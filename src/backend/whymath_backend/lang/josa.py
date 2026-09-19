"""한국어 조사 받침 판별 헬퍼 — 동등문제 생성기 계통 결함 수정(S2-08·S3-12·결정론·순수).

동등문제 생성기(S2-o 계열)는 발문·풀이 템플릿에서 조사를 **선행 수사의 받침과 무관하게 하드
코딩**해 왔다("0와 4"·"13 를 풀어"·"밑 6를"·"−3와"). 이 모듈은 선행 값(정수·한글 단어·일부
문자열)의 받침 유무를 판별해 올바른 조사를 고른다.

핵심 원칙 — **수(數)의 받침은 "표기 글자"가 아니라 "한국어 읽기(한자어·Sino-Korean)의 마지막
음절"이 지배**한다. 수학 수량은 한자어로 읽으므로(예 13=십삼·100=백), 정수의 받침은 아래
일의 자리 읽기 표 + 0으로 끝나는 자리(십·백·천·영)로 결정한다. 표기 마지막 숫자(glyph)로
판별하면 틀린다(예 13의 끝 글자 '3'=삼→받침 有가 맞지만, 10의 끝 글자 '0'은 '영'이 아니라
'십'이 지배 → 둘 다 받침 有라 우연히 맞을 뿐, 20/100은 glyph만으로 오판).

S3-12 확장 — **수식 꼬리(tail) 읽기**: S3-09 AI 검수가 확정한 조사 계통 결함("x² 는"→은·
"18² 로"→으로·"17C3 를"→을·"1/5 는"→은·"0.8 는"→은·"(x-6)로"→으로·"|x-1| 가"→이)은 전부
수식 꼬리의 한국어 읽기가 마지막 음절을 지배하는 사례다. `_tail_reading`이 꼬리 규칙(거듭제곱=
"제곱"·분수="분모분의 분자"·소수=끝자리 낱자 읽기·닫는 괄호/절댓값 기호=묵음·후행 숫자열·
라틴/그리스 문자 읽기)으로 판별을 확장한다. 판별이 정말 불가한 형태(√ 혼합 분수 등)만 None
(정직 한계 — 호출부 안전 기본).

7계층: L3 지역(스켈레톤 생성기 전용 헬퍼). import는 표준 라이브러리만 — 상위 계층 참조 0(순수
함수). 표현이 아니라 값의 언어적 사실만 다룬다.
"""

from __future__ import annotations

import re
from typing import NamedTuple

__all__ = [
    "TailReading",
    "eul_reul",
    "eun_neun",
    "euro_ro",
    "has_batchim_hangul",
    "has_batchim_number",
    "has_batchim_text",
    "i_ga",
    "josa",
    "tail_reading",
    "wa_gwa",
]

# 일의 자리 한자어 읽기의 받침 유무(有=True) — 0=영(ㅇ)·1=일(ㄹ)·2=이(無)·3=삼(ㅁ)·4=사(無)·
# 5=오(無)·6=육(ㄱ)·7=칠(ㄹ)·8=팔(ㄹ)·9=구(無). 이 표가 모든 정수 받침 판별의 단일 진실 원천.
_ONES_DIGIT_BATCHIM: dict[int, bool] = {
    0: True,
    1: True,
    2: False,
    3: True,
    4: False,
    5: False,
    6: True,
    7: True,
    8: True,
    9: False,
}

# 일의 자리 읽기의 'ㄹ' 받침 유무 — 일(1)·칠(7)·팔(8)만 ㄹ. (으)로 예외 판별에 쓴다.
_ONES_DIGIT_RIEUL: frozenset[int] = frozenset({1, 7, 8})

# 한글 음절 유니코드 블록 시작(가)·종성(받침) 개수 28(0=받침 없음).
_HANGUL_BASE = 0xAC00
_HANGUL_END = 0xD7A3
_JONGSEONG_COUNT = 28

# 'ㄹ' 받침 종성 인덱스 — (으)로 조사는 'ㄹ' 받침일 때 '(으)로'가 아니라 '로'를 쓴다(예외).
_JONGSEONG_RIEUL = 8

# 라틴 문자 한국어 읽기의 받침 — 받침 有: l(엘)·m(엠)·n(엔)·r(알). 그중 ㄹ 받침: l·r.
# 나머지(a=에이·b=비·c=씨·x=엑스 …)는 마지막 음절에 받침이 없다. 수식 변수 읽기 관례 기준.
_LATIN_BATCHIM: frozenset[str] = frozenset("lmnr")
_LATIN_RIEUL: frozenset[str] = frozenset("lr")

# 그리스 문자 읽기 — 통용 기호는 전부 모음 끝(π=파이·θ=세타·α=알파·β=베타·ω=오메가 …).
_GREEK_NO_BATCHIM = "πθαβγδλμσφω"

# 읽지 않는 닫는 기호 — 닫는 괄호·절댓값 막대·렌더 중점(·) 등은 읽기의 마지막 음절이 아니다.
_SILENT_TRAILING = ")]}|·"

