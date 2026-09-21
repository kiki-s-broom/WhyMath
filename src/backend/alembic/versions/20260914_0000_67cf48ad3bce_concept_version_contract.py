"""concept_version 테이블 + PUBLISHED 불변성 트리거 (EOS-49)

`docs/architecture/44_eos_version_management.md` §6.2(VersionHeader)·§6.3(도메인별 버전
테이블)·§7(Lifecycle 상태 머신)의 ConceptVersion 계약을 영속화한다. 좌석 판정: `docs/
architecture/canonical_entity_model_v1.md` §3-D "판정 2026-09-06"(게이트
`G-eos49-content-version-seat` D안) — `concept_version`은 새 엔티티가 아니라 **Concept
좌석의 4번째 테이블**이다(`curriculum_version`이 Curriculum 좌석의 2번째 테이블인 선례와
동형). `ContentVersion`(범용 버전 슈퍼테이블) 좌석은 계속 비워 둔다.

이 리비전이 하는 일:
  ① `concept_version_status_enum`(6종: DRAFT/IN_REVIEW/APPROVED/PUBLISHED/DEPRECATED/
     RETIRED) + `concept_version` 테이블 생성. `concept_id`는 **`concept.code`(의미 ID)를
     참조**한다 — `concept.concept_id`(UUID 대리키)를 참조하지 **않는다**(Principle 1:
     Entity ID ≠ Version ID — `curriculum_version.framework_id → curriculum_framework.
     framework_id` 동일 패턴 선례). `previous_version_id`는 self-FK(버전 체인).
  ② `concept`에 nullable `current_published_version_id`(§6.4) 추가 — 비파괴(기존 행
     무영향, 기본값 없음). `899ae0efbb8b`(CUR-10) 선례 그대로 add_column 후
     op.create_foreign_key로 분리(제약명 결정성).
  ③ **PUBLISHED 불변성 BEFORE UPDATE 트리거**(§7 Lifecycle) — 두 규칙을 강제한다:
     (a) PUBLISHED 행의 `payload`는 UPDATE로 바꿀 수 없다(수정하려면 clone해 새 DRAFT
         버전을 만든다 — §7 원문).
     (b) PUBLISHED → DRAFT 전이 금지(§7 "이미 Published 버전을 다시 수정 불가 상태로
         되돌리지 않는다").
     트리거 함수는 slice 59/62(`whymath_cleanup_attempt_events`) 선례를 따르되, **사후
     하드닝이 아니라 최초 생성 시점부터** `SET search_path = pg_catalog, public`를 갖는다
     (이 리비전이 코드베이스의 두 번째 DB 함수 — b8c9d0e1f2a3 하드닝 교훈을 처음부터 반영).

concept_version.concept_id ↔ concept.current_published_version_id는 **상호 FK**(두 테이블이
서로를 가리킴)다 — §6.4 "Entity 상태와 Version 상태는 분리"의 자연스러운 결과이며(Problem ↔
ProblemVersion도 동형 설계, ARCH-31), 생성 순서(먼저 concept_version 테이블 → 그다음
concept 컬럼)와 downgrade 역순(먼저 concept 컬럼/FK 제거 → 그다음 concept_version 테이블)
으로 순환 없이 안전하게 왕복한다.

ARCH-31(ProblemVersion, 미착수)과의 비충돌: 이 리비전은 `concept`·`concept_version`만
건드린다 — `problem` 테이블·`ProblemVersion` 축에는 아무 것도 만들지 않는다.

Revision ID: 67cf48ad3bce
Revises: 3f5c83f51246
Create Date: 2026-09-14 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "67cf48ad3bce"
down_revision: str | None = "3f5c83f51246"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# concept_version_status_enum 라벨(VersionStatus 값과 일치 — 멤버명=값). 마이그레이션은
# 결정적이어야 하므로 ORM enum을 import하지 않고 정본 값을 박는다(solution_nodes_table.py
# 인라인 라벨 선례).
_STATUS_LABELS = (
    "DRAFT",
    "IN_REVIEW",
    "APPROVED",
    "PUBLISHED",
    "DEPRECATED",
    "RETIRED",
)

_TRIGGER_FUNCTION = "whymath_concept_version_immutability_guard"
_TRIGGER_NAME = "trg_concept_version_immutability_guard"


def upgrade() -> None:
    # ── ① concept_version 테이블(+ concept_version_status_enum, create_table이 자동 생성) ──
    op.create_table(
        "concept_version",
        sa.Column(
            "version_id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # 의미 ID(concept.code) 참조 — concept.concept_id(UUID 대리키)가 아니다(Principle 1).
        sa.Column("concept_id", sa.Text(), nullable=False),
        sa.Column(
            "entity_type",
            sa.String(length=50),
            server_default=sa.text("'Concept'"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*_STATUS_LABELS, name="concept_version_status_enum"),
            server_default="DRAFT",
            nullable=False,
        ),
        # self-FK — 버전 체인(직전 버전). 최초 버전은 NULL.
        sa.Column("previous_version_id", sa.Uuid(), nullable=True),
        sa.Column("change", JSONB(none_as_null=True), nullable=True),
        sa.Column("source", JSONB(none_as_null=True), nullable=True),
        sa.Column("governance", JSONB(none_as_null=True), nullable=True),
        sa.Column("integrity", JSONB(none_as_null=True), nullable=True),
        # payload — 이 버전 시점의 Concept 스냅숏(불변성 트리거 보호 대상).
        sa.Column("payload", JSONB(none_as_null=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["concept.code"],
            name=op.f("fk_concept_version_concept_id_concept"),
        ),
        sa.ForeignKeyConstraint(
            ["previous_version_id"],
            ["concept_version.version_id"],
            name=op.f("fk_concept_version_previous_version_id_concept_version"),
        ),
        sa.PrimaryKeyConstraint("version_id", name=op.f("pk_concept_version")),
        sa.UniqueConstraint(
            "concept_id",
            "version_no",
            name="uq_concept_version_concept_no",
        ),
    )
    # "현재 발행 버전 찾기" 조회 경로(concept_id + status='PUBLISHED') 지원.
    op.create_index(
        "idx_concept_version_concept_status",
        "concept_version",
        ["concept_id", "status"],
    )

    # ── ② concept.current_published_version_id(§6.4, nullable·비파괴) ──
    op.add_column(
        "concept",
        sa.Column("current_published_version_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_concept_current_published_version_id_concept_version"),
        "concept",
        "concept_version",
        ["current_published_version_id"],
        ["version_id"],
    )

    # ── ③ PUBLISHED 불변성 트리거(§7) — payload 불변 + PUBLISHED→DRAFT 금지 ──
    # search_path 하드닝을 최초 생성 시점부터 반영(slice 62 b8c9d0e1f2a3 교훈의 선반영).
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {_TRIGGER_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF OLD.status = 'PUBLISHED' THEN
                IF NEW.payload IS DISTINCT FROM OLD.payload THEN
                    RAISE EXCEPTION
                        'concept_version %: PUBLISHED payload is immutable (44 sec7)',
                        OLD.version_id;
                END IF;
                IF NEW.status = 'DRAFT' THEN
                    RAISE EXCEPTION
                        'concept_version %: PUBLISHED -> DRAFT is forbidden (44 sec7)',
                        OLD.version_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """)
    op.execute(f"""
        CREATE TRIGGER {_TRIGGER_NAME}
        BEFORE UPDATE ON concept_version
        FOR EACH ROW
        EXECUTE FUNCTION {_TRIGGER_FUNCTION}();
        """)


def downgrade() -> None:
    # ③ 트리거·함수 제거(테이블보다 먼저 — 순서 무관하나 대칭을 위해 먼저 정리).
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON concept_version;")
    op.execute(f"DROP FUNCTION IF EXISTS {_TRIGGER_FUNCTION}();")

    # ② concept.current_published_version_id 제거 — concept_version을 가리키는 FK부터.
    op.drop_constraint(
        op.f("fk_concept_current_published_version_id_concept_version"),
        "concept",
        type_="foreignkey",
    )
    op.drop_column("concept", "current_published_version_id")

    # ① concept_version 테이블 + enum 타입 제거.
    op.drop_index("idx_concept_version_concept_status", table_name="concept_version")
    op.drop_table("concept_version")
    # 네이티브 ENUM 타입 정리 — create_table이 자동 생성한 PG enum은 drop_table로 사라지지
    # 않으므로 명시 drop(안 떨구면 재-upgrade가 "type already exists"로 깨짐·checkfirst 멱등).
    postgresql.ENUM(name="concept_version_status_enum").drop(op.get_bind(), checkfirst=True)
