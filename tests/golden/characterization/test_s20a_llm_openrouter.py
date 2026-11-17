"""S20A 2일째 특성화 — 옛 OpenRouter 프로바이더·팩토리와 골든 복사본이 같은 입력에 같은 출력을 낸다.

대상(옛 → 골든):
- `l3/providers/openrouter.OpenRouterProvider` → `golden/llm/openrouter.py`
- `l3/providers/factory.build_cloud_provider` → `golden/llm/factory.py`(openrouter 분기만)

같은 설정·같은 라우터 결정·같은 프롬프트 10가지에서, 전송기로 나가는 요청(주소·헤더·본문·제한 시간)과
돌아온 결과(본문·토큰 수)가 같은지 본다. 지연 시간은 실행마다 달라 비교에서 뺀다. 네트워크는 쓰지
않는다(가짜 전송기). 키는 테스트용 가짜 문자열이다.
옛 모듈은 이 테스트에서만 import한다(골든 패키지는 import하지 않는다 — test_import_budget.py).
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Mapping
from typing import Any

import golden.llm.factory as golden_factory
import golden.llm.openrouter as golden_openrouter
import pytest

import whymath_backend.l3.providers.factory as legacy_factory
import whymath_backend.l3.providers.openrouter as legacy_openrouter
from whymath_backend.config import Settings
from whymath_backend.l3.models import CostTier, RoutingDecision


class _RecordingTransport:
    """요청을 그대로 적어 두고 정해진 응답을 돌려주는 가짜 전송기."""

    def __init__(self, response: Any) -> None:
        self.response = response
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
            {"url": url, "headers": dict(headers), "payload": dict(payload), "timeout_s": timeout_s}
        )
        return self.response


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"openrouter_api_key": "sk-or-test-not-a-real-key"}
    base.update(overrides)
    return Settings(**base)


def _decision(tier: CostTier) -> RoutingDecision:
    return RoutingDecision(cost_tier=tier, est_latency_ms=1000)


_RESPONSE = {
    "model": "deepseek/deepseek-v4.1-flash",
    "choices": [{"message": {"content": "  기울기는 무엇과 무엇의 비일까?  "}}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 18},
}

# (이름, 설정 덮어쓰기, 비용 티어, 생성 인자) — 입력 10개
_CASES: list[tuple[str, dict[str, Any], CostTier, dict[str, Any]]] = [
    ("기본 설정 · CLOUD_MID", {}, CostTier.CLOUD_MID, {}),
    ("기본 설정 · CLOUD_HIGH", {}, CostTier.CLOUD_HIGH, {}),
    ("LOCAL 결정은 거부", {}, CostTier.LOCAL, {}),
    (
        "temperature·top_p·seed",
        {},
        CostTier.CLOUD_MID,
        {"temperature": 0.2, "top_p": 0.9, "seed": 7},
    ),
    ("images는 거부", {}, CostTier.CLOUD_MID, {"images": ["data:image/png;base64,AA=="]}),
    ("json_schema는 거부", {}, CostTier.CLOUD_MID, {"json_schema": {"type": "object"}}),
    ("허용목록 비어 있음", {"openrouter_allowed_providers": ()}, CostTier.CLOUD_MID, {}),
    (
        "허용목록 여러 곳",
        {"openrouter_allowed_providers": ("fireworks", "together")},
        CostTier.CLOUD_MID,
        {},
    ),
    (
        "주소 끝 슬래시·토큰 상한·제한 시간",
        {
            "openrouter_base_url": "https://openrouter.example/api/v1/",
            "openrouter_max_tokens": 77,
            "openrouter_request_timeout_s": 9.5,
        },
        CostTier.CLOUD_MID,
        {},
    ),
    (
        "모델 핀 바꿈",
        {"openrouter_model_mid": "x/mid-pin", "openrouter_model_high": "x/high-pin"},
        CostTier.CLOUD_HIGH,
        {},
    ),
]


def _run(module: Any, overrides: dict[str, Any], tier: CostTier, kwargs: dict[str, Any]) -> Any:
    """한 모듈의 프로바이더로 생성 1회 — (결과 또는 예외, 전송 기록, 구성 상태)."""
    transport = _RecordingTransport(_RESPONSE)
    provider = module.OpenRouterProvider(transport=transport, settings=_settings(**overrides))
    status = (provider.configured, provider.jurisdiction, provider.seat)

    async def go() -> tuple[Any, ...]:
        try:
            result = await provider.generate("학생: 3이요", "규칙 7개", _decision(tier), **kwargs)
        except Exception as exc:  # noqa: BLE001 — 예외도 출력의 일부로 비교한다
            return ("err", type(exc).__name__, str(exc))
        usage = dataclasses.replace(result.usage, latency_ms=None)  # 실행마다 다른 값만 뺀다
        return ("ok", result.text, usage)

    return asyncio.run(go()), transport.calls, status


@pytest.mark.parametrize(
    ("label", "overrides", "tier", "kwargs"), _CASES, ids=[c[0] for c in _CASES]
)
def test_generate_matches_legacy(
    label: str, overrides: dict[str, Any], tier: CostTier, kwargs: dict[str, Any]
) -> None:
    assert _run(golden_openrouter, overrides, tier, kwargs) == _run(
        legacy_openrouter, overrides, tier, kwargs
    ), label


def test_cases_are_discriminating() -> None:
    # 성공·거부가 모두 나오고, 실제로 나간 요청 본문이 서로 다르다(공허한 일치가 아니다)
    runs = [_run(golden_openrouter, o, t, k) for _, o, t, k in _CASES]
    assert {r[0][0] for r in runs} == {"ok", "err"}
    payloads = {repr(r[1][0]["payload"]) for r in runs if r[1]}
    assert len(_CASES) == 10 and len(payloads) >= 5


def test_status_check_matches_legacy() -> None:
    for overrides in (
        {},
        {"openrouter_api_key": ""},
        {"openrouter_allowed_providers": ()},
        {"openrouter_allowed_providers": ("unknown-vendor",)},
    ):

        def status(module: Any, o: dict[str, Any] = overrides) -> Any:
            return asyncio.run(module.OpenRouterProvider(settings=_settings(**o)).check_status())

        golden, legacy = status(golden_openrouter), status(legacy_openrouter)
        assert (golden.configured, golden.allowed_providers, golden.jurisdiction, golden.error) == (
            legacy.configured,
            legacy.allowed_providers,
            legacy.jurisdiction,
            legacy.error,
        )


def test_factory_builds_same_seat_and_refuses_others() -> None:
    # openrouter(기본 좌석)는 옛 팩토리와 같은 이름의 제공자를 같은 설정으로 만든다
    settings = _settings()
    assert settings.cloud_provider == "openrouter"
    golden = golden_factory.build_cloud_provider(settings)
    legacy = legacy_factory.build_cloud_provider(settings)
    assert type(golden).__name__ == type(legacy).__name__ == "OpenRouterProvider"
    assert golden._resolved_settings is legacy._resolved_settings  # noqa: SLF001
    # 다른 좌석은 옛 팩토리라면 그 좌석을 만들지만, 골든은 조용히 바꾸지 않고 멈춘다
    for seat in ("deepseek", "anthropic"):
        other = _settings(cloud_provider=seat)
        assert type(legacy_factory.build_cloud_provider(other)).__name__ != "OpenRouterProvider"
        with pytest.raises(ValueError, match=seat):
            golden_factory.build_cloud_provider(other)
