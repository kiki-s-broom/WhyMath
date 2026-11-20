"""오개념 주입기(S17) — 문항과 오개념 ID를 받아 그 오개념을 가진 학생이 낼 틀린 답을 만든다.

LLM을 부르지 않는다. 규칙만 쓰고, 같은 (문항, 오개념) 입력에는 언제나 같은 틀린 답이 나온다
(M3 판정 오류율·오개념 검출률을 재려면 답이 흔들리면 안 된다 — 지시서 S17 목적).

흐름: 오개념 ID → (OP 코드, 변형 이름) 목록 → 문항 유형에 맞는 변형 규칙 → 후보 답 → 채점기로 확인.

- 오개념 ID는 `data/corpus/misconceptions_v1/misconceptions.json`에서 센 일차함수분 8건
  (`subunit=일차함수` 또는 성취기준 `[9수02-14/15/16]`)과 선행 부호 오개념 3건이다.
  옛 로더(`whymath_backend.l1.misconception`)는 쓰지 않고 표를 이 파일 안 딕셔너리로 둔다 —
  T2(S26)가 다섯 걸음으로 정식 목록을 가져올 때까지 중복은 의도된 것이다.
- DB에 짝이 없는 OP 코드(OP_05·OP_06)는 오개념 ID 자리에 OP 코드를 그대로 넣어 부른다
  (`inject(problem, "OP_05")`). 이때 돌려주는 `misconception_id`는 None이다.
- 문항 유형에 맞지 않으면 None을 돌려주고, 부르는 쪽(S19 러너)이 다른 오개념을 고른다.
- 만든 답을 `grade.is_correct`로 채점해 정답이면 같은 규칙의 다음 후보(한 단계 더)를 쓰고,
  그것도 정답이면 None이다. 그래서 돌려주는 답은 언제나 오답이다.

OP 코드 정본은 `golden.sim.seed_extract.OP_CODES`(설명 `golden/sim/op_codes.md`)다.
실행(저장소의 src/backend 폴더에서) — 30문항 × 입력 전부 표를 CSV로 쓴다:
    python -m golden.sim.errors --csv ../../golden/reports_phase1/S17/injection_table.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import sympy

from golden import grade
from golden.problems import Problem, load_problems
from golden.sim.seed_extract import OP_CODES, classify_error

# ──────────────────────────────────────────────────────────────────────
# 오개념 ID → OP 코드 표
# ──────────────────────────────────────────────────────────────────────

# 일차함수분 8건(사전 실측 2026-11-15 · 이 세션 재확인 2026-11-20 — 같은 8건)
LF_MISCONCEPTIONS: tuple[str, ...] = (
    "M0034",
    "M0035",
    "M0036",
    "M0037",
    "M0409",
    "M0567",
    "M0568",
    "M0569",
)

# 일차함수 문항에서 실제로 나는 선행(정수 연산) 부호 오개념 3건
SIGN_MISCONCEPTIONS: tuple[str, ...] = ("M0001", "M0002", "M0548")

ALL_MISCONCEPTIONS: tuple[str, ...] = LF_MISCONCEPTIONS + SIGN_MISCONCEPTIONS

# OP 코드만으로 부를 수 있는 코드(OP_00 미분류는 만들 수 없다)
INJECTABLE_OPS: tuple[str, ...] = tuple(code for code in OP_CODES if code != "OP_00")

# 부호 변형 이름 — 계산 과정의 어느 단계에서 부호를 틀리는가
MUL_NEG = "mul_neg"  # (−)×(−)=(−) · (−)÷(−)=(−)
SUB_NEG = "sub_neg"  # a−(−b)를 a−b로
SUB_NEG_NEG = "sub_neg_neg"  # (−a)−(−b)를 (−a)−b로(빼지는 수도 음수일 때만)
FLIP = "flip"  # 정답과 부호만 반대

# 오개념 ID → (OP 코드, 변형 이름) 목록. 앞에서부터 해 보고 처음 맞는 규칙을 쓴다.
# 빈 목록 = 30문항 어디에도 맞는 규칙이 없다(함수 개념 오개념 — 함수 판별 문항이 없다).
MISCONCEPTION_RULES: dict[str, tuple[tuple[str, str | None], ...]] = {
    # M0034 기울기 — y절편을 기울기로 착각
    "M0034": (("OP_04", None),),
    # M0035 일차함수 그래프 — 음의 기울기 방향 혼동(증가·감소 반대)
    "M0035": (("OP_08", None),),
    # M0036 절편 — x절편과 y절편 혼동(좌표 바꿔 배치)
    "M0036": (("OP_07", None),),
    # M0037 함숫값 — f(2)를 2f로 계산(대입 오류)
    "M0037": (("OP_02", None),),
    # M0409 하나의 x에 여러 y 가능 — 함수 판별 문항이 30문항에 없다
    "M0409": (),
    # M0567 다가 대응도 함수로 봄·상수함수를 함수가 아니라고 봄 — 같은 이유로 없다
    "M0567": (),
    # M0568 기울기 a와 y절편 b의 역할을 바꿈 · 기울기를 Δx/Δy로 뒤집음 — 앞의 것부터 해 본다
    "M0568": (("OP_04", None), ("OP_03", None)),
    # M0569 기울기의 부호와 그래프의 증가·감소를 반대로 봄
    "M0569": (("OP_08", None),),
    # M0001 음수 곱셈 — (−)×(−)=(−)
    "M0001": (("OP_01", MUL_NEG),),
    # M0002 음수 뺄셈 — 3−(−5)=3−5=−2
    "M0002": (("OP_01", SUB_NEG),),
    # M0548 (−)−(−) 같은 부호 처리에서 실수
    "M0548": (("OP_01", SUB_NEG_NEG),),
}

# OP 코드만으로 부를 때의 규칙 목록. OP_01은 계산 단계의 부호 변형을 먼저 보고, 없으면 부호 반대.
OP_RULES: dict[str, tuple[tuple[str, str | None], ...]] = {
    code: ((code, None),) for code in INJECTABLE_OPS
}
OP_RULES["OP_01"] = (
    ("OP_01", MUL_NEG),
    ("OP_01", SUB_NEG),
    ("OP_01", SUB_NEG_NEG),
    ("OP_01", FLIP),
)

# 같은 규칙에서 해 보는 후보 수 — 첫 후보가 정답이면 한 단계 더(두 번째) 보고, 그다음은 없다
MAX_CANDIDATES = 2


@dataclass(frozen=True)
class WrongAnswer:
    """주입기가 만든 틀린 답 1건. OP 코드만으로 만들었으면 misconception_id는 None이다."""

    text: str
    op_code: str
    misconception_id: str | None


# ──────────────────────────────────────────────────────────────────────
# 문항 유형 판별
# ──────────────────────────────────────────────────────────────────────

F_VALUE = "f_value"  # 함숫값 f(k) · x=k일 때 y
SOLVE_COEF = "solve_coef"  # f(k)=v에서 상수 a 구하기
SLOPE_POINTS = "slope_points"  # 두 점으로 기울기
SLOPE_READ = "slope_read"  # 식에서 기울기 읽기
INCREASE = "increase"  # x가 n만큼 늘 때 y의 증가량
Y_INTERCEPT = "y_intercept"  # 식에서 y절편 읽기
X_INTERCEPT = "x_intercept"  # 식에서 x절편 구하기
Y_FROM_X_INTERCEPT = "y_from_x_intercept"  # x절편이 주어졌을 때 y절편(문자 계수)
EQUATION = "equation"  # 식 세우기(answer_kind=expression)
COUNT_DIRECTION = "count_direction"  # 증가·감소 개수 세기
BOUNDARY = "boundary"  # 증가 조건의 경곗값
COUNT_QUADRANT = "count_quadrant"  # 사분면 개수 세기
WORD = "word"  # 나머지 실생활 문항

PROBLEM_TYPES: tuple[str, ...] = (
    F_VALUE,
    SOLVE_COEF,
    SLOPE_POINTS,
    SLOPE_READ,
    INCREASE,
    Y_INTERCEPT,
    X_INTERCEPT,
    Y_FROM_X_INTERCEPT,
    EQUATION,
    COUNT_DIRECTION,
    BOUNDARY,
    COUNT_QUADRANT,
    WORD,
)

_FRAC = re.compile(r"\\frac\{(-?\d+)\}\{(\d+)\}")
_LINEAR = re.compile(r"(?:f\(x\)|y)=(?P<a>-?\d*(?:/\d+)?)x(?P<b>[+-]\d+(?:/\d+)?)?(?![\dx(+\-*/])")
_F_OF_K = re.compile(r"f\((-?\d+)\)")
_X_IS_K = re.compile(r"x=(-?\d+)일때")
_POINT = re.compile(r"\((-?\d+),(-?\d+)\)")
_GIVEN_SLOPE = re.compile(r"기울기가(-?\d+(?:/\d+)?)이고")
_INCREMENT = re.compile(r"(\d+)만큼증가")
_GIVEN_X_INTERCEPT = re.compile(r"x절편이(-?\d+)일때")
_LETTER_B_SLOPE = re.compile(r"y=(-?\d*)x\+b")
_LETTER_A_CONST = re.compile(r"f\(x\)=ax([+-]\d+)")
_F_EQUALS = re.compile(r"f\((-?\d+)\)=(-?\d+)")
_BOUNDARY = re.compile(r"\(a-(\d+)\)x")
_STEM_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _flat_stem(stem: str) -> str:
    """문항 본문에서 LaTeX 겉모양(`\\frac`·`$`·공백)을 걷어 규칙이 읽기 쉬운 한 줄로 만든다."""
    flat = _FRAC.sub(r"\1/\2", stem)
    return re.sub(r"[\s$]", "", flat.replace("\u2212", "-"))


def _coefficient(text: str) -> Fraction:
    """`-`·``(빈칸)·`3`·`1/2` 같은 계수 표기를 분수로 바꾼다."""
    if text in ("", "+"):
        return Fraction(1)
    if text == "-":
        return Fraction(-1)
    return Fraction(text)


def _lines_of(flat: str) -> list[tuple[Fraction, Fraction]]:
    """본문의 모든 일차식 (기울기, y절편). 문자 계수(`ax+5`·`3x+b`)인 식은 빠진다."""
    return [
        (_coefficient(m.group("a")), Fraction(m.group("b") or "0")) for m in _LINEAR.finditer(flat)
    ]


def problem_type(problem: Problem) -> str:
    """문항 유형을 `answer_kind`와 본문 키워드(기울기·절편·증가·사분면·상수 등)로 판별한다.

    순서가 뜻을 가진다: 식 정답 → 기울기 → 증가량 → y절편 → x절편 → 증가·감소 → 사분면 →
    상수 구하기 → 함숫값 → 나머지(실생활).
    """
    if problem["answer_kind"] == "expression":
        return EQUATION
    flat = _flat_stem(problem["stem"])
    if "기울기를구하" in flat:
        return SLOPE_POINTS if len(_POINT.findall(flat)) == 2 else SLOPE_READ
    if "증가량" in flat:
        return INCREASE
    if "y절편을구하" in flat:
        return Y_FROM_X_INTERCEPT if _GIVEN_X_INTERCEPT.search(flat) else Y_INTERCEPT
    if "x절편을구하" in flat:
        return X_INTERCEPT
    if "증가할때" in flat and "몇개" in flat:
        return COUNT_DIRECTION
    if "증가할때" in flat and _BOUNDARY.search(flat):
        return BOUNDARY
    if "사분면" in flat:
        return COUNT_QUADRANT
    if "상수" in flat and _F_EQUALS.search(flat):
        return SOLVE_COEF
    if _lines_of(flat) and (_F_OF_K.search(flat) or _X_IS_K.search(flat)):
        return F_VALUE
    return WORD


# ──────────────────────────────────────────────────────────────────────
# 문항에서 수 읽기
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Info:
    """규칙이 쓰는 문항 정보 — 유형·본문의 수·정답."""

    kind: str
    flat: str
    lines: tuple[tuple[Fraction, Fraction], ...]
    points: tuple[tuple[Fraction, Fraction], ...]
    answer_value: Fraction | None  # number 문항의 정답
    answer_line: tuple[Fraction, Fraction] | None  # expression 문항의 정답 (기울기, y절편)


def _answer_line(answer: str) -> tuple[Fraction, Fraction] | None:
    """식 정답(`2*x + 3`)을 채점기와 같은 파서로 읽어 (기울기, y절편)으로 바꾼다."""
    expr = grade._parse(grade.normalize(answer))
    coeffs = sympy.Poly(expr, sympy.Symbol("x")).all_coeffs()
    if len(coeffs) != 2:
        return None
    a, b = (sympy.nsimplify(c) for c in coeffs)
    return Fraction(int(a.p), int(a.q)), Fraction(int(b.p), int(b.q))


def _info(problem: Problem) -> _Info:
    """문항 1건을 규칙이 쓰는 모양으로 읽는다."""
    flat = _flat_stem(problem["stem"])
    kind = problem_type(problem)
    expression = problem["answer_kind"] == "expression"
    return _Info(
        kind=kind,
        flat=flat,
        lines=tuple(_lines_of(flat)),
        points=tuple((Fraction(px), Fraction(py)) for px, py in _POINT.findall(flat)),
        answer_value=None if expression else Fraction(problem["answer"]),
        answer_line=_answer_line(problem["answer"]) if expression else None,
    )


def _first(pattern: re.Pattern[str], flat: str) -> Fraction:
    """본문에서 패턴의 첫 그룹을 분수로 읽는다(유형 판별을 통과한 문항이라 반드시 있다)."""
    match = pattern.search(flat)
    if match is None:
        raise ValueError(f"본문에서 수를 찾지 못했다: {pattern.pattern}")
    return Fraction(match.group(1))


# ──────────────────────────────────────────────────────────────────────
# 계산 과정 — 부호 오개념은 "어느 단계에서" 틀리는지로 흉내 낸다
# ──────────────────────────────────────────────────────────────────────


class _Calc:
    """사칙 계산기. 변형 이름이 있으면 그 오개념대로 틀리게 계산하고, 틀린 적이 있으면 표시한다."""

    def __init__(self, variant: str | None = None) -> None:
        self.variant = variant
        self.fired = False

    def mul(self, x: Fraction, y: Fraction) -> Fraction:
        """곱셈. MUL_NEG면 (−)×(−)를 (−)로."""
        if self.variant == MUL_NEG and x < 0 and y < 0:
            self.fired = True
            return -(x * y)
        return x * y

    def div(self, x: Fraction, y: Fraction) -> Fraction:
        """나눗셈. MUL_NEG면 (−)÷(−)를 (−)로(곱셈과 같은 부호 규칙)."""
        if self.variant == MUL_NEG and x < 0 and y < 0:
            self.fired = True
            return -(x / y)
        return x / y

    def sub(self, x: Fraction, y: Fraction) -> Fraction:
        """뺄셈. SUB_NEG면 x−(−b)를 x−b로 · SUB_NEG_NEG면 x도 음수일 때만 그렇게."""
        if y < 0 and (self.variant == SUB_NEG or (self.variant == SUB_NEG_NEG and x < 0)):
            self.fired = True
            return x + y
        return x - y


def _solve(info: _Info, calc: _Calc) -> Fraction | None:
    """number 문항을 계산 과정 그대로 푼다. 계산 과정이 정해지지 않은 유형은 None."""
    flat = info.flat
    if info.kind == F_VALUE:
        a, b = info.lines[0]
        k = _first(_F_OF_K, flat) if _F_OF_K.search(flat) else _first(_X_IS_K, flat)
        return calc.mul(a, k) + b
    if info.kind == SOLVE_COEF:
        match = _F_EQUALS.search(flat)
        assert match is not None  # 유형 판별이 이미 확인했다
        k, v = Fraction(match.group(1)), Fraction(match.group(2))
        b = _first(_LETTER_A_CONST, flat)
        return calc.div(calc.sub(v, b), k)
    if info.kind == SLOPE_POINTS:
        (x1, y1), (x2, y2) = info.points
        return calc.div(calc.sub(y2, y1), calc.sub(x2, x1))
    if info.kind == INCREASE:
        return calc.mul(info.lines[0][0], _first(_INCREMENT, flat))
    if info.kind == X_INTERCEPT:
        a, b = info.lines[0]
        return calc.div(calc.sub(Fraction(0), b), a)
    if info.kind == Y_FROM_X_INTERCEPT:
        slope_match = _LETTER_B_SLOPE.search(flat)
        if slope_match is None:
            return None
        a = _coefficient(slope_match.group(1))
        return calc.sub(Fraction(0), calc.mul(a, _first(_GIVEN_X_INTERCEPT, flat)))
    if info.kind == SLOPE_READ:
        return info.lines[0][0]
    if info.kind == Y_INTERCEPT:
        return info.lines[0][1]
    return None


def _line_from_point(slope: Fraction, info: _Info, calc: _Calc) -> tuple[Fraction, Fraction] | None:
    """기울기와 지나는 첫 점으로 y절편을 구한다(b = y₁ − a·x₁). 점이 없으면 None."""
    if not info.points:
        return None
    x1, y1 = info.points[0]
    return slope, calc.sub(y1, calc.mul(slope, x1))


def _solve_line(info: _Info, calc: _Calc) -> tuple[Fraction, Fraction] | None:
    """식 세우기 문항을 계산 과정 그대로 푼다 — (기울기, y절편). 과정이 없으면(실생활) None."""
    given = _GIVEN_SLOPE.search(info.flat)
    if len(info.points) == 2:
        (x1, y1), (x2, y2) = info.points
        return _line_from_point(calc.div(calc.sub(y2, y1), calc.sub(x2, x1)), info, calc)
    if given is not None:
        return _line_from_point(Fraction(given.group(1)), info, calc)
    if info.lines:  # 평행한 직선 — 본문의 식에서 기울기를 가져온다
        return _line_from_point(info.lines[0][0], info, calc)
    return None


# ──────────────────────────────────────────────────────────────────────
# 답 쓰기 — 학생이 칠 법한 모양, 채점기가 읽을 수 있는 모양
# ──────────────────────────────────────────────────────────────────────


def _num(value: Fraction) -> str:
    """분수를 `3`·`-3/2` 꼴로."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _paren(value: Fraction) -> str:
    """음수·분수면 괄호로 감싼다(`5×(-2)`·`(1/2)×10`)."""
    text = _num(value)
    return f"({text})" if value < 0 or value.denominator != 1 else text


