"""S20A 2일째 특성화 — 옛 OpenAI 호환 공용부와 골든 복사본(`golden.llm`)이 같은 입력에 같은 출력을 낸다.

대상(옛 → 골든):
- `l3/providers/_response_fields.read_response_model_id` → `golden/llm/_response_fields.py`
- `l3/providers/_openai_compat`(응답 파싱·Retry-After·전송 재시도) → `golden/llm/_openai_compat.py`
- `l3/providers/seat_failure`(실패 분류) → `golden/llm/seat_failure.py`

맞는지는 묻지 않는다 — 서로 같은지만 본다. 예외는 클래스가 서로 다른 복사본이므로
(클래스 이름 · 메시지 · 상태코드)로 비교한다. 네트워크는 쓰지 않는다(httpx MockTransport).
옛 모듈은 이 테스트에서만 import한다(골든 패키지는 import하지 않는다 — test_import_budget.py).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import golden.llm._openai_compat as golden_compat
import golden.llm._response_fields as golden_fields
import golden.llm.seat_failure as golden_seat
import httpx
import pytest

import whymath_backend.l3.providers._openai_compat as legacy_compat
import whymath_backend.l3.providers._response_fields as legacy_fields
import whymath_backend.l3.providers.seat_failure as legacy_seat

# 진짜 httpx 클라이언트 — 시나리오마다 가짜로 바꿔 끼울 때 가짜가 가짜를 감싸지 않게 한 번만 잡는다
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _outcome(call: Callable[[], Any]) -> tuple[Any, ...]:
    """값 또는 (예외 클래스 이름, 메시지, 상태코드)."""
    try:
        return ("ok", call())
    except Exception as exc:  # noqa: BLE001 — 예외도 출력의 일부로 비교한다
        return ("err", type(exc).__name__, str(exc), getattr(exc, "status_code", None))


def _ok(model: str = "deepseek/x", text: Any = "안녕") -> dict[str, Any]:
    return {
        "model": model,
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7},
    }


# 응답 payload 10개 — 정상·빈 값·모양이 깨진 것
_PAYLOADS: list[Any] = [
    _ok(),
    _ok(model="  "),
    _ok(text=""),
    _ok(text=None),
    {"model": 3, "choices": [], "usage": None},
    {"choices": [{"message": {"content": [{"type": "text", "text": "조각"}]}}]},
    {"choices": [{"message": {}}], "usage": {"prompt_tokens": "9", "completion_tokens": -1}},
    {"choices": "깨짐"},
    None,
    {"model": "m", "choices": [{"message": {"content": "x"}}], "usage": {"prompt_tokens": 1.5}},
]


@pytest.mark.parametrize("payload", _PAYLOADS)
def test_response_parsing_matches_legacy(payload: Any) -> None:
    assert _outcome(lambda: golden_fields.read_response_model_id(payload)) == _outcome(
        lambda: legacy_fields.read_response_model_id(payload)
    )
    assert _outcome(lambda: golden_compat.extract_text(payload)) == _outcome(
        lambda: legacy_compat.extract_text(payload)
    )
    assert _outcome(lambda: golden_compat.extract_usage(payload, 12.5, retries=2)) == _outcome(
        lambda: legacy_compat.extract_usage(payload, 12.5, retries=2)
    )


_RETRY_AFTER = [
    None,
    "",
    "5",
    "0",
    "-3",
    "2.5",
    "abc",
    "Wed, 21 Oct 2026 07:28:00 GMT",
    " 7 ",
    "1e3",
]


@pytest.mark.parametrize("raw", _RETRY_AFTER)
def test_retry_after_parsing_matches_legacy(raw: str | None) -> None:
    assert golden_compat._parse_retry_after(raw) == legacy_compat._parse_retry_after(raw)


# 전송 시나리오 10개 — (응답 상태코드, Retry-After 헤더) 순서
_SCENARIOS: list[list[tuple[int, str | None]]] = [
    [(200, None)],
    [(429, None), (200, None)],
    [(500, None), (502, None), (200, None)],
    [(500, None), (500, None), (500, None)],
    [(400, None)],
    [(401, None)],
    [(429, "5"), (200, None)],
    [(503, "abc"), (200, None)],
    [(429, "100"), (200, None)],
    [(404, None)],
]


def _run_transport(
    module: Any, scenario: list[tuple[int, str | None]], monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, ...]:
    """한 모듈의 HttpxChatTransport를 가짜 HTTP로 돌려 (결과, 대기 시간들, 재시도 수)를 낸다."""
    responses = iter(scenario)
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "body": request.content.decode("utf-8")})
        status, retry_after = next(responses)
        headers = {"retry-after": retry_after} if retry_after is not None else {}
        body = _ok() if status < 400 else {"error": {"message": f"상류 {status}"}}
        return httpx.Response(status, json=body, headers=headers)

    def fake_client(**kwargs: Any) -> httpx.AsyncClient:
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    transport = module.HttpxChatTransport(sleep=record_sleep, jitter=lambda: 0.25)

    async def go() -> tuple[Any, ...]:
        module.reset_retry_count()
        result = await _async_outcome(
            transport.post_chat(
                "https://example.invalid/chat/completions",
                headers={"Authorization": "Bearer fake-key"},  # HTTP 헤더는 ASCII만
                payload={"model": "m", "messages": []},
                timeout_s=3.0,
            )
        )
        return result, tuple(sleeps), module.retries_in_current_call(), tuple(map(str, seen))

    return asyncio.run(go())


async def _async_outcome(coro: Any) -> tuple[Any, ...]:
    try:
        return ("ok", await coro)
    except Exception as exc:  # noqa: BLE001 — 예외도 출력의 일부로 비교한다
        return ("err", type(exc).__name__, str(exc), getattr(exc, "status_code", None))


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_transport_retry_matches_legacy(
    scenario: list[tuple[int, str | None]], monkeypatch: pytest.MonkeyPatch
) -> None:
    golden = _run_transport(golden_compat, scenario, monkeypatch)
    legacy = _run_transport(legacy_compat, scenario, monkeypatch)
    assert golden == legacy


def test_transport_scenarios_are_discriminating(monkeypatch: pytest.MonkeyPatch) -> None:
    # 공허한 일치가 아닌지 — 성공·재시도 뒤 성공·소진 실패·즉시 실패가 모두 나온다
    results = [_run_transport(golden_compat, s, monkeypatch) for s in _SCENARIOS]
    kinds = {r[0][0] for r in results}
    retries = {r[2] for r in results}
    assert kinds == {"ok", "err"} and {0, 1, 2} <= retries
    assert len(_SCENARIOS) == 10 and len(_PAYLOADS) == 10 and len(_RETRY_AFTER) == 10


def _failures(module: Any) -> list[BaseException]:
    """실패 예외 10개 — 같은 모양을 각 모듈의 예외 클래스로 만든다."""
    return [
        module.SeatNotConfiguredError("키 없음"),
        module.SeatHttpError("HTTP 429", status_code=429),
        module.SeatHttpError("HTTP 500", status_code=500),
        module.SeatHttpError("HTTP 503", status_code=503),
        module.SeatHttpError("HTTP 400", status_code=400),
        module.SeatHttpError("HTTP 401", status_code=401),
        asyncio.TimeoutError(),
        TimeoutError("시간 초과"),
        RuntimeError("HTTP 429 문구만 있음"),
        ValueError("모름"),
    ]


def test_seat_failure_classification_matches_legacy() -> None:
    golden = [
        (golden_seat.classify_seat_failure(e), golden_seat.http_status_of(e))
        for e in _failures(golden_seat)
    ]
    legacy = [
        (legacy_seat.classify_seat_failure(e), legacy_seat.http_status_of(e))
        for e in _failures(legacy_seat)
    ]
    assert golden == legacy
    assert len({g[0] for g in golden}) >= 3  # 서로 다른 판정이 실제로 나온다
