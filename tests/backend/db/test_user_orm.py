"""User ORM(영속 레이어) 단위테스트 — DB 연결 *없이* 검증 가능한 것만.

problem ORM 테스트 패턴 답습: 메타데이터 등록 / PG DDL 컴파일(JSONB·enum·DATE·gen_random_uuid)
/ enum values_callable / schema↔ORM 변환 roundtrip.

설계 정본: schemas/v1.0/schema_v1.0.md §5.1·§5.2.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from whymath_backend.db.base import Base
from whymath_backend.db.models.user import (
    UserPersonaHistory as OrmUserPersonaHistory,
)
from whymath_backend.db.models.user import (
    UserProfile as OrmUserProfile,
)
from whymath_backend.db.models.user import (
    UserStateSnapshot as OrmUserStateSnapshot,
)
from whymath_backend.db.models.user import (
    UserTrackHistory as OrmUserTrackHistory,
)
from whymath_backend.schema.enums import (
    Accessibility,
    Persona,
    Role,
    SchoolType,
    SubscriptionTier,
    TrackType,
)
from whymath_backend.schema.user import (
    UserPersonaHistory as SchemaUserPersonaHistory,
)
from whymath_backend.schema.user import (
    UserProfile as SchemaUserProfile,
)
from whymath_backend.schema.user import (
    UserStateSnapshot as SchemaUserStateSnapshot,
)
from whymath_backend.schema.user import (
    UserTrackHistory as SchemaUserTrackHistory,
)


def _pg_ddl(table: object) -> str:
    """ORM 테이블을 PostgreSQL dialect로 컴파일한 CREATE TABLE 문자열로 반환."""
    return str(CreateTable(table).compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────
# 1) 메타데이터 등록
# ──────────────────────────────────────────────────────────────────────────
def test_user_tables_registered_in_metadata() -> None:
    """Base.metadata에 도메인3 네 테이블이 등록돼 있다(alembic 인식 전제)."""
    tables = set(Base.metadata.tables.keys())
    assert {
        "user_profile",
        "user_track_history",
        "user_persona_history",
        "user_state_snapshot",
    } <= tables


def test_user_orm_tablenames() -> None:
    """각 ORM의 __tablename__이 §5 DDL 테이블명과 일치한다."""
    assert OrmUserProfile.__tablename__ == "user_profile"
    assert OrmUserTrackHistory.__tablename__ == "user_track_history"
    assert OrmUserPersonaHistory.__tablename__ == "user_persona_history"
    assert OrmUserStateSnapshot.__tablename__ == "user_state_snapshot"


# ──────────────────────────────────────────────────────────────────────────
# 2) PG DDL 컴파일
# ──────────────────────────────────────────────────────────────────────────
def test_user_profile_ddl_compiles() -> None:
    """UserProfile DDL에 JSONB·persona_enum·DATE·gen_random_uuid()·UUID 포함."""
    ddl = _pg_ddl(OrmUserProfile.__table__)
    assert "JSONB" in ddl  # target_universities
    assert "persona_enum" in ddl  # persona_primary
    assert "DATE" in ddl  # target_exam_date (TIMESTAMPTZ 아님)
    assert "gen_random_uuid()" in ddl
    assert "UUID" in ddl


def test_user_profile_enum_arrays_and_string_fields() -> None:
    """track_type[]·accessibility_needs[]는 enum 배열, gender/school_region은 String(enum 아님)."""
    ddl = _pg_ddl(OrmUserProfile.__table__)
    assert "track_type_enum" in ddl
    assert "accessibility_enum" in ddl
    # gender·school_region은 enum이 아니라 VARCHAR(String) — gender_enum·region_enum이 없어야 함.
    assert "gender_enum" not in ddl
    assert "region_enum" not in ddl


def test_user_persona_history_composite_pk() -> None:
    """user_persona_history: 복합 PK(user_id, detected_at) + user_profile FK."""
    ddl = _pg_ddl(OrmUserPersonaHistory.__table__)
    assert "PRIMARY KEY (user_id, detected_at)" in ddl
    assert "REFERENCES user_profile" in ddl


def test_user_state_snapshot_fk_and_jsonb() -> None:
    """user_state_snapshot: user_profile FK·concept_mastery JSONB·gen_random_uuid."""
    ddl = _pg_ddl(OrmUserStateSnapshot.__table__)
    assert "REFERENCES user_profile" in ddl
    assert "JSONB" in ddl  # concept_mastery·pattern_mastery
    assert "gen_random_uuid()" in ddl


def test_user_track_history_fk() -> None:
    """user_track_history: user_profile FK·track_before/after JSONB."""
    ddl = _pg_ddl(OrmUserTrackHistory.__table__)
    assert "REFERENCES user_profile" in ddl
    assert "JSONB" in ddl


# ──────────────────────────────────────────────────────────────────────────
# 3) enum values_callable
# ──────────────────────────────────────────────────────────────────────────
def test_user_persona_enum_values() -> None:
    """persona_primary 컬럼 enum이 값('A_일반고고3' 등)을 갖는다."""
    enums = OrmUserProfile.__table__.c.persona_primary.type.enums  # type: ignore[attr-defined]
    assert "A_일반고고3" in enums
    assert "E_홈스쿨링영재" in enums


def test_user_school_type_enum_values() -> None:
    """school_type 컬럼 enum이 한글 값('일반고'·'자사고_전국' 등)을 갖는다."""
    enums = OrmUserProfile.__table__.c.school_type.type.enums  # type: ignore[attr-defined]
    assert "일반고" in enums
    assert "자사고_전국" in enums


def test_user_role_column_ddl_and_enum_values() -> None:
    """role 컬럼(SEC-07 D1) — NOT NULL·server_default='student'·role_enum 5값(P3-12가 CMS 3값을
    더했다). 멤버명≠값이므로 values_callable이 실제 *값*을 썼는지 확인한다(`_orm_enum.py` 규약)."""
    ddl = _pg_ddl(OrmUserProfile.__table__)
    assert "role_enum" in ddl
    assert "NOT NULL" in ddl
    assert "'student'" in ddl
    enums = OrmUserProfile.__table__.c.role.type.enums  # type: ignore[attr-defined]
    # 값(멤버명 아님)이 들어가야 한다 — Role.STUDENT="student"(멤버명 STUDENT와 다름).
    assert set(enums) == {
        "student",
        "content_admin",
        "content_editor",
        "content_reviewer",
        "content_publisher",
    }


# ──────────────────────────────────────────────────────────────────────────
# 4) 변환 roundtrip
# ──────────────────────────────────────────────────────────────────────────
def test_user_profile_roundtrip_preserves_core_fields() -> None:
    """schema.UserProfile → ORM → schema가 핵심 필드(id·페르소나·학적·트랙·날짜)를 보존."""
    uid = uuid.uuid4()
    s = SchemaUserProfile(
        user_id=uid,
        persona_primary=Persona.A_일반고고3,
        persona_secondary=Persona.D_학종고2,
        school_type=SchoolType.일반고,
        school_region="서울_강남",  # str(enum 아님)
        gender="무응답",  # str(enum 아님)
        track_type=[TrackType.정시, TrackType.수시학종],
        target_universities=[{"univ": "서울대", "major": "의예", "priority": 1}],
        target_exam_date=date(2026, 11, 19),
        accessibility_needs=[Accessibility.큰글씨],
        subscription_tier=SubscriptionTier.premium,
        diagnostic_completed=True,
    )
    orm = OrmUserProfile.from_schema(s)
    assert orm.user_id == uid
    assert orm.persona_primary == "A_일반고고3"
    assert orm.school_type == "일반고"
    assert orm.school_region == "서울_강남"
    assert orm.gender == "무응답"
    assert orm.track_type == ["정시", "수시학종"]
    assert orm.target_universities == [{"univ": "서울대", "major": "의예", "priority": 1}]
    assert orm.target_exam_date == date(2026, 11, 19)

    back = orm.to_schema()
    assert back.user_id == uid
    assert back.persona_primary == s.persona_primary
    assert back.school_type == s.school_type
    assert back.school_region == s.school_region
    assert back.gender == s.gender
    assert back.track_type == s.track_type
    assert back.target_exam_date == date(2026, 11, 19)
    assert back.accessibility_needs == s.accessibility_needs


def test_user_profile_minimal_only_persona() -> None:
    """persona_primary만 채운 최소 레코드도 변환된다(유일 required)."""
    s = SchemaUserProfile(persona_primary=Persona.C_검정고시N수)
    orm = OrmUserProfile.from_schema(s)
    assert orm.persona_primary == "C_검정고시N수"
    back = orm.to_schema()
    assert back.persona_primary == s.persona_primary
    # 기본값 보존(diagnostic_completed·is_active·is_deleted·role).
    assert back.diagnostic_completed is False
    assert back.is_active is True
    assert back.role == Role.STUDENT.value  # use_enum_values=True → 문자열 "student"


def test_user_profile_role_content_admin_roundtrip() -> None:
    """role=CONTENT_ADMIN 명시 지정도 schema→ORM→schema 왕복에서 보존된다."""
    s = SchemaUserProfile(persona_primary=Persona.A_일반고고3, role=Role.CONTENT_ADMIN)
    orm = OrmUserProfile.from_schema(s)
    assert orm.role == "content_admin"
    back = orm.to_schema()
    assert back.role == Role.CONTENT_ADMIN.value


def test_user_persona_history_roundtrip() -> None:
    """UserPersonaHistory schema↔ORM 변환이 복합키·신호를 보존한다."""
    uid = uuid.uuid4()
    dt = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    s = SchemaUserPersonaHistory(
        user_id=uid,
        detected_at=dt,
        persona=Persona.A_일반고고3,
        confidence=0.85,
        signals={"sessions": 12, "avg_difficulty": 0.7},
    )
    orm = OrmUserPersonaHistory.from_schema(s)
    assert orm.user_id == uid
    assert orm.detected_at == dt
    assert orm.persona == "A_일반고고3"

    back = orm.to_schema()
    assert back.user_id == uid
    assert back.detected_at == dt
    assert back.persona == s.persona
    assert back.signals == s.signals


def test_user_state_snapshot_roundtrip() -> None:
    """UserStateSnapshot schema↔ORM 변환이 숙련도 맵(JSONB)을 보존한다."""
    uid = uuid.uuid4()
    s = SchemaUserStateSnapshot(
        user_id=uid,
        estimated_grade=2.0,
        concept_mastery={"CAL-INT-DEF": 0.8, "FUN-COMPOSITE": 0.5},
        pattern_mastery={"COMPOSITE_DIFFERENTIABILITY": 0.6},
        avg_solve_time_by_difficulty={"easy": 60, "medium": 180, "hard": 600},
    )
    orm = OrmUserStateSnapshot.from_schema(s)
    assert orm.user_id == uid
    assert orm.concept_mastery == {"CAL-INT-DEF": 0.8, "FUN-COMPOSITE": 0.5}

    back = orm.to_schema()
    assert back.user_id == uid
    assert back.concept_mastery == s.concept_mastery
    assert back.pattern_mastery == s.pattern_mastery
    assert back.avg_solve_time_by_difficulty == s.avg_solve_time_by_difficulty


def test_user_track_history_roundtrip() -> None:
    """UserTrackHistory schema↔ORM 변환이 트랙 스냅샷(JSONB)을 보존한다."""
    uid = uuid.uuid4()
    s = SchemaUserTrackHistory(
        user_id=uid,
        track_before={"track": "정시"},
        track_after={"track": "수시학종"},
        reason="모의고사 성적 변화",
    )
    orm = OrmUserTrackHistory.from_schema(s)
    assert orm.user_id == uid
    assert orm.track_before == {"track": "정시"}

    back = orm.to_schema()
    assert back.user_id == uid
    assert back.track_after == s.track_after
    assert back.reason == s.reason
