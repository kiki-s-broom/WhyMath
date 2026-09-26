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

EOS-26 — R6(원인 미상 오답)도 집행한다
-----------------------------------------
설계 정본: `docs/reviews/eos26_r6_diagnosis_prerequisite_directed_judgment_2026-09-26.md`.

R6의 결정은 "같은 개념 연습"(`PRACTICE_SAME_CONCEPT`)이다. Kiki 결정(게이트
`G-eos24-loop1-undiagnosed-wrong-criterion` · (가) 좁힌 기준)은 그 앞에 한 걸음을 인정했다 — 원인을
모르는 오답이면 가장 가까운 구조적 원인(선수 결손)을 먼저 확인한다. 그 한 걸음은 **근거가 설 때만**
딛는다(판정문 §2-1 트리 · 독립 교수학 비판 반영):

  · **연속 두 번째 오답**(직전 정책 결정이 R3·R6) → 방금 틀린 개념으로 제한한다(R6 문면). 탐침을
    틀린 경우 그 개념은 선수 P이고, EOS-124 의도 해소 (나)가 `practice_prerequisite`(목표 = P)를
    붙인다 — Kiki 기준 ⓑ. 셋째 연속 오답은 R5(임계 3)라 여기 오지 않는다. 그래서 탐침은 연속의
    **첫** 오답에서만 나간다: 둘째에서 탐침하면 그 결과를 쓸 다음 수(하강)가 없다.
  · **첫 오답인데 오답 개념 C가 막히지 않았다**(사후 숙달 ≥ 0.4) → 같은 개념. 숙달한 학생의 1회
    실수를 선수 결손으로 읽지 않는다. 막힘 판정은 계획서 §8의 선수 경계(0.4)와 같은 선이다.
  · **첫 오답 · C가 막혔다(< 0.4)** → C의 직접 선수를 본다:
      - 이미 측정된 약점(< 0.7)이 있으면 **진단하지 않는다** — C로 제한해 EOS-124 (가)가 가장 약한
        선수로 연습을 잇게 한다(아는 결손이 먼저다).
      - 아니면 **미측정** 직접 선수의 문항으로 제한한다(선수 탐침 1문항 — 진단은 모르는 것을 잰다).
        Kiki 기준 ⓐ가 여기서 선다. 한 선수는 한 번 재면 측정된 것이 되어 다시 탐침되지 않는다.
      - 탐침할 것이 없으면(엣지 없음 · 전부 숙달 · 문항 없음 · 조회 시간 초과) 같은 개념이다.
  · 같은 개념에도 문항이 없을 때만 기본 경로로 돌아간다.
  · R2(정답+미측정 확신)의 PRACTICING은 지시가 아니다 — 국면과 트리거를 둘 다 본다.

R3 경로와 달리 **근거를 새로 만들지 않는다** — 후보 집합만 바꾸고 이름표는 기본 경로의 연산
(숙달 파생 근거 + EOS-124 의도 해소)이 붙인다. 전달 문항에 대해 그 이름표가 참이기 때문이다(미측정
선수를 진단하러 내면 `diagnose · unmeasured`가 사실이다). 상태 머신이 한 일(후보 생성)은
`StateDirectiveOutcome`과 `policy_version`이 기록한다(판정문 §2-2 근거 4).

그래프 예산은 **정책이 소유한다** — 이 모듈은 예산(깊이·노드·시간)을 건 선수 읽기 함수를 주입받는다
(`PrerequisiteReader`). 여기서 예산을 다시 정의하면 예산 정의가 두 곳이 된다(천장 상수와 그
뮤테이션 하네스는 `l2/recommendation_policy.py`를 가리킨다). 정책 → 이 모듈 → 정책 순환 import도
이 주입으로 피한다.

계층: `l2`. L3~L6을 import하지 않는다. 오개념 가설은 `db.models`(공유 인프라)를 직접 읽는다 —
`l2/learner_state.py`·`l2/learning_state_evidence.py`와 같은 선례다(L4 `hypothesis_store` import
금지).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from sqlalchemy import ColumnElement, Select, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.concept import ProblemConcept
from whymath_backend.db.models.learning_state_transition import LearningStateTransition
from whymath_backend.db.models.misconception_hypothesis import MisconceptionHypothesisRecord
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.ability_estimation import difficulty_to_logit
from whymath_backend.l2.learner_state import LearnerState

