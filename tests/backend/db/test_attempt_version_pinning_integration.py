"""problem_attempt 버전 고정 *통합테스트* — EOS-47 (WHYMATH_RUN_INTEGRATION · 실 PostgreSQL).

마이그레이션 head가 적용된 실 PG에서 두 가지를 검증한다.

A. 리비전 `d6a2f8c4b1e7`의 *왕복*과 비파괴성 — 기존 시도 행이 컬럼 추가/제거를 지나도 보존되고, 새
   컬럼이 NULL로 시작하며(백필 없음), FK가 존재하지 않는 판을 거부한다.
B. **과거 기록 재현성(acceptance ③)** — 문항을 수정해 새 판이 서빙 기준이 된 *뒤에도* 이전 시도가 원래
   판을 가리킨다. 변별력을 위해 대조군 두 개를 함께 둔다: ①수정 뒤에 접수된 새 시도는 새 판을 가리킨다
   (고정이 '영원히 v1'이 아니라 접수 시점 포인터의 복사임을 보인다) ②문항 포인터(`problem.
   problem_version_id`)를 따라 조인하면 새 판이 나온다(= 고정이 없으면 이전 시도가 거짓 판을 가리켰을 것).

PG 미도달·리비전 미적용 시 graceful skip(`test_problem_version_migration_integration.py` 미러).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from whymath_backend.config import Settings

pytestmark = pytest.mark.integration

_REVISION = "d6a2f8c4b1e7"  # 이 슬라이스가 추가한 리비전(head)
_PREV_REVISION = "c5e9f3a7b1d4"  # 직전 리비전(downgrade -1 도착점)
_SENTINEL_UNIT = "U-EOS47-SENTINEL"  # 실 데이터와 충돌하지 않는 고유 단원 코드(식별·정리용)

_BACKEND_DIR = Path(__file__).resolve().parents[3] / "src" / "backend"
_ALEMBIC_DIR = _BACKEND_DIR / "alembic"

_V1_PAYLOAD = (
    '{"source_type": "자체생성", "subject": "공통", "curriculum_version": "2022_REVISION", '
    '"unit_codes": [], "question_text": "v1 본문"}'
)
_V2_PAYLOAD = _V1_PAYLOAD.replace("v1 본문", "v2 본문(해설 정정 후)")


# ── 공용 헬퍼 ────────────────────────────────────────────────────────────────────


def _sync_engine() -> object:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    if settings.db_disable_pool:
        return create_engine(settings.sync_database_url, poolclass=NullPool)
    return create_engine(settings.sync_database_url)


def _scalar(sql: str, **params: object) -> object:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            row = conn.execute(text(sql), params).first()
        return None if row is None else row[0]
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _execute(sql: str, **params: object) -> None:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(text(sql), params)
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _column_exists(table: str, column: str) -> bool:
    return (
        _scalar(
            "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c",
            t=table,
            c=column,
        )
        == 1
    )


def _reachable() -> bool:
    """실 PG 도달 + 이 리비전 적용(`problem_attempt.problem_version_id` 존재) 여부."""
    try:
        return _column_exists("problem_attempt", "problem_version_id")
    except Exception:
        return False


def _skip_if_unreachable() -> None:
    if not _reachable():
        pytest.skip(
            "PostgreSQL 미도달(또는 리비전 d6a2f8c4b1e7 미적용) — 통합 테스트 건너뜀 "
            "(WHYMATH_DATABASE_URL·alembic upgrade head 확인)"
        )


def _alembic_config() -> object:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", "")
    return cfg


def _cleanup_sentinel() -> None:
    """자식(attempt) → 버전 → 문항 순서로 정리. problem↔problem_version 상호 FK는 포인터부터 끊는다."""
    _execute(
        "DELETE FROM problem_attempt WHERE problem_id IN "
        "(SELECT problem_id FROM problem WHERE :u = ANY(unit_codes))",
        u=_SENTINEL_UNIT,
    )
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


def _seed_problem() -> uuid.UUID:
    pid = _scalar(
        "INSERT INTO problem (source_type, curriculum_version, valid_from_year, subject, "
        "unit_codes) VALUES ('자체생성', '2022_REVISION', 2022, '공통', ARRAY[:u]) "
        "RETURNING problem_id",
        u=_SENTINEL_UNIT,
    )
    assert isinstance(pid, uuid.UUID)
    return pid


def _insert_version(problem_id: uuid.UUID, version_no: int, payload: str, status: str) -> uuid.UUID:
    vid = _scalar(
        "INSERT INTO problem_version (problem_id, version_no, schema_version, status, payload) "
        "VALUES (:pid, :vno, 'problem-schema@1', CAST(:st AS problem_version_status_enum), "
        "CAST(:p AS jsonb)) RETURNING version_id",
        pid=problem_id,
        vno=version_no,
        st=status,
        p=payload,
    )
    assert isinstance(vid, uuid.UUID)
    return vid


def _point_problem_at(problem_id: uuid.UUID, version_id: uuid.UUID) -> None:
    _execute(
        "UPDATE problem SET problem_version_id = :v WHERE problem_id = :p",
        v=version_id,
        p=problem_id,
    )


@pytest.fixture(autouse=True)
def _sentinel() -> Iterator[None]:
    _skip_if_unreachable()
    _cleanup_sentinel()
    yield
    _cleanup_sentinel()


# ── A. 리비전 왕복·비파괴성 ──────────────────────────────────────────────────────


class TestMigrationRoundtrip:
    def test_head_has_both_columns_nullable_without_default(self) -> None:
        for col in ("problem_version_id", "evaluation_context"):
            assert _column_exists("problem_attempt", col), col
            nullable_and_default = _scalar(
                "SELECT is_nullable || '|' || coalesce(column_default, '') FROM "
                "information_schema.columns WHERE table_name = 'problem_attempt' "
                "AND column_name = :c",
                c=col,
            )
            assert (
                nullable_and_default == "YES|"
            ), f"{col}: nullable·무기본값이어야 한다(백필 금지) — {nullable_and_default}"

    def test_fk_rejects_a_version_that_does_not_exist(self) -> None:
        from sqlalchemy.exc import IntegrityError

        pid = _seed_problem()
        with pytest.raises(IntegrityError):
            _execute(
                "INSERT INTO problem_attempt (problem_id, problem_version_id) VALUES (:p, :v)",
                p=pid,
                v=uuid.uuid4(),
            )

    def test_roundtrip_preserves_existing_attempts_and_adds_null_columns(self) -> None:
        """revision-local 왕복(downgrade -1 → upgrade head): 기존 시도 행 무손상·새 컬럼 NULL(백필 없음)."""
        from alembic import command

        pid = _seed_problem()
        aid = _scalar(
            "INSERT INTO problem_attempt (problem_id, is_correct) VALUES (:p, true) "
            "RETURNING attempt_id",
            p=pid,
        )
        cfg = _alembic_config()
        try:
            command.downgrade(cfg, _PREV_REVISION)  # type: ignore[arg-type]
            assert not _column_exists("problem_attempt", "problem_version_id")
            assert not _column_exists("problem_attempt", "evaluation_context")
            # 컬럼이 사라져도 시도 행 자체는 그대로다.
            assert (
                _scalar("SELECT is_correct FROM problem_attempt WHERE attempt_id = :a", a=aid)
                is True
            )
        finally:
            command.upgrade(cfg, "head")  # type: ignore[arg-type]
        assert _column_exists("problem_attempt", "problem_version_id")
        assert _column_exists("problem_attempt", "evaluation_context")
        # 재적용 뒤에도 같은 행이 남아 있고 새 컬럼은 NULL이다 — 판을 날조해 채우지 않았다.
        assert (
            _scalar(
                "SELECT problem_version_id IS NULL AND evaluation_context IS NULL "
                "FROM problem_attempt WHERE attempt_id = :a",
                a=aid,
            )
            is True
        )


# ── B. 과거 기록 재현성 (acceptance ③) ───────────────────────────────────────────


async def _record_attempt(problem_id: uuid.UUID) -> uuid.UUID:
    """실 AsyncSession으로 헬퍼를 부르고 그 결과를 시도 행에 적재한다(서빙 경로와 같은 두 단계)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from whymath_backend.db.models.activity import ProblemAttempt
    from whymath_backend.l2.attempt_version_pin import resolve_attempt_version_pin

    engine = create_async_engine(Settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            pin = await resolve_attempt_version_pin(session, problem_id)
            attempt = ProblemAttempt(
                attempt_id=uuid.uuid4(),
                problem_id=problem_id,
                is_correct=True,
                problem_version_id=pin.problem_version_id,
                evaluation_context=pin.evaluation_context,
            )
            session.add(attempt)
            await session.commit()
            return attempt.attempt_id
    finally:
        await engine.dispose()


def _pinned_version_of(attempt_id: uuid.UUID) -> object:
    return _scalar(
        "SELECT problem_version_id FROM problem_attempt WHERE attempt_id = :a", a=attempt_id
    )


class TestReproducibilityAfterProblemEdit:
    async def test_attempt_keeps_pointing_at_the_version_it_was_taken_on(self) -> None:
        pid = _seed_problem()
        v1 = _insert_version(pid, 1, _V1_PAYLOAD, "PUBLISHED")
        _point_problem_at(pid, v1)

        before = await _record_attempt(pid)
        assert _pinned_version_of(before) == v1

        # 문항 수정: v1은 DEPRECATED로 내리고 v2를 발행해 서빙 기준 포인터를 옮긴다.
        _execute("UPDATE problem_version SET status = 'DEPRECATED' WHERE version_id = :v", v=v1)
        v2 = _insert_version(pid, 2, _V2_PAYLOAD, "PUBLISHED")
        _point_problem_at(pid, v2)

        # ① 핵심 — 수정 뒤에도 이전 시도는 v1을 가리키고, 그 판의 본문은 수정 전 모습이다.
        assert _pinned_version_of(before) == v1
        assert (
            _scalar(
                "SELECT pv.payload->>'question_text' FROM problem_attempt pa "
                "JOIN problem_version pv ON pv.version_id = pa.problem_version_id "
                "WHERE pa.attempt_id = :a",
                a=before,
            )
            == "v1 본문"
        )

        # ② 대조군 — 수정 뒤 접수된 새 시도는 v2를 가리킨다(고정은 '영원히 v1'이 아니다).
        after = await _record_attempt(pid)
        assert _pinned_version_of(after) == v2

        # ③ 대조군 — 문항 포인터를 따라 조인하면 이전 시도도 v2 본문으로 보인다. 고정이 없다면 이
        #    조인이 유일한 방법이었고, 그 답은 "학생이 풀지 않은 판"이라는 거짓이다.
        assert (
            _scalar(
                "SELECT pv.payload->>'question_text' FROM problem_attempt pa "
                "JOIN problem p ON p.problem_id = pa.problem_id "
                "JOIN problem_version pv ON pv.version_id = p.problem_version_id "
                "WHERE pa.attempt_id = :a",
                a=before,
            )
            == "v2 본문(해설 정정 후)"
        )

    async def test_problem_without_a_version_pins_none_but_records_context(self) -> None:
        """판이 없는 문항(현재 모든 문항의 상태) → id는 NULL, 환경 스냅숏은 기록된다."""
        pid = _seed_problem()

        aid = await _record_attempt(pid)

        assert _pinned_version_of(aid) is None
        assert (
            _scalar(
                "SELECT evaluation_context->>'curriculum_version' FROM problem_attempt "
                "WHERE attempt_id = :a",
                a=aid,
            )
            == "2022_REVISION"
        )

    async def test_unsourced_keys_are_stored_as_json_null_not_omitted(self) -> None:
        """출처 없는 키는 JSON null로 *존재*한다 — '모름'과 '이 계약 이전 행이라 키가 없음'이 구별된다."""
        pid = _seed_problem()

        aid = await _record_attempt(pid)

        assert (
            _scalar(
                "SELECT evaluation_context ? 'grading_policy_version' AND "
                "jsonb_typeof(evaluation_context->'grading_policy_version') = 'null' "
                "FROM problem_attempt WHERE attempt_id = :a",
                a=aid,
            )
            is True
        )
