"""[12미적Ⅰ-02-10] 상황 설명(문장제) 생성기 — 독립 재계산·번역 정합·스킬 유형 (P3-05 5단계).

정답의 단일 권위는 생성기의 SymPy 미분·풀이다. 이 테스트는 그 경로를 믿지 않고 **학생이 보는 문면**에서
위치함수와 상황의 말("방향을 바꾼다", "멈췄다", "가속도가 0이 되었다", "속도가 …였다")을 다시 읽어
방정식으로 옮겨 SymPy로 푼 값과 정답을 대조한다. 번역(상황의 말 → 식)이 틀린 문항은 정답이 맞아 보여도
여기서 걸린다.
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

from whymath_backend.l3.equivalent import p3_diff_motion_word_problem_skeleton_generator as mod
from whymath_backend.l3.equivalent import p3_diff_skeleton_base as base
from whymath_backend.l3.equivalent.acceptance import evaluate_equivalent_candidate
from whymath_backend.l3.equivalent.p3_diff_motion_word_problem_skeleton_generator import (
    P3DiffMotionWordProblemGenerator as Gen,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import SLOT_IDS

pytestmark = pytest.mark.corpus_authoring

_T, _U = sympy.symbols("t u")
_SLOTS = ("applied", "mastery_check")
_CORPUS_ROOT = Path(__file__).resolve().parents[4] / "data" / "corpus"


def _sym(text: str) -> sympy.Expr:
    """학생 표기('3t^2 - 2ut + 24')를 SymPy 로 읽는다(암묵 곱·^ 지수)."""
    return parse_expr(
        text,
        local_dict={"t": _T, "u": _U},
        transformations=(
            *standard_transformations,
            implicit_multiplication_application,
            convert_xor,
        ),
    )


def _items() -> list[base.DiffItem]:
    return [i for s in _SLOTS for i in Gen.items(s)]


_FN = re.compile(r"s\(t\) = (?P<expr>[^(가-힣]+?) \(cm\)이다")


def _position(text: str) -> sympy.Expr:
    """문면의 위치함수 s(t) — 'ut' 같은 암묵 곱은 u*t 로 읽는다."""
    match = _FN.search(text)
    assert match is not None, text
    return _sym(match["expr"])


def _positive_stops(f: sympy.Expr) -> list[sympy.Expr]:
    return [r for r in sympy.solve(sympy.diff(f, _T), _T) if r.is_real and r > 0]


def _recompute(item) -> str:  # type: ignore[no-untyped-def]
    text = item.question_text
    f = _position(text)
    fid = item.frame_id
    if fid == "word-rail-time-of-turn":
        (t0,) = _positive_stops(f)
        return str(t0)
    if fid == "word-rail-position-at-turn":
        (t0,) = _positive_stops(f)
        return str(f.subs(_T, t0))
    if fid == "word-rail-acceleration-at-turn":
        (t0,) = _positive_stops(f)
        return str(sympy.diff(f, _T, 2).subs(_T, t0))
    if fid == "word-rail-constant-from-stop-time":
        time = int(re.search(r"(\d+)초 후에 순간적으로 멈췄다", text).group(1))  # type: ignore[union-attr]
        (u,) = sympy.solve(sympy.diff(f, _T).subs(_T, time), _U)
        return str(u)
    if fid == "word-rail-constant-from-zero-acceleration":
        time = int(re.search(r"(\d+)초 후에 0이 되었다", text).group(1))  # type: ignore[union-attr]
        (u,) = sympy.solve(sympy.diff(f, _T, 2).subs(_T, time), _U)
        return str(u)
    if fid == "word-rail-constant-from-speed":
        time, speed = (int(v) for v in re.search(r"(\d+)초 후에 (-?\d+) cm/초였다", text).groups())  # type: ignore[union-attr]
        (u,) = sympy.solve(sympy.diff(f, _T).subs(_T, time) - speed, _U)
        return str(u)
    if fid == "word-rail-constant-from-acceleration":
        time, accel = (int(v) for v in re.search(r"(\d+)초 후에 (-?\d+) cm/초\^2였다", text).groups())  # type: ignore[union-attr]
        (u,) = sympy.solve(sympy.diff(f, _T, 2).subs(_T, time) - accel, _U)
        return str(u)
    raise AssertionError(f"독립 재계산 경로가 없는 틀: {fid}")


class TestDeclaration:
    def test_generator_declares_the_two_slots_and_the_modeling_type(self) -> None:
        assert Gen.slots == _SLOTS
        assert Gen.standard_code == "[12미적Ⅰ-02-10]" and Gen.concept_src_id == "H:12미적Ⅰ02-10"
        assert {i.problem_type_code for i in _items()} == {"ptype.model-word-problem"}

    @pytest.mark.parametrize("slot", sorted(set(SLOT_IDS) - set(_SLOTS)))
    def test_a_slot_it_does_not_own_is_empty(self, slot: str) -> None:
        assert Gen.items(slot) == ()

    @pytest.mark.parametrize("slot", _SLOTS)
    def test_twelve_items_over_frames_with_distinct_answers_per_frame(self, slot: str) -> None:
        items = Gen.items(slot)
        assert len(items) == 12 and {i.slot for i in items} == {slot}
        frames = {i.frame_id for i in items}
        assert len(frames) >= 3
        for frame in frames:
            answers = [i.answer_text for i in items if i.frame_id == frame]
            assert len(set(answers)) == len(answers), (frame, answers)

    def test_no_choices_or_misconceptions_and_integer_answers(self) -> None:
        for item in _items():
            assert not item.choices and not item.misconception_ids and not item.distractors
            assert re.fullmatch(r"-?\d+", item.answer_text), item.answer_text


class TestIndependentRecomputation:
    @pytest.mark.parametrize("slot", _SLOTS)
    def test_every_answer_matches_a_translation_of_the_situation_from_the_text(
        self, slot: str
    ) -> None:
        wrong = [
            (i.frame_id, i.question_text, i.answer_text, _recompute(i))
            for i in Gen.items(slot)
            if _recompute(i) != i.answer_text
        ]
        assert wrong == [], wrong[:3]

    def test_the_recomputation_would_notice_a_wrong_answer(self) -> None:
        item = Gen.items("applied")[0]
        assert _recompute(item) == item.answer_text
        assert _recompute(item) != str(int(item.answer_text) + 1)

    def test_every_position_is_cubic_so_the_vertex_formula_is_not_a_shortcut(self) -> None:
        """감사 1회차 as-found: 이차 위치함수는 꼭짓점 공식으로 풀려 '미분 없이 풀림'이었다."""
        for item in _items():
            f = _position(item.question_text)
            assert sympy.degree(f, _T) == 3, item.question_text

    def test_the_turn_is_the_only_positive_stop_and_the_sign_really_changes(self) -> None:
        for item in Gen.items("applied"):
            f = _position(item.question_text)
            (t0,) = _positive_stops(f)
            v = sympy.diff(f, _T)
            before, after = v.subs(_T, t0 - sympy.Rational(1, 10)), v.subs(
                _T, t0 + sympy.Rational(1, 10)
            )
            assert before * after < 0, item.question_text  # 부호가 실제로 바뀐다


class TestExplanation:
    def test_the_velocity_and_acceleration_formulas_are_the_derivatives_of_the_position(
        self,
    ) -> None:
        checked = 0
        for item in _items():
            f = _position(item.question_text)
            for pattern, order in ((r"v\(t\) = ([^이]+?)이다", 1), (r"a\(t\) = ([^이]+?)이", 2)):
                match = re.search(pattern, item.explanation)
                if match is None:
                    continue
                printed = _sym(match.group(1))
                assert sympy.expand(printed - sympy.diff(f, _T, order)) == 0, item.explanation
                checked += 1
        assert checked >= 28

    def test_velocity_is_introduced_as_the_derivative_of_the_position(self) -> None:
        for item in _items():
            assert "위치" in item.explanation and "도함수" in item.explanation, item.explanation

    def test_stop_and_turn_questions_say_zero_velocity_and_the_sign_change(self) -> None:
        for item in _items():
            if re.search(r"멈추|정지|멈췄", item.question_text):
                assert "v(t) = 0" in item.explanation, item.explanation
            if "방향을 바꾸" in item.question_text:
                assert "v(t) = 0" in item.explanation and "부호가" in item.explanation


class TestGateAndCorpus:
    def test_every_item_passes_the_acceptance_gate_and_a_wrong_answer_is_rejected(self) -> None:
        total = 0
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
                total += 1
        assert total == 24

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
    def test_distinct_answer_frame_keeps_the_first_of_each_answer(self) -> None:
        def build(p: tuple[object, ...]) -> base.DiffItem | None:
            if p[0] == 0:
                return None
            return mod._unknown_item(
                frame_id="t",
                text="x",
                condition="u = 1",
                answer=int(str(p[0])) % 2,
                explanation="x",
            )

        frame = mod._distinct_answer_frame("t", ((0,), (1,), (3,), (2,), (4,)), build)
        assert frame.params == ((1,), (2,))  # None 은 빼고 답 1 은 첫 후보만, 답 0 은 (2,)

    def test_rail_polynomial_has_one_positive_stop_and_integer_coefficients(self) -> None:
        assert mod._rail_poly(1, 5, 1) == ((3, 1), (2, -6), (1, -15))  # v = 3(t - 5)(t + 1)
        assert mod._rail_poly(1, 2, 2) is None  # r == n
        assert mod._rail_poly(1, 1, 2) is None  # 3a(n - r)이 홀수라 b가 정수가 아니다

    def test_derivative_texts(self) -> None:
        poly = ((3, 1), (2, -6), (1, -15))
        assert mod._derivative_text(poly) == "3t^2 - 12t - 15"
        assert mod._second_text(poly) == "6t - 12"

    def test_turn_reason_names_the_sign_change(self) -> None:
        assert "음에서 양으로" in mod._turn_reason(2, 3)
        assert "양에서 음으로" in mod._turn_reason(-1, 4)

    def test_velocity_head_introduces_the_symbol_as_subject(self) -> None:
        head = mod._v_head(((3, 1), (2, -6), (1, -15)))
        assert head.startswith("속도 v(t)는 열차의 위치 s(t)의 도함수이므로 v(t) = ")

    def test_degenerate_parameter_sets_are_dropped_not_stored(self) -> None:
        """퇴화 후보(속도·가속도 0, 양이 아닌 상수)는 틀 함수가 직접 건너뛴다 — 은행이 우연히 피해도 가드는 산다."""
        assert mod._speed_constant((2, 4, 4)) is None  # v(2) = 12 - 16 + 4 = 0
        assert mod._speed_constant((2, 4, 5)) is not None  # 대조군 — v(2) = 1
        assert mod._acceleration_constant((3, 9)) is None  # a(3) = 18 - 18 = 0
        assert mod._acceleration_constant((3, 8)) is not None  # 대조군 — a(3) = 2
        assert mod._stop_constant((2, 1)) is None  # c = 4 - 12 < 0
        assert mod._stop_constant((2, 4)) is not None  # 대조군 — c = 16 - 12 = 4

    def test_turn_questions_verify_only_the_positive_stop_time(self) -> None:
        """방향을 바꾸는 시각은 t > 0 인 해 하나 — 검산 조건이 그 제약을 그대로 싣는다."""
        for item in Gen.items("applied"):
            assert "x > 0" in item.conditions, item.question_text
            assert "x >= 0" not in item.conditions
