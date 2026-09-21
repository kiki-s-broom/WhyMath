"""learner_state 테이블 — 학습자 현재 상태 1행 + 자동 생성(provisioning) 계보 (EOS-103)

정본 `docs/architecture/canonical_entity_model_v1.md` §2-A 13번 `LearnerState`의 **두 번째
좌석**. 좌석 추가는 정본 갱신을 경유했다(`EOS-49`가 `concept_version`을 Concept의 4번째
좌석으로 편입한 선례와 동형) — `tests/backend/db/test_canonical_entity_model_freeze.py`의
①(전수 귀속)·④(문서 정합)가 이 편입을 기계로 대조한다.

이 리비전이 하는 일:
  ① `learner_state` 테이블 생성 — PK 겸 FK `learner_id → user_profile.user_id`.
     학생 1명당 **정확히 1행**(대리키 없음 — 두면 "현재 상태"가 둘일 수 있게 된다).
  ② 생산자가 없던 두 축을 영속: `curriculum_id`·`current_objective_id`(둘 다 nullable
     문자열·FK 미적용). FK 미적용 사유는 ORM 모듈 주석 참조(교육과정 키 미결정 · 목표
     삭제가 학생 상태를 막지 않아야 함).
  ③ 생성·변경 계보 4컬럼: `provisioned_at`·`provisioned_by`·`updated_at`·`revision`.

**기존 좌석 무영향**: `user_state_snapshot`(첫 좌석 · 시점별 스냅샷 이력)은 이 리비전이
읽지도 쓰지도 않는다. 그 좌석의 writer 0 상태를 배선할지 폐기할지는 `EOS-10`이 소유한다.

**신규 컬럼은 전부 nullable 또는 server_default를 갖는다** — 나중에 BKT/DKT 축이 생산자를
얻어 컬럼이 늘 때 기존 행 백필 없이 편입되게 하는 규약이며, `tests/backend/db/
test_learner_state_orm.py`가 그 규약을 동결한다.

Revision ID: a7d41c9e0b52
Revises: 67cf48ad3bce
Create Date: 2026-09-16 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d41c9e0b52"
down_revision: str | None = "67cf48ad3bce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learner_state",
        sa.Column(
            "learner_id",
            sa.Uuid(),
            sa.ForeignKey("user_profile.user_id", name="fk_learner_state_user_profile"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("curriculum_id", sa.String(length=128), nullable=True),
        sa.Column("current_objective_id", sa.String(length=128), nullable=True),
        sa.Column(
            "provisioned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("provisioned_by", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("learner_state")
