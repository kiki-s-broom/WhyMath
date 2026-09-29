"""ARCH-64 — CLOUD_MID 좌석 컷오버의 **동작** 계약 (hermetic · 네트워크 0).

`test_cloud_provider_selector.py`가 *정본*(기본값·AST 조립 위치)을 동결한다면, 이 파일은 그
정본이 **실제로 도는 경로**에서 무엇을 내는지를 잰다(CLAUDE.md 「정본화를 집행으로 착각한 완료
선언 금지」 — 계약과 집행 지점을 별항으로 본다).

다섯 가지를 확인한다:

  ① **anthropic 비활성과의 상호작용** — `anthropic_api_enabled=False`(ARCH-66 기본)이고 Anthropic
     키가 **있어도**, 새 기본값에서 학생 대면(`create_app()`)과 저작 경로가 OpenRouter 좌석을
     조립하고 실제 호출이 OpenRouter 본문(모델·공급사 3종 계약)으로 나간다. 가짜 HTTP 전송층을
     모듈에 끼워 넣어 네트워크는 0이다.
  ② **기록 원가 = 좌석 단가** — 학생 대면 파이프라인이 원가를 anthropic 단가(8.612원/회 추정)가
     아니라 openrouter 단가로 계상하고, trace가 `cloud_seat=openrouter`를 싣는다(24.4배 과대
     계상 방지 — 03c §2.2).
  ③ **OpenRouter 키 부재** — 조용히 anthropic으로 가지 않고, 침묵하지도 않는다: **저작·측정 조립**
     (런타임 LOCAL 강등 미장착)은 명확한 RuntimeError, /status는 `cloud_configured=False` + 원인 문구.
     학생 대면 조립은 ARCH-69부터 LOCAL이 대신 답하되 `not_configured`로 표기한다
     (`test_cloud_runtime_local_degrade.py`).
  ④ **2차 좌석 없음의 정직성** (2026-09-28 Kiki 결정) — 1차 좌석 실패는 **다른 클라우드 좌석**으로
     넘어가지 않고, 예외 note·/status·회차 관측이 전부 "2차 클라우드 좌석 없음"을 말한다. '2차 좌석
     있음'으로 보이는 값이 생기면 red. LOCAL 강등은 별개 축이다(ARCH-69 — 강등 미장착 조립에서는
     이 파일이 "LOCAL로도 안 갔다"를, 학생 대면 조립에서는 그 파일이 "LOCAL이 답했다"를 동결한다).
  ⑤ **좌석 선언 ↔ 팩토리 셀렉터 정합** — 제공자 클래스의 `seat` 선언이 그 클래스를 만드는
     셀렉터 값과 같다(원가 기록이 읽는 좌석과 실제 좌석이 갈라지지 않는다).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.config import Settings, get_settings
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.interfaces import InMemoryCache, RecordingTraceSink
from whymath_backend.l3.models import CostTier, RoutingDecision, RoutingRequest, Usage
from whymath_backend.l3.pipeline import generate, served_cloud_seat
from whymath_backend.l3.providers import openrouter as openrouter_module
from whymath_backend.l3.providers.anthropic import AnthropicProvider
from whymath_backend.l3.providers.composite import (
    CLOUD_FAILOVER_SEAT,
    CompositeProvider,
    no_secondary_seat_note,
)
from whymath_backend.l3.providers.factory import build_cloud_provider
from whymath_backend.l3.providers.ollama import OllamaProvider, OllamaStatus
from whymath_backend.l3.providers.openrouter import OpenRouterProvider
from whymath_backend.l3.router import CLOUD_TOKEN_PRICE_USD_PER_1M, USD_TO_KRW, actual_cost_krw

# 가짜 응답의 실측 토큰 — 단가 산식을 테스트 안에서 다시 계산해 대조한다.
_IN_TOKENS = 1000
_OUT_TOKENS = 1000
_ANTHROPIC_KEY_ENV = "WHYMATH_ANTHROPIC_API_KEY"
_OPENROUTER_KEY_ENVS = ("WHYMATH_OPENROUTER_API_KEY", "OPENROUTER_API_KEY")
_SEAT_ENVS = ("WHYMATH_CLOUD_PROVIDER", "WHYMATH_ANTHROPIC_API_ENABLED")


def _expected_krw(seat: str) -> float:
    price_in, price_out = CLOUD_TOKEN_PRICE_USD_PER_1M[(CostTier.CLOUD_MID, seat)]  # type: ignore[index]
    return (_IN_TOKENS * price_in + _OUT_TOKENS * price_out) / 1_000_000 * USD_TO_KRW


class _FakeHttpTransport:
    """`HttpxChatTransport` 대역 — 호출을 기록하고 OpenAI 호환 응답(또는 예외)을 돌려준다.

    `OpenRouterProvider`는 주입 전송이 없으면 **모듈 전역** `HttpxChatTransport()`를 만든다.
    그 이름을 이 클래스로 갈아 끼우면 팩토리·`create_app()`이 만든 *실제* provider가 그대로
    이 대역을 쓴다 — provider를 손으로 조립하지 않으므로 조립 경로 자체를 잰다.
    """

    calls: list[dict[str, Any]] = []
    fail_with: Exception | None = None

    async def post_chat(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_s: float,
    ) -> Any:
        type(self).calls.append({"url": url, "payload": dict(payload)})
        if type(self).fail_with is not None:
            raise type(self).fail_with
        return {
            "choices": [{"message": {"role": "assistant", "content": "좌석 응답"}}],
            "usage": {"prompt_tokens": _IN_TOKENS, "completion_tokens": _OUT_TOKENS},
        }


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_FakeHttpTransport]]:
    _FakeHttpTransport.calls = []
    _FakeHttpTransport.fail_with = None
    monkeypatch.setattr(openrouter_module, "HttpxChatTransport", _FakeHttpTransport)
    yield _FakeHttpTransport
    _FakeHttpTransport.calls = []
    _FakeHttpTransport.fail_with = None


@pytest.fixture
def anthropic_never_called(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Anthropic 좌석이 한 번이라도 불리면 기록한다 — "조용히 anthropic으로 가는가"의 관측 지점."""
    called: list[str] = []

    async def _record(self: AnthropicProvider, *args: Any, **kwargs: Any) -> Any:
        called.append("anthropic")
        raise AssertionError("ARCH-64: 이 기간에 Anthropic 좌석이 호출되면 안 된다")

    monkeypatch.setattr(AnthropicProvider, "generate", _record)
    return called


