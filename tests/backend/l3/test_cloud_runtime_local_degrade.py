"""ARCH-69 — 클라우드 1차 좌석 실패 시 **런타임 LOCAL 강등**의 동작 계약 (hermetic · 네트워크 0 · 라이브 LLM 0).

ARCH-64가 학생 대면 서빙을 OpenRouter 좌석으로 컷오버하면서, 클라우드로 나간 호출이 실패하면 예외가
그대로 올라가 `/v1/generate`가 500이 되는 상태가 실측됐다("기존 LOCAL 강등 경로"라는 ARCH-63·64의
전제가 코드에 없었다 — LOCAL 강등은 라우팅 시점에만 있었다). 이 파일은 그 경로를 **실제로 도는 코드**로
잰다. 가짜 HTTP 전송·가짜 LOCAL 제공자만 쓰므로 어떤 LLM·네트워크에도 닿지 않는다.

확인하는 것 여섯 가지:

  ① **분류는 타입으로** — 상태코드·타임아웃·미설정을 예외 **타입/속성**으로 판정하고 메시지 문자열은
     읽지 않는다. 실물 httpx·anthropic SDK 예외 클래스로도 판정한다(시임 가짜만으로 정합 선언 금지).
  ② **강등 경로** — 429·5xx·408/타임아웃·미설정 → LOCAL이 1회 대신 답한다(사유 코드·원 좌석·답한 LOCAL 결정).
  ③ **대조군** — 4xx(요청·인증 오류)·계약 오류·관할 게이트 차단은 **강등하지 않고** 원 예외가 그대로 올라온다.
     LOCAL도 실패하면 **원래의 클라우드 예외**가 올라오고 LOCAL 실패가 note에 남는다(삼키지 않는다).
  ④ **검증 계약 불변** — 강등된 응답도 파이프라인의 검증을 똑같이 탄다. 강등 응답은 캐시(클라우드 키)에
     저장되지 않아, 캐시 적중 경로로 검증을 건너뛰어 나가지도 않는다.
  ⑤ **정직성** — 원가는 실제로 답한 LOCAL(0원)로, trace·Langfuse·응답에 강등 사실이 실린다. 작동 신호
     `seat_local_degrade_rate`는 분모 0이면 None이고 강등 미장착 조립에서도 None이다. "2차 클라우드 좌석
     없음"은 그대로다.
  ⑥ **집행 지점** — 강등을 켜는 곳은 학생 대면 서빙(`app.py`)뿐이다(AST로 동결) — 저작·측정 조립은 실패가
     실패로 남는다.
"""

from __future__ import annotations

import ast
import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import whymath_backend
from whymath_backend.api._auth import get_current_user
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.harness.anchor_round_ledger import SeatTally, seat_operating_rates
from whymath_backend.l3 import pipeline
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.interfaces import InMemoryCache, RecordingTraceSink
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    RoutingDecision,
    RoutingRequest,
    Usage,
)
from whymath_backend.l3.pregenerate.models import PregenItem, ValidationSignal
from whymath_backend.l3.pregenerate.validator import default_seed_validator
from whymath_backend.l3.providers import openrouter as openrouter_module
from whymath_backend.l3.providers._openai_compat import HttpxChatTransport
from whymath_backend.l3.providers.composite import (
    CLOUD_FAILOVER_SEAT,
    CompositeProvider,
    no_secondary_seat_note,
)
from whymath_backend.l3.providers.ollama import OllamaProvider, OllamaStatus
from whymath_backend.l3.providers.openrouter import OpenRouterProvider
from whymath_backend.l3.providers.seat_failure import (
    DEGRADE_REASONS,
    LocalDegradeCounter,
    LocalDegradeSnapshot,
    SeatHttpError,
    SeatNotConfiguredError,
    classify_seat_failure,
    seat_local_degrade_rate,
)
from whymath_backend.l3.router import CLOUD_TOKEN_PRICE_USD_PER_1M, USD_TO_KRW

_PACKAGE_ROOT = Path(whymath_backend.__file__).parent

_IN_TOKENS = 1000
_OUT_TOKENS = 1000
_LOCAL_TEXT = "로컬 강등 응답"
_CLOUD_TEXT = "클라우드 응답"
_FAKE_USER = UserProfile(user_id=uuid.uuid4())


# ===========================================================================
# 대역 — 가짜 전송·가짜 LOCAL·가짜 클라우드 좌석 조립
# ===========================================================================
def _ok_response(text: str = _CLOUD_TEXT) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": _IN_TOKENS, "completion_tokens": _OUT_TOKENS},
    }


class _ScriptedTransport:
    """`ChatTransport` 대역 — 호출을 기록하고 정해진 결과(응답 dict 또는 raise할 예외)를 낸다."""

    def __init__(self, outcome: Exception | dict[str, Any]) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def post_chat(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_s: float,
    ) -> Any:
        self.calls.append({"url": url, "payload": dict(payload)})
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _FakeLocal:
    """LOCAL 제공자 대역 — 어떤 결정으로 불렸는지 기록하고, 응답하거나 실패한다."""

    def __init__(
        self, *, text: str = _LOCAL_TEXT, fail_with: Exception | None = None, tokens: int = 1000
    ) -> None:
        self._text = text
        self._fail_with = fail_with
        self._tokens = tokens
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision, **kwargs: Any
    ) -> GenerationResult:
        self.calls.append({"prompt": prompt, "decision": decision, "kwargs": dict(kwargs)})
        if self._fail_with is not None:
            raise self._fail_with
        return GenerationResult(
            text=self._text,
            usage=Usage(
                input_tokens=self._tokens,
                output_tokens=self._tokens,
                latency_ms=12.0,
                served_model="qwen2-math:7b",
            ),
        )


def _openrouter(
    transport: _ScriptedTransport | None,
    *,
    key: str = "sk-or-fake-arch69",
    allowed: tuple[str, ...] = ("deepinfra",),
) -> OpenRouterProvider:
    settings = Settings(openrouter_api_key=SecretStr(key), openrouter_allowed_providers=allowed)
    return OpenRouterProvider(transport=transport, settings=settings)


def _composite(
    cloud: OpenRouterProvider, local: _FakeLocal, *, armed: bool = True
) -> CompositeProvider:
    return CompositeProvider(
        local=local,  # type: ignore[arg-type]
        cloud=cloud,
        runtime_local_degrade=armed,
    )


def _cloud_decision(cost: CostTier = CostTier.CLOUD_MID) -> RoutingDecision:
    return RoutingDecision(
        cost_tier=cost,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="arch69",
        est_latency_ms=3000,
        est_cost_krw=0.0,
        data_licenses=SELF_AUTHORED_CORPUS,
    )


def _student_request() -> RoutingRequest:
    """CLOUD_MID로 라우팅되는 학생 요청 — premium·추론 필요·예산 충분·반출 가능 등급."""
    return RoutingRequest(
        task_type="coach",
        difficulty="hard",
        requires_reasoning=True,
        student_subscription="premium",
        budget_krw=1000.0,
        sync=True,
        data_licenses=SELF_AUTHORED_CORPUS,
    )