# 재구현 0 — 대표 개념·최신 숙달 조회는 숙달 좌석이 소유한다(`l2.recommendation_reason` 선례).
from whymath_backend.l2.mastery_tracking import _latest_mastery, get_primary_concept_id
from whymath_backend.l2.next_problem_selection import (
    CANDIDATE_POOL_SIZE,
    CandidateRow,
    TargetCandidateRow,
    build_candidate_pool_stmt,
    load_target_candidate_rows,
)
from whymath_backend.l2.prerequisite_recommendation import PrerequisiteRow
from whymath_backend.l2.recommendation_contract import (
    PREREQUISITE_MASTERY_CEILING,
    WEAK_CONCEPT_MASTERY_CEILING,
    RecommendationReason,
    remediation_reason,
)
from whymath_backend.l2.remediation_policy import MISCONCEPTION_REMEDIATION_FLOOR
from whymath_backend.schema.enums import ConceptRole
from whymath_backend.schema.learning_state import LearningState, TransitionTrigger

__all__ = [
    "POLICY_DECISION_TRIGGERS",
    "PrerequisiteReader",
    "RemediationDirective",
    "StateDirectiveOutcome",
    "StateRoute",
    "UndiagnosedWrongDirective",
    "build_concept_candidate_pool_stmt",
    "collect_remediation_reason",
    "read_remediation_directive",
    "read_undiagnosed_wrong_directive",
    "route_by_learning_state",
]

_logger = logging.getLogger("whymath.l2.learning_state_recommendation")

#: 선수 읽기 함수 — `(오답 개념, 최대 깊이) → 선수 목록`. 그래프 예산(깊이 천장·노드 상한·시간)은
#: **호출부(정책)가 소유**한다. 이 모듈은 예산을 건 함수를 주입받아 부르기만 한다(모듈 docstring
#: "EOS-26" 절). 시간 예산 초과는 `TimeoutError`로 올라온다.
PrerequisiteReader = Callable[[uuid.UUID, int], Awaitable[Sequence[PrerequisiteRow]]]

#: 선수 탐침의 깊이 — **직접 선수만**. 예산 천장(2)이 아니라 교수학이 정한 값이다: depth 2 행은
#: 경로를 싣지 않아, 숙달된 직접 선수 뒤의 기초(이미 덮인 것)와 약한 직접 선수 뒤의 기초를 가를 수
#: 없다(판정문 §3 ⓑ). 더 깊은 하강은 탐침을 틀린 뒤의 측정이 이끈다(EOS-124 의도 해소 (가)).
_PROBE_DEPTH: Final = 1

#: 상태 머신 **정책 결정** 트리거 — `V1_RULES`가 내는 전이만(`ATTEMPT_SUBMITTED`·생애주기 전이
#: 제외). 연속 R6 판정은 "직전 정책 결정"을 봐야 한다: 국면(`assessed_from`)은 R2와 R6가 둘 다
#: PRACTICING이라 가를 수 없다(판정문 §1-4). 새 정책 트리거가 생기면 이 집합도 함께 고친다 —
#: 거버넌스 테스트가 `POLICY_` 접두 전수와 대조해 누락을 잡는다.
POLICY_DECISION_TRIGGERS: Final[frozenset[TransitionTrigger]] = frozenset(
    {
        TransitionTrigger.POLICY_ADVANCE,
        TransitionTrigger.POLICY_PRACTICE_LOW_CONFIDENCE,
        TransitionTrigger.POLICY_REMEDIATE_MISCONCEPTION,
        TransitionTrigger.POLICY_PREREQUISITE_GAP,
        TransitionTrigger.POLICY_REPEATED_FAILURE,
        TransitionTrigger.POLICY_PRACTICE_UNDIAGNOSED,
    }
)

