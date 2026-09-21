#!/usr/bin/env python3
"""작업 보드 — backlog/ 단일 진실 원천을 "한 화면 칸반"으로 렌더한다.

status/brief가 *터미널 요약*이라면 이 모듈은 *전수 가시화*다: 455건 전 태스크를
완료·진행중·다음착수·대기·차단 5열로 배치하고, 스테이지 진행률·사람 게이트·
정합성 경고를 같은 화면에 얹는다.

사용:
    python3 scripts/harness/board.py                    # work/board.html 생성
    python3 scripts/harness/board.py --out <경로>
    python3 scripts/harness/board.py --json             # 페이로드만 표준출력
    python3 scripts/harness/board.py --text             # 터미널 축약 요약만
    python3 scripts/harness/board.py --out <경로> --fragment   # 문서 껍데기 없는 조각 출력

설계 원칙:
    · 판정 로직 무복제 — 착수 가능 여부는 selector.classify_todo, 스테이지 진행률은
      report.stage_progress를 그대로 쓴다(이중 진실원천 금지).
    · 의존성 0 — 표준 라이브러리만. 산출 HTML도 자기완결(외부 CDN·폰트 요청 없음).
    · 읽기 전용 — 백로그 파일을 일절 쓰지 않는다(상태 변경 창구는 backlog.py CLI 단독).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import remote_claims
import report
import selector
import store
from models import Backlog, Gate, Task

# 열 정의 — (열 키, 표시명, 설명). 렌더 순서가 곧 화면 순서다.
COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("in_progress", "진행 중", "지금 누군가(세션)가 claim해 작업 중"),
    ("ready", "다음 착수", "의존성·게이트 전부 해소 — 바로 시작 가능"),
    ("waiting", "대기", "등재됐으나 선행 조건 미해소"),
    ("blocked", "차단", "사유가 붙어 멈춘 상태 — 해제 트리거 필요"),
    ("done", "완료", "증적(PR·커밋) 확인된 종결"),
)

# 대기 사유 코드 → 사람이 읽는 라벨 (selector.Exclusion.reason과 1:1)
WAIT_LABEL: dict[str, str] = {
    "deps": "선행 태스크 대기",
    "gates": "사람 게이트 대기",
    "owner": "사람 소유",
    "track_gate": "트랙 진입 게이트",
    "claimed": "다른 세션 claim",
    "claimed_remote": "원격 claim",
    "path_overlap": "경로 충돌",
    # selector가 내지 않는 축 — 원격 브랜치 사본이 done인 태스크(HARN-11 미머지 done 필터)
    "done_elsewhere": "미머지 완료(다른 브랜치)",
}

_NOTE_MAX = 220  # 카드에 싣는 사유 발췌 상한 (전문은 yaml에 있다)


@dataclass
class BoardTask:
    """보드 카드 1장 — Task에서 화면에 필요한 축만 추린 투영."""

    id: str
    title: str
    column: str
    status: str
    stage: str
    track: str
    layer: str
    subject: str
    priority: int
    owner: str
    updated: str
    session: str | None
    reason: str  # 대기/차단 사유 라벨 (없으면 "")
    detail: str  # 사유 상세 (의존 태스크 id·게이트 id·차단 노트 발췌)
    unlocks: int  # 이 태스크 완료가 해금하는 후속 수
    artifacts: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "column": self.column,
            "status": self.status,
            "stage": self.stage,
            "track": self.track,
            "layer": self.layer,
            "subject": self.subject,
            "priority": self.priority,
            "owner": self.owner,
            "updated": self.updated,
            "session": self.session,
            "reason": self.reason,
            "detail": self.detail,
            "unlocks": self.unlocks,
            "artifacts": self.artifacts,
        }


def _excerpt(text: str, limit: int = _NOTE_MAX) -> str:
    """노트 발췌 — 마지막 [차단 ...] 문단 우선, 없으면 첫 문단(원 사유).

    노트는 시간순으로 뒤에 쌓이므로 최신 차단 사유가 마지막에 온다. 다만 차단 문단이
    하나도 없는 태스크에서 마지막 문단을 집으면 사유가 아닌 부기(복구 불가 기록 등)가
    잡히므로, 그 경우엔 원 사유가 있는 첫 문단으로 되돌린다.
    """
    blocks = [para.strip() for para in text.split("\n\n") if para.strip()]
    chosen = ""
    for para in blocks:
        if para.startswith("[차단") or para.startswith("[블록"):
            chosen = para
    if not chosen:
        chosen = blocks[0] if blocks else ""
    chosen = " ".join(chosen.split())
    return chosen[: limit - 1] + "…" if len(chosen) > limit else chosen


def classify(backlog: Backlog, task: Task) -> tuple[str, str, str]:
    """(열 키, 사유 라벨, 사유 상세) — 열 배치의 단일 판정 지점."""
    if task.status == "done":
        return "done", "", ""
    if task.status == "cancelled":
        return "cancelled", "취소", _excerpt(task.notes)
    if task.status in ("in_progress", "review"):
        label = "검토 대기" if task.status == "review" else ""
        return "in_progress", label, _excerpt(task.notes) if task.status == "review" else ""
    if task.status == "blocked":
        return "blocked", "차단", _excerpt(task.notes)
    exclusion = selector.classify_todo(backlog, task)
    if exclusion is None:
        return "ready", "", ""
    label = WAIT_LABEL.get(exclusion.reason, exclusion.reason)
    return "waiting", label, ", ".join(exclusion.detail)


def build_tasks(backlog: Backlog) -> list[BoardTask]:
    """전 태스크를 카드 투영으로 변환 (열 판정 포함)."""
    cards: list[BoardTask] = []
    for task in backlog.tasks.values():
        column, reason, detail = classify(backlog, task)
        cards.append(
            BoardTask(
                id=task.id,
                title=task.title,
                column=column,
                status=task.status,
                stage=task.stage,
                track=task.track,
                layer=task.layer,
                subject=task.subject,
                priority=task.priority,
                owner=task.owner,
                updated=task.updated,
                session=task.session,
                reason=reason,
                detail=detail,
                unlocks=selector.unblock_count(backlog, task),
                artifacts=list(task.artifacts),
            )
        )
    return cards


def _order_key(backlog: Backlog, card: BoardTask) -> tuple[int, int, int, str]:
    """열 내부 정렬 — next 정렬(스테이지→우선순위→해금수→id)과 동일 규칙."""
    return (
        backlog.stage_index(card.stage),
        card.priority,
        -card.unlocks,
        card.id,
    )


def apply_remote_done(cards: list[BoardTask], remote_done: dict[str, list[str]]) -> None:
    """원격 브랜치에서 이미 done인 태스크를 "다음 착수"에서 빼 대기로 옮긴다 (HARN-11 동형).

    트렁크 사본이 아직 todo인 미머지 완료분을 "예정"으로 보여 주면 중복 구현을 부른다 —
    `backlog.py next`가 같은 이유로 `scan_remote_done` 결과를 후보에서 제외한다. 보드도
    같은 판정을 쓰되, 지우지 않고 **사유를 붙여** 남긴다(무손실 계약).
    """
    for card in cards:
        branches = remote_done.get(card.id)
        if not branches or card.column not in ("ready", "waiting"):
            continue
        card.column = "waiting"
        card.reason = WAIT_LABEL["done_elsewhere"]
        card.detail = ", ".join(branches)


def gate_dependents(
    backlog: Backlog, gate_id: str
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    """이 게이트를 전제로 건 것 — (태스크 목록, 트랙 목록).

    두 경로가 있다: ①태스크가 `requires_gates`로 직접 건 경우 ②트랙 `entry_gate`인 경우
    (E축 하드락처럼 트랙 전체가 잠긴다 — 태스크 쪽에는 아무 표시도 남지 않으므로 이쪽을
    세지 않으면 "아무것도 안 막는 게이트"로 잘못 보인다).

    ⚠ 이 목록은 **의존 관계**이지 "현재 차단"이 아니다. 해소(cleared/waived)된 게이트를
    아직 `requires_gates`에 달고 있는 태스크가 실재하며(실측: G-eos-g0-verification-
    design-freeze ↔ EOS-56), `selector.unmet_gates`는 그 태스크를 착수 가능으로 본다.
    지금 막고 있는지 여부는 `blocks_now`(=게이트가 pending인가)가 말한다 — 이 구분이
    없으면 화면이 "이미 풀린 게이트가 아직 막고 있다"고 거짓말한다.

    태스크 목록의 계산은 `selector.gate_dependent_tasks`(HARN-74) 한 곳이다 — `gates clear`
    화면이 같은 목록을 blocked로 좁혀 쓰므로, 보드와 CLI가 다른 사실을 말하지 않게 한다.
    """
    tasks = [
        {"id": t.id, "title": t.title, "status": t.status}
        for t in selector.gate_dependent_tasks(backlog, gate_id)
    ]
    tracks = [
        {
            "track": key,
            "title": track.title,
            "pending": sum(
                1
                for t in backlog.tasks.values()
                if t.track == key and t.status not in ("done", "cancelled")
            ),
        }
        for key, track in sorted(backlog.tracks.items())
        if track.entry_gate == gate_id
    ]
    return tasks, tracks


def gate_detail(backlog: Backlog, gate: Gate, today: date) -> dict[str, object]:
    """게이트 1건의 카드 + 펼침 상세 — 화면에서 "무엇을 하면 풀리는가"까지 읽히게 한다."""
    days = report._days_pending(gate.requested, today)
    tasks, tracks = gate_dependents(backlog, gate.id)
    return {
        "id": gate.id,
        "title": gate.title,
        "kind": gate.kind,
        "assignee": gate.assignee,
        "status": gate.status,
        "requested": gate.requested,
        "days": days,
        "remind_after_days": gate.remind_after_days,
        "overdue": bool(
            gate.status == "pending"
            and gate.remind_after_days is not None
            and (days or 0) >= gate.remind_after_days
        ),
        "evidence": gate.evidence or "",
        "notes": gate.notes,
        "blocks_now": gate.status == "pending",
        "dependent_tasks": tasks,
        "dependent_tracks": tracks,
    }


def build_board(
    backlog: Backlog,
    errors: list[str],
    today: date,
    *,
    remote_done: dict[str, list[str]] | None = None,
    remote_done_status: str = "skipped",
) -> dict[str, object]:
    """보드 페이로드 — HTML 렌더와 --json이 공유하는 단일 자료구조.

    remote_done: task_id → 그 태스크를 done으로 들고 있는 미머지 브랜치들.
    remote_done_status: 그 스캔의 판정 상태(`ok`/`offline`/`error:*`/`skipped`). `ok`가
        아니면 **판정 불가**이며, 보드가 그 사실을 배너로 드러낸다 — 빈 결과를 "완료분
        없음"으로 읽히게 두면 측정 실패가 통과로 위장된다.
    """
    cards = build_tasks(backlog)
    apply_remote_done(cards, remote_done or {})
    by_column: dict[str, list[BoardTask]] = {key: [] for key, _, _ in COLUMNS}
    by_column["cancelled"] = []
    for card in cards:
        by_column[card.column].append(card)
    for key, items in by_column.items():
        if key == "done":
            # 완료는 최신 갱신 우선 — "무엇을 최근에 끝냈나"가 이 열의 질문이다.
            items.sort(key=lambda c: (c.updated, c.id), reverse=True)
        else:
            items.sort(key=lambda c: _order_key(backlog, c))

    stages = [
        {"stage": stage, "done": done, "total": total}
        for stage, done, total in report.stage_progress(backlog)
    ]
    tracks = {}
    for key, track in backlog.tracks.items():
        members = [c for c in cards if c.track == key]
        tracks[key] = {
            "title": track.title,
            "total": len(members),
            "done": sum(1 for c in members if c.column == "done"),
            "entry_gate": track.entry_gate or "",
        }
    layers: dict[str, dict[str, int]] = {}
    for card in cards:
        bucket = layers.setdefault(card.layer, {"total": 0, "done": 0})
        bucket["total"] += 1
        if card.column == "done":
            bucket["done"] += 1

    gates = [gate_detail(backlog, gate, today) for gate in backlog.gates.values()]
    gates.sort(
        key=lambda g: (g["status"] != "pending", not g["overdue"], -(g["days"] or 0), g["id"])
    )

    counts = {key: len(by_column[key]) for key in by_column}
    return {
        "generated": today.strftime("%Y-%m-%d"),
        "current_stage": report.current_stage(backlog),
        "total": len(cards),
        "counts": counts,
        "columns": [
            {"key": key, "label": label, "hint": hint, "ids": [c.id for c in by_column[key]]}
            for key, label, hint in COLUMNS
        ],
        "stages": stages,
        "tracks": tracks,
        "layers": layers,
        "gates": gates,
        "remote_done_status": remote_done_status,
        "remote_done_count": len(remote_done or {}),
        "errors": errors,
        "tasks": [card.as_dict() for card in cards],
    }


# ── HTML 렌더 ────────────────────────────────────────────────────────────────
# 자기완결 원칙: 외부 CSS/JS/폰트를 일절 요청하지 않는다(오프라인·사내망에서도 열린다).
# 페이로드는 __PAYLOAD__ 자리에 JSON으로 주입한다(.format 미사용 — CSS 중괄호 이스케이프 회피).

_STYLE = """<title>WhyMath 작업 보드</title>
<style>
/* 팔레트 — 중성색에 한랭(청) 편향을 주어 상태색(호박·초록·적)이 또렷하게 뜨게 한다.
   상태색은 액센트와 분리된 의미색이다(진행/착수가능/차단/완료). */
