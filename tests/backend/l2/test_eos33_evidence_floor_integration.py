"""EOS-33 관계 행위의 증거 요건 — **실 PG**에서 실제 숙달 이력의 표본 수·그래프로 판정이 서는가.

단위 테스트(`test_recommendation_policy.py`)는 근거·그래프 조회를 대역으로 바꾼다. 거기서는 "대역이
준 표본 수로 정책이 옳게 판정하는가"만 재고, **`concept_mastery_history.sample_size`를 실제로 읽어
같은 판정이 서는가**는 볼 수 없다(근거 조회기가 표본 수를 흘리면 대역 테스트는 초록이다). 이 파일이
그 공백을 메운다 — 기본 CAT 정책(`CatRecommendationPolicy`)을 실 세션으로 돌린다.

각 시나리오는 **실패 방향의 대조군**을 심는다 — 옮겨 갈 목표 개념(다음 개념·선수)에 출제 가능한
문항을 실제로 둔다. 하한이 사라지면(또는 경계가 0.7로 돌아가면) 그 문항이 나가고, 하한이 서면 1차
선택 문항이 나간다. 목표에 문항이 없으면 증거 부족과 콘텐츠 공백(`target_unavailable`)을 가를 수
없으므로 일부러 채워 둔다(CLAUDE.md "보호 장치를 실패 주입 없이 선언 금지").

전제(기존 정렬 통합 테스트와 같다): DB에 이 파일이 심지 않은 출제 가능 문항이 없다. CI의
backend-migrations 잡은 마이그레이션만 적용한 DB에서 시작하고, 각 테스트는 심은 행을 지운다.
숙달 이력 행을 직접 심는 것은 **정책 판정의 입력을 고정**하기 위해서다(HTTP로 만들면 표본 수와
숙달이 함께 움직여 경계를 따로 밟을 수 없다) — 정답이 쌓여 경계를 넘는 궤적 자체는 HTTP만 쓰는
시나리오 스위트 SCENARIO-007이 본다.

실행: `WHYMATH_RUN_INTEGRATION=1 pytest -m integration tests/backend/l2/test_eos33_evidence_floor_integration.py`
(CI의 backend-migrations 잡이 `pytest -m integration`으로 수집한다.)
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

from whymath_backend.config import Settings
from whymath_backend.db.models.assessment import ConceptMasteryHistory
from whymath_backend.db.models.concept import Concept, ConceptEdge, ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.learner_state import get_state
from whymath_backend.l2.recommendation_contract import LearningContext, RecommendationAction
from whymath_backend.l2.recommendation_policy import (
    CatRecommendationPolicy,
    IntentResolution,
    NextProblemOutcome,
)
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.concept import ProblemConcept as ProblemConceptSchema
from whymath_backend.schema.enums import (
    ConceptLevel,
    ConceptRole,
    Curriculum,
    EdgeType,
    ReviewStatus,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema

pytestmark = pytest.mark.integration

_SECRET = "eos33-evidence-floor-jwt-secret-0123456789ab"


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
            code=f"UC-EOS33-{tag}-{cid.hex[:8]}",
            name_ko=f"증거 요건 픽스처 {tag}",
            level=ConceptLevel.세부개념,
        )
    )


def _edge(from_id: uuid.UUID, to_id: uuid.UUID) -> ConceptEdge:
    """`from`이 `to`의 선수다(선수 → 후행)."""
    return ConceptEdge(
        from_concept_id=from_id,
        to_concept_id=to_id,
        edge_type=EdgeType.PREREQUISITE.value,
        edge_strength=1.0,
    )


def _problem(pid: uuid.UUID, difficulty: float, **over: Any) -> Problem:
    kwargs: dict[str, Any] = {
        "problem_id": pid,
        "source_type": SourceType.자체생성,
        "review_status": ReviewStatus.approved,
        "curriculum_version": Curriculum.REVISION_2022,
        "valid_from_year": 2022,
        "subject": Subject.공통,
        "unit_codes": ["U-EOS33"],
        "difficulty_overall": difficulty,
        "answer": "EOS33_SENTINEL",
    }
    kwargs.update(over)
    return Problem.from_schema(ProblemSchema(**kwargs))


def _anchor_problem(pid: uuid.UUID) -> Problem:
    """1차 선택을 확실히 가져갈 문항 — θ=0(응답 0건)에 딱 맞는다(b=0)."""
    return _problem(pid, 3.0, irt_difficulty_b=0.0)


def _pc(pid: uuid.UUID, cid: uuid.UUID) -> ProblemConcept:
    return ProblemConcept.from_schema(
        ProblemConceptSchema(problem_id=pid, concept_id=cid, role=ConceptRole.PRIMARY)
    )


def _mastery(
    uid: uuid.UUID, cid: uuid.UUID, value: float, sample_size: int | None
) -> ConceptMasteryHistory:
    """숙달 이력 1행 — 신뢰도는 저장 경로와 같은 식(n/(n+5))으로 채운다(없으면 None)."""
    confidence = None if sample_size is None else round(sample_size / (sample_size + 5), 2)
    return ConceptMasteryHistory(
        user_id=uid,
        concept_id=cid,
        measured_at=datetime.now(UTC),
        mastery=value,
        confidence=confidence,
        sample_size=sample_size,
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
    """핸들러와 같은 조립 — 학습자 상태를 읽고 기본 CAT 정책을 실 세션으로 부른다."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            learner_state = await get_state(session, uid)
            policy = CatRecommendationPolicy(session)
            return await policy(learner_state, LearningContext())
    finally:
        await engine.dispose()


