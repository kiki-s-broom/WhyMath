"""미분 단원 오답 **서명** — 문항의 함수식과 제출 답으로 오개념 후보를 읽는다 (P3-56 후보 구현).

`answer_signature`의 거짓 항등식 채널(`canonical_wrong_form`)은 `(a+b)² = a²+b²` 같은 **다항
항등식**만
표현한다. 미분 오답은 그 모양이 아니다 — `f(x)=x⁸`, `f'(3)`을 묻는 문항에서 지수를 내리지 않은 답
`52488`은 항등식의 인스턴스가 아니라 *규칙 적용의 결과값*이다(2026-10-16 실측: 같은 문항에 기존
채널을 돌리면 `RAN_NO_CANDIDATE`, 곱의 미분 문항은 `NOT_RUN`). 그래서 같은 철학 — **문항이 다루는
것과
학생이 낸 답을 이어 이 시도에서 만들어진 주장으로 읽는다** — 을 유지한 채 읽는 법만 넓힌다. 새 판정
알고리즘이 아니라 기존 채널 옆의 두 번째 독법이다(`scan_attempt_answer`가 둘을 합쳐 같은 게이트를
건다).

무엇이 데이터이고 무엇이 코드인가
────────────────────────────────────────────────────────────────────────────
· **데이터**(`data/corpus/wrong_answer_signatures_v1/rules.yaml`): 어느 오개념(M-id)이, 어떤
  질문에서,
  어떤 변환의 값으로 드러나는지 + 신뢰도·근거 종류·픽스처. 오개념을 추가·조정하는 일은 이 파일을
  고친다.
· **코드**(이 파일): 질문 추출기(무엇을 묻는가)와 변환(오답 값을 만드는 수학)의 **이름 있는
  레지스트리**.
  수학이 들어 있으므로 코드다. 데이터가 레지스트리에 없는 이름을 가리키면 적재 시
  거부한다(fail-closed).

ID 체계를 새로 만들지 않는다
────────────────────────────────────────────────────────────────────────────
규칙은 M-id를 가리키고, 후보 id(kebab)는 기존 크로스워크 코퍼스에서 **읽는다**. 한 규칙의 M-id들이
서로 다른 kebab으로 걸려 있으면 어느 것이 런타임 키인지 코퍼스가 정하지 않은 것이므로 적재를
거부한다.

정직 스코프(중요)
────────────────────────────────────────────────────────────────────────────
· **다항 함수 한정**이다. 문항에서 `f(x)=…`/`y=…`를 읽어 x 하나만 가진 식일 때만 판정한다.
  삼각·지수·
  매개변수가 든 식, 구간 제한이 붙은 극값 문항은 *읽지 못한다* — 읽지 못함은 `applicable=False`이고
  호출자는 그것을 "오개념이 없었다"가 아니라 "이 채널로는 볼 수 없었다"로 다뤄야 한다.
· **정답과 같은 값은 후보가 아니다.** 변환이 낸 오답 값이 정답과 같으면(우연 일치) 그 값은 버린다.
· **같은 답이 서로 다른 오개념 둘 이상의 값과 같으면** 어느 쪽인지 가릴 수 없으므로 후보를 모두 내되
  `attribution_unclear`를 세워 확신 진단을 보류시킨다(게이트가 이미 소비하는 플래그 — 새 임계 0).
· 신뢰도는 데이터가 정한다. 직접 증거도 1.0이 아니다 — 학생이 실제로 그 규칙을 적용했다는 전제는
  문항
  식 추출(정규식)에 기대기 때문이다(`answer_signature._STRUCTURAL_MATCH_CONFIDENCE`와 같은 이유).
· **학생 원문을 산출물에 담지 않는다**(미성년 PII) — 규칙 id와 오개념 id만 남긴다.
· 학생 답 파싱은 동치 권위(`identity_status`)와 안전 파서(R22-03)를 거친다. 이 파일은 `sympify`를
  직접
  부르지 않는다.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import sympy

from whymath_backend.l1.misconception.wrong_answer_signature_table import (
    kebab_for_mis_id,
    load_signature_spec,
)
from whymath_backend.l3.symbolic_equivalence import (
    IdentityVerdict,
    identity_status,
    parse_unevaluated,
    to_sympy_source,
)
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.models import MisconceptionMatch
from whymath_backend.schema.wrong_answer_signature import SignatureRule

logger = logging.getLogger("whymath.l4.misconception.derivative_signature")

__all__ = [
    "ASK_EXTRACTORS",
    "WRONG_TRANSFORMS",
    "CompiledRule",
    "DerivativeSignatureError",
    "DerivativeSignatureResult",
    "compile_rules",
    "detect_derivative_signature",
]


class DerivativeSignatureError(ValueError):
    """규칙표가 엔진 레지스트리·크로스워크와 맞지 않는다 — 조용히 건너뛰지 않고 적재를 거부한다."""


# ── 질문에서 읽은 것 ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Frame:
    """질문이 다루는 함수 — 구조 보존형과 평가형을 함께 든다."""

    structure: sympy.Expr  # `evaluate=False` — 곱 꼴을 알아보는 데 쓴다.
    expr: sympy.Expr  # 전개된 다항식 — 값 계산에 쓴다.
    x: sympy.Symbol


@dataclass(frozen=True, slots=True)
class _Ask:
    """질문이 무엇을 묻는가."""

    kind: str
    point: sympy.Expr | None = None
    extremum: Literal["max", "min"] | None = None
    combine: Literal["sum", "product"] | None = None


@dataclass(frozen=True, slots=True)
class _Values:
    """한 변환이 이 질문에서 낸 값 — 정답과, 그 오개념이 낳는 오답들."""

    correct: sympy.Expr
    wrongs: tuple[sympy.Expr, ...]


_X = sympy.Symbol("x")

# `f(x) = …` 또는 `y = …` 다음의 수식 토큰 런. 한글에서 끊긴다(`x^4의`에서 `의` 앞까지).
_FUNC_DEF = re.compile(r"(?:f\(x\)|y)\s*=\s*(?P<expr>[0-9A-Za-z()+\-*/^|. ]+)")
_ABS_PAIR = re.compile(r"\|([^|]+)\|")
# 함수 정의 개수 세기용 — `f'(x)`(도함수 조건)는 아포스트로피 때문에 걸리지 않는다.
_FUNC_NAME_DEF = re.compile(r"\b[a-z]\(x\)\s*=")
# `두 함수 f(x) = A, g(x) = B 에 대하여 함수 f(x)g(x) 의 …` — 곱의 미분을 묻는 유일한 두 함수 표현.
_TWO_FUNCTION_PRODUCT = re.compile(
    r"두\s*함수\s*f\(x\)\s*=\s*(?P<f>[0-9A-Za-z()+\-*/^. ]+?)\s*,\s*"
    r"g\(x\)\s*=\s*(?P<g>[0-9A-Za-z()+\-*/^. ]+?)\s*에\s*대하여\s*함수\s*f\(x\)\s*g\(x\)"
)


def _clean_expr(text: str) -> str:
    """수식 토큰 런의 꼬리 공백을 걷는다."""
    return text.strip()


def _read_frame(question_text: str, *, allow_abs: bool = False) -> _Frame | None:
    """질문에서 x 하나만 가진 다항식을 읽는다. 못 읽으면 `None`(이 채널은 볼 수 없다)."""
    pair = _TWO_FUNCTION_PRODUCT.search(question_text)
    if pair is not None:
        return _read_product_frame(pair.group("f"), pair.group("g"))
    if len(_FUNC_NAME_DEF.findall(question_text)) > 1:
        return None  # `f(x)=…, g(x)=…` — 첫 함수만 읽으면 다른 질문을 푸는 셈이다.
    match = _FUNC_DEF.search(question_text)
    if match is None:
        return None
    raw = _clean_expr(match.group("expr"))
    if "|" in raw:
        if not allow_abs:
            return None
        # `|g|` → `(Abs(g))` — 바깥 괄호는 `Abs(g)(h)`가 함수 호출로 읽히는 것을 막는다.
        raw = _ABS_PAIR.sub(lambda m: f"(Abs({m.group(1)}))", raw)
    try:
        structure = parse_unevaluated(to_sympy_source(raw))
        expr = sympy.expand(structure.doit())
    except Exception as exc:  # noqa: BLE001 — 읽지 못한 식은 '볼 수 없음'으로 접는다(보수)
        logger.debug("함수식 읽기 회피: %s", type(exc).__name__)
        return None
    if not isinstance(expr, sympy.Expr) or expr.free_symbols != {_X}:
        return None
    if not allow_abs and not expr.is_polynomial(_X):
        return None
    return _Frame(structure=structure, expr=expr, x=_X)


def _read_product_frame(f_raw: str, g_raw: str) -> _Frame | None:
    """두 함수의 곱 `f(x)·g(x)` — 구조는 곱으로 보존하고 값 계산은 전개식으로 한다."""
    try:
        f = parse_unevaluated(to_sympy_source(_clean_expr(f_raw)))
        g = parse_unevaluated(to_sympy_source(_clean_expr(g_raw)))
        structure = sympy.Mul(f, g, evaluate=False)
        expr = sympy.expand(structure.doit())
    except Exception as exc:  # noqa: BLE001 — 읽지 못한 식은 '볼 수 없음'으로 접는다(보수)
        logger.debug("두 함수 곱 읽기 회피: %s", type(exc).__name__)
        return None
    if not isinstance(expr, sympy.Expr) or expr.free_symbols != {_X} or not expr.is_polynomial(_X):
        return None
    return _Frame(structure=structure, expr=expr, x=_X)


# ── 질문 추출기: 무엇을 묻는가 ──────────────────────────────────────────────────────────────

_AskExtractor = Callable[[str], _Ask | None]

_INT = r"-?\d+"
_DERIV_AT_PATTERNS = (
    re.compile(rf"f'\((?P<a>{_INT})\)\s*의\s*값"),
    re.compile(rf"x\s*=\s*(?P<a>{_INT})\s*에서의\s*(?:미분계수|순간변화율)"),
    re.compile(rf"x좌표가\s*(?P<a>{_INT})\s*인\s*점에서의\s*접선의\s*기울기"),
    re.compile(rf"점\s*\(\s*(?P<a>{_INT})\s*,\s*{_INT}\s*\)\s*에서의\s*접선의\s*기울기"),
    re.compile(rf"f'\(x\)에\s*x\s*=\s*(?P<a>{_INT})\s*를?\s*대입한\s*값"),
    re.compile(rf"y'에\s*대하여\s*x\s*=\s*(?P<a>{_INT})\s*일\s*때\s*y'의\s*값"),
)


def _ask_derivative_at(question_text: str) -> _Ask | None:
    """`f'(a)`·`x=a에서의 미분계수`·`접선의 기울기` — 점 a에서의 미분계수를 묻는 질문."""
    if "방정식" in question_text and "접선의 방정식" in question_text:
        return None  # 기울기가 아니라 식을 묻는다.
    if question_text.count("f'(") > 1 or re.search(
        r"f\(\s*-?\d+\s*\)|보다|양수|몇\s*배", question_text
    ):
        return None  # f'(a)가 다른 양과 얽힌 문항(비교·역문제) — 단순 값 질문이 아니다.
    # 점을 지정하는 표현은 질문 전체에서 **정확히 한 번**일 때만 읽는다 — 두 번 나오면 두 점의 값을
    # 비교하는 문항(예: '… 기울기에서 … 기울기를 뺀 값')이라 첫 점만 읽으면 다른 양을 푸는 셈이다.
    hits = [m for pattern in _DERIV_AT_PATTERNS for m in pattern.finditer(question_text)]
    if len(hits) != 1:
        return None
    return _Ask(kind="derivative_at", point=sympy.Integer(int(hits[0].group("a"))))


def _ask_monomial_params(question_text: str) -> _Ask | None:
    """`f'(x)를 cx^m 꼴로 나타낼 때 c+m / c·m` — 도함수의 계수·지수 조합을 묻는 질문."""
    if "cx^m" not in question_text:
        return None
    if re.search(r"c\s*\+\s*m", question_text):
        return _Ask(kind="monomial_params", combine="sum")
    if re.search(r"c\s*와\s*m\s*의\s*곱", question_text):
        return _Ask(kind="monomial_params", combine="product")
    return None


_EXTREMUM_POINT = (
    re.compile(r"극(?P<k>대|소)가\s*되는\s*x"),
    re.compile(r"극(?P<k>댓|솟)값을\s*가질\s*때,?\s*그\s*x"),
)
_EXTREMUM_VALUE = re.compile(r"극(?P<k>댓|솟)값(?:을\s*구하시오|으로\s*옳은)")


def _ask_extremum(question_text: str) -> _Ask | None:
    """한쪽 극값 하나의 **점**(x) 또는 **값**(f(x))을 묻는 질문. 그 밖의 극값 문항은 읽지 않는다."""
    if re.search(r"구간|개수|상수|중\s*(?:큰|작은)|방정식", question_text):
        return None  # 구간 제한·개수·매개변수·'둘 중'·방정식 활용은 이 독법의 사정거리 밖이다.
    for pattern in _EXTREMUM_POINT:
        found = pattern.search(question_text)
        if found:
            return _Ask(
                kind="extremum_point", extremum="max" if found.group("k") in "대댓" else "min"
            )
    found = _EXTREMUM_VALUE.search(question_text)
    if found:
        return _Ask(kind="extremum_value", extremum="max" if found.group("k") == "댓" else "min")
    return None


def _ask_extremum_point(question_text: str) -> _Ask | None:
    ask = _ask_extremum(question_text)
    return ask if ask is not None and ask.kind == "extremum_point" else None


def _ask_extremum_value(question_text: str) -> _Ask | None:
    ask = _ask_extremum(question_text)
    return ask if ask is not None and ask.kind == "extremum_value" else None


def _ask_extremum_any_point(question_text: str) -> _Ask | None:
    """`극값을 갖는 x` — 어느 극값인지는 묻지 않고 극값이 되는 점을 묻는 질문."""
    if re.search(r"구간|상수|중\s*(?:큰|작은)", question_text):
        return None
    if (
        re.search(r"극값을\s*갖는\s*x", question_text)
        or re.search(r"극값을\s*가질\s*때,?\s*이\s*점의\s*x", question_text)
        or re.search(r"증가·감소가\s*바뀌는\s*점의\s*x좌표는", question_text)
    ):
        return _Ask(kind="extremum_any_point")
    return None


def _ask_extremum_count(question_text: str) -> _Ask | None:
    """`극값의 개수` — 극값이 되는 점이 몇 개인지 묻는 질문."""
    if re.search(r"구간|상수", question_text):
        return None
    if re.search(r"극값의\s*개수를\s*구하시오", question_text):
        return _Ask(kind="extremum_count")
    return None


def _ask_differentiable_yes_no(question_text: str) -> _Ask | None:
    """`실수 전체에서 미분가능하면 1, 아니면 0을 쓰시오` — 미분가능 여부를 1/0으로 묻는 질문."""
    if re.search(r"실수\s*전체에서\s*미분가능하면\s*1,\s*아니면\s*0을\s*쓰시오", question_text):
        return _Ask(kind="differentiable_yes_no")
    return None


def _ask_one_sided_difference(question_text: str) -> _Ask | None:
    """`x=a에서의 우미분계수에서 좌미분계수를 뺀 값` — 꺾인 점의 미분계수 도약을 묻는 질문."""
    found = re.search(
        rf"x\s*=\s*(?P<a>{_INT})\s*에서의\s*우미분계수에서\s*좌미분계수를\s*뺀", question_text
    )
    if found is None:
        return None
    return _Ask(kind="one_sided_difference", point=sympy.Integer(int(found.group("a"))))


ASK_EXTRACTORS: dict[str, _AskExtractor] = {
    "derivative_at": _ask_derivative_at,
    "monomial_params": _ask_monomial_params,
    "extremum_point": _ask_extremum_point,
    "extremum_value": _ask_extremum_value,
    "extremum_any_point": _ask_extremum_any_point,
    "extremum_count": _ask_extremum_count,
    "differentiable_yes_no": _ask_differentiable_yes_no,
    "one_sided_difference": _ask_one_sided_difference,
}
"""질문 추출기 레지스트리 — 데이터의 `ask`가 가리키는 이름. 추출기가 없으면 적재를 거부한다."""

# ── 변환: 오답 값을 만드는 수학 ─────────────────────────────────────────────────────────────


def _termwise_derivative(
    expr: sympy.Expr, x: sympy.Symbol, rule: Callable[[sympy.Expr, int], sympy.Expr]
) -> sympy.Expr:
    """다항식을 항별로 훑어 `rule(계수, 지수)`의 합으로 만든다 — 상수항은 0."""
    poly = sympy.Poly(expr, x)
    total: sympy.Expr = sympy.Integer(0)
    for (n,), c in poly.terms():
        if n == 0:
            continue
        total += rule(c, n)
    return total


def _omit_reduce(c: sympy.Expr, n: int) -> sympy.Expr:
    """지수를 앞으로 내리되 1을 줄이지 않는다: `c·xⁿ → c·n·xⁿ`."""
    return c * n * _X**n


def _omit_bring_down(c: sympy.Expr, n: int) -> sympy.Expr:
    """1은 줄이되 지수를 앞으로 내리지 않는다: `c·xⁿ → c·xⁿ⁻¹`."""
    return c * _X ** (n - 1)


def _tr_power_rule_step_omitted(frame: _Frame, ask: _Ask) -> _Values | None:
    """거듭제곱 미분의 두 단계(지수 내리기·1 줄이기) 중 하나를 빠뜨린 오답들."""
    x, expr = frame.x, frame.expr
    if _is_product(frame) or not _is_plain_polynomial(frame):
        # 곱의 미분 문항은 곱의 미분 오류의 재료이고, 합성함수 `(2x+3)³`은 연쇄 법칙의 재료다 —
        # 전개한 다항식에 이 변환을 걸면 우연히 같은 값이 나와도 지수 규칙 오류의 증거가 아니다.
        return None
    correct_deriv = sympy.diff(expr, x)
    if ask.kind == "derivative_at":
        assert ask.point is not None
        a = ask.point
        wrongs = (
            _termwise_derivative(expr, x, _omit_reduce).subs(x, a),
            _termwise_derivative(expr, x, _omit_bring_down).subs(x, a),
        )
        return _Values(correct=correct_deriv.subs(x, a), wrongs=tuple(wrongs))
    if ask.kind == "monomial_params":
        poly = sympy.Poly(expr, x)
        if len(poly.terms()) != 1:
            return None  # `cxᵐ` 꼴로 쓸 수 있는 단항식만.
        (n,), c0 = poly.terms()[0]
        if n < 2:
            return None
        combine = _combine(ask.combine)
        correct = combine(c0 * n, sympy.Integer(n - 1))
        return _Values(
            correct=correct,
            wrongs=(
                combine(c0 * n, sympy.Integer(n)),  # 1을 줄이지 않았다.
                combine(c0, sympy.Integer(n - 1)),  # 지수를 내리지 않았다.
            ),
        )
    return None


def _is_product(frame: _Frame) -> bool:
    """구조가 x에 의존하는 인수 둘 이상의 곱인가 — 곱의 미분 규칙이 필요한 식."""
    structure = frame.structure
    if not isinstance(structure, sympy.Mul):
        return False
    return len([f for f in structure.args if f.has(frame.x)]) >= 2


def _is_plain_polynomial(frame: _Frame) -> bool:
    """거듭제곱의 밑이 모두 변수 x 자체인가 — 즉 쓰인 그대로 항들의 합인 다항식."""
    return all(p.base == frame.x for p in frame.structure.atoms(sympy.Pow))


def _combine(
    kind: Literal["sum", "product"] | None,
) -> Callable[[sympy.Expr, sympy.Expr], sympy.Expr]:
    if kind == "sum":
        return lambda c, m: c + m
    if kind == "product":
        return lambda c, m: c * m
    raise DerivativeSignatureError(f"combine이 없습니다: {kind!r}")


def _tr_product_of_factor_derivatives(frame: _Frame, ask: _Ask) -> _Values | None:
    """곱의 미분을 '각 인수를 따로 미분한 것의 곱'으로 처리한 오답 `(fg)' → f'g'`."""
    if ask.kind != "derivative_at" or ask.point is None:
        return None
    x, structure = frame.x, frame.structure
    if not isinstance(structure, sympy.Mul):
        return None  # 전개된 합의 형태는 곱이 아니다 — 이 오개념의 재료가 아니다.
    dependent = [f for f in structure.args if f.has(x)]
    if len(dependent) < 2:
        return None
    constant = sympy.Mul(*[f for f in structure.args if not f.has(x)])
    a = ask.point
    wrong = constant * sympy.Mul(*[sympy.diff(f, x).doit().subs(x, a) for f in dependent])
    correct = sympy.diff(frame.expr, x).subs(x, a)
    return _Values(correct=correct, wrongs=(wrong,))


@dataclass(frozen=True, slots=True)
class _Critical:
    """도함수의 실근 하나 — 그 점이 극대·극소인지, 둘 다 아닌지(부호가 바뀌지 않음)."""

    point: sympy.Rational
    kind: Literal["max", "min", "none"]


_MAX_DEGREE = 6


def _critical_points(expr: sympy.Expr, x: sympy.Symbol) -> tuple[_Critical, ...] | None:
    """도함수의 모든 실근을 분류한다. 유리수가 아닌 근이 있거나 차수가 크면 `None`(볼 수 없음)."""
    deriv = sympy.Poly(sympy.diff(expr, x), x)
    if deriv.is_zero or deriv.degree() > _MAX_DEGREE:
        return None
    roots = sorted({r for r in deriv.real_roots()}, key=lambda r: float(r))
    if not roots or not all(r.is_Rational for r in roots):
        return None
    # 인접 근 사이의 표본점에서 f'의 부호를 읽는다 — 중근(부호 불변)을 잡는 유일하게 안전한
    # 방법이다.
    samples: list[sympy.Expr] = [roots[0] - 1]
    samples += [(roots[i] + roots[i + 1]) / 2 for i in range(len(roots) - 1)]
    samples.append(roots[-1] + 1)
    signs = [sympy.sign(deriv.as_expr().subs(x, s)) for s in samples]
    result: list[_Critical] = []
    for i, root in enumerate(roots):
        left, right = signs[i], signs[i + 1]
        kind: Literal["max", "min", "none"]
        if left > 0 and right < 0:
            kind = "max"
        elif left < 0 and right > 0:
            kind = "min"
        else:
            kind = "none"
        result.append(_Critical(point=sympy.Rational(root), kind=kind))
    return tuple(result)


def _only(criticals: tuple[_Critical, ...], kind: str) -> _Critical | None:
    found = [c for c in criticals if c.kind == kind]
    return found[0] if len(found) == 1 else None


def _tr_extremum_swap(frame: _Frame, ask: _Ask) -> _Values | None:
    """극대와 극소를 맞바꿔 답한 오답 — 묻는 쪽의 반대 극값(점 또는 값)을 낸다."""
    if ask.kind not in ("extremum_point", "extremum_value") or ask.extremum is None:
        return None
    criticals = _critical_points(frame.expr, frame.x)
    if criticals is None:
        return None
    this = _only(criticals, ask.extremum)
    other = _only(criticals, "min" if ask.extremum == "max" else "max")
    if this is None or other is None:
        return None  # 서로 다른 극값이 하나씩 있을 때만 '맞바꿈'이 정의된다.
    if ask.kind == "extremum_point":
        return _Values(correct=this.point, wrongs=(other.point,))
    return _Values(
        correct=frame.expr.subs(frame.x, this.point),
        wrongs=(frame.expr.subs(frame.x, other.point),),
    )


def _tr_extremum_value_as_point(frame: _Frame, ask: _Ask) -> _Values | None:
    """극값(함숫값)을 묻는데 임계점의 x좌표를 답한 오답.

    오개념 코퍼스의 보기 규칙(M0865 `distractor_rule`)이 "극점의 x좌표(임계점)를 극값의 값 대신"
    이라고 정의하므로 같은 극값의 x만이 아니라 **임계점 x좌표 전부**가 이 오답의 모양이다.
    """
    if ask.kind != "extremum_value" or ask.extremum is None:
        return None
    criticals = _critical_points(frame.expr, frame.x)
    if criticals is None:
        return None
    this = _only(criticals, ask.extremum)
    if this is None:
        return None
    return _Values(
        correct=frame.expr.subs(frame.x, this.point),
        wrongs=tuple(c.point for c in criticals if c.kind != "none"),
    )


def _tr_non_extremum_critical_point(frame: _Frame, ask: _Ask) -> _Values | None:
    """f'(a)=0인 점이면 모두 극값이라고 본 오답 — 부호가 바뀌지 않는 임계점을 낸다."""
    if ask.kind not in ("extremum_point", "extremum_any_point"):
        return None
    criticals = _critical_points(frame.expr, frame.x)
    if criticals is None:
        return None
    flat = tuple(c.point for c in criticals if c.kind == "none")
    if not flat:
        return None  # 극값이 아닌 임계점이 없으면 이 오개념이 드러날 자리가 없다.
    if ask.kind == "extremum_point":
        assert ask.extremum is not None
        this = _only(criticals, ask.extremum)
        if this is None:
            return None
        return _Values(correct=this.point, wrongs=flat)
    # 어느 극값인지 묻지 않을 때 정답은 극값인 점들의 집합이라 단일 값이 아니다 — 정답과의 충돌은
    # 후보 점이 극값이 아니라는 사실로 이미 배제된다. 정답 자리에는 비교 불가 표지를 둔다.
    return _Values(correct=sympy.nan, wrongs=flat)


