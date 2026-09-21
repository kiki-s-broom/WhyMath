"""L2 — 응답 1건에서 정책 증거(`AttemptEvidence`)를 조립한다 (EOS-105).

이 모듈의 자리
--------------
    **Event** → LearnerState → Policy → Next Action
    ^^^^^^^^^
    응답 제출이라는 사건을 정책이 읽을 수 있는 증거 구조로 바꾼다.

조립만 한다 — **신규 계산 0**
------------------------------
`l2/learner_state.py`(PED-05)와 같은 원칙이다. 이 모듈은 기존 생산자의 출력을 모아 붙일 뿐
새로운 추정을 하지 않는다. 오개념 판정·숙달 추정을 여기서 다시 하면 그것이 곧 두 번째 진실
원천이다.

생산자 배선 현황 (정본화 ≠ 집행 — 실측을 숨기지 않는다)
--------------------------------------------------------
`AttemptEvidence`의 5필드 중 이 조립기가 **실제로 채우는 것**과 **아직 호출부가 넣어 줘야
하는 것**을 구분해 적는다. "필드가 있다"와 "그 필드에 값이 들어온다"는 다르다.

  | 필드                          | v1 생산자                                   | 상태 |
  |-------------------------------|---------------------------------------------|------|
  | `is_correct`                  | 응답 제출 본문                              | 배선 |
  | `confidence`                  | `ProblemAttempt.confidence_self_reported`   | 배선 |
  | `confirmed_misconception_ids` | `misconception_hypothesis`(is_active=true)  | 배선 |
  | `consecutive_failures`        | `problem_attempt` 최근 이력                 | 배선 |
  | `prerequisite_gap_concept_ids`| `l2.prerequisite_recommendation`            | **미배선** |

`prerequisite_gap_concept_ids`를 이 조립기가 스스로 채우지 않는 이유는 비용이다 —
`recommend_prerequisite_gaps`는 개념 그래프 재귀 CTE 순회라 응답 제출마다 돌리기에 무겁다.
그래서 **인자로 받는다**: 배치·비동기 경로가 계산해 넣어 주면 R4가 그 즉시 작동하고, 이
모듈과 정책은 한 줄도 바뀌지 않는다. 지금 그 생산자를 배선하지 않았다는 사실 자체를 여기
적어 두는 것이 "규칙은 있는데 영원히 안 도는" 상태를 숨기지 않는 방법이다(CLAUDE.md
"작동 신호 없는 알고리즘 부착 금지" — 어느 규칙이 실제로 돌았는지는 `PolicyDecision.rule_id`가
응답에 실려 매 요청 관측된다).

오개념을 *미리* 넣지 않는다
---------------------------
CLAUDE.md는 "오개념을 초기 context에 preload 금지 — reactive retrieval만"을 금기로 둔다.
이 조립기는 **오답일 때만** 오개념을 조회한다(`is_correct=True`면 쿼리 자체를 돌리지 않는다).
정답 맥락에 오개념 id를 실어 보내면 그것이 곧 preload이며, 하류 LLM 컨텍스트 오염의 입구다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.misconception_hypothesis import (
    MisconceptionHypothesisRecord,
)
from whymath_backend.schema.learning_state import AttemptEvidence

__all__ = ["CONSECUTIVE_FAILURE_SCAN_LIMIT", "build_attempt_evidence"]

CONSECUTIVE_FAILURE_SCAN_LIMIT: int = 20
"""연속 오답을 셀 때 거슬러 올라가는 최근 시도 수의 상한.

