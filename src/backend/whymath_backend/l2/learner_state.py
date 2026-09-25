"""L2 — `LearnerState` v0 조립기: L2가 L3/L4에 주입하는 *단일 요약 상태*.

설계 정본: `docs/architecture/02_learner_model.md` §"출력 — LearnerState"(L131-159, 2026-07-30
PED-05 편집자 부기로 v0 범위 축소). 원안은 11필드를 명세했으나 코드에 `LearnerState` 클래스 자체가
없어 소비처(`api/coach.py`·`api/study.py`)마다 `compute_concept_diagnoses`·`get_current_theta` 등
조각을 직접 호출해 흩어져 있었다. 이 모듈이 그 조각들을 **재사용만**(신규 계산 0) 해 단일 조립기로
묶는다.

**v0 범위 원칙**: `l4/pedagogy/runtime_selector.py:96-118`의 `StudentSignals` 결정("생산자 없는
신호는 필드로 만들지 않는다 — 항상 None인 필드는 '읽고 있다'는 착시만 준다")과 동형이다. 원안
11필드 중 실제 생산자가 있는 8개(mastery·general_ability·domain_abilities·active_misconceptions·
recent_struggles·recent_successes·grade·goals)만 v0에 담는다. 나머지 5개(curriculum·affect·
mastery_states·active_textbook_id·shadow_curriculum_progress)의 제외 사유는 `LearnerState`
클래스 docstring 참조.

**7계층 경계(중요)**: 이 모듈은 **L4를 import하지 않는다**(CLAUDE.md "L_n은 L_{n+1}을 알지
못한다" — 역방향 의존 금지). `active_misconceptions`가 필요로 하는 활성 오개념 가설은
`l4/misconception/hypothesis_store.py:get_active_hypotheses`와 **같은 모양의 SELECT**를
`_get_active_misconception_ids`가 이 모듈 안에서 직접 재구현한다(ORM `MisconceptionHypothesisRecord`
는 `db/models/`로 계층 소속이 아니라 공유 인프라이므로 import 가능 — L2 자신도 이미 자기
테이블들을 이렇게 직접 쿼리한다). 전체 레코드→Pydantic 변환 없이 `misconception_id` 컬럼만
select한다(이 조립기는 id 리스트만 필요).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.learning_state_transition import LearningStateTransition
from whymath_backend.db.models.misconception_hypothesis import (
    MisconceptionHypothesisRecord,
)
from whymath_backend.db.models.user import UserProfile
from whymath_backend.l2.ability_tracking import get_current_theta
from whymath_backend.l2.concept_diagnosis import compute_concept_diagnoses
from whymath_backend.l2.learning_state_machine import INITIAL_STATE, list_transitions
from whymath_backend.l2.skill_mastery_tracking import get_all_current_skill_mastery
from whymath_backend.schema.learning_state import LearningState, TransitionTrigger

__all__ = [
    "FieldOrigin",
    "FieldStatus",
    "LearnerState",
    "LearningStateSnapshot",
    "get_state",
]

# LTHC 숙달도 임계값의 **값만 미러링**(import 아님) — `l4/lthc/adapt.py`의 `_DEVELOPING_THRESHOLD`
# (0.4)·`_MASTERED_THRESHOLD`(0.8)와 반드시 같은 값을 유지해야 하지만, L2는 L4를 import할 수
# 없다(CLAUDE.md "L_n은 L_{n+1}을 알지 못한다" — 역방향 의존 금지·본 모듈 최상단 docstring).
# `from whymath_backend.l4.lthc.adapt import ...`는 L2→L4 역방향 의존이라 금지 대상 자체이므로,
# 두 계층이 공유할 수 있는 더 낮은 위치(schema/ 등)로 상수가 이동하기 전까지는 **값을 복제**하고
# 이 주석으로 원본 출처·동기화 의무를 명시한다(새 매직넘버가 아니라 "기존 상수의 문서화된 사본").
_DEVELOPING_THRESHOLD = 0.4  # l4/lthc/adapt.py::_DEVELOPING_THRESHOLD와 동기화 필수
_MASTERED_THRESHOLD = 0.8  # l4/lthc/adapt.py::_MASTERED_THRESHOLD와 동기화 필수


class FieldStatus(str, enum.Enum):
    """`LearnerState` 한 필드가 **왜** 그 값인지 — 값의 부재를 세 가지로 갈라 적는다.

    "값이 없다"는 한 가지 사실이 아니다. 셋을 같은 `None`으로 접으면 읽는 쪽이
    *고칠 수 있는 것*(데이터를 더 모으면 된다)과 *고칠 수 없는 것*(생산자를 먼저 만들어야
    한다)을 구별하지 못한다. CLAUDE.md "모른다 ≠ 아니다"(3상태를 truthiness로 2상태로 접지
    말 것)와 "작동 신호 없는 알고리즘 부착 금지"(알고리즘이 **실제로 작동한 비율**을 응답이
    말해야 한다)의 이행이다.
    """

    MEASURED = "measured"
    """생산자가 있고, 이 학생의 데이터로 값이 나왔다."""

    NO_DATA = "no_data"
    """생산자는 있으나 이 학생의 측정 이력이 없다 — 풀이가 쌓이면 채워진다."""

    NO_PRODUCER = "no_producer"
    """저장소에 생산자 자체가 없다 — 이 학생이 무엇을 해도 채워지지 않는다."""


class FieldOrigin(BaseModel):
    """한 필드의 유래 — **교체 가능성을 주석이 아니라 타입으로** 표현하는 축.

    계획서 300 §2("알고리즘보다 Contract")의 이행이다. v1 내부 구현이 BKT여도 나중에 DKT로
    갈아끼울 때 `LearnerState`의 *모양*은 바뀌지 않아야 한다 — 바뀌는 것은 `estimator`
    **문자열 값**뿐이고, 호출부는 그대로다. 추정기 이름을 docstring에만 적어 두면 교체 시
    그 사실이 응답에 드러나지 않아 소비처가 "무엇이 이 숫자를 냈는지" 알 수 없다.
    """

    status: FieldStatus = Field(description="값이 있는지·없다면 왜 없는지.")
    estimator: str | None = Field(
        default=None,
        description="이 값을 낸 추정기 식별자(예 `bkt.v1`·`irt.2pl`). 추정이 아니라 프로필·"
        "저장소 조회로 나온 값이면 None. **BKT→DKT 교체 시 바뀌는 곳이 여기다.**",
    )
    seat: str | None = Field(
        default=None,
        description="값을 낸 좌석(모듈 경로). 생산자가 없으면 None — 그 자체가 `NO_PRODUCER`의 "
        "증거다.",
    )


# 추정기 식별자 — `FieldOrigin.estimator`에 실리는 값의 정본. 교체 시 여기만 바꾼다.
_EST_BKT = "bkt.v1"
_EST_IRT = "irt.2pl"

# 좌석 경로 — `FieldOrigin.seat`에 실리는 값. 값을 실제로 낸 모듈을 가리킨다.
_SEAT_DIAGNOSIS = "l2.concept_diagnosis.compute_concept_diagnoses"
_SEAT_ABILITY = "l2.ability_tracking.get_current_theta"
_SEAT_SKILL = "l2.skill_mastery_tracking.get_all_current_skill_mastery"
_SEAT_MISCONCEPTION = "db.models.misconception_hypothesis.MisconceptionHypothesisRecord"
_SEAT_PROFILE = "db.models.user.UserProfile"
_SEAT_LEARNING_STATE = "l2.learning_state_machine.list_transitions"

#: 학습 국면 스냅샷이 원장에서 읽는 최신 전이 수. **2인 이유**: 정책 결정 1건은 원장에 두 행을
#: 남긴다(`ATTEMPT_SUBMITTED`로 평가 진입 → 정책 결정). 최신 1행만 보면 "그 결정을 낸 응답이
#: *어느 국면에서* 제출됐는가"(`assessed_from`)를 알 수 없고, 추천은 그것으로 교정 고정을 푼다
#: (EOS-24 판정문 §4 안전장치 ③).
_LEARNING_STATE_ROWS = 2


def _origin(
    has_value: bool, *, estimator: str | None = None, seat: str | None = None
) -> FieldOrigin:
    """생산자가 **있는** 필드의 유래 — 값이 나왔으면 MEASURED, 안 나왔으면 NO_DATA.

    `NO_PRODUCER`는 이 헬퍼로 만들지 않는다(생산자 부재는 런타임 데이터가 아니라 저장소의
    구조적 사실이라 호출부에 리터럴로 박힌다 — 그래야 생산자가 생겼을 때 그 줄을 지우는 것이
    변경의 전부가 된다).
    """
    return FieldOrigin(
        status=FieldStatus.MEASURED if has_value else FieldStatus.NO_DATA,
        estimator=estimator,
        seat=seat,
    )


class LearningStateSnapshot(BaseModel):
    """학습 상태 머신의 **현재 국면 + 그 국면을 만든 최신 결정** — 원장 최신 전이의 요약 (EOS-24).

    왜 `LearnerState` 안에 두는가: 추천 정책의 계약은 `(learner_state, learning_context)` 둘만
    받는다(`l2.recommendation_contract.RecommendationPolicy`). 상태 머신의 국면은 *학습자 상태*이지
    요청 상황이 아니므로, 정책이 DB를 따로 읽지 않고 이 필드로 받는 것이 계약에 맞는 배선이다.
    이 필드가 생기기 전에는 추천이 상태 머신을 읽을 경로 자체가 없었다(EOS-24 acceptance ①).

    파생값이다 — 원장(`learning_state_transition`)이 정본이고 이것은 호출 시점의 읽기 사본이다.
    이 스냅샷은 어떤 테이블에도 쓰이지 않는다.
    """

    state: LearningState = Field(
        description="현재 학습 국면 — 원장 최신 행의 `to_state`. 원장이 비었으면 `NEW`."
    )
    trigger: TransitionTrigger | None = Field(
        default=None,
        description="그 국면으로 들어온 사유. 원장이 비었으면 None — "
        "`POLICY_*`면 정책 결정(규칙 id는 `rule_id`)이다.",
    )
    rule_id: str | None = Field(
        default=None, description="결정을 낸 정책 규칙 id(예 `R3-wrong-misconception`)."
    )
    attempt_id: uuid.UUID | None = Field(
        default=None, description="그 전이를 일으킨 응답 id. 생애주기 전이면 None."
    )
    concept_id: str | None = Field(
        default=None,
        description="전이에 기록된 개념 id. 응답 제출 경로는 현재 비워 두므로 대개 None이다 — "
        "추천은 이 값 대신 `attempt_id`에서 개념을 찾는다.",
    )
    changed_at: datetime | None = Field(default=None, description="그 전이의 시각(UTC).")
    assessed_from: LearningState | None = Field(
        default=None,
        description="최신 행이 **정책 결정**일 때, 그 결정을 낸 응답이 제출되던 시점의 국면 "
        "(같은 `attempt_id`의 `ATTEMPT_SUBMITTED` 행의 `from_state`). 짝 행을 찾지 못하면 None — "
        "모르는 것을 추측으로 채우지 않는다.",
    )


def _learning_state_snapshot(rows: list[LearningStateTransition]) -> LearningStateSnapshot:
    """원장 최신 행(최신순) → 스냅샷. 순수 — 조회는 호출부가 한다.

    `assessed_from`은 **같은 응답에서 나온 짝 행**일 때만 채운다(`attempt_id` 일치 + 트리거가
    `ATTEMPT_SUBMITTED`). 두 행이 다른 응답에서 왔는데 채우면, 앞 응답의 국면을 이번 결정의
    출발점으로 오독한다 — 그러면 교정 고정 해제(EOS-24 안전장치 ③)가 엉뚱한 회차에 걸린다.
    """
    if not rows:
        return LearningStateSnapshot(state=INITIAL_STATE)
    latest = rows[0]
    assessed_from: LearningState | None = None
    if latest.attempt_id is not None and len(rows) > 1:
        entry = rows[1]
        if (
            entry.trigger is TransitionTrigger.ATTEMPT_SUBMITTED
            and entry.attempt_id == latest.attempt_id
        ):
            assessed_from = entry.from_state
    return LearningStateSnapshot(
        state=latest.to_state,
        trigger=latest.trigger,
        rule_id=latest.rule_id,
        attempt_id=latest.attempt_id,
        concept_id=latest.concept_id,
        changed_at=latest.occurred_at,
        assessed_from=assessed_from,
    )


class LearnerState(BaseModel):
    """L2가 조립하는 학습자 요약 상태 v0 — 생산자 실재 필드만.

    `02_learner_model.md`의 원안 11필드 중 생산자가 있는 8개(mastery·general_ability·
    domain_abilities·active_misconceptions·recent_struggles·recent_successes·grade·goals)만
    담는다.

    **v1(EOS-10) 추가 3필드**: `curriculum_id`·`current_objective_id`·`skill_mastery`.
    이 중 생산자가 실재하는 것은 `skill_mastery` 하나뿐이고 나머지 둘은 **생산자 0건**이라
    항상 None이다. v0은 그런 필드를 아예 만들지 않는 원칙("항상 None인 필드는 '읽고 있다'는
    착시만 준다")을 세웠고 그 원칙은 옳다 — 그래서 v1은 필드를 열되 **`origins`가 그 부재를
    `NO_PRODUCER`로 말하게** 해 착시를 구조적으로 막는다. 필드가 있으나 유래가 "생산자 없음"인
    것과, 필드가 없는 것은 다르다: 전자는 계약이 고정돼 생산자가 붙는 날 호출부가 안 바뀐다.

    **v0 제외 필드(생산자 부재 — `runtime_selector.py:96-118` 결정의 이행)**:
    - `affect`: `AffectState` 분류기 자체가 없음(§D6 페이퍼 설계만).
    - `mastery_states: dict[str, MasteryState]`: `MasteryState` 자체가 코드에 미실체화(문서 스케치).
    - `active_textbook_id`: `user_profile`에 학생-교과서 FK 없음(`textbook_mapping`은 콘텐츠
      자산일 뿐, 학생 프로필과 연결되지 않는다).
    - `shadow_curriculum_progress`: 학원·인강 진도 컬럼 없음(`uses_inkang` 불리언만 존재).

    이 필드들이 필요해지면 생산자(추정기·컬럼)를 먼저 만들고 그때 이 클래스에 연다.
    """

    student_id: str = Field(description="학생 user_id 문자열.")
    timestamp: datetime = Field(description="조립 시각(UTC) — 호출 시점 스냅샷.")
    mastery: dict[str, float] = Field(
        description="개념코드 → BKT 최신 숙달 P(L). "
        "`compute_concept_diagnoses`의 `bkt_mastery` 소스(측정 없으면 키 자체가 없음)."
    )
    general_ability: float | None = Field(
        description="전과목 IRT 능력 θ — `get_current_theta(concept_id=None)`. "
        "측정 이력 없으면 None."
    )
    domain_abilities: dict[str, float] = Field(
        description="개념코드 → IRT 능력 θ. **이름과 실제 의미가 다름에 유의**: 원안의 "
        "`domain_abilities`는 '수와 연산' 같은 굵은 도메인 단위를 뜻했지만, 실제 생산자"
        "(`compute_concept_diagnoses`)는 *개념(concept) 단위* θ만 낸다. 필드명은 acceptance대로 "
        "`domain_abilities`를 유지하되, 키는 도메인명이 아니라 concept_code다 — v0 의도적 단순화, "
        "실제 도메인 집계는 후속."
    )
    active_misconceptions: list[str] = Field(
        description="활성(is_active=true) 오개념 가설 id 목록(confidence 내림차순)."
    )
    recent_struggles: list[str] = Field(
        description="BKT 숙달 < 발전중 임계(`_DEVELOPING_THRESHOLD`)인 개념코드 목록. **주의**: "
        "이건 '최근 사건'이 아니라 '현재 낮은 숙달 개념'의 v0 근사다 — `ConceptMasteryHistory`의 "
        "시간축 기반 진짜 recency는 후속, v0은 현재 숙달도 임계 근사."
    )
    recent_successes: list[str] = Field(
        description="BKT 숙달 >= 숙달 임계(`_MASTERED_THRESHOLD`)인 개념코드 목록. "
        "`recent_struggles`와 동일한 v0 근사(현재 숙달도 임계, 시간축 recency 아님)."
    )
    grade: int | None = Field(description="`user_profile.grade` — 학년(정수). 미입력이면 None.")
    goals: dict[str, str] = Field(
        description="`user_profile`의 target_grade·target_score·target_exam_date·"
        "target_universities를 문자열화한 목표 사전. 값 없는 필드는 키 생략, 전부 없으면 빈 dict. "
        "**PII 주의**: 이 필드는 이번 슬라이스(PED-05)에서 프롬프트에 착지되지 않는다 — 목표 "
        "점수/등급/대학을 학생 대면 프롬프트에 노출하는 것은 CLAUDE.md PII 가드 위반이다."
    )

    # ===== v1(EOS-10) 추가 3필드 — 계획서 300 §12 LearnerState 결손분 =====
    curriculum_id: str | None = Field(
        default=None,
        description="학생이 따르는 교육과정 버전 id. **현재 항상 None — 생산자 0건**: "
        "`user_profile` 컬럼 전수에 교육과정 배정 컬럼이 없고(2026-09-16 실측), "
        "`curriculum_version`은 콘텐츠 자산이며 `CurriculumDepthResolver`는 학생이 아니라 "
        "*국가*(KR 고정) 축으로 해석한다. 학생→교육과정 배정 경로 자체가 없다. "
        "`origins['curriculum_id'].status`가 `no_producer`로 이 사실을 말한다.",
    )
    current_objective_id: str | None = Field(
        default=None,
        description="지금 학생이 향하는 학습목표(`learning_objective.id`). **현재 항상 None — "
        "생산자 0건**: `learning_objective`는 콘텐츠로 실재하지만 *이 학생의 현재 목표*를 "
        "정하는 서버측 결정자가 없다. `api/study.py`는 목표를 **클라이언트가 경로 인자로 "
        "넘겨준다**(`_load_objective(session, objective_id)`) — 즉 현재 이 결정은 서버 밖에 "
        "있다. 추천 좌석들(`weak_concept_recommendation`·`learning_path`)은 *개념*을 내지 "
        "목표를 내지 않는다. `origins['current_objective_id']`가 이 사실을 말한다.",
    )
    skill_mastery: dict[str, float] = Field(
        default_factory=dict,
        description="`skill_id`(`skill.<slug>`) → 스킬별 최신 BKT 숙달(행동 축). 개념 축 "
        "`mastery`의 짝이며 **재계산이 아니라 조립**이다 — 값은 소유 모듈 "
        "`l2/skill_mastery_tracking.py`의 `get_all_current_skill_mastery`가 낸다. 측정 없는 "
        "스킬은 키 자체가 없다(`mastery`와 같은 규약).",
    )

    # ===== EOS-24 — 학습 상태 머신의 국면 =====
    learning_state: LearningStateSnapshot | None = Field(
        default=None,
        description="학습 상태 머신의 현재 국면과 그것을 만든 최신 결정(`LearningStateSnapshot`). "
        "`get_state()`는 **항상 채운다**(원장이 비었으면 `state=NEW`·`origins`가 `no_data`). "
        "None은 조립기를 거치지 않고 손으로 만든 상태(테스트 등)뿐이며, 추천은 None을 '상태 머신이 "
        "아무 결정도 하지 않았다'로 읽는다.",
    )

    # ===== 유래 축 — 어느 필드가 실제로 작동했는가 =====
    origins: dict[str, FieldOrigin] = Field(
        default_factory=dict,
        description="필드명 → 그 값의 유래(`FieldOrigin`). 데이터 필드 12개 전건에 대해 채워진다 "
        "— 값이 없는 필드도 *왜* 없는지(`no_data` = 이 학생의 이력 부재 / `no_producer` = "
        "저장소에 생산자 부재)를 말하므로, 소비처는 `status == 'measured'`의 비율로 **이 조립이 "
        "실제로 작동한 비율**을 셀 수 있다. 추정기 교체(BKT→DKT)는 이 dict의 `estimator` 값만 "
        "바꾸고 스키마 모양은 바꾸지 않는다.",
    )


async def _get_active_misconception_ids(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """학생의 활성 오개념 가설 id만 confidence 내림차순으로 조회 — L4 import 없이 직접 SELECT.

    `l4/misconception/hypothesis_store.py::get_active_hypotheses`와 같은 모양의 WHERE/정렬이지만,
    L2→L4 역방향 의존을 피하려 전체 ORM 레코드→Pydantic 변환 없이 `misconception_id` 컬럼만 뽑는다
    (이 조립기는 id 리스트 `list[str]`만 필요하므로 그 이상은 과공학).
    """
    stmt = (
        select(MisconceptionHypothesisRecord.misconception_id)
        .where(
            MisconceptionHypothesisRecord.user_id == user_id,
            MisconceptionHypothesisRecord.is_active.is_(True),
        )
        .order_by(
            MisconceptionHypothesisRecord.confidence.desc(),
            MisconceptionHypothesisRecord.misconception_id,
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _build_goals(profile: UserProfile) -> dict[str, str]:
    """`user_profile`의 4개 target_* 필드를 문자열화 — None인 필드는 키 생략.

    `target_universities`(JSONB 리스트)는 `repr`이 아니라 `str()`로 문자열화한다(v0은 사람이 읽는
    사전 값이면 충분 — 구조화 파싱이 필요해지면 후속에서 JSON 문자열로 교체).
    """
    goals: dict[str, str] = {}
    if profile.target_grade is not None:
        goals["target_grade"] = str(profile.target_grade)
    if profile.target_score is not None:
        goals["target_score"] = str(profile.target_score)
    if profile.target_exam_date is not None:
        goals["target_exam_date"] = profile.target_exam_date.isoformat()
    if profile.target_universities:
        goals["target_universities"] = str(profile.target_universities)
    return goals


async def get_state(session: AsyncSession, user_id: uuid.UUID) -> LearnerState:
    """L2 학습자 요약 상태 v0 조립 — 기존 좌석 재사용만(신규 계산 0).

    `compute_concept_diagnoses` 단 1회 호출로 `mastery`·`domain_abilities`·`recent_struggles`·
    `recent_successes` 4필드를 함께 도출한다(중복 쿼리 금지). `general_ability`는
    `get_current_theta(concept_id=None)`(전과목), `active_misconceptions`는 자체 SELECT(위
    `_get_active_misconception_ids`), `grade`·`goals`는 `user_profile` 단건 조회.

    진단·오개념·프로필이 전부 없는 신규 학생도 예외 없이 반환한다 — 각 컬렉션은 빈 dict/list,
    `general_ability`·`grade`는 None, `goals`는 빈 dict. 값의 부재가 무엇을 뜻하는지는
    `origins`가 필드별로 말한다(빈 값 자체는 센티널이 아니다).

    **좌석 판정 (EOS-10 acceptance ③ — 정본화 ≠ 집행)**
    ----------------------------------------------------
    정본이 학습 상태에 배정한 영속 좌석 `user_state_snapshot`(`db/models/user.py`)을 이 조립기는
    **읽지도 쓰지도 않는다.** 판정과 근거:

    - **실측**: 그 테이블의 writer는 **0건**이다(2026-09-16 · `UserStateSnapshot` 전거 검색 →
      schema 정의 · `db/models/__init__` 등록 · `privacy/export.py`·`privacy/erasure.py`의
      읽기·삭제뿐). 비어 있는 테이블을 읽으면 이 조립기는 항상 빈 상태를 돌려준다.
    - **축이 다르다**: 그 좌석이 담는 것은 `estimated_grade`·`estimated_score`·
      `estimated_percentile`·`pattern_mastery`·`time_management_score`·
      `consecutive_active_days` 등 **예측·시간관리·멘탈 신호**이고, `LearnerState`가 담는 것은
      BKT/IRT 숙달·능력이다. 겹치는 것은 `concept_mastery` 한 축뿐인데 그마저 이쪽은
      `ConceptMasteryHistory`(append-only 시계열)가 정본이다 — 스냅샷을 읽으면 같은 사실의
      **두 번째 진실 원천**이 생긴다(붕괴 연쇄 "유지보수 지옥").
    - **그러므로 조립 즉시 계산이다.** 이 표면은 호출 시점에 기존 좌석들을 조회해 조립하며
      스냅샷을 경유하지 않는다. 캐시가 필요해지면 그때 `user_state_snapshot`이 아니라 이
      조립 결과의 캐시 좌석을 따로 판정한다(축이 다른 테이블을 캐시로 전용하지 않는다).
    - **좌석 자신의 처분은 이 태스크가 하지 않는다.** `privacy/export.py`·`erasure.py`가 그
      테이블을 읽으므로 폐기는 개인정보 표면을 건드리는 별건이다(범위 규율). "배선 또는 폐기"
      판정은 후속 태스크가 소유한다 — 본 태스크는 **"이 표면은 그 좌석을 쓰지 않는다"**를
      확정하는 데까지다.
    """
    diagnoses = await compute_concept_diagnoses(session, user_id)

    mastery: dict[str, float] = {
        d.concept_code: d.bkt_mastery
        for d in diagnoses
        if d.concept_code and d.bkt_mastery is not None
    }
    domain_abilities: dict[str, float] = {
        d.concept_code: d.irt_theta for d in diagnoses if d.concept_code and d.irt_theta is not None
    }
    recent_struggles = [
        d.concept_code
        for d in diagnoses
        if d.concept_code and d.bkt_mastery is not None and d.bkt_mastery < _DEVELOPING_THRESHOLD
    ]
    recent_successes = [
        d.concept_code
        for d in diagnoses
        if d.concept_code and d.bkt_mastery is not None and d.bkt_mastery >= _MASTERED_THRESHOLD
    ]

    general_ability = await get_current_theta(session, user_id)
    active_misconceptions = await _get_active_misconception_ids(session, user_id)

    # 스킬 축은 **조립**이다 — "최신 1건" 규칙은 소유 모듈이 갖고 여기서 다시 쓰지 않는다.
    skill_mastery = await get_all_current_skill_mastery(session, user_id)

    # EOS-24 — 상태 머신 국면. 조회는 **마지막 execute**로 둔다: 순서 기반 테스트 대역이 앞의
    # 다섯 조회를 그대로 소비하고, 늘어난 1건이 끝에 붙는 형태가 가장 덜 흔든다.
    transitions = await list_transitions(session, user_id, limit=_LEARNING_STATE_ROWS)
    learning_state = _learning_state_snapshot(transitions)

    profile = await session.get(UserProfile, user_id)
    grade = profile.grade if profile is not None else None
    goals = _build_goals(profile) if profile is not None else {}

    # 데이터 필드 12개 전건의 유래(EOS-24 `learning_state` 포함). 생산자가 없는 둘만 리터럴
    # `NO_PRODUCER`이고(그 줄을 지우는 것이 생산자가 붙는 날 변경의 전부다), 나머지는 값 유무로
    # MEASURED/NO_DATA가 갈린다.
    origins: dict[str, FieldOrigin] = {
        "mastery": _origin(bool(mastery), estimator=_EST_BKT, seat=_SEAT_DIAGNOSIS),
        "general_ability": _origin(
            general_ability is not None, estimator=_EST_IRT, seat=_SEAT_ABILITY
        ),
        "domain_abilities": _origin(
            bool(domain_abilities), estimator=_EST_IRT, seat=_SEAT_DIAGNOSIS
        ),
        "skill_mastery": _origin(bool(skill_mastery), estimator=_EST_BKT, seat=_SEAT_SKILL),
        "active_misconceptions": _origin(bool(active_misconceptions), seat=_SEAT_MISCONCEPTION),
        "recent_struggles": _origin(
            bool(recent_struggles), estimator=_EST_BKT, seat=_SEAT_DIAGNOSIS
        ),
        "recent_successes": _origin(
            bool(recent_successes), estimator=_EST_BKT, seat=_SEAT_DIAGNOSIS
        ),
        "grade": _origin(grade is not None, seat=_SEAT_PROFILE),
        "learning_state": _origin(bool(transitions), seat=_SEAT_LEARNING_STATE),
        "goals": _origin(bool(goals), seat=_SEAT_PROFILE),
        # ── 생산자 0건(2026-09-16 실측) — 근거는 각 필드 description 참조 ──
        "curriculum_id": FieldOrigin(status=FieldStatus.NO_PRODUCER),
        "current_objective_id": FieldOrigin(status=FieldStatus.NO_PRODUCER),
    }

    return LearnerState(
        student_id=str(user_id),
        timestamp=datetime.now(timezone.utc),
        mastery=mastery,
        general_ability=general_ability,
        domain_abilities=domain_abilities,
        active_misconceptions=active_misconceptions,
        recent_struggles=recent_struggles,
        recent_successes=recent_successes,
        grade=grade,
        goals=goals,
        curriculum_id=None,
        current_objective_id=None,
        skill_mastery=skill_mastery,
        learning_state=learning_state,
        origins=origins,
    )
