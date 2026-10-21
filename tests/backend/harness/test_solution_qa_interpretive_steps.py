"""Solution QA 판정기 확장(P3-71) — 해석 단계(근 선택·대입)와 도메인 제약 근 선택의 RED 테스트.

확장은 판정을 *넓히는* 일이라 그 자체로 위험하다: 넓힌 자리로 틀린 풀이가 빠져나가면 기준 완화다.
그래서 이 파일은 확장마다 ①대조군(성립 → PASS) ②주입 3종(잘못된 근 선택·틀린 대입값·제약 위반 근 →
FAIL) ③근거가 조건에 없을 때 통과가 아니라 검증 불가인지를 함께 본다. 모든 주입은 레코드를 실제로
바꿨는지 단언한다(`_inject`). 마지막 절은 같은 주입을 실 코퍼스 레코드에 건다.
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
P3_FILL_BANK = REPO / "data/corpus/problem_bank_p3_fill_v0/problems.jsonl"


def _inject(record: Record, mutate: Callable[[Record], None]) -> Record:
    mutated = copy.deepcopy(record)
    mutate(mutated)
    assert mutated != record, "주입이 레코드를 바꾸지 못했다 — 이 테스트는 아무것도 검증하지 못한다"
    return mutated


def _steps(record: Record) -> list[str]:
    steps: list[str] = record["verify"]["solution_steps"]
    return steps


# ──────────────────────────────────────────────────────────────────────────
# 합성 대조 레코드
# ──────────────────────────────────────────────────────────────────────────
def _domain_roots() -> Record:
    """'양수 a' — 풀이가 두 근을 나열하고 조건의 `a > 0` 이 정답 근을 고른다(02-01 미분계수형)."""
    return {
        "slug": "syn-domain-roots",
        "unit_codes": ["SYN"],
        "question_format": "단답형",
        "answer": "6",
        "verify": {
            "conditions": ["Derivative(x**3, x).doit().subs(x, a) = 108", "a > 0"],
            "answer_map": {"a": "6"},
            "solution_steps": [
                "Derivative(x**3, x).doit().subs(x, a) = 108",
                "(3*x**2).subs(x, a) = 108",
                "3*(a)**2 = 108",
                "3*a**2 - 108 = 0",
                "3*(a - 6)*(a + 6) = 0",
                "a = -6, a = 6",
            ],
        },
    }


def _boundary_roots() -> Record:
    """엄격 부등식의 **경계**에 후보가 있는 문항 — `s > 3` 에 후보 3 은 모호가 아니라 위반이다."""
    return {
        "slug": "syn-boundary-roots",
        "unit_codes": ["SYN"],
        "question_format": "단답형",
        "answer": "5",
        "verify": {
            "conditions": [
                "Derivative(4*t**3 - 48*t**2 + 180*t + 2, t).doit().subs(t, s) = 0",
                "s > 3",
            ],
            "answer_map": {"s": "5"},
            "solution_steps": [
                "Derivative(4*t**3 - 48*t**2 + 180*t + 2, t).doit().subs(t, s) = 0",
                "(12*t**2 - 96*t + 180).subs(t, s) = 0",
                "12*(s)**2 - 96*(s) + 180 = 0",
                "12*s**2 - 96*s + 180 = 0",
                "12*(s - 5)*(s - 3) = 0",
                "s = 3, s = 5",
            ],
        },
    }


def _domain_selection_step() -> Record:
    """`_domain_roots` 에 근 선택 단계 `a = 6` 을 덧붙인 풀이 — C4 가 그 해석 단계를 판정한다."""
    record = _domain_roots()
    record["slug"] = "syn-domain-select-step"
    _steps(record).append("a = 6")
    return record


def _substitution() -> Record:
    """임계점 두 개 → 도메인 `x >= 0` 으로 x 선택 → 정의 등식 `y = f(x)` 에 대입(극값의 값형)."""
    return {
        "slug": "syn-substitution",
        "unit_codes": ["SYN"],
        "question_format": "단답형",
        "answer": "4",
        "verify": {
            "conditions": [
                "Derivative(2*x**3 - 6*x**2 - 18*x + 58, x).doit() = 0",
                "y = 2*x**3 - 6*x**2 - 18*x + 58",
                "x >= 0",
            ],
            "answer_map": {"x": "3", "y": "4"},
            "solution_steps": [
                "Derivative(2*x**3 - 6*x**2 - 18*x + 58, x).doit() = 0",
                "6*x**2 - 12*x - 18 = 0",
                "6*(x - 3)*(x + 1) = 0",
                "x = -1, x = 3",
                "y = 4",
            ],
        },
    }


def _selection_rule_step() -> Record:
    """도메인 없이 `answer_selection=largest` 가 고르는 근 선택 단계(근은 조건 등식의 근이다)."""
    return {
        "slug": "syn-rule-select-step",
        "unit_codes": ["SYN"],
        "question_format": "단답형",
        "answer": "4",
        "verify": {
            "conditions": "3*x**2 - 6*x - 24 = 0",
            "answer_map": {"x": "4"},
            "answer_selection": "largest",
            "solution_steps": [
                "3*x**2 - 6*x - 24 = 0",
                "3*(x - 4)*(x + 2) = 0",
                "x = -2, x = 4",
                "x = 4",
            ],
        },
    }


CONTROLS: dict[str, Callable[[], Record]] = {
    "domain_roots": _domain_roots,
    "boundary_roots": _boundary_roots,
    "domain_selection_step": _domain_selection_step,
    "substitution": _substitution,
    "selection_rule_step": _selection_rule_step,
}


@pytest.mark.parametrize("name", sorted(CONTROLS))
def test_controls_are_fully_decided_and_pass(name: str) -> None:
    item = qa.judge_record(CONTROLS[name]())
    assert item.verdict is qa.Verdict.PASS, item.reason_text()
    assert all(
        res.state in (qa.CheckState.PASS, qa.CheckState.NOT_APPLICABLE)
        for res in item.checks.values()
    )


# ──────────────────────────────────────────────────────────────────────────
# ② 도메인 제약으로 근 선택 (C2)
# ──────────────────────────────────────────────────────────────────────────
def test_c2_reads_the_domain_constraint_to_pick_the_root() -> None:
    """종전 C2_ROOT_CHOICE_UNSTRUCTURED(검증 불가) 문항이 도메인 제약으로 판정된다."""
    assert qa.judge_record(_domain_roots()).checks["C2"].state is qa.CheckState.PASS


def test_injection_wrong_root_selection_is_caught_by_c2_itself() -> None:
    """정답·answer_map 을 제약 밖 근(-6)으로 — C1 과 별개로 C2 가 '도메인이 고른 근 ≠ 정답'을 낸다."""

    def mutate(r: Record) -> None:
        r["answer"] = "-6"
        r["verify"]["answer_map"] = {"a": "-6"}

    item = qa.judge_record(_inject(_domain_roots(), mutate))
    assert item.verdict is qa.Verdict.FAIL
    assert item.checks["C2"].code == "C2_DOMAIN_PICK_MISMATCH"


def test_injection_constraint_violating_answer_is_red() -> None:
    """도메인을 `a > 10` 으로 — 풀이의 근이 전부 제약 밖인데 정답이 있다(모순 확정)."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"][1] = "a > 10"

    item = qa.judge_record(_inject(_domain_roots(), mutate))
    assert item.verdict is qa.Verdict.FAIL
    # C1 도 같은 문항을 FAIL 로 만들므로 판정만 보면 C2 가 검증 불가로 물러서도 초록이다 —
    # C2 자신의 상태를 단언한다(뮤테이션 M2 가 이 단언 없이 살아남았다).
    assert item.checks["C2"].state is qa.CheckState.FAIL
    assert item.checks["C2"].code == "C2_DOMAIN_NO_ADMISSIBLE_CANDIDATE"


