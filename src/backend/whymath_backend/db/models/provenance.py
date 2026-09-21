"""도메인8 Provenance ORM 모델 (SQLAlchemy 2.0 영속 레이어).

설계 정본: `schemas/v1.0/schema_v1.0.md` §10.1(`content_provenance`·`generation_log` DDL)·
§10.1 인덱스. 이 ORM은 `schema/provenance.py`(Pydantic, 검증·API)와 *별도*로 세운 영속
매핑이며 `from_schema`/`to_schema` 변환 헬퍼가 둘을 잇는다(슬라이스 1 `problem.py` 동일 패턴).

타입 매핑(DDL → ORM, problem.py 선례 그대로):
  - `UUID PRIMARY KEY` → `server_default gen_random_uuid()`(problem.py 모든 UUID PK 선례).
  - `UUID REFERENCES problem`(nullable) → `uuid.UUID|None` + `ForeignKey("problem.problem_id")`.
    problem_id·parent_problem_id 둘 다 메인의 problem 테이블 참조(문자열 FK 타깃).
  - `provenance_id UUID REFERENCES content_provenance`(generation_log) →
    `ForeignKey("content_provenance.provenance_id")`(이 배치 내부 FK).
  - `approved_by UUID`·`prompt_template_id UUID`는 DDL에 `REFERENCES`가 *없어* FK 아님(plain UUID).
  - `source_type_enum`/`generation_type_enum`/`license_enum` → `_pg_enum(...)`(values_callable).
  - 자유형 `JSONB`(original_reference·transformation·… ) → `JSONB`(nullable, schema는 Optional).
  - `DECIMAL(8,4)`(cost_usd) → `sa.Numeric(8, 4)`.
  - 인덱스(§10.1 `CREATE INDEX`) → `__table_args__`.

법적 메모: license/generation_type 차원의 저작권 불변식(원본 그대로 차단·EBS_LICENSED
차단·메타 전용 출처 규칙)은 `schema.ContentProvenance`의 `@model_validator`가 강제한다 —
ORM에는 컬럼만 두고 가짜 DB CHECK를 만들지 않는다(problem.py 본문 미보유 불변식과 동형).
변환 헬퍼가 schema를 거치므로 자연히 시행된다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.db.models._orm_enum import _pg_enum
from whymath_backend.schema.enums import GenerationType, LicenseType, SourceType
from whymath_backend.schema.provenance import ContentProvenance as SchemaContentProvenance
from whymath_backend.schema.provenance import GenerationLog as SchemaGenerationLog


# ──────────────────────────────────────────────────────────────────────────
# 핵심: ContentProvenance (§10.1 content_provenance 테이블)
# ──────────────────────────────────────────────────────────────────────────
class ContentProvenance(Base):
    """콘텐츠 변형·생성 이력 영속 ORM — §10.1 `content_provenance`(감사 추적).

    법적 불변식(ORIGINAL 차단·EBS_LICENSED 차단·메타 전용 출처 규칙)은
    `schema.ContentProvenance`가 강제한다 — 이 ORM에는 컬럼만 두고 DB CHECK를 만들지 않는다
    (모듈 docstring·problem.py 방침).

    FK 판단: `problem_id`·`parent_problem_id`는 `REFERENCES problem`(nullable FK), `approved_by`는
    DDL에 `REFERENCES`가 없으므로 plain UUID(FK 아님).
    """

    __tablename__ = "content_provenance"

    # ===== 기본 식별 =====
    provenance_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    problem_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("problem.problem_id")
    )

    # ===== 원본 출처 =====
    original_source: Mapped[SourceType | None] = mapped_column(
        _pg_enum(SourceType, "source_type_enum")
    )
    original_reference: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    # ===== 변형·생성 단계 =====
    generation_type: Mapped[GenerationType | None] = mapped_column(
        _pg_enum(GenerationType, "generation_type_enum")
    )
    transformation: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    parent_problem_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("problem.problem_id")
    )
    transformation_pipeline: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    # ===== 검증·승인 =====
    auto_validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    human_review: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    approved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # DDL에 REFERENCES 없음 → plain UUID(FK 아님).
    approved_by: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)

    # ===== 저작권·법적 메타데이터 =====
    license: Mapped[LicenseType | None] = mapped_column(_pg_enum(LicenseType, "license_enum"))
    copyright_notice: Mapped[str | None] = mapped_column(sa.Text)
    usage_restrictions: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    # ===== 운영 메타 =====
    created_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    # ── 인덱스 (§10.1 CREATE INDEX) ──
    __table_args__ = (
        sa.Index("idx_provenance_problem", "problem_id"),
        sa.Index("idx_provenance_parent", "parent_problem_id"),
        sa.Index("idx_provenance_source", "original_source"),
    )

    # ── 변환 헬퍼 (schema↔db seam, problem.py 패턴) ──────────────────────
    @classmethod
    def from_schema(cls, schema: SchemaContentProvenance) -> ContentProvenance:
        """검증된 `schema.ContentProvenance` → 영속 ORM(mapper 컬럼키 필터).

        법적 불변식은 schema가 이미 통과시켰으므로(유효 인스턴스만 진입) ORM에서 재검증하지
        않는다(problem.py 방침).
        """
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaContentProvenance:
        """영속 ORM → `schema.ContentProvenance`(Pydantic 검증 복원 — 불변식 안전망)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaContentProvenance.model_validate(data)


