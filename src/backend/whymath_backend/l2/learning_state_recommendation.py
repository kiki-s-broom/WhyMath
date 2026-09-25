"""L2 — 학습 상태 머신의 결정 → 추천의 입력 (EOS-24).

설계 정본: `docs/reviews/eos24_recommendation_reads_learning_state_judgment_2026-09-25.md`.

이 모듈의 자리
--------------
    Event → LearnerState → Policy → **Next Action → Recommendation**
                                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    상태 머신이 낸 다음 행동을 추천이 *집행*하는 이음매.

이 모듈이 생기기 전에는 오개념 오답 직후 상태 머신이 `REMEDIATING`(R3 · 오개념부터 교정)을
결정하는데도, `GET /v1/me/next-problem`은 그 결정을 읽지 않고 θ가 내려간 만큼 선수 개념 문항을
골라 `diagnose · unmeasured`를 냈다(Gate 2 재판정 2026-09-24 §3). 같은 회차에 학생에게 두
지시가 나갔다.

판정 요지 — 추천은 상태 머신을 **다시 판정하지 않고 집행한다**
---------------------------------------------------------------
"다음에 무엇을 할까"의 결정자는 상태 머신(`l2/learning_state_policy.py::V1_RULES`) 하나다.
오개념과 선수 결손 중 무엇이 먼저인가는 논쟁 중이지만(상태 머신 R3 > R4 ↔ MISC-30 경로 표
RT1 > RT2), 추천이 집행만 하면 순서를 바꾸기로 했을 때 고칠 곳이 `V1_RULES` 한 곳이다.

집행 대상은 **R3 하나**다(트리거 `POLICY_REMEDIATE_MISCONCEPTION`). R5·R6·R2·R1을 읽지 않는
이유는 판정문 §3에 있다 — 요지: R5를 따르면 반복 실패 뒤 선수 하강이 막히고, R2를 따르면
확신도를 보고하지 않는 학생의 진급이 막힌다.

안전장치 4개 (판정문 §4 — 독립 교수학 비판 반영)
------------------------------------------------
R3의 입력은 약하다(학생 전체의 활성 가설 · 신뢰 하한 없음). 추천이 R3를 충실히 집행할수록
그 약점이 학생에게 그대로 전달되므로, **지금 근거를 확인할 수 있는 결정만** 집행한다.

  ① 이번 회차에 새로 확인된 가설이 있어야 한다 — `turns_since_evidence = 0` **이고** 직전 다른
     응답이 원장에 남긴 마지막 전이보다 늦게 증거로 갱신된 가설(EOS-140 — tse만으로는 미스캔
     회차에서 뚫린다. `_evidence_since_previous_attempt` docstring).
  ② 그 가설의 신뢰가 `MISCONCEPTION_REMEDIATION_FLOOR`를 **넘어야** 한다(하한은 MISC-30 표가
     정본 — 새 숫자를 만들지 않는다).
  ③ 교정 고정은 1문항이다: 교정 국면에서 제출한 응답이 다시 R3면 고정을 풀고 숙달 구간
     파생(선수 하강 가능)으로 넘긴다.
  ④ 집행·해제·폴백 사유를 `StateDirectiveOutcome`으로 남긴다(CLAUDE.md "작동한 비율").

조건이 맞지 않으면 **예외를 내지 않고** 기존 추천으로 돌아간다 — 근거를 풍부하게 하려는 경로
때문에 학생이 문항을 못 받는 것은 우선순위가 거꾸로다. 대신 그 사실을 값으로 남긴다.

선택 축 — 개념 C로 **제한**한다
-------------------------------
가중치만 올리면 근거는 "오개념 교정"인데 문항은 다른 개념인 경우가 남는다(`EOS-124`와 같은
부류의 결함). 제한하면 이 경로 안에서는 설명과 문항이 구조적으로 어긋날 수 없다. 제한은
`build_candidate_pool_stmt`(저작권·검수 노출 게이트 + 미시도 + θ 근방)에 WHERE를 **덧붙이는**
방식이라 노출 게이트를 다시 쓰지 않는다(REC-06 "한 곳에서만 정의").

계층: `l2`. L3~L6을 import하지 않는다. 오개념 가설은 `db.models`(공유 인프라)를 직접 읽는다 —
`l2/learner_state.py`·`l2/learning_state_evidence.py`와 같은 선례다(L4 `hypothesis_store` import
금지).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from sqlalchemy import ColumnElement, Select, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.concept import ProblemConcept
from whymath_backend.db.models.learning_state_transition import LearningStateTransition
from whymath_backend.db.models.misconception_hypothesis import MisconceptionHypothesisRecord
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.learner_state import LearnerState

# 재구현 0 — 대표 개념·최신 숙달 조회는 숙달 좌석이 소유한다(`l2.recommendation_reason` 선례).
from whymath_backend.l2.mastery_tracking import _latest_mastery, get_primary_concept_id
from whymath_backend.l2.next_problem_selection import CandidateRow, build_candidate_pool_stmt
from whymath_backend.l2.recommendation_contract import RecommendationReason, remediation_reason
from whymath_backend.l2.remediation_policy import MISCONCEPTION_REMEDIATION_FLOOR
from whymath_backend.schema.enums import ConceptRole
from whymath_backend.schema.learning_state import LearningState, TransitionTrigger

__all__ = [
    "RemediationDirective",
    "StateDirectiveOutcome",
    "StateRoute",
    "build_concept_candidate_pool_stmt",
    "collect_remediation_reason",
    "read_remediation_directive",
    "route_by_learning_state",
]


class StateDirectiveOutcome(str, Enum):
    """상태 머신이 추천을 지시했을 때 **실제로 무슨 일이 일어났는가** — 작동 비율의 원자료.

    지시가 없었으면(상태 머신이 R3를 결정하지 않았으면) 이 값 자체가 없다(`None`). 그러므로
    `APPLIED / (전체 non-None)`이 곧 "상태 머신 결정을 추천이 집행한 비율"이다. 폴백 사유를
    하나로 뭉치지 않는 이유: 사유마다 고칠 곳이 다르다(가설 품질 · 데이터 매핑 · 문항 재고).
    """

    APPLIED = "applied"
    """집행했다 — 후보를 개념 C로 제한하고 오개념 교정 근거를 달았다."""

    RELEASED_AFTER_REPEAT = "released_after_repeat"
    """교정 국면에서 제출한 응답이 다시 R3였다 — 고정을 풀고 숙달 구간 파생으로 넘겼다(③)."""

    WEAK_MISCONCEPTION_EVIDENCE = "weak_misconception_evidence"
    """이번 회차에 확인된 가설이 없거나 신뢰가 하한 이하다 — 집행하지 않았다(①②)."""

    ANCHOR_UNRESOLVED = "anchor_unresolved"
    """결정의 응답·문항·대표 개념 중 하나를 찾지 못했다 — 무엇을 교정할지 모른다."""

    NO_CANDIDATE_IN_CONCEPT = "no_candidate_in_concept"
    """개념 C에 노출 가능한 미시도 문항이 없다 — 기존 추천으로 돌아갔다."""


@dataclass(frozen=True, slots=True)
class RemediationDirective:
    """상태 머신의 R3 결정 1건 — 추천이 집행을 **검토할** 대상(아직 집행 여부는 모른다)."""

    attempt_id: uuid.UUID | None
    """결정을 낸 응답. None이면 무엇을 교정할지 찾을 수 없다(`ANCHOR_UNRESOLVED`)."""

    repeated_in_remediation: bool
    """그 응답이 **교정 국면(REMEDIATING)에서** 제출됐는가 — True면 교정 1문항이 이미 실패했다."""


def read_remediation_directive(learner_state: LearnerState) -> RemediationDirective | None:
    """`LearnerState`의 학습 국면 → 집행 검토 대상(순수 · DB 0).

    None을 돌려주는 경우(= 상태 머신이 추천을 지시하지 않았다):
      · 국면 스냅샷이 없다(조립기를 거치지 않은 상태) · 현재 국면이 `REMEDIATING`이 아니다
      · `REMEDIATING`이지만 R3가 아니다(R5 반복 실패 — 판정문 §3)

    **국면과 트리거를 둘 다 본다.** 트리거만 보면 R3 뒤에 생애주기 전이가 끼어도(국면이 바뀌어도)
    지시가 살아 있는 것처럼 읽히고, 국면만 보면 R5의 `REMEDIATING`을 오개념 교정으로 오독한다.
    """
    snapshot = learner_state.learning_state
    if snapshot is None or snapshot.state is not LearningState.REMEDIATING:
        return None
    if snapshot.trigger is not TransitionTrigger.POLICY_REMEDIATE_MISCONCEPTION:
        return None
    return RemediationDirective(
        attempt_id=snapshot.attempt_id,
        repeated_in_remediation=snapshot.assessed_from is LearningState.REMEDIATING,
    )


@dataclass(frozen=True, slots=True)
class StateRoute:
    """상태 머신 지시의 처리 결과 — 집행했으면 제한된 후보까지 함께 담는다."""

    outcome: StateDirectiveOutcome
    concept_id: uuid.UUID | None = None
    """교정 대상 개념 C. 찾지 못했으면 None."""
    candidate_rows: tuple[CandidateRow, ...] = ()
    """C로 제한된 후보(집행했을 때만 비지 않는다)."""
    misconception_confidence: float | None = None
    """집행 근거가 된 가설의 신뢰(②를 넘은 값). 집행하지 않았으면 None."""

    @property
    def applied(self) -> bool:
        return self.outcome is StateDirectiveOutcome.APPLIED


def _evidence_since_previous_attempt(
    user_id: uuid.UUID, attempt_id: uuid.UUID
) -> ColumnElement[bool]:
    """가설의 마지막 증거 갱신이 **직전 다른 응답의 마지막 원장 전이보다 늦다** — ①의 회차 경계.

    왜 `turns_since_evidence = 0`만으로는 부족한가(EOS-140 · 실 PG 재현): 그 값은 "가장 최근
    *스캔* 턴에서 매치됐다"이지 "이 응답에서 매치됐다"가 아니다. 응답 제출 경로의 스캔은 오답 +
    답안(또는 선지 인덱스) + 지문이 있을 때만 돈다(`api/me.py::_scan_attempt_misconceptions` —
    정답·답안 미제출·지문 부재는 NOT_RUN이고 NOT_RUN이면 가설을 건드리지 않는다). 그래서
    오개념 오답(스캔·tse 0) → 정답(미스캔) → 다른 개념의 답안 없는 오답(미스캔)이면 첫 가설의
    tse가 0으로 남고, 학생 전체 가설을 읽는 R3는 다시 발화한다 — tse만 보면 그 옛 가설이 "이번
    회차 증거"가 되어 무관한 개념에 교정이 고정된다(판정문 §4 반례 S1이 그대로 통과했다).

    경계를 원장에서 잡는 이유: 응답 제출 경로는 스캔으로 가설을 갱신·commit한 **뒤에** 상태 머신
    전이를 적재한다. 그러므로 직전 응답이 남긴 마지막 전이보다 늦게 갱신된 가설은 그 뒤의 관측
    (이번 응답의 스캔, 또는 그 사이의 코치 대화 턴)에서 증거를 받은 것이다. 두 시각은 모두 DB
    `now()`라 앱·DB 시계 차이가 끼지 않는다 — `problem_attempt`의 수신 시각은 앱이 채우므로 쓰지
    않는다. 가설 행의 `updated_at`은 매치 때마다 바뀌는 `evidence_count`가 UPDATE를 일으켜
    반드시 갱신된다(`hypothesis_store._persist_active_set` · `onupdate=now()`).

    결정 응답 자신의 행과 `attempt_id` 없는 생애주기 전이는 경계에서 뺀다 — 둘 다 이번 응답의
    스캔 *뒤에* 적재될 수 있어(⓪ 학습 진입 · 평가 진입 · 결정) 경계를 이번 증거 너머로 밀어낸다.
    뒤쪽은 `attempt_id != 결정 응답` 비교가 스스로 뺀다(SQL 3값 논리 — NULL과의 `!=`는 참이
    아니다). 그래서 `IS NOT NULL`을 따로 두지 않는다: 효과 없는 조건은 반례로 검증할 수 없다.
    경계가 **가장 늦은** 전이(`max`)인 이유: 옛 스캔이 그 사이 어느 응답 뒤에 있었든 모두 걸러야
    한다 — `min`이면 첫 응답 이후의 옛 스캔이 전부 "이번 회차"로 통과한다.
    직전 응답이 없으면(첫 응답) 경계가 없고 tse만으로 판정한다 — 그때는 옛 스캔 자체가 없다.

    남는 한계(정직 표기): 두 응답 **사이의** 코치 대화 턴에서 매치된 가설도 "이번 회차"로 센다.
    근본 해소는 R3의 입력을 이번 응답의 스캔 결과로 좁히는 것이며 `EOS-138`이 소유한다.
    """
    boundary = (
        select(func.max(LearningStateTransition.occurred_at))
        .where(
            LearningStateTransition.user_id == user_id,
            LearningStateTransition.attempt_id != attempt_id,
        )
        .scalar_subquery()
    )
    return or_(boundary.is_(None), MisconceptionHypothesisRecord.updated_at > boundary)


async def _fresh_misconception_confidence(
    session: AsyncSession, user_id: uuid.UUID, attempt_id: uuid.UUID | None
) -> float | None:
    """이번 회차에 증거를 받은 활성 가설 중 최고 신뢰 — 없으면 None(①).

    `turns_since_evidence = 0`은 가장 최근 스캔 턴에서 매치됐다는 뜻이다
    (`l4/misconception/hypothesis.py` — 매치되면 0으로 되돌리고, 아니면 경과 턴을 더한다).
    학생 전체에서 가장 높은 가설이 아니라 **방금 관측된** 가설을 보는 것이 이 조회의 요점이다 —
    다른 개념에서 생긴 옛 가설로 지금 개념을 교정 고정하지 않는다(판정문 §4 반례 S1).

    "방금"은 tse만으로 정해지지 않는다 — 결정 응답(`attempt_id`)의 회차 경계를 함께 건다
    (`_evidence_since_previous_attempt` · EOS-140). 경계는 스칼라 서브쿼리라 조회 수는 1건 그대로다.
    `attempt_id`가 없으면 경계를 잡을 수 없지만, 그 경우는 바로 뒤의 `ANCHOR_UNRESOLVED`가 집행을
    막으므로 여기서는 경계 없이 판정한다(조회 순서·결과가 전환 전과 같다).
    """
    conditions: list[ColumnElement[bool]] = [
        MisconceptionHypothesisRecord.user_id == user_id,
        MisconceptionHypothesisRecord.is_active.is_(True),
        MisconceptionHypothesisRecord.turns_since_evidence == 0,
    ]
    if attempt_id is not None:
        conditions.append(_evidence_since_previous_attempt(user_id, attempt_id))
    stmt = (
        select(MisconceptionHypothesisRecord.confidence)
        .where(*conditions)
        .order_by(desc(MisconceptionHypothesisRecord.confidence))
        .limit(1)
    )
    value = (await session.execute(stmt)).scalar_one_or_none()
    return float(value) if value is not None else None


async def _anchor_concept(
    session: AsyncSession, *, user_id: uuid.UUID, attempt_id: uuid.UUID
) -> uuid.UUID | None:
    """결정을 낸 응답 → 그 문항의 대표 개념 C. 어느 고리든 끊기면 None.

    `user_id`로 한 번 더 좁히는 이유: 원장의 `attempt_id`는 FK가 아니다(느슨한 참조). 다른
    학생의 응답을 가리키는 행이 생겨도 그 문항으로 교정 대상을 정하지 않는다.
    """
    stmt = select(ProblemAttempt.problem_id).where(
        ProblemAttempt.attempt_id == attempt_id,
        ProblemAttempt.user_id == user_id,
    )
    problem_id = (await session.execute(stmt)).scalar_one_or_none()
    if problem_id is None:
        return None
    return await get_primary_concept_id(session, problem_id)


def build_concept_candidate_pool_stmt(
    theta: float,
    *,
    concept_id: uuid.UUID,
    attempted_ids: set[uuid.UUID],
    excluded_ids: set[uuid.UUID],
) -> Select[Any]:
    """기본 CAT 후보 SELECT + **대표 개념이 C인 문항만** — 노출 게이트는 원본 그대로다.

    원본 문장(`build_candidate_pool_stmt`)에 WHERE를 덧붙인다. SQLAlchemy `Select`는 생성형이라
    `limit` 뒤에 붙인 WHERE도 WHERE 절로 들어가고 LIMIT은 제한된 결과에 걸린다(θ 근방 상위
    N건이 *C 안에서* 뽑힌다). 노출 게이트를 여기서 다시 쓰지 않는 것이 요점이다 — 다시 쓰면
    "서빙 풀"의 정의가 둘이 된다(REC-06).

    PRIMARY만 보는 이유: 근거의 `concept_id`(C)와 문항의 대표 개념이 같아야 이 경로의 설명과
    문항이 어긋나지 않는다. TESTED로 C를 평가할 뿐인 문항은 대표 개념이 다른 개념이다.
    """
    members = select(ProblemConcept.problem_id).where(
        ProblemConcept.concept_id == concept_id,
        ProblemConcept.role == ConceptRole.PRIMARY,
    )
    return build_candidate_pool_stmt(
        theta, attempted_ids=attempted_ids, excluded_ids=excluded_ids
    ).where(Problem.problem_id.in_(members))


async def route_by_learning_state(
    session: AsyncSession,
    learner_state: LearnerState,
    *,
    theta: float,
    attempted_ids: set[uuid.UUID],
    excluded_ids: set[uuid.UUID],
) -> StateRoute | None:
    """상태 머신의 R3 결정을 추천이 집행할 수 있는지 판정하고, 되면 제한 후보까지 낸다.

    None이면 상태 머신이 추천을 지시하지 않았다 — **조회 0건**이다(순수 판정에서 끝난다). 이 덕에
    지시가 없는 모든 요청(대다수)은 전환 전과 같은 쿼리 수·같은 결과를 낸다.

    검사 순서는 **싼 것부터**다: 해제(순수) → 가설 신뢰(1건) → 교정 대상 개념(2~3건) → 후보(1건).
    앞에서 멈추면 뒤의 조회는 돌지 않는다.
    """
    directive = read_remediation_directive(learner_state)
    if directive is None:
        return None
    if directive.repeated_in_remediation:
        return StateRoute(outcome=StateDirectiveOutcome.RELEASED_AFTER_REPEAT)

    user_id = uuid.UUID(learner_state.student_id)
    confidence = await _fresh_misconception_confidence(session, user_id, directive.attempt_id)
    # "초과"다(이하는 집행하지 않는다) — MISC-30 표의 RT2와 같은 경계 방향.
    if confidence is None or confidence <= MISCONCEPTION_REMEDIATION_FLOOR:
        return StateRoute(outcome=StateDirectiveOutcome.WEAK_MISCONCEPTION_EVIDENCE)

    if directive.attempt_id is None:
        return StateRoute(outcome=StateDirectiveOutcome.ANCHOR_UNRESOLVED)
    concept_id = await _anchor_concept(session, user_id=user_id, attempt_id=directive.attempt_id)
    if concept_id is None:
        return StateRoute(outcome=StateDirectiveOutcome.ANCHOR_UNRESOLVED)

    stmt = build_concept_candidate_pool_stmt(
        theta, concept_id=concept_id, attempted_ids=attempted_ids, excluded_ids=excluded_ids
    )
    rows: tuple[CandidateRow, ...] = tuple(
        (pid, float(difficulty), irt_b)
        for pid, difficulty, irt_b in (await session.execute(stmt)).all()
    )
    if not rows:
        return StateRoute(
            outcome=StateDirectiveOutcome.NO_CANDIDATE_IN_CONCEPT, concept_id=concept_id
        )
    return StateRoute(
        outcome=StateDirectiveOutcome.APPLIED,
        concept_id=concept_id,
        candidate_rows=rows,
        misconception_confidence=confidence,
    )


async def collect_remediation_reason(
    session: AsyncSession,
    *,
    learner_id: uuid.UUID,
    route: StateRoute,
) -> RecommendationReason:
    """집행된 경로의 근거 — 개념 C의 실측 숙달을 참고로 싣는다(읽기 전용 · 조회 1건).

    집행되지 않은 경로로 부르면 **거부한다**(ValueError). 폴백 추천에 오개념 교정 근거를 달면
    "상태 머신이 결정했다"가 거짓이 된다 — 그 거짓은 처치 기록에 영속된다.
    """
    if not route.applied or route.concept_id is None or route.misconception_confidence is None:
        raise ValueError(
            f"집행되지 않은 상태 경로({route.outcome.value})에는 오개념 교정 근거를 달 수 없습니다."
        )
    row = await _latest_mastery(session, learner_id, route.concept_id)
    mastery = float(row.mastery) if row is not None and row.mastery is not None else None
    return remediation_reason(
        concept_id=route.concept_id,
        mastery=mastery,
        misconception_confidence=route.misconception_confidence,
    )