# 수식 꼬리 정규식(전부 결정론) — 거듭제곱(^n·**n)·소수·정수 분수·후행 숫자열.
_EXPONENT_TAIL_RE = re.compile(r"(?:\^|\*\*)\s*[0-9]+$")
_DECIMAL_TAIL_RE = re.compile(r"[0-9]+\.([0-9])$")
_INT_FRACTION_RE = re.compile(r"^\(?\s*(-?[0-9]+)\s*\)?\s*/\s*\(?\s*-?[0-9]+\s*\)?$")
_TRAILING_DIGITS_RE = re.compile(r"([0-9]+)$")


class TailReading(NamedTuple):
    """토큰 마지막 읽기 음절의 언어 사실 — (받침 유무, ㄹ 받침 여부). ㄹ이면 batchim도 True."""

    batchim: bool
    rieul: bool


def has_batchim_number(n: int) -> bool:
    """정수 n의 한자어 읽기 마지막 음절에 받침이 있으면 True.

    규칙: 일의 자리가 0이 아니면 일의 자리 읽기(_ONES_DIGIT_BATCHIM)가 마지막 음절을 지배한다.
    일의 자리가 0이면 십·백·천·(수 0이면 영) 자리가 마지막 음절을 지배하는데, 십(ㅂ)·백(ㄱ)·
    천(ㄴ)·영(ㅇ)은 **모두 받침이 있으므로** …0으로 끝나는 정수와 0 자체는 항상 받침 有다.
    음수는 부호가 읽기의 마지막 음절을 바꾸지 않으므로(예 −3=음의 삼) 절댓값의 읽기가 지배한다.
    """
    return _number_reading(n).batchim


def _number_reading(n: int) -> TailReading:
    """정수 읽기 마지막 음절의 (받침, ㄹ 받침) — has_batchim_number의 ㄹ 확장판(내부 코어)."""
    magnitude = abs(int(n))
    ones = magnitude % 10
    if ones != 0:
        return TailReading(_ONES_DIGIT_BATCHIM[ones], ones in _ONES_DIGIT_RIEUL)
    # 일의 자리 0 → 십(ㅂ)·백(ㄱ)·천(ㄴ)·영(ㅇ) 계열 지배 → 전부 받침 有·ㄹ 아님.
    return TailReading(True, False)


def has_batchim_hangul(ch: str) -> bool:
    """한글 음절 문자 ch의 종성(받침) 유무 — 받침 있으면 True(가~힣 밖이면 False).

    종성 인덱스 = (코드포인트 − 0xAC00) % 28. 0이면 받침 없음(예 '가'·'노'), 그 외 받침 있음.
    """
    if not ch:
        return False
    code = ord(ch[-1])
    if not (_HANGUL_BASE <= code <= _HANGUL_END):
        return False
    return (code - _HANGUL_BASE) % _JONGSEONG_COUNT != 0


def _jongseong_index(ch: str) -> int:
    """한글 음절 ch의 종성 인덱스(0~27) — 받침 없음 0. 한글 밖이면 −1(불명)."""
    if not ch:
        return -1
    code = ord(ch[-1])
    if not (_HANGUL_BASE <= code <= _HANGUL_END):
        return -1
    return (code - _HANGUL_BASE) % _JONGSEONG_COUNT


