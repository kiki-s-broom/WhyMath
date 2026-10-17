"""problem_version 마이그레이션 *왕복* + PUBLISHED 불변성 트리거 *통합테스트* — ARCH-31
(WHYMATH_RUN_INTEGRATION).

마이그레이션 head가 적용된 **실 PostgreSQL**에서 리비전 `c5e1f9a3b7d2`(ARCH-31)를
*revision-local 왕복*(downgrade -1 → upgrade head)으로 검증하고, 이어서 §7 Lifecycle의
PUBLISHED 불변성 트리거를 **실 발화**로 검증한다. CI `backend — 마이그레이션·통합 (실 PG)` 잡이
`alembic downgrade base → upgrade head` 전구간 왕복을 돌리므로, 이 테스트는 그 위에서 *이 리비전이
정확히 무엇을 더하고/되돌리는지*와 *트리거가 실제로 막는지*를 못 박는다. PG 미도달 시 graceful
skip(`test_concept_version_migration_integration.py` 미러).

검증(ARCH-31 핵심):
  ① head에서 `problem_version` 테이블·`problem.problem_version_id` 컬럼 존재, 상태 enum 7종.
  ② revision-local 왕복(downgrade → `b4d8e2a6c0f3` → upgrade head) 부작용 없음 + **기존 problem 행
     무손상·포인터 NULL 유지**(백필 없음 — 왕복이 행을 건드리지 않는다).
  ③ **PUBLISHED 불변성 트리거 — RED/GREEN 양면 실측**(CLAUDE.md house rule: 실패 주입 없이
     "가드가 있다"고 선언 금지):
     - GREEN(허용): DRAFT 행의 payload 수정(대조군 — 트리거가 *모든* UPDATE를 막는 것이 아님).
     - GREEN(허용): PUBLISHED → DEPRECATED 전이(payload 불변 — DRAFT 역행만 막힘).
     - RED(차단): PUBLISHED 행의 payload 변경 UPDATE.
     - RED(차단): PUBLISHED → DRAFT 전이.
  ④ 상호 FK 방향 — 존재하지 않는 version_id를 `problem.problem_version_id`에 넣으면 FK가 거부한다.

alembic은 `Config`(절대 script_location·주입 URL)로 프로그램 구동한다 — pytest rootdir·cwd와 무관.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from whymath_backend.config import Settings

pytestmark = pytest.mark.integration

_REVISION = "c5e1f9a3b7d2"  # 이 슬라이스가 추가한 리비전(head)
_PREV_REVISION = "b4d8e2a6c0f3"  # 직전 리비전(downgrade -1 도착점)

# 왕복·트리거 검증용 sentinel 단원 코드(실 데이터와 충돌 않도록 고유 값으로 식별·정리).
_SENTINEL_UNIT = "U-ARCH31-SENTINEL"

_BACKEND_DIR = Path(__file__).resolve().parents[3] / "src" / "backend"
_ALEMBIC_DIR = _BACKEND_DIR / "alembic"

_SAMPLE_PAYLOAD = (
    '{"source_type": "자체생성", "subject": "공통", "curriculum_version": "2022_REVISION", '
    '"unit_codes": [], "question_text": "왕복 sentinel"}'
)


def _sync_engine() -> object:
    """조회·시드·정리용 sync(psycopg) 엔진."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    if settings.db_disable_pool:
        return create_engine(settings.sync_database_url, poolclass=NullPool)
    return create_engine(settings.sync_database_url)


