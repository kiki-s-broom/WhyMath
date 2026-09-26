"""privacy_audit.token_expires_at/issued_by 2컬럼 추가 (ADMIN-15 — 운영자 토큰 발급 감사)

`ops/operator_token_cli.py`가 운영자(`Role.CONTENT_ADMIN`) 계정에 단기 액세스 토큰을 발급할 때
남기는 6번째 `event_kind`("operator_token_issued")가 쓰는 typed 구분 메타데이터(ORM 정본은
`whymath_backend/db/models/audit.py::PrivacyAudit`).

왜 컬럼이 필요한가: ADMIN-15 acceptance ②는 감사 1행에 "누가·누구에게·언제·만료"를 요구한다.
기존 컬럼으로 채워지는 것은 "누구에게"(`user_id`)와 "언제"(`occurred_at`)뿐이고, **만료 시각과
발급자는 담을 자리가 없다**. 만료를 `occurred_at + 고정 TTL`로 역산하는 대안은 TTL 상수가 바뀌는
순간 과거 행의 의미가 조용히 바뀌므로 채택하지 않았다(간접 신호를 감사 사실로 쓰지 않는다).

스키마 변경(전부 nullable — 기존 5종 이벤트는 계속 NULL):
  - token_expires_at(TIMESTAMPTZ nullable) — 발급한 토큰의 `exp` 클레임과 같은 시각.
  - issued_by(String(64) nullable) — 발급을 실행한 운영자 셸의 로그인 이름(자유서술이 아니라
    식별자 — 형식은 CLI가 검증한다). 토큰 자체는 어떤 컬럼에도 저장하지 않는다.

인덱스 없음(resource_type 3컬럼·target_user_id와 동일 판단 — 이 컬럼을 조건으로 한 조회 소비처가
아직 없다. 발급 이력은 `idx_privacy_audit_user`(user_id, occurred_at)로 조회된다).

downgrade(왕복 안전 — CI 왕복 검증): 2컬럼 drop. 인덱스·enum 없어 후처리 불요.

Revision ID: 8c19e8a611e4
Revises: 8e4c2a7f1b93
Create Date: 2026-09-25 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c19e8a611e4"
down_revision: str | None = "8e4c2a7f1b93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "privacy_audit",
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("privacy_audit", sa.Column("issued_by", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("privacy_audit", "issued_by")
    op.drop_column("privacy_audit", "token_expires_at")
