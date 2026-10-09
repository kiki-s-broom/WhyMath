"""알림 발송 채널 앱 배선 테스트 — OPS-30 ① (hermetic·네트워크 0).

`create_app()` 안에서 웹훅 sink가 실제로 `AlertLogNotifier`에 물려 있고, 그 상태가
`/health/ready`의 `alert_delivery`로 노출되는지 동결한다("정본화"가 아니라 "집행 지점"의 검증).

- 설정됨: 미들웨어가 5xx로 breach를 만들면 웹훅 POST가 실제로 나간다(전이당 1건).
- 미설정: 발송 0건이되 `config_state="unset"`·`dropped_unconfigured`가 그 사실을 말한다.
- 기동 시 미설정 경고가 로그에 남는다(무증상 no-op 금지) — URL은 로그에 실리지 않는다.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from whymath_backend.app import create_app
from whymath_backend.config import get_settings
from whymath_backend.ops.service_health import ComponentCheck, ReadinessProbes

_HOOK = "https://hooks.example.test/services/T000/B000/SECRETTOKEN"


async def _db() -> ComponentCheck:
    return ComponentCheck("database", True, True, True, None)


async def _redis() -> ComponentCheck:
    return ComponentCheck("redis", False, None, False, None)


async def _llm() -> ComponentCheck:
    return ComponentCheck("llm_router", False, None, False, None)


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()  # 이 파일의 setenv가 타 테스트로 새지 않게


def _client() -> TestClient:
    app = create_app(readiness_probes=ReadinessProbes(database=_db, redis=_redis, llm=_llm))

    @app.get("/boom")
    async def boom() -> None:  # 5xx를 만들어 에러율 breach를 일으킨다
        raise RuntimeError("의도적 500")

    return TestClient(app, raise_server_exceptions=False)


def _delivery(client: TestClient) -> dict[str, Any]:
    body = client.get("/health/ready").json()
    return body["alert_delivery"]  # type: ignore[no-any-return]


def test_configured_breach_posts_to_webhook_once_per_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WHYMATH_OPS_ALERT_WEBHOOK_URL", _HOOK)
    get_settings.cache_clear()
    posted: list[tuple[str, Any]] = []
    done = threading.Event()

    def fake_post(url: str, *, json: Any, timeout: float) -> httpx.Response:
        posted.append((url, json))
        done.set()
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client()
    for _ in range(3):  # breach 지속 — 요청이 3번이어도 전이는 1번
        assert client.get("/boom").status_code == 500
    assert done.wait(timeout=5)

    assert len(posted) == 1
    url, payload = posted[0]
    assert url == _HOOK
    assert "error_rate" in payload["text"]
    # 비동기 발송이 끝나 카운터에 반영될 때까지 짧게 대기(스레드 경쟁 배제).
    for _ in range(50):
        snap = _delivery(client)
        if snap["delivered"] == 1:
            break
        threading.Event().wait(0.05)
    assert snap["config_state"] == "configured"
    assert (snap["attempted"], snap["delivered"], snap["failed"]) == (1, 1, 0)
    assert snap["dropped_unconfigured"] == 0
    assert "SECRETTOKEN" not in str(snap)  # URL(토큰)은 응답에 노출되지 않는다


def test_unset_channel_sends_nothing_but_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WHYMATH_OPS_ALERT_WEBHOOK_URL", raising=False)
    get_settings.cache_clear()

    def forbidden_post(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("미설정인데 웹훅 POST가 나갔다")

    monkeypatch.setattr(httpx, "post", forbidden_post)
    client = _client()
    for _ in range(3):
        client.get("/boom")
    snap = _delivery(client)
    assert snap["config_state"] == "unset"
    assert (snap["attempted"], snap["delivered"]) == (0, 0)
    assert snap["dropped_unconfigured"] == 1  # breach는 났고, 알릴 곳이 없었다는 사실이 남는다


def test_startup_warns_when_channel_unset_without_leaking_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("WHYMATH_OPS_ALERT_WEBHOOK_URL", raising=False)
    get_settings.cache_clear()
    with caplog.at_level(logging.WARNING):
        _client()
    assert "알림 발송 채널 미설정" in caplog.text


def test_startup_warns_on_invalid_url_and_does_not_log_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("WHYMATH_OPS_ALERT_WEBHOOK_URL", "SECRETTOKEN-not-a-url")
    get_settings.cache_clear()
    with caplog.at_level(logging.WARNING):
        client = _client()
    assert "형식 오류" in caplog.text
    assert "SECRETTOKEN" not in caplog.text
    assert _delivery(client)["config_state"] == "invalid"


def test_no_startup_warning_when_channel_is_configured(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("WHYMATH_OPS_ALERT_WEBHOOK_URL", _HOOK)
    get_settings.cache_clear()
    with caplog.at_level(logging.WARNING):
        _client()
    assert "알림 발송 채널" not in caplog.text
