"""추천 호출 계약 — `recommend(learner_state, learning_context)` + **필수 Reason** (EOS-14).

설계 정본: 계획서 300 §8. 요지는 *"Recommendation이 아니라 Recommendation + Reason을 처음부터
설계"*이고, 그 말의 실제 내용은 **추천 결과와 그 근거가 같은 반환값에 함께 있어야 한다**는 것이다.
근거를 옵셔널로 두면 비는 경로가 생기고, 비는 경로가 생기면 "왜 이 문항인가"는 결국 아무도
대답하지 못한다.

────────────────────────────────────────────────────────────────────────────
현행과의 차이 (acceptance ③ — 먼저 적는다 · 2026-09-17 main `27df076e` 실측)
────────────────────────────────────────────────────────────────────────────
`NextProblemResponse`의 5필드(`weight_axes_applied`·`candidate_pool_size`·
`weak_concept_signal_count`·`candidate_zero_reason`·`band_calibrated`)는 **관측 메타**다 —
*어느 축이 적용됐나*·*후보가 왜 0인가*를 말한다. 그것은 추천기가 어떻게 돌았는지의 기록이지
**선택된 문항의 추천 근거**가 아니다. "어느 개념이 약해서 이 문항인가"는 어디에도 없다.

`RecommendationReason`이 담는 것은 후자다. 둘은 경쟁하지 않는다 — 관측 메타는 그대로 두고
근거를 **추가**한다(기존 5필드 불변 · 회귀 0).

────────────────────────────────────────────────────────────────────────────
임계값 — "분산된 3모듈"은 셋이 같은 값이 아니었다 (acceptance ⑤ 실측 정정)
────────────────────────────────────────────────────────────────────────────
착수 지시는 임계가 3모듈에 분산돼 있으니 단일 정책 함수로 모으라고 했다. 실측하니 **셋 중 둘만
같은 축**이었다:

| 위치 | 값 | 의미 |
|---|---|---|
| `l2/weak_concept_recommendation.recommend_weak_concepts_detailed` | 0.7 | 약점 판정 컷 |
| `l2/prerequisite_recommendation.recommend_prerequisite_gaps_detailed` | 0.7 | 약점 판정 컷 |
| `l2/learner_state._DEVELOPING_THRESHOLD`/`_MASTERED_THRESHOLD` | 0.4 / **0.8** | LTHC 숙달 밴드 |

앞의 둘은 같은 질문("이 개념이 약한가")에 답하므로 `WEAK_CONCEPT_MASTERY_CEILING` 하나로
모은다. 세 번째는 **다른 축**이다 — `l4/lthc/adapt.py`의 교수학 밴드를 L2가 값만 미러한 것이고
(역방향 의존 금지), 상한도 0.7이 아니라 0.8이다. 합치면 두 개념이 한 상수로 접혀 한쪽을 고칠 때
다른 쪽이 조용히 따라 움직인다 — 그래서 **합치지 않고 이 표로 관계만 명시**한다.

계획서 §8의 추천 분기 규칙(`<0.4 → prerequisite` / `0.4~0.7 → current` / `>0.7 → next`)은
`select_reason_type`이 정본이다. 그 상한 0.7은 위 약점 컷과 의미가 같아(0.7 초과 = 더는 약점이
아니다) **같은 상수를 쓴다** — 우연한 일치가 아니라 같은 판단이다.

────────────────────────────────────────────────────────────────────────────
이 계약이 지는 불변식
────────────────────────────────────────────────────────────────────────────
- **`reason`은 필수다.** `Recommendation`에 추천이 없어도(`problem_id=None`) 이유는 있다 —
  "후보가 없었다"도 이유다. 옵셔널로 두면 그 경로가 비고, 비는 경로가 규칙을 무력화한다.
- **근거 없음을 근거로 위장하지 않는다.** 숙달 측정이 없으면 `UNMEASURED`·`confidence=0.0`이고,
  문항-개념 매핑이 없으면 `CONCEPT_UNMAPPED`다. 0.5 같은 중간값으로 채우면 "잘 모르겠다"가
  "반쯤 확신한다"로 읽힌다(CLAUDE.md "모르면 모른다고").
- **교체 가능성을 타입으로 표현한다.** `RecommendationPolicy` Protocol은 `learner_state`와
  `learning_context`만 받는다 — v1 내부가 if/else 규칙이어도, BKT를 DKT로 갈거나 bandit을
  얹어도 이 시그니처는 그대로다.
- **설명은 콘텐츠와 어긋나지 않는다**(EOS-124). `target_concept`은 전달된 문항의 대표 개념이고,
  관계 행위(선수 복귀·전진)는 앵커와 *다른* 개념을 가리킨다 — `check_intent_alignment`가 구조를
  판정한다. 관계 행위를 실을 수 없으면 `demote_to_current_concept`로 정직하게 내린다.
- **선택 알고리즘을 여기서 재구현하지 않는다**(acceptance ④·⑥). 후보 선별·가중·정보량 최대
  선택은 기존 좌석(`l2.irt.select_weighted_item`·`l6.suneung.recommend_suneung_index`)이
  유일 권위이고, 이 모듈은 *이미 선택된 결과*에 근거를 붙인다. 그래서 계약 도입이 추천 결과를
  바꾸지 않는다.

────────────────────────────────────────────────────────────────────────────
지금 배선된 것과 아닌 것 (정직 표기 — "정본화를 집행으로 착각한 완료 선언 금지")
────────────────────────────────────────────────────────────────────────────
**배선됨**: `RecommendationReason`은 `GET /v1/me/next-problem`의 **필수** 응답 필드이고
(`api/me.py`의 4개 반환 경로 전부), 같은 값이 `l2.recommendation_evidence`의 처치 기록
meta에도 함께 실린다(영속 좌석 신설 0 — acceptance ④).

**아직 아님**: `RecommendationPolicy`·`LearningContext`·`Recommendation` 세 타입은
**소비처 0건**이다. 핸들러는 여전히 `user_id` + 쿼리 파라미터로 내부 재계산하며
`learner_state`를 입력으로 받지 않는다. 그 전환의 소유자는 **`EOS-19`**이고, 그때까지
이 Protocol의 모양은 `tests/backend/l2/test_recommendation_contract.py::
TestPolicyProtocolShape`가 동결한다 — 구현체가 없는 Protocol은 아무 테스트도 건드리지
않아 조용히 표류하기 때문이다.

계층: `l2`(학습자 모델). L3/L4/L6을 import하지 않는다 — 수능 가중·LTHC는 상위 계층 소관이고
이 모듈은 그 결과를 받기만 한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Final, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "PREREQUISITE_MASTERY_CEILING",
    "RELATIONAL_ACTIONS",
    "WEAK_CONCEPT_MASTERY_CEILING",
    "IntentAlignmentError",
    "LearnerStateT",
    "LearningContext",
    "Recommendation",
    "RecommendationAction",
    "RecommendationPolicy",
    "RecommendationReason",
    "ReasonBasis",
    "ReasonType",
    "action_for",
    "build_reason",
    "check_intent_alignment",
    "demote_to_current_concept",
    "no_candidate_reason",
    "remediation_reason",
    "select_reason_type",
]

#: 약점 판정 컷 — 이 값 **이상**이면 더는 약점이 아니다.
#: `recommend_weak_concepts_detailed`·`recommend_prerequisite_gaps_detailed`의 기본
#: `mastery_threshold`와 같은 값이며(둘 다 0.7), 계획서 §8의 `current`↔`next` 경계와도 같다 —
#: 세 자리가 같은 질문("이 개념이 아직 약한가")에 답하므로 상수 하나가 정본이다.
WEAK_CONCEPT_MASTERY_CEILING: Final = 0.7

#: 선수개념으로 되돌아갈 경계 — 이 값 **미만**이면 현재 개념을 더 밀어도 막힌다(계획서 §8).
#: `learner_state._DEVELOPING_THRESHOLD`와 값이 같지만 **다른 축**이다(그쪽은 L4 LTHC 밴드의
#: 미러이고 상한이 0.8이다) — 모듈 docstring의 표 참조. 값이 같다고 합치지 않는다.
PREREQUISITE_MASTERY_CEILING: Final = 0.4


class ReasonType(str, Enum):
    """**왜 이 문항인가** — 계획서 §8의 추천 종류 + 근거가 없는 두 경우 + 상태 머신 결정 1종.

    앞의 셋은 숙달 구간에서 나오고, 넷째·다섯째는 *구간을 판정할 수 없는* 상태다. 넷째·다섯째를
    셋 중 하나로 접으면 근거 없음이 근거로 위장된다.

    여섯째(`MISCONCEPTION_REMEDIATION`)는 **숙달 구간이 아니라 학습 상태 머신의 결정**에서 나온다
    (EOS-24). 그래서 숙달이 선수 경계 미만이어도 이 값일 수 있다 — 오개념과 선수 결손 중 무엇이
    먼저인가는 상태 머신 규칙(`l2/learning_state_policy.py::V1_RULES`)이 정본이고, 추천은 그
    결정을 다시 판정하지 않고 집행한다.
    """

    PREREQUISITE_GAP = "prerequisite_gap"
    """숙달이 선수 경계 미만 — 현재 개념을 더 밀기 전에 막힌 선수개념을 푼다."""

    CURRENT_CONCEPT = "current_concept"
    """같은 개념을 계속 연습한다 — 숙달이 학습 구간이거나(§8 규칙), **정직 강등**이다.

    정직 강등(EOS-124): 숙달 구간은 선수 복귀·전진을 가리켰으나 그 행위를 실제 문항으로
    실어 줄 수 없을 때(그래프 근거가 없거나 반증됐거나, 목표 개념에 출제 가능한 문항이
    없을 때) 전달되는 것은 앵커 개념 자신의 문항이다. 그때 행위를 "선수를 연습하라"·
    "다음으로 넘어가라"로 적으면 설명이 콘텐츠와 어긋난다 — 그래서 이 값으로 내린다.
    `mastery`는 실측값 그대로 실리므로(0.4~0.7 밖일 수 있다) 숨기는 것은 없고, 어느 경우인지는
    정책 관측 메타(`intent_resolution`)가 따로 말한다.
    """

    NEXT_CONCEPT = "next_concept"
    """숙달이 약점 컷 초과 — 다음 개념으로 넘어갈 수 있다."""

    UNMEASURED = "unmeasured"
    """이 개념의 숙달 측정이 없다(콜드스타트) — 구간을 말할 수 없다."""

    NO_CANDIDATE = "no_candidate"
    """추천할 문항이 없다 — 추천의 부재도 이유를 가진다."""

    MISCONCEPTION_REMEDIATION = "misconception_remediation"
    """학습 상태 머신이 오개념 교정 국면을 결정했다(R3) — 같은 개념에서 교정을 확인한다(EOS-24).

    `basis`는 언제나 `LEARNING_STATE`다(검증기가 강제). `confidence`는 숙달 신뢰도가 아니라
    *이번 회차에 확인된 오개념 가설의 신뢰*이고, `mastery`는 그 개념의 실측 숙달을 참고로 싣는다.
    """


class ReasonBasis(str, Enum):
    """`type`이 **무엇에 근거**하는가 — 같은 type이라도 근거가 다르면 신뢰도가 다르다."""

    MEASURED_MASTERY = "measured_mastery"
    """이 개념의 실측 숙달로 구간을 판정했다."""

    COLD_START = "cold_start"
    """숙달 이력이 없어 구간을 판정하지 못했다(학생이 아니라 데이터의 상태다)."""

    CONCEPT_UNMAPPED = "concept_unmapped"
    """문항에 평가 개념이 매핑돼 있지 않다 — 우리 쪽 공백이다."""

    NO_CANDIDATE_POOL = "no_candidate_pool"
    """후보 자체가 없었다 — 근거를 댈 대상이 없다."""

    LEARNING_STATE = "learning_state"
    """학습 상태 머신의 결정(원장 최신 전이)을 집행했다 — 숙달 구간 파생이 아니다(EOS-24)."""


#: 상태 머신 결정에서만 나오는 근거 종류 ↔ 그 근거 기반. 둘은 **짝으로만** 존재한다 —
#: 한쪽만 있으면 "상태 머신이 결정했다"와 "숙달 구간에서 나왔다"가 한 근거 안에서 섞인다.
_STATE_DRIVEN_TYPES: Final[frozenset["ReasonType"]] = frozenset(
    {ReasonType.MISCONCEPTION_REMEDIATION}
)


class RecommendationReason(BaseModel):
    """추천 근거 — `Recommendation`의 **필수** 동반자.

    `confidence`는 *이 근거를 얼마나 믿을 수 있는가*이지 정답 확률이 아니다. 실측 숙달에서
    나온 BKT 신뢰도(표본 수에 따라 커진다)를 그대로 옮기고, 근거가 없으면 **0.0**이다 —
    중간값으로 채우면 "모른다"가 "반쯤 안다"로 읽힌다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: ReasonType
    confidence: float = Field(ge=0.0, le=1.0)
    basis: ReasonBasis
    concept_id: uuid.UUID | None = Field(
        default=None, description="근거가 된 개념. 매핑이 없거나 후보가 없으면 None."
    )
    mastery: float | None = Field(
        default=None, description="그 개념의 실측 숙달. 미측정이면 None(0.0으로 접지 않는다)."
    )

    @model_validator(mode="after")
    def _state_basis_pairs_with_state_type(self) -> "RecommendationReason":
        """상태 머신 근거 종류 ⟺ `LEARNING_STATE` 기반 — 어긋난 조합은 **만들어지지 않는다**.

        숙달 구간 근거에 `LEARNING_STATE`를 달거나, 오개념 교정 근거에 `MEASURED_MASTERY`를 달면
        "누가 이 추천을 결정했는가"가 거짓이 된다. 그 거짓은 처치 기록 meta에 그대로 영속되어
        소급 평가를 오염시키므로 생성 시점에 막는다(EOS-24).
        """
        state_type = self.type in _STATE_DRIVEN_TYPES
        state_basis = self.basis is ReasonBasis.LEARNING_STATE
        if state_type != state_basis:
            raise ValueError(
                f"reason.type({self.type.value})과 basis({self.basis.value})가 어긋납니다 — "
                "상태 머신 결정 근거는 basis=learning_state와만 짝을 이룹니다."
            )
        return self


