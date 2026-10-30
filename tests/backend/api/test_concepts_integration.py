"""concept API 통합테스트 — 실제 PostgreSQL 왕복 (기본 SKIP, Phaiakes9/로컬 전용).

`WHYMATH_RUN_INTEGRATION=1` + 살아있는 PG(마이그레이션 head 적용, WHYMATH_DATABASE_URL)
에서만 실행한다. CI는 이 변수를 설정하지 않아 conftest 게이트가 자동 skip한다. PG 미도달
시에도 graceful skip(redis 통합테스트와 동일 패턴).

검증: POST → GET(단건) → 중복 POST(409) → GET(목록)이 *실 PG*에서 HTTP→get_session→PG로
왕복하는지 — 영속 레이어(ORM·마이그레이션)를 HTTP 표면까지 end-to-end로 결선했음을 증명.
TestClient를 컨텍스트매니저로 써 lifespan(종료 시 dispose_engine)도 함께 발화시킨다.

설정/정리는 전역 캐시 엔진이 아니라 *독립 엔진*으로 수행한다 — TestClient가 자기 이벤트
루프에서 만든 전역 엔진과 루프가 충돌하지 않도록(asyncpg 엔진은 루프 바인딩).

인가(SEC-07 D1): CUD(POST/PATCH/DELETE)는 이제 `Role.CONTENT_ADMIN` 인증이 필요하다.
`test_users_integration.py` 패턴 답습 — `get_settings`를 고정 시크릿으로 오버라이드해 토큰
mint(테스트)와 decode(앱)가 같은 시크릿을 쓰게 하고, 실 PG에 CONTENT_ADMIN
UserProfile 행을 만들어 `get_current_user`가 그 행을 로드하게 한다(get_session은 실제 —
인증→DB 사용자 로드까지 end-to-end). GET은 헤더 없이 호출해 무인증 유지를 함께 확인한다.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.cms_edit_marker import mark_cms_edited
from whymath_backend.db.models.concept import Concept
from whymath_backend.db.models.user import UserProfile
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.enums import Persona, Role
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

pytestmark = pytest.mark.integration

_JWT_SECRET = "concepts-integration-jwt-secret-0123456789ab"


def _jwt_settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_JWT_SECRET))


async def _pg_reachable() -> bool:
    """독립 엔진으로 SELECT 1 — 도달 가능하면 True(실패는 False)."""
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def _insert_content_admin(user_id: uuid.UUID) -> None:
    """CONTENT_ADMIN UserProfile 행을 실 PG에 적재(get_current_user의 실 로드 대상)."""
    engine = create_async_engine(Settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                UserProfile.from_schema(
                    UserProfileSchema(
                        user_id=user_id,
                        persona_primary=Persona.A_일반고고3,
                        role=Role.CONTENT_ADMIN,
                    )
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _delete_user(user_id: uuid.UUID) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM user_profile WHERE user_id = :uid"),
                {"uid": str(user_id)},
            )
    finally:
        await engine.dispose()


@pytest.fixture
def admin_auth() -> Iterator[dict[str, str]]:
    """CONTENT_ADMIN 사용자를 실 PG에 만들고 `Authorization` 헤더를 yield(테스트 후 정리).

    PG 미도달이면 각 테스트 본문의 `_pg_reachable` 체크가 skip을 던지므로, 여기서도 먼저
    확인해 미도달 환경에서 불필요한 삽입 시도를 하지 않는다(그래도 실패하면 그대로 skip).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    admin_id = uuid.uuid4()
    asyncio.run(_insert_content_admin(admin_id))
    token = create_access_token(admin_id, settings=_jwt_settings())
    try:
        yield {"Authorization": f"Bearer {token}"}
    finally:
        asyncio.run(_delete_user(admin_id))


def _app_with_jwt_settings() -> TestClient:
    """get_settings만 고정 시크릿으로 오버라이드(get_session은 실 PG 그대로)."""
    app = create_app()
    app.dependency_overrides[get_settings] = _jwt_settings
    return TestClient(app)


