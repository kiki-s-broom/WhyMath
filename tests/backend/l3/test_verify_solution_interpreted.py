"""P3-76 — 해석 단계(근 선택·대입) 공용 판정 `verify_solution_interpreted`.

세 게이트(Solution QA C4 · 수용 게이트 Tier2 · 야간 상시 재검증)가 이 함수 하나를 공유한다.
여기서는 ①판정 의미(성립 → correct · 불성립 → incorrect · 판정 불가 → 종전 유지) ②단조 규칙
(이웃 동치가 incorrect 였던 전이는 성립 증명일 때만 바뀐다) ③집계 불변식 ④세 호출부가 실제로 이
함수를 쓰고 판정 로직을 따로 갖지 않는지(복제 금지 — AST)를 본다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from whymath_backend.l3.verify_solution import (
    INTERPRETIVE_SELECTION,
    INTERPRETIVE_SUBSTITUTION,
    ROOT_PROVEN,
    ROOT_UNKNOWN,
    ROOT_WRONG,
    judge_root_value,
    verify_solution,
    verify_solution_interpreted,
)
from whymath_backend.l3.verify_step import VerifyStepState

_ROOT = Path(__file__).resolve().parents[3]
_PKG = _ROOT / "src" / "backend" / "whymath_backend"

# P3-62 재개 판정의 GRAPH-SHAPE 실 레코드(wm-p3-diff-graphshape-e6551214a538)를 규칙 (가) 꼴로
# 바꾼 조건 — a 결정 등식 · a 를 대입한 도함수 등식 · 선택 근거(극소 f'' > 0) · 정의 등식.
CONDITIONS = [
    "Derivative(2*x**3 + a*x**2 - 72*x + 6, x).doit().subs(x, 4) = 0",
    "Derivative(2*x**3 - 3*x**2 - 72*x + 6, x).doit() = 0",
    "12*x - 6 > 0",
    "y = 2*x**3 - 3*x**2 - 72*x + 6",
]
BASE_STEPS = [
    "Derivative(2*x**3 + (-3)*x**2 - 72*x + 6, x).doit() = 0",
    "6*x**2 - 6*x - 72 = 0",
    "6*(x - 4)*(x + 3) = 0",
    "x = -3, x = 4",
]


def _states(steps: list[str], conditions: list[str], selection: str | None = None) -> list[str]:
    result = verify_solution_interpreted(
        steps, conditions=conditions, answer_selection=selection
    ).result
    return [step.state.value for step in result.steps]


class TestJudgement:
    def test_rule_ga_selection_and_substitution_are_proven(self) -> None:
        out = verify_solution_interpreted(BASE_STEPS + ["x = 4", "y = -202"], conditions=CONDITIONS)
        assert out.result.n_incorrect == 0 and out.result.n_unverifiable == 0
        assert out.result.n_correct == 5
        assert dict(out.interpretive) == {3: INTERPRETIVE_SELECTION, 4: INTERPRETIVE_SUBSTITUTION}

    def test_plain_verify_solution_does_not_prove_them(self) -> None:
        """대조 — 이웃 동치만으로는 선택은 판정 불가, 변수 전환은 incorrect 다(종전 판정)."""
        plain = verify_solution(BASE_STEPS + ["x = 4", "y = -202"])
        assert plain.steps[3].state == VerifyStepState.unverifiable
        assert plain.steps[4].state == VerifyStepState.incorrect

    def test_wrong_root_selection_is_incorrect(self) -> None:
        states = _states(BASE_STEPS + ["x = -3", "y = 141"], CONDITIONS)
        assert states[3] == "incorrect"  # -3 은 근이지만 12x - 6 > 0 을 어긴다

    def test_wrong_substituted_value_is_incorrect(self) -> None:
        states = _states(BASE_STEPS + ["x = 4", "y = -200"], CONDITIONS)
        assert states[3] == "correct" and states[4] == "incorrect"

    @pytest.mark.parametrize(
        "conditions",
        [
            [c for c in CONDITIONS if c != "12*x - 6 > 0"],  # 선택 근거 없음
            [c for c in CONDITIONS if not c.startswith("y =")],  # 정의 등식 없음
            [*CONDITIONS[:3], "y = 2*x**3 - 3*x**2 - 72*x + 6 + 0*a + log(x)"],  # 허용 목록 밖 정의
        ],
    )
    def test_monotonic_rule_keeps_incorrect_without_proof(self, conditions: list[str]) -> None:
        """이웃 동치가 incorrect 를 낸 변수 전환은 증명 불가면 incorrect 그대로다(단조 규칙)."""
        out = verify_solution_interpreted(BASE_STEPS + ["x = 4", "y = -202"], conditions=conditions)
        assert out.result.steps[4].state == VerifyStepState.incorrect
        assert out.result.first_incorrect_index is not None
        assert 4 in out.interpretive  # 해석 단계 모양으로는 봤다(사람 검수 목록용)

    def test_selection_without_basis_stays_unverifiable(self) -> None:
        conditions = [c for c in CONDITIONS if c != "12*x - 6 > 0"]
        assert _states(BASE_STEPS + ["x = 4"], conditions)[3] == "unverifiable"

    def test_selection_rule_from_structure(self) -> None:
        conditions = [c for c in CONDITIONS if c != "12*x - 6 > 0"]
        assert _states(BASE_STEPS + ["x = 4"], conditions, "largest")[3] == "correct"
        assert _states(BASE_STEPS + ["x = 4"], conditions, "smallest")[3] == "incorrect"

    def test_correct_transitions_are_not_rejudged(self) -> None:
        steps = BASE_STEPS + ["x = 4", "y = -202"]
        plain = verify_solution(steps)
        out = verify_solution_interpreted(steps, conditions=CONDITIONS)
        for index in (0, 1, 2):
            assert out.result.steps[index] == plain.steps[index]
            assert index not in out.interpretive
        # 해석 단계 모양이어도 이웃 동치가 이미 correct 면 다시 보지 않는다(기록에도 남기지 않음).
        restated = verify_solution_interpreted(
            BASE_STEPS + ["x = 4", "x = 4"], conditions=CONDITIONS
        )
        assert restated.result.steps[4].state == VerifyStepState.correct
        assert 4 not in restated.interpretive and 3 in restated.interpretive

    def test_unparsable_or_missing_conditions_change_nothing(self) -> None:
        steps = BASE_STEPS + ["x = 4", "y = -202"]
        plain = verify_solution(steps)
        for conditions in (None, [], ["((("], "((("):
            out = verify_solution_interpreted(steps, conditions=conditions)
            assert out.result == plain

    def test_root_value_judgement(self) -> None:
        assert judge_root_value(CONDITIONS, None, "x", "4") == ROOT_PROVEN
        assert judge_root_value(CONDITIONS, None, "x", "-3") == ROOT_WRONG
        assert judge_root_value(CONDITIONS, None, "x", "5") == ROOT_UNKNOWN  # 근이 아니다
        # 답(answer_map)을 넘기는 자리가 없다 — 선택은 조건에서만 계산된다(P3-24 B3 단서).


class TestAggregateInvariants:
    def test_counts_and_reason_codes_stay_consistent(self) -> None:
        conditions = [c for c in CONDITIONS if c != "12*x - 6 > 0"]
        for steps in (
            BASE_STEPS + ["x = 4", "y = -202"],
            BASE_STEPS + ["x = 4"],
            BASE_STEPS + ["x = -3", "y = 141"],
        ):
            for conds in (CONDITIONS, conditions):
                result = verify_solution_interpreted(steps, conditions=conds).result
                assert result.n_correct + result.n_incorrect + result.n_unverifiable == (
                    result.n_transitions
                )
                assert sum(result.unverifiable_by_reason.values()) == result.n_unverifiable
                assert result.has_incorrect is (result.first_incorrect_index is not None)
                for step in result.steps:
                    if step.state == VerifyStepState.unverifiable:
                        assert step.reason_code is not None
                    else:
                        assert step.evidence_weight == 1.0

    def test_step_types_length_contract_is_kept(self) -> None:
        with pytest.raises(ValueError):
            verify_solution_interpreted(BASE_STEPS, [None], conditions=CONDITIONS)


# ──────────────────────────────────────────────────────────────────────────
# 공용 구현 거버넌스 — 세 호출부가 이 함수를 쓰고, 판정 로직을 따로 두지 않는다(복제 금지)
# ──────────────────────────────────────────────────────────────────────────
_CALLERS = {
    "l3/equivalent/acceptance.py": "_evaluate_verification",
    "harness/corpus_reverify.py": "_reverify_one",
    "harness/solution_qa.py": "_check_c4",
}
# 해석 단계 판정의 구현 이름 — 공용 모듈 밖에서 다시 정의되면 사본이다.
_JUDGE_NAMES = frozenset(
    {
        "_judge_value",
        "judge_root_value",
        "_judge_selection",
        "_judge_substitution",
        "_interpretive_step",
        "interpretive_step",
        "_defines_other_variable",
        "_numeric_assignments",
    }
)


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(found) == 1, f"{name} 을 찾지 못함 — 이 검사는 아무것도 보지 못한다"
    return found[0]


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            if isinstance(call.func, ast.Name):
                names.add(call.func.id)
            elif isinstance(call.func, ast.Attribute):
                names.add(call.func.attr)
    return names


@pytest.mark.parametrize(("relpath", "function"), sorted(_CALLERS.items()))
def test_each_gate_judges_steps_through_the_shared_function(relpath: str, function: str) -> None:
    tree = ast.parse((_PKG / relpath).read_text(encoding="utf-8"))
    called = _called_names(_function(tree, function))
    assert "verify_solution_interpreted" in called
    # 이웃 동치만 보는 옛 호출이 같은 함수 안에 남아 있으면 두 판정이 갈린다.
    assert "verify_solution" not in called


@pytest.mark.parametrize("relpath", sorted(_CALLERS))
def test_no_gate_keeps_its_own_copy_of_the_judgement(relpath: str) -> None:
    tree = ast.parse((_PKG / relpath).read_text(encoding="utf-8"))
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert not (defined & _JUDGE_NAMES), defined & _JUDGE_NAMES
