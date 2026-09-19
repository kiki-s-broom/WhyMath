"""Schema v1.0 도메인6 학습 진단(Assessment) 모델 (Pydantic) — 슬라이스 6.

설계 정본: `schemas/v1.0/schema_v1.0.md` §8.1(`assessment`·`concept_mastery_history`
DDL 2테이블). 초기 진단 + 주기적 재진단의 종합 결과(추정 등급·점수·백분위·합격 예측)와
단원별 숙련도 변화 시계열을 담는 도메인(특성 #14/#15/#29/#45/#50/#78/#86).

Phase 메모: 코드베이스 전체가 *Pydantic-schema-only*(DB 미배포) — 이 슬라이스도 순수
Pydantic 모델이다. SQLAlchemy/alembic 매핑은 후속 Phase(슬라이스 1~5 동일 패턴).

컨벤션(`problem.py`·`concept.py`·`user.py`·`activity.py` 답습):
  - `ConfigDict(extra="forbid", use_enum_values=True, str_strip_whitespace=True)`.
  - enum은 `enums.py`의 `class X(str, Enum)`(AssessmentType·MentalPhase 신규).
  - 공유 베이스 클래스 없음(각 모델 독립).

타입 매핑 판단(DDL → Pydantic, 슬라이스 1~5 선례 그대로):
  - `UUID PK` → `uuid.UUID = Field(default_factory=uuid4)`
  - `UUID`(복합 PK 구성요소) → required `uuid.UUID`(slice4 `UserPersonaHistory`·slice5
    `AttemptEvent` PK 선례)
  - nullable `UUID`(FK) → `uuid.UUID | None`(예: user_id, target_university_id)
  - `INTEGER` → `int | None`(ge/le)
  - `DECIMAL(p,s)` → `float | None`(ge/le); 범위는 DDL 인라인 주석을 따르고, 미명시는
    의미에 맞는 보수값을 골라 각 필드 description에 1줄로 명시(슬라이스 1~5 방식)
  - `TIMESTAMPTZ` → `datetime | None`; `TIMESTAMPTZ`(복합 PK 구성요소) → required `datetime`
    (예: concept_mastery_history.measured_at)
  - `enum` → `Enum | None`
  - `JSONB` 배열 → `list[dict[str, Any]]`(default_factory=list)
  - `TEXT` → `str | None`

개인정보 메모(CLAUDE.md 절대 금기·개인정보보호법, `user.py`·`activity.py` 방침과 동일):
  `assessment`는 *미성년 학생 진단 데이터*(추정 등급·약점·합격 예측 등)다. CLAUDE.md
  절대 금기("미성년자 개인정보를 분석·마케팅 외부 공유 금지"·"학교·학년 정보로 개인 식별
  가능한 분석 결과 외부 노출 금지")는 *저장·노출 계층* 책임이다 — 권한 게이팅(PIPA 데이터
  권한 매트릭스)·암호화 저장은 인프라/미들웨어가 시행한다. 모델 필드는 그 사실을 *상기*
  시키되 cross-field 강제(가짜 validator)를 두지 않는다(슬라이스 1~2가 `source_type`/
  `license`라는 *구조 신호*로 강제 가능했던 것과 달리, 여기엔 강제할 구조 신호가 없다 —
  `user.py`/`activity.py`/`concept.py` 법적 메모와 같은 방침: 문서화만).

  또한 이 도메인에는 자기관계(self-relation) 같은 구조 cross-field 불변식이 없다. 진단
  점수 간 정합(예: estimated_score↔estimated_percentile, weak/strong_points 일관성 등)은
  추정·집계 산출물이라 항상 성립한다 보장이 없어 모델 불변식으로 강제하지 않는다
  (`concept.py`/`activity.py` 방침 — 없는 게 맞다).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.schema.enums import (
    AssessmentType,
    MentalPhase,
)

# ──────────────────────────────────────────────────────────────────────────
# 핵심: Assessment (§8.1 assessment — 초기 진단 + 주기적 재진단, 17필드)
# ──────────────────────────────────────────────────────────────────────────
#: ASM-02 결정으로 **학생에게 노출하지 않는** 예측 필드 (ASM-07 집행).
#: 이 집합은 거버넌스 테스트·`ARCH-27` 봉인 스캔이 함께 읽는 단일 진실 원천이다 —
#: 이름을 여기서만 바꾸면 검사도 따라온다.
STUDENT_HIDDEN_PREDICTION_FIELDS: frozenset[str] = frozenset(
    {
        "estimated_grade",
        "estimated_score",
        "estimated_percentile",
        "target_university_id",
        "admission_probability",
    }
)


class StudentAssessment(BaseModel):
    """진단 평가 — **학생 대면 응답 정본**(ASM-02 결정 (c)의 구조적 집행 · ASM-07).

    `Assessment`(내부·영속 정본)에서 예측 5필드(`STUDENT_HIDDEN_PREDICTION_FIELDS`)를
    **뺀 것이 아니라**, 이쪽이 기반이고 `Assessment`가 그 5필드를 *더한다*. 방향이
    중요하다 — 나중에 누가 `Assessment`에 새 예측 필드를 붙여도 학생 응답에는
    자동으로 새지 않는다(허용목록이지 차단목록이 아니다).

    **왜 런타임 필터가 아닌가**: `response_model_exclude`·`exclude_none` 같은 필터는
    데코레이터 인자 한 줄이 빠지면 조용히 무력화되고 스키마에는 필드가 남아 OpenAPI
    광고도 계속된다. 필터는 꺼질 수 있으나 *필드의 부재*는 꺼지지 않는다
    (`PED-08` acceptance ③ 선례).

    **사고 경위**: 2026-08-08 실측 전까지 `GET /v1/me/assessments`가 `Assessment`를
    그대로 `response_model`로 써서, 값이 비어 있을 뿐 `"admission_probability": null`이
    학생 응답 JSON에 키째로 나가고 OpenAPI에도 광고되고 있었다.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    @classmethod
    def from_assessment(cls, assessment: Assessment) -> StudentAssessment:
        """내부 정본 → 학생 대면 정본. 예측 필드는 애초에 대상 모델에 자리가 없다."""
        return cls.model_validate(
            assessment.model_dump(exclude=set(STUDENT_HIDDEN_PREDICTION_FIELDS))
        )

    # ===== 기본 식별 =====
    assessment_id: uuid.UUID = Field(
        default_factory=uuid4,
        description="진단 PK (UUID)",
    )
    user_id: uuid.UUID | None = Field(
        default=None,
        description="학생 FK (user_profile 참조)",
    )
    assessment_type: AssessmentType | None = Field(
        default=None,
        description="진단 유형 — 초기진단/주간진단/단원진단/실전모의고사/D-100예측",
    )

    # ===== 시간 =====
    started_at: datetime | None = Field(default=None, description="진단 시작 시각")
    completed_at: datetime | None = Field(default=None, description="진단 완료 시각")

    # ===== 단원·패턴별 진단 =====
    concept_diagnosis: list[dict[str, Any]] = Field(
        default_factory=list,
        description='단원(개념)별 진단 [{"concept_id":"...","mastery":0.7,"trend":"+0.1"}, '
        "...](JSONB 배열)",
    )
    pattern_diagnosis: list[dict[str, Any]] = Field(
        default_factory=list,
        description="시그니처 패턴별 진단(JSONB 배열)",
    )
    weak_points: list[dict[str, Any]] = Field(
        default_factory=list,
        description="약점 단원/개념 TOP 5(JSONB 배열) — 단원명만이 아니라 점수·추세 상세를 "
        "담을 수 있어 list[dict]로 둔다(list[str] 대신).",
    )
    strong_points: list[dict[str, Any]] = Field(
        default_factory=list,
        description="강점 단원/개념(JSONB 배열) — weak_points와 동일 사유로 list[dict].",
    )

    # ===== 권장 학습 경로 (특성 #78) =====
    recommended_path: list[dict[str, Any]] = Field(
        default_factory=list,
        description='권장 학습 경로 [{"week":1,"concept":"...","estimated_hours":5}, ...]'
        "(JSONB 배열)",
    )

    # ===== 멘탈·시간 관리 (특성 #50) =====
    mental_phase: MentalPhase | None = Field(
        default=None,
        description="입시 멘탈 단계 — D_100_PLUS/D_100_50/D_50_30/D_30_7/D_7_0/평상시 "
        "(D-100 코칭)",
    )

    # ===== 메모 =====
    notes: str | None = Field(default=None, description="진단 코멘트(자유 서술)")


