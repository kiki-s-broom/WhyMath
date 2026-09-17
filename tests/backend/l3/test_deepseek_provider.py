"""DeepSeekProvider 단위테스트 — 공식 API 경로·CN 관할 고정·요금 구간 (ARCH-49 ③⑥⑦).

검증 핵심:
  - **모델 ID 실측 핀**: 기본값이 `deepseek-flash`/`deepseek-v4-pro`다.
    웹 자료가 널리 적는 `deepseek-v4-flash`는 API가 받지 않는 이름이라 기본값이 아니다 —
    그 사실을 테스트가 동결한다(문자열이 조용히 되돌려지면 RED).
  - **관할 고정**: `CN`이며 설정으로 바뀌지 않는다(본토 서버 전용·레지던시 선택지 없음).
  - **요금 구간 분리**: 피크/오프피크 단가가 2배 차이라 측정 리포트가 두 구간을 분리
    집계해야 한다 — `pricing_window`가 그 키를 준다. naive datetime은 **거부**한다.
  - 조용한 무시 금지: images·json_schema 거부, temperature·seed는 전달.

라이브 없음 — 전송은 가짜를 주입한다(CI hermetic).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import SecretStr

from whymath_backend.config import Settings
from whymath_backend.l3.interfaces import LLMProvider
from whymath_backend.l3.models import CostTier, LocalModelTier, ModelFamily, RoutingDecision
from whymath_backend.l3.provider_jurisdiction import Jurisdiction
from whymath_backend.l3.providers.deepseek import (
    PRICING_OFF_PEAK,
    PRICING_PEAK,
    DeepSeekProvider,
    pricing_window,
)

KST = timezone(timedelta(hours=9), "KST")


class _RecordingTransport:
    """전송 시임 — payload를 그대로 보관한다."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def post_chat(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_s: float,
    ) -> Any:
        self.calls.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        return {
            "choices": [{"message": {"content": "답"}}],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 5,
                "prompt_cache_hit_tokens": 12,
            },
        }

    @property
    def last_payload(self) -> dict[str, Any]:
        assert self.calls, "전송이 한 번도 일어나지 않았다"
        payload: dict[str, Any] = self.calls[-1]["payload"]
        return payload


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"deepseek_api_key": SecretStr("sk-ds-test")}
    base.update(overrides)
    return Settings(**base)


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


class TestMeasuredModelPins:
    """실측으로 확정된 모델 ID — 추론으로 되돌리면 RED (CLAUDE.md 환경 사실 추론 등재 금지)."""

    def test_default_pins_are_the_ids_the_api_actually_returns(self) -> None:
        defaults = Settings()
        assert defaults.deepseek_model_mid == "deepseek-flash"
        assert defaults.deepseek_model_high == "deepseek-v4-pro"

    def test_the_widely_published_wrong_id_is_not_used(self) -> None:
        """`deepseek-v4-flash`는 웹 자료 3곳이 일치해 적지만 API가 받지 않는다(2026-09-16)."""
        defaults = Settings()
        assert defaults.deepseek_model_mid != "deepseek-v4-flash"
        assert defaults.deepseek_model_high != "deepseek-v4-flash"

    async def test_model_pin_follows_cost_tier(self) -> None:
        transport = _RecordingTransport()
        provider = DeepSeekProvider(transport=transport, settings=_settings())
        await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))
        assert transport.last_payload["model"] == "deepseek-flash"
        await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_HIGH))
        assert transport.last_payload["model"] == "deepseek-v4-pro"


class TestJurisdictionIsFixed:
    """관할은 이 경로의 *사실*이지 설정이 아니다."""

    def test_jurisdiction_is_cn(self) -> None:
        assert DeepSeekProvider(settings=_settings()).jurisdiction is Jurisdiction.CN

    def test_internal_corpus_opt_in_defaults_off(self) -> None:
        assert Settings().deepseek_allow_internal_corpus is False
        assert DeepSeekProvider(settings=_settings()).allow_internal_corpus is False

    def test_internal_corpus_opt_in_follows_settings(self) -> None:
        provider = DeepSeekProvider(settings=_settings(deepseek_allow_internal_corpus=True))
        assert provider.allow_internal_corpus is True
        # opt-in을 켜도 관할 자체는 CN 그대로다 — 등급 정책만 넓어진다.
        assert provider.jurisdiction is Jurisdiction.CN

    async def test_status_reports_jurisdiction_and_opt_in(self) -> None:
        status = await DeepSeekProvider(settings=_settings()).check_status()
        assert status.configured is True
        assert status.jurisdiction is Jurisdiction.CN
        assert status.allow_internal_corpus is False