#: 직전 정책 결정이 이 둘 중 하나면 이번 R6는 **연속 두 번째 오답**이다(오답을 낳는 결정은 R3·R4·
#: R5·R6이고, R4는 서빙에서 발화하지 않으며(EOS-127) R5 뒤에는 R6가 올 수 없다 — 연속 3회 이상이면
#: 계속 R5다). 둘째 오답에서는 탐침하지 않는다: 탐침을 틀리면 셋째가 R5라 그 결과를 쓸 하강이 없다.
_WRONG_ANSWER_DECISIONS: Final[frozenset[TransitionTrigger]] = frozenset(
    {
        TransitionTrigger.POLICY_REMEDIATE_MISCONCEPTION,
        TransitionTrigger.POLICY_PRACTICE_UNDIAGNOSED,
    }
)


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
    """개념 C에 노출 가능한 미시도 문항이 없다 — 기존 추천으로 돌아갔다.

    R6 경로에서도 같은 뜻으로 쓴다(같은 개념 연습으로 제한하려 했으나 그 개념에 문항이 없다)."""

    # ── R6(원인 미상 오답) 집행 — EOS-26. 아래 9값은 **후보를 제한했다**(집행했다) ──────────────
    # 사유를 하나로 뭉치지 않는 이유는 위와 같다: 고칠 곳이 다르다(EOS-124 `IntentResolution`과
    # 같은 분리 — 반증은 정상 교수학, 근거 없음은 그래프 커버리지, 문항 없음은 콘텐츠, 시간 초과는
    # 성능). 그래서 `prerequisite_probe / (R6 값 전체)`가 곧 "선수 탐침이 실제로 나간 비율"이다.

    PREREQUISITE_PROBE = "prerequisite_probe"
    """연속 첫 오답 · 오답 개념이 막혔다(< 0.4) · 아는 선수 결손 없음 — 오답 개념의 **미측정** 직접
    선수 문항으로 제한했다(선수 탐침 · 측정이 목적이라 요청 목적 그대로)."""

    SAME_CONCEPT_REPEAT = "same_concept_repeat"
    """연속 두 번째 오답(직전 정책 결정이 R3·R6) — 방금 틀린 개념으로 제한했다(R6 문면 집행)."""

    SAME_CONCEPT_NOT_BLOCKED = "same_concept_not_blocked"
    """연속 첫 오답인데 오답 개념의 사후 숙달이 선수 경계 이상(≥ 0.4)이다 — 1회 실수를 선수 결손으로
    읽지 않고 같은 개념으로 제한했다."""

    SAME_CONCEPT_ANCHOR_UNMEASURED = "same_concept_anchor_unmeasured"
    """연속 첫 오답인데 오답 개념의 숙달 측정이 없다(오답 직후라 정상이면 있어야 한다 — 숙달 전파
    공백) — 막힘을 세울 근거가 없어 같은 개념으로 제한했다(경고 로그 동반)."""

    KNOWN_PREREQUISITE_DEFICIT = "known_prerequisite_deficit"
    """연속 첫 오답 · 오답 개념이 막혔다 · 직접 선수 중 이미 측정된 약점(< 0.7)이 있다 — 진단하지
    않고 오답 개념으로 제한했다. 그 개념 앵커의 EOS-124 선수 구간 의도 (가)가 가장 약한 선수로
    연습을 잇는다(`intent_resolution=served`로 관측된다)."""

    SAME_CONCEPT_PROBE_UNSUPPORTED = "same_concept_probe_unsupported"
    """첫 오답 · 막힘인데 오답 개념에 선수 엣지가 없다 — 같은 개념으로 제한했다(그래프 커버리지
    공백일 수 있다)."""

    SAME_CONCEPT_PROBE_REFUTED = "same_concept_probe_refuted"
    """첫 오답 · 막힘인데 직접 선수가 전부 이미 숙달(≥ 0.7)이다 — 원인 후보가 선수에 없다. 같은
    개념으로 제한했다."""

    SAME_CONCEPT_PROBE_UNAVAILABLE = "same_concept_probe_unavailable"
    """첫 오답 · 막힘인데 미측정 직접 선수에 출제 가능한 미시도 문항이 없다 — 같은 개념으로
    제한했다."""

    SAME_CONCEPT_GRAPH_TIMEOUT = "same_concept_graph_timeout"
    """첫 오답 · 막힘인데 선수 조회가 시간 예산을 넘었다 — 같은 개념으로 제한했다(예외 타입명
    로그)."""


