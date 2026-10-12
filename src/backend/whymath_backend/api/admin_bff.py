"""Admin BFF — `/v1/admin/*` 운영 조회 표면 (ADMIN-05 · 04 §2 원칙2).

엔드포인트 (Phase A는 read-only GET 5종 · **ADMIN-07 Phase B가 검수 큐에 한해 쓰기 1종을 추가**):
  - GET /v1/admin/models        — 모델 상태 매트릭스(로컬 Ollama + 클라우드 구성)
  - GET /v1/admin/costs         — 비용·라우팅 집계(Langfuse 이벤트 → cost_report)
  - GET /v1/admin/review-queue  — 검수 큐(적재 문항 축 — JSONL 축은 승계 태스크)
  - GET /v1/admin/review-queue/items         — 검수 큐 목록(상태별 페이지·본문 제외)
  - GET /v1/admin/review-queue/items/{id}    — 검수 큐 단건(본문 + 서버 판정 `allowed_actions`)
  - POST /v1/admin/review-queue/items/{id}/transitions — 검수 상태 전이(**유일한 쓰기** — 행 잠금·
    전이표 검증·감사 1행·단일 트랜잭션. 전이 규칙 정본 = `schema/review_transition.py`)
  - GET /v1/admin/users         — 사용자 **집계**(PII 0)
  - GET /v1/admin/users/{id}    — 사용자 단건(마스킹) + 관리자 접근 감사 1행

인가(04 §2 원칙3·§4): 전 엔드포인트가 `require_module_roles(<module_id>)` 가드를 쓴다 —
`require_role`을 직접 쓰지 않는다. 역할값이 레지스트리에서 *파생*되므로 메뉴와 가드가 어긋날
수 없고, `ops/admin_guard_audit.py`가 CI에서 그 파생 경로 사용을 전수 검사한다(원칙7 이중 방어).
무인증 401은 `get_current_user`가, 무권한 403과 **데모 계정 403**은 그 가드가 낸다.

원자료 미노출(원칙2): 집계·마스킹은 전부 여기(BFF)에서 끝낸다. 프런트는 코어를 직접 부르지
않으며, 이 응답에는 이메일 해시·문항 본문 같은 원자료가 들어가지 않는다.

측정 실패 ≠ 0건(원칙6): 외부 원천(Langfuse·JSONL 파일)이 없거나 죽었을 때 **0으로 접지 않고
상태값으로 구분**한다. `state` 필드와 `None` 허용 수치가 그 구분의 자리다 — 인프라가 죽으면
"측정 실패"가 보여야지 "0건 통과"로 위장되면 안 된다는 CLAUDE.md 금기의 응답 축 구현이다.

7계층: L5 `api`의 조회 표면. 수학 로직 0 — 판정치는 코어(`l3`·`harness`·`ops`)가 산출하고
여기서는 투영만 한다(원칙1 — 백오피스도 표현≠의미의 예외가 아니다).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api._model_status import collect_model_status
from whymath_backend.api._rate_limit import _client_ip
from whymath_backend.api.admin_module_registry import require_module_roles
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.cms_edit_marker import mark_cms_edited
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.ops.cost_report import CostReport, aggregate_l3_events, fetch_l3_events
from whymath_backend.privacy import record_admin_access_audit
from whymath_backend.privacy.audit import record_content_mutation_audit
from whymath_backend.schema.enums import PrivacyAuditAction, PrivacyAuditResourceType, ReviewStatus
from whymath_backend.schema.review_transition import (
    QUARANTINE_REASON_MAX_LENGTH,
    IllegalReviewTransition,
    ReviewTransitionAction,
    action_requires_reason,
    allowed_actions,
    resolve_review_transition,
)

router = APIRouter(prefix="/v1/admin", tags=["admin"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

# 모듈별 가드 — 모듈 로드 시 1회 생성해 라우트가 같은 객체를 공유한다(테스트가
# `dependency_overrides`로 잡을 안정적 단일 대상이 되려면 매 호출마다 새 클로저를 만들면 안
# 된다 — `_auth.require_content_admin` 선례와 동일한 이유).
RequireModelsAdmin = Annotated[UserProfile, Depends(require_module_roles("ai_models"))]
RequireCostAdmin = Annotated[UserProfile, Depends(require_module_roles("cost_report"))]
RequireReviewAdmin = Annotated[UserProfile, Depends(require_module_roles("review_queue"))]
RequireUserAdmin = Annotated[UserProfile, Depends(require_module_roles("user_lookup"))]


# ── 모델 상태 ────────────────────────────────────────────────────────────────────────


class AdminModelRow(BaseModel):
    """로컬 모델 1종의 존재 여부."""

    model_config = ConfigDict(frozen=True)

    model_id: str = Field(..., description="Ollama 모델 태그.")
    present: bool = Field(..., description="로컬에 적재돼 있는가.")


class AdminModelsResponse(BaseModel):
    """`GET /v1/admin/models` — `GET /status`와 **같은 수집 원천**을 쓴다.

    클라우드 3필드가 `None`일 수 있다: provider가 클라우드를 노출하지 않거나(로컬전용),
    `reachable`을 보고하지 않는 제공자(ARCH-57)다. **`False`가 아니라 `None`** 이라는 점이
    "도달 불가"와 "미측정"을 가르는 자리다.
    """

    model_config = ConfigDict(frozen=True)

    ready: bool = Field(..., description="필수 로컬 모델이 전부 적재됐는가.")
    reachable: bool = Field(..., description="로컬 추론 서버에 닿는가.")
    models: tuple[AdminModelRow, ...] = Field(..., description="모델별 적재 여부.")
    missing: tuple[str, ...] = Field(..., description="빠진 필수 모델 태그.")
    error: str | None = Field(None, description="로컬 점검 실패 사유(성공이면 None).")
    cloud_configured: bool | None = Field(
        None, description="클라우드 전송 가능 구성 여부(키 + 사용 허가 · 미노출=None)."
    )
    cloud_reachable: bool | None = Field(None, description="클라우드 도달성(**미측정=None**).")
    cloud_error: str | None = Field(
        None, description="클라우드 점검 실패 사유 — 사용 중단 방침 차단 사유 포함(ARCH-68)."
    )


@router.get(
    "/models",
    response_model=AdminModelsResponse,
    summary="모델 상태 매트릭스 — 로컬 적재 현황 + 클라우드 구성",
)
async def get_admin_models(request: Request, admin: RequireModelsAdmin) -> AdminModelsResponse:
    """provider를 점검해 보고한다. 추론 서버가 죽어 있어도 500이 아니라 상태로 답한다."""
    snapshot = await collect_model_status(request)
    local = snapshot.local
    return AdminModelsResponse(
        ready=local.all_present,
        reachable=local.reachable,
        models=tuple(AdminModelRow(model_id=m.model_id, present=m.present) for m in local.models),
        missing=tuple(local.missing),
        error=local.error,
        cloud_configured=snapshot.cloud_configured,
        cloud_reachable=snapshot.cloud_reachable,
        cloud_error=snapshot.cloud_error,
    )


# ── 비용 집계 ────────────────────────────────────────────────────────────────────────


class AdminCostDistribution(BaseModel):
    """분포 요약. 표본이 없으면 통계값이 전부 `None`이다(0이 아니다)."""

    model_config = ConfigDict(frozen=True)

    count: int = Field(..., description="표본 수.")
    p50: float | None = Field(None, description="중앙값(표본 없으면 None).")
    p90: float | None = Field(None, description="90분위(표본 없으면 None).")
    mean: float | None = Field(None, description="평균(표본 없으면 None).")
    total: float | None = Field(None, description="합계(표본 없으면 None).")


class AdminCostsResponse(BaseModel):
    """`GET /v1/admin/costs` — Langfuse 이벤트 집계.

    **`state`가 이 응답의 핵심 필드다.** Langfuse가 미설정이거나 죽었을 때 `event_count=0`만
    보이면 운영자는 "비용이 안 든 회차"와 "측정이 안 된 회차"를 구분할 수 없다 —
    04 §2 원칙6이 금지하는 바로 그 위장이다. 그래서 상태를 별도 값으로 낸다.
    """

    model_config = ConfigDict(frozen=True)

    state: Literal["measured", "unconfigured", "empty"] = Field(
        ...,
        description=(
            "measured=이벤트를 실제로 받아 집계함 · unconfigured=Langfuse 미설정(측정 불가) · "
            "empty=설정은 됐으나 기간 내 이벤트 0건. **unconfigured와 empty는 다른 사건이다.**"
        ),
    )
    days: int = Field(..., description="집계 기간(일).")
    event_count: int = Field(..., description="집계에 들어간 이벤트 수.")
    local_count: int = Field(..., description="로컬 모델 호출 수.")
    cloud_count: int = Field(..., description="클라우드 모델 호출 수.")
    local_ratio: float | None = Field(None, description="로컬 비율(**미상=None**).")
    cache_hit_rate: float | None = Field(None, description="프롬프트 캐시 적중률(미상=None).")
    cost_krw: AdminCostDistribution = Field(..., description="원화 비용 분포.")
    latency_ms: AdminCostDistribution = Field(..., description="지연 분포.")
    cost_tier_counts: dict[str, int] = Field(..., description="티어별 호출 수.")
    notes: tuple[str, ...] = Field(..., description="집계기가 남긴 한계·주의.")


def _distribution(dist: object) -> AdminCostDistribution:
    """`cost_report.Distribution` → 응답 모델. 필드 부재는 `None`으로 보존한다."""
    return AdminCostDistribution(
        count=int(getattr(dist, "count", 0)),
        p50=getattr(dist, "p50", None),
        p90=getattr(dist, "p90", None),
        mean=getattr(dist, "mean", None),
        total=getattr(dist, "total", None),
    )


@router.get(
    "/costs",
    response_model=AdminCostsResponse,
    summary="비용·라우팅 집계 — 측정 실패를 0건으로 위장하지 않는다",
)
async def get_admin_costs(
    admin: RequireCostAdmin,
    settings: SettingsDep,
    days: int = 7,
    limit: int = 500,
) -> AdminCostsResponse:
    """Langfuse 이벤트를 받아 집계한다.

    `fetch_l3_events`는 **동기 네트워크 I/O**라 `to_thread`로 넘긴다 — async 라우터에서 직접
    부르면 이벤트 루프를 막는다. 그 함수는 never-break라 예외를 밖으로 내지 않고 빈 리스트를
    주므로, "미설정"과 "0건"의 구분은 **설정 플래그로** 따로 판정한다(반환값만 보면 둘이 같다).
    """
    if days < 1 or days > 90:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="days는 1~90 범위여야 합니다.",
        )

    configured = bool(getattr(settings, "langfuse_configured", False))
    events: list[dict[str, object]] = []
    if configured:
        events = await anyio.to_thread.run_sync(
            lambda: fetch_l3_events(days=days, limit=limit, settings=settings)
        )
    report: CostReport = aggregate_l3_events(events)

    if not configured:
        state: Literal["measured", "unconfigured", "empty"] = "unconfigured"
    elif report.event_count == 0:
        state = "empty"
    else:
        state = "measured"

    return AdminCostsResponse(
        state=state,
        days=days,
        event_count=report.event_count,
        local_count=report.local_count,
        cloud_count=report.cloud_count,
        local_ratio=report.local_ratio,
        cache_hit_rate=report.cache_hit_rate,
        cost_krw=_distribution(report.cost_krw),
        latency_ms=_distribution(report.latency_ms),
        cost_tier_counts=dict(report.cost_tier_counts),
        notes=tuple(report.notes),
    )


# ── 검수 큐 ──────────────────────────────────────────────────────────────────────────


class AdminReviewDbAxis(BaseModel):
    """DB 축 — 적재된 문항의 검수 상태 분포. 설정과 무관하게 **항상 가용**하다."""

    model_config = ConfigDict(frozen=True)

    counts: dict[str, int] = Field(..., description="`ReviewStatus` 값별 문항 수.")
    unset: int = Field(..., description="`review_status`가 NULL인 문항 수(미판정).")
    total: int = Field(..., description="전체 문항 수.")


class AdminReviewQueueResponse(BaseModel):
    """`GET /v1/admin/review-queue` — 적재 문항의 검수 상태 분포.

    **생성 후보 큐(JSONL) 축은 이 PR에서 의도적으로 빠졌다.** 그 축을 읽으려면
    `harness.needs_review_worklist`를 import해야 하는데, 그 모듈이
    `l3.equivalent.orchestrator`를 끌어 `api.admin_bff → harness → l3.equivalent`라는
    **신규 잔여 전이 누수**가 생긴다. `RESIDUAL_LEAK_BASELINE`(tests/infra/
    test_eos_core_boundary_probe.py)은 **shrink-only 래칫**이라 신규 항목 추가가 설계상
    금지돼 있고, 내 편의로 그 기준선을 늘리는 것은 게이트를 느슨하게 하는 우회다. 그래서
    축을 줄이고 승계 태스크로 분리했다 — 선행은 그 harness 모듈의 어댑터 의존 절단이다.

    DB 축만 남아도 이 엔드포인트는 쓸모가 있다: 여기 보이는 것이 *실제로 적재된* 문항의
    검수 상태이고, JSONL은 적재 이전의 생성 후보라 축 자체가 다르다.
    """

    model_config = ConfigDict(frozen=True)

    db: AdminReviewDbAxis = Field(..., description="적재 문항 축.")


@router.get(
    "/review-queue",
    response_model=AdminReviewQueueResponse,
    summary="검수 큐 — 적재 문항 축 + 생성 후보 큐 축(이중 회계)",
)
async def get_admin_review_queue(
    admin: RequireReviewAdmin, session: SessionDep
) -> AdminReviewQueueResponse:
    """적재 문항의 검수 상태를 집계한다(모듈 docstring — JSONL 축은 승계 태스크)."""
    rows = (
        await session.execute(
            select(Problem.review_status, func.count()).group_by(Problem.review_status)
        )
    ).all()
    counts: dict[str, int] = {}
    unset = 0
    total = 0
    for value, count in rows:
        total += int(count)
        if value is None:
            unset += int(count)
            continue
        key = value.value if isinstance(value, ReviewStatus) else str(value)
        counts[key] = counts.get(key, 0) + int(count)

    return AdminReviewQueueResponse(db=AdminReviewDbAxis(counts=counts, unset=unset, total=total))


# ── 검수 큐 항목 · 상태 전이 (ADMIN-07 Phase B) ─────────────────────────────────────────


class AdminReviewItemRow(BaseModel):
    """검수 큐 목록 1행 — 가벼운 요약(문항 본문 제외)."""

    model_config = ConfigDict(frozen=True)

    problem_id: uuid.UUID = Field(..., description="문항 id.")
    review_status: str | None = Field(None, description="현재 검수 상태(미설정=None).")
    subject: str | None = Field(None, description="과목.")
    domain: str | None = Field(None, description="영역.")
    difficulty_overall: float | None = Field(None, description="코어 산출 난이도(그대로 표시).")
    source_type: str | None = Field(None, description="출처 유형.")
    review_score: float | None = Field(None, description="코어 산출 검수 점수(그대로 표시).")
    created_at: str | None = Field(None, description="적재 시각(ISO).")


class AdminReviewItemsResponse(BaseModel):
    """`GET /v1/admin/review-queue/items` — 상태별 페이지."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(..., description="조회한 검수 상태.")
    total: int = Field(..., description="그 상태의 전체 건수.")
    limit: int = Field(..., description="페이지 크기.")
    offset: int = Field(..., description="건너뛴 건수.")
    items: tuple[AdminReviewItemRow, ...] = Field(
        ..., description="created_at·problem_id 오름차순."
    )


