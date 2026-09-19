"""도메인1 Problem ORM 모델 (SQLAlchemy 2.0 영속 레이어).

설계 정본: `schemas/v1.0/schema_v1.0.md` §3.1(`problem`)·§3.2(`problem_step`·
`problem_relation`)·§14.3(ENUM). 이 ORM은 `schema/problem.py`(Pydantic, 검증·API)와
*별도*로 세운 영속 매핑이다(SQLModel 미사용 — 사용자 결정). schema가 단일 진실(검증)을
맡고, 이 db ORM이 영속을 맡으며 `from_schema`/`to_schema` 변환 헬퍼가 둘을 잇는다.

ENUM 매핑 규칙(중요):
  `schema/enums.py`의 기존 str-Enum을 *재사용*한다. `sa.Enum(..., values_callable=...)`로
  매핑하되 `values_callable=lambda e: [m.value for m in e]`를 *반드시* 둔다 — 멤버명≠값인
  enum(예: `Curriculum.REVISION_2015 = "2015_REVISION"`)이 있어, 이게 없으면 SQLAlchemy가
  PostgreSQL enum을 *멤버명*('REVISION_2015')으로 만들어 §14.3 DDL 값('2015_REVISION')과
  어긋난다. PG 타입명은 §3.1/§14.3 DDL의 `*_enum`명을 그대로 박는다(`name=`). 이 매핑
  헬퍼(`_pg_enum`/`_enum_values`)는 6개 도메인 ORM이 공유하도록 `_orm_enum.py`로 추출했다.

타입 매핑(DDL → ORM):
  - `UUID PK` → `Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True,
    server_default=sa.text("gen_random_uuid()"))` (DDL `gen_random_uuid()` 정합 — PG16
    내장 함수, pgcrypto 확장 불요).
  - `JSONB` → `mapped_column(JSONB)` (자유형 dict·`conditions_parsed`·`persona_fit` 등).
  - `TEXT[]` → `mapped_column(ARRAY(sa.Text))`; `*_enum[]` → `ARRAY(sa.Enum(...))`.
  - `DECIMAL(p,s)` → `Mapped[float] = mapped_column(sa.Numeric(p, s))`.
  - `TIMESTAMPTZ` → `mapped_column(sa.DateTime(timezone=True))`; `VARCHAR(n)` →
    `sa.String(n)`; nullable은 `Mapped[X | None]`.
  - 인덱스(§3.1 `CREATE INDEX`, GIN 포함) → `__table_args__`(GIN은 `postgresql_using="gin"`).

본문 미보유 불변식(법적): 평가원/EBS/교과서는 본문 필드(question_text·answer_explanation·
choices)가 비어야 한다는 *교정 불변식*은 `schema.Problem`(Pydantic) `@model_validator`가
이미 강제한다. ORM에는 컬럼만 두고 가짜 DB CHECK를 만들지 않는다 — 이 invariant의 책임은
schema.Problem이다(영속 직전 변환 헬퍼가 schema를 거치므로 자연히 시행된다).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.db.models._orm_enum import _pg_enum
from whymath_backend.db.models._schema_seam import drop_unset_nulls
from whymath_backend.schema.enums import (
    AnswerFormat,
    BloomLevel,
    Curriculum,
    ExamType,
    QuestionFormat,
    RelationType,
    ReviewStatus,
    ScoringType,
    SignaturePattern,
    SourceType,
    StepType,
    Subject,
    VisualType,
)
from whymath_backend.schema.problem import Problem as SchemaProblem
from whymath_backend.schema.problem import ProblemRelation as SchemaProblemRelation
from whymath_backend.schema.problem import ProblemStep as SchemaProblemStep


# ──────────────────────────────────────────────────────────────────────────
# 핵심: Problem (§3.1 problem 테이블 — 50+ 컬럼)
# ──────────────────────────────────────────────────────────────────────────
class Problem(Base):
    """단일 문제 영속 ORM — §3.1 `problem` 테이블. WhyMath 최중요 단일 테이블.

    본문 미보유 불변식(평가원/EBS/교과서)은 `schema.Problem`(Pydantic) 책임이다 — 이
    ORM에는 본문 컬럼만 두고 DB CHECK를 만들지 않는다(모듈 docstring 참조).

    DDL은 `question_text`·`answer`가 `NOT NULL`이지만, 본문 미보유 출처의 *메타 전용*
    레코드를 표현하려면 비어 있을 수 있어야 하므로 ORM에서도 nullable로 둔다(schema의
    Optional 완화와 정합 — schema.Problem docstring 참조).
    """

    __tablename__ = "problem"

    # ===== 기본 식별 =====
    problem_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    external_id: Mapped[str | None] = mapped_column(sa.String(64), unique=True)
    slug: Mapped[str | None] = mapped_column(sa.String(128), unique=True)
    # 변형 계열 식별자(S4-18) — problem_id는 개체마다 불변, identity_id로 "같은 문제의
    # 다른 표현" 계열(원본+rephrase 등)만 묶는다. FK 아님(자기 자신을 포함한 계열의 공유값).
    identity_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, index=True)

    # ===== 출처 =====
    source_type: Mapped[SourceType] = mapped_column(
        _pg_enum(SourceType, "source_type_enum"),
        nullable=False,
    )
    source_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    # ===== 시험 컨텍스트 =====
    exam_type: Mapped[ExamType | None] = mapped_column(_pg_enum(ExamType, "exam_type_enum"))
    exam_year: Mapped[int | None] = mapped_column(sa.Integer)
    exam_month: Mapped[int | None] = mapped_column(sa.Integer)
    problem_number: Mapped[int | None] = mapped_column(sa.Integer)
    exam_authority_weight: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))

    # ===== 교육과정 버전 =====
    # 문항 본질 속성·제거 금지(오등록 상환 2026-07-02) — L6 학교진도 게이트 ③(2015/2022
    # 혼입 방지)의 정합 기준. 개념 노드와 달리 Overlay 이관 대상 아님(`Curriculum` docstring).
    curriculum_version: Mapped[Curriculum] = mapped_column(
        _pg_enum(Curriculum, "curriculum_enum"),
        nullable=False,
    )
    valid_from_year: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    valid_to_year: Mapped[int | None] = mapped_column(sa.Integer)

    # ===== 과목·단원 =====
    subject: Mapped[Subject] = mapped_column(_pg_enum(Subject, "subject_enum"), nullable=False)
    # P3a 신규: 광역 영역 코드(subject보다 세분·topic보다 광역). nullable·점진 채움.
    domain: Mapped[str | None] = mapped_column(sa.String(64))
    unit_codes: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), nullable=False)
    # P3a 신규: 소단원명(사람이 읽는 이름). unit_codes(코드 배열)와 다른 축.
    subunit: Mapped[str | None] = mapped_column(sa.String(128))

    # ===== 문항 형식 =====
    question_format: Mapped[QuestionFormat | None] = mapped_column(
        _pg_enum(QuestionFormat, "question_format_enum")
    )
    points: Mapped[int | None] = mapped_column(sa.Integer)
    answer_format: Mapped[AnswerFormat | None] = mapped_column(
        _pg_enum(AnswerFormat, "answer_format_enum")
    )
    # P3a 신규: Bloom 인지 수준·채점 유형(신규 PG enum 타입 — 마이그레이션이 CREATE TYPE).
    bloom_level: Mapped[BloomLevel | None] = mapped_column(_pg_enum(BloomLevel, "bloom_level_enum"))
    scoring_type: Mapped[ScoringType | None] = mapped_column(
        _pg_enum(ScoringType, "scoring_type_enum")
    )
    answer_constraint: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    answer_transform: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    # ===== 본문·풀이·정답 (본문 미보유 불변식은 schema.Problem 책임) =====
    question_text: Mapped[str | None] = mapped_column(sa.Text)
    question_text_md: Mapped[str | None] = mapped_column(sa.Text)
    question_image_uri: Mapped[str | None] = mapped_column(sa.Text)
    # DDL은 choices가 JSONB(보기 5개) — schema는 list[str]이라 변환 헬퍼에서 list↔JSONB.
    choices: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True))
    answer: Mapped[str | None] = mapped_column(sa.Text)
    answer_explanation: Mapped[str | None] = mapped_column(sa.Text)
    multiple_answers: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # P3b 신규: 객관식 오답 선지→오개념 매핑(rich list). schema는 list[DistractorEntry] —
    # model_dump()로 list[dict]가 되어 JSONB. nullable(server_default 없음 — source_detail·
    # multiple_answers와 동형, visualizations의 NOT NULL '[]' 패턴과 달리 *없음*을 NULL로 표현해
    # schema의 `distractor_map: ... | None = None`과 정합). 참조 무결성은 L4 검증자 소관.
    distractor_map: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB(none_as_null=True))

    # ===== 한국 시그니처 패턴 (enum 배열) =====
    signature_patterns: Mapped[list[SignaturePattern]] = mapped_column(
        ARRAY(_pg_enum(SignaturePattern, "signature_pattern_enum")),
        nullable=False,
        server_default=sa.text("'{}'::signature_pattern_enum[]"),
    )

    # ===== 발문 구조 =====
    has_condition_list: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    condition_count: Mapped[int | None] = mapped_column(sa.Integer)
    # conditions_parsed: schema는 list[Condition] — model_dump()로 list[dict]가 되어 JSONB.
    conditions_parsed: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")
    )

    # ===== 시각자료 =====
    has_visual: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    visual_type: Mapped[list[VisualType]] = mapped_column(
        ARRAY(_pg_enum(VisualType, "visual_type_enum")),
        nullable=False,
        server_default=sa.text("'{}'::visual_type_enum[]"),
    )
    visual_complexity: Mapped[int | None] = mapped_column(sa.Integer)
    # visualizations: schema는 list[Visualization] — model_dump()로 list[dict]가 되어 JSONB.
    visualizations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")
    )

    # ===== 다차원 난이도 (5축) =====
    difficulty_overall: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    diff_calculation: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    diff_interpretation: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    diff_case_analysis: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    diff_visual: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    diff_integration: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))

    # IRT 보정 난이도 b(logit) — JMLE(`l2.fit_jmle`)가 응답 데이터로 적합한 문항 난이도.
    # NULL=미보정 → θ 추정은 `difficulty_overall` 휴리스틱(`difficulty_to_logit`)으로 폴백.
    # logit 척도(전문가 1~5 라벨과 다름).
    irt_difficulty_b: Mapped[float | None] = mapped_column(sa.Float)
    # P3a 신규: IRT 2PL 변별 모수 a(slope) — 1PL b 보완(2PL 확장 시). NULL=미적합. Float·logit.
    irt_a: Mapped[float | None] = mapped_column(sa.Float)
    # P3a 신규: 고전 변별도 D(상위/하위 정답률 차) — irt_a(IRT 모수)와 다른 축(경험 통계). Float.
    # 필드명 대문자 D는 변별도 지수 D 정본 표기 보존(schema.Problem 동일·iPhone noqa 선례).
    discrimination_D: Mapped[float | None] = mapped_column(sa.Float)  # noqa: N815

    # ===== 정답률·통계 =====
    historical_correct_rate: Mapped[float | None] = mapped_column(sa.Numeric(5, 4))
    rate_top_grade: Mapped[float | None] = mapped_column(sa.Numeric(5, 4))
    rate_mid_grade: Mapped[float | None] = mapped_column(sa.Numeric(5, 4))
    rate_low_grade: Mapped[float | None] = mapped_column(sa.Numeric(5, 4))

    # ===== 시간 예상치 =====
    expected_solve_seconds: Mapped[int | None] = mapped_column(sa.Integer)
    expected_solve_seconds_p90: Mapped[int | None] = mapped_column(sa.Integer)
    # P3a 신규: 세션 내 권장 출제 순서(0부터·NULL=비배치)·피드백 템플릿 느슨참조(FK 아님).
    session_position: Mapped[int | None] = mapped_column(sa.Integer)
    feedback_id: Mapped[str | None] = mapped_column(sa.String(64))

    # ===== 페르소나 적합도 (JSONB — schema는 dict[Persona, float]) =====
    persona_fit: Mapped[dict[str, float] | None] = mapped_column(JSONB(none_as_null=True))

    # ===== EBS 연계 =====
    ebs_linked: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    ebs_source: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    # ===== 단원 융합 (JSONB — schema는 list[list[str]]) =====
    is_cross_unit: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    cross_unit_pairs: Mapped[list[list[str]]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")
    )

    # ===== 그래프 개형 추론 =====
    requires_graph_sketch: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    sketch_step_count: Mapped[int | None] = mapped_column(sa.Integer)

    # ===== 라벨링 (TEXT[]) =====
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )
    keywords: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )

    # ===== 사용자 노출 정책 =====
    is_premium: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    is_published: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    publish_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    # ===== 운영 메타 =====
    created_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    review_status: Mapped[ReviewStatus | None] = mapped_column(
        _pg_enum(ReviewStatus, "review_status_enum")
    )
    review_score: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))

    # ===== 운영 격리 (EOS-71 — review_status=quarantined의 근거 기록) =====
    # 격리 = *삭제가 아닌 회수*. 레코드도 딸린 problem_attempt도 보존하고 노출만 끊는다
    # (계약 정본 `docs/standards/problem_quarantine_contract.md` §2 비파괴 원칙).
    #
    # **server_default를 달지 않는 이유(날조 방지)**: `quarantined_at`에 `DEFAULT now()`를 달면
    # PG가 ALTER 시점에 기존 행 전체를 마이그레이션 시각으로 백필한다 — 그 순간 "격리된 적 없음"과
    # "이 시각에 격리됨"이 같은 값이 되어 격리 이력이 통째로 날조된다. NULL=미격리가 정직한
    # 상태이며 관리자 PATCH가 격리 시점에 채운다(`activity.py` `ingested_at`·`attempt_event.
    # skill_ids` 규약과 동형).
    #
    # **CHECK 제약을 두지 않는 이유**: "quarantined면 사유·시각 NOT NULL"은 매력적이지만 기존
    # 행·중간 상태(상태를 먼저 바꾸고 사유를 뒤에 쓰는 트랜잭션)와 충돌한다. 가짜 DB CHECK를 만들지
    # 않는다는 이 모듈 docstring의 판단(본문 미보유 불변식 처리)과 같은 이유로, 기록 의무는 계약
    # 문서 §3의 절차로 둔다.
    quarantine_reason: Mapped[str | None] = mapped_column(sa.Text)
    quarantined_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    # ── 인덱스 (§3.1 CREATE INDEX — GIN 4종 포함) ──
    __table_args__ = (
        sa.Index("idx_problem_exam", "exam_type", "exam_year", "exam_month"),
        sa.Index("idx_problem_subject_unit", "subject", "unit_codes"),
        sa.Index("idx_problem_signature", "signature_patterns", postgresql_using="gin"),
        sa.Index("idx_problem_difficulty", "difficulty_overall"),
        sa.Index("idx_problem_persona_fit", "persona_fit", postgresql_using="gin"),
        sa.Index("idx_problem_curriculum", "curriculum_version", "valid_from_year"),
        sa.Index("idx_problem_tags", "tags", postgresql_using="gin"),
        sa.Index("idx_problem_keywords", "keywords", postgresql_using="gin"),
    )

    # ── 변환 헬퍼 (schema↔db 레이어 연결 seam) ──────────────────────────
    @classmethod
    def from_schema(cls, schema: SchemaProblem) -> Problem:
        """검증된 `schema.Problem`(Pydantic) → 영속 ORM `Problem`.

        schema(검증)↔db(영속) 레이어를 잇는 seam이다. `model_dump()`로 평탄한 dict를
        얻으면 JSONB 대상 필드(`conditions_parsed`: list[Condition], `persona_fit`:
        dict[Persona, float], `cross_unit_pairs`: list[list[str]] 등)가 자동으로
        list[dict]/dict로 직렬화되어 그대로 매핑된다(`use_enum_values=True`라 enum 값은
        문자열로 떨어진다 — sa.Enum이 그 값을 받아 PG enum 라벨로 저장).

        본문 미보유 불변식은 schema.Problem이 *이미* 통과시켰으므로(유효한 인스턴스만
        여기 들어옴) ORM에서 재검증하지 않는다. ORM 매핑 컬럼명만 추려 생성자에 넘긴다.
        """
        data = schema.model_dump()
        # ORM이 매핑한 컬럼명만 전달(schema와 컬럼명이 1:1이라 키 필터 불필요하나, 방어적으로
        # mapper가 아는 키만 추린다 — 향후 schema에 ORM 비매핑 필드가 생겨도 안전).
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaProblem:
        """영속 ORM `Problem` → `schema.Problem`(Pydantic)로 복원(검증 포함).

        ORM 컬럼 값을 schema.Problem으로 되돌린다. JSONB의 list[dict](conditions_parsed)는
        schema.Condition으로, dict(persona_fit)는 dict[Persona, float]로 Pydantic이 다시
        검증·역직렬화한다. 이때 본문 미보유 불변식도 재차 통과한다(영속 데이터가 규칙을
        만족하는지의 안전망). `model_validate`에 ORM 객체를 직접 넘기지 않고 명시 dict를
        구성한다 — ORM은 `extra` 필드(관계 등)가 있을 수 있어 `extra="forbid"`인 schema와
        충돌할 수 있기 때문이다(매핑 컬럼만 추려 깨끗한 dict로 전달).
        """
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaProblem.model_validate(
            drop_unset_nulls(data, SchemaProblem, orm_cls=type(self))
        )


# ──────────────────────────────────────────────────────────────────────────
# 보조: ProblemStep (§3.2 problem_step)
# ──────────────────────────────────────────────────────────────────────────
class ProblemStep(Base):
    """문항 풀이 단계 영속 ORM — §3.2 `problem_step`(Socratic 코칭).

    `UNIQUE(problem_id, step_order)` — 한 문제 안에서 step_order 유일(DDL 제약).

    S4-09(D1) additive 컬럼: SolutionPath 실체화의 *단계 영속 좌석*을 겸한다(단계 전용 테이블
    신설 대신 — 테이블 증식 최소화). 전부 nullable additive라 기존 행·기존 API 응답과 호환
    파괴 0. `UNIQUE(problem_id, step_order)`는 불변 유지 — 한 문제에 *한 경로*의 단계만
    실체화 가능하다(다중 경로 단계 영속은 제약 재론과 함께 S4-10 몫·승격 어댑터가 초과분을
    스킵·리포트).
    """

    __tablename__ = "problem_step"

    step_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    problem_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("problem.problem_id")
    )
    step_order: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    step_type: Mapped[StepType | None] = mapped_column(_pg_enum(StepType, "step_type_enum"))
    step_title: Mapped[str | None] = mapped_column(sa.String(200))
    socratic_prompt: Mapped[str | None] = mapped_column(sa.Text)
    expected_answer: Mapped[str | None] = mapped_column(sa.Text)
    common_mistakes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")
    )

    # ===== S4-09(D1) additive — SolutionPath 단계 실체화 좌석(전부 nullable·비파괴) =====
    # 소속 풀이 경로(solution_paths FK). NULL=경로 미소속(레거시 Socratic 단계 하위호환).
    solution_path_id: Mapped[str | None] = mapped_column(
        sa.Text, sa.ForeignKey("solution_paths.solution_path_id")
    )
    # 이 단계가 통과하는 L1 개념 노드 ID. NULL=매칭 검수 대기(사람 검수 큐 — l3 Pydantic 경계).
    concept_node_id: Mapped[str | None] = mapped_column(sa.Text)
    # 스텝 추론 유형 — 폐쇄 7종 강제는 schema/enums.py ReasoningType(Pydantic)·DB는 TEXT 좌석만
    # (PG enum 신설 안 함 — approach_type과 동일 방침·`_pg_enum` 추가 없이 additive 유지).
    reasoning_type: Mapped[str | None] = mapped_column(sa.Text)
    # 정당화 근거 참조(얇은 3종 묶음·l3 Justification 직렬화). NULL=근거 미명시(하위호환).
    justification: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # 흔한 오류(list[str] — 오개념 카탈로그 코드/패턴 서술). 기존 common_mistakes(자유형 dict
    # 리스트)와 별개 축: yaml SolutionStep.common_errors의 1:1 좌석. NULL=미기록.
    common_errors: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True))
    # SymPy 검증 통과 여부(WH-S 승계 시 *직전 스텝→이 스텝 전이* Tier2 correct). NULL=미판정.
    sympy_verified: Mapped[bool | None] = mapped_column(sa.Boolean)

    __table_args__ = (sa.UniqueConstraint("problem_id", "step_order"),)

    @classmethod
    def from_schema(cls, schema: SchemaProblemStep) -> ProblemStep:
        """검증된 `schema.ProblemStep` → 영속 ORM(schema↔db seam)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaProblemStep:
        """영속 ORM → `schema.ProblemStep`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaProblemStep.model_validate(
            drop_unset_nulls(data, SchemaProblemStep, orm_cls=type(self))
        )


# ──────────────────────────────────────────────────────────────────────────
# 보조: ProblemRelation (§3.2 problem_relation)
# ──────────────────────────────────────────────────────────────────────────
class ProblemRelation(Base):
    """문항 간 관계 영속 ORM — §3.2 `problem_relation`(전형성·유사도).

    복합 PK `(parent_problem_id, related_problem_id, relation_type)` — DDL 제약. 자기
    자신과의 관계 금지(parent ≠ related) 불변식은 `schema.ProblemRelation`이 강제한다.
    """

    __tablename__ = "problem_relation"

    parent_problem_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("problem.problem_id"), primary_key=True
    )
    related_problem_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("problem.problem_id"), primary_key=True
    )
    relation_type: Mapped[RelationType] = mapped_column(
        _pg_enum(RelationType, "relation_type_enum"), primary_key=True
    )
    similarity_score: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))

    @classmethod
    def from_schema(cls, schema: SchemaProblemRelation) -> ProblemRelation:
        """검증된 `schema.ProblemRelation` → 영속 ORM(schema↔db seam)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaProblemRelation:
        """영속 ORM → `schema.ProblemRelation`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaProblemRelation.model_validate(
            drop_unset_nulls(data, SchemaProblemRelation, orm_cls=type(self))
        )


__all__ = ["Problem", "ProblemStep", "ProblemRelation"]
