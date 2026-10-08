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
    (`_cubic_double_root_conditions` — 접점이 발문에서 정해지지 않은 틀만. 다른 접선의 상수는 발문
    조건(접점의 x좌표가 양수 · 접선이 하나뿐)에 대응하는 보호 조건으로 뺀다). 학생 풀이는
    미분(접점의 미분계수)이고, 판별식은 검산 경로일 뿐이다.
  · **(x - a)^2 인수형(접점 고정)** — 발문이 접점 x = a를 정하는 틀(접선의 y절편 · 두 곡선이
    x = a에서 접함)은 *차가 (x - a)^2을 인수로 갖는다*는 항등식의 나머지 계수로 쓴다
    (`_intercept_touch_condition`과 숙련도 두 곡선 틀). 5회차 감사 교정 — 이 틀에 판별식을 쓰면 삼차
    곡선에서 근이 둘이 되어 둘째 근을 발문에 없는 보호 조건으로 버려야 했다(284122b4 · 판정기
    V05-touch-verify-mismatch).
  · **수치 대입형(정직 한계)** — 삼차 이상 곡선의 y절편·접선의 함숫값·삼각형 넓이처럼 미분 평가를
    다른 연산과 섞어야 하는 문항은 Tier1이 섞인 식을 검산하지 못한다(`D + 108 = y` 형태는
    unverifiable — 형제 생성기 docstring 2026-10-06 실측). 그 문항은 생성기가 `sympy.diff`로 구한
    기울기·함숫값을 *상수로 풀어 쓴 산술식*을 조건에 둔다. 이 형태는 미분 자체를 재검산하지는
    않으므로(산술 재확인) 독립 검산은 테스트(`test_p3_diff_tangent_velocity_generators`)가
    극한 정의·SymPy solve로 맡는다.

7회차 감사(은행 감사 3회차 · 2026-10-08) 처분: 접선의 기울기(주어진 값·평행·수직)로 접점을 찾는 틀과
두 점의 접선 기울기 틀까지 곡선을 **삼차 이상**으로 바꿨다 — 이차곡선이면 기울기 m인 직선과 연립한
이차방정식의 중근(판별식·근과 계수의 관계)이 접점·기울기를 미분 없이 준다(판정기
T05-quadratic-slope). 이 파일에 이차곡선이 남은 곳은 숙련도 '두 곡선이 접한다'의 미지 곡선족 y = x^2
+ px + q뿐이다(상대 곡선이 삼차라 차가 삼차다).

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
from whymath_backend.lang.josa import eul_reul, eun_neun, euro_ro, i_ga, wa_gwa
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


def _intercept_touch_condition(
    curve: sympy.Expr, a: int, intercept: sympy.Expr, unknown: str, answer: int
) -> str | None:
    """접점 x = a 고정 · y절편 주어짐 — '접점에서 이중근' 항등식 한 식(미분을 쓰지 않는 경로).

    발문의 문제 그대로다: 접점 (a, f(a))와 y축 위의 점 (0, 절편)을 지나는 직선 ℓ이 *x = a에서*
    곡선에 접한다 ⇔ f(x) - ℓ(x)가 (x - a)^2을 인수로 갖는다. 나머지 Ax + B는 ℓ(a) = f(a)라서 B =
    -aA이므로 A = 0 한 식이 조건 전부다(분모 a를 걷어 낸 분자로 쓴다). 미지 상수(`unknown`)는
    곡선(상수항 c) 또는 절편(k) 어느 쪽에 있어도 된다.

    5회차 감사 교정 — 구판은 '곡선 - 기울기 m 직선족'의 x에 대한 판별식 = 0을 썼는데, 삼차
    곡선에서는 기울기 m인 접선이 둘이라 판별식의 근도 둘이고 둘째 근을 *발문에 없는* 보호 조건으로
    버려야 했다 — 접점 고정이라는 발문 조건을 담지 않은 다른 문제다(284122b4와 같은 결함 · 판정기
    V05-touch-verify-mismatch). 이 식은 근이 정답 하나뿐이라 보호 조건이 필요 없다. 해가 정답 하나가
    아니면 None(구성 오류 — 그 파라미터를 건너뛴다).
    """
    if a == 0:
        return None  # 접점이 y축 위면 절편 = 접점의 y좌표(답 노출) — 이 틀이 다루지 않는다
    u = sympy.Symbol(unknown)
    line = (curve.subs(_X, a) - intercept) / a * _X + intercept
    remainder = sympy.Poly(sympy.rem(sympy.expand(curve - line), (_X - a) ** 2, _X), _X)
    coeffs = [sympy.together(c) for c in remainder.all_coeffs()]
    if len(coeffs) != 2:
        return None  # pragma: no cover — 나머지가 일차식이 아니다(구성 오류)
    slope_coeff = sympy.expand(sympy.numer(coeffs[0]))
    if slope_coeff.free_symbols != {u}:
        return None  # pragma: no cover — 구성 오류
    if sympy.solve([slope_coeff, sympy.numer(coeffs[1])], u, dict=True) != [{u: answer}]:
        return None  # pragma: no cover — 구성 오류(해가 정답 하나가 아니다)
    return f"{sympy.sstr(slope_coeff)} = 0"


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


