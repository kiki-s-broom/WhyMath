"""[12미적Ⅰ-02-09] 방정식과 부등식에의 활용 결정론 문항 생성기 — P3-03(결정론·LLM 0).

개념: `H:12미적Ⅰ02-09`(`math.calculus.bangjeongsik-budeungsikeui-hwalyong`). 핵심 오개념: M0677
(f(x) = k의 근의 개수를 그래프와 가로선 y = k의 교점으로 보는 관점을 못 쓴다). 이 M-id에는 L4
카탈로그의 kebab이 **없다**(MISC-40이 omission형이라 의도적으로 미승격). 그래서 오개념 유발
슬롯의 `distractor_map`은 **M-id를 그대로** 쓴다(계측기가 M-id를 그대로 센다). 신규 id는 만들지
않는다. 대신 L4 참조 무결성 검증자(`validate_distractor_map`)는 M-id를 알지 못해 위반으로 읽는다
— 등록 때 처분이 필요하다(작성자 보고 참조).

범위 — 수치형만(P3-20 판정 §3·§4·§6 준수)
-----------------------------------------
**매개변수(k) 범위형 문항은 만들지 않는다**(검증 경로 없음 — skip은 통과가 아니다). 이 파일의 문항은
계수가 전부 숫자이고 답이 숫자 하나인 수치형이며, 두 갈래다:

  · 실근의 개수(`answer_kind=real_root_count`) — 방정식 f(x) = k의 실근을 곡선 y = f(x)와 직선
    y = k의 교점으로 본다(이 개념의 인지 행동). 유리근이 없는 식(인수분해로 못 푸는 식)은 해설이
    **도함수 → 극값 → 증감 구간마다 f가 지나는 값의 범위 → k가 든 범위의 수**로 센다.
    인수분해가 되는 식도 일부 남기되(기본 감각), 해설은 인수·중근(한 번만 센다)·허근 인수(항상
    양수)를 모두 보인다.
  · 부등식의 등호 조건(값형·`solve-for-unknown`) — 두 변의 차를 f(x)로 놓고 도함수로 최솟값이
    0임을 확인해 *등호가 성립하는 x*를 묻는다(모든 실수 / x >= 0 / x > 0). 해가 한 점이라
    P3-20 S6의 한계(한 점만 본다)가 닿지 않는다.

P3-20 §3 지침: 실근 개수형을 한 슬롯에 몰아 쓰지 않는다 — 슬롯마다 개수형은 최대 2틀이고 나머지는
부등식 등호형이다(오개념 유발 슬롯은 객관식 개수형만 — 예외).

2차 감사(2026-10) 처분 — 삭제한 틀
--------------------------------
근과 계수의 관계(세·네 근의 합·곱, 교점 x좌표의 합)·근 고르기(가장 큰/작은 실근, 양의 실근,
'0 이상의 실수일 때 방정식의 해')·이차부등식·f'(x) = 0의 근 계산(개수·합·작은 근) 틀은 **삭제**했다.
미분 활용 없이 공통수학1 선수 계산만으로 풀려 02-09 태그가 거짓이 되기 때문이다(bad_tag). '던진
물체의 높이' 맥락은 최고차 계수가 양수인 삼차식이 물리 모델과 모순이어서 수직선 위 점의 위치로
바꿨다. 한 다항식 풀을 여러 틀이 쓸 때는 풀을 서로소 몫으로 나눠(`_part`) 같은 다항식이 표기만 바꿔
두 번 나오지 않게 한다(QUAL-07 — 같은 수학 실체 중복 금지).

극값 증인(witness) 문항
--------------------
'최고차항의 계수가 양수인 삼차함수 f(x)의 극댓값이 M, 극솟값이 m' 형태는 f를 주지 않는다. 그런
삼차함수의 그래프는 모두 증가 → 극대 → 감소 → 극소 → 증가하므로 f(x) = k의 실근 개수는
(M, m, k)만으로 정해진다. 검산 조건에는 그 대표 함수 f_w(x) = (M - m)(2x^3 - 3x^2) + M
(x = 0에서 극댓값 M, x = 1에서 극솟값 m)을 쓴다 — 어떤 대표를 써도 개수가 같으므로 검산이 문항의
답과 같은 것을 센다.

문제유형 정직성
--------------
실근 개수를 묻는 문항은 `ptype.count-solutions`, 등호가 성립하는 x를 묻는 문항은
`ptype.solve-for-unknown`이다. 이 개념의 명세 스킬(`case-analysis`·`word-problem-modeling`)과 겹치는
유형은 `count-solutions`(case-analysis)뿐이다 — 거짓 유형으로 맞추지 않았다.

게이트 재료 확장: `KindedDiffItem`(`p3_diff_mean_value_theorem_skeleton_generator`)을 쓰고
`_assemble`에서 `with_item_kinds`로 후보에 싣는다(base 모듈 무수정).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from itertools import combinations
from typing import ClassVar, Final

import sympy

from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.p3_diff_expr import (
    Poly,
    derivative_of,
    eval_at,
    poly_from_sympy,
    poly_to_sympy,
    poly_to_sympy_str,
    render_difference,
    render_factored,
    render_poly,
    with_eul_reul,
    with_eun_neun,
    with_i_ga,
    with_ira,
    with_wa_gwa,
)
from whymath_backend.l3.equivalent.p3_diff_mean_value_theorem_skeleton_generator import (
    KindedDiffItem,
    frac_text,
    with_item_kinds,
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
from whymath_backend.lang.josa import eul_reul, wa_gwa

__all__ = ["P3DiffEquationApplicationGenerator"]

#: 오개념 id — M-id 그대로(kebab 좌석 없음. 모듈 docstring 참조).
_MID: Final = "M0677"
_SOLVE: Final = "ptype.solve-for-unknown"
_COUNT: Final = "ptype.count-solutions"
_KIND: Final = "real_root_count"
_X = sympy.Symbol("x")
#: 부등식 등호형 다항식의 계수 상한(절댓값) — 손계산이 가능한 크기로 묶는다.
_COEF_CAP: Final = 300


def _poly(expr: sympy.Expr, var: str = "x") -> Poly:
    return poly_from_sympy(sympy.expand(expr), var)


def _minus(poly: Poly, k: int) -> Poly:
    """f - k (상수를 뺀 다항식)."""
    return _poly(poly_to_sympy(poly) - k)


def _n_distinct(poly: Poly) -> int:
    """서로 다른 실근 수 — 검산기와 독립인 경로(제곱 없는 부분의 Sturm 개수)."""
    return int(sympy.Poly(poly_to_sympy(poly), _X).sqf_part().count_roots())


def _no_nonpositive_real_root(poly: Poly) -> bool:
    """실근이 모두 양수인가(0 이하의 실근 0개) — 시각 t >= 0의 맥락과 충돌하지 않는지 본다."""
    return int(sympy.Poly(poly_to_sympy(poly), _X).sqf_part().count_roots(sup=0)) == 0


def _has_rational_root(poly: Poly) -> bool:
    """유리수 근이 있는가(일차 인수가 있는가) — 인수분해로 바로 풀리는 식을 거른다."""
    _, factors = sympy.factor_list(poly_to_sympy(poly), _X)
    return any(sympy.degree(factor, _X) == 1 for factor, _ in factors)


def _lin(c: int, var: str = "x") -> str:
    """'x - 2'·'x + 3'·'x' — (var - c)의 표기."""
    return render_poly(_poly(sympy.Symbol(var) - c, var), var)


def _eq_cond(lhs: Poly, rhs: Poly | int, var: str = "x") -> str:
    right = str(rhs) if isinstance(rhs, int) else poly_to_sympy_str(rhs, var)
    return f"{poly_to_sympy_str(lhs, var)} = {right}"


def _define(name: str, poly: Poly, var: str = "x", lead_in: str = "") -> str:
    """해설 첫 문장 — 'f(x) = x^3 - 3x + 2라 하자.'(함수 기호를 쓰기 전에 정의한다)."""
    return f"{lead_in}{name}({var}) = {with_ira(render_poly(poly, var))} 하자. "


def _deriv_eq(poly: Poly, name: str = "f", var: str = "x") -> str:
    """'f'(x) = 3x^2 - 3 = 3(x + 1)(x - 1)' — 도함수와 그 인수분해(같으면 한 번만)."""
    d = derivative_of(poly, var)
    raw = render_poly(d, var)
    fac = render_factored(d, var)
    return f"{name}'({var}) = {raw}" + ("" if fac == raw else f" = {fac}")


