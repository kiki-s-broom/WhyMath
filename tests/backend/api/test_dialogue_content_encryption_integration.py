"""미성년 대화 본문·멀티모달 봉투 암호화 통합테스트 — 실 PG (감사상환 #2 · SEC-01 · 기본 SKIP).

키 설정 시: `POST /v1/coach/sessions` write가 DB `content=NULL`·`content_encrypted=bytes`로
저장(평문 원문 부재), GET·export가 복호해 원문 반환. 키 미설정 시: 평문 폴백 왕복(기존 배포·CI
무영향·회귀 0). 백필: 평문 행을 배치 재암호화 후 복호 왕복.

SEC-01: 손글씨 `image_uri`·Qwen3-VL `image_analysis`도 같은 키로 암호화된다. 이 축은 실 PG에서만
검증 가능한 것이 있다 — 마이그레이션이 만든 **LargeBinary 컬럼**과 JSONB 평문 컬럼이 실제로
붙어 있는지, 그리고 export가 그 둘을 복호해 싣는지는 hermetic으로는 증명되지 않는다.

get_settings 캐시: 코치 핸들러·export는 *직접* `get_settings()`(env 기반·lru_cache)를 부르고
auth만 Depends 오버라이드를 쓴다(기존 통합테스트 아키텍처). 따라서 대화 키는 **env + cache_clear**
로 주입하고, auth jwt는 dependency_overrides로 준다. finally에서 env·캐시를 원복(격리).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.api._crypto import build_dialogue_content_cipher
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.user import UserProfile
from whymath_backend.privacy.dialogue_content_backfill import (
    reencrypt_plaintext_dialogue_content,
)
from whymath_backend.privacy.export import export_user_data
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

pytestmark = pytest.mark.integration

_SECRET = "integration-jwt-secret-0123456789abcdef"
_ENC_KEY_B64 = base64.b64encode(os.urandom(32)).decode()
_STUDENT_TEXT = "내 풀이는 (a+b)² = a² + b² 이렇게 했어"


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_SECRET))


@contextmanager
def _dialogue_key_env(key_b64: str | None) -> Iterator[None]:
    """대화 본문 암호화 키를 env로 주입(또는 제거)하고 get_settings 캐시를 리셋·원복."""
    var = "WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY"
    prev = os.environ.get(var)
    if key_b64 is None:
        os.environ.pop(var, None)
    else:
        os.environ[var] = key_b64
    get_settings.cache_clear()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = prev
        get_settings.cache_clear()


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
                text("DELETE FROM dialogue_turn WHERE dialogue_id = ANY(:ids)"), {"ids": dids}
            )
            await conn.execute(
                text("DELETE FROM attempt_event WHERE user_id = :uid"), {"uid": str(uid)}
            )
            await conn.execute(
                text("DELETE FROM misconception_hypothesis WHERE user_id = :uid"), {"uid": str(uid)}
            )
            await conn.execute(
                text("DELETE FROM dialogue WHERE dialogue_id = ANY(:ids)"), {"ids": dids}
            )
            # EOS-131: 서버 유휴 규칙 세션(user_profile의 자식) — user 삭제 전에 지운다.
            await conn.execute(
                text("DELETE FROM learning_session WHERE user_id = :uid"), {"uid": str(uid)}
            )
            await conn.execute(
                text("DELETE FROM user_profile WHERE user_id = :uid"), {"uid": str(uid)}
            )
    finally:
        await engine.dispose()


async def _turn_storage(
    dialogue_id: uuid.UUID,
) -> list[tuple[str | None, bytes | None, bytes | None]]:
    """dialogue_turn의 (content, content_encrypted, content_nonce) 원시 저장 표현(turn_order순)."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT content, content_encrypted, content_nonce FROM dialogue_turn "
                    "WHERE dialogue_id = :did ORDER BY turn_order"
                ),
                {"did": str(dialogue_id)},
            )
            out: list[tuple[str | None, bytes | None, bytes | None]] = []
            for r in rows.all():
                enc = bytes(r[1]) if r[1] is not None else None
                nonce = bytes(r[2]) if r[2] is not None else None
                out.append((r[0], enc, nonce))
            return out
    finally:
        await engine.dispose()


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = _settings
    return TestClient(app)


