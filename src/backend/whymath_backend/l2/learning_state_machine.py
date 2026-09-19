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

이 규율에는 실제 비용이 있었다: 상태 이력이 없는 학생(= 전원, EOS-105 시점)은 `NEW`에서
출발하는데 `NEW → ASSESSING`이 전이표에 없으므로 응답 제출 시 전이가 거부됐다. 그 거부를
숨기려고 `NEW → ASSESSING`을 표에 넣는 선택도 있었으나 **넣지 않았다** — "무엇 대비
평가인가"가 없는 평가를 합법으로 만들면 상태 머신이 보증하는 것이 사라진다.

**그 한계는 EOS-115가 해소했다 — 금지를 풀어서가 아니라 빠진 경로를 놓아서다.**
`NEW → ASSESSING`은 지금도 닫혀 있다. 대신 `ensure_learning_context`가 평가 직전에 빠져
있던 **학습 진입 전이 1건**을 적재해, 학습자가 `NEW → LEARNING → ASSESSING`으로 정상
경유하게 한다. 진단을 위조하지 않으므로(`from_state=NEW`가 원장에 남는다) "진단 없이
학습에 들어왔다"는 사실은 사후에 그대로 읽힌다.

같은 결함의 두 번째 얼굴도 함께 해소됐다: 정답+높은 확신으로 R1을 받아 `ADVANCING`에
올라간 학습자는 `ADVANCING → ASSESSING`이 닫혀 있어 **다음 응답이 전건 거부**됐다(실측
2026-09-19). 전이표 주석이 이미 "다음 개념 LEARNING을 거쳐야 한다"고 지정했으나 그 경유를
적재하는 코드가 없었다 — 이제 같은 함수가 그것을 적재한다.

