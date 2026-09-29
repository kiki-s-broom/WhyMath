"""학생 입력 수식의 CAS 파싱 *단일 안전 진입점* — 코딩 헌법 R22-03 집행 장치(CONST-09).

R22-03: "학생 입력 수식은 허용 문자 검사를 통과한 뒤에만 CAS로 파싱한다." 이 모듈 밖에서
`sympify`·`parse_expr`·`parse_latex`를 직접 부르는 것은 거버넌스 테스트
(`tests/infra/test_cas_parse_entrypoint_governance.py`)가 막는다 — 허용목록에 사유를 적은
신뢰 입력(코드 상수·저작 코퍼스를 읽는 오프라인 도구)만 예외다.

**왜 필요한가(재현 실측 2026-09-29 · 진단 기준선 BL-004)** — 학생 답이 닿는 경로
(`verify_answer`·`verify_step`·`verify_final_answer`·시도 오개념 훑기·OCR 파싱 검사)에서:
  - 다섯 글자 `9^9^9`·`9**9**9`가 20초 timeout까지 끝나지 않았다(≈3억 7천만 자리 정수 계산).
  - `(10^9)!`·`(x+y+z+w+v)^60`(전개 폭발)·`x^99+x+1=0`(고차 방정식 풀이)·조건 `y = 2^x`에 답
    `x = 10^100` 대입도 같은 부류로 멈췄다.
  - **허용 문자만으로도 임의 코드가 실행됐다.** `exec(chr(111)+chr(112)+…)`는 영문 소문자·숫자·
    괄호·`+`만 쓰는데, SymPy 파서는 내부적으로 `eval`을 쓰고 그 전역 이름공간에 파이썬 내장
    함수(`exec`·`chr`·`open`·`__import__`)를 싣기 때문에 그대로 실행된다(재현: 마커 파일 생성).
    그래서 이 모듈의 허용목록은 *문자*에서 끝나지 않고 *식별자* 단위까지 내려간다.

**집행 순서(모든 진입점 공통)**
  ① 길이 상한 ② 허용 문자 ③ 토큰 검사 — 숫자 리터럴 자릿수·과학표기 지수·괄호 중첩 깊이·
     식별자 허용목록(수학 함수·상수·자유 기호만. 파이썬 내장·그 밖의 SymPy 이름·키워드·밑줄로
     시작하는 이름은 거부)·속성 접근은 `.doit`·`.subs`만
  ④ 구조 파싱 — 모든 함수가 *평가되지 않는* 비활성 이름공간 + `evaluate=False` + 전역
     `evaluate(False)`로, 식을 **계산 없이** 나무로만 만든다
  ⑤ 예산 검사 — 노드 수·정수 비트·거듭제곱 결과 크기·다항 차수·전개 항 수·계승/이항계수 인자·
     미분 차수(모두 결정론적 상한 — 이 상한이 곧 시간 예산이다)
  ⑥ 실제 파싱 — 호출부가 쓰던 파서·옵션을 **그대로** 쓴다(정상 입력의 판정이 바뀌지 않게)
  ⑦ 계산 후 재검사 — `(x^99)^99`는 계산하면 `x^9801`이 되고, 곱·`.subs()`·함수 평가도 구조
     검사 뒤에 값을 키울 수 있다
  ⑧ 경과 시간 기록 — 예산(`PARSE_TIME_BUDGET_S`)을 넘으면 경고 로그만 남긴다. 벽시계로 판정을
     바꾸면 같은 입력의 판정이 기계 부하에 따라 달라져 결정론이 깨지므로 판정에는 쓰지 않는다.
     `signal.alarm`은 쓰지 않는다 — FastAPI는 동기 처리기를 작업자 스레드에서 돌리고, 알람은
     주 스레드에서만 동작한다. 선점형 중단 대신 ④⑤의 구조 상한이 계산 비용 자체를 묶는다.

**거부 경로** — 거부는 `UnsafeExpressionError`(`sympy.SympifyError` 하위 → `ValueError`)로 낸다.
기존 호출부는 이미 파싱 실패를 `unverifiable`/`parse_error`로 보수 처리하므로 거부된 입력은 새
응답 필드 없이 그 경로로 흘러간다(학생 화면은 기존 `parse_error` 분기 문구 — "읽지 못한 단계가
있어요 — 표기를 한 번 확인해볼까요?" — 를 그대로 쓴다). 예외 메시지·로그에는 학생 원문을 싣지
않고 사유 코드만 싣는다(미성년 PII·로그 노출 방지).

**알려진 과잉 거부** — 이항 연산이 수백 개 이어진 초장식(`x+x+…` 약 400항 이상)은 길이 상한
안이어도 구조 파싱(`evaluate=False`)이 파이썬 재귀 한도로 실패해 거부된다(원 파서도 `evaluate=False`
모드에서는 같은 이유로 실패한다). 실측 입력 최장 75자라 학생 입력과는 거리가 멀다.

**정직 스코프** — 이 모듈이 묶는 것은 *파싱과 파싱 직후 구조*다. 파싱을 통과한 식에 대한 하류
`simplify`·`solve`의 비용은 여기서 정한 차수·전개 항 수 상한으로 간접적으로만 묶인다.
"""

