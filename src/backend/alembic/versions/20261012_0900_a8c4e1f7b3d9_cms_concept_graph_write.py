"""CMS 개념 그래프 쓰기 좌석 — 소유 표지 2종 + concept_version FK 해제 + 무결성 트리거 2종 (P3-26)

관리자 CMS가 개념을 **신규 제안**하고 관계(엣지)를 **쓰는** 길을 열기 위한 스키마 좌석이다. 규약
정본:
`docs/standards/cms_concept_graph_write_contract.md`, 코드 어휘:
`whymath_backend/db/cms_edit_marker.py`.

이 리비전이 하는 일:
  ① `concept`·`concept_edge`에 `cms_edited_at TIMESTAMPTZ NULL`을 더한다 — **CMS가 만든 행**의 소유
  표지.
     NULL = graph.json 적재가 소유한 행(대다수). server_default·백필 없음(기본값을 달면 PG가 기존 행
     전체를
     마이그레이션 시각으로 채워 "전 행을 CMS가 만들었다"는 날조가 되고, 그러면 삭제·적재 보호가
     거꾸로
     작동한다 — P3-25 `e7b2c4d8a1f6`와 같은 이유).
  ② `concept_version.concept_id → concept.code` FK를 **푼다**. 신규 개념의 초안·검토·승인은 아직
  살아있는
     `concept` 행이 없는 상태에서 일어나야 하는데(요구사항: 살아있는 행을 직접 만들지 않는다) FK가
     그것을
     막는다.
  ③ FK가 하던 일을 트리거 2종이 이어받는다(무결성이 약해지지 않는다는 DB 수준 증거):
       - `concept_version`에 PUBLISHED로 쓰는 INSERT/UPDATE는 살아있는 `concept` 행이 있어야만
       통과한다.
       - `concept`를 지우려 할 때 그 개념의 PUBLISHED 판이 있으면 거부한다(옛 FK는 *어떤* 판이든
       있으면
         막았다 — 새 규칙은 "발행본이 있는 개념은 삭제 거부"로 요구사항과 정확히 같다).
     두 함수 모두 최초 생성 시점부터 `SET search_path = pg_catalog, public`를 갖는다(보안 하드닝
     선례).

downgrade: 트리거·함수 제거 → FK 복원 → 컬럼 제거. **FK 복원은 고아 판(살아있는 개념 행이 없는
`concept_version`)이 있으면 PG가 거부한다** — 신규 개념 제안이 하나라도 남아 있으면 먼저
폐기·정리해야
한다(조용히 지우지 않는다: 이력 소실을 downgrade가 몰래 하지 않게).

Revision ID: a8c4e1f7b3d9
Revises: d6a2f8c4b1e7
Create Date: 2026-10-12 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8c4e1f7b3d9"
down_revision: str | None = "d6a2f8c4b1e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAME = "fk_concept_version_concept_id_concept"
_PUBLISH_FN = "whymath_concept_version_publish_requires_concept"
_PUBLISH_TRG = "trg_concept_version_publish_requires_concept"
_DELETE_FN = "whymath_concept_delete_refuses_published"
_DELETE_TRG = "trg_concept_delete_refuses_published"


def upgrade() -> None:
    # ① 소유 표지 — 테이블 이름은 리터럴로 적는다(프로브 계약 테스트가 정적으로 본다).
    op.add_column("concept", sa.Column("cms_edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "concept_edge", sa.Column("cms_edited_at", sa.DateTime(timezone=True), nullable=True)
    )

    # ② FK 해제 — 신규 개념 제안(아직 개념 행이 없는 판)을 담는다.
    op.drop_constraint(_FK_NAME, "concept_version", type_="foreignkey")

    # ③-a PUBLISHED 판은 살아있는 개념 행이 있어야만 쓸 수 있다.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {_PUBLISH_FN}() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF NEW.status = 'PUBLISHED' THEN
                IF NOT EXISTS (SELECT 1 FROM concept WHERE code = NEW.concept_id) THEN
                    RAISE EXCEPTION
                        'concept_version %: PUBLISHED requires a live concept row (code=%)',
                        NEW.version_id, NEW.concept_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """)
    op.execute(f"""
        CREATE TRIGGER {_PUBLISH_TRG}
        BEFORE INSERT OR UPDATE ON concept_version
        FOR EACH ROW
        EXECUTE FUNCTION {_PUBLISH_FN}();
        """)

    # ③-b 발행본이 있는 개념 행은 지울 수 없다.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {_DELETE_FN}() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM concept_version
                WHERE concept_id = OLD.code AND status = 'PUBLISHED'
            ) THEN
                RAISE EXCEPTION
                    'concept %: has a PUBLISHED version; deprecate it before deleting',
                    OLD.code;
            END IF;
            RETURN OLD;
        END;
        $$;
        """)
    op.execute(f"""
        CREATE TRIGGER {_DELETE_TRG}
        BEFORE DELETE ON concept
        FOR EACH ROW
        EXECUTE FUNCTION {_DELETE_FN}();
        """)


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_DELETE_TRG} ON concept;")
    op.execute(f"DROP FUNCTION IF EXISTS {_DELETE_FN}();")
    op.execute(f"DROP TRIGGER IF EXISTS {_PUBLISH_TRG} ON concept_version;")
    op.execute(f"DROP FUNCTION IF EXISTS {_PUBLISH_FN}();")
    # 고아 판이 있으면 PG가 여기서 거부한다 — 의도된 동작(위 docstring).
    op.create_foreign_key(_FK_NAME, "concept_version", "concept", ["concept_id"], ["code"])
    op.drop_column("concept_edge", "cms_edited_at")
    op.drop_column("concept", "cms_edited_at")