def test_key_set_stores_ciphertext_and_reads_plaintext_on_live_pg() -> None:
    """키 설정 시: DB content=NULL·content_encrypted=bytes(프라이버시 단언)·GET/export 복호 원문."""  # noqa: E501
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    uid = uuid.uuid4()
    dialogue_ids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _dialogue_key_env(_ENC_KEY_B64), _client() as client:
            resp = client.post(
                "/v1/coach/sessions", headers=auth, json={"student_input": _STUDENT_TEXT}
            )
            assert resp.status_code == 201, resp.text
            did = uuid.UUID(resp.json()["dialogue_id"])
            dialogue_ids.append(did)

            # 프라이버시 단언: 평문 content 컬럼은 NULL, content_encrypted는 bytes(원문 부재).
            storage = asyncio.run(_turn_storage(did))
            assert len(storage) == 2
            for content, encrypted, nonce in storage:
                assert content is None
                assert isinstance(encrypted, bytes) and len(encrypted) > 0
                assert isinstance(nonce, bytes) and len(nonce) == 12

            # GET이 복호해 학생 원문을 그대로 반환(student 턴 = turn_order 1).
            got = client.get(f"/v1/coach/sessions/{did}", headers=auth)
            assert got.status_code == 200
            turns = got.json()["turns"]
            assert turns[0]["content"] == _STUDENT_TEXT

            # export도 복호해 원문 반환(본인 열람권).
            engine = create_async_engine(_settings().database_url)
            try:

                async def _export() -> object:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                        return await export_user_data(s, user_id=uid)

                exported = asyncio.run(_export())
            finally:
                asyncio.run(engine.dispose())
            contents = [t["content"] for t in exported.data["dialogue_turns"]]  # type: ignore[attr-defined]
            assert _STUDENT_TEXT in contents
    finally:
        asyncio.run(_cleanup(uid, dialogue_ids))


def test_key_unset_plaintext_fallback_round_trip_on_live_pg() -> None:
    """키 미설정 시: content 평문 저장·GET 평문 반환(기존 배포·CI 무영향·회귀 0)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    uid = uuid.uuid4()
    dialogue_ids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _dialogue_key_env(None), _client() as client:
            resp = client.post(
                "/v1/coach/sessions", headers=auth, json={"student_input": _STUDENT_TEXT}
            )
            assert resp.status_code == 201, resp.text
            did = uuid.UUID(resp.json()["dialogue_id"])
            dialogue_ids.append(did)

            storage = asyncio.run(_turn_storage(did))
            assert storage[0][0] == _STUDENT_TEXT  # content 평문 저장
            assert storage[0][1] is None and storage[0][2] is None  # 암호화 컬럼 미사용

            got = client.get(f"/v1/coach/sessions/{did}", headers=auth)
            assert got.json()["turns"][0]["content"] == _STUDENT_TEXT
    finally:
        asyncio.run(_cleanup(uid, dialogue_ids))


def test_backfill_reencrypts_plaintext_rows_on_live_pg() -> None:
    """백필: 평문 저장 행을 배치 재암호화 → content=NULL·content_encrypted 세팅·복호 왕복."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    uid = uuid.uuid4()
    dialogue_ids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        # 1) 키 미설정으로 평문 행 생성.
        with _dialogue_key_env(None), _client() as client:
            resp = client.post(
                "/v1/coach/sessions", headers=auth, json={"student_input": _STUDENT_TEXT}
            )
            did = uuid.UUID(resp.json()["dialogue_id"])
            dialogue_ids.append(did)
        pre = asyncio.run(_turn_storage(did))
        assert pre[0][0] == _STUDENT_TEXT and pre[0][1] is None  # 평문 잔존

        # 2) 키 도입 후 백필 배치 → 평문 행 재암호화.
        with _dialogue_key_env(_ENC_KEY_B64):
            cipher = build_dialogue_content_cipher(get_settings())
            assert cipher is not None
            engine = create_async_engine(_settings().database_url)

            async def _run_backfill() -> int:
                total = 0
                while True:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                        n = await reencrypt_plaintext_dialogue_content(s, cipher, batch_size=1)
                    total += n
                    if n == 0:
                        break
                return total

            try:
                reencrypted = asyncio.run(_run_backfill())
            finally:
                asyncio.run(engine.dispose())
            assert reencrypted >= 2  # 학생/AI 2턴 이상 재암호화

            # 3) 재암호화 후 content=NULL·content_encrypted 세팅·GET 복호 원문.
            post = asyncio.run(_turn_storage(did))
            for content, encrypted, nonce in post:
                assert content is None
                assert isinstance(encrypted, bytes) and isinstance(nonce, bytes)
            with _client() as client:
                got = client.get(f"/v1/coach/sessions/{did}", headers=auth)
                assert got.json()["turns"][0]["content"] == _STUDENT_TEXT
    finally:
        asyncio.run(_cleanup(uid, dialogue_ids))


