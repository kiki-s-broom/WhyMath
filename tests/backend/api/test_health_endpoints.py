"""/health/live·/health/ready·요청 계측 미들웨어 테스트 — OPS-01 (hermetic·라이브 인프라 0).

create_app() 팩토리에 가짜(provider·cache·trace·queue + metrics·readiness_probes)를
주입한다(tests/backend/api 관행). 핵심 동결 계약:
  1. 라이브니스 — 의존성 전무 상태에서 /health(하위호환)·/health/live 둘 다 200.
  2. 레디니스 **변별력 양방향** — DB 체크 성공→200/ready·실패→503, 실패 body의
     error에 예외 **타입명** 포함(실 check_database + 폭발 가짜 엔진 경유).
  3. ready 정책 — Redis·LLM 다운은 *보고만*(required=false)·DB만 게이트.
  4. alerts 이중 회계 — 임계 초과 시 /health/ready body.alerts에 상시 노출(SaaS 무관).
  5. 미들웨어 — 요청 계측(2xx/4xx/미처리 예외 5xx)·ops 프로브 경로 제외·**계측 내부
     예외 주입 시 요청은 정상 응답 + 로그에 예외 타입명**(silent failure 금지 동결).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from whymath_backend.api._auth import UserProfile, get_current_user
from whymath_backend.app import create_app
from whymath_backend.db.models.job_ownership import JobOwnership
from whymath_backend.db.session import get_session
from whymath_backend.l3.interfaces import InMemoryCache, RecordingTraceSink
from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l3.providers.ollama import OllamaStatus
from whymath_backend.l3.queue.celery_job_queue import JobStatus
from whymath_backend.ops.service_health import (
    COMPONENT_DATABASE,
    COMPONENT_LLM_ROUTER,
    COMPONENT_REDIS,
    ComponentCheck,
    ReadinessProbes,
    ServiceMetrics,
    check_database,
)

# ──────────────────────────────────────────────────────────────────────────
# 가짜 의존성 — 라이브 Ollama·Redis·PG·broker 차단(hermetic).
# ──────────────────────────────────────────────────────────────────────────
# 계측 표본용 고정 인증 사용자 — `/v1/jobs` 경로가 SEC-24(원 SEC-15) CurrentUser 게이트를 얻은 뒤에도
# 이 파일의 미들웨어 테스트가 그 경로를 2xx 표본으로 계속 쓸 수 있게 한다(_build_app 참조).
_FAKE_METRICS_USER = UserProfile(user_id=uuid.uuid4())


class _FakeOwnershipSession:
    """SEC-27: `/v1/jobs/{id}`가 이제 `session.get(JobOwnership, ...)`을 부른다 — 이 파일의
    관심사(계측 미들웨어)와 무관한 실 DB 진입을 막고, 표본용 job_id 전부를
    `_FAKE_METRICS_USER` 소유로 취급한다(test_app.py `_FakeSession` 동형·간이판)."""

    async def get(self, model: Any, pk: Any) -> Any:
        if model is JobOwnership:
            return JobOwnership(job_id=pk, user_id=_FAKE_METRICS_USER.user_id)
        return None


async def _fake_session() -> AsyncIterator[_FakeOwnershipSession]:
    yield _FakeOwnershipSession()


class _BoomError(Exception):
    """주입 실패용 커스텀 예외 — 로그·body의 타입명 검증이 이 이름을 찾는다(변별력)."""


class _StubProvider:
    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision
    ) -> GenerationResult:
        return GenerationResult("원시출력")

    async def check_status(self) -> OllamaStatus:
        return OllamaStatus(reachable=True, models=())


class _StubQueue:
    async def enqueue(self, payload: dict[str, object]) -> str:
        return "job-1"

    def result(self, job_id: str) -> JobStatus:
        return JobStatus(job_id=job_id, state="pending")


def _ok_check(name: str, *, required: bool) -> ComponentCheck:
    return ComponentCheck(name=name, configured=True, reachable=True, required=required, error=None)


def _down_check(name: str, *, required: bool) -> ComponentCheck:
    return ComponentCheck(
        name=name, configured=True, reachable=False, required=required, error="ConnectionError"
    )


def _probes(
    db: ComponentCheck | None = None,
    redis: ComponentCheck | None = None,
    llm: ComponentCheck | None = None,
) -> ReadinessProbes:
    """고정 결과를 돌려주는 가짜 probes — 기본은 전부 도달 성공."""
    resolved_db = db if db is not None else _ok_check(COMPONENT_DATABASE, required=True)
    resolved_redis = redis if redis is not None else _ok_check(COMPONENT_REDIS, required=False)
    resolved_llm = llm if llm is not None else _ok_check(COMPONENT_LLM_ROUTER, required=False)

    async def _db() -> ComponentCheck:
        return resolved_db

    async def _redis() -> ComponentCheck:
        return resolved_redis

    async def _llm() -> ComponentCheck:
        return resolved_llm

    return ReadinessProbes(database=_db, redis=_redis, llm=_llm)


def _build_app(
    *,
    probes: ReadinessProbes | None = None,
    metrics: ServiceMetrics | None = None,
) -> tuple[FastAPI, ServiceMetrics]:
    resolved_metrics = metrics if metrics is not None else ServiceMetrics()
    app = create_app(
        provider=_StubProvider(),
        cache=InMemoryCache(),
        trace=RecordingTraceSink(),
        queue=_StubQueue(),  # 라이브 broker 차단(test_app 관행)
        metrics=resolved_metrics,
        readiness_probes=probes if probes is not None else _probes(),
    )
    # 이 파일의 관심사는 계측 미들웨어·health 게이트다 — 인증은 관심 밖이라 고정 사용자로
    # 오버라이드한다(test_app.py `_client()` 동형). `/v1/jobs`가 SEC-24(원 SEC-15)로 CurrentUser 게이트를
    # 얻어, 계측 표본용으로 그 경로를 쓰는 아래 테스트들이 401을 받지 않게 한다(인증 자체의
    # 양방향 검증은 test_app.py `TestJobsAuthGate`가 오버라이드 없이 담당).
    app.dependency_overrides[get_current_user] = lambda: _FAKE_METRICS_USER
    app.dependency_overrides[get_session] = _fake_session
    return app, resolved_metrics


# ──────────────────────────────────────────────────────────────────────────
# 라이브니스 — 의존성 전무 상태에서 200 (분리 엔드포인트 + 하위호환).
# ──────────────────────────────────────────────────────────────────────────
class TestLiveness:
    def test_health_live_ok_without_dependencies(self) -> None:
        """/health/live — 의존성 0으로 200(프로세스 생존만)."""
        app, _ = _build_app()
        resp = TestClient(app).get("/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_legacy_health_unchanged(self) -> None:
        """기존 /health 하위호환 — 응답 계약 불변(기존 프로브·런북 보호)."""
        app, _ = _build_app()
        resp = TestClient(app).get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────────
# 레디니스 — 200/503 변별(양방향) + required 정책 + error 타입명.
# ──────────────────────────────────────────────────────────────────────────
class TestReadiness:
    def test_all_ok_is_200_ready(self) -> None:
        """모든 컴포넌트 도달 ⇒ 200·ready=True·alerts=[](트래픽 0이라 위반 없음)."""
        app, _ = _build_app()
        resp = TestClient(app).get("/health/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready"] is True
        assert body["alerts"] == []
        assert body["components"][COMPONENT_DATABASE]["required"] is True
        assert body["components"][COMPONENT_REDIS]["required"] is False
        assert body["components"][COMPONENT_LLM_ROUTER]["required"] is False
        assert body["components"][COMPONENT_DATABASE]["error"] is None

    def test_db_down_is_503_with_exception_type_name(self) -> None:
        """DB 도달 실패 ⇒ 503 + body error에 예외 **타입명**(실 check_database 경유).

        가짜 probes가 아니라 *실물* check_database에 폭발 엔진을 물려 전체 경로를
        변별한다 — 성공 케이스(위)에서 error=None이므로 이 단언은 변별력이 있다.
        """

        class _FailingConn:
            async def __aenter__(self) -> object:
                raise _BoomError("도달 실패(주입)")

            async def __aexit__(self, *args: object) -> None:
                return None

        class _FailingEngine:
            def connect(self) -> _FailingConn:
                return _FailingConn()

        async def _db() -> ComponentCheck:
            return await check_database(engine=_FailingEngine())  # type: ignore[arg-type]

        probes = _probes()
        probes.database = _db
        app, _ = _build_app(probes=probes)
        resp = TestClient(app).get("/health/ready")
        # 업타임 프로브가 HTTP 상태만으로 판정한다(항상 200 보고형 /status와 대비).
        assert resp.status_code == 503
        body = resp.json()
        assert body["ready"] is False
        assert body["components"][COMPONENT_DATABASE]["reachable"] is False
        assert body["components"][COMPONENT_DATABASE]["error"] == "_BoomError"

    def test_redis_and_llm_down_still_ready_200(self) -> None:
        """Redis·LLM 다운은 *보고만*(required=false) — DB 도달이면 여전히 200/ready."""
        app, _ = _build_app(
            probes=_probes(
                redis=_down_check(COMPONENT_REDIS, required=False),
                llm=_down_check(COMPONENT_LLM_ROUTER, required=False),
            )
        )
        resp = TestClient(app).get("/health/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready"] is True
        assert body["components"][COMPONENT_REDIS]["reachable"] is False
        assert body["components"][COMPONENT_LLM_ROUTER]["reachable"] is False

    def test_alerts_surface_in_body(self) -> None:
        """임계 초과 시 body.alerts 상시 노출 — SaaS(Langfuse) 없이 읽는 인프로세스 축.

        주입 metrics에 5xx를 채워 창 에러율 1.0 > 기본 임계 0.05를 만든다.
        """
        metrics = ServiceMetrics()
        for _ in range(10):
            metrics.record(50.0, 500)
        app, _ = _build_app(metrics=metrics)
        resp = TestClient(app).get("/health/ready")
        assert resp.status_code == 200  # 알림은 ready 게이트가 아니다(보고 축)
        body = resp.json()
        assert any(alert["metric"] == "error_rate" for alert in body["alerts"])
        assert body["metrics"]["total_requests"] == 10
        assert body["metrics"]["total_5xx"] == 10
        assert body["metrics"]["window_error_rate"] == 1.0

    def test_no_traffic_metrics_report_unknown(self) -> None:
        """트래픽 0이면 창 지표는 null('미측정') — 0으로 위장하지 않는다(None-vs-0)."""
        app, _ = _build_app()
        body = TestClient(app).get("/health/ready").json()
        assert body["metrics"]["window_error_rate"] is None
        assert body["metrics"]["window_p95_latency_ms"] is None
        assert body["metrics"]["latency_max_ms"] is None


# ──────────────────────────────────────────────────────────────────────────
# 요청 계측 미들웨어 — 기록·제외 경로·5xx 회계·계측 실패 회귀.
# ──────────────────────────────────────────────────────────────────────────
class TestMetricsMiddleware:
    def test_requests_are_recorded(self) -> None:
        """일반 API 요청(2xx)이 계측된다 — 지연·표본 수 누적."""
        app, metrics = _build_app()
        client = TestClient(app)
        assert client.get("/v1/jobs/j1").status_code == 200
        assert client.get("/v1/jobs/j2").status_code == 200
        snapshot = metrics.snapshot()
        assert snapshot.total_requests == 2
        assert snapshot.window_count == 2
        assert snapshot.total_5xx == 0
        assert snapshot.latency_max_ms is not None and snapshot.latency_max_ms >= 0.0

    def test_ops_probe_paths_are_excluded(self) -> None:
        """/health·/health/live·/health/ready·/status는 계측 제외 — 프로브 자기오염 방지."""
        app, metrics = _build_app()
        client = TestClient(app)
        client.get("/health")
        client.get("/health/live")
        client.get("/health/ready")
        client.get("/status")
        assert metrics.snapshot().total_requests == 0

    def test_unhandled_exception_counts_as_5xx_and_reraises(self) -> None:
        """핸들러 미처리 예외 ⇒ 500 응답 + 5xx 회계(계측이 예외를 삼키지 않음)."""
        app, metrics = _build_app()

        @app.get("/boom")
        async def boom() -> None:  # pragma: no cover — 예외 경로 자체가 목적
            raise _BoomError("핸들러 폭발(주입)")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/boom")
        assert resp.status_code == 500
        snapshot = metrics.snapshot()
        assert snapshot.total_requests == 1
        assert snapshot.total_5xx == 1
        assert snapshot.window_error_rate == 1.0

    def test_instrumentation_failure_never_breaks_request(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """계측 내부 예외 주입 ⇒ 요청 정상 응답 + 로그에 예외 **타입명**(침묵 실패 금지 동결).

        record가 폭발하는 metrics를 주입한다 — 요청이 200으로 살아남고, warning 로그에
        커스텀 예외 타입명(_InstrumentBoomError)이 남아야 한다(무타입 경고 금지 —
        langfuse 8일 무증상 전멸 재발 방지 회귀).
        """

        class _InstrumentBoomError(Exception):
            pass

        class _BrokenMetrics(ServiceMetrics):
            def record(self, latency_ms: float, status_code: int) -> None:
                raise _InstrumentBoomError("계측 폭발(주입)")

        app, _ = _build_app(metrics=_BrokenMetrics())
        client = TestClient(app)
        with caplog.at_level(logging.WARNING, logger="whymath_backend.app"):
            resp = client.get("/v1/jobs/j1")
        assert resp.status_code == 200  # 계측 실패가 요청을 깨지 않는다
        assert "_InstrumentBoomError" in caplog.text  # 예외 타입명 로그(침묵 실패 금지)