def _lead(value: Fraction) -> str:
    """식의 맨 앞 수 — 음의 정수는 괄호 없이, 분수는 괄호로(`-3×5`·`(1/2)×10`)."""
    return _num(value) if value.denominator == 1 else f"({_num(value)})"


def _signed(value: Fraction) -> str:
    """뒤에 붙는 항 — `+3`·`-5`·0이면 빈칸."""
    if value == 0:
        return ""
    return f"+{_num(value)}" if value > 0 else f"-{_num(-value)}"


def _line_text(slope: Fraction, intercept: Fraction) -> str:
    """일차식을 `2x+3`·`-x-7`·`(1/2)x+5/2` 꼴로."""
    if slope == 0:
        return _num(intercept)
    if slope == 1:
        head = "x"
    elif slope == -1:
        head = "-x"
    else:
        head = f"{_lead(slope)}x"
    return head + _signed(intercept)


# ──────────────────────────────────────────────────────────────────────
# OP 코드별 변형 규칙 — 후보 답 목록(앞이 먼저 · 비면 이 문항에 맞지 않음)
# ──────────────────────────────────────────────────────────────────────

# 부호 반대(FLIP)를 쓰지 않는 유형 — 개수·경곗값·시간은 음수 답이 학생 오답으로 어색하다
_NO_FLIP = (COUNT_DIRECTION, COUNT_QUADRANT, BOUNDARY, WORD)