class TestPricingWindow:
    """피크/오프피크 분리 집계 키 — 단가가 정확히 2배 차이라 섞으면 비교가 무의미해진다."""

    @pytest.mark.parametrize("hour", [1, 3, 6, 9])
    def test_weekday_peak_hours(self, hour: int) -> None:
        """평일 UTC 01-04·06-10이 피크(2026-08-16 개정)."""
        moment = datetime(2026, 9, 16, hour, 30, tzinfo=UTC)  # 수요일
        assert moment.weekday() == 2
        assert pricing_window(moment) == PRICING_PEAK

    @pytest.mark.parametrize("hour", [0, 4, 5, 10, 23])
    def test_weekday_off_peak_hours(self, hour: int) -> None:
        """경계는 반개구간이다 — 04시·10시는 이미 오프피크(구간 중복 없음)."""
        moment = datetime(2026, 9, 16, hour, 30, tzinfo=UTC)
        assert pricing_window(moment) == PRICING_OFF_PEAK

    @pytest.mark.parametrize("day", [19, 20])  # 토(19)·일(20)
    def test_weekend_is_always_off_peak(self, day: int) -> None:
        """주말은 피크 시각이어도 오프피크 — 요일 절이 없으면 이 픽스처가 통과하지 못한다."""
        moment = datetime(2026, 9, day, 2, 0, tzinfo=UTC)
        assert moment.weekday() >= 5
        assert pricing_window(moment) == PRICING_OFF_PEAK

    def test_conversion_uses_utc_not_the_local_offset(self) -> None:
        """KST 11:00 = UTC 02:00 → 피크. 환산 절이 없으면 로컬 시(11)로 판정해 오프피크가 된다."""
        kst_moment = datetime(2026, 9, 16, 11, 0, tzinfo=KST)
        assert kst_moment.hour == 11  # 로컬 시로는 피크 구간 밖
        assert pricing_window(kst_moment) == PRICING_PEAK

    def test_conversion_can_cross_the_day_boundary(self) -> None:
        """KST 월요일 09:00 = UTC **일요일** 00:00 → 주말 오프피크.

        요일이 환산으로 바뀌는 자리다 — 로컬 요일로 판정하면 평일로 읽어 잘못 계상한다.
        """
        kst_monday = datetime(2026, 9, 21, 9, 0, tzinfo=KST)
        assert kst_monday.weekday() == 0
        assert pricing_window(kst_monday) == PRICING_OFF_PEAK

    def test_naive_datetime_is_rejected(self) -> None:
        """시간대 추측 금지 — 라벨이 통째로 뒤집힐 수 있으므로 모르면 던진다."""
        with pytest.raises(ValueError, match="시간대"):
            pricing_window(datetime(2026, 9, 16, 2, 0))


class TestPayloadAndRefusals:
    async def test_payload_shape(self) -> None:
        transport = _RecordingTransport()
        provider = DeepSeekProvider(transport=transport, settings=_settings())
        await provider.generate("프롬프트", "시스템", _cloud_decision())
        payload = transport.last_payload
        assert payload["messages"] == [
            {"role": "system", "content": "시스템"},
            {"role": "user", "content": "프롬프트"},
        ]
        assert payload["max_tokens"] == Settings().deepseek_max_tokens
        # 공식 API 직행 경로에는 OpenRouter용 provider 블록이 없다(경로 혼선 방지).
        assert "provider" not in payload

    async def test_url_is_official_endpoint(self) -> None:
        transport = _RecordingTransport()
        provider = DeepSeekProvider(transport=transport, settings=_settings())
        await provider.generate("p", "s", _cloud_decision())
        assert transport.calls[-1]["url"] == "https://api.deepseek.com/chat/completions"

    async def test_usage_normalizes_openai_field_names(self) -> None:
        """OpenAI 호환은 `prompt_tokens`/`completion_tokens`다(Anthropic과 이름이 다르다)."""
        transport = _RecordingTransport()
        provider = DeepSeekProvider(transport=transport, settings=_settings())
        result = await provider.generate("p", "s", _cloud_decision())
        assert result.usage is not None
        assert result.usage.input_tokens == 20
        assert result.usage.output_tokens == 5
        assert result.usage.cache_read_input_tokens == 12
        # 이 API에는 캐시 *쓰기* 개념이 없다 — 0이 아니라 None(미측정 ≠ 0).
        assert result.usage.cache_creation_input_tokens is None

    async def test_temperature_and_seed_forwarded(self) -> None:
        transport = _RecordingTransport()
        provider = DeepSeekProvider(transport=transport, settings=_settings())
        await provider.generate("p", "s", _cloud_decision(), temperature=0.2, seed=7)
        assert transport.last_payload["temperature"] == 0.2
        assert transport.last_payload["seed"] == 7

    async def test_local_decision_rejected(self) -> None:
        provider = DeepSeekProvider(transport=_RecordingTransport(), settings=_settings())
        local = RoutingDecision(
            cost_tier=CostTier.LOCAL,
            local_family=ModelFamily.MATH,
            local_model=LocalModelTier.FAST,
            mode="sync",
            reason="local",
            est_latency_ms=1010,
            est_cost_krw=0.0,
        )
        with pytest.raises(ValueError, match="클라우드 결정만"):
            await provider.generate("p", "s", local)

    async def test_images_rejected(self) -> None:
        provider = DeepSeekProvider(transport=_RecordingTransport(), settings=_settings())
        with pytest.raises(RuntimeError, match="멀티모달"):
            await provider.generate("p", "s", _cloud_decision(), images=["ZmFrZQ=="])

    async def test_json_schema_rejected(self) -> None:
        provider = DeepSeekProvider(transport=_RecordingTransport(), settings=_settings())
        with pytest.raises(RuntimeError, match="json_schema"):
            await provider.generate("p", "s", _cloud_decision(), json_schema={"a": 1})

    async def test_unconfigured_key_raises(self) -> None:
        provider = DeepSeekProvider(settings=_settings(deepseek_api_key=SecretStr("")))
        assert provider.configured is False
        with pytest.raises(RuntimeError, match="미설정"):
            await provider.generate("p", "s", _cloud_decision())


def test_provider_satisfies_llm_provider_protocol() -> None:
    assert isinstance(DeepSeekProvider(settings=_settings()), LLMProvider)
