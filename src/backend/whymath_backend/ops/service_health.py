"""서비스 헬스 딥체크 + 인프로세스 요청 계측·알림 — OPS-01 프로덕션 관측성.

배경 (왜 이 모듈이 필요한가)
----------------------------
기존 표면은 둘이었다: `/health`(라이브니스·의존성 0·항상 200)와 `/status`(Ollama·클라우드
*보고형*·항상 200). 프로덕션 업타임 프로브가 "이 인스턴스가 트래픽을 받아도 되는가"를
HTTP 상태코드로 판정할 **레디니스 축**과, 에러율·지연·가동(uptime)을 SaaS 관측 인프라
(Langfuse)가 죽어도 읽을 수 있는 **인프로세스 축**이 없었다. 이 모듈이 그 두 축을 만든다:

1. **컴포넌트 딥체크** — DB(`SELECT 1`)·Redis(`PING`)·LLM 라우터(provider.check_status)의
   도달성을 *비크래시*로 판정한다. 실패 사유(`error`)에는 **예외 타입명만** 담는다 —
   `str(exc)`엔 DSN·호스트 등 환경 값이 섞일 수 있어 제외한다(시크릿·필드값 미포함).
   무타입 경고 금지(CLAUDE.md 침묵 실패 금지)의 뒤집힌 면이다: *타입은 반드시 남기고,
   값은 남기지 않는다*. "미구성"과 "도달 실패"는 구분한다 — 미구성은 오류가 아니다
   (None-vs-0 '모르면 모른다' 회계, `ops/cost_probe.py`·`ops/live_preflight.py` 정본).

2. **인프로세스 요청 계측(`ServiceMetrics`)** — 총 요청·5xx·최근 창(고정 크기 deque)
   에러율·지연(합계/최대/창 p95)·프로세스 uptime을 *프로세스 안에서* 집계한다. Langfuse가
   죽으면 그 축은 '측정 실패'로 드러나고, 이 축은 계속 판정치를 낸다(**이중 회계** —
   CLAUDE.md "측정·게이트 판정치를 외부 관측 인프라(SaaS)에만 의존 금지").

3. **알림 평가·경로(`evaluate_alerts`·`AlertLogNotifier`)** — Settings 임계 초과(breach)를
   ①구조화 warning 로그(*상태 전이 시에만* — 지속 위반의 매 요청 로그는 스팸이라 억제)
   ②`/health/ready` 응답 body의 `alerts` 필드(외부 업타임 프로브가 SaaS 없이 판정치를
   읽는 상시 노출)로 배선한다. ③(OPS-30) 상태 전이를 `AlertSink`(`ops/alert_delivery.py`
   웹훅)로 사람에게 내보낸다 — 로그만으로는 "보고 있지 않으면 알림이 아니다".

동시성 메모
-----------
`ServiceMetrics`·`AlertLogNotifier`는 **스레드-안전 장치를 두지 않는다** — FastAPI(uvicorn)
단일 asyncio 이벤트 루프에서 미들웨어·엔드포인트가 호출하고, `record`/`notify`는 await가
없는 순수 동기 구간이라 코루틴 인터리브로 쪼개지지 않는다(락 불요·명시적 결정). 다중
*워커*(프로세스) 배포는 워커별 독립 계측이다 — 프로세스 경계 합산은 외부 스크레이퍼(후속).
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from whymath_backend.config import Settings, get_settings
from whymath_backend.db.session import get_engine

# Redis 클라이언트 구성은 RedisCache와 동일한 빌더를 *재사용*한다(재발명 금지) —
# Settings.redis_url·decode_responses 관례가 캐시 경로와 항상 일치한다. 같은 패키지
# 내부의 의도적 재사용이라 비공개 이름 import를 허용한다(중복 구현이 더 나쁜 드리프트).
from whymath_backend.l3.cache.redis_cache import _build_default_client, _RedisClient

logger = logging.getLogger(__name__)

# 컴포넌트 이름 상수 — /health/ready components 키와 테스트가 공유하는 단일 어휘.
COMPONENT_DATABASE = "database"
COMPONENT_REDIS = "redis"
COMPONENT_LLM_ROUTER = "llm_router"

# 알림 metric 이름 상수 — 로그·/health/ready alerts 필드가 공유.
ALERT_METRIC_ERROR_RATE = "error_rate"
ALERT_METRIC_LATENCY_P95 = "latency_p95_ms"

# 라우트 매칭 실패 요청(404·라우터 도달 전 거절)이 모이는 단일 버킷 이름 — 원시 경로 문자열을
# 키로 쓰면 크롤러가 만든 임의 경로가 키를 무한히 늘린다(카디널리티 폭발·OPS-95).
ROUTE_UNMATCHED = "(unmatched)"


# ──────────────────────────────────────────────────────────────────────────
# 컴포넌트 딥체크 — 각 체크는 절대 예외를 던지지 않는다(비크래시 보고).
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ComponentCheck:
    """컴포넌트 딥체크 1건의 결과 — /health/ready components 항목의 원천.

    - `configured=False`는 *미구성/확인 수단 미노출*이다(오류 아님 — None-vs-0 원칙).
      이때 `reachable`은 None('판정 불가')이다 — False('도달 실패')와 구분한다(모르면
      모른다고 — 미구성을 다운으로 날조하지 않는다).
    - `error`는 도달 실패 사유의 **예외 타입명**(시크릿·환경값 미포함). 단 provider
      *보고형* 오류 문자열(OllamaStatus.error — 이미 /status가 노출하는 비크래시 표면)은
      기존 노출 정책 그대로 싣는다.
    - `required`는 ready 판정 필수 여부(정책) — DB만 True(근거는 /health/ready docstring).
    """

    name: str
    configured: bool
    reachable: bool | None
    required: bool
    error: str | None


async def check_database(engine: AsyncEngine | None = None) -> ComponentCheck:
    """DB 도달성 딥체크 — `SELECT 1` (기존 `db.session.get_engine` 재사용·lazy).

    engine 미주입 시 `get_engine()`(모듈 전역 lazy 엔진)을 쓴다 — 엔진 생성 자체는 풀만
    준비하므로, 실제 연결(과 실패)은 이 함수의 `connect()`+`SELECT 1`에서 처음 드러난다.
    도달 실패는 예외를 던지지 않고 `reachable=False` + 예외 *타입명*으로 보고한다 —
    `str(exc)`는 DSN·호스트가 섞일 수 있어 싣지 않는다(시크릿·값 미포함).
    """
    try:
        resolved = engine if engine is not None else get_engine()
        async with resolved.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — 도달 실패를 비크래시 보고(타입명 필수·침묵 실패 금지)
        return ComponentCheck(
            name=COMPONENT_DATABASE,
            configured=True,
            reachable=False,
            required=True,
            error=type(exc).__name__,
        )
    return ComponentCheck(
        name=COMPONENT_DATABASE, configured=True, reachable=True, required=True, error=None
    )


class RedisPing(Protocol):
    """PING만 요구하는 좁은 Redis 표면 — redis_cache `_RedisClient`의 부분집합.

    체크에 get/set은 불요하므로 표면을 좁혀 테스트 가짜를 최소화한다(구조적 타이핑).
    """

    async def ping(self) -> object:
        """연결 도달성 확인(redis PING). 도달 시 truthy, 실패 시 예외."""
        ...


class _LazyRedisPinger:
    """지연 생성 Redis PING 클라이언트 — 앱 수명 동안 1개를 재사용한다.

    `check_redis`를 호출할 때마다 새 클라이언트(연결 풀)를 만들면 레디니스 폴링이 풀을
    누적 생성한다 — 기본 probes(`default_readiness_probes`)는 이 pinger 1개를 닫아
    (클로저) 재사용한다. 클라이언트 구성은 RedisCache와 동일 빌더(`_build_default_client`)
    재사용이라 URL·디코딩 관례가 캐시와 일치한다.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        self._client: _RedisClient | None = None

    async def ping(self) -> object:
        """첫 호출에서 클라이언트를 만들고(lazy) PING을 위임한다(실패는 예외 그대로)."""
        if self._client is None:
            resolved = self._settings if self._settings is not None else get_settings()
            self._client = _build_default_client(resolved)
        return await self._client.ping()


