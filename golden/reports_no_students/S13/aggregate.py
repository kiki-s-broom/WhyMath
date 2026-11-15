"""S13 로그 분석 집계 — 문제 단위 기록 · 끊김 태깅 · 출처별 표 · 전수 재채점.

실행(저장소 루트에서, 골든 백엔드가 import되는 가상환경으로):
    /opt/golden-venv/bin/python golden/reports_no_students/S13/aggregate.py

읽는 것
- 사람 출처 원본(gitignore · Kiki 머신과 세션 컨테이너에만 있음):
  golden/logs/self1_turns.csv · adult1_turns.csv · adult2_turns.csv
- AI 시뮬레이션(저장소에 사본이 있음): S11 1차·r2 · S12 재실행 CSV
쓰는 것
- golden/logs/s13_turns_labeled.csv — 모든 턴에 출처 라벨을 붙인 전체 표(사람 원문 포함 → gitignore)
- golden/reports_no_students/S13/problems.csv — 문제 단위 집계(원문 없음 · 줄 번호만)
- golden/reports_no_students/S13/stage_by_source.csv · item_by_source.csv
- golden/reports_no_students/S13/judging_errors.csv — 판정 오류(계약상 정답인데 오답 처리된 입력)
- golden/reports_no_students/S13/regrade.csv — 전수 재채점(서버 판정 vs 지금 grade.py)

이 스크립트는 분석용이다. 골든 경로 코드(api·grade·tutor·store)를 바꾸지 않고
grade.is_correct만 부른다.
닉네임·session_id는 원본 CSV에 처음부터 없다. 피험자는 아래 LABEL로만 부른다.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "backend"))

from golden import grade  # noqa: E402  (경로를 넣은 뒤 import)

OUT = ROOT / "golden" / "reports_no_students" / "S13"
LOGS = ROOT / "golden" / "logs"
S11 = ROOT / "golden" / "reports_no_students" / "S11"
S12 = ROOT / "golden" / "reports_no_students" / "S12"

PROBLEMS = {
    p["id"]: p
    for p in json.loads((ROOT / "golden/data/problems_linear_fn.json").read_text("utf-8"))
}

# ── 데이터 묶음 정의 ────────────────────────────────────────────────
# (출처, 라벨, 실행, S10 전/후, 묶음[본=지시서 누적 기준 / 참고], 파일, id 범위 또는 None)
SETS = [
    ("본인", "self-1", "S9", "전", "본", LOGS / "self1_turns.csv", None),
    ("성인", "adult-1", "S12", "후", "본", LOGS / "adult1_turns.csv", (80, 84)),
    ("성인", "adult-2", "S12", "후", "본", LOGS / "adult2_turns.csv", (118, 122)),
    ("AI", "sim-slope-blind", "S11-1차", "전", "본", S11 / "sim_slope-blind_turns.csv", None),
    ("AI", "sim-sign-slip", "S11-1차", "전", "본", S11 / "sim_sign-slip_turns.csv", None),
    ("AI", "sim-no-setup", "S11-1차", "전", "본", S11 / "sim_no-setup_turns.csv", None),
    (
        "AI",
        "sim-slope-blind",
        "S12-재실행",
        "후",
        "본",
        S12 / "sim_slope-blind_rerun_turns.csv",
        None,
    ),
    ("AI", "sim-sign-slip", "S12-재실행", "후", "본", S12 / "sim_sign-slip_rerun_turns.csv", None),
    ("AI", "sim-no-setup", "S12-재실행", "후", "본", S12 / "sim_no-setup_rerun_turns.csv", None),
    # 참고 묶음 — 순위 계산에 넣지 않는다
    ("본인", "self-norole", "S12", "후", "참고", LOGS / "adult1_turns.csv", (37, 79)),
    ("성인", "adult-1", "S12", "후", "참고", LOGS / "adult1_turns.csv", (85, 115)),
    ("성인", "adult-2", "S12", "후", "참고", LOGS / "adult2_turns.csv", (123, 147)),
    (
        "AI",
        "sim-slope-blind-r2",
        "S11-r2",
        "전",
        "참고",
        S11 / "sim_slope-blind_r2_turns.csv",
        None,
    ),
]

# 표에 쓰는 묶음 이름(출처 + S10 전/후). 세 출처를 합친 숫자는 만들지 않는다.
GROUP_ORDER = [
    ("본", "본인 · S10 전(S9)"),
    ("본", "성인 · S10 후(S12)"),
    ("본", "AI · S10 전(S11 1차)"),
    ("본", "AI · S10 후(S12 재실행)"),
    ("참고", "본인 역할 규칙 없음 · S10 후(S12)"),
    ("참고", "성인 6~30번째 · S10 후(S12)"),
    ("참고", "AI 막히면 재실행 · S10 전(S11 r2)"),
]


def group_name(src: str, run: str, s10: str, bundle: str, label: str) -> str:
    """기록 1건이 어느 표 묶음에 들어가는지 정한다."""
    if bundle == "본":
        if src == "본인":
            return "본인 · S10 전(S9)"
        if src == "성인":
            return "성인 · S10 후(S12)"
        return "AI · S10 전(S11 1차)" if s10 == "전" else "AI · S10 후(S12 재실행)"
    if label == "self-norole":
        return "본인 역할 규칙 없음 · S10 후(S12)"
    if src == "성인":
        return "성인 6~30번째 · S10 후(S12)"
    return "AI 막히면 재실행 · S10 전(S11 r2)"


# ── 손 판정(되묻기 루브릭 C4·C5 · 하위 질문 · 학생 쪽 원인) ──────────────
# 키 = (실행, 라벨, 문제). 값의 gp4 = [(튜터 턴 번호, 종류, 근거 줄)],
# fallback = 시스템 사건이 없을 때의 분류.
# 근거 줄 = 그 원본 CSV의 줄 번호(머리줄 = 1행). 판정 기준은 S9 되묻기_루브릭.md의 C4·C5.
HAND: dict[tuple[str, str, str], dict[str, object]] = {
    # 본인 S9 — S9 보고 턴별 판정표와 같은 판정
    ("S9", "self-1", "LF-03"): {"gp4": [(3, "C5 오류 미겨냥(마지막 되묻기)", "9행")]},
    ("S9", "self-1", "LF-05"): {"gp4": [(1, "C4 대입 대신", "14행"), (3, "C4 계산 대신", "16행")]},
    # AI S11 1차 — GP-5 사건이 없는 끊김만 여기서 정한다
    ("S11-1차", "sim-sign-slip", "LF-06"): {
        "fallback": "학생 쪽(오개념 고수 · 튜터 3턴 모두 겨냥)"
    },
    ("S11-1차", "sim-sign-slip", "LF-09"): {
        "fallback": "학생 쪽(오개념 고수 · 튜터 3턴 모두 겨냥)"
    },
    ("S11-1차", "sim-sign-slip", "LF-10"): {
        "fallback": "학생 쪽(오개념 고수 · 튜터 3턴 모두 겨냥)"
    },
    ("S11-1차", "sim-no-setup", "LF-01"): {"fallback": "학생 쪽(오개념 고수 · 튜터 3턴 모두 겨냥)"},
    ("S11-1차", "sim-no-setup", "LF-06"): {
        "gp4": [(3, "하위 질문을 마지막에 물음(S10 전 규칙)", "24행")]
    },
    ("S11-1차", "sim-no-setup", "LF-10"): {
        "gp4": [(3, "하위 질문을 마지막에 물음(S10 전 규칙)", "40행")]
    },
    # AI S12 재실행(S10 후)
    ("S12-재실행", "sim-sign-slip", "LF-01"): {
        "gp4": [(3, "C5 오류 미겨냥(마지막 되묻기)", "4행")]
    },
    ("S12-재실행", "sim-sign-slip", "LF-02"): {
        "gp4": [(3, "C5 오류 미겨냥(마지막 되묻기)", "8행")]
    },
    ("S12-재실행", "sim-sign-slip", "LF-09"): {"gp4": [(1, "C5 오류 미겨냥(첫 되묻기)", "21행")]},
    ("S12-재실행", "sim-sign-slip", "LF-10"): {
        "gp4": [(3, "C5 오류 미겨냥(마지막 되묻기)", "27행")]
    },
    ("S12-재실행", "sim-no-setup", "LF-01"): {"fallback": "GP-2"},
    ("S12-재실행", "sim-no-setup", "LF-02"): {"fallback": "GP-2"},
    ("S12-재실행", "sim-no-setup", "LF-04"): {"fallback": "GP-2"},
    ("S12-재실행", "sim-no-setup", "LF-06"): {"fallback": "GP-2"},
    ("S12-재실행", "sim-no-setup", "LF-07"): {"fallback": "GP-2"},
    # 참고 묶음
    ("S12", "self-norole", "LF-14"): {"gp4": [(3, "C5 오류 미겨냥(마지막 되묻기)", "21행")]},
    ("S12", "self-norole", "LF-20"): {"fallback": "미분류(긴 쉼 6시간 · 원인이 로그에 없음)"},
    ("S11-r2", "sim-slope-blind-r2", "LF-06"): {
        "gp4": [(3, "하위 질문을 마지막에 물음(S10 전 규칙)", "24행")]
    },
    ("S11-r2", "sim-slope-blind-r2", "LF-07"): {
        "gp4": [(3, "하위 질문을 마지막에 물음(S10 전 규칙)", "28행")]
    },
}

# 관찰 기록(끊김 ④)의 상태 — 로그 밖 자료라 출처별로 고정한다
OBS = {
    "본인": "실제 막힘 0(S9 보고: 막힌 척 5건은 역할 계획표의 연기)",
    "성인": "미측정(Kiki 결정 2026-11-14: 관찰 메모 없음)",
    "AI": "해당 없음(관찰자 없음)",
}

_RUN = re.compile(r"[0-9x+\-*/^().=\s]+")
# 값 = 수 하나(정수·소수·분수 `-3/2`·`-(9/6)`). 그 밖의 연산이 남아 있으면 '식'(계산 전 식)
_PLAIN_NUMBER = re.compile(r"-?\(?-?\d+(\.\d+)?(/\d+(\.\d+)?)?\)?")


def last_math_run(text: str) -> str | None:
    """학생 입력에서 숫자가 든 마지막 수식 조각을 꺼낸다(앞말·꼬리가 붙은 문장의 '주장한 값')."""
    s = unicodedata.normalize("NFKC", text).translate(grade._SYMBOL_MAP)  # noqa: SLF001
    # 앞말 `음...`·`어...`의 점이 조각에 붙지 않게 양끝 공백·점을 뗀다
    # (소수점 `-0.67`은 가운데라 남는다)
    runs = [r.strip(" .") for r in _RUN.findall(s) if re.search(r"\d", r)]
    return runs[-1] if runs else None


def value_or_expr(text: str) -> str:
    """판정에 쓰인 부분이 수 하나(값)인지 계산 전 식(식)인지."""
    s = grade.normalize(text)
    return "값" if _PLAIN_NUMBER.fullmatch(s) else "식"


def contract_correct(pid: str, text: str) -> tuple[bool, str, str]:
    """계약상 정답인가 → (정답 여부, 어떻게 알았나, 값/식).

    ① 지금 grade.is_correct가 입력 전체를 정답으로 보면 '지금 채점기로 정답'.
    ② 아니면 입력의 마지막 수식 조각만 채점해 본다 — 앞말이 붙은 문장('f(3)은 -8이에요')이
       여기서 잡힌다.
    """
    p = PROBLEMS[pid]
    if grade.is_correct(p, text):
        return True, "지금 채점기로 정답", value_or_expr(text)
    run = last_math_run(text)
    if run and grade.is_correct(p, run):
        return True, "마지막 수식 조각이 정답(지금도 거부)", value_or_expr(run)
    return False, "", ""


def ts(s: str) -> datetime:
    """CSV 시각 문자열을 datetime으로(두 형식 '+00'·'+00:00' 모두)."""
    s = s.strip()
    if s.endswith("+00"):
        s += ":00"
    return datetime.fromisoformat(s)


def load() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """모든 묶음을 읽어 턴 목록과 문제 단위 기록 목록을 만든다."""
    turns: list[dict[str, object]] = []
    problems: list[dict[str, object]] = []
    for src, label, run, s10, bundle, path, idr in SETS:
        rows = []
        for line_no, r in enumerate(csv.DictReader(path.open(encoding="utf-8")), start=2):
            if idr and not (idr[0] <= int(r["id"]) <= idr[1]):
                continue
            correct = r["correct"].strip().lower() in ("t", "true")
            rows.append({**r, "line": line_no, "correct_b": correct})
        grp = group_name(src, run, s10, bundle, label)
        # 문제 단위로 자른다 — graded 행이 한 문제의 끝
        episode: list[dict[str, object]] = []
        prev_graded_at: datetime | None = None
        for r in rows:
            episode.append(r)
            if r["kind"] != "graded":
                continue
            pid = str(r["problem_id"])
            inputs = [str(e["student_text"]) for e in episode]
            judged = []  # 판정 오류 입력(계약상 정답인데 서버가 오답 처리)
            for k, e in enumerate(episode, start=1):
                ok, how, ve = contract_correct(pid, str(e["student_text"]))
                now = grade.is_correct(PROBLEMS[pid], str(e["student_text"]))
                turns.append(
                    {
                        "출처": src,
                        "피험자": label,
                        "실행": run,
                        "S10": s10,
                        "묶음": bundle,
                        "파일": path.name,
                        "줄": e["line"],
                        "id": e["id"],
                        "문제": pid,
                        "입력순서": k,
                        "kind": e["kind"],
                        "서버판정": "정답" if e["correct_b"] else "오답",
                        "지금재채점": "정답" if now else "오답",
                        "계약상정답": "예" if ok else "아니오",
                        "student_text": e["student_text"],
                        "tutor_text": e["tutor_text"],
                        "created_at": e["created_at"],
                    }
                )
                if ok and not e["correct_b"]:
                    judged.append((k, how, ve, e["line"], str(e["student_text"])))
            first_at = ts(str(episode[0]["created_at"]))
            graded_at = ts(str(r["created_at"]))
            dur = (graded_at - first_at).total_seconds()
            gap = (graded_at - prev_graded_at).total_seconds() if prev_graded_at else None
            prev_graded_at = graded_at
            tutor_turns = sum(1 for e in episode if e["kind"] == "tutor_turn")
            dontknow = sum("모르겠" in s for s in inputs)
            tags = []
            if not r["correct_b"] and tutor_turns == 3:
                tags.append("①")
            if dur >= 300:
                tags.append("②")
            if dontknow >= 2:
                tags.append("③")
            hand = HAND.get((run, label, pid), {})
            gp4 = list(hand.get("gp4", []))  # type: ignore[arg-type]
            primary = ""
            secondary: list[str] = []
            if tags:
                # 주된 단계 = "판정만 맞았으면 거기서 끝났다"(GP-5) > 튜터 결함(GP-4)
                # > 그 밖(손 판정)
                if judged:
                    primary = "GP-5"
                elif gp4:
                    primary = "GP-4"
                else:
                    primary = str(hand.get("fallback", "미분류"))
                if judged and primary != "GP-5":
                    secondary.append("GP-5")
                if gp4 and primary != "GP-4":
                    secondary.append("GP-4")
            problems.append(
                {
                    "묶음표": grp,
                    "출처": src,
                    "피험자": label,
                    "실행": run,
                    "S10": s10,
                    "묶음": bundle,
                    "문제": pid,
                    "파일": path.name,
                    "줄": f"{episode[0]['line']}~{r['line']}",
                    "입력수": len(episode),
                    "튜터턴": tutor_turns,
                    "판정": "맞음" if r["correct_b"] else "틀림",
                    "소요초_첫턴부터": int(dur),
                    "소요초_직전판정부터": "" if gap is None else int(gap),
                    "모르겠어요수": dontknow,
                    "끊김태그": "".join(tags),
                    "관찰기록④": OBS[src],
                    "주된단계": primary,
                    "함께본단계": " ".join(secondary),
                    "GP4근거": " / ".join(f"T{t} {kind} {line}" for t, kind, line in gp4),
                    "판정오류입력": " / ".join(
                        f"입력{k}({ve}·{how}) {line}행" for k, how, ve, line, _ in judged
                    ),
                    "계산전식정답": (
                        "예"
                        if r["correct_b"]
                        and PROBLEMS[pid]["answer_kind"] == "number"
                        and value_or_expr(str(r["student_text"])) == "식"
                        else ""
                    ),
                    "_judged": judged,
                }
            )
            episode = []
        if episode:
            # graded 없이 끝난 문제 = 앱을 닫은 것으로 본다(끊김 ③)
            problems.append(
                {"묶음표": grp, "문제": episode[0]["problem_id"], "끊김태그": "③(graded 없음)"}
            )
    return turns, problems


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    """UTF-8(BOM 없음) CSV로 쓴다. 밑줄로 시작하는 내부 열은 뺀다."""
    if not rows:
        return
    cols = [c for c in rows[0] if not c.startswith("_")]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


STAGES = ["GP-2", "GP-3", "GP-4", "GP-5", "GP-6", "학생 쪽", "미분류"]


def main() -> int:
    turns, problems = load()
    write_csv(LOGS / "s13_turns_labeled.csv", turns)
    write_csv(OUT / "problems.csv", problems)

    by_group: dict[str, list[dict[str, object]]] = defaultdict(list)
    for p in problems:
        by_group[str(p["묶음표"])].append(p)

    # 출처별 단계별 표(주된 단계 기준 · 함께 본 단계는 별도 열)
    stage_rows = []
    for bundle, g in GROUP_ORDER:
        ps = by_group[g]
        n = len(ps)
        broken = [p for p in ps if p.get("끊김태그")]
        row: dict[str, object] = {"묶음": bundle, "출처·시점": g, "기록": n, "끊김": len(broken)}
        for st in STAGES:
            m = sum(1 for p in broken if str(p.get("주된단계", "")).startswith(st))
            also = sum(1 for p in broken if st in str(p.get("함께본단계", "")).split())
            row[st] = m
            row[st + "(함께)"] = also
        for t in "①②③":
            row["태그" + t] = sum(1 for p in ps if t in str(p.get("끊김태그", "")))
        stage_rows.append(row)
    write_csv(OUT / "stage_by_source.csv", stage_rows)

    # 출처별 문항별 표
    item_rows = []
    for bundle, g in GROUP_ORDER:
        per: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for p in by_group[g]:
            per[str(p["문제"])][0] += 1
            per[str(p["문제"])][1] += 1 if p.get("끊김태그") else 0
        for pid in sorted(per):
            item_rows.append(
                {
                    "묶음": bundle,
                    "출처·시점": g,
                    "문제": pid,
                    "기록": per[pid][0],
                    "끊김": per[pid][1],
                }
            )
    write_csv(OUT / "item_by_source.csv", item_rows)

    # 판정 오류(입력 단위) — 사람 출처는 원문을 저장소에 남기지 않는다
    je_rows = []
    for p in problems:
        for k, how, ve, line, text in p.get("_judged", []):  # type: ignore[union-attr]
            je_rows.append(
                {
                    "출처·시점": p["묶음표"],
                    "피험자": p["피험자"],
                    "파일": p["파일"],
                    "줄": line,
                    "문제": p["문제"],
                    "입력순서": k,
                    "값/식": ve,
                    "지금상태": "S10이 고침" if how == "지금 채점기로 정답" else "지금도 거부",
                    "끊긴문제": "예" if p.get("끊김태그") else "",
                    "학생입력": (
                        text if p["출처"] == "AI" else "(사람 출처 — golden/logs 원본 참조)"
                    ),
                }
            )
    write_csv(OUT / "judging_errors.csv", je_rows)

    # 전수 재채점 요약(서버 판정 vs 지금 grade.py · 입력 전체 기준)
    rg: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t in turns:
        g = group_name(
            str(t["출처"]), str(t["실행"]), str(t["S10"]), str(t["묶음"]), str(t["피험자"])
        )
        rg[g]["입력"] += 1
        if t["서버판정"] != t["지금재채점"]:
            rg[g]["서버≠지금(" + str(t["서버판정"]) + "→" + str(t["지금재채점"]) + ")"] += 1
        if t["계약상정답"] == "예" and t["서버판정"] == "오답":
            rg[g]["계약상 정답인데 서버 오답"] += 1
    regrade_rows = [{"출처·시점": g, **dict(rg[g])} for _, g in GROUP_ORDER]
    keys: list[str] = []
    for r in regrade_rows:
        keys += [k for k in r if k not in keys]
    regrade_rows = [{k: r.get(k, 0) for k in keys} for r in regrade_rows]
    write_csv(OUT / "regrade.csv", regrade_rows)

    print(json.dumps({"턴": len(turns), "문제": len(problems)}, ensure_ascii=False))
    for r in stage_rows:
        print(r)
    for r in regrade_rows:
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
