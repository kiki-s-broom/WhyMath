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
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "PREREQUISITE_MASTERY_CEILING",
    "WEAK_CONCEPT_MASTERY_CEILING",
    "LearningContext",
    "Recommendation",
    "RecommendationPolicy",
    "RecommendationReason",
    "ReasonBasis",
    "ReasonType",
    "build_reason",
    "no_candidate_reason",
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
    """**왜 이 문항인가** — 계획서 §8의 추천 종류 + 근거가 없는 두 경우.

    앞의 셋은 숙달 구간에서 나오고, 뒤의 둘은 *구간을 판정할 수 없는* 상태다. 넷째·다섯째를
    셋 중 하나로 접으면 근거 없음이 근거로 위장된다.
    """

    PREREQUISITE_GAP = "prerequisite_gap"
    """숙달이 선수 경계 미만 — 현재 개념을 더 밀기 전에 막힌 선수개념을 푼다."""

    CURRENT_CONCEPT = "current_concept"
    """숙달이 학습 구간 — 같은 개념을 계속 연습한다."""

    NEXT_CONCEPT = "next_concept"
    """숙달이 약점 컷 초과 — 다음 개념으로 넘어갈 수 있다."""

    UNMEASURED = "unmeasured"
    """이 개념의 숙달 측정이 없다(콜드스타트) — 구간을 말할 수 없다."""

    NO_CANDIDATE = "no_candidate"
    """추천할 문항이 없다 — 추천의 부재도 이유를 가진다."""


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


class Recommendation(BaseModel):
    """추천 1건 — 결과와 **근거가 함께** 나간다(계획서 §8의 요지).

    `problem_id`가 None이어도 `reason`은 있다. 그 경우 `type=NO_CANDIDATE`이며, 왜 후보가
    없었는지는 기존 관측 메타(`candidate_zero_reason`)가 따로 말한다 — 둘은 다른 질문에
    답하므로 합치지 않는다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    problem_id: uuid.UUID | None = None
    reason: RecommendationReason
    policy_version: str | None = Field(
        default=None, description="이 추천을 만든 선택 알고리즘 식별자(소급 평가용)."
    )


class RecommendationPolicy(Protocol):
    """추천 정책의 호출 계약 — **v1 내부가 규칙이어도 이 시그니처는 바뀌지 않는다**.

    입력이 `learner_state`와 `learning_context` 둘뿐인 것이 핵심이다: 정책이 학습자 상태를
    *받아서* 결정하므로, 상태를 어떻게 추정하는가(BKT/DKT/IRT)는 정책 바깥의 관심사가 된다.
    `learner_state`를 `object`로 둔 것은 이 모듈이 `l2.learner_state`를 import하면 순환이
    생기기 때문이다(그쪽이 이 상수들을 참조하게 될 자리다) — 구현체가 구체 타입을 좁힌다.
    """

    async def __call__(
        self, learner_state: object, learning_context: LearningContext
    ) -> Recommendation: ...


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
