"""게이트 3종 — 실패 주입(RED)·대조군(GREEN)·게이트 독립성 (S4-11 · acceptance 검증 축).

CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지"의 집행이다. 게이트마다
① 그 게이트가 막으려는 결함을 **주입**해 거부(verified=false)를 확인하고 ② 결함 없는 대조군이
통과함을 확인한다. 또 각 주입이 **나머지 두 게이트는 통과**하는 입력임을 단언해, 한 게이트가 다른
게이트의 몫을 대신 막아 주는 '우연한 초록'을 배제한다(게이트가 실제로 그 결함을 잡는다는 증거).

게이트 A의 각 절(①~④)마다 그 절이 없으면 통과하는 입력을 둔다(CLAUDE.md "픽스처가 그 절을
실제로 밟는가") — 특히 ④의 '시연 결과 = 최종 결과'는 정답이 1자라 게이트 B가 undecidable을 내는
경로에서만 의미가 있으므로 그 조건을 그대로 픽스처로 만든다.
"""

from __future__ import annotations

import uuid

import pytest

from whymath_backend.l4.hint_content.gates import (
    GATE_ANSWER_LEAKAGE,
    GATE_LEVEL_REVEALS,
    GATE_TONE,
    GateContext,
    check_answer_leakage,
    check_level_reveals,
    check_tone,
    evaluate_gates,
)
from whymath_backend.l4.hint_content.generator import ConceptRef, StepSource, generate_step_hints
from whymath_backend.l4.hint_content.models import Hint, HintReveals, SolutionStepRef

_PID = uuid.UUID("00000000-0000-0000-0000-00000000b022")
_STEPS = ("x**2 - 5*x + 6", "(x - 2)*(x - 3)", "x = 2, x = 3")
_CONCEPT = ConceptRef(concept_id="math.algebra.factoring", name="인수분해", source="step")
# 정답은 단계 본문과 *다른 표기*로 둔다 — 게이트 B 주입이 게이트 A(단계 본문 노출)와 섞이지 않게.
_ANSWER = "123"


def _drafts(
    order: int = 2,
    *,
    steps: tuple[str, ...] = _STEPS,
    concept: ConceptRef | None = _CONCEPT,
) -> dict[int, Hint]:
    source = StepSource(
        solution_path_id="sp-gate",
        problem_id=_PID,
        step_order=order,
        step_contents=steps,
        transition_verified=True,
        concept=concept,
    )
    return {h.level: h for h in generate_step_hints(source).drafts}


def _ctx(
    *,
    steps: tuple[str, ...] = _STEPS,
    concept: ConceptRef | None = _CONCEPT,
    answer: str | None = _ANSWER,
) -> GateContext:
    return GateContext(
        step_contents=steps,
        concept_name=concept.name if concept is not None else None,
        final_answer=answer,
    )


def _with_content(hint: Hint, content: str) -> Hint:
    return hint.model_copy(update={"content": content})


def _with_reveals(hint: Hint, **flags: object) -> Hint:
    """검증기를 우회해 노출 선언을 조작한다 — 외부에서 조립된 불량 행을 흉내 낸다."""
    base = hint.reveals.model_dump()
    base.update(flags)
    return hint.model_copy(update={"reveals": HintReveals.model_construct(**base)})


# ──────────────────────────────────────────────────────────────────────
# 대조군 — 생성기 산출물은 게이트 3종을 모두 통과한다
# ──────────────────────────────────────────────────────────────────────
class TestControls:
    @pytest.mark.parametrize("level", [1, 2, 3])
    def test_generated_hint_passes_all_gates(self, level: int) -> None:
        gated = evaluate_gates(_drafts()[level], _ctx())
        assert gated.verified is True, gated.gate_report
        assert gated.gate_report["passed"] is True
        assert set(gated.gate_report) == {
            GATE_LEVEL_REVEALS,
            GATE_ANSWER_LEAKAGE,
            GATE_TONE,
            "passed",
        }

    def test_generated_hints_without_concept_pass(self) -> None:
        drafts = _drafts(concept=None)
        for hint in drafts.values():
            assert evaluate_gates(hint, _ctx(concept=None)).verified is True

    def test_verified_hint_score_equals_level_over_three(self) -> None:
        """게이트 A가 '레벨 = 노출 단계'를 강제하므로 검수 통과 힌트의 점수는 level/3이다."""
        for level, hint in _drafts().items():
            gated = evaluate_gates(hint, _ctx())
            assert gated.verified
            assert gated.reveals.reveal_score == pytest.approx(level / 3)


