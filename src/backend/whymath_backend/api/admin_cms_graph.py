"""Admin CMS BFF — 개념 그래프 쓰기 `/v1/admin/cms/*` (P3-26).

P3-12(`api/admin_cms.py`)가 의도적으로 열지 않은 세 가지를 연다. 규약 정본:
`docs/standards/cms_concept_graph_write_contract.md`.

**① 신규 개념 — 버전 워크플로우 경유** (살아있는 `concept` 행을 직접 만들지 않는다)
  - GET  /concept-proposals                       : 열린 제안 목록(아직 개념 행이 없는 것)
  - POST /concept-proposals                       : 새 코드로 첫 DRAFT 판 제안
  - POST /concept-proposals/{code}/drafts         : 제안을 고친다(= 새 DRAFT 판)
  제출·검토·승인·발행은 기존 `POST /versions/{id}/transitions`를 그대로 쓴다. **개념 행은 발행하는
  순간 `l3/publish_gate`가 만든다** — 이 모듈은 `Concept` 행을 만들지도 `ConceptVersion` ORM을
  import하지도 않는다(AST 동결: `tests/backend/api/test_cms_graph_write_enforcement.py`).

**② 선수 관계(엣지) 쓰기 — 비순환 검사 후에만**
  - POST   /edges            : 선수 관계 추가(서버가 순환을 거부)
  - DELETE /edges/{edge_id}  : CMS가 만든 관계만 삭제(graph.json 소유 관계는 거부)

**③ 개념 삭제 — 발행본이 있으면 거부**
  - DELETE /concepts/{concept_id}

쓰기 권한은 서버가 DB 접근 **전에** 검사한다(`schema/cms_access.py`). 관계·삭제는 초안 단계가 없는
*살아있는* 쓰기라 편집 권한이 아니라 **발행 권한**(`GRAPH_WRITE_CAPABILITY`)을 요구한다.

모든 쓰기는 같은 트랜잭션에 감사 1행을 합류시키고 commit은 1회다. `from __future__ import
annotations`를 쓰지 않는다(`admin_cms.py`와 같은 이유 — FastAPI가 `Annotated` 별칭을
평가 시점에 해석).

7계층: L5 `api`의 BFF. 수학 로직 0.
"""

import re
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api._concept_graph_rules import (
    WriteBlock,
    concept_codes,
    concept_delete_block,
    edge_delete_block,
    find_cycle_if_added,
    lock_prerequisite_graph,
)
from whymath_backend.api._rate_limit import _client_ip
from whymath_backend.api.admin_cms import (
    CMS_PAYLOAD_SCHEMA_VERSION,
    CmsVersionSummary,
    RequireKnowledgeGraph,
    SessionDep,
    SettingsDep,
    _actor,
    _problem,
    _require,
    _summary,
    _unknown_skills,
)
from whymath_backend.db.cms_edit_marker import mark_cms_edited
from whymath_backend.db.models.concept import Concept, ConceptEdge
from whymath_backend.l3 import publish_gate as gate
from whymath_backend.privacy.audit import record_content_mutation_audit
from whymath_backend.schema.cms_access import GRAPH_WRITE_CAPABILITY, CmsCapability
from whymath_backend.schema.concept_version import ConceptVersionPayload
from whymath_backend.schema.enums import EdgeType, PrivacyAuditAction, PrivacyAuditResourceType

router = APIRouter(prefix="/v1/admin/cms", tags=["admin-cms-graph"])

#: 신규 개념 코드로 허용하는 문자 — 영숫자·한글·`.`·`_`·`-`. 공백·슬래시·따옴표 등은 URL 경로·로그·
#: 파일명에서 사고를 부른다. 기존 코드(`2수01-01-2` 같은 한글 포함 형식)와 같은 문자 집합이다.
_CODE_RE = re.compile(r"^[0-9A-Za-z가-힣][0-9A-Za-z가-힣._-]{1,63}$")


# ── 요청·응답 모델 ──────────────────────────────────────────────────────────────────────


