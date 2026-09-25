"""운영자 토큰 발급 ops CLI(`ops/operator_token_cli.py`, ADMIN-15) — 실 PostgreSQL 통합테스트.

`WHYMATH_RUN_INTEGRATION=1` + 살아있는 PG(마이그레이션 head 적용)에서만 실행한다(conftest 게이트가
CI 기본 skip — CI에서는 `backend-migrations` 잡이 이 파일을 마커로 수집한다). PG 미도달 시 graceful
skip(`test_role_grant_cli_integration.py` 패턴 미러).

검증하는 것(ADMIN-15 acceptance ②):
  ① **발급 토큰으로 콘솔 입구가 열린다** — CLI(기본 좌석 = 실 프리플라이트·실 DB 커밋)가 낸 토큰으로
     `GET /v1/admin/menu`가 200 + 비어 있지 않은 sections. 대조군: 같은 요청을 토큰 없이 보내면
     401 — "메뉴가 원래 열려 있었다"는 위장을 배제한다.
  ② **감사 1행** — 발급 1건마다 `privacy_audit.operator_token_issued` 정확히 1행, 만료·발급자·
     시각이 토큰 클레임과 일치하고 토큰 값은 어느 컬럼에도 없다.
  ③ **거부 3종은 발급 0·감사 0** — 존재하지 않는 user_id·데모 계정·학생 역할 전부 exit 1 +
     stdout 비어 있음 + 해당 user_id의 감사 행 0.

CLI는 모듈 전역 엔진을 자체 `asyncio.run()`에서 쓰므로 TestClient와 같은 프로세스에서 루프 바인딩
충돌을 피하려 `WHYMATH_DB_DISABLE_POOL=1`(NullPool)을 건다(role_grant_cli 통합 테스트와 동일 처방).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.api.auth import email_hash
from whymath_backend.api.demo_auth import DEMO_EMAIL
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import dispose_engine
from whymath_backend.ops import operator_token_cli as cli
from whymath_backend.schema.enums import AuditEventKind, Persona, Role

pytestmark = pytest.mark.integration

_JWT_SECRET = "operator-token-cli-integration-jwt-secret-0123456789"
_MENU_PATH = "/v1/admin/menu"


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


async def _insert_user(user_id: uuid.UUID, *, role: Role, email: str) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                UserProfile(
                    user_id=user_id,
                    role=role,
                    email_hash=email_hash(email),
                    persona_primary=Persona.A_일반고고3,
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


async def _token_audit_rows(user_id: uuid.UUID) -> list[PrivacyAudit]:
    engine = create_async_engine(Settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            rows = (
                await session.scalars(
                    select(PrivacyAudit).where(
                        PrivacyAudit.user_id == user_id,
                        PrivacyAudit.event_kind == AuditEventKind.operator_token_issued.value,
                    )
                )
            ).all()
            return list(rows)
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def _cli_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """CLI와 서버(TestClient)가 **같은 JWT 시크릿**을 쓰게 하고, 루프 간 풀 공유를 끈다."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    monkeypatch.setenv("WHYMATH_DB_DISABLE_POOL", "1")
    monkeypatch.setenv("WHYMATH_JWT_SECRET_KEY", _JWT_SECRET)
    get_settings.cache_clear()
    asyncio.run(dispose_engine())
    yield
    asyncio.run(dispose_engine())
    get_settings.cache_clear()


@pytest.fixture
def make_user() -> Iterator[list[uuid.UUID]]:
    """테스트가 만든 사용자 id를 모아 두었다가 행·감사 행을 함께 정리한다."""
    created: list[uuid.UUID] = []
    yield created
    for uid in created:
        asyncio.run(_delete_user_and_audit(uid))


def _new_user(created: list[uuid.UUID], *, role: Role, email: str) -> uuid.UUID:
    uid = uuid.uuid4()
    asyncio.run(_insert_user(uid, role=role, email=email))
    created.append(uid)
    return uid


