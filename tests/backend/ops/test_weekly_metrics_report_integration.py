"""주간 KPI 집계기(OPS-56) — 실 PG 왕복 (기본 SKIP, `test_me_integration.py` 동형 가드).

`collect()`가 실제로 `review_timer_event`·`generation_log` 테이블을 읽어 measured 값을
내는지, 그리고 창 밖 행이 섞이지 않는지를 실 데이터 삽입 전/후로 대조한다(CLAUDE.md
"변별력 없는 검증 스텝 금지" — 0건 스킵으로 위장 통과하지 않는다). CI의 "backend —
마이그레이션·통합 (실 PG)" 잡이 `pytest -m integration`으로 실제로 돌린다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.config import get_settings
from whymath_backend.db.models.review_timer_event import ReviewTimerEvent as OrmReviewTimerEvent
from whymath_backend.harness.review_timer import finish_review, start_review
from whymath_backend.ops.weekly_metrics_report import KPI_NAMES, collect

pytestmark = pytest.mark.integration

# 집계 창 — 다른 테스트의 "지금" 데이터와 섞이지 않게 과거 고정 창을 쓴다.
_WEEK_START = datetime(2026, 3, 2, tzinfo=UTC)
_WEEK_END = datetime(2026, 3, 9, tzinfo=UTC)
_INSIDE_WINDOW = datetime(2026, 3, 5, tzinfo=UTC)
_OUTSIDE_WINDOW = datetime(2026, 2, 1, tzinfo=UTC)  # 창 밖 — 섞이면 안 된다


async def _pg_reachable() -> bool:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def _insert_review_pair(slug: str, elapsed_ms: int, occurred_at: datetime) -> None:
    started = start_review(cu_slug=slug, reviewer_id="kiki-integration", occurred_at=occurred_at)
    finished = finish_review(
        review_session_id=started.review_session_id,
        cu_slug=slug,
        reviewer_id="kiki-integration",
        verdict="approved",  # type: ignore[arg-type]
        elapsed_ms=elapsed_ms,
        occurred_at=occurred_at,
    )
    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(
                [
                    OrmReviewTimerEvent.from_schema(started),
                    OrmReviewTimerEvent.from_schema(finished),
                ]
            )
            # recorded_at은 server_default now() — 집계 창은 recorded_at 기준이라
            # 삽입 시각을 창 안으로 강제 갱신해야 "창 밖 고정일" 픽스처가 의미를 갖는다.
            await session.flush()
            await session.execute(
                text(
                    "UPDATE review_timer_event SET recorded_at = :ts "
                    "WHERE review_session_id = :sid"
                ),
                {"ts": occurred_at, "sid": started.review_session_id},
            )
            await session.commit()
    finally:
        await engine.dispose()


class TestCollectRealDatabaseRoundTrip:
    async def test_no_rows_in_window_is_unmeasured_not_zero(self) -> None:
        """[변별력 대조군] 창에 행이 하나도 없으면 measured=False — 다음 테스트의 대조."""
        if not await _pg_reachable():
            pytest.skip("실 PG 도달 불가 — CI의 '실 PG' 잡에서만 실행")
        record = await collect(
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=datetime.now(UTC),
            krw_per_usd=1400,
        )
        assert set(record.kpis) == set(KPI_NAMES)
        assert record.kpis["hit_seconds"].measured is False

    async def test_row_inside_window_is_measured_row_outside_is_excluded(self) -> None:
        """[변별력 핵심] 창 안 행은 잡히고 창 밖 행은 안 잡힌다 — 전/후 대조."""
        if not await _pg_reachable():
            pytest.skip("실 PG 도달 불가 — CI의 '실 PG' 잡에서만 실행")

        slug_in = f"ops56-in-{uuid.uuid4().hex[:8]}"
        slug_out = f"ops56-out-{uuid.uuid4().hex[:8]}"
        try:
            before = await collect(
                week_start=_WEEK_START,
                week_end=_WEEK_END,
                generated_at=datetime.now(UTC),
                krw_per_usd=1400,
            )
            assert before.kpis["hit_seconds"].measured is False  # 삽입 전 — 미측정

            await _insert_review_pair(slug_in, 90_000, _INSIDE_WINDOW)
            await _insert_review_pair(slug_out, 30_000, _OUTSIDE_WINDOW)

            after = await collect(
                week_start=_WEEK_START,
                week_end=_WEEK_END,
                generated_at=datetime.now(UTC),
                krw_per_usd=1400,
            )
            assert after.kpis["hit_seconds"].measured is True
            # 창 밖 30초 행이 섞였다면 중앙값이 달라진다 — 90초 단독이어야 한다.
            assert after.kpis["hit_seconds"].value == pytest.approx(90.0)
        finally:
            # 정리 — 다른 테스트·다음 실행에 잔재를 남기지 않는다.
            engine = create_async_engine(get_settings().database_url)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    for slug in (slug_in, slug_out):
                        await session.execute(
                            text("DELETE FROM review_timer_event WHERE cu_slug = :slug"),
                            {"slug": slug},
                        )
                    await session.commit()
            finally:
                await engine.dispose()
