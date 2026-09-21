"""교수법 렌더 어댑터 테스트 — 방식 분화·결정론·조사 일치·render→SymPy verify."""

from __future__ import annotations

import pytest

from whymath_backend.composition import (
    default_assessment_answer_verifier,
    default_expression_seal,
)
from whymath_backend.l3.render.adapter import NullAdapter, PedagogyAdapter, RenderContext
from whymath_backend.l3.render.dsl import ConceptAssessment, ConceptDSL
from whymath_backend.l3.render.registry import get_adapter, registered_strategies
from whymath_backend.l3.verify_answer import verify_answer
from whymath_backend.schema.enums import PedagogyStrategy


def _adapter(strategy: PedagogyStrategy) -> PedagogyAdapter:
    """레지스트리 조회 + **과목 능력 주입**(EOS-89).

    어댑터는 더 이상 합성 루트를 스스로 부르지 않는다 — 능력은 상류가 준다. 프로덕션에서 그
    상류는 `api/study.py`(app.state 등록분)이고, 이 파일에서는 **테스트 자신이 상류**다
    (프로세스가 여기서 시작하므로 합성 루트를 소비해도 되는 자리).
    """
    return get_adapter(
        strategy,
        seal=default_expression_seal(),
        assessment_verifier=default_assessment_answer_verifier(),
    )


def _dsl(**overrides: object) -> ConceptDSL:
    """테스트용 중립 DSL — 개념 이름은 조사 판정(받침 有)을 태우도록 고른다."""
    base: dict[str, object] = {
        "code": "C1",
        "name": "일차식",
        "subject": "중등수학",
        "definition": "미지수의 차수가 1인 식.",
        "intuition": "저울의 균형을 맞추는 일과 같다.",
        "examples": ("2x + 3",),
    }
    base.update(overrides)
    return ConceptDSL(**base)  # type: ignore[arg-type]


def _assessed_dsl() -> ConceptDSL:
    """평가 재료가 있는 DSL — x - 1 = 0 의 해 x = 1(참)."""
    return _dsl(
        assessment=ConceptAssessment(conditions=("x - 1 = 0",), answer_map={"x": "1"}),
    )


class TestRegistry:
    """레지스트리 — 전략 1개 = 어댑터 1개, 미구현은 명확히 거부."""

    def test_five_strategies_implemented(self) -> None:
        assert registered_strategies() == {
            PedagogyStrategy.DIRECT,
            PedagogyStrategy.SOCRATIC,
            PedagogyStrategy.WORKED_EXAMPLE,
            PedagogyStrategy.PROBLEM_BASED,
            PedagogyStrategy.ANALOGY,
        }

    def test_unimplemented_strategy_raises_not_silent_fallback(self) -> None:
        # 조용한 대체 금지 — 요청과 다른 방식의 수업을 주지 않는다.
        with pytest.raises(LookupError, match="등록되지 않았습니다"):
            _adapter(PedagogyStrategy.RETRIEVAL)

    def test_adapters_satisfy_protocol(self) -> None:
        for strategy in registered_strategies():
            assert isinstance(_adapter(strategy), PedagogyAdapter)

    def test_adapter_strategy_matches_registry_key(self) -> None:
        for strategy in registered_strategies():
            assert _adapter(strategy).strategy is strategy


class TestNullAdapterStub:
    """테스트용 스텁 — Protocol 준수·레지스트리 배선 검사를 라이브 구현 없이 가능하게 한다."""

    def test_stub_satisfies_protocol_and_renders(self) -> None:
        stub = NullAdapter(PedagogyStrategy.RETRIEVAL)
        assert isinstance(stub, PedagogyAdapter)
        assert stub.strategy is PedagogyStrategy.RETRIEVAL
        assert stub.can_render(_dsl()) is True
        unit = stub.render(_dsl(), RenderContext())
        assert unit.segments[0].content == "일차식"
        assert unit.ok is True


class TestSameContentDifferentMethod:
    """같은 DSL이 전략별로 *다른* 화면을 낸다 — 콘텐츠 하나, 방식 N개."""

    def test_direct_presents_definition(self) -> None:
        unit = _adapter(PedagogyStrategy.DIRECT).render(_dsl(), RenderContext())
        kinds = [seg.kind for seg in unit.segments]
        assert "definition" in kinds
        assert "question" not in kinds  # 설명 중심 — 발문으로 끌지 않는다.

    def test_socratic_withholds_definition_and_asks(self) -> None:
        unit = _adapter(PedagogyStrategy.SOCRATIC).render(_dsl(), RenderContext())
        kinds = [seg.kind for seg in unit.segments]
        assert "question" in kinds
        # 소크라테스식의 요점 — 정의를 주지 않는다(학생이 답할 자리를 비운다).
        assert "definition" not in kinds

    def test_problem_based_leads_with_problem_and_hides_answer(self) -> None:
        dsl = _assessed_dsl()
        unit = _adapter(PedagogyStrategy.PROBLEM_BASED).render(dsl, RenderContext())
        assert unit.segments[1].kind == "prompt"  # heading 다음이 곧 문제.
        body = " ".join(seg.content for seg in unit.segments)
        assert "x - 1 = 0" in body
        # 정답을 싣지 않는다 — 학생이 스스로 도달해야 한다.
        assert "1로 구해집니다" not in body

    def test_worked_example_shows_solution_steps(self) -> None:
        unit = _adapter(PedagogyStrategy.WORKED_EXAMPLE).render(_assessed_dsl(), RenderContext())
        assert any(seg.kind == "solution_step" for seg in unit.segments)

    def test_analogy_leads_with_intuition_and_flags_limits(self) -> None:
        unit = _adapter(PedagogyStrategy.ANALOGY).render(_dsl(), RenderContext())
        assert unit.segments[1].kind == "intuition"
        # 비유를 정의로 오인하면 그 자체가 오개념이므로 한계를 반드시 짚는다.
        assert any(seg.kind == "reflection" for seg in unit.segments)


