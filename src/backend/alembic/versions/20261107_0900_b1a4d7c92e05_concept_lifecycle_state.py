"""concept_content 생애 상태·출처 컬럼 + 상태 변경 기록 + 학생 노출 기록 (PED-17 A1)

C안(조건부 개방, 2026-11-06 Kiki 승인)의 바탕이 되는 영속 좌석이다. 개념이 초안·검증됨·공개됨·회수됨
중 어디에 있는지, 누가 언제 바꿨는지, 학생이 언제 보았는지를 남긴다.

이 리비전이 하는 일(**additive** — 기존 행을 지우거나 덮어쓰지 않는다):
  ① `concept_content`에 `lifecycle_status`(기본 '초안')·`content_origin`(기본 'AI 생성') 컬럼 추가 +
     어휘 CHECK 2개. 기본값이 '초안'이라 이 컬럼을 모르는 쓰기 경로(코퍼스 적재기 등)가 만든 새 행은
     학생에게 나가지 않는다(fail-closed).
  ② 상태 변경 기록 `concept_state_transition`(추가 전용 · UPDATE/DELETE/TRUNCATE를 트리거가 거부)과
     학생 노출 기록 `concept_exposure_event`(UPDATE만 트리거가 거부 · DELETE는 보존기한 파기를
     위해 허용).
  ③ **기존 행 상태 이월(백필)** — `review_status` 기준:
       reviewed  → 공개됨 + 출처 '사람 검수'   (지금 학생 경로가 이미 여는 행. 학생 화면 불변)
       rejected  → 회수됨 + 출처 'AI 생성'     (사람이 거부한 행. 재검증은 회수됨→초안 재생성을
       거친다)
       그 외      → 초안   + 출처 'AI 생성'     (기본값 그대로 · ai_estimated 포함)
     기본값이 아닌 행(공개됨·회수됨)에는 기록 테이블에 `via='최초 부여'` 행을 1건씩 남긴다. 출발
     상태가
     없으므로 `from_state`는 NULL이다(허용 전환 5쌍에 없는 가짜 이력을 만들지 않는다).
  ④ `concept_content.lifecycle_status` BEFORE UPDATE 트리거 — 허용 전환 5쌍 밖의 변경을 DB가
    거부한다.
     **백필(③) 뒤에 만든다.** 먼저 만들면 백필의 초안→공개됨 UPDATE가 스스로 걸린다.

**upgrade 순서가 계약이다**: 컬럼 → 기록 테이블 → 백필 → 트리거. 어느 단계에서 실패해도 PG의
트랜잭션
DDL이 전체를 되돌린다(이 리비전은 `ALTER TYPE ... ADD VALUE` 같은 트랜잭션 밖 DDL을 쓰지 않는다).

**downgrade 주의 — 기록이 사라진다**: 두 기록 테이블을 DROP하므로 그 안의 이력도 사라진다.
되돌리기 전에
`ped17/산출물/A1/마이그레이션_되돌리기.md`의 내보내기 단계를 먼저 실행한다. 두 컬럼을 DROP하므로
되돌린 뒤의
학생 경로는 `review_status`만 보던 옛 코드여야 한다(코드를 먼저 되돌리거나 함께 되돌린다).

Revision ID: b1a4d7c92e05
Revises: a8c4e1f7b3d9
Create Date: 2026-11-07 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1a4d7c92e05"
down_revision: str | None = "a8c4e1f7b3d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 어휘를 ORM에서 import하지 않고 인라인으로 박는다 — 마이그레이션은 결정적이어야 하고, 훗날 어휘가
# 바뀌어도
# 이 리비전이 만드는 제약은 그때의 값 그대로여야 한다(`learning_state_transition` 리비전 선례).
# 모델·`schema/concept_lifecycle.py`와 같은 값인지는 통합 테스트가 대조한다.
_STATE_VOCAB = "'초안', '검증됨', '공개됨', '회수됨'"
_VIA_VOCAB = (
    "'B6 공개 관문', 'D4 AI 카나리', 'D5 단계적 공개', 'D2 AI 감사', 'D6', "
    "'킬스위치', '회수 기능', '긴급 정지', '재생성', '최초 부여'"
)

_PAIR_FUNCTION = "whymath_concept_lifecycle_pair_guard"
_PAIR_TRIGGER = "trg_concept_content_lifecycle_pair_guard"
_APPEND_ONLY_FUNCTION = "whymath_concept_state_transition_append_only"
_APPEND_ONLY_ROW_TRIGGER = "trg_concept_state_transition_append_only_row"
_APPEND_ONLY_TRUNCATE_TRIGGER = "trg_concept_state_transition_append_only_truncate"
_EXPOSURE_FUNCTION = "whymath_concept_exposure_no_update"
_EXPOSURE_TRIGGER = "trg_concept_exposure_event_no_update"

_BACKFILL_ACTOR = "a1_migration_backfill"


def upgrade() -> None:
    # ① concept_content 컬럼 2개 + 어휘 CHECK. server_default가 기존 행에도 '초안'/'AI 생성'을
    #   채운다.
    op.add_column(
        "concept_content",
        sa.Column("lifecycle_status", sa.Text(), server_default=sa.text("'초안'"), nullable=False),
    )
    op.add_column(
        "concept_content",
        sa.Column("content_origin", sa.Text(), server_default=sa.text("'AI 생성'"), nullable=False),
    )
    op.create_check_constraint(
        "lifecycle_status",
        "concept_content",
        f"lifecycle_status IN ({_STATE_VOCAB})",
    )
    op.create_check_constraint(
        "content_origin",
        "concept_content",
        "content_origin IN ('사람 검수', 'AI 생성')",
    )

    # ② 상태 변경 기록 — 추가 전용 원장.
    op.create_table(
        "concept_state_transition",
        sa.Column(
            "transition_id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("concept_code", sa.Text(), nullable=False),
        sa.Column("from_state", sa.Text(), nullable=True),
        sa.Column("to_state", sa.Text(), nullable=False),
        sa.Column("changed_by_kind", sa.Text(), nullable=False),
        sa.Column("changed_by_name", sa.Text(), nullable=False),
        sa.Column("via", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("transition_id"),
        sa.CheckConstraint(
            f"from_state IS NULL OR from_state IN ({_STATE_VOCAB})",
            name="from_state",
        ),
        sa.CheckConstraint(f"to_state IN ({_STATE_VOCAB})", name="to_state"),
        sa.CheckConstraint(
            "changed_by_kind IN ('rule', 'agent', 'kiki')",
            name="changed_by_kind",
        ),
        sa.CheckConstraint(
            "length(btrim(changed_by_name)) > 0",
            name="changed_by_name",
        ),
        sa.CheckConstraint(f"via IN ({_VIA_VOCAB})", name="via"),
        sa.CheckConstraint(
            "(from_state IS NULL) = (via = '최초 부여')",
            name="initial_pair",
        ),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="reason"),
    )
    op.create_index(
        "ix_concept_state_transition_concept_changed",
        "concept_state_transition",
        ["concept_code", "changed_at"],
    )

    # 학생 노출 기록 — 이름·원본 user_id 미저장(키드 해시 64자만).
    op.create_table(
        "concept_exposure_event",
        sa.Column(
            "exposure_id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("concept_code", sa.Text(), nullable=False),
        sa.Column("student_pseudonym", sa.Text(), nullable=False),
        sa.Column(
            "exposed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ai_label_shown", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("exposure_id"),
        sa.CheckConstraint(
            "student_pseudonym ~ '^[0-9a-f]{64}$'",
            name="pseudonym_format",
        ),
    )
    op.create_index(
        "ix_concept_exposure_event_concept_exposed",
        "concept_exposure_event",
        ["concept_code", "exposed_at"],
    )

    # ③ 기존 행 상태 이월 — 트리거를 만들기 전에 해야 한다(초안→공개됨은 허용 전환이 아니다).
    # 기록 행은 UPDATE보다 먼저 남긴다: UPDATE 뒤에는 어떤 행이 이월 대상이었는지
    # review_status로만
    #    알 수 있어 같은 조건을 두 번 쓰게 되지만, 기록과 변경이 같은 트랜잭션이라 어긋나지 않는다.
    op.execute(f"""
        INSERT INTO concept_state_transition
            (concept_code, from_state, to_state, changed_by_kind, changed_by_name, via, reason)
        SELECT code, NULL, '공개됨', 'rule', '{_BACKFILL_ACTOR}', '최초 부여',
               'A1 이월: 사람 검수 완료(reviewed)로 이미 공개 중인 개념 → 공개됨'
        FROM concept_content
        WHERE review_status = 'reviewed'
        """)
    op.execute(f"""
        INSERT INTO concept_state_transition
            (concept_code, from_state, to_state, changed_by_kind, changed_by_name, via, reason)
        SELECT code, NULL, '회수됨', 'rule', '{_BACKFILL_ACTOR}', '최초 부여',
               'A1 이월: 사람이 거부(rejected)한 개념 → 회수됨, 재검증은 재생성 경유'
        FROM concept_content
        WHERE review_status = 'rejected'
        """)
    op.execute(
        "UPDATE concept_content SET lifecycle_status = '공개됨', content_origin = '사람 검수' "
        "WHERE review_status = 'reviewed'"
    )
    op.execute(
        "UPDATE concept_content SET lifecycle_status = '회수됨' WHERE review_status = 'rejected'"
    )

    # ④ 트리거 3종. 함수는 최초 생성부터 search_path를 고정한다(concept_version 리비전 선례).
    # 4-1) 허용 전환 5쌍 밖의 lifecycle_status 변경 거부.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {_PAIR_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF NOT (
                (OLD.lifecycle_status = '초안'   AND NEW.lifecycle_status = '검증됨') OR
                (OLD.lifecycle_status = '검증됨' AND NEW.lifecycle_status = '공개됨') OR
                (OLD.lifecycle_status = '공개됨' AND NEW.lifecycle_status = '회수됨') OR
                (OLD.lifecycle_status = '검증됨' AND NEW.lifecycle_status = '회수됨') OR
                (OLD.lifecycle_status = '회수됨' AND NEW.lifecycle_status = '초안')
            ) THEN
                RAISE EXCEPTION
                    'concept_content % : 허용되지 않은 상태 전환 % -> % (허용 5쌍 밖)',
                    OLD.code, OLD.lifecycle_status, NEW.lifecycle_status
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$;
        """)
    op.execute(f"""
        CREATE TRIGGER {_PAIR_TRIGGER}
        BEFORE UPDATE OF lifecycle_status ON concept_content
        FOR EACH ROW
        WHEN (OLD.lifecycle_status IS DISTINCT FROM NEW.lifecycle_status)
        EXECUTE FUNCTION {_PAIR_FUNCTION}();
        """)

    # 4-2) 상태 변경 기록 추가 전용 — 행 단위 UPDATE/DELETE + 문장 단위 TRUNCATE 거부.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {_APPEND_ONLY_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            RAISE EXCEPTION
                'concept_state_transition 은 추가 전용입니다 (% 거부)', TG_OP
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$;
        """)
    op.execute(f"""
        CREATE TRIGGER {_APPEND_ONLY_ROW_TRIGGER}
        BEFORE UPDATE OR DELETE ON concept_state_transition
        FOR EACH ROW
        EXECUTE FUNCTION {_APPEND_ONLY_FUNCTION}();
        """)
    op.execute(f"""
        CREATE TRIGGER {_APPEND_ONLY_TRUNCATE_TRIGGER}
        BEFORE TRUNCATE ON concept_state_transition
        FOR EACH STATEMENT
        EXECUTE FUNCTION {_APPEND_ONLY_FUNCTION}();
        """)

    # 4-3) 노출 기록 UPDATE 거부(DELETE는 보존기한 파기를 위해 허용).
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {_EXPOSURE_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            RAISE EXCEPTION
                'concept_exposure_event 는 수정할 수 없다 (라벨 표시 여부를 사후에 고칠 수 없다)'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$;
        """)
    op.execute(f"""
        CREATE TRIGGER {_EXPOSURE_TRIGGER}
        BEFORE UPDATE ON concept_exposure_event
        FOR EACH ROW
        EXECUTE FUNCTION {_EXPOSURE_FUNCTION}();
        """)


