"""L2 — Learning Event Trace: 한 학생의 학습 과정을 **시간순으로 재구성**하는 읽기 축.

설계 정본: 계획서 300 §17("세션 단위 Event Trace"). `EOS-11` acceptance ①~⑤.

────────────────────────────────────────────────────────────────────────────
왜 읽기 축인가 — 적재는 이미 있고, 없는 것은 "한 학생의 시간선"이다
────────────────────────────────────────────────────────────────────────────
학습 이벤트의 *적재*는 이미 충족돼 있다(`attempt_event` hypertable·`problem_attempt`·
`concept_mastery_history`·`misconception_hypothesis`·`assessment` …). 없던 것은 그것들을
**한 학습자의 하나의 시간선으로 합치는 조회**다 — 2026-09-16 실측 기준 기존 소비처는
전부 *집계*다(`l2/learning_metrics_rollup`(일별 롤업)·`harness/attempt_skill_event_reach_report`
(기록률)·`harness/wh1_evaluation`(지표)). 집계는 "이 학생에게 무슨 일이 순서대로 일어났는가"에
답하지 못하고, 그 질문에 답하지 못하면 역추적(왜 이 추천이 나왔는가)이 불가능하다.

**그래서 새 store를 만들지 않는다**(EOS-11 acceptance ② · DP-01 ADR "PostgreSQL 우선" 유지).
새 이벤트 테이블을 세우면 같은 사실이 두 곳에 적히고 truth source가 둘이 된다(붕괴 연쇄 ④
"유지보수 지옥"). 이 모듈은 **투영(projection)**이다 — 기존 행을 읽어 공통 봉투
(`LearningEvent`)로 옮길 뿐, 아무것도 쓰지 않는다(`session.add` 0건·commit 0건).

────────────────────────────────────────────────────────────────────────────
계약이 먼저다 — 내부 구현은 SQL이지만 호출 계약은 store에 중립이다
────────────────────────────────────────────────────────────────────────────
`build_trace()`가 반환하는 `LearningEventTrace`는 *어디서 읽었는지*를 모른다. 나중에 행동
로그가 ClickHouse로 이관되거나(DP-01 착수 조건) 전용 이벤트 스토어가 생겨도, 바뀌는 것은
이 모듈의 `_collect_*` 내부이고 소비자가 보는 타입은 그대로다. 투영 계층을 **순수 함수**
(`project_*` — DB 무접근)로 분리해 둔 이유도 같다: 질의(교체 가능)와 의미(고정)를 타입으로
갈라 둔다.

────────────────────────────────────────────────────────────────────────────
"없음"과 "미생산"과 "미결합"을 같은 글자로 쓰지 않는다 (acceptance ⑤)
────────────────────────────────────────────────────────────────────────────
트레이스가 비어 있을 때 그것이 *이 학생이 안 했다*는 뜻인지 *애초에 아무도 기록하지 않는다*는
뜻인지 구분되지 않으면, 미측정이 무활동으로 읽힌다(CLAUDE.md "작동한 비율" 원칙). 그래서 결과는
행뿐 아니라 **원천별 가용성 대장**(`coverage`)을 함께 낸다. 3상태다:

  - `PRODUCED`   — 생산자가 실재하고 학습자 축으로 결합 가능. 0건이면 진짜 "이 학생은 없음".
  - `DORMANT`    — 테이블·소비 표면은 있는데 **생산자가 0건**. 0건은 학생이 아니라 우리 탓이다.
  - `UNJOINABLE` — 생산자는 있으나 **학습자 축으로 조인 불가**. 데이터는 쌓이는데 이 학생 것을
                   집어낼 방법이 없다.

2026-09-16 main 기준 실측 배정은 `_SOURCE_REGISTRY`에 인용과 함께 고정돼 있고, 그 배정이
실제 코드와 어긋나면 `tests/backend/l2/test_learning_event_trace.py`의 거버넌스 테스트가 깬다.

EOS-131(2026-09-25)이 두 원천을 `PRODUCED`로 옮겼다 — `learning_session`(서버 30분 유휴 규칙
writer 신설 → `concept_selected`)과 `evidence_event`의 추천 처치(실 `session_id` 결합 →
`recommendation_generated`). 추천은 `evidence_event`에 `user_id`가 없으므로 **`learning_session`
조인으로만** 이 학습자 것으로 집어낸다(`_recommendation_stmt`). 세션 행이 지워지면(삭제권) 그
추천은 이 시간선에서 사라진다 — 결합이 끊긴 것이 정확한 상태다.

────────────────────────────────────────────────────────────────────────────
개인정보 경계 (acceptance ④ · DP-02 payload allowlist 승계)
────────────────────────────────────────────────────────────────────────────
트레이스에는 **학생 원문 답안·풀이·수식·이미지·좌표를 싣지 않는다**. `problem_attempt`는
답안을 봉투 암호화해 보관하지만 이 투영은 복호 경로를 아예 갖지 않는다 — 대신 `attempt_id`
포인터만 남겨 권한 있는 기존 표면(`/v1/me/attempts`·프라이버시 export)으로 되짚게 한다
(구조적 차단: 이 모듈의 어떤 함수 시그니처에도 답안 슬롯이 없다).

`attempt_event.event_data`도 통째로 싣지 않는다. `_DETAIL_ALLOWLIST`가 타입별로 *비식별
스칼라 키만* 열거하고 그 밖은 버린다 — 특히 `시각화조작.payload`는 계약상 자유형이라
정밀 좌표가 들어올 수 있어 통째로 제외한다(DP-02 금지 축).

열람 스코프의 기본값은 **학생 본인**이다. 이 모듈은 `learner_id`를 인자로 받을 뿐 인가를
판정하지 않으므로, 호출부(API 핸들러)가 본인 스코프를 강제해야 한다.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import Any, Final, Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import AttemptEvent, LearningSession, ProblemAttempt
from whymath_backend.db.models.assessment import (
    AbilitySnapshot,
    Assessment,
    ConceptMasteryHistory,
    SkillMasteryHistory,
)
from whymath_backend.db.models.evidence_event import EvidenceEvent
from whymath_backend.db.models.misconception_hypothesis import MisconceptionHypothesisRecord
from whymath_backend.l2.learning_metrics_rollup import effective_event_moment
from whymath_backend.l2.recommendation_evidence import (
    EVENT_TYPE_RECOMMENDATION_TREATMENT,
    META_KEY_MODE,
    META_KEY_POLICY_VERSION,
    META_KEY_PROBLEM_ID,
)
from whymath_backend.schema.enums import EventType

__all__ = [
    "DEFAULT_TRACE_LIMIT",
    "MAX_TRACE_LIMIT",
    "LearningEvent",
    "LearningEventTrace",
    "MasteryChange",
    "SourceAvailability",
    "SourceCoverage",
    "TimeBasis",
    "TraceEventType",
    "TraceSource",
    "build_trace",
    "render_trace_lines",
    "source_registry",
]

_logger = logging.getLogger("whymath.l2.learning_event_trace")

DEFAULT_TRACE_LIMIT: Final = 200
MAX_TRACE_LIMIT: Final = 1000


# ──────────────────────────────────────────────────────────────────────────
# 어휘 — 계획서 §17의 트레이스 이벤트 이름
# ──────────────────────────────────────────────────────────────────────────
class TraceEventType(str, Enum):
    """트레이스 이벤트 어휘 — §17 예시 10종 + 실제 생산 중인 행동 이벤트 축.

    **`schema.enums.EventType`과 다른 층위다.** `EventType`은 `attempt_event` 한 테이블의
    물리 이벤트 종류(한글 12종)이고, 이쪽은 *여러 테이블을 가로지르는* 학습 사건의 논리
    어휘다. 둘의 매핑은 `_ATTEMPT_EVENT_TYPE_MAP`이 고정한다 — 새 EventType이 생겼는데
    여기 매핑이 없으면 거버넌스 테스트가 깬다(조용한 누락 금지).
    """

    # §17 예시에 이름이 나오는 10종
    DIAGNOSTIC_STARTED = "diagnostic_started"
    DIAGNOSTIC_COMPLETED = "diagnostic_completed"
    LEARNER_STATE_CREATED = "learner_state_created"
    CONCEPT_SELECTED = "concept_selected"
    CONTENT_VIEWED = "content_viewed"
    PROBLEM_ATTEMPTED = "problem_attempted"
    ASSESSMENT_FAILED = "assessment_failed"
    MISCONCEPTION_DETECTED = "misconception_detected"
    MASTERY_UPDATED = "mastery_updated"
    RECOMMENDATION_GENERATED = "recommendation_generated"

    # §17의 "..."에 해당하는 구간 — 실제 생산자가 있어 시간선에 실린다
    SKILL_MASTERY_UPDATED = "skill_mastery_updated"
    ABILITY_MEASURED = "ability_measured"
    SKILLS_RESOLVED = "skills_resolved"
    VERIFICATION_RECORDED = "verification_recorded"
    HINT_PROVIDED = "hint_provided"
    HINT_REQUESTED = "hint_requested"
    STUCK_DETECTED = "stuck_detected"
    ANSWER_SUBMITTED = "answer_submitted"
    VISUALIZATION_INTERACTED = "visualization_interacted"


class TraceSource(str, Enum):
    """투영 원천 테이블 — 각 `LearningEvent`가 어디서 왔는지(역추적 필수 축)."""

    ASSESSMENT = "assessment"
    PROBLEM_ATTEMPT = "problem_attempt"
    ATTEMPT_EVENT = "attempt_event"
    CONCEPT_MASTERY_HISTORY = "concept_mastery_history"
    SKILL_MASTERY_HISTORY = "skill_mastery_history"
    ABILITY_SNAPSHOT = "ability_snapshot"
    MISCONCEPTION_HYPOTHESIS = "misconception_hypothesis"
    LEARNING_SESSION = "learning_session"
    USER_STATE_SNAPSHOT = "user_state_snapshot"
    CONCEPT_CONTENT = "concept_content"
    EVIDENCE_EVENT = "evidence_event"


class SourceAvailability(str, Enum):
    """원천의 가용 상태 — "0건"의 의미를 결정하는 축(모듈 docstring 참조)."""

    PRODUCED = "produced"
    DORMANT = "dormant"
    UNJOINABLE = "unjoinable"


class TimeBasis(str, Enum):
    """`occurred_at`의 근거 — 발생 신고인가 서버 수신인가.

    둘을 같은 글자로 쓰면 오프라인 태블릿의 지연 도착이 "그때 일어난 일"로 읽힌다
    (EOS-48 발생/수신 분리 계약 승계). 폴백했으면 폴백했다고 말한다.
    """

    OCCURRED = "occurred"
    INGESTED = "ingested"


# ──────────────────────────────────────────────────────────────────────────
# 원천 대장 — 배정 근거를 코드에 고정(실측 인용 포함)
# ──────────────────────────────────────────────────────────────────────────
class SourceCoverage(BaseModel):
    """한 트레이스 이벤트 타입의 원천·가용성·이번 조회 결과 건수."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: TraceEventType
    source: TraceSource
    availability: SourceAvailability
    #: 이번 조회에서 이 타입으로 투영된 행 수. `availability != PRODUCED`면 항상 0이고,
    #: 그 0은 "학생이 안 했다"가 아니라 `reason`이 말하는 이유 때문이다.
    count: int = 0
    reason: str


