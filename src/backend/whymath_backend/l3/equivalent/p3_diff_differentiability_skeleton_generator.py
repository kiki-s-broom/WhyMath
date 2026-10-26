"""[12미적Ⅰ-02-02] 미분가능성과 연속성 결정론 문항 생성기 — P3-05 4단계(결정론·LLM 0).

개념: `H:12미적Ⅰ02-02`(함수의 미분가능성과 연속성). 슬롯이 비어 있던 5칸(대표·기본·응용·진단·
숙련도 확인)을 채운다 — 오개념 유발 칸은 기존 승인 문항(`conceptual_v0` 24건)이 이미 채웠다.

기존 문항과 다른 점 — 미분가능한 **양성 예**
------------------------------------------
기존 24건은 전부 `f(x) = |x - a| (+ b)` 꼴이라 정답이 늘 0(미분가능하지 않다)이었다. "절댓값이면 0"
이라는 규칙 하나로 풀려 변별력이 없다. 이 생성기는 미분가능한 함수와 그렇지 않은 함수를 섞는다.
- 진단: 절댓값이 있어도 매끄러운 함수(`(x - p)|x - p|`·`|(x - p)^2|`·`|x - p|^3`)의 f'(p).
- 응용·숙련도 확인: `|x - p|(cx + a)`에서 미지 상수 a로 꺾임을 없앤다(미분가능하다는 전제).
- 대표·기본: 꺾이는 함수의 좌·우미분계수. 대표 틀의 답 '우 - 좌'는 0일 수 없다 — 좌·우 분기의 차는
  연속성 때문에 x = p에서 함숫값이 0이라, 0이 답이면 함숫값 대입 오답 경로와 겹쳐 우회로 판정기
  (T-function-value-path)가 거부한다. 미분가능한 쪽의 양성 예는 위 세 칸이 맡는다.

모든 문항은 **스칼라 답**이다(좌·우미분계수의 값·차, 미분계수, 미지 상수). 0/1 판정형
(`is_differentiable` 개념형)은 풀이 단계를 손으로 달아야 해서 쓰지 않았다.

검산 재료
---------
함수를 `Abs(u)`로 쓰는 대신 **분기 식**으로 푼다: x = p에서 u(p) = 0이고 u'(p) > 0이면 우쪽에서
|u| = u, 좌쪽에서 |u| = -u (u'(p) < 0이면 반대). 우·좌미분계수는 각 분기 식의
`Derivative(...).doit().subs(x, p)`다(정의에 필요한 연속성은 |u|(p) = 0이라 자동으로 성립한다).
차(우 - 좌)는 *합쳐 한 번에 미분*한다(`Derivative(R - L, x)`) — Tier1은 미분 평가를 다른 연산과
섞지 못한다. 양변이 모두 미분 평가인 등식은 허용된다(`Derivative(R, x)... = Derivative(L, x)...`).

문제유형 정직성
--------------
값을 계산하는 대표·기본·진단은 `ptype.evaluate-expression`, 미지 상수를 구하는 응용·숙련도 확인은
`ptype.solve-for-unknown`.
"""

from __future__ import annotations

from typing import ClassVar, Final

import sympy

from whymath_backend.l3.equivalent.p3_diff_expr import Poly, render_poly
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    DiffItem,
    Frame,
    P3DiffSlotGenerator,
    SlotId,
    answer_format_for,
    round_robin_items,
    seeded_order,
)

__all__ = ["P3DiffDifferentiabilityGenerator"]

_EVAL: Final = "ptype.evaluate-expression"
_SOLVE: Final = "ptype.solve-for-unknown"

_X = sympy.Symbol("x")
_A = sympy.Symbol("a")


# ──────────────────────────────────────────────────────────────────────────
# 식 도구 — 분기 식·표기
# ──────────────────────────────────────────────────────────────────────────
def _grid(seed: str, *axes: tuple[int, ...]) -> tuple[tuple[object, ...], ...]:
    combos: list[tuple[object, ...]] = [()]
    for axis in axes:
        combos = [(*c, v) for c in combos for v in axis]
    return tuple(seeded_order(seed, combos))