# ──────────────────────────────────────────────────────────────────────
# 게이트 A — level-reveals 정합 (절마다 주입)
# ──────────────────────────────────────────────────────────────────────
class TestLevelRevealsGate:
    def _assert_only_a_fails(self, hint: Hint, ctx: GateContext) -> list[str]:
        verdict = check_level_reveals(hint, ctx)
        assert verdict.passed is False and verdict.reasons
        # 독립성 — 같은 입력이 B·C는 통과한다(A가 실제로 이 결함을 잡는다는 증거).
        assert check_answer_leakage(hint, ctx).passed is True
        assert check_tone(hint).passed is True
        assert evaluate_gates(hint, ctx).verified is False
        return list(verdict.reasons)

    def test_l1_revealing_a_step_is_rejected(self) -> None:
        """③ L1에 단계 식이 실리면(계산 미선언) 거부 — 'L1 must not contain step content'."""
        l1 = _drafts()[1]
        bad = _with_content(l1, l1.content + " 참고: (x - 2)*(x - 3)")
        reasons = self._assert_only_a_fails(bad, _ctx())
        assert any("계산 노출" in r for r in reasons)

    def test_l1_revealing_step_flow_is_rejected(self) -> None:
        """③ L1에 흐름 표지(몇 단계)가 실리면 거부."""
        l1 = _drafts()[1]
        bad = _with_content(l1, l1.content + " 풀이는 모두 3단계야.")
        reasons = self._assert_only_a_fails(bad, _ctx())
        assert any("흐름 노출" in r for r in reasons)

    def test_l2_revealing_computation_is_rejected(self) -> None:
        """③ L2(계산 미노출)에 단계 식이 실리면 거부."""
        l2 = _drafts()[2]
        bad = _with_content(l2, l2.content + " 첫 식은 x**2 - 5*x + 6 이야.")
        reasons = self._assert_only_a_fails(bad, _ctx())
        assert any("계산 노출" in r for r in reasons)

    def test_l3_overdeclared_partial_is_rejected(self) -> None:
        """③ 부분 시연을 선언했는데 본문에 식이 없으면 거부(과대 선언 → KPI 과대 계상)."""
        l3 = _drafts()[3]
        bad = _with_content(l3, _drafts()[2].content)
        reasons = self._assert_only_a_fails(bad, _ctx())
        assert any("과대 선언" in r for r in reasons)

    def test_concept_declared_but_absent_is_rejected(self) -> None:
        """③ 개념 이름 노출 선언과 본문이 어긋나면 거부."""
        l1 = _drafts()[1]
        bad = _with_content(l1, "이번 단계에서 쓸 성질을 먼저 생각해 보자.")
        reasons = self._assert_only_a_fails(bad, _ctx())
        assert any("개념 이름" in r for r in reasons)

    def test_concept_ids_must_match_declaration(self) -> None:
        l1 = _drafts()[1]
        bad = _with_reveals(l1, revealed_concept_ids=())
        reasons = self._assert_only_a_fails(bad, _ctx())
        assert any("revealed_concept_ids" in r for r in reasons)

    def test_level_matrix_violation_is_rejected(self) -> None:
        """① L1이 흐름 노출을 선언하면(본문도 일치시켜도) 레벨 행렬 위반으로 거부."""
        l1 = _drafts()[1]
        bad = _with_reveals(
            _with_content(l1, l1.content + " 풀이는 모두 3단계야."),
            reveals_step_flow=True,
            reveal_score=2 / 3,
        )
        reasons = self._assert_only_a_fails(bad, _ctx())
        assert any("L1은" in r for r in reasons)

    def test_score_not_derived_from_flags_is_rejected(self) -> None:
        """② 점수가 플래그 파생값과 다르면 거부(검증기를 우회해 조립된 행 방어)."""
        bad = _with_reveals(_drafts()[2], reveal_score=0.99)
        reasons = self._assert_only_a_fails(bad, _ctx())
        assert any("reveal_score" in r for r in reasons)

    def test_l3_of_final_step_is_level_four_and_rejected(self) -> None:
        """④ 마지막 단계의 부분 시연은 전체 풀이(Level 4) — 구조 판정으로 거부."""
        l3 = _drafts()[3]
        ref = SolutionStepRef(solution_path_id="sp-gate", step_order=3, problem_id=_PID)
        bad = l3.model_copy(update={"solution_step_ref": ref})
        reasons = self._assert_only_a_fails(bad, _ctx())
        assert any("Level 4" in r for r in reasons)

    def test_demonstrated_result_equal_to_final_is_rejected_even_when_b_cannot_decide(
        self,
    ) -> None:
        """④ 시연 결과 = 최종 결과(1자)면 거부 — 정답이 1자라 B는 undecidable, A만이 막는다."""
        steps = ("2 + 5", "7", "7")
        drafts = _drafts(steps=steps)
        ctx = _ctx(steps=steps, answer="7")
        l3 = drafts[3]
        verdict = check_level_reveals(l3, ctx)
        assert verdict.passed is False
        assert any("최종 결과와 같다" in r for r in verdict.reasons)
        leakage = check_answer_leakage(l3, ctx)
        assert leakage.passed is True and leakage.detail["verdict"] == "undecidable"
        assert evaluate_gates(l3, ctx).verified is False

    def test_final_result_anywhere_in_body_is_rejected(self) -> None:
        """④ 최종 단계 결과(2자 이상)가 어느 레벨 본문에든 있으면 거부(전체 풀이 노출)."""
        l2 = _drafts()[2]
        bad = _with_content(l2, l2.content + " 끝은 x = 2, x = 3 이야.")
        verdict = check_level_reveals(bad, _ctx())
        assert verdict.passed is False
        assert any("최종 단계 결과" in r for r in verdict.reasons)


