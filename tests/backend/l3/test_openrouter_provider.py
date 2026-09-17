"""OpenRouterProvider 단위테스트 — 세 파라미터 채택 계약의 동결 (ARCH-49 ⑨⑩).

이 파일의 핵심은 하나다: **전송 직전 payload를 그대로 보고** `provider.only`·
`provider.allow_fallbacks`·`provider.data_collection` 셋이 *항상* 함께 실리는지 판정한다.
문자열 열거("이 키를 쓰지 마라")가 아니라 **구성된 결과**를 검사하므로 표기 변형으로
뚫리지 않는다(CLAUDE.md 「금지 패턴 열거 대신 산출물 검사」).

뮤테이션 대조(각 절을 밟는 픽스처):
  - `only` 제거/`tag` 미정규화      → `test_payload_pins_only_normalized_slugs`
  - `allow_fallbacks` 제거/True     → `test_payload_forbids_fallbacks`
  - `data_collection` 제거/"allow"  → `test_payload_denies_data_collection`
  - 빈 허용목록 가드 제거           → `test_empty_allowlist_is_an_error_not_unlimited`
  - `provider` 블록 자체 누락       → `test_generate_payload_always_carries_provider_block`
  - 관할 유도 규칙                  → `TestJurisdictionDerivation`

라이브 없음 — 전송은 가짜(`_RecordingTransport`)를 주입한다(CI hermetic).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import SecretStr

from whymath_backend.config import Settings
from whymath_backend.l3.interfaces import LLMProvider
from whymath_backend.l3.models import CostTier, LocalModelTier, ModelFamily, RoutingDecision
from whymath_backend.l3.provider_jurisdiction import Jurisdiction
from whymath_backend.l3.providers.openrouter import (
    DATA_COLLECTION_DENY,
    PROVIDER_JURISDICTIONS,
    OpenRouterProvider,
    build_provider_block,
    jurisdiction_of_slugs,
    provider_slug_from_tag,
)


class _RecordingTransport:
    """전송 시임 — 요청 url·헤더·payload를 **그대로** 보관한다(계약 판정의 관측 지점)."""

    def __init__(self, response: Any | None = None) -> None:
        self.response = response if response is not None else _ok_response()
        self.calls: list[dict[str, Any]] = []

    async def post_chat(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_s: float,
    ) -> Any:
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "payload": dict(payload),
                "timeout_s": timeout_s,
            }
        )
        return self.response

    @property
    def last_payload(self) -> dict[str, Any]:
        assert self.calls, "전송이 한 번도 일어나지 않았다 — 계약 판정의 분모가 0이다"
        payload: dict[str, Any] = self.calls[-1]["payload"]
        return payload


def _ok_response() -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": "답"}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "openrouter_api_key": SecretStr("sk-or-test"),
        "openrouter_allowed_providers": ("deepinfra", "fireworks"),
    }
    base.update(overrides)
    return Settings(**base)


def _cloud_decision(cost: CostTier = CostTier.CLOUD_MID, **overrides: Any) -> RoutingDecision:
    kwargs: dict[str, Any] = {
        "cost_tier": cost,
        "local_family": None,
        "local_model": None,
        "mode": "sync",
        "reason": "cloud escalation",
        "est_latency_ms": 2000,
        "est_cost_krw": 1.0,
    }
    kwargs.update(overrides)
    return RoutingDecision(**kwargs)


async def _generate(provider: OpenRouterProvider, **kwargs: Any) -> None:
    await provider.generate("프롬프트", "시스템", _cloud_decision(), **kwargs)


# ──────────────────────────────────────────────────────────────────────────
# 세 파라미터 계약 — build_provider_block 단일 좌석
# ──────────────────────────────────────────────────────────────────────────
class TestThreeParameterContract:
    """셋이 *함께* 실리는가. 하나라도 빠지거나 값이 뒤집히면 RED."""

    def test_payload_pins_only_normalized_slugs(self) -> None:
        """`only`가 있고, `tag` 형태(`deepinfra/fp8`)가 slug로 정규화된다.

        정규화가 없으면 `only`에 `deepinfra/fp8`이 실려 OpenRouter가 매칭하지 못하고
        — 즉 고정이 조용히 무효가 된다. 그래서 픽스처가 **양자화 접미사를 포함한** tag를
        일부러 밟는다(정규화 절이 없으면 이 단언이 실패한다).
        """
        block = build_provider_block(["deepinfra/fp8", " fireworks "])
        assert block["only"] == ["deepinfra", "fireworks"]

    def test_payload_forbids_fallbacks(self) -> None:
        """`allow_fallbacks`가 있고 **False**다 — 조용한 우회 금지."""
        block = build_provider_block(["deepinfra"])
        assert "allow_fallbacks" in block
        assert block["allow_fallbacks"] is False

    def test_payload_denies_data_collection(self) -> None:
        """`data_collection`이 있고 **"deny"**다 — 학습 수집 공급사 배제."""
        block = build_provider_block(["deepinfra"])
        assert "data_collection" in block
        assert block["data_collection"] == DATA_COLLECTION_DENY == "deny"

    def test_block_has_exactly_the_three_keys(self) -> None:
        """셋 **전부**이며 그 이상도 아니다 — 키 하나가 빠지면 이 단언이 곧바로 실패한다."""
        assert set(build_provider_block(["deepinfra"])) == {
            "only",
            "allow_fallbacks",
            "data_collection",
        }

    def test_empty_allowlist_is_an_error_not_unlimited(self) -> None:
        """빈 허용목록은 '제약 없음'이 아니라 **오류**다(fail-closed).

        가드가 없으면 `{"only": []}`가 나가고 OpenRouter는 그것을 제약 없음으로 읽어
        국적 미확인 공급사 16곳 전체가 후보가 된다 — 우리 쪽 방어층이 통째로 사라진다.
        """
        with pytest.raises(ValueError, match="비어"):
            build_provider_block([])

    def test_whitespace_only_entries_do_not_survive_as_slugs(self) -> None:
        """공백만 있는 항목은 slug가 아니다 — 전부 공백이면 빈 목록과 같이 거부된다."""
        with pytest.raises(ValueError):
            build_provider_block(["   ", ""])


class TestGeneratePayload:
    """`generate()`가 만든 **실제 전송 payload**에 계약이 실렸는가."""

    @pytest.mark.parametrize("cost", [CostTier.CLOUD_MID, CostTier.CLOUD_HIGH])
    async def test_generate_payload_always_carries_provider_block(self, cost: CostTier) -> None:
        """두 클라우드 티어 **모두** provider 블록을 싣는다(티어별 누락 방지)."""
        transport = _RecordingTransport()
        provider = OpenRouterProvider(transport=transport, settings=_settings())
        await provider.generate("프롬프트", "시스템", _cloud_decision(cost))
        block = transport.last_payload["provider"]
        assert block == {
            "only": ["deepinfra", "fireworks"],
            "allow_fallbacks": False,
            "data_collection": "deny",
        }

    async def test_model_pin_follows_cost_tier(self) -> None:
        transport = _RecordingTransport()
        settings = _settings(
            openrouter_model_mid="deepseek/deepseek-v4-flash",
            openrouter_model_high="deepseek/deepseek-v4-pro",
        )
        provider = OpenRouterProvider(transport=transport, settings=settings)
        await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))
        assert transport.last_payload["model"] == "deepseek/deepseek-v4-flash"
        await provider.generate("p", "s", _cloud_decision(CostTier.CLOUD_HIGH))
        assert transport.last_payload["model"] == "deepseek/deepseek-v4-pro"

    async def test_default_model_pin_is_the_corrected_openrouter_slug(self) -> None:
        """정정된 핀(2026-09-17) — `v4.1`이며 공식 API id와 **다른 문자열**임을 동결한다.

        초판은 `deepseek/deepseek-v4-flash`(점 없음)로 적혀 있었고, 그것은 OpenRouter
        모델 페이지의 실제 id와 달랐다. 같은 세션의 OpenRouter 기록 4건이 전부 틀린
        것으로 드러난 사고의 일부다 — 그래서 문자열 자체를 동결한다.
        """
        defaults = Settings()
        assert defaults.openrouter_model_mid == "deepseek/deepseek-v4.1-flash"
        assert defaults.openrouter_model_mid != defaults.deepseek_model_mid

    async def test_messages_carry_system_and_user_roles(self) -> None:
        transport = _RecordingTransport()
        provider = OpenRouterProvider(transport=transport, settings=_settings())
        await provider.generate("프롬프트", "시스템", _cloud_decision())
        assert transport.last_payload["messages"] == [
            {"role": "system", "content": "시스템"},
            {"role": "user", "content": "프롬프트"},
        ]

    async def test_optional_args_are_omitted_when_unset(self) -> None:
        """미지정 선택 인자는 키 자체를 싣지 않는다(None 전송 금지 — 기존 규약)."""
        transport = _RecordingTransport()
        provider = OpenRouterProvider(transport=transport, settings=_settings())
        await _generate(provider)
        assert "temperature" not in transport.last_payload
        assert "seed" not in transport.last_payload

    async def test_temperature_and_seed_are_forwarded_when_set(self) -> None:
        """OpenAI 호환 API에는 seed가 **있다** — Anthropic과 달리 거부하지 않는다."""
        transport = _RecordingTransport()
        provider = OpenRouterProvider(transport=transport, settings=_settings())
        await _generate(provider, temperature=0.9, seed=42)
        assert transport.last_payload["temperature"] == 0.9
        assert transport.last_payload["seed"] == 42

    async def test_authorization_header_carries_the_key(self) -> None:
        transport = _RecordingTransport()
        provider = OpenRouterProvider(transport=transport, settings=_settings())
        await _generate(provider)
        assert transport.calls[-1]["headers"]["Authorization"] == "Bearer sk-or-test"

    async def test_url_is_chat_completions_under_base(self) -> None:
        transport = _RecordingTransport()
        provider = OpenRouterProvider(
            transport=transport,
            settings=_settings(openrouter_base_url="https://example.test/api/v1/"),
        )
        await _generate(provider)
        assert transport.calls[-1]["url"] == "https://example.test/api/v1/chat/completions"

    async def test_response_text_and_usage_are_normalized(self) -> None:
        transport = _RecordingTransport()
        provider = OpenRouterProvider(transport=transport, settings=_settings())
        result = await provider.generate("p", "s", _cloud_decision())
        assert result.text == "답"
        assert result.usage is not None
        assert result.usage.input_tokens == 11
        assert result.usage.output_tokens == 7
        assert result.usage.latency_ms is not None


class TestRefusals:
    """조용한 무시 금지 — 지원하지 않는 축은 명확한 오류."""

    async def test_local_decision_rejected(self) -> None:
        transport = _RecordingTransport()
        provider = OpenRouterProvider(transport=transport, settings=_settings())
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
        assert not transport.calls

    async def test_images_rejected(self) -> None:
        transport = _RecordingTransport()
        provider = OpenRouterProvider(transport=transport, settings=_settings())
        with pytest.raises(RuntimeError, match="멀티모달"):
            await _generate(provider, images=["ZmFrZQ=="])
        assert not transport.calls

    async def test_json_schema_rejected(self) -> None:
        transport = _RecordingTransport()
        provider = OpenRouterProvider(transport=transport, settings=_settings())
        with pytest.raises(RuntimeError, match="json_schema"):
            await _generate(provider, json_schema={"type": "object"})
        assert not transport.calls

    async def test_unconfigured_key_raises_before_sending(self) -> None:
        provider = OpenRouterProvider(settings=_settings(openrouter_api_key=SecretStr("")))
        assert provider.configured is False
        with pytest.raises(RuntimeError, match="미설정"):
            await _generate(provider)

    async def test_empty_allowlist_blocks_generation(self) -> None:
        """허용목록이 비면 키가 있어도 보내지 않는다 — 두 번째 방어층의 부재는 차단 사유다."""
        transport = _RecordingTransport()
        provider = OpenRouterProvider(
            transport=transport, settings=_settings(openrouter_allowed_providers=())
        )
        assert provider.configured is False
        with pytest.raises(RuntimeError):
            await _generate(provider)
        assert not transport.calls


class TestJurisdictionDerivation:
    """관할은 *선언*이 아니라 허용목록에서 **계산**된다 — 설정 오염이 조용히 통과하지 않는다."""

    def test_slug_is_the_part_before_the_slash(self) -> None:
        """2026-09-16 실측 규칙 — `tag`의 `/` 앞부분이 slug다."""
        assert provider_slug_from_tag("deepinfra/fp8") == "deepinfra"
        assert provider_slug_from_tag("azure/us") == "azure"
        assert provider_slug_from_tag("digitalocean") == "digitalocean"

    def test_known_us_providers_resolve_to_us(self) -> None:
        """패널에서 `Headquarters: US`가 확인된 곳들은 US로 해소된다."""
        assert jurisdiction_of_slugs(["deepinfra", "fireworks", "together"]) is Jurisdiction.US
        assert jurisdiction_of_slugs(["gmicloud", "baseten"]) is Jurisdiction.US

    def test_provider_dropped_for_lack_of_evidence_is_unknown(self) -> None:
        """`digitalocean`은 근거 재확인 실패로 표에서 빠졌다 — 그래서 UNKNOWN이다.

        "전에 US라고 적었다"는 근거가 아니다: 그것을 적은 세션의 OpenRouter 기록 4건이
        전부 틀린 것으로 드러났으므로, 같은 출처의 다른 항목도 재확인 전까지는 모른다.
        """
        assert "digitalocean" not in PROVIDER_JURISDICTIONS
        assert jurisdiction_of_slugs(["digitalocean"]) is Jurisdiction.UNKNOWN

    def test_unknown_slug_makes_the_whole_call_unknown(self) -> None:
        """국적 미확인이 하나만 섞여도 전체가 UNKNOWN — `open-inference`가 그 사례다."""
        assert jurisdiction_of_slugs(["deepinfra", "open-inference"]) is Jurisdiction.UNKNOWN

    def test_known_chinese_providers_resolve_to_cn_not_unknown(self) -> None:
        """중국계로 *아는* 곳은 CN이다 — "모른다"와 같은 칸에 넣지 않는다.

        판정 결과는 둘 다 차단에 가깝지만(CN은 합성 프로브만) **사실이 다르고**, CN은
        코퍼스 opt-in이라는 경로가 있는 반면 UNKNOWN은 전건 차단이다.
        """
        assert jurisdiction_of_slugs(["siliconflow"]) is Jurisdiction.CN

    def test_mixed_known_jurisdictions_collapse_to_unknown(self) -> None:
        """서로 다른 *아는* 관할이 섞이면 UNKNOWN — 어느 쪽이 응답할지 우리가 말할 수 없다.

        이 픽스처는 **양쪽이 모두 UNKNOWN이 아닌** 조합이어야 그 절을 밟는다: 혼재 절을
        지우면 집합에서 하나를 임의로 꺼내 US 또는 CN을 돌려주는데, 둘 다 UNKNOWN이 아니라
        판정이 확정적으로 뒤집힌다. 미확인 slug를 섞은 앞 테스트로는 이 절을 밟지 못한다
        (그쪽은 절을 지워도 UNKNOWN이 나올 수 있어 변별력이 없다 — 2026-09-17 뮤테이션
        M10 생존으로 발각).
        """
        mixed = jurisdiction_of_slugs(["deepinfra", "siliconflow"])
        assert mixed is Jurisdiction.UNKNOWN
        # 픽스처가 그 절을 실제로 밟는지 자가검증 — 두 항이 서로 다른 *아는* 관할이어야 한다.
        assert jurisdiction_of_slugs(["deepinfra"]) is Jurisdiction.US
        assert jurisdiction_of_slugs(["siliconflow"]) is Jurisdiction.CN

    def test_mixed_jurisdiction_blocks_generation_end_to_end(self) -> None:
        """혼재 허용목록을 설정하면 제공자 전체가 차단 상태가 된다(정책 관통)."""
        provider = OpenRouterProvider(
            settings=_settings(openrouter_allowed_providers=("deepinfra", "siliconflow"))
        )
        assert provider.jurisdiction is Jurisdiction.UNKNOWN

    def test_empty_allowlist_is_unknown_not_permissive(self) -> None:
        assert jurisdiction_of_slugs([]) is Jurisdiction.UNKNOWN

    def test_provider_jurisdiction_follows_settings(self) -> None:
        known = OpenRouterProvider(settings=_settings())  # noqa: F841 — 아래에서 쓴다
        polluted = OpenRouterProvider(
            settings=_settings(openrouter_allowed_providers=("mystery-host",))
        )
        assert known.jurisdiction is Jurisdiction.US
        assert polluted.jurisdiction is Jurisdiction.UNKNOWN

    def test_default_allowlist_is_only_hq_and_retention_verified_providers(self) -> None:
        """기본 허용목록 동결 — 세 조건을 **함께** 만족한 곳만(2026-09-17 공급사 패널 실측).

        조건: `Headquarters: US` · `Prompt training: No` · `Retention: Zero retention`.
        """
        defaults = Settings()
        assert defaults.openrouter_allowed_providers == ("deepinfra", "fireworks", "together")

    def test_us_provider_with_unknown_retention_is_not_in_the_default_allowlist(self) -> None:
        """`gmicloud`는 **US인데도** 기본 허용목록에 없다 — 보존 정책이 `Unknown`이다.

        국적을 아는 것과 데이터 정책을 아는 것은 다른 축이고, 모르는 것은 허용 사유가
        아니다. 관할 표에는 US로 들어 있으므로(설정으로 켤 수는 있다) 이 단언이 없으면
        "US니까 넣자"로 조용히 되돌아간다.
        """
        defaults = Settings()
        assert "gmicloud" not in defaults.openrouter_allowed_providers
        assert PROVIDER_JURISDICTIONS["gmicloud"] is Jurisdiction.US

    def test_cheapest_provider_is_not_auto_included(self) -> None:
        """최저가(`relace` $0.15/$0.60)는 국적 미확인이라 들어가지 않는다 — 가격은 근거가 아니다."""
        defaults = Settings()
        assert "relace" not in defaults.openrouter_allowed_providers
        assert "relace" not in PROVIDER_JURISDICTIONS


class TestStatusReporting:
    """구성 점검이 '보낼 수 없는 상태'를 침묵하지 않는가."""

    async def test_status_reports_healthy_configuration(self) -> None:
        status = await OpenRouterProvider(settings=_settings()).check_status()
        assert status.configured is True
        assert status.jurisdiction is Jurisdiction.US
        assert status.error is None

    async def test_status_reports_empty_allowlist_as_error(self) -> None:
        status = await OpenRouterProvider(
            settings=_settings(openrouter_allowed_providers=())
        ).check_status()
        assert status.error is not None
        assert "비어" in status.error

    async def test_status_reports_unknown_jurisdiction_as_error(self) -> None:
        status = await OpenRouterProvider(
            settings=_settings(openrouter_allowed_providers=("mystery-host",))
        ).check_status()
        assert status.jurisdiction is Jurisdiction.UNKNOWN
        assert status.error is not None


def test_provider_satisfies_llm_provider_protocol() -> None:
    """라우터가 아는 경계를 충족한다 — 파이프라인이 그대로 태울 수 있다."""
    assert isinstance(OpenRouterProvider(settings=_settings()), LLMProvider)