class AdminReviewItemDetail(BaseModel):
    """`GET /v1/admin/review-queue/items/{id}` — 검수에 필요한 본문과 서버 판정 허용 액션."""

    model_config = ConfigDict(frozen=True)

    problem_id: uuid.UUID = Field(..., description="문항 id.")
    review_status: str | None = Field(None, description="현재 검수 상태(미설정=None).")
    question_text: str | None = Field(None, description="문항 본문(렌더러-중립 원문).")
    choices: list[str] | None = Field(None, description="선택지.")
    answer: str | None = Field(None, description="정답.")
    answer_explanation: str | None = Field(None, description="해설.")
    subject: str | None = Field(None, description="과목.")
    domain: str | None = Field(None, description="영역.")
    difficulty_overall: float | None = Field(None, description="코어 산출 난이도(그대로 표시).")
    source_type: str | None = Field(None, description="출처 유형.")
    review_score: float | None = Field(None, description="코어 산출 검수 점수(그대로 표시).")
    quarantine_reason: str | None = Field(None, description="격리 사유(없으면 None).")
    quarantined_at: str | None = Field(None, description="격리 시각(ISO · 없으면 None).")
    created_at: str | None = Field(None, description="적재 시각(ISO).")
    allowed_actions: tuple[str, ...] = Field(
        ..., description="현재 상태에서 허용되는 전이 액션 — 서버 전이표가 정본(프런트 재구현 금지)"
    )


