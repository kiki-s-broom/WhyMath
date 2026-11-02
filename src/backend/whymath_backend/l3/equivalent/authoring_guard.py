"""LLM 저작 산출물의 생성 단계 거부 규칙 — 검산식 근거·정답 키·단원 코드·교육과정 범위 (EOS-205).

왜 필요한가
----------
EOS-197 A6 회차(30 CU)의 검수 메모에 같은 결함 네 가지가 반복됐다.

1. **검산식이 문항을 다시 계산하지 않는다** — `n = 3`·`v - 24 = 0`처럼 정답 상수를 다시 적거나
   (재진술), `b = 7*(0 - 2)`처럼 모델이 미리 구한 중간값(기울기 7)을 박아 넣는다. 정답이 틀려도
   모델은 같은 틀린 값으로 식을 적으므로 Tier1 대입 검산이 **항상 통과한다** — 검증이 아니라
   자기 확인이다(학생 제공 전 검증 원칙 위반 위험).
2. **정답 키가 제각각** — `b`·`v`·`n`·`y`·`M`·`answer`가 섞였다.
3. **단원 코드가 비표준** — `CALC1-TANGENT`·`CAL-TANGENT`·`MI-CALC-EXTREMA` 등 회차 하나에 15종.
4. **교육과정 밖 해설** — 미적분Ⅰ 극값 문항 해설이 이계도함수(f″)로 판정했다(수정승인 2건).

이 모듈은 넷을 **결정론 순수 함수**로 판정한다. 호출부는 `llm_generator._assemble`이고, 거부는
`ValueError` 하위 예외로 올라가 생성 실패(`후보 조립 실패: <예외 타입명>`)로 GenerationLog에 남는다
— 타입명이 사유를 가르므로 회차 측정에서 "동어반복으로 버린 건수"를 셀 수 있다.

검산식 근거 판정 (`grounding_verdict`)
------------------------------------
조건 목록과 발문을 받아 네 상태 중 하나를 낸다. **등식 조건 전부**가 근거를 가져야 통과다(부등식은
도메인 제약이라 보지 않는다).

- **GROUNDED** — 각 등식이 다음 중 하나다.
    · 발문의 방정식과 같은 정규형(`canonicalize.canonical_condition`) — 근을 묻는 문항.
      `f(a) = 10`·`f(1) = 0`처럼 정의된 함수를 적용한 식도 발문 방정식으로 수집한다.
    · 문항 함수 P(또는 P′·P″)를 **계산하는 부분식**이 있고, 그 밖의 수는 발문에 적힌 수·대입
      점·0·1뿐이다. 계산하는 부분식은 두 꼴이다.
        - 기호: `(x**3 - 5*x + 2)`처럼 P의 상수배(`.subs(x, 2)` 꼴 포함).
        - 수치: `(3*2**2 - 5)`처럼 **점 a를 대입한 꼴** — 값이 P(a)·P′(a)·P″(a)와 같고, a의 출현
          일부를 변수로 되돌리면 정확히 P(또는 P′·P″)가 된다(구조 일치). Kiki 검수 메모의 교체안
          `answer == (2**3 - 5*2 + 2) - 2*(3*2**2 - 5)`가 이 꼴이다. 값만 보면 `-2*1`(미리 구한
          기울기 -2)이 f′(1) = -2와 우연히 같아 통과하므로 구조 일치를 함께 요구한다.
      "그 밖의 수" 조건이 없으면 `(f(2) 대입식) - (-3)*2`(기울기 -3 하드코딩)·`0*(…) + 12`(정답
      덧붙임)가 근거 부분식 하나 덕분에 통과한다.
- **RESTATEMENT** — 근거가 없고, 기존 판정기 `verify_bypass.classify_verify_bypass`(EOS-207)가
  우회(정답 상수 재진술·무조건 참)로 판정. 근거 판정을 **먼저** 하는 이유: 그 판정기는 0·1
  리터럴을 버리므로 `4*1`(f′(1), f′(x) = 4x) 같은 정당한 대입식을 재진술로 읽는다.
- **UNGROUNDED** — 근거가 없고 재진술도 아니다(`b = 7*(0 - 2)` · `M**2 - M - 182 = 0`).
- **UNKNOWN** — 발문에서 함수·방정식을 하나도 읽지 못했거나 검산 등식이 없다. 판정할 수 없으므로
  거부하지 않는다(모른다 ≠ 아니다) — 호출부가 경고 로그를 남긴다. 단 이때도 재진술이면 거부한다.

정직한 한계(있는 척 금지)
-----------------------
- 발문 함수 추출은 `f(x) = …`·`s(t) = …`·`y = …`·`… = 0` 꼴의 **다항·유리식 표기만** 읽는다.
  `sqrt`·삼각함수·로그 등 함수 이름이 든 식은 암묵 곱셈 보정과 충돌해 읽지 못할 수 있고, 그러면
  UNKNOWN이 되어 이 판정이 걸리지 않는다(재진술 판정은 여전히 걸린다).
- 이 판정은 적대적 회피가 아니라 *게으른 검산식*(정답·중간값 하드코딩)을 막는 것이 목적이다.
  구조 일치는 "P에 a를 대입한 식이 검산식 안에 있다"까지만 보장한다 — 그 대입식을 정답과 어떻게
  엮었는지(접선 공식 자체가 옳은지)는 Tier1 대입 검산과 사람 검수의 몫이다.
- 한 점의 출현이 8개를 넘는 부분식은 구조 일치를 시도하지 않는다(부분집합 2^N 상한).
- 상수 도함수(이차함수의 P″ 등)는 후보에서 뺀다 — 상수는 어느 수치식과도 너무 쉽게 같아진다.
- 점이 0·1·−1인 대입식을 **미리 약분**해 쓰면(`3*1**2 + 3`을 `3*1 + 3`으로) 구조가 사라져 거부된다
  — 프롬프트가 "함수식에 점을 대입한 형태 그대로" 쓰게 지시한다.
- 발문에 적힌 수는 허용되므로, 하드코딩한 중간값이 우연히 발문의 계수와 같으면 통과한다.
"""