@pytest.fixture
def local_never_called(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """LOCAL(Ollama)이 대신 불리면 기록한다 — "1차 좌석 실패 → 자동 LOCAL 재시도"의 관측 지점.

    **강등 미장착 조립**(저작·측정 경로, `CompositeProvider` 기본값)에서만 쓴다. 학생 대면 조립은
    ARCH-69부터 LOCAL 강등이 켜져 있어 이 관측 지점이 정상적으로 불린다.
    """
    called: list[str] = []

    async def _record(self: OllamaProvider, *args: Any, **kwargs: Any) -> Any:
        called.append("local")
        raise AssertionError(
            "ARCH-64: 강등 미장착 조립에서 클라우드 실패가 LOCAL로 재시도되면 안 된다"
        )

    monkeypatch.setattr(OllamaProvider, "generate", _record)
    return called


def _process_env(monkeypatch: pytest.MonkeyPatch, *, openrouter_key: str | None) -> Iterator[None]:
    """프로세스 설정을 기본값 + (anthropic 키 있음·비활성) + (openrouter 키 선택)으로 고정한다."""
    for name in _SEAT_ENVS + _OPENROUTER_KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    # Anthropic 키를 **넣는다** — 키가 있어도 ARCH-66 스위치가 꺼져 있고, 그래도 좌석이
    # anthropic으로 새지 않는다는 것이 이 파일이 재는 상호작용이다.
    monkeypatch.setenv(_ANTHROPIC_KEY_ENV, "sk-ant-fake-for-arch64-test")
    if openrouter_key is not None:
        monkeypatch.setenv("WHYMATH_OPENROUTER_API_KEY", openrouter_key)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture
def env_with_openrouter_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    yield from _process_env(monkeypatch, openrouter_key="sk-or-fake-for-arch64-test")


@pytest.fixture
def env_without_openrouter_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    yield from _process_env(monkeypatch, openrouter_key=None)


def _student_cloud_mid_request() -> RoutingRequest:
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


def _app_provider() -> Any:
    from whymath_backend.app import _PROVIDER_KEY, create_app

    return getattr(create_app().state, _PROVIDER_KEY)


# ===========================================================================
# ① anthropic 비활성 × 새 기본값 — 두 경로가 실제로 OpenRouter 좌석을 조립한다
# ===========================================================================


def test_defaults_are_anthropic_disabled_and_openrouter_selected(
    env_with_openrouter_key: None,
) -> None:
    """전제 확인 — 기본 설정은 Anthropic 비활성(ARCH-66) + 클라우드 좌석 openrouter(ARCH-64)."""
    settings = get_settings()
    assert settings.anthropic_api_enabled is False
    assert settings.anthropic_configured is False  # 키가 있어도 정책 차단
    assert settings.anthropic_policy_blocked is True
    assert settings.cloud_provider == "openrouter"


async def test_student_facing_app_calls_openrouter_and_records_seat_price(
    env_with_openrouter_key: None,
    fake_http: type[_FakeHttpTransport],
    anthropic_never_called: list[str],
) -> None:
    """학생 대면(`create_app()` 기본 조립) → CLOUD_MID 1회 → OpenRouter 본문 + 좌석 단가 원가."""
    provider = _app_provider()
    assert isinstance(provider, CompositeProvider)
    assert isinstance(provider._cloud, OpenRouterProvider)
    assert provider.cloud_seat == "openrouter"

    trace = RecordingTraceSink()
    result = await generate(
        _student_cloud_mid_request(),
        "학생 질문",
        "시스템",
        provider=provider,
        cache=InMemoryCache(),
        trace=trace,
        cache_ttl_s=60,
    )

    assert result.decision.cost_tier == CostTier.CLOUD_MID.value
    assert result.text == "좌석 응답"
    # 실제로 나간 본문 — ARCH-55 채택 구성 그대로(모델·공급사 고정·3종 계약).
    assert len(fake_http.calls) == 1
    call = fake_http.calls[0]
    assert call["url"].startswith("https://openrouter.ai/api/v1")
    assert call["payload"]["model"] == "deepseek/deepseek-v4.1-flash"
    assert call["payload"]["provider"] == {
        "only": ["deepinfra"],
        "allow_fallbacks": False,
        "data_collection": "deny",
    }
    assert anthropic_never_called == []
    # 원가 — openrouter 단가로 계상, anthropic 단가가 아니다(24.4배 과대 계상 방지).
    record = trace.records[0]
    assert record["cloud_seat"] == "openrouter"
    assert record["cost_krw"] == pytest.approx(_expected_krw("openrouter"))
    assert record["cost_krw"] != pytest.approx(_expected_krw("anthropic"))


async def test_authoring_path_calls_openrouter_and_records_seat_price(
    env_with_openrouter_key: None,
    fake_http: type[_FakeHttpTransport],
    anthropic_never_called: list[str],
) -> None:
    """저작 경로(동등문제 생성기 기본 조립) → OpenRouter 좌석 + 좌석 단가 원가 기록."""
    from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator

    trace = RecordingTraceSink()
    generator = LLMEquivalentProblemGenerator(trace=trace)
    composite = generator._provider
    assert isinstance(composite, CompositeProvider)
    assert isinstance(composite._cloud, OpenRouterProvider)
    assert generator._authoring_seat() == "openrouter"

    decision = RoutingDecision(
        cost_tier=CostTier.CLOUD_MID,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="arch64-authoring",
        est_latency_ms=3000,
        est_cost_krw=0.0,
        data_licenses=SELF_AUTHORED_CORPUS,
    )
    generated = await composite.generate("저작 프롬프트", "시스템", decision)
    assert fake_http.calls[0]["payload"]["model"] == "deepseek/deepseek-v4.1-flash"
    assert anthropic_never_called == []

    generator._record_trace(decision, generated.usage)
    assert trace.records[-1]["cost_krw"] == pytest.approx(_expected_krw("openrouter"))


# ===========================================================================
# ③ OpenRouter 키 부재 — anthropic으로 새지 않고, 침묵하지도 않는다
# ===========================================================================


async def test_missing_openrouter_key_fails_loudly_without_anthropic_or_local(
    env_without_openrouter_key: None,
    anthropic_never_called: list[str],
    local_never_called: list[str],
) -> None:
    """키 없음 → **저작 조립**(강등 미장착)은 명확한 RuntimeError + "2차 좌석 없음" note. Anthropic·LOCAL 어느 쪽도 대신 받지 않는다.

    학생 대면 조립(`create_app()`)은 ARCH-69부터 LOCAL이 대신 답한다 — 그 대비는
    `test_cloud_runtime_local_degrade.py::test_app_missing_openrouter_key_answers_from_local_marked_not_configured`.
    이 테스트가 옮겨 간 이유: 종전에는 앱 조립으로 재서 "LOCAL이 안 받는다"를 동결했는데, 그 사실은
    강등을 켠 조립에서 거짓이 됐다. 저작·측정 조립(강등 미장착)에서는 여전히 참이므로 실제 저작 조립으로 잰다.
    """
    from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator

    provider = LLMEquivalentProblemGenerator(trace=RecordingTraceSink())._provider
    assert isinstance(provider, CompositeProvider)
    assert provider.local_degrade_armed is False  # 저작 조립은 강등이 없다
    assert (
        provider.cloud_seat == "openrouter"
    )  # 키가 없어도 좌석은 openrouter — anthropic으로 접지 않음

    decision = RoutingDecision(
        cost_tier=CostTier.CLOUD_MID,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="arch64-missing-key",
        est_latency_ms=3000,
        est_cost_krw=0.0,
        data_licenses=SELF_AUTHORED_CORPUS,
    )
    with pytest.raises(RuntimeError, match="OpenRouter가 미설정") as excinfo:
        await provider.generate("학생 질문", "시스템", decision)
    notes = getattr(excinfo.value, "__notes__", [])
    assert any("2차 클라우드 좌석 없음" in note for note in notes), notes
    assert any("openrouter" in note for note in notes), notes
    assert any("장착되지 않아" in note for note in notes), notes
    assert anthropic_never_called == []
    assert local_never_called == []


def test_status_reports_missing_openrouter_key_and_no_failover_seat(
    env_without_openrouter_key: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/status — `cloud_configured=False` + 원인 문구 + `cloud_seat=openrouter` + `cloud_failover_seat=None`."""
    from whymath_backend.app import create_app

    async def _stub_local_status(self: OllamaProvider) -> OllamaStatus:
        return OllamaStatus(reachable=False, models=(), error="stub — 네트워크 0")

    monkeypatch.setattr(OllamaProvider, "check_status", _stub_local_status)
    body = TestClient(create_app()).get("/status").json()

    assert body["cloud_configured"] is False
    assert body["cloud_error"] is not None
    assert "키 미설정" in body["cloud_error"]
    assert "대체되지 않는다" in body["cloud_error"]
    assert body["cloud_seat"] == "openrouter"
    assert "cloud_failover_seat" in body  # 필드가 있어야 "없음"이 관측이다(부재 ≠ 없음)
    assert body["cloud_failover_seat"] is None


# ===========================================================================
# ④ 2차 좌석 없음 — 오류 문구·관측 필드가 정직한가
# ===========================================================================


class _CountingLocal:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise AssertionError("LOCAL로 자동 재시도되면 안 된다")


async def test_primary_seat_failure_is_not_retried_anywhere(
    fake_http: type[_FakeHttpTransport],
    anthropic_never_called: list[str],
) -> None:
    """1차 좌석 429 → **강등 미장착 조립**에서는 같은 예외(타입·메시지 보존)가 올라가고, 다른 좌석·LOCAL 호출은 0건.

    조립은 `CompositeProvider(local, cloud)` 기본값(= 저작·측정 조립)이다. 학생 대면 조립은 같은 429에서
    LOCAL이 대신 답한다 — `test_cloud_runtime_local_degrade.py`.
    """
    original = RuntimeError("OpenAI 호환 호출 실패 HTTP 429: engine_overloaded (시도 3회)")
    fake_http.fail_with = original
    local = _CountingLocal()
    settings = Settings(openrouter_api_key="sk-or-fake")  # type: ignore[arg-type]
    composite = CompositeProvider(local=local, cloud=build_cloud_provider(settings))
    decision = RoutingDecision(
        cost_tier=CostTier.CLOUD_MID,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="arch64-failover-absent",
        est_latency_ms=3000,
        est_cost_krw=0.0,
        data_licenses=SELF_AUTHORED_CORPUS,
    )

    with pytest.raises(RuntimeError) as excinfo:
        await composite.generate("p", "s", decision)

    assert excinfo.value is original  # 바꿔 치지 않는다 — 기존 except·match 계약 보존
    assert str(excinfo.value) == str(original)
    assert excinfo.value.__notes__ == [no_secondary_seat_note("openrouter")]
    assert len(fake_http.calls) == 1  # 1차 좌석 1회뿐
    assert local.calls == 0
    assert anthropic_never_called == []


def test_failover_seat_is_declared_absent() -> None:
    """2차 좌석 선언은 None이다 — 문자열이 되면 failover 배선 없이 '있음'을 선언하는 위장이다."""
    assert CLOUD_FAILOVER_SEAT is None
    composite = CompositeProvider(
        local=_CountingLocal(), cloud=build_cloud_provider(Settings())  # type: ignore[arg-type]
    )
    assert composite.cloud_failover_seat is None


def test_no_secondary_seat_note_says_absence_and_no_local_retry() -> None:
    """예외 note 문구 — "2차 클라우드 좌석 없음"과 (강등 미장착 조립의) "LOCAL 재시도 없음"을 둘 다 말한다.

    ARCH-69 이후 "LOCAL로 갔는가"는 조립마다 갈린다 — 이 기본 호출은 강등 미장착(저작·측정) 문구다. 세 상태
    (미장착·강등 대상 아님·LOCAL도 실패)의 문구 대비는 `test_cloud_runtime_local_degrade.py`가 동결한다.
    """
    note = no_secondary_seat_note("openrouter")
    assert "1차 좌석 openrouter" in note
    assert "2차 클라우드 좌석 없음" in note
    assert "재시도 좌석 0개" in note
    assert "LOCAL로도 재시도되지 않았다" in note
    assert "장착되지 않아" in note
    assert "ARCH-69" in note
    assert "ARCH-63" in note
    # 좌석을 모르면 anthropic으로 채우지 않는다.
    assert "anthropic" not in no_secondary_seat_note(None).split("—")[0]
    assert "미선언" in no_secondary_seat_note(None)


def test_round_seat_observation_reports_no_failover_metrics() -> None:
    """회차 관측(`cloud_seat` 블록) — failover 지표는 0이 아니라 **미산출(None)**이다."""
    from whymath_backend.harness.anchor_round_ledger import SeatTally, seat_operating_rates

    tally = SeatTally().observe(
        model_name="deepseek/deepseek-v4.1-flash", success=False, cost_usd=None
    )
    rates = seat_operating_rates(
        tally,
        selected_seat="openrouter",
        seat_model_pins=("deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4-pro"),
    )
    failover = rates["failover"]
    assert failover["secondary_seat"] is None
    assert failover["seat_primary_success_rate"] is None
    assert failover["seat_failover_rate"] is None
    # ARCH-69 — 강등률은 강등 계수를 받았을 때만 산출된다(이 회차 관측은 받지 않았다 → 미측정).
    assert failover["seat_local_degrade_rate"] is None
    assert "2차 클라우드 좌석 없음" in failover["note"]


# ===========================================================================
# ⑤ 좌석 선언 ↔ 팩토리 셀렉터 정합 — 원가 기록이 읽는 좌석이 실제 좌석과 같다
# ===========================================================================


@pytest.mark.parametrize("selector", ["anthropic", "openrouter", "deepseek"])
def test_provider_seat_declaration_matches_factory_selector(selector: str) -> None:
    """셀렉터 값 → 팩토리가 만든 제공자의 `seat` 선언 → Composite `cloud_seat` → 파이프라인 좌석."""
    settings = Settings(cloud_provider=selector)  # type: ignore[arg-type]
    cloud = build_cloud_provider(settings)
    assert type(cloud).seat == selector  # type: ignore[attr-defined]
    composite = CompositeProvider(local=_CountingLocal(), cloud=cloud)  # type: ignore[arg-type]
    assert composite.cloud_seat == selector
    assert served_cloud_seat(composite) == selector  # type: ignore[arg-type]


def test_undeclared_cloud_seat_is_unknown_not_anthropic() -> None:
    """좌석을 선언하지 않은 클라우드 제공자를 꽂으면 좌석은 None(미상) — anthropic으로 접지 않는다."""

    class _UndeclaredCloud:
        async def generate(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
            raise AssertionError

    composite = CompositeProvider(local=_CountingLocal(), cloud=_UndeclaredCloud())  # type: ignore[arg-type]
    assert composite.cloud_seat is None
    assert served_cloud_seat(composite) is None  # type: ignore[arg-type]
    # 미상 좌석의 원가는 None(미측정)이다 — anthropic 단가로 채워지지 않는다.
    decision = RoutingDecision(
        cost_tier=CostTier.CLOUD_MID,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="arch64-undeclared",
        est_latency_ms=3000,
        est_cost_krw=0.0,
    )
    usage = Usage(input_tokens=10, output_tokens=10, latency_ms=None)
    assert actual_cost_krw(decision, usage, seat=served_cloud_seat(composite)) is None  # type: ignore[arg-type]
