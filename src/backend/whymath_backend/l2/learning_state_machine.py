"""L2 — 학습 상태 머신: 전이 판정 · 적재(단일 writer) · 재계산 대조 (EOS-105).

설계 정본: 계획서 300 §3 = `docs/ops/phase2_eos_closed_loop_execution_prompts.md` §P-04.

이 모듈의 자리
--------------
    Event → **LearnerState** → Policy → Next Action
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
            이 모듈이 상태를 읽고, 정책에 넘기고, 결과 전이를 적재한다.

세 가지 책임만 가진다:
  ① **판정** — 주어진 전이가 전이표에 있는가(`assert_transition_allowed`).
  ② **적재** — 허용된 전이를 원장에 남긴다(`record_transition` — 이 테이블의 유일한 writer).
  ③ **대조** — 영속 상태와 증거에서 재계산한 상태가 어긋나는지 본다(`reconcile_state`).

교수학 판단(무엇을 가르칠까·어떤 힌트를 줄까)은 하지 않는다. 그것은 L4의 몫이고, 이 모듈이
L4를 import하면 7계층 역방향 의존이다(CLAUDE.md "L_n은 L_{n+1}을 알지 못한다").

미정의 전이를 어떻게 다루는가 (가장 중요한 계약)
-------------------------------------------------
`assert_transition_allowed`는 표에 없는 전이에 `UndefinedTransitionError`를 낸다. 이 모듈
어디에도 "허용되지 않으면 그냥 넘어간다"·"기본 상태로 되돌린다" 같은 경로가 없다. 호출부가
그 예외를 잡을 수는 있지만, **잡았다는 사실을 표면에 드러내야 한다** — `api/me.py`의
응답 `learning_state.rejected_transition`이 그 표면이다.

이 규율에는 실제 비용이 있다: 상태 이력이 없는 기존 학생(= 전원, 이 슬라이스 이전)은
`NEW`에서 출발하는데 `NEW → ASSESSING`이 전이표에 없으므로 응답 제출 시 전이가 거부된다.
그 거부를 숨기려고 `NEW → ASSESSING`을 표에 넣는 선택도 있었으나 **넣지 않았다** —
"무엇 대비 평가인가"가 없는 평가를 합법으로 만들면 상태 머신이 보증하는 것이 사라진다.
대신 거부는 응답에 그대로 실리고, 응답 제출·숙달 전파 자체는 기존대로 성공한다(이 슬라이스는
상태 머신을 *관측 가능하게* 배선하며, 기존 학습 경로를 막지 않는다 — 한계를 명시한다).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.learning_state_transition import LearningStateTransition
from whymath_backend.l2.learning_state_policy import LearningStatePolicy, default_policy
from whymath_backend.schema.learning_state import (
    AttemptEvidence,
    LearningState,
    PolicyDecision,
    TransitionTrigger,
    UndefinedTransitionError,
    allowed_targets,
    is_transition_allowed,
)

__all__ = [
    "INITIAL_STATE",
    "StateReconciliation",
    "advance_on_attempt",
    "assert_transition_allowed",
    "get_current_state",
    "list_transitions",
    "reconcile_state",
    "record_transition",
]

INITIAL_STATE: LearningState = LearningState.NEW
"""전이 이력이 없는 학생의 상태.

