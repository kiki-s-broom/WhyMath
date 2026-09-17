"""L2 — 채점 Evidence 조립기: 계약(`schema.assessment_evidence`)에 DB 조회를 붙인다 (EOS-12).

계약 자체는 `schema/assessment_evidence.py`가 소유한다(순수 타입·순수 선택 규칙). 이 모듈은
그 계약이 필요로 하는 **조회 재료**만 모은다 — 평가 개념 id(역할별)와 해소된 스킬 id.

**재구현 0**: 조회는 숙달 writer가 이미 쓰는 헬퍼를 *그대로 import*해 재사용한다
(`_assessed_concept_ids`·`_assessed_skill_ids`). 같은 패키지 내부 계약의 private 이름을
빌려 쓰는 것은 이 저장소의 선례를 따른다(`api/me.py`가 `l2.ability_estimation.
_DIFFICULTY_MIDPOINT`를 import하는 형태). 새 SELECT를 쓰면 같은 질문에 두 개의 답이 생긴다.

**모델 B 사본 현황(정직 표기)**: 역할 비대칭 선택 규칙은 지금 세 곳에 있다 —
`schema.assessment_evidence.select_concept_evidence`(정본) ·
`l2.mastery_tracking.record_problem_attempt_mastery`(인라인) ·
`l2.skill_mastery_tracking.record_problem_attempt_skill_mastery`(인라인). 이 모듈은 정본을
쓰고, 셋의 일치는 `tests/backend/l2/test_assessment_evidence.py`의 합치 테스트가 기계로
동결한다. 사본 통합은 호출 계약을 소유한 `EOS-13`(`l2/mastery_tracking.py`)이 가져간다 —
그 파일은 이 태스크의 범위가 아니라 여기서 손대지 않는다.

**쓰기 0**: 이 모듈은 `session.add`·`commit`을 하지 않는다. 증거는 관측이지 상태가 아니므로
(계약 docstring), 조립이 상태를 바꾸면 그 순간 "한 트랜잭션처럼 보이기" 문제가 생긴다
(acceptance ⑤).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

# 재구현 0 — 숙달 writer가 쓰는 조회 헬퍼를 그대로 빌려 쓴다(모듈 docstring 참조).
from whymath_backend.l2.mastery_tracking import _assessed_concept_ids
from whymath_backend.l2.skill_mastery_tracking import _assessed_skill_ids
from whymath_backend.schema.assessment_evidence import (
    AssessmentEvidence,
    EvidenceDirection,
    MisconceptionCandidate,
    MisconceptionScan,
    SkillEvidence,
    build_assessment_evidence,
    select_concept_evidence,
)
from whymath_backend.schema.enums import ASSESSED_ROLES, ConceptRole

__all__ = ["collect_assessment_evidence"]


async def collect_assessment_evidence(
    session: AsyncSession,
    *,
    learner_id: uuid.UUID,
    problem_id: uuid.UUID,
    correct: bool,
    attempt_id: uuid.UUID | None = None,
    observed_at: datetime | None = None,
    possible_misconceptions: Sequence[MisconceptionCandidate] = (),
    misconception_scan: MisconceptionScan = MisconceptionScan.NOT_RUN,
    assessed_roles: Sequence[ConceptRole] = ASSESSED_ROLES,
) -> AssessmentEvidence:
    """채점 1건의 증거를 조립한다(읽기 전용 — `session.add`·commit 0건).

    호출자는 **숙달 전파보다 먼저** 이 함수를 부른다. 그래야 Answer → Evidence → State 순서가
    호출 지점에서 실제로 성립하고, 증거가 "갱신 결과의 사후 요약"으로 전락하지 않는다.

    `concept_mapping_present`는 *문항에 평가 개념이 하나라도 매핑돼 있는가*다 — 정답/오답 선택
    이전의 사실이라 `assessed_roles` 전체로 잰다. 이 축이 없으면 "오답인데 PRIMARY가 없어
    증거 0건"과 "문항-개념 매핑 자체가 0건"이 같은 화면으로 보인다.

    `skill_bridge_present`는 *선택된 개념에서 해소된 스킬이 있는가*가 아니라 **해소를
    시도했는가**다(개념이 하나라도 선택됐으면 True). 개념이 0건이면 스킬 해소는 애초에 돌지
    않으므로 `not_measured`가 정직하다.

    오개념 후보는 이 함수가 만들지 않는다 — 호출자(코치·채점 경로)가 이미 품질 게이트를
    통과시킨 후보만 넘긴다. L2는 L4를 import하지 않으므로(역방향 의존 금지) 구조적으로도
    여기서 진단할 수 없고, 그것이 「LLM·매처 비권위」 불변식과 같은 방향이다.
    """
    primary_ids = await _assessed_concept_ids(session, problem_id, [ConceptRole.PRIMARY])
    tested_ids = await _assessed_concept_ids(session, problem_id, [ConceptRole.TESTED])
    # 매핑 실재 판정은 선택 *이전*의 사실 — assessed_roles 전체 기준(정답/오답과 무관).
    mapped_ids: set[uuid.UUID] = set()
    if ConceptRole.PRIMARY in assessed_roles:
        mapped_ids.update(primary_ids)
    if ConceptRole.TESTED in assessed_roles:
        mapped_ids.update(tested_ids)
    concept_mapping_present = bool(mapped_ids)

    concept_evidence = select_concept_evidence(
        correct=correct, primary_ids=primary_ids, tested_ids=tested_ids
    )
    selected_ids = [ev.concept_id for ev in concept_evidence]
    # `_assessed_skill_ids`는 빈 입력에서 조회 없이 빈 목록을 돌려준다 — 여기서 또 가드하면
    # 같은 판단이 두 곳에 생긴다.
    skill_ids = await _assessed_skill_ids(session, selected_ids)
    direction = EvidenceDirection.SUPPORTING if correct else EvidenceDirection.REFUTING
    skill_evidence = tuple(
        SkillEvidence(
            skill_id=skill_id,
            direction=direction,
            # 출처 없는 스킬 증거 금지 — 해소에 쓰인 개념 집합을 그대로 남긴다.
            resolved_from=tuple(selected_ids),
        )
        for skill_id in skill_ids
    )

    return build_assessment_evidence(
        learner_id=learner_id,
        problem_id=problem_id,
        attempt_id=attempt_id,
        correct=correct,
        observed_at=observed_at or datetime.now(UTC),
        concept_evidence=concept_evidence,
        skill_evidence=skill_evidence,
        possible_misconceptions=possible_misconceptions,
        misconception_scan=misconception_scan,
        concept_mapping_present=concept_mapping_present,
        # 개념이 하나도 선택되지 않았으면 스킬 해소는 돌지 않았다(0건≠측정된 0건).
        skill_bridge_present=bool(selected_ids),
    )
