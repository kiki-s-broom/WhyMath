"""오개념 카탈로그(MisconceptionCatalog) ORM 모델 (SQLAlchemy 2.0 영속 레이어).

설계 정본: `schema/misconception_catalog.py`(Pydantic, 검증·API 계약)와 *별도*로 세운 영속
매핑이며 `from_schema`/`to_schema` 변환 헬퍼가 둘을 잇는다(`models/achievement_standard.py`
동일 패턴 — SQLModel 미사용). 이 슬라이스(Phase B.2)는 카탈로그의 ORM·계약·마이그레이션만
세우고, #290 코퍼스(`data/corpus/misconceptions_v1/misconceptions.json`·839 레코드) 로더는
후속 슬라이스 몫이다.

PK 판단(이 모듈의 핵심 결정):
  `mis_id`(의미 문자열·예 'M0425')가 PK다. UUID가 아니라 의미 문자열이라 `gen_random_uuid()`
  server_default가 없다(`achievement_standard.norm_id`가 str PK라 server_default 없는 것과
  동형 — 값은 schema/로더가 채운다).

별개 체계(FK 금지):
  이 테이블은 **M-id 콘텐츠 카탈로그**다. 기존 L4 탐지 엔진(`l4/misconception/catalog.py`의
  30종 kebab-id)·런타임 테이블(`misconception_hypothesis`·`evidence_links`·
  `misconception_embedding`의 kebab `misconception_id` 느슨참조)과는 *별개 체계*이며 그들과
  **FK를 걸지 않는다**(두 체계 공존·이 테이블은 독립). `concept_src_id`·`standard_code`도
  느슨참조라 FK가 아니다(`concept_standard_link.concept_code` 선례 — 해소는 로더 후속).

타입 매핑(schema → ORM, achievement_standard.py 선례 그대로):
  - `mis_id`(PK) → `sa.String(32)`(의미 문자열·server_default 없음). 원래 String(16)이었으나
    atom 투영 mis_id(`"ATOM:"+code`, `l1/misconception/atom_catalog.py`)가 실측 최장 18자
    (1,837건 중 348건이 16자 초과·예 'ATOM:10공수1-01-01-1')라 오버플로 — 32로 확폭했다
    (Phase 5 kebab→ATOM 이전 대비 헤드룸 포함, 마이그레이션 `a5b6c7d8e9f0`).
  - `canonical_statement`·`student_wrong_thinking`·`distractor_rule`·`correction_point`
    (자유 서술) → `sa.Text`(nullable·와이매스 자체 저작 보유 허용).
  - `error_type` → `sa.String(32)`(8종이나 닫힌 enum 강제는 파이프라인 책임 — str).
  - `difficulty` → `sa.String(8)`('상'/'중'/'하').
  - `ccss_code`·`standard_code` → `sa.String(32)`(느슨참조·코드 문자열).
  - `concept_src_id` → `sa.String(64)`(느슨참조·개념 코드 어휘 길이).
  - `school_level`·`domain` → `sa.String(...)` / `subunit` → `sa.String(128)` /
    `mapping_confidence` → `sa.String(16)` / `provenance_note` → `sa.String(32)`(nullable).
  - `mapping_score` → `sa.Numeric(5, 3)`(예 0.454~1.236 — 1.236까지 담는 precision/scale).
  - `severity`(Phase 4a) → `sa.String(16)`(blocking/local/cosmetic·후속 학습 손상도·difficulty와
    별개 축·어휘 강제는 파이프라인 책임).
  - `behavior_skills`(Phase 4a) → `ARRAY(sa.Text)` NOT NULL server_default '{}'(arises-in skill
    참조 배열·concept_node/problem_type_node 동형·FK·junction 아님·개념 FK 결합 없음·독립 DB 유지).

법적 메모: 본문(`canonical_statement` 등)은 와이매스 자체 저작이라 보유가 허용된다
(redaction 불요 — achievement_standard `statement` 보유 허용 선례와 동형).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.db.cms_edit_marker import CMS_EDIT_MARKER
from whymath_backend.schema.misconception_catalog import (
    MisconceptionCatalog as SchemaMisconceptionCatalog,
)


# ──────────────────────────────────────────────────────────────────────────
# 핵심: MisconceptionCatalog (오개념 카탈로그 — mis_id PK·M-id 콘텐츠 카탈로그)
# ──────────────────────────────────────────────────────────────────────────
class MisconceptionCatalog(Base):
    """오개념 카탈로그 영속 ORM — `mis_id` PK(의미 문자열·M-id).

    형식 검증(error_type 8종·difficulty 3종·코드 형식)·개념/성취기준 해소는 *데이터 파이프라인·
    로더 책임*이며 ORM에는 컬럼만 둔다(achievement_standard.py 방침과 동형 — 가짜 CHECK 없음).
    기존 kebab-id 오개념 체계와는 별개라 FK가 전혀 없다(모듈 docstring 별개 체계).
    """

    __tablename__ = "misconception_catalog"

    # ===== 식별 — mis_id(PK·의미 문자열·UUID 아님) =====
    # mis_id는 UUID가 아니라 의미 문자열(예 'M0425')이라 gen_random_uuid() server_default 없음.
    # String(32) — atom 투영 mis_id('ATOM:'+code)가 실측 최장 18자라 구 String(16)은 오버플로.
    # Phase 5 kebab→ATOM 이전 대비 헤드룸까지 32로 확폭(마이그레이션 a5b6c7d8e9f0).
    mis_id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)

    # ===== 본문 (와이매스 자체 저작 — 본문 보유 허용·redaction 불요) =====
    canonical_statement: Mapped[str | None] = mapped_column(sa.Text)
    student_wrong_thinking: Mapped[str | None] = mapped_column(sa.Text)
    distractor_rule: Mapped[str | None] = mapped_column(sa.Text)

    # ===== 분류 (닫힌 enum 강제는 파이프라인 책임 — str) =====
    error_type: Mapped[str | None] = mapped_column(sa.String(32))
    difficulty: Mapped[str | None] = mapped_column(sa.String(8))
    correction_point: Mapped[str | None] = mapped_column(sa.Text)
    # severity(Phase 4a) — 후속 학습 손상도(blocking/local/cosmetic·SEVERITY_VALUES). difficulty
    # (문항 난이도)와 별개 축·어휘 disjoint. 어휘 강제는 파이프라인 책임(String·가짜 CHECK 없음).
    severity: Mapped[str | None] = mapped_column(sa.String(16))

    # ===== 코드·매핑 (느슨참조 — FK 아님, 해소는 로더 후속) =====
    ccss_code: Mapped[str | None] = mapped_column(sa.String(32))
    concept_src_id: Mapped[str | None] = mapped_column(sa.String(64))
    standard_code: Mapped[str | None] = mapped_column(sa.String(32))
    school_level: Mapped[str | None] = mapped_column(sa.String(32))
    domain: Mapped[str | None] = mapped_column(sa.String(64))
    subunit: Mapped[str | None] = mapped_column(sa.String(128))
    mapping_confidence: Mapped[str | None] = mapped_column(sa.String(16))
    # Numeric(5,3) — mapping_score float(예 0.454~1.236). Decimal로 매핑된다.
    mapping_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 3))
    provenance_note: Mapped[str | None] = mapped_column(sa.String(32))

    # ===== cognition 참조 (Phase 4a·arises-in·신규 엣지 타입 0) =====
    # behavior_skills — 이 오개념이 튀어나오는 skill(arises-in·진단 방향) skill_id 참조 배열.
    # concept_node/problem_type_node.behavior_skills 동형(ARRAY(Text) NOT NULL·server_default '{}').
    # FK·junction 아님(anti-explosion). 개념 테이블에 FK 결합 안 됨(Level 2 loose-ref·독립 DB 유지).
    behavior_skills: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )

    # CMS 편집 표지(P3-25) — NULL=사람이 고친 적 없음(적재가 소유), 값=CMS가 마지막으로 고친 시각.
    # 적재(`populate`)는 이 값이 있는 행을 건너뛰어 충돌로 보고한다. server_default·백필 금지.
    # 규약 정본: `db/cms_edit_marker.py` · `docs/standards/cms_edit_vs_loader_contract.md`.
    cms_edited_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # ── 인덱스 (조회 경로 — UNIQUE는 mis_id PK뿐) ────────────────────────
    __table_args__ = (
        # 개념 코드로 카탈로그를 찾는 경로(느슨참조).
        sa.Index("idx_misconception_catalog_concept", "concept_src_id"),
        # 성취기준 코드로 찾는 경로(느슨참조).
        sa.Index("idx_misconception_catalog_standard", "standard_code"),
        # 오류 유형으로 필터(distractor 생성·진단 묶음).
        sa.Index("idx_misconception_catalog_error_type", "error_type"),
    )

    # ── 변환 헬퍼 (schema↔db seam, achievement_standard.py 패턴) ──────────
    @classmethod
    def from_schema(cls, schema: SchemaMisconceptionCatalog) -> MisconceptionCatalog:
        """검증된 `schema.MisconceptionCatalog` → 영속 ORM(mapper 컬럼키 필터)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaMisconceptionCatalog:
        """영속 ORM → `schema.MisconceptionCatalog`(Pydantic 검증 복원)."""
        # CMS 편집 표지는 운영 메타라 schema(extra=forbid)에 없다 — 복원 대상에서 뺀다(P3-25).
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys if key != CMS_EDIT_MARKER}
        return SchemaMisconceptionCatalog.model_validate(data)


__all__ = ["MisconceptionCatalog"]
