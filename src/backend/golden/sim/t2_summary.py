"""S28 T2 집계 — 시뮬레이터 실행 기록에서 오개념 검출률을 재고, 플래그 전후 표를 만든다(F-05).

무엇을 하는가
- `summarize`: 실행 폴더 하나(`sessions.jsonl` + `run_meta.json` + 보고서)를 읽어
  M1~M5(보고서 그대로)와 오개념 검출률(`metrics.misconception_detection` — P3 세션)을 낸다.
  실행 때 켠 T2 플래그 값(0/1)을 인자로 받아 함께 적는다
  (러너 기록에는 플래그가 남지 않는다 — 런북이 같은 블록에서 정한 값이다).
- `compare`: 플래그 0(전)·1(후) 두 집계를 나란히 놓은 표를 만들고 완료 기준 ①②를 판정해 적는다.

판정하지 않는 것
- 검출률이 60%에 못 미쳐도 고치지 않는다(지시서 S28 할 일 3 — 프롬프트 2차 개정 금지). 숫자만 적고
  S30이 판정한다. 그래서 `compare`의 종료 코드는 판정 결과와 무관하다(집계가 되면 0).

출력하지 않는 것
- 학생·튜터 문장. 숫자·문제 ID·오개념 ID만 낸다(시드 반출 금지 · 미성년자 데이터 규칙).

실행 기록 모양은 S19 공유 계약 그대로 읽는다(새 키 없음). 주입된 오개념은 기록의 `forced_answer`를
주입기에 다시 물어 찾는다 — 같은 주입기가 같은 문항에서 같은 답을 내는 오개념 묶음
(S27 결정 ⓐ와 같은 정의).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from golden import problems
from golden.sim import errors, metrics
from golden.sim.t1_summary import SummaryError, load_run

# 검출 낱말이 있는 오개념 파일(S26 · S28이 keywords를 더함)
MISCONCEPTIONS_PATH = errors.MISCONCEPTIONS_LF_PATH

# 완료 기준 ②(지시서 S28)의 문장 — 플래그 1 실행에서 지켜야 할 것
CRITERION_TWO = "플래그 1에서 M1 0% · M3 1% 미만 · M4 0 · M5 0"


def keyword_table(path: Path = MISCONCEPTIONS_PATH) -> dict[str, tuple[str, ...]]:
    """오개념 ID → 검출 낱말. 낱말이 빈 행이 있으면 멈춘다.

    빈 낱말은 늘 '검출 안 됨'이 되어 숨는다.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("misconceptions") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not rows:
        raise SummaryError(f"오개념 파일에 misconceptions 목록이 없다: {path}")
    table: dict[str, tuple[str, ...]] = {}
    for row in rows:
        words = tuple(str(w).strip() for w in row.get("keywords") or () if str(w).strip())
        if not words:
            raise SummaryError(f"{row.get('mis_id')}: keywords가 비어 있다")
        table[str(row["mis_id"])] = words
    return table


def injection_bundles() -> dict[tuple[str, str], tuple[str, ...]]:
    """(문항 ID, 주입기 틀린 답) → 그 답을 만드는 오개념 ID 묶음(오개념 파일 순서).

    주입기 규칙 그대로 30문항 × 오개념 전부를 다시 만든다(S27 매칭표 70행과 같은 조합).
    """
    bundles: dict[tuple[str, str], list[str]] = {}
    for problem in problems.load_problems():
        for mis_id in errors.MISCONCEPTION_RULES:
            wrong = errors.inject(problem, mis_id)
            if wrong is not None:
                bundles.setdefault((problem["id"], wrong.text), []).append(mis_id)
    return {key: tuple(ids) for key, ids in bundles.items()}


