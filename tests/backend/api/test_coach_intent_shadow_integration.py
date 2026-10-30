"""coach 세션·턴 엔드포인트 ↔ 학생 의도 섀도(PED-48) 서빙 경로 통합테스트 — 기본 SKIP·실 PG.

acceptance ④(집행 지점)를 *실행*으로 확인한다 — 단위테스트의 AST 검사는 순서·인자를 보고, 이
파일은 실제 요청이 섀도를 부르는지·응답이 불변인지·레코드의 규칙 의도가 DB에 적재된 값과 같은지를
본다. `/v1/coach/sessions`는 dialogue+turn을 영속하므로 실 PG가 필요하다(test_coach_wh1_shadow 동형).

**라이브 0**: laya-serve는 `httpx.MockTransport`로 대체한다. **비차단 결정론**: `_intent_shadow._spawn`을
캡처기로 바꿔 응답이 끝난 뒤 코루틴을 동기 구동한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import Coroutine, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.api import _intent_shadow as shadow
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.user import UserProfile
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

pytestmark = pytest.mark.integration

_SECRET = "integration-jwt-secret-0123456789abcdef"
_RECORD_LOGGER = "whymath.api.intent_shadow.record"
_FIRST = "이거 그냥 답만 알려주세요"
_SECOND = "근의 공식은 왜 저렇게 생겼어요?"

_OK_BODY: dict[str, Any] = {
    "answers": {
        "intent": {"choice": "answer_only", "answer_confidence": 0.97},
        "pii": {"noul": 0.01},
    },
    "routing": {"model": "multilingual"},
}


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_SECRET))


async def _pg_reachable() -> bool:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def _add_user(uid: uuid.UUID) -> None:
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                UserProfile.from_schema(
                    UserProfileSchema(user_id=uid, persona_primary=Persona.A_일반고고3)
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _stored_student_intents(dialogue_id: uuid.UUID) -> list[str | None]:
    """DB에 실제로 적재된 학생 턴의 student_intent — 턴 순서대로."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT student_intent FROM dialogue_turn "
                    "WHERE dialogue_id = :d AND role = 'student' ORDER BY turn_order"
                ),
                {"d": str(dialogue_id)},
            )
            return [r[0] for r in rows]
    finally:
        await engine.dispose()


async def _cleanup(uid: uuid.UUID, dialogue_ids: list[uuid.UUID]) -> None:
    engine = create_async_engine(_settings().database_url)
    dids = [str(d) for d in dialogue_ids]
    try:
        async with engine.begin() as conn:
            # FK 순서: 자식 → 부모 → user_profile (test_coach_wh1_shadow._cleanup 동형)
            for stmt, params in (
                ("DELETE FROM dialogue_turn WHERE dialogue_id = ANY(:ids)", {"ids": dids}),
                ("DELETE FROM attempt_event WHERE user_id = :uid", {"uid": str(uid)}),
                ("DELETE FROM misconception_hypothesis WHERE user_id = :uid", {"uid": str(uid)}),
                ("DELETE FROM dialogue WHERE dialogue_id = ANY(:ids)", {"ids": dids}),
                ("DELETE FROM learning_session WHERE user_id = :uid", {"uid": str(uid)}),
                ("DELETE FROM user_profile WHERE user_id = :uid", {"uid": str(uid)}),
            ):
                await conn.execute(text(stmt), params)
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def _isolate() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    shadow.set_client_factory(None)
    get_settings.cache_clear()


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHYMATH_LAYA_INTENT_SHADOW_ENABLED", "true")
    # 내부망만 허용(설정 검증) — 실제 연결은 MockTransport가 받는다
    monkeypatch.setenv("WHYMATH_LAYA_INTENT_SHADOW_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("WHYMATH_LAYA_INTENT_SHADOW_API_KEY", "integration-laya-key-0123456789")
    get_settings.cache_clear()


class _Captured:
    def __init__(self) -> None:
        self.coros: list[Coroutine[Any, Any, None]] = []

    def __call__(self, coro: Coroutine[Any, Any, None]) -> None:
        self.coros.append(coro)

    def drive(self) -> None:
        for coro in self.coros:
            asyncio.run(coro)
        self.coros.clear()


def _laya(status: int, body: dict[str, Any] | None = None) -> list[str]:
    """laya 대역 — 받은 요청의 `state`(학생 발화)를 순서대로 돌려준다(원 발화 전송 검증용)."""
    states: list[str] = []

    def _h(r: httpx.Request) -> httpx.Response:
        states.append(json.loads(r.content)["state"])
        return httpx.Response(status, json=body if body is not None else {"detail": "x"})

    shadow.set_client_factory(
        lambda t: httpx.AsyncClient(transport=httpx.MockTransport(_h), timeout=t)
    )
    return states


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = _settings
    return TestClient(app)


def _auth(uid: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(uid, settings=_settings())}"}


def _decision_fields(body: dict[str, Any]) -> dict[str, Any]:
    """학생-대면 결정론 필드만(매 요청 새로 생성되는 id 제외 — wh1 shadow 테스트 동형)."""
    return {
        k: body.get(k)
        for k in ("decision", "misconceptions", "intervention", "lthc", "solution_coaching")
    }


def _session_and_turn(client: TestClient, uid: uuid.UUID) -> tuple[Any, Any]:
    first = client.post("/v1/coach/sessions", headers=_auth(uid), json={"student_input": _FIRST})
    assert first.status_code == 201, first.text
    did = first.json()["dialogue_id"]
    second = client.post(
        f"/v1/coach/sessions/{did}/turns", headers=_auth(uid), json={"student_input": _SECOND}
    )
    assert second.status_code in (200, 201), second.text
    return first, second


def _require_pg() -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")


def test_flag_off_spawns_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _require_pg()
    uid = uuid.uuid4()
    dids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))
        cap = _Captured()
        monkeypatch.setattr(shadow, "_spawn", cap)
        with _client() as client:
            first, _ = _session_and_turn(client, uid)
            dids.append(uuid.UUID(first.json()["dialogue_id"]))
        assert cap.coros == []
    finally:
        asyncio.run(_cleanup(uid, dids))