class AdminReviewTransitionRequest(BaseModel):
    """`POST …/transitions` 본문."""

    model_config = ConfigDict(extra="forbid")

    action: ReviewTransitionAction = Field(..., description="적용할 전이 액션.")
    expected_status: ReviewStatus = Field(
        ..., description="화면이 본 현재 상태 — 서버 현재값과 다르면 409(낙관적 동시성)."
    )
    reason: str | None = Field(
        None,
        max_length=QUARANTINE_REASON_MAX_LENGTH,
        description="격리 사유 — quarantine이면 필수(공백 제외 1자 이상). 그 외는 기록 안 됨.",
    )

    @model_validator(mode="after")
    def _reason_required_for_quarantine(self) -> AdminReviewTransitionRequest:
        if action_requires_reason(self.action) and not (self.reason or "").strip():
            raise ValueError("이 액션은 사유(reason)가 필요합니다(공백 제외 1자 이상).")
        return self


class AdminReviewTransitionResponse(BaseModel):
    """전이 결과 — 감사 행 id를 함께 낸다."""

    model_config = ConfigDict(frozen=True)

    problem_id: uuid.UUID = Field(..., description="문항 id.")
    from_status: str = Field(..., description="전이 전 상태.")
    to_status: str = Field(..., description="전이 후 상태.")
    audit_id: uuid.UUID = Field(..., description="이 전이의 감사 행 id.")
    occurred_at: str = Field(..., description="전이 시각(ISO).")


