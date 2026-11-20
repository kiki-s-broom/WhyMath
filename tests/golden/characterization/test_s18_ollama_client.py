"""S18 특성화 — 옛 `FixedModelOllamaProvider`와 골든 복사본(`golden.sim.ollama_client`)이 같은 입력에 같은 출력을 낸다.

대상(옛 → 골든): `whymath_backend/l3/providers/ollama.py`의 `FixedModelOllamaProvider.generate`
(호출 인자 조립 · 응답 텍스트·토큰·지연·모델 태그 추출 · LOCAL 아닌 결정 거부)
→ `src/backend/golden/sim/ollama_client.py`.

맞는지는 묻지 않는다 — 서로 같은지만 본다. 데몬은 쓰지 않는다(가짜 클라이언트 주입).
옛 모듈은 이 테스트에서만 import한다(골든 패키지는 import하지 않는다 — test_import_budget.py).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from golden.sim import ollama_client as golden_ollama
from whymath_backend.l3.models import CostTier, LocalModelTier, ModelFamily, RoutingDecision
from whymath_backend.l3.providers import ollama as legacy_ollama


class _FakeClient:
    """받은 호출 인자를 기록하고 정해 둔 응답을 돌려주는 가짜 ollama 클라이언트."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response

    async def list(self) -> Any:
        return {"models": []}


def _decision(tier: CostTier = CostTier.LOCAL) -> RoutingDecision:
    """LOCAL(또는 클라우드) 라우팅 결정 1개."""
    if tier is CostTier.LOCAL:
        return RoutingDecision(
            cost_tier=tier,
            local_family=ModelFamily.GENERAL,
            local_model=LocalModelTier.MID,
            mode="sync",
            reason="t",
            est_latency_ms=1.0,
            est_cost_krw=0.0,
        )
    return RoutingDecision(
        cost_tier=tier,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="t",
        est_latency_ms=1.0,
        est_cost_krw=1.0,
    )


# 입력 10개 — (생성자 인자, generate 키워드, 응답)
_CASES: list[tuple[dict[str, Any], dict[str, Any], Any]] = [
    ({}, {}, {"response": "안녕", "prompt_eval_count": 10, "eval_count": 3, "model": "m:7b"}),
    ({}, {"temperature": 0.8}, {"response": "", "thinking": "생각만"}),
    ({}, {"seed": 7}, {"response": None, "eval_count": True}),
    ({"num_ctx": 2048}, {"top_p": 0.9}, {"response": "a", "prompt_eval_count": -1}),
    ({"num_predict": 40}, {"temperature": 0.0, "seed": 0}, {"response": "b", "model": "  "}),
    ({"num_ctx": 1, "num_predict": 2}, {"temperature": 1.5, "top_p": 0.1, "seed": 3}, {}),
    ({}, {}, None),
    ({}, {}, "문자열 응답"),
    ({}, {"temperature": 0.5}, {"response": 123, "thinking": "대체"}),
    ({"num_predict": 100}, {}, {"response": "줄1\n줄2", "eval_count": 5, "model": "q:7b"}),
]


def _run(provider: Any, kwargs: dict[str, Any]) -> Any:
    return asyncio.run(provider.generate("사용자", "시스템", _decision(), **kwargs))


@pytest.mark.parametrize(("ctor", "kwargs", "response"), _CASES)
def test_same_call_and_result(ctor: dict[str, Any], kwargs: dict[str, Any], response: Any) -> None:
    legacy_client, golden_client = _FakeClient(response), _FakeClient(response)
    legacy = legacy_ollama.FixedModelOllamaProvider("m:7b", client=legacy_client, **ctor)
    golden = golden_ollama.FixedModelOllamaProvider("m:7b", client=golden_client, **ctor)
    a, b = _run(legacy, kwargs), _run(golden, kwargs)
    assert legacy_client.calls == golden_client.calls
    assert a.text == b.text
    # 지연은 실측이라 값이 다르다 — 지연을 뺀 나머지가 같은지 본다
    assert replace(a.usage, latency_ms=0.0) == replace(b.usage, latency_ms=0.0)


@pytest.mark.parametrize("tier", [CostTier.CLOUD_MID, CostTier.CLOUD_HIGH])
def test_both_refuse_cloud_decision(tier: CostTier) -> None:
    legacy_client, golden_client = _FakeClient({}), _FakeClient({})
    legacy = legacy_ollama.FixedModelOllamaProvider("m", client=legacy_client)
    golden = golden_ollama.FixedModelOllamaProvider("m", client=golden_client)
    for provider in (legacy, golden):
        with pytest.raises(ValueError, match="로컬 결정만"):
            asyncio.run(provider.generate("u", "s", _decision(tier)))
    assert legacy_client.calls == golden_client.calls == []  # 호출 0회


def test_jurisdiction_is_domestic_on_both() -> None:
    legacy = legacy_ollama.FixedModelOllamaProvider("m", client=_FakeClient({}))
    golden = golden_ollama.FixedModelOllamaProvider("m", client=_FakeClient({}))
    assert legacy.jurisdiction == golden.jurisdiction