class TestCanRender:
    """재료가 없으면 False — 상위가 생성 경로로 폴백한다(빈 화면 금지)."""

    def test_problem_based_requires_assessment(self) -> None:
        assert _adapter(PedagogyStrategy.PROBLEM_BASED).can_render(_dsl()) is False
        assert _adapter(PedagogyStrategy.PROBLEM_BASED).can_render(_assessed_dsl()) is True

    def test_analogy_requires_intuition(self) -> None:
        adapter = _adapter(PedagogyStrategy.ANALOGY)
        assert adapter.can_render(_dsl(intuition=None)) is False

    def test_direct_requires_definition_or_intuition(self) -> None:
        adapter = _adapter(PedagogyStrategy.DIRECT)
        assert adapter.can_render(_dsl(definition=None, intuition=None)) is False

    def test_socratic_always_renderable(self) -> None:
        adapter = _adapter(PedagogyStrategy.SOCRATIC)
        assert adapter.can_render(_dsl(definition=None, intuition=None, examples=())) is True


class TestRenderVerify:
    """render→SymPy verify — 평가 재료를 실으면 정답이 기계 검증을 통과해야 노출된다."""

    def test_correct_assessment_passes_verification(self) -> None:
        dsl = _assessed_dsl()
        # 재료 자체가 Tier1 검증을 통과한다(어댑터가 쓰는 것과 같은 경로).
        verdict = verify_answer(list(dsl.assessment.conditions), dsl.assessment.answer_map)  # type: ignore[union-attr]
        assert verdict.state == "pass"

        unit = _adapter(PedagogyStrategy.WORKED_EXAMPLE).render(dsl, RenderContext())
        assert unit.ok is True
        assert unit.validation_signal is None

    def test_wrong_answer_is_flagged_not_exposed(self) -> None:
        # x - 1 = 0 인데 x = 2 라고 실으면 렌더는 실패 신호를 달고 나온다(조용한 통과 금지).
        dsl = _dsl(assessment=ConceptAssessment(conditions=("x - 1 = 0",), answer_map={"x": "2"}))
        unit = _adapter(PedagogyStrategy.WORKED_EXAMPLE).render(dsl, RenderContext())
        assert unit.ok is False
        assert unit.validation_signal is not None
        assert unit.validation_signal.kind == "solution"

    def test_failure_is_signalled_not_raised(self) -> None:
        dsl = _dsl(assessment=ConceptAssessment(conditions=("x - 1 = 0",), answer_map={"x": "2"}))
        # 예외를 던지지 않는다 — 상위가 폴백을 결정할 수 있어야 한다.
        unit = _adapter(PedagogyStrategy.PROBLEM_BASED).render(dsl, RenderContext())
        assert unit.validation_signal is not None


class TestDeterminismAndBindings:
    """결정론·light render 치환·조사 일치."""

    def test_render_is_deterministic(self) -> None:
        for strategy in registered_strategies():
            adapter = _adapter(strategy)
            dsl = _assessed_dsl()
            first = adapter.render(dsl, RenderContext())
            second = adapter.render(dsl, RenderContext())
            assert first == second

    def test_bindings_substitute_without_breaking_latex(self) -> None:
        dsl = _dsl(definition="계수가 {coef}인 식. 형태는 \\frac{a}{b} 이다.")
        unit = _adapter(PedagogyStrategy.DIRECT).render(dsl, RenderContext(bindings={"coef": "3"}))
        body = " ".join(seg.content for seg in unit.segments)
        assert "계수가 3인 식" in body
        assert "\\frac{a}{b}" in body  # LaTeX 중괄호는 건드리지 않는다.

    def test_josa_agrees_with_concept_name(self) -> None:
        # 받침 有('일차식') → '은', 받침 無('함수') → '는'. 개념명이 무엇이든 문법이 맞아야 한다.
        with_batchim = _adapter(PedagogyStrategy.SOCRATIC).render(
            _dsl(name="일차식"), RenderContext()
        )
        without_batchim = _adapter(PedagogyStrategy.SOCRATIC).render(
            _dsl(name="함수"), RenderContext()
        )
        assert "일차식은" in " ".join(s.content for s in with_batchim.segments)
        assert "함수는" in " ".join(s.content for s in without_batchim.segments)
