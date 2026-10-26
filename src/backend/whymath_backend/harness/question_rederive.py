"""발문 독립 재유도 — 문항 본문(question_text)에서 정답을 처음부터 다시 계산한다 (P3-63 · Solution QA C5).

왜 필요한가 (P3-07 실측 · 2026-10-18)
-------------------------------------
Solution QA 의 C1 은 정답이 `verify.conditions` 를 만족하는지만 본다. 일부 생성기 계열은
conditions 를 **정답에서 역산한 식**으로 적는다(극댓값 108 문항의 `x**2 + 284*x - 42336 = 0` —
x=108 이 근이 되도록 만든 식이다). 이 경우 C1 통과는 "정답이 자기 자신에게서 유도된 식을 만족한다"
는 뜻일 뿐이고, 학생에게 보이는 **발문**이 그 정답을 낳는지는 아무 검사도 보지 않는다.

이 모듈은 그 고리를 닫는다: 발문의 함수식·조건을 읽어 정답을 **SymPy 로 다시 계산**하고, 문항의
`answer` 와 비교하는 값을 낸다(비교는 호출부 `solution_qa` C5). `verify` 는 한 글자도 읽지 않는다 —
독립성의 핵심이다. LLM 판정이 아니라 기호 계산이다(CLAUDE.md "검증 권위 ① 기계 증명").

인식 방식 — 문장 틀 전체 일치(fullmatch)
----------------------------------------
발문을 느슨하게 훑어 숫자를 줍지 않는다. 생성기 문장 틀마다 **정규식 전체 일치**로 의도를 확정하고,
함수식 칸(`f(x) = ⟨식⟩`)만 SymPy 로 읽는다. 틀에 안 맞는 발문은 억지로 풀지 않고 **미적용**으로 둔다 —
"읽었다고 믿고 틀린 값을 재유도"하는 것이 "읽지 않는 것"보다 나쁘다(거짓 FAIL 이 사람 시간을 쓴다).
식 파싱은 `l3.safe_parse.safe_sympify` 단일 진입점만 쓴다(코딩 헌법 R22-03).

상태 3종 (모른다 ≠ 아니다)
--------------------------
  · DERIVED      틀을 인식했고 값을 하나로 확정했다 → 호출부가 `answer` 와 비교(PASS/FAIL)
  · UNDECIDED    틀은 인식했는데 값이 하나로 안 정해진다(근 둘 이상·정의 불가·판정 한계) → 검증 불가
  · NOT_COVERED  인식기가 없는 틀이거나 식에 매개변수(a, k…)가 있다 → 미적용(사람 검수 목록)

정직 스코프
-----------
· 이 모듈이 읽는 것은 **함수식과 질문 의도**뿐이다. 발문의 서술 맥락(단, 조건)이 식에 영향을 주는 틀은
  그 조건까지 틀에 포함한 것만 인식한다.
· 매개변수가 든 식(`x^3 + ax^2 - 5x`)은 방정식을 세워 풀어야 해서 이번 범위 밖이다 — 미적용으로 목록화한다.
· 인식기가 맞아 보여도 **재유도 값 = 정답** 은 "발문이 이 정답을 낳는다"의 증거일 뿐, 풀이 서술의 옳음은
  C2·C4 가 따로 본다.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Final

import sympy

from whymath_backend.l3.safe_parse import safe_sympify

__all__ = [
    "FAMILY_TITLES",
    "Rederivation",
    "RederiveState",
    "rederive_question",
]

_X: Final = sympy.Symbol("x")
_T: Final = sympy.Symbol("t")


class RederiveState(str, Enum):
    DERIVED = "derived"
    UNDECIDED = "undecided"
    NOT_COVERED = "not_covered"


@dataclass(frozen=True, slots=True)
class Rederivation:
    state: RederiveState
    family: str | None = None
    """인식한 문장 틀 계열 id(`FAMILY_TITLES` 의 키). NOT_COVERED 면 None."""
    value: str | None = None
    """DERIVED 일 때 재유도한 값(SymPy 문자열). 그 밖은 None."""
    reason: str | None = None
    """UNDECIDED/NOT_COVERED 의 폐쇄 사유 코드."""


class _NotCovered(Exception):  # noqa: N818 — 오류가 아니라 '이 발문은 범위 밖' 신호
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _NoMatch(Exception):  # noqa: N818 — 접두는 맞았지만 꼬리 문장을 모르는 틀: 다음 규칙으로 넘긴다
    pass


class _Undecided(Exception):  # noqa: N818 — 오류가 아니라 '값이 하나로 안 정해짐' 신호
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ──────────────────────────────────────────────────────────────────────────
# 발문 정규화 · 식 읽기
# ──────────────────────────────────────────────────────────────────────────
# 수식 칸의 후보 문자 — 영문·숫자·연산자·괄호·절댓값 막대·공백. 한글이 나오면 그 앞에서 끝난다.
_E: Final = r"[0-9A-Za-z+\-*/^().| ]+?"
_NUM: Final = r"-?\d+(?:/\d+)?"


def _normalize(question: str) -> str:
    text = unicodedata.normalize("NFC", question).replace("−", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def _read_expr(text: str, symbols: frozenset[sympy.Symbol] = frozenset({_X})) -> sympy.Expr:
    """발문의 수식 칸 → SymPy 식. 자유 기호가 `symbols` 밖이면(매개변수) 미적용으로 분리한다."""
    raw = text.strip()
    if "..." in raw:
        raw = _expand_ellipsis(raw)
    # 절댓값 막대 → 자리표시자(@) — 아래 암묵 곱셈 규칙이 `Abs` 글자를 건드리지 않게 한다.
    raw = re.sub(r"\|([^|]+)\|", r"@(\1)", raw)
    raw = re.sub(r"(?<=[a-z])(?=[a-z])", "*", raw)  # ax → a*x
    raw = re.sub(r"(?<=\d)(?=[a-z(@])", "*", raw)  # 2x · 3( → 2*x · 3*(
    raw = re.sub(r"(?<=\))(?=[a-z\d(@])", "*", raw)  # )x · )( · )2
    raw = re.sub(r"(?<=[a-z])(?=[(@])", "*", raw)  # x( → x*(
    raw = raw.replace("@", "Abs")
    try:
        expr = safe_sympify(raw)
    except Exception as exc:  # noqa: BLE001 — 읽기 실패는 미적용으로 드러난다(타입명만 사유에)
        raise _NotCovered(f"PARSE_{type(exc).__name__}") from exc
    if not isinstance(expr, sympy.Expr):
        raise _NotCovered("PARSE_NOT_EXPR")
    if not expr.free_symbols <= symbols:
        raise _NotCovered("PARAMETER")
    return expr


def _expand_ellipsis(raw: str) -> str:
    """`x + 2x^2 + 3x^3 + ... + 8x^8` 같은 나열을 펼친다. 규칙을 확정할 수 없으면 미적용.

    머리항(2개 이상)에서 거듭제곱의 등차(공차 s)와 계수의 규칙(등차 또는 부호 교대)을 읽고, 꼬리항의
    거듭제곱까지 같은 규칙으로 채운 뒤 **꼬리항의 계수가 규칙의 예측과 일치하는지** 확인한다 — 예측과
    다르면 규칙을 잘못 읽은 것이므로 풀지 않는다.
    """
    m = re.fullmatch(r"(?P<head>.+?) \+ \.\.\. (?P<ts>[+-]) (?P<tail>.+)", raw)
    if m is None:
        raise _NotCovered("ELLIPSIS_SHAPE")
    term = re.compile(r"\s*([+-]?)\s*(\d*)x(?:\^(\d+))?")
    whole = re.compile(rf"(?:{term.pattern})+")

    def terms(text: str) -> list[tuple[int, int]]:
        if whole.fullmatch(text) is None:
            raise _NotCovered("ELLIPSIS_TERM_SHAPE")
        out: list[tuple[int, int]] = []
        for sign, coef, power in term.findall(text):
            out.append(((-1 if sign == "-" else 1) * int(coef or 1), int(power or 1)))
        return out

    head = terms(m["head"])
    (tail_coef, tail_pow) = terms(m["ts"] + m["tail"])[0]
    if len(head) < 2:
        raise _NotCovered("ELLIPSIS_TOO_SHORT")
    step = head[1][1] - head[0][1]
    if step < 1 or any(b[1] - a[1] != step for a, b in zip(head, head[1:], strict=False)):
        raise _NotCovered("ELLIPSIS_EXPONENT_RULE")
    coefs = [c for c, _ in head]
    diffs = {b - a for a, b in zip(coefs, coefs[1:], strict=False)}
    alternating = all(b == -a for a, b in zip(coefs, coefs[1:], strict=False))
    if len(diffs) == 1:
        delta = diffs.pop()

        def predict(i: int) -> int:
            return coefs[0] + delta * i

    elif alternating:

        def predict(i: int) -> int:
            return coefs[0] * (-1) ** i

    elif coefs[0] != 0 and len(set(b / a for a, b in zip(coefs, coefs[1:], strict=False))) == 1:
        ratio = coefs[1] // coefs[0]  # 등비 — 머리항 3개 이상일 때만 공비가 확정된다

        def predict(i: int) -> int:
            return coefs[0] * ratio**i

        if len(coefs) < 3 or coefs[1] != coefs[0] * ratio:
            raise _NotCovered("ELLIPSIS_COEFFICIENT_RULE")
    else:
        raise _NotCovered("ELLIPSIS_COEFFICIENT_RULE")
    count = (tail_pow - head[0][1]) // step + 1
    if (tail_pow - head[0][1]) % step or count <= len(head) or predict(count - 1) != tail_coef:
        raise _NotCovered("ELLIPSIS_TAIL_MISMATCH")
    return " ".join(
        f"{'+' if predict(i) > 0 else '-'} {abs(predict(i))}*x^{head[0][1] + step * i}"
        for i in range(count)
    ).lstrip("+ ")


def _poly(expr: sympy.Expr, var: sympy.Symbol = _X) -> sympy.Poly:
    try:
        poly = sympy.Poly(expr, var)
    except sympy.PolynomialError as exc:
        raise _NotCovered("NOT_POLYNOMIAL") from exc
    if poly.degree() < 1:
        raise _NotCovered("DEGENERATE")
    return poly


def _clean(value: sympy.Expr) -> str:
    return str(sympy.simplify(value))


# ──────────────────────────────────────────────────────────────────────────
# 미적분 계산 도구 (SymPy)
# ──────────────────────────────────────────────────────────────────────────
def _real_roots_with_multiplicity(poly: sympy.Poly) -> list[tuple[sympy.Expr, int]]:
    counter: Counter[sympy.Expr] = Counter(sympy.real_roots(poly))
    return sorted(counter.items(), key=lambda item: float(item[0]))


def _sign_at(poly: sympy.Poly, point: float) -> int:
    value = sympy.N(poly.as_expr().subs(_X, sympy.Float(point, 30)), 30)
    return 1 if value > 0 else -1 if value < 0 else 0


def _sign_changes(derivative: sympy.Poly) -> list[tuple[sympy.Expr, int, int]]:
    """도함수의 실근 중 **부호가 바뀌는** 점 — (근, 왼쪽 부호, 오른쪽 부호). 이중근은 제외."""
    roots = _real_roots_with_multiplicity(derivative)
    if not roots:
        return []
    floats = [float(root) for root, _ in roots]
    probes = [floats[0] - 1.0]
    probes += [(a + b) / 2 for a, b in zip(floats, floats[1:], strict=False)]
    probes += [floats[-1] + 1.0]
    signs = [_sign_at(derivative, p) for p in probes]
    out: list[tuple[sympy.Expr, int, int]] = []
    for index, (root, _) in enumerate(roots):
        left, right = signs[index], signs[index + 1]
        if left != right:
            out.append((root, left, right))
    return out


def _local_extrema(f: sympy.Expr, kind: str) -> list[sympy.Expr]:
    """국소 극대(`max`)/극소(`min`)가 되는 x. 부호 변화로 판정한다(이계도함수 0 인 경우도 안전)."""
    derivative = _poly(sympy.diff(f, _X))
    want = (1, -1) if kind == "max" else (-1, 1)
    return [root for root, left, right in _sign_changes(derivative) if (left, right) == want]


def _single(values: list[sympy.Expr], reason: str) -> sympy.Expr:
    if len(values) != 1:
        raise _Undecided(f"{reason}_{len(values)}")
    return values[0]


def _local_sign(g: sympy.Expr, point: sympy.Expr, side: int) -> int:
    """`g(point + side·h)` (h→0⁺)의 부호. 처음으로 0 이 아닌 k 계 도함수의 부호 × side^k."""
    for order in range(0, 12):
        value = sympy.simplify(sympy.diff(g, _X, order).subs(_X, point))
        if value != 0:
            sign = 1 if value > 0 else -1
            return sign * (side**order)
    raise _Undecided("ABS_SIGN_UNRESOLVED")


def _resolve_abs(f: sympy.Expr, point: sympy.Expr, side: int) -> sympy.Expr:
    """`point` 의 한쪽(우 +1 · 좌 -1) 근방에서 절댓값을 벗긴 다항식 — 그 쪽 미분계수의 정확한 원천."""
    mapping: dict[sympy.Expr, sympy.Expr] = {}
    for node in f.atoms(sympy.Abs):
        (arg,) = node.args
        if arg.has(sympy.Abs):
            raise _NotCovered("NESTED_ABS")
        mapping[node] = _local_sign(arg, point, side) * arg
    return f.xreplace(mapping)


def _one_sided(f: sympy.Expr, point: sympy.Expr, side: int) -> sympy.Expr:
    """우(+1)·좌(-1) 미분계수 — 절댓값을 그 쪽 부호로 벗겨 해석적으로 미분한다(극한 계산 불필요)."""
    return sympy.simplify(sympy.diff(_resolve_abs(f, point, side), _X).subs(_X, point))


def _derivative_at(f: sympy.Expr, point: sympy.Expr) -> sympy.Expr:
    """f'(point). 절댓값 꼭짓점이면 좌·우 미분계수가 같을 때만 값으로 인정한다."""
    if not f.has(sympy.Abs):
        return sympy.simplify(sympy.diff(f, _X).subs(_X, point))
    right, left = _one_sided(f, point, +1), _one_sided(f, point, -1)
    if sympy.simplify(right - left) != 0:
        raise _Undecided("NOT_DIFFERENTIABLE_AT_POINT")
    return right


def _abs_kinks(f: sympy.Expr) -> set[sympy.Expr]:
    kinks: set[sympy.Expr] = set()
    for node in f.atoms(sympy.Abs):
        (arg,) = node.args
        if arg.has(sympy.Abs):
            raise _NotCovered("NESTED_ABS")
        if arg.free_symbols - {_X}:
            raise _NotCovered("PARAMETER")
        if arg.free_symbols:
            kinks.update(root for root, _ in _real_roots_with_multiplicity(sympy.Poly(arg, _X)))
    return kinks


def _is_differentiable_everywhere(f: sympy.Expr) -> bool:
    return all(
        sympy.simplify(_one_sided(f, kink, +1) - _one_sided(f, kink, -1)) == 0
        for kink in _abs_kinks(f)
    )


# ──────────────────────────────────────────────────────────────────────────
# 문장 틀 규칙
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class _Rule:
    family: str
    pattern: re.Pattern[str]
    compute: Callable[[re.Match[str]], sympy.Expr]


_RULES: list[_Rule] = []
FAMILY_TITLES: dict[str, str] = {}


def _rule(family: str, title: str, pattern: str) -> Callable[
    [Callable[[re.Match[str]], sympy.Expr]], Callable[[re.Match[str]], sympy.Expr]
]:
    """문장 틀 하나를 등록한다. `pattern` 은 발문 **전체**에 일치해야 한다."""

    def register(
        compute: Callable[[re.Match[str]], sympy.Expr],
    ) -> Callable[[re.Match[str]], sympy.Expr]:
        FAMILY_TITLES.setdefault(family, title)
        _RULES.append(_Rule(family, re.compile(pattern), compute))
        return compute

    return register


_FN: Final = r"(?:[삼사이]차)?함수 f\(x\) = "
_SIDE: Final = {"큰": max, "작은": min}


def _pick_by_size(values: list[sympy.Expr], word: str) -> sympy.Expr:
    if not values:
        raise _Undecided("NO_REAL_CANDIDATE")
    return _SIDE[word](values, key=float)


