"""파일럿 KPI 베이스라인 — 순수 단위테스트(hermetic·DB/Langfuse 무관).

순수 조립 코어(`compute_retention`·`compute_verify_coverage`·`_cohort_cost_summary` 경유
`assemble_pilot_baseline`·`render_pilot_baseline`·`kpi_coverage`)와 CLI 파싱(`_resolve_params`)만
검증한다. DB/Langfuse/원장 glue(`_run`·`main`의 asyncio.run)는 실 통합 소관(pragma no cover).

핵심 불변(CLAUDE.md "모르면 모른다"·정직 NO_DATA): 각 KPI는 값(MEASURED) 또는 NO_DATA(사유)를
반드시 가진다. 렌더는 "가짜 0 금지"를 표면화한다 — NO_DATA는 값 대신 '—' + 사유(note)를 옮긴다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timezone

import pytest

from whymath_backend.harness.pilot_kpi_baseline import (
    KpiStatus,
    PilotKpiBaseline,
    RetentionReport,
    _cohort_cost_summary,
    _resolve_params,
    assemble_pilot_baseline,
    compute_retention,
    compute_verify_coverage,
    render_pilot_baseline,
)
from whymath_backend.harness.wh1_evaluation import Metric, MetricStatus
from whymath_backend.harness.wh1_shadow_harvest import Wh1ShadowDistributionSummary
from whymath_backend.ops.cost_report import CostReport, Distribution


def _measured(value: float) -> Metric:
    return Metric(value=value, status=MetricStatus.MEASURED, note="실측 note")


def _no_data() -> Metric:
    return Metric(value=None, status=MetricStatus.NO_DATA, note="표본 0건 — 사유 note")


def _dt(day: int, hour: int = 9) -> datetime:
    """2026-03-<day> <hour>:00 UTC — 리텐션 활동일 픽스처."""
    return datetime(2026, 3, day, hour, tzinfo=UTC)


# ──────────────────────────────────────────────────────────────────────────
# KPI2 리텐션 (신설·순수)
# ──────────────────────────────────────────────────────────────────────────


class TestComputeRetention:
    def test_empty_is_no_data(self) -> None:
        """세션 0건 → 모든 리텐션 지표 NO_DATA(가짜 0 금지)."""
        r = compute_retention([])
        assert r.distinct_users == 0
        assert r.returning_user_rate.status is MetricStatus.NO_DATA
        assert r.returning_user_rate.value is None
        assert r.sessions_per_user.status is MetricStatus.NO_DATA
        assert r.return_gap_days_median.status is MetricStatus.NO_DATA

    def test_excluded_rows_counted(self) -> None:
        """user_id·started_at 결손 행은 귀속 불가라 제외·별도 카운트(정직 회계)."""
        u = uuid.uuid4()
        r = compute_retention([(u, _dt(1)), (None, _dt(2)), (u, None)])
        assert r.excluded_rows == 2
        assert r.total_valid_sessions == 1
        assert r.distinct_users == 1

    def test_single_user_single_day_no_return(self) -> None:
        """1명·1일 → 복귀율 0(실측)·복귀 간격은 NO_DATA(복귀 없음·genuine 부재)."""
        u = uuid.uuid4()
        r = compute_retention([(u, _dt(1)), (u, _dt(1, hour=14))])
        assert r.distinct_users == 1
        assert r.returning_users == 0
        assert r.returning_user_rate.status is MetricStatus.MEASURED
        assert r.returning_user_rate.value == 0.0
        # 같은 날 2세션 → 활동일 1일 → 세션/사용자=2
        assert r.sessions_per_user.value == pytest.approx(2.0)
        assert r.active_days_per_user.value == pytest.approx(1.0)
        # 복귀(다른 날)가 없어 간격 NO_DATA
        assert r.return_gap_days_median.status is MetricStatus.NO_DATA

    def test_returning_user_gap_measured(self) -> None:
        """다른 날 재방문 → 복귀율·복귀 간격 MEASURED."""
        u = uuid.uuid4()
        # 3/1, 3/4 (간격 3일) 두 활동일
        r = compute_retention([(u, _dt(1)), (u, _dt(4))])
        assert r.returning_users == 1
        assert r.returning_user_rate.value == pytest.approx(1.0)
        assert r.return_gap_days_median.status is MetricStatus.MEASURED
        assert r.return_gap_days_median.value == pytest.approx(3.0)
        assert r.active_days_per_user.value == pytest.approx(2.0)

    def test_small_sample_caveat_in_note(self) -> None:
        """< 안정 표본(3명) → 값은 실측이되 note에 '기술통계(추론 아님)' 캐비엇."""
        u1, u2 = uuid.uuid4(), uuid.uuid4()
        r = compute_retention([(u1, _dt(1)), (u2, _dt(2))])
        assert r.distinct_users == 2
        assert r.returning_user_rate.status is MetricStatus.MEASURED
        assert "기술통계(추론 아님)" in r.returning_user_rate.note

    def test_gap_median_multiple_returning_users(self) -> None:
        """복귀 사용자 여럿의 간격 중앙값 — 5명 이상이면 캐비엇 없음."""
        users = [uuid.uuid4() for _ in range(5)]
        rows: list[tuple[uuid.UUID | None, datetime | None]] = []
        # 각 사용자 3/1·3/3 (간격 2일) — 전원 복귀
        for u in users:
            rows.append((u, _dt(1)))
            rows.append((u, _dt(3)))
        r = compute_retention(rows)
        assert r.distinct_users == 5
        assert r.returning_users == 5
        assert r.returning_user_rate.value == pytest.approx(1.0)
        assert r.return_gap_days_median.value == pytest.approx(2.0)
        assert "기술통계" not in r.returning_user_rate.note  # 5명 >= 안정 표본


# ──────────────────────────────────────────────────────────────────────────
# KPI4 코호트 비용 (ops.cost_report 재사용)
# ──────────────────────────────────────────────────────────────────────────


def _cost_report(
    *, event_count: int, cost_total: float | None, local_ratio: float | None
) -> CostReport:
    """테스트용 CostReport(관심 필드만·나머지 기본)."""
    cost_dist = (
        Distribution(
            count=event_count, p50=cost_total, p90=cost_total, mean=cost_total, total=cost_total
        )
        if cost_total is not None
        else Distribution(count=0)
    )
    empty = Distribution(count=0)
    return CostReport(
        event_count=event_count,
        input_tokens=empty,
        output_tokens=empty,
        cost_krw=cost_dist,
        latency_ms=empty,
        local_count=8 if local_ratio is not None else 0,
        cloud_count=2 if local_ratio is not None else 0,
        local_ratio=local_ratio,
        cost_tier_counts={},
        cache_hits=0,
        cache_total=0,
        cache_hit_rate=None,
        suggested_est_input_tokens=None,
        suggested_est_output_tokens=None,
    )


class TestCohortCostSummary:
    def test_none_report_is_no_data(self) -> None:
        """CostReport None(Langfuse 미설정) → 코호트 비용 NO_DATA."""
        s = _cohort_cost_summary(None)
        assert s.total_cost_krw.status is MetricStatus.NO_DATA
        assert s.local_ratio.status is MetricStatus.NO_DATA
        assert s.event_count == 0

    def test_zero_events_is_no_data(self) -> None:
        s = _cohort_cost_summary(_cost_report(event_count=0, cost_total=None, local_ratio=None))
        assert s.total_cost_krw.status is MetricStatus.NO_DATA

    def test_events_without_cost_sample_no_data(self) -> None:
        """이벤트는 있으나 실측 cost_krw 표본 0 → total은 NO_DATA(가짜 0 아님)."""
        s = _cohort_cost_summary(_cost_report(event_count=5, cost_total=None, local_ratio=0.8))
        assert s.total_cost_krw.status is MetricStatus.NO_DATA
        assert s.local_ratio.status is MetricStatus.MEASURED
        assert s.local_ratio.value == pytest.approx(0.8)

    def test_measured_cost_and_local_ratio(self) -> None:
        s = _cohort_cost_summary(_cost_report(event_count=10, cost_total=12.5, local_ratio=0.82))
        assert s.total_cost_krw.status is MetricStatus.MEASURED
        assert s.total_cost_krw.value == pytest.approx(12.5)
        assert s.local_ratio.value == pytest.approx(0.82)
        assert s.cost_sample == 10


# ──────────────────────────────────────────────────────────────────────────
# KPI5 입력 verify 커버리지 (wh1_shadow_harvest 3-state 재사용)
# ──────────────────────────────────────────────────────────────────────────


def _summary(
    *, total: int, correct: int, incorrect: int, unverifiable: int, none: int
) -> Wh1ShadowDistributionSummary:
    counts = {
        "correct": correct,
        "incorrect": incorrect,
        "unverifiable": unverifiable,
        "none": none,
    }
    ratios = {k: v / total for k, v in counts.items()} if total > 0 else {}
    return Wh1ShadowDistributionSummary(
        total=total,
        verdict_counts=counts,
        verdict_ratios=ratios,
        status_counts={},
        turn_verdicts={},
        # 전이별 집계 축(S3-07)은 KPI5(턴 라벨 3-state 커버리지)와 무관 — 이 픽스처는 전부
        # 구판(카운트 미보유)으로 둔다(필수 필드라 명시적으로 채움·정직 회계 계약 유지).
        transition_counts={"correct": 0, "incorrect": 0, "unverifiable": 0},
        transition_records=0,
        # 판정 모집단(none 제외·사전등록 분모)·전이 형태 축(S3-51)도 KPI5와 무관하지만
        # 필수 필드라 명시적으로 채운다 — 기본값으로 숨기면 산출 누락이 0으로 위장된다.
        verify_target_total=correct + incorrect + unverifiable,
        verify_target_ratios={},
        form_transition_counts={"equation": 0, "mixed": 0},
        equation_turns=0,
        form_records=0,
        form_legacy_records=total,
        legacy_records=total,
        distinct_dialogues=0,
        observed_at_min=None,
        observed_at_max=None,
    )


class TestComputeVerifyCoverage:
    def test_no_ledger_provided_is_no_data(self) -> None:
        """원장 미지정 → NO_DATA(사유에 --shadow-ledger 안내)."""
        v = compute_verify_coverage(None, ledger_provided=False)
        assert v.coverage.status is MetricStatus.NO_DATA
        assert "--shadow-ledger" in v.coverage.note

    def test_ledger_provided_but_empty_is_no_data(self) -> None:
        """원장 지정했으나 관측 0(부재/부식) → NO_DATA(다른 사유)."""
        v = compute_verify_coverage(None, ledger_provided=True)
        assert v.coverage.status is MetricStatus.NO_DATA
        assert "부재/부식" in v.coverage.note

    def test_zero_total_is_no_data(self) -> None:
        v = compute_verify_coverage(
            _summary(total=0, correct=0, incorrect=0, unverifiable=0, none=0), ledger_provided=True
        )
        assert v.coverage.status is MetricStatus.NO_DATA

    def test_decision_region_ratio(self) -> None:
        """결정 구간 = (correct+incorrect)/total — unverifiable·none 제외."""
        v = compute_verify_coverage(
            _summary(total=10, correct=4, incorrect=2, unverifiable=3, none=1), ledger_provided=True
        )
        assert v.coverage.status is MetricStatus.MEASURED
        assert v.coverage.value == pytest.approx(0.6)  # (4+2)/10
        assert v.total_observations == 10
        assert v.verdict_counts["unverifiable"] == 3


# ──────────────────────────────────────────────────────────────────────────
# 조립·롤업·렌더
# ──────────────────────────────────────────────────────────────────────────


def _assemble(
    *,
    mastery: Metric,
    retention: RetentionReport,
    cost_report: CostReport | None,
    verify_summary: Wh1ShadowDistributionSummary | None,
    verify_ledger_provided: bool = True,
    user_scoped: bool = False,
    mode_filter: str | None = None,
) -> PilotKpiBaseline:
    return assemble_pilot_baseline(
        mastery_gain=mastery,
        sample_mastery_groups=3,
        retention=retention,
        cost_report=cost_report,
        sample_dialogues_with_tokens=0,
        verify_summary=verify_summary,
        verify_ledger_provided=verify_ledger_provided,
        user_scoped=user_scoped,
        window_start=datetime(2026, 1, 1, tzinfo=UTC),
        window_end=datetime(2026, 3, 1, tzinfo=UTC),
        mode_filter=mode_filter,
    )


def _full_measured_baseline() -> PilotKpiBaseline:
    u1 = uuid.uuid4()
    u2 = uuid.uuid4()
    retention = compute_retention([(u1, _dt(1)), (u1, _dt(4)), (u2, _dt(1)), (u2, _dt(5))])
    return _assemble(
        mastery=_measured(0.3),
        retention=retention,
        cost_report=_cost_report(event_count=10, cost_total=12.5, local_ratio=0.82),
        verify_summary=_summary(total=10, correct=4, incorrect=2, unverifiable=3, none=1),
    )


class TestAssembleAndCoverage:
    def test_tone_always_no_data(self) -> None:
        """KPI3 톤안전은 라이브 미배선이라 항상 NO_DATA(목표 위반 0 note)."""
        b = _full_measured_baseline()
        assert b.tone_safety.status is MetricStatus.NO_DATA
        assert "위반 0" in b.tone_safety.note
        assert "S1-11 flip" in b.tone_safety.note

    def test_per_session_and_pnl_no_data(self) -> None:
        """KPI4 per-session·P&L은 NO_DATA(부분)."""
        b = _full_measured_baseline()
        assert b.per_session_cost.status is MetricStatus.NO_DATA
        assert b.pnl.status is MetricStatus.NO_DATA

    def test_kpi_rollup_cost_is_partial_when_cohort_measured(self) -> None:
        """코호트 비용 MEASURED → KPI4 롤업은 PARTIAL(per-session·P&L NO_DATA)."""
        b = _full_measured_baseline()
        coverage = b.kpi_coverage()
        assert coverage["KPI4 세션비용(P&L)"] is KpiStatus.PARTIAL

    def test_kpi_rollup_all_leaf_states(self) -> None:
        """전 KPI 롤업 — 학습성과/리텐션/verify=MEASURED·톤=NO_DATA·비용=PARTIAL."""
        b = _full_measured_baseline()
        coverage = b.kpi_coverage()
        assert coverage["KPI1 학습성과(숙달 델타)"] is KpiStatus.MEASURED
        assert coverage["KPI2 재사용/리텐션"] is KpiStatus.MEASURED
        assert coverage["KPI3 정서안전(톤 위반)"] is KpiStatus.NO_DATA
        assert coverage["KPI5 입력 verify 커버리지"] is KpiStatus.MEASURED

    def test_kpi_rollup_cost_no_data_when_cohort_absent(self) -> None:
        """코호트 비용 NO_DATA → KPI4 롤업도 NO_DATA(부분조차 아님)."""
        b = _assemble(
            mastery=_no_data(),
            retention=compute_retention([]),
            cost_report=None,
            verify_summary=None,
            verify_ledger_provided=False,
        )
        coverage = b.kpi_coverage()
        assert coverage["KPI4 세션비용(P&L)"] is KpiStatus.NO_DATA
        assert coverage["KPI1 학습성과(숙달 델타)"] is KpiStatus.NO_DATA
        assert coverage["KPI2 재사용/리텐션"] is KpiStatus.NO_DATA


class TestRenderPilotBaseline:
    def test_all_five_kpi_headers_present(self) -> None:
        """5 KPI 헤더가 전부 렌더된다(빠짐 없음)."""
        report = render_pilot_baseline(_full_measured_baseline())
        for header in (
            "KPI1 학습성과",
            "KPI2 재사용/리텐션",
            "KPI3 정서안전",
            "KPI4 세션비용",
            "KPI5 입력 verify 커버리지",
        ):
            assert header in report

    def test_no_data_shows_dash_not_zero(self) -> None:
        """NO_DATA 지표는 값 대신 '—'(가짜 0 금지)."""
        report = render_pilot_baseline(_full_measured_baseline())
        # 톤안전은 NO_DATA → 값 —
        assert "값 —" in report
        # MEASURED 코호트 비용은 실수 값
        assert "값 12.5000" in report

    def test_coverage_rollup_counts(self) -> None:
        """커버리지 롤업 카운트 — MEASURED 3·PARTIAL 1·NO_DATA 1 / 5."""
        report = render_pilot_baseline(_full_measured_baseline())
        assert "MEASURED 3 · PARTIAL 1 · NO_DATA 1 / 5" in report

    def test_mode_scope_honest_annotation(self) -> None:
        """mode 무관 정직 표기 — 5 KPI는 mode-scoped 아님."""
        report = render_pilot_baseline(_full_measured_baseline())
        assert "mode 무관" in report

    def test_mode_filter_shown_when_set(self) -> None:
        """--mode 설정 시 스코프에 그 값이 표기된다."""
        u = uuid.uuid4()
        b = _assemble(
            mastery=_measured(0.3),
            retention=compute_retention([(u, _dt(1))]),
            cost_report=None,
            verify_summary=None,
            verify_ledger_provided=False,
            mode_filter="suneung",
        )
        report = render_pilot_baseline(b)
        assert "suneung" in report

    def test_followup_section_present(self) -> None:
        """후속(범위 밖) note 섹션이 렌더된다."""
        report = render_pilot_baseline(_full_measured_baseline())
        assert "후속 (범위 밖" in report
        assert "톤필터 라이브 배선" in report
        assert "surrogate_baseline_report 참조" in report

    def test_scope_cohort_vs_user(self) -> None:
        report_cohort = render_pilot_baseline(_full_measured_baseline())
        assert "코호트 전체(파일럿)" in report_cohort
        u = uuid.uuid4()
        b = _assemble(
            mastery=_measured(0.3),
            retention=compute_retention([(u, _dt(1))]),
            cost_report=None,
            verify_summary=None,
            verify_ledger_provided=False,
            user_scoped=True,
        )
        assert "본인(user)" in render_pilot_baseline(b)

    def test_window_infinite_when_none(self) -> None:
        """시간창 None → '무한 과거/미래' 정직 표기."""
        u = uuid.uuid4()
        b = assemble_pilot_baseline(
            mastery_gain=_measured(0.3),
            sample_mastery_groups=1,
            retention=compute_retention([(u, _dt(1))]),
            cost_report=None,
            sample_dialogues_with_tokens=0,
            verify_summary=None,
            verify_ledger_provided=False,
            user_scoped=False,
            window_start=None,
            window_end=None,
            mode_filter=None,
        )
        report = render_pilot_baseline(b)
        assert "무한 과거" in report
        assert "무한 미래" in report


class TestResolveParams:
    def test_all_none_defaults(self) -> None:
        assert _resolve_params(None, None, None) == (None, None, None)

    def test_parses_uuid_and_iso(self) -> None:
        uid = uuid.uuid4()
        user, since, until = _resolve_params(
            str(uid), "2026-01-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00"
        )
        assert user == uid
        assert since == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert until == datetime(2026, 3, 1, tzinfo=timezone.utc)

    def test_invalid_uuid_raises(self) -> None:
        with pytest.raises(ValueError):
            _resolve_params("not-a-uuid", None, None)

    def test_invalid_date_raises(self) -> None:
        with pytest.raises(ValueError):
            _resolve_params(None, "not-a-date", None)
