"""다중 풀이 뱅크 적재(`l3/multi_solution.bank_candidates`) — 실 PostgreSQL 통합테스트 (P3-32).

`WHYMATH_RUN_INTEGRATION=1` + 살아있는 PG(마이그레이션 head 적용)에서만 실행한다(conftest 게이트가
CI 기본 skip). PG 미도달 시 graceful skip.

`whs/path_promotion`과 같은 적재 형상(헤더 `solution_paths` + 대표 경로 단계 `problem_step`)이라
같은 결함을 갖고 있었다 — `problem_step.solution_path_id` 외래 키에 ORM `relationship()`이 없어
헤더와 단계가 한 flush에 섞이면 INSERT 순서가 보장되지 않는다. hermetic 테스트(FakeSession)는
INSERT 순서를 볼 수 없으므로 실 PG에서만 잡힌다.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.db.models.problem import Problem as ProblemOrm
from whymath_backend.l3.multi_solution import (
    MultiSolutionReport,
    SeedProblem,
    bank_candidates,
    evaluate_response,
)
from whymath_backend.schema.enums import Curriculum, SourceType, Subject
from whymath_backend.schema.problem import Problem

pytestmark = pytest.mark.integration

# 전용 네임스페이스 UUID — 실 데이터와 겹치지 않는다(정리 대상).
_PID = uuid.UUID("bbbb0032-0000-0000-0000-000000000002")
_NOW = datetime(2026, 11, 1, 0, 0, 0, tzinfo=UTC)


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


async def _bank_and_count() -> tuple[int, int, int]:
    seed = SeedProblem(
        problem_id=_PID,
        question_text="일차방정식 2*x = 6 을 푸시오.",
        conditions=("2*x = 6",),
        answer_map={"x": "3"},
    )
    report = MultiSolutionReport()
    candidates = evaluate_response(
        seed,
        {
            "solutions": [
                {
                    "approach": "algebraic",
                    "key_insight": "식을 정리한다",
                    "steps": ["(x) - (3)", "(x) - (3)"],
                    "final_answer": "3",
                    "educational_value": "기본 절차",
                    "difficulty": "easy",
                    "elegance": 3,
                }
            ],
            "comparison": "비교",
        },
        now=_NOW,
        report=report,
    )
    assert len(candidates) == 1, "검증 통과 후보가 1건이어야 적재 순서를 시험할 수 있다"
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
                        question_text="일차방정식 2*x = 6 을 푸시오.",
                    )
                )
            )
            await session.flush()
            await bank_candidates(session, candidates, report=report)
            await session.commit()
        async with engine.connect() as conn:
            params = {"pid": str(_PID)}

            async def count(table: str) -> int:
                result = await conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE problem_id = :pid"), params
                )
                return int(result.scalar_one())

            return (
                await count("verified_solutions"),
                await count("solution_paths"),
                await count("problem_step"),
            )
    finally:
        await engine.dispose()


def test_bank_candidates_persists_header_before_steps() -> None:
    """후보 1건 적재가 실 PG의 외래 키 순서를 지켜 3좌석을 모두 남긴다."""
    if not asyncio.run(_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    asyncio.run(_cleanup())
    try:
        solutions, headers, steps = asyncio.run(_bank_and_count())
        assert (solutions, headers, steps) == (1, 1, 2)
    finally:
        asyncio.run(_cleanup())
