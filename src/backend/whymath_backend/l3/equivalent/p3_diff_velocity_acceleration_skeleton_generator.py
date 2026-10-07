"""[12미적Ⅰ-02-10] 속도와 가속도 결정론 문항 생성기 — P3-03(결정론·LLM 0).

개념: `H:12미적Ⅰ02-10`(`math.calculus.sokdowa-gasokdo`). 수직선 위를 움직이는 점의 위치 x(t)가
t에 대한 다항함수일 때 속도 v(t) = x'(t), 가속도 a(t) = v'(t) = x''(t)를 구하고, 속도·가속도가
0이 되는 시각·운동 방향이 바뀌는 시각처럼 수치로 답하는 문항을 만든다.

범위(이 개념에 한정): 다항 위치함수의 속도·가속도·방향 전환. **적분으로 위치·이동거리를 구하는
일은 다루지 않는다**(속도→위치는 적분 단원). 평균속도는 두 시각의 위치 차로 묻는 단순 계산만 둔다.
순수 '위치의 변화량'(함숫값의 차) 문항은 미분이 필요 없어 속도·가속도 개념이 아니므로 뺐다(감사
bad_tag 교정 — 문항이 실제로 묻는 개념과 PRIMARY 태그를 일치시킨다).
함수식(속도 함수)을 답으로 하는 문항은 만들지 않는다 — 채점 계약상 스칼라 단일 미지수만이라 속도·
가속도의 *값*·시각·상수로 묻는다.

검산 재료 형식(Tier1)
---------------------
  · 속도 `Derivative(F, t).doit().subs(t, 시각)`, 가속도 `Derivative(F, t, t).doit().subs(...)`
    — 미분 평가를 조건당 1회·맨몸으로 쓴다.
  · 속도+가속도처럼 두 값을 묶는 문항은 `Derivative(F + Derivative(F, t), t)`(= x' + x'')처럼
    *합쳐 한 번에* 미분한다(미분 평가가 든 변을 다른 연산과 섞지 못하는 Tier1 제약 — 2026-10-06
    형제 생성기 실측).
  · 속도의 부호가 중요한 문항은 `Abs(...)`(속력)를 그대로 쓴다.
  · 평균속도처럼 미분이 없는 문항은 위치 다항식에 시각을 *문자열로 대입*한
    산술식으로 검산한다(생성기의 정수 계산과 독립인 SymPy 평가 경로).
  · 미분 결과를 거쳐 *두 번째 값*을 묻는 문항(방향 전환 시각의 위치 등)은 첫 미지수(시각)를
    생성기가 SymPy로 푼 값으로 조건에 대입한다(`_unique_root`가 유일해를 확인).

문제유형 정직성
--------------
이 개념의 명세 스킬(`equation-rearrangement`·`word-problem-modeling`)과 겹치는 필수 유형은
`ptype.solve-for-unknown`(equation-rearrangement) 하나뿐이다. `word-problem-modeling`을 가진
문제유형(모델링 계열)은 명세 필수 5종에 없고, 이 개념의 값 계산 문항은
`ptype.evaluate-expression`으로 정직하게 달아 스킬 연결로 세어지지 않는다. 연결 문항은
*시각·상수를 실제로 구하는* 응용·진단·숙련도·오개념 유발(solve형) 틀에서 나온다.
거짓 유형으로 맞추지 않는다.

오개념: 핵심 오개념 M0678(속도의 부호를 무시하고 속력으로만 본다)에는 *승인된 kebab이 없다*
(MISC-40 판정: 문항 맥락 종속형이라 의도적 미승격). 신규 id를 만들지 않으므로 오개념 유발 슬롯은
속도·가속도를 구하는 *미분 단계*에서 실제로 나오는 기존 kebab `power-rule-step-omitted`로 오답
선지를 연결한다 — M0671(`-02-03` 소속)로 닿으며 **M0678에는 닿지 않는다**(보고 사항). 속도가 음수인
문항에서는 속력(|v|)을 *미매핑 필러 선지*로 두어 M0678의 증상을 선지에는 담되 오개념 연결은 걸지
않는다.
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
    render_factored,
    render_poly,
    render_sum,
    render_surd,
    with_eul_reul,
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
from whymath_backend.schema.enums import AnswerFormat

__all__ = ["P3DiffVelocityAccelerationGenerator"]

_KEBAB: Final = "power-rule-step-omitted"
_EVAL: Final = "ptype.evaluate-expression"
_SOLVE: Final = "ptype.solve-for-unknown"
_T = sympy.Symbol("t")
_V: Final = "t"


# ──────────────────────────────────────────────────────────────────────────
# 공용 도구
# ──────────────────────────────────────────────────────────────────────────
def _fmt(value: object) -> AnswerFormat:
    """정답 형식 — 기반의 단일 규칙(`answer_format_for`)을 따른다."""
    return answer_format_for(str(value))


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


def _rt(f: Poly) -> str:
    """위치 다항식 표기(변수 t)."""
    return render_poly(f, _V)


def _st(f: Poly) -> str:
    """위치 다항식의 SymPy 표기(변수 t)."""
    return poly_to_sympy_str(f, _V)


def _vel(f: Poly) -> Poly:
    return derivative_of(f, _V)


def _acc(f: Poly) -> Poly:
    return derivative_of(_vel(f), _V)


def _v_at(f: Poly, t: int) -> int:
    return eval_at(_vel(f), t, _V)


def _a_at(f: Poly, t: int) -> int:
    return eval_at(_acc(f), t, _V)


def _x_at(f: Poly, t: int) -> int:
    return eval_at(f, t, _V)


def _dv(f: Poly, point: str) -> str:
    """속도 평가 1회 — `Derivative(F, t).doit().subs(t, 시각)`."""
    return f"Derivative({_st(f)}, t).doit().subs(t, {point})"


def _da(f: Poly, point: str) -> str:
    """가속도 평가 1회 — `Derivative(F, t, t).doit().subs(t, 시각)`."""
    return f"Derivative({_st(f)}, t, t).doit().subs(t, {point})"


def _at(f: Poly, t: int) -> str:
    """위치 다항식에 시각을 *문자열로 대입*한 산술식 — 미분 없는 검산용(독립 SymPy 평가)."""
    return f"({poly_to_sympy_str(f, f'({t})')})"


def _minus(left: int, right: int) -> str:
    """'a - b' — b가 음수이면 '+ |b|'로 풀어 이중 부호를 피한다."""
    return f"{left} - {right}" if right >= 0 else f"{left} + {-right}"


def _shift(f: Poly, delta: int) -> Poly:
    expr = sympy.expand(poly_to_sympy(f, _V).subs(_T, _T + delta))
    return poly_from_sympy(expr, _V)


def _v_plus_a_setup(f: Poly, t: int) -> str:
    """풀이 단계 출발식 v(t) + a(t) = y — 속도·가속도를 따로 미분한다(해설과 같은 대상)."""
    return f"(Derivative({_st(f)}, t) + Derivative({_st(f)}, t, 2)).doit().subs(t, {t}) = y"


def _k_affine(base: Poly, t: int) -> str:
    """v(t) = base'(t) + 2kt를 t에 대입한 k의 일차식('6k + 51') — 해설의 방정식 단계."""
    return render_poly(((1, 2 * t), (0, eval_at(_vel(base), t, _V))), _PARAM)


