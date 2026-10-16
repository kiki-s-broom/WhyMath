"""개념 그래프 쓰기 실 PostgreSQL 종단 간 — P3-26 (기본 SKIP, `WHYMATH_RUN_INTEGRATION=1` + head 적용 PG).

hermetic 테스트(`test_admin_cms_graph.py`)는 가짜 세션을 쓴다. 이 파일은 **대체하지 않는다**: 역할별 실제 JWT
→ 실제 모듈 가드·권한 검사 → 실제 `publish_gate`(행 잠금·어드바이저리 잠금·DB 트리거) → 실제 감사 행까지
왕복하고, 거부된 요청 뒤 **DB 상태가 그대로인지** SQL로 직접 읽어 단언한다(응답 코드만 보지 않는다).

검증하는 것(요구사항 ①~④와 1:1):
  ① 원천 정본 — CMS가 만든 관계는 적재(`populate_*_edges`)가 건드리지 않고 충돌로 보고하며,
     graph.json 소유 관계는 CMS가 지울 수 없다.
  ② 비순환 — 순환을 만드는 요청은 서버가 422로 거부하고 **DB에 한 줄도 남기지 않는다**. 동시에 들어온
     두 요청이 합쳐 순환을 만드는 경우도 한쪽만 성공한다. 적재 CLI 쪽도 DB의 CMS 관계와 합쳐 본다.
  ③ 신규 개념 — 제안은 `concept` 행을 만들지 않고, 발행하는 순간에만 만들어진다. 발행본이 있는 개념의
     삭제는 서버·DB 트리거 양쪽에서 거부된다.
  ④ 권한 — 편집자·검수자·학생의 쓰기 시도는 서버가 403으로 막고 DB가 그대로다.

이 파일은 CI의 `backend-migrations` 잡이 `WHYMATH_RUN_INTEGRATION=1`로 실 PG(pgvector 이미지)에서
`pytest -m integration`으로 실행한다(공유 DB·`WHYMATH_DB_DISABLE_POOL=1`·마이그레이션 왕복 직후). 그래서
행은 테스트마다 고유 코드로 만들고 끝에 지운다. 로컬은 `WHYMATH_RUN_INTEGRATION=1` + head 적용 PG가 필요하다.
hermetic 쪽 증거는 `test_admin_cms_graph.py`·`test_cms_graph_write_enforcement.py`다.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.concept import Concept
from whymath_backend.db.models.user import UserProfile
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.enums import Persona, Role
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

pytestmark = pytest.mark.integration

_JWT_SECRET = "cms-graph-integration-jwt-secret-0123456789abcdef"


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_JWT_SECRET))


def _engine() -> Any:
    return create_async_engine(Settings().database_url)


async def _ready() -> bool:
    """PG 도달 + 이 태스크의 리비전 적용(`concept.cms_edited_at` 컬럼 존재)."""
    engine = _engine()
    try:
        async with engine.connect() as conn:
            found = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'concept' AND column_name = 'cms_edited_at'"
                    )
                )
            ).first()
        return found is not None
    except Exception:
        return False
    finally:
        await engine.dispose()


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _sql(stmt: str, **params: Any) -> list[Any]:
    engine = _engine()
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(stmt), params)
            return list(result.fetchall()) if result.returns_rows else []
    finally:
        await engine.dispose()


def q(stmt: str, **params: Any) -> list[Any]:
    return _run(_sql(stmt, **params))


async def _add(*objs: Any) -> None:
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(objs)
            await session.commit()
    finally:
        await engine.dispose()


def _make_user(role: Role) -> uuid.UUID:
    uid = uuid.uuid4()
    _run(
        _add(
            UserProfile.from_schema(
                UserProfileSchema(user_id=uid, persona_primary=Persona.A_일반고고3, role=role)
            )
        )
    )
    return uid


def _headers(uid: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(uid, settings=_settings())}"}


class _World:
    """한 테스트가 만든 행을 기억했다가 FK 순서대로 지운다(공유 DB를 더럽히지 않는다)."""

    def __init__(self) -> None:
        self.users: dict[str, uuid.UUID] = {}
        self.codes: list[str] = []

    def user(self, name: str, role: Role) -> dict[str, str]:
        uid = _make_user(role)
        self.users[name] = uid
        return _headers(uid)

    def code(self) -> str:
        code = f"CMSG-{uuid.uuid4().hex[:10]}"
        self.codes.append(code)
        return code

    def live_concept(self, *, cms_owned: bool = False) -> Concept:
        """살아있는 개념 1건 — 기본은 *적재가 소유한* 행(표지 없음)."""
        code = self.code()
        row = Concept.from_schema(ConceptSchema(code=code, name_ko="그래프 개념", level="단원"))
        if cms_owned:
            from whymath_backend.db.cms_edit_marker import mark_cms_edited

            mark_cms_edited(row)
        _run(_add(row))
        return row

    async def _cleanup(self) -> None:
        engine = _engine()
        try:
            async with engine.begin() as conn:
                for code in self.codes:
                    await conn.execute(
                        text(
                            "DELETE FROM concept_edge WHERE from_concept_id IN "
                            "(SELECT concept_id FROM concept WHERE code = :c) "
                            "OR to_concept_id IN (SELECT concept_id FROM concept WHERE code = :c)"
                        ),
                        {"c": code},
                    )
                    await conn.execute(
                        text(
                            "UPDATE concept SET current_published_version_id = NULL WHERE code = :c"
                        ),
                        {"c": code},
                    )
                    await conn.execute(
                        text("DELETE FROM concept_version WHERE concept_id = :c"), {"c": code}
                    )
                    await conn.execute(text("DELETE FROM concept WHERE code = :c"), {"c": code})
                for uid in self.users.values():
                    await conn.execute(
                        text("DELETE FROM privacy_audit WHERE user_id = CAST(:u AS uuid)"),
                        {"u": str(uid)},
                    )
                    await conn.execute(
                        text("DELETE FROM user_profile WHERE user_id = CAST(:u AS uuid)"),
                        {"u": str(uid)},
                    )
        finally:
            await engine.dispose()


@pytest.fixture
def world() -> Iterator[_World]:
    if not _run(_ready()):
        pytest.skip("PostgreSQL 미도달 또는 리비전 a8c4e1f7b3d9 미적용 — 통합 테스트 건너뜀")
    w = _World()
    try:
        yield w
    finally:
        _run(w._cleanup())


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = _settings
    with TestClient(app) as c:
        yield c


def _count(sql: str, **params: Any) -> int:
    return int(q(sql, **params)[0][0])


def _live(code: str) -> int:
    return _count("SELECT count(*) FROM concept WHERE code = :c", c=code)


def _edges_among(*ids: uuid.UUID) -> int:
    return _count(
        "SELECT count(*) FROM concept_edge WHERE from_concept_id = ANY(CAST(:ids AS uuid[])) "
        "AND to_concept_id = ANY(CAST(:ids AS uuid[]))",
        ids=[str(i) for i in ids],
    )


def _audits(uid: uuid.UUID, resource_type: str) -> int:
    return _count(
        "SELECT count(*) FROM privacy_audit WHERE user_id = CAST(:u AS uuid) "
        "AND resource_type = :t",
        u=str(uid),
        t=resource_type,
    )


def _transition(
    client: TestClient, headers: dict[str, str], version_id: str, action: str, expected: str
) -> Any:
    return client.post(
        f"/v1/admin/cms/versions/{version_id}/transitions",
        headers=headers,
        json={"action": action, "expected_status": expected},
    )


_PROPOSAL = {"name_ko": "제안 개념", "level": "단원"}


# ══════════════════════════════════════════════════════════════════════════════════════
# ③ 신규 개념 — 제안은 행을 만들지 않고, 발행이 만든다
# ══════════════════════════════════════════════════════════════════════════════════════


class TestNewConceptThroughTheWorkflow:
    def test_a_proposal_creates_no_live_row_and_publishing_creates_it(
        self, world: _World, client: TestClient
    ) -> None:
        editor = world.user("editor", Role.CONTENT_EDITOR)
        reviewer = world.user("reviewer", Role.CONTENT_REVIEWER)
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        code = world.code()

        # ── 편집자가 제안한다. 살아있는 개념 행은 생기지 않는다(핵심).
        r = client.post(
            "/v1/admin/cms/concept-proposals",
            headers=editor,
            json={"code": code, "payload": _PROPOSAL, "reason": "신규 단원"},
        )
        assert r.status_code == 201, r.text
        v = r.json()
        assert (v["concept_code"], v["version_no"], v["status"]) == (code, 1, "DRAFT")
        vid = v["version_id"]
        assert _live(code) == 0, "제안이 검수 없이 살아있는 개념 행을 만들었다"
        assert _audits(world.users["editor"], "concept_version") == 1

        # ── 제안 목록에는 보이고, 라이브 개념 목록(학생 경로가 읽는 표면)에는 없다.
        listed = client.get("/v1/admin/cms/concept-proposals", headers=editor).json()
        assert [
            p["summary"]["concept_code"] for p in listed if p["summary"]["concept_code"] == code
        ]
        live_search = client.get(f"/v1/admin/cms/concepts?q={code}", headers=editor).json()
        assert live_search["total"] == 0

        # ── 검토·QA·승인까지 가도 개념 행은 여전히 없다.
        assert _transition(client, editor, vid, "submit", "DRAFT").status_code == 200
        assert _transition(client, reviewer, vid, "pass_review", "IN_REVIEW").status_code == 200
        assert _transition(client, reviewer, vid, "approve", "IN_QA").status_code == 200
        assert _live(code) == 0

        # ── 편집자는 발행 못 한다(403, 개념 행 그대로 없음).
        assert _transition(client, editor, vid, "publish", "APPROVED").status_code == 403
        assert _live(code) == 0

        # ── 배포자가 발행하는 순간 개념 행이 만들어지고, CMS 소유 표지가 채워지며, 포인터가 선다.
        published = _transition(client, publisher, vid, "publish", "APPROVED")
        assert published.status_code == 200, published.text
        row = q(
            "SELECT name_ko, cms_edited_at IS NOT NULL, current_published_version_id::text "
            "FROM concept WHERE code = :c",
            c=code,
        )
        assert row == [("제안 개념", True, vid)], row

    def test_a_taken_code_is_refused_and_leaves_nothing(
        self, world: _World, client: TestClient
    ) -> None:
        editor = world.user("editor", Role.CONTENT_EDITOR)
        live = world.live_concept()  # 이미 살아있는 개념의 코드
        r = client.post(
            "/v1/admin/cms/concept-proposals",
            headers=editor,
            json={"code": live.code, "payload": _PROPOSAL},
        )
        assert r.status_code == 409 and r.json()["detail"]["code"] == "code_taken"
        assert (
            _count("SELECT count(*) FROM concept_version WHERE concept_id = :c", c=live.code) == 0
        )

        # 같은 코드로 두 번째 제안도 거부(판 이력이 남은 코드는 예약).
        code = world.code()
        ok = client.post(
            "/v1/admin/cms/concept-proposals",
            headers=editor,
            json={"code": code, "payload": _PROPOSAL},
        )
        assert ok.status_code == 201
        again = client.post(
            "/v1/admin/cms/concept-proposals",
            headers=editor,
            json={"code": code, "payload": _PROPOSAL},
        )
        assert again.status_code == 409
        assert _count("SELECT count(*) FROM concept_version WHERE concept_id = :c", c=code) == 1

    def test_a_code_taken_by_a_load_while_the_proposal_was_in_review_cannot_be_published(
        self, world: _World, client: TestClient
    ) -> None:
        """심사가 길어지는 사이 graph.json 적재가 같은 코드의 개념을 만들었다 — 발행이 그것을 덮지 않는다."""
        editor = world.user("editor", Role.CONTENT_EDITOR)
        reviewer = world.user("reviewer", Role.CONTENT_REVIEWER)
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        code = world.code()
        vid = client.post(
            "/v1/admin/cms/concept-proposals",
            headers=editor,
            json={"code": code, "payload": _PROPOSAL},
        ).json()["version_id"]
        for who, act, exp in (
            (editor, "submit", "DRAFT"),
            (reviewer, "pass_review", "IN_REVIEW"),
            (reviewer, "approve", "IN_QA"),
        ):
            assert _transition(client, who, vid, act, exp).status_code == 200
        # 적재가 같은 코드를 만든다(표지 없음 = 파일 소유).
        _run(
            _add(Concept.from_schema(ConceptSchema(code=code, name_ko="적재가 만든", level="단원")))
        )

        r = _transition(client, publisher, vid, "publish", "APPROVED")
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "gate_failed"
        assert any("concept_code_free" in f for f in r.json()["detail"]["failures"])
        # 적재가 만든 개념은 그대로이고, 제안 판은 APPROVED에 머문다.
        assert q(
            "SELECT name_ko, cms_edited_at IS NOT NULL FROM concept WHERE code = :c", c=code
        ) == [("적재가 만든", False)]
        assert (
            str(
                q("SELECT status FROM concept_version WHERE version_id = CAST(:v AS uuid)", v=vid)[
                    0
                ][0]
            )
            == "APPROVED"
        )

    def test_a_proposal_can_be_revised_before_it_is_published(
        self, world: _World, client: TestClient
    ) -> None:
        editor = world.user("editor", Role.CONTENT_EDITOR)
        code = world.code()
        client.post(
            "/v1/admin/cms/concept-proposals",
            headers=editor,
            json={"code": code, "payload": _PROPOSAL},
        )
        r = client.post(
            f"/v1/admin/cms/concept-proposals/{code}/drafts",
            headers=editor,
            json={"changes": {"name_ko": "고친 이름"}},
        )
        assert r.status_code == 201, r.text
        assert r.json()["version_no"] == 2
        assert _live(code) == 0

    def test_deleting_a_concept_with_a_published_version_is_refused_by_server_and_by_the_db(
        self, world: _World, client: TestClient
    ) -> None:
        editor = world.user("editor", Role.CONTENT_EDITOR)
        reviewer = world.user("reviewer", Role.CONTENT_REVIEWER)
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        code = world.code()
        vid = client.post(
            "/v1/admin/cms/concept-proposals",
            headers=editor,
            json={"code": code, "payload": _PROPOSAL},
        ).json()["version_id"]
        for who, act, exp in (
            (editor, "submit", "DRAFT"),
            (reviewer, "pass_review", "IN_REVIEW"),
            (reviewer, "approve", "IN_QA"),
            (publisher, "publish", "APPROVED"),
        ):
            assert _transition(client, who, vid, act, exp).status_code == 200
        cid = str(q("SELECT concept_id FROM concept WHERE code = :c", c=code)[0][0])

        # 서버: 발행본이 있으면 409, 개념 행 그대로.
        denied = client.delete(f"/v1/admin/cms/concepts/{cid}", headers=publisher)
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "has_published_version"
        assert _live(code) == 1

        # DB: 서버를 거치지 않는 직접 DELETE도 트리거가 막는다(서버 검사가 유일한 방어선이 아니다).
        with pytest.raises(Exception, match="has a PUBLISHED version"):
            q("DELETE FROM concept WHERE code = :c", c=code)
        assert _live(code) == 1

        # 폐기(deprecate) 후에는 지울 수 있고, 판 이력은 남으며 코드는 예약된다.
        assert _transition(client, publisher, vid, "deprecate", "PUBLISHED").status_code == 200
        gone = client.delete(f"/v1/admin/cms/concepts/{cid}", headers=publisher)
        assert gone.status_code == 200, gone.text
        assert _live(code) == 0
        assert _count("SELECT count(*) FROM concept_version WHERE concept_id = :c", c=code) == 1
        retake = client.post(
            "/v1/admin/cms/concept-proposals",
            headers=editor,
            json={"code": code, "payload": _PROPOSAL},
        )
        assert retake.status_code == 409, "삭제된 개념의 코드가 재사용됐다(이력이 거짓이 된다)"

    def test_a_file_owned_concept_cannot_be_deleted(
        self, world: _World, client: TestClient
    ) -> None:
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        concept = world.live_concept()  # 적재가 소유(표지 없음)
        r = client.delete(f"/v1/admin/cms/concepts/{concept.concept_id}", headers=publisher)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "file_owned"
        assert _live(concept.code) == 1

    def test_the_legacy_direct_create_route_is_closed(
        self, world: _World, client: TestClient
    ) -> None:
        admin = world.user("admin", Role.CONTENT_ADMIN)
        code = world.code()
        r = client.post(
            "/v1/concepts",
            headers=admin,
            json={"code": code, "name_ko": "우회 생성", "level": "단원"},
        )
        assert r.status_code == 410
        assert _live(code) == 0


# ══════════════════════════════════════════════════════════════════════════════════════
# ② 선수 관계 — 서버가 비순환을 강제한다
# ══════════════════════════════════════════════════════════════════════════════════════


def _edge(client: TestClient, headers: dict[str, str], src: Concept, dst: Concept) -> Any:
    return client.post(
        "/v1/admin/cms/edges",
        headers=headers,
        json={"from_concept_id": str(src.concept_id), "to_concept_id": str(dst.concept_id)},
    )


class TestPrerequisiteEdgeWrites:
    def test_a_cycle_is_refused_and_the_database_is_untouched(
        self, world: _World, client: TestClient
    ) -> None:
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        a, b, c = (world.live_concept() for _ in range(3))

        assert _edge(client, publisher, a, b).status_code == 201  # a → b
        assert _edge(client, publisher, b, c).status_code == 201  # b → c
        before_edges = _edges_among(a.concept_id, b.concept_id, c.concept_id)
        before_audit = _audits(world.users["publisher"], "concept_edge")
        assert before_edges == 2 and before_audit == 2

        # c → a 는 a → b → c → a 순환이다 — 422, 경로(개념 코드)를 알려 주고, 어떤 행도 남기지 않는다.
        r = _edge(client, publisher, c, a)
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "prerequisite_cycle"
        assert detail["path"][0] == detail["path"][-1] == c.code, detail["path"]
        assert set(detail["path"]) == {a.code, b.code, c.code}
        assert _edges_among(a.concept_id, b.concept_id, c.concept_id) == before_edges
        assert _audits(world.users["publisher"], "concept_edge") == before_audit

        # 대조군: 순환이 아닌 지름길 a → c 는 통과한다(거부가 과잉이 아님을 보인다).
        assert _edge(client, publisher, a, c).status_code == 201

    def test_a_direct_reverse_edge_and_a_self_edge_are_refused(
        self, world: _World, client: TestClient
    ) -> None:
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        a, b = world.live_concept(), world.live_concept()
        assert _edge(client, publisher, a, b).status_code == 201
        assert _edge(client, publisher, b, a).json()["detail"]["code"] == "prerequisite_cycle"
        assert _edge(client, publisher, a, a).json()["detail"]["code"] == "self_edge"
        dup = _edge(client, publisher, a, b)
        assert dup.status_code == 409 and dup.json()["detail"]["code"] == "edge_exists"
        assert _edges_among(a.concept_id, b.concept_id) == 1

    def test_only_prerequisite_edges_are_writable(self, world: _World, client: TestClient) -> None:
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        a, b = world.live_concept(), world.live_concept()
        r = client.post(
            "/v1/admin/cms/edges",
            headers=publisher,
            json={
                "from_concept_id": str(a.concept_id),
                "to_concept_id": str(b.concept_id),
                "edge_type": "ANALOGOUS_TO",
            },
        )
        assert r.status_code == 422 and r.json()["detail"]["code"] == "edge_type_not_writable"
        assert _edges_among(a.concept_id, b.concept_id) == 0

    def test_two_concurrent_requests_that_would_close_a_cycle_cannot_both_win(
        self, world: _World, client: TestClient
    ) -> None:
        """a→b 와 b→a 를 동시에 보낸다. 각각은 비순환이지만 합치면 순환 — 정확히 한쪽만 성공해야 한다.

        직렬화(어드바이저리 잠금)가 없으면 둘 다 "검사 시점엔 비순환"이라 통과해 순환이 DB에 들어간다.
        """
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        a, b = world.live_concept(), world.live_concept()
        statuses: list[int] = []
        barrier = threading.Barrier(2)

        def fire(src: Concept, dst: Concept) -> None:
            barrier.wait()
            statuses.append(_edge(client, publisher, src, dst).status_code)

        threads = [
            threading.Thread(target=fire, args=(a, b)),
            threading.Thread(target=fire, args=(b, a)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(statuses) == [201, 422], statuses
        assert _edges_among(a.concept_id, b.concept_id) == 1

    def test_only_cms_owned_edges_can_be_deleted(self, world: _World, client: TestClient) -> None:
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        a, b, c = (world.live_concept() for _ in range(3))
        made = _edge(client, publisher, a, b)
        assert made.status_code == 201 and made.json()["cms_owned"] is True
        # graph.json(적재)이 만든 관계 — 표지 없이 직접 삽입해 모사한다.
        q(
            "INSERT INTO concept_edge (from_concept_id, to_concept_id, edge_type) "
            "VALUES (CAST(:f AS uuid), CAST(:t AS uuid), 'PREREQUISITE')",
            f=str(b.concept_id),
            t=str(c.concept_id),
        )
        file_edge = str(
            q(
                "SELECT edge_id FROM concept_edge WHERE from_concept_id = CAST(:f AS uuid)",
                f=str(b.concept_id),
            )[0][0]
        )

        refused = client.delete(f"/v1/admin/cms/edges/{file_edge}", headers=publisher)
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "file_owned"
        assert _edges_among(b.concept_id, c.concept_id) == 1

        ok = client.delete(f"/v1/admin/cms/edges/{made.json()['edge_id']}", headers=publisher)
        assert ok.status_code == 200, ok.text
        assert _edges_among(a.concept_id, b.concept_id) == 0

    def test_concept_detail_tells_the_screen_what_it_may_do(
        self, world: _World, client: TestClient
    ) -> None:
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        editor = world.user("editor", Role.CONTENT_EDITOR)
        a, b = world.live_concept(), world.live_concept()
        _edge(client, publisher, a, b)
        body = client.get(f"/v1/admin/cms/concepts/{b.concept_id}", headers=publisher).json()
        assert body["can_write_graph"] is True
        assert [(e["other_code"], e["cms_owned"]) for e in body["incoming"]] == [(a.code, True)]
        assert body["delete_blocked_code"] == "file_owned"  # b 자체는 적재 소유 개념
        as_editor = client.get(f"/v1/admin/cms/concepts/{b.concept_id}", headers=editor).json()
        assert as_editor["can_write_graph"] is False


# ══════════════════════════════════════════════════════════════════════════════════════
# ④ 권한 — 서버가 403으로 막고 DB가 그대로다
# ══════════════════════════════════════════════════════════════════════════════════════


class TestPermissionsAreEnforcedByTheServer:
    def test_unprivileged_accounts_are_refused_and_nothing_is_written(
        self, world: _World, client: TestClient
    ) -> None:
        a, b = world.live_concept(), world.live_concept()
        cms = world.live_concept(cms_owned=True)
        code = world.code()
        edge_body = {"from_concept_id": str(a.concept_id), "to_concept_id": str(b.concept_id)}
        proposal_body = {"code": code, "payload": _PROPOSAL}

        # (역할, 관계/삭제 가능?, 제안 가능?) — 정확히 선언된 칸만 열린다.
        matrix = [
            ("student", Role.STUDENT, False, False),
            ("editor", Role.CONTENT_EDITOR, False, True),
            ("reviewer", Role.CONTENT_REVIEWER, False, False),
        ]
        for name, role, _graph, may_propose in matrix:
            h = world.user(name, role)
            # 관계 추가·삭제·개념 삭제는 발행 권한 — 이 셋은 전부 403.
            assert client.post("/v1/admin/cms/edges", headers=h, json=edge_body).status_code == 403
            assert (
                client.delete(f"/v1/admin/cms/edges/{uuid.uuid4()}", headers=h).status_code == 403
            )
            assert (
                client.delete(f"/v1/admin/cms/concepts/{cms.concept_id}", headers=h).status_code
                == 403
            )
            if not may_propose:
                r = client.post("/v1/admin/cms/concept-proposals", headers=h, json=proposal_body)
                assert r.status_code == 403, (name, r.status_code)

        # 거부된 요청 뒤 DB는 그대로: 관계 0, 개념 행 살아 있음, 제안(판) 0.
        assert _edges_among(a.concept_id, b.concept_id) == 0
        assert _live(cms.code) == 1
        assert _count("SELECT count(*) FROM concept_version WHERE concept_id = :c", c=code) == 0
        # 거부는 감사 행도 남기지 않는다(쓰기가 없었으므로).
        for name in ("student", "editor", "reviewer"):
            assert _audits(world.users[name], "concept_edge") == 0

    def test_unauthenticated_requests_are_401(self, client: TestClient) -> None:
        for method, path in (
            ("POST", "/v1/admin/cms/edges"),
            ("DELETE", f"/v1/admin/cms/edges/{uuid.uuid4()}"),
            ("DELETE", f"/v1/admin/cms/concepts/{uuid.uuid4()}"),
            ("POST", "/v1/admin/cms/concept-proposals"),
            ("GET", "/v1/admin/cms/concept-proposals"),
        ):
            assert client.request(method, path, json={}).status_code == 401, (method, path)

    def test_the_role_that_may_write_can_(self, world: _World, client: TestClient) -> None:
        """대조군 — 403이 "모든 요청 거부"의 부산물이 아님을 보인다."""
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        a, b = world.live_concept(), world.live_concept()
        assert _edge(client, publisher, a, b).status_code == 201


# ══════════════════════════════════════════════════════════════════════════════════════
# ① 원천 정본 — 적재(CLI)는 CMS가 만든 행을 건드리지 않고 순환도 합쳐서 본다
# ══════════════════════════════════════════════════════════════════════════════════════


def _sync_settings() -> Settings:
    return Settings()


class TestLoaderRespectsCmsOwnership:
    def test_a_reload_skips_cms_owned_edges_and_reports_the_conflict(
        self, world: _World, client: TestClient
    ) -> None:
        from whymath_backend.l1.atom_graph.atom_backend_edge import (
            AtomBackendEdgeRecord,
            populate_atom_edges,
        )
        from whymath_backend.schema.enums import EdgeType

        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        a, b, c = (world.live_concept() for _ in range(3))
        made = _edge(client, publisher, a, b)  # CMS가 만든 a → b (강도 없음)
        assert made.status_code == 201

        def rec(src: Concept, dst: Concept, strength: float) -> AtomBackendEdgeRecord:
            return AtomBackendEdgeRecord(
                from_code=src.code,
                to_code=dst.code,
                edge_type=EdgeType.PREREQUISITE,
                edge_strength=strength,
                relation_subtype="원본",
            )

        conflicts: list[str] = []
        loaded = populate_atom_edges(
            [rec(a, b, 0.9), rec(b, c, 0.7)], settings=_sync_settings(), conflicts=conflicts
        )
        # b→c 는 새로 적재, a→b 는 CMS 소유라 건너뛰고 충돌로 보고한다.
        assert loaded == 1
        assert conflicts == [f"concept_edge:{a.code}->{b.code}"]
        row = q(
            "SELECT edge_strength, cms_edited_at IS NOT NULL FROM concept_edge "
            "WHERE from_concept_id = CAST(:f AS uuid) AND to_concept_id = CAST(:t AS uuid)",
            f=str(a.concept_id),
            t=str(b.concept_id),
        )
        assert row == [(None, True)], "적재가 CMS가 만든 관계를 덮어썼다"

        # --overwrite-cms-edits 는 덮어쓰고 표지를 비운다(파일이 다시 소유).
        conflicts2: list[str] = []
        populate_atom_edges(
            [rec(a, b, 0.9)],
            settings=_sync_settings(),
            overwrite_cms_edits=True,
            conflicts=conflicts2,
        )
        assert conflicts2 == []
        row = q(
            "SELECT edge_strength, cms_edited_at IS NOT NULL FROM concept_edge "
            "WHERE from_concept_id = CAST(:f AS uuid) AND to_concept_id = CAST(:t AS uuid)",
            f=str(a.concept_id),
            t=str(b.concept_id),
        )
        assert [(float(s), m) for s, m in row] == [(0.9, False)]

    def test_a_file_edge_that_closes_a_cycle_with_a_cms_edge_is_refused_before_any_write(
        self, world: _World, client: TestClient
    ) -> None:
        """CMS가 a→b 를 만든 뒤 파일이 b→a(와 새 b→c)를 들고 오면, 합쳐서 순환이다 — 통째로 거부."""
        from whymath_backend.l1.atom_graph.atom_backend_edge import (
            AtomBackendEdgeRecord,
            populate_atom_edges,
        )
        from whymath_backend.l1.concept_graph.prerequisite_guard import PrerequisiteCycleError
        from whymath_backend.schema.enums import EdgeType

        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        a, b, c = (world.live_concept() for _ in range(3))
        assert _edge(client, publisher, a, b).status_code == 201

        def rec(src: Concept, dst: Concept) -> AtomBackendEdgeRecord:
            return AtomBackendEdgeRecord(
                from_code=src.code,
                to_code=dst.code,
                edge_type=EdgeType.PREREQUISITE,
                edge_strength=0.5,
                relation_subtype=None,
            )

        with pytest.raises(PrerequisiteCycleError) as exc:
            populate_atom_edges([rec(b, c), rec(b, a)], settings=_sync_settings())
        assert exc.value.cycle[0] == exc.value.cycle[-1]
        assert {a.code, b.code} <= set(exc.value.cycle)
        # 쓰기 전에 거부 — 무해한 b→c 도 적재되지 않았다(부분 적재 없음).
        assert _edges_among(b.concept_id, c.concept_id) == 0

    def test_a_reload_skips_a_cms_owned_concept_with_the_same_code(self, world: _World) -> None:
        from whymath_backend.l1.atom_graph.atom_backend_concept import (
            AtomBackendConceptRecord,
            populate_atom_concepts,
        )
        from whymath_backend.schema.enums import ConceptLevel

        cms = world.live_concept(cms_owned=True)
        conflicts: list[str] = []
        record = AtomBackendConceptRecord(
            code=cms.code,
            name_ko="파일이 덮으려는 이름",
            level=ConceptLevel.단원,
            parent_code=None,
            intrinsic_difficulty=None,
        )
        written, _ = populate_atom_concepts(
            [record], settings=_sync_settings(), conflicts=conflicts
        )
        assert written == 0 and conflicts == [f"concept:{cms.code}"]
        assert q("SELECT name_ko FROM concept WHERE code = :c", c=cms.code) == [("그래프 개념",)]


# ══════════════════════════════════════════════════════════════════════════════════════
# DB 트리거 — 서버를 거치지 않는 쓰기도 막는다
# ══════════════════════════════════════════════════════════════════════════════════════


class TestDatabaseTriggersBackTheServerRules:
    def test_a_published_version_requires_a_live_concept_row(self, world: _World) -> None:
        code = world.code()
        # DRAFT는 개념 행 없이 넣을 수 있다(제안) — 대조군.
        q(
            "INSERT INTO concept_version (concept_id, version_no, schema_version, status, payload) "
            "VALUES (:c, 1, 'concept-payload@1', 'DRAFT', '{}'::jsonb)",
            c=code,
        )
        # PUBLISHED는 개념 행이 없으면 거부.
        with pytest.raises(Exception, match="requires a live concept row"):
            q(
                "INSERT INTO concept_version "
                "(concept_id, version_no, schema_version, status, payload) "
                "VALUES (:c, 2, 'concept-payload@1', 'PUBLISHED', '{}'::jsonb)",
                c=code,
            )
        with pytest.raises(Exception, match="requires a live concept row"):
            q("UPDATE concept_version SET status = 'PUBLISHED' WHERE concept_id = :c", c=code)
