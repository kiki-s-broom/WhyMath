"""AnthropicProvider 단위테스트 — 가짜 Anthropic 클라이언트 주입 (라이브 서비스 없음).

ollama.py(FakeOllamaClient)·langfuse_sink.py(FakeLangfuseClient) 단위테스트를 미러링한다.
실제 anthropic 라이브러리·네트워크·API 키에 의존하지 않는다 → CI hermetic.

검증 핵심(S5 위험 표면):
  - 모델 해석: CLOUD_MID→anthropic_model_mid, CLOUD_HIGH→anthropic_model_high (03a §A.0).
  - 호출 규약: messages.create(model/max_tokens/system/messages=[user]) — 샘플링 인자 없음.
  - 텍스트 추출: content 블록 중 type=="text"만 이어붙임(thinking/tool 제외, dict·객체 양형).
  - 로컬 거부: LOCAL 결정은 거부(OllamaProvider 담당).
  - 미설정: 키 없으면 configured=False·generate 시 명확한 오류(조용한 강등 금지).

설계 정본: docs/architecture/03a_l3_router_design.md §A.0·§C.1·§H 후속 4.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from whymath_backend.config import Settings
from whymath_backend.l3.interfaces import LLMProvider
from whymath_backend.l3.models import (
    CostTier,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
)
from whymath_backend.l3.providers.anthropic import (
    AnthropicProvider,
    _AnthropicClient,
    _build_default_client,
    _extract_text,
    resolve_cloud_model,
)


# ──────────────────────────────────────────────────────────────────────────
# 가짜 클라이언트 — anthropic.AsyncAnthropic의 messages.create·models.list만 모사
# ──────────────────────────────────────────────────────────────────────────
class _FakeMessages:
    def __init__(self, *, response: Any, raises: Exception | None = None) -> None:
        self._response = response
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            {
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        if self._raises is not None:
            raise self._raises
        return self._response


class _FakeModels:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self._raises = raises
        self.list_calls = 0

    async def list(self) -> Any:
        self.list_calls += 1
        if self._raises is not None:
            raise self._raises
        return {"data": [{"id": "claude-sonnet-4-6"}, {"id": "claude-opus-4-7"}]}


class FakeAnthropicClient:
    """`_AnthropicClient` 시임을 구조적으로 충족하는 가짜 클라이언트."""

    def __init__(
        self,
        *,
        message_response: Any = None,
        create_raises: Exception | None = None,
        list_raises: Exception | None = None,
    ) -> None:
        if message_response is None:
            message_response = _dict_message("원시 출력")
        self.messages = _FakeMessages(response=message_response, raises=create_raises)
        self.models = _FakeModels(raises=list_raises)


# ── 응답 형태 빌더 (dict·객체 양쪽 정규화 경로 테스트) ──
def _dict_message(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


class _Block:
    def __init__(self, type_: str, text: str = "") -> None:
        self.type = type_
        self.text = text


class _ObjMessage:
    def __init__(self, blocks: list[Any]) -> None:
        self.content = blocks


# ── 결정·설정 헬퍼 ──
def _cloud_decision(cost: CostTier) -> RoutingDecision:
    return RoutingDecision(
        cost_tier=cost,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="cloud",
        est_latency_ms=3000,
        est_cost_krw=10.0,
    )


def _local_decision() -> RoutingDecision:
    return RoutingDecision(
        cost_tier=CostTier.LOCAL,
        local_family=ModelFamily.MATH,
        local_model=LocalModelTier.FAST,
        mode="sync",
        reason="local",
        est_latency_ms=1010,
        est_cost_krw=0.0,
    )


def _model_settings() -> Settings:
    """모델 매핑을 결정적으로 검증하기 위한 센티넬 모델 ID Settings."""
    return Settings(
        anthropic_model_mid="model-mid-sentinel",
        anthropic_model_high="model-high-sentinel",
        anthropic_max_tokens=1234,
    )


def _configured_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"anthropic_api_key": SecretStr("sk-ant-test")}
    base.update(overrides)
    return Settings(**base)


def _unconfigured_settings() -> Settings:
    return Settings(anthropic_api_key=SecretStr(""))


# ──────────────────────────────────────────────────────────────────────────
# generate — 모델 해석 + 호출 규약
# ──────────────────────────────────────────────────────────────────────────
class TestGenerate:
    async def test_cloud_mid_resolves_to_mid_model(self) -> None:
        """CLOUD_MID → anthropic_model_mid로 호출, 원시 텍스트 반환."""
        client = FakeAnthropicClient(message_response=_dict_message("42"))
        provider = AnthropicProvider(client=client, settings=_model_settings())

        out = await provider.generate("2+2?", "system", _cloud_decision(CostTier.CLOUD_MID))

        assert out.text == "42"
        assert len(client.messages.calls) == 1
        call = client.messages.calls[0]
        assert call["model"] == "model-mid-sentinel"
        assert call["max_tokens"] == 1234
        assert call["system"] == "system"
        assert call["messages"] == [{"role": "user", "content": "2+2?"}]

    async def test_cloud_high_resolves_to_high_model(self) -> None:
        """CLOUD_HIGH → anthropic_model_high로 호출."""
        client = FakeAnthropicClient()
        provider = AnthropicProvider(client=client, settings=_model_settings())

        await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_HIGH))

        assert client.messages.calls[0]["model"] == "model-high-sentinel"

    async def test_default_model_ids_are_claude_aliases(self) -> None:
        """기본 설정에서 CLOUD_MID=Sonnet 4.6, CLOUD_HIGH=Opus 4.7 alias로 해석된다."""
        defaults = Settings()
        client_mid = FakeAnthropicClient()
        await AnthropicProvider(client=client_mid, settings=defaults).generate(
            "p", "s", _cloud_decision(CostTier.CLOUD_MID)
        )
        client_high = FakeAnthropicClient()
        await AnthropicProvider(client=client_high, settings=defaults).generate(
            "p", "s", _cloud_decision(CostTier.CLOUD_HIGH)
        )
        assert client_mid.messages.calls[0]["model"] == "claude-sonnet-4-6"
        assert client_high.messages.calls[0]["model"] == "claude-opus-4-7"

    async def test_local_decision_rejected(self) -> None:
        """LOCAL 결정은 거부(OllamaProvider 담당) — 호출 자체가 없어야 한다."""
        client = FakeAnthropicClient()
        provider = AnthropicProvider(client=client, settings=_model_settings())

        with pytest.raises(ValueError, match="클라우드 결정만"):
            await provider.generate("p", "s", _local_decision())
        assert client.messages.calls == []

    async def test_extract_text_from_object_blocks(self) -> None:
        """content가 객체 블록(.type/.text)이어도 텍스트 추출."""
        msg = _ObjMessage([_Block("text", "객체응답")])
        client = FakeAnthropicClient(message_response=msg)
        provider = AnthropicProvider(client=client, settings=_model_settings())

        out = await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))
        assert out.text == "객체응답"

    async def test_generate_unconfigured_raises(self) -> None:
        """키 미설정 + 클라이언트 미주입 → generate가 명확한 오류(조용한 강등 금지)."""
        provider = AnthropicProvider(settings=_unconfigured_settings())
        with pytest.raises(RuntimeError, match="API 키"):
            await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))

    async def test_json_schema_rejected(self) -> None:
        """S2-j: json_schema(문법 제약)는 명확히 거부 — plain messages는 제약 디코딩이 없다
        (조용한 무시 금지). 호출 자체가 없어야 한다."""
        client = FakeAnthropicClient()
        provider = AnthropicProvider(client=client, settings=_model_settings())

        with pytest.raises(RuntimeError, match="json_schema"):
            await provider.generate(
                "p", "s", _cloud_decision(CostTier.CLOUD_MID), json_schema={"type": "object"}
            )
        assert client.messages.calls == []


# ──────────────────────────────────────────────────────────────────────────
# 튜닝 노브 — effort/thinking/caching은 *설정된 경우에만* 전달 (기본 OFF, 03a §H#4)
# ──────────────────────────────────────────────────────────────────────────
class TestTuningKnobs:
    async def _call_kwargs(self, settings: Settings) -> dict[str, Any]:
        client = FakeAnthropicClient()
        provider = AnthropicProvider(client=client, settings=settings)
        await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))
        kwargs: dict[str, Any] = client.messages.calls[0]["kwargs"]
        return kwargs

    async def test_defaults_omit_all_tuning_args(self) -> None:
        """기본값(전부 OFF)이면 output_config·thinking·cache_control 키를 싣지 않는다."""
        kwargs = await self._call_kwargs(
            Settings(
                anthropic_effort="",
                anthropic_thinking=False,
                anthropic_prompt_caching=False,
            )
        )
        assert kwargs == {}

    async def test_effort_passed_when_set(self) -> None:
        kwargs = await self._call_kwargs(Settings(anthropic_effort="high"))
        assert kwargs["output_config"] == {"effort": "high"}
        assert "thinking" not in kwargs
        assert "cache_control" not in kwargs

    async def test_thinking_passed_when_enabled(self) -> None:
        kwargs = await self._call_kwargs(Settings(anthropic_thinking=True))
        assert kwargs["thinking"] == {"type": "adaptive"}
        assert "output_config" not in kwargs

    async def test_caching_passed_when_enabled(self) -> None:
        kwargs = await self._call_kwargs(Settings(anthropic_prompt_caching=True))
        assert kwargs["cache_control"] == {"type": "ephemeral"}

    async def test_all_three_together(self) -> None:
        kwargs = await self._call_kwargs(
            Settings(
                anthropic_effort="xhigh",
                anthropic_thinking=True,
                anthropic_prompt_caching=True,
            )
        )
        assert kwargs["output_config"] == {"effort": "xhigh"}
        assert kwargs["thinking"] == {"type": "adaptive"}
        assert kwargs["cache_control"] == {"type": "ephemeral"}

    async def test_temperature_omitted_by_default(self) -> None:
        """온도 미지정(기본) → messages.create에 temperature 키를 싣지 않는다(기존 동작)."""
        client = FakeAnthropicClient()
        provider = AnthropicProvider(client=client, settings=_model_settings())
        await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))
        assert "temperature" not in client.messages.calls[0]["kwargs"]

    async def test_temperature_passed_when_set(self) -> None:
        """온도 지정(S2-g 생성 다양성) → messages.create의 temperature 인자로 전달된다."""
        client = FakeAnthropicClient()
        provider = AnthropicProvider(client=client, settings=_model_settings())
        await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID), temperature=0.9)
        assert client.messages.calls[0]["kwargs"]["temperature"] == 0.9


# ──────────────────────────────────────────────────────────────────────────
# top_p (EOS-121 선결조건 A) — 좌석 간 샘플링 통제 수단
# ──────────────────────────────────────────────────────────────────────────
class TestTopP:
    """막는 것은 넷이다.

    ⓐ **기본값이 조용히 바뀌는 것** — 미지정인데 키가 실리면(특히 `None`이 실리면) 현 공급사
       기본값과 다른 값이 나가 저작 품질이 회귀한다. 그래서 "키가 아예 없는가"를 본다
       (있는데 null인 것과 **다르다** — `assert kwargs.get("top_p") is None`은 둘을 구분하지
       못해 변별력이 0이다).
    ⓑ **지정했는데 안 실리는 것** — 측정자가 "양 좌석을 맞췄다"고 믿는데 실제로는 아무 값도
       안 간 상태.
    ⓒ **temperature와 동시 지정이 호출까지 가는 것** — Anthropic API는 **모델과 무관하게**
       둘의 동시 지정을 400으로 거부한다(2026-09-19 라이브 90호출 전건 실측). 구조적 불가이므로
       `images`·`json_schema`·`seed`와 같은 부류로 **호출 전에 RuntimeError**를 던진다.
    ⓓ **한쪽을 조용히 버리는 것** — 버리면 400 대신 200이 오고 "설정했는데 아무 일도 없었다"가
       되어 원인 지목이 불가능해진다(조용한 무시 금지). 그래서 ⓒ가 *예외*지 *누락*이 아니다.
    """

    async def test_top_p_key_is_absent_by_default(self) -> None:
        """ⓐ 미지정(기본) → messages.create kwargs에 top_p **키 자체가 없다**(null 아님)."""
        client = FakeAnthropicClient()
        provider = AnthropicProvider(client=client, settings=_model_settings())
        await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))
        kwargs = client.messages.calls[0]["kwargs"]
        assert "top_p" not in kwargs

    async def test_top_p_passed_when_set_alone(self) -> None:
        """ⓑ temperature 없이 top_p만 지정 → `top_p=`로 **그 값 그대로** 전달된다."""
        client = FakeAnthropicClient()
        provider = AnthropicProvider(client=client, settings=_model_settings())
        await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID), top_p=0.95)
        kwargs = client.messages.calls[0]["kwargs"]
        assert kwargs["top_p"] == 0.95
        # 대조군 — 혼자 실릴 때 temperature 키가 따라붙지 않는다(우리가 기본값을 발명하지 않는다).
        assert "temperature" not in kwargs

    @pytest.mark.parametrize(
        "cost",
        [CostTier.CLOUD_MID, CostTier.CLOUD_HIGH],
        ids=["cloud_mid=Sonnet4.6", "cloud_high=Opus4.7"],
    )
    async def test_both_together_is_refused_before_the_call(self, cost: CostTier) -> None:
        """ⓒ 동시 지정 → RuntimeError. **Sonnet에서도** 그렇다는 것이 이 테스트의 요점이다.

        종전 계약은 이 제약을 Opus 한정으로 읽고 CLOUD_MID에서는 둘을 함께 실었다. 라이브
        회차가 그 오독의 대가를 치렀다(90호출 전건 400). 그래서 두 티어를 **같은 파라미터로**
        돌린다 — 한쪽만 막는 구현이면 반드시 한 케이스가 RED다.
        """
        client = FakeAnthropicClient()
        provider = AnthropicProvider(client=client, settings=_model_settings())
        with pytest.raises(RuntimeError, match="동시 지정"):
            await provider.generate("p", "s", _cloud_decision(cost), temperature=0.9, top_p=0.95)
        # 호출 0건 — "던지긴 하는데 이미 보낸 뒤"면 400이 그대로 난다(실패가 싸지 않다).
        assert client.messages.calls == []

    async def test_refusal_message_says_how_to_fix(self) -> None:
        """ⓒ 메시지가 *무엇을 어떻게 고칠지*를 담는다 — 측정자가 읽고 바로 고칠 수 있어야 한다.

        예외 타입만 맞고 본문이 비면 런북이 "왜 죽었는지"를 다시 소스에서 찾아야 한다.
        """
        client = FakeAnthropicClient()
        provider = AnthropicProvider(client=client, settings=_model_settings())
        with pytest.raises(RuntimeError) as excinfo:
            await provider.generate(
                "p", "s", _cloud_decision(CostTier.CLOUD_MID), temperature=0.9, top_p=0.95
            )
        message = str(excinfo.value)
        assert "둘 중 하나만" in message  # 처방
        assert "cannot both be specified" in message  # 공급사 원문(검색 가능한 지문)
        assert "0.9" in message and "0.95" in message  # 받은 값 — 어느 호출인지 특정된다

    async def test_temperature_alone_still_rides_on_cloud_high(self) -> None:
        """ⓓ 대조군 — Opus의 *단독* temperature 거부는 종전대로 **런타임 가드가 없다**.

        이 대조군이 없으면 "CLOUD_HIGH에서는 샘플링 인자를 전부 거부"하는 과잉 구현이 위
        테스트들을 통과한다. 단독 temperature는 모델 제약(ⓐ축)이라 호출부 계약으로 막는다 —
        이번 변경이 건드리는 것은 **API 계약**(동시 지정)뿐이다.
        """
        client = FakeAnthropicClient()
        provider = AnthropicProvider(client=client, settings=_model_settings())
        await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_HIGH), temperature=0.9)
        kwargs = client.messages.calls[0]["kwargs"]
        assert kwargs["temperature"] == 0.9
        assert "top_p" not in kwargs

    async def test_cloud_high_omits_both_when_unset(self) -> None:
        """ⓓ 대조군 — 아무것도 지정하지 않으면 두 키 다 없다(plain create·종전 동작)."""
        client = FakeAnthropicClient()
        provider = AnthropicProvider(client=client, settings=_model_settings())
        await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_HIGH))
        kwargs = client.messages.calls[0]["kwargs"]
        assert "top_p" not in kwargs
        assert "temperature" not in kwargs

    def test_module_docstring_separates_the_two_constraint_layers(self) -> None:
        """제약이 **두 층**이라는 사실이 문서에 남아 있는가 — 오독의 재발 방지선.

        ⓐ(Opus 한정 모델 제약)는 런타임 가드가 없으므로 경고문이 유일한 방어선이고,
        ⓑ(모델 무관 API 계약)는 가드가 있지만 *왜 가드가 있는지*가 없으면 다음 세션이
        "축마다 다른 정책"으로 읽고 되돌린다. 두 층이 함께 적혀 있어야 계약이 성립한다.
        """
        import whymath_backend.l3.providers.anthropic as anthropic_module

        doc = anthropic_module.__doc__ or ""
        assert "top_p" in doc
        assert "temperature" in doc
        assert "거부(400)" in doc
        # 모델 제약(Opus 단독)과 API 계약(모델 무관 동시 지정)이 **갈려** 적혀 있을 것.
        assert "동시에" in doc
        assert "Sonnet 4.6" in doc
        generate_doc = AnthropicProvider.generate.__doc__ or ""
        assert "top_p" in generate_doc
        assert "CLOUD_HIGH" in generate_doc
        assert "구조적 불가" in generate_doc


# ──────────────────────────────────────────────────────────────────────────
# _extract_text — content 블록 정규화 (dict·객체·엣지)
# ──────────────────────────────────────────────────────────────────────────
class TestExtractText:
    def test_joins_text_blocks_skips_non_text(self) -> None:
        """여러 text 블록은 이어붙이고 thinking/tool 등 비텍스트는 건너뛴다."""
        msg = {
            "content": [
                {"type": "thinking", "thinking": "속으로..."},
                {"type": "text", "text": "안녕"},
                {"type": "tool_use", "name": "x"},
                {"type": "text", "text": "하세요"},
            ]
        }
        assert _extract_text(msg) == "안녕하세요"

    def test_object_blocks(self) -> None:
        msg = _ObjMessage([_Block("thinking", "x"), _Block("text", "본문")])
        assert _extract_text(msg) == "본문"

    def test_no_content_attr_returns_empty(self) -> None:
        assert _extract_text(12345) == ""

    def test_content_not_list_returns_empty(self) -> None:
        assert _extract_text({"content": "not a list"}) == ""

    def test_text_block_without_text_value_skipped(self) -> None:
        """type=text이나 text 값이 없는(또는 비문자열) 블록은 건너뛴다."""
        msg = {
            "content": [
                {"type": "text"},
                {"type": "text", "text": 7},
                {"type": "text", "text": "ok"},
            ]
        }
        assert _extract_text(msg) == "ok"

    def test_empty_content_returns_empty(self) -> None:
        assert _extract_text({"content": []}) == ""

    def test_block_neither_object_nor_dict_and_text_block_without_text_attr(self) -> None:
        """객체도 dict도 아닌 블록, 그리고 type=text이나 .text 속성이 없는 블록은 건너뛴다."""

        class _TypeOnly:
            type = "text"  # text 타입이지만 .text 속성이 없는 객체(방어 경로)

        msg = {"content": [7, _TypeOnly()]}
        assert _extract_text(msg) == ""


# ──────────────────────────────────────────────────────────────────────────
# resolve_cloud_model — 티어 → 모델 ID 매핑
# ──────────────────────────────────────────────────────────────────────────
class TestResolveCloudModel:
    def test_mid_and_high(self) -> None:
        s = _model_settings()
        assert resolve_cloud_model(CostTier.CLOUD_MID, s) == "model-mid-sentinel"
        assert resolve_cloud_model(CostTier.CLOUD_HIGH, s) == "model-high-sentinel"

    def test_accepts_string_cost_tier(self) -> None:
        """use_enum_values=True 환경 대비 — 문자열 cost_tier도 정규화한다."""
        assert resolve_cloud_model("cloud_mid", _model_settings()) == "model-mid-sentinel"

    def test_local_rejected(self) -> None:
        with pytest.raises(ValueError, match="클라우드 티어에만"):
            resolve_cloud_model(CostTier.LOCAL, _model_settings())


# ──────────────────────────────────────────────────────────────────────────
# check_status — 구성·도달성 보고
# ──────────────────────────────────────────────────────────────────────────
class TestCheckStatus:
    async def test_configured_and_reachable(self) -> None:
        """주입 클라이언트 + models.list 성공 → configured·reachable True."""
        client = FakeAnthropicClient()
        provider = AnthropicProvider(client=client)

        st = await provider.check_status()

        assert st.configured is True
        assert st.reachable is True
        assert st.error is None
        assert client.models.list_calls == 1

    async def test_configured_unreachable_absorbs_error(self) -> None:
        """models.list 실패(인증·네트워크)는 흡수 → reachable=False + 사유."""
        client = FakeAnthropicClient(list_raises=ConnectionError("refused"))
        provider = AnthropicProvider(client=client)

        st = await provider.check_status()

        assert st.configured is True
        assert st.reachable is False
        assert st.error is not None
        assert "ConnectionError" in st.error

    async def test_unconfigured_reports_without_network(self) -> None:
        """키 미설정(클라이언트 미주입) → configured=False, 네트워크·클라이언트 없음."""
        provider = AnthropicProvider(settings=_unconfigured_settings())

        st = await provider.check_status()

        assert st.configured is False
        assert st.reachable is False
        assert st.error is None


# ──────────────────────────────────────────────────────────────────────────
# configured·지연 생성·기본 클라이언트
# ──────────────────────────────────────────────────────────────────────────
class TestConfiguredAndLazy:
    def test_injected_client_configured_true_regardless_of_keys(self) -> None:
        """주입 클라이언트가 있으면 키 미설정이어도 configured=True(DI 우선)."""
        provider = AnthropicProvider(
            client=FakeAnthropicClient(), settings=_unconfigured_settings()
        )
        assert provider.configured is True

    def test_unconfigured_settings_configured_false(self) -> None:
        provider = AnthropicProvider(settings=_unconfigured_settings())
        assert provider.configured is False

    def test_configured_settings_true(self) -> None:
        provider = AnthropicProvider(settings=_configured_settings())
        assert provider.configured is True

    def test_get_client_raises_when_unconfigured(self) -> None:
        """미설정 시 _get_client는 명확한 RuntimeError(조용한 강등 금지)."""
        provider = AnthropicProvider(settings=_unconfigured_settings())
        with pytest.raises(RuntimeError, match="API 키"):
            provider._get_client()

    def test_default_client_built_lazily_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """클라이언트 미주입 + 키 설정 → 첫 _get_client에서 1회 생성·재사용(빌더 monkeypatch)."""
        built: list[Settings] = []

        def _fake_builder(settings: Settings) -> Any:
            built.append(settings)
            return FakeAnthropicClient()

        monkeypatch.setattr(
            "whymath_backend.l3.providers.anthropic._build_default_client",
            _fake_builder,
        )
        provider = AnthropicProvider(settings=_configured_settings())
        c1 = provider._get_client()
        c2 = provider._get_client()
        assert c1 is c2
        assert len(built) == 1

    def test_resolved_settings_falls_back_to_global(self) -> None:
        from whymath_backend.config import get_settings

        get_settings.cache_clear()
        provider = AnthropicProvider()
        assert isinstance(provider._resolved_settings, Settings)

    async def test_build_default_client_constructs_real_async_anthropic(self) -> None:
        """_build_default_client가 실제 AsyncAnthropic을 생성한다(시임 충족·cast 경로).

        ollama.py/langfuse_sink.py가 실제 클라이언트를 생성해 기본 경로를 커버한 것을
        미러링한다. AsyncAnthropic 생성자는 네트워크를 타지 않는다(실제 호출 시 연결).
        잔여 httpx 클라이언트는 close()로 정리한다.
        """
        client = _build_default_client(_configured_settings())
        assert isinstance(client, _AnthropicClient)  # messages·models 보유
        close = getattr(client, "close", None)
        if close is not None:
            await close()


# ──────────────────────────────────────────────────────────────────────────
# Protocol 위생
# ──────────────────────────────────────────────────────────────────────────
def test_provider_satisfies_llm_provider_protocol() -> None:
    """AnthropicProvider는 LLMProvider Protocol을 충족한다(runtime_checkable)."""
    assert isinstance(AnthropicProvider(client=FakeAnthropicClient()), LLMProvider)


def test_fake_client_satisfies_seam_protocol() -> None:
    """가짜 클라이언트가 _AnthropicClient 시임을 구조적으로 충족(테스트 위생)."""
    assert isinstance(FakeAnthropicClient(), _AnthropicClient)


# ──────────────────────────────────────────────────────────────────────────
# 실측 usage 포착 (S1 게이트 ② — response.usage 토큰 + monotonic 지연)
# ──────────────────────────────────────────────────────────────────────────
class TestUsageCapture:
    async def test_dict_usage_captured(self) -> None:
        """dict 응답의 usage.input_tokens/output_tokens → GenerationResult.usage 실측."""
        msg = _dict_message("42") | {"usage": {"input_tokens": 12, "output_tokens": 34}}
        client = FakeAnthropicClient(message_response=msg)
        provider = AnthropicProvider(client=client, settings=_model_settings())

        out = await provider.generate("2+2?", "system", _cloud_decision(CostTier.CLOUD_MID))

        assert out.text == "42"
        assert out.usage is not None
        assert out.usage.input_tokens == 12
        assert out.usage.output_tokens == 34
        assert out.usage.latency_ms is not None and out.usage.latency_ms >= 0.0

    async def test_object_usage_captured(self) -> None:
        """pydantic 객체 스타일 usage(.input_tokens 속성)도 포착한다."""

        class _Usage:
            input_tokens = 7
            output_tokens = 9

        msg = _ObjMessage([_Block("text", "본문")])
        msg.usage = _Usage()  # type: ignore[attr-defined]
        client = FakeAnthropicClient(message_response=msg)
        provider = AnthropicProvider(client=client, settings=_model_settings())

        out = await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))

        assert out.usage is not None
        assert out.usage.input_tokens == 7
        assert out.usage.output_tokens == 9

    async def test_missing_usage_tokens_none_not_fabricated(self) -> None:
        """usage 없는 응답 → 토큰 None(지어내지 않음). 지연은 실측이라 항상 존재."""
        client = FakeAnthropicClient(message_response=_dict_message("42"))
        provider = AnthropicProvider(client=client, settings=_model_settings())

        out = await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))

        assert out.usage is not None
        assert out.usage.input_tokens is None
        assert out.usage.output_tokens is None
        assert out.usage.latency_ms is not None

    async def test_malformed_usage_values_coerced_to_none(self) -> None:
        """usage 값이 비정상 타입(str·bool·음수)이면 None으로 정규화(방어적)."""
        msg = _dict_message("42") | {"usage": {"input_tokens": "많이", "output_tokens": -5}}
        client = FakeAnthropicClient(message_response=msg)
        provider = AnthropicProvider(client=client, settings=_model_settings())

        out = await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))

        assert out.usage is not None
        assert out.usage.input_tokens is None
        assert out.usage.output_tokens is None


# ──────────────────────────────────────────────────────────────────────────
# 프롬프트 캐시 토큰 판독 (EOS-99 ① — 켰다는 사실 ≠ 적중했다는 사실)
#
# `anthropic_prompt_caching`을 켜면 요청에 `cache_control`이 실리지만, **적중 여부는
# 응답 usage에만 있다.** 이 두 필드를 안 읽으면 플래그를 켠 상태와 캐시가 실제로 작동하는
# 상태가 코드에서 구분되지 않는다(짧은 프리픽스는 최소 토큰 미만이라 조용히 무효).
# ──────────────────────────────────────────────────────────────────────────
class TestPromptCacheUsageCapture:
    async def test_dict_cache_tokens_captured(self) -> None:
        """dict usage의 캐시 2종을 실측 그대로 포착한다(적중 회차)."""
        msg = _dict_message("42") | {
            "usage": {
                "input_tokens": 20,
                "output_tokens": 5,
                "cache_read_input_tokens": 2048,
                "cache_creation_input_tokens": 0,
            }
        }
        provider = AnthropicProvider(
            client=FakeAnthropicClient(message_response=msg), settings=_model_settings()
        )

        out = await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))

        assert out.usage is not None
        assert out.usage.cache_read_input_tokens == 2048
        assert out.usage.cache_creation_input_tokens == 0

    async def test_object_cache_tokens_captured(self) -> None:
        """pydantic 객체 스타일 usage(실 SDK anthropic.types.Usage 형태)도 포착한다."""

        class _Usage:
            input_tokens = 11
            output_tokens = 3
            cache_read_input_tokens = 0
            cache_creation_input_tokens = 4096

        msg = _ObjMessage([_Block("text", "본문")])
        msg.usage = _Usage()  # type: ignore[attr-defined]
        provider = AnthropicProvider(
            client=FakeAnthropicClient(message_response=msg), settings=_model_settings()
        )

        out = await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))

        assert out.usage is not None
        assert out.usage.cache_read_input_tokens == 0
        assert out.usage.cache_creation_input_tokens == 4096

    async def test_absent_cache_fields_are_none_not_zero(self) -> None:
        """캐시 필드가 **없는** 응답 → None(미측정)이지 0(실측 0)이 아니다.

        이 방향이 이 태스크의 급소다. 부재를 0으로 접으면 캐시 개념이 없는 provider·구버전
        SDK 응답이 '적중 0%'로 보고되고, 그러면 '켰지만 작동 안 함' 신호가 상시 켜져 습관화된다.
        """
        msg = _dict_message("42") | {"usage": {"input_tokens": 12, "output_tokens": 34}}
        provider = AnthropicProvider(
            client=FakeAnthropicClient(message_response=msg), settings=_model_settings()
        )

        out = await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))

        assert out.usage is not None
        assert out.usage.input_tokens == 12  # 다른 축은 정상 판독(스캔 0건 방지)
        assert out.usage.cache_read_input_tokens is None
        assert out.usage.cache_creation_input_tokens is None

    async def test_malformed_cache_values_coerced_to_none(self) -> None:
        """캐시 값이 비정상 타입(str·bool·음수)이면 None — 토큰 축과 같은 방어 규약."""
        msg = _dict_message("42") | {
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "cache_read_input_tokens": True,
                "cache_creation_input_tokens": -7,
            }
        }
        provider = AnthropicProvider(
            client=FakeAnthropicClient(message_response=msg), settings=_model_settings()
        )

        out = await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))

        assert out.usage is not None
        assert out.usage.cache_read_input_tokens is None
        assert out.usage.cache_creation_input_tokens is None

    def test_sdk_surface_exposes_cache_fields(self) -> None:
        """실물 SDK의 `Usage`에 우리가 읽는 두 필드가 **실재**하는지 확인한다.

        CLAUDE.md "외부 SDK 표면을 시임(가짜) 테스트만으로 정합 선언 금지" — 위 테스트는
        전부 우리가 만든 가짜 응답이라, 필드 이름을 틀려도 자기들끼리 초록이다. SDK가 없는
        환경(hermetic 단위 CI)에서는 건너뛴다.
        """
        anthropic_types = pytest.importorskip("anthropic.types")

        fields = set(anthropic_types.Usage.model_fields)

        assert "cache_read_input_tokens" in fields
        assert "cache_creation_input_tokens" in fields