def test_exact_boundary_candidate_is_rejected_not_left_ambiguous() -> None:
    """`s > 3` 의 후보 3 을 수치 허용치로 '모호'에 접으면 판정 가능한 문항을 놓친다."""
    assert qa.judge_record(_boundary_roots()).checks["C2"].state is qa.CheckState.PASS

    def mutate(r: Record) -> None:
        r["verify"]["conditions"][1] = "s >= 3"  # 이제 두 후보 모두 허용 → 고를 수 없다

    item = qa.judge_record(_inject(_boundary_roots(), mutate))
    assert item.checks["C2"].code == "C2_DOMAIN_AMBIGUOUS"
    assert item.verdict is qa.Verdict.UNVERIFIABLE


def test_two_admissible_candidates_are_unverifiable_not_pass() -> None:
    def mutate(r: Record) -> None:
        r["verify"]["conditions"][1] = "a != 0"

    item = qa.judge_record(_inject(_domain_roots(), mutate))
    assert item.checks["C2"].code == "C2_DOMAIN_AMBIGUOUS"
    assert item.verdict is qa.Verdict.UNVERIFIABLE


def test_candidates_that_are_not_roots_of_the_condition_are_not_compared() -> None:
    """후보가 조건 등식의 근이 아니면 C2 는 비교하지 않는다(C4 가 그 잘못된 단계를 잡는다)."""

    def mutate(r: Record) -> None:
        _steps(r)[-1] = "a = -6, a = 7"

    item = qa.judge_record(_inject(_domain_roots(), mutate))
    assert item.checks["C2"].code == "C2_DOMAIN_CANDIDATE_NOT_ROOT"
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"
    assert item.verdict is qa.Verdict.FAIL


def test_domain_filter_is_not_applied_when_the_answer_is_not_a_root() -> None:
    """개수형(answer_kind)·answer_map 없음 — 정답이 후보의 함수라 도메인 선택을 적용하지 않는다."""

    def mutate(r: Record) -> None:
        r["answer"] = "1"
        r["verify"]["answer_map"] = {}
        r["verify"]["answer_kind"] = "real_root_count"

    item = qa.judge_record(_inject(_domain_roots(), mutate))
    assert item.checks["C2"].code == "C2_ROOT_CHOICE_UNSTRUCTURED"


def test_domain_filter_needs_an_answer_map() -> None:
    """answer_map 이 비면(정답이 근이 아닌 개수·값) 마지막 단계 변수가 정답 변수인지 모른다."""

    def mutate(r: Record) -> None:
        r["answer"] = "2"
        r["verify"]["answer_map"] = {}

    item = qa.judge_record(_inject(_domain_roots(), mutate))
    assert item.checks["C2"].code == "C2_ROOT_CHOICE_UNSTRUCTURED"


def test_answer_kind_blocks_the_domain_filter_even_when_values_coincide() -> None:
    """개념형 문항의 정답이 우연히 허용 근과 같은 값이어도 근 선택으로 통과시키지 않는다."""

    def mutate(r: Record) -> None:
        r["verify"]["answer_kind"] = "real_root_count"

    item = qa.judge_record(_inject(_domain_roots(), mutate))
    assert item.checks["C2"].code == "C2_ROOT_CHOICE_UNSTRUCTURED"


