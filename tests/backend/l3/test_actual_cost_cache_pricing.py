"""실측 비용 산식의 프롬프트 캐시 과금 (OPS-88).

종전 `actual_cost_usd`는 `usage.input_tokens × 입력 단가`만 계산했다. Anthropic의 `input_tokens`는
캐시 미적중 **잔량뿐**이라(캐시로 읽힌 프리픽스는 `cache_read_input_tokens`, 캐시에 쓴 프리픽스는
`cache_creation_input_tokens`에 따로 센다) 캐시를 켠 회차는 읽기(입력 단가의 0.1배)·쓰기(1.25배)
비용이 통째로 빠졌다. 2026-09-21 EOS-02 라이브 회차 실측: 보고 $0.03987 vs 실제 추정 $0.05549
= **28.1% 과소**(`docs/ops/eos02_prompt_cache_live_verdict.md` §3-1).

이 파일이 고정하는 것
  ① 그 라이브 실측 숫자를 그대로 넣었을 때의 기대 금액과 28.1% 갭(결함 고정)
  ② 읽기만·쓰기만·둘 다 미관측 3종 회차의 기대 금액(배수 상수를 1.0으로 바꾸면 적색)
  ③ 쓰기 할증이 통째로 누락되던 방향(쓰기만 있는 회차가 종전 산식보다 **커야** 한다)
  ④ 미관측(None)을 0으로 접지 않는다 — 한쪽만 None이어도 다른 항은 산입한다
  ⑤ **다른 좌석은 가산하지 않는다** — DeepSeek의 `prompt_cache_hit_tokens`는 `prompt_tokens`를 쪼갠
     값이라 `input_tokens`에 이미 들어 있다. anthropic식 가산을 그 좌석에 하면 이중 계상된다.

주의 — "예산 소진 판정"은 이 테스트가 다루지 않는다: 코드를 찾아본 결과 `actual_cost_krw`를 읽어
잔여 예산을 차감하는 소비처가 없다(`budget_krw`는 라우터 요청의 정적 입력이고 `guard_cloud`는
**사전 추정** `cloud_min_cost`와 비교한다). 값 방향만 `actual_cost_krw` 수준에서 고정한다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l3.models import (
    CostTier,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
    Usage,
)
from whymath_backend.l3.pregenerate.provenance_bridge import actual_cost_usd_or_none
from whymath_backend.l3.router import (
    CACHE_READ_PRICE_MULTIPLIER,
    CACHE_WRITE_PRICE_MULTIPLIER,
    CLOUD_TOKEN_PRICE_USD_PER_1M,
    DEFAULT_CACHE_TTL,
    USD_TO_KRW,
    actual_cost_krw,
    actual_cost_usd,
)


def _decision(cost: CostTier) -> RoutingDecision:
    """비용 축만 다른 최소 결정 객체(테스트 헬퍼 — `test_router._decision`과 같은 형태)."""
    if cost is CostTier.LOCAL:
        return RoutingDecision(
            cost_tier=cost,
            local_family=ModelFamily.MATH,
            local_model=LocalModelTier.FAST,
            mode="sync",
            reason="t",
            est_latency_ms=1010,
        )
    return RoutingDecision(
        cost_tier=cost,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="t",
        est_latency_ms=3000,
        est_cost_krw=28.0,
    )


# Sonnet 4.6 단가(USD/1M) — 단가표에서 읽어 기대값을 *독립 계산*한다(상수를 복붙하지 않는다).
_MID_IN, _MID_OUT = CLOUD_TOKEN_PRICE_USD_PER_1M[(CostTier.CLOUD_MID, "anthropic")]
_HIGH_IN, _HIGH_OUT = CLOUD_TOKEN_PRICE_USD_PER_1M[(CostTier.CLOUD_HIGH, "anthropic")]


class TestDocumentedMultipliers:
    def test_multiplier_values_are_the_published_ones(self) -> None:
        # 읽기 0.1배·쓰기 1.25배(5분)는 EOS-02 실측 갭으로 교차검증됐고, 1시간 2배는 미검증 문서값이다.
        assert CACHE_READ_PRICE_MULTIPLIER == 0.1
        assert CACHE_WRITE_PRICE_MULTIPLIER == {"5m": 1.25, "1h": 2.0}
        assert DEFAULT_CACHE_TTL == "5m"


class TestEos02LiveGapIsPinned:
    """① 결함 고정 — 2026-09-21 라이브 회차 숫자(10회 합산)를 그대로 넣는다.

    산식이 토큰에 **선형**이라 10회를 합산한 usage 하나로도 호출별 합계와 같은 값이 나온다.
    uncached 30 · cache_read 21,789 · cache_creation 2,421 · 출력은 보고 총액에서 역산한 2,652.
    """

    _LIVE = Usage(
        input_tokens=30,
        output_tokens=2652,
        cache_read_input_tokens=21789,
        cache_creation_input_tokens=2421,
    )

    def test_reported_total_before_the_fix_is_reproduced_without_cache_terms(self) -> None:
        # 캐시 두 필드를 뺀 같은 회차 = 종전 산식이 보고하던 $0.03987.
        before = Usage(input_tokens=30, output_tokens=2652)
        assert actual_cost_usd(_decision(CostTier.CLOUD_MID), before) == pytest.approx(0.03987)

    def test_actual_total_matches_the_live_estimate(self) -> None:
        # 실제 추정 $0.05549(입력 $0.015705 + 출력 $0.03978).
        cost = actual_cost_usd(_decision(CostTier.CLOUD_MID), self._LIVE)
        assert cost == pytest.approx(0.05548545)
        assert cost == pytest.approx(0.05549, abs=1e-5)

    def test_gap_is_exactly_the_two_cache_terms_and_is_28_percent(self) -> None:
        d = _decision(CostTier.CLOUD_MID)
        with_cache = actual_cost_usd(d, self._LIVE)
        without = actual_cost_usd(d, Usage(input_tokens=30, output_tokens=2652))
        assert with_cache is not None and without is not None
        gap = with_cache - without
        expected_gap = (21789 * 0.1 + 2421 * 1.25) * _MID_IN / 1_000_000
        assert gap == pytest.approx(expected_gap)
        assert gap == pytest.approx(0.01562, abs=1e-5)  # 라이브 리포트가 적은 차이
        # 종전 보고값은 실제보다 28.1% 적었다.
        assert 1 - without / with_cache == pytest.approx(0.281, abs=0.001)

    def test_krw_follows_the_same_formula(self) -> None:
        d = _decision(CostTier.CLOUD_MID)
        usd = actual_cost_usd(d, self._LIVE)
        assert usd is not None
        assert actual_cost_krw(d, self._LIVE) == pytest.approx(usd * USD_TO_KRW)

    def test_ledger_path_cost_includes_the_cache_terms(self) -> None:
        # 원장·출처 기록이 쓰는 `actual_cost_usd_or_none`도 같은 값 — 합계(`cost_usd_total`)가 따라 고쳐진다.
        d = _decision(CostTier.CLOUD_MID)
        assert actual_cost_usd_or_none(d, self._LIVE, seat="anthropic") == pytest.approx(0.05548545)


class TestThreeRoundShapes:
    """⑤ 읽기만 · 쓰기만 · 둘 다 미관측 — 각 회차의 기대 금액을 손으로 계산해 단언한다."""

    def test_read_only_round(self) -> None:
        # (1000 + 20000×0.1) 입력 환산 토큰 × $3 + 500 출력 × $15 = $0.009 + $0.0075.
        usage = Usage(
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=20000,
            cache_creation_input_tokens=0,  # 관측했더니 0 — None과 다른 사실
        )
        expected = ((1000 + 20000 * 0.1) * _MID_IN + 500 * _MID_OUT) / 1_000_000
        assert actual_cost_usd(_decision(CostTier.CLOUD_MID), usage) == pytest.approx(expected)
        assert expected == pytest.approx(0.0165)

    def test_write_only_round_is_billed_the_write_premium(self) -> None:
        # 프리픽스를 썼는데 다시 읽히지 않은 회차 — 1.25배 할증이 비용에 그대로 실려야 한다(③).
        usage = Usage(
            input_tokens=100,
            output_tokens=200,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=5000,
        )
        d = _decision(CostTier.CLOUD_MID)
        cost = actual_cost_usd(d, usage)
        expected = ((100 + 5000 * 1.25) * _MID_IN + 200 * _MID_OUT) / 1_000_000
        assert cost == pytest.approx(expected)
        assert expected == pytest.approx(0.02205)
        # 방향 고정 — 종전 산식(캐시 항 없음)은 이 회차를 훨씬 적게 셌다.
        before = actual_cost_usd(d, Usage(input_tokens=100, output_tokens=200))
        assert before is not None and cost is not None
        assert cost > before * 5

    def test_both_cache_fields_unobserved_equals_the_pre_fix_formula(self) -> None:
        # 구버전 SDK·미노출 — 캐시 항을 산입하지 않아 종전과 같은 값(기존 회귀 0).
        usage = Usage(input_tokens=1000, output_tokens=1000)
        assert usage.cache_read_input_tokens is None and usage.cache_creation_input_tokens is None
        assert actual_cost_usd(_decision(CostTier.CLOUD_MID), usage) == pytest.approx(0.018)

    def test_cloud_high_uses_the_same_multipliers(self) -> None:
        usage = Usage(
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=1_000_000,
            cache_creation_input_tokens=1_000_000,
        )
        expected = (0.1 + 1.25) * _HIGH_IN
        assert actual_cost_usd(_decision(CostTier.CLOUD_HIGH), usage) == pytest.approx(expected)


class TestUnobservedIsNotFoldedToZero:
    """④ 미측정과 0의 구분 — 한쪽만 None이어도 다른 항은 산입하고, 값을 지어 채우지 않는다."""

    def test_read_none_creation_observed(self) -> None:
        usage = Usage(
            input_tokens=10,
            output_tokens=0,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=1000,
        )
        expected = (10 + 1000 * 1.25) * _MID_IN / 1_000_000
        assert actual_cost_usd(_decision(CostTier.CLOUD_MID), usage) == pytest.approx(expected)

    def test_creation_none_read_observed(self) -> None:
        usage = Usage(
            input_tokens=10,
            output_tokens=0,
            cache_read_input_tokens=1000,
            cache_creation_input_tokens=None,
        )
        expected = (10 + 1000 * 0.1) * _MID_IN / 1_000_000
        assert actual_cost_usd(_decision(CostTier.CLOUD_MID), usage) == pytest.approx(expected)

    def test_usage_itself_is_never_rewritten(self) -> None:
        # 비용 계산이 입력 `Usage`를 0으로 바꿔 놓으면 하류(적중률 집계)가 미관측을 0 실측으로 읽는다.
        usage = Usage(input_tokens=10, output_tokens=5, cache_read_input_tokens=None)
        actual_cost_usd(_decision(CostTier.CLOUD_MID), usage)
        assert usage.cache_read_input_tokens is None
        assert usage.cache_creation_input_tokens is None

    def test_unknown_input_or_output_tokens_keep_the_existing_contract(self) -> None:
        # 토큰 미상 → 0.0(호출부가 None 기록) — 캐시 필드가 있어도 이 계약은 그대로다.
        d = _decision(CostTier.CLOUD_MID)
        assert (
            actual_cost_usd(d, Usage(input_tokens=None, output_tokens=5, cache_read_input_tokens=9))
            == 0.0
        )
        assert (
            actual_cost_usd(d, Usage(input_tokens=5, output_tokens=None, cache_read_input_tokens=9))
            == 0.0
        )


class TestCacheTtlAxis:
    def test_one_hour_ttl_is_expressible_and_default_stays_five_minutes(self) -> None:
        usage = Usage(
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=1_000_000,
        )
        d = _decision(CostTier.CLOUD_MID)
        assert actual_cost_usd(d, usage) == pytest.approx(1.25 * _MID_IN)
        assert actual_cost_usd(d, usage, cache_ttl="5m") == pytest.approx(1.25 * _MID_IN)
        assert actual_cost_usd(d, usage, cache_ttl="1h") == pytest.approx(2.0 * _MID_IN)
        assert actual_cost_krw(d, usage, cache_ttl="1h") == pytest.approx(
            2.0 * _MID_IN * USD_TO_KRW
        )


class TestOtherSeatsAreNotDoubleCounted:
    """⑤ anthropic이 아닌 좌석 — 캐시 토큰이 `input_tokens`에 이미 들어 있어 가산하면 이중 계상이다."""

    @pytest.mark.parametrize("seat", ["openrouter", "deepseek"])
    def test_cache_fields_do_not_change_the_cost(self, seat: str) -> None:
        d = _decision(CostTier.CLOUD_MID)
        price_in, price_out = CLOUD_TOKEN_PRICE_USD_PER_1M[(CostTier.CLOUD_MID, seat)]  # type: ignore[index]
        # DeepSeek식: prompt_tokens 1000 중 900이 캐시 적중 — input_tokens에 이미 1000이 들어 있다.
        with_cache = Usage(
            input_tokens=1000,
            output_tokens=100,
            cache_read_input_tokens=900,
            cache_creation_input_tokens=None,
        )
        without = Usage(input_tokens=1000, output_tokens=100)
        expected = (1000 * price_in + 100 * price_out) / 1_000_000
        assert actual_cost_usd(d, with_cache, seat=seat) == pytest.approx(expected)  # type: ignore[arg-type]
        assert actual_cost_usd(d, with_cache, seat=seat) == actual_cost_usd(d, without, seat=seat)  # type: ignore[arg-type]

    def test_default_seat_is_the_additive_one(self) -> None:
        # 좌석을 말하지 않은 호출부의 기본 좌석은 anthropic(역사적 값)이라 캐시 항이 산입된다.
        d = _decision(CostTier.CLOUD_MID)
        usage = Usage(input_tokens=0, output_tokens=0, cache_read_input_tokens=1_000_000)
        assert actual_cost_usd(d, usage) == actual_cost_usd(d, usage, seat="anthropic")
        assert actual_cost_usd(d, usage) == pytest.approx(0.1 * _MID_IN)

    def test_local_stays_zero_whatever_the_cache_fields_say(self) -> None:
        usage = Usage(
            input_tokens=5,
            output_tokens=5,
            cache_read_input_tokens=10**9,
            cache_creation_input_tokens=10**9,
        )
        assert actual_cost_usd(_decision(CostTier.LOCAL), usage) == 0.0
