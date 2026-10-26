"""[12미적Ⅰ-02-01] 미분계수 결정론 문항 생성기 — P3-05 4단계(결정론·LLM 0).

개념: `H:12미적Ⅰ02-01`(미분계수의 뜻). 슬롯이 비어 있던 4칸(대표·기본·진단·숙련도 확인)만 채운다 —
응용·오개념 유발 칸은 기존 승인 문항이 이미 채웠다(`slot_assignment_rules.yaml` ·
P3-05 3단계). 그래서
`slots`를 4종으로 좁힌 부분집합 생성기다.

범위(이 개념에 한정)
--------------------
미분계수의 **정의**(차분몫의 극한)와 그 해석(접선의 기울기·순간변화율)만 다룬다. 거듭제곱·합·곱의
미분법으로 도함수를 능숙하게 구하는 일은 `[12미적Ⅰ-02-03]`·`[12미적Ⅰ-02-04]`의 몫이다.
다만 정의로 구한
값과 규칙으로 구한 값은 같으므로 정답은 항상 `sympy.diff`로 계산하고, 문면이 정의(극한)를 묻는다.
극한 기호(→)는 신규 유니코드 글리프라 쓰지 않고 말로 쓴다("h가 0에 한없이 가까워질 때").

슬롯 × 틀(frame)
----------------
  · 대표(2.0) — 정의 그대로: h-꼴 차분몫 · x-꼴 차분몫 · 평균변화율의 극한 · 순간변화율.
  · 기본(2.0) — 값을 구한다: 미분계수 f'(a) · 접선의 기울기(곡선) · 접선의 기울기(점이 주어짐) ·
    변수가 t인 함수.
  · 진단(2.5) — 차분몫의 **증분과 분모의 관계**만 가려낸다:
    (f(a+2h) - f(a)) / h = 2f'(a) 처럼 정의와
    닮았지만 값이 달라지는 꼴, 그리고 (f(a+3h) - f(a)) / (3h)·(f(a+h) - f(a-h)) / (2h) 처럼 정의로
    되돌아오는 꼴. 한 틀은 한 가지 관계만 묻는다.
  · 숙련도 확인(3.5) — 미지 상수를 거쳐 값을 구한다: 극한값이 주어진 함수의 계수 · 증분이 스케일된
    극한값으로 계수 · 평균변화율과 미분계수가 같아지는 점.

검산 재료의 형식 제약
---------------------
Tier1은 미분 평가를 다른 연산과 섞지 못하고(`2*D = y` 불가), 섀도 채점은 자유기호가 정확히
하나일 것을 요구한다. 그래서 스케일은 *합쳐 한 번에 미분*(`Derivative(2*(식), x)`)으로
표현하고, 모든 문항은 미지수를
정확히 하나만 둔다.

문제유형 정직성
--------------
값 계산은 `ptype.evaluate-expression`, 미지 상수를 구하는 숙련도 문항은
`ptype.solve-for-unknown`.
"""

from __future__ import annotations

from typing import ClassVar, Final

from whymath_backend.l3.equivalent.p3_diff_expr import (
    Poly,
    derivative_of,
    eval_at,
    poly_to_sympy_str,
    render_poly,
    with_wa_gwa,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    DiffItem,
    Frame,
    P3DiffSlotGenerator,
    SlotId,
    answer_format_for,
    round_robin_items,
    seeded_order,
)

__all__ = ["P3DiffDifferentialCoefficientGenerator"]

_EVAL: Final = "ptype.evaluate-expression"
_SOLVE: Final = "ptype.solve-for-unknown"


# ──────────────────────────────────────────────────────────────────────────
# 공용 재료
# ──────────────────────────────────────────────────────────────────────────
def _grid(seed: str, *axes: tuple[int, ...]) -> tuple[tuple[object, ...], ...]:
    combos: list[tuple[object, ...]] = [()]
    for axis in axes:
        combos = [(*c, v) for c in combos for v in axis]
    return tuple(seeded_order(seed, combos))