class LearningContext(BaseModel):
    """추천 요청의 **상황** — 학습자 상태와 직교하는 축들.

    핸들러의 쿼리 파라미터를 그대로 옮긴 것이 아니라, *추천 정책이 읽어야 하는 것*만 담는다.
    정책이 바뀌어도 이 모양이 유지돼야 하므로 SQL·페이지네이션 같은 전송 관심사는 넣지 않는다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    purpose: str = Field(
        default="diagnosis", description="diagnosis(정보량 최대)·learning(성공률 밴드)."
    )
    mode: str | None = Field(default=None, description="응용 모드(예: suneung). None=기본 CAT.")
    persona: str | None = Field(
        default=None, description="대상 페르소나 태그. 수능 모드에서만 쓰인다."
    )
    prioritize_weak_concepts: bool = False
    requested_at: datetime | None = None


class RecommendationAction(str, Enum):
    """**무엇을 하라는 추천인가** — 계획서 §8의 `action`(예: `PRACTICE_PREREQUISITE`).

    `ReasonType`이 *왜*를 말한다면 이것은 *무엇을*을 말한다. 둘은 1:1 대응이지만 같은 필드가
    아니다 — 근거의 종류가 늘어도(예: 오개념 기반 근거) 행위는 기존 다섯 중 하나일 수 있고,
    반대로 같은 근거에서 행위가 갈라질 수도 있다(EOS-19 시점에는 갈라지지 않는다).

    **지금은 파생값이다**(`action_for`가 정본). 그 사실을 주석이 아니라 **검증기**로 못 박아
    (`Recommendation`의 model_validator) 근거와 행위가 어긋난 추천은 *만들어지지 않는다* —
    나중에 대응이 1:1이 아니게 되면 그때 `action_for`가 더 많은 입력을 받게 된다.
    """

    PRACTICE_PREREQUISITE = "practice_prerequisite"
    """막힌 선수개념을 먼저 연습한다(`PREREQUISITE_GAP`)."""

    PRACTICE_CURRENT = "practice_current"
    """현재 개념을 계속 연습한다(`CURRENT_CONCEPT`)."""

    ADVANCE_NEXT = "advance_next"
    """다음 개념으로 넘어간다(`NEXT_CONCEPT`)."""

    DIAGNOSE = "diagnose"
    """구간을 판정할 측정이 없다 — 측정을 먼저 한다(`UNMEASURED`).

    "아무거나 풀린다"가 아니라 *진단이 목적인 출제*라는 뜻이다. 콜드스타트를 연습 행위로
    적으면 측정이 목적인 출제가 학습으로 위장된다.
    """

    NONE = "none"
    """추천할 것이 없다(`NO_CANDIDATE`) — 부재도 행위 공간의 한 값이다."""


#: `ReasonType` → `RecommendationAction` 전사표. `action_for`의 유일한 출처이며, `ReasonType`에
#: 값이 늘면 이 dict가 비어 `action_for`가 **KeyError로 터진다** — 조용히 기본값을 주지 않는다
#: (근거 종류가 늘었는데 행위가 자동으로 "연습"이 되면 그 순간 추천이 근거와 무관해진다).
_ACTION_BY_REASON: Final[dict["ReasonType", "RecommendationAction"]] = {}


def action_for(reason_type: ReasonType) -> RecommendationAction:
    """근거 종류 → 추천 행위(순수·전사표 정본).

    미등록 `ReasonType`은 `KeyError`다. 기본값 폴백을 두지 않는 이유는 CLAUDE.md의 "모르면
    모른다고"와 같다 — 대응을 정하지 않은 근거에 임의의 행위를 붙이면, 틀린 추천이 조용히
    학생에게 나간다. 새 근거를 만든 사람이 그 자리에서 행위도 정하게 한다.
    """
    return _ACTION_BY_REASON[reason_type]


class Recommendation(BaseModel):
    """추천 1건 — 결과와 **근거가 함께** 나간다(계획서 §8의 요지).

    `problem_id`가 None이어도 `reason`은 있다. 그 경우 `type=NO_CANDIDATE`이며, 왜 후보가
    없었는지는 기존 관측 메타(`candidate_zero_reason`)가 따로 말한다 — 둘은 다른 질문에
    답하므로 합치지 않는다.

    **`action`은 근거에서 파생되며 손으로 넣을 수 없다**(EOS-19). 생략하면 `reason`에서
    채워지고, 어긋나는 값을 주면 생성이 **실패한다** — "근거 없는 추천을 구조적으로 만들 수
    없게 한다"의 짝이다(근거는 있는데 행위가 그 근거와 다른 추천도 같은 종류의 거짓말이다).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    problem_id: uuid.UUID | None = None
    reason: RecommendationReason
    action: RecommendationAction = Field(
        description="이 추천이 요구하는 학습 행위. `reason.type`에서 파생된다(손 입력 불가)."
    )
    target_concept: uuid.UUID | None = Field(
        default=None,
        description=(
            "학생이 **다음에 다뤄야 할 개념**. `reason.concept_id`(행위의 근거가 된 *앵커* "
            "개념)와 다를 수 있다: 선수 복귀(`PRACTICE_PREREQUISITE`)면 막힌 선수개념, 전진"
            "(`ADVANCE_NEXT`)이면 다음 개념이다. 근거를 댈 개념 자체가 없으면(미매핑·후보 0) "
            "None. 정렬 계약(EOS-124 · `check_intent_alignment`)을 따르는 정책에서는 이 값이 "
            "**전달된 문항의 대표 개념과 같다** — 설명이 가리키는 개념과 받은 문항이 어긋나지 "
            "않는다."
        ),
    )
    policy_version: str | None = Field(
        default=None, description="이 추천을 만든 선택 알고리즘 식별자(소급 평가용)."
    )

    @model_validator(mode="before")
    @classmethod
    def _derive_action(cls, data: object) -> object:
        """`action` 미지정 시 `reason`에서 채운다 — 호출부가 파생값을 손으로 옮기지 않게.

        `mode="before"`인 것은 필수 필드의 *부재*를 채우려면 검증 전이어야 하기 때문이다.
        여기서 채우지 않으면 `action`이 옵셔널이 되어야 하고, 옵셔널이면 비는 경로가 생긴다.
        """
        if not isinstance(data, dict) or "action" in data:
            return data
        reason = data.get("reason")
        reason_type = getattr(reason, "type", None) or (
            reason.get("type") if isinstance(reason, dict) else None
        )
        if reason_type is None:
            return data  # reason 자체가 없다 — 필수 필드 검증이 그 사실을 말하게 둔다.
        return {**data, "action": action_for(ReasonType(reason_type))}

    @model_validator(mode="after")
    def _action_matches_reason(self) -> "Recommendation":
        """근거와 행위의 불일치를 **생성 시점에** 막는다 — 주입된 불일치는 여기서 죽는다."""
        expected = action_for(self.reason.type)
        if self.action is not expected:
            raise ValueError(
                f"action({self.action.value})이 reason.type({self.reason.type.value})의 "
                f"행위({expected.value})와 다릅니다 — 근거와 행위는 갈라질 수 없습니다."
            )
        return self


