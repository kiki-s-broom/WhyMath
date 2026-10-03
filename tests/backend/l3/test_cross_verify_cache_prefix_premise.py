"""cross_verify 프롬프트 캐싱 판정(OPS-104)의 **전제 동결** — 두 전제가 깨지면 판정을 다시 한다.

OPS-104의 판정은 "cross_verify 경로에서 `anthropic_prompt_caching`을 위한 코드 변경을 하지 않는다"이다
(`docs/reviews/ops104_cross_verify_cache_prefix_2026-10-03.md`). 그 판정은 **측정된 두 전제** 위에 서 있고,
전제는 코드가 바뀌면 조용히 거짓이 된다. 이 파일이 두 전제를 각각 고정한다.

  전제 ① 관점 12종의 system 프롬프트는 전부 최소 캐시 프리픽스(핀된 모델 중 가장 낮은 1024토큰)
         **미만**이다 — 근거는 UTF-8 바이트 상한(토큰은 바이트보다 많을 수 없다). 프롬프트가 커져 1024
         바이트에 닿으면 "위치를 고쳐도 조용히 무효"라는 판정이 더는 확정이 아니다.
  전제 ② `CrossVerifier.verify()`의 라우팅은 어떤 구독·난이도에서도 LOCAL이라 Anthropic 좌석의
         `messages.create`에 **도달하지 않는다**. 클라우드 경로가 열리면(예: 예산 > 0) 캐시 플래그가 이
         경로에 처음으로 의미를 갖게 되므로 판정을 다시 해야 한다.

**라이브 증거가 아니다**: 이 테스트는 네트워크·API 키 없이 돈다(ARCH-66). 실제 `count_tokens`·실제
`cache_read_input_tokens`는 측정하지 않았고 통과로 계상하지 않는다.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from whymath_backend.config import Settings
from whymath_backend.l3.cross_verify import (
    MISSING_CONDITION_PERSPECTIVES,
    MULTIPLE_VALID_ANSWERS_PERSPECTIVES,
    PROBABILITY_PERSPECTIVES,
    STATISTICAL_PERSPECTIVES,
    CrossVerifier,
    Perspective,
    ResidueSubject,
)
from whymath_backend.l3.interfaces import RecordingTraceSink
from whymath_backend.l3.models import CostTier, RoutingDecision
from whymath_backend.l3.providers.anthropic import AnthropicProvider
from whymath_backend.l3.router import DAILY_LIMIT_KRW, Router

# 핀된 모델별 최소 캐시 프리픽스 중 가장 낮은 값(Sonnet 4.6=1024 · Opus 4.7=2048 — 공개 문서 표를 옮긴
# 값, 라이브 미검증). 이 값 미만이면 두 모델 모두에서 '아래'다.
_LOWEST_PINNED_MIN_TOKENS = 1024

_ALL_PERSPECTIVES: tuple[Perspective, ...] = (
    *PROBABILITY_PERSPECTIVES,
    *STATISTICAL_PERSPECTIVES,
    *MISSING_CONDITION_PERSPECTIVES,
    *MULTIPLE_VALID_ANSWERS_PERSPECTIVES,
)

_SUBJECT = ResidueSubject(
    problem_id="wm-ops104",
    question_text="서로 구별되는 두 개의 주사위를 던질 때 눈의 합이 7일 확률은?",
    answer="1/6",
    answer_explanation="전체 36가지 중 6가지.",
    machine_model_ko="표본공간: 36가지.\n사건 A: 합이 7.\n확률 = 6/36.",
    machine_total=36,
    machine_favorable=6,
    authored_by="corpus:FULLY_GENERATED",
)


class TestPremiseOnePromptsBelowMinimum:
    """전제 ① — 12개 관점 system 프롬프트의 바이트 상한이 최소 캐시 프리픽스 미만이다."""

    def test_scan_is_not_vacuous(self) -> None:
        """스캔 0건은 실패다 — 관점 세트가 비거나 줄면 이 파일 전체가 공허하게 통과한다."""
        assert len(_ALL_PERSPECTIVES) == 12
        assert len({p.principle for p in _ALL_PERSPECTIVES}) == 12

    @pytest.mark.parametrize("perspective", _ALL_PERSPECTIVES, ids=lambda p: p.principle)
    def test_system_prompt_bytes_are_below_the_lowest_pinned_minimum(
        self, perspective: Perspective
    ) -> None:
        upper_bound_tokens = len(perspective.system_prompt.encode("utf-8"))
        assert upper_bound_tokens < _LOWEST_PINNED_MIN_TOKENS, (
            f"{perspective.principle}: system 프롬프트가 {upper_bound_tokens}바이트로 "
            f"{_LOWEST_PINNED_MIN_TOKENS}에 닿았다 — OPS-104 판정 전제 ①('위치를 고쳐도 조용히 "
            "무효')이 더는 확정이 아니다. docs/reviews/ops104_*.md 를 다시 판정하라."
        )

    def test_control_a_long_prompt_is_not_below(self) -> None:
        """대조군 — 검사식이 항상 통과하는 가짜가 아님을 보인다(1024바이트는 '아래'가 아니다)."""
        assert len(("a" * 1024).encode("utf-8")) >= _LOWEST_PINNED_MIN_TOKENS


class _RecordingMessages:
    """`messages.create`가 불린 요청을 기록하는 가짜 — 도달 여부를 직접 본다."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return {
            "content": [{"type": "text", "text": '{"total": 36, "favorable": 6}'}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _RecordingMessages()

    @property
    def models(self) -> Any:  # pragma: no cover - 헬스체크 시임(미사용)
        raise AssertionError("models.list는 이 테스트에서 불리지 않는다")


def _verifier(
    *, caching: bool, subscription: str = "free", difficulty: str = "medium"
) -> tuple[CrossVerifier, _RecordingMessages]:
    client = _FakeClient()
    provider = AnthropicProvider(client=client, settings=Settings(anthropic_prompt_caching=caching))
    verifier = CrossVerifier(
        provider,
        trace=RecordingTraceSink(),
        subscription=subscription,
        difficulty=difficulty,
    )
    return verifier, client.messages


def _cloud_decision() -> RoutingDecision:
    return RoutingDecision(
        cost_tier=CostTier.CLOUD_MID,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="ops104-control",
        est_latency_ms=3000,
        est_cost_krw=10.0,
    )


_SUBSCRIPTIONS = sorted({"free", *DAILY_LIMIT_KRW})
_DIFFICULTIES = ["easy", "medium", "hard", "very_hard"]


class TestPremiseTwoCloudPathUnreachable:
    """전제 ② — `CrossVerifier.verify()`는 Anthropic 좌석에 도달하지 않는다."""

    def test_subscription_axis_is_not_vacuous(self) -> None:
        assert len(_SUBSCRIPTIONS) >= 2  # 구독 표가 비면 아래 전수가 공허해진다

    @pytest.mark.parametrize("difficulty", _DIFFICULTIES)
    @pytest.mark.parametrize("subscription", _SUBSCRIPTIONS)
    def test_routing_is_local_for_every_subscription_and_difficulty(
        self, subscription: str, difficulty: str
    ) -> None:
        verifier, _ = _verifier(caching=True, subscription=subscription, difficulty=difficulty)
        decision = Router().route(verifier._routing_request())
        assert decision.cost_tier == CostTier.LOCAL.value, (
            f"{subscription}/{difficulty}: 라우팅이 {decision.cost_tier}가 됐다 — cross_verify가 "
            "클라우드로 갈 수 있게 됐다. OPS-104 판정 전제 ②가 깨졌으니 캐시 판정을 다시 하라."
        )

    @pytest.mark.parametrize("caching", [True, False])
    def test_verify_never_reaches_messages_create(self, caching: bool) -> None:
        """Anthropic 좌석을 직결해도 verify()는 `messages.create`를 한 번도 부르지 않는다."""
        verifier, messages = _verifier(caching=caching)
        verifier.verify(_SUBJECT)
        assert messages.requests == []

    def test_control_cloud_decision_does_reach_messages_create(self) -> None:
        """대조군 — 클라우드 결정이 주어지면 같은 가짜가 요청을 *본다*(도달 검사가 항상 0이 아님)."""
        import asyncio

        verifier, messages = _verifier(caching=True)
        perspective = PROBABILITY_PERSPECTIVES[0]
        asyncio.run(verifier._run_perspective(perspective, _SUBJECT, _cloud_decision()))
        assert len(messages.requests) == 1
        system = messages.requests[0]["system"]
        assert isinstance(system, list)
        assert system[0]["cache_control"] == {"type": "ephemeral"}

    def test_control_caching_off_sends_plain_string_system(self) -> None:
        """대조군 — 캐싱 OFF(기본)는 같은 경로에서 system 문자열·표시 없음(기본값 회귀 0)."""
        import asyncio

        verifier, messages = _verifier(caching=False)
        perspective = replace(PROBABILITY_PERSPECTIVES[0])
        asyncio.run(verifier._run_perspective(perspective, _SUBJECT, _cloud_decision()))
        assert len(messages.requests) == 1
        assert isinstance(messages.requests[0]["system"], str)
        assert "cache_control" not in messages.requests[0]