from __future__ import annotations

import ast
import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import combinations

import sympy

from whymath_backend.l3.equivalent.canonicalize import canonical_condition
from whymath_backend.l3.equivalent.verify_bypass import classify_verify_bypass
from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.l3.verify_answer import _parse_condition, _relation_sides

__all__ = [
    "ANSWER_KEY",
    "AuthoringGuardError",
    "CurriculumScopeError",
    "GroundingState",
    "GroundingVerdict",
    "QuestionRelations",
    "TautologicalConditionError",
    "curriculum_method_violation",
    "extract_question_relations",
    "grounding_verdict",
    "normalize_answer_key",
    "standard_unit_codes",
]

# 정답 키 표준 — 답이 방정식의 근이 아닌 문항(접선의 y절편·극값·속도·개수)은 이 이름으로 고정한다.
ANSWER_KEY = "answer"


class AuthoringGuardError(ValueError):
    """생성 단계 거부의 공통 상위형 — `ValueError` 하위라 기존 조립 실패 경로(None 폴백)를 탄다."""


class TautologicalConditionError(AuthoringGuardError):
    """검산식이 문항을 다시 계산하지 않는다(재진술·중간값 하드코딩·역산 식)."""


class CurriculumScopeError(AuthoringGuardError):
    """해설·발문이 그 성취기준의 교육과정 범위 밖 방법을 쓴다."""


class GroundingState(str, Enum):
    """검산식 근거 판정 4상태(모듈 docstring)."""

    GROUNDED = "grounded"
    RESTATEMENT = "restatement"
    UNGROUNDED = "ungrounded"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GroundingVerdict:
    """판정 결과 — `rejected`가 True면 호출부가 생성을 거부한다."""

    state: GroundingState
    reason: str

    @property
    def rejected(self) -> bool:
        return self.state in (GroundingState.RESTATEMENT, GroundingState.UNGROUNDED)


@dataclass(frozen=True, slots=True)
class QuestionRelations:
    """발문에서 읽은 수식 관계.

    - `functions`: (변수 이름, P) — `f(x) = …` 꼴의 함수 정의(매개변수 허용).
    - `equations`: 방정식 원문(SymPy 표기) — `x^2 - 6x + 8 = 0`·`f(a) = 10`(함수 적용)처럼 근을
      묻는 문항의 근거 대조용. `t = 3`처럼 기호 하나에 수를 지정한 식은 넣지 않는다(조건이지
      방정식이 아니다).
    - `variables`: **방정식**의 자유 기호 이름 — 정답 키 정규화가 "근을 묻는 변수"를 가르는 데 쓴다.
      함수 정의의 변수(`f(x)`의 x)는 넣지 않는다(극값을 `x`로 적은 답은 근이 아니다).
    - `numbers`: 발문에 적힌 수의 절댓값(지수 자리 제외) — 검산식이 써도 되는 수.
    """

    functions: tuple[tuple[str, sympy.Expr], ...]
    equations: tuple[str, ...]
    variables: frozenset[str]
    numbers: frozenset[sympy.Expr] = frozenset()
    # 함수 정의 식 밖에 적힌 수(접점·시각 등)와, 함수 적용이 아닌 발문 고유 방정식 — 구조 중복
    # 판정(EOS-204 `structural_dedup`)의 재료. 함수식의 계수는 `functions`가 이미 담는다.
    point_numbers: frozenset[sympy.Expr] = frozenset()
    own_equations: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.functions and not self.equations


