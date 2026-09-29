"""EOS-25 수능 모드 추천 — **실 PG**에서 설명 정렬·재선택 보류가 실제 그래프·숙달 이력으로 서는가.

단위 테스트(`test_next_problem_policy_suneung.py`)는 그래프·근거 조회를 대역으로 바꾼다. 거기서는
"대역이 준 목표로 정책이 옳게 판정하는가"만 재고, **실제 `concept_edge`·`concept_mastery_history`를
읽어서 같은 판정이 서는가**는 볼 수 없다. 이 파일이 그 공백을 메운다.

각 시나리오는 **실패 방향의 대조군**을 심는다 — 옮겨 갈 목표 개념에 수능 적격 문항을 실제로 둔다.
재선택이 되살아나면(보류가 풀리면) 그 문항이 나가고, 보류가 선다면 1차 선택 문항이 나간다. 목표에
문항이 없으면 보류와 콘텐츠 공백을 가를 수 없으므로 일부러 채워 둔다(CLAUDE.md "보호 장치를 실패
주입 없이 선언 금지").

전제(기존 수능 통합 테스트와 같다): DB에 이 파일이 심지 않은 수능 적격 문항이 없다. CI의
backend-migrations 잡은 마이그레이션만 적용한 DB에서 시작하고, 각 테스트는 심은 행을 지운다.

실행: `WHYMATH_RUN_INTEGRATION=1 pytest -m integration tests/backend/api/test_eos25_suneung_alignment_integration.py`
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.api._next_problem_policy import SuneungRecommendationPolicy
from whymath_backend.config import Settings
from whymath_backend.db.models.assessment import ConceptMasteryHistory
from whymath_backend.db.models.concept import Concept, ConceptEdge, ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.learner_state import get_state
from whymath_backend.l2.recommendation_contract import LearningContext, RecommendationAction
from whymath_backend.l2.recommendation_policy import IntentResolution, NextProblemOutcome
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.concept import ProblemConcept as ProblemConceptSchema
from whymath_backend.schema.enums import (
    ConceptLevel,
    ConceptRole,
    Curriculum,
    EdgeType,
    ExamType,
    Persona,
    ReviewStatus,
    SignaturePattern,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema

pytestmark = pytest.mark.integration

_SECRET = "eos25-suneung-alignment-jwt-secret-0123456789"


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


def _require_pg() -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")


def _concept(cid: uuid.UUID, tag: str) -> Concept:
    return Concept.from_schema(
        ConceptSchema(
            concept_id=cid,
            code=f"UC-EOS25-{tag}-{cid.hex[:8]}",
            name_ko=f"수능 정렬 픽스처 {tag}",
            level=ConceptLevel.세부개념,
        )
    )


def _edge(from_id: uuid.UUID, to_id: uuid.UUID) -> ConceptEdge:
    return ConceptEdge(
        from_concept_id=from_id,
        to_concept_id=to_id,
        edge_type=EdgeType.PREREQUISITE.value,
        edge_strength=1.0,
    )


def _problem(pid: uuid.UUID, difficulty: float | None, **over: Any) -> Problem:
    """기본은 수능 적격(시그니처 보유 · 검수 통과 · 자체생성). 필요한 필드만 덮어쓴다."""
    kwargs: dict[str, Any] = {
        "problem_id": pid,
        "source_type": SourceType.자체생성,
        "review_status": ReviewStatus.approved,
        "curriculum_version": Curriculum.REVISION_2022,
        "valid_from_year": 2022,
        "subject": Subject.공통,
        "unit_codes": ["U-EOS25"],
        "difficulty_overall": difficulty,
        "signature_patterns": [SignaturePattern.COMPOUND_CHOICES],
        "answer": "EOS25_SENTINEL",
    }
    kwargs.update(over)
    return Problem.from_schema(ProblemSchema(**kwargs))


def _pc(pid: uuid.UUID, cid: uuid.UUID, role: ConceptRole = ConceptRole.PRIMARY) -> ProblemConcept:
    return ProblemConcept.from_schema(
        ProblemConceptSchema(problem_id=pid, concept_id=cid, role=role)
    )


def _mastery(uid: uuid.UUID, cid: uuid.UUID, value: float) -> ConceptMasteryHistory:
    return ConceptMasteryHistory(
        user_id=uid,
        concept_id=cid,
        measured_at=datetime.now(UTC),
        mastery=value,
        confidence=0.7,
        sample_size=8,
    )


async def _seed(rows: list[object]) -> None:
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            for row in rows:
                session.add(row)
                await session.flush()  # FK 순서를 목록 순서 그대로 지킨다
            await session.commit()
    finally:
        await engine.dispose()


async def _cleanup(
    problem_ids: list[uuid.UUID], concept_ids: list[uuid.UUID], user_ids: list[uuid.UUID]
) -> None:
    engine = create_async_engine(_settings().database_url)
    pids = [str(p) for p in problem_ids]
    cids = [str(c) for c in concept_ids]
    uids = [str(u) for u in user_ids]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM concept_mastery_history WHERE user_id = ANY(:ids)"),
                {"ids": uids},
            )
            await conn.execute(
                text("DELETE FROM problem_concept WHERE problem_id = ANY(:ids)"), {"ids": pids}
            )
            await conn.execute(
                text("DELETE FROM problem WHERE problem_id = ANY(:ids)"), {"ids": pids}
            )
            await conn.execute(
                text(
                    "DELETE FROM concept_edge WHERE from_concept_id = ANY(:ids) "
                    "OR to_concept_id = ANY(:ids)"
                ),
                {"ids": cids},
            )
            await conn.execute(
                text("DELETE FROM concept WHERE concept_id = ANY(:ids)"), {"ids": cids}
            )
    finally:
        await engine.dispose()


async def _recommend(uid: uuid.UUID) -> NextProblemOutcome:
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            learner_state = await get_state(session, uid)
            policy = SuneungRecommendationPolicy(session, persona=Persona.A_일반고고3)
            return await policy(learner_state, LearningContext(mode="suneung"))
    finally:
        await engine.dispose()


def _anchor_problem(pid: uuid.UUID) -> Problem:
    """1차 선택을 확실히 가져갈 수능 기출 문항 — θ=0에 딱 맞고(b=0) 우선순위 가중이 최대다."""
    return _problem(
        pid, 3.0, exam_type=ExamType.수능, exam_authority_weight=1.0, irt_difficulty_b=0.0
    )


def test_suneung_advance_is_withheld_even_when_the_next_concept_has_a_problem_on_live_pg() -> None:
    """(가) — 숙달 0.98 개념에서 다음 개념에 수능 적격 문항이 **있어도** 옮기지 않는다(보류).

    종전 main은 여기서 `advance_next`·target=현재 개념을 냈다(설명이 전진하며 제자리). 기본 CAT이라면
    다음 개념 문항으로 다시 골랐을 상황이다 — 수능 모드는 1차 문항과 현재 개념 연습을 낸다.
    """
    _require_pg()
    uid = uuid.uuid4()
    c_anchor, c_next = uuid.uuid4(), uuid.uuid4()
    p_anchor, p_next = uuid.uuid4(), uuid.uuid4()
    try:
        asyncio.run(
            _seed(
                [
                    _concept(c_anchor, "anchor"),
                    _concept(c_next, "next"),
                    _edge(c_anchor, c_next),
                    _anchor_problem(p_anchor),
                    _problem(p_next, 4.5),  # 대조군: 재선택이 되살아나면 이 문항이 나간다
                    _pc(p_anchor, c_anchor),
                    _pc(p_next, c_next),
                    _mastery(uid, c_anchor, 0.98),
                ]
            )
        )
        outcome = asyncio.run(_recommend(uid))
        assert (
            outcome.problem_id == p_anchor
        ), f"1차 선택 문항이 아니다: {outcome.problem_id} — 수능 모드가 콘텐츠를 옮겼다(보류 붕괴)"
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == c_anchor
        assert outcome.reason.concept_id == c_anchor
        assert outcome.reason.mastery == 0.98
        assert outcome.intent_resolution is IntentResolution.MODE_WITHHELD
        assert outcome.policy_version == "suneung_v2"
    finally:
        asyncio.run(_cleanup([p_anchor, p_next], [c_anchor, c_next], [uid]))


def _prerequisite_fixture(
    uid: uuid.UUID, prerequisite_mastery: float
) -> tuple[list[object], dict[str, uuid.UUID]]:
    """앵커 A(숙달 0.12 — 선수 구간)와 그 선수 P. P에도 수능 적격 문항을 둔다(대조군)."""
    ids = {name: uuid.uuid4() for name in ("c_pre", "c_anchor", "p_anchor", "p_pre")}
    rows: list[object] = [
        _concept(ids["c_pre"], "pre"),
        _concept(ids["c_anchor"], "anchor"),
        _edge(ids["c_pre"], ids["c_anchor"]),  # P → A: P가 A의 선수
        _anchor_problem(ids["p_anchor"]),
        _problem(ids["p_pre"], 4.5),
        _pc(ids["p_anchor"], ids["c_anchor"]),
        _pc(ids["p_pre"], ids["c_pre"]),
        _mastery(uid, ids["c_anchor"], 0.12),
        _mastery(uid, ids["c_pre"], prerequisite_mastery),
    ]
    return rows, ids


def test_suneung_weak_prerequisite_is_withheld_on_live_pg() -> None:
    """약한 선수(0.2)가 측정돼 있고 문항도 있다 — 기본 CAT이라면 그 문항으로 다시 고를 상황이다."""
    _require_pg()
    uid = uuid.uuid4()
    rows, ids = _prerequisite_fixture(uid, 0.2)
    try:
        asyncio.run(_seed(rows))
        outcome = asyncio.run(_recommend(uid))
        assert outcome.problem_id == ids["p_anchor"]
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == ids["c_anchor"]
        assert outcome.intent_resolution is IntentResolution.MODE_WITHHELD
    finally:
        asyncio.run(
            _cleanup([ids["p_anchor"], ids["p_pre"]], [ids["c_pre"], ids["c_anchor"]], [uid])
        )


def test_suneung_mastered_prerequisite_is_refuted_on_live_pg() -> None:
    """(나) — 선수가 1.0이면 '막힌 선수'가 아니다(반증). 종전 main은 target=그 선수를 냈다."""
    _require_pg()
    uid = uuid.uuid4()
    rows, ids = _prerequisite_fixture(uid, 1.0)
    try:
        asyncio.run(_seed(rows))
        outcome = asyncio.run(_recommend(uid))
        assert outcome.problem_id == ids["p_anchor"]
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == ids["c_anchor"]
        assert outcome.intent_resolution is IntentResolution.REFUTED
        assert outcome.reason.mastery == 0.12
    finally:
        asyncio.run(
            _cleanup([ids["p_anchor"], ids["p_pre"]], [ids["c_pre"], ids["c_anchor"]], [uid])
        )