def _shift(p: int) -> str:
    """`x - p`(p가 음수면 `x + |p|`, 0이면 `x`) — '- -' 표기를 만들지 않는다."""
    if p == 0:
        return "x"
    return f"x - {p}" if p > 0 else f"x + {-p}"


def _factor(c: int, a_text: str | None = None) -> str:
    """`cx + a`·`x + a` 꼴 일차 인수의 표기(c = 1이면 계수 생략)."""
    lead = "x" if c == 1 else f"{c}x"
    return f"{lead} + {a_text}" if a_text else lead


def _join(parts: list[str]) -> str:
    """항 문자열들을 부호에 맞게 이어 붙인다('+ -' 표기를 만들지 않는다)."""
    out = parts[0]
    for part in parts[1:]:
        if part.startswith("-"):
            out += f" - {part[1:]}"
        else:
            out += f" + {part}"
    return out


def _render(expr: sympy.Expr) -> str:
    """x(와 미지 상수 a)의 다항식 SymPy 식 → 학생 표기('4x + a - 2'·'2ax - 3').

    항은 x의 차수 내림차순, 같으면 a의 차수 내림차순이다. 계수 1·0 표기를 만들지 않고 곱은 이어 쓴다
    (계수 0인 항은 없다).
    """
    poly = sympy.Poly(sympy.expand(expr), _X, _A)
    parts: list[str] = []
    for (ex, ea), coef in sorted(poly.terms(), key=lambda t: (-t[0][0], -t[0][1])):
        c = int(coef)
        body = ("a" if ea == 1 else f"a^{ea}" if ea > 1 else "") + (
            "x" if ex == 1 else f"x^{ex}" if ex > 1 else ""
        )
        magnitude = abs(c)
        if not body:
            text = str(magnitude)
        else:
            text = body if magnitude == 1 else f"{magnitude}{body}"
        parts.append(f"-{text}" if c < 0 else text)
    return _join(parts) if parts else "0"


def _smooth_part(r: Poly) -> sympy.Expr:
    return sympy.Add(*(sympy.Integer(c) * _X**e for e, c in r))


def _branches(f_expr: sympy.Expr, point: int) -> tuple[sympy.Expr, sympy.Expr]:
    """x = point 둘레의 (좌분기, 우분기) 다항식.

    각 `Abs(u)`에 대해: u(point) ≠ 0이면 꺾임점이 아니라 point 둘레에서 부호가 한 가지다 — 부호대로
    ±u로 푼다(두 분기 같음). u(point) = 0인 꺾임점에서는 u'(point) > 0이면 우쪽 |u| = u · 좌쪽 -u,
    u'(point) < 0이면 반대. u'(point) = 0이면(`|u^2|` 꼴) u는 한 점 근방에서 부호가 같으므로
    |u| = ±u 가운데 u(x) ≥ 0인 쪽을 SymPy로 고른다.
    """
    left, right = f_expr, f_expr
    for term in f_expr.atoms(sympy.Abs):
        inner = term.args[0]
        at_point = sympy.simplify(inner.subs(_X, point))
        if at_point != 0:
            same = inner if at_point > 0 else -inner
            right = right.xreplace({term: same})
            left = left.xreplace({term: same})
            continue
        slope = sympy.diff(inner, _X).subs(_X, point)
        if slope > 0:
            right_sub, left_sub = inner, -inner
        elif slope < 0:
            right_sub, left_sub = -inner, inner
        else:
            # u'(point) = 0 — u가 (x - point)^2 의 상수배 꼴이면 부호가 한쪽으로 고정이다.
            probe = inner.subs(_X, point + sympy.Rational(1, 7))
            sign = 1 if probe > 0 else -1
            right_sub = left_sub = inner if sign > 0 else -inner
        right = right.xreplace({term: right_sub})
        left = left.xreplace({term: left_sub})
    return sympy.expand(left), sympy.expand(right)


def _at(expr: sympy.Expr, point: int) -> str:
    """`Derivative(식, x).doit().subs(x, 점)` — 미분 평가 1회(맨몸)."""
    return f"Derivative({expr}, x).doit().subs(x, {point})"


