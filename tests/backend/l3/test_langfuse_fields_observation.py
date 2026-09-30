"""ARCH-101 — 학생 대면 trace 레코드의 관측 축(`served_model`·`retries`) 계약 (hermetic · 네트워크 0).

학생 대면 경로(`/v1/generate` → `l3/pipeline.generate`)의 trace 레코드는 `router.langfuse_fields`가
만든다. 그 dict에 `Usage.served_model`(응답이 실제로 어느 모델에서 왔나)과 `Usage.retries`(이 호출
1건의 실제 재시도 수)가 없어서, 저작 경로(EOS-112 genlog)와 달리 학생 대면 경로만 "누가 실제로
답했나"를 사후에 알 수 없었다. ARCH-69(런타임 LOCAL 강등)가 붙은 뒤로 "좌석은 openrouter인데 실제
답은 LOCAL"인 회차가 생겨 그 공백이 커졌다(ARCH-71 런북 부록 ① `served.in_trace_record=false`).

확인하는 것 다섯 가지:

  ① **옮기기만 한다** — 두 값은 `usage`에서 그대로 온다. 미측정 None을 0이나 설정값(선언 핀)으로
     접지 않는다. 기존 키의 이름·값은 그대로다.
  ② **클라우드 정상 응답** — 가짜 OpenRouter 응답의 `model`이 레코드에 그대로 실리고(선언 핀이
     아니다), 실물 전송기(`HttpxChatTransport`)에 재시도 N회를 주입하면 `retries=N`이다.
  ③ **LOCAL 결정** — 실물 `OllamaProvider`가 응답에서 읽은 태그가 실리고(요청 태그가 아니다),
     `retries`는 None이다(Ollama는 우리 전송기를 타지 않아 계측이 없다 — 0이 아니다).
  ④ **ARCH-69 강등** — 레코드의 `served_model`은 **대신 답한 LOCAL 모델**이고 `retries`는 None이다.
     실패한 클라우드 시도는 실제로 재시도했지만(카운터로 확인) 그 수는 이 레코드에 실리지 않는다.
  ⑤ **끝까지 나간다** — `create_app()` 기본 조립의 `/v1/generate`가 같은 두 값을 레코드에 싣고,
     `LangfuseSink`는 두 키를 걸러 내지 않고 이벤트 메타데이터로 보낸다.

어떤 LLM·네트워크에도 닿지 않는다 — 가짜 HTTP 전송(`httpx.MockTransport`)·가짜 Ollama 클라이언트만 쓴다.
"""

from __future__ import annotations

import functools
import importlib
import uuid
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from whymath_backend.api._auth import get_current_user
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l3 import pipeline
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.interfaces import InMemoryCache, RecordingTraceSink
from whymath_backend.l3.models import CallSite, CostTier, RoutingDecision, RoutingRequest, Usage
from whymath_backend.l3.providers import openrouter as openrouter_module
from whymath_backend.l3.providers._openai_compat import (
    HttpxChatTransport,
    retries_in_current_call,
)
from whymath_backend.l3.providers.composite import CompositeProvider
from whymath_backend.l3.providers.ollama import OllamaProvider
from whymath_backend.l3.providers.openrouter import OpenRouterProvider
from whymath_backend.l3.router import langfuse_fields
from whymath_backend.l3.trace.langfuse_sink import LangfuseSink

# 선언 핀(설정이 지목한 모델)과 관측 모델(응답이 말한 모델)을 **일부러 다르게** 둔다 — 같으면
# "설정값으로 접기" 뮤테이션이 초록으로 통과한다(별칭→버전 해소가 실제로 이런 모양이다).
_PIN = "deepseek/deepseek-v4.1-flash"
_SERVED = "deepseek/deepseek-v4.1-flash-20260910"
_CLOUD_TEXT = "cloud answer"
_LOCAL_TEXT = "local answer"
_LOCAL_SERVED_SUFFIX = "-q4_K_M"  # 데몬이 실제로 로드한 태그 = 요청 태그 + 양자화 접미(가짜)

