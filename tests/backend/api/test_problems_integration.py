"""problem API 통합테스트 — 실 PostgreSQL 왕복 (기본 SKIP).

test_concepts_integration.py와 동일 게이트(`@integration`·`WHYMATH_RUN_INTEGRATION=1`·PG
도달성 skip). POST→GET→목록(subject 필터)이 실 PG에서 HTTP→get_session→PG로 왕복하는지 검증.
설정/정리는 독립 엔진으로(전역 캐시 엔진 루프 충돌 회피).

인가(SEC-07 D1): CUD(POST/PATCH/DELETE)는 이제 `Role.CONTENT_ADMIN` 인증이 필요하다.
`test_concepts_integration.py`와 동일 패턴(`admin_auth` 픽스처 — 실 PG에 CONTENT_ADMIN
UserProfile 행 적재 + `get_settings` 고정 시크릿 오버라이드로 토큰 mint/decode 일치).
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
from whymath_backend.db.models.user import UserProfile
from whymath_backend.schema.enums import Persona, Role
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

pytestmark = pytest.mark.integration

_JWT_SECRET = "problems-integration-jwt-secret-0123456789ab"


def _jwt_settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_JWT_SECRET))


def _body(subject: str = "미적분") -> dict[str, object]:
    return {
        "source_type": "자체생성",
        "curriculum_version": "2015_REVISION",
        "valid_from_year": 2014,
        "subject": subject,
        "unit_codes": ["CAL-INT-DEF"],
        # LIC-09 — 자체생성 POST는 provenance 좌석 동반 필수(원장 행이 같은 트랜잭션에 남는다).
        "provenance": {"generation_type": "FULLY_GENERATED", "license": "WHYMATH_GENERATED"},
    }


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
    """CONTENT_ADMIN 사용자를 실 PG에 만들고 `Authorization` 헤더를 yield(테스트 후 정리)."""
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


async def _delete_problem(problem_id: uuid.UUID) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            # LIC-09 — 생성물 POST는 출처 원장 행을 남긴다(FK problem_id → problem). 원장을
            # 먼저 지우지 않으면 문항 정리가 FK 위반으로 실패한다(테스트 정리 전용 경로).
            await conn.execute(
                text("DELETE FROM content_provenance WHERE problem_id = :pid"),
                {"pid": str(problem_id)},
            )
            await conn.execute(
                text("DELETE FROM problem WHERE problem_id = :pid"),
                {"pid": str(problem_id)},
            )
    finally:
        await engine.dispose()


async def _insert_step(problem_id: uuid.UUID, order: int, title: str) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO problem_step (problem_id, step_order, step_title) "
                    "VALUES (:pid, :ord, :title)"
                ),
                {"pid": str(problem_id), "ord": order, "title": title},
            )
    finally:
        await engine.dispose()


async def _delete_steps(problem_id: uuid.UUID) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM problem_step WHERE problem_id = :pid"),
                {"pid": str(problem_id)},
            )
    finally:
        await engine.dispose()


def test_problem_crud_roundtrip_on_live_pg(admin_auth: dict[str, str]) -> None:
    """POST→GET→subject 목록이 실 PG에서 왕복한다."""
    problem_id: str | None = None
    try:
        with _app_with_jwt_settings() as client:
            client.headers.update(admin_auth)
            created = client.post("/v1/problems", json=_body())
            assert created.status_code == 201, created.text
            payload = created.json()
            assert payload["subject"] == "미적분"
            problem_id = payload["problem_id"]

            got = client.get(f"/v1/problems/{problem_id}")
            assert got.status_code == 200
            assert got.json()["source_type"] == "자체생성"

            listed = client.get("/v1/problems?subject=미적분&limit=200")
            assert listed.status_code == 200
            assert problem_id in {item["problem_id"] for item in listed.json()}

            # 다른 과목 필터엔 안 잡혀야(필터 SQL 동작 확인)
            other = client.get("/v1/problems?subject=기하&limit=200")
            assert other.status_code == 200
            assert problem_id not in {item["problem_id"] for item in other.json()}
    finally:
        if problem_id is not None:
            asyncio.run(_delete_problem(uuid.UUID(problem_id)))


def test_problem_steps_nested_read_on_live_pg(admin_auth: dict[str, str]) -> None:
    """GET /problems/{id}/steps가 step_order 순으로 실 PG에서 반환·404·빈 relations."""
    problem_id: str | None = None
    try:
        with _app_with_jwt_settings() as client:
            client.headers.update(admin_auth)
            problem_id = client.post("/v1/problems", json=_body()).json()["problem_id"]
            # 단계 2건을 역순(2→1)으로 삽입 → 엔드포인트가 step_order로 정렬하는지 확인
            asyncio.run(_insert_step(uuid.UUID(problem_id), 2, "둘째 단계"))
            asyncio.run(_insert_step(uuid.UUID(problem_id), 1, "첫째 단계"))

            steps = client.get(f"/v1/problems/{problem_id}/steps")
            assert steps.status_code == 200
            assert [s["step_order"] for s in steps.json()] == [1, 2]

            # relations는 0건 → 200 + []
            rels = client.get(f"/v1/problems/{problem_id}/relations")
            assert rels.status_code == 200
            assert rels.json() == []

            # 없는 문제의 하위 리소스 → 404
            assert client.get(f"/v1/problems/{uuid.uuid4()}/steps").status_code == 404
    finally:
        if problem_id is not None:
            asyncio.run(_delete_steps(uuid.UUID(problem_id)))
            asyncio.run(_delete_problem(uuid.UUID(problem_id)))


def test_problem_patch_delete_roundtrip_on_live_pg(admin_auth: dict[str, str]) -> None:
    """POST→PATCH→GET→DELETE(409 — 출처 원장 보존)가 실 PG에서 왕복.

    LIC-09: 생성물 POST는 `content_provenance` 행을 같은 트랜잭션에 남기고, DELETE는 cascade가
    없어(가짜 cascade 금지) 원장이 참조하는 문항 삭제를 409로 거부한다 — 감사 원장을 REST가
    조용히 지우지 않는다. 비노출이 목적이면 격리(EOS-71)가 비파괴 회수 경로다.
    """
    problem_id: str | None = None
    deleted = False
    try:
        with _app_with_jwt_settings() as client:
            client.headers.update(admin_auth)
            problem_id = client.post("/v1/problems", json=_body()).json()["problem_id"]

            patched = client.patch(f"/v1/problems/{problem_id}", json={"answer": "42"})
            assert patched.status_code == 200, patched.text
            assert patched.json()["answer"] == "42"  # 관리자 표면(PATCH 응답)은 전체 스키마 유지
            assert patched.json()["subject"] == "미적분"  # 기존 필드 보존

            # SEC-24(원 SEC-15): 공개 GET은 공개 투영 — 정답류는 값이 아니라 *키 자체가 없다*.
            # (이전 계약은 GET에서 answer=="42"를 단언했으나, 무인증 정답 노출이 감사 M1
            #  결함으로 판정돼 키 부재로 뒤집었다 — test_problems_public_projection.py 정본.)
            got = client.get(f"/v1/problems/{problem_id}").json()
            assert "answer" not in got
            assert got["subject"] == "미적분"  # 본문·메타 카탈로그(D1)는 계속 공개

            rejected = client.delete(f"/v1/problems/{problem_id}")
            assert rejected.status_code == 409, rejected.text
            assert client.get(f"/v1/problems/{problem_id}").status_code == 200  # 롤백 — 보존
    finally:
        if problem_id is not None and not deleted:
            asyncio.run(_delete_problem(uuid.UUID(problem_id)))


def test_problem_post_without_auth_returns_401_on_live_pg() -> None:
    """SEC-07 D1 — 실 PG 경로에서도 무인증 POST는 401."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    with TestClient(create_app()) as client:
        resp = client.post("/v1/problems", json=_body())
        assert resp.status_code == 401


def test_problem_get_without_auth_still_public_on_live_pg(admin_auth: dict[str, str]) -> None:
    """SEC-07 D1 — GET은 실 PG 경로에서도 무인증 유지(봉인 범위 과확대 방지 회귀)."""
    problem_id: str | None = None
    try:
        with _app_with_jwt_settings() as client:
            client.headers.update(admin_auth)
            problem_id = client.post("/v1/problems", json=_body()).json()["problem_id"]

        # 별도 무인증 client로 GET — 헤더 없이 200이어야 한다. 첫 client의 `with` 블록을
        # 벗어난 뒤 새 TestClient를 연다 — 중첩하면 각자의 anyio 이벤트루프 포탈이 asyncpg
        # 커넥션을 서로 다른 loop에 바인딩해 "attached to a different loop" RuntimeError를 낸다
        # (실측 — 이 파일의 다른 모든 통합테스트는 client 1개만 연다).
        with TestClient(create_app()) as anon_client:
            resp = anon_client.get(f"/v1/problems/{problem_id}")
            assert resp.status_code == 200
            assert resp.json()["problem_id"] == problem_id
    finally:
        if problem_id is not None:
            asyncio.run(_delete_problem(uuid.UUID(problem_id)))
