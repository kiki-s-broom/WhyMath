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

두 번째 생성기 — `P3DiffDifferentiabilityReachGenerator` (P3-65)
--------------------------------------------------------------
위 두 유형은 이 개념의 스킬(`deductive-reasoning`·`graph-reading`)에 닿지 않아,
개념의 Content 연결이 `conceptual_v0`의 24건(정답 0 하나)에만 걸려 있었다
(P3-55 판정 R1·R2). 이 모듈 아래쪽의 두 번째 생성기가 스킬에 닿는
`count-solutions`(미분가능하지 않은 점의 개수)·`verify-claim`(미분가능성 0/1)
문항을 **별도 은행**(`problem_bank_p3_differentiability_reach_v0`)에 만든다.
위에서 쓰지 않았던 0/1 판정형의 풀이 단계는 그 생성기가 식↔식 연쇄
('우미분계수 - 좌미분계수')로 직접 쓰고 기반이 검증한다
(`ReachDiffItem.explicit_steps`). 첫 생성기의 클래스·문항은 한 바이트도 바꾸지
않는다(승인 은행 `p3_fill_v0`의 감사 동결 사본 결속).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import ClassVar, Final

import sympy

from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.p3_diff_expr import Poly, render_poly
from whymath_backend.l3.equivalent.p3_diff_mean_value_theorem_skeleton_generator import (
    KindedDiffItem,
    with_item_kinds,
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

__all__ = [
    "P3DiffDifferentiabilityGenerator",
    "P3DiffDifferentiabilityReachGenerator",
    "ReachDiffItem",
]

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


# ══════════════════════════════════════════════════════════════════════════
# P3-65 — 개념 스킬에 닿는 유형(미분불가 점의 개수 · 미분가능성 참/거짓) 은행
# ══════════════════════════════════════════════════════════════════════════
# 위 생성기(P3-05)의 60건은 값 계산(`evaluate-expression`)·미지 상수(`solve-for-unknown`)라
# [12미적Ⅰ-02-02]의 개념 스킬(`deductive-reasoning`·`graph-reading`)에 닿지 않는다(P3-55 판정 ②).
# 아래 생성기는 동결 명세(`phase3_scope_v1.required_problem_types`)가 이미 허용하는 두 유형 —
# `count-solutions`(미분가능하지 않은 점의 개수)와 `verify-claim`(미분가능성의 참/거짓 0/1) — 의
# 문항을 **새 은행**(`problem_bank_p3_differentiability_reach_v0`)에 만든다. 유형은 문면 형태 그대로
# 단다: 개수를 묻는 문항은 count-solutions, '참이면 1, 거짓이면 0'·'미분가능하면 1'은 verify-claim.
#
# 정답의 단일 권위는 SymPy다 — 후보(절댓값 안의 식의 실근)마다 그 점의 양옆에서 절댓값을 벗긴 분기
# 다항식을 만들고, 두 분기의 도함수를 그 점에서 비교한다(좌·우미분계수). 수용 게이트 Tier1은 이와
# 독립인 경로(차분몫의 좌·우 극한 —
# `verify_nondifferentiable_point_count`·`verify_is_differentiable`)로
# 같은 답을 다시 계산한다.
#
# 변별력(P3-55 위험 R2 — 기존 24건은 정답이 늘 0인 같은 사실 하나였다):
# · 참/거짓 문항은 **같은 틀 안에서** 매개변수에 따라 정답이 0과 1로 갈린다(절댓값이 보이면 0이라는
#   규칙 하나로 풀리지 않는다).
# · 개수 문항은 '절댓값 안의 식이 0이 되는 점의 개수'(후보 수)와 '절댓값 항의 개수'로 센 답이 정답과
#   **다른** 매개변수만 쓴다 — 매끄러운 절댓값 꼴(`(x - p)|x - p|`·`|x - p|^3`·중근)이나 꺾임이
#   상쇄되는
#   항을 늘 하나 이상 넣는다(`_count_item`이 강제 — 어기면 그 매개변수를 건너뛴다).

_COUNT: Final = "ptype.count-solutions"
_CLAIM: Final = "ptype.verify-claim"
_KIND_COUNT: Final = "nondifferentiable_point_count"
_KIND_CLAIM: Final = "is_differentiable"
#: 분기를 고를 때 후보의 양옆 탐침 거리 — 후보가 정수라 다른 후보와 섞이지 않는다
#: (1보다 충분히 작다).
_EPS: Final = sympy.Rational(1, 1000)


@dataclass(frozen=True, slots=True)
class ReachDiffItem(KindedDiffItem):
    """개념형 판정 문항 — `KindedDiffItem` + 생성기가 직접 쓴 식↔식 풀이 연쇄(P3-65).

    참/거짓(0/1) 문항의 풀이 계산은 '우미분계수 - 좌미분계수'라는 식의 값이라 등식 연쇄로 쓰면 새
    변수가 필요하다. `explicit_steps`가 있으면 기반의 `steps_of`가 그 연쇄를 **검증해** 쓴다
    (`p3_diff_solution_steps.verified_expression_chain` — 전이 전건 correct가 아니면 빌드가 멈춘다).
    """

    explicit_steps: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class _Term:
    """함수의 한 항 — SymPy 식과 학생 표기.

    표기는 선두 부호를 포함한다(`_join`이 '+ -'를 만들지 않게 잇는다).
    """

    expr: sympy.Expr
    text: str


def _coef(k: int, body: str) -> str:
    """계수 표기 — 1이면 생략, -1이면 '-'만('1x'·'-1(…)' 표기를 만들지 않는다)."""
    if k == 1:
        return body
    if k == -1:
        return f"-{body}"
    return f"{k}{body}"


def _kink(k: int, a: int) -> _Term:
    """k|x - a| — x = a에서 꺾인다(k ≠ 0)."""
    return _Term(k * sympy.Abs(_X - a), _coef(k, f"|{_shift(a)}|"))


def _signed_square(m: int, a: int) -> _Term:
    """m(x - a)|x - a| — 절댓값이 있어도 x = a에서 미분가능하다(좌·우미분계수 모두 0)."""
    return _Term(m * (_X - a) * sympy.Abs(_X - a), _coef(m, f"({_shift(a)})|{_shift(a)}|"))


def _abs_cube(m: int, a: int) -> _Term:
    """m|x - a|^3 — x = a에서 미분가능하다."""
    return _Term(m * sympy.Abs(_X - a) ** 3, _coef(m, f"|{_shift(a)}|^3"))


def _times_shift(a: int, b: int) -> _Term:
    """|x - a|(x - b) — b ≠ a면 x = a에서 꺾인다(곱 꼴이지만 매끄러운 꼴이 아니다)."""
    return _Term(sympy.Abs(_X - a) * (_X - b), f"|{_shift(a)}|({_shift(b)})")


def _smooth(expr: sympy.Expr | None) -> list[_Term]:
    if expr is None or expr == 0:
        return []
    return [_Term(sympy.expand(expr), _render(expr))]


def _function(terms: list[_Term]) -> tuple[sympy.Expr, str]:
    return sympy.Add(*(t.expr for t in terms)), _join([t.text for t in terms])


def _abs_roots(f_expr: sympy.Expr) -> tuple[int, ...]:
    """후보 — 절댓값 안의 식의 실근(정수만 쓴다 · 정수가 아니면 ValueError — 틀 설계 결함)."""
    roots: set[int] = set()
    for term in f_expr.atoms(sympy.Abs):
        poly = sympy.Poly(term.args[0], _X)
        found = sympy.real_roots(poly)  # 중복도만큼 반복 · 실근 전부(근호식·CRootOf 포함)
        # 실근이 차수만큼 나오지 않으면(허근·놓친 근) 후보 목록을 확정할 수 없다 — 조용히 줄여 쓰지
        # 않고 생성을 거부한다(P3-65 리뷰 ⑥). 이 생성기의 절댓값 인자는 전부 정수 근으로
        # 인수분해된다.
        if len(found) != poly.degree():
            raise ValueError(f"실근이 차수만큼 나오지 않는 절댓값 인자: {term.args[0]} ({f_expr})")
        for root in found:
            if not root.is_integer:
                raise ValueError(f"정수가 아닌 후보: {root} ({f_expr})")
            roots.add(int(root))
    return tuple(sorted(roots))


def _slope_at(branch: sympy.Expr, point: int) -> int:
    """분기 다항식의 x = point 미분계수(다항식 미분 — `_poly_value`와 같은 값, 정수 계수 전용)."""
    return int(sympy.Poly(branch, _X).diff(_X).eval(point))


@dataclass(frozen=True, slots=True)
class _Side:
    """후보 한 점의 좌·우 분기와 그 점의 좌·우미분계수."""

    point: int
    left: sympy.Expr
    right: sympy.Expr
    left_value: int
    right_value: int

    @property
    def differentiable(self) -> bool:
        return self.left_value == self.right_value


def _sides(f_expr: sympy.Expr) -> tuple[_Side, ...]:
    """후보마다 양옆(±`_EPS`)에서 절댓값 안의 식의 부호로 |u| = ±u를 골라 분기 다항식을 만든다."""
    out: list[_Side] = []
    for point in _abs_roots(f_expr):

        def branch(side: int, at: int = point) -> sympy.Expr:
            probe = at + side * _EPS
            sub = {
                t: (t.args[0] if t.args[0].subs(_X, probe) > 0 else -t.args[0])
                for t in f_expr.atoms(sympy.Abs)
            }
            return sympy.expand(f_expr.xreplace(sub))

        left, right = branch(-1), branch(+1)
        out.append(_Side(point, left, right, _slope_at(left, point), _slope_at(right, point)))
    return tuple(out)


def _side_text(side: _Side) -> str:
    p = side.point
    return (
        f"x = {p} 가까이에서 x > {p}일 때 f(x) = {_render(side.right)}이므로 "
        f"f'(x) = {_render(sympy.diff(side.right, _X))}이고 우미분계수는 {side.right_value}이다. "
        f"x < {p}일 때 f(x) = {_render(side.left)}이므로 "
        f"f'(x) = {_render(sympy.diff(side.left, _X))}이고 좌미분계수는 {side.left_value}이다. "
        + (
            f"두 값이 같으므로 x = {p}에서 미분가능하다."
            if side.differentiable
            else f"두 값이 다르므로 x = {p}에서 미분가능하지 않다."
        )
    )


def _candidates_text(sides: tuple[_Side, ...]) -> str:
    listed = ", ".join(str(s.point) for s in sides)
    only = "뿐이고" if len(sides) == 1 else "이고"
    return (
        f"절댓값 안의 식이 0이 되는 x의 값은 {listed}{only}, 그 밖의 점 가까이에서는 절댓값 안의 "
        "식의 부호가 일정해 f(x)가 다항함수와 같으므로 미분가능하다. "
    )


def _jump_chain(side: _Side) -> tuple[str, ...]:
    """x = p에서 '우미분계수 - 좌미분계수'의 식↔식 연쇄(도함수 → 대입값 → 차)."""
    p = side.point
    return (
        f"(Derivative({side.right}, x) - Derivative({side.left}, x)).doit().subs(x, {p})",
        f"({side.right_value}) - ({side.left_value})",
        str(side.right_value - side.left_value),
    )


# ── 개수(count-solutions) ────────────────────────────────────────────────
_COUNT_STEMS: Final = (
    "함수 f(x) = {f}에 대하여 f(x)가 미분가능하지 않은 x의 값의 개수를 구하시오.",
    "함수 f(x) = {f}에 대하여 실수 전체의 집합에서 f(x)가 미분가능하지 않은 점의 개수를 구하시오.",
)


def _naive_counts(
    f_expr: sympy.Expr, terms: list[_Term], sides: tuple[_Side, ...]
) -> frozenset[int]:
    """좌·우미분계수를 비교하지 않는 셈법이 내는 값 — 정답이 이 중 하나면 그 매개변수를 쓰지 않는다.

    ① 후보 수(절댓값 안의 식이 0이 되는 점을 전부 미분불가로 셈 — 매끄러운 꼴을 놓친다).
    ② 절댓값 항의 수(절댓값 하나에 꺾임 하나).
    ③ 절댓값 안 다항식의 차수(절댓값이 하나일 때 '차수만큼 근 → 그만큼 꺾임').
    """
    naive = {len(sides), sum(1 for t in terms if t.expr.has(sympy.Abs))}
    inners = [t.args[0] for t in f_expr.atoms(sympy.Abs)]
    if len(inners) == 1:
        naive.add(int(sympy.degree(inners[0], _X)))
    return frozenset(naive)


def _count_item(*, slot: str, frame_id: str, terms: list[_Term], stem: int) -> ReachDiffItem | None:
    """미분가능하지 않은 점의 개수 — 후보 수·절댓값 항 수로 센 답과 다른 매개변수만 낸다."""
    f_expr, f_text = _function(terms)
    sides = _sides(f_expr)
    if not sides:
        return None
    answer = sum(1 for s in sides if not s.differentiable)
    if answer in _naive_counts(f_expr, terms, sides):
        return None  # 좌·우미분계수를 비교하지 않는 셈법으로도 같은 답 — 변별이 없다
    if _constant_slope(*(b for s in sides for b in (s.left, s.right))):
        return None  # 해설의 도함수 식이 x를 담지 못한다(E-derivative)
    kinks = [s.point for s in sides if not s.differentiable]
    conclusion = (
        f"따라서 미분가능하지 않은 x의 값은 {', '.join(map(str, kinks))}이고 "
        f"그 개수는 {answer}이다."
        if kinks
        else f"따라서 f(x)는 실수 전체의 집합에서 미분가능하고, 구하는 개수는 {answer}이다."
    )
    explanation = (
        _candidates_text(sides) + " ".join(_side_text(s) for s in sides) + " " + conclusion
    )
    candidates = sorted({t.args[0] for t in f_expr.atoms(sympy.Abs)}, key=sympy.default_sort_key)
    return ReachDiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=_COUNT_STEMS[stem].format(f=f_text),
        answer_text=str(answer),
        explanation=explanation,
        conditions=str(f_expr),
        answer_map=(),
        problem_type_code=_COUNT,
        answer_format=answer_format_for(str(answer)),
        # 풀이 단계 — 후보(절댓값 안의 식 = 0)의 근 목록. 개수는 그 후보마다 좌·우미분계수를 비교한
        # 결과라 식 연쇄로 표현되지 않는다(MVT 개수 문항과 같은 한계 — Tier1이 개수를 검산한다).
        solution_setup=f"{sympy.Mul(*candidates)} = 0",
        answer_kind=_KIND_COUNT,
    )


