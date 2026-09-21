"""현재 사용자 본인 학습 데이터 — `/v1/me/{sessions,assessments,dialogues}`.

`ConsentedUser`(인증 + 미성년 동의 게이트) 후 **`WHERE user_id == current_user.user_id`로만**
조회한다 — 본인 데이터 스코핑(타인 데이터 차단, CLAUDE.md 미성년 PII·식별 분석 외부 노출 금지).
읽기 전용·최신순(started_at desc, PK로 안정 정렬)·limit/offset. 쓰기·자식(turn 등) 상세·관리자
(타인) 조회는 범위 밖.

slice 50: `PATCH /v1/me/sessions/{id}/end` — 본인 학습 세션 종료(ended_at 채움). idempotent
(이미 종료된 세션은 ended_at 보존하고 200). 미존재·타인 소유 모두 404(정보 비누설·slice 24 패턴).

slice 51: `DELETE /v1/me/sessions/{id}` — GDPR 본인 학습 세션 영구 삭제. 204 No Content.
미존재·타인 소유 모두 404(슬라이스 50과 동일 비누설). 자식 cascade는 slice 56 참조.

slice 52: `PATCH /v1/me/dialogues/{id}/end` + `DELETE /v1/me/dialogues/{id}` — Dialogue
도메인에 슬라이스 50/51 패턴 답습. 본인 소유 검증·404 비누설·idempotent end·204 delete 동형.

slice 53: `PATCH /v1/me/assessments/{id}/complete` + `DELETE /v1/me/assessments/{id}` —
Assessment 도메인 lifecycle. *명칭은 `/complete`*(진단은 "종료"가 아니라 "완료"라 모델 컬럼
`completed_at`을 따라간다 — slice 50/52의 `ended_at`과 의미 분리). idempotent complete·
204 delete·404 비누설은 50/51/52와 동일 패턴. 세 도메인(LearningSession·Dialogue·Assessment)
lifecycle 완비 — 이식 비용 minimization 4회차 검증.

slice 55: 슬라이스 50~53의 end/complete·delete 6 라우터가 *동형 반복*(fetch→소유검증→404→
commit)하던 중복을 제네릭 헬퍼 `_close_owned_resource`·`_delete_owned_resource`(공통
`_get_owned_or_404`)로 추출 — 라우터는 헬퍼 1줄 호출로 축소. 동작·응답 불변(순수 리팩터).
mypy strict 정합은 *제약 TypeVar*로 해소(아래 헬퍼 주석 참조).

slice 56: GDPR 삭제 cascade 정책 — DB FK `ON DELETE CASCADE`로 직속 자식 자동 제거
(learning_session→problem_attempt·dialogue→dialogue_turn), attempt를 참조하던
dialogue.attempt_id는 `SET NULL`(대화 보존). 슬라이스 51/52의 RESTRICT FK 한계 해소
(라우터 코드 무변경 — DB 레벨 정책·alembic c3d4e5f6a7b8). attempt_event(loose ref)는 고아 잔존.

slice 57: GDPR 삭제 감사 — delete 3종이 `_delete_owned_resource`에서 삭제와 *동일 트랜잭션*으로
`DeletionAudit`(누가·무엇·언제, 콘텐츠 미저장) 1행 적재. 부모만 기록(자식 cascade는 DB 비가시).
user_id는 FK 아님(사용자 삭제돼도 잔존). alembic d4e5f6a7b8c9.

slice 58: `GET /v1/me/deletions` — slice 57이 적재한 본인 삭제 감사 이력 조회(GDPR 투명성).
다른 /me GET과 동일: ConsentedUser·user_id 스코핑·최신순(deleted_at desc)·페이지네이션.
스키마 변경 0(읽기 전용·마이그레이션 없음).
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal, TypeVar

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api._auth import ConsentedUser, CurrentUser, RequireContentAdmin
from whymath_backend.api._crypto import (
    encrypt_dialogue_content,
    require_student_work_cipher,
)
from whymath_backend.api._growth_evidence_state import (
    get_growth_evidence_counters,
    get_growth_evidence_exposure_counters,
)
from whymath_backend.api._next_problem_policy import SuneungRecommendationPolicy
from whymath_backend.api._query_filters import (
    _validate_time_window,
    _validate_tz_aware,
    time_window_conditions,
)
from whymath_backend.api._rate_limit import _client_ip
from whymath_backend.api._subject_capability_state import get_attempt_misconception_detector

# ASM-04: 청사진 조립 후보 조회는 게이팅 라우터(같은 L5 레이어)의 헬퍼를 *재사용*한다 —
# 후보 조회(절단 경고 포함)와 성취기준 원자 축 조인을 두 번 구현하지 않는다(단일 진실 원천).
# private 이름 import는 `l2.ability_estimation._DIFFICULTY_MIDPOINT` 선례와 동형(같은 패키지
# 내부 계약). 순환 없음 — `api/gating.py`는 `api/me.py`를 import하지 않는다.
from whymath_backend.api.gating import (
    _fetch_achievement_codes as _fetch_gating_achievement_codes,
)
from whymath_backend.api.gating import (
    _fetch_candidates as _fetch_gating_candidates,
)
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.activity import LearningSession, ProblemAttempt
from whymath_backend.db.models.assessment import (
    AbilitySnapshot,
    Assessment,
    ConceptMasteryHistory,
    SkillMasteryHistory,
)
from whymath_backend.db.models.audit import DeletionAudit, PrivacyAudit
from whymath_backend.db.models.concept import Concept
from whymath_backend.db.models.dialogue import Dialogue
from whymath_backend.db.models.problem import Problem

# COLLAB-03: 학습시간 통계 좌석의 공급원(l2.learning_metrics_rollup이 적재).
from whymath_backend.db.models.timeseries import DailyLearningMetrics
from whymath_backend.db.session import get_session
from whymath_backend.harness.growth_evidence_exposure import (
    ExposureTier,
    MetricExposure,
    classify_metric_exposure,
    narrate_calibration_brier,
)
from whymath_backend.harness.wh1_evaluation import (
    MetricStatus,
    SurrogateMetrics,
    compute_wh1_surrogate_metrics,
)
from whymath_backend.l2.ability_estimation import (
    ConceptAbilityItem,
    compute_concept_abilities,
    estimate_global_ability,
    resolve_item_difficulty_b,
)
from whymath_backend.l2.assessment_evidence import collect_assessment_evidence
from whymath_backend.l2.attempt_skill_event import AttemptSource, record_attempt_skill_event
from whymath_backend.l2.concept_diagnosis import Agreement, compute_concept_diagnoses
from whymath_backend.l2.irt import (
    IrtItem,
    ability_standard_error,
    estimate_ability,
)
from whymath_backend.l2.learner_state import LearnerState, get_state
from whymath_backend.l2.learner_state_store import provision_learner_state
from whymath_backend.l2.learning_event_trace import (
    DEFAULT_TRACE_LIMIT,
    MAX_TRACE_LIMIT,
    LearningEventTrace,
    build_trace,
)
from whymath_backend.l2.learning_path import (
    LearningPath,
    build_learning_path,
)
from whymath_backend.l2.learning_state_evidence import build_attempt_evidence
from whymath_backend.l2.learning_state_machine import (
    advance_on_attempt,
    get_current_state,
    list_transitions,
    record_transition,
)
from whymath_backend.l2.mastery_tracking import record_problem_attempt_mastery

# 이 블록의 일부 이름은 이 파일 안에서 쓰이지 않고 **재노출**만 된다(아래 별칭 블록 주석).
from whymath_backend.l2.next_problem_selection import (  # noqa: F401
    CANDIDATE_POOL_SIZE,
    CANDIDATE_ZERO_ALL_GATED_INELIGIBLE,
    CANDIDATE_ZERO_NO_POOL,
    TARGET_SE,
    AttemptHistoryState,
    _weak_concept_weights,
    candidate_pool_conditions,
    candidate_pool_order_by,
    combine_weights,
    last_incorrect_problem_id,
    load_attempt_history_state,
    load_sibling_ids,
    load_weak_concept_weights,
    sibling_weights,
)
from whymath_backend.l2.prerequisite_recommendation import (
    MAX_PREREQUISITE_DEPTH,
    PrerequisiteGap,
    recommend_prerequisite_gaps,
)
from whymath_backend.l2.recommendation_contract import (
    LearningContext,
    RecommendationAction,
    RecommendationReason,
)
from whymath_backend.l2.recommendation_evidence import (
    record_recommendation_treatment,
)
from whymath_backend.l2.recommendation_policy import CatRecommendationPolicy, NextProblemPolicy
from whymath_backend.l2.review_queue import ReviewQueue, fetch_review_queue
from whymath_backend.l2.skill_mastery_tracking import (
    record_problem_attempt_skill_mastery,
)
from whymath_backend.l2.strong_concept_recommendation import recommend_strong_concepts
from whymath_backend.l2.target_progress import TargetProgress, get_target_progress
from whymath_backend.l2.weak_concept_recommendation import (
    WeakConceptRecommendation,
    recommend_weak_concepts,
)
from whymath_backend.l4.calibration_coaching import recommend_calibration_coaching
from whymath_backend.l4.lthc.adapt import mastery_to_level
from whymath_backend.l4.lthc.models import MasteryLevel
from whymath_backend.l4.metacognitive_trigger import CoachingTrigger, recommend_coaching
from whymath_backend.l4.misconception.hypothesis_store import (
    apply_candidates,
    get_active_hypotheses,
)
from whymath_backend.l4.prerequisite_coaching import recommend_prerequisite_coaching
from whymath_backend.l6.blueprint import (
    AssembledTestSet,
    ExamBlueprint,
    assemble_test_set,
)
from whymath_backend.privacy import (
    UserDataExport,
    erase_user,
    export_user_data,
    external_export_pending,
    record_export_audit,
)
from whymath_backend.schema.activity import LearningSession as LearningSessionSchema
from whymath_backend.schema.assessment import AbilitySnapshot as AbilitySnapshotSchema
from whymath_backend.schema.assessment import Assessment as AssessmentSchema
from whymath_backend.schema.assessment import (
    ConceptMasteryHistory as ConceptMasteryHistorySchema,
)
from whymath_backend.schema.assessment import (
    SkillMasteryHistory as SkillMasteryHistorySchema,
)
from whymath_backend.schema.assessment import StudentAssessment as StudentAssessmentSchema
from whymath_backend.schema.assessment_evidence import (
    AssessmentEvidence,
    MisconceptionCandidate,
    MisconceptionScan,
)
from whymath_backend.schema.audit import DeletionAudit as DeletionAuditSchema
from whymath_backend.schema.audit import PrivacyAudit as PrivacyAuditSchema
from whymath_backend.schema.dialogue import Dialogue as DialogueSchema
from whymath_backend.schema.enums import (
    AssessmentType,
    AuditEventKind,
    AuditResourceType,
    Persona,
    Resolution,
)
from whymath_backend.schema.learning_state import (
    LearningState,
    NextActionKind,
    TransitionTrigger,
    UndefinedTransitionError,
    allowed_targets,
)
from whymath_backend.schema.problem import Problem as ProblemSchema
from whymath_backend.schema.timeseries import (
    DailyLearningMetrics as DailyLearningMetricsSchema,
)
from whymath_backend.schema.verification_capabilities import AttemptMisconceptionDetector

router = APIRouter(prefix="/v1/me", tags=["me"])

_logger = logging.getLogger("whymath.api.me")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
Limit = Annotated[int, Query(ge=1, le=200, description="페이지 크기")]
Offset = Annotated[int, Query(ge=0, description="건너뛸 행 수")]
# slice 65: deletions 조회의 선택적 도메인 필터 — None이면 전체(slice 58 동작 보존).
# slice 68: 다중 값 OR 필터 — `?resource_type=dialogue&resource_type=assessment`로 여러
# 도메인 동시 조회(IN). 단일 값도 그대로 수용(하위 호환). enum이라 부정 값은 FastAPI가 422.
ResourceTypeFilter = Annotated[
    list[AuditResourceType] | None,
    Query(
        description=(
            "삭제 도메인 필터(learning_session·dialogue·assessment). 반복 지정 시 OR(IN). "
            "생략 시 전체."
        )
    ),
]
# SEC-09: privacy-audit 조회의 선택적 이벤트 종류 필터 — resource_type 필터(slice 65/68)와 동형.
EventKindFilter = Annotated[
    list[AuditEventKind] | None,
    Query(
        description=(
            "개인정보·콘텐츠 감사 이벤트 종류 필터(export_data·consent_change·admin_access·"
            "role_change·content_mutation). 반복 지정 시 OR(IN). 생략 시 전체."
        )
    ),
]
# slice 66/67: /me 리스트 공용 시간창 필터(inclusive·TZ-aware ISO8601). deletions는
# deleted_at, sessions·assessments·dialogues는 started_at 기준. device 목록(slice 41)과
# 동형. naive datetime·since>until은 _query_filters.time_window_conditions가 422.
SinceParam = Annotated[
    datetime | None,
    Query(description="이 시각 *이후* 항목만(inclusive·TZ-aware ISO8601). until과 함께 시간창."),
]
UntilParam = Annotated[
    datetime | None,
    Query(description="이 시각 *이전* 항목만(inclusive·TZ-aware ISO8601). since와 함께 시간창."),
]
# slice 69: lifecycle 종료 시각 시간창 — sessions·dialogues는 ended_at, assessments는
# completed_at 기준(파라미터명으로 구분). started_at(SinceParam)과 *독립* 시간창이라 둘 다
# 지정 시 AND(예: 1월 시작 & 3월 종료). 미종료(NULL) 행은 SQL NULL 비교로 자동 제외.
CloseSince = Annotated[
    datetime | None,
    Query(description="이 시각 *이후* 종료/완료분만(inclusive·TZ-aware ISO8601)."),
]
CloseUntil = Annotated[
    datetime | None,
    Query(description="이 시각 *이전* 종료/완료분만(inclusive·TZ-aware ISO8601)."),
]
# slice 70: 정렬 방향 — desc(최신순·기본·slice 58 동작 보존)·asc(오래된순). device 목록
# (slice 46)과 동형. 1차 정렬 컬럼(started_at/deleted_at)에 적용·PK 2차키는 안정 정렬용 유지.
OrderDir = Literal["asc", "desc"]
OrderParam = Annotated[OrderDir, Query(description="정렬 방향 — desc(최신순·기본)·asc(오래된순).")]
# slice 71: 총 개수 opt-in — true면 *같은 필터*(limit/offset 제외) 적용 후 총 건수를
# `X-Total-Count` 응답 헤더로 노출(페이지네이션 "총 N건"·"Page X of Y"). 기본 false라 추가
# COUNT 쿼리 비용 회피. device 목록(slice 39)은 응답 envelope의 total 필드를 쓰지만 /me는
# bare array 응답이라 *비파괴적* 헤더 방식 채택(REST 관용·기존 클라이언트 무영향).
IncludeTotal = Annotated[
    bool,
    Query(description="true면 `X-Total-Count` 헤더에 필터 적용 총 건수(limit/offset 무시)."),
]
_TOTAL_HEADER = "X-Total-Count"
# slice L2-5: 학습곡선 조회의 개념 필터 — 특정 개념 1개의 측정 시계열(학습 곡선)만.
ConceptIdFilter = Annotated[
    uuid.UUID | None,
    Query(description="특정 개념의 학습 곡선만(선택). 생략 시 전 개념 측정 인터리브."),
]
# slice L2-5c: 현재 숙달 스냅샷 정렬 기준 — concept_id(기본) 또는 mastery(약점/강점 우선).
SnapshotOrderBy = Literal["concept_id", "mastery"]
SnapshotOrderByParam = Annotated[
    SnapshotOrderBy,
    Query(description="스냅샷 정렬 기준 — concept_id(기본) 또는 mastery(order=asc면 약점 우선)."),
]


async def _maybe_set_total(
    session: AsyncSession,
    response: Response,
    include_total: bool,
    count_stmt: Any,
) -> None:
    """slice 71: include_total이면 count_stmt(같은 필터·limit/offset 없음) 실행 후 헤더 설정."""
    if include_total:
        total = (await session.execute(count_stmt)).scalar() or 0
        response.headers[_TOTAL_HEADER] = str(total)


# ── slice 55: 본인 소유 리소스 lifecycle 제네릭 헬퍼 ──────────────────────────
# 슬라이스 50~53이 LearningSession·Dialogue·Assessment 세 도메인에 end/complete·delete를
# *동형 반복*(fetch→소유검증→404→commit)했다(4회차 답습). 그 중복을 헬퍼로 압축한다.
# **mypy strict 정합**(slice 53이 짚은 dispatch 위험 해소): 제약(constrained) TypeVar로
# 세 ORM만 허용 → `row.user_id`(셋 다 보유)·반환 `row.to_schema()`(호출자에서 구체 타입
# 추론)가 타입 안전. close 컬럼은 도메인마다 달라(ended_at vs completed_at) 필드명을 인자로
# 받아 get/setattr로 동적 접근(인자 변수라 ruff B009/B010 미해당).
_LifecycleRow = TypeVar("_LifecycleRow", LearningSession, Dialogue, Assessment)


async def _get_owned_or_404(
    session: AsyncSession,
    model: type[_LifecycleRow],
    pk: uuid.UUID,
    owner_id: uuid.UUID,
    not_found_detail: str,
) -> _LifecycleRow:
    """PK 조회 후 본인 소유 검증 — 미존재·타인 소유 모두 404(정보 비누설·slice 24 패턴)."""
    row = await session.get(model, pk)
    if row is None or row.user_id != owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail)
    return row


async def _close_owned_resource(
    session: AsyncSession,
    model: type[_LifecycleRow],
    pk: uuid.UUID,
    owner_id: uuid.UUID,
    close_field: str,
    not_found_detail: str,
    *,
    commit: bool = True,
) -> tuple[_LifecycleRow, bool]:
    """본인 소유 리소스 lifecycle 종료 — `close_field`(ended_at/completed_at)를 now로.

    *idempotent*: 이미 채워졌으면 보존하고 commit 안 함(현 상태 반환). slice 50/52/53 동형.
    `(row, newly_closed)` 반환 — `newly_closed`는 *이번 호출에서 처음 종료*했는지(slice 34
    세션 종료 자동 트리거가 멱등 재호출 시 중복 동작을 피하도록).

    slice 35: `commit=False`면 종료 컬럼만 세팅하고 *커밋은 호출자*에 맡긴다 — 같은
    트랜잭션에 후속 쓰기(세션 종료 + θ 스냅샷)를 묶어 원자성 보장(부분 적용 방지).
    """
    row = await _get_owned_or_404(session, model, pk, owner_id, not_found_detail)
    newly_closed = getattr(row, close_field) is None
    if newly_closed:
        setattr(row, close_field, datetime.now(UTC))
        if commit:
            await session.commit()
    return row, newly_closed


async def _delete_owned_resource(
    session: AsyncSession,
    model: type[_LifecycleRow],
    pk: uuid.UUID,
    owner_id: uuid.UUID,
    resource_type: AuditResourceType,
    not_found_detail: str,
) -> None:
    """본인 소유 리소스 영구 삭제(GDPR) — 204. slice 51/52/53 동형. slice 56: 직속 자식은
    ON DELETE CASCADE로 자동 제거(session→attempt·dialogue→turn)·dialogue.attempt_id는
    SET NULL. attempt_event(loose ref·FK 아님)는 고아 잔존(설계 한계).

    slice 57: 삭제와 *동일 트랜잭션*으로 DeletionAudit 1행 적재(GDPR 삭제 증빙·부모만 기록·
    콘텐츠 미저장). user_id=소유자·resource_type/resource_id=대상. 같은 commit이라 삭제↔감사
    원자적(부분 실패 없음).
    """
    row = await _get_owned_or_404(session, model, pk, owner_id, not_found_detail)
    await session.delete(row)
    session.add(
        DeletionAudit(
            user_id=owner_id,
            resource_type=resource_type.value,
            resource_id=pk,
        )
    )
    await session.commit()


@router.get("/sessions", response_model=list[LearningSessionSchema], summary="내 학습 세션")
async def list_my_sessions(
    user: ConsentedUser,
    session: SessionDep,
    response: Response,
    limit: Limit = 50,
    offset: Offset = 0,
    since: SinceParam = None,
    until: UntilParam = None,
    ended_since: CloseSince = None,
    ended_until: CloseUntil = None,
    order: OrderParam = "desc",
    include_total: IncludeTotal = False,
) -> list[LearningSessionSchema]:
    """본인 학습 세션 — 기본 최신순. 타인 데이터는 조회 불가(user_id 스코핑).

    slice 67: `since`/`until`(선택)로 `started_at` 시간창 필터(inclusive·TZ-aware ISO8601).
    slice 69: `ended_since`/`ended_until`(선택)로 `ended_at` 시간창 — 미종료(NULL)는 제외.
    slice 70: `order`(asc/desc)로 `started_at` 정렬 방향(기본 desc·최신순).
    slice 71: `include_total=true`면 `X-Total-Count` 헤더에 필터 적용 총 건수.
    """
    conds = [
        LearningSession.user_id == user.user_id,
        *time_window_conditions(LearningSession.started_at, since, until),
        *time_window_conditions(
            LearningSession.ended_at,
            ended_since,
            ended_until,
            since_name="ended_since",
            until_name="ended_until",
        ),
    ]
    primary = (
        LearningSession.started_at.asc() if order == "asc" else LearningSession.started_at.desc()
    )
    stmt = (
        select(LearningSession)
        .where(*conds)
        .order_by(primary, LearningSession.session_id)
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    rows = [row.to_schema() for row in result.scalars().all()]
    await _maybe_set_total(
        session,
        response,
        include_total,
        select(func.count()).select_from(LearningSession).where(*conds),
    )
    return rows


@router.get("/assessments", response_model=list[StudentAssessmentSchema], summary="내 진단 이력")
async def list_my_assessments(
    user: ConsentedUser,
    session: SessionDep,
    response: Response,
    limit: Limit = 50,
    offset: Offset = 0,
    since: SinceParam = None,
    until: UntilParam = None,
    completed_since: CloseSince = None,
    completed_until: CloseUntil = None,
    order: OrderParam = "desc",
    include_total: IncludeTotal = False,
) -> list[StudentAssessmentSchema]:
    """본인 진단(Assessment) 이력 — 기본 최신순. user_id 스코핑.

    ASM-07: 응답 모델은 `StudentAssessment`다 — 예측 5필드는 **스키마에 자리가 없다**
    (런타임 필터가 아니라 구조적 배제 · ASM-02 결정 (c)).

    slice 67: `since`/`until`(선택)로 `started_at` 시간창 필터(inclusive·TZ-aware ISO8601).
    slice 69: `completed_since`/`completed_until`(선택)로 `completed_at` 시간창 — 미완료는 제외.
    slice 70: `order`(asc/desc)로 `started_at` 정렬 방향(기본 desc·최신순).
    slice 71: `include_total=true`면 `X-Total-Count` 헤더에 필터 적용 총 건수.
    """
    conds = [
        Assessment.user_id == user.user_id,
        *time_window_conditions(Assessment.started_at, since, until),
        *time_window_conditions(
            Assessment.completed_at,
            completed_since,
            completed_until,
            since_name="completed_since",
            until_name="completed_until",
        ),
    ]
    primary = Assessment.started_at.asc() if order == "asc" else Assessment.started_at.desc()
    stmt = (
        select(Assessment)
        .where(*conds)
        .order_by(primary, Assessment.assessment_id)
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    rows = [
        StudentAssessmentSchema.from_assessment(row.to_schema()) for row in result.scalars().all()
    ]
    await _maybe_set_total(
        session,
        response,
        include_total,
        select(func.count()).select_from(Assessment).where(*conds),
    )
    return rows


@router.get("/dialogues", response_model=list[DialogueSchema], summary="내 대화 이력")
async def list_my_dialogues(
    user: ConsentedUser,
    session: SessionDep,
    response: Response,
    limit: Limit = 50,
    offset: Offset = 0,
    since: SinceParam = None,
    until: UntilParam = None,
    ended_since: CloseSince = None,
    ended_until: CloseUntil = None,
    order: OrderParam = "desc",
    include_total: IncludeTotal = False,
) -> list[DialogueSchema]:
    """본인 Socratic 대화 이력 — 기본 최신순. user_id 스코핑(턴 상세는 범위 밖).

    slice 67: `since`/`until`(선택)로 `started_at` 시간창 필터(inclusive·TZ-aware ISO8601).
    slice 69: `ended_since`/`ended_until`(선택)로 `ended_at` 시간창 — 미종료(NULL)는 제외.
    slice 70: `order`(asc/desc)로 `started_at` 정렬 방향(기본 desc·최신순).
    slice 71: `include_total=true`면 `X-Total-Count` 헤더에 필터 적용 총 건수.
    """
    conds = [
        Dialogue.user_id == user.user_id,
        *time_window_conditions(
            Dialogue.ended_at,
            ended_since,
            ended_until,
            since_name="ended_since",
            until_name="ended_until",
        ),
        *time_window_conditions(Dialogue.started_at, since, until),
    ]
    primary = Dialogue.started_at.asc() if order == "asc" else Dialogue.started_at.desc()
    stmt = (
        select(Dialogue)
        .where(*conds)
        .order_by(primary, Dialogue.dialogue_id)
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    rows = [row.to_schema() for row in result.scalars().all()]
    await _maybe_set_total(
        session,
        response,
        include_total,
        select(func.count()).select_from(Dialogue).where(*conds),
    )
    return rows


@router.get(
    "/deletions",
    response_model=list[DeletionAuditSchema],
    summary="내 삭제 이력(GDPR 감사)",
)
async def list_my_deletions(
    user: ConsentedUser,
    session: SessionDep,
    response: Response,
    limit: Limit = 50,
    offset: Offset = 0,
    resource_type: ResourceTypeFilter = None,
    since: SinceParam = None,
    until: UntilParam = None,
    order: OrderParam = "desc",
    include_total: IncludeTotal = False,
) -> list[DeletionAuditSchema]:
    """slice 58: 본인 삭제 감사 이력 — 기본 최신순(deleted_at desc·audit_id 안정 정렬).

    slice 57이 적재한 `deletion_audit`를 user_id 스코핑으로 조회(GDPR 투명성 — 학생이 자기
    삭제 이력 확인·타인 것 차단). 메타만 반환(콘텐츠 없음). 본인 user_id의 행이라 타인 삭제는
    노출되지 않음(다른 /me GET과 동일 스코핑).

    slice 65: `resource_type`(선택)로 도메인 필터 — 한 유형(예: 대화)의 삭제 이력만 조회.
    slice 68: `resource_type` 반복 지정 시 OR(IN) — 여러 도메인 동시 조회(단일 값 하위 호환).
    slice 66: `since`/`until`(선택)로 `deleted_at` 시간창 필터(inclusive) — 특정 기간 삭제분만.
    slice 70: `order`(asc/desc)로 `deleted_at` 정렬 방향(기본 desc·최신순).
    slice 71: `include_total=true`면 `X-Total-Count` 헤더에 필터 적용 총 건수.
    모두 생략 시 전체(slice 58 동작 보존). naive datetime·since>until은 422(_query_filters).
    기존 `idx_deletion_audit_user(user_id, deleted_at DESC)`가 user_id prefix + 정렬 + 시간 범위를
    그대로 충족(resource_type만 추가 필터).
    """
    conds = [
        DeletionAudit.user_id == user.user_id,
        *time_window_conditions(DeletionAudit.deleted_at, since, until),
    ]
    if resource_type:
        conds.append(DeletionAudit.resource_type.in_([rt.value for rt in resource_type]))
    primary = DeletionAudit.deleted_at.asc() if order == "asc" else DeletionAudit.deleted_at.desc()
    stmt = (
        select(DeletionAudit)
        .where(*conds)
        .order_by(primary, DeletionAudit.audit_id)
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    rows = [row.to_schema() for row in result.scalars().all()]
    await _maybe_set_total(
        session,
        response,
        include_total,
        select(func.count()).select_from(DeletionAudit).where(*conds),
    )
    return rows


@router.get(
    "/privacy-audit",
    response_model=list[PrivacyAuditSchema],
    summary="내 개인정보 감사 이력",
)
async def list_my_privacy_audit(
    user: ConsentedUser,
    session: SessionDep,
    response: Response,
    limit: Limit = 50,
    offset: Offset = 0,
    event_kind: EventKindFilter = None,
    since: SinceParam = None,
    until: UntilParam = None,
    order: OrderParam = "desc",
    include_total: IncludeTotal = False,
) -> list[PrivacyAuditSchema]:
    """SEC-09: 본인 개인정보 감사 이력 — 기본 최신순(occurred_at desc·audit_id 안정 정렬).

    `privacy.audit`의 writer들이 적재한 `privacy_audit`를 `user_id`(행위자) 스코핑으로
    조회한다(`GET /v1/me/deletions`와 동형 패턴 — `list_my_deletions` 참조). 삭제 이벤트는
    여기 없다(`deletion_audit`가 단일 권위 — 이중 진실원천 금지).

    **이 docstring은 감사 종류를 다시 열거하지 않는다** — 종류의 단일 진실원천은
    `AuditEventKind`(`schema/enums.py`)이고, 값 목록이 사람에게 노출되는 자리는 `event_kind`
    파라미터 description 한 곳뿐이다(그 한 곳은 `tests/backend/api/
    test_privacy_audit_kind_doc_sync.py`가 enum과 동기됨을 기계로 동결한다). 산문이 값을
    복창하면 멤버가 늘 때마다 어긋나고, 어긋나도 기계가 못 본다 — ADMIN-01 회수(#786)에서
    실제로 발생한 드리프트다.

    `event_kind`(선택)로 종류 필터, `since`/`until`(선택)로 `occurred_at` 시간창(inclusive),
    `order`로 정렬 방향(기본 desc), `include_total=true`면 `X-Total-Count` 헤더. 모두 생략 시 전체.
    """
    conds = [
        PrivacyAudit.user_id == user.user_id,
        *time_window_conditions(PrivacyAudit.occurred_at, since, until),
    ]
    if event_kind:
        conds.append(PrivacyAudit.event_kind.in_([ek.value for ek in event_kind]))
    primary = PrivacyAudit.occurred_at.asc() if order == "asc" else PrivacyAudit.occurred_at.desc()
    stmt = (
        select(PrivacyAudit)
        .where(*conds)
        .order_by(primary, PrivacyAudit.audit_id)
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    rows = [row.to_schema() for row in result.scalars().all()]
    await _maybe_set_total(
        session,
        response,
        include_total,
        select(func.count()).select_from(PrivacyAudit).where(*conds),
    )
    return rows


# ── slice L2-4: 풀이 채점 제출 → ProblemAttempt 적재 + BKT 숙달 자동 전파 ──────────
# 클라 신고 `started_at`이 서버 수신 시각보다 앞서야 한다는 규칙의 허용 오차.
#
# 0으로 두지 않는 이유: 학생 기기의 시계는 실제로 몇 초~몇 분 어긋난다(NTP 미동기 태블릿).
# 엄격히 거부하면 정직한 제출이 422로 튕겨 학습 기록이 통째로 유실된다. 반대로 무제한 허용은
# 보존기한 회피를 낳는다 — 막아야 할 것은 *무한한* 미래이지 몇 분의 시계 오차가 아니므로,
# 유계(有界)로 자른다. 5분이면 시계 오차는 흡수하고 보존기한(년 단위)에는 영향이 없다.
_STARTED_AT_SKEW_TOLERANCE = timedelta(minutes=5)


@dataclass(frozen=True)
class _AttemptMisconceptionScan:
    """`_scan_attempt_misconceptions`의 결과 — 훑기 3상태 + 게이트 통과 후보.

    능력 구현이 돌려주는 리치 타입을 Core 안에 들이지 않으려는 좌석이다. Core가 읽는 것은
    `scan`·`candidates` 둘뿐이므로(능력 Protocol이 노출하는 것과 동일) 여기서 그 둘만 고정한다.
    """

    scan: MisconceptionScan
    candidates: tuple[MisconceptionCandidate, ...]


_NOT_SCANNED = _AttemptMisconceptionScan(scan=MisconceptionScan.NOT_RUN, candidates=())
"""훑지 않음 — 정답·답안 미제출·문항 부재·킬 스위치 OFF. **"오개념 없음"이 아니다.**"""


async def _scan_attempt_misconceptions(
    session: AsyncSession,
    detector: AttemptMisconceptionDetector,
    *,
    problem_id: uuid.UUID,
    correct: bool,
    answer: str | None,
) -> _AttemptMisconceptionScan:
    """채점 1건에서 오개념 후보를 훑는다 — 재료가 없으면 훑지 않았다고 말한다.

    훑지 않는 조건 4종(전부 `NOT_RUN`): 킬 스위치 OFF · 정답 시도 · 답안 미제출 · 문항 지문
    부재. 이 넷을 빈 후보 리스트로 뭉뚱그리지 않는 이유는, 그러면 하류가 *미측정*을 *측정된
    0*으로 읽기 때문이다(`MisconceptionScan` 3상태의 존재 이유).

    정답 시도를 제외하는 것은 성능이 아니라 정직 때문이다 — 오개념은 *틀린 방식*의 이름이라
    정답에 붙일 대상이 아니고, 붙지 않은 것과 보지 않은 것은 다른 사실이다.
    """
    if not get_settings().l4_attempt_misconception_scan_enabled:
        return _NOT_SCANNED
    if correct or answer is None:
        return _NOT_SCANNED
    question_text = await session.scalar(
        select(Problem.question_text).where(Problem.problem_id == problem_id)
    )
    if not question_text:
        return _NOT_SCANNED
    # 능력은 **주입받는다**(app.state 등록분·EOS-89 push 형태) — Core가 합성 루트를 이름으로
    # 알지 않는다. Core가 아는 것은 인터페이스 타입 하나뿐이다.
    try:
        result = detector.scan_attempt_answer(question_text=question_text, student_answer=answer)
    except Exception as exc:  # noqa: BLE001 — 관측이 채점을 깨뜨리지 않는다(아래 주석)
        # **never-break**: 이 시점에 attempt는 *이미 commit됐다*. 훑기는 관측이므로 여기서 터지면
        # 기록된 제출이 500으로 돌아가 학생이 다시 풀게 된다 — 관측 실패가 채점 실패를 만드는 셈.
        # 그래서 삼키되, **예외 타입명을 반드시 남긴다**(CLAUDE.md 침묵 실패 금지 — 무타입 경고가
        # langfuse v2 쓰기 8일 무증상 전멸의 원인이었다). 학생 답안·지문은 로그에 넣지 않는다(PII).
        _logger.warning(
            "오개념 훑기 실패 — 채점은 계속한다(scan=not_run). exc_type=%s problem_id=%s",
            type(exc).__name__,
            problem_id,
        )
        return _NOT_SCANNED
    return _AttemptMisconceptionScan(scan=result.scan, candidates=tuple(result.candidates))


class AttemptSubmitRequest(BaseModel):
    """본인 풀이 채점 결과 제출 — `POST /v1/me/attempts` 요청 본문.

    v1: `is_correct`는 *클라이언트 보고*(서버측 답안 채점[OCR·answer-check]은 L3/L5 후속). 이
    필드·엔드포인트는 S3-32(코치 대화 흐름의 완료 통합) 도입 이후에도 **의도적으로 그대로**다 —
    학생이 (예: OCR로 인식한 풀이를) 코치 대화 밖에서 직접 채점 결과를 보고하는 v1 경로는 계속
    존재한다. S3-32는 이와 *별개*로, `/v1/coach/sessions[/turns]` 대화 흐름 안에서 서버가
    `l3.verify_final_answer`로 최종답을 직접 검증하고 Polya 돌아보기(메타인지) 1턴을 거쳐
    `ProblemAttempt`를 *서버 권위*로 적재하는 두 번째 경로를 추가한다(`api/coach.py`의
    `_complete_problem`·`l4/completion.py`). 두 경로는 각자의 `is_correct` 출처가 다르다(여기는
    클라 보고 그대로·코치 경로는 서버 검증 결과) — 어느 한쪽이 다른 쪽을 대체하지 않는다.
    `problem_id`는 존재하는 문제를 참조해야 한다(FK — 미존재 시 저장계층 무결성 오류).
    """

    model_config = ConfigDict(extra="forbid")

    problem_id: uuid.UUID = Field(description="채점 대상 문제 FK.")
    is_correct: bool = Field(description="정답 여부(v1 클라이언트 보고).")
    student_answer: str | None = Field(default=None, description="학생 제출 답안(선택).")
    duration_seconds: int | None = Field(default=None, ge=0, description="풀이 소요 시간(초).")
    # PED-37: 클라 *신고* 발생 시작 시각(선택). 서버가 대신 만들어 낼 수 없는 값이라 클라가 주는
    # 통로를 여는 것 말고 정직한 방법이 없다 — `ended_at − duration_seconds` 역산은 ended_at이
    # 서버 수신 시각이라 지연·오프라인 제출에서 창이 통째로 밀린다(32_learning_history §EOS-48-2
    # "수신 시각 복제 = 날조"). 미제출이면 NULL로 남고, 그 attempt는 시간창 집계·보존 파기에서
    # 조용히 빠진다(빠지는 것이 계약 — 없는 시각을 지어내지 않는다).
    started_at: datetime | None = Field(
        default=None,
        description=(
            "풀이 시작 시각(클라이언트 신고·선택). **timezone 필수**(`Z` 또는 `±HH:MM`) — "
            "naive 값은 422로 거부한다(asyncpg가 서버 로컬 TZ로 해석해 시각이 어긋난다). "
            "서버 수신 시각보다 미래인 값도 422(보존기한 회피 방지·허용 오차 5분). "
            "미제출 시 NULL=미측정으로 남는다 — 서버 시각으로 대체하지 않는다(EOS-48)."
        ),
    )
    session_id: uuid.UUID | None = Field(default=None, description="소속 학습 세션(선택).")
    confidence_self_reported: float | None = Field(
        default=None, ge=0.0, le=1.0, description="학생 자기보고 확신도 0~1(선택)."
    )


class ConceptMasteryUpdate(BaseModel):
    """채점으로 갱신된 한 개념의 숙달 측정 — 응답에 포함(학습 곡선 즉시 피드백)."""

    concept_id: uuid.UUID
    mastery: float
    sample_size: int


class SkillMasteryUpdate(BaseModel):
    """채점으로 갱신된 한 스킬의 숙달 측정 — 응답에 포함(행동 축 학습 곡선 즉시 피드백).

    `ConceptMasteryUpdate`의 스킬 축 짝 — 키가 `concept_id`(UUID)가 아니라 `skill_id`(str)다.
    """

    skill_id: str
    mastery: float
    sample_size: int


# EOS-105 학습 상태 머신 — 정책이 소유하는 트리거(클라이언트가 이 표면으로 적재 금지).
#
# 집합으로 두는 이유: `POST /learning-state/transitions`가 문자열 접두사(`startswith("POLICY_")`)
# 로 걸러도 되지만, 그러면 **이름 규약이 곧 보안 경계**가 된다. 규약은 리팩터링으로 조용히
# 깨지고 그때 이 게이트도 함께 열린다. 열거된 집합은 트리거를 추가한 사람이 여기 한 줄을
# 넣도록 강제하며, 그 강제는 테스트가 동결한다(누락 시 RED).
_POLICY_OWNED_TRIGGERS: frozenset[TransitionTrigger] = frozenset(
    {
        TransitionTrigger.ATTEMPT_SUBMITTED,
        TransitionTrigger.POLICY_ADVANCE,
        TransitionTrigger.POLICY_PRACTICE_LOW_CONFIDENCE,
        TransitionTrigger.POLICY_REMEDIATE_MISCONCEPTION,
        TransitionTrigger.POLICY_PREREQUISITE_GAP,
        TransitionTrigger.POLICY_REPEATED_FAILURE,
        TransitionTrigger.POLICY_PRACTICE_UNDIAGNOSED,
    }
)


class LearningStateTransitionView(BaseModel):
    """전이 이력 1건 — "왜 지금 이 상태인가"의 재구성 자료."""

    from_state: LearningState
    to_state: LearningState
    trigger: TransitionTrigger
    rule_id: str | None = Field(
        default=None, description="정책이 낸 전이면 규칙 id, 생애주기 전이면 null."
    )
    concept_id: str | None = Field(default=None, description="전이가 일어난 맥락 개념 id.")
    occurred_at: datetime


class LearningStateView(BaseModel):
    """`GET /v1/me/learning-state` 응답 — 현재 상태 + 가능한 다음 상태 + 최근 이력."""

    current_state: LearningState = Field(
        description="현재 학습 상태. 전이 이력이 없으면 `NEW`(상태 미상이라는 값은 없다)."
    )
    allowed_next_states: list[str] = Field(
        description=(
            "현재 상태에서 전이표가 허용하는 다음 상태 목록(정렬). 클라이언트가 전이 규칙을 "
            "복제하지 않도록 서버가 내려 준다 — 규칙의 진실 원천은 서버 전이표 하나다."
        )
    )
    transitions: list[LearningStateTransitionView] = Field(description="최근 전이 이력(최신순).")


class LearningStateTransitionRequest(BaseModel):
    """`POST /v1/me/learning-state/transitions` 요청 — 생애주기 전이 1건.

    `from_state`를 받지 않는다: 클라이언트가 출발 상태를 지어내면 원장이 실제 이력과 어긋난다.
    출발 상태는 서버가 원장에서 직접 읽는다.
    """

    to_state: LearningState = Field(description="전이할 목표 상태.")
    trigger: TransitionTrigger = Field(
        description=(
            "전이 사유. 정책 소유 트리거(`ATTEMPT_SUBMITTED`·`POLICY_*`)는 422로 거부된다 "
            "— 그 전이는 `POST /v1/me/attempts`만 적재할 수 있다."
        )
    )
    concept_id: str | None = Field(default=None, description="맥락 개념 id(선택).")


class LearningStateBlock(BaseModel):
    """응답에 실리는 학습 상태 머신의 결과 — EOS-105.

    **`rejected_transition`이 이 모델의 존재 이유다.** 미정의 전이를 예외로만 흘리면 호출부가
    `except`로 잡는 순간 사라지고, 사라지면 "조용히 통과"가 된다. 값으로 만들어 학생 응답까지
    올려 보내 거부가 관측 가능하게 한다(CLAUDE.md 침묵 실패 금지).

    `rule_id`는 "어느 규칙이 실제로 돌았는가"를 매 요청 노출한다 — 알고리즘을 붙였으면 그것이
    작동한 비율을 응답이 말해야 한다는 원칙(CLAUDE.md "작동한 비율")의 집행 지점이다.
    """

    from_state: LearningState = Field(description="응답 제출 시점의 학습 상태.")
    to_state: LearningState = Field(description="이 처리가 끝난 뒤의 학습 상태.")
    rule_id: str | None = Field(
        default=None,
        description="결정을 낸 정책 규칙 id. 전이가 거부돼 정책이 돌지 않았으면 null.",
    )
    next_action: NextActionKind | None = Field(
        default=None, description="정책이 지시한 다음 행동의 종류. 정책 미실행이면 null."
    )
    target_concept_id: str | None = Field(
        default=None, description="다음 행동의 대상 개념 id(선수 개념 복귀 등). 없으면 null."
    )
    target_misconception_id: str | None = Field(
        default=None, description="교정 대상 오개념 id. 없으면 null."
    )
    rejected_transition: str | None = Field(
        default=None,
        description=(
            "거부된 전이의 설명(예: 'DIAGNOSING → ASSESSING'). null이면 거부 없음. 값이 "
            "있으면 상태 머신은 평가 전이를 적재하지 않았다 — 응답 적재·숙달 전파는 그와 "
            "무관하게 성공한다(이 슬라이스는 기존 학습 경로를 막지 않는다)."
        ),
    )
    entered_learning_from: LearningState | None = Field(
        default=None,
        description=(
            "평가 직전에 **학습 진입 전이가 자동 적재된 경우** 그 직전 상태(EOS-115). "
            "null이면 이미 평가 가능한 상태였다는 뜻이다. 붙인 단계가 실제로 돌았는지를 "
            "응답이 말하게 하는 필드다(CLAUDE.md '작동한 비율')."
        ),
    )


class AttemptSubmitResponse(BaseModel):
    """`POST /v1/me/attempts` 응답 — 적재된 attempt + 갱신된 개념·스킬 숙달 목록 + 학습 상태."""

    attempt_id: uuid.UUID
    is_correct: bool
    mastery_updates: list[ConceptMasteryUpdate]
    skill_mastery_updates: list[SkillMasteryUpdate] = Field(
        default_factory=list,
        description=(
            "채점으로 갱신된 스킬 숙달 목록(Phase 2b-2·행동 축). 정답은 평가 개념 전체의 스킬, "
            "오답은 PRIMARY 개념의 스킬만(모델 B). concept→skill 매핑/해소가 없으면 빈 목록."
        ),
    )
    calibration_coaching: CoachingTrigger | None = Field(
        default=None,
        description=(
            "보정(calibration) 코칭(WH-1 §11.4) — 자기보고 확신도↔정오답 불일치 시 처방. "
            "과신(틀렸으나 확신↑)·과소신(맞았으나 확신↓) 구간에서만 채워지고, 잘 보정됐거나 "
            "확신 미제출(None)이면 null. 적재 로직과 무관한 순수 L4 결정(측정→코칭)."
        ),
    )
    evidence: AssessmentEvidence | None = Field(
        default=None,
        description=(
            "이 채점이 만들어 낸 **증거 묶음**(EOS-12) — 개념·스킬·오개념 후보 3종과 작동 비율. "
            "`mastery_updates`가 *쓰기 이후*의 결과라면 이 필드는 *쓰기 이전*의 관측이라, 둘을 "
            "나란히 실어 두 단계가 각각 보이게 한다(부분 쓰기 구조를 한 트랜잭션처럼 가리지 "
            "않는다). `coverage`를 함께 읽어라 — 0건이 '이 답에는 없었다'인지 '보지 않았다'인지 "
            "거기에만 적혀 있다."
        ),
    )
    learning_state: LearningStateBlock = Field(
        description=(
            "학습 상태 머신(EOS-105) 처리 결과 — Event→LearnerState→Policy→NextAction. "
            "전이가 거부된 경우에도 null이 아니라 `rejected_transition`이 채워진 블록이 온다."
        )
    )


@router.post(
    "/attempts",
    response_model=AttemptSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="풀이 채점 제출(ProblemAttempt 적재 + 숙달 자동 갱신)",
)
async def submit_attempt(
    body: AttemptSubmitRequest,
    user: ConsentedUser,
    session: SessionDep,
    misconception_detector: Annotated[
        AttemptMisconceptionDetector, Depends(get_attempt_misconception_detector)
    ],
) -> AttemptSubmitResponse:
    """본인 풀이 채점 1건 제출 — `ProblemAttempt` 적재 후 문제의 평가 개념 BKT 숙달 자동 전파.

    user_id는 인증에서 주입(본문 무시·타인 사칭 차단). attempt를 먼저 commit하고(주된 기록)
    이어서 `record_problem_attempt_mastery`로 숙달을 시계열에 누적한다 — **모델 B(역할 비대칭)**:
    정답은 평가 개념(PRIMARY·TESTED) *전체*, 오답은 책임귀속 가능한 PRIMARY만 갱신(L2 슬라이스 3).
    응답 `mastery_updates`엔 *실제 갱신된* 개념만 담긴다(오답 시 PRIMARY).

    이어서 `record_problem_attempt_skill_mastery`로 *스킬 축* 숙달도 같은 모델 B로 전파한다(Phase
    2b-2·행동 축) — 평가 개념을 `Concept.behavior_skills` 브리지로 mastery-estimable 스킬에 해소해
    갱신한다. 응답 `skill_mastery_updates`는 실제 갱신된 스킬만(매핑/해소 없으면 빈 목록).

    S3-32 참고: 이 엔드포인트는 `is_correct`를 *클라이언트 보고 그대로* 신뢰하는 v1 경로다(변경
    없음 — `AttemptSubmitRequest` docstring 참조). 코치 대화 흐름(`/v1/coach/sessions[/turns]`)
    에서 정답에 도달하면 *같은 두 헬퍼*(`record_problem_attempt_mastery`·
    `record_problem_attempt_skill_mastery`)를 재사용하는 별도의 서버검증 attempt 적재 경로가
    있다 — `api/coach.py::_complete_problem`(서버가 `l3.verify_final_answer`로 직접 판정한
    `is_correct=True`만 적재·Polya 돌아보기 1턴 경유). 두 경로 모두 `GET /me/next-problem`의
    미시도 필터에서 동일하게 소비된다(`ProblemAttempt` 존재 여부만 본다).

    PED-37 시간 귀속: `started_at`은 **클라가 신고한 발생 시각을 그대로** 적재하고(미신고면 NULL),
    서버가 이 요청을 받은 시각은 `ingested_at`에 따로 남긴다(EOS-48 발생/수신 분리). 이 컬럼이
    비어 있던 동안 `harness/wh1_evaluation`의 since/until 집계(R15 정답률 추세·난이도 추세·Brier·
    전이 점수)와 `privacy/retention`의 보존기한 파기가 *조용히 0행*이었다 — 시간창 조건이 NULL과
    비교돼 어떤 행도 통과하지 못했기 때문이다.
    """
    # 서버 *수신* 시각 — 한 번만 읽어 아래 두 컬럼에 같은 값을 쓴다(두 번 호출 시 생기는
    # 마이크로초 시차가 "종료가 수신보다 앞선다"는 사실 아닌 신호로 남는 것을 막는다).
    received_at = datetime.now(UTC)
    # naive datetime 거부 — 다른 라우터(`GET /v1/devices`·`/v1/me/deletions`)와 *같은 헬퍼*를
    # 써서 에러 표면을 하나로 유지한다(병렬 구현 금지·`_query_filters` 모듈 취지).
    #
    # 왜 필수인가: asyncpg의 TIMESTAMPTZ 인코더는 naive 값을 **서버 로컬 TZ**로 해석한다.
    # 프로덕션 컨테이너가 UTC이므로 한국 로컬 시각(`2026-09-07T10:00:00`)이 9시간 어긋나
    # 저장되고, 그러면 이 변경이 되살리려던 시간창 귀속이 오히려 조용히 망가진다
    # (2026-09-07 실측: 오프셋 없는 ISO 문자열이 `tzinfo=None`으로 그대로 수용됐다).
    _validate_tz_aware(body.started_at, "started_at")
    if body.started_at is not None and body.started_at > received_at + _STARTED_AT_SKEW_TOLERANCE:
        # 미래 시각 거부 — 이 검증이 없으면 클라가 신고한 먼 미래 값이 그대로 적재되고,
        # `privacy/retention`의 파기 조건(`started_at < cutoff`)을 **영원히** 벗어난다.
        # 즉 미성년자 답안이 보존기한을 넘겨 무기한 잔존한다(2026-09-07 실측: 2076년 값이
        # 검증 없이 수용됐고 3년 cutoff 판정이 False였다).
        #
        # 이 PR *이전*에는 `started_at`이 항상 NULL이라 조작할 값 자체가 없었다 — 즉 이 통로를
        # 여는 변경이 그 공격 표면도 함께 만들었으므로, 여는 쪽에서 닫는다.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "`started_at`이 서버 수신 시각보다 미래입니다 — 발생 시각은 수신보다 앞설 수 "
                "없습니다. 기기 시계를 확인하거나 값을 생략하십시오(생략 시 NULL=미측정)."
            ),
        )
    # SEC-31: 학생 답안 3축(student_answer·handwriting_uri·ocr_result) 봉투 암호화 — cipher
    # 있으면 평문 컬럼은 NULL·암호화 컬럼에 저장(dialogue_turn._build_dialogue_turn 패턴 동형·
    # 순수 seam인 ProblemAttempt() 생성자엔 cipher를 넣지 않고 이 handler 층에서 결정한다).
    # `AttemptSubmitRequest`에 handwriting_uri·ocr_result가 아직 없어(v1 계약) 그 두 축은
    # 현재 항상 None이지만, 세 축을 *함께* 암호화 경로에 태워야 후속 writer가 그 필드를 채우기
    # 시작해도 곧바로 암호화 대상이 된다(부분 배선 방지 — EOS-32 §4-6 판정 근거와 동형).
    student_work_cipher = require_student_work_cipher(get_settings())
    student_answer_plain, student_answer_encrypted, student_answer_nonce = encrypt_dialogue_content(
        student_work_cipher, body.student_answer
    )
    attempt = ProblemAttempt(
        attempt_id=uuid.uuid4(),  # 명시 발급(server_default 의존 X·응답에 즉시 사용)
        user_id=user.user_id,
        problem_id=body.problem_id,
        session_id=body.session_id,
        is_correct=body.is_correct,
        student_answer=student_answer_plain,
        student_answer_encrypted=student_answer_encrypted,
        student_answer_nonce=student_answer_nonce,
        duration_seconds=body.duration_seconds,
        confidence_self_reported=body.confidence_self_reported,
        # PED-37: 클라 신고 발생 시각을 *그대로* 적재. 미신고면 None이 그대로 들어가 NULL로 남는다
        # (서버 now 폴백 금지 — 그 폴백이 시간창을 업로드 시각 기준으로 밀어 버린다).
        started_at=body.started_at,
        # `ended_at`은 기존 동작(서버 now)을 *일부러* 유지한다. 엄밀히는 이 값도 발생이 아니라
        # 수신 시각이지만, 정정하려면 클라 신고 ended_at을 새로 받아야 하고 그 사이 미신고 행은
        # NULL이 되어 이 컬럼으로 attempt를 정렬하는 기존 계약이 깨진다 — 별건으로 분리한다.
        ended_at=received_at,
        # EOS-48: 발생(started_at)과 분리된 서버 수신 시각 좌석. 오프라인 태블릿이 하루 뒤
        # sync해도 "언제 발생했고 언제 받았는가"가 둘 다 남아 지연 도착을 판별할 수 있다.
        ingested_at=received_at,
    )
    session.add(attempt)
    await session.commit()
    # EOS-12: 증거를 **숙달 전파보다 먼저** 조립한다 — Answer → Evidence → State 순서가 호출
    # 지점에서 실제로 성립해야 증거가 "갱신 결과의 사후 요약"으로 전락하지 않는다. 읽기 전용이라
    # (session.add·commit 0) 이 호출이 아래 적재의 성공/실패를 바꾸지 않고, 반대로 아래가 실패해도
    # 증거는 남는다 — 두 단계가 각각 관측 가능하다(EOS-81 ⑦ 부분 쓰기 구조를 가리지 않는다).
    # EOS-104: 오답 1건의 오개념 훑기 — 이 슬라이스의 **집행 지점**이다(정본화≠집행).
    # 과목 어댑터가 문항 지문·제출 답안을 이어 오류 서명을 읽고, 품질 게이트를 통과한 후보만
    # 돌려준다. Core는 두 문자열을 *불투명 페이로드*로 넘길 뿐 해석하지 않는다(경계 규칙).
    #
    # 귀속(핵심): 후보의 재료가 **이 attempt에서만** 나오므로 attempt 귀속이 정의상 성립한다.
    # 대화 턴의 게이트 매칭을 옮겨 오지 않는 이유가 이것이다 — 그쪽은 *턴* 단위라 옮기면
    # "이 답안의 오개념 후보"가 거짓 주장이 된다(EOS-104 acceptance ③).
    misconception_scan_result = await _scan_attempt_misconceptions(
        session,
        misconception_detector,
        problem_id=body.problem_id,
        correct=body.is_correct,
        answer=body.student_answer,
    )
    evidence = await collect_assessment_evidence(
        session,
        learner_id=user.user_id,
        problem_id=body.problem_id,
        correct=body.is_correct,
        attempt_id=attempt.attempt_id,
        observed_at=received_at,
        possible_misconceptions=misconception_scan_result.candidates,
        misconception_scan=misconception_scan_result.scan,
    )
    # 학습자 상태 반영 — 증거 조립(읽기 전용)과 **분리된 단계**다. 증거는 관측이고 상태 변경은
    # 엔진의 몫이라, 둘을 한 함수에 넣으면 "한 트랜잭션처럼 보이기" 문제가 생긴다(EOS-12 ⑤).
    #
    # 훑은 회차에만 부른다. 후보가 0건이어도 부르는 것이 중요하다 — 그 호출이 이번 회차에
    # 증거를 못 받은 기존 가설을 감쇠시킨다(Persona C: 오개념이 재관측되지 않으면 confidence가
    # *내려가야* 한다). 반대로 훑지 않은 회차(정답·답안 없음·능력 부재)에 부르면 관측하지도
    # 않은 것을 근거로 신뢰를 깎는 셈이라 부르지 않는다.
    if misconception_scan_result.scan is not MisconceptionScan.NOT_RUN:
        await apply_candidates(session, user.user_id, misconception_scan_result.candidates)
        await session.commit()
    # 숙달 전파(평가 개념별 측정 적재·개념 매핑 없으면 빈 리스트)
    # EOS-18: 위에서 조립한 **그 증거**를 그대로 넘긴다 — 학습자·문항·정오답·관측시각을 다시
    # 인자로 풀면 같은 사실의 사본이 둘이 되고, 어긋나도 아무도 모른다.
    records = await record_problem_attempt_mastery(session, evidence=evidence)
    # 스킬 숙달 전파(Phase 2b-2·행동 축) — 같은 모델 B로 concept→skill 해소 후 스킬별 측정 적재.
    # 개념 전파와 독립 트랜잭션(자체 단일 commit)·concept→skill 매핑/해소 없으면 빈 리스트.
    skill_records = await record_problem_attempt_skill_mastery(session, evidence=evidence)
    # EOS-57: 해소된 스킬 배열을 `문제시도` 이벤트로 영속(소급 불가 축 — W2 스키마 ①).
    # 숙달 전파는 "스킬 값이 언제 변했는가"만 남기고 "이 시도가 어떤 스킬을 건드렸는가"는 남기지
    # 않는다 — 매핑이 이후 바뀌면 재구성 불가라 채점 순간에 기록한다. 빈 해소도 `[]`로 적재
    # (미기록 NULL과 구분 — l2.attempt_skill_event 모듈 docstring).
    await record_attempt_skill_event(
        session,
        user_id=user.user_id,
        attempt_id=attempt.attempt_id,
        problem_id=body.problem_id,
        is_correct=body.is_correct,
        skill_ids=[r.skill_id for r in skill_records],
        source=AttemptSource.attempt_submit,
    )
    # WH-1 §11.4 보정 루프: 이미 받은 자기보고 확신도↔정오답에서 과신/과소신 코칭 결정.
    # 순수 L4 결정(DB 무접근·적재 로직 불변)·확신 미제출(None)이면 None(자연).
    calibration_coaching = recommend_calibration_coaching(
        body.confidence_self_reported, body.is_correct
    )
    # EOS-105 학습 상태 머신 — Event → LearnerState → Policy → Next Action.
    #
    # 여기가 이 슬라이스의 **집행 지점**이다(정본화≠집행). 전이표·정책을 만든 것만으로는
    # 아무 학생의 상태도 움직이지 않는다 — 서빙 경로가 그것을 실제로 부르는 이 줄이 계약을
    # 집행으로 바꾼다.
    #
    # 순서 주의: `build_attempt_evidence`는 이번 attempt가 **이미 commit된 뒤** 호출된다
    # (연속 오답 카운트가 `offset(1)`로 이번 행을 건너뛰도록 설계됨 — 그 모듈 docstring 참조).
    #
    # 한계(명시): `prerequisite_gap_concept_ids`의 생산자는 이 경로에 배선하지 않았다 —
    # 개념 그래프 재귀 CTE 순회가 응답 제출마다 돌기엔 무겁다. 따라서 규칙 R4는 이 경로에서
    # 매치되지 않는다. 숨기지 않고 적어 둔다(`l2/learning_state_evidence.py` 생산자 배선 현황).
    # 이름 주의: `evidence`는 EOS-12의 `AssessmentEvidence`(응답 필드)가 이미 쓰고 있다.
    # 상태 머신이 읽는 것은 정책 입력(`AttemptEvidence`)으로 **다른 타입·다른 목적**이므로
    # 이름을 분리한다 — 같은 이름을 재사용하면 응답의 `evidence=evidence`가 조용히 다른
    # 객체를 받는다(2026-09-17 main 병합에서 실제로 그 상태가 만들어졌다).
    policy_evidence = await build_attempt_evidence(
        session,
        user_id=user.user_id,
        is_correct=body.is_correct,
        confidence=body.confidence_self_reported,
    )
    transition = await advance_on_attempt(
        session,
        user_id=user.user_id,
        evidence=policy_evidence,
        attempt_id=attempt.attempt_id,
    )
    decision = transition.decision
    learning_state_block = LearningStateBlock(
        from_state=transition.from_state,
        to_state=transition.final_state,
        rule_id=decision.rule_id if decision is not None else None,
        next_action=decision.next_action.kind if decision is not None else None,
        target_concept_id=(decision.next_action.target_concept_id if decision else None),
        target_misconception_id=(
            decision.next_action.target_misconception_id if decision else None
        ),
        rejected_transition=transition.rejected_transition,
        entered_learning_from=transition.entered_learning_from,
    )
    return AttemptSubmitResponse(
        attempt_id=attempt.attempt_id,
        is_correct=body.is_correct,
        mastery_updates=[
            ConceptMasteryUpdate(
                concept_id=r.concept_id,
                # record_problem_attempt_mastery는 항상 mastery를 채우나 ORM 타입이 float|None.
                mastery=float(r.mastery) if r.mastery is not None else 0.0,
                sample_size=r.sample_size if r.sample_size is not None else 0,
            )
            for r in records
        ],
        skill_mastery_updates=[
            SkillMasteryUpdate(
                skill_id=r.skill_id,
                # 순수 커널이 항상 mastery를 채우나 ORM 타입이 float|None(개념 축 동형).
                mastery=float(r.mastery) if r.mastery is not None else 0.0,
                sample_size=r.sample_size if r.sample_size is not None else 0,
            )
            for r in skill_records
        ],
        calibration_coaching=calibration_coaching,
        evidence=evidence,
        learning_state=learning_state_block,
    )


@router.get(
    "/learning-state",
    response_model=LearningStateView,
    summary="내 현재 학습 상태 + 전이 이력(학습 상태 머신)",
)
async def get_my_learning_state(
    user: ConsentedUser,
    session: SessionDep,
    limit: Limit = 50,
) -> LearningStateView:
    """본인 학습 상태 — 현재 상태·거기서 갈 수 있는 상태·최근 전이 이력.

    `allowed_next_states`를 함께 내는 이유: 클라이언트가 전이 규칙을 자기 코드에 복제하지
    않게 하기 위해서다. 규칙을 클라에 넣으면 전이표의 진실 원천이 둘이 된다(서버 표 + 클라
    분기) — CLAUDE.md "수학 로직을 클라에 넣지 않는다"의 제어 평면 판이다.
    """
    current = await get_current_state(session, user.user_id)
    transitions = await list_transitions(session, user.user_id, limit=limit)
    return LearningStateView(
        current_state=current,
        allowed_next_states=sorted(s.value for s in allowed_targets(current)),
        transitions=[
            LearningStateTransitionView(
                from_state=t.from_state,
                to_state=t.to_state,
                trigger=t.trigger,
                rule_id=t.rule_id,
                concept_id=t.concept_id,
                occurred_at=t.occurred_at,
            )
            for t in transitions
        ],
    )


@router.post(
    "/learning-state/transitions",
    response_model=LearningStateView,
    status_code=status.HTTP_201_CREATED,
    summary="학습 상태 전이 1건 적재(생애주기 전이 — 진단 시작·학습 시작 등)",
)
async def post_my_learning_state_transition(
    body: LearningStateTransitionRequest,
    user: ConsentedUser,
    session: SessionDep,
) -> LearningStateView:
    """생애주기 전이를 명시적으로 적재한다 — 진단 시작·완료·학습 시작 같은 사건.

    응답 제출로 일어나는 평가 전이(`ATTEMPT_SUBMITTED` 및 정책 전이)는 이 표면이 아니라
    `POST /v1/me/attempts`가 적재한다. 여기서 그 트리거를 허용하면 클라이언트가 정책을
    우회해 임의 상태로 점프할 수 있다 — 그래서 **거부한다**(422).

    미정의 전이는 409로 거부한다. 200에 "실패했음" 플래그를 실어 보내지 않는다 — 그 형태는
    호출부가 플래그를 안 읽는 순간 조용한 통과가 된다.
    """
    if body.trigger in _POLICY_OWNED_TRIGGERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"`{body.trigger.value}`는 정책 엔진이 소유하는 트리거입니다 — 이 표면으로 "
                f"적재할 수 없습니다. 평가 전이는 `POST /v1/me/attempts`가 적재합니다."
            ),
        )
    try:
        await record_transition(
            session,
            user_id=user.user_id,
            to_state=body.to_state,
            trigger=body.trigger,
            concept_id=body.concept_id,
        )
    except UndefinedTransitionError as exc:
        # 예외 타입명을 detail에 포함한다(CLAUDE.md 침묵 실패 금지 — 무타입 경고 금지).
        current = await get_current_state(session, user.user_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{type(exc).__name__}: {exc.from_state.value} → {exc.to_state.value}는 "
                f"정의되지 않은 전이입니다. {current.value}에서 갈 수 있는 상태: "
                f"{sorted(s.value for s in allowed_targets(current)) or '없음'}."
            ),
        ) from exc
    return await get_my_learning_state(user, session)


@router.get(
    "/mastery",
    response_model=list[ConceptMasteryHistorySchema],
    summary="내 개념 숙달 학습 곡선(ConceptMasteryHistory 시계열)",
)
async def list_my_mastery(
    user: ConsentedUser,
    session: SessionDep,
    response: Response,
    limit: Limit = 50,
    offset: Offset = 0,
    concept_id: ConceptIdFilter = None,
    since: SinceParam = None,
    until: UntilParam = None,
    order: OrderParam = "desc",
    include_total: IncludeTotal = False,
) -> list[ConceptMasteryHistorySchema]:
    """본인 개념 숙달 측정 시계열 — 학습 곡선(특성 #16). 풀이 채점(slice L2-4)이 누적한
    `concept_mastery_history`를 user_id 스코핑으로 조회(타인 차단).

    `concept_id`(선택)로 한 개념의 곡선만·`since`/`until`로 `measured_at` 시간창·`order`로
    방향(기본 desc 최신순)·`include_total`로 `X-Total-Count`. 2차 정렬키 concept_id로 동률
    (같은 measured_at·다개념) 안정 정렬.
    """
    conds = [ConceptMasteryHistory.user_id == user.user_id]
    if concept_id is not None:
        conds.append(ConceptMasteryHistory.concept_id == concept_id)
    conds += time_window_conditions(ConceptMasteryHistory.measured_at, since, until)
    primary = (
        ConceptMasteryHistory.measured_at.asc()
        if order == "asc"
        else ConceptMasteryHistory.measured_at.desc()
    )
    stmt = (
        select(ConceptMasteryHistory)
        .where(*conds)
        .order_by(primary, ConceptMasteryHistory.concept_id)
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    rows = [row.to_schema() for row in result.scalars().all()]
    await _maybe_set_total(
        session,
        response,
        include_total,
        select(func.count()).select_from(ConceptMasteryHistory).where(*conds),
    )
    return rows


@router.get(
    "/skill-mastery",
    response_model=list[SkillMasteryHistorySchema],
    summary="내 스킬 숙달 학습 곡선(SkillMasteryHistory 시계열·행동 축)",
)
async def list_my_skill_mastery(
    user: ConsentedUser,
    session: SessionDep,
    response: Response,
    limit: Limit = 50,
    offset: Offset = 0,
    skill_id: Annotated[
        str | None, Query(description="한 스킬(`skill.<slug>`)의 곡선만 필터(선택).")
    ] = None,
    since: SinceParam = None,
    until: UntilParam = None,
    order: OrderParam = "desc",
    include_total: IncludeTotal = False,
) -> list[SkillMasteryHistorySchema]:
    """본인 스킬 숙달 측정 시계열 — 행동 축 학습 곡선(Phase 2b-2). 풀이 채점이 누적한
    `skill_mastery_history`를 user_id 스코핑으로 조회(타인 차단·`list_my_mastery` 스킬판).

    `skill_id`(선택)로 한 스킬의 곡선만·`since`/`until`로 시간창·`order`로 방향(기본 desc)·
    `include_total`로 `X-Total-Count`. 2차 정렬키 skill_id로 동률(같은 measured_at) 안정 정렬.
    """
    conds = [SkillMasteryHistory.user_id == user.user_id]
    if skill_id is not None:
        conds.append(SkillMasteryHistory.skill_id == skill_id)
    conds += time_window_conditions(SkillMasteryHistory.measured_at, since, until)
    primary = (
        SkillMasteryHistory.measured_at.asc()
        if order == "asc"
        else SkillMasteryHistory.measured_at.desc()
    )
    stmt = (
        select(SkillMasteryHistory)
        .where(*conds)
        .order_by(primary, SkillMasteryHistory.skill_id)
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    rows = [row.to_schema() for row in result.scalars().all()]
    await _maybe_set_total(
        session,
        response,
        include_total,
        select(func.count()).select_from(SkillMasteryHistory).where(*conds),
    )
    return rows


class ConceptMasterySnapshotItem(BaseModel):
    """현재 숙달 스냅샷 1개 — 측정값 + 개념 메타(이름·코드). 약점 목록 UI 표시용.

    slice L2-5d: 기존 `ConceptMasteryHistorySchema`(concept_id만)에 concept 테이블의
    `name_ko`·`code`를 조인해 클라이언트가 추가 조회 없이 개념명을 표시한다. 개념이 삭제돼
    조인이 비면(loose ref·orphan) name/code는 null(LEFT JOIN·행 보존).
    """

    model_config = ConfigDict(extra="forbid")

    concept_id: uuid.UUID
    concept_code: str | None = Field(default=None, description="개념 코드(예: CAL-INT-...).")
    concept_name: str | None = Field(default=None, description="개념 한글명(name_ko).")
    mastery: float | None = None
    confidence: float | None = None
    sample_size: int | None = None
    measured_at: datetime


TraceLimit = Annotated[
    int,
    Query(
        ge=1,
        le=MAX_TRACE_LIMIT,
        description=(
            "시간선 전역 상한. 초과분은 **오래된 쪽부터** 잘리고 응답의 `truncated`가 true가 된다."
        ),
    ),
]


@router.get(
    "/learning-trace",
    response_model=LearningEventTrace,
    summary="내 학습 과정 시간선(Event Trace — 여러 원천을 하나의 시간순으로 재구성)",
)
async def get_my_learning_trace(
    user: ConsentedUser,
    session: SessionDep,
    since: SinceParam = None,
    until: UntilParam = None,
    limit: TraceLimit = DEFAULT_TRACE_LIMIT,
) -> LearningEventTrace:
    """본인 학습 이벤트를 **시간순으로** 재구성한다(EOS-11 · 계획서 300 §17).

    진단·문제 시도·채점·오개념 가설·숙달 변경(전후 값 포함)·θ 측정·코치 행동 이벤트를 한 줄로
    합친 시간선이다. 집계 리포트와 달리 "이 학생에게 무슨 일이 순서대로 일어났는가"에 답한다.

    **스코프**: `user_id`는 인증 주체로 고정한다 — 경로·쿼리 어디에도 타인 id를 넣을 자리가
    없다(구조적 차단). 운영자·교사 열람은 이 표면의 범위가 아니다(`ADMIN-05` 계열 별건).

    **응답을 `entries`만 보고 읽지 말 것**: `coverage`가 원천별 가용성을 3상태로 말한다.
    `dormant`(생산자 0건)·`unjoinable`(학습자 축 결합 불가)인 원천의 0건은 *이 학생이 안 했다*는
    뜻이 아니라 *우리가 재지 않고 있다*는 뜻이다(미측정을 무활동으로 읽지 않기 — CLAUDE.md
    "작동한 비율" 원칙).

    원문 답안·풀이·수식은 싣지 않는다(미성년 PII 경계). 답안이 필요하면 `attempt_id`로
    기존 본인 표면을 경유한다.
    """
    return await build_trace(
        session,
        learner_id=user.user_id,
        since=since,
        until=until,
        limit=limit,
    )


@router.get(
    "/mastery/current",
    response_model=list[ConceptMasterySnapshotItem],
    summary="현재 개념별 숙달 스냅샷(개념마다 최신 측정 1건·개념명 포함)",
)
async def list_my_current_mastery(
    user: ConsentedUser,
    session: SessionDep,
    order_by: SnapshotOrderByParam = "concept_id",
    order: OrderParam = "asc",
) -> list[ConceptMasterySnapshotItem]:
    """본인의 *개념별 최신* 숙달 1건씩 + 개념 메타(이름·코드) — 현재 상태 스냅샷("한눈에").
    `/mastery`는 전 측정 시계열(학습 곡선)이고, 본 엔드포인트는 개념마다 가장 최근 측정만.

    Postgres `DISTINCT ON (concept_id)` + `ORDER BY concept_id, measured_at DESC`로 개념별
    최신 행을 고른다(개념당 1행). 스냅샷이라 페이지네이션·필터 없음(연습한 개념 수로 한정).

    slice L2-5c: `order_by=mastery`로 약점/강점 우선 정렬("다음에 뭘 연습할지"). DISTINCT ON은
    ORDER BY가 concept_id로 시작해야 해(최신 행 선택 불변) 결과(개념당 1행·소규모)를 Python에서
    재정렬한다. mastery NULL은 *항상 끝*(방향 무관). 기본 concept_id asc(기존 동작 보존).
    slice L2-5d: `concept`(name_ko·code) LEFT JOIN — 약점 목록에 개념명 노출(orphan은 null).
    """
    stmt = (
        select(ConceptMasteryHistory, Concept.code, Concept.name_ko)
        .outerjoin(Concept, ConceptMasteryHistory.concept_id == Concept.concept_id)
        .where(ConceptMasteryHistory.user_id == user.user_id)
        .distinct(ConceptMasteryHistory.concept_id)
        .order_by(
            ConceptMasteryHistory.concept_id,
            ConceptMasteryHistory.measured_at.desc(),
        )
    )
    result = await session.execute(stmt)
    items = [
        ConceptMasterySnapshotItem(
            concept_id=cmh.concept_id,
            concept_code=code,
            concept_name=name_ko,
            mastery=float(cmh.mastery) if cmh.mastery is not None else None,
            confidence=float(cmh.confidence) if cmh.confidence is not None else None,
            sample_size=cmh.sample_size,
            measured_at=cmh.measured_at,
        )
        for cmh, code, name_ko in result.all()
    ]
    reverse = order == "desc"
    if order_by == "mastery":
        # NULL 항상 끝(방향 무관) + 나머지는 mastery 기준 정렬(asc=약점 우선)
        present = sorted(
            (i for i in items if i.mastery is not None),
            key=lambda i: i.mastery if i.mastery is not None else 0.0,
            reverse=reverse,
        )
        items = present + [i for i in items if i.mastery is None]
    else:  # concept_id — DISTINCT ON 자연 순(asc)·desc면 역순
        items.sort(key=lambda i: str(i.concept_id), reverse=reverse)
    return items


# ── slice L2-11: GET /v1/me/ability (IRT 능력 θ 추정 — 채점 풀이 이력 기반) ──────
_CI_Z_95 = 1.96  # 95% 신뢰구간 z값(표준정규 양측 0.025)


class AbilityResponse(BaseModel):
    """`GET /v1/me/ability` 응답 — IRT 능력 추정(θ + 측정 정밀도)."""

    theta: float = Field(description="IRT 능력 추정 θ(logit). 채점 응답 없으면 0.")
    response_count: int = Field(description="추정에 쓰인 채점(is_correct 있는) 풀이 수.")
    standard_error: float | None = Field(
        default=None,
        description="θ 추정 표준오차 SE=1/√I(θ)(slice 13). 응답 없으면(측정 불가) null.",
    )
    confidence_interval: list[float] | None = Field(
        default=None,
        description="95% 신뢰구간 [하한, 상한] = θ ± 1.96·SE. SE 없으면 null.",
    )


@router.get(
    "/ability",
    response_model=AbilityResponse,
    summary="내 IRT 능력 추정(θ — 채점 풀이 이력 기반)",
)
async def get_my_ability(
    user: ConsentedUser,
    session: SessionDep,
) -> AbilityResponse:
    """본인의 채점된 풀이 이력에서 IRT 능력 θ를 추정 — 문항 난이도(difficulty_overall)와 정/오답.

    `problem_attempt`(is_correct 있는 것)를 `problem`과 조인해 (난이도→logit b, 정답) 응답을
    만들고 `estimate_ability`(slice 7)로 θ 추정. 난이도 없는(difficulty_overall NULL) 문항은
    제외. 채점 응답이 없으면 θ=0(정보 없음). v1: difficulty_overall(전문가 1~5)을 b 프록시로
    사용(보정 b는 fit_jmle 후속). BKT(개념별 숙달)와 *상보적* 단일 능력 척도.

    측정 정밀도(slice 13): `ability_standard_error`로 표준오차 SE=1/√I(θ)·95% 신뢰구간
    θ±1.96·SE를 함께 노출. 응답 0건(정보 0=SE 무한)이면 둘 다 null(측정 불가). 경계 θ
    (전부 정답/오답)의 SE는 Fisher 정보 기반이라 *낙관적*(실 불확실성 과소·EAP는 후속).
    """
    theta, se, count = await estimate_global_ability(session, user.user_id)
    if se is None:  # 정보 0(응답 없음) → 측정 불가
        return AbilityResponse(theta=theta, response_count=count)
    return AbilityResponse(
        theta=theta,
        response_count=count,
        standard_error=se,
        confidence_interval=[theta - _CI_Z_95 * se, theta + _CI_Z_95 * se],
    )


# ── slice L2-32: θ 시계열 적재 (POST 캡처 + GET 조회 — ability_snapshot) ──────────
# θ 시계열(history·snapshots 공용) 상한 — 최근 N개(끝 N). 생략 시 전체.
AbilityHistoryLimit = Annotated[
    int | None,
    Query(
        ge=1,
        le=500,
        description="최근 N개 지점만(시간 오름차순 중 끝 N). 생략 시 전체.",
    ),
]
# slice 33: 캡처 시 전과목 θ뿐 아니라 개념별 θ도 함께 적재(개념 곡선).
IncludeConcepts = Annotated[
    bool,
    Query(description="true면 전과목 θ + *개념별* θ를 함께 적재(개념별 성장 곡선). 기본 false."),
]


@router.post(
    "/ability/snapshots",
    response_model=AbilitySnapshotSchema,
    status_code=status.HTTP_201_CREATED,
    summary="현재 IRT 능력 θ 스냅샷 적재(시계열 캡처)",
)
async def capture_ability_snapshot(
    user: ConsentedUser,
    session: SessionDep,
    include_concepts: IncludeConcepts = False,
) -> AbilitySnapshotSchema:
    """현재 전 과목 θ를 계산해 `ability_snapshot`에 1행 적재 — 성장 곡선 시점 캡처.

    파생(slice 28 `/ability/history`·매 요청 재계산)과 달리 *적재형*: 호출 시점의 θ를 보존한다
    (세션 종료·일/주 주기 등 호출자가 캡처 시점 결정). 전과목 행은 `concept_id`=null. θ 계산은
    `/ability`(slice 11)와 동일 헬퍼. `include_concepts=true`면 개념별 θ(slice 18 계산)도 *같은
    시각*으로 함께 적재(개념별 곡선·`concept_id` 값 보유). 응답은 전과목 스냅샷. user_id 스코핑.
    """
    now = datetime.now(UTC)
    theta, se, count = await estimate_global_ability(session, user.user_id)
    snap = AbilitySnapshotSchema(
        user_id=user.user_id,
        theta=theta,
        standard_error=se,
        response_count=count,
        measured_at=now,
    )
    session.add(AbilitySnapshot.from_schema(snap))
    if include_concepts:
        await _add_concept_ability_snapshots(session, user.user_id, now)
    await session.commit()
    return snap


@router.get(
    "/ability/snapshots",
    response_model=list[AbilitySnapshotSchema],
    summary="내 IRT 능력 θ 스냅샷 시계열(적재된 성장 곡선)",
)
async def list_ability_snapshots(
    user: ConsentedUser,
    session: SessionDep,
    concept_id: ConceptIdFilter = None,
    limit: AbilityHistoryLimit = None,
) -> list[AbilitySnapshotSchema]:
    """적재된 θ 스냅샷을 *시간 오름차순*(성장 곡선)으로 조회. `?limit`이면 최근 N개(끝 N).

    파생 `/ability/history`(이력 재생)와 달리 *적재된* 시점들을 그대로 반환(캡처 당시 θ 보존).
    `?concept_id` 생략 시 *전과목 곡선*(concept_id IS NULL)만·지정 시 그 개념 곡선만(slice 33
    개념별 적재와 결선). 곡선이 섞이지 않게 기본 전과목. user_id 스코핑·읽기.
    """
    conds = [AbilitySnapshot.user_id == user.user_id]
    if concept_id is not None:
        conds.append(AbilitySnapshot.concept_id == concept_id)
    else:
        conds.append(AbilitySnapshot.concept_id.is_(None))  # 기본=전과목 곡선
    stmt = select(AbilitySnapshot).where(*conds).order_by(AbilitySnapshot.measured_at.asc())
    snaps = [row.to_schema() for row in (await session.execute(stmt)).scalars().all()]
    if limit is not None:
        snaps = snaps[-limit:]
    return snaps


# ── slice L2-18: GET /v1/me/ability/by-concept (개념별 IRT 능력 θ 분리) ───────────
@router.get(
    "/ability/by-concept",
    response_model=list[ConceptAbilityItem],
    summary="내 개념별 IRT 능력(θ — 개념마다 분리 추정)",
)
async def get_my_ability_by_concept(
    user: ConsentedUser,
    session: SessionDep,
) -> list[ConceptAbilityItem]:
    """채점 풀이 이력을 *문항의 평가 개념별*로 묶어 개념마다 IRT 능력 θ를 분리 추정.

    단일 전과목 θ(`/me/ability`)를 개념/도메인 축으로 쪼갠다(다차원 진단). `problem_attempt`(채점됨)
    를 `problem`·`problem_concept`(role∈PRIMARY/TESTED)와 조인해 개념별 (난이도→b, 정답) 응답을
    만들고 `estimate_ability`(slice 7)로 θ·`ability_standard_error`(slice 13)로 SE 추정. 개념명은
    `concept` LEFT JOIN(orphan은 null·slice L2-5d 패턴). 난이도 NULL 문항 제외. *능력 낮은(약점)
    개념 먼저* 정렬(asc·동률은 concept_id)로 "무엇을 보완할지" 우선순위 노출. BKT 개념별 숙달과
    *상보적*(BKT=정오답 확률·IRT=난이도 보정 능력). user_id 스코핑·읽기(마이그레이션 불필요).
    """
    items = await compute_concept_abilities(session, user.user_id)
    # 약점(저능력) 개념 먼저 — asc 정렬·동률은 concept_id로 안정화(결정론).
    items.sort(key=lambda i: (i.theta, str(i.concept_id)))
    return items


async def _add_concept_ability_snapshots(
    session: AsyncSession, user_id: uuid.UUID, measured_at: datetime
) -> None:
    """개념별 θ 스냅샷을 세션에 *추가만*(commit은 호출자) — 수동 캡처·세션 종료 공유(slice 75).

    `compute_concept_abilities`(slice 18 산식)의 각 개념 θ를 *주어진 시각*으로 적재(전과목
    스냅샷과 같은 measured_at). `capture_ability_snapshot(include_concepts)`와 세션 종료 자동
    적재(`_add_ability_snapshot_if_attempts`)가 공유해 개념 θ 곡선을 자연 샘플링한다(중복 제거).
    """
    for item in await compute_concept_abilities(session, user_id):
        session.add(
            AbilitySnapshot.from_schema(
                AbilitySnapshotSchema(
                    user_id=user_id,
                    concept_id=item.concept_id,
                    theta=item.theta,
                    standard_error=item.standard_error,
                    response_count=item.response_count,
                    measured_at=measured_at,
                )
            )
        )


# ── slice L2-28: GET /v1/me/ability/history (θ 성장 곡선 — 채점 이력 시간 재생) ─────


class AbilityHistoryPoint(BaseModel):
    """`GET /v1/me/ability/history`의 한 시점 — k번째 채점 직후 누적 θ."""

    as_of: datetime = Field(description="이 지점에 반영된 마지막 채점 시각(created_at).")
    theta: float = Field(description="이 시점까지 누적 응답으로 추정한 θ(logit).")
    standard_error: float | None = Field(
        default=None, description="이 시점 θ의 표준오차. 측정 불가면 null."
    )
    response_count: int = Field(description="이 시점까지 누적된 채점 풀이 수(=k).")


@router.get(
    "/ability/history",
    response_model=list[AbilityHistoryPoint],
    summary="내 IRT 능력 성장 곡선(θ — 채점 이력 시간 재생)",
)
async def get_my_ability_history(
    user: ConsentedUser,
    session: SessionDep,
    limit: AbilityHistoryLimit = None,
) -> list[AbilityHistoryPoint]:
    """채점 풀이 이력을 *시간순 재생*해 매 풀이 직후 누적 θ(성장 곡선)를 산출 — 적재 없이 파생.

    `problem_attempt`(채점됨·난이도 보유)를 `created_at` 오름차순으로 모아, k번째까지의 응답으로
    `estimate_ability`(slice 7)·`ability_standard_error`(slice 13)를 매 단계 계산해 시점 1개씩 방출.
    θ 시계열을 *저장하지 않고* 기존 이력에서 재구성(마이그레이션 0). `?limit`이면 *끝* N개(최근)만.
    전 과목 단일 θ(개념별·저장형 시계열은 후속). user_id 스코핑·읽기.

    v1 한계: 매 단계 θ 전체 재추정(O(n²))·시점=풀이당 1개(다운샘플·증분 추정은 후속).
    """
    stmt = (
        select(
            ProblemAttempt.created_at,
            ProblemAttempt.is_correct,
            Problem.difficulty_overall,
            Problem.irt_difficulty_b,
        )
        .join(Problem, ProblemAttempt.problem_id == Problem.problem_id)
        .where(
            ProblemAttempt.user_id == user.user_id,
            ProblemAttempt.is_correct.isnot(None),
            ProblemAttempt.created_at.isnot(None),
            Problem.irt_difficulty_b.isnot(None) | Problem.difficulty_overall.isnot(None),
        )
        .order_by(ProblemAttempt.created_at.asc())
    )
    responses: list[tuple[IrtItem, bool]] = []
    points: list[AbilityHistoryPoint] = []
    for created_at, is_correct, difficulty, irt_b in (await session.execute(stmt)).all():
        b = resolve_item_difficulty_b(irt_b, difficulty)
        if b is None:
            continue
        responses.append((IrtItem(difficulty=b), bool(is_correct)))
        theta = estimate_ability(responses)
        se = ability_standard_error(theta, [it for it, _ in responses])
        points.append(
            AbilityHistoryPoint(
                as_of=created_at,
                theta=theta,
                standard_error=None if math.isinf(se) else se,
                response_count=len(responses),
            )
        )
    if limit is not None:
        points = points[-limit:]
    return points


# ── slice L2-19: GET /v1/me/diagnosis/concepts (BKT 숙달 ↔ IRT θ 교차검증) ────────
# 진단 계산(BKT+IRT 융합·agreement·약점 정렬)은 L2 `concept_diagnosis`(slice 82 이관). 여기선
# 응답 스키마(+ L4 코칭 후처리)·엔드포인트만 둔다 — coaching은 L5 부착(L2→L4 역의존 회피).


class ConceptDiagnosisItem(BaseModel):
    """개념별 BKT↔IRT 교차검증 — `GET /v1/me/diagnosis/concepts`의 한 개념 항목."""

    concept_id: uuid.UUID = Field(description="개념 id.")
    concept_code: str | None = Field(default=None, description="개념 코드(orphan이면 null).")
    concept_name: str | None = Field(default=None, description="개념명(orphan이면 null).")
    bkt_mastery: float | None = Field(
        default=None, description="BKT 최신 숙달 P(L). 측정 없으면 null."
    )
    irt_theta: float | None = Field(
        default=None, description="개념별 IRT 능력 θ. 채점 풀이 없으면 null."
    )
    irt_mastery_proxy: float | None = Field(
        default=None,
        description="logistic(θ)∈[0,1] — BKT 숙달과 비교용. θ 없으면 null.",
    )
    response_count: int = Field(description="개념별 IRT 추정에 쓰인 채점 풀이 수.")
    agreement: Agreement = Field(
        description="BKT↔IRT 일치 신호(agree·irt_higher·bkt_higher·insufficient)."
    )
    coaching: CoachingTrigger = Field(
        description="L4 메타인지 코칭 처방(focus·rationale·prompt·slice 20)."
    )
    mastery_level: MasteryLevel | None = Field(
        default=None,
        description=(
            "숙달 상태 라벨('초보'/'발전 중'/'숙달') — `mastery_to_level`(L4)로 bkt_mastery를 "
            "변환(MOB-10). bkt_mastery가 null(미측정)이면 라벨도 null — 클라는 원시 확률 대신 "
            "이 라벨만 노출한다(전역 UI 불변식 #1: 표현≠의미, 서열 신호 방지)."
        ),
    )


# slice 26: 진단 필터·상한 — "주의 필요 개념 대시보드" 질의(전 개념 반환은 페이로드 과대).
# agreement 다중 OR(예: irt_higher·bkt_higher만=불일치 개념)·limit는 *약점 먼저* 정렬 후 상위 N.
AgreementFilter = Annotated[
    list[Agreement] | None,
    Query(
        description=(
            "일치 신호 필터(agree·irt_higher·bkt_higher·insufficient). 반복 지정 시 OR. "
            "생략 시 전체(예: irt_higher·bkt_higher만 = 불일치 개념)."
        )
    ),
]
DiagnosisLimit = Annotated[
    int | None,
    Query(ge=1, le=200, description="약점(저신호) 먼저 정렬 후 상위 N개만. 생략 시 전체."),
]


async def _compute_concept_diagnosis(
    session: AsyncSession, user_id: uuid.UUID
) -> list[ConceptDiagnosisItem]:
    """개념별 BKT↔IRT 교차검증(L2 `compute_concept_diagnoses`)에 L4 코칭을 부착·반환.

    순수 진단(BKT+IRT 융합·agreement·약점 정렬)은 L2(slice 82 이관). 여기선 각 진단 신호에 L4
    메타인지 코칭 처방(`recommend_coaching`)을 부착해 응답 항목(ConceptDiagnosisItem)으로 만든다 —
    L2→L4 역의존 회피(코칭은 L5 후처리). `/diagnosis/concepts`(필터/상한)·`/diagnosis/summary`
    (집계)가 공유. 정렬·합집합은 L2가 수행.
    """
    diagnoses = await compute_concept_diagnoses(session, user_id)
    return [
        ConceptDiagnosisItem(
            **d.model_dump(),
            coaching=recommend_coaching(d.bkt_mastery, d.irt_theta),
            mastery_level=(mastery_to_level(d.bkt_mastery) if d.bkt_mastery is not None else None),
        )
        for d in diagnoses
    ]


@router.get(
    "/diagnosis/concepts",
    response_model=list[ConceptDiagnosisItem],
    summary="내 개념별 BKT↔IRT 교차검증(통합 약점 진단)",
)
async def get_my_concept_diagnosis(
    user: ConsentedUser,
    session: SessionDep,
    agreement: AgreementFilter = None,
    limit: DiagnosisLimit = None,
) -> list[ConceptDiagnosisItem]:
    """개념별 BKT 숙달(slice L2-5c)과 IRT 능력 θ(slice 18)를 *한 응답에 합쳐* 교차검증.

    두 학습자 모델(L2)이 같은 개념 축에서 *합의/불일치*를 드러낸다 — `agreement`로 "θ는 높은데
    BKT 숙달은 낮음(irt_higher·추측/BKT 지연)"·"BKT 숙달은 높은데 θ 낮음(bkt_higher·망각/고난도)"을
    표면화(진단 신뢰도·메타인지 코칭 입력). ① BKT 최신 숙달 스냅샷(DISTINCT ON)·② 개념별 채점
    풀이로 IRT θ(`estimate_ability`)·logistic 프록시. 둘 중 하나라도 있는 개념을 합집합으로 모아
    *약점(저신호) 먼저* 정렬. 각 개념에 L4 메타인지 코칭 처방(`recommend_coaching`·slice 20)을
    붙여 *무엇을 할지*(focus·발화)까지 노출 — L2 진단→L4 결정→L5 노출 풀 스택. user_id
    스코핑·읽기(마이그레이션 불필요). `?agreement`(다중 OR·예: 불일치만)·`?limit`(약점 상위 N)으로
    "주의 필요 개념" 질의 가능(slice 26). `mastery_level`(MOB-10)은 `bkt_mastery`를
    `mastery_to_level`(L4)로 변환한 학생 노출용 라벨 — 클라는 원시 확률 대신 이 라벨만
    렌더해야 한다(표현≠의미·서열 신호 방지).
    """
    items = await _compute_concept_diagnosis(session, user.user_id)
    # slice 26: agreement OR 필터 → limit(약점 먼저 정렬 후 상위 N). 둘 다 선택적(기본 전체).
    if agreement:
        wanted = set(agreement)
        items = [i for i in items if i.agreement in wanted]
    if limit is not None:
        items = items[:limit]
    return items


# ── slice L2-27: GET /v1/me/diagnosis/summary (진단 집계 — 대시보드 헤더) ──────────
class ConceptDiagnosisSummary(BaseModel):
    """`GET /v1/me/diagnosis/summary` 응답 — 개념 진단 집계."""

    total_concepts: int = Field(description="진단 신호(BKT 또는 IRT)가 있는 개념 수.")
    agree: int = Field(description="BKT↔IRT 합의 개념 수.")
    irt_higher: int = Field(description="θ는 높은데 BKT 낮음(추측/지연) 개념 수.")
    bkt_higher: int = Field(description="BKT는 높은데 θ 낮음(망각/고난도) 개념 수.")
    insufficient: int = Field(description="한쪽 신호만(교차검증 불가) 개념 수.")
    attention_count: int = Field(description="주의 필요(불일치=irt_higher+bkt_higher) 개념 수.")
    weakest_concept_id: uuid.UUID | None = Field(
        default=None, description="가장 약한(저신호) 개념 id. 진단 개념 없으면 null."
    )
    weakest_concept_name: str | None = Field(
        default=None, description="가장 약한 개념명(orphan·미진단이면 null)."
    )


@router.get(
    "/diagnosis/summary",
    response_model=ConceptDiagnosisSummary,
    summary="내 개념 진단 집계(대시보드 헤더 — 주의 필요 수·최약점)",
)
async def get_my_diagnosis_summary(
    user: ConsentedUser,
    session: SessionDep,
) -> ConceptDiagnosisSummary:
    """개념별 진단(`/diagnosis/concepts`)을 *집계* — 대시보드 헤더용 한 줄 요약.

    일치 신호별 개념 수·*주의 필요*(불일치=irt_higher+bkt_higher) 수·*가장 약한* 개념(약점
    정렬 1위)을 반환. 진단 개념이 없으면 모두 0·weakest는 null. 공유 계산(`_compute_concept_
    diagnosis`)을 재사용(개념 리스트와 동일 데이터의 집계 뷰). user_id 스코핑·읽기.
    """
    items = await _compute_concept_diagnosis(session, user.user_id)
    counts = {"agree": 0, "irt_higher": 0, "bkt_higher": 0, "insufficient": 0}
    for i in items:
        counts[i.agreement] += 1
    weakest = items[0] if items else None  # 이미 약점 먼저 정렬됨
    return ConceptDiagnosisSummary(
        total_concepts=len(items),
        agree=counts["agree"],
        irt_higher=counts["irt_higher"],
        bkt_higher=counts["bkt_higher"],
        insufficient=counts["insufficient"],
        attention_count=counts["irt_higher"] + counts["bkt_higher"],
        weakest_concept_id=weakest.concept_id if weakest else None,
        weakest_concept_name=weakest.concept_name if weakest else None,
    )


# ── EOS-10: GET /v1/me/learner-state (LearnerState 단일 조회 표면) ────────────────
# 계획서 300 §12가 요구한 12종 중 유일하게 대응물이 없던 축. 기존에 학습 상태를 알려면 조각
# 3개(`/mastery/current`·`/ability`·`/diagnosis/summary`)를 각각 불러 클라이언트가 합쳐야
# 했고, 그 "합치는 규칙"이 서버 밖에 있어 소비처마다 달라질 수 있었다. 이 표면이 L2 조립기
# (`l2/learner_state.py::get_state`)를 그대로 노출해 합성 규칙을 서버 안에 둔다.
#
# **L5는 표면일 뿐이다** — 조립·계산은 전부 L2가 소유하고 여기서는 user_id 스코핑과 직렬화만
# 한다(다른 /me GET과 동일 규약·읽기 전용·마이그레이션 0).


@router.get(
    "/learner-state",
    response_model=LearnerState,
    summary="내 학습 상태 단일 조회(LearnerState — 숙달·능력·오개념·스킬을 한 번에)",
)
async def get_my_learner_state(
    user: ConsentedUser,
    session: SessionDep,
) -> LearnerState:
    """본인의 `LearnerState`를 **한 호출로** 반환 — 조각 3개를 각각 부르던 것의 합성 표면.

    담는 것: 개념 숙달(BKT)·전과목 및 개념별 능력(IRT θ)·활성 오개념·약/강 개념·스킬 숙달
    (행동 축)·학년·목표. 전부 **기존 좌석 재사용**이며 이 엔드포인트가 새로 계산하는 값은 없다.

    **`origins`를 함께 읽어라.** 값이 비어 있는 것은 두 가지 뜻일 수 있고 이 응답은 그것을
    구별해 말한다 — `no_data`는 이 학생의 이력이 없다는 뜻(풀이가 쌓이면 채워진다)이고,
    `no_producer`는 저장소에 생산자가 없다는 뜻(학생이 무엇을 해도 채워지지 않는다)이다.
    현재 `curriculum_id`·`current_objective_id` 둘이 후자이며, 각 필드 description에 그
    실측 근거가 있다. `origins`에서 `status == "measured"`인 비율이 곧 **이 조립이 실제로
    작동한 비율**이다(CLAUDE.md "작동한 비율" 원칙).

    **PII 주의**: `goals`는 목표 등급·점수·대학을 담는다. 이 표면은 학생 **본인**에게만
    응답하며(`ConsentedUser` + user_id 스코핑), 여기서 나온 값을 학생 대면 프롬프트에 그대로
    넣는 것은 별개로 금지다(`LearnerState.goals` description 참조).
    """
    return await get_state(session, user.user_id)


# ── 원자그래프 소비 슬2: GET /v1/me/weak-concepts (약개념 추천 — 진단 약점 + code 메타 enrich) ──
# L2 약점 진단(`recommend_weak_concepts`·BKT/IRT 융합·약점 정렬·약점 필터)에 `atom_node`(code)
# 안전 그래프 메타(name_ko·subject_area·review_status)를 enrich해 "지금 무엇을 복습할지" 후보를
# 돌려준다(S0-4d·runtime truth=원자·`domain` 응답 필드는 이제 원자 subject_area 값). *학생 직접
# 노출이 아니라* 내부 조회 좌석(소비 슬 노출 계약과 일관 — 안전 필드만·본문 0). 진단·enrich·
# 게이팅 로직은 L2 좌석이 소유(L5는 표면·user_id 스코핑·읽기 전용·마이그레이션 0).
WeakLimit = Annotated[int, Query(ge=1, le=50, description="약점(저신호) 먼저 정렬 후 상위 N개만.")]
WeakThreshold = Annotated[
    float,
    Query(
        ge=0.0,
        le=1.0,
        description="이 숙달 미만(비교 가능한 두 신호 중 최저값 기준)인 개념만 약점으로 추천.",
    ),
]
WeakReviewedOnly = Annotated[
    bool,
    Query(
        description=(
            "검수 게이팅. false(기본)=recall 보존(pending·메타 미적재 개념도 노출). true="
            "review_status='reviewed'인 개념만(메타 없어 확인 불가인 code는 보수적 제외·필터)."
        ),
    ),
]


@router.get(
    "/weak-concepts",
    response_model=list[WeakConceptRecommendation],
    summary="내 약개념 추천(BKT/IRT 약점 + 개념그래프 안전 메타 enrich)",
)
async def get_my_weak_concepts(
    user: ConsentedUser,
    session: SessionDep,
    limit: WeakLimit = 10,
    threshold: WeakThreshold = 0.7,
    reviewed_only: WeakReviewedOnly = False,
) -> list[WeakConceptRecommendation]:
    """학습자 약점(BKT/IRT)을 식별해 원자그래프(`atom_node`·code) 안전 메타를 붙여 추천.

    L2 진단(`compute_concept_diagnoses`·BKT 최신 + IRT θ 융합·*약점 먼저* 정렬)을 재사용해
    약점(비교 가능한 두 신호 중 최저값 < `threshold`)인 개념만 거르고, 그 개념의 `concept_code`
    (=code)로 `atom_node`(PG 프로젝션·원자 메타 좌석) 안전 메타(name_ko·subject_area·review_status)
    를 *단일 IN 조회*로 enrich한다(S0-4d·runtime truth=원자·N+1 0·code 없거나 미적재면 None
    graceful). 응답 `domain` 필드는 계약 안정을 위해 이름을 유지하나 값은 원자 subject_area다.
    `reviewed_only=true`면 검수 안 된 개념을 *필터*(약점 정렬 유지)하고, `limit`로 상위 N만
    돌려준다. 진단·enrich·게이팅은 L2 좌석이 소유(`recommend_weak_concepts`)·user_id 스코핑·읽기
    전용.

    **노출 계약(CLAUDE.md)**: 학생 직접 노출이 아니라 *조회 좌석*(소비 슬과 일관)이다. enrich
    되는 건 안전 표시·게이팅 필드뿐 — **본문(description·formal_definition·core_proposition) 0**
    (atom_node에 본문 컬럼 자체가 없음·redaction). 우열 매기기·정답 빠르게 등 금기 표현 0.
    """
    return await recommend_weak_concepts(
        session,
        user.user_id,
        limit=limit,
        mastery_threshold=threshold,
        reviewed_only=reviewed_only,
    )


# ── S4-18: GET /v1/me/review-queue — BKT 망각 역산 기반 복습 우선순위 큐 ──
@router.get(
    "/review-queue",
    response_model=ReviewQueue,
    summary="내 복습 우선순위 큐(BKT 망각 역산 — decayed_mastery 오름차순)",
)
async def get_my_review_queue(
    user: ConsentedUser,
    session: SessionDep,
) -> ReviewQueue:
    """BKT 최신 숙달에 조회시점 망각 감쇠(`apply_forgetting`)를 적용해 복습이 급한 개념부터 정렬.

    저장 컬럼(`next_review_at` 등)·마이그레이션 없이 매 호출 순수 재계산한다(`l2/review_queue.py`
    모듈 docstring 참조). λ는 문헌 전형값(`calibrated=False`로 정직 표기) — 개인·개념별 EM 적합은
    후속. 관측 이력이 전혀 없는 개념은 자동으로 제외된다(측정 안 됨 ≠ 복습 불필요).
    """
    return await fetch_review_queue(session, user.user_id)


# ── S4-18: GET /v1/me/target-progress — 목표(D-day·목표 등급/점수·성취기준 커버리지) ──
@router.get(
    "/target-progress",
    response_model=TargetProgress,
    summary="내 목표 진행 상황(D-day·목표 echo·성취기준 커버리지 — 예측 필드 없음)",
)
async def get_my_target_progress(
    user: ConsentedUser,
    session: SessionDep,
) -> TargetProgress:
    """`target_exam_date`/`target_grade`/`target_score`의 첫 조회 좌석(지금까지 쓰기 전용이었음).

    목표 등급·목표 점수는 학생이 입력한 값을 *그대로 echo*할 뿐 예측하지 않는다(CLAUDE.md
    "학생을 우열로 매기지 않는다" — `l2/target_progress.py` 모듈 docstring 참조). 성취기준
    커버리지는 v0 정책('2022 개정' × '고등학교' 전체를 단일 스코프)이며, `school_type`이 없는
    학생은 스코프 계산 불가로 관련 필드가 전부 null이다.
    """
    return await get_target_progress(session, user.user_id)


# ── 원자그래프 소비 선수 슬1: GET /v1/me/weak-concepts/{concept_id}/prerequisites ──
# 약개념 C의 *막힌 선수개념* 추천 — concept_edge(to==C·PREREQUISITE) traversal로 선수를 찾고,
# 그 중 학습자가 약한(막힌) 것을 mastery·atom_node 안전 메타와 함께 돌려준다(선수 복습 우선·S0-4d).
# 후행 개념이 안 되는 *근본 원인*이 선수 결손일 수 있으므로 "먼저 복습할 선수"를 가린다(LTHC).
# traversal·약점 필터·enrich·게이팅 로직은 L2 좌석이 소유(L5는 표면·user_id 스코핑·읽기 전용).
WeakOnly = Annotated[
    bool,
    Query(
        description=(
            "true(기본)=막힌(약한·숙달 미만) 선수만(측정 없는 선수 제외). false=모든 선수"
            "(약점 무관·미측정 포함)."
        ),
    ),
]
# 다단계(multi-hop) 선수 traversal 깊이 — 1=직접 선수만(기본·후방 호환)·2~상한=선수의 선수…까지.
# 선수 그래프는 DAG 보장(data-pipeline validate.py가 prerequisite_cycle hard error)이라 재귀는
# 자연 종료하나, 비용·노이즈를 막으려 상한으로 bound한다. 상한은 L2 단일 출처
# `MAX_PREREQUISITE_DEPTH`를 공유한다(매직 넘버 중복 제거·Q10-⑧).
MaxDepth = Annotated[
    int,
    Query(
        ge=1,
        le=MAX_PREREQUISITE_DEPTH,
        description=(
            "선수 traversal 최대 깊이 — 1=직접 선수만(기본)·2 이상=다단계 선수(선수의 선수…). "
            f"DAG 보장이라 종료, 비용·노이즈 상한 {MAX_PREREQUISITE_DEPTH}."
        ),
    ),
]


@router.get(
    "/weak-concepts/{concept_id}/prerequisites",
    response_model=list[PrerequisiteGap],
    summary="약개념의 막힌 선수개념 추천(선수 traversal + BKT/IRT 약점 + 안전 메타 enrich)",
)
async def get_my_prerequisite_gaps(
    concept_id: uuid.UUID,
    user: ConsentedUser,
    session: SessionDep,
    threshold: WeakThreshold = 0.7,
    reviewed_only: WeakReviewedOnly = False,
    weak_only: WeakOnly = True,
    max_depth: MaxDepth = 1,
) -> list[PrerequisiteGap]:
    """약개념 C(`concept_id`)의 선수개념 중 *막힌*(약한) 것을 골라 "먼저 복습할 선수"로 추천.

    `concept_edge`에서 `to_concept_id == concept_id AND edge_type == PREREQUISITE`인 행의
    `from_concept_id`(선수)들을 traversal하고(방향: from은 to의 선수), 각 선수의 BKT/IRT 숙달을
    L2 진단(`compute_concept_diagnoses`)으로 lookup해 `weak_only=true`(기본)면 막힌(숙달 <
    `threshold`) 선수만 남긴다. 선수의 `concept_code`(=code)로 `atom_node` 안전 메타(name_ko·
    subject_area·review_status)를 *단일 IN 조회*로 enrich하고(S0-4d·runtime truth=원자·N+1 0·미적재
    None graceful·응답 `domain` 필드는 계약 안정상 이름 유지·값은 원자 subject_area),
    `reviewed_only=true`면 검수 안 된 선수를 *필터*한다.

    **다단계(multi-hop) traversal**: `max_depth=1`(기본)이면 직접 선수만(기존 1-hop·후방 호환)·
    `max_depth=2~5`면 "선수의 선수…"까지 재귀 CTE로 따라간다 — 후행 개념이 안 되는 *근본 결손*이
    여러 단계 아래일 수 있기 때문(LTHC). 응답 각 항목의 `depth`(1=직접 선수·2=선수의 선수…)로
    선수 거리를 노출한다(그래프 구조 메타·안전). 같은 선수가 여러 경로로 닿으면 가장 가까운(MIN)
    거리만 1건. 선수 그래프는 DAG 보장이라 재귀는 종료하며 `max_depth`로 방어적 bound.

    정렬은 weakness 오름차순(가장 약한 선수=root blocker 먼저)·동률은 **depth 오름차순**(가까운
    선수 먼저·더 직접 실행 가능)·그 다음 선수관계 강도(edge_strength) 내림차순. traversal·약점·
    enrich·게이팅은 L2 좌석이 소유(`recommend_prerequisite_gaps`)·user_id 스코핑·읽기 전용.

    **노출 계약(CLAUDE.md)**: 학생 직접 노출이 아니라 *조회 좌석*(약개념 추천과 일관)이다. enrich
    되는 건 안전 표시·게이팅 필드뿐 — **본문(description·formal_definition·core_proposition) 0**
    (atom_node·PrerequisiteGap 스키마에 컬럼/슬롯 자체가 없음·redaction). 우열 매기기·정답 빠르게
    등 금기 0.
    """
    return await recommend_prerequisite_gaps(
        session,
        user.user_id,
        concept_id,
        mastery_threshold=threshold,
        reviewed_only=reviewed_only,
        weak_only=weak_only,
        max_depth=max_depth,
    )


# ── L4 코칭 결선: GET /v1/me/weak-concepts/{concept_id}/coaching (선수 차단 우선 코칭) ──
# 첫 L4→L2 결선이다(L_n→L_{n-1} 허용). L2 선수 추천(막힌 선수)이 있으면 후행을 바로 코칭하지
# 않고 *선수 복습을 먼저 권하는* L4 코칭(prerequisite_review)을 돌려준다(LTHC·기초 우선). 막힌
# 선수가 없으면 일반 메타인지 코칭(`recommend_coaching`·BKT/IRT)으로 fallback한다. 오케스트레이션
# (L2 fetch + L4 decide 배선)은 L5(여기)·순수 결정은 L4가 소유(역방향 의존 0).
@router.get(
    "/weak-concepts/{concept_id}/coaching",
    response_model=CoachingTrigger,
    summary="약개념 코칭 결정(막힌 선수 있으면 선수 복습 우선·없으면 메타인지 코칭)",
)
async def get_my_concept_coaching(
    concept_id: uuid.UUID,
    user: ConsentedUser,
    session: SessionDep,
    threshold: WeakThreshold = 0.7,
    max_depth: MaxDepth = 1,
) -> CoachingTrigger:
    """약개념 C(`concept_id`)에 대한 L4 코칭 결정 — **선수 차단 우선·없으면 메타인지 코칭**.

    첫 L4→L2 결선(L_n→L_{n-1} 허용). 오케스트레이션:
      ① **L2 fetch** — `recommend_prerequisite_gaps(weak_only=True)`로 C의 *막힌 선수개념*을
         조회한다(weakness asc 정렬·`gaps[0]`=top blocker).
      ② **선수 차단 우선** — `recommend_prerequisite_coaching(gaps)`이 *막힌 선수가 있으면*
         `prerequisite_review` 코칭(선수부터 복습 권유)을 돌려준다. 이걸 *최우선*으로 반환한다 —
         후행을 바로 코칭하면 비계가 허공에 뜨기 때문(LTHC·기초 우선·CLAUDE.md 교수학 #1·#3).
      ③ **fallback(막힌 선수 없음)** — `compute_concept_diagnoses`에서 이 개념의 BKT/IRT 진단을
         찾아 일반 메타인지 코칭(`recommend_coaching`)으로 넘어간다(verify/foundation/advance 등).
         진단이 아예 없으면 `recommend_coaching(None, None)`(→ diagnose·추가 진단 권유).

    `threshold`(막힘 판정 숙달 임계)·`max_depth`(다단계 선수 traversal 깊이)는 선수 슬1과 동일
    재사용. user_id 스코핑·읽기 전용(마이그레이션 0). L4 순수 결정은 `recommend_prerequisite_
    coaching`·`recommend_coaching`이 소유하고, 여기(L5)는 L2 fetch + L4 decide *배선*만 한다.

    **노출 계약(CLAUDE.md)**: 학생 직접 노출이 아니라 *조회 좌석*(소비 슬 일관)이다. rationale·
    prompt는 *자체 작성 코칭 문구*이며 개념 *본문(description·formal_definition·evidence)은 0* —
    선수 이름(name_ko·concept_name·안전 표시 필드)만 삽입된다(`PrerequisiteGap`에 본문 슬롯 없음).
    학생 prompt는 격려·메타인지 유도이며 막힌 선수를 *비난하지 않는다*(부정 강화·우열·"정답 빠르게"
    금지·바로 정답 제공 아님).
    """
    # ① L2 fetch — 막힌 선수(weak_only=True·weakness asc 정렬). ② 선수 차단 *최우선*.
    gaps = await recommend_prerequisite_gaps(
        session,
        user.user_id,
        concept_id,
        mastery_threshold=threshold,
        weak_only=True,
        max_depth=max_depth,
    )
    trigger = recommend_prerequisite_coaching(gaps)
    if trigger is not None:
        return trigger  # 막힌 선수 있음 → 선수 복습 우선(후행 코칭 보류).

    # ③ fallback — 막힌 선수 없음 → 이 개념 자체의 BKT/IRT로 일반 메타인지 코칭.
    diagnoses = await compute_concept_diagnoses(session, user.user_id)
    diag = next((d for d in diagnoses if d.concept_id == concept_id), None)
    if diag is None:
        return recommend_coaching(None, None)  # 진단 없음 → diagnose(추가 진단 권유).
    return recommend_coaching(diag.bkt_mastery, diag.irt_theta)


# ── 개념그래프 소비 학습경로 슬: GET /v1/me/weak-concepts/{concept_id}/learning-path ──
# 선수 슬1(prerequisites)이 "어떤 선수가 막혔나"를 weakness 정렬로 *골랐다면*, 이 슬은 그 막힌
# 선수들 *사이의 선수 의존*을 Kahn 위상정렬해 "무엇부터 복습해야 하나 — 근본 선수 먼저, 그 위에
# 쌓이는 말단 나중"의 학습 *순서*를 돌려준다(LTHC 기초 우선의 기계적 구현). prerequisites 미러:
# query 4종·게이팅·user_id 스코핑을 그대로 답습하되, 응답이 *순서화된 학습 경로*다. L2 fetch +
# L2 위상정렬 *배선*만 L5(여기)·순수 정렬·내부엣지 조회는 L2(`build_learning_path`)가 소유.
@router.get(
    "/weak-concepts/{concept_id}/learning-path",
    response_model=LearningPath,
    summary="약개념의 막힌 선수개념 학습 경로(선수 위상정렬·근본→말단 순서)",
)
async def get_my_learning_path(
    concept_id: uuid.UUID,
    user: ConsentedUser,
    session: SessionDep,
    threshold: WeakThreshold = 0.7,
    reviewed_only: WeakReviewedOnly = False,
    weak_only: WeakOnly = True,
    max_depth: MaxDepth = 1,
) -> LearningPath:
    """약개념 C(`concept_id`)의 *막힌 선수개념들*을 위상정렬한 **학습 순서**(근본 먼저)로 반환.

    선수 슬1(`prerequisites`)의 미러다 — 같은 query(`threshold`·`reviewed_only`·`weak_only`·
    `max_depth`)·게이팅·user_id 스코핑으로 막힌 선수를 고르지만, 응답이 *순서화된 경로*다.
    오케스트레이션:
      ① **L2 fetch** — `recommend_prerequisite_gaps`로 C의 막힌 선수개념(weakness asc)을
         조회한다(`prerequisites`와 동일 인자).
      ② **L2 위상정렬** — `build_learning_path(session, gaps)`가 그 막힌 선수 집합 *내부*의
         직접 선수 엣지를 조회해 Kahn 위상정렬한다 — in-degree 0(선수 의존 없는 *근본*)을 먼저
         방출하고 그 위에 쌓이는 선수를 뒤에 둔다. **제약 엣지가 있을 때만 추천의 depth/
         strength 정렬과 달라진다**: 두 선수가 둘 다 직접 선수(depth=1)여도 A가 B의 선수면
         A를 먼저 다져야 한다(LTHC). 다만 기본값(`max_depth=1`)에서는 그런 제약 엣지가 0인
         사례가 **96.4%**이고, 그때는 실질적으로 `_tiebreak`(weakness 등)만으로 정렬된다 —
         응답의 `ordering_basis`(`"topological"|"tiebreak_only"|"empty"`)와
         `ordering_edge_count`가 이 구분을 정직하게 노출한다(`PATH-02`). 사이클(부분 적재
         방어, 실발생 0건)은 잔여로 정직하게 표시(`has_cycle`·`is_cycle_residual`).

    L2 fetch + L2 정렬 *배선*만 여기(L5)가 소유하고(신규 로직 0), 순수 위상정렬·내부엣지 조회는
    L2(`build_learning_path`·`order_learning_path`)가 소유한다. user_id 스코핑·읽기 전용·
    마이그레이션 0.

    **노출 계약(CLAUDE.md)**: 학생 직접 노출이 아니라 *조회·순서화 좌석*(소비 슬 일관)이다.
    `LearningStep`은 안전 표시·구조 메타(concept_code·concept_name·weakness·depth·
    edge_strength·position)만 담고 — **본문(description·formal_definition·intuitive_
    explanation) 슬롯 자체가 없다**(frozen 스키마·redaction). 우열 매기기·정답 빠르게 등 금기 0.
    """
    gaps = await recommend_prerequisite_gaps(
        session,
        user.user_id,
        concept_id,
        mastery_threshold=threshold,
        reviewed_only=reviewed_only,
        weak_only=weak_only,
        max_depth=max_depth,
    )
    return await build_learning_path(session, gaps)


# ── slice L2-12: GET /v1/me/next-problem (적응형 출제 — IRT 정보량 최대 미응답 문항) ──
#
# **EOS-19: 후보 조회·가중·θ 추정 배선은 이 파일에 없다.** 전부
# `l2.next_problem_selection`으로 *바이트 동일하게* 이동했고(이유: `l2`의 추천 정책이 쓰려면
# `l2 → api` 역방향 import가 생긴다 — CLAUDE.md 7계층 경계), 아래 별칭은 기존 참조 경로
# (`whymath_backend.api.me.candidate_pool_conditions` 등)를 **끊지 않기 위한 재노출**이다.
# `ops/repeat_recommendation_report.py`와 기존 테스트가 그 경로로 참조한다.
_CANDIDATE_POOL_SIZE = CANDIDATE_POOL_SIZE
_TARGET_SE = TARGET_SE
_AttemptHistoryState = AttemptHistoryState
_load_attempt_history_state = load_attempt_history_state
_load_weak_concept_weights = load_weak_concept_weights
_last_incorrect_problem_id = last_incorrect_problem_id
_load_sibling_ids = load_sibling_ids
_sibling_weights = sibling_weights
_combine_weights = combine_weights
# 공개 이름 둘은 별칭 없이 그대로 재노출된다(`ops/repeat_recommendation_report.py`·
# `tests/backend/api/test_problem_quarantine_serving.py`가 `api.me.candidate_pool_conditions`로
# 참조한다). 위 import에 붙인 린트 억제 주석이 그 재노출 의도를 명시한다 — 이 파일 안에서는 쓰이지
# 않지만 *지워지면 안 되는* 이름이라는 뜻이다.

# slice 17: ?prioritize_weak_concepts — 기본 false(slice 12~15 동작 보존). true면 BKT 약점
# 개념 우선(개념 숙달 스냅샷·후보 문항 개념 매핑을 추가 조회해 가중).
PrioritizeWeakConcepts = Annotated[
    bool,
    Query(description="true면 BKT 약점 개념(저숙달) 우선 출제(정보량×약점 가중). 기본 false."),
]
# S2-06: ?mode=suneung — 수능 적응 추천(L6 게이팅 × L2 IRT CAT). 미지정(None)이면 기존
# 기본 CAT(슬라이스 12~17) 경로 그대로(회귀 0). 값 공간은 Literal로 닫는다(오타 → 422).
NextProblemMode = Annotated[
    Literal["suneung"] | None,
    Query(description="응용 모드. 'suneung'=수능 적응 추천(L6 게이팅×IRT CAT). 미지정=기본 CAT."),
]
# REC-04: ?purpose=diagnosis|learning — 진단(현행 정보량 최대, 기본·회귀 0) vs 학습(목표
# 성공률 밴드 70~85% 가중, l2.learning_band_weight). 근원 문제: Rasch 정보량 최대는 P≈0.5를
# 지향해 학생이 절반을 틀리도록 설계된 출제가 학습 세션에도 그대로 적용된다(교수학 금기 —
# 부정적 피드백 정서 강화 금지). mode(suneung)와 직교 축 — 둘 다 지정 가능.
NextProblemPurpose = Annotated[
    Literal["diagnosis", "learning"],
    Query(
        description=(
            "출제 목적. 'diagnosis'(기본)=정보량 최대(측정 정밀도, 회귀 0). "
            "'learning'=목표 성공률 밴드(70~85%, 문헌값·미보정) 가중 — 응답의 "
            "band_calibrated=false로 미보정 상태를 표시한다."
        )
    ),
]
# S2-06: 수능 모드 대상 페르소나 — L6 게이팅(`is_suneung_eligible`)의 판정 축. mode=suneung
# 에서만 쓰인다(기본 CAT 경로는 무시). 기본 A_일반고고3(MVP 정시 정면 대상 — L6 기본과 동일).
SuneungPersona = Annotated[
    Persona,
    Query(description="수능 모드 대상 페르소나(mode=suneung에서만 사용). 기본 A_일반고고3."),
]
# S3-03: GET /me/harness-metrics?mode=suneung — 응용 모드 스코프. 설정 시 attempt_event 기반
# 지표(①⑤⑧)를 그 mode 태그가 실린 이벤트만으로 집계(수능 세션 측정). 미지정이면 전 mode 포함
# (기존 동작 불변). 값 공간은 next-problem과 동일 Literal로 닫는다(오타 → 422).
HarnessMetricsMode = Annotated[
    Literal["suneung"] | None,
    Query(
        description=(
            "응용 모드 스코프. 'suneung'이면 attempt_event 기반 지표(verify·도움 감소·도달 깊이)를 "
            "수능 세션 이벤트만으로 필터. 미지정=전 mode(기존 동작). 완전한 mode별 집계는 후속."
        )
    ),
]

# S4-14: CAT 형제 후보 필터 — problem_relation(변형·유사) 계보를 소비하는 첫 소비처(승격 없는
# 영속 금지 원칙 — populate.py가 채운 관계를 여기서 처음 읽는다). 직전 오답 문항의 "형제"
# (같은 뼈대 변형·인접 유사 문항)를 배제(같은 문제 반복 회피)하거나 가중 우대(약점 재출제)한다.
SiblingFilter = Annotated[
    Literal["exclude", "include"] | None,
    Query(
        description=(
            "직전 오답 문항의 형제(problem_relation 변형·유사) 후보 처리. 'exclude'=후보에서 "
            "배제(같은 뼈대 연속 출제 회피), 'include'=정보량에 가중해 우대(오답 문항 변형 "
            "재출제). 미지정(기본)=기존 동작 그대로(회귀 0 — 형제 조회 자체를 생략)."
        )
    ),
]


class NextProblemResponse(BaseModel):
    """`GET /v1/me/next-problem` 응답 — IRT CAT(적응형 출제) 추천 + 측정 정밀도."""

    problem_id: uuid.UUID | None = Field(
        default=None,
        description="추천 문항 id. 후보(미응답·난이도 라벨 보유)가 없으면 null.",
    )
    theta: float = Field(description="추천에 쓰인 현재 능력 추정 θ(logit). 응답 없으면 0.")
    difficulty: float | None = Field(
        default=None,
        description="추천 문항의 difficulty_overall(전문가 1~5). 없으면 null.",
    )
    standard_error: float | None = Field(
        default=None,
        description="현재 θ 추정의 표준오차(응답한 문항 기준·slice 13). 응답 없으면 null.",
    )
    measurement_sufficient: bool = Field(
        default=False,
        description=f"SE가 목표({_TARGET_SE}) 이하면 True — 적응 검사 중단 권고(CAT 중단 규칙).",
    )
    # ── REC-01: 응답 정직 표기(추천 도달 관측) — 기존 5필드 불변·아래 4필드는 신규 추가 ──
    weight_axes_applied: list[str] = Field(
        default_factory=list,
        description=(
            "이번 응답에 실제로 적용된 가중 축 이름 목록(예: 'weak_concept'·'suneung_priority'). "
            "prioritize_weak_concepts=false(기본)면 'weak_concept' 미포함 — 빈 리스트는 "
            "'적용 안 됨'이지 신호 없음이 아니다. 'weak_concept'이 있어도 실제 가중 신호가 "
            "있었는지는 weak_concept_signal_count로 별도 확인한다."
        ),
    )
    candidate_pool_size: int = Field(
        default=0,
        description=(
            "이번 요청의 실제 후보 풀 크기(θ 근방 SQL 선별 후 개수, 수능 모드는 L6 게이팅 전)."
        ),
    )
    weak_concept_signal_count: int = Field(
        default=0,
        description=(
            "후보 중 BKT 숙달 기록이 있어 약점 가중치가 1.0이 아니게 된 문항 수. "
            "prioritize_weak_concepts=false거나 후보가 없으면 0 — 'weak_concept' 축이 "
            "weight_axes_applied에 있는데 이 값이 0이면 '적용했으나 신호 없음'(콜드스타트 등)."
        ),
    )
    candidate_zero_reason: str | None = Field(
        default=None,
        description=(
            "problem_id가 null일 때만 채워지는 사유 코드. "
            f"'{CANDIDATE_ZERO_NO_POOL}'=SQL 후보 조회 자체가 0건, "
            f"'{CANDIDATE_ZERO_ALL_GATED_INELIGIBLE}'=후보는 있었으나 수능 모드 L6 게이팅이 "
            "전부 부적격 처리(기본 CAT 경로에서는 발생하지 않음). problem_id가 있으면 null."
        ),
    )
    band_calibrated: bool | None = Field(
        default=None,
        description=(
            "REC-04: purpose=learning일 때만 False(문헌값 70~85%·실측 미보정 — S4-15 보정 "
            "대기). purpose=diagnosis(기본)에서는 밴드 자체가 적용되지 않으므로 null."
        ),
    )
    action: RecommendationAction = Field(
        description=(
            "EOS-19: **무엇을 하라는 추천인가** — `reason.type`에서 파생된 학습 행위"
            "(practice_prerequisite·practice_current·advance_next·diagnose·none). 근거와 "
            "어긋난 값은 `Recommendation` 생성 단계에서 거부되므로 이 필드는 reason과 "
            "항상 정합이다."
        ),
    )
    target_concept: uuid.UUID | None = Field(
        default=None,
        description=(
            "EOS-19: 학생이 **다음에 다뤄야 할 개념**. 선수개념이 막혔으면"
            "(action=practice_prerequisite) 개념 그래프에서 찾은 *막힌 선수개념*이고, 그 외에는 "
            "선택된 문항의 대표 개념이다(=reason.concept_id). 측정된 선수가 없거나 문항에 개념 "
            "매핑이 없으면 null — 없는 근거를 지어내지 않는다."
        ),
    )
    reason: RecommendationReason = Field(
        description=(
            "EOS-14: **왜 이 문항인가** — 선택된 문항의 대표 개념·그 개념의 실측 숙달로 판정한 "
            "추천 근거. 위 5필드(weight_axes_applied·candidate_pool_size·"
            "weak_concept_signal_count·candidate_zero_reason·band_calibrated)가 *추천기가 "
            "어떻게 돌았나*의 관측 메타라면, 이 필드는 *선택된 문항의 근거*다 — 둘은 다른 질문에 "
            "답하므로 합치지 않는다. `problem_id`가 null이어도 비지 않는다(type=no_candidate)."
        ),
    )


@router.get(
    "/next-problem",
    response_model=NextProblemResponse,
    summary="적응형 다음 문항 추천(IRT 정보량 최대 — 미응답 문항)",
)
async def recommend_next_problem(
    user: ConsentedUser,
    session: SessionDep,
    prioritize_weak_concepts: PrioritizeWeakConcepts = False,
    mode: NextProblemMode = None,
    persona: SuneungPersona = Persona.A_일반고고3,
    purpose: NextProblemPurpose = "diagnosis",
    sibling_filter: SiblingFilter = None,
) -> NextProblemResponse:
    """본인 능력 θ에 *정보량 최대*인 *미응답* 문항을 추천 — IRT CAT(적응형 출제) 루프.

    **EOS-19: 이 핸들러는 더 이상 문항을 고르지 않는다.** 하는 일은 넷뿐이다 —
      ① 학습자 상태를 단일 조회 표면(`l2.learner_state.get_state`)에서 읽고,
      ② 쿼리 파라미터를 `LearningContext`(요청 상황)로 옮기고,
      ③ `mode`에 맞는 **정책**(`RecommendationPolicy` 구현체)을 골라
         `policy(learner_state, learning_context)`로 부른 뒤,
      ④ 돌아온 `Recommendation`을 HTTP 응답으로 옮긴다(+ 처치 기록·commit).

    선택 알고리즘은 정책이 소유한다: 기본 CAT은 `l2.recommendation_policy.
    CatRecommendationPolicy`, 수능 모드는 `api._next_problem_policy.SuneungRecommendationPolicy`
    (두 계층 합성이 필요해 위치가 다른 이유는 그 모듈 docstring 참조). 두 정책의 알고리즘은
    전환 전 이 함수 안에 있던 것과 **같다** — 배치만 바뀌었고 추천 결과는 바뀌지 않는다
    (EOS-19 acceptance ④).

    정책이 무엇을 하는지(θ 추정·후보 조회·약점/밴드/형제 가중·CAT 중단 규칙·수능 L6 게이팅)는
    각 정책 모듈의 docstring이 정본이다. 여기에 다시 적으면 알고리즘이 바뀔 때 두 설명이
    갈라진다.

    응답 계약은 전환 전과 동일하다(회귀 0): `problem_id`·`theta`·`difficulty`·`standard_error`·
    `measurement_sufficient` + REC-01/04 정직 표기 5필드 + EOS-14 `reason`. **신규 2필드**는
    `action`(이 추천이 요구하는 학습 행위)과 `target_concept`(다음에 다뤄야 할 개념)이며, 둘 다
    `reason`에서 파생되거나 개념 그래프에서 조회된 값이라 선택 결과를 바꾸지 않는다.

    REC-03/REC-11: `problem_id`가 확정되면(null이 아니면) `evidence_event`에 처치 1건을 기록한다
    (가짜 처치 금지 — null 응답은 기록하지 않음). 그 기록에는 후보 점수(`candidates`)와
    `policy_version`이 함께 실린다(소급 평가 재료).
    """
    # ① 학습자 상태 — EOS-10이 세운 단일 조회 표면. 핸들러가 θ·숙달·약점을 따로 재계산하지
    #    않는다(전환 전에는 그랬다). 정책이 이것을 *입력으로* 받는 것이 EOS-19의 요지다.
    learner_state = await get_state(session, user.user_id)
    # ② 요청 상황 — 쿼리 파라미터를 계약 타입으로 옮긴다(전송 관심사는 넣지 않는다).
    learning_context = LearningContext(
        purpose=purpose,
        mode=mode,
        persona=persona.value if mode == "suneung" else None,
        prioritize_weak_concepts=prioritize_weak_concepts,
        requested_at=datetime.now(UTC),
    )
    # ③ 정책 선택 — `mode`가 정책을 고르는 유일한 축이다. 두 정책은 같은 Protocol을 구현하므로
    #    아래 호출부는 어느 쪽인지 모른다(교체 가능성이 타입으로 표현된 자리).
    policy: NextProblemPolicy = (
        SuneungRecommendationPolicy(session, persona=persona, sibling_filter=sibling_filter)
        if mode == "suneung"
        else CatRecommendationPolicy(session, sibling_filter=sibling_filter)
    )
    outcome = await policy(learner_state, learning_context)

    # ④ 처치 기록 — 학생에게 실제로 반환되는 추천만 기록한다(가짜 처치 금지).
    if outcome.problem_id is not None:
        await record_recommendation_treatment(
            session,
            problem_id=outcome.problem_id,
            theta=outcome.theta,
            pool_size=outcome.candidate_pool_size,
            applied_weights=outcome.applied_weights,
            mode=mode,
            candidates=outcome.candidate_scores,
            policy_version=outcome.policy_version,
            reason=outcome.reason,
        )
        await session.commit()

    return NextProblemResponse(
        problem_id=outcome.problem_id,
        theta=outcome.theta,
        difficulty=outcome.difficulty,
        standard_error=outcome.standard_error,
        measurement_sufficient=outcome.measurement_sufficient,
        weight_axes_applied=outcome.weight_axes_applied,
        candidate_pool_size=outcome.candidate_pool_size,
        weak_concept_signal_count=outcome.weak_concept_signal_count,
        candidate_zero_reason=outcome.candidate_zero_reason,
        band_calibrated=outcome.band_calibrated,
        reason=outcome.reason,
        action=outcome.action,
        target_concept=outcome.target_concept,
    )


@router.patch(
    "/sessions/{session_id}/end",
    response_model=LearningSessionSchema,
    summary="내 학습 세션 종료(ended_at 채움)",
)
async def end_my_session(
    session_id: uuid.UUID,
    user: ConsentedUser,
    session: SessionDep,
) -> LearningSessionSchema:
    """slice 50 (slice 55 리팩터): 본인 학습 세션 종료(`ended_at`=now)·idempotent·404 비누설.

    slice 34: *처음 종료*될 때 현재 전과목 θ를 `ability_snapshot`에 자동 적재(세션 종료 트리거 —
    수동 POST 불요·성장 곡선 자연 샘플링). 멱등 재호출(이미 종료)이나 채점 이력 0이면 미적재.
    slice 35: 종료 컬럼 세팅·스냅샷 적재를 *한 트랜잭션*(단일 commit)으로 묶어 원자성 보장.
    """
    row, newly_closed = await _close_owned_resource(
        session,
        LearningSession,
        session_id,
        user.user_id,
        "ended_at",
        "학습 세션을 찾을 수 없습니다.",
        commit=False,  # 종료 + 스냅샷을 아래에서 단일 commit으로 원자 적용.
    )
    if newly_closed:
        await _add_ability_snapshot_if_attempts(session, user.user_id)
        await session.commit()  # 종료(ended_at) + (있으면)스냅샷 한 번에.
    return row.to_schema()


async def _add_ability_snapshot_if_attempts(session: AsyncSession, user_id: uuid.UUID) -> None:
    """채점 이력이 있으면 전과목+개념별 θ 스냅샷을 세션에 *추가만*(commit은 호출자)·빈 θ 미적재.

    slice 32 수동 캡처와 동일 산식·전과목 단일 θ(concept_id null). 세션 종료 트리거(slice 34/35).
    slice 75: 전과목 θ에 더해 *개념별* θ도 같은 시각으로 함께 적재(개념 θ 자연 샘플링 → coach
    BKT↔θ 교차검증이 폴백 없이 같은 개념끼리 정밀 비교). 채점 0이면 개념도 0(전과목의 부분집합).
    """
    now = datetime.now(UTC)
    theta, se, count = await estimate_global_ability(session, user_id)
    if count == 0:
        return  # 채점 이력 0 → 전과목·개념 θ 모두 미적재(개념은 전과목의 부분집합)
    session.add(
        AbilitySnapshot.from_schema(
            AbilitySnapshotSchema(
                user_id=user_id,
                theta=theta,
                standard_error=se,
                response_count=count,
                measured_at=now,
            )
        )
    )
    await _add_concept_ability_snapshots(session, user_id, now)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="내 학습 세션 영구 삭제(GDPR)",
)
async def delete_my_session(
    session_id: uuid.UUID,
    user: ConsentedUser,
    session: SessionDep,
) -> None:
    """slice 51 (slice 55 리팩터): 본인 학습 세션 영구 삭제(GDPR)·204·404 비누설.

    slice 56: 자식 problem_attempt는 ON DELETE CASCADE로 함께 삭제(그 attempt를 참조하던
    dialogue.attempt_id는 SET NULL — 대화 자체는 보존). attempt_event(loose ref)는 고아 잔존.
    """
    await _delete_owned_resource(
        session,
        LearningSession,
        session_id,
        user.user_id,
        AuditResourceType.learning_session,
        "학습 세션을 찾을 수 없습니다.",
    )


class DialogueEndRequest(BaseModel):
    """대화 종료 시 세션 결말(resolution) 선택 보고 — `PATCH /v1/me/dialogues/{id}/end` 본문.

    `resolution`은 *클라이언트 보고*다(`AttemptSubmitRequest.is_correct` 동형) — 클라이언트가
    LTHC 답 미루기 루프를 구동해 세션 결말(자력해결/유도/힌트/풀이공개/포기)의 자연 권위자다.
    서버는 이를 *영속만* 하고 신호로 판정하지 않는다(정답성·hint_level의 dialogue 귀속·포기
    영속은 후속 슬라이스). 본문 자체가 선택(미제공 시 `ended_at`만 채우는 기존 동작 보존).
    """

    model_config = ConfigDict(extra="forbid")

    resolution: Resolution | None = Field(
        default=None,
        description="세션 결말(클라이언트 보고·선택). 미제공 시 ended_at만 채움(하위호환).",
    )


@router.patch(
    "/dialogues/{dialogue_id}/end",
    response_model=DialogueSchema,
    summary="내 Socratic 대화 종료(ended_at 채움·resolution 선택 보고)",
)
async def end_my_dialogue(
    dialogue_id: uuid.UUID,
    user: ConsentedUser,
    session: SessionDep,
    body: Annotated[DialogueEndRequest | None, Body()] = None,
) -> DialogueSchema:
    """slice 52 (slice 55 리팩터): 본인 Dialogue 종료(`ended_at`=now)·idempotent·404 비누설.

    resolution(세션 결말·**클라이언트 보고**)을 선택 적재한다 — 서버는 영속만 하고 신호로
    판정하지 않는다(정답성·hint_level의 dialogue 귀속·포기 영속은 후속). **첫-종결-우선**:
    이미 resolution이 있으면 보존한다(낙인 방지·`ended_at` idempotency와 동형). resolution은
    ended_at과 *같은 트랜잭션*에 커밋한다(부분 적용 방지). 이 값은 self_solve_rate 대리 지표
    (`harness/wh1_evaluation.py` ⑪)의 원천이 된다.
    """
    row, newly_closed = await _close_owned_resource(
        session,
        Dialogue,
        dialogue_id,
        user.user_id,
        "ended_at",
        "대화를 찾을 수 없습니다.",
        commit=False,  # resolution 쓰기와 같은 트랜잭션에 묶어 원자 커밋(부분 적용 방지).
    )
    # resolution은 클라 보고(선택)·첫 기록 우선 — 이미 있으면 보존(낙인 방지). ended_at 재호출
    # 후에도 처음 제공되면 채울 수 있다(종료 먼저·결말 나중 보고 허용).
    resolution_written = False
    if body is not None and body.resolution is not None and row.resolution is None:
        row.resolution = body.resolution
        resolution_written = True
    if newly_closed or resolution_written:  # 변경이 있을 때만 커밋(완전 idempotent 재호출은 no-op).
        await session.commit()
    return row.to_schema()


@router.delete(
    "/dialogues/{dialogue_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="내 Socratic 대화 영구 삭제(GDPR)",
)
async def delete_my_dialogue(
    dialogue_id: uuid.UUID,
    user: ConsentedUser,
    session: SessionDep,
) -> None:
    """slice 52 (slice 55 리팩터): 본인 Dialogue 영구 삭제·204·404 비누설. slice 56: 자식
    dialogue_turn은 ON DELETE CASCADE로 함께 삭제."""
    await _delete_owned_resource(
        session,
        Dialogue,
        dialogue_id,
        user.user_id,
        AuditResourceType.dialogue,
        "대화를 찾을 수 없습니다.",
    )


@router.patch(
    "/assessments/{assessment_id}/complete",
    response_model=StudentAssessmentSchema,
    summary="내 진단 완료(completed_at 채움)",
)
async def complete_my_assessment(
    assessment_id: uuid.UUID,
    user: ConsentedUser,
    session: SessionDep,
) -> StudentAssessmentSchema:
    """slice 53 (slice 55 리팩터): 본인 Assessment 완료(`completed_at`=now). 컬럼은
    `completed_at`(ended_at 아님). idempotent·404 비누설.

    ASM-07: 응답 모델은 `StudentAssessment` — 예측 5필드는 스키마에 자리가 없다."""
    row, _ = await _close_owned_resource(
        session,
        Assessment,
        assessment_id,
        user.user_id,
        "completed_at",
        "진단을 찾을 수 없습니다.",
    )
    return StudentAssessmentSchema.from_assessment(row.to_schema())


@router.delete(
    "/assessments/{assessment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="내 진단 영구 삭제(GDPR)",
)
async def delete_my_assessment(
    assessment_id: uuid.UUID,
    user: ConsentedUser,
    session: SessionDep,
) -> None:
    """slice 53 (slice 55 리팩터): 본인 Assessment 영구 삭제·204·404 비누설. Assessment는
    자식 테이블이 없어 FK 위반 우려 없음(cascade 한계 무관)."""
    await _delete_owned_resource(
        session,
        Assessment,
        assessment_id,
        user.user_id,
        AuditResourceType.assessment,
        "진단을 찾을 수 없습니다.",
    )


# ── ASM-03: POST /v1/me/assessments/capture (measurement_sufficient 경계 → Assessment 조립) ──
# ASM-01(done)은 `assessment` 테이블에 writer가 0건임을 *관측*만 했다("생성 API 신설·활성화는
# 범위 밖"으로 명시 제외). 이 좌석이 그 후속 — writer를 *신설*하되, 신규 진단·통계·ML은 0이다.
# `/next-problem`이 이미 매 호출 판정하는 CAT 중단 경계(`_load_attempt_history_state`의
# `measurement_sufficient`)를 그대로 재사용해, 그 경계에서 *이미 계산되어 있는* L2 산출물
# 4종(개념 진단·약개념 추천·학습 경로·오개념 가설)을 Assessment 행 하나로 "조립"만 한다.
#
# 하드 제약(게임화 금기 — CLAUDE.md 절대 금기·backlog ASM-03 명시 조건): 등급(estimated_grade)·
# 점수(estimated_score)·백분위(estimated_percentile)·합격예측(admission_probability) *4개
# 예측 필드*는 이 경로에서 **절대 채우지 않는다**(항상 None). target_university_id도 합격예측과
# 짝이라 함께 None. 이 4필드는 DB DDL이 이미 갖고 있으나(§8.1), 그 존재가 곧 이 경로의 책임이라는
# 뜻은 아니다 — 예측·랭킹·등급화는 이 프로젝트가 만들지 않는 것(CLAUDE.md "우리가 만들지 않는 것").
_CAPTURE_ASSESSMENT_TYPE = AssessmentType.단원진단
"""캡처 Assessment의 assessment_type — 5종 중 개념 단위 진단과 가장 가까운 유형을 고른다.
신규 enum 값 추가 없음(기존 5종 중 선택)."""

_CAPTURE_WINDOW = "same_calendar_day_utc"
"""idempotency 창 정의(문서용 상수 — 로직은 `_capture_window_start`) — UTC 자정 기준 하루."""

_CAPTURE_ITEM_KIND_CONCEPT = "concept_diagnosis"
_CAPTURE_ITEM_KIND_MISCONCEPTION = "misconception_hypothesis"
"""`concept_diagnosis` JSONB 배열 안에서 두 산출물을 구분하는 판별자(discriminator) 키.
ASM-01 관측 리포트가 `concept_diagnosis`를 "오개념 목록이 담길 자리"로 명시했으므로(설계
정본 `assessment_seat_reach_report.py` 모듈 docstring), 오개념 가설도 같은 필드에 담되
`kind`로 두 항목 형태를 구분한다(별도 컬럼 신설·마이그레이션 0)."""

_CAPTURE_PATH_ORDERING_KEYS = ("ordering_basis", "ordering_edge_count", "has_cycle")
"""`recommended_path` JSONB의 각 step dict에 동반 기록되는 *경로 수준* 정직 표기 3종(`PATH-09`).

**왜 필요한가**: `ordering_basis`·`ordering_edge_count`·`has_cycle`은 `LearningPath`(부모)의
필드이고 `recommended_path`에 담기는 것은 `LearningStep`(자식)이다. 그래서 `path.steps`만
꺼내 저장하면 **부모의 정직 표기가 통째로 사라진다**. 실측상 기본 파라미터에서 96.4%가
`ordering_basis="tiebreak_only"`(= 제약 엣지 0 · 순서가 tiebreak로만 정해짐)인데, 학생은
`GET /v1/me/assessments`로 그 스냅샷을 "권장 학습 경로"로 다시 읽는다 — 근거 없이 정해진
순서를 근거 있는 순서와 구별할 수 없는 상태였다(침묵 실패).

**왜 헤더 원소가 아니라 step별 동반 기록인가**: 배열 앞에 메타 원소를 하나 끼우면
`len(recommended_path)`가 더 이상 step 수가 아니게 된다. 그 길이를 이미 두 곳이 소비한다 —
`harness/assessment_seat_reach_report.py`의 `jsonb_array_length(...) > 0` 관측 지표와
`tests/backend/api/test_me.py`의 step 수 단언. 정직 표기를 넣자고 **기존 관측 지표의 의미를
조용히 바꾸지 않는다**. step별 동반 기록은 배열 길이 의미를 정확히 보존한다(원소 = step).

**빈 배열의 의미**: `recommended_path == []`는 "담을 step이 없다"이고, 그때 경로 수준 표기를
실을 자리도 없다. `build_learning_path`는 steps가 비면 `ordering_basis="empty"`를 내므로
빈 배열과 `empty`는 서로를 함의한다 — 정보 손실이 아니다. 별도 표기를 만들지 않는다.

**날조 금지**: 세 값은 `build_learning_path`가 산출한 `LearningPath`에서 **그대로 옮기기만**
한다. 재계산·보정·정규화(신뢰도 점수화 등)를 하지 않는다."""

_CAPTURE_NOTE = (
    "measurement_sufficient 경계 자동 캡처(ASM-03) — 등급·점수·백분위·합격예측 4개 예측 "
    "필드는 게임화 금기(CLAUDE.md 절대 금기)로 이 경로에서 의도적으로 채우지 않음(항상 null)."
)


def _capture_window_start(now: datetime) -> datetime:
    """캡처 idempotency 창의 시작 시각 — UTC 자정(하루 단위). 순수 함수(테스트 용이)."""
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def _find_existing_capture(
    session: AsyncSession, user_id: uuid.UUID, now: datetime
) -> Assessment | None:
    """같은 창(오늘, UTC)에 이미 캡처된 Assessment가 있는지 조회 — 중복 적재 방지(idempotency).

    동일 학생·동일 assessment_type·`started_at`이 오늘(UTC 자정 이후)인 행이 있으면 그 행을
    돌려준다(있으면 새로 쓰지 않는다 — 이중 계상 방지). 없으면 None.
    """
    window_start = _capture_window_start(now)
    stmt = (
        select(Assessment)
        .where(
            Assessment.user_id == user_id,
            Assessment.assessment_type == _CAPTURE_ASSESSMENT_TYPE,
            Assessment.started_at >= window_start,
        )
        .order_by(Assessment.started_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def _assemble_measurement_assessment(
    session: AsyncSession, user_id: uuid.UUID, *, now: datetime
) -> AssessmentSchema:
    """기존 L2 산출물 4종을 *조립만* 해서 `AssessmentSchema`를 만든다 — 신규 계산 0.

    ① `compute_concept_diagnoses`(개념별 BKT↔IRT 진단, 이미 약점 먼저 정렬) → `concept_
       diagnosis`. ② `get_active_hypotheses`(활성 오개념 가설, confidence 내림차순) → 같은
       `concept_diagnosis` 배열에 `kind` 판별자로 이어붙임(모듈 상단 주석 참조). ③
       `recommend_weak_concepts`(BKT/IRT 약점 + atom_node 안전 메타) → `weak_points`.
       `recommend_strong_concepts`(같은 신호의 반대쪽 절반 — ASM-13) → `strong_points`. 이
       둘은 ①에서 이미 구한 `diagnoses`를 `diagnoses=` 인자로 넘겨받아 *같은 스냅샷*을
       공유한다(PR #1018 Codex 리뷰 실측 — 각자 재조회하면 동시 mastery 갱신 시 세 산출물이
       서로 다른 시점을 볼 수 있었다). ④ 가장 약한 개념(③의 첫 항목·이미 약점 정렬됨)을
       대상으로 `recommend_prerequisite_gaps` + `build_learning_path`(`/weak-concepts/{id}/
       learning-path`와 *동일 호출*·기본 파라미터)를 호출해 `recommended_path`를 얻는다.
       약점 개념이 하나도 없으면 빈 리스트. 각 step에는 경로 수준 정직 표기 3종
       (`ordering_basis`·`ordering_edge_count`·`has_cycle`)을 동반 기록한다(`PATH-09` —
       `_CAPTURE_PATH_ORDERING_KEYS` 참조).

    다섯 함수 전부 기존 L2 좌석 재사용(신규 진단·통계·ML 로직 0) — 이 함수가 하는 일은 *호출
    순서 결정 + 필드 매핑*뿐이다. `estimated_grade`·`estimated_score`·`estimated_percentile`·
    `admission_probability`·`target_university_id`는 명시적으로 None(모듈 상단 하드 제약 참조).
    """
    diagnoses = await compute_concept_diagnoses(session, user_id)
    hypotheses = await get_active_hypotheses(session, user_id)
    # 스냅샷 공유(docstring ③ 참조) — 재조회 0.
    weak = await recommend_weak_concepts(session, user_id, diagnoses=diagnoses)
    strong = await recommend_strong_concepts(session, user_id, diagnoses=diagnoses)

    concept_diagnosis_items: list[dict[str, Any]] = [
        {"kind": _CAPTURE_ITEM_KIND_CONCEPT, **d.model_dump(mode="json")} for d in diagnoses
    ] + [
        {"kind": _CAPTURE_ITEM_KIND_MISCONCEPTION, **h.model_dump(mode="json")} for h in hypotheses
    ]
    weak_point_items = [w.model_dump(mode="json") for w in weak]
    strong_point_items = [s.model_dump(mode="json") for s in strong]

    recommended_path_items: list[dict[str, Any]] = []
    if weak:
        # ③이 이미 약점(weakness) 오름차순 정렬을 보존하므로 첫 항목이 가장 약한 개념이다.
        weakest_concept_id = weak[0].concept_id
        gaps = await recommend_prerequisite_gaps(session, user_id, weakest_concept_id)
        path = await build_learning_path(session, gaps)
        # PATH-09: 경로 수준 정직 표기 3종을 step마다 동반 기록한다(재계산 0 — path에서 그대로
        # 옮기기만). 상수 docstring에 헤더 원소 대신 step별 기록을 택한 이유가 있다.
        ordering = {key: getattr(path, key) for key in _CAPTURE_PATH_ORDERING_KEYS}
        recommended_path_items = [
            {**step.model_dump(mode="json"), **ordering} for step in path.steps
        ]

    return AssessmentSchema(
        user_id=user_id,
        assessment_type=_CAPTURE_ASSESSMENT_TYPE,
        started_at=now,
        completed_at=now,
        # 하드 제약(게임화 금기) — 이 경로는 이 5필드를 절대 채우지 않는다.
        estimated_grade=None,
        estimated_score=None,
        estimated_percentile=None,
        target_university_id=None,
        admission_probability=None,
        concept_diagnosis=concept_diagnosis_items,
        weak_points=weak_point_items,
        strong_points=strong_point_items,
        recommended_path=recommended_path_items,
        notes=_CAPTURE_NOTE,
    )


class AssessmentCaptureResponse(BaseModel):
    """`POST /v1/me/assessments/capture` 응답 — 실제로 썼는지·왜 안 썼는지를 정직하게 표기."""

    written: bool = Field(description="이번 호출로 Assessment 행이 실제로 새로 생성됐는지.")
    reason: Literal["captured", "insufficient_measurement", "already_captured_window"] = Field(
        description=(
            "'captured'=신규 적재. 'insufficient_measurement'=SE가 목표 이상이라 측정 미충분"
            "(적재 안 함). 'already_captured_window'=같은 창(오늘)에 이미 캡처됨(idempotent — "
            "적재 안 함·기존 행 반환)."
        )
    )
    assessment: StudentAssessmentSchema | None = Field(
        default=None,
        description="'captured'·'already_captured_window'면 해당 Assessment(신규 또는 기존). "
        "'insufficient_measurement'면 null. ASM-07: 학생 대면 모델이라 예측 5필드는 "
        "스키마에 자리가 없다(적재는 내부 정본 `Assessment`로 그대로 수행).",
    )
    standard_error: float | None = Field(
        default=None,
        description="판정에 쓰인 현재 SE(참고용 — `/next-problem`과 동일 계산). 응답 없으면 null.",
    )
    measurement_sufficient: bool = Field(
        description="판정에 쓰인 measurement_sufficient(참고용 — `/next-problem`과 동일 경계)."
    )


@router.post(
    "/assessments/capture",
    response_model=AssessmentCaptureResponse,
    summary="measurement_sufficient 경계에서 기존 L2 산출물을 Assessment로 조립·적재(신규 계산 0)",
)
async def capture_measurement_assessment(
    user: ConsentedUser,
    session: SessionDep,
) -> AssessmentCaptureResponse:
    """`/next-problem`이 이미 판정하는 CAT 중단 경계(measurement_sufficient)에서, *그 시점에
    이미 존재하는* L2 산출물(개념 진단·오개념 가설·약개념 추천·학습 경로)을 `Assessment` 행
    하나로 조립해 적재한다(ASM-01이 관측만 하고 남겨둔 writer 부재를 해소).

    ① **경계 판정** — `_load_attempt_history_state`(=`/next-problem`과 *같은* 계산)로 현재
       SE·measurement_sufficient를 구한다. False면 적재하지 않고 `insufficient_measurement`.
    ② **idempotency** — 같은 학생·같은 창(오늘, UTC)에 이미 캡처된 행이 있으면 다시 쓰지
       않고 `already_captured_window`(기존 행을 그대로 반환 — 이중 계상 방지).
    ③ **조립·적재** — `_assemble_measurement_assessment`(신규 계산 0, 위 함수 참조)로
       `AssessmentSchema`를 만들어 1행 commit. `assessment_id`는 스키마
       `default_factory=uuid4`가 클라 측에서 발급(캡처 ability_snapshot과 동일 패턴 —
       `session.refresh` 불요).

    **하드 제약(게임화 금기)**: 등급·점수·백분위·합격예측 4개 예측 필드는 이 경로에서 절대
    채우지 않는다(모듈 상단 주석·`_assemble_measurement_assessment` docstring 참조).
    """
    state = await _load_attempt_history_state(session, user.user_id)
    if not state.measurement_sufficient:
        return AssessmentCaptureResponse(
            written=False,
            reason="insufficient_measurement",
            assessment=None,
            standard_error=state.standard_error,
            measurement_sufficient=False,
        )

    now = datetime.now(UTC)
    existing = await _find_existing_capture(session, user.user_id, now)
    if existing is not None:
        return AssessmentCaptureResponse(
            written=False,
            reason="already_captured_window",
            assessment=StudentAssessmentSchema.from_assessment(existing.to_schema()),
            standard_error=state.standard_error,
            measurement_sufficient=True,
        )

    schema = await _assemble_measurement_assessment(session, user.user_id, now=now)
    # 적재는 내부 정본(예측 5필드 포함 · 값은 항상 None)으로, 응답은 학생 대면 정본으로.
    session.add(Assessment.from_schema(schema))
    # EOS-103: 이 분기가 **진단 완료 경계**다(CAT 중단 규칙 measurement_sufficient가 True이고
    # 이번 창에 아직 캡처가 없는, 즉 진단 결과가 처음으로 확정되는 지점). 여기서 LearnerState
    # 영속 행을 자동 생성해, 운영자가 DB에 행을 직접 만들 필요가 없게 한다(멱등 — 이미 있으면
    # 그 행을 그대로 두고 `provisioned_at`·`provisioned_by`를 덮어쓰지 않는다).
    # 같은 commit 안에 두어 "진단은 적재됐는데 상태는 없다"는 반쪽 성공이 생기지 않게 한다.
    await provision_learner_state(session, user.user_id, reason="diagnosis_capture")
    await session.commit()
    return AssessmentCaptureResponse(
        written=True,
        reason="captured",
        assessment=StudentAssessmentSchema.from_assessment(schema),
        standard_error=state.standard_error,
        measurement_sufficient=True,
    )


# ── ASM-04: POST /v1/me/assessments/assemble (평가 청사진 → 테스트셋 조립 → Assessment 좌석) ──
# 설계 정본 `assessment_module_gap_review.md` §3 D4. ASM-03(위)이 *측정 경계에서 이미 계산된*
# L2 산출물을 Assessment로 조립했다면, 이 좌석은 *선언 명세(blueprint)를 만족하는 문항 집합*을
# 조립해 같은 테이블의 다른 유형(`실전모의고사`) 행으로 앉힌다. 조립 로직 자체는 L6
# (`l6.blueprint.assemble_test_set` — 순수·결정론)이고, 이 핸들러는 "DB 후보 조회 + L6 호출 +
# 적재" 조합만 한다(계층 경계 — api는 게이팅·조립을 *구현하지 않는다*).
#
# **CAT 대체 아님(D4-2 동결)**: 학습 중 문항 노출의 정본은 CAT 단건(`GET /v1/me/next-problem`)
# 이고, 이 세트는 "단원 마감 측정"(`BLUEPRINT_USE_CASE`) 예외에만 쓴다. `/next-problem` 핸들러는
# 이 좌석을 알지 못하며(코드 참조 0), 그 사실을 테스트가 기계로 동결한다.
#
# 하드 제약(ASM-02·ASM-03 승계): 등급·점수·백분위·합격예측 4개 예측 필드는 이 경로에서도
# **절대 채우지 않는다**(항상 None). 게임화 금기 — 세트 시행 결과로 점수·등급을 산출하는 것은
# 이 프로젝트가 만들지 않는 것(CLAUDE.md)이다. 이 좌석은 *세트 구성*까지만 책임진다.
_BLUEPRINT_ASSESSMENT_TYPE = AssessmentType.실전모의고사
"""청사진 세트 Assessment의 `assessment_type` — 기존 5종 중 '실전모의고사'의 **첫 발화**.

신규 enum 값 추가 0(§8.1 DDL이 이미 가진 5종 중 선택). `단원진단`(ASM-03 캡처)과 다른 유형이라
두 좌석의 행이 서로 섞이지 않는다(조회·집계에서 자연 분리).
"""

_BLUEPRINT_ITEM_KIND_SET = "blueprint_test_set"
_BLUEPRINT_ITEM_KIND_ITEM = "blueprint_item"
"""`pattern_diagnosis` JSONB 배열 안에서 두 항목 형태를 구분하는 판별자(discriminator).

세트를 **새 테이블 없이** 표현하기 위한 좌석이다(D4-4 — 신규 마이그레이션 0). `Assessment`의
JSONB 5종 중 `pattern_diagnosis`가 비어 있고 소비처가 없어 이 용도로 쓴다. 한 JSONB 배열에
이종 항목(세트 헤더 1건 + 문항 N건)을 `kind`로 구분해 담는 방식은 ASM-03이 `concept_diagnosis`
에서 만든 선례를 그대로 답습한다.
"""

_BLUEPRINT_NOTE = (
    "평가 청사진 기반 테스트셋 조립(ASM-04) — 단원 마감 측정 전용(CAT 대체 아님). 등급·점수·"
    "백분위·합격예측 4개 예측 필드는 게임화 금기로 이 경로에서 의도적으로 채우지 않음(항상 null)."
)

_BLUEPRINT_CANDIDATE_FETCH_LIMIT = 3000
"""청사진 조립에 먹일 후보 문항 fetch 상한 — `api/gating.py`의 후보 상한과 같은 값(코퍼스
2,647건 + 여유). L6 조립기가 적격·제약·개수를 전부 판정하므로 이 상한은 "후보 풀 크기"일 뿐
응답 크기가 아니다. 상한과 정확히 같은 건수를 읽으면 절단 의심이므로 경고 로그를 남긴다."""


def _blueprint_pattern_diagnosis(assembly: AssembledTestSet) -> list[dict[str, Any]]:
    """조립 결과를 `pattern_diagnosis` JSONB 배열로 직렬화한다(세트 헤더 1 + 문항 N).

    첫 항목은 세트 헤더(`kind=blueprint_test_set`)로 총점 2축 회계·시험시간·용도를 담고,
    이어서 문항마다 1건(`kind=blueprint_item`)이 문항 id·소속 칸·세트 내 위치를 담는다.
    **문항 본문은 담지 않는다** — id 참조만이라 저작권·PII 표면이 늘지 않는다.

    `corpus_total_points`가 `None`인 경우 그 null을 그대로 보존한다(0으로 접지 않는다 —
    "총점 미산출"과 "총점 0점"은 다른 사실이다). 왜 None인지는 `points_missing_count`가 말한다.

    Args:
      assembly: `assemble_test_set` 결과.

    Returns:
      JSONB에 그대로 넣을 수 있는 dict 리스트(헤더 1건 + 문항 건수).
    """
    header: dict[str, Any] = {
        "kind": _BLUEPRINT_ITEM_KIND_SET,
        "title": assembly.title,
        "use_case": assembly.use_case,
        "requested_item_count": assembly.requested_item_count,
        "selected_item_count": assembly.selected_item_count,
        # 총점 2축 — 선언(청사진) / 실측(코퍼스 points). None은 None으로 보존.
        "declared_total_points": assembly.declared_total_points,
        "declared_points_missing_cells": assembly.declared_points_missing_cells,
        "corpus_total_points": assembly.corpus_total_points,
        "points_missing_count": assembly.points_missing_count,
        # 시험시간은 청사진 선언값의 *보존*일 뿐 문항별 배분·추정이 아니다(D4 정직 회계 ②).
        "time_limit_minutes": assembly.time_limit_minutes,
    }
    items: list[dict[str, Any]] = []
    position = 0
    for fill in assembly.cells:
        for problem_id in fill.selected_problem_ids:
            items.append(
                {
                    "kind": _BLUEPRINT_ITEM_KIND_ITEM,
                    "problem_id": str(problem_id),
                    "cell_index": fill.cell_index,
                    "position": position,
                }
            )
            position += 1
    return [header, *items]


async def _fetch_blueprint_candidates(session: AsyncSession) -> list[ProblemSchema]:
    """청사진 조립에 넘길 후보 문항을 읽고 *성취기준 코드*(비영속)를 주입해 돌려준다.

    `api/gating.py`의 두 헬퍼를 **그대로 재사용**한다(같은 L5 레이어·같은 조인을 두 번 쓰지
    않는다 — 단일 진실 원천). `_fetch_candidates`는 후보 조회 + 절단 경고를, `_fetch_achievement
    _codes`는 원자 축 조인(problem_concept→concept→atom_node.standard_codes) 일괄 IN 조회를
    담당한다. 성취기준 코드는 ORM 비매핑(비영속) 필드라 주입이 없으면 빈 리스트이고, 그러면
    `standard_code`를 지정한 청사진 칸은 후보가 0이 되어 **조립이 명시적으로 실패**한다
    (조용히 아무 문항이나 채우지 않는다).

    `curriculum_required_depth` 주입(`_fetch_candidates_with_standards`가 추가로 하는 일)은
    부르지 않는다 — 청사진은 요구 깊이 축을 쓰지 않으므로 sync 엔진·리졸버 비용을 지지 않는다.

    Args:
      session: 요청 수명 AsyncSession.

    Returns:
      성취기준 코드가 주입된 후보 `schema.Problem` 리스트(L6 조립기 입력).
    """
    candidates = await _fetch_gating_candidates(session)
    codes = await _fetch_gating_achievement_codes(session, [p.problem_id for p in candidates])
    for problem in candidates:
        if problem.problem_id in codes:
            # sorted로 결정적 순서(집합→리스트). 키 부재 문항은 기본 빈 리스트 유지.
            problem.achievement_standard_codes = sorted(codes[problem.problem_id])
    return candidates


class AssessmentAssembleResponse(BaseModel):
    """`POST /v1/me/assessments/assemble` 응답 — 적재 여부·이유 + 조립 회계 전문."""

    model_config = ConfigDict(extra="forbid")

    written: bool = Field(description="이번 호출로 Assessment 행이 실제로 생성됐는지.")
    reason: Literal["assembled", "blueprint_unsatisfied"] = Field(
        description="'assembled'=청사진 전 칸 충족·적재 완료. 'blueprint_unsatisfied'=요구 "
        "문항 수를 채우지 못해 **적재하지 않음**(부족한 세트를 조용히 남기지 않는다). 부족 "
        "사유는 `assembly.unsatisfied_reasons`·칸별 `shortfall` 참조."
    )
    assessment: StudentAssessmentSchema | None = Field(
        default=None,
        description="'assembled'면 적재된 Assessment(학생 대면 모델 — 예측 5필드는 스키마에 "
        "자리가 없다). 'blueprint_unsatisfied'면 null.",
    )
    assembly: AssembledTestSet = Field(
        description="조립 결과 전문 — 세트 문항 id·칸별 충족/부족·총점 2축(선언/실측) 회계·"
        "선언 시험시간. 실패 시에도 *무엇이 얼마나 모자랐는지* 진단할 수 있게 항상 채운다."
    )
    candidate_pool_size: int = Field(
        ge=0,
        description="조립기에 실제로 넘어간 후보 문항 수(정직 표기 — 후보가 애초에 적었는지 "
        "제약이 셌는지를 구분할 수 있게 한다).",
    )


@router.post(
    "/assessments/assemble",
    response_model=AssessmentAssembleResponse,
    summary="평가 청사진(성취기준×난이도×유형·문항수·배점·시간)으로 테스트셋 조립·적재",
)
async def assemble_blueprint_assessment(
    blueprint: ExamBlueprint,
    user: ConsentedUser,
    session: SessionDep,
) -> AssessmentAssembleResponse:
    """선언 청사진을 만족하는 테스트셋을 자체 동등문제 코퍼스에서 조립해 `Assessment`로 적재한다.

    ① **후보 조회** — `_fetch_blueprint_candidates`(문항 + 성취기준 코드 원자 축 조인 주입).
    ② **조립** — L6 `assemble_test_set`(순수·결정론). 적격 게이트는 저작권 축
       (`is_exposable`)과 검수 축(`is_review_cleared`)을 *각각 독립된 if*로 통과시킨다 —
       평가원·EBS·교과서(본문 미보유) 출처와 미검수 문항은 세트에 들어갈 수 없다.
    ③ **충족 판정** — 한 칸이라도 요구 문항 수를 못 채우면 `blueprint_unsatisfied`로
       **적재하지 않고** 부족 명세를 그대로 돌려준다(조용한 부분 세트 금지·D4 정직 회계 ③).
    ④ **적재** — 충족이면 `AssessmentType.실전모의고사` 행 1건. 세트는 새 테이블이 아니라
       `pattern_diagnosis` JSONB(세트 헤더 + 문항 id 배열)로 표현한다(신규 마이그레이션 0).
       `completed_at`은 **None** — 세트는 *조립*됐을 뿐 아직 시행·완료되지 않았다(완료는 기존
       `PATCH /v1/me/assessments/{id}/complete` 좌석이 찍는다).

    **총점의 정직한 한계**: 2026-08-10 실측 기준 코퍼스 2,647건이 전량 `points=NULL`이라,
    실측 총점(`assembly.corpus_total_points`)은 사실상 항상 `null`이고 `points_missing_count`가
    그 이유(미부여 건수)를 말한다. NULL을 0으로 접어 가짜 총점을 만들지 않는다. 청사진이 배점을
    선언했다면 `declared_total_points`(선언 축)가 따로 채워진다 — 두 축을 섞지 않는다.

    **CAT 대체 아님**: 이 좌석은 "단원 마감 측정" 예외 전용이다(모듈 상단 주석·`BLUEPRINT_
    USE_CASE`). 학습 중 문항은 계속 `/v1/me/next-problem`(CAT 단건)이 정본이다.
    """
    candidates = await _fetch_blueprint_candidates(session)
    assembly = assemble_test_set(blueprint, candidates)
    if not assembly.satisfied:
        # 부족한 세트는 적재하지 않는다 — "조용히 부족한 세트 반환" 금지(D4 정직 회계 ③).
        return AssessmentAssembleResponse(
            written=False,
            reason="blueprint_unsatisfied",
            assessment=None,
            assembly=assembly,
            candidate_pool_size=len(candidates),
        )

    now = datetime.now(UTC)
    schema = AssessmentSchema(
        user_id=user.user_id,
        assessment_type=_BLUEPRINT_ASSESSMENT_TYPE,
        started_at=now,
        # 조립 시점은 *시행 전*이라 완료가 아니다(완료는 complete 좌석이 찍는다).
        completed_at=None,
        # 하드 제약(게임화 금기) — 이 경로도 이 5필드를 절대 채우지 않는다(ASM-02·03 승계).
        estimated_grade=None,
        estimated_score=None,
        estimated_percentile=None,
        target_university_id=None,
        admission_probability=None,
        pattern_diagnosis=_blueprint_pattern_diagnosis(assembly),
        notes=_BLUEPRINT_NOTE,
    )
    session.add(Assessment.from_schema(schema))
    await session.commit()
    return AssessmentAssembleResponse(
        written=True,
        reason="assembled",
        assessment=StudentAssessmentSchema.from_assessment(schema),
        assembly=assembly,
        candidate_pool_size=len(candidates),
    )


# ── DELETE /v1/me : 계정·전체 데이터 영구 삭제(개인정보 삭제권·R11) ──
# 단일 리소스 삭제(위 sessions/dialogues/assessments)와 달리, 본인 *계정 전체*(17개 테이블 +
# user_profile)를 단일 트랜잭션으로 지운다(privacy.erase_user·#242). 오삭제 방지로 확인 문구를
# 요구하고, **CurrentUser**(동의 게이트 아님)를 쓴다 — 미성년 동의 미설정자도 *삭제*는 가능해야
# 한다(삭제권 우선·수집 동의와 무관). 법정대리인 동의 *흐름*은 후속(여기선 본인 인증 + 확인 문구).
_DELETE_CONFIRMATION = "DELETE_MY_ACCOUNT"


class AccountErasureRequest(BaseModel):
    """계정 삭제 요청 — 오삭제 방지 확인 문구 필수."""

    model_config = ConfigDict(extra="forbid")

    confirmation: str = Field(
        description=f"오삭제 방지 확인 문구 — 정확히 '{_DELETE_CONFIRMATION}'이어야 한다.",
    )


class AccountErasureResponse(BaseModel):
    """계정 삭제 영수증 — 무엇이 지워졌는지의 *요약*(내부 테이블 구조 비노출)."""

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID = Field(description="삭제된 사용자 id.")
    total_rows_deleted: int = Field(ge=0, description="삭제된 총 행수(전 테이블 + user_profile).")


@router.delete(
    "",
    response_model=AccountErasureResponse,
    summary="내 계정·전체 데이터 영구 삭제(개인정보 삭제권·R11)",
)
async def erase_my_account(
    body: AccountErasureRequest,
    user: CurrentUser,
    session: SessionDep,
) -> AccountErasureResponse:
    """삭제권(R11) — 본인 계정의 *모든* 학생-연결 데이터를 단일 트랜잭션으로 영구 삭제.

    인증된 *본인만*(user_id=토큰 subject) 자기 계정을 지운다. 오삭제 방지로 확인 문구
    (`confirmation == '{_DELETE_CONFIRMATION}'`) 불일치 시 **400**. `privacy.erase_user`(#242)
    오케스트레이션을 호출해 17개 테이블 + user_profile을 자식→부모 순서로 지우고, 삭제 *시도*는
    `DeletionAudit`로 잔존한다(GDPR 증빙). 같은 트랜잭션 commit이라 부분 삭제가 없다. 멱등
    (이미 없으면 0행). **동의 게이트 아님**(`CurrentUser`) — 미성년 동의 미설정자도 삭제 가능
    (삭제권 우선). 법정대리인 동의 *흐름*은 후속.

    응답은 *요약 영수증*(user_id·총 삭제 행수)만 — 내부 테이블 구조는 노출하지 않는다. 삭제 후
    본인 토큰/세션도 사라지므로(refresh_token_session 포함) 이후 요청은 재인증이 필요하다.

    RDB 밖 store(Redis·Langfuse)는 이 트랜잭션이 못 지운다 — `report.pending_external`
    매니페스트를 *ops 로그*로 남겨(store명·user_id만) 별도 삭제가 필요함을 가시화한다(누락 은폐
    금지·GDPR 범위 정직). student-facing 응답엔 인프라 정보를 싣지 않는다(정보 누출 방지).
    """
    if body.confirmation != _DELETE_CONFIRMATION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"확인 문구가 일치하지 않습니다('{_DELETE_CONFIRMATION}' 필요).",
        )
    # 삭제 후 user 객체 만료(expire_on_commit)에 대비해 user_id를 먼저 포획.
    user_id = user.user_id
    report = await erase_user(session, user_id=user_id)
    await session.commit()
    # ops 가시화 — RDB 밖 store(Redis·Langfuse)는 이 TX가 못 지운다(report.pending_external).
    # 누락을 조용히 넘기지 않도록 알림(store명·user_id만·키 패턴 미로깅) — 별도 삭제 필요.
    _logger.info(
        "개인정보 삭제권 실행: user=%s · PG %d행 삭제 · 외부 store %d곳 별도 삭제 필요(%s)",
        user_id,
        report.total_rows_deleted,
        len(report.pending_external),
        ", ".join(t.store for t in report.pending_external),
    )
    return AccountErasureResponse(user_id=user_id, total_rows_deleted=report.total_rows_deleted)


@router.get(
    "/export",
    response_model=UserDataExport,
    summary="내 데이터 내보내기(개인정보 열람·이동권·GDPR)",
)
async def export_my_data(
    request: Request,
    user: ConsentedUser,
    session: SessionDep,
    settings: SettingsDep,
) -> UserDataExport:
    """열람·이동권 — 본인의 학습/진단 데이터를 구조화 JSON으로 내려받는다(삭제권의 짝).

    인증된 *본인만*(`user_id=토큰 subject`) 자기 데이터를 받는다(다른 /me GET과 동형·user_id
    스코핑). `privacy.export_user_data`(#264·읽기 전용)가 `_EXPORT_PLAN`의 학습/진단 5종 +
    user_profile을 모아 반환한다. **부분 export**임을 `not_included`로 정직히 고지한다(대화·시계열·
    외부 store 등 미포함·후속). per-user 본인 데이터라 HTTP 노출이 맞다(전역 집계 아님).

    외부 store(Redis·Langfuse)는 RDB 밖이라 이 export에 못 담는다 — `external_export_pending`
    매니페스트를 *ops 로그*로 남겨(store명·user_id만) 별도 export가 필요함을 가시화한다(누락 은폐
    금지·GDPR 범위 정직). student-facing 응답엔 인프라 정보를 싣지 않는다(정보 누출 방지).

    SEC-09: export payload를 모은 *뒤*(반출 내용이 아니라 "반출이 일어났다"는 사실만) `privacy_
    audit`에 감사 1행을 적재하고 이 요청 안에서 commit한다(반출과 감사가 원자적 — 한쪽만
    성공하는 부분 상태를 만들지 않는다). `export_user_data`는 읽기 전용(commit 0)이라 이 함수가
    이 엔드포인트 최초의 쓰기다.
    """
    export = await export_user_data(session, user_id=user.user_id)
    record_export_audit(
        session, user_id=user.user_id, ip=_client_ip(request, settings=settings), settings=settings
    )
    await session.commit()
    # ops 가시화 — RDB 밖 store는 이 export(PG)에 미포함(store명·user_id만·키 패턴 미로깅).
    pending = external_export_pending(user.user_id)
    _logger.info(
        "개인정보 열람·이동권 export: user=%s · 카테고리 %d · 외부 store %d곳 별도 export 필요(%s)",
        user.user_id,
        len(export.data),
        len(pending),
        ", ".join(t.store for t in pending),
    )
    return export


# ── WH-1 0단계: GET /v1/me/harness-metrics (대리 지표 7종+S3 4종+PED-04 3종 — admin 전용) ──
# 설계안 04a §8.4 "0단계 대리 지표 베이스라인 좌석"의 노출 표면. 이제 대리 지표 7종 모두 계측
# 좌석이 가동(⑦은 근사)이고, S3(status_roadmap §3) 세션 대리 지표 4종(⑧ 답 미루기 도달 깊이·
# ⑨ BKT 숙달 증가율·⑩ 오개념 해소율·⑪ 스스로 풀이 도달율)이 편입됐다. PED-04(교수 결정 로그)가
# 3종(⑫ 발문 전략 다양성·⑬ 연속 반복률·⑭ 클라 Polya 상태 불일치율)을 더 편입했다 — D1 writer가
# 처음 만든 데이터의 첫 reader. 각 지표는 표본 0/부족이면 value=None + status(NO_DATA) + note로
# 갭을 표면화한다(날조 금지·CLAUDE.md "모르면 모른다"). 코호트 전체 집계(user_id=None)는
# ops/스크립트가 직접 호출.
#
# SEC-24(원 SEC-13, 2026-08-08): 이 엔드포인트는 도입 당시부터 "내부·집계 전용 원시 계측 표면"이라고
# docstring에 적혀 있었으나 실제 게이트는 `ConsentedUser`(학생 포함 인증 사용자 전원)였다 —
# 선언과 집행이 어긋난 채 방치됐다(functional_security_audit_2026-08-08.md H1). 원시
# `SurrogateMetrics`엔 INTERNAL_ONLY 지표(②진단정확도·④턴당토큰)·⑥보정점수 원 스칼라(역방향
# 오독 위험)·⑧도움 감소 R15 결합판정의 원 verdict(게임화 의심 낙인 가능,
# CLAUDE.md "부정 피드백 정서 강화 금지")가 그대로 실린다 — `harness/growth_evidence_exposure.py`
# 가 이 세 벡터를 정확히 차단 대상으로 규정한다(:65-78 INTERNAL_ONLY 계층·:87-99 Brier 서술
# 변환·:121-129 조합 제약. 참조: `test_me_growth_evidence_governance.py`가 이 파일에 그 두
# 금지 리터럴이 등장하는 것 자체를 별도로 차단하므로 여기서도 서술만 하고 그대로 적지 않는다).
# 그 계약의 유일한 집행 지점은 `GET /v1/me/growth-evidence`(PED-08)
# 뿐이었고 이 원시 표면은 계약을 우회해 학생 토큰에 그대로 도달했다. 정정: `RequireContentAdmin`
# 게이트로 닫는다(문제·개념 CUD 라우터와 동일 v0 역할 게이트 재사용 — 신규 ops 역할 신설은
# 과공학, ADMIN-01 후속 과제). 본인 스코핑(`user.user_id`)은 유지 — 코호트 전체 조회는
# 여전히 admin auth 범위 밖(ops/스크립트가 `compute_wh1_surrogate_metrics(user_id=None)` 직접
# 호출).
@router.get(
    "/harness-metrics",
    response_model=SurrogateMetrics,
    summary="[admin 전용] WH-1 0단계 대리 지표 원시값(7종 + S3 세션 4종 + PED-04 3종 커버리지 맵)",
)
async def get_my_harness_metrics(
    request: Request,
    user: RequireContentAdmin,
    session: SessionDep,
    since: SinceParam = None,
    until: UntilParam = None,
    mode: HarnessMetricsMode = None,
) -> SurrogateMetrics:
    """WH-1 튜터링 하네스 0단계 대리 지표 7종 + S3 세션 4종 + PED-04 3종 + S3-16 1종 — *호출자*
    집계 커버리지 맵(admin 전용 원시 표면).

    설계안 04a §8.4 "측정 없는 도입 없음" 0단계 베이스라인. 대리 지표 7종(① verify 통과율·
    ② 진단정확도·③ 세션 완주율·④ 턴당 토큰·⑤ 도움 감소 곡선·⑥ 보정 점수·⑦ 전이 점수[근사])은
    모두 계측 좌석이 살아 있고, S3(status_roadmap §3) 세션 대리 지표 4종(⑧ 답 미루기 도달 깊이·
    ⑨ BKT 숙달 증가율·⑩ 오개념 해소율·⑪ 스스로 풀이 도달율)이 편입됐다. PED-04(교수 결정 로그)
    3종(⑫ 발문 전략 다양성·⑬ 연속 반복률·⑭ 클라 Polya 상태 불일치율)도 편입됐다 — `DialogueTurn`
    메타 컬럼 writer가 처음 만든 데이터의 첫 reader. S3-16(행동 텔레메트리 생산자 좌석)에서
    ⑮ 도움 요청 대 제공 비(힌트요청/힌트제공 개수 비)도 편입됐다 — supply(힌트제공) 0건이면
    NO_DATA. 각 지표는 표본 0/부족이면 value=None + status + note로 "무엇을 만들면 잴 수 있는지"를
    정직하게 드러낸다(가짜 0/stub 금지). ⑨는 measured_at·⑩은 updated_at·⑪은 started_at
    (resolution) 시간창을 쓰고, ⑫⑬은 대화 started_at·⑭⑮는 힌트제공/힌트요청 이벤트 event_at
    시간창을 쓴다(mode 스코프는 ⑭⑮만 적용 — ⑫⑬은 대화 기반이라 mode 태그가 아직 실리지 않는다).
    나머지는 started_at/event_at 기준이다. ⑪ resolution은 클라이언트 보고(PATCH .../end 적재·
    서버 미판정).

    `since`/`until`(선택)로 시간창(inclusive·TZ-aware ISO8601·naive·since>until은
    422). user_id는 인증에서 주입(호출자 본인 집계만 — 코호트 조회는 미지원).

    **인가(SEC-24, 원 SEC-13)**: `RequireContentAdmin` — `Role.CONTENT_ADMIN`이 아니면 403. 학생
    (`Role.STUDENT`) 토큰은 원시 지표에 도달할 수 없다(INTERNAL_ONLY 2종·⑥Brier 원값·
    ⑧게임화 의심 낙인 차단). 학생 안전 노출은 `GET /v1/me/growth-evidence`(PED-08)만 쓴다
    — 그쪽이 `classify_metric_exposure`의 유일한 집행 지점이다.

    **PED-06 도달 관측**: 이 호출 자체를 `GrowthEvidenceReachCounters`가 센다(`GET /health/ready`
    `growth_evidence.requests_total`에 노출) — `gamification_module_gap_review.md` §3 D1이
    실측한 "클라가 이 엔드포인트를 호출하기로 결정한 적 자체가 없다"는 주장을 라이브로도
    검증 가능하게 만든다. 응답 필드 자체는 이번 태스크로 변경하지 않는다 — SEC-24는 *누가*
    호출할 수 있는지만 좁힌다.
    """
    # 시간창 검증(noexpose 계층): naive·since>until 거부. 검증된 경계를 harness에 그대로 전달.
    get_growth_evidence_counters(request.app).record_request()
    since = _validate_tz_aware(since, "since")
    until = _validate_tz_aware(until, "until")
    _validate_time_window(since, until, "since", "until")
    # S3-03: mode 스코프(예: suneung) — 설정 시 attempt_event 기반 지표(①⑤⑧)를 그 mode 태그가
    # 실린 이벤트만으로 집계한다(수능 세션 측정). 미지정이면 전 mode 포함(기존 동작 불변).
    return await compute_wh1_surrogate_metrics(
        session, user_id=user.user_id, since=since, until=until, mode=mode
    )


# ── PED-08: GET /v1/me/growth-evidence (성장 증거 학생 안전 노출 — 노출 계약 유일 경로) ──
# `growth_evidence_exposure.py`가 스스로 "classify_metric_exposure가 유일한 노출 판정
# 경로"라고 선언했으나(:122 부근) 그 함수를 실제로 부르는 학생 대면 라우트가 이번 태스크
# 이전엔 0건이었다(위 `/harness-metrics`는 원시 SurrogateMetrics를 그대로 반환 — 계약을
# 우회). 이 엔드포인트가 그 계약의 *첫이자 유일한* 집행 지점이다 — 계약 로직(노출 계층·
# 조합 제약 판정)은 재구현하지 않고 `classify_metric_exposure`·`narrate_calibration_brier`를
# 그대로 호출해서만 응답을 만든다.
class GrowthEvidenceMetricView(BaseModel):
    """성장 증거 지표 1종의 학생 노출 뷰 — `MetricExposure`(계약 판정) + `Metric.value` 조합.

    `Metric.note`(자유 서술)는 의도적으로 이 뷰에 없다 — 학생 대면 톤으로 검수된 적 없는
    내부 진단 문구라 범위 밖(태스크 설계 명시).
    """

    model_config = ConfigDict(extra="forbid")

    status: MetricStatus = Field(description="계측 상태 — 실값/미계측 사유 구분(SurrogateMetrics).")
    value: float | None = Field(
        description=(
            "실측값. 미계측·표본 0이면 null. exposable_now=False인 지표는 null로 강제한다"
            "(계약이 노출을 보류한 값을 서빙 층이 흘려보내지 않는다)."
        )
    )
    exposable_now: bool = Field(
        description="이번 판정에서 실제로 노출 가능한지 — `classify_metric_exposure` 그대로."
    )
    suppressed_reason: str | None = Field(
        default=None,
        description=(
            "exposable_now=False인 이유(한국어). `hint_depth_reached`가 R15 조합 제약으로 "
            "보류되면 계약 모듈의 원문 대신 이 서빙 층이 소유한 문장으로 대체한다(금지 토큰 "
            "미포함 보증 — 계약 모듈 원문은 낙인성 verdict 코드명을 리터럴로 포함해 그대로 "
            "내보내면 학생 대면 JSON에 낙인 라벨이 유출된다)."
        ),
    )


class GrowthEvidenceBrierView(BaseModel):
    """⑥ 보정 점수(Brier) 학생 노출 뷰 — 3버킷 서술만(원 스칼라 구조적 배제).

    `value` 필드가 *의도적으로 없다* — Brier는 "낮을수록 좋음" 역방향 스칼라라 그대로
    노출하면 오독(계약 모듈 `narrate_calibration_brier` docstring). 필드 부재는 런타임
    필터가 아니라 스키마 자체의 구조적 배제라 꺼질 수 없다(태스크 설계 원칙).
    """

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(
        description="`narrate_calibration_brier` 4문장 중 1개(NO_DATA/양호/보통/큰 편)."
    )


class GrowthEvidenceResponse(BaseModel):
    """`GET /v1/me/growth-evidence` 응답 — 성장 증거 학생 안전 노출(노출 계약 경유 유일 표면).

    `SurrogateMetrics`의 `STUDENT_VISIBLE` 9지표(`calibration_brier` 제외) + Brier 서술
    1종만 필드로 존재한다. **내부 전용 2종(② 진단정확도·④ 턴당 토큰 — 시스템 품질/비용
    지표)은 이 스키마 어디에도 필드가 없다** — `INTERNAL_ONLY` 계층이라 런타임에 걸러지는
    것이 아니라 애초에 필드 자체가 없다(구조적 배제 — 필터는 꺼질 수 있으나 부재는 꺼질
    수 없다는 태스크 설계 원칙). R15 결합 판정 원본(교정기 함정 verdict 포함)도 이 스키마에
    필드가 없다 — `hint_depth_reached` 뷰의 `suppressed_reason`으로만 간접 반영된다(그마저
    계약 모듈 원문이 아니라 이 서빙 층이 소유한 문장, 아래 엔드포인트 참조). 비교·서열·
    순위(백분위·평균 대비·타 학생) 파생 필드도 의도적으로 0종이다(계약 모듈이 그런 파생
    함수를 두지 않는 것과 동형 — `07_community.md` "❌ 익명·집계만" 승계).
    """

    model_config = ConfigDict(extra="forbid")

    window_start: datetime | None = Field(description="집계 시간창 시작(since, 입력 그대로 echo).")
    window_end: datetime | None = Field(description="집계 시간창 끝(until, 입력 그대로 echo).")
    user_scoped: bool = Field(
        default=True,
        description="항상 true — 본인 집계만(타 학생 데이터 0, 코호트 집계는 범위 밖).",
    )
    mode_filter: str | None = Field(description="응용 모드 스코프(예: suneung). 미지정이면 null.")

    verify_pass_rate: GrowthEvidenceMetricView = Field(description="① verify 통과율.")
    session_completion_rate: GrowthEvidenceMetricView = Field(description="③ 세션 완주율.")
    help_reduction_slope: GrowthEvidenceMetricView = Field(description="⑤ 도움 감소 곡선 기울기.")
    help_demand_supply_ratio: GrowthEvidenceMetricView = Field(
        description="⑮ 도움 요청 대 제공 비."
    )
    transfer_score: GrowthEvidenceMetricView = Field(description="⑦ 전이 점수(근사).")
    hint_depth_reached: GrowthEvidenceMetricView = Field(
        description=(
            "⑧ 답 미루기 도달 깊이 — R15 결합 판정이 교정기 함정 verdict면 value=null + 이 "
            "서빙 층 소유 서술(계약 모듈 원문 아님, 위 GrowthEvidenceMetricView 참조)."
        )
    )
    mastery_gain_rate: GrowthEvidenceMetricView = Field(description="⑨ BKT 숙달 증가율.")
    misconception_resolution_rate: GrowthEvidenceMetricView = Field(description="⑩ 오개념 해소율.")
    self_solve_rate: GrowthEvidenceMetricView = Field(description="⑪ 스스로 풀이 도달율.")
    # ② 진단정확도·④ 턴당 토큰 — INTERNAL_ONLY 2종은 여기 필드가 없다(구조적 배제. 값을
    # 넣고 걸러내는 게 아니라 애초에 자리 자체를 만들지 않는다).

    calibration_brier: GrowthEvidenceBrierView = Field(description="⑥ 보정 점수 — 3버킷 서술만.")


# `hint_depth_reached`가 R15 교정기 함정 조합 제약으로 보류될 때 노출할 서빙 층 소유
# 문장 — 계약 모듈의 `suppressed_reason` 원문(낙인성 verdict 코드명을 리터럴로 포함)을
# 그대로 내보내면 학생 대면 JSON에 낙인 라벨이 유출된다(이 태스크의 핵심 랜드마인). 계약의
# *판정*(exposable_now=False)은 그대로 신뢰하되 *서술*만 이 문장으로 교체한다 — 계약 로직
# 재구현이 아니라 표현 계층 소유권 이전이다.
# MISC-20 — ⑩ 오개념 해소율이 PROVISIONAL(근사·노출 보류)일 때 학생에게 나갈 서빙 층 소유
# 문장. 계약 모듈의 `suppressed_reason` 원문은 재승격 조건·`is_active`·`deactivated_reason`
# 같은 **내부 용어**를 담아 운영자용이다 — 그대로 내보내면 검수되지 않은 내부 진단 문구가 학생
# 대면 JSON에 흘러간다(`GrowthEvidenceMetricView`가 `Metric.note`를 뺀 것과 같은 이유).
# `hint_depth_reached` 랜드마인 방어와 동형: 계약의 *판정*은 그대로 신뢰하고 *서술*만 교체한다.
_RESOLUTION_RATE_SUPPRESSED_MESSAGE = (
    "오개념 극복 정도는 아직 정확하게 알려드리기 어려워요 — 지금 방식으로는 네가 실제로 넘어선 "
    "오개념과 잠시 나타나지 않은 오개념을 구분하지 못해요. 더 정확해지면 다시 보여드릴게요."
)

_HINT_DEPTH_SUPPRESSED_MESSAGE = (
    "지금은 이 지표만 따로 보여드리기 어려워요 — 힌트 사용 패턴과 정답률을 함께 살펴보는 "
    "중이에요. 대신 다른 성장 지표로 진행 상황을 확인해보세요."
)


def _render_growth_evidence_metric(
    metrics: SurrogateMetrics, field: str, exposure_by_field: dict[str, MetricExposure]
) -> GrowthEvidenceMetricView:
    """`SurrogateMetrics`의 `Metric` 1종 + 계약 판정 1종을 학생 노출 뷰로 렌더.

    `hint_depth_reached`이면서 exposable_now=False(R15 결합 판정이 교정기 함정 verdict)인
    단 하나의 경우만 value를 강제 null화하고 서술을 서빙 층 소유 문장으로 치환한다(랜드마인
    방어 — 모듈 상단 주석·`GrowthEvidenceMetricView.suppressed_reason` docstring 참조).
    그 밖의 모든 지표는 계약 판정을 그대로 통과시킨다.
    """
    metric = getattr(metrics, field)
    exposure = exposure_by_field[field]
    if exposure.tier is ExposureTier.PROVISIONAL:
        # MISC-20 집행 지점 — 계약이 근사로 판정한 값은 서빙 층을 통과하지 못한다(value null화).
        # 필드 자체는 남긴다(강등 ≠ 삭제 — 계산·내부 리포트는 유지되고 학생 노출만 멈춘다).
        # `status`는 정직하게 원값 그대로(계측은 됐고 노출만 보류라는 사실을 위장하지 않는다).
        return GrowthEvidenceMetricView(
            status=metric.status,
            value=None,
            exposable_now=False,
            suppressed_reason=_RESOLUTION_RATE_SUPPRESSED_MESSAGE,
        )
    if field == "hint_depth_reached" and not exposure.exposable_now:
        return GrowthEvidenceMetricView(
            status=metric.status,
            value=None,
            exposable_now=False,
            suppressed_reason=_HINT_DEPTH_SUPPRESSED_MESSAGE,
        )
    return GrowthEvidenceMetricView(
        status=metric.status,
        value=metric.value,
        exposable_now=exposure.exposable_now,
        suppressed_reason=exposure.suppressed_reason,
    )


@router.get(
    "/growth-evidence",
    response_model=GrowthEvidenceResponse,
    summary="내 성장 증거(WH-1 대리 지표) 학생 안전 노출 — 노출 계약 경유",
)
async def get_my_growth_evidence(
    request: Request,
    user: ConsentedUser,
    session: SessionDep,
    since: SinceParam = None,
    until: UntilParam = None,
    mode: HarnessMetricsMode = None,
) -> GrowthEvidenceResponse:
    """성장 증거(WH-1 대리 지표)를 *노출 계약*(`growth_evidence_exposure.py`)을 거쳐서만 노출.

    `GET /harness-metrics`(원시 표면·범위 밖 동결)와 달리 이 엔드포인트는
    `classify_metric_exposure`가 유일한 노출 판정 경로가 되도록 강제한다 — R15 결합 판정
    원본 필드·② 진단정확도·④ 턴당 토큰을 이 함수가 직접 읽지 않는다(계약 모듈만 읽는다).

    **랜드마인 방어**: 계약이 `hint_depth_reached`를 보류(exposable_now=False)할 때 반환하는
    `suppressed_reason` 원문은 낙인성 verdict 코드명을 리터럴로 포함한다 — 그대로 내보내면
    낙인 라벨이 학생 대면 JSON에 유출된다. `_render_growth_evidence_metric`이 이 한 경우만
    서빙 층 소유 문장으로 치환한다(계약의 *판정*은 그대로 신뢰 — 재구현 아님).

    `calibration_brier`는 원 스칼라를 절대 직렬화하지 않고 `narrate_calibration_brier`의
    3버킷 서술만 반환한다. 비교·서열·순위 파생 필드는 0종(계약 모듈의 의도적 부재를 API
    층에서도 유지).

    `since`/`until`/`mode`는 `GET /harness-metrics`와 동일 검증·의미(시간창 inclusive·
    TZ-aware ISO8601·naive/역전 422·mode=suneung이면 attempt_event 기반 지표 스코프).
    """
    # PED-08 도달 관측 — 원시 표면(/harness-metrics) 카운터와 *별도 슬롯*(섞이면 도달
    # 판정이 위장된다. `_growth_evidence_state.py` 모듈 docstring).
    get_growth_evidence_exposure_counters(request.app).record_request()
    since = _validate_tz_aware(since, "since")
    until = _validate_tz_aware(until, "until")
    _validate_time_window(since, until, "since", "until")
    metrics = await compute_wh1_surrogate_metrics(
        session, user_id=user.user_id, since=since, until=until, mode=mode
    )
    exposure_by_field = classify_metric_exposure(metrics)
    return GrowthEvidenceResponse(
        window_start=since,
        window_end=until,
        user_scoped=True,
        mode_filter=mode,
        verify_pass_rate=_render_growth_evidence_metric(
            metrics, "verify_pass_rate", exposure_by_field
        ),
        session_completion_rate=_render_growth_evidence_metric(
            metrics, "session_completion_rate", exposure_by_field
        ),
        help_reduction_slope=_render_growth_evidence_metric(
            metrics, "help_reduction_slope", exposure_by_field
        ),
        help_demand_supply_ratio=_render_growth_evidence_metric(
            metrics, "help_demand_supply_ratio", exposure_by_field
        ),
        transfer_score=_render_growth_evidence_metric(metrics, "transfer_score", exposure_by_field),
        hint_depth_reached=_render_growth_evidence_metric(
            metrics, "hint_depth_reached", exposure_by_field
        ),
        mastery_gain_rate=_render_growth_evidence_metric(
            metrics, "mastery_gain_rate", exposure_by_field
        ),
        misconception_resolution_rate=_render_growth_evidence_metric(
            metrics, "misconception_resolution_rate", exposure_by_field
        ),
        self_solve_rate=_render_growth_evidence_metric(
            metrics, "self_solve_rate", exposure_by_field
        ),
        calibration_brier=GrowthEvidenceBrierView(
            narrative=narrate_calibration_brier(metrics.calibration_brier.value)
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# COLLAB-03: 학습시간 통계 (학생 1인칭 좌석)
#
# `l2.learning_metrics_rollup`이 적재한 `daily_learning_metrics`를 **본인 것만** 노출한다.
# 이 좌석이 COLLAB-03의 존재 근거다 — 적재만 하고 조회 좌석을 배선하지 않으면
# `visualization_module_gap_review.md` D1(만들어 놓고 연결하지 않음)의 재발이다.
#
# 노출 경계(acceptance ⑦ — 절대 확장 금지):
#   · 축은 **학생 본인까지**다. `ConsentedUser.user_id`로만 스코핑하며 `user_id` 질의 파라미터를
#     받지 않는다(타인 조회 경로 자체가 없다).
#   · 부모·교사 등 **제3자 노출 엔드포인트를 여기에 만들지 않는다**. PIPA 권한 매트릭스상
#     이용 시간대는 교사 ✕·부모 ◐이므로, 제3자 축은 COLLAB-01 계약과 Phase 3 좌석을 거친다.
#   · `user_behavior_metrics`(hint 의존도 등 행동 지표)와 `problem_solve_time_distribution`
#     (교차 사용자 집계)은 이 좌석에서 노출하지 않는다 — 학습시간 통계에 필요하지 않고,
#     행동 지표의 학생 직노출은 게임화 억제 계약(PED-08)을 먼저 거쳐야 한다. 두 테이블은
#     본인 반출(`privacy/export.py`)·삭제권 경로로만 학생에게 닿는다.
# ──────────────────────────────────────────────────────────────────────────
MetricSince = Annotated[
    date | None,
    Query(description="이 날짜 *이후*(inclusive) 집계일만. YYYY-MM-DD. until과 함께 기간 필터."),
]
MetricUntil = Annotated[
    date | None,
    Query(description="이 날짜 *이전*(inclusive) 집계일만. YYYY-MM-DD. since와 함께 기간 필터."),
]


class LearningMetricsSummary(BaseModel):
    """조회 기간 전체(limit/offset 무관)의 학습시간 통계 합계 — 미측정은 None(0 아님)."""

    days_counted: int = Field(description="집계 행이 존재하는 날 수(활동이 있던 날).")
    total_minutes_active: int | None = Field(description="총 학습 시간(분). 측정치 없으면 null.")
    total_problems_attempted: int | None = Field(description="총 시도 문항 수.")
    total_problems_correct: int | None = Field(description="총 정답 문항 수.")
    total_socratic_turns: int | None = Field(description="총 소크라테스 상호작용 턴 수.")
    accuracy_rate: float | None = Field(
        description="정답률(정답/시도). 시도 0이면 null — 0.0으로 날조하지 않는다."
    )
    avg_minutes_per_active_day: float | None = Field(
        description="활동일 1일 평균 학습 시간(분). 활동일 0이면 null."
    )
    avg_focus_score: float | None = Field(description="기간 평균 집중도(0~1). 미측정이면 null.")


class LearningMetricsResponse(BaseModel):
    """`GET /v1/me/learning-metrics` 응답 — 기간 요약 + 일자별 원자료."""

    summary: LearningMetricsSummary
    days: list[DailyLearningMetricsSchema]


@router.get(
    "/learning-metrics",
    response_model=LearningMetricsResponse,
    summary="내 학습시간 통계",
)
async def get_my_learning_metrics(
    user: ConsentedUser,
    session: SessionDep,
    response: Response,
    limit: Limit = 90,
    offset: Offset = 0,
    since: MetricSince = None,
    until: MetricUntil = None,
    order: OrderParam = "desc",
    include_total: IncludeTotal = False,
) -> LearningMetricsResponse:
    """본인 일별 학습 지표 — 기본 최신순 90일. 타인 데이터는 조회 불가(user_id 스코핑).

    공급원은 `l2.learning_metrics_rollup`(하루 1회 CLI 롤업)이다. 롤업이 아직 돌지 않은 구간은
    행이 없으며 그때 `summary.days_counted == 0`으로 **비어 있음이 그대로 보인다** — 0으로
    채워 "활동 없음"처럼 위장하지 않는다.

    `summary`는 `limit`/`offset`과 무관하게 **필터 전체 구간**을 SQL 집계한 값이고, `days`는
    페이지 슬라이스다(총 건수는 `include_total=true` 시 `X-Total-Count` 헤더 — 기존 /me 규약).
    """
    # 뒤집힌 기간은 조용한 빈 결과가 아니라 422로 알린다(`_query_filters` 시간창 규약과 동형).
    if since is not None and until is not None and since > until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="since가 until보다 늦습니다.",
        )

    # 본인 스코핑이 항상 첫 조건 — 이 줄이 빠지면 전 학생 지표가 새어 나간다(⑦).
    conds = [DailyLearningMetrics.user_id == user.user_id]
    if since is not None:
        conds.append(DailyLearningMetrics.metric_date >= since)
    if until is not None:
        conds.append(DailyLearningMetrics.metric_date <= until)

    primary = (
        DailyLearningMetrics.metric_date.asc()
        if order == "asc"
        else DailyLearningMetrics.metric_date.desc()
    )
    page = await session.execute(
        select(DailyLearningMetrics).where(*conds).order_by(primary).limit(limit).offset(offset)
    )
    days = [row.to_schema() for row in page.scalars().all()]

    # 요약은 필터 전체 구간 SQL 집계(페이지와 독립). SUM은 표본 0이면 NULL을 반환하므로
    # "미측정"이 0으로 뭉개지지 않는다.
    agg = (
        await session.execute(
            select(
                func.count().label("days_counted"),
                func.sum(DailyLearningMetrics.minutes_active).label("minutes_active"),
                func.sum(DailyLearningMetrics.problems_attempted).label("attempted"),
                func.sum(DailyLearningMetrics.problems_correct).label("correct"),
                func.sum(DailyLearningMetrics.socratic_turns).label("socratic_turns"),
                func.avg(DailyLearningMetrics.avg_focus_score).label("avg_focus"),
            ).where(*conds)
        )
    ).one()

    days_counted = int(agg.days_counted or 0)
    minutes_active = None if agg.minutes_active is None else int(agg.minutes_active)
    attempted = None if agg.attempted is None else int(agg.attempted)
    correct = None if agg.correct is None else int(agg.correct)
    accuracy_rate: float | None = None
    if attempted is not None and attempted != 0 and correct is not None:
        accuracy_rate = round(correct / attempted, 4)
    summary = LearningMetricsSummary(
        days_counted=days_counted,
        total_minutes_active=minutes_active,
        total_problems_attempted=attempted,
        total_problems_correct=correct,
        total_socratic_turns=None if agg.socratic_turns is None else int(agg.socratic_turns),
        accuracy_rate=accuracy_rate,
        avg_minutes_per_active_day=(
            round(minutes_active / days_counted, 2)
            if minutes_active is not None and days_counted > 0
            else None
        ),
        avg_focus_score=None if agg.avg_focus is None else round(float(agg.avg_focus), 2),
    )

    await _maybe_set_total(
        session,
        response,
        include_total,
        select(func.count()).select_from(DailyLearningMetrics).where(*conds),
    )
    return LearningMetricsResponse(summary=summary, days=days)
