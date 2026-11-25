"""슬롯 T1 평가(S22) — 옛 정답 유출 탐지기·소형 루브릭의 골든 사본과 그것을 감싼 평가기.

- `rubric_copy` : 옛 `whymath_backend.harness.pedagogical_rubric`의 함수 2개 사본(복사: 의존 과다).
- `rubric`      : `evaluate_tutor_reply(reply, answer) -> RubricVerdict`
                  · 플래그 `GOLDEN_T1_RUBRIC`.
- `misconception`: `match_misconception(problem, student_text) -> str | None`
                  · 플래그 `GOLDEN_T2_MISCONCEPTION`(S27 · 주입기 규칙을 거꾸로 쓴 매칭).
                  `misconception_description(mis_id) -> str`(S28 · 오개념 한 줄 설명 데이터
                  — 튜터 프롬프트 주입은 S30이 되돌림).

GP-4 튜터 응답 직후에 `GOLDEN_T1_RUBRIC=1`일 때만 불리며, 결과는 `golden.eval_log`에 기록만 한다.
"""

from golden.eval.misconception import (
    T2_MATCHER_VERSION,
    match_misconception,
    misconception_description,
    misconception_enabled,
)
from golden.eval.rubric import RubricVerdict, evaluate_tutor_reply, rubric_enabled

__all__ = [
    "RubricVerdict",
    "T2_MATCHER_VERSION",
    "evaluate_tutor_reply",
    "match_misconception",
    "misconception_description",
    "misconception_enabled",
    "rubric_enabled",
]
