"""[12미적Ⅰ-02-05] 접선의 방정식 결정론 문항 생성기 — P3-03(결정론·LLM 0).

개념: `H:12미적Ⅰ02-05`(`math.calculus.jeopseonui-bangjeongsik`). 명세 probe_note —
"접선 조건을 '접점에서 이중근' 항등식으로 써야 한다(표본 검증)". 그래서 이 파일은 검산 재료를 두
갈래로 쓴다.

  · **미분 평가형** — `Derivative(식, x).doit().subs(x, 점) = 값`(접선의 기울기 = 미분계수).
  · **이중근(판별식)형** — 이차 곡선 y = Ax^2 + bx + c와 직선 y = mx + k가 접하면 연립한 이차식
    Ax^2 + (b - m)x + (c - k)가 이중근을 가지므로 판별식 (b - m)^2 - 4A(c - k) = 0이다.
    이 조건은 *미분을 쓰지 않는다* — 생성기가 `sympy.diff`로 구한 접선(기울기 m)과 **독립인 경로**로
    k를 다시 확인하는 검산이다(두 경로가 어긋나면 수용 게이트가 거부).
  · **수치 대입형(정직 한계)** — 삼차 이상 곡선의 y절편·접선의 함숫값·삼각형 넓이처럼 미분 평가를
    다른 연산과 섞어야 하는 문항은 Tier1이 섞인 식을 검산하지 못한다(`D + 108 = y` 형태는
    unverifiable — 형제 생성기 docstring 2026-10-06 실측). 그 문항은 생성기가 `sympy.diff`로 구한
    기울기·함숫값을 *상수로 풀어 쓴 산술식*을 조건에 둔다. 이 형태는 미분 자체를 재검산하지는
    않으므로(산술 재확인) 독립 검산은 테스트(`test_p3_diff_tangent_velocity_generators`)가
    극한 정의·SymPy solve로 맡는다.

범위(이 개념에 한정): 다항함수 곡선의 접선(접점이 주어지거나 기울기·통과점으로 접점을 찾는 것).
**법선·접선 길이·삼각함수 곡선은 다루지 않는다**("김에 같이" 금지). 함수식(직선의 방정식)을 답으로
하는 문항은 만들지 않는다(채점 계약상 스칼라 단일 미지수 답만 — 기울기·y절편·접점·상수·넓이로
묻는다).

슬롯 6종 × 틀(frame): 대표 6 · 기본 6 · 응용 6 · 오개념 유발 6 · 진단 6 · 숙련도 6 = 36틀.

문제유형 정직성
--------------
스킬 연결로 세어지는 유형은 `ptype.solve-for-unknown`(equation-rearrangement)이다. 이 개념의 스킬에
`graph-sketching`이 있어 `optimize-extremum`·`count-solutions`도 겹치지만, 이 생성기는 그 유형의
*진짜* 문항(극값 최적화·해의 개수 — 그 값을 Tier1이 검산할 수 있는 형태)을 아직 만들지 못해 달지
않는다(거짓 유형으로 맞추지 않는다). 값·식 도출 문항은 `ptype.evaluate-expression`으로
정직하게 단다.

오개념: 개념 핵심 오개념 M0673(접점의 좌표와 기울기를 따로 구하지 않는다)에는 *승인된 kebab이
없다*(MISC-40 판정: omission형 — 풀이에 글자가 남지 않아 의도적 미승격). 신규 id를 만들지 않으므로
오개념 유발 슬롯은 접선의 기울기 계산 단계에서 실제로 나오는 기존 kebab `power-rule-step-omitted`
(지수를 내리거나 1 줄이는 단계 누락)로 오답 선지를 연결한다. 그 kebab은 M0671(`-02-03` 소속)으로
닿으므로 **M0673에는 닿지 않는다** — 보고 사항이다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar, Final, cast

import sympy

from whymath_backend.l3.equivalent.p3_diff_expr import (
    Poly,
    derivative_of,
    eval_at,
    poly_from_sympy,
    poly_to_sympy,
    poly_to_sympy_str,
    render_poly,
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
from whymath_backend.lang.josa import eul_reul, eun_neun, i_ga, wa_gwa
from whymath_backend.schema.enums import AnswerFormat

__all__ = ["P3DiffTangentLineGenerator"]

_KEBAB: Final = "power-rule-step-omitted"
_EVAL: Final = "ptype.evaluate-expression"
_SOLVE: Final = "ptype.solve-for-unknown"
_X = sympy.Symbol("x")


# ──────────────────────────────────────────────────────────────────────────
# 공용 도구
# ──────────────────────────────────────────────────────────────────────────
def _fmt(value: int) -> AnswerFormat:
    return AnswerFormat.자연수 if value > 0 else AnswerFormat.실수


def _grid(seed: str, *axes: tuple[object, ...]) -> tuple[tuple[object, ...], ...]:
    combos: list[tuple[object, ...]] = [()]
    for axis in axes:
        combos = [(*c, v) for c in combos for v in axis]
    return tuple(seeded_order(seed, combos))


def _poly(coeffs: dict[int, int]) -> Poly:
    return tuple(sorted(((e, c) for e, c in coeffs.items() if c != 0), reverse=True))


def _as_poly(obj: object) -> Poly:
    return cast(Poly, obj)


def _as_int(obj: object) -> int:
    return int(str(obj))


def _quad_pool() -> tuple[object, ...]:
    """A x^2 + b x + c (A ∈ {1, 2, -1, 3}) — 이중근(판별식) 검산이 가능한 이차 곡선."""
    return tuple(
        _poly({2: lead, 1: b, 0: c})
        for lead in (1, 2, -1, 3)
        for b in range(-4, 5)
        for c in range(-5, 6)
    )


def _cubic_pool() -> tuple[object, ...]:
    return tuple(
        _poly({3: lead, 2: b, 1: c, 0: d})
        for lead in (1, 2, -1)
        for b in range(-3, 4)
        for c in range(-4, 5)
        for d in (-5, -3, -2, 0, 1, 2, 4)
    )


def _quartic_pool() -> tuple[object, ...]:
    return tuple(
        _poly({4: lead, 2: b, 1: c, 0: d})
        for lead in (1, -1, 2)
        for b in (-3, -2, -1, 1, 2, 3)
        for c in range(-4, 5)
        for d in (-3, -1, 0, 2, 4)
    )


def _mixed_pool() -> tuple[object, ...]:
    return (*_quad_pool()[::5], *_cubic_pool()[::23])


_POINTS: Final[tuple[object, ...]] = (-3, -2, -1, 1, 2, 3, 4)
_POS_POINTS: Final[tuple[object, ...]] = (1, 2, 3, 4)


def _tangent(f: Poly, a: int) -> tuple[int, int, int]:
    """접점 (a, f(a))에서의 접선 y = m x + k — (기울기 m, 함숫값 f(a), y절편 k). 전부 SymPy 경로."""
    m = eval_at(derivative_of(f), a)
    fa = eval_at(f, a)
    return m, fa, fa - m * a


def _pt_form(slope: str, a: int, fa: int) -> str:
    """점-기울기 꼴 'y = m(x - a) + b' — 부호를 읽기 좋게 푼다(이중 부호 '- (-2)'·'+ -5' 방지)."""
    x_part = f"x - {a}" if a >= 0 else f"x + {-a}"
    tail = f"+ {fa}" if fa >= 0 else f"- {-fa}"
    return f"y = {slope}({x_part}) {tail}"


def _pt_slope(m: int, a: int, fa: int) -> str:
    return _pt_form(str(m), a, fa)


def _line(m: int, k: int) -> str:
    return render_poly(((1, m), (0, k)))


def _d(f: Poly, point: str) -> str:
    """`Derivative(f, x).doit().subs(x, 점)` — 미분 평가 1회(맨몸) 표기."""
    return f"Derivative({poly_to_sympy_str(f)}, x).doit().subs(x, {point})"


def _shift(f: Poly, delta: int) -> Poly:
    """f(x + delta)를 SymPy로 전개한 다항식(두 점의 기울기를 한 번의 미분으로 묶는 데 쓴다)."""
    expr = sympy.expand(poly_to_sympy(f).subs(_X, _X + delta))
    return poly_from_sympy(expr)


def _pick(roots: list[sympy.Expr], guard: Callable[[sympy.Expr], bool] | None = None) -> int | None:
    """보호 조건을 통과하는 실근이 정수 1개뿐일 때 그 값, 아니면 None(애매한 문항은 버린다)."""
    passed = [r for r in roots if r.is_real and (guard is None or guard(r))]
    if len(passed) != 1 or not passed[0].is_integer:
        return None
    return int(passed[0])


def _solve_real(expr: sympy.Expr, symbol: sympy.Symbol) -> list[sympy.Expr]:
    return list(sympy.solve(expr, symbol))


def _render_with_param(base: Poly, exp: int) -> tuple[str, str]:
    """base + p·x^exp(미지 계수) — (사람이 읽는 표기, SymPy 표기). base에 x^exp 항이 없어야 한다."""
    terms: list[tuple[int, int | None]] = [(e, c) for e, c in base]
    terms.append((exp, None))
    terms.sort(key=lambda t: t[0], reverse=True)
    human: list[str] = []
    symbolic: list[str] = []
    for index, (e, c) in enumerate(terms):
        if c is None:
            h_body = "p" if e == 0 else (f"px^{e}" if e > 1 else "px")
            s_body = "p" if e == 0 else (f"p*x**{e}" if e > 1 else "p*x")
            sign = "+"
        else:
            magnitude = abs(c)
            if e == 0:
                h_body = s_body = str(magnitude)
            else:
                v_h = "x" if e == 1 else f"x^{e}"
                v_s = "x" if e == 1 else f"x**{e}"
                h_body = v_h if magnitude == 1 else f"{magnitude}{v_h}"
                s_body = v_s if magnitude == 1 else f"{magnitude}*{v_s}"
            sign = "-" if c < 0 else "+"
        if index == 0:
            human.append(f"-{h_body}" if sign == "-" else h_body)
            symbolic.append(f"-{s_body}" if sign == "-" else s_body)
        else:
            human.append(f"{sign} {h_body}")
            symbolic.append(f"{sign} {s_body}")
    return " ".join(human), " ".join(symbolic)


def _slope_item(
    *, slot: str, frame_id: str, text: str, f: Poly, a: int, ptype: str = _EVAL
) -> DiffItem:
    m, fa, _ = _tangent(f, a)
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(m),
        explanation=(
            f"접선의 기울기는 접점에서의 미분계수이다. 도함수는 {render_poly(derivative_of(f))}"
            f"이므로 x가 {a}일 때 기울기는 {m}이다."
        ),
        conditions=f"{_d(f, str(a))} = y",
        answer_map=(("y", str(m)),),
        problem_type_code=ptype,
        answer_format=_fmt(m),
    )


def _echo_item(
    *, slot: str, frame_id: str, text: str, value: int, explanation: str, expr: str, ptype: str
) -> DiffItem:
    """수치 대입형 — 생성기가 SymPy로 푼 상수를 산술식으로 재확인한다(독립 미분 검산 아님)."""
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(value),
        explanation=explanation,
        conditions=f"{expr} = y",
        answer_map=(("y", str(value)),),
        problem_type_code=ptype,
        answer_format=_fmt(value),
    )


def _disc_cond(lead: int, b: int, c: int, m: int, k: str) -> str:
    """이중근 항등식 — A x^2 + (b - m) x + (c - k)의 판별식 = 0 (미분을 쓰지 않는 독립 검산)."""
    return f"(({b}) - ({m}))**2 - 4*({lead})*(({c}) - {k}) = 0"


def _quad_parts(f: Poly) -> tuple[int, int, int]:
    table = dict(f)
    return table.get(2, 0), table.get(1, 0), table.get(0, 0)


# ──────────────────────────────────────────────────────────────────────────
# 대표(representative)
# ──────────────────────────────────────────────────────────────────────────
def _rep_frames() -> list[Frame]:
    slot = "representative"

    def r1(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _as_poly(p[0]), _as_int(p[1])
        fa = eval_at(f, a)
        return _slope_item(
            slot=slot,
            frame_id="rep-slope-at-point",
            text=f"곡선 y = {render_poly(f)} 위의 점 ({a}, {fa})에서의 접선의 기울기를 구하시오.",
            f=f,
            a=a,
        )

    def r2(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _as_poly(p[0]), _as_int(p[1])
        return _slope_item(
            slot=slot,
            frame_id="rep-slope-at-x-coordinate",
            text=f"곡선 y = {render_poly(f)}의 x좌표가 {a}인 점에서의 접선의 기울기를 구하시오.",
            f=f,
            a=a,
        )

    def r3(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _as_poly(p[0]), _as_int(p[1])
        lead, b, c = _quad_parts(f)
        m, fa, k = _tangent(f, a)
        return DiffItem(
            slot=slot,
            frame_id="rep-y-intercept-of-tangent",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 점 ({a}, {fa})에서의 접선의 y절편을 구하시오."
            ),
            answer_text=str(k),
            explanation=(
                f"접선을 y = {m}x + k라 두고 곡선과 연립하면 이차방정식이 접점에서 이중근을 "
                f"가져야 하므로 판별식이 0이다. 이를 풀면 k는 {k}이다."
            ),
            conditions=_disc_cond(lead, b, c, m, "k"),
            answer_map=(("k", str(k)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(k),
        )

    def r4(p: tuple[object, ...]) -> DiffItem | None:
        f, a, t = _as_poly(p[0]), _as_int(p[1]), _as_int(p[2])
        if t == a:
            return None
        m, fa, _ = _tangent(f, a)
        value = fa + m * (t - a)
        return _echo_item(
            slot=slot,
            frame_id="rep-tangent-line-value",
            text=(
                f"곡선 y = {render_poly(f)} 위의 점 ({a}, {fa})에서의 접선의 방정식을 y = g(x)라 "
                f"할 때, g({t})의 값을 구하시오."
            ),
            value=value,
            explanation=(f"접선은 {_pt_slope(m, a, fa)}이므로 x가 {t}일 때의 값은 {value}이다."),
            expr=f"({fa}) + ({m})*(({t}) - ({a}))",
            ptype=_EVAL,
        )

    def r5(p: tuple[object, ...]) -> DiffItem | None:
        base, p0, a = _as_poly(p[0]), _as_int(p[1]), _as_int(p[2])
        if any(e == 2 for e, _ in base) or p0 == 0:
            return None
        full = _poly({**dict(base), 2: p0})
        m = eval_at(derivative_of(full), a)
        human, symbolic = _render_with_param(base, 2)
        return DiffItem(
            slot=slot,
            frame_id="rep-find-coefficient-from-slope",
            question_text=(
                f"곡선 y = {human} 위의 x좌표가 {a}인 점에서의 접선의 기울기가 {m}일 때, "
                "상수 p의 값을 구하시오."
            ),
            answer_text=str(p0),
            explanation=(
                f"접선의 기울기는 미분계수이므로 도함수에 x = {a}{eul_reul(str(a))} 대입한 값이 "
                f"{m}{i_ga(str(m))} 되도록 "
                f"p를 정하면 p는 {p0}이다."
            ),
            conditions=f"Derivative({symbolic}, x).doit().subs(x, {a}) = {m}",
            answer_map=(("p", str(p0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(p0),
        )

    def r6(p: tuple[object, ...]) -> DiffItem | None:
        f, a0 = _as_poly(p[0]), _as_int(p[1])
        m = eval_at(derivative_of(f), a0)
        t = sympy.Symbol("t")
        d_expr = sympy.diff(poly_to_sympy(f), _X).subs(_X, t) - m
        found = _pick(_solve_real(d_expr, t), lambda r: r > 0)
        if found != a0:
            return None
        return DiffItem(
            slot=slot,
            frame_id="rep-find-point-for-slope",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 x좌표가 a인 점에서의 접선의 기울기가 {m}일 때, "
                "양수 a의 값을 구하시오."
            ),
            answer_text=str(a0),
            explanation=(
                f"도함수 {render_poly(derivative_of(f))}에서 x가 a일 때의 값이 {m}이 되는 "
                f"양수 a는 {a0}이다."
            ),
            conditions=(f"{_d(f, 'a')} = {m}", "a > 0"),
            answer_map=(("a", str(a0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a0),
        )

    base_pool = tuple(
        _poly({3: lead, 1: c, 0: d})
        for lead in (1, 2, -1)
        for c in (-6, -3, -1, 2, 4)
        for d in (-4, -1, 2, 5)
    )
    quad_a = _grid("p3-tan:r6", _quad_pool()[::4], _POS_POINTS)
    return [
        Frame("rep-slope-at-point", _grid("p3-tan:r1", _cubic_pool()[::9], _POINTS), r1),
        Frame("rep-slope-at-x-coordinate", _grid("p3-tan:r2", _quartic_pool()[::7], _POINTS), r2),
        Frame("rep-y-intercept-of-tangent", _grid("p3-tan:r3", _quad_pool(), _POINTS), r3),
        Frame(
            "rep-tangent-line-value",
            _grid("p3-tan:r4", _cubic_pool()[::31], _POINTS, (-2, -1, 0, 1, 2, 3)),
            r4,
        ),
        Frame(
            "rep-find-coefficient-from-slope",
            _grid("p3-tan:r5", base_pool, (-4, -3, -2, -1, 1, 2, 3, 4), (1, 2, 3, -1, -2)),
            r5,
        ),
        Frame("rep-find-point-for-slope", quad_a, r6),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 기본(basic)
# ──────────────────────────────────────────────────────────────────────────
def _basic_frames() -> list[Frame]:
    slot = "basic"

    def b1(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _as_poly(p[0]), _as_int(p[1])
        return _slope_item(
            slot=slot,
            frame_id="basic-slope-of-function-graph",
            text=(
                f"함수 f(x) = {render_poly(f)}의 그래프 위의 점 ({a}, f({a}))에서의 접선의 "
                "기울기를 구하시오."
            ),
            f=f,
            a=a,
        )

    def b2(p: tuple[object, ...]) -> DiffItem | None:
        f, a, b = _as_poly(p[0]), _as_int(p[1]), _as_int(p[2])
        if a >= b:
            return None
        total = eval_at(derivative_of(f), a) + eval_at(derivative_of(f), b)
        shifted = _shift(f, b - a)
        fa_text = f"f'({a})"
        return DiffItem(
            slot=slot,
            frame_id="basic-slope-sum-at-two-points",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 x좌표가 {a}인 점과 {b}인 점에서의 접선의 "
                "기울기의 합을 구하시오."
            ),
            answer_text=str(total),
            explanation=(
                f"두 점에서의 접선의 기울기는 각각 미분계수 f'({a}){wa_gwa(fa_text)} "
                f"f'({b})이므로 두 값을 "
                f"더하면 {total}이다."
            ),
            # 두 미분 평가를 합치지 못하는 Tier1 제약 — f(x) + f(x + d)를 한 번에 미분해 검산한다.
            conditions=(
                f"Derivative({poly_to_sympy_str(f)} + ({poly_to_sympy_str(shifted)}), x)"
                f".doit().subs(x, {a}) = y"
            ),
            answer_map=(("y", str(total)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(total),
        )

    def b3(p: tuple[object, ...]) -> DiffItem | None:
        f, a, b = _as_poly(p[0]), _as_int(p[1]), _as_int(p[2])
        if a >= b:
            return None
        diff = eval_at(derivative_of(f), b) - eval_at(derivative_of(f), a)
        shifted = _shift(f, b - a)
        return DiffItem(
            slot=slot,
            frame_id="basic-slope-difference-at-two-points",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 x = {b}에서의 접선의 기울기에서 x = {a}에서의 "
                "접선의 기울기를 뺀 값을 구하시오."
            ),
            answer_text=str(diff),
            explanation=(
                f"f'({b})에서 f'({a}){eul_reul(f"f'({a})")} 빼면 {diff}이다 "
                f"(도함수는 {render_poly(derivative_of(f))})."
            ),
            conditions=(
                f"Derivative(({poly_to_sympy_str(shifted)}) - ({poly_to_sympy_str(f)}), x)"
                f".doit().subs(x, {a}) = y"
            ),
            answer_map=(("y", str(diff)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(diff),
        )

    def b4(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _as_poly(p[0]), _as_int(p[1])
        m, fa, k = _tangent(f, a)
        return _echo_item(
            slot=slot,
            frame_id="basic-y-intercept-of-cubic-tangent",
            text=(
                f"곡선 y = {render_poly(f)} 위의 점 ({a}, {fa})에서의 접선이 y축과 만나는 "
                "점의 y좌표를 구하시오."
            ),
            value=k,
            explanation=(f"접선은 {_pt_slope(m, a, fa)}이고 x = 0을 대입하면 y좌표는 {k}이다."),
            expr=f"({fa}) - ({a})*({m})",
            ptype=_EVAL,
        )

    def b5(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _as_poly(p[0]), _as_int(p[1])
        m, fa, k = _tangent(f, a)
        if m == 0:
            return None
        return _echo_item(
            slot=slot,
            frame_id="basic-slope-plus-intercept",
            text=(
                f"곡선 y = {render_poly(f)} 위의 점 ({a}, {fa})에서의 접선의 방정식을 "
                "y = mx + n이라 할 때, m + n의 값을 구하시오."
            ),
            value=m + k,
            explanation=(f"기울기 m은 {m}이고 y절편 n은 {k}이므로 m + n은 {m + k}이다."),
            expr=f"({m}) + ({k})",
            ptype=_EVAL,
        )

    def b6(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _as_poly(p[0]), _as_int(p[1])
        m, fa, _ = _tangent(f, a)
        if m == 0:
            return None
        xi = sympy.Rational(a) - sympy.Rational(fa, m)
        if not xi.is_integer:
            return None
        return _echo_item(
            slot=slot,
            frame_id="basic-x-intercept-of-tangent",
            text=(
                f"곡선 y = {render_poly(f)} 위의 점 ({a}, {fa})에서의 접선이 x축과 만나는 "
                "점의 x좌표를 구하시오."
            ),
            value=int(xi),
            explanation=(f"접선 {_pt_slope(m, a, fa)}에 y = 0을 대입하면 x좌표는 {int(xi)}이다."),
            expr=f"({a}) - ({fa})/({m})",
            ptype=_EVAL,
        )

    cubics = _cubic_pool()
    return [
        Frame("basic-slope-of-function-graph", _grid("p3-tan:b1", cubics[3::17], _POINTS), b1),
        Frame(
            "basic-slope-sum-at-two-points",
            _grid("p3-tan:b2", _mixed_pool(), (-2, -1, 0, 1), (1, 2, 3)),
            b2,
        ),
        Frame(
            "basic-slope-difference-at-two-points",
            _grid("p3-tan:b3", _mixed_pool()[1::2], (-2, -1, 0, 1), (1, 2, 3)),
            b3,
        ),
        Frame("basic-y-intercept-of-cubic-tangent", _grid("p3-tan:b4", cubics[5::29], _POINTS), b4),
        Frame("basic-slope-plus-intercept", _grid("p3-tan:b5", cubics[7::37], _POINTS), b5),
        Frame("basic-x-intercept-of-tangent", _grid("p3-tan:b6", cubics[::13], _POINTS), b6),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 응용(applied) — 미지수를 구한다(solve-for-unknown · 스킬 연결 유형)
# ──────────────────────────────────────────────────────────────────────────
def _applied_frames() -> list[Frame]:
    slot = "applied"

    def a1(p: tuple[object, ...]) -> DiffItem | None:
        f, a0 = _as_poly(p[0]), _as_int(p[1])
        m = eval_at(derivative_of(f), a0)
        if m == 0:
            return None
        t = sympy.Symbol("t")
        found = _pick(
            _solve_real(sympy.diff(poly_to_sympy(f), _X).subs(_X, t) - m, t), lambda r: r > 0
        )
        if found != a0:
            return None
        n = 3 * m - 2  # 평행한 직선의 y절편(값은 답과 무관한 장식)
        return DiffItem(
            slot=slot,
            frame_id="applied-parallel-to-line",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 점 (a, f(a))에서의 접선이 직선 "
                f"y = {render_poly(((1, m), (0, n)))}에 평행할 때, 양수 a의 값을 구하시오."
            ),
            answer_text=str(a0),
            explanation=(
                f"평행한 두 직선의 기울기는 같으므로 접선의 기울기 f'(a)가 {m}이다. 도함수 "
                f"{render_poly(derivative_of(f))}에서 이를 만족하는 양수 a는 {a0}이다."
            ),
            conditions=(f"{_d(f, 'a')} = {m}", "a > 0"),
            answer_map=(("a", str(a0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a0),
        )

    def a2(p: tuple[object, ...]) -> DiffItem | None:
        f, a0, s = _as_poly(p[0]), _as_int(p[1]), _as_int(p[2])
        m = eval_at(derivative_of(f), a0)
        if m != s:
            return None
        t = sympy.Symbol("t")
        found = _pick(
            _solve_real(sympy.diff(poly_to_sympy(f), _X).subs(_X, t) - m, t), lambda r: r > 0
        )
        if found != a0:
            return None
        return DiffItem(
            slot=slot,
            frame_id="applied-perpendicular-to-line",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 점 (a, f(a))에서의 접선이 직선 "
                f"x + {s}y = {s + 1}에 수직일 때, 양수 a의 값을 구하시오."
            ),
            answer_text=str(a0),
            explanation=(
                f"직선 x + {s}y = {s + 1}의 기울기는 -1/{s}이고 수직인 직선의 기울기는 그 "
                f"음의 역수 {s}이다. f'(a)의 값이 {s}{i_ga(str(s))} 되는 양수 a는 {a0}이다."
            ),
            conditions=(f"{_d(f, 'a')} = {s}", "a > 0"),
            answer_map=(("a", str(a0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a0),
        )

    def a3(p: tuple[object, ...]) -> DiffItem | None:
        f, a0, px = _as_poly(p[0]), _as_int(p[1]), _as_int(p[2])
        if a0 <= 0 or px == a0:
            return None
        m, fa, _ = _tangent(f, a0)
        qy = fa + m * (px - a0)
        t = sympy.Symbol("t")
        f_t = poly_to_sympy(f).subs(_X, t)
        d_t = sympy.diff(poly_to_sympy(f), _X).subs(_X, t)
        found = _pick(_solve_real(f_t + d_t * (px - t) - qy, t), lambda r: r > 0)
        if found != a0:
            return None
        f_str = poly_to_sympy_str(f).replace("x", "a")
        d_str = poly_to_sympy_str(derivative_of(f)).replace("x", "a")
        point = f"({px}, {qy})"
        return DiffItem(
            slot=slot,
            frame_id="applied-tangent-passes-through-point",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 점 (a, f(a))에서의 접선이 점 {point}"
                f"{eul_reul(point)} "
                "지날 때, 양수 a의 값을 구하시오."
            ),
            answer_text=str(a0),
            explanation=(
                f"접선 y = f'(a)(x - a) + f(a)가 점 {point}{eul_reul(point)} 지나므로 "
                f"대입해 풀면 양수 a는 {a0}이다."
            ),
            conditions=(f"({f_str}) + ({d_str})*({px} - a) = {qy}", "a > 0"),
            answer_map=(("a", str(a0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a0),
        )

    def a4(p: tuple[object, ...]) -> DiffItem | None:
        lead, b, c0, a = (_as_int(v) for v in p)
        f = _poly({2: lead, 1: b, 0: c0})
        m, _, n = _tangent(f, a)
        # 문면의 곡선은 상수항이 미지수 c — 그래서 y절편 n이 주어지면 c가 정해진다.
        head = render_poly(_poly({2: lead, 1: b}))
        return DiffItem(
            slot=slot,
            frame_id="applied-intercept-given-find-constant",
            question_text=(
                f"곡선 y = {head} + c (c는 상수) 위의 x좌표가 {a}인 점에서의 접선의 y절편이 "
                f"{n}일 때, c의 값을 구하시오."
            ),
            answer_text=str(c0),
            explanation=(
                f"접선 y = {_line(m, n)}{wa_gwa(_line(m, n))} 곡선을 연립한 이차방정식이 "
                f"이중근을 가지므로 판별식이 0이다. 이를 c에 대해 풀면 c는 {c0}이다."
            ),
            conditions=f"(({b}) - ({m}))**2 - 4*({lead})*(c - ({n})) = 0",
            answer_map=(("c", str(c0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(c0),
        )

    def a5(p: tuple[object, ...]) -> DiffItem | None:
        lead, s = _as_int(p[0]), _as_int(p[1])
        # f(x) = lead x^2 + c, 접선이 원점을 지나려면 a^2 = c / lead (a > 0).
        c = lead * s * s
        f = _poly({2: lead, 0: c})
        return DiffItem(
            slot=slot,
            frame_id="applied-tangent-through-origin",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 점 (a, f(a))에서의 접선이 원점을 지날 때, "
                "양수 a의 값을 구하시오."
            ),
            answer_text=str(s),
            explanation=(
                f"접선 y = f'(a)(x - a) + f(a)에 원점을 대입하면 f(a) - a f'(a) = 0이다. "
                f"이를 풀면 양수 a는 {s}이다."
            ),
            conditions=(f"({lead}*a**2 + {c}) - a*({2 * lead}*a) = 0", "a > 0"),
            answer_map=(("a", str(s)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(s),
        )

    def a6(p: tuple[object, ...]) -> DiffItem | None:
        lead, b2, c1, a = (_as_int(v) for v in p)
        f = _poly({3: lead, 2: b2, 1: c1})
        # f'(x) = 3 lead x^2 + 2 b2 x + c1 은 대칭축 x = -b2 / (3 lead)에 대해 대칭이다.
        sym = sympy.Rational(-b2, 3 * lead)
        other = 2 * sym - a
        if not other.is_integer or other == a:
            return None
        b = int(other)
        m = eval_at(derivative_of(f), a)
        if eval_at(derivative_of(f), b) != m:
            return None
        fa_text = f"f'({a})"
        return DiffItem(
            slot=slot,
            frame_id="applied-parallel-tangent-at-other-point",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 x좌표가 {a}인 점에서의 접선과 평행한 접선을 "
                f"갖는 또 다른 점의 x좌표 b (b는 {a}{i_ga(str(a))} 아니다)의 값을 구하시오."
            ),
            answer_text=str(b),
            explanation=(
                f"평행하면 기울기가 같으므로 f'(b)의 값은 f'({a}){wa_gwa(fa_text)} 같은 {m}이다. "
                f"도함수 {render_poly(derivative_of(f))}에서 {a}{i_ga(str(a))} 아닌 근은 {b}이다."
            ),
            conditions=(f"{_d(f, 'b')} = {m}", f"b != {a}"),
            answer_map=(("b", str(b)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(b),
        )

    return [
        Frame("applied-parallel-to-line", _grid("p3-tan:a1", _mixed_pool()[::2], _POS_POINTS), a1),
        Frame(
            "applied-perpendicular-to-line",
            _grid("p3-tan:a2", _mixed_pool(), _POS_POINTS, (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)),
            a2,
        ),
        Frame(
            "applied-tangent-passes-through-point",
            _grid("p3-tan:a3", _quad_pool()[::3], _POS_POINTS, (-3, -2, -1, 0, 1, 2, 3, 5)),
            a3,
        ),
        Frame(
            "applied-intercept-given-find-constant",
            _grid("p3-tan:a4", (1, 2, -1, 3), tuple(range(-4, 5)), tuple(range(-5, 6)), _POINTS),
            a4,
        ),
        Frame(
            "applied-tangent-through-origin",
            _grid("p3-tan:a5", (1, 2, 3, -1), (1, 2, 3, 4, 5, 6)),
            a5,
        ),
        Frame(
            "applied-parallel-tangent-at-other-point",
            _grid("p3-tan:a6", (1, 2, -1), (-6, -3, 0, 3, 6, 9, -9), (-4, -2, 0, 1, 2, 3), _POINTS),
            a6,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 오개념 유발(misconception_trigger) — 기울기 계산 단계의 power-rule-step-omitted
# ──────────────────────────────────────────────────────────────────────────
def _wrong_slopes(f: Poly, a: int) -> tuple[int, int]:
    """항별 거듭제곱 미분에서 (계수 누락, 지수 감소 누락)이 만드는 *틀린* 기울기."""
    coeff_omitted = sum(c * a ** (e - 1) for e, c in f if e >= 1)
    exponent_kept = sum(c * e * a**e for e, c in f if e >= 1)
    return coeff_omitted, exponent_kept


def _mc_item(
    *,
    frame_id: str,
    text: str,
    correct: int,
    wrong: tuple[int, int],
    filler: int,
    conditions: str,
    answer_map: tuple[tuple[str, str], ...],
    explanation: str,
    shuffle_key: str,
    ptype: str = _EVAL,
) -> DiffItem | None:
    try:
        choices, answer, distractors = build_choices(
            [
                ChoiceEntry(str(correct), is_correct=True, sort_key=float(correct)),
                ChoiceEntry(str(wrong[0]), _KEBAB, sort_key=float(wrong[0])),
                ChoiceEntry(str(wrong[1]), _KEBAB, sort_key=float(wrong[1])),
                ChoiceEntry(str(filler), sort_key=float(filler)),
            ],
            shuffle_seed=shuffle_key,
        )
    except ValueError:
        return None
    return DiffItem(
        slot="misconception_trigger",
        frame_id=frame_id,
        question_text=text,
        answer_text=answer,
        explanation=explanation,
        conditions=conditions,
        answer_map=answer_map,
        problem_type_code=ptype,
        answer_format=AnswerFormat.실수,
        choices=choices,
        distractors=distractors,
    )


def _misconception_frames() -> list[Frame]:
    def m1(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _as_poly(p[0]), _as_int(p[1])
        m, fa, _ = _tangent(f, a)
        return _mc_item(
            frame_id="mc-slope-at-point",
            text=f"곡선 y = {render_poly(f)} 위의 점 ({a}, {fa})에서의 접선의 기울기는?",
            correct=m,
            wrong=_wrong_slopes(f, a),
            filler=fa,
            conditions=f"{_d(f, str(a))} = y",
            answer_map=(("y", str(m)),),
            explanation=(
                f"도함수는 {render_poly(derivative_of(f))}이므로 x가 {a}일 때의 접선의 "
                f"기울기는 {m}이다."
            ),
            shuffle_key=f"mc1:{render_poly(f)}:{a}",
        )

    def m2(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _as_poly(p[0]), _as_int(p[1])
        m, fa, _ = _tangent(f, a)
        return _mc_item(
            frame_id="mc-slope-at-x-coordinate",
            text=f"곡선 y = {render_poly(f)}의 x좌표가 {a}인 점에서의 접선의 기울기로 옳은 것은?",
            correct=m,
            wrong=_wrong_slopes(f, a),
            filler=fa,
            conditions=f"{_d(f, str(a))} = y",
            answer_map=(("y", str(m)),),
            explanation=(
                f"도함수는 {render_poly(derivative_of(f))}이므로 x가 {a}일 때의 접선의 "
                f"기울기는 {m}이다."
            ),
            shuffle_key=f"mc2:{render_poly(f)}:{a}",
        )

    def m3(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _as_poly(p[0]), _as_int(p[1])
        m, fa, k = _tangent(f, a)
        w1, w2 = _wrong_slopes(f, a)
        return _mc_item(
            frame_id="mc-y-intercept-of-tangent",
            text=f"곡선 y = {render_poly(f)} 위의 점 ({a}, {fa})에서의 접선의 y절편은?",
            correct=k,
            wrong=(fa - a * w1, fa - a * w2),
            filler=fa,
            conditions=f"({fa}) - ({a})*({m}) = y",
            answer_map=(("y", str(k)),),
            explanation=(f"기울기는 {m}이고 접선은 {_pt_slope(m, a, fa)}이므로 y절편은 {k}이다."),
            shuffle_key=f"mc3:{render_poly(f)}:{a}",
        )

    def m4(p: tuple[object, ...]) -> DiffItem | None:
        f, a, t = _as_poly(p[0]), _as_int(p[1]), _as_int(p[2])
        if t == a:
            return None
        m, fa, _ = _tangent(f, a)
        w1, w2 = _wrong_slopes(f, a)
        value = fa + m * (t - a)
        return _mc_item(
            frame_id="mc-tangent-line-value",
            text=(
                f"곡선 y = {render_poly(f)} 위의 점 ({a}, {fa})에서의 접선의 방정식을 "
                f"y = g(x)라 할 때, g({t})의 값은?"
            ),
            correct=value,
            wrong=(fa + w1 * (t - a), fa + w2 * (t - a)),
            filler=eval_at(f, t),
            conditions=f"({fa}) + ({m})*(({t}) - ({a})) = y",
            answer_map=(("y", str(value)),),
            explanation=(
                f"접선은 {_pt_slope(m, a, fa)}이므로 g({t}){eun_neun(f'g({t})')} {value}이다."
            ),
            shuffle_key=f"mc4:{render_poly(f)}:{a}:{t}",
        )

    def m5(p: tuple[object, ...]) -> DiffItem | None:
        s = _as_int(p[0])
        a0 = s * s
        b = 2 * a0
        entries = [
            ChoiceEntry(str(a0), is_correct=True, sort_key=float(a0)),
            ChoiceEntry(str(b), _KEBAB, sort_key=float(b)),  # (x^2)'를 x로 쓴 경우
            ChoiceEntry(str(s), _KEBAB, sort_key=float(s)),  # (x^2)'를 2x^2으로 쓴 경우
            ChoiceEntry(str(sympy.Rational(a0, 2)), sort_key=a0 / 2),
        ]
        try:
            choices, answer, distractors = build_choices(entries, shuffle_seed=f"mc5:{s}")
        except ValueError:
            return None
        return DiffItem(
            slot="misconception_trigger",
            frame_id="mc-find-point-on-parabola",
            question_text=(
                f"곡선 y = x^2 위의 점 (a, a^2)에서의 접선의 기울기가 {b}일 때, a의 값은?"
            ),
            answer_text=answer,
            explanation=(
                f"x^2의 도함수는 2x이므로 2a{i_ga('2a')} {b}{i_ga(str(b))} 되는 a는 " f"{a0}이다."
            ),
            conditions=f"Derivative(x**2, x).doit().subs(x, a) = {b}",
            answer_map=(("a", str(a0)),),
            problem_type_code=_SOLVE,
            answer_format=AnswerFormat.자연수,
            choices=choices,
            distractors=distractors,
        )

    def m6(p: tuple[object, ...]) -> DiffItem | None:
        a0 = _as_int(p[0])
        b = 3 * a0 * a0
        wrong_coeff = sympy.sqrt(b)  # (x^3)'를 x^2로 쓴 학생이 얻는 a
        entries = [
            ChoiceEntry(str(a0), is_correct=True, sort_key=float(a0)),
            ChoiceEntry(str(sympy.sstr(wrong_coeff)), _KEBAB, sort_key=float(wrong_coeff)),
        ]
        cube_root = round(a0 ** (2 / 3))
        if cube_root**3 == a0 * a0 and cube_root != a0:
            entries.append(ChoiceEntry(str(cube_root), _KEBAB, sort_key=float(cube_root)))
            entries.append(ChoiceEntry(str(a0 * a0), sort_key=float(a0 * a0)))
        else:
            entries.append(ChoiceEntry(str(a0 * a0), sort_key=float(a0 * a0)))
            entries.append(ChoiceEntry(str(3 * a0), sort_key=float(3 * a0)))
        try:
            choices, answer, distractors = build_choices(entries, shuffle_seed=f"mc6:{a0}")
        except ValueError:
            return None
        return DiffItem(
            slot="misconception_trigger",
            frame_id="mc-find-point-on-cubic",
            question_text=(
                f"곡선 y = x^3 위의 점 (a, a^3) (a > 0)에서의 접선의 기울기가 {b}일 때, "
                "a의 값은?"
            ),
            answer_text=answer,
            explanation=(
                f"x^3의 도함수는 3x^2이므로 3a^2{i_ga('3a^2')} {b}{i_ga(str(b))} 되는 양수 a는 "
                f"{a0}이다."
            ),
            conditions=(f"Derivative(x**3, x).doit().subs(x, a) = {b}", "a > 0"),
            answer_map=(("a", str(a0)),),
            problem_type_code=_SOLVE,
            answer_format=AnswerFormat.실수,
            choices=choices,
            distractors=distractors,
        )

    pool = tuple(
        _poly({n: lead, 1: c}) for n in (3, 4, 5) for lead in (1, 2, -1) for c in (-3, -1, 2, 4)
    )
    pts = (1, 2, 3, -1, -2)
    return [
        Frame("mc-slope-at-point", _grid("p3-tan:m1", pool, pts), m1),
        Frame("mc-slope-at-x-coordinate", _grid("p3-tan:m2", pool, pts), m2),
        Frame("mc-y-intercept-of-tangent", _grid("p3-tan:m3", pool, pts), m3),
        Frame("mc-tangent-line-value", _grid("p3-tan:m4", pool, pts, (-2, 0, 3, 4)), m4),
        Frame("mc-find-point-on-parabola", _grid("p3-tan:m5", (2, 3, 4, 5, 6, 7, 8)), m5),
        Frame("mc-find-point-on-cubic", _grid("p3-tan:m6", (2, 3, 4, 5, 6, 8, 27)), m6),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 진단(diagnostic) — 접선의 기울기 = 미분계수라는 핵심 사실을 한 가지씩 확인
# ──────────────────────────────────────────────────────────────────────────
def _diagnostic_frames() -> list[Frame]:
    slot = "diagnostic"

    def d1(p: tuple[object, ...]) -> DiffItem | None:
        lead, half = _as_int(p[0]), _as_int(p[1])
        b = -2 * lead * half
        f = _poly({2: lead, 1: b, 0: 3})
        return DiffItem(
            slot=slot,
            frame_id="diag-slope-at-vertex",
            question_text=(f"곡선 y = {render_poly(f)}의 꼭짓점에서의 접선의 기울기를 구하시오."),
            answer_text="0",
            explanation=(
                f"꼭짓점의 x좌표는 {half}이고 그 점에서 도함수의 값은 0이므로 접선의 기울기는 "
                "0이다."
            ),
            conditions=f"{_d(f, str(half))} = y",
            answer_map=(("y", "0"),),
            problem_type_code=_EVAL,
            answer_format=AnswerFormat.실수,
        )

    def d2(p: tuple[object, ...]) -> DiffItem | None:
        m, n, a = _as_int(p[0]), _as_int(p[1]), _as_int(p[2])
        f = _poly({1: m, 0: n})
        return _slope_item(
            slot=slot,
            frame_id="diag-slope-of-line",
            text=(
                f"직선 y = {render_poly(f)} 위의 점 ({a}, {eval_at(f, a)})에서의 접선의 "
                "기울기를 구하시오."
            ),
            f=f,
            a=a,
        )

    def d3(p: tuple[object, ...]) -> DiffItem | None:
        c, a = _as_int(p[0]), _as_int(p[1])
        f: Poly = ((0, c),)
        return DiffItem(
            slot=slot,
            frame_id="diag-slope-of-constant-curve",
            question_text=(f"곡선 y = {c} 위의 점 ({a}, {c})에서의 접선의 기울기를 구하시오."),
            answer_text="0",
            explanation="상수함수의 도함수는 0이므로 접선의 기울기는 0이다.",
            conditions=f"{_d(f, str(a))} = y",
            answer_map=(("y", "0"),),
            problem_type_code=_EVAL,
            answer_format=AnswerFormat.실수,
        )

    def d4(p: tuple[object, ...]) -> DiffItem | None:
        f = _as_poly(p[0])
        if not any(e == 1 for e, _ in f):
            return None
        return _slope_item(
            slot=slot,
            frame_id="diag-slope-at-y-axis",
            text=(
                f"곡선 y = {render_poly(f)}{i_ga(render_poly(f))} y축과 만나는 점에서의 접선의 "
                "기울기를 구하시오."
            ),
            f=f,
            a=0,
        )

    def d5(p: tuple[object, ...]) -> DiffItem | None:
        lead, half = _as_int(p[0]), _as_int(p[1])
        b = -2 * lead * half
        f = _poly({2: lead, 1: b})
        return DiffItem(
            slot=slot,
            frame_id="diag-horizontal-tangent-point",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 점 중 접선이 x축에 평행한 점의 x좌표를 "
                "구하시오."
            ),
            answer_text=str(half),
            explanation=(
                f"접선이 x축에 평행하면 기울기가 0이므로 f'(x) = {render_poly(derivative_of(f))}"
                f" = 0에서 x는 {half}이다."
            ),
            conditions=f"{_d(f, 'a')} = 0",
            answer_map=(("a", str(half)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(half),
        )

    def d6(p: tuple[object, ...]) -> DiffItem | None:
        n = _as_int(p[0])
        f: Poly = ((n, 1),)
        return DiffItem(
            slot=slot,
            frame_id="diag-slope-at-origin-of-power",
            question_text=f"곡선 y = x^{n} 위의 원점에서의 접선의 기울기를 구하시오.",
            answer_text="0",
            explanation=(
                f"도함수 {render_poly(derivative_of(f))}에 x = 0을 대입하면 0이므로 접선의 "
                "기울기는 0이다."
            ),
            conditions=f"{_d(f, '0')} = y",
            answer_map=(("y", "0"),),
            problem_type_code=_EVAL,
            answer_format=AnswerFormat.실수,
        )

    return [
        Frame(
            "diag-slope-at-vertex",
            _grid("p3-tan:d1", (1, 2, -1, 3, -2), (-3, -2, -1, 1, 2, 3, 4)),
            d1,
        ),
        Frame(
            "diag-slope-of-line",
            _grid("p3-tan:d2", (-4, -3, -2, -1, 1, 2, 3, 4), (-5, -2, 0, 1, 3, 6), (-1, 0, 1, 2)),
            d2,
        ),
        Frame(
            "diag-slope-of-constant-curve",
            _grid("p3-tan:d3", (-4, -2, 1, 3, 5, 7), (-2, -1, 0, 1, 2, 3)),
            d3,
        ),
        Frame("diag-slope-at-y-axis", _grid("p3-tan:d4", _mixed_pool()[::3]), d4),
        Frame(
            "diag-horizontal-tangent-point",
            _grid("p3-tan:d5", (1, 2, -1, 3, -2), (-3, -2, -1, 1, 2, 3, 4)),
            d5,
        ),
        Frame("diag-slope-at-origin-of-power", _grid("p3-tan:d6", (2, 3, 4, 5, 6, 7, 8)), d6),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 숙련도 확인(mastery_check) — 접점 이중근 항등식·통과점·넓이로 묶는다
# ──────────────────────────────────────────────────────────────────────────
def _mastery_frames() -> list[Frame]:
    slot = "mastery_check"

    def k1(p: tuple[object, ...]) -> DiffItem | None:
        m, c, root = _as_int(p[0]), _as_int(p[1]), _as_int(p[2])
        # y = x^2 + p x + c 와 y = m x + n 이 접하면 (p - m)^2 = 4(c - n). c - n = root^2.
        n = c - root * root
        p_big = m + 2 * root
        return DiffItem(
            slot=slot,
            frame_id="mastery-line-tangent-find-coefficient",
            question_text=(
                f"직선 y = {_line(m, n)}{i_ga(_line(m, n))} 곡선 y = x^2 + px {_signed(c)}에 "
                f"접할 때, 상수 p의 값을 구하시오. (단, p > {m})"
            ),
            answer_text=str(p_big),
            explanation=(
                f"직선과 곡선을 연립한 이차방정식이 접점에서 이중근을 가져야 하므로 판별식 "
                f"(p - {m})^2 = 4 * {c - n}이다. 이를 풀면 p는 {m + 2 * root} 또는 "
                f"{m - 2 * root}이고 "
                f"p > {m}이므로 {p_big}이다."
            ),
            conditions=(f"(p - ({m}))**2 - 4*(({c}) - ({n})) = 0", f"p > {m}"),
            answer_map=(("p", str(p_big)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(p_big),
        )

    def k2(p: tuple[object, ...]) -> DiffItem | None:
        f, m = _as_poly(p[0]), _as_int(p[1])
        lead, b, c = _quad_parts(f)
        # 접점 x좌표 a = (m - b) / (2 lead) 가 정수일 때만.
        if (m - b) % (2 * lead) != 0 or m == 0:
            return None
        a = (m - b) // (2 * lead)
        _, _, k = _tangent(f, a)
        return DiffItem(
            slot=slot,
            frame_id="mastery-line-tangent-find-intercept",
            question_text=(
                f"직선 y = {_line_with_k(m)}가 곡선 y = {render_poly(f)}에 접할 때, 상수 k의 "
                "값을 구하시오."
            ),
            answer_text=str(k),
            explanation=(
                f"직선과 곡선을 연립한 이차방정식이 이중근을 가지므로 판별식이 0이다. 접점의 "
                f"x좌표는 {a}이고 k는 {k}이다."
            ),
            conditions=_disc_cond(lead, b, c, m, "k"),
            answer_map=(("k", str(k)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(k),
        )

    def k3(p: tuple[object, ...]) -> DiffItem | None:
        b, c, a1, a2 = (_as_int(v) for v in p)
        if a1 >= a2 or (a1 + a2) % 2 != 0:
            return None
        f = _poly({2: 1, 1: b, 0: c})
        m1, m2 = eval_at(derivative_of(f), a1), eval_at(derivative_of(f), a2)
        px = (a1 + a2) // 2
        # 두 접선의 교점 P — 접선 1에 x = px 대입(SymPy 값).
        py = eval_at(f, a1) + m1 * (px - a1)
        if eval_at(f, a2) + m2 * (px - a2) != py:
            return None
        through = _pt_form("m", px, py)
        return DiffItem(
            slot=slot,
            frame_id="mastery-tangent-from-external-point",
            question_text=(
                f"점 ({px}, {py})에서 곡선 y = {render_poly(f)}에 그은 두 접선 중 기울기가 "
                "더 큰 접선의 기울기를 구하시오."
            ),
            answer_text=str(m2),
            explanation=(
                f"점을 지나는 직선 {through}{wa_gwa(through)} 곡선을 연립한 이차방정식이 "
                f"이중근을 "
                f"가지려면 판별식이 0이어야 한다. 두 접선의 기울기는 {m1}, {m2}이고 큰 것은 "
                f"{m2}이다."
            ),
            conditions=(
                f"(({b}) - m)**2 - 4*(({c}) - ({py}) + m*({px})) = 0",
                f"m > {(m1 + m2) // 2}",
            ),
            answer_map=(("m", str(m2)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(m2),
        )

    def k4(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _as_poly(p[0]), _as_int(p[1])
        m, fa, k = _tangent(f, a)
        if m == 0 or k == 0:
            return None
        xi = sympy.Rational(a) - sympy.Rational(fa, m)
        area = sympy.Rational(1, 2) * abs(sympy.Integer(k)) * abs(xi)
        if not area.is_integer:
            return None
        return _echo_item(
            slot=slot,
            frame_id="mastery-triangle-area-with-axes",
            text=(
                f"곡선 y = {render_poly(f)} 위의 점 ({a}, {fa})에서의 접선과 x축, y축으로 "
                "둘러싸인 삼각형의 넓이를 구하시오."
            ),
            value=int(area),
            explanation=(
                f"접선은 y = {_line(m, k)}이고 y절편의 절댓값은 {abs(k)}, "
                f"x절편의 절댓값은 {abs(xi)}이므로 "
                f"삼각형의 넓이는 (1/2)*{abs(k)}*{abs(xi)} = {int(area)}이다."
            ),
            expr=f"(1/2)*Abs({k})*Abs(({a}) - ({fa})/({m}))",
            ptype=_EVAL,
        )

    def k5(p: tuple[object, ...]) -> DiffItem | None:
        a, p0, lead = (_as_int(v) for v in p)
        if a == 0 or p0 == 0:
            return None
        # y = lead x^3 + p x^2 : 점 x = a 에서의 접선의 y절편 n = -2 lead a^3 - p a^2.
        n = -2 * lead * a**3 - p0 * a * a
        curve = lead * _X**3 + sympy.Symbol("p") * _X**2
        f_a = curve.subs(_X, a)
        d_a = sympy.diff(curve, _X).subs(_X, a)  # 도함수도 SymPy 경로(손 공식 금지)
        cond = sympy.sstr(sympy.expand(f_a - a * d_a))
        lead_text = "" if lead == 1 else str(lead)
        return DiffItem(
            slot=slot,
            frame_id="mastery-cubic-intercept-find-coefficient",
            question_text=(
                f"곡선 y = {lead_text}x^3 + px^2 위의 x좌표가 {a}인 점에서의 접선의 y절편이 "
                f"{n}일 때, 상수 p의 값을 구하시오."
            ),
            answer_text=str(p0),
            explanation=(
                f"접점 ({a}, f({a}))에서의 접선의 y절편은 f({a}) - {a}*f'({a})이고 "
                f"이것이 {n}{i_ga(str(n))} "
                f"되도록 p를 정하면 p는 {p0}이다."
            ),
            conditions=f"{cond} = {n}",
            answer_map=(("p", str(p0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(p0),
        )

    def k6(p: tuple[object, ...]) -> DiffItem | None:
        q0, a, g_lead, g_c = (_as_int(v) for v in p)
        # y = x^2 + p0 x + q 와 y = g(x) = g_lead x^3 + g_c x 가 x = a 에서 접한다
        # (p0는 기울기 일치로 결정).
        g = _poly({3: g_lead, 1: g_c})
        slope = eval_at(derivative_of(g), a)
        p0 = slope - 2 * a
        if p0 == 0:
            return None
        q = eval_at(g, a) - a * a - p0 * a
        if q != q0:
            return None
        return DiffItem(
            slot=slot,
            frame_id="mastery-two-curves-touch-find-constant",
            question_text=(
                f"곡선 y = x^2 {_signed(p0, 'x')} + q가 곡선 y = {render_poly(g)}"
                f"{wa_gwa(render_poly(g))} "
                f"x = {a}인 점에서 접할 때, 상수 q의 값을 구하시오."
            ),
            answer_text=str(q),
            explanation=(
                f"x = {a}에서 두 곡선이 접하므로 접선의 기울기와 y좌표가 모두 같다. "
                f"기울기는 {slope}이고 y좌표 {eval_at(g, a)}{i_ga(str(eval_at(g, a)))} 같아지도록 "
                f"q를 정하면 q는 {q}이다."
            ),
            conditions=f"{a}**2 + ({p0})*{a} + q = {eval_at(g, a)}",
            answer_map=(("q", str(q)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(q),
        )

    k6_params: list[tuple[object, ...]] = []
    for g_lead in (1, 2, -1):
        for g_c in (-3, -1, 1, 2, 4):
            g = _poly({3: g_lead, 1: g_c})
            for a in (-2, -1, 1, 2, 3):
                p0 = eval_at(derivative_of(g), a) - 2 * a
                q = eval_at(g, a) - a * a - p0 * a
                k6_params.append((q, a, g_lead, g_c))
    return [
        Frame(
            "mastery-line-tangent-find-coefficient",
            _grid("p3-tan:k1", (-3, -2, -1, 1, 2, 3), (-3, -1, 1, 2, 4, 5), (1, 2, 3, 4)),
            k1,
        ),
        Frame(
            "mastery-line-tangent-find-intercept",
            _grid("p3-tan:k2", _quad_pool(), tuple(range(-6, 9))),
            k2,
        ),
        Frame(
            "mastery-tangent-from-external-point",
            _grid(
                "p3-tan:k3",
                (-4, -2, 0, 2, 4),
                (-3, -1, 1, 3),
                (-3, -2, -1, 0, 1, 2),
                (0, 1, 2, 3, 4, 5),
            ),
            k3,
        ),
        Frame(
            "mastery-triangle-area-with-axes", _grid("p3-tan:k4", _cubic_pool()[::7], _POINTS), k4
        ),
        Frame(
            "mastery-cubic-intercept-find-coefficient",
            _grid("p3-tan:k5", (-3, -2, -1, 1, 2, 3), (-4, -3, -2, -1, 1, 2, 3, 4), (1, 2, -1)),
            k5,
        ),
        Frame(
            "mastery-two-curves-touch-find-constant",
            tuple(seeded_order("p3-tan:k6", k6_params)),
            k6,
        ),
    ]


def _signed(value: int, var: str = "") -> str:
    """'+ 3' / '- 3' (var가 있으면 '+ 3x') — 문면에서 상수항을 이어 붙일 때."""
    magnitude = abs(value)
    body = f"{'' if magnitude == 1 and var else magnitude}{var}"
    return f"{'-' if value < 0 else '+'} {body}"


def _line_with_k(m: int) -> str:
    return f"{render_poly(((1, m),))} + k"


_SLOT_FRAMES = {
    "representative": _rep_frames,
    "basic": _basic_frames,
    "applied": _applied_frames,
    "misconception_trigger": _misconception_frames,
    "diagnostic": _diagnostic_frames,
    "mastery_check": _mastery_frames,
}


class P3DiffTangentLineGenerator(P3DiffSlotGenerator):
    """[12미적Ⅰ-02-05] 접선의 방정식 — 슬롯 6종 결정론 생성기."""

    standard_code: ClassVar[str] = "[12미적Ⅰ-02-05]"
    concept_src_id: ClassVar[str] = "H:12미적Ⅰ02-05"
    unit_code: ClassVar[str] = "P3-CALC1-DIFF-TANGENT-LINE"
    slug_prefix: ClassVar[str] = "wm-p3-diff-tangent"
    slot_difficulty: ClassVar[dict[str, float]] = {
        "representative": 2.5,
        "basic": 2.5,
        "applied": 3.5,
        "misconception_trigger": 3.0,
        "diagnostic": 2.0,
        "mastery_check": 4.0,
    }
    slot_count: ClassVar[int] = 12

    @classmethod
    def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
        return round_robin_items(_SLOT_FRAMES[slot](), cls.slot_count, claimed=claimed)