def _reachable() -> bool:
    """실 PG 도달 + `problem_version` 테이블 존재(이 리비전 적용) 여부."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            conn.execute(text("SELECT count(*) FROM problem_version"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _skip_if_unreachable() -> None:
    if not _reachable():
        pytest.skip(
            "PostgreSQL 미도달(또는 마이그레이션 미적용) — 통합 테스트 건너뜀 "
            "(WHYMATH_DATABASE_URL·alembic upgrade head 확인)"
        )


def _alembic_config() -> object:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", "")
    return cfg


def _scalar(sql: str, **params: object) -> object:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        # begin(): INSERT … RETURNING 시드도 커밋돼야 한다(connect()만 쓰면 닫을 때 롤백된다).
        with engine.begin() as conn:  # type: ignore[attr-defined]
            row = conn.execute(text(sql), params).first()
        return None if row is None else row[0]
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _table_exists(table: str) -> bool:
    return _scalar("SELECT 1 FROM information_schema.tables WHERE table_name = :t", t=table) == 1


def _column_exists(table: str, column: str) -> bool:
    return (
        _scalar(
            "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c",
            t=table,
            c=column,
        )
        == 1
    )


def _execute(sql: str, **params: object) -> None:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(text(sql), params)
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _cleanup_sentinel() -> None:
    """자식(problem_version) → 부모(problem) 순서로 sentinel 정리. 포인터는 먼저 끊는다(상호 FK)."""
    _execute(
        "UPDATE problem SET problem_version_id = NULL WHERE :u = ANY(unit_codes)",
        u=_SENTINEL_UNIT,
    )
    _execute(
        "DELETE FROM problem_version WHERE problem_id IN "
        "(SELECT problem_id FROM problem WHERE :u = ANY(unit_codes))",
        u=_SENTINEL_UNIT,
    )
    _execute("DELETE FROM problem WHERE :u = ANY(unit_codes)", u=_SENTINEL_UNIT)


def _seed_sentinel_problem() -> uuid.UUID:
    pid = _scalar(
        "INSERT INTO problem (source_type, curriculum_version, valid_from_year, subject, "
        "unit_codes) VALUES ('자체생성', '2022_REVISION', 2022, '공통', ARRAY[:u]) "
        "RETURNING problem_id",
        u=_SENTINEL_UNIT,
    )
    assert isinstance(pid, uuid.UUID)
    return pid


def _insert_draft_version(problem_id: uuid.UUID, version_no: int = 1) -> uuid.UUID:
    vid = _scalar(
        "INSERT INTO problem_version (problem_id, version_no, schema_version, status, payload) "
        "VALUES (:pid, :vno, 'problem-schema@1', 'DRAFT', CAST(:p AS jsonb)) "
        "RETURNING version_id",
        pid=problem_id,
        vno=version_no,
        p=_SAMPLE_PAYLOAD,
    )
    assert isinstance(vid, uuid.UUID)
    return vid


def _set_status(version_id: uuid.UUID, status: str) -> None:
    _execute(
        "UPDATE problem_version SET status = :s WHERE version_id = :v",
        s=status,
        v=version_id,
    )


def _status_of(version_id: uuid.UUID) -> object:
    return _scalar("SELECT status FROM problem_version WHERE version_id = :v", v=version_id)


class TestProblemVersionMigrationRoundtrip:
    """`c5e1f9a3b7d2` 리비전-로컬 왕복 — 테이블·컬럼 추가/제거가 정확히 대칭인지."""

    @pytest.fixture(autouse=True)
    def _sentinel(self) -> Iterator[None]:
        _skip_if_unreachable()
        _cleanup_sentinel()
        yield
        _cleanup_sentinel()

    def test_head_has_problem_version_table_and_columns(self) -> None:
        _skip_if_unreachable()
        assert _table_exists("problem_version")
        assert _column_exists("problem", "problem_version_id")
        for col in (
            "version_id",
            "problem_id",
            "entity_type",
            "version_no",
            "schema_version",
            "status",
            "previous_version_id",
            "change",
            "source",
            "governance",
            "integrity",
            "qa",
            "payload",
            "created_at",
            "published_at",
        ):
            assert _column_exists("problem_version", col), f"problem_version.{col} 부재"

    def test_status_enum_has_all_seven_labels(self) -> None:
        labels = _scalar(
            "SELECT array_agg(enumlabel::text ORDER BY enumsortorder) FROM pg_enum e "
            "JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = 'problem_version_status_enum'"
        )
        assert labels == [
            "DRAFT",
            "IN_REVIEW",
            "IN_QA",
            "APPROVED",
            "PUBLISHED",
            "DEPRECATED",
            "RETIRED",
        ]

    def test_existing_problem_rows_get_null_pointer_no_backfill(self) -> None:
        """백필 금지 — 기존/신규 problem 행의 포인터는 NULL이다."""
        pid = _seed_sentinel_problem()
        assert (
            _scalar("SELECT problem_version_id FROM problem WHERE problem_id = :p", p=pid) is None
        )
        assert (
            _scalar("SELECT count(*) FROM problem WHERE problem_version_id IS NOT NULL") == 0
        ), "백필 금지 위반 — 어떤 problem 행도 판을 미리 갖고 있으면 안 된다"

    def test_downgrade_then_upgrade_removes_and_restores_without_touching_rows(self) -> None:
        from alembic import command

        pid = _seed_sentinel_problem()
        cfg = _alembic_config()
        try:
            command.downgrade(cfg, _PREV_REVISION)  # type: ignore[arg-type]
            assert not _table_exists("problem_version")
            assert not _column_exists("problem", "problem_version_id")
            # enum 타입도 정리됐다(재-upgrade가 "type already exists"로 깨지지 않는 전제).
            assert (
                _scalar("SELECT 1 FROM pg_type WHERE typname = 'problem_version_status_enum'")
                is None
            )
            # 기존 problem 행은 왕복과 무관하게 그대로다.
            assert _scalar("SELECT 1 FROM problem WHERE problem_id = :p", p=pid) == 1

            command.upgrade(cfg, "head")  # type: ignore[arg-type]
            assert _table_exists("problem_version")
            assert _column_exists("problem", "problem_version_id")
            assert _scalar("SELECT 1 FROM problem WHERE problem_id = :p", p=pid) == 1
            assert (
                _scalar("SELECT problem_version_id FROM problem WHERE problem_id = :p", p=pid)
                is None
            )
        finally:
            command.upgrade(cfg, "head")  # type: ignore[arg-type]  # 다른 통합테스트가 head 전제


class TestPointerForeignKey:
    @pytest.fixture(autouse=True)
    def _sentinel(self) -> Iterator[None]:
        _skip_if_unreachable()
        _cleanup_sentinel()
        yield
        _cleanup_sentinel()

    def test_pointer_to_real_version_is_accepted(self) -> None:
        """GREEN(대조군): 실재하는 판을 가리키는 포인터는 허용된다."""
        pid = _seed_sentinel_problem()
        vid = _insert_draft_version(pid)
        _execute("UPDATE problem SET problem_version_id = :v WHERE problem_id = :p", v=vid, p=pid)
        assert _scalar("SELECT problem_version_id FROM problem WHERE problem_id = :p", p=pid) == vid

    def test_pointer_to_nonexistent_version_is_rejected(self) -> None:
        """RED: 존재하지 않는 version_id는 FK가 거부한다(느슨한 문자열 포인터가 아니다)."""
        import sqlalchemy.exc

        pid = _seed_sentinel_problem()
        with pytest.raises(sqlalchemy.exc.IntegrityError, match="foreign key"):
            _execute(
                "UPDATE problem SET problem_version_id = :v WHERE problem_id = :p",
                v=uuid.uuid4(),
                p=pid,
            )

    def test_version_for_nonexistent_problem_is_rejected(self) -> None:
        """RED: 존재하지 않는 problem_id의 판은 만들 수 없다(엔티티 FK)."""
        import sqlalchemy.exc

        with pytest.raises(sqlalchemy.exc.IntegrityError, match="foreign key"):
            _insert_draft_version(uuid.uuid4())

    def test_duplicate_version_no_is_rejected(self) -> None:
        """RED: 같은 problem_id에서 version_no 중복 불가(UNIQUE)."""
        import sqlalchemy.exc

        pid = _seed_sentinel_problem()
        _insert_draft_version(pid, 1)
        with pytest.raises(sqlalchemy.exc.IntegrityError, match="uq_problem_version_problem_no"):
            _insert_draft_version(pid, 1)


class TestPublishedImmutabilityTrigger:
    """§7 Lifecycle — PUBLISHED 불변성 트리거의 RED/GREEN 양면 실측(house rule)."""

    @pytest.fixture(autouse=True)
    def _sentinel(self) -> Iterator[None]:
        _skip_if_unreachable()
        _cleanup_sentinel()
        self.pid = _seed_sentinel_problem()
        yield
        _cleanup_sentinel()

    def _publish(self, version_id: uuid.UUID) -> None:
        """DRAFT → IN_REVIEW → IN_QA → APPROVED → PUBLISHED(전부 순방향)."""
        for status in ("IN_REVIEW", "IN_QA", "APPROVED", "PUBLISHED"):
            _set_status(version_id, status)

    # ── GREEN(대조군) — 트리거가 모든 UPDATE를 막지 않음을 증명 ──────────────
    def test_draft_payload_update_succeeds(self) -> None:
        vid = _insert_draft_version(self.pid)
        _execute(
            "UPDATE problem_version SET payload = jsonb_set(payload, '{question_text}', "
            "'\"수정됨\"') WHERE version_id = :v",
            v=vid,
        )
        assert (
            _scalar(
                "SELECT payload->>'question_text' FROM problem_version WHERE version_id = :v", v=vid
            )
            == "수정됨"
        )

    def test_published_to_deprecated_succeeds(self) -> None:
        vid = _insert_draft_version(self.pid)
        self._publish(vid)
        _set_status(vid, "DEPRECATED")  # 예외 없이 성공해야 한다.
        assert _status_of(vid) == "DEPRECATED"

    def test_published_qa_record_update_succeeds(self) -> None:
        """GREEN: PUBLISHED 행의 payload 외 컬럼(qa 기록)은 갱신 가능 — 불변 대상은 payload뿐."""
        vid = _insert_draft_version(self.pid)
        self._publish(vid)
        _execute(
            "UPDATE problem_version SET qa = CAST(:q AS jsonb) WHERE version_id = :v",
            q='{"qa_status": "PASSED"}',
            v=vid,
        )
        assert (
            _scalar("SELECT qa->>'qa_status' FROM problem_version WHERE version_id = :v", v=vid)
            == "PASSED"
        )

    # ── RED(공격) — PUBLISHED 불변식 위반은 반드시 거부된다 ──────────────────
    def test_published_payload_update_is_rejected(self) -> None:
        import sqlalchemy.exc

        vid = _insert_draft_version(self.pid)
        self._publish(vid)
        with pytest.raises(sqlalchemy.exc.DBAPIError, match="immutable"):
            _execute(
                "UPDATE problem_version SET payload = jsonb_set(payload, '{question_text}', "
                "'\"위반 시도\"') WHERE version_id = :v",
                v=vid,
            )
        # 거부 후에도 payload는 원본 그대로다(부분 적용 없음).
        assert (
            _scalar(
                "SELECT payload->>'question_text' FROM problem_version WHERE version_id = :v", v=vid
            )
            == "왕복 sentinel"
        )

    def test_published_to_draft_is_rejected(self) -> None:
        import sqlalchemy.exc

        vid = _insert_draft_version(self.pid)
        self._publish(vid)
        with pytest.raises(sqlalchemy.exc.DBAPIError, match="forbidden"):
            _set_status(vid, "DRAFT")
        assert _status_of(vid) == "PUBLISHED"