_REASON_PRODUCED_LEARNING_SESSION = (
    "l2/learning_session_writer가 인증된 학습 활동(/me/next-problem·/me/attempts·코치 턴)마다 "
    "서버 30분 유휴 규칙으로 learning_session을 잇거나 연다(EOS-131). 세션 개시(started_at)를 "
    "이 이벤트로 투영한다 — target_concept_id는 이 writer가 채우지 않으므로 concept_id는 비어 "
    "있을 수 있고, 그 None은 '목표 개념을 지정하지 않은 활동 묶음'이라는 사실이다."
)
_REASON_DORMANT_USER_STATE = (
    "user_state_snapshot에 생성 경로가 없다 — ORM·스키마는 있으나 writer 0건"
    "(2026-09-16 실측). LearnerState는 l2/learner_state.get_state가 매 호출 조립하고 "
    "영속하지 않으므로 '상태가 만들어진 순간'이라는 시각 자체가 기록되지 않는다."
)
_REASON_DORMANT_CONTENT_VIEW = (
    "학습자별 콘텐츠 열람 로그가 없다 — concept_content는 조회 표면만 있고 "
    "'누가 언제 봤다'를 남기는 좌석이 0건이다(2026-09-16 실측)."
)
_REASON_PRODUCED_RECOMMENDATION = (
    "l2/recommendation_evidence.record_recommendation_treatment가 실 learning_session.session_id로 "
    "기록한다(EOS-131 — 종전 uuid4 placeholder). evidence_event에는 여전히 user_id가 없고 "
    "(구조적 차단 유지) 학습자 결합은 evidence_event.session_id → learning_session.user_id "
    "조인으로 "
    "얻는다. 세션 기록이 실패한 드문 호출은 placeholder로 남아 이 시간선에 실리지 않는다."
)

