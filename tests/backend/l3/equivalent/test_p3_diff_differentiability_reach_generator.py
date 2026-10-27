"""[12미적Ⅰ-02-02] 스킬 도달 생성기(P3-65) — 문면에서 정의로 재계산 · 유형 정직성 · 변별력 · 풀이 단계.

정답의 단일 권위는 생성기의 분기 다항식 미분이고, 수용 게이트 Tier1이 차분몫 극한으로 다시 본다.
이 테스트는 둘 다 믿지 않고 **학생이 보는 문면**에서 함수를 다시 읽어 **정의(차분몫의 좌·우 극한)로**
정답을 재계산한다 — 문면과 정답이 어긋난 문항(항 부호·꺾임점·계수 오기)은 여기서 걸린다.
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

from whymath_backend.l1.standards import phase3_scope as ps
from whymath_backend.l3.equivalent import p3_diff_differentiability_skeleton_generator as mod
from whymath_backend.l3.equivalent.p3_diff_differentiability_skeleton_generator import (
    P3DiffDifferentiabilityReachGenerator as Gen,
)
from whymath_backend.l3.equivalent.p3_diff_differentiability_skeleton_generator import (
    ReachDiffItem,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import skeleton_of, steps_of
from whymath_backend.l3.equivalent.p3_diff_solution_steps import verified_expression_chain

_X, _H = sympy.symbols("x h")
_SLOTS = ("representative", "basic", "applied", "diagnostic", "mastery_check")
_TRANSFORMS = (*standard_transformations, implicit_multiplication_application, convert_xor)
_COUNT = "ptype.count-solutions"
_CLAIM = "ptype.verify-claim"


def _items() -> list[ReachDiffItem]:
    out: list[ReachDiffItem] = []
    for slot in _SLOTS:
        for item in Gen.items(slot):
            assert isinstance(item, ReachDiffItem)
            out.append(item)
    return out


def _expr(text: str) -> sympy.Expr:
    """학생 표기 식('|x - 2|(x + 1) - x^2')을 SymPy로 읽는다 — `|…|`는 `Abs(…)`로."""
    # 막대 양옆에 공백을 둔다 — 'x|x - 1|'이 'xAbs(…)'(한 이름)로 붙어 읽히지 않게.
    s = re.sub(r"\|([^|]+)\|", r" Abs(\1) ", text)
    return parse_expr(s, local_dict={"x": _X, "Abs": sympy.Abs}, transformations=_TRANSFORMS)


def _function(question: str) -> sympy.Expr:
    m = re.search(r"f\(x\) = (.+?)에 대하여", question)
    assert m, question
    return _expr(m.group(1).strip())


def _one_sided(f: sympy.Expr, point: int, direction: str) -> sympy.Expr:
    """정의: `lim_{h→0±} (f(point + h) - f(point)) / h`."""
    quotient = (f.subs(_X, point + _H) - f.subs(_X, point)) / _H
    return sympy.limit(sympy.simplify(quotient), _H, 0, direction)


def _candidates(f: sympy.Expr) -> list[int]:
    roots: set[int] = set()
    for term in f.atoms(sympy.Abs):
        for r in sympy.solve(term.args[0], _X):
            if r.is_real:
                roots.add(int(r))
    return sorted(roots)


def _differentiable_at(f: sympy.Expr, point: int) -> bool:
    return bool(_one_sided(f, point, "+") == _one_sided(f, point, "-"))


def _solve_by_definition(item: ReachDiffItem) -> str:
    q = item.question_text
    f = _function(q)
    if "개수" in q:
        return str(sum(1 for p in _candidates(f) if not _differentiable_at(f, p)))
    m = re.search(r"x = (-?\d+)에서(?:의 우미분계수와 좌미분계수가 같으면| 미분가능하면)", q)
    if m:
        return "1" if _differentiable_at(f, int(m.group(1))) else "0"
    assert "실수 전체의 집합에서 미분가능하면" in q, q
    return "1" if all(_differentiable_at(f, p) for p in _candidates(f)) else "0"


@pytest.fixture(scope="module")
def items() -> list[ReachDiffItem]:
    return _items()


class TestDeclaration:
    def test_sixty_items_per_owned_slot(self) -> None:
        assert Gen.slots == _SLOTS
        for slot in _SLOTS:
            assert len(Gen.items(slot)) == 60, slot

    def test_it_is_a_separate_generator_from_the_approved_fill_bank_one(self) -> None:
        """승인 은행(`p3_fill_v0`)의 생성기와 클래스·단위 코드·slug 접두가 다르다(문항 바이트 결속 보호)."""
        old = mod.P3DiffDifferentiabilityGenerator
        assert Gen is not old
        assert Gen.unit_code != old.unit_code
        assert Gen.slug_prefix != old.slug_prefix
        assert Gen.standard_code == old.standard_code == "[12미적Ⅰ-02-02]"


class TestHonestProblemTypes:
    def test_only_the_two_skill_reaching_types_allowed_by_the_frozen_spec(
        self, items: list[ReachDiffItem]
    ) -> None:
        spec = ps.load_scope_spec()
        allowed = set(spec.problem_types)
        types = {i.problem_type_code for i in items}
        assert types == {_COUNT, _CLAIM}
        assert types <= allowed

    def test_type_follows_the_stem_form(self, items: list[ReachDiffItem]) -> None:
        """개수를 묻는 문면은 count-solutions, '…면 1, …면 0'은 verify-claim — 문면 그대로."""
        for i in items:
            asks_count = "개수를 구하시오" in i.question_text
            asks_claim = re.search(r"면 1, .+면 0을 쓰시오", i.question_text) is not None
            assert asks_count != asks_claim, i.question_text
            assert i.problem_type_code == (_COUNT if asks_count else _CLAIM)
            assert i.answer_kind == (
                "nondifferentiable_point_count" if asks_count else "is_differentiable"
            )


class TestIndependentRecomputation:
    @pytest.mark.parametrize("slot", _SLOTS)
    def test_every_answer_matches_the_definition_from_the_student_text(self, slot: str) -> None:
        recomputed = [
            (i, _solve_by_definition(i)) for i in Gen.items(slot) if isinstance(i, ReachDiffItem)
        ]
        assert len(recomputed) == 60
        wrong = [
            (i.frame_id, i.question_text, i.answer_text, got)
            for i, got in recomputed
            if got != i.answer_text
        ]
        assert wrong == [], wrong[:3]

    def test_the_recomputation_would_notice_a_wrong_answer(
        self, items: list[ReachDiffItem]
    ) -> None:
        """대조군 — 정답을 뒤집은 문항은 재계산과 어긋난다(변별력)."""
        claim = next(i for i in items if i.problem_type_code == _CLAIM)
        flipped = dataclasses.replace(claim, answer_text="1" if claim.answer_text == "0" else "0")
        assert _solve_by_definition(flipped) != flipped.answer_text

    def test_conditions_are_the_stated_function(self, items: list[ReachDiffItem]) -> None:
        """검산 조건 = 발문의 함수(발문–검산 불일치 방지) — 문면에서 읽은 식과 SymPy 항등."""
        for i in items:
            assert isinstance(i.conditions, str)
            stated = _function(i.question_text)
            assert sympy.simplify(sympy.sympify(i.conditions) - stated) == 0, i.question_text


class TestDiscrimination:
    """P3-55 위험 R2 — 정답이 한 값이고 같은 사실 하나를 반복하던 상태를 다시 만들지 않는다."""

    def test_every_claim_frame_has_both_answers(self, items: list[ReachDiffItem]) -> None:
        by_frame: dict[str, set[str]] = {}
        for i in items:
            if i.problem_type_code == _CLAIM:
                by_frame.setdefault(i.frame_id, set()).add(i.answer_text)
        assert len(by_frame) >= 4
        assert all(v == {"0", "1"} for v in by_frame.values()), by_frame

    def test_count_answers_vary(self, items: list[ReachDiffItem]) -> None:
        answers = Counter(i.answer_text for i in items if i.problem_type_code == _COUNT)
        assert set(answers) == {"0", "1", "2", "3"}, answers

    def test_no_count_answer_is_reachable_by_a_shortcut_tally(
        self, items: list[ReachDiffItem]
    ) -> None:
        """후보 수 · 절댓값 막대 쌍의 수 · (절댓값 하나일 때) 안 다항식의 차수 — 문면에서 센다."""
        for i in items:
            if i.problem_type_code != _COUNT:
                continue
            f = _function(i.question_text)
            shown = re.search(r"f\(x\) = (.+?)에 대하여", i.question_text)
            assert shown
            tallies = {len(_candidates(f)), shown.group(1).count("|") // 2}
            inners = [t.args[0] for t in f.atoms(sympy.Abs)]
            if len(inners) == 1:
                tallies.add(int(sympy.degree(inners[0], _X)))
            assert int(i.answer_text) not in tallies, (i.question_text, tallies)

    def test_point_claims_ask_about_the_only_candidate(self, items: list[ReachDiffItem]) -> None:
        """'x = p에서 미분가능' 문항은 후보가 p 하나뿐 — 그래서 ℝ 전체 검산(`is_differentiable`)과 같은 명제다."""
        for i in items:
            m = re.search(r"x = (-?\d+)에서(?:의 우미분계수| 미분가능하면)", i.question_text)
            if m:
                assert _candidates(_function(i.question_text)) == [int(m.group(1))]

    def test_point_claim_builder_refuses_a_function_with_another_candidate(self) -> None:
        """틀이 지금 후보 하나짜리만 만들어 위 전수 검사는 이 절을 밟지 않는다 — 직접 밟는다.

        |x - 1|^3 + |x - 3|은 x = 1에서 미분가능하지만 실수 전체에서는 아니다(Tier1 은 실수 전체를
        판정하므로 'x = 1에서 미분가능 → 1'과 검산 재료가 어긋난다). 이 함수는 점 판정으로 내지 않는다.
        """
        two = [mod._abs_cube(1, 1), mod._kink(1, 3), *mod._smooth(_X**2)]
        assert mod._point_claim_item(slot="basic", frame_id="t", terms=two, point=1, stem=0) is None
        one = [mod._abs_cube(1, 1), *mod._smooth(_X**2)]  # 대조군 — 후보 하나면 낸다
        built = mod._point_claim_item(slot="basic", frame_id="t", terms=one, point=1, stem=0)
        assert built is not None and built.answer_text == "1"

    def test_stems_are_diverse(self, items: list[ReachDiffItem]) -> None:
        """서로 다른 문면 골격 — P3-55 §②-4의 기존 연결 근거는 줄기 4개였다."""
        assert len({skeleton_of(i.question_text) for i in items}) >= 100


_BRANCH = re.compile(
    r"x ([<>]) (-?\d+)일 때 f\(x\) = (.+?)이므로 f'\(x\) = (.+?)이고 (우|좌)미분계수는 (-?\d+)이다"
)


class TestExplanationIsFaithfulToTheStatement:
    def test_every_printed_branch_derivative_and_value_matches(
        self, items: list[ReachDiffItem]
    ) -> None:
        checked = 0
        for i in items:
            f = _function(i.question_text)
            for sign, point, branch, derivative, _side, value in _BRANCH.findall(i.explanation):
                p = int(point)
                x0 = sympy.Integer(p) + (sympy.Rational(1, 1000) * (1 if sign == ">" else -1))
                sub = {
                    t: (t.args[0] if t.args[0].subs(_X, x0) > 0 else -t.args[0])
                    for t in f.atoms(sympy.Abs)
                }
                expected = sympy.expand(f.xreplace(sub))
                assert sympy.expand(_expr(branch) - expected) == 0, (i.question_text, branch)
                assert sympy.expand(_expr(derivative) - sympy.diff(expected, _X)) == 0
                assert int(value) == sympy.diff(expected, _X).subs(_X, p)
                checked += 1
        assert checked >= 600, checked


class TestSolutionSteps:
    def test_claim_items_carry_a_verified_jump_chain(self, items: list[ReachDiffItem]) -> None:
        for i in items:
            if i.problem_type_code != _CLAIM:
                continue
            assert i.explicit_steps is not None
            chain = steps_of(i)
            assert chain.strategy == "E" and chain.steps == i.explicit_steps
            jump = int(chain.steps[-1])
            assert (jump == 0) == (i.answer_text == "1"), i.question_text

    def test_count_items_end_at_the_full_candidate_list(self, items: list[ReachDiffItem]) -> None:
        for i in items:
            if i.problem_type_code != _COUNT:
                continue
            last = steps_of(i).steps[-1]
            listed = sorted(int(v) for v in re.findall(r"x = (-?\d+)", last))
            assert listed == _candidates(_function(i.question_text)), (i.question_text, last)

    def test_a_wrong_jump_chain_is_refused(self) -> None:
        """대조군 — 값이 틀린 식 연쇄·등식이 섞인 연쇄·한 단계 연쇄는 받지 않는다(빌드가 멈춘다)."""
        good = (
            "(Derivative(x**2 - 3*x + 2, x) - Derivative(-x**2 + 3*x - 2, x)).doit().subs(x, 1)",
            "(-1) - (1)",
            "-2",
        )
        assert verified_expression_chain(good).steps == good
        # 세 거부 가지를 각각 사유 문구로 가른다 — 한 가지가 지워져도 다른 가지가 대신 거부하면
        # `pytest.raises(ValueError)` 만으로는 그 삭제가 보이지 않는다(P3-65 리뷰 ⑤).
        with pytest.raises(ValueError, match="전건 correct가 아니다"):
            verified_expression_chain((*good[:2], "2"))
        with pytest.raises(ValueError, match="등식이 섞였다"):
            verified_expression_chain((*good[:2], "y = -2"))
        with pytest.raises(ValueError, match="2개 이상"):
            verified_expression_chain(good[:1])
        with pytest.raises(ValueError, match="2개 이상"):
            verified_expression_chain(())


class TestCandidateRootsAreNeverSilentlyDropped:
    """생성기의 후보(절댓값 안 식의 실근)는 차수만큼 · 정수로 나와야 한다 — 아니면 생성 거부(⑥)."""

    def test_integer_roots_with_multiplicity(self) -> None:
        assert mod._abs_roots(sympy.Abs((_X - 1) ** 2 * (_X + 2))) == (-2, 1)

    @pytest.mark.parametrize(
        "inner",
        [_X**2 + 1, (_X - 1) * (_X**2 + 4), _X**2 - 2, _X**3 - 3 * _X + 1],
    )
    def test_missing_or_irrational_roots_refuse_generation(self, inner: sympy.Expr) -> None:
        with pytest.raises(ValueError, match="차수만큼|정수가 아닌"):
            mod._abs_roots(sympy.Abs(inner))