# ── 참/거짓(verify-claim · 0/1) ──────────────────────────────────────────
_POINT_STEMS: Final = (
    "함수 f(x) = {f}에 대하여 f(x)가 x = {p}에서 미분가능하면 1, 미분가능하지 않으면 0을 쓰시오.",
    "함수 f(x) = {f}에 대하여 x = {p}에서의 우미분계수와 좌미분계수가 같으면 1, 다르면 0을 쓰시오.",
)
#: 실수 전체에서의 판정 — 명제를 작은따옴표로 감싸면 '…다'가'가 프라임 조사 표기(`prime_josa`)로
#: 읽혀 기계 판정이 결함으로 센다(2026-10-26 실측 45건) — 따옴표 없이 쓴다.
_REAL_STEM: Final = (
    "함수 f(x) = {f}에 대하여 f(x)가 실수 전체의 집합에서 미분가능하면 1, 미분가능하지 않으면 0을 "
    "쓰시오."
)


def _point_claim_item(
    *, slot: str, frame_id: str, terms: list[_Term], point: int, stem: int
) -> ReachDiffItem | None:
    """x = point에서의 미분가능성 0/1 — 후보가 그 점 하나뿐인 함수만(Tier1은 ℝ 전체를 판정한다).

    후보가 하나면 '실수 전체에서 미분가능' ⟺ 'x = point에서 미분가능'이다(그 밖은 다항함수와 같다).
    그래서 검산 조건(`is_differentiable` — ℝ 전체)과 발문(한 점)이 같은 명제를 가리킨다.
    """
    f_expr, f_text = _function(terms)
    sides = _sides(f_expr)
    if [s.point for s in sides] != [point]:
        return None
    (side,) = sides
    if _constant_slope(side.left, side.right):
        return None
    answer = 1 if side.differentiable else 0
    tail = f" 따라서 답은 {answer}이다."
    return ReachDiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=_POINT_STEMS[stem].format(f=f_text, p=point),
        answer_text=str(answer),
        explanation=_side_text(side) + tail,
        conditions=str(f_expr),
        answer_map=(),
        problem_type_code=_CLAIM,
        answer_format=answer_format_for(str(answer)),
        answer_kind=_KIND_CLAIM,
        explicit_steps=_jump_chain(side),
    )


