"""L3 교수법 팩 + 소단원 DSL ORM — 유형→팩→증거 사슬의 영속 좌석 (교수법 DSL 기반).

설계 정본: `docs/reviews/260724_v2_migration_pedagogy_dsl_review.md`(검토서)와
`docs/reviews/260724_v2_migration_pedagogy_dsl.alembic_draft.py`(수정 목표 스키마). 원본 원시
SQL의 Blocking/High 지적을 반영한 *정합 버전*을 구현한다(원본 SQL 복제 아님).

이 모듈은 소단원 DSL 컴파일 산출물(YAML=소스, DB=산출물·단방향)과 교수법 팩(데이터)을 담는
4개 L3 테이블을 정의한다:
  - `unit_spec`            소단원 DSL 컴파일 이력(버전드·게이트 상태)
  - `pedagogy_pack`        지식 유형별 교수법 팩(소크라테스 발문·페이딩·금지 모드·슬롯·증거)
  - `learning_objective`   학습목표(소단원→목표→유형→팩 사슬의 가운데 고리)
  - `pedagogy_content_slot` 콘텐츠 슬롯(provenance는 content_provenance FK 위임)

────────────────────────────────────────────────────────────────────────────
house style 정합 (검토서 반영 지적)
────────────────────────────────────────────────────────────────────────────
projection-table 계열(`atom_node`·`skill_node`·`concept_content`·`strategy_node`)과 동형으로
**schema/ Pydantic 표면·from_schema/to_schema seam을 두지 않는다**(컴파일러/시더가 직접 ORM에
적재). 따라서 `dialogue_turn`의 `_NON_SCHEMA_COLUMNS`(schema round-trip 시 ciphertext 제외)
패턴은 *이 모듈에는 해당 없음*이다 — schema 표면을 신설하지 않았으므로 제외할 seam이 없다.
민감 원문은 애초에 L3 콘텐츠 슬롯이 아니라 L2 `evidence_event`(봉투 암호화·별 모듈)에만 있다.

  M1 (fail-closed): `unit_spec.status`·`pedagogy_content_slot.status` 기본 'DRAFT'. 게이트 통과
      전에는 노출되지 않는다(컴파일러/검수가 통과 시에만 ACTIVE/APPROVED로 승격).
  M4 (native enum 예외): `k_type`은 `_pg_enum(KnowledgeType, "knowledge_type")`로 PG native
      enum에 매핑한다 — plain Text house style의 *의도적 예외*(커널 소유·과목 불변·enums.py
      KnowledgeType docstring·검토서 M4·MEMORY 결정 전제).
  H1/B2 (중복·저작권): `pedagogy_content_slot`은 provenance/라이선스를 *소유하지 않고*
      `content_provenance.provenance_id` FK로 위임한다. `license_tier`·`generated_by`·
      `prompt_version`·`source_refs` 같은 자유 텍스트 provenance 컬럼을 두지 않는다(기존
      `content_provenance`+`generation_log`의 저작권 불변식을 우회하지 않는다).
  H2 (concept_nodes 네임스페이스): `unit_spec.concept_nodes`·`learning_objective.concept_nodes`는
      원자 백본(`atom_node`·런타임 진실 — 노드 수는 `docs/data/corpus_facts.md`의
      `atom_graph.nodes`) 노드 code 배열이다. 봉인된 legacy 437/545
      그래프를 가리키지 않는다. FK/CHECK를 두지 않는다(존재 검증은 컴파일러 책임·house style).
      참조 축 확정은 ARCH-13(개념↔원자 입도 통합) 결론 대기(연성 의존).

본문 표기(CLAUDE.md L55): 콘텐츠 슬롯 `payload`는 렌더러-중립 LaTeX + 구조 태그(완전 AST
아님·화면 문자열 금지)를 JSONB로 담는다. `slot_type`은 팩이 정의하므로 enum이 아닌 TEXT로 둔다.

법적 메모(검토서 L2): `learning_objective.statement`/`achievement_std`는 성취기준(NCIC
공공누리) 유래 *자체 분해*를 전제로 둔다 — 교과서 학습목표 *본문*이면 저작권 게이트 대상
(`learning_objective_text` 선례). 이 좌석은 코드/자체분해만 보관한다.

7계층: L3 콘텐츠 생성·검증의 영속 좌석. L2(evidence_event)와 계층 경계가 다르므로 별 모듈·
별 마이그레이션으로 분리한다(검토서 H3).
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
from whymath_backend.schema.enums import KnowledgeType

# 소단원 상태 리터럴 — M1 fail-closed 기본값 'DRAFT'(게이트 통과 시에만 ACTIVE로 승격).
UNIT_SPEC_STATUS_DEFAULT: str = "DRAFT"
# 콘텐츠 슬롯 상태 리터럴 — M1 fail-closed 기본값 'DRAFT'(검수 통과 시에만 APPROVED로 승격).
CONTENT_SLOT_STATUS_DEFAULT: str = "DRAFT"


# ──────────────────────────────────────────────────────────────────────────
# L3: UnitSpec (소단원 DSL 컴파일 이력 — YAML=소스, DB=산출물·단방향)
# ──────────────────────────────────────────────────────────────────────────
class UnitSpec(Base):
    """소단원 DSL 컴파일 이력 영속 ORM — 버전드 소단원 명세(게이트 상태 포함).

    복합 PK `(unit_id, unit_version)` — 같은 소단원의 여러 버전을 보존(재컴파일 시 새 버전).
    `status`는 M1 fail-closed 기본 'DRAFT' — `v_unit_release_gate` 통과 시에만 컴파일러가
    'ACTIVE'로 올린다. `concept_nodes`는 원자 백본(`atom_node`) code 배열이며 FK가 아니다(H2).
    """

    __tablename__ = "unit_spec"

    # ===== 복합 PK (unit_id, unit_version) — 버전 보존 =====
    unit_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    unit_version: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, nullable=False, server_default=sa.text("1")
    )

    # ===== 명세 메타 =====
    api_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    curriculum_rev: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 연결 NCIC 성취기준 *코드* 배열(코드는 사실정보·본문 statement 아님·atom_node 동형).
    standard_codes: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), nullable=False)
    # H2: 원자 백본(atom_node·런타임 진실 — 규모는 corpus_facts의 atom_graph.nodes) 노드
    #     code 배열. legacy 437/545 아님.
    #     존재 검증은 컴파일러(데이터 파이프라인) 책임 — FK/CHECK 없음(house style).
    #     ARCH-13(개념↔원자 입도 통합) 결론 시 참조 축 확정(연성 의존).
    concept_nodes: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), nullable=False)

    # ===== 컴파일 산출물 메타(YAML→DB 단방향) =====
    yaml_sha256: Mapped[str] = mapped_column(sa.Text, nullable=False)
    compiler_ver: Mapped[str] = mapped_column(sa.Text, nullable=False)
    compiled_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    # ===== 게이트 상태 (M1: fail-closed 'DRAFT') =====
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default=sa.text("'DRAFT'"))

    __table_args__ = (
        # M1: 게이트 통과 전 차단. 컴파일러/게이트가 관리하는 상태 리터럴 화이트리스트.
        sa.CheckConstraint(
            "status IN ('DRAFT','ACTIVE','SUPERSEDED','BLOCKED')",
            name="status",
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# L3: PedagogyPack (교수법 팩 = 데이터. 시더가 packs YAML에서 적재)
# ──────────────────────────────────────────────────────────────────────────
class PedagogyPack(Base):
    """교수법 팩 영속 ORM — 지식 유형(k_type)별 교수 데이터(발문·페이딩·금지 모드·슬롯·증거).

    PK `k_type`(native enum) — 7유형과 1:1. 팩은 *데이터*(코드 아님)라 시더가 subject-math packs
    YAML에서 적재한다. `forbidden_modes`(런타임 가드·Kapur/Sweller 제약을 못박음)·`required_slots`
    (콘텐츠 매니페스트)·`default_evidence`(유형별 달성 증거 기본값)를 담는다.
    """

    __tablename__ = "pedagogy_pack"

    # PK = 지식 유형(native enum·M4 예외). 7유형과 1:1.
    k_type: Mapped[KnowledgeType] = mapped_column(
        _pg_enum(KnowledgeType, "knowledge_type"), primary_key=True
    )
    pack_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("1")
    )
    api_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 스텁 팩 여부(미완성 유형의 자리표시 — 기본 false). NOT NULL·server_default.
    is_stub: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    # 소크라테스 발문 템플릿(과목 명사 금지 — lint 대상·유형 불변 발문). NOT NULL.
    socratic_prompt: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 페이딩(도움 감소) 스케줄(JSONB·nullable — 팩이 정의).
    fading_schedule: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # 금지 모드(런타임 가드·기본 빈 배열). Kapur/Sweller 제약을 데이터로 못박는다.
    forbidden_modes: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )
    # 필요 슬롯 매니페스트(JSONB·NOT NULL — 유형별 필요한 콘텐츠 슬롯 정의).
    required_slots: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), nullable=False)
    # 유형별 기본 달성 증거 규격(JSONB·NOT NULL — "정답≠달성"의 유형별 기준).
    default_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False
    )


# ──────────────────────────────────────────────────────────────────────────
# L3: LearningObjective (소단원→목표→유형→팩 사슬의 가운데 고리)
# ──────────────────────────────────────────────────────────────────────────
class LearningObjective(Base):
    """학습목표 영속 ORM — 소단원의 한 목표(주 유형으로 교수법 팩에 바인딩).

    PK `id`. 복합 FK `(unit_id, unit_version)`→`unit_spec`(ON DELETE CASCADE). `k_type`(주 유형)이
    팩 바인딩 축이고 `k_type_secondary`(부 유형·기록만)는 주 유형과 달라야 한다(CHECK).
    `concept_nodes`는 원자 백본(`atom_node`) code 배열이며 FK가 아니다(H2).

    법적 메모(검토서 L2): `statement`/`achievement_std`는 성취기준(NCIC 공공누리) 유래 *자체
    분해* 전제 — 교과서 학습목표 *본문*이면 저작권 게이트 대상(`learning_objective_text` 선례).
    """

    __tablename__ = "learning_objective"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    # 복합 FK 구성요소 — inline FK 아님(ForeignKeyConstraint로 __table_args__에 둔다).
    unit_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    unit_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("1")
    )

    # ===== 목표 본문·성취기준 (자체 분해 전제) =====
    statement: Mapped[str] = mapped_column(sa.Text, nullable=False)
    achievement_std: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 성취기준 서술어(예 '설명한다'·'구한다'·nullable — 유형 추론 근거).
    source_verb: Mapped[str | None] = mapped_column(sa.Text)

    # ===== 지식 유형 (주=팩 바인딩·부=기록만·M4 native enum) =====
    k_type: Mapped[KnowledgeType] = mapped_column(
        _pg_enum(KnowledgeType, "knowledge_type"), nullable=False
    )
    k_type_secondary: Mapped[KnowledgeType | None] = mapped_column(
        _pg_enum(KnowledgeType, "knowledge_type")
    )
    # 유형 판정이 사람 검수를 거쳤는지(기본 false — AI 추정 정직 표기).
    k_type_verified: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )

    # ===== 연결 (원자 백본 code·오개념 id — 모두 느슨참조·FK 아님) =====
    # H2: atom_node code 배열(런타임 진실). legacy 437/545 아님·FK 없음.
    concept_nodes: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), nullable=False)
    misconception_ids: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text))

    # ===== 매니페스트·증거 규격 (JSONB) =====
    # 콘텐츠 슬롯 매니페스트(필요 슬롯 type/count — v_manifest_fill이 소비).
    slot_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), nullable=False)
    # 출구 증거 규격(이 목표를 언제 달성으로 볼지 — 유형별 기준).
    exit_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), nullable=False)
    # Polya 단계별 오버라이드(nullable — 팩 기본을 목표 단위로 덮어씀).
    phase_overrides: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    __table_args__ = (
        # 복합 FK → unit_spec(소단원 삭제 시 목표 CASCADE).
        sa.ForeignKeyConstraint(
            ["unit_id", "unit_version"],
            ["unit_spec.unit_id", "unit_spec.unit_version"],
            ondelete="CASCADE",
        ),
        # 부 유형은 주 유형과 달라야 한다(같으면 무의미한 중복).
        sa.CheckConstraint(
            "k_type_secondary IS NULL OR k_type_secondary <> k_type",
            name="secondary_distinct",
        ),
        # 소단원별 목표 조회 보조 인덱스.
        sa.Index("idx_lo_unit", "unit_id", "unit_version"),
    )


# ──────────────────────────────────────────────────────────────────────────
# L3: PedagogyContentSlot (콘텐츠 슬롯 — provenance는 content_provenance FK 위임)
# ──────────────────────────────────────────────────────────────────────────
class PedagogyContentSlot(Base):
    """콘텐츠 슬롯 영속 ORM — 학습목표에 딸린 콘텐츠 1점(생성/라이선스는 provenance FK 위임).

    PK `id`. FK `objective_id`→`learning_objective`(CASCADE)·`provenance_id`→`content_provenance`
    (nullable — 사람 직접 저작 시 NULL). B2/H1: `license_tier`·`generated_by`·`prompt_version`·
    `source_refs` 같은 provenance 컬럼을 *소유하지 않는다* — 생성 이력·라이선스·저작권 불변식은
    기존 `content_provenance`+`generation_log`가 소유한다. `status`는 M1 fail-closed 'DRAFT'.

    본문(payload): 렌더러-중립 LaTeX + 구조 태그(CLAUDE.md L55 — 완전 AST 아님·화면 문자열 금지)를
    JSONB로 담는다. `slot_type`은 팩이 정의(diag_item 등)하므로 enum이 아닌 TEXT다.
    """

    __tablename__ = "pedagogy_content_slot"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    objective_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 팩이 정의하는 슬롯 유형(diag_item 등) — TEXT 유지(enum 아님·팩 소유).
    slot_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 본문 — 렌더러-중립 LaTeX + 구조 태그(CLAUDE.md L55·완전 AST 아님).
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), nullable=False)
    # 검증 신호(nullable — 미검증 시 NULL).
    tts_safe: Mapped[bool | None] = mapped_column(sa.Boolean)
    sympy_verified: Mapped[bool | None] = mapped_column(sa.Boolean)
    # B2/H1: provenance 위임 — 생성/라이선스 이력은 content_provenance FK로만 잇는다.
    #        (nullable — 사람 직접 저작 콘텐츠는 provenance 레코드가 없을 수 있음).
    provenance_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("content_provenance.provenance_id")
    )

    # ===== 검수 상태 흐름 (M1: fail-closed 'DRAFT' → PRESCREENED → APPROVED|REJECTED) =====
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default=sa.text("'DRAFT'"))
    prescreen_score: Mapped[int | None] = mapped_column(sa.SmallInteger)
    reviewed_by: Mapped[str | None] = mapped_column(sa.Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    reject_reason: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    __table_args__ = (
        # 콘텐츠 슬롯 → 학습목표(목표 삭제 시 슬롯 CASCADE).
        sa.ForeignKeyConstraint(
            ["objective_id"],
            ["learning_objective.id"],
            ondelete="CASCADE",
        ),
        # M1: 검수 상태 화이트리스트(fail-closed).
        sa.CheckConstraint(
            "status IN ('DRAFT','PRESCREENED','APPROVED','REJECTED')",
            name="status",
        ),
        # 프리스크린 점수 0~3(nullable 허용).
        sa.CheckConstraint(
            "prescreen_score IS NULL OR prescreen_score BETWEEN 0 AND 3",
            name="prescreen",
        ),
        # 목표별 상태 조회 + 검수 대기 큐 부분 인덱스.
        sa.Index("idx_cm_obj_status", "objective_id", "status"),
        sa.Index(
            "idx_cm_queue",
            "status",
            postgresql_where=sa.text("status IN ('DRAFT','PRESCREENED')"),
        ),
    )


__all__ = [
    "UnitSpec",
    "PedagogyPack",
    "LearningObjective",
    "PedagogyContentSlot",
    "UNIT_SPEC_STATUS_DEFAULT",
    "CONTENT_SLOT_STATUS_DEFAULT",
]
