"""PATCH /v1/problems/{id} 검수 상태 전이 — 실 PostgreSQL 통합 (ADMIN-16 · 기본 SKIP,
`WHYMATH_RUN_INTEGRATION=1`).

hermetic 테스트(`test_problems_patch_review_status.py`)가 못 보는 것 — **행 잠금 아래의 실제 갱신·
감사 행의 실재·롤백 원자성**을 실 PG로 확인한다. 응답 코드만 믿지 않고 `privacy_audit`·`problem`
행을 별도 연결로 직접 읽는다(`test_admin_review_transitions_integration.py`와 같은 관찰자 패턴).

  ① 불허 변경(5쌍)은 409이고 DB 상태·감사가 그대로다
  ② 합법 전이(4쌍)는 상태를 쓰고 감사 정확히 1행이며 그 동작이 전이 액션이다
  ③ 격리 시각은 클라이언트가 소급해 보내도 서버 시계로 기록된다 · 해제는 사유·시각을 보존한다
  ④ 상태 키가 없는 PATCH는 종전처럼 `update` 감사 1행이다
  ⑤ 감사 flush 실패를 주입하면 상태 변경도 롤백된다(원자성)
  ⑥ 같은 문항에 동시에 온 상태 변경 PATCH 두 건은 행 잠금으로 직렬화된다(성공 1·409 1·감사 1행)
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from whymath_backend.api._auth import require_content_admin
from whymath_backend.app import create_app
from whymath_backend.config import Settings
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.user import UserProfile
from whymath_backend.schema.enums import (
    Curriculum,
    ReviewStatus,
    Role,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema

pytestmark = pytest.mark.integration

_ADMIN = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
_OLD_REASON = "과거 격리 사유"
_OLD_AT = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)

P, A, R, Q = (
    ReviewStatus.pending,
    ReviewStatus.approved,
    ReviewStatus.rejected,
    ReviewStatus.quarantined,
)


def _url() -> str:
    return Settings(
        jwt_secret_key=SecretStr("integration-jwt-secret-0123456789abcdef")
    ).database_url


def _run(coro_fn: Callable[[Any], Any]) -> Any:
    """새 엔진·새 연결로 1회 실행 — 앱 세션과 분리된 '별도 관찰자'다."""

    async def _inner() -> Any:
        engine = create_async_engine(_url(), poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                return await coro_fn(conn)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _pg_reachable() -> bool:
    async def _ping(conn: Any) -> bool:
        await conn.execute(text("SELECT 1"))
        return True

    try:
        return bool(_run(_ping))
    except Exception:
        return False


def _seed(status_: ReviewStatus | None, *, with_record: bool = False) -> uuid.UUID:
    pid = uuid.uuid4()
    extra: dict[str, Any] = {}
    if with_record:
        extra = {"quarantine_reason": _OLD_REASON, "quarantined_at": _OLD_AT}
    row = Problem.from_schema(
        ProblemSchema(
            problem_id=pid,
            source_type=SourceType.자체생성,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.미적분,
            unit_codes=["CAL-INT-DEF"],
            question_text="ADMIN-16 통합 테스트 문항",
            review_status=status_,
            **extra,
        )
    )

    async def _go() -> None:
        engine = create_async_engine(_url(), poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                s.add(row)
                await s.commit()
        finally:
            await engine.dispose()

    asyncio.run(_go())
    return pid


def _state(pid: uuid.UUID) -> tuple[str | None, str | None, Any]:
    async def _q(conn: Any) -> Any:
        r = await conn.execute(
            text(
                "SELECT review_status::text, quarantine_reason, quarantined_at "
                "FROM problem WHERE problem_id = :p"
            ),
            {"p": str(pid)},
        )
        return tuple(r.one())

    return _run(_q)  # type: ignore[no-any-return]


def _audit_rows(pid: uuid.UUID) -> list[Any]:
    async def _q(conn: Any) -> Any:
        r = await conn.execute(
            text(
                "SELECT user_id, resource_type, resource_id, action, event_kind "
                "FROM privacy_audit WHERE resource_id = :p ORDER BY occurred_at"
            ),
            {"p": str(pid)},
        )
        return [tuple(x) for x in r.all()]

    return _run(_q)  # type: ignore[no-any-return]


def _cleanup(pids: list[uuid.UUID]) -> None:
    async def _d(conn: Any) -> None:
        for pid in pids:
            await conn.execute(
                text("DELETE FROM privacy_audit WHERE resource_id = :p"), {"p": str(pid)}
            )
            await conn.execute(text("DELETE FROM problem WHERE problem_id = :p"), {"p": str(pid)})

    _run(_d)


@pytest.fixture
def seeded() -> Iterator[Callable[..., uuid.UUID]]:
    if not _pg_reachable():
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")
    made: list[uuid.UUID] = []

    def _make(status_: ReviewStatus | None, *, with_record: bool = False) -> uuid.UUID:
        pid = _seed(status_, with_record=with_record)
        made.append(pid)
        return pid

    try:
        yield _make
    finally:
        _cleanup(made)


def _client(**kw: Any) -> TestClient:
    app = create_app()
    app.dependency_overrides[require_content_admin] = lambda: _ADMIN
    return TestClient(app, **kw)


def _patch(client: TestClient, pid: uuid.UUID, **body: Any) -> Any:
    return client.patch(f"/v1/problems/{pid}", json=body)


# ── ① 불허 변경은 409이고 DB가 그대로다 ───────────────────────────────────────────────

_ILLEGAL = [
    (R, "approved"),  # ADMIN-16 이전에는 통과하던 대표 우회
    (P, "quarantined"),
    (A, "pending"),
    (R, "quarantined"),
    (None, "pending"),
]


@pytest.mark.parametrize(
    ("start", "target"),
    _ILLEGAL,
    ids=[f"{'미설정' if s is None else s.value}->{t}" for s, t in _ILLEGAL],
)
def test_illegal_change_is_409_and_db_untouched(
    seeded: Callable[..., uuid.UUID], start: ReviewStatus | None, target: str
) -> None:
    pid = seeded(start)
    before = _state(pid)
    with _client() as client:
        r = _patch(client, pid, review_status=target, quarantine_reason="충분한 사유")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "illegal_transition"
    assert _state(pid) == before
    assert _audit_rows(pid) == []


# ── ② 합법 전이는 상태 + 감사 정확히 1행(동작 = 전이 액션) ─────────────────────────────

_LEGAL = [
    (P, "approved", "approve"),
    (P, "rejected", "reject"),
    (A, "quarantined", "quarantine"),
    (Q, "approved", "release"),
]


@pytest.mark.parametrize(("start", "target", "action"), _LEGAL, ids=[a for _, _, a in _LEGAL])
def test_legal_transition_writes_state_and_exactly_one_audit_row(
    seeded: Callable[..., uuid.UUID], start: ReviewStatus, target: str, action: str
) -> None:
    pid = seeded(start, with_record=start is Q)
    body: dict[str, Any] = {"review_status": target}
    if action == "quarantine":
        body["quarantine_reason"] = "실측 사유"
    with _client() as client:
        r = _patch(client, pid, **body)
    assert r.status_code == 200, r.text
    assert _state(pid)[0] == target
    assert _audit_rows(pid) == [(_ADMIN.user_id, "problem", pid, action, "content_mutation")]


# ── ③ 격리 시각은 서버 시계 · 해제는 기록 보존 ─────────────────────────────────────────


def test_quarantine_stamps_server_time_not_the_client_value(
    seeded: Callable[..., uuid.UUID],
) -> None:
    pid = seeded(A)
    with _client() as client:
        r = _patch(
            client,
            pid,
            review_status="quarantined",
            quarantine_reason="복수 정답",
            quarantined_at="2020-01-01T00:00:00Z",  # 소급 시도
        )
    assert r.status_code == 200, r.text
    status_, reason, at = _state(pid)
    assert (status_, reason) == ("quarantined", "복수 정답")
    assert at is not None and abs((datetime.now(UTC) - at).total_seconds()) < 300


def test_release_keeps_the_quarantine_record(seeded: Callable[..., uuid.UUID]) -> None:
    pid = seeded(Q, with_record=True)
    before = _state(pid)
    assert before[1] == _OLD_REASON
    with _client() as client:
        r = _patch(client, pid, review_status="approved")
    assert r.status_code == 200, r.text
    assert _state(pid) == ("approved", before[1], before[2])


# ── ④ 상태 키가 없는 PATCH는 종전 update ──────────────────────────────────────────────


def test_patch_without_status_key_is_a_plain_update(seeded: Callable[..., uuid.UUID]) -> None:
    pid = seeded(P)
    with _client() as client:
        r = _patch(client, pid, answer="42")
    assert r.status_code == 200, r.text
    assert _state(pid)[0] == "pending"
    assert [row[3] for row in _audit_rows(pid)] == ["update"]


# ── ⑤ 감사 flush 실패 → 상태 변경도 롤백 ──────────────────────────────────────────────


def test_audit_write_failure_rolls_back_state(
    seeded: Callable[..., uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """감사 행이 flush에서 실패(NOT NULL 위반 주입)하면 상태 변경도 DB에 남지 않는다."""
    import whymath_backend.api.problems as problems_module

    real = problems_module.record_content_mutation_audit

    def _broken(*args: Any, **kwargs: Any) -> Any:
        row = real(*args, **kwargs)
        row.event_kind = None  # privacy_audit.event_kind NOT NULL → 커밋 flush에서 실패
        return row

    monkeypatch.setattr(problems_module, "record_content_mutation_audit", _broken)
    pid = seeded(P)
    before = _state(pid)
    with _client(raise_server_exceptions=False) as client:
        r = _patch(client, pid, review_status="approved")
    assert r.status_code != 200, r.text
    assert _state(pid) == before == ("pending", None, None)
    assert _audit_rows(pid) == []


# ── ⑥ 행 잠금 — 동시 상태 변경 두 건은 직렬화된다 ─────────────────────────────────────


def test_concurrent_status_patches_exactly_one_wins(seeded: Callable[..., uuid.UUID]) -> None:
    """같은 pending 문항에 approve/reject를 동시에 보내면 성공 1·409 1·감사 1행이다.

    잠금이 없으면 두 요청이 모두 낡은 `pending`을 읽고 각자 합법이라 판정해 둘 다 200이 되고
    감사가 2행 남는다 — 이 단언이 그 형태를 잡는다.
    """
    pid = seeded(P)
    codes: list[int] = []
    barrier = threading.Barrier(2)

    def _worker(target: str) -> None:
        with _client() as client:
            barrier.wait()
            codes.append(_patch(client, pid, review_status=target).status_code)

    threads = [threading.Thread(target=_worker, args=(t,)) for t in ("approved", "rejected")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200, 409]
    assert len(_audit_rows(pid)) == 1
    assert _state(pid)[0] in {"approved", "rejected"}
