"""v1.1 교과서 매핑(TextbookMapping) ORM 모델 (SQLAlchemy 2.0 영속 레이어).

설계 정본: `schemas/v1.1/textbook_mapping.schema.yaml`(1)TextbookMapping·2)TextbookUnit·
3)TextbookToneProfile·`storage: PostgreSQL 16 — textbook_mappings + textbook_units`·
`ON DELETE CASCADE`). 이 ORM은 `schema/textbook_mapping.py`(Pydantic, 검증·API)와 *별도*로
세운 영속 매핑이며 변환 헬퍼가 둘을 잇는다(슬라이스 1 `problem.py` 동일 패턴).

⚠️ 이 도메인은 *유일하게 비-1:1*이다 — schema의 중첩(`TextbookMapping.unit_tree:
list[TextbookUnit]`·`tone_profile: TextbookToneProfile`)을 YAML storage 힌트("textbook_mappings
+ textbook_units")대로 **관계형 2테이블**로 편다:
  - `TextbookMapping`(테이블): isbn PK + 서지 + `tone_profile`을 *JSONB 컬럼*으로(별도 테이블로
    만들지 않음 — 톤 프로필은 부속 라벨 묶음이라 정규화 이득이 없고 schema가 통째 검증).
  - `TextbookUnit`(테이블): unit_id PK·`textbook_isbn` FK→textbook_mapping.isbn(ON DELETE
    CASCADE — YAML §4.5 즉시 격리: 교과서를 떼면 단원이 동반 삭제)·`parent_unit_id` self-FK.
  - `relationship`로 `TextbookMapping.units ↔ TextbookUnit.mapping`(back_populates).

타입 매핑(YAML → ORM, problem.py·슬라이스 8a 선례):
  - `string`(isbn, PK) → `sa.String`(UUID 아님 → server_default 없음); `subject`·`publisher`는
    enum이 아니라 `sa.String`(schema가 닫힌 enum 날조 회피로 str로 둔 정책 답습).
  - `integer`(grade·revision_year, required) → `sa.Integer, nullable=False`.
  - `list<string>`(authors·source_urls·standard_codes·concept_ids) → `ARRAY(sa.Text)`. source_urls는
    schema가 min_length=1(required NOT NULL 의미)이라 `nullable=False, server_default '{}'::text[]`
    (problem.py NOT NULL 배열 선례); authors 등 나머지는 nullable list.
  - `enum`(legal_review_status, default 있음) → `_pg_enum(...)`(LegalReviewStatus는 멤버명=값).
  - `string | null`(parent_unit_id·page_range·learning_objective_text) → `str|None`.
  - `standard_codes`·`concept_ids`는 cross-dataset 느슨참조라 **FK 아님**(NCIC standards.json·
    개념 그래프 키 공간 — schema docstring 파이프라인 책임).

법적 게이팅: `learning_objective_text`를 `legal_review_status='cleared'` 전까지 null로 막는
🚨 저작권 불변식은 `schema.TextbookMapping`의 `@model_validator`가 강제한다(트리 전체를 보고).
ORM은 재검증하지 않는다 — 변환 헬퍼가 schema를 거치므로 자연히 시행된다(problem.py 본문
미보유 불변식이 schema 책임인 것과 동형). ISBN 13자리 형식 검증도 schema 책임.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whymath_backend.db.base import Base
from whymath_backend.db.models._orm_enum import _pg_enum
from whymath_backend.db.models._schema_seam import drop_unset_nulls
from whymath_backend.schema.enums import LegalReviewStatus
from whymath_backend.schema.textbook_mapping import TextbookMapping as SchemaTextbookMapping
from whymath_backend.schema.textbook_mapping import TextbookToneProfile as SchemaTextbookToneProfile
from whymath_backend.schema.textbook_mapping import TextbookUnit as SchemaTextbookUnit


# ──────────────────────────────────────────────────────────────────────────
# 핵심: TextbookMapping (YAML 1절 — 교과서 1권, PK=isbn) + tone_profile JSONB
# ──────────────────────────────────────────────────────────────────────────
class TextbookMapping(Base):
    """교과서 매핑 영속 ORM — YAML 1절. 검정 교과서 1권의 *구조*(서지 + 단원 트리 + 톤
    프로필)를 개념·NCIC 성취기준에 잇는 매핑. PK는 `isbn`(13자리).

    중첩 평탄화: `unit_tree`는 `units`(TextbookUnit 행들, 1:N relationship)로, `tone_profile`은
    이 테이블의 *JSONB 컬럼*으로 편다(모듈 docstring). ISBN 13자리 형식·학습목표 게이팅
    불변식은 `schema.TextbookMapping`이 강제한다(ORM 재검증 없음).

    🚨 저작권 안전선: 서지·목차·페이지 *번호*·교육과정 코드 같은 구조 메타데이터만 담고
    본문·예제·문제·풀이·그림은 일절 담지 않는다(schema docstring).
    """

    __tablename__ = "textbook_mapping"

    # ===== 교과서 메타데이터 (서지 = 사실정보) =====
    # isbn은 str PK(UUID 아님). 13자리 형식 검증은 schema 책임.
    isbn: Mapped[str] = mapped_column(sa.String(13), primary_key=True)
    publisher: Mapped[str] = mapped_column(sa.String, nullable=False)
    book_title: Mapped[str] = mapped_column(sa.String, nullable=False)
    authors: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text))
    subject: Mapped[str] = mapped_column(sa.String, nullable=False)
    grade: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    revision_year: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    curriculum_revision: Mapped[str | None] = mapped_column(sa.String)

    # ===== 톤 프로필 (별도 테이블 아님 — JSONB 컬럼; required) =====
    tone_profile: Mapped[dict[str, object]] = mapped_column(
        JSONB(none_as_null=True), nullable=False
    )

    # ===== 출처·격리 메타 =====
    # source_urls: schema min_length=1(NOT NULL 의미) → server_default
    # (problem.py NOT NULL 배열 선례).
    source_urls: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )
    isolation_tag: Mapped[str] = mapped_column(sa.String, nullable=False)
    legal_review_status: Mapped[LegalReviewStatus] = mapped_column(
        _pg_enum(LegalReviewStatus, "legal_review_status_enum"),
        nullable=False,
        server_default=sa.text(
            f"'{LegalReviewStatus.not_required.value}'::legal_review_status_enum"
        ),
    )

    # ── 관계: 단원 트리(1:N). ON DELETE CASCADE는 FK 쪽(TextbookUnit)에서 건다 ──
    units: Mapped[list[TextbookUnit]] = relationship(
        back_populates="mapping",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # ── 변환 헬퍼 (schema↔db seam — 중첩 평탄화·복원) ────────────────────
    @classmethod
    def from_schema(cls, schema: SchemaTextbookMapping) -> TextbookMapping:
        """검증된 `schema.TextbookMapping`(중첩) → 영속 ORM(2테이블 평탄화).

        스칼라 서지 필드는 mapper 컬럼키 필터로 추리고(problem.py 패턴), 중첩 2필드는 명시
        처리한다: `tone_profile`은 서브모델 `model_dump()`로 JSONB dict, `unit_tree`는 각
        `TextbookUnit.from_schema`로 변환해 `units` 관계에 채운다. 학습목표 게이팅은 schema가
        이미 통과시켰으므로 ORM에서 재검증하지 않는다(모듈 docstring).
        """
        # 중첩 필드(unit_tree·tone_profile)는 평탄화 대상이라 스칼라 dump에서 제외하고 명시 처리.
        data = schema.model_dump(exclude={"unit_tree", "tone_profile"})
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        instance = cls(**kwargs)
        # tone_profile: 서브모델 → JSONB dict.
        instance.tone_profile = schema.tone_profile.model_dump()
        # unit_tree: list[TextbookUnit pydantic] → list[TextbookUnit ORM](관계로 FK 자동 설정).
        instance.units = [TextbookUnit.from_schema(unit) for unit in schema.unit_tree]
        return instance

    def to_schema(self) -> SchemaTextbookMapping:
        """영속 ORM(2테이블) → `schema.TextbookMapping`(중첩 복원·검증).

        스칼라 서지 컬럼은 그대로, `tone_profile`은 JSONB dict → `TextbookToneProfile`로,
        `units` 행들은 각 `to_schema`로 되돌려 `unit_tree`를 복원한다. Pydantic이 다시 검증하므로
        ISBN 형식·학습목표 게이팅 불변식이 재차 통과한다(영속 데이터 안전망).
        """
        scalar_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        # tone_profile은 아래에서 서브모델로 복원하므로 스칼라 dict에서 뺀다.
        scalar_keys.discard("tone_profile")
        data: dict[str, object] = {key: getattr(self, key) for key in scalar_keys}
        data["tone_profile"] = SchemaTextbookToneProfile.model_validate(self.tone_profile)
        data["unit_tree"] = [unit.to_schema() for unit in self.units]
        return SchemaTextbookMapping.model_validate(
            drop_unset_nulls(data, SchemaTextbookMapping, orm_cls=type(self))
        )


# ──────────────────────────────────────────────────────────────────────────
# 보조: TextbookUnit (YAML 2절 — 단원 트리 노드, FK→textbook_mapping)
# ──────────────────────────────────────────────────────────────────────────
class TextbookUnit(Base):
    """단원 트리 노드 영속 ORM — YAML 2절. 대→중→소단원 트리의 한 노드.

    `textbook_isbn` FK→textbook_mapping.isbn(`ON DELETE CASCADE` — YAML §4.5 즉시 격리),
    `parent_unit_id` self-FK(대단원이면 None). `standard_codes`·`concept_ids`는 cross-dataset
    느슨참조라 FK가 아니다(schema docstring 파이프라인 책임). 자기참조 금지·학습목표 게이팅
    불변식은 `schema.TextbookUnit`/`schema.TextbookMapping`이 강제한다(ORM 재검증 없음).

    `learning_objective_text`는 교과서 저작물이라 기본 None이며, 비-null 허용 여부는 소속
    TextbookMapping.legal_review_status가 결정한다(트리 전체를 보는 게이팅은 schema 책임).
    """

    __tablename__ = "textbook_unit"

    # unit_id는 str PK(UUID 아님).
    unit_id: Mapped[str] = mapped_column(sa.String, primary_key=True)
    # 소속 교과서 FK — ON DELETE CASCADE(교과서 격리 시 단원 동반 삭제, YAML §4.5).
    textbook_isbn: Mapped[str] = mapped_column(
        sa.String(13),
        sa.ForeignKey("textbook_mapping.isbn", ondelete="CASCADE"),
        nullable=False,
    )
    # 상위 단원 self-FK(대단원이면 None). 자기 자신 금지는 schema 불변식.
    parent_unit_id: Mapped[str | None] = mapped_column(
        sa.String, sa.ForeignKey("textbook_unit.unit_id")
    )
    unit_number: Mapped[str] = mapped_column(sa.String, nullable=False)
    unit_title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    page_range: Mapped[str | None] = mapped_column(sa.String)
    # cross-dataset 느슨참조 → FK 아님(NCIC·개념 그래프 키 공간).
    standard_codes: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text))
    concept_ids: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text))
    # 교과서 저작물 — legal_review_status='cleared' 전까지 null(게이팅은 schema 책임).
    learning_objective_text: Mapped[str | None] = mapped_column(sa.Text)

    # ── 관계: 소속 교과서(N:1) ──
    mapping: Mapped[TextbookMapping] = relationship(back_populates="units")

    @classmethod
    def from_schema(cls, schema: SchemaTextbookUnit) -> TextbookUnit:
        """검증된 `schema.TextbookUnit` → 영속 ORM(schema↔db seam).

        `textbook_isbn`은 schema 단원에 없는 FK라 여기서 세우지 않는다 — 부모
        `TextbookMapping.from_schema`가 `units` 관계에 append할 때 relationship이 자동
        설정한다(back_populates). mapper 컬럼키 필터로 schema 필드만 추린다(problem.py 패턴).
        """
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaTextbookUnit:
        """영속 ORM → `schema.TextbookUnit`(Pydantic 검증 복원).

        `textbook_isbn`·관계 속성은 schema에 없는 필드라 추리지 않는다 — schema TextbookUnit이
        아는 컬럼만 명시 dict로 넘긴다(extra="forbid" 충돌 회피, problem.py 방침).
        """
        schema_fields = set(SchemaTextbookUnit.model_fields)
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys & schema_fields}
        return SchemaTextbookUnit.model_validate(
            drop_unset_nulls(data, SchemaTextbookUnit, orm_cls=type(self))
        )


__all__ = ["TextbookMapping", "TextbookUnit"]