async def check_redis(
    client: RedisPing | None = None, *, settings: Settings | None = None
) -> ComponentCheck:
    """Redis 도달성 딥체크 — `PING` (RedisCache와 동일한 클라이언트 구성 방식).

    client 미주입 시 기본 클라이언트를 lazy 생성한다(호출마다 새 풀 — 반복 폴링 경로는
    `default_readiness_probes`의 재사용 pinger를 쓴다). RedisCache.ping()을 그대로 쓰지
    않는 이유: 그 메서드는 예외를 *무타입*으로 삼켜 bool만 남긴다 — 여기서는 침묵 실패
    금지 원칙에 따라 예외 **타입명**을 보고에 남겨야 한다. `required=False`(보고만) —
    근거는 /health/ready docstring(캐시·rate limit은 성능 보완재·미도달은 강등이지 불능
    아님).
    """
    try:
        resolved = (
            client
            if client is not None
            else _build_default_client(settings if settings is not None else get_settings())
        )
        await resolved.ping()
    except Exception as exc:  # noqa: BLE001 — 도달 실패를 비크래시 보고(타입명 필수·침묵 실패 금지)
        return ComponentCheck(
            name=COMPONENT_REDIS,
            configured=True,
            reachable=False,
            required=False,
            error=type(exc).__name__,
        )
    return ComponentCheck(
        name=COMPONENT_REDIS, configured=True, reachable=True, required=False, error=None
    )


