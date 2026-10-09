"""role_enum에 CMS 역할 3종 추가 — content_editor · content_reviewer · content_publisher (P3-12)

관리자 CMS(`api/admin_cms.py`)가 편집·검수·배포 권한을 역할로 나누는 좌석이다. 역할이 *무엇을 할 수
있는가*는 DB가 아니라 `schema/cms_access.py`의 권한 매핑 한 곳이 정한다 — 이 리비전은 어휘만 넓힌다.

이 리비전이 하는 일(**additive·비파괴** — 기존 행·writer·소비자 무영향):
  `role_enum`에 값 3개 추가(`IF NOT EXISTS`로 재실행 멱등). 기존 `student`·`content_admin` 행은
  그대로이고, 새 값을 가진 행은 `role_grant_cli grant`가 만들기 전까지 존재하지 않는다.

**enum ADD VALUE 안전성(PG 16)**: 같은 트랜잭션에서 값을 *추가*만 하고 *사용*하지 않으므로 안전하다
(선례 `9d3e7b1c5a20` IN_QA · `e7c3b9a15f24` quarantined).

upgrade: enum 값 3개 add(멱등).
downgrade: no-op. PG는 enum 값 제거를 지원하지 않아 관례대로 남긴다(무손상). 새 값을 가진
  사용자 행이 있는 상태에서 코드만 이전 판으로 돌리면 ORM이 그 행을 읽을 때 `LookupError`가
  나므로, 롤백하려면 먼저 `role_grant_cli revoke`로 해당 계정을 `student`로 되돌려야 한다.
  `20260730_1200_c5d6e7f0a2b3`(role 컬럼 최초 추가)까지 내려가면 그 downgrade가 타입 자체를
  drop하므로 잔존하지 않는다.

Revision ID: c5e9f3a7b1d4
Revises: c5e1f9a3b7d2
Create Date: 2026-10-08 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5e9f3a7b1d4"
down_revision: str | None = "c5e1f9a3b7d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 라벨은 `schema/enums.py` Role의 값과 글자 그대로 같아야 한다(회귀 테스트가 대조).
    # 문장을 변수 루프로 만들지 않고 그대로 적는다 — 프로브 계약 테스트(`tests/infra/
    # test_prod_schema_probe.py`)가 "이 타입에 이 라벨을 ADD VALUE하는 문장"을 정적으로 찾는다.
    op.execute("ALTER TYPE role_enum ADD VALUE IF NOT EXISTS 'content_editor'")
    op.execute("ALTER TYPE role_enum ADD VALUE IF NOT EXISTS 'content_reviewer'")
    op.execute("ALTER TYPE role_enum ADD VALUE IF NOT EXISTS 'content_publisher'")


def downgrade() -> None:
    # PG는 enum 값 제거 미지원 — 새 값은 남긴다(no-op·관례·데이터 무손상). 위 docstring 참조.
    pass
