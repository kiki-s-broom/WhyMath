"""S20A 특성화 — 옛 `whymath_backend.db.session.get_engine`과 골든 복사본 `golden.db`.

골든은 옛 엔진을 늘 `db_disable_pool=True`(연결 풀 없음)로 받았다(S4 `store._engine`).
같은 연결 주소 10개에서 두 쪽이 만든 엔진의 모양(주소·드라이버·풀 종류)이 같은지 고정한다.
엔진을 만들기만 하고 접속하지 않으므로 DB가 없어도 돈다. 맞는지는 묻지 않는다 — 같은지만 본다.

옛 모듈은 이 테스트에서만 import한다(골든 패키지는 import하지 않는다 — test_import_budget.py).
"""

from __future__ import annotations

import asyncio

import golden.db as golden_db
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

import whymath_backend.db.session as legacy_session
from whymath_backend.config import Settings

# 연결 주소 입력 10개 — CI·시연 DB·Kiki 머신 prod DB·특수문자·질의 문자열 등
_URLS = [
    "postgresql+asyncpg://whymath@127.0.0.1:5432/whymath",
    "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath",
    "postgresql+asyncpg://whymath@127.0.0.1:55432/whymath",
    "postgresql+asyncpg://whymath@localhost/whymath",
    "postgresql+asyncpg://user:secret@db.example:6543/other",
    "postgresql+asyncpg://user:p%40ss%2Fword@db.example/other",
    "postgresql+asyncpg://whymath@[::1]:5432/whymath",
    "postgresql+asyncpg://whymath@127.0.0.1:5432/whymath?ssl=require",
    "postgresql+asyncpg:///whymath",
    "postgresql+asyncpg://whymath@127.0.0.1:5432/golden_test",
]


def _shape(engine: AsyncEngine) -> dict[str, object]:
    """엔진에서 비교할 모양만 뽑는다(객체 자체는 서로 다르다)."""
    return {
        "url": engine.url,  # 비밀번호까지 포함해 비교한다(출력하지 않는다)
        "dialect": engine.dialect.name,
        "driver": engine.dialect.driver,
        "pool": type(engine.pool).__name__,
        "echo": engine.echo,
    }


@pytest.fixture
def no_cached_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    """두 모듈의 전역 엔진을 비우고, 테스트가 끝나면 원래 값으로 되돌린다."""
    monkeypatch.setattr(legacy_session, "_engine", None)
    monkeypatch.setattr(golden_db, "_engine", None)


@pytest.mark.parametrize("url", _URLS)
def test_engine_shape_matches_legacy(url: str, no_cached_engines: None) -> None:
    legacy = legacy_session.get_engine(Settings(database_url=url, db_disable_pool=True))
    copied = golden_db.make_engine(url)
    assert _shape(copied) == _shape(legacy)
    assert _shape(copied)["pool"] == "NullPool"  # 공허한 일치(둘 다 None 등)가 아닌지


def test_inputs_are_ten_distinct_urls() -> None:
    assert len(_URLS) == 10 and len(set(_URLS)) == 10


def test_get_engine_is_lazy_and_cached_like_legacy(
    no_cached_engines: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 처음 부를 때 만들고 그 뒤로는 같은 엔진을 돌려준다(옛 get_engine과 같은 규칙)
    made: list[str] = []
    real = golden_db.make_engine

    def counting(url: str) -> AsyncEngine:
        made.append(url)
        return real(url)

    monkeypatch.setattr(golden_db, "make_engine", counting)
    first = golden_db.get_engine()
    assert golden_db.get_engine() is first
    assert len(made) == 1

    legacy_first = legacy_session.get_engine(Settings(db_disable_pool=True))
    assert legacy_session.get_engine() is legacy_first


def test_get_engine_uses_golden_settings_url(
    no_cached_engines: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 설정의 연결 주소가 그대로 엔진에 들어간다(옛 코드는 settings.database_url을 썼다)
    from golden.settings import GoldenSettings

    url = "postgresql+asyncpg://whymath@127.0.0.1:5999/via_settings"
    monkeypatch.setattr(golden_db, "get_settings", lambda: GoldenSettings(database_url=url))
    legacy = legacy_session.get_engine(Settings(database_url=url, db_disable_pool=True))
    assert _shape(golden_db.get_engine()) == _shape(legacy)


def test_dispose_engine_clears_cache_like_legacy(no_cached_engines: None) -> None:
    # 닫은 뒤에는 새 엔진을 만든다(옛 dispose_engine과 같은 규칙)
    first = golden_db.get_engine()
    asyncio.run(golden_db.dispose_engine())
    assert golden_db.get_engine() is not first

    legacy_first = legacy_session.get_engine(Settings(db_disable_pool=True))
    asyncio.run(legacy_session.dispose_engine())
    assert legacy_session.get_engine(Settings(db_disable_pool=True)) is not legacy_first
