"""골든 패스 채점(GP-5) 단위 테스트 — grade.is_correct가 공유 계약의 채점 규칙대로 판정하는지 본다.

DB·LLM 없이 돈다(순수 함수).
"""

import logging

import pytest
from golden.problems import Problem, load_problems

from golden import grade


def _problem(answer: str, kind: str) -> Problem:
    """채점에 필요한 필드만 채운 문항(스키마 나머지 필드는 채점에 쓰이지 않는다)."""
    return {
        "id": "LF-TEST",
        "stem": "테스트 문항",
        "answer": answer,
        "answer_kind": kind,
        "hint1": "",
        "concept": "[9수02-14]",
        "source": "authored:S5",
    }


NUM_NEG12 = _problem("-12", "number")
NUM_3_2 = _problem("3/2", "number")
EXPR_2X1 = _problem("2*x + 1", "expression")


# ── 맞는 입력 6종(지시서) + 정규화 규칙(U+2212·전각·입니다) ──────────────────────
@pytest.mark.parametrize(
    ("problem", "text"),
    [
        (NUM_NEG12, "-12"),  # ① 그대로
        (NUM_NEG12, " -12 "),  # ② 앞뒤 공백
        (NUM_NEG12, "답: -12"),  # ③ 답: 접두
        (EXPR_2X1, "y=2x+1"),  # ④ y= 접두 + 곱셈 생략
        (EXPR_2X1, "2x + 1"),  # ⑤ 곱셈 생략 + 공백
        (NUM_3_2, "3/2"),  # ⑥-a 분수
        (NUM_3_2, "1.5"),  # ⑥-b 소수(분수·소수 동치)
        (NUM_NEG12, "−12"),  # 수학 빼기 기호 U+2212
        (NUM_NEG12, "－１２"),  # 전각 숫자·전각 빼기
        (NUM_NEG12, "-12입니다"),  # 입니다 꼬리
        (EXPR_2X1, "f(x) = 1 + 2x"),  # f(x)= 접두 + 항 순서 바뀜
        (EXPR_2X1, "y = 2*x + 1"),  # 곱셈 기호를 쓴 경우
    ],
)
def test_correct_inputs_are_graded_correct(problem: Problem, text: str) -> None:
    assert grade.is_correct(problem, text) is True


# ── 틀린 입력 4종(지시서) ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("problem", "text"),
    [
        (NUM_NEG12, "12"),  # 다른 수(부호 실수)
        (EXPR_2X1, "2x - 1"),  # 다른 식
        (NUM_NEG12, ""),  # 빈 문자열
        (NUM_NEG12, "모르겠어요"),  # 글로 쓴 답
        (NUM_3_2, "1.4999"),  # 허용 오차(1e-9)보다 큰 차이
        (NUM_NEG12, "x"),  # number 문항에 식 — 수가 아니면 오답
    ],
)
def test_wrong_inputs_are_graded_wrong(problem: Problem, text: str) -> None:
    assert grade.is_correct(problem, text) is False


# ── 파싱 불가 입력: 예외 없이 오답 + 예외 타입명이 로그에 남는다 ─────────────────
@pytest.mark.parametrize(
    "text",
    ["2x +* 1", "((3", "__import__('os')", "3=5", "9" * 200],
)
def test_unparseable_input_is_wrong_without_exception(
    text: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="golden.grade"):
        result = grade.is_correct(EXPR_2X1, text)
    assert result is False
    # 침묵 실패 금지 — 파싱 실패 로그에 예외 타입명(예: ValueError·SyntaxError)이 들어 있다
    messages = [r.getMessage() for r in caplog.records if r.name == "golden.grade"]
    assert any("예외=" in m and m.split("예외=")[1].strip() for m in messages)


# ── 실제 문항 30개: 각 문항의 정답 문자열은 자기 자신에게 정답이다 ────────────────
@pytest.mark.parametrize("problem", load_problems(), ids=lambda p: p["id"])
def test_every_problem_answer_grades_itself_correct(problem: Problem) -> None:
    assert grade.is_correct(problem, problem["answer"]) is True
    assert grade.is_correct(problem, "모르겠어요") is False
