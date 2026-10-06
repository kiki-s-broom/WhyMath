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
계수가 전부 숫자이고 답이 숫자 하나인 수치형이다:

  · 서로 다른 실근의 개수(`answer_kind=real_root_count`) — 방정식·곡선과 직선·두 곡선의 교점
  · 근의 합·곱(`answer_aggregate`) — 문면에 "중근은 중복하여 센다"를 명시(검증기가 중근을
    중복 포함으로 계산하므로 "서로 다른 근들의 합"은 위장이 된다 — P3-20 X1). 교점의 x좌표의
    합은 교점이 서로 다른 단순근인 경우만 낸다(중복도가 없어 두 해석이 같다).
  · 근의 선택(`answer_selection`) — 가장 큰/작은 실근, 구간·부호 조건으로 유일해진 근
  · 부등식 활용 — 해집합이 한 점으로 줄어드는 형태(완전제곱 인수·정의역 제한)로 *유일한 x*를 묻는다
    (P3-20 S6은 한 점만 보는 한계가 있어, 해가 한 점뿐이라 그 한계가 닿지 않는 형태만 쓴다).

P3-20 §3 지침 두 가지를 지킨다: ① 실근 개수형을 한 슬롯에 몰아 쓰지 않는다 — 슬롯마다 개수형은
최대 2틀이고 나머지는 합·선택·부등식 형태다(문면 골격이 겹치지 않게 틀마다 문장을 다르게 쓴다)
② 근의 합 문면은 항상 "(단, 중근은 중복하여 센다.)"를 명시한다.

교점 문항을 방정식으로 환원하는 일(곡선 = 직선 → g - h = 0)은 생성기가 SymPy로 한 번에 하며
(작성자 책임 — P3-20 §4-3), 개수는 `Poly.sqf_part().count_roots()`로 검산 경로와 *독립*으로 센다.

문제유형 정직성
--------------
실근 개수를 묻는 문항은 `ptype.count-solutions`, 합·선택·유일한 값은 `ptype.solve-for-unknown`이다.
이 개념의 명세 스킬(`case-analysis`·`word-problem-modeling`)과 겹치는 유형은 `count-solutions`
(case-analysis)뿐이다. `word-problem-modeling`과 겹치는 유형(`optimize-extremum` 등)의 문항은 이
개념의 수치형 검산 경로가 없어 만들지 않았다 — 거짓 유형으로 맞추지 않았다.

게이트 재료 확장: `KindedDiffItem`(`p3_diff_mean_value_theorem_skeleton_generator`)을 쓰고
`_assemble`에서 `with_item_kinds`로 후보에 싣는다(base 모듈 무수정).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from typing import ClassVar, Final

import sympy