def test_flag_on_spawns_per_student_turn_response_unchanged_and_intent_matches_db(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _require_pg()
    uid = uuid.uuid4()
    dids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))
        cap = _Captured()
        monkeypatch.setattr(shadow, "_spawn", cap)
        with _client() as client:
            off_first, off_second = _session_and_turn(client, uid)
            dids.append(uuid.UUID(off_first.json()["dialogue_id"]))
        assert cap.coros == []

        _enable(monkeypatch)
        sent_states = _laya(200, _OK_BODY)
        with _client() as client:
            on_first, on_second = _session_and_turn(client, uid)
            on_did = uuid.UUID(on_first.json()["dialogue_id"])
            dids.append(on_did)
        # 학생 턴 2개(세션 생성·턴 추가) → spawn 2회. 응답은 이미 반환된 상태다(비차단).
        assert len(cap.coros) == 2
        # 노출 불변 — 섀도를 켜도 학생-대면 결정 필드는 꺼졌을 때와 같다.
        assert _decision_fields(off_first.json()) == _decision_fields(on_first.json())
        assert _decision_fields(off_second.json()) == _decision_fields(on_second.json())

        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            cap.drive()
        recs = [json.loads(r.getMessage()) for r in caplog.records if r.name == _RECORD_LOGGER]
        assert [r["route"] for r in recs] == ["create_session", "append_turns"]
        # 보낸 것은 *원 발화*다(풀이·암호문·다른 턴의 발화가 아니다)
        assert sent_states == [_FIRST, _SECOND]
        assert all(r["laya_intent"] == "answer_only" and r["failure"] is None for r in recs)
        # 레코드의 규칙 의도 == DB에 실제로 적재된 student_intent (같은 값을 비교해야 의미가 있다)
        stored = asyncio.run(_stored_student_intents(on_did))
        assert [r["rule_intent"] for r in recs] == stored
    finally:
        asyncio.run(_cleanup(uid, dids))


def test_laya_failure_never_breaks_turns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _require_pg()
    uid = uuid.uuid4()
    dids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))
        cap = _Captured()
        monkeypatch.setattr(shadow, "_spawn", cap)
        _enable(monkeypatch)
        _laya(503)
        with _client() as client:
            first, _ = _session_and_turn(client, uid)  # 201/200 단언 포함
            dids.append(uuid.UUID(first.json()["dialogue_id"]))
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            cap.drive()
        recs = [json.loads(r.getMessage()) for r in caplog.records if r.name == _RECORD_LOGGER]
        assert len(recs) == 2
        assert all(r["failure"] == "HTTPStatusError" and r["http_status"] == 503 for r in recs)
    finally:
        asyncio.run(_cleanup(uid, dids))


def test_real_spawn_does_not_block_the_response(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """실제 `_spawn`(create_task) 경로 — laya가 멈춰 있어도 학생 응답은 먼저 돌아온다.

    다른 테스트는 `_spawn`을 캡처기로 바꿔 '구조상 비차단'만 본다. 여기서는 바꾸지 않고, laya 대역이
    `release` 신호를 받을 때까지 멈추게 한다. 응답이 섀도를 기다렸다면 요청이 30초 대기에 걸린다.
    """
    _require_pg()
    uid = uuid.uuid4()
    dids: list[uuid.UUID] = []
    entered = threading.Event()
    release = threading.Event()

    async def _hold(_r: httpx.Request) -> httpx.Response:
        entered.set()
        await asyncio.to_thread(release.wait, 30)
        return httpx.Response(200, json=_OK_BODY)

    try:
        asyncio.run(_add_user(uid))
        _enable(monkeypatch)
        shadow.set_client_factory(
            lambda t: httpx.AsyncClient(transport=httpx.MockTransport(_hold), timeout=t)
        )
        monkeypatch.setenv("WHYMATH_LAYA_INTENT_SHADOW_TIMEOUT_S", "30")
        get_settings.cache_clear()
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER), _client() as client:
            started = time.monotonic()
            resp = client.post(
                "/v1/coach/sessions", headers=_auth(uid), json={"student_input": _FIRST}
            )
            elapsed = time.monotonic() - started
            assert resp.status_code == 201, resp.text
            dids.append(uuid.UUID(resp.json()["dialogue_id"]))
            # 응답이 돌아온 시점에 laya는 아직 풀려나지 않았다 — 응답이 섀도를 기다리지 않았다
            assert not release.is_set()
            assert elapsed < 20, f"응답이 섀도 대기에 걸렸다: {elapsed:.1f}s"
            assert entered.wait(10), "섀도 task가 시작되지 않았다"
            release.set()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if any(r.name == _RECORD_LOGGER for r in caplog.records):
                    break
                time.sleep(0.05)
        recs = [json.loads(r.getMessage()) for r in caplog.records if r.name == _RECORD_LOGGER]
        assert len(recs) == 1 and recs[0]["failure"] is None
    finally:
        release.set()
        asyncio.run(_cleanup(uid, dids))
