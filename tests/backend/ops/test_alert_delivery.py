"""알림 발송 채널 단위테스트 — hermetic(네트워크 0)·OPS-30 ①.

동결하는 것
-----------
1. **전이 판정은 한 곳** — sink는 `AlertLogNotifier`가 계산한 전이(진입·해소)만 받는다. 지속 위반은
   웹훅 1건이고 해소는 별도 1건이다(스팸 방지가 로그 경로와 동일하게 웹훅에도 적용).
2. **미설정은 위장되지 않는다** — URL 없음/형식 오류는 발송 0건이되 `dropped_unconfigured`가 오르고
   `config_state`가 그 이유를 말한다(무증상 no-op 금지).
3. **침묵 실패 금지** — 발송 실패는 예외 타입명/HTTP 코드로 카운터·로그에 남고, URL(=토큰)은 어디에도
   실리지 않는다.
4. **요청 경로 보호** — sink 예외가 `notify`를 깨지 않는다. 기본 발송은 호출 스레드가 아닌 별도 스레드다.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence

import httpx
import pytest

from whymath_backend.ops import alert_delivery as ad
from whymath_backend.ops import service_health as sh

_URL = "https://hooks.example.test/services/T000/B000/SECRETTOKEN"


def _inline(job: Callable[[], None]) -> None:
    """spawn 대역 — 스레드 없이 즉시 실행(결정적 검증)."""
    job()


class _Recorder:
    """sender 대역 — 호출을 기록하고 지정한 결과(None=성공/오류 라벨)를 돌려준다."""

    def __init__(self, result: str | None = None) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def __call__(self, url: str, text: str) -> str | None:
        self.calls.append((url, text))
        return self.result


def _alert(metric: str = "error_rate", observed: float = 0.5, threshold: float = 0.05) -> sh.Alert:
    return sh.Alert(metric=metric, observed=observed, threshold=threshold)


# ── URL 분류 ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("", ad.CONFIG_UNSET),
        ("   ", ad.CONFIG_UNSET),
        (_URL, ad.CONFIG_CONFIGURED),
        ("http://127.0.0.1:18081/hook", ad.CONFIG_CONFIGURED),
        ("HTTPS://hooks.example.test/x", ad.CONFIG_CONFIGURED),
        ("hooks.example.test/x", ad.CONFIG_INVALID),
        ("ftp://hooks.example.test/x", ad.CONFIG_INVALID),
        ("여기에_실제_URL", ad.CONFIG_INVALID),
    ],
)
def test_classify_webhook_url(url: str, expected: str) -> None:
    assert ad.classify_webhook_url(url) == expected


# ── 메시지 ─────────────────────────────────────────────────────────────────
def test_format_text_carries_metric_observed_threshold_and_cleared() -> None:
    text = ad.format_transition_text([_alert(observed=0.5, threshold=0.05)], ["latency_p95_ms"])
    lines = text.split("\n")
    assert lines[0] == "[WhyMath] 알림 진입 — error_rate: 실측 0.5 > 임계 0.05"
    assert lines[1] == "[WhyMath] 알림 해소 — latency_p95_ms"


# ── send_webhook: 성공/실패 양방향 ──────────────────────────────────────────
def test_send_webhook_success_returns_none_and_posts_slack_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_post(url: str, *, json: object, timeout: float) -> httpx.Response:
        seen.update(url=url, json=json, timeout=timeout)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "post", fake_post)
    assert ad.send_webhook(_URL, "안녕", timeout_s=3.0) is None
    assert seen == {"url": _URL, "json": {"text": "안녕"}, "timeout": 3.0}


@pytest.mark.parametrize("code", [400, 403, 404, 429, 500, 503])
def test_send_webhook_non_2xx_is_failure_label(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(code))
    assert ad.send_webhook(_URL, "x", timeout_s=1.0) == f"HTTP{code}"


def test_send_webhook_exception_returns_type_name_without_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError(f"연결 실패 {_URL}")  # 메시지에 URL이 섞여도 라벨엔 안 실린다

    monkeypatch.setattr(httpx, "post", boom)
    label = ad.send_webhook(_URL, "x", timeout_s=1.0)
    assert label == "ConnectError"
    assert "SECRETTOKEN" not in (label or "")


# ── WebhookAlertSink ───────────────────────────────────────────────────────
def test_sink_sends_once_per_transition_and_counts_delivery() -> None:
    rec = _Recorder()
    sink = ad.WebhookAlertSink(_URL, sender=rec, spawn=_inline)
    sink.on_transition([_alert()], [])
    snap = sink.snapshot()
    assert len(rec.calls) == 1
    assert rec.calls[0][0] == _URL
    assert "error_rate" in rec.calls[0][1]
    assert (snap.attempted, snap.delivered, snap.failed, snap.dropped_unconfigured) == (1, 1, 0, 0)
    assert snap.config_state == ad.CONFIG_CONFIGURED
    assert snap.last_error is None


def test_sink_empty_transition_is_noop() -> None:
    rec = _Recorder()
    sink = ad.WebhookAlertSink(_URL, sender=rec, spawn=_inline)
    sink.on_transition([], [])
    assert rec.calls == []
    assert sink.snapshot().attempted == 0


@pytest.mark.parametrize(
    ("url", "state"), [("", ad.CONFIG_UNSET), ("not-a-url", ad.CONFIG_INVALID)]
)
def test_sink_unconfigured_does_not_send_but_counts_the_drop(url: str, state: str) -> None:
    rec = _Recorder()
    sink = ad.WebhookAlertSink(url, sender=rec, spawn=_inline)
    sink.on_transition([_alert()], [])
    sink.on_transition([], ["error_rate"])
    snap = sink.snapshot()
    assert rec.calls == []
    assert snap.config_state == state
    assert sink.configured is False
    assert (snap.attempted, snap.delivered, snap.dropped_unconfigured) == (0, 0, 2)


def test_sink_failure_is_counted_with_label_and_logged_without_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = ad.WebhookAlertSink(_URL, sender=_Recorder("ConnectError"), spawn=_inline)
    with caplog.at_level(logging.WARNING, logger=ad.logger.name):
        sink.on_transition([_alert()], [])
    snap = sink.snapshot()
    assert (snap.attempted, snap.delivered, snap.failed) == (1, 0, 1)
    assert snap.last_error == "ConnectError"
    assert "ConnectError" in caplog.text
    assert "SECRETTOKEN" not in caplog.text


def test_sink_failure_then_success_keeps_counters_consistent() -> None:
    rec = _Recorder("HTTP500")
    sink = ad.WebhookAlertSink(_URL, sender=rec, spawn=_inline)
    sink.on_transition([_alert()], [])
    rec.result = None
    sink.on_transition([], ["error_rate"])
    snap = sink.snapshot()
    assert (snap.attempted, snap.delivered, snap.failed) == (2, 1, 1)
    assert snap.last_error == "HTTP500"  # 마지막 실패 사유는 성공으로 지워지지 않는다(증거 보존)


def test_default_spawn_runs_off_the_caller_thread() -> None:
    done = threading.Event()
    seen: list[str] = []

    def sender(url: str, text: str) -> None:
        seen.append(threading.current_thread().name)
        done.set()

    sink = ad.WebhookAlertSink(_URL, sender=sender)
    sink.on_transition([_alert()], [])
    assert done.wait(timeout=5)
    assert seen == ["alert-webhook"]
    assert threading.current_thread().name != "alert-webhook"


# ── AlertLogNotifier 연동: 전이 판정 재사용 ─────────────────────────────────
def _notifier(rec: _Recorder) -> sh.AlertLogNotifier:
    return sh.AlertLogNotifier(sinks=[ad.WebhookAlertSink(_URL, sender=rec, spawn=_inline)])


def test_sustained_breach_sends_one_message_then_recovery_sends_another() -> None:
    rec = _Recorder()
    notifier = _notifier(rec)
    for _ in range(5):  # 같은 위반이 5번 평가돼도 진입은 1번
        notifier.notify([_alert()])
    assert len(rec.calls) == 1
    notifier.notify([])  # 해소
    assert len(rec.calls) == 2
    assert "해소" in rec.calls[1][1]
    notifier.notify([])  # 해소 후 평온 — 조용
    assert len(rec.calls) == 2


def test_new_metric_entering_while_other_persists_sends_only_the_new_one() -> None:
    rec = _Recorder()
    notifier = _notifier(rec)
    notifier.notify([_alert("error_rate")])
    notifier.notify([_alert("error_rate"), _alert("latency_p95_ms", 7000, 5000)])
    assert len(rec.calls) == 2
    assert "latency_p95_ms" in rec.calls[1][1]
    assert "error_rate" not in rec.calls[1][1]


def test_quiet_when_no_breach_at_all() -> None:
    rec = _Recorder()
    notifier = _notifier(rec)
    for _ in range(3):
        notifier.notify([])
    assert rec.calls == []


class _ExplodingSink:
    def on_transition(self, entered: Sequence[sh.Alert], cleared: Sequence[str]) -> None:
        raise RuntimeError("sink 폭발(주입)")


def test_exploding_sink_does_not_break_notify_or_other_sinks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rec = _Recorder()
    notifier = sh.AlertLogNotifier(
        sinks=[_ExplodingSink(), ad.WebhookAlertSink(_URL, sender=rec, spawn=_inline)]
    )
    with caplog.at_level(logging.WARNING):
        notifier.notify([_alert()])
    assert len(rec.calls) == 1  # 뒤 sink는 여전히 받는다
    assert "RuntimeError" in caplog.text  # 침묵 실패 금지: 타입명이 남는다
    assert "서비스 알림 breach 진입" in caplog.text  # 로그 경로도 정상


def test_notifier_without_sinks_behaves_as_before(caplog: pytest.LogCaptureFixture) -> None:
    notifier = sh.AlertLogNotifier()
    with caplog.at_level(logging.INFO):
        notifier.notify([_alert()])
        notifier.notify([])
    assert "breach 진입" in caplog.text
    assert "알림 해소" in caplog.text