def test_selection_is_never_derived_from_the_answer() -> None:
    """P3-24 B3 단서: 조건에 도메인이 없으면 정답이 후보 중 하나여도 고르지 않는다(순환 통과 금지)."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"] = r["verify"]["conditions"][:1]

    item = qa.judge_record(_inject(_domain_roots(), mutate))
    assert item.checks["C2"].code == "C2_ROOT_CHOICE_UNSTRUCTURED"
    assert item.verdict is qa.Verdict.UNVERIFIABLE


# ──────────────────────────────────────────────────────────────────────────
# ① C4 해석 단계 — 근 선택
# ──────────────────────────────────────────────────────────────────────────
def test_selection_step_is_judged_not_waved_through() -> None:
    item = qa.judge_record(_domain_selection_step())
    assert item.checks["C4"].state is qa.CheckState.PASS


def test_injection_selection_step_picks_the_constraint_violating_root() -> None:
    """선택 단계가 제약 밖 근 -6 을 고른다 — C2 와 별개로 C4 자신이 그 전이를 incorrect 로 내는지 본다."""

    def mutate(r: Record) -> None:
        _steps(r)[-1] = "a = -6"

    item = qa.judge_record(_inject(_domain_selection_step(), mutate))
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"
    assert "근 선택" in (item.checks["C4"].detail or "")
    assert item.verdict is qa.Verdict.FAIL


def test_injection_selection_step_against_the_selection_rule() -> None:
    """answer_selection=largest 인데 선택 단계가 작은 근 -2 를 고른다."""

    def mutate(r: Record) -> None:
        _steps(r)[-1] = "x = -2"

    item = qa.judge_record(_inject(_selection_rule_step(), mutate))
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"
    assert item.verdict is qa.Verdict.FAIL


def test_injection_selection_step_against_the_smallest_rule() -> None:
    """answer_selection=smallest 인데 선택 단계가 큰 근 4 를 고른다 — 규칙 위반 확정(C4 FAIL).
    대조: 같은 규칙에서 작은 근 -2 를 고르면 그 전이는 성립한다."""

    def violate(r: Record) -> None:
        r["verify"]["answer_selection"] = "smallest"

    item = qa.judge_record(_inject(_selection_rule_step(), violate))
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"
    assert "근 선택" in (item.checks["C4"].detail or "")

    def follow(r: Record) -> None:
        r["verify"]["answer_selection"] = "smallest"
        r["answer"] = "-2"
        r["verify"]["answer_map"] = {"x": "-2"}
        _steps(r)[-1] = "x = -2"

    control = qa.judge_record(_inject(_selection_rule_step(), follow))
    assert control.checks["C4"].state is qa.CheckState.PASS


def test_selection_step_without_a_rule_is_unverifiable_not_pass() -> None:
    def mutate(r: Record) -> None:
        r["verify"]["conditions"] = r["verify"]["conditions"][:1]

    item = qa.judge_record(_inject(_domain_selection_step(), mutate))
    assert item.checks["C4"].code == "C4_STEP_UNVERIFIABLE"
    assert item.verdict is qa.Verdict.UNVERIFIABLE


def test_selection_is_checked_against_the_conditions_root_set_not_the_listed_candidates() -> None:
    """조건 등식의 근은 4·8 이고 largest 는 8 — 풀이가 나열한 후보(-2, 4)에서 4 를 골라도 그것은
    조건이 요구하는 근이 아니다. 근 집합을 후보 나열이 아니라 조건으로 계산한다(PR #1703 상2)."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"] = "x**2 - 12*x + 32 = 0"

    item = qa.judge_record(_inject(_selection_rule_step(), mutate))
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"


def test_selected_value_that_is_not_a_root_of_the_condition_is_not_judged() -> None:
    """고른 값이 조건 등식의 근이 아니면(후보가 다른 식의 해) 선택을 판정하지 않는다."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"] = "x**2 - 13*x + 40 = 0"  # 근 5, 8 — 고른 4 는 근이 아니다

    item = qa.judge_record(_inject(_selection_rule_step(), mutate))
    assert item.checks["C4"].code == "C4_STEP_UNVERIFIABLE"


def test_unparsable_condition_blocks_the_selection_judgement() -> None:
    """파싱 못 한 조건이 도메인 제약인지 모르므로, 그 상태로 '제약은 a > 0 뿐'이라고 고르지 않는다."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"].append("a >> 0 (")

    item = qa.judge_record(_inject(_domain_selection_step(), mutate))
    assert item.checks["C4"].code == "C4_STEP_UNVERIFIABLE"


def test_symbolic_value_step_is_not_an_interpretive_step() -> None:
    """뒤 단계 값이 수치가 아니면(`y = x**2 + 1`) 해석 단계로 보지 않는다 — 동치 판정이 남는다."""

    def mutate(r: Record) -> None:
        _steps(r)[-1] = "y = x**2 + 1"

    item = qa.judge_record(_inject(_substitution(), mutate))
    assert item.checks["C4"].code == "C4_STEP_UNVERIFIABLE"  # verify_step 의 판정 그대로
    assert "해석 단계" not in (item.checks["C4"].detail or "")


def test_unjudged_interpretive_step_is_counted_in_the_detail() -> None:
    def mutate(r: Record) -> None:
        r["verify"]["conditions"] = r["verify"]["conditions"][:1]

    item = qa.judge_record(_inject(_domain_selection_step(), mutate))
    assert item.checks["C4"].detail == "1/6전이·해석 단계 1"


def test_value_outside_the_candidates_is_not_a_selection_and_stays_incorrect() -> None:
    """후보 밖 값으로 가는 단계는 해석 단계가 아니다 — 동치 판정(incorrect)이 그대로 남는다."""

    def mutate(r: Record) -> None:
        _steps(r)[-1] = "a = 7"

    item = qa.judge_record(_inject(_domain_selection_step(), mutate))
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"
    assert "해석 단계" not in (item.checks["C4"].detail or "")


