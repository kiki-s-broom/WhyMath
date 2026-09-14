"""ConceptVersion Pydantic 계약 — EOS-49 (44_eos_version_management.md §6.3).

Concept 엔티티(`concept` 테이블, `code`가 의미 ID)의 **버전 스냅숏**. `44
_eos_version_management.md` §6.1 Hybrid 구조의 "도메인별 버전 테이블" 절반이며, 공통
헤더는 `schema/version_header.py`의 `VersionHeader`가 단일 진실이다.

평탄화 판단(모듈 docstring에서 예고한 설계 선택): `VersionHeader`를 `header: VersionHeader`
로 중첩하지 않고 **필드를 그대로 끌어올렸다**. 이유는 이 코드베이스의 `from_schema`/
`to_schema` 관례(`schema.model_dump()` → ORM mapper 컬럼키로 교집합 필터, `concept.py`·
`curriculum_version.py` 선례) 때문이다 — 평탄화하면 `version_id`·`status`·`change` 등
각 필드가 ORM 컬럼명과 1:1 대응해 필터가 그대로 작동한다(중첩이면 `header.version_id`처럼
점 표기가 되어 같은 메커니즘이 깨진다). `VersionHeader` 자신은 필드 계약의 정본으로 남고,
이 클래스는 그 필드를 재선언하지 않고 **동일한 서브모델 타입(`VersionChange` 등)을 그대로
가져와 재사용**한다(계약 이중 정의 방지).

Principle 1(Entity ID ≠ Version ID): `concept_id: str`가 `VersionHeader.entity_id`에
대응하는 *의미 ID*다 — `Concept.code`(`math.<area>.<slug>` 형식, 이 코드베이스 실측으로는
`{TRACK}-{AREA}-{NNN}` 재-ID 형식)를 참조하며, `Concept.concept_id`(UUID 대리키)가
**아니다**(모듈 docstring·태스크 acceptance ① 명시). `version_id`는 이 버전 레코드 자체의
별도 UUID다.

payload(`ConceptVersionPayload`)는 **Concept 전체를 복제하지 않는다** — Concept Purity가
이미 노드에 허용한 정체성/특성 필드만 담는다(구축 플레이북 8대 구조 원칙 ①). renderer·
curriculum·embedding 필드는 여기에도 넣지 않는다(이미 Overlay로 외부화된 것들 — 되돌리지
않는다).

컨벤션(`schema/concept.py`·`schema/curriculum_version.py` 답습):
  - `ConfigDict(extra="forbid", use_enum_values=True, str_strip_whitespace=True)`.
  - enum은 `schema/enums.py` 재사용(`ConceptLevel`·`CognitiveType`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.schema.enums import CognitiveType, ConceptLevel
from whymath_backend.schema.version_header import (
    VersionChange,
    VersionGovernance,
    VersionIntegrity,
    VersionSource,
    VersionStatus,
)


# ──────────────────────────────────────────────────────────────────────────
# ConceptVersionPayload — Concept Purity가 허용하는 정체성/특성 필드만
# ──────────────────────────────────────────────────────────────────────────
class ConceptVersionPayload(BaseModel):
    """한 버전 시점의 Concept 스냅숏 — `schema.Concept`의 *정체성/특성* 필드만 포함.

    포함(Concept Purity가 노드에 이미 허용한 축 — `schema/concept.py` 참조):
      `name_ko`·`name_en`·`level`·`parent_concept_id`·`aliases`·`is_signature_korean`·
      `cognitive_type`·`behavior_skills`·`intrinsic_difficulty`·`exam_frequency`·
      `weight_in_curriculum`.

    제외(의도적 — 8대 구조 원칙에 따라 이미 외부화됨, 여기서도 재내장하지 않는다):
      renderer(`recommended_visual_styles` → Overlay `concept_visual_style`)·
      curriculum(교육과정 매핑 → `CurriculumEntry` Overlay)·embedding·오개념·본문 3종
      (`description`·`formal_definition`·`intuitive_explanation` — Phase 1b redaction).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    name_ko: str = Field(..., description="한글 개념명(스냅숏 시점).", max_length=200)
    name_en: str | None = Field(
        default=None, description="영문 개념명(스냅숏 시점).", max_length=200
    )
    level: ConceptLevel = Field(..., description="개념 계층(스냅숏 시점).")
    parent_concept_id: uuid.UUID | None = Field(
        default=None, description="상위 개념 FK(스냅숏 시점 — Concept.concept_id UUID)."
    )
    aliases: list[str] = Field(default_factory=list, description="옛 키 별칭(스냅숏 시점).")
    is_signature_korean: bool = Field(
        default=False, description="한국 수능 특유 개념 여부(스냅숏 시점)."
    )
    cognitive_type: list[CognitiveType] = Field(
        default_factory=list, description="인지 유형 배열(스냅숏 시점)."
    )
    behavior_skills: list[str] = Field(
        default_factory=list, description="이 개념이 exercise하는 스킬 목록(스냅숏 시점)."
    )
    intrinsic_difficulty: float | None = Field(
        default=None, description="개념 자체 난이도 1-5(스냅숏 시점).", ge=1.0, le=5.0
    )
    exam_frequency: float | None = Field(
        default=None, description="시험 출제 빈도 0-1(스냅숏 시점).", ge=0.0, le=1.0
    )
    weight_in_curriculum: float | None = Field(
        default=None, description="교육과정 가중치 0-1(스냅숏 시점).", ge=0.0, le=1.0
    )