def _expected_cloud_krw() -> float:
    price_in, price_out = CLOUD_TOKEN_PRICE_USD_PER_1M[(CostTier.CLOUD_MID, "openrouter")]
    return (_IN_TOKENS * price_in + _OUT_TOKENS * price_out) / 1_000_000 * USD_TO_KRW


def _http_error(status: int) -> SeatHttpError:
    return SeatHttpError(f"OpenAI 호환 호출 실패 HTTP {status}: x (시도 3회)", status_code=status)


# ===========================================================================
# ① 분류 — 타입·구조 속성으로 판정한다 (메시지 문자열은 읽지 않는다)
# ===========================================================================
_SDK_REQUEST = httpx.Request("POST", "https://example.invalid/v1/messages")


def _sdk_status_error(cls: type[anthropic.APIStatusError], status: int) -> Exception:
    response = httpx.Response(status, request=_SDK_REQUEST)
    return cls("sdk error", response=response, body=None)


_DEGRADABLE: list[Any] = [
    # 우리 전송기의 타입 예외 — 상태코드는 속성이다.
    pytest.param(lambda: _http_error(429), "rate_limited", id="seat-429"),
    pytest.param(lambda: _http_error(500), "server_error", id="seat-500"),
    pytest.param(lambda: _http_error(502), "server_error", id="seat-502"),
    pytest.param(lambda: _http_error(503), "server_error", id="seat-503"),
    pytest.param(lambda: _http_error(504), "server_error", id="seat-504"),
    pytest.param(lambda: _http_error(599), "server_error", id="seat-599"),
    # 408은 4xx지만 요청 오류가 아니라 시간 초과다.
    pytest.param(lambda: _http_error(408), "timeout", id="seat-408"),
    pytest.param(lambda: SeatNotConfiguredError("키 없음"), "not_configured", id="not-configured"),
    # 타임아웃 — 내장·asyncio·**실물 httpx** 클래스.
    pytest.param(lambda: TimeoutError("t"), "timeout", id="builtin-timeout"),
    pytest.param(lambda: asyncio.TimeoutError(), "timeout", id="asyncio-timeout"),
    pytest.param(lambda: httpx.ReadTimeout("read timed out"), "timeout", id="httpx-read-timeout"),
    pytest.param(
        lambda: httpx.ConnectTimeout("connect timed out"), "timeout", id="httpx-connect-timeout"
    ),
    pytest.param(lambda: httpx.PoolTimeout("pool timed out"), "timeout", id="httpx-pool-timeout"),
    # 실물 anthropic SDK 예외 클래스(구조 속성 `status_code`·타임아웃 타입).
    pytest.param(
        lambda: _sdk_status_error(anthropic.RateLimitError, 429), "rate_limited", id="sdk-429"
    ),
    pytest.param(
        lambda: _sdk_status_error(anthropic.InternalServerError, 500), "server_error", id="sdk-500"
    ),
    pytest.param(
        lambda: anthropic.APITimeoutError(request=_SDK_REQUEST), "timeout", id="sdk-timeout"
    ),
    # 실물 httpx 상태 오류 — 상태코드는 `.response.status_code`에 있다.
    pytest.param(
        lambda: httpx.HTTPStatusError(
            "boom", request=_SDK_REQUEST, response=httpx.Response(503, request=_SDK_REQUEST)
        ),
        "server_error",
        id="httpx-status-503",
    ),
]

# 강등 경로 통합 테스트용 — `not_configured`는 호출 전 실패라 전송기를 거치지 않으므로 따로 잰다.
_DEGRADABLE_DISPATCHED: list[Any] = [
    case for case in _DEGRADABLE if case.values[1] != "not_configured"
]

_NOT_DEGRADABLE: list[Any] = [
    pytest.param(lambda: _http_error(400), id="seat-400"),
    pytest.param(lambda: _http_error(401), id="seat-401"),
    pytest.param(lambda: _http_error(402), id="seat-402"),
    pytest.param(lambda: _http_error(403), id="seat-403"),
    pytest.param(lambda: _http_error(404), id="seat-404"),
    pytest.param(lambda: _http_error(409), id="seat-409"),
    pytest.param(lambda: _http_error(422), id="seat-422"),
    pytest.param(lambda: _sdk_status_error(anthropic.AuthenticationError, 401), id="sdk-401"),
    pytest.param(lambda: _sdk_status_error(anthropic.BadRequestError, 400), id="sdk-400"),
    # **타입 없는** 예외 — 메시지에 429/미설정이 들어 있어도 강등 대상이 아니다(문자열 파싱 금지).
    pytest.param(
        lambda: RuntimeError("OpenAI 호환 호출 실패 HTTP 429: engine_overloaded (시도 3회)"),
        id="untyped-message-says-429",
    ),
    pytest.param(
        lambda: RuntimeError("OpenRouter가 미설정이라 생성을 할 수 없습니다"),
        id="untyped-message-says-unconfigured",
    ),
    pytest.param(lambda: RuntimeError("timeout timed out 타임아웃"), id="untyped-message-timeout"),
    pytest.param(lambda: ValueError("잘못된 인자"), id="value-error"),
    pytest.param(lambda: KeyError("x"), id="key-error"),
    # 사유 코드 밖의 연결 실패 — 이 태스크의 범위는 429·5xx·타임아웃·미설정이다(명시적 한계).
    pytest.param(lambda: httpx.ConnectError("refused"), id="httpx-connect-error"),
]


@pytest.mark.parametrize(("factory", "reason"), _DEGRADABLE)
def test_classifier_maps_failure_types_to_degrade_reasons(
    factory: Callable[[], BaseException], reason: str
) -> None:
    """강등 대상은 정확히 네 사유로 분류된다 — 타입/구조 속성 기반(실물 SDK 클래스 포함)."""
    assert classify_seat_failure(factory()) == reason


@pytest.mark.parametrize("factory", _NOT_DEGRADABLE)
def test_classifier_refuses_everything_else(factory: Callable[[], BaseException]) -> None:
    """대조군 — 4xx·계약 오류·타입 없는 예외·정체불명은 **강등하지 않는다**(None).

    특히 메시지에 "429"·"미설정"·"timeout"이 들어 있는 평범한 `RuntimeError`가 None인 것이 요점이다 —
    이것이 분류가 문자열이 아니라 타입으로 이뤄진다는 증거다(정규식 분류는 여기서 강등한다).
    """
    assert classify_seat_failure(factory()) is None


def test_degrade_reasons_are_exactly_the_four_specified_codes() -> None:
    assert DEGRADE_REASONS == ("rate_limited", "server_error", "timeout", "not_configured")


def test_typed_errors_stay_runtime_errors_with_unchanged_messages() -> None:
    """`SeatHttpError`·`SeatNotConfiguredError`는 RuntimeError 하위라 종전 except·match 계약이 성립한다."""
    err = _http_error(429)
    assert isinstance(err, RuntimeError)
    assert err.status_code == 429
    assert str(err).startswith("OpenAI 호환 호출 실패 HTTP 429")
    assert isinstance(SeatNotConfiguredError("x"), RuntimeError)