#: R6 경로가 **후보를 제한한**(=상태 머신 결정을 집행한) 결과. 나머지 R6 결과(`ANCHOR_UNRESOLVED`·
#: `NO_CANDIDATE_IN_CONCEPT`)는 제한하지 못해 기본 경로로 돌아간 것이다.
_UNDIAGNOSED_RESTRICTING: Final[frozenset[StateDirectiveOutcome]] = frozenset(
    {
        StateDirectiveOutcome.PREREQUISITE_PROBE,
        StateDirectiveOutcome.SAME_CONCEPT_REPEAT,
        StateDirectiveOutcome.SAME_CONCEPT_NOT_BLOCKED,
        StateDirectiveOutcome.SAME_CONCEPT_ANCHOR_UNMEASURED,
        StateDirectiveOutcome.KNOWN_PREREQUISITE_DEFICIT,
        StateDirectiveOutcome.SAME_CONCEPT_PROBE_UNSUPPORTED,
        StateDirectiveOutcome.SAME_CONCEPT_PROBE_REFUTED,
        StateDirectiveOutcome.SAME_CONCEPT_PROBE_UNAVAILABLE,
        StateDirectiveOutcome.SAME_CONCEPT_GRAPH_TIMEOUT,
    }
)

#: 그중 **연습**(측정이 아니다) — 탐침을 뺀 전부. 정책은 이 경로들을 요청 목적과 무관하게 학습
#: 밴드(정답 확률 70~85%)로 고른다(EOS-24 교정 경로와 같은 이유 — 정보량 최대는 학생이 절반을
#: 틀리도록 설계된 출제라 오답 직후의 연습에 쓰지 않는다 · REC-04). 탐침은 측정 자체라 제외한다.
_UNDIAGNOSED_PRACTICE: Final[frozenset[StateDirectiveOutcome]] = _UNDIAGNOSED_RESTRICTING - {
    StateDirectiveOutcome.PREREQUISITE_PROBE
}


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
class UndiagnosedWrongDirective:
    """상태 머신의 R6 결정 1건 — 추천이 집행을 **검토할** 대상(EOS-26)."""

    attempt_id: uuid.UUID | None
    """결정을 낸 응답(방금 틀린 응답). None이면 어느 개념을 봐야 할지 모른다
    (`ANCHOR_UNRESOLVED`)."""


def read_undiagnosed_wrong_directive(
    learner_state: LearnerState,
) -> UndiagnosedWrongDirective | None:
    """`LearnerState`의 학습 국면 → R6 집행 검토 대상(순수 · DB 0).

    **국면과 트리거를 둘 다 본다**(판정문 §3 ⓓ). 국면만 보면 R2(정답+미측정 확신)의 PRACTICING을
    지시로 오독한다 — 확신도를 보내지 않는 클라이언트(모바일 앱)의 모든 정답이 R2라, 정답마다 선수
    탐침이 나가게 된다. 트리거만 보면 R6 뒤에 생애주기 전이가 끼어 국면이 바뀌어도 지시가 살아 있는
    것처럼 읽힌다(`read_remediation_directive`와 같은 이유).
    """
    snapshot = learner_state.learning_state
    if snapshot is None or snapshot.state is not LearningState.PRACTICING:
        return None
    if snapshot.trigger is not TransitionTrigger.POLICY_PRACTICE_UNDIAGNOSED:
        return None
    return UndiagnosedWrongDirective(attempt_id=snapshot.attempt_id)


@dataclass(frozen=True, slots=True)
class StateRoute:
    """상태 머신 지시의 처리 결과 — 집행했으면 제한된 후보까지 함께 담는다."""

    outcome: StateDirectiveOutcome
    concept_id: uuid.UUID | None = None
    """R3: 교정 대상 개념 C. R6: 오답 개념(탐침이면 그 선수를 본 개념 · 같은 개념 연습이면 제한한
    그 개념). 찾지 못했으면 None."""
    candidate_rows: tuple[CandidateRow, ...] = ()
    """제한된 후보(집행했을 때만 비지 않는다). R3는 C의 문항, R6 탐침은 선수들의 문항."""
    misconception_confidence: float | None = None
    """집행 근거가 된 가설의 신뢰(②를 넘은 값). 집행하지 않았으면 None."""

    @property
    def applied(self) -> bool:
        """R3(오개념 교정) 결정을 집행했다 — 근거까지 상태 머신 몫으로 바꾸는 경로."""
        return self.outcome is StateDirectiveOutcome.APPLIED

    @property
    def undiagnosed_applied(self) -> bool:
        """R6(원인 미상 오답) 결정을 **후보 제한으로** 집행했다 — 이름표는 기본 경로 연산이
        붙인다."""
        return self.outcome in _UNDIAGNOSED_RESTRICTING

    @property
    def undiagnosed_practice(self) -> bool:
        """R6 집행 중 **연습** 경로(탐침 제외) — 정책이 학습 밴드로 고른다
        (`_UNDIAGNOSED_PRACTICE`)."""
        return self.outcome in _UNDIAGNOSED_PRACTICE


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