async def _seed_concept(code: str, name_ko: str, level: str, *, cms_owned: bool = False) -> str:
    """개념 1건을 직접 심는다(적재 CLI가 하듯). `POST /v1/concepts`는 P3-26부터 폐지(410)라 픽스처에 못 쓴다.

    기본은 *적재가 소유한* 행(표지 없음). `cms_owned=True`면 CMS가 만든 행(삭제가 허용되는 유일한 부류).
    """
    row = Concept.from_schema(ConceptSchema(code=code, name_ko=name_ko, level=level))
    if cms_owned:
        mark_cms_edited(row)
    engine = create_async_engine(Settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(row)
            await session.commit()
            return str(row.concept_id)
    finally:
        await engine.dispose()


async def _delete_concept(concept_id: uuid.UUID) -> None:
    """테스트가 만든 행을 독립 엔진으로 정리(잔여 방지)."""
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM concept WHERE concept_id = :cid"),
                {"cid": str(concept_id)},
            )
    finally:
        await engine.dispose()


async def _insert_edge(from_id: uuid.UUID, to_id: uuid.UUID) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO concept_edge (from_concept_id, to_concept_id, edge_type) "
                    "VALUES (:f, :t, 'PREREQUISITE')"
                ),
                {"f": str(from_id), "t": str(to_id)},
            )
    finally:
        await engine.dispose()


async def _delete_concepts_and_edges(concept_ids: list[uuid.UUID]) -> None:
    engine = create_async_engine(Settings().database_url)
    ids = [str(c) for c in concept_ids]
    try:
        async with engine.begin() as conn:
            # FK 순서: 엣지 먼저, 그다음 노드
            await conn.execute(
                text(
                    "DELETE FROM concept_edge WHERE from_concept_id = ANY(:ids) "
                    "OR to_concept_id = ANY(:ids)"
                ),
                {"ids": ids},
            )
            await conn.execute(
                text("DELETE FROM concept WHERE concept_id = ANY(:ids)"),
                {"ids": ids},
            )
    finally:
        await engine.dispose()


def test_concept_edges_nested_read_on_live_pg(admin_auth: dict[str, str]) -> None:
    """GET /concepts/{id}/edges가 outgoing 엣지를 실 PG에서 반환·방향·404 검증."""
    suffix = uuid.uuid4().hex[:8]
    ids: list[str] = []
    try:
        with _app_with_jwt_settings() as client:
            client.headers.update(admin_auth)
            a = asyncio.run(_seed_concept(f"CG-A-{suffix}", "가", "단원"))
            ids = [a]
            b = asyncio.run(_seed_concept(f"CG-B-{suffix}", "나", "단원"))
            ids = [a, b]
            asyncio.run(_insert_edge(uuid.UUID(a), uuid.UUID(b)))

            # a의 나가는 엣지 1건(→b)
            edges = client.get(f"/v1/concepts/{a}/edges")
            assert edges.status_code == 200
            body = edges.json()
            assert len(body) == 1
            assert body[0]["to_concept_id"] == b

            # b는 나가는 엣지 없음 → [](방향성 확인)
            assert client.get(f"/v1/concepts/{b}/edges").json() == []

            # 없는 개념 → 404
            assert client.get(f"/v1/concepts/{uuid.uuid4()}/edges").status_code == 404
    finally:
        if ids:
            asyncio.run(_delete_concepts_and_edges([uuid.UUID(c) for c in ids]))


