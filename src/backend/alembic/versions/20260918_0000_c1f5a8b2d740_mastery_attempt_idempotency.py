"""concept/skill_mastery_history.attempt_id + 부분 유니크 인덱스 (EOS-108)

계획서 300 §6(Mastery Engine v1)의 "같은 Attempt가 두 번 반영되면 KPI 2(State Integrity)가
즉시 깨진다"를 **DB 수준에서** 집행한다.

이 리비전이 하는 일:
  ① `concept_mastery_history.attempt_id`(uuid·NULL 허용) 추가.
  ② `skill_mastery_history.attempt_id`(uuid·NULL 허용) 추가.
  ③ 두 테이블에 `(user_id, {concept_id|skill_id}, attempt_id)` **부분 유니크 인덱스**
     (`WHERE attempt_id IS NOT NULL`).

왜 부분 인덱스인가: 시도에서 유래하지 않은 측정(배치·백필·진단 세션)은 `attempt_id`가 NULL이며
서로 충돌하면 안 된다. PostgreSQL은 NULL을 유니크 비교에서 서로 다른 값으로 보므로 전체
인덱스로도 동작은 같지만, **의도를 조건으로 적어 두면** 나중에 `NULLS NOT DISTINCT`로 기본값이
바뀌거나 다른 엔진으로 옮겨도 규칙이 살아 남는다.

왜 FK가 아닌가: `user_id`·`concept_id`가 이미 FK가 아닌 느슨참조다(hypertable 선례). 더해서
보존기한 파기로 `problem_attempt` 행이 사라져도 **학습 곡선은 남아야 한다** — FK는 그 보존을
CASCADE(같이 삭제) 또는 삭제 실패로 깨뜨린다. `learning_state_transition`(5a7c31d9e0b4)이
`attempt_id`에 FK를 걸지 않은 것과 같은 판단이다.

**비파괴**: NULL 허용 컬럼 추가 + 인덱스 추가뿐이다. 기존 행은 전부 `attempt_id IS NULL`이 되어
부분 인덱스의 대상 밖에 있으므로, **기존 데이터가 어떤 상태든 이 마이그레이션은 실패하지
않는다**(소급 유니크 위반이 구조적으로 불가능하다). 기존 쿼리도 컬럼을 열거하지 않는 한 영향 0.

Revision ID: c1f5a8b2d740
Revises: 5a7c31d9e0b4
Create Date: 2026-09-18 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1f5a8b2d740"
down_revision: str | None = "5a7c31d9e0b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (테이블, 대상 컬럼, 인덱스 이름) — 개념 축·스킬 축이 같은 모양이라 한 벌로 돈다.
_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("concept_mastery_history", "concept_id", "uq_concept_mastery_history_attempt"),
    ("skill_mastery_history", "skill_id", "uq_skill_mastery_history_attempt"),
)


def upgrade() -> None:
    """컬럼 2개 + 부분 유니크 인덱스 2개."""
    for table, target_column, index_name in _TARGETS:
        op.add_column(table, sa.Column("attempt_id", sa.Uuid(), nullable=True))
        op.create_index(
            index_name,
            table,
            ["user_id", target_column, "attempt_id"],
            unique=True,
            postgresql_where=sa.text("attempt_id IS NOT NULL"),
        )


def downgrade() -> None:
    """역적용 — 인덱스 먼저, 컬럼 나중(의존 순서). 데이터 손실은 `attempt_id` 값뿐이다."""
    for table, _target_column, index_name in reversed(_TARGETS):
        op.drop_index(index_name, table_name=table)
        op.drop_column(table, "attempt_id")
