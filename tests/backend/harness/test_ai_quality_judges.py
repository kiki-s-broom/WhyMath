"""P3-10 AI 품질 8축 판정기 — 축마다 '그 절이 없으면 통과하는 입력'(반례)과 대조군을 둔다.

정상 응답에서 초록인 것은 증거가 아니다. 이 파일은 판정기의 하위 검사마다 그 검사만 걸리는 나쁜 응답을
넣어 실패를 확인하고, 경계(예: '맞아야'는 정답 인정이 아니다 · 식별자 속 숫자는 정답 진술이 아니다)에
대조군을 둔다(CLAUDE.md '픽스처가 그 절을 실제로 밟는가').
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from typing import Any

import pytest

from whymath_backend.harness import ai_quality_judges as judges
from whymath_backend.harness.ai_quality_candidates import build_eos_candidate
from whymath_backend.harness.ai_quality_eval_set import (
    KIND_CHOICE,
    KIND_HINT,
    EvalCase,
    EvalSet,
    load_eval_set,
)
from whymath_backend.harness.ai_quality_judges import (
    JudgeContext,
    Judgment,
    TutorResponse,
    expected_next_action,
    judge_case,
    p309_blocks,
    prepare_ladder_tiers,
)
from whymath_backend.harness.ai_quality_registry import Registry, load_registry
from whymath_backend.harness.wh1_tutor_output import build_tutor_output
from whymath_backend.l3.verify_step import VerifyStepState
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load_registry()


@pytest.fixture(scope="module")
def eval_set(registry: Registry) -> EvalSet:
    return load_eval_set(registry)


@pytest.fixture(scope="module")
def base(eval_set: EvalSet, registry: Registry) -> dict[str, TutorResponse]:
    return build_eos_candidate(eval_set, registry)


def _ctx(
    registry: Registry, eval_set: EvalSet, responses: Mapping[str, TutorResponse]
) -> JudgeContext:
    ctx = JudgeContext(registry=registry, eval_set=eval_set)
    prepare_ladder_tiers(ctx, responses)
    return ctx


def _case(eval_set: EvalSet, case_id: str) -> EvalCase:
    return next(c for c in eval_set.cases if c.case_id == case_id)


def _with(response: TutorResponse, **changes: Any) -> TutorResponse:
    output = dict(response.tutor_output)
    refs = changes.pop("referenced_concept_ids", response.referenced_concept_ids)
    output.update(changes)
    return dataclasses.replace(response, tutor_output=output, referenced_concept_ids=tuple(refs))


def _text(r: TutorResponse) -> str:
    return str(r.tutor_output["explanation"])


def _judge(
    axis: str,
    case: EvalCase,
    response: TutorResponse,
    registry: Registry,
    eval_set: EvalSet,
    base: Mapping[str, TutorResponse],
) -> Judgment:
    responses = dict(base)
    responses[case.case_id] = response
    return judge_case(axis, case, response, _ctx(registry, eval_set, responses))


def _first(eval_set: EvalSet, pred: Any) -> EvalCase:
    return next(c for c in eval_set.cases if pred(c))


def _ladder(eval_set: EvalSet, ladder_id: str) -> dict[int, EvalCase]:
    return {
        c.ladder_pos: c
        for c in eval_set.cases
        if c.ladder_id == ladder_id and c.ladder_pos is not None
    }


@pytest.fixture(scope="module")
def clean_ladder(
    registry: Registry, eval_set: EvalSet, base: Mapping[str, TutorResponse]
) -> dict[int, EvalCase]:
    """기준 응답이 Hint 적절성·정답 누설·수학 3축을 모두 통과하는 첫 사다리."""
    ctx = _ctx(registry, eval_set, base)
    ladders = sorted({c.ladder_id for c in eval_set.cases if c.ladder_id})
    for ladder_id in ladders:
        cases = _ladder(eval_set, ladder_id)
        ok = all(
            judge_case(axis, c, base[c.case_id], ctx).passed
            for c in cases.values()
            for axis in ("hint_appropriateness", "answer_leak", "math_correctness")
        )
        if ok:
            return cases
    raise AssertionError("깨끗한 사다리가 하나도 없다")


# ──────────────────────────────────────────────────────────────────────────
# ① 수학적 정확성
# ──────────────────────────────────────────────────────────────────────────
class TestMathCorrectness:
    def test_reference_l3_hint_is_checked_and_true(
        self, registry, eval_set, base, clean_ladder
    ) -> None:
        case = clean_ladder[3]
        j = _judge("math_correctness", case, base[case.case_id], registry, eval_set, base)
        assert j.applicable and j.passed
        assert j.counters["claims_checked"] >= 1

    def test_false_numeric_relation_fails(self, registry, eval_set, base, clean_ladder) -> None:
        case = clean_ladder[1]
        bad = _with(base[case.case_id], explanation=_text(base[case.case_id]) + " 6*7 = 41이야.")
        j = _judge("math_correctness", case, bad, registry, eval_set, base)
        assert j.applicable and not j.passed
        assert any("6*7 = 41" in r for r in j.reasons)

    def test_true_numeric_relation_is_control(self, registry, eval_set, base, clean_ladder) -> None:
        case = clean_ladder[1]
        ok = _with(base[case.case_id], explanation=_text(base[case.case_id]) + " 6*7 = 42이야.")
        j = _judge("math_correctness", case, ok, registry, eval_set, base)
        assert j.applicable and j.passed

    def test_anchored_wrong_final_assignment_fails(self, registry, eval_set, base) -> None:
        """문자 있는 식은 문항의 검증된 식(조건·풀이 단계)과 대조한다 — 틀린 최종 대입은 거짓."""
        pattern = re.compile(r"^([a-z]) = (-?\d+)$")

        def has_assign(c: EvalCase) -> bool:
            steps = eval_set.materials[c.problem_id].solution_steps
            return c.kind == KIND_HINT and bool(pattern.match(steps[-1]))

        case = _first(eval_set, has_assign)
        var, value = pattern.match(eval_set.materials[case.problem_id].solution_steps[-1]).groups()  # type: ignore[union-attr]
        wrong = f"{var} = {int(value) + 1}"
        bad = _with(base[case.case_id], explanation=f"정리하면 {wrong}이 돼.")
        j = _judge("math_correctness", case, bad, registry, eval_set, base)
        assert j.applicable and not j.passed, j
        right = _with(base[case.case_id], explanation=f"정리하면 {var} = {value}이 돼.")
        assert _judge("math_correctness", case, right, registry, eval_set, base).passed

    def test_letter_relation_in_choice_turn_is_not_judged(self, registry, eval_set, base) -> None:
        """선택 턴은 문항 조건과 대조하지 않는다 — 반례 발화의 변수는 문항 변수가 아니다."""
        case = _first(eval_set, lambda c: c.kind == KIND_CHOICE)
        r = _with(base[case.case_id], explanation="x = 999라고 해 보자.")
        j = _judge("math_correctness", case, r, registry, eval_set, base)
        assert not j.applicable

    def test_anchored_verdict_three_states(self) -> None:
        refs = ("2*x + 3 = 7", "2*x = 4", "x = 2")
        assert judges._anchored_verdict("x = 2", refs) is VerifyStepState.correct
        assert judges._anchored_verdict("4*x = 8", refs) is VerifyStepState.correct
        assert judges._anchored_verdict("x = 3", refs) is VerifyStepState.incorrect
        # 다른 변수의 식은 판정 불가 — 거짓으로 위장하지 않는다.
        assert judges._anchored_verdict("t = 5", refs) is VerifyStepState.unverifiable

    def test_quoted_misconception_statement_is_removed(self) -> None:
        kebab = "power-rule-step-omitted"
        stmt = CATALOG_BY_ID[kebab].canonical_statement
        output = {"diagnosis": {"misconception_id": kebab}, "explanation": f"{stmt}이라고 했지."}
        assert stmt not in judges._strip_quoted_misconception(f"{stmt}이라고 했지.", output)
        assert stmt in judges._strip_quoted_misconception(f"{stmt}이라고 했지.", {})


# ──────────────────────────────────────────────────────────────────────────
# ② 정답 누설
# ──────────────────────────────────────────────────────────────────────────
def _with_answer(
    eval_set: EvalSet, case: EvalCase, answer: str, steps: tuple[str, ...] = ()
) -> EvalSet:
    material = dataclasses.replace(
        eval_set.materials[case.problem_id], answer=answer, solution_steps=steps
    )
    return dataclasses.replace(
        eval_set, materials={**eval_set.materials, case.problem_id: material}
    )


class TestAnswerLeak:
    def test_declaration_fails(self, registry, eval_set, base, clean_ladder) -> None:
        case = clean_ladder[1]
        answer = eval_set.materials[case.problem_id].answer
        bad = _with(base[case.case_id], explanation=f"정답은 {answer}이야.")
        j = _judge("answer_leak", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["declaration"] == 1

    def test_one_char_answer_declaration_still_caught(
        self, registry, eval_set, base, clean_ladder
    ) -> None:
        """1자 정답은 문자열 판정이 유보된다(undecidable) — 선언 어구 검사가 대신 잡아야 한다."""
        case = clean_ladder[1]
        es = _with_answer(eval_set, case, "7")
        bad = _with(base[case.case_id], explanation="답은 7이야.")
        ctx = _ctx(registry, es, base)
        j = judge_case("answer_leak", case, bad, ctx)
        assert not j.passed and j.counters["string"] == 0 and j.counters["declaration"] == 1

    def test_multichar_answer_string_fails(self, registry, eval_set, base, clean_ladder) -> None:
        case = clean_ladder[1]
        es = _with_answer(eval_set, case, "17496")
        bad = _with(base[case.case_id], explanation="17496 근처를 생각해 봐.")
        j = judge_case("answer_leak", case, bad, _ctx(registry, es, base))
        assert not j.passed and j.counters["string"] == 1

    def test_equivalent_arithmetic_fails_and_unequal_is_control(
        self, registry, eval_set, base, clean_ladder
    ) -> None:
        case = clean_ladder[1]
        es = _with_answer(eval_set, case, "7")
        ctx = _ctx(registry, es, base)
        bad = _with(base[case.case_id], explanation="(3) + (4)를 계산해 봐.")
        good = _with(base[case.case_id], explanation="(3) + (5)를 계산해 봐.")
        j = judge_case("answer_leak", case, bad, ctx)
        assert not j.passed and j.counters["equivalent_expr"] == 1
        assert judge_case("answer_leak", case, good, ctx).passed

    def test_single_number_is_not_an_expression(
        self, registry, eval_set, base, clean_ladder
    ) -> None:
        """'7단계' 처럼 숫자 하나는 산술식이 아니다 — 연산자를 사이에 둔 숫자 2개 이상만 본다."""
        case = clean_ladder[1]
        es = _with_answer(eval_set, case, "7")
        ok = _with(base[case.case_id], explanation="풀이는 모두 7단계로 이어져.")
        assert judge_case("answer_leak", case, ok, _ctx(registry, es, base)).passed

    def test_final_step_text_fails(self, registry, eval_set, base, clean_ladder) -> None:
        case = clean_ladder[1]
        final = eval_set.materials[case.problem_id].solution_steps[-1]
        bad = _with(base[case.case_id], explanation=f"마지막 줄은 {final}이야.")
        j = _judge("answer_leak", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["final_step"] == 1

    def test_identifier_digits_are_not_answers(
        self, registry, eval_set, base, clean_ladder
    ) -> None:
        case = clean_ladder[1]
        es = _with_answer(eval_set, case, "12")
        ok = _with(base[case.case_id], explanation="성취기준 [12미적Ⅰ-02-03]을 떠올려 봐.")
        assert judge_case("answer_leak", case, ok, _ctx(registry, es, base)).passed
        bad = _with(base[case.case_id], explanation="12를 떠올려 봐.")
        assert not judge_case("answer_leak", case, bad, _ctx(registry, es, base)).passed

    def test_student_already_correct_is_not_applicable(self, registry, eval_set, base) -> None:
        case = _first(eval_set, lambda c: c.answer_known_to_student)
        answer = eval_set.materials[case.problem_id].answer
        r = _with(base[case.case_id], explanation=f"정답은 {answer}이야.")
        assert not _judge("answer_leak", case, r, registry, eval_set, base).applicable


# ──────────────────────────────────────────────────────────────────────────
# ③ 오개념 판정 정확도
# ──────────────────────────────────────────────────────────────────────────
class TestMisconception:
    def test_label_match_and_mismatch(self, registry, eval_set, base) -> None:
        case = _first(eval_set, lambda c: c.expected_misconception_id is not None)
        assert _judge(
            "misconception_accuracy", case, base[case.case_id], registry, eval_set, base
        ).passed
        other = next(k for k in sorted(CATALOG_BY_ID) if k != case.expected_misconception_id)
        bad = _with(base[case.case_id], diagnosis={"misconception_id": other, "confidence": 0.9})
        assert not _judge("misconception_accuracy", case, bad, registry, eval_set, base).passed

    def test_false_positive_on_correct_choice_fails(self, registry, eval_set, base) -> None:
        case = _first(
            eval_set, lambda c: c.misconception_labeled and c.expected_misconception_id is None
        )
        bad = _with(
            base[case.case_id],
            diagnosis={"misconception_id": sorted(CATALOG_BY_ID)[0], "confidence": 0.9},
        )
        assert not _judge("misconception_accuracy", case, bad, registry, eval_set, base).passed

    def test_hint_case_is_not_applicable(self, registry, eval_set, base, clean_ladder) -> None:
        case = clean_ladder[1]
        j = _judge("misconception_accuracy", case, base[case.case_id], registry, eval_set, base)
        assert not j.applicable


# ──────────────────────────────────────────────────────────────────────────
# ④ Hint 적절성
# ──────────────────────────────────────────────────────────────────────────
class TestHint:
    def test_reference_ladder_passes(self, registry, eval_set, base, clean_ladder) -> None:
        for case in clean_ladder.values():
            assert _judge(
                "hint_appropriateness", case, base[case.case_id], registry, eval_set, base
            ).passed

    def test_wrong_level_fails(self, registry, eval_set, base, clean_ladder) -> None:
        case = clean_ladder[1]
        bad = _with(base[case.case_id], hint_level=2)
        j = _judge("hint_appropriateness", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["level_mismatch"] == 1

    def test_bool_level_is_not_a_level(self, registry, eval_set, base, clean_ladder) -> None:
        case = clean_ladder[1]
        bad = _with(base[case.case_id], hint_level=True)
        j = _judge("hint_appropriateness", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["level_mismatch"] == 1

    def test_premature_disclosure_fails(self, registry, eval_set, base, clean_ladder) -> None:
        """L1 자리에 L3 본문(풀이 단계 식) — 단계-노출 정합(게이트 A)이 거부한다."""
        l1, l3 = clean_ladder[1], clean_ladder[3]
        bad = _with(base[l1.case_id], explanation=_text(base[l3.case_id]))
        j = _judge("hint_appropriateness", l1, bad, registry, eval_set, base)
        assert not j.passed and j.counters["exposure_mismatch"] == 1
        assert j.counters["level_mismatch"] == 0

    def test_under_disclosure_and_regression_fail(
        self, registry, eval_set, base, clean_ladder
    ) -> None:
        """L3 자리에 L1 본문 — 노출 부족이고, 앞 턴(L2)보다 노출이 줄었으므로 단조성도 깨진다."""
        l1, l3 = clean_ladder[1], clean_ladder[3]
        bad = _with(base[l3.case_id], explanation=_text(base[l1.case_id]))
        j = _judge("hint_appropriateness", l3, bad, registry, eval_set, base)
        assert not j.passed
        assert j.counters["exposure_mismatch"] == 1 and j.counters["non_monotone"] == 1

    def test_choice_case_is_not_applicable(self, registry, eval_set, base) -> None:
        case = _first(eval_set, lambda c: c.kind == KIND_CHOICE)
        assert not _judge(
            "hint_appropriateness", case, base[case.case_id], registry, eval_set, base
        ).applicable

    def test_derived_tier_reads_body_not_declaration(
        self, registry, eval_set, base, clean_ladder
    ) -> None:
        tiers = []
        for pos in (1, 2, 3):
            case = clean_ladder[pos]
            tiers.append(
                judges.derived_disclosure_tier(
                    case,
                    eval_set.materials[case.problem_id],
                    registry.concepts[case.concept_id].name_ko,
                    _text(base[case.case_id]),
                )
            )
        assert tiers == [1, 2, 3]


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 설명 일관성
# ──────────────────────────────────────────────────────────────────────────
class TestConsistency:
    def _wrong(self, eval_set: EvalSet) -> EvalCase:
        return _first(eval_set, lambda c: c.verdict == "incorrect")

    def _right(self, eval_set: EvalSet) -> EvalCase:
        return _first(eval_set, lambda c: c.verdict == "correct")

    def test_reference_passes(self, registry, eval_set, base) -> None:
        for case in (self._wrong(eval_set), self._right(eval_set)):
            assert _judge(
                "explanation_consistency", case, base[case.case_id], registry, eval_set, base
            ).passed

    def test_affirmation_on_wrong_turn_fails(self, registry, eval_set, base) -> None:
        case = self._wrong(eval_set)
        bad = _with(base[case.case_id], explanation="응, 그거 정답이야. 어떻게 생각했어?")
        j = _judge("explanation_consistency", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["polarity"] == 1

    def test_must_fit_condition_is_not_affirmation(self, registry, eval_set, base) -> None:
        """'맞아야'는 정답 인정이 아니다 — 부정 전방탐색 (?![야서도]) 의 반례."""
        case = self._wrong(eval_set)
        ok = _with(base[case.case_id], explanation="어떤 값이 조건에 맞아야 할까?")
        assert _judge("explanation_consistency", case, ok, registry, eval_set, base).passed

    def test_negation_on_correct_turn_fails(self, registry, eval_set, base) -> None:
        case = self._right(eval_set)
        bad = _with(base[case.case_id], explanation="음, 이건 틀렸어. 다음으로 가보자.")
        j = _judge("explanation_consistency", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["polarity"] == 1

    def test_next_action_must_follow_verdict(self, registry, eval_set, base) -> None:
        case = self._wrong(eval_set)
        bad = _with(base[case.case_id], next_action="continue_dialogue")
        j = _judge("explanation_consistency", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["next_action"] == 1

    def test_probe_mismatch_is_schema_failure(self, registry, eval_set, base, clean_ladder) -> None:
        case = clean_ladder[1]
        bad = _with(base[case.case_id], next_action="solve_probe")
        j = _judge("explanation_consistency", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["schema"] == 1

    def test_mastery_true_is_schema_failure(self, registry, eval_set, base, clean_ladder) -> None:
        case = clean_ladder[1]
        bad = _with(base[case.case_id], mastery_update_allowed=True)
        j = _judge("explanation_consistency", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["schema"] == 1

    def test_diagnosis_on_correct_turn_fails(self, registry, eval_set, base) -> None:
        case = self._right(eval_set)
        diag = {"misconception_id": sorted(CATALOG_BY_ID)[0], "confidence": 0.9}
        bad = _with(base[case.case_id], diagnosis=diag)
        j = _judge("explanation_consistency", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["diagnosis_on_correct"] == 1

    def test_unknown_ids_belong_to_hallucination_axis(self, registry, eval_set, base) -> None:
        case = self._wrong(eval_set)
        bad = _with(
            base[case.case_id],
            diagnosis={"concept_id": "math.nope.nope", "misconception_id": "nope"},
        )
        assert _judge("explanation_consistency", case, bad, registry, eval_set, base).passed

    @pytest.mark.parametrize("verdict", [None, "correct", "incorrect", "unverifiable"])
    @pytest.mark.parametrize("action", ["질문", "힌트", "출제", "격려"])
    def test_expected_next_action_matches_p309_builder(self, verdict, action) -> None:
        """규칙 드리프트 동결 — P3-09 빌더가 만드는 다음 행동과 전수 일치해야 한다."""
        built = build_tutor_output(
            explanation="질문 하나 해 볼게.",
            explanation_source="harness_template",
            action_type=action,
            mode_guard_replaced=False,
            verify_verdict=verdict,
            hypotheses=(),
            concept_id=None,
            known_concept_ids=frozenset(),
            hint_level=1,
        )
        if isinstance(built, str):  # 오답 턴 격려 등 스키마가 거부하는 조합은 빌더도 안 만든다
            return
        assert expected_next_action(built.response_strategy, verdict) == built.next_action


# ──────────────────────────────────────────────────────────────────────────
# ⑥ 학생 수준 적합성
# ──────────────────────────────────────────────────────────────────────────
class TestStudentLevel:
    def test_not_yet_learned_concept_fails_and_prerequisite_passes(
        self, registry, eval_set, base
    ) -> None:
        case = _first(eval_set, lambda c: c.concept_id == "math.calculus.mibungyesu")
        later = "math.calculus.hamsuui-jeungga-gamsowa-geukdae-geukso"
        prereq = "math.calculus.hamsuui-geukhanui-seongjilgwa-geukhangaps"
        bad = _with(base[case.case_id], referenced_concept_ids=(later,))
        j = _judge("student_level_fit", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["not_yet_learned"] == 1
        ok = _with(base[case.case_id], referenced_concept_ids=(prereq,))
        assert _judge("student_level_fit", case, ok, registry, eval_set, base).passed

    def test_not_yet_learned_name_mention_fails(self, registry, eval_set, base) -> None:
        case = _first(eval_set, lambda c: c.concept_id == "math.calculus.mibungyesu")
        bad = _with(base[case.case_id], explanation="「평균값 정리」를 써 보자.")
        j = _judge("student_level_fit", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["not_yet_learned"] == 1

    def test_notation_beyond_band_fails_for_middle_school(self, registry, eval_set, base) -> None:
        """평가셋은 고등 밴드뿐이라 이 검사는 거기서 실패를 못 낸다 — 중등 사례로 작동을 봉인한다."""
        case = _first(eval_set, lambda c: c.kind == KIND_CHOICE)
        middle = dataclasses.replace(case, student_band="중등")
        r = _with(base[case.case_id], explanation="∫ 기호를 떠올려 봐.")
        j = _judge("student_level_fit", middle, r, registry, eval_set, base)
        assert not j.passed and j.counters["notation"] >= 1
        assert _judge("student_level_fit", case, r, registry, eval_set, base).passed

    def test_concept_band_above_student_fails(self, registry, eval_set, base) -> None:
        case = _first(eval_set, lambda c: c.kind == KIND_CHOICE)
        middle = dataclasses.replace(case, student_band="중등")
        r = _with(base[case.case_id], referenced_concept_ids=(case.concept_id,))
        j = _judge("student_level_fit", middle, r, registry, eval_set, base)
        assert not j.passed and j.counters["concept_band"] == 1


# ──────────────────────────────────────────────────────────────────────────
# ⑦ hallucination
# ──────────────────────────────────────────────────────────────────────────
class TestHallucination:
    @pytest.mark.parametrize(
        ("field", "value", "counter"),
        [
            ("diagnosis", {"concept_id": "math.calculus.mibun-yeokryu-jeongri"}, "concept_id"),
            ("diagnosis", {"misconception_id": "no-such-kebab"}, "misconception_id"),
            ("explanation", "math.calculus.mibun-yeokryu-jeongri 를 보자.", "concept_id"),
            ("explanation", "성취기준 [12미적Ⅰ-02-99]를 보자.", "standard_code"),
            ("explanation", "오개념 M9999를 보자.", "m_id"),
        ],
    )
    def test_nonexistent_reference_fails(
        self, registry, eval_set, base, field, value, counter
    ) -> None:
        case = _first(eval_set, lambda c: c.kind == KIND_CHOICE)
        bad = _with(base[case.case_id], **{field: value})
        j = _judge("hallucination", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters[counter] == 1

    def test_real_references_are_control(self, registry, eval_set, base) -> None:
        case = _first(eval_set, lambda c: c.kind == KIND_CHOICE)
        mid = sorted(registry.misconception_mids)[0]
        ok = _with(
            base[case.case_id],
            explanation=f"{case.concept_id} · [12미적Ⅰ-02-03] · {mid}를 보자.",
        )
        assert _judge("hallucination", case, ok, registry, eval_set, base).passed

    def test_structured_reference_fails(self, registry, eval_set, base) -> None:
        case = _first(eval_set, lambda c: c.kind == KIND_CHOICE)
        bad = _with(base[case.case_id], referenced_concept_ids=("math.none.none",))
        assert not _judge("hallucination", case, bad, registry, eval_set, base).passed


# ──────────────────────────────────────────────────────────────────────────
# ⑧ Curriculum 범위 이탈
# ──────────────────────────────────────────────────────────────────────────
class TestScope:
    def test_out_of_scope_concept_fails(self, registry, eval_set, base) -> None:
        case = _first(eval_set, lambda c: c.kind == KIND_CHOICE)
        bad = _with(
            base[case.case_id], referenced_concept_ids=("math.calculus.bujeongjeokbunui-tteut",)
        )
        j = _judge("curriculum_scope", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["concept"] == 1

    def test_prerequisite_depth_boundary(self, registry, eval_set, base) -> None:
        """선수 조상 깊이 1·2는 범위 안, 깊이 3은 밖 — 깊이 상한(PREREQ_SCOPE_DEPTH)의 반례."""
        case = _first(eval_set, lambda c: c.concept_id == "math.calculus.mibungyesu")
        inside = "math.calculus.hamsuui-geukhanui-seongjilgwa-geukhangaps"
        assert inside in registry.allowed_scope_concepts
        within3 = judges_ancestors(registry, case.concept_id, 3)
        within2 = judges_ancestors(registry, case.concept_id, 2)
        beyond = sorted(within3 - within2 - registry.allowed_scope_concepts)
        assert beyond, "깊이 3 조상이 없으면 이 경계를 시험할 수 없다"
        ok = _with(base[case.case_id], referenced_concept_ids=(inside,))
        bad = _with(base[case.case_id], referenced_concept_ids=(beyond[0],))
        assert _judge("curriculum_scope", case, ok, registry, eval_set, base).passed
        assert not _judge("curriculum_scope", case, bad, registry, eval_set, base).passed

    def test_text_standard_code_out_of_scope_fails(self, registry, eval_set, base) -> None:
        case = _first(eval_set, lambda c: c.kind == KIND_CHOICE)
        bad = _with(base[case.case_id], explanation="[12미적Ⅰ-03-01]에서 배운 걸 떠올려 봐.")
        ok = _with(base[case.case_id], explanation="[12미적Ⅰ-02-03]에서 배운 걸 떠올려 봐.")
        assert not _judge("curriculum_scope", case, bad, registry, eval_set, base).passed
        assert _judge("curriculum_scope", case, ok, registry, eval_set, base).passed

    def test_name_mention_out_of_scope_fails(self, registry, eval_set, base) -> None:
        case = _first(eval_set, lambda c: c.kind == KIND_CHOICE)
        bad = _with(base[case.case_id], explanation="「부정적분의 뜻」을 먼저 보자.")
        j = _judge("curriculum_scope", case, bad, registry, eval_set, base)
        assert not j.passed and j.counters["mention"] == 1

    def test_nonexistent_id_is_not_scope_failure(self, registry, eval_set, base) -> None:
        case = _first(eval_set, lambda c: c.kind == KIND_CHOICE)
        r = _with(base[case.case_id], referenced_concept_ids=("math.none.none",))
        assert _judge("curriculum_scope", case, r, registry, eval_set, base).passed


def judges_ancestors(registry: Registry, concept_id: str, depth: int) -> frozenset[str]:
    from whymath_backend.harness.ai_quality_registry import _ancestors_within

    return _ancestors_within([concept_id], registry.parents, depth)


# ──────────────────────────────────────────────────────────────────────────
# 공용 — 응답 누락·P3-09 노출 경로·레지스트리
# ──────────────────────────────────────────────────────────────────────────
class TestCommon:
    def test_missing_response_fails_every_applicable_axis(
        self, registry, eval_set, base, clean_ladder
    ) -> None:
        case = clean_ladder[3]
        ctx = _ctx(registry, eval_set, base)
        for axis in judges.AXES:
            j = judge_case(axis, case, None, ctx)
            if axis == "misconception_accuracy":
                assert not j.applicable  # 힌트 사례는 오개념 라벨이 없다
            else:
                assert j.applicable and not j.passed and j.reasons == ("응답 누락",), axis

    def test_p309_exposure(self, eval_set, base) -> None:
        case = _first(eval_set, lambda c: c.kind == KIND_CHOICE)
        assert not p309_blocks(case, base[case.case_id])
        fake = _with(base[case.case_id], diagnosis={"concept_id": "math.none.none"})
        assert p309_blocks(case, fake)
        assert p309_blocks(case, None)

    def test_mentioned_concepts_longest_first(self, registry) -> None:
        """긴 이름이 먼저 잡히면 그 안의 짧은 이름은 다시 잡히지 않는다."""
        found = registry.mentioned_concepts("「함수의 극한의 성질과 극한값」을 보자.")
        assert frozenset({"math.calculus.hamsuui-geukhanui-seongjilgwa-geukhangaps"}) in found
        assert all(len(ids) >= 1 for ids in found)
        names = [registry.concepts[next(iter(ids))].name_ko for ids in found]
        assert "함수의 극한" not in names or len(found) == 1

    def test_descendants_are_strict(self, registry) -> None:
        cid = "math.calculus.mibungyesu"
        later = registry.descendants(cid)
        assert cid not in later
        assert "math.calculus.hamsuui-jeungga-gamsowa-geukdae-geukso" in later
        assert "math.calculus.hamsuui-geukhanui-seongjilgwa-geukhangaps" not in later

    def test_axes_and_specs_are_one_to_one(self) -> None:
        assert tuple(judges.AXIS_SPECS) == judges.AXES
        assert tuple(judges.BLIND_SPOTS) == judges.AXES
        assert set(judges._JUDGES) == set(judges.AXES)
        for spec in judges.AXIS_SPECS.values():
            assert spec.direction in ("ceiling", "floor")
            assert 0 < spec.threshold < 1
            assert spec.threshold_basis and spec.kpi_mapping and spec.decision and spec.reuse

    def test_kpi_reuse_thresholds_track_scorecard(self) -> None:
        """재사용이라 적은 임계는 스코어카드 정본과 같은 값이어야 한다(조용히 빗나가지 않게)."""
        from whymath_backend.ops.validation_scorecard import CONTENT_KPI_THRESHOLDS

        mis = CONTENT_KPI_THRESHOLDS["오개념 op-code 라벨 정확도 ≥85%"]
        scope = CONTENT_KPI_THRESHOLDS["교육과정 정합률 ≥92% (블라인드 역매핑)"]
        assert judges.AXIS_SPECS["misconception_accuracy"].threshold == mis.value
        assert judges.AXIS_SPECS["misconception_accuracy"].direction == mis.direction
        assert judges.AXIS_SPECS["curriculum_scope"].threshold == scope.value
        assert judges.AXIS_SPECS["curriculum_scope"].direction == scope.direction
