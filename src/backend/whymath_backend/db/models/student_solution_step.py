"""StudentSolutionStep 영속 ORM(`student_solution_step`) — 학생 풀이 step 정규 기록 (EOS-46).

설계 정본: `docs/architecture/adr/ADR-002-student-solution-step-entity.md` — attempt_event
event_type 확장(A) 대신 **별도 정규 엔티티(B)** 판정(hypertable 정본·실측 대조, enum ALTER
비용·경량 payload 계약 위반·FK 부재·행 정체성 부재로 A 기각·상세는 ADR). 검증 Pydantic
정본은 `schema/student_solution_step.py` — 본 모듈은 *영속 스키마*만 둔다(EOS-32/45 관례).

**명칭·책임 구분(혼동 금지 — ADR-002 3자 대조)**:
  - **이 테이블**: *학생*이 제출한 풀이 단계(미성년 PII 계열 — 오류 위치 학습·오개념 증거).
  - `solution_nodes`(`db/models/solution_node.py` `SolutionNode`): WH-S AI 솔버의 MCTS 탐색
    트리 노드 — *시스템 내부 상태*·학생 데이터 아님·API 노출 0. **이 테이블과 무관하다.**
  - `problem_step`(`ProblemStep`): 문항의 저작 정본 단계(콘텐츠) — 학생 제출물 아님.

**과거분 백필 불가(정직)**: 과거 step *내용*의 원천이 존재하지 않는다 —
`problem_attempt.step_times`는 단계별 *시간*만 담고, `attempt_event`의 `계산`·`그래프그리기`
등은 본문 없는 telemetry다. 재구성은 날조라 하지 않는다(32_learning_history §4 EOS-46 항).

영속 매핑 결정(근거 병기 — EOS-32/45 관례 재사용):
  - `student_step_id` UUID PK `gen_random_uuid()`.
  - `(attempt_id, user_id)` **NOT NULL 복합 FK → problem_attempt(attempt_id, user_id)
    ON DELETE CASCADE** — EOS-32 PR #902 P1 소유 정합 원칙(타인 attempt 조합 거부). 참조
    대상 UNIQUE `uq_problem_attempt_attempt_user`는 EOS-32 마이그레이션이 이미 생성 —
    **재사용**(중복 생성 금지·EOS-45 동형).
  - `user_id` UUID **NOT NULL FK user_profile.user_id**(복합 FK와 별도 — 계정 실재 강제·
    privacy 3종 균일 경로·NO ACTION).
  - `sequence_no` INTEGER NOT NULL + **UNIQUE(attempt_id, sequence_no)** — attempt 내 step
    제출 순번 유일(`answer_submission` 동형). 고쳐 낸 step은 새 순번의 새 행(append-only
    관행 — UPDATE로 이력을 지우지 않는다).
  - `expression` TEXT NOT NULL — 렌더러-중립 LaTeX 본문(표현≠의미: 본문은 LaTeX·구조는
    canonical_ast — CLAUDE.md 현행 정밀).
  - `canonical_ast`·`validation` JSONB nullable — `none_as_null=True`(SEC-06 전수 거버넌스).
    validation의 검증 권위는 **SymPy 단일 권위**(구조 계약 `StepValidation`·schema docstring).
  - `concept_ids` JSONB NOT NULL `server_default '[]'::jsonb` — UC 개념 id 목록(느슨참조 —
    `solution_paths.concept_sequence` 선례 그대로: list[str]·FK 없음·매칭 확정분만).
  - `submitted_at` TIMESTAMPTZ NOT NULL `server_default now()` — 보존 파기 축(NOT NULL이라
    NULL-미파기 잔존 없음).

인덱스: `(user_id, submitted_at DESC)` — privacy 경로(EOS-32/45 동형). attempt 단위 step
재구성(`WHERE attempt_id ORDER BY sequence_no`)은 UNIQUE(attempt_id, sequence_no) 선두
컬럼이 겸한다(`answer_submission` 동형).

개인정보 메모(CLAUDE.md·`answer_submission` 방침 동일): `expression`·`canonical_ast`는
*미성년 학생 풀이 데이터*다 — 암호화·동의는 저장·동의 계층 책임(ORM은 컬럼만·가짜 CHECK
없음). 봉투 암호화는 `student_answer` 계열과 일괄 판단(32 §4 EOS-32 항 ⑥). privacy 3종
배선은 acceptance가 강제·`test_erasure_plan_completeness`가 동결한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.schema.student_solution_step import (
    StudentSolutionStep as SchemaStudentSolutionStep,
)


class StudentSolutionStep(Base):
    """학생 풀이 step 영속 ORM — `student_solution_step`(attempt 내 step 제출 1건 1행).

    한 행 = attempt(`attempt_id`) 안에서 학생(`user_id`)이 `sequence_no`번째로 제출한 풀이
    단계다. **WH-S `SolutionNode`(MCTS 탐색 노드·시스템 데이터)와 무관하다**(ADR-002 명칭·
    책임 구분). 오개념 `evidence_links`가 "N번째 step의 오류"를 가리키는 안정 참조 대상이며,
    소비 로직은 이 모듈 범위 밖(저장소만 세운다 — writer 배선은 후속).
    """

    __tablename__ = "student_solution_step"

    # ===== 기본 식별 =====
    student_step_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    # attempt 참조는 (attempt_id, user_id) 복합 FK(__table_args__ — EOS-32 소유 정합 관례).
    attempt_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    # pseudonymous user_id 직접 보유 — privacy 3종 균일 경로. user_profile FK는 복합 FK와
    # 별도 유지(계정 실재 강제).
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("user_profile.user_id"), nullable=False
    )
    # attempt 내 step 제출 순번(1부터) — UNIQUE(attempt_id, sequence_no) 구성요소.
    sequence_no: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    # ===== step 본문 (*미성년 풀이 데이터* — 표현≠의미) =====
    # 렌더러-중립 LaTeX 본문(구조는 canonical_ast — CLAUDE.md 현행 정밀).
    # SEC-31: schema는 여전히 `str`(required·min_length=1) — 암호화 행에서는 이 컬럼이
    # NULL이 되므로 DB 제약을 nullable로 완화한다(마이그레이션 3f5c83f51246). 복호는
    # `resolve_student_solution_step_expression`이 둘 다 없으면 RuntimeError로 보장한다(schema
    # 계약의 "항상 문자열"은 handler/헬퍼 층이 지킨다 — dialogue_turn과 달리 이 필드는 NOT NULL
    # 계약이라 nullable content와 다른 특수 취급).
    expression: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # 봉투 암호화(AES-256-GCM) — 둘 다 NULL이면 평문(expression) 행. schema round-trip 제외
    # (`_NON_SCHEMA_COLUMNS`).
    expression_encrypted: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    expression_nonce: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    # SEC-06: none_as_null=True — "값 없음"은 SQL NULL(JSONB 스칼라 null 오계수 방지).
    canonical_ast: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # SEC-31: JSONB는 **결정론 직렬화 후**(sort_keys=True·ensure_ascii=False) 암호화
    # (dialogue_turn.image_analysis_encrypted 선례).
    canonical_ast_encrypted: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    canonical_ast_nonce: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)

    # ===== 검증·개념 태그 =====
    # 구조 계약 = schema StepValidation(SymPy 단일 권위 — 미검증=NULL·침묵 valid 위장 금지).
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # UC 개념 id 목록(느슨참조 — solution_paths.concept_sequence 선례·매칭 확정분만).
    concept_ids: Mapped[list[str]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")
    )

    # ===== 시간 (보존 파기 축 — NOT NULL이라 NULL-미파기 잔존 없음) =====
    submitted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    # ── 제약·인덱스 ──
    __table_args__ = (
        # EOS-32 소유 정합 관례 — "A의 attempt + B의 user_id" 조합을 DB가 거부. 참조 대상
        # UNIQUE(uq_problem_attempt_attempt_user)는 EOS-32가 이미 생성(재사용·중복 생성 금지).
        # attempt 삭제(GDPR) 시 자식 step 동반 제거(CASCADE)도 이 복합 FK가 담당.
        sa.ForeignKeyConstraint(
            ["attempt_id", "user_id"],
            ["problem_attempt.attempt_id", "problem_attempt.user_id"],
            name="fk_student_solution_step_attempt_owner",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "attempt_id", "sequence_no", name="uq_student_solution_step_attempt_seq"
        ),
        sa.Index("idx_student_solution_step_user", "user_id", sa.desc("submitted_at")),
    )

    # SEC-31: schema round-trip에서 제외하는 봉투 암호화 컬럼(schema는 extra="forbid"라 이 키가
    # model_validate에 들어가면 실패). 복호는 handler/헬퍼 층이 담당(dialogue_turn 동형).
    _NON_SCHEMA_COLUMNS = frozenset(
        {
            "expression_encrypted",
            "expression_nonce",
            "canonical_ast_encrypted",
            "canonical_ast_nonce",
        }
    )

    # ── 변환 헬퍼 (schema↔db seam, answer_submission.py 패턴) ────────────
    @classmethod
    def from_schema(cls, schema: SchemaStudentSolutionStep) -> StudentSolutionStep:
        """검증된 `schema.StudentSolutionStep` → 영속 ORM(mapper 컬럼키 필터).

        `validation` 서브모델은 `model_dump()`가 dict로 풀어 JSONB에 담긴다.
        `submitted_at=None`(schema 기본 — DB가 채움)은 kwargs에서 *제외*한다 — 명시적 None
        할당은 NULL INSERT가 되어 NOT NULL 위반(EOS-32/45 동형). 암호화 컬럼(expression_encrypted
        등)은 schema에 없어 여기서 설정되지 않는다 — handler/헬퍼 층이 expression을 암호화해
        채운다(schema의 `expression: str` 필수 계약은 여기선 항상 값이 있으므로 영향 없음).
        """
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        if kwargs.get("submitted_at") is None:
            kwargs.pop("submitted_at", None)  # server_default now() 적용(명시 NULL 금지)
        return cls(**kwargs)

    def to_schema(self) -> SchemaStudentSolutionStep:
        """영속 ORM → `schema.StudentSolutionStep`(Pydantic 검증 복원 — validation 재검증).

        JSONB dict는 `StepValidation`으로 재검증된다(구조 오염 시 ValidationError — 침묵
        통과 없음). 봉투 암호화 컬럼은 `_NON_SCHEMA_COLUMNS`로 제외(ciphertext 비노출).

        **주의**: 암호화 행은 `expression`(ORM상 nullable)이 NULL이지만 schema의 `expression`은
        필수 `str`이라 *이 메서드를 암호화 행에 직접 호출하면 ValidationError가 난다* — 호출자
        (`privacy/export.py`)가 `resolve_student_solution_step_expression`으로 복호한 평문을
        먼저 확보해 schema를 구성해야 한다(이 메서드를 그대로 쓰지 않음. 모듈 최상단 참조).
        """
        mapped_keys = {
            col.key
            for col in sa.inspect(type(self)).mapper.column_attrs
            if col.key not in self._NON_SCHEMA_COLUMNS
        }
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaStudentSolutionStep.model_validate(data)


__all__ = ["StudentSolutionStep"]
