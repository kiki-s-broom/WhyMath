"""T2R(반복 회차 · GOLD-42 · F-02) — 앞말·꼬리가 붙은 채점 입력에서 마지막 수식 조각을 고른다.

1단계 AI 대체 50건에서 맞는 식·값이 든 입력 13개가 오답 처리됐다
(`f(0)은 8이에요?` · `f(2)는 6*2 - 8이에요?` · `-3*5 + 3 하면 뭔가요?`).
지금 채점기(`golden.grade`)는 정해 둔 접두·꼬리만 떼므로, 그 밖의 한국어가 앞뒤에 붙으면
파싱에 실패해 오답이 된다.

규칙(FINDINGS 「판정 오류」의 다시 채점 방법 그대로):
입력에서 **숫자가 든 마지막 수식 조각**을 고르고, 그 조각에 `=`가 있으면 **마지막 `=` 뒤**만
답으로 본다. 수식 조각 = 공백을 지운 뒤 숫자·`x`·연산자·괄호·소수점·`=`만 이어진 덩어리.

- 옛 자산은 없다(HARVEST.md 「반복 슬롯 T2R 경계 (S26R)」 — 후보 `verify_final_answer`는
  측정 후 버림). 그래서 golden 안에 새로 썼다(1회차 S27 선례).
- 기능 플래그 `GOLDEN_T2R_GRADE=1`일 때만 쓰인다(기본 꺼짐). 값이 정확히 `1`일 때만 켜진다.
- `golden.grade.is_correct`가 **파싱에 실패했을 때만** 부른다. 정상으로 읽힌 입력
  (`12 같아요` → 12)의 판정은 건드리지 않는다 — 플래그를 켜도 그 입력은 뒤집히지 않는다.
- 공백을 지우고 100자를 넘는 입력은 조각을 고르지 않는다(붙여넣기 속 `x=0`이 우연히 정답과
  맞은 사례 — 가짜 720 실측 1건 · S27R).
"""

from __future__ import annotations

import os
import re
import unicodedata

# 플래그 이름(공유 계약 「기능 플래그·환경변수」의 반복 회차 추가분)
FLAG_ENV = "GOLDEN_T2R_GRADE"

# 학생이 쓰는 빼기(U+2212)·곱셈(×·가운뎃점)·나눗셈(÷) 기호 — golden.grade와 같은 표
_SYMBOL_MAP = str.maketrans({"\u2212": "-", "\u00d7": "*", "\u00f7": "/", "\u00b7": "*"})
# 수식 조각: 숫자·x·연산자·괄호·소수점·등호만 이어진 덩어리
_FRAGMENT = re.compile(r"[0-9x+\-*/^().=]+")
_DIGIT = re.compile(r"[0-9]")
# 공백을 지운 입력이 이보다 길면 조각을 고르지 않는다(golden.grade.MAX_INPUT_LEN과 같은 값)
MAX_TEXT_LEN = 100


def t2r_grade_enabled() -> bool:
    """플래그가 켜졌는가 — 값이 정확히 `1`일 때만(빈 값·`true`·`0`은 꺼짐). 호출 시점에 읽는다."""
    return os.environ.get(FLAG_ENV) == "1"


def last_math_fragment(text: str) -> str | None:
    """숫자가 든 마지막 수식 조각의 답 부분. 없으면 None.

    예: `f(0)은 8이에요?` → `8` · `f(3)=-3-5 같은거야?` → `-3-5` · `6(2)-8=-4요?` → `-4`(끝값) ·
    `f(0)은 뭔가요?` → `0`(문항 정답이 아니면 결과는 오답) · `답 모름` → None ·
    공백을 지우고 100자를 넘는 입력(붙여넣기) → None.
    """
    s = unicodedata.normalize("NFKC", text).translate(_SYMBOL_MAP)
    s = re.sub(r"\s+", "", s)
    if len(s) > MAX_TEXT_LEN:
        return None
    fragments: list[str] = _FRAGMENT.findall(s)
    for fragment in reversed(fragments):
        # 끝의 마침표는 문장 부호다(`1이라고 생각해요.`의 `.`이 따로 잡힐 때)
        answer = fragment.rsplit("=", 1)[-1].rstrip(".")
        if _DIGIT.search(answer):
            return answer
    return None