async def _image_turn_storage(
    dialogue_id: uuid.UUID,
) -> list[tuple[str | None, bytes | None, object | None, bytes | None]]:
    """dialogue_turn의 이미지 축 원시 저장 표현 — (uri, uri_enc, analysis, analysis_enc)."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT image_uri, image_uri_encrypted, image_analysis, "
                    "image_analysis_encrypted FROM dialogue_turn "
                    "WHERE dialogue_id = :did AND image_uri_encrypted IS NOT NULL "
                    "ORDER BY turn_order"
                ),
                {"did": str(dialogue_id)},
            )
            out: list[tuple[str | None, bytes | None, object | None, bytes | None]] = []
            for r in rows.all():
                uri_enc = bytes(r[1]) if r[1] is not None else None
                analysis_enc = bytes(r[3]) if r[3] is not None else None
                out.append((r[0], uri_enc, r[2], analysis_enc))
            return out
    finally:
        await engine.dispose()


async def _append_image_turn(
    dialogue_id: uuid.UUID, *, turn_order: int, image_uri: str, analysis: dict[str, object]
) -> None:
    """이미지 축을 가진 턴을 write 좌석(`_build_dialogue_turn`)을 그대로 통과시켜 저장한다.

    HTTP 경로로는 아직 이미지가 안 들어온다(OCR 핸드오프 미배선) — 그러나 저장 좌석은 이미
    하나뿐이므로 그 좌석을 실 세션으로 통과시키면 컬럼·암호화·복호가 실제로 붙는지 검증된다.
    """
    from whymath_backend.api._crypto import require_dialogue_content_cipher
    from whymath_backend.api.coach import _build_dialogue_turn
    from whymath_backend.schema.dialogue import DialogueTurn as DialogueTurnSchema

    cipher = require_dialogue_content_cipher(get_settings())
    assert cipher is not None  # 이 테스트는 키 설정 컨텍스트 안에서만 호출된다
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                _build_dialogue_turn(
                    DialogueTurnSchema(
                        dialogue_id=dialogue_id,
                        turn_order=turn_order,
                        content="이미지 첨부 턴",
                        image_uri=image_uri,
                        image_analysis=analysis,  # type: ignore[arg-type]
                    ),
                    cipher,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


def test_image_axis_stores_ciphertext_and_export_decrypts_on_live_pg() -> None:
    """SEC-01: image_uri·image_analysis가 DB에 평문 없이 저장되고 export가 복호해 싣는다."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    uri = "s3://whymath-handwriting/ab12cd34.png"
    analysis: dict[str, object] = {
        "steps": [{"latex": "(a+b)^2 = a^2 + b^2", "confidence": 0.87}],
        "라벨": "손글씨",
    }
    uid = uuid.uuid4()
    dialogue_ids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _dialogue_key_env(_ENC_KEY_B64):
            with _client() as client:
                resp = client.post(
                    "/v1/coach/sessions", headers=auth, json={"student_input": _STUDENT_TEXT}
                )
                assert resp.status_code == 201, resp.text
                did = uuid.UUID(resp.json()["dialogue_id"])
                dialogue_ids.append(did)

            asyncio.run(_append_image_turn(did, turn_order=3, image_uri=uri, analysis=analysis))

            # 프라이버시 단언: 평문 컬럼 둘 다 NULL, 암호문 컬럼 둘 다 bytes.
            storage = asyncio.run(_image_turn_storage(did))
            assert len(storage) == 1
            uri_plain, uri_enc, analysis_plain, analysis_enc = storage[0]
            assert uri_plain is None and analysis_plain is None
            assert isinstance(uri_enc, bytes) and len(uri_enc) > 0
            assert isinstance(analysis_enc, bytes) and len(analysis_enc) > 0

            # GET이 두 축을 복호해 원본 그대로 반환.
            with _client() as client:
                turns = client.get(f"/v1/coach/sessions/{did}", headers=auth).json()["turns"]
            image_turns = [t for t in turns if t.get("image_uri") is not None]
            assert len(image_turns) == 1
            assert image_turns[0]["image_uri"] == uri
            assert image_turns[0]["image_analysis"] == analysis

            # export(본인 열람권)도 복호 — 빠뜨리면 *부분 export를 완전 export로 위장*하게 된다.
            engine = create_async_engine(_settings().database_url)
            try:

                async def _export() -> object:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                        return await export_user_data(s, user_id=uid)

                exported = asyncio.run(_export())
            finally:
                asyncio.run(engine.dispose())
            rows = exported.data["dialogue_turns"]  # type: ignore[attr-defined]
            assert uri in [t["image_uri"] for t in rows]
            assert analysis in [t["image_analysis"] for t in rows]
    finally:
        asyncio.run(_cleanup(uid, dialogue_ids))


