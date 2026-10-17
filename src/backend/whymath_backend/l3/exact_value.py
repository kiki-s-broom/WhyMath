"""정확값(유리수·목록) 문자열의 읽기/쓰기 — 과목 무관 단일 파서(S4-66).

정수·`p/q`·그 목록만 **정확하게** 읽고 쓴다. 소수(`0.5`)·부동소수(`73.0`)·bool은 *정확하다고
말할 수 없으므로* 읽지 않는다. 검증기(`l3/sequence_induction.py`)가 답을, 교차검증 판정기
(`l3/cross_verify.py`)가 LLM 재계산값과 기계 정확값을 이 한 곳의 파서로 읽는다 — 두 곳이 따로
읽으면 같은 문자열을 서로 다르게 판독해 검증기는 통과시키고 판정기는 불일치로 보는 갈라짐이 생긴다.

CORE 모듈이다(수학 도메인 문법을 모른다). `cross_verify`(CORE)가 ADAPTER인 `sequence_induction`을
import하면 코어→어댑터 직접 의존이 되므로(경계 탐침이 잡는다) 파서를 이쪽으로 뺐다.

**알려진 한계**: 파이썬 정수→문자열 변환은 4,300자리 이하만 허용한다(`sys.set_int_max_str_digits`
기본값). 읽기는 그보다 큰 정수를 `None`으로 돌리고, 쓰기는 비트 `MAX_SERIALIZED_BITS`를 넘으면 빈
문자열/`None`을 돌린다. 전역 한도는 건드리지 않는다.

7계층: L3 지역. 표준 라이브러리만 import한다.
"""

from __future__ import annotations

import re
from fractions import Fraction

__all__ = [
    "MAX_ANSWER_LEN",
    "MAX_SERIALIZED_BITS",
    "ExactValue",
    "format_exact_scalar",
    "format_exact_value",
    "parse_exact_value",
]

ExactValue = Fraction | tuple[Fraction, ...]

MAX_ANSWER_LEN = 20_000
# 정확값 문자열로 직렬화할 정수의 비트 상한 — 4,300자리(≈14,284비트) 미만으로 묶는다.
MAX_SERIALIZED_BITS = 13_000

# ──────────────────────────────────────────────────────────────────────────
# 정확값 문자열 ↔ Fraction
# ──────────────────────────────────────────────────────────────────────────
_SCALAR_RE = re.compile(r"\s*(-?\d+)\s*(?:/\s*(\d+)\s*)?")


def _parse_scalar(raw: object) -> Fraction | None:
    """정수 또는 `p/q` 하나를 정확 유리수로. 소수·근삿값·bool은 None(정확하지 않다)."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return Fraction(raw)
    if isinstance(raw, str):
        if len(raw) > MAX_ANSWER_LEN:
            return None
        match = _SCALAR_RE.fullmatch(raw)
        if match is None:
            return None
        try:
            numerator = int(match.group(1))
            denominator = int(match.group(2)) if match.group(2) else 1
        except ValueError:  # 4,300자리 초과 정수
            return None
        if denominator == 0:
            return None
        return Fraction(numerator, denominator)
    return None


def parse_exact_value(raw: object) -> ExactValue | None:
    """답/재계산값 → 정확값. 정수·`p/q`·그 목록(`[1, 3, 6]`·`1, 3, 6`·JSON 배열)만 읽는다.

    읽을 수 없으면 None — 호출자가 `unverifiable`(검증기) 또는 `unclear`(교차검증 판정기)로
    돌린다. 소수(`0.5`)·부동소수(`73.0`)는 *정확하다고 말할 수 없으므로* 읽지 않는다.
    """
    if isinstance(raw, (list, tuple)):
        if not raw:
            return None
        items = [_parse_scalar(item) for item in raw]
        if any(item is None for item in items):
            return None
        return tuple(item for item in items if item is not None)
    if isinstance(raw, str):
        text = raw.strip()
        bracketed = text.startswith("[") and text.endswith("]")
        if bracketed:
            text = text[1:-1]
        if bracketed or "," in text:
            parts = [_parse_scalar(part) for part in text.split(",")]
            if not parts or any(part is None for part in parts):
                return None
            return tuple(part for part in parts if part is not None)
        return _parse_scalar(text)
    return _parse_scalar(raw)


def format_exact_scalar(value: Fraction) -> str | None:
    """정확 직렬화 — 4,300자리 변환 한도를 넘는 값은 None(말없이 잘라 쓰지 않는다)."""
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_SERIALIZED_BITS:
        return None
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def format_exact_value(value: ExactValue) -> str:
    """정확값 → 문자열(`73`·`1/2`·`[1, 3, 6]`). 직렬화할 수 없을 만큼 크면 빈 문자열."""
    if isinstance(value, tuple):
        parts = [format_exact_scalar(item) for item in value]
        if any(part is None for part in parts):
            return ""
        return "[" + ", ".join(part for part in parts if part is not None) + "]"
    return format_exact_scalar(value) or ""