def _real_claim_item(*, slot: str, frame_id: str, terms: list[_Term]) -> ReachDiffItem | None:
    """f(x)가 실수 전체의 집합에서 미분가능한가의 0/1 — 후보 전부를 판정한다."""
    f_expr, f_text = _function(terms)
    sides = _sides(f_expr)
    if not sides or _constant_slope(*(b for s in sides for b in (s.left, s.right))):
        return None
    answer = 1 if all(s.differentiable for s in sides) else 0
    first_kink = next((s for s in sides if not s.differentiable), None)
    conclusion = (
        " 모든 후보에서 미분가능하므로 f(x)는 실수 전체의 집합에서 미분가능하다. 따라서 답은 1이다."
        if first_kink is None
        else (
            f" x = {first_kink.point}에서 미분가능하지 않으므로 f(x)는 실수 전체의 집합에서 "
            "미분가능하지 않다. 따라서 답은 0이다."
        )
    )
    shown = (first_kink,) if first_kink is not None else sides
    return ReachDiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=_REAL_STEM.format(f=f_text),
        answer_text=str(answer),
        explanation=_candidates_text(sides) + " ".join(_side_text(s) for s in shown) + conclusion,
        conditions=str(f_expr),
        answer_map=(),
        problem_type_code=_CLAIM,
        answer_format=answer_format_for(str(answer)),
        answer_kind=_KIND_CLAIM,
        explicit_steps=_jump_chain(first_kink if first_kink is not None else sides[0]),
    )


