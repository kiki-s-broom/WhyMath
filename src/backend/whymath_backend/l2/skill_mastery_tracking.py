"""L2 — BKT 추정기 ↔ `SkillMasteryHistory` 시계열 영속 결선(스킬 축·Part 2 Phase 2b-2).

`mastery_tracking.py`(개념 축)의 *스킬 축* 짝이다. 순수 커널(`compute_mastery_record`·`bkt`·
`irt`)은 **엔티티-무관**이라 그대로 재사용하고(변경 0), (user, **skill_id**)로 재키잉한 얇은 async
DB 래퍼만 새로 둔다. 채점 attempt가 평가하는 개념을 concept→skill 브리지로 해소해 각 스킬의 BKT
숙달을 append-only 적재한다.

설계 분리(mastery_tracking.py 동형):
  - **호출 계약 공유**(EOS-13) — 다음-측정 계산은 개념 축과 **같은 함수**
    `l2/mastery_contract.update_mastery(learner_state, assessment_evidence)`를 쓴다. 축은
    `LearnerMasteryState.axis`(`MasteryAxis.SKILL`)가 들고 있을 뿐 계산을 가르지 않는다 —
    "계약은 하나, 내부 구현(조회·적재 좌석)은 갈라둔다". 통합이 재계산을 낳지 않는 이유는
    계산이 원래 한 벌이었고(`compute_mastery_record` 공유) 그 한 벌을 계약 뒤로 옮겼을 뿐이기
    때문이다.
  - **순수 계산 재사용** — `compute_mastery_record`·`MasteryRecord`는 하위호환 재노출이다
    (EOS-13에서 정의가 `l2/mastery_contract.py`로 이동).
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

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.assessment import SkillMasteryHistory
from whymath_backend.db.models.concept import Concept
from whymath_backend.db.models.skill_node import SkillNode
from whymath_backend.l2.bkt import BktModel

# 순수 커널·개념 해소는 개념 축 모듈에서 재사용(엔티티-무관·중복 0). `_assessed_concept_ids`는
# `problem_concept` 조회라 스킬 축과 무관하게 동일한 "문제가 평가하는 개념" 집합을 준다.
from whymath_backend.l2.mastery_contract import (
    AttemptOutcomeEvidence,
    BktMasteryEstimator,
    MasteryRecord,
    compute_mastery_record,
    resolve_estimator,
    state_from_history,
    update_mastery,
)
from whymath_backend.l2.mastery_tracking import _assessed_concept_ids
from whymath_backend.schema.enums import ASSESSED_ROLES, ConceptRole
from whymath_backend.schema.mastery_contract import MasteryAxis, MasteryEstimator

logger = logging.getLogger("whymath.l2.skill_mastery_tracking")

__all__ = [
    "AttemptOutcomeEvidence",
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


async def _applied_skills_for_attempt(
    session: AsyncSession,
    user_id: uuid.UUID,
    skill_ids: Sequence[str],
    attempt_id: uuid.UUID,
) -> dict[str, SkillMasteryHistory]:
    """이 시도가 **이미 반영된** (user, skill) 측정 행 — 개념 축 `_applied_for_attempt` 동형.

    쓰기측 권위는 DB 부분 유니크 인덱스(`uq_skill_mastery_history_attempt`)이고 이 조회는
    *정상 재시도*가 예외를 거치지 않게 할 뿐이다(경합은 인덱스가 막는다).
    """
    if not skill_ids:
        return {}
    stmt = select(SkillMasteryHistory).where(
        SkillMasteryHistory.user_id == user_id,
        SkillMasteryHistory.skill_id.in_(list(skill_ids)),
        SkillMasteryHistory.attempt_id == attempt_id,
    )
    result = await session.execute(stmt)
    return {row.skill_id: row for row in result.scalars().all()}


def _resolve_estimator(model: BktModel | None) -> MasteryEstimator:
    """이 적재 경로가 쓸 추정기 — 개념 축 `mastery_tracking._resolve_estimator`와 동형.

    두 축이 **같은 레지스트리**를 본다(별도 기본값을 두지 않는다) — 추정기를 갈아 끼우면 개념·
    스킬이 함께 바뀐다. 한 축만 바꾸는 것은 정책 결정이라 계약이 아니라 호출부가 명시해야 한다.
    """
    return BktMasteryEstimator(model) if model is not None else resolve_estimator()


async def _stage_skill_attempt_mastery(
    session: AsyncSession,
    user_id: uuid.UUID,
    skill_id: str,
    correct: bool,
    *,
    estimator: MasteryEstimator,
    measured_at: datetime,
    attempt_id: uuid.UUID | None = None,
) -> SkillMasteryHistory:
    """풀이 관측 1건을 (user, skill) 학습 곡선에 반영해 새 측정 행을 *세션에 add*한다(커밋 0).

    `_stage_attempt_mastery`(개념) 스킬판 — 직전 측정을 prior로 읽어 **같은 호출 계약**
    (`update_mastery`)에 넘기고 산출을 새 `skill_mastery_history` 행으로 add만 한다.
    **commit은 호출자 책임**(다스킬 원자 갱신 공유). 경과일 계산은 계약이 소유한다(EOS-13 —
    두 축이 복제하던 식 제거).
    """
    prior_row = await _latest_skill_mastery(session, user_id, skill_id)
    prior_mastery = (
        float(prior_row.mastery)
        if prior_row is not None and prior_row.mastery is not None
        else None
    )
    state = state_from_history(
        MasteryAxis.SKILL,
        skill_id,
        mastery=prior_mastery,
        sample_size=prior_row.sample_size if prior_row is not None else None,
        measured_at=prior_row.measured_at if prior_row is not None else None,
    )
    update = update_mastery(
        state,
        AttemptOutcomeEvidence(correct=correct, observed_at=measured_at, attempt_id=attempt_id),
        estimator=estimator,
    )
    row = SkillMasteryHistory(
        user_id=user_id,
        skill_id=skill_id,
        measured_at=measured_at,
        mastery=update.mastery,
        confidence=update.confidence,
        sample_size=update.sample_size,
        # EOS-108 멱등 키 — 개념 축 동형(계약 산출이 들고 온 것을 그대로 적재).
        attempt_id=update.attempt_id,
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
    attempt_id: uuid.UUID | None = None,
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
    estimator = _resolve_estimator(model)
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
    # EOS-108 멱등 ①(읽기측·정상 재시도) — 개념 축 `record_problem_attempt_mastery` 동형.
    already = (
        await _applied_skills_for_attempt(session, user_id, skill_ids, attempt_id)
        if attempt_id is not None
        else {}
    )
    if already:
        logger.info(
            "MasteryUpdateAlreadyApplied: 시도 %s의 스킬 축 숙달 %d건이 이미 반영돼 있어 "
            "재적재를 건너뜁니다.",
            attempt_id,
            len(already),
        )
    records: list[SkillMasteryHistory] = []
    staged = 0
    for skill_id in skill_ids:
        if skill_id in already:
            records.append(already[skill_id])
            continue
        record = await _stage_skill_attempt_mastery(
            session,
            user_id,
            skill_id,
            correct,
            estimator=estimator,
            measured_at=timestamp,
            attempt_id=attempt_id,
        )
        records.append(record)
        staged += 1
    if staged:  # 빈 스킬셋·전건 이미반영은 커밋 0(개념 축 동작 보존)
        try:
            await session.commit()
        except IntegrityError:
            # EOS-108 멱등 ②(쓰기측·경합) — 부분 유니크 인덱스가 정확히 한 건만 살렸다.
            await session.rollback()
            logger.info(
                "IntegrityError: 시도 %s의 스킬 축 숙달이 동시 갱신 경합에서 이미 반영됐습니다 "
                "— DB 유니크 인덱스가 이중 반영을 막았습니다.",
                attempt_id,
            )
            if attempt_id is None:
                raise
            winners = await _applied_skills_for_attempt(session, user_id, skill_ids, attempt_id)
            if not winners:
                raise
            return [winners[sid] for sid in skill_ids if sid in winners]
    return records