_SOURCE_REGISTRY: Final[tuple[tuple[TraceEventType, TraceSource, SourceAvailability, str], ...]] = (
    (
        TraceEventType.DIAGNOSTIC_STARTED,
        TraceSource.ASSESSMENT,
        SourceAvailability.PRODUCED,
        "api/me.py의 진단 capture·assemble이 Assessment.from_schema로 적재(started_at).",
    ),
    (
        TraceEventType.DIAGNOSTIC_COMPLETED,
        TraceSource.ASSESSMENT,
        SourceAvailability.PRODUCED,
        "같은 행의 completed_at — 미완료(NULL)면 이 이벤트는 나오지 않는다.",
    ),
    (
        TraceEventType.LEARNER_STATE_CREATED,
        TraceSource.USER_STATE_SNAPSHOT,
        SourceAvailability.DORMANT,
        _REASON_DORMANT_USER_STATE,
    ),
    (
        TraceEventType.CONCEPT_SELECTED,
        TraceSource.LEARNING_SESSION,
        SourceAvailability.PRODUCED,
        _REASON_PRODUCED_LEARNING_SESSION,
    ),
    (
        TraceEventType.CONTENT_VIEWED,
        TraceSource.CONCEPT_CONTENT,
        SourceAvailability.DORMANT,
        _REASON_DORMANT_CONTENT_VIEW,
    ),
    (
        TraceEventType.PROBLEM_ATTEMPTED,
        TraceSource.PROBLEM_ATTEMPT,
        SourceAvailability.PRODUCED,
        "api/me.py submit_attempt·api/coach.py 완료 확정이 ProblemAttempt를 적재.",
    ),
    (
        TraceEventType.ASSESSMENT_FAILED,
        TraceSource.PROBLEM_ATTEMPT,
        SourceAvailability.PRODUCED,
        "같은 attempt 행의 is_correct=False에서 파생 — 정답이면 나오지 않고 "
        "problem_attempted.correct가 그 사실을 운반한다(미채점 NULL은 둘 다 아님).",
    ),
    (
        TraceEventType.MISCONCEPTION_DETECTED,
        TraceSource.MISCONCEPTION_HYPOTHESIS,
        SourceAvailability.PRODUCED,
        "l4/misconception/hypothesis_store.py가 가설 신설 시 적재(created_at).",
    ),
    (
        TraceEventType.MASTERY_UPDATED,
        TraceSource.CONCEPT_MASTERY_HISTORY,
        SourceAvailability.PRODUCED,
        "l2/mastery_tracking.py가 채점마다 측정 1행 적재 — 변경 전후는 같은 "
        "(user, concept) 파티션의 직전 행에서 SQL lag로 복원한다.",
    ),
    (
        TraceEventType.RECOMMENDATION_GENERATED,
        TraceSource.EVIDENCE_EVENT,
        SourceAvailability.PRODUCED,
        _REASON_PRODUCED_RECOMMENDATION,
    ),
    (
        TraceEventType.SKILL_MASTERY_UPDATED,
        TraceSource.SKILL_MASTERY_HISTORY,
        SourceAvailability.PRODUCED,
        "l2/skill_mastery_tracking.py가 행동(스킬) 축 측정을 적재 — 전후 복원 방식 동일.",
    ),
    (
        TraceEventType.ABILITY_MEASURED,
        TraceSource.ABILITY_SNAPSHOT,
        SourceAvailability.PRODUCED,
        "api/me.py capture_ability_snapshot·세션 종료 자동 적재가 θ 스냅샷을 남긴다.",
    ),
    (
        TraceEventType.SKILLS_RESOLVED,
        TraceSource.ATTEMPT_EVENT,
        SourceAvailability.PRODUCED,
        "l2/attempt_skill_event.py가 채점 확정 시 `문제시도` 이벤트로 해소 스킬을 적재.",
    ),
    (
        TraceEventType.VERIFICATION_RECORDED,
        TraceSource.ATTEMPT_EVENT,
        SourceAvailability.PRODUCED,
        "api/coach.py `검산결과` — 스테이트풀 코치의 풀이 제출 턴에만.",
    ),
    (
        TraceEventType.HINT_PROVIDED,
        TraceSource.ATTEMPT_EVENT,
        SourceAvailability.PRODUCED,
        "api/coach.py `힌트제공`(supply·hint_level 1~4).",
    ),
    (
        TraceEventType.HINT_REQUESTED,
        TraceSource.ATTEMPT_EVENT,
        SourceAvailability.PRODUCED,
        "api/coach.py `힌트요청`(demand — 학생이 답을 요구한 발화).",
    ),
    (
        TraceEventType.STUCK_DETECTED,
        TraceSource.ATTEMPT_EVENT,
        SourceAvailability.PRODUCED,
        "api/coach.py `막힘`(turn_count ≥ 5 임계 도달).",
    ),
    (
        TraceEventType.ANSWER_SUBMITTED,
        TraceSource.ATTEMPT_EVENT,
        SourceAvailability.PRODUCED,
        "api/coach.py `답입력`(직전 학생 턴 대비 서버 지연).",
    ),
    (
        TraceEventType.VISUALIZATION_INTERACTED,
        TraceSource.ATTEMPT_EVENT,
        SourceAvailability.PRODUCED,
        "api/interactions.py `시각화조작` — payload 자유형이라 종류만 싣고 내부는 버린다.",
    ),
)


def source_registry() -> tuple[SourceCoverage, ...]:
    """원천 대장을 건수 0의 `SourceCoverage` 튜플로 — 조회 전 기본 상태."""
    return tuple(
        SourceCoverage(event_type=et, source=src, availability=av, reason=reason)
        for et, src, av, reason in _SOURCE_REGISTRY
    )


