"""Admin CMS HTTP 계약 동결 — P3-12 (`api/admin_cms.py`, hermetic: 가짜 세션 + 게이트 스파이).

실 PG 종단 간은 `test_admin_cms_integration.py`가 본다(CI는 통합 테스트를 건너뛰므로, CI가 실제로
돌리는 이 파일이 권한·우회 차단의 1차 동결이다).

동결 항목과 **각 항목이 없으면 통과해 버리는 오구현**
--------------------------------------------------
① **권한 없는 사용자의 Publish 요청 주입(지시문 검증 ①)** — 학생·편집자·검수자가 `publish`를 보내면
   403이고 게이트 서비스·DB·감사·commit 중 어느 것도 일어나지 않는다. "403만 보면" 거부 *뒤에*
   쓰기가 일어나는 오구현이 통과하므로 부작용 0을 함께 단언한다.
② **역할×동작 전수 매트릭스** — 한쪽만 보면 "전부 막힌다"·"전부 열린다"가 모두 통과한다. 허용되는
   칸은 게이트가 실제로 호출됐는지를, 거부되는 칸은 호출되지 않았는지를 본다.
③ **워크플로우 우회 차단(지시문 검증 ②)** — 상태·발행 컬럼을 CMS 편집 본문에 실으면 422이고 **행을
   읽기 전에** 거부된다(DB 접근 0). 초안 payload에 포인터·상태 키를 실어도 거부된다.
④ **복합 전용·미정의 전이는 단독 호출 통로가 없다** — 어떤 역할도(관리자 포함) 422.
⑤ **오류 매핑** — 게이트 예외가 안정적인 `code`로 번역되고 거부 시 rollback·commit 0이다.
⑥ **감사** — 쓰기마다 정확히 1행, 문자열 키 리소스는 uuid5 id.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api import admin_cms
from whymath_backend.api._auth import get_current_user
from whymath_backend.api.admin_cms_resources import (
    RESOURCES,
    WORKFLOW_STATE_COLUMNS,
    audit_resource_id,
    get_resource,
)
from whymath_backend.app import create_app
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.concept import Concept
from whymath_backend.db.models.concept_content import ConceptContent
from whymath_backend.db.models.hint import Hint
from whymath_backend.db.models.problem import Problem, ProblemStep
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l3 import publish_gate as gate
from whymath_backend.schema.cms_access import (
    ROLLBACK_CAPABILITY,
    TRANSITION_CAPABILITY,
    CmsCapability,
    has_capability,
)
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.concept_version import ConceptVersion as SchemaConceptVersion
from whymath_backend.schema.concept_version import ConceptVersionPayload
from whymath_backend.schema.enums import (
    ConceptLevel,
    Curriculum,
    EdgeType,
    ReviewStatus,
    Role,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema
from whymath_backend.schema.version_header import (
    TransitionAction,
    VersionGovernance,
    VersionStatus,
)
from whymath_backend.schema.version_lifecycle import UndefinedTransitionError

_A = TransitionAction


def _user(role: Role) -> UserProfile:
    return UserProfile(user_id=uuid.uuid4(), role=role)


_STUDENT = _user(Role.STUDENT)
_EDITOR = _user(Role.CONTENT_EDITOR)
_REVIEWER = _user(Role.CONTENT_REVIEWER)
_PUBLISHER = _user(Role.CONTENT_PUBLISHER)
_ADMIN = _user(Role.CONTENT_ADMIN)
_ALL_USERS = (_STUDENT, _EDITOR, _REVIEWER, _PUBLISHER, _ADMIN)


# ── 가짜 세션 ──────────────────────────────────────────────────────────────────────────


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Result:
    """`execute()` 결과 모사 — 라우터가 부르는 접근자만 구현한다."""

    def __init__(self, rows: list[Any] | None = None, scalar: Any = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else self._scalar

    def scalar_one(self) -> Any:
        return self._scalar

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """AsyncSession 모사 — **어떤 호출이 일어났는지**를 기록한다(거부 시 부작용 0 단언의 근거)."""

    def __init__(
        self, *, get_map: dict[Any, Any] | None = None, results: list[_Result] | None = None
    ) -> None:
        self._get_map = dict(get_map or {})
        self._results = list(results or [])
        self.added: list[Any] = []
        self.statements: list[Any] = []
        self.gets: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def get(self, model: Any, pk: Any) -> Any:
        self.gets.append((model, pk))
        return self._get_map.get(pk)

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return self._results.pop(0) if self._results else _Result()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def flush(self) -> None:
        return None

    @property
    def touched_db(self) -> bool:
        """DB를 한 번이라도 읽거나 썼는가 — 권한 거부는 이것이 False여야 한다."""
        return bool(self.statements or self.gets or self.added or self.commits)

    @property
    def audit_rows(self) -> list[PrivacyAudit]:
        return [o for o in self.added if isinstance(o, PrivacyAudit)]


#: 앱은 모듈에서 한 번만 만든다 — `create_app()`이 약 0.4초라 테스트 269건마다 만들면 CI가 100초를
#: 쓴다. 요청마다 오버라이드를 **전부 지우고 다시 설정**하므로 테스트 간 오염은 없다(xdist는 파일 단위
#: 분배라 한 파일의 테스트는 한 프로세스에서 순차 실행된다).
_APP = create_app()


def _client(user: UserProfile | None, fake: FakeSession) -> TestClient:
    async def _override() -> AsyncIterator[FakeSession]:
        yield fake

    _APP.dependency_overrides.clear()
    _APP.dependency_overrides[get_session] = _override
    if user is not None:
        _APP.dependency_overrides[get_current_user] = lambda: user
    return TestClient(_APP)


# ── 게이트 스파이 ──────────────────────────────────────────────────────────────────────


def _version(
    *,
    status_: VersionStatus = VersionStatus.DRAFT,
    code: str = "CAL-X",
    version_no: int = 1,
    name_ko: str = "개념",
) -> SchemaConceptVersion:
    return SchemaConceptVersion(
        concept_id=code,
        version_no=version_no,
        schema_version="concept-payload@1",
        status=status_,
        payload=ConceptVersionPayload(name_ko=name_ko, level=ConceptLevel.단원),
        governance=VersionGovernance(created_by="tester"),
    )


class GateSpy:
    """`publish_gate`의 DB 함수를 대체한다 — 호출 인자를 기록하고 정해 둔 동작을 한다."""

    def __init__(self) -> None:
        self.apply_calls: list[dict[str, Any]] = []
        self.rollback_calls: list[dict[str, Any]] = []
        self.draft_calls: list[dict[str, Any]] = []
        self.apply_effect: Callable[[], SchemaConceptVersion] | None = None
        self.rollback_effect: Callable[[], gate.RollbackResult] | None = None
        self.versions: list[SchemaConceptVersion] = []

    async def apply_transition(
        self,
        session: Any,
        version_id: uuid.UUID,
        action: Any,
        *,
        actor: str,
        now: Any = None,
        expected_status: VersionStatus | None = None,
    ) -> SchemaConceptVersion:
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

    async def rollback(
        self,
        session: Any,
        concept_code: str,
        *,
        actor: str,
        now: Any = None,
        expected_current_version_id: uuid.UUID | None = None,
    ) -> gate.RollbackResult:
        self.rollback_calls.append(
            {
                "code": concept_code,
                "actor": actor,
                "expected": expected_current_version_id,
            }
        )
        if self.rollback_effect is None:
            raise LookupError("스파이: 개념 없음")
        return self.rollback_effect()

    async def create_draft(self, session: Any, **kwargs: Any) -> SchemaConceptVersion:
        self.draft_calls.append(kwargs)
        return _version(code=kwargs["concept_code"], name_ko=kwargs["payload"].name_ko)

    async def list_versions(self, session: Any, concept_code: str) -> list[SchemaConceptVersion]:
        return list(self.versions)

    async def get_version(self, session: Any, version_id: uuid.UUID) -> SchemaConceptVersion:
        if not self.versions:
            raise LookupError("스파이: 판 없음")
        return self.versions[0]


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> GateSpy:
    s = GateSpy()
    monkeypatch.setattr(admin_cms.gate, "apply_transition", s.apply_transition)
    monkeypatch.setattr(admin_cms.gate, "rollback", s.rollback)
    monkeypatch.setattr(admin_cms.gate, "create_draft", s.create_draft)
    monkeypatch.setattr(admin_cms.gate, "list_versions", s.list_versions)
    monkeypatch.setattr(admin_cms.gate, "get_version", s.get_version)
    return s


def _live_concept(code: str = "CAL-X", **kw: Any) -> Concept:
    return Concept.from_schema(ConceptSchema(code=code, name_ko="미적분", level="단원", **kw))


_VID = uuid.uuid4()
_CID = uuid.uuid4()


# ═══════════════════════════════════════════════════════════════════════════════════════
# ① 인증·모듈 가드 — 모든 CMS 라우트
# ═══════════════════════════════════════════════════════════════════════════════════════


def _cms_routes() -> list[tuple[str, str]]:
    """(메서드, 경로 템플릿) — 앱에서 실제로 서빙되는 `/v1/admin/cms/*` 전수."""
    from whymath_backend.ops.declared_unwired_audit import walk_routes

    routes: list[tuple[str, str]] = []
    for r in walk_routes(_APP.routes):
        path = getattr(r, "path", "")
        if path.startswith("/v1/admin/cms/"):
            for method in sorted(getattr(r, "methods", None) or ()):
                if method not in {"HEAD", "OPTIONS"}:
                    routes.append((method, path))
    return routes


def _fill(path: str) -> str:
    return (
        path.replace("{concept_id}", str(_CID))
        .replace("{version_id}", str(_VID))
        .replace("{pk}", "x1")
    )


def _call(client: TestClient, method: str, path: str) -> Any:
    url = _fill(path)
    if url.endswith("/audit"):
        url += "?resource_type=concept&resource_key=x"
    body: dict[str, Any] = {}
    if method == "PATCH":
        body = {"changes": {"x": 1}}
    elif url.endswith("/transitions"):
        body = {"action": "submit", "expected_status": "DRAFT"}
    elif url.endswith("/rollback"):
        body = {"expected_published_version_id": str(_VID)}
    elif url.endswith("/review"):
        body = {"decision": "reviewed"}
    return client.request(method, url, json=body if method != "GET" else None)


_ROUTES = _cms_routes()


def test_route_inventory_is_not_vacuous() -> None:
    """분모 — 라우트가 통째로 사라져도 아래 전수 검사는 공허하게 통과하므로 개수를 고정한다."""
    assert len(_ROUTES) == 34, f"CMS 라우트 {len(_ROUTES)}건"
    assert sum(1 for m, _ in _ROUTES if m != "GET") == 12


@pytest.mark.parametrize(("method", "path"), _ROUTES, ids=lambda v: str(v))
def test_unauthenticated_request_is_401_everywhere(method: str, path: str) -> None:
    fake = FakeSession()
    resp = _call(_client(None, fake), method, path)
    assert resp.status_code == 401, (method, path, resp.text)
    assert not fake.touched_db


@pytest.mark.parametrize(("method", "path"), _ROUTES, ids=lambda v: str(v))
def test_student_is_403_everywhere_without_touching_the_db(method: str, path: str) -> None:
    fake = FakeSession()
    resp = _call(_client(_STUDENT, fake), method, path)
    assert resp.status_code == 403, (method, path, resp.text)
    assert not fake.touched_db, "거부된 요청이 DB를 건드렸다"


def test_every_cms_route_uses_a_registry_derived_guard() -> None:
    """새 CMS 라우트가 레지스트리 파생 가드를 쓰는지 기존 감사기로 전수 검사한다(분모 포함)."""
    from whymath_backend.ops.admin_guard_audit import audit_admin_route_guards

    violations, scanned = audit_admin_route_guards(_APP)
    assert violations == []
    assert scanned >= len(_ROUTES), f"감사가 CMS 라우트를 다 보지 못했다: {scanned}"


# ═══════════════════════════════════════════════════════════════════════════════════════
# ① 권한 없는 사용자의 Publish 요청 주입
# ═══════════════════════════════════════════════════════════════════════════════════════


class TestPublishInjection:
    @pytest.mark.parametrize("user", [_STUDENT, _EDITOR, _REVIEWER], ids=lambda u: u.role.value)
    def test_unauthorized_roles_cannot_publish(self, user: UserProfile, spy: GateSpy) -> None:
        fake = FakeSession()
        resp = _client(user, fake).post(
            f"/v1/admin/cms/versions/{_VID}/transitions",
            json={"action": "publish", "expected_status": "APPROVED"},
        )
        assert resp.status_code == 403, resp.text
        assert spy.apply_calls == [], "거부된 요청이 게이트 서비스를 호출했다"
        assert not fake.touched_db, "거부된 요청이 DB를 건드렸다(조회·감사·commit)"
        assert fake.audit_rows == []

    @pytest.mark.parametrize("user", [_PUBLISHER, _ADMIN], ids=lambda u: u.role.value)
    def test_publisher_and_admin_reach_the_gate_with_the_actor(
        self, user: UserProfile, spy: GateSpy
    ) -> None:
        spy.apply_effect = lambda: _version(status_=VersionStatus.PUBLISHED)
        fake = FakeSession()
        resp = _client(user, fake).post(
            f"/v1/admin/cms/versions/{_VID}/transitions",
            json={"action": "publish", "expected_status": "APPROVED"},
        )
        assert resp.status_code == 200, resp.text
        assert spy.apply_calls == [
            {
                "version_id": _VID,
                "action": _A.PUBLISH,
                "actor": str(user.user_id),
                "expected_status": VersionStatus.APPROVED,
            }
        ]
        assert fake.commits == 1
        [audit] = fake.audit_rows
        assert (audit.resource_type, audit.action, audit.resource_id) == (
            "concept_version",
            "publish",
            _VID,
        )
        assert audit.user_id == user.user_id
        assert resp.json()["status"] == "PUBLISHED"

    def test_actor_is_the_user_uuid_not_a_pii_string(self, spy: GateSpy) -> None:
        user = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN, nickname="홍길동")
        spy.apply_effect = lambda: _version(status_=VersionStatus.IN_REVIEW)
        resp = _client(user, FakeSession()).post(
            f"/v1/admin/cms/versions/{_VID}/transitions",
            json={"action": "submit", "expected_status": "DRAFT"},
        )
        assert resp.status_code == 200, resp.text
        assert spy.apply_calls[0]["actor"] == str(user.user_id)
        assert "홍길동" not in str(spy.apply_calls)


# ═══════════════════════════════════════════════════════════════════════════════════════
# ② 역할 × 전이 전수 매트릭스
# ═══════════════════════════════════════════════════════════════════════════════════════


class TestTransitionMatrix:
    @pytest.mark.parametrize("action", sorted(TRANSITION_CAPABILITY, key=lambda a: a.value))
    @pytest.mark.parametrize("user", _ALL_USERS, ids=lambda u: u.role.value)
    def test_gate_is_called_iff_the_role_holds_the_capability(
        self, user: UserProfile, action: TransitionAction, spy: GateSpy
    ) -> None:
        spy.apply_effect = lambda: _version(status_=VersionStatus.IN_REVIEW)
        fake = FakeSession()
        resp = _client(user, fake).post(
            f"/v1/admin/cms/versions/{_VID}/transitions",
            json={"action": action.value, "expected_status": "DRAFT"},
        )
        allowed = has_capability(user.role, TRANSITION_CAPABILITY[action])
        if allowed:
            assert resp.status_code == 200, (user.role, action, resp.text)
            assert len(spy.apply_calls) == 1
        else:
            assert resp.status_code == 403, (user.role, action, resp.text)
            assert spy.apply_calls == []
            assert not fake.touched_db

    def test_matrix_has_both_allowed_and_denied_cells(self) -> None:
        """분모 — 전부 허용이거나 전부 거부면 위 매트릭스는 공허하다."""
        cells = [
            has_capability(u.role, c) for u in _ALL_USERS for c in TRANSITION_CAPABILITY.values()
        ]
        assert any(cells) and not all(cells)

    @pytest.mark.parametrize("action", ["supersede", "rollback", "restore", "nope", "PUBLISH", ""])
    @pytest.mark.parametrize("user", [_EDITOR, _ADMIN], ids=lambda u: u.role.value)
    def test_compound_and_unknown_actions_have_no_entry_point(
        self, user: UserProfile, action: str, spy: GateSpy
    ) -> None:
        """④ 관리자도 복합 전용·미정의 전이를 단독으로 부를 수 없다."""
        fake = FakeSession()
        resp = _client(user, fake).post(
            f"/v1/admin/cms/versions/{_VID}/transitions",
            json={"action": action, "expected_status": "DRAFT"},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "unknown_action"
        assert spy.apply_calls == []
        assert not fake.touched_db

    @pytest.mark.parametrize("user", _ALL_USERS, ids=lambda u: u.role.value)
    def test_rollback_requires_publish_capability(self, user: UserProfile, spy: GateSpy) -> None:
        fake = FakeSession(results=[_Result(scalar="CAL-X")])
        resp = _client(user, fake).post(
            f"/v1/admin/cms/concepts/{_CID}/rollback",
            json={"expected_published_version_id": str(_VID)},
        )
        if has_capability(user.role, ROLLBACK_CAPABILITY):
            assert resp.status_code == 404, resp.text  # 스파이가 LookupError — 게이트에 도달했다
            assert len(spy.rollback_calls) == 1
        else:
            assert resp.status_code == 403, resp.text
            assert spy.rollback_calls == []
            assert not fake.touched_db

    @pytest.mark.parametrize("user", _ALL_USERS, ids=lambda u: u.role.value)
    def test_draft_creation_requires_edit_capability(self, user: UserProfile, spy: GateSpy) -> None:
        fake = FakeSession()
        resp = _client(user, fake).post(f"/v1/admin/cms/concepts/{_CID}/drafts", json={})
        if has_capability(user.role, CmsCapability.EDIT):
            assert resp.status_code == 404, resp.text  # 개념 행 없음 — 권한 검사를 통과했다
        else:
            assert resp.status_code == 403, resp.text
            assert not fake.touched_db
        assert spy.draft_calls == []


# ═══════════════════════════════════════════════════════════════════════════════════════
# ⑤ 게이트 예외 → 안정적 코드
# ═══════════════════════════════════════════════════════════════════════════════════════


class TestTransitionErrorMapping:
    def _post(self, spy: GateSpy, exc: Exception) -> tuple[Any, FakeSession]:
        def boom() -> SchemaConceptVersion:
            raise exc

        spy.apply_effect = boom
        fake = FakeSession()
        resp = _client(_ADMIN, fake).post(
            f"/v1/admin/cms/versions/{_VID}/transitions",
            json={"action": "submit", "expected_status": "DRAFT"},
        )
        return resp, fake

    def test_stale_status_is_409_with_the_current_status(self, spy: GateSpy) -> None:
        resp, fake = self._post(
            spy, gate.StaleStatusError(VersionStatus.DRAFT, VersionStatus.IN_REVIEW)
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "stale_status"
        assert resp.json()["detail"]["current_status"] == "IN_REVIEW"
        assert (fake.commits, fake.rollbacks) == (0, 1)
        assert fake.audit_rows == []  # 게이트가 거부하면 감사 행은 만들어지기 전이다

    def test_undefined_transition_is_409(self, spy: GateSpy) -> None:
        resp, fake = self._post(spy, UndefinedTransitionError("미정의"))
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "illegal_transition"
        assert fake.commits == 0

    def test_gate_failure_is_422_with_failures(self, spy: GateSpy) -> None:
        resp, fake = self._post(spy, gate.PublishGateError(None, ["content_hash: 불일치"]))
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "gate_failed"
        assert resp.json()["detail"]["failures"] == ["content_hash: 불일치"]
        assert fake.commits == 0

    def test_gate_kind_is_reported_when_known(self, spy: GateSpy) -> None:
        from whymath_backend.schema.version_header import GateKind

        resp, _ = self._post(spy, gate.PublishGateError(GateKind.PUBLISH, ["x"]))
        assert resp.json()["detail"]["gate"] == "publish"

    def test_missing_version_is_404(self, spy: GateSpy) -> None:
        resp, fake = self._post(spy, LookupError("없음"))
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "not_found"
        assert fake.commits == 0

    def test_unexpected_error_rolls_back_and_propagates(self, spy: GateSpy) -> None:
        def boom() -> SchemaConceptVersion:
            raise RuntimeError("예기치 못한 오류")

        spy.apply_effect = boom
        fake = FakeSession()
        client = _client(_ADMIN, fake)
        client_no_raise = TestClient(client.app, raise_server_exceptions=False)
        resp = client_no_raise.post(
            f"/v1/admin/cms/versions/{_VID}/transitions",
            json={"action": "submit", "expected_status": "DRAFT"},
        )
        assert resp.status_code == 500
        assert (fake.commits, fake.rollbacks) == (0, 1)

    def test_expected_status_must_be_a_known_state(self, spy: GateSpy) -> None:
        resp = _client(_ADMIN, FakeSession()).post(
            f"/v1/admin/cms/versions/{_VID}/transitions",
            json={"action": "submit", "expected_status": "WHATEVER"},
        )
        assert resp.status_code == 422
        assert spy.apply_calls == []


class TestRollbackErrorMapping:
    def _post(self, spy: GateSpy, exc: Exception) -> tuple[Any, FakeSession]:
        def boom() -> gate.RollbackResult:
            raise exc

        spy.rollback_effect = boom
        fake = FakeSession(results=[_Result(scalar="CAL-X")])
        resp = _client(_PUBLISHER, fake).post(
            f"/v1/admin/cms/concepts/{_CID}/rollback",
            json={"expected_published_version_id": str(_VID)},
        )
        return resp, fake

    def test_success_returns_both_versions_and_one_audit_row(self, spy: GateSpy) -> None:
        down, up = uuid.uuid4(), uuid.uuid4()
        spy.rollback_effect = lambda: gate.RollbackResult("CAL-X", down, up)
        fake = FakeSession(results=[_Result(scalar="CAL-X")])
        resp = _client(_PUBLISHER, fake).post(
            f"/v1/admin/cms/concepts/{_CID}/rollback",
            json={"expected_published_version_id": str(_VID)},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "concept_code": "CAL-X",
            "rolled_back_version_id": str(down),
            "restored_version_id": str(up),
        }
        assert spy.rollback_calls == [
            {"code": "CAL-X", "actor": str(_PUBLISHER.user_id), "expected": _VID}
        ]
        [audit] = fake.audit_rows
        assert (audit.resource_type, audit.action, audit.resource_id) == (
            "concept_version",
            "rollback",
            down,
        )
        assert fake.commits == 1

    def test_stale_pointer_is_409(self, spy: GateSpy) -> None:
        actual = uuid.uuid4()
        resp, fake = self._post(spy, gate.StalePublishedPointerError(_VID, actual))
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "stale_pointer"
        assert detail["published_version_id"] == str(actual)
        assert fake.commits == 0

    def test_unavailable_is_409(self, spy: GateSpy) -> None:
        resp, _ = self._post(spy, gate.RollbackUnavailableError("직전 발행본 없음"))
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "rollback_unavailable"

    def test_restore_gate_failure_is_422(self, spy: GateSpy) -> None:
        resp, fake = self._post(spy, gate.PublishGateError(None, ["content_hash: 변조"]))
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "gate_failed"
        assert fake.commits == 0

    def test_illegal_transition_is_409(self, spy: GateSpy) -> None:
        resp, _ = self._post(spy, UndefinedTransitionError("미정의"))
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "illegal_transition"

    def test_missing_concept_is_404_before_the_gate(self, spy: GateSpy) -> None:
        fake = FakeSession(results=[_Result()])
        resp = _client(_PUBLISHER, fake).post(
            f"/v1/admin/cms/concepts/{_CID}/rollback",
            json={"expected_published_version_id": str(_VID)},
        )
        assert resp.status_code == 404
        assert spy.rollback_calls == []

    def test_unexpected_error_rolls_back(self, spy: GateSpy) -> None:
        def boom() -> gate.RollbackResult:
            raise RuntimeError("x")

        spy.rollback_effect = boom
        fake = FakeSession(results=[_Result(scalar="CAL-X")])
        app = _client(_PUBLISHER, fake).app
        resp = TestClient(app, raise_server_exceptions=False).post(
            f"/v1/admin/cms/concepts/{_CID}/rollback",
            json={"expected_published_version_id": str(_VID)},
        )
        assert resp.status_code == 500
        assert fake.rollbacks == 1


# ═══════════════════════════════════════════════════════════════════════════════════════
# 초안 생성 — 편집은 새 판이다
# ═══════════════════════════════════════════════════════════════════════════════════════


class TestDraftCreation:
    def _post(
        self,
        spy: GateSpy,
        body: dict[str, Any],
        *,
        concept: Concept | None = None,
        extra_get: dict[Any, Any] | None = None,
        user: UserProfile = _EDITOR,
    ) -> tuple[Any, FakeSession]:
        live = concept or _live_concept()
        fake = FakeSession(get_map={_CID: live, **(extra_get or {})})
        resp = _client(user, fake).post(f"/v1/admin/cms/concepts/{_CID}/drafts", json=body)
        return resp, fake

    def test_empty_changes_snapshot_the_live_row(self, spy: GateSpy) -> None:
        resp, fake = self._post(spy, {"reason": "첫 판"})
        assert resp.status_code == 201, resp.text
        [call] = spy.draft_calls
        assert call["concept_code"] == "CAL-X"
        assert call["payload"].name_ko == "미적분"
        assert call["created_by"] == str(_EDITOR.user_id)
        assert call["schema_version"] == "concept-payload@1"
        assert call["change"].change_type == "cms_edit"
        assert call["change"].reason == "첫 판"
        assert fake.commits == 1
        [audit] = fake.audit_rows
        assert (audit.resource_type, audit.action) == ("concept_version", "create")

    def test_changes_are_merged_over_the_live_snapshot(self, spy: GateSpy) -> None:
        resp, _ = self._post(spy, {"changes": {"name_ko": "새 이름", "aliases": ["별칭"]}})
        assert resp.status_code == 201, resp.text
        payload = spy.draft_calls[0]["payload"]
        assert (payload.name_ko, payload.aliases) == ("새 이름", ["별칭"])

    def test_latest_version_is_the_base_when_versions_exist(self, spy: GateSpy) -> None:
        spy.versions = [_version(version_no=3, name_ko="v3 이름")]
        resp, _ = self._post(spy, {"changes": {"name_en": "x"}})
        assert resp.status_code == 201, resp.text
        payload = spy.draft_calls[0]["payload"]
        assert payload.name_ko == "v3 이름" and payload.name_en == "x"

    @pytest.mark.parametrize(
        "forbidden",
        [
            {"current_published_version_id": str(uuid.uuid4())},
            {"status": "PUBLISHED"},
            {"published_at": "2026-01-01T00:00:00Z"},
            {"review_status": "approved"},
            {"governance": {"approved_by": "me"}},
            {"qa": {"qa_status": "PASSED"}},
        ],
    )
    def test_publish_and_state_keys_cannot_ride_in_the_payload(
        self, forbidden: dict[str, Any], spy: GateSpy
    ) -> None:
        """③ 초안 payload에 포인터·상태·승인 키를 실어도 `extra=forbid`가 거부한다."""
        resp, fake = self._post(spy, {"changes": forbidden})
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "payload_invalid"
        assert spy.draft_calls == []
        assert fake.commits == 0 and fake.audit_rows == []

    def test_unknown_skill_is_rejected(self, spy: GateSpy, monkeypatch: pytest.MonkeyPatch) -> None:
        async def missing(session: Any, skills: list[str]) -> list[str]:
            return ["SK-없음"]

        monkeypatch.setattr(admin_cms, "_unknown_skills", missing)
        resp, _ = self._post(spy, {"changes": {"behavior_skills": ["SK-없음"]}})
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "unknown_skill"
        assert resp.json()["detail"]["unknown"] == ["SK-없음"]
        assert spy.draft_calls == []

    def test_known_skills_pass(self, spy: GateSpy, monkeypatch: pytest.MonkeyPatch) -> None:
        async def none_missing(session: Any, skills: list[str]) -> list[str]:
            return []

        monkeypatch.setattr(admin_cms, "_unknown_skills", none_missing)
        resp, _ = self._post(spy, {"changes": {"behavior_skills": ["SK-1"]}})
        assert resp.status_code == 201, resp.text
        assert spy.draft_calls[0]["payload"].behavior_skills == ["SK-1"]

    def test_skills_are_not_checked_when_unchanged(
        self, spy: GateSpy, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """기존 행에 낡은 스킬이 있어도 그것을 건드리지 않는 초안은 막지 않는다."""

        async def explode(session: Any, skills: list[str]) -> list[str]:
            raise AssertionError("스킬 조회가 일어나면 안 된다")

        monkeypatch.setattr(admin_cms, "_unknown_skills", explode)
        resp, _ = self._post(spy, {"changes": {"name_en": "x"}})
        assert resp.status_code == 201, resp.text

    def test_parent_cannot_be_self(self, spy: GateSpy) -> None:
        live = _live_concept()
        resp, _ = self._post(
            spy, {"changes": {"parent_concept_id": str(live.concept_id)}}, concept=live
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "parent_is_self"

    def test_parent_must_exist(self, spy: GateSpy) -> None:
        resp, _ = self._post(spy, {"changes": {"parent_concept_id": str(uuid.uuid4())}})
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "unknown_parent"

    def test_existing_parent_is_accepted(self, spy: GateSpy) -> None:
        parent = _live_concept("CAL-P")
        resp, _ = self._post(
            spy,
            {"changes": {"parent_concept_id": str(parent.concept_id)}},
            extra_get={parent.concept_id: parent},
        )
        assert resp.status_code == 201, resp.text

    def test_invalid_value_is_a_payload_error(self, spy: GateSpy) -> None:
        resp, _ = self._post(spy, {"changes": {"level": "없는레벨"}})
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "payload_invalid"
        assert resp.json()["detail"]["field"] == "level"

    def test_unknown_request_fields_are_rejected(self, spy: GateSpy) -> None:
        resp, _ = self._post(spy, {"changes": {}, "created_by": "attacker"})
        assert resp.status_code == 422

    def test_missing_concept_is_404(self, spy: GateSpy) -> None:
        fake = FakeSession()
        resp = _client(_ADMIN, fake).post(f"/v1/admin/cms/concepts/{_CID}/drafts", json={})
        assert resp.status_code == 404
        assert spy.draft_calls == []

    def test_create_failure_rolls_back(self, spy: GateSpy, monkeypatch: pytest.MonkeyPatch) -> None:
        async def broken(session: Any, **kwargs: Any) -> SchemaConceptVersion:
            raise RuntimeError("DB 오류")

        monkeypatch.setattr(admin_cms.gate, "create_draft", broken)  # spy 위에 덮어쓴다
        fake = FakeSession(get_map={_CID: _live_concept()})
        app = _client(_EDITOR, fake).app
        resp = TestClient(app, raise_server_exceptions=False).post(
            f"/v1/admin/cms/concepts/{_CID}/drafts", json={}
        )
        assert resp.status_code == 500
        assert fake.rollbacks == 1 and fake.commits == 0


# ═══════════════════════════════════════════════════════════════════════════════════════
# 개념 읽기 · 버전 읽기
# ═══════════════════════════════════════════════════════════════════════════════════════


class TestConceptAndVersionReads:
    def test_concept_list_shape_and_has_published_flag(self) -> None:
        a = _live_concept("CAL-A")
        b = _live_concept("CAL-B")
        b.current_published_version_id = uuid.uuid4()
        # DB에서 읽은 행의 `level`은 열거형 멤버다(`from_schema` 직후의 가짜 행은 평범한 문자열일 수
        # 있다) — 실물 모양을 흉내 내야 `(str, Enum)` 멤버가 이름 문자열로 새는 결함이 보인다.
        a.level = ConceptLevel.단원
        b.level = ConceptLevel.단원
        fake = FakeSession(results=[_Result(scalar=2), _Result(rows=[a, b])])
        resp = _client(_EDITOR, fake).get("/v1/admin/cms/concepts?q=CAL&limit=10")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2 and body["limit"] == 10 and body["offset"] == 0
        assert [(i["code"], i["has_published_version"]) for i in body["items"]] == [
            ("CAL-A", False),
            ("CAL-B", True),
        ]
        # 계층은 열거형 이름("ConceptLevel.단원")이 아니라 값("단원")으로 나간다.
        assert [i["level"] for i in body["items"]] == ["단원", "단원"]

    def test_concept_list_rejects_out_of_range_paging(self) -> None:
        for query in ("limit=0", "limit=101", "offset=-1"):
            resp = _client(_EDITOR, FakeSession()).get(f"/v1/admin/cms/concepts?{query}")
            assert resp.status_code == 422, query

    def test_concept_detail_exposes_live_fields_edges_and_never_the_body_columns(
        self, spy: GateSpy
    ) -> None:
        live = _live_concept(name_en="Calculus")
        other = _live_concept("CAL-O")
        edge = SimpleNamespaceEdge()
        fake = FakeSession(
            get_map={_CID: live},
            results=[_Result(rows=[(edge, other)]), _Result(rows=[])],
        )
        spy.versions = [_version(version_no=2)]
        resp = _client(_REVIEWER, fake).get(f"/v1/admin/cms/concepts/{_CID}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == "CAL-X"
        assert body["latest_version_no"] == 2
        assert body["published_version_id"] is None
        assert body["can_edit"] is False  # 검수자는 편집 권한이 없다
        assert [(e["other_code"], e["edge_type"]) for e in body["incoming"]] == [
            ("CAL-O", "PREREQUISITE")
        ]
        assert body["outgoing"] == []
        # payload 필드만 — 본문 3종·오버레이는 live에 없다(Concept Purity).
        assert set(body["live"]) <= set(ConceptVersionPayload.model_fields)
        assert "description" not in body["live"] and "formal_definition" not in body["live"]

    def test_concept_detail_404(self) -> None:
        resp = _client(_ADMIN, FakeSession()).get(f"/v1/admin/cms/concepts/{_CID}")
        assert resp.status_code == 404

    def test_version_list_marks_only_actions_the_caller_may_run(self, spy: GateSpy) -> None:
        spy.versions = [_version(status_=VersionStatus.IN_REVIEW)]
        fake = FakeSession(results=[_Result(scalar="CAL-X")])
        as_reviewer = _client(_REVIEWER, fake).get(f"/v1/admin/cms/concepts/{_CID}/versions")
        assert as_reviewer.status_code == 200, as_reviewer.text
        # IN_REVIEW에서 전이표가 허용하는 것은 pass_review·request_changes — 둘 다 검수 권한이다.
        assert sorted(as_reviewer.json()[0]["allowed_actions"]) == [
            "pass_review",
            "request_changes",
        ]
        fake2 = FakeSession(results=[_Result(scalar="CAL-X")])
        as_editor = _client(_EDITOR, fake2).get(f"/v1/admin/cms/concepts/{_CID}/versions")
        assert as_editor.json()[0]["allowed_actions"] == []  # 편집자는 검토 단계를 못 움직인다

    def test_version_list_for_missing_concept_is_404(self) -> None:
        resp = _client(_ADMIN, FakeSession(results=[_Result()])).get(
            f"/v1/admin/cms/concepts/{_CID}/versions"
        )
        assert resp.status_code == 404

    def test_version_detail_includes_payload_and_gate_records(self, spy: GateSpy) -> None:
        spy.versions = [_version(status_=VersionStatus.APPROVED)]
        resp = _client(_PUBLISHER, FakeSession()).get(f"/v1/admin/cms/versions/{_VID}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["summary"]["status"] == "APPROVED"
        assert body["summary"]["allowed_actions"] == ["publish"]
        assert body["payload"]["name_ko"] == "개념"
        assert body["gate_records"] == []

    def test_version_detail_404(self, spy: GateSpy) -> None:
        resp = _client(_ADMIN, FakeSession()).get(f"/v1/admin/cms/versions/{_VID}")
        assert resp.status_code == 404


class SimpleNamespaceEdge:
    """`ConceptEdge` 모사 — `edge_type`만 쓴다.

    값은 평범한 문자열이 아니라 **실제 열거형 멤버**다. 문자열 "x"를 쓰면 `(str, Enum)` 멤버가
    `'EdgeType.PREREQUISITE'`로 새는 결함을 못 본다(실백엔드 종단 검증에서 발견).
    """

    edge_type = EdgeType.PREREQUISITE


# ═══════════════════════════════════════════════════════════════════════════════════════
# ③ 개념 외 리소스 — 허용 목록 제자리 편집
# ═══════════════════════════════════════════════════════════════════════════════════════

_EDITABLE = [spec for spec in RESOURCES if spec.editable]


class TestWorkflowBypassInjection:
    @pytest.mark.parametrize("column", ["review_status", "is_published", "status", "verified"])
    @pytest.mark.parametrize("spec", _EDITABLE, ids=lambda s: s.key)
    def test_state_columns_are_rejected_before_any_db_access(self, spec: Any, column: str) -> None:
        """③ 상태·발행 컬럼을 CMS 편집 본문에 실으면 422이고 DB 접근이 0이다."""
        fake = FakeSession()
        resp = _client(_ADMIN, fake).patch(
            f"/v1/admin/cms/{spec.key}/items/{uuid.uuid4()}",
            json={"changes": {column: "approved"}},
        )
        assert resp.status_code == 422, (spec.key, column, resp.text)
        assert resp.json()["detail"]["code"] == "field_not_editable"
        assert resp.json()["detail"]["field"] == column
        assert not fake.touched_db

    @pytest.mark.parametrize("column", sorted(WORKFLOW_STATE_COLUMNS))
    def test_every_state_column_is_rejected_on_a_state_bearing_resource(self, column: str) -> None:
        fake = FakeSession()
        resp = _client(_ADMIN, fake).patch(
            "/v1/admin/cms/concept_content/items/CODE-1", json={"changes": {column: "reviewed"}}
        )
        assert resp.status_code == 422
        assert not fake.touched_db

    def test_mixed_request_is_rejected_whole(self) -> None:
        """허용 필드와 금지 필드가 섞이면 허용 필드도 적용되지 않는다(부분 적용 없음)."""
        fake = FakeSession()
        resp = _client(_ADMIN, fake).patch(
            "/v1/admin/cms/concept_content/items/CODE-1",
            json={"changes": {"explanation": "ok", "review_status": "reviewed"}},
        )
        assert resp.status_code == 422
        assert not fake.touched_db and fake.commits == 0

    def test_read_only_resource_has_no_write_route(self) -> None:
        for method in ("PATCH", "POST", "DELETE", "PUT"):
            resp = _client(_ADMIN, FakeSession()).request(
                method, "/v1/admin/cms/skill_node/items/SK1", json={"changes": {"name_ko": "x"}}
            )
            assert resp.status_code in (404, 405), (method, resp.status_code)

    def test_no_delete_or_create_route_exists_for_any_resource(self) -> None:
        """CMS는 제자리 편집만 한다 — 생성·삭제 통로가 없다(검수 없는 노출·삭제 방지)."""
        for spec in RESOURCES:
            for method in ("POST", "DELETE", "PUT"):
                resp = _client(_ADMIN, FakeSession()).request(
                    method, f"/v1/admin/cms/{spec.key}", json={}
                )
                assert resp.status_code in (404, 405), (spec.key, method, resp.status_code)

    def test_unknown_body_keys_are_rejected(self) -> None:
        resp = _client(_ADMIN, FakeSession()).patch(
            "/v1/admin/cms/hint/items/H1", json={"changes": {"content": "x"}, "verified": True}
        )
        assert resp.status_code == 422


def _concept_content_row(**kw: Any) -> ConceptContent:
    values: dict[str, Any] = {
        "code": "C-1",
        "scope": "K12",
        "name": "개념",
        "subject": "수학",
        "explanation": "옛 설명",
        "review_status": "reviewed",
        "flashcards": [],
        "standard_codes": [],
        "atom_codes": [],
    }
    values.update(kw)
    return ConceptContent(**values)


class TestInPlaceEdit:
    def test_edit_writes_field_lowers_review_and_audits_once(self) -> None:
        row = _concept_content_row()
        fake = FakeSession(results=[_Result(rows=[row]), _Result(rows=[row])])
        resp = _client(_EDITOR, fake).patch(
            "/v1/admin/cms/concept_content/items/C-1", json={"changes": {"explanation": "새 설명"}}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["changed"] == ["explanation"]
        assert body["server_reset"] == ["review_status"]
        assert row.explanation == "새 설명"
        assert row.review_status == "ai_estimated"  # 검수가 내려갔다
        assert fake.commits == 1
        [audit] = fake.audit_rows
        spec = get_resource("concept_content")
        assert (audit.resource_type, audit.action) == ("concept_content", "update")
        assert audit.resource_id == audit_resource_id(spec, "C-1")
        assert audit.user_id == _EDITOR.user_id

    def test_edit_marks_the_row_so_the_next_load_skips_it(self) -> None:
        """P3-25 — 편집이 `cms_edited_at`을 채워야 CLI 적재가 그 행을 건너뛴다."""
        row = _concept_content_row()
        assert row.cms_edited_at is None
        fake = FakeSession(results=[_Result(rows=[row]), _Result(rows=[row])])
        resp = _client(_EDITOR, fake).patch(
            "/v1/admin/cms/concept_content/items/C-1", json={"changes": {"explanation": "새 설명"}}
        )
        assert resp.status_code == 200, resp.text
        assert row.cms_edited_at is not None

    def test_noop_edit_does_not_take_ownership_from_the_loader(self) -> None:
        """같은 값 저장은 아무것도 안 바꾼다 — 표지도 채우지 않는다(적재 소유권 유지)."""
        row = _concept_content_row()
        fake = FakeSession(results=[_Result(rows=[row]), _Result(rows=[row])])
        _client(_EDITOR, fake).patch(
            "/v1/admin/cms/concept_content/items/C-1",
            json={"changes": {"explanation": row.explanation}},
        )
        assert row.cms_edited_at is None

    def test_same_value_is_a_noop_keeping_review_and_not_committing(self) -> None:
        row = _concept_content_row()
        fake = FakeSession(results=[_Result(rows=[row]), _Result(rows=[row])])
        resp = _client(_EDITOR, fake).patch(
            "/v1/admin/cms/concept_content/items/C-1", json={"changes": {"explanation": "옛 설명"}}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["changed"] == [] and resp.json()["server_reset"] == []
        assert row.review_status == "reviewed"
        assert fake.commits == 0 and fake.audit_rows == []
        assert fake.rollbacks == 1  # 바뀐 것이 없으면 잠금을 일찍 푼다

    @pytest.mark.parametrize("user", [_STUDENT, _REVIEWER, _PUBLISHER], ids=lambda u: u.role.value)
    def test_only_edit_capability_may_edit(self, user: UserProfile) -> None:
        fake = FakeSession()
        resp = _client(user, fake).patch(
            "/v1/admin/cms/hint/items/H1", json={"changes": {"content": "x"}}
        )
        assert resp.status_code == 403
        assert not fake.touched_db

    def test_missing_row_is_404(self) -> None:
        resp = _client(_EDITOR, FakeSession()).patch(
            "/v1/admin/cms/hint/items/NOPE", json={"changes": {"content": "x"}}
        )
        assert resp.status_code == 404

    def test_malformed_key_is_404_not_a_500(self) -> None:
        resp = _client(_EDITOR, FakeSession()).patch(
            "/v1/admin/cms/misconception/items/a%20b", json={"changes": {"severity": "local"}}
        )
        assert resp.status_code == 404

    def test_invalid_value_is_422_with_field(self) -> None:
        resp = _client(_EDITOR, FakeSession()).patch(
            "/v1/admin/cms/misconception/items/M1", json={"changes": {"severity": "치명적"}}
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "choice"
        assert resp.json()["detail"]["field"] == "severity"

    def test_hint_edit_clears_verified(self) -> None:
        hint = Hint(
            hint_id="H1",
            solution_path_id="sp",
            step_order=1,
            problem_id=uuid.uuid4(),
            level=1,
            content="옛",
            verified=True,
        )
        fake = FakeSession(results=[_Result(rows=[hint]), _Result(rows=[hint])])
        resp = _client(_EDITOR, fake).patch(
            "/v1/admin/cms/hint/items/H1", json={"changes": {"content": "새"}}
        )
        assert resp.status_code == 200, resp.text
        assert hint.verified is False and hint.content == "새"
        assert resp.json()["server_reset"] == ["verified"]

    def test_integrity_error_is_409_and_rolls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from sqlalchemy.exc import IntegrityError

        row = _concept_content_row()
        fake = FakeSession(results=[_Result(rows=[row])])

        async def failing_commit() -> None:
            raise IntegrityError("UPDATE", {}, Exception("충돌"))

        monkeypatch.setattr(fake, "commit", failing_commit)
        resp = _client(_EDITOR, fake).patch(
            "/v1/admin/cms/concept_content/items/C-1", json={"changes": {"explanation": "새"}}
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "conflict"
        assert fake.rollbacks >= 1


def _problem_row(
    review_status: ReviewStatus | None, source: SourceType = SourceType.자체생성
) -> Problem:
    row = Problem.from_schema(
        ProblemSchema(
            source_type=source,
            curriculum_version=Curriculum.REVISION_2015,
            valid_from_year=2014,
            subject=Subject.미적분,
            unit_codes=["CAL-INT-DEF"],
            review_status=review_status,
        )
    )
    return row


class TestProblemEditGuard:
    def _patch(self, row: Problem, changes: dict[str, Any], user: UserProfile = _EDITOR) -> Any:
        fake = FakeSession(results=[_Result(rows=[row]), _Result(rows=[row])])
        resp = _client(user, fake).patch(
            f"/v1/admin/cms/problem/items/{row.problem_id}", json={"changes": changes}
        )
        return resp, fake

    def test_approved_problem_cannot_be_edited_in_place(self) -> None:
        """승인된 문항은 서빙 중이다 — 제자리 수정은 검수 없는 변경이다. 먼저 격리해야 한다."""
        row = _problem_row(ReviewStatus.approved)
        resp, fake = self._patch(row, {"answer": "바뀐 정답"})
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "edit_blocked"
        assert row.answer != "바뀐 정답"
        assert fake.commits == 0 and fake.audit_rows == []

    @pytest.mark.parametrize(
        "state", [None, ReviewStatus.pending, ReviewStatus.rejected, ReviewStatus.quarantined]
    )
    def test_non_approved_problem_can_be_edited(self, state: ReviewStatus | None) -> None:
        row = _problem_row(state)
        resp, fake = self._patch(row, {"answer": "고친 정답", "difficulty_overall": 3.5})
        assert resp.status_code == 200, resp.text
        assert row.answer == "고친 정답"
        assert row.review_status == state  # 편집이 검수 상태를 건드리지 않는다
        assert fake.commits == 1

    def test_edit_never_changes_review_status_even_to_approve(self) -> None:
        row = _problem_row(ReviewStatus.pending)
        resp, _ = self._patch(row, {"answer": "x", "review_status": "approved"})
        assert resp.status_code == 422
        assert row.review_status == ReviewStatus.pending

    def test_copyright_restricted_source_cannot_gain_a_body(self) -> None:
        row = _problem_row(ReviewStatus.pending, source=SourceType.평가원)
        resp, fake = self._patch(row, {"question_text": "복제된 본문"})
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "schema"
        assert fake.commits == 0

    def test_difficulty_is_validated_as_a_number(self) -> None:
        row = _problem_row(None)
        resp, _ = self._patch(row, {"difficulty_overall": "어려움"})
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "type"


class TestProblemStepEditGuard:
    def _patch(self, parent_state: ReviewStatus | None, *, orphan: bool = False) -> Any:
        parent = _problem_row(parent_state)
        step = ProblemStep(
            step_id=uuid.uuid4(),
            problem_id=None if orphan else parent.problem_id,
            step_order=1,
            expected_answer="1",
            sympy_verified=True,
        )
        if orphan:
            results = [_Result(rows=[step]), _Result(rows=[step])]
        else:
            # 단계 잠금 → 부모 공유잠금(편집 가드) → [쓰기] → 단계 재조회 → 부모(상세의 가드 설명)
            results = [
                _Result(rows=[step]),
                _Result(rows=[parent]),
                _Result(rows=[step]),
                _Result(rows=[parent]),
            ]
        fake = FakeSession(results=results)
        resp = _client(_EDITOR, fake).patch(
            f"/v1/admin/cms/problem_step/items/{step.step_id}",
            json={"changes": {"expected_answer": "2"}},
        )
        return resp, fake, step

    def test_step_of_an_approved_problem_is_blocked(self) -> None:
        resp, fake, step = self._patch(ReviewStatus.approved)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "edit_blocked"
        assert step.expected_answer == "1" and fake.commits == 0

    def test_step_of_a_pending_problem_is_editable_and_unverifies(self) -> None:
        resp, fake, step = self._patch(ReviewStatus.pending)
        assert resp.status_code == 200, resp.text
        assert step.expected_answer == "2"
        assert step.sympy_verified is None  # '모름'으로 되돌렸다
        assert fake.commits == 1

    def test_parentless_step_is_editable(self) -> None:
        resp, _, step = self._patch(None, orphan=True)
        assert resp.status_code == 200, resp.text
        assert step.expected_answer == "2"


class TestReviewMark:
    def _post(
        self, user: UserProfile, row: ConceptContent, decision: str
    ) -> tuple[Any, FakeSession]:
        fake = FakeSession(results=[_Result(rows=[row])])
        resp = _client(user, fake).post(
            "/v1/admin/cms/concept_content/items/C-1/review", json={"decision": decision}
        )
        return resp, fake

    def test_reviewer_can_raise_the_mark_with_an_approve_audit(self) -> None:
        row = _concept_content_row(review_status="ai_estimated")
        resp, fake = self._post(_REVIEWER, row, "reviewed")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"changed": True, "review_status": "reviewed"}
        assert row.review_status == "reviewed"
        assert fake.commits == 1
        assert fake.audit_rows[0].action == "approve"

    @pytest.mark.parametrize("decision", ["reviewed", "needs_review"])
    def test_review_mark_also_marks_the_row_for_the_loader(self, decision: str) -> None:
        """검수 표시도 사람의 쓰기 — 적재가 `reviewed`를 코퍼스 값으로 되돌리면 안 된다(P3-25)."""
        start = "ai_estimated" if decision == "reviewed" else "reviewed"
        row = _concept_content_row(review_status=start)
        resp, _fake = self._post(_REVIEWER, row, decision)
        assert resp.status_code == 200, resp.text
        assert row.cms_edited_at is not None

    def test_noop_review_does_not_mark_the_row(self) -> None:
        row = _concept_content_row(review_status="reviewed")
        self._post(_REVIEWER, row, "reviewed")
        assert row.cms_edited_at is None

    def test_reviewer_can_lower_the_mark_with_a_reject_audit(self) -> None:
        row = _concept_content_row(review_status="reviewed")
        resp, fake = self._post(_REVIEWER, row, "needs_review")
        assert resp.json() == {"changed": True, "review_status": "ai_estimated"}
        assert fake.audit_rows[0].action == "reject"

    def test_same_state_is_a_noop(self) -> None:
        row = _concept_content_row(review_status="reviewed")
        resp, fake = self._post(_REVIEWER, row, "reviewed")
        assert resp.json() == {"changed": False, "review_status": "reviewed"}
        assert fake.commits == 0 and fake.audit_rows == []

    @pytest.mark.parametrize("user", [_STUDENT, _EDITOR, _PUBLISHER], ids=lambda u: u.role.value)
    def test_only_review_capability_may_mark(self, user: UserProfile) -> None:
        """편집자가 자기가 고친 설명을 스스로 '검수됨'으로 올릴 수 없다 — 직무 분리."""
        row = _concept_content_row(review_status="ai_estimated")
        resp, fake = self._post(user, row, "reviewed")
        assert resp.status_code == 403
        assert row.review_status == "ai_estimated"
        assert not fake.touched_db

    def test_decision_vocabulary_is_closed(self) -> None:
        row = _concept_content_row()
        resp, _ = self._post(_ADMIN, row, "approved")
        assert resp.status_code == 422

    def test_resources_without_a_review_column_have_no_review_route(self) -> None:
        for key in ("hint", "problem", "problem_step", "misconception", "curriculum_version"):
            resp = _client(_ADMIN, FakeSession()).post(
                f"/v1/admin/cms/{key}/items/X1/review", json={"decision": "reviewed"}
            )
            assert resp.status_code in (404, 405), key

    def test_strategy_node_review_route_exists_and_audits_under_its_own_type(self) -> None:
        from whymath_backend.db.models.strategy_node import StrategyNode

        node = StrategyNode(
            strategy_id="ST-1",
            name_ko="전략",
            family="f",
            description="d",
            review_status="ai_estimated",
        )
        fake = FakeSession(results=[_Result(rows=[node])])
        resp = _client(_REVIEWER, fake).post(
            "/v1/admin/cms/strategy_node/items/ST-1/review", json={"decision": "reviewed"}
        )
        assert resp.status_code == 200, resp.text
        assert fake.audit_rows[0].resource_type == "strategy_node"


# ═══════════════════════════════════════════════════════════════════════════════════════
# 목록·상세·메타·감사 이력
# ═══════════════════════════════════════════════════════════════════════════════════════


class TestGenericReads:
    def test_list_shape_truncates_long_text_and_reports_total(self) -> None:
        row = _concept_content_row(name="가" * 200)
        fake = FakeSession(results=[_Result(scalar=1), _Result(rows=[row])])
        resp = _client(_PUBLISHER, fake).get("/v1/admin/cms/concept_content?q=가&limit=5")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1 and body["limit"] == 5
        assert body["columns"] == ["code", "name", "scope", "review_status"]
        name = body["items"][0]["name"]
        assert name.endswith("…") and len(name) == 81

    def test_list_without_search_column_filter(self) -> None:
        fake = FakeSession(results=[_Result(scalar=0), _Result(rows=[])])
        resp = _client(_EDITOR, fake).get("/v1/admin/cms/skill_node")
        assert resp.status_code == 200, resp.text
        assert resp.json()["items"] == [] and resp.json()["total"] == 0

    def test_detail_returns_only_declared_columns(self) -> None:
        """선언한 컬럼만 나간다 — `formal_definition_internal` 같은 내부 필드는 새지 않는다."""
        row = _concept_content_row(formal_definition_internal="내부 정의")
        fake = FakeSession(results=[_Result(rows=[row])])
        resp = _client(_EDITOR, fake).get("/v1/admin/cms/concept_content/items/C-1")
        assert resp.status_code == 200, resp.text
        values = resp.json()["values"]
        assert set(values) == set(get_resource("concept_content").detail_columns)
        assert "formal_definition_internal" not in values
        assert "내부 정의" not in resp.text

    def test_detail_shows_editable_fields_only_to_editors(self) -> None:
        row = _concept_content_row()
        as_editor = _client(_EDITOR, FakeSession(results=[_Result(rows=[row])])).get(
            "/v1/admin/cms/concept_content/items/C-1"
        )
        assert [f["name"] for f in as_editor.json()["fields"]] == [
            "explanation",
            "metaphor",
            "misconception",
        ]
        assert as_editor.json()["can_review"] is False
        as_reviewer = _client(_REVIEWER, FakeSession(results=[_Result(rows=[row])])).get(
            "/v1/admin/cms/concept_content/items/C-1"
        )
        assert as_reviewer.json()["fields"] == [] and as_reviewer.json()["can_review"] is True

    def test_detail_explains_why_an_approved_problem_is_not_editable(self) -> None:
        row = _problem_row(ReviewStatus.approved)
        fake = FakeSession(results=[_Result(rows=[row])])
        resp = _client(_EDITOR, fake).get(f"/v1/admin/cms/problem/items/{row.problem_id}")
        assert resp.status_code == 200, resp.text
        assert "격리" in resp.json()["edit_blocked_reason"]

    def test_detail_404(self) -> None:
        resp = _client(_EDITOR, FakeSession()).get("/v1/admin/cms/hint/items/NOPE")
        assert resp.status_code == 404

    def test_resources_meta_lists_everything_and_the_callers_capabilities(self) -> None:
        resp = _client(_EDITOR, FakeSession()).get("/v1/admin/cms/resources")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [r["key"] for r in body["resources"]] == [s.key for s in RESOURCES]
        assert body["capabilities"] == ["edit", "view"]
        skill = next(r for r in body["resources"] if r["key"] == "skill_node")
        assert skill["read_only"] is True and skill["fields"] == []
        content = next(r for r in body["resources"] if r["key"] == "concept_content")
        assert content["reviewable"] is True

    def test_resources_meta_route_is_derived_from_the_owning_module(self) -> None:
        """화면은 이 `route`로 자기 리소스를 고른다 — 레지스트리 값과 한 글자도 달라선 안 된다.

        선언의 `module_id`가 가드의 모듈과 같다는 것은 별도 테스트가 동결하므로, 여기서는 응답의
        `route`가 그 모듈의 레지스트리 경로와 같음과 — 비어 있거나 `/admin` 밖이 아님 — 을 본다.
        """
        from whymath_backend.api.admin_module_registry import get_module

        resp = _client(_EDITOR, FakeSession()).get("/v1/admin/cms/resources")
        assert resp.status_code == 200, resp.text
        by_key = {r["key"]: r["route"] for r in resp.json()["resources"]}
        assert set(by_key) == {s.key for s in RESOURCES}, "리소스 누락"
        for spec in RESOURCES:
            route = by_key[spec.key]
            assert route == get_module(spec.module_id).route, spec.key
            assert route.startswith("/admin/") and not route.endswith("/"), (spec.key, route)
        # 한 화면에 여러 리소스가 실리는 것은 의도다(콘텐츠 라이브러리) — 모수가 1이면 그 기능은 공허하다.
        assert len({r for r in by_key.values()}) < len(by_key)

    def test_resources_meta_audit_type_matches_the_declaration(self) -> None:
        """변경이력 조회 종류를 서버가 명시로 내린다 — 읽기 전용 리소스만 None이다."""
        resp = _client(_EDITOR, FakeSession()).get("/v1/admin/cms/resources")
        assert resp.status_code == 200, resp.text
        by_key = {r["key"]: r["audit_type"] for r in resp.json()["resources"]}
        for spec in RESOURCES:
            expected = spec.audit_type.value if spec.audit_type is not None else None
            assert by_key[spec.key] == expected, spec.key
        assert by_key["skill_node"] is None  # 읽기 전용 — 쓰기가 없으니 이력도 없다
        assert by_key["problem"] is not None  # 대조군: 쓰기 리소스는 종류가 있다

    def test_resources_meta_pk_column_is_a_listed_column(self) -> None:
        """화면은 이 컬럼 값으로 상세를 연다 — 목록 컬럼에 없으면 행을 열 수 없다."""
        resp = _client(_EDITOR, FakeSession()).get("/v1/admin/cms/resources")
        assert resp.status_code == 200, resp.text
        by_key = {r["key"]: r for r in resp.json()["resources"]}
        for spec in RESOURCES:
            meta = by_key[spec.key]
            assert meta["pk_column"] == spec.pk, spec.key
            assert meta["pk_column"] in meta["list_columns"], spec.key


class TestAuditHistory:
    def _get(self, query: str, fake: FakeSession | None = None, user: UserProfile = _EDITOR) -> Any:
        return _client(user, fake or FakeSession()).get(f"/v1/admin/cms/audit?{query}")

    def test_unknown_resource_type_is_422(self) -> None:
        assert self._get("resource_type=nope&resource_key=x").status_code == 422

    def test_bad_key_is_404(self) -> None:
        assert self._get("resource_type=problem&resource_key=not-a-uuid").status_code == 404
        assert self._get("resource_type=concept_version&resource_key=zzz").status_code == 404
        assert self._get("resource_type=misconception&resource_key=a/b").status_code == 404

    def test_rows_are_mapped_and_the_limit_is_disclosed(self) -> None:
        actor = uuid.uuid4()
        row = PrivacyAudit(user_id=actor, event_kind="content_mutation", action="publish")
        fake = FakeSession(results=[_Result(rows=[row])])
        resp = self._get(f"resource_type=concept_version&resource_key={_VID}", fake)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["items"] == [
            {"action": "publish", "actor_user_id": str(actor), "occurred_at": None}
        ]
        assert "diff" in body["note"] or "기록되지 않습니다" in body["note"]

    def test_string_key_resources_are_looked_up_by_their_uuid5(self) -> None:
        fake = FakeSession(results=[_Result(rows=[])])
        resp = self._get("resource_type=misconception&resource_key=M0425", fake)
        assert resp.status_code == 200, resp.text
        expected = audit_resource_id(get_resource("misconception"), "M0425")
        compiled = str(fake.statements[0].compile(compile_kwargs={"literal_binds": False}))
        params = fake.statements[0].compile().params
        assert expected in params.values(), compiled

    @pytest.mark.parametrize("user", [_STUDENT], ids=lambda u: u.role.value)
    def test_student_cannot_read_history(self, user: UserProfile) -> None:
        fake = FakeSession()
        assert self._get("resource_type=problem&resource_key=x", fake, user).status_code == 403
        assert not fake.touched_db


def test_difficulty_range_is_enforced_before_the_row_is_read() -> None:
    """선언의 범위(1.0~5.0)가 서버 검증으로 작동한다 — 범위 밖은 행을 읽기 전에 422."""
    for bad in (0.4, 5.1, -1):
        fake = FakeSession()
        resp = _client(_ADMIN, fake).patch(
            f"/v1/admin/cms/problem/items/{uuid.uuid4()}",
            json={"changes": {"difficulty_overall": bad}},
        )
        assert resp.status_code == 422, bad
        assert resp.json()["detail"]["code"] == "range"
        assert not fake.touched_db


# ═══════════════════════════════════════════════════════════════════════════════════════
# 트랜잭션 경계 뒤에는 ORM 사용자 객체를 읽지 않는다 (실 DB 통합 테스트가 잡은 결함의 회귀 방지)
# ═══════════════════════════════════════════════════════════════════════════════════════


class ExpiredUserError(RuntimeError):
    """`MissingGreenlet`의 모사 — 만료된 ORM 객체 속성을 비동기 컨텍스트에서 읽었다."""


class _ExpiringUser:
    """`commit`/`rollback` 뒤에 `role`·`user_id`를 읽으면 터지는 인증 사용자.

    실제 `AsyncSession`은 `rollback()`(그리고 `expire_on_commit=True`면 `commit()`)에서 세션의 모든 객체를
    만료시키고, 만료된 속성을 읽으면 동기 IO를 시도하다 `MissingGreenlet`이 난다. 가짜 세션은 만료를
    모사하지 않아 이 결함을 못 본다 — 그래서 사용자 객체 쪽에서 만료를 흉내 낸다.
    """

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
        return None  # 데모 판정은 요청 맨 앞(가드)에서만 읽는다


def _expiring_client(real: UserProfile, fake: FakeSession) -> TestClient:
    async def _override() -> AsyncIterator[FakeSession]:
        yield fake

    _APP.dependency_overrides.clear()
    _APP.dependency_overrides[get_session] = _override
    _APP.dependency_overrides[get_current_user] = lambda: _ExpiringUser(real, fake)
    return TestClient(_APP)


class TestNoUserAccessAfterTheTransactionBoundary:
    def test_noop_edit_responds_after_rollback_without_touching_the_user(self) -> None:
        """실 DB에서 터진 경로: 같은 값 재저장 → `rollback()` → 응답 생성."""
        row = _concept_content_row()
        fake = FakeSession(results=[_Result(rows=[row]), _Result(rows=[row])])
        resp = _expiring_client(_EDITOR, fake).patch(
            "/v1/admin/cms/concept_content/items/C-1", json={"changes": {"explanation": "옛 설명"}}
        )
        assert resp.status_code == 200, resp.text
        assert fake.rollbacks == 1 and resp.json()["changed"] == []

    def test_changing_edit_responds_after_commit_without_touching_the_user(self) -> None:
        row = _concept_content_row()
        fake = FakeSession(results=[_Result(rows=[row]), _Result(rows=[row])])
        resp = _expiring_client(_EDITOR, fake).patch(
            "/v1/admin/cms/concept_content/items/C-1", json={"changes": {"explanation": "새 설명"}}
        )
        assert resp.status_code == 200, resp.text
        assert fake.commits == 1

    def test_transition_responds_after_commit_without_touching_the_user(self, spy: GateSpy) -> None:
        spy.apply_effect = lambda: _version(status_=VersionStatus.IN_REVIEW)
        fake = FakeSession()
        resp = _expiring_client(_EDITOR, fake).post(
            f"/v1/admin/cms/versions/{_VID}/transitions",
            json={"action": "submit", "expected_status": "DRAFT"},
        )
        assert resp.status_code == 200, resp.text
        assert fake.commits == 1

    def test_draft_creation_responds_after_commit_without_touching_the_user(
        self, spy: GateSpy
    ) -> None:
        fake = FakeSession(get_map={_CID: _live_concept()})
        resp = _expiring_client(_EDITOR, fake).post(
            f"/v1/admin/cms/concepts/{_CID}/drafts", json={"reason": "r"}
        )
        assert resp.status_code == 201, resp.text
        assert fake.commits == 1

    def test_rollback_responds_after_commit_without_touching_the_user(self, spy: GateSpy) -> None:
        spy.rollback_effect = lambda: gate.RollbackResult("CAL-X", uuid.uuid4(), uuid.uuid4())
        fake = FakeSession(results=[_Result(scalar="CAL-X")])
        resp = _expiring_client(_PUBLISHER, fake).post(
            f"/v1/admin/cms/concepts/{_CID}/rollback",
            json={"expected_published_version_id": str(_VID)},
        )
        assert resp.status_code == 200, resp.text
        assert fake.commits == 1

    def test_review_mark_responds_after_commit_without_touching_the_user(self) -> None:
        row = _concept_content_row(review_status="ai_estimated")
        fake = FakeSession(results=[_Result(rows=[row])])
        resp = _expiring_client(_REVIEWER, fake).post(
            "/v1/admin/cms/concept_content/items/C-1/review", json={"decision": "reviewed"}
        )
        assert resp.status_code == 200, resp.text
        assert fake.commits == 1

    def test_the_expiring_user_double_really_raises(self) -> None:
        """대조군 — 이 모사가 실제로 터진다는 것을 확인한다(터지지 않으면 위 테스트는 공허하다)."""
        fake = FakeSession()
        user = _ExpiringUser(_EDITOR, fake)
        assert user.role is Role.CONTENT_EDITOR  # 경계 전에는 읽힌다
        fake.commits = 1
        with pytest.raises(ExpiredUserError):
            _ = user.role
        with pytest.raises(ExpiredUserError):
            _ = user.user_id


# ═══════════════════════════════════════════════════════════════════════════════════════
# 선언(RESOURCES) ↔ 정적 핸들러 정합 — 라우트를 데코레이터로 직접 쓴 대가로 생기는 위험을 막는다
# ═══════════════════════════════════════════════════════════════════════════════════════


def _expected_resource_routes() -> set[tuple[str, str]]:
    """선언에서 **도출한** 리소스 라우트 집합 — 핸들러 목록을 손으로 따로 적지 않는다."""
    out: set[tuple[str, str]] = set()
    for spec in RESOURCES:
        out.add(("GET", f"/v1/admin/cms/{spec.key}"))
        out.add(("GET", f"/v1/admin/cms/{spec.key}/items/{{pk}}"))
        if spec.editable:
            out.add(("PATCH", f"/v1/admin/cms/{spec.key}/items/{{pk}}"))
        if spec.review_column is not None:
            out.add(("POST", f"/v1/admin/cms/{spec.key}/items/{{pk}}/review"))
    return out


_CONCEPT_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/v1/admin/cms/concepts"),
        ("GET", "/v1/admin/cms/concepts/{concept_id}"),
        ("POST", "/v1/admin/cms/concepts/{concept_id}/drafts"),
        ("GET", "/v1/admin/cms/concepts/{concept_id}/versions"),
        ("GET", "/v1/admin/cms/versions/{version_id}"),
        ("POST", "/v1/admin/cms/versions/{version_id}/transitions"),
        ("POST", "/v1/admin/cms/concepts/{concept_id}/rollback"),
        ("GET", "/v1/admin/cms/resources"),
        ("GET", "/v1/admin/cms/audit"),
    }
)


class TestRouteDeclarationParity:
    def test_served_routes_equal_declared_routes_exactly(self) -> None:
        """서빙되는 라우트 = 선언에서 도출한 리소스 라우트 ∪ 개념·메타·이력 라우트(정확히 일치).

        선언만 있고 라우트가 없으면(핸들러를 빠뜨림) 그 리소스는 화면에서 못 쓰이고, 선언에 없는 라우트가
        있으면(예: 읽기 전용 리소스에 PATCH) 허용 목록·검수 규칙이 우회된다. 둘 다 RED여야 한다.
        """
        served = set(_ROUTES)
        expected = _expected_resource_routes() | set(_CONCEPT_ROUTES)
        assert served == expected, (
            f"선언에 없는 라우트: {sorted(served - expected)} / 선언만 있고 없는 라우트: "
            f"{sorted(expected - served)}"
        )

    def test_every_resource_route_is_guarded_by_its_declared_module(self) -> None:
        """각 라우트의 레지스트리 파생 가드가 **선언된 모듈**이다 — 다른 모듈 가드를 단 핸들러는 RED."""
        from whymath_backend.ops.admin_guard_audit import _guarded_module_ids
        from whymath_backend.ops.declared_unwired_audit import walk_routes

        by_path: dict[tuple[str, str], set[str]] = {}
        for route in walk_routes(_APP.routes):
            path = getattr(route, "path", "")
            if not (isinstance(path, str) and path.startswith("/v1/admin/cms/")):
                continue  # 문서·정적 라우트에는 `dependant`가 없다 — CMS 라우트만 본다
            dependant = getattr(route, "dependant", None)
            assert (
                dependant is not None
            ), f"{path}: dependant 부재 — 가드 판정 불가(건너뛰지 않는다)"
            for method in getattr(route, "methods", None) or ():
                by_path[(method, path)] = _guarded_module_ids(dependant)
        checked = 0
        for spec in RESOURCES:
            for key in (
                ("GET", f"/v1/admin/cms/{spec.key}"),
                ("GET", f"/v1/admin/cms/{spec.key}/items/{{pk}}"),
                ("PATCH", f"/v1/admin/cms/{spec.key}/items/{{pk}}"),
                ("POST", f"/v1/admin/cms/{spec.key}/items/{{pk}}/review"),
            ):
                if key in by_path:
                    assert by_path[key] == {spec.module_id}, (key, by_path[key], spec.module_id)
                    checked += 1
        assert checked == len(
            _expected_resource_routes()
        ), "가드 모듈을 확인한 라우트 수가 모자란다"

    def test_read_only_resource_has_exactly_two_routes(self) -> None:
        paths = [(m, p) for m, p in _ROUTES if "/skill_node" in p]
        assert sorted(paths) == [
            ("GET", "/v1/admin/cms/skill_node"),
            ("GET", "/v1/admin/cms/skill_node/items/{pk}"),
        ]

    def test_write_routes_are_exactly_the_declared_writable_ones(self) -> None:
        writes = {(m, p) for m, p in _ROUTES if m != "GET"}
        derived = {r for r in _expected_resource_routes() if r[0] != "GET"}
        concept_writes = {r for r in _CONCEPT_ROUTES if r[0] != "GET"}
        assert writes == derived | concept_writes
        assert len(writes) == 12