# ── R6 집행 (EOS-26) ────────────────────────────────────────────────────────────────────────


async def _previous_decision_trigger(
    session: AsyncSession, *, user_id: uuid.UUID, attempt_id: uuid.UUID
) -> TransitionTrigger | None:
    """결정 응답이 **아닌** 응답이 원장에 남긴 가장 늦은 정책 결정의 트리거 — 없으면 None.

    연속 R6 판정의 입력이다(판정문 §3 ⓒ). 국면으로 판정하지 않는 이유: R2와 R6가 둘 다 PRACTICING에
    도착해 `assessed_from`으로는 "직전이 원인 미상 오답이었나"를 가를 수 없다(§1-4).

    정렬은 `list_transitions`와 같은 키다. 원장 writer(`record_transition`)가 행마다 commit하므로
    `occurred_at`(DB `now()` = 트랜잭션 시작 시각)은 응답 사이에서 단조 증가한다. `attempt_id !=`는
    NULL(생애주기 전이) 행도 스스로 뺀다(SQL 3값 논리 — EOS-140 `_evidence_since_previous_attempt`와
    같은 이유로 `IS NOT NULL`을 따로 두지 않는다).
    """
    stmt = (
        select(LearningStateTransition.trigger)
        .where(
            LearningStateTransition.user_id == user_id,
            LearningStateTransition.attempt_id != attempt_id,
            LearningStateTransition.trigger.in_(POLICY_DECISION_TRIGGERS),
        )
        .order_by(
            desc(LearningStateTransition.occurred_at),
            desc(LearningStateTransition.transition_id),
        )
        .limit(1)
    )
    value: TransitionTrigger | None = (await session.execute(stmt)).scalar_one_or_none()
    return value


class _PrerequisiteStatus(str, Enum):
    """직접 선수 1건의 측정 상태 — 탐침 트리의 입력(판정문 §3 ⓑ)."""

    UNMEASURED = "unmeasured"
    """측정이 없다(코드 없음 포함) — **탐침(진단) 대상**이다. 진단은 모르는 것을 잰다."""

    WEAK = "weak"
    """측정된 약점(< 0.7) — 이미 아는 결손이다. 진단하지 않고 연습으로 잇는다(EOS-124 (가)와 같은
    선 · 같은 입력 — 그래서 넘기면 그쪽이 반드시 이 선수를 찾는다)."""

    STRONG = "strong"
    """측정된 숙달(≥ 0.7) — 원인 후보가 아니다."""


def _prerequisite_status(row: PrerequisiteRow, learner_state: LearnerState) -> _PrerequisiteStatus:
    """선수 1건의 측정 상태. 입력은 `learner_state.mastery`(개념코드 키) — EOS-124 선수 구간 의도
    (가)와 같은 입력·같은 경계(`< WEAK_CONCEPT_MASTERY_CEILING`면 약점)다. 경계를 따로 두면 "아는
    결손이 있다"고 넘겼는데 (가)가 그 선수를 찾지 못하는 틈이 생긴다.

    코드가 없거나 측정이 없으면 미측정이다(모른다 ≠ 숙달 · 모른다 ≠ 약점).
    """
    mastery = learner_state.mastery.get(row.concept_code) if row.concept_code is not None else None
    if mastery is None:
        return _PrerequisiteStatus.UNMEASURED
    if mastery < WEAK_CONCEPT_MASTERY_CEILING:
        return _PrerequisiteStatus.WEAK
    return _PrerequisiteStatus.STRONG


def _item_b(row: CandidateRow) -> float:
    """후보 행의 IRT 난이도 b — 보정 b 우선, 없으면 전문가 난이도의 logit(`candidate_items`와
    같다)."""
    _pid, difficulty, irt_b = row
    return irt_b if irt_b is not None else difficulty_to_logit(difficulty)