def _diff_text(left: str, right: str) -> str:
    """두 변의 차 표기 — 'x^3 - (12x - 16)'·'x^4 + 48 - 32x'·'2x^4 + 96 + 64x'.

    오른쪽이 음수 단항이면 빼기를 더하기로 바꿔 '- (-64x)'를 만들지 않고, 다항이면 괄호로 묶는다.
    """
    if right.startswith("-") and " " not in right:
        return f"{left} + {right[1:]}"
    if " " in right:
        return f"{left} - ({right})"
    return f"{left} - {right}"


def _part[T](
    seed: str, pool: Sequence[T], index: int, parts: int
) -> tuple[tuple[object, ...], ...]:
    """풀을 시드 순서로 섞어 서로소 몫 `parts`개로 나눈 뒤 index번째 몫을 틀 파라미터로 낸다.

    같은 다항식이 표기만 바꿔(방정식 = 0 / 곡선과 직선 / 두 곡선) 두 틀에 나오면 검산 조건 문자열은
    달라도 *같은 수학 실체*다(QUAL-07). 한 풀을 쓰는 틀끼리 몫을 나눠 그 중복을 원천 차단한다.
    """
    ordered = seeded_order(seed, tuple(pool))
    return tuple((value,) for value in ordered[index::parts])


# ──────────────────────────────────────────────────────────────────────────
# 인수분해형 풀 — 인수분해된 형태에서 만든다(근을 정확히 알고, 해설이 인수를 보인다)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class _P:
    """다항식 사례 — 전개형과 (선두계수, 실근 목록(중복도 포함), 허근 인수) 구성."""

    poly: Poly
    lead: int
    roots: tuple[int, ...]  # 실근(중복도만큼 반복·오름차순)
    quad: tuple[int, int] | None = None  # 허근 인수 (x - s)^2 + d → (s, d) — 실근이 아니다

    @property
    def distinct_roots(self) -> tuple[int, ...]:
        return tuple(sorted(set(self.roots)))

    @property
    def multiple_roots(self) -> tuple[int, ...]:
        return tuple(r for r in self.distinct_roots if self.roots.count(r) >= 2)

    @property
    def degree(self) -> int:
        return self.poly[0][0]


def _make(lead: int, roots: Sequence[int], quad: tuple[int, int] | None = None) -> _P:
    srt = tuple(sorted(roots))
    expr: sympy.Expr = sympy.Integer(lead)
    for r in srt:
        expr = expr * (_X - r)
    if quad is not None:
        s, d = quad
        expr = expr * ((_X - s) ** 2 + d)
    return _P(_poly(expr), lead, srt, quad)


@lru_cache(maxsize=None)
def _cubics() -> tuple[_P, ...]:
    """삼차: 서로 다른 세 실근 · 중근 + 단근 · 단근 1개 + 허근 인수."""
    out: list[_P] = []
    rng = range(-3, 5)
    for lead in (1, 1, 2):
        for r1 in rng:
            for r2 in rng:
                for r3 in rng:
                    if r1 <= r2 <= r3 and not (r1 == r2 == r3):
                        out.append(_make(lead, (r1, r2, r3)))
    for lead in (1, 2):
        for r in range(-3, 4):
            for s, d in ((0, 1), (0, 2), (1, 1), (-1, 1), (0, 4), (2, 1)):
                out.append(_make(lead, (r,), (s, d)))
    uniq = {p.poly: p for p in out}
    return tuple(seeded_order("p3-eq:cubics", tuple(uniq.values())))


@lru_cache(maxsize=None)
def _quartics() -> tuple[_P, ...]:
    """사차: 네 실근(중근 허용) 또는 실근 2개 + 허근 인수."""
    out: list[_P] = []
    rng = range(-3, 4)
    for r1 in rng:
        for r2 in rng:
            for r3 in rng:
                for r4 in rng:
                    roots = (r1, r2, r3, r4)
                    if list(roots) != sorted(roots) or len(set(roots)) < 2:
                        continue
                    if max(roots.count(v) for v in set(roots)) >= 3:
                        continue
                    out.append(_make(1, roots))
    for r1 in rng:
        for r2 in rng:
            if r1 < r2:
                for s, d in ((0, 1), (0, 2), (1, 1), (-1, 2)):
                    out.append(_make(1, (r1, r2), (s, d)))
    uniq = {p.poly: p for p in out}
    return tuple(seeded_order("p3-eq:quartics", tuple(uniq.values())))


def _split_const(poly: Poly) -> tuple[Poly, int] | None:
    """P = g - k 꼴로 — g는 상수항을 뗀 식, k = -상수항. 상수항이 0이면 None."""
    const = dict(poly).get(0, 0)
    if const == 0:
        return None
    g = tuple((e, c) for e, c in poly if e != 0)
    return g, -const


def _split_line(poly: Poly) -> tuple[Poly, Poly] | None:
    """P = g - h 꼴로 — g는 2차 이상 항, h는 (-1차항 - 상수항)인 직선. 직선이 상수면 None."""
    g = tuple((e, c) for e, c in poly if e >= 2)
    h = tuple((e, -c) for e, c in poly if e < 2)
    if not h or dict(h).get(1, 0) == 0:
        return None
    return g, h


def _split_curves(poly: Poly) -> tuple[Poly, Poly] | None:
    """사차 P = g - h — g는 3차 이상 항, h는 (-1)·(2차 이하 항)인 이차식."""
    g = tuple((e, c) for e, c in poly if e >= 3)
    h = tuple((e, -c) for e, c in poly if e <= 2)
    if not h or h[0][0] != 2:
        return None
    return g, h


def _factor_body(p: _P, *, lead_in: str = "", touch: bool = False) -> tuple[str, int]:
    """인수분해 해설 본문 — 인수·서로 다른 실근·중근(한 번만)·허근 인수(항상 양수). (본문, 개수)."""
    n = _n_distinct(p.poly)
    roots = ", ".join(str(r) for r in p.distinct_roots)
    parts = [f"{lead_in}인수분해하면 {render_factored(p.poly)} = 0이다."]
    if len(p.distinct_roots) == 1:
        parts.append(f"실근은 x = {roots}뿐이다.")
    else:
        parts.append(f"서로 다른 실근은 x = {roots}이다.")
    for r in p.multiple_roots:
        extra = "(그 점에서 두 그래프가 접한다)" if touch else ""
        parts.append(f"x = {with_eun_neun(r)} 중근이므로 한 번만 센다{extra}.")
    if p.quad is not None:
        s, d = p.quad
        quad = render_poly(_poly((_X - s) ** 2 + d))
        if s == 0:
            parts.append(f"이차식 {with_eun_neun(quad)} 항상 양수이므로 실근이 없다.")
        else:
            parts.append(
                f"이차식 {quad} = ({_lin(s)})^2 + {with_eun_neun(d)} 항상 양수이므로 실근이 없다."
            )
    if n != len(p.distinct_roots):  # pragma: no cover — 풀 구성이 깨진 것(작성 오류)
        raise ValueError(f"실근 개수 불일치: {p}")
    return " ".join(parts), n


def _count_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    cond: str,
    poly: Poly,
    explanation: str,
    count: int,
    choices: tuple[str, ...] | None = None,
    distractors: tuple[tuple[int, str], ...] = (),
) -> KindedDiffItem:
    """실근 개수 문항 — 해설이 센 개수와 독립 경로(Sturm) 개수가 같아야 만든다."""
    if count != _n_distinct(poly):  # pragma: no cover — 해설과 검산 경로가 어긋남(작성 오류)
        raise ValueError(f"{frame_id}: 해설 개수 {count} != 실근 수 {_n_distinct(poly)}")
    return KindedDiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(count),
        explanation=explanation,
        conditions=cond,
        answer_map=(),
        problem_type_code=_COUNT,
        answer_format=answer_format_for(str(count)),
        choices=choices,
        distractors=distractors,
        answer_kind=_KIND,
    )


