"""FastAPI 앱 — L3 라우터 ↔ Ollama·Celery 결선의 HTTP 표면 (M1.2-live S1·S4).

엔드포인트:
  - GET  /health         — 라이브니스(의존성 없음, 항상 200 — 하위호환 유지)
  - GET  /health/live    — 라이브니스 전용 경로(OPS-01·/health와 동일 의미)
  - GET  /health/ready   — 레디니스 딥체크(OPS-01·DB SELECT 1/Redis PING/LLM 라우터 +
                           인프로세스 metrics·alerts. DB 미도달 시 503 — 업타임 프로브용)
  - GET  /status         — Ollama 도달성·모델 매트릭스 설치 여부 *보고형*(항상 200)
  - POST /v1/generate    — 라우팅 → (동기) 캐시·생성 텍스트 / (비동기 QUALITY) 202 + job_id
  - GET  /v1/jobs/{id}   — QUALITY 비동기 작업 폴링(상태 + 완료 시 텍스트, S4)

`create_app()`은 의존성(provider·cache·trace·queue)을 주입받는 팩토리다 — 테스트는
가짜를 넣고, 프로덕션은 OllamaProvider + RedisCache(S2) + LangfuseSink(S3) +
CeleryJobQueue(S4)를 기본으로 쓴다. 넷 모두 *지연*이라 앱 구성만으로 라이브 Redis·
Langfuse·Celery broker가 필요하지 않다(첫 사용 시 연결). LangfuseSink는 키 미설정 시
영구 no-op이라 CI에서도 안전하다 — 트레이싱 장애는 학생 생성을 절대 깨뜨리지 않는다
(CLAUDE.md 우선순위 #1 ≫ #6).

경계 메모 (CLAUDE.md 절대 금기): /v1/generate·/v1/jobs가 돌려주는 텍스트는 *검증 전
원시 모델 출력*이다. 03 문서 환각 방어 파이프라인 통과 전에는 학생에게 직접 노출 금지
("LLM 응답을 검증 없이 학생에게 제공 금지").

인가(SEC-07 D1): `/v1/generate`는 이전엔 인증 의존성이 0건이라 무인증 LLM 비용 남용 표면이었다
(실측 `docs/architecture/account_security_gap_review.md` D1). `CurrentUser`(인증만 — 역할
불문)로 게이팅한다: 콘텐츠 CUD(`Role.CONTENT_ADMIN`)와 달리 이 엔드포인트는 *인증된 어느
사용자든* 호출할 수 있어야 하는 저수준 L3 raw 생성 표면이라(orchestrator·teacher tooling 등
소비처가 아직 특정 역할로 좁혀지지 않음) `require_content_admin`이 아니라 인증 존재만 요구한다.
`/v1/jobs/{id}`(폴링)도 같은 `CurrentUser` 게이트다(SEC-24(원 SEC-15) —
`functional_security_audit_2026-08-08.md` M6): SEC-07 당시 "범위 밖"으로 남겨졌던 폴링이
무인증인 채 검증 전 원시 LLM 출력을 반환하고 있었다(짝인 POST는 봉인·폴링만 열림).

소유권(job↔user) 검사(SEC-27, 48_보안 §P0): `job_ownership` 테이블(`db/models/
job_ownership.py`)이 `POST /v1/generate`의 큐잉 시점에 (job_id, user_id)를 기록하고,
`GET /v1/jobs/{id}`가 그 행으로 소유자를 대조해 타 사용자 job 폴링을 404로 거부한다
(매핑 부재도 동일하게 404 — 존재 자체를 노출하지 않음).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from whymath_backend.api._auth import CurrentUser, has_scope_consent
from whymath_backend.api._device_store import (
    build_device_store_from_settings,
    ping_device_store_health,
    set_device_store,
)
from whymath_backend.api._growth_evidence_state import (
    GROWTH_EVIDENCE_EXPOSURE_COUNTERS_KEY,
    GrowthEvidenceReachCounters,
    GrowthEvidenceReachSnapshot,
    get_growth_evidence_counters,
    set_growth_evidence_counters,
)
from whymath_backend.api._l3_state import (
    CACHE_KEY as _CACHE_KEY,
)
from whymath_backend.api._l3_state import (
    PROVIDER_KEY as _PROVIDER_KEY,
)
from whymath_backend.api._l3_state import (
    QUEUE_KEY as _QUEUE_KEY,
)
from whymath_backend.api._l3_state import (
    TRACE_KEY as _TRACE_KEY,
)
from whymath_backend.api._l3_state import (
    get_cache as _get_cache,
)
from whymath_backend.api._l3_state import (
    get_provider as _get_provider,
)
from whymath_backend.api._l3_state import (
    get_queue as _get_queue,
)
from whymath_backend.api._l3_state import (
    get_trace as _get_trace,
)
from whymath_backend.api._l6_mode_reach_state import (
    L6ModeReachCounters,
    L6ModeReachSnapshot,
    get_l6_mode_reach_counters,
    set_l6_mode_reach_counters,
)
from whymath_backend.api._misconception_state import get_semantic_matcher
from whymath_backend.api._ocr_state import (
    OCR_COUNTERS_KEY as _OCR_COUNTERS_KEY,
)
from whymath_backend.api._ocr_state import (
    OcrReachCounters,
    OcrReachSnapshot,
    set_ocr_components,
)
from whymath_backend.api._ocr_state import (
    get_ocr_reach_snapshot as _get_ocr_reach_snapshot,
)
from whymath_backend.api._segmentation_state import (
    SEGMENTATION_COUNTERS_KEY as _SEGMENTATION_COUNTERS_KEY,
)
from whymath_backend.api._segmentation_state import (
    SolutionSegmentationCounters,
    SolutionSegmentationSnapshot,
)
from whymath_backend.api._segmentation_state import (
    get_segmentation_snapshot as _get_segmentation_snapshot,
)
from whymath_backend.api._subject_capability_state import (
    ANSWER_FORM_VERIFIER_KEY as _ANSWER_FORM_VERIFIER_KEY,
)
from whymath_backend.api._subject_capability_state import (
    ASSESSMENT_ANSWER_VERIFIER_KEY as _ASSESSMENT_ANSWER_VERIFIER_KEY,
)
from whymath_backend.api._subject_capability_state import (
    ATTEMPT_MISCONCEPTION_DETECTOR_KEY as _ATTEMPT_MISCONCEPTION_DETECTOR_KEY,
)
from whymath_backend.api._subject_capability_state import (
    EXPRESSION_EQUIVALENCE_KEY as _EXPRESSION_EQUIVALENCE_KEY,
)
from whymath_backend.api._subject_capability_state import (
    EXPRESSION_SEAL_KEY as _EXPRESSION_SEAL_KEY,
)
from whymath_backend.api._subject_capability_state import (
    FINAL_ANSWER_VERIFIER_KEY as _FINAL_ANSWER_VERIFIER_KEY,
)
from whymath_backend.api._subject_capability_state import (
    STEP_CHAIN_VERIFIER_KEY as _STEP_CHAIN_VERIFIER_KEY,
)
from whymath_backend.api.admin_menu import router as admin_menu_router
from whymath_backend.api.alignments import router as alignments_router
from whymath_backend.api.auth import (
    OAUTH_PROVIDERS_KEY as _OAUTH_PROVIDERS_KEY,
)
from whymath_backend.api.auth import (
    OAuthProvider,
)
from whymath_backend.api.auth import (
    router as auth_router,
)
from whymath_backend.api.coach import router as coach_router
from whymath_backend.api.concepts import router as concepts_router
from whymath_backend.api.curricula import router as curricula_router
from whymath_backend.api.devices import router as devices_router
from whymath_backend.api.dsl import router as dsl_router
from whymath_backend.api.gating import router as gating_router
from whymath_backend.api.interactions import router as interactions_router
from whymath_backend.api.me import router as me_router
from whymath_backend.api.oauth_providers import build_oauth_providers
from whymath_backend.api.ocr import router as ocr_router
from whymath_backend.api.privacy import router as privacy_router
from whymath_backend.api.problems import router as problems_router
from whymath_backend.api.reports import router as reports_router
from whymath_backend.api.rights import router as rights_router
from whymath_backend.api.scene import router as scene_router
from whymath_backend.api.solution_paths import router as solution_paths_router
from whymath_backend.api.speech import router as speech_router
from whymath_backend.api.study import router as study_router
from whymath_backend.api.users import router as users_router
from whymath_backend.api.verify import router as verify_router
from whymath_backend.api.visualization import router as visualization_router
from whymath_backend.composition import (
    default_answer_form_verifier,
    default_assessment_answer_verifier,
    default_attempt_misconception_detector,
    default_expression_equivalence,
    default_expression_seal,
    default_final_answer_verifier,
    default_step_chain_verifier,
)
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.job_ownership import JobOwnership
from whymath_backend.db.schema_version import verify_schema_version
from whymath_backend.db.session import dispose_engine, get_session
from whymath_backend.l3 import pipeline
from whymath_backend.l3.cache import RedisCache
from whymath_backend.l3.interfaces import (
    AsyncJobQueue,
    CacheBackend,
    LLMProvider,
    TraceSink,
)
from whymath_backend.l3.models import RoutingDecision, RoutingRequest
from whymath_backend.l3.pipeline import QualityQueueUnavailableError
from whymath_backend.l3.pregenerate.validator import (
    SeedValidator,
    default_seed_validator,
    validate_response,
)
from whymath_backend.l3.providers.anthropic import AnthropicProvider
from whymath_backend.l3.providers.cloud_status import CloudStatus
from whymath_backend.l3.providers.composite import CompositeProvider
from whymath_backend.l3.providers.ollama import OllamaProvider, OllamaStatus
from whymath_backend.l3.queue import CeleryJobQueue
from whymath_backend.l3.trace import LangfuseSink
from whymath_backend.l5.ocr.factory import build_ocr_components
from whymath_backend.ops.log_scrubber import install_log_scrubber
from whymath_backend.ops.service_health import (
    AlertLogNotifier,
    ComponentCheck,
    MetricsSnapshot,
    ReadinessProbes,
    ServiceMetrics,
    default_readiness_probes,
    evaluate_alerts,
)
from whymath_backend.schema.enums import ConsentScope

# 앱 state 의존 키 — provider/cache/trace/queue는 `api/_l3_state.py`로 추출(라우터 공유,
# slice 96)해 위에서 별칭 import. validator/skip-cache는 /v1/generate 전용이라 여기 둔다.
_VALIDATOR_KEY = "shadow_validator"
_SKIP_CACHE_KEY = "skip_cache_on_signal"
# OPS-01 인프로세스 관측성 키 — 계측·알림·레디니스 probes(테스트가 state로 접근 가능).
_METRICS_KEY = "service_metrics"
_ALERT_NOTIFIER_KEY = "service_alert_notifier"
_READY_PROBES_KEY = "readiness_probes"

# 계측 제외 경로(OPS-01) — 업타임 프로브·운영 폴링 경로는 요청 계측에서 뺀다. 넣으면
# 프로브 폴링이 표본을 지배하고, 특히 DB 다운 시 /health/ready 503 폭주가 5xx 에러율을
# *자기증폭*시킨다(관측이 관측을 오염). 학생·API 트래픽만 계측한다.
_OPS_PROBE_PATHS = frozenset({"/health", "/health/live", "/health/ready", "/status"})

# OPS-17: 클라 최소 버전 게이트 — 헤더 이름 + '미상(unknown)' 경량 카운터의 app.state 키.
# 신규 미들웨어를 만들지 않고 기존 `_service_metrics_middleware`(OPS-01) 좌석에 얹는다(아래
# create_app 참조). 헤더 부재/파싱 불가는 '미달'(426 차단)과 다른 '미상'으로, 차단과 무관한
# 롤아웃 추적 신호로만 계상한다(임계는 `Settings.min_app_version`).
_APP_VERSION_HEADER = "X-App-Version"
_VERSION_UNKNOWN_COUNT_KEY = "app_version_unknown_count"

logger = logging.getLogger(__name__)

# /v1/generate의 런타임 shadow 검증기 — 결정론 관계 검증(=·<·>·≤·≥·≠·연쇄). 모듈 1회
# 생성(I/O 없음·재사용). 비차단(반환 텍스트·캐시 불변)이라 default-on이 안전 — 워커
# (`_WORKER_SHADOW_VALIDATOR`, slice 43)와 같은 관측 정책을 동기 HTTP 경로에 적용한다.
# 실제 활성 여부는 `Settings.l3_shadow_validation_enabled`로 게이트(create_app에서 결정).
_SHADOW_VALIDATOR = default_seed_validator()


def _parse_app_version(version: str) -> tuple[int, int, int] | None:
    """`X.Y.Z`(빌드번호 없음) 버전 문자열을 정수 3튜플로 파싱 — 순수 함수(OPS-17).

    외부 semver 라이브러리 없이 `tuple(int, ...)` 비교로 충분하다(정책 확정). 정확히
    3개의 정수 부분이 아니면(형식 위반·빈 문자열·`1.2`·`1.2.3.4`·`1.2.x` 등) **조용히
    넘어가지 않고 None을 반환**한다 — 호출부가 이를 '미상'(차단하지 않음·관측만)으로
    명시 처리한다(CLAUDE.md 침묵 실패 금지 — 여기서는 예외를 삼키는 대신 "판정 불가"를
    타입으로 드러낸다).
    """
    parts = version.strip().split(".")
    if len(parts) != 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


# ──────────────────────────────────────────────────────────────────────────
# 요청/응답 스키마 (HTTP 표면)
# ──────────────────────────────────────────────────────────────────────────
class GenerateBody(BaseModel):
    """POST /v1/generate 본문 — 라우팅 입력 + 프롬프트.

    `request`는 라우팅 신호(RoutingRequest, extra=forbid)를 그대로 받는다. 평탄화
    대신 중첩을 쓰는 이유: RoutingRequest가 추가 필드를 금지하므로 prompt·system을
    섞으면 검증이 깨진다. 중첩이 필드 드리프트도 막는다.
    """

    request: RoutingRequest = Field(..., description="라우팅 입력 신호 (03a §B.1)")
    prompt: str = Field(..., description="사용자 프롬프트(검증 전 원시 입력)")
    system: str = Field(default="", description="시스템 프롬프트")


class GenerateResponseBody(BaseModel):
    """POST /v1/generate 응답(동기 완료) — 생성 텍스트 + 라우팅 메타데이터.

    `text`는 검증 전 원시 출력이다(앱 docstring 경계 메모 참조).
    """

    text: str = Field(..., description="생성된 원시 텍스트(검증 전 — 학생 직접 노출 금지)")
    cache_hit: bool = Field(..., description="캐시 적중 여부 (KPI, 03a §F.1)")
    decision: RoutingDecision = Field(..., description="라우팅 결정 메타데이터 (03a §G)")
    validation_signal: str | None = Field(
        default=None,
        description=(
            "런타임 shadow 검증 환각 신호(비차단·관측). None=통과/미검증(캐시 히트 포함), "
            "문자열=거짓 수치 관계 등 사유. 상위 계층이 재생성·L4/L5 라우팅 결정에 활용."
        ),
    )


class GenerateQueuedBody(BaseModel):
    """POST /v1/generate 응답(비동기 QUALITY 큐잉, HTTP 202) — job_id + 결정 메타데이터.

    QUALITY(27b)는 동기 호출 불가(03a §D.3)라 즉시 텍스트를 주지 않는다. job_id로
    GET /v1/jobs/{job_id}를 폴링해 결과를 받는다. `decision.mode`는 "async"다.
    """

    job_id: str = Field(..., description="비동기 작업 ID — /v1/jobs/{job_id}로 폴링")
    status: str = Field(default="queued", description="작업 적재 상태('queued')")
    decision: RoutingDecision = Field(..., description="라우팅 결정 메타데이터 (03a §G)")


class JobStatusBody(BaseModel):
    """GET /v1/jobs/{job_id} 응답 — 비동기 작업 상태 + (완료 시) 텍스트.

    `state`: pending(진행 중)/success(완료)/failure(실패)/unknown(상태 판정 불가).
    `text`는 success일 때만 채워지며 *검증 전 원시 출력*이다(앱 docstring 경계 메모).
    `error`는 failure/unknown일 때 사유(스택트레이스 아님).
    """

    job_id: str = Field(..., description="조회한 작업 ID")
    state: str = Field(..., description="pending/success/failure/unknown")
    text: str | None = Field(default=None, description="완료 시 원시 텍스트(검증 전)")
    error: str | None = Field(default=None, description="실패/판정불가 사유(스택트레이스 X)")
    validation_signal: str | None = Field(
        default=None,
        description=(
            "완료(success) 텍스트의 런타임 shadow 검증 신호(비차단·관측). None=통과/미검증/"
            "미완료. 동기 /v1/generate와 동형 — 폴링 결과도 거짓 수치 관계를 노출한다."
        ),
    )


class ModelAvailabilityBody(BaseModel):
    """/status 모델 항목."""

    model_id: str
    present: bool


class StatusBody(BaseModel):
    """GET /status 응답 — Ollama(로컬) 레디니스 + 클라우드(Anthropic) 구성 보고.

    로컬 필드(ready/reachable/models/missing/error)는 S1 계약 그대로다. S5가 클라우드
    필드(cloud_*)를 *선택적으로* 덧붙인다 — 기본 None이라 기존 응답·테스트와 호환된다.
    클라우드 미노출 provider(가짜·로컬전용)면 cloud_* 필드는 None으로 남는다.
    """

    ready: bool = Field(..., description="도달 가능 + 모든 라우팅 모델 설치 여부(로컬)")
    reachable: bool = Field(..., description="Ollama 데몬 도달 가능 여부")
    models: list[ModelAvailabilityBody] = Field(..., description="라우팅 모델별 설치 여부")
    missing: list[str] = Field(..., description="미설치 모델 ID 목록")
    error: str | None = Field(default=None, description="도달 실패 시 사유(비크래시)")
    # ── 클라우드(Anthropic, S5) — 선택적. None이면 클라우드 상태 미노출 ──
    cloud_configured: bool | None = Field(
        default=None, description="Anthropic API 키 설정 여부(전송 가능). None=미노출"
    )
    cloud_reachable: bool | None = Field(
        default=None, description="Anthropic 도달·인증 확인(models.list). None=미노출"
    )
    cloud_error: str | None = Field(
        default=None, description="클라우드 도달/인증 실패 사유(비크래시). None=미노출"
    )


class ComponentCheckBody(BaseModel):
    """/health/ready 컴포넌트 항목 — 딥체크 1건 결과(ops/service_health.ComponentCheck)."""

    configured: bool = Field(..., description="구성/확인 수단 노출 여부(False=미구성·오류 아님)")
    reachable: bool | None = Field(
        ...,
        description="도달성. None='판정 불가'(미구성 등 — False '도달 실패'와 구분)",
    )
    required: bool = Field(
        ..., description="ready 판정 필수 여부(DB만 True — 엔드포인트 docstring)"
    )
    error: str | None = Field(
        default=None,
        description=(
            "도달 실패 사유 — 예외 *타입명*(시크릿·환경값 미포함) 또는 provider 보고 문자열"
        ),
    )


class MetricsSummaryBody(BaseModel):
    """/health/ready 인프로세스 계측 요약 — None 필드는 '미측정'(0과 구분·날조 금지)."""

    uptime_seconds: float = Field(..., description="프로세스(계측 시작) 이후 경과 초 — 가동 보고")
    total_requests: int = Field(..., description="누적 계측 요청 수(ops 프로브 경로 제외)")
    total_5xx: int = Field(..., description="누적 5xx 응답 수")
    window_count: int = Field(..., description="최근 창(고정 deque) 표본 수")
    window_error_rate: float | None = Field(
        ..., description="최근 창 5xx 비율. None=표본 없음(미측정)"
    )
    window_p95_latency_ms: float | None = Field(
        ..., description="최근 창 p95 지연(ms). None=표본 없음(미측정)"
    )
    latency_sum_ms: float = Field(..., description="누적 지연 합계(ms)")
    latency_max_ms: float | None = Field(..., description="누적 최대 지연(ms). None=요청 0건")


class AlertBody(BaseModel):
    """/health/ready 알림 항목 — 임계 위반(breach) 1건(임계·실측치 병기)."""

    metric: str = Field(..., description="위반 지표 이름(error_rate·latency_p95_ms)")
    observed: float = Field(..., description="실측치")
    threshold: float = Field(..., description="Settings 임계(초과 시 breach)")


class GrowthEvidenceReachBody(BaseModel):
    """/health/ready 성장 증거 도달 관측 섹션(PED-06) — `GET /v1/me/harness-metrics` 도달 카운터.

    `gamification_module_gap_review.md` §3 D1 — 이 값이 0이면 "성장 지표 11종이 계산은
    되지만 학생에게 도달한 적이 없다"는 실측 주장이 라이브로도 유지된다는 뜻이다. 0이
    아니게 되는 순간이 그 주장이 깨지는 순간이다(정적 감사와의 이중 회계).
    """

    requests_total: int = Field(
        ..., description="GET /v1/me/harness-metrics 누적 요청 수(프로세스 재시작 시 리셋)"
    )


class GrowthEvidenceExposureReachBody(BaseModel):
    """/health/ready 성장 증거 *노출 계약* 도달 관측 섹션(PED-08) — `GET /v1/me/growth-evidence`.

    위 `GrowthEvidenceReachBody`(원시 표면 `/harness-metrics`)와 *별도 슬롯*이다 — 합산되면
    "노출 계약을 거쳐 학생에게 도달했다"는 주장과 "원시 표면에 도달했다"는 주장을 구분할 수
    없게 된다(PED-06 3상태 도달 리포트가 이 구분에 의존). 이 값이 0이 아니게 되는 순간이
    "노출 계약 경유 엔드포인트를 클라가 실제로 호출하기 시작했다"는 주장이 검증되는 순간이다.
    """

    requests_total: int = Field(
        ..., description="GET /v1/me/growth-evidence 누적 요청 수(프로세스 재시작 시 리셋)"
    )


class L6ModeReachBody(BaseModel):
    """/health/ready L6 응용 모드 6종 도달 관측 섹션(PB-04) — `GET /v1/gating/*` 6개 카운터.

    `problem_bank_gap_review_r2.md` §0-②-나 — 6개 값이 전부 0이면 "L6 응용 모드 6종이
    구현은 됐지만 학생 앱(mobile/web) 어디도 이 경로를 호출한 적이 없다"는 실측 주장이
    라이브로도 유지된다는 뜻이다. 어느 값이든 0이 아니게 되는 순간이 그 모드의 도달 주장이
    깨지는 순간이다(정적 grep 감사와의 이중 회계).
    """

    retake: int = Field(
        ..., description="GET /v1/gating/retake 누적 요청 수(프로세스 재시작 시 리셋)"
    )
    suneung: int = Field(
        ..., description="GET /v1/gating/suneung 누적 요청 수(프로세스 재시작 시 리셋)"
    )
    school_progress: int = Field(
        ..., description="GET /v1/gating/school-progress 누적 요청 수(프로세스 재시작 시 리셋)"
    )
    thinking: int = Field(
        ..., description="GET /v1/gating/thinking 누적 요청 수(프로세스 재시작 시 리셋)"
    )
    metacognition: int = Field(
        ..., description="GET /v1/gating/metacognition 누적 요청 수(프로세스 재시작 시 리셋)"
    )
    gifted: int = Field(
        ..., description="GET /v1/gating/gifted 누적 요청 수(프로세스 재시작 시 리셋)"
    )


class OcrReachBody(BaseModel):
    """/health/ready OCR 도달 관측 요약 (NLP-01) — 요청·성공·사유별 503 인프로세스 카운트.

    `enabled=False`면 나머지 카운트가 전부 0이어도 '측정했더니 0건'이 아니라 '이 인스턴스는
    OCR을 켜지 않았다(config off)'로 읽는다(None-vs-zero — `MetricsSummaryBody`의 None
    필드와 같은 취지를 bool 플래그로 표현).
    """

    enabled: bool = Field(..., description="OCR 활성 의도(부품 로드 성공 또는 적재 시도함)")
    requests_total: int = Field(..., description="get_ocr_components 디펜던시 도달 총 횟수")
    succeeded: int = Field(..., description="OCR 파이프라인 정상 완료(200 응답) 횟수")
    unavailable_disabled: int = Field(..., description="503 — 사유: 비활성(config off)")
    unavailable_load_failed: int = Field(..., description="503 — 사유: 부품 적재 실패")


class SolutionSegmentationBody(BaseModel):
    """/health/ready 단계 분해 0-전이 제출 관측 요약 (NLP-03 acceptance ③).

    클라이언트가 이미 분해해 보낸 `CoachRequest.solution_steps`의 길이 분포를 관측한다
    (백엔드가 원문을 직접 분해하는 라이브 경로는 없다 — `api/_segmentation_state.py` 모듈
    docstring 참조). `total`이 분모, `single_or_zero_step`이 분자다. `total=0`이면 관측
    대상 요청 자체가 없었다는 뜻이라 별도 enabled 플래그는 두지 않는다(OCR 축과 달리
    "요청 0건"과 "0-전이 0건"이 total로 자연스럽게 구분됨).
    """

    total: int = Field(
        ...,
        description="solution_steps가 있고(None 아님) 비어있지 않은 요청 총계(분모)",
    )
    single_or_zero_step: int = Field(
        ...,
        description="그중 len(solution_steps) <= 1인 건수(분자·클라 분해 degenerate 의심 신호)",
    )


class ReadyBody(BaseModel):
    """GET /health/ready 응답 — 딥체크·인프로세스 계측·알림(이중 회계의 HTTP 노출면)."""

    ready: bool = Field(..., description="트래픽 수용 가능 여부(= DB 도달성·필수 컴포넌트만)")
    components: dict[str, ComponentCheckBody] = Field(
        ..., description="컴포넌트별 딥체크(database·redis·llm_router)"
    )
    metrics: MetricsSummaryBody = Field(..., description="인프로세스 요청 계측 요약")
    alerts: list[AlertBody] = Field(
        ...,
        description="현재 임계 위반 목록 — 외부 프로브가 SaaS 없이 읽는 인프로세스 축",
    )
    ocr: OcrReachBody = Field(
        ...,
        description="OCR 도달 관측(NLP-01) — 활성 의도 + 요청/성공/사유별 503 카운트",
    )
    solution_segmentation: SolutionSegmentationBody = Field(
        ..., description="단계 분해 0-전이 제출 관측(NLP-03) — solution_steps 길이 분포"
    )
    growth_evidence: GrowthEvidenceReachBody = Field(
        ...,
        description="성장 증거(WH-1 대리 지표) 도달 관측(PED-06) — 원시 표면(/harness-metrics).",
    )
    growth_evidence_exposure: GrowthEvidenceExposureReachBody = Field(
        ...,
        description="성장 증거 노출 계약 경유 도달 관측(PED-08) — /growth-evidence(구분 카운터).",
    )
    l6_mode_reach: L6ModeReachBody = Field(
        ...,
        description="L6 응용 모드 6종 도달 관측(PB-04) — /v1/gating/* 6개 엔드포인트별 카운터.",
    )


def _component_body(check: ComponentCheck) -> ComponentCheckBody:
    """ComponentCheck(도메인) → ComponentCheckBody(HTTP 스키마) 변환."""
    return ComponentCheckBody(
        configured=check.configured,
        reachable=check.reachable,
        required=check.required,
        error=check.error,
    )


def _ocr_reach_body(snapshot: OcrReachSnapshot) -> OcrReachBody:
    """OcrReachSnapshot(도메인, `api._ocr_state`) → OcrReachBody(HTTP 스키마) 변환."""
    return OcrReachBody(
        enabled=snapshot.enabled,
        requests_total=snapshot.requests_total,
        succeeded=snapshot.succeeded,
        unavailable_disabled=snapshot.unavailable_disabled,
        unavailable_load_failed=snapshot.unavailable_load_failed,
    )


def _segmentation_body(
    snapshot: SolutionSegmentationSnapshot,
) -> SolutionSegmentationBody:
    """SolutionSegmentationSnapshot(도메인, `api._segmentation_state`) → HTTP 스키마 변환."""
    return SolutionSegmentationBody(
        total=snapshot.total,
        single_or_zero_step=snapshot.single_or_zero_step,
    )


def _growth_evidence_body(snapshot: GrowthEvidenceReachSnapshot) -> GrowthEvidenceReachBody:
    """GrowthEvidenceReachSnapshot(도메인) → GrowthEvidenceReachBody(HTTP 스키마) 변환."""
    return GrowthEvidenceReachBody(requests_total=snapshot.requests_total)


def _growth_evidence_exposure_body(
    snapshot: GrowthEvidenceReachSnapshot,
) -> GrowthEvidenceExposureReachBody:
    """GrowthEvidenceReachSnapshot(도메인) → GrowthEvidenceExposureReachBody(HTTP 스키마) 변환.

    `_growth_evidence_body`의 미러(PED-08) — 입력 스냅샷 타입은 같지만 출력 스키마가
    달라(다른 라우트를 명명하는 별도 docstring) 별도 변환 함수를 둔다.
    """
    return GrowthEvidenceExposureReachBody(requests_total=snapshot.requests_total)


def _l6_mode_reach_body(snapshot: L6ModeReachSnapshot) -> L6ModeReachBody:
    """L6ModeReachSnapshot(도메인) → L6ModeReachBody(HTTP 스키마) 변환(PB-04)."""
    return L6ModeReachBody(
        retake=snapshot.retake,
        suneung=snapshot.suneung,
        school_progress=snapshot.school_progress,
        thinking=snapshot.thinking,
        metacognition=snapshot.metacognition,
        gifted=snapshot.gifted,
    )


def _metrics_body(snapshot: MetricsSnapshot) -> MetricsSummaryBody:
    """MetricsSnapshot(도메인) → MetricsSummaryBody(HTTP 스키마) 변환."""
    return MetricsSummaryBody(
        uptime_seconds=snapshot.uptime_seconds,
        total_requests=snapshot.total_requests,
        total_5xx=snapshot.total_5xx,
        window_count=snapshot.window_count,
        window_error_rate=snapshot.window_error_rate,
        window_p95_latency_ms=snapshot.window_p95_latency_ms,
        latency_sum_ms=snapshot.latency_sum_ms,
        latency_max_ms=snapshot.latency_max_ms,
    )


# ──────────────────────────────────────────────────────────────────────────
# 의존성 접근자 — provider/cache/trace/queue는 `api/_l3_state.py`로 추출해 라우터와 공유
# (slice 96·위에서 _get_* 별칭 import). validator/skip-cache는 /v1/generate 전용이라 여기 둔다.
# Request.app.state 경유(FastAPI 관용 패턴) — 팩토리 클로저에 의존하지 않아 TestClient에서도 안전.
# ──────────────────────────────────────────────────────────────────────────
def _get_validator(request: Request) -> SeedValidator | None:
    """런타임 shadow 검증기 — Settings 게이트로 None(비활성)일 수 있다."""
    validator: SeedValidator | None = getattr(request.app.state, _VALIDATOR_KEY)
    return validator


def _get_skip_cache_on_signal(request: Request) -> bool:
    """환각 신호 난 미스 생성물을 캐시에 적재하지 않을지(Settings 게이트·캐시 위생)."""
    skip: bool = getattr(request.app.state, _SKIP_CACHE_KEY)
    return skip


def _activate_ocr(_app: FastAPI, settings: Settings) -> None:
    """L5 OCR 부품 구성 시도 + 비활성/실패 사유를 app.state에 기록 (NLP-01).

    lifespan 본문에서 분리한 이유: 이 함수는 순수하게 `settings.ocr_enabled` 분기·
    `build_ocr_components` 호출·실패 로깅·`set_ocr_components` 호출만 하고 I/O 의존
    (DB 스키마 검증·store ping 등 lifespan의 다른 단계)이 없어, DB·Redis 없이도 가짜
    `FastAPI()` 인스턴스로 단위테스트할 수 있다(사유 분리·로그 타입명 회귀 동결).

    `ocr_enabled`면 부품(검출기·라우터·인식기)을 1회 구성해 app.state에 올린다(모델 1회
    로드·매 요청 재구성 회피·세만틱 매처 웜업 미러). 부품 생성은 *지연 import*라 모델
    다운로드·네트워크가 일어나지 않는다(첫 인식 시 적재). 실패해도 *학생 경로 게이트가
    아니라* OCR 기능만 비활성(/v1/ocr → 503)이라 fail-fast시키지 않고 경고만 남긴다
    (부팅 보호·CLAUDE.md 가용성 우선 #1≫#6). off(기본)면 `unavailable_reason="disabled"`로
    비활성 표시(getter가 503) — 켰다가 적재에 실패하면 `"load_failed"`로 구분한다(§3 D1
    "config off"와 "부품 적재 실패"의 무변별 해소).
    """
    if not settings.ocr_enabled:
        set_ocr_components(_app, None, unavailable_reason="disabled")
        return
    try:
        # qwen_vl 인식기는 L3 라우터 경유라 provider/cache/trace 주입이 필요하다 —
        # app.state에 이미 올린 L3 의존을 넘긴다(다른 백엔드는 미사용·무영향).
        set_ocr_components(
            _app,
            build_ocr_components(
                settings,
                llm_provider=getattr(_app.state, _PROVIDER_KEY, None),
                llm_cache=getattr(_app.state, _CACHE_KEY, None),
                trace_sink=getattr(_app.state, _TRACE_KEY, None),
            ),
        )
    except Exception as exc:  # noqa: BLE001 — 비크래시 보고(타입명 필수·침묵 실패 금지)
        # NLP-01: 침묵 실패 금지는 메시지 *본문*에 예외 타입명을 요구한다(exc_info의
        # 트레이스백만으로는 부족 — langfuse 8일 무증상 전멸 교훈, _degradation.py 관례).
        # 사유(load_failed)를 명시해 set_ocr_components에 넘겨 "비활성(config off)"과
        # 무변별이던 503을 사유 분리한다(§3 D1).
        logger.warning(
            "OCR 부품 구성 실패 — /v1/ocr 비활성(503) — 예외 타입: %s",
            type(exc).__name__,
            exc_info=True,
        )
        set_ocr_components(_app, None, unavailable_reason="load_failed")


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """앱 수명 — 시작 시 device store 활성(slice 27), 종료 시 store 해제 + DB 엔진 풀 반납.

    **시작**: `Settings.device_store_mode`(none/pg/pg_cached) 기반으로 store 구성·
    `set_device_store(store)`. `none`(기본)은 slice 21 폴백 그대로(set_device_store(None) 호출).

    **종료**: store 해제(set_device_store(None) + Redis 클라이언트 닫기)·`dispose_engine`으로
    PG async 엔진 풀 반납.

    get_session이 첫 쿼리에서 *지연* 생성한 async 엔진/연결 풀을 앱 종료 시 반납한다.
    엔진이 만들어진 적 없으면(DB 미사용 경로·의존성 오버라이드된 단위테스트) dispose_engine은
    no-op이라 안전하다.

    주의: `TestClient(app)`를 컨텍스트매니저 없이 쓰면 lifespan이 발화하지 않는다(Starlette
    기본) — 기존 L3 단위테스트(가짜 의존성)는 영향받지 않는다.
    """
    settings = get_settings()
    # SEC-03: 스키마 버전(alembic head) 가드 — DB가 코드보다 *뒤처졌으면* 프로덕션에서 기동 거부.
    # SEC-01의 fail-closed는 암호화 *키 부재*만 막고 마이그레이션 미적용은 막지 못했다(SEC-02
    # 실측이 그 조합을 실물로 확인). store ping보다 먼저 둔다 — 스키마가 없으면 어차피 정상
    # 동작이 불가하고, 진단 메시지도 "컬럼이 없다"가 "쿼리가 실패했다"보다 정확하다.
    await verify_schema_version(settings)
    # 슬라이스 30: store 의존성(PG/Redis) 부팅 시 ping → 미도달이면 fail-fast.
    await ping_device_store_health(settings)
    store, cleanup_fn = build_device_store_from_settings(settings)
    set_device_store(store)
    # 슬라이스 106·111: 오개념 의미 매칭 mode가 *off가 아닐 때*(shadow·on 둘 다 라이브 매처
    # 사용) 매처를 *단일 스레드에서* 웜업(첫 match 1회)해 `_ensure_built`(카탈로그 인덱스 1회
    # 적재)를 미리 완료한다 — coach `_compute_matches`가 `asyncio.to_thread`로 매처를 *워커 스레드
    # 풀*에서 호출하므로, 웜업 없이 첫 동시 요청이 여러 워커에서 동시에 `_ensure_built`를 타면
    # 인덱스 적재 경합이 생긴다. 단일 스레드 웜업이 그 경합 안전판이다. off(기본)면 skip(임베딩
    # 로드 0). 웜업 실패도 *학생 경로를 막지 않으려* 삼키고 로그만 남긴다(첫 요청이 lazy 재시도·
    # `_compute_matches`가 graceful 폴백) — 부팅을 fail-fast시키지 않는다(의미 매칭은 보완재·
    # CLAUDE.md 가용성 우선 #1≫#6).
    if settings.misconception_semantic_mode != "off":
        try:
            # 짧은 비-빈 텍스트로 match를 1회 호출 — 빈 문자열은 `_ensure_built` 전에 early
            # return(03 matcher.py `if not student_solution: return []`)이라 인덱스 적재가 안
            # 되므로, 짧은 산문("워밍업")으로 호출해 카탈로그 임베딩·인덱스 적재를 강제한다.
            await asyncio.to_thread(
                get_semantic_matcher().match,
                "워밍업",
                top_k=1,
                threshold=settings.misconception_semantic_threshold,
            )
        except Exception:
            logger.warning("오개념 의미 매처 웜업 실패 — 첫 요청 시 lazy 재시도", exc_info=True)
    # L5 OCR: 사유 분리·로그 타입명 회귀 동결이 가능하도록 별도 함수로 분리(`_activate_ocr`).
    _activate_ocr(_app, settings)
    try:
        yield
    finally:
        set_device_store(None)
        await cleanup_fn()
        await dispose_engine()


def create_app(
    *,
    provider: LLMProvider | None = None,
    cache: CacheBackend | None = None,
    trace: TraceSink | None = None,
    queue: AsyncJobQueue | None = None,
    oauth_providers: dict[str, OAuthProvider] | None = None,
    metrics: ServiceMetrics | None = None,
    readiness_probes: ReadinessProbes | None = None,
    ocr_counters: OcrReachCounters | None = None,
    segmentation_counters: SolutionSegmentationCounters | None = None,
) -> FastAPI:
    """FastAPI 앱 팩토리 — 의존성 주입 가능.

    기본값: OllamaProvider + RedisCache(S2) + LangfuseSink(S3) + CeleryJobQueue(S4). 넷
    모두 *지연*이라 앱 구성 시 라이브 Redis·Langfuse·Celery broker가 필요 없다(첫 사용
    때 연결). LangfuseSink는 키(WHYMATH_LANGFUSE_*) 미설정 시 영구 no-op이므로 CI(키
    없음)에서도 네트워크를 타지 않는다. 테스트는 가짜 provider/cache(InMemoryCache)/
    trace/queue를 주입해 hermetic을 유지한다.

    OPS-01 추가 주입 좌석: `metrics`(인프로세스 요청 계측 — 계측 실패 회귀 테스트가
    폭발하는 가짜를 주입)·`readiness_probes`(/health/ready 딥체크 묶음 — 테스트가 가짜
    CheckFn을 주입해 라이브 DB·Redis·Ollama 없이 200/503 변별을 검증). 기본 probes도
    전부 *지연*이라 앱 구성만으로는 어떤 인프라에도 연결하지 않는다.

    SEC-11: 로그 PII·시크릿 스크러버(`ops/log_scrubber.py`)를 루트 로거에 배선한다.
    `_lifespan`이 아니라 여기서 거는 이유는 순수 in-process 설정(I/O 없음)이라 지연시킬
    이유가 없고, `TestClient(app)`을 `with` 없이 쓰는(=lifespan 미발화) 기존 테스트 다수도
    스크러버 보호를 받아야 하기 때문이다(`api/_crypto.py`의 "게이트는 앱 구성 시점에 건다"
    선례와 동일 타이밍). Settings 게이트 없음 — 저장 축 fail-closed 게이트처럼 끄는 옵션을
    주지 않는다.

    SEC-24(원 SEC-18): 프로덕션 추정(`is_production_like` — 실 OAuth kakao/naver 구성 여부)
    에서는 스키마 표면(`/docs`·`/redoc`·`/openapi.json`)을 비활성화한다. 개발·CI(OAuth
    미구성)는 그대로 노출 — 로컬 개발 경험을 해치지 않는다.
    정본: `docs/reviews/functional_security_audit_2026-08-08.md` L1.
    """
    install_log_scrubber()
    # SEC-24(원 SEC-18): docs_url 등은 FastAPI 생성자에 *한 번만* 넘길 수 있어(런타임 재설정
    # 불가) 앱 구성 시점에 production_like를 확정해야 한다. get_settings()는 @lru_cache라
    # 아래에서 다시 호출되는 것과 같은 캐시 인스턴스를 재사용 — 비용 0.
    settings_for_app = get_settings()
    _prod_like = settings_for_app.production_like
    app = FastAPI(
        title="WhyMath Backend — L3 생성 표면",
        version="0.1.0",
        summary="L3 라우터 ↔ Ollama·Celery 결선 (M1.2-live S1·S4)",
        lifespan=_lifespan,
        docs_url=None if _prod_like else "/docs",
        redoc_url=None if _prod_like else "/redoc",
        openapi_url=None if _prod_like else "/openapi.json",
    )
    # SEC-26(48_보안 §P0 "CORS/보안 헤더 미들웨어" 갭): TrustedHost → CORS → 보안 헤더 순으로
    # 가장 먼저 건다(등록 순서 = 바깥 래핑 순서 — 나쁜 Host를 가장 먼저 걷어내고, preflight를
    # CORS가 처리하고, 마지막으로 모든 응답에 보안 헤더를 얹는다). 셋 다 *항상* 등록한다 —
    # allowlist가 비어 있으면 각자 안전한 기본 자세로 수렴한다(TrustedHost는 `*`=현재 동작
    # 무회귀, CORS는 deny-by-default=네이티브 앱 미영향). 와일드카드+credentials 조합은
    # `Settings._forbid_cors_wildcard_with_credentials`가 부팅 시점에 이미 막았다.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings_for_app.trusted_hosts_list)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings_for_app.cors_allowed_origins_list,
        allow_credentials=settings_for_app.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _security_headers_middleware(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """모든 응답에 보안 헤더를 얹는다(SEC-26 — 48_보안 §P0 "CORS/보안 헤더" 갭 해소).

        `X-Content-Type-Options`·`X-Frame-Options`·`Referrer-Policy`는 항상 적용한다(다운사이드
        없음 — `/docs` 등 스키마 표면도 프레이밍·스니핑 보호를 받아야 마땅하다). `Strict-
        Transport-Security`·`Content-Security-Policy`는 `_prod_like`에서만 적용한다 — CSP
        `default-src 'none'`은 이 API가 JSON 전용이라 안전하지만 Swagger UI(`/docs`)는 CDN
        스크립트·스타일을 로드해야 렌더링되므로, 개발 환경(docs 활성)에서 CSP를 걸면 그
        페이지가 깨진다. `_prod_like`에서는 `docs_url`이 이미 None(라우트 자체가 없음)이라
        이 충돌이 발생하지 않는다 — 즉 CSP 게이팅은 기존 docs_url 게이팅과 정확히 같은 축을
        재사용한다(별도 판정 좌석을 만들지 않음).
        """
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if _prod_like:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'"
            )
        return response

    # 기본 provider는 CompositeProvider — cost_tier로 로컬(Ollama)↔클라우드(Anthropic)
    # 디스패치(S5). 둘 다 지연이라 구성 시 라이브 Ollama·Anthropic 키가 필요 없다.
    # (OPS-01) 변수로 잡아 두는 이유: 기본 readiness probes가 같은 provider의
    # check_status를 재사용한다(/status와 동일 표면 — 재발명 금지).
    resolved_provider: LLMProvider = (
        provider
        if provider is not None
        else CompositeProvider(local=OllamaProvider(), cloud=AnthropicProvider())
    )
    app.state.__setattr__(_PROVIDER_KEY, resolved_provider)
    # 기본 캐시는 RedisCache(지연 연결) — 구성 시 라이브 Redis 불필요(첫 접근 때 연결).
    app.state.__setattr__(_CACHE_KEY, cache if cache is not None else RedisCache())
    # 기본 트레이스는 LangfuseSink(지연·자기비활성) — 키 미설정 시 영구 no-op(S3).
    app.state.__setattr__(_TRACE_KEY, trace if trace is not None else LangfuseSink())
    # 기본 큐는 CeleryJobQueue(지연 연결) — 구성 시 broker 불필요(첫 디스패치 때 연결, S4).
    app.state.__setattr__(_QUEUE_KEY, queue if queue is not None else CeleryJobQueue())
    # ── 과목 능력 등록(push) — 계획서 100 §3.8 / EOS-89 ─────────────────────
    # Application(여기)이 합성 루트를 **한 번** 불러 인터페이스 타입으로 app.state에 올린다.
    # 라우터는 `api/_subject_capability_state.py`의 Depends로 꺼내 쓴다 — 그래서 Core 모듈은
    # `composition`을 이름으로 알지 않는다(`EOS Core → Subject Interface ← Math Adapter`).
    # 부팅 1회 호출이라 요청 경로에서 재조립하지 않는다(팩토리는 상태 없는 판정기를 준다).
    # COMP-01: EOS-86의 `StepChainVerifier` 팩토리도 **같은 줄들 옆에** 등록한다(6번째). 이 줄이
    #    빠지면 `api/coach.py`의 Depends가 `AttributeError`로 터지고(폴백 없음·침묵 실패 금지),
    #    tests/infra `test_app_factory_registers_every_subject_capability`가 RED가 된다.
    app.state.__setattr__(_EXPRESSION_EQUIVALENCE_KEY, default_expression_equivalence())
    app.state.__setattr__(_FINAL_ANSWER_VERIFIER_KEY, default_final_answer_verifier())
    app.state.__setattr__(_ASSESSMENT_ANSWER_VERIFIER_KEY, default_assessment_answer_verifier())
    app.state.__setattr__(_EXPRESSION_SEAL_KEY, default_expression_seal())
    app.state.__setattr__(_ANSWER_FORM_VERIFIER_KEY, default_answer_form_verifier())
    app.state.__setattr__(_STEP_CHAIN_VERIFIER_KEY, default_step_chain_verifier())
    # EOS-104: 7번째 — 오답 1건에서 오개념 후보를 읽는 능력. 같은 줄들 옆에 두는 이유도 같다
    #    (빠지면 `api/me.py`의 Depends가 AttributeError로 터지고 infra 테스트가 RED).
    app.state.__setattr__(
        _ATTEMPT_MISCONCEPTION_DETECTOR_KEY, default_attempt_misconception_detector()
    )
    # OAuth provider 레지스트리(로그인 콜백이 provider 이름으로 조회). 기본은 config의 키가
    # 설정된 provider만(카카오·네이버·OAuth-a2) — 키 미설정(CI)이면 빈 dict라 콜백 404. 클라이언트는
    # 지연이라 구성만으로 네트워크 미발생. 테스트는 가짜 provider를 직접 주입한다.
    app.state.__setattr__(
        _OAUTH_PROVIDERS_KEY,
        (oauth_providers if oauth_providers is not None else build_oauth_providers(get_settings())),
    )
    # shadow 검증기 — Settings 게이트(l3_shadow_validation_enabled). 비활성이면 None이라
    # /v1/generate가 validator 없이 호출(검증 미실행). 비차단이라 둘 다 안전.
    _settings = get_settings()
    app.state.__setattr__(
        _VALIDATOR_KEY,
        _SHADOW_VALIDATOR if _settings.l3_shadow_validation_enabled else None,
    )
    # 캐시 위생 정책(Settings 게이트·slice 49) — 신호 난 미스 생성물 캐시 적재 회피 여부.
    app.state.__setattr__(_SKIP_CACHE_KEY, _settings.l3_skip_cache_on_signal)

    # ── OPS-01: 인프로세스 요청 계측·알림·레디니스 probes (이중 회계의 프로세스 안쪽 축) ──
    # 계측·알림은 SaaS(Langfuse)와 독립이다 — Langfuse가 죽어도 여기 판정치는 계속 나온다
    # (cost_probe 선례). notifier는 미들웨어와 /health/ready가 *공유*해 상태 전이 시에만
    # warning을 남긴다(스팸 방지·이중 로그 방지).
    resolved_metrics = (
        metrics
        if metrics is not None
        else ServiceMetrics(window_size=_settings.ops_metrics_window_size)
    )
    alert_notifier = AlertLogNotifier()
    resolved_probes = (
        readiness_probes
        if readiness_probes is not None
        else default_readiness_probes(provider=resolved_provider)
    )
    app.state.__setattr__(_METRICS_KEY, resolved_metrics)
    app.state.__setattr__(_ALERT_NOTIFIER_KEY, alert_notifier)
    app.state.__setattr__(_READY_PROBES_KEY, resolved_probes)
    # OPS-17: 클라 버전 게이트 — 헤더 부재/파싱 실패("미상") 경량 카운터(신규 SaaS 의존
    # 없음 — Prometheus/StatsD 등은 과공학. 모듈 전역이 아니라 app.state에 둬 앱 인스턴스별
    # (테스트 격리 포함) 카운터가 섞이지 않는다).
    app.state.__setattr__(_VERSION_UNKNOWN_COUNT_KEY, 0)

    # NLP-01: OCR 도달 관측 카운터 — ServiceMetrics와 같은 타이밍(create_app에서 심고,
    # lifespan은 OCR 부품 자체만 늦게 결정)에 앱 수명 동안 1개를 심는다. 테스트가 폭발하는
    # 가짜를 주입할 좌석(metrics·readiness_probes와 동형).
    resolved_ocr_counters = ocr_counters if ocr_counters is not None else OcrReachCounters()
    app.state.__setattr__(_OCR_COUNTERS_KEY, resolved_ocr_counters)

    # NLP-03: 단계 분해 0-전이 제출 관측 카운터 — ocr_counters와 같은 타이밍(create_app에서
    # 즉시 심음·lifespan 무관, `api/coach.py` 핸들러가 매 요청 Depends로 record). 테스트가
    # 초기값·폭발 가짜를 주입할 좌석(ocr_counters와 동형).
    resolved_segmentation_counters = (
        segmentation_counters
        if segmentation_counters is not None
        else SolutionSegmentationCounters()
    )
    app.state.__setattr__(_SEGMENTATION_COUNTERS_KEY, resolved_segmentation_counters)

    # PED-06 — 성장 증거(WH-1 대리 지표) 도달 관측 카운터. 앱 수명 동안 1개(재시작 시 리셋
    # — 인프로세스 계측이라 영속 저장 0, `ServiceMetrics`와 동형 전제).
    set_growth_evidence_counters(app, GrowthEvidenceReachCounters())
    # PED-08 — `GET /v1/me/growth-evidence`(노출 계약 경유) 전용 슬롯. 위 카운터(원시 표면
    # `/harness-metrics`)와 *별도 인스턴스*로 심는다 — 합산되면 도달 판정이 위장된다
    # (`_growth_evidence_state.py` 모듈 docstring).
    set_growth_evidence_counters(
        app, GrowthEvidenceReachCounters(), key=GROWTH_EVIDENCE_EXPOSURE_COUNTERS_KEY
    )
    # PB-04 — L6 응용 모드 6종(`GET /v1/gating/*`) 도달 관측 카운터. 앱 수명 동안 1개
    # (재시작 시 리셋 — 인프로세스 계측이라 영속 저장 0·growth_evidence와 동형 전제).
    set_l6_mode_reach_counters(app, L6ModeReachCounters())

    def _observe_request(elapsed_ms: float, status_code: int) -> None:
        """요청 1건 계측 + 알림 평가 — 계측 실패가 요청을 절대 깨지 않는다.

        침묵 실패 금지(CLAUDE.md): 계측은 best-effort라 예외를 삼키되 **무타입 경고
        금지** — 예외 *타입명*을 warning에 남긴다(langfuse v2 쓰기 8일 무증상 전멸의
        교훈). 시크릿·필드값은 로그에 싣지 않는다.
        """
        try:
            resolved_metrics.record(elapsed_ms, status_code)
            observed_settings = get_settings()
            alert_notifier.notify(
                evaluate_alerts(
                    resolved_metrics.snapshot(),
                    error_rate_threshold=observed_settings.ops_error_rate_alert_threshold,
                    latency_p95_threshold_ms=observed_settings.ops_latency_p95_alert_ms,
                )
            )
        except Exception as exc:  # noqa: BLE001 — 계측 실패 흡수(요청 보호)·타입명 로그 필수
            logger.warning("요청 계측 실패(요청은 정상 반환) — 예외 타입: %s", type(exc).__name__)

    def _observe_version_unknown() -> None:
        """`X-App-Version` 헤더 부재/파싱 불가 — '미달'과 다른 '미상' 경량 관측(OPS-17).

        차단 여부와 무관한 롤아웃 추적 신호(app.state 카운터)다. 계측(`_observe_request`)과
        같은 정책 — 관측 실패가 요청을 절대 깨지 않되 **무타입 경고 금지**(예외 타입명을
        warning에 남긴다·CLAUDE.md 침묵 실패 금지).
        """
        try:
            setattr(
                app.state,
                _VERSION_UNKNOWN_COUNT_KEY,
                getattr(app.state, _VERSION_UNKNOWN_COUNT_KEY) + 1,
            )
        except Exception as exc:  # noqa: BLE001 — 카운터 실패 흡수(요청 보호)·타입명 로그 필수
            logger.warning(
                "버전 미상 카운터 갱신 실패(요청은 정상 반환) — 예외 타입: %s", type(exc).__name__
            )

    @app.middleware("http")
    async def _service_metrics_middleware(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """요청별 (지연 ms·상태코드) 인프로세스 계측 + 클라 최소 버전 게이트 (OPS-01·OPS-17).

        - ops 프로브 경로(`_OPS_PROBE_PATHS`)는 계측·버전 게이트 모두에서 제외한다 — 업타임
          프로브 폴링이 표본을 지배·오염하는 것을 막는다(상수 주석의 자기증폭 근거).
        - **OPS-17 버전 게이트**(신규 미들웨어가 아니라 이 기존 계측 미들웨어 좌석에 얹는다):
          `X-App-Version` 헤더 값이 `Settings.min_app_version` *미만*이면 **426 Upgrade
          Required**로 즉시 차단한다(`call_next` 미호출 — 401/404/422와 구분되는 전용
          사유코드). 헤더가 아예 없으면(이 기능 배포 이전의 구버전 클라) *차단하지 않는다*
          (`call_next` 정상 호출 — 기존 클라이언트를 즉시 깨뜨리지 않는다) — 대신 "미상"으로
          `_observe_version_unknown`이 경량 관측한다(롤아웃 추적용 신호일 뿐 차단과 무관).
          파싱 불가한 버전 문자열(형식 위반)도 침묵 실패 없이 동일하게 "미상"으로 계상한다.
        - 핸들러의 미처리 예외는 5xx(500)로 회계한 뒤 **그대로 재던진다** — 계측은
          예외를 삼키지 않는다(바깥 ServerErrorMiddleware가 500 응답으로 변환).
        - 계측 자체의 실패는 `_observe_request`가 흡수한다(요청 무영향·예외 타입명 로그).
        """
        if request.url.path in _OPS_PROBE_PATHS:
            return await call_next(request)

        version_header = request.headers.get(_APP_VERSION_HEADER)
        if version_header is None:
            # 헤더 없음 — 이 기능 배포 이전 구버전 클라. 차단하지 않고 '미상'으로만 관측.
            _observe_version_unknown()
        else:
            client_version = _parse_app_version(version_header)
            if client_version is None:
                # 파싱 불가 — 침묵 실패 금지: '미상'과 동일 취급(차단하지 않음·관측만).
                logger.warning(
                    "%s 파싱 불가 — 미상으로 계상(차단 안 함) — 원값: %r",
                    _APP_VERSION_HEADER,
                    version_header,
                )
                _observe_version_unknown()
            else:
                min_version = _parse_app_version(get_settings().min_app_version)
                if min_version is not None and client_version < min_version:
                    # 미달 — 426(401/404/422와 구분되는 전용 사유코드). call_next 미호출.
                    return JSONResponse(
                        status_code=status.HTTP_426_UPGRADE_REQUIRED,
                        content={"detail": "앱을 최신 버전으로 업데이트해주세요."},
                    )
                # min_version 파싱 불가(Settings 오구성)면 게이트 자체를 적용하지 않는다
                # (fail-open — 서버 설정 오류로 전 클라를 차단하는 것이 더 나쁜 실패 모드).

        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            _observe_request((time.monotonic() - started) * 1000.0, 500)
            raise
        _observe_request((time.monotonic() - started) * 1000.0, response.status_code)
        return response

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        """라이브니스 — 의존성 없이 프로세스 생존만 확인."""
        return {"status": "ok"}

    @app.get("/health/live", tags=["ops"])
    async def health_live() -> dict[str, str]:
        """라이브니스 전용 경로(OPS-01) — 기존 /health와 동일 의미(프로세스 생존·의존성 0).

        liveness/readiness를 경로로 분리해 업타임 프로브가 목적별로 고르게 한다(쿠버네티스
        livenessProbe 관례 경로). 기존 /health는 하위호환으로 유지한다(기존 프로브·런북
        무변경).
        """
        return {"status": "ok"}

    @app.get("/health/ready", tags=["ops"])
    async def health_ready(request: Request) -> JSONResponse:
        """레디니스 딥체크(OPS-01) — DB·Redis·LLM 도달성 + 인프로세스 metrics·alerts.

        **ready 판정 = DB 도달성만 필수.** 학생 대면 경로(문항 조회·코치 세션·학습 기록
        영속)는 전부 PostgreSQL을 전제하므로 DB 미도달이면 트래픽을 받을 수 없다. Redis
        (응답 캐시·rate limit 백엔드)와 LLM 라우터(로컬 Ollama)는 *보고만* 한다
        (`required: false` 명시) — Redis 미도달은 캐시 미스·성능 강등일 뿐 경로가 살아
        있고, LLM은 경로별 폴백(클라우드 디스패치·QUALITY 큐·WH-1 결정론 템플릿)이 있어
        도달 실패가 곧 서비스 불능이 아니다.

        not ready면 **503**을 반환한다 — 기존 /status(항상 200)는 운영자·드라이버가 body를
        읽는 *보고형*이지만, 이 엔드포인트는 외부 업타임 프로브(쿠버네티스 readinessProbe·
        모니터)가 *HTTP 상태코드만으로* 판정하는 기계용이라 200/503으로 가른다. body의
        `metrics`·`alerts`는 SaaS 관측 인프라(Langfuse)가 죽어도 판정치를 읽을 수 있는
        인프로세스 축이다(이중 회계 — `ops/cost_probe.py` 선례).
        """
        probes: ReadinessProbes = getattr(request.app.state, _READY_PROBES_KEY)
        svc_metrics: ServiceMetrics = getattr(request.app.state, _METRICS_KEY)
        notifier: AlertLogNotifier = getattr(request.app.state, _ALERT_NOTIFIER_KEY)
        growth_evidence_counters = get_growth_evidence_counters(request.app)
        growth_evidence_exposure_counters = get_growth_evidence_counters(
            request.app, key=GROWTH_EVIDENCE_EXPOSURE_COUNTERS_KEY
        )
        l6_mode_reach_counters = get_l6_mode_reach_counters(request.app)
        # 세 딥체크는 서로 독립이라 동시 실행한다. 각 체크는 예외를 던지지 않는 계약
        # (ops/service_health — 비크래시 보고)이라 gather에 예외 누수가 없다.
        db_check, redis_check, llm_check = await asyncio.gather(
            probes.database(), probes.redis(), probes.llm()
        )
        snapshot = svc_metrics.snapshot()
        ready_settings = get_settings()
        alerts = evaluate_alerts(
            snapshot,
            error_rate_threshold=ready_settings.ops_error_rate_alert_threshold,
            latency_p95_threshold_ms=ready_settings.ops_latency_p95_alert_ms,
        )
        # 미들웨어와 같은 notifier 공유 — 전이 시에만 로그(폴링 반복이 스팸이 안 됨).
        notifier.notify(alerts)
        ready = db_check.reachable is True
        body = ReadyBody(
            ready=ready,
            components={
                check.name: _component_body(check) for check in (db_check, redis_check, llm_check)
            },
            metrics=_metrics_body(snapshot),
            alerts=[
                AlertBody(metric=a.metric, observed=a.observed, threshold=a.threshold)
                for a in alerts
            ],
            ocr=_ocr_reach_body(_get_ocr_reach_snapshot(request.app)),
            solution_segmentation=_segmentation_body(_get_segmentation_snapshot(request.app)),
            growth_evidence=_growth_evidence_body(growth_evidence_counters.snapshot()),
            growth_evidence_exposure=_growth_evidence_exposure_body(
                growth_evidence_exposure_counters.snapshot()
            ),
            l6_mode_reach=_l6_mode_reach_body(l6_mode_reach_counters.snapshot()),
        )
        return JSONResponse(
            status_code=(status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE),
            content=body.model_dump(mode="json"),
        )

    @app.get("/status", tags=["ops"], response_model=StatusBody)
    async def get_status(request: Request) -> StatusBody:
        """레디니스 — Ollama(로컬) 도달성·모델 매트릭스 + 클라우드(Anthropic) 구성 보고.

        Ollama·클라우드가 죽어 있어도 500을 던지지 않는다 — 상태로 *보고*한다. 로컬
        도달성은 provider.check_status로, 클라우드 구성/도달성은 provider.check_cloud_status
        (CompositeProvider만 노출)로 점검한다. provider가 해당 메서드를 노출하지 않으면
        (가짜·로컬전용) 로컬은 도달 불가로, 클라우드는 미노출(None)로 간주한다.
        """
        provider = _get_provider(request)
        ollama_status: OllamaStatus
        check = getattr(provider, "check_status", None)
        if check is None:
            ollama_status = OllamaStatus(
                reachable=False, models=(), error="provider has no status check"
            )
        else:
            ollama_status = await check()

        # 클라우드 상태(선택) — CompositeProvider만 check_cloud_status를 노출한다.
        # 없으면(가짜·로컬전용 provider) cloud_* 필드는 None으로 남는다(기존 응답 호환).
        cloud_configured: bool | None = None
        cloud_reachable: bool | None = None
        cloud_error: str | None = None
        cloud_check = getattr(provider, "check_cloud_status", None)
        if cloud_check is not None:
            cloud_status: CloudStatus | None = await cloud_check()
            if cloud_status is not None:
                cloud_configured = cloud_status.configured
                cloud_error = cloud_status.error
                # `reachable`은 공통 표면이 아니다(ARCH-57) — 보고하는 제공자만 자기 Status에
                # 둔다. 없을 때 False로 접으면 "도달 불가"와 "미측정"이 같은 화면이 되므로
                # None으로 남긴다(응답 필드가 이미 `bool | None`이라 구분이 보존된다).
                cloud_reachable = getattr(cloud_status, "reachable", None)

        return StatusBody(
            ready=ollama_status.all_present,
            reachable=ollama_status.reachable,
            models=[
                ModelAvailabilityBody(model_id=m.model_id, present=m.present)
                for m in ollama_status.models
            ],
            missing=list(ollama_status.missing),
            error=ollama_status.error,
            cloud_configured=cloud_configured,
            cloud_reachable=cloud_reachable,
            cloud_error=cloud_error,
        )

    @app.post("/v1/generate", tags=["l3"])
    async def post_generate(
        body: GenerateBody,
        request: Request,
        user: CurrentUser,
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> JSONResponse:
        """라우팅 → (동기) 캐시·생성 / (비동기 QUALITY) 큐잉. 메타데이터 + 결과 반환.

        인증 필수(`CurrentUser` — SEC-07 D1, 무인증 LLM 비용 남용 표면 봉인). 반환 텍스트
        (동기·완료)는 *검증 전 원시 출력*이다 — 03 문서 환각 방어 파이프라인을 통과하기
        전에는 학생에게 직접 노출 금지 (CLAUDE.md 절대 금기). 환각 방어·학생 표면화는 상위
        계층(L4/L5 오케스트레이터)의 책임이다.

        AI 모델 학습/개선에 데이터 사용 가능 여부는 `ConsentScope.ai_training` 동의를
        판정해 Langfuse trace 메타데이터로 전달한다(EOS §48·§50). 이 판정은 응답 생성을
        막지 않으며, 단지 관측/라우팅 계약에서 학습 허용 여부를 명시하는 용도다.
        성인은 현재 별도 성인 동의 저장소가 없어 기본 False(privacy-by-default).

        QUALITY(27b)로 라우팅되면 동기 호출이 불가하므로(03a §D.3) 작업 큐에 적재하고
        **HTTP 202 Accepted**로 job_id를 반환한다 — 호출자는 /v1/jobs/{job_id}로 폴링한다.
        큐가 미구성이거나 broker가 죽어 enqueue가 실패하면 **503**으로 명확히 보고한다
        (500 스택트레이스 노출 금지 — 가용성 우선, '잠시 후 재시도'가 정직·안전).
        """
        provider = _get_provider(request)
        cache = _get_cache(request)
        trace = _get_trace(request)
        queue = _get_queue(request)
        # EOS §48·§50: AI inference와 AI training 목적을 분리. inference 응답 생성은
        # service_core 동의로 진행되며, training_allowed는 별도 ai_training 동의 판정값을
        # Langfuse trace 메타데이터로 전달해 후속 학습 파이프라인이 참조할 수 있게 한다.
        training_allowed = await has_scope_consent(user, session, ConsentScope.ai_training)
        try:
            result = await pipeline.generate(
                body.request,
                body.prompt,
                body.system,
                provider=provider,
                cache=cache,
                trace=trace,
                queue=queue,
                validator=_get_validator(request),
                skip_cache_on_signal=_get_skip_cache_on_signal(request),
                training_allowed=training_allowed,
            )
        except QualityQueueUnavailableError as exc:
            # 큐 미구성/ broker 도달 실패 — 명확한 503 JSON(스택트레이스 금지).
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": "quality_queue_unavailable",
                    "message": str(exc),
                    "detail": (
                        "QUALITY(27b) 비동기 큐를 사용할 수 없습니다 — 잠시 후 재시도(03a §D.3)."
                    ),
                },
            )

        if result.is_queued:
            # SEC-27: 소유권(job↔user) 기록 — /v1/jobs/{job_id} 폴링이 이 행으로 소유자를
            # 대조한다(app.py 모듈 docstring 경계 메모의 "job→user 저장이 생길 때 후속"이 이것).
            # is_queued=True는 pipeline.generate가 실제 enqueue 성공 후에만 세우므로(l3/pipeline.py
            # GenerationResult.is_queued) job_id는 항상 채워진 문자열이다.
            session.add(JobOwnership(job_id=result.job_id or "", user_id=user.user_id))
            await session.commit()
            # 비동기 QUALITY 큐잉 → 202 Accepted + job_id(폴링 안내).
            queued = GenerateQueuedBody(
                job_id=result.job_id or "",
                status=result.status,
                decision=result.decision,
            )
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content=queued.model_dump(mode="json"),
            )

        # 동기 완료 → 200 + 텍스트(+ shadow 검증 신호·비차단 관측).
        completed = GenerateResponseBody(
            text=result.text,
            cache_hit=result.cache_hit,
            decision=result.decision,
            validation_signal=result.validation_signal,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=completed.model_dump(mode="json"),
        )

    @app.get("/v1/jobs/{job_id}", tags=["l3"], response_model=JobStatusBody)
    async def get_job(
        job_id: str,
        request: Request,
        user: CurrentUser,
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> JobStatusBody:
        """QUALITY 비동기 작업 폴링 — 상태 + (완료 시) 생성 텍스트 (03a §D.3).

        인증 필수(`CurrentUser` — SEC-24(원 SEC-15) M6, POST /v1/generate와 동일 게이트):
        무인증 폴링은 검증 전 원시 LLM 출력의 무인증 노출 표면이었다.

        **소유권(job↔user) 검사(SEC-27)**: `job_ownership` 테이블(POST /v1/generate가
        큐잉 시점에 기록)에서 `job_id`를 PK lookup한다. 행이 없거나(매핑 부재 — 이 배포
        이전에 큐잉된 job·잘못된 job_id) `user_id`가 요청자와 다르면(타 사용자 job) 둘 다
        **404**로 거부한다(403이 아닌 이유 — acceptance③: 소유자가 아니면 그 리소스의
        *존재 자체*도 노출하지 않는다. job_id는 UUID4라 존재 여부 자체는 열거 곤란하지만,
        403/404 응답 차이로 "존재하지만 내 것이 아님"을 알려주지 않는 것이 더 안전한
        기본값이다).

        완료(success) 시 `text`는 *검증 전 원시 출력*이다(앱 docstring 경계 메모) —
        학생 직접 노출 금지. 진행 중(pending)·실패(failure)·판정 불가(unknown)는 모두
        명확한 상태로 200을 돌려준다(폴링은 500 스택트레이스를 내지 않는다 — 가용성
        우선). result backend 도달 실패도 unknown으로 흡수된다(CeleryJobQueue.result).

        큐가 폴링(result)을 지원하지 않으면(가짜·미지원 구현) unknown으로 보고한다 —
        ollama check_status 기능 탐지와 동일한 방어 패턴. 소유권 검사는 그보다 *먼저*
        하므로, 큐 미지원이라도 소유자가 아니면 여전히 404다.
        """
        ownership = await session.get(JobOwnership, job_id)
        if ownership is None or ownership.user_id != user.user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
        queue = _get_queue(request)
        result_fn = getattr(queue, "result", None)
        if result_fn is None:
            # 폴링 미지원 큐 — 비크래시로 unknown 보고(상태 판정 불가).
            return JobStatusBody(
                job_id=job_id,
                state="unknown",
                error="queue does not support result polling",
            )
        job_status = result_fn(job_id)
        # 완료 텍스트는 워커가 *로그로만* 관측했으므로(slice 43·bare str 결과 계약), 폴링
        # 시점에 *재검증*해 신호를 노출한다 — 동기 경로와 HTTP 파리티. 결정론이라 재검증
        # 비용 미미·비차단(text 불변). 검증기는 Settings 게이트(_get_validator: 비활성 시 None).
        validator = _get_validator(request)
        signal = (
            validate_response(validator, job_status.text)
            if validator is not None
            and job_status.state == "success"
            and job_status.text is not None
            else None
        )
        return JobStatusBody(
            job_id=job_status.job_id,
            state=job_status.state,
            text=job_status.text,
            error=job_status.error,
            validation_signal=signal.reason if signal is not None else None,
        )

    # DB-backed 라우터 결선 — get_session 의존성으로 PostgreSQL을 읽고 쓴다(영속 레이어 →
    # HTTP). L3 인라인 엔드포인트와 달리 살아있는 PG를 요구하므로 통합테스트(@integration)와
    # 메인의 실 PG 검증으로 동작을 확인한다.
    app.include_router(auth_router)
    app.include_router(concepts_router)
    app.include_router(problems_router)
    app.include_router(users_router)
    app.include_router(me_router)
    app.include_router(privacy_router)
    app.include_router(coach_router)
    app.include_router(verify_router)
    app.include_router(devices_router)
    app.include_router(gating_router)
    app.include_router(visualization_router)
    app.include_router(interactions_router)
    app.include_router(scene_router)
    app.include_router(solution_paths_router)
    app.include_router(study_router)
    app.include_router(ocr_router)
    app.include_router(speech_router)
    app.include_router(reports_router)
    app.include_router(dsl_router)
    app.include_router(rights_router)
    # CUR-11: subject-neutral 교육과정 조회 표면(curricula·learning-outcomes·alignments).
    app.include_router(curricula_router)
    app.include_router(alignments_router)
    # ADMIN-04: Admin BFF 모듈 레지스트리 — GET /v1/admin/menu(좌측 내비 파생 원천).
    app.include_router(admin_menu_router)

    return app
