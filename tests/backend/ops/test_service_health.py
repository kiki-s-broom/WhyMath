"""service_health 단위테스트 — hermetic(라이브 DB·Redis·LLM 0)·OPS-01.

컴포넌트 딥체크(check_database·check_redis·check_llm_router)는 가짜 엔진/핑거/provider로
성공·실패 *양방향*을 변별하고(실패 시 error에 예외 **타입명** 포함 — 침묵 실패 금지 동결),
ServiceMetrics·evaluate_alerts는 순수 로직이라 픽스처로 경계까지 전수 단언한다.
AlertLogNotifier는 caplog로 '상태 전이 시에만 기록'(스팸 방지)을 동결한다.
"""

from __future__ import annotations

import logging

import pytest

from whymath_backend.l3.providers.ollama import OllamaStatus
from whymath_backend.ops import service_health as sh


# ──────────────────────────────────────────────────────────────────────────
# 가짜 엔진·핑거·provider — 라이브 인프라 없이 체크 경로를 태운다.
# ──────────────────────────────────────────────────────────────────────────
class _BoomError(Exception):
    """주입 실패용 커스텀 예외 — 타입명 로그 검증이 *이 이름*을 찾아 변별력을 가진다."""


class _OkConn:
    """성공 경로 가짜 커넥션 — async CM + execute(SELECT 1) 흡수."""

    async def __aenter__(self) -> _OkConn:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: object) -> None:
        return None


class _OkEngine:
    """성공 경로 가짜 엔진 — connect()가 살아있는 커넥션 CM을 준다."""

    def connect(self) -> _OkConn:
        return _OkConn()


class _FailingConn:
    """실패 경로 가짜 커넥션 — 진입(연결) 시점에 폭발(도달 실패 모사)."""

    async def __aenter__(self) -> _FailingConn:
        raise _BoomError("연결 실패(주입)")

    async def __aexit__(self, *args: object) -> None:
        return None


class _FailingEngine:
    def connect(self) -> _FailingConn:
        return _FailingConn()


class _OkPinger:
    async def ping(self) -> bool:
        return True


class _FailingPinger:
    async def ping(self) -> bool:
        raise ConnectionError("redis 도달 실패(주입)")


class _ProviderWithStatus:
    """check_status를 노출하는 가짜 provider — OllamaStatus 보고형 표면."""

    def __init__(self, status: OllamaStatus) -> None:
        self._status = status

    async def check_status(self) -> OllamaStatus:
        return self._status


class _ProviderWithoutStatus:
    """check_status 미노출 provider — '미구성(오류 아님)' 분기 검증용."""


class _ProviderRaisingStatus:
    """check_status 호출 자체가 폭발하는 provider — 예외 타입명 보고 검증용."""

    async def check_status(self) -> OllamaStatus:
        raise _BoomError("상태 체크 폭발(주입)")


# ──────────────────────────────────────────────────────────────────────────
# check_database — 성공/실패 양방향 + 타입명 동결.
# ──────────────────────────────────────────────────────────────────────────
async def test_check_database_ok() -> None:
    """SELECT 1 성공 ⇒ reachable=True·error=None·required=True(ready 필수 컴포넌트)."""
    result = await sh.check_database(engine=_OkEngine())  # type: ignore[arg-type]
    assert result.name == sh.COMPONENT_DATABASE
    assert result.configured is True
    assert result.reachable is True
    assert result.required is True
    assert result.error is None


async def test_check_database_failure_reports_exception_type_name() -> None:
    """도달 실패 ⇒ 비크래시 reachable=False + error에 예외 **타입명**(침묵 실패 금지).

    타입명 *만* 싣는다 — str(exc)의 메시지(DSN·호스트 등 환경 값 위험)는 미포함 동결.
    """
    result = await sh.check_database(engine=_FailingEngine())  # type: ignore[arg-type]
    assert result.reachable is False
    assert result.error == "_BoomError"  # 타입명 그 자체(메시지 미포함)
    assert "주입" not in (result.error or "")  # 예외 메시지가 새지 않음


