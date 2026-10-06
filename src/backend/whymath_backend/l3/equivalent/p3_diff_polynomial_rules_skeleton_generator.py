"""[12미적Ⅰ-02-04] 미분법과 다항함수의 도함수 결정론 문항 생성기 — P3-03(결정론·LLM 0).

개념: `H:12미적Ⅰ02-04`(`math.calculus.mibunbeopgwa-dahanghamsuui-dohamsu`). 핵심 오개념: M0672 ←
kebab `product-rule-naive`(곱의 미분을 '각각 미분한 곱'으로 한다 — 크로스링크 직접매핑 승인분).
신규 오개념 id를 만들지 않는다.

범위: 함수의 실수배·합·차·곱의 미분법과 다항함수의 도함수·미분계수. (`x^n` 자체의 도함수는
`[12미적Ⅰ-02-03]`의 몫이라 여기서는 *이미 아는 것*으로 쓴다.) 접선·증감·극값은 다른 개념이다.

슬롯 6종 × 틀(frame): 대표(식 답)·기본(값)·응용(미정계수·미지수 구하기)·오개념 유발(객관식 — 곱의
미분법 오류)·진단·숙련도 확인. 파라미터만 다른 문항은 같은 문면 골격을 공유하므로 개념당 고유
골격 30 이상은 *틀의 수*로 확보한다.

문제유형 정직성: 이 개념의 명세 스킬(`equation-rearrangement`·`polynomial-arithmetic`)은
`ptype.evaluate-expression`(다항식 연산)·`ptype.solve-for-unknown`(방정식 정리) 둘과 겹친다 —
값·식 도출은 전자, 미정계수·미지수 결정은 후자를 *실제 요구 행동대로* 단다.

검산 재료의 형식 제약(중요)
--------------------------
Tier1(`l3/verify_answer`)은 미분 평가(`Derivative(...).doit().subs(...)`)가 든 변을 다른 연산과 섞지
못하고(`D + 1 = y`·`D1 + D2 = y` 모두 unverifiable — 2026-10-06 실측), 섀도 채점 경로는 검산 조건의
자유기호가 **정확히 하나이고 answer_map의 유일한 키와 같을 것**을 요구한다(NLP-09). 그래서 이 파일의
모든 문항은 미분 평가를 조건당 1회·맨몸으로 쓰고(여러 함수의 값의 합·차는 `Derivative(F + G, x)`처럼
*합쳐서 한 번에* 미분), 미지수를 정확히 1개만 둔다. 두 번째 미지수가 필요한 문항(미정계수 a, b)은
**데이터(미분계수 값)를 SymPy로 구한 뒤** 풀려는 미지수 하나만 기호로 남기고 나머지는
상수로 대입한다.

**함수식을 답으로 하는 문항은 만들지 않는다**(`y = 도함수` 검산 조건은 자유기호가 x와 y 둘이라
위 계약 밖이다 — 현 코퍼스 13,520블록이 전부 스칼라 답이다). 도함수는 *상수항(= f'(0))*·
*모든 계수의 합(= f'(1))*처럼 한 점의 값으로 읽어 묻는다.

정답: 모든 문항의 정답은 `sympy.diff`로 계산한다. 객관식 오답은 곱의 미분법 오류가 만드는 식
(`f'g'` — 오개념 연결)과 한 항만 미분한 식(`f'g`·`fg'` — 미매핑 필러)으로 구성한다.
"""

from __future__ import annotations

import random
from typing import ClassVar, Final

import sympy

from whymath_backend.l3.equivalent.p3_diff_expr import (
    Poly,
    derivative_of,
    eval_at,
    poly_from_sympy,
    poly_to_sympy,
    poly_to_sympy_str,
    product_to_sympy_str,
    render_poly,
    render_product,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    ChoiceEntry,
    DiffItem,
    Frame,
    P3DiffSlotGenerator,
    build_choices,
    round_robin_items,
    seeded_order,
)
from whymath_backend.lang.josa import eul_reul
from whymath_backend.schema.enums import AnswerFormat

__all__ = ["P3DiffPolynomialRulesGenerator"]

_KEBAB: Final = "product-rule-naive"
_EVAL: Final = "ptype.evaluate-expression"
_SOLVE: Final = "ptype.solve-for-unknown"
_X = sympy.Symbol("x")


def _fmt(value: int) -> AnswerFormat:
    return AnswerFormat.자연수 if value > 0 else AnswerFormat.실수


def _rand_poly(rng: random.Random, degree: int, *, terms_skip: float = 0.25) -> Poly:
    """차수 `degree`의 정수 계수 다항식 — 선두 계수 ±1..4·나머지 ±1..7(일부 항 생략)."""
    out: list[tuple[int, int]] = []
    for exp in range(degree, -1, -1):
        if exp == degree:
            coef = rng.choice([v for v in range(-4, 5) if v])
        else:
            if rng.random() < terms_skip:
                continue
            coef = rng.choice([v for v in range(-7, 8) if v])
        out.append((exp, coef))
    return tuple(out)


def _pool(seed: str, count: int, degrees: tuple[int, ...]) -> tuple[Poly, ...]:
    """결정론 다항식 풀 — 차수를 돌려 가며 중복 없이 `count`개."""
    rng = random.Random(seed)
    seen: set[Poly] = set()
    out: list[Poly] = []
    guard = 0
    while len(out) < count and guard < count * 200:
        guard += 1
        poly = _rand_poly(rng, degrees[len(out) % len(degrees)])
        if poly in seen or len(poly) < 2:
            continue
        seen.add(poly)
        out.append(poly)
    return tuple(out)


