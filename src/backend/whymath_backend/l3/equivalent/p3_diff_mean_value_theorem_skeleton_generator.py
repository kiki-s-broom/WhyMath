"""[12미적Ⅰ-02-06] 평균값 정리 결정론 문항 생성기 — P3-03(결정론·LLM 0).

개념: `H:12미적Ⅰ02-06`(`math.calculus.pyeonggyungaps-jeongri`). 핵심 오개념: M0674(평균값 정리
조건 미확인 — "롤의 정리와 혼동한다"). 이 M-id에는 L4 카탈로그의 kebab이 **없다**(MISC-40이
omission형이라 의도적으로 미승격 — `docs/reviews/misc_40_calculus_diff_kebab_seat_judgment_
2026-10-02.md`). 그래서
오개념 유발 슬롯의 `distractor_map`은 **M-id를 그대로** 쓴다(계측기 `_reached_misconceptions`가
M-id를 그대로 센다). 신규 오개념 id는 만들지 않는다. 대신 L4 참조 무결성 검증자
(`validate_distractor_map`)는 M-id를 알지 못하므로 이 개념에서는 위반으로 읽는다 — 등록 때 처분이
필요하다(작성자 보고 참조).

구간 소속 판정(P3-19)
--------------------
평균값 정리 c값 문항의 검산 재료는 **방정식 1개 + 열린구간 경계 4개**의 목록이다(P3-18 보강 fixture
`p3_18_supplement.jsonl`의 정답·오답 행과 같은 형식):

    ["Derivative(F, x).doit().subs(x, c) = (F(b) - F(a))/(b - a)",
     "c >= a", "c <= b", "c != a", "c != b"]

방정식의 근이 둘이고 하나만 구간 안에 있는 문항(삼차함수)을 포함하므로, 구간 조건이 없으면 구간 밖
근이 정답으로 통과한다. 이 파일의 c값 문항은 전부 이 형식을 쓰며, 정답 하나가 유일함(구간 안
유리근이 정확히 1개)을 생성기가 SymPy로 확인한다.

5회차 은행 감사(2026-10-08) 처분 — 함수는 전부 삼차 이상
------------------------------------------------------
이차함수의 평균값 정리는 도함수가 일차라 c가 늘 구간의 중점이고(롤의 정리는 대칭축), 끝점 미지수형의
답은 2c - 고정 끝점이다 — 평균값 정리를 몰라도 '가운데 값'으로 풀렸다(결함 18건 · 판정기
T-quadratic-mean-value · T-midpoint-answer). 이 파일의 틀은 전부 **삼차 이상**으로 바꿨고, 매개변수
단계에서 c ≠ 구간의 중점(끝점형은 답 ≠ 2c - 끝점)을 거부 조건으로 건다(`round_robin_items`의
매개변수 거부 조건). 중점 값은 객관식의 *오답 선지*로만 남긴다. 끝점 미지수형 해설은 방정식을
인수분해해 두 근을 보이고 구간 조건으로 하나를 고른다. 진단 슬롯의 구판 '두 실근은 …이다'(근을
발문에 나열 · T06-roots-given)는 지웠다 — 근을 적지 않는 형태는 대표 슬롯의
'rep-two-candidates-one-inside'가 맡고, 진단은 평균값 정리의 *결론*(f'(c) = 평균변화율 — c를 구하지
않고 f'(c)를 정한다)을 함수식이 있는 짝 틀로 본다.

범위(이 개념에 한정)
--------------------
다항함수 위의 평균값 정리·롤의 정리(c값·평균변화율·미지수 결정)만 다룬다. 극값·증감은 `-02-07`,
그래프 개형은 `-02-08`의 몫이다. 답은 전부 스칼라 단일 미지수다(함수식 답 금지 — 섀도 채점 계약).

문제유형 정직성
--------------
c값·미지수를 구하는 문항은 `ptype.solve-for-unknown`, 값을 계산하는 문항은
`ptype.evaluate-expression`, 방정식 `f'(x) = (평균변화율)`의 서로 다른 실근 개수를 묻는 문항은
`ptype.count-solutions`로 달았다. 이 개념의 명세 스킬(`deductive-reasoning`·`graph-reading`)과
겹치는 유형은 `count-solutions`(graph-reading)뿐이고 `verify-claim`(deductive-reasoning)은
기계 검산 경로가 없어 문항을 만들지 못했다 — 겹치게 하려고 거짓 유형을 달지 않았다.

검산 재료의 형식 제약(중요)
--------------------------
Tier1은 미분 평가가 든 변을 다른 연산과 섞지 못한다(power 생성기 docstring 참조). 그래서 조건의
미분 평가는 조건당 1회·맨몸이며, 우변은 숫자만으로 계산한 평균변화율이다. 미지수가 구간 끝점인
문항은 미분 평가가 *점 대입 뒤 숫자*이고 끝점 쪽에 미지수가 있는 형태로 쓴다.

확장 필드: `KindedDiffItem`은 base `DiffItem`에 `answer_kind`·`answer_aggregate`·`answer_selection`
(게이트 재료)을 더한 것이다. base `_assemble`은 이 셋을 후보에 싣지 않으므로 각 생성기가
`_assemble`을 덮어 `with_item_kinds`로 후보에 얹는다(base 모듈 무수정).
"""

from __future__ import annotations

import dataclasses
import math
import re
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
    eval_at,
    poly_from_sympy,
    poly_to_sympy,
    poly_to_sympy_str,
    render_affine,
    render_difference,
    render_factored,
    render_poly,
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
    build_choices,
    round_robin_items,
    seeded_order,
)
from whymath_backend.lang.josa import eul_reul, i_ga
from whymath_backend.schema.enums import AnswerFormat

__all__ = [
    "KindedDiffItem",
    "P3DiffMeanValueTheoremGenerator",
    "answer_format_of",
    "frac_text",
    "with_item_kinds",
]

#: 오개념 id — M-id 그대로(kebab 좌석 없음. 모듈 docstring 참조).
_MID: Final = "M0674"
_EVAL: Final = "ptype.evaluate-expression"
_SOLVE: Final = "ptype.solve-for-unknown"
_COUNT: Final = "ptype.count-solutions"
_X = sympy.Symbol("x")


# ──────────────────────────────────────────────────────────────────────────
# 공용 확장(02-09 생성기도 import해서 쓴다)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class KindedDiffItem(DiffItem):
    """게이트 재료(개념형 검증 종류·근 집계·근 선택)를 더한 문항 — base `DiffItem`의 확장.

    · `answer_kind` — `real_root_count` 등 개념형 검증기 키(답이 값이 아니라 개수).
    · `answer_aggregate` — "sum"/"product"(답이 근이 아니라 근들의 합/곱).
    · `answer_selection` — "largest"/"smallest"/"unique"(여러 실근 중 어느 근인가).
    """

    answer_kind: str | None = None
    answer_aggregate: str | None = None
    answer_selection: str | None = None


def with_item_kinds(candidate: CandidateProblem, item: DiffItem) -> CandidateProblem:
    """후보 번들에 문항의 게이트 재료(kind·aggregate·selection)를 얹는다(없으면 그대로)."""
    updates: dict[str, str] = {}
    if isinstance(item, KindedDiffItem):
        if item.answer_kind is not None:
            updates["answer_kind"] = item.answer_kind
        if item.answer_aggregate is not None:
            updates["answer_aggregate"] = item.answer_aggregate
        if item.answer_selection is not None:
            updates["answer_selection"] = item.answer_selection
    return candidate.model_copy(update=updates) if updates else candidate


def frac_text(value: Fraction | int) -> str:
    """수 표기 — 정수는 '3'·'-2', 분수는 '5/2'·'-5/2'(ASCII)."""
    frac = Fraction(value)
    return str(frac.numerator) if frac.denominator == 1 else f"{frac.numerator}/{frac.denominator}"


def answer_format_of(value: Fraction | int) -> AnswerFormat:
    frac = Fraction(value)
    if frac.denominator != 1:
        return AnswerFormat.분수
    return AnswerFormat.자연수 if frac > 0 else AnswerFormat.실수


# ──────────────────────────────────────────────────────────────────────────
# 사례 풀 — (함수, 구간, c, 다른 근). 탐색은 정수·분수 산술로, 문항 조립은 SymPy로 재확인
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class _Case:
    f: Poly
    a: int
    b: int
    c: Fraction  # 열린구간 (a, b) 안의 유일한 c
    others: tuple[Fraction, ...]  # f'(x) = 평균변화율의 나머지 유리근(구간 밖)


def _mk_poly(*coefs: tuple[int, int]) -> Poly:
    return tuple((e, c) for e, c in coefs if c != 0)


def _ev(coefs: dict[int, int], x: Fraction) -> Fraction:
    return sum((Fraction(c) * x**e for e, c in coefs.items()), Fraction(0))


def _quad_rational_roots(a2: Fraction, a1: Fraction, a0: Fraction) -> tuple[Fraction, ...] | None:
    """a2 x^2 + a1 x + a0 = 0의 서로 다른 유리근(없거나 무리근이면 None)."""
    if a2 == 0:
        return None
    disc = a1 * a1 - 4 * a2 * a0
    if disc < 0:
        return None
    num, den = disc.numerator, disc.denominator
    rn, rd = _isqrt_exact(num), _isqrt_exact(den)
    if rn is None or rd is None:
        return None
    root = Fraction(rn, rd)
    if root == 0:
        return (-a1 / (2 * a2),)
    return tuple(sorted({(-a1 - root) / (2 * a2), (-a1 + root) / (2 * a2)}))


def _isqrt_exact(n: int) -> int | None:
    r = math.isqrt(n)
    return r if r * r == n else None


def _const_term(seed: int) -> int:
    """상수항 — 문항 모양을 다양하게(결정론)."""
    return seed % 9 - 4


