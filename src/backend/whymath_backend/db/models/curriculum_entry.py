"""v1.1 다국 커리큘럼 매트릭스 셀(CurriculumEntry) ORM 모델 (SQLAlchemy 2.0 영속 레이어).

설계 정본: `schemas/v1.1/curriculum_entry.schema.yaml`(`fields:` 31필드·`composite_key:
[concept_id, country_code, subject]`·`storage: PostgreSQL`). 이 ORM은 `schema/curriculum_entry.py`
(Pydantic, 검증·API)와 *별도*로 세운 영속 매핑이며 `from_schema`/`to_schema` 변환 헬퍼가
둘을 잇는다(슬라이스 1 `problem.py` 동일 패턴).

PK 판단(이 모듈의 핵심 결정):
  YAML의 셀 의미키는 복합키 `(concept_id, country_code, subject)`이지만 `entry_id`가 그
  복합키와 1:1 대응하는 *표면 식별자*다. ORM PK는 `entry_id` *단일 PK*로 두고 복합키는
  `UniqueConstraint(concept_id, country_code, subject)`로 강제한다 — 표면키가 단일 PK로
  자연스럽고(조인·FK 타깃이 단순해짐), 복합키 유일성은 UNIQUE로 보존된다. 복합키 유일성의
  cross-dataset 검증(개념 그래프 노드 실재 등)은 *파이프라인 책임*이다(schema docstring).

subject 축 (과목 확장 S1 — subject_expansion_readiness.md §9):
  `subject`는 **교과** 레벨 과목 축('수학'·'물리')이다 — 같은 개념·같은 나라에서 교과가 다르면
  별개 셀(벡터: 수학·물리학)이라 UNIQUE가 3-튜플이다. NOT NULL + `server_default "수학"`으로
  기존 행·기존 INSERT 경로를 깨지 않는다(마이그레이션 rev a4b5c6d7e8f9). ⚠️ NCIC
  `AchievementStandard.subject`(**과목** 레벨 — '공통수학1')와 이름만 같고 축이 다르다
  (schema docstring 교차 명기).

타입 매핑(YAML → ORM, problem.py 선례 그대로):
  - `string`(entry_id, PK) → `sa.String`(UUID 아님 → server_default gen_random_uuid() 없음).
  - `concept_id`·`country_code`·`national_standard_codes` 등은 *느슨참조(cross-dataset)*라
    **FK 아님** — 다른 데이터셋(개념 그래프·NCIC standards.json)의 키 공간이라 DB FK로 묶지
    않는다(schema docstring "파이프라인 책임"·problem.py 본문 주석 방침과 동형).
  - `required_depth`(enum)·`license_id`(enum NOT NULL) → `_pg_enum(...)`. ⚠️ `CurriculumLicense`는
    멤버명≠값(`KR_NCIC="KR-NCIC"`)이라 values_callable이 *필수*다(없으면 PG enum이 'KR_NCIC'로
    새 — `_orm_enum._enum_values`가 막는다).
  - `date | null`(effective_from) → `sa.Date`(TIMESTAMPTZ 아님 — 날짜만).
  - `datetime`(created_at·updated_at, required:true) → `sa.DateTime(timezone=True), nullable=False`
    (YAML이 required로 명시 → problem.py의 Optional created_at과 달리 NOT NULL).
  - `float`(confidence, required) → `sa.Numeric(3, 2), nullable=False`(범위 [0,1]는 schema Field
    ge/le 책임 — ORM은 정밀도만).
  - `bool`(is_present, required) → `sa.Boolean, nullable=False`; `bool | null`(is_assessed) →
    `bool|None`(미응답=NULL).
  - `list<string>`(notation_variants·prerequisite_concept_ids 등) → `ARRAY(sa.Text)`(schema
    default_factory=list, 닫힌 NOT NULL 신호 없음 → nullable list, concept.cognitive_type 선례).

법적 메모: 이 모델은 교육과정 *구조·코드*만 담고 본문은 담지 않는다. 라이선스 의무는
`license_id`로 셀 단위 추적(schema가 문서화, 가짜 validator 없음 — ORM도 동일).
"""

from __future__ import annotations

from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.db.models._orm_enum import _pg_enum
from whymath_backend.db.models._schema_seam import drop_unset_nulls
from whymath_backend.schema.curriculum_entry import CurriculumEntry as SchemaCurriculumEntry
from whymath_backend.schema.enums import CurriculumLicense, RequiredDepth


