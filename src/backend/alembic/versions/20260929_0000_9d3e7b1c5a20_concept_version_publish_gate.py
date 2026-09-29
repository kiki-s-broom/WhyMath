"""concept_version_status_enum에 'IN_QA' 추가 + concept_version.qa 게이트 기록 좌석 (EOS-50)

`docs/architecture/44_eos_version_management.md` §9(Publish Gate & QA 연계)의 영속 좌석.
축 판정: `docs/reviews/eos50_publish_gate_axis_judgment_2026-09-29.md`.

이 리비전이 하는 일(**additive·비파괴** — 기존 행·writer·소비자 무영향):
  ① `concept_version_status_enum`에 `IN_QA` 1종 추가(`IN_REVIEW` 뒤). P3-11 ⑨가 요구한
     "Review → QA → Approved" 순서를 상태로 표현한다. 허용 전이는 DB가 아니라 전이표
     (`schema/version_lifecycle.py`)가 정한다 — 이 리비전은 어휘만 넓힌다.
  ② `concept_version.qa` JSONB nullable 추가 — §9 "각 버전은 QA 결과를 연결한다"
     (`qa_status`·`qa_run_id`·`validator_bundle_version` + 게이트 통과 이력). 기존 행은 NULL
     = "게이트 기록 없음"이며 기본값을 달지 않는다(가짜 기록 날조 방지 — EOS-48/57/71 규약).

EOS-49 트리거(`whymath_concept_version_immutability_guard`)는 손대지 않는다. 트리거는 OLD가
PUBLISHED일 때 payload 변경과 →DRAFT만 막으므로, 게이트가 PUBLISHED 행의 `qa`·`status`
(→DEPRECATED/RETIRED)를 쓰는 것은 그대로 허용된다.

**enum ADD VALUE 안전성(PG 16)**: 같은 트랜잭션에서 값을 *추가*만 하고 *사용*하지 않으므로
안전하다(선례 `e7c3b9a15f24` quarantined). `IF NOT EXISTS`로 재실행 멱등.

upgrade: enum 값 1개 add(멱등) + 컬럼 1개 add(nullable·default 없음).
downgrade: 컬럼 drop(대칭). enum 값은 PG가 제거를 지원하지 않아 관례대로 남긴다(no-op·무손상).
  단 `67cf48ad3bce`(EOS-49)까지 내려가면 그 downgrade가 타입 자체를 drop하므로 잔존하지 않는다.

Revision ID: 9d3e7b1c5a20
Revises: 8c19e8a611e4
Create Date: 2026-09-29 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9d3e7b1c5a20"
down_revision: str | None = "8c19e8a611e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ① 상태 어휘 1종 추가(멱등·같은 트랜잭션에서 사용하지 않으므로 안전).
    op.execute(
        "ALTER TYPE concept_version_status_enum ADD VALUE IF NOT EXISTS 'IN_QA' AFTER 'IN_REVIEW'"
    )
    # ② 게이트 통과 기록 좌석 — nullable·기본값 없음(NULL = 기록 없음).
    op.add_column(
        "concept_version",
        sa.Column("qa", JSONB(none_as_null=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("concept_version", "qa")
    # PG는 enum 값 제거 미지원 — 'IN_QA'는 남긴다(no-op·관례·데이터 무손상).
