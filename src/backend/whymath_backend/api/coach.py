"""L4 교수학 코치 HTTP 표면 — `POST /v1/coach` + `POST /v1/coach/sessions`.

학생 발화·Polya 상태(+옵션 숙달도)를 받아 *통합 결정*을 반환한다. L4 슬라이스 1-5의 모든
결정 함수를 한 발화로 묶는 엔드포인트:
- `PolyaCoach.decide()` — 단계 전이·prompt 조립·socratic_category·hint_level·reveals
- `diagnose()` — 오개념 후보 top-K
- `select_intervention()` — top-1 신뢰도 0.5+ 시 개입 결정
- `adapt_lthc()` — 숙달도 제공 시 진입점·확장·비계 조정

**경계**:
- `/v1/coach` — *stateless* (state in/out·DB 무접근·LLM 호출 0).
- `/v1/coach/sessions` — *DB 쓰기*(새 dialogue + 학생/AI 2턴 영속). AI 턴 발화는 WH-1
  primary(`wh1_primary_enabled` 기본 ON·2026-07-20 GA)가 LLM으로 승격하고, 실패·타임아웃·
  플래그 OFF면 결정론 `decision.prompt`로 폴백한다(`_wh1_primary_decision_or` 참조).
- 인증 = `ConsentedUser`(미성년 동의 게이트 통과) — 학생 발화는 PII 가능(CLAUDE.md).
- 응답에 `system`/`prompt` 본문이 노출되므로 *학생 발화를 그대로 에코하지 않음*(에코 시
  필터·검증 없이 표면화될 위험).
- 미성년 채팅 평문 저장(CLAUDE.md 금기)은 *저장 계층 책임*(DB 암호화 at-rest·미들웨어).
  본 라우터는 schema/ORM의 기존 방침을 따라 평문 저장 + docstring 상기만(슬라이스 1
  schema 노트와 동일 — `schema/dialogue.py` 모듈 docstring 참조).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Annotated, Literal, NamedTuple

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api._auth import ConsentedUser
from whymath_backend.api._concurrency import etag_for, matches_if_none_match
from whymath_backend.api._crypto import (
    SupportsEnvelope,
    encrypt_dialogue_content,
    encrypt_dialogue_image_analysis,
    encrypt_dialogue_image_uri,
    require_dialogue_content_cipher,
    require_student_work_cipher,
    resolve_dialogue_content,
    resolve_dialogue_image_analysis,
    resolve_dialogue_image_uri,
)
from whymath_backend.api._l3_state import (
    CACHE_KEY as _CACHE_KEY,
)
from whymath_backend.api._l3_state import (
    PROVIDER_KEY as _PROVIDER_KEY,
)
from whymath_backend.api._l3_state import (
    TRACE_KEY as _TRACE_KEY,
)
from whymath_backend.api._misconception_state import get_semantic_matcher
from whymath_backend.api._rate_limit import (
    RateLimitedTripleRead,
    RateLimitedTripleWrite,
)
from whymath_backend.api._segmentation_state import (
    SolutionSegmentationCounters,
    get_segmentation_counters,
)
from whymath_backend.api._subject_capability_state import (
    get_answer_form_verifier,
    get_final_answer_verifier,
    get_step_chain_verifier,
)

# EOS-69: 상태 어휘·연쇄 결과 타입은 schema의 중립 계약에서 읽는다(수학 모듈 의존 제거).
# EOS-89: 능력 *구현*은 `composition`에서 끌어오지(pull) 않고 app.state에서 받는다(push) —
# 아래 `_get_subject_capabilities` Depends. 이 모듈에 `composition` import가 없는 것이 그 증거다.
from whymath_backend.config import get_settings
from whymath_backend.db.models.activity import AttemptEvent as AttemptEventORM
from whymath_backend.db.models.activity import ProblemAttempt as ProblemAttemptORM
from whymath_backend.db.models.concept import Concept
from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
from whymath_backend.db.models.dialogue import DialogueTurn as DialogueTurnORM
from whymath_backend.db.models.problem import Problem as ProblemORM
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.harness.wh1_primary import run_wh1_primary_turn
from whymath_backend.harness.wh1_shadow import observe_wh1_harness_shadow
from whymath_backend.l1.embedding_provider import build_provider
from whymath_backend.l1.standards.alignment_query import (
    AlignmentAxis,
    get_alignments,
    log_join_stats,
)
from whymath_backend.l2 import (
    AbilityReading,
    get_current_ability,
    get_current_mastery,
    get_current_theta,
    get_primary_concept_id,
    theta_to_mastery_proxy,
)
from whymath_backend.l2.attempt_skill_event import AttemptSource, record_attempt_skill_event
from whymath_backend.l2.mastery_tracking import record_problem_attempt_mastery
from whymath_backend.l2.prerequisite_recommendation import recommend_prerequisite_gaps
from whymath_backend.l2.skill_mastery_tracking import record_problem_attempt_skill_mastery
from whymath_backend.l3.interfaces import (
    CacheBackend,
    LLMProvider,
    TraceSink,
)
from whymath_backend.l3.pregenerate.validator import (
    arithmetic_validator,
    validate_response,
)
from whymath_backend.l4 import (
    CoachingFocus,
    CoachingTrigger,
    LthcAdaptation,
    MasteryLevel,
    PedagogyDecision,
    PolyaCoach,
    PolyaState,
    SolutionCoaching,
    adapt_lthc,
    focus_to_socratic_category,
    mastery_to_level,
    recommend_coaching_for_solution,
)
from whymath_backend.l4.completion import (
    CompletionAction,
    decide_completion,
)
from whymath_backend.l4.hint_deferral import is_answer_demand, is_stuck_turn_count
from whymath_backend.l4.misconception import (
    InterventionDecision,
    MisconceptionMatch,
    combine_diagnoses,
    correct_form_present,
    diagnose,
    reject_refuted,
    select_intervention,
    select_intervention_from_hypotheses,
)
from whymath_backend.l4.misconception.catalog import CATALOG, CATALOG_BY_ID
from whymath_backend.l4.misconception.evidence_store import (
    CORRECT_FORM_DEMONSTRATED,
    log_evidence,
)
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.misconception.hypothesis_store import curate_hypothesis
from whymath_backend.l4.misconception.judge import JudgeProtocol, LLMJudge, judge_filter
from whymath_backend.l4.misconception.judge_seam import L3JudgeSeam
from whymath_backend.l4.misconception.match_gate import apply_match_quality_gate
from whymath_backend.l4.misconception.probe_selection import is_exploration_turn
from whymath_backend.l4.misconception.shadow import (
    _spawn,
    observe_misconception_judge_shadow,
    observe_misconception_shadow,
)
from whymath_backend.l4.misconception.warmstart import assemble_warmstart_probe_hints
from whymath_backend.l4.models import next_polya_stage
from whymath_backend.l4.pedagogy.k_type_resolver import k_type_query
from whymath_backend.l4.pedagogy.pack_registry import get_pack
from whymath_backend.l4.prerequisite_coaching import recommend_prerequisite_coaching
from whymath_backend.l4.session_recall import SessionRecall, assemble_session_recall
from whymath_backend.l4.socratic.categories import SocraticCategory
from whymath_backend.l4.turn_meta import (
    TurnMeta,
    TurnMetaRow,
    classify_student_intent,
    compose_understanding_signal,
    derive_polya_state,
    derive_recent_categories,
    detect_state_mismatch,
    resolve_socratic_strategy,
    stage_to_targeted_step,
)
from whymath_backend.schema.answer_form import FormVerdict
from whymath_backend.schema.dialogue import Dialogue as DialogueSchema
from whymath_backend.schema.dialogue import DialogueTurn as DialogueTurnSchema
from whymath_backend.schema.enums import ContentType, EventType, Persona, StepType, TurnRole
from whymath_backend.schema.event_data_contract import build_event_data
from whymath_backend.schema.pedagogy_pack import PedagogyPack
from whymath_backend.schema.verification_capabilities import (
    AnswerFormVerifier,
    ChainVerificationCounts,
    FinalAnswerVerifier,
    StepChainVerifier,
    VerificationOutcome,
)

router = APIRouter(prefix="/v1", tags=["coach"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
# NLP-03 acceptance ③ — 0-전이 제출 관측 카운터(`api/_segmentation_state.py`). 세 핸들러
# (`/coach`·`/coach/sessions`·`/coach/sessions/{id}/turns`) 공통 주입 좌석.
SegmentationCountersDep = Annotated[
    SolutionSegmentationCounters, Depends(get_segmentation_counters)
]

logger = logging.getLogger(__name__)

_coach = PolyaCoach()  # 상태 비저장 — 단일 인스턴스 재사용

# slice 106: 오개념 진단 결합(substring + 의미)에서 *결합 끝* top_k 컷에 쓰는 상수.
# `_DEFAULT_TOP_K`=3은 diagnose 기본(노출 상한 top-3·CoachResponse.misconceptions 계약)과 정합.
# `_FANOUT`은 결합 *전* 양쪽을 넉넉히 뽑는 폭 — substr/semantic을 미리 top_k로 자르면 한쪽이
# 다른 쪽을 밀어내므로, 카탈로그 전수(len(CATALOG)=30종·선형 스캔이라 저렴)로 뽑아 결합 끝에서만
# 자른다. substring도 _FANOUT으로 뽑아 semantic-only가 substr를 부당히 잘라내지 않게 한다.
_DEFAULT_TOP_K = 3
_FANOUT = len(CATALOG)

# slice 73: θ 기반 BKT↔θ 교차검증 코칭 중 *노출*할 포커스 — 불일치(consolidate·retrieval)만.
# verify(계산오류)는 arithmetic_error 경로로 별도 노출·합의(foundation/advance)는 LTHC가 담당·
# diagnose(한쪽 신호만·θ 희소)는 비노출. `_build_response_payload` 노출 게이트에서 사용.
_THETA_SURFACED_FOCI: frozenset[str] = frozenset({"consolidate", "retrieval"})

# WH-1 §2.3 — clean하게 검증된 풀이 1턴이 *현재 의심* 오개념에 주는 *약한* 반박 가중(−1 polarity).
# net_support=Σ(polarity×weight)라, 강한 실제 오개념(다회 +1·weight≤1.0 누적)은 한 turn(−0.5)으로
# 죽지 않고 약·stale 의심만 누적으로 archived된다(낙인 방지하며 실신호 보존·CLAUDE.md #1). 0.5는
# KPI 튜닝 대상(#266 신뢰 floor 0.65 선례처럼 상수로 노출해 A/B 조정 여지를 남긴다).
_REFUTE_WEIGHT: float = 0.5

# WH-1 §2.3 정밀 귀속 — 검증 풀이가 *특정 오개념의 정정 형태*(`correct_form`)를 실제로 보일 때 주는
# *강한* 반박 가중. 막연한 clean 작업(0.5)과 달리 "학생이 M의 올바른 형태를 직접 보였다"는 정밀
# 모순이라 만점 매치(weight 1.0)와 대칭되는 강도를 준다 — 단발 정정이 confident 단일 매치(+1.0)를
# *즉시* 지우진 않고(net 0·archived 아님) 반복·decay와 합쳐 죽인다(신호 보존). 1.0은 KPI 튜닝 대상.
_REFUTE_STRONG_WEIGHT: float = 1.0


class CoachRequest(BaseModel):
    """`/v1/coach` 요청 본문 — 학생 발화·현재 상태·옵션 숙달도."""

    model_config = ConfigDict(extra="forbid")

    student_input: str = Field(
        min_length=0,
        max_length=4000,
        description="학생 발화(자연어). 빈 문자열 허용(첫 진입). 길이 상한은 남용·비용 방어.",
    )
    student_solution: str | None = Field(
        default=None,
        max_length=4000,
        description=(
            "학생의 *풀이/작업* 텍스트(예: L5 OCR로 인식한 손글씨 풀이) — 대화 발화"
            "(`student_input`)와 분리. 계산 슬립 검증(`solution_coaching`)은 이 필드가 "
            "있으면 *이 필드*를 대상으로 한다(없거나 빈 문자열이면 `student_input` 폴백 — "
            "발화에 풀이가 인라인일 수 있음). L5 OCR 결과의 자연 착지점(slice 54 한글 산문 "
            "검출과 결합). Polya·오개념·LTHC 결정은 여전히 `student_input` 기준(대화 흐름)."
        ),
    )
    polya_state: PolyaState = Field(
        default_factory=PolyaState,
        description="세션의 현재 Polya 상태. 기본값=UNDERSTAND 진입.",
    )
    mastery_level: MasteryLevel | None = Field(
        default=None,
        description="학생 숙달도 라벨(있을 때만 LTHC 조정안 반환).",
    )
    bkt_mastery: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "L2 BKT 숙달도(0~1). `mastery_level` 미지정 시 이 값을 라벨로 환산해 LTHC 도출"
            "(slice 25 `mastery_to_level`). `mastery_level`이 있으면 그쪽 우선."
        ),
    )
    coaching_focus: CoachingFocus | None = Field(
        default=None,
        description=(
            "L2 진단(`/me/diagnosis/concepts`)이 권한 코칭 포커스(slice 20). 주면 응답의 "
            "`entry_socratic_category`를 그 포커스에 맞춰 시드(대화 진입 질문 종류)."
        ),
    )
    solution_steps: list[str] | None = Field(
        default=None,
        description=(
            "L5가 공간정보로 분해한 풀이 단계 시퀀스(표현식 리스트). 제공 시 "
            "`verify_solution`으로 단계별(전이별) 검증을 수행해 검산 코칭을 정밀화하고 "
            "`solution_coaching.solution_verification`으로 노출한다(텍스트 신호와 *추가적 OR* "
            "결합). 미제공 시 텍스트 레벨 폴백 — 기존 동작 완전 불변. 텍스트→단계 *분해*는 "
            "L5 OCR 책임이라 백엔드는 제공된 단계만 검증한다."
        ),
    )
    solution_step_types: list[StepType] | None = Field(
        default=None,
        description=(
            "전이별 단계 유형(조건해석/케이스분류/그래프스케치/계산/검산). 제공 시 "
            "`verify_solution`이 비대수 단계를 unverifiable로 보수 처리하는 데 쓴다. 길이는 "
            "전이 수(`len(solution_steps)-1`)와 같아야 한다(규약·길이 검증은 `verify_solution` "
            "위임). 미제공 시 모든 전이를 타입 미지정으로 검증."
        ),
    )
    ocr_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "학생 풀이가 L5 OCR 산출물일 때 인식 신뢰도(0~1). 제공+<0.8이면 §3.3 게이트 ②로 "
            "`match_low_quality`를 표시해 L5가 재확인을 유도. None=OCR 아님/미제공→dormant "
            "(low_quality 항상 False·기존 동작 완전 불변). 이 값은 *입력 품질* 신호지 매칭 "
            "오류가 아니며, 매칭을 비우지 않는다(플래그만)."
        ),
    )
    mode: Literal["suneung"] | None = Field(
        default=None,
        description=(
            "S3-03 응용 모드 태그 — 'suneung'이면 이 코칭 턴이 *수능 세션*의 일부임을 표식한다"
            "(`GET /me/next-problem?mode=suneung` 값 공간과 정합). 스테이트풀 세션(세션 생성·턴 "
            "추가)에서 검산/힌트 `attempt_event.event_data`에 실려 mode-scoped 측정을 가능하게 "
            "한다(수능 세션 식별). **None(기본)이면 기존 동작 완전 불변(회귀 0)** — 이벤트 mode "
            "태그가 None이라 mode-agnostic 집계 그대로. stateless `/v1/coach`는 이벤트를 적재하지 "
            "않아 이 값이 소비되지 않는다(무해). 멀티턴은 클라가 매 턴 같은 mode를 실어 보낸다."
        ),
    )
    persona: Persona | None = Field(
        default=None,
        description=(
            "S3-03 대상 페르소나 태그(선택) — 수능 모드 세션의 응시 페르소나(A/B/C 등). 제공 시 "
            "검산/힌트 이벤트에 `persona` 값 문자열로 실려 후속 per-persona 측정을 돕는다. None"
            "(기본)이면 미태깅(기존 동작 불변). `mode`와 독립적으로 실린다."
        ),
    )


class CoachResponse(BaseModel):
    """`/v1/coach` 응답 — 통합 교수학 결정.

    `decision`은 *반드시* 채워지고(`PolyaCoach.decide()`는 항상 결정 반환), 나머지는 조건부.
    """

    model_config = ConfigDict(extra="forbid")

    decision: PedagogyDecision = Field(
        description="Polya 단계 전이·프롬프트·hint_level·socratic_category 등 핵심 결정.",
    )
    misconceptions: list[MisconceptionMatch] = Field(
        default_factory=list,
        description="오개념 후보 top-3(없으면 빈 리스트). confidence 내림차순.",
    )
    intervention: InterventionDecision | None = Field(
        default=None,
        description=(
            "top-1 misconception이 신뢰도 0.5+면 개입 결정(반례 유도/거꾸로 사고)."
            " 미만이면 None — 진단 보류(라벨링 회피)."
        ),
    )
    lthc: LthcAdaptation | None = Field(
        default=None,
        description="요청에 `mastery_level`이 있을 때만 LTHC 조정안. 없으면 None.",
    )
    entry_socratic_category: SocraticCategory | None = Field(
        default=None,
        description=(
            "요청에 `coaching_focus`가 있을 때만 — 진단 포커스가 권한 대화 진입 소크라테스 "
            "카테고리(slice 22). PolyaCoach의 매 턴 `decision.socratic_category`와 별개(진입 시드)."
        ),
    )
    solution_coaching: SolutionCoaching | None = Field(
        default=None,
        description=(
            "학생 풀이(`student_solution` 우선·없으면 `student_input`)에서 *거짓 수치 관계*"
            "(계산 슬립, 예: '2+3=6')가 L3 결정론 검증으로 "
            "검출되면 검산(verify) 코칭 + L3 신호(slice 52 오케스트레이터). 없으면 None — "
            "이때는 기존 `decision`/`coaching_focus`를 따른다. *실시간 슬립은 배경 진단보다 "
            "우선*(slice 51: 구체적 계산 오류 > θ/숙달 추정). 검증기는 보수적이라 질문·산문은 "
            "거의 발화하지 않는다(false-positive 0 우선). 요청에 `solution_steps`가 있으면 "
            "`solution_verification`(verify_solution 단계별 결과)이 채워지고 단계 레벨 incorrect는 "
            "텍스트 신호와 *추가적 OR*로 결합돼 verify 코칭을 깨운다(미제공 시 None·동작 불변)."
        ),
    )
    prerequisite_coaching: CoachingTrigger | None = Field(
        default=None,
        description=(
            "이 문제 개념의 막힌 선수가 있으면 '선수 복습 먼저' 코칭(L4 prerequisite_review)·"
            "없으면 null. Polya 결정과 *별개의 추가 신호* — 클라/L5가 우선 제시 여부 결정."
        ),
    )
    match_low_quality: bool = Field(
        default=False,
        description=(
            "§3.3 게이트 ② — 요청 `ocr_confidence`가 제공되고 0.8 미만이면 True. 학생 풀이가 "
            "OCR로 오염됐을 수 있으니 L5/LLM이 *재확인을 유도*하라는 신호다. 매칭은 *유지*되고 "
            "(이 플래그는 매칭을 비우지 않는다) intervention도 변경하지 않는다 — 백엔드는 신호만 "
            "노출하고 재확인 발화 생성·intervention 보류는 후속(L5)이 맡는다. `ocr_confidence` "
            "미제공(None)이면 항상 False(기존 동작 불변)."
        ),
    )
    match_attribution_unclear: bool = Field(
        default=False,
        description=(
            "MISC-28 게이트 ③ — 학생 풀이에 정정 어구가 있으나 그것이 top-1 오개념을 가리키는지 "
            "판정할 수 없을 때 True. 앞쪽 정정에는 정당한 반박(`틀린 풀이: <오개념>`)과 무관한 "
            "정정(`부호를 잘못 옮겨 적었지만 <오개념>`)이 **위치로 구별되지 않게** 섞여 있어, "
            "어느 쪽으로 단정해도 학생에게 *틀린 확신*이 나간다(실측 교환표: 억제하면 오억제 "
            "66/66, 무시하면 선행정정 사각 66/66). 그래서 매칭은 *유지*하되 L5/LLM이 단정 대신 "
            "**확인 질문**('이 부분을 정정한 것인가요?')을 내라는 신호다 — `match_low_quality`와 "
            "같은 좌석이며 출처만 다르다(그쪽=입력 OCR 품질·이쪽=L4 귀속 판정). 정정 어구가 "
            "신호 *뒤*면 귀속이 어순으로 확정돼 후보에서 아예 빠지므로 이 플래그로 오지 않는다."
        ),
    )
    no_confident_match: bool = Field(
        default=False,
        description=(
            "§3.3 게이트 ① — top-1 신뢰도가 0.65 미만이라 후보를 *비웠는지* 여부(억지 매칭 금지). "
            "True면 `misconceptions`는 빈 리스트다 — '매칭 없음'(애초에 후보 0)과 '약해서 비움'을 "
            "구분하는 신호. 게이트가 비우던 기존 동작의 *노출*일 뿐 매칭 결과 자체는 불변."
        ),
    )


class SessionCreateRequest(CoachRequest):
    """`/v1/coach/sessions` 요청 — `CoachRequest` + 선택적 problem_id(FK).

    S3-03: `mode`·`persona`(응용 모드/페르소나 태그)는 `CoachRequest`에서 상속한다 — 세션 생성
    턴의 검산/힌트 이벤트에 실려 수능 세션을 측정 계층에서 식별 가능하게 한다(멀티턴은 turns
    요청에도 같은 값을 실어 보낸다).
    """

    problem_id: uuid.UUID | None = Field(
        default=None,
        description="이 대화가 속한 문제(있으면 dialogue.problem_id로 영속·없으면 NULL).",
    )


# WH-1 2단계 §8.4 슬라이스 3: 활성 가설 세트 노출 필드 설명(SessionCreateResponse·
# TurnAppendResponse 공통). stateless `CoachResponse`에는 *싣지 않는다* — stateless 경로는
# DB가 없어 가설을 영속·누적할 수 없기 때문(슬라이스 3 결선은 세션 엔드포인트 한정).
# PED-04 D2: 클라 제출 Polya 상태와 서버 파생 상태가 어긋났음을 알리는 플래그(세션 2응답 공통).
# stateless `CoachResponse`에는 *싣지 않는다* — 그 경로는 DB가 없어 서버 파생 자체가 불가능하고,
# 필드를 넣으면 항상 False인 가짜 계기판이 된다(OpenAPI 스키마 무변경 = 클라 회귀 0).
_CLIENT_STATE_MISMATCH_DESC = (
    "클라이언트가 제출한 `polya_state`가 서버 파생 상태(직전 턴 메타·힌트 적재에서 역산)와 "
    "달랐는지. **true여도 요청은 정상 처리되며, 결정은 서버 파생값으로 내려간다** — 이 값은 "
    "오류가 아니라 *동기화 신호*다(클라가 상태를 갱신하면 사라진다). S3 파일럿 KPI가 이 상태값에 "
    "의존하므로, 어긋남을 조용히 덮지 않고 표면화한다(침묵 실패 금지)."
)

_ANSWER_FORM_DESC = (
    "이 턴 제출답이 문항의 **표기 지시**(예: '기약분수로 나타내시오')를 따랐는지 — EOS-28. "
    "값 정오와 **완전히 별개 축**이다: `violated`여도 답은 맞을 수 있고, 완료(problem_complete)를 "
    "막지 않는다. 4상태 — `satisfied`(지켰다)·`violated`(안 지켰다·오답 아님)·"
    "`not_required`(이 문항엔 형태 요구가 없음)·`unverifiable`(요구는 있으나 판정 못 함). "
    "`not_required`를 `satisfied`와 구분하는 이유: 문항의 99%는 형태 요구가 없어서, 합치면 "
    "형태 준수율이 99%로 부풀어 오른다(요구 없음 ≠ 지켰음). **클라 사용 규약**: `violated`는 "
    "오답 표시나 제출 차단에 쓰지 않는다 — '값은 맞았고, 기약분수로 바꾸면 어떻게 될까?' 같은 "
    "*추가 안내*로만 쓴다(부정 강화 금지·학생 입력 거부 금지). stateless `/v1/coach`에는 싣지 "
    "않는다 — DB 없이는 문항 제약을 읽을 수 없어 항상 `not_required`인 가짜 계기판이 된다."
)

_ACTIVE_HYPOTHESES_DESC = (
    "이 학생의 *누적·감쇠된* 활성 오개념 가설 세트(confidence 내림차순). 매 턴 매칭(증거)으로 "
    "갱신·영속되며, 증거가 끊긴 가설은 감쇠하고 임계 미만이면 가지치기된다. 각 항목은 *확정 "
    "오개념이 아니라 후보*다(낙인 금지 — `misconceptions`와 동형 노출). 학생 *본인*의 가설만 "
    "노출되며(ConsentedUser 게이트 통과), 민감정보 평문 저장·동의는 저장/동의 계층(암호화·"
    "미들웨어·PIPA 권한 매트릭스) 책임이다. 매칭이 없으면 빈 리스트. select_focus 기반 개입 "
    "변경·evidence_links(증거 연결)·진단 일치율 게이트는 후속 슬라이스(이번은 per-turn 영속+노출)."
)


# S3-32 완료 통합 — 세션/턴 응답 완료 필드 설명(SessionCreateResponse·TurnAppendResponse 공통).
_PROBLEM_COMPLETE_DESC = (
    "이 턴에 문제가 *완료*됐는지 — **클라가 '다음 문항으로 진행'을 판단하는 신호**. 완료는 오직 "
    "풀이 제출(body.solution_steps 마지막 단계가 서버 verify로 correct)로 정답 도달을 감지한 뒤, "
    "*Polya 돌아보기(메타인지) 1턴*을 거쳐서만 True가 된다(별도 '정답 제출' 버튼 대체). True면 "
    "서버가 ProblemAttempt(is_correct=True)를 *이미 적재*하고 숙달을 전파했으므로 **클라는 별도로 "
    "POST /v1/me/attempts를 부르지 않는다**(중복 적재 금지). incorrect/미검증이면 항상 False."
)
_AWAITING_REFLECTION_DESC = (
    "정답에 도착해 완료 *직전 돌아보기(메타인지) 응답을 대기* 중인지 — 코치가 '왜 이 답이 "
    "나왔는지' 설명을 요청한 상태다. True면 이번 턴은 완료가 아니며(problem_complete=False) 학생의 "
    "근거 응답 다음 턴에 완료된다(MVP=1턴). 클라는 이 신호로 '돌아보기 1턴' UX(진행 보류)를 표시."
)
_COMPLETED_ATTEMPT_ID_DESC = (
    "완료 시(problem_complete=True) 서버가 적재한 ProblemAttempt PK. 완료가 아니면 None. 클라가 "
    "필요 시 이 attempt를 참조할 수 있게 노출한다(적재 자체는 서버가 이미 수행·클라 재적재 불요)."
)


class SessionCreateResponse(CoachResponse):
    """`/v1/coach/sessions` 응답 — `CoachResponse` + 영속된 dialogue/turn ID + 활성 가설 세트."""

    dialogue_id: uuid.UUID = Field(description="새로 생성된 대화 PK.")
    student_turn_id: uuid.UUID = Field(description="학생 발화 턴 PK(turn_order=1).")
    assistant_turn_id: uuid.UUID = Field(
        description="AI 결정 턴 PK(turn_order=2, content=decision.prompt)."
    )
    active_hypotheses: list[MisconceptionHypothesis] = Field(
        default_factory=list,
        description=_ACTIVE_HYPOTHESES_DESC,
    )
    wh1_turn_index: int = Field(
        ge=1, description="이 교환의 WH-1 턴 번호(1-기반·세션 누적·ε-탐색 카운터·§2.2). 생성=1."
    )
    wh1_exploration_turn: bool = Field(
        description="이 턴이 ε-탐색 강제 턴인지(기본 5턴마다·활성 세트 밖 프로브 의무·§2.2 규칙2)."
    )
    client_state_mismatch: bool = Field(
        default=False,
        description=_CLIENT_STATE_MISMATCH_DESC,
    )
    problem_complete: bool = Field(default=False, description=_PROBLEM_COMPLETE_DESC)
    awaiting_reflection: bool = Field(default=False, description=_AWAITING_REFLECTION_DESC)
    completed_attempt_id: uuid.UUID | None = Field(
        default=None, description=_COMPLETED_ATTEMPT_ID_DESC
    )
    answer_form: FormVerdict = Field(
        default=FormVerdict.not_required, description=_ANSWER_FORM_DESC
    )


class TurnAppendResponse(CoachResponse):
    """`/v1/coach/sessions/{id}/turns` 응답 — `CoachResponse` + 추가 턴 PK·turn_order."""

    student_turn_id: uuid.UUID = Field(description="추가된 학생 턴 PK(turn_order=직전+1).")
    assistant_turn_id: uuid.UUID = Field(
        description="추가된 AI 턴 PK(turn_order=직전+2, content=decision.prompt)."
    )
    student_turn_order: int = Field(
        ge=1, description="학생 턴 순번(append 후 dialogue.total_turns에 반영)."
    )
    assistant_turn_order: int = Field(ge=1, description="AI 턴 순번(=student_turn_order + 1).")
    active_hypotheses: list[MisconceptionHypothesis] = Field(
        default_factory=list,
        description=_ACTIVE_HYPOTHESES_DESC,
    )
    wh1_turn_index: int = Field(
        ge=1, description="이 교환의 WH-1 턴 번호(1-기반·세션 누적·ε-탐색 카운터·§2.2)."
    )
    wh1_exploration_turn: bool = Field(
        description="이 턴이 ε-탐색 강제 턴인지(기본 5턴마다·활성 세트 밖 프로브 의무·§2.2 규칙2)."
    )
    client_state_mismatch: bool = Field(
        default=False,
        description=_CLIENT_STATE_MISMATCH_DESC,
    )
    problem_complete: bool = Field(default=False, description=_PROBLEM_COMPLETE_DESC)
    awaiting_reflection: bool = Field(default=False, description=_AWAITING_REFLECTION_DESC)
    completed_attempt_id: uuid.UUID | None = Field(
        default=None, description=_COMPLETED_ATTEMPT_ID_DESC
    )
    answer_form: FormVerdict = Field(
        default=FormVerdict.not_required, description=_ANSWER_FORM_DESC
    )


class SessionGetResponse(BaseModel):
    """`GET /v1/coach/sessions/{id}` 응답 — dialogue 메타 + turn 목록(turn_order 정렬)."""

    model_config = ConfigDict(extra="forbid")

    dialogue: DialogueSchema = Field(description="대화 세션 메타데이터.")
    turns: list[DialogueTurnSchema] = Field(
        default_factory=list,
        description="대화 턴(turn_order ASC). 학생 발화·AI 결정 본문 포함 — PII 가능.",
    )


def _ability_level(bkt_mastery: float | None, theta: float | None) -> MasteryLevel | None:
    """BKT 숙달(0~1)과 신뢰 θ(logistic 프록시)를 평균해 적응형 스캐폴딩용 ability 라벨 산출.

    힌트(`decide_hint_level`)·Polya 전이(`should_advance`)·LTHC(`adapt_lthc`)가 공유하는
    `mastery_level` 라벨을 *능력 θ까지 반영*해 만든다(slice 77). 둘 다 None이면 None·한쪽만
    있으면 그 신호·둘 다면 평균→`mastery_to_level`. θ는 `_build_response_payload`에서 이미
    slice 76 게이트(`_server_theta_for`)를 통과한 값(신뢰 θ만)이라 여기선 추가 게이팅 불필요.
    """
    proxy = theta_to_mastery_proxy(theta) if theta is not None else None
    parts = [v for v in (bkt_mastery, proxy) if v is not None]
    if not parts:
        return None
    return mastery_to_level(sum(parts) / len(parts))


class _StepVerificationCarry(NamedTuple):
    """S4-19: *게이트 이전* 단계 검증 결과의 적재 전용 운반 컨테이너(노출 아님).

    `_build_response_payload`의 노출 게이트(`_THETA_SURFACED_FOCI`)는 전단계-correct 제출·
    ocr_gated 보류 케이스에서 `solution_coaching`을 None으로 걸러낸다 — 게이트 *이후* 값만
    적재하면 불합격 편향 회계가 되므로, 적재(`_log_verify_event`)는 이 컨테이너로 게이트
    *이전* 값(sol.solution_verification·sol.verification_ocr_gated)을 받는다. HTTP 응답
    (CoachResponse)에는 싣지 않는다 — 노출은 기존 solution_coaching 게이트 그대로다.
    """

    verification: ChainVerificationCounts | None
    """verify_solution 원 결과(단계 미제출·전이 0이면 None) — 카운트만 적재에 쓴다.

    `ChainVerification`이 아니라 카운트 확장인 이유: 이 운반값의 유일한 소비처가
    `_log_verify_event`(계측 적재 좌석)이고 거기서 상태별 카운트·보류 사유 분포를 읽는다.
    채점(`partial_credit`)은 좁은 쪽만 요구한다 — 계약을 필요만큼만 쓰는 것이 분리의 요점이다."""

    ocr_gated: bool | None
    """SolutionCoaching.verification_ocr_gated(verification 객체가 아닌 형제 필드) 운반."""


def _build_response_payload(
    body: CoachRequest,
    *,
    problem_id: uuid.UUID | None = None,
    expected_answer: str | None = None,
    server_mastery: float | None = None,
    server_theta: float | None = None,
    matches: list[MisconceptionMatch] | None = None,
    misconception_hypotheses: list[MisconceptionHypothesis] | None = None,
    pack: PedagogyPack | None = None,
    polya_state_override: PolyaState | None = None,
    recent_categories: Sequence[SocraticCategory] = (),
    grade: int | None = None,
    standard_code: str | None = None,
    step_chain_verifier: StepChainVerifier | None = None,
) -> tuple[
    PedagogyDecision,
    list[MisconceptionMatch],
    InterventionDecision | None,
    LthcAdaptation | None,
    SocraticCategory | None,
    _StepVerificationCarry,
    SolutionCoaching | None,
]:
    """공통 결정 계산 — `/v1/coach`·`/v1/coach/sessions`·turns append 셋 다 사용.

    `problem_id`·`expected_answer`(slice 64)는 step shadow 진단 맥락으로만 하류 전달되고
    반환(노출 payload)엔 *싣지 않는다*. stateless `/v1/coach`는 DB가 없어 None(맥락 없음),
    세션 엔드포인트는 서버 DB 조회값을 넘긴다 — `expected_answer`(정답)는 결코 응답에 노출하지
    않는다(student-facing이면 정답 누출).

    slice 106: `matches`(오개념 후보)를 *주입*받으면 그 리스트를 그대로 쓴다(핸들러가
    `_compute_matches`로 substring+의미 결합을 미리 비블로킹 계산). **미주입(기본 None)이면
    `diagnose(body.student_input)`로 폴백** — 게이트 off·직접 호출(`TestThetaIntoScaffolding`
    sync 직접호출) 시 *현행 동작과 비트동일*이다(추가 인자는 기본값 only·sync성·반환 튜플 형태
    불변). `intervention`은 *결합 후* matches[0] 기준(combine_diagnoses가 substr 우선이라
    substr 진단이 있으면 그대로 1위 유지).

    `misconception_hypotheses`(누적 활성 가설 세트·confidence 내림차순)를 주입받으면 `decide`로
    thread해 *소크라테스 카테고리*를 정밀화한다 — 학생이 머무르며 막혀 있고 명시 신호가 없을 때
    고신뢰+최근 가설이면 ASSUMPTION(가정 표면화). **미주입(기본 None)이면 현행 비트동일**
    (stateless `/v1/coach`·sync 직접호출). 세션/턴 핸들러가 `_apply_hypotheses` 반환 세트를 넘긴다
    (개입 채널 `_intervention_from_hypotheses_or`와 *같은* post-apply 세트·단일 진실원천).

    **PED-04 D2** `polya_state_override`: 세션 경로가 넘기는 *서버 파생* Polya 상태. 주면 Polya
    결정·LTHC가 클라 제출 `body.polya_state` 대신 이 값을 쓴다. 미주입(기본 None)이면 stateless
    `/v1/coach`·직접 호출은 **완전 비트동일**. `recent_categories`(D1 reader ①)도 같은 규약.

    `grade`·`standard_code`(PED-05 개인화 슬롯)는 `decide()`로 그대로 thread된다 — 둘 다 기본
    None이라 미주입 호출자(stateless `/v1/coach`·sync 직접호출)는 완전 회귀 0. 실제 프롬프트
    반영은 `decide()` 내부에서 pack 주입 ∧ `pedagogy_pack_prompt_enabled` 플래그 ON일 때만
    일어난다(기존 옵트인 게이트 그대로 재사용 — 별도 플래그 신설 0).

    **COMP-01** `step_chain_verifier`: 세 핸들러가 `SubjectCapabilityDeps`(app.state 등록분)에서
    꺼내 넘기는 단계 연쇄 검증 능력 — **프로덕션 3경로는 전부 명시 주입**이고, 이것이 정본이다.
    기본 None은 이 함수를 *직접* 부르는 단위테스트(2026-09-07 실측 24곳)용 폴백 좌석이며,
    None이면 L4 오케스트레이터가 합성 루트 기본 구현으로 폴백한다(`l4/solution_coaching.py`
    해당 분기 주석).
    주입값이 실제로 쓰이는지는 `tests/backend/api/test_coach.py`의
    `TestStepChainVerifierInjection`이 가짜 verifier를 app.state에 올려 동결한다.

    **S4-19(2026-08-10)**: 반환이 7-튜플로 확장됐다 — `_StepVerificationCarry`(게이트 *이전*
    단계 검증 운반값·적재 전용)를 끝이 아닌 위치에 삽입해 **마지막 원소=solution_coaching
    불변식은 보존**한다(S3-32 브랜치가 그 언패킹 전제를 명문화). 노출(payload)은 불변 —
    carry는 세션 핸들러의 `_log_verify_event`만 소비한다.
    """
    # slice 25: mastery_level 명시값 우선·없으면 BKT 숙달(0~1)을 라벨로 환산(L2→L4 브릿지).
    # slice 69: level을 _coach.decide 이전에 계산해 hint level 보수화에도 전달(적응형 코칭).
    # slice 70: 세션/턴은 서버 L2 숙달도(server_mastery)로 클라 bkt를 대체(서버 진실원천)·명시
    # mastery_level은 여전히 최우선·stateless는 server_mastery=None(클라값). 숙달도는 비노출.
    # slice 77: 능력 라벨에 신뢰 θ도 통합 — BKT+θ(logistic) 평균→라벨. 힌트·전이·LTHC가 같은
    # 라벨을 쓰므로 θ가 적응형 스캐폴딩 전반에 일관 반영(θ None=stateless·희소면 BKT만·현행 동일).
    effective_bkt = server_mastery if server_mastery is not None else body.bkt_mastery
    level = body.mastery_level
    if level is None:
        level = _ability_level(effective_bkt, server_theta)
    # PED-04 D2: 세션 경로는 서버 파생 상태가 진실원천(클라 제출은 참고값). stateless는 override
    # None이라 클라 제출 그대로 — 두 경로의 계약 차이가 이 한 줄에 모인다.
    state = polya_state_override if polya_state_override is not None else body.polya_state
    decision = _coach.decide(
        body.student_input,
        state,
        mastery_level=level,
        misconception_hypotheses=misconception_hypotheses,
        pack=pack,
        recent_categories=recent_categories,
        grade=grade,
        standard_code=standard_code,
    )
    # slice 106: 주입된 결합 matches 우선·미주입(sync 직접호출·게이트 off 경로)이면 substring
    # diagnose 폴백(현행 비트동일). combine_diagnoses가 substr 우선이라 resolved[0]은 substr가
    # 있으면 substr → select_intervention이 substring 진단(검증된 표면 신호) 기준으로 구동.
    resolved = matches if matches is not None else diagnose(body.student_input)
    intervention = select_intervention(resolved[0]) if resolved else None
    lthc = adapt_lthc(state.current_stage, level) if level is not None else None
    # slice 23: 진단 코칭 포커스 → 대화 진입 소크라테스 카테고리 시드(L4 매핑·slice 22).
    entry_category = (
        focus_to_socratic_category(body.coaching_focus) if body.coaching_focus is not None else None
    )
    # slice 53: L3→L4 오케스트레이터(slice 52) — 학생 풀이의 *거짓 수치 관계*를 L3 결정론
    # 검증으로 검출해 검산(verify) 코칭을 처방(실시간 슬립은 배경 진단보다 우선·slice 51).
    # slice 55: 검증 대상은 *풀이 전용* student_solution 우선(L5 OCR 착지점)·없거나 비면
    # student_input 폴백(발화 인라인 풀이). Polya/오개념/LTHC는 위에서 student_input 기준 유지.
    # slice 73: θ는 세션/턴에서 서버 L2(AbilitySnapshot) 소싱값(server_theta)을 주입 — BKT↔θ
    # 교차검증 코칭(recommend_coaching)을 깨운다. stateless /v1/coach는 None(DB 없음).
    solution_text = body.student_solution or body.student_input
    # WH-1 1단계 결선: L5가 분해한 단계 시퀀스(solution_steps)가 있으면 verify_solution으로
    # 단계별 검증해 검산 코칭을 정밀화한다(텍스트 신호와 추가적 OR 결합·미제공 시 동작 불변).
    # WH-1 1단계 OCR 게이팅: ocr_confidence를 함께 넘겨, 저신뢰 OCR이면 step-incorrect 신호를
    # 코칭 결정에서 누그러뜨리고(거짓 지적 방지·정확성 #1) verification_ocr_gated로 노출한다.
    # 텍스트 레벨 신호·미제공/고신뢰 OCR은 게이팅 안 됨(하위호환). 이미 _compute_matches(게이트
    # ②)에 전달 중인 동일 값을 solution coaching에도 thread한다.
    # WH-1 1단계 잔여(hint 점층 결선): Polya 결정이 이미 계산한 hint_level(decide_hint_level·
    # 턴/좌절/숙달 기반)을 solution 코칭에 thread한다 — *단계 자가검산* 발화가 3·4단계에서 과정
    # 재구성 비계로 점층된다(정답/"틀렸다" 미포함·답 미루기). 재계산 0(L4 decide_hint_level 단일
    # 산정처)·verify_steps 아니거나 1·2단계면 발화 불변(하위호환).
    sol = recommend_coaching_for_solution(
        solution_text,
        effective_bkt,
        server_theta,
        problem_id=problem_id,
        expected_answer=expected_answer,
        solution_steps=body.solution_steps,
        solution_step_types=body.solution_step_types,
        ocr_confidence=body.ocr_confidence,
        hint_level=decision.hint_level,
        # COMP-01: 단계 연쇄 검증 능력을 **명시 주입**한다 — 미주입이면 L4가 합성 루트를
        # 지연 조회(pull)하므로, 이 한 줄이 "Core는 인터페이스만 안다"는 주장의 집행 지점이다.
        verifier=step_chain_verifier,
    )
    # slice 73: 노출은 *불일치 신호만* — 계산오류 verify(기존·arithmetic_error) + BKT↔θ 불일치
    # (consolidate·retrieval). 합의(foundation/advance)는 LTHC가 담당·한쪽 신호만(diagnose)은
    # θ 희소 노이즈라 비노출. θ 수치 자체는 노출 안 함(노출되는 건 trigger의 정성 발화뿐).
    solution_coaching = (
        sol if (sol.arithmetic_error or sol.trigger.focus in _THETA_SURFACED_FOCI) else None
    )
    # S4-19: 적재용 운반값은 노출 게이트 *이전* sol에서 뽑는다 — 전단계-correct·ocr_gated 제출도
    # 카운트가 적재돼야 한다(게이트 이후 값이면 불합격 편향 회계). 마지막 원소는 여전히
    # solution_coaching(불변식 보존 — carry는 끝이 아닌 위치에 삽입).
    step_carry = _StepVerificationCarry(
        verification=sol.solution_verification,
        ocr_gated=sol.verification_ocr_gated,
    )
    return decision, resolved, intervention, lthc, entry_category, step_carry, solution_coaching


class _MatchOutcome(NamedTuple):
    """`_compute_matches` 반환 — 게이트 통과 매칭 + §3.3 게이트 플래그 2종.

    WH-1 1단계 슬라이스: 직전 슬라이스에서 `_gate`가 `MatchGateResult.matches`만 반환하고
    `low_quality`/`no_confident_match`를 *드롭*했다. 이 컨테이너로 플래그를 핸들러까지 thread해
    `CoachResponse`(`match_low_quality`/`no_confident_match`)로 노출한다 — 매칭 *알고리즘*과
    리스트 내용은 불변, 반환 *형태*만 확장(드롭 제거)이다.
    """

    matches: list[MisconceptionMatch]
    low_quality: bool
    no_confident_match: bool
    # MISC-28 게이트 ③ — top-1의 정정 귀속 불명. `low_quality`와 같은 처분(매칭 유지 + 보류)이라
    # 기본값을 두지 않고 나란히 thread한다. 기본값을 주면 새 생성 지점이 조용히 False로 서서
    # "플래그가 안 붙는 경로"가 무증상으로 생긴다.
    attribution_unclear: bool

    @property
    def verdict_withheld(self) -> bool:
        """확신 진단을 **영속 계층에서 보류**해야 하는가 — 게이트 ②·③의 합집합.

        두 게이트는 출처가 다르지만(② 입력 OCR 품질 · ③ 정정 어구의 귀속) 처분이 같다:
        응답에는 후보를 그대로 싣되 학습자 모델에는 확정 진단으로 넣지 않는다. 응답 플래그는
        DB 쓰기를 되돌리지 못하기 때문이다(MISC-17의 근거를 MISC-28이 그대로 물려받는다).

        **+1과 −1을 함께 보류하는 것이 핵심이다.** 보류된 매칭을 빈 리스트로 넘기면 하류의
        `_log_refutation_evidence`가 그것을 "clean 풀이(no-match)"로 읽어 활성 가설을 −1로
        *반박*한다 — 즉 `모른다`가 `아니다`로 뒤집힌다(CLAUDE.md "모른다 ≠ 아니다"). 귀속
        불명은 오개념이 없다는 증거가 아니므로 어느 방향으로도 증거를 만들지 않는다.
        """
        return self.low_quality or self.attribution_unclear


class _JudgeSeamDeps(NamedTuple):
    """judge seam에 주입할 *앱 공유* L3 인프라(관측·provider·캐시) 묶음.

    프로덕션에서 `_judge_for_gate`가 이 셋을 `L3JudgeSeam`에 넘겨, judge LLM 호출의
    usage/cost가 앱 전역 `LangfuseSink`로 흐르고(관측 누락 해소) provider·캐시도 앱 전역과
    공유되게 한다(매 호출 새 `OllamaProvider`·`InMemoryCache` 생성 회피). 셋 다 `None`이면
    `L3JudgeSeam`이 자기 기본값(throwaway trace/새 provider/새 cache)으로 폴백한다 — app.state가
    없는 경로(단위테스트 등) 하위호환.
    """

    provider: LLMProvider | None
    cache: CacheBackend | None
    trace: TraceSink | None


def _get_judge_seam_deps(request: Request) -> _JudgeSeamDeps:
    """app.state의 공유 provider/cache/trace를 judge seam 주입용으로 묶는 얇은 의존성.

    `create_app`이 `app.state`에 1회 올린 공유 인스턴스(`CompositeProvider`·`RedisCache`·
    `LangfuseSink`)를 요청마다 조회한다(DB 세션과 달리 앱 수명 공유라 `app.py:296-298` 패턴과
    동형). 키가 없으면(app.state 미구성) `None` — `L3JudgeSeam` 기본값 폴백이라 안전. 이
    조회는 *부작용 0*이며, judge 게이트 off 경로에서도 주입값이 소비되지 않으므로 현행 동작 불변.
    """

    return _JudgeSeamDeps(
        provider=getattr(request.app.state, _PROVIDER_KEY, None),
        cache=getattr(request.app.state, _CACHE_KEY, None),
        trace=getattr(request.app.state, _TRACE_KEY, None),
    )


JudgeSeamDeps = Annotated[_JudgeSeamDeps, Depends(_get_judge_seam_deps)]


class _SubjectCapabilityDeps(NamedTuple):
    """이 라우터가 쓰는 **과목 능력 3종** — app.state 등록분(EOS-89·COMP-01).

    `_JudgeSeamDeps`와 같은 형태다(`request.app.state` 경유라 팩토리 클로저에 의존하지 않아
    TestClient에서도 안전). 다만 **폴백이 없다**: judge seam은 없으면 자기 기본값으로 도는
    부가 기능이지만, 답 판정 능력이 없는 채로 도는 것은 "검증 없이 학생에게 응답"이므로
    `getattr`가 `AttributeError`로 터지게 둔다(등록 누락을 조용히 넘기지 않는다).
    """

    final_answer: FinalAnswerVerifier
    answer_form: AnswerFormVerifier
    step_chain: StepChainVerifier
    """풀이 단계 연쇄 검증(COMP-01) — `_build_response_payload`가 L4 오케스트레이터에 명시 주입.

    앞의 둘(완료 상태머신용)과 소비처가 다르지만 좌석을 나누지 않는 이유: 셋 다 *같은 등록
    (push) 규약*으로 app.state에서 오고, 좌석을 쪼개면 핸들러 시그니처가 능력 수만큼 늘어난다."""


def _get_subject_capabilities(request: Request) -> _SubjectCapabilityDeps:
    """app.state에 등록된 과목 능력을 묶는 의존성(EOS-89 완료 상태머신 2종 + COMP-01 연쇄 검증).

    `create_app`이 부팅 시 `composition.default_*()`로 1회 올린 인스턴스를 요청마다 조회한다.
    이 라우터가 `composition`을 import하지 않는 것이 §3.8 "등록 형태"의 실체다 — Core는
    인터페이스 타입(`FinalAnswerVerifier`·`AnswerFormVerifier`·`StepChainVerifier`)만 안다.
    """

    return _SubjectCapabilityDeps(
        final_answer=get_final_answer_verifier(request),
        answer_form=get_answer_form_verifier(request),
        step_chain=get_step_chain_verifier(request),
    )


SubjectCapabilityDeps = Annotated[_SubjectCapabilityDeps, Depends(_get_subject_capabilities)]


def _judge_for_gate(
    *,
    provider: LLMProvider | None = None,
    cache: CacheBackend | None = None,
    trace: TraceSink | None = None,
) -> JudgeProtocol:
    """coach 오개념 게이트용 judge 좌석 — 기본 L3 백킹(라우터 경유·로컬 FAST·never-break).

    슬108 플래그(`misconception_judge_enabled`)가 on일 때만 `_gate`가 호출한다. 기본은 L3 백킹
    seam(`L3JudgeSeam`→`l3.pipeline`·로컬 FAST·Langfuse·캐시)을 문 `LLMJudge`다 — "LLM 라우터
    경유·로컬 우선·추적" 절대원칙을 자동 충족(직접 호출 0).

    provider/cache/trace는 L5(엔드포인트→`_compute_matches`)가 app.state 공유 인스턴스
    (`CompositeProvider`·`RedisCache`·`LangfuseSink`)를 주입한다 — 그래야 judge의 usage/cost가
    실제 Langfuse 관측으로 흐르고 캐시도 공유된다(계층 경계: L5가 L3 인프라를 L4 seam에 주입,
    L4 코어는 비용을 모른 채 유지). 미주입(모두 None)이면 `L3JudgeSeam` 기본값 폴백(하위호환).
    테스트는 이 팩토리를 monkeypatch해 `FakeJudge`(결정론·라이브 0)를 주입한다(좌석 주입점·
    hermetic) — 대체물은 kwargs를 받아 무시한다(`lambda **_: judge`). 플래그 off면 호출되지 않아
    provider/cache 구성도 0(현행 비트동일).
    """
    return LLMJudge(L3JudgeSeam(provider=provider, cache=cache, trace=trace))


async def _compute_matches(
    student_input: str,
    *,
    ocr_confidence: float | None = None,
    judge_deps: _JudgeSeamDeps | None = None,
) -> _MatchOutcome:
    """오개념 후보 계산 + §3.3 품질 게이트 — `misconception_semantic_mode` 3값 분기(off/shadow/on).

    WH-1 1단계 슬라이스 1(`match_misconception` 도구화): 모드별 후보 산출 *직후* 결과에
    `apply_match_quality_gate`를 *후처리*로 적용한다(`_gate` 헬퍼). 게이트는 매칭 *알고리즘*
    (`diagnose`/의미 매처/`combine_diagnoses`)을 전혀 바꾸지 않고, top-1 신뢰도<0.65면 후보를
    *비운다*(억지 매칭 금지·CLAUDE.md "확실하지 않으면 모른다"). 따라서 세 모드(off/shadow/on)
    *모두* 동일한 게이트를 거쳐 약한 top-1 매칭이 하류(가설·intervention)로 새지 않는다.

    **게이트 플래그 thread(이 슬라이스)**: 직전엔 `_gate`가 `MatchGateResult.matches`만 반환해
    `low_quality`/`no_confident_match`를 드롭했다. 이제 게이트를 *한 번만* 적용해 `MatchGateResult`
    전체를 받고 matches+플래그를 `_MatchOutcome`으로 함께 반환한다(드롭 제거). 매칭 리스트·재정렬은
    불변 — 반환 *형태*만 확장된다. 세 모드 모두 *같은* `_gate`를 통과하므로 플래그 의미가 일관된다.

    `ocr_confidence`는 OCR 산출물일 때 인식 신뢰도(0~1)다. 제공+<0.8이면 게이트 ②가 `low_quality`를
    세운다(매칭은 *유지*·플래그만). **None(미제공)이면 게이트 ②는 dormant** — `low_quality=False`로
    기존 동작 완전 불변. `low_quality`는 *입력 OCR 품질* 신호라 매칭 유무와 *독립*이다(매칭이 있어도
    low_quality 가능). `no_confident_match`는 top-1<0.65로 후보가 비워졌는지(매칭 결과는 게이트 ①의
    기존 동작 그대로·노출만 추가)다.

    slice 106: 핸들러가 호출해 `_build_response_payload(matches=...)`로 *matches만* 주입한다(직접
    sync 호출 경로는 미주입→`diagnose` 폴백이라 잠긴 `_build_response_payload(body)` 계약 불변).
    플래그는 핸들러가 `_MatchOutcome`에서 직접 꺼내 응답에 싣는다(payload 6-튜플 계약과 분리).

    **§3.3 범위(정직)**: 이 슬라이스는 *신호 노출까지*다 — low OCR→`match_low_quality=True` 노출.
    *재확인 발화 생성*·*intervention 보류*는 L5/LLM·후속(백엔드는 신호 제공·답 미루기 원칙 유지).
    intervention/matches 자체는 여기서 *변경하지 않는다*(억지매칭 차단[no_confident_match]은 기존
    게이트 동작 그대로).

    **`off`(기본)**: `diagnose(student_input)`만 — 의미 매처를 *호출하지 않는다*(임베딩 로드 0·
    현행 비트동일). substring 결과를 그대로 반환.

    **`shadow`(slice 111)**: 의미 매처를 라이브로 *돌리되* 노출은 substring 그대로(off와 비트동일
    반환)이고, `observe_misconception_shadow`로 substring↔semantic *불일치만 로깅*한다(비노출·
    실 분포 플립 근거 수집·학생 원문 미포함). 의미 매처 호출·폴백은 `on`과 동일(아래).

    **`on`**: 의미 매처를 `asyncio.to_thread`로 *워커 스레드*에서 호출한다 — 블로킹 임베딩
    (bge-m3 등)이 이벤트 루프를 막지 않게(CLAUDE.md p50<2s·동시 요청 보호). 결과를
    `combine_diagnoses`로 substring 위·semantic-only 아래로 결합해 *노출*한다(substr 우선·재정렬
    없음). substr/semantic 둘 다 `_FANOUT`(카탈로그 전수)으로 뽑아 *결합 끝에서만*
    `_DEFAULT_TOP_K`로 자른다(한쪽이 다른 쪽을 미리 잘라내지 않게).

    **graceful 폴백(CLAUDE.md 가용성 우선 #1≫#6)**: 의미 매칭이 *어떤 이유로든* 실패하면
    (모델 미설치·DB 미도달·임베딩 오류) 예외를 삼키고 substring 결과로 폴백한다(500이 아니라
    200·진단 1위는 substr라 학생 경험 유지). 실패는 *조용히 넘기지 않고* warning 로그로 남긴다
    (CLAUDE.md "환각/장애 조용히 넘어가지 말고 로그").
    """

    def _make_judge() -> JudgeProtocol:
        # judge 좌석 생성 — 엔드포인트가 넘긴 app.state 공유 provider/cache/trace를 주입한다
        # (미주입이면 `L3JudgeSeam` 기본값 폴백·하위호환). `_judge_for_gate`를 *모듈 전역*으로
        # 참조하므로 테스트의 monkeypatch(`coach._judge_for_gate`)가 그대로 적용된다(좌석 유지).
        if judge_deps is None:
            return _judge_for_gate()
        return _judge_for_gate(
            provider=judge_deps.provider,
            cache=judge_deps.cache,
            trace=judge_deps.trace,
        )

    async def _gate(candidates: list[MisconceptionMatch]) -> _MatchOutcome:
        # §3.3 품질 게이트 후처리 — 세 모드 공통 출구. 게이트를 *한 번만* 적용해 결과 전체를 받고
        # matches+플래그를 함께 반환한다(직전엔 .matches만 반환해 플래그를 드롭했음). 게이트 ①은
        # top-1<floor면 후보를 비우고(억지 매칭 금지) no_confident_match=True를, 게이트 ②는 OCR
        # confidence<0.8(None이면 dormant)면 low_quality=True를 세운다(매칭은 유지). 게이트는
        # *재정렬·변형 없이* 통과분만 그대로 통과시킨다(`combine_diagnoses` 순서 보존).
        # 슬108 결선: judge 게이트 on이면 품질 게이트 *이전*에 방향 판별 필터를 적용한다 —
        # NOT_EXPRESSES(올바름/다른 말)만 제거하고 예·불확실은 유지(recall 보존)해, 품질 게이트의
        # no_confident_match가 *judge 통과 후* top-1을 반영하게 한다. 세 모드(off/shadow/on) 공통
        # 출구라 게이트가 한 곳에 일관 적용된다. off면 좌석 호출 0·LLM 0·현행 비트동일.
        if candidates and get_settings().misconception_judge_enabled:
            candidates = await judge_filter(candidates, student_input, judge=_make_judge())
        # 반박 조건(MISC-23)을 **세 모드 공통 출구**에서 한 번 더 적용한다. substring 경로는
        # `diagnose`가 이미 걸렀지만, `on` 모드의 의미 후보는 그 경로를 지나지 않으므로
        # `combine_diagnoses`가 그것을 "semantic-only"로 보고 되살린다(PR #1039 Codex P2).
        # off 모드에선 무해한 no-op다(이미 걸러진 목록을 다시 훑을 뿐).
        candidates = reject_refuted(candidates, student_input)
        result = apply_match_quality_gate(candidates, ocr_confidence=ocr_confidence)
        return _MatchOutcome(
            matches=result.matches,
            low_quality=result.low_quality,
            no_confident_match=result.no_confident_match,
            attribution_unclear=result.attribution_unclear,
        )

    substr = diagnose(student_input, top_k=_FANOUT)
    mode = get_settings().misconception_semantic_mode
    if mode == "off":
        # off — substring만(의미 매처 미호출). 노출 상한 top-3로 자른다(결합 없음·현행 비트동일).
        return await _gate(substr[:_DEFAULT_TOP_K])
    # shadow·on — 의미 매처를 비블로킹(워커 스레드)으로 돌린다. 실패는 substring graceful 폴백.
    try:
        sem = await asyncio.to_thread(
            get_semantic_matcher().match,
            student_input,
            top_k=_FANOUT,
            threshold=get_settings().misconception_semantic_threshold,
        )
    except Exception:
        # 의미 매칭 실패 — substring 폴백(가용성 우선·200 유지). 조용히 넘기지 않고 로그.
        logger.warning("의미 매칭 실패 — substring 폴백", exc_info=True)
        return await _gate(substr[:_DEFAULT_TOP_K])
    if mode == "shadow":
        # shadow — 노출은 substring 그대로(off 비트동일)·substring↔semantic 불일치만 로깅한다
        # (비노출·실 분포 플립 근거 수집·slice 111). 학생 원문은 로그에 안 담는다(프라이버시).
        # shadow 로깅은 *게이트 전* 원본 substr/sem으로 수행(게이트가 비교 분포를 왜곡하지 않게).
        observe_misconception_shadow(substr, sem)
        # G1: judge-shadow 토글이 켜져 있고 의미 후보가 있으면, 그 후보에 judge를 돌려 *걸러질
        # 결과*(would-be removed/kept)를 무노출로 로깅한다(04b Phase 1·합성↔실 갭 검증). judge는
        # LLM(수 초)이라 *비차단*(_spawn=create_task)으로 띄우고 즉시 반환한다 — 응답 경로는 judge를
        # await하지 않는다(노출 무지연). `_make_judge()`(공유 provider/cache/trace 주입 좌석)를
        # spawn 직전 만들어 인자로 넘긴다(monkeypatch 타이밍 호환). 레코드엔 학생 원문·judge
        # reason 미저장(미성년 PII).
        if get_settings().misconception_judge_shadow and sem:
            _spawn(
                observe_misconception_judge_shadow(
                    sem,
                    student_input,
                    judge=_make_judge(),
                    feed_threshold=get_settings().misconception_semantic_threshold,
                    judge_routing=get_settings().misconception_judge_routing,
                )
            )
        return await _gate(substr[:_DEFAULT_TOP_K])
    # on — substring 아래에 semantic-only 후보를 결합해 *노출*(substring 우선·재정렬 없음).
    return await _gate(combine_diagnoses(substr, sem, top_k=_DEFAULT_TOP_K))


async def _expected_answer_for(session: AsyncSession, problem_id: uuid.UUID | None) -> str | None:
    """문항 기대정답을 서버 DB에서 조회 — step shadow 진단 맥락 전용(slice 64·비노출).

    shadow 게이트(`l4_step_shadow_enabled`)가 off(프로덕션 기본)거나 `problem_id`가 None이면
    조회를 *건너뛴다*(None) — 소비처(`observe_step_breaks`)와 같은 게이트라, 안 쓸 정답을
    불필요하게 DB에서 끌어와 메모리에 적재하지 않는다(비용·데이터 최소화). 문항 부재면 None
    (graceful — 코퍼스 미적재·신규 문항도 안전). 반환값은 *절대 HTTP 응답에 싣지 않는다*
    (정답 누출 차단) — `_build_response_payload`의 `expected_answer` 인자로만 흘러
    `observe_step_breaks` 로그 sink에 도달한다.
    """
    if problem_id is None or not get_settings().l4_step_shadow_enabled:
        return None
    problem = await session.get(ProblemORM, problem_id)
    return problem.answer if problem is not None else None


# ── S3-32: 완료를 풀이 제출에 통합 (정답/오답 도달 감지 → Polya 돌아보기 1턴 → 완료 적재) ──


def _last_solution_step(body: CoachRequest) -> str | None:
    """풀이 단계 시퀀스의 *마지막 단계*(=학생 최종답 후보) — 정답 도달 감지 입력.

    `body.solution_steps`(L5가 분해한 단계 리스트)의 마지막 비어있지 않은 원소를 돌려준다.
    리스트가 없거나·비었거나·마지막 원소가 공백뿐이면 None(감지 대상 아님). *풀이 마지막 단계*가
    완료 경로의 트리거다 — 대화 발화(student_input)나 풀이 산문(student_solution 문자열)이 아니라
    구조화된 단계 시퀀스의 끝을 본다(클라 계약: 완료를 원하면 solution_steps를 보낸다).
    """
    steps = body.solution_steps
    if not steps:
        return None
    last = steps[-1].strip()
    return last or None


async def _final_answer_state(
    session: AsyncSession,
    problem_id: uuid.UUID | None,
    body: CoachRequest,
    *,
    capabilities: _SubjectCapabilityDeps,
) -> tuple[VerificationOutcome | None, FormVerdict]:
    """이 턴 풀이의 *마지막 단계*가 문항 기대정답과 어떤 관계인지 — L3 서버 권위 3상태(비노출).

    완료 상태머신의 *정답/오답 도달 감지* 입력. 게이트(`l4_solution_completion_enabled`) off·
    problem_id 없음·마지막 단계 없음이면 조회조차 하지 않고 None(호출자는 미검증으로 취급). 있으면
    문항을 *무게이트*로 로드해(`_expected_answer_for`의 shadow 게이트와 무관 — 완료는 프로덕션
    기본 기능) 마지막 단계를 `verify_final_answer`로 3상태 판정한다. 기대정답(`Problem.answer`)은
    이 함수 밖으로 결코 흘러나가지 않는다(verify_final_answer가 상태·사유만 반환·사유엔 학생
    원문만 반향).

    반환은 `(값 판정, 형태 판정)` 두 축이다(EOS-28). 조회조차 하지 않는 경로에서는
    `(None, not_required)` — 판정하지 않은 것을 '요구 없음'으로 정직하게 적는다.
    """
    if not get_settings().l4_solution_completion_enabled or problem_id is None:
        return None, FormVerdict.not_required
    last_step = _last_solution_step(body)
    if last_step is None:
        return None, FormVerdict.not_required
    problem = await session.get(ProblemORM, problem_id)  # 무게이트 로드(완료는 정식 기능).
    if problem is None:
        # 문항 부재(코퍼스 미적재·신규) → 서버 채점 근거 없음(graceful).
        return None, FormVerdict.not_required
    # EOS-89: 구현을 이름으로 알지 않는 것에 더해, **끌어오지도 않는다** — 능력은 Application이
    # 부팅 시 app.state에 등록한 것을 엔드포인트가 Depends로 받아 여기까지 내려준다.
    result = capabilities.final_answer.verify_final_answer(last_step, problem)
    # EOS-28: 형태 지시 준수는 **값 판정과 나란히·독립으로** 계산한다. 여기서 두 판정이 서로를
    # 참조하지 않는 것이 교수학 계약의 1차 방어다 — 참조하는 순간 형태가 정오에 스며든다.
    form = capabilities.answer_form.verify_answer_form(
        last_step, getattr(problem, "answer_constraint", None)
    )
    return result.state, form


async def _complete_problem(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    problem_id: uuid.UUID | None,
    final_answer: str | None,
    started_at: datetime | None,
) -> uuid.UUID | None:
    """완료 확정 — ProblemAttempt(is_correct=True) 적재 + 숙달 전파(L2 헬퍼 재사용·중복 로직 0).

    돌아보기(메타인지) 1턴이 끝나 완료가 확정된 순간에만 호출한다. `submit_attempt`(me.py)와 *동일*
    적재·전파 헬퍼를 재사용한다(중복 구현 금지) — 단, 이 경로는 `submit_attempt`의 클라 자가보고
    `is_correct`와 *별개*다(그 필드는 v1 그대로 유지). 여기서 적재하는 `is_correct=True`는 turn A
    에서 서버가 `verify_final_answer`로 correct 판정했으므로 서버 권위값(클라 보고 아님·CLAUDE.md
    "수학 로직 코어 권위"):
      - `ProblemAttempt`를 명시 UUID로 발급해 add하고 **먼저 commit**(주된 기록 durable·submit
        패턴). `used_socratic=True`(코치 대화로 도달).
      - `record_problem_attempt_mastery`(개념 축)·`record_problem_attempt_skill_mastery`(스킬 축)로
        모델 B(역할 비대칭) 숙달 전파. 개념/스킬 매핑이 없으면 각자 빈 리스트(커밋 0·graceful).

    `problem_id`가 None이면(완료는 problem_id 있을 때만 진입·방어) 적재 없이 None. `final_answer`
    (완료 턴에 재제출된 마지막 단계가 있으면 그 값·없으면 None)를 `student_answer`로 기록한다 — 정답
    도달은 이전 턴에서 이미 서버가 확인했으므로 여기선 기록용일 뿐. 반환=적재된 attempt_id(호출자가
    응답·dialogue 링크에 사용).

    적재된 attempt(is_correct 비-NULL·problem_id 보유)는 `GET /me/next-problem` 미시도 필터(NOT IN)
    에서 제외돼 다음 문항 진행이 작동한다(submit_attempt와 동일 루프 닫힘).

    PED-37 `started_at`: 호출자가 이 풀이의 *발생* 시작 시각을 넘긴다(append_turn은 대화 세션의
    `dialogue.started_at` — 학생이 이 문항 풀이를 시작한 시점이라 발생 시각끼리의 이관이다).
    넘어온 값이 None이면 **NULL로 둔다** — 서버 now로 메우면 그건 발생이 아니라 수신 시각의 복제라
    32_learning_history §EOS-48-2가 금지하는 날조다(NULL=미측정이 정직한 상태). 이 컬럼이 비면
    `harness/wh1_evaluation`의 since/until 집계와 `privacy/retention`의 파기 창이 조용히 0행이
    되므로, 값이 *있을 때* 채우는 것이 이 인자의 존재 이유다.
    """
    if problem_id is None:
        return None  # 방어 — 완료는 problem_id가 있을 때만 진입(도달 안 함).
    # 한 번만 읽어 ended_at·ingested_at에 같은 값을 쓴다 — 두 번 호출하면 마이크로초가 갈려
    # "종료가 수신보다 앞선다"는 사실이 아닌 시차가 데이터에 남는다.
    received_at = datetime.now(timezone.utc)
    # SEC-31: 학생 답안 봉투 암호화 — me.py::submit_attempt와 동일 헬퍼(encrypt_dialogue_content)·
    # 동일 키(student_work)를 재사용해 두 ProblemAttempt 적재 경로가 같은 보호를 받는다(부분
    # 배선 방지). final_answer는 서버가 완료 확정 시 기록용으로 담는 값(모듈 docstring 참조).
    student_work_cipher = require_student_work_cipher(get_settings())
    student_answer_plain, student_answer_encrypted, student_answer_nonce = encrypt_dialogue_content(
        student_work_cipher, final_answer
    )
    attempt = ProblemAttemptORM(
        attempt_id=uuid.uuid4(),  # 명시 발급(server_default 의존 X·응답·dialogue 링크에 즉시 사용).
        user_id=user_id,
        problem_id=problem_id,
        is_correct=True,  # 서버 권위 판정(turn A correct) — 클라 보고 아님.
        student_answer=student_answer_plain,
        student_answer_encrypted=student_answer_encrypted,
        student_answer_nonce=student_answer_nonce,
        used_socratic=True,  # 코치 대화(돌아보기)로 도달.
        # PED-37: 발생 시작 시각은 *넘어온 값 그대로*(대화 시작 시각) — 없으면 NULL(날조 금지).
        started_at=started_at,
        # `ended_at`은 기존 동작(서버 now) 그대로 둔다 — 이 경로는 완료 턴이 곧 종료 시점이라
        # 사실과 어긋나지 않고, 값을 비우면 이 컬럼으로 attempt를 정렬하는 기존 계약이 깨진다.
        ended_at=received_at,
        # EOS-48: 서버 *수신* 시각 좌석. 이 경로는 라이브 대화 턴이라 수신=지금이 사실이다
        # (오프라인 sync가 아니다). started_at(발생)과 짝을 이뤄 지연 도착 판별을 가능하게 한다.
        ingested_at=received_at,
    )
    session.add(attempt)
    await session.commit()  # attempt 우선 durable(submit_attempt 패턴).
    # 숙달 전파(개념·스킬 축) — 서버 판정 is_correct=True. 매핑 없으면 빈 리스트(graceful).
    await record_problem_attempt_mastery(session, user_id, problem_id, True)
    skill_records = await record_problem_attempt_skill_mastery(session, user_id, problem_id, True)
    # EOS-57: 해소된 스킬 배열을 `문제시도` 이벤트로 영속 — submit_attempt와 *같은 writer*
    # (중복 구현 0). `source`가 두 채점 경로를 가르므로 기록률 리포트가 경로별 분모로 본다.
    await record_attempt_skill_event(
        session,
        user_id=user_id,
        attempt_id=attempt.attempt_id,
        problem_id=problem_id,
        is_correct=True,  # 서버 권위 판정(turn A correct) — attempt 적재값과 동일.
        skill_ids=[r.skill_id for r in skill_records],
        source=AttemptSource.coach_completion,
    )
    return attempt.attempt_id


class _CompletionResult(NamedTuple):
    """`_resolve_completion` 반환 — 완료 상태머신 처리 결과(호출자가 발화·영속·응답에 반영).

    - `decision`: 발화가 override됐을 수 있는 결정(돌아보기/인정/재고면 prompt·socratic_category
      교체).
    - `problem_complete`/`awaiting_reflection`: 응답 계약 필드(클라 진행·UX 신호).
    - `review_turns_remaining_after`: 세션(dialogue.review_turns_remaining)에 저장할 값.
    - `attempt_id`: 완료 시 적재된 ProblemAttempt PK(dialogue.attempt_id 링크·응답). 아니면 None.
    - `handled`: 완료 상태머신이 이 턴 발화를 *가로챘는지*(True면 WH-1 primary LLM flip을 건너뛴다 —
      돌아보기/인정/재고 발화는 결정론 메타인지 템플릿이라 LLM으로 재작성하지 않는다).
    """

    decision: PedagogyDecision
    problem_complete: bool
    awaiting_reflection: bool
    review_turns_remaining_after: int
    attempt_id: uuid.UUID | None
    handled: bool
    answer_form: FormVerdict = FormVerdict.not_required
    """이 턴 제출답의 형태 지시 준수 판정(EOS-28) — 응답 노출 전용.

    기본값이 `not_required`인 이유: 완료 감지를 건너뛴 턴(돌아보기 중·이미 완료·게이트 off)은
    형태를 *판정하지 않은* 것이고, 그때 `satisfied`를 내면 판정한 척이 된다. `not_required`는
    '이 턴에 형태 판정 대상이 없었다'는 정직한 표기다."""


async def _resolve_completion(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    problem_id: uuid.UUID | None,
    prior_review_remaining: int | None,
    already_completed: bool,
    redirect_turn_index: int,
    body: CoachRequest,
    decision: PedagogyDecision,
    capabilities: _SubjectCapabilityDeps,
    attempt_started_at: datetime | None,
) -> _CompletionResult:
    """완료 상태머신 결선(L5 오케스트레이션) — 정답/오답 감지(L3)·완료 판정(L4)·attempt 적재(L2)를
    잇는다(중복 로직은 L2 헬퍼 재사용).

    흐름(순수 결정은 `l4/completion.decide_completion`·부작용만 여기서):
      1. 게이트 off → no-op(`handled=False`·기존 발화·회귀 완전 불변).
      2. *돌아보기 전(prior=0)이고 미완료*일 때만 이 턴 풀이 마지막 단계를 verify로 판정
         (`_final_answer_state`) — 돌아보기 중·완료된 세션은 감지 자체를 건너뛴다(불필요 조회 0·
         돌아보기 응답 턴은 재검증하지 않음). correct/incorrect만 상태머신에 True로 넘기고
         unverifiable은 둘 다 False(사변에 false redirect 금지).
      3. `decide_completion`으로 5전이 결정.
      4. `NONE` → no-op(기존 발화 유지). 그 외 → 결정론 발화로 override(prompt·socratic_category).
      5. `COMPLETE` → `_complete_problem`으로 attempt 적재·숙달 전파(attempt_id 확보).

    PED-37 `attempt_started_at`: 적재할 attempt의 *발생* 시작 시각. `_complete_problem`이 자체로
    구할 수 없어(이 함수도 dialogue를 모른다) 호출자가 넘긴다 — append_turn은 `dialogue.started_at`,
    create_session은 None(그 턴에는 dialogue가 아직 없고, 애초에 COMPLETE가 나지 않는다).

    반환의 `handled`는 완료 상태머신이 발화를 가로챘는지다 — True면 호출자가 WH-1 primary flip을
    건너뛴다(결정론 메타인지/재고 템플릿을 LLM으로 재작성 금지).
    """
    if not get_settings().l4_solution_completion_enabled:
        # 게이트 off — 완료 기능 완전 inert(정답 감지·돌아보기·적재 0·기존 동작 비트동일).
        return _CompletionResult(
            decision=decision,
            problem_complete=False,
            awaiting_reflection=False,
            review_turns_remaining_after=(prior_review_remaining or 0),
            attempt_id=None,
            handled=False,
        )

    prior = prior_review_remaining or 0
    # 정답/오답 도달 감지는 *돌아보기 전(prior=0)·미완료*일 때만 — 돌아보기 응답 턴·완료 세션은
    # skip한다.
    final_correct = False
    final_incorrect = False
    answer_form = FormVerdict.not_required
    if prior == 0 and not already_completed:
        state, answer_form = await _final_answer_state(
            session, problem_id, body, capabilities=capabilities
        )
        final_correct = state is VerificationOutcome.correct
        final_incorrect = state is VerificationOutcome.incorrect
        # EOS-28 교수학 계약: `answer_form`은 아래 어느 판정에도 **들어가지 않는다**.
        # final_correct/final_incorrect는 값 판정만으로 정해지고, decide_completion도 형태를
        # 인자로 받지 않는다 — 형태 위반이 완료를 막거나 오답을 만드는 경로가 코드에 없다.

    cd = decide_completion(
        prior_review_remaining=prior,
        already_completed=already_completed,
        final_answer_correct=final_correct,
        final_answer_incorrect=final_incorrect,
        redirect_turn_index=redirect_turn_index,
    )
    if cd.action is CompletionAction.NONE:
        # 완료 무관 — 기존 코칭 발화 그대로(돌아보기 상태 유지값=0·회귀 불변).
        return _CompletionResult(
            decision=decision,
            problem_complete=False,
            awaiting_reflection=False,
            review_turns_remaining_after=cd.review_turns_remaining_after,
            attempt_id=None,
            handled=False,
            answer_form=answer_form,
        )

    # 결정론 발화로 override — 돌아보기/인정/재고 발화(prompt)·메타인지 카테고리(socratic_category).
    new_decision = decision.model_copy(
        update={
            "prompt": cd.prompt if cd.prompt is not None else decision.prompt,
            "socratic_category": (
                cd.socratic_category
                if cd.socratic_category is not None
                else decision.socratic_category
            ),
        }
    )
    attempt_id: uuid.UUID | None = None
    if cd.action is CompletionAction.COMPLETE:
        # 완료 확정 — attempt 적재·숙달 전파(L2 헬퍼 재사용). 완료 턴에 재제출된 마지막 단계가
        # 있으면 그 값을 student_answer로 기록(없으면 None — 정답은 이전 턴에서 이미 서버 확인).
        attempt_id = await _complete_problem(
            session,
            user_id=user_id,
            problem_id=problem_id,
            final_answer=_last_solution_step(body),
            started_at=attempt_started_at,
        )
    return _CompletionResult(
        decision=new_decision,
        problem_complete=cd.problem_complete,
        awaiting_reflection=cd.awaiting_reflection,
        review_turns_remaining_after=cd.review_turns_remaining_after,
        attempt_id=attempt_id,
        handled=True,
        answer_form=answer_form,
    )


async def _server_mastery_for(
    session: AsyncSession, user_id: uuid.UUID, problem_id: uuid.UUID | None
) -> float | None:
    """학생의 *실제* 숙달도를 서버 L2 저장소에서 조회 — coach 세션/턴 전용(slice 70·비노출).

    게이트(`l4_server_mastery_enabled`)가 off거나 `problem_id`가 None이면 None(조회 skip).
    문항의 PRIMARY 개념(없으면 TESTED 폴백)을 해석해 그 개념의 현재 숙달도를 돌려준다. 문항-개념
    미매핑·측정 이력 없음이면 graceful None → 호출자는 클라이언트 bkt로 폴백. 반환값은 코칭
    *결정에만* 쓰이고 HTTP 응답엔 싣지 않는다(slice 69 숙달도 비노출 불변).
    """
    if problem_id is None or not get_settings().l4_server_mastery_enabled:
        return None
    concept_id = await get_primary_concept_id(session, problem_id)
    if concept_id is None:
        return None
    return await get_current_mastery(session, user_id, concept_id)


async def _pack_for(session: AsyncSession, problem_id: uuid.UUID | None) -> PedagogyPack | None:
    """문항 PRIMARY 개념 → k_type → 교수법 팩 해석 — coach 세션/턴 GA 배선(PED-01 후속).

    게이트(`pedagogy_pack_prompt_enabled`)가 off면 **조기 None**(팩 조회 자체 skip → 완전
    no-op·회귀 0). `problem_id` None(stateless)이면 None. 문항 PRIMARY 개념(없으면 TESTED
    폴백·`get_primary_concept_id`)의 `code`를 해석하고, 그 code로 학습목표 k_type을 찾아 팩을
    가져온다(`_server_mastery_for`와 동형 해석 seam·요청 AsyncSession 직접 실행). 어느 단계든
    미매핑·미존재면 graceful None → `decide`가 base_system 무변경(pack None이면 회귀 0).
    """
    if problem_id is None or not get_settings().pedagogy_pack_prompt_enabled:
        return None
    concept_id = await get_primary_concept_id(session, problem_id)
    if concept_id is None:
        return None
    code = await session.scalar(select(Concept.code).where(Concept.concept_id == concept_id))
    if code is None:
        return None
    k_type = await session.scalar(k_type_query(str(code)))
    if k_type is None:
        return None
    return get_pack(str(getattr(k_type, "value", k_type)))


async def _grade_for(session: AsyncSession, user_id: uuid.UUID) -> int | None:
    """학생 학년(`user_profile.grade`) 단건 조회 — 프롬프트 개인화(PED-05) 착지용.

    `get_state()`(l2 조립기)를 거치지 않고 `user_profile` 단건만 읽는다 — `get_state()`는
    `compute_concept_diagnoses`(전체 개념 진단 재계산)까지 함께 하므로, 매 코치 턴마다 grade 하나
    때문에 그 무거운 계산을 태우면 `_server_mastery_for`/`_server_theta_for`(단건 조회로 성능을
    지키는 기존 결정)와 같은 함정에 빠진다. graceful None(프로필 없음·미입력) — 호출자는 grade
    없이도 정상 동작(PolyaCoach.decide 기본값 None과 동형).
    """
    profile = await session.get(UserProfile, user_id)
    return profile.grade if profile is not None else None


async def _standard_code_for(session: AsyncSession, problem_id: uuid.UUID | None) -> str | None:
    """문항 PRIMARY 개념의 성취기준 고시코드 1개 — 프롬프트 개인화(PED-05) 착지용(비PII).

    `_pack_for`와 동일한 해석 seam(`get_primary_concept_id` — PRIMARY 없으면 TESTED 폴백)으로
    concept_id를 얻고, **원자 축**(`Concept.code == AtomNode.code` → `AtomNode.standard_codes`)에서
    성취기준 고시코드(예 '[12미적01-01]') 1개를 결정적으로(정렬) 고른다.

    **CUR-04 축 전환**: 구 축(`concept_standard_link → achievement_standard`)은 더 쓰지 않는다.
    S2-03 원자 재연결 이후 `get_primary_concept_id`가 돌려주는 concept_id는 원자 백본 행을
    가리키는데, 원자 행은 `concept.source_id`를 설정하지 않아(`l1/atom_graph/
    atom_backend_concept.py::upsert`) `concept_standard_link` 로더의 `{source_id: code}` 해석
    맵에 구조적으로 닿지 못한다(`concept.code`는 UNIQUE라 legacy code와 원자 code는 겹치지 않는
    별개 공간 — `docs/handoff/atom_backbone_next_session.md:19`가 이미 기록한 사실이자
    `api/gating.py::_fetch_achievement_codes`가 옮겨간 이유와 동일). 그래서 구 축은 이 concept_id에
    대해 늘 0행이었다.

    **CUR-12 통합 경유**: 원자 축 조인을 여기서 다시 쓰지 않고
    `l1/standards/alignment_query.get_alignments`(단일 진실 원천)를 축 1개(ATOM_NODE)로 호출한다
    — 쿼리 수는 그대로 1회다. 조인 회계(probed/matched)는 `log_join_stats`가 낸다.

    문항 없음·개념 미해석·원자 축 미매핑·성취기준 매핑 빈 배열 어느 단계든 graceful None(폴백).
    각 단계를 디버그 로그로 구분한다(CLAUDE.md "작동한 비율" 원칙 — 0%가 "성취기준 미매핑"인지
    "원자 축 조인 실패"인지 무계수로 묻히지 않게 한다·침묵 실패 금지).
    """
    if problem_id is None:
        return None
    concept_id = await get_primary_concept_id(session, problem_id)
    if concept_id is None:
        logger.debug(
            "standard_code_for: 개념 미해석(문항-개념 매핑 없음) problem_id=%s", problem_id
        )
        return None
    result = await get_alignments(
        session,
        concept_ids=[concept_id],
        axes={AlignmentAxis.ATOM_NODE},
    )
    log_join_stats(result.stats, logger=logger, context=f"coach.standard_code_for/{problem_id}")
    if result.stats.matched == 0:
        # 두 사태를 계속 구분해 로그로 남긴다(CUR-04가 세운 3단계 구분 유지 — 0%의 원인이
        # 묻히지 않게). 기준은 **joined**다: OUTER JOIN이라 개념이 있으면 probed는 늘 1이고,
        # 원자 행이 실제로 붙었는지는 joined만 안다(#933 리뷰 P2 — probed로 갈랐더니 조인
        # 미스가 "매핑 없음"으로 잘못 찍혔다).
        if result.stats.joined == 0:
            logger.debug(
                "standard_code_for: 원자 축 조인 미스(concept.code가 atom_node에 없음) "
                "problem_id=%s concept_id=%s",
                problem_id,
                concept_id,
            )
        else:
            logger.debug(
                "standard_code_for: 원자 노드는 매칭됐으나 성취기준 매핑 없음 "
                "problem_id=%s concept_id=%s",
                problem_id,
                concept_id,
            )
        return None
    # 결정론 — refs는 정렬·중복 제거되어 나온다(첫 코드 선택이 안정).
    return result.standard_refs(kind="official_code")[0]


def _theta_reading_reliable(reading: AbilityReading) -> bool:
    """개념 θ를 코칭 교차검증에 쓸 만큼 *신뢰*할 수 있나 — 응답수·SE 게이트(slice 76 노이즈 가드).

    응답이 충분(`l4_theta_min_responses` 이상)하고 SE가 측정 가능(None 아님)하며 상한
    (`l4_theta_max_se`) 이하일 때만 True. 응답 1~2개의 극단 θ(±4·SE inf→None)나 SE가 큰 개념
    θ는 False → 호출자가 전과목 θ로 폴백한다. 임계는 config(운영 튜닝·기본 응답 3·SE 1.0).
    """
    settings = get_settings()
    return (
        reading.response_count >= settings.l4_theta_min_responses
        and reading.standard_error is not None
        and reading.standard_error <= settings.l4_theta_max_se
    )


async def _server_theta_for(
    session: AsyncSession, user_id: uuid.UUID, problem_id: uuid.UUID | None
) -> float | None:
    """학생의 *실제* IRT 능력 θ를 서버 L2(AbilitySnapshot)에서 조회 — coach 세션/턴
    전용(slice 73·74·76·비노출).

    게이트(`l4_server_theta_enabled`)가 off면 None(조회 skip). slice 74: 문항 PRIMARY 개념의
    *개념별* θ를 우선 조회해(같은 개념 BKT와 동일 개념끼리 교차검증·정밀) `_server_mastery_for`와
    대칭을 이룬다. **slice 76 노이즈 가드**: 개념 θ는 *신뢰도*(응답수·SE)가 충분할 때만 쓴다
    (`_theta_reading_reliable`) — 응답 1~2개의 극단 θ는 무시하고 전과목 θ로 폴백(허위
    consolidate/retrieval 차단). 개념 θ가 없거나·불신뢰·problem_id/개념 미해석이면 *전과목* θ
    폴백(slice 73 동작·전과목은 게이팅 안 함). 둘 다 없으면 graceful None → `recommend_coaching`이
    diagnose 폴백(노출 안 함). 반환값(θ 수치)은 코칭 *결정에만* 쓰이고 HTTP 응답엔 싣지 않는다
    (slice 70 숙달도 비노출과 동일 — θ도 student-facing 비노출).
    """
    if not get_settings().l4_server_theta_enabled:
        return None
    if problem_id is not None:
        concept_id = await get_primary_concept_id(session, problem_id)
        if concept_id is not None:
            reading = await get_current_ability(session, user_id, concept_id)
            if reading is not None and _theta_reading_reliable(reading):
                return reading.theta  # 신뢰도 충분한 개념 θ(정밀 교차검증)
    return await get_current_theta(session, user_id)  # 전과목 폴백(slice 73·게이팅 안 함)


async def _prerequisite_coaching_for(
    session: AsyncSession,
    user_id: uuid.UUID,
    problem_id: uuid.UUID | None,
    *,
    mastery_threshold: float = 0.7,
    max_depth: int = 1,
) -> CoachingTrigger | None:
    """이 문제 개념의 *막힌 선수*가 있으면 "선수 복습 먼저" 코칭을 반환 — coach 세션/턴 전용.

    `GET /v1/me/weak-concepts/{id}/coaching`과 *동일 오케스트레이션*(L5가 L2 fetch + L4 decide를
    배선·L2/L4 좌석 무변경 재사용·역의존 0)을 상호작용 코칭 흐름에 옮긴 것이다. 학생이 어떤 문제를
    풀 때 그 문제 개념의 막힌 선수가 있으면 응답에 *별개 추가 신호*로 "선수 복습 먼저"를 실어준다
    (Polya 결정을 *대체하지 않음*·클라/L5가 우선 제시 여부 결정·코칭 턴을 가로채 풀이를 끊지 않음).

    흐름:
      ① `problem_id` None → None(문제 맥락 없음·stateless·매핑 불가).
      ② `get_primary_concept_id`로 문항 PRIMARY 개념(없으면 TESTED 폴백) 해석 → None이면 None
         (문항-개념 미매핑).
      ③ L2 `recommend_prerequisite_gaps(weak_only=True)`로 그 개념의 *막힌 선수*(weakness asc·
         `gaps[0]`=top blocker)를 조회.
      ④ L4 `recommend_prerequisite_coaching(gaps)` — 막힌 선수가 있으면 `prerequisite_review`
         코칭 trigger·없으면 None(순수 결정·L5는 fetch만).

    redaction: `CoachingTrigger`의 rationale/prompt에는 *안전 표시 필드*(name_ko)만 들어가고
    개념 본문·정답은 구조적으로 흐를 수 없다(`PrerequisiteGap`/`recommend_prerequisite_coaching`이
    이미 보장). 톤은 재사용 함수가 격려·비난 0(직전 슬 톤 가드)으로 추가 문구 생성 없음. 반환값은
    HTTP 응답의 `prerequisite_coaching`으로 노출되나 *추가 신호*일 뿐이다.
    """
    if problem_id is None:
        return None  # 문제 맥락 없음 → 선수 코칭 불가(stateless·매핑 없음).
    concept_id = await get_primary_concept_id(session, problem_id)
    if concept_id is None:
        return None  # 문항-개념 미매핑 → 선수 traversal 불가.
    gaps = await recommend_prerequisite_gaps(
        session,
        user_id,
        concept_id,
        mastery_threshold=mastery_threshold,
        weak_only=True,
        max_depth=max_depth,
    )
    return recommend_prerequisite_coaching(gaps)  # 막힌 선수 없으면 None.


async def _log_verify_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    problem_id: uuid.UUID | None,
    attempt_id: uuid.UUID | None,
    student_solution: str | None,
    mode: str | None = None,
    persona: str | None = None,
    verification: ChainVerificationCounts | None = None,
    verification_ocr_gated: bool | None = None,
) -> bool | None:
    """학생 풀이 검산(verify) 결과를 `attempt_event`(검산결과)로 1행 적재 + 통과여부 반환.

    WH-1 0단계 지표 ①(verify 통과율)을 NOT_INSTRUMENTED→MEASURED로 끌어올리는 *적재 좌석*.
    스테이트풀 coach(`create_session`·`append_turns`)에서만 호출하며, stateless `/v1/coach`
    (`coach_decide`)는 DB 무접근 계약이라 적재하지 않는다.

    적재 조건(false-pass 방지): `student_solution`(풀이 전용 필드)이 *비어 있으면 적재 안 함* —
    풀이를 제출한 턴만 검산 신호로 기록한다(빈/대화 턴이 '통과'로 오집계되는 걸 차단). 검증은
    coach 본문(`recommend_coaching_for_solution`)이 쓰는 것과 *동일한* 결정론 검증기를 다시
    호출한다(순수·결정론·저비용 — `_build_response_payload`를 건드리지 않고 신호만 재산출하는
    게 목적). `signal is None`=거짓 수치관계 *미적발*(passed=True), `signal is not None`=적발
    (passed=False). **binary 검산**이지 3-state(정답/오답/검증불가) verify가 아니다.

    트랜잭션: ORM 1행을 `session.add`만 하고 *commit은 하지 않는다* — 호출 핸들러가 이미 자기
    트랜잭션을 commit하므로 그 트랜잭션에 합류한다(별도 commit 금지). `event_at`은 핸들러와 동일
    시각으로 명시(server_default 의존 회피·복합 PK 구성요소).

    **반환(반박 증거 결선용)**: 풀이 제출 턴이 아니면 `None`(검산 신호 없음)·clean 검증이면 `True`·
    거짓 수치관계 적발이면 `False`. 핸들러가 이 값으로 `_log_refutation_evidence`(clean→약한 −1)를
    구동한다 — 적재(부수효과)는 불변이고 *통과여부 신호만* 추가 노출한다(기존 호출자는 반환 무시·
    하위호환).

    **S3-03 mode 태깅**: `mode`·`persona`(선택)를 event_data에 실어 이 검산결과가 어느 응용 모드/
    페르소나 세션에서 나왔는지 표식한다(수능 세션 식별·측정 계층 도달). 둘 다 None(기본)이면
    mode-agnostic으로 기존 event_data 모양과 *비트동일*은 아니지만(계약이 mode/persona=None 키를
    항상 채움) 의미상 완전 불변이다 — 측정 필터가 None을 mode 미지정으로 취급(회귀 0).

    **S4-19 3상태 병기(2026-08-10)**: `verification`(코치 본문이 이미 계산한 `verify_solution`
    결과·게이트 *이전* 값)이 있으면 비식별 카운트 6필드(n_correct·n_incorrect·n_unverifiable·
    unverified_ratio·first_incorrect_index·ocr_gated)를 additive로 병기 적재한다 — **재계산 0**
    (값 운반만·전이 0회 제출도 카운트 0으로 기록해 None과 구분). 없으면(단계 미제출/검증 미실행)
    6필드 전부 None — 구판 이벤트와 같은 NULL 회계로 읽힌다. 위 binary `passed` 재검산 축은
    **무변경**(두 검증기의 이중 회계 — CLAUDE.md 인프로세스 이중 회계). `verification.steps`
    (reason 텍스트)는 절대 싣지 않는다 — 미성년 PII 규약(`wh1_shadow.py` 관측 레코드 동형).
    `verification_ocr_gated`는 `SolutionCoaching.verification_ocr_gated`(verification 객체가
    아닌 형제 필드)를 그대로 받는다.

    **MATH-03 사유 분포 병기 + 분포 리포트(2026-08-11)**: `unverifiable_by_reason`(폐쇄 사유
    코드 → 건수·값 합=n_unverifiable)을 S4-19 동형 additive 필드로 병기 적재하고, 같은 분포를
    분모 동반 형식("전이 N건 중 보류 M건")의 INFO 로그로도 노출한다. 리포트 좌석 실측(태스크
    ④): verify 집계를 읽는 기존 리포트(`harness/wh1_evaluation`·`surrogate_baseline_report`)는
    전부 `harness/**`(타 세션 claim)라 이번 슬라이스에서 확장 불가 → 백엔드 응답 로그 대체
    (본 모듈 client_state_mismatch logger.info 선례). 이벤트 병기 덕에 harness 리포트의 사유별
    집계 확장은 후속에서 데이터 소급 가능하다. 코드·정수만 싣는다(자유문·steps 미적재 —
    비식별 규약 불변).
    """
    solution_text = student_solution or ""
    if not solution_text.strip():
        return None  # 풀이 제출 턴이 아님(빈/대화 턴) → 적재 안 함(false-pass 방지)·검산 신호 없음.

    signal = validate_response(arithmetic_validator(), solution_text)
    passed = signal is None  # None=거짓관계 미적발(통과)·아니면 적발(실패).

    # MATH-03: 보류 사유 분포(폐쇄 enum 코드 → 건수)를 문자열 키로 접는다 — 값 운반만(재계산 0)·
    # 비식별(코드·정수뿐). None=검증 미실행(구판 NULL 회계)·{}=검증 실행·보류 0.
    unverifiable_by_reason = (
        {code.value: count for code, count in verification.unverifiable_by_reason.items()}
        if verification is not None
        else None
    )
    # MATH-03 ④ 분포 리포트 — 분모 없는 0 금지: "전이 N건 중 보류 M건" 형식(보류 0건도 분모와
    # 함께 남긴다). parse_error 비중이 곧 MATH-01(표기 권위)·자연표기 확장(gap review §5-③)의
    # 발화 조건 데이터다. 좌석 근거는 위 docstring(harness 리포트 claim 충돌 → 응답 로그 대체).
    if verification is not None:
        logger.info(
            "verify_solution 확인 보류 분포 — 전이 %d건 중 보류 %d건: %s",
            verification.n_transitions,
            verification.n_unverifiable,
            unverifiable_by_reason,
        )

    # S4-19: verification이 있을 때만 6필드를 값으로 채운다(없으면 전부 None — 정직 NULL 회계).
    # n_transitions는 미적재 — 세 카운트 합==n_transitions 보장(ChainVerificationCounts 규약)으로
    # 재구성 가능하다. ocr_gated도 verification 없으면 None(False로 위장하지 않음).
    # MATH-03: unverifiable_by_reason(사유 코드 분포)도 같은 additive 규약으로 병기한다.
    event = AttemptEventORM(
        event_at=datetime.now(timezone.utc),
        attempt_id=attempt_id,
        user_id=user_id,
        problem_id=problem_id,
        event_type=EventType.검산결과,
        event_data=build_event_data(
            EventType.검산결과,
            passed=passed,
            error_kind=(signal.kind if signal else None),
            mode=mode,
            persona=persona,
            n_correct=verification.n_correct if verification is not None else None,
            n_incorrect=verification.n_incorrect if verification is not None else None,
            n_unverifiable=verification.n_unverifiable if verification is not None else None,
            unverifiable_by_reason=unverifiable_by_reason,
            unverified_ratio=verification.unverified_ratio if verification is not None else None,
            first_incorrect_index=(
                verification.first_incorrect_index if verification is not None else None
            ),
            ocr_gated=verification_ocr_gated if verification is not None else None,
        ),
    )
    session.add(event)  # commit은 핸들러가 — 같은 트랜잭션에 합류(별도 commit 금지).
    return passed  # clean→True·거짓관계 적발→False(핸들러의 반박 증거 결선이 소비).


async def _log_hint_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    problem_id: uuid.UUID | None,
    attempt_id: uuid.UUID | None,
    hint_level: int | None,
    mode: str | None = None,
    persona: str | None = None,
    client_state_mismatch: bool = False,
) -> None:
    """AI가 제공한 힌트 노출량(hint_level)을 `attempt_event`(event_type=힌트제공)로 1행 적재.

    WH-1 0단계 지표 ⑤(도움 감소 곡선)을 NOT_INSTRUMENTED→MEASURED로 끌어올리는 *적재 좌석*.
    직전 verify 슬라이스(`_log_verify_event`·검산결과) **동형**: 스테이트풀 coach
    (`create_session`·`append_turns`)에서만 호출하고, stateless `/v1/coach`(`coach_decide`)는
    DB 무접근 계약이라 적재하지 않는다.

    **재계산 0**: `hint_level`은 핸들러가 이미 보유한 `decision.hint_level`을 그대로 전달받는다
    (`decision`은 `_build_response_payload`가 반환하는 6-튜플의 첫 요소). verify와 달리 검증기를
    다시 부를 필요 없이 *이미 계산된* 값만 적재한다 — `_build_response_payload` 시그니처·반환을
    건드리지 않는다(읽기만).

    적재 신호의 의미: 이 hint_level은 AI가 *제공한* 노출량(supply·graded 1~4·1=가장 은근/
    4=전체 풀이)이지 학생이 *요청*한 demand(`힌트요청`)가 아니다 — 도움 감소 곡선은 supply 추세를
    본다. `hint_level`이 None이면(이론적 경계·decision은 항상 int지만 방어적) early return으로
    적재하지 않는다(날조 회피 — 신호 없는 행 미생성).

    트랜잭션: `_log_verify_event`와 동일하게 ORM 1행을 `session.add`만 하고 *commit은 하지
    않는다* — 호출 핸들러가 자기 트랜잭션을 commit하므로 그 트랜잭션에 합류한다(별도 commit 금지).
    `event_at`은 핸들러와 동일하게 now(복합 PK 구성요소·시계열 순서축).

    **S3-03 mode 태깅**: `_log_verify_event`와 동형으로 `mode`·`persona`(선택)를 event_data에
    실어 ⑤(도움 감소)·⑧(도달 깊이)의 mode-scoped 집계를 가능하게 한다. None(기본)이면 미태깅.
    """
    if hint_level is None:
        return  # 힌트 레벨 없음(이론적 경계) → 적재 안 함(날조 회피).

    event = AttemptEventORM(
        event_at=datetime.now(timezone.utc),
        attempt_id=attempt_id,
        user_id=user_id,
        problem_id=problem_id,
        event_type=EventType.힌트제공,
        event_data=build_event_data(
            EventType.힌트제공,
            hint_level=hint_level,
            mode=mode,
            persona=persona,
            client_state_mismatch=client_state_mismatch,
        ),
    )
    session.add(event)  # commit은 핸들러가 — 같은 트랜잭션에 합류(별도 commit 금지).


async def _log_demand_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    problem_id: uuid.UUID | None,
    attempt_id: uuid.UUID | None,
    student_input: str,
    event_at: datetime,
    mode: str | None = None,
    persona: str | None = None,
) -> None:
    """학생의 답 요구 발화를 `attempt_event`(event_type=힌트요청)로 1행 적재 — S3-16 소생.

    WH-1 행동 텔레메트리 공백을 메우는 *생산자 좌석*(`docs/architecture/
    ai_tutor_module_gap_review.md` §3 D4)의 하나. `is_answer_demand`(재계산 아님·`decide_hint_
    level` 2번 규칙과 동일 상수)가 False면 적재 안 함(신호 없는 행 미생성·날조 회피) — `_log_hint_
    event`의 `hint_level is None` early-return과 동형 원칙.

    트랜잭션: `_log_verify_event`·`_log_hint_event`와 동일하게 ORM 1행을 `session.add`만 하고
    *commit은 하지 않는다*(호출 핸들러의 트랜잭션에 합류). `event_at`은 호출 핸들러가 이미 가진
    `now`를 그대로 받는다(별도 `datetime.now()` 재호출 금지 — 복합 PK 시각 일관성).
    """
    if not is_answer_demand(student_input):
        return  # 답 요구 신호 없음 → 적재 안 함(날조 회피).

    event = AttemptEventORM(
        event_at=event_at,
        attempt_id=attempt_id,
        user_id=user_id,
        problem_id=problem_id,
        event_type=EventType.힌트요청,
        event_data=build_event_data(EventType.힌트요청, mode=mode, persona=persona),
    )
    session.add(event)  # commit은 핸들러가 — 같은 트랜잭션에 합류(별도 commit 금지).


async def _log_stuck_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    problem_id: uuid.UUID | None,
    attempt_id: uuid.UUID | None,
    turn_count: int,
    event_at: datetime,
    mode: str | None = None,
    persona: str | None = None,
) -> None:
    """5회+ 막힘 임계 도달을 `attempt_event`(event_type=막힘)로 1행 적재 — S3-16 소생.

    `is_stuck_turn_count`(재계산 아님·`decide_hint_level` 1번 규칙과 동일 임계)가 False면
    적재 안 함(신호 없는 행 미생성·날조 회피). `turn_count`는 `PolyaState.turn_count`를 그대로
    싣는다(재계산 아님).

    트랜잭션: 형제 writer들과 동형(`session.add`만·commit은 핸들러). `event_at`은 핸들러의
    `now`를 그대로 받는다.
    """
    if not is_stuck_turn_count(turn_count):
        return  # 막힘 임계 미도달 → 적재 안 함(날조 회피).

    event = AttemptEventORM(
        event_at=event_at,
        attempt_id=attempt_id,
        user_id=user_id,
        problem_id=problem_id,
        event_type=EventType.막힘,
        event_data=build_event_data(
            EventType.막힘, turn_count=turn_count, mode=mode, persona=persona
        ),
    )
    session.add(event)  # commit은 핸들러가 — 같은 트랜잭션에 합류(별도 commit 금지).


async def _log_response_latency_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    problem_id: uuid.UUID | None,
    attempt_id: uuid.UUID | None,
    dialogue_id: uuid.UUID,
    now: datetime,
    student_order: int,
    mode: str | None = None,
    persona: str | None = None,
) -> None:
    """직전 학생 턴(server 기준 spoken_at)과 이번 제출 시각의 차를 답입력 이벤트로 적재(S3-16 소생).

    서버 시각 차이므로 클라 신뢰가 불필요하고 조작 불가하다(D4 설계). `append_turns`에서만
    호출한다 — `create_session`은 새 dialogue의 첫 턴이라 이전 턴 기준선이 없어 latency 정의
    불가(날조 회피). 이론상 append_turns는 create_session이 만든 최초 교환 위에서만 호출되므로
    직전 학생 턴이 항상 있어야 하지만, 방어적으로 없으면(None) 기준선 없음으로 보고 행 미생성한다.

    트랜잭션: 형제 writer들과 동형(`session.add`만·commit은 핸들러). `event_at`은 핸들러의
    `now`를 그대로 받는다(복합 PK 시각 일관성).
    """
    prev_stmt = (
        select(DialogueTurnORM.spoken_at)
        .where(
            DialogueTurnORM.dialogue_id == dialogue_id,
            DialogueTurnORM.role == TurnRole.student,
            DialogueTurnORM.turn_order < student_order,
        )
        .order_by(DialogueTurnORM.turn_order.desc())
        .limit(1)
    )
    prev_spoken_at = (await session.execute(prev_stmt)).scalars().first()
    if prev_spoken_at is None:
        return  # 기준선 없음(이론상 도달 안 함) → 적재 안 함(날조 회피).

    latency_ms = int((now - prev_spoken_at).total_seconds() * 1000)
    event = AttemptEventORM(
        event_at=now,
        attempt_id=attempt_id,
        user_id=user_id,
        problem_id=problem_id,
        event_type=EventType.답입력,
        event_data=build_event_data(
            EventType.답입력, server_latency_ms=latency_ms, mode=mode, persona=persona
        ),
    )
    session.add(event)  # commit은 핸들러가 — 같은 트랜잭션에 합류(별도 commit 금지).


async def _apply_hypotheses(
    session: AsyncSession,
    user_id: uuid.UUID | None,
    matches: list[MisconceptionMatch],
) -> list[MisconceptionHypothesis]:
    """이번 턴 매칭(증거)으로 학생 활성 가설 세트를 1턴 *큐레이션*·영속해 반환 — coach 세션/턴 전용.

    WH-1 2단계 §8.4 슬라이스 3 *결선* 좌석. #191 순수 로직·#192 저장소(`curate_hypothesis`)를
    *재사용만* 한다(재구현 0). 핸들러의 `session`/트랜잭션에 합류하고 `curate_hypothesis`가 flush만
    하므로(commit은 핸들러), 가설 갱신이 dialogue/turn 쓰기와 *같은 트랜잭션*에서 원자적으로
    영속된다(별도 commit 없음). 반환 가설은 응답 `active_hypotheses`로 노출된다(매칭 없으면
    빈 리스트 — 감쇠·가지치기 후 빈 세트면 그대로).

    **하네스 동치(parity)**: `apply_matches`(매치만)가 아니라 §3 도구4 `curate_hypothesis`를 쓴다
    — `evidence_links` 순지지도(`net_support`)가 *음수*(반박 우세)인 가설은 archived하고(R4 확증
    편향·거짓 낙인 방지) 최대 5개 활성으로 캡한다(§2.2 큐레이션 규칙·초점). 같은 `student_id` 증거
    그래프를 하네스(`harness/wh1_session.py`)와 공유하므로 *단일 진실원천*이다 — 하네스가 반박한
    오개념을 라이브도 동일 제외. 반박 증거 없고 활성 ≤5면 `apply_matches`와 결과 동일(하위호환).

    `user_id` 가드: `ConsentedUser` 인증 게이트라 실제론 항상 채워지지만, 방어적으로 None이면
    가설을 적용·영속하지 않고 빈 리스트를 반환한다(`curate_hypothesis`는 per-student·user_id 필수).

    범위(정직): per-turn *영속+노출* + 개입 발화 결선까지다. 갱신된 가설 세트는 바로 아래
    `_intervention_from_hypotheses_or`로 *개입 발화*도 구동한다(select_focus 기반 intervention —
    이 슬라이스에서 결선). 라이브 경로 증거 *적재*(`log_evidence`)는 아직 하네스 몫이라 net_support
    는 하네스가 쌓은 증거를 *소비*만 한다(라이브 자가 적재는 후속). 진단-실제 *일치율* 게이트·도구
    루프 오케스트레이션도 후속 슬라이스다.
    """
    if user_id is None:
        return []  # 인증 게이트라 도달 안 함(방어 가드 — curate_hypothesis는 user_id 필수).
    return await curate_hypothesis(session, student_id=user_id, matches=matches)


async def _log_match_evidence(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    student_id: uuid.UUID | None,
    matches: list[MisconceptionMatch],
) -> None:
    """이번 턴 *확정 매치*를 +1 지지 증거로 `evidence_links`에 적재한다(§2.3 생산측 좌석).

    #268이 라이브 coach를 증거 그래프의 *소비측*(`curate_hypothesis`→`net_support<0` 반박)으로
    결선했다면, 본 헬퍼는 그 짝인 ***생산측***이다 — 하네스(`run_persisted_turn`)의 `log_evidence`
    영속 패턴을 결정론 규칙으로 모사한다(재구현 0). `outcome.matches`는 이미 신뢰 게이트
    (top-1<0.65→후보 비움)를 통과한 *확정 진단*이라 추가 floor 불요·match당 +1(지지·진단이 오개념
    신호를 드러냄)·`weight=confidence`(net_support 가중).

    **순서(비순환)**: 호출자는 본 헬퍼를 `_apply_hypotheses`(=`curate_hypothesis`·*직전까지* 누적된
    net_support로 반박 판정) **뒤에** 둔다 — 이번 턴 지지가 같은 턴의 반박을 순환적으로 막지 않고
    *미래 턴* net_support에만 반영된다(소비는 과거 증거·생산은 미래 증거).

    **짝**: −1 *반박* 생산은 `_log_refutation_evidence`(바로 아래)가 담당한다 — clean 검증 풀이가
    의심 오개념을 약하게 반박. no-match 게이트로 둘은 *상호배타*(한 턴은 지지 또는 반박 중 하나).

    `log_evidence`는 주입 `session`에 합류·flush만(commit은 핸들러). `student_id` None이면 가드(인증
    게이트라 미도달)·빈 matches면 no-op. `session_id`는 dialogue UUID(느슨참조·FK 아님).
    """
    if student_id is None:
        return  # 인증 게이트라 도달 안 함(방어 가드 — log_evidence는 student_id 필수).
    for match in matches:
        await log_evidence(
            session,
            session_id=session_id,
            student_id=student_id,
            misconception_id=match.misconception.id,
            polarity=1,  # 매치 = 오개념 *지지* 증거(진단이 오개념 신호를 드러냄).
            weight=match.confidence,
        )


async def _log_refutation_evidence(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    student_id: uuid.UUID | None,
    passed: bool | None,
    matches: list[MisconceptionMatch],
    active_hypotheses: list[MisconceptionHypothesis],
    solution_text: str | None,
) -> None:
    """clean하게 검증된 풀이 1턴을 *현재 의심* 오개념에 대한 −1 *반박* 증거로 적재(§2.3 짝).

    #269가 +1 *지지* 생산(`_log_match_evidence`)을 결선했으나 −1 *반박* 생산이 없어, #268의
    `curate_hypothesis` archived 가드(`net_support<0`)가 라이브-단독 학생에겐 발동하지 못했다
    (net_support≥0). 본 헬퍼가 그 −1 좌석을 *보수적*으로 결선해 evidence 아크를 닫는다 — 04a §2.3
    "verify가 가설 *예측*과 모순되면 −1"의 결정론 조작화.

    **규칙(보수)**: ① 풀이 제출 턴이 clean 검증(`passed is True`)이고 ② 이번 턴 *확정 매치가 없을*
    때만(`not matches`) ③ *현재 active 가설 각각*에 `polarity=-1·weight=_REFUTE_WEIGHT(0.5)`를 적재.
      - **passed 게이트**: 도구 검증된 올바른 풀이 = "학생이 (오류 유발) 오개념을 가졌다"는 예측과
        모순(약한 반대 증거). `passed is None`(풀이 아님)·`False`(거짓관계 적발)은 반박 안 함 — `is
        True` 명시 비교로 None/False를 한 번에 배제(현재 슬라이스는 −1만·verify-fail→+1은 후속).
      - **no-match 게이트(정합·핵심)**: 이번 턴이 오개념을 *매치*했으면(`_log_match_evidence`가 +1)
        반박 안 함 → 한 턴은 지지(매치) 또는 반박(clean 정답) *둘 중 하나*(같은 턴 모순 적재 차단·
        매치+정답 동시 턴은 +1 우선).
      - **tier 가중(정밀 귀속)**: active 가설 각각에 −1을 적재하되 *증거 강도로 가중을 tier*한다.
        풀이에 그 오개념의 *정정 형태*(`correct_form`)가 검출되면(`correct_form_present`) `_REFUTE_
        STRONG_WEIGHT`(1.0·정밀: "학생이 M의 올바른 형태를 직접 보임"), 아니면 `_REFUTE_WEIGHT`
        (0.5·막연한 clean 작업). 대상은 curate가 ≤5·recency로 좁힌 *현재* 의심(active_hypotheses)뿐
        — 오래된 무관 오개념은 이미 decay/prune. 과거 한계(verify 신호는 *일반* 계산정합이라 특정
        오개념 귀속 불가·'올바른 형태' 부재)를 `correct_form`(identity-shaped에 부여) 검출로 *부분
        해소* — 정정이 검출되는 오개념은 정밀(강), 나머지는 보수(약). 강·약 모두 낙인
        방지(−1 방향)·실신호 보존(강 1.0도 만점 단일 매치를 *즉시* 죽이진 않음). domain 스코핑은
        데이터 부재로 보류(후속·NOT).

    **순서(생산=미래)**: `_log_match_evidence`와 동일하게 `_apply_hypotheses`(curate·*직전까지*
    net_support 소비) **뒤에** 둔다 — 이번 턴 −1은 같은 턴 curation을 바꾸지 않고 *미래*
    net_support에만 반영(소비=과거·생산=미래). decay(자연 감쇠)에 더해 *능동적 clearing*을 준다.

    `log_evidence`는 주입 `session`에 합류·flush만(commit은 핸들러). `student_id` None(인증 게이트라
    미도달)·게이트 미충족·빈 active면 no-op. `session_id`는 dialogue UUID(느슨참조·FK 아님).
    """
    if student_id is None:
        return  # 인증 게이트라 도달 안 함(방어 가드 — log_evidence는 student_id 필수).
    if passed is not True:
        return  # clean 검증(통과)만 반박 — None(풀이 아님)·False(거짓관계 적발)은 제외.
    if matches:
        return  # no-match 게이트 — 이번 턴이 매치(+1 지지)면 같은 턴 반박 안 함(모순 차단).
    text = solution_text or ""  # passed is True ⟹ student_solution 비어있지 않음(verify 게이트).
    for hyp in active_hypotheses:
        # 정정 형태 검출 시 정밀·강한 반박(1.0), 아니면 막연한 clean 작업의 약한 반박(0.5).
        entry = CATALOG_BY_ID.get(hyp.misconception_id)
        strong = entry is not None and correct_form_present(entry, text)
        await log_evidence(
            session,
            session_id=session_id,
            student_id=student_id,
            misconception_id=hyp.misconception_id,
            polarity=-1,  # clean 정답 = 의심 오개념 *반박* 증거(#1 낙인 방지).
            weight=_REFUTE_STRONG_WEIGHT if strong else _REFUTE_WEIGHT,
            # MISC-20: 해소 판정의 유일한 축은 이 *출처 표식*이다(가중치가 아니다 — 가중치는
            # nullable이고 하네스 경로에선 LLM이 지정한다). 정정 형태를 기계가 실측한
            # 경우에만 값을 남기고, 아니면 None으로 둔다(모르는 것을 해소로 세지 않는다).
            provenance=CORRECT_FORM_DEMONSTRATED if strong else None,
        )


def _wh1_turn_state(total_turns_before: int) -> tuple[int, bool]:
    """이 교환(student↔AI)의 WH-1 턴 번호 + ε-탐색 턴 여부 — 멀티턴 연속성 카운터(§2.2).

    `total_turns_before`(이번 턴 추가 *전* `dialogue.total_turns` — 교환당 +2라 짝수)에서 1-기반
    WH-1 턴 번호를 유도한다(create=0→1·n번째 append=2n→n+1). `is_exploration_turn`으로 ε-탐색
    주기(기본 5턴마다)도 함께 표식한다 — 설계 §2.2 "하네스가 카운터를 관리"를 *세션 상태(dialogue)*
    에서 충족한다. 활성 가설 세트(웜 스타트로 복원·`active_hypotheses`)와 함께 노출돼 멀티턴 연속성
    (직전 누적 상태 위에 이번 턴 진행)을 클라이언트·후속 도구 루프가 관측할 수 있게 한다.
    """
    turn_index = total_turns_before // 2 + 1
    return turn_index, is_exploration_turn(turn_index)


def _intervention_from_hypotheses_or(
    active_hypotheses: list[MisconceptionHypothesis],
    fallback: InterventionDecision | None,
) -> InterventionDecision | None:
    """개입 발화를 *누적 가설 세트* 기준으로 재결정 — WH-1 2단계 §8.4 *결선* 좌석.

    `_apply_hypotheses` docstring이 예고한 "select_focus 기반 intervention 변경(ε 탐색→개입
    발화)"의 실현. 단일 턴 raw 매치(`fallback` = `_build_response_payload`의 substring-우선
    매치 기반 결정)가 아니라, 시간 감쇠·강화로 **누적된 활성 가설 세트**가 개입을 구동하게
    한다(#191 `select_focus`·`select_intervention_from_hypotheses` 재사용·재구현 0).

    *폴백 보존*(회귀 0): 가설 세트가 결정을 못 내면(빈 세트·focus<0.5 보류·느슨 id) `fallback`을
    그대로 둔다. **턴1**은 가설이 이번 턴 매치로 막 시드되어(감쇠 전) 신뢰도=매치 신뢰도이므로,
    최상위 가설이 raw 매치 1위와 같으면 결과가 비트동일하다. 차이는 *멀티턴 누적*(강화로 반례
    임계 돌파·감쇠로 보류 전환) 또는 가설 세트가 substring-우선과 다른 1위를 가질 때만 난다 —
    그게 정확히 WH-1이 의도한 "상태(누적 증거)가 개입을 결정한다"이다. stateless `/v1/coach`는
    가설 세트가 없어 *호출하지 않는다*(raw 매치 유지).
    """
    return select_intervention_from_hypotheses(active_hypotheses) or fallback


async def _turn_meta_rows(session: AsyncSession, dialogue_id: uuid.UUID) -> list[TurnMetaRow]:
    """대화의 **평문 메타만** 컬럼 투영으로 읽는다(PED-04 D1 reader ①·D2 입력).

    `select(DialogueTurnORM)`으로 엔티티를 통째 로드하지 **않는다** — 그러면 복호하지 않더라도
    미성년 대화 ciphertext가 메모리에 올라온다(데이터 최소화). 4개 컬럼만 투영한다.

    **호출 위치가 계약이다**: 이번 턴을 `session.add`하기 *전에* 불러야 한다. 뒤로 옮기면
    `turn_count`가 이번 턴만큼 부풀어 D2 파생이 조용히 오염된다(통합 테스트가 수치로 동결).
    """
    result = await session.execute(
        select(
            DialogueTurnORM.turn_order,
            DialogueTurnORM.role,
            DialogueTurnORM.targeted_step,
            DialogueTurnORM.student_intent,
        )
        .where(DialogueTurnORM.dialogue_id == dialogue_id)
        .order_by(DialogueTurnORM.turn_order)
    )
    return [TurnMetaRow(*row) for row in result.all()]


async def _prev_hint_level_for(
    session: AsyncSession, *, user_id: uuid.UUID, problem_id: uuid.UUID | None
) -> int | None:
    """직전에 *제공한* 힌트 단계 — `_log_hint_event`(supply) 적재의 짝 reader(PED-04 D2).

    지금까지 `prev_hint_level`은 클라가 실어 보냈다. 그런데 이 값은 답 미루기 점진 상승의 입력
    이고 S3 파일럿의 "도달 깊이" KPI 축이라, 클라 신뢰에 맡기면 측정이 조작·버그에 열린다.
    적재 좌석이 이미 있으므로 **신규 스키마 0으로** 서버가 되찾을 수 있다.

    이력이 없으면 None(첫 결정 — `decide_hint_level`이 1부터 시작).
    """
    stmt = (
        select(AttemptEventORM.event_data)
        .where(
            AttemptEventORM.user_id == user_id,
            AttemptEventORM.event_type == EventType.힌트제공,
        )
        .order_by(AttemptEventORM.event_at.desc())
        .limit(1)
    )
    if problem_id is not None:
        stmt = stmt.where(AttemptEventORM.problem_id == problem_id)
    payload = (await session.execute(stmt)).scalar_one_or_none()
    if not isinstance(payload, dict):
        return None
    level = payload.get("hint_level")
    return level if isinstance(level, int) and 1 <= level <= 4 else None


async def _session_recall_or_none(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    active_hypotheses: list[MisconceptionHypothesis],
    exclude_dialogue_id: uuid.UUID | None,
) -> SessionRecall | None:
    """직전 세션의 교수 이력을 **메타만** 회상한다(never-break·복호 0).

    `_warmstart_hints_or_empty` 선례 그대로 never-break로 감싼다 — 회상 실패가 학생 응답을 깨면
    안 된다(가용성 ≫ 회상). 예외는 삼키되 **타입명을 반드시 로그에 남긴다**(침묵 실패 금지).

    본문 컬럼(`content`·`content_encrypted`·`image_*`)을 **select 목록에 넣지 않는다** — 이 함수가
    암호화 봉투를 여는 경로가 되지 않게 하는 구조적 장치이며, SQL 캡처 테스트로 동결한다.
    """
    try:
        prior_id = (
            await session.execute(
                select(DialogueORM.dialogue_id)
                .where(
                    DialogueORM.user_id == user_id,
                    *(
                        (DialogueORM.dialogue_id != exclude_dialogue_id,)
                        if exclude_dialogue_id is not None
                        else ()
                    ),
                )
                .order_by(DialogueORM.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if prior_id is None:
            return None

        rows = (
            await session.execute(
                select(DialogueTurnORM.targeted_step, DialogueTurnORM.socratic_strategy)
                .where(
                    DialogueTurnORM.dialogue_id == prior_id,
                    DialogueTurnORM.role == TurnRole.assistant,
                )
                .order_by(DialogueTurnORM.turn_order)
            )
        ).all()
        turns_since = (
            await session.execute(
                select(sa_func.coalesce(sa_func.sum(DialogueORM.total_turns), 0)).where(
                    DialogueORM.user_id == user_id,
                    DialogueORM.dialogue_id != prior_id,
                )
            )
        ).scalar_one()
        return assemble_session_recall(
            last_stage_step=rows[-1][0] if rows else None,
            strategies=[strategy for _step, strategy in rows],
            active_hypothesis_ids=[h.misconception_id for h in active_hypotheses],
            turns_since=int(turns_since or 0),
        )
    except Exception as exc:  # noqa: BLE001 — 회상 실패는 학생 응답을 안 깬다(never-break).
        logger.warning(
            "세션 회상 조립 실패(%s) — 회상 없이 진행", type(exc).__name__, exc_info=True
        )
        return None


async def _warmstart_hints_or_empty(
    session: AsyncSession, *, problem_id: uuid.UUID | None, exclude_mids: Sequence[str] = ()
) -> list[str]:
    """웜스타트 probe 힌트(outside_mids) 조립 — WH-1 shadow·primary 공용(never-break).

    S1-c: 진단 시작 시 하네스 탐색 probe가 겨냥할 외부 오개념 후보를 단원 고빈도+atom 확장으로
    미리 공급한다(감사 Q5). **진단 probe 타깃팅 전용** — 코칭 context·개입엔 오개념을 preload하지
    않는다(reactive 유지·CLAUDE.md). 조회만이라 실패해도 학생 응답을 깨면 안 되므로 never-break로
    감싸 빈 리스트로 폴백한다(가용성 #1≫진단 관측 #6·예외 타입명 로그 — 침묵 실패 금지). 직전엔
    create/append 두 핸들러에 인라인 중복이던 블록을 primary flip(S1-11)이 세 번째 소비처가 되며
    단일 헬퍼로 모았다(동작 불변).
    """
    try:
        return await assemble_warmstart_probe_hints(
            session,
            problem_id=problem_id,
            provider=build_provider(get_settings()),
            # PED-04: 이미 활성인 가설은 탐색 표적에서 뺀다(warmstart=무엇을 의심할지 /
            # recall=무엇을 이미 시도했는지 — 교집합 0으로 상보 유지).
            exclude_mids=exclude_mids,
        )
    except Exception as exc:  # noqa: BLE001 — 웜스타트 실패는 학생 응답을 안 깬다(never-break).
        logger.warning(
            "웜스타트 probe 힌트 조립 실패(%s) — 빈 힌트로 진행", type(exc).__name__, exc_info=True
        )
        return []


async def _wh1_primary_decision_or(
    decision: PedagogyDecision,
    *,
    body: CoachRequest,
    active_hypotheses: list[MisconceptionHypothesis],
    warmstart_mids: list[str],
    provider: LLMProvider | None,
    turn_index: int,
    dialogue_id: str | None,
    problem_id: uuid.UUID | None,
    session_recall: SessionRecall | None = None,
    session: AsyncSession | None = None,
    theta: float | None = None,
    user_id: uuid.UUID | None = None,
    pack: PedagogyPack | None = None,
) -> PedagogyDecision:
    """flip(S1-11): 학생-대면 발화를 WH-1 하네스 LLM 발화로 교체 — 실패 시 결정론 폴백.

    `wh1_primary_enabled`일 때만 핸들러가 호출한다. `run_wh1_primary_turn`이 하네스 verify
    의무(§3.1)·정답 억제(§3.4)·L4 톤필터를 통과한 발화만 돌려주며, 실패·타임아웃·예산 소진이면
    `None`(사유는 그쪽이 예외 타입명 포함 로그) → 기존 결정론 `decision`을 그대로 반환한다
    (가용성 — 앱은 죽지 않는다·발화 외 결정 필드는 항상 결정론 유지). 교체는 `model_copy`로
    `prompt`(학생-대면 발화 본문)만 — hint_level·전이·socratic_category 등 구조화 결정과
    solution_coaching·가설·증거 파이프라인은 기존 결정론 경로 그대로다(상태 오케스트레이션
    수렴은 후속·`run_persisted_turn` docstring 참조). 여기서도 방어적으로 try/except를 한 겹 더
    둔다 — 테스트 대체물·미래 리팩터가 예외를 전파해도 학생 응답이 500이 되지 않게(이중 방어).

    `session`·`theta`·`user_id`(REC-02 ②)는 `run_wh1_primary_turn`의 select_probe 후보 공급으로
    그대로 흐른다 — 호출자가 이미 조회한 `server_theta`·`user.user_id`를 재사용할 뿐 신규 쿼리는
    없다(create_session·append_turns 두 핸들러가 이미 계산해 둔 값).

    `pack`(PED-23 회수 — 04e §9): `_pack_for`가 해석해 `decide(pack=)`에 넣은 *같은* 팩 객체를
    러너로 thread한다 — 러너가 톤필터 직전 금지모드 가드(`mode_guard_runtime_enabled` 옵트인·
    기본 OFF)에 재사용(위반 발화 미서빙·소크라테스 재질문 폴백). None(무팩·플래그 OFF 해석)이면
    가드 무관.
    """
    try:
        utterance = await run_wh1_primary_turn(
            student_solution=body.student_solution or body.student_input,
            solution_steps=body.solution_steps or [],
            active_hypotheses=active_hypotheses,
            provider=provider,
            turn_index=turn_index,
            dialogue_id=dialogue_id,
            problem_id=str(problem_id) if problem_id is not None else None,
            warmstart_outside_mids=warmstart_mids,
            session_recall=session_recall,
            session=session,
            theta=theta,
            user_id=user_id,
            pack=pack,
        )
    except Exception as exc:  # noqa: BLE001 — flip은 앱을 죽이지 않는다(이중 방어·타입명 로그).
        logger.warning(
            "WH-1 primary 경로 예외(%s) — 결정론 템플릿 폴백", type(exc).__name__, exc_info=True
        )
        return decision
    if utterance is None:
        return decision  # 결정론 폴백(사유는 run_wh1_primary_turn이 이미 로그).
    return decision.model_copy(update={"prompt": utterance})


def _build_dialogue_turn(
    schema: DialogueTurnSchema,
    cipher: SupportsEnvelope | None,
    meta: TurnMeta | None = None,
) -> DialogueTurnORM:
    """감사상환 #2: 스키마 → 대화 턴 ORM(본문 봉투 암호화 적용) — 4개 write 경로의 단일 좌석.

    순수 seam(`from_schema`)엔 cipher를 주입하지 않고(device store가 handler 층에서 암호화하는
    선례 미러), 이 *handler/헬퍼 층* 함수가 `content`를 암호화해 저장 표현을 결정한다.
    `encrypt_dialogue_content`가 cipher 유무·content None을 분기: cipher 있으면 content=NULL·
    content_encrypted/content_nonce 세팅(평문 원문 DB 부재), cipher None이면 평문 폴백
    (content=평문·encrypted=None — 조용한 무동작 아닌 *명시* 폴백·CI/기존 배포 무영향).
    create_session·append_turns의 학생/AI 턴 4곳이 모두 이 헬퍼를 거쳐 중복·누락을 없앤다.

    SEC-01: 멀티모달 두 축(`image_uri`·`image_analysis`)도 **같은 좌석에서 같은 키로** 암호화한다
    — 손글씨 URI·Qwen3-VL 분석은 미성년 풀이 전사가 가능한 데이터라 본문과 같은 등급이다.
    분기 로직은 본문과 동일(cipher 없으면 명시 평문 폴백·값 None이면 3-튜플 전부 None).
    """
    turn = DialogueTurnORM.from_schema(schema)
    content_plain, content_encrypted, content_nonce = encrypt_dialogue_content(
        cipher, schema.content
    )
    turn.content = content_plain
    turn.content_encrypted = content_encrypted
    turn.content_nonce = content_nonce

    uri_plain, uri_encrypted, uri_nonce = encrypt_dialogue_image_uri(cipher, schema.image_uri)
    turn.image_uri = uri_plain
    turn.image_uri_encrypted = uri_encrypted
    turn.image_uri_nonce = uri_nonce

    analysis_plain, analysis_encrypted, analysis_nonce = encrypt_dialogue_image_analysis(
        cipher, schema.image_analysis
    )
    turn.image_analysis = analysis_plain
    turn.image_analysis_encrypted = analysis_encrypted
    turn.image_analysis_nonce = analysis_nonce

    # PED-04 D1: 교수 결정 메타 4축 적재. **평문 열**이라 위 봉투 암호화 3축과 성격이 다르고,
    # 그래서 암호화 블록 *뒤*에 분리해 붙인다(암호화 좌석의 책임을 흐리지 않는다). `meta=None`
    # (stateless·기존 호출)이면 한 줄도 실행되지 않아 현행과 비트동일.
    if meta is not None:
        turn.socratic_strategy = meta.socratic_strategy
        turn.targeted_step = meta.targeted_step
        turn.student_intent = meta.student_intent
        turn.student_understanding_signal = meta.student_understanding_signal
    return turn


@router.post(
    "/coach",
    response_model=CoachResponse,
    summary="L4 교수학 통합 결정(stateless)",
    dependencies=[RateLimitedTripleWrite],
)
async def coach_decide(
    body: CoachRequest,
    user: ConsentedUser,
    judge_deps: JudgeSeamDeps,
    segmentation_counters: SegmentationCountersDep,
    subject_capabilities: SubjectCapabilityDeps,
) -> CoachResponse:
    """학생 발화 → Polya 결정 + 오개념 진단 + LTHC 조정안을 *한 번에* 반환.

    *DB 무접근* — 영속이 필요하면 `/v1/coach/sessions`를 호출. `user`는 인증 게이트만.
    """
    _ = user.user_id  # 인증 게이트 통과 확인용(stateless라 user 데이터 미사용)
    # NLP-03 acceptance ③ — 클라가 실어 보낸 solution_steps의 0-전이(<=1) 비율 관측.
    segmentation_counters.record(body.solution_steps)

    # slice 106: 오개념 후보를 비블로킹 결합(게이트 off면 substring만)으로 미리 계산해 주입.
    # WH-1: ocr_confidence를 게이트로 thread하고(§3.3 게이트 ②), 게이트 플래그를 응답에 노출한다.
    # MISC-17: 진단 입력도 WH-1 primary와 같은 관용구 — 사진(OCR) 제출 턴(student_input=''
    # + student_solution 채움)의 풀이가 후보·가설·증거 적재에 합류한다. student_solution이
    # None/''이면 `or` 폴백으로 종전 텍스트 턴과 비트동일(회귀 0). 이어붙이기·새 게이트 없음.
    outcome = await _compute_matches(
        body.student_solution or body.student_input,
        ocr_confidence=body.ocr_confidence,
        judge_deps=judge_deps,
    )
    # S4-19: carry(게이트 이전 단계 검증 운반값)는 stateless 경로에선 미소비(DB 무접근 계약 —
    # 적재 좌석 없음). 마지막 원소=solution_coaching 불변식은 유지된다.
    decision, matches, intervention, lthc, entry_category, _step_carry, solution_coaching = (
        _build_response_payload(
            body,
            matches=outcome.matches,
            step_chain_verifier=subject_capabilities.step_chain,
        )
    )
    return CoachResponse(
        decision=decision,
        misconceptions=matches,
        intervention=intervention,
        lthc=lthc,
        entry_socratic_category=entry_category,
        solution_coaching=solution_coaching,
        match_low_quality=outcome.low_quality,
        match_attribution_unclear=outcome.attribution_unclear,
        no_confident_match=outcome.no_confident_match,
    )


@router.post(
    "/coach/sessions",
    response_model=SessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="L4 코치 세션 생성(dialogue + 학생/AI 2턴 영속)",
    dependencies=[RateLimitedTripleWrite],
)
async def create_session(
    body: SessionCreateRequest,
    user: ConsentedUser,
    session: SessionDep,
    judge_deps: JudgeSeamDeps,
    segmentation_counters: SegmentationCountersDep,
    subject_capabilities: SubjectCapabilityDeps,
) -> SessionCreateResponse:
    """새 대화 + 학생/AI 첫 2턴 영속. AI 턴은 WH-1 primary 발화(기본 ON·폴백=`decision.prompt`).

    트랜잭션: dialogue 먼저 commit(PK 확보) → turns commit(FK 의존). `user_id`는 인증된
    `user.user_id`로 자동 설정(타인 데이터 차단). 미성년 채팅 평문 저장은 *저장 계층*
    책임(모듈 docstring 참조 — DB 암호화 at-rest는 후속 인프라 슬라이스).
    """
    # NLP-03 acceptance ③ — 클라가 실어 보낸 solution_steps의 0-전이(<=1) 비율 관측.
    segmentation_counters.record(body.solution_steps)
    # slice 64: 문항 기대정답을 서버 DB에서 조회해 step shadow 진단 맥락으로 주입(비노출 — 응답엔
    # 결코 싣지 않음·정답 누출 차단). 문항 부재/없음이면 None(graceful).
    expected_answer = await _expected_answer_for(session, body.problem_id)
    # slice 70: 서버 L2 저장소의 실제 숙달도를 조회해 클라 bkt 대체(게이트 ON·비노출).
    server_mastery = await _server_mastery_for(session, user.user_id, body.problem_id)
    # slice 73·74: 서버 L2의 실제 θ도 조회 — BKT↔θ 교차검증(게이트 ON·θ 수치 비노출). slice 74:
    # 문항 개념의 *개념별* θ 우선·없으면 전과목 폴백(_server_theta_for 내부).
    server_theta = await _server_theta_for(session, user.user_id, body.problem_id)
    # 선수 복습 코칭 — 이 문제 개념의 막힌 선수가 있으면 "선수 복습 먼저" 신호(L2 fetch + L4 decide
    # 배선·`/me/.../coaching`과 동형). Polya 결정과 *별개의 추가 신호*(non-override·턴 비가로채기).
    prereq = await _prerequisite_coaching_for(session, user.user_id, body.problem_id)
    # slice 106: 오개념 후보를 비블로킹 결합(게이트 off면 substring만)으로 미리 계산해 주입.
    # WH-1: ocr_confidence를 게이트로 thread하고(§3.3 게이트 ②), 게이트 플래그를 응답에 노출한다.
    # MISC-17: 진단 입력도 WH-1 primary와 같은 관용구 — 사진(OCR) 제출 턴(student_input=''
    # + student_solution 채움)의 풀이가 후보·가설·증거 적재에 합류한다. student_solution이
    # None/''이면 `or` 폴백으로 종전 텍스트 턴과 비트동일(회귀 0). 이어붙이기·새 게이트 없음.
    outcome = await _compute_matches(
        body.student_solution or body.student_input,
        ocr_confidence=body.ocr_confidence,
        judge_deps=judge_deps,
    )
    # WH-1 2단계 §8.4 슬라이스 3 — 이번 턴 매칭(증거)으로 학생 활성 가설 세트를 큐레이션·영속한다
    # (#191 순수 로직 + #192 저장소 재사용·재구현 0). 같은 `session`/같은 트랜잭션에 합류하며
    # curate_hypothesis(증거 반박·캡)는 flush만 하고 commit은 *핸들러의 기존 commit*이 담당(별도 X).
    # `user.user_id`는 ConsentedUser 게이트라 채워지지만, None이면 빈 리스트로 가드(per-student라
    # user_id 필요). 가설은 *후보*일 뿐 확정 오개념 아님(낙인 금지)·학생 본인 데이터만 노출.
    # 결정 *앞에서* 적용한다 — 갱신된 가설 세트를 _build_response_payload로 넘겨 소크라테스
    # 카테고리(ASSUMPTION 가정 표면화)까지 구동(개입 채널과 동일한 post-apply 세트·단일 진실원천).
    # MISC-17 (PR #1034 Codex P1 수용): 게이트 ② `low_quality`(OCR 인식 신뢰도<0.8)의 *집행 지점*.
    # 게이트 ②는 설계상 매칭을 유지·플래그만 세워 L5가 재확인을 유도하게 하는데, 풀이가 진단에
    # 합류하면서 노이즈 전사가 우연히 카탈로그 패턴을 담으면 그 매칭이 가설 편입·+1 지지·−1 반박으로
    # *즉시 영속*되는 경로가 열렸다. 응답 플래그는 DB 쓰기를 되돌리지 못하므로 영속 계층은 미확인
    # 전사의 매칭을 확정 진단으로 취급하지 않는다(빈 매칭 = 중립 텍스트 턴과 동일·감쇠만). 응답의
    # 후보·`match_low_quality`·개입 결정은 종전 그대로(§3.3 "intervention은 여기서 안 바꾼다"·
    # acceptance ⑤ 준수).
    # 새 임계 0 — 기존 게이트 ②의 플래그를 소비할 뿐이다.
    # MISC-28: 게이트 ③(정정 귀속 불명)도 같은 집행 지점을 공유한다 — `verdict_withheld` 주석 참조.
    persisted_matches: list[MisconceptionMatch] = (
        [] if outcome.verdict_withheld else outcome.matches
    )
    active_hypotheses = await _apply_hypotheses(session, user.user_id, persisted_matches)
    # S1-b: WH-1 하네스 *shadow 관측*(비노출·비블로킹·무영속). 플래그 ON일 때만 하네스를 병렬로
    # 돌려 '하네스가 어떤 도구를 골랐는지·verify 판정이 무엇인지'만 서버 로그로 남긴다 — 학생 응답은
    # 아래 결정론 경로(`_build_response_payload`) 그대로다(노출 불변). judge shadow의 `_spawn`
    # (fire-and-forget) 패턴 미러 — 응답 경로는 하네스 도구 루프(수 초)를 await하지 않는다. 플래그
    # OFF(기본)면 spawn 0·기존과 비트동일(완전 되돌리기 가능·04a '측정 없는 도입 없음').
    # S1-11 flip: primary(발화 승격)·shadow(비노출 관측) 플래그를 함께 읽는다 — primary on이면
    # 하네스가 *본류*에서 동기 실행·관측 emit까지 하므로 별도 shadow spawn은 하지 않는다(같은 턴
    # 이중 LLM 호출·중복 레코드 회피). 둘 다 off(기본)면 웜스타트·spawn 0 — 기존과 비트동일.
    wh1_primary_on = get_settings().wh1_primary_enabled
    wh1_shadow_on = get_settings().wh1_harness_shadow_enabled
    warmstart_mids: list[str] = []
    session_recall: SessionRecall | None = None
    if wh1_primary_on or wh1_shadow_on:
        # PED-04 D1 reader ②: 직전 세션의 교수 이력(메타 한정·복호 0). 하네스 게이트 *안*이라
        # 두 플래그가 모두 OFF면 쿼리 0(비용·회귀 0).
        session_recall = await _session_recall_or_none(
            session,
            user_id=user.user_id,
            active_hypotheses=active_hypotheses,
            exclude_dialogue_id=None,  # 아직 dialogue 미생성 — 제외할 대상 없음.
        )
        # S1-c: 웜스타트 probe 힌트 조립(진단 probe 타깃팅 전용·never-break·헬퍼 docstring 참조).
        warmstart_mids = await _warmstart_hints_or_empty(
            session,
            problem_id=body.problem_id,
            exclude_mids=(session_recall.unresolved_hypothesis_ids if session_recall else ()),
        )
    if wh1_shadow_on and not wh1_primary_on:
        _spawn(
            observe_wh1_harness_shadow(
                # 학생 원문·풀이 단계는 정책의 *사적 필드*로만 주입(S1-a·프롬프트·레코드 미노출).
                student_solution=body.student_solution or body.student_input,
                solution_steps=body.solution_steps or [],
                active_hypotheses=active_hypotheses,
                problem_id=str(body.problem_id) if body.problem_id is not None else None,
                # 웜스타트 outside_mids는 정책 사적 probe 컨텍스트로만(plan_probe 전용).
                warmstart_outside_mids=warmstart_mids,
                session_recall=session_recall,
                # REC-02 ②: session은 *의도적으로* 넘기지 않는다 — `_spawn`은 이 코루틴을
                # 요청 핸들러와 *동시에* 돈다(fire-and-forget create_task). AsyncSession은
                # 동시 사용이 안전하지 않아(SQLAlchemy 비동기 세션은 단일 실행 흐름 전제),
                # 살아있는 요청 세션을 여기 넘기면 핸들러의 나머지 쿼리와 경합한다. shadow는
                # 비노출 관측이라 이 턴의 probe_candidates가 비어도(session=None → skip)
                # 학생 응답에 영향 없다 — 변별력(⑤)은 동기 실행되는 primary 경로로 증명한다.
            )
        )
    pack = await _pack_for(session, body.problem_id)
    # PED-04 D2: 새 dialogue라 *이 대화의* 턴 이력은 없다 — 그래서 D2가 "클라 vs 서버" 로
    # 판정할 대상은 turn_count·prev_hint_level뿐이다. **current_stage는 다르다** — 새 세션의
    # 진입 단계는 서버가 역산할 대상이 아니라 클라가 고르는 *초기 조건*이다(예: 이해 단계를
    # 건너뛰고 PLAN에서 시작하는 정당한 진입). 그래서 클라 제출값을 그대로 받아들인다(오버라이드
    # 아님). turn_count는 새 대화이므로 항상 0(클라가 0이 아닌 값을 보내면 그 자체가 불일치
    # 신호). prev_hint_level은 *진짜* 서버 소유 데이터라 이 학생·이 문항의 직전 힌트 적재에서
    # 되찾는다(세션을 새로 열어도 답 미루기 사다리가 리셋되지 않게). 회전 이력
    # (`recent_categories`)은 정의상 비어 있다.
    server_prev_hint = await _prev_hint_level_for(
        session, user_id=user.user_id, problem_id=body.problem_id
    )
    server_state = PolyaState(
        current_stage=body.polya_state.current_stage,
        turn_count=0,
        prev_hint_level=server_prev_hint,
    )
    mismatch_fields = detect_state_mismatch(body.polya_state, server_state)
    if mismatch_fields:
        logger.info(
            "client_state_mismatch(세션 생성) fields=%s — 서버 파생값 우선", mismatch_fields
        )
    # PED-05: grade(user_profile 단건 — get_state() 전체 재계산 회피)·standard_code(문항 PRIMARY
    # 개념의 성취기준 고시코드) — 둘 다 비노출 개인화 슬롯(_grade_for/_standard_code_for docstring).
    grade = await _grade_for(session, user.user_id)
    standard_code = await _standard_code_for(session, body.problem_id)
    # S4-19: step_carry = 게이트 이전 단계 검증 운반값(아래 _log_verify_event 적재 전용·비노출).
    decision, matches, intervention, lthc, entry_category, step_carry, solution_coaching = (
        _build_response_payload(
            body,
            problem_id=body.problem_id,
            expected_answer=expected_answer,
            server_mastery=server_mastery,
            server_theta=server_theta,
            matches=outcome.matches,
            misconception_hypotheses=active_hypotheses,
            pack=pack,
            polya_state_override=server_state,
            grade=grade,
            standard_code=standard_code,
            step_chain_verifier=subject_capabilities.step_chain,
        )
    )
    intervention = _intervention_from_hypotheses_or(active_hypotheses, intervention)
    # S3-32 완료 상태머신 — 새 dialogue라 돌아보기 이력·완료 없음(prior=0·미완료). 이 턴 풀이의
    # 마지막 단계가 correct면 ENTER_REVIEW(돌아보기 대기·메타인지 프롬프트로 발화 override)·
    # incorrect면 REDIRECT(재고 유도)·그 외 no-op. 생성 턴에서 완료(COMPLETE)는 일어나지 않는다
    # (돌아보기 이력이 없어 prior=0 → ENTER만).
    completion = await _resolve_completion(
        session,
        user_id=user.user_id,
        problem_id=body.problem_id,
        prior_review_remaining=0,
        already_completed=False,
        redirect_turn_index=1,  # 새 dialogue — 첫 교환(재고 발화 변주 기준).
        body=body,
        decision=decision,
        capabilities=subject_capabilities,
        # PED-37: 이 턴에는 dialogue가 아직 없다(아래에서 생성) → 넘길 발생 시각이 없다. 위 주석대로
        # 생성 턴에서 COMPLETE는 나지 않으므로 실제로 적재에 쓰이지도 않는다. 서버 now를 대신
        # 넣지 않는 이유는 그것이 발생이 아니라 수신 시각이기 때문(§EOS-48-2 날조 금지).
        attempt_started_at=None,
    )
    decision = completion.decision
    # S1-11 flip(사인오프 2026-07-20): primary on이면 학생-대면 발화(decision.prompt·AI 턴
    # content)를 하네스 LLM 발화로 교체한다 — verify 의무·정답 억제·톤필터 통과분만, 실패 시
    # 결정론 폴백(헬퍼 docstring). 구조화 결정·가설·증거 파이프라인은 위 결정론 경로 그대로.
    # 완료 상태머신이 발화를 가로챘으면(handled·돌아보기/인정/재고) LLM flip을 건너뛴다 — 그 발화는
    # *결정론 메타인지/재고 템플릿*이라 LLM으로 재작성하지 않는다(정서안전·문구 고정).
    if wh1_primary_on and not completion.handled:
        decision = await _wh1_primary_decision_or(
            decision,
            body=body,
            active_hypotheses=active_hypotheses,
            warmstart_mids=warmstart_mids,
            provider=judge_deps.provider,
            turn_index=1,  # 새 dialogue — 첫 교환(§2.2 ε 카운터·아래 _wh1_turn_state와 정합).
            dialogue_id=None,  # dialogue는 아래에서 생성되므로 아직 id 없음(shadow 동형).
            problem_id=body.problem_id,
            session_recall=session_recall,
            # REC-02 ②: primary는 이 자리에서 *동기 await*라 session 동시사용 위험이 없다
            # (shadow의 _spawn과 달리 요청 핸들러가 이 호출이 끝날 때까지 다른 쿼리를 안 던진다).
            session=session,
            theta=server_theta,
            user_id=user.user_id,
            pack=pack,  # PED-23: decide에 넣은 같은 팩 재사용 — 러너의 금지모드 가드(옵트인).
        )

    now = datetime.now(timezone.utc)
    dialogue = DialogueORM.from_schema(
        DialogueSchema(
            user_id=user.user_id,
            problem_id=body.problem_id,
            started_at=now,
            total_turns=2,
            student_turns=1,
            assistant_turns=1,
            # S3-32: 정답 첫 도달이면 돌아보기 대기 상태를 세션에 심어 다음 턴 완료를 준비한다
            # (감지 안 됐으면 0=돌아보기 아님). 완료(COMPLETE)는 생성 턴에서 나지 않아 attempt 없음.
            review_turns_remaining=completion.review_turns_remaining_after,
        )
    )
    session.add(dialogue)
    await session.commit()
    await session.refresh(dialogue)
    # 방어: 생성 턴에서 완료가 났다면(이론상 미도달) attempt를 dialogue에 링크한다(재완료 가드).
    if completion.attempt_id is not None:
        dialogue.attempt_id = completion.attempt_id
        await session.commit()

    # 감사상환 #2: 대화 본문 봉투 암호화기(키 미설정 시 None=평문 폴백). 학생/AI 턴 2곳이 동일
    # 헬퍼(`_build_dialogue_turn`)로 content를 암호화 저장(중복 회피).
    content_cipher = require_dialogue_content_cipher(get_settings())
    # S3-03 mode 태깅 — 요청의 응용 모드/페르소나를 event_data에 실을 문자열로 정규화한다.
    # persona는 Persona enum이라 .value(문자열)로 싣는다(둘 다 None이면 미태깅·기존 동작 불변).
    event_persona = body.persona.value if body.persona is not None else None
    # WH-1 지표 ① 적재 — 풀이 제출(student_solution 비어있지 않음)이면 검산 결과를 attempt_event로
    # 기록(같은 트랜잭션 합류·별도 commit 없음). stateless /v1/coach는 미적재(DB 무접근 계약).
    # S3-03: body.mode·persona를 실어 수능 세션 검산결과를 측정 계층에서 식별 가능하게 한다.
    # **PED-04 재정렬**: 이 적재를 턴 생성 *앞*으로 옮겼다 — `student_understanding_signal`이
    # `verify_passed`를 축으로 쓰기 때문이다. 두 `session.add`는 같은 트랜잭션·FK 의존 0이라
    # 순서 교환이 의미상 무해하고, `_log_match_evidence`→`_log_refutation_evidence` 상대 순서
    # (curate 뒤·no-match 게이트)는 손대지 않았다.
    # S4-19: 게이트 이전 운반값(step_carry)으로 3상태 카운트를 병기 적재 — binary passed 불변.
    verify_passed = await _log_verify_event(
        session,
        user_id=user.user_id,
        problem_id=body.problem_id,
        attempt_id=dialogue.attempt_id,
        student_solution=body.student_solution,
        mode=body.mode,
        persona=event_persona,
        verification=step_carry.verification,
        verification_ocr_gated=step_carry.ocr_gated,
    )
    # WH-1 지표 ⑤ 적재 — 이미 계산된 decision.hint_level(supply·1~4)을 그대로 기록(재계산 0·
    # _build_response_payload 불변). verify 적재 바로 옆·같은 트랜잭션 합류(별도 commit 없음).
    # S3-03: verify와 동일 mode·persona 태그를 실어 ⑤⑧ mode-scoped 집계를 가능하게 한다.
    # PED-04 D2: 클라 제출 상태와의 불일치 여부를 이 이벤트에 태그로 실어 *영속 좌석*을 만든다
    # (신규 EventType·컬럼 0 — JSONB 페이로드 확장). 로그만 두면 집계가 불가능하다.
    await _log_hint_event(
        session,
        user_id=user.user_id,
        problem_id=body.problem_id,
        attempt_id=dialogue.attempt_id,
        hint_level=decision.hint_level,
        mode=body.mode,
        persona=event_persona,
        client_state_mismatch=bool(mismatch_fields),
    )
    # PED-04 D1: 교수 결정 메타 조립 — 전부 위에서 *이미 계산된* 값이다(재계산 0).
    target_stage = (
        next_polya_stage(server_state.current_stage)
        if decision.polya_stage_to_advance == "next"
        else server_state.current_stage
    )
    targeted_step = stage_to_targeted_step(target_stage)
    student_turn = _build_dialogue_turn(
        DialogueTurnSchema(
            dialogue_id=dialogue.dialogue_id,
            turn_order=1,
            spoken_at=now,
            role=TurnRole.student,
            content=body.student_input,
            content_type=ContentType.텍스트,
        ),
        content_cipher,
        TurnMeta(
            targeted_step=targeted_step,
            student_intent=classify_student_intent(
                student_input=body.student_input,
                has_solution=bool((body.student_solution or "").strip()),
            ),
            student_understanding_signal=compose_understanding_signal(
                mastery=(server_mastery if server_mastery is not None else body.bkt_mastery),
                verify_passed=verify_passed,
                stuck_turns=server_state.turn_count,
            ),
        ),
    )
    assistant_turn = _build_dialogue_turn(
        DialogueTurnSchema(
            dialogue_id=dialogue.dialogue_id,
            turn_order=2,
            spoken_at=now,
            role=TurnRole.assistant,
            content=decision.prompt,
            content_type=ContentType.텍스트,
        ),
        content_cipher,
        TurnMeta(
            socratic_strategy=resolve_socratic_strategy(
                intervention=intervention,
                reveals=decision.reveals,
                target_stage=target_stage,
            ),
            targeted_step=targeted_step,
        ),
    )
    session.add_all([student_turn, assistant_turn])
    # S3-16 소생 — 행동 텔레메트리 생산자 좌석(§3 D4). 답 요구(demand)·5회+ 막힘 신호는
    # 신호가 실제 있을 때만 1행 적재(날조 회피). 응답 지연(답입력)은 새 dialogue의 첫 턴이라
    # 이전 턴 기준선이 없어 여기서는 호출하지 않는다(append_turns 전용).
    await _log_demand_event(
        session,
        user_id=user.user_id,
        problem_id=body.problem_id,
        attempt_id=dialogue.attempt_id,
        student_input=body.student_input,
        event_at=now,
        mode=body.mode,
        persona=event_persona,
    )
    await _log_stuck_event(
        session,
        user_id=user.user_id,
        problem_id=body.problem_id,
        attempt_id=dialogue.attempt_id,
        turn_count=body.polya_state.turn_count,
        event_at=now,
        mode=body.mode,
        persona=event_persona,
    )
    # WH-1 §2.3 — 이번 턴 확정 매치를 +1 지지 증거로 적재(#268 소비측의 짝·생산측 좌석). curate
    # *뒤*에 둬 이번 턴 지지가 같은 턴 반박을 순환 차단 안 함(미래 net_support 반영). 같은 트랜잭션.
    # MISC-17/MISC-28: 미확인 전사(low_quality)·귀속 불명(attribution_unclear)은 +1 지지도 −1
    # 반박도 생산하지 않는다 — 빈 매칭만 넘기면 반박 헬퍼가 no-match 게이트를 통과해 clean
    # 검산으로 −1을 쓰므로 반박은 호출 자체를 보류한다.
    await _log_match_evidence(
        session,
        session_id=dialogue.dialogue_id,
        student_id=user.user_id,
        matches=persisted_matches,
    )
    # WH-1 §2.3 짝 — clean 검증 풀이(no-match)면 현재 active 가설을 약하게 −1 반박(낙인 방지·#268
    # archived 가드 라이브 발동). +1 생산 뒤·no-match 게이트로 한 턴은 지지/반박 중 하나(상호배타).
    if not outcome.verdict_withheld:
        await _log_refutation_evidence(
            session,
            session_id=dialogue.dialogue_id,
            student_id=user.user_id,
            passed=verify_passed,
            matches=persisted_matches,
            active_hypotheses=active_hypotheses,
            solution_text=body.student_solution,
        )
    await session.commit()

    # WH-1 멀티턴 연속성 — 새 dialogue라 직전 total_turns=0 → 첫 교환은 턴 1(§2.2 ε 카운터).
    wh1_turn_index, wh1_exploration = _wh1_turn_state(0)
    return SessionCreateResponse(
        decision=decision,
        misconceptions=matches,
        intervention=intervention,
        lthc=lthc,
        entry_socratic_category=entry_category,
        solution_coaching=solution_coaching,
        prerequisite_coaching=prereq,
        match_low_quality=outcome.low_quality,
        match_attribution_unclear=outcome.attribution_unclear,
        no_confident_match=outcome.no_confident_match,
        active_hypotheses=active_hypotheses,
        dialogue_id=dialogue.dialogue_id,
        student_turn_id=student_turn.turn_id,
        assistant_turn_id=assistant_turn.turn_id,
        wh1_turn_index=wh1_turn_index,
        wh1_exploration_turn=wh1_exploration,
        client_state_mismatch=bool(mismatch_fields),
        problem_complete=completion.problem_complete,
        answer_form=completion.answer_form,
        awaiting_reflection=completion.awaiting_reflection,
        completed_attempt_id=completion.attempt_id,
    )


@router.post(
    "/coach/sessions/{dialogue_id}/turns",
    response_model=TurnAppendResponse,
    status_code=status.HTTP_201_CREATED,
    summary="L4 코치 세션에 학생/AI 2턴 추가",
    dependencies=[RateLimitedTripleWrite],
)
async def append_turns(
    dialogue_id: uuid.UUID,
    body: CoachRequest,
    user: ConsentedUser,
    session: SessionDep,
    judge_deps: JudgeSeamDeps,
    segmentation_counters: SegmentationCountersDep,
    subject_capabilities: SubjectCapabilityDeps,
) -> TurnAppendResponse:
    """기존 dialogue에 학생/AI 2턴 추가.

    소유권 검증: `dialogue.user_id != user.user_id`거나 dialogue 부재 시 **404**
    (존재 노출 회피 — 타인 데이터 존재 여부 자체를 숨김; 403 분리는 정보 누출).
    `turn_order`는 `dialogue.total_turns` 기반으로 계산(max 쿼리 회피·증분 정합).
    AI 턴 content는 WH-1 primary 발화(기본 ON) — 실패·플래그 OFF 폴백 시 `decision.prompt`
    (slice 7 정합).
    """
    # NLP-03 acceptance ③ — 클라가 실어 보낸 solution_steps의 0-전이(<=1) 비율 관측.
    segmentation_counters.record(body.solution_steps)
    dialogue = await session.get(DialogueORM, dialogue_id)
    if dialogue is None or dialogue.user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="대화를 찾을 수 없습니다."
        )

    # PED-04 D1·D2: **이번 턴을 적재하기 전에** 직전 턴들의 평문 메타를 읽는다(순서가 계약 —
    # `_turn_meta_rows` docstring 참조). 여기서 Polya 상태를 서버가 파생하고, 발문 회전용
    # 카테고리 꼬리 연속열을 복원한다. 클라 제출값은 참고로만 두고 불일치를 표면화한다.
    meta_rows = await _turn_meta_rows(session, dialogue_id)
    server_prev_hint = await _prev_hint_level_for(
        session, user_id=user.user_id, problem_id=dialogue.problem_id
    )
    server_state = derive_polya_state(meta_rows, prev_hint_level=server_prev_hint)
    recent_categories = derive_recent_categories(meta_rows)
    mismatch_fields = detect_state_mismatch(body.polya_state, server_state)
    if mismatch_fields:
        # 침묵 실패 금지 — 무엇이 어긋났는지·양쪽 값(enum/int·PII 아님)을 구조화해 남긴다.
        logger.info(
            "client_state_mismatch(턴 추가) fields=%s client=%s server=%s — 서버 파생값 우선",
            mismatch_fields,
            body.polya_state.model_dump(mode="json", exclude={"history"}),
            server_state.model_dump(mode="json", exclude={"history"}),
        )

    # slice 64: 멀티턴 경로도 문항 맥락 주입 — dialogue에 이미 실린 problem_id로 기대정답 조회
    # (비노출 진단 로그 전용). create_session과 동형(create는 body, append는 dialogue 출처).
    expected_answer = await _expected_answer_for(session, dialogue.problem_id)
    # slice 70: 멀티턴도 서버 L2 숙달도 조회(dialogue.problem_id·user 출처)·클라 bkt 대체.
    server_mastery = await _server_mastery_for(session, user.user_id, dialogue.problem_id)
    # slice 73·74: 멀티턴도 서버 L2 θ 조회 — BKT↔θ 교차검증(θ 수치 비노출). slice 74: 개념별 θ
    # 우선(dialogue.problem_id)·없으면 전과목 폴백.
    server_theta = await _server_theta_for(session, user.user_id, dialogue.problem_id)
    # 선수 복습 코칭 — dialogue에 실린 problem_id로 막힌 선수 조회(create_session과 동형·dialogue
    # 출처). 별개 추가 신호(non-override·턴 비가로채기).
    prereq = await _prerequisite_coaching_for(session, user.user_id, dialogue.problem_id)
    # slice 106: 오개념 후보를 비블로킹 결합(게이트 off면 substring만)으로 미리 계산해 주입.
    # WH-1: ocr_confidence를 게이트로 thread하고(§3.3 게이트 ②), 게이트 플래그를 응답에 노출한다.
    # MISC-17: 진단 입력도 WH-1 primary와 같은 관용구 — 사진(OCR) 제출 턴(student_input=''
    # + student_solution 채움)의 풀이가 후보·가설·증거 적재에 합류한다. student_solution이
    # None/''이면 `or` 폴백으로 종전 텍스트 턴과 비트동일(회귀 0). 이어붙이기·새 게이트 없음.
    outcome = await _compute_matches(
        body.student_solution or body.student_input,
        ocr_confidence=body.ocr_confidence,
        judge_deps=judge_deps,
    )
    # WH-1 2단계 §8.4 슬라이스 3 — create_session과 동형. 이번 턴 매칭으로 *기존* 활성 가설
    # 세트를 큐레이션(감쇠/강화·누적·증거 반박·캡)·영속한다(트랜잭션 합류·별도 commit 없음·재사용).
    # 멀티턴이라 직전 턴들의 가설 위에 누적되어 감쇠·강화가 실제로 가동된다(2단계 메커니즘).
    # 결정 *앞에서* 적용한다 — 누적 가설 세트를 _build_response_payload로 넘겨 소크라테스 카테고리
    # (ASSUMPTION 가정 표면화)까지 구동(개입 채널과 동일한 post-apply 세트·단일 진실원천).
    # MISC-17/MISC-28: create_session과 동형 — 게이트 ②·③이면 영속 계층에 빈 매칭(주석은 위 참조).
    persisted_matches: list[MisconceptionMatch] = (
        [] if outcome.verdict_withheld else outcome.matches
    )
    active_hypotheses = await _apply_hypotheses(session, user.user_id, persisted_matches)
    # S1-11(flip-없는 수렴 잔여): 멀티턴에도 WH-1 shadow 관측 배선 — create_session(위 :1191)과
    # 동형. verdict가 실제 발생하는 곳은 멀티턴(풀이 단계 제출)이라, 여기 배선이 없으면 shadow
    # verdict 분포(S1-11 primary 승격 판정의 근거·live_cost 문서 §verdict 분포)가 구조적으로
    # 빈약하다. 플래그 OFF(기본)면 spawn 0·기존과 비트동일 — 학생 응답은 결정론 경로 그대로
    # (노출 불변·비블로킹 _spawn·무영속·04a '측정 없는 도입 없음' 준수). problem_id만 출처가
    # 다르다(create=body·append=dialogue — expected_answer 조회와 동일한 출처 규약).
    # S1-11 flip: create_session과 동형 — primary on이면 shadow spawn 생략(이중 호출 회피)·
    # 둘 다 off(기본)면 웜스타트·spawn 0(기존과 비트동일). problem_id 출처만 dialogue(멀티턴 규약).
    wh1_primary_on = get_settings().wh1_primary_enabled
    wh1_shadow_on = get_settings().wh1_harness_shadow_enabled
    warmstart_mids_turn: list[str] = []
    session_recall: SessionRecall | None = None
    if wh1_primary_on or wh1_shadow_on:
        # PED-04 D1 reader ②: *직전* 세션(현 dialogue 제외)의 교수 이력 — 메타 한정·복호 0.
        session_recall = await _session_recall_or_none(
            session,
            user_id=user.user_id,
            active_hypotheses=active_hypotheses,
            exclude_dialogue_id=dialogue_id,
        )
        warmstart_mids_turn = await _warmstart_hints_or_empty(
            session,
            problem_id=dialogue.problem_id,
            exclude_mids=(session_recall.unresolved_hypothesis_ids if session_recall else ()),
        )
    if wh1_shadow_on and not wh1_primary_on:
        _spawn(
            observe_wh1_harness_shadow(
                student_solution=body.student_solution or body.student_input,
                solution_steps=body.solution_steps or [],
                active_hypotheses=active_hypotheses,
                # 멀티턴 관측 메타 — dialogue_id로 세션 내 verdict 추이를, turn_index로 턴별
                # 분포를 묶을 수 있게 한다(레코드 스키마 기존 필드·PII 아님·UUID·정수).
                dialogue_id=str(dialogue_id),
                turn_index=(dialogue.total_turns or 0) // 2 + 1,
                problem_id=str(dialogue.problem_id) if dialogue.problem_id is not None else None,
                warmstart_outside_mids=warmstart_mids_turn,
                session_recall=session_recall,
                # REC-02 ②: create_session과 동형 이유로 session 미전달(_spawn 동시성·주석 참조).
            )
        )
    pack = await _pack_for(session, dialogue.problem_id)
    # PED-05: create_session과 동형 — grade는 user_profile 단건, standard_code는 dialogue에 실린
    # problem_id 출처(append 규약과 정합·expected_answer/server_mastery와 같은 출처 패턴).
    grade = await _grade_for(session, user.user_id)
    standard_code = await _standard_code_for(session, dialogue.problem_id)
    # S4-19: create_session과 동형 — step_carry(게이트 이전 운반값)는 verify 적재 전용·비노출.
    decision, matches, intervention, lthc, entry_category, step_carry, solution_coaching = (
        _build_response_payload(
            body,
            problem_id=dialogue.problem_id,
            expected_answer=expected_answer,
            server_mastery=server_mastery,
            server_theta=server_theta,
            matches=outcome.matches,
            misconception_hypotheses=active_hypotheses,
            pack=pack,
            polya_state_override=server_state,
            recent_categories=recent_categories,
            grade=grade,
            standard_code=standard_code,
            step_chain_verifier=subject_capabilities.step_chain,
        )
    )
    intervention = _intervention_from_hypotheses_or(active_hypotheses, intervention)
    # S3-32 완료 상태머신 — dialogue에 저장된 직전 돌아보기 상태(review_turns_remaining)와 완료
    # 여부(attempt_id 존재)를 읽어 이 턴을 판정한다:
    #   ① 돌아보기 대기 중(prior>0)이면 이 턴은 학생 근거 응답 → 완료 확정(attempt 적재·인정 발화).
    #   ② 돌아보기 전(prior=0)·미완료면 이 턴 마지막 단계 correct 시 돌아보기 진입(메타인지 발화)·
    #      incorrect 시 재고 유도(REDIRECT).
    #   ③ 미검증·이미 완료면 no-op(기존 코칭 그대로). 완료는 *풀이 제출을 통해서만* 일어난다.
    completion = await _resolve_completion(
        session,
        user_id=user.user_id,
        problem_id=dialogue.problem_id,
        prior_review_remaining=dialogue.review_turns_remaining,
        already_completed=dialogue.attempt_id is not None,
        redirect_turn_index=(dialogue.total_turns or 0) // 2 + 1,
        body=body,
        decision=decision,
        capabilities=subject_capabilities,
        # PED-37: 완료 시 적재할 attempt의 발생 시작 시각 = 이 대화가 시작된 시각. 학생이 문항
        # 풀이에 착수한 시점이라 발생 시각끼리의 이관이고(추정 아님), 완료가 나는 유일한 경로가
        # 여기다. dialogue.started_at이 비어 있으면 그대로 None(NULL=미측정).
        attempt_started_at=dialogue.started_at,
    )
    decision = completion.decision
    # 완료 상태머신이 계산한 남은 돌아보기 턴 수를 세션에 먼저 반영한다(다음 턴 상태). 완료 시
    # 적재된 attempt를 dialogue에 링크한다 — 완료 판정·재완료 가드가 attempt_id 존재로 작동한다
    # (이후 턴은 already_completed=True → no-op). 이하 verify/hint 이벤트가 완료 attempt에
    # 귀속되게 먼저 설정한다(이 턴이 곧 완료 확정 턴이면 이 턴의 이벤트가 새 attempt를 가리킨다).
    dialogue.review_turns_remaining = completion.review_turns_remaining_after
    if completion.attempt_id is not None:
        dialogue.attempt_id = completion.attempt_id
    # S1-11 flip: create_session과 동형 — 학생-대면 발화만 하네스 LLM 발화로 교체(검증 게이트·
    # 톤필터 통과분·실패 시 결정론 폴백). 멀티턴 메타(dialogue_id·turn_index)는 shadow와 동일 규약.
    # 완료 상태머신이 발화를 가로챘으면(돌아보기/인정/재고) LLM flip을 건너뛴다(결정론 템플릿 고정).
    if wh1_primary_on and not completion.handled:
        decision = await _wh1_primary_decision_or(
            decision,
            body=body,
            active_hypotheses=active_hypotheses,
            warmstart_mids=warmstart_mids_turn,
            provider=judge_deps.provider,
            turn_index=(dialogue.total_turns or 0) // 2 + 1,
            dialogue_id=str(dialogue_id),
            problem_id=dialogue.problem_id,
            session_recall=session_recall,
            # REC-02 ②: create_session과 동형 — 동기 await라 session 동시사용 위험 없음.
            session=session,
            theta=server_theta,
            user_id=user.user_id,
            pack=pack,  # PED-23: create_session과 동형 — decide와 같은 팩을 가드에 재사용.
        )

    current_total = dialogue.total_turns or 0
    student_order = current_total + 1
    assistant_order = current_total + 2

    now = datetime.now(timezone.utc)
    # 감사상환 #2: create_session과 동형 — 본문 봉투 암호화기·동일 헬퍼로 학생/AI 턴 저장.
    content_cipher = require_dialogue_content_cipher(get_settings())
    # S3-03 mode 태깅 — 멀티턴은 클라가 매 턴 같은 mode/persona를 실어 보낸다(dialogue 컬럼 대신
    # 요청 재사용·least-invasive·zero-migration). body가 CoachRequest라 두 값을 그대로 가진다.
    event_persona = body.persona.value if body.persona is not None else None
    # WH-1 지표 ① 적재 — create_session과 동형(풀이 제출 턴만·같은 트랜잭션 합류). problem_id·
    # attempt_id는 dialogue에서 출처(append는 dialogue 컨텍스트).
    # S3-03: body.mode·persona를 실어 수능 세션 후속 턴의 검산결과도 측정 계층에서 식별 가능.
    # PED-04 재정렬: create_session과 동형 — 이해도 신호가 verify 판정을 축으로 쓰므로 턴 생성
    # *앞*에서 계산한다(같은 트랜잭션·FK 의존 0·증거 적재 상대 순서 불변).
    # S4-19: create_session과 동형 — 게이트 이전 운반값으로 3상태 병기(binary passed 불변).
    verify_passed = await _log_verify_event(
        session,
        user_id=user.user_id,
        problem_id=dialogue.problem_id,
        attempt_id=dialogue.attempt_id,
        student_solution=body.student_solution,
        mode=body.mode,
        persona=event_persona,
        verification=step_carry.verification,
        verification_ocr_gated=step_carry.ocr_gated,
    )
    # WH-1 지표 ⑤ 적재 — create_session과 동형(이미 계산된 decision.hint_level·supply 1~4을 그대로
    # 기록·재계산 0·_build_response_payload 불변). verify 적재 바로 옆·같은 트랜잭션 합류(별도
    # commit 없음). problem_id·attempt_id는 dialogue 출처(append는 dialogue 컨텍스트).
    # S3-03: verify와 동일 mode·persona 태그를 실어 후속 턴의 ⑤⑧ 집계도 mode-scoped 가능.
    # PED-04 D2: 클라 제출 상태 불일치 태그(영속 좌석·신규 EventType 0).
    await _log_hint_event(
        session,
        user_id=user.user_id,
        problem_id=dialogue.problem_id,
        attempt_id=dialogue.attempt_id,
        hint_level=decision.hint_level,
        mode=body.mode,
        persona=event_persona,
        client_state_mismatch=bool(mismatch_fields),
    )
    # PED-04 D1: 교수 결정 메타 — create_session과 동형. 목표 단계는 *서버 파생* 상태 기준이다
    # (클라 제출 기준이면 D2가 되찾은 진실원천이 다시 클라로 새어 나간다).
    target_stage = (
        next_polya_stage(server_state.current_stage)
        if decision.polya_stage_to_advance == "next"
        else server_state.current_stage
    )
    targeted_step = stage_to_targeted_step(target_stage)
    student_turn = _build_dialogue_turn(
        DialogueTurnSchema(
            dialogue_id=dialogue_id,
            turn_order=student_order,
            spoken_at=now,
            role=TurnRole.student,
            content=body.student_input,
            content_type=ContentType.텍스트,
        ),
        content_cipher,
        TurnMeta(
            targeted_step=targeted_step,
            student_intent=classify_student_intent(
                student_input=body.student_input,
                has_solution=bool((body.student_solution or "").strip()),
            ),
            student_understanding_signal=compose_understanding_signal(
                mastery=(server_mastery if server_mastery is not None else body.bkt_mastery),
                verify_passed=verify_passed,
                stuck_turns=server_state.turn_count,
            ),
        ),
    )
    assistant_turn = _build_dialogue_turn(
        DialogueTurnSchema(
            dialogue_id=dialogue_id,
            turn_order=assistant_order,
            spoken_at=now,
            role=TurnRole.assistant,
            content=decision.prompt,
            content_type=ContentType.텍스트,
        ),
        content_cipher,
        TurnMeta(
            socratic_strategy=resolve_socratic_strategy(
                intervention=intervention,
                reveals=decision.reveals,
                target_stage=target_stage,
            ),
            targeted_step=targeted_step,
        ),
    )
    session.add_all([student_turn, assistant_turn])

    # dialogue 카운트 증가 — 다음 append의 `total_turns` 입력.
    dialogue.total_turns = current_total + 2
    dialogue.student_turns = (dialogue.student_turns or 0) + 1
    dialogue.assistant_turns = (dialogue.assistant_turns or 0) + 1
    # S3-16 소생 — create_session과 동형(§3 D4). 답 요구(demand)·5회+ 막힘 신호는 있을 때만
    # 1행 적재(날조 회피). problem_id·attempt_id는 dialogue 출처(append는 dialogue 컨텍스트).
    await _log_demand_event(
        session,
        user_id=user.user_id,
        problem_id=dialogue.problem_id,
        attempt_id=dialogue.attempt_id,
        student_input=body.student_input,
        event_at=now,
        mode=body.mode,
        persona=event_persona,
    )
    await _log_stuck_event(
        session,
        user_id=user.user_id,
        problem_id=dialogue.problem_id,
        attempt_id=dialogue.attempt_id,
        turn_count=body.polya_state.turn_count,
        event_at=now,
        mode=body.mode,
        persona=event_persona,
    )
    # S3-16 소생 — 응답 지연(답입력)은 *멀티턴 전용*(create_session은 첫 턴이라 기준선 없음).
    # 직전 학생 턴(server spoken_at)과 이번 제출(now)의 차를 서버 시각으로만 계산(조작 불가).
    await _log_response_latency_event(
        session,
        user_id=user.user_id,
        problem_id=dialogue.problem_id,
        attempt_id=dialogue.attempt_id,
        dialogue_id=dialogue_id,
        now=now,
        student_order=student_order,
        mode=body.mode,
        persona=event_persona,
    )
    # WH-1 §2.3 — create_session과 동형. 이번 턴 확정 매치를 +1 지지 증거로 적재(생산측·curate 뒤).
    # MISC-17/MISC-28: create_session과 동형 — 게이트 ②·③이면 +1·−1 모두 보류.
    await _log_match_evidence(
        session,
        session_id=dialogue_id,
        student_id=user.user_id,
        matches=persisted_matches,
    )
    # WH-1 §2.3 짝 — create_session과 동형. clean 풀이(no-match)면 active 가설 약한 −1 반박.
    if not outcome.verdict_withheld:
        await _log_refutation_evidence(
            session,
            session_id=dialogue_id,
            student_id=user.user_id,
            passed=verify_passed,
            matches=persisted_matches,
            active_hypotheses=active_hypotheses,
            solution_text=body.student_solution,
        )
    await session.commit()

    # WH-1 멀티턴 연속성 — 이번 교환 *전* total_turns(current_total)에서 누적 턴 번호 유도(§2.2).
    wh1_turn_index, wh1_exploration = _wh1_turn_state(current_total)
    return TurnAppendResponse(
        decision=decision,
        misconceptions=matches,
        intervention=intervention,
        lthc=lthc,
        entry_socratic_category=entry_category,
        solution_coaching=solution_coaching,
        prerequisite_coaching=prereq,
        match_low_quality=outcome.low_quality,
        match_attribution_unclear=outcome.attribution_unclear,
        no_confident_match=outcome.no_confident_match,
        active_hypotheses=active_hypotheses,
        student_turn_id=student_turn.turn_id,
        assistant_turn_id=assistant_turn.turn_id,
        student_turn_order=student_order,
        assistant_turn_order=assistant_order,
        wh1_turn_index=wh1_turn_index,
        wh1_exploration_turn=wh1_exploration,
        client_state_mismatch=bool(mismatch_fields),
        problem_complete=completion.problem_complete,
        answer_form=completion.answer_form,
        awaiting_reflection=completion.awaiting_reflection,
        completed_attempt_id=completion.attempt_id,
    )


@router.get(
    "/coach/sessions/{dialogue_id}",
    response_model=SessionGetResponse,
    summary="L4 코치 세션 조회(dialogue 메타 + 턴 목록)",
    dependencies=[RateLimitedTripleRead],
)
async def get_session_detail(
    dialogue_id: uuid.UUID,
    user: ConsentedUser,
    session: SessionDep,
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> SessionGetResponse | Response:
    """세션 메타 + 정렬된 턴 목록 반환. 소유권 검증은 slice 8 패턴(404·존재 노출 회피).

    `turn_order` 오름차순으로 학생/AI/system 모든 턴을 그대로 반환 — content는 학생 PII
    가능(이미 본인 소유 확정·`ConsentedUser` 게이트 통과 후). 페이지네이션 없음(한 세션의
    턴은 소량 가정·필요 시 후속).

    조건부 GET(RFC 7232): 응답에 ETag를 싣고, `If-None-Match`가 현재 ETag와 일치하면
    **304 Not Modified**(빈 본문)로 응답해 모바일 대역폭을 아낀다. ETag는 *dialogue +
    turns 전체 표현*의 해시라 턴 1개 추가만으로도 ETag가 바뀐다(slice 8 append 후 캐시
    무효화 자동).
    """
    dialogue = await session.get(DialogueORM, dialogue_id)
    if dialogue is None or dialogue.user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="대화를 찾을 수 없습니다."
        )

    stmt = (
        select(DialogueTurnORM)
        .where(DialogueTurnORM.dialogue_id == dialogue_id)
        .order_by(DialogueTurnORM.turn_order)
    )
    result = await session.execute(stmt)
    # 감사상환 #2: 암호화 행은 content=NULL·content_encrypted에 저장 — 노출 직전 복호한다.
    # to_schema는 ciphertext 컬럼을 제외하므로 복호값을 schema.content에 덮어쓴다(키 유실 시
    # resolve_dialogue_content가 RuntimeError·조용한 평문 유출/빈 응답 금지).
    content_cipher = require_dialogue_content_cipher(get_settings())
    turns = []
    for row in result.scalars().all():
        turn_schema = row.to_schema()
        turn_schema.content = resolve_dialogue_content(
            content_cipher, row.content, row.content_encrypted, row.content_nonce
        )
        # SEC-01: 멀티모달 두 축도 같은 시점에 복호한다 — 암호화해 놓고 읽는 쪽을 빠뜨리면
        # 학생에게 빈 값이 보이고(조용한 손실) 그것이 암호화 때문인지 알 수 없다.
        turn_schema.image_uri = resolve_dialogue_image_uri(
            content_cipher, row.image_uri, row.image_uri_encrypted, row.image_uri_nonce
        )
        turn_schema.image_analysis = resolve_dialogue_image_analysis(
            content_cipher,
            row.image_analysis,
            row.image_analysis_encrypted,
            row.image_analysis_nonce,
        )
        turns.append(turn_schema)
    payload = SessionGetResponse(dialogue=dialogue.to_schema(), turns=turns)
    etag = etag_for(payload)
    if matches_if_none_match(if_none_match, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return payload
