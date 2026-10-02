"""EOS-31 수능 출제 범위 — **실 PG**에서 게이트(파이썬)와 SQL 사전필터가 같은 정의를 쓰는가.

단위 테스트는 두 곳을 따로 본다 — 게이트는 `tests/backend/l6/suneung/`, 사전필터는 SQL을 컴파일한 문자열만.
**같은 입력에서 두 판정이 같은 문항을 고르는가**와 **사전필터가 실제로 실행돼 후보 풀 소멸을 막는가**는
실 PG에서만 드러난다(WHERE 절이 평가돼야 한다). 이 파일이 그 공백을 메운다.

① 일치(④ "같은 정의") — 성취기준 조합 매트릭스를 심고, SQL 절이 고른 집합 · 파이썬 `suneung_scope_verdict`가
   `IN_SCOPE`로 본 집합 · 기대 집합(이 파일에 손으로 적은 판정)을 **셋 다** 비교한다. 두 구현이 같은 방향으로
   틀려도 기대 집합이 잡고, 기대가 틀려도 두 구현이 잡는다. 매트릭스에는 정반대 대조군이 모두 있다.
② 후보 풀 소멸 방지 — 풀은 θ 근방 순 50개로 잘린다. 범위 밖 문항 50개가 θ에 더 가깝고 범위 안 문항은 멀리
   있을 때, 사전필터가 범위를 모르면 풀이 범위 밖으로만 차서 게이트가 전부 탈락시킨다(후보 소멸). 같은 시나리오를
   **범위 절을 끈 채** 한 번 더 돌려 실제로 소멸함을 보인다 — 소멸이 일어나지 않는 시나리오였다면 이 테스트는
   사전필터가 없어도 통과하는 위장이다(CLAUDE.md "보호 장치를 실패 주입 없이 선언 금지").

전제(기존 수능 통합 테스트와 같다): DB에 이 파일이 심지 않은 수능 적격 문항이 없다. CI의 backend-migrations
잡은 마이그레이션만 적용한 DB에서 시작하고, 각 테스트는 심은 행을 지운다.

실행: `WHYMATH_RUN_INTEGRATION=1 pytest -m integration tests/backend/api/test_eos31_suneung_scope_integration.py`
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text, true
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.api import _next_problem_policy as policy_module
from whymath_backend.api._next_problem_policy import (
    SuneungRecommendationPolicy,
    suneung_scope_clause,
)
from whymath_backend.api.gating import _fetch_achievement_codes
from whymath_backend.config import Settings
from whymath_backend.db.models.atom_node import ATOM_REVIEW_STATUS_AI_ESTIMATED, AtomNode
from whymath_backend.db.models.concept import Concept, ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.learner_state import get_state
from whymath_backend.l2.next_problem_selection import CANDIDATE_POOL_SIZE
from whymath_backend.l2.recommendation_contract import LearningContext
from whymath_backend.l6.suneung import ScopeVerdict, suneung_scope_verdict
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.concept import ProblemConcept as ProblemConceptSchema
from whymath_backend.schema.enums import (
    ConceptLevel,
    ConceptRole,
    Curriculum,
    ExamType,
    Persona,
    ReviewStatus,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema

pytestmark = pytest.mark.integration

_SECRET = "eos31-suneung-scope-jwt-secret-0123456789"


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


class _Seed:
    """심은 행의 id 모음 — 정리가 FK 순서로 지운다."""

    def __init__(self) -> None:
        self.rows: list[object] = []
        self.problem_ids: list[uuid.UUID] = []
        self.concept_ids: list[uuid.UUID] = []
        self.atom_codes: list[str] = []

    def concept_with_codes(self, tag: str, standard_codes: list[str]) -> uuid.UUID:
        """개념 1개 + 같은 `code`의 원자 노드(성취기준 코드 `standard_codes`)를 심는다."""
        cid = uuid.uuid4()
        code = f"UC-EOS31-{tag}-{cid.hex[:8]}"
        self.rows.append(
            Concept.from_schema(
                ConceptSchema(
                    concept_id=cid, code=code, name_ko=f"범위 {tag}", level=ConceptLevel.세부개념
                )
            )
        )
        self.rows.append(
            AtomNode(
                code=code,
                name_ko=f"범위 {tag}",
                level="세부개념",
                standard_codes=standard_codes,
                review_status=ATOM_REVIEW_STATUS_AI_ESTIMATED,
            )
        )
        self.concept_ids.append(cid)
        self.atom_codes.append(code)
        return cid

    def problem(
        self,
        concept_ids: list[uuid.UUID],
        *,
        curriculum: Curriculum = Curriculum.REVISION_2022,
        irt_b: float | None = None,
        exam: bool = True,
    ) -> uuid.UUID:
        """수능 신호(기출 유형)를 가진 승인 문항 — 범위 외 신호는 전부 적격이라 범위만 변인이다."""
        pid = uuid.uuid4()
        kwargs: dict[str, Any] = {
            "problem_id": pid,
            "source_type": SourceType.자체생성,
            "review_status": ReviewStatus.approved,
            "curriculum_version": curriculum,
            "valid_from_year": 2022 if curriculum is Curriculum.REVISION_2022 else 2015,
            "subject": Subject.공통,
            "unit_codes": ["U-EOS31"],
            "difficulty_overall": 3.0,
            "answer": "EOS31_SENTINEL",
        }
        if exam:
            kwargs["exam_type"] = ExamType.수능
            kwargs["exam_authority_weight"] = 1.0
        if irt_b is not None:
            kwargs["irt_difficulty_b"] = irt_b
        self.rows.append(Problem.from_schema(ProblemSchema(**kwargs)))
        for cid in concept_ids:
            self.rows.append(
                ProblemConcept.from_schema(
                    ProblemConceptSchema(problem_id=pid, concept_id=cid, role=ConceptRole.PRIMARY)
                )
            )
        self.problem_ids.append(pid)
        return pid

    async def apply(self) -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                for row in self.rows:
                    session.add(row)
                    await session.flush()  # FK 순서를 목록 순서 그대로 지킨다
                await session.commit()
        finally:
            await engine.dispose()

    async def cleanup(self) -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                pids = [str(p) for p in self.problem_ids]
                await conn.execute(
                    text("DELETE FROM problem_concept WHERE problem_id = ANY(:ids)"), {"ids": pids}
                )
                await conn.execute(
                    text("DELETE FROM problem WHERE problem_id = ANY(:ids)"), {"ids": pids}
                )
                await conn.execute(
                    text("DELETE FROM atom_node WHERE code = ANY(:codes)"),
                    {"codes": self.atom_codes},
                )
                await conn.execute(
                    text("DELETE FROM concept WHERE concept_id = ANY(:ids)"),
                    {"ids": [str(c) for c in self.concept_ids]},
                )
        finally:
            await engine.dispose()


# ──────────────────────────────────────────────────────────────────────────
# ① SQL 절 = 파이썬 게이트 — 같은 입력에서 같은 문항 집합
# ──────────────────────────────────────────────────────────────────────────
async def _sql_and_python_in_scope(
    problem_ids: list[uuid.UUID],
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            sql_rows = await session.execute(
                select(Problem.problem_id).where(
                    Problem.problem_id.in_(problem_ids), suneung_scope_clause()
                )
            )
            by_sql = {row[0] for row in sql_rows.all()}
            problems = [
                row.to_schema()
                for row in (
                    await session.execute(
                        select(Problem).where(Problem.problem_id.in_(problem_ids))
                    )
                )
                .scalars()
                .all()
            ]
            codes = await _fetch_achievement_codes(session, [p.problem_id for p in problems])
            by_python: set[uuid.UUID] = set()
            for problem in problems:
                problem.achievement_standard_codes = sorted(codes.get(problem.problem_id, ()))
                if suneung_scope_verdict(problem) is ScopeVerdict.IN_SCOPE:
                    by_python.add(problem.problem_id)
            return by_sql, by_python
    finally:
        await engine.dispose()


def test_sql_clause_and_python_verdict_select_the_same_problems_on_live_pg() -> None:
    """성취기준 조합 매트릭스 — 셋(SQL · 파이썬 · 손으로 적은 기대)이 같은 집합을 고른다."""
    _require_pg()
    seed = _Seed()
    c_dae = seed.concept_with_codes("dae", ["[12대수01-01]"])
    c_mi = seed.concept_with_codes("mi", ["[12미적02-03]"])
    c_hwak = seed.concept_with_codes("hwak", ["[12확통01-02]"])
    c_mid = seed.concept_with_codes("mid", ["[9수02-01]"])
    c_common = seed.concept_with_codes("common", ["[10공수1-01-01]"])
    c_geo = seed.concept_with_codes("geo", ["[12기하02-05]"])
    c_bridge = seed.concept_with_codes("bridge", ["[9수02-01]", "[12대수01-01]"])
    c_empty = seed.concept_with_codes("empty", [])  # 원자 노드는 있으나 성취기준 코드가 비었다
    c_truncated = seed.concept_with_codes("trunc", ["[12대"])  # 접두어가 잘렸다
    c_midstring = seed.concept_with_codes("midstr", ["X[12대수01-01]"])  # 접두어가 중간에만 있다

    expected_in = {
        "대수": seed.problem([c_dae]),
        "미적분": seed.problem([c_mi]),
        "확통": seed.problem([c_hwak]),
        "중학교+대수 브리지": seed.problem([c_bridge]),
        "두 개념(밖+안)": seed.problem([c_mid, c_mi]),
    }
    expected_out = {
        "중학교": seed.problem([c_mid]),
        "공통수학": seed.problem([c_common]),
        "기하": seed.problem([c_geo]),
        "코드 없는 원자": seed.problem([c_empty]),
        "개념 연결 없음": seed.problem([]),
        "접두어 잘림": seed.problem([c_truncated]),
        "접두어가 중간에": seed.problem([c_midstring]),
        "같은 접두어·다른 개정": seed.problem([c_mi], curriculum=Curriculum.REVISION_2015),
    }
    try:
        asyncio.run(seed.apply())
        by_sql, by_python = asyncio.run(_sql_and_python_in_scope(seed.problem_ids))
        want = set(expected_in.values())
        assert by_sql == want, _diff("SQL", by_sql, want, {**expected_in, **expected_out})
        assert by_python == want, _diff("파이썬", by_python, want, {**expected_in, **expected_out})
        assert by_sql == by_python  # 두 구현이 같은 집합 — 같은 정의(④)
        # 대조군이 실재한다 — 전부 안이거나 전부 밖인 판정기를 통과시키지 않는다.
        assert want and set(expected_out.values())
    finally:
        asyncio.run(seed.cleanup())


def _diff(who: str, got: set[uuid.UUID], want: set[uuid.UUID], names: dict[str, uuid.UUID]) -> str:
    by_id = {v: k for k, v in names.items()}
    extra = sorted(by_id[p] for p in got - want)
    missing = sorted(by_id[p] for p in want - got)
    return f"{who} 판정이 기대와 다르다 — 잘못 포함: {extra} · 잘못 제외: {missing}"


# ──────────────────────────────────────────────────────────────────────────
# ② 후보 풀 소멸 방지 — 범위 밖 문항이 풀을 채워도 범위 안 문항이 나간다
# ──────────────────────────────────────────────────────────────────────────
def _starved_pool_seed() -> tuple[_Seed, uuid.UUID]:
    """θ=0에 더 가까운 범위 밖 문항 `CANDIDATE_POOL_SIZE`개 + 멀리 있는 범위 안 문항 1개."""
    seed = _Seed()
    c_out = seed.concept_with_codes("pool-out", ["[9수02-01]"])
    c_in = seed.concept_with_codes("pool-in", ["[12대수01-01]"])
    for _ in range(CANDIDATE_POOL_SIZE):
        seed.problem([c_out], irt_b=0.0)  # θ 근방 — 풀을 채운다
    target = seed.problem([c_in], irt_b=2.5)  # θ에서 멀다 — 사전필터가 범위를 모르면 풀 밖
    return seed, target


async def _recommend(uid: uuid.UUID) -> Any:
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            learner_state = await get_state(session, uid)
            policy = SuneungRecommendationPolicy(session, persona=Persona.A_일반고고3)
            return await policy(learner_state, LearningContext(mode="suneung"))
    finally:
        await engine.dispose()


def test_out_of_scope_items_do_not_starve_the_candidate_pool_on_live_pg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_pg()
    seed, target = _starved_pool_seed()
    uid = uuid.uuid4()
    try:
        asyncio.run(seed.apply())

        outcome = asyncio.run(_recommend(uid))
        assert outcome.problem_id == target, (
            "범위 안 문항이 후보 풀에 못 들었다 — SQL 사전필터가 출제 범위를 모르거나 무력하다(EOS-31). "
            f"받은 문항: {outcome.problem_id}"
        )

        # 대조군 — 범위 절을 끄면 같은 시나리오에서 후보가 **실제로 소멸**한다. 소멸하지 않는다면 이
        # 시나리오는 사전필터와 무관하게 통과하는 위장이다.
        monkeypatch.setattr(policy_module, "suneung_scope_clause", lambda: true())
        starved = asyncio.run(_recommend(uid))
        assert (
            starved.problem_id is None
        ), "범위 절을 꺼도 후보가 나온다 — 이 시나리오가 풀 소멸을 재현하지 못한다(변별력 상실)."
        assert starved.candidate_zero_reason == "all_candidates_gated_ineligible"
    finally:
        asyncio.run(seed.cleanup())