def _op01(info: _Info, variant: str | None) -> list[str]:
    """OP_01 부호 오류 — 계산 단계의 부호 변형(곱셈·뺄셈), 또는 정답과 부호만 반대."""
    if variant == FLIP:
        if info.kind in _NO_FLIP:
            return []
        if info.answer_line is not None:
            # 식 정답 — y절편 부호를 먼저 바꾸고, 한 단계 더면 기울기 부호
            a, b = info.answer_line
            flipped: list[str] = []
            if b != 0:
                flipped.append(_line_text(a, -b))
            if a != 0:
                flipped.append(_line_text(-a, b))
            return flipped
        assert info.answer_value is not None
        return [_num(-info.answer_value)] if info.answer_value != 0 else []
    calc = _Calc(variant)
    if info.kind == EQUATION:
        line = _solve_line(info, calc)
        return [_line_text(*line)] if line is not None and calc.fired else []
    value = _solve(info, calc)
    return [_num(value)] if value is not None and calc.fired else []


def _op02(info: _Info, _variant: str | None) -> list[str]:
    """OP_02 대입 오류 — f(k)를 k×(계수 합)으로, 한 단계 더면 x 자리를 비운 계수 합."""
    if info.kind != F_VALUE:
        return []
    a, b = info.lines[0]
    k = _first(_F_OF_K, info.flat) if _F_OF_K.search(info.flat) else _first(_X_IS_K, info.flat)
    return [_num(k * (a + b)), _num(a + b)]