from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.p3_diff_expr import (
    Poly,
    derivative_of,
    poly_from_sympy,
    poly_to_sympy,
    poly_to_sympy_str,
    render_poly,
)
from whymath_backend.l3.equivalent.p3_diff_mean_value_theorem_skeleton_generator import (
    KindedDiffItem,
    answer_format_of,
    frac_text,
    with_item_kinds,
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

__all__ = ["P3DiffEquationApplicationGenerator"]

#: 오개념 id — M-id 그대로(kebab 좌석 없음. 모듈 docstring 참조).
_MID: Final = "M0677"
_SOLVE: Final = "ptype.solve-for-unknown"
_COUNT: Final = "ptype.count-solutions"
_KIND: Final = "real_root_count"
_SUM_NOTE: Final = "(단, 중근은 중복하여 센다.)"
_X = sympy.Symbol("x")


# ──────────────────────────────────────────────────────────────────────────
# 다항식 풀 — 인수분해된 형태에서 만든다(근을 정확히 알고, 검산 경로가 끝까지 풀 수 있다)
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
    def degree(self) -> int:
        return self.poly[0][0]


def _expand(lead: int, roots: Sequence[int], quad: tuple[int, int] | None = None) -> Poly:
    expr: sympy.Expr = sympy.Integer(lead)
    for r in roots:
        expr = expr * (_X - r)
    if quad is not None:
        s, d = quad
        expr = expr * ((_X - s) ** 2 + d)
    return poly_from_sympy(sympy.expand(expr))


def _make(lead: int, roots: Sequence[int], quad: tuple[int, int] | None = None) -> _P:
    srt = tuple(sorted(roots))
    return _P(_expand(lead, srt, quad), lead, srt, quad)


def _n_distinct(poly: Poly) -> int:
    """서로 다른 실근 수 — 검산기와 독립인 경로(제곱 없는 부분의 Sturm 개수)."""
    return int(sympy.Poly(poly_to_sympy(poly), _X).sqf_part().count_roots())


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
def _cubics_real() -> tuple[_P, ...]:
    """삼차 중 근이 전부 실수(합·곱·선택 문항용)."""
    return tuple(p for p in _cubics() if p.quad is None)


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


@lru_cache(maxsize=None)
def _quartics_distinct4() -> tuple[_P, ...]:
    return tuple(p for p in _quartics() if p.quad is None and len(p.distinct_roots) == 4)


@lru_cache(maxsize=None)
def _quartics_real() -> tuple[_P, ...]:
    return tuple(p for p in _quartics() if p.quad is None)


@lru_cache(maxsize=None)
def _double_cubics() -> tuple[_P, ...]:
    """중근을 갖는 삼차(실근 2개) — 접하는 경우."""
    return tuple(p for p in _cubics_real() if len(p.distinct_roots) == 2)


@lru_cache(maxsize=None)
def _square_quartics() -> tuple[_P, ...]:
    """(x - a)^2(x^2 + d) — 실근이 a 하나뿐인 사차(부등식 `<= 0`이 한 점으로 줄어든다)."""
    out = [_make(1, (a, a), (0, d)) for a in range(-4, 5) for d in (1, 2, 3, 4)]
    out += [_make(1, (a, a), (s, d)) for a in range(-4, 5) for s in (-2, 2) for d in (1, 2)]
    return tuple(seeded_order("p3-eq:square4", tuple(out)))


@lru_cache(maxsize=None)
def _one_nonneg_cubics() -> tuple[_P, ...]:
    """(x - a)^2(x + s) (a, s > 0) — x >= 0에서 P <= 0 이면 x = a뿐."""
    return tuple(
        _make(lead, (a, a, -s))
        for lead in (1, 2)
        for a in range(1, 5)
        for s in range(1, 5)
        if a != s
    )


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


def _eq_cond(lhs: Poly, rhs: Poly | int, var: str = "x") -> str:
    right = str(rhs) if isinstance(rhs, int) else poly_to_sympy_str(rhs, var)
    return f"{poly_to_sympy_str(lhs, var)} = {right}"


def _factored_text(p: _P, var: str = "x") -> str:
    """해설용 인수분해 표기 — '(x - 1)^2(x + 2)'."""
    parts: list[str] = []
    if p.lead != 1:
        parts.append(str(p.lead))
    for r in p.distinct_roots:
        mult = p.roots.count(r)
        base = f"({var} - {r})" if r > 0 else (var if r == 0 else f"({var} + {-r})")
        parts.append(base if mult == 1 else f"{base}^{mult}")
    if p.quad is not None:
        s, d = p.quad
        inner = var if s == 0 else (f"({var} - {s})" if s > 0 else f"({var} + {-s})")
        parts.append(f"({inner}^2 + {d})" if s == 0 else f"({inner}^2 + {d})")
    return "".join(parts)


def _line_text(h: Poly) -> str:
    return render_poly(h)


def _p_of(x: object) -> _P:
    assert isinstance(x, _P)
    return x


def _params(seed: str, pool: Sequence[_P]) -> tuple[tuple[object, ...], ...]:
    return tuple((p,) for p in seeded_order(seed, tuple(pool)))


def _count_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    cond: str,
    poly: Poly,
    explanation: str,
    choices: tuple[str, ...] | None = None,
    distractors: tuple[tuple[int, str], ...] = (),
    answer: int | None = None,
) -> KindedDiffItem:
    n = _n_distinct(poly) if answer is None else answer
    return KindedDiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(n),
        explanation=explanation,
        conditions=cond,
        answer_map=(),
        problem_type_code=_COUNT,
        answer_format=AnswerFormat.자연수,
        choices=choices,
        distractors=distractors,
        answer_kind=_KIND,
    )


def _sum_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    cond: str,
    value: Fraction | int,
    explanation: str,
) -> KindedDiffItem:
    return KindedDiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=frac_text(value),
        explanation=explanation,
        conditions=cond,
        answer_map=(),
        problem_type_code=_SOLVE,
        answer_format=answer_format_of(value),
        answer_aggregate="sum",
    )


def _root_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    cond: str | tuple[str, ...],
    value: int | Fraction,
    explanation: str,
    selection: str | None,
    var: str = "x",
) -> KindedDiffItem:
    return KindedDiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=frac_text(value),
        explanation=explanation,
        conditions=cond,
        answer_map=((var, frac_text(value)),),
        problem_type_code=_SOLVE,
        answer_format=answer_format_of(value),
        answer_selection=selection,
    )


def _roots_note(p: _P) -> str:
    rs = ", ".join(str(r) for r in p.distinct_roots)
    return f"인수분해하면 {_factored_text(p)} = 0이므로 서로 다른 실근은 {rs}이다."


