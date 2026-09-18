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
from sqlalchemy.exc import IntegrityError
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


def test_same_attempt_cannot_be_applied_twice_on_live_pg() -> None:
    """**멱등의 권위** — 같은 시도의 두 번째 숙달 INSERT를 DB가 거부한다 (EOS-108 ④·⑦-가).

    애플리케이션 사전 조회(`_applied_for_attempt`)는 *정상 재시도*를 조용히 끝내 줄 뿐,
    check-then-act 경합은 막지 못한다 — 동시 제출 두 건이 서로의 행을 보지 못하고 둘 다
    "아직 없다"로 통과할 수 있다. 막는 것은 부분 유니크 인덱스
    `uq_concept_mastery_history_attempt`이며, **그 인덱스가 실재하고 실제로 거부하는지**는
    실 PG에서만 확인된다(hermetic 테스트는 ORM 메타데이터만 본다).

    그래서 여기서는 계약 경로를 우회해 **직접 INSERT**를 두 번 시도한다. 계약 경로로 두 번
    부르면 사전 조회가 먼저 막아 인덱스에 닿지 않아, *인덱스가 없어도 통과하는* 위장
    테스트가 된다(CLAUDE.md 「가드가 막는다는 주장도 주입으로 검증한다」).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    cid = uuid.uuid4()
    attempt_id = uuid.uuid4()
    t1 = datetime(2026, 9, 18, tzinfo=UTC)

    async def _insert(conn: object, measured_at: datetime, aid: uuid.UUID | None) -> None:
        await conn.execute(  # type: ignore[attr-defined]
            text(
                "INSERT INTO concept_mastery_history "
                "(user_id, concept_id, measured_at, mastery, confidence, sample_size, attempt_id) "
                "VALUES (:uid, :cid, :ts, 0.50, 0.50, 1, :aid)"
            ),
            {"uid": str(uid), "cid": str(cid), "ts": measured_at, "aid": aid},
        )

    async def _run() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                await _insert(conn, t1, attempt_id)
            # 같은 시도 + 다른 measured_at → 복합 PK는 통과하지만 부분 유니크 인덱스가 막는다.
            # (PK만으로는 못 막는다는 것이 이 태스크의 출발점이다 — 재시도는 새 시각을 만든다.)
            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await _insert(conn, t1 + timedelta(minutes=5), attempt_id)

            # **대조군** — `attempt_id IS NULL`인 측정은 서로 충돌하지 않는다(부분 인덱스의 요점).
            # 이것이 없으면 "전체 유니크"라는 과잉 제약이 위 단언을 통과시킨다.
            async with engine.begin() as conn:
                await _insert(conn, t1 + timedelta(minutes=10), None)
            async with engine.begin() as conn:
                await _insert(conn, t1 + timedelta(minutes=15), None)

            engine2 = create_async_engine(_settings().database_url)
            try:
                async with engine2.connect() as conn:
                    total = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM concept_mastery_history "
                                "WHERE user_id = :uid"
                            ),
                            {"uid": str(uid)},
                        )
                    ).scalar()
                assert total == 3, "시도 유래 1건 + 배치 2건이어야 한다(이중 반영 0)"
            finally:
                await engine2.dispose()
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup(uid))