# ──────────────────────────────────────────────────────────────────────────
# check_redis — 성공/실패 양방향 + 타입명 동결.
# ──────────────────────────────────────────────────────────────────────────
async def test_check_redis_ok() -> None:
    """PING 성공 ⇒ reachable=True·required=False(보고만 — ready 게이트 아님)."""
    result = await sh.check_redis(_OkPinger())
    assert result.name == sh.COMPONENT_REDIS
    assert result.reachable is True
    assert result.required is False
    assert result.error is None


async def test_check_redis_failure_reports_exception_type_name() -> None:
    """PING 실패 ⇒ reachable=False + error=예외 타입명(RedisCache.ping의 무타입 bool과 대비)."""
    result = await sh.check_redis(_FailingPinger())
    assert result.reachable is False
    assert result.error == "ConnectionError"


# ──────────────────────────────────────────────────────────────────────────
# check_llm_router — 미구성/도달/실패 3분기(None-vs-0).
# ──────────────────────────────────────────────────────────────────────────
async def test_check_llm_router_reachable() -> None:
    """provider.check_status 도달 ⇒ reachable=True (기존 /status 표면 재사용)."""
    provider = _ProviderWithStatus(OllamaStatus(reachable=True, models=()))
    result = await sh.check_llm_router(provider)
    assert result.name == sh.COMPONENT_LLM_ROUTER
    assert result.configured is True
    assert result.reachable is True
    assert result.required is False


async def test_check_llm_router_unreachable_passes_report_error() -> None:
    """도달 불가 보고형 상태 ⇒ reachable=False + provider 보고 오류 문자열 그대로."""
    provider = _ProviderWithStatus(
        OllamaStatus(reachable=False, models=(), error="ConnectError: 데몬 미가동")
    )
    result = await sh.check_llm_router(provider)
    assert result.reachable is False
    assert result.error == "ConnectError: 데몬 미가동"


async def test_check_llm_router_not_exposed_is_unconfigured_not_error() -> None:
    """check_status 미노출 ⇒ 미구성(configured=False)·reachable=None — 오류로 날조 금지."""
    result = await sh.check_llm_router(_ProviderWithoutStatus())
    assert result.configured is False
    assert result.reachable is None  # '모름' — False('다운')와 구분
    assert result.error is None  # 미구성은 오류가 아니다


async def test_check_llm_router_check_raises_reports_type_name() -> None:
    """체크 호출 자체가 던지면 ⇒ 비크래시 reachable=False + 예외 타입명."""
    result = await sh.check_llm_router(_ProviderRaisingStatus())
    assert result.configured is True
    assert result.reachable is False
    assert result.error == "_BoomError"


# ──────────────────────────────────────────────────────────────────────────
# ServiceMetrics — 누적·최근 창·p95·uptime(가짜 시계 결정론).
# ──────────────────────────────────────────────────────────────────────────
class _FakeClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_metrics_empty_snapshot_is_unknown_not_zero() -> None:
    """요청 0건 ⇒ 창 에러율·p95·최대 지연은 None('미측정') — 0으로 날조 금지."""
    snapshot = sh.ServiceMetrics(clock=_FakeClock()).snapshot()
    assert snapshot.total_requests == 0
    assert snapshot.window_error_rate is None
    assert snapshot.window_p95_latency_ms is None
    assert snapshot.latency_max_ms is None
    assert snapshot.latency_sum_ms == 0.0  # 합계 0은 참값(미측정 아님)


def test_metrics_error_rate_rises_with_5xx() -> None:
    """5xx 기록이 누적되면 창 에러율이 상승한다(4xx는 오류로 회계하지 않음)."""
    metrics = sh.ServiceMetrics(clock=_FakeClock())
    for _ in range(8):
        metrics.record(10.0, 200)
    metrics.record(10.0, 404)  # 4xx — 오류율 무영향
    assert metrics.window_error_rate() == 0.0
    metrics.record(10.0, 500)
    snapshot = metrics.snapshot()
    assert snapshot.total_requests == 10
    assert snapshot.total_5xx == 1
    assert snapshot.window_error_rate == pytest.approx(0.1)