def _linear_pool(seed: str, count: int) -> tuple[Poly, ...]:
    """일차식 풀 — (px + q), p·q 모두 0이 아니다."""
    rng = random.Random(seed)
    seen: set[Poly] = set()
    out: list[Poly] = []
    guard = 0
    while len(out) < count and guard < count * 200:
        guard += 1
        p = rng.choice([v for v in range(-4, 5) if v])
        q = rng.choice([v for v in range(-6, 7) if v])
        poly: Poly = ((1, p), (0, q))
        if poly in seen:
            continue
        seen.add(poly)
        out.append(poly)
    return tuple(out)


def _prod(factors: tuple[Poly, ...]) -> Poly:
    """곱을 SymPy로 전개한 다항식."""
    expr = sympy.Integer(1)
    for factor in factors:
        expr = expr * poly_to_sympy(factor)
    return poly_from_sympy(sympy.expand(expr))


def _deriv_sym(expr_str: str, point: str) -> str:
    return f"Derivative({expr_str}, x).doit().subs(x, {point})"


def _grid(seed: str, *axes: tuple[object, ...]) -> tuple[tuple[object, ...], ...]:
    combos: list[tuple[object, ...]] = [()]
    for axis in axes:
        combos = [(*c, v) for c in combos for v in axis]
    return tuple(seeded_order(seed, combos))


_POINTS: Final = (-3, -2, -1, 1, 2, 3)
_POLYS_A: Final = _pool("p3-poly:A", 40, (2, 3, 4))
_POLYS_B: Final = _pool("p3-poly:B", 30, (2, 3))
_LINEARS: Final = _linear_pool("p3-poly:L", 24)
_QUADS: Final = _pool("p3-poly:Q", 24, (2,))


def _poly(p: object) -> Poly:
    assert isinstance(p, tuple)
    return p


def _int(p: object) -> int:
    return int(str(p))


# ──────────────────────────────────────────────────────────────────────────
# 대표(representative) — 도함수를 식으로 구한다
# ──────────────────────────────────────────────────────────────────────────
def _read_item(
    *,
    frame_id: str,
    text: str,
    function: Poly,
    shown: str,
    sym: str,
    point: int,
    var: str = "x",
    what: str,
    note: str,
) -> DiffItem | None:
    """도함수의 한 값(상수항 = f'(0) · 계수의 합 = f'(1))을 스칼라로 묻는 대표 문항."""
    d = derivative_of(function, var)
    value = eval_at(d, point, var)
    if point == 0 and value == 0:
        return None  # 상수항이 0이면 묻는 의미가 없다
    return DiffItem(
        slot="representative",
        frame_id=frame_id,
        question_text=text,
        answer_text=str(value),
        explanation=f"{note} {shown}의 도함수는 {render_poly(d, var)}이므로 {what}은 {value}이다.",
        conditions=f"Derivative({sym}, {var}).doit().subs({var}, {point}) = y",
        answer_map=(("y", str(value)),),
        problem_type_code=_EVAL,
        answer_format=_fmt(value),
    )