# ──────────────────────────────────────────────────────────────────────────
# 대표(representative)
# ──────────────────────────────────────────────────────────────────────────
def _rep_frames() -> list[Frame]:
    def r1(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        return _count_item(
            slot="representative",
            frame_id="rep-count-real-roots-of-equation",
            text=f"방정식 {render_poly(p.poly)} = 0의 서로 다른 실근의 개수를 구하시오.",
            cond=_eq_cond(p.poly, 0),
            poly=p.poly,
            explanation=(
                f"{_roots_note(p)} 따라서 {_n_distinct(p.poly)}개이다."
                if p.quad is None
                else f"인수분해하면 {_factored_text(p)} = 0이고 이차 인수는 실근이 없다."
            ),
        )

    def r2(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        total = sum(p.roots)
        return _sum_item(
            slot="representative",
            frame_id="rep-sum-of-cubic-roots",
            text=f"삼차방정식 {render_poly(p.poly)} = 0의 세 근의 합을 구하시오. {_SUM_NOTE}",
            cond=_eq_cond(p.poly, 0),
            value=total,
            explanation=f"{_roots_note(p)} 중근을 중복하여 세면 세 근의 합은 {total}이다.",
        )

    def r3(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        if len(p.distinct_roots) < 2:
            return None
        big = p.distinct_roots[-1]
        return _root_item(
            slot="representative",
            frame_id="rep-largest-real-root",
            text=f"방정식 {render_poly(p.poly)} = 0의 실근 중 가장 큰 것을 구하시오.",
            cond=_eq_cond(p.poly, 0),
            value=big,
            explanation=f"{_roots_note(p)} 이 중 가장 큰 것은 {big}이다.",
            selection="largest",
        )

    def r4(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_const(p.poly)
        if split is None:
            return None
        g, k = split
        return _count_item(
            slot="representative",
            frame_id="rep-curve-meets-horizontal-line",
            text=(
                f"곡선 y = {render_poly(g)}{wa_gwa(render_poly(g))} 직선 y = {k}{i_ga(str(k))} "
                "만나는 서로 다른 점의 개수를 구하시오."
            ),
            cond=f"{poly_to_sympy_str(g)} = {k}",
            poly=p.poly,
            explanation=(
                f"교점의 x좌표는 {render_poly(g)} = {k}의 실근이다. 정리하면 "
                f"{_factored_text(p)} = 0이므로 서로 다른 실근은 {_n_distinct(p.poly)}개이다."
            ),
        )

    def r5(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        a = p.roots[0]
        return _root_item(
            slot="representative",
            frame_id="rep-unique-real-solution",
            text=(
                f"방정식 {render_poly(p.poly)} = 0을 만족시키는 실수 x는 오직 하나이다. "
                "그 값을 구하시오."
            ),
            cond=_eq_cond(p.poly, 0),
            value=a,
            explanation=(
                f"인수분해하면 {_factored_text(p)} = 0이다. 이차 인수는 항상 양수이므로 "
                f"실근은 {a}뿐이다."
            ),
            selection=None,
        )

    def r6(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        nonneg = [r for r in p.distinct_roots if r >= 0]
        if len(nonneg) != 1:
            return None
        a = nonneg[0]
        return _root_item(
            slot="representative",
            frame_id="rep-root-in-domain",
            text=(
                f"x가 0 이상의 실수일 때, 방정식 {render_poly(p.poly)} = 0의 해를 구하시오. "
                "(단, 해는 하나뿐이다.)"
            ),
            cond=(_eq_cond(p.poly, 0), "x >= 0"),
            value=a,
            explanation=f"{_roots_note(p)} 이 중 0 이상인 것은 {a}뿐이다.",
            selection=None,
        )

    return [
        Frame("rep-count-real-roots-of-equation", _params("p3-eq:r1", _cubics()), r1),
        Frame("rep-sum-of-cubic-roots", _params("p3-eq:r2", _cubics_real()), r2),
        Frame("rep-largest-real-root", _params("p3-eq:r3", _cubics_real()), r3),
        Frame("rep-curve-meets-horizontal-line", _params("p3-eq:r4", _cubics()), r4),
        Frame(
            "rep-unique-real-solution",
            _params("p3-eq:r5", [p for p in _cubics() if p.quad and p.degree == 3]),
            r5,
        ),
        Frame("rep-root-in-domain", _params("p3-eq:r6", _cubics_real()), r6),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 기본(basic)
# ──────────────────────────────────────────────────────────────────────────
def _basic_frames() -> list[Frame]:
    def b1(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        return _count_item(
            slot="basic",
            frame_id="basic-quartic-function-zero-count",
            text=(
                f"사차함수 f(x) = {render_poly(p.poly)}에 대하여 방정식 f(x) = 0을 만족시키는 "
                "서로 다른 실수 x의 개수를 구하시오."
            ),
            cond=_eq_cond(p.poly, 0),
            poly=p.poly,
            explanation=(
                f"인수분해하면 {_factored_text(p)} = 0이므로 서로 다른 실근의 개수는 "
                f"{_n_distinct(p.poly)}이다."
            ),
        )

    def b2(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        if len(p.distinct_roots) < 2:
            return None
        small = p.distinct_roots[0]
        return _root_item(
            slot="basic",
            frame_id="basic-smallest-x-intercept",
            text=(
                f"삼차함수 y = {render_poly(p.poly)}의 그래프가 x축과 만나는 점의 x좌표 중 "
                "가장 작은 값을 구하시오."
            ),
            cond=_eq_cond(p.poly, 0),
            value=small,
            explanation=f"{_roots_note(p)} 이 중 가장 작은 것은 {small}이다.",
            selection="smallest",
        )

    def b3(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        total = sum(p.roots)
        return _sum_item(
            slot="basic",
            frame_id="basic-sum-of-quartic-roots",
            text=f"사차방정식 {render_poly(p.poly)} = 0의 네 근의 합을 구하시오. {_SUM_NOTE}",
            cond=_eq_cond(p.poly, 0),
            value=total,
            explanation=f"{_roots_note(p)} 중근을 중복하여 세면 네 근의 합은 {total}이다.",
        )

    def b4(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_line(p.poly)
        if split is None:
            return None
        g, h = split
        return _count_item(
            slot="basic",
            frame_id="basic-curve-and-line-intersections",
            text=(
                f"곡선 y = {render_poly(g)}{wa_gwa(render_poly(g))} 직선 y = {_line_text(h)}의 "
                "교점의 개수를 구하시오."
            ),
            cond=_eq_cond(g, h),
            poly=p.poly,
            explanation=(
                f"교점의 x좌표는 {render_poly(g)} = {_line_text(h)}의 실근이고 정리하면 "
                f"{_factored_text(p)} = 0이다. 서로 다른 실근은 {_n_distinct(p.poly)}개이다."
            ),
        )

    def b5(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_line(p.poly)
        if split is None or len(p.distinct_roots) != 3 or p.quad is not None:
            return None
        g, h = split
        total = sum(p.roots)
        return _sum_item(
            slot="basic",
            frame_id="basic-sum-of-intersection-x",
            text=(
                f"곡선 y = {render_poly(g)}{wa_gwa(render_poly(g))} "
                f"직선 y = {_line_text(h)}{i_ga(_line_text(h))} 서로 다른 세 점에서 만난다. "
                "세 교점의 x좌표의 합을 구하시오."
            ),
            cond=_eq_cond(g, h),
            value=total,
            explanation=f"{_roots_note(p)} 세 교점의 x좌표의 합은 {total}이다.",
        )

    def b6(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        product = 1
        for r in p.roots:
            product *= r
        return KindedDiffItem(
            slot="basic",
            frame_id="basic-product-of-cubic-roots",
            question_text=(
                f"삼차방정식 {render_poly(p.poly)} = 0의 세 근의 곱을 구하시오. {_SUM_NOTE}"
            ),
            answer_text=str(product),
            explanation=f"{_roots_note(p)} 중근을 중복하여 곱하면 {product}이다.",
            conditions=_eq_cond(p.poly, 0),
            answer_map=(),
            problem_type_code=_SOLVE,
            answer_format=answer_format_of(product),
            answer_aggregate="product",
        )

    return [
        Frame("basic-quartic-function-zero-count", _params("p3-eq:b1", _quartics()), b1),
        Frame("basic-smallest-x-intercept", _params("p3-eq:b2", _cubics_real()), b2),
        Frame("basic-sum-of-quartic-roots", _params("p3-eq:b3", _quartics_real()), b3),
        Frame("basic-curve-and-line-intersections", _params("p3-eq:b4", _cubics()), b4),
        Frame("basic-sum-of-intersection-x", _params("p3-eq:b5", _cubics_real()), b5),
        Frame("basic-product-of-cubic-roots", _params("p3-eq:b6", _cubics_real()), b6),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 응용(applied)
# ──────────────────────────────────────────────────────────────────────────
def _applied_frames() -> list[Frame]:
    def a1(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        a = p.roots[0] if p.roots[0] > 0 else p.roots[1]
        return _root_item(
            slot="applied",
            frame_id="applied-inequality-single-point-domain",
            text=(
                f"x가 0 이상의 실수일 때, 부등식 {render_poly(p.poly)} <= 0을 만족시키는 x의 "
                "값을 구하시오."
            ),
            cond=(f"{poly_to_sympy_str(p.poly)} <= 0", "x >= 0"),
            value=a,
            explanation=(
                f"인수분해하면 {_factored_text(p)} <= 0이다. x가 0 이상이면 남은 인수가 양수이므로 "
                f"제곱 인수가 0이어야 하고 x는 {a}이다."
            ),
            selection=None,
        )

    def a2(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_const(p.poly)
        if split is None:
            return None
        g, k = split
        return _count_item(
            slot="applied",
            frame_id="applied-height-reaches-level",
            text=(
                f"물체를 던진 지 t초 후의 높이가 h(t) = {render_poly(g, 't')} (m)로 주어진다고 "
                f"하자. 높이 {k}m에 도달하는 서로 다른 실수 t의 개수를 구하시오."
            ),
            cond=f"{poly_to_sympy_str(g, 't')} = {k}",
            poly=p.poly,
            explanation=(
                f"{render_poly(g, 't')} = {k}{eul_reul(str(k))} 정리하면 "
                f"{_factored_text(p, 't')} = 0이므로 "
                f"서로 다른 실근은 {_n_distinct(p.poly)}개이다."
            ),
        )

    def a3(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_curves(p.poly)
        if split is None:
            return None
        g, h = split
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
                f"교점의 x좌표는 두 식을 같게 놓은 방정식의 실근이고 정리하면 "
                f"{_factored_text(p)} = 0이다. 서로 다른 실근은 {_n_distinct(p.poly)}개이다."
            ),
        )

    def a4(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_curves(p.poly)
        if split is None or len(p.distinct_roots) != 4:
            return None
        g, h = split
        total = sum(p.roots)
        return _sum_item(
            slot="applied",
            frame_id="applied-sum-of-two-curve-intersections",
            text=(
                f"두 곡선 y = {render_poly(g)}, y = {render_poly(h)}{i_ga(render_poly(h))} "
                "서로 다른 네 점에서 "
                "만난다. 네 교점의 x좌표의 합을 구하시오."
            ),
            cond=_eq_cond(g, h),
            value=total,
            explanation=f"{_roots_note(p)} 네 교점의 x좌표의 합은 {total}이다.",
        )

    def a5(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_line(p.poly)
        if split is None or len(p.distinct_roots) < 2:
            return None
        g, h = split
        big = p.distinct_roots[-1]
        return _root_item(
            slot="applied",
            frame_id="applied-rightmost-intersection",
            text=(
                f"곡선 y = {render_poly(g)}{wa_gwa(render_poly(g))} 직선 y = {_line_text(h)}의 "
                "교점 중 x좌표가 가장 큰 점의 x좌표를 구하시오."
            ),
            cond=_eq_cond(g, h),
            value=big,
            explanation=f"{_roots_note(p)} 가장 큰 x좌표는 {big}이다.",
            selection="largest",
        )

    def a6(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        a = p.roots[0]
        return _root_item(
            slot="applied",
            frame_id="applied-equality-case-of-nonnegative",
            text=(
                f"모든 실수 x에 대하여 부등식 {render_poly(p.poly)} >= 0이 성립한다. 등호가 "
                "성립하는 실수 x의 값을 구하시오."
            ),
            cond=_eq_cond(p.poly, 0),
            value=a,
            explanation=(
                f"인수분해하면 {_factored_text(p)}이고 이차 인수는 항상 양수이므로 등호는 "
                f"제곱 인수가 0일 때, 즉 x가 {a}일 때 성립한다."
            ),
            selection=None,
        )

    return [
        Frame(
            "applied-inequality-single-point-domain", _params("p3-eq:a1", _one_nonneg_cubics()), a1
        ),
        Frame("applied-height-reaches-level", _params("p3-eq:a2", _cubics()), a2),
        Frame("applied-two-curves-intersections", _params("p3-eq:a3", _quartics()), a3),
        Frame(
            "applied-sum-of-two-curve-intersections", _params("p3-eq:a4", _quartics_distinct4()), a4
        ),
        Frame("applied-rightmost-intersection", _params("p3-eq:a5", _cubics_real()), a5),
        Frame("applied-equality-case-of-nonnegative", _params("p3-eq:a6", _square_quartics()), a6),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 오개념 유발(misconception_trigger) — f(x) = k의 근의 개수를 y = k와의 교점으로 못 본다(M0677)
# ──────────────────────────────────────────────────────────────────────────
def _crit_count(poly: Poly) -> int:
    """f'(x) = 0의 서로 다른 실근 수 — '극점 개수'를 근의 개수로 오인한 값."""
    return _n_distinct(derivative_of(poly))


def _mc_count(
    *,
    frame_id: str,
    text: str,
    cond: str,
    p: _P,
    seed: str,
    note: str,
) -> DiffItem | None:
    """실근 개수 객관식 — 차수·극점 수로 답한 값(M0677)을 오답 선지에 둔다."""
    correct = _n_distinct(p.poly)
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
    entries = entries[:4]
    if sum(1 for e in entries if e.kebab) == 0:
        return None
    try:
        choices, answer, distractors = build_choices(entries, shuffle_seed=seed)
    except ValueError:
        return None
    return _count_item(
        slot="misconception_trigger",
        frame_id=frame_id,
        text=text,
        cond=cond,
        poly=p.poly,
        explanation=f"{note} 서로 다른 실근은 {correct}개이다.",
        choices=choices,
        distractors=distractors,
        answer=int(answer),
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
            note=f"인수분해하면 {_factored_text(p)} = 0이다.",
        )

    def m2(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_const(p.poly)
        if split is None:
            return None
        g, k = split
        return _mc_count(
            frame_id="mc-curve-and-horizontal-line",
            text=(
                f"곡선 y = {render_poly(g)}의 그래프와 직선 y = {k}의 교점의 개수로 " "옳은 것은?"
            ),
            cond=f"{poly_to_sympy_str(g)} = {k}",
            p=p,
            seed=f"mc2:{p.poly}",
            note=f"교점의 x좌표는 {render_poly(g)} = {k}의 실근이다.",
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
            note=f"f(x) = {k}를 정리하면 {_factored_text(p)} = 0이다.",
        )

    def m4(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        return _mc_count(
            frame_id="mc-graph-meets-x-axis",
            text=f"함수 y = {render_poly(p.poly)}의 그래프가 x축과 만나는 점의 개수는?",
            cond=_eq_cond(p.poly, 0),
            p=p,
            seed=f"mc4:{p.poly}",
            note=f"x축과 만나는 점의 x좌표는 {render_poly(p.poly)} = 0의 실근이다.",
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
            note="교점의 x좌표는 두 식을 같게 놓은 방정식의 실근이다.",
        )

    return [
        Frame("mc-count-real-roots", _params("p3-eq:m1", _cubics()), m1),
        Frame("mc-curve-and-horizontal-line", _params("p3-eq:m2", _cubics()), m2),
        Frame("mc-equation-fx-equals-k", _params("p3-eq:m3", _quartics()), m3),
        Frame("mc-graph-meets-x-axis", _params("p3-eq:m4", _quartics()), m4),
        Frame("mc-two-curves-intersections", _params("p3-eq:m5", _quartics()), m5),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 진단(diagnostic) — 단계 하나씩(극점 수·극점 위치·부등식 한 점·정의역 제한·근과 계수)
# ──────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=None)
def _derivative_cubics() -> tuple[Poly, ...]:
    """삼차 f = Lx^3 + px^2 + qx + r — f'의 서로 다른 실근 0·1·2개가 모두 나오게 계수를 훑는다."""
    out: list[Poly] = []
    for lead in (1, 2):
        for p in range(-4, 5):
            for qv in range(-6, 7):
                r = (lead * 5 + p * 3 + qv) % 7 - 3
                coefs = [(3, lead), (2, p), (1, qv), (0, r)]
                out.append(tuple((e, c) for e, c in coefs if c != 0))
    return tuple(seeded_order("p3-eq:dcubics", tuple(out))[:150])


def _d1_params() -> tuple[tuple[object, ...], ...]:
    return tuple((f,) for f in _derivative_cubics())


def _f_prime_roots_rational(f: Poly) -> tuple[Fraction, ...] | None:
    d = derivative_of(f)
    roots = sympy.roots(sympy.Poly(poly_to_sympy(d), _X))
    if sum(roots.values()) != 2:
        return None
    out: list[Fraction] = []
    for r in roots:
        if not r.is_rational:
            return None
        out.append(Fraction(int(r.p), int(r.q)))
    return tuple(sorted(out))


def _diagnostic_frames() -> list[Frame]:
    def d1(q: tuple[object, ...]) -> DiffItem | None:
        f = q[0]
        assert isinstance(f, tuple)
        d = derivative_of(f)
        n = _n_distinct(d)
        return _count_item(
            slot="diagnostic",
            frame_id="diag-count-critical-points",
            text=(
                f"함수 f(x) = {render_poly(f)}에 대하여 방정식 f'(x) = 0의 서로 다른 실근의 "
                "개수를 구하시오."
            ),
            cond=_eq_cond(d, 0),
            poly=d,
            explanation=f"도함수는 {render_poly(d)}이고 이 이차식의 서로 다른 실근은 {n}개이다.",
        )

    def d2(q: tuple[object, ...]) -> DiffItem | None:
        f = q[0]
        assert isinstance(f, tuple)
        roots = _f_prime_roots_rational(f)
        if roots is None or len(roots) != 2:
            return None
        d = derivative_of(f)
        total = roots[0] + roots[1]
        return _sum_item(
            slot="diagnostic",
            frame_id="diag-sum-of-critical-points",
            text=(
                f"함수 f(x) = {render_poly(f)}에 대하여 f'(x) = 0을 만족시키는 두 실수 x의 "
                "합을 구하시오."
            ),
            cond=_eq_cond(d, 0),
            value=total,
            explanation=(
                f"도함수는 {render_poly(d)}이고 두 근은 {frac_text(roots[0])}, "
                f"{frac_text(roots[1])}이므로 합은 {frac_text(total)}이다."
            ),
        )

    def d3(q: tuple[object, ...]) -> DiffItem | None:
        f = q[0]
        assert isinstance(f, tuple)
        roots = _f_prime_roots_rational(f)
        if roots is None or len(roots) != 2:
            return None
        d = derivative_of(f)
        return _root_item(
            slot="diagnostic",
            frame_id="diag-smaller-critical-point",
            text=(
                f"함수 f(x) = {render_poly(f)}의 도함수 f'(x)에 대하여 f'(x) = 0의 두 실근 중 "
                "작은 근을 구하시오."
            ),
            cond=_eq_cond(d, 0),
            value=roots[0],
            explanation=(
                f"도함수는 {render_poly(d)}이고 두 근은 {frac_text(roots[0])}, "
                f"{frac_text(roots[1])}이다. 작은 근은 {frac_text(roots[0])}이다."
            ),
            selection="smallest",
        )

    def d4(q: tuple[object, ...]) -> DiffItem | None:
        a = q[0]
        assert isinstance(a, int)
        poly: Poly = ((2, 1), (1, -2 * a), (0, a * a))
        return _root_item(
            slot="diagnostic",
            frame_id="diag-perfect-square-inequality",
            text=(
                f"이차부등식 {render_poly(poly)} <= 0을 만족시키는 실수 x의 값을 구하시오. "
                "(단, 해는 하나뿐이다.)"
            ),
            cond=f"{poly_to_sympy_str(poly)} <= 0",
            value=a,
            explanation=f"좌변은 (x - {a})의 제곱이므로 0 이하가 되려면 x가 {a}이어야 한다.",
            selection=None,
        )

    def d5(q: tuple[object, ...]) -> DiffItem | None:
        r1, r2 = q[0], q[1]
        assert isinstance(r1, int) and isinstance(r2, int)
        if r1 >= r2 or r1 >= 0 or r2 <= 0:
            return None
        poly = _expand(1, (r1, r2))
        return _root_item(
            slot="diagnostic",
            frame_id="diag-positive-root-of-quadratic",
            text=f"이차방정식 {render_poly(poly)} = 0의 양의 실근을 구하시오.",
            cond=(_eq_cond(poly, 0), "x > 0"),
            value=r2,
            explanation=f"인수분해하면 두 근은 {r1}, {r2}이고 양수인 것은 {r2}이다.",
            selection=None,
        )

    def d6(q: tuple[object, ...]) -> DiffItem | None:
        a, b, c0, m, n = (int(str(v)) for v in q)
        g: Poly = ((2, a), (1, b), (0, c0))
        h: Poly = tuple((e, v) for e, v in ((1, m), (0, n)) if v != 0)
        diff = poly_from_sympy(sympy.expand(poly_to_sympy(g) - poly_to_sympy(h)))
        if len(diff) == 0 or diff[0][0] != 2:
            return None
        real = sympy.Poly(poly_to_sympy(diff), _X).count_roots()
        if real != 2 or _n_distinct(diff) != 2:
            return None
        roots = sympy.roots(sympy.Poly(poly_to_sympy(diff), _X))
        total = sum((r * mult for r, mult in roots.items()), sympy.Integer(0))
        if not total.is_rational or any(not r.is_rational for r in roots):
            return None
        value = Fraction(int(total.p), int(total.q))
        return _sum_item(
            slot="diagnostic",
            frame_id="diag-sum-of-parabola-line-intersections",
            text=(
                f"포물선 y = {render_poly(g)}{wa_gwa(render_poly(g))} 직선 y = {render_poly(h)}의 "
                "두 교점의 x좌표의 합을 구하시오."
            ),
            cond=_eq_cond(g, h),
            value=value,
            explanation=(
                f"두 식을 같게 놓으면 {render_poly(diff)} = 0이고 두 근의 합은 "
                f"{frac_text(value)}이다."
            ),
        )

    quad_pairs = tuple((r1, r2) for r1 in range(-5, 0) for r2 in range(1, 6))
    parabola_params = tuple(
        (a, b, c0, m, n)
        for a in (1, 2)
        for b in (-4, -2, 1, 3)
        for c0 in (-3, 1, 4)
        for m in (-2, 1, 3)
        for n in (-1, 2)
    )
    return [
        Frame("diag-count-critical-points", _d1_params(), d1),
        Frame("diag-sum-of-critical-points", _d1_params(), d2),
        Frame("diag-smaller-critical-point", _d1_params(), d3),
        Frame(
            "diag-perfect-square-inequality",
            tuple((a,) for a in seeded_order("p3-eq:d4", tuple(v for v in range(-6, 7) if v))),
            d4,
        ),
        Frame("diag-positive-root-of-quadratic", tuple(seeded_order("p3-eq:d5", quad_pairs)), d5),
        Frame(
            "diag-sum-of-parabola-line-intersections",
            tuple(seeded_order("p3-eq:d6", parabola_params)),
            d6,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 숙련도 확인(mastery_check)
# ──────────────────────────────────────────────────────────────────────────
def _mastery_frames() -> list[Frame]:
    def k1(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        if len(p.distinct_roots) == len(p.roots):
            return None  # 중근이 있는 것만
        return _count_item(
            slot="mastery_check",
            frame_id="mastery-count-with-double-root",
            text=(
                f"사차방정식 {render_poly(p.poly)} = 0은 중근을 갖는다. 이 방정식의 서로 다른 "
                "실근의 개수를 구하시오."
            ),
            cond=_eq_cond(p.poly, 0),
            poly=p.poly,
            explanation=(
                f"인수분해하면 {_factored_text(p)} = 0이므로 중근을 한 번만 세면 서로 다른 "
                f"실근은 {_n_distinct(p.poly)}개이다."
            ),
        )

    def k2(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_curves(p.poly)
        if split is None or len(p.distinct_roots) != 4:
            return None
        g, h = split
        total_sum = sum(p.roots)
        return _sum_item(
            slot="mastery_check",
            frame_id="mastery-sum-of-four-intersections",
            text=(
                f"곡선 y = {render_poly(g)}{i_ga(render_poly(g))} 포물선 "
                f"y = {render_poly(h)}{wa_gwa(render_poly(h))} 서로 다른 네 점에서 만난다. "
                "네 교점의 x좌표의 합을 구하시오."
            ),
            cond=_eq_cond(g, h),
            value=total_sum,
            explanation=f"{_roots_note(p)} 네 교점의 x좌표의 합은 {total_sum}이다.",
        )

    def k3(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        a = p.roots[0] if p.roots[0] > 0 else p.roots[1]
        return _root_item(
            slot="mastery_check",
            frame_id="mastery-equality-in-domain",
            text=(
                f"x >= 0에서 부등식 {render_poly(p.poly)} >= 0이 성립함을 보이려 한다. "
                "이때 x >= 0에서 등호가 성립하는 x의 값을 구하시오."
            ),
            cond=(_eq_cond(p.poly, 0), "x >= 0"),
            value=a,
            explanation=(
                f"인수분해하면 {_factored_text(p)}이고 x >= 0에서 남은 인수는 양수이므로 "
                f"등호는 x가 {a}일 때만 성립한다."
            ),
            selection=None,
        )

    def k4(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_curves(p.poly)
        if split is None or len(p.distinct_roots) < 2 or p.quad is not None:
            return None
        g, h = split
        big = p.distinct_roots[-1]
        return _root_item(
            slot="mastery_check",
            frame_id="mastery-largest-x-of-two-curves",
            text=(
                f"두 곡선 y = {render_poly(g)}, y = {render_poly(h)}의 교점 중 x좌표가 가장 큰 "
                "점의 x좌표를 구하시오."
            ),
            cond=_eq_cond(g, h),
            value=big,
            explanation=f"{_roots_note(p)} 가장 큰 x좌표는 {big}이다.",
            selection="largest",
        )

    def k5(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        if len(p.distinct_roots) < 2:
            return None
        small = p.distinct_roots[0]
        return _root_item(
            slot="mastery_check",
            frame_id="mastery-smallest-real-root-quartic",
            text=f"사차방정식 {render_poly(p.poly)} = 0의 실근 중 가장 작은 것을 구하시오.",
            cond=_eq_cond(p.poly, 0),
            value=small,
            explanation=f"{_roots_note(p)} 가장 작은 것은 {small}이다.",
            selection="smallest",
        )

    def k6(q: tuple[object, ...]) -> DiffItem | None:
        p = _p_of(q[0])
        split = _split_line(p.poly)
        if split is None or len(p.distinct_roots) != 2 or p.quad is not None:
            return None
        g, h = split
        return _count_item(
            slot="mastery_check",
            frame_id="mastery-tangent-line-intersection-count",
            text=(
                f"직선 y = {_line_text(h)}{eun_neun(_line_text(h))} 곡선 y = {render_poly(g)}에 "
                "접하는 점을 갖는다. 이 직선과 곡선이 만나는 서로 다른 점의 개수를 구하시오."
            ),
            cond=_eq_cond(g, h),
            poly=p.poly,
            explanation=(
                f"교점의 x좌표는 {_factored_text(p)} = 0의 실근이고 중근은 접점이다. "
                f"서로 다른 실근은 {_n_distinct(p.poly)}개이다."
            ),
        )

    return [
        Frame("mastery-count-with-double-root", _params("p3-eq:k1", _quartics_real()), k1),
        Frame("mastery-sum-of-four-intersections", _params("p3-eq:k2", _quartics_distinct4()), k2),
        Frame("mastery-equality-in-domain", _params("p3-eq:k3", _one_nonneg_cubics()), k3),
        Frame("mastery-largest-x-of-two-curves", _params("p3-eq:k4", _quartics_real()), k4),
        Frame("mastery-smallest-real-root-quartic", _params("p3-eq:k5", _quartics_real()), k5),
        Frame("mastery-tangent-line-intersection-count", _params("p3-eq:k6", _double_cubics()), k6),
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
