"""problem_version 테이블 + problem.problem_version_id + PUBLISHED 불변성 트리거 (ARCH-31)

`docs/architecture/44_eos_version_management.md` §6.2(VersionHeader)·§6.3(도메인별 버전
테이블)·§6.4(Entity의 현재 버전 포인터)·§7(Lifecycle 상태 머신)의 ProblemVersion 계약을
영속화한다. 좌석 판정: `docs/architecture/canonical_entity_model_v1.md` §3-D "판정 2026-09-06"
(게이트 `G-eos49-content-version-seat` D안) — `problem_version`은 새 엔티티가 아니라 **Problem
좌석의 3번째 테이블**이다(`concept_version`이 Concept 좌석의 4번째 테이블인 선례와 동형).
`ContentVersion`(범용 버전 슈퍼테이블) 좌석은 계속 비워 둔다. 설계 정본·`identity_id` 관계:
`docs/architecture/arch31_problem_version.md`.

이 리비전이 하는 일(**additive·비파괴** — 기존 `problem` 행·writer·소비자 무영향):
  ① `problem_version_status_enum`(7종: DRAFT/IN_REVIEW/IN_QA/APPROVED/PUBLISHED/DEPRECATED/
     RETIRED — `VersionStatus` 전량. concept 쪽이 6종으로 시작해 `9d3e7b1c5a20`이 IN_QA를 나중에
     끼워 넣었던 것과 달리 처음부터 7종이다) + `problem_version` 테이블 생성. `problem_id`는
     `problem.problem_id`(UUID PK)를 참조한다. `previous_version_id`는 self-FK(버전 체인).
     `qa` JSONB(게이트 통과 기록 좌석)도 처음부터 포함한다(nullable·default 없음).
  ② `problem`에 nullable `problem_version_id` 추가(§6.4 현재 서빙 기준 판 포인터) — 기본값 없음,
     **백필 없음**(NULL=버전 미부여. 기존 행에 판을 날조해 넣지 않는다 — DP-03 `event_uuid`·
     ARCH-32 `source_id` 규약). `67cf48ad3bce`(EOS-49)와 같이 add_column 후 op.create_foreign_key로
     분리한다(제약명 결정성).
  ③ **PUBLISHED 불변성 BEFORE UPDATE 트리거**(§7 Lifecycle) — 두 규칙:
     (a) PUBLISHED 행의 `payload`는 UPDATE로 바꿀 수 없다(수정하려면 clone해 새 DRAFT를 만든다).
     (b) PUBLISHED → DRAFT 전이 금지.
     트리거 함수는 최초 생성부터 `SET search_path = pg_catalog, public`를 갖는다.

problem_version.problem_id ↔ problem.problem_version_id는 **상호 FK**다. 생성 순서(먼저
problem_version 테이블 → 그다음 problem 컬럼)와 downgrade 역순(먼저 problem 컬럼/FK 제거 → 그다음
problem_version 테이블)으로 순환 없이 안전하게 왕복한다(`concept` ↔ `concept_version` 동형).

downgrade: 트리거·함수 → problem 컬럼/FK → 인덱스·테이블 → enum 타입 순으로 대칭 제거한다.

Revision ID: c5e1f9a3b7d2
Revises: b4d8e2a6c0f3
Create Date: 2026-10-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5e1f9a3b7d2"
down_revision: str | None = "b4d8e2a6c0f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# problem_version_status_enum 라벨(VersionStatus 값과 일치 — 멤버명=값). 마이그레이션은 결정적이어야
# 하므로 ORM enum을 import하지 않고 정본 값을 박는다(`67cf48ad3bce` 선례). 순서는 enum 선언 순서.
_STATUS_LABELS = (
    "DRAFT",
    "IN_REVIEW",
    "IN_QA",
    "APPROVED",
    "PUBLISHED",
    "DEPRECATED",
    "RETIRED",
)

_TRIGGER_FUNCTION = "whymath_problem_version_immutability_guard"
_TRIGGER_NAME = "trg_problem_version_immutability_guard"


def upgrade() -> None:
    # ── ① problem_version 테이블(+ problem_version_status_enum, create_table이 자동 생성) ──
    op.create_table(
        "problem_version",
        sa.Column(
            "version_id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("problem_id", sa.Uuid(), nullable=False),
        sa.Column(
            "entity_type",
            sa.String(length=50),
            server_default=sa.text("'Problem'"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*_STATUS_LABELS, name="problem_version_status_enum"),
            server_default="DRAFT",
            nullable=False,
        ),
        # self-FK — 버전 체인(직전 버전). 최초 버전은 NULL.
        sa.Column("previous_version_id", sa.Uuid(), nullable=True),
        sa.Column("change", JSONB(none_as_null=True), nullable=True),
        sa.Column("source", JSONB(none_as_null=True), nullable=True),
        sa.Column("governance", JSONB(none_as_null=True), nullable=True),
        sa.Column("integrity", JSONB(none_as_null=True), nullable=True),
        # 게이트 통과 기록 좌석 — NULL = 기록 없음(가짜 기록 날조 방지).
        sa.Column("qa", JSONB(none_as_null=True), nullable=True),
        # payload — 이 버전 시점의 Problem 스냅숏(불변성 트리거 보호 대상).
        sa.Column("payload", JSONB(none_as_null=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["problem_id"],
            ["problem.problem_id"],
            name=op.f("fk_problem_version_problem_id_problem"),
        ),
        sa.ForeignKeyConstraint(
            ["previous_version_id"],
            ["problem_version.version_id"],
            name=op.f("fk_problem_version_previous_version_id_problem_version"),
        ),
        sa.PrimaryKeyConstraint("version_id", name=op.f("pk_problem_version")),
        sa.UniqueConstraint(
            "problem_id",
            "version_no",
            name="uq_problem_version_problem_no",
        ),
    )
    # "현재 발행 버전 찾기" 조회 경로(problem_id + status='PUBLISHED') 지원.
    op.create_index(
        "idx_problem_version_problem_status",
        "problem_version",
        ["problem_id", "status"],
    )

    # ── ② problem.problem_version_id(§6.4, nullable·비파괴·백필 없음) ──
    op.add_column(
        "problem",
        sa.Column("problem_version_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_problem_problem_version_id_problem_version"),
        "problem",
        "problem_version",
        ["problem_version_id"],
        ["version_id"],
    )

    # ── ③ PUBLISHED 불변성 트리거(§7) — payload 불변 + PUBLISHED→DRAFT 금지 ──
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {_TRIGGER_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF OLD.status = 'PUBLISHED' THEN
                IF NEW.payload IS DISTINCT FROM OLD.payload THEN
                    RAISE EXCEPTION
                        'problem_version %: PUBLISHED payload is immutable (44 sec7)',
                        OLD.version_id;
                END IF;
                IF NEW.status = 'DRAFT' THEN
                    RAISE EXCEPTION
                        'problem_version %: PUBLISHED -> DRAFT is forbidden (44 sec7)',
                        OLD.version_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """)
    op.execute(f"""
        CREATE TRIGGER {_TRIGGER_NAME}
        BEFORE UPDATE ON problem_version
        FOR EACH ROW
        EXECUTE FUNCTION {_TRIGGER_FUNCTION}();
        """)


def downgrade() -> None:
    # ③ 트리거·함수 제거.
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON problem_version;")
    op.execute(f"DROP FUNCTION IF EXISTS {_TRIGGER_FUNCTION}();")

    # ② problem.problem_version_id 제거 — problem_version을 가리키는 FK부터.
    op.drop_constraint(
        op.f("fk_problem_problem_version_id_problem_version"),
        "problem",
        type_="foreignkey",
    )
    op.drop_column("problem", "problem_version_id")

    # ① problem_version 테이블 + enum 타입 제거.
    op.drop_index("idx_problem_version_problem_status", table_name="problem_version")
    op.drop_table("problem_version")
    # 네이티브 ENUM 타입 정리 — drop_table로 사라지지 않으므로 명시 drop(안 떨구면 재-upgrade가
    # "type already exists"로 깨짐·checkfirst 멱등).
    postgresql.ENUM(name="problem_version_status_enum").drop(op.get_bind(), checkfirst=True)
