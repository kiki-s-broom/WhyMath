"""감사 Pydantic 스키마 — `DeletionAudit`(slice 58) + `PrivacyAudit`(SEC-09) 조회 API 응답.

slice 57이 `deletion_audit`에 적재하는 행의 *읽기* 표현. `GET /v1/me/deletions`가 본인 삭제
이력을 반환할 때 직렬화에 쓴다. 삭제 *메타*만(콘텐츠 없음 — slice 57 설계: 누가·무엇·언제).
ORM(`db/models/audit.py`)과 별도로 세운 검증·API 레이어이며 `to_schema`/`from_schema`가 잇는다
(activity.py·user.py 동일 패턴).

SEC-09의 `PrivacyAudit`은 개인정보 감사 4종(반출·동의변경·관리자접근·역할변경)의 읽기 표현 —
`GET /v1/me/privacy-audit`가 본인 스코핑으로 반환한다. 동일 패턴(메타만·`to_schema`/
`from_schema`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.schema.enums import (
    AuditEventKind,
    AuditResourceType,
    ConsentScope,
    DefectCategory,
    PrivacyAuditAction,
    PrivacyAuditResourceType,
)


class DeletionAudit(BaseModel):
    """본인 리소스 삭제 감사 1행(읽기) — append-only 기록의 단일 표현."""

    model_config = ConfigDict(
        # 추가 필드 금지 — Pydantic 모델이 스키마의 단일 진실
        extra="forbid",
        # enum 값 그대로 직렬화(resource_type="learning_session")
        use_enum_values=True,
        # 문자열 양끝 공백 제거
        str_strip_whitespace=True,
    )

    audit_id: uuid.UUID = Field(default_factory=uuid4, description="감사 PK (UUID)")
    user_id: uuid.UUID | None = Field(
        default=None,
        description="삭제를 수행한 소유자 (plain UUID — FK 아님, 사용자 삭제돼도 잔존)",
    )
    resource_type: AuditResourceType | None = Field(
        default=None,
        description="삭제된 도메인 (learning_session/dialogue/assessment)",
    )
    resource_id: uuid.UUID | None = Field(
        default=None,
        description="삭제된 리소스의 id (해당 도메인 PK)",
    )
    deleted_at: datetime | None = Field(
        default=None,
        description="삭제·감사 기록 시각 (DB server_default now())",
    )


class PrivacyAudit(BaseModel):
    """SEC-09 개인정보·콘텐츠 감사 5종(반출·동의변경·관리자접근·역할변경·콘텐츠CUD) 1행(읽기)
    — append-only 표현.

    본문·PII 값·평문 IP는 어떤 필드에도 담지 않는다(`docs/architecture/account_security_gap_
    review.md` D3·CLAUDE.md 미성년 PII 보호). `target_user_id`는 행위자(`user_id`)와 다른
    사용자의 데이터가 대상일 때만(관리자접근) 채워지고, 본인 계정의 사건(반출·동의변경·역할변경)·
    콘텐츠CUD(대상이 사용자가 아니라 리소스)는 NULL이다 — 역할변경은 운영자가 셸에서 돌리는
    CLI라 인증된 행위자 신원이 없어 `admin_access`와 달리 대상 계정 본인의 사건으로 적재된다
    (`privacy/audit.py::record_role_change_audit` 참조). `resource_type`/`resource_id`/`action`
    은 콘텐츠CUD 전용(SEC-29) — 대상이 사용자가 아니라 콘텐츠 리소스일 때 그 역할을 대신한다.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    audit_id: uuid.UUID = Field(default_factory=uuid4, description="감사 PK (UUID)")
    user_id: uuid.UUID | None = Field(
        default=None,
        description="행위자(action을 수행한 주체) — plain UUID, FK 아님(계정 삭제돼도 잔존)",
    )
    target_user_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "행위 대상 사용자(행위자와 다를 때만 — 관리자접근) — 본인 행위(반출·동의변경)·"
            "콘텐츠CUD는 NULL"
        ),
    )
    event_kind: AuditEventKind | None = Field(
        default=None,
        description=(
            "감사 이벤트 종류(export_data/consent_change/admin_access/"
            "role_change/content_mutation)"
        ),
    )
    consent_scope: ConsentScope | None = Field(
        default=None,
        description="event_kind=consent_change일 때만 — 어떤 동의 범위가 바뀌었는지",
    )
    resource_type: PrivacyAuditResourceType | None = Field(
        default=None,
        description="event_kind=content_mutation일 때만 — 콘텐츠 리소스 도메인(concept/problem)",
    )
    resource_id: uuid.UUID | None = Field(
        default=None,
        description="event_kind=content_mutation일 때만 — 대상 리소스 id(해당 도메인 PK)",
    )
    action: PrivacyAuditAction | None = Field(
        default=None,
        description="event_kind=content_mutation일 때만 — CRUD 동작(create/update/delete)",
    )
    ip_hash: str | None = Field(
        default=None,
        description="sha256(salt+ip) — 평문 IP 미저장. salt 미설정(개발·CI)이면 None",
    )
    occurred_at: datetime | None = Field(
        default=None,
        description="감사 기록 시각 (DB server_default now())",
    )


class DefectReport(BaseModel):
    """학생 결함 신고 1행(append-only) — RPT-01.

    `docs/architecture/service_operations_gap_review.md` §3 D1. **`user_id` 필드 자체가
    존재하지 않는다** — 결함 대장은 "누가"가 아니라 "무엇이"를 기록한다. 이 필드 부재로
    ⑴ 미성년 PII 미저촉 ⑵ 보존·파기 대상 아님 ⑶ 반출·삭제권 대상 아님 ⑷ 회신 유혹이 구조적으로
    차단(CS로 새지 않음)이 자동 성립한다(`tests/backend/db/test_defect_report_no_user_id.py`가
    이 부재를 컬럼 레벨로 동결).

    v0는 카테고리 + `problem_id`만(자유서술 0). `problem_id`는 문항이 나중에 삭제·재편돼도
    신고 기록이 잔존해야 하므로 FK가 아니라 plain UUID(`DeletionAudit.resource_id` 선례).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    report_id: uuid.UUID = Field(default_factory=uuid4, description="신고 PK (UUID)")
    category: DefectCategory = Field(description="결함 카테고리(폐쇄 6종 — 자유서술 없음)")
    problem_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "신고 대상 문항 id(선택 — plain UUID, FK 아님). 문항 무관 신고(UI문제 등)는 None."
        ),
    )
    reported_at: datetime | None = Field(
        default=None,
        description="신고 접수 시각(DB server_default now())",
    )
