"""CompositeProvider 단위테스트 — cost_tier 디스패치 (로컬↔클라우드, 라이브 없음).

검증 핵심(S5):
  - 디스패치: LOCAL→local.generate, CLOUD_MID/HIGH→cloud.generate (위임 정확성).
  - cloud=None인데 클라우드 결정 → 명확한 RuntimeError(조용한 강등 금지).
  - 상태 분리: check_status=로컬 위임(OllamaStatus), check_cloud_status=클라우드 위임
    (AnthropicStatus|None). 기능 미노출 provider는 비크래시로 흡수.

설계 정본: docs/architecture/03a_l3_router_design.md §A.0·§C.1·§C.4.
"""

from __future__ import annotations

from typing import Any

import pytest

from whymath_backend.l3.interfaces import LLMProvider
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
)
from whymath_backend.l3.providers.anthropic import AnthropicStatus
from whymath_backend.l3.providers.composite import CompositeProvider
from whymath_backend.l3.providers.ollama import ModelAvailability, OllamaStatus


class FakeProvider:
    """generate + check_status를 노출하는 가짜 제공자(로컬·클라우드 양쪽 모사)."""

    def __init__(self, *, text: str = "out", status: Any = None) -> None:
        self._text = text
        self._status = status
        self.calls: list[tuple[str, str, RoutingDecision]] = []
        self.temperatures: list[float | None] = []
        self.json_schemas: list[Any] = []
        # EOS-121 A — 위임 호출의 kwargs를 **그대로** 보관한다. 키 부재와 None을 구분하려면
        # 파라미터 기본값으로 받아서는 안 된다(둘 다 None으로 보인다).
        self.forwarded_kwargs: list[dict[str, Any]] = []

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        **kwargs: Any,
    ) -> GenerationResult:
        self.calls.append((prompt, system, decision))
        self.temperatures.append(kwargs.get("temperature"))
        self.json_schemas.append(kwargs.get("json_schema"))
        self.forwarded_kwargs.append(dict(kwargs))
        return GenerationResult(self._text)

    async def check_status(self) -> Any:
        return self._status


class NoStatusProvider:
    """check_status가 없는 가짜 제공자 — 기능 탐지 분기 검증용."""

    def __init__(self, *, text: str = "out") -> None:
        self._text = text
        self.calls: list[tuple[str, str, RoutingDecision]] = []

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision
    ) -> GenerationResult:
        self.calls.append((prompt, system, decision))
        return GenerationResult(self._text)


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