def test_concept_crud_roundtrip_on_live_pg(admin_auth: dict[str, str]) -> None:
    """직접 생성 폐지(410)→GET→목록이 실 PG에서 HTTP→get_session→PG로 왕복한다(P3-26)."""
    code = f"TEST-CONCEPT-{uuid.uuid4().hex[:8]}"
    body = {"code": code, "name_ko": "통합테스트 개념", "level": "세부개념"}
    concept_id: str | None = None
    try:
        with _app_with_jwt_settings() as client:
            client.headers.update(admin_auth)
            # CREATE → 410: 살아있는 개념 행을 검수 없이 만드는 길은 닫혔고, 아무 행도 생기지 않는다.
            created = client.post("/v1/concepts", json=body)
            assert created.status_code == 410, created.text
            assert created.json()["detail"]["code"] == "concept_create_via_workflow"
            assert client.get("/v1/concepts?limit=200").status_code == 200
            assert code not in {i["code"] for i in client.get("/v1/concepts?limit=200").json()}

            # 적재가 만든 행을 모사해 심고 READ → 200, 내용 일치
            concept_id = asyncio.run(_seed_concept(code, "통합테스트 개념", "세부개념"))
            got = client.get(f"/v1/concepts/{concept_id}")
            assert got.status_code == 200
            assert got.json()["name_ko"] == "통합테스트 개념"

            # LIST → 200, 방금 만든 code 포함
            listed = client.get("/v1/concepts?limit=200")
            assert listed.status_code == 200
            assert code in {item["code"] for item in listed.json()}
    finally:
        if concept_id is not None:
            asyncio.run(_delete_concept(uuid.UUID(concept_id)))


def test_concept_patch_delete_roundtrip_on_live_pg(admin_auth: dict[str, str]) -> None:
    """POST→PATCH(부분수정)→GET(반영확인)→DELETE(204)→GET(404)이 실 PG에서 왕복."""
    code = f"TEST-PATCH-{uuid.uuid4().hex[:8]}"
    concept_id: str | None = None
    deleted = False
    try:
        with _app_with_jwt_settings() as client:
            client.headers.update(admin_auth)
            # CMS가 만든 개념(표지 있음)만 지울 수 있다 — 적재 소유 개념의 삭제 거부는 아래에서 따로 본다.
            concept_id = asyncio.run(_seed_concept(code, "원본", "단원", cms_owned=True))

            # PATCH: name_en만 추가(부분 수정), 병합 재검증
            patched = client.patch(f"/v1/concepts/{concept_id}", json={"name_en": "Patched"})
            assert patched.status_code == 200, patched.text
            assert patched.json()["name_en"] == "Patched"
            assert patched.json()["name_ko"] == "원본"  # 기존 필드 보존

            # GET으로 영속 반영 확인
            assert client.get(f"/v1/concepts/{concept_id}").json()["name_en"] == "Patched"

            # DELETE → 204, 이후 GET → 404
            assert client.delete(f"/v1/concepts/{concept_id}").status_code == 204
            deleted = True
            assert client.get(f"/v1/concepts/{concept_id}").status_code == 404
    finally:
        if concept_id is not None and not deleted:
            asyncio.run(_delete_concept(uuid.UUID(concept_id)))


def test_concept_optimistic_lock_on_live_pg(admin_auth: dict[str, str]) -> None:
    """GET ETag로 PATCH→200·ETag 갱신→옛 ETag 재PATCH→412(동시수정 차단)."""
    code = f"TEST-LOCK-{uuid.uuid4().hex[:8]}"
    concept_id: str | None = None
    try:
        with _app_with_jwt_settings() as client:
            client.headers.update(admin_auth)
            concept_id = asyncio.run(_seed_concept(code, "원본", "단원"))
            etag1 = client.get(f"/v1/concepts/{concept_id}").headers["ETag"]

            # 일치 If-Match → 200, ETag가 새 값으로 바뀜
            patched = client.patch(
                f"/v1/concepts/{concept_id}",
                json={"name_en": "First"},
                headers={"If-Match": etag1},
            )
            assert patched.status_code == 200
            etag2 = patched.headers["ETag"]
            assert etag2 != etag1

            # 옛 ETag(etag1)로 다시 PATCH → 412(그사이 변경됨)
            stale = client.patch(
                f"/v1/concepts/{concept_id}",
                json={"name_en": "Second"},
                headers={"If-Match": etag1},
            )
            assert stale.status_code == 412
            # 412 후 내용 미변경 확인
            assert client.get(f"/v1/concepts/{concept_id}").json()["name_en"] == "First"
    finally:
        if concept_id is not None:
            asyncio.run(_delete_concept(uuid.UUID(concept_id)))


