"""concept API 라우터 단위테스트 — FakeSession 주입(라이브 PG 없음, hermetic).

get_session 의존성을 가짜 세션으로 오버라이드해 *엔드포인트 결선*(상태코드·직렬화·404/409/
422 분기·commit/rollback 호출)을 검증한다. 실제 SQL 정확성은 메인의 실 PG 검증과 통합
테스트(test_concepts_integration.py)가 담당한다 — db 모델 테스트가 from_schema/to_schema
왕복만 보는 것과 같은 분담(라이브 PG는 단위테스트 범위 밖).

app.py L3 테스트가 provider/cache/queue 가짜를 주입하는 것과 동형으로, 여기서는 DB 세션을
FastAPI dependency_overrides로 가짜화한다(create_app의 L3 기본 의존성은 모두 지연이라 구성만
으로 네트워크를 타지 않는다 — app.py docstring).

인가(SEC-07 D1): POST/PATCH/DELETE는 이제 `RequireContentAdmin` 게이트가 있다. 이 파일의
대부분 테스트는 *결선*(상태코드·직렬화·404/409/422)을 보는 것이 목적이라 `_client()`가
`require_content_admin`을 CONTENT_ADMIN 고정 사용자로 오버라이드한다(test_users.py의
`get_consented_user` 오버라이드 패턴과 동형) — 인증 자체는 `TestAuthGate`가 *실제* 의존성으로
검증한다(오버라이드 없이 401/403 확인 + GET 무인증 유지 회귀).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError

from whymath_backend.api._auth import require_content_admin
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.concept import Concept, ConceptEdge
from whymath_backend.db.models.concept_content import ConceptContent
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.concept import ConceptEdge as ConceptEdgeSchema
from whymath_backend.schema.enums import (
    AuditEventKind,
    EdgeType,
    PrivacyAuditAction,
    PrivacyAuditResourceType,
    Role,
)
from whymath_backend.security import create_access_token

_VALID_BODY = {"code": "CAL-INT-FTC", "name_ko": "미적분학의 기본정리", "level": "단원"}

_ADMIN_USER = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)


class _FakeScalars:
    def __init__(self, rows: list[Concept]) -> None:
        self._rows = rows

    def all(self) -> list[Concept]:
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows: list[Concept]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class FakeSession:
    """AsyncSession 표면 일부를 모사 — 라우터가 부르는 메서드만 구현.

    get/execute는 미리 넣어둔 행을 돌려주고, add/commit/rollback/refresh는 호출 사실만
    기록한다(commit_error를 주면 commit이 그 예외를 던져 409 경로를 모사).
    """

    def __init__(
        self,
        *,
        get_map: dict[uuid.UUID, Concept] | None = None,
        content_map: dict[str, ConceptContent] | None = None,
        list_rows: list[Concept] | None = None,
        commit_error: Exception | None = None,
    ) -> None:
        self._get_map = dict(get_map or {})
        # `concept_content`의 기본키는 UUID가 아니라 **코드 문자열**이라 get_map과 키 공간이
        # 다르다. 한 dict에 섞으면 타입이 무너지므로 모델별로 나눠 둔다.
        self._content_map = dict(content_map or {})
        self._list_rows = list(list_rows or [])
        self._commit_error = commit_error
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = False
        self.rolled_back = False

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        if self._commit_error is not None:
            raise self._commit_error
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def refresh(self, obj: Any) -> None:
        return None

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def merge(self, obj: Any) -> Any:
        return obj

    async def get(self, model: Any, pk: Any) -> Any:
        if model is ConceptContent:
            return self._content_map.get(pk)
        return self._get_map.get(pk)

    async def execute(self, stmt: Any) -> _FakeResult:
        return _FakeResult(self._list_rows)


def _client(fake: FakeSession) -> TestClient:
    """get_session을 가짜로, require_content_admin을 고정 관리자로 오버라이드한 TestClient.

    이 파일의 테스트는 CUD *결선*(상태코드·직렬화·404/409/422)이 목적이라 인가는 항상 통과
    시킨다 — 인가 자체의 401/403/GET-무인증 회귀는 `TestAuthGate`가 오버라이드 없이 검증한다.
    """
    app = create_app()

    async def _override() -> AsyncIterator[FakeSession]:
        yield fake

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[require_content_admin] = lambda: _ADMIN_USER
    return TestClient(app)


def _sample_concept(code: str = "CAL-INT-FTC", name: str = "미적분학의 기본정리") -> Concept:
    """from_schema로 만든 transient ORM(라이브 PG 불필요) — get/list 행 모사용."""
    return Concept.from_schema(ConceptSchema(code=code, name_ko=name, level="단원"))


def _sample_edge(from_id: uuid.UUID, to_id: uuid.UUID) -> ConceptEdge:
    return ConceptEdge.from_schema(
        ConceptEdgeSchema(
            from_concept_id=from_id,
            to_concept_id=to_id,
            edge_type=EdgeType.PREREQUISITE,
        )
    )


def _sample_concept_content(
    code: str = "N1",
    *,
    scope: str = "K-12",
    subject: str = "초등수학",
    review_status: str = "ai_estimated",
) -> ConceptContent:
    """`ConceptContent` transient ORM — list_content endpoint 모사용."""
    return ConceptContent(
        code=code,
        scope=scope,
        name=f"name-{code}",
        subject=subject,
        unit="수와 연산",
        metaphor="개수 도구",
        misconception="0 포함 오인",
        formal_definition_internal="정의(내부)",
        accepted_expressions="자연수",
        explanation="기초",
        standard_codes=["[2수01-01]"],
        flashcards=[{"front": "Q", "back": "A"}],
        review_status=review_status,
        updated_at=datetime.now(timezone.utc),
    )


class TestCreate:
    def test_create_returns_201_and_commits(self) -> None:
        """정상 생성 → 201 + code 에코 + commit 호출."""
        fake = FakeSession()
        resp = _client(fake).post("/v1/concepts", json=_VALID_BODY)
        assert resp.status_code == 201, resp.text
        assert resp.json()["code"] == "CAL-INT-FTC"
        assert fake.committed is True
        # SEC-29: Concept 본체 + 콘텐츠CUD 감사 행(PrivacyAudit) = 2건, 같은 트랜잭션.
        assert len(fake.added) == 2

    def test_create_duplicate_code_returns_409(self) -> None:
        """code UNIQUE 충돌(IntegrityError) → 롤백 후 409(스택트레이스 없이)."""
        err = IntegrityError("INSERT", {}, Exception("duplicate key value violates unique"))
        fake = FakeSession(commit_error=err)
        resp = _client(fake).post("/v1/concepts", json=_VALID_BODY)
        assert resp.status_code == 409
        assert fake.rolled_back is True
        assert fake.committed is False

    def test_create_invalid_body_returns_422(self) -> None:
        """필수 필드(name_ko·level) 누락 → 핸들러 전 422(검증은 시스템 경계)."""
        fake = FakeSession()
        resp = _client(fake).post("/v1/concepts", json={"code": "X"})
        assert resp.status_code == 422
        assert fake.committed is False


class TestRead:
    def test_read_existing_returns_200(self) -> None:
        """존재하는 UUID → 200 + to_schema 직렬화."""
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = _client(fake).get(f"/v1/concepts/{concept.concept_id}")
        assert resp.status_code == 200
        assert resp.json()["code"] == concept.code

    def test_read_missing_returns_404(self) -> None:
        """없는 UUID → 404."""
        fake = FakeSession()
        resp = _client(fake).get(f"/v1/concepts/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_read_invalid_uuid_returns_422(self) -> None:
        """경로 파라미터가 UUID가 아니면 422."""
        fake = FakeSession()
        resp = _client(fake).get("/v1/concepts/not-a-uuid")
        assert resp.status_code == 422


class TestList:
    def test_list_returns_rows(self) -> None:
        """행이 있으면 200 + 전부 직렬화."""
        rows = [_sample_concept("C-A", "가"), _sample_concept("C-B", "나")]
        fake = FakeSession(list_rows=rows)
        resp = _client(fake).get("/v1/concepts")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert {item["code"] for item in body} == {"C-A", "C-B"}

    def test_list_empty_returns_empty_array(self) -> None:
        """행이 없으면 200 + 빈 배열."""
        fake = FakeSession()
        resp = _client(fake).get("/v1/concepts")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_rejects_out_of_range_pagination(self) -> None:
        """limit/offset 범위 위반 → 422(Query 제약)."""
        client = _client(FakeSession())
        assert client.get("/v1/concepts?limit=0").status_code == 422
        assert client.get("/v1/concepts?limit=999").status_code == 422
        assert client.get("/v1/concepts?offset=-1").status_code == 422


class TestEdges:
    def test_lists_edges_for_existing_concept(self) -> None:
        concept = _sample_concept()
        edge = _sample_edge(concept.concept_id, uuid.uuid4())
        fake = FakeSession(get_map={concept.concept_id: concept}, list_rows=[edge])
        resp = _client(fake).get(f"/v1/concepts/{concept.concept_id}/edges")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["edge_type"] == "PREREQUISITE"

    def test_edges_404_when_concept_missing(self) -> None:
        resp = _client(FakeSession()).get(f"/v1/concepts/{uuid.uuid4()}/edges")
        assert resp.status_code == 404

    def test_edges_empty_when_no_edges(self) -> None:
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = _client(fake).get(f"/v1/concepts/{concept.concept_id}/edges")
        assert resp.status_code == 200
        assert resp.json() == []


class TestPatch:
    def test_patch_updates_field(self) -> None:
        """제공된 필드만 갱신 → 200 + 병합 결과."""
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = _client(fake).patch(
            f"/v1/concepts/{concept.concept_id}", json={"name_en": "Updated FTC"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name_en"] == "Updated FTC"
        assert fake.committed is True

    def test_patch_404_when_missing(self) -> None:
        resp = _client(FakeSession()).patch(f"/v1/concepts/{uuid.uuid4()}", json={"name_en": "x"})
        assert resp.status_code == 404

    def test_patch_invalid_value_returns_422(self) -> None:
        """병합 결과가 스키마 위반(잘못된 enum) → 422."""
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = _client(fake).patch(f"/v1/concepts/{concept.concept_id}", json={"level": "없는레벨"})
        assert resp.status_code == 422
        assert fake.committed is False

    def test_patch_unknown_field_returns_422(self) -> None:
        """미정의 필드(extra=forbid) → 422."""
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = _client(fake).patch(f"/v1/concepts/{concept.concept_id}", json={"nonexistent": 1})
        assert resp.status_code == 422

    def test_patch_duplicate_code_returns_409(self) -> None:
        """code 변경이 UNIQUE 충돌 → 롤백 후 409."""
        concept = _sample_concept()
        err = IntegrityError("UPDATE", {}, Exception("duplicate key"))
        fake = FakeSession(get_map={concept.concept_id: concept}, commit_error=err)
        resp = _client(fake).patch(f"/v1/concepts/{concept.concept_id}", json={"code": "DUP-CODE"})
        assert resp.status_code == 409
        assert fake.rolled_back is True


class TestDelete:
    def test_delete_returns_204(self) -> None:
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = _client(fake).delete(f"/v1/concepts/{concept.concept_id}")
        assert resp.status_code == 204
        assert fake.committed is True
        assert len(fake.deleted) == 1

    def test_delete_404_when_missing(self) -> None:
        resp = _client(FakeSession()).delete(f"/v1/concepts/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_409_when_referenced(self) -> None:
        """참조(FK)로 IntegrityError → 롤백 후 409."""
        concept = _sample_concept()
        err = IntegrityError("DELETE", {}, Exception("FK violation"))
        fake = FakeSession(get_map={concept.concept_id: concept}, commit_error=err)
        resp = _client(fake).delete(f"/v1/concepts/{concept.concept_id}")
        assert resp.status_code == 409
        assert fake.rolled_back is True


class TestContentMutationAudit:
    """SEC-29(48_보안 §P0) — 콘텐츠 CUD(생성/수정/삭제)가 `PrivacyAudit` 행을 남긴다.

    비관리자/미인증 거부는 `TestAuthGate`(이 파일)가 이미 검증한다 — 여기서는 acceptance④의
    나머지 절반("관리자 동작 시 감사 이벤트 생성")과 그 행의 필드 정합을 검증한다.
    """

    def _audit_rows(self, fake: FakeSession) -> list[PrivacyAudit]:
        return [obj for obj in fake.added if isinstance(obj, PrivacyAudit)]

    def test_create_writes_content_mutation_audit_row(self) -> None:
        fake = FakeSession()
        resp = _client(fake).post("/v1/concepts", json=_VALID_BODY)
        assert resp.status_code == 201, resp.text
        rows = self._audit_rows(fake)
        assert len(rows) == 1
        row = rows[0]
        assert row.user_id == _ADMIN_USER.user_id
        assert row.target_user_id is None
        assert row.event_kind == AuditEventKind.content_mutation.value
        assert row.resource_type == PrivacyAuditResourceType.concept.value
        assert row.action == PrivacyAuditAction.create.value
        assert str(row.resource_id) == resp.json()["concept_id"]

    def test_patch_writes_content_mutation_audit_row(self) -> None:
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = _client(fake).patch(
            f"/v1/concepts/{concept.concept_id}", json={"name_en": "Updated FTC"}
        )
        assert resp.status_code == 200, resp.text
        rows = self._audit_rows(fake)
        assert len(rows) == 1
        assert rows[0].action == PrivacyAuditAction.update.value
        assert rows[0].resource_id == concept.concept_id

    def test_delete_writes_content_mutation_audit_row(self) -> None:
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = _client(fake).delete(f"/v1/concepts/{concept.concept_id}")
        assert resp.status_code == 204
        rows = self._audit_rows(fake)
        assert len(rows) == 1
        assert rows[0].action == PrivacyAuditAction.delete.value
        assert rows[0].resource_id == concept.concept_id

    def test_failed_create_does_not_leave_committed_audit_row(self) -> None:
        """IntegrityError로 롤백되면(409) 감사 행도 함께 롤백 대상(같은 트랜잭션).

        `FakeSession`은 실제 롤백을 모사하지 않으므로(add된 객체를 지우지 않음) 여기서는
        `rolled_back is True`(전체 트랜잭션이 롤백 호출을 받았다)만 확인한다 — 실 PG에서
        ROLLBACK이 add()된 행까지 되돌린다는 것은 DB 트랜잭션의 기본 보장이라 별도 가정이
        필요 없다(session.add는 flush 전까지 방문 상태일 뿐).
        """
        err = IntegrityError("INSERT", {}, Exception("duplicate key value violates unique"))
        fake = FakeSession(commit_error=err)
        resp = _client(fake).post("/v1/concepts", json=_VALID_BODY)
        assert resp.status_code == 409
        assert fake.rolled_back is True
        # 감사 행은 add()는 됐으나(같은 트랜잭션 참여) commit은 되지 않았다.
        assert len(self._audit_rows(fake)) == 1
        assert fake.committed is False


class TestConcurrency:
    """낙관적 동시성 — ETag 노출 + If-Match 조건부 변경."""

    def test_get_and_post_expose_etag(self) -> None:
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        get_resp = _client(fake).get(f"/v1/concepts/{concept.concept_id}")
        assert get_resp.headers.get("ETag", "").startswith('"')
        post_resp = _client(FakeSession()).post("/v1/concepts", json=_VALID_BODY)
        assert post_resp.headers.get("ETag", "").startswith('"')

    def test_patch_with_matching_if_match_succeeds(self) -> None:
        """GET ETag를 If-Match로 보내면(그사이 미변경) 200."""
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        client = _client(fake)
        etag = client.get(f"/v1/concepts/{concept.concept_id}").headers["ETag"]
        resp = client.patch(
            f"/v1/concepts/{concept.concept_id}",
            json={"name_en": "X"},
            headers={"If-Match": etag},
        )
        assert resp.status_code == 200, resp.text

    def test_patch_with_stale_if_match_returns_412(self) -> None:
        """엉뚱한 If-Match(그사이 변경 모사) → 412."""
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = _client(fake).patch(
            f"/v1/concepts/{concept.concept_id}",
            json={"name_en": "X"},
            headers={"If-Match": '"deadbeefdeadbeef"'},
        )
        assert resp.status_code == 412
        assert fake.committed is False

    def test_patch_with_wildcard_if_match_succeeds(self) -> None:
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = _client(fake).patch(
            f"/v1/concepts/{concept.concept_id}",
            json={"name_en": "X"},
            headers={"If-Match": "*"},
        )
        assert resp.status_code == 200

    def test_patch_without_if_match_proceeds(self) -> None:
        """If-Match 미전송 → 무조건 진행(비파괴)."""
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = _client(fake).patch(f"/v1/concepts/{concept.concept_id}", json={"name_en": "X"})
        assert resp.status_code == 200

    def test_delete_with_stale_if_match_returns_412(self) -> None:
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = _client(fake).delete(
            f"/v1/concepts/{concept.concept_id}",
            headers={"If-Match": '"deadbeefdeadbeef"'},
        )
        assert resp.status_code == 412
        assert len(fake.deleted) == 0


class TestConditionalGet:
    """If-None-Match → 304 조건부 GET(캐싱)."""

    def test_matching_if_none_match_returns_304(self) -> None:
        concept = _sample_concept()
        client = _client(FakeSession(get_map={concept.concept_id: concept}))
        etag = client.get(f"/v1/concepts/{concept.concept_id}").headers["ETag"]
        resp = client.get(f"/v1/concepts/{concept.concept_id}", headers={"If-None-Match": etag})
        assert resp.status_code == 304
        assert resp.headers.get("ETag") == etag
        assert resp.content == b""

    def test_wildcard_if_none_match_returns_304(self) -> None:
        concept = _sample_concept()
        client = _client(FakeSession(get_map={concept.concept_id: concept}))
        resp = client.get(f"/v1/concepts/{concept.concept_id}", headers={"If-None-Match": "*"})
        assert resp.status_code == 304

    def test_stale_if_none_match_returns_200(self) -> None:
        concept = _sample_concept()
        client = _client(FakeSession(get_map={concept.concept_id: concept}))
        resp = client.get(
            f"/v1/concepts/{concept.concept_id}",
            headers={"If-None-Match": '"deadbeefdeadbeef"'},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == concept.code

    def test_no_if_none_match_returns_200(self) -> None:
        concept = _sample_concept()
        client = _client(FakeSession(get_map={concept.concept_id: concept}))
        resp = client.get(f"/v1/concepts/{concept.concept_id}")
        assert resp.status_code == 200


_TEST_JWT_SETTINGS = Settings(jwt_secret_key=SecretStr("test-secret-key-0123456789abcdef"))


class TestListContent:
    """GET /v1/concepts/content — 콘텐츠 4종 조회 좌석(내부 표면)."""

    def test_list_content_returns_rows(self) -> None:
        rows = [
            _sample_concept_content("N1", review_status="reviewed"),
            _sample_concept_content("N2", scope="대학", subject="갈루아 이론"),
        ]
        fake = FakeSession(list_rows=rows)
        resp = _client(fake).get("/v1/concepts/content")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert {item["code"] for item in body} == {"N1", "N2"}
        assert body[0]["review_status"] == "reviewed"

    def test_list_content_accepts_query_params(self) -> None:
        """reviewed_only·scope·subject 쿼리 파라미터가 422 없이 수용된다(필터 로직은 SQLAlchemy
        + 실 PG에서 검증 — 단위테스트는 FakeSession이라 필터 미적용)."""
        fake = FakeSession(list_rows=[_sample_concept_content()])
        client = _client(fake)
        assert client.get("/v1/concepts/content?reviewed_only=true").status_code == 200
        assert client.get("/v1/concepts/content?scope=K-12").status_code == 200
        assert (
            client.get(
                "/v1/concepts/content?subject=%EC%B4%88%EB%93%B1%EC%88%98%ED%95%99"
            ).status_code
            == 200
        )

    def test_list_content_pagination_rejects_out_of_range(self) -> None:
        client = _client(FakeSession())
        assert client.get("/v1/concepts/content?limit=0").status_code == 422
        assert client.get("/v1/concepts/content?limit=999").status_code == 422
        assert client.get("/v1/concepts/content?offset=-1").status_code == 422


class TestGetContent:
    """GET /v1/concepts/content/{code} — 단건 조회(P-11 ④로 채운 최소 표면).

    계획서 300 §12의 `GET /contents/{id}`에 대응한다. 목록 좌석과 **같은 응답 스키마**를
    돌려줄 뿐 필드를 늘리지 않는 것이 이 표면의 계약이다.
    """

    def test_get_content_returns_the_row(self) -> None:
        row = _sample_concept_content("N1", review_status="reviewed")
        resp = _client(FakeSession(content_map={"N1": row})).get("/v1/concepts/content/N1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "N1"
        assert body["review_status"] == "reviewed"

    def test_get_content_missing_code_returns_404(self) -> None:
        """부재는 빈 200이 아니라 404다 — 없는 것을 '있는데 비었다'로 돌려주지 않는다."""
        resp = _client(FakeSession(content_map={})).get("/v1/concepts/content/NOPE")
        assert resp.status_code == 404

    def test_get_content_does_not_enrich_the_list_schema(self) -> None:
        """P-11 ④ — 단건이라고 필드를 더 주지 않는다(목록과 키 집합이 같다)."""
        row = _sample_concept_content("N1")
        fake = FakeSession(content_map={"N1": row}, list_rows=[row])
        client = _client(fake)
        single = client.get("/v1/concepts/content/N1").json()
        listed = client.get("/v1/concepts/content").json()
        assert listed, "목록이 비어 대조가 성립하지 않는다"
        assert set(single) == set(listed[0]), (
            f"단건 응답이 목록과 다른 필드 집합을 낸다 — 스키마를 풍부하게 만들지 않는다는 "
            f"계약 위반: 단건만={set(single) - set(listed[0])} 목록만={set(listed[0]) - set(single)}"
        )

    def test_get_content_code_is_not_parsed_as_uuid(self) -> None:
        """코드 문자열이 UUID로 파싱되지 않는다 — 그러면 조회가 영구히 422가 된다."""
        row = _sample_concept_content("MATH.LIMIT.01")
        resp = _client(FakeSession(content_map={"MATH.LIMIT.01": row})).get(
            "/v1/concepts/content/MATH.LIMIT.01"
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["code"] == "MATH.LIMIT.01"


class TestAuthGate:
    """SEC-07 D1 — CUD 인가 회귀(오버라이드 없는 *실제* 의존성) + GET 무인증 유지 동결.

    `require_content_admin`을 오버라이드하지 않는 별도 client를 써서 라우트 결선이 실제
    인증·인가 체인을 타는지 확인한다(get_session만 가짜 — DB 접근 없이 인증 앞단에서
    끝나므로 무관). `get_settings`를 고정 시크릿 `Settings`로 오버라이드해 토큰 mint(테스트)와
    `get_current_user`의 decode(앱)가 같은 시크릿을 쓰게 한다 — 기본 `jwt_secret_key`는 빈
    문자열(`config.py` — 환경변수 `WHYMATH_JWT_SECRET_KEY` 미설정 시 CI가 그렇다)이라 오버라이드
    없이는 decode가 RuntimeError(500)를 던진다(`test_auth.py`의 `Settings(jwt_secret_key=...)`
    직접호출 패턴을 TestClient 왕복용으로 이식).
    """

    def _client_real_auth(self, fake: FakeSession) -> TestClient:
        app = create_app()

        async def _override() -> AsyncIterator[FakeSession]:
            yield fake

        app.dependency_overrides[get_session] = _override
        app.dependency_overrides[get_settings] = lambda: _TEST_JWT_SETTINGS
        return TestClient(app)

    def _token_for(self, user: UserProfile) -> str:
        return create_access_token(user.user_id, settings=_TEST_JWT_SETTINGS)

    # ── 무인증 → CUD 401(GET은 미포함 — 아래 별도 검증) ──
    def test_unauthenticated_post_returns_401(self) -> None:
        resp = self._client_real_auth(FakeSession()).post("/v1/concepts", json=_VALID_BODY)
        assert resp.status_code == 401

    def test_unauthenticated_patch_returns_401(self) -> None:
        resp = self._client_real_auth(FakeSession()).patch(
            f"/v1/concepts/{uuid.uuid4()}", json={"name_en": "x"}
        )
        assert resp.status_code == 401

    def test_unauthenticated_delete_returns_401(self) -> None:
        resp = self._client_real_auth(FakeSession()).delete(f"/v1/concepts/{uuid.uuid4()}")
        assert resp.status_code == 401

    # ── 인증됐으나 역할 불일치(STUDENT) → CUD 403 ──
    def test_student_role_post_returns_403(self) -> None:
        student = UserProfile(user_id=uuid.uuid4(), role=Role.STUDENT)
        fake = FakeSession(get_map={student.user_id: student})
        resp = self._client_real_auth(fake).post(
            "/v1/concepts",
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {self._token_for(student)}"},
        )
        assert resp.status_code == 403

    # ── CONTENT_ADMIN 실 토큰 → 정상 통과(엔드투엔드 결선 확인) ──
    def test_content_admin_role_post_returns_201(self) -> None:
        admin = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
        fake = FakeSession(get_map={admin.user_id: admin})
        resp = self._client_real_auth(fake).post(
            "/v1/concepts",
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {self._token_for(admin)}"},
        )
        assert resp.status_code == 201, resp.text

    # ── GET은 봉인 범위 밖 — 무인증 유지 회귀(과확대 방지) ──
    def test_unauthenticated_get_single_still_public(self) -> None:
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = self._client_real_auth(fake).get(f"/v1/concepts/{concept.concept_id}")
        assert resp.status_code == 200

    def test_unauthenticated_get_list_still_public(self) -> None:
        resp = self._client_real_auth(FakeSession()).get("/v1/concepts")
        assert resp.status_code == 200

    def test_unauthenticated_get_edges_still_public(self) -> None:
        concept = _sample_concept()
        fake = FakeSession(get_map={concept.concept_id: concept})
        resp = self._client_real_auth(fake).get(f"/v1/concepts/{concept.concept_id}/edges")
        assert resp.status_code == 200
