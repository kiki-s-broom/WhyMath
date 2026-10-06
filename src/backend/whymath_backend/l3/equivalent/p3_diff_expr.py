"""Phase 3 미적분Ⅰ 미분 문항 생성기 공용 식 도구 — 다항식 표기·SymPy 변환(P3-03·결정론·LLM 0).

개념별 생성기(`p3_diff_*_skeleton_generator`)가 공유하는 *식 표현* 헬퍼만 담는다. 문항 조립·슬롯·
게이트 배선은 `p3_diff_skeleton_base`가 맡는다(이 모듈은 문항을 모른다).

설계 원칙
---------
· **정답의 단일 권위는 SymPy**다 — 도함수·미분계수는 항상 `sympy.diff`로 계산하고, 그 결과를
  다시 `Poly`로 풀어 사람이 읽는 표기로 되돌린다(손으로 짠 미분 공식을 정답 경로에 두지 않는다).
  생성기가 독립적으로 *다른 경로*(예: 거듭제곱 공식 n·x^(n-1))를 한 번 더 계산해 대조하는 것은
  각 생성기·테스트의 몫이다.
· 표기는 ASCII 전용이다(`x^4`·`*` 없음) — 신규 유니코드 글리프(²·³)는 위생·글리프 가드가 막는다
  (2026-08-07 conic_section_focus 사고 선례).
· 다항식은 `((지수, 계수), ...)` 지수 내림차순 정수 계수 튜플이다. 계수 0 항은 담지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import sympy

__all__ = [
    "Poly",
    "derivative_of",
    "eval_at",
    "poly_from_sympy",
    "poly_to_sympy",
    "poly_to_sympy_str",
    "product_to_sympy_str",
    "render_poly",
    "render_product",
    "sympy_str_of",
]

#: 다항식 — ((지수, 계수), ...) 지수 내림차순·계수 0 제외.
Poly = tuple[tuple[int, int], ...]

_X = sympy.Symbol("x")


def _symbol(var: str) -> sympy.Symbol:
    return _X if var == "x" else sympy.Symbol(var)


def _norm(terms: Iterable[tuple[int, int]]) -> Poly:
    """같은 지수 합산·계수 0 제거·지수 내림차순 정규화."""
    merged: dict[int, int] = {}
    for exp, coef in terms:
        merged[exp] = merged.get(exp, 0) + coef
    return tuple(sorted(((e, c) for e, c in merged.items() if c != 0), reverse=True))


def render_poly(poly: Poly, var: str = "x") -> str:
    """사람이 읽는 표기('3x^4 - 2x^2 + 5x - 7') — 계수 1 생략·지수 1/0 처리·선두 음수는 '-'.

    빈 다항식(영다항식)은 '0'이다.
    """
    if not poly:
        return "0"
    parts: list[str] = []
    for index, (exp, coef) in enumerate(_norm(poly)):
        magnitude = abs(coef)
        if exp == 0:
            body = str(magnitude)
        else:
            var_part = var if exp == 1 else f"{var}^{exp}"
            body = var_part if magnitude == 1 else f"{magnitude}{var_part}"
        if index == 0:
            parts.append(f"-{body}" if coef < 0 else body)
        else:
            parts.append(f"{'-' if coef < 0 else '+'} {body}")
    return " ".join(parts)


def poly_to_sympy_str(poly: Poly, var: str = "x") -> str:
    """Tier1 조건식용 표기('3*x**4 - 2*x**2 + 5*x - 7') — 연산자 `*`·`**` 명시."""
    if not poly:
        return "0"
    parts: list[str] = []
    for index, (exp, coef) in enumerate(_norm(poly)):
        magnitude = abs(coef)
        if exp == 0:
            body = str(magnitude)
        else:
            var_part = var if exp == 1 else f"{var}**{exp}"
            body = var_part if magnitude == 1 else f"{magnitude}*{var_part}"
        if index == 0:
            parts.append(f"-{body}" if coef < 0 else body)
        else:
            parts.append(f"{'-' if coef < 0 else '+'} {body}")
    return " ".join(parts)


def poly_to_sympy(poly: Poly, var: str = "x") -> sympy.Expr:
    """다항식 → SymPy 식."""
    symbol = _symbol(var)
    return sympy.Add(*(sympy.Integer(coef) * symbol**exp for exp, coef in poly))


def poly_from_sympy(expr: sympy.Expr, var: str = "x") -> Poly:
    """SymPy 다항식 → `Poly`. 정수 계수가 아니면 ValueError(정수 답 보장 위반을 넘기지 않는다)."""
    symbol = _symbol(var)
    terms: list[tuple[int, int]] = []
    for monom, coef in sympy.Poly(expr, symbol).terms():
        if not coef.is_integer:
            raise ValueError(f"정수 계수가 아닌 항: {coef}·지수 {monom}")
        terms.append((int(monom[0]), int(coef)))
    return _norm(terms)


def derivative_of(poly: Poly, var: str = "x") -> Poly:
    """`sympy.diff`로 구한 도함수(정답의 단일 권위)."""
    symbol = _symbol(var)
    return poly_from_sympy(sympy.diff(poly_to_sympy(poly, var), symbol), var)


def eval_at(poly: Poly, point: int, var: str = "x") -> int:
    """다항식의 값(정수) — SymPy 평가."""
    value = poly_to_sympy(poly, var).subs(_symbol(var), point)
    if not sympy.Integer(value).is_integer:  # pragma: no cover — 정수 계수·정수 점이면 항상 정수
        raise ValueError(f"정수 값이 아니다: {value}")
    return int(value)


def render_product(factors: Sequence[Poly], var: str = "x") -> str:
    """곱 표기('(x^2 + 1)(3x - 2)') — 인수마다 괄호."""
    return "".join(f"({render_poly(f, var)})" for f in factors)


def product_to_sympy_str(factors: Sequence[Poly], var: str = "x") -> str:
    """곱의 Tier1 표기('(x**2 + 1)*(3*x - 2)')."""
    return "*".join(f"({poly_to_sympy_str(f, var)})" for f in factors)


def sympy_str_of(poly: Poly, var: str = "x") -> str:
    """`answer_map` 값 표기 — `poly_to_sympy_str`의 별칭(의도 명시용)."""
    return poly_to_sympy_str(poly, var)