:root{
  --bg:#f4f6f8; --panel:#ffffff; --ink:#131820; --muted:#626d7a; --line:#dfe4ea;
  --chip:#eaeef3; --accent:#2b5bd7;
  --run:#a76310; --ready:#16704a; --wait:#7a8794; --block:#b8342f; --done:#3f7f66;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0d1116; --panel:#151a21; --ink:#e5e9ee; --muted:#94a0ad; --line:#252c35;
    --chip:#1f262e; --accent:#8aa9ff;
    --run:#dda15e; --ready:#55c491; --wait:#8b97a4; --block:#ef7b72; --done:#74b096;
  }
}
:root[data-theme="dark"]{
  --bg:#0d1116; --panel:#151a21; --ink:#e5e9ee; --muted:#94a0ad; --line:#252c35;
  --chip:#1f262e; --accent:#8aa9ff;
  --run:#dda15e; --ready:#55c491; --wait:#8b97a4; --block:#ef7b72; --done:#74b096;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI","Pretendard",
    "Noto Sans KR","Malgun Gothic",sans-serif}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.num{font-variant-numeric:tabular-nums}
.wrap{max-width:1680px;margin:0 auto;padding:22px 20px 64px}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:12px}
h1{font-size:20px;margin:0;letter-spacing:-.015em;font-weight:680}
.sub{color:var(--muted);font-size:12.5px;font-variant-numeric:tabular-nums}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:10px;margin:16px 0}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:11px 13px}
.tile .n{font-size:23px;font-weight:660;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.tile .k{font-size:11.5px;color:var(--muted);letter-spacing:.01em}
.tile.run .n{color:var(--run)} .tile.ready .n{color:var(--ready)}
.tile.block .n{color:var(--block)} .tile.done .n{color:var(--done)}
.bar{height:9px;border-radius:6px;background:var(--chip);overflow:hidden;display:flex}
.bar i{display:block;height:100%}
.bar i.d{background:var(--done)} .bar i.r{background:var(--run)}
.bar i.k{background:var(--block)} .bar i.t{background:var(--wait);opacity:.4}
.section{margin:24px 0 10px;font-size:11.5px;font-weight:660;color:var(--muted);
  text-transform:uppercase;letter-spacing:.09em}
.stages{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px}
.stage{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:9px 11px}
.stage.now{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
.stage b{font-size:13px;letter-spacing:.02em}
.stage .pct{float:right;color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.stage .bar{margin-top:8px;height:6px}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:18px 0 4px;
  background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px}
input,select{background:var(--bg);color:var(--ink);border:1px solid var(--line);
  border-radius:7px;padding:6px 9px;font:inherit;font-size:13px}
input[type=search]{min-width:240px;flex:1}
.hit{color:var(--muted);font-size:12.5px;margin-left:auto;font-variant-numeric:tabular-nums}
.board{display:grid;grid-template-columns:repeat(5,minmax(250px,1fr));gap:12px;margin-top:12px}
@media (max-width:1200px){.board{grid-template-columns:repeat(2,minmax(250px,1fr))}}
@media (max-width:680px){.board{grid-template-columns:1fr}}
/* 열 상단 3px 스트라이프 = 상태 부호화 — 숫자를 읽기 전에 색으로 먼저 읽힌다 */
.col{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  display:flex;flex-direction:column;min-height:120px;overflow:hidden}
.col{border-top:3px solid var(--wait)}
.col.run{border-top-color:var(--run)} .col.ready{border-top-color:var(--ready)}
.col.blocked{border-top-color:var(--block)} .col.done{border-top-color:var(--done)}
.col > h2{margin:0;padding:11px 13px 9px;font-size:13.5px;display:flex;align-items:center;gap:8px;
  border-bottom:1px solid var(--line);font-weight:660}
.col > h2 .dot{width:8px;height:8px;border-radius:50%;background:var(--wait)}
.col > h2 .cnt{margin-left:auto;color:var(--muted);font-weight:500;font-size:12.5px;
  font-variant-numeric:tabular-nums}
.col .hint{padding:7px 13px;color:var(--muted);font-size:11.5px;border-bottom:1px solid var(--line)}
.col .list{padding:9px;display:flex;flex-direction:column;gap:8px;max-height:74vh;overflow-y:auto}
.card{border:1px solid var(--line);border-radius:9px;padding:9px 10px;background:var(--bg)}
.card .t{font-size:12.8px;font-weight:620;line-height:1.42;overflow-wrap:anywhere;
  text-wrap:balance}
.card .id{font-size:10.8px;color:var(--muted);letter-spacing:.01em;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere;margin-bottom:3px}
.card .meta{display:flex;flex-wrap:wrap;gap:4px;margin-top:7px;font-variant-numeric:tabular-nums}
.chip{background:var(--chip);color:var(--muted);border-radius:5px;padding:1px 6px;font-size:10.5px;
  white-space:nowrap}
.chip.p1{color:var(--panel);background:var(--block)}
.chip.p2{color:var(--run);border:1px solid var(--run)}
.chip.unlock{color:var(--ready);border:1px solid var(--ready)}
.card .why{margin-top:7px;font-size:11.5px;color:var(--muted);border-left:2px solid var(--line);
  padding-left:7px;overflow-wrap:anywhere}
.card .why b{color:var(--ink);font-weight:620}
.run .dot{background:var(--run)} .ready .dot{background:var(--ready)}
.blocked .dot{background:var(--block)} .done .dot{background:var(--done)}
.more{margin:2px 9px 10px;padding:6px;border:1px dashed var(--line);border-radius:8px;
  background:transparent;color:var(--muted);font:inherit;font-size:12px;
  cursor:pointer;width:calc(100% - 18px)}
.more:hover{border-color:var(--accent);color:var(--accent)}
.gates{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:9px;
  align-items:start}
.gate{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--wait);
  border-radius:9px}
.gate.overdue{border-left-color:var(--block)}
.gate.cleared{border-left-color:var(--done)}
.gate > summary{padding:9px 11px;cursor:pointer;list-style:none;display:block}
.gate > summary::-webkit-details-marker{display:none}
.gate > summary::after{content:"펼치기 ▾";float:right;font-size:10.5px;color:var(--muted);
  margin-left:8px}
.gate[open] > summary::after{content:"접기 ▴"}
.gate > summary:hover{background:var(--chip);border-radius:6px}
.gate .g{font-size:10.8px;color:var(--muted);font-family:ui-monospace,Menlo,monospace}
.gate .gt{margin-top:4px;font-size:12.5px;overflow-wrap:anywhere}
.gate .d{float:right;font-size:11.5px;color:var(--block);font-variant-numeric:tabular-nums}
.gate .body{padding:2px 11px 11px;border-top:1px solid var(--line);margin-top:2px}
.gate .body h4{margin:11px 0 5px;font-size:10.5px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.08em;font-weight:660}
.gate .body .meta{display:flex;flex-wrap:wrap;gap:4px}
.gate .body ul{margin:0;padding-left:16px;font-size:12px}
.gate .body li{margin:2px 0}
.gate .note{white-space:pre-wrap;overflow-wrap:anywhere;max-height:280px;overflow:auto;margin:0;
  background:var(--bg);border:1px solid var(--line);border-radius:7px;padding:8px 9px;
  font:11.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}
.gate .cmd{display:block;background:var(--bg);border:1px solid var(--line);border-radius:7px;
  padding:7px 9px;font-size:11px;overflow-x:auto;white-space:pre;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.gate .none{font-size:11.5px;color:var(--muted)}
.resolved{margin-top:12px}
.resolved > summary{cursor:pointer;font-size:12.5px;color:var(--muted);padding:6px 0}
.notice{margin:14px 0 0;background:var(--panel);border:1px solid var(--line);
  border-left:3px solid var(--run);border-radius:9px;padding:9px 12px;font-size:12.5px}
.notice.stale{border-left-color:var(--block)}
.notice b{font-weight:660}
.err{background:var(--panel);border:1px solid var(--block);border-radius:9px;padding:10px 12px;
  color:var(--block);font-size:12.5px}
footer{margin-top:30px;color:var(--muted);font-size:11.5px;line-height:1.75}
code{background:var(--chip);border-radius:4px;padding:1px 5px;font-size:11.5px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
</style>
"""

# 문서 본문 — 마크업 + 렌더 스크립트. __PAYLOAD__ 자리에 JSON이 주입된다.
_CONTENT = """<div class="wrap">
  <header>
    <h1>WhyMath 작업 보드</h1>
    <span class="sub" id="hdr"></span>
  </header>
  <div id="notice"></div>
  <div class="tiles" id="tiles"></div>

  <div class="section">스테이지 진행률</div>
  <div class="stages" id="stages"></div>

  <div class="filters">
    <input type="search" id="q" placeholder="제목·ID·브랜치 검색">
    <select id="fstage"></select>
    <select id="flayer"></select>
    <select id="ftrack"></select>
    <select id="fsubject"></select>
    <span class="hit" id="hit"></span>
  </div>

  <div class="board" id="board"></div>

  <div class="section" id="gates-title">사람 게이트 — 행동 대기</div>
  <div class="gates" id="gates"></div>
  <div id="gates-resolved"></div>

  <div id="errbox"></div>

  <footer>
    정본: <code>backlog/</code> (태스크 YAML) · 이 파일은
    <code>python3 scripts/harness/board.py</code> 재실행으로 갱신한다 (읽기 전용 — 상태 변경은
    <code>backlog.py</code> CLI 단독).<br>
    열 판정은 <code>selector.classify_todo</code>, 스테이지 진행률은
    <code>report.stage_progress</code>를 그대로 사용한다 — 보드는 판정을 복제하지 않는다.
  </footer>
</div>
<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const DATA = JSON.parse(document.getElementById('payload').textContent);
const TASKS = new Map(DATA.tasks.map(t => [t.id, t]));
const COLCLASS = {in_progress:'run', ready:'ready', waiting:'waiting',
  blocked:'blocked', done:'done'};
const PAGE = 40;
const shown = {};
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function head() {
  const c = DATA.counts;
  const pct = DATA.total ? Math.round(c.done / DATA.total * 100) : 0;
  document.getElementById('hdr').textContent = `${DATA.generated} 기준 · 현재 스테이지 `
    + `${DATA.current_stage} · 전체 ${DATA.total}건 · 완료 ${pct}%`;
  const tiles = [
    ['done', '완료', c.done, 'done'],
    ['in_progress', '진행 중', c.in_progress, 'run'],
    ['ready', '다음 착수 가능', c.ready, 'ready'],
    ['waiting', '대기', c.waiting, ''],
    ['blocked', '차단', c.blocked, 'block'],
    ['cancelled', '취소', c.cancelled || 0, ''],
  ];
  document.getElementById('tiles').innerHTML = tiles.map(([k, label, n, cls]) =>
    `<div class="tile ${cls}"><div class="n">${n}</div>`
    + `<div class="k">${label}</div></div>`).join('') +
    `<div class="tile" style="grid-column:span 2">
       <div class="k" style="margin-bottom:6px">전체 진척 (완료/진행/차단/대기)</div>
       <div class="bar">
         <i class="d" style="width:${c.done / DATA.total * 100}%"></i>
         <i class="r" style="width:${c.in_progress / DATA.total * 100}%"></i>
         <i class="k" style="width:${c.blocked / DATA.total * 100}%"></i>
         <i class="t" style="width:${(c.ready + c.waiting) / DATA.total * 100}%"></i>
       </div></div>`;
  document.getElementById('stages').innerHTML = DATA.stages.map(s => {
    const pct = s.total ? Math.round(s.done / s.total * 100) : 0;
    const now = s.stage === DATA.current_stage ? ' now' : '';
    return `<div class="stage${now}"><b>${esc(s.stage)}</b>
      <span class="pct">${s.done}/${s.total}</span>
      <div class="bar"><i class="d" style="width:${pct}%"></i></div></div>`;
  }).join('');
  renderGates();
  const st = DATA.remote_done_status;
  const notice = document.getElementById('notice');
  if (st !== 'ok') {
    notice.innerHTML = `<div class="notice stale"><b>미머지 완료 판정 불가 (${esc(st)})</b> — `
      + `"다음 착수"에 다른 브랜치에서 이미 끝난 작업이 섞여 있을 수 있다. `
      + `착수 전 <code>backlog.py start &lt;id&gt;</code>로 재확인할 것.</div>`;
  } else if (DATA.remote_done_count) {
    notice.innerHTML = `<div class="notice"><b>미머지 완료 ${DATA.remote_done_count}건</b> — `
      + `다른 브랜치에서 끝났으나 아직 머지되지 않은 태스크를 "다음 착수"에서 빼 `
      + `대기 열에 사유와 함께 표기했다.</div>`;
  }
  if (DATA.errors.length) {
    document.getElementById('errbox').innerHTML =
      `<div class="section">정합성 경고</div>`
      + `<div class="err">${DATA.errors.map(esc).join('<br>')}</div>`;
  }
}

function gateBody(g) {
  const meta = [
    `<span class="chip">${esc(g.kind)}</span>`,
    `<span class="chip">담당 ${esc(g.assignee)}</span>`,
    g.requested ? `<span class="chip">요청 ${esc(g.requested)}</span>` : '',
    g.remind_after_days != null
      ? `<span class="chip">리마인드 ${g.remind_after_days}일 경과 시</span>` : '',
    `<span class="chip">${esc(g.status)}</span>`,
  ].join('');

  const deps = [];
  g.dependent_tracks.forEach(t => deps.push(g.blocks_now
    ? `트랙 <b>${esc(t.title)}</b> 전체 잠금 — 이 게이트 전까지 착수 불가한 미완 ${t.pending}건`
    : `트랙 <b>${esc(t.title)}</b> — 이 게이트를 진입 조건으로 걸었다 (미완 ${t.pending}건)`));
  g.dependent_tasks.forEach(t => deps.push(`<code>${esc(t.id)}</code> ${esc(t.title)}`));
  const depTitle = g.blocks_now
    ? '이 게이트가 막고 있는 것'
    : '이 게이트를 전제로 걸었던 것 (해소됨 — 지금은 차단하지 않는다)';
  const depHtml = deps.length
    ? `<ul>${deps.map(b => `<li>${b}</li>`).join('')}</ul>`
    : `<div class="none">이 게이트를 <code>requires_gates</code>로 건 태스크도, `
      + `진입 게이트로 쓰는 트랙도 없다 — 스케줄러를 막지는 않는 운영·법무 축 항목이다.</div>`;

  const noteHtml = g.notes
    ? `<pre class="note">${esc(g.notes)}</pre>`
    : `<div class="none">노트 없음 — 위 제목이 내용 전부다.</div>`;

  const evidenceHtml = g.status === 'pending' ? '' :
    `<h4>근거 (evidence)</h4><div class="none">${esc(g.evidence || '기록 없음')}</div>`;

  // HARN-60: 이 명령은 **사람이 복사해서 실행**하는 경로다. `--as`를 빼고 안내하면 Kiki가
  // 실행한 clear가 대장에 `cleared_by: claude`로 남는다 — 기록이 없는 것보다 나쁘다(거짓
  // 주체가 쌓인다). 그러므로 게이트의 담당자를 그대로 플래그에 실어 준다. 담당자가 claude면
  // (에이전트 소유 게이트) 플래그를 붙이지 않는다 — `--as claude`는 선택지 자체가 아니다.
  const asFlag = g.assignee && g.assignee !== 'claude' ? ` --as ${g.assignee}` : '';
  const cmd = g.status === 'pending'
    ? `python3 scripts/harness/backlog.py gates clear ${g.id}${asFlag} --evidence "&lt;근거&gt;"`
    : `python3 scripts/harness/backlog.py gates list`;

  return `<div class="body">
    <h4>메타</h4><div class="meta">${meta}</div>
    <h4>${depTitle}</h4>${depHtml}
    <h4>상세 노트</h4>${noteHtml}
    ${evidenceHtml}
    <h4>해소</h4><code class="cmd">${cmd}</code></div>`;
}

function gateCard(g) {
  const cls = g.status === 'pending' ? (g.overdue ? ' overdue' : '') : ' cleared';
  const badge = g.status === 'pending'
    ? (g.days != null ? `<span class="d">${g.days}일 경과</span>` : '')
    : `<span class="d" style="color:var(--done)">${esc(g.status)}</span>`;
  return `<details class="gate${cls}">
    <summary><span class="g">${esc(g.id)}</span>${badge}
      <div class="gt">${esc(g.title)}</div></summary>
    ${gateBody(g)}
  </details>`;
}

function renderGates() {
  const pending = DATA.gates.filter(g => g.status === 'pending');
  const resolved = DATA.gates.filter(g => g.status !== 'pending');
  const overdue = pending.filter(g => g.overdue).length;
  document.getElementById('gates-title').textContent = `사람 게이트 — 행동 대기 ${pending.length}건`
    + (overdue ? ` (리마인드 초과 ${overdue}건)` : '');
  document.getElementById('gates').innerHTML =
    pending.map(gateCard).join('') || '<div class="sub">대기 중인 게이트 없음</div>';
  document.getElementById('gates-resolved').innerHTML = resolved.length
    ? `<details class="resolved"><summary>해소된 게이트 ${resolved.length}건 보기 `
      + `(cleared·waived — 근거 포함)</summary>`
      + `<div class="gates" style="margin-top:8px">${resolved.map(gateCard).join('')}</div>`
      + `</details>`
    : '';
}

function fillFilters() {
  const uniq = key => [...new Set(DATA.tasks.map(t => t[key]))].sort();
  const opts = (el, label, values) => {
    el.innerHTML = `<option value="">${label} 전체</option>` +
      values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
  };
  opts(document.getElementById('fstage'), '스테이지', DATA.stages.map(s => s.stage));
  opts(document.getElementById('flayer'), '레이어', uniq('layer'));
  opts(document.getElementById('ftrack'), '트랙', uniq('track'));
  opts(document.getElementById('fsubject'), '과목', uniq('subject'));
}

function match(t) {
  const q = document.getElementById('q').value.trim().toLowerCase();
  const hay = (t.id + ' ' + t.title + ' ' + (t.session || '')).toLowerCase();
  if (q && !hay.includes(q)) return false;
  const axes = [['fstage','stage'], ['flayer','layer'], ['ftrack','track'],
    ['fsubject','subject']];
  for (const [id, key] of axes) {
    const v = document.getElementById(id).value;
    if (v && t[key] !== v) return false;
  }
  return true;
}

function card(t) {
  const chips = [`<span class="chip">${esc(t.stage)}</span>`,
    `<span class="chip">${esc(t.layer)}</span>`];
  if (t.priority <= 2) chips.push(`<span class="chip p${t.priority}">P${t.priority}</span>`);
  if (t.unlocks > 0 && t.column !== 'done') {
    chips.push(`<span class="chip unlock">후속 ${t.unlocks}건 해금</span>`);
  }
  if (t.owner !== 'claude') chips.push(`<span class="chip">owner ${esc(t.owner)}</span>`);
  if (t.updated) chips.push(`<span class="chip">${esc(t.updated)}</span>`);
  const why = [];
  if (t.session) why.push(`<b>브랜치</b> ${esc(t.session)}`);
  if (t.reason) why.push(`<b>${esc(t.reason)}</b>` + (t.detail ? ' — ' + esc(t.detail) : ''));
  else if (t.detail) why.push(esc(t.detail));
  return `<div class="card"><div class="id">${esc(t.id)}</div>
    <div class="t">${esc(t.title)}</div>
    <div class="meta">${chips.join('')}</div>
    ${why.length ? `<div class="why">${why.join('<br>')}</div>` : ''}</div>`;
}

function render() {
  let hits = 0;
  document.getElementById('board').innerHTML = DATA.columns.map(col => {
    const items = col.ids.map(id => TASKS.get(id)).filter(match);
    hits += items.length;
    const limit = shown[col.key] || PAGE;
    const rest = items.length - limit;
    return `<section class="col ${COLCLASS[col.key]}">
      <h2><span class="dot"></span>${esc(col.label)}<span class="cnt">${items.length}</span></h2>
      <div class="hint">${esc(col.hint)}</div>
      <div class="list">${items.slice(0, limit).map(card).join('') ||
        '<div class="sub" style="padding:6px">해당 없음</div>'}</div>
      ${rest > 0 ? `<button class="more" data-col="${col.key}">+ ${rest}건 더 보기</button>` : ''}
    </section>`;
  }).join('');
  const placed = DATA.columns.reduce((n, c) => n + c.ids.length, 0);
  const off = DATA.total - placed;
  document.getElementById('hit').textContent =
    `표시 ${hits}건 / 보드 ${placed}건` + (off ? ` (취소 ${off}건 제외)` : '');
  document.querySelectorAll('.more').forEach(b => b.onclick = () => {
    shown[b.dataset.col] = (shown[b.dataset.col] || PAGE) + 200;
    render();
  });
}

head();
fillFilters();
render();
['q', 'fstage', 'flayer', 'ftrack', 'fsubject'].forEach(id => {
  document.getElementById(id).addEventListener('input', render);
});
</script>
"""

# 완전 문서 껍데기 — 조각(fragment) 모드는 이 껍데기 없이 _STYLE + _CONTENT만 낸다
# (아티팩트 호스트처럼 <head>/<body>를 스스로 두르는 소비처를 위한 출력).
_DOCUMENT = (
    '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "{style}\n</head>\n<body>\n{content}</body>\n</html>\n"
)


def render_html(payload: dict[str, object], *, fragment: bool = False) -> str:
    """페이로드를 자기완결 HTML로 렌더.

    fragment=True면 <html>/<head>/<body> 껍데기를 생략하고 <title>+<style>+본문만 낸다
    (문서 골격을 스스로 두르는 호스트에 그대로 삽입하기 위한 출력).
    """
    # </script> 조기 종료 방지 — JSON 안의 '<'를 이스케이프한다.
    blob = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    content = _CONTENT.replace("__PAYLOAD__", blob)
    if fragment:
        return _STYLE + "\n" + content
    return _DOCUMENT.format(style=_STYLE, content=content)


def render_text(payload: dict[str, object]) -> str:
    """터미널 요약 — HTML을 열 수 없는 환경(SSH·CI 로그)용 같은 데이터의 축약본."""
    counts = payload["counts"]
    lines = [
        f"📋 WhyMath 작업 보드 — {payload['generated']} 기준 "
        f"(현재 스테이지 {payload['current_stage']} · 전체 {payload['total']}건)",
        "",
        f"  완료 {counts['done']} · 진행 중 {counts['in_progress']} · 다음 착수 {counts['ready']} "
        f"· 대기 {counts['waiting']} · 차단 {counts['blocked']} · 취소 {counts['cancelled']}",
    ]
    status = payload["remote_done_status"]
    if status == "ok" and payload["remote_done_count"]:
        lines.append(
            f"  ⚠ 미머지 완료 {payload['remote_done_count']}건 — 다음 착수에서 빼 대기로 표기"
        )
    elif status != "ok":
        lines.append(f"  ⚠ 미머지 완료 판정 불가({status}) — 다음 착수에 완료분이 섞였을 수 있음")
    tasks = {t["id"]: t for t in payload["tasks"]}
    for column in payload["columns"]:
        if column["key"] == "done":
            continue
        ids = column["ids"][:8]
        if not ids:
            continue
        lines.append("")
        lines.append(f"── {column['label']} ({len(column['ids'])}건) ──")
        for tid in ids:
            task = tasks[tid]
            tail = f" [{task['reason']}]" if task["reason"] else ""
            lines.append(f"  · {tid}{tail}")
        if len(column["ids"]) > len(ids):
            lines.append(f"  … 외 {len(column['ids']) - len(ids)}건")
    return "\n".join(lines)


def scan_unmerged_done(
    root: Path, backlog: Backlog, *, skip: bool = False
) -> tuple[dict[str, list[str]], str]:
    """미머지 완료분 조회 — {task_id: [브랜치…]} 와 판정 상태.

    `fetch=False`라 **이미 있는 remote-tracking ref만** 본다(네트워크 0 — 보드는 오프라인
    에서도 돌아야 한다). 그만큼 마지막 fetch 시점 기준으로 stale할 수 있고, 조회가 실패하면
    빈 결과가 아니라 상태 문자열로 그 사실이 남는다.
    """
    todo_ids = [t.id for t in backlog.tasks.values() if t.status == "todo"]
    if skip:
        return {}, "skipped"
    if not todo_ids:
        return {}, "ok"
    policy, _ = store.load_policy(root)
    if not policy.remote_claims:
        return {}, "disabled"
    done_map, status = remote_claims.scan_remote_done(root, todo_ids)
    return {tid: [f.branch for f in finishers] for tid, finishers in done_map.items()}, status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="backlog/ 작업 보드 생성 (읽기 전용)")
    parser.add_argument(
        "--out", default="work/board.html", help="HTML 출력 경로 (기본 work/board.html)"
    )
    parser.add_argument("--json", action="store_true", help="HTML 대신 페이로드 JSON을 표준출력")
    parser.add_argument("--text", action="store_true", help="터미널 축약 요약 출력")
    parser.add_argument(
        "--fragment",
        action="store_true",
        help="문서 껍데기(<html>/<head>/<body>) 없이 title+style+본문만 출력",
    )
    parser.add_argument(
        "--no-remote",
        action="store_true",
        help="원격 미머지 done 스캔 생략 (판정 불가로 표기된다 — 숨기지 않는다)",
    )
    args = parser.parse_args(argv)

    root = store.find_repo_root()
    backlog, schema_errors = store.load_backlog(root)
    errors = store.validate_backlog(backlog, schema_errors)
    remote_done, remote_done_status = scan_unmerged_done(root, backlog, skip=args.no_remote)
    payload = build_board(
        backlog,
        errors,
        date.today(),
        remote_done=remote_done,
        remote_done_status=remote_done_status,
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.text:
        print(render_text(payload))
        return 0

    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(payload, fragment=args.fragment), encoding="utf-8")
    print(render_text(payload))
    print("")
    print(f"🗂  보드 생성: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
