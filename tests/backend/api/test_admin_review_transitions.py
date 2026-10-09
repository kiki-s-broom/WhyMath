"""검수 큐 목록·단건·전이 BFF 계약 동결 — hermetic (ADMIN-07 · ADMIN-18).

실 PG 의미(행 잠금·롤백·동시성)는 `test_admin_review_transitions_integration.py`가 본다. 여기서는
가짜 세션으로 **가드·검증·HTTP 계약**과 "실패 경로는 add/commit을 하지 않는다"를 고정한다.

ADMIN-18(검수 판정은 반려코드·HIT 타이머 없이 제출될 수 없다)의 hermetic 몫은 이 파일 하단
"ADMIN-18" 절이다: ①reject는 failure_code 없이 422 ②approve/reject는 review_session_id 없이 422
③성공 시 같은 트랜잭션에 finished 타이머 행(verdict·failure_code·서버 계산 elapsed_ms) ④세션 불일치
409 ⑤타이머 적재 실패 시 상태·감사 롤백 ⑥착수 엔드포인트가 started 행을 적재.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api import admin_bff
from whymath_backend.api._auth import get_current_user
from whymath_backend.api.admin_module_registry import DEMO_ACCOUNT_DENIED_DETAIL
from whymath_backend.api.auth import email_hash
from whymath_backend.api.demo_auth import DEMO_EMAIL
from whymath_backend.app import create_app
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.review_timer_event import ReviewTimerEvent as OrmTimerEvent
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import ReviewStatus, Role, SourceType, Subject
from whymath_backend.schema.review_timer import ReviewTimerEvent, ReviewTimerEventType

_ADMIN = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
_STUDENT = UserProfile(user_id=uuid.uuid4(), role=Role.STUDENT)
_DEMO_ADMIN = UserProfile(
    user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN, email_hash=email_hash(DEMO_EMAIL)
)
# parametrize id에 들어가므로 고정값이어야 한다 — 무작위면 xdist 워커마다 수집 목록이 달라 수집 단계에서 실패한다.
_PID = uuid.UUID("00000000-0000-4000-8000-000000000a07")
_BASE = "/v1/admin/review-queue/items"
# 고정 UUID — 무작위면 xdist 워커마다 parametrize 수집 목록이 달라진다.
_SID = uuid.UUID("00000000-0000-4000-8000-0000000a1801")
_OTHER_PID = uuid.UUID("00000000-0000-4000-8000-000000000a08")
_T0 = datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC)


def _problem(status_: ReviewStatus | None = ReviewStatus.pending) -> Problem:
    return Problem(
        problem_id=_PID,
        review_status=status_,
        source_type=SourceType.자체생성,
        subject=Subject.미적분,
        domain="미분",
        question_text="f(x)=x^2 의 도함수는?",
        choices=["x", "2x"],
        answer="2x",
        answer_explanation="멱함수 미분",
        difficulty_overall=0.55,
        review_score=0.71,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


class _Result:
    def __init__(self, *, one: Any = None, scalar: Any = None, rows: list[Any] | None = None):
        self._one, self._scalar, self._rows = one, scalar, rows or []

    def scalar_one_or_none(self) -> Any:
        return self._one

    def scalar(self) -> Any:
        return self._scalar

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _Result:
        return self


class FakeSession:
    def __init__(self, problem: Problem | None = None, results: list[_Result] | None = None):
        self.problem = problem
        self.results = list(results or [])
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.flush_error: Exception | None = None
        # ADMIN-18 — 이미 적재된 타이머 이벤트(세션 검증이 읽는다) · 타이머 행 add 실패 주입.
        self.timer_rows: list[OrmTimerEvent] = []
        self.timer_add_error: Exception | None = None

    @property
    def audits(self) -> list[Any]:
        return [o for o in self.added if isinstance(o, PrivacyAudit)]

    @property
    def timers(self) -> list[OrmTimerEvent]:
        return [o for o in self.added if isinstance(o, OrmTimerEvent)]

    async def execute(self, stmt: Any) -> _Result:
        if "review_timer_event" in str(stmt):
            return _Result(rows=list(self.timer_rows))
        if self.results:
            return self.results.pop(0)
        return _Result(one=self.problem)

    async def get(self, model: Any, pk: Any) -> Any:
        return self.problem

    def add(self, obj: Any) -> None:
        if isinstance(obj, OrmTimerEvent) and self.timer_add_error is not None:
            raise self.timer_add_error
        self.added.append(obj)

    async def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error
        for obj in self.audits:
            obj.audit_id = uuid.uuid4()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _client(user: UserProfile | None, fake: FakeSession | None = None) -> TestClient:
    app = create_app()
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    if fake is not None:

        async def _override() -> AsyncIterator[FakeSession]:
            yield fake

        app.dependency_overrides[get_session] = _override
    return TestClient(app)


def _post(client: TestClient, **body: Any) -> Any:
    return client.post(f"{_BASE}/{_PID}/transitions", json=body)


def _started_row(
    *,
    session_id: uuid.UUID = _SID,
    problem_id: uuid.UUID = _PID,
    reviewer: uuid.UUID | None = None,
    at: datetime = _T0,
    event_type: ReviewTimerEventType = ReviewTimerEventType.STARTED,
    verdict: str | None = None,
) -> OrmTimerEvent:
    """이미 DB에 있다고 가정하는 타이머 이벤트 행(검증 계약을 통과하는 형태로만 만든다)."""
    return OrmTimerEvent.from_schema(
        ReviewTimerEvent(
            review_session_id=session_id,
            cu_slug="cu-admin18",
            problem_id=problem_id,
            reviewer_id=str(reviewer or _ADMIN.user_id),
            event_type=event_type,
            verdict=verdict,  # type: ignore[arg-type]
            elapsed_ms=1000 if event_type is ReviewTimerEventType.FINISHED else None,
            occurred_at=at,
        )
    )


def _with_open_session(fake: FakeSession) -> FakeSession:
    fake.timer_rows.append(_started_row())
    return fake


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """서버 시계를 고정한다 — 경과(elapsed_ms)가 '착수 시각과 서버 현재 시각의 차'임을 단언하려면
    시계를 우리가 쥐어야 한다(90초 뒤 판정)."""
    monkeypatch.setattr(admin_bff, "_utcnow", lambda: _T0 + timedelta(seconds=90))


_ALL_ROUTES = (
    ("GET", _BASE),
    ("GET", f"{_BASE}/{_PID}"),
    ("POST", f"{_BASE}/{_PID}/transitions"),
    ("POST", f"{_BASE}/{_PID}/review-sessions"),
)


@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
def test_unauthenticated_is_401(method: str, path: str) -> None:
    with _client(None) as client:
        assert client.request(method, path, json={}).status_code == 401


@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
def test_student_is_403_and_demo_is_403_with_distinct_reason(method: str, path: str) -> None:
    fake = FakeSession(_problem())
    with _client(_STUDENT, fake) as client:
        r = client.request(method, path, json={})
    assert r.status_code == 403
    assert r.json()["detail"] != DEMO_ACCOUNT_DENIED_DETAIL
    with _client(_DEMO_ADMIN, fake) as client:
        r = client.request(method, path, json={})
    assert r.status_code == 403
    assert r.json()["detail"] == DEMO_ACCOUNT_DENIED_DETAIL
    assert fake.added == [] and fake.commits == 0


# ── 목록 ─────────────────────────────────────────────────────────────────────────────


def test_list_projects_light_rows_without_body() -> None:
    row = SimpleNamespace(
        problem_id=_PID,
        review_status=ReviewStatus.pending,
        subject=Subject.미적분,
        domain="미분",
        difficulty_overall=0.55,
        source_type=SourceType.자체생성,
        review_score=0.71,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    fake = FakeSession(results=[_Result(scalar=1), _Result(rows=[row])])
    with _client(_ADMIN, fake) as client:
        payload = client.get(_BASE).json()
    assert set(payload) == {"status", "total", "limit", "offset", "items"}
    assert payload["status"] == "pending"
    assert (payload["total"], payload["limit"], payload["offset"]) == (1, 50, 0)
    item = payload["items"][0]
    assert set(item) == {
        "problem_id",
        "review_status",
        "subject",
        "domain",
        "difficulty_overall",
        "source_type",
        "review_score",
        "created_at",
    }
    assert item["review_status"] == "pending" and item["review_score"] == 0.71
    assert "question_text" not in item


@pytest.mark.parametrize(
    "params",
    [{"status": "bogus"}, {"limit": 0}, {"limit": 101}, {"offset": -1}],
)
def test_list_rejects_bad_query_with_422(params: dict[str, Any]) -> None:
    with _client(_ADMIN, FakeSession()) as client:
        assert client.get(_BASE, params=params).status_code == 422


# ── 단건 ─────────────────────────────────────────────────────────────────────────────


def test_detail_shows_core_values_as_is_and_server_allowed_actions() -> None:
    with _client(_ADMIN, FakeSession(_problem(ReviewStatus.pending))) as client:
        payload = client.get(f"{_BASE}/{_PID}").json()
    assert payload["review_score"] == 0.71 and payload["difficulty_overall"] == 0.55
    assert payload["question_text"] == "f(x)=x^2 의 도함수는?"
    assert payload["allowed_actions"] == ["approve", "reject"]
    assert payload["quarantine_reason"] is None and payload["quarantined_at"] is None


def test_detail_unset_status_has_no_allowed_actions() -> None:
    with _client(_ADMIN, FakeSession(_problem(None))) as client:
        payload = client.get(f"{_BASE}/{_PID}").json()
    assert payload["review_status"] is None and payload["allowed_actions"] == []


def test_detail_unknown_is_404() -> None:
    with _client(_ADMIN, FakeSession(None)) as client:
        assert client.get(f"{_BASE}/{_PID}").status_code == 404


# ── 전이 ─────────────────────────────────────────────────────────────────────────────


def test_transition_success_writes_one_audit_and_commits_once() -> None:
    fake = _with_open_session(FakeSession(_problem(ReviewStatus.pending)))
    with _client(_ADMIN, fake) as client:
        r = _post(client, action="approve", expected_status="pending", review_session_id=str(_SID))
    assert r.status_code == 200
    body = r.json()
    assert (body["from_status"], body["to_status"]) == ("pending", "approved")
    assert body["audit_id"] == str(fake.audits[0].audit_id)
    assert body["review_session_id"] == str(_SID)
    # 감사 1행 + finished 타이머 1행(ADMIN-18) — 단일 커밋.
    assert len(fake.audits) == 1 and len(fake.timers) == 1
    assert fake.commits == 1 and fake.rollbacks == 0
    audit = fake.audits[0]
    assert (audit.action, audit.resource_type, audit.event_kind) == (
        "approve",
        "problem",
        "content_mutation",
    )
    assert audit.user_id == _ADMIN.user_id and audit.resource_id == _PID
    assert fake.problem is not None and fake.problem.review_status is ReviewStatus.approved


def test_transition_quarantine_writes_reason_and_time_together() -> None:
    fake = FakeSession(_problem(ReviewStatus.approved))
    with _client(_ADMIN, fake) as client:
        r = _post(client, action="quarantine", expected_status="approved", reason="  복수 정답  ")
    assert r.status_code == 200
    assert fake.problem is not None
    assert fake.problem.review_status is ReviewStatus.quarantined
    assert fake.problem.quarantine_reason == "복수 정답"
    assert fake.problem.quarantined_at is not None


def test_transition_release_keeps_reason_and_time() -> None:
    p = _problem(ReviewStatus.quarantined)
    p.quarantine_reason, p.quarantined_at = "원래 사유", datetime(2026, 8, 31, tzinfo=UTC)
    fake = FakeSession(p)
    with _client(_ADMIN, fake) as client:
        r = _post(client, action="release", expected_status="quarantined")
    assert r.status_code == 200
    assert p.review_status is ReviewStatus.approved
    assert p.quarantine_reason == "원래 사유"
    assert p.quarantined_at == datetime(2026, 8, 31, tzinfo=UTC)


def test_transition_missing_problem_is_404_without_audit() -> None:
    fake = FakeSession(None)
    with _client(_ADMIN, fake) as client:
        r = _post(client, action="approve", expected_status="pending", review_session_id=str(_SID))
    assert r.status_code == 404 and fake.added == [] and fake.commits == 0


def test_transition_stale_is_409_with_current_status() -> None:
    fake = FakeSession(_problem(ReviewStatus.approved))
    with _client(_ADMIN, fake) as client:
        r = _post(client, action="approve", expected_status="pending", review_session_id=str(_SID))
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "stale_status" and detail["current_status"] == "approved"
    assert fake.added == [] and fake.commits == 0
    assert fake.problem is not None and fake.problem.review_status is ReviewStatus.approved


def test_transition_illegal_is_409_with_current_status() -> None:
    fake = FakeSession(_problem(ReviewStatus.pending))
    with _client(_ADMIN, fake) as client:
        r = _post(client, action="release", expected_status="pending")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "illegal_transition" and detail["current_status"] == "pending"
    assert fake.added == [] and fake.commits == 0


def test_transition_unset_status_is_illegal_not_pending() -> None:
    """미설정 문항은 expected_status가 무엇이든 stale 또는 illegal — 승인 경로로 흘러들지 않는다."""
    fake = FakeSession(_problem(None))
    with _client(_ADMIN, fake) as client:
        r = _post(client, action="approve", expected_status="pending", review_session_id=str(_SID))
    assert r.status_code == 409 and r.json()["detail"]["current_status"] is None
    assert fake.added == [] and fake.commits == 0


@pytest.mark.parametrize(
    "body",
    [
        {"action": "quarantine", "expected_status": "approved"},
        {"action": "quarantine", "expected_status": "approved", "reason": "   "},
        {"action": "quarantine", "expected_status": "approved", "reason": "x" * 2001},
        {"action": "bogus", "expected_status": "pending"},
        {"action": "approve", "expected_status": "bogus"},
        {"action": "approve"},
        {"action": "approve", "expected_status": "pending", "extra": 1},
        {"action": "approve", "expected_status": "pending", "review_session_id": "not-a-uuid"},
    ],
)
def test_transition_body_validation_is_422_without_audit(body: dict[str, Any]) -> None:
    fake = FakeSession(_problem(ReviewStatus.approved))
    with _client(_ADMIN, fake) as client:
        r = _post(client, **body)
    assert r.status_code == 422 and fake.added == [] and fake.commits == 0


def test_transition_audit_failure_rolls_back_and_never_commits() -> None:
    fake = _with_open_session(FakeSession(_problem(ReviewStatus.pending)))
    fake.flush_error = RuntimeError("audit write failed")
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        client.app.dependency_overrides[get_current_user] = lambda: _ADMIN  # type: ignore[attr-defined]

        async def _override() -> AsyncIterator[FakeSession]:
            yield fake

        client.app.dependency_overrides[get_session] = _override  # type: ignore[attr-defined]
        r = _post(client, action="approve", expected_status="pending", review_session_id=str(_SID))
    assert r.status_code == 500
    assert fake.commits == 0 and fake.rollbacks == 1


# ── ADMIN-18: 판정은 반려코드·HIT 타이머 없이 제출될 수 없다 ────────────────────────────


def _transition(fake: FakeSession, **body: Any) -> Any:
    with _client(_ADMIN, fake) as client:
        return _post(client, **body)


def test_reject_with_failure_code_writes_finished_timer_row_in_same_transaction() -> None:
    fake = _with_open_session(FakeSession(_problem(ReviewStatus.pending)))
    r = _transition(
        fake,
        action="reject",
        expected_status="pending",
        failure_code="F3",
        review_session_id=str(_SID),
    )
    assert r.status_code == 200 and r.json()["to_status"] == "rejected"
    (timer,) = fake.timers
    assert timer.event_type == "finished" and timer.verdict == "rejected"
    assert timer.failure_code == "F3"
    assert timer.review_session_id == _SID and timer.problem_id == _PID
    assert timer.reviewer_id == str(_ADMIN.user_id)
    # 경과는 서버 시계(고정 시계: 착수 +90초)로 계산 — 클라 값도 0 날조도 아니다.
    assert timer.elapsed_ms == 90_000
    assert timer.cu_slug == "cu-admin18"  # 착수 행의 cu_slug를 그대로 잇는다(페어링)
    assert len(fake.audits) == 1 and fake.commits == 1 and fake.rollbacks == 0


def test_approve_writes_finished_timer_row_without_failure_code() -> None:
    fake = _with_open_session(FakeSession(_problem(ReviewStatus.pending)))
    r = _transition(fake, action="approve", expected_status="pending", review_session_id=str(_SID))
    assert r.status_code == 200
    (timer,) = fake.timers
    assert (timer.verdict, timer.failure_code, timer.elapsed_ms) == ("approved", None, 90_000)


@pytest.mark.parametrize("failure_code", [None, "F9", "f3", "", "코드"])
def test_reject_requires_a_valid_failure_code_422(failure_code: str | None) -> None:
    fake = _with_open_session(FakeSession(_problem(ReviewStatus.pending)))
    body: dict[str, Any] = {
        "action": "reject",
        "expected_status": "pending",
        "review_session_id": str(_SID),
    }
    if failure_code is not None:
        body["failure_code"] = failure_code
    r = _transition(fake, **body)
    assert r.status_code == 422
    assert fake.added == [] and fake.commits == 0
    assert fake.problem is not None and fake.problem.review_status is ReviewStatus.pending


@pytest.mark.parametrize(
    ("action", "expected"),
    [("approve", "pending"), ("reject", "pending")],
    ids=["approve", "reject"],
)
def test_verdict_without_review_session_is_422(action: str, expected: str) -> None:
    fake = FakeSession(_problem(ReviewStatus.pending))
    body: dict[str, Any] = {"action": action, "expected_status": expected}
    if action == "reject":
        body["failure_code"] = "F1"
    r = _transition(fake, **body)
    assert r.status_code == 422
    locs = [tuple(e["loc"]) for e in r.json()["detail"]]
    assert ("body", "review_session_id") in locs
    assert fake.added == [] and fake.commits == 0
    assert fake.problem is not None and fake.problem.review_status is ReviewStatus.pending


@pytest.mark.parametrize(
    ("action", "status_", "extra"),
    [
        ("approve", "pending", {}),
        ("quarantine", "approved", {"reason": "복수 정답"}),
        ("release", "quarantined", {}),
    ],
    ids=["approve", "quarantine", "release"],
)
def test_failure_code_on_non_reject_is_422_not_ignored(
    action: str, status_: str, extra: dict[str, Any]
) -> None:
    fake = _with_open_session(FakeSession(_problem(ReviewStatus(status_))))
    r = _transition(
        fake,
        action=action,
        expected_status=status_,
        failure_code="F1",
        review_session_id=str(_SID),
        **extra,
    )
    assert r.status_code == 422
    assert ("body", "failure_code") in [tuple(e["loc"]) for e in r.json()["detail"]]
    assert fake.added == [] and fake.commits == 0


@pytest.mark.parametrize(
    ("action", "status_", "extra"),
    [("quarantine", "approved", {"reason": "복수 정답"}), ("release", "quarantined", {})],
    ids=["quarantine", "release"],
)
def test_quarantine_and_release_need_no_session_and_write_no_timer(
    action: str, status_: str, extra: dict[str, Any]
) -> None:
    """격리·해제는 새 검수 판정이 아니다(ReviewVerdict에 값 없음) — 세션 없이 통과하고 타이머 행도
    만들지 않는다. HIT 분모에 사후 회수가 섞이지 않게 한다."""
    fake = FakeSession(_problem(ReviewStatus(status_)))
    r = _transition(fake, action=action, expected_status=status_, **extra)
    assert r.status_code == 200 and r.json()["review_session_id"] is None
    assert fake.timers == [] and len(fake.audits) == 1 and fake.commits == 1


def test_quarantine_with_a_session_validates_it_but_does_not_close_it() -> None:
    fake = _with_open_session(FakeSession(_problem(ReviewStatus.approved)))
    r = _transition(
        fake,
        action="quarantine",
        expected_status="approved",
        reason="복수 정답",
        review_session_id=str(_SID),
    )
    assert r.status_code == 200 and r.json()["review_session_id"] == str(_SID)
    assert fake.timers == []  # 판정이 아니므로 finished를 만들지 않는다(세션은 열린 채)


def test_quarantine_with_an_invalid_session_is_409() -> None:
    fake = FakeSession(_problem(ReviewStatus.approved))  # 열린 세션 없음
    r = _transition(
        fake,
        action="quarantine",
        expected_status="approved",
        reason="복수 정답",
        review_session_id=str(_SID),
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "invalid_review_session"
    assert fake.added == [] and fake.commits == 0


def _invalid_session_cases() -> list[tuple[str, Any]]:
    other_admin = uuid.UUID("00000000-0000-4000-8000-0000000a1802")
    return [
        ("no_such_session", []),
        ("other_problem", [_started_row(problem_id=_OTHER_PID)]),
        ("other_reviewer", [_started_row(reviewer=other_admin)]),
        (
            "already_finished",
            [
                _started_row(),
                _started_row(event_type=ReviewTimerEventType.FINISHED, verdict="approved"),
            ],
        ),
        ("aborted", [_started_row(), _started_row(event_type=ReviewTimerEventType.ABORTED)]),
        ("two_starts", [_started_row(), _started_row()]),
    ]


@pytest.mark.parametrize(
    "rows", [c[1] for c in _invalid_session_cases()], ids=[c[0] for c in _invalid_session_cases()]
)
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_invalid_review_session_is_409_and_leaves_no_trace(action: str, rows: list[Any]) -> None:
    fake = FakeSession(_problem(ReviewStatus.pending))
    fake.timer_rows = list(rows)
    body: dict[str, Any] = {
        "action": action,
        "expected_status": "pending",
        "review_session_id": str(_SID),
    }
    if action == "reject":
        body["failure_code"] = "F2"
    r = _transition(fake, **body)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "invalid_review_session" and detail["current_status"] == "pending"
    assert set(detail) == {"code", "message", "current_status"}
    assert fake.added == [] and fake.commits == 0
    assert fake.problem is not None and fake.problem.review_status is ReviewStatus.pending


def test_started_event_without_any_moment_cannot_fabricate_elapsed() -> None:
    """착수 시각을 알 수 없는 세션은 경과를 0으로 날조하지 않고 거부한다."""
    row = _started_row()
    row.occurred_at = None
    row.recorded_at = None  # type: ignore[assignment]
    fake = FakeSession(_problem(ReviewStatus.pending))
    fake.timer_rows = [row]
    r = _transition(fake, action="approve", expected_status="pending", review_session_id=str(_SID))
    assert r.status_code == 409 and fake.added == [] and fake.commits == 0


def test_clock_going_backwards_records_unmeasured_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_bff, "_utcnow", lambda: _T0 - timedelta(seconds=5))
    fake = _with_open_session(FakeSession(_problem(ReviewStatus.pending)))
    r = _transition(fake, action="approve", expected_status="pending", review_session_id=str(_SID))
    assert r.status_code == 200
    assert fake.timers[0].elapsed_ms is None  # 미측정 — 0 날조 금지


def test_timer_write_failure_rolls_back_state_and_audit() -> None:
    """타이머 적재가 실패하면 판정은 성립하지 않는다 — commit 0 · rollback 1 · 500."""
    fake = _with_open_session(FakeSession(_problem(ReviewStatus.pending)))
    fake.timer_add_error = RuntimeError("timer write failed")
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        client.app.dependency_overrides[get_current_user] = lambda: _ADMIN  # type: ignore[attr-defined]

        async def _override() -> AsyncIterator[FakeSession]:
            yield fake

        client.app.dependency_overrides[get_session] = _override  # type: ignore[attr-defined]
        r = _post(client, action="approve", expected_status="pending", review_session_id=str(_SID))
    assert r.status_code == 500
    assert fake.commits == 0 and fake.rollbacks == 1
    assert fake.audits == []  # 타이머 적재가 감사보다 앞이므로 감사도 쓰이지 않았다


# ── 착수 엔드포인트 ──────────────────────────────────────────────────────────────────────


def _start(fake: FakeSession) -> Any:
    with _client(_ADMIN, fake) as client:
        return client.post(f"{_BASE}/{_PID}/review-sessions")


def test_start_writes_exactly_one_started_row_and_returns_the_session() -> None:
    p = _problem()
    p.slug = "cu-admin18-slug"
    fake = FakeSession(p)
    r = _start(fake)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"review_session_id", "started_at"}
    (timer,) = fake.timers
    assert str(timer.review_session_id) == body["review_session_id"]
    assert timer.event_type == "started" and timer.cu_slug == "cu-admin18-slug"
    assert timer.problem_id == _PID and timer.reviewer_id == str(_ADMIN.user_id)
    assert timer.verdict is None and timer.failure_code is None and timer.elapsed_ms is None
    assert body["started_at"] == (_T0 + timedelta(seconds=90)).isoformat()
    assert fake.commits == 1 and fake.audits == []


def test_start_without_slug_falls_back_to_problem_id_as_cu_slug() -> None:
    fake = FakeSession(_problem())  # slug None
    assert _start(fake).status_code == 200
    assert fake.timers[0].cu_slug == str(_PID)


def test_start_unknown_problem_is_404_without_write() -> None:
    fake = FakeSession(None)
    assert _start(fake).status_code == 404
    assert fake.added == [] and fake.commits == 0


def test_start_write_failure_rolls_back() -> None:
    fake = FakeSession(_problem())
    fake.timer_add_error = RuntimeError("timer write failed")
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        client.app.dependency_overrides[get_current_user] = lambda: _ADMIN  # type: ignore[attr-defined]

        async def _override() -> AsyncIterator[FakeSession]:
            yield fake

        client.app.dependency_overrides[get_session] = _override  # type: ignore[attr-defined]
        r = client.post(f"{_BASE}/{_PID}/review-sessions")
    assert r.status_code == 500 and fake.commits == 0 and fake.rollbacks == 1