def _tr_critical_point_count(frame: _Frame, ask: _Ask) -> _Values | None:
    """극값의 개수를 묻는데 f'=0인 점의 개수를 센 오답 — 부호가 안 바뀌는 점까지 극값으로 센다."""
    if ask.kind != "extremum_count":
        return None
    criticals = _critical_points(frame.expr, frame.x)
    if criticals is None:
        return None
    extrema = sum(1 for c in criticals if c.kind != "none")
    return _Values(correct=sympy.Integer(extrema), wrongs=(sympy.Integer(len(criticals)),))


def _kink_points(frame: _Frame) -> list[sympy.Expr] | None:
    """절댓값 안쪽이 0이 되는 유리수 점 — 꺾일 수 있는 후보. 읽지 못하면 `None`."""
    points: list[sympy.Expr] = []
    for node in frame.expr.atoms(sympy.Abs):
        inner = sympy.Poly(node.args[0], frame.x)
        if inner.degree() > 4:
            return None
        for root in inner.real_roots():
            if not root.is_Rational:
                return None
            if root not in points:
                points.append(root)
    return points


def _jump_at(frame: _Frame, a: sympy.Expr) -> sympy.Expr | None:
    """`a`에서 (우미분계수 − 좌미분계수). 중근 절댓값처럼 이 독법 밖이면 `None`."""
    x = frame.x
    right: dict[sympy.Expr, sympy.Expr] = {}
    left: dict[sympy.Expr, sympy.Expr] = {}
    for node in frame.expr.atoms(sympy.Abs):
        inner = node.args[0]
        at = inner.subs(x, a)
        slope = sympy.diff(inner, x).subs(x, a)
        if at == 0:
            if slope == 0:
                return None  # 중근에서의 절댓값은 꺾임이 아니다 — 이 독법 밖.
            sgn = sympy.sign(slope)
            right[node], left[node] = sgn * inner, -sgn * inner
        else:
            sgn = sympy.sign(at)
            right[node] = left[node] = sgn * inner
    f_right, f_left = frame.expr.xreplace(right), frame.expr.xreplace(left)
    return sympy.diff(f_right, x).subs(x, a) - sympy.diff(f_left, x).subs(x, a)


