"""misconception_hypothesis.deactivated_reason 추가 — 해소율 정직화 축 (MISC-20).

**왜 필요한가**: ⑩ 오개념 해소율은 `is_active=false` 비율인데, 저장소는 **감쇠(stale 정리)·
반박·해소·최대N 캡절단**을 전부 같은 `is_active=false`로 눌러 쓴다. 그래서 "학생이 실제로
오개념을 넘어섰다"와 "가설이 조용히 시들었다"가 구분되지 않는다(`harness/wh1_evaluation.py`의
`_misconception_resolution_from_counts`가 스스로 자백한 한계 · 오개념 R2 §2 G4). 이 컬럼이
서면 `RESOLVED`만 분자로 세는 정직한 해소율이 가능해지고, 그때 비로소 노출 재승격을 판정할 수
있다(04e §9-D4 · CLAUDE.md "작동 신호 없는 알고리즘 부착 금지").

컬럼(ORM 정본 `db/models/misconception_hypothesis.py`와 1:1):
  - `deactivated_reason` TEXT NULL — `l4.misconception.hypothesis.DeactivationReason` 값
    (`resolved` / `refuted` / `decayed` / `capped`).

**과거 행 백필 없음(정직 회계)**: 기존 비활성 행의 사유는 **복원 불가능한 정보**다. 특정 값으로
채우면 그 순간 날조가 되고, 하필 그 날조가 학생에게 "네가 극복한 비율"로 표시된다. nullable·
server_default 없음으로 두고 NULL(사유 미상)은 분자에서 제외한다(04e §9-D4 명시 · EOS-99
`generation_log` 캐시 축과 같은 방침).

CHECK 제약을 만들지 않는다 — 값 집합의 소유자는 애플리케이션 Enum이며, DB에 불변식을 위장하지
않는다(이 테이블의 기존 방침). 인덱스도 만들지 않는다 — 이 컬럼은 집계 재료이지 선별 질의
축이 아니고, 이미 `(user_id, is_active)` 인덱스가 접근 경로를 담당한다(조기 최적화 회피).

upgrade: nullable 1컬럼 add. downgrade: 역순 drop(완전 복원).

Revision ID: d2f4a68b91e7
Revises: c1a5e07b4d38
Create Date: 2026-09-07 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2f4a68b91e7"
down_revision: str | None = "c1a5e07b4d38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 비활성화 사유 축 — nullable·server_default 없음(구 행 NULL=사유 미상·소급 날조 금지).
    op.add_column(
        "misconception_hypothesis", sa.Column("deactivated_reason", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    # upgrade 역순 drop — 완전 복원(대칭).
    op.drop_column("misconception_hypothesis", "deactivated_reason")