def test_metrics_latency_accounting_and_p95() -> None:
    """지연 합계/최대 + 창 p95(1~100ms 균일 분포 ⇒ p95=95ms) 결정론 검증."""
    metrics = sh.ServiceMetrics(window_size=100, clock=_FakeClock())
    for ms in range(1, 101):  # 1..100
        metrics.record(float(ms), 200)
    snapshot = metrics.snapshot()
    assert snapshot.latency_sum_ms == pytest.approx(5050.0)
    assert snapshot.latency_max_ms == 100.0
    assert snapshot.window_p95_latency_ms == 95.0


def test_metrics_window_evicts_oldest() -> None:
    """고정 크기 창 — maxlen 초과 시 가장 오래된 표본이 밀려난다(최근성 보장)."""
    metrics = sh.ServiceMetrics(window_size=3, clock=_FakeClock())
    metrics.record(10.0, 500)  # 곧 축출될 5xx
    for _ in range(3):
        metrics.record(10.0, 200)
    snapshot = metrics.snapshot()
    assert snapshot.window_count == 3
    assert snapshot.window_error_rate == 0.0  # 축출된 5xx는 창 밖(누적 total_5xx엔 남음)
    assert snapshot.total_5xx == 1


# ──────────────────────────────────────────────────────────────────────────
# OPS-95 — 라우트 템플릿 차원(SLO S5): 라우트별 p50/p75/p95·표본 수·에러율.
# ──────────────────────────────────────────────────────────────────────────
_COACH_TURN = "/v1/coach/sessions/{dialogue_id}/turns"
_PROBLEM = "/v1/problems/{problem_id}"


def test_route_windows_are_separated_not_mixed() -> None:
    """느린 코치 턴과 빠른 문제 조회가 한 창에 섞이지 않는다 — S5의 존재 이유.

    전역 p95는 느린 쪽에 끌려가 빠른 라우트를 위장하지만, 라우트별 p95는 각자의 값을 낸다.
    """
    metrics = sh.ServiceMetrics(clock=_FakeClock())
    for _ in range(50):
        metrics.record(4000.0, 200, _COACH_TURN)
        metrics.record(20.0, 200, _PROBLEM)
    by_route = {row.route: row for row in metrics.snapshot().routes}
    assert by_route[_COACH_TURN].p95_latency_ms == 4000.0
    assert by_route[_PROBLEM].p95_latency_ms == 20.0
    assert by_route[_COACH_TURN].count == 50 and by_route[_PROBLEM].count == 50
    assert (
        metrics.window_p95_latency_ms() == 4000.0
    )  # 전역은 섞여 있다(= 라우트 차원이 필요한 이유)


def test_route_percentiles_p50_p75_p95_nearest_rank() -> None:
    """1..100ms 균일 분포 ⇒ nearest-rank p50=50·p75=75·p95=95(전역 p95와 같은 식)."""
    metrics = sh.ServiceMetrics(window_size=100, clock=_FakeClock())
    for ms in range(1, 101):
        metrics.record(float(ms), 200, _PROBLEM)
    (row,) = metrics.snapshot().routes
    assert (row.p50_latency_ms, row.p75_latency_ms, row.p95_latency_ms) == (50.0, 75.0, 95.0)
    assert row.p95_latency_ms == metrics.window_p95_latency_ms()  # 두 표면의 식이 같다


def test_route_error_rate_counts_only_5xx_per_route() -> None:
    """라우트별 에러율 — 5xx만 회계(4xx 제외)하고 다른 라우트에 번지지 않는다."""
    metrics = sh.ServiceMetrics(clock=_FakeClock())
    for _ in range(3):
        metrics.record(10.0, 200, _COACH_TURN)
    metrics.record(10.0, 500, _COACH_TURN)
    metrics.record(10.0, 404, _PROBLEM)
    by_route = {row.route: row for row in metrics.snapshot().routes}
    assert by_route[_COACH_TURN].error_rate == pytest.approx(0.25)
    assert by_route[_PROBLEM].error_rate == 0.0