def downgrade() -> None:
    # 트리거 → 기록 테이블 → CHECK → 컬럼 순(생성의 역순). 컬럼 DROP은 그 컬럼에 걸린 트리거를 먼저
    # 지워야 한다. 기록 테이블 DROP은 append-only 트리거에 막히지 않는다(DROP은 UPDATE/DELETE가
    # 아니다).
    op.execute(f"DROP TRIGGER IF EXISTS {_PAIR_TRIGGER} ON concept_content;")
    op.execute(f"DROP FUNCTION IF EXISTS {_PAIR_FUNCTION}();")

    op.execute(f"DROP TRIGGER IF EXISTS {_EXPOSURE_TRIGGER} ON concept_exposure_event;")
    op.execute(f"DROP FUNCTION IF EXISTS {_EXPOSURE_FUNCTION}();")
    op.drop_index("ix_concept_exposure_event_concept_exposed", table_name="concept_exposure_event")
    op.drop_table("concept_exposure_event")

    op.execute(
        f"DROP TRIGGER IF EXISTS {_APPEND_ONLY_TRUNCATE_TRIGGER} ON concept_state_transition;"
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_APPEND_ONLY_ROW_TRIGGER} ON concept_state_transition;")
    op.execute(f"DROP FUNCTION IF EXISTS {_APPEND_ONLY_FUNCTION}();")
    op.drop_index(
        "ix_concept_state_transition_concept_changed", table_name="concept_state_transition"
    )
    op.drop_table("concept_state_transition")

    op.drop_constraint("content_origin", "concept_content", type_="check")
    op.drop_constraint("lifecycle_status", "concept_content", type_="check")
    op.drop_column("concept_content", "content_origin")
    op.drop_column("concept_content", "lifecycle_status")