# 접선 기울기가 K 인 점의 x좌표 중 큰/작은 값 -------------------------------------
@_rule(
    "tangent_slope_pick",
    "접선의 기울기가 K인 점의 x좌표 (큰/작은 쪽)",
    rf"곡선 y = f\(x\) = (?P<f>{_E}) 위의 점 중 접선의 기울기가 (?P<k>{_NUM})인 점의 x좌표가 "
    r"(?P<s>큰|작은) 것을 구하시오\.",
)
@_rule(
    "tangent_slope_pick",
    "접선의 기울기가 K인 점의 x좌표 (큰/작은 쪽)",
    rf"{_FN}(?P<f>{_E}) 의 그래프 위에서 접선의 기울기가 (?P<k>{_NUM})인 두 점 중 "
    r"x좌표가 (?P<s>큰|작은) 점의 x좌표를 구하시오\.",
)
def _tangent_slope_pick(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    equation = sympy.Poly(sympy.diff(f, _X) - sympy.Rational(m["k"]), _X)
    roots = [root for root, _ in _real_roots_with_multiplicity(equation)]
    return _pick_by_size(roots, m["s"])


# 극대/극소가 되는 x ----------------------------------------------------------------
@_rule(
    "local_extremum_x",
    "극대·극소가 되는 x의 값(좌표)",
    rf"{_FN}(?P<f>{_E}) ?(?:가|이) (?:(?P<k1>극대|극소)가 되는 x(?:의 값|좌표)|"
    r"(?P<k2>극댓값|극솟값)을 가질 때, 그 x의 값)(?:을|를) 구하시오\.",
)
def _local_extremum_x(m: re.Match[str]) -> sympy.Expr:
    # '극대'(대 U+B300)와 '극댓값'(댓 U+B313)은 둘째 글자가 다르다 — 접두 비교 하나로는 극댓값을 놓친다.
    kind = "max" if (m["k1"] or m["k2"]).startswith(("극대", "극댓")) else "min"
    return _single(_local_extrema(_read_expr(m["f"]), kind), "EXTREMUM_POINTS")


# 극댓값/극솟값 --------------------------------------------------------------------
@_rule(
    "local_extremum_value",
    "극댓값·극솟값",
    rf"{_FN}(?P<f>{_E}) 의 (?P<k>극댓값|극솟값)(?:을 구하시오|으로 옳은 것을 고르시오)\.",
)
@_rule(
    "local_extremum_value",
    "극댓값·극솟값",
    rf"{_FN}(?P<f>{_E}) ?(?:가|이) (?:극대|극소)일 때, 그 (?P<k>극댓값|극솟값)을 구하시오\.",
)
def _local_extremum_value(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    point = _single(
        _local_extrema(f, "max" if m["k"] == "극댓값" else "min"), "EXTREMUM_POINTS"
    )
    return sympy.simplify(f.subs(_X, point))


# 극값의 개수 -----------------------------------------------------------------------
@_rule(
    "extremum_count",
    "극값의 개수",
    rf"{_FN}(?P<f>{_E}) 의 극값의 개수를 구하시오\.",
)
def _extremum_count(m: re.Match[str]) -> sympy.Expr:
    derivative = _poly(sympy.diff(_read_expr(m["f"]), _X))
    return sympy.Integer(len(_sign_changes(derivative)))


# 미분가능성(1/0) -------------------------------------------------------------------
@_rule(
    "differentiable_flag",
    "실수 전체에서 미분가능하면 1, 아니면 0",
    rf"{_FN}(?P<f>{_E}) ?(?:이|가) 실수 전체에서 미분가능하면 1, 아니면 0을 쓰시오\.",
)
def _differentiable_flag(m: re.Match[str]) -> sympy.Expr:
    return sympy.Integer(1 if _is_differentiable_everywhere(_read_expr(m["f"])) else 0)


# x = a 에서의 미분계수 (합성·곱) ----------------------------------------------------
@_rule(
    "derivative_at_point",
    "x = a 에서의 미분계수 f'(a)",
    rf"{_FN}(?P<f>{_E}) 의 x = (?P<a>{_NUM}) 에서의 미분계수 f'\((?P=a)\) 의 값을 구하시오\.",
)
def _chain_derivative(m: re.Match[str]) -> sympy.Expr:
    return _derivative_at(_read_expr(m["f"]), sympy.Rational(m["a"]))


@_rule(
    "product_derivative_at_point",
    "두 함수 곱의 x = a 에서의 미분계수",
    rf"두 함수 f\(x\) = (?P<f>{_E}), g\(x\) = (?P<g>{_E}) 에 대하여 함수 f\(x\)g\(x\) 의 "
    rf"x = (?P<a>{_NUM}) 에서의 미분계수를 구하시오\.",
)
def _product_derivative(m: re.Match[str]) -> sympy.Expr:
    product = _read_expr(m["f"]) * _read_expr(m["g"])
    return _derivative_at(product, sympy.Rational(m["a"]))


@_rule(
    "derivative_at_point",
    "x = a 에서의 미분계수 f'(a)",
    rf"{_FN}(?P<f>{_E}) ?에 대하여 f'\((?P<a>{_NUM})\)의 값(?:을 구하시오|은\?)\.?",
)
def _derivative_at_value(m: re.Match[str]) -> sympy.Expr:
    return _derivative_at(_read_expr(m["f"]), sympy.Rational(m["a"]))


# ──────────────────────────────────────────────────────────────────────────
# 고등 미분 단원(P3-CALC1-DIFF-*) 공통 의도 — 수치 함수식만 읽는다
# ──────────────────────────────────────────────────────────────────────────
_HEAD: Final = rf"(?:(?:[삼사이]차)?함수 )?(?:f\(x\)|y) = (?P<f>{_E})"

_A = sympy.Symbol("a")


def _rat(text: str) -> sympy.Rational:
    return sympy.Rational(text)


# f'(a) 의 값 — 문장 변형 5가지 ------------------------------------------------------
@_rule(
    "derivative_at_point",
    "x = a 에서의 미분계수 f'(a)",
    rf"{_HEAD}일 때, 미분계수 f'\((?P<a>{_NUM})\)(?:를|을) 구하시오\.",
)
@_rule(
    "derivative_at_point",
    "x = a 에서의 미분계수 f'(a)",
    rf"{_HEAD}의 x = (?P<a>{_NUM})에서의 미분계수(?:를 구하시오|로 옳은 것은\?)\.?",
)
@_rule(
    "derivative_at_point",
    "x = a 에서의 미분계수 f'(a)",
    rf"{_HEAD}의 도함수 (?:f'\(x\)|y')에 x = (?P<a>{_NUM})(?:을|를) 대입한 값"
    r"(?:을 구하시오|으로 옳은 것은\?)\.?",
)
@_rule(
    "derivative_at_point",
    "x = a 에서의 미분계수 f'(a)",
    rf"{_HEAD}의 도함수 y'에 대하여 x = (?P<a>{_NUM})일 때 y'의 값은\?",
)
@_rule(
    "derivative_at_point",
    "x = a 에서의 미분계수 f'(a)",
    rf"{_HEAD} ?에 대하여 x = (?P<a>{_NUM})에서의 미분계수 f'\((?P=a)\)의 값을 구하시오\.",
)
def _derivative_at_variants(m: re.Match[str]) -> sympy.Expr:
    return _derivative_at(_read_expr(m["f"]), _rat(m["a"]))


@_rule(
    "derivative_constant_term",
    "도함수 f'(x)의 상수항",
    rf"{_HEAD}의 도함수 f'\(x\)의 상수항을 구하시오\.",
)
def _derivative_constant_term(m: re.Match[str]) -> sympy.Expr:
    return _derivative_at(_read_expr(m["f"]), sympy.Integer(0))


# 거듭제곱 함수의 도함수 cx^m 꼴 — 계수 c = n, 지수 m = n-1 -----------------------------
@_rule(
    "power_derivative_form",
    "x^n 의 도함수 cx^m 꼴의 c+m · c·m",
    r"(?:함수 )?(?:f\(x\)|g\(t\)|y) = (?P<c0>\d*)(?P<v>[xt])\^(?P<n>\d+).*?(?P<ask>[ck] \+ m|[ck]와 m의 곱).*",
)
def _power_derivative_form(m: re.Match[str]) -> sympy.Expr:
    n = int(m["n"])
    c, power = sympy.Integer(int(m["c0"] or 1) * n), sympy.Integer(n - 1)
    return c + power if "+" in m["ask"] else c * power


# 여러 함수의 f'(a) 합·차 ----------------------------------------------------------
@_rule(
    "derivative_combination",
    "여러 함수의 미분계수 합·차",
    rf"(?:(?:두 )?함수 )?(?P<defs>[fgh]\(x\) = {_E}(?:, [fgh]\(x\) = {_E})*)(?:일 때,|에 대하여) "
    r"(?P<ask>[fgh]'\(-?\d+\)(?: [+-] [fgh]'\(-?\d+\))*)의 값을 구하시오\.",
)
def _derivative_combination(m: re.Match[str]) -> sympy.Expr:
    funcs = {
        name: _read_expr(body)
        for name, body in re.findall(rf"([fgh])\(x\) = ({_E})(?:, |$)", m["defs"])
    }
    total = sympy.Integer(0)
    for sign, name, point in re.findall(r"(?:^| )([+-]?) ?([fgh])'\((-?\d+)\)", m["ask"]):
        if name not in funcs:
            raise _NotCovered("UNDEFINED_FUNCTION")
        total += (-1 if sign == "-" else 1) * _derivative_at(funcs[name], sympy.Integer(point))
    return total


# f'(a) 가 f(a) 의 몇 배 ------------------------------------------------------------
@_rule(
    "derivative_ratio",
    "f'(a) 는 f(a) 의 몇 배",
    rf"{_HEAD}에 대하여 f'\((?P<a>{_NUM})\)의 값은 f\((?P=a)\)의 값의 몇 배인지 구하시오\.",
)
def _derivative_ratio(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    a = _rat(m["a"])
    base = sympy.simplify(f.subs(_X, a))
    if base == 0:
        raise _Undecided("DIVISOR_ZERO")
    return sympy.simplify(_derivative_at(f, a) / base)


# 극한 정의형 — (f(a + c·h) - f(a)) / (d·h) 의 극한값 = f'(a)·c/d ----------------------
@_rule(
    "difference_quotient_limit",
    "차분몫의 극한 (f(a+ch)-f(a))/(dh)",
    rf"{_HEAD}에 대하여 h가 0에 한없이 가까워질 때 "
    rf"\(f\((?P<a>{_NUM}) \+ (?P<c>\d*)h\) - f\((?P=a)\)\) / (?:(?P<d>\d*)h|\((?P<d2>\d*)h\))의 "
    r"극한값을 구하시오\.",
)
def _difference_quotient_limit(m: re.Match[str]) -> sympy.Expr:
    c = int(m["c"] or 1)
    d = int((m["d"] if m["d"] is not None else m["d2"]) or 1)
    return _derivative_at(_read_expr(m["f"]), _rat(m["a"])) * sympy.Rational(c, d)


@_rule(
    "difference_quotient_limit",
    "차분몫의 극한 (f(a+ch)-f(a))/(dh)",
    rf"{_HEAD}에서 x의 값이 (?P<a>{_NUM})에서 (?P=a) \+ h까지 변할 때의 평균변화율을 구한 뒤, "
    r"h가 0에 한없이 가까워질 때의 극한값을 구하시오\.",
)
def _average_rate_limit(m: re.Match[str]) -> sympy.Expr:
    return _derivative_at(_read_expr(m["f"]), _rat(m["a"]))


# 좌·우미분계수 --------------------------------------------------------------------
@_rule(
    "one_sided_derivative",
    "x = a 에서의 우·좌미분계수(와 그 차)",
    rf"{_FN}(?P<f>{_E}) ?에 대하여 x = (?P<a>{_NUM})에서의 "
    r"(?P<w>우미분계수에서 좌미분계수를 뺀 값|우미분계수|좌미분계수)(?:을|를) 구하시오\.",
)
def _one_sided_derivative(m: re.Match[str]) -> sympy.Expr:
    f, a = _read_expr(m["f"]), _rat(m["a"])
    if m["w"] == "우미분계수":
        return _one_sided(f, a, +1)
    if m["w"] == "좌미분계수":
        return _one_sided(f, a, -1)
    return sympy.simplify(_one_sided(f, a, +1) - _one_sided(f, a, -1))


# 매개변수가 든 식이 x = r 에서 미분가능 → 매개변수(또는 f'(c)) -----------------------------
@_rule(
    "differentiable_parameter",
    "x = r 에서 미분가능할 때 상수 a(또는 f'(c))",
    rf"{_FN}(?P<f>{_E}) \((?P<p>[a-z])는 상수\)(?:가|이) x = (?P<r>{_NUM})에서 미분가능할 때, "
    rf"(?:상수 (?P=p)의 값|f'\((?P<c>{_NUM})\)의 값)을 구하시오\.",
)
def _differentiable_parameter(m: re.Match[str]) -> sympy.Expr:
    param = sympy.Symbol(m["p"])
    f = _read_expr(m["f"], frozenset({_X, param}))
    r = _rat(m["r"])
    gap = sympy.simplify(_one_sided(f, r, +1) - _one_sided(f, r, -1))
    solutions = sympy.solve(gap, param)
    if len(solutions) != 1:
        raise _Undecided(f"PARAMETER_SOLUTIONS_{len(solutions)}")
    if m["c"] is None:
        return sympy.simplify(solutions[0])
    return _derivative_at(f.subs(param, solutions[0]), _rat(m["c"]))


# ──────────────────────────────────────────────────────────────────────────
# 접선 — 곡선과 접점 + 꼬리 질문
# ──────────────────────────────────────────────────────────────────────────
def _real_roots(expr: sympy.Expr, var: sympy.Symbol = _X) -> list[sympy.Expr]:
    """다항식의 서로 다른 실근(오름차순). 다항식이 아니면 미적용."""
    try:
        poly = sympy.Poly(expr, var)
    except sympy.PolynomialError as exc:
        raise _NotCovered("NOT_POLYNOMIAL") from exc
    if poly.degree() < 1:
        raise _Undecided("CONSTANT_EQUATION")
    return [root for root, _ in _real_roots_with_multiplicity(poly)]


def _tangent(f: sympy.Expr, a: sympy.Expr) -> tuple[sympy.Expr, sympy.Expr]:
    """x = a 에서의 접선 y = m·x + n 의 (m, n)."""
    slope = sympy.simplify(sympy.diff(f, _X).subs(_X, a))
    return slope, sympy.simplify(f.subs(_X, a) - slope * a)


def _require_on_curve(f: sympy.Expr, a: sympy.Expr, b_text: str | None) -> None:
    """발문이 준 접점 (a, b) 가 곡선 위에 있는지 — 아니면 발문 자체가 모순이라 값을 정하지 않는다."""
    if b_text is None or b_text.startswith("f("):
        return
    if sympy.simplify(f.subs(_X, a) - sympy.Rational(b_text)) != 0:
        raise _Undecided("POINT_NOT_ON_CURVE")


_TANGENT_PREFIXES: Final = (
    rf"곡선 y = (?P<f>{_E}) 위의 점 \((?P<a>{_NUM}), (?P<b>{_NUM})\)에서의 접선(?P<tail>.+)",
    rf"곡선 y = (?P<f>{_E}) ?(?:위의|의) x좌표가 (?P<a>{_NUM})인 점에서의 접선(?P<tail>.+)",
    rf"{_FN}(?P<f>{_E})의 그래프 위의 점 \((?P<a>{_NUM}), (?P<b>f\((?P=a)\))\)에서의 접선"
    r"(?P<tail>.+)",
)
_TAIL_SLOPE: Final = re.compile(r"의 기울기(?:를 구하시오|는\?|로 옳은 것은\?)\.?")
_TAIL_YINT: Final = re.compile(r"(?:의 y절편(?:을 구하시오|은\?)|이 y축과 만나는 점의 y좌표를 구하시오)\.?")
_TAIL_XINT: Final = re.compile(r"이 x축과 만나는 점의 x좌표를 구하시오\.")
_TAIL_G: Final = re.compile(
    rf"의 방정식을 y = g\(x\)라 할 때, g\((?P<c>{_NUM})\)의 값(?:을 구하시오|은\?)\.?"
)
_TAIL_MN: Final = re.compile(r"의 방정식을 y = mx \+ n이라 할 때, m \+ n의 값을 구하시오\.")
_TAIL_AREA: Final = re.compile(r"과 x축, y축으로 둘러싸인 삼각형의 넓이를 구하시오\.")


def _tangent_tail(f: sympy.Expr, a: sympy.Expr, tail: str) -> sympy.Expr:
    slope, intercept = _tangent(f, a)
    if _TAIL_SLOPE.fullmatch(tail):
        return slope
    if _TAIL_YINT.fullmatch(tail):
        return intercept
    if _TAIL_XINT.fullmatch(tail):
        if slope == 0:
            raise _Undecided("HORIZONTAL_TANGENT")
        return sympy.simplify(-intercept / slope)
    if g := _TAIL_G.fullmatch(tail):
        return sympy.simplify(slope * _rat(g["c"]) + intercept)
    if _TAIL_MN.fullmatch(tail):
        return sympy.simplify(slope + intercept)
    if _TAIL_AREA.fullmatch(tail):
        if slope == 0 or intercept == 0:
            raise _Undecided("DEGENERATE_TRIANGLE")
        return sympy.simplify(sympy.Abs(intercept) * sympy.Abs(intercept / slope) / 2)
    raise _NoMatch


_TANGENT_TAILS: Final = (_TAIL_SLOPE, _TAIL_YINT, _TAIL_XINT, _TAIL_G, _TAIL_MN, _TAIL_AREA)


def _register_tangent_prefix(pattern: str) -> None:
    def compute(m: re.Match[str]) -> sympy.Expr:
        if not any(tail.fullmatch(m["tail"]) for tail in _TANGENT_TAILS):
            raise _NoMatch  # 꼬리를 모르면 식을 읽지 않는다 — 뒤 규칙(매개변수형 등)에 기회를 준다
        f, a = _read_expr(m["f"]), _rat(m["a"])
        groups = m.groupdict()
        _require_on_curve(f, a, groups.get("b"))
        return _tangent_tail(f, a, m["tail"])

    FAMILY_TITLES.setdefault("tangent_at_point", "접점이 주어진 접선의 기울기·절편·방정식")
    _RULES.append(_Rule("tangent_at_point", re.compile(pattern), compute))


for _pattern in _TANGENT_PREFIXES:
    _register_tangent_prefix(_pattern)


@_rule(
    "tangent_slope_sum_diff",
    "두 접점의 접선 기울기의 합·차",
    rf"곡선 y = (?P<f>{_E}) 위의 x좌표가 (?P<p>{_NUM})인 점과 (?P<q>{_NUM})인 점에서의 접선의 "
    r"기울기의 합을 구하시오\.",
)
def _slope_sum(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    return _tangent(f, _rat(m["p"]))[0] + _tangent(f, _rat(m["q"]))[0]


@_rule(
    "tangent_slope_sum_diff",
    "두 접점의 접선 기울기의 합·차",
    rf"곡선 y = (?P<f>{_E}) 위의 x좌표가 (?P<p>{_NUM})인 점에서의 접선의 기울기에서 "
    rf"x좌표가 (?P<q>{_NUM})인 점에서의 접선의 기울기를 뺀 값을 구하시오\.",
)
def _slope_diff(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    return _tangent(f, _rat(m["p"]))[0] - _tangent(f, _rat(m["q"]))[0]


def _positive_unique(values: list[sympy.Expr], reason: str) -> sympy.Expr:
    return _single([v for v in values if float(v) > 0], reason)


@_rule(
    "tangent_unknown_point",
    "접선의 기울기 조건으로 접점 매개변수 a 구하기",
    rf"곡선 y = (?P<f>{_E}) 위의 점 \(a, (?P<b>{_E})\) \(a > 0\)에서의 접선의 기울기가 "
    rf"(?P<k>{_NUM})일 때, a의 값은\?",
)
@_rule(
    "tangent_unknown_point",
    "접선의 기울기 조건으로 접점 매개변수 a 구하기",
    rf"곡선 y = (?P<f>{_E}) 위의 x좌표가 a인 점에서의 접선의 기울기가 (?P<k>{_NUM})일 때, "
    r"양수 a의 값을 구하시오\.",
)
def _tangent_unknown_point(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    groups = m.groupdict()
    if groups.get("b") is not None:  # 발문이 준 점 (a, b(a)) 가 곡선 위인지 — a 의 식으로 대조
        point_y = _read_expr(groups["b"], frozenset({_A}))
        if sympy.simplify(point_y - f.subs(_X, _A)) != 0:
            raise _Undecided("POINT_NOT_ON_CURVE")
    slope = sympy.diff(f, _X).subs(_X, _A) - _rat(m["k"])
    return _positive_unique(_real_roots(slope, _A), "POSITIVE_ROOTS")


@_rule(
    "tangent_by_height",
    "y좌표가 c 인 (하나뿐인) 점의 접선 기울기",
    rf"곡선 y = (?P<f>{_E}) 위의 점 중 y좌표가 (?P<c>{_NUM})인 점은 하나뿐이다\. "
    r"이 점에서의 접선의 기울기를 구하시오\.",
)
def _tangent_by_height(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    point = _single(_real_roots(f - _rat(m["c"])), "HEIGHT_POINTS")
    return _tangent(f, point)[0]


@_rule(
    "tangent_by_slope",
    "접선의 기울기가 k 인 (하나뿐인) 점의 x좌표",
    rf"곡선 y = (?P<f>{_E}) 위의 점 중 접선의 기울기가 (?P<k>{_NUM})(?:이|가) 되는 점은 "
    r"하나뿐이다\. 그 점의 x좌표를 구하시오\.",
)
def _tangent_by_slope(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    return _single(_real_roots(sympy.diff(f, _X) - _rat(m["k"])), "SLOPE_POINTS")


@_rule(
    "tangent_at_axis_crossing",
    "x축과 만나는 점 중 가장 큰 x좌표에서의 접선 기울기",
    rf"곡선 y = (?P<f>{_E})(?:이|가) x축과 만나는 점 중 x좌표가 가장 큰 점에서의 접선의 "
    r"기울기를 구하시오\.",
)
def _tangent_at_axis_crossing(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    roots = _real_roots(f)
    if not roots:
        raise _Undecided("NO_AXIS_CROSSING")
    return _tangent(f, roots[-1])[0]


# ──────────────────────────────────────────────────────────────────────────
# 수직선 위의 운동 — 위치 x(t) 에서 속도·가속도
# ──────────────────────────────────────────────────────────────────────────
_T_RANGE: Final = r"(?: \(t [>≥] 0\))?"
_MOTION: Final = rf"수직선 위(?:의|를 움직이는) 점 P의 시각 t{_T_RANGE}에서의 위치가 x = (?P<f>{_E})(?:일 때|이다)"
_Q: Final = {"속도": 1, "순간속도": 1, "가속도": 2}


def _motion_ctx(m: re.Match[str]) -> tuple[sympy.Expr, sympy.Expr, sympy.Expr]:
    pos = _read_expr(m["f"], frozenset({_T}))
    vel = sympy.diff(pos, _T)
    return pos, vel, sympy.diff(vel, _T)


def _at(expr: sympy.Expr, t: str) -> sympy.Expr:
    return sympy.simplify(expr.subs(_T, _rat(t)))


def _motion(pattern: str, family: str, title: str) -> Callable[
    [Callable[[re.Match[str]], sympy.Expr]], Callable[[re.Match[str]], sympy.Expr]
]:
    return _rule(family, title, rf"{_MOTION}, {pattern}")


@_motion(
    rf"(?:시각 |출발한 후 )?t = (?P<a>{_NUM})(?:에서의?|일 때|인 순간의?) ?(?:점 P의 )?"
    r"(?P<q>속도|가속도|순간속도)(?:를 구하시오|로 옳은 것은\?|는\?)\.?",
    "motion_at_time",
    "t = a 에서의 속도·가속도",
)
def _motion_at_time(m: re.Match[str]) -> sympy.Expr:
    _, vel, acc = _motion_ctx(m)
    return _at(vel if _Q[m["q"]] == 1 else acc, m["a"])


@_motion(
    rf"t = (?P<a>{_NUM})에서의 점 P의 속력\(속도의 절댓값\)을 구하시오\.",
    "motion_at_time",
    "t = a 에서의 속도·가속도",
)
def _motion_speed(m: re.Match[str]) -> sympy.Expr:
    return sympy.Abs(_at(_motion_ctx(m)[1], m["a"]))


@_motion(
    rf"t = (?P<a>{_NUM})에서의 점 P의 속도와 가속도의 합(?:을 구하시오\.|은\?)",
    "motion_velocity_plus_acceleration",
    "t = a 에서의 속도와 가속도의 합",
)
def _motion_va_sum(m: re.Match[str]) -> sympy.Expr:
    _, vel, acc = _motion_ctx(m)
    return _at(vel, m["a"]) + _at(acc, m["a"])


@_motion(
    rf"t = (?P<a>{_NUM})일 때와 t = (?P<b>{_NUM})일 때의 점 P의 속도의 합을 구하시오\.",
    "motion_velocity_plus_acceleration",
    "t = a 에서의 속도와 가속도의 합",
)
def _motion_two_velocities(m: re.Match[str]) -> sympy.Expr:
    vel = _motion_ctx(m)[1]
    return _at(vel, m["a"]) + _at(vel, m["b"])


@_motion(
    rf"t = (?P<a>{_NUM})에서 t = (?P<b>{_NUM})까지 점 P의 속도의 변화량을 구하시오\.",
    "motion_velocity_change",
    "속도의 변화량",
)
def _motion_velocity_change(m: re.Match[str]) -> sympy.Expr:
    vel = _motion_ctx(m)[1]
    return _at(vel, m["b"]) - _at(vel, m["a"])


@_motion(
    rf"점 P의 (?P<q>속도|가속도)가 (?P<c>{_NUM})(?:이|가) 되는 시각 t{_T_RANGE}"
    r"(?:는\?|의 값을 구하시오\.|를 구하시오\.)",
    "motion_time_when",
    "속도·가속도가 c 가 되는 시각",
)
def _motion_time_when(m: re.Match[str]) -> sympy.Expr:
    _, vel, acc = _motion_ctx(m)
    roots = _real_roots((vel if _Q[m["q"]] == 1 else acc) - _rat(m["c"]), _T)
    if "t > 0" in m.string or "t ≥ 0" in m.string:
        roots = [r for r in roots if float(r) > 0]
    return _single(roots, "TIME_ROOTS")


@_motion(
    r"점 P가 순간적으로 멈추는 시각 t \(t > 0\)의 값을 구하시오\.",
    "motion_time_when",
    "속도·가속도가 c 가 되는 시각",
)
def _motion_stop_time(m: re.Match[str]) -> sympy.Expr:
    roots = [r for r in _real_roots(_motion_ctx(m)[1], _T) if float(r) > 0]
    return _single(roots, "TIME_ROOTS")


@_motion(
    r"점 P의 가속도가 0이 되는 시각의 속도를 구하시오\.",
    "motion_velocity_when_zero_acceleration",
    "가속도가 0 인 시각의 속도",
)
def _motion_velocity_at_zero_acceleration(m: re.Match[str]) -> sympy.Expr:
    _, vel, acc = _motion_ctx(m)
    return sympy.simplify(vel.subs(_T, _single(_real_roots(acc, _T), "TIME_ROOTS")))


@_motion(
    r"점 P의 속도와 가속도가 같아지는 시각 t를 구하시오\.",
    "motion_time_when",
    "속도·가속도가 c 가 되는 시각",
)
def _motion_equal_va(m: re.Match[str]) -> sympy.Expr:
    _, vel, acc = _motion_ctx(m)
    return _single(_real_roots(vel - acc, _T), "TIME_ROOTS")


_ORDINAL: Final = {"": 0, "처음 ": 0, "처음으로 ": 0, "두 번째로 ": 1}


def _direction_changes(vel: sympy.Expr) -> list[sympy.Expr]:
    poly = _poly(vel, _T)
    changes = _sign_changes_in(poly, _T)
    return [t for t in changes if float(t) > 0]


def _sign_changes_in(poly: sympy.Poly, var: sympy.Symbol) -> list[sympy.Expr]:
    roots = [root for root, _ in _real_roots_with_multiplicity(poly)]
    if not roots:
        return []
    floats = [float(r) for r in roots]
    probes = [floats[0] - 1.0, *[(x + y) / 2 for x, y in zip(floats, floats[1:], strict=False)]]
    probes.append(floats[-1] + 1.0)
    signs = []
    for point in probes:
        value = sympy.N(poly.as_expr().subs(var, sympy.Float(point, 30)), 30)
        signs.append(1 if value > 0 else -1 if value < 0 else 0)
    return [r for i, r in enumerate(roots) if signs[i] != signs[i + 1]]


def _nth_direction_change(m: re.Match[str]) -> sympy.Expr:
    pos, vel, acc = _motion_ctx(m)
    changes = _direction_changes(vel)
    index = _ORDINAL[m["o"] or ""]
    if index >= len(changes):
        raise _Undecided("DIRECTION_CHANGE_MISSING")
    when = changes[index]
    kind = m["ask"]
    if kind == "시각 t를 구하시오.":
        return when
    if kind == "순간의 가속도를 구하시오.":
        return sympy.simplify(acc.subs(_T, when))
    return sympy.simplify(pos.subs(_T, when))


@_motion(
    r"점 P가 (?P<o>처음 |처음으로 |두 번째로 )?운동 방향을 바꾸(?:는|ㄹ) (?P<ask>시각 t를 구하시오\.)",
    "motion_direction_change",
    "운동 방향을 바꾸는 시각·위치·가속도",
)
@_motion(
    r"점 P가 (?P<o>처음 |두 번째로 )운동 방향을 바꾸는 (?P<ask>순간의 가속도를 구하시오\.)",
    "motion_direction_change",
    "운동 방향을 바꾸는 시각·위치·가속도",
)
@_motion(
    r"점 P가 (?P<o>처음 )운동 방향을 바꿀 때의 (?P<ask>점 P의 위치를 구하시오\.)",
    "motion_direction_change",
    "운동 방향을 바꾸는 시각·위치·가속도",
)
def _motion_direction_change(m: re.Match[str]) -> sympy.Expr:
    return _nth_direction_change(m)


# ──────────────────────────────────────────────────────────────────────────
# 증감·극값 좌표 — 머리(함수식) + 꼬리(질문) 표
# ──────────────────────────────────────────────────────────────────────────
def _critical_points(f: sympy.Expr) -> tuple[list[sympy.Expr], list[sympy.Expr], list[sympy.Expr]]:
    """(극대 x 목록, 극소 x 목록, f'=0 이지만 부호가 안 바뀌는 x 목록)."""
    derivative = _poly(sympy.diff(f, _X))
    changes = {root: (left, right) for root, left, right in _sign_changes(derivative)}
    maxima = [r for r, lr in changes.items() if lr == (1, -1)]
    minima = [r for r, lr in changes.items() if lr == (-1, 1)]
    flat = [r for r, _ in _real_roots_with_multiplicity(derivative) if r not in changes]
    key = float
    return sorted(maxima, key=key), sorted(minima, key=key), sorted(flat, key=key)


def _monotone_integers(f: sympy.Expr, increasing: bool) -> sympy.Expr:
    """증가(감소)하는 x 의 범위에 속하는 정수가 **하나뿐**이면 그 정수. 모호하면 보류한다.

    보류 조건: 범위가 끝없이 뻗는다(정수가 무한히 많다) · 범위 끝점이 정수다(열린/닫힌 구간에 따라
    정수 개수가 달라진다).
    """
    derivative = _poly(sympy.diff(f, _X))
    floats = [float(r) for r, _ in _real_roots_with_multiplicity(derivative)]
    if not floats:
        raise _Undecided("NO_TURNING_POINT")
    want = 1 if increasing else -1
    inf = float("inf")
    bounds = [-inf, *floats, inf]
    found: list[int] = []
    for lo, hi in zip(bounds, bounds[1:], strict=False):
        probe = hi - 1 if lo == -inf else lo + 1 if hi == inf else (lo + hi) / 2
        if _sign_at(derivative, probe) != want:
            continue
        if lo == -inf or hi == inf:
            raise _Undecided("UNBOUNDED_INTERVAL")
        if lo == math.floor(lo) or hi == math.floor(hi):
            raise _Undecided("INTEGER_ENDPOINT")
        found.extend(range(math.floor(lo) + 1, math.floor(hi) + 1))
    return _single([sympy.Integer(v) for v in found], "INTEGERS_IN_RANGE")


_GS_HEAD: Final = (
    rf"(?:(?:[삼사이]차)?함수 (?:f\(x\)|y)|곡선 y) = (?P<f>{_E}) ?(?:에서|에 대하여|이|가|의)? ?"
    r"(?P<tail>(?:[가-힣f]|x의 값이).*)"
)
_PICK: Final = r"(?P<s>큰|작은)"


_ExtremaCtx = tuple[sympy.Expr, list[sympy.Expr], list[sympy.Expr], list[sympy.Expr]]
"""(f, 극대 x 목록, 극소 x 목록, f'=0 이지만 부호가 안 바뀌는 x 목록)."""


def _both(ctx: _ExtremaCtx) -> list[sympy.Expr]:
    return sorted([*ctx[1], *ctx[2]], key=float)


_TailFn = Callable[[re.Match[str], _ExtremaCtx], sympy.Expr]
# (꼬리 정규식, 계산) — 꼬리가 하나도 안 맞으면 규칙 전체가 물러난다(_NoMatch).
_EXTREMUM_TAILS: Final[list[tuple[re.Pattern[str], _TailFn]]] = [
    (
        re.compile(r"극값을 갖는 x(?:좌표|의 값)(?:는\?|(?:를|을) 구하시오\.)"),
        lambda m, c: _single(_both(c), "CRITICAL_POINTS"),
    ),
    (
        re.compile(rf"극값을 갖는 x좌표 중 {_PICK} 값을 구하시오\."),
        lambda m, c: _pick_by_size(_both(c), m["s"]),
    ),
    (
        re.compile(rf"극(?P<k>대|소)가 되는 x(?:좌표|의 값) 중 {_PICK} 값을 구하시오\."),
        lambda m, c: _pick_by_size(c[1] if m["k"] == "대" else c[2], m["s"]),
    ),
    (
        re.compile(
            rf"(?:증가·감소가|증가와 감소가) 바뀌는 (?:점의 )?x(?:좌표|의 값) 중 {_PICK} 값을 구하시오\."
        ),
        lambda m, c: _pick_by_size(_both(c), m["s"]),
    ),
    (
        re.compile(r"증가·감소가 바뀌는 점의 x좌표(?:는\?|를 구하시오\.)"),
        lambda m, c: _single(_both(c), "CRITICAL_POINTS"),
    ),
    (
        re.compile(r"증가하다가 감소로 바뀌는 점의 x(?:좌표|의 값)(?:를|을) 구하시오\."),
        lambda m, c: _single(c[1], "CRITICAL_POINTS"),
    ),
    (
        re.compile(r"감소하다가 증가로 바뀌는 점의 x(?:좌표|의 값)(?:를|을) 구하시오\."),
        lambda m, c: _single(c[2], "CRITICAL_POINTS"),
    ),
    (
        re.compile(
            r"f'\(x\) = 0이지만 (?:증가·감소|f'\(x\)의 부호)가 바뀌지 않는 x의 값을 구하시오\."
        ),
        lambda m, c: _single(c[3], "FLAT_POINTS"),
    ),
    (
        re.compile(
            r"(?P<w>증가|감소)하는 x의 값의 범위에 속하는 정수는 하나뿐이다\. 그 정수를 구하시오\."
        ),
        lambda m, c: _monotone_integers(c[0], m["w"] == "증가"),
    ),
    (
        re.compile(
            r"x의 값이 커질 때 y의 값이 작아지는 x의 값의 범위에 속하는 정수는 하나뿐이다\. "
            r"그 정수를 구하시오\."
        ),
        lambda m, c: _monotone_integers(c[0], False),
    ),
]


@_rule("extremum_points", "극값·증감 전환점의 x좌표", _GS_HEAD)
def _extremum_points(m: re.Match[str]) -> sympy.Expr:
    for pattern, compute in _EXTREMUM_TAILS:
        tail = pattern.fullmatch(m["tail"])
        if tail is not None:
            f = _read_expr(m["f"])
            maxima, minima, flat = _critical_points(f)
            return compute(tail, (f, maxima, minima, flat))
    raise _NoMatch


@_rule(
    "extremum_points",
    "극값·증감 전환점의 x좌표",
    rf"방정식 f'\(x\) = 0의 해 중에서 함수 f\(x\) = (?P<f>{_E})(?:이|가) 극값을 갖는 x좌표는\?",
)
@_rule(
    "extremum_points",
    "극값·증감 전환점의 x좌표",
    rf"{_FN}(?P<f>{_E})의 그래프 위의 점 \(a, f\(a\)\)에서 함수 f\(x\)가 극값을 가질 때, "
    r"이 점의 x좌표 a의 값은\?",
)
def _extremum_points_unique(m: re.Match[str]) -> sympy.Expr:
    maxima, minima, _ = _critical_points(_read_expr(m["f"]))
    return _single(sorted([*maxima, *minima], key=float), "CRITICAL_POINTS")


# ──────────────────────────────────────────────────────────────────────────
# 방정식·교점의 서로 다른 실근 개수
# ──────────────────────────────────────────────────────────────────────────
def _count_real_roots(difference: sympy.Expr, var: sympy.Symbol = _X) -> sympy.Expr:
    return sympy.Integer(len(_real_roots(difference, var)))


_COUNT_ASK: Final = r"(?:를 구하시오\.|로 옳은 것은\?|는\?)"


@_rule(
    "real_root_count",
    "방정식·곡선의 서로 다른 실근(교점) 개수",
    rf"(?:삼차)?방정식 (?P<l>{_E}) = (?P<r>{_E})의 서로 다른 실근의 개수{_COUNT_ASK}",
)
def _root_count_equation(m: re.Match[str]) -> sympy.Expr:
    return _count_real_roots(_read_expr(m["l"]) - _read_expr(m["r"]))


@_rule(
    "real_root_count",
    "방정식·곡선의 서로 다른 실근(교점) 개수",
    rf"{_FN}(?P<f>{_E}) ?에 대하여 방정식 f\(x\) = (?P<k>{_NUM})의 서로 다른 실근의 개수{_COUNT_ASK}",
)
@_rule(
    "real_root_count",
    "방정식·곡선의 서로 다른 실근(교점) 개수",
    rf"{_FN}(?P<f>{_E})의 극댓값과 극솟값을 구하여 방정식 f\(x\) = (?P<k>{_NUM})의 서로 다른 "
    r"실근의 개수를 구하시오\.",
)
@_rule(
    "real_root_count",
    "방정식·곡선의 서로 다른 실근(교점) 개수",
    rf"{_FN}(?P<f>{_E})의 극댓값, 극솟값과 {_NUM}을 비교하여 방정식 f\(x\) = (?P<k>{_NUM})의 "
    r"서로 다른 실근의 개수를 구하시오\.",
)
def _root_count_level(m: re.Match[str]) -> sympy.Expr:
    return _count_real_roots(_read_expr(m["f"]) - _rat(m["k"]))


@_rule(
    "real_root_count",
    "방정식·곡선의 서로 다른 실근(교점) 개수",
    rf"곡선 y = (?P<f>{_E})(?:와|과) 직선 y = (?P<g>{_E})(?:(?:이|가) 만나는 서로 다른 점의|의 서로 다른 교점의|의 교점의)"
    rf" 개수(?:를 구하시오\.|로 옳은 것은\?)",
)
@_rule(
    "real_root_count",
    "방정식·곡선의 서로 다른 실근(교점) 개수",
    rf"두 곡선 y = (?P<f>{_E}), y = (?P<g>{_E})의 (?:서로 다른 )?교점의 개수{_COUNT_ASK}",
)
def _root_count_two_curves(m: re.Match[str]) -> sympy.Expr:
    return _count_real_roots(_read_expr(m["f"]) - _read_expr(m["g"]))


@_rule(
    "real_root_count",
    "방정식·곡선의 서로 다른 실근(교점) 개수",
    rf"함수 y = (?P<f>{_E})의 그래프가 x축과 만나는 점의 개수{_COUNT_ASK}",
)
def _root_count_axis(m: re.Match[str]) -> sympy.Expr:
    return _count_real_roots(_read_expr(m["f"]))


@_rule(
    "motion_position_count",
    "위치가 c 가 되는 서로 다른 시각의 개수",
    rf"수직선 위를 움직이는 점 P의 시각 t \(t ≥ 0\)에서의 위치가 x\(t\) = (?P<f>{_E})이다\. "
    rf"점 P의 위치가 (?P<c>{_NUM})(?:이|가) 되는 서로 다른 시각의 개수를 구하시오\.",
)
def _motion_position_count(m: re.Match[str]) -> sympy.Expr:
    pos = _read_expr(m["f"], frozenset({_T}))
    roots = _real_roots(pos - _rat(m["c"]), _T)
    return sympy.Integer(sum(1 for r in roots if float(r) >= -1e-12))


# ──────────────────────────────────────────────────────────────────────────
# 평균값 정리·롤의 정리·평균속도 — 열린구간 안의 유일한 c
# ──────────────────────────────────────────────────────────────────────────
def _in_open(value: sympy.Expr, lo: sympy.Expr, hi: sympy.Expr) -> bool:
    x = float(value)
    return float(lo) + 1e-12 < x < float(hi) - 1e-12


def _mvt_roots(f: sympy.Expr, lo: sympy.Expr, hi: sympy.Expr, var: sympy.Symbol) -> list[sympy.Expr]:
    """f'(c) = (f(hi) - f(lo)) / (hi - lo) 의 열린구간 (lo, hi) 안 실근."""
    slope = (f.subs(var, hi) - f.subs(var, lo)) / (hi - lo)
    return [r for r in _real_roots(sympy.diff(f, var) - slope, var) if _in_open(r, lo, hi)]


def _bounds(m: re.Match[str], lo_key: str = "lo", hi_key: str = "hi") -> tuple[sympy.Expr, sympy.Expr]:
    lo, hi = _rat(m[lo_key]), _rat(m[hi_key])
    if lo >= hi:
        raise _Undecided("INTERVAL_ORDER")
    return lo, hi


_RANGE_NOTE: Final = r"(?: \(단, [^)]*\))?"
_MVT_FN: Final = rf"{_FN}(?P<f>{_E}) ?에 대하여,? "
_MVT_TITLE: Final = "평균값 정리·롤의 정리·평균속도로 구하는 c"


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"{_MVT_FN}(?:닫힌구간 \[(?P<lo>{_NUM}), (?P<hi>{_NUM})\]|열린구간 \((?P<lo2>{_NUM}), (?P<hi2>{_NUM})\))"
    rf"에서 평균값 정리(?:를|의 결론을) 만족시키는 (?:상수 |실수 )?c의 값(?:을 구하시오\.|은\?|으로 옳은 것은\?)"
    rf"{_RANGE_NOTE}",
)
def _mvt_standard(m: re.Match[str]) -> sympy.Expr:
    lo, hi = _bounds(m, "lo", "hi") if m["lo"] is not None else _bounds(m, "lo2", "hi2")
    return _single(_mvt_roots(_read_expr(m["f"]), lo, hi, _X), "MVT_POINTS")


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"{_MVT_FN}(?:닫힌구간 \[(?P<lo>{_NUM}), (?P<hi>{_NUM})\]|열린구간 \((?P<lo2>{_NUM}), (?P<hi2>{_NUM})\))"
    r"에서 평균값 정리를 만족시키는 실수 c의 개수를 구하시오\.",
)
def _mvt_count(m: re.Match[str]) -> sympy.Expr:
    lo, hi = _bounds(m, "lo", "hi") if m["lo"] is not None else _bounds(m, "lo2", "hi2")
    return sympy.Integer(len(_mvt_roots(_read_expr(m["f"]), lo, hi, _X)))


def _wrapped(text: str) -> str:
    return f"({text})" if text.startswith("-") else text


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"{_FN}(?P<f>{_E}) ?에 대하여, f는 닫힌구간 \[(?P<lo>{_NUM}), (?P<hi>{_NUM})\]에서 연속이고 "
    rf"열린구간 \((?P=lo), (?P=hi)\)에서 미분가능하다\. f'\(c\) = \(f\((?P=hi)\) - f\((?P=lo)\)\)/"
    rf"\((?P<den>.+?)\)인 c가 열린구간 \((?P=lo), (?P=hi)\)에 오직 하나 존재할 때, c의 값을 구하시오\.",
)
def _mvt_stated_formula(m: re.Match[str]) -> sympy.Expr:
    lo, hi = _bounds(m)
    if m["den"] != f"{m['hi']} - {_wrapped(m['lo'])}":
        raise _Undecided("FORMULA_DENOMINATOR_MISMATCH")
    return _single(_mvt_roots(_read_expr(m["f"]), lo, hi, _X), "MVT_POINTS")


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"{_FN}(?P<f>{_E}) ?에 대하여 f\((?P<lo>{_NUM})\) = f\((?P<hi>{_NUM})\)이다\. "
    r"닫힌구간 \[(?P=lo), (?P=hi)\]에서 롤의 정리를 만족시키는 c의 값을 구하시오\.",
)
@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"{_FN}(?P<f>{_E}) ?에 대하여 f\((?P<lo>{_NUM})\) = f\((?P<hi>{_NUM})\)이므로 롤의 정리에 의하여 "
    r"f'\(c\) = 0인 c가 열린구간 \((?P=lo), (?P=hi)\)에 존재한다\. 이 c의 값을 구하시오\.",
)
def _rolle(m: re.Match[str]) -> sympy.Expr:
    f, (lo, hi) = _read_expr(m["f"]), _bounds(m)
    if sympy.simplify(f.subs(_X, lo) - f.subs(_X, hi)) != 0:
        raise _Undecided("ROLLE_PRECONDITION")
    return _single(_mvt_roots(f, lo, hi, _X), "MVT_POINTS")


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"{_FN}(?P<f>{_E})의 그래프 위의 x좌표가 (?P<lo>{_NUM}), (?P<hi>{_NUM})인 두 점을 각각 A, B라 하자\. "
    r"열린구간 \((?P=lo), (?P=hi)\)에서 곡선 y = f\(x\) 위의 점 P\(c, f\(c\)\)에서의 접선이 직선 AB와 "
    r"평행할 때, c의 값을 구하시오\.",
)
def _mvt_parallel_by_x(m: re.Match[str]) -> sympy.Expr:
    lo, hi = _bounds(m)
    return _single(_mvt_roots(_read_expr(m["f"]), lo, hi, _X), "MVT_POINTS")


def _points_on_curve(f: sympy.Expr, a: re.Match[str]) -> None:
    for x_key, y_key in (("ax", "ay"), ("bx", "by")):
        if sympy.simplify(f.subs(_X, _rat(a[x_key])) - _rat(a[y_key])) != 0:
            raise _Undecided("POINT_NOT_ON_CURVE")


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"{_FN}(?P<f>{_E}) ?에 대하여 곡선 y = f\(x\) 위의 두 점 A\((?P<ax>{_NUM}), (?P<ay>{_NUM})\), "
    rf"B\((?P<bx>{_NUM}), (?P<by>{_NUM})\)이 있다\. 열린구간 \((?P=ax), (?P=bx)\)에서 곡선 위의 점 "
    r"P\(c, f\(c\)\)에서의 접선이 직선 AB와 평행할 때, c의 값을 구하시오\.",
)
@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"{_FN}(?P<f>{_E}) ?에 대하여 곡선 y = f\(x\) 위의 두 점 A\((?P<ax>{_NUM}), (?P<ay>{_NUM})\), "
    rf"B\((?P<bx>{_NUM}), (?P<by>{_NUM})\) 사이의 곡선 위에서 직선 AB와 평행한 접선을 갖는 점의 "
    r"x좌표는\?",
)
def _mvt_parallel_by_points(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    _points_on_curve(f, m)
    lo, hi = _rat(m["ax"]), _rat(m["bx"])
    return _single(_mvt_roots(f, lo, hi, _X), "MVT_POINTS")


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"곡선 y = (?P<f>{_E}) 위의 두 점 A\((?P<ax>{_NUM}), (?P<ay>{_NUM})\), B\((?P<bx>{_NUM}), (?P<by>{_NUM})\)에 "
    r"대하여, (?P=ax) < x < (?P=bx)인 범위에서 접선이 직선 AB와 평행한 점의 개수를 구하시오\.",
)
def _mvt_parallel_count(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    _points_on_curve(f, m)
    return sympy.Integer(len(_mvt_roots(f, _rat(m["ax"]), _rat(m["bx"]), _X)))


_VELOCITY_MVT_FN: Final = r"x\(t\) = (?P<f>" + _E + ")"


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"직선 위를 움직이는 점 P의 시각 t에서의 위치가 {_VELOCITY_MVT_FN}일 때, 시각 t = (?P<lo>{_NUM})부터 "
    rf"t = (?P<hi>{_NUM})까지의 평균속도와 순간속도가 같아지는 시각 t = c \((?P=lo) < c < (?P=hi)\)의 "
    r"값을 구하시오\.",
)
@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"직선 위를 움직이는 점의 시각 t에서의 위치가 {_VELOCITY_MVT_FN}일 때, t = (?P<lo>{_NUM})부터 "
    rf"t = (?P<hi>{_NUM})까지의 평균속도와 같은 순간속도를 갖는 시각 t = c의 값은\? "
    r"\(단, (?P=lo) < c < (?P=hi)\)",
)
def _mvt_velocity(m: re.Match[str]) -> sympy.Expr:
    lo, hi = _bounds(m)
    return _single(_mvt_roots(_read_expr(m["f"], frozenset({_T})), lo, hi, _T), "MVT_POINTS")


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"수직선 위를 움직이는 점 P의 시각 t에서의 위치가 {_VELOCITY_MVT_FN}이다\. (?P<lo>{_NUM}) < t < "
    rf"(?P<hi>{_NUM})에서 점 P의 순간속도가 t = (?P=lo)부터 t = (?P=hi)까지의 평균속도와 같아지는 "
    r"시각을 t = c라 할 때, c의 값을 구하시오\.",
)
def _mvt_velocity_phrase(m: re.Match[str]) -> sympy.Expr:
    lo, hi = _bounds(m)
    return _single(_mvt_roots(_read_expr(m["f"], frozenset({_T})), lo, hi, _T), "MVT_POINTS")


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"자동차가 출발한 지 t시간 후의 이동 거리가 s\(t\) = (?P<f>{_E}) \(km\)이다\. "
    rf"(?:출발 후 (?P<lo>{_NUM})시간부터 (?P<hi>{_NUM})시간까지|출발 시각부터 (?P<hi2>{_NUM})시간 후까지)의 "
    r"평균 속도와 순간 속도가 같아지는 시각 t = c \((?P<lo3>-?\d+) < c < (?P<hi3>-?\d+)\)의 값을 구하시오\.",
)
def _mvt_car(m: re.Match[str]) -> sympy.Expr:
    lo = _rat(m["lo"] if m["lo"] is not None else "0")
    hi = _rat(m["hi"] if m["hi"] is not None else m["hi2"])
    if (lo, hi) != (_rat(m["lo3"]), _rat(m["hi3"])):
        raise _Undecided("INTERVAL_MISMATCH")
    return _single(_mvt_roots(_read_expr(m["f"], frozenset({_T})), lo, hi, _T), "MVT_POINTS")