def _tr_differentiable_claimed(frame: _Frame, ask: _Ask) -> _Values | None:
    """연속인데 꺾인 함수를 '미분가능하다'(1)고 답한 오답 — 연속이면 미분가능하다는 단정."""
    if ask.kind != "differentiable_yes_no":
        return None
    kinks = _kink_points(frame)
    if kinks is None:
        return None
    for a in kinks:
        jump = _jump_at(frame, a)
        if jump is None:
            return None
        if jump != 0:
            return _Values(correct=sympy.Integer(0), wrongs=(sympy.Integer(1),))
    return _Values(correct=sympy.Integer(1), wrongs=())  # 꺾임이 없다 — 1이 정답이다.


def _tr_one_sided_difference_zero(frame: _Frame, ask: _Ask) -> _Values | None:
    """연속이면 미분가능하다고 보아 꺾인 점에서 좌우 미분계수가 같다고 답한 오답 `0`."""
    if ask.kind != "one_sided_difference" or ask.point is None:
        return None
    jump = _jump_at(frame, ask.point)
    if jump is None:
        return None
    return _Values(correct=jump, wrongs=(sympy.Integer(0),))


_Transform = Callable[[_Frame, _Ask], _Values | None]

WRONG_TRANSFORMS: dict[str, tuple[frozenset[str], _Transform]] = {
    "power_rule_step_omitted": (
        frozenset({"derivative_at", "monomial_params"}),
        _tr_power_rule_step_omitted,
    ),
    "product_of_factor_derivatives": (
        frozenset({"derivative_at"}),
        _tr_product_of_factor_derivatives,
    ),
    "extremum_swap": (frozenset({"extremum_point", "extremum_value"}), _tr_extremum_swap),
    "extremum_value_as_point": (frozenset({"extremum_value"}), _tr_extremum_value_as_point),
    "non_extremum_critical_point": (
        frozenset({"extremum_point", "extremum_any_point"}),
        _tr_non_extremum_critical_point,
    ),
    "one_sided_difference_zero": (
        frozenset({"one_sided_difference"}),
        _tr_one_sided_difference_zero,
    ),
    "critical_point_count": (frozenset({"extremum_count"}), _tr_critical_point_count),
    "differentiable_claimed": (frozenset({"differentiable_yes_no"}), _tr_differentiable_claimed),
}
"""변환 레지스트리 — 이름 → (지원하는 질문 종류, 함수). 데이터의 `wrong_transform`이 가리킨다."""

