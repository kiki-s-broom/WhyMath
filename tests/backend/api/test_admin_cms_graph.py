"""Admin CMS 개념 그래프 쓰기 HTTP 계약 동결 — P3-26 (`api/admin_cms_graph.py`, hermetic).

PG 없이 모든 PR의 `backend` 잡에서 도는 **빠른 증거**다(실 PG 종단 간은 `backend-migrations` 잡이 돌리는
`test_admin_cms_graph_integration.py`가 본다). 동결 항목과 *그 항목이 없으면 통과해 버리는 오구현*:

① **권한 매트릭스 전수** — 라우트 × 역할. 거부되는 칸은 403이면서 **DB를 한 번도 건드리지 않는다**(403만
   보면 거부 *뒤에* 쓰기가 일어나는 오구현이 통과한다). 열리는 칸은 403이 아니고 DB까지 간다("전부 거부"
   오구현이 통과하지 못하게). 관계·삭제는 발행 권한, 제안은 편집 권한이다.
② **순환 거부** — 순환을 만드는 관계는 422이고 행·감사·commit이 0이다. 경로는 개념 *코드*로 돌려준다.
   대조군(순환 아닌 지름길)은 통과한다.
③ **소유(정본) 규칙** — graph.json 소유 관계·개념은 CMS가 지우지 못한다(409 `file_owned`). 발행본이 있으면
   개념 삭제도 거부(`has_published_version`).
④ **신규 개념은 게이트 경유** — 제안 API는 `publish_gate.create_proposal`만 부르고 개념 행을 만들지 않는다.
⑤ **오류 매핑** — 코드 선점은 409 `code_taken`, 거부 시 rollback·commit 0.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api import _concept_graph_rules as rules
from whymath_backend.api._auth import get_current_user
from whymath_backend.app import create_app
from whymath_backend.db.cms_edit_marker import mark_cms_edited
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.concept import Concept, ConceptEdge
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l3 import publish_gate as gate
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.concept_version import ConceptVersion as SchemaConceptVersion
from whymath_backend.schema.concept_version import ConceptVersionPayload
from whymath_backend.schema.enums import (
    AuditEventKind,
    ConceptLevel,
    EdgeType,
    PrivacyAuditAction,
    PrivacyAuditResourceType,
    Role,
)
from whymath_backend.schema.version_header import (
    VersionChange,
    VersionGovernance,
    VersionStatus,
)


def _user(role: Role) -> UserProfile:
    return UserProfile(user_id=uuid.uuid4(), role=role)


_STUDENT = _user(Role.STUDENT)
_EDITOR = _user(Role.CONTENT_EDITOR)
_REVIEWER = _user(Role.CONTENT_REVIEWER)
_PUBLISHER = _user(Role.CONTENT_PUBLISHER)
_ADMIN = _user(Role.CONTENT_ADMIN)
_ALL = {
    "student": _STUDENT,
    "editor": _EDITOR,
    "reviewer": _REVIEWER,
    "publisher": _PUBLISHER,
    "admin": _ADMIN,
}

# ── 가짜 세션 ──────────────────────────────────────────────────────────────────────────


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def __iter__(self) -> Any:
        return iter(self._rows)


class _Result:
    """`execute()` 결과 모사 — 라우터·규칙 모듈이 부르는 접근자만 구현한다."""

    def __init__(self, rows: list[Any] | None = None, scalar: Any = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else self._scalar

    def scalar_one(self) -> Any:
        return self._scalar

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """AsyncSession 모사 — **어떤 호출이 일어났는지**를 기록한다(거부 시 부작용 0 단언의 근거)."""

    def __init__(self, results: list[_Result] | None = None) -> None:
        self._results = list(results or [])
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.statements: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def get(self, model: Any, pk: Any) -> Any:
        self.statements.append(("get", model, pk))
        return None

    async def execute(self, stmt: Any, params: Any = None) -> _Result:
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
        return bool(self.statements or self.added or self.deleted or self.commits)

    @property
    def audit_rows(self) -> list[PrivacyAudit]:
        return [o for o in self.added if isinstance(o, PrivacyAudit)]

    @property
    def edges(self) -> list[ConceptEdge]:
        return [o for o in self.added if isinstance(o, ConceptEdge)]


_APP = create_app()


def _client(user: UserProfile | None, fake: FakeSession) -> TestClient:
    async def _override() -> AsyncIterator[FakeSession]:
        yield fake

    _APP.dependency_overrides.clear()
    _APP.dependency_overrides[get_session] = _override
    if user is not None:
        _APP.dependency_overrides[get_current_user] = lambda: user
    return TestClient(_APP)


# 결정적 UUID — xdist 워커마다 파라미터 id가 같아야 한다(무작위면 "수집된 테스트가 워커 간 다르다"로
# 실행이 무효가 된다).
_A, _B, _C = (uuid.UUID(int=0xA), uuid.UUID(int=0xB), uuid.UUID(int=0xC))
_EDGE_ID = uuid.UUID(int=0xED)
_CONCEPT_ID = uuid.UUID(int=0xC0)
_NAMES = {_A: "A", _B: "B", _C: "C"}


def _codes_result(*ids: uuid.UUID) -> _Result:
    return _Result(rows=[(i, _NAMES[i]) for i in ids])


def _edges_result(*pairs: tuple[uuid.UUID, uuid.UUID]) -> _Result:
    return _Result(rows=list(pairs))


def _version(
    *,
    code: str = "NEW-1",
    version_no: int = 1,
    status_: VersionStatus = VersionStatus.DRAFT,
    name_ko: str = "새 개념",
) -> SchemaConceptVersion:
    return SchemaConceptVersion(
        concept_id=code,
        version_no=version_no,
        schema_version="concept-payload@1",
        status=status_,
        payload=ConceptVersionPayload(name_ko=name_ko, level=ConceptLevel.단원),
        governance=VersionGovernance(created_by="tester"),
        change=VersionChange(change_type=gate.CMS_CREATE_CHANGE_TYPE),
    )


_PROPOSAL = {"code": "NEW-1", "payload": {"name_ko": "새 개념", "level": "단원"}}
_EDGE_BODY = {"from_concept_id": str(_A), "to_concept_id": str(_B)}


# ═══════════════════════════════════════════════════════════════════════════════════════
# ① 권한 매트릭스 — 라우트 × 역할
# ═══════════════════════════════════════════════════════════════════════════════════════

_VIEWERS = {"editor", "reviewer", "publisher", "admin"}
_EDITORS = {"editor", "admin"}
_PUBLISHERS = {"publisher", "admin"}

_ROUTES: list[tuple[str, str, str, dict[str, Any] | None, set[str]]] = [
    ("GET", "list_proposals", "/v1/admin/cms/concept-proposals", None, _VIEWERS),
    ("POST", "propose", "/v1/admin/cms/concept-proposals", _PROPOSAL, _EDITORS),
    (
        "POST",
        "revise",
        "/v1/admin/cms/concept-proposals/NEW-1/drafts",
        {"changes": {}},
        _EDITORS,
    ),
    ("POST", "edge_add", "/v1/admin/cms/edges", _EDGE_BODY, _PUBLISHERS),
    ("DELETE", "edge_del", f"/v1/admin/cms/edges/{_EDGE_ID}", None, _PUBLISHERS),
    ("DELETE", "concept_del", f"/v1/admin/cms/concepts/{_CONCEPT_ID}", None, _PUBLISHERS),
]


@pytest.mark.parametrize(
    ("method", "name", "path", "body", "allowed"), _ROUTES, ids=[r[1] for r in _ROUTES]
)
@pytest.mark.parametrize("who", list(_ALL))
def test_permission_matrix(
    who: str,
    method: str,
    name: str,
    path: str,
    body: dict[str, Any] | None,
    allowed: set[str],
) -> None:
    fake = FakeSession()
    resp = _client(_ALL[who], fake).request(method, path, json=body)
    if who in allowed:
        # 열리는 칸: 권한 때문에 막히지 않고, 요청이 DB(또는 게이트)까지 간다.
        assert resp.status_code != 403, (name, who, resp.text)
    else:
        assert resp.status_code == 403, (name, who, resp.status_code, resp.text)
        assert not fake.touched_db, f"{name}/{who}: 거부된 요청이 DB를 건드렸다"
        assert fake.audit_rows == [] and fake.commits == 0


def test_matrix_is_not_vacuous() -> None:
    """분모 — 열리는 칸과 닫히는 칸이 모두 있어야 위 전수 검사가 의미를 갖는다."""
    cells = [(n, w) for (_m, n, _p, _b, ok) in _ROUTES for w in _ALL if w in ok]
    assert len(cells) == 4 + 2 + 2 + 2 + 2 + 2
    denied = [(n, w) for (_m, n, _p, _b, ok) in _ROUTES for w in _ALL if w not in ok]
    assert len(denied) == 5 * 6 - len(cells)


# ═══════════════════════════════════════════════════════════════════════════════════════
# ② 관계 추가 — 순환 거부
# ═══════════════════════════════════════════════════════════════════════════════════════


class TestEdgeCreate:
    def test_success_marks_ownership_audits_once_and_commits_once(self) -> None:
        fake = FakeSession(
            [
                _Result(),  # 잠금
                _codes_result(_A, _B),  # 양 끝 실재
                _Result(),  # 중복 없음
                _edges_result(),  # 기존 선수 엣지 없음 → 순환 없음
            ]
        )
        r = _client(_PUBLISHER, fake).post(
            "/v1/admin/cms/edges", json={**_EDGE_BODY, "edge_strength": 0.456}
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert (body["from_code"], body["to_code"], body["cms_owned"]) == ("A", "B", True)
        assert body["edge_type"] == "PREREQUISITE"
        assert body["edge_strength"] == pytest.approx(0.46)  # Numeric(3,2)로 반올림
        (edge,) = fake.edges
        assert edge.cms_edited_at is not None, "CMS가 만든 관계에 소유 표지가 없다"
        assert edge.edge_type == EdgeType.PREREQUISITE and edge.edge_strength == Decimal("0.46")
        (audit,) = fake.audit_rows
        assert audit.event_kind == AuditEventKind.content_mutation.value
        assert audit.resource_type == PrivacyAuditResourceType.concept_edge.value
        assert audit.action == PrivacyAuditAction.create.value
        assert audit.resource_id == edge.edge_id and audit.user_id == _PUBLISHER.user_id
        assert fake.commits == 1 and fake.rollbacks == 0

    def test_a_cycle_is_422_with_a_readable_path_and_writes_nothing(self) -> None:
        # 기존: A→B, B→C. 새로 C→A 를 더하면 A→B→C→A 순환.
        fake = FakeSession(
            [
                _Result(),
                _codes_result(_C, _A),
                _Result(),
                _edges_result((_A, _B), (_B, _C)),
                _codes_result(_A, _B, _C),  # 경로를 코드로 바꾸는 조회
            ]
        )
        r = _client(_PUBLISHER, fake).post(
            "/v1/admin/cms/edges",
            json={"from_concept_id": str(_C), "to_concept_id": str(_A)},
        )
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "prerequisite_cycle"
        assert detail["path"] == ["C", "A", "B", "C"]  # 닫힘 노드 반복: 어디를 끊을지 보인다
        assert fake.edges == [] and fake.audit_rows == []
        assert fake.commits == 0 and fake.rollbacks >= 1

    def test_a_shortcut_that_is_not_a_cycle_passes(self) -> None:
        """대조군 — 같은 그래프에서 A→C 는 순환이 아니다. 위 거부가 "항상 거부"의 부산물이 아님을 보인다."""
        fake = FakeSession(
            [
                _Result(),
                _codes_result(_A, _C),
                _Result(),
                _edges_result((_A, _B), (_B, _C)),
            ]
        )
        r = _client(_PUBLISHER, fake).post(
            "/v1/admin/cms/edges",
            json={"from_concept_id": str(_A), "to_concept_id": str(_C)},
        )
        assert r.status_code == 201, r.text
        assert len(fake.edges) == 1 and fake.commits == 1

    def test_the_cycle_check_runs_after_the_graph_lock(self) -> None:
        """검사와 쓰기 사이 틈을 막는 잠금이 순환 검사 **앞**에 있어야 한다(첫 SQL이 잠금)."""
        fake = FakeSession([_Result(), _codes_result(_A, _B), _Result(), _edges_result()])
        _client(_PUBLISHER, fake).post("/v1/admin/cms/edges", json=_EDGE_BODY)
        first = str(fake.statements[0])
        assert "pg_advisory_xact_lock" in first

    @pytest.mark.parametrize(
        ("body", "code"),
        [
            ({"from_concept_id": str(_A), "to_concept_id": str(_A)}, "self_edge"),
            ({**_EDGE_BODY, "edge_type": "ANALOGOUS_TO"}, "edge_type_not_writable"),
            ({**_EDGE_BODY, "edge_type": "TRIGGERS_DISTRACTOR"}, "edge_type_not_writable"),
        ],
    )
    def test_malformed_requests_are_refused_before_touching_the_db(
        self, body: dict[str, Any], code: str
    ) -> None:
        fake = FakeSession()
        r = _client(_PUBLISHER, fake).post("/v1/admin/cms/edges", json=body)
        assert r.status_code == 422 and r.json()["detail"]["code"] == code
        assert not fake.touched_db

    def test_unknown_concept_and_duplicate_are_refused(self) -> None:
        unknown = FakeSession([_Result(), _codes_result(_A)])  # B가 없다
        r = _client(_PUBLISHER, unknown).post("/v1/admin/cms/edges", json=_EDGE_BODY)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_concept"
        assert unknown.edges == [] and unknown.commits == 0

        dup = FakeSession([_Result(), _codes_result(_A, _B), _Result(rows=[(uuid.uuid4(),)])])
        r2 = _client(_PUBLISHER, dup).post("/v1/admin/cms/edges", json=_EDGE_BODY)
        assert r2.status_code == 409 and r2.json()["detail"]["code"] == "edge_exists"
        assert dup.edges == [] and dup.commits == 0

    @pytest.mark.parametrize("strength", [-0.1, 1.5])
    def test_strength_out_of_range_is_422_before_the_db(self, strength: float) -> None:
        fake = FakeSession()
        r = _client(_PUBLISHER, fake).post(
            "/v1/admin/cms/edges", json={**_EDGE_BODY, "edge_strength": strength}
        )
        assert r.status_code == 422 and not fake.touched_db


# ═══════════════════════════════════════════════════════════════════════════════════════
# ② 순환 경로 복원 — 규칙 모듈 직접
# ═══════════════════════════════════════════════════════════════════════════════════════


class TestFindCycle:
    @staticmethod
    async def _find(
        existing: list[tuple[uuid.UUID, uuid.UUID]], src: uuid.UUID, dst: uuid.UUID
    ) -> list[uuid.UUID] | None:
        return await rules.find_cycle_if_added(FakeSession([_edges_result(*existing)]), src, dst)  # type: ignore[arg-type]

    @pytest.mark.anyio
    async def test_direct_reverse_edge(self) -> None:
        assert await self._find([(_A, _B)], _B, _A) == [_B, _A, _B]

    @pytest.mark.anyio
    async def test_long_chain_returns_the_whole_loop(self) -> None:
        d = uuid.uuid4()
        got = await self._find([(_A, _B), (_B, _C), (_C, d)], d, _A)
        assert got == [d, _A, _B, _C, d]

    @pytest.mark.anyio
    async def test_no_cycle_returns_none(self) -> None:
        assert await self._find([(_A, _B), (_B, _C)], _A, _C) is None
        assert await self._find([], _A, _B) is None

    @pytest.mark.anyio
    async def test_a_preexisting_cycle_elsewhere_does_not_hang(self) -> None:
        """DB에 이미 (다른 곳의) 순환이 있어도 visited로 멈춘다 — 무한 루프 금지."""
        x, y = uuid.uuid4(), uuid.uuid4()
        assert await self._find([(x, y), (y, x), (_A, _B)], _B, _C) is None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ═══════════════════════════════════════════════════════════════════════════════════════
# ③ 관계·개념 삭제 — 소유 규칙
# ═══════════════════════════════════════════════════════════════════════════════════════


def _edge(*, cms_owned: bool) -> ConceptEdge:
    edge = ConceptEdge(
        edge_id=uuid.uuid4(),
        from_concept_id=_A,
        to_concept_id=_B,
        edge_type=EdgeType.PREREQUISITE,
    )
    if cms_owned:
        mark_cms_edited(edge)
    return edge


class TestEdgeDelete:
    def test_cms_owned_edge_is_deleted_with_one_audit_row(self) -> None:
        edge = _edge(cms_owned=True)
        fake = FakeSession([_Result(), _Result(rows=[edge])])
        r = _client(_PUBLISHER, fake).delete(f"/v1/admin/cms/edges/{edge.edge_id}")
        assert r.status_code == 200 and r.json() == {"edge_id": str(edge.edge_id), "deleted": True}
        assert fake.deleted == [edge] and fake.commits == 1
        (audit,) = fake.audit_rows
        assert audit.action == PrivacyAuditAction.delete.value
        assert audit.resource_type == PrivacyAuditResourceType.concept_edge.value

    def test_file_owned_edge_is_refused_because_the_loader_would_resurrect_it(self) -> None:
        edge = _edge(cms_owned=False)
        fake = FakeSession([_Result(), _Result(rows=[edge])])
        r = _client(_PUBLISHER, fake).delete(f"/v1/admin/cms/edges/{edge.edge_id}")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "file_owned"
        assert "graph.json" in r.json()["detail"]["message"]
        assert fake.deleted == [] and fake.audit_rows == [] and fake.commits == 0
        assert fake.rollbacks >= 1

    def test_missing_edge_is_404(self) -> None:
        fake = FakeSession([_Result(), _Result()])
        r = _client(_PUBLISHER, fake).delete(f"/v1/admin/cms/edges/{uuid.uuid4()}")
        assert r.status_code == 404 and fake.commits == 0


def _concept(*, cms_owned: bool, pointer: bool = False) -> Concept:
    row = Concept.from_schema(ConceptSchema(code="DEL-1", name_ko="지울 개념", level="단원"))
    if cms_owned:
        mark_cms_edited(row)
    if pointer:
        row.current_published_version_id = uuid.uuid4()
    return row


class TestConceptDelete:
    def _delete(self, concept: Concept, *results: _Result) -> tuple[Any, FakeSession]:
        fake = FakeSession([_Result(rows=[concept]), *results])
        resp = _client(_PUBLISHER, fake).delete(f"/v1/admin/cms/concepts/{concept.concept_id}")
        return resp, fake

    def test_a_cms_owned_unpublished_unreferenced_concept_is_deleted(self) -> None:
        concept = _concept(cms_owned=True)
        # 발행본 조회(없음) → 관계 수 0 → 자식 수 0
        resp, fake = self._delete(concept, _Result(), _Result(scalar=0), _Result(scalar=0))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"concept_code": "DEL-1", "deleted": True}
        assert fake.deleted == [concept] and fake.commits == 1
        (audit,) = fake.audit_rows
        assert audit.resource_type == PrivacyAuditResourceType.concept.value
        assert audit.action == PrivacyAuditAction.delete.value

    def test_file_owned_concept_is_refused(self) -> None:
        resp, fake = self._delete(_concept(cms_owned=False))
        assert resp.status_code == 409 and resp.json()["detail"]["code"] == "file_owned"
        assert fake.deleted == [] and fake.commits == 0

    def test_a_published_pointer_is_refused(self) -> None:
        resp, fake = self._delete(_concept(cms_owned=True, pointer=True))
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "has_published_version"
        assert fake.deleted == [] and fake.commits == 0

    def test_a_published_version_row_is_refused_even_if_the_pointer_is_empty(self) -> None:
        """포인터가 비어도 PUBLISHED 판이 남은 불일치를 막는다 — 포인터만 보는 오구현이 통과하지 못하게."""
        resp, fake = self._delete(_concept(cms_owned=True), _Result(rows=[(uuid.uuid4(),)]))
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "has_published_version"
        assert fake.deleted == []

    def test_edges_and_children_block_deletion_with_counts(self) -> None:
        resp, fake = self._delete(_concept(cms_owned=True), _Result(), _Result(scalar=2))
        assert resp.status_code == 409 and resp.json()["detail"]["code"] == "has_edges"
        assert resp.json()["detail"]["edge_count"] == 2
        resp2, fake2 = self._delete(
            _concept(cms_owned=True), _Result(), _Result(scalar=0), _Result(scalar=3)
        )
        assert resp2.status_code == 409 and resp2.json()["detail"]["code"] == "has_children"
        assert resp2.json()["detail"]["child_count"] == 3
        assert fake.deleted == [] and fake2.deleted == []

    def test_missing_concept_is_404(self) -> None:
        fake = FakeSession([_Result()])
        r = _client(_PUBLISHER, fake).delete(f"/v1/admin/cms/concepts/{uuid.uuid4()}")
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════════════
# ④ 신규 개념 제안 — 게이트만 경유
# ═══════════════════════════════════════════════════════════════════════════════════════


class _GateStub:
    def __init__(self) -> None:
        self.proposals: list[dict[str, Any]] = []
        self.revisions: list[dict[str, Any]] = []
        self.versions: list[SchemaConceptVersion] = []
        self.open: list[SchemaConceptVersion] = []
        self.propose_error: Exception | None = None
        self.revise_error: Exception | None = None

    async def create_proposal(self, session: Any, **kw: Any) -> SchemaConceptVersion:
        self.proposals.append(kw)
        if self.propose_error is not None:
            raise self.propose_error
        return _version(code=kw["concept_code"], name_ko=kw["payload"].name_ko)

    async def revise_proposal(self, session: Any, **kw: Any) -> SchemaConceptVersion:
        self.revisions.append(kw)
        if self.revise_error is not None:
            raise self.revise_error
        return _version(code=kw["concept_code"], version_no=2, name_ko=kw["payload"].name_ko)

    async def list_versions(self, session: Any, code: str) -> list[SchemaConceptVersion]:
        return list(self.versions)

    async def list_open_proposals(self, session: Any, **kw: Any) -> list[SchemaConceptVersion]:
        return list(self.open)


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> _GateStub:
    s = _GateStub()
    for name in ("create_proposal", "revise_proposal", "list_versions", "list_open_proposals"):
        monkeypatch.setattr(gate, name, getattr(s, name))
    return s


class TestProposals:
    def test_a_proposal_goes_through_the_gate_and_creates_no_concept_row(
        self, stub: _GateStub
    ) -> None:
        fake = FakeSession()
        r = _client(_EDITOR, fake).post(
            "/v1/admin/cms/concept-proposals",
            json={**_PROPOSAL, "code": "  NEW-1  ", "reason": "신규"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["concept_code"] == "NEW-1" and r.json()["status"] == "DRAFT"
        (call,) = stub.proposals
        assert call["concept_code"] == "NEW-1"  # 앞뒤 공백 제거
        assert call["created_by"] == str(_EDITOR.user_id) and call["reason"] == "신규"
        assert not [o for o in fake.added if isinstance(o, Concept)], "제안이 개념 행을 만들었다"
        (audit,) = fake.audit_rows
        assert audit.resource_type == PrivacyAuditResourceType.concept_version.value
        assert audit.action == PrivacyAuditAction.create.value
        assert fake.commits == 1

    @pytest.mark.parametrize("code", ["a b", "x/y", "x\ny", "", "a", "x" * 65, "-lead", '"q"'])
    def test_invalid_codes_are_422_before_the_gate(self, stub: _GateStub, code: str) -> None:
        fake = FakeSession()
        r = _client(_EDITOR, fake).post(
            "/v1/admin/cms/concept-proposals", json={**_PROPOSAL, "code": code}
        )
        assert r.status_code == 422, (code, r.text)
        assert stub.proposals == [] and fake.commits == 0

    @pytest.mark.parametrize("code", ["2수01-01-2", "math.calc.limit", "CMS_NEW-1", "가나"])
    def test_real_world_code_shapes_are_accepted(self, stub: _GateStub, code: str) -> None:
        """대조군 — 기존 코드(한글 포함 `2수01-01-2` 등)와 같은 문자 집합은 통과한다."""
        r = _client(_EDITOR, FakeSession()).post(
            "/v1/admin/cms/concept-proposals", json={**_PROPOSAL, "code": code}
        )
        assert r.status_code == 201, (code, r.text)

    def test_invalid_payload_never_reaches_the_gate(self, stub: _GateStub) -> None:
        for payload in (
            {"name_ko": "이름만"},  # level 누락
            {"name_ko": "x", "level": "없는계층"},
            {"name_ko": "x", "level": "단원", "current_published_version_id": str(uuid.uuid4())},
            {"name_ko": "x", "level": "단원", "status": "PUBLISHED"},  # 상태 키 밀수
        ):
            fake = FakeSession()
            r = _client(_EDITOR, fake).post(
                "/v1/admin/cms/concept-proposals", json={"code": "NEW-1", "payload": payload}
            )
            assert r.status_code == 422, (payload, r.text)
            assert r.json()["detail"]["code"] == "payload_invalid"
            assert fake.commits == 0
        assert stub.proposals == []

    def test_unknown_skill_is_refused(self, stub: _GateStub) -> None:
        fake = FakeSession([_Result(rows=[])])  # skill_node에 없다
        r = _client(_EDITOR, fake).post(
            "/v1/admin/cms/concept-proposals",
            json={
                "code": "NEW-1",
                "payload": {"name_ko": "x", "level": "단원", "behavior_skills": ["ghost.skill"]},
            },
        )
        assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_skill"
        assert stub.proposals == []

    def test_unknown_parent_is_refused(self, stub: _GateStub) -> None:
        fake = FakeSession([_Result(rows=[])])  # 부모 개념 없음
        r = _client(_EDITOR, fake).post(
            "/v1/admin/cms/concept-proposals",
            json={
                "code": "NEW-1",
                "payload": {
                    "name_ko": "x",
                    "level": "소단원",
                    "parent_concept_id": str(uuid.uuid4()),
                },
            },
        )
        assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_parent"
        assert stub.proposals == []

    def test_a_taken_code_is_409_and_rolls_back(self, stub: _GateStub) -> None:
        stub.propose_error = gate.CodeTakenError("NEW-1", "이미 살아있는 개념의 코드입니다")
        fake = FakeSession()
        r = _client(_EDITOR, fake).post("/v1/admin/cms/concept-proposals", json=_PROPOSAL)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "code_taken"
        assert fake.commits == 0 and fake.rollbacks >= 1

    def test_listing_shows_open_proposals_for_every_cms_viewer(self, stub: _GateStub) -> None:
        stub.open = [_version(code="NEW-9", name_ko="열린 제안")]
        r = _client(_REVIEWER, FakeSession()).get("/v1/admin/cms/concept-proposals")
        assert r.status_code == 200
        (row,) = r.json()
        assert row["name_ko"] == "열린 제안" and row["summary"]["concept_code"] == "NEW-9"
        # 검수자 화면의 버튼은 검수 권한으로 가능한 전이만 — 제출(편집 권한)은 없다.
        assert "submit" not in row["summary"]["allowed_actions"]

    def test_revise_merges_changes_onto_the_latest_version(self, stub: _GateStub) -> None:
        stub.versions = [_version(code="NEW-1", name_ko="처음")]
        fake = FakeSession()
        r = _client(_EDITOR, fake).post(
            "/v1/admin/cms/concept-proposals/NEW-1/drafts", json={"changes": {"name_ko": "고침"}}
        )
        assert r.status_code == 201, r.text
        (call,) = stub.revisions
        assert call["payload"].name_ko == "고침" and r.json()["version_no"] == 2
        assert fake.commits == 1

    def test_revise_of_an_unknown_proposal_is_404(self, stub: _GateStub) -> None:
        r = _client(_EDITOR, FakeSession()).post(
            "/v1/admin/cms/concept-proposals/NOPE/drafts", json={"changes": {}}
        )
        assert r.status_code == 404 and stub.revisions == []

    def test_revise_of_an_already_realized_concept_is_409(self, stub: _GateStub) -> None:
        stub.versions = [_version()]
        stub.revise_error = gate.CodeTakenError("NEW-1", "이미 살아있는 개념입니다")
        fake = FakeSession()
        r = _client(_EDITOR, fake).post(
            "/v1/admin/cms/concept-proposals/NEW-1/drafts", json={"changes": {}}
        )
        assert r.status_code == 409 and r.json()["detail"]["code"] == "concept_exists"
        assert fake.commits == 0


# ═══════════════════════════════════════════════════════════════════════════════════════
# 게이트 순수 함수 — 발행이 만드는 개념 행
# ═══════════════════════════════════════════════════════════════════════════════════════


class TestMaterialize:
    def test_the_realized_concept_carries_the_payload_and_the_cms_marker(self) -> None:
        payload = ConceptVersionPayload(
            name_ko="발행으로 생긴 개념",
            name_en="Born",
            level=ConceptLevel.세부개념,
            aliases=["old-1"],
            is_signature_korean=True,
            behavior_skills=["skill.a"],
            intrinsic_difficulty=3.5,
        )
        version = SchemaConceptVersion(
            concept_id="NEW-7",
            version_no=1,
            schema_version="concept-payload@1",
            status=VersionStatus.APPROVED,
            payload=payload,
            governance=VersionGovernance(created_by="t"),
            change=VersionChange(change_type=gate.CMS_CREATE_CHANGE_TYPE),
        )
        concept = gate._materialize_concept(version)
        assert concept.code == "NEW-7" and concept.name_ko == "발행으로 생긴 개념"
        assert concept.name_en == "Born" and concept.aliases == ["old-1"]
        assert concept.behavior_skills == ["skill.a"] and concept.is_signature_korean is True
        assert concept.cms_edited_at is not None, "CMS가 만든 행에 소유 표지가 없다"
        # 발행 포인터는 이 함수가 아니라 `apply_transition`이 판 행을 쓴 뒤에 세운다.
        assert concept.current_published_version_id is None