async def test_real_transport_raises_status_typed_error_and_classifies_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실물 `HttpxChatTransport` + 실물 httpx(MockTransport) — 상태코드가 **속성**으로 올라온다.

    네트워크 0이다: `httpx.AsyncClient`가 `MockTransport`를 쓰게 끼워 넣었을 뿐 전송기 코드는
    프로덕션 그대로 돈다. 429는 재시도 뒤에 `SeatHttpError(429)`, 401은 재시도 없이 즉시
    `SeatHttpError(401)`이며, 분류기가 각각 rate_limited·None으로 판정한다.
    """
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = int(request.headers["x-test-status"])
        seen.append(status)
        return httpx.Response(status, json={"error": {"message": "boom"}})

    real_client = httpx.AsyncClient

    def client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)

    async def _no_sleep(_: float) -> None:
        return None

    transport = HttpxChatTransport(max_attempts=2, sleep=_no_sleep, jitter=lambda: 0.0)

    with pytest.raises(SeatHttpError) as rate_limited:
        await transport.post_chat(
            "https://example.invalid/chat/completions",
            headers={"x-test-status": "429"},
            payload={},
            timeout_s=1.0,
        )
    assert rate_limited.value.status_code == 429
    assert seen == [429, 429]  # 429는 재시도 대상 — 총 2회 시도
    assert classify_seat_failure(rate_limited.value) == "rate_limited"

    seen.clear()
    with pytest.raises(SeatHttpError) as unauthorized:
        await transport.post_chat(
            "https://example.invalid/chat/completions",
            headers={"x-test-status": "401"},
            payload={},
            timeout_s=1.0,
        )
    assert unauthorized.value.status_code == 401
    assert seen == [401]  # 401은 재시도해도 같다 — 1회로 끝
    assert classify_seat_failure(unauthorized.value) is None


async def test_real_transport_timeout_is_a_timeout_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """실물 httpx 타임아웃 예외는 전송기를 그대로 통과하고 분류기가 `timeout`으로 판정한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    real_client = httpx.AsyncClient

    def client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    transport = HttpxChatTransport(max_attempts=1)
    with pytest.raises(httpx.TimeoutException) as excinfo:
        await transport.post_chat(
            "https://example.invalid/chat/completions", headers={}, payload={}, timeout_s=1.0
        )
    assert classify_seat_failure(excinfo.value) == "timeout"


def test_single_classifier_and_single_rate_definition_in_the_source() -> None:
    """분류 함수와 `seat_local_degrade_rate` 정의는 저장소에 **한 곳**뿐이다(두 번째 정의 금지)."""

    def defs_of(name: str) -> list[str]:
        found: list[str] = []
        for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
                    found.append(path.relative_to(_PACKAGE_ROOT).as_posix())
        return found

    assert defs_of("classify_seat_failure") == ["l3/providers/seat_failure.py"]
    assert defs_of("seat_local_degrade_rate") == ["l3/providers/seat_failure.py"]


# ===========================================================================
# ② 강등 경로 — 429·5xx·타임아웃·미설정이면 LOCAL이 1회 대신 답한다
# ===========================================================================
@pytest.mark.parametrize(("factory", "reason"), _DEGRADABLE_DISPATCHED)
async def test_degradable_failure_is_answered_by_local_once(
    factory: Callable[[], BaseException], reason: str
) -> None:
    original = factory()
    transport = _ScriptedTransport(original)  # type: ignore[arg-type]
    local = _FakeLocal()
    composite = _composite(_openrouter(transport), local)

    result = await composite.generate("질문", "시스템", _cloud_decision())

    assert result.text == _LOCAL_TEXT
    degrade = result.local_degrade
    assert degrade is not None
    assert degrade.reason == reason
    assert degrade.from_seat == "openrouter"
    assert degrade.cloud_error_type == type(original).__name__
    assert degrade.cloud_attempt_ms is not None and degrade.cloud_attempt_ms >= 0.0
    # 클라우드는 1회, LOCAL도 1회 — 재귀·재시도 없음.
    assert len(transport.calls) == 1
    assert len(local.calls) == 1
    served = local.calls[0]["decision"]
    assert served.cost_tier == CostTier.LOCAL.value
    assert served.local_family == "math" and served.local_model == "mid"
    assert served.mode == "sync"
    assert served == degrade.served_decision
    # 데이터 등급은 승계된다(LOCAL은 국내라 게이트가 막을 것이 없다 — blocked는 False).
    assert served.data_licenses == _cloud_decision().data_licenses
    assert served.data_export_blocked is False

    snapshot = composite.local_degrade_snapshot()
    assert snapshot.armed is True
    assert (snapshot.cloud_attempts, snapshot.local_degrades) == (1, 1)
    assert snapshot.local_degrade_failures == 0
    assert snapshot.rate == 1.0
    assert snapshot.by_reason is not None
    assert snapshot.by_reason[reason] == 1
    assert sum(snapshot.by_reason.values()) == 1


async def test_missing_key_degrades_as_not_configured() -> None:
    """키 부재(전송기 미주입 + 빈 키) → 호출이 나가기 전 실패 → `not_configured`로 LOCAL 강등."""
    local = _FakeLocal()
    cloud = _openrouter(None, key="")  # 전송 미주입 + 빈 키 → configured=False
    assert cloud.configured is False
    composite = _composite(cloud, local)

    result = await composite.generate("질문", "시스템", _cloud_decision())

    assert result.text == _LOCAL_TEXT
    assert result.local_degrade is not None
    assert result.local_degrade.reason == "not_configured"
    assert result.local_degrade.cloud_error_type == "SeatNotConfiguredError"
    assert len(local.calls) == 1
    snapshot = composite.local_degrade_snapshot()
    assert (snapshot.cloud_attempts, snapshot.local_degrades) == (1, 1)


async def test_cloud_high_also_degrades_to_the_same_sync_local_target() -> None:
    """CLOUD_HIGH 결정도 같은 대상(MATH/MID·동기)으로 강등된다 — QUALITY(비동기 전용)로 가지 않는다."""
    local = _FakeLocal()
    composite = _composite(_openrouter(_ScriptedTransport(_http_error(503))), local)

    result = await composite.generate("질문", "시스템", _cloud_decision(CostTier.CLOUD_HIGH))

    assert result.local_degrade is not None
    served = local.calls[0]["decision"]
    assert (served.local_family, served.local_model, served.mode) == ("math", "mid", "sync")
    assert "cloud_high" in served.reason


async def test_optional_generation_kwargs_are_forwarded_to_local_unchanged() -> None:
    """temperature·top_p·seed는 삼키지 않고 LOCAL로 그대로 전달된다(조용한 무시 금지)."""
    local = _FakeLocal()
    composite = _composite(_openrouter(_ScriptedTransport(_http_error(429))), local)

    await composite.generate("p", "s", _cloud_decision(), temperature=0.9, top_p=0.95, seed=7)

    assert local.calls[0]["kwargs"] == {"temperature": 0.9, "top_p": 0.95, "seed": 7}