from __future__ import annotations

import builtins
import keyword
import logging
import math
import re
import time
import types
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import sympy
from sympy.core.parameters import evaluate as _evaluate_context
from sympy.parsing.sympy_parser import convert_xor as _t_convert_xor
from sympy.parsing.sympy_parser import (
    implicit_multiplication as _t_implicit_multiplication,
)
from sympy.parsing.sympy_parser import parse_expr as _sympy_parse_expr
from sympy.parsing.sympy_parser import standard_transformations as _standard_transformations

__all__ = [
    "MAX_BINOMIAL_N",
    "MAX_DERIVATIVE_ORDER",
    "MAX_EXPANSION_TERMS",
    "MAX_FACTORIAL_ARG",
    "MAX_FLOAT_EXPONENT",
    "MAX_INPUT_LENGTH",
    "MAX_INTEGER_BITS",
    "MAX_LITERAL_DIGITS",
    "MAX_NESTING_DEPTH",
    "MAX_POLY_DEGREE",
    "MAX_TREE_DEPTH",
    "MAX_TREE_NODES",
    "PARSE_TIME_BUDGET_S",
    "UnsafeExpressionError",
    "ensure_within_budget",
    "safe_parse_expr",
    "safe_parse_latex",
    "safe_subs",
    "safe_sympify",
]

logger = logging.getLogger("whymath.l3.safe_parse")

# ── 상한(결정론 예산) ─────────────────────────────────────────────────────────────
# 값은 2026-09-29 실측으로 정했다: 기존 테스트 스위트(backend 14,887건 + corpus_authoring
# 509건)가 CAS 파서에 넣은 입력 680,211건을 수집해 보니 최장 75자·리터럴 최대 17자리·괄호
# 중첩 최대 4·기호 밑 지수 최대 5(저작 코퍼스 최대 12)였다. 상한은 그 위로 충분한 여유를
# 두고, 적대 입력(재현표)은 전부 걸리도록 잡았다.

MAX_INPUT_LENGTH = 1000
"""파서에 넘기는 문자열 길이 상한(자). API 진입 상한(4000자)보다 좁다 — 실측 최장 75자."""

MAX_LITERAL_DIGITS = 100
"""숫자 리터럴 하나의 가수 자릿수 상한. 5000자리 리터럴 같은 입력을 파서 전에 끊는다."""

MAX_FLOAT_EXPONENT = 308
"""과학표기 지수(`1e308`)의 절댓값 상한 — 배정밀도 범위. `floor(1e999999)` 같은 우회 차단."""

MAX_NESTING_DEPTH = 30
"""괄호(`([{`) 중첩 깊이 상한. 실측 최대 4."""

MAX_TREE_NODES = 2000
"""식 나무의 (서로 다른) 노드 수 상한 — 예산 검사 자체의 비용도 이 값으로 묶인다."""

MAX_TREE_DEPTH = 60
"""식 나무 깊이 상한 — `x^x^x^…` 같은 탑이 하류 재귀(`simplify`·출력)를 깊게 만드는 것을 막는다."""

MAX_INTEGER_BITS = 10_000
"""정수(및 유리수 분자·분모)의 비트 수 상한(≈3,010자리). 1000!(8,530비트)·3^2024가 들어간다.
파이썬 정수→문자열 변환 한도(4,300자리)보다 작아 사유 문자열 조립이 터지지 않는다."""

MAX_POLY_DEGREE = 20
"""기호가 들어간 식의 (전체) 차수 상한. 실측 최대 12. 차수 20의 방정식 풀이가 ~1.3초,
30이 6~12초, 99는 20초 timeout이었다(`sympy.solve` 실측) — 하류 풀이 비용을 묶는 값이다."""

MAX_EXPANSION_TERMS = 500
"""완전 전개 시 항 수의 상한(다항 전개 `expand`의 비용 상한). `(x+y+z+w)^20`(1,771항 ≈0.5초)은
넘고 `(x+1)^20`·`(a+b+c)^10`(66항)은 들어간다."""

MAX_FACTORIAL_ARG = 1000
"""계승 인자 상한 — 결과 8,530비트로 `MAX_INTEGER_BITS` 안이다. `(10^9)!`은 20초 timeout이었다."""

MAX_BINOMIAL_N = 10_000
"""이항계수 `binomial(n, k)`의 n 상한."""

MAX_DERIVATIVE_ORDER = 10
"""`Derivative(f, x, n)`의 미분 차수 상한 — `.doit()`이 n번 미분하므로 비용이 n에 비례한다."""

PARSE_TIME_BUDGET_S = 0.2
"""관측용 시간 예산(초). 넘으면 경고 로그만 남긴다 — 판정 불변(결정론 유지·모듈 docstring ⑧)."""

