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
  | `confirmed_misconception_ids` | **이번 응답의 스캔 후보**(호출부가 넘긴다)   | 배선 |
  | `consecutive_failures`        | `problem_attempt` 최근 이력                 | 배선 |
  | `prerequisite_gap_concept_ids`| `l2.prerequisite_recommendation`            | **미배선** |

`prerequisite_gap_concept_ids`를 이 조립기가 스스로 채우지 않는 이유는 비용이다 —
`recommend_prerequisite_gaps`는 개념 그래프 재귀 CTE 순회라 응답 제출마다 돌리기에 무겁다.
그래서 **인자로 받는다**: 배치·비동기 경로가 계산해 넣어 주면 R4가 그 즉시 작동하고, 이
모듈과 정책은 한 줄도 바뀌지 않는다. 지금 그 생산자를 배선하지 않았다는 사실 자체를 여기
적어 두는 것이 "규칙은 있는데 영원히 안 도는" 상태를 숨기지 않는 방법이다(CLAUDE.md
"작동 신호 없는 알고리즘 부착 금지" — 어느 규칙이 실제로 돌았는지는 `PolicyDecision.rule_id`가
응답에 실려 매 요청 관측된다).

R3의 입력 = **이 응답에서** 강하게 확인된 오개념 (EOS-138 ②)
---------------------------------------------------------------
`confirmed_misconception_ids`는 규칙 R3(`R3-wrong-misconception`)의 유일한 입력이다. 종전에는
이 조립기가 **학생 전체의 활성 가설**을 신뢰 하한 없이 읽었다. 그래서 다른 개념에서 생긴 옛
가설 1건만 남아 있어도 이번 오답에 R3가 발화했고, `target_misconception_id`가 방금 틀린 개념과
무관한 옛 가설을 가리켰다(EOS-24 판정문 §4 반례 S1).

지금은 호출부(`api/me.py::submit_attempt`)가 **이번 응답의 스캔이 게이트 통과시킨 후보**만
`(misconception_id, 갱신 후 가설 신뢰)` 쌍으로 넘기고, 이 조립기는 그중 신뢰가
`MISCONCEPTION_REMEDIATION_FLOOR`(0.7)를 **초과**하는 것만 남긴다. 스캔이 돌지 않은 회차(답안
없음·지문 없음·킬 스위치 OFF)에는 빈 값이 넘어오므로 R3는 발화하지 않는다. `turns_since_evidence
= 0`으로 좁히는 방식은 쓰지 않는다 — tse는 *스캔한* 회차에만 움직여, 미스캔 회차에서는 옛
가설의 0이 그대로 남는다(태스크 ⑥ 정정 · EOS-140 실측 반례). 판정 정본은
`docs/reviews/eos138_r3_input_scope_and_route_order_judgment_2026-09-28.md`.

쌍으로 받는 이유는 계층 경계다: 가설 타입(`MisconceptionHypothesis`)은 L4이고 L2는 L4를 import할
수 없다(역방향 의존 금지). 원시 쌍이면 어느 쪽 타입도 끌어오지 않는다.

오개념을 *미리* 넣지 않는다
---------------------------
CLAUDE.md는 "오개념을 초기 context에 preload 금지 — reactive retrieval만"을 금기로 둔다.
이 조립기는 **오답일 때만** 오개념 id를 싣는다(`is_correct=True`면 넘겨받은 쌍이 있어도 빈
튜플). 그리고 이제 이 조립기는 가설 테이블을 **아예 조회하지 않는다** — 넘겨받는 것은 이번
응답이 방금 관측한 후보뿐이라, 과거 가설이 정책 입력으로 새어 들어올 경로 자체가 없다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.l2.remediation_policy import MISCONCEPTION_REMEDIATION_FLOOR
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


def _confirmed_misconception_ids(
    this_attempt_misconceptions: Sequence[tuple[str, float]],
) -> tuple[str, ...]:
    """이번 응답의 (id, 신뢰) 쌍 → R3 입력 id — 하한 **초과**만·신뢰 내림차순·동률 id 오름차순.

    경계는 "초과"다(0.7은 **제외**). `MISCONCEPTION_REMEDIATION_FLOOR`의 정의("이 값을 초과해야
    교정으로 간다")와 추천 쪽 안전장치 ②(`learning_state_recommendation` — `<= 하한`이면 집행
    안 함)가 같은 방향이다. 두 곳의 경계 방향이 어긋나면 상태 머신은 R3를 냈는데 추천은
    거절하는 회차가 생긴다.

    같은 id가 여러 번 오면 **가장 높은 신뢰 하나**로 합친다(중복 제거). 순서는 결정론이다 —
    `target_misconception_id`가 첫 원소이므로, 동률에서 입력 순서를 따르면 같은 사실이 호출마다
    다른 교정 대상을 낼 수 있다.

    신뢰가 [0, 1] 밖이거나 NaN이면 **거부한다**. NaN은 모든 비교가 거짓이라 조용히 "하한 이하"로
    떨어진다 — 망가진 입력이 "확인된 오개념 없음"으로 위장되면 안 된다(CLAUDE.md 침묵 실패 금지).
    """
    best: dict[str, float] = {}
    for misconception_id, confidence in this_attempt_misconceptions:
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(
                f"오개념 신뢰는 0~1이어야 합니다(id={misconception_id!r}, 받은 값: {confidence!r})."
            )
        if confidence <= MISCONCEPTION_REMEDIATION_FLOOR:
            continue
        if confidence > best.get(misconception_id, -1.0):
            best[misconception_id] = confidence
    ordered = sorted(best.items(), key=lambda item: (-item[1], item[0]))
    return tuple(misconception_id for misconception_id, _ in ordered)


async def build_attempt_evidence(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    is_correct: bool,
    confidence: float | None = None,
    prerequisite_gap_concept_ids: Sequence[str] = (),
    this_attempt_misconceptions: Sequence[tuple[str, float]] = (),
) -> AttemptEvidence:
    """응답 1건의 정책 증거를 조립한다.

    Args:
        is_correct: 이번 응답의 정오답.
        confidence: 학생 자기보고 확신도 0~1. 미측정은 `None`(0.0으로 채우지 않는다).
        prerequisite_gap_concept_ids: 선수 개념 결손 id — **호출부가 넣어 준다**(모듈
            docstring "생산자 배선 현황" 참조). 비우면 R4가 매치되지 않는다.
        this_attempt_misconceptions: **이번 응답의 스캔**이 게이트 통과시킨 후보의
            `(misconception_id, 갱신 후 가설 신뢰)` 쌍. 스캔이 돌지 않았으면 비운다 — 그러면
            R3가 매치되지 않는다(모듈 docstring "R3의 입력" 참조). 하한 필터·정렬·중복 제거는
            이 조립기가 한다.

    오답일 때만 오개념 id를 싣는다(reactive retrieval — CLAUDE.md 금기).
    """
    misconception_ids = (
        () if is_correct else _confirmed_misconception_ids(this_attempt_misconceptions)
    )
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