def summarize(run_dir: Path, flag: str) -> dict[str, Any]:
    """실행 폴더 하나 → M1~M5(보고서 그대로) + 오개념 검출률."""
    if flag not in ("0", "1"):
        raise SummaryError(f"플래그 값은 0 또는 1이다: {flag!r}")
    rows, meta, report, report_name = load_run(run_dir)
    detection = metrics.misconception_detection(rows, injection_bundles(), keyword_table())
    return {
        "run_dir": run_dir.name,
        "t2_flag": flag,
        "mode": meta.get("mode"),
        "date": meta.get("date"),
        "planned_sessions": meta.get("planned_sessions"),
        "skipped_sessions": meta.get("skipped_sessions"),
        "sessions": len(rows),
        "personas": meta.get("personas"),
        "report_file": report_name,
        "metrics": {name: report.get(name) for name in ("M1", "M2", "M3", "M4", "M5")},
        "exit_code": report.get("exit_code"),
        "degraded_tutor_turns": meta.get("degraded_tutor_turns"),
        "detection": detection,
    }


def _value(summary: Mapping[str, Any], name: str) -> Any:
    return (summary["metrics"].get(name) or {}).get("value")


def _num(value: Any) -> float | None:
    """숫자면 그대로, 아니면 None(bool은 숫자로 치지 않는다)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """플래그 0(전)·1(후) 집계 → 비교 결과. 같은 조건의 실행이 아니면 거부한다.

    완료 기준 ①은 검출률 숫자가 있는가(기준 60% 대비 — 미달이어도 숫자가 있으면 충족),
    ②는 플래그 1 실행의 M1·M3·M4·M5다. 숫자가 하나라도 없으면 그 항목은 실패(모름 ≠ 통과).
    """
    if before.get("t2_flag") != "0" or after.get("t2_flag") != "1":
        raise SummaryError(
            f"전후 플래그가 0→1이 아니다({before.get('t2_flag')!r}→{after.get('t2_flag')!r})"
        )
    for key in ("mode", "planned_sessions", "personas"):
        if before.get(key) != after.get(key):
            raise SummaryError(
                f"전후 실행 조건이 다르다({key}: {before.get(key)!r} ≠ {after.get(key)!r})"
                " — 비교하지 않는다"
            )
    m1, m3 = _num(_value(after, "M1")), _num(_value(after, "M3"))
    m4, m5 = _num(_value(after, "M4")), _num(_value(after, "M5"))
    rate_after = _num(after["detection"].get("value"))
    checks = {
        "detection_measured": rate_after is not None,
        "detection_at_least_60pct": rate_after is not None and rate_after >= metrics.DETECTION_MIN,
        "m1_zero": m1 is not None and m1 == 0,
        "m3_under_1pct": m3 is not None and m3 < metrics.M3_MAX,
        "m4_zero": m4 is not None and m4 == 0,
        "m5_zero": m5 is not None and m5 == 0,
    }
    # 참고(판정 아님): S23이 Kiki 결정으로 쓴 "나빠지지 않았는가" 축 — M1이 플래그 0보다 늘었는가
    m1_before = _num(_value(before, "M1"))
    return {
        "before": before,
        "after": after,
        "criterion_two": CRITERION_TWO,
        "checks": checks,
        "criterion_one_met": checks["detection_measured"],
        "criterion_two_met": all(
            checks[k] for k in ("m1_zero", "m3_under_1pct", "m4_zero", "m5_zero")
        ),
        "reference_m1_not_increased": m1_before is not None and m1 is not None and m1 <= m1_before,
    }


def _fmt(value: Any) -> str:
    return "—" if value is None else str(value)


def render_markdown(result: Mapping[str, Any]) -> str:
    """비교 결과 → 보고서에 붙일 마크다운 표(숫자·ID만)."""
    before, after = result["before"], result["after"]
    lines = [
        f"- 실행: 플래그 0 `{before['run_dir']}` · 플래그 1 `{after['run_dir']}` · "
        f"모드 {before['mode']} · 계획 세션 {before['planned_sessions']} · "
        f"기록 {before['sessions']}→{after['sessions']} · "
        f"건너뜀 {before['skipped_sessions']}→{after['skipped_sessions']}",
        "",
        "| 항목 | 플래그 0 | 플래그 1 |",
        "| --- | --- | --- |",
    ]
    for name in ("M1", "M2", "M3", "M4", "M5"):
        lines.append(f"| {name} | {_fmt(_value(before, name))} | {_fmt(_value(after, name))} |")
    db, da = before["detection"], after["detection"]
    lines += [
        f"| 오개념 검출률(P3) | {_fmt(db['value'])} | {_fmt(da['value'])} |",
        f"| └ 검출 / 분모 | {db['detected_sessions']}/{db['eligible_sessions']} | "
        f"{da['detected_sessions']}/{da['eligible_sessions']} |",
        f"| └ 제외: OP 코드만 주입 | {db['excluded_op_only']} | {da['excluded_op_only']} |",
        f"| └ 제외: 되묻기 없음 | {db['excluded_no_tutor_turn']} | "
        f"{da['excluded_no_tutor_turn']} |",
        f"| 튜터 대체 문장 턴(degraded) | {_fmt(before.get('degraded_tutor_turns'))} | "
        f"{_fmt(after.get('degraded_tutor_turns'))} |",
        "",
        "| 오개념 묶음 | 플래그 0 검출/분모 | 플래그 1 검출/분모 |",
        "| --- | --- | --- |",
    ]
    for key in sorted(set(db["by_bundle"]) | set(da["by_bundle"])):
        b = db["by_bundle"].get(key, {"detected": 0, "eligible": 0})
        a = da["by_bundle"].get(key, {"detected": 0, "eligible": 0})
        lines.append(
            f"| {key} | {b['detected']}/{b['eligible']} | {a['detected']}/{a['eligible']} |"
        )
    checks = result["checks"]
    lines += [
        "",
        f"- 완료 기준 ① 검출률 숫자: {'있음' if result['criterion_one_met'] else '없음'} "
        f"(기준 {metrics.DETECTION_MIN:.0%} 이상: {checks['detection_at_least_60pct']})",
        f"- 완료 기준 ② {result['criterion_two']}: {result['criterion_two_met']} "
        f"(M1 0: {checks['m1_zero']} · M3<1%: {checks['m3_under_1pct']} · "
        f"M4 0: {checks['m4_zero']} · M5 0: {checks['m5_zero']})",
        f"- 참고(판정 아님): 플래그 1 M1 ≤ 플래그 0 M1: {result['reference_m1_not_increased']}",
    ]
    return "\n".join(lines) + "\n"


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI. 거부는 종료 코드 2와 `T2_SUMMARY_REFUSED` 한 줄(이유)이다."""
    parser = argparse.ArgumentParser(prog="python -m golden.sim.t2_summary")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("summarize", help="실행 폴더 하나 → t2_summary.json")
    s.add_argument("--run-dir", type=Path, required=True)
    s.add_argument("--flag", required=True, help="그 실행의 GOLDEN_T2_MISCONCEPTION 값(0/1)")
    s.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("compare", help="플래그 0·1 집계 둘 → 전후 표")
    c.add_argument("--before", type=Path, required=True, help="플래그 0의 t2_summary.json")
    c.add_argument("--after", type=Path, required=True, help="플래그 1의 t2_summary.json")
    c.add_argument("--out-json", type=Path, required=True)
    c.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "summarize":
            summary = summarize(args.run_dir, args.flag)
            _write_json(args.out, summary)
            d = summary["detection"]
            print(
                f"T2_SUMMARY flag={summary['t2_flag']} sessions={summary['sessions']} "
                f"detection={d['value']} ({d['detected_sessions']}/{d['eligible_sessions']}) "
                f"op_only={d['excluded_op_only']} no_tutor_turn={d['excluded_no_tutor_turn']}"
            )
            return 0
        before = json.loads(args.before.read_text(encoding="utf-8"))
        after = json.loads(args.after.read_text(encoding="utf-8"))
        result = compare(before, after)
        _write_json(args.out_json, result)
        markdown = render_markdown(result)
        args.out_md.write_text(markdown, encoding="utf-8")
        print(markdown, end="")
        print(
            f"T2_COMPARE criterion_one={result['criterion_one_met']} "
            f"criterion_two={result['criterion_two_met']}"
        )
        return 0
    except (SummaryError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"T2_SUMMARY_REFUSED {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
