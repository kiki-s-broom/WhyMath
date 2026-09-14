"""공통 버전 헤더(VersionHeader) Pydantic 계약 — EOS-49.

설계 정본: `docs/architecture/44_eos_version_management.md` §6.1(Hybrid 구조)·§6.2(공통
버전 헤더)·§7(Lifecycle 상태 머신). 판 관리(version management)는 도메인마다 제각각의
버전 시스템을 만들지 않고 *공통 헤더 계약 + 도메인별 버전 테이블*의 Hybrid로 처리한다
(§6.1 — Unified Entity 슈퍼테이블은 `011_1`에서 보류됨).

이 파일은 그 **공통 헤더**만 담는다 — 재사용 대상은 `ConceptVersion`(이 슬라이스,
`schema/concept_version.py`)과 후속 `ProblemVersion`(`ARCH-31`)이다. 도메인별 payload는
각자의 스키마 파일이 소유한다(§6.3).

Principle 1(Entity ID ≠ Version ID): `entity_id`는 그 엔티티의 *의미 ID*(예: Concept의
`code` — `math.<area>.<slug>`)이고, `version_id`는 이 버전 레코드 자체의 UUID다. 하나의
entity_id에 여러 version_id가 매달린다(§6.2 예시: "Problem PRB-001234 v7").

Lifecycle(§7, 상태 6종): `DRAFT → IN_REVIEW → APPROVED → PUBLISHED → DEPRECATED → RETIRED`.
**PUBLISHED → DRAFT는 금지**다(이미 발행된 버전은 수정 불가 — 수정하려면 clone해 새
DRAFT vN+1을 만든다). 이 계약은 상태 값의 *어휘*만 정의한다 — 전이 규칙 자체의 강제는
도메인별 ORM/DB 트리거 소관이다(예: `db/models/concept_version.py` + alembic 트리거).

컨벤션(`schema/curriculum_version.py`·`schema/concept.py` 답습):
  - `ConfigDict(extra="forbid", use_enum_values=True, str_strip_whitespace=True)`.
  - 공유 베이스 클래스 없음(각 모델 독립) — 이 파일 안의 서브모델(`VersionChange` 등)도
    동일 컨벤션을 개별적으로 갖는다.

범위 축소(스코프 규율 — 이 태스크의 acceptance ④): Release Snapshot·VersionContext(§10·§13,
Phase 2)·Edge versioning은 이 계약에 넣지 않는다. `VersionDependency`(§8.2)도 넣지 않는다
— 이 헤더는 "이 버전이 무엇인가"만 기술하고 "이 버전이 무엇에 의존하는가"는 별도 축이다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


# ──────────────────────────────────────────────────────────────────────────
# Lifecycle 상태 (44_eos_version_management.md §7 — 6단계)
# ──────────────────────────────────────────────────────────────────────────
class VersionStatus(str, Enum):
    """버전 생명주기 상태 — §7 상태 머신 6종.

    전이 규칙(§7 다이어그램): `DRAFT → IN_REVIEW → APPROVED → PUBLISHED → DEPRECATED →
    RETIRED`(IN_REVIEW에서 반려되면 DRAFT로 되돌아갈 수 있음 — request changes). **단
    PUBLISHED에 도달한 뒤로는 DRAFT로 돌아갈 수 없다** — "이미 Published 버전을 다시
    수정 불가 상태로 되돌리지 않는다. 대신 Published 버전을 clone해 Draft vN+1을
    만든다"(§7). 이 금지의 기계 시행은 도메인 ORM/DB 트리거 소관(예: `concept_version`
    BEFORE UPDATE 트리거 — `db/models/concept_version.py` docstring 참조).

    값(영어) — `44_eos_version_management.md` §6.2 원문 그대로.
    """

    DRAFT = "DRAFT"
    """초안 — 편집 중, 아직 검토에 제출되지 않음."""

    IN_REVIEW = "IN_REVIEW"
    """검토 중 — 제출되어 리뷰어의 승인/반려를 기다림."""

    APPROVED = "APPROVED"
    """승인됨 — 검토를 통과했으나 아직 발행 전."""

    PUBLISHED = "PUBLISHED"
    """발행됨 — 학생/서빙 경로에 노출. 이 상태 도달 후 payload는 불변(immutable)."""

    DEPRECATED = "DEPRECATED"
    """폐기 예정 — 여전히 조회 가능하나 신규 참조를 권장하지 않음."""

    RETIRED = "RETIRED"
    """은퇴 — 더 이상 서빙되지 않음(Soft Delete — §7 "DELETE를 피하고 상태로 처리")."""


# ──────────────────────────────────────────────────────────────────────────
# 서브모델 4종 (§6.2 VersionHeader 필드 그룹 — 각각 최소 구성)
# ──────────────────────────────────────────────────────────────────────────
class VersionChange(BaseModel):
    """이 버전이 만들어진 변경의 성격 — §6.2 `change: VersionChange`.

    전부 선택 필드다(최초 버전(v1)은 "변경"이 아니라 "생성"이라 채울 내용이 없을 수 있음).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    change_type: str | None = Field(
        default=None,
        description="변경 유형(자유 텍스트 — 예: 'content_fix'·'difficulty_recalibration').",
    )
    impact: str | None = Field(
        default=None,
        description="변경의 영향 범위/정도(자유 텍스트).",
    )
    reason: str | None = Field(
        default=None,
        description="변경 사유(자유 텍스트).",
    )
    ticket_id: str | None = Field(
        default=None,
        description="이 변경을 추적하는 티켓/태스크 ID(예: 'EOS-49').",
    )