# ARCH-101 직전(main ebd7a159)의 `langfuse_fields` 키 — 이름이 하나도 바뀌지 않았는지 본다.
_PRE_ARCH101_KEYS = frozenset(
    {
        "cost_tier",
        "local_family",
        "local_model",
        "mode",
        "est_latency_ms",
        "est_cost_krw",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "cost_krw",
        "call_site",
        "cache_hit",
        "escalated_from",
        "student_id_hash",
        "reason",
        "validation_signal",
        "training_allowed",
        "data_export_blocked",
        "data_export_reason",
        "content_source",
        "cloud_seat",
        "local_degraded",
        "degraded_from_seat",
        "degrade_reason",
        "degraded_to_local",
        "degrade_cloud_attempt_ms",
    }
)
_OPENROUTER_KEY_ENVS = ("WHYMATH_OPENROUTER_API_KEY", "OPENROUTER_API_KEY")
_SEAT_ENVS = ("WHYMATH_CLOUD_PROVIDER", "WHYMATH_ANTHROPIC_API_ENABLED")


# ===========================================================================
# 대역 — 가짜 HTTP(실물 전송기가 그 위에서 돈다)·가짜 Ollama 클라이언트
# ===========================================================================
def _ok_body(model: str | None = _SERVED) -> dict[str, Any]:
    """OpenAI 호환 `/chat/completions` 200 본문 — 최상위 `model`이 관측 모델의 출처다."""
    body: dict[str, Any] = {
        "choices": [{"message": {"role": "assistant", "content": _CLOUD_TEXT}}],
        "usage": {"prompt_tokens": 40, "completion_tokens": 60},
    }
    if model is not None:
        body["model"] = model
    return body


class _ScriptedHttp:
    """`httpx.MockTransport` 핸들러 — 상태코드 순서표대로 응답하고 받은 요청 수를 센다.

    실물 `HttpxChatTransport`가 이 위에서 **프로덕션 코드 그대로** 재시도·백오프를 돈다(대기만
    no-op으로 주입). 순서표가 다 떨어지면 마지막 상태를 반복한다.
    """

    def __init__(self, statuses: Sequence[int], *, model: str | None = _SERVED) -> None:
        self._statuses = list(statuses)
        self._model = model
        self.requests = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        status = self._statuses[min(self.requests, len(self._statuses) - 1)]
        self.requests += 1
        if status == 200:
            return httpx.Response(200, json=_ok_body(self._model))
        return httpx.Response(status, json={"error": {"message": f"scripted {status}"}})


def _install_http(monkeypatch: pytest.MonkeyPatch, handler: _ScriptedHttp) -> None:
    """전송기가 쓰는 `httpx.AsyncClient`를 MockTransport 기반으로 바꾼다(네트워크 0).

    가리기 **전에** anthropic을 적재한다: 강등 분류기(`seat_failure._timeout_types`)가 첫 분류 때
    anthropic을 지연 import하고, anthropic은 import 시점에 `httpx.AsyncClient`를 **상속**한다 —
    이름을 함수로 가린 뒤에 그 import가 일어나면 TypeError다(대역의 순서 문제·프로덕션 무관).
    """
    importlib.import_module("anthropic")
    real_client = httpx.AsyncClient

    def client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)


async def _no_sleep(_: float) -> None:
    return None


def _real_transport() -> HttpxChatTransport:
    """프로덕션 전송기 — 최대 3회 시도(기본값과 같다)·대기와 지터만 테스트용으로 0."""
    return HttpxChatTransport(max_attempts=3, sleep=_no_sleep, jitter=lambda: 0.0)


class _FakeOllamaClient:
    """`_OllamaClient` 대역 — 요청 태그를 기록하고, 응답의 `model`에는 **다른** 태그를 싣는다.

    실제 데몬도 요청 태그와 다른 태그를 돌려줄 수 있다(`qwen2-math` → `qwen2-math:7b`). 응답
    태그를 요청 태그와 다르게 두어야 "요청 태그를 관측으로 실었다"는 오류가 초록으로 통과하지 못한다.
    """

    def __init__(self) -> None:
        self.requested: list[str] = []

    async def generate(self, **kwargs: Any) -> Mapping[str, Any]:
        model = str(kwargs["model"])
        self.requested.append(model)
        return {
            "response": _LOCAL_TEXT,
            "model": model + _LOCAL_SERVED_SUFFIX,
            "prompt_eval_count": 7,
            "eval_count": 9,
        }

    # 이 파일은 /status를 부르지 않는다 — `_OllamaClient` 표면을 채우는 자리일 뿐이다.
    async def list(self) -> Mapping[str, Any]:  # pragma: no cover
        return {"models": []}


