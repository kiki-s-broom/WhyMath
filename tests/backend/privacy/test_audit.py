"""개인정보·콘텐츠 감사(SEC-09/SEC-29, `privacy/audit.py`) — 단위(hermetic·순수함수 + FakeSession).

`hash_client_ip`(salt 해싱·fail-closed/경고 분기)와 네 writer(`record_export_audit`·
`record_consent_change_audit`·`record_admin_access_audit`·`record_content_mutation_audit`)의
*조립 로직*만 검증한다(session.add로 무엇이 쌓이는지·commit은 호출자 책임이라 여기선 add까지만).
end-to-end(엔드포인트 결선·동일 TX 커밋)는 `tests/backend/api/test_me_export.py`·
`test_parental_consent.py`·`test_concepts.py`/`test_problems.py`(`TestContentMutationAudit`)·
실 PG 통합(`tests/backend/api/test_privacy_audit_integration.py`)이 검증한다(중복 0).
`record_role_change_audit`은 `tests/backend/ops/test_role_grant_cli.py`가 담당(그쪽이 유일
호출부라 조립 로직도 거기서 함께 본다).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import pytest
from pydantic import SecretStr

from whymath_backend.config import Settings
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.privacy.audit import (
    hash_client_ip,
    record_admin_access_audit,
    record_consent_change_audit,
    record_content_mutation_audit,
    record_export_audit,
)
from whymath_backend.schema.enums import ConsentScope, PrivacyAuditAction, PrivacyAuditResourceType

_UID = uuid.uuid4()
_TARGET_UID = uuid.uuid4()


class _FakeSession:
    """`session.add()`만 추적 — writer는 flush/commit을 하지 않는다(호출자 책임)."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)


def _settings(*, salt: str = "") -> Settings:
    return Settings(pii_audit_ip_salt=SecretStr(salt))


class TestHashClientIp:
    def test_none_ip_returns_none(self) -> None:
        """IP 추출 실패(None)면 salt 설정과 무관하게 None(해싱할 것이 없음)."""
        assert hash_client_ip(None, settings=_settings(salt="s")) is None

    def test_salt_configured_produces_deterministic_sha256(self) -> None:
        """salt 설정 시 sha256(salt+ip) hex(64자)·결정론(같은 입력=같은 해시)."""
        settings = _settings(salt="my-salt")
        h1 = hash_client_ip("203.0.113.7", settings=settings)
        h2 = hash_client_ip("203.0.113.7", settings=settings)
        assert h1 == h2
        assert h1 is not None
        assert len(h1) == 64
        expected = hashlib.sha256(b"my-salt" + b"203.0.113.7").hexdigest()
        assert h1 == expected

    def test_different_salt_or_ip_changes_hash(self) -> None:
        """salt 또는 ip가 다르면 해시도 다르다(레인보우테이블 저항 방향성 확인)."""
        base = hash_client_ip("203.0.113.7", settings=_settings(salt="salt-a"))
        other_salt = hash_client_ip("203.0.113.7", settings=_settings(salt="salt-b"))
        other_ip = hash_client_ip("198.51.100.1", settings=_settings(salt="salt-a"))
        assert base != other_salt
        assert base != other_ip

    def test_hash_never_contains_plaintext_ip(self) -> None:
        """평문 IP는 해시 문자열 어디에도 등장하지 않는다(hex 알파벳엔 '.'이 없다)."""
        ip = "203.0.113.7"
        h = hash_client_ip(ip, settings=_settings(salt="s"))
        assert h is not None
        assert ip not in h

    def test_salt_unconfigured_dev_warns_and_returns_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """salt 미설정 + 비프로덕션(기본 Settings) → 경고 로그 + None(주행위 안 막음)."""
        with caplog.at_level("WARNING", logger="whymath.privacy.audit"):
            result = hash_client_ip("203.0.113.7", settings=_settings(salt=""))
        assert result is None
        assert any("PII_AUDIT_IP_SALT" in r.getMessage() for r in caplog.records)

    def test_salt_unconfigured_production_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """salt 미설정 + 프로덕션 추정(실 OAuth provider 구성) → RuntimeError(fail-closed)."""
        settings = Settings(
            pii_audit_ip_salt=SecretStr(""),
            kakao_client_id="real-kakao-client-id",
        )
        with pytest.raises(RuntimeError, match="PII_AUDIT_IP_SALT"):
            hash_client_ip("203.0.113.7", settings=settings)


