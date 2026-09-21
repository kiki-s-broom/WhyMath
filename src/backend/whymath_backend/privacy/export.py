"""개인정보 열람·이동권 — 인증된 *본인*의 학습/진단 데이터를 구조화 JSON으로 모아 반환.

설계 정본: `docs/architecture/04a_wh1_tutoring_harness.md` §2.3 개인정보 설계 원칙(R11). 삭제권
(`erasure.erase_user`·#242)·보존 파기(`retention`·#253/#254)의 *짝*인 **열람·이동권**(GDPR
data access·portability)이다. 삭제권이 이미 *어떤 테이블이 사용자 PII인지* 열거(`_ERASURE_PLAN`)
하므로, 그 인벤토리의 *학습/진단 subset*을 **읽기**로 재사용해 본인 데이터를 한데 모은다.

범위(plan-driven 확장): `_EXPORT_PLAN`의 학습/진단 19종(학습 세션·시도·진단·개념 숙달 이력·능력
스냅샷·동의·트랙/페르소나/상태 이력·오개념 가설·진단 증거·일별 학습 지표·행동 지표 시계열·대화
세션 메타 + **세부 시도 이벤트** + **답 제출 시퀀스**(EOS-32 `answer_submission` — 본인 제출
원문·채점·오류 분석) + **힌트 사용 이력**(EOS-45 `hint_usage` — 레벨·시각·열람시간) +
**풀이 step 이력**(EOS-46 `student_solution_step` — 단계 본문·검증·개념 태그)) +
**대화 턴 본문**(`dialogue_turns`·조인) + `user_profile` 단건.
**보안 항목 영구 제외**: `device_credential`·`refresh_token_session`(로그인 토큰·기기 자격 — 노출은
보안 위험·"개인 학습 데이터" 아님). 손글씨 이미지 원본 파일(외부 저장소·URI만 포함)·외부 store
실조회·비동기 job은 후속 — 미포함을 *조용히 넘기지 않고* `not_included`로 정직히 드러낸다(날조 0).
오개념 가설·증거는 *식별자·신호·날짜*만 담고 자유텍스트 PII가 없어(증거 그래프 설계 04a
§2.3) 본인 export에 그대로 안전(redaction 0). 증분 4 시계열 2종도 *식별자·지표·날짜*만이라 동일
안전 — `UserBehaviorMetrics`의 churn_risk 등 추론 행동분석치도 본인 열람·이동권(Art.15)엔 포함하되
(기존 θ·오개념 가설 등 추론치 포함과 일관) `ProblemSolveTimeDistribution`은 `problem_id` 교차집계라
개인 PII가 아니므로 제외한다(영구). **증분 5**: `Dialogue`(대화 세션 메타·자유텍스트 0)를 포함.
**증분 6**: 자식 `DialogueTurn`(채팅 본문·손글씨)을 `Dialogue` 조인으로 결선 — *전체 본문 포함*
(사용자 결정·GDPR Art.15 열람권·본인 인증 게이트·제3자 공유 아님). 채팅 본문·동의는 *저장 계층*
(암호화·미들웨어) 책임이며 이 읽기 경로는 인증된 본인에게만 본인 데이터를 돌려준다. **증분 7**:
`AttemptEvent`(세부 시도 이벤트)를 동기 export로 포함(Phase1·완전성 우선) — 매우 큰 이력은 후속
스트리밍으로 최적화 가능.

외부 store(Redis 캐시·큐 · Langfuse 트레이스 SaaS)는 RDB 밖이라 이 export(PostgreSQL)에 *포함되지
않는다* — `external_export_pending`으로 *구조화*해 ops가 가시화한다(#252 `external_erasure_targets`
미러·정보 누출 방지로 student-facing 응답엔 인프라 store명/locator 미노출·ops 로그만).
그 매니페스트에 적히는 store는 **실재하는 것만**이다(SEC-32 — 미도입 ClickHouse·S3 제거·
실 반출처 Langfuse 등재. 근거 대조는 `tests/backend/_external_store_evidence.py` 계약).

저장소 패턴: `AsyncSession` 주입·**읽기 전용**(commit 0·flush 0·`select`만·원시 SQL 0). per-user
본인 데이터라 HTTP 노출이 맞다("전역 집계는 ops CLI" 제약은 *전역*에만 — 이건 본인 1명).

**ASM-12 예외(2026-08-11)**: 위 "추론치 포함" 방침에서 **성적 예측 5필드**(`STUDENT_HIDDEN_
PREDICTION_FIELDS` — 추정 등급·점수·백분위·대상 대학·합격 확률)만은 제외한다. 이 필드들은
ASM-02/07이 학생 대면 전 표면에서 봉인한 것이고 이 export도 학생 토큰이 받는 학생 표면이다
(θ·오개념 가설 등 *학습 진단* 추론치와 달리, 또래 비교·서열 산출물이라 `pipa_data_matrix`
§2.2 #8이 학생 본인조차 요약만으로 제한). 열람권과의 충돌 판정·뒤집힘 조건은
`docs/legal/export_prediction_disclosure_verdict.md`(변호사 게이트 유보) — 제외는
`not_included`로 고지한다(침묵 금지).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.base import Base
from whymath_backend.db.models.activity import AttemptEvent, LearningSession, ProblemAttempt
from whymath_backend.db.models.answer_submission import AnswerSubmission
from whymath_backend.db.models.assessment import (
    AbilitySnapshot,
    Assessment,
    ConceptMasteryHistory,
    SkillMasteryHistory,
)
from whymath_backend.db.models.dialogue import Dialogue, DialogueTurn
from whymath_backend.db.models.evidence_link import EvidenceLink
from whymath_backend.db.models.hint_usage import HintUsage
from whymath_backend.db.models.misconception_hypothesis import MisconceptionHypothesisRecord
from whymath_backend.db.models.parental_consent import ParentalConsent
from whymath_backend.db.models.student_solution_step import StudentSolutionStep
from whymath_backend.db.models.timeseries import DailyLearningMetrics, UserBehaviorMetrics
from whymath_backend.db.models.user import (
    UserPersonaHistory,
    UserProfile,
    UserStateSnapshot,
    UserTrackHistory,
)
from whymath_backend.schema.activity import ProblemAttempt as SchemaProblemAttempt
from whymath_backend.schema.answer_submission import AnswerSubmission as SchemaAnswerSubmission
from whymath_backend.schema.student_solution_step import (
    StudentSolutionStep as SchemaStudentSolutionStep,
)

__all__ = [
    "ExternalDataLocation",
    "UserDataExport",
    "export_user_data",
    "external_export_pending",
]

# export 계획 — (모델, user 컬럼명, 응답 카테고리 키). `_ERASURE_PLAN`(erasure.py)의 *`to_schema`
# 보유 subset*이다. 보안 토큰(device_credential·refresh_token_session)만 영구 제외(노출=보안 위험).
# 대화 turn 본문(`DialogueTurn`)은 user_id 직접 키가 없어 아래 전용 조인 쿼리로 별도 결선.
# 오개념 가설·진단 증거는 `to_schema()` 부여로 포함(#269~272 라이브 적재·식별자/신호/날짜만
# PII-safe). **증분 4**: *바운드 per-user 시계열 2종*(일별 학습 지표·행동 지표)을 추가한다 —
# 둘 다 `user_id` PK·`to_schema()` 보유·이미 `_ERASURE_PLAN` PII 등재라 열람권↔삭제권 비대칭을
# 메운다. `ProblemSolveTimeDistribution`은 `problem_id` 키 *교차 사용자 집계*라 개인 PII가 아니므로
# 제외(영구). `UserBehaviorMetrics`의 churn_risk 등 *추론 행동분석*도 본인 열람·이동권(GDPR
# Art.15)엔 포함한다(기존 θ·오개념 가설 등 추론치 포함과 일관·식별자/지표/날짜만 PII-safe·
# 자유텍스트 0). **증분 5**: `Dialogue`(대화 *세션 메타*·`user_id` 키·`to_schema()` 보유·
# `_ERASURE_PLAN` 첫 타깃)를 추가한다. **증분 6**: 그 자식 `DialogueTurn`(채팅 본문·손글씨)을
# *user_id 직접 키가 없어* `_EXPORT_PLAN`이 아닌 전용 조인 쿼리(`Dialogue`로 조인·아래 함수)로
# 결선한다 — 사용자 결정(전체 본문 포함·GDPR Art.15)에 따라 `content`·`image_uri`·`image_analysis`
# 포함(본인 인증 게이트·제3자 공유 아님·기존 추론/진단 데이터 포함과 일관). 컬럼명은 모델별
# (evidence_links는 `student_id`·나머지는 `user_id`)이라 튜플 2번째로 파라미터화한다. 모든 모델은
# `to_schema()`를 보유한다(JSON-safe 직렬화). **증분 7**: `AttemptEvent`(세부 시도 이벤트·user_id
# 느슨참조 키·`to_schema()` 보유·`_ERASURE_PLAN` 등재)를 추가 — RDB 내 마지막 미포함 per-user PII.
# 동기 export(증분 4~6 패턴)로 결선(Phase1·실사용자 0). *매우 큰 이력*은 후속 스트리밍 export로
# 최적화할 수 있으나(메모리), 현재는 완전성 우선(열람권 PII 누락=비준수). event_data(JSONB)는
# 본인 이벤트 페이로드라 본인 export에 안전.
_EXPORT_PLAN: tuple[tuple[type[Base], str, str], ...] = (
    (LearningSession, "user_id", "learning_sessions"),
    (ProblemAttempt, "user_id", "problem_attempts"),
    (Assessment, "user_id", "assessments"),
    (ConceptMasteryHistory, "user_id", "concept_mastery_history"),
    (SkillMasteryHistory, "user_id", "skill_mastery_history"),  # 스킬 숙달·느슨참조·hypertable
    (AbilitySnapshot, "user_id", "ability_snapshots"),
    (ParentalConsent, "user_id", "parental_consents"),
    (UserTrackHistory, "user_id", "track_history"),
    (UserPersonaHistory, "user_id", "persona_history"),
    (UserStateSnapshot, "user_id", "state_snapshots"),
    (MisconceptionHypothesisRecord, "user_id", "misconception_hypotheses"),
    (EvidenceLink, "student_id", "misconception_evidence"),
    (DailyLearningMetrics, "user_id", "daily_learning_metrics"),  # 증분 4: 일별 학습 활동 집계
    (UserBehaviorMetrics, "user_id", "user_behavior_metrics"),  # 증분 4: 학습 행동 시계열
    (Dialogue, "user_id", "dialogues"),  # 증분 5: 대화 세션 메타(본문은 DialogueTurn·아래 조인)
    (AttemptEvent, "user_id", "attempt_events"),  # 증분 7: 세부 시도 이벤트(동기·Phase1)
    # EOS-32: 답 제출 시퀀스(본인 풀이 원문·채점·오류 분석 — 본인 열람권 Art.15에 그대로 안전.
    # 성적 예측 필드 0·자유텍스트는 본인 제출물 자체). user_id 직접 보유·to_schema() 보유.
    (AnswerSubmission, "user_id", "answer_submissions"),
    # EOS-45: 힌트 사용 이력(레벨·시각·열람시간 — 식별자/수치/날짜만·자유텍스트 0·PII-safe).
    (HintUsage, "user_id", "hint_usages"),
    # EOS-46: 학생 풀이 step(본인 제출 단계 본문·검증·개념 태그 — 본인 열람권 Art.15에 안전.
    # 자유텍스트는 본인 제출물 자체·성적 예측 필드 0). user_id 직접 보유·to_schema() 보유.
    (StudentSolutionStep, "user_id", "student_solution_steps"),
)

# 이 export에 *포함되지 않은* 범위 — student-facing 사용자 친화 설명(인프라 store명·키 미노출).
# 부분 export임을 정직히 알린다(GDPR 완전성·날조 0). 외부 store 상세는 ops 로그(아래 함수)로만.
_NOT_INCLUDED: tuple[str, ...] = (
    "손글씨 이미지 *원본 파일*은 외부 저장소(별도 시스템) 보관 — 본 export엔 참조 URI만 담긴다.",
    "LLM 응답 캐시·요청 처리 트레이스 등 외부 시스템 보관 데이터는 미포함(별도 시스템).",
    "보안 항목(로그인 토큰·기기 자격)은 보안상 내보내지 않는다.",
    # ASM-12 — 제외를 침묵하면 부분 export를 완전 export로 위장하게 된다(정직 고지).
    "성적 예측 추정치(추정 등급·점수·백분위·합격 예측)는 학습 보호 정책에 따라 미포함 — "
    "법률 검토 후 재판정된다.",
)


# ASM-12 — 학생 대면 직렬화 대체표. 내부 정본이 학생에게 노출하지 않는 예측 필드
# (`STUDENT_HIDDEN_PREDICTION_FIELDS`)를 가진 모델은 **허용목록 학생 대면 모델**(필드의
# 부재 — ASM-07 방식·런타임 필터 금지)로 직렬화한다. 이 export는 학생 본인 토큰
# (`ConsentedUser`)이 받는 두 번째 학생 표면이라 `/v1/me/assessments`와 같은 봉인 계약을
# 따른다. 열람권(PIPA §35·GDPR Art.15)과의 긴장은 미조정 충돌이 아니라 **판정된 잠정
# 기본값**이다 — 근거·뒤집힘 조건 = `docs/legal/export_prediction_disclosure_verdict.md`
# (변호사 게이트 `G-export-prediction-disclosure` 해소 시 재판정. 현재 예측 필드 writer
# 0건이라 실제로 제약되는 저장 데이터도 0건이다).
def _assessment_student_json(row: Any) -> dict[str, Any]:
    from whymath_backend.schema.assessment import StudentAssessment

    return StudentAssessment.from_assessment(row.to_schema()).model_dump(mode="json")


def _state_snapshot_student_json(row: Any) -> dict[str, Any]:
    from whymath_backend.schema.user import StudentStateSnapshot

    return StudentStateSnapshot.from_snapshot(row.to_schema()).model_dump(mode="json")


_STUDENT_FACING_SERIALIZERS: dict[type[Base], Any] = {
    Assessment: _assessment_student_json,
    UserStateSnapshot: _state_snapshot_student_json,
}


class ExternalDataLocation(BaseModel):
    """RDB *밖* store에 남은 본인 데이터 — 이 export(PG)에 *포함되지 않음*. ops용 구조화. 불변.

    `export_user_data`는 PostgreSQL만 읽는다. 외부 store(Redis 캐시·큐, Langfuse 트레이스
    SaaS)는 RDB 밖·별도 클라이언트/전송 인프라라 이 export에 *포함되지 않는다*. 이 모델은 그
    미포함을 *조용히 넘기지 않고*(날조 0·GDPR 범위 정직) ops가 인지·후속 export할 체크리스트로
    *구조화*한다. `locator`는 *정확한 키 문법을 단정하지 않는다* — 키/프리픽스 규약은 인프라
    정의라 user_id 연관 대상만 서술하고, **user 단위 조회가 불가능한 store는 그 사실 자체를
    적는다**(SEC-32 — 후속 export가 가능하다는 인상만 남기면 미포함 고지가 거짓이 된다).
    정보 누출 방지로 student-facing 응답엔 싣지 않는다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    store: str = Field(description="외부 store 식별자(redis·langfuse).")
    data: str = Field(description="그 store가 보유한 사용자 데이터 설명(한국어).")
    locator: str = Field(description="대상(user_id 연관·키 규약은 인프라 정의·단정 아님).")