# ──────────────────────────────────────────────────────────────────────────
# generate — 디스패치
# ──────────────────────────────────────────────────────────────────────────
class TestDispatch:
    async def test_local_goes_to_local(self) -> None:
        local = FakeProvider(text="로컬결과")
        cloud = FakeProvider(text="클라우드결과")
        composite = CompositeProvider(local=local, cloud=cloud)

        out = await composite.generate("p", "s", _local_decision())

        assert out.text == "로컬결과"
        assert len(local.calls) == 1
        assert cloud.calls == []

    async def test_cloud_mid_goes_to_cloud(self) -> None:
        local = FakeProvider(text="로컬결과")
        cloud = FakeProvider(text="클라우드결과")
        composite = CompositeProvider(local=local, cloud=cloud)

        out = await composite.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))

        assert out.text == "클라우드결과"
        assert len(cloud.calls) == 1
        assert local.calls == []

    async def test_cloud_high_goes_to_cloud(self) -> None:
        local = FakeProvider()
        cloud = FakeProvider(text="opus")
        composite = CompositeProvider(local=local, cloud=cloud)

        out = await composite.generate("p", "s", _cloud_decision(CostTier.CLOUD_HIGH))

        assert out.text == "opus"
        assert len(cloud.calls) == 1

    async def test_cloud_decision_without_cloud_provider_raises(self) -> None:
        """cloud=None인데 클라우드 결정 → 명확한 오류(조용한 강등 금지)."""
        composite = CompositeProvider(local=FakeProvider())
        with pytest.raises(RuntimeError, match="클라우드 제공자가 미구성"):
            await composite.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID))

    async def test_local_decision_works_without_cloud_provider(self) -> None:
        """cloud=None이어도 로컬 결정은 정상 처리된다(로컬 전용 배포)."""
        local = FakeProvider(text="로컬전용")
        composite = CompositeProvider(local=local)
        out = await composite.generate("p", "s", _local_decision())
        assert out.text == "로컬전용"

    async def test_temperature_forwarded_to_target(self) -> None:
        """S2-g: temperature는 위임받는 제공자로 그대로 전달된다."""
        local = FakeProvider()
        composite = CompositeProvider(local=local)
        await composite.generate("p", "s", _local_decision(), temperature=0.9)
        assert local.temperatures == [0.9]

    async def test_top_p_forwarded_to_target(self) -> None:
        """EOS-121 A: top_p는 위임받는 제공자로 **그 값 그대로** 전달된다(삼키지 않는다)."""
        local = FakeProvider()
        composite = CompositeProvider(local=local)
        await composite.generate("p", "s", _local_decision(), top_p=0.95)
        assert local.forwarded_kwargs[0]["top_p"] == 0.95

    async def test_top_p_key_absent_when_unset(self) -> None:
        """EOS-121 A: 미지정이면 위임 호출에 top_p **키 자체가 없다**(None 전송 금지).

        하위 제공자가 "키가 없다"와 "None이 왔다"를 다르게 다룰 수 있으므로(예 payload에
        `top_p: null`을 싣는 구현) 둘을 구분해 동결한다.
        """
        local = FakeProvider()
        composite = CompositeProvider(local=local)
        await composite.generate("p", "s", _local_decision())
        assert "top_p" not in local.forwarded_kwargs[0]

    async def test_top_p_forwarded_to_cloud_seat_too(self) -> None:
        """EOS-121 A: 클라우드 분기에서도 같은 값이 전달된다 — 좌석 대칭의 디스패처 축."""
        local, cloud = FakeProvider(), FakeProvider()
        composite = CompositeProvider(local=local, cloud=cloud)
        await composite.generate("p", "s", _cloud_decision(CostTier.CLOUD_MID), top_p=0.95)
        assert cloud.forwarded_kwargs[0]["top_p"] == 0.95
        assert local.forwarded_kwargs == []

    async def test_temperature_omitted_by_default(self) -> None:
        """온도 미지정이면 하위 제공자에 temperature를 싣지 않는다(기본 None·하위호환)."""
        local = FakeProvider()
        composite = CompositeProvider(local=local)
        await composite.generate("p", "s", _local_decision())
        assert local.temperatures == [None]

    async def test_json_schema_forwarded_to_target(self) -> None:
        """S2-j: json_schema는 위임받는 제공자로 그대로 전달된다(제약 처리는 하위 책임)."""
        local = FakeProvider()
        composite = CompositeProvider(local=local)
        schema = {"type": "object", "required": ["answer"]}
        await composite.generate("p", "s", _local_decision(), json_schema=schema)
        assert local.json_schemas == [schema]

    async def test_json_schema_omitted_by_default(self) -> None:
        """스키마 미지정이면 하위 제공자에 json_schema를 싣지 않는다(기본 None·하위호환)."""
        local = FakeProvider()
        composite = CompositeProvider(local=local)
        await composite.generate("p", "s", _local_decision())
        assert local.json_schemas == [None]


# ──────────────────────────────────────────────────────────────────────────
# check_status / check_cloud_status — 상태 분리 위임
# ──────────────────────────────────────────────────────────────────────────
class TestStatus:
    async def test_check_status_delegates_to_local(self) -> None:
        status = OllamaStatus(reachable=True, models=(ModelAvailability("qwen2-math:1.5b", True),))
        composite = CompositeProvider(local=FakeProvider(status=status), cloud=FakeProvider())
        result = await composite.check_status()
        assert result is status

    async def test_check_status_local_without_check_method(self) -> None:
        """로컬이 check_status 미노출 → 도달 불가로 보고(비크래시)."""
        composite = CompositeProvider(local=NoStatusProvider())
        result = await composite.check_status()
        assert result.reachable is False
        assert result.error is not None

    async def test_check_cloud_status_delegates_to_cloud(self) -> None:
        status = AnthropicStatus(configured=True, reachable=True)
        composite = CompositeProvider(local=FakeProvider(), cloud=FakeProvider(status=status))
        result = await composite.check_cloud_status()
        assert result is status

    async def test_check_cloud_status_none_when_no_cloud(self) -> None:
        composite = CompositeProvider(local=FakeProvider())
        assert await composite.check_cloud_status() is None

    async def test_check_cloud_status_none_when_cloud_has_no_check(self) -> None:
        composite = CompositeProvider(local=FakeProvider(), cloud=NoStatusProvider())
        assert await composite.check_cloud_status() is None


def test_composite_satisfies_llm_provider_protocol() -> None:
    """CompositeProvider는 LLMProvider Protocol을 충족한다(runtime_checkable)."""
    assert isinstance(CompositeProvider(local=FakeProvider()), LLMProvider)