def _op03(info: _Info, _variant: str | None) -> list[str]:
    """OP_03 기울기 분자·분모 뒤바꿈 — Δx/Δy(두 점) · 1/a(식에서 읽기)."""
    if info.kind in (SLOPE_POINTS, EQUATION) and len(info.points) == 2:
        (x1, y1), (x2, y2) = info.points
        dx, dy = x2 - x1, y2 - y1
        if dy == 0:
            return []
        if info.kind == SLOPE_POINTS:
            return [_num(dx / dy), _num(-dx / dy)]
        line = _line_from_point(dx / dy, info, _Calc())
        return [_line_text(*line)] if line is not None else []
    if info.kind == SLOPE_READ and info.lines[0][0] != 0:
        return [_num(1 / info.lines[0][0])]
    return []


def _op04(info: _Info, _variant: str | None) -> list[str]:
    """OP_04 기울기·y절편 혼동 — 읽을 때 서로 바꾸거나, 식에서 두 수를 바꿔 씀."""
    if info.kind == EQUATION:
        assert info.answer_line is not None
        a, b = info.answer_line
        return [_line_text(b, a)]
    if not info.lines:
        return []
    a, b = info.lines[0]
    if info.kind == SLOPE_READ:
        return [_num(b)]
    if info.kind in (Y_INTERCEPT, X_INTERCEPT):
        return [_num(a)]
    if info.kind == INCREASE:
        return [_num(b * _first(_INCREMENT, info.flat))]
    return []


