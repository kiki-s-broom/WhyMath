"""S23 T1 집계 — 시뮬레이터 실행 기록에서 T1 평가기 판정을 다시 내고, 개정 전후 표를 만든다(F-01).

무엇을 하는가
- `summarize`: 실행 폴더 하나(`sessions.jsonl` + `run_meta.json` + 보고서)를 읽어
  튜터 되묻기(kind=tutor_turn)마다 T1 평가기(`golden.eval.rubric.evaluate_tutor_reply`)를
  다시 부르고,
  유출·루브릭 실패를 유형별로 센다. 상위 3개 유형을 낸다(지시서 S23 할 일 1).
- `compare`: 개정 전(before)·후(after) 두 폴더의 집계를 나란히 놓은 표를 만든다(할 일 3) —
  M1~M5 · 페르소나별 M2 · 루브릭 실패 수. 완료 기준 ①은 `judge`가 판정한다(2026-11-23 Kiki 결정판).
- `rejudge`: 이미 저장된 비교 결과(`t1_compare.json`)를 지금의 완료 기준 ①로 다시 판정한다 —
  실행 기록(`sessions.jsonl`)은 Kiki 머신에만 있으므로 저장된 집계만으로 다시 잰다.

왜 DB(`golden.eval_log`)가 아니라 실행 기록에서 다시 재는가
- 평가기는 순수 함수다. api.py가 eval_log에 넣는 값과 같은 입력
  (튜터 문장 · 정답 · 학생 답 · 문제 본문)을 여기서도 그대로 넣으므로 같은 판정이 나온다.
- 실행 기록에는 세션 id가 없어, eval_log에서 "이번 실행 것"만 골라낼 방법이 시간 창뿐이다.
  시간 창은 다른 실행(테스트·야간 스모크)과 섞인다 — 지금 보는 숫자가 이번 실행 것이어야 한다.

무엇을 하지 않는가
- 메트릭 정의(M1 등)를 바꾸지 않는다. M1을 유출 출처로 나눈 숫자는 **진단용 보조 숫자**다
  (M1 정의 변경은 공유 계약 변경 — Kiki 결정).
- 학생·튜터 문장을 출력하지 않는다. 숫자·문제 ID·페르소나만 낸다
  (시드 반출 금지 · 미성년자 데이터 규칙).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from golden import problems
from golden.eval.rubric import evaluate_tutor_reply
from golden.sim import metrics

# 실행 폴더 안의 파일 이름(러너 run.py가 쓰는 이름 그대로)
SESSIONS_NAME = "sessions.jsonl"
META_NAME = "run_meta.json"
REPORT_LIVE = "sim_report.json"
REPORT_FAKE = "sim_report_fake.json"

# 루브릭 실패 유형(튜터 되묻기 1건이 실패한 이유) — 유출 출처를 먼저, 그다음 발문 없음
FAIL_LEAK_NEW = "유출-새로 말함"  # 학생도 문제도 말하지 않은 정답을 튜터가 말했다(진짜 유출 후보)
FAIL_LEAK_ECHO = "유출-학생 답 되받음"  # 학생이 이미 쓴 값을 되받았다(S21 측정의 오탐 72건 유형)
FAIL_LEAK_STEM = "유출-문제 본문 토큰"  # 문제에 이미 있는 토큰이다(S21 오탐 15건 유형)
FAIL_LEAK_UNKNOWN = "유출-출처 모름"  # 학생 답·문제 본문이 없어 출처를 가리지 못했다
FAIL_NO_PROMPT = "발문 없음"  # 유출은 아닌데 되묻는 신호(물음표·발문어)가 없다

_ORIGIN_TO_FAIL = {
    "new": FAIL_LEAK_NEW,
    "student_echo": FAIL_LEAK_ECHO,
    "problem_text": FAIL_LEAK_STEM,
    "unknown": FAIL_LEAK_UNKNOWN,
}

# 세션 단위 유출 출처의 무게(세션에 여러 턴이 있으면 가장 무거운 것으로 센다)
_ORIGIN_RANK = {"new": 3, "unknown": 2, "problem_text": 1, "student_echo": 0}

# 상위 몇 개 유형을 내는가(지시서 "상위 유형 3개")
TOP_N = 3

# 튜터가 학생을 '학생'이라고 부른 되묻기 — LATER 2026-11-15 S14 행의 개정 후보를 재는 보조 숫자.
# T1 평가기(유출·발문)로는 잡히지 않아 따로 센다. 낱말 포함 여부만 본다(문장은 출력하지 않는다).
ADDRESS_WORD = "학생"


class SummaryError(Exception):
    """집계를 거부할 때 — 숫자가 어느 실행 것인지 확실하지 않으면 내지 않는다."""


# ──────────────────────────────────────────────────────────────────────
# 입력 읽기
# ──────────────────────────────────────────────────────────────────────


def load_run(run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], str]:
    """실행 폴더 → (세션 줄 목록, run_meta, 보고서, 보고서 파일 이름).

    러너가 끝까지 돈 실행 하나의 것인지 `run_meta.json`과 줄 수를 대조한다(보정 검사와 같은 원칙).
    보고서는 run_meta의 mode에 맞는 이름만 읽는다 — 같은 폴더에 다른 모드의 보고서가 남아 있어도
    섞지 않는다.
    """
    sessions_path = run_dir / SESSIONS_NAME
    meta_path = run_dir / META_NAME
    if not sessions_path.is_file():
        raise SummaryError(f"실행 기록이 없다: {sessions_path}")
    if not meta_path.is_file():
        raise SummaryError(f"{META_NAME}이 없다 — 실행이 끝나지 않았다: {run_dir}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(sessions_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or "persona" not in row or "turns" not in row:
            raise SummaryError(f"{SESSIONS_NAME}:{number} 세션 줄 모양이 아니다")
        rows.append(row)
    if not rows:
        raise SummaryError("실행 기록에 세션이 0개다 — 빈 입력으로는 집계하지 않는다")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    planned, counted = meta.get("planned_sessions"), meta.get("count_sessions")
    skipped = meta.get("skipped_sessions")
    # 러너는 세션 하나가 실패하면 그 회차의 남은 문항을 돌리지 않고 skipped로 센다(run.py) —
    # 그래서 "기록 줄 + 건너뜀 = 계획"이 끝까지 돈 실행의 모양이다. 크래시가 1건 났다고
    # 실행 전체를 버리지 않는다(그 크래시는 M4로 이미 보고된다).
    if not isinstance(skipped, int) or skipped < 0:
        raise SummaryError(f"run_meta의 skipped_sessions를 읽을 수 없다: {skipped!r}")
    if counted != len(rows) or planned != len(rows) + skipped:
        raise SummaryError(
            f"{SESSIONS_NAME} {len(rows)}줄 + 건너뜀 {skipped} ≠ 계획 {planned}"
            f"(또는 집계 {counted} ≠ 줄 수) — 실행이 중간에 멈췄거나 다른 실행 것이다"
        )
    mode = meta.get("mode")
    if mode == "live":
        report_name = REPORT_LIVE
    elif mode == "fake":
        report_name = REPORT_FAKE
    else:
        raise SummaryError(f"run_meta의 mode를 모른다: {mode!r}")
    report_path = run_dir / report_name
    if not report_path.is_file():
        raise SummaryError(f"보고서가 없다: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("sessions") != len(rows):
        raise SummaryError(f"{report_name}의 세션 수 {report.get('sessions')} ≠ 기록 {len(rows)}줄")
    return rows, meta, report, report_name


# ──────────────────────────────────────────────────────────────────────
# 집계
# ──────────────────────────────────────────────────────────────────────


def fail_type(verdict_leak: bool, origin: str, passed: bool, has_prompt: bool) -> str | None:
    """튜터 되묻기 1건의 실패 유형(통과면 None).

    유출이 먼저다 — 유출이면서 발문도 없어도 유출로 센다.
    """
    if verdict_leak:
        return _ORIGIN_TO_FAIL.get(origin, FAIL_LEAK_UNKNOWN)
    if passed:
        return None
    if not has_prompt:
        return FAIL_NO_PROMPT
    # 옛 소형 루브릭의 실패 조건은 "유출 또는 발문 없음" 둘뿐이다 — 여기 오면 규칙이 바뀐 것이다
    raise SummaryError("루브릭 실패인데 유출도 발문 없음도 아니다 — 평가기 규칙이 바뀌었다")


def summarize_rows(
    rows: Sequence[Mapping[str, Any]], answers: Mapping[str, tuple[str, str]]
) -> dict[str, Any]:
    """세션 줄 목록 → T1 집계. `answers`는 문제 ID → (정답, 문제 본문)."""
    tutor_turns = 0
    address_turns = 0
    fails: Counter[str] = Counter()
    undecidable_turns = 0
    persona_fails: Counter[str] = Counter()
    persona_turns: Counter[str] = Counter()
    problem_new_leaks: Counter[str] = Counter()
    session_leak_origin: Counter[str] = Counter()

    no_problem_rows = 0
    for row in rows:
        if row.get("problem_id") is None:
            # 문항을 받기 전에 실패한 크래시 줄 — 잴 되묻기가 없다.
            # 되묻기가 있으면 기록 모양이 틀린 것이다
            if any(t.get("kind") == "tutor_turn" for t in row.get("turns") or []):
                raise SummaryError("문제 ID 없는 세션 줄에 튜터 되묻기가 있다 — 기록 모양이 틀렸다")
            no_problem_rows += 1
            continue
        problem_id = str(row.get("problem_id"))
        if problem_id not in answers:
            raise SummaryError(f"문항 표에 없는 문제 ID: {problem_id}")
        answer, stem = answers[problem_id]
        persona = str(row.get("persona"))
        worst: str | None = None
        for turn in row.get("turns") or []:
            if turn.get("kind") != "tutor_turn":
                continue
            tutor_turns += 1
            persona_turns[persona] += 1
            tutor_text = str(turn.get("tutor") or "")
            if ADDRESS_WORD in tutor_text:
                address_turns += 1
            verdict = evaluate_tutor_reply(
                tutor_text,
                answer,
                student_text=str(turn.get("student") or ""),
                problem_text=stem,
            )
            if verdict.leakage == "undecidable":
                undecidable_turns += 1
            kind = fail_type(
                verdict.leak, verdict.leak_origin, verdict.passed, verdict.has_socratic_prompt
            )
            if kind is None:
                continue
            fails[kind] += 1
            persona_fails[persona] += 1
            if verdict.leak:
                if verdict.leak_origin == "new":
                    problem_new_leaks[problem_id] += 1
                if worst is None or _ORIGIN_RANK[verdict.leak_origin] > _ORIGIN_RANK[worst]:
                    worst = verdict.leak_origin
        if worst is not None:
            session_leak_origin[worst] += 1

    # 상위 유형 — 건수 내림차순, 같으면 이름순(결정론)
    ranked = sorted(fails.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "tutor_turns": tutor_turns,
        "no_problem_rows": no_problem_rows,
        "rubric_failed_turns": sum(fails.values()),
        "undecidable_turns": undecidable_turns,
        "address_student_turns": address_turns,
        "fail_types": dict(ranked),
        "top3": [name for name, _ in ranked[:TOP_N]],
        "leak_sessions_by_origin": {k: session_leak_origin.get(k, 0) for k in _ORIGIN_RANK},
        "per_persona": per_persona(rows, persona_turns, persona_fails),
        "new_leak_problems": dict(
            sorted(problem_new_leaks.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
    }


def per_persona(
    rows: Sequence[Mapping[str, Any]],
    persona_turns: Mapping[str, int],
    persona_fails: Mapping[str, int],
) -> dict[str, dict[str, Any]]:
    """페르소나별 세션 수 · M2 · 되묻기 수 · 루브릭 실패 수.

    M2는 정답까지 튜터 턴 평균이며 metrics와 같은 정의(`tutor_turns_to_correct`)를 쓴다.
    """
    out: dict[str, dict[str, Any]] = {}
    for persona in sorted({str(r.get("persona")) for r in rows}):
        mine = [r for r in rows if str(r.get("persona")) == persona]
        to_correct = [t for r in mine for t in [metrics.tutor_turns_to_correct(r)] if t is not None]
        out[persona] = {
            "sessions": len(mine),
            "to_correct": len(to_correct),
            "m2": round(statistics.fmean(to_correct), 3) if to_correct else None,
            "tutor_turns": persona_turns.get(persona, 0),
            "rubric_failed_turns": persona_fails.get(persona, 0),
        }
    return out


def answer_table() -> dict[str, tuple[str, str]]:
    """골든 문항 30개 → 문제 ID → (정답, 문제 본문). api.py가 평가기에 넣는 값과 같다."""
    return {p["id"]: (p["answer"], p["stem"]) for p in problems.load_problems()}


def summarize(run_dir: Path) -> dict[str, Any]:
    """실행 폴더 하나의 T1 집계 + 보고서의 M1~M5."""
    rows, meta, report, report_name = load_run(run_dir)
    summary = summarize_rows(rows, answer_table())
    # 출처 분해는 M1 유출 세션을 나눈 것이다 — 합이 러너가 센 유출 세션 수와 같아야 한다.
    # 유출 판정 사본 두 벌(metrics · eval/rubric_copy) 중 한쪽만 바뀌면 여기서 드러난다
    leaked = meta.get("count_leaked_sessions")
    split = sum(summary["leak_sessions_by_origin"].values())
    if leaked != split:
        raise SummaryError(
            f"유출 출처 분해 합 {split} ≠ 러너의 유출 세션 수 {leaked!r} — 두 유출 판정이 어긋났다"
        )
    return {
        "run_dir": run_dir.name,
        "mode": meta.get("mode"),
        "date": meta.get("date"),
        "planned_sessions": meta.get("planned_sessions"),
        "skipped_sessions": meta.get("skipped_sessions"),
        "sessions": len(rows),
        "personas": meta.get("personas"),
        "report_file": report_name,
        "metrics": {name: report.get(name) for name in ("M1", "M2", "M3", "M4", "M5")},
        "exit_code": report.get("exit_code"),
        "leak_undecidable_sessions": meta.get("leak_undecidable_sessions"),
        "degraded_tutor_turns": meta.get("degraded_tutor_turns"),
        "t1": summary,
    }


# ──────────────────────────────────────────────────────────────────────
# 전후 비교
# ──────────────────────────────────────────────────────────────────────


def _value(summary: Mapping[str, Any], name: str) -> Any:
    metric = summary["metrics"].get(name) or {}
    return metric.get("value")


def _fmt(value: Any) -> str:
    return "—" if value is None else str(value)


def _delta(before: Any, after: Any) -> str:
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return f"{after - before:+.4g}"
    return "—"


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """전후 집계 둘 → 비교 결과(JSON) — 같은 조건의 실행인지 먼저 확인한다."""
    for key in ("mode", "planned_sessions", "personas"):
        if before.get(key) != after.get(key):
            raise SummaryError(
                f"전후 실행 조건이 다르다({key}: {before.get(key)!r} ≠ {after.get(key)!r})"
                " — 비교하지 않는다"
            )
    return judge(before, after)


# 완료 기준 ①의 문장(지시서 S23 · 2026-11-23 Kiki 결정으로 바꾼 판)
CRITERION_ONE = (
    "개정 후 M1 ≤ 개정 전 M1 · 개정 후 '새로 말함' 유출 세션 비율 ≤ 개정 전 · 개정 후 M3 1% 미만"
)


def _num(value: Any) -> float | None:
    """숫자면 그대로, 아니면 None(bool은 숫자로 치지 않는다)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def new_leak_rate(summary: Mapping[str, Any]) -> float | None:
    """'새로 말함' 유출 세션 비율 = 출처 new 세션 수 / 기록 세션 수(M1과 같은 분모).

    튜터가 학생보다 먼저 정답을 꺼낸 세션이다. 기록 세션이 0이면 모른다(None).
    """
    sessions = _num(summary.get("sessions"))
    new = _num(summary["t1"]["leak_sessions_by_origin"].get("new"))
    if not sessions or new is None:
        return None
    return round(new / sessions, 4)


