"""검수 전이 BFF — 실 PostgreSQL 통합 (ADMIN-07 · 기본 SKIP, `WHYMATH_RUN_INTEGRATION=1`).

hermetic 테스트가 못 보는 것 — **행 잠금 아래의 실제 갱신·감사 행의 실재·롤백 원자성**을 실 PG로
확인한다. 응답 코드만 믿지 않고 `privacy_audit`·`problem` 행을 별도 연결로 직접 읽는다.

  ① 전이 성공마다 감사 정확히 1행(user_id·resource_type·resource_id·action·event_kind)
  ② 실패(404·409·422·403)는 감사 0행·상태 불변
  ③ quarantine이 reason·at을 함께 쓰고 release가 approved로 되돌리되 사유·시각을 유지
  ④ 감사 flush 실패를 주입하면 상태 변경도 롤백(원자성)
  ⑤ 같은 expected_status 재요청은 409(순차 + 실제 동시 2요청 경합)
  ⑥ allowed_actions가 상태별 서버 표와 일치
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from whymath_backend.api._auth import get_current_user
from whymath_backend.api.auth import email_hash
from whymath_backend.api.demo_auth import DEMO_EMAIL
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
_STUDENT = UserProfile(user_id=uuid.uuid4(), role=Role.STUDENT)
_DEMO = UserProfile(
    user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN, email_hash=email_hash(DEMO_EMAIL)
)
_BASE = "/v1/admin/review-queue/items"


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


def _seed(status_: ReviewStatus | None) -> uuid.UUID:
    pid = uuid.uuid4()
    row = Problem.from_schema(
        ProblemSchema(
            problem_id=pid,
            source_type=SourceType.자체생성,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.미적분,
            unit_codes=["CAL-INT-DEF"],
            question_text="ADMIN-07 통합 테스트 문항",
            review_status=status_,
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
def seeded() -> Iterator[Callable[[ReviewStatus | None], uuid.UUID]]:
    if not _pg_reachable():
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")
    made: list[uuid.UUID] = []

    def _make(status_: ReviewStatus | None) -> uuid.UUID:
        pid = _seed(status_)
        made.append(pid)
        return pid

    try:
        yield _make
    finally:
        _cleanup(made)


def _client(user: UserProfile, **kw: Any) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, **kw)


def _post(client: TestClient, pid: uuid.UUID, **body: Any) -> Any:
    return client.post(f"{_BASE}/{pid}/transitions", json=body)


_ALL_SUCCESS = [
    (ReviewStatus.pending, "approve", "approved"),
    (ReviewStatus.pending, "reject", "rejected"),
    (ReviewStatus.approved, "quarantine", "quarantined"),
    (ReviewStatus.quarantined, "release", "approved"),
]


@pytest.mark.parametrize(("start", "action", "end"), _ALL_SUCCESS)
def test_success_writes_state_and_exactly_one_audit_row(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
    start: ReviewStatus,
    action: str,
    end: str,
) -> None:
    pid = seeded(start)
    with _client(_ADMIN) as client:
        r = _post(client, pid, action=action, expected_status=start.value, reason="실측 사유")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["from_status"], body["to_status"]) == (start.value, end)
    assert _state(pid)[0] == end
    rows = _audit_rows(pid)
    assert rows == [(_ADMIN.user_id, "problem", pid, action, "content_mutation")]
    assert body["audit_id"]


def test_failures_leave_no_audit_and_no_state_change(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    pid = seeded(ReviewStatus.pending)
    before = _state(pid)
    with _client(_ADMIN) as client:
        stale = _post(client, pid, action="approve", expected_status="approved")
        illegal = _post(client, pid, action="release", expected_status="pending")
        no_reason = _post(client, pid, action="quarantine", expected_status="pending")
        missing_pid = uuid.uuid4()
        missing = _post(client, missing_pid, action="approve", expected_status="pending")
    with _client(_STUDENT) as client:
        student = _post(client, pid, action="approve", expected_status="pending")
    with _client(_DEMO) as client:
        demo = _post(client, pid, action="approve", expected_status="pending")

    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_status"
    assert illegal.status_code == 409 and illegal.json()["detail"]["code"] == "illegal_transition"
    assert no_reason.status_code == 422
    assert missing.status_code == 404
    assert student.status_code == 403 and demo.status_code == 403
    assert _state(pid) == before
    assert _audit_rows(pid) == [] and _audit_rows(missing_pid) == []


def test_unset_status_is_not_transitionable(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    pid = seeded(None)
    with _client(_ADMIN) as client:
        r = _post(client, pid, action="approve", expected_status="pending")
    assert r.status_code == 409 and r.json()["detail"]["current_status"] is None
    assert _state(pid)[0] is None and _audit_rows(pid) == []


def test_quarantine_writes_reason_and_time_and_release_keeps_them(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    pid = seeded(ReviewStatus.approved)
    with _client(_ADMIN) as client:
        q = _post(client, pid, action="quarantine", expected_status="approved", reason="복수 정답")
        assert q.status_code == 200
        status_, reason, at = _state(pid)
        assert (status_, reason) == ("quarantined", "복수 정답") and at is not None
        rel = _post(client, pid, action="release", expected_status="quarantined")
        assert rel.status_code == 200
    assert _state(pid) == ("approved", "복수 정답", at)
    assert [row[3] for row in _audit_rows(pid)] == ["quarantine", "release"]


def test_audit_write_failure_rolls_back_state(
    seeded: Callable[[ReviewStatus | None], uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """감사 행이 flush에서 실패(NOT NULL 위반 주입)하면 상태 변경도 DB에 남지 않는다."""
    import whymath_backend.api.admin_bff as bff

    real = bff.record_content_mutation_audit

    def _broken(*args: Any, **kwargs: Any) -> Any:
        row = real(*args, **kwargs)
        row.event_kind = None  # privacy_audit.event_kind NOT NULL → flush 단계에서 실패
        return row

    monkeypatch.setattr(bff, "record_content_mutation_audit", _broken)
    pid = seeded(ReviewStatus.pending)
    before = _state(pid)
    with _client(_ADMIN, raise_server_exceptions=False) as client:
        r = _post(client, pid, action="approve", expected_status="pending")
    assert r.status_code == 500
    assert _state(pid) == before == ("pending", None, None)
    assert _audit_rows(pid) == []


def test_second_request_with_same_expected_status_is_409(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    pid = seeded(ReviewStatus.pending)
    with _client(_ADMIN) as client:
        first = _post(client, pid, action="approve", expected_status="pending")
        second = _post(client, pid, action="approve", expected_status="pending")
    assert first.status_code == 200
    assert second.status_code == 409 and second.json()["detail"]["code"] == "stale_status"
    assert second.json()["detail"]["current_status"] == "approved"
    assert len(_audit_rows(pid)) == 1


def test_concurrent_requests_exactly_one_wins(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    """행 잠금 실증 — 같은 expected_status 두 요청이 동시에 와도 성공 1·409 1·감사 1행."""
    pid = seeded(ReviewStatus.pending)
    codes: list[int] = []
    barrier = threading.Barrier(2)

    def _worker(action: str) -> None:
        with _client(_ADMIN) as client:
            barrier.wait()
            codes.append(_post(client, pid, action=action, expected_status="pending").status_code)

    threads = [threading.Thread(target=_worker, args=(a,)) for a in ("approve", "reject")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200, 409]
    assert len(_audit_rows(pid)) == 1
    assert _state(pid)[0] in {"approved", "rejected"}


@pytest.mark.parametrize(
    ("status_", "expected"),
    [
        (ReviewStatus.pending, ["approve", "reject"]),
        (ReviewStatus.approved, ["quarantine"]),
        (ReviewStatus.rejected, []),
        (ReviewStatus.quarantined, ["release"]),
        (None, []),
    ],
)
def test_detail_allowed_actions_match_server_table(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
    status_: ReviewStatus | None,
    expected: list[str],
) -> None:
    pid = seeded(status_)
    with _client(_ADMIN) as client:
        payload = client.get(f"{_BASE}/{pid}").json()
    assert payload["allowed_actions"] == expected
    assert payload["review_status"] == (status_.value if status_ else None)


def test_list_filters_by_status_pages_stably(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    ids = [seeded(ReviewStatus.quarantined) for _ in range(3)]
    with _client(_ADMIN) as client:
        full = client.get(_BASE, params={"status": "quarantined", "limit": 100}).json()
        page1 = client.get(_BASE, params={"status": "quarantined", "limit": 1, "offset": 0}).json()
        page2 = client.get(_BASE, params={"status": "quarantined", "limit": 1, "offset": 1}).json()
    assert full["total"] >= 3
    got = [i["problem_id"] for i in full["items"]]
    assert {str(i) for i in ids} <= set(got)
    assert all(i["review_status"] == "quarantined" for i in full["items"])
    assert page1["total"] == full["total"] == page2["total"]
    assert page1["items"][0]["problem_id"] == got[0]
    assert page2["items"][0]["problem_id"] == got[1]