def _op05(info: _Info, _variant: str | None) -> list[str]:
    """OP_05 계산을 끝내지 않음 — 대입식 문자열 그대로(값이 같으면 정답이라 한 단계 더: 중간값)."""
    flat = info.flat
    if info.kind == F_VALUE:
        a, b = info.lines[0]
        k = _first(_F_OF_K, flat) if _F_OF_K.search(flat) else _first(_X_IS_K, flat)
        return [f"{_lead(a)}×{_paren(k)}{_signed(b)}", f"{_lead(a)}×{_paren(k)}"]
    if info.kind == SLOPE_POINTS:
        (x1, y1), (x2, y2) = info.points
        dy_text = f"{_num(y2)}-{_paren(y1)}"
        return [f"({dy_text})/({_num(x2)}-{_paren(x1)})", dy_text]
    if info.kind == X_INTERCEPT:
        a, b = info.lines[0]
        return [f"{_num(-b)}/{_paren(a)}", _num(-b)]
    if info.kind == INCREASE:
        return [f"{_lead(info.lines[0][0])}×{_paren(_first(_INCREMENT, flat))}"]
    if info.kind == SOLVE_COEF:
        match = _F_EQUALS.search(flat)
        assert match is not None
        k, v = Fraction(match.group(1)), Fraction(match.group(2))
        top = f"{_num(v)}{_signed(-_first(_LETTER_A_CONST, flat))}"
        return [f"({top})/{_paren(k)}", top]
    return []


