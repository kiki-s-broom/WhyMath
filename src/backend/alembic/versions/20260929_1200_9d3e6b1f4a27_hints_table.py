"""hints 테이블 신설 (S4-11 — graded 힌트 카탈로그 · HintNode Persistence 연기 해제)

ORM 정본: `whymath_backend/db/models/hint.py::Hint`. 설계 정본: `schemas/v1.1/hint.schema.yaml`·
`docs/architecture/solution_module_gap_review.md` §3 D3.

왜 지금인가: 2026-07-08 Phase 6b는 writer 0·reader 0이라 이 테이블을 연기했다(dead code 회피).
S4-11이 생성 writer(오프라인 템플릿 생성 CLI)·검증(게이트 3종)·coach 서빙 reader를 한
슬라이스로 세우므로 도입 전제가 충족된다.

스키마(전부 신설 — 기존 테이블 변경 0):
  - hint_id TEXT PK(결정론 `hint-{path}-s{order}-l{level}` — 재실행 멱등)
  - solution_path_id TEXT NOT NULL FK solution_paths ON DELETE CASCADE(파생물)
  - step_order INTEGER NOT NULL CHECK >= 1
  - problem_id UUID NOT NULL FK problem(서빙 조회 키)
  - level SMALLINT NOT NULL CHECK 1~3 — Level 4(전체 풀이)는 Hint 엔티티 밖 안전망
  - content TEXT NOT NULL · socratic_category TEXT(기존 6카테고리 값 — 신규 enum 0)
  - reveals_concept_names/step_flow/partial_computation BOOL NOT NULL default false
  - revealed_concept_ids JSONB NOT NULL default '[]' · reveal_score FLOAT NOT NULL CHECK 0~1
  - verified BOOL NOT NULL default false · gate_report JSONB NOT NULL default '{}'
  - generator_version TEXT NOT NULL · created_at/updated_at TIMESTAMPTZ NOT NULL default now()
  - UNIQUE(solution_path_id, step_order, level) · INDEX(problem_id, level, step_order)

PG enum 신설 없음(level은 CHECK, socratic_category는 TEXT) → downgrade는 drop_table 하나로 대칭.

Revision ID: 9d3e6b1f4a27
Revises: 8c19e8a611e4
Create Date: 2026-09-29 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9d3e6b1f4a27"
down_revision: str | None = "8c19e8a611e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hints",
        sa.Column("hint_id", sa.Text(), nullable=False),
        sa.Column("solution_path_id", sa.Text(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("problem_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("socratic_category", sa.Text(), nullable=True),
        sa.Column(
            "reveals_concept_names", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("reveals_step_flow", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "reveals_partial_computation",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "revealed_concept_ids",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("reveal_score", sa.Float(), nullable=False),
        sa.Column("verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "gate_report",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("generator_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # 이름은 ORM 명명 규약이 만드는 *최종* 이름을 op.f로 그대로 적는다(재접두 방지·ORM과 일치).
        sa.CheckConstraint("level BETWEEN 1 AND 3", name=op.f("ck_hints_level_graded_1_3")),
        sa.CheckConstraint(
            "reveal_score >= 0 AND reveal_score <= 1", name=op.f("ck_hints_reveal_score_unit")
        ),
        sa.CheckConstraint("step_order >= 1", name=op.f("ck_hints_step_order_positive")),
        sa.ForeignKeyConstraint(
            ["problem_id"],
            ["problem.problem_id"],
            name=op.f("fk_hints_problem_id_problem"),
        ),
        sa.ForeignKeyConstraint(
            ["solution_path_id"],
            ["solution_paths.solution_path_id"],
            name=op.f("fk_hints_solution_path_id_solution_paths"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("hint_id", name=op.f("pk_hints")),
        sa.UniqueConstraint(
            "solution_path_id", "step_order", "level", name=op.f("uq_hints_step_level")
        ),
    )
    op.create_index(
        "idx_hints_serving", "hints", ["problem_id", "level", "step_order"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_hints_serving", table_name="hints")
    op.drop_table("hints")
