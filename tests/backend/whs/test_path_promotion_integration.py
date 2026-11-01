"""WH-S 구조 승격(`whs/path_promotion.py`) — 실 PostgreSQL 통합테스트 (P3-32).

`WHYMATH_RUN_INTEGRATION=1` + 살아있는 PG(마이그레이션 head 적용)에서만 실행한다(conftest 게이트가
CI 기본 skip). PG 미도달 시 graceful skip.

왜 이 테스트가 있는가
--------------------
hermetic 테스트(`test_path_promotion.py`)는 FakeSession으로 add/flush 배선만 본다 — 그 모듈
docstring이 "실 SQL·FK는 실 PG 통합 몫"이라고 적었지만 그 통합 테스트가 없었다. 그 사이
`problem_step.solution_path_id → solution_paths` 외래 키가 있는데 ORM에 `relationship()`이 없어
SQLAlchemy가 헤더와 단계의 INSERT 순서를 보장하지 않았고, 단계가 먼저 나가 **외래 키 위반으로
배치 전체가 롤백**됐다(P3-32 착수 세션이 로컬 PG 샌드박스에서 1,507경로 승격 시 실측). 운영 DB에서는
승격 가능한 경로가 한 번도 없어 드러나지 않았다.

검증하는 것: 단계가 있는 경로 1개를 실 PG에서 승격하면 ① 오류 없이 끝나고 ② 헤더 1행과 단계 행이
실제로 남고 ③ 단계가 그 헤더를 가리킨다. 수정 전 코드(헤더·단계를 한 flush에 섞음)에서는 ①이
`IntegrityError`(ForeignKeyViolation)로 RED다.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.db.models.problem import Problem as ProblemOrm
from whymath_backend.db.models.verified_solution import WhsSolutionGrade
from whymath_backend.schema.enums import Curriculum, SourceType, Subject
from whymath_backend.schema.problem import Problem
from whymath_backend.whs.path_promotion import promote_verified_solutions, solution_path_id_for
from whymath_backend.whs.solution_bank import bank_solution

pytestmark = pytest.mark.integration

# 전용 네임스페이스 UUID — 실 데이터와 겹치지 않는다(정리 대상).
_PID = uuid.UUID("bbbb0032-0000-0000-0000-000000000001")


async def _reachable() -> bool:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def _cleanup() -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            params = {"pid": str(_PID)}
            await conn.execute(text("DELETE FROM problem_step WHERE problem_id = :pid"), params)
            await conn.execute(text("DELETE FROM solution_paths WHERE problem_id = :pid"), params)
            await conn.execute(
                text("DELETE FROM verified_solutions WHERE problem_id = :pid"), params
            )
            await conn.execute(text("DELETE FROM problem WHERE problem_id = :pid"), params)
    finally:
        await engine.dispose()


async def _seed_and_promote() -> tuple[str, int, int, set[str]]:
    engine = create_async_engine(Settings().database_url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            session.add(
                ProblemOrm.from_schema(
                    Problem(
                        problem_id=_PID,
                        source_type=SourceType.자체생성,
                        curriculum_version=Curriculum.REVISION_2022,
                        valid_from_year=2027,
                        subject=Subject.미적분,
                        unit_codes=["CAL-DIFF"],
                        question_text="f(x) = 3x^2 + 24x 를 인수분해하시오",
                    )
                )
            )
            await session.flush()
            solution = await bank_solution(
                session,
                problem_id=_PID,
                grade=WhsSolutionGrade.VERIFIED,
                solution_path={
                    "conditions": [],
                    "answer": "3*(x + 8)*x",
                    "steps": ["3*x**2 + 24*x", "3*(x + 8)*(x)"],
                },
                strategy_tag="algebraic",
            )
            await session.commit()
            path_id = solution_path_id_for(solution.id)

        async with maker() as session:
            plan = await promote_verified_solutions(session)
            await session.commit()
        # 공유 DB에 다른 미승격 풀이가 있을 수 있어 '이 경로가 계획에 있다'만 단언한다.
        assert path_id in {p.path.solution_path_id for p in plan.planned}

        async with engine.connect() as conn:
            params = {"pid": str(_PID)}
            headers = (
                await conn.execute(
                    text("SELECT count(*) FROM solution_paths WHERE problem_id = :pid"), params
                )
            ).scalar_one()
            steps = (
                await conn.execute(
                    text("SELECT count(*) FROM problem_step WHERE problem_id = :pid"), params
                )
            ).scalar_one()
            refs = set(
                (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT solution_path_id FROM problem_step "
                            "WHERE problem_id = :pid"
                        ),
                        params,
                    )
                ).scalars()
            )
        return path_id, int(headers), int(steps), refs
    finally:
        await engine.dispose()


def test_promotion_with_steps_persists_header_before_steps() -> None:
    """단계 있는 경로 승격이 실 PG의 외래 키 순서를 지켜 헤더·단계를 모두 남긴다."""
    if not asyncio.run(_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    asyncio.run(_cleanup())
    try:
        path_id, headers, steps, refs = asyncio.run(_seed_and_promote())
        assert headers == 1
        assert steps == 2
        assert refs == {path_id}
    finally:
        asyncio.run(_cleanup())