def _op06(info: _Info, _variant: str | None) -> list[str]:
    """OP_06 식 세우기 실패 — 문항 본문의 첫 숫자(한 단계 더: 그다음 다른 숫자)."""
    numbers: list[str] = []
    for text in _STEM_NUMBER.findall(info.flat):
        if text not in numbers:
            numbers.append(text)
    return numbers[:MAX_CANDIDATES]


def _op07(info: _Info, _variant: str | None) -> list[str]:
    """OP_07 x절편·y절편 혼동 — 구하라는 절편 대신 다른 절편."""
    if info.kind == Y_INTERCEPT and info.lines[0][0] != 0:
        a, b = info.lines[0]
        return [_num(-b / a)]
    if info.kind == X_INTERCEPT:
        return [_num(info.lines[0][1])]
    if info.kind == Y_FROM_X_INTERCEPT:
        return [_num(_first(_GIVEN_X_INTERCEPT, info.flat))]
    return []


def _passes_first_quadrant(slope: Fraction, intercept: Fraction) -> bool:
    """직선이 제1사분면을 지나는가 — 기울기가 양수이거나 y절편이 양수면 지난다."""
    return slope > 0 or intercept > 0


def _op08(info: _Info, _variant: str | None) -> list[str]:
    """OP_08 증가·감소 방향 혼동 — 기울기 부호를 반대로 보고 푼 답."""
    if info.kind == COUNT_DIRECTION:
        return [str(sum(1 for slope, _ in info.lines if slope > 0))]
    if info.kind == BOUNDARY:
        return [_num(_first(_BOUNDARY, info.flat) - 1)]
    if info.kind == COUNT_QUADRANT:
        return [str(sum(1 for m, c in info.lines if not _passes_first_quadrant(-m, c)))]
    if info.kind == SLOPE_POINTS:
        assert info.answer_value is not None
        return [_num(-info.answer_value)]
    if info.kind == SLOPE_READ:
        return [_num(-info.lines[0][0])]
    if info.kind == EQUATION:
        assert info.answer_line is not None
        a, b = info.answer_line
        line = _line_from_point(-a, info, _Calc()) or (-a, b)
        return [_line_text(*line)]
    return []