#: 학습자 상태의 타입 변수 — **반변(contravariant)**. 구현체는 계약보다 *좁은* 상태 타입을
#: 요구할 수 있고(예: `LearnerState`), 그때도 `RecommendationPolicy[LearnerState]`로서 계약에
#: 적합하다. 이 모듈이 `l2.learner_state`를 구체 import하지 않는 이유는 순환 회피이며(그쪽이
#: 이 상수들을 참조하게 될 자리다), 타입 변수는 그 제약 없이 정확한 계약을 표현한다.
LearnerStateT = TypeVar("LearnerStateT", contravariant=True)


class RecommendationPolicy(Protocol[LearnerStateT]):
    """추천 정책의 호출 계약 — **v1 내부가 규칙이어도 이 시그니처는 바뀌지 않는다**.

    입력이 `learner_state`와 `learning_context` 둘뿐인 것이 핵심이다: 정책이 학습자 상태를
    *받아서* 결정하므로, 상태를 어떻게 추정하는가(BKT/DKT/IRT)는 정책 바깥의 관심사가 된다.

    **제네릭인 이유**(EOS-19 정정): 원래 `learner_state: object`였는데, 그러면 구체 타입을
    요구하는 구현체(`LearnerState`를 받는 v1 정책)가 이 Protocol에 **적합하지 않다**(매개변수는
    반변이라 좁히면 어긋난다). 즉 동결 테스트는 모양을 지키고 있었지만 정작 구현체를 제약하지는
    못하는 상태였다 — 구현체가 생기는 시점에야 드러나는 종류의 공백이다. 타입 변수로 바꿔
    "상태 타입은 구현체가 고른다"를 정확히 표현하고, 그 적합성은 mypy가 CI에서 판정한다.
    """

    async def __call__(
        self, learner_state: LearnerStateT, learning_context: LearningContext
    ) -> Recommendation: ...


