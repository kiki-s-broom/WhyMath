"""주간 KPI 집계기(OPS-56) — 실 PG 왕복 (기본 SKIP, `test_me_integration.py` 동형 가드).

`collect()`가 실제로 `review_timer_event`·`generation_log` 테이블을 읽어 measured 값을
내는지, 그리고 창 밖 행이 섞이지 않는지를 실 데이터 삽입 전/후로 대조한다(CLAUDE.md
"변별력 없는 검증 스텝 금지" — 0건 스킵으로 위장 통과하지 않는다). CI의 "backend —
마이그레이션·통합 (실 PG)" 잡이 `pytest -m integration`으로 실제로 돌린다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
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


# ── EOS-198 ①② — 같은 입력이면 DB 경로와 파일 입력 모드가 같은 레코드를 낸다(실 PG) ──
# 위 두 테스트와 섞이지 않게 다른 과거 창을 쓴다(삽입 전 창이 비어 있음을 먼저 단언한다).
_EQ_WEEK_START = datetime(2026, 4, 6, tzinfo=UTC)
_EQ_WEEK_END = datetime(2026, 4, 13, tzinfo=UTC)
_EQ_INSIDE = datetime(2026, 4, 9, tzinfo=UTC)


class TestDbPathEqualsFileInputMode:
    async def test_same_rows_same_record_including_batch_cost_join(self, tmp_path: Path) -> None:
        """DB에 넣은 행과 같은 행을 JSONL로 써서 파일 모드로 돌리면 KPI가 같다.

        배치 저작 행(problem_id=None)의 비용이 cu_slug로 조인되는지도 실 DB에서 본다(G-B) —
        종전 DB 경로라면 여기서 unit_cost_krw가 미측정이었다.
        """
        if not await _pg_reachable():
            pytest.skip("실 PG 도달 불가 — CI의 '실 PG' 잡에서만 실행")
        from whymath_backend.db.models.provenance import GenerationLog as OrmGenerationLog
        from whymath_backend.ops.weekly_metrics_report import collect_from_files
        from whymath_backend.schema.provenance import GenerationLog as SchemaGenerationLog

        slug = f"eos198-eq-{uuid.uuid4().hex[:8]}"
        log = SchemaGenerationLog(
            model_name="deepseek/deepseek-v4.1-flash",
            input_tokens=3000,
            output_tokens=1500,
            cost_usd=0.0015,
            success=True,
            generated_at=_EQ_INSIDE,
            cu_slug=slug,
        )
        try:
            before = await collect(
                week_start=_EQ_WEEK_START,
                week_end=_EQ_WEEK_END,
                generated_at=datetime.now(UTC),
                krw_per_usd=1540,
            )
            assert before.kpis["hit_seconds"].measured is False  # 대조 — 창이 비어 있다

            await _insert_review_pair(slug, 95_000, _EQ_INSIDE)
            engine = create_async_engine(get_settings().database_url)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    session.add(OrmGenerationLog.from_schema(log))
                    await session.commit()
            finally:
                await engine.dispose()

            db_record = await collect(
                week_start=_EQ_WEEK_START,
                week_end=_EQ_WEEK_END,
                generated_at=_EQ_WEEK_END,
                krw_per_usd=1540,
            )

            # 같은 행을 파일로 — 이벤트는 DB가 읽어 준 그대로(recorded_at 포함) 덤프한다.
            engine = create_async_engine(get_settings().database_url)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    rows = (
                        (
                            await session.execute(
                                sa.select(OrmReviewTimerEvent).where(
                                    OrmReviewTimerEvent.cu_slug == slug
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    events = [r.to_schema() for r in rows]
            finally:
                await engine.dispose()
            ev_path = tmp_path / "events.jsonl"
            ev_path.write_text("".join(e.model_dump_json() + "\n" for e in events), "utf-8")
            gl_path = tmp_path / "cu.genlog.jsonl"
            gl_path.write_text(log.model_dump_json() + "\n", "utf-8")
            file_record, _ = collect_from_files(
                events_paths=[ev_path],
                genlog_paths=[gl_path],
                week_start=_EQ_WEEK_START,
                week_end=_EQ_WEEK_END,
                generated_at=_EQ_WEEK_END,
                krw_per_usd=1540,
            )

            assert db_record.kpis["unit_cost_krw"].measured is True
            assert db_record.to_json() == file_record.to_json()
        finally:
            engine = create_async_engine(get_settings().database_url)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    await session.execute(
                        text("DELETE FROM review_timer_event WHERE cu_slug = :slug"), {"slug": slug}
                    )
                    await session.execute(
                        text("DELETE FROM generation_log WHERE cu_slug = :slug"), {"slug": slug}
                    )
                    await session.commit()
            finally:
                await engine.dispose()
