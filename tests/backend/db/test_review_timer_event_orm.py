"""ReviewTimerEvent ORM(`review_timer_event`) — DB 연결 없이 검증 (EOS-54 acceptance ①).

`test_hint_usage_orm.py`(EOS-45) 컨벤션 미러: 메타데이터 등록·PG DDL 컴파일·제약 선언·
schema↔ORM round-trip·마이그레이션 파일 검사(전부 hermetic — DB 0).

검증 핵심:
  - problem_id nullable FK(적재 전 needs_review 후보는 NULL — NOT NULL FK면 검수 기록 불가).
  - elapsed_ms nullable + **server_default 없음**(미측정=NULL·0 날조 금지 — acceptance ④).
  - occurred_at(발생·nullable)/recorded_at(수신·NOT NULL now()) — EOS-48 분리.
  - **학생 소유 축 컬럼 부재 동결**(RPT-01 `test_defect_report_no_user_id.py` 선례) —
    erasure/retention/export 3종 배선 불요 판정의 기계 고정. privacy 스윕
    (`test_erasure_plan_completeness`)이 이 테이블에 green인 것과 양방향으로 맞물린다.
  - alembic 파일 존재·up/down 대칭·체인(c9bc2555282e 위 1체인 — 단일 head 유지).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from whymath_backend.db.base import Base
from whymath_backend.db.models.review_timer_event import ReviewTimerEvent
from whymath_backend.schema.review_timer import ReviewTimerEvent as SchemaReviewTimerEvent

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VERSIONS_DIR = _REPO_ROOT / "src" / "backend" / "alembic" / "versions"


def _full_schema() -> SchemaReviewTimerEvent:
    """모든 필드가 채워진 검증 schema 1건(round-trip 재료 — 반려+부기+계측)."""
    return SchemaReviewTimerEvent(
        event_id=uuid.uuid4(),
        review_session_id=uuid.uuid4(),
        cu_slug="quadratic-roots-001",
        problem_id=uuid.uuid4(),
        reviewer_id="kiki",
        event_type="finished",
        verdict="rejected",
        failure_code="F3",
        failure_note="2→3단계 비약",
        elapsed_ms=185_000,
        occurred_at=datetime(2026, 8, 31, 2, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 31, 2, 0, 3, tzinfo=UTC),
    )


class TestReviewTimerEventTable:
    def test_registered_in_metadata(self) -> None:
        """`review_timer_event`가 Base.metadata에 등록(모델 패키지 import 경유)."""
        import whymath_backend.db.models  # noqa: F401  # 패키지 __init__ 등록 경로 검증

        assert "review_timer_event" in Base.metadata.tables

    def test_pg_ddl_compiles_with_expected_shapes(self) -> None:
        """PG DDL 컴파일 — PK·problem FK·NOT NULL·recorded_at server_default."""
        ddl = str(CreateTable(ReviewTimerEvent.__table__).compile(dialect=postgresql.dialect()))
        assert "review_timer_event" in ddl
        assert "PRIMARY KEY (event_id)" in ddl
        assert "REFERENCES problem (problem_id)" in ddl
        assert "now()" in ddl  # recorded_at server_default(수신 시각)

    def test_required_columns_not_null(self) -> None:
        """세션·CU·행위자·유형·수신 시각은 NOT NULL(수집 정합 — 시각 미상 행 없음)."""
        columns = ReviewTimerEvent.__table__.columns
        for name in ("review_session_id", "cu_slug", "reviewer_id", "event_type", "recorded_at"):
            assert columns[name].nullable is False, f"review_timer_event.{name}은 NOT NULL"

    def test_problem_id_nullable_fk(self) -> None:
        """problem_id nullable FK — 미적재 후보(needs_review)는 NULL로 기록 가능해야
        스키마가 측정 실패를 제조하지 않는다(GenerationLog.problem_id 동형)."""
        column = ReviewTimerEvent.__table__.columns["problem_id"]
        assert column.nullable is True
        targets = {fk.target_fullname for fk in column.foreign_keys}
        assert targets == {"problem.problem_id"}

    def test_elapsed_ms_nullable_without_server_default(self) -> None:
        """acceptance ④ — 미측정=NULL. server_default가 있으면 0 날조 경로가 된다."""
        column = ReviewTimerEvent.__table__.columns["elapsed_ms"]
        assert column.nullable is True
        assert column.server_default is None

    def test_time_separation_columns(self) -> None:
        """EOS-48 — occurred_at(발생) nullable / recorded_at(수신) NOT NULL now()."""
        columns = ReviewTimerEvent.__table__.columns
        assert columns["occurred_at"].nullable is True
        assert columns["occurred_at"].server_default is None  # 발생 시각은 신고만(서버 날조 금지)
        assert columns["recorded_at"].nullable is False
        assert columns["recorded_at"].server_default is not None

    def test_review_session_id_is_correlation_not_fk(self) -> None:
        """세션 id는 상관 축 — 세션 정본 테이블 부재(FK 날조 금지·hint_id 선례)."""
        assert len(ReviewTimerEvent.__table__.columns["review_session_id"].foreign_keys) == 0

    def test_indexes_exist(self) -> None:
        """(review_session_id) 페어링 + (cu_slug, recorded_at DESC) CU 집계 인덱스."""
        index_names = {index.name for index in ReviewTimerEvent.__table__.indexes}
        assert "idx_review_timer_session" in index_names
        assert "idx_review_timer_cu" in index_names


class TestNoStudentAxis:
    """학생 소유 축 부재 동결 — RPT-01(`test_defect_report_no_user_id.py`) 선례.

    reviewer_id는 검수 *행위자*(content_provenance.approved_by 계열)이지 데이터 주체 소유
    축이 아니다 — privacy 스윕(`test_erasure_plan_completeness`)의 분류 기준을 그대로 따른다. 이 컬럼 집합이 유지되는 한 erasure/retention/export 3종 배선은
    불요하며, 학생 축 컬럼을 추가하는 순간 이 테스트와 완전성 스윕이 함께 red가 된다.
    """

    def test_orm_has_no_student_owner_column(self) -> None:
        columns = {col.key for col in sa.inspect(ReviewTimerEvent).mapper.column_attrs}
        forbidden = {"user_id", "student_id", "target_user_id"}
        assert columns & forbidden == set(), "검수자 텔레메트리에 학생 소유 축 컬럼 유입 금지"

    def test_not_in_erasure_plan_nor_exemptions(self) -> None:
        """삭제권 계획·허용목록 둘 다 밖(의도) + 스윕 소유 축 미보유 실측(추측 금지).

        완전성 스윕(`test_erasure_plan_completeness`)의 소유 축(SEC-35 이후 *`user_profile.
        user_id` FK 보유* ∪ *`_ERASURE_PLAN` 파생 컬럼명 보유* — 정본은 그 파일)을 이 테이블이
        어느 쪽으로도 보유하지 않으므로, 계획에도 허용목록에도 없이 스윕이 green이어야 한다 — 그 스윕 자체는 privacy 스위트가 실행한다
        (본 테스트는 판정 전제 3축을 지역화: 소유 컬럼 0·계획 밖·허용목록 밖). 학생 축 컬럼을
        추가하는 순간 위 컬럼 부재 테스트와 완전성 스윕이 **함께** red가 된다(양방향 변별력).
        """
        from whymath_backend.privacy.erasure import _ERASURE_PLAN, _ERASURE_PLAN_EXEMPTIONS

        owner_columns = frozenset({"user_id", "student_id", "target_user_id"})  # 스윕 정본 복제
        table = Base.metadata.tables["review_timer_event"]
        assert {c.name for c in table.columns} & owner_columns == set()
        planned = frozenset(model.__tablename__ for model, _ in _ERASURE_PLAN)
        assert "review_timer_event" not in planned
        assert "review_timer_event" not in _ERASURE_PLAN_EXEMPTIONS

    def test_schema_side_has_no_student_axis(self) -> None:
        """Pydantic 계약에도 학생 축 필드 없음(ORM과 이중 확인 — RPT-01 동형)."""
        fields = set(SchemaReviewTimerEvent.model_fields)
        assert fields & {"user_id", "student_id", "target_user_id"} == set()


class TestSchemaOrmRoundTrip:
    def test_round_trip_preserves_all_fields(self) -> None:
        """schema → from_schema → to_schema 왕복이 전 필드를 보존(교차 필드 재검증 포함)."""
        original = _full_schema()
        orm = ReviewTimerEvent.from_schema(original)
        assert orm.event_type == "finished"
        assert orm.failure_code == "F3"
        assert orm.elapsed_ms == 185_000
        restored = orm.to_schema()
        assert restored == original

    def test_from_schema_omits_none_recorded_at(self) -> None:
        """recorded_at=None(기본)은 속성 미설정 — server_default 적용(EOS-45 동형)."""
        schema = SchemaReviewTimerEvent(
            review_session_id=uuid.uuid4(),
            cu_slug="cu-x",
            reviewer_id="kiki",
            event_type="started",
        )
        orm = ReviewTimerEvent.from_schema(schema)
        assert "recorded_at" not in orm.__dict__

    def test_to_schema_rejects_corrupted_rejected_without_code(self) -> None:
        """DB 오염(반려인데 코드 없음)을 to_schema가 잡는다(침묵 통과 없음 — §4 안전망)."""
        orm = ReviewTimerEvent.from_schema(_full_schema())
        orm.failure_code = None  # 오염 시뮬레이션 — 반려코드 소실
        orm.failure_note = None
        with pytest.raises(Exception) as excinfo:
            orm.to_schema()
        assert "failure_code" in str(excinfo.value)


class TestMigrationFile:
    def test_migration_file_exists_with_symmetric_updown(self) -> None:
        """EOS-54 마이그레이션 파일 존재·up/down 대칭·FK·인덱스 2종·체인."""
        matches = list(_VERSIONS_DIR.glob("*review_timer_event.py"))
        assert len(matches) == 1, "EOS-54 마이그레이션 파일이 정확히 1개여야 한다"
        source = matches[0].read_text(encoding="utf-8")
        assert 'op.create_table(\n        "review_timer_event"' in source
        assert 'op.drop_table("review_timer_event")' in source
        assert '["problem.problem_id"]' in source
        assert '"idx_review_timer_session"' in source
        assert '"idx_review_timer_cu"' in source
        assert 'op.drop_index("idx_review_timer_cu"' in source
        assert 'op.drop_index("idx_review_timer_session"' in source
        # 체인: EOS-48 event_time_active_time(c9bc2555282e) 위에 1체인(단일 head 유지).
        assert 'down_revision: str | None = "c9bc2555282e"' in source

    def test_migration_does_not_fabricate_elapsed_default(self) -> None:
        """elapsed_ms에 server_default 부여 금지 — 마이그레이션 소스 레벨 동결(0 날조 방지)."""
        source = next(_VERSIONS_DIR.glob("*review_timer_event.py")).read_text(encoding="utf-8")
        elapsed_block = source.split('"elapsed_ms"')[1].split("sa.Column")[0]
        assert "server_default" not in elapsed_block


class TestEditAwareVerdictPersistence:
    """EOS-62 — 판정 3종화가 영속 계층에 **마이그레이션 없이** 안착하는가.

    `verdict`는 TEXT 컬럼이고 폐쇄 강제는 schema 쪽이다(모듈 docstring "DB는 TEXT" 판단).
    그래서 값 추가는 DDL 변경을 요구하지 않는다 — 그 사실을 주장으로 두지 않고 왕복으로
    실측한다(마이그레이션이 필요한데 안 만든 상태를 조용히 통과시키지 않기 위해).
    """

    def test_verdict_column_is_free_text_not_a_db_enum(self) -> None:
        """DB enum이면 값 추가에 마이그레이션이 필요하다 — TEXT임을 실측해 그 전제를 고정."""
        column = ReviewTimerEvent.__table__.columns["verdict"]
        assert isinstance(column.type, sa.Text)
        assert column.nullable is True

    def test_edit_approval_round_trips(self) -> None:
        original = SchemaReviewTimerEvent(
            review_session_id=uuid.uuid4(),
            cu_slug="quadratic-roots-002",
            reviewer_id="kiki",
            event_type="finished",
            verdict="approved_with_edit",
            failure_code="F7",
            failure_note="어휘 수준을 중3에 맞게 손질",
            elapsed_ms=90_000,
            occurred_at=datetime(2026, 9, 1, 2, 0, tzinfo=UTC),
        )
        restored = ReviewTimerEvent.from_schema(original).to_schema()
        assert restored.verdict == "approved_with_edit"
        assert restored.failure_code == "F7"

    def test_edit_approval_without_code_round_trips(self) -> None:
        """부기 선택 — 코드 없는 손질 승인도 영속·복원된다."""
        original = SchemaReviewTimerEvent(
            review_session_id=uuid.uuid4(),
            cu_slug="quadratic-roots-003",
            reviewer_id="kiki",
            event_type="finished",
            verdict="approved_with_edit",
            elapsed_ms=90_000,
        )
        restored = ReviewTimerEvent.from_schema(original).to_schema()
        assert restored.verdict == "approved_with_edit"
        assert restored.failure_code is None