# ──────────────────────────────────────────────────────────────────────────
# ① C4 해석 단계 — 대입
# ──────────────────────────────────────────────────────────────────────────
def test_substitution_step_is_judged_against_the_defining_condition() -> None:
    item = qa.judge_record(_substitution())
    assert item.checks["C4"].state is qa.CheckState.PASS
    assert item.checks["C2"].state is qa.CheckState.PASS


def test_injection_wrong_substituted_value_turns_red() -> None:
    """틀린 대입값 — 정답·answer_map 도 같은 틀린 값으로 맞춰, C4 가 대입 자체를 잡는지 본다."""

    def mutate(r: Record) -> None:
        _steps(r)[-1] = "y = 5"
        r["answer"] = "5"
        r["verify"]["answer_map"]["y"] = "5"

    item = qa.judge_record(_inject(_substitution(), mutate))
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"
    assert "대입" in (item.checks["C4"].detail or "")
    assert item.verdict is qa.Verdict.FAIL


def test_injection_substitution_of_the_constraint_violating_candidate_turns_red() -> None:
    """제약 밖 후보 x = -1 을 대입한 값 f(-1) = 68 — 도메인이 고른 x = 3 의 값이 아니다."""

    def mutate(r: Record) -> None:
        _steps(r)[-1] = "y = 68"
        r["answer"] = "68"
        r["verify"]["answer_map"] = {"x": "-1", "y": "68"}

    item = qa.judge_record(_inject(_substitution(), mutate))
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"
    assert item.verdict is qa.Verdict.FAIL


def test_substitution_after_candidates_without_a_rule_keeps_the_old_failure() -> None:
    """후보 둘 중 어느 x 인지 조건이 말하지 않으면 결과값에 맞는 후보를 거꾸로 찾지 않는다 — 성립을
    증명하지 못한 변수 전환은 종전 동치 판정(incorrect)을 그대로 둔다(PR #1703 중4)."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"] = r["verify"]["conditions"][:2]

    item = qa.judge_record(_inject(_substitution(), mutate))
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"
    assert item.verdict is qa.Verdict.FAIL


def test_substitution_needs_a_definition_without_borrowed_parameters() -> None:
    """정의 등식에 다른 매개변수(a)가 섞이면 그 값을 정답 기록에서 빌려 와야 하므로 판정하지 않는다."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"][1] = "y = 2*x**3 + a*x**2 - 18*x + 58"
        r["verify"]["answer_map"]["a"] = "-6"

    item = qa.judge_record(_inject(_substitution(), mutate))
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"  # 증명 못 한 변수 전환 — 종전 FAIL 유지


def test_parameterized_definition_alongside_a_pure_one_blocks_the_proof() -> None:
    """정의 등식이 둘(매개변수 섞인 것 + 순수 {x, y})이면 x 를 다른 변수와 함께 담은 조건이 남아
    증명하지 않는다 — 그 매개변수 등식이 x 를 더 제약하는지 모른다(PR #1703 재검토 MV2). 변수 전환은
    종전 동치 판정(incorrect)을 유지한다."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"].append("y = 2*x**3 + b*x**2 - 18*x + 58")

    item = qa.judge_record(_inject(_substitution(), mutate))
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"


def test_substitution_without_a_defining_condition_keeps_the_old_failure() -> None:
    def mutate(r: Record) -> None:
        del r["verify"]["conditions"][1]

    item = qa.judge_record(_inject(_substitution(), mutate))
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"


def test_one_unproven_definition_blocks_the_substitution_proof() -> None:
    """정의 등식이 둘(`y = f(x)` 와 `y = sqrt(x - 10)`)이고 하나가 x = 3 에서 실수 y 를 주지 못하면
    성립 증명이 아니다 — 하나만 맞는다고 통과시키지 않는다(종전 FAIL 유지)."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"].append("y = sqrt(x - 10)")

    item = qa.judge_record(_inject(_substitution(), mutate))
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"


# ──────────────────────────────────────────────────────────────────────────
# PR #1703 검토 반례 — main 에서 FAIL 이던 입력은 FAIL, 판정 불가이던 입력은 PASS 로 새지 않는다
# ──────────────────────────────────────────────────────────────────────────
def _rec(conditions: list[str], answer: str, amap: dict[str, str], steps: list[str]) -> Record:
    return {
        "slug": "adv",
        "unit_codes": ["SYN"],
        "question_format": "단답형",
        "answer": answer,
        "verify": {"conditions": conditions, "answer_map": amap, "solution_steps": steps},
    }


