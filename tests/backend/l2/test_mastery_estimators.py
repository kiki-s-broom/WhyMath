"""계획서 300 §6 v1 가산 규칙 추정기 + 계약 경계 강제 — EOS-108 acceptance ①②③.

세 가지를 본다.

1. **규칙이 문서가 아니라 코드다** — §6이 글로 적은 네 규칙(정답 +0.10 / 오답 -0.08 /
   힌트 x0.7 / 연속 정답 → confidence↑)이 상수와 산출로 실재하는지.
2. **교체가 진짜로 된다** — 호출부를 한 글자도 고치지 않고 두 번째 *진짜* 구현이 도는지.
   가짜 스텁이 아니라 다른 수학을 쓰는 구현이어야 이 주장이 증명된다.
3. **계약이 추정기를 신뢰하지 않는다** — 범위 밖 산출·NaN·사후 변조가 학습자 상태에 닿지
   않는지(클램프 우회 주입).
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from whymath_backend.l2.bkt import BktParameters
from whymath_backend.l2.mastery_contract import (
    BKT_ESTIMATOR_ID,
    AttemptOutcomeEvidence,
    resolve_estimator,
    update_mastery,
    use_estimator,
)
from whymath_backend.l2.mastery_estimators import (
    ADDITIVE_ESTIMATOR_ID,
    CONFIDENCE_HALFLIFE,
    CONFIDENCE_STREAK_CAP,
    CONFIDENCE_STREAK_STEP,
    CORRECT_GAIN,
    HINT_GAIN_FACTOR,
    INITIAL_MASTERY,
    WRONG_PENALTY,
    AdditiveMasteryEstimator,
)
from whymath_backend.schema.mastery_contract import (
    LearnerMasteryState,
    MasteryAxis,
    MasteryContractError,
    MasteryEstimator,
    MasteryUpdate,
    clamp_unit,
)

_T0 = datetime(2026, 1, 1, tzinfo=UTC)
_T1 = _T0 + timedelta(days=3)
_CID = str(uuid.uuid4())


def _state(mastery: float | None = 0.50, sample_size: int | None = 4) -> LearnerMasteryState:
    return LearnerMasteryState(
        axis=MasteryAxis.CONCEPT,
        target_id=_CID,
        mastery=mastery,
        sample_size=sample_size,
        measured_at=None if mastery is None else _T0,
    )


def _evidence(
    correct: bool,
    *,
    hint_used: bool | None = None,
    consecutive_correct: int | None = None,
) -> AttemptOutcomeEvidence:
    return AttemptOutcomeEvidence(
        correct=correct,
        observed_at=_T1,
        attempt_id=uuid.uuid4(),
        hint_used=hint_used,
        consecutive_correct=consecutive_correct,
    )


class TestPlanRulesAreCode:
    """§6의 네 규칙이 값으로 실재한다."""

    def test_correct_adds_the_declared_gain(self) -> None:
        """① 정답 → +0.10."""
        update = AdditiveMasteryEstimator().estimate(_state(0.50), _evidence(True))
        assert update.mastery == pytest.approx(0.50 + CORRECT_GAIN)
        assert CORRECT_GAIN == 0.10

    def test_wrong_subtracts_the_declared_penalty(self) -> None:
        """② 오답 → -0.08."""
        update = AdditiveMasteryEstimator().estimate(_state(0.50), _evidence(False))
        assert update.mastery == pytest.approx(0.50 - WRONG_PENALTY)
        assert WRONG_PENALTY == 0.08

    def test_penalty_is_smaller_than_gain(self) -> None:
        """오답 1회가 정답 1회를 지우지 않는다 — 교수학 전제(오답=정보)."""
        assert WRONG_PENALTY < CORRECT_GAIN

    def test_hint_scales_the_gain(self) -> None:
        """③ 힌트를 쓰고 맞히면 이득에 x0.7."""
        update = AdditiveMasteryEstimator().estimate(_state(0.50), _evidence(True, hint_used=True))
        assert update.mastery == pytest.approx(round(0.50 + CORRECT_GAIN * HINT_GAIN_FACTOR, 2))
        assert HINT_GAIN_FACTOR == 0.7

    def test_hint_does_not_soften_the_penalty(self) -> None:
        """③ 감점에는 곱하지 않는다 — 곱하면 힌트가 감점 회피 수단이 된다."""
        with_hint = AdditiveMasteryEstimator().estimate(
            _state(0.50), _evidence(False, hint_used=True)
        )
        without = AdditiveMasteryEstimator().estimate(_state(0.50), _evidence(False))
        assert with_hint.mastery == without.mastery

    def test_unknown_hint_is_not_treated_as_no_hint(self) -> None:
        """**모른다 ≠ 안 썼다** — `None`은 감액을 적용하지 않되, `False`와 같은 *사실*이 아니다.

        값이 같다는 것이 이 테스트의 요점이 아니다(같다). 요점은 **그 동일성이 우연이 아니라
        선언된 규약**이라는 것 — `None`을 `False`로 접는 구현으로 바꿔도 이 테스트는 통과하므로,
        3상태 보존은 `hint_used_of`의 반환 타입이 지킨다. 여기서는 그 규약이 회귀하지 않는지만
        고정한다(감액이 `None`에 적용되기 시작하면 RED).
        """
        unknown = AdditiveMasteryEstimator().estimate(_state(0.50), _evidence(True))
        explicit_no = AdditiveMasteryEstimator().estimate(
            _state(0.50), _evidence(True, hint_used=False)
        )
        assert unknown.mastery == explicit_no.mastery == pytest.approx(0.60)

    def test_streak_raises_confidence(self) -> None:
        """④ 연속 정답 → confidence 증가."""
        plain = AdditiveMasteryEstimator().estimate(_state(0.50), _evidence(True))
        streaked = AdditiveMasteryEstimator().estimate(
            _state(0.50), _evidence(True, consecutive_correct=3)
        )
        assert streaked.confidence > plain.confidence
        assert streaked.confidence == pytest.approx(
            round(5 / (5 + CONFIDENCE_HALFLIFE) + CONFIDENCE_STREAK_STEP * 3, 2)
        )

    def test_streak_bonus_is_capped(self) -> None:
        """④ 가산에 상한이 있다 — 없으면 연속 정답만으로 confidence가 1.0에 붙는다."""
        capped = AdditiveMasteryEstimator().estimate(
            _state(0.50), _evidence(True, consecutive_correct=CONFIDENCE_STREAK_CAP)
        )
        beyond = AdditiveMasteryEstimator().estimate(
            _state(0.50), _evidence(True, consecutive_correct=CONFIDENCE_STREAK_CAP + 50)
        )
        assert capped.confidence == beyond.confidence

    def test_streak_bonus_requires_this_observation_to_be_correct(self) -> None:
        """④ 이번이 오답이면 연속이 거기서 끊긴다 — 가산하지 않는다."""
        wrong = AdditiveMasteryEstimator().estimate(
            _state(0.50), _evidence(False, consecutive_correct=9)
        )
        plain_wrong = AdditiveMasteryEstimator().estimate(_state(0.50), _evidence(False))
        assert wrong.confidence == plain_wrong.confidence

    def test_negative_streak_is_a_contract_error(self) -> None:
        """음수 연속 정답은 조용히 0으로 고치지 않는다 — 조용한 정정은 관측을 날조한다."""
        with pytest.raises(MasteryContractError):
            AdditiveMasteryEstimator().estimate(
                _state(0.50), _evidence(True, consecutive_correct=-1)
            )


class TestBoundsAreRuleNotRescue:
    """클램프가 규칙의 일부다 — 경계에서도 산출이 계약을 만족한다."""

    def test_clamps_at_upper_bound(self) -> None:
        update = AdditiveMasteryEstimator().estimate(_state(0.97), _evidence(True))
        assert update.mastery == 1.0

    def test_clamps_at_lower_bound(self) -> None:
        update = AdditiveMasteryEstimator().estimate(_state(0.03), _evidence(False))
        assert update.mastery == 0.0

    def test_first_observation_starts_from_declared_prior(self) -> None:
        """첫 관측은 선언된 사전값에서 출발하고, `prior_mastery`는 None으로 남는다."""
        update = AdditiveMasteryEstimator().estimate(_state(None, None), _evidence(True))
        assert update.prior_mastery is None
        assert update.mastery == pytest.approx(round(INITIAL_MASTERY + CORRECT_GAIN, 2))
        assert update.sample_size == 1

    def test_initial_prior_matches_bkt(self) -> None:
        """두 추정기의 **출발점이 같다** — 다르면 차이가 규칙 탓인지 사전값 탓인지 모른다."""
        assert INITIAL_MASTERY == pytest.approx(BktParameters().p_init)

    def test_confidence_halflife_matches_bkt_kernel(self) -> None:
        """신뢰도 척도도 같다 — 추정기 교체가 confidence 때문에 판정을 흔들지 않게."""
        from whymath_backend.l2.mastery_contract import _CONFIDENCE_HALFLIFE

        assert CONFIDENCE_HALFLIFE == _CONFIDENCE_HALFLIFE


class TestSwappabilityIsReal:
    """구현을 갈아 끼워도 **호출부는 한 글자도 바뀌지 않는다**."""

    def test_default_is_still_bkt(self) -> None:
        """기본값은 `bkt-v1` 그대로 — 가산 규칙은 등록되되 전 학생에게 적용되지 않는다."""
        assert resolve_estimator().estimator_id == BKT_ESTIMATOR_ID

    def test_additive_is_registered(self) -> None:
        """등록은 돼 있다 — 전환이 코드 변경이 아니라 설정 한 줄이 되도록."""
        assert resolve_estimator(ADDITIVE_ESTIMATOR_ID).estimator_id == ADDITIVE_ESTIMATOR_ID

    def test_swapping_default_changes_the_math_without_touching_callers(self) -> None:
        """`update_mastery` 호출은 동일한데 산출이 달라진다 — 그것이 교체 가능성의 증거다."""
        state, evidence = _state(0.50), _evidence(True)
        before = update_mastery(state, evidence)
        with use_estimator(ADDITIVE_ESTIMATOR_ID):
            swapped = update_mastery(state, evidence)
        after = update_mastery(state, evidence)

        assert before.estimator_id == BKT_ESTIMATOR_ID
        assert swapped.estimator_id == ADDITIVE_ESTIMATOR_ID
        assert swapped.mastery != before.mastery, "두 구현이 같은 값을 내면 교체가 증명되지 않는다"
        assert after.estimator_id == BKT_ESTIMATOR_ID, "컨텍스트를 나가면 반드시 원복된다"

    def test_additive_satisfies_estimator_protocol(self) -> None:
        """상속 없이 구조적으로 만족한다 — Protocol이 계약이지 기반 클래스가 아니다."""
        assert isinstance(AdditiveMasteryEstimator(), MasteryEstimator)

    def test_carries_attempt_id_through(self) -> None:
        """멱등 키는 추정기가 만들지 않고 **옮긴다**."""
        evidence = _evidence(True)
        update = AdditiveMasteryEstimator().estimate(_state(), evidence)
        assert update.attempt_id == evidence.attempt_id

    def test_reports_elapsed_days_even_though_unused(self) -> None:
        """감쇠를 쓰지 않아도 경과일은 산출에 남는다 — 두 추정기를 나란히 비교하기 위해서."""
        update = AdditiveMasteryEstimator().estimate(_state(0.5), _evidence(True))
        assert update.elapsed_days == pytest.approx(3.0)


# ── 클램프 우회 주입 (acceptance ⑦-나) ───────────────────────────────────────


class _OutOfRangeEstimator:
    """계약을 어기는 추정기 — 생성자 검사를 **우회해** 범위 밖 값을 반환한다.

    `MasteryUpdate.__post_init__`이 범위를 검사하므로 정직한 생성자 호출로는 이 상태를 만들
    수 없다. 그래서 `object.__setattr__`로 frozen dataclass를 사후 변조한다 — 이것이 정확히
    "생성자 검사만으로는 막히지 않는 경로"이며, 계약 층의 두 번째 회계가 필요한 이유다.
    """

    def __init__(self, mastery: float = 1.8, confidence: float = -0.4) -> None:
        self._mastery = mastery
        self._confidence = confidence

    @property
    def estimator_id(self) -> str:
        return "rogue-out-of-range"

    def estimate(
        self,
        learner_state: LearnerMasteryState,
        assessment_evidence: AttemptOutcomeEvidence,
    ) -> MasteryUpdate:
        update = MasteryUpdate(
            axis=learner_state.axis,
            target_id=learner_state.target_id,
            mastery=0.5,
            confidence=0.5,
            sample_size=1,
            prior_mastery=learner_state.mastery,
            elapsed_days=None,
            estimator_id=self.estimator_id,
        )
        object.__setattr__(update, "mastery", self._mastery)
        object.__setattr__(update, "confidence", self._confidence)
        return update


class TestContractDoesNotTrustEstimators:
    """추정기가 계약을 어겨도 **학습자 상태에는 범위 안 값만 들어간다**."""

    def test_injection_actually_applies(self) -> None:
        """주입이 실제로 적용됐는지 먼저 단언한다 — 안 들어간 주입은 '검출'처럼 보인다."""
        rogue = _OutOfRangeEstimator().estimate(_state(), _evidence(True))
        assert rogue.mastery == 1.8 and rogue.confidence == -0.4

    def test_out_of_range_output_is_clamped(self) -> None:
        """범위 밖 산출이 계약을 통과하면 0~1로 잘린다."""
        update = update_mastery(_state(), _evidence(True), estimator=_OutOfRangeEstimator())
        assert update.mastery == 1.0
        assert update.confidence == 0.0
        assert update.bounds_clamped is True

    def test_clamping_is_not_silent(self, caplog: pytest.LogCaptureFixture) -> None:
        """자른 사실이 로그에 남는다 — 값은 구제하되 사실은 잃지 않는다(침묵 실패 금지)."""
        with caplog.at_level(logging.WARNING, logger="whymath.l2.mastery_contract"):
            update_mastery(_state(), _evidence(True), estimator=_OutOfRangeEstimator())
        assert any(
            "MasteryContractBoundsViolation" in record.message
            and "rogue-out-of-range" in str(record.args)
            for record in caplog.records
        )

    def test_in_range_output_is_untouched(self) -> None:
        """**대조군** — 정상 산출에는 `bounds_clamped`가 붙지 않는다.

        이것이 없으면 "전부 clamped로 표시"라는 과잉 수정이 위 테스트를 통과한다.
        """
        update = update_mastery(_state(), _evidence(True))
        assert update.bounds_clamped is False

    def test_nan_is_rejected_not_clamped(self) -> None:
        """NaN은 비교가 전부 False라 조용히 통과한다 — 자를 수 없으므로 예외로 드러낸다."""
        with pytest.raises(MasteryContractError):
            update_mastery(
                _state(), _evidence(True), estimator=_OutOfRangeEstimator(mastery=math.nan)
            )

    def test_clamp_unit_itself_rejects_nan(self) -> None:
        """`clamp_unit`의 NaN 절을 **직접** 밟는다 — 위 테스트는 이 절을 밟지 않는다.

        뮤테이션 실측(2026-09-18): `clamp_unit`의 NaN 검사를 제거해도 위
        `test_nan_is_rejected_not_clamped`는 **통과했다**. NaN이 그대로 반환되면
        `nan == nan`이 False라 `_enforce_bounds`가 클램프 분기로 들어가고, 거기서
        `MasteryUpdate.__post_init__`의 범위 검사가 대신 터지기 때문이다 — 즉 그 테스트는
        *다른 절* 덕에 초록이었고 NaN 절의 생존을 덮고 있었다(CLAUDE.md 「픽스처가 그 절을
        실제로 밟는가」). 이 테스트가 그 절의 반례를 직접 준다.
        """
        assert clamp_unit(1.8) == 1.0  # 대조군 — 정상 클램프는 여전히 동작한다
        with pytest.raises(MasteryContractError):
            clamp_unit(math.nan)