def _poly(*terms: tuple[int, int]) -> Poly:
    return tuple(sorted(((e, c) for e, c in terms if c != 0), reverse=True))


def _quadratic(a: int, b: int, c: int) -> Poly:
    return _poly((2, a), (1, b), (0, c))


def _cubic(a: int, b: int, c: int, d: int) -> Poly:
    return _poly((3, a), (2, b), (1, c), (0, d))


def _plus(var: str, n: int) -> str:
    """`var + n`(n이 음수면 `var - |n|`) — '--' 표기를 만들지 않는다."""
    return f"{var} + {n}" if n > 0 else f"{var} - {-n}"


def _arg(n: int, step: str) -> str:
    """f의 인자 `n + step`(n이 0이면 step만) — `f(-2 + h)`·`f(1 + 2h)`."""
    if n == 0:
        return step
    return f"{n} + {step}"


def _sym(poly: Poly, var: str = "x") -> str:
    return poly_to_sympy_str(poly, var)


def _d_at(poly: Poly, point: int, var: str = "x") -> str:
    """`Derivative(식, var).doit().subs(var, 점)` — 미분 평가 1회(맨몸)."""
    return f"Derivative({_sym(poly, var)}, {var}).doit().subs({var}, {point})"


def _value_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    poly: Poly,
    point: int,
    lead: str,
    var: str = "x",
    fn: str = "f",
    scale: int = 1,
    divisor: int = 1,
    ptype: str = _EVAL,
) -> DiffItem:
    """`scale·f'(point) / divisor`를 묻는 문항 — 정답은 SymPy 도함수의 값에서 읽는다."""
    d = derivative_of(poly, var)
    base = eval_at(d, point, var)
    numerator = scale * base
    if numerator % divisor:
        raise ValueError(f"{frame_id}: 정수 답이 아니다({numerator}/{divisor})")
    value = numerator // divisor
    if divisor != 1:
        raise ValueError(f"{frame_id}: 분모 스케일은 아직 쓰지 않는다")
    if scale == 1:
        condition = _d_at(poly, point, var) + " = y"
        closing = f"{fn}'({point}) = {value}이다."
    else:
        # 스케일은 *합쳐 한 번에 미분*한다(Tier1은 미분 평가를 다른 연산과 섞지 못한다).
        condition = (
            f"Derivative({scale}*({_sym(poly, var)}), {var}).doit().subs({var}, {point}) = y"
        )
        closing = f"{fn}'({point}) = {base}이고, 구하는 값은 {scale}f'({point}) = {value}이다."
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(value),
        explanation=f"{lead} {fn}'({var}) = {render_poly(d, var)}이므로 {closing}",
        conditions=condition,
        answer_map=(("y", str(value)),),
        problem_type_code=ptype,
        answer_format=answer_format_for(str(value)),
    )


# 함수 풀: 이차·삼차 정수 계수 다항식. 상수항 0·일차항 0도 섞어 정의에 의존하는 풀이를 막는다.
_QUADRATIC_POOL: Final = tuple(
    _quadratic(a, b, c)
    for a in (1, 2, 3, -1, -2)
    for b in (-5, -3, -2, 1, 2, 4, 6)
    for c in (-4, 0, 3, 5)
)
_CUBIC_POOL: Final = tuple(
    _cubic(a, b, c, d)
    for a in (1, 2, -1)
    for b in (-3, 0, 2, 3)
    for c in (-6, -2, 1, 4)
    for d in (-2, 0, 5)
)
# 앞에서부터 소비되므로 부호가 번갈아 나오게 둔다(앞 3개만 쓰는 틀도 음수 점에 몰리지 않는다).
_POINTS: Final = (2, -1, 3, -2, 1, -3)


def _fn_points(seed: str, pool: tuple[Poly, ...]) -> tuple[tuple[object, ...], ...]:
    """(함수, 점) 후보열 — 함수 풀을 시드 순서로 섞어 점을 번갈아 붙인다."""
    ordered = seeded_order(seed, pool)
    return tuple((p, _POINTS[i % len(_POINTS)]) for i, p in enumerate(ordered))