def _openrouter(transport: HttpxChatTransport | None) -> OpenRouterProvider:
    settings = Settings(
        openrouter_api_key=SecretStr("sk-or-fake-for-arch101-test"),
        openrouter_allowed_providers=("deepinfra",),
        openrouter_model_mid=_PIN,
    )
    return OpenRouterProvider(transport=transport, settings=settings)


def _student_facing(
    cloud: OpenRouterProvider, local_client: _FakeOllamaClient
) -> CompositeProvider:
    """학생 대면 조립과 같은 모양 — 1차 좌석 openrouter + 실물 Ollama 제공자 + 런타임 강등 장착."""
    return CompositeProvider(
        local=OllamaProvider(client=local_client),  # type: ignore[arg-type]
        cloud=cloud,
        runtime_local_degrade=True,
    )


def _cloud_mid_request() -> RoutingRequest:
    """CLOUD_MID로 라우팅되는 요청 — premium·추론 필요·예산 충분·반출 가능 등급(ARCH-71 0-2 표)."""
    return RoutingRequest(
        task_type="coach",
        difficulty="hard",
        requires_reasoning=True,
        student_subscription="premium",
        budget_krw=1000.0,
        sync=True,
        data_licenses=SELF_AUTHORED_CORPUS,
    )


def _local_request() -> RoutingRequest:
    """LOCAL로 라우팅되는 요청 — 오늘의 학생 기본 신호와 같은 free·예산 0."""
    return RoutingRequest(
        task_type="coach",
        difficulty="hard",
        requires_reasoning=True,
        student_subscription="free",
        budget_krw=0.0,
        sync=True,
        data_licenses=SELF_AUTHORED_CORPUS,
    )


async def _generate(
    provider: CompositeProvider,
    request: RoutingRequest,
    *,
    trace: RecordingTraceSink,
    cache: InMemoryCache | None = None,
) -> pipeline.GenerationResult:
    return await pipeline.generate(
        request,
        "학생 질문",
        "시스템",
        provider=provider,
        cache=cache if cache is not None else InMemoryCache(),
        trace=trace,
        cache_ttl_s=60,
    )


def _local_decision() -> RoutingDecision:
    return RoutingDecision(
        cost_tier=CostTier.LOCAL,
        local_family="math",
        local_model="mid",
        mode="sync",
        reason="arch101",
        est_latency_ms=3918,
        est_cost_krw=0.0,
        data_licenses=SELF_AUTHORED_CORPUS,
    )


# ===========================================================================
# ① 옮기기만 한다 — `langfuse_fields` 단위 계약
# ===========================================================================
def test_both_keys_are_present_and_none_when_usage_is_absent() -> None:
    """usage 없음(캐시 적중·enqueue·미계측) → 두 키가 **있고** 값은 None이다(키 부재 ≠ None)."""
    fields = langfuse_fields(_local_decision())
    assert "served_model" in fields and "retries" in fields
    assert fields["served_model"] is None
    assert fields["retries"] is None


def test_values_are_copied_verbatim_from_usage() -> None:
    fields = langfuse_fields(
        _local_decision(), usage=Usage(served_model="some/model-x", retries=2), cost_krw=0.0
    )
    assert fields["served_model"] == "some/model-x"
    assert fields["retries"] == 2


@pytest.mark.parametrize(("measured", "expected"), [(0, 0), (None, None), (3, 3)])
def test_retries_none_and_zero_are_different_facts(
    measured: int | None, expected: int | None
) -> None:
    """0은 "계측했고 한 번에 성공"이고 None은 "계측 없음"이다 — 서로 접히지 않는다."""
    fields = langfuse_fields(_local_decision(), usage=Usage(retries=measured))
    assert fields["retries"] == expected
    assert (fields["retries"] is None) is (measured is None)


