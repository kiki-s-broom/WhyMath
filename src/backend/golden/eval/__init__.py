"""슬롯 T1 평가(S22) — 옛 정답 유출 탐지기·소형 루브릭의 골든 사본과 그것을 감싼 평가기.

- `rubric_copy` : 옛 `whymath_backend.harness.pedagogical_rubric`의 함수 2개 사본(복사: 의존 과다).
- `rubric`      : `evaluate_tutor_reply(reply, answer) -> RubricVerdict`
                  · 플래그 `GOLDEN_T1_RUBRIC`.

GP-4 튜터 응답 직후에 `GOLDEN_T1_RUBRIC=1`일 때만 불리며, 결과는 `golden.eval_log`에 기록만 한다.
"""

from golden.eval.rubric import RubricVerdict, evaluate_tutor_reply, rubric_enabled

__all__ = ["RubricVerdict", "evaluate_tutor_reply", "rubric_enabled"]
