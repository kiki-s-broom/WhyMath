"""EOS-14 추천 호출 계약 — 정책 규칙·필수 Reason·임계 정본 (hermetic·순수).

이 파일이 지키는 것은 넷이다.

① **계획서 §8 분기 규칙** — `<0.4 prerequisite` / `0.4~0.7 current` / `>0.7 next`. 경계가
   어느 쪽으로 닫히는지까지 못 박는다(0.7은 current이고 0.7 *초과*라야 next).
② **미측정은 구간이 아니다** — 콜드스타트를 0.0으로 접으면 측정된 적 없는 학생이 전부
   "선수개념이 막혔다"로 분류된다. 그 오진을 막는 절이 `select_reason_type`의 첫 분기다.
③ **reason은 필수** — 추천이 없어도(`problem_id=None`) 이유가 있다. 옵셔널이면 비는 경로가
   생기고, 비는 경로가 규칙을 무력화한다.
④ **임계 정본** — 약점 컷 0.7이 두 추천 모듈의 기본값과 *같은 상수*인가. 값이 갈라지면
   "약점"의 정의가 모듈마다 달라진다.

DB·상위 계층 의존 0 — 전부 순수 함수다.
"""

from __future__ import annotations

import inspect
import typing
import uuid

import pytest

from whymath_backend.l2 import prerequisite_recommendation, weak_concept_recommendation
from whymath_backend.l2.recommendation_contract import (
    PREREQUISITE_MASTERY_CEILING,
    WEAK_CONCEPT_MASTERY_CEILING,
    LearningContext,
    ReasonBasis,
    ReasonType,
    Recommendation,
    RecommendationPolicy,
    RecommendationReason,
    build_reason,
    no_candidate_reason,
    select_reason_type,
)

_CONCEPT = uuid.uuid4()


# ──────────────────────────────────────────────────────────────────────────
# ①② 분기 규칙과 경계
# ──────────────────────────────────────────────────────────────────────────
class TestSelectReasonType:
    @pytest.mark.parametrize(
        ("mastery", "expected"),
        [
            (0.0, ReasonType.PREREQUISITE_GAP),
            (0.39, ReasonType.PREREQUISITE_GAP),
            (0.4, ReasonType.CURRENT_CONCEPT),  # 경계는 current 쪽으로 닫힌다
            (0.55, ReasonType.CURRENT_CONCEPT),
            (0.7, ReasonType.CURRENT_CONCEPT),  # 0.7 자체는 아직 current
            (0.71, ReasonType.NEXT_CONCEPT),
            (1.0, ReasonType.NEXT_CONCEPT),
        ],
    )
    def test_mastery_bands_follow_the_plan_rule(self, mastery: float, expected: ReasonType) -> None:
        assert select_reason_type(mastery) is expected

    def test_unmeasured_is_not_folded_into_prerequisite(self) -> None:
        """콜드스타트를 0.0으로 접으면 측정된 적 없는 학생이 전부 '선수 막힘'이 된다."""
        assert select_reason_type(None) is ReasonType.UNMEASURED
        assert select_reason_type(0.0) is ReasonType.PREREQUISITE_GAP
        assert select_reason_type(None) is not select_reason_type(0.0)

    def test_boundaries_use_the_named_constants(self) -> None:
        """경계가 상수에서 오지 않으면 상수를 고쳐도 규칙이 안 따라온다."""
        assert select_reason_type(PREREQUISITE_MASTERY_CEILING) is ReasonType.CURRENT_CONCEPT
        assert (
            select_reason_type(PREREQUISITE_MASTERY_CEILING - 0.01) is ReasonType.PREREQUISITE_GAP
        )
        assert select_reason_type(WEAK_CONCEPT_MASTERY_CEILING) is ReasonType.CURRENT_CONCEPT
        assert select_reason_type(WEAK_CONCEPT_MASTERY_CEILING + 0.01) is ReasonType.NEXT_CONCEPT


