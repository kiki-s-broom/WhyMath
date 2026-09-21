"""privacy_audit.resource_type/resource_id/action 3컬럼 추가 (SEC-29 — 콘텐츠CUD 감사)

`Role.CONTENT_ADMIN`이 콘텐츠 리소스(개념·문항)를 생성·수정·삭제할 때 남기는 5번째
`event_kind`("content_mutation")가 쓰는 typed 구분 메타데이터. 개인정보 대상이 아니라
콘텐츠 리소스 대상이므로 `target_user_id`가 아니라 이 3컬럼을 채운다(ORM 정본은
`whymath_backend/db/models/audit.py::PrivacyAudit`). enum 없음(String·UUID 기본 타입 — 코드
안전성은 `schema/enums.py`의 `PrivacyAuditResourceType`/`PrivacyAuditAction`이 담당).

스키마 변경(전부 nullable — 기존 4종 이벤트는 계속 NULL):
  - resource_type(String(32) nullable) — "concept"/"problem"(PrivacyAuditResourceType).
  - resource_id(UUID nullable) — 대상 리소스 PK. FK 아님(콘텐츠 삭제 후에도 감사 잔존 —
    DeletionAudit.resource_id·job_ownership 등 기존 "느슨참조" 선례와 동형).
  - action(String(16) nullable) — "create"/"update"/"delete"(PrivacyAuditAction).

인덱스 없음(target_user_id와 동일 판단 — 이 컬럼들을 조건으로 한 조회 소비처가 아직 없다.
`idx_privacy_audit_user`(user_id, occurred_at)로 이미 충분 — 콘텐츠CUD 행도 행위자
user_id로 조회된다).

downgrade(왕복 안전 — CI 왕복 검증): 3컬럼 drop. 인덱스·enum 없어 후처리 불요.

Revision ID: 4c6dfb1527a9
Revises: f2662166a661
Create Date: 2026-09-11 23:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c6dfb1527a9"
down_revision: str | None = "f2662166a661"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("privacy_audit", sa.Column("resource_type", sa.String(length=32), nullable=True))
    op.add_column("privacy_audit", sa.Column("resource_id", sa.Uuid(), nullable=True))
    op.add_column("privacy_audit", sa.Column("action", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("privacy_audit", "action")
    op.drop_column("privacy_audit", "resource_id")
    op.drop_column("privacy_audit", "resource_type")