_RULES: dict[str, Callable[[_Info, str | None], list[str]]] = {
    "OP_01": _op01,
    "OP_02": _op02,
    "OP_03": _op03,
    "OP_04": _op04,
    "OP_05": _op05,
    "OP_06": _op06,
    "OP_07": _op07,
    "OP_08": _op08,
}


# ──────────────────────────────────────────────────────────────────────
# 주입
# ──────────────────────────────────────────────────────────────────────


def _first_wrong(problem: Problem, candidates: list[str]) -> str | None:
    """후보를 앞에서부터 채점한 첫 오답. 첫 후보가 정답이면 한 단계 더, 그것도 정답이면 None."""
    for text in candidates[:MAX_CANDIDATES]:
        if not grade.is_correct(problem, text):
            return text
    return None


def inject(problem: Problem, misconception_id: str) -> WrongAnswer | None:
    """문항과 오개념 ID(또는 OP 코드)로 결정적인 틀린 답을 만든다. 문항에 맞지 않으면 None.

    `misconception_id`는 `ALL_MISCONCEPTIONS`의 ID이거나, DB에 짝이 없는 오류를 부를 때의
    OP 코드(`OP_01`~`OP_08`)다. 둘 다 아니면(오타·OP_00) ValueError — 조용히 None을 내면
    부르는 쪽이 "이 문항엔 안 맞는다"로 오해한다.
    """
    if misconception_id in MISCONCEPTION_RULES:
        rules = MISCONCEPTION_RULES[misconception_id]
        recorded: str | None = misconception_id
    elif misconception_id in OP_RULES:
        rules = OP_RULES[misconception_id]
        recorded = None
    else:
        raise ValueError(f"주입할 수 없는 입력이다(오개념 ID 또는 OP_01~OP_08): {misconception_id}")
    info = _info(problem)
    for op_code, variant in rules:
        text = _first_wrong(problem, _RULES[op_code](info, variant))
        if text is not None:
            return WrongAnswer(text=text, op_code=op_code, misconception_id=recorded)
    return None


