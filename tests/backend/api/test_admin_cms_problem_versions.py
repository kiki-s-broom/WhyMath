"""문항 판 발행 호출 표면 HTTP 계약 동결 — EOS-194 (`api/admin_cms_problem_versions.py`, hermetic).

EOS-190이 `problem_version`의 유일한 writer(`l3/problem_publish_gate`)를 만들었지만 부르는 곳이 0건이라
운영 DB의 `problem.problem_version_id`는 전부 NULL이었다. 이 파일은 그 호출 표면이 **권한·감사·오류
매핑·집행 경계**를 지키는지 CI가 실제로 도는 hermetic 층에서 동결한다(실 PG 관통은 같은 이름의
`_integration.py`가 본다 — 기본 SKIP).

동결 항목과 **각 항목이 없으면 통과해 버리는 오구현**
--------------------------------------------------
① **역할×전이 전수 매트릭스(리터럴 기대표)** — 기대표를 `cms_access`에서 읽어 오면 같은 값끼리 비교하는
   동어반복이다. 그래서 기대표는 이 파일에 **글자로 적고**, 권한표가 바뀌면 이 테스트가 깨져 의식적 검토를
   요구한다. 허용 칸은 게이트가 정확한 인자로 불렸는지·감사 1행·commit 1회를, 거부 칸은 게이트·DB·감사·
   commit 중 어느 것도 일어나지 않았는지를 본다("403만 보면" 거부 뒤에 쓰기가 일어나는 오구현이 통과한다).
② **복합 전용·미정의 전이는 단독 호출 통로가 없다** — 관리자도 422, DB 접근 0.
③ **초안 요청은 내용을 받지 않는다** — `payload`·`changes`·`status`·`problem_version_id`를 실으면 422이고
   게이트는 불리지 않는다(발행될 수 없는 초안·발행 포인터를 직접 쓰는 입구가 없다).
④ **오류 매핑** — 게이트 예외가 안정적인 `code`로 번역되고, 거부 시 rollback 1·commit 0·감사 0이다.
⑤ **트랜잭션 경계 뒤 사용자 접근 금지** — 응답을 commit 뒤에 만들 때 만료된 사용자 객체를 읽지 않는다.
⑥ **집행 경계(AST)** — 이 모듈은 ORM `ProblemVersion`을 import하지 않고, 발행 포인터를 쓰지 않으며,
   게이트 모듈의 **공개 함수 5개만** 부르고, 권한표를 자기 안에 다시 적지 않는다. 정상 코드가 0건인 것은
   증거가 아니므로 위반 코드를 주입해 RED를 확인한다.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api import admin_cms_problem_versions as route_module
from whymath_backend.api._auth import get_current_user
from whymath_backend.app import create_app
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l3.publish_gate import PublishGateError, StaleStatusError
from whymath_backend.schema.enums import (
    Curriculum,
    PrivacyAuditAction,
    PrivacyAuditResourceType,
    Role,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem_version import ProblemVersion as SchemaProblemVersion
from whymath_backend.schema.problem_version import ProblemVersionPayload
from whymath_backend.schema.version_header import (
    GateKind,
    GateRecord,
    TransitionAction,
    VersionGovernance,
    VersionQA,
    VersionStatus,
)
from whymath_backend.schema.version_lifecycle import UndefinedTransitionError

_A = TransitionAction
_S = VersionStatus

_REPO = Path(__file__).resolve().parents[3]
_MODULE_REL = "api/admin_cms_problem_versions.py"
_MODULE_PATH = _REPO / "src" / "backend" / "whymath_backend" / _MODULE_REL
_ENFORCEMENT = _REPO / "tests" / "backend" / "l3" / "test_problem_publish_gate_enforcement.py"


def _user(role: Role) -> UserProfile:
    return UserProfile(user_id=uuid.uuid4(), role=role)


_STUDENT = _user(Role.STUDENT)
_EDITOR = _user(Role.CONTENT_EDITOR)
_REVIEWER = _user(Role.CONTENT_REVIEWER)
_PUBLISHER = _user(Role.CONTENT_PUBLISHER)
_ADMIN = _user(Role.CONTENT_ADMIN)
_CMS_USERS = (_EDITOR, _REVIEWER, _PUBLISHER, _ADMIN)

_PID = uuid.uuid4()
_VID = uuid.uuid4()


# ── 가짜 세션 ──────────────────────────────────────────────────────────────────────────


class _Result:
    """`execute()` 결과 모사 — 라우터가 부르는 접근자만 구현한다."""

    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class FakeSession:
    """AsyncSession 모사 — **어떤 호출이 일어났는지**를 기록한다(거부 시 부작용 0 단언의 근거)."""

    def __init__(self, *, results: list[_Result] | None = None) -> None:
        self._results = list(results or [])
        self.added: list[Any] = []
        self.statements: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit_with: Exception | None = None
        #: commit이 불린 순간 세션에 이미 합류해 있던 감사 행 수 — 감사가 같은 트랜잭션인지의 증거.
        self.audit_at_commit: int | None = None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return self._results.pop(0) if self._results else _Result()

    async def commit(self) -> None:
        if self.fail_commit_with is not None:
            raise self.fail_commit_with
        self.audit_at_commit = len(self.audit_rows)
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def flush(self) -> None:
        return None

    @property
    def touched_db(self) -> bool:
        return bool(self.statements or self.added or self.commits)

    @property
    def audit_rows(self) -> list[PrivacyAudit]:
        return [o for o in self.added if isinstance(o, PrivacyAudit)]


#: 앱은 모듈에서 한 번만 만든다(`create_app()`≈0.4초). 요청마다 오버라이드를 전부 지우고 다시 설정한다.
_APP = create_app()


def _client(user: UserProfile | None, fake: FakeSession) -> TestClient:
    async def _override() -> AsyncIterator[FakeSession]:
        yield fake

    _APP.dependency_overrides.clear()
    _APP.dependency_overrides[get_session] = _override
    if user is not None:
        _APP.dependency_overrides[get_current_user] = lambda: user
    return TestClient(_APP)


class ExpiredUserError(RuntimeError):
    """`MissingGreenlet`의 모사 — 트랜잭션 경계 뒤에 만료된 ORM 객체 속성을 읽었다."""


class _ExpiringUser:
    def __init__(self, real: UserProfile, fake: FakeSession) -> None:
        self._real = real
        self._fake = fake

    def _guard(self) -> None:
        if self._fake.commits or self._fake.rollbacks:
            raise ExpiredUserError("트랜잭션 경계 뒤에 사용자 객체를 읽었다")

    @property
    def role(self) -> Role:
        self._guard()
        return self._real.role

    @property
    def user_id(self) -> uuid.UUID:
        self._guard()
        return self._real.user_id

    @property
    def email_hash(self) -> str | None:
        return None


def _expiring_client(real: UserProfile, fake: FakeSession) -> TestClient:
    async def _override() -> AsyncIterator[FakeSession]:
        yield fake

    _APP.dependency_overrides.clear()
    _APP.dependency_overrides[get_session] = _override
    _APP.dependency_overrides[get_current_user] = lambda: _ExpiringUser(real, fake)
    return TestClient(_APP)


# ── 게이트 스파이 ──────────────────────────────────────────────────────────────────────


def _version(
    *,
    status_: VersionStatus = VersionStatus.DRAFT,
    problem_id: uuid.UUID = _PID,
    version_no: int = 1,
    records: list[GateRecord] | None = None,
) -> SchemaProblemVersion:
    return SchemaProblemVersion(
        problem_id=problem_id,
        version_no=version_no,
        schema_version="problem-schema@1",
        status=status_,
        payload=ProblemVersionPayload(
            source_type=SourceType.자체생성,
            subject=Subject.미적분,
            curriculum_version=Curriculum.REVISION_2015,
            unit_codes=["CAL-INT-DEF"],
            answer="정답",
        ),
        governance=VersionGovernance(created_by="tester"),
        qa=VersionQA(records=records or []),
    )


class GateSpy:
    """`problem_publish_gate`의 DB 함수를 대체한다 — 호출 인자를 기록하고 정해 둔 동작을 한다."""

    def __init__(self) -> None:
        self.apply_calls: list[dict[str, Any]] = []
        self.draft_calls: list[dict[str, Any]] = []
        self.list_calls: list[uuid.UUID] = []
        self.get_calls: list[uuid.UUID] = []
        self.apply_effect: Callable[[], SchemaProblemVersion] | None = None
        self.draft_effect: Callable[[], SchemaProblemVersion] | None = None
        self.versions: list[SchemaProblemVersion] = []
        self.list_error: Exception | None = None
        self.exists_calls: list[uuid.UUID] = []
        self.problem_exists_result = True

    async def problem_exists(self, session: Any, problem_id: uuid.UUID) -> bool:
        self.exists_calls.append(problem_id)
        return self.problem_exists_result

    async def apply_transition(
        self,
        session: Any,
        version_id: uuid.UUID,
        action: Any,
        *,
        actor: str,
        now: Any = None,
        expected_status: VersionStatus | None = None,
    ) -> SchemaProblemVersion:
        self.apply_calls.append(
            {
                "version_id": version_id,
                "action": action,
                "actor": actor,
                "expected_status": expected_status,
            }
        )
        if self.apply_effect is None:
            raise LookupError("스파이: 판 없음")
        return self.apply_effect()

    async def create_draft(self, session: Any, **kwargs: Any) -> SchemaProblemVersion:
        self.draft_calls.append(kwargs)
        if self.draft_effect is None:
            raise LookupError("스파이: 문항 없음")
        return self.draft_effect()

    async def list_versions(
        self, session: Any, problem_id: uuid.UUID
    ) -> list[SchemaProblemVersion]:
        self.list_calls.append(problem_id)
        if self.list_error is not None:
            raise self.list_error
        return list(self.versions)

    async def get_version(self, session: Any, version_id: uuid.UUID) -> SchemaProblemVersion:
        self.get_calls.append(version_id)
        if not self.versions:
            raise LookupError("스파이: 판 없음")
        return self.versions[0]


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> GateSpy:
    s = GateSpy()
    gate = route_module.pgate
    monkeypatch.setattr(gate, "apply_transition", s.apply_transition)
    monkeypatch.setattr(gate, "create_draft", s.create_draft)
    monkeypatch.setattr(gate, "list_versions", s.list_versions)
    monkeypatch.setattr(gate, "get_version", s.get_version)
    monkeypatch.setattr(gate, "problem_exists", s.problem_exists)
    return s


def _post_transition(
    client: TestClient, action: str, expected: str = "DRAFT", version_id: uuid.UUID = _VID
) -> Any:
    return client.post(
        f"/v1/admin/cms/problem-versions/{version_id}/transitions",
        json={"action": action, "expected_status": expected},
    )


# ═══════════════════════════════════════════════════════════════════════════════════════
# 라우트 인벤토리 · 인증 · 모듈 가드
# ═══════════════════════════════════════════════════════════════════════════════════════

_PROBLEM_VERSION_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/v1/admin/cms/problems/{problem_id}/drafts"),
        ("GET", "/v1/admin/cms/problems/{problem_id}/versions"),
        ("GET", "/v1/admin/cms/problem-versions/{version_id}"),
        ("POST", "/v1/admin/cms/problem-versions/{version_id}/transitions"),
    }
)


def _served_problem_version_routes() -> set[tuple[str, str]]:
    from whymath_backend.ops.declared_unwired_audit import walk_routes

    out: set[tuple[str, str]] = set()
    for r in walk_routes(_APP.routes):
        path = getattr(r, "path", "")
        if "/problems/{problem_id}/" in path or "/problem-versions/" in path:
            if not path.startswith("/v1/admin/cms/"):
                continue
            for method in getattr(r, "methods", None) or ():
                if method not in {"HEAD", "OPTIONS"}:
                    out.add((method, path))
    return out


def test_served_routes_are_exactly_the_four_declared_ones() -> None:
    """분모 — 라우트가 사라져도, 선언 밖 라우트(롤백 등)가 늘어도 RED다."""
    assert _served_problem_version_routes() == set(_PROBLEM_VERSION_ROUTES)


def _call(client: TestClient, method: str, path: str) -> Any:
    url = path.replace("{problem_id}", str(_PID)).replace("{version_id}", str(_VID))
    body: dict[str, Any] = {}
    if url.endswith("/transitions"):
        body = {"action": "submit", "expected_status": "DRAFT"}
    return client.request(method, url, json=body if method != "GET" else None)


_ROUTE_PARAMS = sorted(_PROBLEM_VERSION_ROUTES)


@pytest.mark.parametrize(("method", "path"), _ROUTE_PARAMS, ids=lambda v: str(v))
def test_unauthenticated_request_is_401(method: str, path: str) -> None:
    fake = FakeSession()
    resp = _call(_client(None, fake), method, path)
    assert resp.status_code == 401, resp.text
    assert not fake.touched_db


@pytest.mark.parametrize(("method", "path"), _ROUTE_PARAMS, ids=lambda v: str(v))
def test_student_is_403_without_touching_the_db(method: str, path: str, spy: GateSpy) -> None:
    fake = FakeSession()
    resp = _call(_client(_STUDENT, fake), method, path)
    assert resp.status_code == 403, resp.text
    assert not fake.touched_db, "거부된 요청이 DB를 건드렸다"
    assert not (spy.apply_calls or spy.draft_calls or spy.list_calls or spy.get_calls)


def test_routes_use_registry_derived_module_guards() -> None:
    """새 라우트가 레지스트리 파생 가드를 쓰는지 기존 감사기로 검사한다(분모 포함)."""
    from whymath_backend.ops.admin_guard_audit import audit_admin_route_guards

    violations, scanned = audit_admin_route_guards(_APP)
    assert violations == []
    assert scanned >= len(_PROBLEM_VERSION_ROUTES)


# ═══════════════════════════════════════════════════════════════════════════════════════
# ① 역할 × 전이 전수 매트릭스 — 리터럴 기대표
# ═══════════════════════════════════════════════════════════════════════════════════════

_ALL_DIRECT = frozenset(
    {
        "submit",
        "request_changes",
        "pass_review",
        "fail_qa",
        "approve",
        "publish",
        "deprecate",
        "retire",
    }
)
#: 글자로 적은 기대표 — `schema/cms_access.TRANSITION_CAPABILITY`가 바뀌면 이 표가 RED가 된다.
#: 승인(approve)은 **검수 권한**(reviewer)이다 — 개념 판과 같은 정본을 쓴다(발행만 배포 권한).
_EXPECTED_ACTIONS: dict[Role, frozenset[str]] = {
    Role.CONTENT_EDITOR: frozenset({"submit"}),
    Role.CONTENT_REVIEWER: frozenset({"request_changes", "pass_review", "fail_qa", "approve"}),
    Role.CONTENT_PUBLISHER: frozenset({"publish", "deprecate", "retire"}),
    Role.CONTENT_ADMIN: _ALL_DIRECT,
}
_STATE_AFTER = {
    "submit": _S.IN_REVIEW,
    "request_changes": _S.DRAFT,
    "pass_review": _S.IN_QA,
    "fail_qa": _S.DRAFT,
    "approve": _S.APPROVED,
    "publish": _S.PUBLISHED,
    "deprecate": _S.DEPRECATED,
    "retire": _S.RETIRED,
}
_STATE_BEFORE = {
    "submit": "DRAFT",
    "request_changes": "IN_REVIEW",
    "pass_review": "IN_REVIEW",
    "fail_qa": "IN_QA",
    "approve": "IN_QA",
    "publish": "APPROVED",
    "deprecate": "PUBLISHED",
    "retire": "DEPRECATED",
}


def test_expected_table_is_not_vacuous() -> None:
    assert set(_STATE_AFTER) == set(_STATE_BEFORE) == _ALL_DIRECT
    assert _EXPECTED_ACTIONS[Role.CONTENT_ADMIN] == _ALL_DIRECT
    # 관리자 외 세 역할의 허용 집합은 서로소이고 합이 전체다 — 빠진 전이가 있으면 RED.
    union: set[str] = set()
    for role in (Role.CONTENT_EDITOR, Role.CONTENT_REVIEWER, Role.CONTENT_PUBLISHER):
        assert not (union & _EXPECTED_ACTIONS[role])
        union |= _EXPECTED_ACTIONS[role]
    assert union == _ALL_DIRECT


class TestTransitionMatrix:
    @pytest.mark.parametrize("user", _CMS_USERS, ids=lambda u: u.role.value)
    @pytest.mark.parametrize("action", sorted(_ALL_DIRECT))
    def test_role_times_action(self, user: UserProfile, action: str, spy: GateSpy) -> None:
        spy.apply_effect = lambda: _version(status_=_STATE_AFTER[action])
        fake = FakeSession()
        resp = _post_transition(_client(user, fake), action, _STATE_BEFORE[action])
        if action in _EXPECTED_ACTIONS[user.role]:
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == _STATE_AFTER[action].value
            assert len(spy.apply_calls) == 1
            call = spy.apply_calls[0]
            assert call["version_id"] == _VID
            assert call["action"] is TransitionAction(action)
            assert call["actor"] == str(user.user_id), "행위자는 사용자 UUID(PII 아님)여야 한다"
            assert call["expected_status"] is VersionStatus(_STATE_BEFORE[action])
            assert fake.commits == 1 and fake.rollbacks == 0
            assert fake.audit_at_commit == 1, "감사 행이 commit과 같은 트랜잭션에 합류하지 않았다"
            rows = fake.audit_rows
            assert len(rows) == 1, "전이 1건마다 감사 행이 정확히 1개여야 한다"
            assert rows[0].resource_type == PrivacyAuditResourceType.problem_version.value
            assert rows[0].resource_id == _VID
            assert rows[0].action == PrivacyAuditAction(action).value
            assert rows[0].user_id == user.user_id
        else:
            assert resp.status_code == 403, resp.text
            assert resp.json()["detail"]["code"] == "capability_required"
            assert not spy.apply_calls, "권한 없는 요청이 게이트를 불렀다"
            assert not fake.touched_db, "권한 거부가 DB·감사·commit을 건드렸다"

    def test_editor_and_reviewer_cannot_publish_before_anything_runs(self, spy: GateSpy) -> None:
        """지시문 검증 ① — 편집자·검수자의 `publish`는 게이트를 부르기 전에 403으로 끝난다."""
        for user in (_EDITOR, _REVIEWER):
            fake = FakeSession()
            resp = _post_transition(_client(user, fake), "publish", "APPROVED")
            assert resp.status_code == 403
            assert not spy.apply_calls and not fake.touched_db


class TestNoStandaloneCompoundOrUnknownTransition:
    @pytest.mark.parametrize(
        "name", ["supersede", "rollback", "restore", "nope", "PUBLISH", "publish ", ""]
    )
    def test_admin_gets_422_and_nothing_runs(self, name: str, spy: GateSpy) -> None:
        fake = FakeSession()
        resp = _post_transition(_client(_ADMIN, fake), name, "APPROVED")
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "unknown_action"
        assert not spy.apply_calls and not fake.touched_db

    def test_expected_status_must_be_in_the_vocabulary(self, spy: GateSpy) -> None:
        fake = FakeSession()
        resp = _post_transition(_client(_ADMIN, fake), "submit", "NOT_A_STATUS")
        assert resp.status_code == 422
        assert not spy.apply_calls and not fake.touched_db

    def test_transition_body_rejects_extra_keys(self, spy: GateSpy) -> None:
        fake = FakeSession()
        resp = _client(_ADMIN, fake).post(
            f"/v1/admin/cms/problem-versions/{_VID}/transitions",
            json={"action": "submit", "expected_status": "DRAFT", "problem_version_id": str(_VID)},
        )
        assert resp.status_code == 422
        assert not spy.apply_calls and not fake.touched_db


# ═══════════════════════════════════════════════════════════════════════════════════════
# ④ 오류 매핑
# ═══════════════════════════════════════════════════════════════════════════════════════


class TestTransitionErrorMapping:
    def _assert_refused(self, fake: FakeSession) -> None:
        assert fake.rollbacks == 1 and fake.commits == 0
        assert fake.audit_rows == [], "거부된 전이가 감사 행을 남겼다"

    def test_missing_version_is_404(self, spy: GateSpy) -> None:
        fake = FakeSession()
        resp = _post_transition(_client(_ADMIN, fake), "submit")  # 스파이 기본 동작 = LookupError
        assert resp.status_code == 404 and resp.json()["detail"]["code"] == "not_found"
        self._assert_refused(fake)

    def test_stale_status_is_409_with_the_current_status(self, spy: GateSpy) -> None:
        def boom() -> SchemaProblemVersion:
            raise StaleStatusError(_S.DRAFT, _S.IN_REVIEW)

        spy.apply_effect = boom
        fake = FakeSession()
        resp = _post_transition(_client(_ADMIN, fake), "submit")
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "stale_status" and detail["current_status"] == "IN_REVIEW"
        self._assert_refused(fake)

    def test_illegal_transition_is_409(self, spy: GateSpy) -> None:
        def boom() -> SchemaProblemVersion:
            raise UndefinedTransitionError("미정의 전이")

        spy.apply_effect = boom
        fake = FakeSession()
        resp = _post_transition(_client(_ADMIN, fake), "publish", "DRAFT")
        assert resp.status_code == 409 and resp.json()["detail"]["code"] == "illegal_transition"
        self._assert_refused(fake)

    def test_gate_failure_is_422_with_the_failures(self, spy: GateSpy) -> None:
        def boom() -> SchemaProblemVersion:
            raise PublishGateError(
                GateKind.PUBLISH, ["live_content_current: 승인 이후 라이브 문항이 바뀌었다"]
            )

        spy.apply_effect = boom
        fake = FakeSession()
        resp = _post_transition(_client(_ADMIN, fake), "publish", "APPROVED")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "gate_failed" and detail["gate"] == GateKind.PUBLISH.value
        assert detail["failures"] == ["live_content_current: 승인 이후 라이브 문항이 바뀌었다"]
        self._assert_refused(fake)

    def test_unexpected_error_rolls_back_and_propagates(self, spy: GateSpy) -> None:
        def boom() -> SchemaProblemVersion:
            raise RuntimeError("예상 밖 장애")

        spy.apply_effect = boom
        fake = FakeSession()
        with pytest.raises(RuntimeError, match="예상 밖 장애"):
            _post_transition(_client(_ADMIN, fake), "submit")
        self._assert_refused(fake)

    def test_commit_failure_rolls_back_and_propagates(self, spy: GateSpy) -> None:
        """감사 행과 전이는 한 트랜잭션이다 — commit이 실패하면 rollback하고 성공으로 응답하지 않는다."""
        spy.apply_effect = lambda: _version(status_=_S.IN_REVIEW)
        fake = FakeSession()
        fake.fail_commit_with = RuntimeError("commit 실패")
        with pytest.raises(RuntimeError, match="commit 실패"):
            _post_transition(_client(_EDITOR, fake), "submit")
        assert fake.rollbacks == 1 and fake.commits == 0


# ═══════════════════════════════════════════════════════════════════════════════════════
# ③ 초안 생성
# ═══════════════════════════════════════════════════════════════════════════════════════


class TestDraftCreation:
    @pytest.mark.parametrize("user", [_EDITOR, _ADMIN], ids=lambda u: u.role.value)
    def test_editor_and_admin_create_a_draft(self, user: UserProfile, spy: GateSpy) -> None:
        created = _version(version_no=3)
        spy.draft_effect = lambda: created
        fake = FakeSession()
        resp = _client(user, fake).post(
            f"/v1/admin/cms/problems/{_PID}/drafts",
            json={"reason": "정답 정정", "ticket_id": "T-1"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "DRAFT" and body["version_no"] == 3
        assert body["problem_id"] == str(_PID) and body["version_id"] == str(created.version_id)
        assert len(spy.draft_calls) == 1
        call = spy.draft_calls[0]
        assert call["problem_id"] == _PID
        assert call["created_by"] == str(user.user_id)
        assert (
            "payload" not in call
        ), "내용을 호출자가 정하는 입구가 생겼다 — 라이브 스냅숏이어야 한다"
        assert call["change"].reason == "정답 정정" and call["change"].ticket_id == "T-1"
        assert fake.commits == 1 and fake.rollbacks == 0
        assert fake.audit_at_commit == 1, "감사 행이 commit과 같은 트랜잭션에 합류하지 않았다"
        rows = fake.audit_rows
        assert len(rows) == 1
        assert rows[0].resource_type == PrivacyAuditResourceType.problem_version.value
        assert rows[0].resource_id == created.version_id
        assert rows[0].action == PrivacyAuditAction.create.value
        assert rows[0].user_id == user.user_id

    @pytest.mark.parametrize("user", [_REVIEWER, _PUBLISHER], ids=lambda u: u.role.value)
    def test_reviewer_and_publisher_cannot_create_a_draft(
        self, user: UserProfile, spy: GateSpy
    ) -> None:
        fake = FakeSession()
        resp = _client(user, fake).post(f"/v1/admin/cms/problems/{_PID}/drafts", json={})
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "capability_required"
        assert not spy.draft_calls and not fake.touched_db

    @pytest.mark.parametrize(
        "extra",
        [
            {"payload": {"answer": "x"}},
            {"changes": {"answer": "x"}},
            {"status": "PUBLISHED"},
            {"problem_version_id": str(_VID)},
        ],
        ids=lambda e: next(iter(e)),
    )
    def test_body_rejects_content_and_workflow_keys(
        self, extra: dict[str, Any], spy: GateSpy
    ) -> None:
        fake = FakeSession()
        resp = _client(_ADMIN, fake).post(f"/v1/admin/cms/problems/{_PID}/drafts", json=extra)
        assert resp.status_code == 422, resp.text
        assert not spy.draft_calls and not fake.touched_db

    def test_missing_problem_is_404(self, spy: GateSpy) -> None:
        fake = FakeSession()
        resp = _client(_EDITOR, fake).post(f"/v1/admin/cms/problems/{_PID}/drafts", json={})
        assert resp.status_code == 404 and resp.json()["detail"]["code"] == "not_found"
        assert fake.rollbacks == 1 and fake.commits == 0 and fake.audit_rows == []

    def test_live_problem_violating_the_snapshot_contract_is_422(self, spy: GateSpy) -> None:
        def boom() -> SchemaProblemVersion:
            raise PublishGateError(None, ["schema_valid: 라이브 문항 ValidationError"])

        spy.draft_effect = boom
        fake = FakeSession()
        resp = _client(_EDITOR, fake).post(f"/v1/admin/cms/problems/{_PID}/drafts", json={})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "gate_failed" and detail["gate"] is None
        assert fake.rollbacks == 1 and fake.commits == 0 and fake.audit_rows == []

    def test_unexpected_error_rolls_back_and_propagates(self, spy: GateSpy) -> None:
        def boom() -> SchemaProblemVersion:
            raise RuntimeError("예상 밖 장애")

        spy.draft_effect = boom
        fake = FakeSession()
        with pytest.raises(RuntimeError, match="예상 밖 장애"):
            _client(_EDITOR, fake).post(f"/v1/admin/cms/problems/{_PID}/drafts", json={})
        assert fake.rollbacks == 1 and fake.commits == 0 and fake.audit_rows == []

    def test_commit_failure_rolls_back_and_propagates(self, spy: GateSpy) -> None:
        spy.draft_effect = lambda: _version()
        fake = FakeSession()
        fake.fail_commit_with = RuntimeError("commit 실패")
        with pytest.raises(RuntimeError, match="commit 실패"):
            _client(_EDITOR, fake).post(f"/v1/admin/cms/problems/{_PID}/drafts", json={})
        assert fake.rollbacks == 1 and fake.commits == 0

    def test_reason_is_length_limited(self, spy: GateSpy) -> None:
        fake = FakeSession()
        resp = _client(_EDITOR, fake).post(
            f"/v1/admin/cms/problems/{_PID}/drafts", json={"reason": "가" * 501}
        )
        assert resp.status_code == 422 and not spy.draft_calls


# ═══════════════════════════════════════════════════════════════════════════════════════
# 읽기 — 목록·상세·allowed_actions
# ═══════════════════════════════════════════════════════════════════════════════════════


def _record() -> GateRecord:
    from datetime import UTC, datetime

    return GateRecord(
        gate=GateKind.QA,
        action=TransitionAction.APPROVE,
        judged_by="reviewer-1",
        judged_at=datetime(2026, 10, 13, tzinfo=UTC),
        checks=["schema_valid", "content_hash"],
        content_hash="sha256:" + "a" * 64,
        validator_bundle_version="eos190-problem-publish-gate@1",
        qa_run_id="QA-test",
        bypassed=False,
    )


class TestReads:
    @pytest.mark.parametrize("user", _CMS_USERS, ids=lambda u: u.role.value)
    def test_every_cms_role_can_read(self, user: UserProfile, spy: GateSpy) -> None:
        spy.versions = [_version(version_no=2), _version(version_no=1)]
        fake = FakeSession()
        resp = _client(user, fake).get(f"/v1/admin/cms/problems/{_PID}/versions")
        assert resp.status_code == 200, resp.text
        assert [v["version_no"] for v in resp.json()] == [2, 1], "최신 판부터"
        assert spy.exists_calls == [_PID] and spy.list_calls == [_PID]
        assert fake.commits == 0 and fake.added == [], "읽기는 쓰지 않는다"

    def test_unknown_problem_is_404_and_the_gate_is_not_asked(self, spy: GateSpy) -> None:
        spy.problem_exists_result = False
        fake = FakeSession()
        resp = _client(_EDITOR, fake).get(f"/v1/admin/cms/problems/{_PID}/versions")
        assert resp.status_code == 404 and resp.json()["detail"]["code"] == "not_found"
        assert spy.exists_calls == [_PID] and not spy.list_calls

    def test_known_problem_with_no_versions_is_an_empty_list(self, spy: GateSpy) -> None:
        fake = FakeSession()
        resp = _client(_EDITOR, fake).get(f"/v1/admin/cms/problems/{_PID}/versions")
        assert resp.status_code == 200 and resp.json() == []

    def test_corrupt_stored_version_is_reported_not_skipped(self, spy: GateSpy) -> None:
        spy.list_error = PublishGateError(None, ["schema_valid: 저장된 행 ValidationError"])
        fake = FakeSession()
        resp = _client(_EDITOR, fake).get(f"/v1/admin/cms/problems/{_PID}/versions")
        assert resp.status_code == 422 and resp.json()["detail"]["code"] == "gate_failed"

    def test_detail_has_payload_and_gate_records(self, spy: GateSpy) -> None:
        spy.versions = [_version(status_=_S.APPROVED, records=[_record()])]
        resp = _client(_PUBLISHER, FakeSession()).get(f"/v1/admin/cms/problem-versions/{_VID}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["payload"]["answer"] == "정답"
        assert [r["gate"] for r in body["gate_records"]] == [GateKind.QA.value]
        assert body["gate_records"][0]["checks"] == ["schema_valid", "content_hash"]
        assert spy.get_calls == [_VID]

    def test_detail_of_missing_version_is_404(self, spy: GateSpy) -> None:
        resp = _client(_EDITOR, FakeSession()).get(f"/v1/admin/cms/problem-versions/{_VID}")
        assert resp.status_code == 404

    # allowed_actions = 전이표 ∩ 호출자 권한 — 리터럴 기대표(상태 × 역할)
    @pytest.mark.parametrize(
        ("state", "role_user", "expected"),
        [
            (_S.DRAFT, _EDITOR, ("submit",)),
            (_S.DRAFT, _REVIEWER, ()),
            (_S.DRAFT, _PUBLISHER, ()),
            (_S.IN_REVIEW, _EDITOR, ()),
            (_S.IN_REVIEW, _REVIEWER, ("request_changes", "pass_review")),
            (_S.IN_QA, _REVIEWER, ("fail_qa", "approve")),
            (_S.IN_QA, _PUBLISHER, ()),
            (_S.APPROVED, _REVIEWER, ()),
            (_S.APPROVED, _PUBLISHER, ("publish",)),
            (_S.PUBLISHED, _PUBLISHER, ("deprecate",)),
            (_S.PUBLISHED, _EDITOR, ()),
            (_S.DEPRECATED, _PUBLISHER, ("retire",)),
            (_S.APPROVED, _ADMIN, ("publish",)),
            (_S.RETIRED, _ADMIN, ()),
        ],
        ids=lambda v: (
            getattr(v, "value", getattr(v, "role", v)) if not isinstance(v, tuple) else str(v)
        ),
    )
    def test_allowed_actions_are_the_table_intersected_with_the_callers_rights(
        self, state: VersionStatus, role_user: UserProfile, expected: tuple[str, ...], spy: GateSpy
    ) -> None:
        spy.versions = [_version(status_=state)]
        resp = _client(role_user, FakeSession()).get(f"/v1/admin/cms/problem-versions/{_VID}")
        assert resp.status_code == 200, resp.text
        assert tuple(resp.json()["summary"]["allowed_actions"]) == expected


# ═══════════════════════════════════════════════════════════════════════════════════════
# ⑤ 트랜잭션 경계 뒤 사용자 접근 금지
# ═══════════════════════════════════════════════════════════════════════════════════════


class TestNoUserAccessAfterTheTransactionBoundary:
    def test_transition_responds_after_commit_without_touching_the_user(self, spy: GateSpy) -> None:
        spy.apply_effect = lambda: _version(status_=_S.IN_REVIEW)
        fake = FakeSession()
        resp = _post_transition(_expiring_client(_EDITOR, fake), "submit")
        assert resp.status_code == 200, resp.text
        assert fake.commits == 1

    def test_draft_responds_after_commit_without_touching_the_user(self, spy: GateSpy) -> None:
        spy.draft_effect = lambda: _version()
        fake = FakeSession()
        resp = _expiring_client(_EDITOR, fake).post(
            f"/v1/admin/cms/problems/{_PID}/drafts", json={}
        )
        assert resp.status_code == 201, resp.text
        assert fake.commits == 1

    def test_the_expiring_user_double_really_raises(self) -> None:
        """대조군 — 이 모사가 실제로 터진다(터지지 않으면 위 테스트는 공허하다)."""
        fake = FakeSession()
        user = _ExpiringUser(_EDITOR, fake)
        assert user.role is Role.CONTENT_EDITOR
        fake.commits = 1
        with pytest.raises(ExpiredUserError):
            _ = user.role
        with pytest.raises(ExpiredUserError):
            _ = user.user_id


# ═══════════════════════════════════════════════════════════════════════════════════════
# ⑥ 집행 경계(AST) — 정상 0건 + 주입 RED
# ═══════════════════════════════════════════════════════════════════════════════════════


def _load_enforcement() -> Any:
    spec = importlib.util.spec_from_file_location("_problem_gate_enforcement_for_cms", _ENFORCEMENT)
    assert (
        spec is not None and spec.loader is not None
    ), f"스캐너 원본을 로드하지 못했다: {_ENFORCEMENT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_E = _load_enforcement()
_GATE_PUBLIC_FUNCTIONS = frozenset(
    {"create_draft", "list_versions", "get_version", "problem_exists", "apply_transition"}
)


def _source() -> str:
    assert _MODULE_PATH.is_file(), f"대상 모듈이 없다(공허 통과 금지): {_MODULE_PATH}"
    return _MODULE_PATH.read_text(encoding="utf-8")


class TestEnforcementBoundary:
    def test_the_module_has_no_violation_of_the_problem_gate_rules(self) -> None:
        assert _E.scan_source(_MODULE_REL, _source()) == []

    def test_the_scanner_actually_looks_at_this_module(self) -> None:
        """대상이 스캔 목록에서 빠지는 상황을 막는다 — 실제 운영 패키지 스캔 대상에 이 파일이 들어 있다."""
        pkg = _MODULE_PATH.parents[1]
        scanned = {p.relative_to(pkg).as_posix() for p in pkg.rglob("*.py")}
        assert _MODULE_REL in scanned

    def test_injected_orm_import_is_caught(self) -> None:
        src = _source()
        mutated = src + "\nfrom whymath_backend.db.models.problem_version import ProblemVersion\n"
        assert mutated != src
        assert any(v.startswith("R1") for v in _E.scan_source(_MODULE_REL, mutated))

    def test_injected_pointer_write_is_caught(self) -> None:
        src = _source()
        mutated = src + "\n\ndef _x(problem):\n    problem.problem_version_id = None\n"
        assert mutated != src
        assert any(v.startswith("R2") for v in _E.scan_source(_MODULE_REL, mutated))

    def test_injected_write_sql_is_caught(self) -> None:
        src = _source()
        mutated = src + '\n_SQL = "UPDATE problem_version SET status = 1"\n'
        assert mutated != src
        assert any(v.startswith("R3") for v in _E.scan_source(_MODULE_REL, mutated))

    def test_only_the_five_public_gate_functions_are_used(self) -> None:
        tree = ast.parse(_source())
        used = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "pgate"
        }
        assert used, "게이트 호출이 0건이다 — 이 모듈이 아무것도 안 부른다"
        assert (
            used <= _GATE_PUBLIC_FUNCTIONS
        ), f"공개 함수 밖을 부른다: {sorted(used - _GATE_PUBLIC_FUNCTIONS)}"
        assert (
            used == _GATE_PUBLIC_FUNCTIONS
        ), f"쓰지 않는 공개 함수: {sorted(_GATE_PUBLIC_FUNCTIONS - used)}"

    def test_the_module_does_not_touch_the_database_directly(self) -> None:
        """DB는 게이트 모듈이 읽고 쓴다 — 이 모듈에 `session.execute`·`select`가 생기면 데이터 접근
        baseline(`scripts/analysis/data_access_layer_audit.py`)에 새 접근점을 등재해야 한다."""
        tree = ast.parse(_source())
        direct_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "session"
            and node.func.attr in {"execute", "get", "scalar", "scalars", "add", "delete", "merge"}
        }
        # 감사 행 합류(`record_content_mutation_audit`)가 `session`을 넘길 뿐 직접 add하지 않는다.
        assert direct_calls == set(), f"세션을 직접 잡는다: {sorted(direct_calls)}"
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy":
                assert "select" not in {a.name for a in node.names}

    def test_a_direct_session_call_would_be_caught_by_the_check_above(self) -> None:
        """대조군 — 위 검사가 직접 조회를 실제로 잡는다."""
        tree = ast.parse(_source() + "\n\nasync def _x(session):\n    await session.execute(1)\n")
        calls = {
            n.func.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "session"
            and n.func.attr == "execute"
        }
        assert calls == {"execute"}

    def test_a_private_gate_call_would_be_caught_by_the_check_above(self) -> None:
        """대조군 — 위 검사가 비공개 호출을 실제로 잡는다."""
        tree = ast.parse(_source() + "\n\nasync def _x():\n    pgate._write_back(None, None)\n")
        used = {
            n.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == "pgate"
        }
        assert not used <= _GATE_PUBLIC_FUNCTIONS

    def test_the_module_does_not_restate_the_capability_table(self) -> None:
        """역할→권한 매핑·전이→권한 매핑은 `schema/cms_access` 한 곳이다 — 여기 다시 적으면 드리프트한다."""
        tree = ast.parse(_source())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                assert node.value.id != "Role", f"역할 이름으로 분기한다: Role.{node.attr}"
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assert target.id not in {"ROLE_CAPABILITIES", "TRANSITION_CAPABILITY"}

    def test_the_audit_resource_type_is_the_problem_version_axis(self) -> None:
        tree = ast.parse(_source())
        used = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "PrivacyAuditResourceType"
        }
        assert used == {"problem_version"}, f"감사가 다른 리소스 타입을 쓴다: {sorted(used)}"


# ═══════════════════════════════════════════════════════════════════════════════════════
# 운영 측정 쿼리(인수 조건 ③) ↔ 서빙 노출 게이트 드리프트 가드
# ═══════════════════════════════════════════════════════════════════════════════════════

#: 운영 DB에서 "발행으로 포인터가 채워진 문항 수 / 노출 문항 수"를 재는 읽기 전용 쿼리. 런북
#: (`docs/architecture/eos194_problem_publish_caller_surface.md` §5)이 이 글자 그대로를 싣는다.
#: **ASCII만 쓴다** — 한글 출처명은 `U&'\XXXX'` 유니코드 이스케이프다. Windows PowerShell 5.1은 네이티브
#: 명령 인자를 로케일(cp949)로 왕복시켜 한글 리터럴을 조용히 바꿀 수 있고, 그러면 분모가 틀어진 채
#: 숫자가 정상처럼 나온다. 분모의 "노출"은 손으로 다시 정의하지 않는다 — 서빙 후보 풀의 WHERE
#: (`candidate_pool_conditions`)다.
_EXPOSURE_GATE_SQL = (
    "problem.difficulty_overall IS NOT NULL "
    "AND (problem.source_type NOT IN ('EBS', U&'\\D3C9\\AC00\\C6D0', U&'\\AD50\\ACFC\\C11C')) "
    "AND problem.review_status = 'approved'"
)
EXPOSURE_COVERAGE_SQL = (
    "SELECT count(*) AS total_problems, "
    f"count(*) FILTER (WHERE {_EXPOSURE_GATE_SQL}) AS exposed, "
    f"count(*) FILTER (WHERE {_EXPOSURE_GATE_SQL} "
    "AND problem.problem_version_id IS NOT NULL) AS exposed_with_pointer, "
    "count(*) FILTER (WHERE problem.problem_version_id IS NOT NULL) AS any_with_pointer, "
    "(SELECT count(*) FROM problem_version WHERE status = 'PUBLISHED') AS published_versions "
    "FROM problem"
)


def _canonical(sql: str) -> str:
    """비교용 정규형 — 유니코드 이스케이프를 글자로 풀고, `NOT IN (...)` 목록을 정렬한다.

    목록의 나열 순서는 `frozenset` 순회 순서라 프로세스마다 다르다(문자열 해시 무작위화). 의미는
    집합이므로 순서를 지운다. 나머지 글자는 그대로 비교한다.
    """
    unescaped = re.sub(
        r"U&'((?:\\[0-9A-Fa-f]{4})+)'",
        lambda m: "'"
        + "".join(chr(int(h, 16)) for h in re.findall(r"[0-9A-Fa-f]{4}", m.group(1)))
        + "'",
        sql,
    )
    normalized = " ".join(unescaped.split())

    def _sorted_members(match: re.Match[str]) -> str:
        members = sorted(part.strip() for part in match.group(1).split(","))
        return "NOT IN (" + ", ".join(members) + ")"

    return re.sub(r"NOT IN \(([^)]*)\)", _sorted_members, normalized)


def test_runbook_coverage_sql_is_pure_ascii() -> None:
    """한글 리터럴이 있으면 PowerShell 인자 왕복에서 조용히 바뀐다 — 글자 수준에서 막는다."""
    assert EXPOSURE_COVERAGE_SQL.isascii()


def test_runbook_coverage_sql_embeds_the_compiled_serving_exposure_gate() -> None:
    """런북 SQL의 노출 조건이 코드의 서빙 게이트와 갈라지면 RED — 노출 정의가 바뀌었는데 측정만 옛
    정의로 남는 상황(측정이 서빙을 설명하지 못하는 상태)을 막는다. 노출 조건은 2곳(분모·분자)에 쓰인다."""
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql

    from whymath_backend.db.models.problem import Problem
    from whymath_backend.l2.next_problem_selection import candidate_pool_conditions

    gate = str(
        sa.select(sa.literal(1))
        .select_from(Problem)
        .where(*candidate_pool_conditions())
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    gate_where = gate.split("WHERE", 1)[1]
    assert _canonical(EXPOSURE_COVERAGE_SQL).count(_canonical(gate_where)) == 2


def test_the_canonicalizer_distinguishes_real_drift() -> None:
    """대조군 — 정규형 비교가 순서·이스케이프 표기 차이는 무시하고 의미 차이는 잡는다."""
    a = "x NOT IN ('EBS', U&'\\D3C9\\AC00\\C6D0')"
    assert _canonical(a) == _canonical("x NOT IN ('평가원', 'EBS')")  # 순서·표기 무시
    assert _canonical(a) != _canonical("x NOT IN ('EBS')")  # 의미 차이는 잡는다
    assert _canonical(a) != _canonical("x NOT IN ('EBS', U&'\\D3C9\\AC00\\C6D1')")  # 한 글자


def test_the_runbook_document_carries_exactly_this_sql() -> None:
    """Kiki가 붙여넣는 문서의 SQL이 테스트가 지키는 상수와 글자 단위로 같다 — 문서만 낡는 것을 막는다."""
    doc_path = _REPO / "docs" / "architecture" / "eos194_problem_publish_caller_surface.md"
    assert doc_path.is_file(), f"런북 문서가 없다(공허 통과 금지): {doc_path}"
    text = doc_path.read_text(encoding="utf-8")
    found = re.findall(r'\$Sql = "(.*)"\n', text)
    assert found == [EXPOSURE_COVERAGE_SQL], "런북 SQL이 상수와 다르거나 블록이 둘 이상이다"