def _value_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    cond: str | tuple[str, ...],
    value: int,
    explanation: str,
) -> DiffItem:
    """등호가 성립하는 x 하나를 묻는 값형 문항(조건이 해를 한 점으로 정한다)."""
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(value),
        explanation=explanation,
        conditions=cond,
        answer_map=(("x", str(value)),),
        problem_type_code=_SOLVE,
        answer_format=answer_format_for(str(value)),
    )


# ──────────────────────────────────────────────────────────────────────────
# 극값 비교형 풀 — f'의 근이 정수(단순근)이고 f - k가 유리근을 갖지 않는다(인수분해로 못 푼다)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class _Level:
    """방정식 f(x) = k — f는 상수항 0인 다항식, crit는 f'의 근(정수·단순근), k는 극값과 다르다."""

    poly: Poly
    crit: tuple[int, ...]
    k: int


def _crit_cubic(lead: int, p: int, q: int) -> Poly | None:
    """f'(x) = 3·lead·(x - p)(x - q)인 삼차식(상수항 0) — 계수가 정수가 아니면 None."""
    if (lead * (p + q)) % 2:
        return None
    return _poly(
        lead * _X**3 - sympy.Rational(3 * lead * (p + q), 2) * _X**2 + 3 * lead * p * q * _X
    )


def _crit_quartic(p: int, q: int, r: int) -> Poly:
    """f'(x) = 12(x - p)(x - q)(x - r)인 사차식(상수항 0)."""
    s1, s2, s3 = p + q + r, p * q + q * r + r * p, p * q * r
    return _poly(3 * _X**4 - 4 * s1 * _X**3 + 6 * s2 * _X**2 - 12 * s3 * _X)


@lru_cache(maxsize=None)
def _cubic_levels() -> tuple[_Level, ...]:
    out: list[_Level] = []
    for lead in (1, 2, -1):
        for p in range(-3, 3):
            for q in range(p + 1, 4):
                f = _crit_cubic(lead, p, q)
                if f is None:
                    continue
                vals = (eval_at(f, p), eval_at(f, q))
                if max(abs(v) for v in vals) > 30:
                    continue
                for k in range(min(vals) - 3, max(vals) + 4):
                    if k in vals or k == 0 or _has_rational_root(_minus(f, k)):
                        continue
                    out.append(_Level(f, (p, q), k))
    return tuple(out)


@lru_cache(maxsize=None)
def _motion_levels() -> tuple[_Level, ...]:
    """시각 t >= 0의 위치 x(t) — 0 < p < q, k > 0, 실근이 모두 양수(정의역과 충돌 없음)."""
    out: list[_Level] = []
    for lead in (1, 2):
        for p in range(1, 4):
            for q in range(p + 1, 5):
                f = _crit_cubic(lead, p, q)
                if f is None:
                    continue
                vals = (eval_at(f, p), eval_at(f, q))
                if max(abs(v) for v in vals) > 40:
                    continue
                for k in range(1, max(vals) + 4):
                    eq = _minus(f, k)
                    if k in vals or _has_rational_root(eq) or not _no_nonpositive_real_root(eq):
                        continue
                    out.append(_Level(f, (p, q), k))
    return tuple(out)


@lru_cache(maxsize=None)
def _quartic_levels() -> tuple[_Level, ...]:
    """f'(x) = 12(x - p)(x - q)(x - r)인 W자 사차식 — 실근 2개 또는 4개인 수준만."""
    out: list[_Level] = []
    for p, q, r in combinations(range(-2, 3), 3):
        f = _crit_quartic(p, q, r)
        vals = tuple(eval_at(f, c) for c in (p, q, r))
        if max(abs(v) for v in vals) > 60:
            continue
        for k in range(min(vals) - 3, max(vals) + 4):
            eq = _minus(f, k)
            if k in vals or k == 0 or _has_rational_root(eq) or _n_distinct(eq) not in (2, 4):
                continue
            out.append(_Level(f, (p, q, r), k))
    return tuple(out)


def _frac_eval(poly: Poly, x: Fraction) -> Fraction:
    return sum((Fraction(c) * x**e for e, c in poly), Fraction(0))


def _level_body(
    level: _Level, *, name: str = "f", var: str = "x", lower: int | None = None
) -> tuple[str, int]:
    """f(x) = k의 실근 개수를 증감으로 센다 — (해설 본문, 개수).

    도함수의 근(정수·단순근)으로 나눈 증감 구간마다 f는 단조이므로 해가 많아야 하나다. 구간마다 f가
    지나는 값의 범위를 적고 k가 든 범위의 수를 센다. `lower`가 있으면 정의역은 var >= lower다.
    """
    f, k = level.poly, level.k
    d = derivative_of(f, var)
    crit = sorted(level.crit)
    vals = [eval_at(f, c, var) for c in crit]

    def rising(x: Fraction) -> bool:
        return _frac_eval(d, x) > 0

    pieces = []
    for c, v in zip(crit, vals, strict=True):
        kind = "극댓값" if rising(Fraction(c) - Fraction(1, 2)) else "극솟값"
        pieces.append(f"{var} = {c}에서 {kind} {v}")
    head = (
        f"{_deriv_eq(f, name, var)}이므로 {name}({var})는 "
        + ", ".join(pieces)
        + f"{eul_reul(str(vals[-1]))} 갖는다. "
    )
    bounds: list[int | None] = [lower, *crit, None]
    ranges: list[str] = []
    hits = 0
    for left, right in zip(bounds, bounds[1:], strict=False):
        if left is None and right is not None:
            sample = Fraction(right - 1)
        elif right is None and left is not None:
            sample = Fraction(left + 1)
        else:
            assert left is not None and right is not None
            sample = Fraction(left + right, 2)
        up = rising(sample)
        lv = None if left is None else eval_at(f, left, var)
        rv = None if right is None else eval_at(f, right, var)
        lo, hi = (lv, rv) if up else (rv, lv)  # None은 그 방향의 무한대
        if left is None:
            label = f"{var} < {right}"
        elif right is None:
            label = f"{var} > {left}"
        else:
            label = f"{left} < {var} < {right}"
        if lo is None:
            span = f"{hi}보다 작은 모든 값"
        elif hi is None:
            span = f"{lo}보다 큰 모든 값"
        else:
            span = f"{with_wa_gwa(lo)} {hi} 사이의 값"
        ranges.append(f"{label}에서 {span}")
        hits += (lo is None or lo < k) and (hi is None or k < hi)
    start = (
        f"{var}가 {lower}일 때 {name}의 값은 {eval_at(f, lower, var)}이고, "
        if lower is not None
        else ""
    )
    body = (
        head
        + f"{start}{name}({var})는 "
        + ", ".join(ranges)
        + f"을 한 번씩 갖는다. {with_eun_neun(k)} 이 가운데 {hits}개의 범위에 들어 있다."
    )
    return body, hits


# ──────────────────────────────────────────────────────────────────────────
# 부등식 등호형 풀 — 도함수로 최솟값 0을 확인하면 등호가 한 점에서만 성립한다
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class _Ineq:
    """등호 조건 부등식 사례 — f(x) >= 0의 등호가 x = a 한 점에서만 성립한다.

    · kind "c1": f = L(x^4 - 4a^3x + 3a^4) = L(x - a)^2(x^2 + 2ax + 3a^2) — 모든 실수에서 f >= 0.
    · kind "c2": f = L(3x^4 - 4ax^3 + a^4) = L(x - a)^2(3x^2 + 2ax + a^2) — 모든 실수에서 f >= 0.
    · kind "v": f = L(x - a)^2(x + s) (a, s > 0, a < 2s) — x >= 0(또는 x > 0)에서 f >= 0.
    """

    kind: str
    poly: Poly
    lead: int
    a: int
    s: int = 0


