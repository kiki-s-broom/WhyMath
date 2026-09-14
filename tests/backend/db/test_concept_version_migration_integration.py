"""concept_version 마이그레이션 *왕복* + PUBLISHED 불변성 트리거 *통합테스트* — EOS-49
(WHYMATH_RUN_INTEGRATION).

마이그레이션 head가 적용된 **실 PostgreSQL**에서 리비전 `67cf48ad3bce`(EOS-49)를
*revision-local 왕복*(downgrade -1 → upgrade head)으로 검증하고, 이어서 §7 Lifecycle의
PUBLISHED 불변성 트리거를 **실 발화**로 검증한다. CI `backend — 마이그레이션·통합 (실 PG)`
잡이 이미 `alembic downgrade base → upgrade head` 전구간 왕복을 돌리므로(ci.yml
backend-migrations), 이 테스트는 그 위에서 *이 리비전이 정확히 무엇을 더하고/되돌리는지*와
*트리거가 실제로 막는지*를 못 박는다. PG 미도달 시 graceful skip
(`test_concept_source_id_migration_integration.py` 미러).

검증(EOS-49 핵심):
  ① head에서 `concept_version` 테이블·`concept.current_published_version_id` 컬럼 존재.
  ② revision-local 왕복(downgrade → `3f5c83f51246` → upgrade head)이 부작용 없이 성립.
  ③ **PUBLISHED 불변성 트리거 — RED/GREEN 양면 실측**(CLAUDE.md house rule: 실패 주입 없이
     "가드가 있다"고 선언 금지):
     - GREEN(허용): DRAFT 행의 payload 수정은 성공한다(대조군 — 트리거가 *모든* UPDATE를
       막는 것이 아님을 증명).
     - GREEN(허용): PUBLISHED → DEPRECATED 전이(payload 불변)는 성공한다(대조군 — 트리거가
       상태 전이 *전체*를 막는 것이 아니라 DRAFT로의 역행만 막음을 증명).
     - RED(차단): PUBLISHED 행의 payload를 바꾸려는 UPDATE는 거부된다.
     - RED(차단): PUBLISHED → DRAFT 전이는 거부된다.

alembic은 `Config`(절대 script_location·주입 URL)로 프로그램 구동한다 — pytest rootdir·cwd와
무관하게 동작(자격증명 0 하드코딩 — Settings.database_url의 sync 형태 사용).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from whymath_backend.config import Settings

pytestmark = pytest.mark.integration

# 왕복·트리거 검증용 sentinel concept code(실 데이터와 충돌 않도록 9xx slug).
_SENTINEL_CODE = "HIGH-EOS49-901"
_REVISION = "67cf48ad3bce"  # 이 슬라이스가 추가한 리비전(head)
_PREV_REVISION = "3f5c83f51246"  # 직전 리비전(downgrade -1 도착점)

# alembic 디렉토리 절대 경로(src/backend/alembic) — 이 테스트 파일 기준 ../../../src/backend.
_BACKEND_DIR = Path(__file__).resolve().parents[3] / "src" / "backend"
_ALEMBIC_DIR = _BACKEND_DIR / "alembic"

_SAMPLE_PAYLOAD = (
    '{"name_ko": "왕복 sentinel", "level": "세부개념", "aliases": [], '
    '"cognitive_type": [], "behavior_skills": [], "is_signature_korean": false}'
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
    """실 PG 도달 + `concept_version` 테이블 존재(이 리비전 적용) 여부."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            conn.execute(text("SELECT count(*) FROM concept_version"))
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
    """절대 script_location·주입 URL로 구성한 alembic Config(cwd·rootdir 무관)."""
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", "")
    return cfg


