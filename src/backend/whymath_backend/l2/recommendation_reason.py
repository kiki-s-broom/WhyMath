"""추천 근거 조회기 — 계약(`l2.recommendation_contract`)에 DB 조회를 붙인다 (EOS-14).

계약과 규칙(순수)은 `recommendation_contract`가 소유한다. 이 모듈이 하는 일은 하나다:
**이미 선택된 문항**에 대해 "왜 이것인가"의 재료(대표 개념 · 그 개념의 실측 숙달 · 신뢰도)를
모아 `RecommendationReason`으로 만든다.

**선택에 관여하지 않는다**(acceptance ⑥). 후보 선별·가중·정보량 최대 선택은 기존 좌석이 유일
권위이고, 이 모듈은 그 결정이 끝난 뒤에 호출된다 — 그래서 근거 배선이 추천 결과를 바꿀 수
없다. 바꿀 수 있는 구조였다면 "계약 교체가 추천을 바꾸지 않았다"를 증명할 방법이 없다.

**재구현 0**: 대표 개념 조회는 `l2.mastery_tracking.get_primary_concept_id`(PRIMARY→TESTED
폴백을 이미 소유), 숙달·신뢰도는 같은 모듈의 `_latest_mastery`를 그대로 쓴다. 같은 패키지
내부의 private 이름을 빌려 쓰는 것은 이 저장소의 선례를 따른다(`api/me.py`가
`l2.ability_estimation._DIFFICULTY_MIDPOINT`를 import하는 형태 · `l2.assessment_evidence`가
`_assessed_concept_ids`를 쓰는 형태). 새 SELECT를 쓰면 같은 질문에 답이 둘 생긴다.

**쓰기 0**: `session.add`·`commit`을 하지 않는다. 근거는 관측이다.

비용(정직 표기): 추천이 실제로 나간 경로에서만 조회가 는다 — **2건 또는 3건**이다.
`get_primary_concept_id`가 PRIMARY를 먼저 묻고 비었을 때만 TESTED를 한 번 더 물으므로(그쪽의
폴백 설계), PRIMARY가 잡히면 [대표 개념 1 + 최신 숙달 1] = 2건, PRIMARY가 비면 [PRIMARY 1 +
TESTED 1 + 최신 숙달 1] = 3건이다. 매핑이 아예 없으면 숙달을 물을 대상이 없어 2건에서 멈춘다.
추천이 없으면(`problem_id=None`) 조회 0건이다 — 근거를 댈 대상이 없으므로 묻지 않는다.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

# 재구현 0 — 대표 개념·최신 숙달 조회는 숙달 좌석이 이미 소유한다(모듈 docstring).
from whymath_backend.l2.mastery_tracking import _latest_mastery, get_primary_concept_id
from whymath_backend.l2.recommendation_contract import (
    RecommendationReason,
    build_reason,
    no_candidate_reason,
)

__all__ = ["collect_concept_reason", "collect_recommendation_reason"]


async def collect_recommendation_reason(
    session: AsyncSession,
    *,
    learner_id: uuid.UUID,
    problem_id: uuid.UUID | None,
) -> RecommendationReason:
    """선택된 문항의 추천 근거를 조립한다(읽기 전용 · `session.add`·commit 0건).

    `problem_id`가 None이면 조회 없이 `NO_CANDIDATE` 근거를 낸다 — 후보가 없다는 것이 곧
    이유이고, 없는 문항의 개념을 묻는 조회는 낭비다.

    세 갈래를 **서로 다른 basis로** 가른다(계약 docstring "근거 없음을 근거로 위장하지 않는다"):
      · 문항에 평가 개념이 없다 → `CONCEPT_UNMAPPED`(우리 쪽 데이터 공백)
      · 개념은 있는데 숙달 이력이 없다 → `COLD_START`(학생의 상태)
      · 둘 다 있다 → 구간 판정(`select_reason_type`) + 실측 신뢰도

    `confidence`는 BKT 신뢰도(`sample_size/(sample_size+5)`)를 그대로 옮긴다 — 정답 확률이
    아니라 *이 근거를 얼마나 믿을 수 있는가*이며, 표본이 쌓일수록 커진다.
    """
    if problem_id is None:
        return no_candidate_reason()

    concept_id = await get_primary_concept_id(session, problem_id)
    if concept_id is None:
        return build_reason(concept_id=None, mastery=None, confidence=None)
    return await collect_concept_reason(session, learner_id=learner_id, concept_id=concept_id)


async def collect_concept_reason(
    session: AsyncSession,
    *,
    learner_id: uuid.UUID,
    concept_id: uuid.UUID,
) -> RecommendationReason:
    """**개념 하나**의 근거 — 문항을 거치지 않고 그 개념의 최신 숙달·신뢰도로 판정한다(읽기 전용).

    `collect_recommendation_reason`의 뒷부분을 떼어 낸 것이다(같은 `_latest_mastery`·같은
    `build_reason` — 재구현 0). 따로 부를 자리가 생긴 이유는 EOS-124다: 추천 근거의 *앵커*가
    전달 문항의 개념이 아닐 수 있다. 예컨대 학생이 막힌 개념 W의 선수 K 문항을 받으면, 근거는
    "W가 막혔다"이고 그 숙달은 W의 것이어야 한다 — K 문항의 개념 조회로는 W에 닿지 않는다.
    """
    row = await _latest_mastery(session, learner_id, concept_id)
    mastery = float(row.mastery) if row is not None and row.mastery is not None else None
    confidence = float(row.confidence) if row is not None and row.confidence is not None else None
    return build_reason(concept_id=concept_id, mastery=mastery, confidence=confidence)