def _status_value(value: ReviewStatus | str | None) -> str | None:
    if value is None:
        return None
    return value.value if isinstance(value, ReviewStatus) else str(value)


def _enum_value(value: object) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _float_or_none(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


@router.get(
    "/review-queue/items",
    response_model=AdminReviewItemsResponse,
    summary="검수 큐 목록 — 상태별 페이지(본문 제외)",
)
async def list_admin_review_items(
    admin: RequireReviewAdmin,
    session: SessionDep,
    status_: Annotated[ReviewStatus, Query(alias="status")] = ReviewStatus.pending,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminReviewItemsResponse:
    """`status` 상태의 문항을 `created_at ASC, problem_id ASC`(안정 정렬)로 돌려준다."""
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(Problem).where(Problem.review_status == status_)
            )
        ).scalar()
        or 0
    )
    rows = (
        await session.execute(
            select(
                Problem.problem_id,
                Problem.review_status,
                Problem.subject,
                Problem.domain,
                Problem.difficulty_overall,
                Problem.source_type,
                Problem.review_score,
                Problem.created_at,
            )
            .where(Problem.review_status == status_)
            .order_by(Problem.created_at.asc(), Problem.problem_id.asc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return AdminReviewItemsResponse(
        status=status_.value,
        total=total,
        limit=limit,
        offset=offset,
        items=tuple(
            AdminReviewItemRow(
                problem_id=r.problem_id,
                review_status=_status_value(r.review_status),
                subject=_enum_value(r.subject),
                domain=r.domain,
                difficulty_overall=_float_or_none(r.difficulty_overall),
                source_type=_enum_value(r.source_type),
                review_score=_float_or_none(r.review_score),
                created_at=_iso(r.created_at),
            )
            for r in rows
        ),
    )


@router.get(
    "/review-queue/items/{problem_id}",
    response_model=AdminReviewItemDetail,
    summary="검수 큐 단건 — 본문 + 서버 판정 허용 액션",
)
async def get_admin_review_item(
    problem_id: uuid.UUID, admin: RequireReviewAdmin, session: SessionDep
) -> AdminReviewItemDetail:
    """코어 산출값(`review_score` 등)은 있는 그대로 투영한다 — 재계산·재해석 없음."""
    problem = await session.get(Problem, problem_id)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="문항을 찾을 수 없습니다."
        )
    current = problem.review_status
    return AdminReviewItemDetail(
        problem_id=problem.problem_id,
        review_status=_status_value(current),
        question_text=problem.question_text,
        choices=problem.choices,
        answer=problem.answer,
        answer_explanation=problem.answer_explanation,
        subject=_enum_value(problem.subject),
        domain=problem.domain,
        difficulty_overall=_float_or_none(problem.difficulty_overall),
        source_type=_enum_value(problem.source_type),
        review_score=_float_or_none(problem.review_score),
        quarantine_reason=problem.quarantine_reason,
        quarantined_at=_iso(problem.quarantined_at),
        created_at=_iso(problem.created_at),
        allowed_actions=tuple(a.value for a in allowed_actions(current)),
    )


def _transition_conflict(code: str, message: str, current: ReviewStatus | None) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message, "current_status": _status_value(current)},
    )