# ── 매개변수 풀 ──────────────────────────────────────────────────────────
_PTS: Final = (-3, -2, -1, 1, 2, 3)
#: 덧붙이는 매끄러운 항(없음 포함) — 분기 도함수가 x를 담게 하고 문면을 다양하게 한다.
_R_POOL: Final[tuple[sympy.Expr | None, ...]] = (
    None,
    _X**2,
    -(_X**2) + 3 * _X,
    2 * _X**2 - 1,
    _X**3 - 2 * _X,
    -2 * _X**2 + 5,
)


def _cartesian(seed: str, *axes: tuple[object, ...]) -> tuple[tuple[object, ...], ...]:
    """축들의 곱집합을 시드 순서로 섞는다(`_grid`와 같은 절차 — 축 값이 정수만이 아니다)."""
    combos: list[tuple[object, ...]] = [()]
    for axis in axes:
        combos = [(*c, v) for c in combos for v in axis]
    return tuple(seeded_order(seed, combos))


def _sampled(seed: str, count: int, *axes: tuple[object, ...]) -> tuple[tuple[object, ...], ...]:
    """곱집합이 너무 큰 축(항 4개 × 종류·계수)에서 시드 고정 표본 `count`개 — 결정론·중복 제거."""
    rng = random.Random(seed)
    seen: set[tuple[object, ...]] = set()
    out: list[tuple[object, ...]] = []
    for _ in range(count * 4):
        combo = tuple(rng.choice(axis) for axis in axes)
        if combo not in seen:
            seen.add(combo)
            out.append(combo)
        if len(out) >= count:
            break
    return tuple(out)


