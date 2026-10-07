"""[12미적Ⅰ-02-05] 접선의 방정식 결정론 문항 생성기 — P3-03(결정론·LLM 0).

개념: `H:12미적Ⅰ02-05`(`math.calculus.jeopseonui-bangjeongsik`). 명세 probe_note —
"접선 조건을 '접점에서 이중근' 항등식으로 써야 한다(표본 검증)". 그래서 이 파일은 검산 재료를 두
갈래로 쓴다.

  · **미분 평가형** — `Derivative(식, x).doit().subs(x, 점) = 값`(접선의 기울기 = 미분계수).
  · **이중근(판별식)형** — 이차 곡선 y = Ax^2 + bx + c와 직선 y = mx + k가 접하면 연립한 이차식
    Ax^2 + (b - m)x + (c - k)가 이중근을 가지므로 판별식 (b - m)^2 - 4A(c - k) = 0이다.
    이 조건은 *미분을 쓰지 않는다* — 생성기가 `sympy.diff`로 구한 접선(기울기 m)과 **독립인 경로**로
    k를 다시 확인하는 검산이다(두 경로가 어긋나면 수용 게이트가 거부). 숙련도 슬롯의 **삼차** 곡선
    (3차 감사 bad_tag 처분 — 이차 곡선의 접할 조건은 판별식만으로 풀려 미분이 필요 없었다)도 같은
    원리로 *곡선 - 직선의 x에 대한 판별식 = 0*을 미지 상수 하나의 다항식으로 쓴다
    (`_cubic_double_root_conditions` — 다른 접선의 상수는 `!=` 보호 조건으로 뺀다). 학생 풀이는
    미분(접점의 미분계수)이고, 판별식은 검산 경로일 뿐이다.
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
    render_affine,
    render_difference,
    render_factored,
    render_poly,
    render_sum,
    render_surd,
    with_eul_reul,
    with_eun_neun,
    with_i_ga,
    with_wa_gwa,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    ChoiceEntry,
    DiffItem,
    Frame,
    P3DiffSlotGenerator,
    answer_format_for,
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
def _fmt(value: object) -> AnswerFormat:
    """정답 형식 — 기반의 단일 규칙(`answer_format_for`)을 따른다."""
    return answer_format_for(str(value))


def _var_poly(f: Poly, var: str) -> str:
    """다항식을 다른 변수 이름으로 표기('a^2 - 3a') — 해설에서 미지수 식을 보일 때."""
    return render_poly(f, var)


def _minus_const(f: Poly, value: int) -> Poly:
    """f - value(상수)를 정규화한 다항식 — 'f'(a) = m'을 'f'(a) - m = 0'으로 옮길 때."""
    terms = dict(f)
    terms[0] = terms.get(0, 0) - value
    return tuple(sorted(((e, c) for e, c in terms.items() if c), reverse=True))


def _solve_steps(lhs: Poly, value: int, var: str) -> str:
    """'(식) = 값, 즉 (인수분해) = 0' — 미지수 방정식의 중간 단계(2차 감사: 결론만 해설 교정)."""
    moved = _minus_const(lhs, value)
    return f"{_var_poly(lhs, var)} = {value}, 즉 {render_factored(moved, var)} = 0"


def _disc_steps(lead: int, b: int, c: int, m: int, unknown: str) -> str:
    """접선 판별식의 중간 단계 — 연립한 이차방정식과 판별식 = 0을 숫자로 보인다.

    곡선 y = lead x^2 + b x + c와 직선 y = m x + (unknown)을 연립하면
    lead x^2 + (b - m) x + (c - unknown) = 0이고, 접하려면 판별식
    (b - m)^2 - 4·lead·(c - unknown) = 0이다. unknown은 'k'(직선의 y절편)다.
    """
    q = b - m
    quad = render_poly(((2, lead), (1, q), (0, c)))
    four = 4 * lead
    tail = render_affine(c, -1, unknown)
    disc = f"{q * q} - {four}({tail}) = 0" if four > 0 else f"{q * q} + {-four}({tail}) = 0"
    return (
        f"연립하면 {quad} - {unknown} = 0이고, 접하려면 이 이차방정식이 이중근을 가져야 하므로 "
        f"판별식이 0이다. {disc}"
    )


def _cubic_double_root_conditions(
    curve: sympy.Expr, line: sympy.Expr, unknown: str, answer: int
) -> str | tuple[str, ...] | None:
    """삼차 곡선과 직선(미지 상수 하나)이 접할 조건 — x에 대한 판별식 = 0(미분을 쓰지 않는 경로).

    곡선 - 직선이 x에 대한 삼차식이므로 *이중근을 갖는다 ⇔ 판별식 = 0*이다(실계수 삼차식은 허근이
    짝으로 나오므로 이중근은 실근이다 — 곧 접점). 판별식은 미지 상수 `unknown`에 대한 다항식이 되고,
    그 실근이 *곡선에 접하는 직선*의 상수 전부다. 정답 외의 실근이 있으면 보호 조건을 붙여 목록으로
    내고(섀도 채점 단일 미지수 계약 — 부등식 보호가 붙은 목록), 실근이 정답 하나뿐이면 문자열 하나로
    낸다. 보호 조건은 다른 근이 정수면 `unknown != 근`(그 접선 하나만 정확히 뺀다), 정수가 아니면
    정답과 그 근 사이의 정수 경계(`unknown > ⌈근⌉`·`unknown < ⌊근⌋`)다. 정답이 실근이 아니거나 경계
    정수가 정답과 겹치면 None(그 파라미터는 건너뛴다).
    """
    u = sympy.Symbol(unknown)
    disc = sympy.expand(sympy.discriminant(sympy.expand(curve - line), _X))
    if disc.free_symbols != {u}:
        return None  # pragma: no cover — 구성 오류
    roots = sorted(set(sympy.real_roots(sympy.Poly(disc, u))), key=lambda r: float(r))
    if sympy.Integer(answer) not in roots:
        return None  # pragma: no cover — 구성 오류(정답이 접선 상수가 아니다)
    guards: list[str] = []
    for r in (r for r in roots if r != answer):
        if r.is_integer:
            guards.append(f"{unknown} != {r}")
        elif r < answer:
            bound = int(sympy.ceiling(r))
            if bound >= answer:
                return None
            guards.append(f"{unknown} > {bound}")
        else:
            bound = int(sympy.floor(r))
            if bound <= answer:
                return None
            guards.append(f"{unknown} < {bound}")
    cond = f"{sympy.sstr(disc)} = 0"
    return (cond, *guards) if guards else cond


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


def _render_with_param(base: Poly, exp: int, coef: int = 1) -> tuple[str, str]:
    """base + coef·p·x^exp(미지 계수) — (사람이 읽는 표기, SymPy 표기).

    base에 x^exp 항이 없어야 한다.
    """
    terms: list[tuple[int, int | None]] = [(e, c) for e, c in base]
    terms.append((exp, None))
    terms.sort(key=lambda t: t[0], reverse=True)
    human: list[str] = []
    symbolic: list[str] = []
    for index, (e, c) in enumerate(terms):
        if c is None:
            lead = "" if coef == 1 else str(coef)
            h_body = f"{lead}p" if e == 0 else (f"{lead}px^{e}" if e > 1 else f"{lead}px")
            s_lead = "" if coef == 1 else f"{coef}*"
            s_body = f"{s_lead}p" if e == 0 else (f"{s_lead}p*x**{e}" if e > 1 else f"{s_lead}p*x")
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
                f"접선의 기울기는 접점에서의 미분계수이므로 도함수 "
                f"{render_poly(derivative_of(f))}에 x = {with_eul_reul(a)} 대입한 {m}이다. 접선을 "
                f"y = {render_poly(((1, m),))} + k라 두고 곡선과 "
                f"{_disc_steps(lead, b, c, m, 'k')}에서 k = {k}이다."
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
            explanation=(
                f"도함수 {render_poly(derivative_of(f))}에 x = {with_eul_reul(a)} 대입하면 "
                "기울기는 "
                f"{m}이므로 접선은 {_pt_slope(m, a, fa)}이다. 따라서 g({t}) = {value}이다."
            ),
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
                f"접선의 기울기는 미분계수이다. y' = "
                f"{_render_with_param(derivative_of(base), 1, 2)[0]}이므로 x = {a}에서의 기울기는 "
                f"{render_poly(((1, 2 * a), (0, eval_at(derivative_of(base), a))), 'p')}이다. "
                f"이 값이 {with_i_ga(m)} 되어야 하므로 "
                f"{render_poly(((1, 2 * a), (0, eval_at(derivative_of(base), a))), 'p')} = {m}에서 "
                f"p = {p0}이다."
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
                f"도함수는 y' = {render_poly(derivative_of(f))}이므로 x좌표가 a인 점에서의 접선의 "
                f"기울기는 {_var_poly(derivative_of(f), 'a')}이다. "
                f"{_solve_steps(derivative_of(f), m, 'a')}이고 a는 양수이므로 a = {a0}이다."
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
                f"두 점에서의 접선의 기울기는 각각 미분계수 f'({a}){wa_gwa(fa_text)} f'({b})이다. "
                f"f'(x) = {render_poly(derivative_of(f))}이므로 f'({a}) + f'({b})의 값은 "
                f"{render_sum(eval_at(derivative_of(f), a), eval_at(derivative_of(f), b))} = "
                f"{total}이다."
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
                f"곡선 y = {render_poly(f)} 위의 x좌표가 {b}인 점에서의 접선의 기울기에서 x좌표가 "
                f"{a}인 점에서의 접선의 기울기를 뺀 값을 구하시오."
            ),
            answer_text=str(diff),
            explanation=(
                f"두 접선의 기울기는 미분계수 f'({b}){wa_gwa(f"f'({b})")} f'({a})이다. "
                f"f'(x) = {render_poly(derivative_of(f))}이므로 f'({b}) - f'({a})의 값은 "
                f"{render_difference(eval_at(derivative_of(f), b), eval_at(derivative_of(f), a))} "
                f"= {diff}이다."
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
            explanation=(
                f"도함수 {render_poly(derivative_of(f))}에 x = {with_eul_reul(a)} 대입하면 "
                "기울기는 "
                f"{m}이므로 접선은 {_pt_slope(m, a, fa)}이다. x = 0을 대입하면 y좌표는 {k}이다."
            ),
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
            explanation=(
                f"도함수 {render_poly(derivative_of(f))}에 x = {with_eul_reul(a)} 대입하면 m = "
                f"{m}이다. "
                f"접선 {_pt_slope(m, a, fa)}{eul_reul(_pt_slope(m, a, fa))} 정리하면 "
                f"y = {_line(m, k)}이므로 n = {k}이다. "
                f"따라서 m + n = {render_sum(m, k)} = {m + k}이다."
            ),
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
            explanation=(
                f"도함수 {render_poly(derivative_of(f))}에 x = {with_eul_reul(a)} 대입하면 "
                "기울기는 "
                f"{m}이므로 접선은 {_pt_slope(m, a, fa)}이다. y = 0을 대입하면 x좌표는 "
                f"{int(xi)}이다."
            ),
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
                f"함수 f(x) = {render_poly(f)}에 대하여 곡선 y = f(x) "
                f"위의 점 (a, f(a))에서의 접선이 직선 "
                f"y = {render_poly(((1, m), (0, n)))}에 평행할 때, 양수 a의 값을 구하시오."
            ),
            answer_text=str(a0),
            explanation=(
                f"평행한 두 직선의 기울기는 같으므로 접선의 기울기 f'(a)가 {m}이다. "
                f"f'(x) = {render_poly(derivative_of(f))}이므로 "
                f"{_solve_steps(derivative_of(f), m, 'a')}이고 a는 양수이므로 a = {a0}이다."
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
                f"함수 f(x) = {render_poly(f)}에 대하여 곡선 y = f(x) "
                f"위의 점 (a, f(a))에서의 접선이 직선 "
                f"x + {s}y = {s + 1}에 수직일 때, 양수 a의 값을 구하시오."
            ),
            answer_text=str(a0),
            explanation=(
                f"직선 x + {s}y = {s + 1}의 기울기는 -1/{s}이고, 수직인 두 직선의 기울기의 곱은 "
                f"-1이므로 접선의 기울기 f'(a)는 {s}이다. f'(x) = {render_poly(derivative_of(f))}"
                f"이므로 {_solve_steps(derivative_of(f), s, 'a')}이고 a는 양수이므로 a = {a0}이다."
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
        # 해설용: f(a) + f'(a)(px - a) - qy = 0을 a에 대한 다항식으로(SymPy 전개).
        a_sym = sympy.Symbol("a")
        through_poly = poly_from_sympy(
            sympy.expand(
                poly_to_sympy(f, "a") + poly_to_sympy(derivative_of(f), "a") * (px - a_sym) - qy
            ),
            "a",
        )
        return DiffItem(
            slot=slot,
            frame_id="applied-tangent-passes-through-point",
            question_text=(
                f"함수 f(x) = {render_poly(f)}에 대하여 곡선 y = f(x) "
                f"위의 점 (a, f(a))에서의 접선이 점 {point}"
                f"{eul_reul(point)} "
                "지날 때, 양수 a의 값을 구하시오."
            ),
            answer_text=str(a0),
            explanation=(
                f"접선 y = f'(a)(x - a) + f(a)가 점 {point}{eul_reul(point)} 지나므로 "
                f"{qy} = f'(a)({px} - a) + f(a)이다. f(a) = {_var_poly(f, 'a')}, "
                f"f'(a) = {with_eul_reul(_var_poly(derivative_of(f), 'a'))} 대입해 정리하면 "
                f"{render_poly(through_poly, 'a')} = 0, 즉 {render_factored(through_poly, 'a')} = 0"
                f"이고 a는 양수이므로 a = {a0}이다."
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
        c_minus_n = render_poly(((1, 1), (0, -n)), "c")
        four = 4 * lead
        disc_text = (
            f"{(b - m) ** 2} - {four}({c_minus_n}) = 0"
            if four > 0
            else f"{(b - m) ** 2} + {-four}({c_minus_n}) = 0"
        )
        return DiffItem(
            slot=slot,
            frame_id="applied-intercept-given-find-constant",
            question_text=(
                f"곡선 y = {head} + c (c는 상수) 위의 x좌표가 {a}인 점에서의 접선의 y절편이 "
                f"{n}일 때, c의 값을 구하시오."
            ),
            answer_text=str(c0),
            explanation=(
                f"접선의 기울기는 도함수 {render_poly(_poly({1: 2 * lead, 0: b}))}에 x = "
                f"{with_eul_reul(a)} 대입한 {m}이므로 접선은 y = {_line(m, n)}이다. 곡선과 "
                "연립하면 "
                f"{render_poly(_poly({2: lead, 1: b - m}))} + ({c_minus_n}) = 0이고, 접하려면 "
                f"판별식이 0이어야 한다. {disc_text}에서 c = {c0}이다."
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
                f"함수 f(x) = {render_poly(f)}에 대하여 곡선 y = f(x) "
                f"위의 점 (a, f(a))에서의 접선이 원점을 지날 때, "
                "양수 a의 값을 구하시오."
            ),
            answer_text=str(s),
            explanation=(
                f"접선 y = f'(a)(x - a) + f(a)에 원점 (0, 0)을 대입하면 f(a) - af'(a) = 0이다. "
                f"f(a) = {_var_poly(f, 'a')}, f'(a) = {_var_poly(derivative_of(f), 'a')}이므로 "
                f"({_var_poly(f, 'a')}) - a({_var_poly(derivative_of(f), 'a')}) = "
                f"{render_poly(_poly({2: -lead, 0: c}), 'a')} = 0에서 a^2 = {s * s}이다. "
                f"a는 양수이므로 a = {s}이다."
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
        return DiffItem(
            slot=slot,
            frame_id="applied-parallel-tangent-at-other-point",
            # 괄호 조건을 명사구 가운데 끼우지 않는다('또 다른'이 이미 b ≠ a를 말한다).
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 x좌표가 {a}인 점에서의 접선과 평행한 접선을 "
                "갖는 또 다른 점의 x좌표를 b라 할 때, b의 값을 구하시오."
            ),
            answer_text=str(b),
            # '도함수의 근'이 아니라 '방정식 f'(x) = m의 근'이다(2차 감사: 수학적으로 틀린 서술).
            explanation=(
                f"평행한 두 접선은 기울기가 같으므로 f'(b) = f'({a})이다. "
                f"f'(x) = {render_poly(derivative_of(f))}이므로 f'({a})의 값은 {m}이고, "
                f"방정식 f'(x) = {m}, 즉 {render_factored(_minus_const(derivative_of(f), m))} = "
                "0의 "
                f"근은 x = {min(a, b)}, {max(a, b)}이다. 이 중 {with_i_ga(a)} 아닌 근이 b이므로 "
                f"b = {b}이다."
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
        answer_format=_fmt(answer),
        choices=choices,
        distractors=distractors,
    )


#: 오개념 유발 해설의 함정 문장 — 오답 선지가 나오는 경로(power-rule-step-omitted)를 짚는다.
_POWER_TRAP: Final = (
    " 각 항을 미분할 때 지수를 앞으로 내리는 단계나 지수를 1 줄이는 단계를 빠뜨리면 "
    "기울기를 잘못 구하게 된다."
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
                f"기울기는 {m}이다.{_POWER_TRAP}"
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
                f"기울기는 {m}이다.{_POWER_TRAP}"
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
            explanation=(
                f"도함수 {render_poly(derivative_of(f))}에 x = {with_eul_reul(a)} 대입하면 "
                "기울기는 "
                f"{m}이고 접선은 {_pt_slope(m, a, fa)}이다. x = 0을 대입하면 y절편은 {k}이다."
                f"{_POWER_TRAP}"
            ),
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
                f"도함수 {render_poly(derivative_of(f))}에 x = {with_eul_reul(a)} 대입하면 "
                "기울기는 "
                f"{m}이므로 접선은 {_pt_slope(m, a, fa)}이다. 따라서 "
                f"g({t}){eun_neun(f'g({t})')} {value}이다.{_POWER_TRAP}"
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
                f"x^2의 도함수는 2x이므로 2a = {b}에서 a = {a0}이다. 도함수를 x로 쓰거나(계수 2 "
                "누락) 2x^2으로 쓰면(지수를 1 줄이지 않음) 다른 값이 나온다."
            ),
            conditions=f"Derivative(x**2, x).doit().subs(x, a) = {b}",
            answer_map=(("a", str(a0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a0),
            choices=choices,
            distractors=distractors,
        )

    def m6(p: tuple[object, ...]) -> DiffItem | None:
        a0 = _as_int(p[0])
        b = 3 * a0 * a0
        wrong_coeff = sympy.sqrt(b)  # (x^3)'를 x^2로 쓴 학생이 얻는 a
        entries = [
            ChoiceEntry(str(a0), is_correct=True, sort_key=float(a0)),
            # 학생 표기(렌더 계약) — '9*sqrt(3)'이 아니라 '9sqrt(3)'(3차 감사 bad_wording).
            ChoiceEntry(render_surd(wrong_coeff), _KEBAB, sort_key=float(wrong_coeff)),
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
                f"x^3의 도함수는 3x^2이므로 3a^2 = {b}에서 a^2 = {a0 * a0}이고, a는 양수이므로 "
                f"a = {a0}이다. 도함수를 x^2으로 쓰거나(계수 3 누락) 3x^3으로 쓰면(지수를 1 줄이지 "
                "않음) 다른 값이 나온다."
            ),
            conditions=(f"Derivative(x**3, x).doit().subs(x, a) = {b}", "a > 0"),
            answer_map=(("a", str(a0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(a0),
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
        Frame("mc-find-point-on-cubic", _grid("p3-tan:m6", (3, 4, 5, 6, 7, 9, 10)), m6),
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
        top = 3 - lead * half * half
        vertex_form = (
            f"{'' if lead == 1 else ('-' if lead == -1 else lead)}({_lin_text(half)})^2"
            f" {_signed(top)}"
            if top
            else f"{'' if lead == 1 else ('-' if lead == -1 else lead)}({_lin_text(half)})^2"
        )
        fp = derivative_of(f)
        return DiffItem(
            slot=slot,
            frame_id="diag-slope-at-vertex",
            question_text=(f"곡선 y = {render_poly(f)}의 꼭짓점에서의 접선의 기울기를 구하시오."),
            answer_text="0",
            # 3차 감사 bad_explanation — 도함수 식과 대입 과정을 보인다(종전: 결론만).
            explanation=(
                f"y = {vertex_form}이므로 꼭짓점의 x좌표는 {half}이다. 도함수는 "
                f"y' = {render_poly(fp)}이므로 x = {half}에서의 미분계수는 "
                f"{_eval_text(fp, half)} = 0이고, 접선의 기울기는 0이다."
            ),
            conditions=f"{_d(f, str(half))} = y",
            answer_map=(("y", "0"),),
            problem_type_code=_EVAL,
            answer_format=_fmt(0),
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
            question_text=(f"직선 y = {c} 위의 점 ({a}, {c})에서의 접선의 기울기를 구하시오."),
            answer_text="0",
            explanation=(
                f"{with_eun_neun(f'y = {c}')} 상수함수이고 상수함수의 도함수는 0이므로 접선의 "
                "기울기는 0이다. "
                "(직선 위의 점에서의 접선은 그 직선 자신이다.)"
            ),
            conditions=f"{_d(f, str(a))} = y",
            answer_map=(("y", "0"),),
            problem_type_code=_EVAL,
            answer_format=_fmt(0),
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
            answer_format=_fmt(0),
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
        Frame("diag-slope-at-origin-of-power", _grid("p3-tan:d6", (2, 3, 4, 5, 8, 9, 10)), d6),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 숙련도 확인(mastery_check) — 접점 이중근 항등식·통과점·넓이로 묶는다
# ──────────────────────────────────────────────────────────────────────────
def _mastery_frames() -> list[Frame]:
    slot = "mastery_check"

    # 3차 감사(2026-10) bad_tag 처분 — 이차곡선과 직선의 접할 조건·곡선 밖의 점에서 그은 접선은
    # 연립 이차방정식의 판별식만으로 풀려 미분이 필요 없었다(k1·k2·k3 구판). 곡선을 **삼차**로
    # 바꾸고
    # 접점의 미분계수가 풀이에 필수인 틀로 다시 짰다(우회로 판정기 T05-quadratic-tangency). 검산은
    # 명세 probe_note대로 *접점 이중근 항등식* — 곡선과 접선의 차가 (x - 접점)^2을 인수로 갖는다는
    # x에 대한 항등식(미분을 쓰지 않는 독립 경로)이다.
    def k1(p: tuple[object, ...]) -> DiffItem | None:
        lead, r1, r2, m, d = (_as_int(v) for v in p)
        # f'(x) - m = 3·lead(x - r1)(x - r2) → 접점 후보 r1 < r2 중 x좌표가 양수인 것은 r2 하나.
        if not (r1 < 0 < r2) or (3 * lead * (r1 + r2)) % 2 != 0:
            return None
        b = -3 * lead * (r1 + r2) // 2
        c = m + 3 * lead * r1 * r2
        f = _poly({3: lead, 2: b, 1: c, 0: d})
        if eval_at(derivative_of(f), r2) != m or eval_at(derivative_of(f), r1) != m:
            return None  # pragma: no cover — 구성 오류
        _, fa, k = _tangent(f, r2)
        if k == 0 or 0 in (b, c):
            return None
        fp = derivative_of(f)
        moved = _minus_const(fp, m)
        line = _line_with_k(m)
        conditions = _cubic_double_root_conditions(
            poly_to_sympy(f), m * _X + sympy.Symbol("k"), "k", k
        )
        if conditions is None:
            return None
        return DiffItem(
            slot=slot,
            frame_id="mastery-cubic-tangent-given-slope",
            question_text=(
                f"직선 y = {with_i_ga(line)} 곡선 y = {render_poly(f)} 위의 x좌표가 양수인 점에서 "
                "이 곡선에 접할 때, 상수 k의 값을 구하시오."
            ),
            answer_text=str(k),
            explanation=(
                f"접점의 x좌표를 a라 하자. 접선의 기울기는 미분계수이므로 f'(a) = {m}이다. "
                f"f'(x) = {render_poly(fp)}이므로 {render_poly(fp, 'a')} = {m}, 즉 "
                f"{render_factored(moved, 'a')} = 0에서 a = {r1} 또는 a = {r2}이고, a는 양수이므로 "
                f"a = {r2}이다. 접점 ({r2}, {fa})이 직선 위에 있으므로 "
                f"{fa} = {m}({r2}) + k에서 k = {k}이다."
            ),
            conditions=conditions,
            answer_map=(("k", str(k)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(k),
        )

    def k2(p: tuple[object, ...]) -> DiffItem | None:
        f, a = _as_poly(p[0]), _as_int(p[1])
        lead, b = dict(f).get(3, 0), dict(f).get(2, 0)
        if lead == 0 or b % lead:
            return None
        s_root = -b // lead - 2 * a  # 접선과 곡선의 교점: 접점 a(이중근)와 나머지 s
        if s_root == a:
            return None  # 변곡점의 접선 — 다시 만나는 점이 없다
        m, fa, k = _tangent(f, a)
        fp = derivative_of(f)
        diff_poly = poly_from_sympy(sympy.expand(poly_to_sympy(f) - (m * _X + k)))
        return DiffItem(
            slot=slot,
            frame_id="mastery-tangent-meets-curve-again",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 점 ({a}, {fa})에서의 접선이 이 곡선과 만나는 점 "
                "중 "
                "접점이 아닌 점의 x좌표를 구하시오."
            ),
            answer_text=str(s_root),
            explanation=(
                f"f'(x) = {render_poly(fp)}이므로 접점의 x좌표가 {a}일 때 접선의 기울기는 "
                f"f'({a})의 값인 {m}이고 접선은 "
                f"{_pt_slope(m, a, fa)}, 즉 y = {_line(m, k)}이다. 곡선과 접선을 연립하면 "
                f"{render_poly(diff_poly)} = 0이고, 접점의 x좌표 {with_eun_neun(a)} 이 방정식의 "
                "중근이므로 "
                f"{render_factored(diff_poly)} = 0이다. 따라서 접점이 아닌 교점의 x좌표는 "
                f"{s_root}이다."
            ),
            conditions=(
                f"{poly_to_sympy_str(f, 's')} - ({m}*s + ({k})) = 0",
                f"s != {a}",
            ),
            answer_map=(("s", str(s_root)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(s_root),
        )

    def k3(p: tuple[object, ...]) -> DiffItem | None:
        lead, c, d, t = (_as_int(v) for v in p)
        if t == 0 or c == 0:
            return None
        # y = lead x^3 + c x + d 위의 점 x = t에서의 접선의 y절편 = d - 2·lead·t^3 (t에 대해 단조라
        # y축 위의 점에서 그을 수 있는 접선은 하나뿐이다).
        f = _poly({3: lead, 1: c, 0: d})
        point_y = d - 2 * lead * t**3
        m, fa, _ = _tangent(f, t)
        fp = derivative_of(f)
        tt = sympy.Symbol("t")
        intercept = sympy.expand(
            poly_to_sympy(f).subs(_X, tt) - tt * sympy.diff(poly_to_sympy(f), _X).subs(_X, tt)
        )
        intercept_poly = poly_from_sympy(intercept, "t")
        moved = _minus_const(intercept_poly, point_y)
        conditions = _cubic_double_root_conditions(
            poly_to_sympy(f), sympy.Symbol("m") * _X + point_y, "m", m
        )
        if conditions is None:
            return None
        return DiffItem(
            slot=slot,
            frame_id="mastery-tangent-from-point-on-y-axis",
            question_text=(
                f"점 (0, {point_y})에서 곡선 y = {render_poly(f)}에 그은 접선은 하나뿐이다. 이 "
                "접선의 기울기를 구하시오."
            ),
            answer_text=str(m),
            explanation=(
                f"접점을 (t, f(t))라 하자. f'(x) = {render_poly(fp)}이므로 접선은 "
                "y = f'(t)(x - t) + f(t)이고, 이 직선이 점 "
                f"{with_eul_reul(f'(0, {point_y})')} 지나므로 "
                f"{point_y} = f(t) - tf'(t) = {render_poly(intercept_poly, 't')}이다. 정리하면 "
                f"{render_poly(moved, 't')} = 0이고 실근은 t = {t}뿐이다. "
                f"따라서 접선의 기울기는 f'({t})의 값인 {m}이다."
            ),
            conditions=conditions,
            answer_map=(("m", str(m)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(m),
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
                f"도함수 {render_poly(derivative_of(f))}에 x = {with_eul_reul(a)} 대입하면 "
                "기울기는 "
                f"{m}이므로 접선은 y = {_line(m, k)}이다. y절편은 {k}, x절편은 {xi}이므로 "
                f"삼각형은 두 변의 길이가 {abs(k)}, {abs(xi)}인 직각삼각형이고 넓이는 "
                f"{with_wa_gwa(abs(k))} {abs(xi)}의 곱의 절반인 {int(area)}이다."
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
        lead_text = "" if lead == 1 else ("-" if lead == -1 else str(lead))
        f_a_poly = poly_from_sympy(sympy.expand(f_a), "p")
        d_a_poly = poly_from_sympy(sympy.expand(d_a), "p")
        cond_poly = poly_from_sympy(sympy.expand(f_a - a * d_a), "p")
        # y절편 = f(a) - a·f'(a) — 계수 1·음수 a를 사람이 읽는 표기로
        # ('f(1) - f'(1)'·'f(-2) + 2f'(-2)').
        coef = "" if abs(a) == 1 else str(abs(a))
        intercept_text = f"f({a}) - {coef}f'({a})" if a > 0 else f"f({a}) + {coef}f'({a})"
        return DiffItem(
            slot=slot,
            frame_id="mastery-cubic-intercept-find-coefficient",
            question_text=(
                f"곡선 y = {lead_text}x^3 + px^2 위의 x좌표가 {a}인 점에서의 접선의 y절편이 "
                f"{n}일 때, 상수 p의 값을 구하시오."
            ),
            answer_text=str(p0),
            explanation=(
                f"f(x) = {lead_text}x^3 + px^2이므로 f'(x) = {3 * lead}x^2 + 2px이고 "
                f"f({a}) = {render_poly(f_a_poly, 'p')}, f'({a}) = "
                f"{render_poly(d_a_poly, 'p')}이다. "
                f"접점 ({a}, f({a}))에서의 접선 y = f'({a})(x {_x_shift(a)}) + f({a})에 x = 0을 "
                f"대입하면 y절편은 {intercept_text} = {render_poly(cond_poly, 'p')}이다. "
                f"{render_poly(cond_poly, 'p')} = {n}에서 p = {p0}이다."
            ),
            conditions=f"{cond} = {n}",
            answer_map=(("p", str(p0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(p0),
        )

    def k6(p: tuple[object, ...]) -> DiffItem | None:
        a, g_lead, g_c = (_as_int(v) for v in p)
        # y = x^2 + px + q 와 y = g(x) = g_lead x^3 + g_c x 가 x = a 에서 접한다. 3차 감사 처분 —
        # 구판은 p를 미리 숫자로 박아 q가 함숫값 대입만으로 정해졌다(기울기 조건 불요·bad_tag).
        # 이제 p·q 둘 다 미지수라 기울기 조건(p)을 먼저 써야 q가 정해진다.
        g = _poly({3: g_lead, 1: g_c})
        slope = eval_at(derivative_of(g), a)
        p0 = slope - 2 * a
        q0 = eval_at(g, a) - a * a - p0 * a
        if 0 in (p0, q0) or p0 == q0:
            return None
        gp = derivative_of(g)
        # 검산: 기울기 조건으로 정한 p = p0에서 두 곡선이 접할 조건(판별식 = 0)을 q로 쓴다 — 함숫값
        # 대입식(산술 재확인)이 아니라 *접한다*는 사실 자체를 미분 없이 다시 확인한다.
        conditions = _cubic_double_root_conditions(
            poly_to_sympy(g), _X**2 + p0 * _X + sympy.Symbol("q"), "q", q0
        )
        if conditions is None:
            return None
        # p를 대입한 함숫값 조건 — 상수항이 0이면('q = 3') 같은 결론을 두 번 쓰지 않는다.
        q_side = render_affine(a * a + p0 * a, 1, "q")
        settled = (
            f"q = {q0}이다." if q_side == "q" else f"{q_side} = {eval_at(g, a)}이므로 q = {q0}이다."
        )
        return DiffItem(
            slot=slot,
            frame_id="mastery-two-curves-touch-find-constant",
            question_text=(
                f"곡선 y = x^2 + px + q가 곡선 y = {render_poly(g)}{wa_gwa(render_poly(g))} "
                f"x = {a}인 점에서 접할 때, 상수 q의 값을 구하시오. (단, p, q는 상수이다.)"
            ),
            answer_text=str(q0),
            explanation=(
                f"두 곡선이 x = {a}인 점에서 접하므로 그 점에서 접선의 기울기와 함숫값이 모두 "
                "같다. "
                f"y = x^2 + px + q의 도함수는 y' = 2x + p이고 y = {render_poly(g)}의 도함수는 "
                f"y' = {render_poly(gp)}이다. 기울기 조건에서 {render_affine(2 * a, 1, 'p')} = "
                f"{slope}이므로 p = {p0}이다. 함숫값 조건에서 x가 {a}일 때 두 함숫값이 같으므로 "
                f"{render_affine(a * a, a, 'p')} + q = {eval_at(g, a)}이고, p = "
                f"{with_eul_reul(p0)} "
                f"대입하면 {settled}"
            ),
            conditions=conditions,
            answer_map=(("q", str(q0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(q0),
        )

    k6_params: list[tuple[object, ...]] = [
        (a, g_lead, g_c)
        for g_lead in (1, 2, -1)
        for g_c in (-3, -1, 1, 2, 4)
        for a in (-2, -1, 1, 2, 3)
    ]
    k1_params = _grid(
        "p3-tan:k1",
        (1, 2, -1),
        (-3, -2, -1),
        (1, 2, 3),
        (-6, -3, 3, 6, 9),
        (-4, -1, 2, 5),
    )
    k3_params = _grid("p3-tan:k3", (1, 2, -1), (-6, -3, -1, 2, 5), (-4, 1, 3, 6), (-2, -1, 1, 2))
    return [
        Frame("mastery-cubic-tangent-given-slope", k1_params, k1),
        Frame(
            "mastery-tangent-meets-curve-again",
            _grid("p3-tan:k2", _cubic_pool()[1::11], (-2, -1, 1, 2, 3)),
            k2,
        ),
        Frame("mastery-tangent-from-point-on-y-axis", k3_params, k3),
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


def _lin_text(a: int) -> str:
    """'x - 3'·'x + 2'·'x' — (x - a)의 표기."""
    return render_poly(((1, 1), (0, -a)))


def _eval_text(f: Poly, a: int) -> str:
    """일차식 f에 x = a를 대입하는 식 — '-4(-3) - 12'(음수 대입은 괄호)."""
    coef = dict(f).get(1, 0)
    const = dict(f).get(0, 0)
    head = "" if coef == 1 else ("-" if coef == -1 else str(coef))
    tail = "" if const == 0 else (f" + {const}" if const > 0 else f" - {-const}")
    return f"{head}({a}){tail}"


def _x_shift(a: int) -> str:
    """'(x - a)'의 꼬리 — a > 0이면 '- a', a < 0이면 '+ |a|'(이중 부호 금지)."""
    return f"- {a}" if a >= 0 else f"+ {-a}"


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
