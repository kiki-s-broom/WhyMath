"""성장 증거 학생 대면 노출 계약 — 순수 단위테스트(hermetic·DB 무관) (PED-06 D1 ①).

`docs/architecture/gamification_module_gap_review.md` §3 D1이 승계 대상으로 명시한 4개 규칙을
검증한다: ②④ 내부 전용 고정·⑧×R15(GAMING_SUSPECT) 조합 제약·⑥ 서술 변환(원 스칼라 미노출)·
비교/서열/순위 파생 함수 부재(모듈 자체에 그런 함수가 없다는 사실을 governance로 동결).
"""

from __future__ import annotations

import inspect

from whymath_backend.harness import growth_evidence_exposure as exposure_module
from whymath_backend.harness.growth_evidence_exposure import (
    ExposureTier,
    MetricExposure,
    classify_metric_exposure,
    narrate_calibration_brier,
)
from whymath_backend.harness.wh1_evaluation import (
    HelpReductionValidation,
    Metric,
    MetricStatus,
    R15Verdict,
    SurrogateMetrics,
)


def _metric(value: float | None = 0.5, status: MetricStatus = MetricStatus.MEASURED) -> Metric:
    return Metric(value=value, status=status, note="테스트 note")


def _metrics(verdict: R15Verdict) -> SurrogateMetrics:
    m = _metric()
    return SurrogateMetrics(
        verify_pass_rate=m,
        diagnosis_agreement_rate=m,
        session_completion_rate=m,
        tokens_per_turn=m,
        help_reduction_slope=m,
        calibration_brier=m,
        transfer_score=m,
        hint_depth_reached=m,
        mastery_gain_rate=m,
        gap_recovery_leadtime_days=m,
        misconception_resolution_rate=m,
        self_solve_rate=m,
        help_reduction_validated=HelpReductionValidation(
            verdict=verdict,
            help_slope=-1.0,
            accuracy_slope=0.5 if verdict is R15Verdict.GENUINE_IMPROVEMENT else -0.5,
            difficulty_slope=None,
            note="테스트 판정 note",
        ),
        sample_sessions=1,
        sample_resolved_dialogues=1,
        window_start=None,
        window_end=None,
        user_scoped=True,
    )


def test_internal_only_fields_never_exposable() -> None:
    """②(진단정확도)·④(턴당 토큰)는 R15 판정과 무관하게 항상 내부 전용."""
    for verdict in (R15Verdict.GENUINE_IMPROVEMENT, R15Verdict.GAMING_SUSPECT):
        result = classify_metric_exposure(_metrics(verdict))
        for field in ("diagnosis_agreement_rate", "tokens_per_turn"):
            assert result[field].tier is ExposureTier.INTERNAL_ONLY
            assert result[field].exposable_now is False
            assert result[field].suppressed_reason is not None


def test_hint_depth_suppressed_only_when_gaming_suspect() -> None:
    """⑧(답 미루기 도달 깊이)은 GAMING_SUSPECT일 때만 억제되고, GENUINE이면 노출 가능(변별력)."""
    genuine = classify_metric_exposure(_metrics(R15Verdict.GENUINE_IMPROVEMENT))
    gaming = classify_metric_exposure(_metrics(R15Verdict.GAMING_SUSPECT))

    assert genuine["hint_depth_reached"].exposable_now is True
    assert genuine["hint_depth_reached"].suppressed_reason is None

    assert gaming["hint_depth_reached"].exposable_now is False
    assert gaming["hint_depth_reached"].suppressed_reason is not None
    assert "GAMING_SUSPECT" in gaming["hint_depth_reached"].suppressed_reason


def test_other_no_help_reduction_and_insufficient_verdicts_do_not_suppress_hint_depth() -> None:
    """⑧ 억제는 GAMING_SUSPECT 전용 — 다른 verdict는 억제하지 않는다(과잉 억제 방지)."""
    for verdict in (R15Verdict.NO_HELP_REDUCTION, R15Verdict.INSUFFICIENT_DATA):
        result = classify_metric_exposure(_metrics(verdict))
        assert result["hint_depth_reached"].exposable_now is True


def test_gaming_suspect_label_not_exposed_as_a_field() -> None:
    """`MetricExposure` 스키마에 R15 verdict 원문을 실을 필드가 없다(단일 노출 판정 경로).

    `extra="forbid"` 모델이라 정의되지 않은 필드는 애초에 만들 수 없다 — 이 테스트는 그
    계약을 스키마 필드 목록으로 명시 동결한다(실수로 verdict 필드를 추가하면 실패).
    """
    field_names = set(MetricExposure.model_fields)
    assert field_names == {"field", "tier", "exposable_now", "suppressed_reason"}


