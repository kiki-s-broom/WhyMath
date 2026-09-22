"""Admin BFF — `/v1/admin/*` 운영 조회 표면 (ADMIN-05 · 04 §2 원칙2).

엔드포인트 (전부 GET — **Phase A는 read-only**, 쓰기는 ADMIN-07 Phase B):
  - GET /v1/admin/models        — 모델 상태 매트릭스(로컬 Ollama + 클라우드 구성)
  - GET /v1/admin/costs         — 비용·라우팅 집계(Langfuse 이벤트 → cost_report)
  - GET /v1/admin/review-queue  — 검수 큐(DB 축 + JSONL 축 이중 회계)
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
from pathlib import Path
from typing import Annotated, Literal

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api._model_status import collect_model_status
from whymath_backend.api._rate_limit import _client_ip
from whymath_backend.api.admin_module_registry import require_module_roles
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.ops.cost_report import CostReport, aggregate_l3_events, fetch_l3_events
from whymath_backend.privacy import record_admin_access_audit
from whymath_backend.schema.enums import ReviewStatus

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
    cloud_configured: bool | None = Field(None, description="클라우드 키 구성 여부(미노출=None).")
    cloud_reachable: bool | None = Field(None, description="클라우드 도달성(**미측정=None**).")
    cloud_error: str | None = Field(None, description="클라우드 점검 실패 사유.")


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


class AdminReviewJsonlAxis(BaseModel):
    """JSONL 축 — 생성 후보 큐. **문항 본문은 싣지 않는다.**

    `ReviewQueueEntry.candidate_payload`에는 문항 본문 전문이 들어 있어 학생 대면·외부 노출이
    금지된 자산이다. 콘솔 목록에 필요한 것은 개수와 상태 분포뿐이므로 본문은 아예 꺼내지 않는다
    (저작권 레일 — 필요해지면 그때 별도 인가를 붙여 단건으로 연다).
    """

    model_config = ConfigDict(frozen=True)

    state: Literal["unconfigured", "missing", "unreadable", "loaded"] = Field(
        ...,
        description=(
            "unconfigured=경로 미설정 · missing=설정된 경로에 파일 없음 · unreadable=읽기 실패 · "
            "loaded=읽음. **앞의 셋은 '0건'이 아니라 '미측정'이다.**"
        ),
    )
    counts: dict[str, int] = Field(
        default_factory=dict, description="상태값별 항목 수(loaded일 때만 의미 있음)."
    )
    total: int = Field(0, description="유효 항목 수.")
    load_error_count: int = Field(0, description="파싱 실패한 줄 수(조용히 버리지 않는다).")
    detail: str | None = Field(None, description="미측정·실패 사유(경로 문자열은 싣지 않는다).")


class AdminReviewQueueResponse(BaseModel):
    """`GET /v1/admin/review-queue` — 두 축을 **함께** 낸다(04 §2 원칙6 이중 회계).

    한 축만 내면 그 축의 원천이 죽었을 때 화면이 비고, 빈 화면은 "검수할 것이 없다"로 읽힌다.
    두 축을 나란히 두면 한쪽이 미측정이어도 다른 쪽이 살아 있고, 무엇이 미측정인지도 보인다.
    """

    model_config = ConfigDict(frozen=True)

    db: AdminReviewDbAxis = Field(..., description="적재 문항 축.")
    jsonl: AdminReviewJsonlAxis = Field(..., description="생성 후보 큐 축.")


def _load_jsonl_axis(raw_path: str) -> AdminReviewJsonlAxis:
    """JSONL 큐를 읽어 축 요약을 만든다. **동기 파일 I/O** — 호출부가 to_thread로 감싼다."""
    if not raw_path.strip():
        return AdminReviewJsonlAxis(
            state="unconfigured",
            detail="검수 큐 경로가 설정되지 않았습니다(admin_review_queue_path).",
        )
    path = Path(raw_path)
    if not path.is_file():
        return AdminReviewJsonlAxis(
            state="missing", detail="설정된 경로에 검수 큐 파일이 없습니다."
        )
    # 지연 import — `harness`는 조회 경로의 선택적 원천이라 모듈 로드 비용을 상시 지불하지 않는다.
    from whymath_backend.harness.needs_review_worklist import load_review_queue_jsonl

    try:
        entries, load_errors = load_review_queue_jsonl(path)
    except Exception as exc:  # noqa: BLE001 — 사유는 타입명으로 남긴다(침묵 실패 금지)
        return AdminReviewJsonlAxis(
            state="unreadable", detail=f"검수 큐를 읽지 못했습니다({type(exc).__name__})."
        )
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    return AdminReviewJsonlAxis(
        state="loaded",
        counts=counts,
        total=len(entries),
        load_error_count=len(load_errors),
    )


@router.get(
    "/review-queue",
    response_model=AdminReviewQueueResponse,
    summary="검수 큐 — 적재 문항 축 + 생성 후보 큐 축(이중 회계)",
)
async def get_admin_review_queue(
    admin: RequireReviewAdmin,
    session: SessionDep,
    settings: SettingsDep,
) -> AdminReviewQueueResponse:
    """DB 축은 항상, JSONL 축은 설정·파일이 있을 때만 실측한다."""
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

    raw_path = str(getattr(settings, "admin_review_queue_path", "") or "")
    jsonl = await anyio.to_thread.run_sync(_load_jsonl_axis, raw_path)

    return AdminReviewQueueResponse(
        db=AdminReviewDbAxis(counts=counts, unset=unset, total=total),
        jsonl=jsonl,
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
