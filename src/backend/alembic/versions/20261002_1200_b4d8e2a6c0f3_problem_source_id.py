"""problem.source_id — 주 출처 엔티티 FK 좌석 (ARCH-32).

011_1 EOS Identity 결정이 "`source_type`/`source_detail` → 별도 source 테이블로 점진 이관"을
명했다. 그런데 출처 테이블은 이미 LIC-01(a1b2c3d4e5f6)이 `source_entity`(+`content_source`
N:M)로 만들어 두었다 — 새 `source` 테이블을 또 만들면 같은 사실의 두 번째 좌석이 된다. 그래서
이 리비전은 **테이블을 만들지 않고** `problem`이 그 `source_entity`를 가리킬 FK 한 컬럼만 더한다.

nullable·server_default 없음(백필 금지): 기존 행에 출처 엔티티를 날조해 채우면 "원본에서 그렇게
등록된 적 없는 출처"를 만드는 것이다 — NULL=미이관이 정직하다(DP-03 `event_uuid` 규약). 채우는
일은 별도 이관 단계가 맡는다(docs/architecture/arch32_source_entity_migration.md §4).
`source_type`·`source_detail`은 그대로 둔다(저작권 불변식의 근거·소비처 다수 — 같은 문서 §3).

upgrade: 컬럼 1개 add(nullable, FK → source_entity.source_id) + 조회 인덱스 1개.
downgrade: 인덱스 drop + 컬럼 drop(FK는 컬럼과 함께 사라진다 — 대칭).

Revision ID: b4d8e2a6c0f3
Revises: a3f7c9d1e5b2
Create Date: 2026-10-02 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4d8e2a6c0f3"
down_revision: str | None = "a3f7c9d1e5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "idx_problem_source_id"
_FK = "fk_problem_source_id_source_entity"


def upgrade() -> None:
    op.add_column("problem", sa.Column("source_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(_FK, "problem", "source_entity", ["source_id"], ["source_id"])
    op.create_index(_INDEX, "problem", ["source_id"])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="problem")
    op.drop_constraint(_FK, "problem", type_="foreignkey")
    op.drop_column("problem", "source_id")
