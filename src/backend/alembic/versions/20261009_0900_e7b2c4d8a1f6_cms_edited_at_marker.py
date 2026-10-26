"""CMS 편집 표지 — cms_edited_at 컬럼 5종 추가 (P3-25)

관리자 CMS의 제자리 편집이 다음 CLI 적재(`populate`)에 소실되지 않게 하는 좌석이다. 사람이
CMS로 고친 행에 시각을 남기고, 적재는 그 표지가 있는 행을 건너뛰어 충돌로 보고한다
(`ON CONFLICT DO UPDATE ... WHERE cms_edited_at IS NULL`). 규약 정본:
`docs/standards/cms_edit_vs_loader_contract.md`, 코드 어휘: `whymath_backend/db/cms_edit_marker.py`.

대상 5종(CLI 적재가 같은 행을 upsert하는 것이 실측된 테이블 — 계약 문서 §2): `problem` ·
`misconception_catalog` · `strategy_node` · `concept_content` · `hints`. `problem_step`(적재 upsert
없음)·`curriculum_version`(alembic 시드만)에는 두지 않는다.

이 리비전이 하는 일(**additive·비파괴** — 기존 행·writer·소비자 무영향):
  5개 테이블에 `cms_edited_at TIMESTAMPTZ NULL`을 더한다. **server_default도 백필도 두지 않는다**
  (NULL = "사람이 고친 적 없음"이 정직한 상태 — 기본값을 달면 PG가 기존 행 전체를 마이그레이션
  시각으로 백필해 "전 행을 사람이 고쳤다"는 날조가 되고, 그러면 다음 적재가 전부 막힌다. 선례:
  `problem.quarantined_at`의 server_default 금지 판단).

upgrade: 컬럼 5개 add.
downgrade: 컬럼 5개 drop. 표지가 비워지므로 이후 적재는 다시 CMS 편집을 덮어쓸 수 있다.

Revision ID: e7b2c4d8a1f6
Revises: c5e9f3a7b1d4
Create Date: 2026-10-09 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b2c4d8a1f6"
down_revision: str | None = "c5e9f3a7b1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 테이블 이름은 리터럴로 적는다 — 프로브 계약 테스트(`tests/infra/test_prod_schema_probe.py`)가
    # "이 리비전 파일에 판별 테이블 이름이 따옴표로 등장하는가"를 정적으로 본다.
    op.add_column("problem", sa.Column("cms_edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "misconception_catalog",
        sa.Column("cms_edited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "strategy_node", sa.Column("cms_edited_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "concept_content", sa.Column("cms_edited_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("hints", sa.Column("cms_edited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("hints", "cms_edited_at")
    op.drop_column("concept_content", "cms_edited_at")
    op.drop_column("strategy_node", "cms_edited_at")
    op.drop_column("misconception_catalog", "cms_edited_at")
    op.drop_column("problem", "cms_edited_at")