def _constant_slope(*branches: sympy.Expr) -> bool:
    """분기 식 가운데 하나라도 도함수가 상수(일차 이하)면 True — 해설의 도함수 식이 x를 담지 못한다.

    우회로 판정기(E-derivative)는 해설에 x를 담은 도함수 식을 요구한다. 상수 도함수는 그 식이 없어
    결론만 적은 해설로 읽히므로 그 매개변수를 건너뛴다(틀 설계가 아니라 수치 선택의 우연).
    """
    return any(_X not in sympy.diff(b, _X).free_symbols for b in branches)


def _poly_value(expr: sympy.Expr, point: int) -> int:
    return int(sympy.diff(expr, _X).subs(_X, point))


_Q_POOL: Final = tuple(
    ((2, a), (1, b), (0, c)) for a in (1, 2, -1) for b in (-4, -2, 1, 3, 5) for c in (-3, 0, 2, 4)
)
_POINTS: Final = (2, -1, 3, -2, 1)


def _pq(seed: str) -> tuple[tuple[object, ...], ...]:
    """(함수 r, 꺾임점 p) 후보열 — 점을 번갈아 붙여 앞 몇 개만 써도 점이 치우치지 않는다."""
    ordered = seeded_order(seed, _Q_POOL)
    return tuple((r, _POINTS[i % len(_POINTS)]) for i, r in enumerate(ordered))


def _mix(
    base: tuple[tuple[object, ...], ...], extras: tuple[object, ...]
) -> tuple[tuple[object, ...], ...]:
    """(함수, 점) 후보 × 틀 고유 값 — 앞 후보들이 틀 고유 값을 돌아가며 쓰도록 짝짓는다.

    i번째 기반 후보는 `extras[(i + 이동) % n]`을 받는다(이동 = 0, 1, …). 그래서 앞 n개 후보가
    서로 다른 값을 쓰고, 같은 함수·점이 연달아 앞에 서지도 않는다.
    """
    n = len(extras)
    out: list[tuple[object, ...]] = []
    for shift in range(n):
        for i, b in enumerate(base):
            e = extras[(i + shift) % n]
            out.append((*b, *e) if isinstance(e, tuple) else (*b, e))
    return tuple(out)


def _rp(p: tuple[object, ...]) -> tuple[Poly, int]:
    r, point = p
    assert isinstance(r, tuple) and isinstance(point, int)
    return r, point


# ──────────────────────────────────────────────────────────────────────────
# 대표(representative) — 우미분계수와 좌미분계수의 차
# ──────────────────────────────────────────────────────────────────────────
def _diff_of_one_sided(
    *,
    frame_id: str,
    f_text: str,
    f_expr: sympy.Expr,
    point: int,
    slot: str = "representative",
) -> DiffItem | None:
    """`(우미분계수) - (좌미분계수)`를 묻는다(꺾이는 함수라 답은 0이 아니다)."""
    left, right = _branches(f_expr, point)
    if _constant_slope(left, right):
        return None
    value = _poly_value(right - left, point)
    r_val, l_val = _poly_value(right, point), _poly_value(left, point)
    # 절댓값 항이 둘 이상이거나 절댓값 안이 이차 이상이면 다른 꺾임점 너머에서는 식이 달라진다 —
    # 분기 식은 x = point 근처에서만 맞다.
    absolutes = f_expr.atoms(sympy.Abs)
    near = len(absolutes) > 1 or any(sympy.degree(a.args[0], _X) > 1 for a in absolutes)
    right_at = f"x = {point} 가까이에서 x > {point}일 때" if near else f"x > {point}에서"
    left_at = f"x = {point} 가까이에서 x < {point}일 때" if near else f"x < {point}에서"
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=(
            f"함수 f(x) = {f_text}에 대하여 x = {point}에서의 우미분계수에서 좌미분계수를 뺀 값을 "
            "구하시오."
        ),
        answer_text=str(value),
        explanation=(
            f"{right_at} f(x) = {_render(right)}이므로 "
            f"f'(x) = {_render(sympy.diff(right, _X))}이고 우미분계수는 {r_val}이다. "
            f"{left_at} f(x) = {_render(left)}이므로 "
            f"f'(x) = {_render(sympy.diff(left, _X))}이고 좌미분계수는 {l_val}이다. "
            f"따라서 구하는 값은 {r_val} - {f'({l_val})' if l_val < 0 else l_val} = {value}이다."
            + (f" 이 값이 0이므로 x = {point}에서 미분가능하다." if value == 0 else "")
        ),
        conditions=f"Derivative({right} - ({left}), x).doit().subs(x, {point}) = y",
        answer_map=(("y", str(value)),),
        problem_type_code=_EVAL,
        answer_format=answer_format_for(str(value)),
        solution_setup=(
            f"(Derivative({right}, x) - Derivative({left}, x)).doit().subs(x, {point}) = y"
        ),
    )


