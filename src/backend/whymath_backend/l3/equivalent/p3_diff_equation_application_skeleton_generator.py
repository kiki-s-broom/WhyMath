"""[12미적Ⅰ-02-09] 방정식과 부등식에의 활용 결정론 문항 생성기 — P3-03(결정론·LLM 0).

개념: `H:12미적Ⅰ02-09`(`math.calculus.bangjeongsik-budeungsikeui-hwalyong`). 명세의 핵심 오개념은
M0677(f(x) = k의 근의 개수를 그래프와 가로선 y = k의 교점으로 보는 관점을 못 쓴다)이다. 이 M-id에는
L4 카탈로그의 kebab이 **없다**(MISC-40이 omission형이라 의도적으로 미승격). 그래서 오개념 유발
슬롯의 `distractor_map`은 **M-id를 그대로** 쓴다(계측기가 M-id를 그대로 센다). 신규 id는 만들지
않는다. 대신 L4 참조 무결성 검증자(`validate_distractor_map`)는 M-id를 알지 못해 위반으로 읽는다
— 등록 때 처분이 필요하다(작성자 보고 참조).

5회차 은행 감사(2026-10-08) 처분 — M0677 연결 정지·M0615로 귀속
--------------------------------------------------------------
M0677의 정본 설명은 서술어가 잘린 손상 원문('…관점을')이라 *잘못된 절차*가 적혀 있지 않다. 그래서
어떤 선지가 'M0677에서 나오는 값'인지 판정할 수 없다(판정자 지적 12건 · 판정기 M-link-undescribed).
원문 정정은 별건 QUAL-14가 소유하므로, 그 전까지 오개념 유발 슬롯은 **차수 세기 선지를 M0615**(정본
설명 '고차방정식의 근을 두 개로 단정한다(차수만큼 근)' — 괄호의 '차수만큼 근을 센다' 절차)에
연결한다. M0615의 설명도 '두 개로 단정'과 '차수만큼'을 함께 적은 이중 서술이라, 사차 문항의 차수
선지(4)가 앞 절('두 개')과는 맞지 않는다 — 원문 정정 대상으로 보고한다. 임계점 개수 선지는 귀속할
오개념의 절차 설명이 없어 연결하지 않는다. 개수 정답은 차수·임계점 개수와 다르게 고른다(판정기
T09-degree-count·T09-critical-count — 차수 세기·임계점 세기 오답 경로가 정답에 닿지 않게). 이 귀속은
명세의 핵심 오개념(M0677)과 다르므로 Phase 3 커버리지의 02-09 오개념 사슬은 M0677 정정 후 재연결까지
끊긴다(테스트가 그 상태를 동결한다).

3차 감사(2026-10 · κ 0.854)가 드러낸 구조 원인과 이 파일의 재설계
---------------------------------------------------------------
종전 은행의 02-09 결함 61/72는 한 원인이었다 — 기계 검증을 위해 **정수 근**을 가진 다항식을
골랐는데, 바로 그 성질이 인수정리·인수분해 우회로를 열었다. 실근 개수형은 인수분해로 끝났고,
등호형('부등식이 성립한다 · 등호가 성립하는 x')은 등호점이 곧 정수 중근이라 인수정리로 바로
나왔다. 1·2회차 교정은 지적된 틀을 지우기만 해 같은 원인이 새 틀로 재발했다.

이번 재설계는 우회로를 **생성 시점에 코드로 차단**한다(우회로 판정기 `p3_diff_shortcut_guard` —
`_validate_slot`이 문항마다 부르고 위반이면 빌드를 멈춘다). 이 파일의 문항은 세 갈래다:

  · **실근 개수(수준선)** — 방정식 f(x) = k의 f - k가 **유리수 근을 갖지 않는다**(인수정리 불가).
    도함수의 근(임계점)은 정수라 극값은 깔끔하지만 실근은 무리수다(예 x^3 - 3x + 1: 임계점 ±1,
    극값 -1·3). 실근 개수는 도함수 → 극값 → 증감 구간마다 f가 지나는 값의 범위로만 정해진다.
    사차는 어떤 x = h에 대해 대칭인 식(복이차식 — (x - h)^2 = u로 이차방정식이 된다)을 뺀다.
  · **극값을 계산하는 진단** — 5회차 감사 처분으로 구판 '극값 증인'(극댓값·극솟값을 발문이 주고 식은
    주지 않던 틀 — 도함수 없이 개형 상식과 대소 비교만으로 풀렸다 · 판정기
    T09-given-extremum-values)을 지웠다. 진단 슬롯도 함수를 명시하고 학생이 극값을 미분으로 구해
    개수를 정한다(수준선 풀의 몫).
  · **최솟값(부등식 증명의 핵심 단계)** — '부등식이 성립함을 보이려 한다 · 두 변의 차의 최솟값'.
    등호형(등호점 = 정수 중근)은 **쓰지 않는다**(판정기 T09-repeated-root·T09-rational-root가 형태
    자체를 막는다). 최솟값은 임계점에서의 극값이라 도함수 없이는 위치를 알 수 없고, 발문은 그 위치를
    알려 주지 않는다(판정기 T09-pinned-minimizer). 답은 스칼라 하나이고 문자 k가 없다 — P3-20의
    '매개변수 범위형'(답이 k의 범위)이 아니다(아래 '범위').

범위 — 수치형만(P3-20 판정 §3·§4·§6 준수)
-----------------------------------------
**매개변수(k) 범위형 문항은 만들지 않는다**(검증 경로 없음 — skip은 통과가 아니다). 모든 문항은
계수가 숫자이고 답이 숫자 하나다. 최솟값형은 'k의 최댓값' 같은 매개변수 표현도 쓰지 않는다 — 같은
수학을 '두 변의 차의 최솟값'으로 묻는다. 검산은 Tier1이다: 조건 `f'(x) = 0`·`y = f(x)`(·범위)를
최솟값을 갖는 x(작성자가 SymPy로 확인한 전역 최솟점)와 최솟값 y로 대입한다 — 극댓값·경계값·틀린
값은 y = f(x)에서 떨어진다(02-08 규칙 C3과 같은 'x 고정' 방식).

P3-20 §3 지침: 실근 개수형을 한 슬롯에 몰아 쓰지 않는다 — 대표·기본·응용·숙련도 슬롯은 개수형과
최솟값형을 섞고, 오개념 유발 슬롯(객관식 개수형)과 진단 슬롯(극값을 계산하는 개수형)만 예외다.

QUAL-07 — 같은 수학 실체 중복 금지: 한 수준선 풀을 여러 틀이 쓸 때는 풀을 서로소 몫으로 나눠
(`_part`) 같은 방정식이 표기만 바꿔(방정식 = 0 / 곡선과 직선 / 두 곡선) 두 번 나오지 않게 한다.

문제유형 정직성
--------------
실근 개수 → `ptype.count-solutions`, 최솟값 → `ptype.optimize-extremum`. 이 개념의 명세 스킬
(`case-analysis`·`word-problem-modeling`)과 겹치는 유형은 `count-solutions`(case-analysis)뿐이다 —
최솟값 문항을 거짓 유형으로 맞추지 않는다.

게이트 재료 확장: `KindedDiffItem`(`p3_diff_mean_value_theorem_skeleton_generator`)을 쓰고
`_assemble`에서 `with_item_kinds`로 후보에 싣는다(base 모듈 무수정).
"""