def _ints(p: tuple[object, ...]) -> list[int]:
    return [int(str(v)) for v in p]


def _r_at(index: object) -> sympy.Expr | None:
    return _R_POOL[int(str(index)) % len(_R_POOL)]


# ── 대표(representative) — 개수: 꺾이는 항과 매끄러운 절댓값 항의 합 ───────
_TERM_KINDS: Final = ("kink", "square", "cube", "shifted")


def _term_of(kind: str, a: int, coef: int, other: int) -> _Term | None:
    if kind == "kink":
        return _kink(coef, a)
    if kind == "square":
        return _signed_square(coef, a)
    if kind == "cube":
        return _abs_cube(coef, a)
    if other == a:
        return None  # |x - a|(x - a)는 square 와 같은 꼴 — 'shifted'는 꺾이는 곱 꼴만 쓴다
    return _times_shift(a, other)


def _reach_rep_frames() -> list[Frame]:
    def sum_of_terms(n_terms: int, frame_id: str, stem: int) -> Frame:
        def build(p: tuple[object, ...]) -> DiffItem | None:
            points = _ints(p[0:n_terms])
            kinds = [str(k) for k in p[n_terms : 2 * n_terms]]
            coefs = _ints(p[2 * n_terms : 3 * n_terms])
            if len(set(points)) != n_terms:
                return None
            terms: list[_Term] = []
            for i, (a, kind, c) in enumerate(zip(points, kinds, coefs, strict=True)):
                other = points[(i + 1) % n_terms]
                term = _term_of(kind, a, c, other)
                if term is None:
                    return None
                terms.append(term)
            return _count_item(slot="representative", frame_id=frame_id, terms=terms, stem=stem)

        axes: list[tuple[object, ...]] = [_PTS] * n_terms
        axes += [_TERM_KINDS] * n_terms
        axes += [(1, 2, -1)] * n_terms
        return Frame(frame_id, _sampled(f"p365:rep:{frame_id}", 3000, *axes), build)

    return [
        sum_of_terms(2, "reach-rep-two-terms", 0),
        sum_of_terms(3, "reach-rep-three-terms", 1),
        sum_of_terms(3, "reach-rep-three-terms-x", 0),
        sum_of_terms(4, "reach-rep-four-terms", 1),
    ]


# ── 응용(applied) — 개수: 다항식의 절댓값(중근은 매끄럽다) ─────────────────
def _factor_text(a: int, m: int) -> str:
    """인수 표기 — `(x - a)`·`(x - a)^2`, a = 0이면 괄호 없이 `x`·`x^2`.

    `(x)` 표기를 만들지 않는다(P3-65 리뷰 ③).
    """
    if a == 0:
        return "x" if m == 1 else f"x^{m}"
    return f"({_shift(a)})" if m == 1 else f"({_shift(a)})^{m}"