# 절댓값을 읽어야 하는 질문 종류 — 나머지는 다항식만 읽는다.
_ASKS_NEEDING_ABS = frozenset({"one_sided_difference", "differentiable_yes_no"})


# ── 규칙 적재 ───────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CompiledRule:
    """검증을 마친 규칙 — 데이터 규칙 + 해소된 런타임 kebab."""

    rule: SignatureRule
    kebab_id: str


@lru_cache(maxsize=1)
def compile_rules() -> tuple[CompiledRule, ...]:
    """규칙표를 레지스트리·크로스워크·카탈로그와 대조해 적재한다 — 하나라도 어긋나면 거부.

    Raises:
        DerivativeSignatureError: 모르는 질문 추출기·변환 이름, 변환이 지원하지 않는 질문 종류,
            M-id가 kebab에 걸려 있지 않거나 여러 kebab에 걸림, kebab이 카탈로그에 없음.
    """
    compiled: list[CompiledRule] = []
    for rule in load_signature_spec().rules:
        if rule.ask not in ASK_EXTRACTORS:
            raise DerivativeSignatureError(f"{rule.rule_id}: 모르는 ask {rule.ask!r}")
        if rule.wrong_transform not in WRONG_TRANSFORMS:
            raise DerivativeSignatureError(
                f"{rule.rule_id}: 모르는 wrong_transform {rule.wrong_transform!r}"
            )
        supported, _ = WRONG_TRANSFORMS[rule.wrong_transform]
        if rule.ask not in supported:
            raise DerivativeSignatureError(
                f"{rule.rule_id}: 변환 {rule.wrong_transform!r}은 "
                f"ask {rule.ask!r}를 지원하지 않습니다"
            )
        kebabs = {kebab_for_mis_id(m) for m in rule.mis_ids}
        if None in kebabs or len(kebabs) != 1:
            raise DerivativeSignatureError(
                f"{rule.rule_id}: mis_ids {rule.mis_ids}가 크로스워크에서 하나의 kebab으로 "
                f"해소되지 않습니다(해소 결과: {sorted(str(k) for k in kebabs)})"
            )
        kebab = next(iter(kebabs))
        assert kebab is not None
        if kebab not in CATALOG_BY_ID:
            raise DerivativeSignatureError(f"{rule.rule_id}: kebab {kebab!r}이 카탈로그에 없습니다")
        compiled.append(CompiledRule(rule=rule, kebab_id=kebab))
    return tuple(compiled)