# ──────────────────────────────────────────────────────────────────────────
# 매개변수를 조건으로 풀어 값을 구하는 틀
# ──────────────────────────────────────────────────────────────────────────
_PARAM_NAMES: Final = "abkpqcu"
_PARAMS: Final = frozenset(sympy.Symbol(ch) for ch in _PARAM_NAMES)


def _read_with_params(text: str, var: sympy.Symbol = _X) -> sympy.Expr:
    return _read_expr(text, frozenset({var, *_PARAMS}))


def _solve_params(
    equations: list[sympy.Expr], params: list[sympy.Symbol]
) -> dict[sympy.Symbol, sympy.Expr]:
    """연립방정식의 유일한 실수 해. 해가 없거나 둘 이상이면 보류(모른다 ≠ 아니다)."""
    try:
        solutions = sympy.solve(equations, params, dict=True)
    except NotImplementedError as exc:
        raise _Undecided("PARAMETER_SOLVE_FAILED") from exc
    real = [sol for sol in solutions if all(v.is_real for v in sol.values())]
    if len(real) != 1 or set(real[0]) != set(params):
        raise _Undecided(f"PARAMETER_SOLUTIONS_{len(real)}")
    return real[0]


def _free_params(*exprs: sympy.Expr) -> list[sympy.Symbol]:
    found: set[sympy.Symbol] = set()
    for expr in exprs:
        found |= expr.free_symbols
    return sorted(found - {_X, _T}, key=lambda sym: sym.name)