# ──────────────────────────────────────────────────────────────────────────
# ③ 근거 조립 — 근거 없음을 근거로 위장하지 않는다
# ──────────────────────────────────────────────────────────────────────────
class TestBuildReason:
    def test_measured_mastery_carries_band_and_confidence(self) -> None:
        reason = build_reason(concept_id=_CONCEPT, mastery=0.25, confidence=0.6)
        assert reason.type is ReasonType.PREREQUISITE_GAP
        assert reason.basis is ReasonBasis.MEASURED_MASTERY
        assert reason.concept_id == _CONCEPT
        assert reason.mastery == pytest.approx(0.25)
        assert reason.confidence == pytest.approx(0.6)

    def test_unmapped_concept_and_cold_start_are_different_bases(self) -> None:
        """둘 다 '근거 없음'이지만 하나는 데이터 공백, 하나는 학생 상태다."""
        unmapped = build_reason(concept_id=None, mastery=None, confidence=None)
        cold = build_reason(concept_id=_CONCEPT, mastery=None, confidence=None)
        assert unmapped.basis is ReasonBasis.CONCEPT_UNMAPPED
        assert cold.basis is ReasonBasis.COLD_START
        assert unmapped.type is cold.type is ReasonType.UNMEASURED
        assert unmapped.basis is not cold.basis

    def test_unmapped_concept_does_not_claim_a_concept(self) -> None:
        reason = build_reason(concept_id=None, mastery=None, confidence=None)
        assert reason.concept_id is None

    @pytest.mark.parametrize(
        "reason",
        [
            build_reason(concept_id=None, mastery=None, confidence=None),
            build_reason(concept_id=_CONCEPT, mastery=None, confidence=None),
            no_candidate_reason(),
        ],
    )
    def test_absent_evidence_scores_zero_not_a_middle_value(
        self, reason: RecommendationReason
    ) -> None:
        """0.5로 채우면 '모른다'가 '반쯤 안다'로 읽힌다."""
        assert reason.confidence == 0.0

    def test_missing_confidence_on_measured_row_is_zero_not_invented(self) -> None:
        """구판 행처럼 숙달은 있는데 신뢰도가 비면 0.0 — 있는 척하지 않는다."""
        reason = build_reason(concept_id=_CONCEPT, mastery=0.9, confidence=None)
        assert reason.type is ReasonType.NEXT_CONCEPT
        assert reason.confidence == 0.0
        assert reason.mastery == pytest.approx(0.9)

    def test_no_candidate_reason_is_self_describing(self) -> None:
        reason = no_candidate_reason()
        assert reason.type is ReasonType.NO_CANDIDATE
        assert reason.basis is ReasonBasis.NO_CANDIDATE_POOL
        assert reason.concept_id is None
        assert reason.mastery is None


