"""검수 큐 목록·단건·전이 BFF 계약 동결 — hermetic (ADMIN-07).

실 PG 의미(행 잠금·롤백·동시성)는 `test_admin_review_transitions_integration.py`가 본다. 여기서는
가짜 세션으로 **가드·검증·HTTP 계약**과 "실패 경로는 add/commit을 하지 않는다"를 고정한다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api._auth import get_current_user
from whymath_backend.api.admin_module_registry import DEMO_ACCOUNT_DENIED_DETAIL
from whymath_backend.api.auth import email_hash
from whymath_backend.api.demo_auth import DEMO_EMAIL
from whymath_backend.app import create_app
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import ReviewStatus, Role, SourceType, Subject

_ADMIN = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
_STUDENT = UserProfile(user_id=uuid.uuid4(), role=Role.STUDENT)
_DEMO_ADMIN = UserProfile(
    user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN, email_hash=email_hash(DEMO_EMAIL)
)
# parametrize id에 들어가므로 고정값이어야 한다 — 무작위면 xdist 워커마다 수집 목록이 달라 수집 단계에서 실패한다.
_PID = uuid.UUID("00000000-0000-4000-8000-000000000a07")
_BASE = "/v1/admin/review-queue/items"


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


class FakeSession:
    def __init__(self, problem: Problem | None = None, results: list[_Result] | None = None):
        self.problem = problem
        self.results = list(results or [])
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.flush_error: Exception | None = None

    async def execute(self, stmt: Any) -> _Result:
        if self.results:
            return self.results.pop(0)
        return _Result(one=self.problem)

    async def get(self, model: Any, pk: Any) -> Any:
        return self.problem

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error
        for obj in self.added:
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


_ALL_ROUTES = (
    ("GET", _BASE),
    ("GET", f"{_BASE}/{_PID}"),
    ("POST", f"{_BASE}/{_PID}/transitions"),
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
    fake = FakeSession(_problem(ReviewStatus.pending))
    with _client(_ADMIN, fake) as client:
        r = _post(client, action="approve", expected_status="pending")
    assert r.status_code == 200
    body = r.json()
    assert (body["from_status"], body["to_status"]) == ("pending", "approved")
    assert body["audit_id"] == str(fake.added[0].audit_id)
    assert len(fake.added) == 1 and fake.commits == 1 and fake.rollbacks == 0
    audit = fake.added[0]
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
        r = _post(client, action="approve", expected_status="pending")
    assert r.status_code == 404 and fake.added == [] and fake.commits == 0


def test_transition_stale_is_409_with_current_status() -> None:
    fake = FakeSession(_problem(ReviewStatus.approved))
    with _client(_ADMIN, fake) as client:
        r = _post(client, action="approve", expected_status="pending")
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
        r = _post(client, action="approve", expected_status="pending")
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
    ],
)
def test_transition_body_validation_is_422_without_audit(body: dict[str, Any]) -> None:
    fake = FakeSession(_problem(ReviewStatus.approved))
    with _client(_ADMIN, fake) as client:
        r = _post(client, **body)
    assert r.status_code == 422 and fake.added == [] and fake.commits == 0


def test_transition_audit_failure_rolls_back_and_never_commits() -> None:
    fake = FakeSession(_problem(ReviewStatus.pending))
    fake.flush_error = RuntimeError("audit write failed")
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        client.app.dependency_overrides[get_current_user] = lambda: _ADMIN  # type: ignore[attr-defined]

        async def _override() -> AsyncIterator[FakeSession]:
            yield fake

        client.app.dependency_overrides[get_session] = _override  # type: ignore[attr-defined]
        r = _post(client, action="approve", expected_status="pending")
    assert r.status_code == 500
    assert fake.commits == 0 and fake.rollbacks == 1
