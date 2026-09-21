"""ARCH-58 — genlog의 `model_name`이 클라우드 좌석 셀렉터를 따르는가.

**상환하는 사고**(2026-09-18 Phaiakes9 라이브 1회차): OpenRouter 좌석으로 돈 저작 회차의
genlog가 `model_name=claude-sonnet-4-6` 5건을 적었다. 실행은 정상이었다 — 캐시 텔레메트리가
OpenRouter 0/5 · Anthropic 5/5로 갈렸고(AnthropicProvider가 양쪽을 서빙했다면 양쪽 다
실렸어야 한다), 좌석 재검사도 `OpenRouterProvider`였다. **기록만 거짓이었다.**

원인은 `model_name_for_decision`이 CLOUD_* 티어에서 `anthropic_model_mid/high`를 무조건
읽은 것이고, 그 전제는 `ARCH-57`이 셀렉터를 도입하기 전에는 참이었다. 슬롯을 셀렉터로
바꾸면서 이 함수를 같이 고치지 않은 것이 누락이다.

**왜 기존 테스트가 못 잡았나**: `tests/backend/l3/test_generation_log_wiring.py`는 기대값을
`model_name_for_decision(...)` 자신으로 계산한다(`assert log.model_name ==
model_name_for_decision(decision)`). 배선은 검사하지만 **값이 맞는가는 동어반복**이라 이
회귀를 구조적으로 볼 수 없다. 그래서 여기서는 **실값 문자열**을 단언한다.

hermetic: `Settings`와 순수 함수만 — 네트워크·키·DB 0.
"""

from __future__ import annotations

import pytest

from whymath_backend.config import Settings
from whymath_backend.l3.models import CostTier, RoutingDecision
from whymath_backend.l3.pregenerate.provenance_bridge import model_name_for_decision

_SECRET = "x" * 32


def _settings(seat: str) -> Settings:
    return Settings(jwt_secret_key=_SECRET, cloud_provider=seat)  # type: ignore[arg-type]


def _cloud_decision(tier: CostTier) -> RoutingDecision:
    """클라우드 결정 최소 구성 — 이름 해석만 보므로 나머지 축은 임의의 유효값이다.

    `est_latency_ms`는 필수 필드라 값을 준다(이 함수의 판정과 무관하며, 그 사실을 여기
    적어 두는 것은 다음 사람이 이 숫자에 의미를 찾지 않게 하기 위해서다).
    """
    return RoutingDecision(cost_tier=tier, est_latency_ms=1000)


@pytest.mark.parametrize("tier", [CostTier.CLOUD_MID, CostTier.CLOUD_HIGH])
def test_default_seat_still_reports_anthropic_pin(tier: CostTier) -> None:
    """대조군 — 기본 좌석(anthropic)에서는 종전과 **같은 값**이다(과잉 수정 방지).

    이 단언이 없으면 "전부 openrouter로 계상"하는 잘못된 수정도 아래 테스트들을 통과한다.
    """
    settings = _settings("anthropic")
    expected = (
        settings.anthropic_model_mid
        if tier is CostTier.CLOUD_MID
        else settings.anthropic_model_high
    )
    assert model_name_for_decision(_cloud_decision(tier), settings=settings) == expected


@pytest.mark.parametrize("tier", [CostTier.CLOUD_MID, CostTier.CLOUD_HIGH])
def test_openrouter_seat_reports_openrouter_pin_not_anthropic(tier: CostTier) -> None:
    """이번 회귀 그 자체 — openrouter 좌석인데 anthropic 핀을 적으면 red.

    **실값**을 단언한다(함수 자신으로 기대값을 만들지 않는다 — 그러면 동어반복이라 어떤
    값을 돌려줘도 통과한다. 기존 `test_generation_log_wiring.py`가 정확히 그 형태였고 이
    회귀를 못 봤다).
    """
    settings = _settings("openrouter")
    actual = model_name_for_decision(_cloud_decision(tier), settings=settings)
    expected = (
        settings.openrouter_model_mid
        if tier is CostTier.CLOUD_MID
        else settings.openrouter_model_high
    )
    assert actual == expected
    assert actual != settings.anthropic_model_mid, (
        "openrouter 좌석인데 anthropic 핀이 기록된다 — 2026-09-18 회귀 재발. "
        "출처 로그가 조용히 틀린 값을 적는 상태이며, 없는 기록보다 나쁘다."
    )


@pytest.mark.parametrize("tier", [CostTier.CLOUD_MID, CostTier.CLOUD_HIGH])
def test_deepseek_seat_reports_deepseek_pin(tier: CostTier) -> None:
    """세 번째 좌석도 같은 규약 — 두 좌석만 고치고 하나를 빠뜨리는 형태를 막는다."""
    settings = _settings("deepseek")
    expected = (
        settings.deepseek_model_mid if tier is CostTier.CLOUD_MID else settings.deepseek_model_high
    )
    assert model_name_for_decision(_cloud_decision(tier), settings=settings) == expected


def test_mid_and_high_are_distinct_per_seat() -> None:
    """mid/high 축이 실제로 갈라진다 — 한쪽만 고치고 다른 쪽을 방치하는 형태의 픽스처.

    두 값이 같은 좌석이라면 이 테스트가 그 좌석을 건너뛴다고 적는다(그래야 픽스처가 그 절을
    실제로 밟는지 다음 사람이 안다).
    """
    checked = 0
    for seat in ("anthropic", "openrouter", "deepseek"):
        settings = _settings(seat)
        mid = model_name_for_decision(_cloud_decision(CostTier.CLOUD_MID), settings=settings)
        high = model_name_for_decision(_cloud_decision(CostTier.CLOUD_HIGH), settings=settings)
        if mid != high:
            checked += 1
    assert checked >= 1, (
        "어느 좌석에서도 mid/high가 갈리지 않는다 — 이 테스트가 티어 축을 한 번도 밟지 "
        "못하므로 변별력이 0이다(설정 핀을 확인하라)."
    )


def test_unknown_seat_raises_instead_of_silently_writing_anthropic() -> None:
    """알 수 없는 좌석은 예외 — 기본 핀으로 조용히 접으면 이 회귀가 그대로 재생산된다."""

    class _UnknownSeat:
        cloud_provider = "gemini"

        def __getattr__(self, item: str) -> object:  # pragma: no cover - 방어
            raise AttributeError(item)

    with pytest.raises(ValueError, match="알 수 없는 cloud_provider"):
        model_name_for_decision(_cloud_decision(CostTier.CLOUD_MID), settings=_UnknownSeat())  # type: ignore[arg-type]