# ── 판정 ────────────────────────────────────────────────────────────────────────────────────

_ANSWER_PREFIX = re.compile(r"^\s*[a-zA-Z]\s*=\s*")


def _same_value(student_answer: str, value: sympy.Expr) -> bool:
    """학생 답이 `value`와 동치인가 — 동치 권위(`identity_status`)에 위임한다."""
    if value is sympy.nan or not value.is_number:
        return False
    answer = _ANSWER_PREFIX.sub("", student_answer).strip().rstrip(".")
    if not answer:
        return False
    try:
        return identity_status(to_sympy_source(answer), str(value)) is IdentityVerdict.identity
    except Exception as exc:  # noqa: BLE001 — 읽지 못한 답은 일치가 아니다(보수)
        logger.debug("학생 답 대조 회피: %s", type(exc).__name__)
        return False


@dataclass(frozen=True, slots=True)
class DerivativeSignatureResult:
    """이 채널의 판정 — 후보와 **읽었는지 여부**.

    `applicable=False`는 "질문에서 함수식이나 묻는 양을 읽지 못해 볼 수 없었다"이고, 후보가 비었어도
    `applicable=True`면 "읽었고 어느 규칙의 오답 값과도 같지 않았다"이다. 호출자는 이 둘을 구별해야
    한다 — 0건이 두 뜻을 가지기 때문이다.
    """

    matches: tuple[MisconceptionMatch, ...]
    applicable: bool
    rules_total: int
    answer_is_correct: bool | None = None
    """학생 답이 이 질문의 **정답**과 같은가. `report_correctness=True`로 불렀고 질문을 읽었을 때만
    True/False이고, 그 밖에는 `None`(모른다 ≠ 아니다). 그림자 관측이 정답 회차와 오답 회차를 가르는
    데 쓴다 — 정답 회차에서 후보가 나오면 오발화다."""


