"""`top_p` 좌석 계약 동결 — EOS-121 선결조건 A + 라이브 정정 (라이브 0·hermetic).

**왜 별도 파일인가**: 각 프로바이더 테스트 파일은 *자기 좌석*만 본다. 그런데 EOS-121이
닫으려던 교란 변수는 "한 좌석이 top_p를 싣는가"가 아니라 **"두 좌석이 같은 값을 싣는가"**였다.
그 판정은 두 좌석의 전송 직전 페이로드를 *같은 테스트 안에서 나란히 놓아야* 성립한다 —
한쪽만 보면 반쪽이 조용히 갈라져도 양쪽 파일이 모두 초록이다.

**라이브 정정(2026-09-19)**: 그 대칭은 **저작 경로에서 성립하지 않는다.** Anthropic Messages
API가 `temperature`와 `top_p`의 **동시 지정**을 모델과 무관하게 400으로 거부하는데
(`temperature` and `top_p` cannot both be specified for this model), 저작 경로는
temperature=0.9를 항상 싣는다. 실측: anthropic 좌석 90호출 전건 `generation_failed`.
따라서 선결조건 A의 원 처방("양 좌석에 동일 명시 전송해 축을 닫는다")은 **구조적으로 불가능**
하며, 측정은 양 좌석 **모두 미전송**(각 공급사 기본값)으로 돈다 — "닫았다"가 아니라
**"대칭이되 통제되지 않음"**이다(`docs/ops/eos121_seat_generation_diversity_precheck.md` §1·§4).

이 파일이 막는 것 넷(전부 실패 주입으로 RED 확인):
  ⓐ **기본값의 조용한 변경** — 미지정인데 페이로드에 키가 생기는 것. `None`이 실리는 것도
     포함한다(공급사 기본값 ≠ null). 그래서 `is None` 비교가 아니라 **키 부재**를 본다.
  ⓑ **좌석 비대칭(top_p 단독)** — 같은 값을 줬는데 한 좌석에만 실리거나 값이 달라지는 것.
     이 축은 정정 후에도 그대로 성립한다(temperature가 없으면 anthropic도 top_p를 싣는다).
  ⓒ **동시 지정이 호출까지 가는 것** — anthropic은 **거부**하고 openrouter는 **싣는다**.
     이 비대칭 자체가 정정의 핵심 사실이라 여기서 나란히 동결한다.
  ⓓ **저작 경로에서 그 조합이 조용히 성립한다고 믿는 것** — 생성기는 temperature를 항상
     실으므로 `top_p=`를 준 생성기 + anthropic 좌석은 **반드시** 터진다. 프로바이더 단독
     테스트만으로는 "저작 경로가 실제로 무엇을 보내는가"를 모르므로 생성기 축에서 따로 잰다.
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
# ⓑ 좌석 대칭 — top_p **단독**이면 같은 값이 두 좌석에 실린다
# ──────────────────────────────────────────────────────────────────────────
class TestSeatSymmetryForTopPAlone:
    """temperature를 함께 주지 않는 한, top_p 축의 좌석 대칭은 그대로 성립한다.

    정정이 무효화한 것은 *저작 경로에서의* 통제이지 *프로바이더의 top_p 전송*이 아니다.
    둘을 뭉뚱그리면 "anthropic은 top_p를 못 싣는다"는 과잉 일반화가 생긴다.
    """

    async def test_same_value_lands_in_both_seats(self) -> None:
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

    async def test_temperature_axis_is_untouched_when_alone(self) -> None:
        """temperature **단독** 축은 종전 그대로 두 좌석 대칭이다 — 이번 정정이 그것을 깨지 않는다.

        착지 전 실측에서 temperature는 **이미 통제되고 있었다**(양 좌석 명시 0.9). 동시 지정을
        막으면서 이 축까지 건드리면 닫혀 있던 유일한 축이 도로 열린다.
        """
        anthropic_payload = await _anthropic_payload(temperature=0.9)
        openrouter_payload = await _openrouter_payload(temperature=0.9)
        assert anthropic_payload["temperature"] == openrouter_payload["temperature"] == 0.9
        assert "top_p" not in anthropic_payload
        assert "top_p" not in openrouter_payload


# ──────────────────────────────────────────────────────────────────────────
# ⓒ 동시 지정 — 좌석이 **갈린다**. 이 비대칭이 정정의 핵심 사실이다
# ──────────────────────────────────────────────────────────────────────────
class TestSimultaneousSpecificationSplitsTheSeats:
    """`temperature` + `top_p`를 함께 주면 anthropic은 거부하고 openrouter는 싣는다.

    두 좌석을 **같은 테스트 안에** 나란히 두는 이유: 한쪽만 보면 "anthropic이 까다롭다"까지만
    읽히고, *openrouter에서는 되기 때문에* 측정을 대칭으로 맞출 수 없다는 결론이 안 나온다.
    그 결론이 런북·사전실측 정정의 근거다.
    """

    @pytest.mark.parametrize(
        "cost",
        [CostTier.CLOUD_MID, CostTier.CLOUD_HIGH],
        ids=["cloud_mid=Sonnet4.6", "cloud_high=Opus4.7"],
    )
    async def test_anthropic_refuses_before_sending(self, cost: CostTier) -> None:
        """모델과 무관하다 — Sonnet에서도 거부다(오독의 진원지가 바로 이 칸이었다)."""
        with pytest.raises(RuntimeError, match="동시 지정"):
            await _anthropic_payload(decision=_cloud_decision(cost), temperature=0.9, top_p=_TOP_P)

    async def test_openrouter_accepts_both(self) -> None:
        """대조군 — 제약이 Anthropic 한정임을 **실측 대칭점으로** 고정한다.

        이 단언이 없으면 "둘의 동시 지정은 원래 안 되는 것"이라는 과잉 일반화가 통과하고,
        그러면 openrouter 좌석의 `--top-p`까지 막는 구현도 초록이 된다(과잉 차단).
        """
        payload = await _openrouter_payload(temperature=0.9, top_p=_TOP_P)
        assert payload["temperature"] == 0.9
        assert payload["top_p"] == _TOP_P


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


# ──────────────────────────────────────────────────────────────────────────
# ⓓ 저작 경로 — 생성기 + anthropic 좌석 + top_p 는 **반드시** 터진다
# ──────────────────────────────────────────────────────────────────────────
def test_generator_with_top_p_cannot_run_on_the_anthropic_seat() -> None:
    """이것이 라이브 회차 90건을 죽인 조합 그 자체다 — 시임이 아니라 *실제 프로바이더*로 잰다.

    `_KwargsRecordingProvider`는 무엇이든 받으므로 위 생성기 테스트들은 이 결함을 볼 수 없었다
    (그래서 라이브에서만 드러났다 — CLAUDE.md「외부 SDK 표면을 시임 테스트만으로 정합 선언
    금지」의 *파라미터 조합* 축). 여기서는 생성기에 **진짜 AnthropicProvider**를 물려
    "저작 경로가 실제로 내보내는 조합"을 재현한다.

    생성기가 temperature(기본 0.9)를 *항상* 싣는다는 것이 이 단언의 전제이고, 그 전제는 아래
    대조군이 지킨다 — temperature를 빼는 회귀가 들어오면 대조군이 RED다.
    """
    client = _FakeAnthropicClient()
    provider = AnthropicProvider(
        client=client,  # type: ignore[arg-type]
        settings=Settings(anthropic_api_key=SecretStr("sk-ant-test")),
    )
    generator = LLMEquivalentProblemGenerator(provider, top_p=_TOP_P)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="동시 지정"):
        generator._invoke("프롬프트", _cloud_decision(), seed=None)
    # 호출 0건 — 실패는 전송 **전에** 나야 90번 반복되지 않는다.
    assert client.messages.kwargs == []


def test_generator_without_top_p_runs_on_the_anthropic_seat() -> None:
    """대조군 — top_p를 안 주면 같은 좌석이 종전대로 돈다(temperature만 실린다).

    이 대조군이 없으면 "생성기 + anthropic이면 무조건 거부"하는 과잉 구현이 위 테스트를
    통과한다. 그리고 그 과잉 구현은 **저작 배치 전체를 멈춘다**(EOS-118 회차와 같은 조건조차
    못 돌린다) — 정정의 처방이 "top_p를 빼고 돈다"이므로 이 방향이 반드시 살아 있어야 한다.
    """
    client = _FakeAnthropicClient()
    provider = AnthropicProvider(
        client=client,  # type: ignore[arg-type]
        settings=Settings(anthropic_api_key=SecretStr("sk-ant-test")),
    )
    generator = LLMEquivalentProblemGenerator(provider)  # type: ignore[arg-type]
    generator._invoke("프롬프트", _cloud_decision(), seed=None)
    sent = client.messages.kwargs[0]
    assert sent["temperature"] == 0.9  # 저작 경로가 temperature를 항상 싣는다는 전제
    assert "top_p" not in sent
