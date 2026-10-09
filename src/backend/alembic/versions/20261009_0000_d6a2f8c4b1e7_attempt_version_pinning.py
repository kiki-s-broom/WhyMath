"""problem_attempt 버전 고정 — problem_version_id + evaluation_context (EOS-47)

`docs/architecture/44_eos_version_management.md` §10.2(Runtime VersionContext)·§11(AI 재현성)의
"한 번의 채점이 어떤 환경에서 나왔는가를 나중에 재현한다" 요구를 `problem_attempt`에 영속화한다.
선행: ARCH-31(`c5e1f9a3b7d2` — `problem_version` 테이블). 계약 정본·키별 출처:
`whymath_backend/schema/evaluation_context.py`.

이 리비전이 하는 일(**additive·비파괴** — 기존 행·writer·소비자 무영향):
  ① `problem_attempt.problem_version_id` — nullable UUID, FK → `problem_version.version_id`.
     시도 접수 시점의 `problem.problem_version_id` 포인터를 복사해 넣는 자리
     (`l2/attempt_version_pin`).
  ② `problem_attempt.evaluation_context` — nullable JSONB. 채점 시점의 교육 환경 스냅숏.

**백필 없음**(두 컬럼 모두 NULL로 시작): 기존 시도에 판·환경을 날조해 채우면 "그 학생이 그 판을 푼
적 없는데 푼 것으로 기록된" 거짓 재현 근거가 된다 — NULL=고정 안 됨이 정직하다(DP-03 `event_uuid`·
ARCH-31 `problem_version_id` 규약). 기본값도 두지 않는다.

인덱스는 만들지 않는다: 이 컬럼을 조건으로 읽는 소비처가 아직 없다(재현 조회는 `attempt_id` PK로
들어온다). `problem_version` 행은 PUBLISHED 불변이고 삭제 경로가 없어 FK 검사 비용 문제도 없다.
소비처가 생기면 그때 부분 인덱스(`WHERE problem_version_id IS NOT NULL`)로 추가한다.

upgrade: 컬럼 2개 add + FK 1개 create(제약명 결정성을 위해 add_column 뒤
         `op.create_foreign_key` 분리 — `67cf48ad3bce`·`c5e1f9a3b7d2` 선례).
downgrade: FK drop → 컬럼 2개 drop(역순 대칭).

Revision ID: d6a2f8c4b1e7
Revises: c5e9f3a7b1d4
Create Date: 2026-10-09 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6a2f8c4b1e7"
down_revision: str | None = "c5e9f3a7b1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "fk_problem_attempt_problem_version_id_problem_version"


def upgrade() -> None:
    op.add_column(
        "problem_attempt",
        sa.Column("problem_version_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "problem_attempt",
        sa.Column("evaluation_context", JSONB(none_as_null=True), nullable=True),
    )
    op.create_foreign_key(
        _FK,
        "problem_attempt",
        "problem_version",
        ["problem_version_id"],
        ["version_id"],
    )


def downgrade() -> None:
    op.drop_constraint(_FK, "problem_attempt", type_="foreignkey")
    op.drop_column("problem_attempt", "evaluation_context")
    op.drop_column("problem_attempt", "problem_version_id")