#: `attempt_event`의 물리 EventType → 논리 트레이스 어휘.
#: 휴면 5종(문제읽기·조건분석·그래프그리기·계산·지움)은 생산자가 0이라 **의도적으로 비어 있다**
#: — 매핑을 미리 만들면 "읽고 있다"는 착시를 준다(`learner_state.py` v0 범위 원칙 동형).
_ATTEMPT_EVENT_TYPE_MAP: Final[Mapping[EventType, TraceEventType]] = {
    EventType.문제시도: TraceEventType.SKILLS_RESOLVED,
    EventType.검산결과: TraceEventType.VERIFICATION_RECORDED,
    EventType.힌트제공: TraceEventType.HINT_PROVIDED,
    EventType.힌트요청: TraceEventType.HINT_REQUESTED,
    EventType.막힘: TraceEventType.STUCK_DETECTED,
    EventType.답입력: TraceEventType.ANSWER_SUBMITTED,
    EventType.시각화조작: TraceEventType.VISUALIZATION_INTERACTED,
}

#: 생산자가 0건이라 매핑하지 않는 EventType — 거버넌스 테스트가 이 집합과
#: `_ATTEMPT_EVENT_TYPE_MAP`의 합집합이 `EventType` 전체와 같은지 확인한다(누락 0).
_DORMANT_EVENT_TYPES: Final[frozenset[EventType]] = frozenset(
    {
        EventType.문제읽기,
        EventType.조건분석,
        EventType.그래프그리기,
        EventType.계산,
        EventType.지움,
    }
)

#: `event_data`에서 트레이스로 옮길 **비식별 스칼라 키**만 타입별로 열거(DP-02 승계).
#: 여기 없는 키는 버린다 — 특히 `시각화조작.payload`(자유형·좌표 유입 가능)는 의도적 제외다.
_DETAIL_ALLOWLIST: Final[Mapping[EventType, tuple[str, ...]]] = {
    EventType.문제시도: ("is_correct", "source"),
    EventType.검산결과: ("passed", "error_kind", "mode"),
    EventType.힌트제공: ("hint_level", "mode"),
    EventType.힌트요청: ("mode",),
    EventType.막힘: ("turn_count", "mode"),
    EventType.답입력: ("server_latency_ms", "mode"),
    EventType.시각화조작: ("interaction",),
}

#: allowlist를 통과한 값 중에서도 이 타입들만 싣는다 — dict/list가 통과하면
#: 중첩 자유형이 다시 들어온다(키 이름만으로는 막을 수 없는 축).
_ALLOWED_DETAIL_VALUE_TYPES: Final = (str, int, float, bool)


# ──────────────────────────────────────────────────────────────────────────
# 봉투 — 최소 이벤트 스키마
# ──────────────────────────────────────────────────────────────────────────
class MasteryChange(BaseModel):
    """숙달 변경 전후 — 역추적의 전제(계획서 §17 `mastery_updated(0.54→0.43)`).

    `mastery_before`가 `None`이면 **이 개념/스킬의 첫 측정**이다. 0.0으로 채우지 않는다 —
    "몰랐다(0.0)"와 "잰 적이 없다(NULL)"는 다른 사실이고, 둘을 합치면 첫 채점이 항상
    '0.0에서 올랐다'는 없는 상승으로 보인다(S3-07 None≠0 규약).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mastery_before: float | None = Field(default=None, description="직전 측정값. None=첫 측정.")
    mastery_after: float | None = Field(default=None, description="이번 측정값.")
    is_first_measurement: bool = Field(description="True면 before가 없는 것이 정상이다.")
    confidence: float | None = None
    sample_size: int | None = None

    @property
    def delta(self) -> float | None:
        """변화량 — 첫 측정이거나 어느 한쪽이 없으면 None(0.0으로 접지 않는다)."""
        if self.mastery_before is None or self.mastery_after is None:
            return None
        return self.mastery_after - self.mastery_before


class LearningEvent(BaseModel):
    """학습 이벤트 봉투 — 여러 원천을 하나의 시간선으로 합치는 공통 모양.

    **필수**: `event_type`·`learner_id`·`occurred_at`·`time_basis`·`source`.
    나머지는 전부 선택이며 `None`은 "이 이벤트에 그 축이 없다"는 뜻이다(빈 값 날조 금지).

    계획서 §4의 최소 스키마와의 대조:
      - `event_type`·`learner_id`·`session_id`·`problem_id`·`concept_id`·`correct`·
        `response_time_ms`·`timestamp`(→`occurred_at`)는 그대로 있다.
      - `answer`(학생 원문 답안)는 **의도적으로 없다** — 미성년 원문은 트레이스에 싣지 않는다
        (모듈 docstring 개인정보 경계·DP-02). 대신 `attempt_id` 포인터를 남겨 권한 있는
        기존 표면으로 되짚는다. 이 제외는 CLAUDE.md 의사결정 우선순위 ②(법적·윤리)가
        ⑤(UX)보다 앞선다는 판단이다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: TraceEventType
    learner_id: uuid.UUID
    occurred_at: datetime
    time_basis: TimeBasis
    source: TraceSource

    session_id: uuid.UUID | None = None
    attempt_id: uuid.UUID | None = None
    problem_id: uuid.UUID | None = None
    concept_id: uuid.UUID | None = None
    skill_id: str | None = None
    misconception_id: str | None = None

    correct: bool | None = Field(default=None, description="채점 결과. None=미채점.")
    response_time_ms: int | None = Field(default=None, description="응답 소요. None=미측정.")

    mastery_change: MasteryChange | None = None
    #: allowlist를 통과한 비식별 스칼라만. 빈 dict가 아니라 None이 '싣을 것이 없었다'다.
    detail: Mapping[str, str | int | float | bool] | None = None


