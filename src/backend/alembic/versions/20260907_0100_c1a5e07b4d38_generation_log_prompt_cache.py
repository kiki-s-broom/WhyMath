"""generation_log 프롬프트 캐시 2종 추가 — 적중 계측 축 (EOS-99).

**왜 필요한가**: `settings.anthropic_prompt_caching`을 켜면 요청에 `cache_control`이
실리지만, **적중했는지는 응답 usage에만 있다.** 종전 genlog는 `input_tokens`·
`output_tokens`만 적재해 "캐싱을 켠 회차"와 "캐시가 실제로 작동한 회차"를 구분할 수
없었다 — 짧은 프리픽스는 최소 토큰 미만이라 조용히 무효가 되므로(silent no-op), 플래그가
켜진 채 0% 적중이 이어져도 아무 신호가 없다(CLAUDE.md "작동 신호 없는 알고리즘 부착 금지").

컬럼(ORM 정본 `db/models/provenance.py::GenerationLog`와 1:1):
  - `cache_read_input_tokens` INTEGER — 캐시에서 읽힌 프리픽스 토큰(적중분·약 0.1배 과금).
  - `cache_creation_input_tokens` INTEGER — 캐시에 쓰인 프리픽스 토큰(첫 회차·약 1.25배).

`input_tokens`와 **배타 관계**임에 주의한다(합산 아님) — Anthropic은 캐시 적중분을
`input_tokens`에서 빼고 별도로 센다. 따라서 프롬프트 총 토큰은 세 값의 합이고, 적중률의
분모도 그 합이다(`harness/anchor_round_ledger.prompt_cache_rates` 단일 원천).

**구 행 NULL=미기록(정직)**: 기존 generation_log 행은 캐시 축 없이 적재됐다 — 0으로
채우면 "읽었는데 적중 0"(실측)과 구분되지 않으므로 소급 날조하지 않는다. nullable·
server_default 없음(additive·data migration 0건 — run_id/EOS-55와 같은 방침).

인덱스는 만들지 않는다 — 이 두 컬럼은 회차 단위 **집계** 재료이지 선별 질의 축이 아니다
(`run_id`가 선별 축이며 그쪽에만 인덱스가 있다). 조기 최적화 회피.

upgrade: nullable 2컬럼 add. downgrade: 역순 drop(완전 복원).

Revision ID: c1a5e07b4d38
Revises: b8d3f6a91c24
Create Date: 2026-09-07 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1a5e07b4d38"
down_revision: str | None = "b8d3f6a91c24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 프롬프트 캐시 계측 축 — nullable·server_default 없음(구 행 NULL=미기록·소급 날조 금지).
    op.add_column(
        "generation_log", sa.Column("cache_read_input_tokens", sa.Integer(), nullable=True)
    )
    op.add_column(
        "generation_log", sa.Column("cache_creation_input_tokens", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    # upgrade 역순 drop — 완전 복원(대칭).
    op.drop_column("generation_log", "cache_creation_input_tokens")
    op.drop_column("generation_log", "cache_read_input_tokens")
