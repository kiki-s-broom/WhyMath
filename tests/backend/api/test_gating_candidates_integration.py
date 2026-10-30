"""게이팅 후보 조회의 검수 축 사전 축소 — 실 PostgreSQL 통합 (PB-27 · 기본 SKIP, `WHYMATH_RUN_INTEGRATION=1`).

hermetic 테스트(`test_gating_candidate_truncation.py`)는 SQL 문을 컴파일해 *조건이 있는지*만 본다.
여기서는 그 조건이 실제 행을 어떻게 거르는지를 실 PG로 확인한다.

  ① 승인 전수 진입 — 상한이 승인 행 수와 같을 때, DB의 승인 행이 **전부** 후보에 들어오고
     비승인 행은 하나도 들어오지 않는다. 사전 축소가 없으면 맨 앞에 정렬되도록 심은 비승인 행이
     상한 자리를 차지해 승인 행이 밀려난다(PB-25 ⑤ 승계 — 특정 은행·문항의 고정 탈락 방지).
  ② 격리 즉시 반영 — 승인 행을 격리(quarantined)하면 **다음 요청부터** 후보에서 빠지고, 해제
     (approved)하면 다시 들어온다. 캐시(ⓐ안)를 택하지 않은 이유를 동작으로 고정한다.

DB에 다른 테스트·적재가 남긴 행이 있어도 성립하도록, 기대값은 "이 DB의 승인 행 전체"를 별도
연결로 직접 세어 비교한다(심은 행만 보지 않는다). 정리는 이 테스트가 심은 행만 지운다.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from whymath_backend.api import gating as gating_module
from whymath_backend.config import Settings
from whymath_backend.db.models.problem import Problem
from whymath_backend.schema.enums import (
    Curriculum,
    ReviewStatus,
    SourceType,
    Subject,
    is_review_status_cleared,
)
from whymath_backend.schema.problem import Problem as ProblemSchema

pytestmark = pytest.mark.integration

# 비승인 행은 problem_id를 0으로 시작하게 심는다 — 적재 시각이 비어 있는 행끼리는 problem_id
# 오름차순이 동률을 가르므로, 사전 축소가 없으면 이 행들이 정렬 맨 앞에서 상한 자리를 먼저 차지한다.
_UNCLEARED_STATUSES: tuple[ReviewStatus | None, ...] = (
    None,
    None,
    ReviewStatus.pending,
    ReviewStatus.rejected,
    ReviewStatus.quarantined,
)
_UNCLEARED_IDS = [
    uuid.UUID(f"00000000-0000-4000-8000-{i:012d}") for i in range(len(_UNCLEARED_STATUSES))
]


def _url() -> str:
    return Settings(
        jwt_secret_key=SecretStr("integration-jwt-secret-0123456789abcdef")
    ).database_url


def _run(coro_fn: Any) -> Any:
    """새 엔진·새 세션으로 1회 실행 — 테스트마다 이벤트 루프가 달라도 연결을 공유하지 않는다."""

    async def _inner() -> Any:
        engine = create_async_engine(_url(), poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await coro_fn(session)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _pg_reachable() -> bool:
    async def _ping(session: AsyncSession) -> bool:
        await session.execute(text("SELECT count(*) FROM problem"))
        return True

    try:
        return bool(_run(_ping))
    except Exception:
        return False


def _row(problem_id: uuid.UUID, status: ReviewStatus | None) -> Problem:
    return Problem.from_schema(
        ProblemSchema(
            problem_id=problem_id,
            slug=f"it-pb27-{problem_id}",
            source_type=SourceType.자체생성,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.미적분,
            unit_codes=["CAL-INT-DEF"],
            question_text="PB-27 통합 테스트 문항",
            review_status=status,
        )
    )


def _seed(rows: list[Problem]) -> None:
    async def _go(session: AsyncSession) -> None:
        session.add_all(rows)
        await session.commit()

    _run(_go)


def _delete(ids: list[uuid.UUID]) -> None:
    async def _go(session: AsyncSession) -> None:
        await session.execute(delete(Problem).where(Problem.problem_id.in_(ids)))
        await session.commit()

    _run(_go)


def _cleared_ids_in_db() -> set[uuid.UUID]:
    """이 DB에서 권위가 통과시키는 행의 id 전체 — 후보 조회와 별개의 단순 질의로 센다."""
    cleared = [status.value for status in ReviewStatus if is_review_status_cleared(status)]

    async def _go(session: AsyncSession) -> set[uuid.UUID]:
        result = await session.execute(
            text("SELECT problem_id FROM problem WHERE review_status::text = ANY(:vals)"),
            {"vals": cleared},
        )
        return {row[0] for row in result}

    return set(_run(_go))


def _fetch_candidate_ids() -> list[uuid.UUID]:
    async def _go(session: AsyncSession) -> list[uuid.UUID]:
        candidates = await gating_module._fetch_candidates(session)  # type: ignore[arg-type]
        return [p.problem_id for p in candidates]

    return list(_run(_go))


def _set_status(problem_id: uuid.UUID, status: ReviewStatus) -> None:
    async def _go(session: AsyncSession) -> None:
        await session.execute(
            update(Problem).where(Problem.problem_id == problem_id).values(review_status=status)
        )
        await session.commit()

    _run(_go)


def _status_of(problem_id: uuid.UUID) -> ReviewStatus | None:
    async def _go(session: AsyncSession) -> ReviewStatus | None:
        result = await session.execute(
            select(Problem.review_status).where(Problem.problem_id == problem_id)
        )
        return result.scalar_one()

    return _run(_go)  # type: ignore[no-any-return]


@pytest.fixture
def seeded() -> Iterator[dict[str, list[uuid.UUID]]]:
    """비승인 5행(맨 앞 정렬용 id) + 승인 2행을 심고, 끝나면 심은 행만 지운다."""
    if not _pg_reachable():
        pytest.skip("PostgreSQL(problem 테이블)에 도달하지 못함")
    cleared_ids = [uuid.uuid4(), uuid.uuid4()]
    # 이전 실행이 중간에 죽어 남긴 고정 id 행을 먼저 지운다.
    _delete(_UNCLEARED_IDS + cleared_ids)
    rows = [_row(pid, st) for pid, st in zip(_UNCLEARED_IDS, _UNCLEARED_STATUSES, strict=True)]
    rows += [_row(pid, ReviewStatus.approved) for pid in cleared_ids]
    _seed(rows)
    try:
        yield {"uncleared": list(_UNCLEARED_IDS), "cleared": cleared_ids}
    finally:
        _delete(_UNCLEARED_IDS + cleared_ids)


def test_every_cleared_row_reaches_candidates_and_no_other_row_does(
    seeded: dict[str, list[uuid.UUID]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """① 상한 = 승인 행 수일 때 승인 행 전부가 후보이고, 비승인 행은 0건이다."""
    expected = _cleared_ids_in_db()
    assert set(seeded["cleared"]) <= expected, "심은 승인 행이 DB 집계에 없다 — 전제가 깨졌다"
    monkeypatch.setattr(gating_module, "_CANDIDATE_FETCH_LIMIT", len(expected))

    got = _fetch_candidate_ids()

    assert set(got) == expected, (
        f"승인 행 중 후보에서 빠진 것 {len(expected - set(got))}건 · "
        f"승인이 아닌데 후보에 든 것 {len(set(got) - expected)}건"
    )
    assert not set(seeded["uncleared"]) & set(got)


def test_quarantine_leaves_candidates_on_the_next_request(
    seeded: dict[str, list[uuid.UUID]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """② 격리하면 다음 요청부터 빠지고, 해제하면 다시 들어온다(캐시 없음 · 즉시 반영)."""
    target = seeded["cleared"][0]
    # 다른 행 수와 무관하게 절단이 끼어들지 않도록 상한을 넉넉히 둔다.
    monkeypatch.setattr(gating_module, "_CANDIDATE_FETCH_LIMIT", len(_cleared_ids_in_db()) + 10)

    assert target in _fetch_candidate_ids()

    _set_status(target, ReviewStatus.quarantined)
    assert _status_of(target) is ReviewStatus.quarantined
    assert target not in _fetch_candidate_ids()

    _set_status(target, ReviewStatus.approved)
    assert target in _fetch_candidate_ids()
