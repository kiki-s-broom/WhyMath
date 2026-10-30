"""[12미적Ⅰ-02-02] 미분가능성과 연속성 생성기 — 독립 경로 재계산·양성 예 균형·가드 (P3-05 4단계).

정답의 단일 권위는 생성기의 분기 식 미분이다. 이 테스트는 그 경로를 믿지 않고 **학생이 보는 문면**에서
함수를 다시 읽어 **정의(좌·우 극한)로** 정답을 재계산한다 — 문면과 정답이 어긋난 문항(꺾임점 오기·
분기 부호 오기·상수 a 오기)은 여기서 걸린다.
"""

from __future__ import annotations

import dataclasses
import re
from collections import Counter

import pytest
import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from whymath_backend.l3.equivalent import p3_diff_differentiability_skeleton_generator as mod
from whymath_backend.l3.equivalent.p3_diff_differentiability_skeleton_generator import (
    P3DiffDifferentiabilityGenerator as Gen,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import SLOT_IDS, skeleton_of

_X, _H, _A = sympy.symbols("x h a")

_SLOTS = ("representative", "basic", "applied", "diagnostic", "mastery_check")
_TRANSFORMS = (*standard_transformations, implicit_multiplication_application, convert_xor)


def _expr(text: str) -> sympy.Expr:
    """학생 표기 식('|x - 2|(x + 1) - x^2')을 SymPy 로 읽는다 — `|…|` 는 `Abs(…)` 로."""
    s = re.sub(r"\|([^|]+)\|", r"Abs(\1)", text)
    return parse_expr(
        s, local_dict={"x": _X, "a": _A, "Abs": sympy.Abs}, transformations=_TRANSFORMS
    )


def _function(question: str) -> sympy.Expr:
    cleaned = question.replace(" (a는 상수)", "")
    m = re.search(r"f\(x\) = ([^가-힣]+?)(?:에 대하여| ?가 x|$)", cleaned)
    assert m, question
    return _expr(m.group(1).strip())


def _limit(f: sympy.Expr, point: int, direction: str) -> sympy.Expr:
    """정의: `lim_{h→0±} (f(point + h) - f(point)) / h`."""
    quotient = (f.subs(_X, point + _H) - f.subs(_X, point)) / _H
    return sympy.limit(sympy.simplify(quotient), _H, 0, direction)


def _solve_by_definition(item) -> str:  # type: ignore[no-untyped-def]
    q = item.question_text
    f = _function(q)
    if item.slot == "representative":
        point = int(re.search(r"x = (-?\d+)에서의 우미분계수", q).group(1))  # type: ignore[union-attr]
        return str(_limit(f, point, "+") - _limit(f, point, "-"))
    if item.slot == "basic":
        point = int(re.search(r"x = (-?\d+)에서의", q).group(1))  # type: ignore[union-attr]
        side = "+" if "우미분계수" in q else "-"
        return str(_limit(f, point, side))
    if item.slot == "applied":
        point = int(re.search(r"x = (-?\d+)에서 미분가능", q).group(1))  # type: ignore[union-attr]
        eq = sympy.Eq(_limit(f, point, "+"), _limit(f, point, "-"))
        return str(sympy.solve(eq, _A)[0])
    if item.slot == "diagnostic":
        point = int(re.search(r"f'\((-?\d+)\)", q).group(1))  # type: ignore[union-attr]
        right, left = _limit(f, point, "+"), _limit(f, point, "-")
        assert right == left, f"꺾이는 함수를 미분계수로 물었다: {q}"
        return str(right)
    m = re.search(r"x = (-?\d+)에서 미분가능할 때, f'\((-?\d+)\)", q)
    assert m, q
    point, query = int(m.group(1)), int(m.group(2))
    eq = sympy.Eq(_limit(f, point, "+"), _limit(f, point, "-"))
    a_val = sympy.solve(eq, _A)[0]
    g = f.subs(_A, a_val)
    return str(_limit(g, query, "+"))


def _resolved_branch(f: sympy.Expr, x0: sympy.Rational) -> sympy.Expr:
    """`x0` 근방에서 절댓값을 벗긴 다항식(각 `Abs(u)` 는 u(x0) 의 부호로 ±u)."""
    sub = {t: (t.args[0] if t.args[0].subs(_X, x0) > 0 else -t.args[0]) for t in f.atoms(sympy.Abs)}
    return sympy.expand(f.xreplace(sub))


_CLAIM = re.compile(r"x ([<>]) (-?\d+)에서 f(\(x\)|'\(x\)) = ([^가-힣,]+?)(?=이|,)")


class TestExplanationIsFaithfulToTheStatement:
    """해설이 보여 주는 분기 식·도함수 식이 문면의 함수와 일치한다 — 답이 맞아도 해설의 식이 틀리면 학생을 오도한다."""

    @pytest.mark.parametrize("slot", _SLOTS)
    def test_every_printed_branch_and_derivative_matches_the_statement(self, slot: str) -> None:
        checked = 0
        for item in Gen.items(slot):
            f = _function(item.question_text)
            a_match = re.search(r"a = (-?\d+)이다", item.explanation)
            for sign, point, kind, text in _CLAIM.findall(item.explanation):
                x0 = sympy.Integer(int(point)) + (
                    sympy.Rational(1, 3) if sign == ">" else -sympy.Rational(1, 3)
                )
                branch = _resolved_branch(f, x0)
                if kind == "(x)" and a_match:  # 풀이가 a 를 정한 뒤의 식
                    branch = branch.subs(_A, int(a_match.group(1)))
                expected = branch if kind == "(x)" else sympy.diff(branch, _X)
                printed = _expr(text.strip())
                assert sympy.expand(printed - expected) == 0, (item.question_text, text, expected)
                checked += 1
        assert checked >= 12, checked

    def test_the_faithfulness_check_would_notice_a_wrong_printed_formula(self) -> None:
        """대조군 — 해설의 식 하나를 어긋나게 하면 이 검사가 불일치를 낸다(변별력)."""
        item = Gen.items("basic")[0]
        f = _function(item.question_text)
        sign, point, kind, text = _CLAIM.findall(item.explanation)[0]
        x0 = sympy.Integer(int(point)) + (
            sympy.Rational(1, 3) if sign == ">" else -sympy.Rational(1, 3)
        )
        expected = _resolved_branch(f, x0)
        assert sympy.expand(_expr(text.strip()) - expected) == 0
        assert sympy.expand(_expr(text.strip()) + 1 - expected) != 0


class TestDeclaration:
    def test_generator_declares_exactly_the_five_empty_cells(self) -> None:
        assert Gen.slots == _SLOTS
        assert set(Gen.slot_difficulty) >= set(_SLOTS)

    @pytest.mark.parametrize("slot", sorted(set(SLOT_IDS) - set(_SLOTS)))
    def test_a_slot_it_does_not_own_is_an_empty_generator_not_an_error(self, slot: str) -> None:
        assert Gen.items(slot) == ()

    @pytest.mark.parametrize("slot", _SLOTS)
    def test_twelve_items_per_owned_slot(self, slot: str) -> None:
        assert len(Gen.items(slot)) == 12


class TestIndependentRecomputation:
    @pytest.mark.parametrize("slot", _SLOTS)
    def test_every_answer_matches_a_recomputation_from_the_student_text(self, slot: str) -> None:
        wrong = [
            (i.frame_id, i.question_text, i.answer_text, _solve_by_definition(i))
            for i in Gen.items(slot)
            if _solve_by_definition(i) != i.answer_text
        ]
        assert wrong == [], wrong[:3]

    def test_the_recomputation_would_notice_a_wrong_answer(self) -> None:
        """대조군 — 정답을 1 어긋나게 하면 이 검사가 실제로 불일치를 낸다(변별력)."""
        item = Gen.items("basic")[0]
        assert _solve_by_definition(item) == item.answer_text
        assert _solve_by_definition(item) != str(int(item.answer_text) + 1)


def _solve_conditions(item) -> str:  # type: ignore[no-untyped-def]
    """검산 재료(`conditions`)만으로 미지수를 풀어 정답을 다시 구한다 — 배치의 Tier1 과 별개의 경로."""
    lhs, rhs = str(item.conditions).split(" = ")
    local = {"x": _X, "a": _A, "y": sympy.Symbol("y"), "Derivative": sympy.Derivative}
    ((name, _value),) = item.answer_map
    unknown = sympy.Symbol(name)
    eq = sympy.Eq(sympy.sympify(lhs, locals=local).doit(), sympy.sympify(rhs, locals=local).doit())
    (solution,) = sympy.solve(eq, unknown)
    return str(solution)


class TestConditionsEncodeTheAnswer:
    @pytest.mark.parametrize("slot", _SLOTS)
    def test_solving_the_conditions_gives_the_stated_answer(self, slot: str) -> None:
        wrong = [
            (i.frame_id, i.answer_text, _solve_conditions(i))
            for i in Gen.items(slot)
            if _solve_conditions(i) != i.answer_text
        ]
        assert wrong == [], wrong[:3]

    def test_the_check_would_notice_a_flipped_sign(self) -> None:
        """대조군 — 대표 조건의 `R - (L)` 을 `R + (L)` 로 바꾸면 정답이 달라져 이 검사가 불일치를 낸다."""
        item = next(i for i in Gen.items("representative") if i.answer_text != "0")
        assert _solve_conditions(item) == item.answer_text
        flipped = dataclasses.replace(
            item, conditions=str(item.conditions).replace(" - (", " + (", 1)
        )
        assert _solve_conditions(flipped) != flipped.answer_text


class TestPositiveExamples:
    """기존 24건은 정답이 전부 0 — '절댓값이면 0'이라는 규칙 하나로 풀렸다. 이 생성기는 그 규칙을 깬다."""

    def test_representative_asks_a_nonzero_gap_because_a_zero_gap_collides_with_the_value_path(
        self,
    ) -> None:
        """대표 틀의 답 '우 - 좌 미분계수'는 0이면 우회로 판정기(T-function-value-path)와 겹쳐 쓸 수 없다.

        (좌·우 분기의 차는 연속성 때문에 x = p 에서 함숫값이 0이라, 함숫값을 대입해도 0이 나온다.)
        미분가능한 양성 예는 진단·응용·숙련도 칸이 맡는다.
        """
        answers = [i.answer_text for i in Gen.items("representative")]
        assert all(a != "0" for a in answers), answers
        assert len(set(answers)) >= 4, answers

    def test_differentiable_positives_live_in_the_other_four_cells(self) -> None:
        """진단은 절댓값이 있어도 미분가능한 함수, 응용·숙련도는 '미분가능할 때'를 전제로 한다."""
        assert all("|" in i.question_text for i in Gen.items("diagnostic"))
        for slot in ("applied", "mastery_check"):
            assert all("미분가능할 때" in i.question_text for i in Gen.items(slot))

    def test_representative_explanation_never_claims_differentiability(self) -> None:
        """대표 문항은 전부 꺾이는 함수다 — 해설이 '미분가능하다'고 말하면 거짓이다."""
        for i in Gen.items("representative"):
            assert "미분가능" not in i.explanation, i.explanation

    def test_diagnostic_functions_contain_an_absolute_value_yet_are_differentiable(self) -> None:
        for i in Gen.items("diagnostic"):
            assert "|" in i.question_text, i.question_text
            assert "미분가능하고" in i.explanation, i.explanation

    def test_applied_answers_are_never_zero(self) -> None:
        """a = 0 이면 꺾임이 '상수가 없어서' 사라지는 퇴화다 — 응용 문항은 0이 아닌 a 만 묻는다."""
        assert all(i.answer_text != "0" for i in Gen.items("applied"))


class TestSlotShape:
    @pytest.mark.parametrize("slot", _SLOTS)
    def test_at_least_three_frames_and_eight_distinct_skeletons(self, slot: str) -> None:
        items = Gen.items(slot)
        assert len({i.frame_id for i in items}) >= 3
        assert len({skeleton_of(i.question_text) for i in items}) >= 8

    def test_problem_types_are_honest(self) -> None:
        for slot in ("representative", "basic", "diagnostic"):
            assert {i.problem_type_code for i in Gen.items(slot)} == {"ptype.evaluate-expression"}
        for slot in ("applied", "mastery_check"):
            assert {i.problem_type_code for i in Gen.items(slot)} == {"ptype.solve-for-unknown"}

    def test_no_misconception_is_linked_because_the_trigger_cell_is_already_filled(self) -> None:
        assert all(not i.misconception_ids for s in _SLOTS for i in Gen.items(s))

    def test_basic_frames_cover_both_sides(self) -> None:
        by_frame = Counter(i.frame_id for i in Gen.items("basic"))
        assert any("right" in f for f in by_frame) and any("left" in f for f in by_frame)

    def test_kink_points_are_not_all_on_one_side(self) -> None:
        for slot in ("representative", "basic", "diagnostic"):
            points = {
                int(m.group(1) or m.group(2))
                for i in Gen.items(slot)
                if (m := re.search(r"x = (-?\d+)에서|f'\((-?\d+)\)", i.question_text))
            }
            assert any(p > 0 for p in points) and any(p < 0 for p in points), (slot, points)

    def test_no_explanation_prints_a_constant_slope_without_a_formula(self) -> None:
        """해설은 x를 담은 도함수 식을 보인다 — 상수 도함수 매개변수는 건너뛴다(E-derivative)."""
        for slot in ("representative", "basic", "diagnostic"):
            for i in Gen.items(slot):
                assert re.search(r"f'\(x\) = [^.]*x", i.explanation), i.explanation


class TestGuards:
    def test_a_non_kink_absolute_value_is_resolved_by_its_sign_on_both_sides(self) -> None:
        """|x - 5| 는 x = 2 둘레에서 늘 양수가 아니라 음수(x - 5 < 0) — 두 분기가 같은 식 5 - x 가 된다."""
        left, right = mod._branches(sympy.Abs(_X - 5), 2)
        assert left == right == sympy.expand(5 - _X)
        left, right = mod._branches(sympy.Abs(_X - 5) + sympy.Abs(_X - 2), 2)
        assert right - left == 2 * (_X - 2)  # 꺾이는 항만 분기 차이를 만든다

    def test_branches_of_a_square_pick_the_non_negative_side(self) -> None:
        left, right = mod._branches(sympy.Abs((_X - 2) ** 2), 2)
        assert left == right == sympy.expand((_X - 2) ** 2)
        left, right = mod._branches(-sympy.Abs((_X - 2) ** 2) * -1, 2)
        assert left == right

    def test_branches_follow_the_sign_of_the_slope(self) -> None:
        u = _X**2 - 4  # u(-2) = 0, u'(-2) = -4 < 0 — 오른쪽(x > -2)에서 u < 0 이라 |u| = -u
        left, right = mod._branches(sympy.Abs(u), -2)
        assert right == sympy.expand(-u) and left == sympy.expand(u)
        left, right = mod._branches(sympy.Abs(u), 2)  # u'(2) = 4 > 0 — 반대
        assert right == sympy.expand(u) and left == sympy.expand(-u)

    def test_unknown_constant_rejects_a_wrong_expected_value(self) -> None:
        with pytest.raises(ValueError, match="유일하지 않다"):
            mod._unknown_constant(
                slot="applied",
                frame_id="t",
                f_text="|x - 2|(x + a)",
                f_expr=sympy.Abs(_X - 2) * (_X + _A),
                point=2,
                a_true=5,
            )

    def test_smooth_coefficient_rejects_a_kinked_function(self) -> None:
        with pytest.raises(ValueError, match="꺾이는 함수"):
            mod._smooth_coefficient(
                frame_id="t",
                f_text="|x - 2| + x^2",
                f_expr=sympy.Abs(_X - 2) + _X**2,
                point=2,
                why="",
            )

    def test_then_derivative_rejects_a_wrong_expected_value(self) -> None:
        with pytest.raises(ValueError, match="유일하지 않다"):
            mod._then_derivative(
                frame_id="t",
                f_text="|x - 2|(x + a)",
                f_expr=sympy.Abs(_X - 2) * (_X + _A),
                point=2,
                a_true=1,
                query=3,
            )

    def test_constant_slope_detects_degree_zero_derivative(self) -> None:
        assert mod._constant_slope(_X**2 - _X**2 + 3 * _X)
        assert not mod._constant_slope(_X**2)

    def test_one_constant_branch_is_enough_to_skip_a_two_branch_item(self) -> None:
        """|x^2 - 4| - x^2 은 우분기가 상수(-4)·좌분기는 아니다 — 한쪽만 상수여도 해설에 식이 없다."""
        f = sympy.Abs(_X**2 - 4) - _X**2
        assert mod._diff_of_one_sided(frame_id="t", f_text="x", f_expr=f, point=2) is None
        assert mod._smooth_coefficient(frame_id="t", f_text="x", f_expr=f, point=2, why="") is None

    def test_builders_return_none_for_a_constant_slope_branch(self) -> None:
        """우분기 4x - 9 → 도함수 4(상수): 해설에 도함수 식을 보일 수 없으므로 문항으로 만들지 않는다."""
        f = sympy.Abs(_X - 3) * (_X + 2) - _X**2 + 5 * _X - 3
        assert mod._one_sided(frame_id="t", f_text="x", f_expr=f, point=3, side="right") is None

    @pytest.mark.parametrize(
        ("text", "expected"),
        [("2x - 3", "2x - 3"), ("-x^2 + a", "-x^2 + a"), ("2ax - 3", "2ax - 3"), ("0", "0")],
    )
    def test_render_prints_student_notation(self, text: str, expected: str) -> None:
        assert mod._render(_expr(text)) == expected

    def test_mix_pairs_every_base_with_every_extra_and_cycles_the_leading_ones(self) -> None:
        base = ((1,), (2,), (3,))
        mixed = mod._mix(base, (10, 20, 30))
        assert len(mixed) == 9 and len(set(mixed)) == 9  # 전 쌍이 한 번씩
        assert mixed[:3] == ((1, 10), (2, 20), (3, 30))  # 앞 후보가 틀 고유 값을 돌려 쓴다
        assert mixed[3:6] == ((1, 20), (2, 30), (3, 10))

    def test_mix_flattens_tuple_extras(self) -> None:
        assert mod._mix(((1,), (2,)), ((7, 8), (9, 6))) == (
            (1, 7, 8),
            (2, 9, 6),
            (1, 9, 6),
            (2, 7, 8),
        )

    def test_shift_and_join_never_print_a_double_sign(self) -> None:
        assert mod._shift(-2) == "x + 2" and mod._shift(0) == "x" and mod._shift(3) == "x - 3"
        assert mod._join(["a", "-b", "c"]) == "a - b + c"
