"""값 축 정답 노출 훑기 — 옛 `whymath_backend.l3.verify_solution`의 함수 5개 골든 사본(S32R · T3R).

복사: 의존 과다 — 옛 모듈을 import하면 whymath 모듈 56개가 따라오고, 그 모듈은
`golden/LEGACY_MANIFEST.txt`에 있어 골든이 새로 import할 수 없다(HARVEST.md 「반복 슬롯 T3R 경계
(S31R)」
· 다섯 걸음 ③). 가져온 것: `scan_value_exposure` · `arithmetic_fragments` · `_value_targets` ·
`split_top_level` · `_closed_value`(+ 그것이 쓰는 `_name_kind` · `_balanced` ·
`_is_single_variable`).

옛 판과 다른 점(의존을 자른 자리 — 출력은 S31R 특성화 입력 10개에서 옛 판과 같다):
- `same_value`: 옛 판은 정본 채점기 `verify_final_answer`(옛 모듈 다수)에 위임했다. 이 사본은 같은
  안전
  파서(`safe_sympify` — 골든이 이미 쓰는 `l3.safe_parse`)로 두 값을 읽어 수로 비교한다. 목표가 수가
  아니면
  (식 정답 `2*x + 3`) 옛 판처럼 UNKNOWN이다. 읽지 못해도 UNKNOWN(모른다 ≠ 아니다).
- `_value_targets`: 옛 판의 LaTeX 평문화(`latex_to_plain`)는 가져오지 않았다. 골든 30문항의 정답은
  모두
  평문이다. 정답에 `\\`가 있으면 목표를 읽지 않고 판정 불가로 둔다(접지 않는다).
- 결과 3상태는 이 파일의 `ValueExposure`(옛 `schema.verification_capabilities.ValueExposure`와 같은
  값).

순수 함수다(DB·네트워크·LLM 없음). 같은 입력에 같은 출력이다.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from tokenize import TokenError
from typing import Final

import sympy

# 골든 채점기(`golden.grade`)가 이미 쓰는 옛 모듈 — 직접 import 예산이 늘지
# 않는다(test_import_budget)
from whymath_backend.l3.safe_parse import UnsafeExpressionError, safe_sympify

logger = logging.getLogger(__name__)

# 수치 비교 허용 오차(골든 채점기 `golden.grade.TOLERANCE`와 같은 값)
_TOLERANCE: Final = 1e-9


class ValueExposure(str, Enum):
    """값 노출 3상태 — 옛 판과 같은 값."""

    exposed = "exposed"
    clean = "clean"
    undecidable = "undecidable"


class ValueSame(str, Enum):
    """두 값이 같은가 — 3상태(모르면 모른다)."""

    SAME = "same"
    DIFFERENT = "different"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ValueExposureResult:
    """`scan_value_exposure` 결과. `candidates` = 본 식 수 · `undecided` = 판정 못 한 식 수."""

    outcome: ValueExposure
    fragment: str | None = None
    candidates: int = 0
    undecided: int = 0


# 학생·튜터가 쓰는 곱셈·나눗셈·빼기 기호를 식 문법으로 바꾼다
_VALUE_OP_NORMALIZE: Final = str.maketrans({"×": "*", "÷": "/", "−": "-", "·": "*"})
# 식 덩어리 — 문자·수·연산자·괄호·쉼표·등호가 이어진 구간(한글·콜론·줄바꿈에서 끊긴다)
_EXPR_RUN: Final = re.compile(r"[0-9A-Za-z_.()+\-*/^,= \t]+")
_NUMBER_TOKEN: Final = re.compile(r"\d+(?:\.\d+)?")
_OPERATOR_BETWEEN: Final = re.compile(r"[0-9)]\s*[-+*/^]\s*[-(0-9]")
_IDENT: Final = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
# 식에 쓰인 이름 — 점(.) 바로 뒤의 메서드 이름(`.doit`)은 이름이 아니라 속성이다
_NAME: Final = re.compile(r"(?<![.\w])[A-Za-z_][A-Za-z_0-9]*")

# 식 해석 실패로 예상되는 예외 — 이것만 "식이 아니다"로 접는다(프로그래밍 오류는 삼키지 않는다)
_FRAGMENT_PARSE_FAILURES: Final[tuple[type[BaseException], ...]] = (
    sympy.SympifyError,
    TokenError,
    SyntaxError,
    ValueError,
    ZeroDivisionError,
    OverflowError,
    RecursionError,
)

# 안전 파서의 거부 중 "허용 목록 밖 이름·속성" 사유 — 식은 맞는데 읽기를 거절한 경우다
_ALLOWLIST_REFUSALS: Final = frozenset({"disallowed_name", "disallowed_attribute"})
_NAME_VARIABLE: Final = "variable"
_NAME_CONSTANT: Final = "constant"
_NAME_UNKNOWN: Final = "unknown"


def split_top_level(text: str) -> list[str]:
    """최상위 쉼표로만 자른다 — `f(1, 2)` 안의 쉼표는 자르지 않는다."""
    parts: list[str] = []
    depth = 0
    start = 0
    for index, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


@lru_cache(maxsize=512)
def _name_kind(name: str) -> str:
    """식에 쓰인 이름 하나의 종류 — variable(자유 기호) · constant(함수·상수) · unknown(읽지
    못함)."""
    try:
        value = safe_sympify(name)
    except _FRAGMENT_PARSE_FAILURES as exc:  # 허용 목록 밖 이름 — 종류를 모른다
        logger.debug("이름 해석 불가(%s) — unknown", type(exc).__name__)
        return _NAME_UNKNOWN
    if isinstance(value, sympy.Basic):
        return _NAME_VARIABLE if value.free_symbols else _NAME_CONSTANT
    if isinstance(value, type) or callable(value):
        return _NAME_CONSTANT
    return _NAME_UNKNOWN


def _balanced(side: str) -> bool:
    """괄호 짝이 맞고 문법상 완결된 식인가(평가하지 않는다 — 파이썬 문법 트리로만 본다)."""
    try:
        ast.parse(side.replace("^", "**"), mode="eval")
    except SyntaxError as exc:  # 잘린 변 — 식이 아니다(타입명은 남긴다 · 침묵 실패 금지)
        logger.debug("식 모양 아님(%s) — 후보에서 제외", type(exc).__name__)
        return False
    return True


def _closed_value(side: str) -> bool:
    """변 하나가 쓰인 그대로 닫힌 값인가 — 변수 이름이 없고 값이 수로 정해진다(옛 판과 같은
    규칙)."""
    kinds = {_name_kind(name) for name in _NAME.findall(side)}
    if _NAME_VARIABLE in kinds:
        return False
    if _NAME_UNKNOWN in kinds:
        return bool(_NUMBER_TOKEN.search(side)) and "(" in side and _balanced(side)
    try:
        value = safe_sympify(side.replace("^", "**"))
    except UnsafeExpressionError as exc:
        # 허용 목록 밖 이름·속성을 거절했다 — 변수 없이 수를 쓰는 식이면 후보로 낸다
        logger.debug("변 안전 파싱 거부(%s) — 허용 목록 거절이면 후보", exc.code)
        return (
            exc.code in _ALLOWLIST_REFUSALS and bool(_NUMBER_TOKEN.search(side)) and _balanced(side)
        )
    except _FRAGMENT_PARSE_FAILURES as exc:  # 잘린 변 — 식이 아니다
        logger.debug("변 해석 불가(%s) — 대상에서 제외", type(exc).__name__)
        return False
    return isinstance(value, sympy.Basic) and bool(value.is_number)


def _is_single_variable(side: str) -> bool:
    """값 진술의 변수 쪽인가 — 이름 하나이고, 한 글자이거나 상수가 아니다."""
    if _IDENT.fullmatch(side) is None:
        return False
    return len(side) == 1 or _name_kind(side) != _NAME_CONSTANT


def arithmetic_fragments(text: str) -> list[str]:
    """본문 → 값을 드러내는 닫힌 식 후보. ①계산만 남은 식(`3*5+1`) ②값 진술(`y = 4`의 `4`).

    수 하나(`4`)만으로는 ①이 아니다 — 본문의 "4번" 같은 수와 구별되지 않는다. 순서 보존 · 중복 1회.
    """
    out: list[str] = []
    seen: set[str] = set()

    def add(frag: str) -> None:
        if frag not in seen:
            seen.add(frag)
            out.append(frag)

    for run in _EXPR_RUN.findall(text.translate(_VALUE_OP_NORMALIZE)):
        for part in split_top_level(run):
            sides = [side.strip() for side in part.split("=")]
            for side in sides:
                if not side or side in seen:
                    continue
                computed = _OPERATOR_BETWEEN.search(side) or _IDENT.search(side)
                if computed and _closed_value(side):
                    add(side)
            if len(sides) == 2 and all(sides):
                left, right = sides
                for var, value in ((left, right), (right, left)):
                    if _is_single_variable(var) and _closed_value(value):
                        add(value)
    return out


def _value_targets(target: str) -> list[str]:
    """정답 문자열 → 비교할 값 목록(최상위 쉼표로 나뉜 여러 값은 각각). LaTeX 정답은 읽지 않는다(빈
    목록)."""
    if "\\" in target:
        return []
    parts = [p.strip() for p in split_top_level(target) if p.strip()]
    return parts if len(parts) > 1 else [target.strip()]


def same_value(left: str, right: str) -> ValueSame:
    """두 값 문자열이 같은 수인가 — 안전 파서로 읽어 차이 ≤ 1e-9면 SAME(옛 판의 정본 채점기 위임을
    대신함)."""
    try:
        a = safe_sympify(left.replace("^", "**"))
        b = safe_sympify(right.replace("^", "**"))
    except _FRAGMENT_PARSE_FAILURES as exc:
        logger.debug("값 비교 회피: %s", type(exc).__name__)
        return ValueSame.UNKNOWN
    if not (isinstance(a, sympy.Basic) and isinstance(b, sympy.Basic)):
        return ValueSame.UNKNOWN
    if not a.is_number:
        return ValueSame.UNKNOWN
    if not b.is_number:
        # 정답이 식(`2*x + 3`)이면 옛 판(정본 채점기)도 수와 비교하지 못해 판정 불가였다 — 같게 둔다
        return ValueSame.UNKNOWN
    try:
        diff = abs(complex(sympy.nsimplify(a) - sympy.nsimplify(b)))
    except (TypeError, ValueError, OverflowError) as exc:
        logger.debug("값 비교 회피: %s", type(exc).__name__)
        return ValueSame.UNKNOWN
    return ValueSame.SAME if diff <= _TOLERANCE else ValueSame.DIFFERENT


def scan_value_exposure(text: str, target: str) -> ValueExposureResult:
    """`text`의 닫힌 식 중 값이 `target`과 같은 것이 있는가 — 3상태(옛 판과 같은 규칙).

    - exposed: 식 하나가 목표(또는 목표의 한 성분)와 SAME.
    - undecidable: 같은 것은 없는데 판정하지 못한 쌍이 있다(clean으로 접지 않는다).
    - clean: 식이 없거나, 모든 식이 모든 목표 성분과 DIFFERENT.
    """
    fragments = arithmetic_fragments(text)
    if not fragments:
        return ValueExposureResult(ValueExposure.clean)
    targets = _value_targets(target) if target.strip() else []
    if not targets:
        return ValueExposureResult(
            ValueExposure.undecidable, candidates=len(fragments), undecided=len(fragments)
        )
    undecided = 0
    for frag in fragments:
        relations = [same_value(frag, t) for t in targets]
        if ValueSame.SAME in relations:
            return ValueExposureResult(
                ValueExposure.exposed, fragment=frag, candidates=len(fragments), undecided=undecided
            )
        if ValueSame.UNKNOWN in relations:
            undecided += 1
    return ValueExposureResult(
        ValueExposure.undecidable if undecided else ValueExposure.clean,
        candidates=len(fragments),
        undecided=undecided,
    )