class TestReasonIsRequired:
    def test_recommendation_cannot_be_built_without_a_reason(self) -> None:
        """옵셔널이면 비는 경로가 생기고, 비는 경로가 이 계약을 무력화한다."""
        with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError(버전 무관)
            Recommendation(problem_id=uuid.uuid4())  # type: ignore[call-arg]

    def test_recommendation_without_a_problem_still_carries_a_reason(self) -> None:
        rec = Recommendation(problem_id=None, reason=no_candidate_reason())
        assert rec.problem_id is None
        assert rec.reason.type is ReasonType.NO_CANDIDATE

    def test_reason_is_frozen(self) -> None:
        reason = no_candidate_reason()
        with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
            reason.confidence = 1.0  # type: ignore[misc]

    def test_confidence_outside_unit_interval_is_rejected(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
            RecommendationReason(
                type=ReasonType.NEXT_CONCEPT,
                confidence=1.5,
                basis=ReasonBasis.MEASURED_MASTERY,
            )

    def test_context_rejects_unknown_fields(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
            LearningContext(purpose="diagnosis", sql_limit=50)  # type: ignore[call-arg]


# ──────────────────────────────────────────────────────────────────────────
# ④ 임계 정본 — 두 추천 모듈이 같은 상수를 쓰는가
# ──────────────────────────────────────────────────────────────────────────
class TestThresholdSingleSource:
    @pytest.mark.parametrize(
        "func",
        [
            weak_concept_recommendation.recommend_weak_concepts_detailed,
            weak_concept_recommendation.recommend_weak_concepts,
            prerequisite_recommendation.recommend_prerequisite_gaps_detailed,
            prerequisite_recommendation.recommend_prerequisite_gaps,
        ],
    )
    def test_weak_cut_defaults_come_from_the_contract(self, func: object) -> None:
        """기본값이 리터럴로 되돌아가면 '약점'의 정의가 모듈마다 갈라진다."""
        default = inspect.signature(func).parameters["mastery_threshold"].default  # type: ignore[arg-type]
        assert default == WEAK_CONCEPT_MASTERY_CEILING

    def test_weak_cut_value_is_unchanged_from_before_consolidation(self) -> None:
        """통합은 *이름*을 모으는 것이지 값을 바꾸는 것이 아니다(회귀 0 · acceptance ⑥)."""
        assert WEAK_CONCEPT_MASTERY_CEILING == 0.7

    def test_lthc_band_is_not_folded_into_the_weak_cut(self) -> None:
        """`learner_state`의 LTHC 밴드는 **다른 축**이다 — 상한이 0.8이라 합치면 한쪽이 움직인다.

        값이 같다고 합치지 않는다는 판단을 기계로 남긴다: 0.4는 두 곳에서 같지만 상한이 다르다.
        """
        from whymath_backend.l2 import learner_state

        assert learner_state._DEVELOPING_THRESHOLD == PREREQUISITE_MASTERY_CEILING
        assert learner_state._MASTERED_THRESHOLD == 0.8
        assert learner_state._MASTERED_THRESHOLD != WEAK_CONCEPT_MASTERY_CEILING


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 교체 가능성 — Protocol 시그니처가 타입으로 서 있는가 (주석이 아니라)
# ──────────────────────────────────────────────────────────────────────────
class TestPolicyProtocolShape:
    """`RecommendationPolicy`는 **아직 구현체가 없다** — 그래서 더 단단히 동결한다.

    구현체가 없는 Protocol은 아무 테스트도 건드리지 않으므로 조용히 표류한다. 이 태스크가
    넘기는 것은 *시그니처 약속*이고, 그 약속을 받는 쪽(핸들러의 learner_state 입력 전환)은
    후속 태스크다 — 그 사이에 모양이 바뀌면 후속이 다른 계약을 구현하게 된다.
    """

    def test_takes_only_learner_state_and_learning_context(self) -> None:
        """입력이 둘뿐인 것이 요점 — 상태 추정 방식(BKT/DKT/IRT)이 정책 바깥 관심사가 된다."""
        params = list(inspect.signature(RecommendationPolicy.__call__).parameters)
        assert params == ["self", "learner_state", "learning_context"]

    def test_returns_a_recommendation_not_a_bare_problem_id(self) -> None:
        """반환이 `uuid`면 근거가 낄 자리가 없다 — 결과와 이유를 한 반환값에 묶는다."""
        hints = typing.get_type_hints(RecommendationPolicy.__call__)
        assert hints["return"] is Recommendation

    def test_context_is_not_a_bag_of_transport_concerns(self) -> None:
        """SQL·페이지네이션이 섞이면 전송 계층이 바뀔 때 정책 계약이 따라 깨진다."""
        fields = set(LearningContext.model_fields)
        assert fields == {
            "purpose",
            "mode",
            "persona",
            "prioritize_weak_concepts",
            "requested_at",
        }

    def test_recommendation_is_frozen(self) -> None:
        """추천도 사후 변조 불가 — 근거만 얼리고 결과를 열어 두면 둘이 갈라진다."""
        rec = Recommendation(reason=no_candidate_reason())
        with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
            rec.problem_id = uuid.uuid4()  # type: ignore[misc]
