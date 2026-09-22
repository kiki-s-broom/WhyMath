"""Admin BFF read-only 계약 동결 (ADMIN-05).

동결 항목과 **각 항목이 없으면 통과해 버리는 오구현**
--------------------------------------------------
① 무인증 401 / ② 무권한 403 — 한쪽만 보면 "전부 막힌다"·"전부 열린다" 양쪽이 통과한다.
③ **데모 계정 403** — 04 §4 "데모 토큰 절대 금지". 역할이 `CONTENT_ADMIN`이어도 막혀야 하므로
   *역할 미달과 다른 사유 문자열*로 구분한다. 같은 문자열이면 "데모라서 막혔는지 역할이 모자라
   막혔는지"를 테스트가 알 수 없고, 그러면 데모 차단의 작동을 확인할 방법이 없다.
④ **쓰기 0 동결** — `/v1/admin/*`에 GET 아닌 메서드가 하나도 없다(acceptance ③). 라우트 수를
   함께 단언한다: 표면이 통째로 사라져도 "비-GET 0건"은 참이므로, 분모 없이는 공허하다.
⑤ **집계에 PII 부재** — 목록 응답 필드 집합을 통째로 동결한다. 필드가 하나 새면 즉시 RED.
⑥ **단건 마스킹 + 감사 1행** — 이메일 해시류가 응답에 없고, `record_admin_access_audit`이
   실제로 행을 만든다(SEC-29가 남겨 둔 함수의 첫 호출부).
⑦ **측정 실패 ≠ 0건** — 비용·검수 큐가 원천 부재를 `state`로 구분한다(04 §2 원칙6). 이것이
   없으면 Langfuse가 죽은 회차와 비용이 0인 회차가 같은 화면이 된다.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api._auth import get_current_user
from whymath_backend.api.admin_bff import mask_nickname
from whymath_backend.api.admin_module_registry import DEMO_ACCOUNT_DENIED_DETAIL
from whymath_backend.api.auth import email_hash
from whymath_backend.api.demo_auth import DEMO_EMAIL
from whymath_backend.app import create_app
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import Role

_ADMIN = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
_STUDENT = UserProfile(user_id=uuid.uuid4(), role=Role.STUDENT)
#: 데모 계정 — 역할은 **관리자**다. 역할 게이트가 아니라 데모 판정이 막는지 보려면 그래야 한다.
_DEMO_ADMIN = UserProfile(
    user_id=uuid.uuid4(),
    role=Role.CONTENT_ADMIN,
    email_hash=email_hash(DEMO_EMAIL),
)

_READ_PATHS = (
    "/v1/admin/models",
    "/v1/admin/costs",
    "/v1/admin/review-queue",
    "/v1/admin/users",
)


class _Result:
    def __init__(self, rows: list[Any] | None = None, scalar: Any = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar(self) -> Any:
        return self._scalar


class FakeSession:
    """`execute` 결과를 순서대로 돌려주는 최소 세션. 커밋·추가를 기록한다."""

    def __init__(self, results: list[_Result] | None = None, got: Any = None) -> None:
        self._results = list(results or [])
        self._got = got
        self.added: list[Any] = []
        self.committed = False

    async def execute(self, stmt: Any) -> _Result:
        return self._results.pop(0) if self._results else _Result()

    async def get(self, model: Any, pk: Any) -> Any:
        return self._got

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:  # pragma: no cover - 실패 경로 미사용
        return None


def _client(user: UserProfile | None, fake: FakeSession | None = None) -> TestClient:
    app = create_app()
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    if fake is not None:

        async def _override() -> Iterator[FakeSession]:
            yield fake

        app.dependency_overrides[get_session] = _override
    return TestClient(app)


# ── ① 무인증 · ② 무권한 · ③ 데모 ──────────────────────────────────────────────────


@pytest.mark.parametrize("path", _READ_PATHS)
def test_unauthenticated_is_401(path: str) -> None:
    with _client(None) as client:
        assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", _READ_PATHS)
def test_student_role_is_403(path: str) -> None:
    with _client(_STUDENT) as client:
        response = client.get(path)
    assert response.status_code == 403
    # 역할 미달 사유이지 데모 사유가 아니다 — 두 경로가 섞이지 않음을 함께 동결한다.
    assert response.json()["detail"] != DEMO_ACCOUNT_DENIED_DETAIL


@pytest.mark.parametrize("path", _READ_PATHS)
def test_demo_account_is_403_even_with_admin_role(path: str) -> None:
    """③ 역할이 충분해도 데모 계정이면 막힌다 — 이 검사가 데모 차단의 유일한 증거다."""
    with _client(_DEMO_ADMIN) as client:
        response = client.get(path)
    assert response.status_code == 403
    assert response.json()["detail"] == DEMO_ACCOUNT_DENIED_DETAIL


def test_non_demo_admin_is_not_blocked_by_demo_rule() -> None:
    """대조군 — 데모 판정이 모든 관리자를 막는 무차별 차단이 아님을 보인다."""
    with _client(_ADMIN, FakeSession()) as client:
        response = client.get("/v1/admin/users")
    assert response.status_code == 200


def test_mask_nickname_distinguishes_none_from_empty() -> None:
    """빈 닉네임을 None으로 접으면 '없음'과 '미설정'이 같아진다."""
    assert mask_nickname(None) is None
    assert mask_nickname("") == ""
    assert mask_nickname("김와이") == "김***"


def test_models_endpoint_reports_status_without_raising() -> None:
    """모델 상태 200 경로 — 추론 서버가 없어도 **500이 아니라 상태로** 답한다.

    401/403만 검사하면 이 라우트는 "막히는 것"만 증명되고 *작동하는지*는 아무도 안 본다
    (declared-unwired 감사가 정확히 그 미도달을 잡았다). 테스트 환경에는 Ollama가 없으므로
    `reachable=False`가 정상이고, 그 상태에서 `error`가 채워지거나 모델이 빈 목록인 것이
    기대 결과다 — 여기서 500이 나면 운영자는 "서버가 죽었다"와 "모델이 없다"를 구분할 수 없다.
    """
    with _client(_ADMIN, FakeSession()) as client:
        response = client.get("/v1/admin/models")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "ready",
        "reachable",
        "models",
        "missing",
        "error",
        "cloud_configured",
        "cloud_reachable",
        "cloud_error",
    }
    assert isinstance(payload["reachable"], bool)
    # 클라우드 미측정은 False가 아니라 None으로 남는다(ARCH-57) — 둘이 같으면 "도달 불가"와
    # "안 물어봤다"가 한 화면이 된다.
    assert payload["cloud_reachable"] is None or isinstance(payload["cloud_reachable"], bool)


# ── ④ 쓰기 0 동결 ────────────────────────────────────────────────────────────────


def test_admin_surface_is_read_only() -> None:
    """Phase A는 read-only — 비-GET 0건 **이면서** 라우트가 실재함을 함께 단언한다."""
    from whymath_backend.ops.declared_unwired_audit import walk_routes

    app = create_app()
    admin_routes = [
        (sorted(getattr(r, "methods", None) or ()), r.path)
        for r in walk_routes(app.routes)
        if getattr(r, "path", "").startswith("/v1/admin/")
    ]
    assert len(admin_routes) >= 5, f"admin 표면이 {len(admin_routes)}건 — 분모가 사라졌다"
    writes = [(m, p) for m, p in admin_routes if set(m) - {"GET", "HEAD", "OPTIONS"}]
    assert writes == [], f"Phase A에 쓰기 라우트가 생겼다: {writes}"


def test_every_admin_route_uses_registry_derived_guard() -> None:
    """ADMIN-04 감사기를 ADMIN-05 표면에 대고 다시 돌린다 — 분모가 실제로 늘었는지 함께 본다."""
    from whymath_backend.ops.admin_guard_audit import audit_admin_route_guards

    violations, scanned = audit_admin_route_guards(create_app())
    assert scanned >= 6, f"검사 라우트 {scanned}건 — ADMIN-05 표면이 감사에 안 잡힌다"
    assert violations == [], violations


# ── ⑤ 집계 PII 부재 ──────────────────────────────────────────────────────────────


def test_user_aggregate_has_no_per_user_rows_or_pii() -> None:
    fake = FakeSession(
        results=[
            _Result(scalar=10),  # total
            _Result(scalar=8),  # active
            _Result(scalar=1),  # deleted
            _Result(scalar=6),  # minors
            _Result(rows=[(Role.STUDENT, 9), (Role.CONTENT_ADMIN, 1)]),
            _Result(rows=[(None, 10)]),
        ]
    )
    with _client(_ADMIN, fake) as client:
        payload = client.get("/v1/admin/users").json()

    assert set(payload) == {
        "total",
        "active",
        "deleted",
        "minors",
        "by_role",
        "by_subscription_tier",
    }
    assert payload["total"] == 10
    assert payload["by_role"] == {"student": 9, "content_admin": 1}
    # 티어가 전부 None이면 집계에서 빠진다 — None을 문자열 키로 만들지 않는다.
    assert payload["by_subscription_tier"] == {}
    serialized = str(payload)
    for leaked in ("email", "hash", "nickname"):
        assert leaked not in serialized


# ── ⑥ 단건 마스킹 + 감사 ─────────────────────────────────────────────────────────


def test_user_detail_masks_and_writes_one_audit_row() -> None:
    target = UserProfile(
        user_id=uuid.uuid4(),
        role=Role.STUDENT,
        nickname="김와이",
        email_hash="a" * 64,
        grade=3,
        is_minor=True,
        is_active=True,
        is_deleted=False,
    )
    fake = FakeSession(got=target)
    with _client(_ADMIN, fake) as client:
        response = client.get(f"/v1/admin/users/{target.user_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["nickname_masked"] == "김***"
    assert "email_hash" not in payload and "parent_email_hash" not in payload
    assert "a" * 64 not in str(payload), "이메일 해시가 응답 어딘가로 샜다"

    assert len(fake.added) == 1, f"감사 행 {len(fake.added)}건 (기대 1)"
    audit = fake.added[0]
    assert audit.user_id == _ADMIN.user_id
    assert audit.target_user_id == target.user_id
    assert fake.committed, "감사 행을 add만 하고 commit하지 않았다"


def test_user_detail_unknown_id_is_404_and_writes_no_audit() -> None:
    """없는 사용자에 감사 행을 남기면 대장이 조회 시도로 오염된다."""
    fake = FakeSession(got=None)
    with _client(_ADMIN, fake) as client:
        response = client.get(f"/v1/admin/users/{uuid.uuid4()}")
    assert response.status_code == 404
    assert fake.added == []


# ── ⑦ 측정 실패 ≠ 0건 ────────────────────────────────────────────────────────────


def test_costs_reports_unconfigured_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Langfuse 미설정은 `empty`가 아니라 `unconfigured`다 — 둘이 같으면 위장이다."""
    with _client(_ADMIN, FakeSession()) as client:
        payload = client.get("/v1/admin/costs").json()
    assert payload["state"] == "unconfigured"
    assert payload["event_count"] == 0
    # 미상 수치는 0이 아니라 None으로 남는다.
    assert payload["local_ratio"] is None


def test_costs_rejects_out_of_range_days() -> None:
    with _client(_ADMIN, FakeSession()) as client:
        assert client.get("/v1/admin/costs", params={"days": 0}).status_code == 422
        assert client.get("/v1/admin/costs", params={"days": 999}).status_code == 422


def test_review_queue_db_axis_counts_unset_separately() -> None:
    """`review_status`가 NULL인 문항을 어느 상태값에도 섞지 않는다(미판정은 판정이 아니다)."""
    from whymath_backend.schema.enums import ReviewStatus

    fake = FakeSession(
        results=[_Result(rows=[(ReviewStatus.pending, 4), (None, 2), (ReviewStatus.approved, 7)])]
    )
    with _client(_ADMIN, fake) as client:
        payload = client.get("/v1/admin/review-queue").json()
    assert payload["db"] == {"counts": {"pending": 4, "approved": 7}, "unset": 2, "total": 13}