def _reach_applied_frames() -> list[Frame]:
    def factored(p: tuple[object, ...]) -> DiffItem | None:
        a, b, c, d, ma, mb, mc, md, k = _ints(p)
        roots = [(a, ma), (b, mb)] + ([(c, mc)] if mc else []) + ([(d, md)] if mc and md else [])
        if len({r for r, _ in roots}) != len(roots) or all(m == 2 for _, m in roots):
            return None
        inner = sympy.Mul(*((_X - r) ** m for r, m in roots))
        # x 인수는 맨 앞에 쓴다('(x - 1)x'가 아니라 'x(x - 1)') — 식은 그대로, 표기 순서만.
        text = "".join(_factor_text(r, m) for r, m in sorted(roots, key=lambda rm: rm[0] != 0))
        terms = [_Term(k * sympy.Abs(inner), _coef(k, f"|{text}|"))]
        return _count_item(slot="applied", frame_id="reach-app-abs-factored", terms=terms, stem=0)

    def expanded(p: tuple[object, ...]) -> DiffItem | None:
        a, b, c, ma, mb, mc, stem = _ints(p)
        roots = [(a, ma), (b, mb)] + ([(c, mc)] if mc else [])
        if len({r for r, _ in roots}) != len(roots) or all(m == 2 for _, m in roots):
            return None
        inner = sympy.expand(sympy.Mul(*((_X - r) ** m for r, m in roots)))
        if max(abs(int(v)) for v in sympy.Poly(inner, _X).all_coeffs()) > 40:
            return None  # 학생 손계산으로 인수분해할 크기만
        terms = [_Term(sympy.Abs(inner), f"|{_render(inner)}|")]
        return _count_item(
            slot="applied", frame_id="reach-app-abs-expanded", terms=terms, stem=stem
        )

    def quadratic_with_smooth(p: tuple[object, ...]) -> DiffItem | None:
        # |x^2 - a^2|는 절댓값 하나에 꺾임 둘이고 매끄러운 항은 절댓값 하나에 꺾임 0이라, 매끄러운
        # 항이 하나뿐이면 '절댓값 항 수'가 늘 정답과 같다 — 매끄러운 항을 둘 둔다(c, d).
        a, c, d, e, m, kind, k = _ints(p)
        if len({a, -a, c, d, e}) != 5:
            return None
        first = _signed_square(m, c) if kind == 0 else _abs_cube(m, c)
        second = _abs_cube(-m, d) if kind == 0 else _signed_square(-m, d)
        terms = [
            _Term(sympy.Abs(_X**2 - a * a), f"|x^2 - {a * a}|"),
            first,
            second,
            *([_kink(k, e)] if k else []),
        ]
        return _count_item(
            slot="applied", frame_id="reach-app-difference-of-squares", terms=terms, stem=1
        )

    return [
        Frame(
            "reach-app-abs-factored",
            _cartesian(
                "p365:app:fac",
                _PTS,
                _PTS,
                _PTS,
                (0, *_PTS),
                (1, 2),
                (1, 2),
                (0, 1, 2),
                (0, 1, 2),
                (1, 2),
            ),
            factored,
        ),
        Frame(
            "reach-app-abs-expanded",
            _cartesian("p365:app:exp", _PTS, _PTS, (0, *_PTS), (1, 2), (1, 2), (0, 1, 2), (0, 1)),
            expanded,
        ),
        Frame(
            "reach-app-difference-of-squares",
            _cartesian(
                "p365:app:sq", (1, 2, 3), _PTS, _PTS, (*_PTS, 4), (1, -1, 2), (0, 1), (0, 1, -2)
            ),
            quadratic_with_smooth,
        ),
    ]


# ── 기본(basic) — 참/거짓: 한 점의 미분가능성 ─────────────────────────────
def _linear_text(c: int, d: int) -> str:
    return _render(c * _X + d)


