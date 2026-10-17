"""Admin CMS 실 PostgreSQL 종단 간 — P3-12 (기본 SKIP, `WHYMATH_RUN_INTEGRATION=1` + head 적용 PG).

hermetic 테스트(`test_admin_cms.py`)는 게이트 서비스를 스파이로 대체한다. 이 파일은 **대체하지 않는다**:
역할별 실제 JWT → 실제 `get_current_user`(DB 사용자 로드) → 실제 모듈 가드·권한 검사 → 실제
`publish_gate`(행 잠금·전이표·게이트·해시) → 실제 감사 행까지 왕복하고, 거부된 요청 뒤 **DB 상태가 그대로인지**
를 SQL로 직접 읽어 단언한다(응답 코드만 보지 않는다).

CI는 통합 테스트를 건너뛴다(`WHYMATH_RUN_INTEGRATION` 미설정) — 그래서 이 파일은 CI의 증거가 아니라
**개발 중 실 DB 검증**이다. CI의 증거는 hermetic 파일들이다.

설정/정리는 전역 캐시 엔진이 아니라 *독립 엔진*으로 한다(asyncpg 엔진은 이벤트 루프에 묶인다).
"""

from __future__ import annotations

import asyncio
import json
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
from whymath_backend.db.models.concept_content import ConceptContent
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.user import UserProfile
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.enums import (
    Curriculum,
    Persona,
    ReviewStatus,
    Role,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

pytestmark = pytest.mark.integration

_JWT_SECRET = "cms-integration-jwt-secret-0123456789abcdef"


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_JWT_SECRET))


def _engine() -> Any:
    return create_async_engine(Settings().database_url)


async def _ready() -> bool:
    """PG 도달 + 이 태스크의 리비전 적용(`role_enum`에 CMS 역할 존재)."""
    engine = _engine()
    try:
        async with engine.connect() as conn:
            found = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                        "WHERE t.typname = 'role_enum' AND e.enumlabel = 'content_publisher'"
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


async def _add(*objs: Any) -> None:
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(objs)
            await session.commit()
    finally:
        await engine.dispose()


def _user(role: Role) -> uuid.UUID:
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
    """한 테스트가 만든 행을 기억했다가 FK 순서대로 지운다."""

    def __init__(self) -> None:
        self.users: dict[str, uuid.UUID] = {}
        self.concept_codes: list[str] = []
        self.concept_content_codes: list[str] = []
        self.problem_ids: list[uuid.UUID] = []

    def user(self, name: str, role: Role) -> dict[str, str]:
        uid = _user(role)
        self.users[name] = uid
        return _headers(uid)

    def concept(self) -> Concept:
        code = f"CMS-IT-{uuid.uuid4().hex[:8]}"
        row = Concept.from_schema(ConceptSchema(code=code, name_ko="통합 개념", level="단원"))
        _run(_add(row))
        self.concept_codes.append(code)
        return row

    def content(self, *, review_status: str = "reviewed") -> str:
        code = f"CMS-IT-C-{uuid.uuid4().hex[:8]}"
        _run(
            _add(
                ConceptContent(
                    code=code,
                    scope="K12",
                    name="통합 설명",
                    subject="수학",
                    explanation="처음 설명",
                    review_status=review_status,
                    flashcards=[],
                    standard_codes=[],
                    atom_codes=[],
                )
            )
        )
        self.concept_content_codes.append(code)
        return code

    def problem(self, review_status: ReviewStatus | None) -> uuid.UUID:
        row = Problem.from_schema(
            ProblemSchema(
                source_type=SourceType.자체생성,
                curriculum_version=Curriculum.REVISION_2015,
                valid_from_year=2014,
                subject=Subject.미적분,
                unit_codes=["CAL-INT-DEF"],
                answer="원래 정답",
                review_status=review_status,
            )
        )
        _run(_add(row))
        self.problem_ids.append(row.problem_id)
        return row.problem_id

    async def _cleanup(self) -> None:
        engine = _engine()
        try:
            async with engine.begin() as conn:
                for code in self.concept_codes:
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
                for code in self.concept_content_codes:
                    await conn.execute(
                        text("DELETE FROM concept_content WHERE code = :c"), {"c": code}
                    )
                for pid in self.problem_ids:
                    await conn.execute(
                        text("DELETE FROM problem WHERE problem_id = CAST(:p AS uuid)"),
                        {"p": str(pid)},
                    )
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
        pytest.skip("PostgreSQL 미도달 또는 리비전 c5e9f3a7b1d4 미적용 — 통합 테스트 건너뜀")
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