def _probe_candidates(rows: Sequence[TargetCandidateRow], theta: float) -> tuple[CandidateRow, ...]:
    """선수들의 후보(개념별로 나뉘어 온다) → 탐침 후보 풀 1개.

    한 문항이 두 선수의 PRIMARY로 걸려 두 번 오면 한 번만 센다. 합친 뒤 **기본 후보 풀과 같은 키**
    (|b−θ| 오름차순 → `problem_id`)로 정렬하고 같은 크기로 자른다 — 선택기가 동률에서 낮은 인덱스를
    고르므로, 키가 같아야 동률 처리까지 기본 경로와 같다(`candidate_pool_order_by`).
    """
    seen: set[uuid.UUID] = set()
    merged: list[CandidateRow] = []
    for pid, difficulty, irt_b, _concept in rows:
        if pid in seen:
            continue
        seen.add(pid)
        merged.append((pid, difficulty, irt_b))
    merged.sort(key=lambda row: (abs(_item_b(row) - theta), str(row[0])))
    return tuple(merged[:CANDIDATE_POOL_SIZE])


async def _same_concept_route(
    session: AsyncSession,
    *,
    concept_id: uuid.UUID,
    outcome: StateDirectiveOutcome,
    theta: float,
    attempted_ids: set[uuid.UUID],
    excluded_ids: set[uuid.UUID],
) -> StateRoute:
    """R6 문면 집행 — 후보를 그 개념의 PRIMARY 문항으로 제한한다(R3와 같은 제한 문장 · 조회 1건).

    그 개념에 미시도 문항이 없으면 제한하지 못한 것이다 — 기본 경로로 돌아가고 사유를 남긴다.
    """
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
    return StateRoute(outcome=outcome, concept_id=concept_id, candidate_rows=rows)


async def _route_undiagnosed_wrong(
    session: AsyncSession,
    learner_state: LearnerState,
    directive: UndiagnosedWrongDirective,
    *,
    theta: float,
    attempted_ids: set[uuid.UUID],
    excluded_ids: set[uuid.UUID],
    read_prerequisites: PrerequisiteReader,
) -> StateRoute:
    """R6 결정 → 선수 탐침 또는 같은 개념 연습(판정문 §2-1 트리).

    검사 순서는 **싼 것부터**: 앵커(2~3건) → 직전 결정(1건) → 오답 개념 숙달(1건) → 선수(주입
    읽기 1건) → 탐침 후보(1건). 앞에서 같은 개념으로 정해지면 그 개념 후보(1건)만 더 묻는다.
    """
    if directive.attempt_id is None:
        return StateRoute(outcome=StateDirectiveOutcome.ANCHOR_UNRESOLVED)
    user_id = uuid.UUID(learner_state.student_id)
    concept_id = await _anchor_concept(session, user_id=user_id, attempt_id=directive.attempt_id)
    if concept_id is None:
        return StateRoute(outcome=StateDirectiveOutcome.ANCHOR_UNRESOLVED)

    async def same_concept(outcome: StateDirectiveOutcome) -> StateRoute:
        return await _same_concept_route(
            session,
            concept_id=concept_id,
            outcome=outcome,
            theta=theta,
            attempted_ids=attempted_ids,
            excluded_ids=excluded_ids,
        )

    # ⓒ 연속 두 번째 오답(직전 정책 결정이 R3·R6) — R6 문면대로 방금 틀린 개념을 연습한다. 탐침을
    # 틀린 경우가 여기다(ⓑ의 근원). 둘째에서 탐침하지 않는 이유: 셋째 오답은 R5라 탐침 결과를 쓸
    # 하강이 없다(판정문 §3 ⓒ). 셋째 연속 오답은 R5라 이 함수에 오지 않는다(개입은 최대 2문항).
    previous = await _previous_decision_trigger(
        session, user_id=user_id, attempt_id=directive.attempt_id
    )
    if previous in _WRONG_ANSWER_DECISIONS:
        return await same_concept(StateDirectiveOutcome.SAME_CONCEPT_REPEAT)

    # 첫 오답 — 오답 개념이 **막혔을 때만** 선수 쪽으로 간다(계획서 §8 선수 경계 0.4와 같은 선).
    # 숙달이 높은 학생의 1회 실수를 선수 결손으로 읽지 않는다. 입력은 최신 숙달 이력이다 — 아래
    # 기본 경로 이름표(EOS-124)가 앵커 구간을 같은 값으로 판정하므로 두 판정이 갈라지지 않는다.
    row = await _latest_mastery(session, user_id, concept_id)
    anchor_mastery = float(row.mastery) if row is not None and row.mastery is not None else None
    if anchor_mastery is None:
        _logger.warning(
            "R6 선수 탐침 — 오답 직후인데 오답 개념의 숙달 측정이 없다(숙달 전파 공백) · 같은 개념 "
            "연습으로 집행. concept=%s attempt=%s",
            concept_id,
            directive.attempt_id,
        )
        return await same_concept(StateDirectiveOutcome.SAME_CONCEPT_ANCHOR_UNMEASURED)
    if anchor_mastery >= PREREQUISITE_MASTERY_CEILING:
        return await same_concept(StateDirectiveOutcome.SAME_CONCEPT_NOT_BLOCKED)

    # ⓑ 막힌 개념의 직접 선수 — 예산(시간·노드·깊이 천장)은 주입된 읽기 함수가 건다. 시간 초과는
    # 추천을 실패시키지 않는다(같은 개념 연습 + 예외 타입명 로그).
    try:
        prerequisites = await read_prerequisites(concept_id, _PROBE_DEPTH)
    except TimeoutError as exc:
        _logger.warning(
            "R6 선수 탐침 — 선수 조회 시간 예산 초과(%s) · 같은 개념 연습으로 집행. concept=%s",
            type(exc).__name__,
            concept_id,
        )
        return await same_concept(StateDirectiveOutcome.SAME_CONCEPT_GRAPH_TIMEOUT)
    if not prerequisites:
        return await same_concept(StateDirectiveOutcome.SAME_CONCEPT_PROBE_UNSUPPORTED)
    statuses = [(row, _prerequisite_status(row, learner_state)) for row in prerequisites]
    # 아는 결손이 먼저다 — 진단하지 않고 오답 개념 앵커로 EOS-124 (가)가 가장 약한 선수를 잇게 한다.
    if any(status is _PrerequisiteStatus.WEAK for _row, status in statuses):
        return await same_concept(StateDirectiveOutcome.KNOWN_PREREQUISITE_DEFICIT)
    unmeasured = [
        row.concept_id for row, status in statuses if status is _PrerequisiteStatus.UNMEASURED
    ]
    if not unmeasured:
        return await same_concept(StateDirectiveOutcome.SAME_CONCEPT_PROBE_REFUTED)
    probe_rows = _probe_candidates(
        await load_target_candidate_rows(
            session,
            theta,
            concept_ids=unmeasured,
            attempted_ids=attempted_ids,
            excluded_ids=excluded_ids,
        ),
        theta,
    )
    if not probe_rows:
        return await same_concept(StateDirectiveOutcome.SAME_CONCEPT_PROBE_UNAVAILABLE)
    return StateRoute(
        outcome=StateDirectiveOutcome.PREREQUISITE_PROBE,
        concept_id=concept_id,
        candidate_rows=probe_rows,
    )