class Assessment(StudentAssessment):
    """진단 평가 — §8.1 `assessment`. 초기 진단·주간/단원 진단·실전 모의고사·D-100 예측의
    종합 결과를 담는 도메인6 핵심 모델(특성 #14/#15/#29/#45/#50/#78/#86).

    **내부·영속 정본**이다. 학생 대면 응답에는 이 모델을 쓰지 않는다 — `StudentAssessment`
    를 쓴다(ASM-02 결정 (c) · ASM-07). 보호자·교사 노출 형태는 Phase 3 미결이다.

    PK `assessment_id`만 있고 나머지는 모두 nullable/기본값(DDL 그대로). 진단 시작 직후
    결과가 아직 비어 있는 *진행 중* 레코드도 표현할 수 있어야 하기 때문이다.

    5개 진단 결과 필드(`concept_diagnosis`·`pattern_diagnosis`·`weak_points`·
    `strong_points`·`recommended_path`)는 모두 *컬렉션*이라 `list[dict[str, Any]]`로 둔다.
    weak/strong_points는 코드 배열(`list[str]`)로도 모델링 가능하나, 약점 단원명만이 아니라
    개념 점수·추세 등 상세를 담을 수 있도록 `list[dict[str, Any]]`로 둔다(JSONB 자유형).

    개인정보 메모(모듈 docstring 참조): 이 모델은 *미성년 학생 진단 데이터*(추정 등급·
    약점·합격 예측)다. CLAUDE.md 절대 금기(미성년 개인정보 분석·외부 공유 금지·개인 식별
    분석 결과 외부 노출 금지)는 *저장·노출 계층*(PIPA 권한 매트릭스·암호화·미들웨어) 책임
    이며, 이 모델 필드는 그 사실을 *상기*시키되 가짜 validator를 두지 않는다(문서화만 —
    `user.py`/`activity.py`/`concept.py` 방침과 동일). 여기엔 강제할 구조 신호가 없다.
    """

    model_config = ConfigDict(
        # 추가 필드 금지 — Pydantic 모델이 스키마의 단일 진실
        extra="forbid",
        # 직렬화 시 enum 값을 그대로(한글 값 보존: assessment_type="단원진단" 등)
        use_enum_values=True,
        # 문자열 양끝 공백 제거
        str_strip_whitespace=True,
    )

    # ===== 종합 결과 (특성 #14, #15, #45) =====
    estimated_grade: float | None = Field(
        default=None,
        description="추정 등급 1-9 (DDL 'DECIMAL(3,2)' → 등급 척도이므로 `user.py` "
        "estimated_grade 선례를 따라 ge=1 le=9 설정).",
        ge=1.0,
        le=9.0,
    )
    estimated_score: int | None = Field(
        default=None,
        description="추정 표준점수. DDL에 범위 미명시 → 점수라 음수 불가 ge=0만 설정.",
        ge=0,
    )
    estimated_percentile: float | None = Field(
        default=None,
        description="추정 백분위 0-100 (DDL 'DECIMAL(5,2)' → 백분위 척도이므로 ge=0 le=100, "
        "`user.py` estimated_percentile 선례).",
        ge=0.0,
        le=100.0,
    )

    # ===== 합격 예측 (특성 #86) =====
    target_university_id: uuid.UUID | None = Field(
        default=None,
        description="합격 예측 대상 대학 FK",
    )
    admission_probability: float | None = Field(
        default=None,
        description="합격 확률 0-1 (DDL 주석 '0-1' → ge=0 le=1, DECIMAL(3,2)).",
        ge=0.0,
        le=1.0,
    )


