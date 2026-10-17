"""EOS-131 학습 세션 writer — 실 PostgreSQL 통합 테스트(기본 SKIP · `WHYMATH_RUN_INTEGRATION=1`).

hermetic(`test_learning_session_writer.py`)이 계약 모양을 본다면, 이 파일은 **실 DB에서 규칙이
실제로 성립하는지**를 본다:
  ② 유휴 규칙 — 30분 이내는 잇고, 정확히 30분은 잇고(경계 포함), 30분+1초는 직전 세션을 *마지막
     활동 시각*으로 닫고 새로 연다. 조회 시점 확정(`close_idle_sessions`)이 다시 오지 않는 학생의
     세션을 닫고, 유휴 이내 세션·writer 이전 행은 건드리지 않는다.
  ③ 점수 NULL — writer가 만든 행의 `focus_score`·`engagement_score`는 NULL이다.
  P3-27 개념 채움 — 세션의 `target_concept_id`는 "이 묶음에서 처음 확인된 개념"이다. 새 세션은 첫
     활동의 개념으로 열리고, 개념 없이 열린 세션은 뒤 활동이 알려 주면 채워지며(NULL→값), 이미 있는
     값은 덮어쓰지 않는다. 유휴 초과로 새로 열린 세션은 자기 활동의 개념을 갖는다.
  ⑩ 동시성 — 같은 학생의 요청 2건을 **실제로 동시에**(별도 연결·별도 트랜잭션) 넣어도 열린 세션은
     1개다. 부분 유니크 인덱스가 실제로 걸려 있는지도 직접 주입으로 확인한다.
"""

from __future__ import annotations

import asyncio
import logging
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


async def _touch(
    engine: AsyncEngine,
    uid: uuid.UUID,
    at: datetime,
    concept_id: uuid.UUID | None = None,
) -> writer.SessionTouch:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        touched = await writer.touch_learning_session(
            db, user_id=uid, now=at, concept_id=concept_id
        )
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