def _pt(p: tuple[object, ...]) -> tuple[Poly, int]:
    poly, point = p
    assert isinstance(poly, tuple) and isinstance(point, int)
    return poly, point


# ──────────────────────────────────────────────────────────────────────────
# 대표(representative) — 정의 그대로
# ──────────────────────────────────────────────────────────────────────────
_REP_LEAD: Final = "미분계수의 정의에 따라 구하는 값은 f'({a})이다."


def _rep_frames() -> list[Frame]:
    def h_form(p: tuple[object, ...]) -> DiffItem | None:
        poly, a = _pt(p)
        return _value_item(
            slot="representative",
            frame_id="rep-difference-quotient-in-h",
            text=(
                f"함수 f(x) = {render_poly(poly)}에 대하여 h가 0에 한없이 가까워질 때 "
                f"(f({_arg(a, 'h')}) - f({a})) / h의 극한값을 구하시오."
            ),
            poly=poly,
            point=a,
            lead=_REP_LEAD.format(a=a),
        )

    def x_form(p: tuple[object, ...]) -> DiffItem | None:
        poly, a = _pt(p)
        return _value_item(
            slot="representative",
            frame_id="rep-difference-quotient-in-x",
            text=(
                f"함수 f(x) = {render_poly(poly)}에 대하여 x가 {a}에 한없이 가까워질 때 "
                f"(f(x) - f({a})) / ({_plus('x', -a)})의 극한값을 구하시오."
            ),
            poly=poly,
            point=a,
            lead=_REP_LEAD.format(a=a),
        )

    def average_rate(p: tuple[object, ...]) -> DiffItem | None:
        poly, a = _pt(p)
        return _value_item(
            slot="representative",
            frame_id="rep-average-rate-limit",
            text=(
                f"함수 f(x) = {render_poly(poly)}에서 x의 값이 {a}에서 {_arg(a, 'h')}까지 "
                "변할 때의 "
                "평균변화율을 구한 뒤, h가 0에 한없이 가까워질 때의 극한값을 구하시오."
            ),
            poly=poly,
            point=a,
            lead=_REP_LEAD.format(a=a),
        )

    def instantaneous(p: tuple[object, ...]) -> DiffItem | None:
        poly, a = _pt(p)
        d = derivative_of(poly)
        value = eval_at(d, a)
        return DiffItem(
            slot="representative",
            frame_id="rep-instantaneous-rate",
            question_text=f"함수 y = {render_poly(poly)}에서 x = {a}일 때의 순간변화율을 구하시오.",
            answer_text=str(value),
            explanation=(
                f"x = {a}에서의 순간변화율은 미분계수 {with_wa_gwa("f'(" + str(a) + ")")} 같다. "
                f"y' = {render_poly(d)}이므로 x = {a}일 때의 순간변화율은 {value}이다."
            ),
            conditions=_d_at(poly, a) + " = y",
            answer_map=(("y", str(value)),),
            problem_type_code=_EVAL,
            answer_format=answer_format_for(str(value)),
        )

    return [
        Frame(
            "rep-difference-quotient-in-h",
            _fn_points("p3c:rep-h", _QUADRATIC_POOL + _CUBIC_POOL),
            h_form,
        ),
        Frame(
            "rep-difference-quotient-in-x",
            _fn_points("p3c:rep-x", _QUADRATIC_POOL + _CUBIC_POOL),
            x_form,
        ),
        Frame(
            "rep-average-rate-limit",
            _fn_points("p3c:rep-avg", _QUADRATIC_POOL + _CUBIC_POOL),
            average_rate,
        ),
        Frame(
            "rep-instantaneous-rate",
            _fn_points("p3c:rep-inst", _QUADRATIC_POOL + _CUBIC_POOL),
            instantaneous,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 기본(basic) — 값을 구한다
# ──────────────────────────────────────────────────────────────────────────
def _basic_frames() -> list[Frame]:
    def coefficient(p: tuple[object, ...]) -> DiffItem | None:
        poly, a = _pt(p)
        return _value_item(
            slot="basic",
            frame_id="basic-differential-coefficient",
            text=(
                f"함수 f(x) = {render_poly(poly)}에 대하여 x = {a}에서의 미분계수 "
                f"f'({a})의 값을 구하시오."
            ),
            poly=poly,
            point=a,
            lead="도함수를 구하면",
        )

    def tangent_slope(p: tuple[object, ...]) -> DiffItem | None:
        poly, a = _pt(p)
        d = derivative_of(poly)
        value = eval_at(d, a)
        return DiffItem(
            slot="basic",
            frame_id="basic-tangent-slope-of-curve",
            question_text=(
                f"곡선 y = {render_poly(poly)} 위의 x좌표가 {a}인 점에서의 "
                "접선의 기울기를 구하시오."
            ),
            answer_text=str(value),
            explanation=(
                "접선의 기울기는 그 점에서의 미분계수와 같다. "
                f"y' = {render_poly(d)}이므로 x = {a}에서의 접선의 기울기는 {value}이다."
            ),
            conditions=_d_at(poly, a) + " = y",
            answer_map=(("y", str(value)),),
            problem_type_code=_EVAL,
            answer_format=answer_format_for(str(value)),
        )

    def tangent_slope_at_point(p: tuple[object, ...]) -> DiffItem | None:
        poly, a = _pt(p)
        d = derivative_of(poly)
        value = eval_at(d, a)
        y0 = eval_at(poly, a)
        return DiffItem(
            slot="basic",
            frame_id="basic-tangent-slope-at-given-point",
            question_text=(
                f"곡선 y = {render_poly(poly)} 위의 점 ({a}, {y0})에서의 접선의 기울기를 구하시오."
            ),
            answer_text=str(value),
            explanation=(
                "접선의 기울기는 그 점에서의 미분계수와 같다. "
                f"y' = {render_poly(d)}이므로 점 ({a}, {y0})에서의 접선의 기울기는 {value}이다."
            ),
            conditions=_d_at(poly, a) + " = y",
            answer_map=(("y", str(value)),),
            problem_type_code=_EVAL,
            answer_format=answer_format_for(str(value)),
        )

    def in_t(p: tuple[object, ...]) -> DiffItem | None:
        poly, a = _pt(p)
        return _value_item(
            slot="basic",
            frame_id="basic-differential-coefficient-in-t",
            text=f"함수 g(t) = {render_poly(poly, 't')}에 대하여 g'({a})의 값을 구하시오.",
            poly=poly,
            point=a,
            lead="도함수를 구하면",
            var="t",
            fn="g",
        )

    return [
        Frame(
            "basic-differential-coefficient",
            _fn_points("p3c:basic-coef", _QUADRATIC_POOL),
            coefficient,
        ),
        Frame(
            "basic-tangent-slope-of-curve",
            _fn_points("p3c:basic-curve", _CUBIC_POOL),
            tangent_slope,
        ),
        Frame(
            "basic-tangent-slope-at-given-point",
            _fn_points("p3c:basic-point", _QUADRATIC_POOL + _CUBIC_POOL),
            tangent_slope_at_point,
        ),
        Frame("basic-differential-coefficient-in-t", _fn_points("p3c:basic-t", _CUBIC_POOL), in_t),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 진단(diagnostic) — 증분과 분모의 관계 하나만 가려낸다
# ──────────────────────────────────────────────────────────────────────────
def _diag_frames() -> list[Frame]:
    """증분과 분모의 관계 하나만 묻는 4틀 — 해설이 *왜 그 배수가 되는지*를 먼저 말한다."""

    def build_frame(
        frame_id: str, scale: int, numerator: str, denominator: str, reason: str
    ) -> Frame:
        def build(p: tuple[object, ...]) -> DiffItem | None:
            poly, a = _pt(p)
            minus = f"{a} - h" if a != 0 else "-h"
            text_numerator = numerator.format(
                a=a, p1=_arg(a, "h"), p2=_arg(a, "2h"), p3=_arg(a, "3h"), m1=minus
            )
            return _value_item(
                slot="diagnostic",
                frame_id=frame_id,
                text=(
                    f"함수 f(x) = {render_poly(poly)}에 대하여 h가 0에 한없이 가까워질 때 "
                    f"{text_numerator} / {denominator}의 극한값을 구하시오."
                ),
                poly=poly,
                point=a,
                lead=reason.format(
                    a=a, p1=_arg(a, "h"), p2=_arg(a, "2h"), p3=_arg(a, "3h"), m1=minus
                ),
                scale=scale,
            )

        return Frame(frame_id, _fn_points(f"p3c:{frame_id}", _QUADRATIC_POOL + _CUBIC_POOL), build)

    return [
        build_frame(
            "diag-increment-doubled-over-h",
            2,
            "(f({p2}) - f({a}))",
            "h",
            "분자의 증분은 2h인데 분모는 h이므로, 이 식은 정의 꼴 (f({p2}) - f({a})) / (2h)의 "
            "2배이다. 따라서 극한값은 f'({a})의 2배이다.",
        ),
        build_frame(
            "diag-increment-tripled-over-same",
            1,
            "(f({p3}) - f({a}))",
            "(3h)",
            "분자의 증분 3h와 분모 3h가 같으므로 정의 꼴이다. 따라서 극한값은 f'({a})이다.",
        ),
        build_frame(
            "diag-symmetric-over-2h",
            1,
            "(f({p1}) - f({m1}))",
            "(2h)",
            "f({p1}) - f({m1}) = (f({p1}) - f({a})) + (f({a}) - f({m1}))이므로 이 식은 두 차분몫 "
            "(f({p1}) - f({a})) / h와 (f({m1}) - f({a})) / (-h)의 평균이고, 두 차분몫이 모두 "
            "f'({a})에 한없이 가까워진다. 따라서 극한값은 f'({a})이다.",
        ),
        build_frame(
            "diag-symmetric-over-h",
            2,
            "(f({p1}) - f({m1}))",
            "h",
            "f({p1}) - f({m1}) = (f({p1}) - f({a})) + (f({a}) - f({m1}))이므로 이 식은 두 차분몫 "
            "(f({p1}) - f({a})) / h와 (f({m1}) - f({a})) / (-h)의 합이고, 두 차분몫이 모두 "
            "f'({a})에 한없이 가까워진다. 따라서 극한값은 f'({a})의 2배이다.",
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 숙련도 확인(mastery_check) — 미지 상수를 거쳐 값을 구한다
# ──────────────────────────────────────────────────────────────────────────
def _mastery_frames() -> list[Frame]:
    def with_param(c3: int, c1: int) -> str:
        """`c3x^3 + ax^2 + c1x` 표기(a는 미지 상수) — 계수 1·0 표기를 만들지 않는다."""
        out = render_poly(((3, c3),)) + " + ax^2"
        if c1:
            out += (" + " if c1 > 0 else " - ") + render_poly(((1, abs(c1)),))
        return out

    def with_param_sym(c3: int, c1: int) -> str:
        return f"{c3}*x**3 + a*x**2 + {c1}*x" if c1 >= 0 else f"{c3}*x**3 + a*x**2 - {-c1}*x"

    def limit_value(p: tuple[object, ...]) -> DiffItem | None:
        c3, c1, point, a_true = (int(str(v)) for v in p)
        value = 3 * c3 * point**2 + 2 * a_true * point + c1
        return DiffItem(
            slot="mastery_check",
            frame_id="mastery-coefficient-from-limit-value",
            question_text=(
                f"함수 f(x) = {with_param(c3, c1)} (a는 상수)에 대하여 h가 0에 한없이 가까워질 때 "
                f"(f({_arg(point, 'h')}) - f({point})) / h의 극한값이 {value}이다. "
                "상수 a의 값을 구하시오."
            ),
            answer_text=str(a_true),
            explanation=(
                f"구하는 극한값은 f'({point})이다. f'(x) = {3 * c3}x^2 + 2ax"
                + (f" {'+' if c1 > 0 else '-'} {abs(c1)}" if c1 else "")
                + f"이므로 f'({point}) = {3 * c3 * point**2} + {2 * point}a"
                + (f" {'+' if c1 > 0 else '-'} {abs(c1)}" if c1 else "")
                + f" = {value}이고, a = {a_true}이다."
            ),
            conditions=(
                f"Derivative({with_param_sym(c3, c1)}, x).doit().subs(x, {point}) = {value}"
            ),
            answer_map=(("a", str(a_true)),),
            problem_type_code=_SOLVE,
            answer_format=answer_format_for(str(a_true)),
        )

    def scaled_limit(p: tuple[object, ...]) -> DiffItem | None:
        c3, c1, point, a_true, m = (int(str(v)) for v in p)
        value = m * (3 * c3 * point**2 + 2 * a_true * point + c1)
        return DiffItem(
            slot="mastery_check",
            frame_id="mastery-coefficient-from-scaled-limit",
            question_text=(
                f"함수 f(x) = {with_param(c3, c1)} (a는 상수)에 대하여 h가 0에 한없이 가까워질 때 "
                f"(f({_arg(point, f'{m}h')}) - f({point})) / h의 극한값이 {value}이다. "
                "상수 a의 값을 구하시오."
            ),
            answer_text=str(a_true),
            explanation=(
                f"증분이 {m}h이므로 구하는 극한값은 {m}f'({point})이다. f'(x) = {3 * c3}x^2 + 2ax"
                + (f" {'+' if c1 > 0 else '-'} {abs(c1)}" if c1 else "")
                + f"이므로 {m}f'({point}) = {m}({3 * c3 * point**2} + {2 * point}a"
                + (f" {'+' if c1 > 0 else '-'} {abs(c1)}" if c1 else "")
                + f") = {value}이고, a = {a_true}이다."
            ),
            conditions=(
                f"Derivative({m}*({with_param_sym(c3, c1)}), x).doit().subs(x, {point}) = {value}"
            ),
            answer_map=(("a", str(a_true)),),
            problem_type_code=_SOLVE,
            answer_format=answer_format_for(str(a_true)),
        )

    def average_equals_instantaneous(p: tuple[object, ...]) -> DiffItem | None:
        """평균변화율 = 미분계수에서 미지 상수 a를 구한다 — c1 항은 양변에서 사라진다
        (선형 항의 평균변화율은 어느 점의 미분계수와도 같으므로). a가 정수이고 구간의 중점에서의
        미분계수가 아닐 때만 낸다."""
        c3, c1, lo, hi, r = (int(str(v)) for v in p)
        slope_gap = hi + lo - 2 * r  # 중점이면 0 — a가 사라져 방정식이 성립하지 않는다
        if slope_gap == 0:
            return None
        numerator = c3 * (3 * r * r - hi * hi - hi * lo - lo * lo)
        if numerator % slope_gap:
            return None
        a_true = numerator // slope_gap
        if a_true == 0:
            return None
        poly_text = with_param(c3, c1)
        avg_const = c3 * (hi * hi + hi * lo + lo * lo) + c1
        avg_expr = render_poly(((1, hi + lo), (0, avg_const)), "a")
        slope_const = 3 * c3 * r * r + c1
        slope_expr = render_poly(((1, 2 * r), (0, slope_const)), "a")
        f_hi = f"({c3 * hi**3 + c1 * hi} + {hi * hi}*a)"
        f_lo = f"({c3 * lo**3 + c1 * lo} + {lo * lo}*a)"
        return DiffItem(
            slot="mastery_check",
            frame_id="mastery-average-rate-equals-coefficient",
            question_text=(
                f"함수 f(x) = {poly_text} (a는 상수)에서 x의 값이 {lo}에서 {hi}까지 변할 때의 "
                f"평균변화율이 x = {r}에서의 미분계수와 같다. 상수 a의 값을 구하시오."
            ),
            answer_text=str(a_true),
            explanation=(
                f"평균변화율은 (f({hi}) - f({lo})) / {hi - lo} = {avg_expr}이다. "
                f"f'(x) = {3 * c3}x^2 + 2ax"
                + (f" {'+' if c1 > 0 else '-'} {abs(c1)}" if c1 else "")
                + f"이므로 f'({r}) = {slope_expr}이다. "
                f"두 값이 같으므로 {avg_expr} = {slope_expr}에서 a = {a_true}이다."
            ),
            conditions=(
                f"Derivative({with_param_sym(c3, c1)}, x).doit().subs(x, {r}) = "
                f"({f_hi} - {f_lo})/{hi - lo}"
            ),
            answer_map=(("a", str(a_true)),),
            problem_type_code=_SOLVE,
            answer_format=answer_format_for(str(a_true)),
        )

    limit_params = _grid("p3c:mastery-limit", (1, 2, -1), (-3, 2, 5), (1, 2, 3), (-3, -1, 2, 3, 4))
    scaled_params = _grid("p3c:mastery-scaled", (1, 2), (-2, 3, 4), (1, 2), (-2, 1, 3, 5), (2, 3))
    # 일차항 계수 c1은 양변에서 사라져 답을 바꾸지 않는다 — c1만 다른 문항은 같은 문제의 복제라
    # (c3, 구간, 점) 조합마다 한 건만 남긴다(PR #1639 의 중복 방지와 같은 취지).
    avg_unique: dict[tuple[object, ...], tuple[object, ...]] = {}
    for params in _grid(
        "p3c:mastery-avg",
        (1, 2, -1),
        (-3, 2, 4),
        (-1, 0, 1),
        (2, 3, 4),
        (-1, 0, 1, 4, 5),
    ):
        avg_unique.setdefault((params[0], *params[2:]), params)
    avg_params = tuple(avg_unique.values())
    return [
        Frame("mastery-coefficient-from-limit-value", limit_params, limit_value),
        Frame("mastery-coefficient-from-scaled-limit", scaled_params, scaled_limit),
        Frame(
            "mastery-average-rate-equals-coefficient",
            avg_params,
            average_equals_instantaneous,
        ),
    ]


_SLOT_FRAMES = {
    "representative": _rep_frames,
    "basic": _basic_frames,
    "diagnostic": _diag_frames,
    "mastery_check": _mastery_frames,
}


class P3DiffDifferentialCoefficientGenerator(P3DiffSlotGenerator):
    """[12미적Ⅰ-02-01] 미분계수 — 빈 4칸(대표·기본·진단·숙련도 확인) 결정론 생성기."""

    standard_code: ClassVar[str] = "[12미적Ⅰ-02-01]"
    concept_src_id: ClassVar[str] = "H:12미적Ⅰ02-01"
    unit_code: ClassVar[str] = "P3-CALC1-DIFF-COEFFICIENT"
    slug_prefix: ClassVar[str] = "wm-p3-diff-coefficient"
    slots: ClassVar[tuple[SlotId, ...]] = (
        "representative",
        "basic",
        "diagnostic",
        "mastery_check",
    )
    slot_difficulty: ClassVar[dict[str, float]] = {
        "representative": 2.0,
        "basic": 2.0,
        "diagnostic": 2.5,
        "mastery_check": 3.5,
    }
    slot_count: ClassVar[int] = 12

    @classmethod
    def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
        return round_robin_items(
            _SLOT_FRAMES[slot](),
            cls.slot_count,
            claimed=claimed,
            standard_code=cls.standard_code,
        )