# ──────────────────────────────────────────────────────────────────────────
# ConceptVersion — VersionHeader 평탄화 + concept_id(의미 ID) + payload
# ──────────────────────────────────────────────────────────────────────────
class ConceptVersion(BaseModel):
    """Concept 버전 레코드 — `VersionHeader`(§6.2) 평탄화 + `concept_id`(§6.3) + payload.

    `entity_type`은 이 도메인 버전 테이블에서 항상 `"Concept"`로 고정한다(다른 값을
    넣을 이유가 없다 — 상수 취급이나 계약상 자유 문자열로 열어 둔다, `VersionHeader`
    원 계약과 동형).

    Lifecycle 불변식(PUBLISHED payload 불변·PUBLISHED→DRAFT 금지)은 **이 Pydantic
    모델이 강제하지 않는다** — 단일 트랜잭션 내 상태 전이 검증은 DB 트리거(ORM 계층
    아래)가 유일 권위다(`db/models/concept_version.py` 참조). Pydantic은 구조만 검증한다.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    version_id: uuid.UUID = Field(
        default_factory=uuid4,
        description="버전 PK(UUID) — Concept.concept_id(엔티티 UUID)와 별개.",
    )
    concept_id: str = Field(
        ...,
        description="소속 Concept의 의미 ID(Concept.code, 'math.<area>.<slug>' 형식). "
        "Concept.concept_id(UUID 대리키)가 아니다.",
    )
    entity_type: str = Field(
        default="Concept",
        description="엔티티 유형 — 이 도메인 테이블에서는 항상 'Concept'.",
    )
    version_no: int = Field(..., description="concept_id 내 버전 순번(1부터 증가).", ge=1)
    schema_version: str = Field(..., description="payload가 따르는 스키마 버전 태그.")
    status: VersionStatus = Field(
        default=VersionStatus.DRAFT, description="생명주기 상태(44 §7) — 기본 DRAFT."
    )
    previous_version_id: uuid.UUID | None = Field(
        default=None, description="직전 버전의 version_id(self-FK, 최초 버전이면 None)."
    )
    change: VersionChange = Field(default_factory=VersionChange, description="변경 성격.")
    source: VersionSource = Field(default_factory=VersionSource, description="원천 정보.")
    governance: VersionGovernance = Field(
        default_factory=VersionGovernance, description="검토·승인 이력."
    )
    integrity: VersionIntegrity = Field(
        default_factory=VersionIntegrity, description="무결성 검증 정보."
    )
    payload: ConceptVersionPayload = Field(..., description="이 버전 시점의 Concept 스냅숏.")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="레코드 생성 시각.")
    published_at: datetime | None = Field(
        default=None, description="PUBLISHED로 전이된 시각(발행 전이면 None)."
    )


__all__ = ["ConceptVersionPayload", "ConceptVersion"]