def _run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = cli.main(argv, issuer_fn=lambda: "integration-runner")
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestIssuedTokenOpensAdminMenu:
    def test_menu_200_with_non_empty_sections_and_one_audit_row(
        self, make_user: list[uuid.UUID], capsys: pytest.CaptureFixture[str]
    ) -> None:
        uid = _new_user(make_user, role=Role.CONTENT_ADMIN, email=f"op-{uuid.uuid4()}@x.org")

        code, out, err = _run_cli(["issue", str(uid), "--ttl-minutes", "15"], capsys)
        assert code == 0, err
        payload = json.loads(out)
        token = payload["access_token"]
        assert payload["user_id"] == str(uid)

        client = TestClient(create_app())
        # 대조군 — 토큰 없이는 401. 이게 200이면 아래 200은 토큰의 효과가 아니다.
        assert client.get(_MENU_PATH).status_code == 401
        resp = client.get(_MENU_PATH, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text
        sections = resp.json()["sections"]
        assert sections, "content_admin 토큰인데 메뉴가 비었다"
        assert all(section["items"] for section in sections)

        # 감사 — 정확히 1행, 토큰 클레임과 같은 시각·만료, 발급자, 토큰 값 미저장.
        rows = asyncio.run(_token_audit_rows(uid))
        assert len(rows) == 1
        row = rows[0]
        claims = jwt.get_unverified_claims(token)
        assert row.occurred_at == datetime.fromtimestamp(claims["iat"], tz=UTC)
        assert row.token_expires_at == datetime.fromtimestamp(claims["exp"], tz=UTC)
        assert (row.token_expires_at - row.occurred_at).total_seconds() == 15 * 60
        assert row.issued_by == "integration-runner"
        assert row.target_user_id is None
        assert payload["expires_at"] == row.token_expires_at.isoformat()
        signature = token.rsplit(".", 1)[-1]
        for col in PrivacyAudit.__table__.columns:
            assert signature not in str(getattr(row, col.key))

    def test_each_issuance_leaves_its_own_row(
        self, make_user: list[uuid.UUID], capsys: pytest.CaptureFixture[str]
    ) -> None:
        uid = _new_user(make_user, role=Role.CONTENT_ADMIN, email=f"op-{uuid.uuid4()}@x.org")
        for _ in range(2):
            code, _out, err = _run_cli(["issue", str(uid)], capsys)
            assert code == 0, err
        assert len(asyncio.run(_token_audit_rows(uid))) == 2


class TestRejectionsIssueNothing:
    def test_missing_user(
        self, make_user: list[uuid.UUID], capsys: pytest.CaptureFixture[str]
    ) -> None:
        ghost = uuid.uuid4()
        make_user.append(ghost)  # 정리 대상(감사 행이 잘못 생겼을 경우까지 치운다)
        code, out, err = _run_cli(["issue", str(ghost)], capsys)
        assert code == 1
        assert out == ""
        assert "찾을 수 없습니다" in json.loads(err)["error"]
        assert asyncio.run(_token_audit_rows(ghost)) == []

    def test_demo_account_with_admin_role(
        self, make_user: list[uuid.UUID], capsys: pytest.CaptureFixture[str]
    ) -> None:
        # 데모 계정은 email_hash가 고정이라 공유 DB에 이미 행이 있을 수 있다 — 그 행의 역할을
        # 바꾸면 다른 테스트를 오염시키므로 건드리지 않고 건너뛴다(CI의 빈 DB에서는 항상 실행된다).
        if asyncio.run(_find_demo_user()) is not None:
            pytest.skip("공유 DB에 데모 계정 행이 이미 있다 — 역할을 바꾸지 않기 위해 건너뜀")
        # 역할은 content_admin — 역할로 막히면 데모 거부를 본 것이 아니다(대조가 무효).
        uid = _new_user(make_user, role=Role.CONTENT_ADMIN, email=DEMO_EMAIL)
        code, out, err = _run_cli(["issue", str(uid)], capsys)
        assert code == 1
        assert out == ""
        assert "데모 계정" in json.loads(err)["error"]
        assert asyncio.run(_token_audit_rows(uid)) == []

    def test_student_role(
        self, make_user: list[uuid.UUID], capsys: pytest.CaptureFixture[str]
    ) -> None:
        uid = _new_user(make_user, role=Role.STUDENT, email=f"st-{uuid.uuid4()}@x.org")
        code, out, err = _run_cli(["issue", str(uid)], capsys)
        assert code == 1
        assert out == ""
        assert "content_admin 계정에만" in json.loads(err)["error"]
        assert asyncio.run(_token_audit_rows(uid)) == []


async def _find_demo_user() -> uuid.UUID | None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as conn:
            found = await conn.scalar(
                text("SELECT user_id FROM user_profile WHERE email_hash = :h"),
                {"h": email_hash(DEMO_EMAIL)},
            )
            return found if found is None else uuid.UUID(str(found))
    finally:
        await engine.dispose()
