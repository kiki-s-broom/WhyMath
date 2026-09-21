"""explanation_generator(연령별 설명 생성기) 단위 테스트 — hermetic(FakeProvider·라이브 LLM 0).

검증 축: ①라우터 경유(저작 패밀리 GENERAL 스왑) ②DRAFT 산출 형태·원문 동봉(환각 방지)
③상태기계 재사용(prescreen→review) + F7 언어 수준 게이트 ④실패 폴백(None).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest

from whymath_backend.l3.models import GenerationResult, ModelFamily, RoutingDecision
from whymath_backend.l3.pedagogy.explanation_generator import (
    ExplanationGenerator,
    ExplanationTarget,
    build_explanation_draft_row,
    run_explanation_review,
)
from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.speech import SpeechGradeBand

_GOOD_EXPLANATION = "분수는 전체를 똑같이 나눈 것 중 몇 조각인지를 나타내는 수다."
_GOOD_JSON = json.dumps({"explanation": _GOOD_EXPLANATION}, ensure_ascii=False)

_ARITHMETIC_ONLY: frozenset[str] = frozenset({"fraction", "power", "abs", "factorial"})
_FULL: frozenset[str] = _ARITHMETIC_ONLY | {
    "root",
    "subscript",
    "trig",
    "log",
    "integral",
    "sum",
    "product",
    "limit",
    "derivative",
    "binom",
}
_CONSTRUCTS_BY_BAND: dict[SpeechGradeBand, frozenset[str]] = {
    SpeechGradeBand.초등: _ARITHMETIC_ONLY,
    SpeechGradeBand.중등: _ARITHMETIC_ONLY | {"root", "subscript", "trig"},
    SpeechGradeBand.고등: _FULL,
    SpeechGradeBand.대학: _FULL,
}


class FakeProvider:
    """스크립트 응답 provider 대역 — LLMProvider 충족(네트워크 0·analogy_generator 테스트 미러)."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.calls: list[tuple[str, str]] = []
        self.decisions: list[RoutingDecision] = []
        self.temperatures: list[float | None] = []

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
        self.decisions.append(decision)
        self.temperatures.append(temperature)
        text = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return GenerationResult(text=text)


class BrokenProvider:
    """항상 던지는 provider — 안전 폴백(None) 검증용."""

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
        raise RuntimeError("provider 다운(테스트)")


class _NullTrace:
    def record(self, fields: dict[str, object]) -> None:
        del fields


def _generator(provider: object) -> ExplanationGenerator:
    return ExplanationGenerator(provider, trace=_NullTrace())  # type: ignore[arg-type]


_TARGET = ExplanationTarget(
    code="N1",
    name="분수",
    subject="초등수학",
    band=SpeechGradeBand.초등,
    source_explanation="분수란 전체를 등분한 것 중 일부를 나타내는 수다.",
)


class TestExplanationTarget:
    def test_rejects_blank_source_explanation(self) -> None:
        """재표현할 원문이 없으면 표적 구성 자체를 거부(환각 방지 설계)."""
        with pytest.raises(ValueError):
            ExplanationTarget(
                code="N1",
                name="분수",
                subject="초등수학",
                band=SpeechGradeBand.초등,
                source_explanation="   ",
            )


class TestAgenerateDraft:
    """async 호출부용 경로 — 이미 실행 중인 이벤트 루프 안에서도 안전해야 한다(자체 루프 재진입
    금지 — `l4/pedagogy/age_band_explanation.py`가 이 경로만 쓰는 이유)."""

    async def test_returns_same_shape_as_sync_wrapper(self) -> None:
        provider = FakeProvider([_GOOD_JSON])
        row = await _generator(provider).agenerate_draft(_TARGET)
        assert row is not None
        assert row["status"] == "DRAFT"
        assert row["payload"]["body"] == _GOOD_EXPLANATION

    async def test_provider_failure_returns_none(self) -> None:
        assert await _generator(BrokenProvider()).agenerate_draft(_TARGET) is None

    async def test_callable_inside_already_running_event_loop(self) -> None:
        """이 테스트 자체가 실행 중인 이벤트 루프 안이다 — 크래시 없이 완주하면 회귀 봉인."""
        provider = FakeProvider([_GOOD_JSON])
        row = await _generator(provider).agenerate_draft(_TARGET)
        assert row is not None