# ──────────────────────────────────────────────────────────────────────
# 게이트 B — detect_answer_leakage 재사용
# ──────────────────────────────────────────────────────────────────────
class TestAnswerLeakageGate:
    def test_leaked_answer_is_rejected(self) -> None:
        """정답 값 주입 → leaked → 거부. A·C는 통과(단계 식·금지 패턴 없음)."""
        l2 = _drafts()[2]
        bad = _with_content(l2, l2.content + " 참고로 123")
        verdict = check_answer_leakage(bad, _ctx())
        assert verdict.passed is False
        assert verdict.detail["verdict"] == "leaked"
        assert check_level_reveals(bad, _ctx()).passed is True
        assert check_tone(bad).passed is True
        assert evaluate_gates(bad, _ctx()).verified is False

    def test_clean_control_passes(self) -> None:
        verdict = check_answer_leakage(_drafts()[2], _ctx())
        assert verdict.passed is True and verdict.detail["verdict"] == "clean"

    def test_numeric_boundary_is_not_a_leak(self) -> None:
        """재사용 판정의 단어 경계 — '1234'는 정답 '123'의 누출이 아니다(오탐 금지 유지)."""
        l2 = _drafts()[2]
        verdict = check_answer_leakage(_with_content(l2, l2.content + " 1234"), _ctx())
        assert verdict.passed is True and verdict.detail["verdict"] == "clean"

    def test_undecidable_passes_but_is_recorded(self) -> None:
        verdict = check_answer_leakage(_drafts()[2], _ctx(answer="7"))
        assert verdict.passed is True and verdict.detail["verdict"] == "undecidable"

    def test_missing_answer_fails_closed(self) -> None:
        """정답 원천이 없으면 판정 불가 — 통과로 위장하지 않고 거부."""
        verdict = check_answer_leakage(_drafts()[2], _ctx(answer=None))
        assert verdict.passed is False
        assert verdict.detail["verdict"] == "not_run"
        assert evaluate_gates(_drafts()[2], _ctx(answer=None)).verified is False


# ──────────────────────────────────────────────────────────────────────
# 게이트 C — 정서 톤(거부, 치환 아님)
# ──────────────────────────────────────────────────────────────────────
class TestToneGate:
    def test_negative_tone_is_rejected(self) -> None:
        """금지 패턴 주입 → 거부. A·B는 통과."""
        l2 = _drafts()[2]
        bad = _with_content(l2, l2.content + " 네가 틀렸어도 괜찮아.")
        verdict = check_tone(bad)
        assert verdict.passed is False
        assert any("틀렸" in r for r in verdict.reasons)
        assert check_level_reveals(bad, _ctx()).passed is True
        assert check_answer_leakage(bad, _ctx()).passed is True
        assert evaluate_gates(bad, _ctx()).verified is False

    def test_concept_name_colliding_with_banned_pattern_is_rejected_not_rewritten(self) -> None:
        """개념 「실수」(real number)는 금지 패턴과 겹친다 — 치환하면 뜻이 망가지므로 거부한다."""
        concept = ConceptRef(concept_id="math.number.real", name="실수", source="step")
        l1 = _drafts(concept=concept)[1]
        gated = evaluate_gates(l1, _ctx(concept=concept))
        assert gated.verified is False
        assert gated.content == l1.content  # 본문을 조용히 바꾸지 않는다
        assert check_level_reveals(l1, _ctx(concept=concept)).passed is True

    def test_clean_control_passes(self) -> None:
        verdict = check_tone(_drafts()[1])
        assert verdict.passed is True and verdict.reasons == ()


def test_all_gate_reasons_are_recorded_without_short_circuit() -> None:
    """여러 게이트가 동시에 실패하면 사유가 **전부** 남는다(단락 평가로 사유를 잃지 않는다)."""
    l2 = _drafts()[2]
    bad = _with_content(l2, l2.content + " 네가 틀렸어도 괜찮아. 참고로 123 그리고 x**2 - 5*x + 6")
    report = evaluate_gates(bad, _ctx()).gate_report
    for gate in (GATE_LEVEL_REVEALS, GATE_ANSWER_LEAKAGE, GATE_TONE):
        verdict = report[gate]
        assert isinstance(verdict, dict) and verdict["passed"] is False, gate
    assert report["passed"] is False
