"""다음 지시문 계산기 — 단계별 AI 지시문 묶음에서 "지금 열 수 있는 세션"을 고른다.

왜 있는가
- 지시문 묶음(`golden/prompts_phase1~4`)은 README의 「작업별 실행 정보」 표에 작업 번호와
  선행 작업을 적어 둔다. 작업이 끝났는지는
  `golden/reports_phaseN/<번호>/보고.md`의 `결과:` 줄이 말한다.
- 예약 실행(새 클라우드 세션)이 매번 같은 판단을 하도록, 그 둘을 읽어 다음 작업을 계산한다.
  사람이 추측해서 고르지 않는다.

판정 규칙(보수적으로 — 모르면 멈춘다)
- 보고 상태: 보고 없음 = 미착수 · `결과: 완료` = 완료 · `결과: 중단` = 중단(Kiki 결정으로 닫힘) ·
  `결과: 일부 완료` = 일부 완료 · 그 밖의 결과 = 기타 · 보고는 있는데 `결과:` 줄이 없음 = 진행 중.
- 선행을 채우는 것은 완료·중단뿐이다. 일부 완료는 선행을 채우지 않는다
  (공통 규칙 "완료 기준을 못 채우면 같은 번호를 반복").
- 열 수 있는 작업 = 미착수 + 선행 전부 완료·중단.
- 단계 경계: 앞 단계 작업이 전부 완료·중단이고 다음 단계가 하나도 시작되지 않았으면 멈춘다.
  2~4단계는 "시작 조건"(앞 단계 게이트 판정)이 있고, 그 판정을 이 계산기가 대신하지 않는다.
- 작업 종류: `H` 번호이거나 이름이 `-Kiki`로 끝나면 Kiki 작업(사람만 한다). 지시문 할 일에
  `(Kiki)`가 있으면 Kiki 머신 단계가 있는 작업(세션은 런북까지 쓰고 멈춘다). 나머지는 클라우드 작업.

무엇을 하지 않는가
- 열린 PR은 보지 않는다(오프라인 계산). 같은 작업을 두 번 열지 않는 것은 예약 실행 지시문이
  GitHub에서 확인한다.
- 지시문·보고를 고치지 않는다. 읽기만 한다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# 저장소 맨 위(src/backend/golden/driver/next_task.py → 네 단계 위)
REPO = Path(__file__).resolve().parents[4]

# (단계 이름, 지시문 폴더, 보고 폴더) — 실행 순서대로. 5단계는 아직 저장소 지시문 묶음이 아니다
# (golden/inbox에 보관 · 4단계 게이트 뒤 Kiki 결정으로 편입).
PACKS: tuple[tuple[str, str, str], ...] = (
    ("1단계", "golden/prompts_phase1", "golden/reports_phase1"),
    ("2단계", "golden/prompts_phase2", "golden/reports_phase2"),
    ("3단계", "golden/prompts_phase3", "golden/reports_phase3"),
    ("4단계", "golden/prompts_phase4", "golden/reports_phase4"),
)

# 보고 상태
TODO = "미착수"
DONE = "완료"
STOPPED = "중단"
PARTIAL = "일부 완료"
OTHER = "기타"
IN_PROGRESS = "진행 중"
SATISFIED = frozenset({DONE, STOPPED})

# 작업 종류
KIND_KIKI = "kiki"  # 사람만 하는 작업
KIND_KIKI_MACHINE = "kiki_machine"  # Kiki 머신 실행 단계가 있다 — 세션은 런북까지
KIND_CLOUD = "cloud"  # 클라우드 세션이 끝까지 할 수 있다

# 판정 — RUN 열 작업 있음 · WAIT_KIKI 사람 작업뿐 · ATTENTION 진행 중·일부 완료가 막음 ·
# BOUNDARY 단계 경계(Kiki 확인) · ALL_DONE 전부 끝
VERDICTS = frozenset({"RUN", "WAIT_KIKI", "ATTENTION", "BOUNDARY", "ALL_DONE"})

_HEADER = re.compile(r"^\|\s*번호\s*\|\s*세션 이름\s*\|")
_ID = re.compile(r"^[HS]\d+[A-Z]?$")
_RESULT = re.compile(r"^\s*(?:>\s*)?(?:\*\*)?결과\s*[:：]\s*(.*)$")


class NextTaskError(Exception):
    """지시문 묶음을 읽을 수 없다 — 추측하지 않고 거부한다."""


@dataclass
class Task:
    """지시문 하나 = 세션 하나."""

    phase: str
    task_id: str
    name: str
    stage: int
    deps: list[str]
    file: str
    kind: str
    status: str = TODO
    result: str = ""
    blocked_by: list[str] = field(default_factory=list)


def parse_table(readme: Path) -> list[tuple[str, str, int, list[str]]]:
    """README 「작업별 실행 정보」 표 → [(번호, 세션 이름, 단계, 선행)].

    표가 없거나 0줄이면 거부한다.
    """
    lines = readme.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if _HEADER.match(line)), None)
    if start is None:
        raise NextTaskError(f"{readme}: 「작업별 실행 정보」 표 머리줄이 없다")
    rows: list[tuple[str, str, int, list[str]]] = []
    for line in lines[start + 2 :]:  # 머리줄 · 구분줄 다음부터
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not _ID.match(cells[0]):
            raise NextTaskError(f"{readme}: 표 줄을 읽을 수 없다 — {line[:60]!r}")
        deps = [] if cells[4] == "없음" else [d.strip() for d in cells[4].split(",")]
        if not cells[2].isdigit():
            raise NextTaskError(f"{readme}: {cells[0]}의 단계 칸이 숫자가 아니다 — {cells[2]!r}")
        rows.append((cells[0], cells[1], int(cells[2]), deps))
    if not rows:
        raise NextTaskError(f"{readme}: 표에 작업이 0개다 — 스캔이 공허하다")
    return rows


def read_status(report: Path) -> tuple[str, str]:
    """보고 파일 → (상태, 결과 줄 원문). 첫 `결과:` 줄로 판정한다."""
    if not report.is_file():
        return TODO, ""
    for line in report.read_text(encoding="utf-8").splitlines():
        m = _RESULT.match(line)
        if not m:
            continue
        text = m.group(1).strip().lstrip("*").strip()
        if text.startswith("일부 완료"):
            return PARTIAL, text
        if text.startswith("완료"):
            return DONE, text
        if text.startswith("중단"):
            return STOPPED, text
        return OTHER, text
    return IN_PROGRESS, ""


def task_kind(task_id: str, name: str, text: str) -> str:
    """작업 종류 — Kiki 작업 · Kiki 머신 단계 있음 · 클라우드."""
    if task_id.startswith("H") or name.endswith("-Kiki"):
        return KIND_KIKI
    if "(Kiki)" in text:
        return KIND_KIKI_MACHINE
    return KIND_CLOUD


def load_pack(root: Path, phase: str, prompts: str, reports: str) -> list[Task]:
    """한 단계 묶음의 작업 전부(상태 포함)."""
    prompts_dir = root / prompts
    tasks: list[Task] = []
    for task_id, name, stage, deps in parse_table(prompts_dir / "README.md"):
        found = sorted(prompts_dir.glob(f"단계*/{name}.md"))
        if len(found) != 1:
            raise NextTaskError(f"{prompts}: {name}.md가 {len(found)}개다(1개여야 한다)")
        path = found[0]
        status, result = read_status(root / reports / task_id / "보고.md")
        tasks.append(
            Task(
                phase=phase,
                task_id=task_id,
                name=name,
                stage=stage,
                deps=deps,
                file=path.relative_to(root).as_posix(),
                kind=task_kind(task_id, name, path.read_text(encoding="utf-8")),
                status=status,
                result=result,
            )
        )
    return tasks


def plan(root: Path, packs: Sequence[tuple[str, str, str]] = PACKS) -> dict[str, Any]:
    """지금 단계와 열 수 있는 작업을 계산한다."""
    if not packs:
        raise NextTaskError("지시문 묶음 목록이 비었다")
    phases = [(phase, load_pack(root, phase, p, r)) for phase, p, r in packs]
    for phase, tasks in phases:
        ids = {t.task_id for t in tasks}
        for t in tasks:
            unknown = [d for d in t.deps if d not in ids]
            if unknown:
                raise NextTaskError(f"{phase} {t.task_id}: 선행 {unknown}이 같은 단계 표에 없다")

    # 지금 단계 = 끝나지 않은 작업이 있는 첫 단계
    current = next(
        ((ph, ts) for ph, ts in phases if any(t.status not in SATISFIED for t in ts)), None
    )
    if current is None:
        return {"verdict": "ALL_DONE", "phase": None, "runnable": [], "attention": []}
    phase, tasks = current
    by_id = {t.task_id: t for t in tasks}
    for t in tasks:
        t.blocked_by = [d for d in t.deps if by_id[d].status not in SATISFIED]
    started = any(t.status != TODO for t in tasks)
    boundary = phase != phases[0][0] and not started
    runnable = sorted(
        (t for t in tasks if t.status == TODO and not t.blocked_by),
        key=lambda t: (t.stage, t.task_id),
    )
    attention = [t for t in tasks if t.status in (PARTIAL, OTHER, IN_PROGRESS)]
    if boundary:
        verdict = "BOUNDARY"
    elif any(t.kind != KIND_KIKI for t in runnable):
        verdict = "RUN"
    elif runnable:
        verdict = "WAIT_KIKI"  # 열 수 있는 것이 사람 작업뿐
    else:
        verdict = "ATTENTION"  # 진행 중·일부 완료가 길을 막고 있다
    return {
        "verdict": verdict,
        "phase": phase,
        "counts": {
            s: sum(t.status == s for t in tasks)
            for s in (TODO, DONE, STOPPED, PARTIAL, OTHER, IN_PROGRESS)
        },
        "runnable": [asdict(t) for t in runnable],
        "attention": [asdict(t) for t in attention],
    }


def render(result: dict[str, Any]) -> str:
    """사람이 읽는 요약(작업 번호·파일 경로·상태만)."""
    lines = [f"NEXT_TASK verdict={result['verdict']} phase={result['phase']}"]
    for t in result["runnable"]:
        lines.append(f"  열 수 있음 {t['task_id']} [{t['kind']}] {t['file']}")
    for t in result["attention"]:
        extra = f" — {t['result'][:60]}" if t["result"] else ""
        lines.append(f"  주의 {t['task_id']} ({t['status']}){extra}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m golden.driver.next_task [--json]`. 거부는 exit 2."""
    parser = argparse.ArgumentParser(prog="python -m golden.driver.next_task")
    parser.add_argument("--root", default=str(REPO), help="저장소 맨 위(기본: 이 파일 기준)")
    parser.add_argument("--json", action="store_true", help="JSON으로 출력")
    args = parser.parse_args(argv)
    try:
        result = plan(Path(args.root))
    except (NextTaskError, OSError, UnicodeDecodeError) as exc:
        print(f"NEXT_TASK_REFUSED — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=1) if args.json else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