# ── 발문 수식 추출 ─────────────────────────────────────────────────────────
# 발문 속 수식으로 볼 문자(한글·쉼표를 만나면 멈춘다 — `(2, 0)`·`의`·`로` 경계).
_MATH_CHAR = re.compile(r"[0-9A-Za-z+\-*/^().\s²³⁴−·×]")
# 함수 머리: `f(x)`·`s(t)`·`x(t)` — 한 글자 이름 + 한 글자 변수 또는 수(`f(1)`·`f(-2)` 적용).
_FUNCTION_HEAD = re.compile(r"^([A-Za-z])\s*\(\s*([A-Za-z]|-?\d+(?:/\d+)?)\s*\)$")
# 수식 꼬리의 단위 표기 `(m)`·`(cm)` — 암묵 곱셈으로 함수식에 섞이지 않게 먼저 떼어 낸다.
_UNIT_TAIL = re.compile(r"\s*\(\s*[A-Za-z]{1,3}\s*\)\s*$")
# 위첨자·유니코드 연산자 → SymPy 표기.
_SUPERSCRIPTS = {"²": "**2", "³": "**3", "⁴": "**4"}
_UNICODE_OPS = {"−": "-", "×": "*", "·": "*"}
# 꼬리 다듬기 시도 상한 — `3 (x의`처럼 수식 뒤에 붙은 괄호 조각을 잘라 보는 횟수.
_TRIM_ATTEMPTS = 6


def _normalize_math(text: str) -> str:
    """발문 수식 표기 → SymPy 표기(`^`·위첨자·유니코드 연산자·암묵 곱셈)."""
    out = text.strip()
    for src, dst in {**_SUPERSCRIPTS, **_UNICODE_OPS}.items():
        out = out.replace(src, dst)
    out = out.replace("^", "**")
    # 암묵 곱셈: `5x`→`5*x` · `)(`→`)*(` · `)x`→`)*x` · `xy`→`x*y` · `x(`→`x*(`.
    out = re.sub(r"(\d)\s*(?=[A-Za-z(])", r"\1*", out)
    out = re.sub(r"\)\s*(?=[A-Za-z0-9(])", ")*", out)
    out = re.sub(r"([A-Za-z])(?=[A-Za-z(])", r"\1*", out)
    return out


def _parse_math(text: str, allowed: frozenset[str] | None = None) -> sympy.Expr | None:
    """발문 수식 조각 → SymPy 식. 꼬리의 괄호 조각을 잘라 가며 재시도하고, 끝내 못 읽으면 None.

    `allowed`를 주면 자유 기호가 그 안에 들어올 때까지 꼬리를 더 자른다 — `… + 1 (m)`의 단위
    표기 `(m)`가 암묵 곱셈으로 `1*m`이 되어 함수식에 섞이는 것을 막는다.
    """
    candidate = text.strip().rstrip(".")
    # 짝 없는 여는 괄호 머리 제거 — `\( x^2 - 5x + 6 = 0 \)`의 왼쪽은 `( x^2 - 5x + 6`로 잘린다.
    while candidate.startswith("(") and candidate.count("(") > candidate.count(")"):
        candidate = candidate[1:].lstrip()
    for _ in range(_TRIM_ATTEMPTS):
        if not candidate:
            return None
        try:
            expr = safe_sympify(_normalize_math(candidate))
        except Exception:  # noqa: BLE001 — 발문 수식을 못 읽으면 다음 꼬리 자르기로(판정은 호출부)
            expr = None
        if isinstance(expr, sympy.Expr) and (
            allowed is None or {str(s) for s in expr.free_symbols} <= allowed
        ):
            return expr
        # 마지막 여는 괄호 또는 마지막 공백에서 자른다(`… + 3 (x` → `… + 3`).
        cut = max(candidate.rfind("("), candidate.rfind(" "))
        if cut <= 0:
            return None
        candidate = candidate[:cut].rstrip()
    return None


def _scan(text: str, start: int, step: int) -> str:
    """`start`에서 `step` 방향으로 수식 문자가 이어지는 구간을 잘라 낸다."""
    end = start
    while 0 <= end < len(text) and _MATH_CHAR.match(text[end]):
        end += step
    if step > 0:
        return text[start:end]
    return text[end + 1 : start + 1]