async def check_llm_router(provider: object) -> ComponentCheck:
    """LLM 라우터(로컬 provider) 도달성 딥체크 — 기존 `check_status` getattr 패턴 재사용.

    /status 엔드포인트와 동일한 기능 탐지 방어다: provider가 `check_status`를 노출하지
    않으면(가짜·클라우드 전용) **미구성**으로 보고한다(`configured=False`·`reachable=None`
    — 오류 아님·None-vs-0). 노출하면 그 보고형 상태(OllamaStatus: reachable·error)를
    그대로 매핑하고, 체크 호출 자체가 던지면 예외 *타입명*으로 보고한다.
    `required=False`(보고만) — 근거는 /health/ready docstring(LLM은 경로별 폴백 존재).
    """
    check = getattr(provider, "check_status", None)
    if check is None:
        # 확인 수단 미노출 = 미구성(오류 아님) — 도달성은 '모름'(None)으로 남긴다.
        return ComponentCheck(
            name=COMPONENT_LLM_ROUTER,
            configured=False,
            reachable=None,
            required=False,
            error=None,
        )
    try:
        status_report = await check()
    except Exception as exc:  # noqa: BLE001 — 도달 실패를 비크래시 보고(타입명 필수·침묵 실패 금지)
        return ComponentCheck(
            name=COMPONENT_LLM_ROUTER,
            configured=True,
            reachable=False,
            required=False,
            error=type(exc).__name__,
        )
    reachable = bool(getattr(status_report, "reachable", False))
    raw_error = getattr(status_report, "error", None)
    return ComponentCheck(
        name=COMPONENT_LLM_ROUTER,
        configured=True,
        reachable=reachable,
        required=False,
        error=raw_error if isinstance(raw_error, str) else None,
    )


# 레디니스 체크 1개의 호출 표면 — 인자 없이 await하면 ComponentCheck가 나온다(비크래시).
CheckFn = Callable[[], Awaitable[ComponentCheck]]


@dataclass(slots=True)
class ReadinessProbes:
    """레디니스 딥체크 묶음 — create_app이 주입받는 경계(테스트는 가짜 CheckFn 주입).

    cost_probe의 `ProbeDeps`와 동형인 의존성 묶음 패턴 — 프로덕션은
    `default_readiness_probes`(실 자산 배선), 테스트는 가짜 체크를 넣는다(hermetic).
    """

    database: CheckFn
    redis: CheckFn
    llm: CheckFn


def default_readiness_probes(
    *, provider: object, settings: Settings | None = None
) -> ReadinessProbes:
    """기본 probes — 실 자산(get_engine·Redis 클라이언트·provider.check_status)을 배선한다.

    전부 *지연*이다 — 이 함수 호출만으로는 DB·Redis·Ollama에 연결하지 않는다(create_app의
    지연 의존 관례와 동형·앱 구성은 라이브 인프라 불요). Redis pinger는 1개를 앱 수명
    동안 재사용한다(폴링마다 연결 풀 생성 방지 — `_LazyRedisPinger` docstring).
    """
    pinger = _LazyRedisPinger(settings=settings)

    async def _database() -> ComponentCheck:
        return await check_database()

    async def _redis() -> ComponentCheck:
        return await check_redis(pinger)

    async def _llm() -> ComponentCheck:
        return await check_llm_router(provider)

    return ReadinessProbes(database=_database, redis=_redis, llm=_llm)


