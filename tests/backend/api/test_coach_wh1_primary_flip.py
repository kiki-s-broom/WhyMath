"""coach 세션/턴 WH-1 primary flip 통합테스트 — S1-11 (기본 SKIP·실 PG·mock LLM).

`POST /v1/coach/sessions`(+`/turns`)가 `wh1_primary_enabled`에 따라 학생-대면 발화를 WH-1
하네스 LLM 발화로 승격하는지 검증한다(`test_coach_wh1_shadow.py` 패턴 답습·실 PG 미도달 시 skip).

검증 항목(사인오프 방침 매핑):
- 플래그 OFF(기본) → primary 러너 호출 0회·발화는 정적 Polya 템플릿(비트동일·회귀 0) — 방침 ①.
- 플래그 ON → 응답 `decision.prompt`·DB AI 턴 content가 하네스 발화로 대체 — 방침 ① flip.
- 톤필터: 위반 발화는 rewritten 텍스트로 노출(금지 패턴 미노출) — 방침 ③.
- 러너 실패 → 결정론 템플릿 폴백·응답 201(앱은 죽지 않는다) — 방침 ④.
- 관측 연속: primary on에서도 shadow 레코드 계약으로 emit(`primary=True`) — 방침 ⑤.
- 멀티턴(append)도 동형 — dialogue_id·turn_index 관측 메타 유지.

**라이브 0**: `coach.run_wh1_primary_turn`을 감싸 스텁 provider를 강제 주입한다(mock LLM·네트워크
0). **게이트 토글**: 핸들러가 실 `get_settings()`(모듈 직호출)를 읽으므로 env+cache_clear.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.api import coach
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.user import UserProfile
from whymath_backend.harness import wh1_primary
from whymath_backend.harness.wh1_shadow import Wh1HarnessShadowObservation
from whymath_backend.l3.models import GenerationResult
from whymath_backend.l4.polya.prompts import STAGE_PROMPTS
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

pytestmark = pytest.mark.integration

_SECRET = "integration-jwt-secret-0123456789abcdef"
_RECORD_LOGGER = "whymath.harness.wh1_shadow.record"
_STUDENT_INPUT = "이 문제 어떻게 시작해야 할지 모르겠어요"
_STATIC_PROMPTS = frozenset(sp.prompt for sp in STAGE_PROMPTS.values())
# mock LLM이 실을 하네스 발화 — 정적 템플릿 4종 어디에도 없는 고유 문장(승격 판별용).
_LLM_UTTERANCE = "네 풀이에서 어떤 가정을 세웠는지 한 가지만 짚어 말해줄래? ZZFLIPZZ"
_TONE_BAD_UTTERANCE = "그 방식은 틀렸어. 처음부터 다시 해."


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


async def _cleanup(uid: uuid.UUID, dialogue_ids: list[uuid.UUID]) -> None:
    engine = create_async_engine(_settings().database_url)
    dids = [str(d) for d in dialogue_ids]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM dialogue_turn WHERE dialogue_id = ANY(:ids)"),
                {"ids": dids},
            )
            await conn.execute(
                text("DELETE FROM attempt_event WHERE user_id = :uid"),
                {"uid": str(uid)},
            )
            await conn.execute(
                text("DELETE FROM misconception_hypothesis WHERE user_id = :uid"),
                {"uid": str(uid)},
            )
            await conn.execute(
                text("DELETE FROM dialogue WHERE dialogue_id = ANY(:ids)"),
                {"ids": dids},
            )
            # EOS-131: 서버 유휴 규칙 세션(user_profile의 자식) — user 삭제 전에 지운다.
            await conn.execute(
                text("DELETE FROM learning_session WHERE user_id = :uid"),
                {"uid": str(uid)},
            )
            await conn.execute(
                text("DELETE FROM user_profile WHERE user_id = :uid"),
                {"uid": str(uid)},
            )
    finally:
        await engine.dispose()


def _enable_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    """WH-1 primary flip 토글 ON — env+cache_clear."""
    monkeypatch.setenv("WHYMATH_WH1_PRIMARY_ENABLED", "true")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _restore_settings_cache() -> Iterator[None]:
    yield
    get_settings.cache_clear()


class _StubProvider:
    """스크립트된 end_turn JSON만 돌려주는 L3 provider 대역(mock LLM·네트워크 0)."""

    def __init__(self, utterance: str) -> None:
        self._utterance = utterance

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: object,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        payload = (
            '{"kind": "end_turn", "action_type": "질문", "utterance": "' + self._utterance + '"}'
        )
        return GenerationResult(payload)


def _patch_primary_provider(
    monkeypatch: pytest.MonkeyPatch, *, utterance: str = _LLM_UTTERANCE
) -> list[dict[str, Any]]:
    """primary 러너를 감싸 스텁 provider 강제 주입 + 호출 kwargs 기록(스파이)."""
    original = wh1_primary.run_wh1_primary_turn
    calls: list[dict[str, Any]] = []

    async def _wrapped(**kwargs: Any) -> str | None:
        calls.append(dict(kwargs))
        kwargs["provider"] = _StubProvider(utterance)
        return await original(**kwargs)

    monkeypatch.setattr(coach, "run_wh1_primary_turn", _wrapped)
    return calls


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = _settings
    return TestClient(app)


def _auth(uid: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(uid, settings=_settings())}"}


def _records(caplog: pytest.LogCaptureFixture) -> list[Wh1HarnessShadowObservation]:
    return [
        Wh1HarnessShadowObservation.model_validate_json(r.getMessage())
        for r in caplog.records
        if r.name == _RECORD_LOGGER
    ]


# ──────────────────────────────────────────────────────────────────────────
# ① 플래그 OFF(기본) → primary 러너 미호출·정적 템플릿(비트동일·회귀 0)
# ──────────────────────────────────────────────────────────────────────────
def test_flag_off_runner_not_called_static_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    uid = uuid.uuid4()
    dialogue_ids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))
        calls = _patch_primary_provider(monkeypatch)
        monkeypatch.setenv("WHYMATH_WH1_PRIMARY_ENABLED", "false")  # OFF 명시(기본 ON·GA)
        get_settings.cache_clear()
        with _client() as client:
            resp = client.post(
                "/v1/coach/sessions", headers=_auth(uid), json={"student_input": _STUDENT_INPUT}
            )
            assert resp.status_code == 201, resp.text
            dialogue_ids.append(uuid.UUID(resp.json()["dialogue_id"]))
        assert calls == []  # OFF → primary 러너 호출 0(LLM 비용 0·완전 되돌리기)
        assert resp.json()["decision"]["prompt"] in _STATIC_PROMPTS  # 결정론 템플릿 그대로
    finally:
        asyncio.run(_cleanup(uid, dialogue_ids))


# ──────────────────────────────────────────────────────────────────────────
# ② 플래그 ON → 하네스 발화가 응답·DB AI 턴에 실리고 관측 레코드가 primary=True
# ──────────────────────────────────────────────────────────────────────────
def test_flag_on_serves_harness_utterance_and_persists(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    uid = uuid.uuid4()
    dialogue_ids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))
        calls = _patch_primary_provider(monkeypatch)
        _enable_primary(monkeypatch)
        with _client() as client:
            with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
                resp = client.post(
                    "/v1/coach/sessions",
                    headers=_auth(uid),
                    json={"student_input": _STUDENT_INPUT},
                )
            assert resp.status_code == 201, resp.text
            did = uuid.UUID(resp.json()["dialogue_id"])
            dialogue_ids.append(did)

            # flip: 응답 발화 = 하네스 LLM 발화(정적 템플릿 아님) — 방침 ① 발화 승격.
            assert resp.json()["decision"]["prompt"] == _LLM_UTTERANCE
            assert resp.json()["decision"]["prompt"] not in _STATIC_PROMPTS
            assert len(calls) == 1  # 러너 1회(동기·본류)

            # DB AI 턴 content = 학생이 실제 본 발화(하네스 발화) — 저장·노출 정합.
            detail = client.get(f"/v1/coach/sessions/{did}", headers=_auth(uid))
            assert detail.status_code == 200, detail.text
            turns = detail.json()["turns"]
            assistant = [t for t in turns if t["role"] == "assistant"]
            assert len(assistant) == 1
            assert assistant[0]["content"] == _LLM_UTTERANCE

        # 관측 연속(방침 ⑤): primary on에서도 shadow 레코드 계약으로 emit·primary=True 회계.
        records = _records(caplog)
        assert len(records) == 1
        assert records[0].primary is True
        assert records[0].status == "ended"
    finally:
        asyncio.run(_cleanup(uid, dialogue_ids))


# ──────────────────────────────────────────────────────────────────────────
# ③ 톤필터 — 위반 발화는 rewritten 텍스트로 노출(금지 패턴 미노출·KPI3 관측)
# ──────────────────────────────────────────────────────────────────────────
def test_flag_on_tone_violation_served_rewritten(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    uid = uuid.uuid4()
    dialogue_ids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))
        _patch_primary_provider(monkeypatch, utterance=_TONE_BAD_UTTERANCE)
        _enable_primary(monkeypatch)
        with _client() as client:
            with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
                resp = client.post(
                    "/v1/coach/sessions",
                    headers=_auth(uid),
                    json={"student_input": _STUDENT_INPUT},
                )
            assert resp.status_code == 201, resp.text
            dialogue_ids.append(uuid.UUID(resp.json()["dialogue_id"]))
        served = resp.json()["decision"]["prompt"]
        assert "틀렸" not in served  # 금지 패턴 미노출(정서 안전·CLAUDE.md 금기)
        assert "다시 봐도 좋아" in served  # filter_tone 권장 표현 치환분이 실제 노출
        records = _records(caplog)
        assert len(records) == 1
        assert records[0].tone_rewritten is True  # 위반 사실의 관측 기록(KPI3 좌석)
        assert records[0].tone_violations == 1
    finally:
        asyncio.run(_cleanup(uid, dialogue_ids))


# ──────────────────────────────────────────────────────────────────────────
# ④ 러너 실패 → 결정론 템플릿 폴백·201(가용성 — 앱은 죽지 않는다)
# ──────────────────────────────────────────────────────────────────────────
def test_flag_on_runner_failure_falls_back_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    uid = uuid.uuid4()
    dialogue_ids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))

        async def _boom(**_kwargs: Any) -> str | None:
            raise RuntimeError("primary 러너 실패(폴백 테스트)")

        monkeypatch.setattr(coach, "run_wh1_primary_turn", _boom)
        _enable_primary(monkeypatch)
        with _client() as client:
            resp = client.post(
                "/v1/coach/sessions", headers=_auth(uid), json={"student_input": _STUDENT_INPUT}
            )
            assert resp.status_code == 201, resp.text  # 폴백 — 500 아님(방침 ④)
            did = uuid.UUID(resp.json()["dialogue_id"])
            dialogue_ids.append(did)
            assert resp.json()["decision"]["prompt"] in _STATIC_PROMPTS  # 결정론 템플릿 폴백

            # 폴백 시 DB AI 턴도 결정론 템플릿(학생이 본 것과 저장이 일치). 저장 스키마가
            # content 후행 공백을 strip하는 기존 동작(flip 무관)이라 strip 기준으로 비교한다.
            detail = client.get(f"/v1/coach/sessions/{did}", headers=_auth(uid))
            assistant = [t for t in detail.json()["turns"] if t["role"] == "assistant"]
            assert assistant[0]["content"].strip() in {p.strip() for p in _STATIC_PROMPTS}
    finally:
        asyncio.run(_cleanup(uid, dialogue_ids))


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 멀티턴(append)도 동형 — 발화 승격 + dialogue_id·turn_index 관측 메타
# ──────────────────────────────────────────────────────────────────────────
def test_append_turns_flip_serves_utterance_with_meta(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    uid = uuid.uuid4()
    dialogue_ids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))
        _patch_primary_provider(monkeypatch)

        # 세션은 OFF에서 생성(결정론) — append의 flip만 고립 관측. (기본 ON·GA라 OFF 명시)
        monkeypatch.setenv("WHYMATH_WH1_PRIMARY_ENABLED", "false")
        get_settings.cache_clear()
        with _client() as client:
            created = client.post(
                "/v1/coach/sessions", headers=_auth(uid), json={"student_input": _STUDENT_INPUT}
            )
            assert created.status_code == 201, created.text
            did = uuid.UUID(created.json()["dialogue_id"])
            dialogue_ids.append(did)
            assert created.json()["decision"]["prompt"] in _STATIC_PROMPTS

            _enable_primary(monkeypatch)
            with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
                on = client.post(
                    f"/v1/coach/sessions/{did}/turns",
                    headers=_auth(uid),
                    json={"student_input": _STUDENT_INPUT},
                )
            assert on.status_code == 201, on.text
            assert on.json()["decision"]["prompt"] == _LLM_UTTERANCE  # 멀티턴도 발화 승격

        records = _records(caplog)
        assert len(records) == 1
        assert records[0].primary is True
        assert records[0].dialogue_id == str(did)
        assert records[0].turn_index >= 2  # 멀티턴 인덱스(관측 메타 유지)
    finally:
        asyncio.run(_cleanup(uid, dialogue_ids))