# 전사표 채우기 — 정의는 `RecommendationAction` 선언 위에 두되(참조 위치 명시) 값은 두 Enum이
# 모두 존재한 뒤에 넣는다. `ReasonType` 전 5값을 여기서 소진하며, 빠진 값은 `action_for`에서
# KeyError로 드러난다(아래 거버넌스 테스트가 전수성을 동결한다).
_ACTION_BY_REASON.update(
    {
        ReasonType.PREREQUISITE_GAP: RecommendationAction.PRACTICE_PREREQUISITE,
        ReasonType.CURRENT_CONCEPT: RecommendationAction.PRACTICE_CURRENT,
        ReasonType.NEXT_CONCEPT: RecommendationAction.ADVANCE_NEXT,
        ReasonType.UNMEASURED: RecommendationAction.DIAGNOSE,
        ReasonType.NO_CANDIDATE: RecommendationAction.NONE,
        # EOS-24 — 오개념 교정은 새 행위가 아니라 "현재 개념 연습"이다. 행위 어휘를 늘리지 않은
        # 이유: 학생이 할 일(같은 개념 문항을 푼다)은 같고, *왜*가 다를 뿐이다 — 그 차이는
        # `reason.type`/`basis`가 말한다(이 Enum docstring의 "근거가 늘어도 행위는 기존 다섯 중
        # 하나일 수 있다"가 처음 실현된 자리).
        ReasonType.MISCONCEPTION_REMEDIATION: RecommendationAction.PRACTICE_CURRENT,
    }
)


