"""AnswerSubmission 영속 ORM(`answer_submission`) — attempt 내 다회 제출 시퀀스 정규화 (EOS-32).

설계 정본: `docs/architecture/32_learning_history.md` §4("AnswerSubmission 분리의 근거")·§11.
`problem_attempt.student_answer`는 최종값 1개만 담아 중간 제출(오답 → 오답 → 정답)의 오개념
신호가 손실된다 — 이 테이블이 제출 시퀀스를 1급 데이터로 영속한다(오개념 시스템 `evidence_links`
의 핵심 입력). 검증 Pydantic 정본은 `schema/answer_submission.py` — 본 모듈은 *영속 스키마*만
두고 `from_schema`/`to_schema` seam이 둘을 잇는다(`dialogue.py`·`activity.py` 동일 패턴).

**과거분 백필 불가(정직)**: `attempt_event`의 `답입력` payload(`ResponseLatencyEventData`)는
응답 본문·채점 결과를 담지 않는 지연 신호라 과거 제출 시퀀스를 이벤트에서 재구성하면 *날조*다.
시퀀스 수집은 이 엔티티 배포 시점부터 시작한다(이관·병행 전략 = 32_learning_history §4).

영속 매핑 결정(근거 병기):
  - `submission_id` UUID PK `gen_random_uuid()` — 배치1 UUID PK 선례.
  - `(attempt_id, user_id)` **NOT NULL 복합 FK → problem_attempt(attempt_id, user_id)
    ON DELETE CASCADE** (PR #902 P1 정정) — attempt FK와 user FK를 독립으로 두면 "A의 attempt +
    B의 user_id" 조합 INSERT가 통과해, `user_id`만으로 선별하는 export/erasure에 타인 풀이·채점
    데이터가 섞인다(소유 불일치). 복합 FK가 그 조합을 DB 수준에서 거부한다 — 참조 대상 UNIQUE
    `(attempt_id, user_id)`는 `problem_attempt`에 추가(attempt_id PK라 논리 중복이나 복합 FK
    참조 대상으로 필요 — PG 표준 패턴). attempt 삭제(GDPR) 시 자식 제출 동반 제거는 유지
    (slice 56 `dialogue_turn`→`dialogue` CASCADE 선례와 동형). 부수 강제(정직 명시):
    `problem_attempt.user_id`가 NULL인 attempt는 (attempt_id, user_id) 쌍이 실재하지 않아
    제출을 못 단다 — 소유자 미상 attempt에 제출을 다는 것 자체가 소유 불일치이므로 의도된
    강제다(신규 수집 경로는 항상 인증 학생 컨텍스트).
  - `user_id` UUID **NOT NULL FK user_profile.user_id**(복합 FK와 별도 유지) — pseudonymous
    user_id만(PII 직접 컬럼 금지·§11.5). 직접 보유가 privacy 3종 배선(삭제권 user 단위 delete·
    반출 user 단위 select)의 균일 경로를 만든다(`attempt_event.user_id` 동거 선례). CASCADE
    없음 — `problem_attempt.user_id`와 동형(NO ACTION — 삭제권은 앱레벨 `_ERASURE_PLAN`이
    자식 우선 명시 삭제).
  - `sequence_no` INTEGER NOT NULL + **UNIQUE(attempt_id, sequence_no)** — attempt 내 제출 순번
    유일(1부터). `dialogue_turn` `UNIQUE(dialogue_id, turn_order)` 선례와 동형(명명 제약은
    `misconception_hypothesis` `uq_*` 선례).
  - `response_type` String(32) NOT NULL — 폐쇄 4종(latex/text/choice/handwriting)은 schema
    Literal·`to_schema` 재검증이 강제(DB는 값만 담는다 — `misconception_relation.relation_type`
    선례·PG enum 신설 안 함).
  - `raw_response`·`latex` TEXT nullable — 제출 원문·수식 정규 LaTeX(*미성년 풀이 데이터* — 아래
    개인정보 메모).
  - `canonical_ast`·`grading_result`·`error_analysis` JSONB nullable — 전부
    `none_as_null=True`(SEC-06 전수 거버넌스 — Python None을 JSONB 스칼라 null로 저장 금지·
    `test_jsonb_none_as_null_governance.py` 동결). 구조 계약은 schema의
    GradingResult/ErrorAnalysis(suspected_misconception_ids는 kebab-case 카탈로그 id 느슨참조 —
    `evidence_link.misconception_id` 동형·FK 아님).
  - `submitted_at` TIMESTAMPTZ NOT NULL `server_default now()` — 보존 파기(`_RETENTION_PLAN`)의
    타임스탬프 축(NOT NULL이라 NULL-미파기 잔존 없음).

인덱스: `(user_id, submitted_at DESC)` — 삭제권/반출/보존 파기·학생 단위 최근순 조회
(`idx_attempt_user` 접근 패턴 동형). attempt 단위 조회는 UNIQUE(attempt_id, sequence_no)가
선두 컬럼 인덱스로 겸한다.

개인정보 메모(CLAUDE.md 절대 금기·개인정보보호법 — `activity.py` 방침과 동일):
  `raw_response`·`latex`·`canonical_ast`는 *미성년 학생 풀이 데이터*다. 평문 저장 금지·동의 없는
  학습 사용 금지는 *저장·동의 계층*(암호화·미들웨어·검수) 책임이며, ORM에는 컬럼만 두고 가짜
  CHECK를 만들지 않는다(`problem_attempt.student_answer` 동형 — 문서화만). 봉투 암호화 컬럼
  (§11.4 "적용 검토")은 `student_answer`와 동일 계층이라 함께 일괄 판단한다(32_learning_history
  §4 이관·병행 전략에 명문화 — 이 테이블만 선행 암호화하면 같은 데이터가 두 계층에서 다른 보호를
  받는 비대칭이 생긴다). privacy 3종 배선(erasure·retention·export)은 acceptance가 강제·
  `test_erasure_plan_completeness`가 동결한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.schema.answer_submission import AnswerSubmission as SchemaAnswerSubmission


class AnswerSubmission(Base):
    """답 제출 영속 ORM — `answer_submission`(attempt 내 다회 제출 시퀀스의 정규 기록).

    한 행 = 한 attempt(`attempt_id`) 안의 `sequence_no`번째 제출(1부터·UNIQUE 제약으로 attempt
    내 유일). `problem_attempt.student_answer`(최종값)와 병행 기록되며 시퀀스의 정본은 이
    테이블이다. 오개념 시스템(`evidence_links`)이 `error_analysis.suspected_misconception_ids`
    를 1급 입력으로 소비한다(소비 로직은 이 모듈 범위 밖 — 저장소만 세운다).
    """

    __tablename__ = "answer_submission"

    # ===== 기본 식별 =====
    submission_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    # attempt 참조는 단독 FK가 아니라 (attempt_id, user_id) *복합 FK*(__table_args__ — PR #902
    # P1: 타인 attempt에 제출을 다는 소유 불일치 조합을 DB가 거부).
    attempt_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    # pseudonymous user_id 직접 보유 — privacy 3종 배선의 균일 경로(모듈 docstring 근거).
    # user_profile FK는 복합 FK와 별도 유지(계정 실재 강제).
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("user_profile.user_id"), nullable=False
    )
    # attempt 내 제출 순번(1부터) — UNIQUE(attempt_id, sequence_no) 구성요소.
    sequence_no: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    # ===== 응답 본문 (*미성년 풀이 데이터* — 모듈 docstring 개인정보 메모) =====
    # 폐쇄 4종 강제는 schema Literal(latex/text/choice/handwriting) — DB는 String 좌석만.
    response_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    raw_response: Mapped[str | None] = mapped_column(sa.Text)
    # SEC-31: at-rest 봉투 암호화(AES-256-GCM) — dialogue_turn.content_encrypted 선례 미러.
    # 둘 다 NULL이면 평문(raw_response) 행. schema round-trip 제외(`_NON_SCHEMA_COLUMNS`).
    raw_response_encrypted: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    raw_response_nonce: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    latex: Mapped[str | None] = mapped_column(sa.Text)
    latex_encrypted: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    latex_nonce: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    # SEC-06: none_as_null=True — "값 없음"은 SQL NULL(JSONB 스칼라 null 오계수 방지).
    canonical_ast: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # SEC-31: JSONB는 **결정론 직렬화 후**(sort_keys=True·ensure_ascii=False) 암호화
    # (dialogue_turn.image_analysis_encrypted 선례).
    canonical_ast_encrypted: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    canonical_ast_nonce: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)

    # ===== 채점·오류 분석 (구조 계약 = schema GradingResult/ErrorAnalysis) =====
    grading_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # suspected_misconception_ids(kebab-case 느슨참조)를 내부에 담는 좌석 — evidence_links 입력.
    error_analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    # ===== 시간 (보존 파기 축 — NOT NULL이라 NULL-미파기 잔존 없음) =====
    submitted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    # ── 제약·인덱스 ──
    __table_args__ = (
        # PR #902 P1: attempt·user 소유 일치의 DB 강제 — (attempt_id, user_id) 쌍이 실재하는
        # problem_attempt 행과 일치해야 INSERT된다("A의 attempt + B의 user_id" 조합 거부).
        # attempt 삭제(GDPR) 시 자식 제출 동반 제거(CASCADE)는 이 복합 FK가 담당.
        sa.ForeignKeyConstraint(
            ["attempt_id", "user_id"],
            ["problem_attempt.attempt_id", "problem_attempt.user_id"],
            name="fk_answer_submission_attempt_owner",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("attempt_id", "sequence_no", name="uq_answer_submission_attempt_seq"),
        sa.Index("idx_answer_submission_user", "user_id", sa.desc("submitted_at")),
    )

    # SEC-31: schema round-trip에서 제외하는 봉투 암호화 컬럼(schema는 extra="forbid"라 이 키가
    # model_validate에 들어가면 실패). 복호는 handler/헬퍼 층이 담당(dialogue_turn 동형).
    _NON_SCHEMA_COLUMNS = frozenset(
        {
            "raw_response_encrypted",
            "raw_response_nonce",
            "latex_encrypted",
            "latex_nonce",
            "canonical_ast_encrypted",
            "canonical_ast_nonce",
        }
    )

    # ── 변환 헬퍼 (schema↔db seam, dialogue.py 패턴) ──────────────────────
    @classmethod
    def from_schema(cls, schema: SchemaAnswerSubmission) -> AnswerSubmission:
        """검증된 `schema.AnswerSubmission` → 영속 ORM(mapper 컬럼키 필터).

        `grading_result`/`error_analysis` 서브모델은 `model_dump()`가 dict로 풀어 JSONB에
        그대로 담긴다. `submitted_at=None`(schema 기본 — DB가 채움)은 kwargs에서 *제외*한다 —
        명시적 None 할당은 SQLAlchemy가 NULL을 INSERT해 NOT NULL 위반이 되고, 속성 미설정이어야
        `server_default now()`가 적용된다. 암호화 컬럼(raw_response_encrypted 등)은 schema에
        없어 여기서 설정되지 않는다 — handler/헬퍼 층이 raw_response 등을 암호화해 채운다.
        """
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        if kwargs.get("submitted_at") is None:
            kwargs.pop("submitted_at", None)  # server_default now() 적용(명시 NULL 금지)
        return cls(**kwargs)

    def to_schema(self) -> SchemaAnswerSubmission:
        """영속 ORM → `schema.AnswerSubmission`(Pydantic 검증 복원 — response_type 재검증).

        JSONB dict는 GradingResult/ErrorAnalysis 서브모델로 재검증된다(구조 오염 시
        ValidationError — 침묵 통과 없음). 봉투 암호화 컬럼은 `_NON_SCHEMA_COLUMNS`로 제외
        (ciphertext 비노출) — 암호화 행은 raw_response 등이 NULL이므로 handler/헬퍼 층
        (`privacy/export.py`)이 복호값을 덮어쓴다.
        """
        mapped_keys = {
            col.key
            for col in sa.inspect(type(self)).mapper.column_attrs
            if col.key not in self._NON_SCHEMA_COLUMNS
        }
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaAnswerSubmission.model_validate(data)


__all__ = ["AnswerSubmission"]