# 과학표기 지수 한 개가 가질 수 있는 최대 크기의 로그2 — 이보다 큰 지수는 결과가 어떻든
# 계산 자체가 천문학적이다(2^64 ≈ 1.8×10^19).
_MAX_EXPONENT_LOG2 = 64.0

# ── 허용 문자·식별자 ───────────────────────────────────────────────────────────────
# sympify/parse_expr 경로의 ASCII 허용 문자. 따옴표(문자열 리터럴 → `S("…")` 우회)·`:`(lambda·
# 슬라이스)·`;`·`#`(주석으로 뒷부분 무시)·`@`·`\`·중괄호(집합·사전 리터럴)·`&|~`는 없다 — 실측
# 입력 68만 건에서 이 문자를 쓴 입력은 원 파서도 전부 실패했다. `%`(나머지)는 DSL 제약식
# (`(c - b) % a == 0`)이 쓴다. 유니코드 문자(한글·그리스 문자 등)는 `str.isalpha()`로 따로
# 허용한다: 현행 파서가 한글 단어를 기호로 읽어 판정(parse_error가 아닌 undecidable 등)이 그에
# 의존하는 테스트가 있다.
_ASCII_ALLOWED = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" " \t\n\r" "+-*/^()[].,=<>!_%"
)
# LaTeX 경로는 여기에 `\`·중괄호·`&`(정렬)·`~`(간격)·`|`(절댓값)·`'`(프라임)·`:`·`;`(간격 매크로
# `\;`·`\:`)을 더한다 — 파서가 파이썬 eval이 아닌 antlr 문법이라 따옴표가 문자열이 되지 않는다.
_LATEX_EXTRA_ALLOWED = frozenset("\\{}&~|':;")

# 허용 함수 — 저작 코퍼스·테스트 실측에 나온 이름 + 중·고교 표준 함수. 적분·급수·극한 계산
# (`integrate`·`Sum`·`limit`·`solve`·`diff`)은 없다: 기호 계산 비용이 입력 크기와 무관하게
# 폭발할 수 있다. `Integral`은 *평가하지 않은* 적분식이라 허용하되 `.doit()`과 같이 쓰면 거부한다.
_ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "cot",
        "sec",
        "csc",
        "asin",
        "acos",
        "atan",
        "acot",
        "sinh",
        "cosh",
        "tanh",
        "log",
        "ln",
        "exp",
        "sqrt",
        "cbrt",
        "root",
        "Abs",
        "abs",
        "sign",
        "floor",
        "ceiling",
        "gcd",
        "lcm",
        "factorial",
        "binomial",
        "Max",
        "Min",
        "max",
        "min",
        "Derivative",
        "Integral",
    }
)
# 관계 생성자 — 구조 파싱에서도 실물을 쓴다(전역 evaluate(False)로 평가가 봉인된다).
_RELATION_NAMES: frozenset[str] = frozenset({"Eq", "Ne", "Lt", "Le", "Gt", "Ge"})
# 상수 — 원자라 비용이 없다. True/False/None은 파이썬 키워드지만 값 상수다.
_ALLOWED_CONSTANTS: frozenset[str] = frozenset({"pi", "E", "I", "oo", "True", "False", "None"})
_ALLOWED_NAMES: frozenset[str] = _ALLOWED_FUNCTIONS | _RELATION_NAMES | _ALLOWED_CONSTANTS

# 속성 접근 허용목록 — 저작 코퍼스의 `Derivative(...).doit().subs(x, k)` 형태만.
_ALLOWED_ATTRIBUTES: frozenset[str] = frozenset({"doit", "subs"})
# `.doit()`과 같이 쓰면 기호 적분을 실제로 수행하게 되는 이름.
_HEAVY_DOIT_OPERATORS: frozenset[str] = frozenset({"Integral"})


def _build_bound_names() -> frozenset[str]:
    """SymPy 파서의 기본 전역 이름공간에 *이미 묶여 있는* 이름 — 자동 기호화되지 않는 이름.

    `parse_expr(global_dict=None)`은 `from sympy import *` + 파이썬 내장 함수(+`max`·`min`)를
    전역에 싣는다(sympy_parser 소스). 여기 있는 이름은 기호(Symbol)로 바뀌지 않고 *실물*로
    호출되므로, 허용목록에 없는 한 거부해야 한다(`exec`·`chr`·`open`·`var`·`test`·`preview` 등).
    """
    namespace: dict[str, Any] = {}
    exec(
        "from sympy import *", namespace
    )  # noqa: S102 — 파서와 같은 이름공간을 *재현*할 뿐(입력 아님)
    names = set(namespace)
    names.update(
        name for name, obj in vars(builtins).items() if isinstance(obj, types.BuiltinFunctionType)
    )
    names.update({"max", "min"})
    return frozenset(names)


_BOUND_NAMES: frozenset[str] = _build_bound_names()