@lru_cache(maxsize=None)
def _cubic_cases() -> tuple[_Case, ...]:
    """삼차함수 f = Lx^3 + px^2 + qx + r — f'(x) = 평균변화율의 두 근이 유리수, 하나만 구간 안."""
    out: list[_Case] = []
    for lead in (1, 2):
        for p in range(-4, 5):
            for q in range(-6, 7):
                for a in range(-3, 3):
                    for b in range(a + 2, 5):
                        r = _const_term(lead * 11 + p * 7 + q * 3 + a * 5 + b)
                        coefs = {3: lead, 2: p, 1: q, 0: r}
                        m = (_ev(coefs, Fraction(b)) - _ev(coefs, Fraction(a))) / (b - a)
                        roots = _quad_rational_roots(
                            Fraction(3 * lead), Fraction(2 * p), Fraction(q) - m
                        )
                        if roots is None or len(roots) != 2:
                            continue
                        inside = [x for x in roots if a < x < b]
                        outside = [x for x in roots if x < a or x > b]
                        if len(inside) == 1 and len(outside) == 1:
                            f = _mk_poly((3, lead), (2, p), (1, q), (0, r))
                            out.append(_Case(f, a, b, inside[0], (outside[0],)))
    return tuple(seeded_order("p3-mvt:cubic-pool", out)[:150])


@lru_cache(maxsize=None)
def _both_inside_cases() -> tuple[_Case, ...]:
    """f'(x) = 평균변화율의 두 근이 *모두* 열린구간 (a, b) 안에 있는 삼차함수(유리근).

    개수형 문항(평균값 정리를 만족시키는 c의 개수)의 재료다. 검산은 열린구간 범위 안의 근을 센다
    (6회차 처분 — `_count_item`). 근이 *전부* 구간 안인 사례라 '구간 안의 c의 개수'가 두 근을 모두
    센다. 1차 은행의 '(구간 밖의 값도 포함)' 개수형은 평균값 정리가 아니라
    도함수 방정식 근 세기였고 단서 없는 문항은 해석이 갈렸다(2차 감사 bad_tag·ambiguous).
    c 필드에는 두 근 중 작은 것을, others에는 큰 것을 담는다.
    """
    out: list[_Case] = []
    for lead in (1, 2, -1, -2):
        for p in range(-8, 9):
            for a in range(-5, 3):
                for b in range(a + 2, 7):
                    m = (_ev({3: lead, 2: p}, Fraction(b)) - _ev({3: lead, 2: p}, Fraction(a))) / (
                        b - a
                    )
                    roots = _quad_rational_roots(Fraction(3 * lead), Fraction(2 * p), -m)
                    if roots is None or len(roots) != 2 or not all(a < x < b for x in roots):
                        continue
                    for q in (-5, -2, 0, 3, 6):
                        r = _const_term(lead * 11 + p * 7 + q * 3 + a * 5 + b)
                        f = _mk_poly((3, lead), (2, p), (1, q), (0, r))
                        out.append(_Case(f, a, b, roots[0], (roots[1],)))
    return tuple(seeded_order("p3-mvt:both-inside-pool", out)[:120])


@lru_cache(maxsize=None)
def _rolle_cubic_cases() -> tuple[_Case, ...]:
    """f(a) = f(b)인 삼차함수 L(x - a)(x - b)(x - r) + d — f'(x) = 0의 유리근 중 하나만 구간 안."""
    out: list[_Case] = []
    for lead in (1, -1, 2):
        for a in range(-3, 3):
            for b in range(a + 2, 5):
                for r in range(-4, 6):
                    expanded = sympy.expand(lead * (_X - a) * (_X - b) * (_X - r))
                    roots = sympy.solve(sympy.diff(expanded, _X), _X)
                    if len(roots) != 2 or not all(t.is_rational for t in roots):
                        continue
                    fracs = [Fraction(int(t.p), int(t.q)) for t in roots]
                    inside = [t for t in fracs if a < t < b]
                    if len(inside) != 1:
                        continue
                    d = _const_term(lead * 7 + a * 5 + b * 3 + r)
                    poly = poly_from_sympy(expanded + d)
                    out.append(
                        _Case(poly, a, b, inside[0], tuple(t for t in fracs if t != inside[0]))
                    )
    return tuple(seeded_order("p3-mvt:rolle-cubic-pool", out)[:80])


def _solve_c(case: _Case, var: str = "x") -> tuple[Fraction, Fraction, tuple[Fraction, ...]] | None:
    """SymPy로 f'(x) = 평균변화율을 풀어 (c, 평균변화율, 구간 밖 유리근)을 낸다 — 정답의 단일 권위.

    열린구간 (a, b) 안의 유리근이 **정확히 1개**가 아니면 None(문항으로 쓰지 않는다).
    """
    f, a, b = case.f, case.a, case.b
    m = sympy.Rational(eval_at(f, b, var) - eval_at(f, a, var), b - a)
    fprime = poly_to_sympy(derivative_of(f, var), var)
    symbol = sympy.Symbol(var)
    roots = sympy.solve(sympy.Eq(fprime, m), symbol)
    rationals = [Fraction(int(r.p), int(r.q)) for r in roots if r.is_rational]
    inside = [r for r in rationals if a < r < b]
    outside = tuple(sorted(r for r in rationals if not a < r < b))
    if len(inside) != 1:
        return None
    return inside[0], Fraction(int(m.p), int(m.q)), outside


# ──────────────────────────────────────────────────────────────────────────
# 조건·표기 조립기
# ──────────────────────────────────────────────────────────────────────────
def _paren(n: int) -> str:
    return f"({n})"


def _rate_str(f: Poly, a: int, b: int, var: str = "x") -> str:
    """평균변화율 우변 — 숫자만으로 쓴 `((f(b)) - (f(a)))/((b) - (a))`."""
    fb, fa = eval_at(f, b, var), eval_at(f, a, var)
    return f"({_paren(fb)} - {_paren(fa)})/({_paren(b)} - {_paren(a)})"


def _minus(b: int, a: int) -> str:
    """읽기용 차 표기 — 음수 뒤에만 괄호('3 - 0'·'4 - (-2)')."""
    return f"{b} - ({a})" if a < 0 else f"{b} - {a}"


def _bounds(a: int, b: int) -> tuple[str, ...]:
    """열린구간 (a, b) 소속 판정 4개 — P3-19 fixture와 같은 형식."""
    return (f"c >= {a}", f"c <= {b}", f"c != {a}", f"c != {b}")


def _deriv_at_c(f: Poly, var: str = "x") -> str:
    return f"Derivative({poly_to_sympy_str(f, var)}, {var}).doit().subs({var}, c)"


def _c_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    case: _Case,
    var: str = "x",
    rhs: str | None = None,
    equation_override: str | None = None,
    ptype: str = _SOLVE,
    choices: tuple[str, ...] | None = None,
    distractors: tuple[tuple[int, str], ...] = (),
    fn: str = "f",
    note: str = "",
) -> DiffItem | None:
    """평균값 정리의 c를 묻는 문항 — 검산 재료는 방정식 1개 + 열린구간 경계 4개.

    `fn`은 해설이 쓰는 함수 기호다 — 발문이 위치를 x(t)·s(t)로 소개한 시간 문항에서 해설이 발문에
    없는 f를 꺼내지 않게 한다(감사 결함 교정: 발문에 정의 없이 f 등장).
    """
    solved = _solve_c(case, var)
    if solved is None:
        return None
    c, m, others = solved
    if c != case.c:
        raise ValueError(f"사례 탐색과 SymPy가 다른 c를 냈다: {c} != {case.c}")
    rate = rhs if rhs is not None else _rate_str(case.f, case.a, case.b, var)
    equation = equation_override or f"{_deriv_at_c(case.f, var)} = {rate}"
    answer = frac_text(c)
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=answer,
        explanation=note
        + _c_explanation(case, c, m, others, var=var, fn=fn, rate_given=rhs is not None),
        conditions=(equation, *_bounds(case.a, case.b)),
        answer_map=(("c", frac_text(c)),),
        problem_type_code=ptype,
        answer_format=answer_format_of(c),
        choices=choices,
        distractors=distractors,
    )


def _c_explanation(
    case: _Case,
    c: Fraction,
    m: Fraction,
    others: tuple[Fraction, ...],
    *,
    var: str,
    fn: str,
    rate_given: bool,
) -> str:
    """c값 해설 — 평균변화율 계산 → 방정식 f'(c) = m → 인수분해 → 구간 판정의 *중간 단계*를 보인다.

    1차 해설은 '평균변화율은 32이다. f'(c) = 32를 풀어 …'로 계산 과정 없이 결론만 냈고, 발문이 준
    직선의 기울기를 평균변화율로 바꿔 부르는 오류도 있었다(2차 감사). 여기서는 발문이 평균변화율을
    주지 않았으면 두 함숫값으로 직접 계산해 보인다.
    """
    a, b = case.a, case.b
    fa, fb = eval_at(case.f, a, var), eval_at(case.f, b, var)
    deriv = derivative_of(case.f, var)
    m_int = int(m)
    if fa == fb and m == 0:
        head = (
            f"{fn}({a}) = {fn}({b})이므로 평균변화율은 0이고, 롤의 정리에 의하여 "
            f"{fn}'(c) = 0인 c가 열린구간 ({a}, {b})에 있다. "
        )
    elif rate_given:
        head = f"구간 [{a}, {b}]에서의 평균변화율은 {frac_text(m)}이다. "
    else:
        head = (
            f"구간 [{a}, {b}]에서의 평균변화율은 ({fn}({b}) - {fn}({a}))/({_minus(b, a)}) = "
            f"({render_difference(fb, fa)})/{b - a} = {frac_text(m)}이다. "
        )
    terms = dict(deriv)
    terms[0] = terms.get(0, 0) - m_int
    eq = tuple(sorted(((e, k) for e, k in terms.items() if k), reverse=True))
    roots = sorted([c, *others])
    eq_text = f"{fn}'(c) = {frac_text(m)}, 즉 {render_poly(eq, 'c')} = 0"
    if eq and eq[0][0] == 2 and len(roots) == 2:
        solve = (
            f"{eq_text}에서 {render_factored(eq, 'c')} = 0이므로 c = {frac_text(roots[0])} 또는 "
            f"c = {frac_text(roots[1])}이다. "
        )
        pick = (
            f"이 중 열린구간 ({a}, {b})에 속하는 것은 c = {frac_text(c)}이고, "
            f"{with_eun_neun(frac_text(others[0]))} 열린구간에 속하지 않으므로 버린다."
        )
        return f"{fn}'({var}) = {render_poly(deriv, var)}이다. {head}{solve}{pick}"
    return (
        f"{fn}'({var}) = {render_poly(deriv, var)}이다. {head}{eq_text}에서 c = {frac_text(c)}"
        f"이고, 이 값은 열린구간 ({a}, {b})에 속한다."
    )


