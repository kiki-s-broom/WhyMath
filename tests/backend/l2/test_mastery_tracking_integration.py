"""L2 BKT↔ConceptMasteryHistory 결선 — 실 PG 통합테스트 (기본 SKIP).

`record_attempt_mastery`가 직전 측정을 SELECT(measured_at DESC)해 prior로 쓰고 새 측정 행을
INSERT하는지 검증한다. `concept_mastery_history`는 FK 없는 hypertable 느슨참조라 user_profile
선적재 불요(임의 user_id/concept_id 사용).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.db.models.concept import Concept, ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2 import BktModel
from whymath_backend.l2.mastery_tracking import (
    record_attempt_mastery,
    record_problem_attempt_mastery,
)
from whymath_backend.schema.assessment_evidence import (
    AssessmentEvidence,
    build_assessment_evidence,
)
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.concept import ProblemConcept as ProblemConceptSchema
from whymath_backend.schema.enums import (
    ConceptLevel,
    ConceptRole,
    Curriculum,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema

pytestmark = pytest.mark.integration

_SECRET = "integration-jwt-secret-0123456789abcdef"


def _ev(
    learner_id: uuid.UUID,
    problem_id: uuid.UUID,
    correct: bool,
    observed_at: datetime | None = None,
) -> AssessmentEvidence:
    """실 `AssessmentEvidence` — EOS-18 이후 적재 writer가 받는 타입(어댑터 폐기).

    증거는 순수 관측 객체라 DB 제약을 지지 않는다(영속 0) — 여기서는 적재 경로에 넘길
    최소 재료만 싣는다.
    """
    return build_assessment_evidence(
        learner_id=learner_id,
        problem_id=problem_id,
        correct=correct,
        observed_at=observed_at or datetime.now(UTC),
        concept_evidence=(),
        skill_evidence=(),
        concept_mapping_present=False,
        skill_bridge_present=False,
    )


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_SECRET))


async def _pg_reachable() -> bool:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def _cleanup(user_id: uuid.UUID) -> None:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM concept_mastery_history WHERE user_id = :uid"),
                {"uid": str(user_id)},
            )
    finally:
        await engine.dispose()


def test_record_attempt_mastery_appends_and_reads_prior_on_live_pg() -> None:
    """첫 관측은 P(L0) 갱신·둘째는 직전 측정을 prior로 읽어 갱신(학습 곡선 누적)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    cid = uuid.uuid4()
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = t1 + timedelta(minutes=5)

    async def _run() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            sm = async_sessionmaker(engine, expire_on_commit=False)
            model = BktModel()
            async with sm() as session:
                # 첫 관측(정답): P(L0)=0.3 → 0.69·표본 1
                r1 = await record_attempt_mastery(
                    session, cid, evidence=_ev(uid, uuid.uuid4(), True, t1), model=model
                )
                assert float(r1.mastery) == 0.69
                assert r1.sample_size == 1
                # 둘째 관측(정답): 직전 0.69를 prior로 → 0.92·표본 2
                r2 = await record_attempt_mastery(
                    session, cid, evidence=_ev(uid, uuid.uuid4(), True, t2), model=model
                )
                assert float(r2.mastery) == 0.92
                assert r2.sample_size == 2
            # DB에 2개 행 적재 확인
            async with sm() as session:
                rows = (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM concept_mastery_history "
                            "WHERE user_id = :uid AND concept_id = :cid"
                        ),
                        {"uid": str(uid), "cid": str(cid)},
                    )
                ).scalar()
                assert rows == 2
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup(uid))


async def _cleanup_problem(problem_id: uuid.UUID, concept_ids: list[uuid.UUID]) -> None:
    engine = create_async_engine(_settings().database_url)
    cids = [str(c) for c in concept_ids]
    try:
        async with engine.begin() as conn:
            # 자식(problem_concept) → 부모(problem·concept) 순
            await conn.execute(
                text("DELETE FROM problem_concept WHERE problem_id = :pid"),
                {"pid": str(problem_id)},
            )
            await conn.execute(
                text("DELETE FROM problem WHERE problem_id = :pid"),
                {"pid": str(problem_id)},
            )
            await conn.execute(
                text("DELETE FROM concept WHERE concept_id = ANY(:cids)"),
                {"cids": cids},
            )
    finally:
        await engine.dispose()


def _concept(cid: uuid.UUID, code: str) -> Concept:
    return Concept.from_schema(
        ConceptSchema(
            concept_id=cid,
            code=code,
            name_ko=f"개념{code}",
            level=ConceptLevel.세부개념,
        )
    )


