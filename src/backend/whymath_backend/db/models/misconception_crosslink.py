"""오개념 crosswalk(kebab-id ↔ M-id) 링크 ORM 모델 (SQLAlchemy 2.0 영속 레이어).

`concept_standard_link.py`(개념↔성취기준 N:M)의 *오개념* 짝이다. L4 런타임 탐지 정본 kebab-id 30종과
콘텐츠 카탈로그 M-id(건수는 `docs/data/corpus_facts.md`의 `misconceptions.count`)를 *FK로 묶지 않던* 두 체계 사이를 N:M 매핑으로 잇는다(오개념 정체성
통합 골격 — `math_dsl_remediation_design.md` §1). 학생 데이터는 kebab-id를 보존하고(rekey 불필요)
조회 시점에 이 테이블로 M-id를 해석한다(`l1/misconception/crosslink_resolve.py`).

PK·참조 판단(concept_standard_link 선례 그대로):
  - `link_id`(UUID PK·server_default gen_random_uuid()) — schema엔 link_id 없음(의미키는
    (kebab_id, mis_id, link_type)). from_schema가 link_id를 비우고 DB server_default가 채운다.
  - `kebab_id`(String(64)·NOT NULL) — L4 탐지 카탈로그 id *느슨참조*. **FK 아님** — kebab 카탈로그는
    코드 상수(`CATALOG_BY_ID`)라 DB 테이블이 없다(concept_standard_link.concept_code와 동형).
  - `mis_id`(String(32)·NOT NULL·**REAL FK** → `misconception_catalog.mis_id`·CASCADE) —
    M-id 삭제 시 매핑도 함께 삭제(연결은 M-id에 종속·concept_standard_link.norm_id 선례).
    참조 대상 `misconception_catalog.mis_id`와 동일 폭 String(32) — atom 투영 mis_id
    ('ATOM:'+code)가 실측 최장 18자라 구 String(16)에서 확폭(마이그레이션 a5b6c7d8e9f0).

`link_type`('직접매핑'/'부분매핑'/'개념겹침')·`method`('manual'/'standard_code'/'embedding')는 닫힌
어휘를 schema Literal·to_schema 재검증이 강제하므로 DB는 값만 담는다(String —
concept_standard_link.link_type 선례). `confidence`는 Numeric(3,2)(hypothesis.confidence 선례).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.schema.misconception_crosslink import (
    MisconceptionCrosslink as SchemaMisconceptionCrosslink,
)


class MisconceptionCrosslink(Base):
    """오개념 kebab-id ↔ M-id 연결 영속 ORM — `link_id` UUID PK, `mis_id` 실 FK.

    의미 유일키 `(kebab_id, mis_id, link_type)` — 같은 쌍·의미의 중복 링크를 막는다(복합 UNIQUE).
    `kebab_id`는 느슨참조(FK 아님), `mis_id`는 실 FK(misconception_catalog, CASCADE).
    """

    __tablename__ = "misconception_crosslink"

    link_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    # L4 탐지 카탈로그 id 느슨참조 — FK 아님(kebab 카탈로그는 코드 상수·DB 테이블 없음).
    kebab_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    # M-id 실 FK — M-id 삭제 시 매핑도 함께 삭제(연결은 M-id에 종속).
    # String(32) — 참조 대상 misconception_catalog.mis_id와 동일 폭(atom mis_id 최장 18자 실측).
    mis_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("misconception_catalog.mis_id", ondelete="CASCADE"),
        nullable=False,
    )
    # 연결 의미('직접매핑'/'부분매핑'/'개념겹침') — 닫힌 어휘는 schema Literal·to_schema 재검증 몫.
    link_type: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    # 매핑 신뢰도(0~1·검수 보조) — misconception_hypothesis.confidence(Numeric(3,2)) 선례.
    confidence: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    # 후보 근거 방식('manual'/'standard_code'/'embedding') — 닫힌 어휘는 schema Literal 몫.
    method: Mapped[str] = mapped_column(sa.String(16), nullable=False, server_default="manual")
    note: Mapped[str | None] = mapped_column(sa.Text)

    __table_args__ = (
        # 같은 (kebab, M-id, 의미) 쌍의 중복 링크 금지.
        sa.UniqueConstraint(
            "kebab_id",
            "mis_id",
            "link_type",
            name="uq_misconception_crosslink_kebab_mis_type",
        ),
        # kebab → 연결된 M-id 조회(read-time resolver 경로).
        sa.Index("idx_misconception_crosslink_kebab", "kebab_id"),
        # M-id → 연결된 kebab 조회(FK 역방향).
        sa.Index("idx_misconception_crosslink_mis", "mis_id"),
    )

    # ── 변환 헬퍼 (schema↔db seam, concept_standard_link.py 패턴) ──────────
    @classmethod
    def from_schema(cls, schema: SchemaMisconceptionCrosslink) -> MisconceptionCrosslink:
        """검증된 `schema.MisconceptionCrosslink` → 영속 ORM(mapper 컬럼키 필터).

        schema엔 `link_id`가 없으므로(의미키는 (kebab_id, mis_id, link_type)) 필터가 link_id를
        비우고 DB server_default(gen_random_uuid())가 채운다.
        """
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaMisconceptionCrosslink:
        """영속 ORM → `schema.MisconceptionCrosslink`(Pydantic 검증 복원).

        ORM 전용 컬럼 `link_id`는 schema에 없고(extra="forbid") 들어가면 거부되므로 schema 필드만
        추려 복원한다(concept_standard_link.to_schema 선례). Numeric → float 변환은 Pydantic이 처리.
        """
        schema_fields = set(SchemaMisconceptionCrosslink.model_fields)
        data = {name: getattr(self, name) for name in schema_fields}
        return SchemaMisconceptionCrosslink.model_validate(data)


__all__ = ["MisconceptionCrosslink"]