# 극값 조건으로 매개변수를 정한 뒤 극댓값·극솟값 -----------------------------------------------
_EXT_HEAD: Final = rf"(?:[삼사이]차)?함수 (?:f\(x\)|y) = (?P<f>{_E})"
_EXT_NOTE: Final = r"(?: \(단, (?P<n1>[a-z])(?:, (?P<n2>[a-z]))?는 상수이다\.\))?"


def _extremum_value_after(m: re.Match[str], f: sympy.Expr) -> sympy.Expr:
    maxima, minima, _ = _critical_points(f)
    ask = m["ask"]
    if ask.startswith("두 극솟값"):
        return min((sympy.simplify(f.subs(_X, r)) for r in _exactly_two(minima)), key=float)
    if ask.startswith("두 극댓값"):
        return max((sympy.simplify(f.subs(_X, r)) for r in _exactly_two(maxima)), key=float)
    points = maxima if "극댓값" in ask else minima
    return sympy.simplify(f.subs(_X, _single(points, "EXTREMUM_POINTS")))


def _exactly_two(values: list[sympy.Expr]) -> list[sympy.Expr]:
    if len(values) != 2:
        raise _Undecided(f"EXTREMA_COUNT_{len(values)}")
    return values


_EXT_ASK: Final = (
    r"(?P<ask>(?:f\(x\)의|이 함수의) 극(?:댓|솟)값을 구하시오\.|두 극솟값 중 작은 값을 구하시오\.|"
    r"두 극댓값 중 큰 값을 구하시오\.)"
)