ADVERSARIAL: dict[str, tuple[Record, qa.Verdict]] = {
    # 상1 — 첫 줄의 틀린 값(도메인 위반·근 아님)에 맞는 대입을 한 풀이
    "A3d 도메인 위반 값 대입": (
        _rec(
            ["a**2 - 4 = 0", "a > 0", "y = a**2 + 1"],
            "5",
            {"a": "2", "y": "5"},
            ["a = -2", "y = 5"],
        ),
        qa.Verdict.FAIL,
    ),
    "A3c 등식의 근 아닌 값 대입": (
        _rec(["x**3 = 27", "y = x**2"], "9", {"x": "3", "y": "9"}, ["x = -3", "y = 9"]),
        qa.Verdict.FAIL,
    ),
    "A3 도메인 위반 값 대입(등식 둘)": (
        _rec(["y = x**2", "x > 0", "x**2 = 9"], "9", {"x": "3", "y": "9"}, ["x = -3", "y = 9"]),
        qa.Verdict.FAIL,
    ),
    "A3b 등식 단계 뒤 도메인 위반 값": (
        _rec(["y = x**2", "x > 0"], "9", {"x": "3", "y": "9"}, ["x**2 = 9", "x = -3", "y = 9"]),
        qa.Verdict.FAIL,
    ),
    # 중4 — 정의 등식 없는 변수 전환
    "A4 정의 없는 변수 전환": (
        _rec(["x**2 = 9", "x > 0"], "5", {"x": "3", "y": "5"}, ["x = 3", "y = 5"]),
        qa.Verdict.FAIL,
    ),
    # 상2 — 불완전한 후보 나열(허용 근 2·3 중 2만 남음)
    "A1 불완전 후보": (
        _rec(["(x-1)*(x-2)*(x-3) = 0", "x > 3/2"], "2", {"x": "2"}, ["x = 1, x = 2"]),
        qa.Verdict.UNVERIFIABLE,
    ),
    # 상3 — 주기함수(해 집합 불완전)
    "A9 삼각 등식 후보": (
        _rec(
            ["sin(x*pi/180) = 1/2", "x > 100", "x < 720"], "150", {"x": "150"}, ["x = 30, x = 150"]
        ),
        qa.Verdict.UNVERIFIABLE,
    ),
    # 재검토 상1 — 초월 등식의 부분 해를 "유일 근"으로 읽지 않는다
    "T1 초월 등식 값 대입": (
        _rec(["sin(x) = 1", "y = 2*x"], "pi", {"x": "pi/2", "y": "pi"}, ["x = pi/2", "y = pi"]),
        qa.Verdict.FAIL,
    ),
    "T3 초월 등식 근 선택": (
        _rec(["tan(x) = 1"], "pi/4", {"x": "pi/4"}, ["x = pi/4, x = 5*pi/4", "x = pi/4"]),
        qa.Verdict.UNVERIFIABLE,
    ),
    "T4 초월 등식 + answer_selection": (
        {
            **_rec(["sin(x*pi/180) = 1/2"], "150", {"x": "150"}, ["x = 30, x = 150", "x = 150"]),
            "verify": {
                "conditions": ["sin(x*pi/180) = 1/2"],
                "answer_map": {"x": "150"},
                "answer_selection": "largest",
                "solution_steps": ["x = 30, x = 150", "x = 150"],
            },
        },
        qa.Verdict.UNVERIFIABLE,
    ),
    # 재검토 MV2 — x 를 다른 변수와 함께 제약하는 조건을 무시한 증명
    "MV2 섞인 제약 무시": (
        {
            **_rec([], "3", {}, []),
            "verify": {
                "conditions": ["x**2 - 4 = 0", "x > -5", "x + z > 100", "y = x + 1"],
                "answer_map": {"x": "2", "y": "3", "z": "200"},
                "answer_selection": "largest",
                "solution_steps": ["x = -2, x = 2", "x = 2", "y = 3"],
            },
        },
        qa.Verdict.FAIL,
    ),
    # 재검토 중2 — 근사 중복 후보로 빠진 근(√2)을 가린 나열
    "N4a 근사 중복으로 근 누락": (
        _rec(
            ["x**3 - 2*x = 0", "x >= 0"],
            "0",
            {"x": "0"},
            ["x = -1.4142135623730951, x = -sqrt(2), x = 0"],
        ),
        qa.Verdict.UNVERIFIABLE,
    ),
    # 3차 검토 상1 — 평가 파싱의 자동 약분으로 무연근이 '다항 등식의 근'처럼 보이는 분수방정식
    "RF3 약분 무연근 x(x-2)/(x-2)=2": (
        _rec(["x*(x - 2)/(x - 2) = 2", "y = x + 1"], "3", {"x": "2", "y": "3"}, ["x = 2", "y = 3"]),
        qa.Verdict.FAIL,
    ),
    "RF4 약분 무연근 (x-2)^3/(x-2)^2=0": (
        _rec(
            ["(x - 2)**3/(x - 2)**2 = 0", "y = x**2"], "4", {"x": "2", "y": "4"}, ["x = 2", "y = 4"]
        ),
        qa.Verdict.FAIL,
    ),
    "RF5 음수 지수 표기": (
        _rec(["x*(x-2)*(x-2)**-1 = 2", "y = x + 1"], "3", {"x": "2", "y": "3"}, ["x = 2", "y = 3"]),
        qa.Verdict.FAIL,
    ),
    "RF6 분모 속 분수 표기": (
        _rec(["x/((x-2)/(x-2)) = 2", "y = x + 1"], "3", {"x": "2", "y": "3"}, ["x = 2", "y = 3"]),
        qa.Verdict.FAIL,
    ),
    "RF7 같은 꼴·무연근 아닌 값(보수 — 증명하지 않음)": (
        _rec(["x*(x - 2)/(x - 2) = 3", "y = x + 1"], "4", {"x": "3", "y": "4"}, ["x = 3", "y = 4"]),
        qa.Verdict.FAIL,
    ),
    "RF8 약분 안 되는 분수방정식(대조 — 종전 판정 유지)": (
        _rec(
            ["x/(x + 5) = 1/3", "x > 0", "y = 2*x"],
            "5",
            {"x": "5/2", "y": "5"},
            ["x = 5/2", "y = 5"],
        ),
        qa.Verdict.FAIL,
    ),
    # 4차 검토 — 금지 목록 우회(허용 목록으로 구조적으로 막힌다)
    "B1 .doit() 래퍼 속 약분": (
        _rec(
            ["(x*(x - 2)/(x - 2)).doit() = 2", "y = x + 1"],
            "3",
            {"x": "2", "y": "3"},
            ["x = 2", "y = 3"],
        ),
        qa.Verdict.FAIL,
    ),
    "B3 exp(-log) 분모 대용": (
        _rec(
            ["x*(x - 2)*exp(-log(x - 2)) = 2", "y = x + 1"],
            "3",
            {"x": "2", "y": "3"},
            ["x = 2", "y = 3"],
        ),
        qa.Verdict.FAIL,
    ),
    "B10 0 제곱": (
        _rec(["x*(x - 2)**0 = 2", "y = x + 1"], "3", {"x": "2", "y": "3"}, ["x = 2", "y = 3"]),
        qa.Verdict.FAIL,
    ),
    # P3-75 — C1(Tier1)도 원문 정의역을 본다: x = 1 은 원문 분모 (x - 1) 이 0 이라 정의되지 않는다.
    # 종전(P3-71)에는 C2 가 허용 목록 밖이라 검증 불가였고 C1 은 자동 약분으로 통과했다.
    "D1 Derivative 속 약분(C2)": (
        _rec(
            ["Derivative(x**3*(x - 1)/(x - 1), x).doit() = 3", "x > 0"],
            "1",
            {"x": "1"},
            ["x = -1, x = 1"],
        ),
        qa.Verdict.FAIL,
    ),
    "D2 Derivative 속 약분(선택 뒤 대입)": (
        _rec(
            ["Derivative(x**3*(x - 1)/(x - 1), x).doit() = 3", "x > 0", "y = x + 5"],
            "6",
            {"x": "1", "y": "6"},
            ["x = -1, x = 1", "x = 1", "y = 6"],
        ),
        qa.Verdict.FAIL,
    ),
    "D3 Derivative 속 약분(값 대입)": (
        _rec(
            ["Derivative(x**3*(x - 1)/(x - 1), x).doit() = 3", "x > 0", "y = x + 5"],
            "6",
            {"x": "1", "y": "6"},
            ["x = 1", "y = 6"],
        ),
        qa.Verdict.FAIL,
    ),
    "NR1 허수부 1e-10 근(실근 없음)": (
        _rec(
            ["(x - 1)**2 + 10**(-20) = 0", "y = x + 1"],
            "2",
            {"x": "1", "y": "2"},
            ["x = 1", "y = 2"],
        ),
        qa.Verdict.FAIL,
    ),
    "NR2 같은 꼴·상수 나눗셈 표기": (
        _rec(
            ["(x - 1)**2 + 1/10**20 = 0", "y = x + 1"],
            "2",
            {"x": "1", "y": "2"},
            ["x = 1", "y = 2"],
        ),
        qa.Verdict.FAIL,
    ),
    "DOK Derivative(다항식).doit() 대조": (
        _rec(
            ["Derivative(x**3 - 3*x, x).doit() = 0", "x > 0", "y = x + 5"],
            "6",
            {"x": "1", "y": "6"},
            ["x = -1, x = 1", "x = 1", "y = 6"],
        ),
        qa.Verdict.PASS,
    ),
    "HD2 5차 다항식 근사 실근 대입": (
        _rec(
            ["x**5 - x - 1 = 0", "y = x + 1"],
            "2.1673039782614187",
            {"x": "1.1673039782614187", "y": "2.1673039782614187"},
            ["x = 1.1673039782614187", "y = 2.1673039782614187"],
        ),
        qa.Verdict.PASS,
    ),
    # 정당한 판정 확장(main 의 거짓 실패·판정 불가 → 다항 등식으로 증명돼 PASS)
    "DR2 중근 등식 대입": (
        _rec(
            ["(x-2)**2*(x+1) = 0", "x > 0", "y = x**2"],
            "4",
            {"x": "2", "y": "4"},
            ["x = 2", "y = 4"],
        ),
        qa.Verdict.PASS,
    ),
    "IR2 근사 √2 대입": (
        _rec(
            ["x**2 - 2 = 0", "x > 0", "y = x**2 + 1"],
            "3",
            {"x": "sqrt(2)", "y": "3"},
            ["x = 1.4142135623730951", "y = 3"],
        ),
        qa.Verdict.PASS,
    ),
    "SP1 다른 변수만의 등식 섞임": (
        _rec(
            ["a**2 - 4 = 0", "a > 0", "y = a**2 + 1", "b = 7"],
            "5",
            {"a": "2", "y": "5", "b": "7"},
            ["a = 2", "y = 5"],
        ),
        qa.Verdict.PASS,
    ),
    # 대조 — 근 선택 근거·정의 등식이 모두 있는 올바른 풀이(main 의 거짓 실패 → PASS)
    "A10 선택 뒤 대입(올바름)": (
        _rec(
            ["a**2 - 4 = 0", "a > 0", "y = a**2 + 1"],
            "5",
            {"a": "2", "y": "5"},
            ["a**2 - 4 = 0", "a = -2, a = 2", "a = 2", "y = 5"],
        ),
        qa.Verdict.PASS,
    ),
}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_review_counterexamples(name: str) -> None:
    record, expected = ADVERSARIAL[name]
    item = qa.judge_record(record)
    assert item.verdict is expected, item.reason_text()