class UnsafeExpressionError(sympy.SympifyError):  # type: ignore[misc]  # sympy 무타입
    """안전 파싱 거부 — 사유 코드만 싣는다(학생 원문은 예외·로그 어디에도 싣지 않는다).

    `sympy.SympifyError`(→ `ValueError`)의 하위 클래스라, 파싱 실패를 이미 잡는 기존 호출부의
    `except`(SympifyError·ValueError·Exception)가 그대로 받아 `unverifiable`/`parse_error`로
    보수 처리한다 — 거부 전용 응답 필드를 새로 만들지 않는다.
    """

    def __init__(self, code: str) -> None:
        super().__init__("안전 파싱 거부", None)
        self.code = code

    def __str__(self) -> str:
        return f"안전 파싱 거부({self.code})"


def _reject(code: str) -> UnsafeExpressionError:
    """거부 예외를 만들고 사유 코드를 로그에 남긴다(원문 미포함 — 침묵 실패 금지)."""
    logger.info("safe_parse 거부 — 사유=%s", code)
    return UnsafeExpressionError(code)


# ── ①②③ 문자열 검사 ────────────────────────────────────────────────────────────────
# 숫자 리터럴(정수·소수·과학표기·허수 접미사)을 이름보다 먼저 소비한다 — `2x`는 숫자 `2`와
# 이름 `x`로, `1e5`는 숫자 하나로 읽힌다. 이름은 유니코드 문자/밑줄로 시작한다.
_TOKEN_RE = re.compile(
    r"(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[jJ]?)|(?P<name>[^\W\d]\w*)",
    re.UNICODE,
)
# 속성 접근 — `.` 뒤(공백 허용)에 이름이 오는 자리. 소수점 뒤 숫자(`2.5`)는 해당하지 않는다.
_ATTRIBUTE_RE = re.compile(r"\.\s*(?P<attr>[^\W\d]\w*)", re.UNICODE)
_EXPONENT_PART_RE = re.compile(r"[eE]([+-]?\d+)")


def _screen_text(
    text: str,
    *,
    latex: bool = False,
    local_names: Iterable[str] = (),
) -> None:
    """①길이 ②허용 문자 ③토큰(자릿수·지수·중첩·식별자·속성)을 검사한다 — 위반이면 거부."""
    if len(text) > MAX_INPUT_LENGTH:
        raise _reject("too_long")
    extra = _LATEX_EXTRA_ALLOWED if latex else frozenset()
    for ch in text:
        if ch in _ASCII_ALLOWED or ch in extra:
            continue
        if not ch.isascii() and ch.isalpha():
            continue  # 유니코드 문자(한글·그리스 문자) — 이름의 일부로만 쓰인다.
        raise _reject("disallowed_char")

    depth = 0
    for ch in text:
        if ch in "([{":
            depth += 1
            if depth > MAX_NESTING_DEPTH:
                raise _reject("nesting_too_deep")
        elif ch in ")]}":
            depth -= 1

    if latex:
        # LaTeX 제어어(`\frac`·`\sqrt`)는 이름 검사 대상이 아니다 — 백슬래시 뒤 이름을 지운 뒤
        # 나머지 토큰만 본다. 식별자 허용은 평문 변환 후 구조 검사(⑤)에서 다시 걸린다.
        text = re.sub(r"\\[A-Za-z]+", " ", text)

    attributes = {
        unicodedata.normalize("NFKC", m.group("attr")) for m in _ATTRIBUTE_RE.finditer(text)
    }
    for attr in attributes:
        if attr not in _ALLOWED_ATTRIBUTES:
            raise _reject("disallowed_attribute")

    local = frozenset(local_names)
    names: set[str] = set()
    for match in _TOKEN_RE.finditer(text):
        number = match.group("num")
        if number is not None:
            mantissa, _, _ = number.rstrip("jJ").partition("e")
            mantissa = mantissa.partition("E")[0]
            if sum(ch.isdigit() for ch in mantissa) > MAX_LITERAL_DIGITS:
                raise _reject("literal_too_long")
            exponent = _EXPONENT_PART_RE.search(number)
            if exponent is not None and abs(int(exponent.group(1))) > MAX_FLOAT_EXPONENT:
                raise _reject("float_exponent_too_large")
            continue
        # 바로 앞(공백 제외)이 `.`이면 속성 이름 — 위에서 허용목록으로 따로 검사했다.
        if text[: match.start()].rstrip().endswith("."):
            continue
        names.add(unicodedata.normalize("NFKC", match.group("name")))

    for name in names:
        # 파이썬은 식별자를 NFKC로 정규화해 컴파일한다(`ｅｘｅｃ` → `exec`) — 정규화 후 판정한다.
        if name.startswith("_"):
            raise _reject("disallowed_name")
        if keyword.iskeyword(name) and name not in _ALLOWED_CONSTANTS:
            raise _reject("disallowed_name")
        if name in _ALLOWED_NAMES or name in local:
            continue
        if name in _BOUND_NAMES:
            raise _reject("disallowed_name")
        # 그 밖의 이름은 파서가 자유 기호(Symbol)나 미정의 함수로 만든다 — 실행할 실물이 없다.

    if "doit" in attributes and names & _HEAVY_DOIT_OPERATORS:
        raise _reject("heavy_operator_doit")


