"""WH-1 대리 지표 베이스라인 리포트 렌더 — 순수 단위테스트(hermetic·DB 무관).

`render_baseline_report`(SurrogateMetrics → 마크다운)와 `_resolve_params`(CLI 인자 파싱)만
검증한다. DB 조회 glue(`_run`·`main`의 asyncio.run)는 실 PG 통합검증 소관(pragma no cover).

핵심 불변(계산 계층과 동일 철학·CLAUDE.md "모르면 모른다"): 렌더는 "가짜 0 금지"를 표면화한다 —
MEASURED만 값을 보이고 NO_DATA는 값 대신 '—' + 사유(note)를 옮긴다. 12 지표 전부·R15 판정·
커버리지 카운트가 리포트에 나타나야 한다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from whymath_backend.harness.surrogate_baseline_report import (
    GrowthEvidenceReachState,
    _resolve_params,
    classify_reach_state,
    render_baseline_report,
    render_growth_evidence_reach_report,
    render_step_verification_section,
)
from whymath_backend.harness.wh1_evaluation import (
    HelpReductionValidation,
    Metric,
    MetricStatus,
    R15Verdict,
    StepVerificationAccounting,
    SurrogateMetrics,
)

# 12 지표 라벨(리포트에 전부 나타나야 함).
_METRIC_LABELS = (
    "① verify 통과율",
    "② 진단정확도(오프라인)",
    "③ 세션 완주율",
    "④ 턴당 토큰",
    "⑤ 도움 감소 곡선",
    "⑥ 보정 점수(Brier)",
    "⑦ 전이 점수(근사)",
    "⑧ 답 미루기 도달 깊이",
    "⑨ BKT 숙달 증가율",
    "⑩ 오개념 해소율",
    "⑪ 스스로 풀이 도달율",
    "⑮ 도움 요청 대 제공 비",
)


def _measured(value: float) -> Metric:
    return Metric(value=value, status=MetricStatus.MEASURED, note="실측 note")


def _no_data() -> Metric:
    return Metric(value=None, status=MetricStatus.NO_DATA, note="표본 0건 — 사유 note")


def _all_measured_metrics() -> SurrogateMetrics:
    """13 지표 전부 MEASURED인 SurrogateMetrics(커버리지 13/13 검증용)."""
    m = _measured(0.5)
    return SurrogateMetrics(
        verify_pass_rate=m,
        diagnosis_agreement_rate=m,
        session_completion_rate=m,
        tokens_per_turn=_measured(42.0),
        help_reduction_slope=_measured(-1.0),
        help_demand_supply_ratio=_measured(0.2),
        calibration_brier=_measured(0.1),
        transfer_score=m,
        hint_depth_reached=_measured(2.5),
        mastery_gain_rate=_measured(0.3),
        gap_recovery_leadtime_days=_measured(0.3),
        misconception_resolution_rate=m,
        self_solve_rate=m,
        help_reduction_validated=HelpReductionValidation(
            verdict=R15Verdict.GENUINE_IMPROVEMENT,
            help_slope=-1.0,
            accuracy_slope=0.5,
            difficulty_slope=0.4,
            note="진짜 개선 note",
        ),
        sample_sessions=4,
        sample_resolved_dialogues=3,
        sample_demand_events=1,
        window_start=datetime(2026, 1, 1, tzinfo=UTC),
        window_end=datetime(2026, 3, 1, tzinfo=UTC),
        user_scoped=False,
    )


def _mixed_metrics() -> SurrogateMetrics:
    """일부 MEASURED·일부 NO_DATA(가짜 0 금지 렌더 검증용)."""
    return SurrogateMetrics(
        verify_pass_rate=_measured(0.8),
        diagnosis_agreement_rate=_no_data(),
        session_completion_rate=_measured(0.75),
        tokens_per_turn=_no_data(),
        help_reduction_slope=_no_data(),
        help_demand_supply_ratio=_no_data(),
        calibration_brier=_no_data(),
        transfer_score=_no_data(),
        hint_depth_reached=_no_data(),
        mastery_gain_rate=_no_data(),
        gap_recovery_leadtime_days=_no_data(),
        misconception_resolution_rate=_no_data(),
        self_solve_rate=_no_data(),
        help_reduction_validated=HelpReductionValidation(
            verdict=R15Verdict.INSUFFICIENT_DATA,
            note="표본 부족 note",
        ),
        user_scoped=True,
    )


class TestRenderBaselineReport:
    def test_all_metric_labels_present(self) -> None:
        """12 지표 라벨이 전부 리포트에 렌더된다(빠짐 없음)."""
        report = render_baseline_report(_all_measured_metrics())
        for label in _METRIC_LABELS:
            assert label in report

    def test_coverage_count_all_measured(self) -> None:
        """전부 MEASURED → 커버리지 13/13."""
        report = render_baseline_report(_all_measured_metrics())
        assert "MEASURED 13/13" in report
        assert "코호트 전체" in report  # user_scoped=False

    def test_coverage_count_mixed(self) -> None:
        """혼합(2 MEASURED) → 커버리지 2/13·본인 스코프."""
        report = render_baseline_report(_mixed_metrics())
        assert "MEASURED 2/13" in report
        assert "NO_DATA/미계측 11/13" in report
        assert "본인(user)" in report  # user_scoped=True

    def test_no_data_shows_reason_not_zero(self) -> None:
        """NO_DATA 지표는 값 대신 '—' + 사유(note) — 가짜 0 금지."""
        report = render_baseline_report(_mixed_metrics())
        # NO_DATA 지표의 값은 0이 아니라 '—'
        assert "값 —" in report
        assert "표본 0건 — 사유 note" in report
        # 0.0000 같은 가짜 0이 NO_DATA 지표에서 나오지 않는다(MEASURED만 실수 값).
        assert "값 0.8000" in report  # MEASURED verify_pass_rate

    def test_measured_value_formatted(self) -> None:
        """MEASURED 값은 4자리 소수로 렌더."""
        report = render_baseline_report(_all_measured_metrics())
        assert "값 42.0000" in report  # tokens_per_turn
        assert "값 -1.0000" in report  # help_reduction_slope(음수=도움 감소)

    def test_r15_verdict_rendered(self) -> None:
        """R15 결합 판정 verdict·note가 렌더된다."""
        report = render_baseline_report(_all_measured_metrics())
        assert "R15 결합 판정" in report
        assert R15Verdict.GENUINE_IMPROVEMENT.value in report

    def test_window_infinite_when_none(self) -> None:
        """시간창 None → '무한 과거/미래'로 정직 표기."""
        report = render_baseline_report(_mixed_metrics())  # window None
        assert "무한 과거" in report
        assert "무한 미래" in report

    def test_sample_counts_rendered(self) -> None:
        """표본 수가 지표 행에 렌더된다."""
        report = render_baseline_report(_all_measured_metrics())
        assert "표본 4" in report  # sample_sessions
        assert "표본 3" in report  # sample_resolved_dialogues


class TestResolveParams:
    def test_all_none_defaults(self) -> None:
        """전부 미지정 → 코호트 전체·전체 기간(None, None, None)."""
        assert _resolve_params(None, None, None) == (None, None, None)

    def test_parses_uuid_and_iso(self) -> None:
        uid = uuid.uuid4()
        user, since, until = _resolve_params(
            str(uid), "2026-01-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00"
        )
        assert user == uid
        assert since == datetime(2026, 1, 1, tzinfo=UTC)
        assert until == datetime(2026, 3, 1, tzinfo=UTC)

    def test_invalid_uuid_raises(self) -> None:
        """잘못된 UUID는 즉시 실패(조용한 폴백 없음)."""
        with pytest.raises(ValueError):
            _resolve_params("not-a-uuid", None, None)

    def test_invalid_date_raises(self) -> None:
        with pytest.raises(ValueError):
            _resolve_params(None, "not-a-date", None)


class TestClassifyReachState:
    """`classify_reach_state` 순수 함수 — 구조적불가 > 무데이터 > 미도달/도달 우선순위(PED-06)."""

    def test_session_completion_is_no_longer_structurally_impossible(self) -> None:
        """EOS-131: ③(세션완주율)의 "영구 불가" 표기를 걷었다 — 세션 writer가 생겼으므로 ③도
        다른 지표처럼 상태·요청 수로 판정된다(종전 단언의 반대 방향 — 지우지 않고 뒤집었다)."""
        reached = classify_reach_state("session_completion_rate", MetricStatus.MEASURED, 100)
        no_data = classify_reach_state("session_completion_rate", MetricStatus.NO_DATA, 100)
        assert reached is GrowthEvidenceReachState.REACHED
        assert no_data is GrowthEvidenceReachState.NO_DATA

    def test_structurally_impossible_branch_still_overrides_everything(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """판정 분기 자체는 남아 있다 — 생산자가 사라진 지표가 다시 등재되면 무엇보다 우선한다."""
        from whymath_backend.harness import surrogate_baseline_report as report_mod

        monkeypatch.setattr(
            report_mod, "_STRUCTURALLY_IMPOSSIBLE_FIELDS", frozenset({"verify_pass_rate"})
        )
        state = classify_reach_state("verify_pass_rate", MetricStatus.MEASURED, 100)
        assert state is GrowthEvidenceReachState.STRUCTURALLY_IMPOSSIBLE

    def test_no_data_when_status_not_measured(self) -> None:
        state = classify_reach_state("verify_pass_rate", MetricStatus.NO_DATA, 0)
        assert state is GrowthEvidenceReachState.NO_DATA

    def test_unreached_when_measured_but_zero_requests(self) -> None:
        state = classify_reach_state("verify_pass_rate", MetricStatus.MEASURED, 0)
        assert state is GrowthEvidenceReachState.UNREACHED

    def test_reached_when_measured_and_requests_positive(self) -> None:
        """변별력(양방향) — 요청 수가 0→양수로 바뀌면 미도달이 실제로 해제된다."""
        unreached = classify_reach_state("verify_pass_rate", MetricStatus.MEASURED, 0)
        reached = classify_reach_state("verify_pass_rate", MetricStatus.MEASURED, 1)
        assert unreached is GrowthEvidenceReachState.UNREACHED
        assert reached is GrowthEvidenceReachState.REACHED
        assert unreached is not reached

    def test_reverts_to_unreached_when_requests_reset_to_zero(self) -> None:
        """변별력(양방향, 되돌림) — 도달 후 요청 수가 다시 0이면 미도달로 되돌아간다."""
        reached = classify_reach_state("verify_pass_rate", MetricStatus.MEASURED, 3)
        reverted = classify_reach_state("verify_pass_rate", MetricStatus.MEASURED, 0)
        assert reached is GrowthEvidenceReachState.REACHED
        assert reverted is GrowthEvidenceReachState.UNREACHED

    def test_no_data_takes_priority_over_reach_regardless_of_requests(self) -> None:
        """무데이터는 요청 수가 아무리 커도 도달로 격상되지 않는다(값이 없으니 보여줄 게 없음)."""
        state = classify_reach_state("calibration_brier", MetricStatus.NO_DATA, 1000)
        assert state is GrowthEvidenceReachState.NO_DATA


class TestRenderGrowthEvidenceReachReport:
    """`render_growth_evidence_reach_report` — 노출 계약 + 3상태를 얹은 확장 리포트(PED-06)."""

    def test_zero_requests_shown_as_unreached_not_zero_pass(self) -> None:
        """요청 0건은 '0건 통과'가 아니라 '미도달'로 표시(이중 회계 — VIZ-01·NLP-01 승계)."""
        report = render_growth_evidence_reach_report(_all_measured_metrics(), requests_total=0)
        assert "누적 요청 0건" in report
        assert "미도달" in report
        assert "0건 통과" not in report

    def test_session_completion_section_no_longer_says_structurally_impossible(self) -> None:
        """EOS-131: ③ 섹션에서 '구조적 불가' 라벨이 사라지고 실제 상태(여기선 측정됨·요청 0 →
        미도달)로 표시된다. 종전 단언('구조적 불가' 포함)의 반대 방향이다."""
        report = render_growth_evidence_reach_report(_mixed_metrics(), requests_total=0)
        assert "무데이터" in report
        section_start = report.index("## ③ 세션 완주율")
        section_end = report.index("## ④", section_start)
        section = report[section_start:section_end]
        assert "구조적 불가" not in section
        assert "미도달" in section

    def test_internal_only_fields_show_suppression_reason(self) -> None:
        report = render_growth_evidence_reach_report(_all_measured_metrics(), requests_total=5)
        assert "내부 전용" in report
        assert "노출 억제 사유" in report

    def test_hint_depth_suppressed_when_gaming_suspect(self) -> None:
        metrics = _all_measured_metrics()
        gaming = metrics.model_copy(
            update={
                "help_reduction_validated": HelpReductionValidation(
                    verdict=R15Verdict.GAMING_SUSPECT,
                    help_slope=-1.0,
                    accuracy_slope=-0.5,
                    difficulty_slope=None,
                    note="게이밍 의심 note",
                )
            }
        )
        report = render_growth_evidence_reach_report(gaming, requests_total=5)
        section_start = report.index("## ⑧")
        section_end = report.index("## ⑨", section_start)
        assert "노출 억제 사유" in report[section_start:section_end]

    def test_calibration_no_data_notes_missing_input_ui_not_rec01(self) -> None:
        """⑥ NO_DATA일 때 '입력 UI 부재'를 REC-01 입력 루프 미도달과 구분해 표기한다."""
        report = render_growth_evidence_reach_report(_mixed_metrics(), requests_total=0)
        section_start = report.index("## ⑥")
        section_end = report.index("## ⑦", section_start)
        section = report[section_start:section_end]
        assert "입력 UI" in section
        assert "REC-01" in section

    def test_reached_state_appears_when_requests_positive_and_measured(self) -> None:
        report = render_growth_evidence_reach_report(_all_measured_metrics(), requests_total=7)
        assert "누적 요청 7건" in report
        assert "도달상태 도달" in report


# ── S4-19 — 3상태 단계 검증 회계 내부 섹션 렌더 ─────────────────────────────────────
def _accounting(
    *,
    counted: int = 2,
    uncounted: int = 3,
    correct: int = 3,
    incorrect: int = 1,
    unverifiable: int = 1,
    decision_rate: float | None = 0.8,
    incorrect_rate: float | None = 0.2,
    ocr_gated: int = 1,
) -> StepVerificationAccounting:
    return StepVerificationAccounting(
        counted_events=counted,
        uncounted_events=uncounted,
        n_correct_total=correct,
        n_incorrect_total=incorrect,
        n_unverifiable_total=unverifiable,
        step_decision_rate=decision_rate,
        step_incorrect_rate=incorrect_rate,
        ocr_gated_events=ocr_gated,
    )


class TestRenderStepVerificationSection:
    """S4-19 — 내부 전용 섹션 렌더(결정론·NO_DATA 정직 표기·비보유 버킷 분리)."""

    def test_values_rendered_when_measured(self) -> None:
        """카운트·비율·ocr_gated가 전부 렌더되고 '내부 전용' 라벨이 붙는다."""
        section = render_step_verification_section(_accounting())
        assert "[내부 전용]" in section
        assert "S4-19" in section
        assert "counted(3카운트 보유·신판 유검증) 2건" in section
        assert "uncounted(구판 또는 검증 미실행 제출 — 구분 불가·한 버킷) 3건" in section
        assert "correct 3" in section
        assert "incorrect 1" in section
        assert "unverifiable 1" in section
        assert "step_decision_rate 0.8000" in section
        assert "step_incorrect_rate 0.2000" in section
        assert "ocr_gated" in section and "1건" in section

    def test_no_data_shows_dash_not_zero(self) -> None:
        """전이 표본 0 → 비율은 0이 아니라 '—' + NO_DATA 사유(가짜 0 금지)."""
        section = render_step_verification_section(
            _accounting(
                counted=0,
                uncounted=4,
                correct=0,
                incorrect=0,
                unverifiable=0,
                decision_rate=None,
                incorrect_rate=None,
                ocr_gated=0,
            )
        )
        assert "step_decision_rate —" in section
        assert "NO_DATA" in section
        assert "가짜 0 아님" in section
        assert "0.0000" not in section  # 비율 자리에 가짜 0이 렌더되지 않는다

    def test_deterministic(self) -> None:
        """같은 입력 → 같은 출력(결정론) — 리포트 diff 안정성."""
        acc = _accounting()
        assert render_step_verification_section(acc) == render_step_verification_section(acc)

    def test_student_route_non_exposure_stated(self) -> None:
        """섹션이 스스로 '학생 라우트 비노출'을 명시한다(노출 집행 별항의 가시화)."""
        section = render_step_verification_section(_accounting())
        assert "학생 라우트 비노출" in section
        assert "SurrogateMetrics 무변경" in section
