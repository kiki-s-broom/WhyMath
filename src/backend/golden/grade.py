"""골든 패스 정답 판정(GP-5) — SymPy로 학생 답과 정답을 비교한다."""

from __future__ import annotations

from golden.problems import Problem


def is_correct(problem: Problem, student_text: str) -> bool:
    """학생 답이 정답인지 판정한다.

    S4 스텁: 항상 False(오답)를 돌려준다. S5에서 교체 — 공유 계약의 채점 규칙
    (접두 제거 → number는 nsimplify 수치 비교·expression은 simplify 차이 0)으로 바꾼다.
    """
    del problem, student_text  # S5에서 교체 — 스텁이라 인자를 쓰지 않는다
    return False
