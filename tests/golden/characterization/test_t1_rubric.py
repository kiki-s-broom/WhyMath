"""S21 특성화 — 슬롯 T1 옛 자산: 정답 유출 탐지기·소형 루브릭(F-01 · 다섯 걸음 ②).

옛 `whymath_backend.harness.pedagogical_rubric`의 함수 2개를 **옛 자리에서 그대로** 불러,
골든 패스 로그에서 고른 실제 튜터 발화 10개에 대한 **지금 출력**을 고정한다.
출력이 맞는지는 묻지 않는다 — 바뀌지 않는지만 본다. 틀려 보이는 출력도 고치지 않고 그대로 적었다.

- 대상 함수: `detect_answer_leakage(response, answer)` · `score_tutoring_response(response, *, answer)`.
  경계는 `golden/HARVEST.md` 「T1 경계 (S21)」 절에 먼저 적었다.
- 입력 10개 = 정답 유출(leaked) 3 · 판정 불가(undecidable) 2 · 깨끗함(clean) 5.
  전부 `golden/reports_no_students/` 아래 커밋된 로그의 **튜터 쪽 문장**이다(시드 아님 —
  시드 `golden/sim/seed/`는 학생 발화이고 Kiki 머신에만 있다). 발화자 출처는 본인·AI 시뮬레이션이며
  실제 중학생 발화는 없다.
- 옛 모듈은 이 테스트에서만 import한다. 골든 코드(`src/backend/golden/`)는 import하지 않는다
  (import-linter 계약 `golden-no-legacy`의 대상은 `golden` 패키지뿐이다 · 이 모듈은 LEGACY_MANIFEST에 있다).
- 두 함수 모두 LLM·DB·파일을 쓰지 않는다(순수 함수).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import pytest

from whymath_backend.harness.pedagogical_rubric import (
    LeakageVerdict,
    detect_answer_leakage,
    score_tutoring_response,
)

# 옛 모듈이 내는 근거 문자열(지금 값 그대로 — 바뀌면 특성화가 깨진 것)
_R_LEAKED = "정답 값이 발화에 노출됨 — 최상위 교수학 금기 위반."
_R_UNDECIDABLE = "정답 유출 판정 불가(짧음·모호) — 보수적으로 미유출 처리."
_R_CLEAN = "정답 값 미노출(clean)."
_R_SOCRATIC = "소크라테스 발문 신호 존재."
_R_NO_SOCRATIC = "소크라테스 발문 신호 없음."


@dataclass(frozen=True)
class Case:
    """특성화 입력 1개와 지금 출력."""

    no: int  # 번호
    source: str  # 로그 위치(파일 · 행 또는 재생 사례 번호)
    problem_id: str  # 문항 ID(golden/data/problems_linear_fn.json)
    answer: str  # 그 문항의 answer 필드 그대로
    response: str  # 튜터 쪽 문장 원문 그대로
    leakage: str  # detect_answer_leakage 지금 출력
    score: dict[str, Any]  # score_tutoring_response(...).model_dump(mode="json") 지금 출력


def _score(leakage: str, socratic: bool, passed: bool) -> dict[str, Any]:
    """기대 출력 dict를 만든다(값은 아래 표에서 손으로 정한다 — 옛 함수를 부르지 않는다)."""
    reason = {"leaked": _R_LEAKED, "undecidable": _R_UNDECIDABLE, "clean": _R_CLEAN}[leakage]
    return {
        "passed": passed,
        "no_answer_leak": leakage != "leaked",
        "leakage": leakage,
        "has_socratic_prompt": socratic,
        "reasons": [reason, _R_SOCRATIC if socratic else _R_NO_SOCRATIC],
    }


_CASES: list[Case] = [
    # ── 정답 유출(leaked) 3 ─────────────────────────────────────────────────────
    # 1. 학생이 이미 말한 정답을 튜터가 되받았다(AI · S12 재실행 입력 재생)
    Case(
        1,
        "S14/replay_full_after.json 사례 046 첫 턴",
        "LF-01",
        "-12",
        "f(5)는 -12라고 말했군요. 그 값을 얻기 위해 x 자리에 5를 넣어서 어떤 식을 세웠는지 말해 볼래요?",
        "leaked",
        _score("leaked", socratic=True, passed=False),
    ),
    # 2. 정답 토큰이 문제 식 자체에 들어 있다(ASCII 빼기 "-5x - 4" → 공백 제거 뒤 "-4" 일치)
    Case(
        2,
        "S14/replay_full_after.json 사례 044 첫 턴",
        "LF-09",
        "-4",
        "f(0)을 어떻게 구하는지 궁금한 거군요. f(x)라는 식에서 괄호 안의 x가 0이라는 뜻이니까, "
        "-5x - 4에서 x 자리에 0을 넣으면 어떤 식이 되는지 직접 써 볼래요?",
        "leaked",
        _score("leaked", socratic=True, passed=False),
    ),
    # 3. GP-5 판정 문장(오답 뒤 서버 문장) — 발문 신호가 없어 passed=False가 되는 유일한 사례
    Case(
        3,
        "S12/sim_no-setup_rerun_turns.csv 15행(kind=graded)",
        "LF-04",
        "-8",
        "이번 문제의 답은 -8이었어요. 다음 문제에서 다시 해 봐요.",
        "leaked",
        _score("leaked", socratic=False, passed=False),
    ),
    # ── 판정 불가(undecidable) 2 — 정답이 정규화 뒤 1글자 ─────────────────────────
    # 4. 정답 4 · 문장에 "-4"(학생의 틀린 값)가 있어도 판정을 유보한다(본인 S9 기록 재생)
    Case(
        4,
        "S10/replay_tutor_after.json 사례 'S9 7~10행' 세 번째 턴",
        "LF-03",
        "4",
        "x 자리에 2를 넣은 식을 계산한 값으로 -4를 말했군요. "
        "그 계산을 끝까지 해서 나온 값을 f(2)의 값으로 정리하면 얼마라고 말하겠어요?",
        "undecidable",
        _score("undecidable", socratic=True, passed=True),
    ),
    # 5. 정답 0 · LaTeX \( \) 구분자가 섞인 문장
    Case(
        5,
        "S14/replay_full_after.json 사례 031 첫 턴",
        "LF-06",
        "0",
        "어디서부터 막히는지 모르겠다고 했군요. 그럼 \\(f(-1)\\)이라는 표시는 \\(f(x)\\)에서 "
        "\\(x\\) 자리에 어떤 수를 넣으라는 뜻인지 말해 볼래요?",
        "undecidable",
        _score("undecidable", socratic=True, passed=True),
    ),
    # ── 깨끗함(clean) 5 ─────────────────────────────────────────────────────────
    # 6. LaTeX 분수 $-\frac{2}{3}$(학생의 뒤바뀐 값) — 정답 -3/2와 다르다
    Case(
        6,
        "S14/replay_full_before.json 사례 005 첫 턴",
        "LF-14",
        "-3/2",
        "기울기를 $-\\frac{2}{3}$라고 구했군요. 그 값을 얻기까지 y의 값의 증가량과 x의 값의 증가량을 "
        "각각 어떤 수로 놓았는지, 두 수를 쓴 식으로 보여 줄래요?",
        "clean",
        _score("clean", socratic=True, passed=True),
    ),
    # 7. LaTeX 나눗셈 $6\div(-9)$ — 분수 정답은 숫자 경로가 아니라 부분 문자열 경로로 간다
    Case(
        7,
        "S14/replay_full_before.json 사례 005 세 번째 턴",
        "LF-14",
        "-3/2",
        "분모에 x의 값의 증가량을 넣어 $6\\div(-9)$까지 식을 세운 셈이군요. "
        "그 나눗셈을 직접 계산해서 이 그래프의 기울기가 얼마인지 말해 볼래요?",
        "clean",
        _score("clean", socratic=True, passed=True),
    ),
    # 8. 튜터 대체 문장(FAKE_PREFIX + hint1 — LLM이 실패했을 때 학생 화면에 나가는 문장)
    Case(
        8,
        "S14/replay_full_after.json 사례 019 두 번째 턴",
        "LF-04",
        "-8",
        "어느 부분이 막히는지 한 가지만 말해 줄래? x 자리에 3을 넣으면 식이 어떻게 되는지 말해 볼래?",
        "clean",
        _score("clean", socratic=True, passed=True),
    ),
    # 9. FINDINGS 1위 근거 3번 문장(유니코드 빼기 "−3×5" · 학생의 틀린 값 15)
    Case(
        9,
        "S12/sim_sign-slip_rerun_turns.csv 4행",
        "LF-01",
        "-12",
        "−3×5를 15라고 계산했군요. 그 계산까지 넣어서 f(5)의 값을 직접 구해 말해 볼래요?",
        "clean",
        _score("clean", socratic=True, passed=True),
    ),
    # 10. 정답과 같은 "−4"가 있지만 유니코드 빼기(U+2212)라 일치하지 않는다 — 2번과 짝
    Case(
        10,
        "S14/replay_full_after.json 사례 064 두 번째 턴",
        "LF-09",
        "-4",
        "−5×0이 0이라고 확인했군요. 그 0을 원래 식에 넣으면 −4와 함께 어떤 계산이 남는지 말해 볼래요?",
        "clean",
        _score("clean", socratic=True, passed=True),
    ),
]

_IDS = [f"{c.no:02d}-{c.problem_id}-{c.leakage}" for c in _CASES]

# 결정성 검사 반복 횟수(지시서 S21 할 일 4)
_REPEAT = 100


def test_case_mix_is_fixed() -> None:
    """입력 구성 동결 — 10개 · 유출 3 · 판정 불가 2 · 깨끗함 5 · 번호 1~10 · 발화 중복 없음."""
    assert [c.no for c in _CASES] == list(range(1, 11))
    assert Counter(c.leakage for c in _CASES) == {"leaked": 3, "undecidable": 2, "clean": 5}
    assert len({c.response for c in _CASES}) == len(_CASES)


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_detect_answer_leakage_output_unchanged(case: Case) -> None:
    """`detect_answer_leakage` 지금 출력(3상태 중 하나)이 그대로인가."""
    verdict = detect_answer_leakage(case.response, case.answer)
    assert isinstance(verdict, LeakageVerdict)
    assert verdict.value == case.leakage


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_score_tutoring_response_output_unchanged(case: Case) -> None:
    """`score_tutoring_response` 지금 출력(필드 5개 전부 · 근거 문자열 포함)이 그대로인가."""
    score = score_tutoring_response(case.response, answer=case.answer)
    assert score.model_dump(mode="json") == case.score


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_same_input_same_output_100_times(case: Case) -> None:
    """결정성 — 같은 입력을 100번 넣어 두 함수의 출력이 각각 한 가지뿐인가(비결정이면 버린다)."""
    verdicts = {detect_answer_leakage(case.response, case.answer) for _ in range(_REPEAT)}
    dumps = {
        repr(score_tutoring_response(case.response, answer=case.answer).model_dump(mode="json"))
        for _ in range(_REPEAT)
    }
    assert len(verdicts) == 1
    assert len(dumps) == 1