def _reach_basic_frames() -> list[Frame]:
    def times_linear(p: tuple[object, ...]) -> DiffItem | None:
        point, c, shift, order, r, stem = _ints(p)
        d = -c * point + shift  # shift = 0이면 cx + d = c(x - point) → 매끄럽다(답 1)
        abs_text, lin_text = f"|{_shift(point)}|", f"({_linear_text(c, d)})"
        body = abs_text + lin_text if order == 0 else lin_text + abs_text
        if d == 0:  # 일차식이 cx 뿐이면 괄호 없이 앞에 쓴다('|x - 1|(x)'가 아니라 'x|x - 1|')
            body = _coef(c, f"x{abs_text}")
        terms = [_Term(sympy.Abs(_X - point) * (c * _X + d), body), *_smooth(_r_at(r))]
        return _point_claim_item(
            slot="basic",
            frame_id="reach-basic-abs-times-linear",
            terms=terms,
            point=point,
            stem=stem,
        )

    def cube_plus_kink(p: tuple[object, ...]) -> DiffItem | None:
        point, m, k, r, stem = _ints(p)
        terms = [_abs_cube(m, point), *([_kink(k, point)] if k else []), *_smooth(_r_at(r))]
        return _point_claim_item(
            slot="basic",
            frame_id="reach-basic-cube-plus-kink",
            terms=terms,
            point=point,
            stem=stem,
        )

    return [
        Frame(
            "reach-basic-abs-times-linear",
            _cartesian(
                "p365:basic:lin",
                _PTS,
                (1, 2, -1, 3),
                (0, 0, 1, -2),
                (0, 1),
                (0, 1, 2, 3, 4, 5),
                (0, 1),
            ),
            times_linear,
        ),
        Frame(
            "reach-basic-cube-plus-kink",
            _cartesian(
                "p365:basic:cube", _PTS, (1, 2, -1), (0, 0, 1, -2, 3), (1, 2, 3, 4, 5), (0, 1)
            ),
            cube_plus_kink,
        ),
    ]


# ── 진단(diagnostic) — 참/거짓: 곱 꼴의 매끄러움 판정 ──────────────────────
def _reach_diag_frames() -> list[Frame]:
    def times_square(p: tuple[object, ...]) -> DiffItem | None:
        point, gap, order, r, stem = _ints(p)
        q = point + gap  # gap = 0이면 |x - p|(x - p)^2 = |x - p|^3 → 매끄럽다
        abs_text, sq_text = f"|{_shift(point)}|", f"({_shift(q)})^2"
        body = abs_text + sq_text if order == 0 else sq_text + abs_text
        if q == 0:  # '(x)^2' 표기를 만들지 않는다 — 'x^2|x - p|'
            body = f"x^2{abs_text}"
        terms = [_Term(sympy.Abs(_X - point) * (_X - q) ** 2, body), *_smooth(_r_at(r))]
        if stem == 2:
            return _real_claim_item(
                slot="diagnostic", frame_id="reach-diag-times-square", terms=terms
            )
        return _point_claim_item(
            slot="diagnostic",
            frame_id="reach-diag-times-square",
            terms=terms,
            point=point,
            stem=stem,
        )

    def times_quadratic(p: tuple[object, ...]) -> DiffItem | None:
        point, offset, order, r, stem = _ints(p)
        big_q = point * point + offset  # offset = 0이면 x^2 - Q 가 x = p에서 0 → 매끄럽다
        if big_q <= 0:
            return None
        abs_text, q_text = f"|{_shift(point)}|", f"(x^2 - {big_q})"
        body = abs_text + q_text if order == 0 else q_text + abs_text
        terms = [_Term(sympy.Abs(_X - point) * (_X**2 - big_q), body), *_smooth(_r_at(r))]
        if stem == 2:
            return _real_claim_item(
                slot="diagnostic", frame_id="reach-diag-times-quadratic", terms=terms
            )
        return _point_claim_item(
            slot="diagnostic",
            frame_id="reach-diag-times-quadratic",
            terms=terms,
            point=point,
            stem=stem,
        )

    return [
        Frame(
            "reach-diag-times-square",
            _cartesian(
                "p365:diag:sq", _PTS, (0, 0, 1, -1, 2), (0, 1), (0, 1, 2, 3, 4, 5), (0, 1, 2)
            ),
            times_square,
        ),
        Frame(
            "reach-diag-times-quadratic",
            _cartesian(
                "p365:diag:quad", _PTS, (0, 0, 1, -2, 3), (0, 1), (0, 1, 2, 3, 4, 5), (0, 1, 2)
            ),
            times_quadratic,
        ),
    ]


# ── 숙련도 확인(mastery_check) — 꺾임이 상쇄되는 합(개수·참/거짓) ──────────
def _cancel_terms(a: int, b: int, m: int, n: int) -> list[_Term] | None:
    """|(x - a)(x - b)| + m(x - b)|x - a| + n(x - a)|x - b| — 두 후보 각각에서 꺾임이 상쇄될 수
    있다.

    x = a 가까이에서 |(x - a)(x - b)| = sgn(a - b)(x - b)|x - a|라 m = -sgn(a - b)면 x = a의 꺾임이
    사라진다(x = b도 같다). 절댓값 안의 이차식은 전개해 보인다(인수분해가 첫 단계).
    """
    if a == b or (m == 0 and n == 0):
        return None
    inner = sympy.expand((_X - a) * (_X - b))
    terms = [_Term(sympy.Abs(inner), f"|{_render(inner)}|")]
    if m:
        terms.append(
            _Term(m * (_X - b) * sympy.Abs(_X - a), _coef(m, f"({_shift(b)})|{_shift(a)}|"))
        )
    if n:
        terms.append(
            _Term(n * (_X - a) * sympy.Abs(_X - b), _coef(n, f"({_shift(a)})|{_shift(b)}|"))
        )
    return terms