def _table_exists(table: str) -> bool:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            found = conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
                {"t": table},
            ).first()
        return found is not None
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _column_exists(table: str, column: str) -> bool:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            found = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :table AND column_name = :col"
                ),
                {"table": table, "col": column},
            ).first()
        return found is not None
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _cleanup_sentinel() -> None:
    """concept_version(자식) → concept(부모) 순서로 sentinel 정리(FK 방향 준수)."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text("DELETE FROM concept_version WHERE concept_id = :code"),
                {"code": _SENTINEL_CODE},
            )
            conn.execute(text("DELETE FROM concept WHERE code = :code"), {"code": _SENTINEL_CODE})
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _seed_sentinel_concept() -> None:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text(
                    "INSERT INTO concept (code, name_ko, level, aliases) "
                    "VALUES (:code, :name, '세부개념', '{}'::text[])"
                ),
                {"code": _SENTINEL_CODE, "name": "EOS-49 왕복/트리거 sentinel"},
            )
    finally:
        engine.dispose()  # type: ignore[attr-defined]


class TestConceptVersionMigrationRoundtrip:
    """`67cf48ad3bce` 리비전-로컬 왕복 — 테이블·컬럼 추가/제거가 정확히 대칭인지."""

    def test_head_has_concept_version_table_and_columns(self) -> None:
        _skip_if_unreachable()
        # ① head 상태(CI가 upgrade head 완료): concept_version 테이블·concept의 신규 컬럼 존재.
        assert _table_exists("concept_version")
        assert _column_exists("concept", "current_published_version_id")
        for col in (
            "version_id",
            "concept_id",
            "entity_type",
            "version_no",
            "schema_version",
            "status",
            "previous_version_id",
            "change",
            "source",
            "governance",
            "integrity",
            "payload",
            "created_at",
            "published_at",
        ):
            assert _column_exists("concept_version", col), f"concept_version.{col} 부재"

    def test_downgrade_then_upgrade_removes_and_restores(self) -> None:
        _skip_if_unreachable()
        from alembic import command

        cfg = _alembic_config()
        try:
            # ② downgrade -1(EOS-49 역적용) — 테이블·컬럼 사라진다.
            command.downgrade(cfg, _PREV_REVISION)  # type: ignore[arg-type]
            assert not _table_exists("concept_version")
            assert not _column_exists("concept", "current_published_version_id")

            # ③ upgrade head(재적용) — 테이블·컬럼 복귀.
            command.upgrade(cfg, "head")  # type: ignore[arg-type]
            assert _table_exists("concept_version")
            assert _column_exists("concept", "current_published_version_id")
        finally:
            # 항상 head로 복원(다른 통합테스트가 head 전제).
            command.upgrade(cfg, "head")  # type: ignore[arg-type]


class TestPublishedImmutabilityTrigger:
    """§7 Lifecycle — PUBLISHED 불변성 트리거의 RED/GREEN 양면 실측(house rule)."""

    @pytest.fixture(autouse=True)
    def _sentinel(self) -> Iterator[None]:
        _skip_if_unreachable()
        _cleanup_sentinel()  # 이전 실행 잔재 방어적 제거.
        _seed_sentinel_concept()
        yield
        _cleanup_sentinel()

    def _insert_draft_version(self, version_no: int = 1) -> uuid.UUID:
        from sqlalchemy import text

        engine = _sync_engine()
        try:
            with engine.begin() as conn:  # type: ignore[attr-defined]
                row = conn.execute(
                    text(
                        "INSERT INTO concept_version "
                        "(concept_id, version_no, schema_version, status, payload) "
                        "VALUES (:cid, :vno, 'concept-schema@1', 'DRAFT', "
                        f"'{_SAMPLE_PAYLOAD}'::jsonb) "
                        "RETURNING version_id"
                    ),
                    {"cid": _SENTINEL_CODE, "vno": version_no},
                ).one()
            result: uuid.UUID = row.version_id
            return result
        finally:
            engine.dispose()  # type: ignore[attr-defined]

    def _set_status(self, version_id: uuid.UUID, status: str) -> None:
        from sqlalchemy import text

        engine = _sync_engine()
        try:
            with engine.begin() as conn:  # type: ignore[attr-defined]
                conn.execute(
                    text("UPDATE concept_version SET status = :status WHERE version_id = :vid"),
                    {"status": status, "vid": version_id},
                )
        finally:
            engine.dispose()  # type: ignore[attr-defined]

    def _publish(self, version_id: uuid.UUID) -> None:
        """DRAFT → IN_REVIEW → APPROVED → PUBLISHED(전부 허용된 순방향 전이)."""
        for status in ("IN_REVIEW", "APPROVED", "PUBLISHED"):
            self._set_status(version_id, status)

    # ── GREEN(대조군) — 트리거가 모든 UPDATE를 막지 않음을 증명 ──────────────
    def test_draft_payload_update_succeeds(self) -> None:
        """GREEN: DRAFT 행의 payload 수정은 허용된다(대조군 ①)."""
        from sqlalchemy import text

        vid = self._insert_draft_version()
        engine = _sync_engine()
        try:
            with engine.begin() as conn:  # type: ignore[attr-defined]
                conn.execute(
                    text(
                        "UPDATE concept_version SET payload = "
                        '\'{"name_ko": "수정됨", "level": "세부개념", "aliases": [], '
                        '"cognitive_type": [], "behavior_skills": [], '
                        '"is_signature_korean": false}\'::jsonb '
                        "WHERE version_id = :vid"
                    ),
                    {"vid": vid},
                )
            with engine.connect() as conn:  # type: ignore[attr-defined]
                row = conn.execute(
                    text(
                        "SELECT payload->>'name_ko' AS n FROM concept_version WHERE version_id = :vid"
                    ),
                    {"vid": vid},
                ).one()
            assert row.n == "수정됨"
        finally:
            engine.dispose()  # type: ignore[attr-defined]

    def test_published_to_deprecated_succeeds(self) -> None:
        """GREEN: PUBLISHED → DEPRECATED(payload 불변)는 허용된다(대조군 ② — 상태 전이
        *전체*가 막힌 게 아니라 DRAFT로의 역행만 막힘을 증명)."""
        from sqlalchemy import text

        vid = self._insert_draft_version()
        self._publish(vid)
        self._set_status(vid, "DEPRECATED")  # 예외 없이 성공해야 한다.

        engine = _sync_engine()
        try:
            with engine.connect() as conn:  # type: ignore[attr-defined]
                row = conn.execute(
                    text("SELECT status FROM concept_version WHERE version_id = :vid"),
                    {"vid": vid},
                ).one()
            assert row.status == "DEPRECATED"
        finally:
            engine.dispose()  # type: ignore[attr-defined]

    # ── RED(공격) — PUBLISHED 불변식 위반은 반드시 거부된다 ──────────────────
    def test_published_payload_update_is_rejected(self) -> None:
        """RED: PUBLISHED 행의 payload 변경 시도는 트리거가 거부한다."""
        import sqlalchemy.exc
        from sqlalchemy import text

        vid = self._insert_draft_version()
        self._publish(vid)

        engine = _sync_engine()
        try:
            with pytest.raises(sqlalchemy.exc.DBAPIError, match="immutable"):
                with engine.begin() as conn:  # type: ignore[attr-defined]
                    conn.execute(
                        text(
                            "UPDATE concept_version SET payload = "
                            '\'{"name_ko": "위반 시도", "level": "세부개념", '
                            '"aliases": [], "cognitive_type": [], "behavior_skills": [], '
                            '"is_signature_korean": false}\'::jsonb '
                            "WHERE version_id = :vid"
                        ),
                        {"vid": vid},
                    )
            # 거부 후에도 payload는 원본 그대로다(부분 적용 없음 — 트랜잭션 롤백).
            with engine.connect() as conn:  # type: ignore[attr-defined]
                row = conn.execute(
                    text(
                        "SELECT payload->>'name_ko' AS n FROM concept_version WHERE version_id = :vid"
                    ),
                    {"vid": vid},
                ).one()
            assert row.n == "왕복 sentinel"
        finally:
            engine.dispose()  # type: ignore[attr-defined]

    def test_published_to_draft_is_rejected(self) -> None:
        """RED: PUBLISHED → DRAFT 역행 시도는 트리거가 거부한다(§7 명문 금지)."""
        import sqlalchemy.exc

        vid = self._insert_draft_version()
        self._publish(vid)

        with pytest.raises(sqlalchemy.exc.DBAPIError, match="forbidden"):
            self._set_status(vid, "DRAFT")

        # 거부 후에도 상태는 PUBLISHED 그대로다.
        from sqlalchemy import text

        engine = _sync_engine()
        try:
            with engine.connect() as conn:  # type: ignore[attr-defined]
                row = conn.execute(
                    text("SELECT status FROM concept_version WHERE version_id = :vid"),
                    {"vid": vid},
                ).one()
            assert row.status == "PUBLISHED"
        finally:
            engine.dispose()  # type: ignore[attr-defined]