def tail_reading(token: str) -> TailReading | None:
    """토큰의 읽기 마지막 음절 (받침, ㄹ 받침) 판별 — 불가하면 None(정직 한계).

    판별 순서(먼저 걸린 규칙이 지배·전부 한국어 독법의 언어 사실):
      ① 정수 전체("13"·"-46656") → 수 읽기(_number_reading).
      ② 한글 끝("값"·"수") → 음절 종성.
      ③ 정수/정수 분수("1/5"·"40/10") → "분모분의 분자"라 **분자** 수 읽기 지배.
         '/'가 있는데 정수/정수가 아니면(√3/2 등) 분자 읽기를 문자로 알 수 없어 None.
      ④ 닫는 기호 꼬리(")"·"]"·"|"·"·")는 묵음 — 벗겨내고 재판별("f(3)"→"3"·"|x-1|"→"1").
      ⑤ 거듭제곱 꼬리("x²"·"18²"·"10^5"·"a**2") → 읽기 "…제곱" → 곱(ㅂ 받침·ㄹ 아님).
      ⑥ 이분의 일 기호("½") → 읽기 "…이분의 일" → 일(ㄹ 받침).
      ⑦ 소수("0.8") → 소수부는 낱자 읽기라 마지막 숫자 낱자(팔)가 지배.
      ⑧ 후행 숫자열("17C3"→3=삼·"x = 12"→12=십이) → 그 수의 읽기 지배.
      ⑨ 라틴/그리스 문자 끝("x"=엑스·"r"=알·"π"=파이) → 문자 읽기 표.
    """
    stripped = token.strip()
    if not stripped:
        return None
    # ① 정수 전체.
    try:
        return _number_reading(int(stripped))
    except ValueError:
        pass
    # ② 한글 끝.
    jong = _jongseong_index(stripped[-1])
    if jong >= 0:
        return TailReading(jong != 0, jong == _JONGSEONG_RIEUL)
    # ③ 분수 — 정수/정수만 분자 지배. 그 외('/' 포함)는 분자 읽기 불명 → None.
    if "/" in stripped:
        match = _INT_FRACTION_RE.match(stripped)
        if match is not None:
            return _number_reading(int(match.group(1)))
        return None
    # ④ 닫는 기호(묵음) 벗기기 — 남은 몸통으로 재판별.
    if stripped[-1] in _SILENT_TRAILING:
        return tail_reading(stripped.rstrip(_SILENT_TRAILING))
    # ⑤ 거듭제곱 꼬리 — "제곱"의 곱(ㅂ 받침·ㄹ 아님).
    if stripped[-1] in "²³" or _EXPONENT_TAIL_RE.search(stripped) is not None:
        return TailReading(True, False)
    # ⑥ ½ — "이분의 일"의 일(ㄹ 받침).
    if stripped[-1] == "½":
        return TailReading(True, True)
    # ⑦ 소수 — 소수부 낱자 읽기(마지막 숫자 하나가 지배·0=영도 받침 有).
    decimal = _DECIMAL_TAIL_RE.search(stripped)
    if decimal is not None:
        digit = int(decimal.group(1))
        return TailReading(_ONES_DIGIT_BATCHIM[digit], digit in _ONES_DIGIT_RIEUL)
    # ⑧ 후행 숫자열 — 마지막에 붙은 수의 읽기 지배("17C3"→3·"sqrt(11"→11).
    digits = _TRAILING_DIGITS_RE.search(stripped)
    if digits is not None:
        return _number_reading(int(digits.group(1)))
    # ⑨ 라틴/그리스 문자 읽기.
    last = stripped[-1].lower()
    if "a" <= last <= "z":
        return TailReading(last in _LATIN_BATCHIM, last in _LATIN_RIEUL)
    if last in _GREEK_NO_BATCHIM:
        return TailReading(False, False)
    return None


def has_batchim_text(token: str) -> bool | None:
    """선행 토큰 token의 받침 유무 — 수·수식 꼬리 읽기 기반(tail_reading 위임).

    정수는 수 읽기, 한글 끝은 음절 종성, 수식 꼬리(거듭제곱·분수·소수·괄호·후행 숫자·문자)는
    S3-12 확장 규칙으로 판별한다. 판별 불가(√ 혼합 분수 등 독법이 문자로 안 보이는 형태)면
    None을 반환한다 — 호출부는 None일 때 안전 기본(받침 有)을 쓰거나 고정 값 매핑으로 보정한다
    (정직 한계).
    """
    reading = tail_reading(token)
    return None if reading is None else reading.batchim


def josa(
    token: str,
    with_batchim: str,
    without_batchim: str,
    *,
    default_batchim: bool = True,
) -> str:
    """선행 token에 맞는 조사 선택 — 받침 有면 with_batchim, 無면 without_batchim.

    판별 불가(has_batchim_text=None)면 default_batchim(안전 기본 True — 을/과/은/이 계열)을
    적용한다. 저수준 선택기이며, 상위 편의 래퍼(eul_reul 등)가 이를 호출한다.
    """
    batchim = has_batchim_text(token)
    if batchim is None:
        batchim = default_batchim
    return with_batchim if batchim else without_batchim


def eul_reul(token: str) -> str:
    """목적격 조사 을/를 — 받침 有 '을'·無 '를'."""
    return josa(token, "을", "를")


def wa_gwa(token: str) -> str:
    """접속 조사 와/과 — 받침 有 '과'·無 '와'."""
    return josa(token, "과", "와")


def eun_neun(token: str) -> str:
    """보조사 은/는 — 받침 有 '은'·無 '는'."""
    return josa(token, "은", "는")


def i_ga(token: str) -> str:
    """주격 조사 이/가 — 받침 有 '이'·無 '가'."""
    return josa(token, "이", "가")


def euro_ro(token: str) -> str:
    """부사격 조사 (으)로 — 받침 無 또는 'ㄹ' 받침이면 '로', 그 외 받침이면 '으로'.

    한국어 예외: 'ㄹ' 받침 뒤에는 '으로'가 아니라 '로'를 쓴다(예 '물로'·'1(일)로'·'x½(…의 일)로').
    판별은 tail_reading(수 읽기·수식 꼬리·한글 종성)에 위임하고, 불가면 안전 기본 '으로'.
    """
    reading = tail_reading(token)
    if reading is None:
        return "으로"  # 불명 — 안전 기본
    if not reading.batchim or reading.rieul:
        return "로"
    return "으로"