def _reach_mastery_frames() -> list[Frame]:
    def cancel_count(p: tuple[object, ...]) -> DiffItem | None:
        a, b, m, n, stem = _ints(p)
        terms = _cancel_terms(a, b, m, n)
        if terms is None:
            return None
        return _count_item(
            slot="mastery_check", frame_id="reach-mastery-cancel-count", terms=terms, stem=stem
        )

    def cancel_claim(p: tuple[object, ...]) -> DiffItem | None:
        a, b, flip_m, flip_n = _ints(p)
        sign = 1 if a > b else -1
        # 상쇄 계수(-sgn)에서 flip만큼 비켜 둔다 — 둘 다 0이면 참(답 1), 하나라도 아니면 거짓(답 0).
        m, n = -sign + flip_m, sign + flip_n
        terms = _cancel_terms(a, b, m, n)
        if terms is None:
            return None
        return _real_claim_item(
            slot="mastery_check", frame_id="reach-mastery-cancel-claim", terms=terms
        )

    def squares_plus_kink(p: tuple[object, ...]) -> DiffItem | None:
        a, c, d, e, m, k = _ints(p)
        if len({a, -a, c, d, e}) != 5:
            return None
        terms = [
            _Term(sympy.Abs(_X**2 - a * a), f"|x^2 - {a * a}|"),
            _abs_cube(m, c),
            *([_kink(k, e)] if k else []),
            _signed_square(1 if m < 0 else -1, d),
        ]
        return _count_item(
            slot="mastery_check", frame_id="reach-mastery-squares-plus-kink", terms=terms, stem=0
        )

    return [
        Frame(
            "reach-mastery-cancel-count",
            _cartesian("p365:mas:cc", _PTS, _PTS, (0, 1, -1, 2, -2), (0, 1, -1, 2, -2), (0, 1)),
            cancel_count,
        ),
        Frame(
            "reach-mastery-cancel-claim",
            _cartesian("p365:mas:cl", _PTS, _PTS, (0, 0, 1, -2), (0, 0, -1, 2)),
            cancel_claim,
        ),
        Frame(
            "reach-mastery-squares-plus-kink",
            _cartesian("p365:mas:sk", (1, 2, 3), _PTS, _PTS, (*_PTS, 4), (1, -1, 2), (0, 1, 2, -1)),
            squares_plus_kink,
        ),
    ]


_REACH_SLOT_FRAMES = {
    "representative": _reach_rep_frames,
    "basic": _reach_basic_frames,
    "applied": _reach_applied_frames,
    "diagnostic": _reach_diag_frames,
    "mastery_check": _reach_mastery_frames,
}


class P3DiffDifferentiabilityReachGenerator(P3DiffSlotGenerator):
    """[12미적Ⅰ-02-02] 개념 스킬 도달 은행(P3-65) — 개수(count-solutions)·참/거짓(verify-claim).

    기존 [12미적Ⅰ-02-02] 생성기(`P3DiffDifferentiabilityGenerator` — 승인 은행 `p3_fill_v0`의
    60건)와 **다른 클래스**다: 그 생성기의 문항 바이트는 감사 동결 사본과 결속돼 있어 한 글자도
    바꾸지 않는다.
    단위 코드도 따로 둔다(감사 기계 판정 `p3_audit_qualification`이 단위 코드로 생성기를 찾는다).
    """

    standard_code: ClassVar[str] = "[12미적Ⅰ-02-02]"
    concept_src_id: ClassVar[str] = "H:12미적Ⅰ02-02"
    unit_code: ClassVar[str] = "P3-CALC1-DIFF-DIFFERENTIABILITY-REACH"
    slug_prefix: ClassVar[str] = "wm-p3-diff-diffreach"
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
        "diagnostic": 3.0,
        "mastery_check": 3.5,
    }
    slot_count: ClassVar[int] = 60

    @classmethod
    def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
        return round_robin_items(
            _REACH_SLOT_FRAMES[slot](),
            cls.slot_count,
            claimed=claimed,
            standard_code=cls.standard_code,
        )

    def _assemble(self, spec: EquivalenceSpec, item: DiffItem) -> CandidateProblem:
        """기반 후보에 개념형 검증 종류(`answer_kind`)를 얹는다(기반 `_assemble`은 싣지 않는다)."""
        return with_item_kinds(super()._assemble(spec, item), item)
