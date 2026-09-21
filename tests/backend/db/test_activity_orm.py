"""Activity ORM(영속 레이어) 단위테스트 — DB 연결 *없이* 검증 가능한 것만.

problem/user ORM 테스트 패턴 답습: 메타데이터 등록 / PG DDL 컴파일(JSONB·enum·BIGSERIAL·
복합PK·부분인덱스) / enum values_callable / schema↔ORM 변환 roundtrip. hypertable 변환은
마이그레이션 레벨이라 여기서 보지 않는다(ORM은 일반 테이블).

설계 정본: schemas/v1.0/schema_v1.0.md §6.1.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from whymath_backend.db.base import Base
from whymath_backend.db.models.activity import (
    AttemptEvent as OrmAttemptEvent,
)
from whymath_backend.db.models.activity import (
    LearningSession as OrmLearningSession,
)
from whymath_backend.db.models.activity import (
    ProblemAttempt as OrmProblemAttempt,
)
from whymath_backend.schema.activity import (
    AttemptEvent as SchemaAttemptEvent,
)
from whymath_backend.schema.activity import (
    LearningSession as SchemaLearningSession,
)
from whymath_backend.schema.activity import (
    ProblemAttempt as SchemaProblemAttempt,
)
from whymath_backend.schema.enums import (
    AttemptMode,
    Device,
    EventType,
    SessionType,
)


def _pg_ddl(table: object) -> str:
    """ORM 테이블을 PostgreSQL dialect로 컴파일한 CREATE TABLE 문자열로 반환."""
    return str(CreateTable(table).compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────
# 1) 메타데이터 등록
# ──────────────────────────────────────────────────────────────────────────
def test_activity_tables_registered_in_metadata() -> None:
    """Base.metadata에 도메인4 세 테이블이 등록돼 있다(alembic 인식 전제)."""
    tables = set(Base.metadata.tables.keys())
    assert {"learning_session", "problem_attempt", "attempt_event"} <= tables


def test_activity_orm_tablenames() -> None:
    """각 ORM의 __tablename__이 §6.1 DDL 테이블명과 일치한다."""
    assert OrmLearningSession.__tablename__ == "learning_session"
    assert OrmProblemAttempt.__tablename__ == "problem_attempt"
    assert OrmAttemptEvent.__tablename__ == "attempt_event"


# ──────────────────────────────────────────────────────────────────────────
# 2) PG DDL 컴파일
# ──────────────────────────────────────────────────────────────────────────
def test_learning_session_ddl_compiles() -> None:
    """LearningSession DDL에 session_type_enum·device_enum·gen_random_uuid()·UUID 포함."""
    ddl = _pg_ddl(OrmLearningSession.__table__)
    assert "session_type_enum" in ddl
    assert "device_enum" in ddl  # device_used (배치1 공유 enum)
    assert "gen_random_uuid()" in ddl
    assert "UUID" in ddl
    assert "NUMERIC" in ddl  # focus_score·engagement_score DECIMAL


def test_learning_session_fk_and_loose_ref() -> None:
    """learning_session: user_id→user_profile FK O, target_concept_id는 FK 아님(REFERENCES 없음)."""
    ddl = _pg_ddl(OrmLearningSession.__table__)
    assert "REFERENCES user_profile" in ddl
    # target_concept_id는 §6.1 DDL에 REFERENCES가 없어 FK 아님 — concept 참조가 없어야 함.
    assert "REFERENCES concept" not in ddl
    # FK는 user_id 하나뿐.
    assert len(OrmLearningSession.__table__.foreign_keys) == 1


def test_problem_attempt_ddl_fks_and_jsonb() -> None:
    """problem_attempt: FK 3개(user_profile·learning_session·problem)
    ·ocr_result/step_times JSONB."""
    ddl = _pg_ddl(OrmProblemAttempt.__table__)
    assert "REFERENCES user_profile" in ddl
    assert "REFERENCES learning_session" in ddl
    assert "REFERENCES problem" in ddl
    assert "JSONB" in ddl  # ocr_result·step_times
    # stuck_at_concept_id는 REFERENCES 없음 → FK 아님(FK는 정확히 3개).
    assert len(OrmProblemAttempt.__table__.foreign_keys) == 3


def test_problem_attempt_partial_index() -> None:
    """idx_attempt_stuck은 부분 인덱스(WHERE stuck_at_concept_id IS NOT NULL)다."""
    idxs = {i.name: i for i in OrmProblemAttempt.__table__.indexes}
    assert "idx_attempt_stuck" in idxs
    where = idxs["idx_attempt_stuck"].dialect_options["postgresql"]["where"]
    assert where is not None  # 부분 인덱스 조건이 설정됨
    # 다른 두 인덱스도 존재.
    assert "idx_attempt_user" in idxs
    assert "idx_attempt_problem" in idxs


def test_attempt_event_bigserial_and_composite_pk() -> None:
    """attempt_event: event_id BIGSERIAL·복합 PK(event_id, event_at)·FK 없음(느슨참조)."""
    ddl = _pg_ddl(OrmAttemptEvent.__table__)
    # BIGSERIAL — BigInteger autoincrement PK가 PG에서 BIGSERIAL로 방출.
    assert "BIGSERIAL" in ddl
    assert "PRIMARY KEY (event_id, event_at)" in ddl
    assert "JSONB" in ddl  # event_data
    assert "event_type_enum" in ddl
    # attempt_id/user_id/problem_id는 REFERENCES 없음 → FK 0개.
    assert len(OrmAttemptEvent.__table__.foreign_keys) == 0


def test_attempt_event_event_id_autoincrement() -> None:
    """event_id 컬럼이 autoincrement(DB-assigned BIGSERIAL)로 설정돼 있다."""
    col = OrmAttemptEvent.__table__.c.event_id
    assert col.primary_key is True
    assert col.autoincrement is True


# ──────────────────────────────────────────────────────────────────────────
# 3) enum values_callable — 멤버명이 아니라 *값*이 PG enum 라벨인지
# ──────────────────────────────────────────────────────────────────────────
def test_session_type_enum_values() -> None:
    """session_type 컬럼 enum이 한글 값('자유학습' 등)을 갖는다."""
    enums = OrmLearningSession.__table__.c.session_type.type.enums  # type: ignore[attr-defined]
    assert "자유학습" in enums
    assert "AI추천" in enums


def test_device_enum_reused_values() -> None:
    """device_used 컬럼이 배치1 device_enum 값('아이패드'·'iPhone' 등)을 공유한다."""
    enums = OrmLearningSession.__table__.c.device_used.type.enums  # type: ignore[attr-defined]
    assert "아이패드" in enums
    assert "iPhone" in enums


def test_attempt_mode_and_event_type_enum_values() -> None:
    """attempt_mode·event_type enum이 한글 값을 갖는다."""
    am = OrmProblemAttempt.__table__.c.attempt_mode.type.enums  # type: ignore[attr-defined]
    assert "Socratic대화" in am
    assert "풀이공개" in am
    et = OrmAttemptEvent.__table__.c.event_type.type.enums  # type: ignore[attr-defined]
    assert "막힘" in et
    assert "힌트요청" in et


# ──────────────────────────────────────────────────────────────────────────
# 4) 변환 roundtrip
# ──────────────────────────────────────────────────────────────────────────
def test_learning_session_roundtrip() -> None:
    """LearningSession schema↔ORM 변환이 핵심 필드(id·유형·기기·점수)를 보존한다."""
    sid = uuid.uuid4()
    uid = uuid.uuid4()
    s = SchemaLearningSession(
        session_id=sid,
        user_id=uid,
        session_type=SessionType.단원집중,
        device_used=Device.아이패드,
        focus_score=0.85,
        problems_attempted=10,
        network_type="wifi",
    )
    orm = OrmLearningSession.from_schema(s)
    assert orm.session_id == sid
    assert orm.user_id == uid
    assert orm.session_type == "단원집중"
    assert orm.device_used == "아이패드"
    assert orm.network_type == "wifi"

    back = orm.to_schema()
    assert back.session_id == sid
    assert back.session_type == s.session_type
    assert back.device_used == s.device_used
    assert back.focus_score == 0.85


def test_problem_attempt_roundtrip_jsonb_and_loose_ref() -> None:
    """ProblemAttempt 변환이 OCR/step_times JSONB·느슨참조(stuck_at_concept_id)를 보존한다."""
    aid = uuid.uuid4()
    pid = uuid.uuid4()
    stuck = uuid.uuid4()
    s = SchemaProblemAttempt(
        attempt_id=aid,
        problem_id=pid,
        is_correct=True,
        attempt_mode=AttemptMode.Socratic대화,
        used_socratic=True,
        used_solution_view=False,
        ocr_result={"text": "f(x)=x^2", "conf": 0.9},
        step_times=[{"step": 1, "seconds": 30}, {"step": 2, "seconds": 120}],
        stuck_at_concept_id=stuck,
        selected_choice_index=2,
    )
    orm = OrmProblemAttempt.from_schema(s)
    assert orm.attempt_id == aid
    assert orm.is_correct is True
    assert orm.attempt_mode == "Socratic대화"
    assert orm.ocr_result == {"text": "f(x)=x^2", "conf": 0.9}
    assert orm.step_times == [{"step": 1, "seconds": 30}, {"step": 2, "seconds": 120}]
    assert orm.stuck_at_concept_id == stuck
    assert orm.selected_choice_index == 2

    back = orm.to_schema()
    assert back.attempt_id == aid
    assert back.ocr_result == s.ocr_result
    assert back.step_times == s.step_times
    assert back.stuck_at_concept_id == stuck
    assert back.used_solution_view is False
    assert back.selected_choice_index == 2


def test_problem_attempt_selected_choice_index_defaults_to_none() -> None:
    """ASM-06: selected_choice_index 미지정(자유응답형 등) → None으로 보존(기존 행 호환)."""
    s = SchemaProblemAttempt()
    orm = OrmProblemAttempt.from_schema(s)
    assert orm.selected_choice_index is None
    back = orm.to_schema()
    assert back.selected_choice_index is None


def test_problem_attempt_default_step_times() -> None:
    """step_times 미지정 시 빈 리스트로 보존된다(schema default_factory=list)."""
    s = SchemaProblemAttempt()
    orm = OrmProblemAttempt.from_schema(s)
    assert orm.step_times == []
    back = orm.to_schema()
    assert back.step_times == []


def test_attempt_event_roundtrip_with_event_id() -> None:
    """AttemptEvent 변환이 복합 PK 구성요소(event_id·event_at)·event_data를 보존한다."""
    at = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    s = SchemaAttemptEvent(
        event_id=123,
        event_at=at,
        event_type=EventType.막힘,
        event_data={"step": 2, "duration": 45},
    )
    orm = OrmAttemptEvent.from_schema(s)
    assert orm.event_id == 123
    assert orm.event_at == at
    assert orm.event_type == "막힘"
    assert orm.event_data == {"step": 2, "duration": 45}

    back = orm.to_schema()
    assert back.event_id == 123
    assert back.event_at == at
    assert back.event_type == s.event_type
    assert back.event_data == s.event_data


def test_attempt_event_db_assigned_event_id() -> None:
    """event_id 미지정(BIGSERIAL DB-assigned) 시 None으로 두고 변환된다."""
    at = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    s = SchemaAttemptEvent(event_at=at, event_type=EventType.답입력)
    orm = OrmAttemptEvent.from_schema(s)
    # 클라이언트 기본값 없음 → None(INSERT 시 DB가 autoincrement로 채운다).
    assert orm.event_id is None
    back = orm.to_schema()
    assert back.event_id is None
    assert back.event_at == at