"상태 미상"이라는 네 번째 값을 만들지 않는다 — `NEW`가 곧 "아직 아무것도 시작하지 않음"의
정본 표현이고, 이 덕에 `LearningState | None`을 다루는 분기가 코드베이스에 생기지 않는다.
"""


def assert_transition_allowed(from_state: LearningState, to_state: LearningState) -> None:
    """전이표 판정 — 허용이면 조용히 반환, 아니면 `UndefinedTransitionError`.

    **이 함수 안에 상태별 분기를 넣지 말 것.** 판정은 `ALLOWED_TRANSITIONS`만 본다. 예외
    하나를 여기 `if`로 뚫으면 전이 규칙의 진실 원천이 둘이 되고, 그 시점부터 전이표는
    "허용 전이의 목록"이 아니라 "허용 전이 중 일부의 목록"이 된다.
    """
    if not is_transition_allowed(from_state, to_state):
        raise UndefinedTransitionError(from_state, to_state)


async def get_current_state(session: AsyncSession, user_id: uuid.UUID) -> LearningState:
    """현재 학습 상태 — 원장 최신 행의 `to_state`, 행이 없으면 `INITIAL_STATE`.

    파생값이지 저장값이 아니다(모듈 docstring "왜 전이 원장인가" 참조). 동일 `occurred_at`이
    둘 이상일 때를 대비해 `transition_id`를 2차 정렬키로 둔다 — 없으면 같은 밀리초에 적재된
    두 전이의 순서가 비결정적이 되어 현재 상태가 호출마다 달라질 수 있다.
    """
    stmt = (
        select(LearningStateTransition.to_state)
        .where(LearningStateTransition.user_id == user_id)
        .order_by(
            desc(LearningStateTransition.occurred_at),
            desc(LearningStateTransition.transition_id),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    latest = result.scalar_one_or_none()
    return latest if latest is not None else INITIAL_STATE


async def list_transitions(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 50,
) -> list[LearningStateTransition]:
    """전이 이력 — 최신순. "왜 지금 이 상태인가"의 재구성 자료."""
    stmt = (
        select(LearningStateTransition)
        .where(LearningStateTransition.user_id == user_id)
        .order_by(
            desc(LearningStateTransition.occurred_at),
            desc(LearningStateTransition.transition_id),
        )
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def record_transition(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    to_state: LearningState,
    trigger: TransitionTrigger,
    rule_id: str | None = None,
    concept_id: str | None = None,
    attempt_id: uuid.UUID | None = None,
) -> LearningStateTransition:
    """전이 1건 적재 — `learning_state_transition`의 **유일한 writer**.

    `from_state`를 인자로 받지 않는다: 호출부가 그것을 지어내면 원장이 실제 이력과 어긋난다.
    현재 상태는 이 함수가 원장에서 직접 읽는다(TOCTOU 창은 남지만, 같은 학생의 동시 제출은
    실사용에서 드물고 append-only라 어긋난 행이 과거를 훼손하지는 않는다 — 어긋남은
    `reconcile_state`가 검출한다).

    적재 **전에** 전이표를 확인하므로, 거부된 전이는 원장에 남지 않는다.

    Raises:
        UndefinedTransitionError: 현재 상태에서 `to_state`로 가는 전이가 표에 없을 때.
    """
    from_state = await get_current_state(session, user_id)
    assert_transition_allowed(from_state, to_state)

    transition = LearningStateTransition(
        transition_id=uuid.uuid4(),
        user_id=user_id,
        from_state=from_state,
        to_state=to_state,
        trigger=trigger,
        rule_id=rule_id,
        concept_id=concept_id,
        attempt_id=attempt_id,
    )
    session.add(transition)
    await session.commit()
    return transition


@dataclass(frozen=True)
class AttemptTransitionResult:
    """응답 1건이 상태 머신을 통과한 결과.

    `decision`이 None이면 정책이 실행되지 않았다는 뜻이다(평가 국면 진입 자체가 거부된 경우).
    "결정이 없었다"와 "결정이 났는데 못 적재했다"를 같은 값으로 접지 않는다.
    """

    from_state: LearningState
    """응답 제출 시점의 상태."""

    assessed: bool
    """평가 국면(ASSESSING) 진입 전이가 적재됐는가."""

    decision: PolicyDecision | None
    """정책 결정. 평가 진입이 거부됐으면 None."""

    final_state: LearningState
    """이 처리가 끝난 뒤의 상태. 아무 전이도 못 했으면 `from_state`와 같다."""

    rejected_transition: str | None
    """거부된 전이의 설명(`"NEW → ASSESSING"` 형태). 거부가 없었으면 None.

    **이 필드가 이 결과 타입의 존재 이유다.** 거부를 예외로만 흘리면 호출부가 `except`로
    삼키는 순간 사라지고, 무시하면 "조용히 통과"가 된다. 값으로 만들어 응답까지 실어 보낸다.
    """


async def advance_on_attempt(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    evidence: AttemptEvidence,
    concept_id: str | None = None,
    attempt_id: uuid.UUID | None = None,
    policy: LearningStatePolicy | None = None,
) -> AttemptTransitionResult:
    """응답 제출 1건을 상태 머신에 통과시킨다 — 이 모듈의 주 진입점.

    순서(이 순서 자체가 P-04 항목 3의 구조다):
      ① 현재 상태를 읽는다                      (LearnerState)
      ② 평가 국면(ASSESSING) 진입 전이를 적재한다 (Event → 전이)
      ③ 정책에 증거를 넘겨 결정을 받는다          (Policy)
      ④ 결정된 다음 상태로 전이를 적재한다        (Next Action)

    ②가 거부되면 ③④를 하지 않고 거부 사실을 결과에 담아 돌려준다 — 정책을 돌려 봐야 그
    결정을 적재할 합법 경로가 없기 때문이다. 거부를 `rejected_transition`으로 표면화하므로
    조용한 통과가 아니다.

    ④가 거부되는 경우(정책이 표에 없는 상태를 제안)는 **버그**다. 그때는 예외를 삼키지 않고
    그대로 전파한다 — 정책과 전이표가 어긋났다는 사실은 학생 응답 하나보다 중요하다.
    """
    active_policy = policy if policy is not None else default_policy()
    from_state = await get_current_state(session, user_id)

    try:
        await record_transition(
            session,
            user_id=user_id,
            to_state=LearningState.ASSESSING,
            trigger=TransitionTrigger.ATTEMPT_SUBMITTED,
            concept_id=concept_id,
            attempt_id=attempt_id,
        )
    except UndefinedTransitionError as exc:
        # 삼키지 않는다 — 값으로 바꿔 호출부(및 학생 응답)까지 올려 보낸다.
        # 예외 타입명을 포함한 설명을 남기는 것이 CLAUDE.md 침묵 실패 금지의 요구다.
        return AttemptTransitionResult(
            from_state=from_state,
            assessed=False,
            decision=None,
            final_state=from_state,
            rejected_transition=(
                f"{exc.from_state.value} → {exc.to_state.value} "
                f"({type(exc).__name__}; {from_state.value}에서 가능한 상태: "
                f"{sorted(s.value for s in allowed_targets(from_state)) or '없음'})"
            ),
        )

    decision = active_policy.decide(LearningState.ASSESSING, evidence)

    # 정책이 제안한 상태가 표에 없으면 여기서 UndefinedTransitionError가 그대로 전파된다.
    # 잡지 않는 것이 의도다: 정책과 전이표의 불일치는 학생 데이터가 아니라 코드의 결함이다.
    await record_transition(
        session,
        user_id=user_id,
        to_state=decision.next_state,
        trigger=decision.trigger,
        rule_id=decision.rule_id,
        concept_id=decision.next_action.target_concept_id or concept_id,
        attempt_id=attempt_id,
    )
    return AttemptTransitionResult(
        from_state=from_state,
        assessed=True,
        decision=decision,
        final_state=decision.next_state,
        rejected_transition=None,
    )


@dataclass(frozen=True)
class StateReconciliation:
    """영속 상태 ↔ 증거 재계산 상태의 대조 결과 (acceptance ⑥).

    2026-09-03 보류 사유("`*MasteryHistory`와 같은 사실의 두 번째 진실 원천")에 대한 처치다.
    두 축이 어긋날 수 있다는 위험을 없앨 수는 없으므로, 어긋남을 **검출 가능하게** 만든다.
    """

    persisted: LearningState
    """원장이 말하는 현재 상태."""

    recomputed: LearningState
    """같은 증거를 정책에 다시 통과시켰을 때 나왔어야 할 상태."""

    diverged: bool
    """둘이 다른가."""

    detail: str | None
    """다를 때의 설명. 같으면 None."""


async def reconcile_state(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    evidence: AttemptEvidence,
    policy: LearningStatePolicy | None = None,
) -> StateReconciliation:
    """영속 상태를 증거에서 재계산한 상태와 대조한다 — **조용히 덮어쓰지 않는다**.

    이 함수는 원장을 고치지 않는다. 자동 정정은 두 축 중 어느 쪽이 옳은지 기계가 안다는
    전제가 필요한데, 그 전제는 성립하지 않는다(정책이 바뀌었을 수도, 적재가 누락됐을 수도
    있다). 검출해 보고하고 판정은 사람에게 넘긴다.

    쓰는 곳: 운영 점검·회귀 테스트. 서빙 경로에서 매 요청 호출하는 용도가 아니다.
    """
    active_policy = policy if policy is not None else default_policy()
    persisted = await get_current_state(session, user_id)
    recomputed = active_policy.decide(LearningState.ASSESSING, evidence).next_state
    diverged = persisted is not recomputed
    return StateReconciliation(
        persisted=persisted,
        recomputed=recomputed,
        diverged=diverged,
        detail=(
            f"영속 상태 {persisted.value} ≠ 증거 재계산 {recomputed.value} "
            f"(user_id={user_id}) — 자동 정정하지 않았습니다. 정책 변경 또는 적재 누락 여부를 "
            f"사람이 판정해야 합니다."
            if diverged
            else None
        ),
    )
