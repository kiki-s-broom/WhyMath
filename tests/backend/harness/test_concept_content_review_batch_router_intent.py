"""OPS-110 — 리뷰 배치가 `Router`를 거치지 않는 것이 *의도*임을 동결하고, 그 우회가 클라우드로 새지
않음을 계약으로 못박는다.

판정(근거는 `_assess_one` docstring): 이 배치는 `--model`로 지정한 *한 모델*의 판정력(주입 결함
검출률·Wilson 상한)을 잰다. 라우터를 끼우면 표본마다 모델이 달라져 수치가 섞인 모집단의 것이 된다.
다만 "라우터 우회"가 허용되는 것은 *로컬 고정*일 때뿐이다 — 그 경계가 이 파일이 막는 것이다:

  ① 모든 티어가 LOCAL·비용 0 `RoutingDecision`을 만든다(클라우드 티어로 가는 값이 없다)
  ② `_build_provider`가 모든 티어에서 `OllamaProvider`만 만든다(클라우드 provider 불가)
  ③ 티어 표의 값이 `LocalModelTier`·`ModelFamily`의 실재 값이다(오타·미정의 티어로 조용히 다른 모델)
  ④ 이 모듈이 `Router`를 도입하면 docstring의 판정이 낡으므로 RED — 바꾸려면 판정을 다시 한다
  ⑤ `_assess_one` docstring이 의도 판정(OPS-110)과 한계(Langfuse 미추적)를 적고 있다
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.db.models.concept_content import (
    CONTENT_REVIEW_STATUS_AI_ESTIMATED,
    CONTENT_SCOPE_K12,
)
from whymath_backend.harness import concept_content_review_batch as ccrb
from whymath_backend.l1.concept_content.projection import ConceptContentRecord
from whymath_backend.l3.models import CostTier, GenerationResult, LocalModelTier, ModelFamily, Usage

_SRC = Path(ccrb.__file__)


def _record() -> ConceptContentRecord:
    return ConceptContentRecord(
        code="N1",
        scope=CONTENT_SCOPE_K12,
        name="x",
        subject="s",
        unit=None,
        metaphor=None,
        misconception=None,
        formal_definition_internal=None,
        accepted_expressions=None,
        explanation=None,
        standard_codes=(),
        flashcards=(),
        review_status=CONTENT_REVIEW_STATUS_AI_ESTIMATED,
    )


class _Recorder:
    """받은 `decision`을 그대로 기록하는 provider — 어떤 모델·티어로 불렀는지를 본다."""

    def __init__(self) -> None:
        self.decisions: list[Any] = []

    async def generate(self, prompt: str, system: str, decision: Any, **kw: object) -> Any:
        self.decisions.append(decision)
        text = '{"passed": true, "defects": [], "reason": "ok"}'
        return GenerationResult(text=text, usage=Usage(input_tokens=1, output_tokens=1))


@pytest.mark.parametrize("tier", sorted(ccrb._MODEL_TIER_MAP))
class TestEveryTierStaysLocal:
    async def test_decision_is_local_and_free(self, tier: str) -> None:
        rec = _Recorder()
        await ccrb._assess_one(rec, _record(), model_tier=tier)
        assert len(rec.decisions) == 1  # 스캔 0건·다중 호출 방지
        d = rec.decisions[0]
        assert d.cost_tier == CostTier.LOCAL
        assert d.est_cost_krw == 0.0
        assert d.local_model in set(LocalModelTier)

    def test_provider_is_ollama_only(self, tier: str) -> None:
        from whymath_backend.l3.providers.ollama import OllamaProvider

        assert isinstance(ccrb._build_provider(tier), OllamaProvider)


class TestTierTableIsWellFormed:
    def test_every_entry_names_real_enum_values(self) -> None:
        assert ccrb._MODEL_TIER_MAP  # 비어 있으면 위 parametrize가 공허하게 통과한다
        for tier, (family, size) in ccrb._MODEL_TIER_MAP.items():
            LocalModelTier(size)  # 미정의 크기면 ValueError
            if family is not None:
                ModelFamily(family)
            assert tier  # 키가 빈 문자열이 아니다

    def test_unknown_tier_is_refused_not_defaulted(self) -> None:
        with pytest.raises(ValueError):
            ccrb._build_provider("cloud:mid")


class TestBypassIsRecordedAsIntent:
    def test_module_does_not_use_router(self) -> None:
        tree = ast.parse(_SRC.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.Name):
                names.add(node.id)
        assert "Router" not in names, (
            "리뷰 배치가 Router 를 쓰기 시작했다 — `_assess_one` docstring 의 OPS-110 판정"
            "(고정 모델 측정이라 우회가 의도)이 낡았다. 판정을 다시 하고 docstring 을 고쳐라."
        )

    def test_assess_one_docstring_carries_the_verdict_and_the_limit(self) -> None:
        doc = ccrb._assess_one.__doc__ or ""
        assert "OPS-110" in doc
        assert "의도" in doc
        assert "Langfuse" in doc  # 한계를 숨기지 않는다
