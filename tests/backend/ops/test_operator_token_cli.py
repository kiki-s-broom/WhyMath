"""운영자 토큰 발급 ops CLI(`ops/operator_token_cli.py`, ADMIN-15) — 단위(hermetic).

DB 없이 검증하는 것:
  ① argparse 배선 — 잘못된 UUID·만료 범위 밖(0·61) → SystemExit(2)
  ② `issue_operator_token` 거부 3종(사용자 없음·데모 계정·content_admin 아님) — 전부 예외 +
     **감사 행 0**(`session.added == []`). 각 거부에는 *같은 조건에서 통과하는 대조군*이 있다
     (성공 1종) — 대조군이 없으면 "전부 거부" 오구현이 통과한다
  ③ 감사 행 조립 — event_kind·user_id·occurred_at=토큰 iat·token_expires_at=토큰 exp·
     issued_by, 그리고 **토큰 값이 행의 어떤 컬럼에도 없다**
  ④ 만료 상한 — 60분 상한·서버 기본 만료보다 긴 값 거부·JWT 미설정 거부
  ⑤ `main()` 조립 — 성공 JSON stdout(토큰 포함)·거부는 stderr+exit 1+stdout 비어 있음·
     발급자 식별자 형식 검사

실 DB 왕복(감사 행 실제 적재·발급 토큰으로 `GET /v1/admin/menu` 200)은
`test_operator_token_cli_integration.py`(`@pytest.mark.integration`)가 검증한다.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from jose import jwt
from pydantic import SecretStr

from whymath_backend.api.auth import email_hash
from whymath_backend.api.demo_auth import DEMO_EMAIL
from whymath_backend.config import Settings
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.user import UserProfile
from whymath_backend.ops import operator_token_cli as cli
from whymath_backend.schema.enums import AuditEventKind, Role
from whymath_backend.security import decode_access_token

_UID = uuid.uuid4()
_SECRET = "operator-token-cli-unit-jwt-secret-0123456789abcdef"


def _settings(*, secret: str = _SECRET, expire_minutes: int = 60 * 24) -> Settings:
    return Settings(jwt_secret_key=SecretStr(secret), jwt_expire_minutes=expire_minutes)


class _FakeSession:
    """`get`(사용자 조회)·`add`(감사 적재)만 추적 — commit 없음(호출자 책임 계약)."""

    def __init__(self, users: dict[uuid.UUID, UserProfile] | None = None) -> None:
        self._users = dict(users or {})
        self.added: list[Any] = []

    async def get(self, model: Any, pk: uuid.UUID) -> UserProfile | None:
        assert model is UserProfile
        return self._users.get(pk)

    def add(self, obj: Any) -> None:
        self.added.append(obj)


def _admin() -> UserProfile:
    return UserProfile(user_id=_UID, role=Role.CONTENT_ADMIN, email_hash=email_hash("op@x.org"))


async def _issue(session: _FakeSession, **overrides: Any) -> cli.IssuedToken:
    kwargs: dict[str, Any] = {
        "user_id": _UID,
        "ttl_minutes": 30,
        "issued_by": "kiki",
        "settings": _settings(),
    }
    kwargs.update(overrides)
    return await cli.issue_operator_token(session, **kwargs)  # type: ignore[arg-type]


async def _preflight_ok() -> None:
    """프리플라이트 통과 좌석 — hermetic 테스트는 DB를 왕복하지 않는다."""


# ===========================================================================
# ① argparse 배선
# ===========================================================================


class TestArgparseWiring:
    def test_invalid_uuid_exits_2(self) -> None:
        with pytest.raises(SystemExit) as exc:
            cli.main(["issue", "not-a-uuid"])
        assert exc.value.code == 2

    @pytest.mark.parametrize("ttl", ["0", "61", "1440", "abc"])
    def test_ttl_out_of_range_exits_2(self, ttl: str) -> None:
        with pytest.raises(SystemExit) as exc:
            cli.main(["issue", str(_UID), "--ttl-minutes", ttl])
        assert exc.value.code == 2

    def test_no_subcommand_exits_2(self) -> None:
        with pytest.raises(SystemExit) as exc:
            cli.main([])
        assert exc.value.code == 2

    def test_default_ttl_is_below_cap(self) -> None:
        # 상수 자체의 관계 — 기본값이 상한을 넘으면 기본 실행이 argparse에서 막힌다.
        assert 1 <= cli.DEFAULT_TTL_MINUTES <= cli.MAX_TTL_MINUTES == 60


# ===========================================================================
# ② 거부 3종 — 전부 감사 0·토큰 0 (각각 대조군 있음)
# ===========================================================================


class TestRejections:
    @pytest.mark.asyncio
    async def test_missing_user_rejected_without_audit(self) -> None:
        session = _FakeSession()
        with pytest.raises(cli.OperatorTokenError, match="찾을 수 없습니다"):
            await _issue(session)
        assert session.added == []

    @pytest.mark.asyncio
    async def test_demo_account_rejected_even_with_admin_role(self) -> None:
        # 역할은 content_admin — 역할로 막히면 데모 거부를 본 것이 아니다(대조가 무효).
        demo = UserProfile(user_id=_UID, role=Role.CONTENT_ADMIN, email_hash=email_hash(DEMO_EMAIL))
        session = _FakeSession({_UID: demo})
        with pytest.raises(cli.OperatorTokenError, match="데모 계정"):
            await _issue(session)
        assert session.added == []

    @pytest.mark.asyncio
    async def test_student_role_rejected(self) -> None:
        student = UserProfile(user_id=_UID, role=Role.STUDENT, email_hash=email_hash("s@x.org"))
        session = _FakeSession({_UID: student})
        with pytest.raises(cli.OperatorTokenError, match="content_admin 계정에만"):
            await _issue(session)
        assert session.added == []

    @pytest.mark.asyncio
    async def test_every_role_but_content_admin_is_rejected(self) -> None:
        # Role이 늘어도 허용 집합은 content_admin 하나로 유지된다 — 전수 스캔.
        for role in Role:
            session = _FakeSession(
                {_UID: UserProfile(user_id=_UID, role=role, email_hash=email_hash("r@x.org"))}
            )
            if role is Role.CONTENT_ADMIN:
                await _issue(session)
                assert len(session.added) == 1
            else:
                with pytest.raises(cli.OperatorTokenError):
                    await _issue(session)
                assert session.added == []


# ===========================================================================
# ③ 성공 1종 + 감사 행 조립
# ===========================================================================


class TestSuccessAndAuditRow:
    @pytest.mark.asyncio
    async def test_issues_valid_token_for_the_target(self) -> None:
        session = _FakeSession({_UID: _admin()})
        issued = await _issue(session)
        # 서버와 같은 시크릿이면 서버 디코더가 그대로 받아들인다(typ=access·sub=대상).
        assert decode_access_token(issued.access_token, settings=_settings()) == str(_UID)
        assert issued.user_id == _UID

    @pytest.mark.asyncio
    async def test_exactly_one_audit_row_matching_token_claims(self) -> None:
        session = _FakeSession({_UID: _admin()})
        issued = await _issue(session, ttl_minutes=15, issued_by="kiki")
        assert len(session.added) == 1
        row = session.added[0]
        assert isinstance(row, PrivacyAudit)
        claims = jwt.get_unverified_claims(issued.access_token)
        # 누구에게 · 언제 · 만료 · 누가
        assert row.user_id == _UID
        assert row.event_kind == AuditEventKind.operator_token_issued.value
        assert row.occurred_at == datetime.fromtimestamp(claims["iat"], tz=UTC)
        assert row.token_expires_at == datetime.fromtimestamp(claims["exp"], tz=UTC)
        assert row.issued_by == "kiki"
        assert row.token_expires_at - row.occurred_at == timedelta(minutes=15)
        # 셸 실행 — 행위자·IP 없음, 다른 이벤트 전용 컬럼은 비어 있다.
        assert row.target_user_id is None
        assert row.ip_hash is None
        assert row.consent_scope is None
        assert row.resource_type is None and row.action is None

    @pytest.mark.asyncio
    async def test_token_value_is_not_stored_in_audit_row(self) -> None:
        session = _FakeSession({_UID: _admin()})
        issued = await _issue(session)
        row = session.added[0]
        values = [str(getattr(row, col.key)) for col in PrivacyAudit.__table__.columns]
        assert values, "감사 행 컬럼 수집이 비었다 — 아래 검사가 공허하게 통과한다"
        token = issued.access_token
        signature = token.rsplit(".", 1)[-1]
        assert all(token not in v and signature not in v for v in values)


# ===========================================================================
# ④ 만료 상한·JWT 설정
# ===========================================================================


class TestTtlAndJwtGuards:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("ttl", [0, 61, 24 * 60])
    async def test_ttl_outside_cap_rejected_without_audit(self, ttl: int) -> None:
        session = _FakeSession({_UID: _admin()})
        with pytest.raises(cli.OperatorTokenError, match="1~60분"):
            await _issue(session, ttl_minutes=ttl)
        assert session.added == []

    @pytest.mark.asyncio
    async def test_ttl_at_cap_is_allowed(self) -> None:
        session = _FakeSession({_UID: _admin()})
        issued = await _issue(session, ttl_minutes=cli.MAX_TTL_MINUTES)
        assert issued.expires_at - issued.issued_at == timedelta(minutes=cli.MAX_TTL_MINUTES)

    @pytest.mark.asyncio
    async def test_ttl_longer_than_server_default_rejected(self) -> None:
        session = _FakeSession({_UID: _admin()})
        with pytest.raises(cli.OperatorTokenError, match="서버 기본"):
            await _issue(session, ttl_minutes=30, settings=_settings(expire_minutes=20))
        assert session.added == []

    @pytest.mark.asyncio
    async def test_unconfigured_jwt_secret_rejected_without_audit(self) -> None:
        session = _FakeSession({_UID: _admin()})
        with pytest.raises(cli.OperatorTokenError, match="WHYMATH_JWT_SECRET_KEY"):
            await _issue(session, settings=_settings(secret=""))
        assert session.added == []


class TestIssuerValidation:
    @pytest.mark.parametrize("value", ["kiki", "DESKTOP-1\\kiki", "ops.bot@host", "키키"])
    def test_identifier_accepted(self, value: str) -> None:
        assert cli.validate_issuer(value) == value

    @pytest.mark.parametrize("value", ["", "two words", "a\nb", "x" * 65, "rm -rf;"])
    def test_prose_or_oversize_rejected(self, value: str) -> None:
        with pytest.raises(cli.OperatorTokenError):
            cli.validate_issuer(value)


# ===========================================================================
# ⑤ main() 조립
# ===========================================================================


def _issued_stub() -> cli.IssuedToken:
    now = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
    return cli.IssuedToken(
        user_id=_UID,
        access_token="header.payload.sig",
        issued_at=now,
        expires_at=now + timedelta(minutes=30),
    )


class TestMain:
    def test_success_prints_token_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        seen: dict[str, Any] = {}

        async def _fn(user_id: uuid.UUID, ttl: int, issuer: str) -> cli.IssuedToken:
            seen.update(user_id=user_id, ttl=ttl, issuer=issuer)
            return _issued_stub()

        code = cli.main(
            ["issue", str(_UID)],
            issue_fn=_fn,
            preflight_fn=_preflight_ok,
            issuer_fn=lambda: "kiki",
        )
        assert code == 0
        captured = capsys.readouterr()
        out = json.loads(captured.out)
        assert out["access_token"] == "header.payload.sig"
        assert out["user_id"] == str(_UID)
        assert out["token_type"] == "bearer"
        assert out["expires_at"] == "2026-09-25T12:30:00+00:00"
        assert out["issued_by"] == "kiki"
        assert captured.err == ""  # 토큰은 stdout 한 곳에만
        assert seen == {"user_id": _UID, "ttl": cli.DEFAULT_TTL_MINUTES, "issuer": "kiki"}

    def test_by_overrides_shell_login(self) -> None:
        seen: dict[str, str] = {}

        async def _fn(user_id: uuid.UUID, ttl: int, issuer: str) -> cli.IssuedToken:
            seen["issuer"] = issuer
            return _issued_stub()

        code = cli.main(
            ["issue", str(_UID), "--by", "ops-runbook", "--ttl-minutes", "10"],
            issue_fn=_fn,
            preflight_fn=_preflight_ok,
            issuer_fn=lambda: "kiki",
        )
        assert code == 0
        assert seen["issuer"] == "ops-runbook"

    def test_rejection_exits_1_with_reason_and_no_token(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def _fn(user_id: uuid.UUID, ttl: int, issuer: str) -> cli.IssuedToken:
            raise cli.OperatorTokenError("데모 계정에는 발급하지 않습니다")

        code = cli.main(
            ["issue", str(_UID)], issue_fn=_fn, preflight_fn=_preflight_ok, issuer_fn=lambda: "k"
        )
        assert code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "데모 계정" in json.loads(captured.err)["error"]

    def test_unexpected_error_reports_type_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        async def _fn(user_id: uuid.UUID, ttl: int, issuer: str) -> cli.IssuedToken:
            raise ConnectionError("db down")

        code = cli.main(
            ["issue", str(_UID)], issue_fn=_fn, preflight_fn=_preflight_ok, issuer_fn=lambda: "k"
        )
        assert code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "ConnectionError" in json.loads(captured.err)["error"]

    def test_preflight_failure_blocks_issue(self, capsys: pytest.CaptureFixture[str]) -> None:
        called: list[bool] = []

        async def _fn(user_id: uuid.UUID, ttl: int, issuer: str) -> cli.IssuedToken:
            called.append(True)
            return _issued_stub()

        async def _preflight_bad() -> None:
            raise cli.SchemaPreflightError("privacy_audit.token_expires_at 없음")

        code = cli.main(
            ["issue", str(_UID)], issue_fn=_fn, preflight_fn=_preflight_bad, issuer_fn=lambda: "k"
        )
        assert code == 1
        assert called == []
        assert capsys.readouterr().out == ""

    def test_unknown_shell_login_requires_by(self, capsys: pytest.CaptureFixture[str]) -> None:
        async def _fn(user_id: uuid.UUID, ttl: int, issuer: str) -> cli.IssuedToken:
            raise AssertionError("발급자 미상인데 발급 좌석까지 왔다")

        code = cli.main(
            ["issue", str(_UID)], issue_fn=_fn, preflight_fn=_preflight_ok, issuer_fn=lambda: None
        )
        assert code == 1
        assert "--by" in json.loads(capsys.readouterr().err)["error"]

    def test_prose_issuer_rejected_before_issue(self, capsys: pytest.CaptureFixture[str]) -> None:
        async def _fn(user_id: uuid.UUID, ttl: int, issuer: str) -> cli.IssuedToken:
            raise AssertionError("형식 위반 발급자인데 발급 좌석까지 왔다")

        code = cli.main(
            ["issue", str(_UID), "--by", "누가 봐도 문장"],
            issue_fn=_fn,
            preflight_fn=_preflight_ok,
        )
        assert code == 1
        assert capsys.readouterr().out == ""


class TestSchemaReadiness:
    def test_all_present_is_none(self) -> None:
        assert cli.judge_schema_readiness(()) is None

    def test_missing_columns_named_with_upgrade_hint(self) -> None:
        msg = cli.judge_schema_readiness(("privacy_audit.token_expires_at",))
        assert msg is not None
        assert "privacy_audit.token_expires_at" in msg
        assert "alembic upgrade head" in msg

    def test_required_columns_include_the_admin15_seats(self) -> None:
        # 프리플라이트가 이 CLI의 쓰기 대상 컬럼을 실제로 확인하는가(목록에서 빠지면 공허 통과).
        required = set(cli._REQUIRED_COLUMNS)
        assert ("privacy_audit", "token_expires_at") in required
        assert ("privacy_audit", "issued_by") in required
        assert ("user_profile", "role") in required
