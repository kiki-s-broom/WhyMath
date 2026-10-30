"""Admin CMS — 문항 판 발행 호출 표면 (EOS-194).

경로: `/v1/admin/cms/problems/*` · `/v1/admin/cms/problem-versions/*`

`l3/problem_publish_gate.py`(EOS-190)는 `problem_version`과 발행 포인터
`problem.problem_version_id`를 쓰는 **유일한 자리**지만, 부르는 곳이 0건이라 운영 DB의
포인터는 전부 NULL이었다. 시도 버전 고정(EOS-47)의 `outcome=pinned` 비율도 운영에서 0이었다.
이 모듈이 그 마지막 연결이다.

  - POST /problems/{problem_id}/drafts              : 라이브 문항 행의 스냅숏으로 새 DRAFT 판
  - GET  /problems/{problem_id}/versions            : 변경이력(판 목록, 최신 판부터)
  - GET  /problem-versions/{version_id}             : 판 상세(payload·게이트 통과 기록)
  - POST /problem-versions/{version_id}/transitions : 제출·검토·승인·발행·폐기·은퇴

## 왜 CMS 라우트이고 CLI가 아닌가

이 표면이 지켜야 하는 두 가지가 인증된 사용자 신원을 전제한다.

  ① **역할 분리** — 초안·제출은 편집 권한, 검토·승인은 검수 권한, 발행·내리기는 배포 권한이다
     (`schema/cms_access.py`가 정본).
  ② **전이마다 감사 1행** — 누가 했는지가 `privacy_audit.user_id`다.

운영 CLI는 인증된 역할이 없어 둘 다 새로 지어야 하고(권한표 복제 = 드리프트 자리), 개념 판
(P3-12)이 이미 같은 모양의 라우트를 갖고 있다. 같은 권한표·같은 오류 코드로 읽히는 한 곳이
운영자에게도 단순하다.

## 개념 판 라우트와 다른 점

- **초안에 `changes`가 없다.** 문항은 판과 별개로 라이브 `problem` 행이 서빙된다. 발행은
  "승인 이후 라이브 문항이 바뀌지 않았다"(`live_content_current`)를 요구하므로 초안 내용은
  항상 **지금 라이브 행의 스냅숏**이어야 한다. 내용을 고치려면 라이브 행을 먼저 고친
  (`PATCH /problem/items/{pk}`) 뒤 새 초안을 만든다. payload를 따로 받으면 발행될 수 없는
  초안을 만드는 입구가 된다.
- **판 경로가 `/versions/{id}`가 아니라 `/problem-versions/{id}`다.** 앞의 것은 개념 판이 쓴다.
- **롤백이 없다.** 문항 판 Rollback·Restore는 `EOS-196` 소유다(호출 경로 없는 코드를 두지 않는다).

## 집행 경계 (정본화 ≠ 집행)

이 모듈은 **게이트 모듈의 공개 함수만 부른다.** ORM `ProblemVersion`을 import하지 않고 발행
포인터를 쓰지 않는다. 그 금지는 AST 동결(`tests/backend/l3/
test_problem_publish_gate_enforcement.py` R1·R2·R3)이 운영 패키지 전체에서 막고, 이 모듈에 대한
주입 검증은 `tests/backend/api/test_admin_cms_problem_versions.py`가 한다.

권한은 **역할 이름이 아니라 `CmsCapability`**로 묻는다. 전이→권한 매핑은
`TRANSITION_CAPABILITY` 한 곳이며 이 모듈에 매핑을 다시 적지 않는다.

7계층: L5 `api`의 BFF. 수학 로직 0 — 전이 규칙은 `schema/version_lifecycle`, 검증은
`l3/problem_publish_gate`.

`from __future__ import annotations`를 쓰지 않는다 — `admin_cms.py`와 같은 이유다(모듈 전역
`Annotated` 별칭을 FastAPI가 평가 시점에 해석한다).
"""

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.api._rate_limit import _client_ip
from whymath_backend.api.admin_cms import (
    RequireContentLibrary,
    RequireContentVersion,
    SessionDep,
    SettingsDep,
    _actor,
    _iso,
    _require,
)
from whymath_backend.api.admin_cms import _problem as _http_error
from whymath_backend.l3 import problem_publish_gate as pgate
from whymath_backend.l3.publish_gate import PublishGateError, StaleStatusError
from whymath_backend.privacy.audit import record_content_mutation_audit
from whymath_backend.schema.cms_access import CmsCapability, has_capability, required_capability
from whymath_backend.schema.enums import PrivacyAuditAction, PrivacyAuditResourceType, Role
from whymath_backend.schema.problem_version import ProblemVersion as SchemaProblemVersion
from whymath_backend.schema.version_header import TransitionAction, VersionChange, VersionStatus
from whymath_backend.schema.version_lifecycle import UndefinedTransitionError, allowed_actions