# ──────────────────────────────────────────────────────────────────────────
# 인프로세스 요청 계측 — 이중 회계의 프로세스 안쪽 축(SaaS 독립).
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class RouteLatency:
    """라우트 템플릿 1개의 최근 창 지연·에러율 — S5(경로별 SLO)의 측정 원천(OPS-95).

    `route`는 원시 경로가 아니라 FastAPI 라우트 템플릿(`/v1/coach/sessions/{dialogue_id}/turns`)
    이다. 표본이 있는 라우트만 만들어지므로 count>=1이고 백분위는 항상 값이 있다(표본 0은
    스냅샷에 아예 없다 — '미측정'을 0.0으로 위장하지 않는다).
    """

    route: str
    count: int
    error_rate: float
    p50_latency_ms: float
    p75_latency_ms: float
    p95_latency_ms: float


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    """계측 스냅샷(불변) — /health/ready 노출·알림 평가의 입력.

    None 필드는 전부 '측정 불가/표본 없음'이다(0·0.0과 구분 — 모르면 모른다).
    """

    uptime_seconds: float
    total_requests: int
    total_5xx: int
    window_count: int
    window_error_rate: float | None
    window_p95_latency_ms: float | None
    latency_sum_ms: float
    latency_max_ms: float | None
    # 라우트별 최근 창(OPS-95) — 라우트 이름순. 기본값을 둬 기존 생성처(테스트 포함)를 깨지 않는다.
    routes: tuple[RouteLatency, ...] = ()


def _percentile(ordered: Sequence[float], q: float) -> float:
    """오름차순 표본의 nearest-rank 백분위(q∈(0,1]). 빈 입력은 호출자가 먼저 걸러야 한다.

    전역 p95와 라우트별 백분위가 같은 식을 쓰도록 한 곳에 둔다 — 식이 둘로 갈라지면 같은
    표본이 두 표면에서 다른 p95를 낸다.
    """
    index = max(0, math.ceil(len(ordered) * q) - 1)
    return ordered[index]