def test_unobserved_served_model_is_not_folded_to_the_declared_pin() -> None:
    """응답이 모델을 말하지 않았으면 None이다 — 설정의 선언 핀으로 채우지 않는다."""
    assert get_settings().openrouter_model_mid  # 접을 대상(선언 핀)이 실제로 존재한다
    fields = langfuse_fields(_local_decision(), usage=Usage(input_tokens=1, output_tokens=1))
    assert fields["served_model"] is None
    assert fields["served_model"] != get_settings().openrouter_model_mid


def test_existing_keys_keep_their_names_and_measured_values() -> None:
    """ARCH-101은 키를 **더할** 뿐이다 — 직전 키 이름은 전부 남고 실측 값의 의미도 그대로다."""
    usage = Usage(input_tokens=11, output_tokens=22, latency_ms=33.5, served_model="m", retries=1)
    fields = langfuse_fields(_local_decision(), usage=usage, cost_krw=0.0)
    assert _PRE_ARCH101_KEYS <= set(fields)
    assert {"served_model", "retries"} <= set(fields) - _PRE_ARCH101_KEYS
    assert (fields["input_tokens"], fields["output_tokens"], fields["latency_ms"]) == (11, 22, 33.5)
    assert fields["cost_krw"] == 0.0


# ===========================================================================
# ② 클라우드 정상 응답 — 응답의 `model`이 그대로·재시도 수는 이 호출의 실측
# ===========================================================================
@pytest.mark.parametrize(
    ("statuses", "expected_retries"),
    [([200], 0), ([429, 200], 1), ([503, 429, 200], 2)],
    ids=["no-retry", "one-429-retry", "two-retries"],
)
async def test_openrouter_answer_records_the_response_model_and_the_retry_count(
    monkeypatch: pytest.MonkeyPatch, statuses: list[int], expected_retries: int
) -> None:
    """실물 전송기에 재시도 N회를 주입하면 레코드의 `retries`가 N이고, `served_model`은 응답의 `model`이다.

    대조군(no-retry)의 0은 "계측 없음(None)"이 아니라 **계측했고 한 번에 성공**이다.
    """
    handler = _ScriptedHttp(statuses)
    _install_http(monkeypatch, handler)
    local_client = _FakeOllamaClient()
    trace = RecordingTraceSink()

    result = await _generate(
        _student_facing(_openrouter(_real_transport()), local_client),
        _cloud_mid_request(),
        trace=trace,
    )

    assert result.text == _CLOUD_TEXT and result.local_degrade is None
    assert handler.requests == expected_retries + 1  # 주입이 실제로 적용됐다(전송 횟수)
    assert local_client.requested == []  # LOCAL은 닿지 않았다
    record = trace.records[-1]
    assert record["cost_tier"] == CostTier.CLOUD_MID.value
    assert record["cloud_seat"] == "openrouter"
    assert record["local_degraded"] is False
    assert record["served_model"] == _SERVED
    assert record["served_model"] != _PIN  # 선언 핀이 아니라 응답이 말한 모델
    assert record["retries"] == expected_retries


async def test_response_without_a_model_field_records_none_not_the_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """공급사 응답에 `model`이 없으면 관측 모델은 None이다 — 설정 핀으로 채우지 않는다."""
    _install_http(monkeypatch, _ScriptedHttp([200], model=None))
    trace = RecordingTraceSink()
    await _generate(
        _student_facing(_openrouter(_real_transport()), _FakeOllamaClient()),
        _cloud_mid_request(),
        trace=trace,
    )
    record = trace.records[-1]
    assert record["served_model"] is None
    assert record["retries"] == 0  # 전송기는 계측했다 — 모델 미관측과 재시도 계측은 별개 축