# ──────────────────────────────────────────────────────────────────────
# 표 — 30문항 × 입력 전부 (보고용 CSV)
# ──────────────────────────────────────────────────────────────────────

ALL_INPUTS: tuple[str, ...] = ALL_MISCONCEPTIONS + INJECTABLE_OPS

TABLE_COLUMNS = ("입력", "오개념ID", "문항", "유형", "정답", "틀린답", "OP", "분류기재분류")


def injection_table(problems: list[Problem]) -> list[dict[str, str]]:
    """문항 × 입력 전부의 주입 결과. 맞지 않는 조합은 틀린답·OP가 빈칸이다.

    `분류기재분류`는 S16 분류기(`classify_error`)가 그 틀린 답을 어느 OP로 보는지다 — 주입한 OP와
    다르면 두 표의 규칙 순서가 다른 곳이다(S20 보정이 참고한다). 판정 기준이 아니다.
    """
    rows: list[dict[str, str]] = []
    for problem in problems:
        kind = problem_type(problem)
        for item in ALL_INPUTS:
            result = inject(problem, item)
            rows.append(
                {
                    "입력": item,
                    "오개념ID": item if item in MISCONCEPTION_RULES else "",
                    "문항": problem["id"],
                    "유형": kind,
                    "정답": problem["answer"],
                    "틀린답": result.text if result else "",
                    "OP": result.op_code if result else "",
                    "분류기재분류": (classify_error(problem, result.text) or "") if result else "",
                }
            )
    return rows


def write_table(path: Path, problems: list[Problem]) -> list[dict[str, str]]:
    """주입 표를 CSV(UTF-8, BOM 없음, 줄바꿈 LF)로 쓴다."""
    rows = injection_table(problems)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TABLE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    """표를 CSV로 쓰고 입력별 적용 가능 문항 수를 찍는다."""
    parser = argparse.ArgumentParser(description="오개념 주입기 표(30문항 × 입력 전부)")
    parser.add_argument("--csv", type=Path, required=True, help="쓸 CSV 경로")
    args = parser.parse_args(argv)
    rows = write_table(args.csv, load_problems())
    for item in ALL_INPUTS:
        hits = [row for row in rows if row["입력"] == item and row["틀린답"]]
        print(f"{item}\t적용 문항 {len(hits)}/30")
    print(f"행 {len(rows)} · 파일 {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
