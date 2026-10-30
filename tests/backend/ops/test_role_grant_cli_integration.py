"""운영자 좌석 발급 ops CLI(`ops/role_grant_cli.py`, ADMIN-01) — 실 PostgreSQL 통합테스트.

`WHYMATH_RUN_INTEGRATION=1` + 살아있는 PG(마이그레이션 head 적용)에서만 실행한다(conftest
게이트가 CI 기본 skip). PG 미도달 시에도 graceful skip(`test_concepts_integration.py` 패턴 미러).

검증하는 것(ADMIN-01 완료조건 ③·⑤):
  ① **3상태 왕복**(⑤ — 변별력) — 콘텐츠 CUD 라우터(`DELETE /v1/concepts/{id}`)가 실 STUDENT
     사용자에게 부여 전 403 → `grant` CLI 실행 후 404(권한은 통과, 없는 개념) → `revoke` CLI 실행
     후 다시 403을 실제로 낸다(같은 값 반복이면 위장 — 세 상태가 실제로 *다름*을 단언한다).
     P3-26 이전에는 `POST /v1/concepts`의 201을 "통과" 신호로 썼으나, 그 경로는 폐지(410)됐다 —
     404는 인가 체인을 통과해 핸들러까지 갔다는 신호로 같은 변별력을 가진다(403과 다르다).
  ② **트랜잭션 원자성**(③) — 역할 변경 + `privacy_audit.role_change` 감사 적재를 같은 세션에서
     `flush`(DB에 SQL 발사)까지 밀어넣은 뒤 커밋 전에 인위로 예외를 일으켜 롤백하면, 역할도
     감사 행도 *둘 다* 사라짐을 새 세션 재조회로 확인한다(부분 성공 0 증명).

CLI(`role_grant_cli.main`)는 모듈 전역 캐시 엔진(`db.session.get_engine`)을 쓴다 — 같은 프로세스
안에서 TestClient(자체 이벤트루프 portal)와 `asyncio.run()`(CLI 호출마다 새 루프)이 그 전역
엔진을 서로 다른 루프에서 재사용하면 asyncpg가 "다른 루프에 바인딩된 연결" 오류를 낸다
(`db/session.py` docstring). `WHYMATH_DB_DISABLE_POOL=1`(NullPool — 매 체크아웃 새 연결)로
회피한다(CI `backend — 마이그레이션·통합(실 PG)` 잡의 표준 처방과 동일).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import dispose_engine
from whymath_backend.ops import role_grant_cli as cli
from whymath_backend.privacy.audit import record_role_change_audit
from whymath_backend.schema.enums import AuditEventKind, Persona, Role
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

pytestmark = pytest.mark.integration

_JWT_SECRET = "role-grant-cli-integration-jwt-secret-0123456789ab"


def _jwt_settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_JWT_SECRET))


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


async def _insert_student(user_id: uuid.UUID) -> None:
    """기본 역할(`Role.STUDENT`) UserProfile 행을 실 PG에 적재(부여 전 403 재현용)."""
    engine = create_async_engine(Settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                UserProfile.from_schema(
                    UserProfileSchema(user_id=user_id, persona_primary=Persona.A_일반고고3)
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _delete_user_and_audit(user_id: uuid.UUID) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM privacy_audit WHERE user_id = :uid"), {"uid": str(user_id)}
            )
            await conn.execute(
                text("DELETE FROM user_profile WHERE user_id = :uid"), {"uid": str(user_id)}
            )
    finally:
        await engine.dispose()


async def _delete_concepts(concept_ids: list[uuid.UUID]) -> None:
    if not concept_ids:
        return
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM concept WHERE concept_id = ANY(:ids)"),
                {"ids": [str(c) for c in concept_ids]},
            )
    finally:
        await engine.dispose()


@pytest.fixture
def student_user() -> Iterator[uuid.UUID]:
    """기본 역할 사용자 1명을 실 PG에 만들고 user_id를 yield(테스트 후 정리)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    uid = uuid.uuid4()
    asyncio.run(_insert_student(uid))
    try:
        yield uid
    finally:
        asyncio.run(_delete_user_and_audit(uid))


