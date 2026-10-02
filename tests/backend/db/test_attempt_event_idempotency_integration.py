"""attempt_event.event_uuid 멱등성 — 마이그레이션 왕복 + 재전송 한 번만 반영 (DP-03 · WHYMATH_RUN_INTEGRATION).

마이그레이션 head가 적용된 **실 PostgreSQL**에서 리비전 `a3f7c9d1e5b2`를 검증한다. PG 미도달 또는
이 리비전 미적용이면 graceful skip(`test_hints_migration_integration.py` 미러).

검증(DP-03 acceptance):
  ① head에서 `event_uuid` 컬럼(nullable)과 부분 UNIQUE 인덱스가 존재하고, 복합 PK
     `(event_id, event_at)`는 그대로다(내부 BIGSERIAL 키 유지).
  ② revision-local 왕복(downgrade → `9d3e7b1c5a20` → upgrade head)이 대칭 — 컬럼·인덱스 제거/복원.
  ③ **재전송이 한 번만 반영** — 같은 `event_uuid`를 (a) 순차 재전송 (b) 동시 재전송(서로 다른
     세션·`asyncio.gather`)해도 행은 1건이고 정확히 한 호출만 True. RED/GREEN 양면: 다른 uuid는
     각자 반영되고, 키 없는(NULL) 이벤트끼리는 충돌하지 않는다(부분 인덱스의 의도).
  ④ 재전송은 `event_at`(서버 수신 시각)이 달라도 막힌다 — hypertable 복합키 `(uuid, event_at)`
     방식이면 뚫리는 지점이다(마이그레이션 docstring의 비호환 근거).
  ⑤ 키 없는 이벤트를 멱등 헬퍼로 보내면 ValueError(멱등 보호 위장 방지).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from whymath_backend.config import Settings

pytestmark = pytest.mark.integration

_REVISION = "a3f7c9d1e5b2"
_PREV_REVISION = "9d3e7b1c5a20"
_BACKEND_DIR = Path(__file__).resolve().parents[3] / "src" / "backend"
_ALEMBIC_DIR = _BACKEND_DIR / "alembic"
_INDEX = "uq_attempt_event_event_uuid"


def _sync_engine() -> object:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    if settings.db_disable_pool:
        return create_engine(settings.sync_database_url, poolclass=NullPool)
    return create_engine(settings.sync_database_url)


def _has_event_uuid() -> bool:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            return (
                conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'attempt_event' AND column_name = 'event_uuid'"
                    )
                ).first()
                is not None
            )
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _skip_if_unreachable() -> None:
    if not _has_event_uuid():
        pytest.skip(
            "PostgreSQL 미도달(또는 event_uuid 리비전 미적용) — 통합 테스트 건너뜀 "
            "(WHYMATH_DATABASE_URL·alembic upgrade head 확인)"
        )


def _alembic_config() -> object:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", "")
    return cfg


class TestMigrationShape:
    def test_head_has_nullable_column_partial_unique_index_and_unchanged_pk(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        engine = _sync_engine()
        try:
            with engine.connect() as conn:  # type: ignore[attr-defined]
                nullable = conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name='attempt_event' AND column_name='event_uuid'"
                    )
                ).scalar_one()
                indexdef = conn.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE tablename='attempt_event' AND indexname=:i"
                    ),
                    {"i": _INDEX},
                ).scalar_one()
                pk_cols = conn.execute(
                    text(
                        "SELECT a.attname FROM pg_index i "
                        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) "
                        "WHERE i.indrelid='attempt_event'::regclass AND i.indisprimary "
                        "ORDER BY a.attname"
                    )
                ).all()
        finally:
            engine.dispose()  # type: ignore[attr-defined]
        assert nullable == "YES"
        assert "UNIQUE" in indexdef and "WHERE (event_uuid IS NOT NULL)" in indexdef
        assert [r[0] for r in pk_cols] == ["event_at", "event_id"]  # 내부 BIGSERIAL 키 유지

    def test_downgrade_then_upgrade_removes_and_restores(self) -> None:
        _skip_if_unreachable()
        from alembic import command

        cfg = _alembic_config()
        try:
            command.downgrade(cfg, _PREV_REVISION)  # type: ignore[arg-type]
            assert not _has_event_uuid()
        finally:
            command.upgrade(cfg, "head")  # type: ignore[arg-type]
        assert _has_event_uuid()


def _event(event_uuid: uuid.UUID | None, *, at: datetime | None = None):  # type: ignore[no-untyped-def]
    from whymath_backend.db.models.activity import AttemptEvent
    from whymath_backend.schema.enums import EventType

    return AttemptEvent(
        event_uuid=event_uuid,
        event_at=at or datetime.now(UTC),
        event_type=EventType.시각화조작,
    )


class TestRetransmitAppliedOnce:
    async def _run(self, scenario):  # type: ignore[no-untyped-def]
        _skip_if_unreachable()
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        engine = create_async_engine(Settings().database_url, poolclass=NullPool)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        keys: list[uuid.UUID] = []
        try:
            await scenario(maker, keys)
        finally:
            # 테스트가 만든 행만 정리한다(uuid로 식별 — 다른 테스트 데이터 무접촉).
            async with maker() as s:
                if keys:
                    await s.execute(
                        text("DELETE FROM attempt_event WHERE event_uuid = ANY(:k)"),
                        {"k": keys},
                    )
                await s.commit()
            await engine.dispose()

    async def test_sequential_resend_with_different_event_at_is_dropped(self) -> None:
        from sqlalchemy import text

        from whymath_backend.db.models.activity import insert_attempt_event_once

        async def scenario(maker, keys):  # type: ignore[no-untyped-def]
            key = uuid.uuid4()
            keys.append(key)
            now = datetime.now(UTC)
            async with maker() as s:
                first = await insert_attempt_event_once(s, _event(key, at=now))
                await s.commit()
            async with maker() as s:  # 재전송 — 서버 수신 시각이 달라도(④) 막혀야 한다
                again = await insert_attempt_event_once(s, _event(key, at=now + timedelta(hours=1)))
                await s.commit()
            async with maker() as s:
                count = (
                    await s.execute(
                        text("SELECT count(*) FROM attempt_event WHERE event_uuid = :k"),
                        {"k": key},
                    )
                ).scalar_one()
            assert (first, again, count) == (True, False, 1)

        await self._run(scenario)

    async def test_concurrent_resend_lands_exactly_once(self) -> None:
        from sqlalchemy import text

        from whymath_backend.db.models.activity import insert_attempt_event_once

        async def scenario(maker, keys):  # type: ignore[no-untyped-def]
            key = uuid.uuid4()
            keys.append(key)

            async def send() -> bool:
                async with maker() as s:
                    ok = await insert_attempt_event_once(s, _event(key))
                    await s.commit()
                    return ok

            results = await asyncio.gather(*(send() for _ in range(8)))
            async with maker() as s:
                count = (
                    await s.execute(
                        text("SELECT count(*) FROM attempt_event WHERE event_uuid = :k"),
                        {"k": key},
                    )
                ).scalar_one()
            assert sum(results) == 1 and count == 1, (results, count)

        await self._run(scenario)

    async def test_control_group_distinct_keys_and_null_keys_do_not_collide(self) -> None:
        """대조군 — 인덱스가 모든 삽입을 막는 것이 아니다(다른 uuid·NULL 키는 각자 반영)."""
        from sqlalchemy import text

        from whymath_backend.db.models.activity import insert_attempt_event_once

        async def scenario(maker, keys):  # type: ignore[no-untyped-def]
            a, b = uuid.uuid4(), uuid.uuid4()
            keys.extend([a, b])
            async with maker() as s:
                assert await insert_attempt_event_once(s, _event(a)) is True
                assert await insert_attempt_event_once(s, _event(b)) is True
                await s.commit()
            # NULL 키 두 건: 기존 writer 경로(session.add)는 충돌하지 않는다.
            marker = uuid.uuid4()  # 정리용 식별자는 user_id에 심는다
            async with maker() as s:
                for _ in range(2):
                    e = _event(None)
                    e.user_id = marker
                    s.add(e)
                await s.commit()
            try:
                async with maker() as s:
                    n = (
                        await s.execute(
                            text("SELECT count(*) FROM attempt_event WHERE user_id = :u"),
                            {"u": marker},
                        )
                    ).scalar_one()
                assert n == 2
            finally:
                async with maker() as s:
                    await s.execute(
                        text("DELETE FROM attempt_event WHERE user_id = :u"), {"u": marker}
                    )
                    await s.commit()

        await self._run(scenario)

    async def test_helper_rejects_event_without_key(self) -> None:
        from whymath_backend.db.models.activity import insert_attempt_event_once

        with pytest.raises(ValueError, match="event_uuid"):
            await insert_attempt_event_once(None, _event(None))  # type: ignore[arg-type]