def test_all_thirteen_fields_classified() -> None:
    """13지표 전부가 판정에 나타난다(누락 0).

    원 설계 11종 + 병합 편입 `help_demand_supply_ratio` + `gap_recovery_leadtime_days`(⑯·PED-13).
    """
    result = classify_metric_exposure(_metrics(R15Verdict.GENUINE_IMPROVEMENT))
    assert set(result) == {
        "verify_pass_rate",
        "diagnosis_agreement_rate",
        "session_completion_rate",
        "tokens_per_turn",
        "help_reduction_slope",
        "help_demand_supply_ratio",
        "calibration_brier",
        "transfer_score",
        "hint_depth_reached",
        "mastery_gain_rate",
        "misconception_resolution_rate",
        "self_solve_rate",
        "gap_recovery_leadtime_days",
    }


def test_narrate_calibration_brier_never_returns_raw_number() -> None:
    """⑥ 서술 변환 — 반환값이 숫자를 그대로 담지 않는다(원 스칼라 미노출)."""
    for value in (None, 0.05, 0.2, 0.5):
        narrated = narrate_calibration_brier(value)
        assert isinstance(narrated, str)
        # 소수점이 섞인 원값 형태(예: "0.05")가 그대로 문자열에 들어가면 실패 — 서술만 허용.
        assert str(value) not in narrated if value is not None else True


def test_narrate_calibration_brier_low_vs_high_differ() -> None:
    """좋은 보정(낮은 Brier)과 나쁜 보정(높은 Brier)의 서술이 실제로 달라진다(변별력)."""
    good = narrate_calibration_brier(0.05)
    bad = narrate_calibration_brier(0.9)
    none_case = narrate_calibration_brier(None)
    assert good != bad
    assert good != none_case
    assert bad != none_case


def test_no_ranking_or_percentile_derivation_function_exists() -> None:
    """비교·서열·순위 파생 함수가 이 모듈에 없다 — 계약 동결(governance).

    함수명에 백분위/랭크/순위/비교 계열 토큰이 있으면 실패한다. 새 함수를 추가할 때 이
    테스트가 실수로 그런 파생을 들여오는지 감시한다.
    """
    forbidden_tokens = ("percentile", "rank", "compare", "순위", "랭크", "석차")
    for name, _obj in inspect.getmembers(exposure_module, inspect.isfunction):
        lowered = name.lower()
        assert not any(
            token in lowered for token in forbidden_tokens
        ), f"금지된 파생 함수로 의심됨: {name}"


# ── MISC-20: ⑩ 오개념 해소율 강등 — PROVISIONAL(근사·노출 보류) 계층 ──────────────────
def test_resolution_rate_demoted_to_provisional_and_not_exposable() -> None:
    """(a) 강등 — 값이 is_active=false 비율(해소 *근사*)인데 근사임을 알릴 채널이 없다.

    학생은 "내가 오개념을 극복한 비율"로 읽는다(의사결정 우선순위 #1·"확실하지 않을 때 자신
    있게 말함 금지"). STUDENT_VISIBLE에서 내리되 INTERNAL_ONLY(시스템 품질·비용)와는 성격이
    달라 별도 계층 PROVISIONAL로 둔다 — 계산·리포트는 유지되고 학생 노출만 멈춘다(삭제 아님).
    """
    result = classify_metric_exposure(_metrics(R15Verdict.GENUINE_IMPROVEMENT))
    exp = result["misconception_resolution_rate"]
    assert exp.tier is ExposureTier.PROVISIONAL
    assert exp.exposable_now is False
    assert exp.suppressed_reason  # 사유 비어있지 않음(재승격 조건을 담는다)
    assert "재승격" in exp.suppressed_reason


def test_provisional_demotion_does_not_touch_other_student_visible_metrics() -> None:
    """⑥ 범위 밖 동결 — 다른 지표 티어는 그대로(mastery_gain_rate는 PED-14 소관)."""
    result = classify_metric_exposure(_metrics(R15Verdict.GENUINE_IMPROVEMENT))
    for field in (
        "verify_pass_rate",
        "session_completion_rate",
        "help_reduction_slope",
        "help_demand_supply_ratio",
        "transfer_score",
        "hint_depth_reached",
        "mastery_gain_rate",
        "gap_recovery_leadtime_days",
        "self_solve_rate",
        "calibration_brier",
    ):
        assert result[field].tier is ExposureTier.STUDENT_VISIBLE, field
        assert result[field].exposable_now is True, field


def test_provisional_is_the_only_field_in_that_tier() -> None:
    """강등 대상은 ⑩ 하나뿐 — PROVISIONAL이 다른 지표로 번지지 않는다(범위 동결)."""
    result = classify_metric_exposure(_metrics(R15Verdict.GENUINE_IMPROVEMENT))
    provisional = {f for f, e in result.items() if e.tier is ExposureTier.PROVISIONAL}
    assert provisional == {"misconception_resolution_rate"}
