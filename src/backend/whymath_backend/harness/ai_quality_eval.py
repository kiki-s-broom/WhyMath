"""P3-10 — AI 품질 평가 8종 CLI: 평가셋 × 후보 응답 → 축별 점수·Wilson 경계·실패 사례·exit code.

정본 지시: `docs/strategy/phase3_math_eos_completion_instruction_set.md` [14] P3-10.
보고서: `docs/reviews/p3_10_ai_quality_eval_suite_2026-10-21.md`.

8축: 수학적 정확성 · 정답 누설 · 오개념 판정 정확도 · Hint 적절성 · 설명 일관성 · 학생 수준 적합성 ·
hallucination · Curriculum 범위 이탈. 축 정의·재사용 판정·사각은 `ai_quality_judges`가 정본이다.

사용
----
    # 현재 코드의 결정론 튜터 출력(LLM 0)을 잰다 — 기본
    python -m whymath_backend.harness.ai_quality_eval
    # 라이브 튜터 응답(JSONL)을 잰다
    python -m whymath_backend.harness.ai_quality_eval --responses responses.jsonl
    # 축 하나에 나쁜 응답을 넣어 잰다(음성 대조군)
    python -m whymath_backend.harness.ai_quality_eval --inject answer_leak
    # 변별력 자가 점검 — 8축 각각에 주입해 그 축 점수가 떨어지고 판정이 FAIL로 바뀌는지(CI 스텝)
    python -m whymath_backend.harness.ai_quality_eval --self-test
    # 평가셋을 코퍼스에서 다시 만든다(커밋본과 바이트 비교는 테스트가 한다)
    python -m whymath_backend.harness.ai_quality_eval --build-eval-set out.jsonl

판정(점추정 금지 · CLAUDE.md 검증 권위)
-------------------------------------
축마다 `ceiling`(실패율의 Wilson 단측 95% **상한** ≤ 임계) 또는 `floor`(통과율의 Wilson **하한** ≥
임계). 무관용 축(정답 누설·hallucination)은 그에 더해 실패 1건이면 FAIL이다. 임계는 KPI 재사용이거나
이 태스크의 **제안값**(Kiki 확인 전)이며 리포트가 어느 쪽인지 적는다.
판정 대상이 `min_n` 미만이거나 판정기가 예외를 내면 그 축은 **측정 실패**다(통과로 접지 않는다).
표본 크기로는 임계에 닿을 수 없으면(`reachable=False`) 그 사실을 함께 낸다.

종료 코드
---------
- 0 — 8축 전부 PASS (`--self-test`: 8축 전부 주입이 점수 하락 + FAIL 전환을 만들었다)
- 1 — 하나라도 FAIL (`--self-test`: 하나라도 무반응·주입 미적용)
- 2 — 측정 실패(적재 실패·판정 대상 부족·판정기 예외). 1과 2 모두 CI를 빨갛게 한다.
  `--self-test`에서 2는 적재 실패뿐이다 — 판정 대상 부족·판정기 예외는 그 축이 UNMEASURED가 되어
  FAIL 전환을 못 하므로 '무반응'으로 계상돼 1이 된다.

학생 노출 경로(P3-G3 ② 준비) — 범위를 밝힌다
--------------------------------------------
실패 사례마다 P3-09 학생 대면 출력 게이트(`validate_tutor_output`)가 그 응답을 **차단하는지**를
함께 적는다(`blocked_by_p309`). 차단되면 그 실패는 그 게이트에서 멈춘다. **미차단이 곧 학생 도달은
아니다** — 서빙 경로에는 P3-09 앞에 정답 억제 백스톱·프로즈 게이트·톤필터·금지모드 가드가 있고, 이
CLI는 그 층들을 모델링하지 않는다(실제 러너를 거친 측정은 라이브 후보 측정 태스크의 몫). 그래서
리포트 표기는 '노출'이 아니라 'P3-09 미차단'이다.

측정 도구 실패 경로(2026-08-22 규칙)
-----------------------------------
축 결과를 계산되는 대로 즉시 출력(flush)한다 · 적재 실패는 단계명 + 예외 타입명을 남긴다 · 리포트
머리에 평가셋 sha256·후보 출처·주입 축을 찍어 "지금 보는 것이 이번 실행 것인가"를 판별하게 한다 ·
외부 프로세스·네트워크 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from whymath_backend.harness.ai_quality_candidates import (
    CANDIDATE_EOS,
    CandidateError,
    build_eos_candidate,
    dump_responses,
    inject,
    load_responses,
)
from whymath_backend.harness.ai_quality_eval_set import (
    EvalSet,
    EvalSetError,
    build_cases,
    dump_cases,
    load_eval_set,
)
from whymath_backend.harness.ai_quality_judges import (
    AXES,
    AXIS_SPECS,
    BLIND_SPOTS,
    AxisSpec,
    JudgeContext,
    Judgment,
    TutorResponse,
    judge_case,
    p309_blocks,
    prepare_ladder_tiers,
)
from whymath_backend.harness.ai_quality_registry import Registry, RegistryError, load_registry
from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.ops.validation_scorecard import KpiThreshold

__all__ = [
    "AxisResult",
    "EvalReport",
    "SelfTestReport",
    "evaluate",
    "main",
    "render_report",
    "render_self_test",
    "run_self_test",
    "to_json",
]

_EXIT_OK: Final = 0
_EXIT_FAIL: Final = 1
_EXIT_MEASUREMENT: Final = 2
_CONFIDENCE: Final = 0.95
REPORT_SCHEMA: Final = "ai-quality-report/v1"


@dataclass(frozen=True)
class FailureCase:
    case_id: str
    reasons: tuple[str, ...]
    blocked_by_p309: bool


@dataclass(frozen=True)
class AxisResult:
    """축 1개의 집계 — 분모·통과·실패·Wilson 경계·판정·실패 사례·P3-09 차단 여부·작동 회계."""

    spec: AxisSpec
    n_cases: int
    n_applicable: int
    n_pass: int
    n_fail: int
    n_errors: int
    bound: float | None
    observed: str
    verdict: str
    """PASS / FAIL / UNMEASURED."""
    reachable: bool | None
    failures: tuple[FailureCase, ...]
    counters: Mapping[str, int]

    @property
    def pass_rate(self) -> float | None:
        return self.n_pass / self.n_applicable if self.n_applicable else None

    @property
    def unblocked_failures(self) -> int:
        return sum(1 for f in self.failures if not f.blocked_by_p309)


@dataclass(frozen=True)
class EvalReport:
    eval_source: str
    eval_sha256: str
    n_cases: int
    kinds: Mapping[str, int]
    candidate: str
    injection: str | None
    axes: tuple[AxisResult, ...]
    missing_responses: int

    @property
    def verdict(self) -> str:
        if any(a.verdict == "UNMEASURED" for a in self.axes):
            return "UNMEASURED"
        if any(a.verdict == "FAIL" for a in self.axes):
            return "FAIL"
        return "PASS"

    @property
    def exit_code(self) -> int:
        return {"PASS": _EXIT_OK, "FAIL": _EXIT_FAIL}.get(self.verdict, _EXIT_MEASUREMENT)

    def axis(self, name: str) -> AxisResult:
        return next(a for a in self.axes if a.spec.axis == name)


def _judge_axis(
    spec: AxisSpec,
    eval_set: EvalSet,
    responses: Mapping[str, TutorResponse],
    ctx: JudgeContext,
) -> AxisResult:
    applicable = passed = failed = errors = 0
    failures: list[FailureCase] = []
    counters: Counter[str] = Counter()
    for case in eval_set.cases:
        response = responses.get(case.case_id)
        try:
            judgment: Judgment = judge_case(spec.axis, case, response, ctx)
        except Exception as exc:  # 판정기 예외 = 측정 실패(타입명을 남긴다 — 침묵 실패 금지)
            errors += 1
            failures.append(
                FailureCase(case.case_id, (f"판정기 예외 {type(exc).__name__}",), False)
            )
            continue
        counters.update(judgment.counters)
        if not judgment.applicable:
            continue
        applicable += 1
        if judgment.passed:
            passed += 1
        else:
            failed += 1
            failures.append(
                FailureCase(case.case_id, judgment.reasons, p309_blocks(case, response))
            )
    threshold = KpiThreshold(spec.direction, spec.threshold)
    bound: float | None = None
    observed = "—"
    reachable: bool | None = None
    ok = False
    if applicable:
        hits = failed if spec.direction == "ceiling" else passed
        ok, bound, observed = threshold.judge(hits, applicable)
        reachable = (
            wilson_upper_bound(0, applicable, _CONFIDENCE) <= spec.threshold
            if spec.direction == "ceiling"
            else wilson_lower_bound(applicable, applicable, _CONFIDENCE) >= spec.threshold
        )
    if errors or applicable < spec.min_n:
        verdict = "UNMEASURED"
    elif spec.zero_tolerance and failed:
        verdict = "FAIL"
    else:
        verdict = "PASS" if ok else "FAIL"
    return AxisResult(
        spec=spec,
        n_cases=len(eval_set.cases),
        n_applicable=applicable,
        n_pass=passed,
        n_fail=failed,
        n_errors=errors,
        bound=bound,
        observed=observed,
        verdict=verdict,
        reachable=reachable,
        failures=tuple(failures),
        counters=dict(counters),
    )


def evaluate(
    eval_set: EvalSet,
    registry: Registry,
    responses: Mapping[str, TutorResponse],
    *,
    candidate: str,
    injection: str | None = None,
    stream: Any = None,
) -> EvalReport:
    """8축 판정 — `stream`이 있으면 축 결과를 계산되는 대로 한 줄씩 즉시 쓴다."""
    ctx = JudgeContext(registry=registry, eval_set=eval_set)
    prepare_ladder_tiers(ctx, responses)
    axes: list[AxisResult] = []
    for axis in AXES:
        result = _judge_axis(AXIS_SPECS[axis], eval_set, responses, ctx)
        axes.append(result)
        if stream is not None:
            print(_axis_line(result), file=stream, flush=True)
    kinds = Counter(c.kind for c in eval_set.cases)
    return EvalReport(
        eval_source=eval_set.source,
        eval_sha256=eval_set.sha256,
        n_cases=len(eval_set.cases),
        kinds=dict(kinds),
        candidate=candidate,
        injection=injection,
        axes=tuple(axes),
        missing_responses=sum(1 for c in eval_set.cases if c.case_id not in responses),
    )


# ──────────────────────────────────────────────────────────────────────────
# 변별력 자가 점검
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class InjectionOutcome:
    axis: str
    mutated: int
    baseline_rate: float | None
    injected_rate: float | None
    injected_verdict: str
    cross_rates: Mapping[str, float | None] = field(default_factory=dict)

    @property
    def dropped(self) -> bool:
        if self.injected_rate is None:
            return False
        base = 1.0 if self.baseline_rate is None else self.baseline_rate
        return self.injected_rate < base

    @property
    def ok(self) -> bool:
        return self.mutated > 0 and self.dropped and self.injected_verdict == "FAIL"


@dataclass(frozen=True)
class SelfTestReport:
    baseline: EvalReport
    outcomes: tuple[InjectionOutcome, ...]

    @property
    def exit_code(self) -> int:
        return _EXIT_OK if all(o.ok for o in self.outcomes) else _EXIT_FAIL


def run_self_test(
    eval_set: EvalSet,
    registry: Registry,
    base: Mapping[str, TutorResponse],
    *,
    candidate: str,
    stream: Any = None,
) -> SelfTestReport:
    """8축 각각에 나쁜 응답을 넣어 그 축 점수가 떨어지고 FAIL이 되는지 — 무반응이면 exit 1."""
    baseline = evaluate(eval_set, registry, base, candidate=candidate)
    outcomes: list[InjectionOutcome] = []
    for axis in AXES:
        mutated, changed = inject(axis, eval_set, registry, base)
        report = evaluate(eval_set, registry, mutated, candidate=candidate, injection=axis)
        mine = report.axis(axis)
        outcome = InjectionOutcome(
            axis=axis,
            mutated=changed,
            baseline_rate=baseline.axis(axis).pass_rate,
            injected_rate=mine.pass_rate,
            injected_verdict=mine.verdict,
            cross_rates={a.spec.axis: a.pass_rate for a in report.axes},
        )
        outcomes.append(outcome)
        if stream is not None:
            print(_outcome_line(outcome), file=stream, flush=True)
    return SelfTestReport(baseline=baseline, outcomes=tuple(outcomes))


# ──────────────────────────────────────────────────────────────────────────
# 렌더
# ──────────────────────────────────────────────────────────────────────────
def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _axis_line(a: AxisResult) -> str:
    direction = "실패율 상한" if a.spec.direction == "ceiling" else "통과율 하한"
    reach = "" if a.reachable is None or a.reachable else " · 이 표본으로는 임계 도달 불가"
    return (
        f"[{a.verdict:<10}] {a.spec.name_ko:<14} 대상 {a.n_applicable}/{a.n_cases} · 통과 "
        f"{a.n_pass} · 실패 {a.n_fail} (P3-09 미차단 {a.unblocked_failures}) · {a.observed} · "
        f"기준 {direction} {a.spec.threshold:.2f}{reach}"
        + (f" · 판정기 예외 {a.n_errors}" if a.n_errors else "")
    )


def _outcome_line(o: InjectionOutcome) -> str:
    mark = "OK  " if o.ok else "무반응"
    return (
        f"[{mark}] 주입 {AXIS_SPECS[o.axis].name_ko:<14} 바뀐 응답 {o.mutated} · 점수 "
        f"{_pct(o.baseline_rate)} → {_pct(o.injected_rate)} · 판정 {o.injected_verdict}"
    )


def render_report(report: EvalReport, *, failures: int = 5) -> str:
    lines = [
        "AI 품질 평가 8종 (P3-10)",
        f"평가셋 {report.eval_source} · sha256 {report.eval_sha256[:12]} · 사례 {report.n_cases} "
        f"{dict(report.kinds)}",
        f"후보 {report.candidate} · 주입 {report.injection or '없음'} · 응답 누락 "
        f"{report.missing_responses}",
        "",
    ]
    for a in report.axes:
        lines.append(_axis_line(a))
        lines.append(f"    판정 권위: {a.spec.reuse}")
        lines.append(f"    임계 출처: {a.spec.threshold_basis}")
        if a.counters:
            lines.append(
                "    작동 회계: " + ", ".join(f"{k}={v}" for k, v in sorted(a.counters.items()))
            )
        for f in a.failures[:failures]:
            block = "P3-09 차단" if f.blocked_by_p309 else "P3-09 미차단"
            lines.append(f"    ✗ {f.case_id} [{block}] {' / '.join(f.reasons)}")
        if len(a.failures) > failures:
            lines.append(f"    … 실패 {len(a.failures) - failures}건 더(--json 에 전건)")
    lines.append("")
    lines.append(f"종합: {report.verdict} (exit {report.exit_code})")
    return "\n".join(lines)


def render_self_test(report: SelfTestReport) -> str:
    lines = ["변별력 자가 점검 — 축마다 나쁜 응답 주입 → 그 축 점수 하락 + FAIL 전환", ""]
    header = "주입 \\ 축 점수".ljust(18) + " ".join(f"{a[:8]:>9}" for a in AXES)
    lines.append(header)
    base = report.baseline
    lines.append(
        "기준(주입 없음)".ljust(18) + " ".join(f"{_pct(base.axis(a).pass_rate):>9}" for a in AXES)
    )
    for o in report.outcomes:
        lines.append(
            o.axis[:16].ljust(18) + " ".join(f"{_pct(o.cross_rates.get(a)):>9}" for a in AXES)
        )
    lines.append("")
    for o in report.outcomes:
        lines.append(_outcome_line(o))
    ok = sum(1 for o in report.outcomes if o.ok)
    lines.append("")
    lines.append(f"자가 점검: {ok}/{len(report.outcomes)} 축 반응 (exit {report.exit_code})")
    return "\n".join(lines)


def _axis_json(a: AxisResult) -> dict[str, Any]:
    return {
        "axis": a.spec.axis,
        "name_ko": a.spec.name_ko,
        "decision": a.spec.decision,
        "kpi_mapping": a.spec.kpi_mapping,
        "reuse": a.spec.reuse,
        "threshold": {
            "direction": a.spec.direction,
            "value": a.spec.threshold,
            "basis": a.spec.threshold_basis,
        },
        "min_n": a.spec.min_n,
        "n_cases": a.n_cases,
        "n_applicable": a.n_applicable,
        "n_pass": a.n_pass,
        "n_fail": a.n_fail,
        "n_errors": a.n_errors,
        "pass_rate": a.pass_rate,
        "wilson_bound": a.bound,
        "observed": a.observed,
        "reachable": a.reachable,
        "verdict": a.verdict,
        "failures_not_blocked_by_p309": a.unblocked_failures,
        "counters": dict(a.counters),
        "blind_spots": list(BLIND_SPOTS.get(a.spec.axis, ())),
        "failures": [
            {"case_id": f.case_id, "reasons": list(f.reasons), "blocked_by_p309": f.blocked_by_p309}
            for f in a.failures
        ],
    }


def to_json(report: EvalReport) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "eval_set": {
            "source": report.eval_source,
            "sha256": report.eval_sha256,
            "cases": report.n_cases,
            "kinds": dict(report.kinds),
        },
        "candidate": report.candidate,
        "injection": report.injection,
        "missing_responses": report.missing_responses,
        "axes": [_axis_json(a) for a in report.axes],
        "verdict": report.verdict,
        "exit_code": report.exit_code,
    }


def _self_test_json(report: SelfTestReport) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA + "+self-test",
        "baseline": to_json(report.baseline),
        "injections": [
            {
                "axis": o.axis,
                "mutated": o.mutated,
                "baseline_rate": o.baseline_rate,
                "injected_rate": o.injected_rate,
                "injected_verdict": o.injected_verdict,
                "dropped": o.dropped,
                "ok": o.ok,
                "cross_rates": dict(o.cross_rates),
            }
            for o in report.outcomes
        ],
        "exit_code": report.exit_code,
    }


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.ai_quality_eval",
        description="P3-10 AI 품질 평가 8종 — 평가셋 × 후보 응답 → 축별 점수·Wilson 판정·exit "
        "code (hermetic · LLM 0 · DB 0)",
    )
    parser.add_argument("--eval-set", type=Path, default=None, help="평가셋 JSONL(기본 정본)")
    parser.add_argument(
        "--responses",
        type=Path,
        default=None,
        help=f"외부 후보 응답 JSONL(없으면 {CANDIDATE_EOS} — 현재 코드의 결정론 튜터 출력)",
    )
    parser.add_argument("--inject", choices=AXES, default=None, help="축 하나에 나쁜 응답 주입")
    parser.add_argument("--self-test", action="store_true", help="8축 주입 변별력 자가 점검")
    parser.add_argument("--json", type=Path, default=None, help="JSON 리포트 출력 경로")
    parser.add_argument("--dump-responses", type=Path, default=None, help="후보 응답 JSONL 저장")
    parser.add_argument(
        "--build-eval-set", type=Path, default=None, help="평가셋을 코퍼스에서 다시 만들어 저장"
    )
    parser.add_argument("--failures", type=int, default=5, help="축마다 출력할 실패 사례 수")
    return parser


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"JSON 리포트 저장: {path}", flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    stage = "레지스트리"
    try:
        registry = load_registry()
        if args.build_eval_set is not None:
            stage = "평가셋 생성"
            text = dump_cases(build_cases(registry))
            args.build_eval_set.write_text(text, encoding="utf-8")
            print(f"평가셋 저장: {args.build_eval_set} ({text.count(chr(10))}건)", flush=True)
            return _EXIT_OK
        stage = "평가셋 적재"
        eval_set = load_eval_set(registry, args.eval_set)
        stage = "후보 응답"
        if args.responses is not None:
            responses = load_responses(args.responses)
            candidate = f"external:{args.responses}"
        else:
            responses = build_eos_candidate(eval_set, registry)
            candidate = CANDIDATE_EOS
    except (RegistryError, EvalSetError, CandidateError, OSError) as exc:
        print(f"측정 실패 — {stage} 단계: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return _EXIT_MEASUREMENT
    print(
        f"평가셋 {eval_set.source} · sha256 {eval_set.sha256[:12]} · 사례 {len(eval_set.cases)} · "
        f"후보 {candidate}",
        flush=True,
    )
    if args.dump_responses is not None:
        args.dump_responses.write_text(dump_responses(responses), encoding="utf-8")
        print(f"후보 응답 저장: {args.dump_responses}", flush=True)

    if args.self_test:
        st = run_self_test(eval_set, registry, responses, candidate=candidate, stream=sys.stdout)
        print("", flush=True)
        print(render_self_test(st), flush=True)
        if args.json is not None:
            _write_json(args.json, _self_test_json(st))
        return st.exit_code

    injection: str | None = args.inject
    if injection is not None:
        responses, changed = inject(injection, eval_set, registry, responses)
        print(f"주입 {injection}: 바뀐 응답 {changed}건", flush=True)
        if changed == 0:
            print("측정 실패 — 주입이 아무 응답도 바꾸지 않았다", file=sys.stderr, flush=True)
            return _EXIT_MEASUREMENT
    report = evaluate(
        eval_set, registry, responses, candidate=candidate, injection=injection, stream=sys.stdout
    )
    print("", flush=True)
    print(render_report(report, failures=args.failures), flush=True)
    if args.json is not None:
        _write_json(args.json, to_json(report))
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    sys.exit(main())
