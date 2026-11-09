"""골든 패스 정답 판정(GP-5) — SymPy로 학생 답과 정답을 비교한다.

규칙(공유 계약):
- 정규화: 공백 제거, `답:`·`y=`·`f(x)=` 접두와 `입니다` 꼬리 제거,
  전각 숫자·기호와 `−`(U+2212)를 반각으로.
- `answer_kind == "number"`: SymPy `nsimplify`로 바꾼 두 수의 차이가 1e-9 이하면 정답(1.5 = 3/2).
- `answer_kind == "expression"`: `simplify(student - answer) == 0`이면 정답. `2x+1`처럼 곱셈 기호를
  생략해도 읽는다(implicit multiplication).
- 파싱 실패는 오답이다. 예외를 삼키지 않고 예외 타입명을 로그에 남긴다.

부분 점수·풀이 과정 채점·오류 유형 분류는 하지 않는다(지시서 '하지 말 것').
"""

from __future__ import annotations

import logging
import re
import unicodedata

import sympy
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    standard_transformations,
)

from golden.problems import Problem

# 학생 입력 파싱은 옛 코드의 단일 안전 진입점으로만 한다(코딩 헌법 R22-03 · HARVEST.md).
# `9^9^9` 같은 거대 계산·파서 내부 eval을 통한 코드 실행을 파싱 전에 막는다.
from whymath_backend.l3.safe_parse import safe_parse_expr

logger = logging.getLogger(__name__)

# 수치 비교 허용 오차(공유 계약)
TOLERANCE = 1e-9

# 학생 입력이 이보다 길면 파싱하지 않고 오답으로 본다(SymPy가 긴 입력에서 오래 걸리는 것을 막는다)
MAX_INPUT_LEN = 100

# 식에서 쓸 수 있는 변수는 x 하나뿐이다(공유 계약: expression 정답은 변수 x만 쓴다)
_X = sympy.Symbol("x")

# `2x+1`도 읽도록 곱셈 생략 변환을 더한다
_TRANSFORMS = standard_transformations + (implicit_multiplication_application,)

# 앞에서 떼어 낼 접두(정규화 뒤 — 공백이 이미 사라진 상태에서 비교)
_PREFIXES = ("정답:", "정답은", "답:", "답은", "답", "f(x)=", "y=")

# 뒤에서 떼어 낼 꼬리
_SUFFIXES = ("입니다", "이에요", "예요", "이다", ".")

# 학생이 쓰는 빼기(U+2212)·곱셈(×·가운뎃점)·나눗셈(÷) 기호를 SymPy 문법으로 바꾼다
_SYMBOL_MAP = str.maketrans({"\u2212": "-", "\u00d7": "*", "\u00f7": "/", "\u00b7": "*"})

# 파싱 대상에 허용하는 문자(숫자·x·연산자·괄호·소수점). 그 밖의 글자가 있으면 파싱하지 않는다
# (1차 거름망 — 크기·구조 상한은 safe_parse_expr가 본다)
_ALLOWED = re.compile(r"^[0-9x+\-*/^().]+$")


def normalize(text: str) -> str:
    """학생 입력을 SymPy가 읽을 수 있는 모양으로 다듬는다.

    전각 문자는 NFKC로 반각이 된다(`－１２` → `-12`). U+2212 같은 수학 기호는 표로 바꾼다.
    """
    s = unicodedata.normalize("NFKC", text).translate(_SYMBOL_MAP)
    s = re.sub(r"\s+", "", s)
    # 접두·꼬리는 여러 겹일 수 있다(`답: y = 2x+1 입니다`) — 더 떼어 낼 것이 없을 때까지 반복
    changed = True
    while changed:
        changed = False
        for prefix in _PREFIXES:
            if s.startswith(prefix):
                s = s[len(prefix) :]
                changed = True
        for suffix in _SUFFIXES:
            if s.endswith(suffix):
                s = s[: -len(suffix)]
                changed = True
    return s


def _parse(text: str) -> sympy.Expr:
    """정규화된 문자열을 SymPy 식으로 바꾼다. 읽을 수 없으면 ValueError."""
    if not text or len(text) > MAX_INPUT_LEN or not _ALLOWED.match(text):
        raise ValueError("허용되지 않는 입력")
    expr = safe_parse_expr(
        text.replace("^", "**"),
        local_dict={"x": _X},
        transformations=_TRANSFORMS,
        evaluate=True,
    )
    if not isinstance(expr, sympy.Expr):
        raise ValueError("수식이 아님")
    return expr


def _same_number(student: sympy.Expr, answer: sympy.Expr) -> bool:
    """두 수가 같은지(nsimplify 후 차이 ≤ 1e-9). 변수가 남아 있으면 수가 아니므로 False."""
    if student.free_symbols or answer.free_symbols:
        return False
    diff = sympy.nsimplify(student) - sympy.nsimplify(answer)
    return bool(abs(float(diff)) <= TOLERANCE)


def _same_expression(student: sympy.Expr, answer: sympy.Expr) -> bool:
    """두 식이 같은지(simplify(student - answer) == 0)."""
    return bool(sympy.simplify(student - answer) == 0)


def is_correct(problem: Problem, student_text: str) -> bool:
    """학생 답이 정답인지 판정한다. 파싱 실패는 오답(False)이며 예외 타입명을 로그에 남긴다."""
    try:
        student = _parse(normalize(student_text))
        answer = _parse(normalize(problem["answer"]))
        if problem["answer_kind"] == "expression":
            return _same_expression(student, answer)
        return _same_number(student, answer)
    except Exception as exc:  # noqa: BLE001 — 파싱 실패는 오답. 침묵 실패 금지라 타입명을 남긴다
        logger.info(
            "golden.grade 파싱 실패 → 오답 처리 problem_id=%s 예외=%s",
            problem.get("id", "?"),
            type(exc).__name__,
        )
        return False