async def test_healthy_cloud_call_never_touches_local_and_counts_no_degrade() -> None:
    """정상 호출 — 강등 0·LOCAL 호출 0. 분모(디스패치)는 1, 강등률은 **0.0**(시도했는데 강등 0회)."""
    transport = _ScriptedTransport(_ok_response())
    local = _FakeLocal()
    composite = _composite(_openrouter(transport), local)

    result = await composite.generate("질문", "시스템", _cloud_decision())

    assert result.text == _CLOUD_TEXT
    assert result.local_degrade is None
    assert local.calls == []
    snapshot = composite.local_degrade_snapshot()
    assert (snapshot.cloud_attempts, snapshot.local_degrades) == (1, 0)
    assert snapshot.rate == 0.0  # 분모 1 — 0.0이 정직하다(분모 0이면 None인 것과 구분)


# ===========================================================================
# ③ 대조군 — 강등하지 않고 원 예외가 그대로 올라온다
# ===========================================================================
@pytest.mark.parametrize("factory", _NOT_DEGRADABLE[:7])
async def test_request_and_auth_errors_are_raised_as_is_without_local(
    factory: Callable[[], BaseException],
) -> None:
    """4xx(400·401·402·403·404·409·422) → 강등 없음. 원 예외 **객체**가 올라오고 LOCAL은 0회."""
    original = factory()
    local = _FakeLocal()
    composite = _composite(_openrouter(_ScriptedTransport(original)), local)  # type: ignore[arg-type]

    with pytest.raises(SeatHttpError) as excinfo:
        await composite.generate("질문", "시스템", _cloud_decision())

    assert excinfo.value is original
    assert local.calls == []
    notes = getattr(excinfo.value, "__notes__", [])
    assert any("강등 대상이 아니" in note for note in notes), notes
    assert any("2차 클라우드 좌석 없음" in note for note in notes), notes
    snapshot = composite.local_degrade_snapshot()
    assert (snapshot.cloud_attempts, snapshot.local_degrades) == (1, 0)
    assert snapshot.rate == 0.0  # 디스패치는 있었고 강등은 없었다


async def test_contract_errors_are_not_degraded() -> None:
    """`images`·`json_schema` 미지원 같은 계약 오류(타입 없는 RuntimeError)는 강등하지 않는다."""
    local = _FakeLocal()
    transport = _ScriptedTransport(_ok_response())
    composite = _composite(_openrouter(transport), local)

    with pytest.raises(RuntimeError, match="멀티모달"):
        await composite.generate("p", "s", _cloud_decision(), images=["aGVsbG8="])
    with pytest.raises(RuntimeError, match="json_schema"):
        await composite.generate("p", "s", _cloud_decision(), json_schema={"type": "object"})

    assert local.calls == []
    assert transport.calls == []


async def test_jurisdiction_gate_block_is_not_degraded_and_not_counted() -> None:
    """관할 게이트 차단은 **설정 오류**다 — LOCAL로 조용히 내리지 않고, 디스패치가 아니므로 분모에도 안 든다."""
    local = _FakeLocal()
    transport = _ScriptedTransport(_ok_response())
    # CN 관할 공급사 + 등급 선언 없는 결정(fail-closed) → 게이트가 위임 직전에 차단한다.
    cloud = _openrouter(transport, allowed=("siliconflow",))
    composite = _composite(cloud, local)
    undeclared = RoutingDecision(
        cost_tier=CostTier.CLOUD_MID,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="gate",
        est_latency_ms=3000,
    )

    with pytest.raises(RuntimeError, match="관할 게이트"):
        await composite.generate("p", "s", undeclared)

    assert local.calls == [] and transport.calls == []
    assert composite.local_degrade_snapshot().cloud_attempts == 0


async def test_local_failure_raises_the_original_cloud_exception_with_a_note() -> None:
    """LOCAL도 실패 → **원래의 클라우드 예외**가 올라온다. LOCAL 실패는 삼키지 않고 note에 남는다."""
    original = _http_error(429)
    local = _FakeLocal(fail_with=ConnectionError("ollama down"))
    composite = _composite(_openrouter(_ScriptedTransport(original)), local)

    with pytest.raises(SeatHttpError) as excinfo:
        await composite.generate("질문", "시스템", _cloud_decision())

    assert excinfo.value is original  # LOCAL 예외가 원인을 덮지 않는다
    assert (
        original.__context__ is None
    )  # 원 예외의 맥락도 오염되지 않는다(inner except 밖에서 raise)
    notes = getattr(excinfo.value, "__notes__", [])
    joined = "\n".join(notes)
    assert "LOCAL도 실패" in joined
    assert "ConnectionError" in joined  # LOCAL 실패의 타입이 적힌다
    assert "rate_limited" in joined  # 어떤 사유로 강등을 시도했는지
    assert "2차 클라우드 좌석 없음" in joined
    assert len(local.calls) == 1  # 강등은 1회 — LOCAL 재시도 없음
    snapshot = composite.local_degrade_snapshot()
    assert (snapshot.cloud_attempts, snapshot.local_degrades) == (1, 1)
    assert snapshot.local_degrade_failures == 1  # 학생은 강등 응답이 아니라 오류를 받았다


