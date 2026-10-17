"""문항 난이도 보정 루프 도달 관측 — 카운터 델타 변별력 통합테스트 (실 PG, 기본 SKIP).

PB-10 acceptance①: `collect_counts`의 SQL이 **보정 배치와 같은 필터**로 같은 문항 집합을 세는지 실DB로
실측한다. 모의(mock) 카운트로는 이 SQL을 검증할 수 없다 — 응답 필터(`is_correct`·`user_id`·`problem_id`
NOT NULL)나 자격 임계 조인이 어긋나면 "자격 문항"이 실제 배치가 보는 문항과 달라지는데, 그것은 단위
테스트에서 보이지 않는다.

**절대값을 어디서도 assert하지 않는다** — 테스트 DB에 기존 행이 있을 수 있어(운영 DB 5433 등) 절대 행 수를
가정하는 것 자체가 위험하다. 오직 `삽입 전/후/UPDATE 후/정리 후`의 **델타**만 비교한다. 성공과 실패가 같은
값을 내면 검증이 아니다(CLAUDE.md 변별력 원칙) — 그래서 장면 안에 **세지 말아야 할 행**(미채점 응답)과
**자격 미달 문항**(응답 4회)을 일부러 섞어, 필터가 빠지면 델타가 어긋나도록 설계했다.

`WHYMATH_RUN_INTEGRATION=1` + 살아있는 PG에서만 실행. `test_problem_irt_b_integration.py`의 접속 판정·
자체 엔진·dispose 패턴을 미러링한다.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from whymath_backend.config import Settings
from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.user import UserProfile
from whymath_backend.harness.item_calibration_reach_report import (
    MIN_RESPONSES_FOR_CALIBRATION,
    CalibrationReachCounts,
    collect_counts,
)
from whymath_backend.schema.enums import Curriculum, Persona, Role, SourceType, Subject
from whymath_backend.schema.problem import Problem as ProblemSchema

pytestmark = pytest.mark.integration

_FLOOR = MIN_RESPONSES_FOR_CALIBRATION


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr("integration-jwt-secret-0123456789abcdef"))


async def _pg_reachable() -> bool:
    from sqlalchemy import text

    engine = create_async_engine(_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


def _problem(pid: uuid.UUID, *, b: float | None) -> Problem:
    return Problem.from_schema(
        ProblemSchema(
            problem_id=pid,
            source_type=SourceType.자체생성,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.공통,
            unit_codes=[f"U-{pid.hex[:8]}"],
            irt_difficulty_b=b,
        )
    )


def _delta(after: CalibrationReachCounts, before: CalibrationReachCounts) -> dict[str, int]:
    return {
        name: getattr(after, name) - getattr(before, name)
        for name in CalibrationReachCounts.__dataclass_fields__
    }


def test_counters_move_by_exact_deltas_and_ignore_ungraded_and_below_floor() -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    # 장면: 사용자 5명(= 자격 임계 수) · 문항 4개.
    users = [uuid.uuid4() for _ in range(_FLOOR)]
    p_unfilled, p_filled, p_below, p_ungraded = (uuid.uuid4() for _ in range(4))
    all_problems = (p_unfilled, p_filled, p_below, p_ungraded)
    # 배치 입력에서 제외돼야 하는 응답 2건 — 사용자 NULL(자격 미달 문항에 얹어 임계를 넘기려 한다)·
    # 문항 NULL(어느 문항에도 속하지 않는다). 필터가 빠지면 자격 문항 수·응답 수가 어긋난다.
    null_user_attempt = uuid.uuid4()
    null_problem_attempt = uuid.uuid4()

    def _attempts(pid: uuid.UUID, n: int, *, graded: bool) -> list[ProblemAttempt]:
        return [
            ProblemAttempt(
                attempt_id=uuid.uuid4(),
                user_id=users[i],
                problem_id=pid,
                is_correct=(i % 2 == 0) if graded else None,
            )
            for i in range(n)
        ]

    async def _measure() -> CalibrationReachCounts:
        engine = create_async_engine(_settings().database_url, poolclass=NullPool)
        try:
            sm = async_sessionmaker(engine, expire_on_commit=False)
            async with sm() as session:
                return await collect_counts(session)
        finally:
            await engine.dispose()

    async def _insert_scene() -> None:
        engine = create_async_engine(_settings().database_url, poolclass=NullPool)
        try:
            sm = async_sessionmaker(engine, expire_on_commit=False)
            async with sm() as session:
                session.add_all(
                    UserProfile(user_id=u, persona_primary=Persona.A_일반고고3, role=Role.STUDENT)
                    for u in users
                )
                # 문항은 FK 대상이라 시도보다 먼저 flush한다.
                session.add_all(
                    [
                        _problem(p_unfilled, b=None),
                        _problem(p_filled, b=0.3),
                        _problem(p_below, b=None),
                        _problem(p_ungraded, b=None),
                    ]
                )
                await session.flush()
                attempts: Sequence[ProblemAttempt] = [
                    *_attempts(p_unfilled, _FLOOR, graded=True),  # 자격 · b NULL
                    *_attempts(p_filled, _FLOOR, graded=True),  # 자격 · b 채움
                    *_attempts(p_below, _FLOOR - 1, graded=True),  # 자격 미달(4회)
                    *_attempts(p_ungraded, _FLOOR, graded=False),  # 미채점 — 세면 안 된다
                    # 사용자 NULL 1건을 p_below에 얹으면 필터가 없을 때 4→5회로 임계를 넘는다.
                    ProblemAttempt(
                        attempt_id=null_user_attempt,
                        user_id=None,
                        problem_id=p_below,
                        is_correct=True,
                    ),
                    ProblemAttempt(
                        attempt_id=null_problem_attempt,
                        user_id=users[0],
                        problem_id=None,
                        is_correct=True,
                    ),
                ]
                session.add_all(attempts)
                await session.commit()
        finally:
            await engine.dispose()

    async def _simulate_batch_ran() -> None:
        """배치가 돈 뒤 상태 — 자격 문항의 b를 채운다(calibrate가 쓰는 update().values() 경로)."""
        engine = create_async_engine(_settings().database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    update(Problem)
                    .where(Problem.problem_id == p_unfilled)
                    .values(irt_difficulty_b=-0.7)
                )
        finally:
            await engine.dispose()

    async def _cleanup() -> None:
        engine = create_async_engine(_settings().database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    delete(ProblemAttempt).where(
                        ProblemAttempt.problem_id.in_(all_problems)
                        | ProblemAttempt.attempt_id.in_((null_user_attempt, null_problem_attempt))
                    )
                )
                await conn.execute(delete(Problem).where(Problem.problem_id.in_(all_problems)))
                await conn.execute(delete(UserProfile).where(UserProfile.user_id.in_(users)))
        finally:
            await engine.dispose()

    async def _scenario() -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
        before = await _measure()
        await _insert_scene()
        after_insert = await _measure()
        await _simulate_batch_ran()
        after_batch = await _measure()
        return (
            _delta(after_insert, before),
            _delta(after_batch, before),
            _delta(after_batch, after_insert),
        )

    try:
        inserted, batched, batch_step = asyncio.run(_scenario())
    finally:
        asyncio.run(_cleanup())

    # ① 삽입 직후 — 배치 전. 자격 문항 2개(미채움 1·채움 1) · 미달 1 · 미채점 문항은 응답 집합 밖.
    assert inserted["problem_total"] == 4
    assert inserted["irt_b_filled"] == 1
    assert inserted["graded_attempts"] == _FLOOR * 2 + (_FLOOR - 1)  # 미채점 5건은 세지 않는다
    assert inserted["distinct_students"] == len(users)
    assert inserted["items_with_responses"] == 3  # unfilled·filled·below (ungraded 제외)
    assert inserted["eligible_items"] == 2  # below(4회)는 임계 미달
    assert inserted["eligible_unfilled"] == 1  # filled는 이미 채워져 있다
    # ② 배치가 돈 뒤 — 미채움 자격 문항이 사라지고 채움이 하나 늘 뿐, 응답 집합은 그대로다.
    assert batch_step["eligible_unfilled"] == -1
    assert batch_step["irt_b_filled"] == 1
    assert batch_step["eligible_items"] == 0
    assert batch_step["graded_attempts"] == 0
    assert batched["eligible_unfilled"] == 0  # 장면 기준 전부 따라잡힘