def _capped(poly: Poly) -> bool:
    return max(abs(c) for _, c in poly) <= _COEF_CAP


@lru_cache(maxsize=None)
def _c1_cases() -> tuple[_Ineq, ...]:
    out = []
    for lead in (1, 2, 3):
        for a in (-3, -2, -1, 1, 2, 3):
            poly = _poly(lead * (_X**4 - 4 * a**3 * _X + 3 * a**4))
            if _capped(poly):
                out.append(_Ineq("c1", poly, lead, a))
    return tuple(out)


@lru_cache(maxsize=None)
def _c2_cases() -> tuple[_Ineq, ...]:
    out = []
    for lead in (1, 2, 3):
        for a in (-3, -2, -1, 1, 2, 3):
            poly = _poly(lead * (3 * _X**4 - 4 * a * _X**3 + a**4))
            if _capped(poly):
                out.append(_Ineq("c2", poly, lead, a))
    return tuple(out)


@lru_cache(maxsize=None)
def _v_cases() -> tuple[_Ineq, ...]:
    out = []
    for lead in (1, 2, 3):
        for a in range(1, 6):
            for s in range(1, 8):
                if a >= 2 * s:
                    # f'(x) = L(x - a)(3x + 2s - a)의 다른 근이 양수면 증감 설명이 복잡해진다
                    continue
                poly = _poly(lead * (_X - a) ** 2 * (_X + s))
                if _capped(poly):
                    out.append(_Ineq("v", poly, lead, a, s))
    return tuple(out)


# 위생 게이트(`l3.pregenerate.validator`) 오탐 회피 규약 — 해설 문장 표기
# · "f'(2) = 5"처럼 프라임 뒤 '(수) = 값'을 쓰지 않는다: 검증기가 '(2) = 5'를 거짓 산술로 읽는다.
# · "f(1) = -7"처럼 함수값 등식을 늘어놓지 않는다: f(1)을 f·1로 읽어 'f = -7'이라는 해 주장으로 세고
#   다른 함수값 등식과 모순이라 판정한다. 극값은 "x = 1에서 극솟값 -7"(교과서 표기)로 쓴다.
# · x에 대한 해 주장('x = a')이 하나뿐이면 "f'(x) = …"를 x의 방정식으로 읽어 모순 판정한다 —
#   도함수의 근을 둘 이상 밝히거나(증감 설명에 필요하다) 'x가 a일 때'로 쓴다.
# 수학 내용은 그대로이고 표기만 고른다(게이트를 약하게 하지 않는다).


def _c1_story(case: _Ineq, name: str = "f") -> str:
    a = case.a
    quad = render_poly(_poly(_X**2 + a * _X + a * a))
    return (
        f"{_deriv_eq(case.poly, name)}이다. 이차식 {quad}의 판별식은 "
        f"{render_difference(a * a, 4 * a * a)} = {-3 * a * a} < 0이므로 {with_eun_neun(quad)} "
        f"항상 양수이고, {name}'(x)의 부호는 {_lin(a)}의 부호와 같다. 따라서 {name}(x)는 "
        f"x <= {a}에서 감소하고 x >= {a}에서 증가하여, x가 {a}일 때 최솟값 {name}({a}) = 0을 "
        "갖는다."
    )


def _c2_story(case: _Ineq, name: str = "f") -> str:
    a = case.a
    return (
        f"{_deriv_eq(case.poly, name)}이다. x^2 >= 0이므로 {name}'(x)의 부호는 {_lin(a)}의 "
        f"부호와 같다(x가 0일 때 {name}'(0) = 0이지만 그 좌우에서 부호가 바뀌지 않는다). 따라서 "
        f"{name}(x)는 x <= {a}에서 감소하고 x >= {a}에서 증가하여, x가 {a}일 때 최솟값 "
        f"{name}({a}) = 0을 갖는다."
    )