class TestFirstConfirmedConcept:
    """P3-27 — `learning_session.target_concept_id` = 묶음 안에서 처음 확인된 개념(덮어쓰기 금지)."""

    _A = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
    _B = uuid.UUID("00000000-0000-4000-8000-0000000000b2")

    async def test_session_opens_with_the_concept_of_its_first_activity(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        await _touch(engine, user_id, _T0, concept_id=self._A)
        (row,) = await _sessions(engine, user_id)
        assert row.target_concept_id == self._A

    async def test_concept_unknown_activity_leaves_null_and_a_later_one_fills_it(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        # 추천 조회는 문항을 고르기 전에 세션을 잇는다 — 개념을 모른다(날조 금지).
        await _touch(engine, user_id, _T0)
        (row,) = await _sessions(engine, user_id)
        assert row.target_concept_id is None
        # 같은 묶음의 뒤 활동이 개념을 알려 주면 NULL→값으로 채운다.
        await _touch(engine, user_id, _T0 + timedelta(minutes=3), concept_id=self._A)
        (row,) = await _sessions(engine, user_id)
        assert row.target_concept_id == self._A
        assert row.last_activity_at == _T0 + timedelta(minutes=3)

    async def test_an_existing_concept_is_never_overwritten(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        await _touch(engine, user_id, _T0, concept_id=self._A)
        await _touch(engine, user_id, _T0 + timedelta(minutes=2), concept_id=self._B)
        await _touch(engine, user_id, _T0 + timedelta(minutes=4))
        (row,) = await _sessions(engine, user_id)
        assert row.target_concept_id == self._A  # 첫 확인 개념 유지
        assert row.last_activity_at == _T0 + timedelta(minutes=4)

    async def test_a_concept_fill_with_an_older_clock_does_not_rewind_last_activity(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        await _touch(engine, user_id, _T0 + timedelta(minutes=10))
        await _touch(engine, user_id, _T0 + timedelta(minutes=9), concept_id=self._A)  # 도착 역전
        (row,) = await _sessions(engine, user_id)
        assert row.target_concept_id == self._A
        assert row.last_activity_at == _T0 + timedelta(minutes=10)

    async def test_a_session_opened_after_the_idle_gap_gets_its_own_concept(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        await _touch(engine, user_id, _T0, concept_id=self._A)
        later = _T0 + timedelta(minutes=31)
        await _touch(engine, user_id, later, concept_id=self._B)
        old, new = await _sessions(engine, user_id)
        assert old.target_concept_id == self._A and old.ended_at == _T0
        assert new.target_concept_id == self._B

    async def test_record_resolves_the_problem_concept_and_survives_a_resolution_failure(
        self,
        engine: AsyncEngine,
        user_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """서빙 래퍼 — 문항→대표 개념을 해석해 채우고, 해석이 터져도 세션 결합은 계속된다."""
        maker = async_sessionmaker(engine, expire_on_commit=False)
        problem = uuid.uuid4()

        async def _found(_session: object, problem_id: uuid.UUID) -> uuid.UUID:
            assert problem_id == problem  # 활동이 실어 온 문항이 그대로 해석기로 간다
            return self._A

        monkeypatch.setattr(writer, "get_primary_concept_id", _found)
        async with maker() as db:
            sid = await writer.record_learning_activity(
                db, user_id=user_id, now=_T0, problem_id=problem
            )
            await db.commit()
        (row,) = await _sessions(engine, user_id)
        assert sid == row.session_id and row.target_concept_id == self._A

        async def _boom(_session: object, _problem_id: uuid.UUID) -> uuid.UUID:
            raise ConnectionResetError("주입된 개념 조회 실패")

        monkeypatch.setattr(writer, "get_primary_concept_id", _boom)
        before = writer.failure_count()
        with caplog.at_level(logging.WARNING, logger="whymath.l2.learning_session_writer"):
            async with maker() as db:
                again = await writer.record_learning_activity(
                    db, user_id=user_id, now=_T0 + timedelta(minutes=1), problem_id=problem
                )
                await db.commit()
        assert again == sid  # 개념을 못 풀어도 세션에는 결합된다(never-break)
        assert writer.failure_count() == before + 1  # 침묵하지 않는다(이중 회계)
        # 삼키되 침묵하지 않는다 — 예외 *타입명*이 로그에 남는다(CLAUDE.md 침묵 실패 금지).
        assert "ConnectionResetError" in caplog.text and "세션 개념 해석 실패" in caplog.text
        (row,) = await _sessions(engine, user_id)
        assert row.target_concept_id == self._A  # 실패가 기존 값을 지우지 않는다
        assert row.last_activity_at == _T0 + timedelta(minutes=1)

    async def test_no_problem_means_no_resolution_attempt(
        self,
        engine: AsyncEngine,
        user_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _must_not_run(*_a: object, **_k: object) -> uuid.UUID:  # pragma: no cover
            raise AssertionError(
                "문항이 없는 활동(추천 조회·문항 없는 코치)은 개념을 해석하지 않는다"
            )

        monkeypatch.setattr(writer, "get_primary_concept_id", _must_not_run)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            sid = await writer.record_learning_activity(db, user_id=user_id, now=_T0)
            await db.commit()
        (row,) = await _sessions(engine, user_id)
        assert sid == row.session_id and row.target_concept_id is None


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

    async def test_a_losing_activity_fills_the_winners_missing_concept(
        self, engine: AsyncEngine, user_id: uuid.UUID
    ) -> None:
        """P3-27 — 경합에서 진 요청이 개념을 알면, 개념 없이 열린 승자 세션에 NULL→값으로 채운다.

        승자(추천 조회류 — 개념 미상)가 먼저 세션을 열고, 패자(시도류 — 개념 확인)가 충돌 대기 뒤 승자
        세션에 합류한다. 합류 분기가 개념을 채우지 않으면 세션은 영영 개념 없이 남는다(그 뒤 활동이
        없으면 트레이스 `concept_selected`가 개념을 못 싣는다).
        """
        concept = uuid.UUID("00000000-0000-4000-8000-0000000000c3")
        maker = async_sessionmaker(engine, expire_on_commit=False)
        winner_inserted = asyncio.Event()

        async def first() -> uuid.UUID:
            async with maker() as db:
                touched = await writer.touch_learning_session(db, user_id=user_id, now=_T0)
                winner_inserted.set()
                await asyncio.sleep(0.5)  # 패자가 INSERT 충돌 대기에 걸릴 시간
                await db.commit()
                return touched.session_id

        async def second() -> uuid.UUID:
            await winner_inserted.wait()
            async with maker() as db:
                touched = await writer.touch_learning_session(
                    db, user_id=user_id, now=_T0 + timedelta(seconds=1), concept_id=concept
                )
                await db.commit()
                return touched.session_id

        a, b = await asyncio.gather(first(), second())
        assert a == b, "경합한 두 요청이 서로 다른 세션을 열었다"
        (row,) = await _sessions(engine, user_id)
        assert row.target_concept_id == concept, "합류한 패자의 개념이 승자 세션에 채워지지 않았다"

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
