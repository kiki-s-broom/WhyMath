"""EOS-25 수능 정렬 재선택 — **실 PG**에서 SQL과 정책이 의도대로 도는가 (기본 SKIP).

단위 테스트(`test_next_problem_policy_suneung.py`)는 조회를 전부 대역으로 바꾼다. 거기서는 "대역이
준 행으로 정책이 옳게 고르는가"만 재고, **SQL이 옳은 행을 내는가**와 **실제 그래프·숙달 이력으로
정책이 옳게 도는가**는 볼 수 없다. 이 파일이 그 공백을 메운다.

  ① `load_suneung_target_candidates` — 수능 사전필터(난이도 · 저작권 · 수능 신호 OR · 페르소나
     적합도) · 대표 개념(PRIMARY) 한정 · 미응답/형제 배제 · 개념별 상한 · ORM→스키마 매핑.
  ② 정책 전체 — 숙달한 개념에서 다음 개념으로 전진할 때 **수능 적격** 문항만 나간다. 기본 CAT이라면
     골랐을 수능 신호 없는 문항·검수 안 된 문항은 θ에 더 가까워도 나가지 않는다. 적격 문항이 없으면
     모드를 벗어나지 않고 정직 강등한다.

각 검사는 **실패 방향의 대조군**을 함께 심는다(정상 입력만 심으면 모든 입력에서 초록인 조회도 같은
화면을 낸다 — CLAUDE.md "보호 장치를 실패 주입 없이 선언 금지").

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

from whymath_backend.api import _next_problem_policy as suneung_module
from whymath_backend.api._next_problem_policy import (
    SuneungRecommendationPolicy,
    load_suneung_target_candidates,
)
from whymath_backend.config import Settings
from whymath_backend.db.models.assessment import ConceptMasteryHistory
from whymath_backend.db.models.concept import Concept, ConceptEdge, ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.learner_state import get_state
from whymath_backend.l2.recommendation_contract import LearningContext, RecommendationAction
from whymath_backend.l2.recommendation_policy import IntentResolution, NextProblemOutcome
from whymath_backend.l6.suneung import is_suneung_eligible
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


def test_suneung_target_candidates_are_prefiltered_primary_unattempted_and_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """목표 개념 수능 후보 = 사전필터 통과 · 대표 개념이 목표 · 미응답·비형제 문항, 개념마다 상한까지.

    페르소나 B로 부른다 — 적합도 신호는 **요청 페르소나의 적합도**로만 통과해야 한다(A의 적합도로
    B 학생의 후보가 되지 않는다).
    """
    _require_pg()
    c_a, c_b, c_other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    a_near, a_far, b_fit = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    controls = {
        name: uuid.uuid4()
        for name in (
            "tested_only",
            "no_signal",
            "copyright",
            "no_difficulty",
            "fit_below",
            "fit_other_persona",
            "attempted",
            "sibling",
            "other_concept",
        )
    }
    problems = [a_near, a_far, b_fit, *controls.values()]
    concepts = [c_a, c_b, c_other]

    async def _run() -> None:
        await _seed(
            [
                _concept(c_a, "target-a"),
                _concept(c_b, "target-b"),
                _concept(c_other, "other"),
                _problem(a_near, 3.0),  # 시그니처 신호
                _problem(
                    a_far,
                    5.0,
                    signature_patterns=[],
                    exam_type=ExamType.수능,
                    exam_authority_weight=1.0,
                ),  # 기출 유형 신호
                # 적합도 신호만 — θ에서 멀어도 개념별 상한 덕에 잘리지 않아야 한다
                _problem(b_fit, 4.9, signature_patterns=[], persona_fit={Persona.B_자사고N수: 0.8}),
                _problem(controls["tested_only"], 3.0),
                _problem(controls["no_signal"], 3.0, signature_patterns=[]),
                _problem(
                    controls["copyright"],
                    3.0,
                    source_type=SourceType.평가원,
                    exam_type=ExamType.수능,
                ),
                _problem(controls["no_difficulty"], None),
                _problem(
                    controls["fit_below"],
                    3.0,
                    signature_patterns=[],
                    persona_fit={Persona.B_자사고N수: 0.3},
                ),
                _problem(
                    controls["fit_other_persona"],
                    3.0,
                    signature_patterns=[],
                    persona_fit={Persona.A_일반고고3: 0.9},
                ),
                _problem(controls["attempted"], 3.0),
                _problem(controls["sibling"], 3.0),
                _problem(controls["other_concept"], 3.0),
                _pc(a_near, c_a),
                _pc(a_far, c_a),
                _pc(b_fit, c_b),
                _pc(controls["tested_only"], c_a, ConceptRole.TESTED),  # 대조군: 주된 개념 아님
                _pc(controls["no_signal"], c_a),  # 대조군: 수능 신호 없음
                _pc(controls["copyright"], c_a),  # 대조군: 저작권 사전배제
                _pc(controls["no_difficulty"], c_a),  # 대조군: 난이도 라벨 없음
                _pc(controls["fit_below"], c_a),  # 대조군: 적합도 임계 미달
                _pc(controls["fit_other_persona"], c_a),  # 대조군: 다른 페르소나의 적합도
                _pc(controls["attempted"], c_a),  # 대조군: 이미 푼 문항
                _pc(controls["sibling"], c_a),  # 대조군: 형제 배제
                _pc(controls["other_concept"], c_other),  # 대조군: 목표 밖 개념
            ]
        )
        engine = create_async_engine(_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as session:
                kwargs: dict[str, Any] = {
                    "persona": Persona.B_자사고N수,
                    "concept_ids": [c_a, c_b],
                    "attempted_ids": {controls["attempted"]},
                    "excluded_ids": {controls["sibling"]},
                }
                rows = await load_suneung_target_candidates(session, 0.0, **kwargs)
                assert {(p.problem_id, cid) for p, cid in rows} == {
                    (a_near, c_a),
                    (a_far, c_a),
                    (b_fit, c_b),
                }
                # ORM→스키마 매핑이 온전하다(별칭 엔티티가 게이트가 읽는 필드를 잃지 않는다) —
                # 진실 게이트가 실제로 읽는 결과로 확인한다(적합도는 B에게만 있다).
                by_id = {p.problem_id: p for p, _ in rows}
                assert by_id[a_far].exam_authority_weight == 1.0
                assert is_suneung_eligible(by_id[b_fit], Persona.B_자사고N수) is True
                assert is_suneung_eligible(by_id[b_fit], Persona.A_일반고고3) is False
                # 개념별 상한 — 상한을 1로 줄이면 개념마다 θ에 가장 가까운 1건만 남는다.
                # 전체에 한 번 limit을 걸었다면 θ에서 먼 b_fit이 여기서 사라진다.
                monkeypatch.setattr(suneung_module, "CANDIDATE_POOL_SIZE", 1)
                capped = await load_suneung_target_candidates(session, 0.0, **kwargs)
                assert {(p.problem_id, cid) for p, cid in capped} == {(a_near, c_a), (b_fit, c_b)}
                monkeypatch.undo()
                assert (
                    await load_suneung_target_candidates(
                        session,
                        0.0,
                        persona=Persona.B_자사고N수,
                        concept_ids=[],
                        attempted_ids=set(),
                        excluded_ids=set(),
                    )
                    == []
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup(problems, concepts, []))


async def _recommend(uid: uuid.UUID) -> NextProblemOutcome:
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            learner_state = await get_state(session, uid)
            policy = SuneungRecommendationPolicy(session, persona=Persona.A_일반고고3)
            return await policy(learner_state, LearningContext(mode="suneung"))
    finally:
        await engine.dispose()


def _advance_fixture(
    uid: uuid.UUID, *, with_eligible_next: bool
) -> tuple[list[object], dict[str, uuid.UUID], list[uuid.UUID]]:
    """숙달한 개념 A(0.98)와 그 후행 N. A에는 1차 선택을 확실히 가져갈 수능 기출 문항 하나.

    N의 문항 셋이 핵심이다 — 기본 CAT이 고를 문항(수능 신호 없음)과 사전필터는 통과하지만 진실
    게이트가 막는 문항(검수 전)을 **θ에 가장 가깝게** 두고, 적격 문항은 θ에서 멀리 둔다. 재선택이
    수능 게이트를 빼먹으면 앞의 둘 중 하나가 이긴다.
    """
    c_anchor, c_next = uuid.uuid4(), uuid.uuid4()
    ids = {
        "anchor_problem": uuid.uuid4(),
        "next_no_signal": uuid.uuid4(),
        "next_unreviewed": uuid.uuid4(),
        "next_eligible": uuid.uuid4(),
        "c_anchor": c_anchor,
        "c_next": c_next,
    }
    rows: list[object] = [
        _concept(c_anchor, "anchor"),
        _concept(c_next, "next"),
        _edge(c_anchor, c_next),
        # 1차 선택: θ=0에 딱 맞는 수능 기출(권위 1.0 · 시그니처) — 우선순위 가중 최대.
        _problem(
            ids["anchor_problem"],
            3.0,
            exam_type=ExamType.수능,
            exam_authority_weight=1.0,
            irt_difficulty_b=0.0,
        ),
        _problem(ids["next_no_signal"], 3.0, signature_patterns=[]),  # 기본 CAT이라면 고를 문항
        _problem(ids["next_unreviewed"], 3.0, review_status=ReviewStatus.pending),
        _pc(ids["anchor_problem"], c_anchor),
        _pc(ids["next_no_signal"], c_next),
        _pc(ids["next_unreviewed"], c_next),
        _mastery(uid, c_anchor, 0.98),
    ]
    problems = [ids["anchor_problem"], ids["next_no_signal"], ids["next_unreviewed"]]
    if with_eligible_next:
        rows[6:6] = [_problem(ids["next_eligible"], 4.5)]
        rows.append(_pc(ids["next_eligible"], c_next))
        problems.append(ids["next_eligible"])
    return rows, ids, problems


def test_suneung_policy_advances_only_to_a_suneung_eligible_problem_on_live_pg() -> None:
    """(가) 해소 — 숙달한 개념의 문항 대신 다음 개념의 **수능 적격** 문항이 나간다(served)."""
    _require_pg()
    uid = uuid.uuid4()
    rows, ids, problems = _advance_fixture(uid, with_eligible_next=True)
    try:
        asyncio.run(_seed(rows))
        outcome = asyncio.run(_recommend(uid))
        assert outcome.problem_id == ids["next_eligible"], (
            f"다음 개념의 수능 적격 문항이 아니다: {outcome.problem_id} — "
            "재선택이 수능 게이트를 건너뛰었거나(수능 신호 없음·검수 전 문항) 재선택을 안 했다"
        )
        assert outcome.action is RecommendationAction.ADVANCE_NEXT
        assert outcome.target_concept == ids["c_next"]
        assert outcome.reason.concept_id == ids["c_anchor"]
        assert outcome.intent_resolution is IntentResolution.SERVED
        assert outcome.policy_version == "suneung_v2"
    finally:
        asyncio.run(_cleanup(problems, [ids["c_anchor"], ids["c_next"]], [uid]))


def test_suneung_policy_demotes_instead_of_leaving_the_mode_on_live_pg() -> None:
    """다음 개념에 수능 적격 문항이 없다 — 1차 문항을 내보내고 전진을 말하지 않는다.

    기본 CAT 풀이라면 `next_no_signal`이 전달됐을 상황이다. 수능 모드는 그 문항으로 가지 않는다.
    """
    _require_pg()
    uid = uuid.uuid4()
    rows, ids, problems = _advance_fixture(uid, with_eligible_next=False)
    try:
        asyncio.run(_seed(rows))
        outcome = asyncio.run(_recommend(uid))
        assert outcome.problem_id == ids["anchor_problem"]
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == ids["c_anchor"]
        assert outcome.intent_resolution is IntentResolution.TARGET_UNAVAILABLE
        assert outcome.reason.mastery == 0.98
    finally:
        asyncio.run(_cleanup(problems, [ids["c_anchor"], ids["c_next"]], [uid]))