def _case_of(p: object) -> _Case:
    assert isinstance(p, _Case)
    return p


def _frames_params(seed: str, pool: tuple[_Case, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple((case,) for case in seeded_order(seed, pool))


def _fx(case: _Case) -> str:
    return render_poly(case.f)


def _from_time_zero(pool: tuple[_Case, ...]) -> tuple[_Case, ...]:
    """시간 맥락 문항용 풀 — 구간의 시작 시각이 0 이상인 사례만(출발 전 음수 시각 금지)."""
    return tuple(case for case in pool if case.a >= 0)


# ──────────────────────────────────────────────────────────────────────────
# 대표(representative)
# ──────────────────────────────────────────────────────────────────────────
def _rep_frames() -> list[Frame]:
    def r1(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _c_item(
            slot="representative",
            frame_id="rep-find-c-with-interval",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 닫힌구간 [{c.a}, {c.b}]에서 평균값 정리를 "
                f"만족시키는 상수 c의 값을 구하시오. (단, {c.a} < c < {c.b})"
            ),
            case=c,
        )

    def r2(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _c_item(
            slot="representative",
            frame_id="rep-cubic-continuous-differentiable",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여, f는 닫힌구간 [{c.a}, {c.b}]에서 연속이고 "
                f"열린구간 ({c.a}, {c.b})에서 미분가능하다. f'(c) = (f({c.b}) - f({c.a}))/"
                f"({_minus(c.b, c.a)})인 c가 열린구간 ({c.a}, {c.b})에 오직 하나 존재할 때, "
                "c의 값을 구하시오."
            ),
            case=c,
        )

    def r3(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        fa, fb = eval_at(c.f, c.a), eval_at(c.f, c.b)
        return _c_item(
            slot="representative",
            frame_id="rep-tangent-parallel-to-chord",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 곡선 y = f(x) 위의 두 점 A({c.a}, {fa}), "
                f"{with_i_ga(f'B({c.b}, {fb})')} 있다. 열린구간 ({c.a}, {c.b})에서 곡선 위의 점 "
                "P(c, f(c))에서의 "
                "접선이 직선 AB와 평행할 때, c의 값을 구하시오."
            ),
            case=c,
        )

    def r5(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _c_item(
            slot="representative",
            frame_id="rep-two-candidates-one-inside",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 f'(x) = (f({c.b}) - f({c.a}))/({_minus(c.b, c.a)})"
                f"{eul_reul(_minus(c.b, c.a))} "
                f"만족시키는 실수 x는 두 개이다. 이 중 열린구간 ({c.a}, {c.b})에 속하는 것을 "
                "c라 할 때, c의 값을 구하시오."
            ),
            case=c,
        )

    def r6(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _c_item(
            slot="representative",
            frame_id="rep-average-equals-instantaneous",
            text=(
                f"닫힌구간 [{c.a}, {c.b}]에서 함수 f(x) = {_fx(c)}의 평균변화율과 x = c에서의 "
                f"미분계수가 같아지는 c ({c.a} < c < {c.b})의 값을 구하시오."
            ),
            case=c,
        )

    # 5회차 감사(2026-10-08) 처분 — 이차함수의 평균값 정리는 c가 늘 구간의 중점이라 미분 없이 풀렸다
    # (판정기 T-quadratic-mean-value · 이차 풀 `_quad_cases`·`_rolle_cases` 삭제). c값 틀은 전부
    # 삼차 풀을 쓴다(c ≠ 중점·구간 안 자연수 하나뿐 같은 우연 일치는 매개변수 거부 조건이 건너뛴다).
    return [
        Frame("rep-find-c-with-interval", _frames_params("p3-mvt:r1", _cubic_cases()), r1),
        Frame(
            "rep-cubic-continuous-differentiable", _frames_params("p3-mvt:r2", _cubic_cases()), r2
        ),
        Frame("rep-tangent-parallel-to-chord", _frames_params("p3-mvt:r3", _cubic_cases()), r3),
        # 3차 감사(2026-10) bad_tag 처분 — 'rep-average-rate-given'(발문이 평균변화율 값과 방정식
        # f'(c) = m을 모두 줘 일차방정식 하나만 남던 틀)은 삭제했다(우회로 판정기 T06-given-rate).
        Frame("rep-two-candidates-one-inside", _frames_params("p3-mvt:r5", _cubic_cases()), r5),
        Frame("rep-average-equals-instantaneous", _frames_params("p3-mvt:r6", _cubic_cases()), r6),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 기본(basic) — 평균변화율·롤의 정리·시간 모델
# ──────────────────────────────────────────────────────────────────────────
def _value_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    value: Fraction,
    condition: str,
    explanation: str,
    ptype: str = _EVAL,
    unknown: str = "y",
    setup: str | None = None,
) -> DiffItem:
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=frac_text(value),
        explanation=explanation,
        conditions=condition,
        answer_map=((unknown, frac_text(value)),),
        problem_type_code=ptype,
        answer_format=answer_format_of(value),
        solution_setup=setup,
    )


def _mvt_setup(f: Poly, a: int, b: int, var: str = "x") -> str:
    """풀이 단계 출발식 f'(var) = (f(b) - f(a))/(b - a) — 평균값 정리의 결론(도함수 = 평균변화율).

    개수·구간 밖 근 문항의 검산 조건은 이 식을 미리 정리한 다항식이라 도함수가 없다. 해설 첫 단계
    그대로 도함수에서 출발한다(`DiffItem.solution_setup`).
    """
    fa, fb = eval_at(f, a, var), eval_at(f, b, var)
    return (
        f"Derivative({poly_to_sympy_str(f, var)}, {var}).doit() = "
        f"(({fb}) - ({fa}))/(({b}) - ({a}))"
    )


def _witness_line(slope: int, a: int, pv: int) -> str:
    """도함수가 늘 slope인 함수(f(a) = pv를 지나는 일차·상수함수).

    해설이 등호 성립을 보이는 함수다.
    """
    return poly_to_sympy_str(((1, slope), (0, pv - slope * a)))


def _count_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    case: _Case,
    var: str = "x",
    fn: str = "f",
    note: str = "",
) -> KindedDiffItem | None:
    """평균값 정리를 만족시키는 c(구간 *안*)의 개수 — `real_root_count` 개념형 검산.

    검산 조건은 f'(x) - (평균변화율) = 0과 **열린구간 범위**(`x > a`·`x < b`)다 — 발문이 세는 범위와
    같은 범위에서 근을 센다(6회차 은행 감사 처분 · 판정자 지적 c743fda0 · 판정기 V-count-interval).
    종전 검산은 방정식 하나만 둬 실수 전체의 근을 셌고, 근이 전부 구간 안인 사례만 골라 값이 우연히
    같았을 뿐 다른 문제를 가리켰다. 재료 풀은 지금도 두 근이 모두 구간 안인 사례다(답 2).
    """
    eq, m = _fprime_eq_rate_poly(case, var)
    roots = sympy.real_roots(sympy.Poly(poly_to_sympy(eq, var), sympy.Symbol(var)))
    distinct = sorted(set(roots))
    if not distinct or not all(case.a < r < case.b for r in distinct):
        return None
    if not all(r.is_rational for r in distinct):
        return None
    n = len(distinct)
    a, b = case.a, case.b
    fa, fb = eval_at(case.f, a, var), eval_at(case.f, b, var)
    # 3차 감사 bad_explanation — 발문에 없는 기호 c를 소개 없이 쓰던 해설(시각·x좌표를 c라 둔다).
    if re.search(r"(?<![A-Za-z])c(?![A-Za-z])", text) is None:
        note += (
            "조건을 만족시키는 시각을 c라 하자. "
            if var == "t"
            else "조건을 만족시키는 점의 x좌표를 c라 하자. "
        )
    listed = ", ".join(frac_text(Fraction(int(r.p), int(r.q))) for r in distinct)
    solve = (
        f"{render_poly(eq, 'c')} = 0이고, {render_factored(eq, 'c')} = 0의 근은 c = {listed}이다"
        if eq[0][0] == 2
        else f"{render_poly(eq, 'c')} = 0이고 그 근은 c = {listed} 하나이다"
    )
    explanation = (
        f"{note}{fn}'({var}) = {render_poly(derivative_of(case.f, var), var)}이다. "
        f"구간 [{a}, {b}]에서의 평균변화율은 ({fn}({b}) - {fn}({a}))/({_minus(b, a)}) = "
        f"({render_difference(fb, fa)})/{b - a} = {frac_text(m)}이므로 {fn}'(c) = "
        f"{frac_text(m)}에서 "
        f"{solve}. "
        + (
            f"두 근이 모두 열린구간 ({a}, {b})에 속하므로 구하는 개수는 {n}이다."
            if n == 2
            else f"이 근은 열린구간 ({a}, {b})에 속하므로 구하는 개수는 {n}이다."
        )
    )
    return KindedDiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(n),
        explanation=explanation,
        conditions=(f"{poly_to_sympy_str(eq, var)} = 0", f"{var} > {a}", f"{var} < {b}"),
        answer_map=(),
        problem_type_code=_COUNT,
        answer_format=answer_format_of(n),
        answer_kind="real_root_count",
        solution_setup=_mvt_setup(case.f, a, b, var),
    )


def _count_pool(seed: str) -> tuple[tuple[object, ...], ...]:
    """개수형 재료 — 두 근이 모두 구간 안인 삼차(답 2).

    5회차 감사(2026-10-08) 처분 — 종전 풀은 이차(답 1)를 섞었는데, 이차는 평균값 정리의 c가 늘 중점
    하나라 어떤 경로('적어도 하나 → 1'·판별식·중점 암기)로도 1이 나왔다(판정자 지적 033597a2 ·
    판정기 T-quadratic-mean-value).
    """
    return tuple((case,) for case in seeded_order(seed, _both_inside_cases()))


