"""L2 — BKT 추정기 ↔ `ConceptMasteryHistory` 시계열 영속 결선.

`l2/bkt`는 *순수 추정*(prior + 관측 → 새 P(L))만 한다. 본 모듈은 그 추정을 영속 학습 곡선에
잇는다: 풀이 관측이 들어오면 ① (user, concept)의 *직전* 숙달 측정을 읽어 prior로 삼고
② BKT로 갱신해 ③ 새 `concept_mastery_history` 행을 append-only로 적재한다(특성 #16 학습 곡선).

설계 분리(코드베이스 패턴):
  - **호출 계약**(EOS-13) — 다음-측정 계산은 `l2/mastery_contract.update_mastery(learner_state,
    assessment_evidence)`가 소유한다. 이 모듈은 *상태를 읽어 계약에 넘기고 산출을 적재*할 뿐
    숫자를 만들지 않는다 — 추정기(BKT·후속 DKT)는 레지스트리에서 해소되므로 **교체해도 이
    파일은 바뀌지 않는다**.
  - **`compute_mastery_record`** — *순수*(DB 무관) 다음-측정 커널. EOS-13에서
    `l2/mastery_contract.py`로 옮겨졌고 여기서는 **하위호환 재노출**만 한다(기존 import 경로
    보존). 새 코드는 계약 진입점을 쓴다.
  - **`record_attempt_mastery`** — 얇은 async DB 래퍼(직전 측정 SELECT → 계약 호출 → INSERT).
    실 PG 통합테스트가 SELECT 정렬·INSERT를 검증.

정밀도: `concept_mastery_history.mastery`는 `Numeric(3,2)`(소수 2자리)다. prior를 다시 읽어
갱신하므로 *저장 정밀도에 맞춰* 2자리로 반올림해 hermetic↔실 PG 동작을 일치시킨다(컬럼 폭
확대·고정밀 상태 분리는 후속). confidence는 v1 휴리스틱(표본 크기 기반·아래 상수).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.assessment import ConceptMasteryHistory
from whymath_backend.db.models.concept import ProblemConcept
from whymath_backend.l2.bkt import BktModel

# EOS-13: 다음-측정 계산은 호출 계약이 소유한다. `MasteryRecord`·`compute_mastery_record`는
# 하위호환 재노출(`__all__` 등재 — 기존 import 경로를 깨지 않는다).
from whymath_backend.l2.mastery_contract import (
    AttemptOutcomeEvidence,
    BktMasteryEstimator,
    MasteryRecord,
    compute_mastery_record,
    resolve_estimator,
    state_from_history,
    update_mastery,
)
from whymath_backend.schema.enums import ASSESSED_ROLES, ConceptRole
from whymath_backend.schema.mastery_contract import MasteryAxis, MasteryEstimator

logger = logging.getLogger("whymath.l2.mastery_tracking")

# slice 3: 채점된 풀이 정/오답이 *직접 평가*하는 개념 역할은 `ASSESSED_ROLES`(PRIMARY·TESTED·
# `schema.enums` 단일 출처). SUPPORTING(계산 부수)·IMPLICIT(무의식 사용)는 정/오답이 그 개념
# 숙달의 직접 증거가 아니라 제외(오답이 보조 개념 탓일 수도·정답이 보조 개념 숙달을 확증 못함).


async def _latest_mastery(
    session: AsyncSession, user_id: uuid.UUID, concept_id: uuid.UUID
) -> ConceptMasteryHistory | None:
    """(user, concept)의 가장 최근 측정 1건 — 없으면 None(첫 관측)."""
    stmt = (
        select(ConceptMasteryHistory)
        .where(
            ConceptMasteryHistory.user_id == user_id,
            ConceptMasteryHistory.concept_id == concept_id,
        )
        .order_by(ConceptMasteryHistory.measured_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def _applied_for_attempt(
    session: AsyncSession,
    user_id: uuid.UUID,
    concept_ids: Sequence[uuid.UUID],
    attempt_id: uuid.UUID,
) -> dict[uuid.UUID, ConceptMasteryHistory]:
    """이 시도가 **이미 반영된** (user, concept) 측정 행 — 개념 id로 색인해 돌려준다.

    멱등의 *읽기측*이다. 쓰기측 권위는 DB 부분 유니크 인덱스
    (`uq_concept_mastery_history_attempt`)이며 이 조회는 그것을 대신하지 않는다 — 조회와 INSERT
    사이에 다른 트랜잭션이 끼어드는 check-then-act 경합을 조회만으로는 막을 수 없기 때문이다
    (막는 것은 인덱스고, 이 함수는 *정상 재시도*가 예외를 거치지 않고 조용히 끝나게 한다).

    `attempt_id`가 없는 측정은 애초에 이 함수를 거치지 않는다(호출부가 분기) — NULL끼리는
    같은 시도인지 알 방법이 없으므로 "이미 반영됨"을 판정할 수 없다.
    """
    if not concept_ids:
        return {}
    stmt = select(ConceptMasteryHistory).where(
        ConceptMasteryHistory.user_id == user_id,
        ConceptMasteryHistory.concept_id.in_(list(concept_ids)),
        ConceptMasteryHistory.attempt_id == attempt_id,
    )
    result = await session.execute(stmt)
    return {row.concept_id: row for row in result.scalars().all()}


async def get_current_mastery(
    session: AsyncSession, user_id: uuid.UUID, concept_id: uuid.UUID
) -> float | None:
    """(user, concept)의 현재 숙달도 — 최신 측정 1건의 mastery 값(읽기 전용).

    L4 coach가 서버에서 학생의 특정 개념 숙달도를 *클라이언트 전송값 대신* 조회할 때 쓴다
    (slice 70·L2↔L4 서버 진실원천). 측정 이력이 없거나 mastery가 NULL이면 None(미학습 폴백).
    """
    row = await _latest_mastery(session, user_id, concept_id)
    return float(row.mastery) if row is not None and row.mastery is not None else None


def _resolve_estimator(model: BktModel | None) -> MasteryEstimator:
    """이 적재 경로가 쓸 추정기 — **교체 지점은 여기 하나다**(EOS-13 ②).

    `model`을 명시하면 그 파라미터의 BKT를 쓴다(하위호환·기존 호출부와 테스트의 커스텀 모델).
    생략하면 레지스트리의 현재 기본 추정기를 해소한다 — 그래서 `use_estimator("dkt-v1")`처럼
    기본을 바꾸면 **이 파일도, 그 위의 API도 한 글자도 고치지 않고** 다른 추정기가 돈다.
    """
    return BktMasteryEstimator(model) if model is not None else resolve_estimator()


async def _stage_attempt_mastery(
    session: AsyncSession,
    user_id: uuid.UUID,
    concept_id: uuid.UUID,
    correct: bool,
    *,
    estimator: MasteryEstimator,
    measured_at: datetime,
    attempt_id: uuid.UUID | None = None,
) -> ConceptMasteryHistory:
    """풀이 관측 1건을 (user, concept) 학습 곡선에 반영해 새 측정 행을 *세션에 add*한다(커밋 0).

    직전 측정을 prior로 읽어 **호출 계약**(`update_mastery(learner_state, assessment_evidence)`)에
    넘기고, 산출을 새 `concept_mastery_history` 행으로 만들어 `session.add`만 한다 —
    **commit은 호출자 책임**. 단일 개념(`record_attempt_mastery`)·다개념 원자 갱신
    (`record_problem_attempt_mastery`)이 이 staging을 공유하되 커밋 경계는 각자 정한다.

    EOS-13: 경과일(망각 감쇠 입력) 계산이 여기서 사라졌다 — `LearnerMasteryState`가 직전 측정
    시각을 들고 있고 계약이 계산한다(개념 축·스킬 축이 각자 복제하던 식을 한 자리로 모았다).

    EOS-108: `attempt_id`(멱등 키)를 증거에 실어 계약에 넘기고, 산출이 들고 나온 그 값을 새 행에
    적재한다. **이 함수 자체는 중복을 판정하지 않는다** — 판정은 호출부(`record_*`)의 사전 조회와
    DB 부분 유니크 인덱스가 한다. staging이 판정까지 하면 "add만 한다"는 이 함수의 유일한 계약이
    무너지고, 커밋 경계를 소유하지 않은 자리에서 경합을 다루게 된다.
    """
    prior_row = await _latest_mastery(session, user_id, concept_id)
    prior_mastery = (
        float(prior_row.mastery)
        if prior_row is not None and prior_row.mastery is not None
        else None
    )
    state = state_from_history(
        MasteryAxis.CONCEPT,
        str(concept_id),
        mastery=prior_mastery,
        sample_size=prior_row.sample_size if prior_row is not None else None,
        measured_at=prior_row.measured_at if prior_row is not None else None,
    )
    update = update_mastery(
        state,
        AttemptOutcomeEvidence(
            correct=correct, observed_at=measured_at, attempt_id=attempt_id
        ),
        estimator=estimator,
    )
    row = ConceptMasteryHistory(
        user_id=user_id,
        concept_id=concept_id,
        measured_at=measured_at,
        mastery=update.mastery,
        confidence=update.confidence,
        sample_size=update.sample_size,
        # EOS-108 멱등 키 — 계약 산출이 들고 온 것을 그대로 적재한다(여기서 새로 만들지 않는다).
        attempt_id=update.attempt_id,
    )
    session.add(row)
    return row


async def record_attempt_mastery(
    session: AsyncSession,
    user_id: uuid.UUID,
    concept_id: uuid.UUID,
    correct: bool,
    *,
    model: BktModel | None = None,
    measured_at: datetime | None = None,
    attempt_id: uuid.UUID | None = None,
) -> ConceptMasteryHistory:
    """풀이 관측 1건을 (user, concept) 학습 곡선에 반영 — 새 측정 행 적재·반환.

    `_stage_attempt_mastery`로 새 행을 세션에 add한 뒤 **단일 개념 단위로 commit**한다(공개 계약·
    하위호환). `measured_at` 생략 시 현재. 다개념 원자 갱신은 `record_problem_attempt_mastery`가
    staging을 직접 묶어 한 번만 커밋한다.

    EOS-108 멱등: `attempt_id`를 주면 **그 시도는 정확히 한 번만 반영된다**. 이미 반영됐으면
    새 행을 만들지 않고 기존 행을 그대로 돌려준다(호출자가 보기에 결과는 같고, 학습 곡선에는
    점이 하나만 찍힌다). `attempt_id`가 없으면 멱등 보호가 **없다** — 그것은 결함이 아니라
    "이 관측에는 신원이 없다"는 사실이며, 신원 없는 관측을 조용히 중복 제거하면 서로 다른 두
    관측이 하나로 합쳐진다.
    """
    estimator = _resolve_estimator(model)
    now = measured_at or datetime.now(UTC)
    if attempt_id is not None:
        applied = await _applied_for_attempt(session, user_id, [concept_id], attempt_id)
        if concept_id in applied:
            logger.info(
                "MasteryUpdateAlreadyApplied: 시도 %s의 개념 축 숙달이 이미 반영돼 있어 "
                "재적재를 건너뜁니다(concept=%s).",
                attempt_id,
                concept_id,
            )
            return applied[concept_id]
    row = await _stage_attempt_mastery(
        session,
        user_id,
        concept_id,
        correct,
        estimator=estimator,
        measured_at=now,
        attempt_id=attempt_id,
    )
    try:
        await session.commit()
    except IntegrityError:
        # 경합 — 사전 조회 이후 다른 트랜잭션이 같은 시도를 반영했다. DB 인덱스가 정확히 한 건만
        # 살렸고 진 쪽이 여기다. 예외 타입명을 로그에 남기고(침묵 실패 금지) 승자의 행을 돌려준다.
        await session.rollback()
        logger.info(
            "IntegrityError: 시도 %s의 개념 축 숙달이 동시 갱신 경합에서 이미 반영됐습니다"
            "(concept=%s) — DB 유니크 인덱스가 이중 반영을 막았습니다.",
            attempt_id,
            concept_id,
        )
        if attempt_id is None:
            raise
        applied = await _applied_for_attempt(session, user_id, [concept_id], attempt_id)
        winner = applied.get(concept_id)
        if winner is None:
            # 멱등 위반이 아닌 다른 무결성 오류였다 — 삼키면 원인을 잃는다.
            raise
        return winner
    return row


async def _assessed_concept_ids(
    session: AsyncSession,
    problem_id: uuid.UUID,
    assessed_roles: Sequence[ConceptRole],
) -> list[uuid.UUID]:
    """문제가 *평가*하는 distinct 개념 id — `problem_concept` 중 role∈assessed_roles."""
    stmt = (
        select(ProblemConcept.concept_id)
        .where(
            ProblemConcept.problem_id == problem_id,
            ProblemConcept.role.in_(list(assessed_roles)),
        )
        .distinct()
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_primary_concept_id(session: AsyncSession, problem_id: uuid.UUID) -> uuid.UUID | None:
    """문항의 *대표* 개념 1개 — coach가 "어느 개념 숙달도를 볼지" 정할 때(slice 70).

    PRIMARY(주된 개념) 우선·없으면 TESTED 폴백·둘 다 없으면 None(문항-개념 미매핑). PRIMARY가
    복수면 첫째(문항당 PRIMARY 1개 보장이 설계 전제·후속에서 가중). 기존 `_assessed_concept_ids`
    재사용(role 필터·distinct).
    """
    primary = await _assessed_concept_ids(session, problem_id, [ConceptRole.PRIMARY])
    if primary:
        return primary[0]
    tested = await _assessed_concept_ids(session, problem_id, [ConceptRole.TESTED])
    return tested[0] if tested else None


async def record_problem_attempt_mastery(
    session: AsyncSession,
    user_id: uuid.UUID,
    problem_id: uuid.UUID,
    correct: bool,
    *,
    model: BktModel | None = None,
    measured_at: datetime | None = None,
    assessed_roles: Sequence[ConceptRole] = ASSESSED_ROLES,
    attempt_id: uuid.UUID | None = None,
) -> list[ConceptMasteryHistory]:
    """채점된 풀이(정/오답)를 문제가 평가하는 개념의 숙달 갱신으로 전파 — 풀이 채점 파이프라인의
    자동 결선 진입점. **역할 가중 부분 크레딧(모델 B·무파라미터 비대칭)**.

    대상 개념을 정/오답으로 비대칭 선택한다(pedagogy-designer 권고·사용자 확정):
      - **정답** → `assessed_roles`(기본 PRIMARY·TESTED) *전체*를 지지(합동 증거 — 모든 평가 개념이
        함께 작동했다는 증거라 귀속 모호성이 작다).
      - **오답** → 책임귀속이 정의상 분명한 **PRIMARY에만** 감점(문항당 PRIMARY 1 보장 전제).
        TESTED는 *갱신하지 않는다*(=관측 없음) — 책임귀속 모호한 개념에 거짓 약점 신호를 주지
        않는다(기존 SUPPORTING·IMPLICIT 제외 논리의 연장·CLAUDE.md "오답=약점 단정 금지").
        PRIMARY 미매핑인 퇴화 문항은 TESTED로 폴백(`get_primary_concept_id`의 PRIMARY→TESTED 선례).

    선택된 개념마다 `_stage_attempt_mastery`로 측정 1건씩 add하고 **루프 후 한 번만 commit**한다
    (#279 단일 트랜잭션 원자성 — 전부 성공 또는 전부 롤백). 매핑이 없으면 빈 리스트(커밋 0). 모든
    개념은 *같은 `measured_at`*(생략 시 현재)을 공유한다.

    데이터·EM 적합이 갖춰지면 역할별 p_slip 등 per-skill 파라미터(모델 C)로 승격해 TESTED 오답도
    *약화된 신호*로 반영하는 경로를 남긴다(현재는 무파라미터 보수 기본값).
    """
    estimator = _resolve_estimator(model)
    timestamp = measured_at or datetime.now(UTC)
    if correct:
        # 정답: 평가 개념 전체 지지(합동 증거).
        concept_ids = await _assessed_concept_ids(session, problem_id, assessed_roles)
    else:
        # 오답: PRIMARY에만 책임귀속(거짓 약점 0). 없으면 TESTED 폴백(get_primary_concept_id 선례).
        concept_ids = await _assessed_concept_ids(session, problem_id, [ConceptRole.PRIMARY])
        if not concept_ids:
            concept_ids = await _assessed_concept_ids(session, problem_id, [ConceptRole.TESTED])
    # EOS-108 멱등 ①(읽기측·정상 재시도) — 이미 반영된 개념은 다시 계산하지도 적재하지도 않는다.
    already = (
        await _applied_for_attempt(session, user_id, concept_ids, attempt_id)
        if attempt_id is not None
        else {}
    )
    if already:
        logger.info(
            "MasteryUpdateAlreadyApplied: 시도 %s의 개념 축 숙달 %d건이 이미 반영돼 있어 "
            "재적재를 건너뜁니다.",
            attempt_id,
            len(already),
        )
    records: list[ConceptMasteryHistory] = []
    staged = 0
    for concept_id in concept_ids:
        if concept_id in already:
            records.append(already[concept_id])
            continue
        record = await _stage_attempt_mastery(
            session,
            user_id,
            concept_id,
            correct,
            estimator=estimator,
            measured_at=timestamp,
            attempt_id=attempt_id,
        )
        records.append(record)
        staged += 1
    if staged:  # 빈 개념셋·전건 이미반영은 커밋 0(현 동작 보존)
        try:
            await session.commit()
        except IntegrityError:
            # EOS-108 멱등 ②(쓰기측·경합) — 사전 조회 이후 다른 트랜잭션이 같은 시도를 반영했다.
            # 부분 유니크 인덱스가 정확히 한 건만 살렸다. 승자의 행을 다시 읽어 돌려준다.
            await session.rollback()
            logger.info(
                "IntegrityError: 시도 %s의 개념 축 숙달이 동시 갱신 경합에서 이미 반영됐습니다 "
                "— DB 유니크 인덱스가 이중 반영을 막았습니다.",
                attempt_id,
            )
            if attempt_id is None:
                raise
            winners = await _applied_for_attempt(session, user_id, concept_ids, attempt_id)
            if not winners:
                # 멱등 위반이 아닌 다른 무결성 오류였다 — 삼키면 원인을 잃는다.
                raise
            return [winners[cid] for cid in concept_ids if cid in winners]
    return records


__all__ = [
    "AttemptOutcomeEvidence",
    "MasteryRecord",
    "compute_mastery_record",
    "get_current_mastery",
    "get_primary_concept_id",
    "record_attempt_mastery",
    "record_problem_attempt_mastery",
]