def select_reason_type(mastery: float | None) -> ReasonType:
    """숙달 → 추천 종류 (계획서 §8 규칙의 **정본**·순수).

    - `None`(미측정) → `UNMEASURED`. 0.0으로 접으면 측정된 적 없는 학생이 전부
      "선수개념이 막혔다"로 분류된다 — 콜드스타트를 약점으로 오진하는 형태다.
    - `< 0.4` → `PREREQUISITE_GAP`
    - `0.4 이상 0.7 이하` → `CURRENT_CONCEPT`
    - `> 0.7` → `NEXT_CONCEPT`

    경계는 닫힌 쪽을 명시한다: 0.4는 current, 0.7도 current다(0.7 *초과*라야 next). 약점
    판정(`WEAK_CONCEPT_MASTERY_CEILING` 이상이면 약점 아님)과 어긋나지 않게 맞춘 것이다.
    """
    if mastery is None:
        return ReasonType.UNMEASURED
    if mastery < PREREQUISITE_MASTERY_CEILING:
        return ReasonType.PREREQUISITE_GAP
    if mastery <= WEAK_CONCEPT_MASTERY_CEILING:
        return ReasonType.CURRENT_CONCEPT
    return ReasonType.NEXT_CONCEPT


def build_reason(
    *,
    concept_id: uuid.UUID | None,
    mastery: float | None,
    confidence: float | None,
) -> RecommendationReason:
    """선택된 문항의 개념·숙달 → 근거(순수).

    세 입력이 각각 없을 때를 **다른 basis로** 가른다 — 전부 "근거 없음"으로 뭉치면 데이터
    공백(개념 미매핑)과 학생 상태(콜드스타트)가 같은 글자로 보인다.
    """
    if concept_id is None:
        return RecommendationReason(
            type=ReasonType.UNMEASURED,
            confidence=0.0,
            basis=ReasonBasis.CONCEPT_UNMAPPED,
        )
    reason_type = select_reason_type(mastery)
    if reason_type is ReasonType.UNMEASURED:
        return RecommendationReason(
            type=ReasonType.UNMEASURED,
            confidence=0.0,
            basis=ReasonBasis.COLD_START,
            concept_id=concept_id,
        )
    return RecommendationReason(
        type=reason_type,
        # 측정이 있는데 confidence가 비는 경우(구판 행)는 0.0 — 있는 척하지 않는다.
        confidence=confidence if confidence is not None else 0.0,
        basis=ReasonBasis.MEASURED_MASTERY,
        concept_id=concept_id,
        mastery=mastery,
    )