# ──────────────────────────────────────────────────────────────────────────
# 핵심: ConceptMasteryHistory (§8.1 concept_mastery_history — 숙련도 변화 시계열)
# ──────────────────────────────────────────────────────────────────────────
class ConceptMasteryHistory(BaseModel):
    """단원별 숙련도 변화 추적 — §8.1 `concept_mastery_history`(특성 #16 학습 곡선).

    복합 PK `(user_id, concept_id, measured_at)` — DB 제약. PK 구성요소는 NOT NULL이므로
    `user_id`·`concept_id`·`measured_at` 셋 다 required로 둔다(슬라이스 4
    `UserPersonaHistory`·슬라이스 5 `AttemptEvent`가 PK 구성요소를 모두 required로 둔 선례
    답습).

    운영 시 `concept_mastery_history`는 TimescaleDB hypertable로 변환되어 `measured_at`
    기준 7일 청크로 분할된다(런타임/DB 레벨; 단일 모델 레벨에서는 표현하지 않음 —
    `AttemptEvent` 선례).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    # ===== 복합 PK (user_id, concept_id, measured_at) =====
    user_id: uuid.UUID = Field(..., description="학생 FK (복합 PK 구성요소)")
    concept_id: uuid.UUID = Field(..., description="개념 FK (복합 PK 구성요소)")
    measured_at: datetime = Field(
        ...,
        description="숙련도 측정 시각 (복합 PK 구성요소·hypertable 7일 청크 분할 키)",
    )

    # ===== 측정값 =====
    mastery: float | None = Field(
        default=None,
        description="숙련도 0-1 (DDL 주석 '0-1' → ge=0 le=1, DECIMAL(3,2)).",
        ge=0.0,
        le=1.0,
    )
    confidence: float | None = Field(
        default=None,
        description="측정 신뢰도. DDL 'DECIMAL(3,2)' → 정규화 신뢰도로 보아 ge=0 le=1 설정 "
        "(`user.py` persona_confidence 선례).",
        ge=0.0,
        le=1.0,
    )
    sample_size: int | None = Field(
        default=None,
        description="이 측정의 근거가 된 문제 수. DDL에 범위 미명시 → 개수라 음수 불가 ge=0만 "
        "설정.",
        ge=0,
    )

    attempt_id: uuid.UUID | None = Field(
        default=None,
        description="이 측정을 낳은 시도(`problem_attempt.attempt_id`)의 **멱등 키**. 같은 시도가 "
        "두 번 반영되는 것을 DB 부분 유니크 인덱스가 막는다(EOS-108). `None`은 시도에서 유래하지 "
        "않은 측정(배치·백필)이며 그 측정은 멱등 보호를 받지 않는다 — 가짜 UUID로 채우면 서로 "
        "다른 관측이 같은 시도인 척하게 되므로 `None`을 그대로 둔다. FK는 걸지 않는다(느슨참조 "
        "선례 + 보존기한 파기로 attempt가 사라져도 학습 곡선은 남아야 한다).",
    )


# ──────────────────────────────────────────────────────────────────────────
# 핵심: SkillMasteryHistory (skill_mastery_history — 스킬 숙달 변화 시계열·Part 2 Phase 2b-2)
# ──────────────────────────────────────────────────────────────────────────
class SkillMasteryHistory(BaseModel):
    """스킬별 숙달 변화 추적 — `skill_mastery_history`(Part 2 리치 채택 Phase 2b-2).

    `ConceptMasteryHistory`의 *스킬 축* 짝이다 — 개념(무엇)과 직교하는 *행동*(어떻게) 숙달을
    시계열로 적재한다. 채점 attempt가 평가하는 개념을 concept→skill 브리지(`Concept.behavior_skills`
    ∩ mastery-estimable `skill_node`)로 해소한 각 스킬에 대해 BKT/IRT 순수 커널을 *그대로 재사용*
    (엔티티-무관)해 갱신한다.

    복합 PK `(user_id, skill_id, measured_at)` — DB 제약. **개념과의 유일한 차이**: 개념은
    `concept_id`(UUID)지만 스킬은 `skill_id`(**TEXT**·`skill.<slug>`·`skill_node` PK 공간)다.
    `user_id`·`skill_id`는 §느슨참조라 *FK 아님*(hypertable·ConceptMasteryHistory 선례). 운영 시
    `measured_at` 7일 청크 hypertable로 변환(마이그레이션 레벨·모델 미표현).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    # ===== 복합 PK (user_id, skill_id, measured_at) =====
    user_id: uuid.UUID = Field(..., description="학생 FK (복합 PK 구성요소)")
    skill_id: str = Field(
        ...,
        description="스킬 id(`skill.<slug>`·skill_node PK 공간·복합 PK 구성요소·느슨참조).",
        max_length=200,
    )
    measured_at: datetime = Field(
        ...,
        description="스킬 숙달 측정 시각 (복합 PK 구성요소·hypertable 7일 청크 분할 키)",
    )

    # ===== 측정값 (ConceptMasteryHistory 동형·Numeric(3,2)/Int) =====
    mastery: float | None = Field(
        default=None,
        description="스킬 숙달도 0-1 (DECIMAL(3,2)·ge=0 le=1).",
        ge=0.0,
        le=1.0,
    )
    confidence: float | None = Field(
        default=None,
        description="측정 신뢰도 (DECIMAL(3,2)·표본 기반 휴리스틱·ge=0 le=1).",
        ge=0.0,
        le=1.0,
    )
    sample_size: int | None = Field(
        default=None,
        description="이 측정의 근거가 된 관측(문제) 수 (개수·ge=0).",
        ge=0,
    )

    attempt_id: uuid.UUID | None = Field(
        default=None,
        description="이 측정을 낳은 시도(`problem_attempt.attempt_id`)의 **멱등 키**. 같은 시도가 "
        "두 번 반영되는 것을 DB 부분 유니크 인덱스가 막는다(EOS-108). `None`은 시도에서 유래하지 "
        "않은 측정(배치·백필)이며 그 측정은 멱등 보호를 받지 않는다 — 가짜 UUID로 채우면 서로 "
        "다른 관측이 같은 시도인 척하게 되므로 `None`을 그대로 둔다. FK는 걸지 않는다(느슨참조 "
        "선례 + 보존기한 파기로 attempt가 사라져도 학습 곡선은 남아야 한다).",
    )


