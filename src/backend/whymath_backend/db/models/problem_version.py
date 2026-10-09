"""ProblemVersion 영속 ORM 모델 (SQLAlchemy 2.0) — ARCH-31.

설계 정본: `docs/architecture/44_eos_version_management.md` §6.2(VersionHeader)·§6.3
(도메인별 버전 테이블)·§6.4(Entity의 현재 버전 포인터)·§7(Lifecycle 상태 머신). 좌석 판정:
`docs/architecture/canonical_entity_model_v1.md` §3-D "판정 2026-09-06"(게이트
`G-eos49-content-version-seat` D안) — `problem_version`은 새 엔티티가 아니라 **Problem 좌석의
3번째 테이블**이다(`concept_version`이 Concept 좌석의 4번째 테이블인 선례와 동형). `ContentVersion`
좌석(범용 버전 슈퍼테이블)은 계속 비워 둔다. 설계·`identity_id` 관계 정본은
`docs/architecture/arch31_problem_version.md`.

`schema/problem_version.py`(Pydantic)와 별도의 영속 매핑이며 `from_schema`/`to_schema`
헬퍼로 둘을 잇는다(`concept_version.py` 동일 패턴).

PK 판단(Principle 1: Entity ID ≠ Version ID):
  `version_id`는 UUID PK — server_default `gen_random_uuid()`.
  `problem_id`(UUID)는 **`problem.problem_id`를 참조하는 FK**다. Concept 쪽이 의미 ID(`code`)를
  참조한 것과 달리 여기는 UUID PK를 참조한다 — Problem의 의미 식별자(`slug`·`external_id`)는
  nullable이라 FK 대상이 될 수 없고, 44 §6.3이 `problem_id: UUID  # Problem entity FK`로 못 박았다.

상호 FK: `problem.problem_version_id → problem_version.version_id`(현재 서빙 기준 판 포인터)와
`problem_version.problem_id → problem.problem_id`가 서로를 가리킨다(§6.4 "Entity 상태와 Version
상태는 분리"의 자연스러운 결과 — `concept` ↔ `concept_version`과 동형). 마이그레이션이 생성·역순
제거 순서로 순환 없이 왕복한다.

Lifecycle 불변식 시행(§7):
  PUBLISHED 행의 `payload`는 불변이고, PUBLISHED → DRAFT 전이는 금지된다. 이 두 규칙은 ORM이
  아니라 **DB BEFORE UPDATE 트리거**(`problem_version_immutability_guard`, alembic 리비전에서
  생성)가 유일 권위로 강제한다 — ORM에는 가짜 CHECK/이벤트 리스너를 만들지 않는다.

**운영 writer는 아직 없다.** 전이 실행(게이트)은 `l3/publish_gate.py`가 `ConceptVersion`에 대해서만
갖고 있다. 문항 발행 경로가 생기면 그 모듈이 이 ORM의 유일한 쓰기 자리가 되어야 한다(별도 태스크).
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
from whymath_backend.schema.problem_version import ProblemVersion as SchemaProblemVersion
from whymath_backend.schema.version_header import VersionStatus

# JSONB로 저장되는 필드 — 중첩 UUID/datetime이 안에 있으면 기본 `model_dump()`(python 모드)는
# raw 객체를 남겨 INSERT 시점에 `TypeError: Object of type UUID is not JSON serializable`로 죽는다
# (`concept_version.py` 주석 동일 — 엔진에 커스텀 json_serializer 없음). 이 6개만 mode="json"으로
# 다시 덤프한다. 스칼라 컬럼은 전용 SQLAlchemy 타입이 바인딩하므로 영향 없음.
_JSONB_FIELDS: tuple[str, ...] = ("change", "source", "governance", "integrity", "qa", "payload")


class ProblemVersion(Base):
    """Problem 버전 레코드 영속 ORM — Problem 좌석의 3번째 테이블(ARCH-31).

    `problem_id`는 `problem.problem_id`(UUID PK)를 참조한다. `previous_version_id`는 self-FK
    (버전 체인).
    """

    __tablename__ = "problem_version"

    # ===== 식별 =====
    version_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    problem_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("problem.problem_id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(
        sa.String(50), nullable=False, server_default=sa.text("'Problem'")
    )
    version_no: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(sa.String(50), nullable=False)

    # ===== Lifecycle (44 §7) =====
    status: Mapped[VersionStatus] = mapped_column(
        _pg_enum(VersionStatus, "problem_version_status_enum"),
        nullable=False,
        server_default=sa.text("'DRAFT'"),
    )
    # self-FK — 버전 체인(직전 버전). 최초 버전은 NULL.
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("problem_version.version_id")
    )

    # ===== VersionHeader 서브필드(§6.2) — JSONB 스냅숏 =====
    # SEC-06 전수 거버넌스(`test_jsonb_none_as_null_governance.py`) — 전 JSONB는
    # `none_as_null=True`(Python None → SQL NULL, JSON 스칼라 null 오계수 방지).
    change: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    source: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    governance: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    integrity: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    # 게이트 통과 기록(§9 QA 연결) — 기존 행 NULL = "게이트 기록 없음"(날조 금지).
    qa: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))

    # ===== payload — 이 버전 시점의 Problem 스냅숏(불변성 트리거 보호 대상) =====
    payload: Mapped[dict[str, object]] = mapped_column(JSONB(none_as_null=True), nullable=False)

    # ===== 운영 메타 =====
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    # ── 제약·인덱스 ──────────────────────────────────────────────────────
    __table_args__ = (
        sa.UniqueConstraint("problem_id", "version_no", name="uq_problem_version_problem_no"),
        # "현재 발행 버전 찾기" 조회 경로(problem_id + status='PUBLISHED') 지원.
        sa.Index("idx_problem_version_problem_status", "problem_id", "status"),
    )

    # ── 변환 헬퍼 ────────────────────────────────────────────────────────
    @classmethod
    def from_schema(cls, schema: SchemaProblemVersion) -> ProblemVersion:
        """검증된 schema → ORM(mapper 컬럼키 필터, `concept_version.py` 동일 패턴)."""
        data = schema.model_dump()
        for field in _JSONB_FIELDS:
            value = getattr(schema, field, None)
            if value is not None:
                data[field] = value.model_dump(mode="json")
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaProblemVersion:
        """ORM → schema(Pydantic 검증 복원 — JSONB dict가 서브모델로 재검증된다)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaProblemVersion.model_validate(
            drop_unset_nulls(data, SchemaProblemVersion, orm_cls=type(self))
        )


__all__ = ["ProblemVersion"]
