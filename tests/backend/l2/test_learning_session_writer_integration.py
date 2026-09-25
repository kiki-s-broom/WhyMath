"""EOS-131 학습 세션 writer — 실 PostgreSQL 통합 테스트(기본 SKIP · `WHYMATH_RUN_INTEGRATION=1`).

hermetic(`test_learning_session_writer.py`)이 계약 모양을 본다면, 이 파일은 **실 DB에서 규칙이
실제로 성립하는지**를 본다:
  ② 유휴 규칙 — 30분 이내는 잇고, 정확히 30분은 잇고(경계 포함), 30분+1초는 직전 세션을 *마지막
     활동 시각*으로 닫고 새로 연다. 조회 시점 확정(`close_idle_sessions`)이 다시 오지 않는 학생의
     세션을 닫고, 유휴 이내 세션·writer 이전 행은 건드리지 않는다.
  ③ 점수 NULL — writer가 만든 행의 `focus_score`·`engagement_score`는 NULL이다.
  ⑩ 동시성 — 같은 학생의 요청 2건을 **실제로 동시에**(별도 연결·별도 트랜잭션) 넣어도 열린 세션은
     1개다. 부분 유니크 인덱스가 실제로 걸려 있는지도 직접 주입으로 확인한다.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.db.models.activity import LearningSession
from whymath_backend.db.models.user import UserProfile
from whymath_backend.l2 import learning_session_writer as writer
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

pytestmark = pytest.mark.integration


async def _pg_reachable() -> bool:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    if not await _pg_reachable():
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    eng = create_async_engine(Settings().database_url)
    yield eng
    await eng.dispose()


@pytest.fixture
async def user_id(engine: AsyncEngine) -> AsyncIterator[uuid.UUID]:
    """성인 학생 1명(learning_session.user_id FK 대상) — 끝나면 세션·학생 정리."""
    uid = uuid.uuid4()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        db.add(
            UserProfile.from_schema(
                UserProfileSchema(
                    user_id=uid,
                    persona_primary=Persona.A_일반고고3,
                    birth_year=2000,
                    is_minor=False,
                )
            )
        )
        await db.commit()
    try:
        yield uid
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM learning_session WHERE user_id = :u"), {"u": uid})
            await conn.execute(text("DELETE FROM user_profile WHERE user_id = :u"), {"u": uid})


async def _sessions(engine: AsyncEngine, uid: uuid.UUID) -> list[LearningSession]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        rows = await db.execute(
            select(LearningSession)
            .where(LearningSession.user_id == uid)
            .order_by(LearningSession.started_at)
        )
        return list(rows.scalars().all())


async def _touch(engine: AsyncEngine, uid: uuid.UUID, at: datetime) -> writer.SessionTouch:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        touched = await writer.touch_learning_session(db, user_id=uid, now=at)
        await db.commit()
        return touched


_T0 = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)


class TestIdleRule:
    async def test_first_activity_opens_and_scores_stay_null(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        touched = await _touch(engine, user_id, _T0)
        assert touched.opened is True and touched.closed_previous is None
        (row,) = await _sessions(engine, user_id)
        assert row.session_id == touched.session_id
        assert row.started_at == _T0 and row.last_activity_at == _T0
        assert row.ended_at is None
        # ③ 점수 미신설(S3-16 ③) — writer 경로를 실제로 돌린 행에서 확인한다.
        assert row.focus_score is None
        assert row.engagement_score is None

    async def test_activity_within_gap_continues_and_exact_gap_is_inclusive(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        first = await _touch(engine, user_id, _T0)
        second = await _touch(engine, user_id, _T0 + timedelta(minutes=10))
        # 마지막 활동(10분)에서 정확히 30분 — 같은 세션(경계 포함).
        third = await _touch(engine, user_id, _T0 + timedelta(minutes=40))
        assert second.session_id == third.session_id == first.session_id
        assert second.opened is False and third.opened is False
        (row,) = await _sessions(engine, user_id)
        assert row.last_activity_at == _T0 + timedelta(minutes=40)
        assert row.ended_at is None

    async def test_gap_exceeded_closes_at_last_activity_and_opens_new(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        first = await _touch(engine, user_id, _T0)
        await _touch(engine, user_id, _T0 + timedelta(minutes=5))
        later = _T0 + timedelta(minutes=35, seconds=1)  # 마지막 활동(5분)+30분+1초
        second = await _touch(engine, user_id, later)
        assert second.opened is True
        assert second.closed_previous == first.session_id
        old, new = await _sessions(engine, user_id)
        # 종료 시각은 닫은 *지금*이 아니라 마지막 활동 — 유휴 30분을 학습 시간으로 세지 않는다.
        assert old.ended_at == _T0 + timedelta(minutes=5)
        assert old.duration_seconds == 300
        assert new.session_id == second.session_id and new.ended_at is None

    async def test_clock_going_backwards_does_not_rewind_last_activity(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        await _touch(engine, user_id, _T0 + timedelta(minutes=10))
        await _touch(engine, user_id, _T0 + timedelta(minutes=9))  # 도착 순서 역전
        (row,) = await _sessions(engine, user_id)
        assert row.last_activity_at == _T0 + timedelta(minutes=10)


class TestCloseAtQueryTime:
    async def test_only_stale_server_sessions_are_closed(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        now = datetime.now(UTC)
        stale_id, fresh_uid = uuid.uuid4(), uuid.uuid4()
        legacy_id = uuid.uuid4()
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            db.add(
                UserProfile.from_schema(
                    UserProfileSchema(
                        user_id=fresh_uid,
                        persona_primary=Persona.A_일반고고3,
                        birth_year=2000,
                        is_minor=False,
                    )
                )
            )
            await db.flush()
            db.add_all(
                [
                    LearningSession(
                        session_id=stale_id,
                        user_id=user_id,
                        started_at=now - timedelta(minutes=50),
                        last_activity_at=now - timedelta(minutes=31),
                    ),
                    LearningSession(
                        session_id=uuid.uuid4(),
                        user_id=fresh_uid,
                        started_at=now - timedelta(minutes=40),
                        last_activity_at=now - timedelta(minutes=29),
                    ),
                    # writer 이전 행(last_activity_at NULL) — 서버 규칙 대상이 아니다.
                    LearningSession(
                        session_id=legacy_id,
                        user_id=user_id,
                        started_at=now - timedelta(days=3),
                    ),
                ]
            )
            await db.commit()
        try:
            async with maker() as db:
                closed_other = await writer.close_idle_sessions(db, now=now, user_id=fresh_uid)
                closed = await writer.close_idle_sessions(db, now=now, user_id=user_id)
                await db.commit()
            assert closed_other == 0, "유휴 이내 세션은 닫지 않는다"
            assert closed == 1
            rows = {r.session_id: r for r in await _sessions(engine, user_id)}
            assert rows[stale_id].ended_at == now - timedelta(minutes=31)
            assert rows[stale_id].duration_seconds == 19 * 60
            assert rows[legacy_id].ended_at is None, "writer 이전 행은 건드리지 않는다"
            (fresh,) = await _sessions(engine, fresh_uid)
            assert fresh.ended_at is None
        finally:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM learning_session WHERE user_id = :u"), {"u": fresh_uid}
                )
                await conn.execute(
                    text("DELETE FROM user_profile WHERE user_id = :u"), {"u": fresh_uid}
                )


class TestConcurrency:
    """⑩ — 같은 학생의 동시 요청 2건 → 열린 세션 1개."""

    async def test_two_concurrent_first_activities_open_one_session(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        winner_inserted = asyncio.Event()

        async def first() -> uuid.UUID:
            async with maker() as db:
                touched = await writer.touch_learning_session(db, user_id=user_id, now=_T0)
                winner_inserted.set()
                # 패자가 "열린 세션 없음"을 보고 INSERT에 들어가 충돌 대기에 걸릴 시간을 준다.
                await asyncio.sleep(0.5)
                await db.commit()
                return touched.session_id

        async def second() -> uuid.UUID:
            await winner_inserted.wait()
            async with maker() as db:
                touched = await writer.touch_learning_session(
                    db, user_id=user_id, now=_T0 + timedelta(seconds=1)
                )
                await db.commit()
                return touched.session_id

        a, b = await asyncio.gather(first(), second())
        assert a == b, "경합한 두 요청이 서로 다른 세션을 열었다"
        rows = await _sessions(engine, user_id)
        assert len(rows) == 1, f"열린 세션이 {len(rows)}개 — 학생당 1개여야 한다"
        assert rows[0].last_activity_at == _T0 + timedelta(seconds=1)

    async def test_the_partial_unique_index_actually_rejects_a_second_open_session(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        """DB 제약 실재 — writer를 거치지 않은 두 번째 열린 서버 세션은 DB가 거부한다."""
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            db.add(LearningSession(user_id=user_id, started_at=_T0, last_activity_at=_T0))
            await db.commit()
        async with maker() as db:
            db.add(LearningSession(user_id=user_id, started_at=_T0, last_activity_at=_T0))
            with pytest.raises(IntegrityError, match="uq_learning_session_open_per_user"):
                await db.commit()

    async def test_closed_and_legacy_sessions_are_outside_the_constraint(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        """닫힌 세션·writer 이전 행(last_activity_at NULL)은 여러 개여도 된다(술어 범위)."""
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            db.add_all(
                [
                    LearningSession(user_id=user_id, started_at=_T0),
                    LearningSession(user_id=user_id, started_at=_T0),
                    LearningSession(
                        user_id=user_id, started_at=_T0, last_activity_at=_T0, ended_at=_T0
                    ),
                    LearningSession(user_id=user_id, started_at=_T0, last_activity_at=_T0),
                ]
            )
            await db.commit()
        assert len(await _sessions(engine, user_id)) == 4