# ── ④ 구조 파싱(계산 없음) ─────────────────────────────────────────────────────────


def _build_inert_namespace() -> dict[str, Any]:
    """구조 파싱용 전역 이름공간 — 허용 함수가 전부 *미정의 함수*라 아무것도 계산하지 않는다.

    파서의 생성 코드가 참조하는 생성자(`Symbol`·`Integer`·`Float`·`Rational`·`Function`·`Add`·
    `Mul`·`Pow`·논리/관계)만 실물로 둔다 — 그 평가는 전역 `evaluate(False)`가 봉인한다. 내장
    함수는 비운다(`__builtins__ = {}`): 이 이름공간에서는 `exec`가 있어도 찾을 수 없다.
    """
    namespace: dict[str, Any] = {"__builtins__": {}}
    for name in (
        "Symbol",
        "Function",
        "Integer",
        "Float",
        "Rational",
        "Add",
        "Mul",
        "Pow",
        "And",
        "Or",
        "Not",
        "Lambda",
        *sorted(_RELATION_NAMES),
    ):
        namespace[name] = getattr(sympy, name)
    for name in ("pi", "E", "I", "oo"):
        namespace[name] = getattr(sympy, name)
    for name in sorted(_ALLOWED_FUNCTIONS | {"factorial2"}):
        namespace[name] = sympy.Function(name)
    return namespace


_INERT_NAMESPACE: dict[str, Any] = _build_inert_namespace()


def _structural_parse(
    text: str,
    *,
    transformations: tuple[Any, ...],
    local_dict: Mapping[str, Any] | None,
) -> Any:
    """④ 계산 없는 구조 파싱 — 실패하면 거부(구조를 확인하지 못한 입력은 계산하지 않는다)."""
    source = text.replace("\n", "").strip()
    try:
        with _evaluate_context(False):
            return _sympy_parse_expr(
                source,
                local_dict=dict(local_dict) if local_dict else {},
                transformations=transformations,
                global_dict=dict(_INERT_NAMESPACE),
                evaluate=False,
            )
    except UnsafeExpressionError:
        raise
    except Exception as exc:  # noqa: BLE001 — 구조를 못 읽은 입력은 거부(타입명만 로그)
        logger.info("safe_parse 구조 파싱 실패 — %s", type(exc).__name__)
        raise _reject("structure_unparseable") from None


# ── ⑤⑦ 예산 검사 ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _NodeInfo:
    """노드 하나의 비용 추정 — 수치 크기·차수·전개 항 수·깊이.

    `numeric`이면 기호가 없는 수치 노드이고, 그때만 `mag`(|값|의 log2 상한)와 `bits`(그 값을
    정수·유리수로 *정확히* 계산할 때 분자·분모가 가질 비트 수의 상한)가 의미를 갖는다.
    `degree`는 기호식의 (전체) 차수 상한, `terms`는 완전 전개 시 항 수 상한, `depth`는 나무 깊이.
    """

    numeric: bool
    mag: float
    bits: float
    degree: float
    terms: int
    depth: int
    upper: float


def _numeric(mag: float, bits: float, depth: int, upper: float | None = None) -> _NodeInfo:
    """수치 노드 정보(차수 0·항 1). `upper`는 |값|의 상한 — 원자는 정확값, 나머지는 2^mag."""
    if upper is None:
        upper = math.inf if mag > 1023 else float(2.0**mag)
    return _NodeInfo(
        numeric=True, mag=mag, bits=bits, degree=0.0, terms=1, depth=depth, upper=upper
    )


def _symbolic(degree: float, terms: int, depth: int) -> _NodeInfo:
    """기호 노드 정보(수치 크기 없음)."""
    return _NodeInfo(
        numeric=False, mag=0.0, bits=0.0, degree=degree, terms=terms, depth=depth, upper=0.0
    )


def _func_name(node: Any) -> str:
    """함수 노드의 이름 — 미정의 함수(구조 파싱)와 실물 클래스(계산 후) 양쪽에서 같은 이름."""
    func = getattr(node, "func", None)
    return str(getattr(func, "__name__", "")) if func is not None else ""


def _children(node: Any) -> tuple[Any, ...]:
    """자식 노드 — SymPy 식이면 args, 파이썬 컨테이너면 원소."""
    if isinstance(node, sympy.Basic):
        return tuple(node.args)
    if isinstance(node, (list, tuple, set, frozenset)):
        return tuple(node)
    if isinstance(node, dict):
        return tuple(node.keys()) + tuple(node.values())
    return ()


def _exponent_magnitude(info: _NodeInfo) -> float:
    """수치 지수의 |값| 상한 — 천문학적(2^64 초과)이면 거부.

    원자(정수·유리수)는 정확값을 쓴다 — `2^log2(20)`은 부동소수 오차로 20을 조금 넘어
    `(x+1)^20`을 차수 상한 초과로 잘못 거부했다(실측).
    """
    if info.mag > _MAX_EXPONENT_LOG2:
        raise _reject("exponent_too_large")
    return info.upper