@_rule(
    "extremum_parameter",
    "극값 조건으로 매개변수를 정한 뒤의 극댓값·극솟값",
    rf"{_EXT_HEAD} ?(?:이|가|은|는) x = (?P<r>{_NUM})에서 극값을 (?:가질 때, |갖는다\. ){_EXT_ASK}{_EXT_NOTE}",
)
@_rule(
    "extremum_parameter",
    "극값 조건으로 매개변수를 정한 뒤의 극댓값·극솟값",
    rf"{_EXT_HEAD} ?에 대하여 방정식 f'\(x\) = 0의 한 근이 x = (?P<r>{_NUM})이다\. {_EXT_ASK}{_EXT_NOTE}",
)
def _extremum_parameter(m: re.Match[str]) -> sympy.Expr:
    f = _read_with_params(m["f"])
    params = _free_params(f)
    if len(params) != 1:
        raise _NotCovered("PARAMETER_COUNT")
    solved = _solve_params([sympy.diff(f, _X).subs(_X, _rat(m["r"]))], params)
    resolved = f.subs(solved)
    maxima, minima, _ = _critical_points(resolved)
    if _rat(m["r"]) not in maxima + minima:
        raise _Undecided("GIVEN_POINT_NOT_EXTREMUM")
    return _extremum_value_after(m, resolved)


@_rule(
    "extremum_parameter",
    "극값 조건으로 매개변수를 정한 뒤의 극댓값·극솟값",
    rf"{_EXT_HEAD}(?:이|가) x = (?P<r>{_NUM})에서 극값을 갖고 f\(x\)의 (?P<kind>극댓값|극솟값)이 (?P<v>{_NUM})일 때, "
    r"상수 (?P<k>[a-z])의 값을 구하시오\. \(단, [a-z]는 상수이다\.\)",
)
@_rule(
    "extremum_parameter",
    "극값 조건으로 매개변수를 정한 뒤의 극댓값·극솟값",
    rf"{_EXT_HEAD}(?:는|은) x = (?P<r>{_NUM})에서 극값을 갖는다\. 이 함수의 (?P<kind>극댓값|극솟값)이 (?P<v>{_NUM})일 때, "
    r"상수 (?P<k>[a-z])의 값을 구하시오\. \(단, [a-z]는 상수이다\.\)",
)
def _extremum_two_parameters(m: re.Match[str]) -> sympy.Expr:
    f = _read_with_params(m["f"])
    target = sympy.Symbol(m["k"])
    others = [sym for sym in _free_params(f) if sym != target]
    if len(others) != 1:
        raise _NotCovered("PARAMETER_COUNT")
    first = _solve_params([sympy.diff(f, _X).subs(_X, _rat(m["r"]))], others)
    partial = f.subs(first)
    maxima, minima, _ = _critical_points(partial.subs(target, 0))  # 상수항은 극점 위치와 무관하다
    point = _single(maxima if m["kind"] == "극댓값" else minima, "EXTREMUM_POINTS")
    solved = _solve_params([partial.subs(_X, point) - _rat(m["v"])], [target])
    return solved[target]


@_rule(
    "extremum_parameter",
    "극값 조건으로 매개변수를 정한 뒤의 극댓값·극솟값",
    rf"{_EXT_HEAD}(?:이|가) x = (?P<r>{_NUM})에서 (?P<kind>극댓값|극솟값) (?P<v>{_NUM})(?:을|를) 가질 때, "
    r"상수 (?P<ask>[a-z])의 값을 구하시오\. \(단, [a-z](?:, [a-z])?는 상수이다\.\)",
)
def _extremum_value_given(m: re.Match[str]) -> sympy.Expr:
    f = _read_with_params(m["f"])
    params = _free_params(f)
    r = _rat(m["r"])
    equations = [sympy.diff(f, _X).subs(_X, r), f.subs(_X, r) - _rat(m["v"])]
    if len(params) != 2:
        raise _NotCovered("PARAMETER_COUNT")
    solved = _solve_params(equations, params)
    maxima, minima, _ = _critical_points(f.subs(solved))
    if r not in (maxima if m["kind"] == "극댓값" else minima):
        raise _Undecided("GIVEN_POINT_NOT_THE_STATED_EXTREMUM")
    return solved[sympy.Symbol(m["ask"])]