def test_c2_domain_requires_the_full_root_set_even_with_the_right_survivor() -> None:
    """근 -2 를 빠뜨린 나열(-1, 3) — 남은 후보 3 이 정답과 같아도 근 집합이 불완전하면 판정하지 않는다.
    완전한 나열(-2, -1, 3)이면 같은 문항이 PASS 다(대조)."""
    complete = _rec(
        ["(x + 1)*(x + 2)*(x - 3) = 0", "x > 0"], "3", {"x": "3"}, ["x = -2, x = -1, x = 3"]
    )
    assert qa.judge_record(complete).checks["C2"].state is qa.CheckState.PASS

    def mutate(r: Record) -> None:
        _steps(r)[-1] = "x = -1, x = 3"

    item = qa.judge_record(_inject(complete, mutate))
    assert item.checks["C2"].code == "C2_DOMAIN_CANDIDATES_INCOMPLETE"
    assert item.verdict is qa.Verdict.UNVERIFIABLE


def test_near_duplicate_candidates_do_not_hide_an_omitted_root() -> None:
    """같은 근을 표기만 달리 두 번 적어(`-1.4142135623730951`·`-sqrt(2)`, 또는 5e-15 차이 소수) 근 √2
    를 빠뜨린 나열 — 정본 채점기는 둘을 다른 값으로 보지만 근 판정은 수치 기준이다. 완전성은 같은
    수치 기준으로 세어 '불완전'으로 잡는다(PR #1703 재검토 중2 · N4a)."""
    for duplicate in ("-1.4142135623730951", "-1.41421356237309"):
        record = _rec(
            ["x**3 - 2*x = 0", "x >= 0"], "0", {"x": "0"}, [f"x = {duplicate}, x = -sqrt(2), x = 0"]
        )
        item = qa.judge_record(record)
        assert item.checks["C2"].code == "C2_DOMAIN_CANDIDATES_INCOMPLETE", duplicate