async def test_local_failure_is_logged_with_exception_type_names(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """침묵 실패 금지 — 강등 발생과 LOCAL 실패 모두 **예외 타입명**을 로그에 남긴다(본문·시크릿 제외)."""
    local = _FakeLocal(fail_with=ConnectionError("ollama down: sk-secret-should-not-be-logged"))
    composite = _composite(_openrouter(_ScriptedTransport(_http_error(503))), local)

    with caplog.at_level("WARNING", logger="whymath.l3.composite"):
        with pytest.raises(SeatHttpError):
            await composite.generate("질문", "시스템", _cloud_decision())

    text = caplog.text
    assert "LOCAL 강등" in text
    assert "SeatHttpError" in text and "ConnectionError" in text
    assert "server_error" in text
    assert "sk-secret-should-not-be-logged" not in text


# ===========================================================================
# 강등 미장착(저작·측정 조립) — 실패는 실패로 남는다
# ===========================================================================
async def test_unarmed_composite_never_degrades_and_says_so() -> None:
    original = _http_error(429)
    local = _FakeLocal()
    composite = CompositeProvider(
        local=local,  # type: ignore[arg-type]
        cloud=_openrouter(_ScriptedTransport(original)),
    )  # runtime_local_degrade 기본값 = False
    assert composite.local_degrade_armed is False

    with pytest.raises(SeatHttpError) as excinfo:
        await composite.generate("질문", "시스템", _cloud_decision())

    assert excinfo.value is original
    assert local.calls == []
    notes = getattr(excinfo.value, "__notes__", [])
    assert notes == [no_secondary_seat_note("openrouter")]
    assert "장착되지 않아" in notes[0]
    snapshot = composite.local_degrade_snapshot()
    assert snapshot.armed is False
    assert snapshot.cloud_attempts == 0 and snapshot.local_degrades == 0
    assert snapshot.rate is None  # 강등할 수 없는 구성 ≠ 강등 0회


async def test_local_decisions_do_not_touch_the_degrade_counter() -> None:
    """LOCAL 결정 호출은 클라우드 디스패치가 아니다 — 분모에 들어가지 않는다."""
    local = _FakeLocal()
    composite = _composite(_openrouter(_ScriptedTransport(_ok_response())), local)
    local_decision = RoutingDecision(
        cost_tier=CostTier.LOCAL,
        local_family="math",  # type: ignore[arg-type]
        local_model="fast",  # type: ignore[arg-type]
        mode="sync",
        reason="routed-local",
        est_latency_ms=1010,
    )

    result = await composite.generate("p", "s", local_decision)

    assert result.text == _LOCAL_TEXT
    assert result.local_degrade is None  # 라우팅 시점의 LOCAL — 강등이 아니다
    assert composite.local_degrade_snapshot().cloud_attempts == 0


# ===========================================================================
# ④ 검증 계약 불변 — 강등 응답도 같은 검증을 탄다 · 캐시로 검증을 건너뛰지 않는다
# ===========================================================================
_HALLUCINATED = "따라서 3 > 5 이다."
_TRUE_STATEMENT = "따라서 2 < 3 이다."


class _SpyValidator:
    """`SeedValidator` 대역 — 실제 검증기를 감싸 호출 횟수와 입력을 기록한다."""

    def __init__(self) -> None:
        self._inner = default_seed_validator()
        self.responses: list[str] = []

    def validate(self, item: PregenItem | None, response: str) -> ValidationSignal | None:
        self.responses.append(response)
        return self._inner.validate(item, response)


async def _generate_through_pipeline(
    provider: CompositeProvider,
    *,
    cache: InMemoryCache,
    trace: RecordingTraceSink,
    validator: _SpyValidator | None = None,
    skip_cache_on_signal: bool = False,
) -> pipeline.GenerationResult:
    return await pipeline.generate(
        _student_request(),
        "학생 질문",
        "시스템",
        provider=provider,
        cache=cache,
        trace=trace,
        validator=validator,
        skip_cache_on_signal=skip_cache_on_signal,
        cache_ttl_s=60,
    )


@pytest.mark.parametrize(
    ("text", "expect_signal"), [(_HALLUCINATED, True), (_TRUE_STATEMENT, False)]
)
async def test_degraded_response_gets_the_same_validation_as_a_healthy_cloud_response(
    text: str, expect_signal: bool
) -> None:
    """같은 텍스트가 (a) 클라우드 정상 응답 (b) 강등된 LOCAL 응답으로 나올 때 검증 결과가 **같다**.

    검증기는 각 경로에서 정확히 1회 불리고 그 텍스트를 본다 — 강등이 검증을 건너뛰거나(0회), 다른
    입력을 보거나, 결과를 바꾸면 red다. 환각 텍스트(`3 > 5`)는 두 경로 모두 신호를 낸다.
    """
    # (a) 클라우드가 정상 응답
    healthy_spy = _SpyValidator()
    healthy = await _generate_through_pipeline(
        _composite(_openrouter(_ScriptedTransport(_ok_response(text))), _FakeLocal()),
        cache=InMemoryCache(),
        trace=RecordingTraceSink(),
        validator=healthy_spy,
    )
    # (b) 클라우드 429 → LOCAL이 같은 텍스트로 강등 응답
    degraded_spy = _SpyValidator()
    degraded = await _generate_through_pipeline(
        _composite(_openrouter(_ScriptedTransport(_http_error(429))), _FakeLocal(text=text)),
        cache=InMemoryCache(),
        trace=RecordingTraceSink(),
        validator=degraded_spy,
    )

    assert healthy.local_degrade is None and degraded.local_degrade is not None
    assert healthy_spy.responses == [text]
    assert degraded_spy.responses == [text]  # 강등 응답도 검증기를 정확히 1회 탄다
    assert degraded.validation_signal == healthy.validation_signal
    assert (degraded.validation_signal is not None) is expect_signal


async def test_degraded_response_validation_signal_reaches_the_trace() -> None:
    """검증 신호가 강등 응답의 trace 레코드에도 실린다 — 강등이 관측에서 신호를 지우지 않는다."""
    trace = RecordingTraceSink()
    result = await _generate_through_pipeline(
        _composite(
            _openrouter(_ScriptedTransport(_http_error(503))), _FakeLocal(text=_HALLUCINATED)
        ),
        cache=InMemoryCache(),
        trace=trace,
        validator=_SpyValidator(),
    )
    assert result.validation_signal is not None
    assert trace.records[0]["validation_signal"] == result.validation_signal
    assert trace.records[0]["local_degraded"] is True


async def test_degraded_response_is_never_stored_under_the_cloud_cache_key() -> None:
    """강등 응답은 캐시에 적재되지 않는다 — 다음 동일 요청이 LOCAL 텍스트를 클라우드 응답으로 적중시키지 못한다.

    적중 경로는 검증기를 타지 않고(미스 생성물만 검증) 강등 표기도 싣지 못한다. 그래서 강등 응답의
    캐시 저장은 **검증 우회 경로**가 된다. 대조군: 정상 클라우드 응답은 저장되어 다음 호출이 적중한다.
    """
    cache = InMemoryCache()
    degraded_provider = _composite(_openrouter(_ScriptedTransport(_http_error(429))), _FakeLocal())
    first = await _generate_through_pipeline(
        degraded_provider, cache=cache, trace=RecordingTraceSink(), validator=_SpyValidator()
    )
    assert first.local_degrade is not None and first.cache_hit is False

    # 클라우드가 복구된 뒤 같은 요청 — 캐시 미스여야 한다(LOCAL 텍스트가 저장되지 않았다).
    healthy_transport = _ScriptedTransport(_ok_response())
    healthy_provider = _composite(_openrouter(healthy_transport), _FakeLocal())
    second = await _generate_through_pipeline(
        healthy_provider, cache=cache, trace=RecordingTraceSink(), validator=_SpyValidator()
    )
    assert second.cache_hit is False
    assert second.text == _CLOUD_TEXT
    assert len(healthy_transport.calls) == 1  # 클라우드가 실제로 다시 불렸다
    assert second.local_degrade is None

    # 대조군 — 정상 응답은 저장되고, 세 번째 호출은 적중한다.
    third = await _generate_through_pipeline(
        healthy_provider, cache=cache, trace=RecordingTraceSink(), validator=_SpyValidator()
    )
    assert third.cache_hit is True
    assert len(healthy_transport.calls) == 1


# ===========================================================================
# ⑤ 정직성 — 원가·trace·응답·작동 신호
# ===========================================================================
async def test_degraded_call_is_costed_as_local_and_traced_with_reason_and_seat() -> None:
    """원가는 **실제로 답한 좌석(LOCAL=0원)**으로 기록되고, 강등 사실이 trace에 실린다.

    LOCAL 가짜가 1,000/1,000 토큰을 보고한다 — 클라우드 단가(약 0.354원)를 곱했다면 0.0이 아니다.
    """
    trace = RecordingTraceSink()
    await _generate_through_pipeline(
        _composite(_openrouter(_ScriptedTransport(_http_error(429))), _FakeLocal()),
        cache=InMemoryCache(),
        trace=trace,
    )
    record = trace.records[0]
    assert record["cost_krw"] == 0.0
    assert record["cost_krw"] != pytest.approx(_expected_cloud_krw())
    assert record["cloud_seat"] is None  # LOCAL이 답했다 — 클라우드 단가 좌석이 없다
    assert record["local_degraded"] is True
    assert record["degraded_from_seat"] == "openrouter"
    assert record["degrade_reason"] == "rate_limited"
    assert record["degraded_to_local"] == "math/mid"
    assert (
        record["cost_tier"] == CostTier.CLOUD_MID.value
    )  # 라우터의 결정은 그대로 — 어긋남이 드러난다
    assert isinstance(record["degrade_cloud_attempt_ms"], float)
    assert record["input_tokens"] == 1000  # 실측 usage는 LOCAL의 것


async def test_healthy_call_trace_carries_the_degrade_axis_as_false() -> None:
    """정상 호출도 강등 축을 **False로 명시**한다 — 키 부재(축을 모름)와 False(강등 없음)를 가른다."""
    trace = RecordingTraceSink()
    await _generate_through_pipeline(
        _composite(_openrouter(_ScriptedTransport(_ok_response())), _FakeLocal()),
        cache=InMemoryCache(),
        trace=trace,
    )
    record = trace.records[0]
    assert record["local_degraded"] is False
    assert record["degraded_from_seat"] is None
    assert record["degrade_reason"] is None
    assert record["degraded_to_local"] is None
    assert record["cloud_seat"] == "openrouter"
    assert record["cost_krw"] == pytest.approx(_expected_cloud_krw())


async def test_langfuse_sink_tags_only_degraded_calls() -> None:
    """Langfuse 메타데이터에 강등 필드가 그대로 실리고, 강등 사유만 태그로 노출된다."""
    from whymath_backend.l3.trace.langfuse_sink import _to_metadata

    trace = RecordingTraceSink()
    await _generate_through_pipeline(
        _composite(_openrouter(_ScriptedTransport(_http_error(500))), _FakeLocal()),
        cache=InMemoryCache(),
        trace=trace,
    )
    degraded_meta = _to_metadata(trace.records[0])
    assert degraded_meta["local_degraded"] is True
    assert "degrade_reason:server_error" in degraded_meta["tags"]  # type: ignore[operator]

    trace2 = RecordingTraceSink()
    await _generate_through_pipeline(
        _composite(_openrouter(_ScriptedTransport(_ok_response())), _FakeLocal()),
        cache=InMemoryCache(),
        trace=trace2,
    )
    healthy_tags = _to_metadata(trace2.records[0])["tags"]
    assert not any(str(tag).startswith("degrade_reason") for tag in healthy_tags)  # type: ignore[attr-defined]


def test_rate_is_none_when_the_denominator_is_zero_and_never_zero_point_zero() -> None:
    """분모 0 → None. 0.0으로 접으면 '호출이 없었다'가 '건강했다'로 읽힌다."""
    assert seat_local_degrade_rate(0, 0) is None
    assert seat_local_degrade_rate(0, 5) == 0.0
    assert seat_local_degrade_rate(1, 4) == 0.25
    assert seat_local_degrade_rate(3, 3) == 1.0
    with pytest.raises(ValueError, match="넘을 수 없다"):
        seat_local_degrade_rate(2, 1)  # 계수가 깨졌다 — 조용히 1.0으로 자르지 않는다
    with pytest.raises(ValueError, match="음수"):
        seat_local_degrade_rate(-1, 3)


def test_snapshot_rate_is_none_when_unarmed_even_with_counts() -> None:
    counter = LocalDegradeCounter()
    counter.record_cloud_attempt()
    counter.record_degrade("timeout")
    assert counter.snapshot(armed=False).rate is None
    assert counter.snapshot(armed=True).rate == 1.0
    assert counter.snapshot(armed=True).by_reason == {
        "rate_limited": 0,
        "server_error": 0,
        "timeout": 1,
        "not_configured": 0,
    }


async def test_rate_accumulates_across_mixed_traffic() -> None:
    """정상 3 + 429 1 + 401 1 → 디스패치 5·강등 1 = 0.2. 4xx는 분모에 들고 분자에는 안 든다."""
    counter_local = _FakeLocal()
    outcomes: list[Exception | dict[str, Any]] = [
        _ok_response(),
        _ok_response(),
        _ok_response(),
        _http_error(429),
        _http_error(401),
    ]

    class _Sequenced:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def post_chat(self, url: str, **kwargs: Any) -> Any:
            outcome = outcomes[len(self.calls)]
            self.calls.append(kwargs)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    composite = _composite(
        _openrouter(_Sequenced()),  # type: ignore[arg-type]
        counter_local,
    )
    for _ in range(4):
        await composite.generate("p", "s", _cloud_decision())
    with pytest.raises(SeatHttpError):
        await composite.generate("p", "s", _cloud_decision())

    snapshot = composite.local_degrade_snapshot()
    assert (snapshot.cloud_attempts, snapshot.local_degrades) == (5, 1)
    assert snapshot.rate == pytest.approx(0.2)


def test_stale_no_local_retry_claims_are_gone_from_the_source() -> None:
    """ARCH-64가 적은 문장 — 이제 **거짓**인 것들이 소스에 남아 있지 않다.

    "LOCAL로도 자동 재시도되지 않았다"·"LOCAL로 자동 재시도하지 않는다"는 학생 대면 서빙 조립에서
    거짓이다(ARCH-69가 런타임 강등을 붙였다). 이 문구가 돌아오면 코드가 다시 없는 사실을 말한다.
    """
    stale = (
        "LOCAL로도 자동 재시도되지 않았다",
        "LOCAL로 자동 재시도하지 않는다",
        "LOCAL 강등은 라우팅 시점의 구독·예산 가드에서만 일어난다",
        "다른 좌석·LOCAL로 자동 재시도",
    )
    offenders: dict[str, list[str]] = {}
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        hits = [phrase for phrase in stale if phrase in text]
        if hits:
            offenders[path.relative_to(_PACKAGE_ROOT).as_posix()] = hits
    assert offenders == {}, offenders


def test_secondary_cloud_seat_is_still_declared_absent() -> None:
    """LOCAL 강등이 생겨도 **2차 클라우드 좌석은 여전히 없다** — 두 사실을 섞어 위장하지 않는다."""
    assert CLOUD_FAILOVER_SEAT is None
    composite = _composite(_openrouter(_ScriptedTransport(_ok_response())), _FakeLocal())
    assert composite.cloud_failover_seat is None
    for outcome in ("not_armed", "not_eligible", "local_failed"):
        note = no_secondary_seat_note("openrouter", local_degrade=outcome)  # type: ignore[arg-type]
        assert "2차 클라우드 좌석 없음" in note
        assert "재시도 좌석 0개" in note


def test_note_wording_differs_per_local_outcome() -> None:
    """예외 note는 LOCAL로 갔는가를 조립별로 다르게 말한다 — 세 상태가 서로 다른 문장이다."""
    not_armed = no_secondary_seat_note("openrouter", local_degrade="not_armed")
    not_eligible = no_secondary_seat_note(
        "openrouter", local_degrade="not_eligible", failure_type="SeatHttpError"
    )
    failed = no_secondary_seat_note(
        "openrouter",
        local_degrade="local_failed",
        reason="rate_limited",
        local_error=ConnectionError("x"),
    )
    assert len({not_armed, not_eligible, failed}) == 3
    assert "장착되지 않아" in not_armed
    assert "강등 대상이 아니" in not_eligible and "SeatHttpError" in not_eligible
    assert "LOCAL도 실패" in failed and "ConnectionError" in failed
    # 좌석 미상은 anthropic으로 접지 않는다.
    assert "anthropic" not in no_secondary_seat_note(None).split("—")[0]
    assert "미선언" in no_secondary_seat_note(None)


# ===========================================================================
# 회차 관측(failover 블록) — seat_local_degrade_rate
# ===========================================================================
_PINS = ("deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4-pro")


def _failover(snapshot: LocalDegradeSnapshot | None) -> dict[str, Any]:
    tally = SeatTally().observe(model_name=_PINS[0], success=True, cost_usd=0.001)
    rates = seat_operating_rates(
        tally, selected_seat="openrouter", seat_model_pins=_PINS, local_degrade=snapshot
    )
    failover: dict[str, Any] = rates["failover"]
    return failover


def test_round_failover_block_without_counts_is_not_measured_not_zero() -> None:
    block = _failover(None)
    assert block["seat_local_degrade_rate"] is None
    assert block["local_degrade"]["measured"] is False
    assert block["local_degrade"]["armed"] is None
    assert block["secondary_seat"] is None
    assert "2차 클라우드 좌석 없음" in block["note"]
    assert "미측정" in block["note"]


def test_round_failover_block_reports_the_rate_from_the_shared_definition() -> None:
    counter = LocalDegradeCounter()
    for _ in range(4):
        counter.record_cloud_attempt()
    counter.record_degrade("rate_limited")
    block = _failover(counter.snapshot(armed=True))
    assert block["seat_local_degrade_rate"] == 0.25
    degrade = block["local_degrade"]
    assert degrade["measured"] is True and degrade["armed"] is True
    assert (degrade["cloud_attempts"], degrade["local_degrades"]) == (4, 1)
    assert set(degrade["by_reason"]) == set(DEGRADE_REASONS)
    assert degrade["by_reason"]["rate_limited"] == 1
    # ARCH-63 몫인 두 지표는 계속 미산출(0이 아니다).
    assert block["seat_primary_success_rate"] is None
    assert block["seat_failover_rate"] is None


def test_round_failover_block_zero_denominator_and_unarmed_are_none() -> None:
    empty_armed = LocalDegradeCounter().snapshot(armed=True)
    assert _failover(empty_armed)["seat_local_degrade_rate"] is None  # 분모 0
    unarmed = LocalDegradeCounter().snapshot(armed=False)
    block = _failover(unarmed)
    assert block["seat_local_degrade_rate"] is None  # 강등할 수 없는 구성
    assert "장착돼 있지 않았다" in block["note"]


# ===========================================================================
# ⑥ 집행 지점 — 강등을 켜는 곳은 학생 대면 서빙(app.py)뿐이다
# ===========================================================================
def _composite_calls() -> list[tuple[str, ast.Call]]:
    calls: list[tuple[str, ast.Call]] = []
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "CompositeProvider"
            ):
                calls.append((path.relative_to(_PACKAGE_ROOT).as_posix(), node))
    return calls