@router.post(
    "/review-queue/items/{problem_id}/transitions",
    response_model=AdminReviewTransitionResponse,
    summary="검수 상태 전이 — 행 잠금 + 전이표 검증 + 감사 1행(단일 트랜잭션)",
)
async def transition_admin_review_item(
    problem_id: uuid.UUID,
    body: AdminReviewTransitionRequest,
    request: Request,
    admin: RequireReviewAdmin,
    session: SessionDep,
    settings: SettingsDep,
) -> AdminReviewTransitionResponse:
    """한 트랜잭션에서 잠금 → 낙관적 동시성 → 전이표 → 갱신 → 감사 1행 → commit 1회.

    전이 규칙은 `schema/review_transition.py`가 정본이고 여기서는 호출만 한다. 어느 단계든
    실패하면 commit 전이므로 상태도 감사 행도 남지 않는다(감사 쓰기 실패 시 상태 변경도 롤백).
    `review_status`를 쓰는 다른 관리자 표면 `PATCH /v1/problems/{id}`는 ADMIN-16부터 같은 표
    (`action_for_status_change` 역해석)를 거친다 — 전이 규칙의 집행 지점은 이 라우트와
    그 PATCH 둘이다.
    """
    problem = (
        await session.execute(
            select(Problem)
            .where(Problem.problem_id == problem_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="문항을 찾을 수 없습니다."
        )

    current = problem.review_status
    if current != body.expected_status:
        raise _transition_conflict(
            "stale_status", "화면의 상태가 최신이 아닙니다. 새로고침 후 다시 시도하세요.", current
        )
    try:
        target = resolve_review_transition(current, body.action)
    except IllegalReviewTransition as exc:
        raise _transition_conflict(
            "illegal_transition", "현재 상태에서 허용되지 않는 전이입니다.", current
        ) from exc

    occurred_at = datetime.now(UTC)
    problem.review_status = target
    # 사람이 바꾼 검수·격리 상태 — 다음 CLI 적재가 코퍼스 초기값으로 되돌리지 못하게
    # 표지를 남긴다(P3-25).
    mark_cms_edited(problem, at=occurred_at)
    if body.action is ReviewTransitionAction.quarantine:
        # 격리 계약 §3 — 사유·시각을 상태와 함께 쓴다. release/approve/reject는 이 필드를 건드리지
        # 않는다(§5-2: 회수 이력은 해제 후에도 영구 기록).
        problem.quarantine_reason = (body.reason or "").strip()
        problem.quarantined_at = occurred_at

    try:
        audit = record_content_mutation_audit(
            session,
            actor_user_id=admin.user_id,
            resource_type=PrivacyAuditResourceType.problem,
            resource_id=problem_id,
            action=PrivacyAuditAction(body.action.value),
            ip=_client_ip(request, settings=settings),
            settings=settings,
        )
        await session.flush()  # 서버 기본값(audit_id)을 받아 오되 commit은 아래 1회뿐이다.
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    return AdminReviewTransitionResponse(
        problem_id=problem_id,
        from_status=current.value,
        to_status=target.value,
        audit_id=audit.audit_id,
        occurred_at=occurred_at.isoformat(),
    )


# ── 사용자 조회 ──────────────────────────────────────────────────────────────────────


class AdminUserAggregateResponse(BaseModel):
    """`GET /v1/admin/users` — **집계만**. 개별 사용자 행이 없으므로 PII가 0이다.

    목록에 per-user 행을 실으면 두 가지가 동시에 깨진다: ①원자료가 프런트로 나가고(원칙2)
    ②관리자 접근 감사가 조회 1회당 사용자 수만큼 폭발해 감사 대장이 무의미해진다. 그래서
    목록은 집계, 단건은 마스킹+감사로 나눴다.
    """

    model_config = ConfigDict(frozen=True)

    total: int = Field(..., description="전체 사용자 수(삭제 표시 포함).")
    active: int = Field(..., description="`is_active`인 사용자 수.")
    deleted: int = Field(..., description="`is_deleted`인 사용자 수.")
    minors: int = Field(..., description="`is_minor`인 사용자 수(미성년 보호 대상 규모).")
    by_role: dict[str, int] = Field(..., description="역할별 수.")
    by_subscription_tier: dict[str, int] = Field(..., description="구독 티어별 수(미설정 제외).")


class AdminUserDetailResponse(BaseModel):
    """`GET /v1/admin/users/{user_id}` — 마스킹된 단건.

    **싣지 않는 것**: `email_hash`·`parent_email_hash`(직접 식별자 — `api/users.py`의
    `_PII_EXCLUDE` 선례와 같은 축), 사교육 현황·진단 원점수 같은 프로파일링 필드. 운영자가
    계정을 특정·지원하는 데 필요한 최소 필드만 남긴다.

    `nickname`은 마스킹해서 낸다 — 운영자가 "맞는 계정인지" 확인하는 데는 앞 글자로 충분하고,
    전체 노출은 미성년 개인정보를 화면에 띄우는 것이다.
    """

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID = Field(..., description="사용자 식별자.")
    nickname_masked: str | None = Field(None, description="닉네임 마스킹(앞 1자 + ***).")
    role: str = Field(..., description="인가 역할.")
    grade: int | None = Field(None, description="학년.")
    school_type: str | None = Field(None, description="학교 유형.")
    persona_primary: str = Field(..., description="1차 페르소나.")
    subscription_tier: str | None = Field(None, description="구독 티어.")
    is_minor: bool | None = Field(None, description="미성년 여부.")
    parent_consent_at: str | None = Field(None, description="법정대리인 동의 시각(ISO).")
    is_active: bool = Field(..., description="활성 여부.")
    is_deleted: bool = Field(..., description="삭제 표시 여부.")
    created_at: str | None = Field(None, description="가입 시각(ISO).")
    last_active_at: str | None = Field(None, description="마지막 활동 시각(ISO).")


def mask_nickname(nickname: str | None) -> str | None:
    """닉네임 마스킹 — 앞 1자만 남기고 `***`.

    저장소에 부분 마스킹 헬퍼가 없어 여기서 만든다(`ops/log_scrubber`는 로그 전용이고
    `api/users.py::_PII_EXCLUDE`는 *필드 제외*이지 마스킹이 아니다). 빈 문자열과 `None`을
    구분해 유지한다 — 빈 닉네임을 `None`으로 접으면 "닉네임 없음"과 "닉네임 미설정"이
    같아진다.
    """
    if nickname is None:
        return None
    if not nickname:
        return ""
    return f"{nickname[0]}***"


def _iso(value: object) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


@router.get(
    "/users",
    response_model=AdminUserAggregateResponse,
    summary="사용자 집계 — 개별 행·PII 없음",
)
async def get_admin_user_aggregate(
    admin: RequireUserAdmin, session: SessionDep
) -> AdminUserAggregateResponse:
    """역할·티어·미성년 규모를 집계한다. 개별 사용자는 나가지 않으므로 감사 행도 남기지 않는다."""
    total = int(
        (await session.execute(select(func.count()).select_from(UserProfile))).scalar() or 0
    )
    active = int(
        (
            await session.execute(
                select(func.count()).select_from(UserProfile).where(UserProfile.is_active.is_(True))
            )
        ).scalar()
        or 0
    )
    deleted = int(
        (
            await session.execute(
                select(func.count())
                .select_from(UserProfile)
                .where(UserProfile.is_deleted.is_(True))
            )
        ).scalar()
        or 0
    )
    minors = int(
        (
            await session.execute(
                select(func.count()).select_from(UserProfile).where(UserProfile.is_minor.is_(True))
            )
        ).scalar()
        or 0
    )

    by_role: dict[str, int] = {}
    for value, count in (
        await session.execute(select(UserProfile.role, func.count()).group_by(UserProfile.role))
    ).all():
        key = getattr(value, "value", None) or str(value)
        by_role[key] = by_role.get(key, 0) + int(count)

    by_tier: dict[str, int] = {}
    for value, count in (
        await session.execute(
            select(UserProfile.subscription_tier, func.count()).group_by(
                UserProfile.subscription_tier
            )
        )
    ).all():
        if value is None:
            continue
        key = getattr(value, "value", None) or str(value)
        by_tier[key] = by_tier.get(key, 0) + int(count)

    return AdminUserAggregateResponse(
        total=total,
        active=active,
        deleted=deleted,
        minors=minors,
        by_role=by_role,
        by_subscription_tier=by_tier,
    )


@router.get(
    "/users/{user_id}",
    response_model=AdminUserDetailResponse,
    summary="사용자 단건(마스킹) — 관리자 접근 감사 1행을 남긴다",
)
async def get_admin_user_detail(
    user_id: uuid.UUID,
    request: Request,
    admin: RequireUserAdmin,
    session: SessionDep,
    settings: SettingsDep,
) -> AdminUserDetailResponse:
    """타인 개인정보 접근이므로 **반드시 감사 행을 남긴다**(04 §2 원칙4).

    `record_admin_access_audit`은 SEC-29가 "대상 호출부가 없어(ADMIN-06 선행) 그대로 두고"
    남겨 둔 함수이고, 이 라우트가 그 **첫 호출부**다. 그 함수는 `session.add`만 하고 commit은
    호출자 책임이므로(주행위와 같은 트랜잭션 합류가 문서화된 불변식) 여기서 commit한다 —
    조회 자체는 쓰기가 없지만 감사 행은 쓰기다.

    본인 조회에도 감사를 남긴다. 예외를 두면 "본인이면 안 남는다"가 되고, 운영자 계정이
    피조회자와 같은 경우를 구분하려면 결국 감사 대장을 봐야 하는데 그 행이 없다.
    """
    target = await session.get(UserProfile, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="사용자를 찾을 수 없습니다."
        )

    record_admin_access_audit(
        session,
        actor_user_id=admin.user_id,
        target_user_id=target.user_id,
        ip=_client_ip(request, settings=settings),
        settings=settings,
    )
    await session.commit()

    return AdminUserDetailResponse(
        user_id=target.user_id,
        nickname_masked=mask_nickname(target.nickname),
        role=getattr(target.role, "value", None) or str(target.role),
        grade=target.grade,
        school_type=getattr(target.school_type, "value", None),
        persona_primary=getattr(target.persona_primary, "value", None)
        or str(target.persona_primary),
        subscription_tier=getattr(target.subscription_tier, "value", None),
        is_minor=target.is_minor,
        parent_consent_at=_iso(target.parent_consent_at),
        is_active=target.is_active,
        is_deleted=target.is_deleted,
        created_at=_iso(target.created_at),
        last_active_at=_iso(target.last_active_at),
    )