class TestRecordExportAudit:
    def test_adds_export_data_row_with_hashed_ip(self) -> None:
        session = _FakeSession()
        row = record_export_audit(
            session, user_id=_UID, ip="203.0.113.7", settings=_settings(salt="s")
        )
        assert session.added == [row]
        assert isinstance(row, PrivacyAudit)
        assert row.user_id == _UID
        assert row.target_user_id is None
        assert row.event_kind == "export_data"
        assert row.consent_scope is None
        assert row.ip_hash is not None
        assert "203.0.113.7" not in row.ip_hash

    def test_no_ip_yields_none_ip_hash(self) -> None:
        session = _FakeSession()
        row = record_export_audit(session, user_id=_UID, ip=None, settings=_settings(salt="s"))
        assert row.ip_hash is None


class TestRecordConsentChangeAudit:
    def test_adds_consent_change_row_with_scope(self) -> None:
        session = _FakeSession()
        row = record_consent_change_audit(
            session,
            user_id=_UID,
            consent_scope=ConsentScope.service_core,
            ip="203.0.113.7",
            settings=_settings(salt="s"),
        )
        assert session.added == [row]
        assert row.user_id == _UID
        assert row.event_kind == "consent_change"
        assert row.consent_scope == "service_core"
        assert row.target_user_id is None


class TestRecordAdminAccessAudit:
    """SEC-09 시점 호출부 0곳 — 그래도 writer 자체는 실 동작해야 미래 콘솔이 안전히 배선."""

    def test_adds_admin_access_row_with_actor_and_target(self) -> None:
        session = _FakeSession()
        row = record_admin_access_audit(
            session,
            actor_user_id=_UID,
            target_user_id=_TARGET_UID,
            ip="203.0.113.7",
            settings=_settings(salt="s"),
        )
        assert session.added == [row]
        assert row.user_id == _UID  # 행위자
        assert row.target_user_id == _TARGET_UID  # 행위 대상(본인 아닌 학생)
        assert row.event_kind == "admin_access"
        assert row.consent_scope is None


class TestRecordContentMutationAudit:
    """SEC-29 — `api/concepts.py`·`api/problems.py`의 CUD 6라우터가 실 첫 호출부."""

    def test_adds_content_mutation_row_with_resource_fields(self) -> None:
        resource_id = uuid.uuid4()
        session = _FakeSession()
        row = record_content_mutation_audit(
            session,
            actor_user_id=_UID,
            resource_type=PrivacyAuditResourceType.concept,
            resource_id=resource_id,
            action=PrivacyAuditAction.create,
            ip="203.0.113.7",
            settings=_settings(salt="s"),
        )
        assert session.added == [row]
        assert row.user_id == _UID  # 행위자(관리자)
        assert row.target_user_id is None  # 대상은 사용자가 아니라 리소스
        assert row.event_kind == "content_mutation"
        assert row.resource_type == "concept"
        assert row.resource_id == resource_id
        assert row.action == "create"
        assert row.consent_scope is None

    def test_action_and_resource_type_vary_independently(self) -> None:
        """세 값(resource_type·resource_id·action)이 서로 다른 조합에서도 올바르게 채워진다."""
        session = _FakeSession()
        resource_id = uuid.uuid4()
        row = record_content_mutation_audit(
            session,
            actor_user_id=_UID,
            resource_type=PrivacyAuditResourceType.problem,
            resource_id=resource_id,
            action=PrivacyAuditAction.delete,
            ip=None,
            settings=_settings(salt="s"),
        )
        assert row.resource_type == "problem"
        assert row.action == "delete"
        assert row.ip_hash is None  # ip=None → 해싱할 것이 없음(hash_client_ip 계약)