# ──────────────────────────────────────────────────────────────────────────
# 전진 — 앵커 응답 3개 미만이면 옮기지 않는다
# ──────────────────────────────────────────────────────────────────────────
def _advance_fixture(
    uid: uuid.UUID, anchor_samples: int | None
) -> tuple[list[object], dict[str, uuid.UUID]]:
    """앵커 A(숙달 0.92 — 전진 구간)와 그 후행 N. N에도 출제 가능한 문항을 둔다(대조군)."""
    ids = {name: uuid.uuid4() for name in ("c_anchor", "c_next", "p_anchor", "p_next")}
    rows: list[object] = [
        _concept(ids["c_anchor"], "anchor"),
        _concept(ids["c_next"], "next"),
        _edge(ids["c_anchor"], ids["c_next"]),  # A → N: A가 N의 선수(N이 다음 개념)
        _anchor_problem(ids["p_anchor"]),
        _problem(ids["p_next"], 4.5),  # 대조군: 하한이 사라지면 이 문항이 나간다
        _pc(ids["p_anchor"], ids["c_anchor"]),
        _pc(ids["p_next"], ids["c_next"]),
        _mastery(uid, ids["c_anchor"], 0.92, anchor_samples),
    ]
    return rows, ids


@pytest.mark.parametrize("anchor_samples", [2, None])
def test_thin_advance_keeps_the_first_pass_problem_on_live_pg(anchor_samples: int | None) -> None:
    """응답 2개(BKT 기본값 정답 2회 ≈ 0.92)로는 다음 개념에 문항이 **있어도** 옮기지 않는다.

    `None`은 표본 수 열이 빈 레거시 행이다 — "모른다"를 "충분하다"로 읽지 않는다. 표본 수는 실제
    `concept_mastery_history.sample_size`에서 근거 조회기를 거쳐 온다(대역 없음).
    """
    _require_pg()
    uid = uuid.uuid4()
    rows, ids = _advance_fixture(uid, anchor_samples)
    try:
        asyncio.run(_seed(rows))
        outcome = asyncio.run(_recommend(uid))
        assert outcome.problem_id == ids["p_anchor"], (
            f"1차 선택 문항이 아니다: {outcome.problem_id} — 응답 {anchor_samples}개로 콘텐츠가 "
            "다음 개념으로 옮겨졌다(전진 하한 붕괴)"
        )
        assert outcome.intent_resolution is IntentResolution.INSUFFICIENT_EVIDENCE
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == ids["c_anchor"]
        assert outcome.reason.mastery == 0.92
        assert outcome.reason.sample_size == anchor_samples
        assert outcome.policy_version == "cat_v3"
    finally:
        asyncio.run(
            _cleanup([ids["p_anchor"], ids["p_next"]], [ids["c_anchor"], ids["c_next"]], [uid])
        )