def test_route_window_evicts_oldest_per_route() -> None:
    """라우트별 창도 고정 크기 — 한 라우트의 폭주가 다른 라우트의 표본을 밀어내지 않는다."""
    metrics = sh.ServiceMetrics(window_size=3, clock=_FakeClock())
    metrics.record(9999.0, 200, _COACH_TURN)  # 곧 축출될 이상치
    for _ in range(3):
        metrics.record(10.0, 200, _COACH_TURN)
    metrics.record(7.0, 200, _PROBLEM)
    by_route = {row.route: row for row in metrics.snapshot().routes}
    assert by_route[_COACH_TURN].count == 3
    assert by_route[_COACH_TURN].p95_latency_ms == 10.0  # 축출된 9999는 창 밖
    assert by_route[_PROBLEM].count == 1  # 다른 라우트는 무영향


def test_route_none_records_global_only() -> None:
    """route 미지정(기존 호출자) ⇒ 전역만 기록 — 라우트 표에 이름 없는 행을 날조하지 않는다."""
    metrics = sh.ServiceMetrics(clock=_FakeClock())
    metrics.record(10.0, 200)
    snapshot = metrics.snapshot()
    assert snapshot.total_requests == 1
    assert snapshot.routes == ()


def test_route_without_samples_is_absent_not_zero() -> None:
    """표본 0인 라우트는 목록에 없다 — 0.0으로 위장한 행을 만들지 않는다(None-vs-0)."""
    assert sh.ServiceMetrics(clock=_FakeClock()).snapshot().routes == ()


def test_routes_are_sorted_by_name_for_deterministic_output() -> None:
    """라우트 순서는 이름순 — 기록 순서에 따라 응답이 흔들리지 않는다."""
    metrics = sh.ServiceMetrics(clock=_FakeClock())
    for route in ("/v1/zzz", sh.ROUTE_UNMATCHED, "/v1/aaa"):
        metrics.record(1.0, 200, route)
    names = [row.route for row in metrics.snapshot().routes]
    assert names == sorted(names)


def test_snapshot_can_skip_route_percentiles_for_per_request_path() -> None:
    """알림 평가용 스냅샷은 라우트 계산을 건너뛴다(정렬은 조회 시점에만 — OPS-95 ⑤).

    전역 필드는 그대로이고 routes만 비어, 알림 판정(S1·S2)이 비트동일이다.
    """
    metrics = sh.ServiceMetrics(clock=_FakeClock())
    metrics.record(30.0, 500, _COACH_TURN)
    full = metrics.snapshot()
    light = metrics.snapshot(include_routes=False)
    assert full.routes and light.routes == ()
    assert full.window_p95_latency_ms == light.window_p95_latency_ms
    assert full.window_error_rate == light.window_error_rate


def test_metrics_uptime_uses_clock() -> None:
    """uptime = 계측 시작 이후 경과 초(가짜 시계로 결정론 검증)."""
    clock = _FakeClock(now=100.0)
    metrics = sh.ServiceMetrics(clock=clock)
    clock.now = 107.5
    assert metrics.uptime_seconds() == pytest.approx(7.5)


# ──────────────────────────────────────────────────────────────────────────
# evaluate_alerts — 초과/경계/미측정(순수·경계 동결).
# ──────────────────────────────────────────────────────────────────────────
def _snapshot(error_rate: float | None, p95_ms: float | None) -> sh.MetricsSnapshot:
    return sh.MetricsSnapshot(
        uptime_seconds=1.0,
        total_requests=10,
        total_5xx=1,
        window_count=10,
        window_error_rate=error_rate,
        window_p95_latency_ms=p95_ms,
        latency_sum_ms=100.0,
        latency_max_ms=10.0,
    )