async def _insert_plaintext_image_turn(
    dialogue_id: uuid.UUID, *, turn_order: int, image_uri: str, analysis: dict[str, object]
) -> None:
    """암호화 이전 세계의 행 — 평문 image_uri·image_analysis를 그대로 저장(백필 대상 조성)."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO dialogue_turn (turn_id, dialogue_id, turn_order, image_uri, "
                    "image_analysis) VALUES (:tid, :did, :ord, :uri, CAST(:analysis AS jsonb))"
                ),
                {
                    "tid": str(uuid.uuid4()),
                    "did": str(dialogue_id),
                    "ord": turn_order,
                    "uri": image_uri,
                    "analysis": json.dumps(analysis, ensure_ascii=False),
                },
            )
    finally:
        await engine.dispose()


def test_backfill_covers_image_axis_on_live_pg() -> None:
    """SEC-01: 백필이 이미지 두 축도 전환한다 — 본문만 돌면 *부분 처리를 완전 처리로 위장*한다.

    변별력: 백필 *전* 단언(평문 잔존)과 *후* 단언(평문 NULL·ciphertext 존재)이 짝이라,
    백필이 이미지 축을 건너뛰면 후단언이 실패한다.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    uri = "s3://whymath-handwriting/legacy-plaintext.png"
    analysis: dict[str, object] = {"steps": [{"latex": "x+1"}], "라벨": "구행"}
    uid = uuid.uuid4()
    dialogue_ids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        # 1) 키 미설정으로 대화를 만들고, 평문 이미지 축을 가진 구 행을 직접 심는다.
        with _dialogue_key_env(None), _client() as client:
            resp = client.post(
                "/v1/coach/sessions", headers=auth, json={"student_input": _STUDENT_TEXT}
            )
            did = uuid.UUID(resp.json()["dialogue_id"])
            dialogue_ids.append(did)
        asyncio.run(
            _insert_plaintext_image_turn(did, turn_order=3, image_uri=uri, analysis=analysis)
        )
        assert asyncio.run(_image_turn_storage(did)) == []  # 아직 암호문 없음(평문 잔존)

        # 2) 키 도입 후 백필 → 본문 + 이미지 두 축이 함께 전환돼야 한다.
        with _dialogue_key_env(_ENC_KEY_B64):
            cipher = build_dialogue_content_cipher(get_settings())
            assert cipher is not None
            engine = create_async_engine(_settings().database_url)

            async def _run_backfill() -> int:
                total = 0
                while True:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                        n = await reencrypt_plaintext_dialogue_content(s, cipher, batch_size=10)
                    total += n
                    if n == 0:
                        break
                return total

            try:
                asyncio.run(_run_backfill())
            finally:
                asyncio.run(engine.dispose())

            storage = asyncio.run(_image_turn_storage(did))
            assert len(storage) == 1
            uri_plain, uri_enc, analysis_plain, analysis_enc = storage[0]
            assert uri_plain is None and analysis_plain is None  # 평문 비워짐
            assert isinstance(uri_enc, bytes) and isinstance(analysis_enc, bytes)

            # 복호 왕복 — 백필 직렬화가 저장 좌석과 같은 규칙이어야 원본이 돌아온다.
            with _client() as client:
                turns = client.get(f"/v1/coach/sessions/{did}", headers=auth).json()["turns"]
            restored = [t for t in turns if t.get("image_uri") is not None]
            assert len(restored) == 1
            assert restored[0]["image_uri"] == uri
            assert restored[0]["image_analysis"] == analysis
    finally:
        asyncio.run(_cleanup(uid, dialogue_ids))


async def _insert_jsonb_null_analysis_turns(dialogue_id: uuid.UUID, *, count: int) -> None:
    """`image_analysis`가 **JSONB 스칼라 null**인 행을 심는다(SEC-04 이전 세계의 저장 표현).

    SQL NULL이 아니라 JSON `null`이라 순진한 `IS NOT NULL` 술어에 걸린다 — 굶주림의 재료.
    """
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.begin() as conn:
            for order in range(10, 10 + count):  # 기존 대화 턴(1~2)과 순번 충돌 회피
                await conn.execute(
                    text(
                        "INSERT INTO dialogue_turn (turn_id, dialogue_id, turn_order, "
                        "image_analysis) VALUES (:tid, :did, :ord, 'null'::jsonb)"
                    ),
                    {"tid": str(uuid.uuid4()), "did": str(dialogue_id), "ord": order},
                )
    finally:
        await engine.dispose()