@_rule(
    "extremum_points",
    "극값·증감 전환점의 x좌표",
    rf"{_FN}(?P<f>{_E}) ?에 대하여 방정식 f'\(x\) = 0의 실근은 x = (?P<r1>{_NUM})과 x = (?P<r2>{_NUM})이다\. "
    r"f\(x\)의 극값을 구하시오\.",
)
def _extremum_value_with_stated_roots(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    stated = sorted([_rat(m["r1"]), _rat(m["r2"])])
    actual = [r for r, _ in _real_roots_with_multiplicity(_poly(sympy.diff(f, _X)))]
    if [float(r) for r in actual] != [float(r) for r in stated]:
        raise _Undecided("STATED_ROOTS_MISMATCH")
    maxima, minima, _ = _critical_points(f)
    point = _single(sorted([*maxima, *minima], key=float), "CRITICAL_POINTS")
    return sympy.simplify(f.subs(_X, point))


# 평균값 정리 — 도함수의 범위로 함숫값의 범위 -------------------------------------------------
@_rule(
    "mean_value_bounds",
    "평균값 정리로 구하는 k · 함숫값의 한계",
    rf"함수 f는 닫힌구간 \[(?P<lo>{_NUM}), (?P<hi>{_NUM})\]에서 연속이고 열린구간 \((?P=lo), (?P=hi)\)에서 "
    rf"미분가능하며 f\((?P=lo)\) = (?P<a>{_NUM}), f\((?P=hi)\) = (?P<b>{_NUM})이다\. 평균값 정리에 의하여 "
    r"f'\(c\) = k인 c가 이 열린구간에 존재할 때, k의 값을 구하시오\.",
)
def _mvt_k(m: re.Match[str]) -> sympy.Expr:
    lo, hi = _bounds(m)
    return (_rat(m["b"]) - _rat(m["a"])) / (hi - lo)


@_rule(
    "mean_value_bounds",
    "평균값 정리로 구하는 k · 함숫값의 한계",
    rf"함수 f\(x\)는 모든 실수 x에서 미분가능하고 f'\(x\) (?P<op>[≥≤]) (?P<m>{_NUM})이다\. "
    rf"f\((?P<a>{_NUM})\) = (?P<fa>{_NUM})일 때, f\((?P<b>{_NUM})\)의 값이 될 수 있는 "
    r"가장 (?P<w>큰|작은) 값을 구하시오\.",
)
def _mvt_one_sided_bound(m: re.Match[str]) -> sympy.Expr:
    a, b, bound = _rat(m["a"]), _rat(m["b"]), _rat(m["m"])
    if a == b:
        raise _Undecided("SAME_POINT")
    # f(b) - f(a) = f'(c)(b - a) — 구간 방향(b > a)과 부등호 방향으로 어느 쪽이 한계인지 정해진다.
    upper_limited = (m["op"] == "≤") == (b > a)  # f(b)에 위로 한계가 있나
    if (m["w"] == "큰") != upper_limited:
        raise _Undecided("UNBOUNDED_IN_ASKED_DIRECTION")
    return _rat(m["fa"]) + bound * (b - a)


@_rule(
    "mean_value_bounds",
    "평균값 정리로 구하는 k · 함숫값의 한계",
    rf"함수 f\(x\)는 모든 실수 x에서 미분가능하고 (?P<lo_m>{_NUM}) ≤ f'\(x\) ≤ (?P<hi_m>{_NUM})이다\. "
    rf"f\((?P<a>{_NUM})\) = (?P<fa>{_NUM})일 때, f\((?P<b>{_NUM})\)의 값이 될 수 있는 가장 큰 값과 "
    r"가장 작은 값의 합을 구하시오\.",
)
def _mvt_two_sided_bound_sum(m: re.Match[str]) -> sympy.Expr:
    a, b = _rat(m["a"]), _rat(m["b"])
    low_m, high_m = _rat(m["lo_m"]), _rat(m["hi_m"])
    if a == b:
        raise _Undecided("SAME_POINT")
    span = b - a
    ends = sorted([_rat(m["fa"]) + low_m * span, _rat(m["fa"]) + high_m * span])
    return ends[0] + ends[1]


# 차분몫·평균변화율의 매개변수 형 -------------------------------------------------------------
@_rule(
    "difference_quotient_limit",
    "차분몫의 극한 (f(a+ch)-f(a))/(dh)",
    rf"{_FN}(?P<f>{_E}) \((?P<p>[a-z])는 상수\)에 대하여 h가 0에 한없이 가까워질 때 "
    rf"\(f\((?P<a>{_NUM}) \+ (?P<c>\d*)h\) - f\((?P=a)\)\) / (?:(?P<d>\d*)h|\((?P<d2>\d*)h\))의 "
    rf"극한값이 (?P<v>{_NUM})이다\. 상수 (?P=p)의 값을 구하시오\.",
)
def _difference_quotient_parameter(m: re.Match[str]) -> sympy.Expr:
    param = sympy.Symbol(m["p"])
    f = _read_expr(m["f"], frozenset({_X, param}))
    c, d = int(m["c"] or 1), int((m["d"] if m["d"] is not None else m["d2"]) or 1)
    value = sympy.diff(f, _X).subs(_X, _rat(m["a"])) * sympy.Rational(c, d)
    return _solve_params([value - _rat(m["v"])], [param])[param]


@_rule(
    "difference_quotient_limit",
    "차분몫의 극한 (f(a+ch)-f(a))/(dh)",
    rf"{_FN}(?P<f>{_E}) \((?P<p>[a-z])는 상수\)에서 x의 값이 (?P<lo>{_NUM})에서 (?P<hi>{_NUM})까지 변할 때의 "
    rf"평균변화율이 x = (?P<c>{_NUM})에서의 미분계수와 같다\. 상수 (?P=p)의 값을 구하시오\.",
)
def _average_rate_parameter(m: re.Match[str]) -> sympy.Expr:
    param = sympy.Symbol(m["p"])
    f = _read_expr(m["f"], frozenset({_X, param}))
    lo, hi = _rat(m["lo"]), _rat(m["hi"])
    rate = (f.subs(_X, hi) - f.subs(_X, lo)) / (hi - lo)
    return _solve_params([rate - sympy.diff(f, _X).subs(_X, _rat(m["c"]))], [param])[param]


@_rule(
    "difference_quotient_limit",
    "차분몫의 극한 (f(a+ch)-f(a))/(dh)",
    rf"{_FN}(?P<f>{_E}) ?에 대하여 x가 (?P<a>{_NUM})에 한없이 가까워질 때 \(f\(x\) - f\((?P=a)\)\) / "
    r"\(x [+-] \d+\)의 극한값을 구하시오\.",
)
def _limit_x_to_a(m: re.Match[str]) -> sympy.Expr:
    a = _rat(m["a"])
    denominator = re.search(r"/ \(x ([+-]) (\d+)\)", m.string)
    assert denominator is not None
    shift = int(denominator[2]) * (1 if denominator[1] == "+" else -1)
    if a + shift != 0:  # x - a 의 꼴이어야 미분계수의 정의다(분모 x + 1 은 a = -1 일 때 x - a)
        raise _Undecided("DENOMINATOR_NOT_X_MINUS_A")
    return _derivative_at(_read_expr(m["f"]), a)


@_rule(
    "difference_quotient_limit",
    "차분몫의 극한 (f(a+ch)-f(a))/(dh)",
    rf"{_FN}(?P<f>{_E}) ?에 대하여 h가 0에 한없이 가까워질 때 \(f\((?P<a>{_NUM}) \+ h\) - "
    rf"f\((?P=a) - h\)\) / (?:(?P<d>\d*)h|\((?P<d2>\d*)h\))의 극한값을 구하시오\.",
)
def _symmetric_difference_limit(m: re.Match[str]) -> sympy.Expr:
    d = int((m["d"] if m["d"] is not None else m["d2"]) or 1)
    return _derivative_at(_read_expr(m["f"]), _rat(m["a"])) * sympy.Rational(2, d)


@_rule(
    "instantaneous_rate",
    "x = a 에서의 순간변화율",
    rf"함수 y = (?P<f>{_E})에서 x = (?P<a>{_NUM})일 때의 순간변화율을 구하시오\.",
)
def _instantaneous_rate(m: re.Match[str]) -> sympy.Expr:
    return _derivative_at(_read_expr(m["f"]), _rat(m["a"]))


@_rule(
    "derivative_at_point",
    "x = a 에서의 미분계수 f'(a)",
    rf"함수 g\(t\) = (?P<f>{_E}) ?에 대하여 g'\((?P<a>{_NUM})\)의 값(?:을 구하시오|은)[.?]",
)
def _derivative_at_t(m: re.Match[str]) -> sympy.Expr:
    return _derivative_at(_read_expr(m["f"], frozenset({_T})).subs(_T, _X), _rat(m["a"]))


@_rule(
    "derivative_constant_term",
    "도함수 f'(x)의 상수항",
    rf"함수 g\(t\) = (?P<f>{_E})(?:을|를) t에 대하여 미분한 도함수 g'\(t\)의 상수항을 구하시오\.",
)
def _derivative_constant_term_t(m: re.Match[str]) -> sympy.Expr:
    return _derivative_at(_read_expr(m["f"], frozenset({_T})).subs(_T, _X), sympy.Integer(0))


@_rule(
    "derivative_constant_term",
    "도함수 f'(x)의 상수항",
    rf"{_HEAD}의 도함수 f'\(x\)의 상수항(?:을 구하시오\.|으로 옳은 것은\?)",
)
def _derivative_constant_term_mc(m: re.Match[str]) -> sympy.Expr:
    return _derivative_at(_read_expr(m["f"]), sympy.Integer(0))


# 도함수의 모든 계수의 합 = f'(1) -----------------------------------------------------------
@_rule(
    "derivative_coefficient_sum",
    "도함수의 모든 계수의 합",
    rf"{_HEAD}의 도함수 f'\(x\)의 모든 계수의 합(?:을 구하시오\.|으로 옳은 것은\?)",
)
@_rule(
    "derivative_coefficient_sum",
    "도함수의 모든 계수의 합",
    rf"y = (?P<f>{_E})일 때, dy/dx의 모든 계수의 합을 구하시오\.",
)
@_rule(
    "derivative_coefficient_sum",
    "도함수의 모든 계수의 합",
    rf"y = (?P<f>{_E})의 도함수의 모든 계수의 합(?:을 구하시오\.|으로 옳은 것은\?)",
)
def _coefficient_sum(m: re.Match[str]) -> sympy.Expr:
    return _derivative_at(_read_expr(m["f"]), sympy.Integer(1))  # 다항식의 계수 합 = 1 에서의 값


@_rule(
    "derivative_coefficient_sum",
    "도함수의 모든 계수의 합",
    rf"두 함수 f\(x\) = (?P<f>{_E}), g\(x\) = (?P<g>{_E})에 대하여 함수 y = f\(x\) \+ g\(x\)의 도함수의 "
    r"모든 계수의 합을 구하시오\.",
)
def _coefficient_sum_of_sum(m: re.Match[str]) -> sympy.Expr:
    return _derivative_at(_read_expr(m["f"]) + _read_expr(m["g"]), sympy.Integer(1))


# 합성 함수 h = αf ± βg 의 미분계수, g = f + c 의 차 --------------------------------------------
@_rule(
    "linear_combination_derivative",
    "αf ± βg 의 x = a 에서의 미분계수",
    rf"두 함수 f\(x\) = (?P<f>{_E}), g\(x\) = (?P<g>{_E})에 대하여 함수 h\(x\) = (?P<al>\d*)f\(x\) "
    rf"(?P<op>[+-]) (?P<be>\d*)g\(x\)의 x = (?P<a>{_NUM})에서의 미분계수를 구하시오\.",
)
def _linear_combination(m: re.Match[str]) -> sympy.Expr:
    alpha, beta = int(m["al"] or 1), int(m["be"] or 1)
    sign = 1 if m["op"] == "+" else -1
    h = alpha * _read_expr(m["f"]) + sign * beta * _read_expr(m["g"])
    return _derivative_at(h, _rat(m["a"]))


@_rule(
    "linear_combination_derivative",
    "αf ± βg 의 x = a 에서의 미분계수",
    rf"두 함수 f\(x\), g\(x\)에 대하여 f'\(1\)의 값이 (?P<fa>{_NUM}), g'\(1\)의 값이 (?P<ga>{_NUM})일 때, "
    r"함수 h\(x\) = (?P<al>\d*)f\(x\) (?P<op>[+-]) (?P<be>\d*)g\(x\)의 x = 1에서의 미분계수를 구하시오\.",
)
def _abstract_linear_combination(m: re.Match[str]) -> sympy.Expr:
    alpha, beta = int(m["al"] or 1), int(m["be"] or 1)
    sign = 1 if m["op"] == "+" else -1
    return alpha * _rat(m["fa"]) + sign * beta * _rat(m["ga"])


@_rule(
    "shifted_function_difference",
    "g = f + c 일 때 g'(a) - f'(a)",
    rf"{_HEAD}에 대하여 g\(x\) = f\(x\) (?P<op>[+-]) (?P<c>\d+)(?:이)?라 할 때, g'\((?P<a>{_NUM})\) - "
    r"f'\((?P=a)\)의 값을 구하시오\.",
)
def _shifted_difference(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    shift = int(m["c"]) * (1 if m["op"] == "+" else -1)
    a = _rat(m["a"])
    return _derivative_at(f + shift, a) - _derivative_at(f, a)


# f'(a) = c 를 만족하는 a (양수·0 이 아닌 수 등 조건) ------------------------------------------------
_POS_FILTERS: Final = {"양수 ": lambda v: float(v) > 0, "0이 아닌 실수 ": lambda v: float(v) != 0}


def _filtered_unique(roots: list[sympy.Expr], word: str | None) -> sympy.Expr:
    kept = [r for r in roots if _POS_FILTERS[word](r)] if word else roots
    return _single(kept, "ROOTS_AFTER_FILTER")


_A_FILTER: Final = r"(?P<flt>양수 |0이 아닌 실수 )?"


@_rule(
    "derivative_equation_root",
    "f'(a) 가 주어진 값이 되는 a",
    rf"{_HEAD}에 대하여 f'\(a\) = (?P<k>{_NUM})(?:을|를) 만족시키는 {_A_FILTER}a의 값(?:을 구하시오\.|은\?)",
)
@_rule(
    "derivative_equation_root",
    "f'(a) 가 주어진 값이 되는 a",
    rf"{_HEAD}에 대하여 f'\(a\)의 값이 (?P<k>{_NUM})이 되도록 하는 {_A_FILTER}a의 값을 구하시오\.",
)
@_rule(
    "derivative_equation_root",
    "f'(a) 가 주어진 값이 되는 a",
    rf"{_HEAD}의 x = a에서의 미분계수가 (?P<k>{_NUM})일 때, {_A_FILTER}a의 값을 구하시오\.",
)
def _derivative_equals_value(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    equation = sympy.diff(f, _X).subs(_X, _A) - _rat(m["k"])
    return _filtered_unique(_real_roots(equation, _A), m["flt"])


@_rule(
    "derivative_equation_root",
    "f'(a) 가 주어진 값이 되는 a",
    rf"{_HEAD}에 대하여 f'\(a\) = f\(a\)를 만족시키는 {_A_FILTER}a의 값을 구하시오\.",
)
def _derivative_equals_function(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    return _filtered_unique(_real_roots((sympy.diff(f, _X) - f).subs(_X, _A), _A), m["flt"])


@_rule(
    "derivative_equation_root",
    "f'(a) 가 주어진 값이 되는 a",
    rf"{_HEAD}에 대하여 f'\(a\)의 값이 f'\((?P<b>{_NUM})\)의 값보다 (?P<d>\d+)만큼 클 때, "
    r"(?P<flt>양수 )?a의 값을 구하시오\.",
)
def _derivative_exceeds(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    base = _derivative_at(f, _rat(m["b"])) + int(m["d"])
    roots = _real_roots(sympy.diff(f, _X).subs(_X, _A) - base, _A)
    return _filtered_unique(roots, m["flt"])


@_rule(
    "derivative_equation_root",
    "f'(a) 가 주어진 값이 되는 a",
    rf"{_HEAD}에 대하여 방정식 f'\(x\) = (?P<rhs>{_E})의 0이 아닌 실근을 구하시오\.",
)
def _derivative_equation_nonzero_root(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    roots = _real_roots(sympy.diff(f, _X) - _read_expr(m["rhs"]))
    return _single([r for r in roots if float(r) != 0], "ROOTS_AFTER_FILTER")


# 매개변수를 f'(·) 조건으로 정하는 틀 -----------------------------------------------------------
_COND: Final = rf"f'\({_NUM}\)의 값이 {_NUM}"


@_rule(
    "derivative_parameter",
    "미분계수 조건으로 정하는 매개변수",
    rf"{_FN}(?P<f>{_E})(?: \([a-z](?:, [a-z])?는 상수\))? ?에 대하여 (?P<conds>{_COND}(?:이고 {_COND})?)일 때, "
    r"(?:상수 )?(?P<ask>[a-z])의 값을 구하시오\.",
)
def _derivative_parameter(m: re.Match[str]) -> sympy.Expr:
    f = _read_with_params(m["f"])
    params = _free_params(f)
    equations = [
        sympy.diff(f, _X).subs(_X, _rat(point)) - _rat(value)
        for point, value in re.findall(rf"f'\(({_NUM})\)의 값이 ({_NUM})", m["conds"])
    ]
    ask = sympy.Symbol(m["ask"])
    if ask not in params or len(equations) != len(params):
        raise _NotCovered("PARAMETER_CONDITION_COUNT")
    return _solve_params(equations, params)[ask]


@_rule(
    "derivative_parameter",
    "미분계수 조건으로 정하는 매개변수",
    rf"{_FN}(?P<f>{_E}) \((?P<p>[a-z]), (?P<q>[a-z])는 상수\)에 대하여 방정식 f'\(x\) = 0의 두 실근이 "
    rf"(?P<r1>{_NUM}), (?P<r2>{_NUM})일 때, 상수 (?P<ask>[a-z])의 값을 구하시오\.",
)
def _derivative_roots_parameter(m: re.Match[str]) -> sympy.Expr:
    f = _read_with_params(m["f"])
    params = _free_params(f)
    equations = [sympy.diff(f, _X).subs(_X, _rat(m["r1"])), sympy.diff(f, _X).subs(_X, _rat(m["r2"]))]
    if len(params) != 2:
        raise _NotCovered("PARAMETER_COUNT")
    return _solve_params(equations, params)[sympy.Symbol(m["ask"])]


@_rule(
    "derivative_parameter",
    "미분계수 조건으로 정하는 매개변수",
    rf"{_FN}(?P<f>{_E})의 도함수가 f'\(x\) = (?P<g>{_E})일 때, 상수 (?P<ask>[a-z])의 값을 구하시오\.",
)
def _derivative_identity_parameter(m: re.Match[str]) -> sympy.Expr:
    derivative = sympy.diff(_read_expr(m["f"]), _X)
    given = _read_with_params(m["g"])
    params = _free_params(given)
    if len(params) != 1:
        raise _NotCovered("PARAMETER_COUNT")
    difference = sympy.Poly(sympy.expand(derivative - given), _X)
    return _solve_params(list(difference.coeffs()), params)[sympy.Symbol(m["ask"])]


# x^n 에서 지수 n 을 정하는 틀 ---------------------------------------------------------------------
_N: Final = sympy.Symbol("n")
_NATURAL_LIMIT: Final = 80


def _natural_domain(word: str) -> range:
    return range(2 if word.startswith("2 이상의") else 1, _NATURAL_LIMIT)


def _exponent_candidates(domain: range, holds: Callable[[int], bool], what: str) -> int:
    matches = [n for n in domain if holds(n)]
    if len(matches) != 1:
        raise _Undecided(f"{what}_{len(matches)}")
    return matches[0]


_XN: Final = r"함수 f\(x\) = x\^n \(n은 (?P<dom>2 이상의 |)자연수\)"


def _pow_d(n: int, a: str) -> sympy.Expr:
    return sympy.Integer(n) * _rat(a) ** (n - 1)


@_rule(
    "power_exponent_unknown",
    "x^n 에서 지수 n 을 정하는 틀",
    rf"{_XN}에 대하여 f'\((?P<a>{_NUM})\)의 값이 (?P<v>{_NUM})일 때, f'\((?P<b>{_NUM})\)의 값을 구하시오\.",
)
def _power_exponent_then_derivative(m: re.Match[str]) -> sympy.Expr:
    n = _exponent_candidates(
        _natural_domain(m["dom"]), lambda k: _pow_d(k, m["a"]) == _rat(m["v"]), "EXPONENTS"
    )
    return _pow_d(n, m["b"])


@_rule(
    "power_exponent_unknown",
    "x^n 에서 지수 n 을 정하는 틀",
    rf"{_XN}에 대하여 f'\((?P<a>{_NUM})\)의 값이 (?P<v>{_NUM})일 때, n의 값을 구하시오\.",
)
def _power_exponent_from_derivative(m: re.Match[str]) -> sympy.Expr:
    return sympy.Integer(
        _exponent_candidates(
            _natural_domain(m["dom"]), lambda k: _pow_d(k, m["a"]) == _rat(m["v"]), "EXPONENTS"
        )
    )


@_rule(
    "power_exponent_unknown",
    "x^n 에서 지수 n 을 정하는 틀",
    rf"{_XN}에 대하여 f'\((?P<a>{_NUM})\)의 값이 f\((?P=a)\)의 값의 (?P<r>\d+)배일 때, n의 값을 구하시오\.",
)
def _power_exponent_from_ratio(m: re.Match[str]) -> sympy.Expr:
    a = _rat(m["a"])
    if a == 0:
        raise _Undecided("ZERO_POINT")
    return sympy.Integer(
        _exponent_candidates(
            _natural_domain(m["dom"]),
            lambda k: _pow_d(k, m["a"]) == int(m["r"]) * a**k,
            "EXPONENTS",
        )
    )


@_rule(
    "power_exponent_unknown",
    "x^n 에서 지수 n 을 정하는 틀",
    rf"{_XN}의 도함수가 f'\(x\) = kx\^(?P<m>\d+) \(k는 상수\)일 때, k의 값을 구하시오\.",
)
def _power_exponent_from_form(m: re.Match[str]) -> sympy.Expr:
    n = int(m["m"]) + 1
    if n not in _natural_domain(m["dom"]):
        raise _Undecided("EXPONENT_OUT_OF_DOMAIN")
    return sympy.Integer(n)


# ──────────────────────────────────────────────────────────────────────────
# 부등식을 보이려 할 때의 최솟값 — 정의역별 존재 판정
# ──────────────────────────────────────────────────────────────────────────
def _minimum_value(g: sympy.Expr, domain: str, var: sympy.Symbol = _X) -> sympy.Expr:
    """다항식 g 의 정의역(`R` · `>=0` · `>0`) 위 최솟값. 최솟값이 존재한다고 확정될 때만 값을 낸다.

    보류 조건: 아래로 한없이 내려간다(최고차 계수 부호·차수로 판정) · 하한이 열린 경계에서만 닿아 값이
    실제로 달성되지 않는다(x > 0 에서 g(0) 이 내부 후보보다 작은 경우).
    """
    poly = sympy.Poly(g, var)
    if poly.degree() < 1:
        raise _Undecided("CONSTANT_EXPRESSION")
    leading, degree = poly.LC(), poly.degree()
    unbounded_left = domain == "R" and (degree % 2 == 1 or leading < 0)
    unbounded_right = leading < 0
    if unbounded_left or unbounded_right:
        raise _Undecided("UNBOUNDED_BELOW")
    critical = [r for r in _real_roots(sympy.diff(g, var), var)] if degree > 1 else []
    inside = [r for r in critical if domain == "R" or float(r) > 0]
    values = [sympy.simplify(g.subs(var, r)) for r in inside]
    if domain != "R":
        boundary = sympy.simplify(g.subs(var, 0))
        if domain == ">=0":
            values.append(boundary)
        elif not values or float(boundary) < min(float(v) for v in values) - 1e-12:
            raise _Undecided("INFIMUM_NOT_ATTAINED")
    if not values:
        raise _Undecided("NO_CANDIDATE")
    return min(values, key=float)


def _domain_of(text: str) -> str:
    return ">=0" if "x ≥ 0" in text else ">0" if "x > 0" in text else "R"


_MIN_TITLE: Final = "부등식을 보이려 할 때의 최솟값"
_IMPLIES: Final = r"을 보이려 한다\."


@_rule(
    "inequality_minimum",
    _MIN_TITLE,
    rf"모든 실수 x에 대하여 부등식 (?P<l>{_E}) > (?P<r>{_E})(?:이|가) 성립함을 보이려 한다\. "
    r"(?:(?P<left>좌변)|두 변의 차 (?P<g>.+?))의 최솟값을 구하시오\.",
)
def _min_all_reals_inequality(m: re.Match[str]) -> sympy.Expr:
    left, right = _read_expr(m["l"]), _read_expr(m["r"])
    if m["left"] and sympy.simplify(right) != 0:
        raise _NotCovered("LEFT_SIDE_NOT_AGAINST_ZERO")
    target = left - right if m["g"] is None else _read_expr(m["g"])
    if sympy.simplify(target - (left - right)) != 0:
        raise _Undecided("STATED_DIFFERENCE_MISMATCH")
    return _minimum_value(target, "R")


@_rule(
    "inequality_minimum",
    _MIN_TITLE,
    rf"x (?P<d>[≥>]) 0일 때 부등식 (?P<l>{_E}) > (?P<r>{_E})(?:이|가) 성립함을 보이려 한다\. x [≥>] 0에서 "
    r"두 변의 차 (?P<g>.+?)의 최솟값을 구하시오\.",
)
def _min_halfline_inequality(m: re.Match[str]) -> sympy.Expr:
    left, right = _read_expr(m["l"]), _read_expr(m["r"])
    target = _read_expr(m["g"])
    if sympy.simplify(target - (left - right)) != 0:
        raise _Undecided("STATED_DIFFERENCE_MISMATCH")
    return _minimum_value(target, ">=0" if m["d"] == "≥" else ">0")


@_rule(
    "inequality_minimum",
    _MIN_TITLE,
    rf"모든 실수 x에 대하여 (?P<a>{_E})의 값은 (?P<b>{_E})의 값보다 크다\. 두 식의 값의 차 (?P<g>.+?)의 "
    r"최솟값을 구하시오\.",
)
def _min_two_expressions(m: re.Match[str]) -> sympy.Expr:
    target = _read_expr(m["g"])
    if sympy.simplify(target - (_read_expr(m["a"]) - _read_expr(m["b"]))) != 0:
        raise _Undecided("STATED_DIFFERENCE_MISMATCH")
    return _minimum_value(target, "R")


@_rule(
    "inequality_minimum",
    _MIN_TITLE,
    rf"x > 0에서 곡선 y = (?P<a>{_E})(?:은|는) (?:직선|곡선) y = (?P<b>{_E})보다 위쪽에 있다\. x > 0에서 "
    r"(?:곡선과 직선의|두 곡선의) y좌표의 차 (?P<g>.+?)의 최솟값을 구하시오\.",
)
def _min_curve_gap(m: re.Match[str]) -> sympy.Expr:
    target = _read_expr(m["g"])
    if sympy.simplify(target - (_read_expr(m["a"]) - _read_expr(m["b"]))) != 0:
        raise _Undecided("STATED_DIFFERENCE_MISMATCH")
    return _minimum_value(target, ">0")


@_rule(
    "inequality_minimum",
    _MIN_TITLE,
    rf"{_FN}(?P<f>{_E}) ?에 대하여 x ≥ 0에서 방정식 f\(x\) = 0이 실근을 갖지 않음{_IMPLIES} "
    r"x ≥ 0에서 f\(x\)의 최솟값을 구하시오\.",
)
@_rule(
    "inequality_minimum",
    _MIN_TITLE,
    rf"{_FN}(?P<f>{_E}) ?에 대하여 x ≥ 0에서 f\(x\) > 0임{_IMPLIES} x ≥ 0에서 f\(x\)의 최솟값을 구하시오\.",
)
def _min_function_halfline(m: re.Match[str]) -> sympy.Expr:
    return _minimum_value(_read_expr(m["f"]), ">=0")


@_rule(
    "inequality_minimum",
    _MIN_TITLE,
    rf"두 함수 f\(x\) = (?P<f>{_E}), g\(x\) = (?P<g>{_E})에 대하여 x ≥ 0에서 f\(x\) > g\(x\)임{_IMPLIES} "
    r"x ≥ 0에서 f\(x\) - g\(x\)의 최솟값을 구하시오\.",
)
def _min_function_gap(m: re.Match[str]) -> sympy.Expr:
    return _minimum_value(_read_expr(m["f"]) - _read_expr(m["g"]), ">=0")


@_rule(
    "inequality_minimum",
    _MIN_TITLE,
    rf"사차함수 y = (?P<f>{_E})의 그래프가 x축과 만나지 않음{_IMPLIES} 이 함수의 최솟값을 구하시오\.",
)
@_rule(
    "inequality_minimum",
    _MIN_TITLE,
    rf"곡선 y = (?P<f>{_E})(?:이|가) x축보다 위쪽에 있음{_IMPLIES} 이 곡선 위의 점의 y좌표의 최솟값을 구하시오\.",
)
@_rule(
    "inequality_minimum",
    _MIN_TITLE,
    rf"{_FN}(?P<f>{_E}) ?에 대하여 모든 실수 x에서 f\(x\) > 0임{_IMPLIES} f\(x\)의 최솟값을 구하시오\.",
)
def _min_function_all_reals(m: re.Match[str]) -> sympy.Expr:
    return _minimum_value(_read_expr(m["f"]), "R")


@_rule(
    "inequality_minimum",
    _MIN_TITLE,
    rf"모든 실수 x에 대하여 곡선 y = (?P<a>{_E})(?:은|는) 직선 y = (?P<b>{_E})보다 위쪽에 있음{_IMPLIES} "
    r"두 그래프의 y좌표의 차의 최솟값을 구하시오\.",
)
def _min_graph_gap(m: re.Match[str]) -> sympy.Expr:
    return _minimum_value(_read_expr(m["a"]) - _read_expr(m["b"]), "R")


@_rule(
    "inequality_minimum",
    _MIN_TITLE,
    rf"사차함수 f\(x\) = (?P<f>{_E})에 대하여 방정식 f\(x\) = 0이 실근을 갖지 않음{_IMPLIES} "
    r"f\(x\)의 두 극솟값 중 작은 값을 구하시오\.",
)
def _min_of_two_minima(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    minima = _exactly_two(_critical_points(f)[1])
    return min((sympy.simplify(f.subs(_X, r)) for r in minima), key=float)


# ──────────────────────────────────────────────────────────────────────────
# 접선 — 직선과의 관계 · 외부 점 · 접하는 두 곡선
# ──────────────────────────────────────────────────────────────────────────
_Y = sympy.Symbol("y")


def _line_slope(text: str) -> sympy.Expr:
    """`y = -52x - 158` 또는 `x + 8y = 9` 꼴 직선의 기울기. y 가 없으면(수직선) 보류."""
    sides = text.split(" = ")
    if len(sides) != 2:
        raise _NotCovered("LINE_SHAPE")
    both = frozenset({_X, _Y})
    equation = _read_expr(sides[0], both) - _read_expr(sides[1], both)
    solved = sympy.solve(equation, _Y)
    if len(solved) != 1:
        raise _Undecided("VERTICAL_OR_DEGENERATE_LINE")
    return sympy.diff(solved[0], _X)


@_rule(
    "tangent_relation_to_unknown_point",
    "접선이 직선과 평행·수직이거나 한 점을 지날 때의 접점 a",
    rf"{_FN}(?P<f>{_E}) ?에 대하여 곡선 y = f\(x\) 위의 점 \(a, f\(a\)\)에서의 접선이 "
    rf"(?:직선 (?P<line>.+?)에 (?P<rel>평행할|수직일) 때|(?:점 \((?P<px>{_NUM}), (?P<py>{_NUM})\)(?:를|을)|(?P<origin>원점을)) 지날 때), "
    r"양수 a의 값을 구하시오\.",
)
def _tangent_relation(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    slope_at_a = sympy.diff(f, _X).subs(_X, _A)
    if m["line"] is not None:
        target = _line_slope(m["line"])
        if m["rel"] == "수직일":
            if target == 0:
                raise _Undecided("PERPENDICULAR_TO_HORIZONTAL")
            target = -1 / target
        equation = slope_at_a - target
    else:
        px, py = (0, 0) if m["origin"] else (_rat(m["px"]), _rat(m["py"]))
        equation = f.subs(_X, _A) + slope_at_a * (px - _A) - py
    return _positive_unique(_real_roots(equation, _A), "POSITIVE_ROOTS")


@_rule(
    "tangent_parameter",
    "접선 조건으로 정하는 곡선의 매개변수",
    rf"곡선 y = (?P<f>{_E})(?: \((?P<n>[a-z])는 상수\))? 위의 x좌표가 (?P<r>{_NUM})인 점에서의 접선의 "
    rf"(?P<w>기울기|y절편)(?:이|가) (?P<k>{_NUM})일 때, (?:상수 )?(?P<p>[a-z])의 값을 구하시오\.",
)
def _tangent_parameter(m: re.Match[str]) -> sympy.Expr:
    f = _read_with_params(m["f"])
    param = sympy.Symbol(m["p"])
    if param not in f.free_symbols or len(_free_params(f)) != 1:
        raise _NotCovered("PARAMETER_COUNT")
    r = _rat(m["r"])
    slope = sympy.diff(f, _X).subs(_X, r)
    intercept = f.subs(_X, r) - slope * r
    value = slope if m["w"] == "기울기" else intercept
    return _solve_params([value - _rat(m["k"])], [param])[param]


@_rule(
    "tangent_parallel_other_point",
    "접선과 평행한 접선을 갖는 또 다른 점",
    rf"곡선 y = (?P<f>{_E}) 위의 x좌표가 (?P<r>{_NUM})인 점에서의 접선과 평행한 접선을 갖는 또 다른 점의 "
    r"x좌표를 b라 할 때, b의 값을 구하시오\.",
)
def _tangent_other_point(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    r = _rat(m["r"])
    roots = [v for v in _real_roots(sympy.diff(f, _X) - sympy.diff(f, _X).subs(_X, r)) if float(v) != float(r)]
    return _single(roots, "OTHER_POINTS")


@_rule(
    "tangent_line_parameter",
    "직선이 곡선에 접하도록 하는 상수",
    rf"직선 y = (?P<m>{_NUM})x \+ k(?:가|이) 곡선 y = (?P<f>{_E}) 위의 x좌표가 양수인 점에서 이 곡선에 접할 때, "
    r"상수 k의 값을 구하시오\.",
)
def _tangent_line_constant(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    slope = _rat(m["m"])
    point = _positive_unique(_real_roots(sympy.diff(f, _X) - slope), "TOUCH_POINTS")
    return sympy.simplify(f.subs(_X, point) - slope * point)


@_rule(
    "tangent_second_intersection",
    "접선이 곡선과 다시 만나는 점",
    rf"곡선 y = (?P<f>{_E}) 위의 점 \((?P<a>{_NUM}), (?P<b>{_NUM})\)에서의 접선이 이 곡선과 만나는 점 중 "
    r"접점이 아닌 점의 x좌표를 구하시오\.",
)
def _tangent_second_intersection(m: re.Match[str]) -> sympy.Expr:
    f, a = _read_expr(m["f"]), _rat(m["a"])
    _require_on_curve(f, a, m["b"])
    slope, intercept = _tangent(f, a)
    roots = [r for r in _real_roots(f - (slope * _X + intercept)) if float(r) != float(a)]
    return _single(roots, "SECOND_INTERSECTIONS")


@_rule(
    "tangent_from_outside_point",
    "곡선 밖의 점에서 그은 접선의 기울기",
    rf"점 \((?P<px>{_NUM}), (?P<py>{_NUM})\)에서 곡선 y = (?P<f>{_E})에 그은 접선은 하나뿐이다\. "
    r"이 접선의 기울기를 구하시오\.",
)
def _tangent_from_outside(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    t = sympy.Symbol("t")
    equation = f.subs(_X, t) + sympy.diff(f, _X).subs(_X, t) * (_rat(m["px"]) - t) - _rat(m["py"])
    touch = _single(_real_roots(equation, t), "TOUCH_POINTS")
    return sympy.simplify(sympy.diff(f, _X).subs(_X, touch))


@_rule(
    "tangent_two_curves_parameter",
    "두 곡선이 한 점에서 접할 때의 상수",
    rf"곡선 y = (?P<f>{_E})(?:가|이) 곡선 y = (?P<g>{_E})와 x = (?P<r>{_NUM})인 점에서 접할 때, 상수 (?P<ask>[a-z])의 값을 "
    r"구하시오\. \(단, [a-z], [a-z]는 상수이다\.\)",
)
def _tangent_two_curves(m: re.Match[str]) -> sympy.Expr:
    f, g = _read_with_params(m["f"]), _read_expr(m["g"])
    params = _free_params(f)
    r = _rat(m["r"])
    equations = [(f - g).subs(_X, r), sympy.diff(f - g, _X).subs(_X, r)]
    if len(params) != 2:
        raise _NotCovered("PARAMETER_COUNT")
    return _solve_params(equations, params)[sympy.Symbol(m["ask"])]


# ──────────────────────────────────────────────────────────────────────────
# 열차 운동(직선 레일) · 매개변수 형 운동
# ──────────────────────────────────────────────────────────────────────────
_TRAIN: Final = (
    rf"직선 레일 위를 움직이는 장난감 열차가 출발한 지 t초 후, 출발 지점에서 잰 위치는 s\(t\) = (?P<f>{_E}) \(cm\)이다"
    r"(?: \((?P<p>[a-z])는 상수\))?\. (?P<tail>.+)"
)


def _train_value(kind: str, order: int, pos: sympy.Expr, when: sympy.Expr) -> sympy.Expr:
    return sympy.simplify(sympy.diff(pos, _T, order).subs(_T, when)) if kind else sympy.Integer(0)


@_rule("train_motion", "열차 운동(방향 전환·매개변수)", _TRAIN)
def _train_motion(m: re.Match[str]) -> sympy.Expr:
    tail = m["tail"]
    pos = _read_with_params(m["f"], _T)
    if m["p"] is None:
        pos = _read_expr(m["f"], frozenset({_T}))
        vel, acc = sympy.diff(pos, _T), sympy.diff(pos, _T, 2)
        changes = [t for t in _sign_changes_in(_poly(vel, _T), _T) if float(t) > 0]
        if re.fullmatch(r"열차가 운동 방향을 바꾸는 순간 출발 지점에서 잰 위치는 몇 cm인가\? \(단, t > 0\)", tail):
            return sympy.simplify(pos.subs(_T, _single(changes, "DIRECTION_CHANGES")))
        if re.fullmatch(r"열차가 운동 방향을 바꾸는 순간의 가속도는 몇 cm/초\^2인가\? \(단, t > 0\)", tail):
            return sympy.simplify(acc.subs(_T, _single(changes, "DIRECTION_CHANGES")))
        if re.fullmatch(r"열차가 운동 방향을 바꾸는 것은 출발한 지 몇 초 후인가\? \(단, t > 0\)", tail):
            return _single(changes, "DIRECTION_CHANGES")
        raise _NoMatch
    param = sympy.Symbol(m["p"])
    vel, acc = sympy.diff(pos, _T), sympy.diff(pos, _T, 2)
    if g := re.fullmatch(rf"열차가 출발한 지 (?P<a>\d+)초 후에 순간적으로 멈췄다고 할 때, {m['p']}의 값을 구하시오\.", tail):
        equation = vel.subs(_T, _rat(g["a"]))
    elif g := re.fullmatch(rf"열차의 가속도가 출발한 지 (?P<a>\d+)초 후에 0이 되었다고 할 때, {m['p']}의 값을 구하시오\.", tail):
        equation = acc.subs(_T, _rat(g["a"]))
    elif g := re.fullmatch(
        rf"열차의 (?P<q>속도|가속도)가 출발한 지 (?P<a>\d+)초 후에 (?P<v>{_NUM}) cm/초(?:\^2)?였다고 할 때, "
        rf"{m['p']}의 값을 구하시오\.",
        tail,
    ):
        equation = (vel if g["q"] == "속도" else acc).subs(_T, _rat(g["a"])) - _rat(g["v"])
    else:
        raise _NoMatch
    return _solve_params([equation], [param])[param]


@_rule(
    "motion_parameter",
    "운동 조건으로 정하는 매개변수",
    rf"수직선 위(?:의|를 움직이는) 점 P의 시각 t에서의 위치가 x = (?P<f>{_E})(?: \((?P<n>[a-z])는 상수\))?이다\. "
    rf"t = (?P<a>{_NUM})에서(?:의)? 점 P의 (?P<q>속도|가속도)가 (?P<c>{_NUM})일 때, "
    rf"(?:상수 (?P<p>[a-z])의 값을 구하시오|t = (?P<b>{_NUM})에서의 점 P의 (?P<q2>속도|가속도)를 구하시오)\.",
)
def _motion_parameter(m: re.Match[str]) -> sympy.Expr:
    pos = _read_with_params(m["f"], _T)
    params = _free_params(pos)
    if len(params) != 1:
        raise _NotCovered("PARAMETER_COUNT")
    vel, acc = sympy.diff(pos, _T), sympy.diff(pos, _T, 2)
    equation = (vel if m["q"] == "속도" else acc).subs(_T, _rat(m["a"])) - _rat(m["c"])
    solved = _solve_params([equation], params)
    if m["p"] is not None:
        return solved[params[0]]
    resolved = pos.subs(solved)
    final = sympy.diff(resolved, _T, 1 if m["q2"] == "속도" else 2)
    return sympy.simplify(final.subs(_T, _rat(m["b"])))


# ──────────────────────────────────────────────────────────────────────────
# 평균값 정리 변형 — 매개변수 · 미지의 끝점 · 구간 밖의 근 · 개수
# ──────────────────────────────────────────────────────────────────────────
def _slope_between(f: sympy.Expr, lo: sympy.Expr, hi: sympy.Expr) -> sympy.Expr:
    return (f.subs(_X, hi) - f.subs(_X, lo)) / (hi - lo)


@_rule(
    "mean_value_parameter",
    "평균값 정리의 c 값이 주어질 때 매개변수·끝점",
    rf"{_FN}(?P<f>{_E}) ?에 대하여 닫힌구간 \[(?P<lo>{_NUM}), (?P<hi>{_NUM})\]에서 평균값 정리를 만족시키는 c의 값이 "
    rf"(?P<cv>{_NUM})일 때, 상수 (?P<p>[a-z])의 값을 구하시오\.",
)
@_rule(
    "mean_value_parameter",
    "평균값 정리의 c 값이 주어질 때 매개변수·끝점",
    rf"{_FN}(?P<f>{_E}) ?에 대하여 곡선 y = f\(x\) 위의 두 점 \((?P<lo>{_NUM}), f\((?P=lo)\)\), "
    rf"\((?P<hi>{_NUM}), f\((?P=hi)\)\)을 잇는 직선과 평행한 접선의 접점의 x좌표가 (?P<cv>{_NUM})일 때, "
    r"상수 (?P<p>[a-z])의 값을 구하시오\.",
)
def _mvt_parameter(m: re.Match[str]) -> sympy.Expr:
    f = _read_with_params(m["f"])
    lo, hi, cv = _rat(m["lo"]), _rat(m["hi"]), _rat(m["cv"])
    if not lo < cv < hi:
        raise _Undecided("C_OUTSIDE_INTERVAL")
    param = sympy.Symbol(m["p"])
    return _solve_params([sympy.diff(f, _X).subs(_X, cv) - _slope_between(f, lo, hi)], [param])[param]


@_rule(
    "mean_value_parameter",
    "평균값 정리의 c 값이 주어질 때 매개변수·끝점",
    rf"{_FN}(?P<f>{_E}) ?에 대하여 (?:닫힌)?구간 \[(?P<lo>[^,\]]+), (?P<hi>[^,\]]+)\] \((?P<cond>[a-z] [<>] {_NUM})\)에서 "
    rf"평균값 정리를 만족시키는 c의 값이 (?P<cv>{_NUM})일 때, (?P<p>[a-z])의 값을 구하시오\.",
)
def _mvt_unknown_endpoint(m: re.Match[str]) -> sympy.Expr:
    f = _read_expr(m["f"])
    var = sympy.Symbol(m["p"])
    lo = var if m["lo"] == m["p"] else _rat(m["lo"])
    hi = var if m["hi"] == m["p"] else _rat(m["hi"])
    if (lo == var) == (hi == var):
        raise _NotCovered("ENDPOINT_SHAPE")
    cv = _rat(m["cv"])
    equation = sympy.together(sympy.diff(f, _X).subs(_X, cv) - _slope_between(f, lo, hi))
    numerator = sympy.numer(equation)
    cond_var, op, bound = m["cond"].split(" ")
    kept = [
        r
        for r in _real_roots(numerator, var)
        if (float(r) < float(bound)) == (op == "<") and float(r) != float(bound)
    ]
    root = _single(kept, "ENDPOINT_ROOTS")
    other = hi if lo == var else lo
    interval = sorted([float(root), float(other)])
    if not interval[0] < float(cv) < interval[1]:
        raise _Undecided("C_OUTSIDE_INTERVAL")
    return root


@_rule(
    "mean_value_parameter",
    "평균값 정리의 c 값이 주어질 때 매개변수·끝점",
    rf"{_FN}(?P<f>{_E})(?:이|가) 닫힌구간 \[(?P<lo>{_NUM}), (?P<hi>{_NUM})\]에서 롤의 정리의 가정을 만족시키도록 "
    r"상수 (?P<p>[a-z])의 값을 정할 때, 롤의 정리를 만족시키는 c의 값을 구하시오\.",
)
def _rolle_parameter(m: re.Match[str]) -> sympy.Expr:
    f = _read_with_params(m["f"])
    lo, hi = _bounds(m)
    param = sympy.Symbol(m["p"])
    solved = _solve_params([f.subs(_X, lo) - f.subs(_X, hi)], [param])
    return _single(_mvt_roots(f.subs(solved), lo, hi, _X), "MVT_POINTS")


_ROOTS_NOTE: Final = r"f'\(x\) = \(f\((?P<hi>{n})\) - f\((?P<lo>{n})\)\)/\((?P=hi) - (?P<den>.+?)\)"
_ROOTS_SLOPE: Final = _ROOTS_NOTE.format(n=_NUM)


def _roots_with_formula(m: re.Match[str], *, inside: bool) -> sympy.Expr:
    f = _read_expr(m["f"])
    lo, hi = _bounds(m, "ilo", "ihi")
    if (_rat(m["lo"]), _rat(m["hi"])) != (lo, hi) or m["den"] != _wrapped(m["lo"]):
        raise _Undecided("FORMULA_INTERVAL_MISMATCH")
    slope = _slope_between(f, lo, hi)
    roots = _real_roots(sympy.diff(f, _X) - slope)
    return _single([r for r in roots if _in_open(r, lo, hi) == inside], "MVT_POINTS")


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"{_FN}(?P<f>{_E}) ?에 대하여 {_ROOTS_SLOPE}을 만족시키는 실수 x는 두 개이다\. "
    rf"이 중 열린구간 \((?P<ilo>{_NUM}), (?P<ihi>{_NUM})\)에 속하는 것을 c라 할 때, c의 값을 구하시오\.",
)
def _mvt_inside_root(m: re.Match[str]) -> sympy.Expr:
    return _roots_with_formula(m, inside=True)


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"{_FN}(?P<f>{_E}) ?에 대하여 방정식 {_ROOTS_SLOPE}의 두 실근 중 "
    rf"열린구간 \((?P<ilo>{_NUM}), (?P<ihi>{_NUM})\)에 속하지 않는 근을 구하시오\.",
)
def _mvt_outside_root(m: re.Match[str]) -> sympy.Expr:
    return _roots_with_formula(m, inside=False)


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"닫힌구간 \[(?P<lo>{_NUM}), (?P<hi>{_NUM})\]에서 함수 f\(x\) = (?P<f>{_E})의 평균변화율과 x = c에서의 "
    r"미분계수가 같아지는 c \((?P=lo) < c < (?P=hi)\)의 값을 구하시오\.",
)
def _mvt_average_rate_phrase(m: re.Match[str]) -> sympy.Expr:
    lo, hi = _bounds(m)
    return _single(_mvt_roots(_read_expr(m["f"]), lo, hi, _X), "MVT_POINTS")


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"삼차함수 f\(x\) = (?P<f>{_E})에 대하여 f\((?P<hi>{_NUM})\) - f\((?P<lo>{_NUM})\) = "
    rf"f'\(c\)\((?P=hi) - (?P<den>.+?)\)을 만족시키는 c \((?P=lo) < c < (?P=hi)\)의 값을 구하시오\.",
)
def _mvt_product_form(m: re.Match[str]) -> sympy.Expr:
    lo, hi = _bounds(m)
    if m["den"] != _wrapped(m["lo"]):
        raise _Undecided("FORMULA_DENOMINATOR_MISMATCH")
    return _single(_mvt_roots(_read_expr(m["f"]), lo, hi, _X), "MVT_POINTS")


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"{_FN}(?P<f>{_E})에 대하여 f\((?P<lo>{_NUM})\)과 f\((?P<hi>{_NUM})\)의 값은 서로 다르다\. "
    r"구간 \[(?P=lo), (?P=hi)\]에서 평균값 정리를 만족시키는 c를 구하려 할 때, 올바른 방정식을 세워 구한 c의 값은\?",
)
def _mvt_correct_equation(m: re.Match[str]) -> sympy.Expr:
    lo, hi = _bounds(m)
    f = _read_expr(m["f"])
    if sympy.simplify(f.subs(_X, lo) - f.subs(_X, hi)) == 0:
        raise _Undecided("EQUAL_ENDPOINT_VALUES")
    return _single(_mvt_roots(f, lo, hi, _X), "MVT_POINTS")


@_rule(
    "mean_value_c",
    _MVT_TITLE,
    rf"수직선 위를 움직이는 점 P의 시각 t에서의 위치가 {_VELOCITY_MVT_FN}일 때, (?P<lo>{_NUM}) < t < (?P<hi>{_NUM})에서 "
    rf"점 P의 순간속도가 t = (?P=lo)부터 t = (?P=hi)까지의 평균속도와 같아지는 시각의 개수를 구하시오\.",
)
def _mvt_velocity_count(m: re.Match[str]) -> sympy.Expr:
    lo, hi = _bounds(m)
    return sympy.Integer(len(_mvt_roots(_read_expr(m["f"], frozenset({_T})), lo, hi, _T)))


# 두 점의 위치 차의 최솟값 -----------------------------------------------------------------------
@_rule(
    "inequality_minimum",
    _MIN_TITLE,
    rf"수직선 위를 움직이는 두 점 P, Q의 시각 t \(t ≥ 0\)에서의 위치가 각각 p\(t\) = (?P<p>{_E}), q\(t\) = (?P<q>{_E})이다\. "
    r"t ≥ 0에서 점 P는 항상 점 Q보다 오른쪽에 있음을 보이려 한다\. t ≥ 0에서 p\(t\) - q\(t\)의 최솟값을 구하시오\.",
)
def _min_position_gap(m: re.Match[str]) -> sympy.Expr:
    gap = _read_expr(m["p"], frozenset({_T})) - _read_expr(m["q"], frozenset({_T}))
    return _minimum_value(gap, ">=0", _T)


@_motion(
    rf"t = (?P<lo>{_NUM})에서 t = (?P<hi>{_NUM})까지의 평균속도와 순간속도가 같아지는 시각 t "
    r"\((?P=lo) < t < (?P=hi)\)의 값을 구하시오\.",
    "mean_value_c",
    _MVT_TITLE,
)
def _motion_average_equals_instant(m: re.Match[str]) -> sympy.Expr:
    lo, hi = _bounds(m)
    return _single(_mvt_roots(_read_expr(m["f"], frozenset({_T})), lo, hi, _T), "MVT_POINTS")


@_rule(
    "motion_time_when",
    "속도·가속도가 c 가 되는 시각",
    rf"수직선 위를 움직이는 두 점 P, Q의 시각 t에서의 위치가 각각 f\(t\) = (?P<f>{_E}), g\(t\) = (?P<g>{_E})이다\. "
    r"두 점의 속도가 같아지는 시각 t \(t > 0\)의 값을 구하시오\.",
)
def _two_points_equal_velocity(m: re.Match[str]) -> sympy.Expr:
    symbols = frozenset({_T})
    gap = sympy.diff(_read_expr(m["f"], symbols) - _read_expr(m["g"], symbols), _T)
    return _single([r for r in _real_roots(gap, _T) if float(r) > 0], "TIME_ROOTS")


# ──────────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────────
def rederive_question(question_text: str) -> Rederivation:
    """발문 → 재유도 결과. 인식기가 없으면 NOT_COVERED, 틀은 맞는데 값이 안 정해지면 UNDECIDED."""
    text = _normalize(question_text)
    for rule in _RULES:
        match = rule.pattern.fullmatch(text)
        if match is None:
            continue
        try:
            value = rule.compute(match)
        except _NoMatch:
            continue
        except _NotCovered as exc:
            return Rederivation(RederiveState.NOT_COVERED, rule.family, reason=exc.reason)
        except _Undecided as exc:
            return Rederivation(RederiveState.UNDECIDED, rule.family, reason=exc.reason)
        except Exception as exc:  # noqa: BLE001 — 한 문항의 계산 실패로 전수 측정을 잃지 않는다
            return Rederivation(
                RederiveState.UNDECIDED, rule.family, reason=f"COMPUTE_{type(exc).__name__}"
            )
        return Rederivation(RederiveState.DERIVED, rule.family, value=_clean(value))
    return Rederivation(RederiveState.NOT_COVERED, reason="NO_RECOGNIZER")
