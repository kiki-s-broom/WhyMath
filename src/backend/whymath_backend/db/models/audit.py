"""감사(audit) ORM 모델 — `DeletionAudit`(slice 57)·`PrivacyAudit`(SEC-09)·`DefectReport`(RPT-01).

본인 데이터 삭제(`DELETE /v1/me/{sessions,dialogues,assessments}/{id}`, slice 51~53) 시 *부모
리소스 삭제 이벤트*를 append-only로 기록한다 — GDPR 삭제권 이행의 *증빙*(언제·누가·무엇을
지웠는가). 삭제된 **콘텐츠 자체는 저장하지 않는다**(메타데이터만: 도메인·id·시각·소유자
UUID) — 미성년 PII 비저촉(CLAUDE.md). 자식(cascade·slice 56)은 DB 레벨이라 비가시 → 부모만
기록(개별 자식 감사는 앱레벨 명시 삭제 필요·후속).

설계 결정(`DeletionAudit`):
  - `user_id`는 **FK 아님**(plain UUID) — 사용자 프로필이 삭제돼도 감사 로그는 *잔존*해야
    하므로(FK CASCADE/RESTRICT 어느 쪽도 부적합). compliance 로그의 독립성.
  - `resource_type`은 `sa.String(32)`(네이티브 PG enum 미생성) — 코드 안전성은 Pydantic
    `AuditResourceType`(.value 저장)으로 확보, DB는 단순 문자열(감사 메타 태그).
  - append-only — UPDATE/DELETE 라우터 없음. 읽기는 slice 58 `GET /v1/me/deletions`(본인 스코핑).

`PrivacyAudit`(SEC-09)은 개인정보·콘텐츠 감사 5종(반출·동의변경·관리자접근·역할변경·
**콘텐츠CUD**)의 append-only 기록이다 — `docs/architecture/account_security_gap_review.md`
D3의 경계 확정(본인 조회 29개 엔드포인트 전수 감사는 *하지 않는다*)에 따라 "시스템 밖으로
나가는 사건"·"본인 아닌 주체의 접근"·"계정 권한 자체의 변경"·"전역 콘텐츠 리소스의 CUD"
(SEC-29 추가)만 기록한다(역할변경은 ADMIN-01이 추가 — `ops/role_grant_cli.py`가 유일 생산자이고
역할 UPDATE와 **동일 트랜잭션**으로 적재된다. 콘텐츠CUD는 SEC-29가 추가 — `api/concepts.py`·
`api/problems.py`의 `RequireContentAdmin` 게이팅 6라우터가 생산자다). `DeletionAudit`의
append-only·plain-UUID·String(32) 패턴을 그대로 답습하되
**삭제 이벤트는 중복 기록하지 않는다**(`deletion_audit`가 삭제 감사의 단일 권위 — 이중
진실원천 금지).

`DefectReport`(RPT-01)는 학생 결함 신고(문항·AI응답·수식 오류)의 append-only 기록이다 —
`docs/architecture/service_operations_gap_review.md` §3 D1. **`user_id` 컬럼 자체를 만들지
않는다**(다른 두 감사 테이블과의 핵심 차이 — 저것들은 "누가"가 필수지만 결함 대장은 "무엇을"만
필요하다). `attempt_event`/`EventType`은 재사용하지 않는다(`EventType`은 네이티브 PG enum이라
값 추가에 alembic이 필요해지고, `attempt_event`는 `privacy/retention.py`가 이미 3년 보존파기
대상으로 지정해 학생 데이터 파기와 함께 사라지는데 결함 대장은 학생 기록이 아니라 콘텐츠
기록이라 그와 함께 사라지면 안 된다).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.schema.audit import DefectReport as SchemaDefectReport
from whymath_backend.schema.audit import DeletionAudit as SchemaDeletionAudit
from whymath_backend.schema.audit import PrivacyAudit as SchemaPrivacyAudit


class DeletionAudit(Base):
    """GDPR 삭제 감사 1행 — 한 번의 본인 리소스 삭제 이벤트."""

    __tablename__ = "deletion_audit"

    audit_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    # FK 아님(plain UUID) — 사용자 삭제돼도 감사 잔존(설계 메모 참조).
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    resource_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    # slice 60: list_my_deletions(user_id 필터·deleted_at desc 정렬) 접근 패턴 인덱스 —
    # learning_session.idx_session_user·dialogue.idx_dialogue_user와 동형(parity).
    __table_args__ = (sa.Index("idx_deletion_audit_user", "user_id", sa.desc("deleted_at")),)

    # ── 변환 헬퍼 (schema↔db seam, activity.py 패턴) — slice 58 조회 API용 ──
    @classmethod
    def from_schema(cls, schema: SchemaDeletionAudit) -> DeletionAudit:
        """검증된 `schema.DeletionAudit` → 영속 ORM(mapper 컬럼키 필터)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaDeletionAudit:
        """영속 ORM → `schema.DeletionAudit`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaDeletionAudit.model_validate(data)


class PrivacyAudit(Base):
    """SEC-09 개인정보·콘텐츠 감사 1행 — 반출·동의변경·관리자접근·역할변경·콘텐츠CUD 5종 중
    1건의 append-only 기록.

    `user_id`는 **행위자**(action을 수행한 주체)다 — 본인 반출·동의변경이면 본인, 관리자접근·
    콘텐츠CUD면 그 관리자. `target_user_id`는 *행위자와 다른 사용자의 데이터가 대상일 때만*
    채운다(관리자접근이 자기 아닌 학생의 데이터를 봤을 때 그 학생 id) — 본인 행위(반출·동의변경)
    는 행위자==대상이라 중복 저장하지 않고 NULL로 둔다(현재 admin_access 호출부 0곳이라 실제로는
    항상 NULL — `AuditEventKind.admin_access` docstring 참조). 콘텐츠CUD도 대상이 사용자가
    아니라 리소스이므로 NULL(그 역할은 `resource_type`/`resource_id`가 대신한다).

    `consent_scope`는 `event_kind=consent_change`일 때만 채우는 구분 메타데이터(어떤 동의
    범위가 바뀌었는지) — `resource_type`/`resource_id`/`action`은 `event_kind=content_mutation`
    일 때만 채우는 구분 메타데이터(SEC-29, 어떤 콘텐츠에 무슨 CUD가 있었는지) — 그 외 이벤트는
    각각 NULL(한 event_kind가 자기 몫의 typed 컬럼만 채우는 패턴은 기존 consent_scope와 동형).
    자유텍스트 필드는 두지 않는다(감사 행이 PII를 우연히 담는 사고 방지 — CLAUDE.md 미성년 PII
    보호. SEC-29가 acceptance에서 제안한 `reason` 자유텍스트 컬럼은 이 불변식과 충돌해 **의도적
    으로 채택하지 않았다** — `action`+`resource_type`+`resource_id` 3종으로 "무엇을 했는지"는
    충분히 특정된다).

    설계 결정(DeletionAudit 패턴 답습 — `docs/architecture/account_security_gap_review.md` D3):
      - `user_id`/`target_user_id` 둘 다 **FK 아님**(plain UUID) — 계정 삭제 후에도 감사 잔존.
      - `event_kind`는 `sa.String(32)`(네이티브 PG enum 미생성) — Pydantic `AuditEventKind`
        (.value 저장)로 코드 안전성 확보, DB는 단순 문자열(AuditResourceType 선례).
      - `ip_hash`는 `sa.String(64)`(sha256 hex) **nullable** — salt 미설정(개발·CI)이면
        `privacy.audit.hash_client_ip`가 None을 반환해도 감사 행 자체는 적재된다(주행위를
        막지 않기 위해 — config.py `pii_audit_ip_salt` 설명 참조). 평문 IP는 어떤 컬럼에도
        저장하지 않는다.
      - append-only — UPDATE/DELETE 라우터 없음. 읽기는 `GET /v1/me/privacy-audit`(본인 스코핑
        — `user_id`로 필터, `DeletionAudit`/`GET /v1/me/deletions` 패턴 답습).
      - **학생 소유 데이터의 삭제 이벤트는 여기 적재하지 않는다** — `deletion_audit`가 그
        도메인의 단일 권위(이중 진실원천 금지). `api/me.py:291`의 `_delete_owned_resource`도
        `erase_my_account`도 이 테이블에 쓰지 않는다(회귀 테스트로 동결 —
        `tests/backend/api/test_privacy_audit_integration.py`). 콘텐츠(개념·문항) 삭제는
        학생 소유 데이터가 아니므로 이 경계 밖 — `content_mutation`의 `action=delete`로 여기
        적재된다(SEC-29).
      - `resource_type`/`action`도 `event_kind`/`consent_scope`와 동일하게 `sa.String`
        (네이티브 PG enum 미생성) — 코드 안전성은 Pydantic `PrivacyAuditResourceType`/
        `PrivacyAuditAction`(.value 저장)으로, DB는 단순 문자열.
      - `resource_type`/`resource_id`/`action` 셋 다 nullable — `event_kind=content_mutation`
        일 때만 채워진다. 별도 인덱스는 두지 않는다(target_user_id와 동일 판단 — 이 컬럼들을
        조건으로 한 조회 소비처가 아직 없다. 필요해지면 실 쿼리 부하로 다시 판단 — YAGNI).
    """

    __tablename__ = "privacy_audit"

    audit_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    # FK 아님(plain UUID) — 사용자 삭제돼도 감사 잔존(DeletionAudit 설계 메모 참조).
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    event_kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    consent_scope: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    # SEC-29: event_kind=content_mutation 전용 — 콘텐츠 리소스 CUD 식별(개인정보 대상이 아니므로
    # target_user_id 대신 이 셋을 쓴다. PrivacyAuditResourceType/PrivacyAuditAction 참조).
    resource_type: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    action: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    # `GET /v1/me/privacy-audit`(user_id 필터·occurred_at desc 정렬) 접근 패턴 인덱스 —
    # idx_deletion_audit_user와 동형(parity). target_user_id는 admin_access 호출부가 생길 때
    # 실 쿼리 부하로 다시 판단(현재 0행이라 인덱스를 먼저 만들지 않는다 — YAGNI).
    __table_args__ = (sa.Index("idx_privacy_audit_user", "user_id", sa.desc("occurred_at")),)

    # ── 변환 헬퍼 (schema↔db seam, DeletionAudit 패턴) ──
    @classmethod
    def from_schema(cls, schema: SchemaPrivacyAudit) -> PrivacyAudit:
        """검증된 `schema.PrivacyAudit` → 영속 ORM(mapper 컬럼키 필터)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaPrivacyAudit:
        """영속 ORM → `schema.PrivacyAudit`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaPrivacyAudit.model_validate(data)


class DefectReport(Base):
    """RPT-01 학생 결함 신고 append-only 1행 — 카테고리 + 대상 문항 참조만.

    설계 결정(`DeletionAudit`/`PrivacyAudit` 패턴 답습·차이점 명시):
      - **`user_id` 컬럼이 없다**(이 클래스의 핵심 차이) — 결함 대장에 필요한 건 "누가"가
        아니라 "무엇이"다. 이 부재가 ⑴ 미성년 PII 미저촉 ⑵ 보존·파기 대상 아님 ⑶ 반출·삭제권
        대상 아님 ⑷ 회신 유혹 차단(CS로 새지 않음)을 구조적으로 성립시킨다. 이 부재는
        `tests/backend/db/test_defect_report_no_user_id.py`가 컬럼 목록 레벨로 동결한다.
      - `category`는 `sa.String(32)`(네이티브 PG enum 미생성) — 코드 안전성은 Pydantic
        `DefectCategory`(.value 저장)로, DB는 단순 문자열(`AuditResourceType` 선례).
      - `problem_id`는 **FK 아님**(plain UUID) — 문항이 나중에 삭제·재편돼도 신고 기록은
        잔존해야 한다(`DeletionAudit.resource_id` 설계 메모와 동일 근거). nullable — 문항과
        무관한 신고(UI문제 등)도 허용.
      - 자유서술 필드 없음(v0는 카테고리 + `problem_id`만) — 미성년 자유서술 PII 표면을 만들지
        않는다.
      - append-only — UPDATE/DELETE 라우터 없음(`api/reports.py`는 POST 1개만 노출).
    """

    __tablename__ = "defect_report"

    report_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    category: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    # FK 아님(plain UUID) — 문항이 삭제·재편돼도 신고 기록 잔존(DeletionAudit 설계 메모 참조).
    problem_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    reported_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    # qa_pipeline 축(harness/qa_pipeline.py `defect_report_intake`)의 카테고리별 집계 조회
    # 패턴 인덱스 — idx_deletion_audit_user/idx_privacy_audit_user와 동형(parity).
    __table_args__ = (sa.Index("idx_defect_report_category", "category", sa.desc("reported_at")),)

    # ── 변환 헬퍼 (schema↔db seam, DeletionAudit 패턴) ──
    @classmethod
    def from_schema(cls, schema: SchemaDefectReport) -> DefectReport:
        """검증된 `schema.DefectReport` → 영속 ORM(mapper 컬럼키 필터)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaDefectReport:
        """영속 ORM → `schema.DefectReport`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaDefectReport.model_validate(data)