def no_candidate_reason() -> RecommendationReason:
    """추천이 없을 때의 근거 — 부재도 이유를 가진다(필수 필드가 비지 않는 이유)."""
    return RecommendationReason(
        type=ReasonType.NO_CANDIDATE,
        confidence=0.0,
        basis=ReasonBasis.NO_CANDIDATE_POOL,
    )


# ────────────────────────────────────────────────────────────────────────────
# EOS-124 — 정책 축(action·target)과 선택 축(problem_id)의 정렬 계약
# ────────────────────────────────────────────────────────────────────────────
#: **관계 행위** — 앵커 개념이 아닌 *다른 개념*을 가리키는 행위(선수로 내려가라·다음으로 넘어가라).
#: 나머지(연습·진단)는 앵커 개념 자신을 다룬다. 정렬 계약은 이 구분 위에 선다: 관계 행위면 목표가
#: 앵커와 달라야 하고, 비관계 행위면 같아야 한다.
RELATIONAL_ACTIONS: Final = frozenset(
    {RecommendationAction.PRACTICE_PREREQUISITE, RecommendationAction.ADVANCE_NEXT}
)


class IntentAlignmentError(ValueError):
    """정책 축과 선택 축이 어긋난 추천 — **만들어지지 않아야 하는** 상태(구성 결함)."""