def _multinomial_terms(power: int, base_terms: int) -> int:
    """(항 t개의 합)^n을 완전 전개한 항 수 C(n+t-1, t-1) — 상한을 넘는 순간 멈춘다.

    곱셈 순서상 중간값이 단조 증가하므로 상한 초과 즉시 반환해도 판정이 같다. 거대한 n·t에서
    `math.comb`를 끝까지 계산하는 비용(수만 자리 정수)을 피한다.
    """
    if base_terms < 2:
        return 1
    k = base_terms - 1
    count = 1
    for i in range(1, k + 1):
        count = count * (power + i) // i
        if count > MAX_EXPANSION_TERMS:
            return count
    return count


def _atom_info(node: Any) -> _NodeInfo:
    """원자(숫자·기호·상수)의 비용 정보 — 정수·유리수 비트 상한도 여기서 검사한다."""
    if isinstance(node, sympy.Symbol):
        return _symbolic(degree=1.0, terms=1, depth=1)
    if isinstance(node, sympy.Integer):
        value = abs(int(node.p))
        if value.bit_length() > MAX_INTEGER_BITS:
            raise _reject("integer_too_large")
        log2 = math.log2(value) if value > 1 else 0.0
        upper = float(value) if value.bit_length() <= 1023 else math.inf
        return _numeric(mag=log2, bits=log2, depth=1, upper=upper)
    if isinstance(node, sympy.Rational):
        p, q = abs(int(node.p)), int(node.q)
        if max(p.bit_length(), q.bit_length()) > MAX_INTEGER_BITS:
            raise _reject("integer_too_large")
        lp = math.log2(p) if p > 1 else 0.0
        lq = math.log2(q) if q > 1 else 0.0
        upper = p / q if max(p.bit_length(), q.bit_length()) <= 1023 else math.inf
        return _numeric(mag=max(0.0, lp - lq), bits=max(lp, lq), depth=1, upper=upper)
    if isinstance(node, sympy.Float):
        _sign, mantissa, exponent, bitcount = node._mpf_
        # |값| ≈ 2^(지수+비트수). 0이면 가수가 0이다.
        magnitude = float(exponent + bitcount) if mantissa else 0.0
        if abs(magnitude) > MAX_INTEGER_BITS:
            raise _reject("integer_too_large")
        return _numeric(mag=max(0.0, magnitude), bits=abs(magnitude), depth=1)
    if isinstance(node, sympy.NumberSymbol):
        return _numeric(mag=2.0, bits=2.0, depth=1)  # pi·E 등 |값| < 4
    # I·oo·zoo·nan·참/거짓 원자·파이썬 None 등 — 비용 없는 원자.
    return _numeric(mag=0.0, bits=0.0, depth=1)


def _pow_info(base: _NodeInfo, exponent: _NodeInfo, depth: int) -> _NodeInfo:
    """거듭제곱 — 폭발의 1차 원천. 수치 밑은 결과 비트, 기호 밑은 차수·전개 항 수를 본다."""
    if not exponent.numeric:
        # 기호 지수(2^x 등) — 대입 전에는 값이 없다(대입 폭발은 `safe_subs`가 막는다).
        return _symbolic(degree=base.degree, terms=base.terms, depth=depth)
    e_up = _exponent_magnitude(exponent)
    if base.numeric:
        bits = base.bits * e_up  # ±1·0·I는 bits 0 → 지수와 무관하게 0
        if bits > MAX_INTEGER_BITS:
            raise _reject("power_too_large")
        return _numeric(mag=bits, bits=bits, depth=depth)
    degree = base.degree * e_up
    if degree > MAX_POLY_DEGREE:
        raise _reject("degree_too_high")
    terms = _multinomial_terms(max(1, math.ceil(e_up)), base.terms)
    return _symbolic(degree=degree, terms=terms, depth=depth)


def _function_info(node: Any, kids: list[_NodeInfo], depth: int) -> _NodeInfo | None:
    """이름으로 식별하는 함수(계승·이항·exp·미분) 검사 — 해당 없으면 None."""
    name = _func_name(node)
    first = kids[0] if kids else None
    if name in ("factorial", "factorial2") and first is not None and first.numeric:
        n = first.upper
        if n > MAX_FACTORIAL_ARG:
            raise _reject("factorial_too_large")
        bits = n * math.log2(max(n, 2.0))
        return _numeric(mag=bits, bits=bits, depth=depth)
    if name == "binomial" and first is not None and first.numeric:
        n = first.upper
        if n > MAX_BINOMIAL_N:
            raise _reject("binomial_too_large")
        if all(k.numeric for k in kids):
            return _numeric(mag=n, bits=n, depth=depth)
    if name == "exp" and first is not None and first.numeric:
        # exp(a) = E^a — 거듭제곱과 같은 크기 검사(`exp(10^6)`는 E^1000000).
        bits = math.log2(math.e) * _exponent_magnitude(first)
        if bits > MAX_INTEGER_BITS:
            raise _reject("power_too_large")
        return _numeric(mag=bits, bits=bits, depth=depth)
    if name == "Derivative":
        _check_derivative_order(node)
    return None