@pytest.fixture(autouse=True)
def _disable_pool_for_cross_loop_cli_calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`role_grant_cli`(자체 `asyncio.run`)와 TestClient(자체 이벤트루프)가 같은 프로세스에서
    전역 엔진(`db.session.get_engine`)을 공유할 때의 asyncpg 루프 바인딩 충돌을 NullPool로 회피.
    """
    monkeypatch.setenv("WHYMATH_DB_DISABLE_POOL", "1")
    get_settings.cache_clear()
    asyncio.run(dispose_engine())
    yield
    asyncio.run(dispose_engine())
    get_settings.cache_clear()


def _app_with_jwt_settings() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = _jwt_settings
    return TestClient(app)


class TestThreeStateRoundTrip:
    """⑤ 변별력 — 403(부여 전) → 404(grant 후·권한 통과) → 403(revoke 후) 3상태가 실제로 다름."""

    def test_403_then_201_then_403(self, student_user: uuid.UUID) -> None:
        token = create_access_token(student_user, settings=_jwt_settings())
        headers = {"Authorization": f"Bearer {token}"}
        created_concept_ids: list[uuid.UUID] = []

        try:
            with _app_with_jwt_settings() as client:
                client.headers.update(headers)

                # ── ① 부여 전: CONTENT_ADMIN 0명 상태 재현 — CUD 라우터 403 ──
                missing = uuid.uuid4()  # 존재하지 않는 개념 — 권한이 있으면 404, 없으면 403
                resp_before = client.delete(f"/v1/concepts/{missing}")
                assert resp_before.status_code == 403

                # ── grant CLI 실행(실 프로세스 경로 — cli.main, 기본 DB-backed 함수) ──
                grant_code = cli.main(["grant", str(student_user), "content_admin"])
                assert grant_code == 0

                # ── ② 부여 후: 같은 라우터가 인가를 통과해 404(없는 개념) ──
                resp_after_grant = client.delete(f"/v1/concepts/{missing}")
                assert resp_after_grant.status_code == 404

                # ── revoke CLI 실행 ──
                revoke_code = cli.main(["revoke", str(student_user), "content_admin"])
                assert revoke_code == 0

                # ── ③ 회수 후: 다시 403(같은 값 반복이 아님 — 세 상태 전부 실제로 다름) ──
                resp_after_revoke = client.delete(f"/v1/concepts/{missing}")
                assert resp_after_revoke.status_code == 403

            statuses = [
                resp_before.status_code,
                resp_after_grant.status_code,
                resp_after_revoke.status_code,
            ]
            assert statuses == [403, 404, 403]
        finally:
            asyncio.run(_delete_concepts(created_concept_ids))

    def test_list_reflects_grant_and_revoke(self, student_user: uuid.UUID) -> None:
        """`list` — 부여 중엔 대상이 나타나고, 회수 후엔 사라진다(동일 CLI 표면 회귀)."""
        assert cli.main(["grant", str(student_user), "content_admin"]) == 0

        async def _list() -> list[dict[str, str]]:
            return await cli._default_list_fn()

        during = asyncio.run(_list())
        assert any(row["user_id"] == str(student_user) for row in during)

        assert cli.main(["revoke", str(student_user), "content_admin"]) == 0

        after = asyncio.run(_list())
        assert not any(row["user_id"] == str(student_user) for row in after)


class TestTransactionAtomicity:
    """③ — 역할 변경 + role_change 감사가 같은 트랜잭션. 커밋 전 강제 실패 → 둘 다 롤백."""

    def test_forced_failure_before_commit_rolls_back_both(self, student_user: uuid.UUID) -> None:
        async def _run() -> None:
            engine = create_async_engine(Settings().database_url)
            try:
                sm = async_sessionmaker(engine, expire_on_commit=False)
                settings = Settings()

                async def _apply_and_audit_then_boom(session: AsyncSession) -> None:
                    old_role = await cli.apply_role_change(
                        session, user_id=student_user, new_role=Role.CONTENT_ADMIN
                    )
                    assert old_role is Role.STUDENT
                    record_role_change_audit(
                        session, user_id=student_user, ip=None, settings=settings
                    )
                    # 역할 UPDATE + 감사 INSERT를 *같은(아직 열린) 트랜잭션* 안에서 DB로
                    # 실제 발사한다(flush) — 커밋 전 강제 실패가 "이미 전송된" 두 변경 모두를
                    # 되돌리는지 보려는 것이므로, flush 없이 add만 한 상태에서 롤백하면 애초에
                    # 아무것도 전송되지 않아 증명력이 약하다.
                    await session.flush()
                    raise RuntimeError("강제 실패(테스트 — 커밋 전 인위 예외)")

                async with sm() as session:
                    with pytest.raises(RuntimeError, match="강제 실패"):
                        await _apply_and_audit_then_boom(session)
                    await session.rollback()

                # 새 세션(=새 트랜잭션)으로 재조회 — 부분 성공(역할만 또는 감사만 남음) 0 확인.
                async with sm() as session:
                    reloaded = await session.get(UserProfile, student_user)
                    assert reloaded is not None
                    assert reloaded.role is Role.STUDENT  # 강제 롤백 — 여전히 기본 역할

                    audit_rows = (
                        (
                            await session.execute(
                                select(PrivacyAudit).where(
                                    PrivacyAudit.user_id == student_user,
                                    PrivacyAudit.event_kind == AuditEventKind.role_change.value,
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    assert audit_rows == []  # 강제 롤백 — 감사 행도 잔존하지 않음
            finally:
                await engine.dispose()

        asyncio.run(_run())

    def test_successful_grant_persists_both_role_and_audit(self, student_user: uuid.UUID) -> None:
        """대조군 — 정상 커밋(강제 실패 없음)이면 역할·감사 *둘 다* 남는다(위 롤백과 대비)."""
        assert cli.main(["grant", str(student_user), "content_admin"]) == 0

        async def _check() -> None:
            engine = create_async_engine(Settings().database_url)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    reloaded = await session.get(UserProfile, student_user)
                    assert reloaded is not None
                    assert reloaded.role is Role.CONTENT_ADMIN

                    audit_rows = (
                        (
                            await session.execute(
                                select(PrivacyAudit).where(
                                    PrivacyAudit.user_id == student_user,
                                    PrivacyAudit.event_kind == AuditEventKind.role_change.value,
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    assert len(audit_rows) == 1
            finally:
                await engine.dispose()

        asyncio.run(_check())