def test_backfill_is_not_starved_by_jsonb_null_rows_on_live_pg() -> None:
    """SEC-04: JSONB null 행이 LIMIT 창을 채워도 진짜 평문 행이 반드시 암호화된다.

    **변별력**: 술어에서 `jsonb_typeof(...) != 'null'`을 빼면 백필이 "0행 처리"(=완료)를
    보고하면서 미성년 평문 본문이 그대로 남는다 — *부분 처리를 완전 처리로 위장*하는 실패다
    (2026-07-28 실 PG 재현으로 발견). batch_size를 JSONB null 행 수보다 작게 잡아 굶주림
    조건을 강제한다.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    uid = uuid.uuid4()
    dialogue_ids: list[uuid.UUID] = []
    plaintext = "굶주림 재현용 미성년 평문 본문"
    try:
        asyncio.run(_add_user(uid))
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _dialogue_key_env(None), _client() as client:
            resp = client.post(
                "/v1/coach/sessions", headers=auth, json={"student_input": plaintext}
            )
            assert resp.status_code == 201, resp.text
            did = uuid.UUID(resp.json()["dialogue_id"])
            dialogue_ids.append(did)
        # 평문 본문 행(위 2턴)보다 앞 순번에 JSONB null 행을 다수 심어 LIMIT 창을 채운다.
        asyncio.run(_insert_jsonb_null_analysis_turns(did, count=5))

        with _dialogue_key_env(_ENC_KEY_B64):
            cipher = build_dialogue_content_cipher(get_settings())
            assert cipher is not None
            engine = create_async_engine(_settings().database_url)

            async def _run_backfill() -> int:
                total = 0
                for _ in range(20):  # 상한 — 무한 루프면 테스트가 매달리지 않고 끝난다
                    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                        n = await reencrypt_plaintext_dialogue_content(s, cipher, batch_size=3)
                    total += n
                    if n == 0:
                        break
                return total

            try:
                asyncio.run(_run_backfill())

            finally:
                asyncio.run(engine.dispose())

            # 별도 엔진 — 풀을 다른 이벤트 루프에서 재사용하면 asyncpg가 거부한다(파일 관용).
            async def _remaining_plaintext() -> int:
                probe = create_async_engine(_settings().database_url)
                try:
                    async with probe.connect() as conn:
                        row = await conn.execute(
                            text(
                                "SELECT count(*) FROM dialogue_turn WHERE dialogue_id = :did "
                                "AND content IS NOT NULL AND content_encrypted IS NULL"
                            ),
                            {"did": str(did)},
                        )
                        return int(row.scalar_one())
                finally:
                    await probe.dispose()

            remaining = asyncio.run(_remaining_plaintext())

            # 굶주림이 있으면 여기서 > 0 — CLI는 완료를 보고했는데 평문이 남은 상태.
            assert remaining == 0, f"평문 본문 {remaining}행이 백필되지 않고 남았다(굶주림)"
    finally:
        asyncio.run(_cleanup(uid, dialogue_ids))


def test_no_analysis_turn_stores_sql_null_not_jsonb_null_on_live_pg() -> None:
    """SEC-04 근원 수정 — 분석 없는 턴은 JSONB `null`이 아니라 **SQL NULL**로 저장된다.

    JSONB null이면 배포 실측 쿼리(§3)가 그 행을 *평문 데이터 보유*로 오계수해 "암호화 안 됨"
    거짓경보를 낸다.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    uid = uuid.uuid4()
    dialogue_ids: list[uuid.UUID] = []
    try:
        asyncio.run(_add_user(uid))
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _dialogue_key_env(_ENC_KEY_B64), _client() as client:
            resp = client.post(
                "/v1/coach/sessions", headers=auth, json={"student_input": _STUDENT_TEXT}
            )
            did = uuid.UUID(resp.json()["dialogue_id"])
            dialogue_ids.append(did)

        async def _jsonb_null_count() -> int:
            engine = create_async_engine(_settings().database_url)
            try:
                async with engine.connect() as conn:
                    row = await conn.execute(
                        text(
                            "SELECT count(*) FROM dialogue_turn WHERE dialogue_id = :did "
                            "AND jsonb_typeof(image_analysis) = 'null'"
                        ),
                        {"did": str(did)},
                    )
                    return int(row.scalar_one())
            finally:
                await engine.dispose()

        assert asyncio.run(_jsonb_null_count()) == 0
    finally:
        asyncio.run(_cleanup(uid, dialogue_ids))