def detect_derivative_signature(
    question_text: str, student_answer: str, *, report_correctness: bool = False
) -> DerivativeSignatureResult:
    """질문과 제출 답에서 미분 오답 서명을 읽어 후보를 낸다 — 순수·결정론·DB 무지.

    절차: ① 규칙마다 질문 추출기로 *무엇을 묻는지* 읽는다 ② 함수식을 읽는다 ③ 변환이 오답 값들을
    계산한다(정답과 같은 값은 버린다) ④ 학생 답이 그 값과 동치인지 동치 권위로 대조한다 ⑤ 같은 답이
    서로 다른 kebab 둘 이상에 걸리면 모두 `attribution_unclear`로 표시한다.

    `report_correctness=True`면 학생 답이 정답과 같은지도 대조해 `answer_is_correct`에 싣는다 —
    동치 호출이 규칙마다 하나 늘어나므로 기본은 끈다(서빙 경로는 필요 없다).
    """
    rules = compile_rules()
    frames: dict[bool, _Frame | None] = {}
    hits: dict[str, MisconceptionMatch] = {}
    applicable = False
    answer_is_correct: bool | None = None

    for compiled in rules:
        rule = compiled.rule
        ask = ASK_EXTRACTORS[rule.ask](question_text)
        if ask is None:
            continue
        needs_abs = ask.kind in _ASKS_NEEDING_ABS
        if needs_abs not in frames:
            frames[needs_abs] = _read_frame(question_text, allow_abs=needs_abs)
        frame = frames[needs_abs]
        if frame is None:
            continue
        _, transform = WRONG_TRANSFORMS[rule.wrong_transform]
        try:
            values = transform(frame, ask)
        except (
            Exception
        ) as exc:  # noqa: BLE001 — 계산 불가는 '볼 수 없음'으로 접는다(예외 타입만 기록)
            logger.debug("변환 회피(%s): %s", rule.rule_id, type(exc).__name__)
            continue
        if values is None:
            continue
        applicable = True
        if report_correctness and answer_is_correct is not True:
            answer_is_correct = _same_value(student_answer, values.correct)
        wrongs = [w for w in values.wrongs if w != values.correct]
        if not any(_same_value(student_answer, w) for w in wrongs):
            continue
        misconception = CATALOG_BY_ID[compiled.kebab_id]
        match = MisconceptionMatch(
            misconception=misconception,
            confidence=rule.confidence,
            matched_signals=(rule.rule_id,),
        )
        previous = hits.get(compiled.kebab_id)
        if previous is None or match.confidence > previous.confidence:
            hits[compiled.kebab_id] = match

    ordered = sorted(hits.values(), key=lambda m: m.confidence, reverse=True)
    if len(ordered) > 1:
        # 한 답이 서로 다른 오개념 둘 이상의 값과 같다 — 어느 쪽인지 가릴 수 없다.
        ordered = [m.model_copy(update={"attribution_unclear": True}) for m in ordered]
    return DerivativeSignatureResult(
        matches=tuple(ordered),
        applicable=applicable,
        rules_total=len(rules),
        answer_is_correct=answer_is_correct if applicable else None,
    )
