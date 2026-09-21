"""WH-1 0단계 대리 지표 — *순수* 계산 단위테스트 (hermetic·FakeSession).

`compute_wh1_surrogate_metrics`의 집계 로직(① verify 통과율·③ 세션 완주율·④ 턴당 토큰·
⑤ 도움 감소 곡선 OLS 기울기)과 미계측 3종(②⑥⑦)의 status·note·value None 불변을 전수
검증한다. 집계 SQL의 *실 정확성*(GROUP BY·AVG·JSONB 캐스팅·정렬)은 통합테스트
(`test_me_integration` 류·실 PG)가 검증 — 여기선 FakeSession이 execute 큐로 count/AVG/
hint_level 행을 주입해 *래퍼 로직*(분기·status 결정·OLS 기울기·None 보존)만 본다.

핵심 불변(설계안 04a §8.4·CLAUDE.md "모르면 모른다"): 미계측 지표는 *절대* 0/stub을 내지
않는다 — value=None + status enum + 한국어 note. 표본 0이면 NO_DATA(가짜 0 아님). ⑤는
종단 표본이 _MIN_SLOPE_POINTS 미만이면 NO_DATA(가짜 기울기 금지).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from pytest import approx as pytest_approx
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.harness.wh1_evaluation import (
    _MIN_CALIBRATION_SAMPLES,
    _MIN_MASTERY_POINTS,
    _MIN_TRANSFER_PROBES,
    HelpReductionValidation,
    Metric,
    MetricStatus,
    R15Verdict,
    SurrogateMetrics,
    _calibration_from_pairs,
    _diagnosis_agreement_offline,
    _help_demand_supply_ratio_from_counts,
    _hint_depth_from_levels,
    _identify_transfer_probes,
    _judge_r15,
    _mastery_gain_from_gains,
    _mastery_gains_from_rows,
    _misconception_resolution_from_counts,
    _ols_slope,
    _self_solve_from_counts,
    _state_mismatch_from_counts,
    _strategy_diversity_from_values,
    _strategy_repeat_from_sequences,
    _transfer_from_probes,
    compute_wh1_surrogate_metrics,
)
from whymath_backend.schema.enums import SignaturePattern

# ⑯ 리드타임(PED-13) 도입으로 mastery 행이 (user, concept, mastery, measured_at) 4-튜플이
# 됐다. ⑨ 테스트는 간격에 관심이 없으므로 고정 2점만 둔다(간격 자체는 리드타임 전용
# 테스트 test_wh1_evaluation_gap_recovery_leadtime.py가 본다).
_MEASURED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_MEASURED_AT2 = datetime(2026, 1, 8, tzinfo=UTC)

# ⑦ 전이 테스트 단축 별칭(긴 enum 이름 회피·가독).
_P_COND = SignaturePattern.CONDITION_LIST
_P_GRAPH = SignaturePattern.GRAPH_SHAPE_INFERENCE
_P_SEQ = SignaturePattern.INDUCTIVE_SEQUENCE


class _FakeScalarResult:
    """`.scalar()`(count)·`.one()`(AVG, count)·`.all()`(행 목록)을 반환하는 execute 결과."""

    def __init__(self, scalar: Any = None, one: Any = None, all_rows: Any = None) -> None:
        self._scalar = scalar
        self._one = one
        self._all = all_rows if all_rows is not None else []

    def scalar(self) -> Any:
        return self._scalar

    def one(self) -> Any:
        return self._one

    def all(self) -> Any:
        return self._all


class _FakeSession:
    """execute 호출 순서대로 미리 큐에 넣은 결과를 돌려준다(stmt 무시).

    `compute_wh1_surrogate_metrics`의 execute 순서:
      1) total_sessions(count·scalar)
      2) completed_sessions(count·scalar)
      3) token row(AVG, count·one 튜플)
      4) verify row(passed_count, total·one 튜플)
      5) hint rows(event_at 오름차순 hint_level 행 목록·all)
      6) demand total(count·scalar) — ⑮ 도움 요청 대 제공 비의 분자(힌트요청 attempt_event 수·
         S3-16 소생). 분모는 5)의 hint_levels 표본을 재사용(새 all-row 쿼리 아님).
      7) accuracy rows(started_at 오름차순 is_correct 행 목록·all)
      8) difficulty rows(started_at 오름차순 (irt_b, difficulty_overall) 행 목록·all·Problem join)
      9) calibration rows((confidence_self_reported, is_correct) 쌍 목록·all)
     10) transfer rows(started_at 오름차순 (problem_id, signature_patterns, is_correct) 행
         목록·all·Problem join) — ⑦ 근사 전이 점수 식별 입력.
     11) mastery rows((user_id, concept_id, mastery, measured_at) 행 목록·all·(user,concept,measured_at)
         오름차순) — ⑨ BKT 숙달 증가율(그룹별 첫→마지막 차) 입력.
     12) misconception row((inactive_count, total_count)·one 튜플) — ⑩ 오개념 해소율
         (is_active=false 비율) 카운트.
     13) self-solve row((self_solved_count, resolved_total_count)·one 튜플) — ⑪ 스스로 풀이
         도달율(resolution=학생자력해결 / resolution NOT NULL) 카운트.
     14) strategy rows((dialogue_id, socratic_strategy) 행 목록·all·turn_order 오름차순) —
         ⑫⑬ 발문 전략 다양성·연속 반복률(PED-04) 입력.
    이 14개를 큐로 주입한다 — 정렬·실 SQL·join은 통합테스트가 실 PG로 검증.
    """

    def __init__(self, results: list[_FakeScalarResult]) -> None:
        self._results = list(results)
        self.execute_count = 0

    async def execute(self, _stmt: Any) -> _FakeScalarResult:
        result = self._results[self.execute_count]
        self.execute_count += 1
        return result


def _make_session(
    *,
    total_sessions: int,
    completed_sessions: int,
    avg_tokens: float | None,
    token_sample: int,
    verify_passed: int = 0,
    verify_total: int = 0,
    hint_levels: list[int | None] | None = None,
    demand_events: int = 0,
    accuracy_correct: list[bool | None] | None = None,
    difficulty_rows: list[tuple[float | None, float | None]] | None = None,
    calibration_pairs: list[tuple[float | None, bool | None]] | None = None,
    transfer_rows: list[tuple[Any, Any, bool]] | None = None,
    mastery_rows: list[tuple[Any, Any, float | None, Any]] | None = None,
    misconception_inactive: int = 0,
    misconception_total: int = 0,
    self_solved: int = 0,
    resolved_total: int = 0,
    hint_mismatch_flags: list[bool | None] | None = None,
    strategy_rows: list[tuple[Any, Any]] | None = None,
) -> AsyncSession:
    # ⑤ 힌트 쿼리는 이제 2컬럼(hint_level·client_state_mismatch, PED-04 ⑭ 동거)을 event_at
    # 오름차순으로 뽑으므로 행은 (level, mismatch) 튜플. `hint_mismatch_flags` 미지정이면 전부
    # None(=구 이벤트·태그 없음 — 본문이 False로 취급)으로 채워 기존 호출자를 그대로 둔다.
    hint_levels_list = hint_levels or []
    mismatch_flags = hint_mismatch_flags or [None] * len(hint_levels_list)
    hint_rows = list(zip(hint_levels_list, mismatch_flags, strict=False))
    # R15 정답률 쿼리는 단일 컬럼(is_correct)을 started_at 오름차순으로 뽑으므로 행은 (bool,) 튜플.
    accuracy_rows = [(c,) for c in (accuracy_correct or [])]
    # R15 난이도 쿼리는 Problem join으로 (irt_difficulty_b, difficulty_overall)을 started_at
    # 오름차순으로 뽑는다 — 행은 (irt_b, difficulty) 튜플. problem_id NULL·미매칭 행은 join이
    # 이미 떨군 상태(실 PG)이므로 여기엔 매칭된 행만 주입한다(둘 다 None이면 본문이 유효 b로 제외).
    diff_rows = list(difficulty_rows or [])
    # ⑥ 보정 쿼리는 (confidence_self_reported, is_correct) 쌍을 뽑으므로 행은 (conf, correct) 튜플.
    # 둘 중 하나라도 None인 행도 주입할 수 있게 그대로 둔다 — 본문이 None 쌍을 걸러낸다.
    calib_rows = list(calibration_pairs or [])
    # ⑦ 전이 쿼리는 Problem join으로 (problem_id, signature_patterns, is_correct)를 started_at
    # 오름차순으로 뽑는다 — 행은 (problem_id, patterns, is_correct) 튜플. is_correct는 본문이
    # accuracy_conds(IS NOT NULL)로 좁혀 join하므로 bool만 들어온다. problem_id None·패턴 빈 행도
    # 주입할 수 있게 그대로 둔다 — 본문/식별 함수가 초견·사전노출 규칙으로 처리한다.
    xfer_rows = list(transfer_rows or [])
    # ⑨ 숙달 쿼리는 (user_id, concept_id, mastery)를 (user,concept,measured_at) 오름차순으로 뽑는다
    # — 행은 (user, concept, mastery) 튜플. 그룹 내 오름차순은 본문 order_by가 보장하므로 여기선
    # 그 순서대로 주입한다(첫 등장=최이른·마지막=최근). mastery None은 본문이 필터로 제외한다.
    mstry_rows = list(mastery_rows or [])
    return cast(
        AsyncSession,
        _FakeSession(
            [
                _FakeScalarResult(scalar=total_sessions),
                _FakeScalarResult(scalar=completed_sessions),
                _FakeScalarResult(one=(avg_tokens, token_sample)),
                _FakeScalarResult(one=(verify_passed, verify_total)),
                _FakeScalarResult(all_rows=hint_rows),
                _FakeScalarResult(scalar=demand_events),
                _FakeScalarResult(all_rows=accuracy_rows),
                _FakeScalarResult(all_rows=diff_rows),
                _FakeScalarResult(all_rows=calib_rows),
                _FakeScalarResult(all_rows=xfer_rows),
                _FakeScalarResult(all_rows=mstry_rows),
                _FakeScalarResult(one=(misconception_inactive, misconception_total)),
                _FakeScalarResult(one=(self_solved, resolved_total)),
                _FakeScalarResult(all_rows=list(strategy_rows or [])),
            ]
        ),
    )


# ── ③ 세션 완주율 ────────────────────────────────────────────────────────────
class TestSessionCompletionRate:
    async def test_measured_ratio(self) -> None:
        """완주(ended_at NOT NULL) 3/4 → MEASURED·value 0.75·표본 4."""
        session = _make_session(
            total_sessions=4, completed_sessions=3, avg_tokens=None, token_sample=0
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.session_completion_rate.status is MetricStatus.MEASURED
        assert m.session_completion_rate.value == 0.75
        assert m.sample_sessions == 4

    async def test_all_completed(self) -> None:
        session = _make_session(
            total_sessions=2, completed_sessions=2, avg_tokens=None, token_sample=0
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.session_completion_rate.value == 1.0
        assert m.session_completion_rate.status is MetricStatus.MEASURED

    async def test_none_completed(self) -> None:
        session = _make_session(
            total_sessions=3, completed_sessions=0, avg_tokens=None, token_sample=0
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.session_completion_rate.value == 0.0
        assert m.session_completion_rate.status is MetricStatus.MEASURED

    async def test_zero_total_is_no_data_not_zero(self) -> None:
        """표본 0 → NO_DATA·value None(가짜 0 금지·날조 회피 핵심)."""
        session = _make_session(
            total_sessions=0, completed_sessions=0, avg_tokens=None, token_sample=0
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.session_completion_rate.status is MetricStatus.NO_DATA
        assert m.session_completion_rate.value is None  # 0이 아님!
        assert m.sample_sessions == 0
        assert "0건" in m.session_completion_rate.note


# ── ④ 턴당 토큰 ──────────────────────────────────────────────────────────────
class TestTokensPerTurn:
    async def test_measured(self) -> None:
        """토큰 채워진 대화 있음 → MEASURED·AVG 값·표본 수."""
        session = _make_session(
            total_sessions=1, completed_sessions=1, avg_tokens=42.5, token_sample=10
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.tokens_per_turn.status is MetricStatus.MEASURED
        assert m.tokens_per_turn.value == 42.5
        assert m.sample_dialogues == 10

    async def test_no_qualifying_rows_is_no_data(self) -> None:
        """토큰·턴 채워진 행 0 → NO_DATA·value None(토큰 미적재면 정직하게 NO_DATA)."""
        session = _make_session(
            total_sessions=1, completed_sessions=1, avg_tokens=None, token_sample=0
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.tokens_per_turn.status is MetricStatus.NO_DATA
        assert m.tokens_per_turn.value is None  # 0이 아님!
        assert m.sample_dialogues == 0
        assert "미적재" in m.tokens_per_turn.note

    async def test_avg_none_with_sample_still_no_data(self) -> None:
        """count>0이나 AVG가 None(이론적 경계)이면 NO_DATA로 안전 처리."""
        session = _make_session(
            total_sessions=1, completed_sessions=1, avg_tokens=None, token_sample=3
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.tokens_per_turn.status is MetricStatus.NO_DATA
        assert m.tokens_per_turn.value is None


# ── ① verify 통과율 ──────────────────────────────────────────────────────────
class TestVerifyPassRate:
    async def test_measured_ratio(self) -> None:
        """검산결과 이벤트 passed 3/4 → MEASURED·value 0.75·표본 4."""
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            verify_passed=3,
            verify_total=4,
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.verify_pass_rate.status is MetricStatus.MEASURED
        assert m.verify_pass_rate.value == 0.75
        assert m.sample_verify_events == 4

    async def test_all_passed(self) -> None:
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            verify_passed=2,
            verify_total=2,
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.verify_pass_rate.value == 1.0
        assert m.verify_pass_rate.status is MetricStatus.MEASURED

    async def test_none_passed(self) -> None:
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            verify_passed=0,
            verify_total=5,
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.verify_pass_rate.value == 0.0
        assert m.verify_pass_rate.status is MetricStatus.MEASURED

    async def test_zero_events_is_no_data_not_zero(self) -> None:
        """검산결과 이벤트 0건 → NO_DATA·value None(가짜 0 금지)."""
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            verify_passed=0,
            verify_total=0,
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.verify_pass_rate.status is MetricStatus.NO_DATA
        assert m.verify_pass_rate.value is None  # 0이 아님!
        assert m.sample_verify_events == 0

    async def test_note_is_honest_binary_verify(self) -> None:
        """MEASURED note에 '미적발'(binary)·S4-19 3상태 병기 안내 정직 표기.

        S4-19 갱신: 3상태 파생 회계(compute_step_verification_accounting)가 병기 착지해
        'unverifiable 미구분' 한계 서술이 3상태 병기 안내로 바뀌었다 — binary 값·계산식은
        불변(이중 회계)임을 note가 스스로 밝힌다.
        """
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            verify_passed=1,
            verify_total=2,
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert "미적발" in m.verify_pass_rate.note
        assert "binary" in m.verify_pass_rate.note  # 이 지표 자체는 여전히 binary(값 불변)
        assert "3상태" in m.verify_pass_rate.note  # S4-19 병기 파생으로 한계가 커버됨을 안내
        assert "S4-19" in m.verify_pass_rate.note
        assert "unverifiable 미구분" not in m.verify_pass_rate.note  # 구 한계 서술은 갱신됨


# ── ⑤ 도움 감소 곡선(OLS 기울기) ─────────────────────────────────────────────
class TestHelpReductionSlope:
    async def _slope(self, hint_levels: list[int | None]) -> Metric:
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            hint_levels=hint_levels,
        )
        return (await compute_wh1_surrogate_metrics(session)).help_reduction_slope

    async def test_decreasing_trend_negative_slope_measured(self) -> None:
        """감소 추세(4→3→2→1) → MEASURED·음수 기울기(도움 감소=개선)."""
        m = await self._slope([4, 3, 2, 1])
        assert m.status is MetricStatus.MEASURED
        assert m.value is not None
        assert m.value < 0
        assert m.value == -1.0  # 완전 등차 −1

    async def test_increasing_trend_positive_slope_measured(self) -> None:
        """증가 추세(1→2→3) → MEASURED·양수 기울기(도움 증가=악화)."""
        m = await self._slope([1, 2, 3])
        assert m.status is MetricStatus.MEASURED
        assert m.value is not None
        assert m.value > 0
        assert m.value == 1.0

    async def test_too_few_points_is_no_data_not_fake_slope(self) -> None:
        """포인트 < _MIN_SLOPE_POINTS(3) → NO_DATA·value None(가짜 기울기/0 금지)."""
        m = await self._slope([4, 2])  # 2점 < 3
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None  # 0도, 기울기도 아님!
        assert "표본 부족" in m.note

    async def test_zero_points_is_no_data(self) -> None:
        m = await self._slope([])
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None

    async def test_constant_levels_zero_variance_is_no_data(self) -> None:
        """동일 레벨(3,3,3) — y 분산 0이지만 x 분산은 양수라 기울기 0(MEASURED·평탄).

        x(0,1,2) 분산은 양수이므로 OLS는 정의되고 기울기는 정확히 0(평탄=도움 불변). 0 분산
        NO_DATA 가드는 *x축* 분산이 0일 때만(이론적 경계)이라 동일 레벨은 MEASURED 0이다 —
        이건 날조 0이 아니라 *실측된 평탄*이다(입력이 실제로 평평).
        """
        m = await self._slope([3, 3, 3])
        assert m.status is MetricStatus.MEASURED
        assert m.value == 0.0

    async def test_none_levels_filtered_then_too_few(self) -> None:
        """JSONB 파싱 실패(None) 행은 걸러져 유효 포인트만 카운트 — 2개만 유효→NO_DATA."""
        m = await self._slope([4, None, 2, None])  # 유효 2점 < 3
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None

    async def test_note_honest_r15_and_longitudinal(self) -> None:
        """MEASURED note에 'R15'(정확률 교차검증 미반영)·'종단' 정직 표기."""
        m = await self._slope([4, 3, 2, 1])
        assert "R15" in m.note
        assert "종단" in m.note


# ── 미계측 격상 회귀 (②⑥⑦ 모두 더는 REQUIRES_TOOL/REQUIRES_DATA stub 아님) ──────────────
class TestUnmeasuredMetrics:
    async def _metrics(self) -> SurrogateMetrics:
        session = _make_session(
            total_sessions=1, completed_sessions=1, avg_tokens=10.0, token_sample=5
        )
        return await compute_wh1_surrogate_metrics(session)

    async def test_transfer_no_longer_requires_tool(self) -> None:
        """⑦ 전이 점수 — 전이 프로브 0건(전이 행 미주입)이면 REQUIRES_TOOL이 아니라 NO_DATA.

        근사 전이 점수로 격상돼 더는 고정 REQUIRES_TOOL stub이 아니다 — 데이터(전이 프로브)가
        없으면 NO_DATA(가짜 0 금지)·쌓이면 MEASURED.
        """
        m = (await self._metrics()).transfer_score
        assert m.status is MetricStatus.NO_DATA  # REQUIRES_TOOL 아님
        assert m.value is None
        assert "전이" in m.note
        assert "assign_transfer_probe" not in m.note or "다른" in m.note  # 근사 표기 존재

    async def test_calibration_no_longer_requires_tool(self) -> None:
        """⑥ 보정 점수 — 보정 쌍 0건이면 REQUIRES_TOOL이 아니라 NO_DATA(stale 진단 교정)."""
        m = (await self._metrics()).calibration_brier
        assert m.status is MetricStatus.NO_DATA  # REQUIRES_TOOL 아님
        assert m.value is None
        assert "elicit_prediction" not in m.note

    async def test_transfer_value_none_when_no_data(self) -> None:
        """전이 프로브 부족 ⑦ value None — 0/stub 아님(날조 0 불변)."""
        m = (await self._metrics()).transfer_score
        assert isinstance(m, Metric)
        assert m.value is None
        assert m.status is not MetricStatus.MEASURED
        assert m.note  # 한국어 note 비어있지 않음


# ── ② 진단-실제 오개념 일치율 (오프라인 진단정확도·substring recall) ─────────────────
class TestDiagnosisAgreementOffline:
    """`_diagnosis_agreement_offline`(canned hit/miss)·MEASURED/NO_DATA·정직 note·시스템 지표.

    실 프로브 파일 로드는 L4 통합 테스트(`tests/backend/l4/test_misconception_probes.py`)가
    검증한다 — 여기선 (hit, total) 튜플을 직접 넣어 *Metric 변환*(비율·상태·note)만 못 박는다.
    """

    def test_measured_recall_value_and_status(self) -> None:
        """hit 45/total 60 → MEASURED·value 0.75·표본은 호출자(하네스) 책임."""
        m = _diagnosis_agreement_offline(45, 60)
        assert m.status is MetricStatus.MEASURED
        assert m.value == 0.75

    def test_all_hit(self) -> None:
        m = _diagnosis_agreement_offline(60, 60)
        assert m.value == 1.0
        assert m.status is MetricStatus.MEASURED

    def test_no_hit_is_measured_zero_not_no_data(self) -> None:
        """recall 프로브는 있는데 hit 0 → MEASURED value 0.0(*실측된* 0이지 날조 0 아님)."""
        m = _diagnosis_agreement_offline(0, 60)
        assert m.status is MetricStatus.MEASURED
        assert m.value == 0.0

    def test_zero_probes_is_no_data_not_fabricated_zero(self) -> None:
        """recall 프로브 0건(라벨셋 부재/전부 FP) → NO_DATA·value None(가짜 0 금지)."""
        m = _diagnosis_agreement_offline(0, 0)
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None
        assert "0건" in m.note

    def test_note_is_honest_offline_system_metric(self) -> None:
        """정직 note — 오프라인·substring·시스템 지표(LIVE per-user 아님)·precision 미반영 명시."""
        m = _diagnosis_agreement_offline(45, 60)
        assert m.note  # 비어있지 않음
        # LIVE 학생별 ground-truth가 아님(시스템 지표) 명시
        assert "ground-truth" in m.note
        assert "전 user 동일" in m.note
        # substring 보수적 기준선·precision은 semantic_eval 별도 명시
        assert "substring" in m.note
        assert "precision" in m.note or "FP율" in m.note

    async def test_harness_surfaces_offline_recall_measured(self) -> None:
        """하네스 통합 — DB와 무관하게 ②가 실 프로브셋(61건)으로 MEASURED가 된다(시스템 지표).

        `compute_diagnostic_recall`이 실 패키지 프로브셋을 로드하므로 FakeSession이어도 ②는
        MEASURED다(user/기간 무관·전 user 동일값). value∈[0,1]·표본=recall 프로브 수만 단언
        (구체 recall 값은 substring 매처 품질이라 L4 통합이 검증·여기선 배선·구조).
        """
        session = _make_session(
            total_sessions=1, completed_sessions=1, avg_tokens=10.0, token_sample=5
        )
        m = await compute_wh1_surrogate_metrics(session)
        diag = m.diagnosis_agreement_rate
        assert diag.status is MetricStatus.MEASURED
        assert diag.value is not None and 0.0 <= diag.value <= 1.0
        # 표본 메타 = recall 프로브 수(DB 표본 아님·프로브셋 크기·현재 89건)
        assert m.sample_diagnostic_probes == 98
        assert "오프라인 진단정확도" in diag.note

    async def test_offline_metric_invariant_to_user_and_window(self) -> None:
        """② 시스템 지표 — user_id/since/until을 바꿔도 value가 불변(전 user 동일값)."""
        session_a = _make_session(
            total_sessions=1, completed_sessions=1, avg_tokens=10.0, token_sample=5
        )
        session_b = _make_session(
            total_sessions=3, completed_sessions=2, avg_tokens=20.0, token_sample=9
        )
        m_cohort = await compute_wh1_surrogate_metrics(session_a)
        m_user = await compute_wh1_surrogate_metrics(
            session_b,
            user_id=uuid.uuid4(),
            since=datetime(2026, 1, 1, tzinfo=UTC),
            until=datetime(2026, 6, 1, tzinfo=UTC),
        )
        # 진단정확도는 user/기간과 무관(시스템 지표) — value·표본 동일.
        assert m_cohort.diagnosis_agreement_rate.value == m_user.diagnosis_agreement_rate.value
        assert m_cohort.sample_diagnostic_probes == m_user.sample_diagnostic_probes


# ── ⑥ 보정 점수(Brier) — _calibration_from_pairs 순수 단위 ────────────────────────
class TestCalibrationFromPairs:
    """Brier=mean((conf−outcome)²)·MIN 가드·MEASURED/NO_DATA(순수·FakeSession 불요)."""

    def _pairs(self, n: int, conf: float, correct: bool) -> list[tuple[float, bool]]:
        return [(conf, correct)] * n

    def test_perfect_calibration_is_zero(self) -> None:
        """완벽 보정(conf=outcome) → Brier 0. conf=1 정답·conf=0 오답 섞어도 0."""
        pairs: list[tuple[float, bool]] = [
            (1.0, True),
            (1.0, True),
            (0.0, False),
            (0.0, False),
            (1.0, True),
        ]
        m = _calibration_from_pairs(pairs)
        assert m.status is MetricStatus.MEASURED
        assert m.value == 0.0  # (1−1)²·(0−0)² 평균 = 0

    def test_total_miscalibration_is_one(self) -> None:
        """완전 오보정(conf=1인데 오답·conf=0인데 정답) → Brier 1."""
        pairs: list[tuple[float, bool]] = [
            (1.0, False),
            (1.0, False),
            (0.0, True),
            (0.0, True),
            (1.0, False),
        ]
        m = _calibration_from_pairs(pairs)
        assert m.status is MetricStatus.MEASURED
        assert m.value == 1.0  # (1−0)²·(0−1)² 평균 = 1

    def test_mixed_average(self) -> None:
        """혼합 — conf 0.5·outcome 다양 → 정확한 평균 제곱오차.

        5쌍: (0.5,T)=0.25·(0.5,F)=0.25·(1.0,T)=0·(0.0,F)=0·(0.8,T)=0.04 → 합 0.54/5=0.108.
        """
        pairs: list[tuple[float, bool]] = [
            (0.5, True),
            (0.5, False),
            (1.0, True),
            (0.0, False),
            (0.8, True),
        ]
        m = _calibration_from_pairs(pairs)
        assert m.status is MetricStatus.MEASURED
        assert m.value is not None
        assert abs(m.value - 0.108) < 1e-9

    def test_too_few_pairs_is_no_data_not_fake_zero(self) -> None:
        """쌍 < _MIN_CALIBRATION_SAMPLES → NO_DATA·value None(가짜 0/Brier 금지)."""
        m = _calibration_from_pairs(self._pairs(_MIN_CALIBRATION_SAMPLES - 1, 0.5, True))
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None  # 0이 아님!
        assert "표본 부족" in m.note

    def test_exactly_min_pairs_is_measured(self) -> None:
        """정확히 _MIN_CALIBRATION_SAMPLES 쌍 → MEASURED(경계 inclusive)."""
        m = _calibration_from_pairs(self._pairs(_MIN_CALIBRATION_SAMPLES, 0.5, True))
        assert m.status is MetricStatus.MEASURED
        assert m.value is not None

    def test_empty_is_no_data(self) -> None:
        m = _calibration_from_pairs([])
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None

    def test_measured_note_is_honest(self) -> None:
        """MEASURED note에 자기보고·과신/과소신 코칭 후속·§11.4 정직 표기."""
        m = _calibration_from_pairs(self._pairs(_MIN_CALIBRATION_SAMPLES, 0.6, True))
        assert "자기보고" in m.note
        assert "과신/과소신" in m.note
        assert "§11.4" in m.note


# ── ⑥ 보정 점수 — compute_wh1_surrogate_metrics 통합(FakeSession 쌍 주입) ──────────
class TestCalibrationBrierIntegratedWithCompute:
    async def _brier(
        self, calibration_pairs: list[tuple[float | None, bool | None]] | None
    ) -> Metric:
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            calibration_pairs=calibration_pairs,
        )
        return (await compute_wh1_surrogate_metrics(session)).calibration_brier

    async def test_measured_perfect(self) -> None:
        """완벽 보정 5쌍 → MEASURED·Brier 0."""
        m = await self._brier([(1.0, True), (1.0, True), (0.0, False), (0.0, False), (1.0, True)])
        assert m.status is MetricStatus.MEASURED
        assert m.value == 0.0

    async def test_measured_total_miscalibration(self) -> None:
        """완전 오보정 5쌍 → MEASURED·Brier 1."""
        m = await self._brier([(1.0, False), (1.0, False), (0.0, True), (0.0, True), (1.0, False)])
        assert m.status is MetricStatus.MEASURED
        assert m.value == 1.0

    async def test_too_few_pairs_no_data(self) -> None:
        """유효 쌍 < MIN → NO_DATA·value None(날조 0 금지)."""
        m = await self._brier([(0.5, True), (0.5, False)])  # 2쌍 < 5
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None

    async def test_none_confidence_excluded(self) -> None:
        """confidence None 행은 제외 — 유효 쌍만 카운트(둘 다 채워진 쌍만)."""
        # 유효 4쌍(< 5)만 — confidence None 2개는 제외되어 표본에 안 들어감 → NO_DATA.
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            calibration_pairs=[
                (0.9, True),
                (None, True),
                (0.8, False),
                (None, False),
                (0.7, True),
                (0.6, True),
            ],
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.sample_calibration_pairs == 4  # None confidence 2개 제외
        assert m.calibration_brier.status is MetricStatus.NO_DATA  # 4 < 5

    async def test_none_is_correct_excluded(self) -> None:
        """is_correct None 행은 제외 — 5쌍 중 None 섞이면 유효 쌍만."""
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            calibration_pairs=[
                (0.9, True),
                (0.8, None),
                (0.2, False),
                (0.1, False),
                (0.7, True),
                (0.6, True),
            ],
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.sample_calibration_pairs == 5  # is_correct None 1개 제외 → 5 유효
        assert m.calibration_brier.status is MetricStatus.MEASURED


# ── ⑦ 근사 전이 점수 — _identify_transfer_probes 순수 식별 단위 ──────────────────────
class TestIdentifyTransferProbes:
    """전이 프로브 식별(같은 패턴·다른 problem_id·사전 노출 후 초견) 순수 로직.

    입력은 started_at 오름차순 (problem_id, signature_patterns, is_correct) 시퀀스. 반환은
    전이 프로브로 인정된 attempt의 is_correct 목록(패턴별 독립 카운트).
    """

    def test_basic_transfer_probe_after_prior_exposure(self) -> None:
        """패턴 P를 P1에서 본 뒤 *다른* 문항 P2 초견 → P2가 전이 프로브(is_correct 집계)."""
        pa, pb = uuid.uuid4(), uuid.uuid4()
        rows = [
            (pa, [_P_COND], False),  # P1 첫 등장(사전 노출 없음) → 프로브 아님
            (pb, [_P_COND], True),  # P2 초견·P1에서 패턴 본 적 있음 → 전이 프로브(True)
        ]
        assert _identify_transfer_probes(rows) == [True]

    def test_first_pattern_appearance_excluded(self) -> None:
        """사전 노출 없는 첫 패턴 등장은 전이 프로브 아님(같은 패턴 다른 문항 이력 없음)."""
        pa = uuid.uuid4()
        rows = [(pa, [_P_COND], True)]  # 첫 등장·사전 노출 없음
        assert _identify_transfer_probes(rows) == []

    def test_same_problem_retry_excluded(self) -> None:
        """같은 problem_id 재시도는 초견이 아니므로 전이 프로브 제외(첫 등장만)."""
        pa, pb = uuid.uuid4(), uuid.uuid4()
        rows = [
            (pa, [_P_COND], False),  # P1 첫 등장
            (pb, [_P_COND], True),  # P2 초견·사전 노출 → 전이 프로브(True)
            (pb, [_P_COND], False),  # P2 *재시도*(초견 아님) → 제외
        ]
        assert _identify_transfer_probes(rows) == [True]

    def test_same_attempt_pattern_not_self_exposure(self) -> None:
        """같은 패턴을 처음 보는 문항이 두 번째로 등장해야 사전 노출 — 한 문항 안에선 아님.

        P1·P2가 모두 P_COND. P1은 첫 등장(사전 노출 0)·P2는 초견이고 P1이 사전 노출 →
        P2만 전이 프로브.
        """
        pa, pb, pc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        rows = [
            (pa, [_P_COND], True),  # 첫 등장
            (pb, [_P_COND], True),  # 초견·사전 노출(pa) → 프로브
            (pc, [_P_COND], False),  # 초견·사전 노출(pa,pb) → 프로브
        ]
        assert _identify_transfer_probes(rows) == [True, False]

    def test_multiple_patterns_independent_count(self) -> None:
        """한 attempt가 여러 패턴 전이 프로브면 패턴별 독립 카운트(중복·같은 is_correct 공유)."""
        pa, pb, pc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        rows = [
            (pa, [_P_COND, _P_GRAPH], True),  # 두 패턴 첫 등장(사전 노출 0)
            # pb 초견·두 패턴 모두 pa에서 사전 노출 → 전이 프로브 2건(둘 다 is_correct=True)
            (pb, [_P_COND, _P_GRAPH], True),
            (pc, [_P_COND], False),  # 초견·P_COND 사전 노출(pa,pb) → 프로브 1건(False)
        ]
        # pb가 2건(True,True)·pc가 1건(False).
        assert _identify_transfer_probes(rows) == [True, True, False]

    def test_different_pattern_no_cross_exposure(self) -> None:
        """다른 패턴은 사전 노출로 치지 않음 — P_COND 노출이 P_SEQ 초견을 프로브로 만들지 않음."""
        pa, pb = uuid.uuid4(), uuid.uuid4()
        rows = [
            (pa, [_P_COND], True),  # P_COND 노출
            (pb, [_P_SEQ], True),  # P_SEQ 초견·P_SEQ 사전 노출 없음 → 프로브 아님
        ]
        assert _identify_transfer_probes(rows) == []

    def test_none_problem_id_excluded(self) -> None:
        """problem_id None(느슨참조 미설정) attempt는 초견/사전노출 식별 불가 → 전체 제외."""
        pa = uuid.uuid4()
        rows = [
            (pa, [_P_COND], True),
            (None, [_P_COND], True),  # problem_id None → 제외(식별 불가)
            (pa, [_P_COND], True),  # pa 재시도(초견 아님) → 제외
        ]
        assert _identify_transfer_probes(rows) == []

    def test_empty_patterns_contributes_nothing(self) -> None:
        """패턴 태그 0개 문항은 전이 사건 없음(기여 0)."""
        pa, pb = uuid.uuid4(), uuid.uuid4()
        rows: list[tuple[uuid.UUID | None, list[SignaturePattern], bool]] = [
            (pa, [], True),
            (pb, [], False),
        ]
        assert _identify_transfer_probes(rows) == []

    def test_none_patterns_treated_as_empty(self) -> None:
        """signature_patterns None(방어적)도 빈 리스트로 취급 — 기여 0(예외 없음)."""
        pa, pb = uuid.uuid4(), uuid.uuid4()
        rows = [(pa, None, True), (pb, None, False)]
        assert _identify_transfer_probes(rows) == []


# ── ⑦ 근사 전이 점수 — _transfer_from_probes 순수 단위(정답률·MIN 가드) ─────────────────
class TestTransferFromProbes:
    def test_all_correct_score_one(self) -> None:
        """전이 프로브 전부 정답(3건) → MEASURED·value 1.0."""
        m = _transfer_from_probes([True, True, True])
        assert m.status is MetricStatus.MEASURED
        assert m.value == 1.0

    def test_partial_correct_ratio(self) -> None:
        """전이 프로브 2/4 정답 → MEASURED·value 0.5."""
        m = _transfer_from_probes([True, False, True, False])
        assert m.status is MetricStatus.MEASURED
        assert m.value == 0.5

    def test_none_correct_is_measured_zero(self) -> None:
        """전이 프로브 있는데 전부 오답(>=MIN) → MEASURED value 0.0(*실측* 0·날조 아님)."""
        m = _transfer_from_probes([False, False, False])
        assert m.status is MetricStatus.MEASURED
        assert m.value == 0.0

    def test_too_few_probes_is_no_data_not_fake(self) -> None:
        """전이 프로브 < _MIN_TRANSFER_PROBES → NO_DATA·value None(가짜 0/정답률 금지)."""
        m = _transfer_from_probes([True] * (_MIN_TRANSFER_PROBES - 1))
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None
        assert "표본 부족" in m.note

    def test_exactly_min_is_measured(self) -> None:
        """정확히 _MIN_TRANSFER_PROBES → MEASURED(경계 inclusive)."""
        m = _transfer_from_probes([True] * _MIN_TRANSFER_PROBES)
        assert m.status is MetricStatus.MEASURED
        assert m.value is not None

    def test_empty_is_no_data(self) -> None:
        m = _transfer_from_probes([])
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None

    def test_measured_note_is_honest_approximation(self) -> None:
        """MEASURED note에 §11.5 완전판과 다른 *근사*·BKT·2주 스케줄 미반영 정직 표기."""
        m = _transfer_from_probes([True, True, True])
        assert "근사" in m.note
        assert "§11.5" in m.note
        assert "assign_transfer_probe" in m.note
        assert "BKT" in m.note


# ── ⑦ 근사 전이 점수 — compute_wh1_surrogate_metrics 통합(FakeSession 전이 행 주입) ────────
class TestTransferScoreIntegratedWithCompute:
    async def _transfer(
        self, transfer_rows: list[tuple[Any, Any, bool]] | None
    ) -> SurrogateMetrics:
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            transfer_rows=transfer_rows,
        )
        return await compute_wh1_surrogate_metrics(session)

    async def test_measured_transfer_ratio_and_sample(self) -> None:
        """사전 노출 후 초견 동형 3건(2정답·1오답) → MEASURED·value≈0.667·표본 3."""
        pa, pb, pc, pd = (uuid.uuid4() for _ in range(4))
        m = await self._transfer(
            [
                (pa, [_P_COND], False),  # P_COND 첫 등장(사전 노출 0)
                (pb, [_P_COND], True),  # 초견·사전 노출 → 프로브(True)
                (pc, [_P_COND], True),  # 초견·사전 노출 → 프로브(True)
                (pd, [_P_COND], False),  # 초견·사전 노출 → 프로브(False)
            ]
        )
        ts = m.transfer_score
        assert ts.status is MetricStatus.MEASURED
        assert ts.value is not None
        assert abs(ts.value - 2 / 3) < 1e-9  # 2/3 전이 프로브 정답
        assert m.sample_transfer_probes == 3

    async def test_no_data_when_no_prior_exposure(self) -> None:
        """사전 노출 없는 첫 패턴 등장만 있으면 전이 프로브 0 → NO_DATA(가짜 0 금지)."""
        pa, pb = uuid.uuid4(), uuid.uuid4()
        m = await self._transfer(
            [(pa, [_P_COND], True), (pb, [_P_SEQ], True)]  # 서로 다른 패턴 첫 등장
        )
        assert m.transfer_score.status is MetricStatus.NO_DATA
        assert m.transfer_score.value is None
        assert m.sample_transfer_probes == 0

    async def test_same_problem_retry_not_counted(self) -> None:
        """같은 problem_id 재시도는 전이 프로브 아님 — 초견만(부족하면 NO_DATA)."""
        pa, pb = uuid.uuid4(), uuid.uuid4()
        m = await self._transfer(
            [
                (pa, [_P_COND], False),  # 첫 등장
                (pb, [_P_COND], True),  # 초견·사전 노출 → 프로브 1건
                (pb, [_P_COND], True),  # pb 재시도(초견 아님) → 제외
            ]
        )
        # 전이 프로브 1건(< MIN 3) → NO_DATA. 표본도 1.
        assert m.sample_transfer_probes == 1
        assert m.transfer_score.status is MetricStatus.NO_DATA

    async def test_multiple_patterns_counted_independently(self) -> None:
        """복수 패턴 attempt — 패턴별 독립 전이 프로브로 카운트(표본·정답률 반영)."""
        pa, pb, pc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        m = await self._transfer(
            [
                (pa, [_P_COND, _P_GRAPH], True),  # 두 패턴 첫 등장(사전 노출 0)
                (
                    pb,
                    [_P_COND, _P_GRAPH],
                    True,
                ),  # 초견·두 패턴 사전 노출 → 프로브 2건(True,True)
                (pc, [_P_COND], False),  # 초견·P_COND 사전 노출 → 프로브 1건(False)
            ]
        )
        ts = m.transfer_score
        assert m.sample_transfer_probes == 3  # 2 + 1(패턴별 독립)
        assert ts.status is MetricStatus.MEASURED
        assert ts.value is not None
        assert abs(ts.value - 2 / 3) < 1e-9  # True,True,False → 2/3

    async def test_none_problem_id_rows_excluded(self) -> None:
        """problem_id None 행은 식별에서 제외 — 표본에 안 들어감(날조 0)."""
        pa, pb = uuid.uuid4(), uuid.uuid4()
        m = await self._transfer(
            [
                (pa, [_P_COND], True),  # 첫 등장
                (None, [_P_COND], True),  # problem_id None → 제외
                (pb, [_P_COND], True),  # 초견·사전 노출(pa) → 프로브 1건
            ]
        )
        assert m.sample_transfer_probes == 1  # None 행 제외 → 프로브 1건
        assert m.transfer_score.status is MetricStatus.NO_DATA  # 1 < 3


# ── 메타·필드셋·스코핑 ───────────────────────────────────────────────────────
class TestMetaAndFieldSet:
    async def test_field_set_complete(self) -> None:
        """SurrogateMetrics가 7 지표 + S3 3종 + R15 결합 판정 + 메타(표본 수)를 모두 보유."""
        u1, u2 = uuid.uuid4(), uuid.uuid4()
        c1, c2 = uuid.uuid4(), uuid.uuid4()
        session = _make_session(
            total_sessions=2,
            completed_sessions=1,
            avg_tokens=12.0,
            token_sample=4,
            hint_levels=[4, 3, 2],
            # ⑮ 도움 요청 대 제공 비 — 힌트제공(supply) 3건(위 hint_levels) 대 힌트요청(demand) 2건.
            demand_events=2,
            accuracy_correct=[True, True, True],
            difficulty_rows=[(1.0, None), (0.5, None), (0.0, None)],
            # ⑥ 보정 쌍 5개(>= _MIN_CALIBRATION_SAMPLES) → calibration_brier MEASURED.
            calibration_pairs=[
                (0.9, True),
                (0.8, True),
                (0.2, False),
                (0.1, False),
                (0.7, True),
            ],
            # ⑦ 전이 — P1 첫 등장 후 P2·P3·P4 초견 동형(사전 노출) 3건 → MEASURED·표본 3.
            transfer_rows=[
                (uuid.uuid4(), [_P_COND], True),  # 첫 등장(사전 노출 0)
                (uuid.uuid4(), [_P_COND], True),  # 초견·사전 노출 → 프로브
                (uuid.uuid4(), [_P_COND], True),  # 초견·사전 노출 → 프로브
                (uuid.uuid4(), [_P_COND], False),  # 초견·사전 노출 → 프로브
            ],
            # ⑨ 숙달 — 2그룹 각 2점(그룹 내 measured_at 오름차순) → 자격 그룹 2·증가량 평균.
            mastery_rows=[
                (u1, c1, 0.3, _MEASURED_AT),  # (u1,c1) 첫
                (u1, c1, 0.7, _MEASURED_AT2),  # (u1,c1) 마지막 → gain +0.4
                (u2, c2, 0.5, _MEASURED_AT),  # (u2,c2) 첫
                (u2, c2, 0.6, _MEASURED_AT2),  # (u2,c2) 마지막 → gain +0.1
            ],
            # ⑩ 오개념 — 전체 5건 중 비활성(해소 근사) 2건 → rate 0.4.
            misconception_inactive=2,
            misconception_total=5,
            # ⑪ 스스로 풀이 — 결말 도달 4건 중 학생자력해결 3건 → rate 0.75.
            self_solved=3,
            resolved_total=4,
            # ⑭ 힌트제공 3건 중 1건 client_state_mismatch=true.
            hint_mismatch_flags=[True, False, False],
            # ⑫⑬ 대화 2개 — d1: 3턴(조건확인×2 연속+단계분해) · d2: 1턴(예시제시).
            strategy_rows=[
                (u1, "조건확인"),
                (u1, "조건확인"),
                (u1, "단계분해"),
                (u2, "예시제시"),
            ],
        )
        m = await compute_wh1_surrogate_metrics(session)
        for name in (
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
            "strategy_diversity",
            "strategy_repeat_rate",
            "client_state_mismatch_rate",
        ):
            assert isinstance(getattr(m, name), Metric)
        assert isinstance(m.help_reduction_validated, HelpReductionValidation)
        assert m.sample_sessions == 2
        assert m.sample_dialogues == 4
        assert m.sample_hint_events == 3  # 유효 hint_level 행 수
        assert m.sample_demand_events == 2  # ⑫ 힌트요청 attempt_event 수
        assert m.help_demand_supply_ratio.status is MetricStatus.MEASURED
        assert m.help_demand_supply_ratio.value == pytest_approx(2 / 3)
        assert m.sample_accuracy_attempts == 3  # is_correct NOT NULL 행 수
        assert m.sample_difficulty_attempts == 3  # 유효 b(Problem join) 행 수
        assert m.sample_calibration_pairs == 5  # 유효 보정 쌍 수
        assert m.sample_transfer_probes == 3  # ⑦ 전이 프로브 수(초견·사전 노출·패턴별)
        assert m.sample_diagnostic_probes == 98  # ② recall 프로브 수(시스템 지표·프로브셋 크기)
        assert m.sample_mastery_groups == 2  # ⑨ 자격 (user,concept) 그룹 수(≥2점)
        assert m.sample_misconception_hypotheses == 5  # ⑩ 오개념 가설 총수(비활성 2 포함)
        assert m.sample_resolved_dialogues == 4  # ⑪ resolution 채워진 세션 수(자력해결 3 포함)
        # difficulty_slope 필드 노출(양수=난이도 상승·음수=쉬워짐). 여기선 하강(1→0.5→0)이라 음수.
        assert m.help_reduction_validated.difficulty_slope is not None
        # ⑥ 보정 점수 — 5쌍 >= MIN → MEASURED·value 실수(Brier∈[0,1]).
        assert m.calibration_brier.status is MetricStatus.MEASURED
        assert m.calibration_brier.value is not None
        assert 0.0 <= m.calibration_brier.value <= 1.0
        # ⑦ 전이 점수 — 전이 프로브 3건(>= MIN) → MEASURED·value 실수(정답률∈[0,1]).
        assert m.transfer_score.status is MetricStatus.MEASURED
        assert m.transfer_score.value is not None
        assert 0.0 <= m.transfer_score.value <= 1.0
        # PED-04 ⑫⑬⑭ — 표본 4턴(>=MIN) → MEASURED. distinct=3/4=0.75(조건확인·단계분해·예시제시).
        assert m.sample_strategy_turns == 4
        assert m.strategy_diversity.status is MetricStatus.MEASURED
        assert m.strategy_diversity.value == pytest_approx(0.75)
        # 인접쌍은 d1 내부 2쌍(조건확인→조건확인 동일·조건확인→단계분해 다름)뿐 — d2는 1턴이라
        # 쌍 없음. 표본 2쌍은 _MIN_STRATEGY_TURNS(3) 미만이라 NO_DATA(가짜 비율 금지).
        assert m.strategy_repeat_rate.status is MetricStatus.NO_DATA
        assert m.strategy_repeat_rate.value is None
        assert m.client_state_mismatch_rate.status is MetricStatus.MEASURED
        assert m.client_state_mismatch_rate.value == pytest_approx(1 / 3)

    async def test_user_scoped_true_when_user_id(self) -> None:
        session = _make_session(
            total_sessions=1, completed_sessions=1, avg_tokens=None, token_sample=0
        )
        m = await compute_wh1_surrogate_metrics(session, user_id=uuid.uuid4())
        assert m.user_scoped is True

    async def test_user_scoped_false_for_cohort(self) -> None:
        session = _make_session(
            total_sessions=1, completed_sessions=1, avg_tokens=None, token_sample=0
        )
        m = await compute_wh1_surrogate_metrics(session, user_id=None)
        assert m.user_scoped is False

    async def test_window_passthrough(self) -> None:
        """since/until이 메타(window_start/end)에 그대로 반영."""
        since = datetime(2026, 1, 1, tzinfo=UTC)
        until = datetime(2026, 3, 1, tzinfo=UTC)
        session = _make_session(
            total_sessions=1, completed_sessions=1, avg_tokens=None, token_sample=0
        )
        m = await compute_wh1_surrogate_metrics(session, since=since, until=until)
        assert m.window_start == since
        assert m.window_end == until


# ── _ols_slope 공유 헬퍼(⑤ 리팩터 후 ⑤·R15 공유 코어) ───────────────────────────
class TestOlsSlope:
    def test_decreasing_slope(self) -> None:
        """완전 등차 하강(4,3,2,1) → 기울기 −1.0."""
        assert _ols_slope([4.0, 3.0, 2.0, 1.0]) == -1.0

    def test_increasing_slope(self) -> None:
        """완전 등차 상승(1,2,3) → 기울기 +1.0."""
        assert _ols_slope([1.0, 2.0, 3.0]) == 1.0

    def test_flat_is_zero_not_none(self) -> None:
        """동일값(3,3,3) → x 분산 양수라 기울기 0.0(실측 평탄·날조 0 아님)."""
        assert _ols_slope([3.0, 3.0, 3.0]) == 0.0

    def test_too_few_points_is_none(self) -> None:
        """포인트 < _MIN_SLOPE_POINTS(3) → None(가짜 기울기/0 금지)."""
        assert _ols_slope([4.0, 2.0]) is None
        assert _ols_slope([1.0]) is None
        assert _ols_slope([]) is None


# ── _judge_r15 결합 판정(R15 3신호: 도움·정답률·난이도) ──────────────────────────
class TestJudgeR15:
    # ─ 도움↓·정답률 유지/↑ × 난이도 분기(이 슬라이스 정밀화 핵심) ─
    def test_genuine_improvement_help_down_accuracy_up_difficulty_up(self) -> None:
        """도움↓(−1)·정답률↑(+0.5)·난이도↑(+0.4) → GENUINE_IMPROVEMENT(진짜 개선)."""
        v = _judge_r15(-1.0, 0.5, 0.4)
        assert v.verdict is R15Verdict.GENUINE_IMPROVEMENT
        assert v.help_slope == -1.0
        assert v.accuracy_slope == 0.5
        assert v.difficulty_slope == 0.4
        assert "진짜 개선" in v.note

    def test_genuine_improvement_difficulty_flat_boundary(self) -> None:
        """도움↓·정답률 유지·난이도 유지(0·경계) → GENUINE(난이도 slope 0 임계는 회피 아님)."""
        v = _judge_r15(-0.3, 0.0, 0.0)
        assert v.verdict is R15Verdict.GENUINE_IMPROVEMENT
        assert v.difficulty_slope == 0.0

    def test_gaming_suspect_easy_problem_avoidance_difficulty_down(self) -> None:
        """도움↓(−1)·정답률 유지(+0.0)지만 난이도↓(−0.5) → GAMING_SUSPECT(쉬운 문제 회피).

        이 슬라이스 핵심 정밀화: 정답률이 유지돼도 문항이 쉬워지면 진짜 개선이 아니다.
        """
        v = _judge_r15(-1.0, 0.0, -0.5)
        assert v.verdict is R15Verdict.GAMING_SUSPECT
        assert v.difficulty_slope == -0.5
        assert "쉬운 문제 회피" in v.note
        assert "난이도↓" in v.note

    def test_gaming_suspect_easy_avoidance_accuracy_up_difficulty_down(self) -> None:
        """정답률↑여도 난이도↓면 회피 — 쉬운 문제로 갈아타며 정답률까지 올린 경우."""
        v = _judge_r15(-1.0, 0.5, -0.3)
        assert v.verdict is R15Verdict.GAMING_SUSPECT
        assert "쉬운 문제 회피" in v.note

    def test_genuine_with_caveat_when_difficulty_none(self) -> None:
        """도움↓·정답률 유지·난이도 추세 None(b 부족) → GENUINE + blind spot 캐비엇 note."""
        v = _judge_r15(-1.0, 0.2, None)
        assert v.verdict is R15Verdict.GENUINE_IMPROVEMENT
        assert v.difficulty_slope is None
        assert "난이도 추세 미가용" in v.note
        assert "쉬운문제 회피 미검증" in v.note

    # ─ 정답률↓ 분기(기존·난이도 무관) ─
    def test_gaming_suspect_accuracy_down_regardless_of_difficulty(self) -> None:
        """도움↓이나 정답률↓ → GAMING_SUSPECT(정답률 하락·기존). 난이도 부호 무관."""
        v = _judge_r15(-1.0, -0.5, 0.9)
        assert v.verdict is R15Verdict.GAMING_SUSPECT
        assert "정답률 하락" in v.note
        # 난이도가 None이어도 정답률↓면 동일.
        assert _judge_r15(-1.0, -0.5, None).verdict is R15Verdict.GAMING_SUSPECT

    # ─ NO_HELP_REDUCTION·INSUFFICIENT_DATA(기존 회귀) ─
    def test_no_help_reduction_positive_help_slope(self) -> None:
        """도움 기울기 >= 0(안 줄어듦) → NO_HELP_REDUCTION(개선 신호 아님)."""
        assert _judge_r15(0.5, -1.0, -0.5).verdict is R15Verdict.NO_HELP_REDUCTION
        # 경계 0도 도움 안 줄어듦(>= 0) — 정답률·난이도 부호 무관.
        assert _judge_r15(0.0, 0.9, 0.9).verdict is R15Verdict.NO_HELP_REDUCTION

    def test_insufficient_data_when_help_none(self) -> None:
        """도움 기울기 None(표본 부족) → INSUFFICIENT_DATA(날조 판정 금지)."""
        v = _judge_r15(None, 0.5, -0.5)
        assert v.verdict is R15Verdict.INSUFFICIENT_DATA
        assert v.help_slope is None
        assert v.accuracy_slope == 0.5
        assert v.difficulty_slope == -0.5

    def test_insufficient_data_when_accuracy_none(self) -> None:
        """정답률 기울기 None(표본 부족) → INSUFFICIENT_DATA(한쪽이라도 부족이면)."""
        v = _judge_r15(-1.0, None, -0.5)
        assert v.verdict is R15Verdict.INSUFFICIENT_DATA

    def test_insufficient_data_when_both_none(self) -> None:
        assert _judge_r15(None, None, None).verdict is R15Verdict.INSUFFICIENT_DATA

    def test_difficulty_none_does_not_trigger_insufficient(self) -> None:
        """난이도만 None(help·accuracy는 충분)이면 INSUFFICIENT 아님 — 난이도는 선택 신호."""
        v = _judge_r15(-1.0, 0.5, None)
        assert v.verdict is R15Verdict.GENUINE_IMPROVEMENT


# ── R15 결합 판정 — compute_wh1_surrogate_metrics 통합(FakeSession is_correct 주입) ──
class TestHelpReductionValidatedIntegratedWithCompute:
    async def _validate(
        self,
        *,
        hint_levels: list[int | None] | None,
        accuracy_correct: list[bool | None] | None,
        difficulty_rows: list[tuple[float | None, float | None]] | None = None,
    ) -> HelpReductionValidation:
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            hint_levels=hint_levels,
            accuracy_correct=accuracy_correct,
            difficulty_rows=difficulty_rows,
        )
        return (await compute_wh1_surrogate_metrics(session)).help_reduction_validated

    async def test_genuine_improvement(self) -> None:
        """도움↓(4→3→2→1)·정답률↑(F→T→T→T)·난이도 추세 없음 → GENUINE + 캐비엇."""
        v = await self._validate(
            hint_levels=[4, 3, 2, 1],
            accuracy_correct=[False, True, True, True],
        )
        assert v.verdict is R15Verdict.GENUINE_IMPROVEMENT
        assert v.help_slope is not None and v.help_slope < 0
        assert v.accuracy_slope is not None and v.accuracy_slope > 0
        # 난이도 행 미주입 → difficulty_slope None·blind spot 캐비엇.
        assert v.difficulty_slope is None
        assert "난이도 추세 미가용" in v.note

    async def test_genuine_improvement_with_rising_difficulty(self) -> None:
        """도움↓·정답률 유지·난이도 상승(b 보정 −1→0→1) → GENUINE(쉬운문제 회피 아님)."""
        v = await self._validate(
            hint_levels=[4, 3, 2, 1],
            accuracy_correct=[True, True, True, True],
            difficulty_rows=[(-1.0, None), (0.0, None), (1.0, None), (2.0, None)],
        )
        assert v.verdict is R15Verdict.GENUINE_IMPROVEMENT
        assert v.difficulty_slope is not None and v.difficulty_slope > 0

    async def test_gaming_suspect_easy_problem_avoidance(self) -> None:
        """도움↓·정답률 유지지만 난이도↓(b 보정 2→1→0→−1) → GAMING_SUSPECT(쉬운문제 회피)."""
        v = await self._validate(
            hint_levels=[4, 3, 2, 1],
            accuracy_correct=[True, True, True, True],
            difficulty_rows=[(2.0, None), (1.0, None), (0.0, None), (-1.0, None)],
        )
        assert v.verdict is R15Verdict.GAMING_SUSPECT
        assert v.difficulty_slope is not None and v.difficulty_slope < 0
        assert "쉬운 문제 회피" in v.note

    async def test_difficulty_uses_heuristic_when_no_calibrated_b(self) -> None:
        """보정 b 없고 difficulty_overall(5→4→3→2)만 있어도 휴리스틱 b로 난이도↓ → 회피."""
        v = await self._validate(
            hint_levels=[4, 3, 2, 1],
            accuracy_correct=[True, True, True, True],
            # irt_b None·difficulty_overall 하강(어려움→쉬움) → 휴리스틱 b도 하강.
            difficulty_rows=[(None, 5.0), (None, 4.0), (None, 3.0), (None, 2.0)],
        )
        assert v.verdict is R15Verdict.GAMING_SUSPECT
        assert v.difficulty_slope is not None and v.difficulty_slope < 0

    async def test_difficulty_excludes_rows_with_both_none(self) -> None:
        """irt_b·difficulty_overall 둘 다 None인 행은 난이도 시계열에서 제외(유효 b만)."""
        # 유효 b는 (2,1,0) 3점 하강만 — 둘 다 None인 행 2개는 제외되어 표본에 안 들어감.
        v = await self._validate(
            hint_levels=[4, 3, 2, 1],
            accuracy_correct=[True, True, True, True],
            difficulty_rows=[
                (2.0, None),
                (None, None),
                (1.0, None),
                (None, None),
                (0.0, None),
            ],
        )
        assert v.verdict is R15Verdict.GAMING_SUSPECT
        assert v.difficulty_slope is not None and v.difficulty_slope < 0

    async def test_difficulty_too_few_valid_b_is_none_caveat(self) -> None:
        """유효 b 2점(<3)뿐이면 difficulty_slope None → 2신호 GENUINE + 캐비엇(날조 0 금지)."""
        v = await self._validate(
            hint_levels=[4, 3, 2, 1],
            accuracy_correct=[True, True, True, True],
            difficulty_rows=[(2.0, None), (1.0, None)],  # 유효 2점 < 3
        )
        assert v.verdict is R15Verdict.GENUINE_IMPROVEMENT
        assert v.difficulty_slope is None
        assert "난이도 추세 미가용" in v.note

    async def test_gaming_suspect(self) -> None:
        """도움↓(4→3→2→1)이나 정답률↓(T→T→F→F) → GAMING_SUSPECT(힌트 회피 의심)."""
        v = await self._validate(
            hint_levels=[4, 3, 2, 1],
            accuracy_correct=[True, True, False, False],
        )
        assert v.verdict is R15Verdict.GAMING_SUSPECT
        assert v.help_slope is not None and v.help_slope < 0
        assert v.accuracy_slope is not None and v.accuracy_slope < 0

    async def test_no_help_reduction(self) -> None:
        """도움↑(1→2→3) → NO_HELP_REDUCTION(정답률 무관)."""
        v = await self._validate(
            hint_levels=[1, 2, 3],
            accuracy_correct=[True, True, True],
        )
        assert v.verdict is R15Verdict.NO_HELP_REDUCTION

    async def test_insufficient_when_accuracy_too_few(self) -> None:
        """도움↓ 충분하나 정답률 표본 부족(2점<3) → INSUFFICIENT_DATA(날조 판정 금지)."""
        v = await self._validate(
            hint_levels=[4, 3, 2, 1],
            accuracy_correct=[True, False],
        )
        assert v.verdict is R15Verdict.INSUFFICIENT_DATA
        assert v.accuracy_slope is None

    async def test_insufficient_when_hint_too_few(self) -> None:
        """정답률 충분하나 도움 표본 부족(2점<3) → INSUFFICIENT_DATA."""
        v = await self._validate(
            hint_levels=[4, 2],
            accuracy_correct=[True, True, True],
        )
        assert v.verdict is R15Verdict.INSUFFICIENT_DATA
        assert v.help_slope is None

    async def test_accuracy_none_rows_filtered(self) -> None:
        """is_correct None 행은 본문이 거르므로 sample_accuracy_attempts에서 제외(방어적)."""
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            hint_levels=[4, 3, 2, 1],
            accuracy_correct=[True, None, True, True],
        )
        m = await compute_wh1_surrogate_metrics(session)
        # None 1개 제외 → 유효 3개.
        assert m.sample_accuracy_attempts == 3


# ── ⑤ 리팩터 회귀(비트동일) — _help_reduction_from_levels는 _ols_slope 위임 후도 불변 ──
class TestHelpReductionRefactorRegression:
    async def _slope(self, hint_levels: list[int | None]) -> Metric:
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            hint_levels=hint_levels,
        )
        return (await compute_wh1_surrogate_metrics(session)).help_reduction_slope

    async def test_measured_value_unchanged(self) -> None:
        """리팩터 후도 4→3→2→1 기울기 −1.0·MEASURED(⑤ 동작 비트동일)."""
        m = await self._slope([4, 3, 2, 1])
        assert m.status is MetricStatus.MEASURED
        assert m.value == -1.0

    async def test_too_few_note_unchanged(self) -> None:
        """표본 부족 NO_DATA·'표본 부족' note 보존(가드 분기 비트동일)."""
        m = await self._slope([4, 2])
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None
        assert "표본 부족" in m.note


# ── ⑧ 답 미루기 도달 깊이 (hint_level 평균·최대·⑤와 동일 신호 재사용) ─────────────────
class TestHintDepthPure:
    def test_measured_mean_and_note_max(self) -> None:
        """hint_level [1,3,4,2] → 평균 2.5·note에 최대 4(도달 깊이)·MEASURED."""
        m = _hint_depth_from_levels([1, 3, 4, 2])
        assert m.status is MetricStatus.MEASURED
        assert m.value == 2.5
        assert "최대 도달 4" in m.note
        # 게이밍 캐비엇·R15 참조가 note에 정직 표기(단독 해석 금지).
        assert "R15" in m.note

    def test_empty_is_no_data_not_zero(self) -> None:
        """힌트 0건 → NO_DATA·value None(가짜 0 금지)."""
        m = _hint_depth_from_levels([])
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None
        assert "0건" in m.note


class TestHintDepthIntegratedWithCompute:
    async def test_measured_via_compute(self) -> None:
        """compute가 ⑤와 동일 hint_levels로 ⑧ 평균 깊이·표본(sample_hint_events 공유) 산출."""
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            hint_levels=[4, 4, 1],  # 평균 3.0·최대 4
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.hint_depth_reached.status is MetricStatus.MEASURED
        assert m.hint_depth_reached.value == 3.0
        assert m.sample_hint_events == 3  # ⑤와 동일 표본(새 쿼리 0)

    async def test_no_hint_events_no_data(self) -> None:
        session = _make_session(
            total_sessions=1, completed_sessions=1, avg_tokens=None, token_sample=0
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.hint_depth_reached.status is MetricStatus.NO_DATA
        assert m.hint_depth_reached.value is None


# ── ⑮ 도움 요청 대 제공 비 (힌트요청/힌트제공 개수 비·S3-16 소생) ──────────────────────
class TestHelpDemandSupplyRatioPure:
    def test_measured_ratio(self) -> None:
        """demand 2/supply 4 → MEASURED·value 0.5."""
        m = _help_demand_supply_ratio_from_counts(2, 4)
        assert m.status is MetricStatus.MEASURED
        assert m.value == pytest_approx(0.5)

    def test_zero_supply_no_data(self) -> None:
        """힌트제공(supply) 0건 → NO_DATA·value None(분모 0 방지·가짜 0 금지)."""
        m = _help_demand_supply_ratio_from_counts(3, 0)
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None
        assert "0건" in m.note

    def test_zero_demand_with_supply_is_measured_zero(self) -> None:
        """demand 0·supply>0 → ratio 0.0·MEASURED(실측 0·날조 아님 — NO_DATA 아님)."""
        m = _help_demand_supply_ratio_from_counts(0, 5)
        assert m.status is MetricStatus.MEASURED
        assert m.value == 0.0


class TestHelpDemandSupplyRatioIntegratedWithCompute:
    async def test_measured_via_compute(self) -> None:
        """compute가 ⑤ hint_levels(supply)를 분모로 재사용·demand_events를 분자로 ⑫ 산출."""
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            hint_levels=[1, 2, 3, 4],  # supply 4건
            demand_events=1,
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.help_demand_supply_ratio.status is MetricStatus.MEASURED
        assert m.help_demand_supply_ratio.value == pytest_approx(0.25)
        assert m.sample_demand_events == 1
        assert m.sample_hint_events == 4  # ⑤와 동일 표본(새 all-row 쿼리 0)

    async def test_no_supply_no_data(self) -> None:
        """힌트제공(supply) 0건이면 ⑤⑧과 함께 ⑫도 NO_DATA(분모 0 방지)."""
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            demand_events=3,  # supply 없이 demand만 있어도 분모 0이라 NO_DATA.
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.help_demand_supply_ratio.status is MetricStatus.NO_DATA
        assert m.help_demand_supply_ratio.value is None
        assert m.sample_demand_events == 3


# ── ⑨ BKT 숙달 증가율 ((user,concept)별 첫→마지막 mastery 차 평균) ──────────────────
class TestMasteryGainsPure:
    def test_groups_first_to_last_delta(self) -> None:
        """(user,concept)별 첫→마지막 차 — 2점 그룹 gain, 1점 그룹 제외(_MIN_MASTERY_POINTS)."""
        u1, u2, u3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        c1, c2 = uuid.uuid4(), uuid.uuid4()
        rows = [
            (u1, c1, 0.2),
            (u1, c1, 0.6),  # (u1,c1) gain +0.4
            (u2, c2, 0.5),
            (u2, c2, 0.5),  # (u2,c2) gain 0.0(실측 평탄)
            (u3, c1, 0.9),  # (u3,c1) 1점만 → 제외
        ]
        gains = _mastery_gains_from_rows(rows)
        assert len(gains) == 2  # 자격 그룹 2(1점 그룹 제외)
        assert sorted(gains) == [0.0, pytest_approx(0.4)]

    def test_min_points_boundary(self) -> None:
        """_MIN_MASTERY_POINTS는 2 — 그룹당 before/after 2점 요구."""
        assert _MIN_MASTERY_POINTS == 2


class TestMasteryGainMetric:
    def test_measured_mean(self) -> None:
        m = _mastery_gain_from_gains([0.4, 0.0])
        assert m.status is MetricStatus.MEASURED
        assert m.value == pytest_approx(0.2)

    def test_empty_no_data(self) -> None:
        """자격 그룹 0 → NO_DATA·value None(가짜 0 금지)."""
        m = _mastery_gain_from_gains([])
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None
        assert "rate 아님" in m.note or "증가량" in m.note


class TestMasteryGainIntegratedWithCompute:
    async def test_measured_via_compute(self) -> None:
        u1, u2 = uuid.uuid4(), uuid.uuid4()
        c1, c2 = uuid.uuid4(), uuid.uuid4()
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            mastery_rows=[
                (u1, c1, 0.3, _MEASURED_AT),
                (u1, c1, 0.9, _MEASURED_AT2),  # gain +0.6
                (u2, c2, 0.4, _MEASURED_AT),
                (u2, c2, 0.6, _MEASURED_AT2),  # gain +0.2
            ],
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.mastery_gain_rate.status is MetricStatus.MEASURED
        assert m.mastery_gain_rate.value == pytest_approx(0.4)  # (0.6+0.2)/2
        assert m.sample_mastery_groups == 2

    async def test_none_mastery_excluded(self) -> None:
        """mastery None 행은 제외 — 남은 자격 그룹 0이면 NO_DATA."""
        u1 = uuid.uuid4()
        c1 = uuid.uuid4()
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            mastery_rows=[
                (u1, c1, None, _MEASURED_AT),
                (u1, c1, 0.5, _MEASURED_AT2),
            ],  # None 제외 → 1점 → 그룹 미자격
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.mastery_gain_rate.status is MetricStatus.NO_DATA
        assert m.mastery_gain_rate.value is None
        assert m.sample_mastery_groups == 0


# ── ⑩ 오개념 해소율 (is_active=false 비율·해소 근사) ─────────────────────────────────
class TestMisconceptionResolutionPure:
    def test_measured_ratio(self) -> None:
        m = _misconception_resolution_from_counts(2, 5)
        assert m.status is MetricStatus.MEASURED
        assert m.value == pytest_approx(0.4)
        assert "근사" in m.note  # 해소 근사 정직 표기

    def test_zero_total_no_data(self) -> None:
        """가설 0건 → NO_DATA·value None(가짜 0 금지)."""
        m = _misconception_resolution_from_counts(0, 0)
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None
        assert "0건" in m.note

    def test_all_active_zero_rate(self) -> None:
        """전부 활성(비활성 0) → rate 0.0·MEASURED(실측 0·날조 아님)."""
        m = _misconception_resolution_from_counts(0, 4)
        assert m.status is MetricStatus.MEASURED
        assert m.value == 0.0


class TestMisconceptionResolutionIntegratedWithCompute:
    async def test_measured_via_compute(self) -> None:
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            misconception_inactive=3,
            misconception_total=4,
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.misconception_resolution_rate.status is MetricStatus.MEASURED
        assert m.misconception_resolution_rate.value == pytest_approx(0.75)
        assert m.sample_misconception_hypotheses == 4

    async def test_no_hypotheses_no_data(self) -> None:
        session = _make_session(
            total_sessions=1, completed_sessions=1, avg_tokens=None, token_sample=0
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.misconception_resolution_rate.status is MetricStatus.NO_DATA
        assert m.misconception_resolution_rate.value is None
        assert m.sample_misconception_hypotheses == 0


# ── ④ 턴당 토큰 — NO_DATA→MEASURED 전환 (S1 게이트 ② 계측 배선 증명) ────────────
class TestTokensPerTurnTransition:
    async def test_transitions_no_data_to_measured_when_dialogue_tokens_loaded(
        self,
    ) -> None:
        """토큰 미적재(NO_DATA) → Dialogue.total_tokens/total_turns 적재 시 MEASURED 전환.

        S1 게이트 ②의 지표 ④ 근거: usage 계측 파이프가 Dialogue 토큰을 적재하기 *전*에는
        정직하게 NO_DATA(가짜 0 금지)이고, 적재 데이터가 주입되는 *순간* 같은 계산이
        MEASURED·실측 평균으로 전환됨을 한 테스트로 증명한다(코드 변경 0으로 전환).
        """
        # 1) 적재 전 — total_tokens 채워진 Dialogue 0건 → NO_DATA.
        before = await compute_wh1_surrogate_metrics(
            _make_session(total_sessions=1, completed_sessions=1, avg_tokens=None, token_sample=0)
        )
        assert before.tokens_per_turn.status is MetricStatus.NO_DATA
        assert before.tokens_per_turn.value is None  # 가짜 0 아님

        # 2) 적재 후 — 같은 계산에 (AVG=310.0, 표본 4) 주입 → MEASURED 전환.
        #    (예: 대화 4건의 AVG(total_tokens/total_turns)=310토큰/턴)
        after = await compute_wh1_surrogate_metrics(
            _make_session(total_sessions=1, completed_sessions=1, avg_tokens=310.0, token_sample=4)
        )
        assert after.tokens_per_turn.status is MetricStatus.MEASURED
        assert after.tokens_per_turn.value == 310.0
        assert after.sample_dialogues == 4


# ── ⑪ 스스로 풀이 도달율 (resolution=학생자력해결 비율·클라이언트 보고) ────────────────
class TestSelfSolvePure:
    def test_measured_ratio(self) -> None:
        m = _self_solve_from_counts(3, 4)
        assert m.status is MetricStatus.MEASURED
        assert m.value == pytest_approx(0.75)
        # 클라이언트 보고·서버 미판정 정직 표기.
        assert "클라이언트 보고" in m.note

    def test_zero_resolved_no_data(self) -> None:
        """resolution 채워진 대화 0건 → NO_DATA·value None(가짜 0 금지·미보고 NULL 제외)."""
        m = _self_solve_from_counts(0, 0)
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None
        assert "0건" in m.note

    def test_none_self_solved_zero_rate(self) -> None:
        """결말 도달했으나 자력해결 0 → rate 0.0·MEASURED(실측 0·날조 아님)."""
        m = _self_solve_from_counts(0, 3)
        assert m.status is MetricStatus.MEASURED
        assert m.value == 0.0


class TestSelfSolveIntegratedWithCompute:
    async def test_measured_via_compute(self) -> None:
        session = _make_session(
            total_sessions=1,
            completed_sessions=1,
            avg_tokens=None,
            token_sample=0,
            self_solved=2,
            resolved_total=5,
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.self_solve_rate.status is MetricStatus.MEASURED
        assert m.self_solve_rate.value == pytest_approx(0.4)
        assert m.sample_resolved_dialogues == 5

    async def test_no_resolved_dialogues_no_data(self) -> None:
        session = _make_session(
            total_sessions=1, completed_sessions=1, avg_tokens=None, token_sample=0
        )
        m = await compute_wh1_surrogate_metrics(session)
        assert m.self_solve_rate.status is MetricStatus.NO_DATA
        assert m.self_solve_rate.value is None
        assert m.sample_resolved_dialogues == 0


# ── PED-04 ⑫⑬⑭ 발문 전략·클라 상태 불일치 지표 ──────────────────────────────
class TestStrategyDiversity:
    def test_too_few_turns_no_data(self) -> None:
        """기록 턴 2건(< _MIN_STRATEGY_TURNS) → NO_DATA(가짜 1.0 금지)."""
        m = _strategy_diversity_from_values(["조건확인", "단계분해"])
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None
        assert "2건" in m.note

    def test_all_distinct_measured_one(self) -> None:
        """4턴 전부 다른 전략 → MEASURED·value 1.0."""
        m = _strategy_diversity_from_values(["조건확인", "단계분해", "유사문제", "반례제시"])
        assert m.status is MetricStatus.MEASURED
        assert m.value == pytest_approx(1.0)
        # 실질 상한(REACHABLE_STRATEGIES 4종) 근거가 note에 표기됨 — 오독 방지.
        assert "상한" in m.note

    def test_all_same_measured_low(self) -> None:
        """4턴 전부 같은 전략 → MEASURED·value 0.25(distinct 1/4, 날조 아닌 실측 저다양성)."""
        m = _strategy_diversity_from_values(["단계분해"] * 4)
        assert m.status is MetricStatus.MEASURED
        assert m.value == pytest_approx(0.25)


class TestStrategyRepeatRate:
    def test_too_few_pairs_no_data(self) -> None:
        """대화 하나·2턴(인접쌍 1개 < _MIN_STRATEGY_TURNS) → NO_DATA."""
        m = _strategy_repeat_from_sequences([["조건확인", "조건확인"]])
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None

    def test_measured_ratio(self) -> None:
        """대화 하나·4턴(A,A,B,A) → 인접쌍 3개 중 동일 1개(A,A) → 1/3."""
        m = _strategy_repeat_from_sequences([["조건확인", "조건확인", "단계분해", "조건확인"]])
        assert m.status is MetricStatus.MEASURED
        assert m.value == pytest_approx(1 / 3)

    def test_does_not_cross_dialogue_boundary(self) -> None:
        """대화 A 마지막='조건확인'·대화 B 처음='조건확인'이어도 경계를 넘어 쌍을 만들지 않는다.

        각 대화가 1턴뿐이면 인접쌍이 아예 생기지 않아야 한다(날조 방지) — 두 대화를 이어붙여
        인접쌍을 만들면 서로 다른 학습 맥락을 반복으로 오집계하게 된다.
        """
        m = _strategy_repeat_from_sequences([["조건확인"], ["조건확인"], ["조건확인"]])
        assert m.status is MetricStatus.NO_DATA  # 인접쌍 0개 — 세션 경계 미교차가 지켜졌다.


class TestStateMismatchRate:
    def test_zero_total_no_data(self) -> None:
        m = _state_mismatch_from_counts(0, 0)
        assert m.status is MetricStatus.NO_DATA
        assert m.value is None

    def test_measured_ratio(self) -> None:
        m = _state_mismatch_from_counts(1, 4)
        assert m.status is MetricStatus.MEASURED
        assert m.value == pytest_approx(0.25)
        assert "동기화 신호" in m.note

    def test_zero_mismatch_is_measured_zero(self) -> None:
        """불일치 0건이어도 total>0이면 MEASURED·value 0.0(가짜 0 아닌 실측 0)."""
        m = _state_mismatch_from_counts(0, 5)
        assert m.status is MetricStatus.MEASURED
        assert m.value == 0.0
