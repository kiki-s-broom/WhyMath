"""[12미적Ⅰ-02-01] 미분계수 생성기 — 독립 경로 재계산·슬롯 계약·빈 칸 정합 (P3-05 4단계).

정답의 단일 권위는 생성기의 SymPy 미분이다. 이 테스트는 그 경로를 믿지 않고 **학생이 보는 문면**에서
식을 다시 읽어 **정의(극한)로** 정답을 재계산한다 — 문면과 정답이 어긋난 문항(증분 배수 오기·분모 오기·
점 오기 등)은 여기서 걸린다.
"""

from __future__ import annotations

import re
from collections import Counter

import pytest
import sympy

from whymath_backend.l3.equivalent.p3_diff_differential_coefficient_skeleton_generator import (
    P3DiffDifferentialCoefficientGenerator as Gen,
)
from whymath_backend.l3.equivalent.p3_diff_differential_coefficient_skeleton_generator import (
    _mastery_frames,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import SLOT_IDS, skeleton_of

_X, _H, _A, _C = sympy.symbols("x h a c")

_SLOTS = ("representative", "basic", "diagnostic", "mastery_check")


def _expr(text: str, **names: object) -> sympy.Expr:
    """학생 표기 식('2x^2 - 3x', '(f(-3 + 2h) - f(-3)) / h')을 SymPy 로 읽는다. `f` 는 함수로 받는다."""
    s = text.replace("^", "**")
    # 암묵 곱셈: 숫자·')' 뒤의 문자/'(' , 문자 뒤의 문자('ax' → a*x). 함수 호출 'f(' 는 건드리지 않는다.
    s = re.sub(r"(?<=[0-9)])(?=[a-z(])|(?<=[a-z])(?=[a-z])", "*", s)
    return sympy.sympify(s, locals={"x": _X, "h": _H, "a": _A, "c": _C, **names})


def _poly_of(question: str) -> str:
    """`f(x) = …` 우변의 다항식 문자열(한글·'(a는 상수)' 제외)."""
    cleaned = question.replace(" (a는 상수)", "")
    m = re.search(r"[fg]\([xt]\) = ([^가-힣]+)", cleaned) or re.search(r"y = ([^가-힣]+)", cleaned)
    assert m, question
    return m.group(1).strip()


def _function(question: str) -> sympy.Lambda:
    return sympy.Lambda(_X, _expr(_poly_of(question).replace("t", "x")))


def _solve_by_definition(item) -> str:  # type: ignore[no-untyped-def]
    """문면만으로 정답을 다시 구한다(정의 = 차분몫의 극한 · 미지 상수는 방정식으로)."""
    q = item.question_text
    fid = item.frame_id
    if fid in {"rep-difference-quotient-in-h"} or fid.startswith("diag-"):
        f = _function(q)
        m = re.search(r"때 (\(f\(.+\)) / (.+?)의 극한값", q)
        assert m, q
        quotient = _expr(f"{m.group(1)} / {m.group(2)}", f=f)
        return str(sympy.limit(quotient, _H, 0))
    if fid == "rep-difference-quotient-in-x":
        f = _function(q)
        a = int(re.search(r"x가 (-?\d+)에", q).group(1))  # type: ignore[union-attr]
        m = re.search(r"때 (\(f\(x\) - f\(.+?\)\)) / (\(.+?\))의 극한값", q)
        assert m, q
        return str(sympy.limit(_expr(f"{m.group(1)} / {m.group(2)}", f=f), _X, a))
    if fid == "rep-average-rate-limit":
        f = _function(q)
        a = int(re.search(r"x의 값이 (-?\d+)에서", q).group(1))  # type: ignore[union-attr]
        return str(sympy.limit((f(a + _H) - f(a)) / _H, _H, 0))
    if fid in {
        "rep-instantaneous-rate",
        "basic-tangent-slope-of-curve",
        "basic-tangent-slope-at-given-point",
    }:
        f = _function(q)
        m = (
            re.search(r"x = (-?\d+)일 때", q)
            or re.search(r"x좌표가 (-?\d+)인", q)
            or re.search(r"점 \((-?\d+), ", q)
        )
        assert m, q
        a = int(m.group(1))
        return str(sympy.limit((f(a + _H) - f(a)) / _H, _H, 0))
    if fid in {"basic-differential-coefficient", "basic-differential-coefficient-in-t"}:
        f = _function(q)
        m = re.search(r"[fg]'\((-?\d+)\)의 값", q)
        assert m, q
        a = int(m.group(1))
        return str(sympy.limit((f(a + _H) - f(a)) / _H, _H, 0))
    if fid in {"mastery-coefficient-from-limit-value", "mastery-coefficient-from-scaled-limit"}:
        f = sympy.Lambda(_X, _expr(_poly_of(q)))
        m = re.search(r"\(f\((.+?)\) - f\((-?\d+)\)\) / h의 극한값이 (-?\d+)이다", q)
        assert m, q
        step = _expr(m.group(1), h=_H)
        a0 = int(m.group(2))
        value = int(m.group(3))
        quotient = (f(step) - f(a0)) / _H
        return str(sympy.solve(sympy.limit(quotient, _H, 0) - value, _A)[0])
    if fid == "mastery-average-rate-equals-coefficient":
        f = sympy.Lambda(_X, _expr(_poly_of(q)))
        m = re.search(r"x의 값이 (-?\d+)에서 (-?\d+)까지 .* x = (-?\d+)에서의", q)
        assert m, q
        lo, hi, r = (int(v) for v in m.groups())
        avg = (f(hi) - f(lo)) / (hi - lo)
        slope = sympy.diff(f(_X), _X).subs(_X, r)
        return str(sympy.solve(sympy.Eq(avg, slope), _A)[0])
    raise AssertionError(f"독립 재계산 경로가 없는 틀: {fid}")


class TestDeclaration:
    def test_generator_declares_exactly_the_four_empty_cells(self) -> None:
        assert Gen.slots == _SLOTS
        assert set(Gen.slot_difficulty) >= set(_SLOTS)

    @pytest.mark.parametrize("slot", sorted(set(SLOT_IDS) - set(_SLOTS)))
    def test_a_slot_it_does_not_own_is_an_empty_generator_not_an_error(self, slot: str) -> None:
        """겹침 감사기(QUAL-08)는 `slot` Literal 의 모든 값으로 인스턴스화한다 — 던지면 '측정 불가'가 된다."""
        generator = Gen(slot=slot)  # type: ignore[arg-type]
        assert Gen.items(slot) == ()
        assert generator.generate(Gen.spec_for("representative")) is None

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
        item = Gen.items("diagnostic")[0]
        assert _solve_by_definition(item) == item.answer_text
        assert _solve_by_definition(item) != str(int(item.answer_text) + 1)


class TestSlotShape:
    @pytest.mark.parametrize("slot", _SLOTS)
    def test_at_least_three_frames_and_eight_distinct_skeletons(self, slot: str) -> None:
        items = Gen.items(slot)
        assert len({i.frame_id for i in items}) >= 3
        assert len({skeleton_of(i.question_text) for i in items}) >= 8

    def test_problem_types_are_honest(self) -> None:
        for slot in ("representative", "basic", "diagnostic"):
            assert {i.problem_type_code for i in Gen.items(slot)} == {"ptype.evaluate-expression"}
        assert {i.problem_type_code for i in Gen.items("mastery_check")} == {
            "ptype.solve-for-unknown"
        }

    def test_no_misconception_is_linked_because_the_trigger_cell_is_already_filled(self) -> None:
        assert all(not i.misconception_ids for s in _SLOTS for i in Gen.items(s))

    def test_diagnostic_frames_each_ask_for_a_different_relation(self) -> None:
        by_frame = Counter(i.frame_id for i in Gen.items("diagnostic"))
        assert set(by_frame) == {
            "diag-increment-doubled-over-h",
            "diag-increment-tripled-over-same",
            "diag-symmetric-over-2h",
            "diag-symmetric-over-h",
        }

    def test_scaled_diagnostics_are_not_the_definition_and_their_explanation_says_why(self) -> None:
        """2배가 되는 두 틀은 정의 꼴이 아니라는 점을 해설이 먼저 말한다 — 답만 적은 해설이 아니다."""
        for i in Gen.items("diagnostic"):
            if i.frame_id in {"diag-increment-doubled-over-h", "diag-symmetric-over-h"}:
                assert "2배" in i.explanation, i.explanation

    def test_points_are_not_all_on_one_side(self) -> None:
        for slot in ("representative", "basic", "diagnostic"):
            points = {
                int(m.group(1))
                for i in Gen.items(slot)
                if (m := re.search(r"subs\(\w, (-?\d+)\)", str(i.conditions)))
            }
            assert any(p > 0 for p in points) and any(p < 0 for p in points), (slot, points)

    def test_scaled_limit_frame_is_not_a_copy_that_differs_only_in_the_cancelled_term(self) -> None:
        """평균변화율 틀은 일차항 계수 c1 이 양변에서 사라진다 — c1 만 다른 문항이 둘 있으면 복제다."""
        keys = []
        for i in Gen.items("mastery_check"):
            if i.frame_id != "mastery-average-rate-equals-coefficient":
                continue
            m = re.search(
                r"f\(x\) = (-?\d*)x\^3.*x의 값이 (-?\d+)에서 (-?\d+)까지.*x = (-?\d+)에서",
                i.question_text,
            )
            assert m, i.question_text
            keys.append(m.groups())
        assert keys and len(keys) == len(set(keys))


class TestGivenPointCoordinates:
    def test_the_stated_y_coordinate_is_the_function_value_at_that_x(self) -> None:
        """'점 (a, b)'의 b 가 f(a)가 아니면 학생이 보는 점이 곡선 위에 있지 않다 — 정답만 맞는 불량 문항."""
        checked = 0
        for item in Gen.items("basic"):
            if item.frame_id != "basic-tangent-slope-at-given-point":
                continue
            f = _function(item.question_text)
            m = re.search(r"점 \((-?\d+), (-?\d+)\)", item.question_text)
            assert m, item.question_text
            assert f(int(m.group(1))) == int(m.group(2)), item.question_text
            checked += 1
        assert checked >= 2, "점 좌표 틀의 문항이 없어 이 검사가 공허하다"


class TestAverageRateFrameRejectsDegenerateInputs:
    """평균변화율 틀의 방어 분기는 기본 파라미터 열에서 밟히지 않는다 — 직접 먹여서 잠근다."""

    @staticmethod
    def _build(params: tuple[object, ...]):  # type: ignore[no-untyped-def]
        frame = next(
            f for f in _mastery_frames() if f.frame_id == "mastery-average-rate-equals-coefficient"
        )
        return frame.build(params)

    def test_midpoint_of_the_interval_is_rejected(self) -> None:
        """(c3, c1, lo, hi, r): r 이 구간의 중점이면 a 가 양변에서 사라진다 — 문항이 되지 않는다."""
        assert self._build((1, 2, -1, 3, 1)) is None

    def test_a_non_integer_unknown_is_rejected(self) -> None:
        assert self._build((1, 2, 0, 2, 3)) is None  # a = 23/(-4)

    def test_a_zero_unknown_is_rejected(self) -> None:
        """a = 0 이면 '상수 a'가 사라져 식이 상수 계수를 갖지 않는다 — 구하는 값이 자명하다."""
        assert self._build((1, 2, -1, 2, 1)) is None

    def test_a_valid_input_builds_and_has_the_expected_answer(self) -> None:
        item = self._build((1, 2, -1, 2, 5))
        assert item is not None and item.answer_text == "-8"
