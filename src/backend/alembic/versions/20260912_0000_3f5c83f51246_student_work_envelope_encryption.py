"""학생 답안·풀이 본문 봉투 암호화 컬럼 (SEC-31 — problem_attempt·answer_submission·
student_solution_step 3테이블 일괄).

PR #903 Codex P1 지적 → EOS-32 §4-6 "일괄 후속" 유보 해소. `dialogue_turn` 봉투 암호화
(SEC-01·c3d4e5f0a1b2/a2b3c4d5e6f1) 선례를 답안/풀이 계열 3테이블에 그대로 적용한다:

  - `problem_attempt`: student_answer·handwriting_uri·ocr_result
  - `answer_submission`: raw_response·latex·canonical_ast
  - `student_solution_step`: expression·canonical_ast

각 대상 컬럼에 `<컬럼>_encrypted`(LargeBinary)+`<컬럼>_nonce`(LargeBinary) 쌍을 추가한다(8쌍
16컬럼). 마스터 키(DB 밖·env — `student_work_encryption_key`)로 AES-256-GCM 암호화된 본문을
저장하면 DB dump만으로는 복호 불가(CLAUDE.md "학생 데이터는 민감 정보로 분류 — 암호화 저장"의
저장계층 시행). 키 미설정이면 평문 폴백(기존 동작 무영향·점진 도입 — `api/_crypto.py`).

**`student_solution_step.expression`을 nullable로 완화한다** — 생성 마이그레이션(EOS-46
a926d39f126a)이 `NOT NULL`로 만들었으나, 암호화 행에서는 평문 컬럼이 NULL이 되므로 제약을
완화해야 한다. **기존 행은 전부 값을 갖고 있어 안전**(NULL로 채워지는 신규 값이 없다 — 완화만
하고 백필 없음). 다른 7개 대상 컬럼은 생성 시점부터 이미 nullable이라 별도 완화가 불요하다
(dialogue_turn.content가 이미 nullable이었던 선례와 동형 — c3d4e5f0a1b2 참조).

3테이블을 **한 리비전에 일괄 적재**한다 — EOS-32 §4-6이 명문화한 "단일 테이블 선행 암호화는
보호 비대칭" 판정(부분 배선 = 이 태스크의 존재 이유 자체를 재생산)을 그대로 따른다.

downgrade: 16컬럼 drop + `student_solution_step.expression` NOT NULL 복원(왕복 안전 — 오프라인
`--sql` 검증만·실 PG 없음. SEC-27/29와 동일 제약. 복원 시점에 NULL 행이 있으면 실 DB에선
실패하나, 이 리비전 자체는 새 NULL 값을 만들지 않으므로 롤백 직후 상태에선 안전하다).

Revision ID: 3f5c83f51246
Revises: 4c6dfb1527a9
Create Date: 2026-09-12 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f5c83f51246"
down_revision: str | None = "4c6dfb1527a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── problem_attempt: student_answer·handwriting_uri·ocr_result ──
    op.add_column(
        "problem_attempt",
        sa.Column("student_answer_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "problem_attempt",
        sa.Column("student_answer_nonce", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "problem_attempt",
        sa.Column("handwriting_uri_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "problem_attempt",
        sa.Column("handwriting_uri_nonce", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "problem_attempt",
        sa.Column("ocr_result_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "problem_attempt",
        sa.Column("ocr_result_nonce", sa.LargeBinary(), nullable=True),
    )

    # ── answer_submission: raw_response·latex·canonical_ast ──
    op.add_column(
        "answer_submission",
        sa.Column("raw_response_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "answer_submission",
        sa.Column("raw_response_nonce", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "answer_submission",
        sa.Column("latex_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "answer_submission",
        sa.Column("latex_nonce", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "answer_submission",
        sa.Column("canonical_ast_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "answer_submission",
        sa.Column("canonical_ast_nonce", sa.LargeBinary(), nullable=True),
    )

    # ── student_solution_step: expression(NOT NULL → nullable 완화)·canonical_ast ──
    op.alter_column(
        "student_solution_step",
        "expression",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.add_column(
        "student_solution_step",
        sa.Column("expression_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "student_solution_step",
        sa.Column("expression_nonce", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "student_solution_step",
        sa.Column("canonical_ast_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "student_solution_step",
        sa.Column("canonical_ast_nonce", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("student_solution_step", "canonical_ast_nonce")
    op.drop_column("student_solution_step", "canonical_ast_encrypted")
    op.drop_column("student_solution_step", "expression_nonce")
    op.drop_column("student_solution_step", "expression_encrypted")
    op.alter_column(
        "student_solution_step",
        "expression",
        existing_type=sa.Text(),
        nullable=False,
    )

    op.drop_column("answer_submission", "canonical_ast_nonce")
    op.drop_column("answer_submission", "canonical_ast_encrypted")
    op.drop_column("answer_submission", "latex_nonce")
    op.drop_column("answer_submission", "latex_encrypted")
    op.drop_column("answer_submission", "raw_response_nonce")
    op.drop_column("answer_submission", "raw_response_encrypted")

    op.drop_column("problem_attempt", "ocr_result_nonce")
    op.drop_column("problem_attempt", "ocr_result_encrypted")
    op.drop_column("problem_attempt", "handwriting_uri_nonce")
    op.drop_column("problem_attempt", "handwriting_uri_encrypted")
    op.drop_column("problem_attempt", "student_answer_nonce")
    op.drop_column("problem_attempt", "student_answer_encrypted")
