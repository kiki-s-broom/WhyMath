"""Solution QA(P3-07) 테스트 — 문제·정답·풀이 불일치 주입이 RED 로 나오는지가 핵심이다.

정상 입력에서 초록인 것은 보호의 증거가 아니다. 그래서 이 파일의 중심은 ①지시문의 3종 주입(정답 변조·
풀이 최종 답 변조·중복 선택지)을 **합성 레코드와 실 코퍼스 레코드 양쪽에** 걸어 FAIL 로 바뀌는지 ②모든
주입이 실제로 레코드를 바꿨는지(`mutated != original`) ③검증 불가가 통과로 세어지지 않는지다.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import solution_qa as qa

Record = dict[str, Any]

REPO = Path(__file__).resolve().parents[3]
P3_DIFF_BANK = REPO / "data/corpus/problem_bank_p3_calculus1_diff_v0/problems.jsonl"


# ──────────────────────────────────────────────────────────────────────────
# 합성 대조 레코드 — 네 검사가 전부 결정되어 PASS 인 문항 3형
# ──────────────────────────────────────────────────────────────────────────
def _single_assignment() -> Record:
    """풀이가 `y = -4` 로 끝나는 단답형 — C1·C2·C4 결정, C3 해당 없음."""
    return {
        "slug": "syn-assign",
        "unit_codes": ["SYN"],
        "question_format": "단답형",
        "answer": "-4",
        "verify": {
            "conditions": "Derivative(-x**3 - 7*x**2 - 4*x + 6, x).doit().subs(x, 0) = y",
            "answer_map": {"y": "-4"},
            "solution_steps": [
                "Derivative(-x**3 - 7*x**2 - 4*x + 6, x).doit().subs(x, 0) = y",
                "(-3*x**2 - 14*x - 4).subs(x, 0) = y",
                "-3*(0)**2 - 14*(0) - 4 = y",
                "y = -4",
            ],
        },
    }


def _multiple_choice() -> Record:
    """객관식 — 선택지 4개에 정답이 정확히 한 번. 보기 `8√3` 은 유니코드 근호다."""
    record = _single_assignment()
    record.update(
        {
            "slug": "syn-mc",
            "question_format": "객관식",
            "answer": "-4",
            "choices": ["-4", "4", "-8", "8√3"],
        }
    )
    return record


def _root_pick() -> Record:
    """풀이가 두 근을 나열하고 `answer_selection=largest` 가 정답을 고르는 문항."""
    return {
        "slug": "syn-roots",
        "unit_codes": ["SYN"],
        "question_format": "단답형",
        "answer": "4",
        "verify": {
            "conditions": "3*x**2 - 6*x - 24 = 0",
            "answer_map": {"x": "4"},
            "answer_selection": "largest",
            "solution_steps": [
                "Derivative(x**3 - 3*x**2 - 24*x + 2, x).doit() = 0",
                "3*x**2 - 6*x - 24 = 0",
                "3*(x - 4)*(x + 2) = 0",
                "x = -2, x = 4",
            ],
        },
    }


CONTROLS: dict[str, Callable[[], Record]] = {
    "assignment": _single_assignment,
    "multiple_choice": _multiple_choice,
    "root_pick": _root_pick,
}


@pytest.fixture(params=sorted(CONTROLS))
def control(request: pytest.FixtureRequest) -> Record:
    return CONTROLS[request.param]()


def _verdict(record: Record) -> qa.Verdict:
    return qa.judge_record(record).verdict


def _codes(record: Record) -> set[str]:
    item = qa.judge_record(record)
    return {res.code for res in item.checks.values() if res.code}


# ──────────────────────────────────────────────────────────────────────────
# 주입 도구 — 주입이 실제로 레코드를 바꿨는지 단언한다(안 바뀌면 초록이 검출처럼 보인다)
# ──────────────────────────────────────────────────────────────────────────
def _inject(record: Record, mutate: Callable[[Record], None]) -> Record:
    mutated = copy.deepcopy(record)
    mutate(mutated)
    assert mutated != record, "주입이 레코드를 바꾸지 못했다 — 이 테스트는 아무것도 검증하지 못한다"
    return mutated


def _wrong_answer(record: Record) -> Record:
    """① `answer` 필드만 틀린 값으로 — answer_map·풀이는 그대로(학생에게 보이는 값만 어긋난다)."""

    def mutate(r: Record) -> None:
        r["answer"] = "987654321"
        if r.get(
            "choices"
        ):  # 보기에도 새 정답이 없으면 C3 이 먼저 잡을 뿐이라, C1 만 시험하려고 보기도 맞춘다
            r["choices"] = [c if c != record["answer"] else "987654321" for c in r["choices"]]

    return _inject(record, mutate)


def _wrong_final_step(record: Record) -> Record:
    """② 풀이의 **마지막 단계**만 틀린 값으로 — answer·answer_map 은 그대로."""

    def mutate(r: Record) -> None:
        steps = r["verify"]["solution_steps"]
        last = steps[-1]
        if "," in last:  # 근 나열: 정답 근만 다른 값으로
            var = last.split("=")[0].strip()
            steps[-1] = f"{var} = -2, {var} = 987654321"
        else:
            var = last.split("=")[0].strip()
            steps[-1] = f"{var} = 987654321"

    return _inject(record, mutate)


def _duplicate_choice_exact(record: Record) -> Record:
    """③-a 오답 보기를 다른 보기와 **같은 문자열**로."""

    def mutate(r: Record) -> None:
        r["choices"][2] = r["choices"][1]

    return _inject(record, mutate)


def _duplicate_choice_semantic(record: Record) -> Record:
    """③-b 오답 보기를 정답과 **문자열은 다르나 같은 값**으로(`-4` ↔ `-8/2`)."""

    def mutate(r: Record) -> None:
        r["choices"][1] = "-8/2"

    return _inject(record, mutate)


# ──────────────────────────────────────────────────────────────────────────
# 0. 대조군 — 주입 전에는 전부 PASS 여야 주입의 RED 가 의미를 갖는다
# ──────────────────────────────────────────────────────────────────────────
def test_controls_are_fully_decided_and_pass(control: Record) -> None:
    item = qa.judge_record(control)
    assert item.verdict is qa.Verdict.PASS, item.reason_text()
    assert all(res.state is not qa.CheckState.UNVERIFIABLE for res in item.checks.values())


def test_mc_control_applies_c3_and_non_mc_does_not() -> None:
    assert qa.judge_record(_multiple_choice()).checks["C3"].state is qa.CheckState.PASS
    assert qa.judge_record(_single_assignment()).checks["C3"].state is qa.CheckState.NOT_APPLICABLE


# ──────────────────────────────────────────────────────────────────────────
# 1. 주입 ① — 정답을 바꾸면 RED (answer 필드만 바뀐 경우 포함)
# ──────────────────────────────────────────────────────────────────────────
def test_injection_wrong_answer_turns_red(control: Record) -> None:
    mutated = _wrong_answer(control)
    assert _verdict(mutated) is qa.Verdict.FAIL
    assert "C1_ANSWER_NOT_IN_ANSWER_MAP" in _codes(mutated)


def test_injection_wrong_answer_is_caught_by_both_gates() -> None:
    """`answer` 만 틀린 표준 경로 문항 — 야간 S6 재검증과 이 도구가 같은 판정으로 잡는다(OPS-150).

    종전엔 이 테스트가 반대(야간 재검증은 못 잡음)를 고정점으로 동결했다. OPS-150 이 두 게이트를
    공용 대조 함수(`l3.verify_solution.answer_map_vars_matching`) 하나로 묶었으므로 판정이 같아야 한다.
    """
    from whymath_backend.harness import corpus_reverify as cr

    mutated = _wrong_answer(_single_assignment())
    report = cr.reverify_corpus([mutated], use_fuzz=False)
    assert report.failed == 1 and report.answer_mismatched == 1  # 야간 재검증: 잡음
    assert _verdict(mutated) is qa.Verdict.FAIL  # 이 도구: 잡음
    assert "C1_ANSWER_NOT_IN_ANSWER_MAP" in _codes(mutated)


def test_injection_answer_map_change_turns_red(control: Record) -> None:
    """검산 재료(answer_map)가 틀려도 RED — 조건을 만족하지 않는 값이다."""

    def mutate(r: Record) -> None:
        var = next(iter(r["verify"]["answer_map"]))
        r["verify"]["answer_map"][var] = "987654321"

    mutated = _inject(control, mutate)
    assert _verdict(mutated) is qa.Verdict.FAIL


# ──────────────────────────────────────────────────────────────────────────
# 2. 주입 ② — 풀이 최종 답을 바꾸면 RED
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("factory", [_single_assignment, _root_pick])
def test_injection_wrong_final_step_turns_red(factory: Callable[[], Record]) -> None:
    mutated = _wrong_final_step(factory())
    assert _verdict(mutated) is qa.Verdict.FAIL


def test_final_step_value_mismatch_is_caught_by_c2_itself() -> None:
    """C4(연쇄 동치)가 없어도 C2 가 단독으로 잡는다 — 단계 중간은 그대로 두고 마지막 줄만 바꾼다."""
    mutated = _wrong_final_step(_single_assignment())
    result = qa.judge_record(mutated)
    assert result.checks["C2"].state is qa.CheckState.FAIL
    assert result.checks["C2"].code == "C2_FINAL_ANSWER_MISMATCH"


def test_broken_intermediate_step_turns_red() -> None:
    """풀이 중간 등식이 성립하지 않으면 RED(C4)."""

    def mutate(r: Record) -> None:
        r["verify"]["solution_steps"][1] = "(-3*x**2 - 14*x - 5).subs(x, 0) = y"

    mutated = _inject(_single_assignment(), mutate)
    result = qa.judge_record(mutated)
    assert result.verdict is qa.Verdict.FAIL
    assert result.checks["C4"].state is qa.CheckState.FAIL


# ──────────────────────────────────────────────────────────────────────────
# 3. 주입 ③ — 중복 선택지는 RED
# ──────────────────────────────────────────────────────────────────────────
def test_injection_duplicate_choice_exact_turns_red() -> None:
    mutated = _duplicate_choice_exact(_multiple_choice())
    result = qa.judge_record(mutated)
    assert result.verdict is qa.Verdict.FAIL
    assert result.checks["C3"].code == "C3_DUPLICATE_CHOICE"


def test_injection_duplicate_choice_semantic_turns_red() -> None:
    """문자열이 달라도 값이 정답과 같은 보기가 하나 더 있으면 '정답이 정확히 한 번'이 깨진다."""
    mutated = _duplicate_choice_semantic(_multiple_choice())
    result = qa.judge_record(mutated)
    assert result.verdict is qa.Verdict.FAIL
    assert result.checks["C3"].code == "C3_ANSWER_REPEATED"


def test_answer_missing_from_choices_turns_red() -> None:
    def mutate(r: Record) -> None:
        r["choices"][0] = "12"  # 정답 보기를 오답으로 덮어쓴다

    mutated = _inject(_multiple_choice(), mutate)
    assert qa.judge_record(mutated).checks["C3"].code == "C3_ANSWER_NOT_IN_CHOICES"


def test_multiple_choice_without_choices_turns_red() -> None:
    def mutate(r: Record) -> None:
        del r["choices"]

    mutated = _inject(_multiple_choice(), mutate)
    assert qa.judge_record(mutated).checks["C3"].code == "C3_MC_WITHOUT_CHOICES"


def test_unicode_radical_choice_is_decided_not_unverifiable() -> None:
    """정본 채점기가 못 읽는 `8√3` 때문에 문항이 검증 불가로 새지 않는다(비교용 정규화)."""
    assert qa.judge_record(_multiple_choice()).checks["C3"].state is qa.CheckState.PASS


# ──────────────────────────────────────────────────────────────────────────
# 4. 검증 불가는 통과가 아니다 — 거짓 실패도 아니다
# ──────────────────────────────────────────────────────────────────────────
def test_candidate_list_without_the_answer_is_unverifiable_not_fail() -> None:
    """2026-10-18 실측 회귀 고정: 마지막 단계가 임계점 나열이고 정답이 그 함수(교점 개수)인 문항.

    '정답이 후보에 없음'을 FAIL 로 내면 대표 과정 47건이 전부 거짓 실패였다.
    """
    record: Record = {
        "slug": "syn-count",
        "unit_codes": ["SYN"],
        "question_format": "단답형",
        "answer": "1",
        "verify": {
            "conditions": "2*x**3 - 3*x**2 - 12*x - 9 = 0",
            "answer_map": {},
            "answer_kind": "real_root_count",
            "solution_steps": [
                "Derivative(2*x**3 - 3*x**2 - 12*x, x).doit() = 0",
                "6*x**2 - 6*x - 12 = 0",
                "6*(x - 2)*(x + 1) = 0",
                "x = -1, x = 2",
            ],
        },
    }
    result = qa.judge_record(record)
    assert result.checks["C2"].state is qa.CheckState.UNVERIFIABLE
    assert result.verdict is not qa.Verdict.FAIL


def test_unstructured_root_choice_is_unverifiable() -> None:
    """근이 둘이고 정답이 그중 하나지만 '양수 a' 같은 선택 규칙이 구조에 없으면 가릴 수 없다."""

    def mutate(r: Record) -> None:
        del r["verify"]["answer_selection"]

    mutated = _inject(_root_pick(), mutate)
    result = qa.judge_record(mutated)
    assert result.checks["C2"].code == "C2_ROOT_CHOICE_UNSTRUCTURED"
    assert result.verdict is qa.Verdict.UNVERIFIABLE


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda r: r["verify"].pop("solution_steps"), "C2_NO_STEPS"),
        (
            lambda r: r["verify"].update(solution_steps=["3*x**2", "3*(x)*(x)"]),
            "C2_FINAL_STEP_NOT_ANSWER_FORM",
        ),
    ],
)
def test_missing_or_non_answer_form_solution_is_unverifiable(
    mutate: Callable[[Record], object], code: str
) -> None:
    result = qa.judge_record(_inject(_single_assignment(), lambda r: mutate(r)))
    assert result.checks["C2"].code == code
    assert result.verdict is qa.Verdict.UNVERIFIABLE


def test_missing_verify_material_is_unverifiable() -> None:
    result = qa.judge_record({"slug": "no-verify", "answer": "3", "unit_codes": ["SYN"]})
    assert result.verdict is qa.Verdict.UNVERIFIABLE
    assert result.checks["C1"].code == "C1_NO_VERIFY_MATERIAL"


def test_missing_answer_is_a_failure() -> None:
    mutated = _inject(_single_assignment(), lambda r: r.pop("answer"))
    assert qa.judge_record(mutated).checks["C1"].code == "C1_ANSWER_MISSING"
    assert _verdict(mutated) is qa.Verdict.FAIL


def test_check_exception_becomes_unverifiable_with_the_type_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_: Record) -> qa.CheckResult:
        raise MemoryError("x")

    monkeypatch.setattr(qa, "_check_c3", boom)
    result = qa.judge_record(_multiple_choice())
    assert result.checks["C3"].code == "CHECK_EXCEPTION"
    assert result.checks["C3"].detail == "MemoryError"
    assert result.verdict is qa.Verdict.UNVERIFIABLE


# ──────────────────────────────────────────────────────────────────────────
# 4-b. 절마다 그 절이 없으면 통과해 버리는 반례 — 뮤테이션이 닿도록 각 절의 픽스처를 둔다
# ──────────────────────────────────────────────────────────────────────────
def _multivar() -> Record:
    """answer_map 에 변수 둘 — `answer` 는 y 의 값이고 풀이의 마지막 단계는 x 에 대한 것이다."""
    return {
        "slug": "syn-multivar",
        "unit_codes": ["SYN"],
        "question_format": "단답형",
        "answer": "14",
        "verify": {
            "conditions": ["x + 2 = 0", "y = x**2 + 3"],
            "answer_map": {"x": "-2", "y": "7"},
            "solution_steps": ["x + 2 = 0", "x = -2"],
        },
    }


def test_last_step_variable_that_is_not_the_answer_variable_is_unverifiable() -> None:
    """마지막 단계가 중간 변수(x)에 대한 것이면 그것은 최종 답을 말한 단계가 아니다."""
    record = _inject(_multivar(), lambda r: r.update(answer="7"))  # 정답은 y=7
    result = qa.judge_record(record)
    assert result.checks["C1"].state is qa.CheckState.PASS
    assert result.checks["C2"].code == "C2_FINAL_STEP_VAR_NOT_ANSWER_VAR"


def test_mixed_variables_in_the_last_step_are_not_an_answer_form() -> None:
    record = _inject(
        _single_assignment(),
        lambda r: r["verify"]["solution_steps"].__setitem__(-1, "y = -4, z = 1"),
    )
    assert qa.judge_record(record).checks["C2"].code == "C2_FINAL_STEP_NOT_ANSWER_FORM"


def test_conceptual_kind_checks_the_answer_field_directly() -> None:
    count = {
        "slug": "syn-count",
        "unit_codes": ["SYN"],
        "question_format": "단답형",
        "answer": "1",
        "verify": {
            "conditions": "2*x**3 - 3*x**2 - 12*x - 9 = 0",
            "answer_map": {},
            "answer_kind": "real_root_count",
        },
    }
    assert qa.judge_record(count).checks["C1"].state is qa.CheckState.PASS
    wrong = _inject(count, lambda r: r.update(answer="3"))
    assert qa.judge_record(wrong).checks["C1"].code == "C1_CONCEPTUAL_FAIL"


def test_root_aggregate_checks_the_answer_field_directly() -> None:
    aggregate = {
        "slug": "syn-sum",
        "unit_codes": ["SYN"],
        "question_format": "단답형",
        "answer": "5",
        "verify": {
            "conditions": "x**2 - 5*x + 6 = 0",
            "answer_map": {},
            "answer_aggregate": "sum",
        },
    }
    assert qa.judge_record(aggregate).checks["C1"].state is qa.CheckState.PASS
    wrong = _inject(aggregate, lambda r: r.update(answer="6"))
    assert qa.judge_record(wrong).checks["C1"].code == "C1_AGGREGATE_FAIL"


def test_root_selection_declared_in_metadata_is_enforced() -> None:
    """`answer_selection=smallest` 인데 정답이 큰 근이면 조건은 만족해도 RED(C1)."""
    record = _inject(_root_pick(), lambda r: r["verify"].update(answer_selection="smallest"))
    assert qa.judge_record(record).checks["C1"].code == "C1_SELECTION_FAIL"


def test_selection_pass_requires_the_picked_root_to_equal_the_answer() -> None:
    """후보 나열 + 선택 규칙이 정답을 고르지 못하면 PASS 로 세지 않는다(거짓 통과 방지).

    FAIL 도 아니다 — 정답이 후보의 함수일 수 있다(47건 거짓 실패 회귀 고정). 실제 오류는 C4 가 잡는다.
    """
    record = _inject(
        _root_pick(),
        lambda r: r["verify"]["solution_steps"].__setitem__(-1, "x = -2, x = 5"),
    )
    result = qa.judge_record(record)
    assert result.checks["C2"].code == "C2_ANSWER_NOT_SELECTED_CANDIDATE"
    assert result.checks["C2"].state is qa.CheckState.UNVERIFIABLE
    assert (
        result.checks["C4"].state is qa.CheckState.FAIL
    )  # 도출 단계(인수분해)와 어긋난 후보를 C4 가 잡는다


def test_two_distractors_with_the_same_value_turn_red() -> None:
    """정답과는 다르지만 오답 보기끼리 값이 같다(`4` ↔ `8/2`) — 문자열이 달라 정확 일치로는 안 보인다."""
    record = _inject(_multiple_choice(), lambda r: r.update(choices=["-4", "4", "8/2", "-8"]))
    assert qa.judge_record(record).checks["C3"].code == "C3_DUPLICATE_CHOICE"


def test_identical_text_choices_are_duplicates_even_when_values_are_not_comparable() -> None:
    """수식으로 읽히지 않는 보기(`ㄱ, ㄴ` 같은 보기 조합)가 똑같이 두 번 나오면 문자열 일치로 확정 RED.

    정본 채점기는 이런 문자열을 같은 것끼리도 'unknown' 으로 돌려준다(2026-10-18 실측). 문자열
    중복 검사가 없으면 이 문항은 '비교 불가'로 검증 불가에 숨는다(뮤테이션 M06 생존으로 발각).
    """
    record = _inject(
        _multiple_choice(), lambda r: r.update(choices=["-4", "ㄱ, ㄴ", "ㄱ, ㄴ", "-8"])
    )
    assert qa.judge_record(record).checks["C3"].code == "C3_DUPLICATE_CHOICE"
    assert qa.judge_record(record).checks["C3"].state is qa.CheckState.FAIL


def test_a_single_choice_is_not_a_multiple_choice_question() -> None:
    record = _inject(_multiple_choice(), lambda r: r.update(choices=["-4"]))
    assert qa.judge_record(record).checks["C3"].code == "C3_TOO_FEW_CHOICES"


def test_choice_that_cannot_be_compared_blocks_the_exactly_once_claim() -> None:
    """정답 보기가 하나 확인돼도, 값을 비교할 수 없는 보기가 남으면 '정확히 한 번'을 단정하지 않는다."""
    record = _inject(
        _multiple_choice(), lambda r: r.update(choices=["-4", "4", "-8", "아무것도 아님"])
    )
    result = qa.judge_record(record)
    assert result.checks["C3"].state is qa.CheckState.UNVERIFIABLE
    assert result.verdict is qa.Verdict.UNVERIFIABLE


def test_unjudgeable_step_in_the_chain_is_unverifiable_not_pass() -> None:
    record = _inject(
        _single_assignment(),
        lambda r: r["verify"].update(
            solution_steps=r["verify"]["solution_steps"][:3] + ["이제 y 의 값을 정리한다", "y = -4"]
        ),
    )
    assert qa.judge_record(record).checks["C4"].code == "C4_STEP_UNVERIFIABLE"


def test_comma_inside_a_function_call_is_not_a_candidate_separator() -> None:
    """`y = Min(-4, 3)` 은 값 하나다 — 괄호 안 쉼표로 잘라 근 나열로 오독하면 PASS 가 UNVERIFIABLE 로 샌다."""
    record = _inject(
        _single_assignment(),
        lambda r: r["verify"]["solution_steps"].__setitem__(-1, "y = Min(-4, 3)"),
    )
    assert qa.judge_record(record).checks["C2"].state is qa.CheckState.PASS


# ──────────────────────────────────────────────────────────────────────────
# 5. 집계 — 검증 불가는 분모에도 분자에도 안 들어가고, 따로 보인다
# ──────────────────────────────────────────────────────────────────────────
def _mixed_report() -> qa.SolutionQaReport:
    unverifiable = _inject(_single_assignment(), lambda r: r["verify"].pop("solution_steps"))
    failing = _wrong_answer(_single_assignment())
    return qa.run_solution_qa([_single_assignment(), _multiple_choice(), failing, unverifiable])


def test_rate_excludes_unverifiable_and_reports_coverage_separately() -> None:
    report = _mixed_report()
    assert (report.passed, report.failed, report.unverifiable) == (2, 1, 1)
    assert report.pass_rate == pytest.approx(2 / 3)
    assert report.decidable_ratio == pytest.approx(3 / 4)


def test_all_unverifiable_has_no_rate() -> None:
    unverifiable = _inject(_single_assignment(), lambda r: r["verify"].pop("solution_steps"))
    report = qa.run_solution_qa([unverifiable])
    assert report.pass_rate is None  # 0% 도 100% 도 아니다


def test_failures_and_queue_are_listed_in_full() -> None:
    report = _mixed_report()
    assert [ident for ident, _ in report.failures] == ["syn-assign"]
    assert [item.ident for item in report.queue] == ["syn-assign"]
    assert report.reason_counts(qa.CheckState.UNVERIFIABLE) == {"C2:C2_NO_STEPS": 1}


# ──────────────────────────────────────────────────────────────────────────
# 6. CLI 종료 코드 — 판정은 exit code 로 한다
# ──────────────────────────────────────────────────────────────────────────
def _write(tmp_path: Path, records: list[Record], name: str = "bank.jsonl") -> Path:
    path = tmp_path / name
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), "utf-8")
    return path


def test_cli_exit_0_when_everything_decided_passes(tmp_path: Path) -> None:
    path = _write(tmp_path, [_single_assignment(), _multiple_choice()])
    assert qa.main([str(path)]) == qa.EXIT_OK


def test_cli_exit_1_on_any_failure(tmp_path: Path) -> None:
    path = _write(tmp_path, [_single_assignment(), _wrong_answer(_single_assignment())])
    assert qa.main([str(path)]) == qa.EXIT_FAIL


def test_cli_exit_1_on_a_single_failure_even_when_the_rate_is_above_any_target(
    tmp_path: Path,
) -> None:
    """영 허용 고정 — 456건 중 1건 실패는 통과율 99.78% 로 99.5% 위지만 게이트는 빨개야 한다.

    비율 판정이면 코퍼스가 클수록 확정된 불일치를 삼킨다(실 코퍼스 주입 실측). 판정을 임계 비교로
    되돌리면 이 테스트가 RED 가 된다(뮤테이션 M33).
    """
    good = [_single_assignment() | {"slug": f"ok-{i}"} for i in range(400)]
    path = _write(tmp_path, [*good, _wrong_answer(_single_assignment())])
    assert qa.main([str(path)]) == qa.EXIT_FAIL


def test_cli_has_no_ineffective_target_switch() -> None:
    """효력 없는 스위치를 두지 않는다 — `--target` 을 주면 인자 오류다."""
    with pytest.raises(SystemExit):
        qa.main(["--target", "0.99"])


def test_cli_exit_2_when_nothing_is_measurable(tmp_path: Path) -> None:
    empty = _write(tmp_path, [], "empty.jsonl")
    assert qa.main([str(empty)]) == qa.EXIT_UNMEASURED
    unverifiable = _inject(_single_assignment(), lambda r: r["verify"].pop("solution_steps"))
    assert qa.main([str(_write(tmp_path, [unverifiable], "unv.jsonl"))]) == qa.EXIT_UNMEASURED


def test_cli_writes_json_and_the_full_review_queue(tmp_path: Path) -> None:
    unverifiable = _inject(_single_assignment(), lambda r: r["verify"].pop("solution_steps"))
    path = _write(tmp_path, [_single_assignment(), unverifiable])
    out_json, out_queue = tmp_path / "out.json", tmp_path / "queue.jsonl"
    assert qa.main([str(path), "--json", str(out_json), "--queue-out", str(out_queue)]) == 0
    payload = json.loads(out_json.read_text("utf-8"))
    assert payload["passed"] == 1 and payload["unverifiable"] == 1
    assert payload["unverifiable_reasons"] == {"C2:C2_NO_STEPS": 1}
    rows = [json.loads(line) for line in out_queue.read_text("utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["reasons"][0]["code"] == "C2_NO_STEPS"


# ──────────────────────────────────────────────────────────────────────────
# 7. 실 코퍼스 레코드에 같은 3종 주입 — 합성 대조군에서만 통하는 검출기가 아님을 보인다
# ──────────────────────────────────────────────────────────────────────────
def _real_controls() -> dict[str, Record]:
    """P3 미분 은행에서 형태별 대조 레코드를 하나씩 — 현재 판정이 PASS 인 것만 쓴다."""
    found: dict[str, Record] = {}
    with P3_DIFF_BANK.open(encoding="utf-8") as handle:
        for line in handle:
            record: Record = json.loads(line)
            if record.get("review_status") != "approved":
                continue
            if qa.judge_record(record).verdict is not qa.Verdict.PASS:
                continue
            steps = (record.get("verify") or {}).get("solution_steps") or []
            if not steps:
                continue
            shape = (
                "choices" if record.get("choices") else ("roots" if "," in steps[-1] else "assign")
            )
            found.setdefault(shape, record)
            if len(found) == 3:
                break
    return found


@pytest.fixture(scope="module")
def real_controls() -> dict[str, Record]:
    controls = _real_controls()
    assert set(controls) == {"assign", "roots", "choices"}, (
        f"실 코퍼스에서 대조 레코드를 못 찾았다(찾은 형태: {sorted(controls)}) — "
        "이 테스트가 공허하게 통과하지 않도록 실패시킨다"
    )
    return controls


def test_real_records_injection_wrong_answer_turns_red(real_controls: dict[str, Record]) -> None:
    for shape, record in real_controls.items():
        mutated = _wrong_answer(record)
        assert _verdict(mutated) is qa.Verdict.FAIL, shape


def test_real_records_injection_wrong_final_step_turns_red(
    real_controls: dict[str, Record],
) -> None:
    for shape in ("assign", "roots"):
        mutated = _wrong_final_step(real_controls[shape])
        assert _verdict(mutated) is qa.Verdict.FAIL, shape


def test_real_records_injection_duplicate_choice_turns_red(
    real_controls: dict[str, Record],
) -> None:
    record = real_controls["choices"]
    # 정답이 아닌 보기 두 개의 자리를 찾아, 하나를 다른 하나의 복사본으로 만든다.
    answer = record["answer"]
    others = [i for i, c in enumerate(record["choices"]) if c.strip() != answer.strip()]

    def mutate(r: Record) -> None:
        r["choices"][others[1]] = r["choices"][others[0]]

    assert _verdict(_inject(record, mutate)) is qa.Verdict.FAIL


# ──────────────────────────────────────────────────────────────────────────
# 8. 주입 헬퍼 자체의 변별력 — 대조군에 주입이 닿지 않으면 위 테스트가 위장이 된다
# ──────────────────────────────────────────────────────────────────────────
def test_inject_helper_rejects_a_noop_mutation() -> None:
    with pytest.raises(AssertionError, match="주입이 레코드를 바꾸지 못했다"):
        _inject(_single_assignment(), lambda r: None)