def external_export_pending(user_id: uuid.UUID) -> tuple[ExternalDataLocation, ...]:
    """이 사용자에 대해 외부 store에 남아 *이 export에 포함되지 않은* 데이터 목록(per-user·구조화).

    `export_user_data`의 PostgreSQL 읽기 *밖*에 있는 store들을 명시한다 — export 범위를 정직히
    드러내(GDPR·날조 0) ops/후속 오케스트레이터가 인지·집행하게 한다. 순수 함수(외부 호출 0)·
    locator는 *키 문법을 단정하지 않고* user_id 연관 대상만 서술한다(인프라 키 규약 날조 금지).
    """
    uid = str(user_id)
    # 삭제권 매니페스트(`erasure.external_erasure_targets`)와 *같은 store 집합*을 본다 — 한쪽만
    # 고치면 "지울 곳"과 "못 담은 곳"이 어긋나 두 권리의 범위 고지가 서로 모순된다. ClickHouse·
    # S3를 뺀 사유와 Langfuse를 넣은 사유는 그쪽 주석이 정본이다(중복 서술 대신 단일 진실).
    return (
        ExternalDataLocation(
            store="redis",
            data=(
                "LLM 응답 캐시(학생 프롬프트로 생성된 응답 본문)·QUALITY 비동기 큐 payload"
                "(prompt·system 원문)."
            ),
            locator=(
                f"user_id={uid}의 요청에서 파생되나 *user_id로 조회할 키가 없다* — 캐시 키는 "
                "(프롬프트·시스템·티어) 해시라 본인 데이터만 골라 담을 수 없다."
            ),
        ),
        ExternalDataLocation(
            store="langfuse",
            data=(
                "L3 라우팅 결정 트레이스(`l3_routing` 이벤트) — 티어·모델·토큰·비용·지연 등 "
                "*결정 메타데이터*. 프롬프트·응답 본문은 전송하지 않는다."
            ),
            locator=(
                f"user_id={uid}의 요청에서 생성되나 학생 연결 축은 해시(`student_id_hash`) 하나"
                "뿐이고 현행 서빙 경로는 그마저 채우지 않는다(2026-09-07 실측) — user 단위 조회 "
                "불가."
            ),
        ),
    )


