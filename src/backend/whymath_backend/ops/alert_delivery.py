"""알림 발송 채널 — 알림의 마지막 1홉 (OPS-30 ①).

배경
----
`AlertLogNotifier`(`ops/service_health.py`)는 임계 위반(breach)을 `logger.warning`으로만 쓴다.
런북(`docs/standards/incident_response_slo.md` §6)이 "로그를 보고 있지 않으면 알림이 아니다"라고
자인한 공백이다. OPS-01의 상태 전이 억제 판정은 정교한데 **그 결과가 사람에게 도달하지 않는다**.

이 모듈은 판정을 새로 만들지 않는다 — `AlertLogNotifier`가 이미 계산한 *상태 전이*(진입·해소)를
`on_transition`으로 받아 웹훅 1종으로 내보낼 뿐이다(판정 로직 신설 0).

설계 결정
---------
- **채널은 웹훅 1종**(Slack Incoming Webhook 형식 `{"text": ...}` — Discord는 URL 끝 `/slack`).
  푸시·메일·PagerDuty 다중화는 과공학이라 만들지 않는다.
- **요청 경로를 막지 않는다** — `notify`는 asyncio 이벤트 루프에서 동기 호출되므로, POST는 별도
  데몬 스레드에서 한다. 전이는 드문 사건(지속 위반은 억제됨)이라 스레드 비용은 무시할 수 있다.
- **침묵 실패 금지** — 발송 실패는 삼키되 예외 *타입명*을 로그·카운터에 남긴다(값·URL은 제외 —
  URL 자체가 인증 토큰이다). 성공/실패/미설정 드롭을 서로 다른 카운터로 센다.
- **미설정은 정직하게 드러낸다** — URL이 비면 `config_state="unset"`이고 전이마다
  `dropped_unconfigured`가 오른다. "알릴 곳이 없어 아무도 못 받았다"가 "알림이 없었다"로
  위장되지 않는다(`/health/ready` `alert_delivery`가 노출 — langfuse v2 8일 무증상 전멸 교훈).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import httpx

if TYPE_CHECKING:  # 무거운 import 회피 — Alert는 덕 타이핑(metric·observed·threshold)으로만 쓴다.
    from whymath_backend.ops.service_health import Alert

__all__ = [
    "CONFIG_CONFIGURED",
    "CONFIG_INVALID",
    "CONFIG_UNSET",
    "DeliverySnapshot",
    "WebhookAlertSink",
    "classify_webhook_url",
    "format_transition_text",
    "send_webhook",
]

logger = logging.getLogger(__name__)

CONFIG_CONFIGURED: Final = "configured"
CONFIG_UNSET: Final = "unset"
CONFIG_INVALID: Final = "invalid"

_ALLOWED_SCHEMES: Final = ("https://", "http://")

# 메시지 접두 — 수신 채널에서 어느 서비스의 알림인지 한눈에 보이게 한다(값·시크릿 없음).
_MESSAGE_PREFIX: Final = "[WhyMath]"


def classify_webhook_url(url: str) -> str:
    """URL 설정 상태 — 빈 값=unset, http(s) 시작=configured, 그 외=invalid(오타·붙여넣기 사고)."""
    stripped = url.strip()
    if not stripped:
        return CONFIG_UNSET
    if stripped.lower().startswith(_ALLOWED_SCHEMES):
        return CONFIG_CONFIGURED
    return CONFIG_INVALID


def send_webhook(url: str, text: str, *, timeout_s: float) -> str | None:
    """웹훅 1회 POST — 성공이면 None, 실패면 **오류 라벨**(예외 타입명·`HTTP<코드>`)을 돌려준다.

    예외를 던지지 않는다(비크래시 계약). 라벨에는 URL·응답 본문을 싣지 않는다 — URL이 토큰이다.
    타임아웃은 항상 건다(멈춘 소켓이 호출자를 영구 점유하지 않게).
    """
    try:
        response = httpx.post(url, json={"text": text}, timeout=timeout_s)
    except Exception as exc:  # noqa: BLE001 — 발송 실패 흡수(요청 보호)·타입명 반환 필수
        return type(exc).__name__
    if not 200 <= response.status_code < 300:
        return f"HTTP{response.status_code}"
    return None


def format_transition_text(entered: Sequence[Alert], cleared: Sequence[str]) -> str:
    """상태 전이 → 사람이 읽는 한 덩어리 메시지. metric·실측치·임계만 싣는다(시크릿·필드값 없음)."""
    lines: list[str] = []
    for alert in entered:
        lines.append(
            f"{_MESSAGE_PREFIX} 알림 진입 — {alert.metric}: "
            f"실측 {alert.observed:.4g} > 임계 {alert.threshold:.4g}"
        )
    lines.extend(f"{_MESSAGE_PREFIX} 알림 해소 — {metric}" for metric in cleared)
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class DeliverySnapshot:
    """발송 채널 상태 스냅샷 — /health/ready `alert_delivery`의 원천."""

    config_state: str
    attempted: int
    delivered: int
    failed: int
    dropped_unconfigured: int
    last_error: str | None


class WebhookAlertSink:
    """상태 전이를 웹훅으로 내보내는 sink — `AlertLogNotifier(sinks=[...])`에 주입한다.

    `sender`·`spawn`은 테스트 주입점이다(기본: 실제 `send_webhook` + 데몬 스레드).
    """

    def __init__(
        self,
        url: str,
        *,
        timeout_s: float = 5.0,
        sender: Callable[[str, str], str | None] | None = None,
        spawn: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._url = url.strip()
        self._config_state = classify_webhook_url(url)
        self._timeout_s = timeout_s
        self._sender = sender if sender is not None else self._default_sender
        self._spawn = spawn if spawn is not None else self._spawn_thread
        # 카운터는 요청 스레드(증가)와 발송 스레드(증가)·조회(HTTP 핸들러)가 함께 만진다 → 락.
        self._lock = threading.Lock()
        self._attempted = 0
        self._delivered = 0
        self._failed = 0
        self._dropped_unconfigured = 0
        self._last_error: str | None = None

    @property
    def config_state(self) -> str:
        return self._config_state

    @property
    def configured(self) -> bool:
        return self._config_state == CONFIG_CONFIGURED

    def _default_sender(self, url: str, text: str) -> str | None:
        return send_webhook(url, text, timeout_s=self._timeout_s)

    @staticmethod
    def _spawn_thread(job: Callable[[], None]) -> None:
        # 데몬 스레드 — 종료 시 발송 대기로 프로세스가 매달리지 않는다(알림은 best-effort 1회).
        threading.Thread(target=job, name="alert-webhook", daemon=True).start()

    def on_transition(self, entered: Sequence[Alert], cleared: Sequence[str]) -> None:
        """진입·해소가 하나라도 있을 때 호출된다(AlertLogNotifier가 전이만 넘긴다)."""
        if not entered and not cleared:
            return
        if not self.configured:
            # 채널이 없어 아무에게도 못 알렸다 — 사실을 센다(로그만이 아니라 /health/ready로 노출).
            with self._lock:
                self._dropped_unconfigured += 1
            return
        text = format_transition_text(entered, cleared)
        with self._lock:
            self._attempted += 1
        self._spawn(lambda: self._deliver(text))

    def _deliver(self, text: str) -> None:
        error = self._sender(self._url, text)
        with self._lock:
            if error is None:
                self._delivered += 1
                return
            self._failed += 1
            self._last_error = error
        # 침묵 실패 금지 — 타입명/상태코드만 남긴다(URL·본문 제외).
        logger.warning("알림 웹훅 발송 실패 — 사유: %s", error)

    def snapshot(self) -> DeliverySnapshot:
        with self._lock:
            return DeliverySnapshot(
                config_state=self._config_state,
                attempted=self._attempted,
                delivered=self._delivered,
                failed=self._failed,
                dropped_unconfigured=self._dropped_unconfigured,
                last_error=self._last_error,
            )
