"""ConceptVersion 영속 ORM 모델 (SQLAlchemy 2.0) — EOS-49.

설계 정본: `docs/architecture/44_eos_version_management.md` §6.2(VersionHeader)·§6.3
(도메인별 버전 테이블)·§7(Lifecycle 상태 머신). 좌석 판정: `docs/architecture/
canonical_entity_model_v1.md` §3-D "판정 2026-09-06"(게이트 `G-eos49-content-version-seat`
D안) — `concept_version`은 새 엔티티가 아니라 **Concept 좌석의 4번째 테이블**이다
(`curriculum_version`이 Curriculum 좌석의 2번째 테이블인 선례와 동형). `ContentVersion`
좌석(범용 버전 슈퍼테이블)은 계속 비워 둔다.

`schema/concept_version.py`(Pydantic)와 별도의 영속 매핑이며 `from_schema`/`to_schema`
헬퍼로 둘을 잇는다(`curriculum_version.py` 동일 패턴).

PK 판단(Principle 1: Entity ID ≠ Version ID):
  `version_id`는 UUID PK — server_default `gen_random_uuid()`.
  `concept_id`(Text)는 **의미 ID**(`Concept.code` — `math.<area>.<slug>`, 이 코드베이스
  실측 형식은 `{TRACK}-{AREA}-{NNN}`)를 참조하는 FK다. **`Concept.concept_id`(UUID 대리키)를
  참조하지 않는다** — 태스크 acceptance ①이 명시한 방향이며 `curriculum_version.framework_id
  → curriculum_framework.framework_id`(둘 다 의미 문자열 PK)와 동형 선례다.

Lifecycle 불변식 시행(§7 — acceptance ②):
  PUBLISHED 행의 `payload`는 불변이고, PUBLISHED → DRAFT 전이는 금지된다. 이 두 규칙은
  ORM 계층이 아니라 **DB BEFORE UPDATE 트리거**(`concept_version_immutability_guard`,
  alembic 리비전에서 생성)가 유일 권위로 강제한다 — ORM에는 가짜 CHECK/이벤트 리스너를
  만들지 않는다(`concept.py`의 "ORM에 가짜 CHECK를 만들지 않음" 방침과 동형, 여기서는
  트리거가 그 자리를 대신한다). 트리거 함수는 최초 생성 시점부터
  `SET search_path = pg_catalog, public`를 갖는다(slice 62 보안 하드닝 선례를 사후 적용이
  아니라 처음부터 반영 — 이 모듈이 코드베이스의 두 번째 DB 함수다).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.db.models._orm_enum import _pg_enum
from whymath_backend.db.models._schema_seam import drop_unset_nulls
from whymath_backend.schema.concept_version import ConceptVersion as SchemaConceptVersion
from whymath_backend.schema.version_header import VersionStatus

# JSONB로 저장되는 필드 — 중첩 UUID(예: `VersionSource.derived_from`·
# `ConceptVersionPayload.parent_concept_id`)가 이 안에 있으면 기본 `model_dump()`(모드
# "python")는 그 값을 raw `uuid.UUID` 객체로 남긴다. 엔진에 커스텀 `json_serializer`가
# 없으면(이 코드베이스 실측 — db/session.py 어디에도 미설정) SQLAlchemy가 stdlib
# `json.dumps`로 폴백하는데, 이는 UUID를 직렬화하지 못해 INSERT/UPDATE 시점에
# `TypeError: Object of type UUID is not JSON serializable`로 죽는다(다른 컬럼처럼
# 드라이버 레벨 타입 바인딩을 안 타고 범용 JSON 문자열화를 타기 때문). 스칼라 컬럼
# (`version_id`·`previous_version_id`·`created_at`·`published_at`)은 각자 전용
# SQLAlchemy 타입(Uuid·DateTime)이 네이티브로 바인딩하므로 영향 없음 — 이 JSONB
# 대상 5개만 `mode="json"`으로 다시 덤프해 UUID/datetime을 JSON-안전 문자열로 만든다.
_JSONB_FIELDS: tuple[str, ...] = ("change", "source", "governance", "integrity", "payload")


class ConceptVersion(Base):
    """Concept 버전 레코드 영속 ORM — Concept 좌석의 4번째 테이블(EOS-49).

    `concept_id`는 `concept.code`(Text UNIQUE, 의미 ID)를 참조한다 — `concept.concept_id`
    (UUID 대리키)가 아니다. `previous_version_id`는 self-FK(버전 체인).
    """

    __tablename__ = "concept_version"

    # ===== 식별 =====
    version_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    # 의미 ID(Concept.code) 참조 — Concept.concept_id(UUID 대리키)가 아니다(Principle 1).
    concept_id: Mapped[str] = mapped_column(sa.Text, sa.ForeignKey("concept.code"), nullable=False)
    entity_type: Mapped[str] = mapped_column(
        sa.String(50), nullable=False, server_default=sa.text("'Concept'")
    )
    version_no: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(sa.String(50), nullable=False)

    # ===== Lifecycle (44 §7) =====
    status: Mapped[VersionStatus] = mapped_column(
        _pg_enum(VersionStatus, "concept_version_status_enum"),
        nullable=False,
        server_default=sa.text("'DRAFT'"),
    )
    # self-FK — 버전 체인(직전 버전). 최초 버전은 NULL.
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("concept_version.version_id")
    )

    # ===== VersionHeader 서브필드(§6.2) — JSONB 스냅숏 =====
    # 각각 `schema.version_header.Version{Change,Source,Governance,Integrity}`의 model_dump().
    # SEC-06 전수 거버넌스(`test_jsonb_none_as_null_governance.py`) — 전 JSONB는
    # `none_as_null=True`(Python None → SQL NULL, JSON 스칼라 null 오계수 방지).
    change: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    source: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    governance: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    integrity: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))

    # ===== payload — 이 버전 시점의 Concept 스냅숏(불변성 트리거 보호 대상) =====
    payload: Mapped[dict[str, object]] = mapped_column(JSONB(none_as_null=True), nullable=False)

    # ===== 운영 메타 =====
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    # ── 제약·인덱스 ──────────────────────────────────────────────────────
    __table_args__ = (
        sa.UniqueConstraint("concept_id", "version_no", name="uq_concept_version_concept_no"),
        # "현재 발행 버전 찾기" 조회 경로(concept_id + status='PUBLISHED') 지원.
        sa.Index("idx_concept_version_concept_status", "concept_id", "status"),
    )

    # ── 변환 헬퍼 ────────────────────────────────────────────────────────
    @classmethod
    def from_schema(cls, schema: SchemaConceptVersion) -> ConceptVersion:
        """검증된 schema → ORM(mapper 컬럼키 필터, `curriculum_version.py` 동일 패턴)."""
        data = schema.model_dump()
        for field in _JSONB_FIELDS:
            value = getattr(schema, field, None)
            if value is not None:
                data[field] = value.model_dump(mode="json")
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaConceptVersion:
        """ORM → schema(Pydantic 검증 복원 — JSONB dict가 서브모델로 재검증된다)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaConceptVersion.model_validate(
            drop_unset_nulls(data, SchemaConceptVersion, orm_cls=type(self))
        )


__all__ = ["ConceptVersion"]
