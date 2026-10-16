"""[12미적Ⅰ-02-03] 규칙 일반화 생성기 — 독립 재계산·생략된 항의 복원·스킬 유형 (P3-05 5단계).

정답의 단일 권위는 생성기의 SymPy 미분이다. 이 테스트는 그 경로를 믿지 않고 **학생이 보는 문면**의
다항식(첫 세 항 + 생략 부호 + 끝 항)에서 생략된 항을 규칙으로 복원해 **차분몫을 약분한 값으로**
미분계수를 다시 계산한다. 문면이 보이는 항이 규칙과 어긋난 문항(끝 항 오기·부호 규칙 위반)은 여기서 걸린다.
"""

from __future__ import annotations

import glob
import json
import re
from pathlib import Path

import pytest
import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from whymath_backend.l3.equivalent import p3_diff_power_pattern_skeleton_generator as mod
from whymath_backend.l3.equivalent import p3_diff_skeleton_base as base
from whymath_backend.l3.equivalent.acceptance import evaluate_equivalent_candidate
from whymath_backend.l3.equivalent.p3_diff_power_pattern_skeleton_generator import (
    P3DiffPowerPatternGenerator as Gen,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import SLOT_IDS

pytestmark = pytest.mark.corpus_authoring

_X, _H = sympy.symbols("x h")
_SLOTS = ("applied", "mastery_check")
_CORPUS_ROOT = Path(__file__).resolve().parents[4] / "data" / "corpus"
_TRANSFORMS = (*standard_transformations, implicit_multiplication_application, convert_xor)

#: 틀마다 학생이 읽어 내야 하는 규칙 — 생성기와 따로 쓴 두 번째 정의(k번째 항의 (계수, 지수)).
_RULES = {
    "pat-consecutive-powers": lambda k: (1, k),
    "pat-odd-powers": lambda k: (1, 2 * k - 1),
    "pat-even-powers": lambda k: (1, 2 * k),
    "pat-coefficient-equals-exponent": lambda k: (k, k),
    "pat-alternating-signs": lambda k: ((-1) ** (k - 1), k),
    "pat-doubling-coefficients": lambda k: (2 ** (k - 1), k),
}
#: 끝 항의 지수 → 항의 개수
_COUNT = {
    "pat-consecutive-powers": lambda e: e,
    "pat-odd-powers": lambda e: (e + 1) // 2,
    "pat-even-powers": lambda e: e // 2,
    "pat-coefficient-equals-exponent": lambda e: e,
    "pat-alternating-signs": lambda e: e,
    "pat-doubling-coefficients": lambda e: e,
}


def _items() -> list[base.DiffItem]:
    return [i for s in _SLOTS for i in Gen.items(s)]


def _parse(text: str) -> sympy.Expr:
    return parse_expr(text, local_dict={"x": _X}, transformations=_TRANSFORMS)


_STEM = re.compile(
    r"f\(x\) = (?P<head>.+?) \+ \.\.\. (?P<last>[-+] [^에]+?)에 대하여 f'\((?P<pt>-?\d+)\)"
)


def _split(question: str) -> tuple[str, str, int]:
    match = _STEM.search(question)
    assert match is not None, question
    return match["head"], match["last"], int(match["pt"])


def _derivative_at(poly: sympy.Expr, point: int) -> int:
    """정의: (f(a + h) - f(a)) / h 를 약분해 h = 0 을 넣는다."""
    quotient = sympy.cancel((poly.subs(_X, point + _H) - poly.subs(_X, point)) / _H)
    return int(quotient.subs(_H, 0))


def _restored(item) -> tuple[sympy.Expr, int]:  # type: ignore[no-untyped-def]
    """문면의 보이는 항으로 규칙을 확인하고, 생략된 항을 채운 다항식과 점을 돌려준다."""
    head, last, point = _split(item.question_text)
    rule = _RULES[item.frame_id]
    shown = 4 if item.frame_id == "pat-alternating-signs" else 3  # 부호 규칙은 네 항을 보인다
    shown_head = _parse(head)
    first = sum(c * _X**e for c, e in (rule(k) for k in range(1, shown + 1)))
    assert sympy.expand(shown_head - first) == 0
    last_term = _parse(last.replace(" ", "").replace("+", "+", 1))
    exponent = sympy.degree(last_term, _X)
    n = _COUNT[item.frame_id](int(exponent))
    c_last, e_last = rule(n)
    assert sympy.expand(last_term - c_last * _X**e_last) == 0, item.question_text
    return sympy.Add(*(c * _X**e for c, e in (rule(k) for k in range(1, n + 1)))), point


class TestDeclaration:
    def test_generator_declares_the_two_pattern_slots(self) -> None:
        assert Gen.slots == _SLOTS
        assert Gen.standard_code == "[12미적Ⅰ-02-03]" and Gen.concept_src_id == "H:12미적Ⅰ02-03"

    @pytest.mark.parametrize("slot", sorted(set(SLOT_IDS) - set(_SLOTS)))
    def test_a_slot_it_does_not_own_is_empty(self, slot: str) -> None:
        assert Gen.items(slot) == ()

    @pytest.mark.parametrize("slot", _SLOTS)
    def test_twelve_items_over_three_frames(self, slot: str) -> None:
        items = Gen.items(slot)
        assert len(items) == 12 and {i.slot for i in items} == {slot}
        assert len({i.frame_id for i in items}) == 3
        assert len({i.answer_text for i in items}) >= 8  # 정답이 몰리지 않는다

    def test_every_item_carries_the_pattern_skill_type_and_no_choices(self) -> None:
        for item in _items():
            assert item.problem_type_code == "ptype.generalize-pattern"
            assert not item.choices and not item.misconception_ids and not item.distractors
            assert item.conditions and item.answer_map


class TestIndependentRecomputation:
    @pytest.mark.parametrize("slot", _SLOTS)
    def test_answers_match_the_derivative_of_the_restored_polynomial(self, slot: str) -> None:
        wrong = []
        for item in Gen.items(slot):
            poly, point = _restored(item)
            if str(_derivative_at(poly, point)) != item.answer_text:
                wrong.append((item.frame_id, item.question_text, item.answer_text))
        assert wrong == [], wrong[:3]

    def test_the_recomputation_would_notice_a_wrong_answer(self) -> None:
        item = Gen.items("applied")[0]
        poly, point = _restored(item)
        assert str(_derivative_at(poly, point)) == item.answer_text
        assert str(_derivative_at(poly, point)) != str(int(item.answer_text) + 1)

    def test_at_least_one_omitted_term_hides_between_the_dots(self) -> None:
        """생략 부호가 아무 항도 가리지 않는 문항(보이는 항이 전부)은 규칙 일반화가 아니다."""
        for item in _items():
            poly, _ = _restored(item)
            assert len(sympy.Add.make_args(sympy.expand(poly))) >= 6, item.question_text

    def test_no_example_values_are_given(self) -> None:
        """감사 1회차의 결함 — 문면이 미분계수 사례를 주면 도함수 없이 풀린다. 사례 값을 주지 않는다."""
        for item in _items():
            assert not re.search(r"[a-z]\(\d+\) = ", item.question_text), item.question_text
            assert "미분계수를" not in item.question_text.split("에 대하여")[0]


class TestExplanation:
    def test_filled_polynomial_and_derivative_in_the_explanation_are_faithful(self) -> None:
        checked = 0
        for item in _items():
            poly, point = _restored(item)
            filled = re.search(r"f\(x\) = (?P<f>.+?)이다\. ", item.explanation)
            deriv = re.search(r"f'\(x\) = (?P<d>.+?)이고, ", item.explanation)
            assert filled is not None and deriv is not None, item.explanation
            assert sympy.expand(_parse(filled["f"]) - poly) == 0, item.explanation
            assert sympy.expand(_parse(deriv["d"]) - sympy.diff(poly, _X)) == 0, item.explanation
            checked += 1
        assert checked == 24

    def test_summed_terms_add_up_to_the_answer(self) -> None:
        for item in _items():
            match = re.search(r"값은 (?P<sum>[-+\d ]+) = (?P<total>-?\d+)이다", item.explanation)
            assert match is not None, item.explanation
            assert int(sympy.sympify(match["sum"])) == int(match["total"]) == int(item.answer_text)

    def test_no_double_sign_or_particle_after_a_negative_number(self) -> None:
        for item in _items():
            for text in (item.question_text, item.explanation):
                assert not re.search(r"\+ -|- -|× -|-\d+를", text), text


class TestGateAndCorpus:
    def test_every_item_passes_the_acceptance_gate_and_a_wrong_answer_is_rejected(self) -> None:
        for slot in _SLOTS:
            spec = Gen.spec_for(slot)
            generator = Gen(slot=slot)
            while (candidate := generator.generate(spec)) is not None:
                ok = evaluate_equivalent_candidate(
                    spec,
                    candidate.problem,
                    provenance=candidate.provenance,
                    conditions=candidate.conditions,
                    answer_map=candidate.answer_map,
                )
                assert ok.accepted, ok.reasons
                key = sorted(candidate.answer_map)[-1]
                broken = dict(candidate.answer_map)
                broken[key] = f"({broken[key]}) + 1"
                bad = evaluate_equivalent_candidate(
                    spec,
                    candidate.problem,
                    provenance=candidate.provenance,
                    conditions=candidate.conditions,
                    answer_map=broken,
                )
                assert not bad.accepted

    def test_slot_building_reserves_the_approved_bank_conditions(self) -> None:
        theirs = mod._sibling_condition_keys()
        assert theirs
        claimed: set[str] = set()
        Gen._slot_items("applied", claimed)
        assert theirs <= claimed

    def test_no_question_text_repeats_any_other_bank(self) -> None:
        mine = {i.question_text for i in _items()}
        for path in glob.glob(str(_CORPUS_ROOT / "problem_bank_*" / "problems.jsonl")):
            if Path(path).parent.name == "problem_bank_p3_fill_v0":
                continue
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    assert json.loads(line).get("question_text") not in mine, path

    def test_items_are_deterministic_across_cache_rebuilds(self) -> None:
        before = {slot: Gen.items(slot) for slot in SLOT_IDS}
        for slot in SLOT_IDS:
            base._ITEM_CACHE.pop((Gen, slot), None)
        assert before == {slot: Gen.items(slot) for slot in SLOT_IDS}


class TestHelpers:
    def test_signed_sum_and_paren_never_print_a_double_sign(self) -> None:
        assert mod._signed_sum([1, -2, 3, -4]) == "1 - 2 + 3 - 4"
        assert mod._paren(-3) == "(-3)" and mod._paren(3) == "3"

    def test_term_text(self) -> None:
        assert mod._term_text(1, 1, first=True) == "x"
        assert mod._term_text(-1, 2, first=True) == "-x^2"
        assert mod._term_text(3, 4, first=False) == "+ 3x^4"
        assert mod._term_text(-2, 1, first=False) == "- 2x"

    def test_expanded_text_handles_constants_and_signs(self) -> None:
        assert mod._expanded_text([(1, 0), (-2, 1), (3, 2)]) == "1 - 2x + 3x^2"
        assert mod._expanded_text([(-1, 0), (2, 1)]) == "-1 + 2x"

    def test_the_alternating_series_shows_four_terms_and_a_signed_last_term(self) -> None:
        """부호가 번갈아 바뀌는 급수는 세 항만으로 생략된 부호가 하나로 읽히지 않는다(감사 2회차)."""
        text = mod._series_text(mod._alternating, 7, 4)
        assert text == "x - x^2 + x^3 - x^4 + ... + x^7"
        assert mod._SHOWN_TERMS == {"pat-alternating-signs": 4}
        for item in Gen.items("mastery_check"):
            if item.frame_id == "pat-alternating-signs":
                assert re.search(r"f\(x\) = x - x\^2 \+ x\^3 - x\^4 \+ \.\.\.", item.question_text)

    def test_answers_beyond_the_hand_arithmetic_cap_are_skipped(self) -> None:
        """상한 가드는 문항을 만드는 길목에서 직접 확인한다 — 은행이 우연히 작아도 가드는 살아 있어야 한다."""
        small = mod._item(
            slot="mastery_check",
            frame_id="x",
            term=mod._doubling,
            n_terms=6,
            point=2,
            general="",
        )
        huge = mod._item(
            slot="mastery_check",
            frame_id="x",
            term=mod._doubling,
            n_terms=8,
            point=2,
            general="",
        )
        assert small is not None and abs(int(small.answer_text)) <= mod._MAX_ANSWER
        assert huge is None, "상한을 넘는 정답 후보를 건너뛰지 않았다"
        assert all(abs(int(i.answer_text)) <= mod._MAX_ANSWER for i in _items())

    def test_series_text_hides_the_middle_terms(self) -> None:
        assert mod._series_text(mod._power, 6) == "x + x^2 + x^3 + ... + x^6"
        assert mod._series_text(mod._alternating, 6) == "x - x^2 + x^3 + ... - x^6"
