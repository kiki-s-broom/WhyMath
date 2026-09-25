"""learning_session.last_activity_at + 학생당 열린 서버 세션 1개 부분 유니크 인덱스 (EOS-131)

`learning_session`은 테이블·조회·종료·삭제 표면만 있고 **writer가 0건**이었다(2026-09-16
`l2/learning_event_trace` 실측). EOS-131이 서버 측 30분 유휴 규칙 writer
(`l2/learning_session_writer`)를 배선하면서 두 가지 좌석이 필요해졌다.

- **`last_activity_at` (nullable TIMESTAMPTZ)**: 유휴 간격을 재려면 "이 세션의 마지막 학습
  활동 시각"이 있어야 한다. `ended_at`은 *종료*의 좌석이라 열린 세션에서는 NULL이어야 하고,
  `duration_seconds`는 경과 초라 시각이 아니다. 기존 행은 전부 NULL로 남는다 — writer 이전의
  행(테스트·수동 적재)은 서버 추론 세션이 아니므로 값을 지어내지 않는다(NULL=서버 writer가
  만들지 않은 행). 이 NULL 여부가 곧 "서버 추론 세션인가"의 판별자다.
- **부분 유니크 인덱스 `uq_learning_session_open_per_user`**: `(user_id) WHERE ended_at IS NULL
  AND last_activity_at IS NOT NULL`. 같은 학생의 요청 두 건이 거의 동시에 "열린 세션 없음"을
  보고 각자 세션을 열면 KPI 분모·재방문율이 부풀어 오른다(EOS-131 ⑩). 행 잠금만으로는 *아직
  행이 없는* 경합을 막을 수 없으므로(잠글 대상 부재) DB 제약으로 막는다. writer는
  `INSERT … ON CONFLICT DO NOTHING`으로 패자를 승자의 세션에 합류시킨다.
  범위를 `last_activity_at IS NOT NULL`로 좁힌 이유: writer 이전의 행(값 NULL)에 한 학생의 열린
  세션이 여럿 있어도 이 마이그레이션이 실패하지 않게 하고(기존 데이터 무수정), 제약의 대상을
  이 writer가 만드는 행으로 한정한다.

additive만 한다 — 데이터 백필 없음. downgrade는 인덱스 → 컬럼 순으로 되돌린다(왕복 가능).

Revision ID: 8e4c2a7f1b93
Revises: 5b3e9c27a1f6
Create Date: 2026-09-25 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8e4c2a7f1b93"
down_revision: str | None = "5b3e9c27a1f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_learning_session_open_per_user"


def upgrade() -> None:
    """`last_activity_at` 추가 + 학생당 열린 서버 세션 1개 부분 유니크 인덱스."""
    op.add_column(
        "learning_session",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        _INDEX,
        "learning_session",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL AND last_activity_at IS NOT NULL"),
    )


def downgrade() -> None:
    """인덱스 → 컬럼 순 제거. 서버 세션의 마지막 활동 시각만 소실(세션 행·시도는 무영향)."""
    op.drop_index(_INDEX, table_name="learning_session")
    op.drop_column("learning_session", "last_activity_at")