from __future__ import annotations

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
    with_item_kinds,
)
from whymath_backend.l3.equivalent.p3_diff_shortcut_guard import (
    has_rational_root,
    is_shifted_biquadratic,
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

# 오개념 유발 선지의 연결 id — **M0615**(정본 설명 '고차방정식의 근을 두 개로 단정한다(차수만큼 근)'
# · [10공수1-02-07] 소속 M-id 그대로, kebab 좌석 없음). 5회차 감사(2026-10-08)까지는 이 개념의 핵심
# 오개념 M0677에 연결했으나, M0677의 설명은 서술어가 끊긴 손상 문장('…관점을')이라 잘못된 *절차*를
# 적지 않아 연결 선지가 그 오개념에서 나오는 값인지 판정할 수 없었다(판정자 지적 12건 · 판정기
# M-link-undescribed · 원문 정정은 QUAL-14 소관). 차수로 센 값의 선지만 절차('차수만큼 근')가 적힌
# M0615로 연결하고, 임계점(극값 후보) 개수 선지는 그 절차를 적은 오개념이 없어 **연결하지 않는다**
# (연결 없는 오답 선지는 결함이 아니다).
_DEGREE_MID: Final = "M0615"
_COUNT: Final = "ptype.count-solutions"
_OPT: Final = "ptype.optimize-extremum"
_KIND: Final = "real_root_count"
_X = sympy.Symbol("x")
#: 최솟값형 다항식의 계수 상한(절댓값) — 손계산이 가능한 크기로 묶는다.
_COEF_CAP: Final = 160


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


def _rational_root(poly: Poly) -> bool:
    """유리수 근이 있는가 — 판정기(`has_rational_root`)와 같은 술어로 미리 거른다."""
    return has_rational_root(poly_to_sympy(poly), _X)


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


def _part[T](
    seed: str, pool: Sequence[T], index: int, parts: int
) -> tuple[tuple[object, ...], ...]:
    """풀을 시드 순서로 섞어 서로소 몫 `parts`개로 나눈 뒤 index번째 몫을 틀 파라미터로 낸다.

    같은 방정식이 표기만 바꿔(방정식 = 0 / 곡선과 직선 / 두 곡선) 두 틀에 나오면 검산 조건 문자열은
    달라도 *같은 수학 실체*다(QUAL-07). 한 풀을 쓰는 틀끼리 몫을 나눠 그 중복을 원천 차단한다.
    """
    ordered = seeded_order(seed, tuple(pool))
    return tuple((value,) for value in ordered[index::parts])


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


# ──────────────────────────────────────────────────────────────────────────
# 수준선 풀 — f'의 근이 정수(단순근)이고 f - k가 유리근을 갖지 않는다(인수분해로 못 푼다)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class _Level:
    """방정식 f(x) = k — f는 다항식(수준선 풀은 상수항 0), crit는 f'의 근(정수·단순근)."""

    poly: Poly
    crit: tuple[int, ...]
    k: int

    @property
    def equation(self) -> Poly:
        """f - k(학생이 보는 방정식의 한 변 = 0 꼴)."""
        return _minus(self.poly, self.k)


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
                    if k in vals or k == 0 or _rational_root(_minus(f, k)):
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
                    if k in vals or _rational_root(eq) or not _no_nonpositive_real_root(eq):
                        continue
                    out.append(_Level(f, (p, q), k))
    return tuple(out)


@lru_cache(maxsize=None)
def _quartic_levels() -> tuple[_Level, ...]:
    """f'(x) = 12(x - p)(x - q)(x - r)인 W자 사차식 — 실근 2개 또는 4개, 비대칭(복이차식 아님)."""
    out: list[_Level] = []
    for p, q, r in combinations(range(-2, 3), 3):
        f = _crit_quartic(p, q, r)
        vals = tuple(eval_at(f, c) for c in (p, q, r))
        if max(abs(v) for v in vals) > 60:
            continue
        for k in range(min(vals) - 3, max(vals) + 4):
            eq = _minus(f, k)
            if k in vals or k == 0 or _rational_root(eq) or _n_distinct(eq) not in (2, 4):
                continue
            if is_shifted_biquadratic(poly_to_sympy(eq), _X):
                continue  # (x - h)^2 = u로 이차방정식이 되는 대칭 사차식(3차 감사 R5 지적)
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


def _zero_level(level: _Level) -> _Level:
    """f(x) = k를 F(x) = 0(F = f - k)로 옮긴 수준선 — '방정식 F(x) = 0'·'x축과의 교점' 틀용."""
    return _Level(level.equation, level.crit, 0)


def _split_curves(poly: Poly) -> tuple[Poly, Poly] | None:
    """사차 P = g - h — g는 3차 이상 항, h는 (-1)·(2차 이하 항)인 이차식."""
    g = tuple((e, c) for e, c in poly if e >= 3)
    h = tuple((e, -c) for e, c in poly if e <= 2)
    if not h or h[0][0] != 2:
        return None
    return g, h


def _split_line(poly: Poly) -> tuple[Poly, Poly] | None:
    """P = g - h — g는 2차 이상 항, h는 (-1)·(1차 이하 항)인 직선(기울기 0이면 None)."""
    g = tuple((e, c) for e, c in poly if e >= 2)
    h = tuple((e, -c) for e, c in poly if e < 2)
    if not h or dict(h).get(1, 0) == 0:
        return None
    return g, h


def _has_rootless_factor(poly: Poly) -> bool:
    """실근이 없는 유리계수 인수가 있는가.

    객관식 해설이 '항상 양수'를 설명해야 하는 경우를 피한다.
    """
    expr = poly_to_sympy(poly)
    _, factors = sympy.factor_list(expr, _X)
    return any(sympy.degree(f, _X) >= 2 and not sympy.real_roots(f) for f, _ in factors)


def _level_of(x: object) -> _Level:
    assert isinstance(x, _Level)
    return x


# ──────────────────────────────────────────────────────────────────────────
# 최솟값 풀 — 부등식을 보이는 핵심 단계(두 변의 차의 최솟값). 등호형(정수 중근)은 쓰지 않는다.
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class _Min:
    """최솟값 사례 — 다항식 f가 범위(전 실수 / x >= 0 / x > 0)에서 x = at일 때 최솟값 value(> 0).

    `at`·`value`는 생성기가 SymPy로 확인한 **전역** 최솟점·최솟값이다(극솟값이 여럿이면 작은 쪽,
    범위 경계가 있으면 경계값과도 비교). 극댓값·경계값을 답으로 내면 검산 y = f(x)에서 떨어진다.
    """

    poly: Poly
    crit: tuple[int, ...]
    at: int
    value: int


def _capped(poly: Poly) -> bool:
    return max(abs(c) for _, c in poly) <= _COEF_CAP


def _global_min_on(poly: Poly, lower: int | None) -> tuple[Fraction, Fraction] | None:
    """범위(lower가 None이면 전 실수, 아니면 x >= lower)에서의 전역 최솟점·최솟값(SymPy 독립 경로).

    임계점(실근)과 경계를 전부 비교한다 — 최솟값을 갖는 x가 하나뿐일 때만 낸다.
    """
    expr = poly_to_sympy(poly)
    crit = [r for r in sympy.real_roots(sympy.Poly(sympy.diff(expr, _X), _X))]
    cands = [r for r in crit if lower is None or r >= lower]
    if lower is not None:
        cands.append(sympy.Integer(lower))
    if not cands:
        return None
    values = [(expr.subs(_X, c), c) for c in cands]
    best = min(v for v, _ in values)
    where = {c for v, c in values if v == best}
    if len(where) != 1:
        return None
    point = next(iter(where))
    if not (point.is_rational and best.is_rational):
        return None
    return Fraction(int(point.p), int(point.q)), Fraction(int(best.p), int(best.q))


@lru_cache(maxsize=None)
def _min_cubic_cases() -> tuple[_Min, ...]:
    """x >= 0(또는 x > 0)에서의 삼차함수 최솟값 — f'(x) = 3L(x - p)(x - q), p <= 0 < q.

    x >= 0에서 f는 0 <= x <= q에서 감소, x >= q에서 증가하므로 최솟값은 x = q에서의 극솟값이다.
    """
    out: list[_Min] = []
    for lead in (1, 2):
        for p in (-3, -2, -1, 0):
            for q in (1, 2, 3):
                f0 = _crit_cubic(lead, p, q)
                if f0 is None:
                    continue
                base = eval_at(f0, q)
                for value in (1, 2, 3, 4, 5, 6):
                    f = _poly(poly_to_sympy(f0) + (value - base))
                    if not _capped(f):
                        continue
                    found = _global_min_on(f, 0)
                    if found != (Fraction(q), Fraction(value)):
                        continue  # pragma: no cover — 구성 오류(경계·극솟값 비교)
                    out.append(_Min(f, (p, q), q, value))
    return tuple(out)


@lru_cache(maxsize=None)
def _min_quartic_single_cases() -> tuple[_Min, ...]:
    """f(x) = L(x^4 - 4a^3x) + c — f'(x) = 4L(x - a)(x^2 + ax + a^2), 임계점 a 하나(전 실수)."""
    out: list[_Min] = []
    for lead in (1, 2, 3):
        for a in (-2, -1, 1, 2):
            for value in (1, 2, 3, 4, 5):
                c = value + 3 * lead * a**4
                f = _poly(lead * (_X**4 - 4 * a**3 * _X) + c)
                if not _capped(f):
                    continue
                if _global_min_on(f, None) != (Fraction(a), Fraction(value)):
                    continue  # pragma: no cover — 구성 오류
                out.append(_Min(f, (a,), a, value))
    return tuple(out)


@lru_cache(maxsize=None)
def _min_quartic_w_cases() -> tuple[_Min, ...]:
    """W자 사차함수 _crit_quartic(p, q, r) + D — 두 극솟값이 다르고 작은 쪽이 최솟값(전 실수)."""
    out: list[_Min] = []
    for p, q, r in combinations(range(-3, 4), 3):
        f0 = _crit_quartic(p, q, r)
        vp, vr = eval_at(f0, p), eval_at(f0, r)
        if vp == vr:
            continue  # 대칭(복이차식) — 두 극솟값이 같다
        low_at, low = (p, vp) if vp < vr else (r, vr)
        if low_at == 0:
            continue  # 최솟점이 x = 0이면 상수항이 곧 답이다(우회로 판정기 T09-pinned-minimizer)
        for value in (1, 2, 3, 4, 5):
            f = _poly(poly_to_sympy(f0) + (value - low))
            if not _capped(f):
                continue
            if _global_min_on(f, None) != (Fraction(low_at), Fraction(value)):
                continue  # pragma: no cover — 구성 오류
            out.append(_Min(f, (p, q, r), low_at, value))
    return tuple(out)


def _min_of(x: object) -> _Min:
    assert isinstance(x, _Min)
    return x


def _signs_text(
    poly: Poly, crit: Sequence[int], lower: int | None, var: str = "x"
) -> tuple[str, list[str]]:
    """f'의 부호 서술 — 범위 안의 증감 구간마다 '감소/증가'를 적는다. (본문, 구간별 증감 목록)."""
    d = derivative_of(poly)
    pts = sorted(c for c in crit if lower is None or c > lower)
    bounds: list[int | None] = [lower, *pts, None]
    pieces: list[str] = []
    trend: list[str] = []
    for left, right in zip(bounds, bounds[1:], strict=False):
        if left is None and right is not None:
            sample = Fraction(right - 1)
        elif right is None and left is not None:
            sample = Fraction(left + 1)
        else:
            assert left is not None and right is not None
            sample = Fraction(left + right, 2)
        up = _frac_eval(d, sample) > 0
        word = "증가" if up else "감소"
        trend.append(word)
        if left is None:
            label = f"{var} < {right}"
        elif right is None:
            label = f"{var} > {left}"
        else:
            label = f"{left} < {var} < {right}"
        pieces.append(f"{label}에서 {word}")
    return ", ".join(pieces), trend


def _min_body(
    case: _Min,
    *,
    name: str = "f",
    lower: int | None = None,
    strict: bool = False,
    var: str = "x",
) -> str:
    """최솟값 해설 — 도함수(인수분해) → 방정식 f'(x) = 0의 근 → 범위 안의 증감 → 최솟값.

    위생 게이트 회피 규약(표기만 고른다): 함숫값 등식 'f(1) = -7'을 늘어놓지 않고 'x = 1에서
    극솟값 -7'로 쓴다. 도함수의 근은 둘 이상 밝힌다(근이 하나인 사차는 'x가 a일 때').
    """
    f = case.poly
    crit = sorted(case.crit)
    head = f"{_deriv_eq(f, name, var)}이다. "
    if len(crit) == 1:
        a = crit[0]
        quad = render_poly(_poly(_X**2 + a * _X + a * a))
        lin = render_poly(_poly(_X - a))
        return (
            head + f"이차식 {quad}의 판별식은 {a * a} - {4 * a * a} = {-3 * a * a} < 0이므로 "
            f"{with_eun_neun(quad)} 항상 양수이다. 그러므로 방정식 {name}'(x) = 0의 실근은 "
            f"{a} 하나뿐이고, {name}'(x)의 부호는 {lin}의 부호와 같다. "
            f"따라서 {name}(x)는 x ≤ {a}에서 감소하고 x ≥ {a}에서 증가하여, x가 {a}일 때 최솟값 "
            f"{with_eul_reul(case.value)} 갖는다."
        )
    roots = ", ".join(f"{var} = {c}" for c in crit)
    signs, _ = _signs_text(f, crit, lower, var)
    vals = {c: eval_at(f, c) for c in crit}
    if lower is None:
        mins = [c for c in crit if _is_local_min(f, c)]
        listed = ", ".join(f"{var} = {c}에서 {vals[c]}" for c in mins)
        tail = (
            f"극솟값은 {listed}이고, 이 가운데 작은 값 {with_i_ga(case.value)} 최솟값이다."
            if len(mins) > 1
            else f"최솟값은 {var} = {case.at}에서의 극솟값 {case.value}이다."
        )
        return (
            head
            + f"방정식 {name}'({var}) = 0의 근은 {roots}이고, {name}({var})는 {signs}한다. "
            + tail
        )
    dom = f"{var} > 0" if strict else f"{var} ≥ 0"
    outside = [c for c in crit if c <= lower]
    note = ""
    if outside:
        where = "경계" if outside[0] == lower else "밖"
        note = f"그중 {var} = {with_eun_neun(outside[0])} 범위 {dom}의 {where}에 있다. "
    return (
        head
        + f"방정식 {name}'({var}) = 0의 근은 {roots}이고, {note}범위 {dom}에서 {name}({var})는 "
        f"{signs}한다. 따라서 {dom}에서의 최솟값은 {var} = {case.at}에서의 극솟값 "
        f"{case.value}이다."
    )


def _is_local_min(poly: Poly, c: int) -> bool:
    d = derivative_of(poly)
    return (
        _frac_eval(d, Fraction(c) - Fraction(1, 2))
        < 0
        < _frac_eval(d, Fraction(c) + Fraction(1, 2))
    )


def _min_item(
    *,
    slot: str,
    frame_id: str,
    text: str,
    case: _Min,
    explanation: str,
    domain: str | None,
    var: str = "x",
) -> DiffItem:
    """최솟값 문항 — 검산: f'(x) = 0 · y = f(x) (· 범위)에 x = 최솟점, y = 최솟값을 대입한다."""
    sym = poly_to_sympy_str(case.poly, var)
    conditions: tuple[str, ...] = (f"Derivative({sym}, {var}).doit() = 0", f"y = {sym}")
    if domain is not None:
        conditions = (*conditions, domain)
    return DiffItem(
        slot=slot,
        frame_id=frame_id,
        question_text=text,
        answer_text=str(case.value),
        explanation=explanation,
        conditions=conditions,
        answer_map=((var, str(case.at)), ("y", str(case.value))),
        problem_type_code=_OPT,
        answer_format=answer_format_for(str(case.value)),
    )


def _sides_text(left: Poly, right: Poly) -> str:
    """두 변의 차 표기 '(g) - (h)' — 단항이면 괄호를 생략한다."""
    lt, rt = render_poly(left), render_poly(right)
    lt = lt if " " not in lt else f"({lt})"
    rt = rt if " " not in rt and not rt.startswith("-") else f"({rt})"
    return f"{lt} - {rt}"


def _cubic_two_curves(case: _Min) -> tuple[Poly, Poly] | None:
    """f = g - h — g는 삼차항과 일차항·상수항, h는 (-1)·이차항(포물선 y = Bx^2이 아닌 y = -Bx^2)."""
    g = tuple((e, c) for e, c in case.poly if e != 2)
    h = tuple((e, -c) for e, c in case.poly if e == 2)
    if not h or not g:
        return None
    return g, h


# ──────────────────────────────────────────────────────────────────────────
# 대표(representative)
# ──────────────────────────────────────────────────────────────────────────
def _rep_frames() -> list[Frame]:
    def r1(q: tuple[object, ...]) -> DiffItem | None:
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
            poly=level.equation,
            explanation=(
                _define("f", level.poly)
                + f"교점의 x좌표는 방정식 f(x) = {level.k}의 실근이다. "
                + body
                + f" 따라서 곡선과 직선은 서로 다른 {n}개의 점에서 만난다."
            ),
            count=n,
        )

    def r2(q: tuple[object, ...]) -> DiffItem | None:
        level = _level_of(q[0])
        body, n = _level_body(level)
        return _count_item(
            slot="representative",
            frame_id="rep-level-equation-count",
            text=(
                f"방정식 {render_poly(level.poly)} = {level.k}의 서로 다른 실근의 개수를 "
                "구하시오."
            ),
            cond=_eq_cond(level.poly, level.k),
            poly=level.equation,
            explanation=(
                _define("f", level.poly)
                + f"방정식 f(x) = {level.k}의 실근의 개수는 곡선 y = f(x)와 직선 y = {level.k}의 "
                "교점의 개수와 같다. " + body + f" 따라서 서로 다른 실근은 {n}개이다."
            ),
            count=n,
        )

    def r3(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        split = _split_line(case.poly)
        if split is None:
            return None
        g, h = split
        gt, ht = render_poly(g), render_poly(h)
        return _min_item(
            slot="representative",
            frame_id="rep-difference-minimum-nonnegative",
            text=(
                f"x ≥ 0일 때 부등식 {gt} > {with_i_ga(ht)} 성립함을 보이려 한다. x ≥ 0에서 "
                f"두 변의 차 {_sides_text(g, h)}의 최솟값을 구하시오."
            ),
            case=case,
            explanation=(
                f"두 변의 차를 f(x) = {with_ira(render_poly(case.poly))} 하자. "
                + _min_body(case, lower=0)
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 x ≥ 0에서 부등식이 성립한다."
            ),
            domain="x >= 0",
        )

    def r4(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        p = render_poly(case.poly)
        return _min_item(
            slot="representative",
            frame_id="rep-quartic-left-side-minimum",
            text=(
                f"모든 실수 x에 대하여 부등식 {p} > 0이 성립함을 보이려 한다. 좌변의 최솟값을 "
                "구하시오."
            ),
            case=case,
            explanation=(
                _define("f", case.poly)
                + _min_body(case)
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 모든 실수 x에 대하여 부등식이 "
                "성립한다."
            ),
            domain=None,
        )

    def r5(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        p = render_poly(case.poly)
        return _min_item(
            slot="representative",
            frame_id="rep-quartic-curve-above-x-axis",
            text=(
                f"곡선 y = {with_i_ga(p)} x축보다 위쪽에 있음을 보이려 한다. 이 곡선 위의 점의 "
                "y좌표의 최솟값을 구하시오."
            ),
            case=case,
            explanation=(
                _define("f", case.poly)
                + _min_body(case)
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 곡선은 x축보다 위쪽에 있다."
            ),
            domain=None,
        )

    return [
        Frame("rep-curve-meets-horizontal-line", _part("p3-eq:lv3", _cubic_levels(), 0, 8), r1),
        Frame("rep-level-equation-count", _part("p3-eq:lv3", _cubic_levels(), 1, 8), r2),
        Frame(
            "rep-difference-minimum-nonnegative", _part("p3-eq:minc", _min_cubic_cases(), 0, 8), r3
        ),
        Frame(
            "rep-quartic-left-side-minimum",
            _part("p3-eq:minq1", _min_quartic_single_cases(), 0, 4),
            r4,
        ),
        Frame(
            "rep-quartic-curve-above-x-axis", _part("p3-eq:minw", _min_quartic_w_cases(), 3, 4), r5
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 기본(basic)
# ──────────────────────────────────────────────────────────────────────────
def _basic_frames() -> list[Frame]:
    def b1(q: tuple[object, ...]) -> DiffItem | None:
        level = _zero_level(_level_of(q[0]))
        body, n = _level_body(level)
        p = render_poly(level.poly)
        return _count_item(
            slot="basic",
            frame_id="basic-cubic-equation-zero-count",
            text=f"삼차방정식 {p} = 0의 서로 다른 실근의 개수를 구하시오.",
            cond=_eq_cond(level.poly, 0),
            poly=level.poly,
            explanation=(
                _define("f", level.poly)
                + "방정식 f(x) = 0의 실근의 개수는 곡선 y = f(x)와 x축의 교점의 개수와 같다. "
                + body
                + f" 따라서 서로 다른 실근은 {n}개이다."
            ),
            count=n,
        )

    def b2(q: tuple[object, ...]) -> DiffItem | None:
        level = _level_of(q[0])
        body, n = _level_body(level)
        return _count_item(
            slot="basic",
            frame_id="basic-function-level-count",
            text=(
                f"함수 f(x) = {render_poly(level.poly)}에 대하여 방정식 f(x) = {level.k}의 "
                "서로 다른 실근의 개수를 구하시오."
            ),
            cond=_eq_cond(level.poly, level.k),
            poly=level.equation,
            explanation=(
                f"방정식 f(x) = {level.k}의 실근은 곡선 y = f(x)와 직선 y = {level.k}의 교점의 "
                f"x좌표이다. {body} 따라서 서로 다른 실근은 {n}개이다."
            ),
            count=n,
        )

    def b3(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        split = _split_line(case.poly)
        if split is None:
            return None
        g, h = split
        gt, ht = render_poly(g), render_poly(h)
        return _min_item(
            slot="basic",
            frame_id="basic-curve-above-line-gap",
            text=(
                f"x > 0에서 곡선 y = {with_eun_neun(gt)} 직선 y = {ht}보다 위쪽에 있다. x > 0에서 "
                f"곡선과 직선의 y좌표의 차 {_sides_text(g, h)}의 최솟값을 구하시오."
            ),
            case=case,
            explanation=(
                f"y좌표의 차를 f(x) = {with_ira(render_poly(case.poly))} 하자. "
                + _min_body(case, lower=0, strict=True)
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 x > 0에서 곡선은 직선보다 위쪽에 "
                "있다."
            ),
            domain="x > 0",
        )

    def b4(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        return _min_item(
            slot="basic",
            frame_id="basic-cubic-minimum-on-nonnegative-domain",
            # 4차 감사 bad_tag(불확실) 처분 — 방정식·부등식 맥락 없는 순수 최솟값은 02-07/02-08
            # 기술만으로 풀린다(판정기 T09-no-application). 최솟값(> 0)으로 '실근 없음'을 보이는
            # 방정식 활용으로 묻는다.
            text=(
                f"함수 f(x) = {render_poly(case.poly)}에 대하여 x ≥ 0에서 방정식 f(x) = 0이 실근을 "
                "갖지 않음을 보이려 한다. x ≥ 0에서 f(x)의 최솟값을 구하시오."
            ),
            case=case,
            explanation=(
                _min_body(case, lower=0)
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 x ≥ 0에서 f(x) > 0이고, 방정식 "
                "f(x) = 0은 x ≥ 0에서 실근을 갖지 않는다."
            ),
            domain="x >= 0",
        )

    def b5(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        split = _split_line(case.poly)
        if split is None:
            return None
        g, h = split
        gt, ht = render_poly(g), render_poly(h)
        return _min_item(
            slot="basic",
            frame_id="basic-quartic-two-sides-minimum",
            text=(
                f"모든 실수 x에 대하여 부등식 {gt} > {with_i_ga(ht)} 성립함을 보이려 한다. 두 변의 "
                "차 "
                f"{_sides_text(g, h)}의 최솟값을 구하시오."
            ),
            case=case,
            explanation=(
                f"두 변의 차를 f(x) = {with_ira(render_poly(case.poly))} 하자. "
                + _min_body(case)
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 모든 실수 x에 대하여 부등식이 "
                "성립한다."
            ),
            domain=None,
        )

    return [
        Frame("basic-cubic-equation-zero-count", _part("p3-eq:lv3", _cubic_levels(), 2, 8), b1),
        Frame("basic-function-level-count", _part("p3-eq:lv3", _cubic_levels(), 3, 8), b2),
        Frame("basic-curve-above-line-gap", _part("p3-eq:minc", _min_cubic_cases(), 1, 8), b3),
        Frame(
            "basic-cubic-minimum-on-nonnegative-domain",
            _part("p3-eq:minc", _min_cubic_cases(), 2, 8),
            b4,
        ),
        Frame(
            "basic-quartic-two-sides-minimum",
            _part("p3-eq:minq1", _min_quartic_single_cases(), 1, 4),
            b5,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 응용(applied)
# ──────────────────────────────────────────────────────────────────────────
def _applied_frames() -> list[Frame]:
    def a1(q: tuple[object, ...]) -> DiffItem | None:
        level = _level_of(q[0])
        body, n = _level_body(level, name="x", var="t", lower=0)
        return _count_item(
            slot="applied",
            frame_id="applied-moving-point-position-count",
            text=(
                "수직선 위를 움직이는 점 P의 시각 t (t ≥ 0)에서의 위치가 "
                f"x(t) = {render_poly(level.poly, 't')}이다. 점 P의 위치가 {with_i_ga(level.k)} "
                "되는 서로 다른 시각의 개수를 구하시오."
            ),
            cond=_eq_cond(level.poly, level.k, "t"),
            poly=level.equation,
            explanation=(
                f"위치가 {with_i_ga(level.k)} 되는 시각은 방정식 x(t) = {level.k}의 0 이상인 "
                "실근이다. " + body + f" 따라서 위치가 {with_i_ga(level.k)} 되는 시각은 {n}개이다."
            ),
            count=n,
        )

    def a2(q: tuple[object, ...]) -> DiffItem | None:
        level = _level_of(q[0])
        split = _split_curves(level.equation)
        if split is None:
            return None
        g, h = split
        body, n = _level_body(level)
        return _count_item(
            slot="applied",
            frame_id="applied-two-curves-intersections",
            text=(
                f"두 곡선 y = {render_poly(g)}, y = {render_poly(h)}의 서로 다른 교점의 개수를 "
                "구하시오."
            ),
            cond=_eq_cond(g, h),
            poly=level.equation,
            explanation=(
                "교점의 x좌표는 두 식을 같게 놓은 방정식의 실근이고, 정리하면 "
                f"{render_poly(level.poly)} = {level.k}이다. "
                + _define("f", level.poly)
                + body
                + f" 따라서 서로 다른 교점은 {n}개이다."
            ),
            count=n,
        )

    def a3(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        split = _cubic_two_curves(case)
        if split is None:
            return None
        g, h = split
        return _min_item(
            slot="applied",
            frame_id="applied-two-functions-gap-minimum",
            text=(
                f"두 함수 f(x) = {render_poly(g)}, g(x) = {render_poly(h)}에 대하여 x ≥ 0에서 "
                "f(x) > g(x)임을 보이려 한다. x ≥ 0에서 f(x) - g(x)의 최솟값을 구하시오."
            ),
            case=case,
            explanation=(
                f"h(x) = f(x) - g(x) = {with_ira(render_poly(case.poly))} 하자. "
                + _min_body(case, name="h", lower=0)
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 x ≥ 0에서 f(x) > g(x)이다."
            ),
            domain="x >= 0",
        )

    def a4(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        split = _split_curves(case.poly)
        if split is None:
            return None
        g, h = split
        gt, ht = render_poly(g), render_poly(h)
        return _min_item(
            slot="applied",
            frame_id="applied-quartic-two-sides-gap",
            text=(
                f"모든 실수 x에 대하여 {gt}의 값은 {ht}의 값보다 크다. 두 식의 값의 차 "
                f"{_sides_text(g, h)}의 최솟값을 구하시오."
            ),
            case=case,
            explanation=(
                f"두 식의 차를 f(x) = {with_ira(render_poly(case.poly))} 하자. "
                + _min_body(case)
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 앞의 식의 값이 항상 더 크다."
            ),
            domain=None,
        )

    def a5(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        split = _cubic_two_curves(case)
        if split is None:
            return None
        g, h = split
        return _min_item(
            slot="applied",
            frame_id="applied-two-moving-points-gap",
            text=(
                "수직선 위를 움직이는 두 점 P, Q의 시각 t (t ≥ 0)에서의 위치가 각각 "
                f"p(t) = {render_poly(g, 't')}, q(t) = {render_poly(h, 't')}이다. t ≥ 0에서 점 "
                "P는 "
                "항상 점 Q보다 오른쪽에 있음을 보이려 한다. t ≥ 0에서 p(t) - q(t)의 최솟값을 "
                "구하시오."
            ),
            case=case,
            explanation=(
                f"h(t) = p(t) - q(t) = {with_ira(render_poly(case.poly, 't'))} 하자. "
                + _min_body(case, name="h", lower=0, var="t")
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 t ≥ 0에서 p(t) > q(t), 즉 점 P는 "
                "항상 점 Q보다 오른쪽에 있다."
            ),
            domain="t >= 0",
            var="t",
        )

    return [
        Frame("applied-moving-point-position-count", _part("p3-eq:mv", _motion_levels(), 0, 1), a1),
        Frame("applied-two-curves-intersections", _part("p3-eq:lv4", _quartic_levels(), 0, 6), a2),
        Frame(
            "applied-two-functions-gap-minimum", _part("p3-eq:minc", _min_cubic_cases(), 3, 8), a3
        ),
        Frame(
            "applied-quartic-two-sides-gap", _part("p3-eq:minw", _min_quartic_w_cases(), 0, 4), a4
        ),
        Frame("applied-two-moving-points-gap", _part("p3-eq:minc", _min_cubic_cases(), 6, 8), a5),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 오개념 유발(misconception_trigger) — 차수만큼 근이 있다고 단정한다(M0615 · 5회차 감사 재연결)
# ──────────────────────────────────────────────────────────────────────────
def _crit_count(poly: Poly) -> int:
    """f'(x) = 0의 서로 다른 실근 수 — '극값 후보의 개수'를 근의 개수로 오인한 값."""
    return _n_distinct(derivative_of(poly))


def _mc_level_count(
    *, frame_id: str, text: str, cond: str, level: _Level, seed: str, lead_in: str
) -> DiffItem | None:
    """실근 개수 객관식 — 차수로 센 값(M0615 연결)과 극값 후보 수(미연결)를 오답 선지에 둔다.

    해설은 도함수 → 극값 → 구간별 값의 범위로 개수를 센 뒤, *오답이 왜 틀렸는지*(차수를 그대로
    셈·도함수의 근을 셈)를 오답 선지마다 한 문장씩 설명한다. 방정식은 유리수 근이 없어(3차 감사)
    인수분해로는 셀 수 없다.

    슬롯 계약(오개념 유발 슬롯은 문항마다 같은 연결 집합 · 1개 이상 — `_validate_slot`)을 지키려고
    **차수 ≠ 정답**인 수준선만 쓴다 — 차수 선지가 늘 M0615로 연결된다. 차수·극값 후보 수가 정답과
    같은 수준선은 판정기 우연 일치 규칙(T09-degree-count·T09-critical-count)이 매개변수 거부로 뺀다.
    """
    equation = level.equation
    if _has_rootless_factor(equation):
        return None
    body, correct = _level_body(level)
    degree = equation[0][0]
    crit = _crit_count(equation)
    if correct in (degree, crit):
        return None  # 차수 세기·극값 후보 세기 오답 경로가 정답과 같다(변별 없음)
    entries = [
        ChoiceEntry(str(correct), is_correct=True, sort_key=float(correct)),
        ChoiceEntry(str(degree), _DEGREE_MID, sort_key=float(degree)),
    ]
    taken = {correct, degree}
    if crit not in taken:
        entries.append(ChoiceEntry(str(crit), sort_key=float(crit)))  # 연결 없는 오답(절차 미기술)
        taken.add(crit)
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
    traps = [
        f"차수 {with_eul_reul(degree)} 그대로 실근의 개수로 세면 그래프가 직선과 실제로 몇 번 "
        "만나는지를 보지 않은 것이다."
    ]
    if crit != degree:
        traps.append(
            f"도함수가 0이 되는 서로 다른 x의 개수 {with_eun_neun(crit)} 극값 후보를 센 값일 뿐 "
            "실근의 개수가 아니다."
        )
    return _count_item(
        slot="misconception_trigger",
        frame_id=frame_id,
        text=text,
        cond=cond,
        poly=equation,
        explanation=f"{lead_in}{body} {' '.join(traps)} 따라서 서로 다른 실근은 {correct}개이다.",
        count=int(answer),
        choices=choices,
        distractors=distractors,
    )


def _misconception_frames() -> list[Frame]:
    def m1(q: tuple[object, ...]) -> DiffItem | None:
        level = _zero_level(_level_of(q[0]))
        p = render_poly(level.poly)
        return _mc_level_count(
            frame_id="mc-count-real-roots",
            text=f"방정식 {p} = 0의 서로 다른 실근의 개수로 옳은 것은?",
            cond=_eq_cond(level.poly, 0),
            level=level,
            seed=f"mc1:{level.poly}",
            lead_in=_define("f", level.poly),
        )

    def m2(q: tuple[object, ...]) -> DiffItem | None:
        level = _level_of(q[0])
        gt = render_poly(level.poly)
        return _mc_level_count(
            frame_id="mc-curve-and-horizontal-line",
            text=f"곡선 y = {gt}{wa_gwa(gt)} 직선 y = {level.k}의 교점의 개수로 옳은 것은?",
            cond=_eq_cond(level.poly, level.k),
            level=level,
            seed=f"mc2:{level.poly}:{level.k}",
            lead_in=(
                _define("f", level.poly) + f"교점의 x좌표는 방정식 f(x) = {level.k}의 실근이다. "
            ),
        )

    def m3(q: tuple[object, ...]) -> DiffItem | None:
        level = _level_of(q[0])
        return _mc_level_count(
            frame_id="mc-equation-fx-equals-k",
            text=(
                f"함수 f(x) = {render_poly(level.poly)}에 대하여 방정식 f(x) = {level.k}의 서로 "
                "다른 실근의 개수는?"
            ),
            cond=_eq_cond(level.poly, level.k),
            level=level,
            seed=f"mc3:{level.poly}:{level.k}",
            lead_in=(
                f"방정식 f(x) = {level.k}의 실근은 곡선 y = f(x)와 직선 y = {level.k}의 교점의 "
                "x좌표이다. "
            ),
        )

    def m4(q: tuple[object, ...]) -> DiffItem | None:
        level = _zero_level(_level_of(q[0]))
        p = render_poly(level.poly)
        return _mc_level_count(
            frame_id="mc-graph-meets-x-axis",
            text=f"함수 y = {p}의 그래프가 x축과 만나는 점의 개수는?",
            cond=_eq_cond(level.poly, 0),
            level=level,
            seed=f"mc4:{level.poly}",
            lead_in=(
                _define("f", level.poly) + "x축과 만나는 점의 x좌표는 방정식 f(x) = 0의 실근이다. "
            ),
        )

    def m5(q: tuple[object, ...]) -> DiffItem | None:
        level = _level_of(q[0])
        split = _split_curves(level.equation)
        if split is None:
            return None
        g, h = split
        return _mc_level_count(
            frame_id="mc-two-curves-intersections",
            text=(f"두 곡선 y = {render_poly(g)}, y = {render_poly(h)}의 교점의 개수로 옳은 것은?"),
            cond=_eq_cond(g, h),
            level=level,
            seed=f"mc5:{level.poly}:{level.k}",
            lead_in=(
                "교점의 x좌표는 두 식을 같게 놓은 방정식의 실근이고, 정리하면 "
                f"{render_poly(level.poly)} = {level.k}이다. " + _define("f", level.poly)
            ),
        )

    return [
        Frame("mc-count-real-roots", _part("p3-eq:lv3", _cubic_levels(), 4, 8), m1),
        Frame("mc-curve-and-horizontal-line", _part("p3-eq:lv3", _cubic_levels(), 5, 8), m2),
        Frame("mc-equation-fx-equals-k", _part("p3-eq:lv4", _quartic_levels(), 1, 6), m3),
        Frame("mc-graph-meets-x-axis", _part("p3-eq:lv4", _quartic_levels(), 2, 6), m4),
        Frame("mc-two-curves-intersections", _part("p3-eq:lv4", _quartic_levels(), 3, 6), m5),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 진단(diagnostic) — 극값만으로 개수 세기(식 없이) · 극값을 이용한 개수 세기
# ──────────────────────────────────────────────────────────────────────────
def _diagnostic_frames() -> list[Frame]:
    # 5회차 감사(2026-10-08) 처분 — 구판 d1·d2는 '극댓값 M, 극솟값 m을 갖는 삼차함수'처럼 함수를
    # 주지 않고 극값을 발문이 알려 줘, 도함수 없이 개형 상식과 대소 비교만으로 풀렸다(판정자 지적
    # 2359c043· 47e06865 · 판정기 T09-given-extremum-values). 함수를 명시해 극값을 *미분으로 구하게*
    # 하되, 진단의 초점(극값과 수준 k의 대소로 개수를 센다)은 발문에 그대로 둔다.
    def d1(q: tuple[object, ...]) -> DiffItem | None:
        level = _zero_level(_level_of(q[0]))
        p = render_poly(level.poly)
        body, n = _level_body(level)
        return _count_item(
            slot="diagnostic",
            frame_id="diag-count-from-computed-extrema",
            text=(
                f"함수 f(x) = {p}의 극댓값과 극솟값을 구하여 방정식 f(x) = 0의 서로 다른 실근의 "
                "개수를 구하시오."
            ),
            cond=_eq_cond(level.poly, 0),
            poly=level.equation,
            explanation=f"{body} 따라서 서로 다른 실근은 {n}개이다.",
            count=n,
        )

    def d2(q: tuple[object, ...]) -> DiffItem | None:
        level = _level_of(q[0])
        p = render_poly(level.poly)
        body, n = _level_body(level)
        return _count_item(
            slot="diagnostic",
            frame_id="diag-count-level-from-computed-extrema",
            text=(
                f"함수 f(x) = {p}의 극댓값, 극솟값과 {with_eul_reul(level.k)} 비교하여 방정식 "
                f"f(x) = {level.k}의 서로 다른 실근의 개수를 구하시오."
            ),
            cond=_eq_cond(level.poly, level.k),
            poly=level.equation,
            explanation=(
                f"방정식 f(x) = {level.k}의 실근은 곡선 y = f(x)와 직선 y = {level.k}의 교점의 "
                f"x좌표이다. {body} 따라서 서로 다른 실근은 {n}개이다."
            ),
            count=n,
        )

    def d4(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        return _min_item(
            slot="diagnostic",
            frame_id="diag-cubic-positive-on-domain",
            text=(
                f"함수 f(x) = {render_poly(case.poly)}에 대하여 x ≥ 0에서 f(x) > 0임을 보이려 "
                "한다. "
                "x ≥ 0에서 f(x)의 최솟값을 구하시오."
            ),
            case=case,
            explanation=(
                _min_body(case, lower=0)
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 x ≥ 0에서 f(x) > 0이다."
            ),
            domain="x >= 0",
        )

    def d5(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        return _min_item(
            slot="diagnostic",
            frame_id="diag-quartic-single-critical-minimum",
            # 4차 감사 처분 — 그래프와 x축의 위치 관계(교점 없음)를 보이는 활용으로 묻는다.
            text=(
                f"사차함수 y = {render_poly(case.poly)}의 그래프가 x축과 만나지 않음을 "
                "보이려 한다. 이 함수의 최솟값을 구하시오."
            ),
            case=case,
            explanation=(
                f"f(x) = {with_ira(render_poly(case.poly))} 하자. "
                + _min_body(case)
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 그래프는 x축과 만나지 않는다."
            ),
            domain=None,
        )

    def d6(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        return _min_item(
            slot="diagnostic",
            frame_id="diag-compare-two-local-minima",
            # 4차 감사 bad_tag(불확실) 처분 — '두 극솟값 중 작은 값'만 묻던 문면에 방정식 맥락을
            # 준다.
            text=(
                f"사차함수 f(x) = {render_poly(case.poly)}에 대하여 방정식 f(x) = 0이 실근을 갖지 "
                "않음을 보이려 한다. f(x)의 두 극솟값 중 작은 값을 구하시오."
            ),
            case=case,
            explanation=(
                _min_body(case)
                + " 이 값이 양수이므로 모든 실수 x에 대하여 f(x) > 0이고, 방정식 f(x) = 0은 "
                "실근을 갖지 않는다."
            ),
            domain=None,
        )

    return [
        Frame("diag-count-from-computed-extrema", _part("p3-eq:lv3", _cubic_levels(), 6, 8), d1),
        Frame(
            "diag-count-level-from-computed-extrema",
            _part("p3-eq:lv3", _cubic_levels(), 7, 8),
            d2,
        ),
        Frame("diag-cubic-positive-on-domain", _part("p3-eq:minc", _min_cubic_cases(), 4, 8), d4),
        Frame(
            "diag-quartic-single-critical-minimum",
            _part("p3-eq:minq1", _min_quartic_single_cases(), 2, 4),
            d5,
        ),
        Frame(
            "diag-compare-two-local-minima", _part("p3-eq:minw", _min_quartic_w_cases(), 2, 4), d6
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# 숙련도 확인(mastery_check)
# ──────────────────────────────────────────────────────────────────────────
def _mastery_frames() -> list[Frame]:
    def k1(q: tuple[object, ...]) -> DiffItem | None:
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
            poly=level.equation,
            explanation=(
                f"방정식 f(x) = {level.k}의 실근은 곡선 y = f(x)와 직선 y = {level.k}의 교점의 "
                f"x좌표이다. {body} 따라서 서로 다른 실근은 {n}개이다."
            ),
            count=n,
        )

    def k2(q: tuple[object, ...]) -> DiffItem | None:
        level = _level_of(q[0])
        split = _split_line(level.equation)
        if split is None:
            return None
        g, h = split
        body, n = _level_body(level)
        return _count_item(
            slot="mastery_check",
            frame_id="mastery-quartic-curve-and-line-count",
            text=(
                f"곡선 y = {render_poly(g)}{wa_gwa(render_poly(g))} 직선 y = {render_poly(h)}의 "
                "서로 다른 교점의 개수를 구하시오."
            ),
            cond=_eq_cond(g, h),
            poly=level.equation,
            explanation=(
                "교점의 x좌표는 곡선과 직선의 식을 같게 놓은 방정식의 실근이고, 정리하면 "
                f"{render_poly(level.poly)} = {level.k}이다. "
                + _define("f", level.poly)
                + body
                + f" 따라서 서로 다른 교점은 {n}개이다."
            ),
            count=n,
        )

    def k3(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        p = render_poly(case.poly)
        return _min_item(
            slot="mastery_check",
            frame_id="mastery-quartic-two-local-minima",
            text=(
                f"사차함수 f(x) = {p}에 대하여 모든 실수 x에서 f(x) > 0임을 보이려 한다. f(x)의 "
                "최솟값을 구하시오."
            ),
            case=case,
            explanation=(
                _min_body(case)
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 모든 실수 x에서 f(x) > 0이다."
            ),
            domain=None,
        )

    def k4(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        split = _cubic_two_curves(case)
        if split is None:
            return None
        g, h = split
        gt, ht = render_poly(g), render_poly(h)
        return _min_item(
            slot="mastery_check",
            frame_id="mastery-cubic-above-parabola-gap",
            text=(
                f"x > 0에서 곡선 y = {with_eun_neun(gt)} 곡선 y = {ht}보다 위쪽에 있다. x > 0에서 "
                "두 "
                f"곡선의 y좌표의 차 {_sides_text(g, h)}의 최솟값을 구하시오."
            ),
            case=case,
            explanation=(
                f"y좌표의 차를 f(x) = {with_ira(render_poly(case.poly))} 하자. "
                + _min_body(case, lower=0, strict=True)
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 x > 0에서 첫째 곡선이 둘째 곡선보다 "
                "위쪽에 있다."
            ),
            domain="x > 0",
        )

    def k5(q: tuple[object, ...]) -> DiffItem | None:
        case = _min_of(q[0])
        split = _split_line(case.poly)
        if split is None:
            return None
        g, h = split
        gt, ht = render_poly(g), render_poly(h)
        return _min_item(
            slot="mastery_check",
            frame_id="mastery-quartic-curve-above-line-gap",
            text=(
                f"모든 실수 x에 대하여 곡선 y = {with_eun_neun(gt)} 직선 y = {ht}보다 위쪽에 "
                "있음을 "
                "보이려 한다. 두 그래프의 y좌표의 차의 최솟값을 구하시오."
            ),
            case=case,
            explanation=(
                f"y좌표의 차를 f(x) = {_sides_text(g, h)} = {with_ira(render_poly(case.poly))} "
                "하자. "
                + _min_body(case)
                + f" 최솟값 {with_i_ga(case.value)} 양수이므로 곡선은 직선보다 위쪽에 있다."
            ),
            domain=None,
        )

    return [
        Frame("mastery-quartic-level-count", _part("p3-eq:lv4", _quartic_levels(), 4, 6), k1),
        Frame(
            "mastery-quartic-curve-and-line-count",
            _part("p3-eq:lv4", _quartic_levels(), 5, 6),
            k2,
        ),
        Frame(
            "mastery-quartic-two-local-minima",
            _part("p3-eq:minw", _min_quartic_w_cases(), 1, 4),
            k3,
        ),
        Frame(
            "mastery-cubic-above-parabola-gap", _part("p3-eq:minc", _min_cubic_cases(), 5, 8), k4
        ),
        Frame(
            "mastery-quartic-curve-above-line-gap",
            _part("p3-eq:minq1", _min_quartic_single_cases(), 3, 4),
            k5,
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
        return round_robin_items(
            _SLOT_FRAMES[slot](),
            cls.slot_count,
            claimed=claimed,
            standard_code=cls.standard_code,  # 매개변수 거부 조건(우연 일치 — 5회차 감사)
        )

    def _assemble(self, spec: EquivalenceSpec, item: DiffItem) -> CandidateProblem:
        return with_item_kinds(super()._assemble(spec, item), item)