def check_intent_alignment(
    *,
    problem_id: uuid.UUID | None,
    action: RecommendationAction,
    reason_concept_id: uuid.UUID | None,
    target_concept: uuid.UUID | None,
    delivered_concept: uuid.UUID | None,
) -> None:
    """설명(action·target)이 **전달된 콘텐츠**(problem_id)와 어긋나지 않는지 판정한다(순수).

    EOS-124 실측(main `433ec9ea`): 기본 CAT은 문항을 IRT로 고른 뒤 그 문항의 개념 숙달로 행위를
    붙였다. 그래서 숙달 0.98 개념의 문항에 `advance_next`가 붙었고(전진을 선언하면서 전진하지
    않는다), 선수 숙달 1.0인데도 원래 개념 문항에 `practice_prerequisite`가 붙었다(설명이 낡음).
    이 함수가 막는 것은 그 두 형태의 *일반형*이다.

    규칙 네 개(위반 시 `IntentAlignmentError` — 어느 규칙인지 메시지가 지목한다):
      R1 추천이 없으면(`problem_id=None`) 행위는 `NONE`이고 목표도 없다.
      R2 추천이 있으면 목표 = **전달 문항의 대표 개념**(`delivered_concept`, 미매핑이면 None).
         설명이 가리키는 개념과 학생이 받은 문항이 같은 개념이어야 한다는 것이 이 계약의 핵심이다.
      R3 관계 행위(`RELATIONAL_ACTIONS`)면 앵커·목표가 모두 있고 **서로 다르다** — 같은 개념을
         가리키면서 "선수로 가라"·"다음으로 가라"고 말하는 것은 행위가 비어 있다는 뜻이다.
      R4 비관계 행위(연습·진단)면 목표 = 앵커다(둘 다 None인 미매핑 포함).

    **판정하지 않는 것**: 목표가 앵커의 *실제* 선수·후행인지(그래프 관계)는 이 함수가 보지 않는다
    — DB가 필요하고, 그 관계는 정책이 그래프에서 목표를 *구성*하는 방식으로 보장된다. 이 함수는
    구조(같다·다르다)만 본다. 그래서 "관계가 옳다"는 정책 테스트가, "구조가 옳다"는 이 함수가
    각각 소유한다.
    """
    if problem_id is None:
        if action is not RecommendationAction.NONE or target_concept is not None:
            raise IntentAlignmentError(
                f"R1 위반 — 추천이 없는데 action={action.value}·target={target_concept}이다."
            )
        return
    if target_concept != delivered_concept:
        raise IntentAlignmentError(
            f"R2 위반 — target_concept({target_concept})이 전달 문항 {problem_id}의 대표 개념"
            f"({delivered_concept})과 다르다. 설명이 가리키는 개념과 받은 문항이 어긋난다."
        )
    if action in RELATIONAL_ACTIONS:
        if reason_concept_id is None or target_concept is None:
            raise IntentAlignmentError(
                f"R3 위반 — 관계 행위 {action.value}인데 앵커({reason_concept_id})나 "
                f"목표({target_concept})가 없다."
            )
        if reason_concept_id == target_concept:
            raise IntentAlignmentError(
                f"R3 위반 — 관계 행위 {action.value}가 앵커와 같은 개념({target_concept})을 "
                "가리킨다. 전진·선수 복귀를 선언하면서 제자리에 있다."
            )
        return
    if target_concept != reason_concept_id:
        raise IntentAlignmentError(
            f"R4 위반 — 비관계 행위 {action.value}의 목표({target_concept})가 앵커"
            f"({reason_concept_id})와 다르다."
        )