def _armed_keyword(call: ast.Call) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == "runtime_local_degrade":
            return keyword.value
    return None


def test_only_the_student_facing_app_arms_runtime_local_degrade() -> None:
    """AST 동결 — `runtime_local_degrade=True`는 `app.py`의 CompositeProvider 조립에만 있다.

    스캔 0건은 통과가 아니다: 저작·측정 조립(여러 파일)이 실제로 잡혀야 이 가드가 공허하지 않다.
    저작·측정 조립이 강등을 켜면 ⓐ "명확한 실패"가 옳은 저작 경로가 LOCAL 응답으로 조용히 이어지고
    ⓑ 좌석 정확도를 재는 하네스가 LOCAL 응답을 클라우드 좌석의 응답으로 기록해 측정이 무효가 된다.
    """
    calls = _composite_calls()
    files = {name for name, _ in calls}
    assert "app.py" in files
    assert (
        len(files) >= 6
    ), f"CompositeProvider 조립 파일이 너무 적게 잡혔다(가드가 공허한가?): {files}"

    armed_files: set[str] = set()
    for name, call in calls:
        value = _armed_keyword(call)
        if value is None:
            continue
        assert isinstance(value, ast.Constant), f"{name}: runtime_local_degrade는 리터럴이어야 한다"
        if value.value is True:
            armed_files.add(name)
    assert armed_files == {"app.py"}, armed_files