#: 오개념 유발 해설의 함정 문장 — 오답 선지가 나오는 경로(power-rule-step-omitted)를 짚는다.
_POWER_TRAP: Final = (
    " 위치를 미분할 때 지수를 앞으로 내리는 단계나 지수를 1 줄이는 단계를 빠뜨리면 다른 값이 "
    "나온다."
)


def _sign_change_text(r1: int, r2: int) -> str:
    """방향 전환의 근거 — v = 0인 두 시각의 좌우에서 속도의 부호가 바뀐다(3차 감사: 부호 판정 누락).

    v(t) = 3·lead·(t - r1)(t - r2)는 단순근 두 개라 각 근의 좌우에서 부호가 바뀐다.
    """
    return (
        f"v(t) = 0인 시각 {r1}, {r2}의 좌우에서 속도의 부호가 각각 바뀌어 점 P는 두 시각 모두에서 "
        "운동 방향을 바꾼다. 따라서"
    )


def _intro(f: Poly) -> str:
    return f"수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = {_rt(f)}일 때,"


def _real_roots(expr: sympy.Expr, symbol: sympy.Symbol) -> list[sympy.Expr]:
    return [r for r in sympy.solve(expr, symbol) if r.is_real]


def _unique_root(
    expr: sympy.Expr, symbol: sympy.Symbol, guard: Callable[[sympy.Expr], bool] | None = None
) -> int | None:
    """보호 조건을 통과하는 실근이 정수 1개뿐일 때 그 값, 아니면 None(애매한 문항은 버린다)."""
    passed = [r for r in _real_roots(expr, symbol) if guard is None or guard(r)]
    if len(passed) != 1 or not passed[0].is_integer:
        return None
    return int(passed[0])


def _vel_expr(f: Poly, symbol: sympy.Symbol) -> sympy.Expr:
    return cast(sympy.Expr, sympy.diff(poly_to_sympy(f, _V), _T).subs(_T, symbol))


def _acc_expr(f: Poly, symbol: sympy.Symbol) -> sympy.Expr:
    return cast(sympy.Expr, sympy.diff(poly_to_sympy(f, _V), _T, 2).subs(_T, symbol))


#: 미지 계수 기호 — 점 P와 상수 p가 한 문항에 함께 나오면 대소문자만 다른 두 기호가 혼동된다
#: (2차 감사 결함). 이 개념의 미지 계수는 k로 쓴다.
_PARAM: Final = "k"


def _render_with_param(base: Poly, exp: int, coef: int = 1) -> tuple[str, str]:
    """base + coef·k·t^exp — (사람이 읽는 표기, SymPy 표기). base에 t^exp 항이 없어야 한다."""
    terms: list[tuple[int, int | None]] = [(e, c) for e, c in base]
    terms.append((exp, None))
    terms.sort(key=lambda term: term[0], reverse=True)
    human: list[str] = []
    symbolic: list[str] = []
    for index, (e, c) in enumerate(terms):
        if c is None:
            lead = "" if coef == 1 else str(coef)
            s_lead = "" if coef == 1 else f"{coef}*"
            h_body = (
                f"{lead}{_PARAM}t^{e}"
                if e > 1
                else (f"{lead}{_PARAM}t" if e == 1 else f"{lead}{_PARAM}")
            )
            s_body = (
                f"{s_lead}{_PARAM}*t**{e}"
                if e > 1
                else (f"{s_lead}{_PARAM}*t" if e == 1 else f"{s_lead}{_PARAM}")
            )
            sign = "+"
        else:
            magnitude = abs(c)
            if e == 0:
                h_body = s_body = str(magnitude)
            else:
                v_h = "t" if e == 1 else f"t^{e}"
                v_s = "t" if e == 1 else f"t**{e}"
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


def _quad_pool() -> tuple[object, ...]:
    return tuple(
        _poly({2: lead, 1: b, 0: c})
        for lead in (1, 2, -1, -2, 3)
        for b in range(-8, 9)
        for c in (-4, -2, 0, 1, 3, 5)
    )


def _cubic_pool() -> tuple[object, ...]:
    return tuple(
        _poly({3: lead, 2: b, 1: c, 0: d})
        for lead in (1, 2, -1)
        for b in range(-6, 7)
        for c in range(-6, 7)
        for d in (-3, 0, 2, 4)
    )


def _stop_quad_pool() -> tuple[object, ...]:
    """v(t) = 2A(t - r) — 속도가 0이 되는 시각 r이 양의 정수 1개인 이차 위치함수."""
    return tuple(
        _poly({2: lead, 1: -2 * lead * r, 0: c})
        for lead in (1, 2, -1, 3)
        for r in (1, 2, 3, 4, 5, 6)
        for c in (-3, 0, 2, 5)
    )


def _two_stop_cubic_pool() -> tuple[tuple[Poly, int, int], ...]:
    """v(t) = 3A(t - r1)(t - r2) (0 < r1 < r2) — 방향이 두 번 바뀌는 삼차 위치함수와 (r1, r2)."""
    out: list[tuple[Poly, int, int]] = []
    for lead in (2, 4, -2, 1, -1, 3):
        for r1 in (1, 2, 3):
            for r2 in (r1 + 1, r1 + 2, r1 + 3, r1 + 4):
                b3 = 3 * lead * (r1 + r2)
                if b3 % 2:
                    continue
                for d in (0, 2, -3, 5):
                    f = _poly({3: lead, 2: -(b3 // 2), 1: 3 * lead * r1 * r2, 0: d})
                    out.append((f, r1, r2))
    return tuple(out)


_TIMES: Final[tuple[object, ...]] = (1, 2, 3, 4, 5)
_TIMES0: Final[tuple[object, ...]] = (0, 1, 2, 3, 4, 5)


def _value_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    value: int,
    explanation: str,
    conditions: str,
    ptype: str = _EVAL,
    setup: str | None = None,
) -> DiffItem:
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(value),
        explanation=explanation,
        conditions=conditions,
        answer_map=(("y", str(value)),),
        problem_type_code=ptype,
        answer_format=_fmt(value),
        solution_setup=setup,
    )


def _velocity_item(slot: str, frame_id: str, text: str, f: Poly, t: int) -> DiffItem:
    v = _v_at(f, t)
    return _value_item(
        slot=slot,
        frame_id=frame_id,
        text=text,
        value=v,
        explanation=(
            f"속도는 위치를 시각 t로 미분한 값이다. v(t) = {render_poly(_vel(f), _V)}이므로 "
            f"t = {t}일 때의 속도는 {v}이다."
        ),
        conditions=f"{_dv(f, str(t))} = y",
    )


def _acceleration_item(slot: str, frame_id: str, text: str, f: Poly, t: int) -> DiffItem:
    a = _a_at(f, t)
    return _value_item(
        slot=slot,
        frame_id=frame_id,
        text=text,
        value=a,
        explanation=(
            f"가속도는 속도를 시각 t로 미분한 값이다. a(t) = {render_poly(_acc(f), _V)}이므로 "
            f"t = {t}일 때의 가속도는 {a}이다."
        ),
        conditions=f"{_da(f, str(t))} = y",
    )


def _solve_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    answer: int,
    explanation: str,
    conditions: str | tuple[str, ...],
    symbol: str = "s",
    setup: str | None = None,
) -> DiffItem:
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(answer),
        explanation=explanation,
        conditions=conditions,
        answer_map=((symbol, str(answer)),),
        problem_type_code=_SOLVE,
        answer_format=_fmt(answer),
        solution_setup=setup,
    )