def test_non_isolated_target_equation_blocks_the_substitution_proof() -> None:
    """`y**2 + (x - 3)**2 = 0` 은 y 만 정하는 정의(`y = f(x)`)가 아니라 x 도 묶는다 — x = 3 에서 y 가
    0 하나로 정해져도, x 를 함께 제약하는 조건이 있는 채로 증명하지 않는다(종전 FAIL 유지)."""
    record = _rec(
        ["x**2 - 9 = 0", "x > 0", "y**2 + (x - 3)**2 = 0"],
        "0",
        {"x": "3", "y": "0"},
        ["x = 3", "y = 0"],
    )
    assert qa.judge_record(record).checks["C4"].code == "C4_STEP_INCORRECT"


def test_near_double_root_answer_is_not_confirmed_by_the_conditions() -> None:
    """중근 근처 값 2.00001 은 잔차 허용치(1e-9) 안이라 Tier1 이 '근'으로 받지만, 정확 근 2 와의 대조
    (허용치 1e-9)에서는 근이 아니다 — 후보를 근으로 세지 않는다(재검토 중2)."""
    record = _rec(
        ["(x-2)**2*(x+1) = 0", "x > 0"], "2.00001", {"x": "2.00001"}, ["x = -1, x = 2.00001"]
    )
    item = qa.judge_record(record)
    assert item.checks["C2"].code == "C2_DOMAIN_CANDIDATE_NOT_ROOT"
    assert item.verdict is not qa.Verdict.PASS


def test_answer_aggregate_blocks_the_domain_filter_even_when_values_coincide() -> None:
    def mutate(r: Record) -> None:
        r["verify"]["answer_aggregate"] = "sum"

    item = qa.judge_record(_inject(_domain_roots(), mutate))
    assert item.checks["C2"].code == "C2_ROOT_CHOICE_UNSTRUCTURED"


def test_condition_mixing_the_variable_with_another_blocks_the_proof() -> None:
    """`a + y > 0` 은 a 를 y 와 함께 제약한다 — y 를 모르는 채로 "조건이 요구하는 근은 6" 이라고
    증명하지 않는다(PR #1703 재검토 MV2)."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"].append("a + y > 0")

    item = qa.judge_record(_inject(_domain_selection_step(), mutate))
    assert item.checks["C4"].code == "C4_STEP_UNVERIFIABLE"


def test_mixed_inequality_blocks_every_conclusion_including_violation() -> None:
    """`a + y > 0` 처럼 a 를 다른 변수와 묶는 조건이 있으면 근 집합·도메인을 확정하지 않는다 — 위반
    판정도 내지 않고 판정 불가로 둔다(main 도 이 선택 단계는 판정 불가였다)."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"].insert(1, "a + y > 0")
        _steps(r)[-1] = "a = -6"

    item = qa.judge_record(_inject(_domain_selection_step(), mutate))
    assert item.checks["C4"].code == "C4_STEP_UNVERIFIABLE"


def test_c2_domain_does_not_count_roots_of_a_cancelled_rational_equation() -> None:
    """`(x-2)**2*(x+1)/(x-2) = 0` 은 약분하면 근 2·-1 이지만 2 는 원문 분모를 0 으로 만드는 무연근이다.
    약분된 근 개수로 완전성을 말하지 않는다 — 도메인 판정을 하지 않고 종전 사유로 돌아간다."""
    record = _rec(["(x - 2)**2*(x + 1)/(x - 2) = 0", "x > 0"], "2", {"x": "2"}, ["x = -1, x = 2"])
    assert qa.judge_record(record).checks["C2"].code == "C2_ROOT_CHOICE_UNSTRUCTURED"


def test_implicit_domain_definition_is_not_exempted_as_a_definition() -> None:
    """`y = log(x)` 는 x > 0 이어야 y 가 있으므로 x 를 제약한다 — 정의로 면제해 smallest(-2)와 비교해
    근 선택 단계를 '틀렸다'로 내지 않는다(3차 검토 하2). 선택 단계는 판정 불가, 대입 단계에서 종전
    FAIL 이 남는다."""
    record = _rec(
        ["x**2 - 4 = 0", "y = log(x)"],
        "log(2)",
        {"x": "2", "y": "log(2)"},
        ["x = -2, x = 2", "x = 2", "y = log(2)"],
    )
    record["verify"]["answer_selection"] = "smallest"
    item = qa.judge_record(record)
    assert item.checks["C4"].detail == "전이 1·해석 단계(대입)"


