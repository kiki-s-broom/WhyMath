"""Admin CMS BFF — `/v1/admin/cms/*` 콘텐츠 운영 표면 (P3-12 · 04 §2 원칙2).

개발자 없이 콘텐츠팀이 12종 작업(교육과정·개념·스킬·문항·풀이·오개념·교수전략·설명/힌트·검수·
변경이력·배포·롤백)을 하는 서버 쪽이다. 두 갈래로 나뉜다:

**① 개념 — 버전 워크플로우 경유** (`l3/publish_gate.py`가 유일한 쓰기 자리)
  - GET  /concepts · /concepts/{id}                : 목록·상세(+관계 **읽기 전용**)
  - POST /concepts/{id}/drafts                      : 새 DRAFT 판 생성(편집 = 새 판, 44 §1 원칙 3)
  - GET  /concepts/{id}/versions · /versions/{id}   : 변경이력(판 목록·상세)
  - POST /versions/{id}/transitions                 : 제출·검토·승인·발행·폐기·은퇴(전이표가 정본)
  - POST /concepts/{id}/rollback                    : 직전 발행본으로 복구
  **이 모듈은 `ConceptVersion` ORM을 import하지 않고 발행 포인터를 쓰지 않는다** — 둘 다 AST 동결
  (`test_publish_gate_enforcement` R1·R2)이 이 파일을 포함한 운영 패키지 전체에서 막는다.

**② 개념 외 — 허용 목록 제자리 편집** (`api/admin_cms_resources.py`가 선언)
  - GET /{resource} · /{resource}/items/{pk}        : 목록·상세
  - PATCH /{resource}/items/{pk}                    : 허용 필드만 수정(상태·발행 컬럼은 거부)
  - POST  /{resource}/items/{pk}/review             : 텍스트 검수 표지 올리기/내리기(검수 권한)
  버전 테이블이 없는 리소스라(문항 버전 ARCH-31 미착수·Phase 3 신규 Entity 금지) 워크플로우 대신
  **검수 축을 우회하지 않는** 규칙을 둔다: 승인된 문항은 먼저 격리해야 수정되고, 수정은 검수 표지를
  안전한 방향(내림)으로만 되돌린다.

**쓰기 권한은 서버가 검사한다** — 화면에서 버튼을 숨기는 것은 보안이 아니다. 모든 쓰기 라우트는
레지스트리 파생 모듈 가드(`require_module_roles`)에 더해 **권한(`CmsCapability`)** 을 DB 접근 전에
검사한다(`schema/cms_access.py`가 역할→권한 정본). 거부는 부작용 0이다.

모든 쓰기는 같은 트랜잭션에 감사 1행(`record_content_mutation_audit`)을 합류시키고 commit은 1회다.

`from __future__ import annotations`를 쓰지 않는다 — 리소스별 가드를 루프에서 만들어 등록하므로
지역 `Annotated` 별칭을 FastAPI가 평가 시점에 해석할 수 있어야 한다(문자열 어노테이션은 모듈
전역에서만 해석된다).

7계층: L5 `api`의 BFF. 수학 로직 0 — 전이 규칙은 `schema/version_lifecycle`,
검증은 `l3/publish_gate`.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api._rate_limit import _client_ip
from whymath_backend.api.admin_cms_resources import (
    RESOURCES,
    REVIEW_STATUS_AI_ESTIMATED,
    REVIEW_STATUS_REVIEWED,
    FieldError,
    ResourceSpec,
    apply_changes,
    audit_resource_id,
    get_resource,
    parse_pk,
    to_jsonable,
    validate_changes,
)
from whymath_backend.api.admin_module_registry import get_module, require_module_roles
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.cms_edit_marker import mark_cms_edited
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.concept import Concept, ConceptEdge
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.skill_node import SkillNode
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l3 import publish_gate as gate
from whymath_backend.privacy.audit import record_content_mutation_audit
from whymath_backend.schema.cms_access import (
    ROLLBACK_CAPABILITY,
    CmsCapability,
    capabilities_of,
    has_capability,
    required_capability,
)
from whymath_backend.schema.concept_version import ConceptVersion as SchemaConceptVersion
from whymath_backend.schema.concept_version import ConceptVersionPayload
from whymath_backend.schema.enums import (
    AuditEventKind,
    PrivacyAuditAction,
    PrivacyAuditResourceType,
    ReviewStatus,
    Role,
)
from whymath_backend.schema.version_header import TransitionAction, VersionChange, VersionStatus
from whymath_backend.schema.version_lifecycle import UndefinedTransitionError, allowed_actions

router = APIRouter(prefix="/v1/admin/cms", tags=["admin-cms"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

#: 개념 payload가 따르는 스키마 버전 태그 — `create_draft`가 형식을 검사한다(`<이름>@<정수>`).
CMS_PAYLOAD_SCHEMA_VERSION = "concept-payload@1"

# 모듈별 가드 — 레지스트리에서 *파생*된 역할을 쓴다(`require_role` 직접 사용 금지).
RequireKnowledgeGraph = Annotated[UserProfile, Depends(require_module_roles("knowledge_graph"))]
RequireContentVersion = Annotated[UserProfile, Depends(require_module_roles("content_version"))]
RequireDeployment = Annotated[UserProfile, Depends(require_module_roles("deployment"))]
RequireContentLibrary = Annotated[UserProfile, Depends(require_module_roles("content_library"))]
RequireCurriculum = Annotated[UserProfile, Depends(require_module_roles("curriculum"))]
RequireMisconception = Annotated[UserProfile, Depends(require_module_roles("misconception"))]
RequirePedagogy = Annotated[UserProfile, Depends(require_module_roles("pedagogy_pack"))]


# ── 오류·권한 도우미 ───────────────────────────────────────────────────────────────


def _problem(status_code: int, code: str, message: str, **extra: object) -> HTTPException:
    """오류 본문을 `{code, message, ...}`로 통일한다 — 화면은 문구가 아니라 `code`로 분기한다."""
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message, **extra}
    )


def _require(user: UserProfile, capability: CmsCapability) -> None:
    """권한이 없으면 403 — **DB 접근 전에** 부른다(거부는 부작용·정보 노출 0)."""
    if not has_capability(user.role, capability):
        raise _problem(
            status.HTTP_403_FORBIDDEN,
            "capability_required",
            f"이 작업에는 '{capability.value}' 권한이 필요합니다.",
            capability=capability.value,
        )


def _actor(user: UserProfile) -> str:
    """거버넌스·게이트 기록의 행위자 식별자 — 사용자 UUID(이메일·닉네임 등 PII는 싣지 않는다)."""
    return str(user.user_id)


def _field_problem(exc: FieldError) -> HTTPException:
    return _problem(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        exc.code,
        exc.message,
        field=exc.field,
    )


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime | date) else None


# ── 응답·요청 모델 ──────────────────────────────────────────────────────────────────


class CmsFieldMeta(BaseModel):
    """편집 가능한 필드 1개의 화면용 메타 — 서버 선언을 그대로 내린다(화면은 규칙을 복제 안 함)."""

    model_config = ConfigDict(frozen=True)

    name: str
    label_ko: str
    kind: str
    max_length: int | None = None
    choices: tuple[str, ...] | None = None
    nullable: bool = False


class CmsResourceMeta(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    label_ko: str
    # 이 리소스를 소유한 콘솔 모듈의 화면 경로 — 레지스트리에서 파생한다. 화면은 모듈 id·경로를
    # 코드에 적지 않고(하드코딩 nav 금지) 자기 경로와 이 값을 맞춰 어떤 리소스를 그릴지 정한다.
    route: str
    # 목록 행·상세 경로에서 대상을 가리키는 기본키 컬럼 이름 — 화면이 "첫 컬럼이 키겠지"라고
    # 추정하지 않도록 서버가 명시로 내린다.
    pk_column: str
    # 변경이력 조회(`GET /audit?resource_type=`)에 쓰는 종류 — 읽기 전용 리소스는 쓰기가 없어 None.
    # 화면이 "리소스 키 = 감사 종류"라고 암묵 가정하지 않도록 서버가 명시로 내린다.
    audit_type: str | None
    list_columns: tuple[str, ...]
    detail_columns: tuple[str, ...]
    fields: tuple[CmsFieldMeta, ...]
    reviewable: bool
    read_only: bool


class CmsResourcesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    resources: tuple[CmsResourceMeta, ...]
    capabilities: tuple[str, ...] = Field(..., description="호출자가 가진 CMS 권한.")


class CmsListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource: str
    columns: tuple[str, ...]
    items: tuple[dict[str, object], ...]
    total: int
    limit: int
    offset: int


class CmsDetailResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource: str
    pk: str
    values: dict[str, object]
    fields: tuple[CmsFieldMeta, ...] = Field(..., description="호출자가 지금 고칠 수 있는 필드.")
    can_review: bool
    edit_blocked_reason: str | None = Field(None, description="편집이 막힌 사유(없으면 None).")


class CmsEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: dict[str, Any] = Field(..., description="필드 → 새 값. 허용 목록 밖은 422.")


class CmsEditResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    changed: tuple[str, ...]
    server_reset: tuple[str, ...] = Field(..., description="서버가 안전한 방향으로 되돌린 표지.")
    detail: CmsDetailResponse


class CmsReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["reviewed", "needs_review"]


class CmsReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    changed: bool
    review_status: str


class CmsConceptRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    concept_id: uuid.UUID
    code: str
    name_ko: str
    level: str
    has_published_version: bool


class CmsConceptListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[CmsConceptRow, ...]
    total: int
    limit: int
    offset: int


class CmsEdgeRow(BaseModel):
    """관계 1건 — **읽기 전용**. 원천 정본이 `graph.json`이라 CMS는 DB 엣지를 고치지 않는다."""

    model_config = ConfigDict(frozen=True)

    other_concept_id: uuid.UUID
    other_code: str
    other_name_ko: str
    edge_type: str


class CmsConceptDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    concept_id: uuid.UUID
    code: str
    live: dict[str, object] = Field(..., description="살아있는 개념 행의 payload 필드(읽기 전용).")
    # 필드 이름이 `published_version_id`인 이유: AST 동결(R2)이 `current_published_version_id`라는
    # 이름의 키워드 인자를 모듈 밖 어디서든 "포인터 쓰기"로 읽는다. 이 필드는 읽기 전용 응답이지만
    # 스캐너는 문법만 보므로, 이름을 달리해 규칙을 면제 없이 그대로 지킨다.
    published_version_id: uuid.UUID | None
    latest_version_no: int | None
    incoming: tuple[CmsEdgeRow, ...] = Field(..., description="이 개념을 선행으로 삼는 관계.")
    outgoing: tuple[CmsEdgeRow, ...] = Field(..., description="이 개념이 선행으로 삼는 관계.")
    can_edit: bool


class CmsDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: dict[str, Any] = Field(
        default_factory=dict,
        description="payload 필드 → 새 값. 비우면 현재 기준 그대로 새 초안을 만든다.",
    )
    reason: str | None = Field(None, max_length=500, description="변경 사유(이력에 남는다).")
    ticket_id: str | None = Field(None, max_length=64)


class CmsGateRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    gate: str
    action: str
    judged_by: str
    judged_at: str
    checks: tuple[str, ...]
    content_hash: str


class CmsVersionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    version_id: uuid.UUID
    concept_code: str
    version_no: int
    status: str
    created_by: str | None
    reviewed_by: str | None
    approved_by: str | None
    content_hash: str | None
    change_reason: str | None
    created_at: str | None
    published_at: str | None
    allowed_actions: tuple[str, ...] = Field(
        ..., description="전이표가 허용하고 **호출자 권한으로 실행할 수 있는** 전이."
    )


class CmsVersionDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: CmsVersionSummary
    payload: dict[str, object]
    gate_records: tuple[CmsGateRecord, ...]


class CmsTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(..., max_length=32, description="전이 이름(전이표 어휘).")
    expected_status: VersionStatus = Field(
        ..., description="화면이 본 상태 — 그사이 바뀌었으면 409(stale_status)."
    )


class CmsRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_published_version_id: uuid.UUID = Field(
        ..., description="화면이 본 현재 발행본 — 그사이 바뀌었으면 409(stale_pointer)."
    )


class CmsRollbackResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    concept_code: str
    rolled_back_version_id: uuid.UUID
    restored_version_id: uuid.UUID


class CmsAuditRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: str | None
    actor_user_id: uuid.UUID
    occurred_at: str | None


class CmsAuditResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource_type: str
    resource_key: str
    items: tuple[CmsAuditRow, ...]
    note: str = Field(..., description="이 이력이 담는 것의 한계(diff 없음).")


# ── 개념 · 버전 워크플로우 ──────────────────────────────────────────────────────────────

#: 개념 payload 필드 목록(`ConceptVersionPayload` 정본) — 살아있는 개념 행에서 이 필드만 스냅숏한다.
_PAYLOAD_FIELDS: tuple[str, ...] = tuple(ConceptVersionPayload.model_fields)


def _live_payload(concept: Concept) -> dict[str, object]:
    """살아있는 개념 행 → payload 필드 dict(JSON 모드). 본문 3종·오버레이는 payload에 없다."""
    dumped = concept.to_schema().model_dump(mode="json")
    return {name: dumped[name] for name in _PAYLOAD_FIELDS if name in dumped}


def _permitted(role: Role, action: TransitionAction) -> bool:
    capability = required_capability(action)
    return capability is not None and has_capability(role, capability)


def _summary(version: SchemaConceptVersion, role: Role) -> CmsVersionSummary:
    """버전 → 요약. `allowed_actions`는 전이표 ∩ 호출자 권한이다(화면은 이것만 버튼으로 그린다).

    ORM 사용자 객체가 아니라 **역할 값**을 받는다: 응답은 `commit`/`rollback` 뒤에 만들어지는데,
    그 경계가 세션의 모든 객체(인증된 `UserProfile` 포함)를 만료시키면 이후 속성 접근이 동기 IO를
    시도해 `MissingGreenlet`으로 터진다. 값은 핸들러 맨 앞에서 스냅숏한다.
    """
    state = VersionStatus(version.status)
    permitted = tuple(a.value for a in allowed_actions(state) if _permitted(role, a))
    return CmsVersionSummary(
        version_id=version.version_id,
        concept_code=version.concept_id,
        version_no=version.version_no,
        status=state.value,
        created_by=version.governance.created_by,
        reviewed_by=version.governance.reviewed_by,
        approved_by=version.governance.approved_by,
        content_hash=version.integrity.content_hash,
        change_reason=version.change.reason,
        created_at=_iso(version.created_at),
        published_at=_iso(version.published_at),
        allowed_actions=permitted,
    )


def _edge_rows(pairs: list[tuple[ConceptEdge, Concept]]) -> tuple[CmsEdgeRow, ...]:
    return tuple(
        CmsEdgeRow(
            other_concept_id=other.concept_id,
            other_code=other.code,
            other_name_ko=other.name_ko,
            edge_type=str(to_jsonable(edge.edge_type)),
        )
        for edge, other in pairs
    )


async def _concept_code(session: AsyncSession, concept_id: uuid.UUID) -> str:
    """개념 코드만 읽는다 — **엔티티를 세션에 올리지 않는다**.

    게이트 함수가 개념 행에 `FOR UPDATE`를 잡고 판정하는데, 호출자가 같은 세션에 엔티티를 먼저
    올려 두면 그 속성이 판정에 낡은 값으로 끼어들 수 있다(`populate_existing`으로 보강했지만
    이중 방어).
    """
    code = (
        await session.execute(select(Concept.code).where(Concept.concept_id == concept_id))
    ).scalar_one_or_none()
    if code is None:
        raise _problem(status.HTTP_404_NOT_FOUND, "not_found", "개념을 찾을 수 없습니다.")
    return str(code)


@router.get(
    "/concepts",
    response_model=CmsConceptListResponse,
    summary="개념 목록 — 코드·이름 검색",
)
async def list_concepts(
    user: RequireKnowledgeGraph,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CmsConceptListResponse:
    _require(user, CmsCapability.VIEW)
    conditions: list[sa.ColumnElement[bool]] = []
    if q:
        conditions.append(
            sa.or_(
                Concept.code.icontains(q, autoescape=True),
                Concept.name_ko.icontains(q, autoescape=True),
            )
        )
    total = (
        await session.execute(select(func.count()).select_from(Concept).where(*conditions))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(Concept)
                .where(*conditions)
                .order_by(Concept.code)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    items = tuple(
        CmsConceptRow(
            concept_id=row.concept_id,
            code=row.code,
            name_ko=row.name_ko,
            level=str(to_jsonable(row.level)),
            has_published_version=row.current_published_version_id is not None,
        )
        for row in rows
    )
    return CmsConceptListResponse(items=items, total=int(total), limit=limit, offset=offset)


@router.get(
    "/concepts/{concept_id}",
    response_model=CmsConceptDetail,
    summary="개념 상세 — 살아있는 행(읽기 전용) + 관계(읽기 전용) + 발행 포인터",
)
async def get_concept_detail(
    concept_id: uuid.UUID, user: RequireKnowledgeGraph, session: SessionDep
) -> CmsConceptDetail:
    _require(user, CmsCapability.VIEW)
    role = user.role
    concept = await session.get(Concept, concept_id)
    if concept is None:
        raise _problem(status.HTTP_404_NOT_FOUND, "not_found", "개념을 찾을 수 없습니다.")
    versions = await gate.list_versions(session, concept.code)
    incoming = (
        await session.execute(
            select(ConceptEdge, Concept)
            .join(Concept, Concept.concept_id == ConceptEdge.from_concept_id)
            .where(ConceptEdge.to_concept_id == concept_id)
            .order_by(Concept.code)
            .limit(200)
        )
    ).all()
    outgoing = (
        await session.execute(
            select(ConceptEdge, Concept)
            .join(Concept, Concept.concept_id == ConceptEdge.to_concept_id)
            .where(ConceptEdge.from_concept_id == concept_id)
            .order_by(Concept.code)
            .limit(200)
        )
    ).all()
    return CmsConceptDetail(
        concept_id=concept.concept_id,
        code=concept.code,
        live=_live_payload(concept),
        published_version_id=concept.current_published_version_id,
        latest_version_no=versions[0].version_no if versions else None,
        incoming=_edge_rows([(e, c) for e, c in incoming]),
        outgoing=_edge_rows([(e, c) for e, c in outgoing]),
        can_edit=has_capability(role, CmsCapability.EDIT),
    )


async def _unknown_skills(session: AsyncSession, skills: list[str]) -> list[str]:
    """`skill_node`에 없는 스킬 id — 개념에 존재하지 않는 스킬을 연결하지 못하게 한다."""
    if not skills:
        return []
    found = set(
        (await session.execute(select(SkillNode.skill_id).where(SkillNode.skill_id.in_(skills))))
        .scalars()
        .all()
    )
    return sorted(set(skills) - found)


@router.post(
    "/concepts/{concept_id}/drafts",
    response_model=CmsVersionSummary,
    status_code=status.HTTP_201_CREATED,
    summary="개념 초안 생성 — 수정은 항상 새 DRAFT 판(살아있는 행을 직접 고치지 않는다)",
)
async def create_concept_draft(
    concept_id: uuid.UUID,
    body: CmsDraftRequest,
    request: Request,
    user: RequireKnowledgeGraph,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsVersionSummary:
    """기준 = 최신 판의 payload(있으면) 아니면 살아있는 행 스냅숏 → 변경 병합 → payload 재검증
    → 새 DRAFT.

    `ConceptVersionPayload`는 `extra="forbid"`라 발행 포인터·상태 같은 키는 payload에 실을 수 없다
    (422). 스킬은 `skill_node`에 실재해야 하고, 부모 개념은 실재하며 자기 자신이 아니어야 한다.
    """
    _require(user, CmsCapability.EDIT)
    role, actor, actor_id = user.role, _actor(user), user.user_id  # commit 뒤에는 읽지 않는다
    concept = await session.get(Concept, concept_id)
    if concept is None:
        raise _problem(status.HTTP_404_NOT_FOUND, "not_found", "개념을 찾을 수 없습니다.")
    versions = await gate.list_versions(session, concept.code)
    base: dict[str, object] = (
        dict(versions[0].payload.model_dump(mode="json")) if versions else _live_payload(concept)
    )
    merged = {**base, **body.changes}
    try:
        payload = ConceptVersionPayload.model_validate(merged)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "payload_invalid",
            str(first["msg"]),
            field=".".join(str(part) for part in first["loc"]) or "payload",
        ) from exc

    if "behavior_skills" in body.changes:
        unknown = await _unknown_skills(session, list(payload.behavior_skills))
        if unknown:
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "unknown_skill",
                "skill_node에 없는 스킬입니다.",
                field="behavior_skills",
                unknown=unknown,
            )
    if "parent_concept_id" in body.changes and payload.parent_concept_id is not None:
        if payload.parent_concept_id == concept.concept_id:
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "parent_is_self",
                "자기 자신을 부모로 지정할 수 없습니다.",
                field="parent_concept_id",
            )
        if await session.get(Concept, payload.parent_concept_id) is None:
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "unknown_parent",
                "존재하지 않는 부모 개념입니다.",
                field="parent_concept_id",
            )

    try:
        version = await gate.create_draft(
            session,
            concept_code=concept.code,
            payload=payload,
            schema_version=CMS_PAYLOAD_SCHEMA_VERSION,
            created_by=actor,
            change=VersionChange(
                change_type="cms_edit", reason=body.reason, ticket_id=body.ticket_id
            ),
        )
        record_content_mutation_audit(
            session,
            actor_user_id=actor_id,
            resource_type=PrivacyAuditResourceType.concept_version,
            resource_id=version.version_id,
            action=PrivacyAuditAction.create,
            ip=_client_ip(request, settings=settings),
            settings=settings,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return _summary(version, role)


@router.get(
    "/concepts/{concept_id}/versions",
    response_model=tuple[CmsVersionSummary, ...],
    summary="개념의 판 목록 — 변경이력(최신 판부터)",
)
async def list_concept_versions(
    concept_id: uuid.UUID, user: RequireContentVersion, session: SessionDep
) -> tuple[CmsVersionSummary, ...]:
    _require(user, CmsCapability.VIEW)
    code = await _concept_code(session, concept_id)
    role = user.role
    return tuple(_summary(v, role) for v in await gate.list_versions(session, code))


@router.get(
    "/versions/{version_id}",
    response_model=CmsVersionDetail,
    summary="판 상세 — payload·거버넌스·게이트 통과 기록",
)
async def get_version_detail(
    version_id: uuid.UUID, user: RequireContentVersion, session: SessionDep
) -> CmsVersionDetail:
    _require(user, CmsCapability.VIEW)
    try:
        version = await gate.get_version(session, version_id)
    except LookupError as exc:
        raise _problem(status.HTTP_404_NOT_FOUND, "not_found", "판을 찾을 수 없습니다.") from exc
    records = tuple(
        CmsGateRecord(
            gate=str(rec.gate),
            action=str(rec.action),
            judged_by=rec.judged_by,
            judged_at=rec.judged_at.isoformat(),
            checks=tuple(rec.checks),
            content_hash=rec.content_hash,
        )
        for rec in version.qa.records
    )
    return CmsVersionDetail(
        summary=_summary(version, user.role),
        payload=dict(version.payload.model_dump(mode="json")),
        gate_records=records,
    )


@router.post(
    "/versions/{version_id}/transitions",
    response_model=CmsVersionSummary,
    summary="판 전이 — 제출·검토·승인·발행·폐기·은퇴 (전이표·게이트·권한을 서버가 강제)",
)
async def transition_version(
    version_id: uuid.UUID,
    body: CmsTransitionRequest,
    request: Request,
    user: RequireContentVersion,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsVersionSummary:
    """권한 검사 → (잠금 후 상태 비교 · 전이표 · 게이트) → 감사 1행 → commit 1회.

    **권한을 DB 접근 전에 검사한다**: 편집자의 `publish` 요청은 게이트 서비스를 호출하기 전에
    403으로 끝난다(주입 검증 ①). 복합 전용 전이(supersede·rollback·restore)와 어휘에 없는
    이름은 권한이 매핑되지 않아 422로 거부된다 — 단독 호출 통로가 없다.
    """
    capability = required_capability(body.action)
    if capability is None:
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "unknown_action",
            "허용되지 않는 전이 이름입니다(복합 전용 전이는 단독으로 호출할 수 없습니다).",
            action=body.action,
        )
    _require(user, capability)
    role, actor, actor_id = user.role, _actor(user), user.user_id  # commit 뒤에는 읽지 않는다
    action = TransitionAction(body.action)
    try:
        version = await gate.apply_transition(
            session,
            version_id,
            action,
            actor=actor,
            expected_status=body.expected_status,
        )
        record_content_mutation_audit(
            session,
            actor_user_id=actor_id,
            resource_type=PrivacyAuditResourceType.concept_version,
            resource_id=version_id,
            action=PrivacyAuditAction(action.value),
            ip=_client_ip(request, settings=settings),
            settings=settings,
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise _problem(status.HTTP_404_NOT_FOUND, "not_found", "판을 찾을 수 없습니다.") from exc
    except gate.StaleStatusError as exc:
        await session.rollback()
        raise _problem(
            status.HTTP_409_CONFLICT,
            "stale_status",
            "화면의 상태가 최신이 아닙니다. 새로고침 후 다시 시도하세요.",
            current_status=exc.actual.value,
        ) from exc
    except UndefinedTransitionError as exc:
        await session.rollback()
        raise _problem(
            status.HTTP_409_CONFLICT,
            "illegal_transition",
            "현재 상태에서 허용되지 않는 전이입니다.",
        ) from exc
    except gate.PublishGateError as exc:
        await session.rollback()
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "gate_failed",
            "검증 게이트를 통과하지 못했습니다.",
            gate=(
                exc.gate.value
                if exc.gate is not None and not isinstance(exc.gate, str)
                else exc.gate
            ),
            failures=list(exc.failures),
        ) from exc
    except Exception:
        await session.rollback()
        raise
    return _summary(version, role)


@router.post(
    "/concepts/{concept_id}/rollback",
    response_model=CmsRollbackResponse,
    summary="롤백 — 현재 발행본을 내리고 직전 발행본으로 복구",
)
async def rollback_concept(
    concept_id: uuid.UUID,
    body: CmsRollbackRequest,
    request: Request,
    user: RequireDeployment,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsRollbackResponse:
    """배포 권한 → 개념 행 잠금 후 발행본 비교 → 복원 대상 RESTORE 게이트 → 감사 1행 → commit."""
    _require(user, ROLLBACK_CAPABILITY)
    actor, actor_id = _actor(user), user.user_id  # commit 뒤에는 읽지 않는다
    code = await _concept_code(session, concept_id)
    try:
        result = await gate.rollback(
            session,
            code,
            actor=actor,
            expected_current_version_id=body.expected_published_version_id,
        )
        record_content_mutation_audit(
            session,
            actor_user_id=actor_id,
            resource_type=PrivacyAuditResourceType.concept_version,
            resource_id=result.rolled_back_version_id,
            action=PrivacyAuditAction.rollback,
            ip=_client_ip(request, settings=settings),
            settings=settings,
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise _problem(status.HTTP_404_NOT_FOUND, "not_found", "개념을 찾을 수 없습니다.") from exc
    except gate.StalePublishedPointerError as exc:
        await session.rollback()
        raise _problem(
            status.HTTP_409_CONFLICT,
            "stale_pointer",
            "화면의 발행본이 최신이 아닙니다. 새로고침 후 다시 시도하세요.",
            published_version_id=str(exc.actual) if exc.actual else None,
        ) from exc
    except gate.RollbackUnavailableError as exc:
        await session.rollback()
        raise _problem(
            status.HTTP_409_CONFLICT, "rollback_unavailable", "롤백할 수 없는 상태입니다."
        ) from exc
    except UndefinedTransitionError as exc:
        await session.rollback()
        raise _problem(
            status.HTTP_409_CONFLICT, "illegal_transition", "허용되지 않는 전이입니다."
        ) from exc
    except gate.PublishGateError as exc:
        await session.rollback()
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "gate_failed",
            "복원 대상이 검증 게이트를 통과하지 못했습니다(내려간 동안 내용이 바뀌었을 수 있음).",
            failures=list(exc.failures),
        ) from exc
    except Exception:
        await session.rollback()
        raise
    return CmsRollbackResponse(
        concept_code=result.concept_code,
        rolled_back_version_id=result.rolled_back_version_id,
        restored_version_id=result.restored_version_id,
    )


# ── 개념 외 리소스 · 허용 목록 제자리 편집 ──────────────────────────────────────────────

_CELL_PREVIEW = 80


def _cell(value: object) -> object:
    """목록 셀 — 긴 문자열은 미리보기로 줄인다(본문 전체는 상세에서 본다)."""
    plain = to_jsonable(value)
    if isinstance(plain, str) and len(plain) > _CELL_PREVIEW:
        return plain[:_CELL_PREVIEW] + "…"
    return plain


def _field_metas(spec: ResourceSpec) -> tuple[CmsFieldMeta, ...]:
    return tuple(
        CmsFieldMeta(
            name=f.name,
            label_ko=f.label_ko,
            kind=f.kind,
            max_length=f.max_length,
            choices=f.choices,
            nullable=f.nullable,
        )
        for f in spec.editable
    )


def _resource_meta(spec: ResourceSpec) -> CmsResourceMeta:
    return CmsResourceMeta(
        key=spec.key,
        label_ko=spec.label_ko,
        route=get_module(spec.module_id).route,
        pk_column=spec.pk,
        audit_type=spec.audit_type.value if spec.audit_type is not None else None,
        list_columns=spec.list_columns,
        detail_columns=spec.detail_columns,
        fields=_field_metas(spec),
        reviewable=spec.review_column is not None,
        read_only=spec.read_only,
    )


async def _load_row(
    session: AsyncSession, spec: ResourceSpec, raw_pk: str, *, lock: bool = False
) -> Any:
    """키로 행 1건 — 형태가 틀리거나 없으면 404. `lock`이면 `FOR UPDATE` + 잠금 후 재조회."""
    key = parse_pk(spec, raw_pk)
    if key is None:
        raise _problem(status.HTTP_404_NOT_FOUND, "not_found", "대상을 찾을 수 없습니다.")
    stmt = select(spec.model).where(getattr(spec.model, spec.pk) == key)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise _problem(status.HTTP_404_NOT_FOUND, "not_found", "대상을 찾을 수 없습니다.")
    return row


async def _edit_block_reason(
    session: AsyncSession, spec: ResourceSpec, row: Any, *, lock_parent: bool = False
) -> str | None:
    """편집이 막히는 사유(없으면 None) — 검수 축을 우회하지 않기 위한 규칙.

    승인(`approved`)된 문항은 학생에게 서빙 중이라 제자리 수정이 곧 검수 없는 변경이다 —
    먼저 검수 큐에서 격리해야 한다(그 동작은 검수 권한). 풀이 단계는 부모 문항이 승인 상태면
    같은 이유로 막는다.
    `lock_parent`면 부모 행에 공유 잠금을 걸어, 수정 중에 부모가 승인되는 틈(검사-쓰기 사이)을
    막는다.
    """
    if spec.edit_guard == "none":
        return None
    if spec.edit_guard == "problem_not_approved":
        if row.review_status == ReviewStatus.approved:
            return "승인된 문항입니다. 먼저 검수 큐에서 격리한 뒤 수정하세요."
        return None
    # parent_problem_not_approved
    if row.problem_id is None:
        return None
    stmt = select(Problem).where(Problem.problem_id == row.problem_id)
    if lock_parent:
        stmt = stmt.with_for_update(read=True).execution_options(populate_existing=True)
    parent = (await session.execute(stmt)).scalar_one_or_none()
    if parent is not None and parent.review_status == ReviewStatus.approved:
        return "승인된 문항의 풀이 단계입니다. 먼저 검수 큐에서 문항을 격리한 뒤 수정하세요."
    return None


async def _detail(
    session: AsyncSession, spec: ResourceSpec, row: Any, role: Role
) -> CmsDetailResponse:
    """상세 응답 — `role`은 값이다(트랜잭션 경계 뒤에도 안전, `_summary` 주석 참조)."""
    can_edit = has_capability(role, CmsCapability.EDIT)
    return CmsDetailResponse(
        resource=spec.key,
        pk=str(to_jsonable(getattr(row, spec.pk))),
        values={c: to_jsonable(getattr(row, c)) for c in spec.detail_columns},
        fields=_field_metas(spec) if can_edit else (),
        can_review=spec.review_column is not None and has_capability(role, CmsCapability.REVIEW),
        edit_blocked_reason=await _edit_block_reason(session, spec, row) if spec.editable else None,
    )


async def _list_items(
    spec: ResourceSpec,
    user: UserProfile,
    session: AsyncSession,
    q: str | None,
    limit: int,
    offset: int,
) -> CmsListResponse:
    _require(user, CmsCapability.VIEW)
    model = spec.model
    conditions: list[sa.ColumnElement[bool]] = []
    if q and spec.search_column is not None:
        column = getattr(model, spec.search_column)
        conditions.append(sa.cast(column, sa.Text).icontains(q, autoescape=True))
    total = (
        await session.execute(select(func.count()).select_from(model).where(*conditions))
    ).scalar_one()
    order = [getattr(model, spec.pk)]
    if spec.order_by is not None and spec.order_by != spec.pk:
        order.insert(0, getattr(model, spec.order_by))
    rows = (
        (
            await session.execute(
                select(model).where(*conditions).order_by(*order).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    items = tuple({c: _cell(getattr(row, c)) for c in spec.list_columns} for row in rows)
    return CmsListResponse(
        resource=spec.key,
        columns=spec.list_columns,
        items=items,
        total=int(total),
        limit=limit,
        offset=offset,
    )


async def _get_item(
    spec: ResourceSpec, pk: str, user: UserProfile, session: AsyncSession
) -> CmsDetailResponse:
    _require(user, CmsCapability.VIEW)
    row = await _load_row(session, spec, pk)
    return await _detail(session, spec, row, user.role)


async def _patch_item(
    spec: ResourceSpec,
    pk: str,
    body: CmsEditRequest,
    request: Request,
    user: UserProfile,
    session: AsyncSession,
    settings: Settings,
) -> CmsEditResponse:
    """권한 → 허용 목록 검증 → 행 잠금 → 편집 가드 → 도메인 불변식 → 쓰기 → 감사 → commit.

    허용 목록 밖의 필드(상태·발행 컬럼 포함)는 **행을 읽기 전에** 422로 거부된다.
    """
    _require(user, CmsCapability.EDIT)
    role, actor_id = user.role, user.user_id  # commit·rollback 뒤에는 읽지 않는다
    try:
        coerced = validate_changes(spec, body.changes)
    except FieldError as exc:
        raise _field_problem(exc) from exc
    try:
        row = await _load_row(session, spec, pk, lock=True)
        reason = await _edit_block_reason(session, spec, row, lock_parent=True)
        if reason is not None:
            raise _problem(status.HTTP_409_CONFLICT, "edit_blocked", reason)
        if spec.merged_validator is not None:
            try:
                spec.merged_validator(row, coerced)
            except FieldError as exc:
                raise _field_problem(exc) from exc
        changed, resets = apply_changes(spec, row, coerced)
        if changed:
            assert spec.audit_type is not None  # check_specs가 보장(쓰기 리소스는 감사 대상 필수)
            record_content_mutation_audit(
                session,
                actor_user_id=actor_id,
                resource_type=spec.audit_type,
                resource_id=audit_resource_id(spec, getattr(row, spec.pk)),
                action=PrivacyAuditAction.update,
                ip=_client_ip(request, settings=settings),
                settings=settings,
            )
            await session.commit()
        else:
            await session.rollback()  # 바뀐 것이 없다 — 잠금만 일찍 푼다.
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        raise _problem(
            status.HTTP_409_CONFLICT, "conflict", "저장 중 충돌이 발생했습니다."
        ) from exc
    except Exception:
        await session.rollback()
        raise
    fresh = await _load_row(session, spec, pk)
    return CmsEditResponse(
        changed=tuple(changed),
        server_reset=tuple(resets),
        detail=await _detail(session, spec, fresh, role),
    )


async def _review_item(
    spec: ResourceSpec,
    pk: str,
    body: CmsReviewRequest,
    request: Request,
    user: UserProfile,
    session: AsyncSession,
    settings: Settings,
) -> CmsReviewResponse:
    """검수 표지를 올리거나(`reviewed`) 내린다(`needs_review`) — 검수 권한 전용."""
    _require(user, CmsCapability.REVIEW)
    actor_id = user.user_id  # commit 뒤에는 읽지 않는다
    review_column = spec.review_column
    assert review_column is not None  # 검수 라우트는 검수 컬럼이 있는 리소스에만 선언한다
    target = REVIEW_STATUS_REVIEWED if body.decision == "reviewed" else REVIEW_STATUS_AI_ESTIMATED
    try:
        row = await _load_row(session, spec, pk, lock=True)
        current = str(getattr(row, review_column))
        if current == target:
            await session.rollback()
            return CmsReviewResponse(changed=False, review_status=current)
        setattr(row, review_column, target)
        if spec.loader_protected:
            # 검수 표시도 사람의 쓰기다 — 적재가 `reviewed`를 정본 값으로 되돌리지 못하게
            # 표지를 채운다.
            mark_cms_edited(row)
        assert spec.audit_type is not None  # check_specs가 보장
        record_content_mutation_audit(
            session,
            actor_user_id=actor_id,
            resource_type=spec.audit_type,
            resource_id=audit_resource_id(spec, getattr(row, spec.pk)),
            action=(
                PrivacyAuditAction.approve
                if body.decision == "reviewed"
                else PrivacyAuditAction.reject
            ),
            ip=_client_ip(request, settings=settings),
            settings=settings,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return CmsReviewResponse(changed=True, review_status=target)


# ── 리소스별 라우트 — **데코레이터로 정적 선언**한다 ────────────────────────────────────
# 루프 안에서 `add_api_route`로 등록하면 코드가 짧아지지만 라우트가 grep·코드 리뷰·정적 인벤토리
# (`scripts/analysis/eos_feature_inventory_v2.py`는 `@router.<method>` 데코레이터를 AST로 읽는다)
# 어디에도 보이지 않는다 — 장부가 라우트 34개 중 9개만 센 채 "전수"라고 말하게 된다. 그래서
# 라우트는 눈에 보이게 쓰고 로직은 위 공용 함수가 소유한다. 선언(`RESOURCES`)과 이 핸들러 집합이
# 어긋나지 않음은 `tests/backend/api/test_admin_cms.py::TestRouteDeclarationParity`가 동결한다.

QueryText = Annotated[str | None, Query(max_length=100)]
QueryLimit = Annotated[int, Query(ge=1, le=100)]
QueryOffset = Annotated[int, Query(ge=0)]


@router.get("/curriculum_version", response_model=CmsListResponse, summary="교육과정 판 목록")
async def list_curriculum_version(
    user: RequireCurriculum,
    session: SessionDep,
    q: QueryText = None,
    limit: QueryLimit = 25,
    offset: QueryOffset = 0,
) -> CmsListResponse:
    return await _list_items(get_resource("curriculum_version"), user, session, q, limit, offset)


@router.get(
    "/curriculum_version/items/{pk}", response_model=CmsDetailResponse, summary="교육과정 판 상세"
)
async def get_curriculum_version(
    pk: str, user: RequireCurriculum, session: SessionDep
) -> CmsDetailResponse:
    return await _get_item(get_resource("curriculum_version"), pk, user, session)


@router.patch(
    "/curriculum_version/items/{pk}",
    response_model=CmsEditResponse,
    summary="교육과정 판 수정 — 허용 필드만(상태·발행 컬럼 거부)",
)
async def patch_curriculum_version(
    pk: str,
    body: CmsEditRequest,
    request: Request,
    user: RequireCurriculum,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsEditResponse:
    return await _patch_item(
        get_resource("curriculum_version"), pk, body, request, user, session, settings
    )


@router.get("/problem", response_model=CmsListResponse, summary="문항 목록")
async def list_problem(
    user: RequireContentLibrary,
    session: SessionDep,
    q: QueryText = None,
    limit: QueryLimit = 25,
    offset: QueryOffset = 0,
) -> CmsListResponse:
    return await _list_items(get_resource("problem"), user, session, q, limit, offset)


@router.get("/problem/items/{pk}", response_model=CmsDetailResponse, summary="문항 상세")
async def get_problem(
    pk: str, user: RequireContentLibrary, session: SessionDep
) -> CmsDetailResponse:
    return await _get_item(get_resource("problem"), pk, user, session)


@router.patch(
    "/problem/items/{pk}",
    response_model=CmsEditResponse,
    summary="문항 수정 — 허용 필드만, 승인된 문항은 먼저 격리",
)
async def patch_problem(
    pk: str,
    body: CmsEditRequest,
    request: Request,
    user: RequireContentLibrary,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsEditResponse:
    return await _patch_item(get_resource("problem"), pk, body, request, user, session, settings)


@router.get("/problem_step", response_model=CmsListResponse, summary="풀이 단계 목록")
async def list_problem_step(
    user: RequireContentLibrary,
    session: SessionDep,
    q: QueryText = None,
    limit: QueryLimit = 25,
    offset: QueryOffset = 0,
) -> CmsListResponse:
    return await _list_items(get_resource("problem_step"), user, session, q, limit, offset)


@router.get("/problem_step/items/{pk}", response_model=CmsDetailResponse, summary="풀이 단계 상세")
async def get_problem_step(
    pk: str, user: RequireContentLibrary, session: SessionDep
) -> CmsDetailResponse:
    return await _get_item(get_resource("problem_step"), pk, user, session)


@router.patch(
    "/problem_step/items/{pk}",
    response_model=CmsEditResponse,
    summary="풀이 단계 수정 — 승인된 문항의 단계는 먼저 격리",
)
async def patch_problem_step(
    pk: str,
    body: CmsEditRequest,
    request: Request,
    user: RequireContentLibrary,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsEditResponse:
    return await _patch_item(
        get_resource("problem_step"), pk, body, request, user, session, settings
    )


@router.get("/misconception", response_model=CmsListResponse, summary="오개념 목록")
async def list_misconception(
    user: RequireMisconception,
    session: SessionDep,
    q: QueryText = None,
    limit: QueryLimit = 25,
    offset: QueryOffset = 0,
) -> CmsListResponse:
    return await _list_items(get_resource("misconception"), user, session, q, limit, offset)


@router.get("/misconception/items/{pk}", response_model=CmsDetailResponse, summary="오개념 상세")
async def get_misconception(
    pk: str, user: RequireMisconception, session: SessionDep
) -> CmsDetailResponse:
    return await _get_item(get_resource("misconception"), pk, user, session)


@router.patch(
    "/misconception/items/{pk}",
    response_model=CmsEditResponse,
    summary="오개념 수정 — Signature·교정 문구",
)
async def patch_misconception(
    pk: str,
    body: CmsEditRequest,
    request: Request,
    user: RequireMisconception,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsEditResponse:
    return await _patch_item(
        get_resource("misconception"), pk, body, request, user, session, settings
    )


@router.get("/strategy_node", response_model=CmsListResponse, summary="교수전략 목록")
async def list_strategy_node(
    user: RequirePedagogy,
    session: SessionDep,
    q: QueryText = None,
    limit: QueryLimit = 25,
    offset: QueryOffset = 0,
) -> CmsListResponse:
    return await _list_items(get_resource("strategy_node"), user, session, q, limit, offset)


@router.get("/strategy_node/items/{pk}", response_model=CmsDetailResponse, summary="교수전략 상세")
async def get_strategy_node(
    pk: str, user: RequirePedagogy, session: SessionDep
) -> CmsDetailResponse:
    return await _get_item(get_resource("strategy_node"), pk, user, session)


@router.patch(
    "/strategy_node/items/{pk}",
    response_model=CmsEditResponse,
    summary="교수전략 수정 — 검수 표지를 내린다",
)
async def patch_strategy_node(
    pk: str,
    body: CmsEditRequest,
    request: Request,
    user: RequirePedagogy,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsEditResponse:
    return await _patch_item(
        get_resource("strategy_node"), pk, body, request, user, session, settings
    )


@router.post(
    "/strategy_node/items/{pk}/review",
    response_model=CmsReviewResponse,
    summary="교수전략 검수 표지 변경 — 검수 권한",
)
async def review_strategy_node(
    pk: str,
    body: CmsReviewRequest,
    request: Request,
    user: RequirePedagogy,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsReviewResponse:
    return await _review_item(
        get_resource("strategy_node"), pk, body, request, user, session, settings
    )


@router.get("/concept_content", response_model=CmsListResponse, summary="개념 설명 목록")
async def list_concept_content(
    user: RequireContentLibrary,
    session: SessionDep,
    q: QueryText = None,
    limit: QueryLimit = 25,
    offset: QueryOffset = 0,
) -> CmsListResponse:
    return await _list_items(get_resource("concept_content"), user, session, q, limit, offset)


@router.get(
    "/concept_content/items/{pk}", response_model=CmsDetailResponse, summary="개념 설명 상세"
)
async def get_concept_content(
    pk: str, user: RequireContentLibrary, session: SessionDep
) -> CmsDetailResponse:
    return await _get_item(get_resource("concept_content"), pk, user, session)


@router.patch(
    "/concept_content/items/{pk}",
    response_model=CmsEditResponse,
    summary="개념 설명 수정 — 검수 표지를 내린다",
)
async def patch_concept_content(
    pk: str,
    body: CmsEditRequest,
    request: Request,
    user: RequireContentLibrary,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsEditResponse:
    return await _patch_item(
        get_resource("concept_content"), pk, body, request, user, session, settings
    )


@router.post(
    "/concept_content/items/{pk}/review",
    response_model=CmsReviewResponse,
    summary="개념 설명 검수 표지 변경 — 검수 권한",
)
async def review_concept_content(
    pk: str,
    body: CmsReviewRequest,
    request: Request,
    user: RequireContentLibrary,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsReviewResponse:
    return await _review_item(
        get_resource("concept_content"), pk, body, request, user, session, settings
    )


@router.get("/hint", response_model=CmsListResponse, summary="힌트 목록")
async def list_hint(
    user: RequireContentLibrary,
    session: SessionDep,
    q: QueryText = None,
    limit: QueryLimit = 25,
    offset: QueryOffset = 0,
) -> CmsListResponse:
    return await _list_items(get_resource("hint"), user, session, q, limit, offset)


@router.get("/hint/items/{pk}", response_model=CmsDetailResponse, summary="힌트 상세")
async def get_hint(pk: str, user: RequireContentLibrary, session: SessionDep) -> CmsDetailResponse:
    return await _get_item(get_resource("hint"), pk, user, session)


@router.patch(
    "/hint/items/{pk}",
    response_model=CmsEditResponse,
    summary="힌트 수정 — 검증 표지를 내린다(재검증 필요)",
)
async def patch_hint(
    pk: str,
    body: CmsEditRequest,
    request: Request,
    user: RequireContentLibrary,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsEditResponse:
    return await _patch_item(get_resource("hint"), pk, body, request, user, session, settings)


@router.get("/skill_node", response_model=CmsListResponse, summary="스킬 목록(읽기 전용)")
async def list_skill_node(
    user: RequireKnowledgeGraph,
    session: SessionDep,
    q: QueryText = None,
    limit: QueryLimit = 25,
    offset: QueryOffset = 0,
) -> CmsListResponse:
    return await _list_items(get_resource("skill_node"), user, session, q, limit, offset)


@router.get(
    "/skill_node/items/{pk}", response_model=CmsDetailResponse, summary="스킬 상세(읽기 전용)"
)
async def get_skill_node(
    pk: str, user: RequireKnowledgeGraph, session: SessionDep
) -> CmsDetailResponse:
    return await _get_item(get_resource("skill_node"), pk, user, session)


@router.get(
    "/resources",
    response_model=CmsResourcesResponse,
    summary="CMS 리소스 선언 — 화면이 목록·폼을 서버 선언에서 그린다",
)
async def list_cms_resources(user: RequireContentLibrary) -> CmsResourcesResponse:
    _require(user, CmsCapability.VIEW)
    return CmsResourcesResponse(
        resources=tuple(_resource_meta(spec) for spec in RESOURCES),
        capabilities=tuple(sorted(c.value for c in capabilities_of(user.role))),
    )


# ── 변경이력(감사) ────────────────────────────────────────────────────────────────────


@router.get(
    "/audit",
    response_model=CmsAuditResponse,
    summary="콘텐츠 변경이력 — 누가·언제·무슨 동작(diff는 없음)",
)
async def list_cms_audit(
    user: RequireContentVersion,
    session: SessionDep,
    resource_type: Annotated[str, Query(max_length=32)],
    resource_key: Annotated[str, Query(max_length=200)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CmsAuditResponse:
    """제자리 편집 리소스는 버전 테이블이 없어 이 감사 이력이 변경이력의 전부다.

    감사 행은 **동작만** 남긴다(어느 필드가 어떻게 바뀌었는지는 없다 — `PrivacyAudit`에 자유텍스트가
    없다는 불변식). 그 한계를 응답의 `note`로 밝힌다.
    """
    _require(user, CmsCapability.VIEW)
    if resource_type not in {t.value for t in PrivacyAuditResourceType}:
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "unknown_resource_type",
            "알 수 없는 리소스 종류입니다.",
        )
    spec = next(
        (s for s in RESOURCES if s.audit_type and s.audit_type.value == resource_type), None
    )
    resource_id: uuid.UUID
    if spec is not None:
        key = parse_pk(spec, resource_key)
        if key is None:
            raise _problem(status.HTTP_404_NOT_FOUND, "not_found", "대상을 찾을 수 없습니다.")
        resource_id = audit_resource_id(spec, key)
    else:
        try:
            resource_id = uuid.UUID(resource_key)
        except ValueError as exc:
            raise _problem(
                status.HTTP_404_NOT_FOUND, "not_found", "대상을 찾을 수 없습니다."
            ) from exc
    rows = (
        (
            await session.execute(
                select(PrivacyAudit)
                .where(
                    PrivacyAudit.event_kind == AuditEventKind.content_mutation.value,
                    PrivacyAudit.resource_type == resource_type,
                    PrivacyAudit.resource_id == resource_id,
                )
                .order_by(PrivacyAudit.occurred_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return CmsAuditResponse(
        resource_type=resource_type,
        resource_key=resource_key,
        items=tuple(
            CmsAuditRow(
                action=row.action,
                actor_user_id=row.user_id,
                occurred_at=_iso(row.occurred_at),
            )
            for row in rows
        ),
        note="감사 행은 동작과 시각만 남깁니다. 어떤 필드가 어떻게 바뀌었는지는 기록되지 않습니다.",
    )