class AbilitySnapshot(BaseModel):
    """IRT 능력 θ 시계열 적재 — slice 31(`ability_snapshot`). 성장 곡선 영속.

    `concept_mastery_history`(BKT 숙달 시계열)와 *상보적* — 이쪽은 IRT 능력 θ(logit)를 시점별로
    저장한다. 파생 계산(slice 28 `/me/ability/history`)과 달리 *적재형*(캡처 시점 보존·재계산
    불요). `concept_id`가 null이면 전 과목 단일 θ, 값이 있으면 개념별 θ(후속). 미성년 진단
    데이터(개인정보)는 저장·노출 계층 책임(assessment 모듈 docstring과 동일 방침).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    snapshot_id: uuid.UUID = Field(default_factory=uuid4, description="스냅샷 PK(surrogate·UUID4).")
    user_id: uuid.UUID = Field(..., description="학생 id(느슨참조·FK 아님).")
    concept_id: uuid.UUID | None = Field(
        default=None, description="개념 id. null이면 전 과목 단일 θ(개념별은 후속)."
    )
    theta: float = Field(..., description="IRT 능력 θ(logit). 이 시점 추정값.")
    standard_error: float | None = Field(
        default=None, description="θ 표준오차 SE. 측정 불가면 null.", ge=0.0
    )
    response_count: int = Field(..., description="이 추정에 쓰인 채점 풀이 수.", ge=0)
    measured_at: datetime | None = Field(
        default=None,
        description="측정(캡처) 시각. None이면 DB server_default now() 사용(insert 시각).",
    )