def _strip_open(text: str) -> str:
    """짝 없는 여는 괄호 머리 제거 — `( x^2 - 5x + 6`처럼 왼쪽 스캔이 괄호를 물고 온 경우."""
    out = text.strip()
    while out.startswith("(") and out.count("(") > out.count(")"):
        out = out[1:].lstrip()
    return out


def _preprocess_question(text: str) -> str:
    """LaTeX 표기를 평문 수식으로 — `$x^2$`의 `$`를 지우고 `x^{3}`의 중괄호를 괄호로.

    `\\( … \\)` 구분자는 따로 지우지 않는다 — 백슬래시가 수식 문자가 아니라 스캔이 거기서 멈추고,
    남는 짝 없는 여는 괄호는 `_strip_open`이 벗긴다(같은 일을 두 번 하는 절은 두지 않는다).
    """
    out = (text or "").replace("$", " ").replace("{", "(").replace("}", ")")
    return out


def _question_numbers(text: str) -> frozenset[sympy.Expr]:
    """발문에 적힌 수(절댓값) — 지수 자리(`x^3`의 3)는 수가 아니라 구조라서 뺀다."""
    found: set[sympy.Expr] = set()
    for match in re.finditer(r"(?<![\^\d.])(\d+(?:\.\d+)?(?:/\d+)?)", text):
        try:
            found.add(abs(sympy.nsimplify(match.group(1))))
        except (sympy.SympifyError, ValueError, TypeError, ZeroDivisionError):
            continue
    return frozenset(found)


def _is_assignment(lhs: sympy.Expr, rhs: sympy.Expr) -> bool:
    """`t = 3`처럼 기호 하나에 수를 지정하는 식 — 문제의 조건(점)이지 검산할 방정식이 아니다."""
    return (isinstance(lhs, sympy.Symbol) and not rhs.free_symbols) or (
        isinstance(rhs, sympy.Symbol) and not lhs.free_symbols
    )


def extract_question_relations(question_text: str) -> QuestionRelations:
    """발문 → 함수 정의·방정식·방정식 변수·발문 수. 못 읽은 관계는 건너뛴다(빈 결과 = UNKNOWN)."""
    functions: list[tuple[str, sympy.Expr]] = []
    defined: dict[str, tuple[str, sympy.Expr]] = {}
    equations: list[str] = []
    own_equations: list[str] = []
    variables: set[str] = set()
    text = _preprocess_question(question_text)
    blanked = list(text)  # 함수 정의 식을 지운 사본 — 그 밖의 수가 '점'이다
    for match in re.finditer(r"(?<![<>!=])=(?!=)", text):
        pos = match.start()
        lhs_span = _scan(text, pos - 1, -1)
        rhs_span = _scan(text, pos + 1, 1)
        lhs_raw = _strip_open(lhs_span)
        rhs_raw = _UNIT_TAIL.sub("", rhs_span.strip())
        if not lhs_raw or not rhs_raw:
            continue
        head = _FUNCTION_HEAD.match(lhs_raw)
        rhs = _parse_math(rhs_raw)
        if rhs is None:
            continue
        if head is not None or lhs_raw == "y":
            name, arg = (head.group(1), head.group(2)) if head is not None else ("y", "x")
            if arg.isalpha() and sympy.Symbol(arg) in rhs.free_symbols:
                # 함수 정의 `f(x) = …` — 매개변수(a·b)가 섞여도 된다.
                functions.append((arg, rhs))
                defined[name] = (arg, rhs)
                for i in range(pos - len(lhs_span), pos + 1 + len(rhs_span)):
                    blanked[i] = " "
                continue
            if name in defined:
                # 함수 적용 `f(a) = 10`·`f(1) = 0` — 정의된 함수에 인자를 넣은 방정식이다.
                var, body = defined[name]
                applied = body.subs(sympy.Symbol(var), _parse_math(arg) or sympy.Symbol(arg))
                lhs: sympy.Expr = sympy.expand(applied)
            else:
                continue
        else:
            parsed = _parse_math(lhs_raw)
            if parsed is None or _is_assignment(parsed, rhs):
                continue
            lhs = parsed
        residual = sympy.expand(lhs - rhs)
        if not residual.free_symbols:
            continue
        equation = f"{sympy.sstr(lhs)} = {sympy.sstr(rhs)}"
        equations.append(equation)
        if head is None and lhs_raw != "y":
            own_equations.append(equation)
            # 방정식의 계수는 정규형(`own_equations`)이 담는다 — 점 집합에 다시 세지 않는다.
            for i in range(pos - len(lhs_span), pos + 1 + len(rhs_span)):
                blanked[i] = " "
        variables.update(str(s) for s in residual.free_symbols)
    return QuestionRelations(
        tuple(functions),
        tuple(equations),
        frozenset(variables),
        _question_numbers(text),
        _point_numbers("".join(blanked), functions),
        tuple(own_equations),
    )