def _combine(node: Any, kids: list[_NodeInfo]) -> _NodeInfo:
    """자식 정보로 노드 정보를 만들고 폭발 원천(거듭제곱·계승·이항·미분 차수)을 검사한다."""
    depth = 1 + max(k.depth for k in kids)
    numeric = all(k.numeric for k in kids)
    degree_max = max(k.degree for k in kids)

    if isinstance(node, sympy.Pow):
        return _pow_info(kids[0], kids[1], depth)

    if isinstance(node, (sympy.Add, sympy.core.relational.Relational)):
        if numeric:
            mag = max(k.mag for k in kids) + math.log2(len(kids))
            return _numeric(mag=mag, bits=sum(k.bits for k in kids), depth=depth)
        return _symbolic(degree=degree_max, terms=sum(k.terms for k in kids), depth=depth)

    if isinstance(node, sympy.Mul):
        if numeric:
            return _numeric(
                mag=sum(k.mag for k in kids), bits=sum(k.bits for k in kids), depth=depth
            )
        return _symbolic(
            degree=sum(k.degree for k in kids), terms=math.prod(k.terms for k in kids), depth=depth
        )

    special = _function_info(node, kids, depth)
    if special is not None:
        return special
    if numeric:
        # 그 밖의 수치 함수(sin·log·sqrt·floor·gcd·Max …) — 크기는 인자 크기 수준으로 본다.
        mag = max(k.mag for k in kids) + 1.0
        return _numeric(mag=mag, bits=sum(k.bits for k in kids) + 1.0, depth=depth)
    return _symbolic(degree=degree_max, terms=1, depth=depth)


def _check_derivative_order(node: Any) -> None:
    """`Derivative`의 미분 차수(정수 인자·`(x, n)` 쌍의 n)가 상한 안인지 검사한다."""
    for arg in node.args[1:]:
        candidates = arg.args[1:] if isinstance(arg, sympy.Tuple) else (arg,)
        for candidate in candidates:
            if isinstance(candidate, sympy.Integer) and abs(int(candidate)) > MAX_DERIVATIVE_ORDER:
                raise _reject("derivative_order_too_large")


def _check_tree(root: Any) -> None:
    """⑤⑦ 예산 검사 — 반복 후위 순회(재귀 한도 무관)로 노드마다 비용을 추정·검사한다.

    같은 객체가 여러 번 나와도(공유 부분식) 한 번만 계산한다. 순회 중 노드를 `pinned`에 붙잡아
    `id()` 재사용을 막는다.
    """
    info: dict[int, _NodeInfo] = {}
    pinned: list[Any] = []
    stack: list[tuple[Any, bool]] = [(root, False)]
    while stack:
        node, expanded = stack.pop()
        key = id(node)
        if key in info:
            continue
        if not expanded:
            pinned.append(node)
            if len(pinned) > 2 * MAX_TREE_NODES:
                raise _reject("too_many_nodes")
            stack.append((node, True))
            stack.extend((child, False) for child in _children(node) if id(child) not in info)
            continue
        children = _children(node)
        node_info = (
            _combine(node, [info[id(c)] for c in children]) if children else _atom_info(node)
        )
        if node_info.degree > MAX_POLY_DEGREE:
            raise _reject("degree_too_high")
        if node_info.terms > MAX_EXPANSION_TERMS:
            raise _reject("expansion_too_large")
        if node_info.depth > MAX_TREE_DEPTH:
            raise _reject("tree_too_deep")
        info[key] = node_info
        if len(info) > MAX_TREE_NODES:
            raise _reject("too_many_nodes")


# ── 공개 진입점 ────────────────────────────────────────────────────────────────────


def _contains_text(value: Any) -> bool:
    """컨테이너 안에 문자열이 있는가 — `sympify(["9**9**9"])`는 원소를 그대로 파싱한다."""
    if isinstance(value, str):
        return True
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_text(v) for v in value)
    if isinstance(value, dict):
        return any(_contains_text(k) or _contains_text(v) for k, v in value.items())
    return False


def _timed(entry: str, started: float) -> None:
    """⑧ 관측 — 시간 예산 초과는 경고 로그만(판정 불변·결정론)."""
    elapsed = time.perf_counter() - started
    if elapsed > PARSE_TIME_BUDGET_S:
        logger.warning("safe_parse 시간 예산 초과(관측) — 진입점=%s 경과=%.3fs", entry, elapsed)


def ensure_within_budget(value: Any) -> Any:
    """⑦ 이미 만들어진 SymPy 값(파이썬 수 포함)을 `sympify`해 예산 검사 후 돌려준다.

    `sympy.sympify(lhs - rhs)`·`sympy.sympify(expr.subs(...))`처럼 *문자열이 아닌* 값을 다시
    감싸던 자리의 대체다 — 결과는 `sympy.sympify(value)`와 같고, 계산이 키운 값(`x^9801`·거대
    정수)이면 거부한다. 문자열이면 `safe_sympify`로 보낸다(문자열을 여기서 파싱하지 않는다).
    """
    if isinstance(value, str):
        return safe_sympify(value)
    if _contains_text(value):
        raise _reject("not_text")
    result = sympy.sympify(value)
    _check_tree(result)
    return result