def _bound_params(seed: str) -> tuple[tuple[object, ...], ...]:
    """평균값 정리 부등식(도함수의 범위 → 함숫값의 범위) 재료 (p, m, M, a, b)."""
    combos = [
        (pv, lo, hi, a, a + width)
        for pv in (-3, 1, 4, 6)
        for lo, hi in ((-2, 3), (1, 4), (-1, 2), (2, 5), (-3, 1), (0, 6))
        for a in (0, 1, 2, -1)
        for width in (2, 3, 4)
    ]
    return tuple(seeded_order(seed, combos))


def _bound_item(*, slot: str, frame_id: str, p: tuple[object, ...], side: str) -> DiffItem:
    """도함수가 위(아래)로 막힌 함수의 f(b)가 가질 수 있는 가장 큰(작은) 값 — 평균값 정리의
    부등식 활용.

    side: "upper"(f'(x) <= M → 최댓값) · "lower"(f'(x) >= m → 최솟값) · "both"(두 극단의 합).
    검산은 산술 재확인(평균값 정리로 얻은 식 p + M(b - a)의 값)이다 — 부등식 추론 자체는 해설이
    보인다.
    """
    pv, lo, hi, a, b = (int(str(v)) for v in p)
    width = b - a
    top, bottom = pv + hi * width, pv + lo * width
    mvt = (
        f"평균값 정리에 의하여 f({b}) - f({a}) = f'(c)({_minus(b, a)})인 c가 열린구간 ({a}, {b})에 "
        f"존재한다. "
    )
    if side == "upper":
        text = (
            f"함수 f(x)는 모든 실수 x에서 미분가능하고 f'(x) ≤ {hi}이다. f({a}) = {pv}일 때, "
            f"f({b})의 값이 될 수 있는 가장 큰 값을 구하시오."
        )
        value = top
        line = render_poly(((1, hi), (0, pv - hi * a)))
        body = (
            f"f'(c) ≤ {hi}이므로 {render_difference(f'f({b})', pv)} ≤ {hi * width}, 즉 "
            f"f({b}) ≤ {top}이다. "
            f"f(x) = {line}이면 등호가 성립하므로 가장 큰 값은 {top}이다."
        )
        cond = f"{pv} + ({hi})*(({b}) - ({a})) = y"
    elif side == "lower":
        text = (
            f"함수 f(x)는 모든 실수 x에서 미분가능하고 f'(x) ≥ {lo}이다. f({a}) = {pv}일 때, "
            f"f({b})의 값이 될 수 있는 가장 작은 값을 구하시오."
        )
        value = bottom
        line = render_poly(((1, lo), (0, pv - lo * a)))
        body = (
            f"f'(c) ≥ {lo}이므로 {render_difference(f'f({b})', pv)} ≥ {lo * width}, 즉 "
            f"f({b}) ≥ {bottom}이다. "
            f"f(x) = {line}이면 등호가 성립하므로 가장 작은 값은 {bottom}이다."
        )
        cond = f"{pv} + ({lo})*(({b}) - ({a})) = y"
    else:
        text = (
            f"함수 f(x)는 모든 실수 x에서 미분가능하고 {lo} ≤ f'(x) ≤ {hi}이다. f({a}) = {pv}일 "
            f"때, f({b})의 값이 될 수 있는 가장 큰 값과 가장 작은 값의 합을 구하시오."
        )
        value = top + bottom
        body = (
            f"{lo} ≤ f'(c) ≤ {hi}이므로 {lo * width} ≤ {render_difference(f'f({b})', pv)} ≤ "
            f"{hi * width}, 즉 "
            f"{bottom} ≤ f({b}) ≤ {top}이다. 두 끝값은 각각 f(x)가 {_extreme_line(lo)}일 때와 "
            f"{_extreme_line(hi)}일 때 실제로 나오므로 구하는 합은 {top} + "
            f"{_paren_if_neg(bottom)} = {value}이다."
        )
        cond = f"({pv} + ({hi})*(({b}) - ({a}))) + ({pv} + ({lo})*(({b}) - ({a}))) = y"
    # 풀이 단계 출발식 — f(b) = f(a) + f'(c)(b - a)에서 f'(c)가 끝값일 때(해설의 등호 성립 함수).
    span = f"(({b}) - ({a}))"
    upper = f"({pv}) + Derivative({_witness_line(hi, a, pv)}, x)*{span}"
    lower = f"({pv}) + Derivative({_witness_line(lo, a, pv)}, x)*{span}"
    body_expr = {"upper": upper, "lower": lower}.get(side, f"{upper} + {lower}")
    return _value_item(
        slot=slot,
        frame_id=frame_id,
        text=text,
        value=Fraction(value),
        condition=cond,
        explanation=mvt + body,
        setup=f"({body_expr}).doit() = y",
    )


def _extreme_line(slope: int) -> str:
    """끝값을 내는 함수의 이름 — 기울기 0이면 상수함수.

    3차 감사: '기울기 0인 일차함수'는 틀린 용어다.
    """
    return "상수함수" if slope == 0 else f"기울기가 {slope}인 일차함수"


def _paren_if_neg(value: int) -> str:
    return f"({value})" if value < 0 else str(value)


def _increasing_from_zero(f: Poly, var: str) -> bool:
    """t >= 0에서 도함수가 양수인가(이동 거리 맥락 — 거리가 줄어들 수 없다)."""
    d = poly_to_sympy(derivative_of(f, var), var)
    symbol = sympy.Symbol(var)
    if d.subs(symbol, 0) <= 0:
        return False
    return all(r < 0 for r in sympy.real_roots(sympy.Poly(d, symbol)))