class LearningEventTrace(BaseModel):
    """조회 결과 — 시간순 행 + 원천 가용성 대장 + 절단 고지.

    `entries`가 비어 있다고 해서 학생이 아무것도 안 한 것이 아니다. 반드시 `coverage`와
    함께 읽는다(모듈 docstring "없음/미생산/미결합").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    learner_id: uuid.UUID
    entries: tuple[LearningEvent, ...]
    coverage: tuple[SourceCoverage, ...]
    since: datetime | None = None
    until: datetime | None = None
    #: limit에 걸려 잘렸는가. True면 `entries`는 **시간창 전체가 아니다** —
    #: 잘린 결과를 전체로 읽으면 "그 뒤엔 아무 일도 없었다"는 거짓이 된다.
    truncated: bool = False
    limit: int = DEFAULT_TRACE_LIMIT

    @property
    def produced_sources(self) -> tuple[SourceCoverage, ...]:
        return tuple(c for c in self.coverage if c.availability is SourceAvailability.PRODUCED)

    @property
    def unmeasured_sources(self) -> tuple[SourceCoverage, ...]:
        """0건이 학생 탓이 아닌 원천 — 미생산·미결합. 보고에 반드시 함께 낸다."""
        return tuple(c for c in self.coverage if c.availability is not SourceAvailability.PRODUCED)


# ──────────────────────────────────────────────────────────────────────────
# 순수 투영 — DB 무접근(질의 교체와 무관하게 의미를 고정하는 층)
# ──────────────────────────────────────────────────────────────────────────
class _HasMasteryRow(Protocol):
    """`project_mastery_rows`가 읽는 행 모양 — 개념 축·스킬 축 공용."""

    measured_at: datetime
    mastery: float | None
    mastery_before: float | None
    confidence: float | None
    sample_size: int | None


def _scalar_detail(
    event_type: EventType, event_data: Mapping[str, Any] | None
) -> dict[str, str | int | float | bool] | None:
    """`event_data`에서 allowlist 키의 **스칼라 값만** 추출(없으면 None).

    두 겹으로 막는다: ①키 이름 allowlist ②값 타입 화이트리스트. 키만 막으면 계약이 확장될 때
    같은 이름 아래 dict가 들어와 자유형이 되살아난다(DP-02가 중첩까지 검사하는 이유와 같은 축).
    """
    if not event_data:
        return None
    allowed = _DETAIL_ALLOWLIST.get(event_type)
    if not allowed:
        return None
    picked: dict[str, str | int | float | bool] = {}
    for key in allowed:
        if key not in event_data:
            continue
        value = event_data[key]
        if value is None:
            continue
        if isinstance(value, _ALLOWED_DETAIL_VALUE_TYPES):
            picked[key] = value
    return picked or None


def project_assessment_rows(learner_id: uuid.UUID, rows: Sequence[Any]) -> list[LearningEvent]:
    """`assessment` 행 → 진단 시작/완료 2이벤트(완료 시각이 NULL이면 시작만)."""
    events: list[LearningEvent] = []
    for row in rows:
        if row.started_at is not None:
            events.append(
                LearningEvent(
                    event_type=TraceEventType.DIAGNOSTIC_STARTED,
                    learner_id=learner_id,
                    occurred_at=row.started_at,
                    time_basis=TimeBasis.OCCURRED,
                    source=TraceSource.ASSESSMENT,
                    detail=_assessment_detail(row),
                )
            )
        if row.completed_at is not None:
            events.append(
                LearningEvent(
                    event_type=TraceEventType.DIAGNOSTIC_COMPLETED,
                    learner_id=learner_id,
                    occurred_at=row.completed_at,
                    time_basis=TimeBasis.OCCURRED,
                    source=TraceSource.ASSESSMENT,
                    detail=_assessment_detail(row),
                )
            )
    return events


def _assessment_detail(row: Any) -> dict[str, str | int | float | bool] | None:
    kind = getattr(row, "assessment_type", None)
    if kind is None:
        return None
    return {"assessment_type": kind.value if isinstance(kind, Enum) else str(kind)}


def project_attempt_rows(learner_id: uuid.UUID, rows: Sequence[Any]) -> list[LearningEvent]:
    """`problem_attempt` 행 → `problem_attempted`(+ 오답이면 `assessment_failed`).

    시각은 발생(`started_at`) 우선·수신(`ingested_at`/`ended_at`) 폴백이고, 어느 쪽을 썼는지
    `time_basis`가 말한다. `effective_event_moment`가 시계 왜곡(발생 > 수신)도 함께 가드한다.
    """
    events: list[LearningEvent] = []
    for row in rows:
        ingested = row.ingested_at or row.ended_at or row.created_at
        if ingested is None:
            # 귀속할 시각이 하나도 없는 행은 시간선에 놓을 수 없다 — 날조 대신 건너뛰고 센다.
            _logger.warning(
                "트레이스 투영 건너뜀 — problem_attempt에 귀속 가능한 시각이 없음"
                " (attempt_id=%s): started_at·ingested_at·ended_at·created_at 전부 NULL.",
                getattr(row, "attempt_id", None),
            )
            continue
        moment = effective_event_moment(row.started_at, ingested)
        basis = TimeBasis.OCCURRED if moment == row.started_at else TimeBasis.INGESTED
        rt_ms = row.duration_seconds * 1000 if row.duration_seconds is not None else None

        events.append(
            _attempt_trace_event(
                TraceEventType.PROBLEM_ATTEMPTED,
                learner_id=learner_id,
                row=row,
                moment=moment,
                basis=basis,
                response_time_ms=rt_ms,
            )
        )
        if row.is_correct is False:
            # 미채점(None)은 실패가 아니다 — `is False`로만 파생한다.
            events.append(
                _attempt_trace_event(
                    TraceEventType.ASSESSMENT_FAILED,
                    learner_id=learner_id,
                    row=row,
                    moment=moment,
                    basis=basis,
                    response_time_ms=rt_ms,
                )
            )
    return events


def _attempt_trace_event(
    kind: TraceEventType,
    *,
    learner_id: uuid.UUID,
    row: Any,
    moment: datetime,
    basis: TimeBasis,
    response_time_ms: int | None,
) -> LearningEvent:
    """한 `problem_attempt` 행에서 트레이스 이벤트 1건 — 필드명을 dict로 넘기지 않는다.

    `LearningEvent(**some_dict)` 형태는 pydantic `init_typed` 검사를 통과해 버려 필드명 오타가
    CI가 아니라 실행 시점까지 산다(`extra="forbid"`가 잡긴 하지만 그때는 이미 런타임이다).
    """
    return LearningEvent(
        event_type=kind,
        learner_id=learner_id,
        occurred_at=moment,
        time_basis=basis,
        source=TraceSource.PROBLEM_ATTEMPT,
        session_id=row.session_id,
        attempt_id=row.attempt_id,
        problem_id=row.problem_id,
        correct=row.is_correct,
        response_time_ms=response_time_ms,
    )


def project_attempt_event_rows(learner_id: uuid.UUID, rows: Sequence[Any]) -> list[LearningEvent]:
    """`attempt_event` 행 → 행동 이벤트. 매핑 없는(휴면) 타입은 조용히 버리지 않고 센다."""
    events: list[LearningEvent] = []
    for row in rows:
        physical = row.event_type
        if physical is None:
            continue
        mapped = _ATTEMPT_EVENT_TYPE_MAP.get(physical)
        if mapped is None:
            # 휴면 타입이 실제로 생산되기 시작하면 여기로 온다 — 그때는 매핑을 늘려야 하므로
            # 침묵하지 않는다(거버넌스 테스트도 같은 사실을 CI에서 먼저 깬다).
            _logger.warning(
                "트레이스 투영 건너뜀 — attempt_event에 매핑 없는 event_type=%s"
                " (휴면 타입의 생산 개시 가능성). _ATTEMPT_EVENT_TYPE_MAP 확장 필요.",
                physical.value,
            )
            continue
        moment = effective_event_moment(row.event_time, row.event_at)
        basis = TimeBasis.OCCURRED if moment == row.event_time else TimeBasis.INGESTED
        events.append(
            LearningEvent(
                event_type=mapped,
                learner_id=learner_id,
                occurred_at=moment,
                time_basis=basis,
                source=TraceSource.ATTEMPT_EVENT,
                attempt_id=row.attempt_id,
                problem_id=row.problem_id,
                detail=_scalar_detail(physical, row.event_data),
            )
        )
    return events


def project_mastery_rows(
    learner_id: uuid.UUID,
    rows: Sequence[_HasMasteryRow],
    *,
    concept_axis: bool,
) -> list[LearningEvent]:
    """숙달 측정 행 → `mastery_updated` / `skill_mastery_updated`(전후 값 포함).

    `mastery_before`는 **질의가 SQL `lag`로 채워 준다**(같은 파티션의 직전 측정). 파이썬에서
    시간창 안의 행만 보고 직전 값을 계산하면 창 시작 직전의 측정을 못 봐서 첫 행이 늘
    '첫 측정'으로 둔갑한다 — 그래서 창 필터보다 lag가 먼저 계산된다(`_mastery_stmt`).
    """
    events: list[LearningEvent] = []
    for row in rows:
        before = row.mastery_before
        change = MasteryChange(
            mastery_before=float(before) if before is not None else None,
            mastery_after=float(row.mastery) if row.mastery is not None else None,
            is_first_measurement=before is None,
            confidence=float(row.confidence) if row.confidence is not None else None,
            sample_size=row.sample_size,
        )
        events.append(
            LearningEvent(
                event_type=(
                    TraceEventType.MASTERY_UPDATED
                    if concept_axis
                    else TraceEventType.SKILL_MASTERY_UPDATED
                ),
                learner_id=learner_id,
                occurred_at=row.measured_at,
                time_basis=TimeBasis.INGESTED,
                source=(
                    TraceSource.CONCEPT_MASTERY_HISTORY
                    if concept_axis
                    else TraceSource.SKILL_MASTERY_HISTORY
                ),
                concept_id=getattr(row, "concept_id", None) if concept_axis else None,
                skill_id=None if concept_axis else getattr(row, "skill_id", None),
                mastery_change=change,
            )
        )
    return events


def project_misconception_rows(learner_id: uuid.UUID, rows: Sequence[Any]) -> list[LearningEvent]:
    """`misconception_hypothesis` 행 → `misconception_detected`(가설 신설 시각)."""
    return [
        LearningEvent(
            event_type=TraceEventType.MISCONCEPTION_DETECTED,
            learner_id=learner_id,
            occurred_at=row.created_at,
            time_basis=TimeBasis.INGESTED,
            source=TraceSource.MISCONCEPTION_HYPOTHESIS,
            misconception_id=row.misconception_id,
            detail={
                "confidence": float(row.confidence),
                "evidence_count": row.evidence_count,
                "is_active": bool(row.is_active),
            },
        )
        for row in rows
    ]


def project_ability_rows(learner_id: uuid.UUID, rows: Sequence[Any]) -> list[LearningEvent]:
    """`ability_snapshot` 행 → `ability_measured`(θ 측정)."""
    return [
        LearningEvent(
            event_type=TraceEventType.ABILITY_MEASURED,
            learner_id=learner_id,
            occurred_at=row.measured_at,
            time_basis=TimeBasis.INGESTED,
            source=TraceSource.ABILITY_SNAPSHOT,
            concept_id=row.concept_id,
            detail={"theta": float(row.theta), "response_count": row.response_count},
        )
        for row in rows
    ]


def project_session_rows(learner_id: uuid.UUID, rows: Sequence[Any]) -> list[LearningEvent]:
    """`learning_session` 행 → `concept_selected`(세션 개시 — EOS-131 서버 유휴 규칙).

    `started_at`은 서버가 첫 활동을 *수신*한 시각이라 `INGESTED`다. `started_at`이 없는 행
    (writer 이전의 수동 적재 등)은 시간선에 놓을 수 없어 건너뛰고 경고한다(날조 금지).
    """
    events: list[LearningEvent] = []
    for row in rows:
        if row.started_at is None:
            _logger.warning(
                "트레이스 투영 건너뜀 — learning_session에 started_at이 없음 (session_id=%s).",
                getattr(row, "session_id", None),
            )
            continue
        events.append(
            LearningEvent(
                event_type=TraceEventType.CONCEPT_SELECTED,
                learner_id=learner_id,
                occurred_at=row.started_at,
                time_basis=TimeBasis.INGESTED,
                source=TraceSource.LEARNING_SESSION,
                session_id=row.session_id,
                concept_id=row.target_concept_id,
            )
        )
    return events


def _recommendation_detail(meta: Mapping[str, Any] | None) -> dict[str, str | int | float | bool]:
    """추천 meta에서 비식별 스칼라만 — 정책 버전·모드(후보 목록·사유 객체는 싣지 않는다)."""
    picked: dict[str, str | int | float | bool] = {}
    for key in (META_KEY_POLICY_VERSION, META_KEY_MODE):
        value = (meta or {}).get(key)
        if isinstance(value, _ALLOWED_DETAIL_VALUE_TYPES):
            picked[key] = value
    return picked


def _parse_uuid(value: Any) -> uuid.UUID | None:
    """meta의 문항 id 문자열 → UUID(형식이 깨졌으면 None — 날조하지 않는다)."""
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def project_recommendation_rows(learner_id: uuid.UUID, rows: Sequence[Any]) -> list[LearningEvent]:
    """`evidence_event` 추천 처치 행(세션 조인으로 이 학습자 것만) → `recommendation_generated`."""
    return [
        LearningEvent(
            event_type=TraceEventType.RECOMMENDATION_GENERATED,
            learner_id=learner_id,
            occurred_at=row.time,
            time_basis=TimeBasis.INGESTED,
            source=TraceSource.EVIDENCE_EVENT,
            session_id=row.session_id,
            problem_id=_parse_uuid((row.meta or {}).get(META_KEY_PROBLEM_ID)),
            detail=_recommendation_detail(row.meta) or None,
        )
        for row in rows
    ]


#: 같은 시각 동률의 정렬 순서 — **인과 순서**다(사전순 아님).
#: 채점은 제출과 같은 시각에 기록되므로 사전순으로 묶으면 `assessment_failed`가
#: `problem_attempted`보다 앞에 온다 — 원인보다 결과가 먼저 보이는 시간선은 읽는 사람을
#: 속인다. 계획서 §17의 흐름 순서를 그대로 계단으로 쓴다.
_TIE_ORDER: Final[Mapping[TraceEventType, int]] = {
    TraceEventType.DIAGNOSTIC_STARTED: 0,
    TraceEventType.DIAGNOSTIC_COMPLETED: 1,
    TraceEventType.LEARNER_STATE_CREATED: 2,
    TraceEventType.CONCEPT_SELECTED: 3,
    TraceEventType.CONTENT_VIEWED: 4,
    TraceEventType.HINT_REQUESTED: 5,
    TraceEventType.STUCK_DETECTED: 6,
    TraceEventType.HINT_PROVIDED: 7,
    TraceEventType.ANSWER_SUBMITTED: 8,
    TraceEventType.VISUALIZATION_INTERACTED: 9,
    TraceEventType.PROBLEM_ATTEMPTED: 10,
    TraceEventType.VERIFICATION_RECORDED: 11,
    TraceEventType.ASSESSMENT_FAILED: 12,
    TraceEventType.SKILLS_RESOLVED: 13,
    TraceEventType.MISCONCEPTION_DETECTED: 14,
    TraceEventType.MASTERY_UPDATED: 15,
    TraceEventType.SKILL_MASTERY_UPDATED: 16,
    TraceEventType.ABILITY_MEASURED: 17,
    TraceEventType.RECOMMENDATION_GENERATED: 18,
}


def sort_entries(events: Sequence[LearningEvent]) -> list[LearningEvent]:
    """시간순 정렬 — 동시각 동률은 인과 순서(`_TIE_ORDER`)·원천명으로 안정 정렬.

    안정성이 필요한 이유는 재현성이다. 같은 데이터에서 매번 다른 순서가 나오면 트레이스를
    근거로 한 판정을 두 번 다시 확인할 수 없다.
    """
    return sorted(
        events,
        key=lambda e: (e.occurred_at, _TIE_ORDER[e.event_type], e.source.value),
    )


# ──────────────────────────────────────────────────────────────────────────
# 질의 — 교체 가능한 층(현재 구현: PostgreSQL/ORM)
# ──────────────────────────────────────────────────────────────────────────
def _window(column: Any, since: datetime | None, until: datetime | None) -> list[Any]:
    conds: list[Any] = []
    if since is not None:
        conds.append(column >= since)
    if until is not None:
        conds.append(column <= until)
    return conds


def _mastery_stmt(
    model: type[ConceptMasteryHistory] | type[SkillMasteryHistory],
    axis_column: Any,
    learner_id: uuid.UUID,
    since: datetime | None,
    until: datetime | None,
    limit: int,
) -> Select[Any]:
    """숙달 시계열 + 직전 값(`lag`) — **창 필터를 lag 계산 뒤에** 건다.

    순서가 핵심이다. 창 안에서만 lag를 계산하면 창 첫 행의 '직전'이 사라져 첫 측정으로
    오인된다(없는 상승을 만든다). 그래서 학습자 전 구간에서 lag를 먼저 계산한 뒤 바깥에서
    시간창을 건다.
    """
    before = func.lag(model.mastery).over(
        partition_by=(model.user_id, axis_column),
        order_by=model.measured_at,
    )
    inner = (
        select(
            axis_column.label("axis_id"),
            model.measured_at.label("measured_at"),
            model.mastery.label("mastery"),
            model.confidence.label("confidence"),
            model.sample_size.label("sample_size"),
            before.label("mastery_before"),
        )
        .where(model.user_id == learner_id)
        .subquery()
    )
    return (
        select(inner)
        .where(*_window(inner.c.measured_at, since, until))
        .order_by(inner.c.measured_at.desc())
        .limit(limit)
    )


class _MasteryRowView:
    """`_mastery_stmt` 결과 행을 `_HasMasteryRow`+축 id로 보여 주는 얇은 뷰."""

    __slots__ = (
        "measured_at",
        "mastery",
        "mastery_before",
        "confidence",
        "sample_size",
        "concept_id",
        "skill_id",
    )

    def __init__(self, row: Any, *, concept_axis: bool) -> None:
        self.measured_at = row.measured_at
        self.mastery = row.mastery
        self.mastery_before = row.mastery_before
        self.confidence = row.confidence
        self.sample_size = row.sample_size
        self.concept_id = row.axis_id if concept_axis else None
        self.skill_id = None if concept_axis else row.axis_id


async def build_trace(
    session: AsyncSession,
    *,
    learner_id: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = DEFAULT_TRACE_LIMIT,
) -> LearningEventTrace:
    """한 학습자의 학습 과정을 시간순으로 재구성한다(읽기 전용·쓰기 0).

    **실패를 삼키지 않는다.** 원천 질의가 실패하면 예외가 그대로 올라간다 — 읽기 표면에는
    적재 경로 같은 "삼켜도 데이터가 안 죽는다"는 근거가 없고, 조용히 빠진 원천은 그 학생이
    그 행동을 안 한 것처럼 보이기 때문이다(침묵 실패 금지). 부분 결과를 성공으로 포장하는
    경로 자체를 두지 않는다.

    `limit`은 **정렬 후 전역 상한**이다. 각 원천에서 limit+1건씩 가져와 합친 뒤 자르므로,
    잘렸는지 여부(`truncated`)가 정확하다.
    """
    if limit < 1 or limit > MAX_TRACE_LIMIT:
        raise ValueError(f"limit은 1..{MAX_TRACE_LIMIT} 범위여야 합니다(받은 값: {limit}).")

    # 전역 상한보다 1건 더 — 정렬·병합 후 잘림 여부를 정확히 판정하기 위한 감시 행.
    probe = limit + 1

    assessment_rows = (
        (
            await session.execute(
                select(Assessment)
                .where(
                    Assessment.user_id == learner_id,
                    *_window(Assessment.started_at, since, until),
                )
                .order_by(Assessment.started_at.desc())
                .limit(probe)
            )
        )
        .scalars()
        .all()
    )
    attempt_rows = (
        (
            await session.execute(
                select(ProblemAttempt)
                .where(
                    ProblemAttempt.user_id == learner_id,
                    *_window(ProblemAttempt.ingested_at, since, until),
                )
                .order_by(ProblemAttempt.ingested_at.desc())
                .limit(probe)
            )
        )
        .scalars()
        .all()
    )
    event_rows = (
        (
            await session.execute(
                select(AttemptEvent)
                .where(
                    AttemptEvent.user_id == learner_id,
                    *_window(AttemptEvent.event_at, since, until),
                )
                .order_by(AttemptEvent.event_at.desc())
                .limit(probe)
            )
        )
        .scalars()
        .all()
    )
    concept_mastery_rows = (
        await session.execute(
            _mastery_stmt(
                ConceptMasteryHistory,
                ConceptMasteryHistory.concept_id,
                learner_id,
                since,
                until,
                probe,
            )
        )
    ).all()
    skill_mastery_rows = (
        await session.execute(
            _mastery_stmt(
                SkillMasteryHistory,
                SkillMasteryHistory.skill_id,
                learner_id,
                since,
                until,
                probe,
            )
        )
    ).all()
    misconception_rows = (
        (
            await session.execute(
                select(MisconceptionHypothesisRecord)
                .where(
                    MisconceptionHypothesisRecord.user_id == learner_id,
                    *_window(MisconceptionHypothesisRecord.created_at, since, until),
                )
                .order_by(MisconceptionHypothesisRecord.created_at.desc())
                .limit(probe)
            )
        )
        .scalars()
        .all()
    )
    ability_rows = (
        (
            await session.execute(
                select(AbilitySnapshot)
                .where(
                    AbilitySnapshot.user_id == learner_id,
                    *_window(AbilitySnapshot.measured_at, since, until),
                )
                .order_by(AbilitySnapshot.measured_at.desc())
                .limit(probe)
            )
        )
        .scalars()
        .all()
    )

    # EOS-131 ⑧ learning_session(세션 개시) ⑨ 추천 처치 — 추천은 user_id가 없어 세션 조인으로만.
    session_rows = (
        (
            await session.execute(
                select(LearningSession)
                .where(
                    LearningSession.user_id == learner_id,
                    *_window(LearningSession.started_at, since, until),
                )
                .order_by(LearningSession.started_at.desc())
                .limit(probe)
            )
        )
        .scalars()
        .all()
    )
    recommendation_rows = (
        (
            await session.execute(
                select(EvidenceEvent)
                .join(LearningSession, EvidenceEvent.session_id == LearningSession.session_id)
                .where(
                    LearningSession.user_id == learner_id,
                    EvidenceEvent.event_type == EVENT_TYPE_RECOMMENDATION_TREATMENT,
                    *_window(EvidenceEvent.time, since, until),
                )
                .order_by(EvidenceEvent.time.desc())
                .limit(probe)
            )
        )
        .scalars()
        .all()
    )

    collected: list[LearningEvent] = []
    collected += project_assessment_rows(learner_id, assessment_rows)
    collected += project_attempt_rows(learner_id, attempt_rows)
    collected += project_attempt_event_rows(learner_id, event_rows)
    collected += project_mastery_rows(
        learner_id,
        [_MasteryRowView(r, concept_axis=True) for r in concept_mastery_rows],
        concept_axis=True,
    )
    collected += project_mastery_rows(
        learner_id,
        [_MasteryRowView(r, concept_axis=False) for r in skill_mastery_rows],
        concept_axis=False,
    )
    collected += project_misconception_rows(learner_id, misconception_rows)
    collected += project_ability_rows(learner_id, ability_rows)
    collected += project_session_rows(learner_id, session_rows)
    collected += project_recommendation_rows(learner_id, recommendation_rows)

    ordered = sort_entries(collected)
    truncated = len(ordered) > limit
    # 잘릴 때는 **최근 쪽**을 남긴다 — 트레이스는 "지금 이 학생에게 무슨 일이 있었는가"를
    # 묻는 도구이므로 창의 오래된 끝을 버린다. 남긴 구간은 여전히 오래된→최신 순서다.
    entries = tuple(ordered[-limit:] if truncated else ordered)

    counted = dict.fromkeys((et for et, _, _, _ in _SOURCE_REGISTRY), 0)
    for entry in entries:
        counted[entry.event_type] = counted[entry.event_type] + 1
    coverage = tuple(
        cov.model_copy(update={"count": counted[cov.event_type]}) for cov in source_registry()
    )

    return LearningEventTrace(
        learner_id=learner_id,
        entries=entries,
        coverage=coverage,
        since=since,
        until=until,
        truncated=truncated,
        limit=limit,
    )


# ──────────────────────────────────────────────────────────────────────────
# 사람이 읽는 렌더 — 계획서 §17의 화살표 나열 형태
# ──────────────────────────────────────────────────────────────────────────
def render_trace_lines(trace: LearningEventTrace) -> list[str]:
    """§17 예시 형태의 한 줄씩 나열 — `mastery_updated(0.54→0.43)` 표기 포함.

    렌더는 *표현*이므로 계약이 아니다(CLAUDE.md "표현 ≠ 의미") — 구조는 `LearningEventTrace`가
    정본이고 이 함수는 사람이 눈으로 확인할 때만 쓴다.
    """
    lines: list[str] = []
    for entry in trace.entries:
        label = entry.event_type.value
        change = entry.mastery_change
        if change is not None:
            before = "미측정" if change.mastery_before is None else f"{change.mastery_before:.2f}"
            after = "?" if change.mastery_after is None else f"{change.mastery_after:.2f}"
            label = f"{label}({before}→{after})"
        axis = entry.concept_id or entry.skill_id or entry.misconception_id or entry.problem_id
        suffix = f"  [{axis}]" if axis is not None else ""
        basis = "" if entry.time_basis is TimeBasis.OCCURRED else "~"
        lines.append(f"{entry.occurred_at.isoformat()}{basis}  {label}{suffix}")
    if trace.truncated:
        lines.append(
            f"… limit={trace.limit}에 걸려 앞부분이 잘렸습니다 — 이 목록은 시간창 전체가 아닙니다."
        )
    for cov in trace.unmeasured_sources:
        lines.append(f"[{cov.availability.value}] {cov.event_type.value} — {cov.reason}")
    return lines