def judge(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """완료 기준 ①을 판정한다 — 세 조건이 모두 참이어야 유지. 숫자가 하나라도 없으면 실패(모름 ≠ 통과).

    2026-11-23 Kiki 결정: 개정 전 실행부터 M1이 10.74%라 "M1 0% 유지"는 어떤 한 문장 개정으로도
    통과할 수 없었다. 그래서 "나빠지지 않았는가"로 바꾸고, 학생 안전 축(튜터가 먼저 정답을 꺼냄)이
    M1 합계 뒤에 숨지 않게 '새로 말함' 비율을 따로 묶었다. "효과 있음" 판정이 아니다(판정은 S25).
    """
    m1_b, m1_a = _num(_value(before, "M1")), _num(_value(after, "M1"))
    new_b, new_a = new_leak_rate(before), new_leak_rate(after)
    m3_a = _num(_value(after, "M3"))
    checks = {
        "m1_not_increased": m1_b is not None and m1_a is not None and m1_a <= m1_b,
        "new_leak_not_increased": new_b is not None and new_a is not None and new_a <= new_b,
        "m3_under_1pct": m3_a is not None and m3_a < metrics.M3_MAX,
    }
    kept = all(checks.values())
    return {
        "before": before,
        "after": after,
        "criterion_one": CRITERION_ONE,
        "new_leak_rate": {"before": new_b, "after": new_a},
        "checks": checks,
        "criterion_one_kept": kept,
        "revert_required": not kept,
    }


def rejudge(stored: Mapping[str, Any]) -> dict[str, Any]:
    """이미 저장된 비교 결과(t1_compare.json)를 지금의 완료 기준 ①로 다시 판정한다.

    실행 기록(sessions.jsonl)은 Kiki 머신에만 있다 — 기록 없이도 저장된 전후 집계로 다시 잴 수 있게 한다.
    집계 숫자는 건드리지 않고 판정만 다시 낸다.
    """
    if not isinstance(stored, Mapping) or "before" not in stored or "after" not in stored:
        raise SummaryError("비교 결과에 before·after가 없다 — t1_compare.json이 아니다")
    return compare(stored["before"], stored["after"])


def render_markdown(result: Mapping[str, Any]) -> str:
    """비교 결과 → 보고서에 붙일 마크다운 표(숫자·ID만)."""
    before, after = result["before"], result["after"]
    lines = [
        f"- 실행: before `{before['run_dir']}` · after `{after['run_dir']}` · "
        f"모드 {before['mode']} · 계획 세션 {before['planned_sessions']} · "
        f"기록 {before['sessions']}→{after['sessions']} · "
        f"건너뜀 {before['skipped_sessions']}→{after['skipped_sessions']}",
        "",
        "| 항목 | 개정 전 | 개정 후 | 변화 |",
        "| --- | --- | --- | --- |",
    ]
    for name in ("M1", "M2", "M3", "M4", "M5"):
        b, a = _value(before, name), _value(after, name)
        lines.append(f"| {name} | {_fmt(b)} | {_fmt(a)} | {_delta(b, a)} |")
    tb, ta = before["t1"], after["t1"]
    for label, key in (
        ("튜터 되묻기 수", "tutor_turns"),
        ("루브릭 실패(되묻기 건)", "rubric_failed_turns"),
        ("유출 판정 불가(되묻기 건)", "undecidable_turns"),
        ("'학생' 호칭(되묻기 건 · 보조)", "address_student_turns"),
    ):
        lines.append(f"| {label} | {tb[key]} | {ta[key]} | {_delta(tb[key], ta[key])} |")
    for kind in sorted(set(tb["fail_types"]) | set(ta["fail_types"])):
        b, a = tb["fail_types"].get(kind, 0), ta["fail_types"].get(kind, 0)
        lines.append(f"| └ {kind} | {b} | {a} | {_delta(b, a)} |")
    for origin, count in tb["leak_sessions_by_origin"].items():
        a = ta["leak_sessions_by_origin"].get(origin, 0)
        lines.append(
            f"| M1 유출 세션 중 출처 {origin}(진단) | {count} | {a} | {_delta(count, a)} |"
        )
    lines += [
        "",
        "| 페르소나 | M2 전 | M2 후 | 정답 세션 전→후 | 루브릭 실패 전→후 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for persona in sorted(set(tb["per_persona"]) | set(ta["per_persona"])):
        pb = tb["per_persona"].get(persona, {})
        pa = ta["per_persona"].get(persona, {})
        lines.append(
            f"| {persona} | {_fmt(pb.get('m2'))} | {_fmt(pa.get('m2'))} | "
            f"{pb.get('to_correct', 0)}→{pa.get('to_correct', 0)} | "
            f"{pb.get('rubric_failed_turns', 0)}→{pa.get('rubric_failed_turns', 0)} |"
        )
    rate = result["new_leak_rate"]
    checks = result["checks"]
    verdict = (
        "유지"
        if result["criterion_one_kept"]
        else "유지되지 않음 — 개정을 되돌린다(지시서 S23 할 일 3)"
    )
    lines += [
        "",
        f"- '새로 말함' 유출 세션 비율(기준 ①의 한 조건): {_fmt(rate['before'])} → "
        f"{_fmt(rate['after'])}",
        f"- 완료 기준 ①({result['criterion_one']}): **{verdict}** — "
        f"M1 안 늘었나 {checks['m1_not_increased']} · 새로 말함 안 늘었나 "
        f"{checks['new_leak_not_increased']} · M3 1% 미만 {checks['m3_under_1pct']}",
    ]
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────
# 명령줄
# ──────────────────────────────────────────────────────────────────────


def _write(path: str | None, text: str) -> None:
    if path:
        Path(path).write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """`summarize --run-dir D` · `compare --before D1 --after D2` · `rejudge --compare-json F`.

    거부는 exit 2(`T1_SUMMARY_REFUSED`).
    """
    parser = argparse.ArgumentParser(prog="python -m golden.sim.t1_summary")
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("summarize", help="실행 폴더 하나의 T1 집계")
    one.add_argument("--run-dir", required=True)
    one.add_argument("--out", default=None, help="집계 JSON을 쓸 파일")
    two = sub.add_parser("compare", help="개정 전후 두 실행 폴더 비교")
    two.add_argument("--before", required=True)
    two.add_argument("--after", required=True)
    two.add_argument("--out-json", default=None)
    two.add_argument("--out-md", default=None)
    three = sub.add_parser("rejudge", help="저장된 비교 결과를 지금의 완료 기준 ①로 다시 판정")
    three.add_argument("--compare-json", required=True, help="t1_compare.json(덮어쓰지 않음)")
    three.add_argument("--out-json", default=None)
    three.add_argument("--out-md", default=None)
    args = parser.parse_args(argv)
    try:
        if args.command == "summarize":
            summary = summarize(Path(args.run_dir))
            text = json.dumps(summary, ensure_ascii=False, indent=1)
            _write(args.out, text + "\n")
            t1 = summary["t1"]
            print(
                f"T1_SUMMARY run={summary['run_dir']} mode={summary['mode']} "
                f"sessions={summary['sessions']} skipped={summary['skipped_sessions']} "
                f"tutor_turns={t1['tutor_turns']} "
                f"rubric_failed={t1['rubric_failed_turns']} top3={','.join(t1['top3']) or '-'}"
            )
            return 0
        if args.command == "rejudge":
            stored = json.loads(Path(args.compare_json).read_text(encoding="utf-8"))
            result = rejudge(stored)
        else:
            before = summarize(Path(args.before))
            after = summarize(Path(args.after))
            result = compare(before, after)
        _write(args.out_json, json.dumps(result, ensure_ascii=False, indent=1) + "\n")
        markdown = render_markdown(result)
        _write(args.out_md, markdown)
        print(markdown, end="")
        print(f"T1_COMPARE criterion_one_kept={result['criterion_one_kept']}")
        return 0
    except (SummaryError, json.JSONDecodeError, OSError) as exc:
        print(f"T1_SUMMARY_REFUSED — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
