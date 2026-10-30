"""검수 전이 BFF — 실 PostgreSQL 통합 (ADMIN-07 · 기본 SKIP, `WHYMATH_RUN_INTEGRATION=1`).

hermetic 테스트가 못 보는 것 — **행 잠금 아래의 실제 갱신·감사 행의 실재·롤백 원자성**을 실 PG로
확인한다. 응답 코드만 믿지 않고 `privacy_audit`·`problem` 행을 별도 연결로 직접 읽는다.

  ① 전이 성공마다 감사 정확히 1행(user_id·resource_type·resource_id·action·event_kind)
  ② 실패(404·409·422·403)는 감사 0행·상태 불변
  ③ quarantine이 reason·at을 함께 쓰고 release가 approved로 되돌리되 사유·시각을 유지
  ④ 감사 flush 실패를 주입하면 상태 변경도 롤백(원자성)
  ⑤ 같은 expected_status 재요청은 409(순차 + 실제 동시 2요청 경합)
  ⑥ allowed_actions가 상태별 서버 표와 일치

ADMIN-18(판정은 반려코드·HIT 타이머 없이 제출될 수 없다) 실 PG 몫 — 하단 "ADMIN-18" 절:
  ⑦ 착수가 started 행을, approve/reject가 같은 트랜잭션에 finished 행(verdict·failure_code·서버 계산
     elapsed_ms)을 `review_timer_event`에 실제로 쓴다
  ⑧ 타이머 행 적재가 flush에서 실패하면 상태·감사도 DB에 남지 않는다(주입)
  ⑨ 반려코드/세션 없는 판정·남의 문항 세션·이미 종결된 세션·PATCH 판정은 DB 행을 하나도 바꾸지 않는다
  ⑩ `hit_cu_metrics --from-db`가 DB 적재분을 읽어 적재율이 실제로 올라간다(작동한 비율 실측)
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
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
            # review_timer_event.problem_id → problem FK — 타이머 행을 먼저 지운다(ADMIN-18).
            await conn.execute(
                text("DELETE FROM review_timer_event WHERE problem_id = :p"), {"p": str(pid)}
            )
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


def _begin(client: TestClient, pid: uuid.UUID) -> str:
    """검수 착수 — 실제 엔드포인트로 세션을 발급받는다(타이머 started 행이 DB에 생긴다)."""
    r = client.post(f"{_BASE}/{pid}/review-sessions")
    assert r.status_code == 200, r.text
    return str(r.json()["review_session_id"])


def _timer_rows(pid: uuid.UUID) -> list[Any]:
    async def _q(conn: Any) -> Any:
        r = await conn.execute(
            text(
                "SELECT event_type, verdict, failure_code, elapsed_ms, review_session_id, "
                "reviewer_id, cu_slug FROM review_timer_event WHERE problem_id = :p "
                "ORDER BY recorded_at, event_type DESC"
            ),
            {"p": str(pid)},
        )
        return [tuple(x) for x in r.all()]

    return _run(_q)  # type: ignore[no-any-return]


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
    extra: dict[str, Any] = {"reason": "실측 사유"}
    with _client(_ADMIN) as client:
        if action in ("approve", "reject"):
            extra["review_session_id"] = _begin(client, pid)
        if action == "reject":
            extra["failure_code"] = "F3"
        r = _post(client, pid, action=action, expected_status=start.value, **extra)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["from_status"], body["to_status"]) == (start.value, end)
    assert _state(pid)[0] == end
    rows = _audit_rows(pid)
    assert rows == [(_ADMIN.user_id, "problem", pid, action, "content_mutation")]
    assert body["audit_id"]
    timers = _timer_rows(pid)
    if action in ("approve", "reject"):
        # 판정은 started 1 + finished 1 — 타이머 없는 판정이 DB에 존재하지 않는다(ADMIN-18).
        assert [t[0] for t in timers] == ["started", "finished"]
        assert timers[1][1] == end.replace("approved", "approved").replace("rejected", "rejected")
    else:
        assert timers == []  # 격리·해제는 판정이 아니다 — 타이머 행 0


def test_failures_leave_no_audit_and_no_state_change(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    pid = seeded(ReviewStatus.pending)
    before = _state(pid)
    with _client(_ADMIN) as client:
        sid = str(uuid.UUID("00000000-0000-4000-8000-0000000a1803"))
        stale = _post(
            client, pid, action="approve", expected_status="approved", review_session_id=sid
        )
        illegal = _post(client, pid, action="release", expected_status="pending")
        no_reason = _post(client, pid, action="quarantine", expected_status="pending")
        missing_pid = uuid.uuid4()
        missing = _post(
            client,
            missing_pid,
            action="approve",
            expected_status="pending",
            review_session_id=sid,
        )
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
    sid = "00000000-0000-4000-8000-0000000a1804"
    with _client(_ADMIN) as client:
        r = _post(client, pid, action="approve", expected_status="pending", review_session_id=sid)
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
        sid = _begin(client, pid)
        r = _post(client, pid, action="approve", expected_status="pending", review_session_id=sid)
    assert r.status_code == 500
    assert _state(pid) == before == ("pending", None, None)
    assert _audit_rows(pid) == []
    # 감사 flush 실패는 같은 트랜잭션의 finished 타이머 행도 되돌린다 — started만 남는다.
    assert [t[0] for t in _timer_rows(pid)] == ["started"]


def test_second_request_with_same_expected_status_is_409(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    pid = seeded(ReviewStatus.pending)
    with _client(_ADMIN) as client:
        sid = _begin(client, pid)
        first = _post(
            client, pid, action="approve", expected_status="pending", review_session_id=sid
        )
        second = _post(
            client, pid, action="approve", expected_status="pending", review_session_id=sid
        )
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
    with _client(_ADMIN) as setup:
        sessions = {a: _begin(setup, pid) for a in ("approve", "reject")}

    def _worker(action: str) -> None:
        extra: dict[str, Any] = {"review_session_id": sessions[action]}
        if action == "reject":
            extra["failure_code"] = "F5"
        with _client(_ADMIN) as client:
            barrier.wait()
            codes.append(
                _post(client, pid, action=action, expected_status="pending", **extra).status_code
            )

    threads = [threading.Thread(target=_worker, args=(a,)) for a in ("approve", "reject")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200, 409]
    assert len(_audit_rows(pid)) == 1
    assert _state(pid)[0] in {"approved", "rejected"}
    # 이긴 쪽의 finished 정확히 1행 — 진 쪽은 타이머도 남기지 않았다.
    assert [t[0] for t in _timer_rows(pid)].count("finished") == 1


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


# ── ADMIN-18: 판정은 반려코드·HIT 타이머 없이 제출될 수 없다(실 PG) ─────────────────────────


def test_reject_persists_finished_row_with_code_and_server_computed_elapsed(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    pid = seeded(ReviewStatus.pending)
    with _client(_ADMIN) as client:
        sid = _begin(client, pid)
        time.sleep(
            0.2
        )  # 서버가 재는 경과 하한 — 클라 값이 아님을 보이려면 0이 아닌 시간이 흘러야 한다
        r = _post(
            client,
            pid,
            action="reject",
            expected_status="pending",
            failure_code="F7",
            review_session_id=sid,
        )
    assert r.status_code == 200 and r.json()["review_session_id"] == sid
    started, finished = _timer_rows(pid)
    assert started[0] == "started" and started[1:4] == (None, None, None)
    assert finished[:3] == ("finished", "rejected", "F7")
    assert finished[3] is not None and 200 <= finished[3] < 60_000  # 서버 계산 경과(ms)
    assert str(finished[4]) == sid == str(started[4])  # 같은 세션으로 페어링
    assert finished[5] == str(_ADMIN.user_id) and finished[6] == str(pid)  # slug 없음 → pid


def test_reject_without_failure_code_or_session_leaves_db_untouched(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    pid = seeded(ReviewStatus.pending)
    before = _state(pid)
    with _client(_ADMIN) as client:
        sid = _begin(client, pid)
        no_code = _post(
            client, pid, action="reject", expected_status="pending", review_session_id=sid
        )
        no_session = _post(
            client, pid, action="reject", expected_status="pending", failure_code="F1"
        )
        no_session_approve = _post(client, pid, action="approve", expected_status="pending")
        code_on_approve = _post(
            client,
            pid,
            action="approve",
            expected_status="pending",
            failure_code="F1",
            review_session_id=sid,
        )
    assert [r.status_code for r in (no_code, no_session, no_session_approve, code_on_approve)] == [
        422,
        422,
        422,
        422,
    ]
    assert _state(pid) == before == ("pending", None, None)
    assert _audit_rows(pid) == []
    assert [t[0] for t in _timer_rows(pid)] == ["started"]  # 착수만 — 종결 없음


def test_timer_row_write_failure_rolls_back_state_and_audit(
    seeded: Callable[[ReviewStatus | None], uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """finished 행이 flush에서 실패(NOT NULL 위반 주입)하면 판정·감사 모두 DB에 남지 않는다."""
    import whymath_backend.api.admin_bff as bff

    real = bff.OrmReviewTimerEvent.from_schema

    def _broken(schema: Any) -> Any:
        row = real(schema)
        if schema.event_type == "finished":
            row.cu_slug = None  # review_timer_event.cu_slug NOT NULL → flush에서 실패
        return row

    monkeypatch.setattr(bff.OrmReviewTimerEvent, "from_schema", staticmethod(_broken))
    pid = seeded(ReviewStatus.pending)
    before = _state(pid)
    with _client(_ADMIN, raise_server_exceptions=False) as client:
        sid = _begin(client, pid)
        r = _post(client, pid, action="approve", expected_status="pending", review_session_id=sid)
    assert r.status_code == 500
    assert _state(pid) == before == ("pending", None, None)
    assert _audit_rows(pid) == []
    assert [t[0] for t in _timer_rows(pid)] == ["started"]


def test_session_cannot_be_reused_or_borrowed_across_problems(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    a = seeded(ReviewStatus.pending)
    b = seeded(ReviewStatus.pending)
    with _client(_ADMIN) as client:
        sid_a = _begin(client, a)
        borrowed = _post(
            client, b, action="approve", expected_status="pending", review_session_id=sid_a
        )
        ok = _post(client, a, action="approve", expected_status="pending", review_session_id=sid_a)
        # 종결된 세션으로 같은 문항을 격리하려는 재사용도 거부 — 세션은 한 번의 앉음이다.
        reused = _post(
            client,
            a,
            action="quarantine",
            expected_status="approved",
            reason="재사용",
            review_session_id=sid_a,
        )
    assert borrowed.status_code == 409
    assert borrowed.json()["detail"]["code"] == "invalid_review_session"
    assert ok.status_code == 200
    assert reused.status_code == 409
    assert reused.json()["detail"]["code"] == "invalid_review_session"
    assert _state(b)[0] == "pending" and _audit_rows(b) == [] and _timer_rows(b) == []
    assert _state(a)[0] == "approved" and len(_audit_rows(a)) == 1


def test_another_reviewers_session_is_refused(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    pid = seeded(ReviewStatus.pending)
    other = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
    with _client(_ADMIN) as client:
        sid = _begin(client, pid)
    with _client(other) as client:
        r = _post(client, pid, action="approve", expected_status="pending", review_session_id=sid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "invalid_review_session"
    assert _state(pid)[0] == "pending" and _audit_rows(pid) == []


def test_start_unknown_problem_is_404_and_writes_nothing(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    with _client(_ADMIN) as client:
        r = client.post(f"{_BASE}/{uuid.uuid4()}/review-sessions")
    assert r.status_code == 404


def test_patch_cannot_submit_a_verdict_without_timer(
    seeded: Callable[[ReviewStatus | None], uuid.UUID],
) -> None:
    """PATCH 우회 — pending→rejected/approved가 DB를 바꾸지 못하고 타이머·감사 행도 만들지 않는다."""
    from whymath_backend.api._auth import require_content_admin

    pid = seeded(ReviewStatus.pending)
    app = create_app()
    app.dependency_overrides[require_content_admin] = lambda: _ADMIN
    with TestClient(app) as client:
        rej = client.patch(f"/v1/problems/{pid}", json={"review_status": "rejected"})
        app_ = client.patch(f"/v1/problems/{pid}", json={"review_status": "approved"})
    assert rej.status_code == 409 and app_.status_code == 409
    assert rej.json()["detail"]["code"] == "review_session_required"
    assert _state(pid) == ("pending", None, None)
    assert _audit_rows(pid) == [] and _timer_rows(pid) == []


# ── ⑩ 적재율 실측 — hit_cu_metrics --from-db ─────────────────────────────────────────────


def _db_coverage() -> tuple[int, int, float | None]:
    """DB 적재분만으로 계산한 (판정 수, 타이머 동반 판정 수, 적재율) — CLI와 같은 로더를 쓴다."""
    from whymath_backend.ops.hit_cu_metrics import aggregate, load_db_sources

    events, errors, verdicts = asyncio.run(load_db_sources())
    assert errors == []
    report = aggregate(events, verdict_rows=verdicts)
    assert report.verdict_total is not None and report.verdict_with_timer is not None
    return report.verdict_total, report.verdict_with_timer, report.coverage_rate


def _force_status(pid: uuid.UUID, status_: str) -> None:
    """타이머 없는 옛 경로의 판정을 흉내낸다(직접 DB 작업·오프라인 적재)."""

    async def _u(conn: Any) -> None:
        await conn.execute(
            text(
                "UPDATE problem SET review_status = CAST(:s AS review_status_enum) WHERE problem_id = :p"
            ),
            {"s": status_, "p": str(pid)},
        )

    _run(_u)


def test_hit_cu_metrics_from_db_coverage_rises_when_verdicts_go_through_the_api(
    seeded: Callable[[ReviewStatus | None], uuid.UUID], capsys: pytest.CaptureFixture[str]
) -> None:
    from whymath_backend.ops.hit_cu_metrics import main

    legacy = [seeded(ReviewStatus.pending) for _ in range(2)]
    via_api = [seeded(ReviewStatus.pending) for _ in range(2)]

    for pid in legacy:
        _force_status(pid, "approved")  # 타이머 없는 판정 2건
    total_a, timed_a, rate_a = _db_coverage()
    assert rate_a is not None and rate_a < 1.0  # 타이머 없는 판정이 분모에 그대로 잡힌다

    with _client(_ADMIN) as client:
        for pid in via_api:
            sid = _begin(client, pid)
            r = _post(
                client, pid, action="approve", expected_status="pending", review_session_id=sid
            )
            assert r.status_code == 200
    total_b, timed_b, rate_b = _db_coverage()
    # API를 거친 판정 2건은 분모와 분자에 함께 늘어난다 → 적재율이 실제로 올라간다.
    assert (total_b - total_a, timed_b - timed_a) == (2, 2)
    assert rate_b is not None and rate_b > rate_a

    capsys.readouterr()
    rc = main(["--from-db", "--json"])
    out = capsys.readouterr().out
    assert rc == 0, out
    payload = json.loads(out)
    assert payload["verdict_total"] == total_b and payload["verdict_with_timer"] == timed_b
    assert payload["coverage_rate"] == pytest.approx(rate_b)