# 부호 있는 수 — 앞이 숫자·문자·닫는 괄호면 이항 연산의 빼기라 부호로 읽지 않는다.
_SIGNED_NUMBER = re.compile(r"(?<![\^\d.A-Za-z)])(-?)\s*(\d+(?:\.\d+)?(?:/\d+)?)")
_NUMBER_TOKEN = r"-?\s*\d+(?:\.\d+)?(?:/\d+)?"
# 좌표쌍 `(a, b)` — 둘째 성분이 f(a)면 함수에서 유도되는 값이라 점 집합에 따로 세지 않는다.
_COORDINATE_PAIR = re.compile(rf"\(\s*({_NUMBER_TOKEN})\s*,\s*({_NUMBER_TOKEN})\s*\)")


def _as_number(token: str) -> sympy.Expr | None:
    try:
        return sympy.nsimplify(token.replace(" ", ""))
    except (sympy.SympifyError, ValueError, TypeError, ZeroDivisionError):
        return None


def _point_numbers(
    blanked: str, functions: Sequence[tuple[str, sympy.Expr]]
) -> frozenset[sympy.Expr]:
    """함수식·방정식 밖의 수(부호 포함) — 좌표쌍 `(a, f(a))`의 둘째 성분은 뺀다.

    같은 문항을 `x좌표가 2인 점`과 `점 (2, 3)`으로 다르게 적어도 같은 점 집합 {2}가 되게 한다.
    유도값은 **좌표쌍의 둘째 성분일 때만** 뺀다 — 어떤 수가 우연히 다른 수의 함숫값과 같다는 이유로
    지우면 `f(1)=3 … x=3인 점`의 진짜 점 3이 사라진다. 부호를 지키는 이유: `x=2`와 `x=-2`는
    다른 점이다.
    """
    text = blanked.replace("−", "-")
    derived_spans: list[tuple[int, int]] = []
    for pair in _COORDINATE_PAIR.finditer(text):
        first, second = _as_number(pair.group(1)), _as_number(pair.group(2))
        if first is None or second is None:
            continue
        for var, body in functions:
            try:
                image = sympy.simplify(body.subs(sympy.Symbol(var), first))
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            if sympy.simplify(image - second) == 0:
                derived_spans.append(pair.span(2))
                break
    numbers: set[sympy.Expr] = set()
    for match in _SIGNED_NUMBER.finditer(text):
        if any(start <= match.start(2) < end for start, end in derived_spans):
            continue
        value = _as_number(match.group(1) + match.group(2))
        if value is not None:
            numbers.add(value)
    return frozenset(numbers)


# ── 검산식 근거 판정 ─────────────────────────────────────────────────────
def _candidates(relations: QuestionRelations) -> list[tuple[sympy.Symbol, sympy.Expr]]:
    """대조 후보 — 함수 P와 그 1·2계 도함수(상수는 제외)."""
    out: list[tuple[sympy.Symbol, sympy.Expr]] = []
    for name, expr in relations.functions:
        var = sympy.Symbol(name)
        for order in range(3):
            derived = sympy.expand(sympy.diff(expr, var, order) if order else expr)
            if var in derived.free_symbols:
                out.append((var, derived))
    return out


def _symbolic_match(
    expr: sympy.Expr, candidates: Sequence[tuple[sympy.Symbol, sympy.Expr]]
) -> bool:
    """기호 부분식이 후보 하나의 상수배인가(0배 제외)."""
    for var, cand in candidates:
        if var not in expr.free_symbols:
            continue
        ratio = sympy.cancel(expr / cand)
        if not ratio.free_symbols and ratio != 0:
            return True
    return False


# 한 점의 출현 위치 상한 — 부분집합 시도가 2^N이라 N을 묶는다(문항 하나의 대입식은 이보다 짧다).
_MAX_OCCURRENCES = 8

_PositionKey = tuple[int, int, str]


def _key(node: ast.AST) -> _PositionKey:
    return (
        getattr(node, "col_offset", -1),
        getattr(node, "end_col_offset", -1),
        type(node).__name__,
    )