class TestGenerateDraft:
    def test_routes_via_router_with_authoring_family_swap(self) -> None:
        provider = FakeProvider([_GOOD_JSON])
        row = _generator(provider).generate_draft(_TARGET)
        assert row is not None
        decision = provider.decisions[0]
        assert decision.cost_tier == "local"
        assert decision.local_family == ModelFamily.GENERAL.value
        assert "저작:general" in decision.reason

    def test_draft_row_shape_and_status(self) -> None:
        row = _generator(FakeProvider([_GOOD_JSON])).generate_draft(_TARGET)
        assert row is not None
        assert row["status"] == "DRAFT"
        assert row["id"] == "explanation:N1:초등"
        assert row["target_code"] == "N1"
        assert row["band"] == SpeechGradeBand.초등
        assert row["sympy_verified"] is None
        assert row["payload"]["reasoning_type"] == "age_band_explanation"
        assert row["payload"]["structure_tags"] == ["explanation", "초등"]

    def test_source_explanation_and_band_reach_prompt(self) -> None:
        """원문 동봉(재표현 대상)·레지스터가 프롬프트에 실린다(환각 방지·파라미터화 검증)."""
        provider = FakeProvider([_GOOD_JSON])
        _generator(provider).generate_draft(_TARGET)
        prompt, _system = provider.calls[0]
        assert _TARGET.source_explanation in prompt
        assert "초등" in prompt

    def test_forbidden_vocabulary_reaches_prompt(self) -> None:
        provider = FakeProvider([_GOOD_JSON])
        target = ExplanationTarget(
            code="N1",
            name="분수",
            subject="초등수학",
            band=SpeechGradeBand.초등,
            source_explanation="분수란 전체를 등분한 것 중 일부를 나타내는 수다.",
            forbidden_vocabulary=("미분", "적분"),
        )
        _generator(provider).generate_draft(target)
        prompt, _system = provider.calls[0]
        assert "미분" in prompt and "적분" in prompt

    def test_provider_failure_returns_none(self) -> None:
        assert _generator(BrokenProvider()).generate_draft(_TARGET) is None

    def test_json_garbage_returns_none(self) -> None:
        assert _generator(FakeProvider(["JSON 아님"])).generate_draft(_TARGET) is None

    def test_missing_explanation_field_returns_none(self) -> None:
        no_field = json.dumps({"foo": "bar"}, ensure_ascii=False)
        assert _generator(FakeProvider([no_field])).generate_draft(_TARGET) is None

    def test_code_fence_tolerated(self) -> None:
        fenced = f"```json\n{_GOOD_JSON}\n```"
        assert _generator(FakeProvider([fenced])).generate_draft(_TARGET) is not None


class TestRunExplanationReview:
    def test_clean_draft_at_appropriate_band_approved(self) -> None:
        row = build_explanation_draft_row(_TARGET, _GOOD_EXPLANATION)
        outcome = run_explanation_review([row], introduced_constructs_by_band=_CONSTRUCTS_BY_BAND)[
            0
        ]
        assert outcome.status == "APPROVED"
        assert outcome.reject_reason is None
        assert outcome.prescreen_score >= 2

    def test_unintroduced_construct_vocabulary_rejected_with_f7(self) -> None:
        """초등 밴드인데 '미분' 어휘가 섞이면 F7로 반려된다(EOS-98 신설 게이트)."""
        row = build_explanation_draft_row(_TARGET, "미분은 순간의 변화율을 구하는 방법이다.")
        outcome = run_explanation_review([row], introduced_constructs_by_band=_CONSTRUCTS_BY_BAND)[
            0
        ]
        assert outcome.status == "REJECTED"
        assert outcome.reject_reason == GenerationFailureCode.F7.value

    def test_same_vocabulary_passes_for_appropriate_band(self) -> None:
        """같은 어휘라도 이미 도입된 밴드(고등)에서는 통과한다(밴드 파라미터화 검증)."""
        target = ExplanationTarget(
            code="N1",
            name="미분",
            subject="수학Ⅱ",
            band=SpeechGradeBand.고등,
            source_explanation="미분은 함수의 순간 변화율이다.",
        )
        row = build_explanation_draft_row(target, "미분은 순간의 변화율을 구하는 방법이다.")
        outcome = run_explanation_review([row], introduced_constructs_by_band=_CONSTRUCTS_BY_BAND)[
            0
        ]
        assert outcome.status == "APPROVED"

    def test_structural_defect_rejected_by_reused_gate(self) -> None:
        """빈 본문은 기존 review_slot 게이트가 반려 — 상태기계 재사용의 실증(새 게이트 아님)."""
        row = build_explanation_draft_row(_TARGET, "   ")
        outcome = run_explanation_review([row], introduced_constructs_by_band=_CONSTRUCTS_BY_BAND)[
            0
        ]
        assert outcome.status == "REJECTED"
        assert outcome.reject_reason == "empty_body"

    def test_missing_band_profile_defaults_to_no_introduced_constructs(self) -> None:
        """주입 맵에 밴드가 없으면 도입 구조 0(보수적 fail-closed) — 빈 dict라도 크래시 없음."""
        row = build_explanation_draft_row(_TARGET, "이것은 오늘의 날씨 이야기다.")
        outcome = run_explanation_review([row], introduced_constructs_by_band={})[0]
        assert outcome.status == "APPROVED"  # 구조 어휘가 없는 본문이라 F7 대상이 아님