def test_two_equations_for_the_variable_leave_the_root_set_undetermined() -> None:
    """그 변수의 등식이 둘이면(`3a² = 108`·`a² = 49`) 근의 집합을 하나로 정하지 않는다."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"].append("a**2 = 49")

    item = qa.judge_record(_inject(_domain_selection_step(), mutate))
    assert item.checks["C4"].code == "C4_STEP_UNVERIFIABLE"


def test_c2_uncertified_domain_is_not_used_to_pick_a_root() -> None:
    """`log(x) >= 1` 은 허용 목록 다항 부등식이 아니다 — 그 도메인으로 근을 고르지 않고 종전 사유로."""
    record = _rec(["x**2 - 1 = 0", "log(x) >= 1"], "1", {"x": "1"}, ["x = -1, x = 1"])
    item = qa.judge_record(record)
    assert item.checks["C2"].code == "C2_ROOT_CHOICE_UNSTRUCTURED"


def test_transitions_already_correct_are_not_reinterpreted() -> None:
    """동치 판정이 correct 인 전이(`x = 3 → x = 3`)는 해석 판정으로 다시 보지 않는다."""
    record = _rec(["x**2 = 9", "x < 0"], "3", {"x": "3"}, ["x = 3", "x = 3"])
    assert qa.judge_record(record).checks["C4"].state is qa.CheckState.PASS


# ──────────────────────────────────────────────────────────────────────────
# 실 코퍼스 레코드 — 합성 대조군만으로는 생성기 실제 모양을 밟는지 모른다
# ──────────────────────────────────────────────────────────────────────────
def _iter_bank(path: Path) -> list[Record]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _real_domain_root_choice() -> Record | None:
    """종전 C2_ROOT_CHOICE_UNSTRUCTURED 였고 지금 도메인 제약으로 PASS 인 실 레코드(02-01 등)."""
    for record in _iter_bank(P3_DIFF_BANK):
        verify = record.get("verify") or {}
        steps = verify.get("solution_steps") or []
        conditions = verify.get("conditions")
        if (
            record.get("review_status") == "approved"
            and isinstance(conditions, list)
            and len(conditions) >= 2
            and steps
            and "," in steps[-1]
            and not verify.get("answer_selection")
            and verify.get("answer_map")
            and qa.judge_record(record).verdict is qa.Verdict.PASS
        ):
            return record
    return None


def _real_substitution_candidate() -> Record | None:
    """마지막 단계가 x 후보 나열이고 정답 변수가 y 이며 조건에 x 도메인이 있는 실 레코드(극값의 값형)."""
    for path in (P3_DIFF_BANK, P3_FILL_BANK):
        for record in _iter_bank(path):
            item = qa.judge_record(record)
            if record.get("review_status") != "approved":
                continue
            if item.checks["C2"].code != "C2_FINAL_STEP_VAR_NOT_ANSWER_VAR":
                continue
            conditions = (record.get("verify") or {}).get("conditions") or []
            if any(c.strip().startswith("x >") for c in conditions):
                return record
    return None


@pytest.fixture(scope="module")
def real_domain_record() -> Record:
    record = _real_domain_root_choice()
    assert record is not None, "도메인 근 선택 실 레코드를 못 찾았다 — 공허 통과 방지로 실패시킨다"
    return record


@pytest.fixture(scope="module")
def real_substitution_record() -> Record:
    record = _real_substitution_candidate()
    assert record is not None, "대입형 실 레코드를 못 찾았다 — 공허 통과 방지로 실패시킨다"
    return record


def _other_candidate(record: Record) -> str:
    parsed = qa._final_assignments(_steps(record)[-1])
    assert parsed is not None
    var, values = parsed
    others = [v for v in values if qa._same(v, record["answer"]) is not qa._Same.SAME]
    assert others, "정답 아닌 후보가 없다 — 주입이 성립하지 않는다"
    return others[0]


def test_real_record_wrong_root_selection_turns_red(real_domain_record: Record) -> None:
    other = _other_candidate(real_domain_record)
    var = next(iter(real_domain_record["verify"]["answer_map"]))

    def mutate(r: Record) -> None:
        r["answer"] = other
        r["verify"]["answer_map"] = {var: other}

    item = qa.judge_record(_inject(real_domain_record, mutate))
    assert item.verdict is qa.Verdict.FAIL
    assert item.checks["C2"].code == "C2_DOMAIN_PICK_MISMATCH"


def test_real_record_selection_step_is_judged(real_domain_record: Record) -> None:
    var = next(iter(real_domain_record["verify"]["answer_map"]))
    right = _inject(real_domain_record, lambda r: _steps(r).append(f"{var} = {r['answer']}"))
    assert qa.judge_record(right).verdict is qa.Verdict.PASS

    other = _other_candidate(real_domain_record)
    wrong = _inject(real_domain_record, lambda r: _steps(r).append(f"{var} = {other}"))
    item = qa.judge_record(wrong)
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"
    assert item.verdict is qa.Verdict.FAIL


def test_real_record_substitution_step_is_judged(real_substitution_record: Record) -> None:
    amap = real_substitution_record["verify"]["answer_map"]
    target = next(k for k in amap if k != "x")
    right = _inject(
        real_substitution_record, lambda r: _steps(r).append(f"{target} = {amap[target]}")
    )
    assert qa.judge_record(right).verdict is qa.Verdict.PASS

    wrong = _inject(real_substitution_record, lambda r: _steps(r).append(f"{target} = 987654321"))
    item = qa.judge_record(wrong)
    assert item.checks["C4"].code == "C4_STEP_INCORRECT"
    assert item.verdict is qa.Verdict.FAIL
