"""learning_state_transition 테이블 + 상태·트리거 enum (EOS-105)

계획서 300 §3 「Phase 2의 핵심 상태 머신」(= `docs/ops/phase2_eos_closed_loop_execution_
prompts.md` §P-04)의 8상태 학습 상태 머신을 영속화한다.

이 리비전이 하는 일:
  ① `learning_state_enum`(8종: NEW/DIAGNOSING/READY/LEARNING/PRACTICING/ASSESSING/
     REMEDIATING/ADVANCING) + `learning_state_trigger_enum`(13종) 생성.
  ② `learning_state_transition` 테이블 생성 — 학생별 상태 전이 **append-only 원장**.
     현재 상태는 이 테이블의 최신 행에서 파생되며 별도 상태 컬럼을 두지 않는다(같은 사실의
     두 번째 진실 원천 회피 — 2026-09-03 보류 사유에 대한 처치. 모델 docstring 참조).
  ③ `(user_id, occurred_at DESC)` 인덱스 — 현재 상태 조회가 지배적 질의다.

**비파괴**: 새 테이블·새 enum만 만든다. 기존 테이블에 컬럼을 추가하거나 제약을 바꾸지
않으므로 기존 행·기존 쿼리에 영향이 0이다. 특히 `user_state_snapshot`(writer 0 좌석)과
EOS-103이 도입 중인 `learner_state`(PR #1185 미머지) **어느 쪽도 건드리지 않는다** — 담는
사실이 달라 좌석이 겹치지 않는다(모델 docstring "좌석 판정").

FK 판단: `user_id`만 실 FK(`user_profile.user_id`)다. `concept_id`·`attempt_id`에는 FK를
걸지 **않는다** — 개념 폐기·개명이나 보존기한 파기로 그 대상이 사라져도 전이 이력은 남아야
하며(append-only 원장의 요건), FK는 그 보존을 CASCADE 또는 삭제 실패로 깨뜨린다.

Revision ID: 5a7c31d9e0b4
Revises: 67cf48ad3bce
Create Date: 2026-09-16 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5a7c31d9e0b4"
down_revision: str | None = "67cf48ad3bce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# enum 라벨을 ORM에서 import하지 않고 인라인으로 박는다 — 마이그레이션은 결정적이어야 하고,
# 훗날 `LearningState`에 값이 추가돼도 이 리비전이 만드는 타입은 그때의 8종 그대로여야 한다
# (concept_version 리비전의 `_STATUS_LABELS` 선례 동형). 값이 늘면 새 리비전이 ALTER TYPE한다.
_STATE_LABELS = (
    "NEW",
    "DIAGNOSING",
    "READY",
    "LEARNING",
    "PRACTICING",
    "ASSESSING",
    "REMEDIATING",
    "ADVANCING",
)

_TRIGGER_LABELS = (
    "DIAGNOSIS_STARTED",
    "DIAGNOSIS_COMPLETED",
    "LEARNING_STARTED",
    "PRACTICE_STARTED",
    "ATTEMPT_SUBMITTED",
    "POLICY_ADVANCE",
    "POLICY_PRACTICE_LOW_CONFIDENCE",
    "POLICY_REMEDIATE_MISCONCEPTION",
    "POLICY_PREREQUISITE_GAP",
    "POLICY_REPEATED_FAILURE",
    "POLICY_PRACTICE_UNDIAGNOSED",
    "REMEDIATION_COMPLETED",
    "ADVANCE_COMPLETED",
)


def upgrade() -> None:
    op.create_table(
        "learning_state_transition",
        sa.Column(
            "transition_id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        # from_state가 nullable이 아닌 이유: 최초 전이도 NEW에서 출발한다("상태 없음"이라는
        # 아홉 번째 값을 만들지 않는다 — 그러면 NULL 분기가 코드 전역에 생긴다).
        sa.Column(
            "from_state",
            sa.Enum(*_STATE_LABELS, name="learning_state_enum"),
            nullable=False,
        ),
        sa.Column(
            "to_state",
            # 같은 PG 타입을 두 컬럼이 공유한다 — 두 번째 Column에서 create_type=False로
            # 중복 CREATE TYPE를 막는다(단일 create_table 안의 동일 enum 재사용 관용구).
            sa.Enum(*_STATE_LABELS, name="learning_state_enum", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "trigger",
            sa.Enum(*_TRIGGER_LABELS, name="learning_state_trigger_enum"),
            nullable=False,
        ),
        # 정책이 낸 전이만 채워진다. 생애주기 전이(진단 시작 등)는 NULL — "규칙이 없었다"와
        # "규칙을 못 적었다"를 구분하려고 빈 문자열로 채우지 않는다.
        sa.Column("rule_id", sa.String(length=64), nullable=True),
        # FK 없음(의도) — 상단 docstring "FK 판단" 참조.
        sa.Column("concept_id", sa.Text(), nullable=True),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_profile.user_id"],
            name=op.f("fk_learning_state_transition_user_id_user_profile"),
        ),
        sa.PrimaryKeyConstraint("transition_id", name=op.f("pk_learning_state_transition")),
    )
    op.create_index(
        "idx_learning_state_transition_user_time",
        "learning_state_transition",
        ["user_id", sa.text("occurred_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_learning_state_transition_user_time",
        table_name="learning_state_transition",
    )
    op.drop_table("learning_state_transition")
    # create_table이 암묵 생성한 두 enum 타입은 drop_table이 지우지 않는다 — 명시적으로 지운다.
    # 지우지 않으면 downgrade 후 재-upgrade가 "type already exists"로 죽는다(왕복 불가).
    sa.Enum(name="learning_state_trigger_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="learning_state_enum").drop(op.get_bind(), checkfirst=True)
