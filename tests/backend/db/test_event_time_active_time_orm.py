"""EOS-48 — event_time/ingested_at 분리 + active/idle 실측 좌석의 영속 계약 (DB 연결 없이).

기존 테이블 ALTER형 태스크라 검증 축이 신설 엔티티와 다르다: **비파괴**(전 컬럼 nullable·
server_default 없음 — 기존 행/writer 무영향·백필 날조 방지)와 **round-trip 정합**(신규 ORM
컬럼이 Pydantic schema에 대응 필드를 가져 to_schema가 깨지지 않음 — extra='forbid' 계약)을
못박는다. red 실측: ORM 컬럼만 추가한 시점에 `test_activity_orm.py` 5건이 ValidationError로
red였고(세션 보고 기록), schema 필드 추가로 green — 그 계약을 여기서 이름으로 동결한다.

`ProblemAttempt.ingested_at`은 SEC-33 ⑥(19149e92d368)에서 이 무-server_default 계약을
**의도적으로 벗어났다** — `privacy/retention`의 COALESCE 폴백 좌석이 되므로 신규 INSERT가
값을 생략해도 서버 시각으로 채워지는 안전망이 필요해졌다. `SET DEFAULT`는 기존 행을 건드리지
않으므로(ALTER 시 UPDATE가 아니다) EOS-48이 막으려던 "기존 행 백필" 위험은 발생하지 않는다 —
그래서 이 컬럼만 별도 클래스(`TestIngestedAtHasServerDefaultSinceSec33`)로 검증한다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from whymath_backend.db.models.activity import AttemptEvent, LearningSession, ProblemAttempt
from whymath_backend.schema.activity import AttemptEvent as AttemptEventSchema
from whymath_backend.schema.activity import LearningSession as LearningSessionSchema
from whymath_backend.schema.activity import ProblemAttempt as ProblemAttemptSchema

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VERSIONS_DIR = _REPO_ROOT / "src" / "backend" / "alembic" / "versions"

# (모델, 신규 컬럼) — EOS-48이 더한 컬럼 중 *여전히* server_default가 없어야 하는 것들.
# `ProblemAttempt.ingested_at`은 SEC-33 ⑥이 의도적으로 제외했다(아래 별도 클래스 참조).
_NEW_COLUMNS = (
    (AttemptEvent, "event_time"),
    (ProblemAttempt, "active_seconds"),
    (ProblemAttempt, "idle_seconds"),
    (LearningSession, "active_seconds"),
    (LearningSession, "idle_seconds"),
)


class TestNonDestructiveColumns:
    def test_all_new_columns_nullable_without_server_default(self) -> None:
        """전 신규 컬럼 nullable + server_default 없음 — 기존 행 백필 0(날조 방지)·기존 writer
        무영향. `ADD COLUMN DEFAULT now()`는 기존 행에 마이그레이션 시각을 채우는 날조라
        금지된 설계다(마이그레이션 docstring)."""
        for model, name in _NEW_COLUMNS:
            column = model.__table__.columns[name]
            assert column.nullable is True, f"{model.__tablename__}.{name}은 nullable이어야 한다"
            assert (
                column.server_default is None
            ), f"{model.__tablename__}.{name}에 server_default가 있다 — 기존 행 백필 날조 위험"
            assert len(column.foreign_keys) == 0  # 순수 시각/초 좌석(FK 아님)


class TestIngestedAtHasServerDefaultSinceSec33:
    def test_ingested_at_still_nullable(self) -> None:
        """server_default가 생겨도 컬럼 자체의 NULL 허용은 불변 — 과거(EOS-48 이전) 행 대조 유지."""
        column = ProblemAttempt.__table__.columns["ingested_at"]
        assert column.nullable is True

    def test_ingested_at_has_a_server_default(self) -> None:
        """SEC-33 ⑥ — COALESCE 폴백 좌석이 되므로 신규 INSERT 생략분을 서버 시각으로 채운다.

        `ALTER COLUMN ... SET DEFAULT`는 기존 행을 UPDATE하지 않는다(PG 의미론) — 이 계약이
        깨지면(server_default가 사라지면) 세 번째 writer가 `ingested_at`을 생략했을 때
        `privacy/retention`의 COALESCE 폴백이 다시 NULL로 무력화된다.
        """
        column = ProblemAttempt.__table__.columns["ingested_at"]
        assert (
            column.server_default is not None
        ), "ingested_at에 server_default가 없다 — COALESCE 폴백이 셋째 writer 누락에 무방비"

    def test_existing_time_columns_untouched(self) -> None:
        """기존 시각 컬럼 불변 — event_at NOT NULL PK 구성요소·started_at/created_at 그대로
        (기존 소비자 회귀 0의 구조적 근거)."""
        assert AttemptEvent.__table__.columns["event_at"].nullable is False
        assert AttemptEvent.__table__.columns["event_at"].primary_key is True
        assert ProblemAttempt.__table__.columns["started_at"].nullable is True
        assert ProblemAttempt.__table__.columns["created_at"].server_default is not None
        assert LearningSession.__table__.columns["duration_seconds"].nullable is True


class TestSchemaRoundTripCarriesNewFields:
    """신규 컬럼이 Pydantic schema에 대응 필드를 가진다 — to_schema(extra='forbid') 정합 +
    export payload(`to_schema().model_dump()`) 노출의 전제(privacy 검토 acceptance ③)."""

    def test_attempt_event_round_trip(self) -> None:
        schema = AttemptEventSchema(
            event_at=datetime(2026, 8, 31, 1, 0, tzinfo=UTC),
            event_time=datetime(2026, 8, 30, 22, 0, tzinfo=UTC),  # 지연 도착(발생 < 수신)
            user_id=uuid.uuid4(),
        )
        orm = AttemptEvent.from_schema(schema)
        assert orm.event_time == schema.event_time
        restored = orm.to_schema()
        assert restored.event_time == schema.event_time
        assert "event_time" in restored.model_dump()  # export payload 노출 전제

    def test_problem_attempt_round_trip(self) -> None:
        schema = ProblemAttemptSchema(
            user_id=uuid.uuid4(),
            started_at=datetime(2026, 8, 30, 9, 0, tzinfo=UTC),
            ingested_at=datetime(2026, 8, 31, 1, 0, tzinfo=UTC),
            active_seconds=300,
            idle_seconds=60,
        )
        restored = ProblemAttempt.from_schema(schema).to_schema()
        assert restored.ingested_at == schema.ingested_at
        assert restored.active_seconds == 300
        assert restored.idle_seconds == 60

    def test_learning_session_round_trip_unmeasured_stays_none(self) -> None:
        """미측정(None)은 round-trip에서도 None — 0으로 승격되지 않는다(날조 금지)."""
        schema = LearningSessionSchema(
            user_id=uuid.uuid4(), started_at=datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
        )
        restored = LearningSession.from_schema(schema).to_schema()
        assert restored.active_seconds is None
        assert restored.idle_seconds is None


class TestMigrationFile:
    def test_migration_file_exists_with_symmetric_updown(self) -> None:
        """EOS-48 마이그레이션 존재·add/drop 대칭·server_default 0건(백필 날조 방지)."""
        matches = list(_VERSIONS_DIR.glob("*event_time_active_time.py"))
        assert len(matches) == 1, "EOS-48 마이그레이션 파일이 정확히 1개여야 한다"
        source = matches[0].read_text(encoding="utf-8")
        for table, name in (
            ("attempt_event", "event_time"),
            ("problem_attempt", "ingested_at"),
            ("problem_attempt", "active_seconds"),
            ("problem_attempt", "idle_seconds"),
            ("learning_session", "active_seconds"),
            ("learning_session", "idle_seconds"),
        ):
            assert f'"{name}"' in source, f"upgrade에 {name} 누락"
            assert f'op.drop_column("{table}", "{name}")' in source, f"downgrade {name} 대칭 위반"
        # upgrade 함수 구간에 server_default 0건 — 기존 행 백필 날조 방지(핵심 비파괴 계약).
        upgrade_src = source.split("def upgrade()")[1].split("def downgrade()")[0]
        assert "server_default" not in upgrade_src
        # 체인: EOS-46 student_solution_step(a926d39f126a) 위에 쌓인다.
        assert 'down_revision: str | None = "a926d39f126a"' in source

    def test_no_table_or_constraint_mutation(self) -> None:
        """컬럼 add/drop만 — 테이블 생성·제약 변경 0건(기존 데이터·hypertable 전환 절차와
        무충돌 — ADR-001 추기)."""
        source = next(_VERSIONS_DIR.glob("*event_time_active_time.py")).read_text(encoding="utf-8")
        assert "op.create_table(" not in source
        assert "op.drop_table(" not in source
        assert "op.create_unique_constraint(" not in source
        assert "op.drop_constraint(" not in source