class UserDataExport(BaseModel):
    """열람·이동권 export 결과 — 본인 학습/진단 데이터 + 미포함 범위 고지(정직). 불변(frozen).

    `data`는 카테고리(`_EXPORT_PLAN` 키)→행 리스트(각 행은 `to_schema().model_dump(mode="json")`).
    `not_included`는 *이 export에 빠진 범위*를 사용자 친화로 알린다(부분 export 정직·완전성). 외부
    store 상세(인프라 store명·locator)는 *싣지 않는다*(정보 누출 방지·ops 로그로만).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: uuid.UUID = Field(description="데이터 주체(인증된 본인).")
    exported_at: datetime = Field(description="export 생성 시각(UTC).")
    user_profile: dict[str, Any] | None = Field(
        default=None, description="계정 프로필 단건(없으면 None)."
    )
    data: dict[str, list[dict[str, Any]]] = Field(
        description="카테고리→행 리스트(학습/진단 데이터·JSON-safe)."
    )
    not_included: tuple[str, ...] = Field(
        description="이 export에 미포함된 범위 고지(부분 export 정직·완전성)."
    )


# SEC-31: 학생 답안/풀이 3테이블(problem_attempt·answer_submission·student_solution_step)의
# 봉투 암호화 필드 복호 명세 — (schema/attr 이름, 평문 컬럼, 암호화 컬럼, nonce 컬럼, 종류).
# 종류: "text"(nullable str — resolve_dialogue_content 재사용)·"json"(nullable dict —
# resolve_dialogue_image_analysis 재사용)·"text_required"(student_solution_step.expression
# 전용 — schema는 필수 str이라 resolve_student_solution_step_expression으로 복호. 둘 다 없으면
# RuntimeError·조용한 빈 문자열 없음).
_StudentWorkFieldSpec = tuple[str, str, str, str, str]

_PROBLEM_ATTEMPT_ENCRYPTED_FIELDS: tuple[_StudentWorkFieldSpec, ...] = (
    (
        "student_answer",
        "student_answer",
        "student_answer_encrypted",
        "student_answer_nonce",
        "text",
    ),
    (
        "handwriting_uri",
        "handwriting_uri",
        "handwriting_uri_encrypted",
        "handwriting_uri_nonce",
        "text",
    ),
    ("ocr_result", "ocr_result", "ocr_result_encrypted", "ocr_result_nonce", "json"),
)
_ANSWER_SUBMISSION_ENCRYPTED_FIELDS: tuple[_StudentWorkFieldSpec, ...] = (
    ("raw_response", "raw_response", "raw_response_encrypted", "raw_response_nonce", "text"),
    ("latex", "latex", "latex_encrypted", "latex_nonce", "text"),
    ("canonical_ast", "canonical_ast", "canonical_ast_encrypted", "canonical_ast_nonce", "json"),
)
_STUDENT_SOLUTION_STEP_ENCRYPTED_FIELDS: tuple[_StudentWorkFieldSpec, ...] = (
    ("expression", "expression", "expression_encrypted", "expression_nonce", "text_required"),
    ("canonical_ast", "canonical_ast", "canonical_ast_encrypted", "canonical_ast_nonce", "json"),
)

# 모델 → (필드 명세, 대응 schema 클래스). `_row_to_json`(→`to_schema()`)을 그대로 못 쓰는 이유:
# `student_solution_step.expression`은 schema에서 필수 `str`인데, 암호화 행에서는 ORM 컬럼이
# NULL이라 `to_schema()`를 먼저 부르면 복호 적용 전에 ValidationError가 난다(SEC-31 마이그레이션
# 참조). 그래서 이 3모델은 "복호 → schema 검증" 순서를 지키는 전용 함수(`_student_work_row_json`)
# 로 내보낸다.
_StudentWorkModelSpec = tuple[tuple[_StudentWorkFieldSpec, ...], type[BaseModel]]
_STUDENT_WORK_MODELS: dict[type[Base], _StudentWorkModelSpec] = {
    ProblemAttempt: (_PROBLEM_ATTEMPT_ENCRYPTED_FIELDS, SchemaProblemAttempt),
    AnswerSubmission: (_ANSWER_SUBMISSION_ENCRYPTED_FIELDS, SchemaAnswerSubmission),
    StudentSolutionStep: (_STUDENT_SOLUTION_STEP_ENCRYPTED_FIELDS, SchemaStudentSolutionStep),
}


def _student_work_row_json(row: Any, cipher: Any) -> dict[str, Any]:
    """SEC-31: 학생 답안/풀이 3테이블 전용 — 복호를 *먼저* 적용한 뒤 schema로 재검증한 JSON.

    `_row_to_json`(→ `row.to_schema()`)을 그대로 쓰지 않는 이유는 모듈 상단 `_STUDENT_WORK_MODELS`
    주석 참조(student_solution_step.expression 필수 str 계약과의 순서 충돌). ciphertext 컬럼은
    필드 명세의 `encrypted_attr`/`nonce_attr` 집합으로 직접 제외한다(`_NON_SCHEMA_COLUMNS`
    속성에 의존하지 않아 이 함수가 자기 완결적이다). 복호 실패(cipher 미설정인데 암호화 행)는
    각 resolve 헬퍼가 RuntimeError로 노출한다(조용한 침묵 실패 금지 — CLAUDE.md).
    """
    from whymath_backend.api._crypto import (
        resolve_dialogue_content,
        resolve_dialogue_image_analysis,
        resolve_student_solution_step_expression,
    )

    model = type(row)
    specs, schema_cls = _STUDENT_WORK_MODELS[model]
    exclude = {name for spec in specs for name in (spec[2], spec[3])}
    mapped_keys = {
        col.key for col in sa.inspect(model).mapper.column_attrs if col.key not in exclude
    }
    data: dict[str, Any] = {key: getattr(row, key) for key in mapped_keys}
    for attr, plain_attr, encrypted_attr, nonce_attr, kind in specs:
        plain = getattr(row, plain_attr)
        encrypted = getattr(row, encrypted_attr)
        nonce = getattr(row, nonce_attr)
        if kind == "text":
            data[attr] = resolve_dialogue_content(cipher, plain, encrypted, nonce)
        elif kind == "json":
            data[attr] = resolve_dialogue_image_analysis(cipher, plain, encrypted, nonce)
        else:  # "text_required"
            data[attr] = resolve_student_solution_step_expression(cipher, plain, encrypted, nonce)
    return schema_cls.model_validate(data).model_dump(mode="json")


def _row_to_json(row: Any) -> dict[str, Any]:
    """ORM 행 → JSON-safe dict(`to_schema().model_dump(mode="json")`). `_EXPORT_PLAN` 모델 전제.

    `to_schema()`가 Pydantic 스키마로 검증 복원하므로 enum·UUID·datetime이 JSON 안전하게 직렬화된다.
    ASM-12: 예측 필드 보유 모델은 학생 대면 허용목록 모델로 대체 직렬화한다
    (`_STUDENT_FACING_SERIALIZERS` — 이 export는 학생 토큰이 받는 학생 표면이다).
    """
    serializer = _STUDENT_FACING_SERIALIZERS.get(type(row))
    if serializer is not None:
        return cast("dict[str, Any]", serializer(row))
    return cast("dict[str, Any]", row.to_schema().model_dump(mode="json"))


async def export_user_data(session: AsyncSession, *, user_id: uuid.UUID) -> UserDataExport:
    """본인의 학습/진단 데이터를 `_EXPORT_PLAN`대로 모아 구조화 export로 반환한다(읽기 전용).

    각 테이블을 `select(...).where(user컬럼 == user_id)`로 조회(PK 정렬·결정적)하고
    `to_schema().model_dump(mode="json")`로 직렬화한다. **증분 6**: `dialogue_turns`는 `user_id`
    직접 키가 없어(자식 테이블) `Dialogue`로 조인해 본인 턴만 조회한다(전체 본문 포함·사용자 결정).
    `user_profile`은 단건. **commit/flush 0**(읽기 전용·저장소 패턴). 외부 store는 포함하지 않고
    `external_export_pending`(ops)로 별도 고지. 멱등·부작용 0(같은 user는 같은 데이터·시각만 갱신).
    """
    # SEC-31: 학생 답안/풀이 3테이블 봉투 암호화 cipher — export 순회 전 1회 조립(감사상환 #2
    # content_cipher와 동일 위치·동일 이유: 함수-지역 import로 privacy → api 순환 회피). 이
    # cipher는 `_student_work_row_json`에 전달돼 3모델 각각의 복호에 재사용된다(요청당 1회
    # cipher 조립 — 행마다 조립하지 않음). 키 유실 시 조용한 평문 유출/빈 응답 대신 시끄러운
    # 실패(각 resolve 헬퍼가 RuntimeError).
    from whymath_backend.api._crypto import require_student_work_cipher
    from whymath_backend.config import get_settings

    student_work_cipher = require_student_work_cipher(get_settings())

    data: dict[str, list[dict[str, Any]]] = {}
    for model, column, category in _EXPORT_PLAN:
        result = await session.execute(
            select(model)
            .where(getattr(model, column) == user_id)
            .order_by(*model.__mapper__.primary_key)
        )
        rows = result.scalars().all()
        if model in _STUDENT_WORK_MODELS:
            data[category] = [_student_work_row_json(row, student_work_cipher) for row in rows]
        else:
            data[category] = [_row_to_json(row) for row in rows]

    # 대화 턴(채팅 본문·손글씨) — `dialogue_turn`엔 user_id가 없어 부모 `dialogue`로 조인해 본인
    # 턴만 조회. (dialogue_id, turn_order) 정렬로 대화별·시간순 결정적. 전체 본문 포함(증분 6).
    turn_result = await session.execute(
        select(DialogueTurn)
        .join(Dialogue, DialogueTurn.dialogue_id == Dialogue.dialogue_id)
        .where(Dialogue.user_id == user_id)
        .order_by(DialogueTurn.dialogue_id, DialogueTurn.turn_order)
    )
    # 감사상환 #2: content가 봉투 암호화됐으면 노출(본인 열람권) 직전 복호한다. cipher 빌더·복호
    # 헬퍼는 함수-지역 import — privacy → api 모듈 로드 순환(api.me → privacy) 회피(요청 시점
    # import이라 안전). `_row_to_json`은 ciphertext 컬럼을 제외(to_schema)하므로 export엔 평문만
    # 실린다. 키 유실 시 resolve가 RuntimeError(조용한 평문/빈 export 금지).
    from whymath_backend.api._crypto import (
        require_dialogue_content_cipher,
        resolve_dialogue_content,
        resolve_dialogue_image_analysis,
        resolve_dialogue_image_uri,
    )

    content_cipher = require_dialogue_content_cipher(get_settings())
    turn_dicts: list[dict[str, Any]] = []
    for row in turn_result.scalars().all():
        turn_json = _row_to_json(row)
        turn_json["content"] = resolve_dialogue_content(
            content_cipher, row.content, row.content_encrypted, row.content_nonce
        )
        # SEC-01: 손글씨 URI·분석도 암호화 대상이 됐으므로 열람권(GDPR Art.15) 경로에서 복호한다.
        # 복호를 빠뜨리면 export에 빈 값이 실려 *부분 export를 완전 export로 위장*하게 된다.
        turn_json["image_uri"] = resolve_dialogue_image_uri(
            content_cipher, row.image_uri, row.image_uri_encrypted, row.image_uri_nonce
        )
        turn_json["image_analysis"] = resolve_dialogue_image_analysis(
            content_cipher,
            row.image_analysis,
            row.image_analysis_encrypted,
            row.image_analysis_nonce,
        )
        turn_dicts.append(turn_json)
    data["dialogue_turns"] = turn_dicts

    profile_result = await session.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile_row = profile_result.scalars().first()
    user_profile = _row_to_json(profile_row) if profile_row is not None else None

    return UserDataExport(
        user_id=user_id,
        exported_at=datetime.now(UTC),
        user_profile=user_profile,
        data=data,
        not_included=_NOT_INCLUDED,
    )