class ServiceMetrics:
    """인프로세스 요청 계측 — 총 요청·5xx·최근 창 에러율·지연·프로세스 uptime.

    최근 창은 고정 크기 deque(기본 500·`Settings.ops_metrics_window_size`)다 — 에러율·
    p95를 *최근* 트래픽에서 계산해, 전 기간 평균이 최근 악화를 희석하는 것을 막는다.
    스레드-안전 장치는 없다(모듈 docstring '동시성 메모' — asyncio 단일 루프 전제·명시).
    clock 주입은 테스트 결정론용(uptime을 가짜 시계로 검증).
    """

    def __init__(
        self,
        *,
        window_size: int = 500,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._started_at = clock()
        self._total_requests = 0
        self._total_5xx = 0
        self._latency_sum_ms = 0.0
        self._latency_max_ms: float | None = None  # 요청 0건이면 최대 지연은 '없음'(0 아님)
        # (지연 ms, 5xx 여부) 최근 창 — maxlen이 가장 오래된 표본을 자동 축출한다.
        self._window: deque[tuple[float, bool]] = deque(maxlen=window_size)
        self._window_size = window_size
        # 라우트 템플릿 → 그 라우트의 최근 창(OPS-95). 키는 라우트 표의 템플릿 + 미매칭 버킷뿐이라
        # 유한하다(원시 경로를 키로 쓰지 않는 것이 카디널리티 방어선).
        self._route_windows: dict[str, deque[tuple[float, bool]]] = {}

    def record(self, latency_ms: float, status_code: int, route: str | None = None) -> None:
        """요청 1건 기록 — 지연(ms)·상태코드. 5xx(>=500)만 오류로 회계한다.

        `route`(OPS-95)는 라우트 *템플릿*이다. 주면 전역 창에 더해 그 라우트의 창에도 기록하고,
        None이면 전역만 기록한다(라우트를 모르는 기존 호출자 호환 — 미들웨어는 미매칭 요청에
        `ROUTE_UNMATCHED`를 명시해 넘긴다). 요청 경로의 비용은 deque append 상수 시간이다 —
        정렬은 `snapshot()`(조회 시점)에서만 한다.

        4xx는 오류율에 넣지 않는다 — 클라이언트 귀책(잘못된 입력·미인증)은 서비스 가동
        판정과 무관하고, 넣으면 크롤러·오타 트래픽이 가짜 알림을 낸다.
        """
        is_5xx = status_code >= 500
        self._total_requests += 1
        if is_5xx:
            self._total_5xx += 1
        self._latency_sum_ms += latency_ms
        self._latency_max_ms = (
            latency_ms if self._latency_max_ms is None else max(self._latency_max_ms, latency_ms)
        )
        self._window.append((latency_ms, is_5xx))
        if route is not None:
            route_window = self._route_windows.get(route)
            if route_window is None:
                route_window = deque(maxlen=self._window_size)
                self._route_windows[route] = route_window
            route_window.append((latency_ms, is_5xx))

    def uptime_seconds(self) -> float:
        """프로세스(계측 시작) 이후 경과 초 — 가동(uptime) 보고의 원천."""
        return self._clock() - self._started_at

    def window_error_rate(self) -> float | None:
        """최근 창 5xx 비율. 창 표본 0이면 None('미측정'·0.0과 구분 — 날조 금지)."""
        if not self._window:
            return None
        return sum(1 for _, is_5xx in self._window if is_5xx) / len(self._window)

    def window_p95_latency_ms(self) -> float | None:
        """최근 창 p95 지연(ms). 창 표본 0이면 None('미측정'·0.0과 구분)."""
        if not self._window:
            return None
        return _percentile(sorted(latency for latency, _ in self._window), 0.95)

    def route_latencies(self) -> tuple[RouteLatency, ...]:
        """라우트별 최근 창 지연·에러율 — 라우트 이름순(결정적 출력). 표본 없는 라우트는 없다."""
        rows: list[RouteLatency] = []
        for route in sorted(self._route_windows):
            window = self._route_windows[route]
            if not window:
                continue
            ordered = sorted(latency for latency, _ in window)
            rows.append(
                RouteLatency(
                    route=route,
                    count=len(window),
                    error_rate=sum(1 for _, is_5xx in window if is_5xx) / len(window),
                    p50_latency_ms=_percentile(ordered, 0.50),
                    p75_latency_ms=_percentile(ordered, 0.75),
                    p95_latency_ms=_percentile(ordered, 0.95),
                )
            )
        return tuple(rows)

    def snapshot(self, *, include_routes: bool = True) -> MetricsSnapshot:
        """현재 계측의 불변 스냅샷 — 노출·알림 평가는 이 스냅샷 기준(평가 중 변형 방지).

        `include_routes=False`는 요청마다 알림을 평가하는 경로용이다 — 라우트별 백분위는 정렬이
        필요해 요청 경로에서 계산하면 안 된다(OPS-95: 정렬은 조회 시점에만). 알림 판정(S1·S2)은
        전역 지표만 쓰므로 결과가 같다.
        """
        return MetricsSnapshot(
            uptime_seconds=self.uptime_seconds(),
            total_requests=self._total_requests,
            total_5xx=self._total_5xx,
            window_count=len(self._window),
            window_error_rate=self.window_error_rate(),
            window_p95_latency_ms=self.window_p95_latency_ms(),
            latency_sum_ms=self._latency_sum_ms,
            latency_max_ms=self._latency_max_ms,
            routes=self.route_latencies() if include_routes else (),
        )


# ──────────────────────────────────────────────────────────────────────────
# 알림 평가·경로 — ①상태 전이 warning 로그 ②/health/ready body(alerts) 상시 노출.
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Alert:
    """임계 위반(breach) 1건 — metric 이름·실측치·임계를 병기한다(무맥락 경고 금지)."""

    metric: str
    observed: float
    threshold: float


def evaluate_alerts(
    snapshot: MetricsSnapshot,
    *,
    error_rate_threshold: float,
    latency_p95_threshold_ms: float,
) -> list[Alert]:
    """스냅샷을 임계에 대조해 breach 목록을 반환한다(순수 — I/O 0·hermetic 검증 가능).

    판정 규약(테스트로 동결):
    - **초과(>)만** breach다 — 경계 동률(==)은 비위반(임계는 '허용 상한').
    - None 지표(표본 없음)는 평가하지 않는다 — 미측정은 위반이 아니라 '모름'이다
      (None-vs-0). 단 미측정이 '정상'으로 위장되지도 않는다 — /health/ready body가
      window_error_rate=None을 그대로 노출해 외부 프로브가 미측정을 식별한다.
    """
    alerts: list[Alert] = []
    if snapshot.window_error_rate is not None and snapshot.window_error_rate > error_rate_threshold:
        alerts.append(
            Alert(
                metric=ALERT_METRIC_ERROR_RATE,
                observed=snapshot.window_error_rate,
                threshold=error_rate_threshold,
            )
        )
    if (
        snapshot.window_p95_latency_ms is not None
        and snapshot.window_p95_latency_ms > latency_p95_threshold_ms
    ):
        alerts.append(
            Alert(
                metric=ALERT_METRIC_LATENCY_P95,
                observed=snapshot.window_p95_latency_ms,
                threshold=latency_p95_threshold_ms,
            )
        )
    return alerts


class AlertSink(Protocol):
    """알림 상태 전이를 받는 추가 발송 채널(OPS-30) — 판정은 `AlertLogNotifier`가 이미 끝냈다."""

    def on_transition(self, entered: Sequence[Alert], cleared: Sequence[str]) -> None: ...


class AlertLogNotifier:
    """알림 로그 경로 — breach *상태 전이 시에만* 기록한다(스팸 방지).

    같은 위반이 지속되는 동안 매 요청 warning을 찍으면 로그가 알림 가치를 잃는다. 직전
    위반 metric 집합을 기억해 *새로 진입한* 위반만 warning(임계·실측치 병기), *해소된*
    위반만 info로 남긴다. 로그에 시크릿·필드값은 없다(metric 이름·수치뿐).

    OPS-30: `sinks`로 실발송 채널(웹훅)을 *옆에* 붙인다. 전이 판정(진입·해소 계산)은 이 클래스
    한 곳에만 있고, sink는 계산된 전이를 받을 뿐이다. sink 실패는 요청·로그 경로를 깨지 않는다.
    """

    def __init__(
        self,
        target_logger: logging.Logger | None = None,
        sinks: Sequence[AlertSink] = (),
    ) -> None:
        self._logger = target_logger if target_logger is not None else logger
        self._sinks = tuple(sinks)
        self._active: frozenset[str] = frozenset()

    def notify(self, alerts: Sequence[Alert]) -> None:
        """breach 목록을 직전 상태와 비교해 전이만 로그한다(진입=warning·해소=info)."""
        current = frozenset(alert.metric for alert in alerts)
        entered = current - self._active
        cleared = self._active - current
        entered_alerts = [alert for alert in alerts if alert.metric in entered]
        for alert in entered_alerts:
            self._logger.warning(
                "서비스 알림 breach 진입 — metric=%s observed=%.4f threshold=%.4f",
                alert.metric,
                alert.observed,
                alert.threshold,
            )
        cleared_metrics = sorted(cleared)
        for metric in cleared_metrics:
            self._logger.info("서비스 알림 해소 — metric=%s", metric)
        self._active = current
        if entered_alerts or cleared_metrics:
            self._dispatch_to_sinks(entered_alerts, cleared_metrics)

    def _dispatch_to_sinks(self, entered: list[Alert], cleared: list[str]) -> None:
        """전이를 각 sink에 넘긴다 — sink 실패가 다른 sink·요청을 깨지 않는다(타입명 로그)."""
        for sink in self._sinks:
            try:
                sink.on_transition(entered, cleared)
            except Exception as exc:  # noqa: BLE001 — sink 실패 흡수(요청 보호)·타입명 로그 필수
                self._logger.warning(
                    "알림 sink 전달 실패(로그 경로는 정상) — 예외 타입: %s", type(exc).__name__
                )