# ===========================================================================
# ③ LOCAL 결정 — Ollama 응답의 태그 · 재시도 계측 없음(None)
# ===========================================================================
async def test_local_decision_records_the_ollama_response_tag_and_no_retry_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOCAL로 라우팅되면 `served_model`은 **데몬이 응답한 태그**, `retries`는 None(0이 아니다)."""
    handler = _ScriptedHttp([200])
    _install_http(monkeypatch, handler)
    local_client = _FakeOllamaClient()
    trace = RecordingTraceSink()

    result = await _generate(
        _student_facing(_openrouter(_real_transport()), local_client),
        _local_request(),
        trace=trace,
    )

    assert result.decision.cost_tier == CostTier.LOCAL.value
    assert handler.requests == 0  # 클라우드 좌석은 닿지 않았다
    assert len(local_client.requested) == 1
    record = trace.records[-1]
    assert record["served_model"] == local_client.requested[0] + _LOCAL_SERVED_SUFFIX
    assert record["served_model"] != local_client.requested[0]  # 요청 태그가 아니라 응답 태그
    assert record["retries"] is None
    assert record["cloud_seat"] is None


# ===========================================================================
# ④ ARCH-69 강등 — 대신 답한 LOCAL 모델 · 클라우드 시도의 재시도는 싣지 않는다
# ===========================================================================
async def test_degraded_call_records_the_local_model_that_answered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1차 좌석 429 소진 → LOCAL이 답한다 → 레코드의 관측 모델은 **LOCAL 태그**, `retries`는 None.

    클라우드 시도는 실제로 재시도 2회를 했다(전송기 카운터가 2 늘었다) — 그래도 레코드의
    `retries`는 그 값이 아니다. 이 레코드의 두 값은 텍스트를 만든 호출(LOCAL)의 것이고, LOCAL에는
    재시도 계측이 없다. 실패한 시도의 시간은 `degrade_cloud_attempt_ms`에 있다.
    """
    handler = _ScriptedHttp([429, 429, 429])
    _install_http(monkeypatch, handler)
    local_client = _FakeOllamaClient()
    trace = RecordingTraceSink()

    before = retries_in_current_call()
    result = await _generate(
        _student_facing(_openrouter(_real_transport()), local_client),
        _cloud_mid_request(),
        trace=trace,
    )
    cloud_retries = retries_in_current_call() - before

    assert result.local_degrade is not None and result.local_degrade.reason == "rate_limited"
    assert handler.requests == 3 and cloud_retries == 2  # 클라우드 쪽 재시도는 실제로 있었다
    assert len(local_client.requested) == 1
    record = trace.records[-1]
    assert record["cost_tier"] == CostTier.CLOUD_MID.value  # 결정은 클라우드 그대로
    assert record["local_degraded"] is True
    assert record["served_model"] == local_client.requested[0] + _LOCAL_SERVED_SUFFIX
    assert record["served_model"] not in (_SERVED, _PIN)
    assert record["retries"] is None
    assert record["retries"] != cloud_retries
    assert isinstance(record["degrade_cloud_attempt_ms"], float)


# ===========================================================================
# usage가 없는 기록 — 캐시 적중·비동기 enqueue는 둘 다 None
# ===========================================================================
async def test_cache_hit_record_carries_none_for_both(monkeypatch: pytest.MonkeyPatch) -> None:
    """적중 레코드는 이번 요청에 LLM 호출이 없었다 — 관측 모델·재시도 모두 None(원 생성자는 미스 레코드)."""
    _install_http(monkeypatch, _ScriptedHttp([200]))
    provider = _student_facing(_openrouter(_real_transport()), _FakeOllamaClient())
    cache = InMemoryCache()
    trace = RecordingTraceSink()

    await _generate(provider, _cloud_mid_request(), trace=trace, cache=cache)
    hit = await _generate(provider, _cloud_mid_request(), trace=trace, cache=cache)

    assert hit.cache_hit is True
    miss_record, hit_record = trace.records
    assert miss_record["served_model"] == _SERVED
    assert hit_record["served_model"] is None
    assert hit_record["retries"] is None


class _RecordingQueue:
    async def enqueue(self, payload: dict[str, object]) -> str:
        return "job-arch101"


async def test_async_enqueue_record_carries_none_for_both() -> None:
    """QUALITY enqueue 레코드는 생성 전이다 — 두 값 모두 None(워커가 생성 완료 레코드를 따로 남긴다)."""
    request = RoutingRequest(
        task_type="verify",
        difficulty="medium",
        requires_reasoning=True,
        student_subscription="free",
        budget_krw=0.0,
        sync=False,
        call_site=CallSite.SELF_VERIFY,
        data_licenses=SELF_AUTHORED_CORPUS,
    )
    trace = RecordingTraceSink()
    result = await pipeline.generate(
        request,
        "p",
        "s",
        provider=_student_facing(_openrouter(None), _FakeOllamaClient()),
        cache=InMemoryCache(),
        trace=trace,
        queue=_RecordingQueue(),
    )
    assert result.is_queued
    assert trace.records[-1]["served_model"] is None
    assert trace.records[-1]["retries"] is None