거부가 사라진 것은 아니다. 자동 진입 대상이 아닌 상태(`DIAGNOSING`)에서는 거부가 그대로
응답에 실리며, 응답 적재·숙달 전파는 예전처럼 그와 무관하게 성공한다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.learning_state_transition import LearningStateTransition
from whymath_backend.l2.learning_state_policy import LearningStatePolicy, default_policy
from whymath_backend.schema.learning_state import (
    ALLOWED_TRANSITIONS,
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
    "ensure_learning_context",
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


_LEARNING_ENTRY_TRIGGERS: dict[LearningState, TransitionTrigger] = {
    # 진단 없이 바로 학습에 들어온 학습자 — `from_state=NEW`가 그 사실을 원장에 남긴다.
    LearningState.NEW: TransitionTrigger.LEARNING_STARTED,
    # 진단을 마치고 출발점이 확정된 학습자의 학습 시작.
    LearningState.READY: TransitionTrigger.LEARNING_STARTED,
    # 진급 완료 — 전이표 주석이 "다음 개념 LEARNING을 거쳐야 한다"고 지정한 그 경유다.
    LearningState.ADVANCING: TransitionTrigger.ADVANCE_COMPLETED,
}
"""평가 직전에 **학습 진입 전이 1건**으로 평가 가능 상태에 닿을 수 있는 출발 상태 → 트리거.

여기 **없는** 상태는 자동 진입 대상이 아니며 거부가 그대로 표면화된다. 대표적으로
`DIAGNOSING`이 없다 — 진단 중에 제출된 응답은 *진단 그 자체*일 수 있어 "학습을 시작했다"로
단정할 수 없고, LEARNING까지 두 걸음이라 한 건으로 메울 수도 없다. 모르는 것을 아는 것처럼
적지 않는다(CLAUDE.md "모른다 ≠ 아니다").

새 트리거를 만들지 않은 이유: 세 트리거 모두 이미 이 사건을 가리키는 이름으로 존재한다.
없는 값을 추가하면 PG enum(`learning_state_trigger_enum`) 마이그레이션이 따라붙는데, 그
비용으로 사는 것이 `from_state`가 이미 구분해 주는 정보의 사본뿐이다.
"""


def _assessable_from_states() -> frozenset[LearningState]:
    """평가(ASSESSING)로 들어갈 수 있는 출발 상태 — **전이표에서 파생한다**.

    목록을 여기 하드코딩하지 않는다. 하드코딩하면 전이표를 고쳐도 이쪽이 따라오지 않아
    "허용 전이의 목록"이 둘이 된다(전이표 주석이 금지하는 바로 그 상태).
    """
    return frozenset(src for src, dst in ALLOWED_TRANSITIONS if dst is LearningState.ASSESSING)


async def ensure_learning_context(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    concept_id: str | None = None,
) -> LearningState | None:
    """평가 전 **학습 맥락 확보** — 빠진 학습 진입 전이 1건을 적재한다 (EOS-115).

    왜 필요한가: 전이표는 평가(ASSESSING)가 학습 맥락에서 출발하기를 요구하는데, 그 맥락에
    들어가는 전이를 적재하는 서버 경로가 **0건**이었다. 그래서 두 부류가 영구히 막혔다 —
    ① 전이 이력이 없는 기본 학습자(`NEW`, 즉 전원) ② 정답+높은 확신으로 R1을 받아
    `ADVANCING`에 올라간 학습자(다음 응답이 전건 거부된다. 실측 2026-09-19).

    이 함수는 전이표를 **우회하지 않는다**. 표가 이미 허용하는 학습 진입 간선을 실제로
    적재할 뿐이며, 적재 역시 `record_transition`(유일한 writer)을 거치므로 표에 없는 전이는
    여기서도 거부된다.

    Returns:
        적재했으면 진입 **전**의 상태(원장·관측용), 적재할 필요·근거가 없으면 `None`.
    """
    current = await get_current_state(session, user_id)
    if current in _assessable_from_states():
        return None  # 이미 평가 가능 — 아무것도 적재하지 않는다.
    trigger = _LEARNING_ENTRY_TRIGGERS.get(current)
    if trigger is None:
        # 자동 진입 대상이 아니다. 조용히 넘어가는 것이 아니라, 뒤따르는 평가 전이가
        # 거부되어 `rejected_transition`으로 표면화된다(침묵 실패 금지).
        return None
    await record_transition(
        session,
        user_id=user_id,
        to_state=LearningState.LEARNING,
        trigger=trigger,
        concept_id=concept_id,
    )
    return current


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

    entered_learning_from: LearningState | None = None
    """⓪ 학습 맥락 확보가 **실제로 적재한** 경우 그 직전 상태, 아니면 None (EOS-115).

    붙인 단계가 돌았는지를 결과가 말하게 한다(CLAUDE.md "작동한 비율" — 정상 응답 200은
    그 단계가 일했다는 증거가 아니다). `from_state`로 추론할 수도 있지만 추론은 규칙을
    아는 사람만 할 수 있고, 규칙이 바뀌면 조용히 틀린다.
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
      ⓪ 학습 맥락을 확보한다                     (EOS-115 — 빠진 학습 진입 전이 1건)
      ① 현재 상태를 읽는다                      (LearnerState)
      ② 평가 국면(ASSESSING) 진입 전이를 적재한다 (Event → 전이)
      ③ 정책에 증거를 넘겨 결정을 받는다          (Policy)
      ④ 결정된 다음 상태로 전이를 적재한다        (Next Action)

    ⓪가 ①보다 앞선 이유는 보고값 때문이 아니라 **적재 순서** 때문이다 — 학습 진입 전이가
    평가 전이보다 먼저 원장에 있어야 이력이 인과 순서대로 읽힌다. 반면 결과의 `from_state`는
    ⓪ **이전**의 상태를 보고한다(아래 참조).

    ②가 거부되면 ③④를 하지 않고 거부 사실을 결과에 담아 돌려준다 — 정책을 돌려 봐야 그
    결정을 적재할 합법 경로가 없기 때문이다. 거부를 `rejected_transition`으로 표면화하므로
    조용한 통과가 아니다.

    ④가 거부되는 경우(정책이 표에 없는 상태를 제안)는 **버그**다. 그때는 예외를 삼키지 않고
    그대로 전파한다 — 정책과 전이표가 어긋났다는 사실은 학생 응답 하나보다 중요하다.

    `from_state`는 ⓪ **이전**의 상태다 — 즉 "이 학생이 이번 제출을 시작한 자리". 이미
    기존 계약이 한 간선이 아니라 **구간**을 보고한다(LEARNING에서 제출하면
    `from_state=LEARNING · to_state=ADVANCING`이고 그 사이에 ASSESSING이 있다). 같은 규칙을
    ⓪에도 적용해 `from_state=NEW · to_state=REMEDIATING`처럼 온보딩을 포함한 구간으로 읽게
    한다 — ⓪ 이후 값을 보고하면 학습자가 어디서 출발했는지가 응답에서 사라진다.
    """
    active_policy = policy if policy is not None else default_policy()
    # ⓪ 학습 맥락 확보 — 이 줄이 EOS-115의 집행 지점이다(정본화 ≠ 집행). 표를 고친 것만으로는
    # 아무 학생도 움직이지 않는다; 주 진입점이 그것을 실제로 부르는 여기가 계약을 집행으로 바꾼다.
    entered_learning_from = await ensure_learning_context(
        session, user_id=user_id, concept_id=concept_id
    )
    # `from_state`는 ⓪ 이전 값을 유지한다(위 docstring). ⓪가 적재했으면 그 반환값이 곧 그 값이고,
    # 아니면 원장에서 읽는다 — 어느 쪽이든 "이번 제출을 시작한 자리"라는 의미는 동일하다.
    from_state = (
        entered_learning_from
        if entered_learning_from is not None
        else await get_current_state(session, user_id)
    )

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
            entered_learning_from=entered_learning_from,
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
        entered_learning_from=entered_learning_from,
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