def _point_occurrences(node: ast.AST) -> dict[sympy.Expr, list[_PositionKey]]:
    """부분식에 나오는 '대입된 점' 후보 → 그 출현 위치들. 지수 자리는 구조라서 보지 않는다.

    `(-1)**3`의 -1처럼 음수 점은 `-(1)` 단항 노드 하나로 출현한다(양수 1의 출현과 따로 센다).
    """
    found: dict[sympy.Expr, list[_PositionKey]] = {}

    def add(value: sympy.Expr, sub: ast.AST) -> None:
        found.setdefault(value, []).append(_key(sub))

    def walk(sub: ast.AST) -> None:
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Pow):
            walk(sub.left)  # 지수(right)는 대입된 점이 아니다
            return
        if isinstance(sub, ast.Constant) and type(sub.value) in (int, float):
            add(sympy.nsimplify(sub.value), sub)
            return
        if (
            isinstance(sub, ast.UnaryOp)
            and isinstance(sub.op, ast.USub)
            and isinstance(sub.operand, ast.Constant)
            and type(sub.operand.value) in (int, float)
        ):
            add(-sympy.nsimplify(sub.operand.value), sub)
        for child in ast.iter_child_nodes(sub):
            walk(child)

    walk(node)
    return found


class _Substitute(ast.NodeTransformer):
    """지정한 위치의 노드를 변수 이름으로 바꾼다(그 점을 다시 변수로 되돌리기)."""

    def __init__(self, keys: frozenset[_PositionKey], name: str) -> None:
        self._keys = keys
        self._name = name

    def visit(self, node: ast.AST) -> ast.AST:
        if _key(node) in self._keys and isinstance(node, (ast.Constant, ast.UnaryOp)):
            return ast.copy_location(ast.Name(id=self._name, ctx=ast.Load()), node)
        visited: ast.AST = super().visit(node)
        return visited


def _structural_point(
    node: ast.AST,
    value: sympy.Expr,
    candidates: Sequence[tuple[sympy.Symbol, sympy.Expr]],
) -> sympy.Expr | None:
    """수치 부분식이 '후보 함수에 점 a를 대입한 식'이면 그 점 a, 아니면 None.

    값만 보면 `-2*1`(미리 구한 기울기 -2를 박은 식)이 P′(1) = -2와 우연히 같아 통과한다.
    그래서 a의 출현 중 일부를 변수로 되돌렸을 때 식이 **정확히** 후보(P·P′·P″)가 되는지 본다 —
    `(2**3 - 5*2 + 2)`는 앞의 두 2를 x로 되돌리면 `x**3 - 5*x + 2`가 된다(마지막 2는 상수항).
    """
    for point, positions in _point_occurrences(node).items():
        if len(positions) > _MAX_OCCURRENCES:
            continue
        for var, cand in candidates:
            if sympy.simplify(cand.subs(var, point) - value) != 0:
                continue  # 값이 다르면 구조를 볼 필요도 없다(값 일치는 필요조건)
            for size in range(1, len(positions) + 1):
                for chosen in combinations(positions, size):
                    rebuilt = _Substitute(frozenset(chosen), str(var)).visit(copy.deepcopy(node))
                    try:
                        expr = safe_sympify(ast.unparse(rebuilt))
                    except Exception:  # noqa: BLE001 — 되돌린 식을 못 읽으면 다음 조합으로
                        continue
                    if isinstance(expr, sympy.Expr) and sympy.expand(expr - cand) == 0:
                        return point
    return None


def _is_subs_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "subs"
    )


def _node_expr(text: str, node: ast.AST) -> sympy.Expr | None:
    segment = ast.get_source_segment(text, node)
    if not segment:
        return None
    try:
        expr = safe_sympify(segment)
    except Exception:  # noqa: BLE001 — 부분식 하나를 못 읽어도 다른 부분식으로 계속
        return None
    return expr if isinstance(expr, sympy.Expr) else None


def _grounded_nodes(
    text: str, tree: ast.AST, candidates: Sequence[tuple[sympy.Symbol, sympy.Expr]]
) -> tuple[set[int], set[sympy.Expr]]:
    """근거 부분식(문항 함수를 계산하는 가장 바깥 노드)의 id 집합과 그 대입 점들."""
    grounded: set[int] = set()
    points: set[sympy.Expr] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.BinOp, ast.UnaryOp, ast.Call)):
            if _is_subs_call(node):
                assert isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                receiver = _node_expr(text, node.func.value)
                if receiver is not None and _symbolic_match(receiver, candidates):
                    grounded.add(id(node))  # `(P).subs(x, 2)` — 대입 인자까지 근거로 본다
                    return
            expr = _node_expr(text, node)
            if expr is not None:
                if expr.free_symbols:
                    if _symbolic_match(expr, candidates):
                        grounded.add(id(node))
                        return
                else:
                    point = _structural_point(node, expr, candidates)
                    if point is not None:
                        grounded.add(id(node))
                        points.add(abs(point))
                        return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return grounded, points