def test_app_default_provider_arms_it_and_authoring_assemblies_do_not() -> None:
    """행위 확인 — `create_app()` 기본 조립은 장착, 저작 생성기의 기본 조립은 미장착."""
    from whymath_backend.app import _PROVIDER_KEY
    from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator

    provider = getattr(create_app().state, _PROVIDER_KEY)
    assert isinstance(provider, CompositeProvider)
    assert provider.local_degrade_armed is True

    authoring = LLMEquivalentProblemGenerator(trace=RecordingTraceSink())._provider
    assert isinstance(authoring, CompositeProvider)
    assert authoring.local_degrade_armed is False


# ===========================================================================
# 앱 조립 끝단 — 실제 `create_app()` provider가 강등하고 /status·/v1/generate가 그것을 말한다
# ===========================================================================
_OPENROUTER_KEY_ENVS = ("WHYMATH_OPENROUTER_API_KEY", "OPENROUTER_API_KEY")
_SEAT_ENVS = ("WHYMATH_CLOUD_PROVIDER", "WHYMATH_ANTHROPIC_API_ENABLED")


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """프로세스 설정을 기본값 + OpenRouter 키 있음으로 고정한다(anthropic 키는 넣지 않는다)."""
    for name in _SEAT_ENVS + _OPENROUTER_KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WHYMATH_OPENROUTER_API_KEY", "sk-or-fake-for-arch69-test")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


class _AppTransport:
    """모듈 전역 `HttpxChatTransport` 자리에 끼우는 대역 — 팩토리·`create_app()`이 만든 실제 provider가 쓴다."""

    outcome: Exception | dict[str, Any] = _ok_response()
    calls: int = 0

    async def post_chat(self, url: str, **kwargs: Any) -> Any:
        type(self).calls += 1
        if isinstance(type(self).outcome, Exception):
            raise type(self).outcome
        return type(self).outcome


