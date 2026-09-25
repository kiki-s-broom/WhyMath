"""EOS-124 정렬 선택 조회 2종 — **실 PG**에서 SQL이 의도대로 도는가 (기본 SKIP).

`load_direct_successors`(앵커 → 직접 후행)와 `load_target_candidate_rows`(목표 개념의 후보)는
정책 단위 테스트(`test_recommendation_policy.py`)에서 전부 대역으로 바뀐다. 거기서는 "대역이 준
행으로 정책이 옳게 고르는가"만 재고, **SQL 자체가 옳은 행을 내는가**는 볼 수 없다. 이 파일이 그
공백을 메운다 — 방향·엣지 타입 격리·대표 개념(PRIMARY) 한정·노출 게이트·미응답 배제·개념별 상한.

각 검사는 **실패 방향의 대조군**을 함께 심는다(정상 입력만 심으면 모든 입력에서 초록인 조회도
같은 화면을 낸다 — CLAUDE.md "보호 장치를 실패 주입 없이 선언 금지"):
  - 후행 조회에 *역방향*(선수) 엣지와 *다른 타입*(ANALOGOUS_TO) 엣지를 함께 심는다.
  - 후보 조회에 TESTED 전용 문항·미검수 문항·이미 푼 문항·목표 밖 개념 문항을 함께 심는다.

실행: `WHYMATH_RUN_INTEGRATION=1 pytest -m integration tests/backend/l2/test_next_problem_alignment_integration.py`
(CI의 backend-migrations 잡이 `pytest -m integration`으로 수집한다.)
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.db.models.concept import Concept, ConceptEdge, ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2 import next_problem_selection as selection
from whymath_backend.l2.next_problem_selection import (
    load_direct_successors,
    load_target_candidate_rows,
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

_SECRET = "eos124-alignment-jwt-secret-0123456789abcdef"


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


def _concept(cid: uuid.UUID, tag: str) -> Concept:
    return Concept.from_schema(
        ConceptSchema(
            concept_id=cid,
            code=f"UC-EOS124-{tag}-{cid.hex[:8]}",
            name_ko=f"정렬 선택 픽스처 {tag}",
            level=ConceptLevel.세부개념,
        )
    )


def _edge(from_id: uuid.UUID, to_id: uuid.UUID, edge_type: EdgeType) -> ConceptEdge:
    return ConceptEdge(
        from_concept_id=from_id,
        to_concept_id=to_id,
        edge_type=edge_type.value,
        edge_strength=1.0,
    )


def _problem(
    pid: uuid.UUID, difficulty: float, *, review: ReviewStatus = ReviewStatus.approved
) -> Problem:
    return Problem.from_schema(
        ProblemSchema(
            problem_id=pid,
            source_type=SourceType.자체생성,
            review_status=review,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.공통,
            unit_codes=["U-EOS124"],
            difficulty_overall=difficulty,
            answer="EOS124_SENTINEL",
        )
    )


def _pc(pid: uuid.UUID, cid: uuid.UUID, role: ConceptRole) -> ProblemConcept:
    return ProblemConcept.from_schema(
        ProblemConceptSchema(problem_id=pid, concept_id=cid, role=role)
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


async def _cleanup(problem_ids: list[uuid.UUID], concept_ids: list[uuid.UUID]) -> None:
    engine = create_async_engine(_settings().database_url)
    pids = [str(p) for p in problem_ids]
    cids = [str(c) for c in concept_ids]
    try:
        async with engine.begin() as conn:
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


def _require_pg() -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")


def test_direct_successors_follow_prerequisite_edges_forward_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """후행 = 앵커를 *선수로 삼는* 개념(from==앵커). 역방향·다른 타입 엣지는 후행이 아니다."""
    _require_pg()
    anchor, nxt_a, nxt_b, before, analogous = (uuid.uuid4() for _ in range(5))
    concepts = [anchor, nxt_a, nxt_b, before, analogous]

    async def _run() -> None:
        await _seed(
            [
                _concept(anchor, "anchor"),
                _concept(nxt_a, "next-a"),
                _concept(nxt_b, "next-b"),
                _concept(before, "before"),
                _concept(analogous, "analog"),
                _edge(anchor, nxt_a, EdgeType.PREREQUISITE),
                _edge(anchor, nxt_b, EdgeType.PREREQUISITE),
                _edge(before, anchor, EdgeType.PREREQUISITE),  # 대조군: 선수(역방향)
                _edge(anchor, analogous, EdgeType.ANALOGOUS_TO),  # 대조군: traversal 금지 타입
            ]
        )
        engine = create_async_engine(_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as session:
                rows = await load_direct_successors(session, anchor, max_nodes=20)
                assert {r.concept_id for r in rows} == {nxt_a, nxt_b}
                assert all(r.concept_code.startswith("UC-EOS124-next") for r in rows)
                # 너비 예산 — 잘라도 **로그를 남긴다**(침묵 절단 금지).
                with caplog.at_level("WARNING"):
                    capped = await load_direct_successors(session, anchor, max_nodes=1)
                assert len(capped) == 1
                assert "노드 예산 초과" in caplog.text
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup([], concepts))


def test_target_candidates_are_primary_gated_unattempted_and_capped_per_concept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """목표 개념 후보 = 대표 개념이 목표인 · 노출 게이트 통과 · 미응답 문항, 개념마다 상한까지."""
    _require_pg()
    c_a, c_b, c_other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    a_near, a_far, b_only = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tested_only, pending, attempted, other = (uuid.uuid4() for _ in range(4))
    problems = [a_near, a_far, b_only, tested_only, pending, attempted, other]
    concepts = [c_a, c_b, c_other]

    async def _run() -> None:
        await _seed(
            [
                _concept(c_a, "target-a"),
                _concept(c_b, "target-b"),
                _concept(c_other, "other"),
                _problem(a_near, 3.0),
                _problem(a_far, 5.0),
                _problem(b_only, 4.9),  # θ에서 멀어도 개념별 상한 덕에 잘리지 않아야 한다
                _problem(tested_only, 3.0),
                _problem(pending, 3.0, review=ReviewStatus.pending),
                _problem(attempted, 3.0),
                _problem(other, 3.0),
                _pc(a_near, c_a, ConceptRole.PRIMARY),
                _pc(a_far, c_a, ConceptRole.PRIMARY),
                _pc(b_only, c_b, ConceptRole.PRIMARY),
                _pc(tested_only, c_a, ConceptRole.TESTED),  # 대조군: 주된 개념이 아니다
                _pc(pending, c_a, ConceptRole.PRIMARY),  # 대조군: 검수 게이트
                _pc(attempted, c_a, ConceptRole.PRIMARY),  # 대조군: 이미 푼 문항
                _pc(other, c_other, ConceptRole.PRIMARY),  # 대조군: 목표 밖 개념
            ]
        )
        engine = create_async_engine(_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as session:
                rows = await load_target_candidate_rows(
                    session,
                    0.0,
                    concept_ids=[c_a, c_b],
                    attempted_ids={attempted},
                    excluded_ids=set(),
                )
                by_concept = {(pid, cid) for pid, _d, _b, cid in rows}
                assert by_concept == {(a_near, c_a), (a_far, c_a), (b_only, c_b)}
                # 개념별 상한 — 상한을 1로 줄이면 개념마다 θ에 가장 가까운 1건만 남는다.
                # 전체에 한 번 limit을 걸었다면 θ에 먼 b_only가 여기서 사라진다.
                monkeypatch.setattr(selection, "CANDIDATE_POOL_SIZE", 1)
                capped = await load_target_candidate_rows(
                    session,
                    0.0,
                    concept_ids=[c_a, c_b],
                    attempted_ids={attempted},
                    excluded_ids=set(),
                )
                assert {(pid, cid) for pid, _d, _b, cid in capped} == {
                    (a_near, c_a),
                    (b_only, c_b),
                }
                assert (
                    await load_target_candidate_rows(
                        session, 0.0, concept_ids=[], attempted_ids=set(), excluded_ids=set()
                    )
                    == []
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup(problems, concepts))