async def route_by_learning_state(
    session: AsyncSession,
    learner_state: LearnerState,
    *,
    theta: float,
    attempted_ids: set[uuid.UUID],
    excluded_ids: set[uuid.UUID],
    read_prerequisites: PrerequisiteReader,
) -> StateRoute | None:
    """상태 머신의 결정(R3 · R6)을 추천이 집행할 수 있는지 판정하고, 되면 제한 후보까지 낸다.

    None이면 상태 머신이 추천을 지시하지 않았다 — **조회 0건**이다(순수 판정에서 끝난다). 이 덕에
    지시가 없는 요청(R1·R2·R5·생애주기 · 원장 없음)은 전환 전과 같은 쿼리 수·같은 결과를 낸다.

    지시는 요청마다 하나다 — 판독은 원장 최신 결정 하나를 보고, R3(REMEDIATING)와 R6(PRACTICING)는
    동시에 성립하지 않는다. R3를 먼저 읽는다(EOS-24 순서 유지 · 판정문 §3 ⓔ).

    R3 검사 순서는 **싼 것부터**다: 해제(순수) → 가설 신뢰(1건) → 교정 대상 개념(2~3건) → 후보(1건).
    앞에서 멈추면 뒤의 조회는 돌지 않는다. R6 순서는 `_route_undiagnosed_wrong` docstring.
    """
    directive = read_remediation_directive(learner_state)
    if directive is None:
        undiagnosed = read_undiagnosed_wrong_directive(learner_state)
        if undiagnosed is None:
            return None
        return await _route_undiagnosed_wrong(
            session,
            learner_state,
            undiagnosed,
            theta=theta,
            attempted_ids=attempted_ids,
            excluded_ids=excluded_ids,
            read_prerequisites=read_prerequisites,
        )
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