무제한 스캔은 오래 쓴 학생에서 응답 제출 경로를 느리게 만든다. 임계
(`REPEATED_FAILURE_THRESHOLD`=3)보다 충분히 크므로 판정에 영향이 없다 — 20건을 봐도 연속
오답이 끊기지 않았다면 이미 임계를 한참 넘은 것이고, 그 경우 정확한 개수는 R5의 판정을
바꾸지 않는다(임계 **이상**이면 같은 결정).
"""


async def _count_consecutive_failures(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    this_attempt_is_correct: bool,
) -> int:
    """이번 응답을 **포함한** 연속 오답 수.

    이번 응답이 정답이면 0이다 — 연속 오답이 이번에 끊겼기 때문이다. 오답이면 이번 1건에
    직전 이력의 연속 오답을 더한다.

    호출 시점 주의: 이 함수는 **이번 attempt를 적재한 뒤** 호출돼도 정확하다. 적재된 행이
    최신 1건으로 잡히지만 그 값이 곧 `this_attempt_is_correct`와 같으므로, 중복 계상을 피하려
    적재분을 건너뛰는 대신 **이번 응답을 인자로 받고 이력에서는 그 다음 행부터** 센다
    (`offset(1)`). 적재 순서에 의존하지 않으려면 이 오프셋 대신 시각 비교를 써야 하지만,
    같은 밀리초 적재에서 다시 비결정적이 되므로 오프셋이 더 견고하다.
    """
    if this_attempt_is_correct:
        return 0

    stmt = (
        select(ProblemAttempt.is_correct)
        .where(ProblemAttempt.user_id == user_id)
        .order_by(desc(ProblemAttempt.ingested_at), desc(ProblemAttempt.attempt_id))
        .offset(1)
        .limit(CONSECUTIVE_FAILURE_SCAN_LIMIT)
    )
    result = await session.execute(stmt)

    failures = 1  # 이번 오답
    for (is_correct,) in result.all():
        # NULL(미채점)은 연속을 **끊는다** — "모른다"를 "틀렸다"로 접으면 미채점 이력이
        # 학생을 교정 국면으로 밀어 넣는다(CLAUDE.md "모른다 ≠ 아니다").
        if is_correct is not False:
            break
        failures += 1
    return failures


async def _active_misconception_ids(session: AsyncSession, user_id: uuid.UUID) -> tuple[str, ...]:
    """활성 오개념 가설 id — confidence 내림차순.

    `l2/learner_state.py::_get_active_misconception_ids`와 **같은 모양의 SELECT**다. 두
    모듈이 각자 쓰는 이유는 계층 경계 때문이며(L2는 L4의 `hypothesis_store`를 import할 수
    없다), 이 중복은 의도적이다 — 값이 아니라 쿼리 모양의 중복이고, 가설 테이블 자체가 단일
    진실 원천으로 남는다.
    """
    stmt = (
        select(MisconceptionHypothesisRecord.misconception_id)
        .where(
            MisconceptionHypothesisRecord.user_id == user_id,
            MisconceptionHypothesisRecord.is_active.is_(True),
        )
        .order_by(desc(MisconceptionHypothesisRecord.confidence))
    )
    result = await session.execute(stmt)
    return tuple(result.scalars().all())


async def build_attempt_evidence(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    is_correct: bool,
    confidence: float | None = None,
    prerequisite_gap_concept_ids: Sequence[str] = (),
) -> AttemptEvidence:
    """응답 1건의 정책 증거를 조립한다.

    Args:
        is_correct: 이번 응답의 정오답.
        confidence: 학생 자기보고 확신도 0~1. 미측정은 `None`(0.0으로 채우지 않는다).
        prerequisite_gap_concept_ids: 선수 개념 결손 id — **호출부가 넣어 준다**(모듈
            docstring "생산자 배선 현황" 참조). 비우면 R4가 매치되지 않는다.

    오답일 때만 오개념을 조회한다(reactive retrieval — CLAUDE.md 금기).
    """
    misconception_ids = () if is_correct else await _active_misconception_ids(session, user_id)
    consecutive_failures = await _count_consecutive_failures(
        session, user_id, this_attempt_is_correct=is_correct
    )
    return AttemptEvidence(
        is_correct=is_correct,
        confidence=confidence,
        confirmed_misconception_ids=misconception_ids,
        prerequisite_gap_concept_ids=tuple(prerequisite_gap_concept_ids),
        consecutive_failures=consecutive_failures,
    )