@pytest.fixture
def app_cloud_transport(
    monkeypatch: pytest.MonkeyPatch, app_env: None
) -> Iterator[type[_AppTransport]]:
    _AppTransport.outcome = _ok_response()
    _AppTransport.calls = 0
    monkeypatch.setattr(openrouter_module, "HttpxChatTransport", _AppTransport)

    async def _local_generate(
        self: OllamaProvider, prompt: str, system: str, decision: RoutingDecision, **kwargs: Any
    ) -> GenerationResult:
        return GenerationResult(_LOCAL_TEXT, usage=Usage(input_tokens=3, output_tokens=4))

    async def _local_status(self: OllamaProvider) -> OllamaStatus:
        return OllamaStatus(reachable=False, models=(), error="stub — 네트워크 0")

    monkeypatch.setattr(OllamaProvider, "generate", _local_generate)
    monkeypatch.setattr(OllamaProvider, "check_status", _local_status)
    yield _AppTransport
    _AppTransport.outcome = _ok_response()
    _AppTransport.calls = 0


async def test_app_assembled_provider_degrades_end_to_end_and_status_reports_the_rate(
    app_cloud_transport: type[_AppTransport],
) -> None:
    """`create_app()` 기본 조립 → CLOUD_MID 요청 → 1차 좌석 429 → LOCAL이 답한다 → /status가 강등률을 말한다."""
    from whymath_backend.app import _PROVIDER_KEY

    app = create_app()
    provider = getattr(app.state, _PROVIDER_KEY)
    client = TestClient(app)

    # 강등 전 — 디스패치가 없었으므로 강등률은 **None**이다(0.0이 아니다).
    before = client.get("/status").json()["cloud_local_degrade"]
    assert before["armed"] is True
    assert before["cloud_attempts"] == 0
    assert before["seat_local_degrade_rate"] is None
    assert set(before["by_reason"]) == set(DEGRADE_REASONS)

    app_cloud_transport.outcome = _http_error(429)
    trace = RecordingTraceSink()
    result = await pipeline.generate(
        _student_request(),
        "학생 질문",
        "시스템",
        provider=provider,
        cache=InMemoryCache(),
        trace=trace,
        cache_ttl_s=60,
    )

    assert result.text == _LOCAL_TEXT
    assert result.local_degrade is not None
    assert result.local_degrade.reason == "rate_limited"
    assert result.local_degrade.from_seat == "openrouter"
    assert app_cloud_transport.calls == 1
    assert trace.records[0]["cost_krw"] == 0.0

    after = client.get("/status").json()
    assert after["cloud_failover_seat"] is None  # 2차 **클라우드** 좌석은 여전히 없다
    degrade = after["cloud_local_degrade"]
    assert (degrade["cloud_attempts"], degrade["local_degrades"]) == (1, 1)
    assert degrade["seat_local_degrade_rate"] == 1.0
    assert degrade["by_reason"]["rate_limited"] == 1


async def test_app_assembled_provider_does_not_degrade_on_auth_errors(
    app_cloud_transport: type[_AppTransport],
) -> None:
    """앱 조립에서도 4xx 대조군 — 401은 강등하지 않고 예외가 그대로 올라온다."""
    from whymath_backend.app import _PROVIDER_KEY

    provider = getattr(create_app().state, _PROVIDER_KEY)
    app_cloud_transport.outcome = _http_error(401)

    with pytest.raises(SeatHttpError) as excinfo:
        await pipeline.generate(
            _student_request(),
            "학생 질문",
            "시스템",
            provider=provider,
            cache=InMemoryCache(),
            trace=RecordingTraceSink(),
            cache_ttl_s=60,
        )
    assert excinfo.value.status_code == 401
    snapshot = provider.local_degrade_snapshot()
    assert (snapshot.cloud_attempts, snapshot.local_degrades) == (1, 0)


async def test_app_missing_openrouter_key_answers_from_local_marked_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenRouter 키 부재 — 학생 대면 조립은 LOCAL이 대신 답하되 `not_configured`로 **표기**한다.

    ARCH-64 시점에는 이 경우 명확한 RuntimeError였다(LOCAL·anthropic 어느 쪽도 대신 받지 않았다).
    학생 대면은 그 오류가 화면의 500이므로 강등으로 바뀌었고, 표기가 그 조용함을 막는다.
    """
    for name in _SEAT_ENVS + _OPENROUTER_KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    async def _local_generate(
        self: OllamaProvider, prompt: str, system: str, decision: RoutingDecision, **kwargs: Any
    ) -> GenerationResult:
        return GenerationResult(_LOCAL_TEXT, usage=Usage(input_tokens=1, output_tokens=1))

    monkeypatch.setattr(OllamaProvider, "generate", _local_generate)
    try:
        from whymath_backend.app import _PROVIDER_KEY

        provider = getattr(create_app().state, _PROVIDER_KEY)
        trace = RecordingTraceSink()
        result = await pipeline.generate(
            _student_request(),
            "학생 질문",
            "시스템",
            provider=provider,
            cache=InMemoryCache(),
            trace=trace,
            cache_ttl_s=60,
        )
    finally:
        get_settings.cache_clear()
    assert result.local_degrade is not None
    assert result.local_degrade.reason == "not_configured"
    assert trace.records[0]["degrade_reason"] == "not_configured"


class _FakeSession:
    """`/v1/generate`의 session 의존성용 가짜 — 동의 조회(scalar)·소유권 기록(add·commit)만 모사한다."""

    async def scalar(self, stmt: Any) -> Any:
        return None

    def add(self, obj: Any) -> None:
        return None

    async def commit(self) -> None:
        return None


class _NoQueue:
    async def enqueue(self, payload: dict[str, object]) -> str:  # pragma: no cover - 동기 경로
        raise AssertionError("동기 CLOUD 경로는 큐를 타지 않는다")


def _generate_client(provider: CompositeProvider) -> TestClient:
    app = create_app(
        provider=provider, cache=InMemoryCache(), trace=RecordingTraceSink(), queue=_NoQueue()
    )
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _payload() -> dict[str, Any]:
    return {
        "request": _student_request().model_dump(mode="json"),
        "prompt": "학생 질문",
        "system": "",
    }


def test_generate_response_body_says_local_answered_when_degraded() -> None:
    """`/v1/generate` 응답 — `decision`은 클라우드 그대로지만 `local_degraded=true`가 어긋남을 말한다."""
    provider = _composite(_openrouter(_ScriptedTransport(_http_error(503))), _FakeLocal())
    body = _generate_client(provider).post("/v1/generate", json=_payload()).json()

    assert body["text"] == _LOCAL_TEXT
    assert body["decision"]["cost_tier"] == CostTier.CLOUD_MID.value
    assert body["local_degraded"] is True
    assert body["degraded_from_seat"] == "openrouter"
    assert body["degrade_reason"] == "server_error"
    assert body["cache_hit"] is False


def test_generate_response_body_healthy_call_has_no_degrade() -> None:
    provider = _composite(_openrouter(_ScriptedTransport(_ok_response())), _FakeLocal())
    body = _generate_client(provider).post("/v1/generate", json=_payload()).json()

    assert body["text"] == _CLOUD_TEXT
    assert body["local_degraded"] is False
    assert body["degraded_from_seat"] is None
    assert body["degrade_reason"] is None