def _slope_pool() -> tuple[object, ...]:
    """기울기·접점 틀의 곡선 풀 — 삼차만(7회차 감사: 이차곡선은 판별식·근과 계수의 관계로 기울기와
    접점이 미분 없이 나온다 · 판정기 T05-quadratic-slope). 종전 풀은 이차 곡선을 섞었다."""
    return _cubic_pool()[::7]


def _slope_point_slope(f: Poly, a0: int) -> int | None:
    """기울기가 f'(a0)인 접선의 접점 중 x좌표가 양수인 것이 a0 하나뿐일 때 그 기울기 m(아니면 None).

    7회차 감사(2026-10-08) 처분 — 접선의 기울기(주어진 값·평행·수직)로 접점의 x좌표 a를 묻는 틀이
    이차곡선을 쓰면, 기울기 m인 직선과 연립한 이차방정식의 중근(판별식 = 0)이 곧 접점이라 미분 없이
    풀렸다(판정자 지적 4d287bbd·1006bee0·5209729b · 판정기 T05-quadratic-slope). 곡선을 **삼차**로
    쓰면 f'(x) = m이 이차방정식이 되어 근 둘 중 양수인 것을 발문의 '양수 a' 조건으로 고른다(조건이
    실제로 일한다 — 이차곡선에서는 해가 하나라 '양수'가 공허했다). 해설이 인수분해 → '양수이므로'로
    끝나도록 두 근이 모두 유리수인 매개변수만 쓴다(삼차의 f'(x) = m은 근의 합이 유리수라 한 근이
    정수면 다른 근도 유리수다). 기울기 0(수평 접선)은 쓰지 않는다.
    """
    if sympy.degree(poly_to_sympy(f), _X) < 3:
        return None
    m = eval_at(derivative_of(f), a0)
    if m == 0:
        return None
    a = sympy.Symbol("a")
    roots = sympy.roots(sympy.Poly(sympy.diff(poly_to_sympy(f), _X).subs(_X, a) - m, a))
    if sum(roots.values()) != 2 or any(not r.is_rational for r in roots):
        return None
    if [r for r in roots if r > 0] != [a0]:
        return None
    return m


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


def _setup_at(body: str, point: str) -> str:
    """풀이 단계 출발식의 한 변 — 도함수가 든 식 전체를 점에서 계산한다(`(식).doit().subs(x, 점)`).

    검산 조건이 기울기·함숫값을 상수로 풀어 쓴 산술식인 문항은 그 상수를 `Derivative(f, x)`·`f`로
    되돌려 출발식을 단다(`DiffItem.solution_setup`). `.doit()`·`.subs()`는 변 전체에만 붙일 수
    있어(안전 파서) 산술과 섞인 도함수는 이 꼴로 쓴다(`p3_diff_solution_steps` docstring).
    """
    return f"({body}).doit().subs(x, {point})"