def _status_of(version_id: str) -> str:
    return str(
        _run(
            _sql(
                "SELECT status FROM concept_version WHERE version_id = CAST(:v AS uuid)",
                v=version_id,
            )
        )[0][0]
    )


def _pointer_of(code: str) -> str | None:
    value = _run(_sql("SELECT current_published_version_id FROM concept WHERE code = :c", c=code))[
        0
    ][0]
    return None if value is None else str(value)


def _transition(
    client: TestClient, headers: dict[str, str], version_id: str, action: str, expected: str
) -> Any:
    return client.post(
        f"/v1/admin/cms/versions/{version_id}/transitions",
        headers=headers,
        json={"action": action, "expected_status": expected},
    )


class TestConceptWorkflowEndToEnd:
    def test_roles_move_a_concept_from_draft_to_published_and_back(
        self, world: _World, client: TestClient
    ) -> None:
        editor = world.user("editor", Role.CONTENT_EDITOR)
        reviewer = world.user("reviewer", Role.CONTENT_REVIEWER)
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        student = world.user("student", Role.STUDENT)
        concept = world.concept()
        cid, code = str(concept.concept_id), concept.code

        # ── 편집자가 새 판(초안)을 만든다. 살아있는 행은 건드리지 않는다.
        r = client.post(
            f"/v1/admin/cms/concepts/{cid}/drafts",
            headers=editor,
            json={"changes": {"name_ko": "고친 이름"}, "reason": "표기 정정"},
        )
        assert r.status_code == 201, r.text
        v1 = r.json()
        assert (v1["version_no"], v1["status"]) == (1, "DRAFT")
        assert v1["created_by"] == str(world.users["editor"])
        assert v1["allowed_actions"] == ["submit"]  # 편집자가 지금 할 수 있는 것은 제출뿐
        live_name = _run(_sql("SELECT name_ko FROM concept WHERE code = :c", c=code))[0][0]
        assert live_name == "통합 개념", "초안 생성이 살아있는 개념 행을 바꿨다"
        vid = v1["version_id"]

        # ── 편집자는 발행할 수 없다 — 거부 뒤 DB 상태 그대로.
        denied = _transition(client, editor, vid, "publish", "DRAFT")
        assert denied.status_code == 403
        assert _status_of(vid) == "DRAFT"
        assert _pointer_of(code) is None

        # ── 학생은 이력도 못 본다.
        assert (
            client.get(f"/v1/admin/cms/concepts/{cid}/versions", headers=student).status_code == 403
        )

        # ── 제출(편집자) → 검토 통과·승인(검수자). 편집자는 검토 단계를, 검수자는 발행을 못 한다.
        assert _transition(client, editor, vid, "submit", "DRAFT").json()["status"] == "IN_REVIEW"
        assert _transition(client, editor, vid, "pass_review", "IN_REVIEW").status_code == 403
        assert (
            _transition(client, reviewer, vid, "pass_review", "IN_REVIEW").json()["status"]
            == "IN_QA"
        )
        approved = _transition(client, reviewer, vid, "approve", "IN_QA")
        assert approved.status_code == 200, approved.text
        body = approved.json()
        assert body["status"] == "APPROVED"
        assert body["reviewed_by"] == str(world.users["reviewer"])
        assert body["approved_by"] == str(world.users["reviewer"])
        assert body["content_hash"].startswith("sha256:")
        assert _transition(client, reviewer, vid, "publish", "APPROVED").status_code == 403
        assert _status_of(vid) == "APPROVED" and _pointer_of(code) is None

        # ── 배포자: 오래된 화면 상태로는 거부(409), 최신 상태로는 발행.
        stale = _transition(client, publisher, vid, "publish", "IN_QA")
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_status"
        assert stale.json()["detail"]["current_status"] == "APPROVED"
        assert _status_of(vid) == "APPROVED"
        published = _transition(client, publisher, vid, "publish", "APPROVED")
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "PUBLISHED"
        assert _pointer_of(code) == vid

        # ── 레거시 CRUD로 발행 포인터를 바꾸려는 시도는 거부된다(워크플로우 우회 차단).
        admin = world.user("admin", Role.CONTENT_ADMIN)
        bypass = client.patch(
            f"/v1/concepts/{cid}",
            headers=admin,
            json={"current_published_version_id": str(uuid.uuid4())},
        )
        assert bypass.status_code == 422, bypass.text
        assert bypass.json()["detail"]["code"] == "publish_pointer_readonly"
        assert _pointer_of(code) == vid, "우회 시도 뒤 발행 포인터가 바뀌었다"

        # ── 두 번째 판: 기준은 최신 판의 payload, 발행하면 v1은 DEPRECATED.
        r2 = client.post(
            f"/v1/admin/cms/concepts/{cid}/drafts",
            headers=editor,
            json={"changes": {"name_en": "Fixed"}},
        )
        v2 = r2.json()
        assert (v2["version_no"], v2["status"]) == (2, "DRAFT")
        detail2 = client.get(f"/v1/admin/cms/versions/{v2['version_id']}", headers=editor).json()
        assert detail2["payload"]["name_ko"] == "고친 이름"  # v1의 변경이 기준으로 이어졌다
        assert detail2["payload"]["name_en"] == "Fixed"
        vid2 = v2["version_id"]
        _transition(client, editor, vid2, "submit", "DRAFT")
        _transition(client, reviewer, vid2, "pass_review", "IN_REVIEW")
        _transition(client, reviewer, vid2, "approve", "IN_QA")
        assert _transition(client, publisher, vid2, "publish", "APPROVED").status_code == 200
        assert _pointer_of(code) == vid2 and _status_of(vid) == "DEPRECATED"

        # ── 롤백: 편집자는 모듈 가드에서 막히고, 배포자는 오래된 포인터로는 거부된다.
        url = f"/v1/admin/cms/concepts/{cid}/rollback"
        assert (
            client.post(
                url, headers=editor, json={"expected_published_version_id": vid2}
            ).status_code
            == 403
        )
        stale_rb = client.post(url, headers=publisher, json={"expected_published_version_id": vid})
        assert stale_rb.status_code == 409 and stale_rb.json()["detail"]["code"] == "stale_pointer"
        assert _pointer_of(code) == vid2
        ok = client.post(url, headers=publisher, json={"expected_published_version_id": vid2})
        assert ok.status_code == 200, ok.text
        assert ok.json()["restored_version_id"] == vid
        assert ok.json()["rolled_back_version_id"] == vid2
        assert _pointer_of(code) == vid
        assert (_status_of(vid), _status_of(vid2)) == ("PUBLISHED", "RETIRED")

        # ── 변경이력: 이 판에 대한 동작이 감사에 순서대로 남았다.
        hist = client.get(
            f"/v1/admin/cms/audit?resource_type=concept_version&resource_key={vid}", headers=editor
        ).json()
        actions = [row["action"] for row in hist["items"]]
        assert sorted(actions) == sorted(["create", "submit", "pass_review", "approve", "publish"])
        hist2 = client.get(
            f"/v1/admin/cms/audit?resource_type=concept_version&resource_key={vid2}", headers=editor
        ).json()
        assert "rollback" in [row["action"] for row in hist2["items"]]

        # ── 변경이력 화면 데이터: 판 목록은 최신부터이고 호출자 권한으로 걸러진 전이만 담는다.
        listing = client.get(f"/v1/admin/cms/concepts/{cid}/versions", headers=editor).json()
        assert [v["version_no"] for v in listing] == [2, 1]

    def test_tampered_payload_cannot_be_published(self, world: _World, client: TestClient) -> None:
        """승인 뒤 payload를 DB에서 바꾸면(DB 트리거는 PUBLISHED만 보호) 발행 게이트가 해시로 거부한다."""
        editor = world.user("editor", Role.CONTENT_EDITOR)
        reviewer = world.user("reviewer", Role.CONTENT_REVIEWER)
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        concept = world.concept()
        cid, code = str(concept.concept_id), concept.code
        vid = client.post(f"/v1/admin/cms/concepts/{cid}/drafts", headers=editor, json={}).json()[
            "version_id"
        ]
        _transition(client, editor, vid, "submit", "DRAFT")
        _transition(client, reviewer, vid, "pass_review", "IN_REVIEW")
        _transition(client, reviewer, vid, "approve", "IN_QA")
        _run(
            _sql(
                "UPDATE concept_version SET payload = jsonb_set(payload, '{name_ko}', '\"변조\"') "
                "WHERE version_id = CAST(:v AS uuid)",
                v=vid,
            )
        )
        refused = _transition(client, publisher, vid, "publish", "APPROVED")
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["code"] == "gate_failed"
        assert any("content_hash" in f for f in refused.json()["detail"]["failures"])
        assert _status_of(vid) == "APPROVED" and _pointer_of(code) is None

    def test_unknown_skill_is_rejected_against_the_real_skill_table(
        self, world: _World, client: TestClient
    ) -> None:
        editor = world.user("editor", Role.CONTENT_EDITOR)
        concept = world.concept()
        r = client.post(
            f"/v1/admin/cms/concepts/{concept.concept_id}/drafts",
            headers=editor,
            json={"changes": {"behavior_skills": ["SK-NOT-REAL-" + uuid.uuid4().hex[:6]]}},
        )
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "unknown_skill"
        assert (
            _run(
                _sql("SELECT count(*) FROM concept_version WHERE concept_id = :c", c=concept.code)
            )[0][0]
            == 0
        )


