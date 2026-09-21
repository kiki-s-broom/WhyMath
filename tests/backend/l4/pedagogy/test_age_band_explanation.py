"""age_band_explanation(EOS-98 공개 진입점) 단위 테스트 — hermetic(FakeSession·FakeProvider).

검증 축: ①원문 부재 시 None 폴백(환각 방지 표적 불변식과 정합) ②단일 밴드 생성·검수 완주
③4개 밴드 전량("동일 개념 다수준 설명") — generator 인스턴스 공유(루프 재사용) 확인.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pytest

from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l3.pedagogy.explanation_generator import ExplanationGenerator
from whymath_backend.l4.pedagogy.age_band_explanation import (
    AGE_BANDS,
    explain_concept_all_bands,
    explain_concept_at_age_band,
)
from whymath_backend.schema.speech import SpeechGradeBand


@dataclass
class _FakeConceptContent:
    code: str
    name: str
    subject: str
    explanation: str | None


class _FakeSession:
    """`session.get(Model, pk)` 대역 — resolve.get_concept_content가 소비하는 API만 충족."""

    def __init__(self, content: _FakeConceptContent | None) -> None:
        self._content = content

    async def get(self, model: object, pk: str) -> _FakeConceptContent | None:
        del model
        if self._content is not None and self._content.code == pk:
            return self._content
        return None


class FakeProvider:
    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.calls: list[tuple[str, str]] = []

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        self.calls.append((prompt, system))
        text = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return GenerationResult(text=text)


class _NullTrace:
    def record(self, fields: dict[str, object]) -> None:
        del fields


def _generator(provider: object) -> ExplanationGenerator:
    return ExplanationGenerator(provider, trace=_NullTrace())  # type: ignore[arg-type]


_GOOD_JSON = json.dumps(
    {"explanation": "분수는 전체를 똑같이 나눈 것 중 몇 조각인지를 나타낸다."},
    ensure_ascii=False,
)


class TestExplainConceptAtAgeBand:
    @pytest.mark.asyncio
    async def test_missing_concept_content_returns_none(self) -> None:
        session = _FakeSession(None)
        outcome = await explain_concept_at_age_band(
            session, "N1", SpeechGradeBand.초등, generator=_generator(FakeProvider([_GOOD_JSON]))
        )
        assert outcome is None

    @pytest.mark.asyncio
    async def test_blank_source_explanation_returns_none(self) -> None:
        session = _FakeSession(_FakeConceptContent("N1", "분수", "초등수학", None))
        outcome = await explain_concept_at_age_band(
            session, "N1", SpeechGradeBand.초등, generator=_generator(FakeProvider([_GOOD_JSON]))
        )
        assert outcome is None

    @pytest.mark.asyncio
    async def test_generates_and_reviews_single_band(self) -> None:
        session = _FakeSession(
            _FakeConceptContent("N1", "분수", "초등수학", "분수란 전체를 등분한 것 중 일부다.")
        )
        provider = FakeProvider([_GOOD_JSON])
        outcome = await explain_concept_at_age_band(
            session, "N1", SpeechGradeBand.초등, generator=_generator(provider)
        )
        assert outcome is not None
        assert outcome.status == "APPROVED"
        # 원문이 프롬프트에 동봉됐다(환각 방지 — L4가 L1 조회 결과를 표적에 실었다는 증거).
        prompt, _system = provider.calls[0]
        assert "분수란 전체를 등분한 것 중 일부다." in prompt

    @pytest.mark.asyncio
    async def test_unintroduced_vocabulary_generation_rejected_with_f7(self) -> None:
        """초등 표적인데 LLM이 '미분' 어휘를 섞어 냈다면 F7로 반려된다(생성 실측 시나리오)."""
        session = _FakeSession(
            _FakeConceptContent("N1", "분수", "초등수학", "분수란 전체를 등분한 것 중 일부다.")
        )
        bad_json = json.dumps(
            {"explanation": "분수는 미분처럼 순간의 변화를 재는 것과 비슷하다."},
            ensure_ascii=False,
        )
        outcome = await explain_concept_at_age_band(
            session, "N1", SpeechGradeBand.초등, generator=_generator(FakeProvider([bad_json]))
        )
        assert outcome is not None
        assert outcome.status == "REJECTED"
        assert outcome.reject_reason == "F7"


class TestExplainConceptAllBands:
    @pytest.mark.asyncio
    async def test_generates_all_four_bands(self) -> None:
        """동일 개념 다수준 설명 생성 — 4개 밴드 전량 생성(EOS-98 acceptance ③ 핵심 문구)."""
        session = _FakeSession(
            _FakeConceptContent("N1", "분수", "초등수학", "분수란 전체를 등분한 것 중 일부다.")
        )
        provider = FakeProvider([_GOOD_JSON] * 4)
        results = await explain_concept_all_bands(session, "N1", generator=_generator(provider))
        assert set(results.keys()) == set(AGE_BANDS)
        assert len(AGE_BANDS) == 4
        assert all(outcome is not None for outcome in results.values())
        assert len(provider.calls) == 4
