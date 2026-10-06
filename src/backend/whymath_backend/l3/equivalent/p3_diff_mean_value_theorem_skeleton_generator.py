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

import math
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
    poly_to_sympy,
    poly_to_sympy_str,
    render_affine,
    render_poly,
    with_eul_reul,
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
from whymath_backend.lang.josa import eul_reul, eun_neun
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
def _quad_cases() -> tuple[_Case, ...]:
    """이차함수 f = px^2 + qx + r — c는 항상 구간의 중점이다(유일)."""
    out: list[_Case] = []
    for p in (1, 2, 3, -1, -2):
        for q in range(-6, 7):
            for a in range(-3, 3):
                for b in range(a + 2, 6, 2 if (a % 2) else 1):
                    r = _const_term(p * 7 + q * 3 + a * 5 + b)
                    f = _mk_poly((2, p), (1, q), (0, r))
                    out.append(_Case(f, a, b, Fraction(a + b, 2), ()))
    return tuple(seeded_order("p3-mvt:quad-pool", out)[:150])


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
def _rolle_cases() -> tuple[_Case, ...]:
    """f(a) = f(b)인 이차함수(롤의 정리) — c = 중점."""
    out: list[_Case] = []
    for p in (1, 2, 3, -1, -2, -3):
        for a in range(-4, 3):
            for b in range(a + 2, 6, 2):
                r = _const_term(p * 5 + a * 3 + b)
                f = _mk_poly((2, p), (1, -p * (a + b)), (0, r))
                out.append(_Case(f, a, b, Fraction(a + b, 2), ()))
    return tuple(seeded_order("p3-mvt:rolle-pool", out)[:60])


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
    others_text = ", ".join(frac_text(o) for o in others)
    other_note = (
        f" 방정식의 다른 근 {others_text}{eun_neun(others_text)} 열린구간 밖이므로 버린다."
        if others
        else ""
    )
    answer = frac_text(c)
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=answer,
        explanation=(
            f"{fn}'({var}) = {render_poly(derivative_of(case.f, var), var)}이고 "
            f"구간 [{case.a}, {case.b}]에서의 평균변화율은 {frac_text(m)}이다. "
            f"{fn}'(c) = {frac_text(m)}{eul_reul(frac_text(m))} 풀어 열린구간 "
            f"({case.a}, {case.b})에 속하는 근을 찾으면 c = {frac_text(c)}이다.{other_note}"
        ),
        conditions=(equation, *_bounds(case.a, case.b)),
        answer_map=(("c", frac_text(c)),),
        problem_type_code=ptype,
        answer_format=answer_format_of(c),
        choices=choices,
        distractors=distractors,
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
            frame_id="rep-quadratic-find-c",
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

    def r4(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        solved = _solve_c(c)
        if solved is None:
            return None
        m = solved[1]
        return _c_item(
            slot="representative",
            frame_id="rep-average-rate-given",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 구간 [{c.a}, {c.b}]에서의 평균변화율은 "
                f"{frac_text(m)}이다. f'(c) = {frac_text(m)}{eul_reul(frac_text(m))} "
                f"만족시키는 c가 열린구간 "
                f"({c.a}, {c.b})에 존재할 때, c의 값을 구하시오."
            ),
            case=c,
            rhs=frac_text(m),
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

    return [
        Frame("rep-quadratic-find-c", _frames_params("p3-mvt:r1", _quad_cases()), r1),
        Frame(
            "rep-cubic-continuous-differentiable", _frames_params("p3-mvt:r2", _cubic_cases()), r2
        ),
        Frame("rep-tangent-parallel-to-chord", _frames_params("p3-mvt:r3", _cubic_cases()), r3),
        Frame("rep-average-rate-given", _frames_params("p3-mvt:r4", _quad_cases()), r4),
        Frame("rep-two-candidates-one-inside", _frames_params("p3-mvt:r5", _cubic_cases()), r5),
        Frame("rep-average-equals-instantaneous", _frames_params("p3-mvt:r6", _quad_cases()), r6),
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
    )


def _basic_frames() -> list[Frame]:
    def b1(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        m = Fraction(eval_at(c.f, c.b) - eval_at(c.f, c.a), c.b - c.a)
        return _value_item(
            slot="basic",
            frame_id="basic-average-rate",
            text=f"함수 f(x) = {_fx(c)}의 닫힌구간 [{c.a}, {c.b}]에서의 평균변화율을 구하시오.",
            value=m,
            condition=f"{_rate_str(c.f, c.a, c.b)} = y",
            explanation=(
                f"평균변화율은 (f({c.b}) - f({c.a}))/({c.b} - ({c.a})) = "
                f"({eval_at(c.f, c.b)} - ({eval_at(c.f, c.a)}))/{c.b - c.a} = {frac_text(m)}이다."
            ),
        )

    def b2(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _c_item(
            slot="basic",
            frame_id="basic-difference-equals-derivative-times-length",
            text=(
                f"이차함수 f(x) = {_fx(c)}에 대하여 f({c.b}) - f({c.a}) = f'(c)({_minus(c.b, c.a)})"
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

    def b4(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        m = Fraction(eval_at(c.f, c.b) - eval_at(c.f, c.a), c.b - c.a)
        fa, fb = eval_at(c.f, c.a), eval_at(c.f, c.b)
        return _value_item(
            slot="basic",
            frame_id="basic-chord-slope",
            text=(
                f"곡선 y = {_fx(c)} 위의 두 점 A({c.a}, {fa}), "
                f"{with_eul_reul(f'B({c.b}, {fb})')} 지나는 직선의 "
                "기울기를 구하시오."
            ),
            value=m,
            condition=f"{_rate_str(c.f, c.a, c.b)} = y",
            explanation=f"기울기는 ({fb} - ({fa}))/({c.b} - ({c.a})) = {frac_text(m)}이다.",
        )

    def b5(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        diff = eval_at(c.f, c.b) - eval_at(c.f, c.a)
        return _value_item(
            slot="basic",
            frame_id="basic-function-value-difference",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 f({c.b}) - f({c.a})의 값을 구하시오. "
                "(평균값 정리의 양변을 비교하기 위한 값이다.)"
            ),
            value=Fraction(diff),
            condition=f"{_paren(eval_at(c.f, c.b))} - {_paren(eval_at(c.f, c.a))} = y",
            explanation=(
                f"f({c.b}) = {eval_at(c.f, c.b)}, f({c.a}) = {eval_at(c.f, c.a)}이므로 "
                f"차는 {diff}이다."
            ),
        )

    def b6(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        ft = render_poly(c.f, "t")
        item = _c_item(
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
        return item

    def b7(p: tuple[object, ...]) -> DiffItem | None:
        c, off = _case_of(p[0]), int(str(p[1]))
        poly, slope = _slope_equation(c, off)
        n = _count_roots(poly)
        fa, fb = eval_at(c.f, c.a), eval_at(c.f, c.b)
        # 기울기를 직선 AB(평균변화율)와 견주어 말한다 — 평균값 정리의 '평균변화율 ↔ 접선 기울기'
        # 비교 맥락을 발문에 드러내 문항이 실제로 묻는 개념과 태그를 맞춘다(감사 bad_tag 교정).
        compare = "큰" if off > 0 else "작은"
        return KindedDiffItem(
            slot="basic",
            frame_id="basic-count-points-with-given-slope",
            question_text=(
                f"함수 f(x) = {_fx(c)}에 대하여 곡선 y = f(x) 위의 두 점 A({c.a}, {fa}), "
                f"{with_i_ga(f'B({c.b}, {fb})')} 있다. 이 곡선 위의 점 중에서 접선의 기울기가 "
                f"직선 AB의 기울기보다 {abs(off)}만큼 {compare} 점의 개수를 구하시오."
            ),
            answer_text=str(n),
            explanation=(
                f"직선 AB의 기울기는 구간 [{c.a}, {c.b}]에서의 평균변화율 {slope - off}이므로 "
                f"접선의 기울기는 {slope}이다. 이를 만족하는 점의 x좌표는 "
                f"{render_poly(poly)} = 0의 실근이고, 서로 다른 실근은 {n}개이다."
            ),
            conditions=f"{poly_to_sympy_str(poly)} = 0",
            answer_map=(),
            problem_type_code=_COUNT,
            answer_format=AnswerFormat.자연수,
            answer_kind="real_root_count",
        )

    return [
        Frame("basic-count-points-with-given-slope", _slope_params("p3-mvt:b7"), b7),
        Frame("basic-average-rate", _frames_params("p3-mvt:b1", _quad_cases()), b1),
        Frame(
            "basic-difference-equals-derivative-times-length",
            _frames_params("p3-mvt:b2", _quad_cases()),
            b2,
        ),
        Frame("basic-rolle-theorem", _frames_params("p3-mvt:b3", _rolle_cases()), b3),
        Frame("basic-chord-slope", _frames_params("p3-mvt:b4", _cubic_cases()), b4),
        Frame("basic-function-value-difference", _frames_params("p3-mvt:b5", _cubic_cases()), b5),
        Frame(
            "basic-time-average-velocity",
            _frames_params("p3-mvt:b6", _from_time_zero(_quad_cases())),
            b6,
        ),
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


def _k_item(slot: str, frame_id: str, text_of: object, p: tuple[object, ...]) -> DiffItem | None:
    k, a, b, c = int(str(p[0])), int(str(p[1])), int(str(p[2])), p[3]
    assert isinstance(c, Fraction)
    if not _unique_k(k, a, b, c):
        return None
    assert callable(text_of)
    cs = frac_text(c)
    condition = (
        f"Derivative(x**3 + k*x**2, x).doit().subs(x, {cs}) = "
        f"(({b})**3 + k*({b})**2 - (({a})**3 + k*({a})**2))/(({b}) - ({a}))"
    )
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text_of(a, b, cs),
        answer_text=str(k),
        explanation=(
            f"f'(x) = 3x^2 + 2kx이고 평균변화율은 "
            f"{render_affine(a * a + a * b + b * b, a + b, 'k')}이다. "
            f"f'({cs}) = (평균변화율)에서 k = {k}이다."
        ),
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
        )

    def a2(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        solved = _solve_c(c)
        if solved is None:
            return None
        m = solved[1]
        n = ((c.a * 3 + c.b * 5) % 7) - 3
        return _c_item(
            slot="applied",
            frame_id="applied-tangent-parallel-to-line",
            text=(
                f"함수 f(x) = {_fx(c)}에 대하여 곡선 y = f(x) 위의 점 P(c, f(c)) "
                f"({c.a} < c < {c.b})에서의 접선이 직선 "
                f"y = {frac_text(m)}x {'+' if n >= 0 else '-'} {abs(n)}"
                f"{with_wa_gwa(abs(n))} 평행할 때, c의 값을 구하시오."
            ),
            case=c,
            rhs=frac_text(m),
        )

    def a3(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        ft = render_poly(c.f, "t")
        return _c_item(
            slot="applied",
            frame_id="applied-car-instantaneous-equals-average",
            text=(
                f"자동차가 출발한 지 t시간 후의 이동 거리가 s(t) = {ft} (km)이다. 출발 후 "
                f"{c.a}시간부터 {c.b}시간까지의 평균 속도와 순간 속도가 같아지는 시각 "
                f"t = c ({c.a} < c < {c.b})의 값을 구하시오."
            ),
            case=c,
            var="t",
            fn="s",
        )

    def a4(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        # 이차함수에서 c는 구간의 중점이다. 왼쪽 끝점 a를 미지수로 둔다 — b와 c가 주어진다.
        f_poly = c.f
        return _endpoint_item(
            "applied", "applied-find-left-endpoint", f_poly, c, unknown="a", fixed_is_left=False
        )

    def a5(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _endpoint_item(
            "applied", "applied-find-chord-endpoint", c.f, c, unknown="b", fixed_is_left=True
        )

    return [
        Frame("applied-find-k-from-c", tuple(_k_params("p3-mvt:a1")), a1),
        Frame("applied-tangent-parallel-to-line", _frames_params("p3-mvt:a2", _cubic_cases()), a2),
        Frame(
            "applied-car-instantaneous-equals-average",
            _frames_params("p3-mvt:a3", _from_time_zero(_cubic_cases())),
            a3,
        ),
        Frame("applied-find-left-endpoint", _frames_params("p3-mvt:a4", _quad_cases()), a4),
        Frame("applied-find-chord-endpoint", _frames_params("p3-mvt:a5", _quad_cases()), a5),
    ]


def _k_params(seed: str) -> list[tuple[object, ...]]:
    return [tuple(case) for case in seeded_order(seed, _k_cases())]


def _endpoint_explanation(a: int, b: int, cs: str, *, unknown: str, fixed_is_left: bool) -> str:
    """끝점 미지수 해설 — 답을 먼저 대입해 놓지 않고 미지수 식에서 풀이 순서대로 푼다.

    c는 구간의 중점이므로 (두 끝점의 합)/2 = c이고, 합 = 2c는 주어진 c에서 곧바로 나온다.
    """
    total = a + b  # 2c — 두 끝점의 합(주어진 c에서 나오는 값)
    if fixed_is_left:  # 왼쪽 끝점 a가 고정, 오른쪽 b가 미지수
        head = f"({a} + {unknown})/2"
        step = f"{a} + {unknown} = {total}"
    else:  # 오른쪽 끝점 b가 고정, 왼쪽 a가 미지수
        sign = "+" if b >= 0 else "-"
        head = f"({unknown} {sign} {abs(b)})/2"
        step = f"{unknown} {sign} {abs(b)} = {total}"
    answer = b if fixed_is_left else a
    return (
        f"이차함수에서 평균값 정리의 c는 구간의 중점이므로 {head} = {cs}이다. "
        f"양변에 2를 곱하면 {step}이므로 {unknown} = {answer}이다."
    )


def _endpoint_item(
    slot: str,
    frame_id: str,
    f: Poly,
    case: _Case,
    *,
    unknown: str,
    fixed_is_left: bool,
) -> DiffItem | None:
    """이차함수에서 c와 한 끝점이 주어질 때 다른 끝점(미지수)을 구한다.

    f'(c) = (f(b) - f(a))/(b - a)에서 미지수 끝점은 근이 둘이 아니라 구간이 퇴화하는 가짜 근
    (끝점 = 다른 끝점)을 낳는다 — 조건에 `unknown > 고정 끝점`(또는 `<`)을 함께 둬 가른다.
    """
    a, b, c = case.a, case.b, case.c
    given = a if fixed_is_left else b
    answer = b if fixed_is_left else a
    sym = sympy.Symbol(unknown)
    f_unknown = poly_to_sympy(f).subs(_X, sym)
    f_given = eval_at(f, given)
    cs = frac_text(c)
    deriv = f"Derivative({poly_to_sympy_str(f)}, x).doit().subs(x, {cs})"
    if fixed_is_left:
        rate = f"({sympy.sstr(f_unknown)} - ({f_given}))/({unknown} - ({given}))"
        side = f"{unknown} > {given}"
    else:
        rate = f"({f_given} - ({sympy.sstr(f_unknown)}))/(({given}) - {unknown})"
        side = f"{unknown} < {given}"
    # 검산: 답을 대입해 평균값 정리의 c가 정말 c인지 SymPy로 확인(생성기 자기 점검)
    check = sympy.solve(
        sympy.Eq(
            sympy.diff(poly_to_sympy(f), _X).subs(_X, sympy.Rational(c.numerator, c.denominator)),
            (
                (f_unknown - f_given) / (sym - given)
                if fixed_is_left
                else (f_given - f_unknown) / (given - sym)
            ),
        ),
        sym,
    )
    if sympy.Integer(answer) not in check:
        return None
    if fixed_is_left:
        text = (
            f"함수 f(x) = {render_poly(f)}에 대하여 구간 [{a}, b] (b > {a})에서 평균값 정리를 "
            f"만족시키는 c의 값이 {cs}일 때, b의 값을 구하시오."
            if frame_id == "applied-find-chord-endpoint"
            else (
                f"곡선 y = {render_poly(f)} 위의 점 A({a}, {f_given})와 x좌표가 b (b > {a})인 "
                f"점 B를 잇는 직선과 평행한 접선의 접점의 x좌표가 {cs}일 때, b의 값을 구하시오."
            )
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
        explanation=_endpoint_explanation(a, b, cs, unknown=unknown, fixed_is_left=fixed_is_left),
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
    )
    if base is None:
        return None
    assert answer == base.answer_text
    return base


def _misconception_frames() -> list[Frame]:
    def m1(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        return _mc_c_item(
            frame_id="mc-quadratic-find-c",
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
            text=(
                f"직선 위를 움직이는 점의 시각 t에서의 위치가 x(t) = {ft}일 때, t = {c.a}부터 "
                f"t = {c.b}까지의 평균속도와 같은 순간속도를 갖는 시각 t = c의 값은?"
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

    quad = tuple(c for c in _quad_cases() if _rolle_wrong_values(c))
    quad_time = _from_time_zero(quad)
    cubic = tuple(c for c in _cubic_cases() if _rolle_wrong_values(c))
    return [
        Frame("mc-quadratic-find-c", _frames_params("p3-mvt:m1", quad), m1),
        Frame("mc-cubic-find-c", _frames_params("p3-mvt:m2", cubic), m2),
        Frame("mc-time-find-c", _frames_params("p3-mvt:m3", quad_time), m3),
        Frame("mc-tangent-parallel-find-c", _frames_params("p3-mvt:m4", cubic), m4),
        Frame("mc-student-solution-check", _frames_params("p3-mvt:m5", quad), m5),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 진단(diagnostic) — 풀이의 한 단계씩을 따로 확인한다
# ──────────────────────────────────────────────────────────────────────────
def _count_roots(poly: Poly) -> int:
    """서로 다른 실근 수 — 검산기와 독립인 경로(제곱 없는 부분의 Sturm 개수)."""
    return int(sympy.Poly(poly_to_sympy(poly), _X).sqf_part().count_roots())


def _slope_equation(case: _Case, offset: int) -> tuple[Poly, int]:
    """f'(x) - (평균변화율 + offset)을 다항식으로 — 접선의 기울기가 그 값인 점의 x좌표 방정식."""
    base_eq, m = _fprime_eq_rate_poly(case)
    slope = int(m) + offset
    d = dict(derivative_of(case.f))
    d[0] = d.get(0, 0) - slope
    return tuple(sorted(((e, c) for e, c in d.items() if c), reverse=True)), slope


def _slope_params(seed: str) -> tuple[tuple[object, ...], ...]:
    """(사례, 기울기 변위) 격자 — 변위가 달라 실근이 0·1·2개로 갈리게 한다."""
    pool = _cubic_cases()[:60]
    combos = tuple((case, off) for case in pool for off in (-9, -5, -2, 2, 5, 9, 14, 20))
    return tuple(seeded_order(seed, combos))


def _fprime_eq_rate_poly(case: _Case) -> tuple[Poly, Fraction]:
    """f'(x) - (평균변화율)을 다항식으로(평균변화율은 정수 — 정수 계수 다항식의 차분몫)."""
    m = Fraction(eval_at(case.f, case.b) - eval_at(case.f, case.a), case.b - case.a)
    if m.denominator != 1:  # pragma: no cover — 정수 계수 다항식의 평균변화율은 항상 정수
        raise ValueError("평균변화율이 정수가 아니다")
    d = dict(derivative_of(case.f))
    d[0] = d.get(0, 0) - int(m)
    return tuple(sorted(((e, c) for e, c in d.items() if c), reverse=True)), m


def _diagnostic_frames() -> list[Frame]:
    def d2(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        eq, m = _fprime_eq_rate_poly(c)
        roots = sympy.roots(sympy.Poly(poly_to_sympy(eq), _X))
        s = sum((r * mult for r, mult in roots.items()), sympy.Integer(0))
        if sum(roots.values()) != sympy.Poly(poly_to_sympy(eq), _X).degree() or not s.is_rational:
            return None
        value = Fraction(int(s.p), int(s.q))
        return KindedDiffItem(
            slot="diagnostic",
            frame_id="diag-sum-of-candidate-roots",
            question_text=(
                f"함수 f(x) = {_fx(c)}에 대하여 닫힌구간 [{c.a}, {c.b}]에서의 평균변화율과 "
                "같은 미분계수를 갖는 실수 x(구간 밖의 값도 포함)의 합을 구하시오. "
                "(단, 중근은 중복하여 센다.)"
            ),
            answer_text=frac_text(value),
            explanation=(
                f"구간 [{c.a}, {c.b}]에서의 평균변화율은 {frac_text(m)}이므로 f'(x)의 값이 "
                f"{frac_text(m)}인 방정식은 {render_poly(eq)} = 0이고 "
                f"근의 합은 {frac_text(value)}이다."
            ),
            conditions=f"{poly_to_sympy_str(eq)} = 0",
            answer_map=(),
            problem_type_code=_SOLVE,
            answer_format=answer_format_of(value),
            answer_aggregate="sum",
        )

    def d3(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        eq, m = _fprime_eq_rate_poly(c)
        both = sorted([c.c, *c.others])
        if len(both) != 2:
            return None
        big = both[-1]
        return KindedDiffItem(
            slot="diagnostic",
            frame_id="diag-larger-candidate",
            question_text=(
                f"함수 f(x) = {_fx(c)}에 대하여 닫힌구간 [{c.a}, {c.b}]에서의 평균변화율과 "
                "같은 미분계수를 갖는 실수 x는 두 개이다. 이 중 큰 값을 구하시오."
            ),
            answer_text=frac_text(big),
            explanation=(
                f"구간 [{c.a}, {c.b}]에서의 평균변화율은 {frac_text(m)}이므로 f'(x)의 값이 "
                f"{frac_text(m)}인 방정식은 {render_poly(eq)} = 0이고 그 두 근은 "
                f"{frac_text(both[0])}, {frac_text(both[1])}이다."
            ),
            conditions=f"{poly_to_sympy_str(eq)} = 0",
            answer_map=(("x", frac_text(big)),),
            problem_type_code=_SOLVE,
            answer_format=answer_format_of(big),
            answer_selection="largest",
        )

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
            explanation=f"k는 평균변화율 ({fb} - ({fa}))/({c.b} - ({c.a})) = {frac_text(m)}이다.",
            conditions=f"({_paren(fb)} - {_paren(fa)})/({_paren(c.b)} - {_paren(c.a)}) = k",
            answer_map=(("k", frac_text(m)),),
            problem_type_code=_EVAL,
            answer_format=answer_format_of(m),
        )

    def d6(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        # 롤의 정리 전제(f(a) = f(b))를 맞추는 상수 k — f(x) = x^2 + kx + r
        r = _const_term(c.a * 3 + c.b)
        k = -(c.a + c.b)
        cond = f"(({c.a})**2 + k*({c.a}) + ({r})) = (({c.b})**2 + k*({c.b}) + ({r}))"
        r_text = f"+ {r}" if r >= 0 else f"- {-r}"
        return DiffItem(
            slot="diagnostic",
            frame_id="diag-rolle-premise-find-k",
            question_text=(
                f"함수 f(x) = x^2 + kx {r_text}에 대하여 f({c.a}) = f({c.b})일 때, 닫힌구간 "
                f"[{c.a}, {c.b}]에서 롤의 정리의 조건이 성립하도록 하는 상수 k의 값을 구하시오."
            ),
            answer_text=str(k),
            explanation=(
                f"f({c.a}) = f({c.b})에서 두 끝점의 합과 k의 합이 0이어야 하므로 k는 {k}이다."
            ),
            conditions=cond,
            answer_map=(("k", str(k)),),
            problem_type_code=_SOLVE,
            answer_format=answer_format_of(k),
        )

    def d7(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        eq, m = _fprime_eq_rate_poly(c)
        distinct = len(set(sympy.real_roots(sympy.Poly(poly_to_sympy(eq), _X))))
        return KindedDiffItem(
            slot="diagnostic",
            frame_id="diag-count-candidates",
            question_text=(
                f"함수 f(x) = {_fx(c)}에 대하여 닫힌구간 [{c.a}, {c.b}]에서의 평균변화율과 "
                "같은 미분계수를 갖는 서로 다른 실수 x의 개수를 구하시오."
            ),
            answer_text=str(distinct),
            explanation=(
                f"구간 [{c.a}, {c.b}]에서의 평균변화율은 {frac_text(m)}이므로 f'(x)의 값이 "
                f"{frac_text(m)}인 방정식은 {render_poly(eq)} = 0이고 서로 다른 실근은 "
                f"{distinct}개이다."
            ),
            conditions=f"{poly_to_sympy_str(eq)} = 0",
            answer_map=(),
            problem_type_code=_COUNT,
            answer_format=AnswerFormat.자연수,
            answer_kind="real_root_count",
        )

    return [
        Frame("diag-sum-of-candidate-roots", _frames_params("p3-mvt:d2", _cubic_cases()), d2),
        Frame("diag-larger-candidate", _frames_params("p3-mvt:d3", _cubic_cases()), d3),
        Frame("diag-value-of-derivative-at-c", _frames_params("p3-mvt:d5", _cubic_cases()), d5),
        Frame("diag-rolle-premise-find-k", _frames_params("p3-mvt:d6", _rolle_cases()), d6),
        Frame("diag-count-candidates", _frames_params("p3-mvt:d7", _cubic_cases()), d7),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 숙련도 확인(mastery_check) — 구간 밖 근 식별·미지수·두 구간 비교
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
            explanation=(
                f"{render_poly(eq)} = 0의 두 근은 {with_wa_gwa(frac_text(c.c))} "
                f"{frac_text(out)}이고 {frac_text(c.c)}만 열린구간 안에 있다. "
                f"구간 밖의 근은 {frac_text(out)}이다."
            ),
            conditions=(f"{poly_to_sympy_str(eq)} = 0", side),
            answer_map=(("x", frac_text(out)),),
            problem_type_code=_SOLVE,
            answer_format=answer_format_of(out),
        )

    def k2(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        # 이차함수 f의 두 구간 [a, b], [a2, k] — 평균변화율이 같도록 하는 k (k > a2)
        a2 = c.a - 1
        fk = poly_to_sympy(c.f).subs(_X, sympy.Symbol("k"))
        rate1 = Fraction(eval_at(c.f, c.b) - eval_at(c.f, c.a), c.b - c.a)
        k_expected = c.a + c.b - a2  # 이차함수의 평균변화율은 (끝점 합)에 의해서만 정해진다
        if k_expected <= a2:
            return None
        cond = f"{frac_text(rate1)}*(k - ({a2})) = {sympy.sstr(fk)} - ({eval_at(c.f, a2)})"
        sols = sympy.solve(
            sympy.Eq(
                rate1.numerator * (sympy.Symbol("k") - a2),
                rate1.denominator * (fk - eval_at(c.f, a2)),
            ),
            sympy.Symbol("k"),
        )
        if sympy.Integer(k_expected) not in sols or len([s for s in sols if s > a2]) != 1:
            return None
        return DiffItem(
            slot="mastery_check",
            frame_id="mastery-two-intervals-equal-average-rate",
            question_text=(
                f"이차함수 f(x) = {_fx(c)}에 대하여 구간 [{c.a}, {c.b}]에서의 평균변화율과 "
                f"구간 [{a2}, k]에서의 평균변화율이 같을 때, k ({a2} < k)의 값을 구하시오."
            ),
            answer_text=str(k_expected),
            explanation=(
                f"이차함수의 평균변화율은 두 끝점의 합으로 정해지므로 {c.a} + {c.b} = {a2} + k에서 "
                f"k = {k_expected}이다."
            ),
            conditions=(cond, f"k > {a2}"),
            answer_map=(("k", str(k_expected)),),
            problem_type_code=_SOLVE,
            answer_format=answer_format_of(k_expected),
        )

    def k3(p: tuple[object, ...]) -> DiffItem | None:
        return _k_item(
            "mastery_check",
            "mastery-find-k-tangent-parallel",
            lambda a, b, cs: (
                f"함수 f(x) = x^3 + kx^2에 대하여 곡선 y = f(x) 위의 두 점 (a, f(a)), "
                f"(b, f(b))에서 a = {a}, b = {b}이다. 이 두 점을 잇는 직선과 평행한 접선의 "
                f"접점의 x좌표가 {cs}일 때, 상수 k의 값을 구하시오."
            ),
            p,
        )

    def k4(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        eq, m = _fprime_eq_rate_poly(c)
        if len(c.others) != 1:
            return None
        total = c.c + c.others[0]
        return KindedDiffItem(
            slot="mastery_check",
            frame_id="mastery-sum-of-c-and-outside-root",
            question_text=(
                f"함수 f(x) = {_fx(c)}에 대하여 열린구간 ({c.a}, {c.b})에서 평균값 정리를 "
                f"만족시키는 c와, f'(x) = f'(c)를 만족시키는 또 하나의 실수 x = e가 있다. "
                "c + e의 값을 구하시오."
            ),
            answer_text=frac_text(total),
            explanation=f"{render_poly(eq)} = 0의 두 근이 c와 e이므로 합은 {frac_text(total)}이다.",
            conditions=f"{poly_to_sympy_str(eq)} = 0",
            answer_map=(),
            problem_type_code=_SOLVE,
            answer_format=answer_format_of(total),
            answer_aggregate="sum",
        )

    def k5(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        # 이차함수 f(x) = px^2 + qx + r의 구간 [a, k] (k > a)에서 평균값 정리의 c가 주어진다.
        sym = sympy.Symbol("k")
        c_given = Fraction(c.a + c.b, 2)
        k_val = c.b
        f_k = poly_to_sympy(c.f).subs(_X, sym)
        f_a = eval_at(c.f, c.a)
        cs = frac_text(c_given)
        deriv = f"Derivative({poly_to_sympy_str(c.f)}, x).doit().subs(x, {cs})"
        cond = f"{deriv} = ({sympy.sstr(f_k)} - ({f_a}))/(k - ({c.a}))"
        check = sympy.solve(
            sympy.Eq(
                sympy.diff(poly_to_sympy(c.f), _X).subs(
                    _X, sympy.Rational(c_given.numerator, c_given.denominator)
                ),
                (f_k - f_a) / (sym - c.a),
            ),
            sym,
        )
        if sympy.Integer(k_val) not in check:
            return None
        return DiffItem(
            slot="mastery_check",
            frame_id="mastery-find-upper-endpoint",
            question_text=(
                f"함수 f(x) = {_fx(c)}에 대하여 닫힌구간 [{c.a}, k] (k > {c.a})에서 평균값 "
                f"정리를 만족시키는 c의 값이 {cs}일 때, k의 값을 구하시오."
            ),
            answer_text=str(k_val),
            explanation=(
                f"이차함수의 c는 구간의 중점이므로 ({c.a} + k)/2 = {cs}에서 k = {k_val}이다."
            ),
            conditions=(cond, f"k > {c.a}"),
            answer_map=(("k", str(k_val)),),
            problem_type_code=_SOLVE,
            answer_format=answer_format_of(k_val),
        )

    def k6(p: tuple[object, ...]) -> DiffItem | None:
        c = _case_of(p[0])
        eq, m = _fprime_eq_rate_poly(c)
        distinct = len(set(sympy.real_roots(sympy.Poly(poly_to_sympy(eq), _X))))
        fa, fb = eval_at(c.f, c.a), eval_at(c.f, c.b)
        return KindedDiffItem(
            slot="mastery_check",
            frame_id="mastery-count-parallel-tangent-points",
            question_text=(
                f"곡선 y = {_fx(c)} 위의 두 점 A({c.a}, {fa}), B({c.b}, {fb})에 대하여, 이 곡선 "
                "위의 점 중 접선이 직선 AB와 평행한 점의 개수를 구하시오. (단, 구간은 "
                "제한하지 않는다.)"
            ),
            answer_text=str(distinct),
            explanation=f"{render_poly(eq)} = 0의 서로 다른 실근이 {distinct}개이다.",
            conditions=f"{poly_to_sympy_str(eq)} = 0",
            answer_map=(),
            problem_type_code=_COUNT,
            answer_format=AnswerFormat.자연수,
            answer_kind="real_root_count",
        )

    return [
        Frame("mastery-root-outside-interval", _frames_params("p3-mvt:k1", _cubic_cases()), k1),
        Frame(
            "mastery-two-intervals-equal-average-rate",
            _frames_params("p3-mvt:k2", _quad_cases()),
            k2,
        ),
        Frame("mastery-find-k-tangent-parallel", tuple(_k_params("p3-mvt:k3")), k3),
        Frame("mastery-sum-of-c-and-outside-root", _frames_params("p3-mvt:k4", _cubic_cases()), k4),
        Frame("mastery-find-upper-endpoint", _frames_params("p3-mvt:k5", _quad_cases()), k5),
        Frame(
            "mastery-count-parallel-tangent-points", _frames_params("p3-mvt:k6", _cubic_cases()), k6
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
        return round_robin_items(_SLOT_FRAMES[slot](), cls.slot_count, claimed=claimed)

    def _assemble(self, spec: EquivalenceSpec, item: DiffItem) -> CandidateProblem:
        return with_item_kinds(super()._assemble(spec, item), item)
