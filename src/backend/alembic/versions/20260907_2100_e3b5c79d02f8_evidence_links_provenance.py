"""evidence_links.provenance 추가 — 해소 판정의 출처 축 (MISC-20 · Codex P1 수용).

**왜 필요한가**: 같은 PR이 도입한 "해소(RESOLVED)" 판정은 처음에 `polarity=-1 AND
coalesce(weight, 1.0) >= 0.75`로 *가중치에서 출처를 추론*했다. 그 추론은 두 곳에서 깨진다:

  1. `weight`는 **nullable**(미평가 None)인데 `coalesce(..., 1.0)`이 **NULL을 최강 신호로**
     접었다 — *모른다*가 *확정*이 되는 방향이라, CLAUDE.md "모른다 ≠ 아니다"의 정확히 반대다.
  2. WH-1 하네스의 `LogEvidenceAction.weight`는 **LLM이 지정**한다. 즉 LLM이 숫자 하나로
     "이 학생은 오개념을 넘어섰다"를 영구 기록하게 만들 수 있었다.

`weight`는 *강도*를 말할 뿐 **누가 무엇을 근거로 썼는지**를 말하지 못한다. 그래서 출처를
별도 컬럼으로 1급화한다 — 기계가 확인한 사실(`correct_form_present` 실측)만 값으로 남고,
모르는 경로는 NULL로 남아 해소율 분자에서 빠진다(정직 회계).

컬럼(ORM 정본 `db/models/evidence_link.py`와 1:1):
  - `provenance` TEXT NULL — 예: `correct_form_demonstrated`.

**구 행 NULL=출처 미상(정직)**: 기존 증거 행의 출처는 복원 불가능하다. 특정 값으로 채우면
그 순간 "학생이 넘어섰다"는 날조가 되고, 하필 그 날조가 해소율의 분자가 된다. 백필하지 않는다
(`misconception_hypothesis.deactivated_reason`·`generation_log` 캐시 축과 같은 방침).

CHECK 제약·인덱스를 만들지 않는다 — 값 집합의 소유자는 애플리케이션 상수이고, 이 컬럼은
집계 필터 재료다. 조회는 이미 `(student_id, misconception_id)` 축 인덱스를 탄다.

upgrade: nullable 1컬럼 add. downgrade: 역순 drop(완전 복원).

Revision ID: e3b5c79d02f8
Revises: d2f4a68b91e7
Create Date: 2026-09-07 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3b5c79d02f8"
down_revision: str | None = "d2f4a68b91e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 증거 출처 축 — nullable·server_default 없음(구 행 NULL=출처 미상·소급 날조 금지).
    op.add_column("evidence_links", sa.Column("provenance", sa.Text(), nullable=True))


def downgrade() -> None:
    # upgrade 역순 drop — 완전 복원(대칭).
    op.drop_column("evidence_links", "provenance")
