"""Phase 3 미적분Ⅰ 미분 문항 생성기 공용 식 도구 — 다항식 표기·SymPy 변환(P3-03·결정론·LLM 0).

개념별 생성기(`p3_diff_*_skeleton_generator`)가 공유하는 *식 표현* 헬퍼만 담는다. 문항 조립·슬롯·
게이트 배선은 `p3_diff_skeleton_base`가 맡는다(이 모듈은 문항을 모른다).

설계 원칙
---------
· **정답의 단일 권위는 SymPy**다 — 도함수·미분계수는 항상 `sympy.diff`로 계산하고, 그 결과를
  다시 `Poly`로 풀어 사람이 읽는 표기로 되돌린다(손으로 짠 미분 공식을 정답 경로에 두지 않는다).
  생성기가 독립적으로 *다른 경로*(예: 거듭제곱 공식 n·x^(n-1))를 한 번 더 계산해 대조하는 것은
  각 생성기·테스트의 몫이다.
· 표기는 ASCII가 기본이다(`x^4`·`*` 없음) — 신규 유니코드 글리프(²·³)는 위생·글리프 가드가 막는다
  (2026-08-07 conic_section_focus 사고 선례). 예외는 승인 은행이 이미 쓰는 세 글리프
  '√'·'≤'·'≥'뿐이다(4차 감사 교정 — 표기 커버리지 베이스라인 등재 글리프라 신규 누락이 아니다).
· 다항식은 `((지수, 계수), ...)` 지수 내림차순 정수 계수 튜플이다. 계수 0 항은 담지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

import sympy

from whymath_backend.lang.josa import eul_reul, eun_neun, has_batchim_text, i_ga, wa_gwa

__all__ = [
    "ANCHOR_PREFIX",
    "Poly",
    "anchor_curve_function",
    "derivative_of",
    "eval_at",
    "poly_from_sympy",
    "poly_to_sympy",
    "poly_to_sympy_str",
    "product_to_sympy_str",
    "render_affine",
    "render_difference",
    "render_factored",
    "render_poly",
    "render_product",
    "render_sum",
    "render_surd",
    "sympy_str_of",
    "with_eul_reul",
    "with_eun_neun",
    "with_i_ga",
    "with_ira",
    "with_wa_gwa",
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


def render_affine(const: int, coef: int, var: str) -> str:
    """상수항 먼저 쓰는 일차식 표기('9 - 3k'·'3 + k'·'-k'·'5') — 계수 ±1 생략·0 항 제거·`+ -` 금지.

    `render_poly`는 차수 내림차순('-3k + 9')이라 해설의 '평균변화율은 9 - 3k' 같은 상수항 우선
    서술에 못 쓴다. 문자열을 손으로 이어 붙이면 '3 + 1k'·'1 + 0k'·'9 + -3k'가 나오므로(P3-03 감사
    결함) 그 부류를 이 헬퍼 하나로 막는다.
    """
    if coef == 0:
        return str(const)
    magnitude = abs(coef)
    term = var if magnitude == 1 else f"{magnitude}{var}"
    if const == 0:
        return f"-{term}" if coef < 0 else term
    return f"{const} {'-' if coef < 0 else '+'} {term}"


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


def render_surd(value: sympy.Expr) -> str:
    """학생 대면 근호 표기 — `8*sqrt(3)` → '8√3'·`sqrt(5)` → '√5'·정수는 그대로.

    4차 감사(2026-10-07) 교정: 3차 교정이 고른 '8sqrt(3)'(함수 호출꼴)은 감사자 둘이 모두 학생에게
    노출된 코드 표기로 판정했다. 승인 은행 4종의 관례는 유니코드 '√'다(2026-10 실측 93건 — 표기
    커버리지 게이트 `l3/notation_coverage`의 베이스라인에 이미 있는 글리프라 신규 누락이 아니다).
    Flutter 렌더(`math_notation.dart`)는 '√'를 비-ASCII 프로즈 글리프로 그대로 그린다.

    지원 범위는 `c·√r`(c 정수, r 제곱 인수 없는 양의 정수) 꼴뿐이다 — 그 밖의 값(분수 계수·
    합)이 들어오면 조용히 이상한 표기를 내지 않고 ValueError로 멈춘다.
    """
    expr = sympy.nsimplify(value)
    if expr.is_Integer:
        return str(expr)
    coeff, rest = expr.as_coeff_Mul()
    if not (coeff.is_Integer and rest.is_Pow and rest.exp == sympy.Rational(1, 2)):
        raise ValueError(f"c·√r 꼴이 아닌 근호 값: {value}")
    radicand = rest.base
    if not (radicand.is_Integer and radicand > 1):
        raise ValueError(f"근호 안이 1보다 큰 정수가 아니다: {value}")
    head = "" if coeff == 1 else ("-" if coeff == -1 else str(coeff))
    return f"{head}√{radicand}"


def render_product(factors: Sequence[Poly], var: str = "x") -> str:
    """곱 표기('(x^2 + 1)(3x - 2)') — 인수마다 괄호."""
    return "".join(f"({render_poly(f, var)})" for f in factors)


def render_factored(poly: Poly, var: str = "x") -> str:
    """정수 계수 인수분해 표기('3(x + 2)(x - 4)'·'2x(x + 3)^2'·'(x - 1)(x^2 + 2)').

    해설이 "도함수 → 인수분해 → 근"의 *중간 단계*를 보이도록 쓰는 헬퍼다(2차 감사: 결론만 말하는
    해설 교정). 인수분해는 SymPy `factor_list`가 정한다(손으로 인수를 고르지 않는다). 표기 순서는
    ① 정수 계수(1이면 생략·-1이면 '-') ② 변수 단항 인수('x'·'x^2') ③ 일차 인수(근 오름차순)
    ④ 나머지(이차 이상). 단항 인수를 맨 앞에 두는 것은 '2(x + 3)^2x'처럼 지수 뒤에 변수가 붙어
    `(x+3)^(2x)`로 읽히는 표기를 막기 위해서다(2차 감사 결함).
    """
    symbol = _symbol(var)
    expr = poly_to_sympy(poly, var)
    if expr == 0:
        return "0"
    coeff, factors = sympy.factor_list(expr, symbol)
    monomial: list[str] = []
    linear: list[tuple[sympy.Rational, str]] = []
    others: list[str] = []
    for factor, mult in factors:
        fpoly = poly_from_sympy(sympy.expand(factor), var)
        power = "" if mult == 1 else f"^{mult}"
        if fpoly == ((1, 1),):
            monomial.append(f"{var}{power}")
        elif fpoly[0][0] == 1:
            root = sympy.Rational(-dict(fpoly).get(0, 0), fpoly[0][1])
            linear.append((root, f"({render_poly(fpoly, var)}){power}"))
        else:
            others.append(f"({render_poly(fpoly, var)}){power}")
    head = "" if coeff == 1 else ("-" if coeff == -1 else str(coeff))
    body = "".join(monomial + [text for _, text in sorted(linear)] + others)
    return f"{head}{body}" if body else str(coeff)


def _signed_operand(value: object) -> str:
    """이항 연산의 오른쪽 피연산자 — 음수만 괄호('-3' → '(-3)')."""
    text = str(value)
    return f"({text})" if text.startswith("-") else text


def render_difference(left: object, right: object) -> str:
    """'2 - 3'·'2 - (-3)' — 산술 과정을 해설에 보일 때 쓰는 차 표기('2 - -3' 금지)."""
    return f"{left} - {_signed_operand(right)}"


def render_sum(left: object, right: object) -> str:
    """'2 + 3'·'2 + (-3)' — 산술 과정을 해설에 보일 때 쓰는 합 표기('2 + -3' 금지)."""
    return f"{left} + {_signed_operand(right)}"


def product_to_sympy_str(factors: Sequence[Poly], var: str = "x") -> str:
    """곱의 Tier1 표기('(x**2 + 1)*(3*x - 2)')."""
    return "*".join(f"({poly_to_sympy_str(f, var)})" for f in factors)


def sympy_str_of(poly: Poly, var: str = "x") -> str:
    """`answer_map` 값 표기 — `poly_to_sympy_str`의 별칭(의도 명시용)."""
    return poly_to_sympy_str(poly, var)


# ── 조사 부착 헬퍼 ────────────────────────────────────────────────────────
# 발문·해설 템플릿에 값·낱말을 끼우고 그 뒤에 조사를 붙일 때 *조사를 하드코딩하지 않는다*
# (P3-03 감사 결함 교정 — "계수은"·"108가"·"-6와" 류). 받침 판별은 `lang.josa`(수는 한자어 읽기·
# 변수는 라틴 문자 읽기·수식 꼬리는 마지막 읽기 음절)가 단일 진실 원천이다.


def with_i_ga(value: object) -> str:
    """값 뒤에 주격 조사(이/가)를 붙인 문자열 — 예 `with_i_ga(108)` = '108이'."""
    token = str(value)
    return f"{token}{i_ga(token)}"


def with_eun_neun(value: object) -> str:
    """값 뒤에 보조사(은/는)를 붙인 문자열 — 예 `with_eun_neun('계수')` = '계수는'."""
    token = str(value)
    return f"{token}{eun_neun(token)}"


def with_eul_reul(value: object) -> str:
    """값 뒤에 목적격 조사(을/를)를 붙인 문자열 — 예 `with_eul_reul(9)` = '9를'."""
    token = str(value)
    return f"{token}{eul_reul(token)}"


def with_wa_gwa(value: object) -> str:
    """값 뒤에 접속 조사(와/과)를 붙인 문자열 — 예 `with_wa_gwa(-6)` = '-6과'."""
    token = str(value)
    return f"{token}{wa_gwa(token)}"


def with_ira(value: object) -> str:
    """값 뒤에 서술격 '(이)라'를 붙인 문자열 — 예 `with_ira(3)` = '3이라'·`with_ira(2)` = '2라'.

    'g(x) = f(x) + 3라 할 때'(2차 감사 결함)처럼 '라'를 하드코딩하면 받침 있는 수 뒤에서 틀린다.
    받침 판별은 다른 조사 헬퍼와 같은 `lang.josa`(수는 한자어 읽기)다.
    """
    token = str(value)
    return f"{token}{'이라' if has_batchim_text(token) else '라'}"


_FN_USE_RE = {name: re.compile(rf"(?<![A-Za-z0-9_']){name}\s*[(']") for name in "fgh"}


def _defines_function(question_text: str, name: str) -> bool:
    """발문이 함수 기호 `name`을 소개했는가 — `name(x)`·`name(t)`·'함수 name'이 있으면 True."""
    pattern = rf"(?<![A-Za-z0-9_']){name}\((?:x|t)\)|함수 {name}(?![A-Za-z])"
    return re.search(pattern, question_text) is not None


#: 곡선 식에 함수 기호를 붙이는 *독립 문장* — 해설 앞에 붙는다(뒤 문장과 연결어미로 잇지 않는다).
ANCHOR_PREFIX = "곡선의 식을 y = {name}(x)라 하자. "

#: 해설 스스로의 명시 정의 — 'f(x) = x^3 - 3x + 2라 하자'·'h(x) = f(x) - g(x) = …라 하자'.
_EXPLICIT_DEF_RE = {
    name: re.compile(rf"(?<![A-Za-z0-9_']){name}\((?:x|t)\) = [^.]*?라 하자") for name in "fgh"
}


def _explanation_defines_function(explanation: str, name: str) -> bool:
    """해설이 `name`을 *쓰기 전에* 스스로 정의했는가(정의 문장이 첫 사용과 같은 자리거나 앞선다)."""
    match = _EXPLICIT_DEF_RE[name].search(explanation)
    if match is None:
        return False
    first_use = _FN_USE_RE[name].search(explanation)
    return first_use is None or first_use.start() >= match.start()


def anchor_curve_function(question_text: str, explanation: str, *, name: str = "f") -> str:
    """해설이 발문에 없는 함수 기호(f')를 꺼내면 곡선 식을 `y = f(x)`라 한다고 먼저 밝힌다.

    '곡선 y = x^2 + 1 위의 …' 처럼 곡선을 y = …로만 준 발문의 해설이 갑자기 f'(1)을 쓰면 f가
    정의되지 않은 채 등장한다(P3-03 감사 결함). 발문이 f를 소개했거나 해설이 f를 쓰지 않으면 해설을
    그대로 둔다. 머리말은 **독립 문장**이다 — 1차 교정은 '…로 놓으면 '으로 뒤 문장과 이어 붙여
    '놓으면 평행하면 …'처럼 '-면'이 겹치는 문장을 만들었다(2차 감사 결함).
    """
    if _FN_USE_RE[name].search(explanation) is None:
        return explanation
    if _defines_function(question_text, name):
        return explanation
    # 해설이 f를 *다른 뜻*(두 변의 차 등)으로 직접 정의하면 머리말을 붙이지 않는다 — 붙이면
    # '곡선의 식을 y = f(x)라 하자. 두 변의 차를 f(x) = …라 하자'처럼 f가 두 번, 다르게 정의된다.
    if _explanation_defines_function(explanation, name):
        return explanation
    return ANCHOR_PREFIX.format(name=name) + explanation