class VersionSource(BaseModel):
    """이 버전이 유래한 원천 — §6.2 `source: VersionSource`."""

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    source_ids: list[str] = Field(
        default_factory=list,
        description="원천 식별자 목록(예: 코퍼스 source_id·외부 참조).",
    )
    derived_from: uuid.UUID | None = Field(
        default=None,
        description="이 버전이 파생된 다른 버전의 version_id(있다면).",
    )


class VersionGovernance(BaseModel):
    """이 버전의 검토·승인 이력 — §6.2 `governance: VersionGovernance`."""

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    created_by: str | None = Field(default=None, description="작성자 식별자.")
    reviewed_by: str | None = Field(default=None, description="검토자 식별자.")
    approved_by: str | None = Field(default=None, description="승인자 식별자.")


class VersionIntegrity(BaseModel):
    """이 버전의 무결성 검증 정보 — §6.2 `integrity: VersionIntegrity`."""

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    content_hash: str | None = Field(
        default=None,
        description="payload 내용 해시(변경 탐지·재현성 — 알고리즘은 도메인이 정함).",
    )


# ──────────────────────────────────────────────────────────────────────────
# 공통 버전 헤더 (§6.2 원문 필드 목록)
# ──────────────────────────────────────────────────────────────────────────
class VersionHeader(BaseModel):
    """도메인 공통 버전 헤더 — §6.2 `VersionHeader` 원문 그대로.

    이 모델은 *단독으로 저장되지 않는다* — 도메인별 버전 모델(`ConceptVersion` 등)이 이
    필드들을 (중첩 또는 평탄화로) 구성에 포함한다. `schema/concept_version.py`는 ORM
    JSONB 컬럼과의 매핑을 단순화하기 위해 **평탄화**를 택했다(모듈 docstring 참조) —
    이 클래스 자체는 필드 계약의 단일 진실 원천으로 남는다.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    version_id: uuid.UUID = Field(
        default_factory=uuid4,
        description="버전 PK(UUID) — Entity ID와 별개(Principle 1: Entity ID ≠ Version ID).",
    )
    entity_id: str = Field(
        ...,
        description="이 버전이 속한 엔티티의 논리적(의미) ID"
        "(예: Concept.code, Problem.problem_id 문자열 표현).",
    )
    entity_type: str = Field(
        ...,
        description="엔티티 유형 — 'Problem' | 'Concept' | ... "
        "(도메인별 버전 테이블이 상수로 고정).",
    )
    version_no: int = Field(
        ...,
        description="이 entity_id 내에서 몇 번째 버전인가(1부터 증가).",
        ge=1,
    )
    schema_version: str = Field(
        ...,
        description="payload가 따르는 스키마 버전(예: 'concept-schema@1').",
    )
    status: VersionStatus = Field(
        default=VersionStatus.DRAFT,
        description="생명주기 상태(§7) — 기본 DRAFT.",
    )
    previous_version_id: uuid.UUID | None = Field(
        default=None,
        description="직전 버전의 version_id(최초 버전이면 None).",
    )
    change: VersionChange = Field(
        default_factory=VersionChange,
        description="이 버전을 만든 변경의 성격.",
    )
    source: VersionSource = Field(
        default_factory=VersionSource,
        description="이 버전의 원천 정보.",
    )
    governance: VersionGovernance = Field(
        default_factory=VersionGovernance,
        description="검토·승인 이력.",
    )
    integrity: VersionIntegrity = Field(
        default_factory=VersionIntegrity,
        description="무결성 검증 정보.",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="레코드 생성 시각.",
    )
    published_at: datetime | None = Field(
        default=None,
        description="PUBLISHED로 전이된 시각(아직 발행 전이면 None).",
    )


__all__ = [
    "VersionStatus",
    "VersionChange",
    "VersionSource",
    "VersionGovernance",
    "VersionIntegrity",
    "VersionHeader",
]