def test_concept_conditional_get_304_on_live_pg(admin_auth: dict[str, str]) -> None:
    """GET ETag→If-None-Match로 GET→304→PATCH 변경 후 옛 ETag→200(내용 바뀜)."""
    code = f"TEST-INM-{uuid.uuid4().hex[:8]}"
    concept_id: str | None = None
    try:
        with _app_with_jwt_settings() as client:
            client.headers.update(admin_auth)
            concept_id = asyncio.run(_seed_concept(code, "원본", "단원"))
            etag = client.get(f"/v1/concepts/{concept_id}").headers["ETag"]

            # 변하지 않았으면 304(빈 본문)
            not_mod = client.get(f"/v1/concepts/{concept_id}", headers={"If-None-Match": etag})
            assert not_mod.status_code == 304
            assert not_mod.content == b""

            # PATCH로 내용 변경 → 옛 ETag로 조건부 GET은 이제 200(본문)
            client.patch(f"/v1/concepts/{concept_id}", json={"name_en": "Changed"})
            refetched = client.get(f"/v1/concepts/{concept_id}", headers={"If-None-Match": etag})
            assert refetched.status_code == 200
            assert refetched.json()["name_en"] == "Changed"
    finally:
        if concept_id is not None:
            asyncio.run(_delete_concept(uuid.UUID(concept_id)))


def test_concept_post_without_auth_returns_401_on_live_pg() -> None:
    """SEC-07 D1 — 실 PG 경로에서도 무인증 POST는 401(get_current_user가 DB 도달 전 차단)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    with TestClient(create_app()) as client:
        body = {
            "code": f"TEST-NOAUTH-{uuid.uuid4().hex[:8]}",
            "name_ko": "무인증",
            "level": "단원",
        }
        resp = client.post("/v1/concepts", json=body)
        assert resp.status_code == 401


def test_concept_get_without_auth_still_public_on_live_pg(admin_auth: dict[str, str]) -> None:
    """SEC-07 D1 — GET은 실 PG 경로에서도 무인증 유지(봉인 범위 과확대 방지 회귀)."""
    code = f"TEST-PUBLICGET-{uuid.uuid4().hex[:8]}"
    concept_id: str | None = None
    try:
        with _app_with_jwt_settings() as client:
            client.headers.update(admin_auth)
            concept_id = asyncio.run(_seed_concept(code, "원본", "단원"))

        # 별도 무인증 client로 GET — 헤더 없이 200이어야 한다. 첫 client의 `with` 블록을
        # 벗어난 뒤 새 TestClient를 연다 — 중첩하면 각자의 anyio 이벤트루프 포탈이 asyncpg
        # 커넥션을 서로 다른 loop에 바인딩해 "attached to a different loop" RuntimeError를 낸다
        # (실측 — 이 파일의 다른 모든 통합테스트는 client 1개만 연다).
        with TestClient(create_app()) as anon_client:
            resp = anon_client.get(f"/v1/concepts/{concept_id}")
            assert resp.status_code == 200
            assert resp.json()["code"] == code
    finally:
        if concept_id is not None:
            asyncio.run(_delete_concept(uuid.UUID(concept_id)))


def test_delete_of_a_loader_owned_concept_is_refused_on_live_pg(admin_auth: dict[str, str]) -> None:
    """적재가 소유한 개념(표지 없음)은 지워도 다음 적재가 되살린다 — 레거시 DELETE도 409로 거부한다(P3-26)."""
    code = f"TEST-FILEOWNED-{uuid.uuid4().hex[:8]}"
    concept_id: str | None = None
    try:
        with _app_with_jwt_settings() as client:
            client.headers.update(admin_auth)
            concept_id = asyncio.run(_seed_concept(code, "적재 소유", "단원"))
            refused = client.delete(f"/v1/concepts/{concept_id}")
            assert refused.status_code == 409, refused.text
            assert refused.json()["detail"]["code"] == "file_owned"
            assert client.get(f"/v1/concepts/{concept_id}").status_code == 200  # 그대로 살아 있다
    finally:
        if concept_id is not None:
            asyncio.run(_delete_concept(uuid.UUID(concept_id)))
