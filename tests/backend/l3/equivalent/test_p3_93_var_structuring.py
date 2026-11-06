"""P3-93 — 잔여 VAR(마지막 단계 변수 ≠ 정답 변수) 꼴의 구조화 계약(빌더 1건씩 · 생성기 전체를 돌리지 않는다).

P3-62 규칙 (가)는 "근 목록 → 근 선택 → 정답 변수 값"을 **조건만으로** 증명할 수 있을 때만 풀이 끝을 붙인다.
P3-62 §B-5가 남긴 네 꼴은 선택 근거를 조건에 실을 방법이 없어 검증 불가로 남았다. P3-93은 **판정기를 넓히지
않고**(공용 해석 판정 `verify_solution_interpreted`·허용 목록 다항식 그대로) 생성기가 조건을 더 정확히 싣는다.

검증 축
-------
① A 미지수 a·b 연립 — 연립을 소거한 조건(b 정의 등식 + a 단일 방정식 + 극값 종류의 f''(r) 부호)에서 연쇄를
   새로 풀어 정답 변수(a 또는 b)의 값까지 간다. a를 묻는 틀은 연쇄가 a에서 끝나고, b를 묻는 틀은 a 값을 b 정의
   등식에 대입하는 한 줄이 붙는다(조건으로 증명된 대입).
② B 같은 종류 두 극값 중 큰/작은 값 — f'' 부호 + **같은 종류 극점 전부**와의 값 비교 부등식.
③ C 범위(전 실수·x ≥ 0) 최솟값 — 범위 안 임계점 **전부**와 경계와의 값 비교 부등식.
④ D 평평한 임계점이 섞인 '극값' — f''(x) ≠ 0(평평한 근은 f''도 0이라 빠진다).
⑤ **결함 주입(RED)** — 각 꼴에서 생성기가 *다른* 근을 고르거나 틀린 값을 진술하면 Solution QA C4가 FAIL을 낸다
   (조건이 고르는 근이 정해져 있다 — 판정은 정답 기록이 아니라 조건에서 나온다). 비교 조건을 빼면 선택이 증명되지
   않고(후보 둘 이상), 값이 같은 두 극값은 하나로 정해지지 않는다(구조화 안 됨 — 거짓 통과 없음).
⑥ 정답 역산 금지 — 비교 조건을 만드는 함수에는 정답을 넘기는 자리가 없다(시그니처 동결). 비교 대상은 후보
   전부이고 조건 문자열은 정답 극점과 무관하게 같다.
⑦ 저작 결함 — 구조화 출발식이 정답 기록과 다른 값에 닿으면 빌드가 멈춘다(ValueError · 조용한 강등 없음).
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Mapping, Sequence

import pytest

from whymath_backend.harness import solution_qa as sq
from whymath_backend.l3.equivalent.p3_diff_equation_application_skeleton_generator import (
    _Min,
    _min_item,
    _min_rank_conditions,
)
from whymath_backend.l3.equivalent.p3_diff_expr import Poly
from whymath_backend.l3.equivalent.p3_diff_graph_shape_skeleton_generator import (
    _analyze,
    _find_ab_item,
    _find_b_quartic_frame,
    _judged_value_item,
    _quartic_k_frame,
    _value_rank_conds,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import DiffItem, structured_view
from whymath_backend.l3.equivalent.p3_diff_solution_steps import final_statement_steps

_AB_TEMPLATE = (
    "함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오. "
    "(단, a, b는 상수이다.)"
)


def _judge(
    answer: str,
    conditions: Sequence[str] | str,
    answer_map: Mapping[str, str],
    steps: Sequence[str],
) -> dict[str, str]:
    """Solution QA C1·C2·C4 판정 상태 — 은행 레코드와 같은 모양의 최소 레코드로 본다."""
    verify = {
        "conditions": list(conditions) if not isinstance(conditions, str) else conditions,
        "answer_map": dict(answer_map),
        "solution_steps": list(steps),
    }
    record = {"answer": answer, "verify": verify}
    return {
        "C1": sq._check_c1(record, verify).state.value,
        "C2": sq._check_c2(record, verify).state.value,
        "C4": sq._check_c4(verify).state.value,
    }


def _passes(item: DiffItem) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """구조화본이 C1·C2·C4 전부 pass인지 단언하고 (조건, 단계)를 돌려준다."""
    view = structured_view(item)
    assert view is not None
    conditions, steps = view
    assert isinstance(conditions, tuple)
    states = _judge(item.answer_text, conditions, dict(item.answer_map), steps)
    assert states == {"C1": "pass", "C2": "pass", "C4": "pass"}, (states, conditions, steps)
    return conditions, steps


def _substituted(conditions: Sequence[str], chain_end: Sequence[str], var: str, pick: str) -> str:
    """정의 등식 `y = P(var)`에 pick을 대입한 값(결함 주입 — 다른 근을 고른 진술값)."""
    import sympy

    definition = next(c for c in conditions if c.startswith("y = "))
    return str(sympy.sympify(definition[4:]).subs(sympy.Symbol(var), sympy.Integer(pick)))


# ── ① A — a·b 연립 ───────────────────────────────────────────────────────
def _cubic_find_a() -> DiffItem:
    # 실 은행 레코드 wm-p3-diff-graphshape-157000e44a8f — f(x) = x^3 + ax^2 + bx + 6, x = 3에서 극솟값 -21.
    item = _find_ab_item(
        "applied", "t-find-a", _AB_TEMPLATE, lead=1, a=-3, b=-9, c=6, r=3, ask="a", want="min"
    )
    assert item is not None
    return item


def test_a_find_a_chain_ends_at_answer_variable() -> None:
    item = _cubic_find_a()
    conditions, steps = _passes(item)
    assert conditions[0] == "b = -6*a - 27"  # f'(3) = 27 + 6a + b = 0 을 b에 대해 푼 정의 등식
    assert conditions[2] == "2*a + 18 > 0"  # 극소 — f''(3) = 18 + 2a > 0
    assert steps[0] == item.structured_setup
    assert steps[-1] == "a = -3"


def test_a_find_b_appends_proven_substitution() -> None:
    # _find_b_cubic_frame과 같은 수 — f(x) = -x^3 + 3x^2 + 9x + 1, x = 3에서 극값(b를 묻는다).
    item = _find_ab_item(
        "mastery_check", "t-find-b", _AB_TEMPLATE, lead=-1, a=3, b=9, c=1, r=3, ask="b", want=None
    )
    assert item is not None
    _, steps = _passes(item)
    assert steps[-2:] == ("a = 3", "b = 9")


def test_a_quartic_find_b() -> None:
    frame = _find_b_quartic_frame(
        "t-quartic-b",
        "사차함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오. "
        "(단, a, b는 상수이다.)",
        "seed",
        slot="mastery_check",
    )
    item = frame.build((3, 5))  # q = 3 → a = -4 · f(x) = x^4 - 4x^3 + 5 · 극솟값 -22
    assert item is not None
    conditions, steps = _passes(item)
    assert steps[-2:] == ("a = -4", "b = 5")
    assert conditions[2] == "18*a + 108 > 0"  # 극소 — f''(3) = 108 + 18a > 0


def test_a_wrong_substitution_value_is_red() -> None:
    """결함 주입 — b 대입 진술이 정의 등식과 다르면 C4 FAIL(조건이 b를 정한다)."""
    item = _find_ab_item(
        "mastery_check", "t-find-b", _AB_TEMPLATE, lead=-1, a=3, b=9, c=1, r=3, ask="b", want=None
    )
    assert item is not None
    conditions, steps = _passes(item)
    bad = (*steps[:-1], "b = 10")
    assert _judge("10", conditions, {**dict(item.answer_map), "b": "10"}, bad)["C4"] == "fail"


def test_a_authoring_defect_stops_the_build() -> None:
    """저작 결함 — 기록된 정답이 조건이 정하는 값과 다르면 구조화 빌드가 멈춘다."""
    item = _cubic_find_a()
    broken = dataclasses.replace(
        item, answer_text="-2", answer_map=(("x", "3"), ("a", "-2"), ("b", "-9"))
    )
    with pytest.raises(ValueError):
        structured_view.__wrapped__(broken)  # type: ignore[attr-defined]


def test_b_recorded_wrong_while_a_chain_is_right_stops_the_build() -> None:
    """저작 결함(진술값 ↔ 정답 기록 대조 절) — a 연쇄는 맞고 b 기록만 틀리면, 조건이 정한 b와 달라 멈춘다.

    a를 묻는 틀의 기록 오류는 연쇄 도출(`solution_steps`의 정답 도달 검사)이 먼저 잡으므로 이 절에 닿지
    않는다. b를 묻는 틀은 연쇄가 a에서 끝나고 b는 정의 등식 대입으로 계산되므로 이 절만이 잡는다
    (뮤테이션 M7이 살아남아 드러난 픽스처 공백 — 이 반례가 그 절을 밟는다).
    """
    frame = _find_b_quartic_frame(
        "t-quartic-b",
        "사차함수 f(x) = {f}{ga} x = {r}에서 {kind} {v}{veul} 가질 때, 상수 {p}의 값을 구하시오. "
        "(단, a, b는 상수이다.)",
        "seed",
        slot="mastery_check",
    )
    item = frame.build((3, 5))  # 참값 a = -4 · b = 5
    assert item is not None
    broken = dataclasses.replace(
        item, answer_text="6", answer_map=(("x", "3"), ("b", "6"), ("a", "-4"))
    )
    with pytest.raises(ValueError, match="저작 결함"):
        structured_view.__wrapped__(broken)  # type: ignore[attr-defined]


def test_a_setup_requires_structured_conditions() -> None:
    item = dataclasses.replace(_cubic_find_a(), structured_conditions=None)
    with pytest.raises(ValueError, match="구조화 조건이 함께"):
        structured_view.__wrapped__(item)  # type: ignore[attr-defined]


# ── ② B — 같은 종류 두 극값 중 큰/작은 값 ─────────────────────────────────
def _quartic_outer(ask: str, params: tuple[int, ...]) -> DiffItem:
    frame = _quartic_k_frame(
        "t-outer",
        "사차함수 f(x) = {f}{neun} x = {p}에서 극값을 갖는다. 두 {kind} 중 {size} 값을 구하시오. "
        "(단, k는 상수이다.)",
        "seed",
        slot="mastery_check",
        leads=(1, -1),
        pin="middle",
        ask=ask,
    )
    item = frame.build(params)
    assert item is not None
    return item


def test_b_smaller_of_two_minima_green_and_other_minimum_red() -> None:
    # 실 은행 레코드 wm-p3-diff-graphshape-276fae287f0e — f(x) = x^4 + 8x^3 + 10x^2 + kx + 6, 임계점 -4·-3·1.
    item = _quartic_outer("outer-smaller", (1, -4, -3, 1, 6))
    conditions, steps = _passes(item)
    assert steps[-2:] == ("x = 1", "y = -23")
    # 결함 주입 — 다른 극솟점(x = -4)을 고르면 그 선택이 조건에서 '틀림'으로 확정된다.
    wrong = _substituted(conditions, steps, "x", "-4")
    bad = (*steps[:-2], "x = -4", f"y = {wrong}")
    assert _judge(wrong, conditions, {"x": "-4", "k": "-48", "y": wrong}, bad)["C4"] == "fail"


def test_b_larger_of_two_maxima() -> None:
    # 실 은행 레코드 wm-p3-diff-graphshape-b52db165fb66의 꼴(최고차 -1 · 두 극댓값 중 큰 값).
    item = _quartic_outer("outer-larger", (-1, -2, -1, 3, 3))
    conditions, steps = _passes(item)
    assert any(c.endswith(">= 0") for c in conditions)


def test_b_without_rank_conditions_selection_is_not_proven() -> None:
    """비교 조건이 없으면 f'' 부호만으로는 두 극솟점이 다 남는다 — 아무것도 붙이지 않는다(P3-62 §B-5)."""
    item = _quartic_outer("outer-smaller", (1, -4, -3, 1, 6))
    conditions, _ = _passes(item)
    stripped = tuple(c for c in conditions if not (c.endswith("<= 0") or c.endswith(">= 0")))
    chain = structured_view(item)
    assert chain is not None
    base = chain[1][:-2]  # 근 목록까지
    assert final_statement_steps(base, conditions=stripped, target="y") is None


def test_b_tied_values_are_not_decided() -> None:
    """값이 같은 두 극솟값(복이차 x^4 - 2x^2 + 3)은 비교 조건으로도 하나가 안 된다 — 구조화 안 됨."""
    poly: Poly = ((4, 1), (2, -2), (0, 3))
    chain = (
        "Derivative(x**4 - 2*x**2 + 3, x).doit() = 0",
        "4*x**3 - 4*x = 0",
        "4*x*(x - 1)*(x + 1) = 0",
        "x = -1, x = 0, x = 1",
    )
    conditions = (
        "Derivative(x**4 - 2*x**2 + 3, x).doit() = 0",
        "12*x**2 - 4 > 0",
        *_value_rank_conds(poly, (-1, 1), pick="smaller"),
        "y = x**4 - 2*x**2 + 3",
    )
    assert final_statement_steps(chain, conditions=conditions, target="y") is None


def test_rank_conditions_take_no_answer() -> None:
    """정답 역산 금지 — 비교 조건 함수에 정답을 넘기는 자리가 없고, 결과는 후보 순서와 무관한 집합이다."""
    assert list(inspect.signature(_value_rank_conds).parameters) == ["poly", "points", "pick"]
    assert list(inspect.signature(_min_rank_conditions).parameters) == [
        "case",
        "sym",
        "domain",
        "var",
    ]
    poly: Poly = ((4, 1), (3, 8), (2, 10), (1, -48), (0, 6))
    forward = set(_value_rank_conds(poly, (-4, 1), pick="smaller"))
    backward = set(_value_rank_conds(poly, (1, -4), pick="smaller"))
    assert forward == backward and len(forward) == 2


# ── ③ C — 범위 최솟값 ────────────────────────────────────────────────────
def test_c_global_min_of_w_quartic_green_and_other_minimum_red() -> None:
    # 실 은행 레코드 wm-p3-diff-eqapp-0a7fc9c16151 — f(x) = 3x^4 + 8x^3 - 6x^2 - 24x + 24, 임계점 -2·-1·1.
    poly: Poly = ((4, 3), (3, 8), (2, -6), (1, -24), (0, 24))
    item = _min_item(
        slot="diagnostic",
        frame_id="t-w",
        text="사차함수의 최솟값을 구하시오.",
        case=_Min(poly, (-2, -1, 1), 1, 5),
        explanation="-",
        domain=None,
    )
    conditions, steps = _passes(item)
    assert steps[-2:] == ("x = 1", "y = 5")
    # 결함 주입 — 다른 극솟점 x = -2(값 13)를 최솟점으로 진술하면 FAIL.
    bad = (*steps[:-2], "x = -2", "y = 13")
    assert _judge("13", conditions, {"x": "-2", "y": "13"}, bad)["C4"] == "fail"


def test_c_min_on_half_line_boundary_critical_point_red() -> None:
    # 실 은행 레코드 wm-p3-diff-eqapp-7fef137243c5 — f(x) = 2x^3 - 6x^2 + 12, x ≥ 0, 임계점 0·2.
    poly: Poly = ((3, 2), (2, -6), (0, 12))
    item = _min_item(
        slot="applied",
        frame_id="t-half",
        text="x ≥ 0에서 f(x)의 최솟값을 구하시오.",
        case=_Min(poly, (0, 2), 2, 4),
        explanation="-",
        domain="x >= 0",
    )
    conditions, steps = _passes(item)
    assert "x >= 0" in conditions
    # 결함 주입 — 경계이자 임계점인 x = 0(값 12)을 고르면 FAIL.
    bad = (*steps[:-2], "x = 0", "y = 12")
    assert _judge("12", conditions, {"x": "0", "y": "12"}, bad)["C4"] == "fail"


def test_c_true_minimum_at_boundary_is_not_misstated() -> None:
    """범위 경계 비교 절 — 진짜 최솟값이 경계(x = 0)에 있는데 극솟점을 최솟값으로 적은 저작 결함을 막는다.

    f(x) = 2x^3 - 9x^2 + 12x + 1은 x ≥ 0에서 임계점 1·2(극대 6·극소 5)이지만 경계 f(0) = 1이 더 작다. 경계와의
    비교 조건이 있으면 조건을 만족하는 임계점이 없어 구조화가 멈춘다. 경계 비교가 빠지면 극소 x = 2가 '최솟값'
    으로 증명돼 틀린 기록(5)을 그대로 통과시킨다(뮤테이션 M6이 살아남아 드러난 픽스처 공백 — 앞 픽스처는 경계
    0이 마침 임계점이라 이 절을 밟지 않았다).
    """
    poly: Poly = ((3, 2), (2, -9), (1, 12), (0, 1))
    item = _min_item(
        slot="applied",
        frame_id="t-boundary",
        text="x ≥ 0에서 f(x)의 최솟값을 구하시오.",
        case=_Min(poly, (1, 2), 2, 5),  # 저작 결함 — 참 최솟값은 x = 0에서 1
        explanation="-",
        domain="x >= 0",
    )
    assert item.structured_conditions is not None
    assert any(c.endswith("- (1) <= 0") for c in item.structured_conditions)  # 경계 f(0) = 1 비교
    with pytest.raises(ValueError):
        structured_view.__wrapped__(item)  # type: ignore[attr-defined]


def test_c_single_inside_critical_point_keeps_previous_path() -> None:
    """범위 안 임계점이 하나뿐이면 도메인 부등식만으로 정해진다 — 비교 조건을 달지 않는다(종전 바이트)."""
    poly: Poly = ((3, 2), (2, 3), (1, -12), (0, 20))  # f'(x) = 6(x + 2)(x - 1) — x ≥ 0 안은 1뿐
    assert _min_rank_conditions(_Min(poly, (-2, 1), 1, 13), "2*x**3", "x >= 0", "x") is None
    # 범위 표기를 읽지 못하면 구조화하지 않는다(조용히 틀린 범위로 비교하지 않는다).
    assert _min_rank_conditions(_Min(poly, (-2, 0, 1), 1, 13), "2*x**3", "0 <= x", "x") is None


# ── ④ D — 평평한 임계점이 섞인 '극값' ──────────────────────────────────────
def test_d_flat_root_excluded_green_and_flat_pick_red() -> None:
    # 실 은행 레코드 wm-p3-diff-graphshape-fe747f2bd019 — f(x) = x^4 - 4x^3 - 1, f'(x) = 4x^2(x - 3).
    fn = _analyze(((4, 1), (3, -4), (0, -1)))
    assert fn is not None
    item = _judged_value_item(
        "diagnostic",
        "t-flat",
        "사차함수 f(x) = {f}에 대하여 방정식 f'(x) = 0의 실근은 {pins}이다. f(x)의 극값을 구하시오.",
        fn,
        word="any",
    )
    assert item is not None
    conditions, steps = _passes(item)
    assert "12*x**2 - 24*x != 0" in conditions
    assert steps[-2:] == ("x = 3", "y = -28")
    # 결함 주입 — 평평한 임계점 x = 0(값 -1)을 극값 자리로 고르면 FAIL.
    bad = (*steps[:-2], "x = 0", "y = -1")
    assert _judge("-1", conditions, {"x": "0", "y": "-1"}, bad)["C4"] == "fail"
