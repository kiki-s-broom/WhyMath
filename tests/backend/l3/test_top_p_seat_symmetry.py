"""`top_p` 좌석 대칭 계약 동결 — EOS-121 선결조건 A (라이브 0·hermetic).

**왜 별도 파일인가**: 각 프로바이더 테스트 파일은 *자기 좌석*만 본다. 그런데 EOS-121이
닫으려는 교란 변수는 "한 좌석이 top_p를 싣는가"가 아니라 **"두 좌석이 같은 값을 싣는가"**다.
그 판정은 두 좌석의 전송 직전 페이로드를 *같은 테스트 안에서 나란히 놓아야* 성립한다 —
한쪽만 보면 반쪽이 조용히 갈라져도 양쪽 파일이 모두 초록이다.

배경(`docs/ops/eos121_seat_generation_diversity_precheck.md` §1): 착지 전 저장소에는 `top_p`를
페이로드에 싣는 코드가 **0건**이었고, 두 공급사 기본값이 같다는 근거도 다르다는 근거도 없었다.
즉 "같음"도 "다름"도 아닌 **통제되지 않음**이라는 3번째 상태였다(CLAUDE.md「모른다 ≠ 아니다」).

이 파일이 막는 것 셋(전부 실패 주입으로 RED 확인):
  ⓐ **기본값의 조용한 변경** — 미지정인데 페이로드에 키가 생기는 것. `None`이 실리는 것도
     포함한다(공급사 기본값 ≠ null). 그래서 `is None` 비교가 아니라 **키 부재**를 본다.
  ⓑ **좌석 비대칭** — 같은 값을 줬는데 한 좌석에만 실리거나 값이 달라지는 것.
  ⓒ **CLOUD_HIGH 정책 분기** — Opus 4.7은 temperature/top_p를 함께 400으로 거부한다. 이
     저장소의 기존 대응은 *호출부 계약*(런타임 거부 없음)이므로 top_p에만 다른 정책을
     발명하지 않는다. 동시에 조용히 버리지도 않는다(조용한 무시 금지).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from whymath_backend.config import Settings
from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
)
from whymath_backend.l3.providers.anthropic import AnthropicProvider
from whymath_backend.l3.providers.openrouter import OpenRouterProvider

# 측정 회차가 양 좌석에 동일하게 줄 값(대표값 — 특정 수치 자체에 의미는 없다).
_TOP_P = 0.95


# ──────────────────────────────────────────────────────────────────────────
# 좌석 시임 — 전송 직전 페이로드를 **그대로** 보관한다(관측 지점)
# ──────────────────────────────────────────────────────────────────────────
class _FakeMessages:
    def __init__(self) -> None:
        self.kwargs: list[dict[str, Any]] = []

    async def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Any:
        self.kwargs.append(dict(kwargs))
        return {"content": [{"type": "text", "text": "답"}]}


class _FakeModels:
    async def list(self) -> Any:
        return {"data": []}


class _FakeAnthropicClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()
        self.models = _FakeModels()


class _RecordingTransport:
    """OpenRouter 전송 시임 — payload를 그대로 보관."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def post_chat(
        self,
        url: str,
        *,
        headers: Any,
        payload: Any,
        timeout_s: float,
    ) -> Any:
        self.payloads.append(dict(payload))
        return {
            "choices": [{"message": {"role": "assistant", "content": "답"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }


def _cloud_decision(cost: CostTier = CostTier.CLOUD_MID) -> RoutingDecision:
    return RoutingDecision(
        cost_tier=cost,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="cloud escalation",
        est_latency_ms=2000,
        est_cost_krw=1.0,
    )


async def _anthropic_payload(**call_kwargs: Any) -> dict[str, Any]:
    """Anthropic 좌석에 1회 호출하고 messages.create가 받은 **선택 인자 dict**를 돌려준다."""
    client = _FakeAnthropicClient()
    provider = AnthropicProvider(
        client=client,  # type: ignore[arg-type]
        settings=Settings(anthropic_api_key=SecretStr("sk-ant-test")),
    )
    decision = call_kwargs.pop("decision", _cloud_decision())
    await provider.generate("p", "s", decision, **call_kwargs)
    return client.messages.kwargs[0]


async def _openrouter_payload(**call_kwargs: Any) -> dict[str, Any]:
    """OpenRouter 좌석에 1회 호출하고 전송 직전 payload를 돌려준다."""
    transport = _RecordingTransport()
    provider = OpenRouterProvider(
        transport=transport,  # type: ignore[arg-type]
        settings=Settings(
            openrouter_api_key=SecretStr("sk-or-test"),
            openrouter_allowed_providers=("deepinfra",),
        ),
    )
    decision = call_kwargs.pop("decision", _cloud_decision())
    await provider.generate("p", "s", decision, **call_kwargs)
    return transport.payloads[0]


# ──────────────────────────────────────────────────────────────────────────
# ⓐ 기본값 — 미전송(키 부재). "있는데 null"과 **다르다**
# ──────────────────────────────────────────────────────────────────────────
class TestDefaultIsNoTransmission:
    """기본값을 바꾸지 않는 것이 이 변경의 **가장 중요한 제약**이다.

    top_p를 무조건 명시 전송하면 현재 각 공급사 기본값과 다른 값이 나가 **기존 저작 품질이
    조용히 바뀐다**(회귀). 회귀는 로그를 남기지 않으므로 이 단언들이 유일한 방어선이다.
    """

    async def test_anthropic_omits_the_key_entirely(self) -> None:
        payload = await _anthropic_payload()
        assert "top_p" not in payload

    async def test_openrouter_omits_the_key_entirely(self) -> None:
        payload = await _openrouter_payload()
        assert "top_p" not in payload

    async def test_absence_is_not_the_same_as_null(self) -> None:
        """`payload.get("top_p") is None`으로는 둘을 구분하지 못한다는 사실 자체를 동결한다.

        이 단언이 없으면 `payload["top_p"] = None`으로 바꾸는 회귀가 *`is None` 형태의*
        느슨한 검사를 그대로 통과한다 — 그리고 공급사에는 기본값이 아니라 null이 나간다.
        """
        anthropic_payload = await _anthropic_payload()
        openrouter_payload = await _openrouter_payload()
        for payload in (anthropic_payload, openrouter_payload):
            assert payload.get("top_p") is None  # 느슨한 검사는 통과하고
            assert "top_p" not in payload  # 엄밀한 검사가 실제 계약이다


# ──────────────────────────────────────────────────────────────────────────
# ⓑ 좌석 대칭 — 같은 값을 주면 두 좌석에 같은 값이 실린다
# ──────────────────────────────────────────────────────────────────────────
class TestSeatSymmetry:
    async def test_same_value_lands_in_both_seats(self) -> None:
        """EOS-121이 실제로 필요로 하는 것 — *한 번 지정해 두 좌석을 맞출 수 있는가*."""
        anthropic_payload = await _anthropic_payload(top_p=_TOP_P)
        openrouter_payload = await _openrouter_payload(top_p=_TOP_P)
        assert anthropic_payload["top_p"] == _TOP_P
        assert openrouter_payload["top_p"] == _TOP_P
        # 두 좌석이 *서로* 같은지를 직접 본다 — 한쪽만 보면 비대칭이 안 보인다.
        assert anthropic_payload["top_p"] == openrouter_payload["top_p"]

    async def test_presence_is_symmetric_in_both_directions(self) -> None:
        """실림/안 실림 여부 자체가 두 좌석에서 일치한다(지정·미지정 양방향).

        방향이 하나뿐이면 "항상 싣는다"는 과잉 구현이 통과한다 — 미지정 방향이 대조군이다.
        """
        set_pair = (await _anthropic_payload(top_p=_TOP_P), await _openrouter_payload(top_p=_TOP_P))
        unset_pair = (await _anthropic_payload(), await _openrouter_payload())
        assert [("top_p" in p) for p in set_pair] == [True, True]
        assert [("top_p" in p) for p in unset_pair] == [False, False]

    async def test_temperature_axis_is_untouched(self) -> None:
        """top_p를 실어도 temperature 축은 종전 그대로다 — 두 축이 서로를 덮지 않는다.

        이 변경의 착지 전 실측에서 temperature는 **이미 통제되고 있었다**(양 좌석 명시 0.9).
        top_p를 붙이면서 그것을 깨뜨리면 닫혀 있던 축이 도로 열린다.
        """
        anthropic_payload = await _anthropic_payload(temperature=0.9, top_p=_TOP_P)
        openrouter_payload = await _openrouter_payload(temperature=0.9, top_p=_TOP_P)
        assert anthropic_payload["temperature"] == openrouter_payload["temperature"] == 0.9
        assert anthropic_payload["top_p"] == openrouter_payload["top_p"] == _TOP_P


# ──────────────────────────────────────────────────────────────────────────
# ⓒ CLOUD_HIGH — Opus 4.7의 400 거부 경로
# ──────────────────────────────────────────────────────────────────────────
class TestCloudHighRejectionPath:
    """Opus 4.7은 `temperature`/`top_p`/`top_k`/`budget_tokens`를 **거부(400)** 한다.

    이 저장소의 기존 대응(temperature)은 런타임 가드가 아니라 **호출부 계약 + 모듈 경고문**
    이다. top_p에만 다른 정책(예 CLOUD_HIGH에서 RuntimeError)을 새로 만들지 않는다 — 같은
    API 제약을 두 방식으로 다루면 호출부가 어느 쪽이 계약인지 알 수 없게 되기 때문이다.
    그렇다고 **조용히 버리지도 않는다**: 버리면 400 대신 "설정했는데 아무 일도 없다"가 되어
    원인 지목이 불가능해진다(조용한 무시 금지).
    """

    async def test_cloud_high_treats_top_p_exactly_like_temperature(self) -> None:
        payload = await _anthropic_payload(
            decision=_cloud_decision(CostTier.CLOUD_HIGH), temperature=0.9, top_p=_TOP_P
        )
        assert payload["top_p"] == _TOP_P
        # 정책 대칭 — 한쪽에만 거부 가드를 넣거나 한쪽만 버리면 여기서 RED.
        assert ("top_p" in payload) == ("temperature" in payload)

    async def test_cloud_high_stays_plain_when_unset(self) -> None:
        """대조군 — 미지정이면 CLOUD_HIGH도 종전처럼 plain create다(두 키 모두 부재)."""
        payload = await _anthropic_payload(decision=_cloud_decision(CostTier.CLOUD_HIGH))
        assert "top_p" not in payload
        assert "temperature" not in payload


# ──────────────────────────────────────────────────────────────────────────
# 생성기 축 — 측정자가 실제로 쥐는 손잡이
# ──────────────────────────────────────────────────────────────────────────
class _KwargsRecordingProvider:
    """`generate`가 받은 **키워드 인자를 그대로** 보관하는 대역.

    기본값 있는 파라미터로 받으면 "안 왔다"와 "None이 왔다"가 둘 다 None으로 보여 변별력이
    0이 된다 — 그래서 `**kwargs`로 받는다.
    """

    def __init__(self, response: str = "{}") -> None:
        self._response = response
        self.kwargs: list[dict[str, Any]] = []

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision, **kwargs: Any
    ) -> GenerationResult:
        self.kwargs.append(dict(kwargs))
        return GenerationResult(self._response)


def _local_decision() -> RoutingDecision:
    return RoutingDecision(
        cost_tier=CostTier.LOCAL,
        local_family=ModelFamily.GENERAL,
        local_model=LocalModelTier.FAST,
        mode="sync",
        reason="local",
        est_latency_ms=1010,
        est_cost_krw=0.0,
    )


@pytest.mark.parametrize(
    ("kwargs", "expect_key", "expect_value"),
    [
        pytest.param({}, False, None, id="기본값=미전송"),
        pytest.param({"top_p": _TOP_P}, True, _TOP_P, id="명시=전송"),
    ],
)
def test_generator_passes_top_p_only_when_explicitly_set(
    kwargs: dict[str, Any], expect_key: bool, expect_value: float | None
) -> None:
    """생성기 기본값은 **None**이다 — temperature(0.9)와 달리 기본값을 박지 않는다.

    이유는 회귀 방어다: 생성기가 기본으로 top_p를 실으면 기존 저작 배치 전부의 샘플링이
    조용히 바뀐다. 측정자가 명시할 때만 실려야 "설정을 맞춘 뒤 재측정"이라는 처방이 성립한다.
    """
    provider = _KwargsRecordingProvider()
    generator = LLMEquivalentProblemGenerator(provider, **kwargs)  # type: ignore[arg-type]
    # `_invoke`는 sync 경계다(내부에서 전용 루프를 돌린다) — 이 테스트가 `async def`면
    # "Cannot run the event loop while another loop is running"으로 실패한다.
    generator._invoke("프롬프트", _local_decision(), seed=None)

    call = provider.kwargs[0]
    assert ("top_p" in call) is expect_key
    if expect_key:
        assert call["top_p"] == expect_value
    # 온도는 어느 경우에도 종전 기본값(0.9)이 그대로 실린다 — 새 인자가 기존 축을 건드리지 않는다.
    assert call["temperature"] == 0.9


def test_generator_input_snapshot_records_top_p() -> None:
    """실제 반영된 샘플링 신호는 재현 스냅샷에 남는다 — "맞췄다"의 사후 증거.

    미지정이면 `None`으로 기록된다(키를 빼지 않는다): 키 부재는 *구판 기록*을 뜻해야 하고,
    null은 *이번 회차에 안 보냈다*를 뜻해야 구분이 선다.
    """
    from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
    from whymath_backend.schema.enums import AnswerFormat

    spec = EquivalenceSpec(
        achievement_standard_codes=frozenset({"[12미적01-01]"}),
        target_misconception_ids=frozenset(),
        difficulty_overall=3.0,
        answer_format=AnswerFormat.자연수,
    )
    unset = LLMEquivalentProblemGenerator(_KwargsRecordingProvider())._input_snapshot(spec, "p")  # type: ignore[arg-type]
    assert unset["top_p"] is None

    tuned = LLMEquivalentProblemGenerator(
        _KwargsRecordingProvider(),  # type: ignore[arg-type]
        top_p=_TOP_P,
    )._input_snapshot(spec, "p")
    assert tuned["top_p"] == _TOP_P