class CmsProposalRequest(BaseModel):
    """신규 개념 제안 — 코드와 payload 필드. `name_ko`·`level`은 필수(스키마가 422로 알려 준다)."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., max_length=64, description="새 개념 코드(영숫자·한글·`._-`, 2~64자).")
    payload: dict[str, Any] = Field(..., description="payload 필드 → 값(`ConceptVersionPayload`).")
    reason: str | None = Field(None, max_length=500, description="제안 사유(이력에 남는다).")
    ticket_id: str | None = Field(None, max_length=64)


class CmsProposalReviseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: dict[str, Any] = Field(
        default_factory=dict, description="payload 필드 → 새 값. 비우면 직전 판 그대로 새 판."
    )
    reason: str | None = Field(None, max_length=500)
    ticket_id: str | None = Field(None, max_length=64)


class CmsProposalRow(BaseModel):
    """열린 제안 1건 — 판 요약 + 화면 목록용 이름·계층."""

    model_config = ConfigDict(frozen=True)

    summary: CmsVersionSummary
    name_ko: str
    level: str


class CmsConceptDeleteResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    concept_code: str
    deleted: bool


class CmsEdgeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_concept_id: uuid.UUID = Field(..., description="선수 개념(알아야 하는 쪽).")
    to_concept_id: uuid.UUID = Field(..., description="후행 개념(그것을 알아야 아는 쪽).")
    edge_type: str = Field("PREREQUISITE", max_length=32, description="지금은 PREREQUISITE만.")
    edge_strength: float | None = Field(None, ge=0.0, le=1.0, description="관계 강도 0~1.")


class CmsEdgeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    edge_id: uuid.UUID
    from_concept_id: uuid.UUID
    from_code: str
    to_concept_id: uuid.UUID
    to_code: str
    edge_type: str
    edge_strength: float | None
    cms_owned: bool


class CmsEdgeDeleteResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    edge_id: uuid.UUID
    deleted: bool


# ── 도우미 ─────────────────────────────────────────────────────────────────────────────


def _check_code(code: str) -> str:
    """코드 형식 검사 — 앞뒤 공백은 지우고, 허용 문자 밖이면 422."""
    cleaned = code.strip()
    if not _CODE_RE.fullmatch(cleaned):
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_code",
            "개념 코드는 영숫자·한글·`.`·`_`·`-`만 쓸 수 있고 2~64자여야 합니다.",
            field="code",
        )
    return cleaned


async def _validated_payload(
    session: AsyncSession, merged: dict[str, Any]
) -> ConceptVersionPayload:
    """payload 검증 + 실재 확인(스킬·부모). 실패는 422 — 쓰기 전에 끝낸다."""
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
    unknown = await _unknown_skills(session, list(payload.behavior_skills))
    if unknown:
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "unknown_skill",
            "skill_node에 없는 스킬입니다.",
            field="behavior_skills",
            unknown=unknown,
        )
    if payload.parent_concept_id is not None:
        found = (
            await session.execute(
                select(Concept.concept_id).where(Concept.concept_id == payload.parent_concept_id)
            )
        ).first()
        if found is None:
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "unknown_parent",
                "존재하지 않는 부모 개념입니다.",
                field="parent_concept_id",
            )
    return payload


# ── ① 신규 개념 제안 ────────────────────────────────────────────────────────────────────


@router.get(
    "/concept-proposals",
    response_model=tuple[CmsProposalRow, ...],
    summary="열린 신규 개념 제안 — 아직 개념 행이 없는 것(발행하면 개념이 만들어진다)",
)
async def list_concept_proposals(
    user: RequireKnowledgeGraph, session: SessionDep
) -> tuple[CmsProposalRow, ...]:
    _require(user, CmsCapability.VIEW)
    role = user.role
    return tuple(
        CmsProposalRow(
            summary=_summary(version, role),
            name_ko=version.payload.name_ko,
            level=str(version.payload.level),
        )
        for version in await gate.list_open_proposals(session)
    )


@router.post(
    "/concept-proposals",
    response_model=CmsVersionSummary,
    status_code=status.HTTP_201_CREATED,
    summary="신규 개념 제안 — 살아있는 개념 행은 만들지 않고 첫 DRAFT 판만 만든다",
)
async def create_concept_proposal(
    body: CmsProposalRequest,
    request: Request,
    user: RequireKnowledgeGraph,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsVersionSummary:
    """권한 → 코드·payload 검증 → 코드 선점 확인 → DRAFT 1건 + 감사 1행 → commit 1회.

    코드가 이미 살아있는 개념이거나 판 이력이 있으면 409(`code_taken`). 개념 행은 이 요청으로
    생기지 않는다 — 검토·QA·승인·발행(`POST /versions/{id}/transitions`)을 거쳐야 만들어진다.
    """
    _require(user, CmsCapability.EDIT)
    role, actor, actor_id = user.role, _actor(user), user.user_id  # commit 뒤에는 읽지 않는다
    code = _check_code(body.code)
    payload = await _validated_payload(session, dict(body.payload))
    try:
        version = await gate.create_proposal(
            session,
            concept_code=code,
            payload=payload,
            schema_version=CMS_PAYLOAD_SCHEMA_VERSION,
            created_by=actor,
            reason=body.reason,
            ticket_id=body.ticket_id,
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
    except gate.CodeTakenError as exc:
        await session.rollback()
        raise _problem(
            status.HTTP_409_CONFLICT, "code_taken", exc.reason, concept_code=code
        ) from exc
    except Exception:
        await session.rollback()
        raise
    return _summary(version, role)


@router.post(
    "/concept-proposals/{code}/drafts",
    response_model=CmsVersionSummary,
    status_code=status.HTTP_201_CREATED,
    summary="신규 개념 제안 수정 — 항상 새 DRAFT 판",
)
async def revise_concept_proposal(
    code: str,
    body: CmsProposalReviseRequest,
    request: Request,
    user: RequireKnowledgeGraph,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsVersionSummary:
    _require(user, CmsCapability.EDIT)
    role, actor, actor_id = user.role, _actor(user), user.user_id
    versions = await gate.list_versions(session, code)
    if not versions:
        raise _problem(status.HTTP_404_NOT_FOUND, "not_found", "제안을 찾을 수 없습니다.")
    merged = {**dict(versions[0].payload.model_dump(mode="json")), **body.changes}
    payload = await _validated_payload(session, merged)
    try:
        version = await gate.revise_proposal(
            session,
            concept_code=code,
            payload=payload,
            schema_version=CMS_PAYLOAD_SCHEMA_VERSION,
            created_by=actor,
            reason=body.reason,
            ticket_id=body.ticket_id,
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
    except LookupError as exc:
        await session.rollback()
        raise _problem(
            status.HTTP_404_NOT_FOUND, "not_found", "신규 개념 제안을 찾을 수 없습니다."
        ) from exc
    except gate.CodeTakenError as exc:
        await session.rollback()
        raise _problem(
            status.HTTP_409_CONFLICT, "concept_exists", exc.reason, concept_code=code
        ) from exc
    except Exception:
        await session.rollback()
        raise
    return _summary(version, role)


# ── ③ 개념 삭제 ────────────────────────────────────────────────────────────────────────


def _block_problem(block: WriteBlock) -> HTTPException:
    return _problem(status.HTTP_409_CONFLICT, block.code, block.message, **block.extra)


@router.delete(
    "/concepts/{concept_id}",
    response_model=CmsConceptDeleteResponse,
    summary="개념 삭제 — CMS가 만들었고 발행본·관계·하위 개념이 없을 때만",
)
async def delete_concept(
    concept_id: uuid.UUID,
    request: Request,
    user: RequireKnowledgeGraph,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsConceptDeleteResponse:
    """권한 → 개념 행 잠금 → 삭제 가능 판정 → 삭제 + 감사 1행 → commit 1회.

    판 이력(`concept_version`)은 지우지 않는다 — 코드는 영구 예약된다. 외래키가 막는 그 밖의 참조는
    409(`referenced`)로 바뀐다.
    """
    _require(user, GRAPH_WRITE_CAPABILITY)
    actor_id = user.user_id  # commit 뒤에는 읽지 않는다
    try:
        concept = (
            await session.execute(
                select(Concept)
                .where(Concept.concept_id == concept_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if concept is None:
            raise _problem(status.HTTP_404_NOT_FOUND, "not_found", "개념을 찾을 수 없습니다.")
        block = await concept_delete_block(session, concept)
        if block is not None:
            raise _block_problem(block)
        code = concept.code
        await session.delete(concept)
        record_content_mutation_audit(
            session,
            actor_user_id=actor_id,
            resource_type=PrivacyAuditResourceType.concept,
            resource_id=concept_id,
            action=PrivacyAuditAction.delete,
            ip=_client_ip(request, settings=settings),
            settings=settings,
        )
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except (IntegrityError, DBAPIError) as exc:
        await session.rollback()
        raise _problem(
            status.HTTP_409_CONFLICT,
            "referenced",
            "이 개념을 참조하는 데이터(학습 기록·문항 연결 등)가 있어 삭제할 수 없습니다.",
        ) from exc
    except Exception:
        await session.rollback()
        raise
    return CmsConceptDeleteResponse(concept_code=code, deleted=True)


# ── ② 선수 관계 쓰기 ───────────────────────────────────────────────────────────────────


def _edge_response(edge: ConceptEdge, from_code: str, to_code: str) -> CmsEdgeResponse:
    strength = edge.edge_strength
    return CmsEdgeResponse(
        edge_id=edge.edge_id,
        from_concept_id=edge.from_concept_id,
        from_code=from_code,
        to_concept_id=edge.to_concept_id,
        to_code=to_code,
        edge_type=EdgeType.PREREQUISITE.value,
        edge_strength=float(strength) if strength is not None else None,
        cms_owned=edge.cms_edited_at is not None,
    )


@router.post(
    "/edges",
    response_model=CmsEdgeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="선수 관계 추가 — 서버가 비순환(DAG)을 검사하고 순환이면 거부",
)
async def create_edge(
    body: CmsEdgeCreateRequest,
    request: Request,
    user: RequireKnowledgeGraph,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsEdgeResponse:
    """권한 → 형식 검증 → **선수 그래프 잠금** → 실재·중복·순환 검사 → 쓰기 + 감사 → commit.

    순환 검사는 잠금을 잡은 뒤 **같은 트랜잭션에서** 한다: 각각은 비순환인 두 요청이 동시에 들어와
    합쳐서 순환을 만드는 틈을 막는다(적재 CLI도 같은 잠금 키를 쓴다). 순환이면
    422(`prerequisite_cycle`)
    이고 응답에 순환 경로(개념 코드)를 싣는다 — 부작용 0.
    """
    _require(user, GRAPH_WRITE_CAPABILITY)
    actor_id = user.user_id  # commit 뒤에는 읽지 않는다
    if body.edge_type != EdgeType.PREREQUISITE.value:
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "edge_type_not_writable",
            "CMS에서 쓸 수 있는 관계는 선수(PREREQUISITE)뿐입니다.",
            field="edge_type",
        )
    if body.from_concept_id == body.to_concept_id:
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "self_edge",
            "개념이 자기 자신의 선수가 될 수 없습니다.",
        )
    try:
        await lock_prerequisite_graph(session)
        codes = await concept_codes(session, [body.from_concept_id, body.to_concept_id])
        missing = [i for i in (body.from_concept_id, body.to_concept_id) if i not in codes]
        if missing:
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "unknown_concept",
                "존재하지 않는 개념입니다.",
                unknown=[str(i) for i in missing],
            )
        duplicate = (
            await session.execute(
                select(ConceptEdge.edge_id).where(
                    ConceptEdge.from_concept_id == body.from_concept_id,
                    ConceptEdge.to_concept_id == body.to_concept_id,
                    ConceptEdge.edge_type == EdgeType.PREREQUISITE,
                )
            )
        ).first()
        if duplicate is not None:
            raise _problem(status.HTTP_409_CONFLICT, "edge_exists", "이미 있는 관계입니다.")
        cycle = await find_cycle_if_added(session, body.from_concept_id, body.to_concept_id)
        if cycle is not None:
            names = await concept_codes(session, cycle)
            path = [names.get(i, str(i)) for i in cycle]
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "prerequisite_cycle",
                "이 관계를 더하면 선수 관계가 순환합니다: " + " → ".join(path),
                path=path,
            )
        strength = (
            Decimal(str(round(body.edge_strength, 2))) if body.edge_strength is not None else None
        )
        edge = ConceptEdge(
            edge_id=uuid.uuid4(),
            from_concept_id=body.from_concept_id,
            to_concept_id=body.to_concept_id,
            edge_type=EdgeType.PREREQUISITE,
            edge_strength=strength,
        )
        mark_cms_edited(edge)  # CMS가 만든 관계 — 적재가 건드리지 않고, 삭제가 허용된다
        session.add(edge)
        record_content_mutation_audit(
            session,
            actor_user_id=actor_id,
            resource_type=PrivacyAuditResourceType.concept_edge,
            resource_id=edge.edge_id,
            action=PrivacyAuditAction.create,
            ip=_client_ip(request, settings=settings),
            settings=settings,
        )
        await session.commit()
        response = _edge_response(edge, codes[body.from_concept_id], codes[body.to_concept_id])
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
    return response


@router.delete(
    "/edges/{edge_id}",
    response_model=CmsEdgeDeleteResponse,
    summary="선수 관계 삭제 — CMS가 만든 관계만(graph.json 소유 관계는 거부)",
)
async def delete_edge(
    edge_id: uuid.UUID,
    request: Request,
    user: RequireKnowledgeGraph,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsEdgeDeleteResponse:
    _require(user, GRAPH_WRITE_CAPABILITY)
    actor_id = user.user_id
    try:
        await lock_prerequisite_graph(session)
        edge = (
            await session.execute(
                select(ConceptEdge)
                .where(ConceptEdge.edge_id == edge_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if edge is None:
            raise _problem(status.HTTP_404_NOT_FOUND, "not_found", "관계를 찾을 수 없습니다.")
        block = edge_delete_block(edge)
        if block is not None:
            raise _block_problem(block)
        await session.delete(edge)
        record_content_mutation_audit(
            session,
            actor_user_id=actor_id,
            resource_type=PrivacyAuditResourceType.concept_edge,
            resource_id=edge_id,
            action=PrivacyAuditAction.delete,
            ip=_client_ip(request, settings=settings),
            settings=settings,
        )
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    return CmsEdgeDeleteResponse(edge_id=edge_id, deleted=True)
