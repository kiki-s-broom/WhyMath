"""generation_log.run_id 추가 — 리콜 조인 축 (EOS-97).

**왜 필요한가**: `GenerationLog`는 EOS-55/EOS-73으로 재현 재료(프롬프트 전문 스냅샷·해시·
모델·시드)를 강하게 갖췄으나 **어느 회차에 속한 호출인지**를 말하지 못했다. `run_id`는
`AccumulateReport`·`ReviewQueueEntry`에만 있어 GenerationLog와 조인할 축이 아니었고,
그래서 결함을 발견해도 *"이 배치로 만든 산출물만 골라 처분"* 이 기계로 불가능했다
(설계서 §3 리콜 시나리오가 짚은 실제 공백 — 갭 리뷰 §6 G-2).

컬럼(ORM 정본 `db/models/provenance.py::GenerationLog`와 1:1):
  - `run_id` VARCHAR(64) — 생성 회차 식별자. 회차 시작 시 호출자가 정하고 JSONL append
    시 스탬프된다. 회차 개념이 없는 경로(pregenerate 단발 인제스트)는 NULL=미기록.

**구 행 NULL=미기록(정직)**: 기존 generation_log 행은 회차 축 없이 적재됐다 — 값을 소급
날조하지 않는다. nullable·server_default 없음(additive·data migration 0건 — EOS-55 재현
좌석 5컬럼과 같은 방침).

인덱스 `idx_generation_run_id`: 리콜의 주 질의가 회차 단위 선별이라 함께 만든다. 부분
인덱스로 좁히지 않는다 — NULL 행이 대부분인 현시점에도 전체 인덱스가 단순하고, 회차 축이
쌓이면 그대로 이득이다(조기 최적화 회피).

upgrade: nullable 1컬럼 add + 인덱스. downgrade: 역순 drop(완전 복원).

Revision ID: b8d3f6a91c24
Revises: e7c3b9a15f24
Create Date: 2026-09-06 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d3f6a91c24"
down_revision: str | None = "e7c3b9a15f24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 리콜 조인 축 — nullable·server_default 없음(구 행 NULL=미기록·소급 날조 금지).
    op.add_column("generation_log", sa.Column("run_id", sa.String(length=64), nullable=True))
    op.create_index("idx_generation_run_id", "generation_log", ["run_id"])


def downgrade() -> None:
    # upgrade 역순 drop — 완전 복원(대칭).
    op.drop_index("idx_generation_run_id", table_name="generation_log")
    op.drop_column("generation_log", "run_id")