class TestInPlaceEditEndToEnd:
    def test_edit_lowers_the_review_mark_and_only_a_reviewer_raises_it(
        self, world: _World, client: TestClient
    ) -> None:
        editor = world.user("editor", Role.CONTENT_EDITOR)
        reviewer = world.user("reviewer", Role.CONTENT_REVIEWER)
        publisher = world.user("publisher", Role.CONTENT_PUBLISHER)
        code = world.content(review_status="reviewed")
        url = f"/v1/admin/cms/concept_content/items/{code}"

        assert (
            client.patch(url, headers=publisher, json={"changes": {"explanation": "x"}}).status_code
            == 403
        )
        r = client.patch(url, headers=editor, json={"changes": {"explanation": "새 설명"}})
        assert r.status_code == 200, r.text
        assert r.json()["server_reset"] == ["review_status"]
        row = _run(
            _sql("SELECT explanation, review_status FROM concept_content WHERE code = :c", c=code)
        )[0]
        assert tuple(row) == ("새 설명", "ai_estimated")

        # 편집자는 스스로 검수됨으로 올릴 수 없다.
        assert (
            client.post(f"{url}/review", headers=editor, json={"decision": "reviewed"}).status_code
            == 403
        )
        up = client.post(f"{url}/review", headers=reviewer, json={"decision": "reviewed"})
        assert up.status_code == 200 and up.json() == {"changed": True, "review_status": "reviewed"}
        # 같은 내용 재저장은 검수를 풀지 않는다.
        same = client.patch(url, headers=editor, json={"changes": {"explanation": "새 설명"}})
        assert same.json()["changed"] == []
        assert (
            _run(_sql("SELECT review_status FROM concept_content WHERE code = :c", c=code))[0][0]
            == "reviewed"
        )

        # 상태 컬럼을 직접 쓰려는 시도 — 422, DB 그대로.
        bad = client.patch(url, headers=editor, json={"changes": {"review_status": "reviewed"}})
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "field_not_editable"

        hist = client.get(
            f"/v1/admin/cms/audit?resource_type=concept_content&resource_key={code}", headers=editor
        ).json()
        assert sorted(i["action"] for i in hist["items"]) == ["approve", "update"]

    def test_approved_problem_must_be_quarantined_before_it_can_be_edited(
        self, world: _World, client: TestClient
    ) -> None:
        """검수 축을 우회하지 않는다: 승인된 문항 수정 → 거부 → 격리(검수자) → 수정 → 격리 해제."""
        editor = world.user("editor", Role.CONTENT_EDITOR)
        reviewer = world.user("reviewer", Role.CONTENT_REVIEWER)
        pid = world.problem(ReviewStatus.approved)
        url = f"/v1/admin/cms/problem/items/{pid}"

        blocked = client.patch(url, headers=editor, json={"changes": {"answer": "새 정답"}})
        assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "edit_blocked"
        assert (
            _run(
                _sql("SELECT answer FROM problem WHERE problem_id = CAST(:p AS uuid)", p=str(pid))
            )[0][0]
            == "원래 정답"
        )

        # 편집자는 격리할 수 없다(검수 큐는 검수 권한) — 검수자가 격리한다.
        q_url = f"/v1/admin/review-queue/items/{pid}/transitions"
        no = client.post(
            q_url,
            headers=editor,
            json={"action": "quarantine", "expected_status": "approved", "reason": "정답 오류"},
        )
        assert no.status_code == 403
        yes = client.post(
            q_url,
            headers=reviewer,
            json={"action": "quarantine", "expected_status": "approved", "reason": "정답 오류"},
        )
        assert yes.status_code == 200, yes.text

        ok = client.patch(
            url, headers=editor, json={"changes": {"answer": "새 정답", "difficulty_overall": 3.0}}
        )
        assert ok.status_code == 200, ok.text
        row = _run(
            _sql(
                "SELECT answer, review_status FROM problem WHERE problem_id = CAST(:p AS uuid)",
                p=str(pid),
            )
        )[0]
        assert tuple(row) == ("새 정답", "quarantined")  # 편집은 검수 상태를 바꾸지 않는다

        back = client.post(
            q_url, headers=reviewer, json={"action": "release", "expected_status": "quarantined"}
        )
        assert back.status_code == 200, back.text
        assert (
            _run(
                _sql(
                    "SELECT review_status FROM problem WHERE problem_id = CAST(:p AS uuid)",
                    p=str(pid),
                )
            )[0][0]
            == "approved"
        )

    def test_pending_problem_edit_cannot_smuggle_an_approval(
        self, world: _World, client: TestClient
    ) -> None:
        editor = world.user("editor", Role.CONTENT_EDITOR)
        pid = world.problem(ReviewStatus.pending)
        r = client.patch(
            f"/v1/admin/cms/problem/items/{pid}",
            headers=editor,
            json={"changes": {"answer": "x", "review_status": "approved", "is_published": True}},
        )
        assert r.status_code == 422, r.text
        row = _run(
            _sql(
                "SELECT review_status::text, answer FROM problem WHERE problem_id = CAST(:p AS uuid)",
                p=str(pid),
            )
        )[0]
        assert tuple(row) == ("pending", "원래 정답")


class TestMenuPerRole:
    def test_each_role_gets_only_its_modules_from_the_real_menu_endpoint(
        self, world: _World, client: TestClient
    ) -> None:
        def modules(headers: dict[str, str]) -> set[str]:
            body = client.get("/v1/admin/menu", headers=headers).json()
            return {m["id"] for s in body["sections"] for m in s["items"]}

        editor = modules(world.user("e", Role.CONTENT_EDITOR))
        reviewer = modules(world.user("r", Role.CONTENT_REVIEWER))
        publisher = modules(world.user("p", Role.CONTENT_PUBLISHER))
        assert (
            "content_library" in editor
            and "review_queue" not in editor
            and "deployment" not in editor
        )
        assert "review_queue" in reviewer and "deployment" not in reviewer
        assert "deployment" in publisher and "review_queue" not in publisher
        for ids in (editor, reviewer, publisher):
            assert "cost_report" not in ids and "user_lookup" not in ids
        assert json.dumps(sorted(editor))  # 직렬화 가능