def _stray_literals(tree: ast.AST, grounded: set[int]) -> list[sympy.Expr]:
    """근거 부분식 밖의 수 리터럴(절댓값) — 지수 자리는 구조라서 뺀다."""
    found: list[sympy.Expr] = []

    def visit(node: ast.AST) -> None:
        if id(node) in grounded:
            return
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            visit(node.left)
            return
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            found.append(abs(sympy.nsimplify(node.value)))
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return found


# 근거 부분식 밖에 있어도 되는 수 — 항등 연산(`1*`·`+ 0`)과 개수 문항의 경계 보정(`- 1`).
_NEUTRAL_NUMBERS: frozenset[sympy.Expr] = frozenset({sympy.Integer(0), sympy.Integer(1)})


def _condition_grounding(
    condition: str,
    candidates: Sequence[tuple[sympy.Symbol, sympy.Expr]],
    question_numbers: frozenset[sympy.Expr],
) -> str | None:
    """등식 하나의 근거 판정 — 근거가 있으면 None, 없으면 사유.

    근거 = 문항 함수를 계산하는 부분식이 하나 이상 있고, **그 밖의 수는 모두 발문에 적힌 수·대입
    점·0·1뿐**이다. 둘째 조건이 없으면 `(f(2) 대입식) - (-3)*2`처럼 기울기 -3을 박은 식이나
    `0*(f(2) 대입식) + 12`처럼 정답을 더한 식이 근거 부분식 하나 덕분에 통과한다.
    """
    grounded: set[int] = set()
    points: set[sympy.Expr] = set()
    trees: list[ast.AST] = []
    for side in _relation_sides(condition):
        # `^`를 먼저 바꾼 문자열을 파싱·잘라내기 양쪽에 쓴다 — 오프셋이 같은 원문을 가리키게.
        text = side.strip().replace("^", "**")
        try:
            safe_sympify(text)  # 안전 진입점의 허용 문자·예산 검사를 먼저 통과해야 한다
            tree = ast.parse(text, mode="eval").body
        except Exception:  # noqa: BLE001 — 못 읽은 변은 근거 없음
            return "검산식을 읽지 못함"
        side_grounded, side_points = _grounded_nodes(text, tree, candidates)
        grounded |= side_grounded
        points |= side_points
        trees.append(tree)
    if not grounded:
        return "문항 함수를 계산하는 부분식이 없다"
    allowed = _NEUTRAL_NUMBERS | question_numbers | points
    stray = sorted(
        {n for tree in trees for n in _stray_literals(tree, grounded)} - allowed, key=str
    )
    if stray:
        return f"발문에 없는 수 {[str(n) for n in stray]}를 박았다(중간값·정답 하드코딩)"
    return None


def _condition_list(conditions: str | Sequence[str]) -> list[str]:
    return [conditions] if isinstance(conditions, str) else list(conditions)


def _is_equation(condition: str) -> bool:
    try:
        _, op = _parse_condition(condition)
    except Exception:  # noqa: BLE001 — 못 읽은 조건은 등식으로 취급해 근거 판정에서 거부되게
        return True
    return op == "=="


def grounding_verdict(
    question_text: str,
    conditions: str | Sequence[str],
    answer_map: Mapping[str, str],
) -> GroundingVerdict:
    """검산식이 문항을 다시 계산하는가 — 모듈 docstring의 4상태 판정.

    순서: 근거 판정이 먼저다. 근거가 있으면 재진술 판정기(EOS-207)의 결과와 무관하게 통과한다 —
    그 판정기는 0·1 리터럴을 버리므로 `4*1`(f′(1), f′(x) = 4x)처럼 점이 1인 정당한 대입식을
    재진술로 읽는다. 근거가 없을 때만 재진술 여부로 사유를 가른다.
    """
    items = _condition_list(conditions)
    equations = [c for c in items if _is_equation(c)]
    relations = extract_question_relations(question_text)
    bypassed = bool(answer_map) and (
        classify_verify_bypass({"conditions": items, "answer_map": dict(answer_map)}).bypassed
        is True
    )
    if relations.empty or not equations:
        if bypassed:
            return GroundingVerdict(GroundingState.RESTATEMENT, "검산식 우회(EOS-207)")
        return GroundingVerdict(GroundingState.UNKNOWN, "발문 수식 또는 검산 등식이 없음")
    question_forms = {canonical_condition(eq) for eq in relations.equations} - {None}
    candidates = _candidates(relations)
    reasons: list[str] = []
    for condition in equations:
        if canonical_condition(condition) in question_forms:
            continue  # 발문의 방정식 그대로(근 문항)
        reason = _condition_grounding(condition, candidates, relations.numbers)
        if reason is not None:
            reasons.append(f"{condition!r}: {reason}")
    if not reasons:
        return GroundingVerdict(GroundingState.GROUNDED, "모든 검산 등식이 문항을 다시 계산한다")
    if bypassed:
        return GroundingVerdict(GroundingState.RESTATEMENT, "검산식 우회(EOS-207)")
    return GroundingVerdict(GroundingState.UNGROUNDED, "; ".join(reasons))