def _v_story(case: _Ineq, *, strict: bool, name: str = "f") -> str:
    """x >= 0(또는 x > 0)에서 f(x) = L(x - a)^2(x + s)의 최솟값이 f(a) = 0임을 도함수로 보인다.

    도함수 f'(x) = L(x - a)(3x + 2s - a)의 두 근(음수 근 (a - 2s)/3과 a)을 밝히고, 음수 근은
    정의역 밖이라 버린 뒤 x = a 좌우의 부호로 최솟값을 정한다.
    """
    a, s = case.a, case.s
    rest = 2 * s - a  # f'(x) = L(x - a)(3x + 2s - a)
    g = math.gcd(3, rest)
    other = render_poly(_poly((3 // g) * _X + rest // g))
    root = frac_text(Fraction(a - 2 * s, 3))
    dom = "x > 0" if strict else "x >= 0"
    left = "0 < x" if strict else "0 <= x"
    return (
        f"{_deriv_eq(case.poly, name)}이므로 방정식 {name}'(x) = 0의 근은 x = {root}, x = {a}이고, "
        f"음수인 x = {with_eun_neun(root)} 범위 {dom} 밖에 있다. {dom}에서 {other} > 0이므로 "
        f"{name}'(x)의 부호는 {_lin(a)}의 부호와 같다. 따라서 {name}(x)는 {left} <= {a}에서 "
        f"감소하고 x >= {a}에서 증가하여 x = {a}에서 최솟값 {name}({a}) = 0을 갖는다."
    )


def _ineq_of(q: tuple[object, ...]) -> _Ineq:
    case = q[0]
    assert isinstance(case, _Ineq)
    return case


def _all_real_tail(a: int, name: str = "f") -> str:
    return f" 그러므로 모든 실수 x에 대하여 {name}(x) >= 0이고, 등호는 x가 {a}일 때만 성립한다."


def _domain_tail(a: int, name: str = "f") -> str:
    return f" 그러므로 x >= 0에서 {name}(x) >= 0이고, 등호는 x가 {a}일 때만 성립한다."


def _v_line_split(case: _Ineq) -> tuple[Poly, Poly]:
    """f = g - h — g는 2차 이상 항(곡선), h는 기울기가 양수인 직선."""
    split = _split_line(case.poly)
    assert split is not None  # a < 2s이면 일차항 계수 La(a - 2s)가 0이 아니다
    return split


def _v_curve_split(case: _Ineq, *, odd: bool) -> tuple[Poly, Poly] | None:
    """f = g1 - g2 — 두 곡선(삼차 대 이차). 이차 곡선의 최고차 계수가 양수인 사례(s < 2a)만.

    odd=False: g1 = Lx^3 + (상수항), g2 = -(이차항 + 일차항).
    odd=True:  g1 = Lx^3 + (일차항), g2 = -(이차항 + 상수항).
    """
    terms = dict(case.poly)
    if terms.get(2, 0) >= 0:
        return None
    keep = (3, 1) if odd else (3, 0)
    g1 = tuple((e, c) for e, c in case.poly if e in keep)
    g2 = tuple((e, -c) for e, c in case.poly if e not in keep)
    return g1, g2


# ──────────────────────────────────────────────────────────────────────────
# 극값 증인(witness) — 극댓값 M, 극솟값 m만 주어진 삼차함수
# ──────────────────────────────────────────────────────────────────────────
def _witness(m_max: int, m_min: int) -> Poly:
    """x = 0에서 극댓값 M, x = 1에서 극솟값 m을 갖는 대표 삼차함수 (M - m)(2x^3 - 3x^2) + M."""
    return _poly((m_max - m_min) * (2 * _X**3 - 3 * _X**2) + m_max)


def _witness_body(m_max: int, m_min: int, k: int) -> tuple[str, int]:
    head = (
        "최고차항의 계수가 양수인 삼차함수 y = f(x)의 그래프는 증가하다가 극댓값 "
        f"{m_max}에서 감소로 바뀌고, 극솟값 {m_min}에서 다시 증가한다. 방정식 f(x) = {k}의 실근의 "
        f"개수는 이 그래프와 직선 y = {k}의 교점의 개수이다. "
    )
    line = with_eun_neun(f"직선 y = {k}")
    if m_min < k < m_max:
        body = (
            f"{with_eun_neun(k)} 극솟값 {m_min}보다 크고 극댓값 {m_max}보다 작으므로 직선은 "
            "증가·감소·"
            "증가하는 세 구간에서 한 번씩 그래프와 만난다."
        )
        n = 3
    elif k == m_max:
        body = (
            f"{line} 극댓값을 갖는 점에서 그래프에 접하고, 극솟값을 지난 뒤 증가하는 구간에서 한 "
            "번 더 "
            "만난다."
        )
        n = 2
    elif k == m_min:
        body = (
            f"{line} 극솟값을 갖는 점에서 그래프에 접하고, 극댓값에 이르기 전 증가하는 구간에서 한 "
            "번 더 "
            "만난다."
        )
        n = 2
    elif k > m_max:
        body = (
            f"{with_eun_neun(k)} 극댓값 {m_max}보다 크므로 직선은 극솟값을 지난 뒤 증가하는 "
            "구간에서만 "
            "한 번 만난다."
        )
        n = 1
    else:
        body = (
            f"{with_eun_neun(k)} 극솟값 {m_min}보다 작으므로 직선은 극댓값에 이르기 전 증가하는 "
            "구간에서만 한 번 만난다."
        )
        n = 1
    return head + body + f" 따라서 서로 다른 실근은 {n}개이다.", n


def _witness_pairs() -> tuple[tuple[object, ...], ...]:
    pairs = [(mx, mn) for mx in range(-3, 6) for mn in range(-5, mx)]
    return tuple(seeded_order("p3-eq:witness0", tuple(pairs)))


def _witness_triples() -> tuple[tuple[object, ...], ...]:
    triples: list[tuple[int, int, int]] = []
    for mx in range(-2, 6):
        for mn in range(-4, mx):
            mid = (mx + mn) // 2
            levels = {mx, mn, mx + 2, mn - 2} | ({mid} if mn < mid < mx else set())
            triples.extend((mx, mn, k) for k in sorted(levels) if k != 0)
    return tuple(seeded_order("p3-eq:witnessk", tuple(triples)))


def _ints(q: tuple[object, ...]) -> tuple[int, ...]:
    out = []
    for value in q:
        assert isinstance(value, int)
        out.append(value)
    return tuple(out)


def _p_of(x: object) -> _P:
    assert isinstance(x, _P)
    return x


def _level_of(x: object) -> _Level:
    assert isinstance(x, _Level)
    return x


# ──────────────────────────────────────────────────────────────────────────
# 대표(representative)
# ──────────────────────────────────────────────────────────────────────────
def _rep_frames() -> list[Frame]:
    def r8(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        p = render_poly(case.poly)
        return _value_item(
            slot="representative",
            frame_id="rep-inequality-equality-nonnegative-domain",
            text=(f"x >= 0일 때 부등식 {p} >= 0이 성립한다. 등호가 성립하는 x의 값을 구하시오."),
            cond=(_eq_cond(case.poly, 0), "x >= 0"),
            value=case.a,
            explanation=(
                _define("f", case.poly) + _v_story(case, strict=False) + _domain_tail(case.a)
            ),
        )

    def r9(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        g, h = _v_line_split(case)
        gt, ht = render_poly(g), render_poly(h)
        return _value_item(
            slot="representative",
            frame_id="rep-inequality-curve-over-line",
            text=(
                f"x > 0에서 부등식 {gt} >= {with_i_ga(ht)} 성립한다. 등호가 성립하는 x의 값을 "
                "구하시오."
            ),
            cond=(_eq_cond(g, h), "x > 0"),
            value=case.a,
            explanation=(
                f"두 변의 차를 f(x) = {_diff_text(gt, ht)} = {with_ira(render_poly(case.poly))} "
                "하자. "
                + _v_story(case, strict=True)
                + f" 그러므로 x > 0에서 f(x) >= 0이고, 등호는 x = {case.a}일 때만 성립한다."
            ),
        )

    def r10(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        return _value_item(
            slot="representative",
            frame_id="rep-quartic-inequality-equality",
            text=(
                f"모든 실수 x에 대하여 부등식 {render_poly(case.poly)} >= 0이 성립한다. 등호가 "
                "성립하는 실수 x의 값을 구하시오."
            ),
            cond=_eq_cond(case.poly, 0),
            value=case.a,
            explanation=_define("f", case.poly) + _c1_story(case) + _all_real_tail(case.a),
        )

    def r1(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        body, n = _factor_body(p)
        return _count_item(
            slot="representative",
            frame_id="rep-count-real-roots-of-equation",
            text=f"방정식 {render_poly(p.poly)} = 0의 서로 다른 실근의 개수를 구하시오.",
            cond=_eq_cond(p.poly, 0),
            poly=p.poly,
            explanation=f"{body} 따라서 서로 다른 실근은 {n}개이다.",
            count=n,
        )

    def r4(q: tuple[object, ...]) -> DiffItem | None:
        level = _level_of(q[0])
        g = render_poly(level.poly)
        body, n = _level_body(level)
        return _count_item(
            slot="representative",
            frame_id="rep-curve-meets-horizontal-line",
            text=(
                f"곡선 y = {g}{wa_gwa(g)} 직선 y = {with_i_ga(level.k)} 만나는 서로 다른 점의 "
                "개수를 구하시오."
            ),
            cond=_eq_cond(level.poly, level.k),
            poly=_minus(level.poly, level.k),
            explanation=(
                _define("f", level.poly)
                + f"교점의 x좌표는 방정식 f(x) = {level.k}의 실근이다. "
                + body
                + f" 따라서 곡선과 직선은 서로 다른 {n}개의 점에서 만난다."
            ),
            count=n,
        )

    return [
        Frame("rep-inequality-equality-nonnegative-domain", _part("p3-eq:v", _v_cases(), 0, 9), r8),
        Frame("rep-quartic-inequality-equality", _part("p3-eq:c1", _c1_cases(), 0, 3), r10),
        Frame("rep-count-real-roots-of-equation", _part("p3-eq:cubic", _cubics(), 0, 4), r1),
        Frame("rep-inequality-curve-over-line", _part("p3-eq:v", _v_cases(), 1, 9), r9),
        Frame("rep-curve-meets-horizontal-line", _part("p3-eq:lv3", _cubic_levels(), 0, 2), r4),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 기본(basic)
# ──────────────────────────────────────────────────────────────────────────
def _basic_frames() -> list[Frame]:
    def b12(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        lhs = tuple((e, c) for e, c in case.poly if e != 1)
        rhs = tuple((e, -c) for e, c in case.poly if e == 1)
        lt, rt = render_poly(lhs), render_poly(rhs)
        return _value_item(
            slot="basic",
            frame_id="basic-quartic-inequality-two-sides-equal",
            text=(
                f"부등식 {lt} >= {with_i_ga(rt)} 모든 실수 x에 대하여 성립함을 보이려 한다. 두 "
                "변의 "
                "값이 같아지는 x의 값을 구하시오."
            ),
            cond=_eq_cond(lhs, rhs),
            value=case.a,
            explanation=(
                f"두 변의 차를 f(x) = {_diff_text(lt, rt)} = {with_ira(render_poly(case.poly))} "
                "하자. "
                + _c1_story(case)
                + " 그러므로 f(x) >= 0이어서 부등식이 성립하고, 두 변이 같아지는 것은 "
                f"x가 {case.a}일 때뿐이다."
            ),
        )

    def b13(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        return _value_item(
            slot="basic",
            frame_id="basic-quartic-left-side-zero",
            text=(
                f"모든 실수 x에 대하여 {render_poly(case.poly)} >= 0이다. 좌변이 0이 되는 실수 x의 "
                "값을 구하시오."
            ),
            cond=_eq_cond(case.poly, 0),
            value=case.a,
            explanation=_define("f", case.poly) + _c2_story(case) + _all_real_tail(case.a),
        )

    def b14(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        split = _v_curve_split(case, odd=False)
        if split is None:
            return None
        g1, g2 = split
        t1, t2 = render_poly(g1), render_poly(g2)
        return _value_item(
            slot="basic",
            frame_id="basic-cubic-curve-not-below-parabola",
            text=(
                f"x > 0에서 곡선 y = {with_eun_neun(t1)} 곡선 y = {t2}보다 아래쪽에 있지 않다. 두 "
                "곡선이 "
                "만나는 점의 x좌표를 구하시오."
            ),
            cond=(_eq_cond(g1, g2), "x > 0"),
            value=case.a,
            explanation=(
                f"두 식의 차를 f(x) = {_diff_text(t1, t2)} = {with_ira(render_poly(case.poly))} "
                "하자. "
                + _v_story(case, strict=True)
                + " 그러므로 x > 0에서 f(x) >= 0, 즉 첫째 곡선은 둘째 곡선보다 아래에 있지 않고 두 "
                f"곡선은 x = {case.a}에서만 만난다."
            ),
        )

    def b1(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        body, n = _factor_body(p, lead_in="f(x)를 ")
        return _count_item(
            slot="basic",
            frame_id="basic-quartic-function-zero-count",
            text=(
                f"사차함수 f(x) = {render_poly(p.poly)}에 대하여 방정식 f(x) = 0을 만족시키는 "
                "서로 다른 실수 x의 개수를 구하시오."
            ),
            cond=_eq_cond(p.poly, 0),
            poly=p.poly,
            explanation=f"{body} 따라서 서로 다른 실수 x는 {n}개이다.",
            count=n,
        )

    def b11(q: tuple[object, ...]) -> DiffItem | None:
        level = _level_of(q[0])
        body, n = _level_body(level)
        return _count_item(
            slot="basic",
            frame_id="basic-cubic-equation-level-count",
            text=(
                f"방정식 {render_poly(level.poly)} = {level.k}의 서로 다른 실근의 개수를 "
                "구하시오."
            ),
            cond=_eq_cond(level.poly, level.k),
            poly=_minus(level.poly, level.k),
            explanation=(
                _define("f", level.poly)
                + f"방정식 f(x) = {level.k}의 실근의 개수는 곡선 y = f(x)와 직선 y = {level.k}의 "
                "교점의 개수와 같다. " + body + f" 따라서 서로 다른 실근은 {n}개이다."
            ),
            count=n,
        )

    return [
        Frame(
            "basic-quartic-inequality-two-sides-equal", _part("p3-eq:c1", _c1_cases(), 1, 3), b12
        ),
        Frame("basic-quartic-left-side-zero", _part("p3-eq:c2", _c2_cases(), 0, 3), b13),
        Frame("basic-quartic-function-zero-count", _part("p3-eq:quartic", _quartics(), 0, 5), b1),
        Frame("basic-cubic-curve-not-below-parabola", _part("p3-eq:v", _v_cases(), 2, 9), b14),
        Frame("basic-cubic-equation-level-count", _part("p3-eq:lv3", _cubic_levels(), 1, 2), b11),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 응용(applied)
# ──────────────────────────────────────────────────────────────────────────
def _applied_frames() -> list[Frame]:
    def a1(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        return _value_item(
            slot="applied",
            frame_id="applied-inequality-single-point-domain",
            text=(
                f"x가 0 이상의 실수일 때, 부등식 {render_poly(case.poly)} <= 0을 만족시키는 x의 "
                "값을 구하시오."
            ),
            cond=(f"{poly_to_sympy_str(case.poly)} <= 0", "x >= 0"),
            value=case.a,
            explanation=(
                _define("f", case.poly)
                + _v_story(case, strict=False)
                + " 그러므로 x >= 0에서 f(x) >= 0이어서 f(x) <= 0이 되는 것은 f(x) = 0일 때뿐이고, "
                f"그때 x = {case.a}이다."
            ),
        )

    def a6(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        return _value_item(
            slot="applied",
            frame_id="applied-quartic-show-nonnegative",
            text=(
                f"함수 f(x) = {render_poly(case.poly)}에 대하여 모든 실수 x에서 f(x) >= 0임을 "
                "보이려 "
                "한다. f(x) = 0을 만족시키는 실수 x의 값을 구하시오."
            ),
            cond=_eq_cond(case.poly, 0),
            value=case.a,
            explanation=_c1_story(case) + _all_real_tail(case.a),
        )

    def a7(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        g, h = _v_line_split(case)
        gt, ht = render_poly(g), render_poly(h)
        return _value_item(
            slot="applied",
            frame_id="applied-curve-not-below-line",
            text=(
                f"x > 0에서 곡선 y = {with_eun_neun(gt)} 직선 y = {ht}보다 아래쪽에 있지 않다. "
                "곡선과 "
                "직선이 만나는 점의 x좌표를 구하시오."
            ),
            cond=(_eq_cond(g, h), "x > 0"),
            value=case.a,
            explanation=(
                f"두 식의 차를 f(x) = {_diff_text(gt, ht)} = {with_ira(render_poly(case.poly))} "
                "하자. "
                + _v_story(case, strict=True)
                + " 그러므로 x > 0에서 f(x) >= 0, 즉 곡선은 직선보다 아래에 있지 않고 두 그래프는 "
                f"x = {case.a}에서만 만난다(접한다)."
            ),
        )

    def a2(q: tuple[object, ...]) -> DiffItem | None:
        level = _level_of(q[0])
        body, n = _level_body(level, name="x", var="t", lower=0)
        return _count_item(
            slot="applied",
            frame_id="applied-moving-point-position-count",
            text=(
                "수직선 위를 움직이는 점 P의 시각 t (t >= 0)에서의 위치가 "
                f"x(t) = {render_poly(level.poly, 't')}이다. 점 P의 위치가 {with_i_ga(level.k)} "
                "되는 "
                "서로 다른 시각의 개수를 구하시오."
            ),
            cond=_eq_cond(level.poly, level.k, "t"),
            poly=_minus(level.poly, level.k),
            explanation=(
                f"위치가 {with_i_ga(level.k)} 되는 시각은 방정식 x(t) = {level.k}의 0 이상인 "
                "실근이다. " + body + f" 따라서 위치가 {with_i_ga(level.k)} 되는 시각은 {n}개이다."
            ),
            count=n,
        )

    def a3(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_curves(p.poly)
        if split is None:
            return None
        g, h = split
        body, n = _factor_body(p, lead_in="좌변을 ", touch=True)
        return _count_item(
            slot="applied",
            frame_id="applied-two-curves-intersections",
            text=(
                f"두 곡선 y = {render_poly(g)}, y = {render_poly(h)}의 서로 다른 교점의 개수를 "
                "구하시오."
            ),
            cond=_eq_cond(g, h),
            poly=p.poly,
            explanation=(
                "교점의 x좌표는 두 식을 같게 놓은 방정식의 실근이고, 정리하면 "
                f"{render_poly(p.poly)} = "
                f"0이다. {body} 따라서 서로 다른 교점은 {n}개이다."
            ),
            count=n,
        )

    return [
        Frame("applied-inequality-single-point-domain", _part("p3-eq:v", _v_cases(), 3, 9), a1),
        Frame("applied-quartic-show-nonnegative", _part("p3-eq:c1", _c1_cases(), 2, 3), a6),
        Frame("applied-moving-point-position-count", _part("p3-eq:mv", _motion_levels(), 0, 1), a2),
        Frame("applied-curve-not-below-line", _part("p3-eq:v", _v_cases(), 4, 9), a7),
        Frame("applied-two-curves-intersections", _part("p3-eq:quartic", _quartics(), 1, 5), a3),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 오개념 유발(misconception_trigger) — f(x) = k의 근의 개수를 y = k와의 교점으로 못 본다(M0677)
# ──────────────────────────────────────────────────────────────────────────
def _crit_count(poly: Poly) -> int:
    """f'(x) = 0의 서로 다른 실근 수 — '극값 후보의 개수'를 근의 개수로 오인한 값."""
    return _n_distinct(derivative_of(poly))


def _mc_count(
    *,
    frame_id: str,
    text: str,
    cond: str,
    p: _P,
    seed: str,
    lead_in: str,
    touch: bool = False,
) -> DiffItem | None:
    """실근 개수 객관식 — 차수·극값 후보 수로 답한 값(M0677)을 오답 선지에 둔다.

    해설은 인수·중근·허근 인수를 보인 뒤 *오답이 왜 틀렸는지*(차수를 그대로 셈·도함수의 근을
    셈)를 오답 선지마다 한 문장씩 설명한다(2차 감사: 결론만 적은 해설은 오답을 고른 학생을 교정하지
    못한다).
    """
    body, correct = _factor_body(p, lead_in=lead_in, touch=touch)
    degree = p.degree
    crit = _crit_count(p.poly)
    wrong = [v for v in dict.fromkeys((degree, crit)) if v != correct]
    if not wrong:
        return None
    entries = [ChoiceEntry(str(correct), is_correct=True, sort_key=float(correct))]
    taken = {correct}
    for v in wrong:
        entries.append(ChoiceEntry(str(v), _MID, sort_key=float(v)))
        taken.add(v)
    for v in seeded_order(seed, tuple(range(0, 5))):
        if len(entries) == 4:
            break
        if v not in taken:
            entries.append(ChoiceEntry(str(v), sort_key=float(v)))
            taken.add(v)
    if len(entries) != 4:
        return None
    try:
        choices, answer, distractors = build_choices(entries, shuffle_seed=seed)
    except ValueError:
        return None
    traps: list[str] = []
    if degree in wrong:
        traps.append(
            f"차수 {with_eul_reul(degree)} 그대로 실근의 개수로 세면 중근을 두 번 세거나 허근까지 "
            "세게 "
            "된다."
        )
    if crit in wrong:
        traps.append(
            f"도함수가 0이 되는 서로 다른 x의 개수 {with_eun_neun(crit)} 극값 후보를 센 값일 뿐 "
            "실근의 개수가 아니다."
        )
    return _count_item(
        slot="misconception_trigger",
        frame_id=frame_id,
        text=text,
        cond=cond,
        poly=p.poly,
        explanation=f"{body} {' '.join(traps)} 따라서 서로 다른 실근은 {correct}개이다.",
        count=int(answer),
        choices=choices,
        distractors=distractors,
    )


def _misconception_frames() -> list[Frame]:
    def m1(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        return _mc_count(
            frame_id="mc-count-real-roots",
            text=f"방정식 {render_poly(p.poly)} = 0의 서로 다른 실근의 개수로 옳은 것은?",
            cond=_eq_cond(p.poly, 0),
            p=p,
            seed=f"mc1:{p.poly}",
            lead_in="좌변을 ",
        )

    def m2(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_const(p.poly)
        if split is None:
            return None
        g, k = split
        gt = render_poly(g)
        return _mc_count(
            frame_id="mc-curve-and-horizontal-line",
            text=f"곡선 y = {gt}{wa_gwa(gt)} 직선 y = {k}의 교점의 개수로 옳은 것은?",
            cond=f"{poly_to_sympy_str(g)} = {k}",
            p=p,
            seed=f"mc2:{p.poly}",
            lead_in=f"교점의 x좌표는 방정식 {gt} = {k}의 실근이다. 이 방정식을 정리하여 ",
            touch=True,
        )

    def m3(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_const(p.poly)
        if split is None:
            return None
        g, k = split
        return _mc_count(
            frame_id="mc-equation-fx-equals-k",
            text=(
                f"함수 f(x) = {render_poly(g)}에 대하여 방정식 f(x) = {k}의 서로 다른 실근의 "
                "개수는?"
            ),
            cond=f"{poly_to_sympy_str(g)} = {k}",
            p=p,
            seed=f"mc3:{p.poly}",
            lead_in=f"방정식 f(x) = {with_eul_reul(k)} 정리하여 ",
        )

    def m4(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        return _mc_count(
            frame_id="mc-graph-meets-x-axis",
            text=f"함수 y = {render_poly(p.poly)}의 그래프가 x축과 만나는 점의 개수는?",
            cond=_eq_cond(p.poly, 0),
            p=p,
            seed=f"mc4:{p.poly}",
            lead_in=(
                f"x축과 만나는 점의 x좌표는 방정식 {render_poly(p.poly)} = 0의 실근이다. 좌변을 "
            ),
            touch=True,
        )

    def m5(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_curves(p.poly)
        if split is None:
            return None
        g, h = split
        return _mc_count(
            frame_id="mc-two-curves-intersections",
            text=(
                f"두 곡선 y = {render_poly(g)}, y = {render_poly(h)}의 교점의 개수로 옳은 " "것은?"
            ),
            cond=_eq_cond(g, h),
            p=p,
            seed=f"mc5:{p.poly}",
            lead_in=(
                f"교점의 x좌표는 두 식을 같게 놓은 방정식 {render_poly(p.poly)} = 0의 실근이다. "
                "좌변을 "
            ),
            touch=True,
        )

    return [
        Frame("mc-count-real-roots", _part("p3-eq:cubic", _cubics(), 1, 4), m1),
        Frame("mc-curve-and-horizontal-line", _part("p3-eq:cubic", _cubics(), 2, 4), m2),
        Frame("mc-equation-fx-equals-k", _part("p3-eq:quartic", _quartics(), 2, 5), m3),
        Frame("mc-graph-meets-x-axis", _part("p3-eq:quartic", _quartics(), 3, 5), m4),
        Frame("mc-two-curves-intersections", _part("p3-eq:quartic", _quartics(), 4, 5), m5),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 진단(diagnostic) — 단계 하나씩(극값만으로 개수 세기 · 등호 조건 · 엄격 부등식의 실패점)
# ──────────────────────────────────────────────────────────────────────────
def _diagnostic_frames() -> list[Frame]:
    def d13(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        return _value_item(
            slot="diagnostic",
            frame_id="diag-quartic-equality-case",
            text=(
                f"부등식 {render_poly(case.poly)} >= 0은 모든 실수 x에 대하여 성립한다. 등호가 "
                "성립하는 x의 값을 구하시오."
            ),
            cond=_eq_cond(case.poly, 0),
            value=case.a,
            explanation=_define("f", case.poly) + _c2_story(case) + _all_real_tail(case.a),
        )

    def d14(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        return _value_item(
            slot="diagnostic",
            frame_id="diag-strict-inequality-fails",
            text=(
                f"x >= 0일 때, 부등식 {render_poly(case.poly)} > 0이 성립하지 않는 x의 값을 "
                "구하시오."
            ),
            cond=(f"{poly_to_sympy_str(case.poly)} <= 0", "x >= 0"),
            value=case.a,
            explanation=(
                _define("f", case.poly)
                + _v_story(case, strict=False)
                + " 그러므로 x >= 0에서 f(x) >= 0이고, f(x) > 0이 성립하지 않는 것은 f(x) = 0인 "
                f"x = {case.a}일 때뿐이다."
            ),
        )

    def d11(q: tuple[object, ...]) -> DiffItem | None:
        mx, mn = _ints(q)
        fw = _witness(mx, mn)
        body, n = _witness_body(mx, mn, 0)
        return _count_item(
            slot="diagnostic",
            frame_id="diag-count-from-extremum-values",
            text=(
                f"최고차항의 계수가 양수인 삼차함수 f(x)의 극댓값이 {mx}, 극솟값이 {mn}이다. "
                "방정식 f(x) = 0의 서로 다른 실근의 개수를 구하시오."
            ),
            cond=_eq_cond(fw, 0),
            poly=fw,
            explanation=body,
            count=n,
        )

    def d15(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        split = _v_curve_split(case, odd=True)
        if split is None:
            return None
        g1, g2 = split
        t1, t2 = render_poly(g1), render_poly(g2)
        return _value_item(
            slot="diagnostic",
            frame_id="diag-cubic-value-not-smaller",
            text=(
                f"x > 0일 때 {t1}의 값은 {t2}의 값보다 작지 않다. 두 값이 같아지는 x의 값을 "
                "구하시오."
            ),
            cond=(_eq_cond(g1, g2), "x > 0"),
            value=case.a,
            explanation=(
                f"두 식의 차를 f(x) = {_diff_text(t1, t2)} = {with_ira(render_poly(case.poly))} "
                "하자. "
                + _v_story(case, strict=True)
                + f" 그러므로 x > 0에서 f(x) >= 0이고, 두 값이 같아지는 것은 x = {case.a}일 "
                "때뿐이다."
            ),
        )

    def d12(q: tuple[object, ...]) -> DiffItem | None:
        mx, mn, k = _ints(q)
        fw = _witness(mx, mn)
        body, n = _witness_body(mx, mn, k)
        return _count_item(
            slot="diagnostic",
            frame_id="diag-count-level-from-extremum-values",
            text=(
                f"최고차항의 계수가 양수인 삼차함수 f(x)는 극댓값 {with_wa_gwa(mx)} 극솟값 "
                f"{with_eul_reul(mn)} 갖는다. 방정식 f(x) = {k}의 서로 다른 실근의 개수를 구하시오."
            ),
            cond=_eq_cond(fw, k),
            poly=_minus(fw, k),
            explanation=body,
            count=n,
        )

    return [
        Frame("diag-quartic-equality-case", _part("p3-eq:c2", _c2_cases(), 1, 3), d13),
        Frame("diag-strict-inequality-fails", _part("p3-eq:v", _v_cases(), 5, 9), d14),
        Frame("diag-count-from-extremum-values", _witness_pairs(), d11),
        Frame("diag-cubic-value-not-smaller", _part("p3-eq:v", _v_cases(), 6, 9), d15),
        Frame("diag-count-level-from-extremum-values", _witness_triples(), d12),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 숙련도 확인(mastery_check)
# ──────────────────────────────────────────────────────────────────────────
def _mastery_frames() -> list[Frame]:
    def k3(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        return _value_item(
            slot="mastery_check",
            frame_id="mastery-equality-in-domain",
            text=(
                f"x >= 0에서 부등식 {render_poly(case.poly)} >= 0이 성립함을 보이려 한다. "
                "이때 x >= 0에서 등호가 성립하는 x의 값을 구하시오."
            ),
            cond=(_eq_cond(case.poly, 0), "x >= 0"),
            value=case.a,
            explanation=(
                _define("f", case.poly) + _v_story(case, strict=False) + _domain_tail(case.a)
            ),
        )

    def k8(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        lhs = tuple((e, c) for e, c in case.poly if e != 3)
        rhs = tuple((e, -c) for e, c in case.poly if e == 3)
        lt, rt = render_poly(lhs), render_poly(rhs)
        return _value_item(
            slot="mastery_check",
            frame_id="mastery-quartic-not-smaller-than-cubic",
            text=(
                f"모든 실수 x에 대하여 {with_eun_neun(lt)} {rt}보다 작지 않다. 두 식의 값이 "
                "같아지는 "
                "x의 값을 구하시오."
            ),
            cond=_eq_cond(lhs, rhs),
            value=case.a,
            explanation=(
                f"두 식의 차를 f(x) = {_diff_text(lt, rt)} = {with_ira(render_poly(case.poly))} "
                "하자. "
                + _c2_story(case)
                + f" 그러므로 f(x) >= 0이고, 두 식의 값이 같아지는 것은 x가 {case.a}일 때뿐이다."
            ),
        )

    def k6(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_line(p.poly)
        if split is None or len(p.distinct_roots) != 2 or p.quad is not None:
            return None
        g, h = split
        ht = render_poly(h)
        body, n = _factor_body(p, lead_in="좌변을 ", touch=True)
        return _count_item(
            slot="mastery_check",
            frame_id="mastery-tangent-line-intersection-count",
            text=(
                f"직선 y = {with_eun_neun(ht)} 곡선 y = {render_poly(g)}에 접하는 점을 갖는다. "
                "이 직선과 곡선이 만나는 서로 다른 점의 개수를 구하시오."
            ),
            cond=_eq_cond(g, h),
            poly=p.poly,
            explanation=(
                f"교점의 x좌표는 방정식 {render_poly(g)} = {ht}, 즉 {render_poly(p.poly)} = 0의 "
                f"실근이다. {body} 따라서 직선과 곡선은 서로 다른 {n}개의 점에서 만난다."
            ),
            count=n,
        )

    def k9(q: tuple[object, ...]) -> DiffItem | None:
        case = _ineq_of(q)
        split = _v_curve_split(case, odd=False)
        if split is None:
            return None
        g1, g2 = split
        return _value_item(
            slot="mastery_check",
            frame_id="mastery-two-functions-equal-at-positive-x",
            text=(
                f"두 함수 f(x) = {render_poly(g1)}, g(x) = {render_poly(g2)}에 대하여 x > 0에서 "
                "f(x) >= g(x)가 성립한다. f(x) = g(x)를 만족시키는 양수 x의 값을 구하시오."
            ),
            cond=(_eq_cond(g1, g2), "x > 0"),
            value=case.a,
            explanation=(
                f"h(x) = f(x) - g(x) = {with_ira(render_poly(case.poly))} 하자. "
                + _v_story(case, strict=True, name="h")
                + f" 그러므로 x > 0에서 h(x) >= 0이고, h(x) = 0인 양수 x는 {case.a}뿐이다."
            ),
        )

    def k10(q: tuple[object, ...]) -> DiffItem | None:
        level = _level_of(q[0])
        body, n = _level_body(level)
        return _count_item(
            slot="mastery_check",
            frame_id="mastery-quartic-level-count",
            text=(
                f"사차함수 f(x) = {render_poly(level.poly)}에 대하여 방정식 f(x) = {level.k}의 "
                "서로 다른 실근의 개수를 구하시오."
            ),
            cond=_eq_cond(level.poly, level.k),
            poly=_minus(level.poly, level.k),
            explanation=(
                f"방정식 f(x) = {level.k}의 실근은 곡선 y = f(x)와 직선 y = {level.k}의 교점의 "
                f"x좌표이다. {body} 따라서 서로 다른 실근은 {n}개이다."
            ),
            count=n,
        )

    return [
        Frame("mastery-equality-in-domain", _part("p3-eq:v", _v_cases(), 7, 9), k3),
        Frame("mastery-quartic-not-smaller-than-cubic", _part("p3-eq:c2", _c2_cases(), 2, 3), k8),
        Frame("mastery-tangent-line-intersection-count", _part("p3-eq:cubic", _cubics(), 3, 4), k6),
        Frame("mastery-two-functions-equal-at-positive-x", _part("p3-eq:v", _v_cases(), 8, 9), k9),
        Frame("mastery-quartic-level-count", _part("p3-eq:lv4", _quartic_levels(), 0, 1), k10),
    ]


_SLOT_FRAMES = {
    "representative": _rep_frames,
    "basic": _basic_frames,
    "applied": _applied_frames,
    "misconception_trigger": _misconception_frames,
    "diagnostic": _diagnostic_frames,
    "mastery_check": _mastery_frames,
}


class P3DiffEquationApplicationGenerator(P3DiffSlotGenerator):
    """[12미적Ⅰ-02-09] 방정식과 부등식에의 활용(수치형) — 슬롯 6종 결정론 생성기."""

    standard_code: ClassVar[str] = "[12미적Ⅰ-02-09]"
    concept_src_id: ClassVar[str] = "H:12미적Ⅰ02-09"
    unit_code: ClassVar[str] = "P3-CALC1-DIFF-EQUATION-APPLICATION"
    slug_prefix: ClassVar[str] = "wm-p3-diff-eqapp"
    slot_difficulty: ClassVar[dict[str, float]] = {
        "representative": 2.5,
        "basic": 2.5,
        "applied": 3.5,
        "misconception_trigger": 3.0,
        "diagnostic": 2.5,
        "mastery_check": 4.0,
    }
    slot_count: ClassVar[int] = 12

    @classmethod
    def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
        return round_robin_items(_SLOT_FRAMES[slot](), cls.slot_count, claimed=claimed)

    def _assemble(self, spec: EquivalenceSpec, item: DiffItem) -> CandidateProblem:
        return with_item_kinds(super()._assemble(spec, item), item)
