"""EOS-131 ⑪ — 서버 세션 연쇄 파기가 시도를 *조기에* 지우지 않는다(실 PG · 기본 SKIP).

`problem_attempt.session_id → learning_session`은 `ON DELETE CASCADE`다. 서버 writer 이전에는
값이 늘 NULL이라 이 연쇄가 한 번도 작동하지 않았다. 이제 서버가 값을 채우므로, 세션을
`started_at` 기준으로 파기하면 **세션은 기준 밖·그 뒤쪽 시도는 기준 안**인 경계에서 시도가 연쇄로
함께 지워진다(조기 파기 + 파기 리포트의 시도 건수 과소 집계). `privacy/retention`은 서버 세션을
`last_activity_at` 기준 + "남은 시도 없음" 조건으로 지운다 — 이 파일이 그 경계를 실 CASCADE로 잰다.

주입 확인: `_purge_condition`을 종전 규칙(`started_at < cutoff`)으로 되돌리면
`test_session_straddling_the_cutoff_keeps_its_recent_attempt`가 RED다(세션과 함께 최근 시도가
사라진다).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.db.models.activity import LearningSession, ProblemAttempt
from whymath_backend.db.models.user import UserProfile
from whymath_backend.privacy.retention import purge_expired_records, retention_cutoff
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

pytestmark = pytest.mark.integration

_AS_OF = date(2026, 9, 25)
_YEARS = 3
_CUTOFF = datetime.combine(retention_cutoff(_AS_OF, years=_YEARS), datetime.min.time(), UTC)


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
async def uid(engine: AsyncEngine) -> AsyncIterator[uuid.UUID]:
    user_id = uuid.uuid4()
    async with async_sessionmaker(engine)() as db:
        db.add(
            UserProfile.from_schema(
                UserProfileSchema(
                    user_id=user_id,
                    persona_primary=Persona.A_일반고고3,
                    birth_year=2000,
                    is_minor=False,
                )
            )
        )
        await db.commit()
    try:
        yield user_id
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM problem_attempt WHERE user_id = :u"), {"u": user_id}
            )
            await conn.execute(
                text("DELETE FROM learning_session WHERE user_id = :u"), {"u": user_id}
            )
            await conn.execute(text("DELETE FROM user_profile WHERE user_id = :u"), {"u": user_id})


async def _seed(
    engine: AsyncEngine,
    uid: uuid.UUID,
    *,
    started_at: datetime,
    last_activity_at: datetime | None,
    attempts: list[tuple[datetime | None, datetime]],
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """세션 1개 + 시도 n건((클라 신고 started_at, 서버 수신 ingested_at))."""
    sid = uuid.uuid4()
    aids = [uuid.uuid4() for _ in attempts]
    async with async_sessionmaker(engine)() as db:
        db.add(
            LearningSession(
                session_id=sid,
                user_id=uid,
                started_at=started_at,
                last_activity_at=last_activity_at,
                # 닫힌 서버 세션 — 여러 개여도 부분 유니크 인덱스 대상이 아니다.
                ended_at=last_activity_at,
            )
        )
        await db.flush()
        for aid, (reported, ingested) in zip(aids, attempts, strict=True):
            db.add(
                ProblemAttempt(
                    attempt_id=aid,
                    user_id=uid,
                    session_id=sid,
                    started_at=reported,
                    ingested_at=ingested,
                )
            )
        await db.commit()
    return sid, aids


async def _exists(engine: AsyncEngine, table: str, column: str, value: uuid.UUID) -> bool:
    async with engine.connect() as conn:
        row = (
            await conn.execute(text(f"SELECT 1 FROM {table} WHERE {column} = :v"), {"v": value})
        ).first()
        return row is not None


async def _purge(engine: AsyncEngine) -> dict[str, int]:
    async with async_sessionmaker(engine)() as db:
        counts = await purge_expired_records(db, as_of=_AS_OF, years=_YEARS)
        await db.commit()
        return counts


class TestServerSessionPurgeBasis:
    async def test_session_straddling_the_cutoff_keeps_its_recent_attempt(
        self, engine: AsyncEngine, uid: uuid.UUID
    ) -> None:
        """경계 사례 — 세션 시작은 기준 밖, 뒤쪽 시도는 기준 안. 오래된 시도만 지워진다."""
        sid, (old_aid, new_aid) = await _seed(
            engine,
            uid,
            started_at=_CUTOFF - timedelta(minutes=20),
            last_activity_at=_CUTOFF + timedelta(minutes=5),
            attempts=[
                (None, _CUTOFF - timedelta(minutes=20)),
                (None, _CUTOFF + timedelta(minutes=5)),
            ],
        )
        counts = await _purge(engine)
        assert not await _exists(engine, "problem_attempt", "attempt_id", old_aid)
        assert await _exists(
            engine, "problem_attempt", "attempt_id", new_aid
        ), "기준 안쪽 시도가 세션 연쇄로 조기 파기됐다(EOS-131 ⑪)"
        assert await _exists(engine, "learning_session", "session_id", sid)
        assert counts["problem_attempt"] >= 1

    async def test_session_whose_last_activity_expired_goes_with_all_its_attempts(
        self, engine: AsyncEngine, uid: uuid.UUID
    ) -> None:
        """대조군 — 마지막 활동까지 기준 밖이면 세션과 시도가 모두 파기되고, 시도는 *직접*
        파기로 계상된다(연쇄로 사라져 리포트에서 빠지지 않는다)."""
        sid, aids = await _seed(
            engine,
            uid,
            started_at=_CUTOFF - timedelta(days=2),
            last_activity_at=_CUTOFF - timedelta(days=1),
            attempts=[(None, _CUTOFF - timedelta(days=2)), (None, _CUTOFF - timedelta(days=1))],
        )
        counts = await _purge(engine)
        assert not await _exists(engine, "learning_session", "session_id", sid)
        for aid in aids:
            assert not await _exists(engine, "problem_attempt", "attempt_id", aid)
        assert counts["problem_attempt"] >= 2
        assert counts["learning_session"] >= 1

    async def test_reported_start_ahead_of_last_activity_still_blocks_the_cascade(
        self, engine: AsyncEngine, uid: uuid.UUID
    ) -> None:
        """허용 오차(클라 신고 started_at이 수신보다 최대 5분 앞섬) 경계 — 세션의 마지막 활동은
        기준 밖이어도 그 시도의 파기 기준(started_at)이 기준 안이면 세션을 지우지 않는다."""
        sid, (aid,) = await _seed(
            engine,
            uid,
            started_at=_CUTOFF - timedelta(minutes=30),
            last_activity_at=_CUTOFF - timedelta(minutes=1),
            attempts=[(_CUTOFF + timedelta(minutes=2), _CUTOFF - timedelta(minutes=1))],
        )
        await _purge(engine)
        assert await _exists(engine, "problem_attempt", "attempt_id", aid)
        assert await _exists(engine, "learning_session", "session_id", sid)

    async def test_legacy_session_keeps_the_started_at_rule(
        self, engine: AsyncEngine, uid: uuid.UUID
    ) -> None:
        """writer 이전 행(last_activity_at NULL)은 종전 규칙 그대로 — started_at 기준 파기."""
        sid, _ = await _seed(
            engine, uid, started_at=_CUTOFF - timedelta(days=1), last_activity_at=None, attempts=[]
        )
        await _purge(engine)
        assert not await _exists(engine, "learning_session", "session_id", sid)
