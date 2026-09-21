"""도메인3 학생(User) ORM 모델 (SQLAlchemy 2.0 영속 레이어).

설계 정본: `schemas/v1.0/schema_v1.0.md` §5.1(`user_profile`·`user_track_history`·
`user_persona_history` DDL)·§5.2(`user_state_snapshot` DDL)·§5 인덱스. 이 ORM은
`schema/user.py`(Pydantic, 검증·API)와 *별도*로 세운 영속 매핑이며 `from_schema`/`to_schema`
변환 헬퍼가 둘을 잇는다(슬라이스 1 `problem.py` 동일 패턴).

타입 매핑(DDL → ORM, problem.py 선례 그대로):
  - `UUID PRIMARY KEY DEFAULT gen_random_uuid()` → `server_default gen_random_uuid()`.
  - `UUID REFERENCES user_profile`(nullable) → `uuid.UUID|None` + FK.
  - `gender_enum`/`region_enum`은 *enum이 아님* — schema가 `str`로 둔(닫힌 카테고리 미확정,
    §14.3 정의 없음) 정책 그대로 ORM도 `sa.String`(slice4 gender/school_region docstring).
  - `persona_enum NOT NULL`(persona_primary) → required enum; 나머지 enum은 nullable.
  - `enum[]`(track_type·accessibility_needs) → `ARRAY(_pg_enum(...))`(DDL NOT NULL 아님 →
    nullable list, concept.cognitive_type 선례).
  - `TEXT[]`(inkang_provider) → `ARRAY(sa.Text)`(nullable list).
  - `DATE`(target_exam_date) → `sa.Date`(TIMESTAMPTZ 아님 — 날짜만).
  - `JSONB`(target_universities·track_before/after·concept_mastery 등) → `JSONB`.
  - `BOOLEAN DEFAULT FALSE/TRUE` → `nullable=False, server_default sa.false()/sa.true()`;
    기본값 없는 `BOOLEAN` → `bool|None`(미응답=NULL 구분 — schema가 bool|None으로 둔 선례).
  - `TIMESTAMPTZ` → `sa.DateTime(timezone=True)`; `VARCHAR(n)` → `sa.String(n)`.
  - 인덱스(§5 `CREATE INDEX`, snapshot은 snapshot_at DESC) → `__table_args__`.

개인정보 메모: "is_minor면 parent_consent_at 필수" 같은 cross-field 강제는 schema가
*일부러 하지 않는다*(동의 대기 상태가 정당 → 미들웨어 책임). ORM도 동일하게 강제하지
않는다(가짜 CHECK 없음 — concept.py 법적 메모 방침).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base
from whymath_backend.db.models._orm_enum import _pg_enum
from whymath_backend.db.models._schema_seam import drop_unset_nulls
from whymath_backend.schema.enums import (
    Accessibility,
    Device,
    MajorCategory,
    NoteApp,
    Persona,
    Role,
    SchoolType,
    SubscriptionTier,
    TrackType,
)
from whymath_backend.schema.user import UserPersonaHistory as SchemaUserPersonaHistory
from whymath_backend.schema.user import UserProfile as SchemaUserProfile
from whymath_backend.schema.user import UserStateSnapshot as SchemaUserStateSnapshot
from whymath_backend.schema.user import UserTrackHistory as SchemaUserTrackHistory


# ──────────────────────────────────────────────────────────────────────────
# 핵심: UserProfile (§5.1 user_profile 테이블 — 학생 프로필, ~40필드)
# ──────────────────────────────────────────────────────────────────────────
class UserProfile(Base):
    """학생 프로필 영속 ORM — §5.1 `user_profile`. 학적·입시 트랙·페르소나·학습 환경·진단·
    구독·보호자 정보를 담는 도메인3 핵심 모델.

    유일한 required(NOT NULL)는 `persona_primary`(DDL `persona_enum NOT NULL`)이다 — 가입 직후
    페르소나만 분류된 최소 레코드도 표현할 수 있어야 하기 때문(schema와 정합).

    `gender`·`school_region`은 enum이 아니라 `String`이다 — §14.3에 정의가 없고 닫힌 카테고리
    강제가 미성년 민감정보에 부적절해 schema가 `str`로 둔 정책을 ORM도 그대로 따른다(모듈
    docstring). 개인정보 cross-field 불변식은 미들웨어 책임이라 ORM/schema 모두 강제 안 함.
    """

    __tablename__ = "user_profile"

    # ===== 기본 식별 =====
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )

    # ===== 기본 정보 (개인정보 보호) =====
    email_hash: Mapped[str | None] = mapped_column(sa.String(64), unique=True)
    nickname: Mapped[str | None] = mapped_column(sa.String(50))
    birth_year: Mapped[int | None] = mapped_column(sa.Integer)
    # gender_enum 미확정 → String(schema str 정책 답습).
    gender: Mapped[str | None] = mapped_column(sa.String(32))

    # ===== 학적 정보 =====
    school_type: Mapped[SchoolType | None] = mapped_column(_pg_enum(SchoolType, "school_type_enum"))
    # region_enum 미확정 → String(schema str 정책 답습).
    school_region: Mapped[str | None] = mapped_column(sa.String(64))
    school_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    grade: Mapped[int | None] = mapped_column(sa.Integer)

    # ===== 입시 트랙 =====
    track_type: Mapped[list[TrackType] | None] = mapped_column(
        ARRAY(_pg_enum(TrackType, "track_type_enum"))
    )
    target_universities: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    target_major_category: Mapped[MajorCategory | None] = mapped_column(
        _pg_enum(MajorCategory, "major_category_enum")
    )

    # ===== 학습 목표 =====
    target_grade: Mapped[int | None] = mapped_column(sa.Integer)
    target_score: Mapped[int | None] = mapped_column(sa.Integer)
    # DATE — 날짜만(TIMESTAMPTZ 아님).
    target_exam_date: Mapped[date | None] = mapped_column(sa.Date)

    # ===== 페르소나 분류 =====
    persona_primary: Mapped[Persona] = mapped_column(
        _pg_enum(Persona, "persona_enum"),
        nullable=False,
    )
    persona_secondary: Mapped[Persona | None] = mapped_column(_pg_enum(Persona, "persona_enum"))
    persona_confidence: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))

    # ===== 학습 환경 =====
    primary_device: Mapped[Device | None] = mapped_column(_pg_enum(Device, "device_enum"))
    # 기본값 없는 BOOLEAN → 미응답=NULL 구분(schema bool|None 선례).
    has_apple_pencil: Mapped[bool | None] = mapped_column(sa.Boolean)
    note_app: Mapped[NoteApp | None] = mapped_column(_pg_enum(NoteApp, "note_app_enum"))

    # ===== 현재 학력 진단 =====
    current_grade_estimate: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    current_grade_updated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    diagnostic_completed: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    diagnostic_completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    # ===== 사교육 사용 현황 =====
    uses_inkang: Mapped[bool | None] = mapped_column(sa.Boolean)
    inkang_provider: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text))
    uses_offline_academy: Mapped[bool | None] = mapped_column(sa.Boolean)
    monthly_education_spend: Mapped[int | None] = mapped_column(sa.Integer)

    # ===== 결제·구독 =====
    subscription_tier: Mapped[SubscriptionTier | None] = mapped_column(
        _pg_enum(SubscriptionTier, "subscription_tier_enum")
    )
    subscription_started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    subscription_renewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    # ===== 보호자 정보 (미성년자 보호) =====
    is_minor: Mapped[bool | None] = mapped_column(sa.Boolean)
    parent_consent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    parent_email_hash: Mapped[str | None] = mapped_column(sa.String(64))

    # ===== 접근성 =====
    accessibility_needs: Mapped[list[Accessibility] | None] = mapped_column(
        ARRAY(_pg_enum(Accessibility, "accessibility_enum"))
    )

    # ===== 인가(authorization) 역할 (SEC-07 D1 — 콘텐츠 CUD 게이팅) =====
    # Role은 str mixin이 아니다(enums.py 참조 — 7단 선형 서열 재도입 방지를 위해 <·> 비교가
    # TypeError). _pg_enum은 어느 Enum이든 values_callable로 값(멤버명 아님)을 쓰므로 무관하다.
    role: Mapped[Role] = mapped_column(
        _pg_enum(Role, "role_enum"),
        nullable=False,
        server_default="student",
    )

    # ===== 운영 메타 =====
    created_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    last_active_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    is_deleted: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    # ── 인덱스 (§5 CREATE INDEX) ──
    __table_args__ = (
        sa.Index("idx_user_persona", "persona_primary"),
        sa.Index("idx_user_school", "school_type", "grade"),
        sa.Index("idx_user_target", "target_major_category"),
        sa.Index("idx_user_active", "is_active", "last_active_at"),
    )

    # ── 변환 헬퍼 (schema↔db seam, problem.py 패턴) ──────────────────────
    @classmethod
    def from_schema(cls, schema: SchemaUserProfile) -> UserProfile:
        """검증된 `schema.UserProfile` → 영속 ORM(mapper 컬럼키 필터)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaUserProfile:
        """영속 ORM → `schema.UserProfile`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaUserProfile.model_validate(
            drop_unset_nulls(data, SchemaUserProfile, orm_cls=type(self))
        )


# ──────────────────────────────────────────────────────────────────────────
# 보조: UserTrackHistory (§5.1 user_track_history — 진로 변경 이력)
# ──────────────────────────────────────────────────────────────────────────
class UserTrackHistory(Base):
    """학생 진로 변경 이력 영속 ORM — §5.1 `user_track_history`.

    `track_before`/`track_after`는 변경 전후 트랙 스냅샷(자유형 JSONB). PK `history_id`만
    있고 나머지는 nullable(DDL 그대로). `user_id`→user_profile FK.
    """

    __tablename__ = "user_track_history"

    history_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("user_profile.user_id")
    )
    changed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    track_before: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    track_after: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    reason: Mapped[str | None] = mapped_column(sa.Text)

    @classmethod
    def from_schema(cls, schema: SchemaUserTrackHistory) -> UserTrackHistory:
        """검증된 `schema.UserTrackHistory` → 영속 ORM(schema↔db seam)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaUserTrackHistory:
        """영속 ORM → `schema.UserTrackHistory`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaUserTrackHistory.model_validate(
            drop_unset_nulls(data, SchemaUserTrackHistory, orm_cls=type(self))
        )


# ──────────────────────────────────────────────────────────────────────────
# 보조: UserPersonaHistory (§5.1 user_persona_history — 페르소나 분류 이력)
# ──────────────────────────────────────────────────────────────────────────
class UserPersonaHistory(Base):
    """페르소나 분류 이력 영속 ORM — §5.1 `user_persona_history`.

    복합 PK `(user_id, detected_at)` — DDL 제약. PK 구성요소는 NOT NULL이므로 둘 다
    primary_key. `signals`는 판정 근거 행동 신호(자유형 JSONB). user_id에 FK는 DDL에 명시되지
    않았으나(복합 PK만), 의미상 user_profile을 가리키므로 schema docstring("user_profile 참조")
    정합 위해 FK를 건다(problem_relation이 PK 구성 FK를 건 선례와 동형).
    """

    __tablename__ = "user_persona_history"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("user_profile.user_id"), primary_key=True
    )
    detected_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), primary_key=True)
    persona: Mapped[Persona | None] = mapped_column(_pg_enum(Persona, "persona_enum"))
    confidence: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    signals: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    @classmethod
    def from_schema(cls, schema: SchemaUserPersonaHistory) -> UserPersonaHistory:
        """검증된 `schema.UserPersonaHistory` → 영속 ORM(schema↔db seam)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaUserPersonaHistory:
        """영속 ORM → `schema.UserPersonaHistory`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaUserPersonaHistory.model_validate(
            drop_unset_nulls(data, SchemaUserPersonaHistory, orm_cls=type(self))
        )


# ──────────────────────────────────────────────────────────────────────────
# 핵심: UserStateSnapshot (§5.2 user_state_snapshot — 시점별 학습 상태)
# ──────────────────────────────────────────────────────────────────────────
class UserStateSnapshot(Base):
    """학생 시점별 학습 상태 스냅샷 영속 ORM — §5.2 `user_state_snapshot`.

    `concept_mastery`·`pattern_mastery`는 {코드: 숙련도0-1} 맵(JSONB), `avg_solve_time_by_
    difficulty`는 난이도 키 자유형 JSONB. `embedding_id`는 벡터 저장소(pgvector·Postgres
    동거·슬98) 참조(벡터 저장 아님). PK `snapshot_id`만 있고 나머지는 nullable(DDL 그대로).
    `user_id`→user_profile FK.

    인덱스 `idx_snapshot_user_time`는 DDL에서 `(user_id, snapshot_at DESC)`이므로 snapshot_at에
    내림차순을 부여한다(`sa.desc()`).
    """

    __tablename__ = "user_state_snapshot"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("user_profile.user_id")
    )
    snapshot_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    # ===== 종합 학력 =====
    estimated_grade: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))
    estimated_score: Mapped[int | None] = mapped_column(sa.Integer)
    estimated_percentile: Mapped[float | None] = mapped_column(sa.Numeric(5, 2))

    # ===== 단원별/패턴별 숙련도 (키→스칼라 맵 JSONB) =====
    concept_mastery: Mapped[dict[str, float] | None] = mapped_column(JSONB(none_as_null=True))
    pattern_mastery: Mapped[dict[str, float] | None] = mapped_column(JSONB(none_as_null=True))

    # ===== 시간 관리 능력 =====
    avg_solve_time_by_difficulty: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    time_management_score: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))

    # ===== 멘탈·컨디션 신호 =====
    consecutive_active_days: Mapped[int | None] = mapped_column(sa.Integer)
    avg_session_quality: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))

    # ===== 임베딩 (pgvector·Postgres 동거 참조 — 벡터 저장 아님·슬98) =====
    embedding_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)

    # ── 인덱스 (§5.2 CREATE INDEX — snapshot_at DESC) ──
    __table_args__ = (sa.Index("idx_snapshot_user_time", "user_id", sa.desc("snapshot_at")),)

    @classmethod
    def from_schema(cls, schema: SchemaUserStateSnapshot) -> UserStateSnapshot:
        """검증된 `schema.UserStateSnapshot` → 영속 ORM(schema↔db seam)."""
        data = schema.model_dump()
        mapped_keys = {col.key for col in sa.inspect(cls).mapper.column_attrs}
        kwargs = {k: v for k, v in data.items() if k in mapped_keys}
        return cls(**kwargs)

    def to_schema(self) -> SchemaUserStateSnapshot:
        """영속 ORM → `schema.UserStateSnapshot`(Pydantic 검증 복원)."""
        mapped_keys = {col.key for col in sa.inspect(type(self)).mapper.column_attrs}
        data = {key: getattr(self, key) for key in mapped_keys}
        return SchemaUserStateSnapshot.model_validate(
            drop_unset_nulls(data, SchemaUserStateSnapshot, orm_cls=type(self))
        )


__all__ = [
    "UserProfile",
    "UserTrackHistory",
    "UserPersonaHistory",
    "UserStateSnapshot",
]
