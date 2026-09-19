"""도메인6 학습 진단(Assessment) ORM 모델 (SQLAlchemy 2.0 영속 레이어).

설계 정본: `schemas/v1.0/schema_v1.0.md` §8.1(`assessment`·`concept_mastery_history` DDL
2테이블). 이 ORM은 `schema/assessment.py`(Pydantic, 검증·API)와 *별도*로 세운 영속 매핑이며
`from_schema`/`to_schema` 변환 헬퍼가 둘을 잇는다(배치1 `problem.py`·`user.py` 동일 패턴).

타입 매핑(DDL → ORM, problem.py/user.py 선례 그대로):
  - `UUID PRIMARY KEY` → `server_default gen_random_uuid()`(배치1 UUID PK 선례).
  - `UUID REFERENCES`(nullable FK) → `uuid.UUID|None` + FK(user_id→user_profile).
  - `UUID`(REFERENCES 없음) → `uuid.UUID|None`(*FK 아님* — `target_university_id`는 §8.1 DDL에
    REFERENCES 절이 없는 느슨참조. activity.target_concept_id 선례와 동형).
  - `UUID`(복합 PK 구성요소, REFERENCES 없음) → required `uuid.UUID` + `primary_key=True`
    (*FK 아님* — concept_mastery_history.user_id·concept_id. user.py UserPersonaHistory가 PK
    구성 FK를 *걸었던* 것과 달리, 여기는 §8.1 DDL이 REFERENCES를 명시하지 않은 hypertable
    느슨참조라 FK를 걸지 않는다).
  - `TIMESTAMPTZ`(복합 PK 구성요소) → required `datetime` + `primary_key=True`(measured_at).
  - `assessment_type_enum`/`mental_phase_enum` → `_pg_enum(...)`(신규 PG 타입).
  - `DECIMAL(p,s)` → `Mapped[float|None] = mapped_column(sa.Numeric(p, s))`(estimated_grade
    DECIMAL(3,2)·estimated_percentile DECIMAL(5,2)·admission_probability·mastery·confidence).
  - `INTEGER` → `int|None`(estimated_score·sample_size).
  - `JSONB`(5개 진단 결과: concept_diagnosis·pattern_diagnosis·weak_points·strong_points·
    recommended_path) → schema가 default_factory=list(NOT NULL 의미)라 problem.py
    conditions_parsed처럼 `nullable=False, server_default "'[]'::jsonb"`.
  - `TEXT`(notes) → `sa.Text`.
  - §8.1 DDL엔 별도 CREATE INDEX가 없으나, slice 61에서 `list_my_assessments` 접근 패턴용
    `idx_assessment_user(user_id, started_at DESC)`를 추가(다른 /me 도메인과 parity).

개인정보 메모(CLAUDE.md 절대 금기·개인정보보호법, `user.py`·`activity.py` 방침과 동일):
  `assessment`는 *미성년 학생 진단 데이터*(추정 등급·약점·합격 예측)다. 미성년 개인정보
  분석·외부 공유 금지·개인 식별 분석 결과 외부 노출 금지는 *저장·노출 계층*(PIPA 권한
  매트릭스·암호화·미들웨어) 책임이며, ORM에는 컬럼만 두고 가짜 CHECK를 만들지 않는다
  (schema.assessment 모듈 docstring·problem.py 방침과 동형 — 문서화만).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.db.models._orm_enum import _pg_enum
from whymath_backend.schema.assessment import (
    AbilitySnapshot as SchemaAbilitySnapshot,
)
from whymath_backend.schema.assessment import Assessment as SchemaAssessment
from whymath_backend.schema.assessment import (
    ConceptMasteryHistory as SchemaConceptMasteryHistory,
)
from whymath_backend.schema.assessment import (
    SkillMasteryHistory as SchemaSkillMasteryHistory,
)
from whymath_backend.schema.enums import (
    AssessmentType,
    MentalPhase,
)


# ──────────────────────────────────────────────────────────────────────────
# 핵심: Assessment (§8.1 assessment — 초기 진단 + 주기적 재진단)
# ──────────────────────────────────────────────────────────────────────────
class Assessment(Base):
    """진단 평가 영속 ORM — §8.1 `assessment`(특성 #14/#15/#29/#45/#50/#78/#86).

    PK `assessment_id`만 있고 나머지는 nullable/기본값(DDL 그대로). `user_id`→user_profile FK.
    `target_university_id`는 §8.1 DDL에 `REFERENCES`가 없어 *FK가 아니다*(느슨참조). 5개 진단
    결과(concept_diagnosis·pattern_diagnosis·weak_points·strong_points·recommended_path)는
    schema가 default_factory=list라 NOT NULL JSONB(server_default '[]')로 둔다.

    개인정보 메모(모듈 docstring 참조): *미성년 학생 진단 데이터*다. 저장·노출 계층(PIPA 권한
    매트릭스·암호화·미들웨어) 책임이라 ORM에는 컬럼만 두고 가짜 CHECK를 만들지 않는다.
    """

    __tablename__ = "assessment"

    # ===== 기본 식별 =====
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("user_profile.user_id")
    )
    assessment_type: Mapped[AssessmentType | None] = mapped_column(
        _pg_enum(AssessmentType, "assessment_type_enum")
    )

    # ===== 시간 =====
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    # ===== 종합 결과 (특성 #14/#15/#45) =====
    estimated_grade: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    estimated_score: Mapped[int | None] = mapped_column(sa.Integer)
    estimated_percentile: Mapped[float | None] = mapped_column(sa.Numeric(5, 2))

    # ===== 합격 예측 (특성 #86) =====
    # REFERENCES 없음 → FK 아님(느슨참조).
    target_university_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    admission_probability: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))

    # ===== 단원·패턴별 진단 (schema default_factory=list → NOT NULL JSONB) =====
    concept_diagnosis: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    pattern_diagnosis: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    weak_points: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    strong_points: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")
    )

    # ===== 권장 학습 경로 (특성 #78) =====
    recommended_path: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")
    )

    # ===== 멘탈·시간 관리 (특성 #50) =====
    mental_phase: Mapped[MentalPhase | None] = mapped_column(
        _pg_enum(MentalPhase, "mental_phase_enum")
    )

    # ===== 메모 =====
    notes: Mapped[str | None] = mapped_column(sa.Text)

    # slice 61: list_my_assessments(user_id 필터·started_at desc 정렬) 접근 패턴 인덱스 —
    # learning_session.idx_session_user·dialogue.idx_dialogue_user와 동형(parity).
    __table_args__ = (sa.Index("idx_assessment_user", "user_id", sa.desc("started_at")),)

    # ── 변환 헬퍼 (schema↔db seam, problem.py 패턴) ──────────────────────
    @classmethod
    def from_schema(cls, schema: SchemaAssessment) -> Assessment:
        """검증된 `schema.Assessment` → 영속 ORM(mapper 컬럼키 필터)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaAssessment:
        """영속 ORM → `schema.Assessment`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaAssessment.model_validate(data)


# ──────────────────────────────────────────────────────────────────────────
# 핵심: ConceptMasteryHistory (§8.1 concept_mastery_history — 숙련도 변화 시계열)
# ──────────────────────────────────────────────────────────────────────────
class ConceptMasteryHistory(Base):
    """단원별 숙련도 변화 추적 영속 ORM — §8.1 `concept_mastery_history`(특성 #16 학습 곡선).

    복합 PK `(user_id, concept_id, measured_at)` — DDL 제약. PK 구성요소는 NOT NULL이라 셋 다
    primary_key. `user_id`·`concept_id`는 §8.1 DDL에 `REFERENCES`가 없어 *FK가 아니다*
    (hypertable 느슨참조 — user.py UserPersonaHistory가 PK 구성 FK를 *걸었던* 것과 달리, 여기는
    DDL이 REFERENCES를 명시하지 않았다).

    운영 시 이 테이블은 TimescaleDB hypertable로 변환되나(`measured_at` 7일 청크), *그 변환은
    마이그레이션 레벨*이라 ORM에서는 일반 테이블로 둔다(hypertable 코드를 ORM에 넣지 않는다).
    """

    __tablename__ = "concept_mastery_history"

    # ===== 복합 PK (user_id, concept_id, measured_at) — REFERENCES 없음 → FK 아님 =====
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    concept_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    measured_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), primary_key=True)

    # ===== 측정값 =====
    mastery: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    confidence: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    sample_size: Mapped[int | None] = mapped_column(sa.Integer)

    # ===== 멱등 키 (EOS-108) =====
    # 이 측정을 낳은 시도. **FK 아님**(느슨참조 선례 + 보존기한 파기로 attempt가 사라져도
    # 학습 곡선은 남아야 한다). NULL 허용 = 시도에서 유래하지 않은 측정(배치·백필).
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)

    __table_args__ = (
        # 같은 시도가 같은 (학생, 개념)에 두 번 반영되는 것을 **DB가** 막는다. 애플리케이션
        # 사전 조회만으로는 동시 제출 두 건이 서로의 행을 못 보고 둘 다 통과한다(check-then-act
        # 경합) — 유니크 제약은 그 경합에서 정확히 한 건만 살린다.
        # 부분 인덱스인 이유: `attempt_id IS NULL`인 배치·백필 측정은 서로 충돌하면 안 된다
        # (PostgreSQL에서 NULL은 유니크 비교에서 서로 다르지만, 의도를 조건으로 명시해 둔다).
        sa.Index(
            "uq_concept_mastery_history_attempt",
            "user_id",
            "concept_id",
            "attempt_id",
            unique=True,
            postgresql_where=sa.text("attempt_id IS NOT NULL"),
        ),
    )

    @classmethod
    def from_schema(cls, schema: SchemaConceptMasteryHistory) -> ConceptMasteryHistory:
        """검증된 `schema.ConceptMasteryHistory` → 영속 ORM(schema↔db seam)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaConceptMasteryHistory:
        """영속 ORM → `schema.ConceptMasteryHistory`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaConceptMasteryHistory.model_validate(data)


class SkillMasteryHistory(Base):
    """스킬별 숙달 변화 추적 영속 ORM — `skill_mastery_history`(Part 2 리치 채택 Phase 2b-2).

    `ConceptMasteryHistory`의 *스킬 축* 짝(개념=무엇 ↔ 스킬=행동). 채점 attempt가 평가하는 개념을
    concept→skill 브리지로 해소한 각 스킬에 순수 커널(`compute_mastery_record`·엔티티-무관)을
    재사용해 갱신·append-only 적재한다(특성 #16 학습 곡선의 행동 축).

    복합 PK `(user_id, skill_id, measured_at)` — DDL 제약. **개념과의 유일 차이**: concept_id(UUID)
    대신 `skill_id`(**Text**·`skill.<slug>`·`skill_node` PK). `user_id`·`skill_id`는 §느슨참조라
    *FK 아님*(hypertable·ConceptMasteryHistory 선례 — DDL에 REFERENCES 없음). 운영 시 `measured_at`
    7일 청크 hypertable로 변환되나 *그 변환은 마이그레이션 레벨*이라 ORM은 일반 테이블로 둔다.
    """

    __tablename__ = "skill_mastery_history"

    # ===== 복합 PK (user_id, skill_id, measured_at) — REFERENCES 없음 → FK 아님 =====
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    skill_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    measured_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), primary_key=True)

    # ===== 측정값 (ConceptMasteryHistory 동형) =====
    mastery: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    confidence: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    sample_size: Mapped[int | None] = mapped_column(sa.Integer)

    # ===== 멱등 키 (EOS-108) — 개념 축 동형 =====
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)

    __table_args__ = (
        sa.Index(
            "uq_skill_mastery_history_attempt",
            "user_id",
            "skill_id",
            "attempt_id",
            unique=True,
            postgresql_where=sa.text("attempt_id IS NOT NULL"),
        ),
    )

    @classmethod
    def from_schema(cls, schema: SchemaSkillMasteryHistory) -> SkillMasteryHistory:
        """검증된 `schema.SkillMasteryHistory` → 영속 ORM(schema↔db seam)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaSkillMasteryHistory:
        """영속 ORM → `schema.SkillMasteryHistory`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaSkillMasteryHistory.model_validate(data)


class AbilitySnapshot(Base):
    """IRT 능력 θ 시계열 적재 ORM — slice 31(`ability_snapshot`). 성장 곡선 영속.

    `concept_mastery_history`(BKT 숙달 시계열)와 *상보적*: 이쪽은 IRT 능력 θ(logit)를 시점별로
    저장한다. surrogate PK `snapshot_id`(gen_random_uuid). `user_id`는 §느슨참조라 *FK 아님*
    (concept_mastery_history 선례). `concept_id` null=전 과목 단일 θ. `theta`·`standard_error`는
    실수(logit·SE)라 `Float`(Numeric 정밀도 제약 불요). `measured_at`은 server_default now()
    (캡처 시각 자동). 접근 패턴(본인 시계열·시간순)용 `idx_ability_snapshot_user`.
    """

    __tablename__ = "ability_snapshot"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    concept_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    theta: Mapped[float] = mapped_column(sa.Float, nullable=False)
    standard_error: Mapped[float | None] = mapped_column(sa.Float)
    response_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (sa.Index("idx_ability_snapshot_user", "user_id", sa.desc("measured_at")),)

    @classmethod
    def from_schema(cls, schema: SchemaAbilitySnapshot) -> AbilitySnapshot:
        """검증된 `schema.AbilitySnapshot` → 영속 ORM(schema↔db seam)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys and v is not None}
        return cls(**kwargs)

    def to_schema(self) -> SchemaAbilitySnapshot:
        """영속 ORM → `schema.AbilitySnapshot`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaAbilitySnapshot.model_validate(data)


__all__ = ["AbilitySnapshot", "Assessment", "ConceptMasteryHistory"]
