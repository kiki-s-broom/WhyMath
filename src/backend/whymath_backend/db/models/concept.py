"""도메인2 Concept Graph ORM 모델 (SQLAlchemy 2.0 영속 레이어).

설계 정본: `schemas/v1.0/schema_v1.0.md` §4.2(`concept`·`concept_edge`·`problem_concept`·
`concept_fusion` DDL 4테이블)·§4.2 인덱스. 이 ORM은 `schema/concept.py`(Pydantic, 검증·API)와
*별도*로 세운 영속 매핑이며 `from_schema`/`to_schema` 변환 헬퍼가 둘을 잇는다(슬라이스 1
`problem.py` 동일 패턴 — SQLModel 미사용).

타입 매핑(DDL → ORM, problem.py 선례 그대로):
  - `UUID PRIMARY KEY` → `server_default gen_random_uuid()`(problem.py가 모든 UUID PK에 동일
    적용한 선례 — schema의 `default_factory=uuid4`와 양면으로 PK를 채운다).
  - `UUID REFERENCES`(NOT NULL 명시) → required `uuid.UUID` + FK; nullable FK → `uuid.UUID|None`.
  - self-FK(`parent_concept_id REFERENCES concept`) → `sa.ForeignKey("concept.concept_id")`.
  - `concept_role_enum`/`edge_type_enum`/`concept_level_enum` → `_pg_enum(...)`(values_callable).
  - `cognitive_type_enum[]` → `ARRAY(_pg_enum(...))`(DDL NOT NULL 아님 → nullable list).
    (`visualization_style_enum[]` 구 `recommended_visual_styles`·슬88은 ARCH-14 ③으로 전용 Overlay
    `concept_visual_style`로 이관됨 — 노드 비내장·Concept Purity, rev a9b8c7d6e5f4.)
  - `UUID[] NOT NULL`(concept_fusion.concept_ids) → `ARRAY(sa.Uuid)`(*배열이라 FK 아님* —
    schema docstring 명시) + `nullable=False, server_default "'{}'::uuid[]"`.
  - nullable `UUID[]`(exemplar_problem_ids) → `ARRAY(sa.Uuid)`(배열, FK 아님, nullable).
  - 인덱스(§4.2 `CREATE INDEX`) → `__table_args__`.

법적 메모(Phase 1b redaction·2026-07-03): 본문 근접 자유 서술 3종(description·formal_definition·
intuitive_explanation)과 자유텍스트 오개념(common_misconceptions)은 런타임 노드에서 *제거*했다
(마이그레이션 동반). 정본은 정본 identity 노드 semantic 계층·ConceptContent·독립 오개념 DB다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.db.models._orm_enum import _pg_enum
from whymath_backend.schema.concept import Concept as SchemaConcept
from whymath_backend.schema.concept import ConceptEdge as SchemaConceptEdge
from whymath_backend.schema.concept import ConceptFusion as SchemaConceptFusion
from whymath_backend.schema.concept import ProblemConcept as SchemaProblemConcept
from whymath_backend.schema.enums import (
    CognitiveType,
    ConceptLevel,
    ConceptRole,
    DependencyLevel,
    EdgeType,
    RequiredStrength,
)


# ──────────────────────────────────────────────────────────────────────────
# 핵심: Concept (§4.2 concept 테이블 — 개념 노드, 3계층 위계)
# ──────────────────────────────────────────────────────────────────────────
class Concept(Base):
    """개념 노드 영속 ORM — §4.2 `concept`(단원 > 소단원 > 세부개념 3계층).

    `code`는 `UNIQUE NOT NULL`(전역 식별), `parent_concept_id`는 self-FK(상위 개념).
    자기 자신을 부모로 둘 수 없는 불변식은 `schema.Concept._no_self_parent`가 강제한다
    (ORM에는 가짜 CHECK를 만들지 않음 — problem.py 방침).
    """

    __tablename__ = "concept"

    # ===== 기본 식별 =====
    concept_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    # code = concept_id(개념그래프 UC). Part 9(#409)가 `math.<area>.<slug>`로 재-ID하며 최장
    # 83자(예 'math.measurement.pyeonghaengsabyeonhyeong-…-neolbi')가 돼 구 String(64)를 넘어섰다
    # → Text로 확폭(같은 UC 키의 다른 투영 `concept_node.concept_id`가 이미 Text·단일 키공간 정합).
    # unique 유지(PG Text 유니크 인덱스 정상)·FK 무영향(타 테이블은 concept_id UUID를 참조).
    code: Mapped[str] = mapped_column(sa.Text, unique=True, nullable=False)
    name_ko: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    name_en: Mapped[str | None] = mapped_column(sa.String(200))
    # source_id: 재ID(2026-06-16) 이전 원천 식별자(src_id) 보존 — concept_id가 src_id에서
    # *파생*되었음을 추적(롤백·재현). data-pipeline Concept.source_id(필수)의 영속 짝이나, 백엔드
    # 적재기는 옛 graph.json(source_id 부재)도 받을 수 있어 *nullable*로 둔다(점진 채움·하위호환).
    # FK 아님(원천 키 공간) — 인덱스만 둔다(src_id로 개념을 역조회·링크 해석 SELECT의 조회 키).
    source_id: Mapped[str | None] = mapped_column(sa.String(64))
    # aliases: 옛 키 별칭([레거시 UC, src_id]) — 새 code로 전환 후에도 옛 키·원천 키로 join 가능.
    # schema.Concept.aliases가 list[str](default_factory=list·NOT NULL 의미)라 problem.py
    # tags/keywords 선례대로 NOT NULL + server_default '{}'로 둔다(NULL 대신 빈 배열로 정규화).
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )

    # ===== 계층 정보 =====
    level: Mapped[ConceptLevel] = mapped_column(
        _pg_enum(ConceptLevel, "concept_level_enum"),
        nullable=False,
    )
    parent_concept_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("concept.concept_id")
    )
    # subject·curriculum_version 제거됨(Overlay 분리·rev f3a4b5c6d7e8) — 교육과정은
    # CurriculumEntry(domain_label·curriculum_revision)가 단일 진실. 런타임 조회 소비처 0이었다.

    # ===== 교육과정 매핑 =====
    # `grade_introduced`·`semester_introduced`는 제거됨 — 교육과정 도입정보는 노드 내장이 아니라
    # `CurriculumEntry`(Overlay·국가별 introduced_grade·required_depth)가 단일 진실이다
    # (math_dsl_risk_register.md Q5·Q8). 두 컬럼은 전량 NULL·중복이라 안전 제거(마이그레이션 동반).

    # ===== 개념의 특성 =====
    is_signature_korean: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    # DDL은 cognitive_type_enum[](NOT NULL 아님) → nullable list. schema는 default_factory=list
    # 라 실무상 항상 list를 넘기지만 DDL 충실성을 위해 nullable로 둔다.
    cognitive_type: Mapped[list[CognitiveType] | None] = mapped_column(
        ARRAY(_pg_enum(CognitiveType, "cognitive_type_enum"))
    )
    # ===== 권장 시각화 양식: ARCH-14 ③으로 제거(Concept Purity 마지막 부채 청산·Overlay 이관) =====
    # 구 `recommended_visual_styles`(슬88·visualization_style_enum[])는 개념 정체성이 아니라 시각화
    # 계층의 투영 정보라 전용 Overlay `concept_visual_style`(code 키)로 외부화했다
    # (rev a9b8c7d6e5f4·`concept_visualization`·CurriculumEntry Overlay 선례).
    # 스키마 필드로는 존치(API 계약·Overlay 값을 API seam이 model_copy로 주입)하되 런타임
    # 노드 컬럼은 제거했다. 컬럼 데이터는 전량 NULL이었고 *ORM 컬럼 직접* 소비처는 0이다 —
    # 소비(L3 visualization·L4 scene)는 모두 스키마 필드 경로라 API seam Overlay 주입으로 무손실
    # 재배선된다(embedding_id/Phase 1b 청산과 달리 죽은 컬럼이 아니라 소비처 살아있는 이관).
    # 시각화 가능성 4분류도 *노드 비내장* — 시각화 계층 Overlay `concept_visualization`
    # (`db/models/concept_visualization.py`·code 키)가 단일 진실(ADR 계층분리·CurriculumEntry 선례).

    # ===== cognition 참조(Part 2 Phase 2b-2) — concept→skill 브리지 =====
    # 이 개념이 exercise하는 스킬 skill_id 목록(정본 노드 behavior_skills·2b-1 저작의 런타임 투영).
    # skill mastery가 채점 attempt→평가 개념→스킬 해소(= ANY 멤버십 조인)에 쓴다. 참조 키 배열이라
    # `aliases`(NOT NULL·server_default '{}') 선례 동형 — junction 테이블 아님·신규 엣지 타입 0.
    # 구 437 concept_node가 아니라 *런타임 concept* 테이블에 싣는다(S0-4b: concept_node 런타임 read
    # 금지·문제 태깅 축인 concept UUID에 직접 투영·concept mastery와 동일 sanctioned 축).
    behavior_skills: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )

    # ===== 난이도·중요도 =====
    intrinsic_difficulty: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    exam_frequency: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    weight_in_curriculum: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))

    # ===== 설명·예제(본문 계층) — 런타임 노드 비내장(Phase 1b 청산·redaction) =====
    # description·formal_definition·intuitive_explanation(Text×3)과 common_misconceptions(JSONB)는
    # 2026-07-03 Part 2 리치 채택 Phase 1b로 *제거*했다(마이그레이션 동반). 앞 3개는 성취기준·교과서
    # 본문 근접(redaction), 마지막은 자유텍스트 오개념(독립 오개념 DB·CLAUDE.md #6)이라 런타임
    # 노드에 담지 않는다. 네 컬럼 모두 소비처 0·전량 NULL/`[]`이었다(죽은 컬럼 청산·계약 변경).

    # ===== 벡터 임베딩 ID: ARCH-14로 제거(죽은 컬럼 청산·순수성 부채 해소) =====
    # `embedding_id`(구 ChromaDB→pgvector 이관 잔재·슬98)는 소비처 0·전량 NULL·로더 미설정·
    # 코퍼스 부재였다(위 Phase 1b 4컬럼 청산 선례 동형). 실 벡터는 code 키 별 테이블
    # (`concept_embedding` 등)이 소유하므로 이 참조 컬럼은 불필요 — 마이그레이션 동반 제거.

    # ===== 판 관리(EOS-49 §6.4) — 현재 발행 버전 포인터 =====
    # `concept_version`(Concept 좌석 4번째 테이블 — canonical_entity_model_v1.md §3-D
    # 판정 D안)의 PUBLISHED 행을 가리키는 느슨 포인터. nullable·기본값 없음 — 기존 행
    # 무영향(비파괴, 44_eos_version_management.md §6.4 "Entity 상태와 Version 상태는
    # 분리"). 이 컬럼 자체는 어떤 전이 규칙도 강제하지 않는다 — PUBLISHED 불변·
    # PUBLISHED→DRAFT 금지는 `concept_version` BEFORE UPDATE 트리거가 강제한다.
    current_published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("concept_version.version_id")
    )

    # ===== 운영 메타 =====
    created_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    # ── 인덱스 (§4.2 CREATE INDEX + source_id 역조회) ──
    __table_args__ = (
        sa.Index("idx_concept_code", "code"),
        sa.Index("idx_concept_parent", "parent_concept_id"),
        sa.Index("idx_concept_level", "level"),
        # src_id → code 해석(standard_loader load_links)·src_id 역조회 경로.
        sa.Index("idx_concept_source_id", "source_id"),
    )

    # ── 변환 헬퍼 (schema↔db seam, problem.py 패턴) ──────────────────────
    @classmethod
    def from_schema(cls, schema: SchemaConcept) -> Concept:
        """검증된 `schema.Concept` → 영속 ORM(mapper 컬럼키 필터)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaConcept:
        """영속 ORM → `schema.Concept`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaConcept.model_validate(data)


# ──────────────────────────────────────────────────────────────────────────
# 핵심: ConceptEdge (§4.2 concept_edge 테이블 — DAG 엣지)
# ──────────────────────────────────────────────────────────────────────────
class ConceptEdge(Base):
    """개념 관계(DAG 엣지) 영속 ORM — §4.2 `concept_edge`.

    `from_concept_id`·`to_concept_id`는 `REFERENCES concept NOT NULL`, `edge_type` NOT NULL.
    복합 UNIQUE `(from_concept_id, to_concept_id, edge_type)` — DDL 제약. 자기 자신을 가리키는
    엣지 금지는 `schema.ConceptEdge._no_self_edge`가 강제한다(ORM 가짜 CHECK 없음).
    """

    __tablename__ = "concept_edge"

    edge_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    from_concept_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("concept.concept_id"), nullable=False
    )
    to_concept_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("concept.concept_id"), nullable=False
    )
    edge_type: Mapped[EdgeType] = mapped_column(
        _pg_enum(EdgeType, "edge_type_enum"),
        nullable=False,
    )
    edge_strength: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    typical_gap_signal: Mapped[str | None] = mapped_column(sa.Text)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    # 원자 백본 관계유형(원본/소단원내/소단원간/학년간/학교급간 등) — 자유 텍스트 주석.
    relation_subtype: Mapped[str | None] = mapped_column(sa.Text)

    # ── EOS 6_개념 DB 검토 §13 prerequisite 메타 (CUR-16) ─────────
    required_strength: Mapped[RequiredStrength | None] = mapped_column(
        _pg_enum(RequiredStrength, "required_strength_enum")
    )
    dependency_level: Mapped[DependencyLevel | None] = mapped_column(
        _pg_enum(DependencyLevel, "dependency_level_enum")
    )
    minimum_mastery: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    curriculum_context: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text),
        nullable=False,
        server_default=sa.text("'{}'::text[]"),
    )
    evidence_source_id: Mapped[str | None] = mapped_column(sa.String(64))

    created_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    # ── 제약·인덱스 (§4.2 UNIQUE + CREATE INDEX) ──
    __table_args__ = (
        sa.UniqueConstraint("from_concept_id", "to_concept_id", "edge_type"),
        sa.Index("idx_concept_edge_from", "from_concept_id", "edge_type"),
        sa.Index("idx_concept_edge_to", "to_concept_id", "edge_type"),
    )

    @classmethod
    def from_schema(cls, schema: SchemaConceptEdge) -> ConceptEdge:
        """검증된 `schema.ConceptEdge` → 영속 ORM(schema↔db seam)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaConceptEdge:
        """영속 ORM → `schema.ConceptEdge`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaConceptEdge.model_validate(data)


# ──────────────────────────────────────────────────────────────────────────
# 보조: ProblemConcept (§4.2 problem_concept 테이블 — 문제↔개념 N:M)
# ──────────────────────────────────────────────────────────────────────────
class ProblemConcept(Base):
    """문제 ↔ 개념 매핑 영속 ORM — §4.2 `problem_concept`(N:M).

    복합 PK `(problem_id, concept_id, role)` — DDL 제약. `problem_id`는 메인의 problem 테이블,
    `concept_id`는 이 배치의 concept 테이블을 참조한다(둘 다 문자열 FK 타깃).
    """

    __tablename__ = "problem_concept"

    problem_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("problem.problem_id"), primary_key=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("concept.concept_id"), primary_key=True
    )
    relevance: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    role: Mapped[ConceptRole] = mapped_column(
        _pg_enum(ConceptRole, "concept_role_enum"), primary_key=True
    )

    # ── 인덱스 (§4.2 CREATE INDEX) ──
    __table_args__ = (sa.Index("idx_problem_concept_pc", "problem_id", "concept_id"),)

    @classmethod
    def from_schema(cls, schema: SchemaProblemConcept) -> ProblemConcept:
        """검증된 `schema.ProblemConcept` → 영속 ORM(schema↔db seam)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaProblemConcept:
        """영속 ORM → `schema.ProblemConcept`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaProblemConcept.model_validate(data)


# ──────────────────────────────────────────────────────────────────────────
# 보조: ConceptFusion (§4.2 concept_fusion 테이블 — 단원 융합 패턴, 특성 #16)
# ──────────────────────────────────────────────────────────────────────────
class ConceptFusion(Base):
    """단원 융합 패턴 영속 ORM — §4.2 `concept_fusion`(특성 #16).

    `concept_ids`(`UUID[] NOT NULL`)·`exemplar_problem_ids`(nullable `UUID[]`)는 *배열이라
    FK가 아니다*(schema docstring 명시 — DB FK는 스칼라 컬럼에만 걸린다). concept_ids는
    NOT NULL이므로 problem.py NOT NULL 배열 선례대로 server_default `'{}'::uuid[]`를 둔다.
    """

    __tablename__ = "concept_fusion"

    fusion_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    name: Mapped[str | None] = mapped_column(sa.String(200))
    # UUID[] NOT NULL — 배열이라 FK 아님(concept를 *가리키는 값 묶음*일 뿐).
    concept_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(sa.Uuid), nullable=False, server_default=sa.text("'{}'::uuid[]")
    )
    fusion_difficulty: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    typical_question_pattern: Mapped[str | None] = mapped_column(sa.Text)
    # nullable UUID[] — 배열이라 FK 아님.
    exemplar_problem_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(sa.Uuid))

    @classmethod
    def from_schema(cls, schema: SchemaConceptFusion) -> ConceptFusion:
        """검증된 `schema.ConceptFusion` → 영속 ORM(schema↔db seam)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaConceptFusion:
        """영속 ORM → `schema.ConceptFusion`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaConceptFusion.model_validate(data)


__all__ = ["Concept", "ConceptEdge", "ProblemConcept", "ConceptFusion"]