def test_advance_with_three_responses_moves_to_the_next_concept_on_live_pg() -> None:
    """경계 자체 — 응답 3개면 다음 개념 문항으로 다시 고른다(하한이 전진을 막아 버리지 않는다)."""
    _require_pg()
    uid = uuid.uuid4()
    rows, ids = _advance_fixture(uid, 3)
    try:
        asyncio.run(_seed(rows))
        outcome = asyncio.run(_recommend(uid))
        assert outcome.problem_id == ids["p_next"], outcome
        assert outcome.intent_resolution is IntentResolution.SERVED
        assert outcome.action is RecommendationAction.ADVANCE_NEXT
        assert outcome.target_concept == ids["c_next"]
        assert outcome.reason.concept_id == ids["c_anchor"]  # 근거는 숙달한 앵커
        assert outcome.reason.sample_size == 3
    finally:
        asyncio.run(
            _cleanup([ids["p_anchor"], ids["p_next"]], [ids["c_anchor"], ids["c_next"]], [uid])
        )


# ──────────────────────────────────────────────────────────────────────────
# 선수 복귀 — 앵커 하한은 없고, 목표 P에 결손의 직접 증거(< 0.3)를 요구한다
# ──────────────────────────────────────────────────────────────────────────
def _prerequisite_fixture(
    uid: uuid.UUID, prerequisite_mastery: float
) -> tuple[list[object], dict[str, uuid.UUID]]:
    """앵커 A(숙달 0.12 · **응답 1개** — 선수 구간)와 그 선수 P. P에도 문항을 둔다(대조군)."""
    ids = {name: uuid.uuid4() for name in ("c_pre", "c_anchor", "p_anchor", "p_pre")}
    rows: list[object] = [
        _concept(ids["c_pre"], "pre"),
        _concept(ids["c_anchor"], "anchor"),
        _edge(ids["c_pre"], ids["c_anchor"]),  # P → A: P가 A의 선수
        _anchor_problem(ids["p_anchor"]),
        _problem(ids["p_pre"], 4.5),
        _pc(ids["p_anchor"], ids["c_anchor"]),
        _pc(ids["p_pre"], ids["c_pre"]),
        _mastery(uid, ids["c_anchor"], 0.12, 1),
        _mastery(uid, ids["c_pre"], prerequisite_mastery, 1),
    ]
    return rows, ids


def test_mixed_evidence_prerequisite_is_not_a_target_on_live_pg() -> None:
    """P 숙달 0.69(사전값에서 **정답 1회**) — cat_v2는 이 P로 내려갔다(정답이 복귀를 부르는 비단조).

    P에 문항이 있어도 1차 선택 문항이 나가고 반증(`refuted`)으로 강등된다.
    """
    _require_pg()
    uid = uuid.uuid4()
    rows, ids = _prerequisite_fixture(uid, 0.69)
    try:
        asyncio.run(_seed(rows))
        outcome = asyncio.run(_recommend(uid))
        assert (
            outcome.problem_id == ids["p_anchor"]
        ), f"1차 선택 문항이 아니다: {outcome.problem_id} — 엇갈린 증거의 선수로 내려갔다"
        assert outcome.intent_resolution is IntentResolution.REFUTED
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == ids["c_anchor"]
    finally:
        asyncio.run(
            _cleanup([ids["p_anchor"], ids["p_pre"]], [ids["c_pre"], ids["c_anchor"]], [uid])
        )


def test_deficit_prerequisite_is_served_despite_a_thin_anchor_on_live_pg() -> None:
    """P 숙달 0.15(사전값에서 **오답 1회**) — 앵커 응답이 1개여도 P 문항으로 내려간다.

    선수 쪽에는 앵커 하한을 걸지 않는다: 막힌 학생의 하강을 응답 3개까지 늦추면 그 사이 쌓인
    오답이 거짓 전진을 오히려 늘린다(판정문 §3-3). 이 테스트가 그 비대칭을 실 경로에서 고정한다.
    """
    _require_pg()
    uid = uuid.uuid4()
    rows, ids = _prerequisite_fixture(uid, 0.15)
    try:
        asyncio.run(_seed(rows))
        outcome = asyncio.run(_recommend(uid))
        assert outcome.problem_id == ids["p_pre"], outcome
        assert outcome.intent_resolution is IntentResolution.SERVED
        assert outcome.action is RecommendationAction.PRACTICE_PREREQUISITE
        assert outcome.target_concept == ids["c_pre"]
        assert outcome.reason.concept_id == ids["c_anchor"]  # 근거는 막힌 앵커
        assert outcome.reason.sample_size == 1
    finally:
        asyncio.run(
            _cleanup([ids["p_anchor"], ids["p_pre"]], [ids["c_pre"], ids["c_anchor"]], [uid])
        )