def test_evaluate_alerts_below_threshold_no_alert() -> None:
    """임계 미만 ⇒ 알림 없음."""
    alerts = sh.evaluate_alerts(
        _snapshot(0.01, 100.0), error_rate_threshold=0.05, latency_p95_threshold_ms=5000.0
    )
    assert alerts == []


def test_evaluate_alerts_boundary_equal_is_not_breach() -> None:
    """경계 케이스 — 임계 *동률*(==)은 비위반(초과만 breach·계약 동결)."""
    alerts = sh.evaluate_alerts(
        _snapshot(0.05, 5000.0), error_rate_threshold=0.05, latency_p95_threshold_ms=5000.0
    )
    assert alerts == []


def test_evaluate_alerts_error_rate_breach() -> None:
    """에러율 초과 ⇒ error_rate 알림(실측치·임계 병기)."""
    alerts = sh.evaluate_alerts(
        _snapshot(0.2, 100.0), error_rate_threshold=0.05, latency_p95_threshold_ms=5000.0
    )
    assert [a.metric for a in alerts] == [sh.ALERT_METRIC_ERROR_RATE]
    assert alerts[0].observed == pytest.approx(0.2)
    assert alerts[0].threshold == pytest.approx(0.05)


def test_evaluate_alerts_latency_breach() -> None:
    """p95 지연 초과 ⇒ latency_p95_ms 알림."""
    alerts = sh.evaluate_alerts(
        _snapshot(0.0, 5000.1), error_rate_threshold=0.05, latency_p95_threshold_ms=5000.0
    )
    assert [a.metric for a in alerts] == [sh.ALERT_METRIC_LATENCY_P95]


def test_evaluate_alerts_both_breach() -> None:
    """두 지표 동시 초과 ⇒ 알림 2건."""
    alerts = sh.evaluate_alerts(
        _snapshot(1.0, 9999.0), error_rate_threshold=0.05, latency_p95_threshold_ms=5000.0
    )
    assert {a.metric for a in alerts} == {
        sh.ALERT_METRIC_ERROR_RATE,
        sh.ALERT_METRIC_LATENCY_P95,
    }


def test_evaluate_alerts_unknown_metrics_do_not_alert() -> None:
    """미측정(None) 지표는 평가하지 않는다 — 표본 없음은 위반이 아니라 '모름'(None-vs-0)."""
    alerts = sh.evaluate_alerts(
        _snapshot(None, None), error_rate_threshold=0.05, latency_p95_threshold_ms=5000.0
    )
    assert alerts == []


# ──────────────────────────────────────────────────────────────────────────
# AlertLogNotifier — 상태 전이 시에만 기록(스팸 방지 동결).
# ──────────────────────────────────────────────────────────────────────────
_LOGGER_NAME = "whymath_backend.ops.service_health"


def test_notifier_logs_only_on_transition(caplog: pytest.LogCaptureFixture) -> None:
    """진입 시 warning 1회 → 지속 위반은 무로그 → 해소 시 info → 재진입 시 다시 warning."""
    notifier = sh.AlertLogNotifier()
    breach = [sh.Alert(metric=sh.ALERT_METRIC_ERROR_RATE, observed=0.5, threshold=0.05)]

    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        notifier.notify(breach)  # 진입 — warning 1회(임계·실측치 병기)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert sh.ALERT_METRIC_ERROR_RATE in warnings[0].getMessage()
        assert "0.5" in warnings[0].getMessage()  # 실측치 병기
        assert "0.05" in warnings[0].getMessage()  # 임계 병기

        caplog.clear()
        notifier.notify(breach)  # 같은 위반 지속 — 로그 0(스팸 방지)
        assert caplog.records == []

        notifier.notify([])  # 해소 — info 1회
        infos = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(infos) == 1
        assert "해소" in infos[0].getMessage()

        caplog.clear()
        notifier.notify(breach)  # 재진입 — 다시 warning
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