# ──────────────────────────────────────────────────────────────────────────
# 보조: GenerationLog (§10.1 generation_log 테이블)
# ──────────────────────────────────────────────────────────────────────────
class GenerationLog(Base):
    """LLM 생성 호출 이력 영속 ORM — §10.1 `generation_log`(비용·품질 분석).

    FK 판단: `problem_id`→problem, `provenance_id`→content_provenance(이 배치 내부 FK).
    `prompt_template_id`는 DDL에 `REFERENCES`가 없으므로 plain UUID(FK 아님). 검증 불변식 없음
    (로그 레코드는 관대하게 적재 — schema와 동일).
    """

    __tablename__ = "generation_log"

    # EOS-55 메모: 재현 좌석 5컬럼(prompt_version·seed·input_sha256·input_snapshot·
    # cu_slug)이 추가되면서 schema.GenerationLog에 스냅샷↔해시 정합 validator가 생겼다 —
    # to_schema()가 model_validate를 거치므로 DB 읽기도 그 무결성 봉인을 지난다.

    log_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    problem_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("problem.problem_id")
    )
    provenance_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("content_provenance.provenance_id")
    )
    model_name: Mapped[str | None] = mapped_column(sa.String(64))
    # DDL에 REFERENCES 없음 → plain UUID(FK 아님).
    prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    input_tokens: Mapped[int | None] = mapped_column(sa.Integer)
    output_tokens: Mapped[int | None] = mapped_column(sa.Integer)
    # 프롬프트 캐시 2종(EOS-99) — nullable·server_default 없음(구 행 NULL=미기록·소급 날조
    # 금지, run_id/EOS-55 재현 좌석과 같은 방침). 여기 컬럼이 없으면 `from_schema`의
    # mapped_keys 필터가 값을 **조용히 버려** DB 경로만 캐시 축을 잃는다(침묵 실패 금지).
    cache_read_input_tokens: Mapped[int | None] = mapped_column(sa.Integer)
    cache_creation_input_tokens: Mapped[int | None] = mapped_column(sa.Integer)
    cost_usd: Mapped[float | None] = mapped_column(sa.Numeric(8, 4))
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer)
    success: Mapped[bool | None] = mapped_column(sa.Boolean)
    error_detail: Mapped[str | None] = mapped_column(sa.Text)
    generated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    # ── 생성 Run 재현 좌석 (EOS-55) — 전부 nullable·server_default 없음(구 행 NULL=미기록).
    # 값 의미·불변식(스냅샷↔해시 정합)은 schema.GenerationLog가 강제한다(본 파일 방침:
    # ORM은 컬럼만 — from_schema/to_schema seam이 검증을 경유).
    prompt_version: Mapped[str | None] = mapped_column(sa.String(128))
    # BigInteger 좌석 — 실제 추출 범위는 [0, 2**31-1](llama.cpp 샘플러 시드가 uint32라
    # 좌석보다 좁게 뽑는다·`l3/generation_seed`). EOS-73부터 LOCAL 경로는 값이 실리고,
    # 클라우드(seed 파라미터 부재)·호출 없는 항목은 NULL=미기록이다(날조 금지).
    seed: Mapped[int | None] = mapped_column(sa.BigInteger)
    input_sha256: Mapped[str | None] = mapped_column(sa.String(64))
    input_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # 생산 CU 조인 정체성(#912 P1-2) — 코퍼스 키·review_timer cu_slug와 동일 산식(폭 128
    # schema 강제 동형). 정체성 없는 종단(파싱 실패·pregenerate 시드)은 NULL=미기록.
    cu_slug: Mapped[str | None] = mapped_column(sa.String(128))
    # 리콜 조인 축(EOS-97) — "이 회차로 만든 산출물"을 기계가 특정하는 키. 회차 개념이
    # 없는 경로(pregenerate 단발 인제스트)는 NULL=미기록(날조 금지·EOS-55 좌석 동형).
    run_id: Mapped[str | None] = mapped_column(sa.String(64))

    # ── 관측 좌석(EOS-112) — nullable·server_default 없음(구 행 NULL=미기록, 위 좌석 동형).
    # 폭 128은 `model_name`(64)보다 넓다: 이쪽은 **외부 응답이 정하는 값**이라 공급사가
    # 접미(`:free`·날짜 버전)를 붙여 돌려줄 수 있다. schema가 같은 폭을 강제한다.
    served_model: Mapped[str | None] = mapped_column(sa.String(128))
    # 계측 없는 경로는 NULL이다(0이 아니다) — 0으로 채우면 Anthropic·Ollama 회차가
    # '재시도 0회 실측'처럼 보여 미계측과 구분되지 않는다.
    retries: Mapped[int | None] = mapped_column(sa.Integer)

    # ── 인덱스 (§10.1 CREATE INDEX) ──
    # idx_generation_run_id: 리콜은 회차 단위 선별이 주 질의라 인덱스를 둔다(EOS-97).
    __table_args__ = (
        sa.Index("idx_generation_problem", "problem_id"),
        sa.Index("idx_generation_run_id", "run_id"),
    )

    @classmethod
    def from_schema(cls, schema: SchemaGenerationLog) -> GenerationLog:
        """검증된 `schema.GenerationLog` → 영속 ORM(schema↔db seam)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaGenerationLog:
        """영속 ORM → `schema.GenerationLog`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaGenerationLog.model_validate(data)


__all__ = ["ContentProvenance", "GenerationLog"]