def demote_to_current_concept(reason: RecommendationReason) -> RecommendationReason:
    """관계 행위를 실을 수 없을 때의 **정직 강등** — 같은 앵커·같은 실측으로 `CURRENT_CONCEPT`.

    바꾸는 것은 `type` 하나뿐이다. 개념·숙달·신뢰도·basis를 그대로 두는 이유: 강등은 *무엇을
    하라는가*를 전달된 콘텐츠에 맞추는 것이지 측정을 고치는 것이 아니다. 숙달 0.12가 0.12로
    실려 나가므로 "학습 구간이라서 연습"으로 위장되지 않는다(`ReasonType.CURRENT_CONCEPT` 참조).

    측정 근거가 없는 근거(미측정·미매핑·후보 없음)는 강등 대상이 아니다 — 그것들은 애초에 관계
    행위를 낳지 않는다. 들어오면 `ValueError`다(조용히 통과시키면 호출부의 분기 결함이 가려진다).
    """
    if reason.basis is not ReasonBasis.MEASURED_MASTERY or reason.concept_id is None:
        raise ValueError(
            f"실측 근거만 강등할 수 있다 — basis={reason.basis.value}·concept={reason.concept_id}."
        )
    return reason.model_copy(update={"type": ReasonType.CURRENT_CONCEPT})


def remediation_reason(
    *,
    concept_id: uuid.UUID,
    mastery: float | None,
    misconception_confidence: float,
) -> RecommendationReason:
    """상태 머신의 오개념 교정 결정(R3)을 집행한 추천의 근거(순수 · EOS-24).

    `confidence`에 싣는 것은 **이번 회차에 확인된 오개념 가설의 신뢰**다 — 이 근거가 주장하는
    것("지금은 오개념 교정 국면이다")을 얼마나 믿을 수 있는가이고, 숙달 추정의 신뢰도가 아니다.
    `mastery`는 그 개념의 실측 숙달을 참고로 싣는다(미측정이면 None — 0.0으로 접지 않는다).
    """
    return RecommendationReason(
        type=ReasonType.MISCONCEPTION_REMEDIATION,
        confidence=misconception_confidence,
        basis=ReasonBasis.LEARNING_STATE,
        concept_id=concept_id,
        mastery=mastery,
    )