def _tangent_at(f: Poly, a: object, t: str) -> str:
    """접점 x = a에서의 접선 y = f'(a)(x - a) + f(a)의 x = t에서의 값 — 출발식의 한 변."""
    s = poly_to_sympy_str(f)
    return _setup_at(f"{s} + Derivative({s}, x)*(({t}) - x)", str(a))


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
    *,
    slot: str,
    frame_id: str,
    text: str,
    value: int,
    explanation: str,
    expr: str,
    ptype: str,
    setup: str,
) -> DiffItem:
    """수치 대입형 — 생성기가 SymPy로 푼 상수를 산술식으로 재확인한다(독립 미분 검산 아님).

    검산 조건(`expr = y`)에 도함수가 없으므로 풀이 단계의 출발식(`setup` — 상수를 `Derivative`로
    되돌린 같은 관계)을 반드시 받는다.
    """
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
        solution_setup=setup,
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
        # 5회차 감사(2026-10-08) — 이차 곡선의 접선 y절편은 중근(판별식)만으로 풀렸다(판정자 지적
        # 32ec89c8 · 판정기 T05-quadratic-tangent-constant). 곡선을 **삼차**로 바꾸고 접점의
        # 미분계수로 접선을 세우게 한다. 검산은 미분을 쓰지 않는 독립 경로 — 접점 (a, f(a))와
        # (0, k)를 지나는 직선이 x = a에서 접한다는 '접점에서 이중근' 항등식
        # (`_intercept_touch_condition` · k의 일차식 한 개).
        f, a = _as_poly(p[0]), _as_int(p[1])
        m, fa, k = _tangent(f, a)
        conditions = _intercept_touch_condition(poly_to_sympy(f), a, sympy.Symbol("k"), "k", k)
        if conditions is None:
            return None
        return DiffItem(
            slot=slot,
            frame_id="rep-y-intercept-of-cubic-tangent",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 점 ({a}, {fa})에서의 접선의 y절편을 구하시오."
            ),
            answer_text=str(k),
            explanation=(
                "접선의 기울기는 접점에서의 미분계수이다. 도함수는 y' = "
                f"{render_poly(derivative_of(f))}이므로 x = {a}에서의 기울기는 {m}이고, 접선은 "
                f"{_pt_slope(m, a, fa)}, 즉 y = {_line(m, k)}이다. 따라서 접선의 y절편은 {k}이다."
            ),
            conditions=conditions,
            answer_map=(("k", str(k)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(k),
            # 해설 그대로 — 접점 x = a에서의 접선 y = f'(a)(x - a) + f(a)에 x = 0을 넣은 y절편.
            solution_setup=f"{_tangent_at(f, a, '0')} = k",
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
            setup=f"{_tangent_at(f, a, str(t))} = y",
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
        # 7회차 감사 처분 — 이차곡선이면 판별식(중근)으로 접점이 나왔다(`_slope_point_slope` 참조).
        f, a0 = _as_poly(p[0]), _as_int(p[1])
        m = _slope_point_slope(f, a0)
        if m is None:
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
    slope_point = _grid("p3-tan:r6", _cubic_pool()[::11], _POS_POINTS)
    return [
        Frame("rep-slope-at-point", _grid("p3-tan:r1", _cubic_pool()[::9], _POINTS), r1),
        Frame("rep-slope-at-x-coordinate", _grid("p3-tan:r2", _quartic_pool()[::7], _POINTS), r2),
        Frame(
            "rep-y-intercept-of-cubic-tangent",
            _grid("p3-tan:r3", _cubic_pool()[2::19], _POINTS),
            r3,
        ),
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
        Frame("rep-find-point-for-slope", slope_point, r6),
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
            # 풀이 단계는 해설처럼 f'(a)와 f'(b)를 따로 구한다 — 두 점을 한 식에 담으려고 두 번째
            # 점은 같은 함수를 변수 u로 쓴다(검산 조건의 f(x + d) 이동은 Tier1 표기 제약일 뿐이다).
            solution_setup=(
                f"(Derivative({poly_to_sympy_str(f)}, x)"
                f" + Derivative({poly_to_sympy_str(f, 'u')}, u))"
                f".doit().subs(x, {a}).subs(u, {b}) = y"
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
            # 풀이 단계는 해설처럼 f'(b) - f'(a)를 따로 구한다(두 번째 점은 같은 함수를 변수 u로).
            solution_setup=(
                f"(Derivative({poly_to_sympy_str(f, 'u')}, u)"
                f" - Derivative({poly_to_sympy_str(f)}, x))"
                f".doit().subs(u, {b}).subs(x, {a}) = y"
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
            setup=f"{_tangent_at(f, a, '0')} = y",
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
            # m + n = f'(a) + (접선의 y절편 f(a) + f'(a)(0 - a)).
            setup=(
                _setup_at(
                    f"Derivative({poly_to_sympy_str(f)}, x) + ({poly_to_sympy_str(f)})"
                    f" + Derivative({poly_to_sympy_str(f)}, x)*((0) - x)",
                    str(a),
                )
                + " = y"
            ),
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
            # 접선에 y = 0을 넣은 x절편 a - f(a)/f'(a).
            setup=(
                _setup_at(
                    f"x - ({poly_to_sympy_str(f)})/Derivative({poly_to_sympy_str(f)}, x)", str(a)
                )
                + " = y"
            ),
        )

    cubics = _cubic_pool()
    return [
        Frame("basic-slope-of-function-graph", _grid("p3-tan:b1", cubics[3::17], _POINTS), b1),
        Frame(
            "basic-slope-sum-at-two-points",
            _grid("p3-tan:b2", _slope_pool(), (-2, -1, 0, 1), (1, 2, 3)),
            b2,
        ),
        Frame(
            "basic-slope-difference-at-two-points",
            _grid("p3-tan:b3", _slope_pool()[1::2], (-2, -1, 0, 1), (1, 2, 3)),
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
        # 7회차 감사 처분 — 이차곡선이면 판별식(중근)으로 접점이 나왔다(판정자 지적 5209729b ·
        # `_slope_point_slope` 참조).
        f, a0 = _as_poly(p[0]), _as_int(p[1])
        m = _slope_point_slope(f, a0)
        if m is None:
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
        # 7회차 감사 처분 — 이차곡선이면 판별식(중근)으로 접점이 나왔다(판정자 지적 1006bee0 ·
        # `_slope_point_slope` 참조). 수직인 직선 x + sy = s + 1의 기울기 -1/s에서 접선의 기울기 s.
        f, a0, s = _as_poly(p[0]), _as_int(p[1]), _as_int(p[2])
        if _slope_point_slope(f, a0) != s:
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
        through_expr = sympy.expand(
            poly_to_sympy(f, "a") + poly_to_sympy(derivative_of(f), "a") * (px - a_sym) - qy
        )
        # 해설이 '인수분해 → a는 양수이므로'로 끝나려면 *다른 근이 전부 실수이고 양수가 아니어야*
        # 한다. 삼차 곡선이면 남는 이차 인수가 허근일 수 있다 — 그때 정답 하나만 남는 이유는
        # '양수'가 아니라 '실근이 아님'이라 해설이 거짓 근거를 대고, 풀이 단계(근 목록 → 선택)도
        # 실수 범위 동치가 아니어서 정답 대입 검산으로 내려간다. 근이 모두 유리수인 매개변수만 쓴다.
        through_roots = sympy.roots(sympy.Poly(through_expr, a_sym))
        if sum(through_roots.values()) != sympy.degree(through_expr, a_sym) or any(
            not r.is_rational or (r != a0 and r > 0) for r in through_roots
        ):
            return None
        through_poly = poly_from_sympy(through_expr, "a")
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
            # 접선 y = f'(a)(x - a) + f(a)가 점을 지난다 — f(a)·f'(a)를 미분으로 되돌린 같은 식.
            solution_setup=f"{_tangent_at(f, 'a', str(px))} = {qy}",
        )

    def a4(p: tuple[object, ...]) -> DiffItem | None:
        # 5회차 감사(2026-10-08) — 이차 곡선 y = Ax^2 + bx + c의 접선 y절편으로 c를 구하는 틀은 중근
        # (판별식)만으로 풀렸다(판정자 지적 2fd9fad4·7e31841b · 판정기
        # T05-quadratic-tangent-constant). 곡선을 **삼차**로 바꾼다. 학생 풀이는 접점의 미분계수로
        # 접선을 세워 y절편을 c의 식으로 쓰는 것이고, 검산은 미분을 쓰지 않는 독립 경로 — 접점
        # (a, f(a))와 (0, n)을 지나는 직선이 x = a에서 접한다는 '접점에서 이중근' 항등식
        # (`_intercept_touch_condition` · c의 일차식 한 개)이다.
        lead, b2, b1, c0, a = (_as_int(v) for v in p)
        head = _poly({3: lead, 2: b2, 1: b1})
        if len(head) < 3:
            return None
        f = _poly({**dict(head), 0: c0})
        m, _, n = _tangent(f, a)
        if m == 0:
            return None
        conditions = _intercept_touch_condition(
            poly_to_sympy(head) + sympy.Symbol("c"), a, sympy.Integer(n), "c", c0
        )
        if conditions is None:
            return None
        head_at = eval_at(head, a)
        point_y = render_poly(((1, 1), (0, head_at)), "c")  # 접점의 y좌표 'c + 39'
        intercept = render_poly(((1, 1), (0, head_at - a * m)), "c")  # y절편 'c - 27'
        head_sym = poly_to_sympy_str(head)
        return DiffItem(
            slot=slot,
            frame_id="applied-cubic-intercept-given-find-constant",
            question_text=(
                f"곡선 y = {render_poly(head)} + c (c는 상수) 위의 x좌표가 {a}인 점에서의 접선의 "
                f"y절편이 {n}일 때, c의 값을 구하시오."
            ),
            answer_text=str(c0),
            explanation=(
                f"도함수는 y' = {render_poly(derivative_of(head))}이므로 x = {a}에서의 접선의 "
                f"기울기는 {m}이다. 접점의 좌표는 ({a}, {point_y})이므로 접선은 y = {m}(x "
                f"{_x_shift(a)}) + {point_y}이고, x = 0을 대입하면 y절편은 {intercept}이다. "
                f"{intercept} = {n}에서 c = {c0}이다."
            ),
            conditions=conditions,
            answer_map=(("c", str(c0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(c0),
            # 해설 그대로 — 접점 x = a에서의 접선의 y절편 f(a) - af'(a)(곡선의 상수항 c 미지) = n.
            solution_setup=(
                _setup_at(f"{head_sym} + c - x*Derivative({head_sym} + c, x)", str(a)) + f" = {n}"
            ),
        )

    def a5(p: tuple[object, ...]) -> DiffItem | None:
        # 5회차 감사 처분 — 포물선에 원점에서 그은 접선은 직선 y = mx와의 중근(판별식)만으로
        # 풀린다(판정기 T05-quadratic-tangent-constant · 3회차 원칙 '곡선 밖의 점에서 그은 접선은
        # 곡선 차수 ≥ 3'). f(x) = Lx^3 + 6Lr x^2 + qx + 8Lr^3 —
        # f(a) - af'(a) = -2L(a^3 + 3r a^2 - 4r^3) = -2L(a - r)(a + 2r)^2이라
        # 근이 전부 실수(r과 -2r)이고 양수 근은 r 하나다. 해설의 '인수분해 → a는 양수이므로'가 참인
        # 근거가 되고, 풀이 단계도 근 목록 → 선택으로 끝난다(a^3 = k 꼴은 허근 두 개를 버려야 해서
        # 실수 범위 근 목록이 아니다 — 정답 대입 검산으로 내려갔다).
        lead, q, root = _as_int(p[0]), _as_int(p[1]), _as_int(p[2])
        f = _poly({3: lead, 2: 6 * lead * root, 1: q, 0: 8 * lead * root**3})
        fa_text = _var_poly(f, "a")
        da_text = _var_poly(derivative_of(f), "a")
        reduced: Poly = ((3, -2 * lead), (2, -6 * lead * root), (0, 8 * lead * root**3))
        return DiffItem(
            slot=slot,
            frame_id="applied-cubic-tangent-through-origin",
            question_text=(
                f"함수 f(x) = {render_poly(f)}에 대하여 곡선 y = f(x) "
                f"위의 점 (a, f(a))에서의 접선이 원점을 지날 때, "
                "양수 a의 값을 구하시오."
            ),
            answer_text=str(root),
            explanation=(
                f"접선 y = f'(a)(x - a) + f(a)에 원점 (0, 0)을 대입하면 f(a) - af'(a) = 0이다. "
                f"f(a) = {fa_text}, f'(a) = {da_text}이므로 "
                f"({fa_text}) - a({da_text}) = {render_poly(reduced, 'a')} = 0, 즉 "
                f"{render_factored(reduced, 'a')} = 0이고 a는 양수이므로 a = {root}이다."
            ),
            conditions=(
                f"({poly_to_sympy_str(f, 'a')}) - a*({poly_to_sympy_str(derivative_of(f), 'a')}) = "
                "0",
                "a > 0",
            ),
            answer_map=(("a", str(root)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(root),
            # 해설의 f(a) - af'(a) = 0 — 접선에 원점을 대입한 식.
            solution_setup=(
                _setup_at(f"{poly_to_sympy_str(f)} - x*Derivative({poly_to_sympy_str(f)}, x)", "a")
                + " = 0"
            ),
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
        Frame("applied-parallel-to-line", _grid("p3-tan:a1", _slope_pool(), _POS_POINTS), a1),
        Frame(
            "applied-perpendicular-to-line",
            # s = 1은 'x + 1y = 2'·'기울기 -1/1' 표기가 생겨 뺐다(삼차 풀로 바꾼 뒤 처음 드러났다).
            _grid("p3-tan:a2", _slope_pool(), _POS_POINTS, (2, 3, 4, 5, 6, 7, 8, 9, 10)),
            a2,
        ),
        # 5회차 감사 처분 — 곡선 밖의 점에서 그은 접선은 곡선이 이차면 판별식만으로 풀린다(판정기
        # T05-quadratic-tangent-constant). 삼차 곡선 풀로 바꿨다(a에 대한 삼차방정식의 양의 정수근
        # 하나).
        Frame(
            "applied-tangent-passes-through-point",
            _grid("p3-tan:a3", _cubic_pool()[1::5], _POS_POINTS, (-3, -2, -1, 0, 1, 2, 3, 5)),
            a3,
        ),
        Frame(
            "applied-cubic-intercept-given-find-constant",
            _grid(
                "p3-tan:a4",
                (1, 2, -1),
                (-3, -2, -1, 1, 2, 3),
                (-4, -2, -1, 1, 3, 5),
                tuple(range(-5, 6)),
                _POINTS,
            ),
            a4,
        ),
        Frame(
            "applied-cubic-tangent-through-origin",
            _grid("p3-tan:a5", (1, -1), (-6, -3, -1, 2, 4, 5), (1, 2)),
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
    setup: str | None = None,
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
        solution_setup=setup,
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
            setup=f"{_tangent_at(f, a, '0')} = y",
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
            setup=f"{_tangent_at(f, a, str(t))} = y",
            explanation=(
                f"도함수 {render_poly(derivative_of(f))}에 x = {with_eul_reul(a)} 대입하면 "
                "기울기는 "
                f"{m}이므로 접선은 {_pt_slope(m, a, fa)}이다. 따라서 "
                f"g({t}){eun_neun(f'g({t})')} {value}이다.{_POWER_TRAP}"
            ),
            shuffle_key=f"mc4:{render_poly(f)}:{a}:{t}",
        )

    def m5(p: tuple[object, ...]) -> DiffItem | None:
        # 7회차 감사(2026-10-08) 처분 — 종전 '곡선 y = x^2 위의 점 (a, a^2)에서의 접선의 기울기가
        # b'는 기울기 b인 직선과 연립한 x^2 - bx - k = 0의 중근 x = b/2(판별식)로 미분 없이
        # 풀렸다(판정자 지적 ac28058d·ee5a4588 · 판정기 T05-quadratic-slope). 삼차곡선 y = x^3 +
        # qx로 바꾼다 — f'(a) = 3a^2 + q = b의 두 근 ±a0 중 양수를 발문의 'a > 0'이 고른다. 오개념
        # 선지는 그 절차로 정확히 나오는 값만 연결한다: 계수 누락 (x^3)' = x^2 → a^2 + q = b → a =
        # a0√3(늘 무리수 — 근호 표기), 지수 유지 (x^3)' = 3x^3·(qx)' = qx → 3a^3 + qa = b의 양의
        # 실근이 유리수일 때만.
        q, a0 = _as_int(p[0]), _as_int(p[1])
        b = 3 * a0 * a0 + q
        a = sympy.Symbol("a")
        omitted = sympy.sqrt(sympy.Integer(b - q))  # a^2 = b - q = 3a0^2
        kept = [r for r in sympy.solve(3 * a**3 + q * a - b, a) if r.is_real and r > 0]
        entries = [
            ChoiceEntry(str(a0), is_correct=True, sort_key=float(a0)),
            ChoiceEntry(render_surd(omitted), _KEBAB, sort_key=float(omitted)),
        ]
        if len(kept) == 1 and kept[0].is_rational and kept[0] != a0:
            entries.append(ChoiceEntry(str(kept[0]), _KEBAB, sort_key=float(kept[0])))
        for filler in (a0 * a0, 3 * a0, a0 + 1):
            if len(entries) == 4:
                break
            if str(filler) not in {e.text for e in entries}:
                entries.append(ChoiceEntry(str(filler), sort_key=float(filler)))
        try:
            choices, answer, distractors = build_choices(entries, shuffle_seed=f"mc5:{q}:{a0}")
        except ValueError:
            return None
        shown = render_poly(((3, 1), (1, q)))
        omitted_d = render_poly(((2, 1), (0, q)))
        kept_d = render_poly(((3, 3), (1, q)))
        return DiffItem(
            slot="misconception_trigger",
            frame_id="mc-find-point-on-cubic-with-linear-term",
            question_text=(
                f"곡선 y = {shown} 위의 점 (a, {render_poly(((3, 1), (1, q)), 'a')}) (a > 0)에서의 "
                f"접선의 기울기가 {b}일 때, a의 값은?"
            ),
            answer_text=answer,
            explanation=(
                f"{shown}의 도함수는 {render_poly(((2, 3), (0, q)))}이므로 "
                f"{render_poly(((2, 3), (0, q)), 'a')} = {b}에서 a^2 = {a0 * a0}이고, "
                f"a는 양수이므로 a = {a0}이다. 도함수를 {omitted_d}{euro_ro(omitted_d)} "
                f"쓰거나(계수 3 누락) {kept_d}{euro_ro(kept_d)} 쓰면(지수를 1 줄이지 않음) "
                "다른 값이 나온다."
            ),
            conditions=(f"Derivative(x**3 + {q}*x, x).doit().subs(x, a) = {b}", "a > 0"),
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
            # 학생 표기 — '9√3'(4차 감사 bad_wording: 3차의 '9sqrt(3)'도 코드 표기로 판정됐다).
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
        Frame(
            "mc-find-point-on-cubic-with-linear-term",
            _grid("p3-tan:m5", (1, 2, 3, 5, 6, 9, 12, 24), (2, 3, 4, 5)),
            m5,
        ),
        Frame("mc-find-point-on-cubic", _grid("p3-tan:m6", (3, 4, 5, 6, 7, 9, 10)), m6),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 진단(diagnostic) — 접선의 기울기 = 미분계수라는 핵심 사실을 한 가지씩 확인
# ──────────────────────────────────────────────────────────────────────────
def _diagnostic_frames() -> list[Frame]:
    """진단 슬롯 — 4차 감사(2026-10-07) bad_tag 처분으로 틀 5종 중 4종을 바꿨다.

    삭제: 포물선 꼭짓점에서의 접선의 기울기·포물선의 x축에 평행한 접선(꼭짓점 공식 -b/(2a)로 풀림 —
    판정기 T05-vertex-tangent) · 직선(상수함수 포함) 위의 점에서의 접선의 기울기(직선의 기울기를
    읽기만 하면 됨 — T05-line-tangent) · y = x^n의 원점에서의 접선의 기울기(정답·원함수 대입·오답
    경로가 모두 0 — T-zero-monomial). 대신 *미분계수와 함숫값을 구별해야* 답이 정해지는 틀을 둔다.
    """
    slot = "diagnostic"

    def d4(p: tuple[object, ...]) -> DiffItem | None:
        # 5회차 감사(2026-10-08) 처분 — 종전 'y축과 만나는 점에서의 접선의 기울기'는 x = 0의
        # 미분계수라 일차항 계수를 읽기만 해도 답이 나왔다(판정자 지적 953ef7a0 · 판정기
        # T-coefficient-reading). 대신 *점의 y좌표*와 *접선의 기울기*를 구별해야 하는 틀을 둔다 —
        # y좌표로 접점의 x좌표를 먼저 찾고(증가함수라 하나뿐) 그 점의 미분계수를 구한다. y좌표를
        # 답으로 옮기는 오답 경로는 정답과 다르다(같으면 매개변수 거부 조건이 건너뛴다).
        lead, q, d, a = (_as_int(v) for v in p)
        if lead * q <= 0 or a == 0:
            return None
        f = _poly({3: lead, 1: q, 0: d})
        level = eval_at(f, a)
        m = eval_at(derivative_of(f), a)
        moved = _minus_const(f, level)
        return DiffItem(
            slot=slot,
            frame_id="diag-slope-at-point-with-given-y",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 점 중 y좌표가 {level}인 점은 하나뿐이다. "
                "이 점에서의 접선의 기울기를 구하시오."
            ),
            answer_text=str(m),
            explanation=(
                f"y좌표가 {level}인 점의 x좌표는 방정식 {render_poly(f)} = {level}, 즉 "
                f"{render_poly(moved)} = 0의 실근이다. {render_factored(moved)} = 0이고 이차식 "
                f"인수는 실근이 없으므로 x = {a}이다. 접선의 기울기는 접점에서의 미분계수이고 "
                f"도함수는 y' = {render_poly(derivative_of(f))}이므로 x = {a}에서의 기울기는 "
                f"{m}이다."
            ),
            conditions=f"{_d(f, str(a))} = y",
            answer_map=(("y", str(m)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(m),
        )

    def d7(p: tuple[object, ...]) -> DiffItem | None:
        # x축과 만나는 점(y = 0)에서의 기울기 — '그 점의 y좌표(0)'와 '접선의 기울기'를 혼동하면
        # 0을 답한다. 삼차 곡선이라 이중근(판별식) 우회로도 없다.
        lead, p_root, q_root, r_root = (_as_int(v) for v in p)
        if not p_root < q_root < r_root:
            return None
        expr = sympy.expand(lead * (_X - p_root) * (_X - q_root) * (_X - r_root))
        f = poly_from_sympy(expr)
        if max(abs(c) for _, c in f) > 40:
            return None
        m = eval_at(derivative_of(f), r_root)
        factored = render_factored(f)
        return DiffItem(
            slot=slot,
            frame_id="diag-slope-at-largest-x-intercept",
            question_text=(
                f"곡선 y = {render_poly(f)}{i_ga(render_poly(f))} x축과 만나는 점 중 x좌표가 "
                "가장 큰 점에서의 접선의 기울기를 구하시오."
            ),
            answer_text=str(m),
            explanation=(
                f"y = {factored}이므로 곡선이 x축과 만나는 점의 x좌표는 {p_root}, {q_root}, "
                f"{r_root}이고 가장 큰 값은 {r_root}이다. 이 점의 y좌표는 0이지만 접선의 기울기는 "
                f"미분계수이다. 도함수는 y' = {render_poly(derivative_of(f))}이므로 "
                f"x = {r_root}에서의 기울기는 {m}이다."
            ),
            conditions=f"{_d(f, str(r_root))} = y",
            answer_map=(("y", str(m)),),
            problem_type_code=_EVAL,
            answer_format=_fmt(m),
        )

    def d8(p: tuple[object, ...]) -> DiffItem | None:
        # 기울기가 m인 접선이 하나뿐인 삼차 곡선 — f'(x) - m = 3·lead(x - r)^2(이중근)이라 접점이
        # 하나다. 포물선의 '수평 접선 = 꼭짓점'(-b/(2a)) 같은 우회로가 없고, 근이 하나라 검산 조건이
        # 문자열 하나로 성립한다(섀도 채점 단일 미지수 계약).
        lead, r, m, d = (_as_int(v) for v in p)
        f = _poly({3: lead, 2: -3 * lead * r, 1: 3 * lead * r * r + m, 0: d})
        if max(abs(c) for _, c in f) > 40 or len(f) < 3:
            return None
        fp = derivative_of(f)
        moved = _minus_const(fp, m)
        return DiffItem(
            slot=slot,
            frame_id="diag-unique-tangent-slope-point",
            question_text=(
                f"곡선 y = {render_poly(f)} 위의 점 중 접선의 기울기가 {with_i_ga(m)} 되는 점은 "
                "하나뿐이다. 그 점의 x좌표를 구하시오."
            ),
            answer_text=str(r),
            explanation=(
                f"접선의 기울기는 미분계수이다. 도함수는 y' = {render_poly(fp)}이므로 "
                f"{render_poly(fp)} = {m}, 즉 {render_factored(moved)} = 0이다. 이 방정식의 근은 "
                f"x = {r} 하나뿐이므로 구하는 x좌표는 {r}이다."
            ),
            conditions=f"{_d(f, 'a')} = {m}",
            answer_map=(("a", str(r)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(r),
        )

    def d9(p: tuple[object, ...]) -> DiffItem | None:
        # y = x^n 위의 점 (-1, (-1)^n)에서의 접선의 y절편 — 기울기 n(-1)^(n - 1)을 거쳐야 한다.
        # 함숫값과 혼동하거나 지수 홀짝의 부호를 놓치면 다른 값이 나온다(원점이던 종전 틀은 모든
        # 경로가 0이었다). 같은 점의 *기울기*는 02-03 진단 f'(-1)과 검산 실체가 겹쳐(배치 교차
        # 중복 제거) 기울기 대신 y절편을 묻는다.
        n = _as_int(p[0])
        f: Poly = ((n, 1),)
        m, fa, k = _tangent(f, -1)
        # 검산은 형제 틀(basic-y-intercept-of-cubic-tangent)과 같은 산술 재확인 — Tier1은
        # Derivative(...)와 산술을 섞은 관계를 파싱하지 않는다(unverifiable).
        return _echo_item(
            slot=slot,
            frame_id="diag-tangent-intercept-of-power-at-minus-one",
            text=f"곡선 y = x^{n} 위의 점 (-1, {fa})에서의 접선의 y절편을 구하시오.",
            value=k,
            explanation=(
                f"접선의 기울기는 접점에서의 미분계수이다. 도함수는 y' = "
                f"{render_poly(derivative_of(f))}이므로 x = -1에서의 기울기는 {m}이다. 접선은 "
                f"{_pt_slope(m, -1, fa)}이고, x = 0을 대입하면 y절편은 {k}이다."
            ),
            expr=f"({fa}) - (-1)*({m})",
            ptype=_EVAL,
            setup=f"{_tangent_at(f, -1, '0')} = y",
        )

    return [
        Frame(
            "diag-slope-at-point-with-given-y",
            _grid("p3-tan:d4", (1, -1, 2), (-5, -3, -2, -1, 1, 2, 3, 5), (-4, -1, 2, 5), _POINTS),
            d4,
        ),
        Frame(
            "diag-slope-at-largest-x-intercept",
            _grid("p3-tan:d7", (1, -1, 2), (-3, -2, -1), (0, 1), (2, 3, 4)),
            d7,
        ),
        Frame(
            "diag-unique-tangent-slope-point",
            _grid("p3-tan:d8", (1, 2, -1), (-2, -1, 1, 2, 3), (-6, -3, 2, 4, 5), (-4, -1, 2, 5)),
            d8,
        ),
        Frame(
            "diag-tangent-intercept-of-power-at-minus-one",
            _grid("p3-tan:d9", (2, 3, 4, 5, 6, 7, 8)),
            d9,
        ),
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
            # 직선이 x = r2에서의 접선이므로 k는 그 접선의 y절편 f(r2) + f'(r2)(0 - r2)이다.
            # (접점 r2를 f'(a) = m으로 고르는 앞 단계는 연쇄에 싣지 못한다 — 미지수가 바뀐다.)
            solution_setup=f"{_tangent_at(f, r2, '0')} = k",
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
            # 곡선 f(s)와 접선 f'(a)(s - a) + f(a)를 연립 — 접선의 기울기를 미분으로 되돌린 같은 식.
            solution_setup=(
                f"({poly_to_sympy_str(f, 's')} - ({poly_to_sympy_str(f)}"
                f" + Derivative({poly_to_sympy_str(f)}, x)*(s - x))).doit().subs(x, {a}) = 0"
            ),
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
            # 해설의 마지막 단계 — 접선의 기울기는 접점 x = t에서의 미분계수 f'(t)다. (t를 고르는
            # f(t) - tf'(t) = 점의 y좌표는 허근이 섞인 삼차라 해집합 판정 불가 — 연쇄에 싣지
            # 못한다.)
            solution_setup=f"{_d(f, str(t))} = m",
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
            # 넓이 = (1/2)|y절편 f(a) - af'(a)|·|x절편 a - f(a)/f'(a)|.
            setup=(
                _setup_at(
                    f"(1/2)*Abs({poly_to_sympy_str(f)} - x*Derivative({poly_to_sympy_str(f)}, x))"
                    f"*Abs(x - ({poly_to_sympy_str(f)})/Derivative({poly_to_sympy_str(f)}, x))",
                    str(a),
                )
                + " = y"
            ),
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
            # 해설의 y절편 f(a) - af'(a) = n — 도함수를 미분으로 되돌린 같은 식(미지수 p).
            solution_setup=(
                _setup_at(f"{sympy.sstr(curve)} - x*Derivative({sympy.sstr(curve)}, x)", str(a))
                + f" = {n}"
            ),
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
        # 검산(5회차 감사 교정 · 284122b4): 발문의 문제 그대로 — 접점 x = a 고정, p·q 둘 다 미지수.
        # 두 곡선이 x = a에서 접한다 ⇔ 차 g(x) - (x^2 + px + q)가 (x - a)^2을 인수로 갖는다(x에 대한
        # 항등식 — 미분을 쓰지 않는 독립 경로). 나머지 Ax + B에서 A = 0은 p를 정하고, 상수항 B에서는
        # p가 소거된다(B = 차(a) - a·차'(a)) — 그래서 B = 0 한 식이 발문 문제의 q 해집합 그 자체다.
        # 섀도 채점 계약(미지수 1개)을 지키면서 접점 x = a 고정을 그대로 담는다. 구판은 p를 미리
        # 숫자로 고정하고 접점을 풀어 둔 판별식(-27q^2 - 94q + 525 = 0)에 발문에 없는 보호 조건
        # (q > -6)으로 둘째 해를 버렸다 — 다른 문제를 담았다(판정기 V05-touch-verify-mismatch).
        p_sym, q_sym = sympy.Symbol("p"), sympy.Symbol("q")
        gap = sympy.expand(poly_to_sympy(g) - (_X**2 + p_sym * _X + q_sym))
        remainder = sympy.Poly(sympy.rem(gap, (_X - a) ** 2, _X), _X)
        slope_coeff, constant_coeff = (sympy.expand(c) for c in remainder.all_coeffs())
        if p_sym in constant_coeff.free_symbols:
            return None  # pragma: no cover — 구성 오류(상수항에서 p가 소거되지 않았다)
        solved = sympy.solve([slope_coeff, constant_coeff], [p_sym, q_sym])
        if solved != {p_sym: p0, q_sym: q0}:
            return None  # pragma: no cover — 구성 오류(검산 조건이 해설의 p·q와 다르다)
        conditions = f"{sympy.sstr(constant_coeff)} = 0"
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
            # 해설의 두 조건을 한 식으로 — 기울기 조건 p = g'(a) - (x^2)'(a)를 함숫값 조건
            # q = g(a) - a^2 - pa에 넣는다(미지수 q 하나).
            solution_setup=(
                _setup_at(
                    f"{poly_to_sympy_str(g)} - x**2"
                    f" - (Derivative({poly_to_sympy_str(g)}, x) - Derivative(x**2, x))*x",
                    str(a),
                )
                + " = q"
            ),
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
        return round_robin_items(
            _SLOT_FRAMES[slot](),
            cls.slot_count,
            claimed=claimed,
            standard_code=cls.standard_code,  # 매개변수 거부 조건(우연 일치 — 5회차 감사)
        )