def _rep_frames() -> list[Frame]:
    def r1(p: tuple[object, ...]) -> DiffItem | None:
        f = _poly(p[0])
        return _read_item(
            frame_id="rep-constant-term-of-derivative",
            text=f"함수 f(x) = {render_poly(f)}의 도함수 f'(x)의 상수항을 구하시오.",
            function=f,
            shown=render_poly(f),
            sym=poly_to_sympy_str(f),
            point=0,
            what="상수항",
            note="항별로 미분해 더한다.",
        )

    def r2(p: tuple[object, ...]) -> DiffItem | None:
        f = _poly(p[0])
        return _read_item(
            frame_id="rep-sum-of-coefficients-of-derivative",
            text=f"y = {render_poly(f)}일 때, dy/dx의 모든 계수의 합을 구하시오.",
            function=f,
            shown=render_poly(f),
            sym=poly_to_sympy_str(f),
            point=1,
            what="모든 계수의 합",
            note="합의 미분법을 쓴다.",
        )

    def r3(p: tuple[object, ...]) -> DiffItem | None:
        f = _poly(p[0])
        text_f = render_poly(f, "t")
        return _read_item(
            frame_id="rep-constant-term-in-t",
            text=(
                f"함수 g(t) = {text_f}{eul_reul(text_f)} t에 대하여 미분한 도함수 g'(t)의 "
                "상수항을 구하시오."
            ),
            function=f,
            shown=text_f,
            sym=poly_to_sympy_str(f, "t"),
            point=0,
            var="t",
            what="상수항",
            note="항별로 미분해 더한다.",
        )

    def r4(p: tuple[object, ...]) -> DiffItem | None:
        c, n = _int(p[0]), _int(p[1])
        f: Poly = ((n, c),)
        d = derivative_of(f)
        ((m_exp, k_coef),) = d
        return DiffItem(
            slot="representative",
            frame_id="rep-constant-multiple-coefficient",
            question_text=(
                f"함수 f(x) = {render_poly(f)}의 도함수 f'(x)를 kx^m (k, m은 상수) 꼴로 "
                "나타낼 때, k의 값을 구하시오."
            ),
            answer_text=str(k_coef),
            explanation=(
                f"상수배의 미분법에 따라 도함수는 {render_poly(d)}이므로 k는 {k_coef}이다."
            ),
            conditions=f"{_deriv_sym(poly_to_sympy_str(f), '2')} = k*2**{m_exp}",
            answer_map=(("k", str(k_coef)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(k_coef),
        )

    def r5(p: tuple[object, ...]) -> DiffItem | None:
        f1, f2 = _poly(p[0]), _poly(p[1])
        prod = _prod((f1, f2))
        return _read_item(
            frame_id="rep-product-constant-term",
            text=(f"함수 f(x) = {render_product((f1, f2))}의 도함수 f'(x)의 상수항을 구하시오."),
            function=prod,
            shown=render_product((f1, f2)),
            sym=product_to_sympy_str((f1, f2)),
            point=0,
            what="상수항",
            note="곱의 미분법 (fg)'은 f'g와 fg'의 합이다.",
        )

    def r6(p: tuple[object, ...]) -> DiffItem | None:
        f1, f2, sign = _poly(p[0]), _poly(p[1]), _int(p[2])
        sym1, sym2 = poly_to_sympy_str(f1), poly_to_sympy_str(f2)
        total = poly_from_sympy(sympy.expand(poly_to_sympy(f1) + sign * poly_to_sympy(f2)))
        word = "+" if sign == 1 else "-"
        return _read_item(
            frame_id="rep-sum-or-difference-coefficients",
            text=(
                f"두 함수 f(x) = {render_poly(f1)}, g(x) = {render_poly(f2)}에 대하여 "
                f"함수 y = f(x) {word} g(x)의 도함수의 모든 계수의 합을 구하시오."
            ),
            function=total,
            shown=f"f(x) {word} g(x)",
            sym=f"({sym1}) {word} ({sym2})",
            point=1,
            what="모든 계수의 합",
            note="합과 차의 미분법에 따라 각각 미분해 더하거나 뺀다.",
        )

    return [
        Frame(
            "rep-constant-term-of-derivative",
            tuple((f,) for f in seeded_order("p3-poly:r1", _POLYS_A[:20])),
            r1,
        ),
        Frame(
            "rep-sum-of-coefficients-of-derivative",
            tuple((f,) for f in seeded_order("p3-poly:r2", _POLYS_A[:20])),
            r2,
        ),
        Frame(
            "rep-constant-term-in-t",
            tuple((f,) for f in seeded_order("p3-poly:r3", _POLYS_B[:20])),
            r3,
        ),
        Frame(
            "rep-constant-multiple-coefficient",
            _grid("p3-poly:r4", (2, 3, 4, 5, 6, 7), (2, 3, 4, 5, 6)),
            r4,
        ),
        Frame(
            "rep-product-constant-term",
            _grid("p3-poly:r5", tuple(_LINEARS[:8]), tuple(_QUADS[:8])),
            r5,
        ),
        Frame(
            "rep-sum-or-difference-coefficients",
            _grid("p3-poly:r6", tuple(_POLYS_B[20:30]), tuple(_POLYS_B[:10]), (1, -1)),
            r6,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 기본(basic) — 미분계수
# ──────────────────────────────────────────────────────────────────────────
def _basic_value_item(frame_id: str, text: str, f: Poly, a: int) -> DiffItem:
    d = derivative_of(f)
    value = eval_at(d, a)
    return DiffItem(
        slot="basic",
        frame_id=frame_id,
        question_text=text,
        answer_text=str(value),
        explanation=(f"도함수는 {render_poly(d)}이므로 x가 {a}일 때의 값은 {value}이다."),
        conditions=_deriv_sym(poly_to_sympy_str(f), str(a)) + " = y",
        answer_map=(("y", str(value)),),
        problem_type_code=_EVAL,
        answer_format=_fmt(value),
    )


def _basic_frames() -> list[Frame]:
    def b1(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _poly(p[0]), _int(p[1])
        return _basic_value_item(
            "basic-value-of-derivative",
            f"함수 f(x) = {render_poly(f)}에 대하여 f'({a})의 값을 구하시오.",
            f,
            a,
        )

    def b2(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _poly(p[0]), _int(p[1])
        return _basic_value_item(
            "basic-differential-coefficient",
            f"f(x) = {render_poly(f)}일 때, 미분계수 f'({a}){eul_reul(str(a))} 구하시오.",
            f,
            a,
        )

    def b3(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _poly(p[0]), _int(p[1])
        return _basic_value_item(
            "basic-coefficient-at-point",
            f"함수 y = {render_poly(f)}의 x = {a}에서의 미분계수를 구하시오.",
            f,
            a,
        )

    def b4(p: tuple[object, ...]) -> DiffItem | None:
        f1, f2, a = _poly(p[0]), _poly(p[1]), _int(p[2])
        prod = _prod((f1, f2))
        d = derivative_of(prod)
        value = eval_at(d, a)
        return DiffItem(
            slot="basic",
            frame_id="basic-product-value",
            question_text=(
                f"함수 f(x) = {render_product((f1, f2))}에 대하여 f'({a})의 값을 구하시오."
            ),
            answer_text=str(value),
            explanation=(
                f"곱의 미분법에 따라 도함수는 {render_poly(d)}이므로 x가 {a}일 때의 값은 "
                f"{value}이다."
            ),
            conditions=_deriv_sym(product_to_sympy_str((f1, f2)), str(a)) + " = y",
            answer_map=(("y", str(value)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(value),
        )

    def b5(p: tuple[object, ...]) -> DiffItem | None:
        f1, f2, a = _poly(p[0]), _poly(p[1]), _int(p[2])
        if f1 == f2:
            return None
        d1, d2 = derivative_of(f1), derivative_of(f2)
        v1, v2 = eval_at(d1, a), eval_at(d2, a)
        return DiffItem(
            slot="basic",
            frame_id="basic-sum-of-two-derivative-values",
            question_text=(
                f"두 함수 f(x) = {render_poly(f1)}, g(x) = {render_poly(f2)}에 대하여 "
                f"f'({a}) + g'({a})의 값을 구하시오."
            ),
            answer_text=str(v1 + v2),
            explanation=(
                f"f'(x)는 {render_poly(d1)}이고 g'(x)는 {render_poly(d2)}이므로 두 값을 더하면 "
                f"{v1 + v2}이다."
            ),
            conditions=(
                _deriv_sym(f"({poly_to_sympy_str(f1)}) + ({poly_to_sympy_str(f2)})", str(a))
                + " = y"
            ),
            answer_map=(("y", str(v1 + v2)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(v1 + v2),
        )

    def b6(p: tuple[object, ...]) -> DiffItem | None:
        f1, f2, a = _poly(p[0]), _poly(p[1]), _int(p[2])
        if f1 == f2:
            return None
        d1, d2 = derivative_of(f1), derivative_of(f2)
        v1, v2 = eval_at(d1, a), eval_at(d2, a)
        return DiffItem(
            slot="basic",
            frame_id="basic-difference-of-two-derivative-values",
            question_text=(
                f"두 함수 f(x) = {render_poly(f1)}, g(x) = {render_poly(f2)}에 대하여 "
                f"f'({a}) - g'({a})의 값을 구하시오."
            ),
            answer_text=str(v1 - v2),
            explanation=(
                f"f'(x)는 {render_poly(d1)}이고 g'(x)는 {render_poly(d2)}이므로 두 값의 차는 "
                f"{v1 - v2}이다."
            ),
            conditions=(
                _deriv_sym(f"({poly_to_sympy_str(f1)}) - ({poly_to_sympy_str(f2)})", str(a))
                + " = y"
            ),
            answer_map=(("y", str(v1 - v2)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(v1 - v2),
        )

    return [
        Frame("basic-value-of-derivative", _grid("p3-poly:b1", _POLYS_A, _POINTS), b1),
        Frame("basic-differential-coefficient", _grid("p3-poly:b2", _POLYS_A, _POINTS), b2),
        Frame("basic-coefficient-at-point", _grid("p3-poly:b3", _POLYS_A, _POINTS), b3),
        Frame(
            "basic-product-value",
            _grid("p3-poly:b4", tuple(_LINEARS[:8]), tuple(_QUADS[:6]), (1, 2, -1)),
            b4,
        ),
        Frame(
            "basic-sum-of-two-derivative-values",
            _grid("p3-poly:b5", tuple(_POLYS_B[16:24]), tuple(_POLYS_B[24:30]), (1, 2, -1)),
            b5,
        ),
        Frame(
            "basic-difference-of-two-derivative-values",
            _grid("p3-poly:b6", tuple(_POLYS_B[:8]), tuple(_POLYS_B[8:16]), (1, 2, -1)),
            b6,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 응용(applied) — 미정계수·미지수를 구한다(solve-for-unknown · 스킬 연결 유형)
# ──────────────────────────────────────────────────────────────────────────
def _nonzero(lo: int, hi: int) -> tuple[int, ...]:
    return tuple(v for v in range(lo, hi + 1) if v)


def _applied_frames() -> list[Frame]:
    def a1(p: tuple[object, ...]) -> DiffItem | None:
        lead, a, c, pt = _int(p[0]), _int(p[1]), _int(p[2]), _int(p[3])
        if pt == 0:
            return None
        f: Poly = ((3, lead), (2, a), (1, c))
        b = eval_at(derivative_of(f), pt)  # 데이터는 SymPy로 구한다
        sign = "+" if c > 0 else "-"
        text_f = f"{render_poly(((3, lead),))} + ax^2 {sign} {abs(c)}x"
        return DiffItem(
            slot="applied",
            frame_id="applied-find-coefficient-from-value",
            question_text=(
                f"함수 f(x) = {text_f}에 대하여 f'({pt})의 값이 {b}일 때, 상수 a의 값을 구하시오."
            ),
            answer_text=str(a),
            explanation=(
                f"도함수는 {3 * lead}x^2 + 2ax {sign} {abs(c)}이므로 x가 {pt}일 때의 값이 {b}가 "
                f"되는 a는 {a}이다."
            ),
            conditions=f"{_deriv_sym(f'{lead}*x**3 + a*x**2 + ({c})*x', str(pt))} = {b}",
            answer_map=(("a", str(a)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a),
        )

    def a2(p: tuple[object, ...]) -> DiffItem | None:
        m = _int(p[0])
        k = 3 * m * m
        f: Poly = ((3, 1), (1, -k))
        if eval_at(derivative_of(f), m) != 0:  # pragma: no cover — 구성 항등
            return None
        return DiffItem(
            slot="applied",
            frame_id="applied-positive-root-of-derivative",
            question_text=(
                f"함수 f(x) = x^3 - {k}x에 대하여 f'(a) = 0을 만족시키는 양수 a의 값을 구하시오."
            ),
            answer_text=str(m),
            explanation=f"도함수는 3x^2 - {k}이므로 이 값이 0이 되는 양수 a는 {m}이다.",
            conditions=(f"{_deriv_sym(f'x**3 - {k}*x', 'a')} = 0", "a > 0"),
            answer_map=(("a", str(m)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(m),
        )

    def a3(p: tuple[object, ...]) -> DiffItem | None:
        a, b, x1 = _int(p[0]), _int(p[1]), _int(p[2])
        f: Poly = ((2, a), (1, b))
        d = derivative_of(f)
        v0, v1 = eval_at(d, 0), eval_at(d, x1)  # f'(0) = b 로 b가 정해지고 f'(x1)로 a가 정해진다
        return DiffItem(
            slot="applied",
            frame_id="applied-two-derivative-values-find-a",
            question_text=(
                f"함수 f(x) = ax^2 + bx에 대하여 f'(0)의 값이 {v0}이고 f'({x1})의 값이 {v1}일 때, "
                "상수 a의 값을 구하시오."
            ),
            answer_text=str(a),
            explanation=(
                f"도함수는 2ax + b이므로 f'(0)에서 b는 {v0}이고, f'({x1})에서 a는 {a}이다."
            ),
            conditions=f"{_deriv_sym(f'a*x**2 + ({v0})*x', str(x1))} = {v1}",
            answer_map=(("a", str(a)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a),
        )

    def a4(p: tuple[object, ...]) -> DiffItem | None:
        a, b = _int(p[0]), _int(p[1])
        f = _prod((((1, 1), (0, a)), ((2, 1), (0, b))))
        c = eval_at(derivative_of(f), 1)
        return DiffItem(
            slot="applied",
            frame_id="applied-product-with-unknown",
            question_text=(
                f"함수 f(x) = (x + a)(x^2 + {b})에 대하여 f'(1)의 값이 {c}일 때, "
                "상수 a의 값을 구하시오."
            ),
            answer_text=str(a),
            explanation=(
                f"곱의 미분법에 따라 f'(1)은 2a + {b + 3}이므로 이 값이 {c}가 되는 a는 {a}이다."
            ),
            conditions=f"{_deriv_sym(f'(x + a)*(x**2 + {b})', '1')} = {c}",
            answer_map=(("a", str(a)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a),
        )

    def a5(p: tuple[object, ...]) -> DiffItem | None:
        bb, cc, a = _int(p[0]), _int(p[1]), _int(p[2])
        f: Poly = ((3, 1), (1, bb), (0, cc))
        b = eval_at(derivative_of(f), a)
        return DiffItem(
            slot="applied",
            frame_id="applied-cubic-derivative-value-to-point",
            question_text=(
                f"함수 f(x) = {render_poly(f)}에 대하여 f'(a)의 값이 {b}가 되도록 하는 "
                "양수 a의 값을 구하시오."
            ),
            answer_text=str(a),
            explanation=(
                f"도함수는 {render_poly(derivative_of(f))}이므로 이 값이 {b}가 되는 "
                f"양수 a는 {a}이다."
            ),
            conditions=(f"{_deriv_sym(poly_to_sympy_str(f), 'a')} = {b}", "a > 0"),
            answer_map=(("a", str(a)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a),
        )

    def a6(p: tuple[object, ...]) -> DiffItem | None:
        a, b, c = _int(p[0]), _int(p[1]), _int(p[2])
        f = _prod((((1, a), (0, b)), ((2, 1), (0, c))))
        d = eval_at(derivative_of(f), 0)
        return DiffItem(
            slot="applied",
            frame_id="applied-product-derivative-at-zero",
            question_text=(
                f"함수 f(x) = (ax + {b})(x^2 + {c})에 대하여 f'(0)의 값이 {d}일 때, "
                "상수 a의 값을 구하시오."
            ),
            answer_text=str(a),
            explanation=(f"곱의 미분법에 따라 f'(0)은 {c}a이므로 이 값이 {d}가 되는 a는 {a}이다."),
            conditions=f"{_deriv_sym(f'(a*x + {b})*(x**2 + {c})', '0')} = {d}",
            answer_map=(("a", str(a)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a),
        )

    return [
        Frame(
            "applied-find-coefficient-from-value",
            _grid("p3-poly:a1", (1, 2), _nonzero(-4, 4), _nonzero(-5, 5), (1, 2, 3, -1, -2)),
            a1,
        ),
        Frame("applied-positive-root-of-derivative", _grid("p3-poly:a2", tuple(range(2, 12))), a2),
        Frame(
            "applied-two-derivative-values-find-a",
            _grid("p3-poly:a3", _nonzero(-4, 4), _nonzero(-6, 6), (1, 2, 3, -1, -2)),
            a3,
        ),
        Frame(
            "applied-product-with-unknown",
            _grid("p3-poly:a4", _nonzero(-5, 5), tuple(range(1, 8))),
            a4,
        ),
        Frame(
            "applied-cubic-derivative-value-to-point",
            _grid("p3-poly:a5", _nonzero(-6, 6), _nonzero(-5, 5), (1, 2, 3, 4)),
            a5,
        ),
        Frame(
            "applied-product-derivative-at-zero",
            _grid("p3-poly:a6", _nonzero(-6, 6), (1, 2, 3, 4), (2, 3, 4, 5)),
            a6,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 오개념 유발(misconception_trigger) — 곱의 미분을 각각의 미분의 곱으로 한 오답이 선지에 있다
# ──────────────────────────────────────────────────────────────────────────
def _naive_values(f1: Poly, f2: Poly, a: int) -> tuple[int, int, int, int]:
    """(정답 f'(a), 오개념 f1'·f2', 필러 f1'·f2, 필러 f1·f2')."""
    prod = _prod((f1, f2))
    d1, d2 = derivative_of(f1), derivative_of(f2)
    correct = eval_at(derivative_of(prod), a)
    naive = eval_at(d1, a) * eval_at(d2, a)
    left_only = eval_at(d1, a) * eval_at(f2, a)
    right_only = eval_at(f1, a) * eval_at(d2, a)
    return correct, naive, left_only, right_only


def _mc_value(
    frame_id: str, text: str, f1: Poly, f2: Poly, a: int, var: str = "x"
) -> DiffItem | None:
    correct, naive, left_only, right_only = _naive_values(f1, f2, a)
    try:
        choices, answer, distractors = build_choices(
            [
                ChoiceEntry(str(correct), is_correct=True, sort_key=float(correct)),
                ChoiceEntry(str(naive), _KEBAB, sort_key=float(naive)),
                ChoiceEntry(str(left_only), sort_key=float(left_only)),
                ChoiceEntry(str(right_only), sort_key=float(right_only)),
            ],
            shuffle_seed=f"{frame_id}:{a}",
        )
    except ValueError:
        return None
    prod = _prod((f1, f2))
    sym = product_to_sympy_str((f1, f2))
    if var != "x":
        sym = sym.replace("x", var)
    return DiffItem(
        slot="misconception_trigger",
        frame_id=frame_id,
        question_text=text,
        answer_text=answer,
        explanation=(
            f"곱의 미분법에 따라 도함수는 {render_poly(derivative_of(prod), var)}이므로 "
            f"{var}가 {a}일 때의 값은 {correct}이다."
        ),
        conditions=f"Derivative({sym}, {var}).doit().subs({var}, {a}) = y",
        answer_map=(("y", str(correct)),),
        problem_type_code=_EVAL,
        answer_format=_fmt(correct),
        choices=choices,
        distractors=distractors,
    )


def _misconception_frames() -> list[Frame]:
    def m1(p: tuple[object, ...]) -> DiffItem | None:
        f1, f2, a = _poly(p[0]), _poly(p[1]), _int(p[2])
        return _mc_value(
            "mc-product-value",
            f"함수 f(x) = {render_product((f1, f2))}에 대하여 f'({a})의 값은?",
            f1,
            f2,
            a,
        )

    def m2(p: tuple[object, ...]) -> DiffItem | None:
        f1, f2, a = _poly(p[0]), _poly(p[1]), _int(p[2])
        return _mc_value(
            "mc-product-coefficient-at-point",
            f"y = {render_product((f1, f2))}의 x = {a}에서의 미분계수로 옳은 것은?",
            f1,
            f2,
            a,
        )

    def m3(p: tuple[object, ...]) -> DiffItem | None:
        f1, f2 = _poly(p[0]), _poly(p[1])
        return _mc_value(
            "mc-product-constant-term",
            f"함수 f(x) = {render_product((f1, f2))}의 도함수 f'(x)의 상수항으로 옳은 것은?",
            f1,
            f2,
            0,
        )

    def m4(p: tuple[object, ...]) -> DiffItem | None:
        f1, f2 = _poly(p[0]), _poly(p[1])
        return _mc_value(
            "mc-product-sum-of-coefficients",
            f"y = {render_product((f1, f2))}의 도함수의 모든 계수의 합으로 옳은 것은?",
            f1,
            f2,
            1,
        )

    def m5(p: tuple[object, ...]) -> DiffItem | None:
        f1, f2, a = _poly(p[0]), _poly(p[1]), _int(p[2])
        t1, t2 = render_poly(f1, "t"), render_poly(f2, "t")
        return _mc_value(
            "mc-product-in-t",
            f"함수 g(t) = ({t1})({t2})에 대하여 g'({a})의 값은?",
            f1,
            f2,
            a,
            var="t",
        )

    def m6(p: tuple[object, ...]) -> DiffItem | None:
        n, f2, a = _int(p[0]), _poly(p[1]), _int(p[2])
        f1: Poly = ((n, 1),)
        return _mc_value(
            "mc-monomial-times-linear",
            f"함수 f(x) = x^{n}({render_poly(f2)})에 대하여 f'({a})의 값은?",
            f1,
            f2,
            a,
        )

    return [
        Frame(
            "mc-product-value",
            _grid("p3-poly:m1", tuple(_LINEARS[:10]), tuple(_QUADS[:8]), (1, 2, 3, -1, -2)),
            m1,
        ),
        Frame(
            "mc-product-coefficient-at-point",
            _grid("p3-poly:m2", tuple(_LINEARS[10:20]), tuple(_QUADS[8:16]), (1, 2, 3, -1, -2)),
            m2,
        ),
        Frame(
            "mc-product-constant-term",
            _grid("p3-poly:m3", tuple(_LINEARS[:12]), tuple(_LINEARS[12:])),
            m3,
        ),
        Frame(
            "mc-product-sum-of-coefficients",
            _grid("p3-poly:m4", tuple(_LINEARS[:12]), tuple(_QUADS[:12])),
            m4,
        ),
        Frame(
            "mc-product-in-t",
            _grid("p3-poly:m5", tuple(_LINEARS[12:]), tuple(_LINEARS[:12]), (1, 2, -1)),
            m5,
        ),
        Frame(
            "mc-monomial-times-linear",
            _grid("p3-poly:m6", (2, 3, 4), tuple(_LINEARS), (1, 2, 3)),
            m6,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 진단(diagnostic) — 규칙 하나씩을 확인한다
# ──────────────────────────────────────────────────────────────────────────
def _diagnostic_frames() -> list[Frame]:
    def d1(p: tuple[object, ...]) -> DiffItem | None:
        f = _poly(p[0])
        d = derivative_of(f)
        value = eval_at(d, 0)
        if value == 0:
            return None
        return DiffItem(
            slot="diagnostic",
            frame_id="diag-constant-term-of-derivative",
            question_text=f"함수 f(x) = {render_poly(f)}의 도함수 f'(x)의 상수항을 구하시오.",
            answer_text=str(value),
            explanation=f"도함수는 {render_poly(d)}이므로 상수항은 {value}이다.",
            conditions=_deriv_sym(poly_to_sympy_str(f), "0") + " = y",
            answer_map=(("y", str(value)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(value),
        )

    def d2(p: tuple[object, ...]) -> DiffItem | None:
        f = _poly(p[0])
        d = derivative_of(f)
        value = eval_at(d, 1)
        return DiffItem(
            slot="diagnostic",
            frame_id="diag-sum-of-derivative-coefficients",
            question_text=(
                f"함수 f(x) = {render_poly(f)}의 도함수 f'(x)의 모든 계수의 합을 구하시오."
            ),
            answer_text=str(value),
            explanation=f"도함수는 {render_poly(d)}이고 계수의 합은 {value}이다.",
            conditions=_deriv_sym(poly_to_sympy_str(f), "1") + " = y",
            answer_map=(("y", str(value)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(value),
        )

    def d3(p: tuple[object, ...]) -> DiffItem | None:
        fp, gp, s, t = _int(p[0]), _int(p[1]), _int(p[2]), _int(p[3])
        value = s * fp - t * gp
        return DiffItem(
            slot="diagnostic",
            frame_id="diag-linearity-of-derivative",
            question_text=(
                f"두 함수 f(x), g(x)에 대하여 f'(1)의 값이 {fp}, g'(1)의 값이 {gp}일 때, "
                f"함수 h(x) = {s}f(x) - {t}g(x)의 x = 1에서의 미분계수를 구하시오."
            ),
            answer_text=str(value),
            explanation=(
                f"실수배와 차의 미분법에 따라 h'(1)은 {s}f'(1)에서 {t}g'(1)을 뺀 값이므로 "
                f"{value}이다."
            ),
            # 증인 함수: f(x) = fp·x, g(x) = gp·x (미분계수 상수) — 선형성이라 답은 증인과 무관하다.
            conditions=_deriv_sym(f"{s}*({fp}*x) - {t}*({gp}*x)", "1") + " = y",
            answer_map=(("y", str(value)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(value),
        )

    def d4(p: tuple[object, ...]) -> DiffItem | None:
        f, c, a = _poly(p[0]), _int(p[1]), _int(p[2])
        g = poly_from_sympy(sympy.expand(poly_to_sympy(f) + c))
        gap = eval_at(derivative_of(g), a) - eval_at(derivative_of(f), a)  # SymPy로 구한 차
        return DiffItem(
            slot="diagnostic",
            frame_id="diag-constant-shift-vanishes",
            question_text=(
                f"함수 f(x) = {render_poly(f)}에 대하여 g(x) = f(x) + {c}라 할 때, "
                f"g'({a}) - f'({a})의 값을 구하시오."
            ),
            answer_text=str(gap),
            explanation="상수를 더해도 도함수는 변하지 않으므로 두 미분계수의 차는 0이다.",
            # g'(a) - f'(a) = (g - f)'(a) — 미분 평가 1회·맨몸 제약에 맞춰 차를 한 번에 미분한다.
            conditions=(
                _deriv_sym(f"(({poly_to_sympy_str(f)}) + {c}) - ({poly_to_sympy_str(f)})", str(a))
                + " = y"
            ),
            answer_map=(("y", str(gap)),),
            problem_type_code=_EVAL,
            answer_format=AnswerFormat.실수,
        )

    def d5(p: tuple[object, ...]) -> DiffItem | None:
        a, b = _int(p[0]), _int(p[1])
        f1: Poly = ((1, 1), (0, a))
        f2: Poly = ((1, 1), (0, b))
        prod = _prod((f1, f2))
        k = eval_at(derivative_of(prod), 0)  # f'(x) = 2x + k 이므로 k = f'(0)
        return DiffItem(
            slot="diagnostic",
            frame_id="diag-product-of-linear-factors",
            question_text=(
                f"함수 f(x) = {render_product((f1, f2))}의 도함수가 f'(x) = 2x + k일 때, "
                "상수 k의 값을 구하시오."
            ),
            answer_text=str(k),
            explanation=(
                f"곱의 미분법에 따라 f'(x)는 {render_poly(derivative_of(prod))}이므로 k는 {k}이다."
            ),
            # 도함수 전체 항등식은 자유기호가 x·k 둘이라 x = 0에서의 값으로 k 하나만 남긴다.
            conditions=_deriv_sym(product_to_sympy_str((f1, f2)), "0") + " = k",
            answer_map=(("k", str(k)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(k),
        )

    def d6(p: tuple[object, ...]) -> DiffItem | None:
        c, n = _int(p[0]), _int(p[1])
        f: Poly = ((n, c),)
        value = eval_at(derivative_of(f), 1)
        return DiffItem(
            slot="diagnostic",
            frame_id="diag-constant-multiple-value",
            question_text=f"함수 f(x) = {render_poly(f)}에 대하여 f'(1)의 값을 구하시오.",
            answer_text=str(value),
            explanation=(
                f"상수배의 미분법에 따라 도함수는 {render_poly(derivative_of(f))}이므로 "
                f"f'(1)의 값은 {value}이다."
            ),
            conditions=_deriv_sym(poly_to_sympy_str(f), "1") + " = y",
            answer_map=(("y", str(value)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(value),
        )

    return [
        Frame("diag-constant-term-of-derivative", _grid("p3-poly:d1", _POLYS_A[20:]), d1),
        Frame("diag-sum-of-derivative-coefficients", _grid("p3-poly:d2", _POLYS_A[20:]), d2),
        Frame(
            "diag-linearity-of-derivative",
            _grid("p3-poly:d3", _nonzero(-6, 6), _nonzero(-6, 6), (2, 3, 4), (2, 3, 5)),
            d3,
        ),
        Frame(
            "diag-constant-shift-vanishes",
            _grid("p3-poly:d4", tuple(_POLYS_B[:6]), (2, 3, 5, 7), (-2, 1, 2)),
            d4,
        ),
        Frame(
            "diag-product-of-linear-factors",
            _grid("p3-poly:d5", _nonzero(-6, 6), _nonzero(-6, 6)),
            d5,
        ),
        Frame(
            "diag-constant-multiple-value",
            _grid("p3-poly:d6", (2, 3, 4, 5, 6, 7), (2, 3, 4, 5)),
            d6,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 숙련도 확인(mastery_check) — 규칙을 묶어 쓰거나 조건에서 미정계수를 거쳐 값을 구한다
# ──────────────────────────────────────────────────────────────────────────
def _mastery_frames() -> list[Frame]:
    def k1(p: tuple[object, ...]) -> DiffItem | None:
        f1, f2, s, t, a = _poly(p[0]), _poly(p[1]), _int(p[2]), _int(p[3]), _int(p[4])
        if f1 == f2:
            return None
        h = poly_from_sympy(sympy.expand(s * poly_to_sympy(f1) - t * poly_to_sympy(f2)))
        d1, d2 = derivative_of(f1), derivative_of(f2)
        value = eval_at(derivative_of(h), a)
        return DiffItem(
            slot="mastery_check",
            frame_id="mastery-linear-combination-of-two-functions",
            question_text=(
                f"두 함수 f(x) = {render_poly(f1)}, g(x) = {render_poly(f2)}에 대하여 "
                f"함수 h(x) = {s}f(x) - {t}g(x)의 x = {a}에서의 미분계수를 구하시오."
            ),
            answer_text=str(value),
            explanation=(
                f"실수배와 차의 미분법에 따라 h'(x)는 {s}f'(x)에서 {t}g'(x)를 뺀 것이고 "
                f"f'(x)는 {render_poly(d1)}, g'(x)는 {render_poly(d2)}이므로 x가 {a}일 때의 값은 "
                f"{value}이다."
            ),
            conditions=(
                _deriv_sym(f"{s}*({poly_to_sympy_str(f1)}) - {t}*({poly_to_sympy_str(f2)})", str(a))
                + " = y"
            ),
            answer_map=(("y", str(value)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(value),
        )

    def k2(p: tuple[object, ...]) -> DiffItem | None:
        a, b, c = _int(p[0]), _int(p[1]), _int(p[2])
        f: Poly = ((3, 1), (2, a), (1, b), (0, c))
        d = derivative_of(f)
        v1, v2 = eval_at(d, 1), eval_at(d, -1)  # 데이터는 SymPy로 구한다
        # f'(1) - f'(-1) = 4a 라 두 값이 a를 정한다. b는 두 값으로 정해지므로 상수로 대입한다.
        return DiffItem(
            slot="mastery_check",
            frame_id="mastery-two-values-find-leading-coefficient",
            question_text=(
                f"함수 f(x) = x^3 + ax^2 + bx + {c}에 대하여 f'(1)의 값이 {v1}이고 "
                f"f'(-1)의 값이 {v2}일 때, 상수 a의 값을 구하시오."
            ),
            answer_text=str(a),
            explanation=(f"도함수는 3x^2 + 2ax + b이므로 두 조건에서 a는 {a}, b는 {b}이다."),
            conditions=(f"{_deriv_sym(f'x**3 + a*x**2 + ({b})*x + {c}', '1')} = {v1}"),
            answer_map=(("a", str(a)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a),
        )

    def k3(p: tuple[object, ...]) -> DiffItem | None:
        s, a = _int(p[0]), _int(p[1])
        f = _prod((((2, 1), (0, s)), ((2, 1), (0, a))))
        value = eval_at(derivative_of(f), 1)
        return DiffItem(
            slot="mastery_check",
            frame_id="mastery-quartic-product-find-constant",
            question_text=(
                f"함수 f(x) = (x^2 + {s})(x^2 + a)에 대하여 f'(1)의 값이 {value}일 때, "
                "상수 a의 값을 구하시오."
            ),
            answer_text=str(a),
            explanation=(
                f"곱의 미분법에 따라 f'(1)은 2a + {2 * s + 4}이므로 이 값이 {value}가 되는 "
                f"a는 {a}이다."
            ),
            conditions=f"{_deriv_sym(f'(x**2 + {s})*(x**2 + a)', '1')} = {value}",
            answer_map=(("a", str(a)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a),
        )

    def k4(p: tuple[object, ...]) -> DiffItem | None:
        r1, r2 = _int(p[0]), _int(p[1])
        if r1 >= r2 or (r1 + r2) % 2:
            return None
        a = -3 * (r1 + r2) // 2
        b = 3 * r1 * r2
        f: Poly = ((3, 1), (2, a), (1, b))
        d = derivative_of(f)
        if eval_at(d, r1) != 0 or eval_at(d, r2) != 0:  # pragma: no cover — 구성 항등
            return None
        return DiffItem(
            slot="mastery_check",
            frame_id="mastery-roots-of-derivative-find-a",
            question_text=(
                f"함수 f(x) = x^3 + ax^2 + bx (a, b는 상수)에 대하여 방정식 f'(x) = 0의 "
                f"두 실근이 {r1}, {r2}일 때, 상수 a의 값을 구하시오."
            ),
            answer_text=str(a),
            explanation=(
                f"도함수 3x^2 + 2ax + b의 두 근이 {r1}, {r2}이므로 근과 계수의 관계에서 "
                f"a는 {a}이다."
            ),
            conditions=f"{_deriv_sym(f'x**3 + a*x**2 + ({b})*x', str(r1))} = 0",
            answer_map=(("a", str(a)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a),
        )

    return [
        Frame(
            "mastery-linear-combination-of-two-functions",
            _grid(
                "p3-poly:k1",
                tuple(_POLYS_B[:8]),
                tuple(_POLYS_B[8:16]),
                (2, 3, 4),
                (2, 3, 5),
                (-1, 1, 2),
            ),
            k1,
        ),
        Frame(
            "mastery-two-values-find-leading-coefficient",
            _grid("p3-poly:k2", _nonzero(-4, 4), _nonzero(-5, 5), (1, 2, 3, 4, 5)),
            k2,
        ),
        Frame(
            "mastery-quartic-product-find-constant",
            _grid("p3-poly:k3", (1, 2, 3), _nonzero(-6, 6)),
            k3,
        ),
        Frame(
            "mastery-roots-of-derivative-find-a",
            _grid("p3-poly:k4", tuple(range(-5, 6)), tuple(range(-5, 6))),
            k4,
        ),
    ]


_SLOT_FRAMES = {
    "representative": _rep_frames,
    "basic": _basic_frames,
    "applied": _applied_frames,
    "misconception_trigger": _misconception_frames,
    "diagnostic": _diagnostic_frames,
    "mastery_check": _mastery_frames,
}


class P3DiffPolynomialRulesGenerator(P3DiffSlotGenerator):
    """[12미적Ⅰ-02-04] 미분법과 다항함수의 도함수 — 슬롯 6종 결정론 생성기."""

    standard_code: ClassVar[str] = "[12미적Ⅰ-02-04]"
    concept_src_id: ClassVar[str] = "H:12미적Ⅰ02-04"
    unit_code: ClassVar[str] = "P3-CALC1-DIFF-POLYNOMIAL-RULES"
    slug_prefix: ClassVar[str] = "wm-p3-diff-polyrules"
    slot_difficulty: ClassVar[dict[str, float]] = {
        "representative": 2.0,
        "basic": 2.5,
        "applied": 3.0,
        "misconception_trigger": 3.0,
        "diagnostic": 2.5,
        "mastery_check": 3.5,
    }
    slot_count: ClassVar[int] = 12

    @classmethod
    def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
        return round_robin_items(_SLOT_FRAMES[slot](), cls.slot_count, claimed=claimed)
