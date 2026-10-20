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


def test_selection_step_without_a_rule_is_unverifiable_not_pass() -> None:
    def mutate(r: Record) -> None:
        r["verify"]["conditions"] = r["verify"]["conditions"][:1]

    item = qa.judge_record(_inject(_domain_selection_step(), mutate))
    assert item.checks["C4"].code == "C4_STEP_UNVERIFIABLE"
    assert item.verdict is qa.Verdict.UNVERIFIABLE


def test_selection_rule_is_not_applied_to_candidates_of_another_equation() -> None:
    """후보가 조건 등식의 근이 아니면(임계점 나열 등) answer_selection 을 후보에 적용하지 않는다."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"] = "x**2 - 12*x + 32 = 0"  # 근 4, 8 — 후보 -2, 4 와 다른 등식

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
        r["verify"]["conditions"] = r["verify"]["conditions"][:2]

    item = qa.judge_record(_inject(_substitution(), mutate))
    assert item.checks["C4"].detail == "1/4전이·해석 단계 1"


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


def test_substitution_after_candidates_without_a_rule_is_unverifiable() -> None:
    """후보 둘 중 어느 x 인지 조건이 말하지 않으면, 결과값에 맞는 후보를 거꾸로 찾지 않는다."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"] = r["verify"]["conditions"][:2]

    item = qa.judge_record(_inject(_substitution(), mutate))
    assert item.checks["C4"].code == "C4_STEP_UNVERIFIABLE"
    assert item.verdict is qa.Verdict.UNVERIFIABLE


def test_substitution_needs_a_definition_without_borrowed_parameters() -> None:
    """정의 등식에 다른 매개변수(a)가 섞이면 그 값을 정답 기록에서 빌려 와야 하므로 판정하지 않는다."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"][1] = "y = 2*x**3 + a*x**2 - 18*x + 58"
        r["verify"]["answer_map"]["a"] = "-6"

    item = qa.judge_record(_inject(_substitution(), mutate))
    assert item.checks["C4"].code == "C4_STEP_UNVERIFIABLE"


def test_parameterized_definition_is_ignored_when_a_pure_one_decides() -> None:
    """정의 등식이 둘(매개변수 섞인 것 + 순수 {x, y})이면 순수한 것만 쓴다 — 매개변수 등식을 섞어
    '판정 불가'로 끌어내리지도, 그 값을 빌려 오지도 않는다."""

    def mutate(r: Record) -> None:
        r["verify"]["conditions"].append("y = 2*x**3 + b*x**2 - 18*x + 58")

    item = qa.judge_record(_inject(_substitution(), mutate))
    assert item.checks["C4"].state is qa.CheckState.PASS


def test_substitution_without_a_defining_condition_is_unverifiable() -> None:
    def mutate(r: Record) -> None:
        del r["verify"]["conditions"][1]

    item = qa.judge_record(_inject(_substitution(), mutate))
    assert item.checks["C4"].code == "C4_STEP_UNVERIFIABLE"


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
