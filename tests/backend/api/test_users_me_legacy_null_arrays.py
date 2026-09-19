"""이미 NULL로 저장된 *기존* 행도 `/v1/users/me`가 읽고 고치는가 — EOS-109 acceptance ③.

**왜 별도 모듈인가**: 이 축은 "배열 컬럼이 NULL인 행"을 *의도적으로 만들어* 검증해야 하므로
원시 `UPDATE`가 필요하다. 그런데 게이트 하네스(`test_week1_gate_closed_loop.py`)는 학습자 상태
직접 쓰기가 AST로 금지돼 있다(`test_week1_gate_no_learner_writes.py`) — 그 규율은 게이트 문면의
근거라 완화 대상이 아니다. 그래서 축을 여기로 분리한다.

**무엇을 증명하는가**: EOS-109의 수정 축은 ⓑ(읽기측 `to_schema()`)다. ⓐ(신규 생성 시 `[]` 채움)를
골랐다면 *이미 NULL인 행*은 계속 500이었을 것이므로 백필 마이그레이션이 별도로 필요했다. ⓑ를
고른 결과 그 행들도 함께 읽히는데, 그 주장은 **실제로 NULL인 행을 만들어 읽어 봐야** 성립한다.
이 모듈이 그 주입을 한다(주장이 아니라 검사).

NULL 행의 출처는 두 가지이며 둘 다 여기서 재현된다: ①`resolve_user`/`bootstrap_account`가
ORM 생성자로 만든 신규 행 ②그 이전 배포에서 같은 경로로 만들어져 DB에 남아 있는 행.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from whymath_backend.api._rate_limit import reset_store
from whymath_backend.api.demo_auth import DEMO_PROVIDER_NAME, FakeOAuthProvider
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings

pytestmark = pytest.mark.integration

_SECRET = "legacy-null-arrays-jwt-secret-0123456789"
_REDIRECT_URI = "http://localhost:8000/auth/demo/callback"
_ERASE_CONFIRM = "DELETE_MY_ACCOUNT"

# 결함이 났던 바로 그 4컬럼 — ORM nullable ↔ schema 비옵셔널 `list[...]`.
_ARRAY_COLUMNS = ("track_type", "target_universities", "inkang_provider", "accessibility_needs")


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_SECRET), oauth_redirect_uri_allowlist=_REDIRECT_URI)


async def _pg_reachable() -> bool:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — 미도달이면 판정 불가(skip). 통과가 아니다.
        return False
    finally:
        await engine.dispose()


async def _null_out_arrays(user_id: uuid.UUID) -> int:
    """배열 4컬럼을 NULL로 되돌린다 — "구버전이 남긴 행" 상태의 주입. 영향 행 수를 돌려준다."""
    assignments = ", ".join(f"{col} = NULL" for col in _ARRAY_COLUMNS)
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(f"UPDATE user_profile SET {assignments} WHERE user_id = :uid"),
                {"uid": str(user_id)},
            )
            return int(result.rowcount)
    finally:
        await engine.dispose()


async def _arrays_are_null(user_id: uuid.UUID) -> bool:
    """주입이 실제로 적용됐는지 되읽어 확인한다(쓰기 성공 ≠ 내용 반영)."""
    cols = ", ".join(_ARRAY_COLUMNS)
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(f"SELECT {cols} FROM user_profile WHERE user_id = :uid"),
                    {"uid": str(user_id)},
                )
            ).first()
        return row is not None and all(value is None for value in row)
    finally:
        await engine.dispose()


def _client() -> TestClient:
    app = create_app(oauth_providers={DEMO_PROVIDER_NAME: FakeOAuthProvider()})
    app.dependency_overrides[get_settings] = _settings
    return TestClient(app)


def _login(client: TestClient) -> dict[str, str]:
    state = client.get(f"/v1/auth/{DEMO_PROVIDER_NAME}/state")
    assert state.status_code == 200, state.text
    login = client.post(
        f"/v1/auth/{DEMO_PROVIDER_NAME}/callback",
        json={
            "code": "legacy-null-arrays",
            "redirect_uri": _REDIRECT_URI,
            "state": state.json()["state"],
        },
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _erase(client: TestClient) -> None:
    auth = _login(client)
    erased = client.request("DELETE", "/v1/me", headers=auth, json={"confirmation": _ERASE_CONFIRM})
    assert erased.status_code == 200, erased.text


def test_row_with_null_array_columns_is_readable_and_patchable() -> None:
    """NULL 배열을 *주입한* 기존 행에서 GET·PATCH가 모두 200이고 빈 배열로 읽힌다."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가. 통과가 아니다.")

    asyncio.run(reset_store())
    with _client() as client:
        _erase(client)
        auth = _login(client)
        me = client.get("/v1/users/me", headers=auth)
        assert me.status_code == 200, me.text
        uid = uuid.UUID(me.json()["user_id"])
        try:
            # ── 주입: 배열 4컬럼을 NULL로. 적용·반영을 각각 단언한다(무증상 미적용 방지). ──
            rowcount = asyncio.run(_null_out_arrays(uid))
            assert rowcount == 1, f"주입이 {rowcount}행에 적용됐다(1행이어야)"
            assert asyncio.run(_arrays_are_null(uid)), "주입 후에도 NULL이 아니다 — 주입 미반영"

            # ── 읽기: 수정 전에는 여기서 500이었다. ──
            read = client.get("/v1/users/me", headers=auth)
            assert read.status_code == 200, read.text
            for column in _ARRAY_COLUMNS:
                assert read.json()[column] == [], f"{column}: {read.json()[column]!r}"

            # ── 쓰기: PATCH도 같은 스키마를 응답하므로 함께 깨져 있었다. ──
            patched = client.patch(
                "/v1/users/me",
                headers={**auth, "If-Match": read.headers["ETag"]},
                json={"inkang_provider": ["메가스터디"]},
            )
            assert patched.status_code == 200, patched.text
            assert patched.json()["inkang_provider"] == ["메가스터디"], patched.json()

            # PATCH는 병합 결과를 되써서 NULL을 `[]`로 *치유*한다(ⓑ의 부수 효과).
            assert not asyncio.run(_arrays_are_null(uid)), "PATCH 후에도 NULL이 남아 있다"
        finally:
            _erase(client)


def test_injection_helper_is_discriminating() -> None:
    """주입 헬퍼의 변별력 — 주입하지 않은 상태에서는 `_arrays_are_null`이 False여야 한다.

    이 대조군이 없으면 `_arrays_are_null`이 *항상* True를 돌려주는 고장 상태에서도 위 테스트가
    초록이 된다(주입을 한 번도 안 하고 통과하는 위장).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가. 통과가 아니다.")

    asyncio.run(reset_store())
    with _client() as client:
        _erase(client)
        auth = _login(client)
        me = client.get("/v1/users/me", headers=auth)
        assert me.status_code == 200, me.text
        uid = uuid.UUID(me.json()["user_id"])
        try:
            patched = client.patch(
                "/v1/users/me",
                headers={**auth, "If-Match": me.headers["ETag"]},
                json={"inkang_provider": ["이투스"]},
            )
            assert patched.status_code == 200, patched.text
            assert not asyncio.run(
                _arrays_are_null(uid)
            ), "`[]`로 저장된 행을 `_arrays_are_null`이 NULL로 본다 — 변별력 0"
        finally:
            _erase(client)