def test_record_problem_attempt_mastery_only_assessed_roles_on_live_pg() -> None:
    """문제↔개념 중 PRIMARY·TESTED만 숙달 갱신·SUPPORTING은 제외(역할 필터)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid = uuid.uuid4()
    c_primary, c_tested, c_supporting = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    suffix = pid.hex[:8]

    async def _setup() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            sm = async_sessionmaker(engine, expire_on_commit=False)
            async with sm() as s:
                s.add(
                    Problem.from_schema(
                        ProblemSchema(
                            problem_id=pid,
                            source_type=SourceType.자체생성,
                            curriculum_version=Curriculum.REVISION_2022,
                            valid_from_year=2022,
                            subject=Subject.공통,
                            unit_codes=[f"U-{suffix}"],
                        )
                    )
                )
                s.add_all(
                    [
                        _concept(c_primary, f"P-{suffix}"),
                        _concept(c_tested, f"T-{suffix}"),
                        _concept(c_supporting, f"S-{suffix}"),
                    ]
                )
                await s.commit()
            async with sm() as s:
                s.add_all(
                    [
                        ProblemConcept.from_schema(
                            ProblemConceptSchema(
                                problem_id=pid,
                                concept_id=c_primary,
                                role=ConceptRole.PRIMARY,
                            )
                        ),
                        ProblemConcept.from_schema(
                            ProblemConceptSchema(
                                problem_id=pid,
                                concept_id=c_tested,
                                role=ConceptRole.TESTED,
                            )
                        ),
                        ProblemConcept.from_schema(
                            ProblemConceptSchema(
                                problem_id=pid,
                                concept_id=c_supporting,
                                role=ConceptRole.SUPPORTING,
                            )
                        ),
                    ]
                )
                await s.commit()
        finally:
            await engine.dispose()

    async def _run() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            sm = async_sessionmaker(engine, expire_on_commit=False)
            async with sm() as session:
                records = await record_problem_attempt_mastery(
                    session, evidence=_ev(uid, pid, True)
                )
            # PRIMARY·TESTED 2개만 갱신·SUPPORTING 제외
            updated = {r.concept_id for r in records}
            assert updated == {c_primary, c_tested}
            assert c_supporting not in updated
            assert all(float(r.mastery) == 0.69 for r in records)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup(uid))
        asyncio.run(_cleanup_problem(pid, [c_primary, c_tested, c_supporting]))


async def _mastery_row_count(user_id: uuid.UUID, concept_id: uuid.UUID) -> int:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            n = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM concept_mastery_history "
                        "WHERE user_id = :uid AND concept_id = :cid"
                    ),
                    {"uid": str(user_id), "cid": str(concept_id)},
                )
            ).scalar()
        return int(n or 0)
    finally:
        await engine.dispose()


def test_incorrect_blames_primary_only_on_live_pg() -> None:
    """모델 B(실 PG) — 오답은 PRIMARY에만 행 적재·TESTED 거짓 약점 0. 이후 정답은 TESTED도 지지."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid = uuid.uuid4()
    c_primary, c_tested = uuid.uuid4(), uuid.uuid4()
    suffix = pid.hex[:8]

    async def _setup() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            sm = async_sessionmaker(engine, expire_on_commit=False)
            async with sm() as s:
                s.add(
                    Problem.from_schema(
                        ProblemSchema(
                            problem_id=pid,
                            source_type=SourceType.자체생성,
                            curriculum_version=Curriculum.REVISION_2022,
                            valid_from_year=2022,
                            subject=Subject.공통,
                            unit_codes=[f"U-{suffix}"],
                        )
                    )
                )
                s.add_all([_concept(c_primary, f"P-{suffix}"), _concept(c_tested, f"T-{suffix}")])
                await s.commit()
            async with sm() as s:
                s.add_all(
                    [
                        ProblemConcept.from_schema(
                            ProblemConceptSchema(
                                problem_id=pid, concept_id=c_primary, role=ConceptRole.PRIMARY
                            )
                        ),
                        ProblemConcept.from_schema(
                            ProblemConceptSchema(
                                problem_id=pid, concept_id=c_tested, role=ConceptRole.TESTED
                            )
                        ),
                    ]
                )
                await s.commit()
        finally:
            await engine.dispose()

    async def _run() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            sm = async_sessionmaker(engine, expire_on_commit=False)
            # 오답: PRIMARY만 갱신(TESTED 미갱신 — 거짓 약점 0).
            async with sm() as session:
                rec_wrong = await record_problem_attempt_mastery(
                    session, evidence=_ev(uid, pid, False)
                )
            assert {r.concept_id for r in rec_wrong} == {c_primary}
            assert await _mastery_row_count(uid, c_primary) == 1
            assert await _mastery_row_count(uid, c_tested) == 0  # ★ TESTED 거짓 약점 0
            # 정답: 전체 지지 — TESTED도 행 생성(비대칭의 반대편).
            async with sm() as session:
                rec_right = await record_problem_attempt_mastery(
                    session, evidence=_ev(uid, pid, True)
                )
            assert {r.concept_id for r in rec_right} == {c_primary, c_tested}
            assert await _mastery_row_count(uid, c_tested) == 1
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup(uid))
        asyncio.run(_cleanup_problem(pid, [c_primary, c_tested]))
