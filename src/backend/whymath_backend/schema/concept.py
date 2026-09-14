"""Schema v1.0 도메인2 Concept Graph 모델 (Pydantic) — 슬라이스 3.

설계 정본: `schemas/v1.0/schema_v1.0.md` §4.2(`concept`·`concept_edge`·`problem_concept`·
`concept_fusion` DDL 4테이블). 개념 간 선후/포함/유사 관계를 DAG로 표현해 "막힌 진짜
이유 = 선수 개념 미숙"을 진단하는 도메인(특성 #16·PRD FR-006).

Phase 메모: 코드베이스 전체가 *Pydantic-schema-only*(DB 미배포) — 이 슬라이스도 순수
Pydantic 모델이다. SQLAlchemy/alembic 매핑은 후속 Phase(슬라이스 1 `problem.py` 동일 패턴).

컨벤션(`problem.py`·`provenance.py`·`l3/models.py` 답습):
  - `ConfigDict(extra="forbid", use_enum_values=True, str_strip_whitespace=True)`.
  - enum은 `enums.py`의 `class X(str, Enum)`(ConceptLevel·CognitiveType·EdgeType·ConceptRole).
    교육과정 enum(Subject·Curriculum)은 더 이상 사용하지 않는다(Overlay 이관·rev f3a4b5c6d7e8).
  - 불변식은 `@model_validator(mode="after")`(자기관계 금지는 슬라이스 1
    `ProblemRelation._no_self_relation` 패턴 답습).
  - 공유 베이스 클래스 없음(각 모델 독립).

타입 매핑 판단(DDL → Pydantic, 슬라이스 1·2 선례 그대로):
  - `UUID PK` → `uuid.UUID = Field(default_factory=uuid4)`
  - `UUID ... NOT NULL`(FK) → required `uuid.UUID`(예: concept_edge.from/to_concept_id)
  - nullable `UUID`(FK) → `uuid.UUID | None`(예: parent_concept_id)
  - `VARCHAR(n)` → `str`(max_length=n); `NOT NULL`이면 required(`...`)
  - `TEXT` → `str | None`
  - `TEXT[]` → `list[str]`(default_factory=list)
  - `enum[]` → `list[Enum]`(default_factory=list)
  - `UUID[] NOT NULL` → `list[uuid.UUID] = Field(..., min_length=1)`(예: concept_fusion.concept_ids)
  - nullable `UUID[]` → `list[uuid.UUID]`(default_factory=list)(예: exemplar_problem_ids)
  - `DECIMAL` → `float | None`(ge/le); 범위는 DDL 인라인 주석을 따르고, 미명시는
    의미에 맞는 보수값을 골라 각 필드 description에 1줄로 명시(슬라이스 1·2 방식)
  - `INTEGER` → `int | None`(ge/le)
  - `BOOLEAN DEFAULT FALSE` → `bool = False`
  - `TIMESTAMPTZ` → `datetime | None`

법적 메모(CLAUDE.md 절대 금기·저작권 가이드 v2.0·Phase 1b redaction):
  본문 근접 자유 서술(`description`·`formal_definition`·`intuitive_explanation`)과 자유텍스트
  오개념(`common_misconceptions`)은 2026-07-03 Part 2 리치 채택 **Phase 1b로 런타임 Concept
  노드에서 제거**했다 — 성취기준·교과서 본문 근접(앞 3개) 또는 낙인/즉답/날조 위험 오개념
  리스트(마지막)라 노드에 담지 않는다(redaction·CLAUDE.md #6). 자체작성 교수 텍스트의 정본은
  정본 identity 노드 semantic 계층(intuition·representations)과 ConceptContent가, 오개념은
  독립 오개념 DB(카탈로그 kebab-id)가 단일 진실이다. 노드 재내장은 `test_concept.py`의
  `_FORBIDDEN_NODE_FIELDS`와 schema↔ORM 정합 테스트가 정적으로 차단한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whymath_backend.schema.enums import (
    CognitiveType,
    ConceptLevel,
    ConceptRole,
    DependencyLevel,
    EdgeType,
    RequiredStrength,
    VisualizationStyle,
)


# ──────────────────────────────────────────────────────────────────────────
# 핵심: Concept (§4.2 concept 테이블 — 개념 노드, 3계층 위계)
# ──────────────────────────────────────────────────────────────────────────
class Concept(BaseModel):
    """개념 노드 — §4.2 `concept`(단원 > 소단원 > 세부개념 3계층).

    개념 그래프(DAG)의 노드. `code`(예: 'CAL-INT-DEF-FUNDAMENTAL')로 전역 식별되며,
    `parent_concept_id`로 상위 개념을 가리키는 위계와 `concept_edge`로 표현되는
    선후/유사 관계를 함께 가진다.

    불변식(`@model_validator(mode="after")`, 슬라이스 1 `ProblemRelation._no_self_relation`
    패턴): `parent_concept_id`가 있으면 `concept_id != parent_concept_id`(자기 자신을
    부모로 둘 수 없음).

    본문 근접 자유 서술(`description`·`formal_definition`·`intuitive_explanation`)과 자유텍스트
    오개념(`common_misconceptions`)은 Phase 1b(2026-07-03)로 이 런타임 노드에서 제거했다 —
    정본은 identity 노드 semantic 계층·ConceptContent·독립 오개념 DB다(모듈 docstring 법적 메모).

    `embedding_id`(구 pgvector 참조·슬98)는 ARCH-14로 *제거*했다 — 소비처 0·전량 NULL·로더
    미설정의 죽은 컬럼이었고, 실 벡터는 code 키 별 테이블(`concept_embedding` 등)이 소유한다.
    """

    model_config = ConfigDict(
        # 추가 필드 금지 — Pydantic 모델이 스키마의 단일 진실
        extra="forbid",
        # 직렬화 시 enum 값을 그대로(한글 값 보존: level="단원" 등)
        use_enum_values=True,
        # 문자열 양끝 공백 제거
        str_strip_whitespace=True,
    )

    # ===== 기본 식별 =====
    concept_id: uuid.UUID = Field(
        default_factory=uuid4,
        description="개념 PK (UUID)",
    )
    code: str = Field(
        ...,
        description="개념 코드 (UNIQUE, 예: 'HIGH-CALC-001'). 2026-06-16 UC→'{TRACK}-{AREA}-{NNN}' "
        "전환(breaking) — 추적성은 source_id·aliases로 보존.",
        max_length=64,
    )
    source_id: str | None = Field(
        default=None,
        description="재ID 전 원천 식별자(src_id, 예: 'N1'·'HK01'). concept_id가 src_id에서 "
        "*파생*되었음을 추적(롤백·재현). 백엔드는 옛 데이터(부재) 수용 위해 선택(None 허용).",
        max_length=64,
    )
    name_ko: str = Field(
        ...,
        description="한글 개념명 (예: '미적분학의 기본정리')",
        max_length=200,
    )
    name_en: str | None = Field(
        default=None,
        description="영문 개념명 (예: 'Fundamental Theorem of Calculus')",
        max_length=200,
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="옛 키 별칭 배열 — [레거시 UC, src_id]. 새 code 전환 후에도 옛 키·원천 키로 "
        "join/조회 가능하게 보존(하위호환, 예: ['UC.calc.ftc', 'N1']).",
    )

    # ===== 계층 정보 =====
    level: ConceptLevel = Field(
        ...,
        description="개념 계층 — 단원/소단원/세부개념 (NOT NULL)",
    )
    parent_concept_id: uuid.UUID | None = Field(
        default=None,
        description="상위 개념 FK (자기 자신 불가 — 불변식으로 강제)",
    )
    # ===== 교육과정 매핑 (Overlay 분리·노드 비내장) =====
    # 교육과정 정보(과목·버전·학년·학기·깊이)는 *개념 노드에 내장하지 않는다* — 교육과정은 시간·
    # 국가에 따라 바뀌는 Overlay이므로 `CurriculumEntry`(domain_label·curriculum_revision·
    # introduced_grade·country_code별)가 단일 진실 원천이다(math_dsl_risk_register.md Q5·Q8·Q10-③
    # "노드는 의미만"·completed Overlay 이관). 과거 내장 필드 `subject`·`curriculum_version`·
    # `grade_introduced`·`semester_introduced`는 모두 제거됐다 — 런타임 조회/필터 소비처가 없었고
    # (정합 게이팅은 `Problem.curriculum_version` 사용) Overlay와 중복이었다. `subject`는 원천
    # 코퍼스 domain에서 파생됐으므로 필요 시 CurriculumEntry 적재로 재구성한다(비가역 손실 아님).

    # ===== 개념의 특성 =====
    is_signature_korean: bool = Field(
        default=False,
        description="한국 수능 특유 개념 여부 (BOOLEAN DEFAULT FALSE)",
    )
    cognitive_type: list[CognitiveType] = Field(
        default_factory=list,
        description="인지 유형 배열 — DEFINITION/THEOREM/TECHNIQUE/PATTERN/VISUAL_REASONING",
    )
    recommended_visual_styles: list[VisualizationStyle] = Field(
        default_factory=list,
        description="권장 시각화 양식 배열 — 개념을 가장 잘 드러내는 교수학적 표현 형식 "
        "(예: 삼각함수→단위원·확률→수형도). 슬라이스 88·visualization_style_enum[] nullable.",
    )
    # cognition 참조 계층(Part 2 Phase 2b-2) — 이 개념이 exercise하는 스킬 skill_id 목록.
    # 정본 identity 노드 `behavior_skills`(concepts.jsonl·ai_estimated·2b-1 저작)의 *런타임 투영*
    # 이다. skill mastery(l2/skill_mastery_tracking)가 채점 attempt→평가 개념→스킬 해소에 쓰는
    # 참조 배열(= ANY 멤버십 조인 백킹). **참조 키일 뿐 본문 아님**(자체작성 skill_id 공간·redaction
    # 무관·신규 엣지 타입 0·anti-explosion). 구 437 `concept_node.behavior_skills`가 아니라 런타임
    # `concept` 테이블에 투영한다 — S0-4b 거버넌스가 concept_node 런타임 read를 금지하므로, 문제가
    # 태깅되는 concept(UUID) 축에 직접 싣는다(concept mastery와 동일 sanctioned 축).
    behavior_skills: list[str] = Field(
        default_factory=list,
        description="이 개념이 exercise하는 스킬 skill_id 목록(`skill.<slug>`·skill_node PK 공간). "
        "런타임 skill mastery 해소의 concept→skill 브리지. 참조 키 배열(본문 아님·자체작성).",
    )
    # 시각화 가능성 4분류(직접/동적/추상/불가)는 *노드 비내장* — 시각화 계층 Overlay
    # `concept_visualization`(`db/models/concept_visualization.py`·code 키)가 단일 진실이다
    # (ADR concept_node_layering_decision §1 "visualization 계층=노드 비내장"·CurriculumEntry
    # Overlay 선례). 노드 재내장은 `test_concept.py::_FORBIDDEN_NODE_FIELDS`가 차단한다.

    # ===== 난이도·중요도 =====
    intrinsic_difficulty: float | None = Field(
        default=None,
        description="개념 자체 난이도 1-5 (DDL 주석 'DECIMAL(3,2) 1-5')",
        ge=1.0,
        le=5.0,
    )
    exam_frequency: float | None = Field(
        default=None,
        description="시험 출제 빈도 0-1 (DDL 주석 '0-1')",
        ge=0.0,
        le=1.0,
    )
    weight_in_curriculum: float | None = Field(
        default=None,
        description="교육과정 가중치. DDL에 범위 미명시 → 정규화 가중치로 보아 ge=0 le=1 "
        "보수 설정(exam_frequency 선례).",
        ge=0.0,
        le=1.0,
    )

    # ===== 설명·예제(본문 계층) — 런타임 노드 비내장(Phase 1b 청산·redaction) =====
    # description·formal_definition·intuitive_explanation·common_misconceptions는 성취기준·
    # 교과서 *본문* 근접(앞 3개) 또는 자유텍스트 오개념(마지막)이라 런타임 Concept 노드에서
    # *제거*했다(Part 2 리치 채택 Phase 1b·2026-07-03). 앞 3개의 자체작성 정본은 정본 identity
    # 노드(semantic 계층·intuition/representations)와 ConceptContent가, 오개념은 독립 오개념
    # DB(카탈로그 kebab-id·CLAUDE.md #6)가 단일 진실이다. 노드 재내장은 test_concept.py의
    # `_FORBIDDEN_NODE_FIELDS`·schema↔ORM 정합 테스트가 차단한다.

    # ===== 벡터 임베딩 ID: ARCH-14로 제거(죽은 컬럼·순수성 부채 해소) =====
    # `embedding_id`(구 pgvector 참조 잔재·슬98)는 소비처 0·전량 NULL·로더 미설정이라
    # ORM·스키마 양쪽에서 제거했다(마이그레이션 동반). 실 벡터는 code 키 별 테이블이 소유.

    # ===== 판 관리(EOS-49 §6.4) — 현재 발행 버전 포인터 =====
    # `concept_version`(Concept 좌석 4번째 테이블)의 PUBLISHED 행을 가리키는 느슨 포인터.
    # schema↔ORM 필드 정합(`test_concept_orm.py::test_schema_orm_field_parity_frozen`)을
    # 위해 ORM 컬럼과 짝을 맞춘다 — from_schema/to_schema 교집합 필터가 이 필드 없이는
    # ORM 컬럼값을 조용히 유실한다(§ 모듈 docstring 변환 헬퍼 메커니즘).
    current_published_version_id: uuid.UUID | None = Field(
        default=None,
        description="현재 발행(PUBLISHED) 버전의 concept_version.version_id(없으면 미발행).",
    )

    # ===== 운영 메타 =====
    created_at: datetime | None = Field(default=None, description="생성 시각")

    # ── 불변식 ────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _no_self_parent(self) -> Concept:
        """자기 자신을 부모로 둘 수 없다 — parent_concept_id ≠ concept_id.

        슬라이스 1 `ProblemRelation._no_self_relation` 패턴. parent가 None이면
        검사 대상 아님(루트 개념 허용).
        """
        if self.parent_concept_id is not None and self.parent_concept_id == self.concept_id:
            raise ValueError(
                "개념 위계 위반: parent_concept_id가 concept_id와 같을 수 없다 "
                "(자기 자신이 부모일 수 없음)"
            )
        return self


# ──────────────────────────────────────────────────────────────────────────
# 핵심: ConceptEdge (§4.2 concept_edge 테이블 — DAG 엣지)
# ──────────────────────────────────────────────────────────────────────────
class ConceptEdge(BaseModel):
    """개념 관계(DAG 엣지) — §4.2 `concept_edge`.

    개념 A→B의 관계(선수/구성/유사/확장/대조)를 표현한다. `edge_type`별로 의미가 다르며
    (`EdgeType` docstring 참조), `typical_gap_signal`은 이 엣지의 *부재*를 진단하는 신호다
    (예: "학생이 B를 이해 못한 가장 흔한 이유는 A를 모르는 것").

    복합 UNIQUE `(from_concept_id, to_concept_id, edge_type)` — DB 제약(런타임/DB 레벨;
    단일 모델 레벨에서는 표현하지 않음).

    불변식(`@model_validator(mode="after")`, 슬라이스 1 `ProblemRelation._no_self_relation`
    패턴): `from_concept_id != to_concept_id`(자기 자신을 가리키는 엣지 금지).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    edge_id: uuid.UUID = Field(default_factory=uuid4, description="엣지 PK (UUID)")
    from_concept_id: uuid.UUID = Field(..., description="출발 개념 FK (NOT NULL)")
    to_concept_id: uuid.UUID = Field(..., description="도착 개념 FK (NOT NULL)")
    edge_type: EdgeType = Field(
        ...,
        description="관계 유형 — PREREQUISITE/COMPOSED_OF/ANALOGOUS_TO/EXTENDS/CONTRASTS",
    )
    edge_strength: float | None = Field(
        default=None,
        description="관계의 강도 0-1 (DDL 주석 '0-1')",
        ge=0.0,
        le=1.0,
    )
    typical_gap_signal: str | None = Field(
        default=None,
        description="이 엣지의 부재를 진단하는 신호(자체 작성 텍스트)",
    )
    notes: str | None = Field(default=None, description="비고")
    relation_subtype: str | None = Field(
        default=None,
        description="관계 세부유형 — 원자 백본 관계유형(원본/소단원내/소단원간/학년간/학교급간 등)",
    )

    # ── EOS 6_개념 DB 검토 §13 prerequisite 메타 (CUR-16) ──────────
    required_strength: RequiredStrength | None = Field(
        default=None,
        description="선수학습 관계의 필요 강도 — WEAK/MODERATE/STRONG/CRITICAL. "
        "edge_type이 PREREQUISITE일 때만 의미를 가진다.",
    )
    dependency_level: DependencyLevel | None = Field(
        default=None,
        description="선수학습 관계의 의존 수준 — RECOMMENDED/EXPECTED/REQUIRED. "
        "edge_type이 PREREQUISITE일 때만 의미를 가진다.",
    )
    minimum_mastery: float | None = Field(
        default=None,
        description="선수개념의 최소 숙련도 임계값 (0.0~1.0). "
        "edge_type이 PREREQUISITE일 때만 의미를 가진다.",
        ge=0.0,
        le=1.0,
    )
    curriculum_context: list[str] = Field(
        default_factory=list,
        description="교육과정 맥락 식별자 배열(예: '2022_KR_Math_9', '2015_KR_Math_9'). "
        "CurriculumEntry Overlay와의 느슨한 참조.",
    )
    evidence_source_id: str | None = Field(
        default=None,
        description="이 관계의 근거가 되는 증거/출처 ID(예: 'src_xxx').",
        max_length=64,
    )

    created_at: datetime | None = Field(default=None, description="생성 시각")

    # ── 불변식 ────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _no_self_edge(self) -> ConceptEdge:
        """자기 자신을 가리키는 엣지 금지 — from_concept_id ≠ to_concept_id."""
        if self.from_concept_id == self.to_concept_id:
            raise ValueError(
                "개념 엣지 위반: from_concept_id와 to_concept_id가 같을 수 없다 "
                "(자기 자신을 가리키는 엣지 금지)"
            )
        return self

    @model_validator(mode="after")
    def _prerequisite_meta_only_for_prerequisite(self) -> ConceptEdge:
        """선수학습 메타 필드는 PREREQUISITE 엣지에서만 사용 가능."""
        if self.edge_type != EdgeType.PREREQUISITE:
            if self.required_strength is not None:
                raise ValueError("required_strength은 PREREQUISITE 엣지에서만 설정할 수 있다")
            if self.dependency_level is not None:
                raise ValueError("dependency_level은 PREREQUISITE 엣지에서만 설정할 수 있다")
            if self.minimum_mastery is not None:
                raise ValueError("minimum_mastery는 PREREQUISITE 엣지에서만 설정할 수 있다")
        return self


