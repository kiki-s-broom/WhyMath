"""T1 평가기 — 튜터 되묻기 1건을 옛 결정론 루브릭(사본)으로 재고 판정을 돌려준다(S22 · 인용 F-01).

무엇을 하는가
- `evaluate_tutor_reply(reply, answer)`가 사본 `rubric_copy`의 두 함수를 불러
  유출 여부·루브릭 통과·근거를 한 덩어리(`RubricVerdict`)로 낸다.
  순수 함수 — LLM·DB·파일을 쓰지 않는다.
- 학생 답(`student_text`)과 문제 본문(`problem_text`)을 함께 주면, 유출이 **어디서 왔는지**
  (`leak_origin`)도 적는다. S21 측정에서 골든 로그 되묻기 `leaked` 87건이 전부 학생이 말한 값을
  되받았거나(72) 문제 식에 든 토큰(15)이었다 — M1 답 유출률이 이 둘을 새 유출과 섞어 세지 않게
  재료를 남기는 것이다. 판정 자체(`leakage`)는 옛 탐지기 그대로이며 이 칸이 바꾸지 않는다.

무엇을 하지 않는가(지시서 S22 "하지 말 것")
- 튜터 응답을 바꾸거나 막지 않는다 — 결과는 `golden.eval_log`에 기록만 한다(api.py).
- 되묻기 루브릭 v0(C1~C5)를 재지 않는다. 특히 F-01 본체인 C5(틀린 곳 겨냥)는 이 평가기로 잴 수 없다
  (사람 판정 — S23·S25).

기능 플래그
- `GOLDEN_T1_RUBRIC=1`일 때만 api.py가 이 평가기를 부른다. 기본은 끔(`0` 또는 없음).
  값은 import 시점이 아니라 요청을 처리하는 시점에 읽는다(테스트 픽스처가 켜고 끈다).
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict

from golden.eval.rubric_copy import LeakageVerdict, detect_answer_leakage, score_tutoring_response

# 기능 플래그 이름(공유 계약 「기능 플래그·환경변수」)
FLAG_ENV = "GOLDEN_T1_RUBRIC"

# 평가기 판본 — 기록(verdict_json)에 함께 남겨, 나중에 기준이 바뀌어도 어느 판정인지 알 수 있게 한다
EVALUATOR_VERSION = "t1-s22"

# 유출 출처 4가지
# - none          : 유출 아님(clean 또는 undecidable)
# - student_echo  : 학생이 이번 답에 이미 쓴 값을 튜터가 되받았다
# - problem_text  : 문제 본문에 이미 있는 토큰이다(학생은 말하지 않았다)
# - new           : 학생도 문제도 말하지 않은 정답을 튜터가 새로 말했다(진짜 유출 후보)
# - unknown       : 유출이지만 학생 답·문제 본문을 받지 못해 출처를 가리지 못했다
LeakOrigin = Literal["none", "student_echo", "problem_text", "new", "unknown"]


class RubricVerdict(BaseModel):
    """튜터 되묻기 1건의 T1 판정(기록용). 학생 화면에는 나가지 않는다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluator: str  # 평가기 판본(EVALUATOR_VERSION)
    leak: bool  # 옛 탐지기가 leaked로 판정했는가
    leakage: str  # 옛 탐지기 3상태 값 그대로(leaked · clean · undecidable)
    leak_origin: LeakOrigin  # 유출 출처(위 설명)
    passed: bool  # 옛 소형 루브릭 통과(유출 아님 AND 발문 있음)
    has_socratic_prompt: bool  # 발문 신호(물음표·발문어) 있음
    reasons: list[str]  # 옛 루브릭 근거 문자열 그대로


def rubric_enabled() -> bool:
    """`GOLDEN_T1_RUBRIC=1`일 때만 참. 호출 시점에 읽는다(기본 끔)."""
    return os.environ.get(FLAG_ENV) == "1"


def _leak_origin(
    leakage: LeakageVerdict,
    answer: str,
    student_text: str | None,
    problem_text: str | None,
) -> LeakOrigin:
    """유출 출처를 가린다 — 같은 옛 탐지기로 학생 답·문제 본문에도 정답이 있는지 본다."""
    if leakage is not LeakageVerdict.leaked:
        return "none"
    if student_text is None or problem_text is None:
        return "unknown"
    if detect_answer_leakage(student_text, answer) is LeakageVerdict.leaked:
        return "student_echo"
    if detect_answer_leakage(problem_text, answer) is LeakageVerdict.leaked:
        return "problem_text"
    return "new"


def evaluate_tutor_reply(
    reply: str,
    answer: str,
    *,
    student_text: str | None = None,
    problem_text: str | None = None,
) -> RubricVerdict:
    """튜터 되묻기 `reply`를 문항 정답 `answer` 기준으로 잰다(순수·결정론).

    `leak`·`leakage`·`passed`·`has_socratic_prompt`·`reasons`는 옛 함수 출력을 그대로 옮긴 것이다.
    `leak_origin`만 이 평가기가 더한 칸이다(학생 답·문제 본문을 줄 때만 가린다).
    """
    score = score_tutoring_response(reply, answer=answer)
    return RubricVerdict(
        evaluator=EVALUATOR_VERSION,
        leak=score.leakage is LeakageVerdict.leaked,
        leakage=score.leakage.value,
        leak_origin=_leak_origin(score.leakage, answer, student_text, problem_text),
        passed=score.passed,
        has_socratic_prompt=score.has_socratic_prompt,
        reasons=list(score.reasons),
    )