# ===========================================================================
# ⑤ 끝까지 — `create_app()` 기본 조립의 `/v1/generate` · LangfuseSink 메타데이터
# ===========================================================================
class _FakeSession:
    """`/v1/generate`의 session 의존성 대역 — 동의 조회·소유권 기록만 모사한다."""

    async def scalar(self, stmt: Any) -> Any:
        return None

    def add(self, obj: Any) -> None:
        return None

    async def commit(self) -> None:
        return None


@pytest.fixture
def default_assembly(monkeypatch: pytest.MonkeyPatch) -> Iterator[_ScriptedHttp]:
    """프로세스 설정을 기본 좌석 + OpenRouter 키 있음으로 고정하고, 실물 전송기 아래 HTTP만 가짜로 둔다.

    `create_app()`이 조립하는 OpenRouter 제공자는 모듈 전역 `HttpxChatTransport()`를 쓴다 — 그
    이름을 **대기만 0으로 바꾼 같은 클래스**로 가리고, 그 아래 httpx만 MockTransport로 바꾼다.
    """
    for name in _SEAT_ENVS + _OPENROUTER_KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WHYMATH_OPENROUTER_API_KEY", "sk-or-fake-for-arch101-test")
    monkeypatch.setattr(
        openrouter_module,
        "HttpxChatTransport",
        functools.partial(HttpxChatTransport, sleep=_no_sleep, jitter=lambda: 0.0),
    )
    handler = _ScriptedHttp([429, 200])
    _install_http(monkeypatch, handler)
    get_settings.cache_clear()
    try:
        yield handler
    finally:
        get_settings.cache_clear()


def test_v1_generate_default_assembly_records_served_model_and_one_retry(
    default_assembly: _ScriptedHttp,
) -> None:
    """ARCH-71 런북 프로브와 같은 조립 — `/v1/generate` 1회 → trace 레코드에 응답 모델·재시도 1."""
    trace = RecordingTraceSink()
    app = create_app(cache=InMemoryCache(), trace=trace)
    app.dependency_overrides[get_current_user] = lambda: UserProfile(user_id=uuid.uuid4())

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _fake_session
    response = TestClient(app).post(
        "/v1/generate",
        json={
            "request": _cloud_mid_request().model_dump(mode="json"),
            "prompt": "학생 질문",
            "system": "",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["local_degraded"] is False
    assert default_assembly.requests == 2  # 429 1회 → 재시도 → 200
    record = trace.records[-1]
    assert record["cloud_seat"] == "openrouter"
    assert record["served_model"] == _SERVED
    assert record["retries"] == 1


class _CapturingLangfuseClient:
    """`_LangfuseClient` 대역 — `create_event`로 받은 메타데이터를 보관한다."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def create_event(
        self, *, name: str, metadata: dict[str, object] | None = None, level: str | None = None
    ) -> Any:
        self.events.append({"name": name, "metadata": dict(metadata or {})})
        return None


@pytest.mark.parametrize(
    "usage",
    [Usage(served_model=_SERVED, retries=1), None],
    ids=["observed", "unmeasured"],
)
def test_langfuse_sink_forwards_both_keys_as_event_metadata(usage: Usage | None) -> None:
    """싱크는 키 화이트리스트가 없다 — 두 키가 값 그대로(None 포함) Langfuse 메타데이터로 나간다."""
    client = _CapturingLangfuseClient()
    fields = langfuse_fields(_local_decision(), usage=usage)
    LangfuseSink(client=client).record(fields)

    assert len(client.events) == 1
    metadata = client.events[0]["metadata"]
    assert "served_model" in metadata and "retries" in metadata
    assert metadata["served_model"] == fields["served_model"]
    assert metadata["retries"] == fields["retries"]