# ──────────────────────────────────────────────────────────────────────────
# 보조: ProblemConcept (§4.2 problem_concept 테이블 — 문제↔개념 N:M)
# ──────────────────────────────────────────────────────────────────────────
class ProblemConcept(BaseModel):
    """문제 ↔ 개념 매핑 — §4.2 `problem_concept`(N:M).

    한 문제가 어떤 개념을 어떤 *역할*(핵심/보조/암묵/평가대상)로 사용하는지 잇는다.

    복합 PK `(problem_id, concept_id, role)` — DB 제약. PK 구성요소는 NOT NULL이므로
    셋 모두 required로 둔다(슬라이스 1 `ProblemRelation`이 PK 3요소를 모두 required로 둔
    선례 답습 — 특히 `role`은 PK 구성요소라 Optional이 아니다).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    problem_id: uuid.UUID = Field(..., description="문제 FK (복합 PK 구성요소)")
    concept_id: uuid.UUID = Field(..., description="개념 FK (복합 PK 구성요소)")
    relevance: float | None = Field(
        default=None,
        description="개념과의 관련도 0-1 (DDL 주석 '0-1')",
        ge=0.0,
        le=1.0,
    )
    role: ConceptRole = Field(
        ...,
        description="개념의 역할 — PRIMARY/SUPPORTING/IMPLICIT/TESTED (복합 PK 구성요소)",
    )


# ──────────────────────────────────────────────────────────────────────────
# 보조: ConceptFusion (§4.2 concept_fusion 테이블 — 단원 융합 패턴, 특성 #16)
# ──────────────────────────────────────────────────────────────────────────
class ConceptFusion(BaseModel):
    """단원 융합 패턴 — §4.2 `concept_fusion`(특성 #16).

    여러 개념이 한 문제에서 융합 출제되는 전형(예: "수열의 극한 + 부등식")을 표현한다.
    `concept_ids`는 융합되는 개념들(NOT NULL → 최소 1개 이상), `exemplar_problem_ids`는
    대표 예제 문제들이다.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    fusion_id: uuid.UUID = Field(default_factory=uuid4, description="융합 PK (UUID)")
    name: str | None = Field(
        default=None,
        description="융합 패턴명 (예: '수열의 극한 + 부등식')",
        max_length=200,
    )
    concept_ids: list[uuid.UUID] = Field(
        ...,
        description="융합되는 개념 FK 배열 (UUID[] NOT NULL → 최소 1개)",
        min_length=1,
    )
    fusion_difficulty: float | None = Field(
        default=None,
        description="융합 자체의 난이도. DDL에 범위 미명시 → 난이도 척도이므로 "
        "intrinsic_difficulty 선례를 따라 ge=1 le=5 설정.",
        ge=1.0,
        le=5.0,
    )
    typical_question_pattern: str | None = Field(
        default=None,
        description="이 융합이 출제되는 전형적 패턴(자체 작성 텍스트)",
    )
    exemplar_problem_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="대표 예제 문제 FK 배열(nullable UUID[])",
    )