# ──────────────────────────────────────────────────────────────────────────
# 핵심: CurriculumEntry (curriculum_entry.schema.yaml — 매트릭스 셀, 31필드)
# ──────────────────────────────────────────────────────────────────────────
class CurriculumEntry(Base):
    """다국 커리큘럼 매트릭스 셀 영속 ORM — YAML `CurriculumEntry`(31필드).

    PK는 `entry_id`(표면키, 단일 PK), 복합 의미키 `(concept_id, country_code, subject)`는
    `UniqueConstraint`로 강제한다(모듈 docstring PK 판단·subject 축). `concept_id`·
    `country_code`·`national_standard_codes` 등은 cross-dataset 느슨참조라 FK가 아니다.

    불변식(is_present=true면 source_url 필수·IMO 셀 confidence≤0.7)은 `schema.CurriculumEntry`의
    `@model_validator`가 강제한다 — ORM에는 컬럼만 두고 DB CHECK를 만들지 않는다(problem.py 방침).
    """

    __tablename__ = "curriculum_entry"

    # ===== 그룹 1: 식별 — 표면키 entry_id(PK) + 복합 의미키 (concept_id, country_code, subject) ==
    # entry_id는 str(UUID 아님)이라 gen_random_uuid() server_default 없음 — schema가 채운다.
    entry_id: Mapped[str] = mapped_column(sa.String, primary_key=True)
    # cross-dataset 느슨참조 → FK 아님(개념 그래프·국가 코드 키 공간, 파이프라인 책임).
    concept_id: Mapped[str] = mapped_column(sa.String, nullable=False)
    country_code: Mapped[str] = mapped_column(sa.String, nullable=False)
    # 교과 레벨 과목 축(S1) — NOT NULL + server_default '수학'(기존 행·INSERT 무손상 백필).
    # NCIC AchievementStandard.subject(과목 레벨 '공통수학1')와 granularity 다름(모듈 docstring).
    subject: Mapped[str] = mapped_column(sa.String, nullable=False, server_default="수학")

    # ===== 그룹 2: 출처 =====
    source_name: Mapped[str] = mapped_column(sa.String, nullable=False)
    source_code: Mapped[str | None] = mapped_column(sa.String)
    source_url: Mapped[str | None] = mapped_column(sa.String)
    source_document: Mapped[str | None] = mapped_column(sa.String)
    # license_id: required enum. CurriculumLicense는 멤버명≠값(KR_NCIC="KR-NCIC")이라
    # values_callable이 필수다(_orm_enum이 처리).
    license_id: Mapped[CurriculumLicense] = mapped_column(
        _pg_enum(CurriculumLicense, "curriculum_license_enum"),
        nullable=False,
    )

    # ===== 그룹 3: 시점 =====
    introduced_grade: Mapped[int | None] = mapped_column(sa.Integer)
    grade_band: Mapped[str | None] = mapped_column(sa.String)
    # DATE — 날짜만(TIMESTAMPTZ 아님).
    effective_from: Mapped[date | None] = mapped_column(sa.Date)
    curriculum_revision: Mapped[str | None] = mapped_column(sa.String)
    # CUR-10: CurriculumFramework 연결(느슨 FK, nullable). curriculum_revision은 하위호환 레이블.
    framework_id: Mapped[str | None] = mapped_column(
        sa.String(64), sa.ForeignKey("curriculum_framework.framework_id"), nullable=True
    )

    # ===== 그룹 4: 맥락 =====
    introduced_context: Mapped[str | None] = mapped_column(sa.Text)
    domain_label: Mapped[str | None] = mapped_column(sa.String)
    sub_domain_label: Mapped[str | None] = mapped_column(sa.String)

    # ===== 그룹 5: 깊이 =====
    required_depth: Mapped[RequiredDepth | None] = mapped_column(
        _pg_enum(RequiredDepth, "required_depth_enum")
    )
    cognitive_level: Mapped[str | None] = mapped_column(sa.String)
    is_assessed: Mapped[bool | None] = mapped_column(sa.Boolean)
    assessment_format: Mapped[str | None] = mapped_column(sa.String)

    # ===== 그룹 6: 표기 =====
    notation_local: Mapped[str | None] = mapped_column(sa.String)
    terminology_local: Mapped[str | None] = mapped_column(sa.String)
    notation_variants: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text))

    # ===== 그룹 7: 위계 (그 나라 교육과정 내 — 느슨참조, FK 아님) =====
    prerequisite_concept_ids: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text))
    followup_concept_ids: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text))

    # ===== 그룹 8: 매핑 (느슨참조, FK 아님) =====
    national_standard_codes: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text))
    textbook_unit_refs: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text))

    # ===== 그룹 9: 상태 =====
    is_present: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    # 범위 [0,1]은 schema Field ge/le 책임 — ORM은 DECIMAL(3,2) 정밀도만.
    confidence: Mapped[float] = mapped_column(sa.Numeric(3, 2), nullable=False)
    verified_by: Mapped[str | None] = mapped_column(sa.String)
    # YAML required:true → NOT NULL(problem.py Optional created_at과 다름).
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    # ── 제약 (복합 의미키 유일성 3-튜플 — 모듈 docstring PK 판단·subject 축) ──
    __table_args__ = (sa.UniqueConstraint("concept_id", "country_code", "subject"),)

    # ── 변환 헬퍼 (schema↔db seam, problem.py 패턴) ──────────────────────
    @classmethod
    def from_schema(cls, schema: SchemaCurriculumEntry) -> CurriculumEntry:
        """검증된 `schema.CurriculumEntry` → 영속 ORM(mapper 컬럼키 필터)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaCurriculumEntry:
        """영속 ORM → `schema.CurriculumEntry`(Pydantic 검증 복원 — 불변식 안전망)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaCurriculumEntry.model_validate(
            drop_unset_nulls(data, SchemaCurriculumEntry, orm_cls=type(self))
        )


__all__ = ["CurriculumEntry"]