# ── 정답 키 정규화 ───────────────────────────────────────────────────────
def normalize_answer_key(
    question_text: str,
    conditions: str | list[str],
    answer_map: Mapping[str, str],
) -> tuple[str | list[str], dict[str, str]]:
    """답이 근이 아닌 문항의 정답 키를 `answer`로 고정한다.

    정답 변수가 **발문 방정식의 변수**(근을 묻는 `x^2 - 6x + 8 = 0`의 `x` 등)면 그대로 둔다 — 그
    이름을 바꾸면 검산식이 발문의 방정식과 갈라진다. 그 밖(`b`·`v`·`M` 등 모델이 지은 이름)은 검산식
    원문과 치환맵 양쪽에서 `answer`로 바꾼다. 이름만 바뀌고 식의 의미는 같다.
    """
    if len(answer_map) != 1:
        return conditions, dict(answer_map)
    ((var, value),) = answer_map.items()
    relations = extract_question_relations(question_text)
    if var == ANSWER_KEY or relations.empty or var in relations.variables:
        # 근을 묻는 방정식의 변수면 유지. 발문을 못 읽었으면(empty) 근 변수인지 모른다 — 유지.
        return conditions, dict(answer_map)
    pattern = re.compile(rf"(?<![A-Za-z0-9_.]){re.escape(var)}(?![A-Za-z0-9_])")
    items = _condition_list(conditions)
    if any(re.search(rf"(?<![A-Za-z0-9_.]){ANSWER_KEY}(?![A-Za-z0-9_])", c) for c in items):
        return conditions, dict(answer_map)  # `answer`가 이미 다른 뜻으로 쓰임 — 바꾸지 않는다
    renamed = [pattern.sub(ANSWER_KEY, c) for c in items]
    new_conditions: str | list[str] = renamed[0] if isinstance(conditions, str) else renamed
    return new_conditions, {ANSWER_KEY: value}


# ── 단원 코드 ────────────────────────────────────────────────────────────
def standard_unit_codes(achievement_standard_codes: Sequence[str]) -> list[str]:
    """성취기준 코드 → 단원 코드(대괄호를 벗긴 표준 표기). `[12미적Ⅰ-02-05]` → `12미적Ⅰ-02-05`.

    LLM이 지은 단원 코드(`CALC1-TANGENT` 등)를 읽지 않고 스펙의 성취기준에서 유도한다 — 저작권
    메타를 LLM과 무관하게 박는 것과 같은 원리(구조적 강제)다.
    """
    codes: list[str] = []
    for code in achievement_standard_codes:
        stripped = code.strip().strip("[]").strip()
        if stripped and stripped not in codes:
            codes.append(stripped)
    return codes


# ── 교육과정 범위 밖 방법 ───────────────────────────────────────────────
# (성취기준 코드 접두, 금지 표현 정규식, 사유). 2022 개정 미적분Ⅰ은 이계도함수를 다루지 않는다
# (이계도함수·변곡점은 미적분Ⅱ) — 극대·극소는 f′의 부호 변화로 판정한다(EOS-197 수정승인 2건).
_METHOD_SCOPE: tuple[tuple[tuple[str, ...], re.Pattern[str], str], ...] = (
    (
        ("12미적Ⅰ", "12미적I-"),
        re.compile(
            r"이계\s*도함수|이차\s*도함수|2계\s*도함수|두\s*번\s*미분|second\s+derivative"
            r"|[A-Za-z]\s*(?:''|″|′′|\")\s*\(|\\prime\s*\\prime"
            r"|d\s*\^?\s*2\s*[a-z]\s*/\s*d\s*[a-z]\s*\^?\s*2",
            re.IGNORECASE,
        ),
        "미적분Ⅰ 범위 밖 — 이계도함수(f″) 대신 f′의 부호 변화로 판정해야 한다",
    ),
)


def curriculum_method_violation(
    achievement_standard_codes: Sequence[str], texts: Iterable[str | None]
) -> str | None:
    """성취기준 범위 밖 방법을 쓰면 사유를, 아니면 None.

    범위 표가 없는 성취기준은 검사하지 않는다.
    """
    body = "\n".join(t for t in texts if t)
    if not body:
        return None
    for prefixes, pattern, reason in _METHOD_SCOPE:
        if not any(p in code for p in prefixes for code in achievement_standard_codes):
            continue
        if pattern.search(body):
            return reason
    return None
