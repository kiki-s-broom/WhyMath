"""슬롯 T3R 튜터 응답 유출 검사(S32R · F-07) — 튜터가 정답을 **새로** 말했는가.

S31R 출처 표(`golden/reports_phase1r/S31R/보고.md` 2절)의 세 칸을 이 모듈이 가른다.
- ⓐ 새로 말함: 튜터 문장에 정답이 드러나고, 그 정답이 이번 문제의 학생 입력(앞 턴 포함)에 없다 →
  **막는다**.
- ⓑ 학생 값 되짚음: 학생이 이미 낸 정답 값을 튜터가 되짚는다 → 막지 않는다(되묻기 루브릭 C1).
- ⓒ 부호 반대 오답 되짚음(`-11` · 정답 `11`): 정답이 드러난 것이 아니다 → 막지 않는다.

정답이 드러났는가(두 축 · 하나라도 참이면 드러남)
- 글자 축: M1 규칙(`golden.sim.metrics.detect_answer_leakage` · 측정 도구와 같은 규칙)에 **부호
  경계**를
  더한다. 양수 정답 `11`은 `-11` 속에 있으면 드러난 것이 아니다(S31R ⓒ 12/21세션). 분수
  정답(`2/3`)도
  수 경계로 맞춘다. M1이 유보(undecidable)하는 1글자 정답은 이 축에서 판정하지 않는다.
- 값 축: 옛 `scan_value_exposure`의 골든 사본(`golden.eval.value_exposure`). 계산하면 정답이 되는 식
  (`3*5+1` · 1글자 정답의 `6*2-8`)을 잡는다.

학생 입력에 그 정답이 있었는가(되짚기 판정)는 같은 두 축으로 보되, 1글자 수 정답은 수 경계로 맞춘다
(학생이 `4요`라고 썼으면 튜터의 `4`는 되짚기다 — 유보하면 되짚기를 새 유출로 잘못 막는다).
문제 본문은 되짚기 근거로 쓰지 않는다. `f(0)` 문항(LF-05 `4x + 8` · 정답 8)처럼 본문의 수를 짚는
것이 곧
정답을 알려 주는 문항이 있기 때문이다(S32R 실측 — 본문에 정답 수가 든 문항 7개).

M1 정의(측정)는 바꾸지 않는다 — 이 모듈은 GP-4 행동이고, 측정은 그대로 M1이 한다(공유 계약).
순수 함수다(DB·네트워크·LLM 없음).
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from golden.eval.value_exposure import ValueExposure, scan_value_exposure
from golden.sim.metrics import LeakageVerdict, detect_answer_leakage

# 기능 플래그 — 값이 정확히 `1`일 때만 켜진다(기본 끔 · 공유 계약 플래그 표)
FLAG_ENV: Final = "GOLDEN_T3R_LEAK_GUARD"

# eval_log에 함께 남기는 검사기 판 — 규칙이 바뀌면 올린다(기록끼리 섞어 세지 않게)
GUARD_VERSION: Final = "t3r-v1"

# 두 번째 응답도 걸리면 쓰는 고정 문장(지시서 S32R 할 일 2)
FIXED_SENTENCE: Final = "식에서 x 자리에 주어진 값을 넣은 식을 먼저 써 볼래요?"

# 빼기 기호 변형(U+2212 · 전각은 NFKC가 처리) → `-`
_MINUS: Final = str.maketrans({"−": "-", "–": "-"})
# M1 정규화와 같은 구조 문자 제거(괄호·공백·쉼표·`$`·중괄호·역슬래시) — 표기 차이를 흡수한다
_STRUCTURAL: Final = re.compile(r"[$\\{}()\s,]")
_LATEX_COMMANDS: Final = re.compile(r"\\[a-zA-Z]+")
# 수 정답(정수·소수·분수 · 부호 허용)
_NUMBER_ANSWER: Final = re.compile(r"-?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?")

Axis = Literal["glyph", "value"]


def leak_guard_enabled() -> bool:
    """`GOLDEN_T3R_LEAK_GUARD=1`일 때만 참. 호출 시점에 읽는다(기본 끔)."""
    return os.environ.get(FLAG_ENV) == "1"


def _norm(text: str) -> str:
    """M1과 같은 정규화 + 빼기 기호 통일."""
    s = unicodedata.normalize("NFKC", text).translate(_MINUS).lower()
    s = _LATEX_COMMANDS.sub("", s)
    return _STRUCTURAL.sub("", s)


def _number_in(text: str, answer: str) -> bool:
    """수 정답이 수 경계·부호 경계로 본문에 있는가. 양수 정답 앞의 `-`는 다른 수다(`-11` ≠ `11`)."""
    lead = r"(?<![\d./])" if answer.startswith("-") else r"(?<![\d./\-])"
    return re.search(rf"{lead}{re.escape(answer)}(?![\d./])", _norm(text)) is not None


def _glyph_exposed(text: str, answer: str) -> bool | None:
    """글자 축 — True 드러남 · False 아님 · None 판정 유보(M1이 유보하는 짧은 정답)."""
    verdict = detect_answer_leakage(unicodedata.normalize("NFKC", text).translate(_MINUS), answer)
    if verdict is LeakageVerdict.undecidable:
        return None
    if verdict is LeakageVerdict.clean:
        return False
    norm_answer = _norm(answer)
    if _NUMBER_ANSWER.fullmatch(norm_answer):
        # M1은 `-11`에서도 `11`을 찾는다 — 부호 경계로 다시 본다(S31R ⓒ)
        return _number_in(text, norm_answer)
    return True


def exposure_axis(text: str, answer: str) -> Axis | None:
    """본문에 정답이 드러났으면 그 축(glyph · value), 아니면 None. 유보는 드러나지 않은 것으로 본다.

    유보를 '드러남'으로 접으면 1글자 정답 문항의 모든 되묻기를 막게 된다. 1글자 정답의 노출은 값
    축이 본다.
    """
    if _glyph_exposed(text, answer):
        return "glyph"
    if scan_value_exposure(text, answer).outcome is ValueExposure.exposed:
        return "value"
    return None


def _student_said(student_texts: Sequence[str], answer: str) -> bool:
    """이번 문제의 학생 입력 중 정답이 든 것이 있었나(되짚기 판정 · 1글자 수 정답은 수 경계로)."""
    norm_answer = _norm(answer)
    is_number = _NUMBER_ANSWER.fullmatch(norm_answer) is not None
    for text in student_texts:
        if exposure_axis(text, answer) is not None:
            return True
        if is_number and _number_in(text, norm_answer):
            return True
    return False


@dataclass(frozen=True)
class LeakCheck:
    """튜터 응답 1개의 검사 결과. `new_leak`이 참일 때만 막는다(ⓐ)."""

    axis: Axis | None  # 정답이 드러난 축(없으면 None)
    student_echo: bool  # 학생 입력에 같은 정답이 있었다(ⓑ) — axis가 None이면 늘 False

    @property
    def new_leak(self) -> bool:
        """ⓐ 새로 말함 — 드러났고, 되짚기가 아니다."""
        return self.axis is not None and not self.student_echo


def check_reply(reply: str, answer: str, student_texts: Sequence[str]) -> LeakCheck:
    """튜터 응답 `reply`가 정답을 새로 말했는가. `student_texts` = 이번 문제의 학생 입력 전부(이번
    입력 포함)."""
    axis = exposure_axis(reply, answer)
    echo = axis is not None and _student_said(student_texts, answer)
    return LeakCheck(axis=axis, student_echo=echo)