router = APIRouter(prefix="/v1/admin/cms", tags=["admin-cms"])


# ── 요청·응답 모델 ──────────────────────────────────────────────────────────────────────


class CmsProblemDraftRequest(BaseModel):
    """초안 생성 요청 — 내용(payload)은 받지 않는다(모듈 docstring '다른 점')."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(None, max_length=500, description="변경 사유(이력에 남는다).")
    ticket_id: str | None = Field(None, max_length=64)


class CmsProblemGateRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    gate: str
    action: str
    judged_by: str
    judged_at: str
    checks: tuple[str, ...]
    content_hash: str


class CmsProblemVersionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    version_id: uuid.UUID
    problem_id: uuid.UUID
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


class CmsProblemVersionDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: CmsProblemVersionSummary
    payload: dict[str, object]
    gate_records: tuple[CmsProblemGateRecord, ...]


class CmsProblemTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(..., max_length=32, description="전이 이름(전이표 어휘).")
    expected_status: VersionStatus = Field(
        ..., description="화면이 본 상태 — 그사이 바뀌었으면 409(stale_status)."
    )


# ── 도우미 ──────────────────────────────────────────────────────────────────────────────


def _permitted(role: Role, action: TransitionAction) -> bool:
    capability = required_capability(action)
    return capability is not None and has_capability(role, capability)


def _summary(version: SchemaProblemVersion, role: Role) -> CmsProblemVersionSummary:
    """판 → 요약. `allowed_actions`는 전이표 ∩ 호출자 권한이다(화면은 이것만 버튼으로 그린다).

    ORM 사용자 객체가 아니라 **역할 값**을 받는다 — 응답은 `commit` 뒤에 만들어지고 그 경계가 세션의
    모든 객체(인증된 `UserProfile` 포함)를 만료시켜, 이후 속성 접근이 `MissingGreenlet`으로 터진다
    (`admin_cms._summary` 와 같은 이유). 값은 핸들러 맨 앞에서 스냅숏한다.
    """
    state = VersionStatus(version.status)
    permitted = tuple(a.value for a in allowed_actions(state) if _permitted(role, a))
    return CmsProblemVersionSummary(
        version_id=version.version_id,
        problem_id=version.problem_id,
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


def _gate_failed(exc: PublishGateError, message: str) -> HTTPException:
    return _http_error(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "gate_failed",
        message,
        gate=(
            exc.gate.value if exc.gate is not None and not isinstance(exc.gate, str) else exc.gate
        ),
        failures=list(exc.failures),
    )


# ── 라우트 ──────────────────────────────────────────────────────────────────────────────


@router.post(
    "/problems/{problem_id}/drafts",
    response_model=CmsProblemVersionSummary,
    status_code=status.HTTP_201_CREATED,
    summary="문항 판 초안 생성 — 지금 라이브 문항 행의 스냅숏(편집 권한)",
)
async def create_problem_draft(
    problem_id: uuid.UUID,
    body: CmsProblemDraftRequest,
    request: Request,
    user: RequireContentLibrary,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsProblemVersionSummary:
    """권한 검사 → (문항 행 잠금 · 스냅숏 · 판 번호 부여) → 감사 1행 → commit 1회.

    라이브 문항이 판 payload 계약을 어기면(예: 평가원·EBS·교과서 출처에 본문이 남은 행)
    초안을 만들지 않고 422로 거부한다 — 판 경로가 저작권 레일의 우회로가 되지 않는다.
    """
    _require(user, CmsCapability.EDIT)
    role, actor, actor_id = user.role, _actor(user), user.user_id  # commit 뒤에는 읽지 않는다
    try:
        version = await pgate.create_draft(
            session,
            problem_id=problem_id,
            created_by=actor,
            change=VersionChange(
                change_type="cms_edit", reason=body.reason, ticket_id=body.ticket_id
            ),
        )
        record_content_mutation_audit(
            session,
            actor_user_id=actor_id,
            resource_type=PrivacyAuditResourceType.problem_version,
            resource_id=version.version_id,
            action=PrivacyAuditAction.create,
            ip=_client_ip(request, settings=settings),
            settings=settings,
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise _http_error(
            status.HTTP_404_NOT_FOUND, "not_found", "문항을 찾을 수 없습니다."
        ) from exc
    except PublishGateError as exc:
        await session.rollback()
        raise _gate_failed(
            exc, "라이브 문항이 판 스냅숏 계약을 만족하지 못해 초안을 만들 수 없습니다."
        ) from exc
    except Exception:
        await session.rollback()
        raise
    return _summary(version, role)


@router.get(
    "/problems/{problem_id}/versions",
    response_model=tuple[CmsProblemVersionSummary, ...],
    summary="문항의 판 목록 — 변경이력(최신 판부터)",
)
async def list_problem_versions(
    problem_id: uuid.UUID, user: RequireContentVersion, session: SessionDep
) -> tuple[CmsProblemVersionSummary, ...]:
    _require(user, CmsCapability.VIEW)
    role = user.role
    # 없는 문항(404)과 판이 0건인 문항(빈 목록)을 구분한다 — DB는 게이트 모듈이 읽는다.
    if not await pgate.problem_exists(session, problem_id):
        raise _http_error(status.HTTP_404_NOT_FOUND, "not_found", "문항을 찾을 수 없습니다.")
    try:
        versions = await pgate.list_versions(session, problem_id)
    except PublishGateError as exc:
        raise _gate_failed(exc, "저장된 판이 스키마 계약을 어깁니다.") from exc
    return tuple(_summary(v, role) for v in versions)


@router.get(
    "/problem-versions/{version_id}",
    response_model=CmsProblemVersionDetail,
    summary="문항 판 상세 — payload·거버넌스·게이트 통과 기록",
)
async def get_problem_version_detail(
    version_id: uuid.UUID, user: RequireContentVersion, session: SessionDep
) -> CmsProblemVersionDetail:
    _require(user, CmsCapability.VIEW)
    try:
        version = await pgate.get_version(session, version_id)
    except LookupError as exc:
        raise _http_error(status.HTTP_404_NOT_FOUND, "not_found", "판을 찾을 수 없습니다.") from exc
    except PublishGateError as exc:
        raise _gate_failed(exc, "저장된 판이 스키마 계약을 어깁니다.") from exc
    records = tuple(
        CmsProblemGateRecord(
            gate=str(rec.gate),
            action=str(rec.action),
            judged_by=rec.judged_by,
            judged_at=rec.judged_at.isoformat(),
            checks=tuple(rec.checks),
            content_hash=rec.content_hash,
        )
        for rec in version.qa.records
    )
    return CmsProblemVersionDetail(
        summary=_summary(version, user.role),
        payload=dict(version.payload.model_dump(mode="json")),
        gate_records=records,
    )


@router.post(
    "/problem-versions/{version_id}/transitions",
    response_model=CmsProblemVersionSummary,
    summary="문항 판 전이 — 제출·검토·승인·발행·폐기·은퇴 (전이표·게이트·권한을 서버가 강제)",
)
async def transition_problem_version(
    version_id: uuid.UUID,
    body: CmsProblemTransitionRequest,
    request: Request,
    user: RequireContentVersion,
    session: SessionDep,
    settings: SettingsDep,
) -> CmsProblemVersionSummary:
    """권한 검사 → (잠금 후 상태 비교 · 전이표 · 게이트) → 감사 1행 → commit 1회.

    **권한을 DB 접근 전에 검사한다**: 편집자의 `publish` 요청은 게이트 서비스를 호출하기 전에
    403으로 끝난다. 복합 전용 전이(supersede·rollback·restore)와 어휘에 없는 이름은 권한이
    매핑되지 않아 422로 거부된다 — 단독 호출 통로가 없다.
    """
    capability = required_capability(body.action)
    if capability is None:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "unknown_action",
            "허용되지 않는 전이 이름입니다(복합 전용 전이는 단독으로 호출할 수 없습니다).",
            action=body.action,
        )
    _require(user, capability)
    role, actor, actor_id = user.role, _actor(user), user.user_id  # commit 뒤에는 읽지 않는다
    action = TransitionAction(body.action)
    try:
        version = await pgate.apply_transition(
            session,
            version_id,
            action,
            actor=actor,
            expected_status=body.expected_status,
        )
        record_content_mutation_audit(
            session,
            actor_user_id=actor_id,
            resource_type=PrivacyAuditResourceType.problem_version,
            resource_id=version_id,
            action=PrivacyAuditAction(action.value),
            ip=_client_ip(request, settings=settings),
            settings=settings,
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise _http_error(status.HTTP_404_NOT_FOUND, "not_found", "판을 찾을 수 없습니다.") from exc
    except StaleStatusError as exc:
        await session.rollback()
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "stale_status",
            "화면의 상태가 최신이 아닙니다. 새로고침 후 다시 시도하세요.",
            current_status=exc.actual.value,
        ) from exc
    except UndefinedTransitionError as exc:
        await session.rollback()
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "illegal_transition",
            "현재 상태에서 허용되지 않는 전이입니다.",
        ) from exc
    except PublishGateError as exc:
        await session.rollback()
        raise _gate_failed(exc, "검증 게이트를 통과하지 못했습니다.") from exc
    except Exception:
        await session.rollback()
        raise
    return _summary(version, role)