def safe_sympify(text: Any, *, convert_xor: bool = True, evaluate: bool = True) -> Any:
    """`sympy.sympify(text, convert_xor=…, evaluate=…)`의 안전판 — 결과는 원 호출과 같다.

    문자열이 아니면(SymPy 값·파이썬 수) `ensure_within_budget`과 같이 처리한다.
    """
    if not isinstance(text, str):
        return ensure_within_budget(text)
    started = time.perf_counter()
    _screen_text(text)
    transformations = _standard_transformations + ((_t_convert_xor,) if convert_xor else ())
    _check_tree(_structural_parse(text, transformations=transformations, local_dict=None))
    result = sympy.sympify(text, convert_xor=convert_xor, evaluate=evaluate)
    _check_tree(result)
    _timed("sympify", started)
    return result


def safe_parse_expr(
    text: str,
    *,
    transformations: tuple[Any, ...],
    local_dict: Mapping[str, Any] | None = None,
    evaluate: bool = True,
) -> Any:
    """`parse_expr(text, local_dict=…, transformations=…, evaluate=…)`의 안전판.

    `local_dict`의 이름은 호출부가 명시한 값이라 식별자 허용목록 검사에서 통과시킨다(값 자체는
    구조 검사가 본다 — 바인딩 값이 거대 정수면 거부된다).
    """
    started = time.perf_counter()
    if not isinstance(text, str):
        raise _reject("not_text")
    _screen_text(text, local_names=tuple(local_dict or ()))
    _check_tree(_structural_parse(text, transformations=transformations, local_dict=local_dict))
    result = _sympy_parse_expr(
        text,
        local_dict=local_dict,  # 원 호출과 같은 객체를 넘긴다(복사 없음 — 동작 동일)
        transformations=transformations,
        evaluate=evaluate,
    )
    _check_tree(result)
    _timed("parse_expr", started)
    return result


def safe_parse_latex(text: str, *, plain: Callable[[str], str]) -> Any:
    """`sympy.parsing.latex.parse_latex(text)`의 안전판.

    LaTeX 파서(antlr)는 이 모듈의 비활성 이름공간을 쓸 수 없으므로, 호출부가 주는 평문 변환
    `plain`(L3 `latex_to_plain`)으로 같은 식을 평문으로 바꿔 ③④⑤를 **먼저** 통과시킨다. 평문으로
    구조를 확인하지 못하면 LaTeX 파서도 부르지 않는다(확인 못 한 식은 계산하지 않는다). 파서가
    없으면(antlr 미설치) 원래대로 `ImportError`류가 호출부로 올라간다. 결과는 ⑦로 재검사한다.
    """
    started = time.perf_counter()
    if not isinstance(text, str):
        raise _reject("not_text")
    _screen_text(text, latex=True)
    plain_text = plain(text)
    _screen_text(plain_text)
    # LaTeX는 병치 곱(`\frac{1}{2}x`·`2x`)이 표준이라 사전 검사는 암묵곱 변환으로 읽는다 —
    # 동치 권위(`identity_status`)의 평문 파싱과 같은 관례다.
    transformations = _standard_transformations + (_t_implicit_multiplication, _t_convert_xor)
    _check_tree(_structural_parse(plain_text, transformations=transformations, local_dict=None))
    from sympy.parsing.latex import parse_latex  # 지연 import — antlr 의존이 선택적이다

    result = parse_latex(text)
    _check_tree(result)
    _timed("parse_latex", started)
    return result


def safe_subs(expr: Any, substitutions: Mapping[Any, Any]) -> Any:
    """`sympy.sympify(expr.subs(substitutions))`의 안전판 — 대입 *전에* 폭발을 막는다.

    대입은 곧바로 계산한다: 조건 `2^x`에 `x = 10^100`을 넣으면 `subs` 안에서 2^(10^100)을
    구하다 멈춘다(재현표). 그래서 먼저 전역 `evaluate(False)` 아래 `xreplace`로 *계산 없는* 대입
    결과를 만들어 ⑤를 통과시킨 뒤에야 실제 `subs`를 부른다. 결과는 ⑦로 재검사한다.
    """
    mapping = dict(substitutions)
    try:
        with _evaluate_context(False):
            preview = expr.xreplace(mapping)
    except UnsafeExpressionError:
        raise
    except Exception as exc:  # noqa: BLE001 — 계산 없는 대입을 못 만들면 거부(타입명 로그)
        logger.info("safe_parse 대입 미리보기 실패 — %s", type(exc).__name__)
        raise _reject("substitution_unverifiable") from None
    _check_tree(preview)
    return ensure_within_budget(expr.subs(mapping))