def _basic_frames() -> list[Frame]:
    def b2(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _c_item(
            slot="basic",
            frame_id="basic-difference-equals-derivative-times-length",
            text=(
                f"삼차함수 f(x) = {_fx(c)}에 대하여 f({c.b}) - f({c.a}) = f'(c)({_minus(c.b, c.a)})"
                f"{eul_reul(_minus(c.b, c.a))} "
                f"만족시키는 c ({c.a} < c < {c.b})의 값을 구하시오."
            ),
            case=c,
        )

    def b3(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _c_item(
            slot="basic",
            frame_id="basic-rolle-theorem",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 f({c.a}) = f({c.b})이다. 닫힌구간 "
                f"[{c.a}, {c.b}]에서 롤의 정리를 만족시키는 c의 값을 구하시오."
            ),
            case=c,
            rhs="0",
        )

    def b6(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        ft = render_poly(c.f, "t")
        return _c_item(
            slot="basic",
            frame_id="basic-time-average-velocity",
            text=(
                f"직선 위를 움직이는 점 P의 시각 t에서의 위치가 x(t) = {ft}일 때, "
                f"시각 t = {c.a}부터 t = {c.b}까지의 평균속도와 순간속도가 같아지는 시각 "
                f"t = c ({c.a} < c < {c.b})의 값을 구하시오."
            ),
            case=c,
            var="t",
            fn="x",
        )

    def b8(p: tuple[object, ...]) -> DiffItem | None:
        # 삼차함수의 롤의 정리 — f'(x) = 0의 두 근 중 하나만 열린구간 안(구간 판정까지 요구).
        c = _case_of(p[0])
        return _c_item(
            slot="basic",
            frame_id="basic-rolle-cubic",
            text=(
                f"삼차함수 f(x) = {_fx(c)}에 대하여 f({c.a}) = f({c.b})이므로 롤의 정리에 의하여 "
                f"f'(c) = 0인 c가 열린구간 ({c.a}, {c.b})에 존재한다. 이 c의 값을 구하시오."
            ),
            case=c,
            rhs="0",
        )

    def b9(p: tuple[object, ...]) -> DiffItem | None:
        return _bound_item(slot="basic", frame_id="basic-mvt-upper-bound", p=p, side="upper")

    def b10(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _count_item(
            slot="basic",
            frame_id="basic-count-mvt-points",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 닫힌구간 [{c.a}, {c.b}]에서 평균값 정리를 "
                "만족시키는 실수 c의 개수를 구하시오."
            ),
            case=c,
        )

    # 1차 basic의 평균변화율 계산만·두 점 직선 기울기만·f(b) - f(a)만·'AB 기울기보다 k만큼 큰
    # 접선 개수' 틀은 평균값 정리를 쓰지 않는 선수 계산이라 삭제했다(2차 감사 bad_tag) — 대신 롤의
    # 정리(삼차)·평균값 정리 부등식·구간 안 c의 개수로 채운다.
    return [
        Frame(
            "basic-difference-equals-derivative-times-length",
            _frames_params("p3-mvt:b2", _cubic_cases()),
            b2,
        ),
        # 5회차 감사 — 이차 롤의 정리는 c가 꼭짓점(대칭축 = f(a) = f(b)인 두 점의 중점)이라 미분
        # 없이 풀렸다(판정자 지적 4b597448·59bacdba). 삼차 롤 풀로 바꿨다(f'(x) = 0의 근 중 하나만
        # 구간 안).
        Frame("basic-rolle-theorem", _frames_params("p3-mvt:b3", _rolle_cubic_cases()), b3),
        Frame(
            "basic-time-average-velocity",
            _frames_params("p3-mvt:b6", _from_time_zero(_cubic_cases())),
            b6,
        ),
        Frame("basic-rolle-cubic", _frames_params("p3-mvt:b8", _rolle_cubic_cases()), b8),
        Frame("basic-mvt-upper-bound", _bound_params("p3-mvt:b9"), b9),
        Frame("basic-count-mvt-points", _count_pool("p3-mvt:b10"), b10),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 응용(applied) — 미지수·평행 접선·시간 모델
# ──────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=None)
def _k_cases() -> tuple[tuple[int, int, int, Fraction], ...]:
    """f = x^3 + kx^2 — (k, a, b, c): c가 구간 안의 유일한 근이고 2c != a+b(k가 유일)."""
    out: list[tuple[int, int, int, Fraction]] = []
    for k in (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5):
        for a in range(-3, 2):
            for b in range(a + 2, 5):
                m = Fraction(a * a + a * b + b * b + k * (a + b))
                roots = _quad_rational_roots(Fraction(3), Fraction(2 * k), -m)
                if roots is None or len(roots) != 2:
                    continue
                inside = [x for x in roots if a < x < b]
                if len(inside) == 1 and 2 * inside[0] != a + b:
                    out.append((k, a, b, inside[0]))
    return tuple(seeded_order("p3-mvt:k-pool", out)[:80])


def _unique_k(k: int, a: int, b: int, c: Fraction) -> bool:
    """f'(c) = 평균변화율이 k에 대한 일차방정식이고 해가 k 하나임을 SymPy로 확인한다."""
    ks = sympy.Symbol("k")
    f_expr = _X**3 + ks * _X**2
    lhs = sympy.diff(f_expr, _X).subs(_X, sympy.Rational(c.numerator, c.denominator))
    rhs = (f_expr.subs(_X, b) - f_expr.subs(_X, a)) / (b - a)
    sols = sympy.solve(sympy.Eq(lhs, rhs), ks)
    return bool(sols == [k])


def _tangent_k_text(c: Fraction) -> str:
    """f'(c) = 3c^2 + 2ck를 k의 일차식으로 — c가 정수면 정리한 꼴('-6k + 12'), 분수면 대입 꼴."""
    if c.denominator == 1:
        ci = int(c)
        if ci == 0:
            return "0"
        return render_poly(((1, 2 * ci), (0, 3 * ci * ci)), "k")
    cs = frac_text(c)
    return f"3({cs})^2 + 2({cs})k"


def _k_item(
    slot: str,
    frame_id: str,
    text_of: object,
    p: tuple[object, ...],
    *,
    points_in_question: bool,
) -> DiffItem | None:
    """평균값 정리의 c로 미지수 k를 구하는 문항.

    `points_in_question`이 False면(발문이 구간만 주고 점·접선을 말하지 않는다) 해설도 '두 점을 잇는
    직선'·'접점' 대신 발문의 말(구간에서의 평균변화율·f'(c))로 쓴다 — 4차 감사 bad_explanation
    (소개 없이 '두 점'·'접점'이 등장 · 판정기 E-object-intro).
    """
    k, a, b, c = int(str(p[0])), int(str(p[1])), int(str(p[2])), p[3]
    assert isinstance(c, Fraction)
    if not _unique_k(k, a, b, c):
        return None
    assert callable(text_of)
    cs = frac_text(c)
    rate = render_affine(a * a + a * b + b * b, a + b, "k")
    if points_in_question:
        explanation = (
            f"f'(x) = 3x^2 + 2kx이다. 두 점을 잇는 직선의 기울기는 구간 [{a}, {b}]에서의 "
            f"평균변화율이므로 (f({b}) - f({a}))/({_minus(b, a)}) = {rate}이다. "
            f"접점 x = {cs}에서의 접선의 기울기는 f'({cs}) = {_tangent_k_text(c)}이고 "
            "이 값이 평균변화율과 같아야 하므로 "
            f"{_tangent_k_text(c)} = {rate}에서 k = {k}이다."
        )
    else:
        explanation = (
            f"f'(x) = 3x^2 + 2kx이다. 구간 [{a}, {b}]에서의 평균변화율은 "
            f"(f({b}) - f({a}))/({_minus(b, a)}) = {rate}이다. 평균값 정리에 따라 f'(c)가 이 "
            f"평균변화율과 같고 c의 값이 {cs}이므로 f'({cs}) = {_tangent_k_text(c)}에서 "
            f"{_tangent_k_text(c)} = {rate}이다. 따라서 k = {k}이다."
        )
    condition = (
        f"Derivative(x**3 + k*x**2, x).doit().subs(x, {cs}) = "
        f"(({b})**3 + k*({b})**2 - (({a})**3 + k*({a})**2))/(({b}) - ({a}))"
    )
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text_of(a, b, cs),
        answer_text=str(k),
        explanation=explanation,
        conditions=condition,
        answer_map=(("k", str(k)),),
        problem_type_code=_SOLVE,
        answer_format=answer_format_of(k),
    )


def _applied_frames() -> list[Frame]:
    def a1(p: tuple[object, ...]) -> DiffItem | None:
        return _k_item(
            "applied",
            "applied-find-k-from-c",
            lambda a, b, cs: (
                f"함수 f(x) = x^3 + kx^2에 대하여 닫힌구간 [{a}, {b}]에서 평균값 정리를 "
                f"만족시키는 c의 값이 {cs}일 때, 상수 k의 값을 구하시오."
            ),
            p,
            points_in_question=False,
        )

    def a2(p: tuple[object, ...]) -> DiffItem | None:
        # 1차는 '직선 y = 32x - 11과 평행'으로 *아무 직선*을 주고 해설은 그 기울기를 평균변화율이라
        # 불렀다(평균값 정리 문항이 아니었다 — 2차 감사). 이제 할선 AB를 x좌표로만 주어 학생이 두
        # 함숫값으로 AB의 기울기(= 평균변화율)를 구하고 c를 구간 안에서 고르게 한다.
        c = _case_of(p[0])
        return _c_item(
            slot="applied",
            frame_id="applied-tangent-parallel-to-chord-from-x",
            text=(
                f"함수 f(x) = {_fx(c)}의 그래프 위의 x좌표가 {c.a}, {c.b}인 두 점을 각각 A, B라 "
                f"하자. 열린구간 ({c.a}, {c.b})에서 곡선 y = f(x) 위의 점 P(c, f(c))에서의 접선이 "
                "직선 AB와 평행할 때, c의 값을 구하시오."
            ),
            case=c,
            note="직선 AB의 기울기는 구간에서의 평균변화율과 같다. ",
        )

    def a3(p: tuple[object, ...]) -> DiffItem | None:
        # 이동 거리는 출발 순간 0이고 줄어들지 않는다 — 상수항을 0으로 두고(c값은 상수항과 무관)
        # t >= 0에서 증가하는 사례만 쓴다(2차 감사: s(0) = 1 km 모순).
        src = _case_of(p[0])
        f0 = tuple((e, k) for e, k in src.f if e != 0)
        if not _increasing_from_zero(f0, "t"):
            return None
        c = _Case(f0, src.a, src.b, src.c, src.others)
        ft = render_poly(c.f, "t")
        return _c_item(
            slot="applied",
            frame_id="applied-car-instantaneous-equals-average",
            text=(
                f"자동차가 출발한 지 t시간 후의 이동 거리가 s(t) = {ft} (km)이다. "
                + (
                    f"출발 시각부터 {c.b}시간 후까지"
                    if c.a == 0
                    else f"출발 후 {c.a}시간부터 {c.b}시간까지"
                )
                + f"의 평균 속도와 순간 속도가 같아지는 시각 t = c ({c.a} < c < {c.b})의 값을 "
                "구하시오."
            ),
            case=c,
            var="t",
            fn="s",
        )

    def a4(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        # 삼차함수 — 왼쪽 끝점 a를 미지수로 둔다(b와 c가 주어진다). 끝점의 방정식은 이차라 근이
        # 둘이고, 다른 근은 'a < b' 조건으로 버려지는 사례만 쓴다(`_endpoint_item`).
        return _endpoint_item(
            "applied", "applied-find-left-endpoint", c.f, c, unknown="a", fixed_is_left=False
        )

    def a5(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _endpoint_item(
            "applied", "applied-find-chord-endpoint", c.f, c, unknown="b", fixed_is_left=True
        )

    return [
        Frame("applied-find-k-from-c", tuple(_k_params("p3-mvt:a1")), a1),
        Frame(
            "applied-tangent-parallel-to-chord-from-x",
            _frames_params("p3-mvt:a2", _cubic_cases()),
            a2,
        ),
        Frame(
            "applied-car-instantaneous-equals-average",
            _frames_params("p3-mvt:a3", _from_time_zero(_cubic_cases())),
            a3,
        ),
        # 5회차 감사 처분 — 이차함수의 끝점 미지수형은 c가 중점이라 '2c - 끝점'으로 풀렸다(판정자
        # 지적 24d7eb97·db749952). 삼차 풀로 바꿨다(중점 경로와 정답이 같으면 매개변수 거부 조건이
        # 뺀다).
        Frame("applied-find-left-endpoint", _frames_params("p3-mvt:a4", _cubic_cases()), a4),
        Frame("applied-find-chord-endpoint", _frames_params("p3-mvt:a5", _cubic_cases()), a5),
    ]


def _k_params(seed: str) -> list[tuple[object, ...]]:
    return [tuple(case) for case in seeded_order(seed, _k_cases())]


def _endpoint_quadratic(f: Poly, fixed: int, value: Fraction) -> Poly:
    """(f(u) - f(fixed))/(u - fixed) - value를 u의 다항식으로 — 삼차 f면 이차식(정수 계수).

    f(x) = Lx^3 + px^2 + qx + r이면 (f(u) - f(fixed))/(u - fixed) = L(u^2 + fixed·u + fixed^2)
    + p(u + fixed) + q이다(인수 (u - fixed)를 약분한 몫).
    """
    terms = dict(f)
    lead, quad, lin = terms.get(3, 0), terms.get(2, 0), terms.get(1, 0)
    const = lead * fixed * fixed + quad * fixed + lin - value
    if Fraction(const).denominator != 1:
        raise ValueError("끝점 방정식의 상수항이 정수가 아니다")
    raw = ((2, lead), (1, lead * fixed + quad), (0, int(const)))
    return tuple((e, k) for e, k in raw if k)


def _endpoint_explanation(
    f: Poly,
    fixed: int,
    c: Fraction,
    *,
    unknown: str,
    fixed_is_left: bool,
    answer: int,
    other: Fraction,
) -> str:
    """끝점 미지수 해설 — 도함수 식 → c에서의 미분계수 → 미지 끝점의 평균변화율(약분한 이차식) →
    방정식의 두 근 → 구간 조건으로 고르기.

    5회차 감사(2026-10-08) 처분 — 이차함수 틀은 c가 늘 중점이라 '2c - 끝점'으로 풀렸다. 삼차함수는
    평균변화율이 미지 끝점의 이차식이라 방정식의 근이 둘이고, 구간 조건(미지 끝점 > 또는 < 고정
    끝점)으로 하나를 고른다(3차 감사 처분의 '도함수 식·평균변화율 계산 단계'도 그대로 보인다).
    """
    fp = derivative_of(f)
    slope = Fraction(sum(Fraction(k) * c ** (e - 1) * e for e, k in f if e >= 1))
    slope_text = frac_text(slope)
    cs = frac_text(c)
    terms = dict(f)
    lead, quad, lin = terms.get(3, 0), terms.get(2, 0), terms.get(1, 0)
    rate = tuple(
        (e, k)
        for e, k in (
            (2, lead),
            (1, lead * fixed + quad),
            (0, lead * fixed * fixed + quad * fixed + lin),
        )
        if k
    )
    rate_text = render_poly(rate, unknown)
    moved = _endpoint_quadratic(f, fixed, slope)
    if fixed_is_left:
        span = render_poly(((1, 1), (0, -fixed)), unknown)  # 'b - 1'
        diff_head = f"f({unknown}) - f({fixed})"
        side = f"{unknown} > {fixed}"
    else:
        span = render_affine(fixed, -1, unknown)  # '1 - a'
        diff_head = f"f({fixed}) - f({unknown})"
        side = f"{unknown} < {fixed}"
    span_paren = f"({span})" if (" " in span or span.startswith("-")) else span
    roots = sorted((Fraction(answer), other))
    return (
        f"f'(x) = {render_poly(fp)}이고, 평균값 정리를 만족시키는 c가 {cs}이므로 그 점에서의 "
        f"미분계수는 f'({cs})의 값인 {slope_text}이다. 구간의 평균변화율은 "
        f"({diff_head})/{span_paren}이고, {with_eul_reul(diff_head)} 인수분해하면 "
        f"{span_paren}({rate_text})이므로 평균변화율은 {rate_text}이다. 평균값 정리에 의하여 "
        f"{rate_text} = {slope_text}, 즉 {render_poly(moved, unknown)} = 0에서 "
        f"{render_factored(moved, unknown)} = 0이므로 {unknown} = {frac_text(roots[0])} 또는 "
        f"{unknown} = {frac_text(roots[1])}이다. {side}이므로 {unknown} = {answer}이다."
    )


def _endpoint_item(
    slot: str,
    frame_id: str,
    f: Poly,
    case: _Case,
    *,
    unknown: str,
    fixed_is_left: bool,
    text: str | None = None,
) -> DiffItem | None:
    """삼차함수에서 c와 한 끝점이 주어질 때 다른 끝점(미지수)을 구한다.

    f'(c) = (f(u) - f(fixed))/(u - fixed)는 u의 이차방정식이다 — 근 둘 중 정답이 아닌 근이 조건
    `unknown > 고정 끝점`(또는 `<`)을 어기는 사례만 쓴다(해가 발문 조건으로 하나로 정해진다). 구간
    퇴화(u = fixed) 가짜 근도 같은 조건이 가른다.
    """
    a, b, c = case.a, case.b, case.c
    fixed = a if fixed_is_left else b
    answer = b if fixed_is_left else a
    sym = sympy.Symbol(unknown)
    f_unknown = poly_to_sympy(f).subs(_X, sym)
    f_fixed = eval_at(f, fixed)
    cs = frac_text(c)
    deriv = f"Derivative({poly_to_sympy_str(f)}, x).doit().subs(x, {cs})"
    if fixed_is_left:
        rate = f"({sympy.sstr(f_unknown)} - ({f_fixed}))/({unknown} - ({fixed}))"
        side = f"{unknown} > {fixed}"
    else:
        rate = f"({f_fixed} - ({sympy.sstr(f_unknown)}))/(({fixed}) - {unknown})"
        side = f"{unknown} < {fixed}"
    slope = sympy.diff(poly_to_sympy(f), _X).subs(_X, sympy.Rational(c.numerator, c.denominator))
    try:
        moved = _endpoint_quadratic(f, fixed, Fraction(int(slope.p), int(slope.q)))
    except ValueError:
        return None
    roots = sympy.solve(poly_to_sympy(moved, unknown), sym)
    if sympy.Integer(answer) not in roots or len(roots) != 2:
        return None
    other = next(r for r in roots if r != answer)
    if not other.is_rational:
        return None
    other_frac = Fraction(int(other.p), int(other.q))
    if (other_frac > fixed) if fixed_is_left else (other_frac < fixed):
        return None  # 다른 근도 구간 조건을 만족시키면 답이 하나로 정해지지 않는다
    if text is None:
        if fixed_is_left:
            text = (
                f"함수 f(x) = {render_poly(f)}에 대하여 구간 [{a}, b] (b > {a})에서 평균값 정리를 "
                f"만족시키는 c의 값이 {cs}일 때, b의 값을 구하시오."
            )
        else:
            text = (
                f"함수 f(x) = {render_poly(f)}에 대하여 구간 [a, {b}] (a < {b})에서 평균값 정리를 "
                f"만족시키는 c의 값이 {cs}일 때, a의 값을 구하시오."
            )
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(answer),
        explanation=_endpoint_explanation(
            f,
            fixed,
            c,
            unknown=unknown,
            fixed_is_left=fixed_is_left,
            answer=answer,
            other=other_frac,
        ),
        conditions=(f"{deriv} = {rate}", side),
        answer_map=((unknown, str(answer)),),
        problem_type_code=_SOLVE,
        answer_format=answer_format_of(answer),
    )


# ──────────────────────────────────────────────────────────────────────────
# 오개념 유발(misconception_trigger) — 롤의 정리와 혼동해 f'(c) = 0을 푼 값이 선지에 있다(M0674)
# ──────────────────────────────────────────────────────────────────────────
def _rolle_wrong_values(case: _Case) -> tuple[Fraction, ...]:
    """롤의 정리와 혼동한 값 — f'(x) = 0의 유리근 중 정답 c가 아닌 것(구간 안을 우선)."""
    roots = sympy.solve(sympy.Eq(poly_to_sympy(derivative_of(case.f)), 0), _X)
    values = [Fraction(int(r.p), int(r.q)) for r in roots if r.is_rational]
    inside = [v for v in values if case.a < v < case.b and v != case.c]
    return tuple(inside)


def _mc_c_item(
    *,
    frame_id: str,
    text: str,
    case: _Case,
    var: str = "x",
    fillers_seed: str,
    fn: str = "f",
    note: str = "",
) -> DiffItem | None:
    """c를 묻는 객관식 — 롤의 정리와 혼동한 값(M0674)을 오답 선지에 둔다."""
    solved = _solve_c(case, var)
    if solved is None:
        return None
    c, m, others = solved
    wrong = _rolle_wrong_values(case)
    if not wrong:
        return None
    pool: list[Fraction] = []
    for cand in (
        *others,
        Fraction(case.a + case.b, 2) if Fraction(case.a + case.b, 2) != c else None,
        m if m != c else None,
        Fraction(case.b),
        Fraction(case.a),
        c + 1,
        c - 1,
        c + Fraction(1, 2),
    ):
        if cand is not None and cand != c and cand not in wrong and cand not in pool:
            pool.append(cand)
    entries = [ChoiceEntry(frac_text(c), is_correct=True, sort_key=float(c))]
    entries.append(ChoiceEntry(frac_text(wrong[0]), _MID, sort_key=float(wrong[0])))
    taken = {c, wrong[0]}
    for cand in seeded_order(fillers_seed, pool):
        if len(entries) == 4:
            break
        if cand not in taken:
            entries.append(ChoiceEntry(frac_text(cand), sort_key=float(cand)))
            taken.add(cand)
    if len(entries) != 4:
        return None
    try:
        choices, answer, distractors = build_choices(entries, shuffle_seed=fillers_seed)
    except ValueError:
        return None
    base = _c_item(
        slot="misconception_trigger",
        frame_id=frame_id,
        text=text,
        case=case,
        var=var,
        choices=choices,
        distractors=distractors,
        fn=fn,
        note=note,
    )
    if base is None:
        return None
    assert answer == base.answer_text
    # 오개념(M0674 — 롤의 정리와 혼동)으로 생기는 오답 선지가 왜 틀렸는지 해설이 짚는다.
    wrong_text = frac_text(wrong[0])
    # 5회차 감사 해설 결함(44e7281a) 교정 — '~인데, ~인데' 비문과 수 하나를 '롤의 정리의 결론'이라
    # 부른 용어 오용을 고친다(결론은 'f'(c) = 0인 c가 존재한다'는 명제다).
    trap = (
        f" 방정식 {fn}'(c) = 0의 근 {with_eun_neun(wrong_text)} 롤의 정리를 적용할 때 구하는 "
        f"값이다. 롤의 정리는 {with_wa_gwa(f'{fn}({case.a})')} {fn}({case.b})의 값이 같을 때만 쓸 "
        f"수 있다. 여기서는 두 값이 다르므로 {with_eun_neun(wrong_text)} 답이 아니다."
    )
    return dataclasses.replace(base, explanation=base.explanation + trap)


def _misconception_frames() -> list[Frame]:
    def m1(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _mc_c_item(
            frame_id="mc-closed-interval-find-c",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 닫힌구간 [{c.a}, {c.b}]에서 평균값 정리를 "
                "만족시키는 c의 값은?"
            ),
            case=c,
            fillers_seed=f"mc-q:{c.a}:{c.b}:{_fx(c)}",
        )

    def m2(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _mc_c_item(
            frame_id="mc-cubic-find-c",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 열린구간 ({c.a}, {c.b})에서 평균값 정리의 "
                "결론을 만족시키는 c의 값으로 옳은 것은?"
            ),
            case=c,
            fillers_seed=f"mc-c:{c.a}:{c.b}:{_fx(c)}",
        )

    def m3(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        ft = render_poly(c.f, "t")
        return _mc_c_item(
            frame_id="mc-time-find-c",
            # 6회차 은행 감사 처분 — 삼차화로 x'(c) = (평균속도)의 해가 둘인데 발문에 c의 범위가
            # 없어 구간 밖 근도 발문 조건을 만족했다(판정자 지적 bdc71cfe·d524ac47 · 판정기
            # U-extra-solution). 열린구간 조건을 발문에 둔다 — 구간 밖 근이 선지에 있어도 정답이
            # 하나로 정해진다.
            text=(
                f"직선 위를 움직이는 점의 시각 t에서의 위치가 x(t) = {ft}일 때, t = {c.a}부터 "
                f"t = {c.b}까지의 평균속도와 같은 순간속도를 갖는 시각 t = c의 값은? "
                f"(단, {c.a} < c < {c.b})"
            ),
            case=c,
            var="t",
            fn="x",
            fillers_seed=f"mc-t:{c.a}:{c.b}:{ft}",
        )

    def m4(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        fa, fb = eval_at(c.f, c.a), eval_at(c.f, c.b)
        return _mc_c_item(
            frame_id="mc-tangent-parallel-find-c",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 곡선 y = f(x) 위의 두 점 A({c.a}, {fa}), "
                f"B({c.b}, {fb}) 사이의 곡선 위에서 직선 AB와 평행한 접선을 갖는 점의 x좌표는?"
            ),
            case=c,
            fillers_seed=f"mc-p:{c.a}:{c.b}:{_fx(c)}",
            # 3차 감사 bad_explanation — 발문에 없는 c를 소개 없이 쓰던 해설.
            note="직선 AB와 평행한 접선을 갖는 점의 x좌표를 c라 하자. ",
        )

    def m5(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _mc_c_item(
            frame_id="mc-student-solution-check",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 f({c.a})와 f({c.b})의 값은 서로 다르다. 구간 "
                f"[{c.a}, {c.b}]에서 평균값 정리를 만족시키는 c를 구하려 할 때, 올바른 방정식을 "
                "세워 구한 c의 값은?"
            ),
            case=c,
            fillers_seed=f"mc-s:{c.a}:{c.b}:{_fx(c)}",
        )

    # 5회차 감사(2026-10-08) 처분 — 이차함수 틀(m1·m3·m5)은 정답 c가 구간의 중점이라 'c는 구간의
    # 가운데'라는 추측·오개념으로도 정답 선지에 닿았다(판정자 지적 79d7c8b4 등 7건). 전부 삼차 풀로
    # 바꿨다. 이제 중점은 *오답* 선지(필러)로만 나온다 — 삼차라 중점이 정답이 아니어서 그 선지가
    # 유효하다.
    cubic = tuple(c for c in _cubic_cases() if _rolle_wrong_values(c))
    cubic_time = _from_time_zero(cubic)
    return [
        Frame("mc-closed-interval-find-c", _frames_params("p3-mvt:m1", cubic), m1),
        Frame("mc-cubic-find-c", _frames_params("p3-mvt:m2", cubic), m2),
        Frame("mc-time-find-c", _frames_params("p3-mvt:m3", cubic_time), m3),
        Frame("mc-tangent-parallel-find-c", _frames_params("p3-mvt:m4", cubic), m4),
        Frame("mc-student-solution-check", _frames_params("p3-mvt:m5", cubic), m5),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 진단(diagnostic) — 풀이의 한 단계씩을 따로 확인한다
# ──────────────────────────────────────────────────────────────────────────
def _fprime_eq_rate_poly(case: _Case, var: str = "x") -> tuple[Poly, Fraction]:
    """f'(x) - (평균변화율)을 다항식으로(평균변화율은 정수 — 정수 계수 다항식의 차분몫)."""
    m = Fraction(eval_at(case.f, case.b, var) - eval_at(case.f, case.a, var), case.b - case.a)
    if m.denominator != 1:  # pragma: no cover — 정수 계수 다항식의 평균변화율은 항상 정수
        raise ValueError("평균변화율이 정수가 아니다")
    d = dict(derivative_of(case.f, var))
    d[0] = d.get(0, 0) - int(m)
    return tuple(sorted(((e, c) for e, c in d.items() if c), reverse=True)), m


@lru_cache(maxsize=None)
def _rolle_k_cases() -> tuple[tuple[int, int, int, int, int, Fraction], ...]:
    """f(x) = x^3 + kx^2 + qx + d — f(a) = f(b)가 k를 정하고, 그때 f'(x) = 0의 근 중 하나만 구간 안.

    (a, b, q, d, k, c) — k = -((a^2 + ab + b^2) + q)/(a + b)가 정수이고 f'의 두 근이 유리수인 것만.
    """
    out: list[tuple[int, int, int, int, int, Fraction]] = []
    for a in range(-3, 4):
        for b in range(a + 2, 5):
            if a + b == 0:
                continue
            for q in range(-9, 10):
                num = -((a * a + a * b + b * b) + q)
                if num % (a + b):
                    continue
                k = num // (a + b)
                if k == 0 or abs(k) > 8:
                    continue
                roots = sympy.solve(3 * _X**2 + 2 * k * _X + q, _X)
                if len(roots) != 2 or not all(r.is_rational for r in roots):
                    continue
                fracs = [Fraction(int(r.p), int(r.q)) for r in roots]
                inside = [r for r in fracs if a < r < b]
                if len(inside) != 1:
                    continue
                d = _const_term(a * 5 + b * 3 + q)
                out.append((a, b, q, d, k, inside[0]))
    return tuple(seeded_order("p3-mvt:rolle-k-pool", out))


def _shift_to_zero(case: _Case) -> _Case:
    """구간 [a, b]를 [0, b - a]로 옮긴 사례 — 시각 문항(출발 시각 0)용. 근도 같이 옮긴다."""
    shifted = poly_from_sympy(sympy.expand(poly_to_sympy(case.f).subs(_X, _X + case.a)))
    return _Case(
        shifted,
        0,
        case.b - case.a,
        case.c - case.a,
        tuple(o - case.a for o in case.others),
    )


def _diagnostic_frames() -> list[Frame]:
    def d5(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        fa, fb = eval_at(c.f, c.a), eval_at(c.f, c.b)
        m = Fraction(fb - fa, c.b - c.a)
        return DiffItem(
            slot="diagnostic",
            frame_id="diag-value-of-derivative-at-c",
            question_text=(
                f"함수 f는 닫힌구간 [{c.a}, {c.b}]에서 연속이고 열린구간 ({c.a}, {c.b})에서 "
                f"미분가능하며 f({c.a}) = {fa}, f({c.b}) = {fb}이다. 평균값 정리에 의하여 "
                "f'(c) = k인 c가 이 열린구간에 존재할 때, k의 값을 구하시오."
            ),
            answer_text=frac_text(m),
            explanation=(
                f"평균값 정리의 결론은 f'(c) = (f({c.b}) - f({c.a}))/({_minus(c.b, c.a)})이므로 "
                f"k는 ({render_difference(fb, fa)})/{c.b - c.a} = {frac_text(m)}이다."
            ),
            conditions=f"({_paren(fb)} - {_paren(fa)})/({_paren(c.b)} - {_paren(c.a)}) = k",
            answer_map=(("k", frac_text(m)),),
            problem_type_code=_EVAL,
            answer_format=answer_format_of(m),
        )

    def d8(p: tuple[object, ...]) -> DiffItem | None:
        return _bound_item(slot="diagnostic", frame_id="diag-mvt-lower-bound", p=p, side="lower")

    def d9(p: tuple[object, ...]) -> DiffItem | None:
        # 5회차 감사(2026-10-08) 처분 — 구판 'diag-choose-root-in-interval'은 방정식 f'(x) =
        # (평균변화율)의 두 근을 발문에 적어 구간 안의 값을 고르기만 남았다(판정자 지적
        # 327a1b94·492338dc·ba2a7f9a · 판정기 T06-roots-given). 근을 적지 않는 형태는 대표 슬롯의
        # 'rep-two-candidates-one-inside'가 맡으므로, 진단은 평균값 정리의 *결론*(f'(c) =
        # 평균변화율)만 따로 확인한다 — c를 구하지 않아도 f'(c)가 정해진다는 것을 아는가(함수식이
        # 있는 d5 짝).
        c = _case_of(p[0])
        fa, fb = eval_at(c.f, c.a), eval_at(c.f, c.b)
        m = Fraction(fb - fa, c.b - c.a)
        return _value_item(
            slot="diagnostic",
            frame_id="diag-derivative-value-at-mvt-point",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 닫힌구간 [{c.a}, {c.b}]에서 평균값 정리를 "
                "만족시키는 c가 있다. f'(c)의 값을 구하시오."
            ),
            value=m,
            condition=f"({_paren(fb)} - {_paren(fa)})/({_paren(c.b)} - {_paren(c.a)}) = y",
            # 위생 게이트(QUAL-13)는 'f'(c) = 29'·'f(4) = 60'의 f'(c)·f(4)를 곱으로 읽는다 —
            # 함숫값은 '의 값은'으로 쓰고, 'c = …'·'f'(x) = 29' 같은 값 주장 꼴을 쓰지 않는다.
            explanation=(
                f"평균값 정리에 의하여 f'(c)의 값은 구간 [{c.a}, {c.b}]에서의 평균변화율과 같다. "
                f"평균변화율은 (f({c.b}) - f({c.a}))/({_minus(c.b, c.a)})이고, f({c.b})의 값은 "
                f"{fb}, f({c.a})의 값은 {fa}이므로 그 값은 "
                f"({render_difference(fb, fa)})/{c.b - c.a} = {frac_text(m)}이다. 실제로 f'(x) = "
                f"{render_poly(derivative_of(c.f))}이고, {render_poly(derivative_of(c.f))} = "
                f"{with_eul_reul(frac_text(m))} 만족시키는 x 중 열린구간 ({c.a}, {c.b})에 속하는 "
                f"것은 {frac_text(c.c)} 하나이다."
            ),
        )

    def d10(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        fa, fb = eval_at(c.f, c.a), eval_at(c.f, c.b)
        return _count_item(
            slot="diagnostic",
            frame_id="diag-count-parallel-tangents-between",
            text=(
                f"곡선 y = {_fx(c)} 위의 두 점 A({c.a}, {fa}), B({c.b}, {fb})에 대하여, "
                f"{c.a} < x < {c.b}인 범위에서 접선이 직선 AB와 평행한 점의 개수를 구하시오."
            ),
            case=c,
            note="직선 AB의 기울기는 평균변화율과 같다. ",
        )

    def d11(p: tuple[object, ...]) -> DiffItem | None:
        # 운동 맥락의 진단 — '평균속도 = 위치의 평균변화율'·'순간속도 = 도함수'를 잇고, f'(c) =
        # 평균변화율의
        # 두 근 중 시간 구간 안의 것만 고르는지를 본다(삼차 위치 함수·구간 밖 근 1개).
        c = _shift_to_zero(_case_of(p[0]))
        ft = render_poly(c.f, "t")
        return _c_item(
            slot="diagnostic",
            frame_id="diag-velocity-equals-average-at-time-c",
            text=(
                f"수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x(t) = {ft}이다. 0 < t < {c.b}"
                f"에서 점 P의 순간속도가 t = 0부터 t = {c.b}까지의 평균속도와 같아지는 시각을 "
                "t = c라 할 때, c의 값을 구하시오."
            ),
            case=c,
            var="t",
            fn="x",
            note="평균속도는 위치의 평균변화율이고, 순간속도는 위치의 도함수이다. ",
        )

    # 1차 diagnostic의 근의 합(근과 계수의 관계만)·큰 근(이차방정식 풀이만)·'(구간 밖 포함)' 없는
    # 실근 개수(해석이 갈림)는 평균값 정리의 판단을 요구하지 않아 삭제했다(2차 감사).
    return [
        Frame("diag-value-of-derivative-at-c", _frames_params("p3-mvt:d5", _cubic_cases()), d5),
        # 3차 감사(2026-10) 처분 — 'diag-rolle-premise-find-k'(가정 f(a) = f(b)만으로 k를 구해
        # 미분이
        # 쓰이지 않고, 이차함수라 대칭축만 보면 c까지 정해지는 틀)는 삭제했다(우회로 판정기
        # E-derivative). 롤의 정리의 가정→결론 두 단계는 숙련도의 삼차 틀이 맡는다.
        Frame(
            "diag-derivative-value-at-mvt-point", _frames_params("p3-mvt:d9", _cubic_cases()), d9
        ),
        Frame("diag-mvt-lower-bound", _bound_params("p3-mvt:d8"), d8),
        Frame("diag-count-parallel-tangents-between", _count_pool("p3-mvt:d10"), d10),
        Frame(
            "diag-velocity-equals-average-at-time-c",
            _frames_params("p3-mvt:d11", _cubic_cases()),
            d11,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 숙련도 확인(mastery_check) — 구간 밖 근 식별·미지수·부등식·롤의 정리 두 단계·개수
# ──────────────────────────────────────────────────────────────────────────
def _mastery_frames() -> list[Frame]:
    def k1(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        eq, m = _fprime_eq_rate_poly(c)
        if len(c.others) != 1:
            return None
        out = c.others[0]
        side = f"x < {c.a}" if out < c.a else f"x > {c.b}"
        return KindedDiffItem(
            slot="mastery_check",
            frame_id="mastery-root-outside-interval",
            question_text=(
                f"함수 f(x) = {_fx(c)}에 대하여 방정식 f'(x) = (f({c.b}) - f({c.a}))/"
                f"({_minus(c.b, c.a)})의 두 실근 중 열린구간 ({c.a}, {c.b})에 속하지 않는 근을 "
                "구하시오."
            ),
            answer_text=frac_text(out),
            # 3차 감사 bad_explanation — 도함수 식과 평균변화율 계산 과정을 보인다(종전: 결론만).
            explanation=(
                f"f'(x) = {render_poly(derivative_of(c.f))}이다. 구간 [{c.a}, {c.b}]에서의 "
                f"평균변화율은 (f({c.b}) - f({c.a}))/({_minus(c.b, c.a)}) = "
                f"({render_difference(eval_at(c.f, c.b), eval_at(c.f, c.a))})/{c.b - c.a} = "
                f"{frac_text(m)}이므로 방정식은 {render_poly(derivative_of(c.f))} = "
                f"{frac_text(m)}, "
                f"즉 {render_poly(eq)} = 0이다. {render_factored(eq)} = 0이므로 두 근은 "
                f"{with_wa_gwa(frac_text(c.c))} {frac_text(out)}이다. 이 중 {frac_text(c.c)}만 "
                f"열린구간 안에 있으므로 구간에 속하지 않는 근은 {frac_text(out)}이다."
            ),
            conditions=(f"{poly_to_sympy_str(eq)} = 0", side),
            answer_map=(("x", frac_text(out)),),
            problem_type_code=_SOLVE,
            answer_format=answer_format_of(out),
            solution_setup=_mvt_setup(c.f, c.a, c.b),
        )

    def k3(p: tuple[object, ...]) -> DiffItem | None:
        # 1차 '두 점 (a, f(a)), (b, f(b))에서 a = -1, b = 2이다'는 기호를 들이자마자 값을 고정한
        # 어색한 문장이었다(2차 감사) — 두 점을 좌표 그대로 쓴다.
        return _k_item(
            "mastery_check",
            "mastery-find-k-tangent-parallel",
            lambda a, b, cs: (
                f"함수 f(x) = x^3 + kx^2에 대하여 곡선 y = f(x) 위의 두 점 ({a}, f({a})), "
                f"({b}, f({b})){eul_reul(f'f({b})')} 잇는 직선과 평행한 접선의 접점의 x좌표가 "
                f"{cs}일 때, 상수 k의 값을 구하시오."
            ),
            p,
            points_in_question=True,
        )

    def k5(p: tuple[object, ...]) -> DiffItem | None:
        # 5회차 감사 처분 — 이차함수 구판은 c가 중점이라 k = 2c - a로 풀렸다(판정자 지적 1ebb69fb·
        # 62d2b1fc). 삼차함수로 바꿔 끝점 k의 이차방정식을 풀고 'k > a'로 하나를 고르게 한다.
        c = _case_of(p[0])
        cs = frac_text(c.c)
        return _endpoint_item(
            "mastery_check",
            "mastery-find-upper-endpoint",
            c.f,
            c,
            unknown="k",
            fixed_is_left=True,
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 닫힌구간 [{c.a}, k] (k > {c.a})에서 평균값 "
                f"정리를 만족시키는 c의 값이 {cs}일 때, k의 값을 구하시오."
            ),
        )

    def k7(p: tuple[object, ...]) -> DiffItem | None:
        return _bound_item(
            slot="mastery_check", frame_id="mastery-mvt-bound-range-sum", p=p, side="both"
        )

    def k8(p: tuple[object, ...]) -> DiffItem | None:
        # 롤의 정리를 두 단계로 — 가정(f(a) = f(b))으로 k를 정하고, 결론(f'(c) = 0)으로 c를 구한다.
        a, b, q, d, k0, c_in = p[0], p[1], p[2], p[3], p[4], p[5]
        assert isinstance(c_in, Fraction)
        a, b, q, d, k0 = (int(str(v)) for v in (a, b, q, d, k0))
        f = _mk_poly((3, 1), (2, k0), (1, q), (0, d))
        case = _Case(f, a, b, c_in, ())
        solved = _solve_c(case)
        if solved is None or solved[0] != c_in:
            return None
        q_text = "" if q == 0 else (f" + {q}x" if q > 0 else f" - {-q}x")
        if abs(q) == 1:
            q_text = " + x" if q > 0 else " - x"
        d_text = "" if d == 0 else (f" + {d}" if d > 0 else f" - {-d}")
        human = f"x^3 + kx^2{q_text}{d_text}"
        fa_k = render_poly(((1, a * a), (0, a**3 + q * a + d)), "k")
        fb_k = render_poly(((1, b * b), (0, b**3 + q * b + d)), "k")
        premise = (
            f"다항함수는 연속이고 미분가능하므로 롤의 정리를 적용하려면 f({a}) = f({b})이어야 "
            f"한다. f({a}) = {fa_k}, f({b}) = {fb_k}이므로 {fa_k} = {fb_k}에서 k = {k0}이다. "
            f"그러면 f(x) = {render_poly(f)}이고 "
        )
        return _c_item(
            slot="mastery_check",
            frame_id="mastery-rolle-cubic-k-then-c",
            text=(
                f"함수 f(x) = {human}{i_ga(human)} 닫힌구간 [{a}, {b}]에서 롤의 정리의 가정을 "
                "만족시키도록 상수 k의 값을 정할 때, 롤의 정리를 만족시키는 c의 값을 구하시오."
            ),
            case=case,
            rhs="0",
            note=premise,
        )

    def k9(p: tuple[object, ...]) -> DiffItem | None:
        c = _shift_to_zero(_case_of(p[0]))
        ft = render_poly(c.f, "t")
        return _count_item(
            slot="mastery_check",
            frame_id="mastery-count-velocity-matches-average",
            text=(
                f"수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x(t) = {ft}일 때, "
                f"0 < t < {c.b}에서 점 P의 순간속도가 t = 0부터 t = {c.b}까지의 평균속도와 "
                "같아지는 시각의 개수를 구하시오."
            ),
            case=c,
            var="t",
            fn="x",
            note="평균속도는 위치의 평균변화율이다. ",
        )

    # 1차 숙련도의 '두 구간의 평균변화율이 같은 k'(평균변화율 대수 계산만)·'c + e'(근과 계수의
    # 관계만)·'구간은 제한하지 않는다' 개수(도함수 방정식 근 세기)는 삭제했다(2차 감사 bad_tag).
    return [
        Frame("mastery-root-outside-interval", _frames_params("p3-mvt:k1", _cubic_cases()), k1),
        Frame("mastery-find-k-tangent-parallel", tuple(_k_params("p3-mvt:k3")), k3),
        Frame("mastery-find-upper-endpoint", _frames_params("p3-mvt:k5", _cubic_cases()), k5),
        Frame("mastery-mvt-bound-range-sum", _bound_params("p3-mvt:k7"), k7),
        Frame(
            "mastery-rolle-cubic-k-then-c",
            tuple(tuple(c) for c in _rolle_k_cases()),
            k8,
        ),
        Frame(
            "mastery-count-velocity-matches-average",
            tuple((case,) for case in seeded_order("p3-mvt:k9", _both_inside_cases())),
            k9,
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


class P3DiffMeanValueTheoremGenerator(P3DiffSlotGenerator):
    """[12미적Ⅰ-02-06] 평균값 정리 — 슬롯 6종 결정론 생성기."""

    standard_code: ClassVar[str] = "[12미적Ⅰ-02-06]"
    concept_src_id: ClassVar[str] = "H:12미적Ⅰ02-06"
    unit_code: ClassVar[str] = "P3-CALC1-DIFF-MEAN-VALUE-THEOREM"
    slug_prefix: ClassVar[str] = "wm-p3-diff-mvt"
    slot_difficulty: ClassVar[dict[str, float]] = {
        "representative": 2.5,
        "basic": 2.0,
        "applied": 3.5,
        "misconception_trigger": 3.0,
        "diagnostic": 2.5,
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

    def _assemble(self, spec: EquivalenceSpec, item: DiffItem) -> CandidateProblem:
        return with_item_kinds(super()._assemble(spec, item), item)