# ──────────────────────────────────────────────────────────────────────────
# 대표(representative)
# ──────────────────────────────────────────────────────────────────────────
def _rep_frames() -> list[Frame]:
    slot = "representative"

    def r1(p: tuple[object, ...]) -> DiffItem | None:
        f, t = _as_poly(p[0]), _as_int(p[1])
        return _velocity_item(
            slot,
            "rep-velocity-at-time",
            f"{_intro(f)} t = {t}에서의 점 P의 속도를 구하시오.",
            f,
            t,
        )

    def r2(p: tuple[object, ...]) -> DiffItem | None:
        f, t = _as_poly(p[0]), _as_int(p[1])
        return _acceleration_item(
            slot,
            "rep-acceleration-at-time",
            f"{_intro(f)} t = {t}에서의 점 P의 가속도를 구하시오.",
            f,
            t,
        )

    def r3(p: tuple[object, ...]) -> DiffItem | None:
        base, p0, t = _as_poly(p[0]), _as_int(p[1]), _as_int(p[2])
        if any(e == 2 for e, _ in base) or p0 == 0:
            return None
        full = _poly({**dict(base), 2: p0})
        v = _v_at(full, t)
        human, symbolic = _render_with_param(base, 2)
        return _solve_item(
            slot=slot,
            frame_id="rep-find-coefficient-from-velocity",
            text=(
                f"수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = {human}이다. t = {t}에서의 "
                f"점 P의 속도가 {v}일 때, 상수 {_PARAM}의 값을 구하시오."
            ),
            answer=p0,
            explanation=(
                f"속도는 위치를 시각 t로 미분한 값이므로 "
                f"v(t) = {_render_with_param(_vel(base), 1, 2)[0]}이다. "
                f"v({t}) = {_k_affine(base, t)} = {v}에서 {_PARAM} = {p0}이다."
            ),
            conditions=f"Derivative({symbolic}, t).doit().subs(t, {t}) = {v}",
            symbol=_PARAM,
        )

    def r4(p: tuple[object, ...]) -> DiffItem | None:
        f, r = _as_poly(p[0]), _as_int(p[1])
        v0 = _v_at(f, r)
        s = sympy.Symbol("s")
        found = _unique_root(_vel_expr(f, s) - v0, s, lambda x: x > 0)
        if found != r:
            return None
        return _solve_item(
            slot=slot,
            frame_id="rep-time-when-velocity-given",
            text=(
                f"{_intro(f)} 점 P의 속도가 {with_i_ga(v0)} 되는 시각 t (t > 0)의 값을 구하시오."
            ),
            answer=r,
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)}이므로 {render_poly(_vel(f), _V)} = {v0}에서 "
                f"t = {r}이다."
            ),
            conditions=(f"{_dv(f, 's')} = {v0}", "s > 0"),
        )

    def r5(p: tuple[object, ...]) -> DiffItem | None:
        f, t = _as_poly(p[0]), _as_int(p[1])
        total = _v_at(f, t) + _a_at(f, t)
        return _value_item(
            slot=slot,
            frame_id="rep-velocity-plus-acceleration",
            text=f"{_intro(f)} t = {t}에서의 점 P의 속도와 가속도의 합을 구하시오.",
            value=total,
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)}, a(t) = {render_poly(_acc(f), _V)}이므로 "
                f"t = {t}에서 속도 {with_wa_gwa(_v_at(f, t))} 가속도 {_a_at(f, t)}의 합은 "
                f"{total}이다."
            ),
            # 속도+가속도 = (x + x')'이므로 한 번의 미분 평가로 검산한다.
            conditions=(
                f"Derivative({_st(f)} + Derivative({_st(f)}, t), t).doit().subs(t, {t}) = y"
            ),
            # 풀이 단계는 해설처럼 v(t)·a(t)를 따로 구한다.
            setup=_v_plus_a_setup(f, t),
        )

    def r6(p: tuple[object, ...]) -> DiffItem | None:
        f, t0, t1 = _as_poly(p[0]), _as_int(p[1]), _as_int(p[2])
        if t0 >= t1:
            return None
        change = _v_at(f, t1) - _v_at(f, t0)
        shifted = _shift(f, t1 - t0)
        return _value_item(
            slot=slot,
            frame_id="rep-velocity-change-between-times",
            text=(f"{_intro(f)} t = {t0}에서 t = {t1}까지 점 P의 속도의 변화량을 구하시오."),
            value=change,
            # 3차 감사 bad_explanation — 속도를 위치의 도함수로 구하는 단계(v(t) 식)를 보인다.
            explanation=(
                f"속도는 위치를 시각 t로 미분한 값이므로 v(t) = {render_poly(_vel(f), _V)}이다. "
                f"t = {t1}일 때의 속도는 {_v_at(f, t1)}, t = {t0}일 때의 속도는 "
                f"{_v_at(f, t0)}이므로 "
                f"속도의 변화량은 {_v_at(f, t1)}에서 {with_eul_reul(_v_at(f, t0))} 뺀 값인 "
                f"{change}이다."
            ),
            conditions=(f"Derivative(({_st(shifted)}) - ({_st(f)}), t).doit().subs(t, {t0}) = y"),
            # 풀이 단계는 해설처럼 v(t1) - v(t0)를 따로 구한다(두 번째 시각은 같은 함수를 변수 u로).
            setup=(
                f"(Derivative({poly_to_sympy_str(f, 'u')}, u) - Derivative({_st(f)}, t))"
                f".doit().subs(u, {t1}).subs(t, {t0}) = y"
            ),
        )

    base_pool = tuple(
        _poly({3: lead, 1: c, 0: d})
        for lead in (1, 2, -1)
        for c in (-6, -3, -1, 2, 4)
        for d in (-4, 0, 3)
    )
    return [
        Frame("rep-velocity-at-time", _grid("p3-vel:r1", _cubic_pool()[::7], _TIMES0), r1),
        Frame("rep-acceleration-at-time", _grid("p3-vel:r2", _cubic_pool()[3::7], _TIMES0), r2),
        Frame(
            "rep-find-coefficient-from-velocity",
            _grid("p3-vel:r3", base_pool, (-4, -3, -2, -1, 1, 2, 3, 4), (1, 2, 3, 4)),
            r3,
        ),
        Frame("rep-time-when-velocity-given", _grid("p3-vel:r4", _quad_pool()[::3], _TIMES), r4),
        Frame(
            "rep-velocity-plus-acceleration",
            _grid("p3-vel:r5", _cubic_pool()[5::11], _TIMES0),
            r5,
        ),
        Frame(
            "rep-velocity-change-between-times",
            _grid("p3-vel:r6", _cubic_pool()[2::13], (0, 1, 2), (3, 4, 5)),
            r6,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 기본(basic)
# ──────────────────────────────────────────────────────────────────────────
def _basic_frames() -> list[Frame]:
    slot = "basic"

    def b1(p: tuple[object, ...]) -> DiffItem | None:
        # 3차 감사(2026-10) bad_tag 처분 — 'basic-average-velocity'(평균속도만 묻는 틀)는 위치에 두
        # 시각을 대입한 차분몫이라 미분이 필요 없었다(우회로 판정기 T10-average-only). 두 시각의
        # *순간*속도의 합으로 바꿨다.
        f, t0, t1 = _as_poly(p[0]), _as_int(p[1]), _as_int(p[2])
        if t0 >= t1:
            return None
        v0, v1 = _v_at(f, t0), _v_at(f, t1)
        total = v0 + v1
        shifted = _shift(f, t1 - t0)
        return _value_item(
            slot=slot,
            frame_id="basic-velocity-sum-two-times",
            text=(f"{_intro(f)} t = {t0}일 때와 t = {t1}일 때의 점 P의 속도의 합을 구하시오."),
            value=total,
            explanation=(
                f"속도는 위치를 시각 t로 미분한 값이므로 v(t) = {render_poly(_vel(f), _V)}이다. "
                f"t = {t0}일 때의 속도는 {v0}, t = {t1}일 때의 속도는 {v1}이므로 그 합은 "
                f"{render_sum(v0, v1)} = {total}이다."
            ),
            conditions=(f"Derivative(({_st(f)}) + ({_st(shifted)}), t).doit().subs(t, {t0}) = y"),
            # 풀이 단계는 해설처럼 v(t0) + v(t1)을 따로 구한다(두 번째 시각은 같은 함수를 변수 u로).
            setup=(
                f"(Derivative({_st(f)}, t) + Derivative({poly_to_sympy_str(f, 'u')}, u))"
                f".doit().subs(t, {t0}).subs(u, {t1}) = y"
            ),
        )

    def b2(p: tuple[object, ...]) -> DiffItem | None:
        f, t = _as_poly(p[0]), _as_int(p[1])
        return _acceleration_item(
            slot,
            "basic-acceleration-of-cubic",
            f"{_intro(f)} t = {t}에서 점 P의 가속도를 구하시오.",
            f,
            t,
        )

    def b3(p: tuple[object, ...]) -> DiffItem | None:
        f, t = _as_poly(p[0]), _as_int(p[1])
        return _velocity_item(
            slot,
            "basic-velocity-of-quadratic",
            f"{_intro(f)} t = {t}일 때 점 P의 속도를 구하시오.",
            f,
            t,
        )

    def b5(p: tuple[object, ...]) -> DiffItem | None:
        f, t = _as_poly(p[0]), _as_int(p[1])
        v = _v_at(f, t)
        if v == 0:
            return None
        return _value_item(
            slot=slot,
            frame_id="basic-speed-at-time",
            text=f"{_intro(f)} t = {t}에서의 점 P의 속력(속도의 절댓값)을 구하시오.",
            value=abs(v),
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)}이므로 t = {t}일 때의 속도는 {v}이고 "
                f"속력은 그 절댓값 {abs(v)}이다."
            ),
            conditions=f"Abs({_dv(f, str(t))}) = y",
        )

    def b6(p: tuple[object, ...]) -> DiffItem | None:
        f, t = _as_poly(p[0]), _as_int(p[1])
        return _velocity_item(
            slot,
            "basic-velocity-of-cubic",
            f"{_intro(f)} 시각 t = {t}에서의 순간속도를 구하시오.",
            f,
            t,
        )

    quads = _quad_pool()
    cubics = _cubic_pool()
    return [
        Frame(
            "basic-velocity-sum-two-times", _grid("p3-vel:b1", quads[::5], (0, 1, 2), (3, 4, 5)), b1
        ),
        Frame("basic-acceleration-of-cubic", _grid("p3-vel:b2", cubics[1::17], _TIMES0), b2),
        Frame("basic-velocity-of-quadratic", _grid("p3-vel:b3", quads[1::5], _TIMES0), b3),
        Frame("basic-speed-at-time", _grid("p3-vel:b5", cubics[6::23], _TIMES), b5),
        Frame("basic-velocity-of-cubic", _grid("p3-vel:b6", cubics[8::29], _TIMES0), b6),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 응용(applied) — 시각·상수를 구한다(solve-for-unknown · 스킬 연결 유형)
# ──────────────────────────────────────────────────────────────────────────
def _applied_frames() -> list[Frame]:
    slot = "applied"

    def a1(p: tuple[object, ...]) -> DiffItem | None:
        f = _as_poly(p[0])
        s = sympy.Symbol("s")
        r = _unique_root(_vel_expr(f, s), s)
        if r is None or r <= 0:
            return None
        return _solve_item(
            slot=slot,
            frame_id="applied-time-velocity-zero",
            text=f"{_intro(f)} 점 P의 속도가 0이 되는 시각 t를 구하시오.",
            answer=r,
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)} = 0에서 t는 {r}이다. 이 시각에 점 P는 "
                "운동 방향을 바꾼다."
            ),
            conditions=f"{_dv(f, 's')} = 0",
        )

    def a2(p: tuple[object, ...]) -> DiffItem | None:
        f = _as_poly(p[0])
        s = sympy.Symbol("s")
        r = _unique_root(_acc_expr(f, s), s)
        if r is None or r <= 0:
            return None
        return _solve_item(
            slot=slot,
            frame_id="applied-time-acceleration-zero",
            text=f"{_intro(f)} 점 P의 가속도가 0이 되는 시각 t를 구하시오.",
            answer=r,
            explanation=(f"a(t) = {render_poly(_acc(f), _V)} = 0에서 t는 {r}이다."),
            conditions=f"{_da(f, 's')} = 0",
        )

    def a3(p: tuple[object, ...]) -> DiffItem | None:
        f, r1, r2 = cast(tuple[Poly, int, int], p[0])
        return _solve_item(
            slot=slot,
            frame_id="applied-second-direction-change",
            text=f"{_intro(f)} 점 P가 두 번째로 운동 방향을 바꾸는 시각 t를 구하시오.",
            answer=r2,
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)} = {render_factored(_vel(f), _V)} = 0의 두 근은 "
                f"{r1}, {r2}이고 각 근의 좌우에서 속도의 부호가 바뀌므로 두 번째 시각은 {r2}이다."
            ),
            conditions=(f"{_dv(f, 's')} = 0", f"s > {r1}"),
        )

    def a4(p: tuple[object, ...]) -> DiffItem | None:
        f, r1, r2 = cast(tuple[Poly, int, int], p[0])
        return _solve_item(
            slot=slot,
            frame_id="applied-first-direction-change",
            text=f"{_intro(f)} 점 P가 처음으로 운동 방향을 바꾸는 시각 t를 구하시오.",
            answer=r1,
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)} = {render_factored(_vel(f), _V)} = 0의 두 근은 "
                f"{r1}, {r2}이고 각 근의 좌우에서 속도의 부호가 바뀌므로 처음 시각은 {r1}이다."
            ),
            conditions=(f"{_dv(f, 's')} = 0", f"s < {r2}"),
        )

    def a5(p: tuple[object, ...]) -> DiffItem | None:
        base, p0, t = _as_poly(p[0]), _as_int(p[1]), _as_int(p[2])
        if any(e == 2 for e, _ in base) or p0 == 0:
            return None
        full = _poly({**dict(base), 2: p0})
        # t = t0에서 속도가 0이 되도록 base의 t 계수를 맞춘다: base'(t) + 2 p t = 0 → 계수 조정.
        v = _v_at(full, t)
        if v != 0:
            return None
        human, symbolic = _render_with_param(base, 2)
        return _solve_item(
            slot=slot,
            frame_id="applied-coefficient-from-velocity-zero",
            text=(
                f"수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = {human}이다. t = {t}에서 "
                f"점 P의 속도가 0일 때, 상수 {_PARAM}의 값을 구하시오."
            ),
            answer=p0,
            explanation=(
                f"속도는 위치를 시각 t로 미분한 값이므로 "
                f"v(t) = {_render_with_param(_vel(base), 1, 2)[0]}이다. "
                f"v({t}) = {_k_affine(base, t)} = 0에서 {_PARAM} = {p0}이다."
            ),
            conditions=f"Derivative({symbolic}, t).doit().subs(t, {t}) = 0",
            symbol=_PARAM,
        )

    def a6(p: tuple[object, ...]) -> DiffItem | None:
        lead, b, c = (_as_int(v) for v in p)
        f = _poly({2: lead, 1: b, 0: c})
        s = sympy.Symbol("s")
        r = _unique_root(_vel_expr(f, s) - _acc_expr(f, s), s)
        if r is None or r <= 0:
            return None
        return _solve_item(
            slot=slot,
            frame_id="applied-time-velocity-equals-acceleration",
            text=f"{_intro(f)} 점 P의 속도와 가속도가 같아지는 시각 t를 구하시오.",
            answer=r,
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)}, a(t) = {_a_at(f, 0)}이므로 "
                f"{render_poly(_vel(f), _V)} = {_a_at(f, 0)}에서 t = {r}이다."
            ),
            # v - a = (x - x')' 이므로 한 번의 미분 평가로 검산한다.
            conditions=f"Derivative({_st(f)} - Derivative({_st(f)}, t), t).doit().subs(t, s) = 0",
        )

    # a5: 속도 0 조건이 성립하는 (base, p0, t) 조합을 미리 걸러 둔다(계수 c는 base의 t 항).
    a5_params: list[tuple[object, ...]] = []
    for lead in (1, 2, -1):
        for p0 in (-4, -3, -2, -1, 1, 2, 3, 4):
            for t0 in (1, 2, 3, 4):
                # base = lead t^3 + c t + d, v(t0) = 3 lead t0^2 + c + 2 p0 t0 = 0 → c 결정
                c = -(3 * lead * t0 * t0 + 2 * p0 * t0)
                for d in (-3, 0, 2, 5):
                    a5_params.append((_poly({3: lead, 1: c, 0: d}), p0, t0))

    return [
        Frame("applied-time-velocity-zero", _grid("p3-vel:a1", _stop_quad_pool()), a1),
        Frame(
            "applied-time-acceleration-zero",
            _grid("p3-vel:a2", _cubic_pool()[::3]),
            a2,
        ),
        Frame(
            "applied-second-direction-change",
            tuple((item,) for item in seeded_order("p3-vel:a3", _two_stop_cubic_pool())),
            a3,
        ),
        Frame(
            "applied-first-direction-change",
            tuple((item,) for item in seeded_order("p3-vel:a4", _two_stop_cubic_pool())),
            a4,
        ),
        Frame(
            "applied-coefficient-from-velocity-zero",
            tuple(seeded_order("p3-vel:a5", a5_params)),
            a5,
        ),
        Frame(
            "applied-time-velocity-equals-acceleration",
            _grid("p3-vel:a6", (1, 2, -1, -2, 3), tuple(range(-12, 13)), (-2, 0, 3)),
            a6,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 오개념 유발(misconception_trigger) — 미분 단계의 power-rule-step-omitted
# ──────────────────────────────────────────────────────────────────────────
def _wrong_step(f: Poly, mode: str) -> Poly:
    """항별 거듭제곱 미분의 *틀린* 한 단계 — 'coeff'(지수 안 내림) / 'exp'(지수 안 줄임)."""
    if mode == "coeff":
        return _poly({e - 1: c for e, c in f if e >= 1})
    return _poly({e: c * e for e, c in f if e >= 1})


def _wrong_values(f: Poly, t: int, steps: int) -> tuple[int, int]:
    """(coeff 누락, exp 누락)이 `steps`번 미분에서 만드는 틀린 값."""
    out: list[int] = []
    for mode in ("coeff", "exp"):
        g = f
        for _ in range(steps):
            g = _wrong_step(g, mode)
        out.append(eval_at(g, t, _V))
    return out[0], out[1]


def _mc_item(
    *,
    frame_id: str,
    text: str,
    correct: int,
    wrong: tuple[int, int],
    filler: int,
    conditions: str,
    explanation: str,
    shuffle_key: str,
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
        answer_map=(("y", str(correct)),),
        problem_type_code=_EVAL,
        answer_format=_fmt(answer),
        choices=choices,
        distractors=distractors,
        solution_setup=setup,
    )


def _misconception_frames() -> list[Frame]:
    def m1(p: tuple[object, ...]) -> DiffItem | None:
        f, t = _as_poly(p[0]), _as_int(p[1])
        v = _v_at(f, t)
        # 속도가 음수이면 속력(|v|)을 미매핑 필러로 — 속도의 부호를 무시하는 선지(M0678 증상).
        filler = abs(v) if v < 0 else _x_at(f, t)
        return _mc_item(
            frame_id="mc-velocity-at-time",
            text=f"{_intro(f)} t = {t}에서의 점 P의 속도는?",
            correct=v,
            wrong=_wrong_values(f, t, 1),
            filler=filler,
            conditions=f"{_dv(f, str(t))} = y",
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)}이므로 t = {t}일 때의 속도는 {v}이다."
                f"{_POWER_TRAP}"
            ),
            shuffle_key=f"vm1:{_rt(f)}:{t}",
        )

    def m2(p: tuple[object, ...]) -> DiffItem | None:
        f, t = _as_poly(p[0]), _as_int(p[1])
        v = _v_at(f, t)
        filler = abs(v) if v < 0 else _x_at(f, t)
        return _mc_item(
            frame_id="mc-instantaneous-velocity",
            text=f"{_intro(f)} 시각 t = {t}에서의 순간속도로 옳은 것은?",
            correct=v,
            wrong=_wrong_values(f, t, 1),
            filler=filler,
            conditions=f"{_dv(f, str(t))} = y",
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)}이므로 t = {t}일 때의 순간속도는 {v}이다."
                f"{_POWER_TRAP}"
            ),
            shuffle_key=f"vm2:{_rt(f)}:{t}",
        )

    def m3(p: tuple[object, ...]) -> DiffItem | None:
        f, t = _as_poly(p[0]), _as_int(p[1])
        a = _a_at(f, t)
        return _mc_item(
            frame_id="mc-acceleration-at-time",
            text=f"{_intro(f)} t = {t}에서의 점 P의 가속도는?",
            correct=a,
            wrong=_wrong_values(f, t, 2),
            filler=_v_at(f, t),
            conditions=f"{_da(f, str(t))} = y",
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)}이고 a(t) = {render_poly(_acc(f), _V)}이므로 "
                f"t = {t}일 때의 가속도는 {a}이다.{_POWER_TRAP}"
            ),
            shuffle_key=f"vm3:{_rt(f)}:{t}",
        )

    def m4(p: tuple[object, ...]) -> DiffItem | None:
        f, t = _as_poly(p[0]), _as_int(p[1])
        v, a = _v_at(f, t), _a_at(f, t)
        w1v, w2v = _wrong_values(f, t, 1)
        w1a, w2a = _wrong_values(f, t, 2)
        return _mc_item(
            frame_id="mc-velocity-plus-acceleration",
            text=f"{_intro(f)} t = {t}에서의 점 P의 속도와 가속도의 합은?",
            correct=v + a,
            wrong=(w1v + w1a, w2v + w2a),
            filler=v - a,
            conditions=(
                f"Derivative({_st(f)} + Derivative({_st(f)}, t), t).doit().subs(t, {t}) = y"
            ),
            setup=_v_plus_a_setup(f, t),
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)}, a(t) = {render_poly(_acc(f), _V)}이므로 "
                f"t = {t}에서 속도는 {v}, 가속도는 {a}이고 합은 {render_sum(v, a)} = {v + a}이다."
                f"{_POWER_TRAP}"
            ),
            shuffle_key=f"vm4:{_rt(f)}:{t}",
        )

    def m5(p: tuple[object, ...]) -> DiffItem | None:
        s = _as_int(p[0])
        t0 = s * s
        b = 2 * t0
        entries = [
            ChoiceEntry(str(t0), is_correct=True, sort_key=float(t0)),
            ChoiceEntry(str(b), _KEBAB, sort_key=float(b)),  # v = t로 쓴 경우
            ChoiceEntry(str(s), _KEBAB, sort_key=float(s)),  # v = 2t^2으로 쓴 경우
            ChoiceEntry(str(sympy.Rational(t0, 2)), sort_key=t0 / 2),
        ]
        try:
            choices, answer, distractors = build_choices(entries, shuffle_seed=f"vm5:{s}")
        except ValueError:
            return None
        return DiffItem(
            slot="misconception_trigger",
            frame_id="mc-time-for-velocity-quadratic",
            question_text=(
                f"수직선 위를 움직이는 점 P의 시각 t (t > 0)에서의 위치가 x = t^2일 때, "
                f"점 P의 속도가 {with_i_ga(b)} 되는 시각 t는?"
            ),
            answer_text=answer,
            explanation=(
                f"v(t) = 2t이므로 2t = {b}에서 t = {t0}이다. 속도를 t로 쓰거나(계수 2 누락) "
                "2t^2으로 쓰면(지수를 1 줄이지 않음) 다른 시각이 나온다."
            ),
            conditions=f"Derivative(t**2, t).doit().subs(t, s) = {b}",
            answer_map=(("s", str(t0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(answer),
            choices=choices,
            distractors=distractors,
        )

    def m6(p: tuple[object, ...]) -> DiffItem | None:
        t0 = _as_int(p[0])
        b = 3 * t0 * t0
        wrong_coeff = sympy.sqrt(b)  # v = t^2으로 쓴 학생이 얻는 시각
        entries = [
            ChoiceEntry(str(t0), is_correct=True, sort_key=float(t0)),
            # 학생 표기 — '5√3'(4차 감사 bad_wording: 3차의 '5sqrt(3)'도 코드 표기로 판정됐다).
            ChoiceEntry(render_surd(wrong_coeff), _KEBAB, sort_key=float(wrong_coeff)),
        ]
        cube_root = round(t0 ** (2 / 3))
        if cube_root**3 == t0 * t0 and cube_root != t0:
            entries.append(ChoiceEntry(str(cube_root), _KEBAB, sort_key=float(cube_root)))
            entries.append(ChoiceEntry(str(t0 * t0), sort_key=float(t0 * t0)))
        else:
            entries.append(ChoiceEntry(str(t0 * t0), sort_key=float(t0 * t0)))
            entries.append(ChoiceEntry(str(3 * t0), sort_key=float(3 * t0)))
        try:
            choices, answer, distractors = build_choices(entries, shuffle_seed=f"vm6:{t0}")
        except ValueError:
            return None
        return DiffItem(
            slot="misconception_trigger",
            frame_id="mc-time-for-velocity-cubic",
            question_text=(
                f"수직선 위를 움직이는 점 P의 시각 t (t > 0)에서의 위치가 x = t^3일 때, "
                f"점 P의 속도가 {with_i_ga(b)} 되는 시각 t는?"
            ),
            answer_text=answer,
            explanation=(
                f"v(t) = 3t^2이므로 3t^2 = {b}에서 t^2 = {t0 * t0}이고, t > 0이므로 t = {t0}이다. "
                "속도를 t^2으로 쓰거나(계수 3 누락) 3t^3으로 쓰면(지수를 1 줄이지 않음) 다른 "
                "시각이 나온다."
            ),
            conditions=(f"Derivative(t**3, t).doit().subs(t, s) = {b}", "s > 0"),
            answer_map=(("s", str(t0)),),
            problem_type_code=_SOLVE,
            answer_format=_fmt(answer),
            choices=choices,
            distractors=distractors,
        )

    pool = tuple(
        _poly({n: lead, 1: c, 0: d})
        for n in (3, 4)
        for lead in (1, 2, -1)
        for c in (-6, -3, 2, 5)
        for d in (0, 3)
    ) + tuple(_poly({3: lead, 2: b, 1: c}) for lead in (1, 2) for b in (-3, -1, 2) for c in (-6, 4))
    # 시각은 0 이상이다 — 음수 시각에서의 속도·가속도를 묻지 않는다(2차 감사 결함).
    times = (0, 1, 2, 3, 4)
    return [
        Frame("mc-velocity-at-time", _grid("p3-vel:m1", pool, times), m1),
        Frame("mc-instantaneous-velocity", _grid("p3-vel:m2", pool, times), m2),
        Frame("mc-acceleration-at-time", _grid("p3-vel:m3", pool, times), m3),
        Frame("mc-velocity-plus-acceleration", _grid("p3-vel:m4", pool, times), m4),
        Frame("mc-time-for-velocity-quadratic", _grid("p3-vel:m5", (2, 3, 4, 5, 6, 7, 8)), m5),
        Frame("mc-time-for-velocity-cubic", _grid("p3-vel:m6", (2, 3, 4, 5, 6, 8, 27)), m6),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 진단(diagnostic) — 속도·가속도의 의미를 한 가지씩 확인
# ──────────────────────────────────────────────────────────────────────────
def _diagnostic_frames() -> list[Frame]:
    slot = "diagnostic"

    # 4차 감사(2026-10-07) bad_tag 처분 — 위치가 상수(x = 7로 일정)·일차(x = 2t + 1)인 틀 3종
    # (정지점의 속도·등속 운동의 속도·가속도)을 삭제했다. 정지면 속도 0, 등속이면 가속도 0·속도는
    # 일차함수의 기울기라는 상식으로 풀린다(판정기 T10-linear-position이 재발을 막는다).
    def d3(p: tuple[object, ...]) -> DiffItem | None:
        f = _as_poly(p[0])
        if not any(e == 1 for e, _ in f):
            return None
        return _velocity_item(
            slot,
            "diag-velocity-at-start",
            f"{_intro(f)} 출발하는 순간(t = 0)의 점 P의 속도를 구하시오.",
            f,
            0,
        )

    def d10(p: tuple[object, ...]) -> DiffItem | None:
        # 이차 위치의 가속도 — 시각과 무관한 상수 2A다. 속도 v(t)(시각에 따라 변함)나 위치와
        # 혼동하면 시각 T에 따라 다른 값이 나와 변별된다(등속 운동의 '가속도 0'과 달리 상식으로
        # 정해지지 않는다).
        f, t = _as_poly(p[0]), _as_int(p[1])
        if dict(f).get(1, 0) == 0:
            return None
        a = _a_at(f, t)
        return _value_item(
            slot=slot,
            frame_id="diag-acceleration-of-quadratic-position",
            text=f"{_intro(f)} t = {t}에서의 점 P의 가속도를 구하시오.",
            value=a,
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)}이고 a(t) = {render_poly(_acc(f), _V)}이다. "
                f"가속도는 시각과 관계없이 항상 {a}이다. 따라서 t = {t}에서의 가속도는 {a}이다."
            ),
            conditions=f"{_da(f, str(t))} = y",
        )

    def d5(p: tuple[object, ...]) -> DiffItem | None:
        n, t = _as_int(p[0]), _as_int(p[1])
        f: Poly = ((n, 1),)
        return _acceleration_item(
            slot,
            "diag-acceleration-of-power-position",
            f"수직선 위의 점 P의 시각 t에서의 위치가 x = t^{n}일 때, t = {t}에서의 점 P의 "
            "가속도를 구하시오.",
            f,
            t,
        )

    def d6(p: tuple[object, ...]) -> DiffItem | None:
        lead, r = _as_int(p[0]), _as_int(p[1])
        f = _poly({2: lead, 1: -2 * lead * r})
        s = sympy.Symbol("s")
        found = _unique_root(_vel_expr(f, s), s)
        if found != r:
            return None
        return _solve_item(
            slot=slot,
            frame_id="diag-time-at-rest",
            text=f"{_intro(f)} 점 P가 순간적으로 멈추는 시각 t를 구하시오.",
            answer=r,
            explanation=f"v(t) = {render_poly(_vel(f), _V)} = 0에서 t는 {r}이다.",
            conditions=f"{_dv(f, 's')} = 0",
        )

    return [
        Frame("diag-velocity-at-start", _grid("p3-vel:d3", _quad_pool()[::7]), d3),
        Frame(
            "diag-acceleration-of-quadratic-position",
            _grid("p3-vel:d10", _quad_pool()[2::9], _TIMES),
            d10,
        ),
        Frame(
            "diag-acceleration-of-power-position",
            _grid("p3-vel:d5", (2, 3, 4, 5, 6), (1, 2, 3)),
            d5,
        ),
        Frame("diag-time-at-rest", _grid("p3-vel:d6", (1, 2, -1, 3), (1, 2, 3, 4, 5, 6)), d6),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 숙련도 확인(mastery_check)
# ──────────────────────────────────────────────────────────────────────────
def _mastery_frames() -> list[Frame]:
    slot = "mastery_check"

    def k1(p: tuple[object, ...]) -> DiffItem | None:
        f, t0, t1 = _as_poly(p[0]), _as_int(p[1]), _as_int(p[2])
        if t1 - t0 < 2:
            return None
        diff = _x_at(f, t1) - _x_at(f, t0)
        if diff % (t1 - t0) != 0:
            return None
        avg = diff // (t1 - t0)
        s = sympy.Symbol("s")
        found = _unique_root(_vel_expr(f, s) - avg, s, lambda r: t0 < r < t1)
        if found is None:
            return None
        return _solve_item(
            slot=slot,
            frame_id="mastery-time-average-equals-instant",
            text=(
                f"{_intro(f)} t = {t0}에서 t = {t1}까지의 평균속도와 순간속도가 같아지는 시각 "
                f"t ({t0} < t < {t1})를 구하시오."
            ),
            answer=found,
            explanation=(
                f"평균속도는 (x({t1}) - x({t0}))/({t1} - {t0}) = "
                f"({_minus(_x_at(f, t1), _x_at(f, t0))})/{t1 - t0} = {avg}이다. "
                f"v(t) = {render_poly(_vel(f), _V)}이므로 {render_poly(_vel(f), _V)} = {avg}에서 "
                f"t = {found}이다."
            ),
            conditions=(f"{_dv(f, 's')} = {avg}", f"s > {t0}", f"s < {t1}"),
        )

    def k2(p: tuple[object, ...]) -> DiffItem | None:
        f, r1, r2 = cast(tuple[Poly, int, int], p[0])
        which = _as_int(p[1])
        r = r1 if which == 1 else r2
        order = "처음" if which == 1 else "두 번째로"
        x = _x_at(f, r)
        return _value_item(
            slot=slot,
            frame_id="mastery-position-at-direction-change",
            text=f"{_intro(f)} 점 P가 {order} 운동 방향을 바꿀 때의 점 P의 위치를 구하시오.",
            value=x,
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)} = {render_factored(_vel(f), _V)}이므로 "
                f"{_sign_change_text(r1, r2)} {order} 방향을 바꾸는 시각은 {r}이고 그때의 위치는 "
                f"x({r}) = {x}이다."
            ),
            conditions=f"{_at(f, r)} = y",
            # 검산 조건은 위치 대입 산술식 — 풀이 단계는 해설의 v(t) = 0(운동 방향이 바뀌는
            # 시각)에서 출발해 그 시각들에서 끝난다(위치 x(r)는 다른 미지수라 같은 연쇄에 싣지
            # 못한다).
            setup=f"Derivative({_st(f)}, t).doit() = 0",
        )

    def k3(p: tuple[object, ...]) -> DiffItem | None:
        lead, b, c, d = (_as_int(v) for v in p)
        f = _poly({3: lead, 2: b, 1: c, 0: d})
        s = sympy.Symbol("s")
        r = _unique_root(_acc_expr(f, s), s)
        if r is None or r < 0:
            return None
        v = _v_at(f, r)
        return _value_item(
            slot=slot,
            frame_id="mastery-velocity-when-acceleration-zero",
            text=f"{_intro(f)} 점 P의 가속도가 0이 되는 시각의 속도를 구하시오.",
            value=v,
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)}이고 a(t) = {render_poly(_acc(f), _V)}이다. "
                f"a(t) = 0에서 t는 {r}이고, 그때의 속도는 v(t)에 t = {with_eul_reul(r)} 대입한 "
                f"{v}이다."
            ),
            conditions=f"{_dv(f, str(r))} = y",
        )

    def k4(p: tuple[object, ...]) -> DiffItem | None:
        f, g = _as_poly(p[0]), _as_poly(p[1])
        if f == g:
            return None
        diff = _poly({e: c for e, c in _combine(f, g)})
        s = sympy.Symbol("s")
        r = _unique_root(_vel_expr(diff, s), s, lambda x: x > 0)
        if r is None:
            return None
        return _solve_item(
            slot=slot,
            frame_id="mastery-equal-velocity-two-points",
            # 두 위치를 둘 다 'x = …'로 쓰면 기호가 겹친다(2차 감사) — f(t)·g(t)로 나눠 쓴다.
            text=(
                f"수직선 위를 움직이는 두 점 P, Q의 시각 t에서의 위치가 각각 f(t) = {_rt(f)}, "
                f"g(t) = {_rt(g)}이다. 두 점의 속도가 같아지는 시각 t (t > 0)의 값을 구하시오."
            ),
            answer=r,
            explanation=(
                f"P의 속도는 f'(t) = {render_poly(_vel(f), _V)}, Q의 속도는 "
                f"g'(t) = {render_poly(_vel(g), _V)}이다. "
                f"{render_poly(_vel(f), _V)} = {render_poly(_vel(g), _V)}에서 t = {r}이다."
            ),
            conditions=(f"Derivative(({_st(f)}) - ({_st(g)}), t).doit().subs(t, s) = 0", "s > 0"),
            # 풀이 단계는 해설처럼 f'(t) = g'(t)로 두 속도를 따로 미분한다.
            setup=(
                f"Derivative({_st(f)}, t).doit().subs(t, s) = "
                f"Derivative({_st(g)}, t).doit().subs(t, s)"
            ),
        )

    def k5(p: tuple[object, ...]) -> DiffItem | None:
        lead, p0, t_a, t_b = (_as_int(v) for v in p)
        if t_a == t_b:
            return None
        # x = lead t^3 + p t^2 + 2t : 가속도 a(t) = 6 lead t + 2p = 0 at t = t_a → p = -3 lead t_a
        if p0 != -3 * lead * t_a:
            return None
        f = _poly({3: lead, 2: p0, 1: 2})
        v = _v_at(f, t_b)
        human, symbolic = _render_with_param(_poly({3: lead, 1: 2}), 2)
        # 첫 미지수 k는 생성기가 SymPy로 푼 값(`p0`)을 조건에 대입한다 — 마지막 속도만 검산.
        return _value_item(
            slot=slot,
            frame_id="mastery-coefficient-then-velocity",
            text=(
                f"수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = {human} ({_PARAM}는 상수)"
                f"이다. t = {t_a}에서의 점 P의 가속도가 0일 때, t = {t_b}에서의 점 P의 속도를 "
                "구하시오."
            ),
            value=v,
            explanation=(
                f"v(t) = {3 * lead}t^2 + 2{_PARAM}t + 2이고 a(t) = {6 * lead}t + 2{_PARAM}이다. "
                f"a({t_a}) = {6 * lead * t_a} + 2{_PARAM} = 0에서 {_PARAM} = {p0}이다. 그러면 "
                f"v(t) = {render_poly(_vel(f), _V)}이고 t = {t_b}에서의 속도는 {v}이다."
            ),
            conditions=f"{_dv(f, str(t_b))} = y",
        )

    def k6(p: tuple[object, ...]) -> DiffItem | None:
        f, r1, r2 = cast(tuple[Poly, int, int], p[0])
        which = _as_int(p[1])
        r = r1 if which == 1 else r2
        order = "처음" if which == 1 else "두 번째로"
        a = _a_at(f, r)
        return _value_item(
            slot=slot,
            frame_id="mastery-acceleration-at-direction-change",
            text=(f"{_intro(f)} 점 P가 {order} 운동 방향을 바꾸는 순간의 가속도를 구하시오."),
            value=a,
            explanation=(
                f"v(t) = {render_poly(_vel(f), _V)} = {render_factored(_vel(f), _V)}이므로 "
                f"{_sign_change_text(r1, r2)} {order} 방향을 바꾸는 시각은 {r}이고 "
                f"a(t) = {render_poly(_acc(f), _V)}이므로 그때의 가속도는 {a}이다."
            ),
            conditions=f"{_da(f, str(r))} = y",
        )

    stops = _two_stop_cubic_pool()
    k5_params = tuple(
        (lead, -3 * lead * ta, ta, tb)
        for lead in (1, 2, -1, 3)
        for ta in (1, 2, 3, 4)
        for tb in (0, 1, 2, 3, 4, 5)
    )
    pair_pool = tuple(
        (_poly({2: a2, 1: b1, 0: 0}), _poly({2: g2, 1: g1, 0: 3}))
        for a2 in (1, 2, -1, 3)
        for b1 in (-6, -3, 2, 5)
        for g2 in (1, -1, 2)
        for g1 in (-4, 1, 4, 7)
    )
    k4_params = tuple((f, g) for f, g in pair_pool if f != g) + tuple(
        (_poly({3: 1, 1: c1}), _poly({2: g2, 1: g1}))
        for c1 in (-6, -3, 2, 4)
        for g2 in (1, 2, -1)
        for g1 in (-4, 3, 6)
    )
    return [
        Frame(
            "mastery-time-average-equals-instant",
            _grid("p3-vel:k1", _quad_pool()[::5], (0, 1, 2), (3, 4, 5, 6)),
            k1,
        ),
        Frame(
            "mastery-position-at-direction-change",
            tuple(seeded_order("p3-vel:k2", [(s, w) for s in stops for w in (1, 2)])),
            k2,
        ),
        Frame(
            "mastery-velocity-when-acceleration-zero",
            _grid("p3-vel:k3", (1, 2, -1), tuple(range(-9, 10, 3)), tuple(range(-6, 7)), (0, 2)),
            k3,
        ),
        Frame("mastery-equal-velocity-two-points", tuple(seeded_order("p3-vel:k4", k4_params)), k4),
        Frame(
            "mastery-coefficient-then-velocity",
            tuple(seeded_order("p3-vel:k5", k5_params)),
            k5,
        ),
        Frame(
            "mastery-acceleration-at-direction-change",
            tuple(seeded_order("p3-vel:k6", [(s, w) for s in stops for w in (1, 2)])),
            k6,
        ),
    ]


def _combine(f: Poly, g: Poly) -> list[tuple[int, int]]:
    """f - g의 항(같은 차수 합산) — `_poly`가 0 항을 걸러 낸다."""
    merged: dict[int, int] = {}
    for e, c in f:
        merged[e] = merged.get(e, 0) + c
    for e, c in g:
        merged[e] = merged.get(e, 0) - c
    return list(merged.items())


_SLOT_FRAMES = {
    "representative": _rep_frames,
    "basic": _basic_frames,
    "applied": _applied_frames,
    "misconception_trigger": _misconception_frames,
    "diagnostic": _diagnostic_frames,
    "mastery_check": _mastery_frames,
}


class P3DiffVelocityAccelerationGenerator(P3DiffSlotGenerator):
    """[12미적Ⅰ-02-10] 속도와 가속도 — 슬롯 6종 결정론 생성기."""

    standard_code: ClassVar[str] = "[12미적Ⅰ-02-10]"
    concept_src_id: ClassVar[str] = "H:12미적Ⅰ02-10"
    unit_code: ClassVar[str] = "P3-CALC1-DIFF-VELOCITY-ACCELERATION"
    slug_prefix: ClassVar[str] = "wm-p3-diff-velocity"
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
