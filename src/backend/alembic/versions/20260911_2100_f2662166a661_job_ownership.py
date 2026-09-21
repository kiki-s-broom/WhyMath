"""job_ownership 테이블 (비동기 QUALITY 작업 소유권·SEC-27, 48_보안 §P0)

`/v1/jobs/{job_id}` 폴링이 인증만 게이트하고 소유권(job↔user) 검사가 없던 갭(SEC-24(원
SEC-15) M6·`app.py` 모듈 docstring)을 메운다. Celery 자체는 job_id 외 메타데이터가 없어
소유자 기록은 이 백엔드가 별도로 영속한다. ORM 정본은
`whymath_backend/db/models/job_ownership.py`(JobOwnership). enum 없음(String·UUID·
TIMESTAMPTZ 기본 타입).

스키마:
  - job_id(String(255) PK = Celery 태스크 id·외부 발급). server_default 없음 — 큐잉 직후
    API 핸들러가 명시 기록.
  - user_id(UUID NOT NULL·FK user_profile.user_id) — 소유자.
  - created_at(TIMESTAMPTZ NOT NULL·server_default now()) — 기록 시각.

인덱스: 없음(조회는 PK 단건 lookup뿐 — refresh_token_session.py와 달리 사용자별 목록
조회 소비처가 아직 없다).

downgrade(왕복 안전 — CI 왕복 검증): 테이블 drop. 인덱스·enum 없어 후처리 불요.

Revision ID: f2662166a661
Revises: 19149e92d368
Create Date: 2026-09-11 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2662166a661"
down_revision: str | None = "19149e92d368"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_ownership",
        # PK = Celery 태스크 id(문자열, 외부 발급·server_default 없음 — API가 큐잉 직후 기록).
        sa.Column("job_id", sa.String(length=255), nullable=False),
        # 소유자 — user_profile FK(NOT NULL).
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_job_ownership")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_profile.user_id"],
            name=op.f("fk_job_ownership_user_id_user_profile"),
        ),
    )


def downgrade() -> None:
    op.drop_table("job_ownership")
