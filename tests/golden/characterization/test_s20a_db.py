"""S20A 특성화 테스트 — 골든 엔진 복사본(golden.db)이 옛 get_engine의 NullPool 분기와 같게 동작한다.

다섯 걸음 ②: 옛 코드를 옛 자리에서 그대로 부르고, 같은 입력 10개에 복사본이 같은 출력을 내는지
고정한다. 지금 동작이 "맞는지"는 묻지 않는다 — 바뀌지 않는지만 본다.

- 입력 = 연결 주소(database_url) 10개. 옛 쪽은 S20A 이전 store.py와 똑같이
  `get_settings().model_copy(update={"database_url": url, "db_disable_pool": True})`를 넘긴다.
- 출력 = 엔진의 겉모습 5가지(주소·방언·드라이버·풀 종류·async 여부). 엔진 생성은 풀만 준비하므로
  DB 접속이 일어나지 않는다(살아 있는 PostgreSQL 불요).
- 옛 get_engine은 첫 호출의 엔진을 모듈 전역에 캐시하므로, 매번 캐시를 비웠다가 원래 값으로 되돌린다.
"""

from __future__ import annotations

from collections.abc import Iterator

import golden.db as golden_db
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

import whymath_backend.db.session as old_session
from whymath_backend.config import get_settings

# 입력 10개 — 호스트·포트·사용자·비밀번호·DB 이름·쿼리 인자·IPv6를 고루 바꾼다
URLS = [
    "postgresql+asyncpg://whymath@127.0.0.1:5432/whymath",
    "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath",
    "postgresql+asyncpg://whymath@127.0.0.1:55432/whymath",
    "postgresql+asyncpg://whymath:secret@localhost/whymath",
    "postgresql+asyncpg://u:p%40ss@db.example.local:6543/other_db",
    "postgresql+asyncpg://whymath@[::1]:5432/whymath",
    "postgresql+asyncpg://whymath@127.0.0.1/whymath?ssl=disable",
    "postgresql+asyncpg://whymath@127.0.0.1:5432/whymath?prepared_statement_cache_size=0",
    "postgresql+asyncpg://user_only@host-only",
    "postgresql+asyncpg:///local_socket_db",
]


def _shape(engine: AsyncEngine) -> tuple[str, str, str, str, bool]:
    """비교할 겉모습 — 비밀번호는 가려서 문자열로 만든다(로그·실패 메시지에 원문이 안 나오게)."""
    return (
        engine.url.render_as_string(hide_password=True),
        engine.dialect.name,
        engine.dialect.driver,
        type(engine.pool).__name__,
        isinstance(engine, AsyncEngine),
    )


@pytest.fixture
def restore_old_cache() -> Iterator[None]:
    """옛 모듈 전역 캐시(_engine)를 테스트 뒤 원래 값으로 되돌린다(다른 테스트 오염 방지)."""
    saved = old_session._engine
    try:
        yield
    finally:
        old_session._engine = saved


@pytest.mark.parametrize("url", URLS)
def test_copy_matches_old_get_engine_nullpool_branch(url: str, restore_old_cache: None) -> None:
    old_session._engine = None  # 옛 캐시를 비워 이번 입력으로 새로 만들게 한다
    old_engine = old_session.get_engine(
        get_settings().model_copy(update={"database_url": url, "db_disable_pool": True})
    )
    new_engine = golden_db.build_engine(url)
    assert _shape(new_engine) == _shape(old_engine)
    # 풀 종류는 둘 다 NullPool이어야 한다(골든이 쓰던 분기 그 자체)
    assert _shape(new_engine)[3] == "NullPool"


def test_get_engine_caches_first_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """복사본의 get_engine도 원본처럼 첫 호출의 엔진을 계속 돌려준다."""
    monkeypatch.setattr(golden_db, "_engine", None)
    first = golden_db.get_engine()
    assert golden_db.get_engine() is first
    assert type(first.pool).__name__ == "NullPool"
