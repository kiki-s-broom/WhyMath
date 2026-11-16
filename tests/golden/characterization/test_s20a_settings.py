"""S20A 특성화 — 옛 `whymath_backend.config.Settings`와 골든 복사본 `golden.settings.GoldenSettings`.

골든이 옛 설정에서 쓰던 것은 `database_url` 하나다. 같은 환경(환경변수·`.env` 파일) 10가지에서
두 설정이 같은 값을 읽는지 고정한다. 지금 동작이 맞는지는 묻지 않는다 — 서로 같은지만 본다.

옛 모듈은 이 테스트에서만 import한다(골든 패키지는 import하지 않는다 — test_import_budget.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from golden.settings import GoldenSettings, get_settings

from whymath_backend.config import Settings

_DEFAULT = "postgresql+asyncpg://whymath@127.0.0.1:5432/whymath"

# (이름, 환경변수, .env 파일 내용 또는 None) — 입력 10개
_CASES: list[tuple[str, dict[str, str], str | None]] = [
    ("아무것도 없음 → 기본값", {}, None),
    ("환경변수(CI 값)", {"WHYMATH_DATABASE_URL": _DEFAULT}, None),
    (
        "환경변수(시연 DB 55432)",
        {"WHYMATH_DATABASE_URL": "postgresql+asyncpg://whymath@127.0.0.1:55432/whymath"},
        None,
    ),
    (
        "환경변수(비밀번호·특수문자)",
        {"WHYMATH_DATABASE_URL": "postgresql+asyncpg://u:p%40ss@db.example:6543/x?ssl=require"},
        None,
    ),
    ("환경변수 이름이 소문자", {"whymath_database_url": "postgresql+asyncpg://lower@h/d"}, None),
    ("빈 문자열", {"WHYMATH_DATABASE_URL": ""}, None),
    (
        "접두사 없는 이름은 무시",
        {"DATABASE_URL": "postgresql+asyncpg://wrong@h/d"},
        None,
    ),
    (".env 파일만", {}, "WHYMATH_DATABASE_URL=postgresql+asyncpg://dotenv@h/d\n"),
    (
        "환경변수가 .env를 이긴다",
        {"WHYMATH_DATABASE_URL": "postgresql+asyncpg://env@h/d"},
        "WHYMATH_DATABASE_URL=postgresql+asyncpg://dotenv@h/d\n",
    ),
    (
        "모르는 키가 섞여 있어도 무시",
        {"WHYMATH_NO_SUCH_KEY": "1", "WHYMATH_DATABASE_URL": "postgresql+asyncpg://extra@h/d"},
        "WHYMATH_ANOTHER_UNKNOWN=2\n",
    ),
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """DB 주소 환경변수를 지우고 빈 폴더로 옮긴다(.env는 현재 폴더에서 읽는다)."""
    for name in ("WHYMATH_DATABASE_URL", "whymath_database_url", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize(("label", "env", "dotenv"), _CASES, ids=[c[0] for c in _CASES])
def test_database_url_matches_legacy_settings(
    label: str,
    env: dict[str, str],
    dotenv: str | None,
    clean_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    if dotenv is not None:
        (clean_env / ".env").write_text(dotenv, encoding="utf-8")
    assert GoldenSettings().database_url == Settings().database_url, label


def test_cases_are_ten_and_not_all_default(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 입력이 10개이고, 전부 기본값으로 떨어지는 공허한 비교가 아닌지 확인한다
    assert len(_CASES) == 10
    values = set()
    for _, env, dotenv in _CASES:
        with monkeypatch.context() as mp:
            for name, value in env.items():
                mp.setenv(name, value)
            dotenv_path = clean_env / ".env"
            if dotenv is not None:
                dotenv_path.write_text(dotenv, encoding="utf-8")
            values.add(GoldenSettings().database_url)
            dotenv_path.unlink(missing_ok=True)
    assert len(values) >= 6
    assert _DEFAULT in values


def test_get_settings_is_cached_per_process() -> None:
    # 옛 get_settings와 같이 한 번 만든 설정을 재사용한다
    assert get_settings() is get_settings()
