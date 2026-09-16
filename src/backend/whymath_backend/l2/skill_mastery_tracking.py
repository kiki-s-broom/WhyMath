"""L2 — BKT 추정기 ↔ `SkillMasteryHistory` 시계열 영속 결선(스킬 축·Part 2 Phase 2b-2).

`mastery_tracking.py`(개념 축)의 *스킬 축* 짝이다. 순수 커널(`compute_mastery_record`·`bkt`·
`irt`)은 **엔티티-무관**이라 그대로 재사용하고(변경 0), (user, **skill_id**)로 재키잉한 얇은 async
DB 래퍼만 새로 둔다. 채점 attempt가 평가하는 개념을 concept→skill 브리지로 해소해 각 스킬의 BKT
숙달을 append-only 적재한다.

설계 분리(mastery_tracking.py 동형):
  - **순수 계산 재사용** — `compute_mastery_record`·`MasteryRecord`를 `mastery_tracking`에서 import
    한다(중복 0·엔티티-무관). 스킬도 개념과 동일한 다음-측정 수학을 쓴다.
  - **얇은 async 래퍼** — `_latest_skill_mastery`/`_stage_skill_attempt_mastery`/
    `record_problem_attempt_skill_mastery`는 `SkillMasteryHistory`를 skill_id(str)로 조회·적재.

런타임 skill 해소(핵심): 문제가 평가하는 개념(UUID)을 `_assessed_concept_ids`(mastery_tracking
재사용)로 얻고, `Concept.behavior_skills`(런타임 concept→skill 브리지·Phase 2b-2) ∩ estimable
`skill_node`로 스킬을 해소한다. **구 437 `concept_node`를 읽지 않는다** — S0-4b 거버넌스
(`test_legacy_snapshot_governance.py`)가 ConceptNode 런타임 read를 금지하므로, 문제 태깅 축인
`concept`(UUID)에 직접 실린 `Concept.behavior_skills`를 조인한다(concept mastery와 같은 축).

정밀도: `skill_mastery_history.mastery`는 `Numeric(3,2)`. prior를 다시 읽어 갱신하므로 순수 커널이
저장 정밀도(2자리)로 반올림해 hermetic↔실 PG 동작을 일치시킨다(mastery_tracking 동형).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.assessment import SkillMasteryHistory
from whymath_backend.db.models.concept import Concept
from whymath_backend.db.models.skill_node import SkillNode
from whymath_backend.l2.bkt import BktModel

# 순수 커널·개념 해소는 개념 축 모듈에서 재사용(엔티티-무관·중복 0). `_assessed_concept_ids`는
# `problem_concept` 조회라 스킬 축과 무관하게 동일한 "문제가 평가하는 개념" 집합을 준다.
from whymath_backend.l2.mastery_tracking import (
    MasteryRecord,
    _assessed_concept_ids,
    compute_mastery_record,
)
from whymath_backend.schema.enums import ASSESSED_ROLES, ConceptRole

__all__ = [
    "MasteryRecord",
    "compute_mastery_record",
    "get_all_current_skill_mastery",
    "get_current_skill_mastery",
    "record_problem_attempt_skill_mastery",
]


async def _latest_skill_mastery(
    session: AsyncSession, user_id: uuid.UUID, skill_id: str
) -> SkillMasteryHistory | None:
    """(user, skill)의 가장 최근 측정 1건 — 없으면 None(첫 관측). `_latest_mastery` 스킬판."""
    stmt = (
        select(SkillMasteryHistory)
        .where(
            SkillMasteryHistory.user_id == user_id,
            SkillMasteryHistory.skill_id == skill_id,
        )
        .order_by(SkillMasteryHistory.measured_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def get_current_skill_mastery(
    session: AsyncSession, user_id: uuid.UUID, skill_id: str
) -> float | None:
    """(user, skill)의 현재 숙달도 — 최신 측정 1건의 mastery 값(읽기 전용).

    측정 이력이 없거나 mastery가 NULL이면 None(미학습 폴백). `get_current_mastery` 스킬판.
    """
    row = await _latest_skill_mastery(session, user_id, skill_id)
    return float(row.mastery) if row is not None and row.mastery is not None else None


async def get_all_current_skill_mastery(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, float]:
    """한 학생의 **스킬별 최신** 숙달 전건 — `{skill_id: mastery}`(읽기 전용·측정된 것만).

    `get_current_skill_mastery`가 (user, skill) **1건**을 보는 것의 벌크 판이다. 조립기
    (`l2/learner_state.py`)가 스킬 축을 담으려면 스킬 수만큼 왕복하거나(N+1) 자기 안에서
    "최신 1건" 규칙을 다시 써야 하는데, 후자는 **같은 규칙의 두 번째 진실 원천**이 된다
    (붕괴 연쇄 "유지보수 지옥"). 그래서 규칙의 소유 모듈인 여기에 벌크 좌석을 둔다.

    "최신"의 정의는 `_latest_skill_mastery`와 **같아야 한다** — 그쪽이 `measured_at DESC`
    LIMIT 1이므로 여기도 `DISTINCT ON (skill_id) ORDER BY skill_id, measured_at DESC`다
    (개념 축 `l2/concept_diagnosis.py:96`·`l2/review_queue.py:156`과 동일 관용어). 두 함수가
    같은 (user, skill)에 대해 다른 행을 고르면 그 자체가 결함이므로
    `test_skill_mastery_tracking.py`가 일치를 계약으로 동결한다.

    `mastery`가 NULL인 행은 **키 자체를 만들지 않는다**(`get_current_skill_mastery`가 그런
    행에 None을 돌려주는 것과 같은 의미 — "측정 없음"이지 "숙달 0"이 아니다). 측정 이력이
    전혀 없으면 빈 dict.
    """
    stmt = (
        select(SkillMasteryHistory.skill_id, SkillMasteryHistory.mastery)
        .where(SkillMasteryHistory.user_id == user_id)
        .distinct(SkillMasteryHistory.skill_id)
        .order_by(
            SkillMasteryHistory.skill_id,
            SkillMasteryHistory.measured_at.desc(),
        )
    )
    result = await session.execute(stmt)
    return {skill_id: float(mastery) for skill_id, mastery in result.all() if mastery is not None}


async def _assessed_skill_ids(session: AsyncSession, concept_ids: Sequence[uuid.UUID]) -> list[str]:
    """평가 개념 UUID 목록 → mastery-estimable skill_id 목록(런타임 concept→skill 해소).

    `Concept.behavior_skills`(런타임 concept→skill 참조 배열·Phase 2b-2) 멤버십(`= ANY`)으로
    `skill_node`를 조인하되 `mastery_estimable=True` 스킬만 남긴다(추정 가치 게이트). concept
    UUID 축에 직접 실린 브리지라 **구 437 `concept_node`(ConceptNode)를 읽지 않는다**(S0-4b 거버넌스
    준수·concept mastery와 동일 sanctioned 축). 빈 입력·매핑 없으면 빈 목록.
    """
    if not concept_ids:
        return []
    stmt = (
        select(SkillNode.skill_id)
        .select_from(Concept)
        .join(SkillNode, SkillNode.skill_id == sa.any_(Concept.behavior_skills))
        .where(
            Concept.concept_id.in_(list(concept_ids)),
            SkillNode.mastery_estimable.is_(True),
        )
        .distinct()
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _stage_skill_attempt_mastery(
    session: AsyncSession,
    user_id: uuid.UUID,
    skill_id: str,
    correct: bool,
    *,
    model: BktModel,
    measured_at: datetime,
) -> SkillMasteryHistory:
    """풀이 관측 1건을 (user, skill) 학습 곡선에 반영해 새 측정 행을 *세션에 add*한다(커밋 0).

    `_stage_attempt_mastery`(개념) 스킬판 — 직전 측정을 prior로 읽어 순수 커널로 갱신 후 새
    `skill_mastery_history` 행을 add만 한다. **commit은 호출자 책임**(다스킬 원자 갱신 공유).
    """
    prior_row = await _latest_skill_mastery(session, user_id, skill_id)
    prior_mastery = (
        float(prior_row.mastery)
        if prior_row is not None and prior_row.mastery is not None
        else None
    )
    prior_sample = prior_row.sample_size if prior_row is not None else None
    # 직전 측정 이후 경과일(망각 감쇠 입력·mastery_tracking 동형). 직전 없으면 0.
    elapsed_days = (
        (measured_at - prior_row.measured_at).total_seconds() / 86400.0
        if prior_row is not None
        else 0.0
    )
    rec = compute_mastery_record(prior_mastery, prior_sample, correct, model, elapsed_days)
    row = SkillMasteryHistory(
        user_id=user_id,
        skill_id=skill_id,
        measured_at=measured_at,
        mastery=rec.mastery,
        confidence=rec.confidence,
        sample_size=rec.sample_size,
    )
    session.add(row)
    return row


async def record_problem_attempt_skill_mastery(
    session: AsyncSession,
    user_id: uuid.UUID,
    problem_id: uuid.UUID,
    correct: bool,
    *,
    model: BktModel | None = None,
    measured_at: datetime | None = None,
    assessed_roles: Sequence[ConceptRole] = ASSESSED_ROLES,
) -> list[SkillMasteryHistory]:
    """채점된 풀이(정/오답)를 문제가 평가하는 개념의 *스킬* 숙달 갱신으로 전파.

    `record_problem_attempt_mastery`(개념)와 **동일한 모델 B(역할 비대칭 부분 크레딧)** 를 스킬 축에
    적용한다:
      - **정답** → `assessed_roles`(기본 PRIMARY·TESTED) 전체 개념의 스킬을 지지(합동 증거).
      - **오답** → 책임귀속 가능한 **PRIMARY 개념**의 스킬만 감점(PRIMARY 미매핑이면 TESTED 폴백).
        TESTED는 갱신하지 않는다 — 책임귀속 모호한 개념의 스킬에 거짓 약점 신호를 주지 않는다
        (CLAUDE.md "오답=약점 단정 금지"·mastery_tracking 논리 연장).

    선택된 개념을 `_assessed_skill_ids`로 mastery-estimable 스킬로 해소한 뒤 스킬마다
    `_stage_skill_attempt_mastery`로 측정 1건씩 add하고 **루프 후 한 번만 commit**한다(단일 트랜잭션
    원자성). 매핑/해소가 없으면 빈 리스트(커밋 0). 모든 스킬은 *같은 measured_at*(생략 시 현재)을
    공유한다. 순수 커널·bkt/irt는 엔티티-무관 재사용이라 mastery 수학은 회귀 0.
    """
    model = model or BktModel()
    timestamp = measured_at or datetime.now(UTC)
    if correct:
        # 정답: 평가 개념 전체(합동 증거)의 스킬.
        concept_ids = await _assessed_concept_ids(session, problem_id, assessed_roles)
    else:
        # 오답: PRIMARY 개념(없으면 TESTED 폴백)의 스킬만(거짓 약점 0).
        concept_ids = await _assessed_concept_ids(session, problem_id, [ConceptRole.PRIMARY])
        if not concept_ids:
            concept_ids = await _assessed_concept_ids(session, problem_id, [ConceptRole.TESTED])
    skill_ids = await _assessed_skill_ids(session, concept_ids)
    records: list[SkillMasteryHistory] = []
    for skill_id in skill_ids:
        record = await _stage_skill_attempt_mastery(
            session, user_id, skill_id, correct, model=model, measured_at=timestamp
        )
        records.append(record)
    if records:  # 빈 스킬셋은 커밋 0(개념 축 동작 보존)
        await session.commit()
    return records