def _rep_frames() -> list[Frame]:
    def kink(p: tuple[object, ...]) -> DiffItem | None:
        (r, point), k = _rp(p[:2]), int(str(p[2]))
        f_expr = k * sympy.Abs(_X - point) + _smooth_part(r)
        lead = "|%s|" % _shift(point)
        head = lead if k == 1 else ("-" + lead if k == -1 else f"{k}{lead}")
        return _diff_of_one_sided(
            frame_id="rep-kink-times-constant",
            f_text=_join([head, render_poly(r)]),
            f_expr=f_expr,
            point=point,
        )

    def times_linear(p: tuple[object, ...]) -> DiffItem | None:
        (r, point), s = _rp(p[:2]), int(str(p[2]))
        if s == 0:
            return None
        f_expr = sympy.Abs(_X - point) * (_X - s) + _smooth_part(r)
        return _diff_of_one_sided(
            frame_id="rep-kink-times-linear-factor",
            f_text=_join([f"|{_shift(point)}|({_shift(s)})", render_poly(r)]),
            f_expr=f_expr,
            point=point,
        )

    def two_absolute_values(p: tuple[object, ...]) -> DiffItem | None:
        (r, point), k1, k2, gap = _rp(p[:2]), int(str(p[2])), int(str(p[3])), int(str(p[4]))
        other = point + gap
        f_expr = k1 * sympy.Abs(_X - point) + k2 * sympy.Abs(_X - other) + _smooth_part(r)

        def lead(k: int, at: int) -> str:
            body = f"|{_shift(at)}|"
            return body if k == 1 else (f"-{body}" if k == -1 else f"{k}{body}")

        return _diff_of_one_sided(
            frame_id="rep-two-absolute-values",
            f_text=_join([lead(k1, point), lead(k2, other), render_poly(r)]),
            f_expr=f_expr,
            point=point,
        )

    def abs_of_quadratic(p: tuple[object, ...]) -> DiffItem | None:
        r, point = _rp(p[:2])
        if point == 0:
            return None
        f_expr = sympy.Abs(_X**2 - point**2) + _smooth_part(r)
        return _diff_of_one_sided(
            frame_id="rep-abs-of-difference-of-squares",
            f_text=_join([f"|x^2 - {point * point}|", render_poly(r)]),
            f_expr=f_expr,
            point=point,
        )

    base = _pq("p3d:rep")
    return [
        Frame("rep-kink-times-constant", _mix(base, (2, -3, 1)), kink),
        Frame(
            "rep-kink-times-linear-factor",
            _mix(base, (3, -2, 1, 4, -1)),
            times_linear,
        ),
        Frame(
            "rep-two-absolute-values",
            _mix(base, ((2, 1, 3), (3, -2, -4), (1, 2, 5), (-2, 3, 4), (2, 3, -3))),
            two_absolute_values,
        ),
        Frame(
            "rep-abs-of-difference-of-squares",
            _mix(base, (0,)),
            abs_of_quadratic,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 기본(basic) — 한쪽 미분계수 하나
# ──────────────────────────────────────────────────────────────────────────
def _one_sided(
    *,
    frame_id: str,
    f_text: str,
    f_expr: sympy.Expr,
    point: int,
    side: str,
    slot: str = "basic",
) -> DiffItem | None:
    left, right = _branches(f_expr, point)
    branch, name, ineq = (
        (right, "우미분계수", ">") if side == "right" else (left, "좌미분계수", "<")
    )
    if _constant_slope(branch):
        return None
    value = _poly_value(branch, point)
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=f"함수 f(x) = {f_text}에 대하여 x = {point}에서의 {name}를 구하시오.",
        answer_text=str(value),
        explanation=(
            f"x {ineq} {point}에서 f(x) = {_render(branch)}이므로 "
            f"f'(x) = {_render(sympy.diff(branch, _X))}이고, {name}는 {value}이다."
        ),
        conditions=_at(branch, point) + " = y",
        answer_map=(("y", str(value)),),
        problem_type_code=_EVAL,
        answer_format=answer_format_for(str(value)),
    )


def _basic_frames() -> list[Frame]:
    def with_constant(side: str, frame_id: str) -> Frame:
        def build(p: tuple[object, ...]) -> DiffItem | None:
            (r, point), k = _rp(p[:2]), int(str(p[2]))
            f_expr = k * sympy.Abs(_X - point) + _smooth_part(r)
            lead = "|%s|" % _shift(point)
            head = lead if k == 1 else ("-" + lead if k == -1 else f"{k}{lead}")
            return _one_sided(
                frame_id=frame_id,
                f_text=_join([head, render_poly(r)]),
                f_expr=f_expr,
                point=point,
                side=side,
            )

        base = _pq(f"p3d:{frame_id}")
        return Frame(frame_id, _mix(base, (2, 3, -2, 1)), build)

    def with_factor(side: str, frame_id: str) -> Frame:
        def build(p: tuple[object, ...]) -> DiffItem | None:
            (r, point), s = _rp(p[:2]), int(str(p[2]))
            if s == 0:
                return None
            f_expr = sympy.Abs(_X - point) * (_X - s) + _smooth_part(r)
            return _one_sided(
                frame_id=frame_id,
                f_text=_join([f"|{_shift(point)}|({_shift(s)})", render_poly(r)]),
                f_expr=f_expr,
                point=point,
                side=side,
            )

        base = _pq(f"p3d:{frame_id}")
        return Frame(frame_id, _mix(base, (3, -2, 4, -1)), build)

    return [
        with_constant("right", "basic-right-derivative-kink-times-constant"),
        with_constant("left", "basic-left-derivative-kink-times-constant"),
        with_factor("right", "basic-right-derivative-kink-times-linear-factor"),
        with_factor("left", "basic-left-derivative-kink-times-linear-factor"),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 응용(applied) — 미분가능하도록 하는 상수
# ──────────────────────────────────────────────────────────────────────────
def _unknown_constant(
    *,
    slot: str,
    frame_id: str,
    f_text: str,
    f_expr: sympy.Expr,
    point: int,
    a_true: int,
) -> DiffItem:
    """`f가 x = point에서 미분가능하도록 하는 상수 a` — 좌·우미분계수가 같다는 방정식을 푼다."""
    left, right = _branches(f_expr, point)
    r_expr, l_expr = sympy.diff(right, _X), sympy.diff(left, _X)
    r_at, l_at = _render(r_expr.subs(_X, point)), _render(l_expr.subs(_X, point))
    got = sympy.solve(sympy.Eq(r_expr.subs(_X, point), l_expr.subs(_X, point)), _A)
    if got != [a_true]:
        raise ValueError(f"{frame_id}: a 가 유일하지 않다 — {got} != {a_true}")
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=(
            f"함수 f(x) = {f_text} (a는 상수)가 x = {point}에서 미분가능할 때, "
            "상수 a의 값을 구하시오."
        ),
        answer_text=str(a_true),
        explanation=(
            f"x > {point}에서 f'(x) = {_render(r_expr)}이므로 우미분계수는 {r_at}이고, "
            f"x < {point}에서 f'(x) = {_render(l_expr)}이므로 좌미분계수는 {l_at}이다. "
            f"두 값이 같아야 하므로 {r_at} = {l_at}에서 a = {a_true}이다."
        ),
        conditions=(
            f"Derivative({right}, x).doit().subs(x, {point}) = "
            f"Derivative({left}, x).doit().subs(x, {point})"
        ),
        answer_map=(("a", str(a_true)),),
        problem_type_code=_SOLVE,
        answer_format=answer_format_for(str(a_true)),
    )


def _applied_frames() -> list[Frame]:
    def linear(p: tuple[object, ...]) -> DiffItem | None:
        point, c = int(str(p[0])), int(str(p[1]))
        a_true = -c * point
        if a_true == 0:
            return None
        f_expr = sympy.Abs(_X - point) * (c * _X + _A)
        return _unknown_constant(
            slot="applied",
            frame_id="applied-abs-times-linear-factor",
            f_text=f"|{_shift(point)}|({_factor(c, 'a')})",
            f_expr=f_expr,
            point=point,
            a_true=a_true,
        )

    def with_square(p: tuple[object, ...]) -> DiffItem | None:
        point, m = int(str(p[0])), int(str(p[1]))
        a_true = -m * point * point
        f_expr = sympy.Abs(_X - point) * (m * _X**2 + _A)
        lead = "x^2" if m == 1 else f"{m}x^2"
        return _unknown_constant(
            slot="applied",
            frame_id="applied-abs-times-quadratic-factor",
            f_text=f"|{_shift(point)}|({lead} + a)",
            f_expr=f_expr,
            point=point,
            a_true=a_true,
        )

    def with_smooth_term(p: tuple[object, ...]) -> DiffItem | None:
        point, c, r_c = (int(str(v)) for v in p)
        a_true = -c * point
        if a_true == 0:
            return None
        f_expr = sympy.Abs(_X - point) * (c * _X + _A) + r_c * _X**2
        r_text = "x^2" if r_c == 1 else ("-x^2" if r_c == -1 else f"{r_c}x^2")
        return _unknown_constant(
            slot="applied",
            frame_id="applied-abs-times-linear-plus-smooth",
            f_text=_join([f"|{_shift(point)}|({_factor(c, 'a')})", r_text]),
            f_expr=f_expr,
            point=point,
            a_true=a_true,
        )

    return [
        Frame(
            "applied-abs-times-linear-factor",
            _grid("p3d:app-lin", (2, -1, 3, -2, 1), (2, 3, -2, 4)),
            linear,
        ),
        Frame(
            "applied-abs-times-quadratic-factor",
            _grid("p3d:app-sq", (2, -1, 3, 1), (1, 2)),
            with_square,
        ),
        Frame(
            "applied-abs-times-linear-plus-smooth",
            _grid("p3d:app-smooth", (2, -2, 3, -1), (2, 3, -1), (1, 2, -1)),
            with_smooth_term,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 진단(diagnostic) — 절댓값이 있어도 매끄러운 꼴의 미분계수
# ──────────────────────────────────────────────────────────────────────────
def _smooth_coefficient(
    *, frame_id: str, f_text: str, f_expr: sympy.Expr, point: int, why: str
) -> DiffItem | None:
    """절댓값 항이 미분계수에 기여하지 않는(매끄러운) 함수의 f'(point)."""
    left, right = _branches(f_expr, point)
    if _constant_slope(left, right):
        return None
    lv, rv = _poly_value(left, point), _poly_value(right, point)
    if lv != rv:
        raise ValueError(f"{frame_id}: 꺾이는 함수다 — 좌 {lv} != 우 {rv}")
    return DiffItem(
        slot="diagnostic",
        frame_id=frame_id,
        question_text=f"함수 f(x) = {f_text}에 대하여 f'({point})의 값을 구하시오.",
        answer_text=str(rv),
        explanation=(
            f"{why} x > {point}에서 f(x) = {_render(right)}이므로 f'(x) = "
            f"{_render(sympy.diff(right, _X))}이고, x < {point}에서 f(x) = {_render(left)}이므로 "
            f"f'(x) = {_render(sympy.diff(left, _X))}이다. 두 쪽의 도함수가 x = {point}에서 모두 "
            f"{rv}이므로 x = {point}에서 미분가능하고 f'({point}) = {rv}이다."
        ),
        conditions=_at(right, point) + " = y",
        answer_map=(("y", str(rv)),),
        problem_type_code=_EVAL,
        answer_format=answer_format_for(str(rv)),
    )


def _diag_frames() -> list[Frame]:
    def product_form(p: tuple[object, ...]) -> DiffItem | None:
        (r, point), m = _rp(p[:2]), int(str(p[2]))
        f_expr = m * (_X - point) * sympy.Abs(_X - point) + _smooth_part(r)
        lead = f"({_shift(point)})|{_shift(point)}|"
        head = lead if m == 1 else (f"-{lead}" if m == -1 else f"{m}{lead}")
        return _smooth_coefficient(
            frame_id="diag-smooth-product-form",
            f_text=_join([head, render_poly(r)]),
            f_expr=f_expr,
            point=point,
            why=f"곱 꼴 항은 x = {point} 둘레에서 한쪽은 제곱, 다른 쪽은 제곱에 -1을 곱한 식이다.",
        )

    def abs_of_square(p: tuple[object, ...]) -> DiffItem | None:
        r, point = _rp(p[:2])
        f_expr = sympy.Abs((_X - point) ** 2) + _smooth_part(r)
        return _smooth_coefficient(
            frame_id="diag-abs-of-square",
            f_text=_join([f"|({_shift(point)})^2|", render_poly(r)]),
            f_expr=f_expr,
            point=point,
            why="제곱은 늘 0 이상이라 절댓값을 벗겨도 식이 같다.",
        )

    def abs_cubed(p: tuple[object, ...]) -> DiffItem | None:
        (r, point), m = _rp(p[:2]), int(str(p[2]))
        f_expr = m * sympy.Abs(_X - point) ** 3 + _smooth_part(r)
        lead = f"|{_shift(point)}|^3"
        head = lead if m == 1 else (f"-{lead}" if m == -1 else f"{m}{lead}")
        return _smooth_coefficient(
            frame_id="diag-abs-cubed",
            f_text=_join([head, render_poly(r)]),
            f_expr=f_expr,
            point=point,
            why=(
                f"|{_shift(point)}|^3의 차분몫은 크기가 |{_shift(point)}|^2이라 "
                "x가 가까워지면 0에 한없이 가까워진다."
            ),
        )

    base = _pq("p3d:diag")
    return [
        Frame("diag-smooth-product-form", _mix(base, (1, 2, -1)), product_form),
        Frame("diag-abs-of-square", _mix(base, (0,)), abs_of_square),
        Frame("diag-abs-cubed", _mix(base, (1, 2, -1)), abs_cubed),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 숙련도 확인(mastery_check) — 상수를 정한 뒤 다른 점의 미분계수
# ──────────────────────────────────────────────────────────────────────────
def _then_derivative(
    *,
    frame_id: str,
    f_text: str,
    f_expr: sympy.Expr,
    point: int,
    a_true: int,
    query: int,
) -> DiffItem:
    """미분가능 조건으로 a를 정한 뒤 x = query에서의 미분계수를 묻는다(두 단계)."""
    left, right = _branches(f_expr, point)
    r_expr, l_expr = sympy.diff(right, _X), sympy.diff(left, _X)
    r_at, l_at = _render(r_expr.subs(_X, point)), _render(l_expr.subs(_X, point))
    got = sympy.solve(sympy.Eq(r_expr.subs(_X, point), l_expr.subs(_X, point)), _A)
    if got != [a_true]:
        raise ValueError(f"{frame_id}: a 가 유일하지 않다 — {got} != {a_true}")
    branch = right if query > point else left
    solved = branch.subs(_A, a_true)
    value = _poly_value(solved, query)
    side = ">" if query > point else "<"
    return DiffItem(
        slot="mastery_check",
        frame_id=frame_id,
        question_text=(
            f"함수 f(x) = {f_text} (a는 상수)가 x = {point}에서 미분가능할 때, f'({query})의 값을 "
            "구하시오."
        ),
        answer_text=str(value),
        explanation=(
            f"x > {point}에서 f'(x) = {_render(r_expr)}, "
            f"x < {point}에서 f'(x) = {_render(l_expr)}이므로 "
            f"x = {point}에서의 우미분계수와 좌미분계수가 같아야 한다. "
            f"{r_at} = {l_at}에서 a = {a_true}이다. "
            f"x {side} {point}에서 f(x) = {_render(solved)}이므로 f'({query}) = {value}이다."
        ),
        conditions=_at(solved, query) + " = y",
        answer_map=(("y", str(value)),),
        problem_type_code=_SOLVE,
        answer_format=answer_format_for(str(value)),
    )


def _mastery_frames() -> list[Frame]:
    def linear(side: int) -> Frame:
        frame_id = (
            "mastery-constant-then-derivative-right"
            if side > 0
            else ("mastery-constant-then-derivative-left")
        )

        def build(p: tuple[object, ...]) -> DiffItem | None:
            point, c, gap, factor_first = (int(str(v)) for v in p)
            a_true = -c * point
            if a_true == 0:
                return None
            query = point + side * gap
            f_expr = sympy.Abs(_X - point) * (c * _X + _A)
            return _then_derivative(
                frame_id=frame_id,
                f_text=(
                    f"({_factor(c, 'a')})|{_shift(point)}|"
                    if factor_first
                    else f"|{_shift(point)}|({_factor(c, 'a')})"
                ),
                f_expr=f_expr,
                point=point,
                a_true=a_true,
                query=query,
            )

        return Frame(
            frame_id,
            _grid(f"p3d:mas-{side}", (2, -1, 3, -2, 1), (2, 3, -2), (1, 2, 3), (0, 1)),
            build,
        )

    def quadratic(p: tuple[object, ...]) -> DiffItem | None:
        point, m, gap = (int(str(v)) for v in p)
        a_true = -m * point * point
        query = point + gap
        f_expr = sympy.Abs(_X - point) * (m * _X**2 + _A)
        lead = "x^2" if m == 1 else f"{m}x^2"
        return _then_derivative(
            frame_id="mastery-constant-then-derivative-quadratic",
            f_text=f"|{_shift(point)}|({lead} + a)",
            f_expr=f_expr,
            point=point,
            a_true=a_true,
            query=query,
        )

    def with_smooth_term(p: tuple[object, ...]) -> DiffItem | None:
        point, c, r_c, gap, smooth_first = (int(str(v)) for v in p)
        a_true = -c * point
        if a_true == 0:
            return None
        query = point + gap
        if query == 0:  # 매끄러운 항 r·x^2 의 x = 0 미분계수가 0이라 지수 처리를 변별하지 못한다
            return None
        f_expr = sympy.Abs(_X - point) * (c * _X + _A) + r_c * _X**2
        r_text = "x^2" if r_c == 1 else ("-x^2" if r_c == -1 else f"{r_c}x^2")
        return _then_derivative(
            frame_id="mastery-constant-then-derivative-plus-smooth",
            f_text=_join(
                [r_text, f"|{_shift(point)}|({_factor(c, 'a')})"]
                if smooth_first
                else [f"|{_shift(point)}|({_factor(c, 'a')})", r_text]
            ),
            f_expr=f_expr,
            point=point,
            a_true=a_true,
            query=query,
        )

    return [
        linear(+1),
        linear(-1),
        Frame(
            "mastery-constant-then-derivative-plus-smooth",
            _grid("p3d:mas-smooth", (2, -2, 3, -1), (2, 3, -2), (2, -1, 3), (1, -2, 2), (0, 1)),
            with_smooth_term,
        ),
        Frame(
            "mastery-constant-then-derivative-quadratic",
            _grid("p3d:mas-sq", (2, -1, 3, 1), (1, 2), (1, 2)),
            quadratic,
        ),
    ]


_SLOT_FRAMES = {
    "representative": _rep_frames,
    "basic": _basic_frames,
    "applied": _applied_frames,
    "diagnostic": _diag_frames,
    "mastery_check": _mastery_frames,
}


class P3DiffDifferentiabilityGenerator(P3DiffSlotGenerator):
    """[12미적Ⅰ-02-02] 미분가능성과 연속성 — 빈 5칸 결정론 생성기."""

    standard_code: ClassVar[str] = "[12미적Ⅰ-02-02]"
    concept_src_id: ClassVar[str] = "H:12미적Ⅰ02-02"
    unit_code: ClassVar[str] = "P3-CALC1-DIFF-DIFFERENTIABILITY"
    slug_prefix: ClassVar[str] = "wm-p3-diff-differentiability"
    slots: ClassVar[tuple[SlotId, ...]] = (
        "representative",
        "basic",
        "applied",
        "diagnostic",
        "mastery_check",
    )
    slot_difficulty: ClassVar[dict[str, float]] = {
        "representative": 2.5,
        "basic": 2.0,
        "applied": 3.0,
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
