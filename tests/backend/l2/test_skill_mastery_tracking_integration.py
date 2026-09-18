"""L2 BKT↔SkillMasteryHistory 결선 — 실 PG 통합테스트 (기본 SKIP·Part 2 Phase 2b-2).

`record_problem_attempt_skill_mastery`가 채점 attempt를 concept→skill 브리지
(`Concept.behavior_skills` ∩ mastery-estimable `skill_node`)로 해소해 `skill_mastery_history`에
INSERT하는지 실 PG로 검증한다. 핵심: ① concept→skill 조인(= ANY 멤버십) ② mastery_estimable 게이트
③ 모델 B(정답=전체 개념 스킬). `skill_mastery_history`는 FK 없는 hypertable 느슨참조라 user 선적재
불요. **구 437 `concept_node`를 읽지 않는다**(브리지가 런타임 `concept` 테이블).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.db.models.concept import Concept, ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.skill_node import SkillNode
from whymath_backend.l2.skill_mastery_tracking import record_problem_attempt_skill_mastery
from whymath_backend.schema.assessment_evidence import (
    AssessmentEvidence,
    build_assessment_evidence,
)
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.concept import ProblemConcept as ProblemConceptSchema
from whymath_backend.schema.enums import (
    BehaviorArea,
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


def _concept(cid: uuid.UUID, code: str, skills: list[str]) -> Concept:
    return Concept.from_schema(
        ConceptSchema(
            concept_id=cid,
            code=code,
            name_ko=f"개념{code}",
            level=ConceptLevel.세부개념,
            behavior_skills=skills,
        )
    )


def _skill(skill_id: str, *, estimable: bool) -> SkillNode:
    return SkillNode(
        skill_id=skill_id,
        name_ko=f"스킬{skill_id}",
        behavior_area=BehaviorArea.COMPUTE,
        family="test-family",
        mastery_estimable=estimable,
        review_status="ai_estimated",
    )


async def _cleanup(
    user_id: uuid.UUID,
    problem_id: uuid.UUID,
    concept_ids: list[uuid.UUID],
    skill_ids: list[str],
) -> None:
    engine = create_async_engine(_settings().database_url)
    cids = [str(c) for c in concept_ids]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM skill_mastery_history WHERE user_id = :uid"),
                {"uid": str(user_id)},
            )
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
            await conn.execute(
                text("DELETE FROM skill_node WHERE skill_id = ANY(:sids)"),
                {"sids": skill_ids},
            )
    finally:
        await engine.dispose()


def test_attempt_resolves_skills_and_gates_non_estimable_on_live_pg() -> None:
    """정답 attempt → 평가 개념(PRIMARY+TESTED)의 mastery-estimable 스킬만 갱신(비추정 스킬 게이트).

    c1(PRIMARY)→[s_est, s_nonest], c2(TESTED)→[s_est2]. 정답이면 두 개념 모두 지지하되
    s_nonest(mastery_estimable=False)는 게이트로 제외된다. 결과 스킬 = {s_est, s_est2}·mastery 0.69.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid = uuid.uuid4()
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    suffix = pid.hex[:8]
    s_est = f"skill.est-{suffix}"
    s_nonest = f"skill.nonest-{suffix}"
    s_est2 = f"skill.est2-{suffix}"

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
                        _concept(c1, f"C1-{suffix}", [s_est, s_nonest]),
                        _concept(c2, f"C2-{suffix}", [s_est2]),
                        _skill(s_est, estimable=True),
                        _skill(s_nonest, estimable=False),
                        _skill(s_est2, estimable=True),
                    ]
                )
                await s.commit()
            async with sm() as s:
                s.add_all(
                    [
                        ProblemConcept.from_schema(
                            ProblemConceptSchema(
                                problem_id=pid, concept_id=c1, role=ConceptRole.PRIMARY
                            )
                        ),
                        ProblemConcept.from_schema(
                            ProblemConceptSchema(
                                problem_id=pid, concept_id=c2, role=ConceptRole.TESTED
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
                records = await record_problem_attempt_skill_mastery(
                    session, evidence=_ev(uid, pid, True)
                )
            updated = {r.skill_id for r in records}
            # mastery-estimable 스킬만·비추정(s_nonest) 게이트 제외.
            assert updated == {s_est, s_est2}
            assert s_nonest not in updated
            assert all(float(r.mastery) == 0.69 for r in records)  # 정답·첫 관측
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup(uid, pid, [c1, c2], [s_est, s_nonest, s_est2]))


def test_incorrect_blames_primary_skills_only_on_live_pg() -> None:
    """오답 attempt → PRIMARY 개념 스킬만 감점·TESTED 개념 스킬은 미갱신(거짓 약점 0·모델 B)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid = uuid.uuid4()
    c_p, c_t = uuid.uuid4(), uuid.uuid4()
    suffix = pid.hex[:8]
    s_primary = f"skill.p-{suffix}"
    s_tested = f"skill.t-{suffix}"

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
                        _concept(c_p, f"P-{suffix}", [s_primary]),
                        _concept(c_t, f"T-{suffix}", [s_tested]),
                        _skill(s_primary, estimable=True),
                        _skill(s_tested, estimable=True),
                    ]
                )
                await s.commit()
            async with sm() as s:
                s.add_all(
                    [
                        ProblemConcept.from_schema(
                            ProblemConceptSchema(
                                problem_id=pid, concept_id=c_p, role=ConceptRole.PRIMARY
                            )
                        ),
                        ProblemConcept.from_schema(
                            ProblemConceptSchema(
                                problem_id=pid, concept_id=c_t, role=ConceptRole.TESTED
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
                records = await record_problem_attempt_skill_mastery(
                    session, evidence=_ev(uid, pid, False)
                )
            updated = {r.skill_id for r in records}
            assert updated == {s_primary}  # PRIMARY 개념 스킬만
            assert s_tested not in updated  # TESTED 스킬은 거짓 약점 방지로 미갱신
            assert records[0].mastery == 0.15  # 오답·첫 관측
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup(uid, pid, [c_p, c_t], [s_primary, s_tested]))
