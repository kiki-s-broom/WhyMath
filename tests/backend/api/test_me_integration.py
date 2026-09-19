"""me 라우터 통합테스트 — 실 PG로 본인 데이터 스코핑 검증 (기본 SKIP).

핵심: 두 사용자 A·B의 학습 세션을 적재하고, A 토큰으로 /v1/me/sessions를 부르면 **A의 것만**
나오는지(타인 데이터 차단 — CLAUDE.md 미성년 PII·식별 분석 금기) 검증한다. get_settings만
오버라이드(jwt 시크릿), get_session은 실 PG. 행은 독립 엔진으로 ORM 적재·정리(FK 순서 준수).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.activity import LearningSession, ProblemAttempt
from whymath_backend.db.models.assessment import ConceptMasteryHistory
from whymath_backend.db.models.atom_node import AtomNode
from whymath_backend.db.models.audit import DeletionAudit
from whymath_backend.db.models.concept import Concept, ConceptEdge, ProblemConcept
from whymath_backend.db.models.problem import Problem, ProblemRelation
from whymath_backend.db.models.user import UserProfile
from whymath_backend.l2.ability_tracking import get_current_theta
from whymath_backend.schema.activity import LearningSession as LearningSessionSchema
from whymath_backend.schema.assessment import (
    ConceptMasteryHistory as ConceptMasteryHistorySchema,
)
from whymath_backend.schema.audit import DeletionAudit as DeletionAuditSchema
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.concept import ProblemConcept as ProblemConceptSchema
from whymath_backend.schema.enums import (
    AuditResourceType,
    ConceptLevel,
    ConceptRole,
    Curriculum,
    EdgeType,
    Persona,
    RelationType,
    ReviewStatus,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema
from whymath_backend.schema.problem import ProblemRelation as ProblemRelationSchema
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

pytestmark = pytest.mark.integration

_SECRET = "integration-jwt-secret-0123456789abcdef"


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_SECRET))


async def _pg_reachable() -> bool:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def _add_all(*objs: object) -> None:
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(list(objs))
            await session.commit()
    finally:
        await engine.dispose()


async def _cleanup(user_ids: list[uuid.UUID]) -> None:
    engine = create_async_engine(_settings().database_url)
    ids = [str(u) for u in user_ids]
    try:
        async with engine.begin() as conn:
            # FK 순서: 자식(learning_session) 먼저, 부모(user_profile) 나중.
            await conn.execute(
                text("DELETE FROM learning_session WHERE user_id = ANY(:ids)"),
                {"ids": ids},
            )
            # deletion_audit는 user_id가 FK 아님(독립 잔존 로그) — user_id로 정리.
            await conn.execute(
                text("DELETE FROM deletion_audit WHERE user_id = ANY(:ids)"),
                {"ids": ids},
            )
            await conn.execute(
                text("DELETE FROM user_profile WHERE user_id = ANY(:ids)"), {"ids": ids}
            )
    finally:
        await engine.dispose()


def _user(uid: uuid.UUID) -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(user_id=uid, persona_primary=Persona.A_일반고고3)
    )


def _session_row(
    sid: uuid.UUID,
    uid: uuid.UUID,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> LearningSession:
    # started_at 생략 시 server_default now(). 시간창 테스트는 명시 값 주입.
    # ended_at은 nullable(미종료 None) — slice 69 ended_at 시간창 테스트용.
    return LearningSession.from_schema(
        LearningSessionSchema(session_id=sid, user_id=uid, started_at=started_at, ended_at=ended_at)
    )


def _deletion_row(
    uid: uuid.UUID,
    resource_type: AuditResourceType,
    deleted_at: datetime | None = None,
) -> DeletionAudit:
    # from_schema는 deleted_at을 명시 전달하므로 None이면 NOT NULL 위반 위험(운영 경로는
    # deleted_at 생략→server_default now()). 시드는 항상 명시 timestamp(미지정 시 현재) 주입.
    return DeletionAudit.from_schema(
        DeletionAuditSchema(
            user_id=uid,
            resource_type=resource_type,
            resource_id=uuid.uuid4(),
            deleted_at=deleted_at or datetime.now(UTC),
        )
    )


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = _settings
    return TestClient(app)


def test_me_sessions_scoped_to_current_user_on_live_pg() -> None:
    """A·B 세션 적재 → A 토큰 /me/sessions는 A의 것만(B 제외). 무토큰 401."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    uid_a, uid_b = uuid.uuid4(), uuid.uuid4()
    sid_a, sid_b = uuid.uuid4(), uuid.uuid4()
    try:
        # FK 순서: 부모(user_profile) 먼저 커밋 → 자식(learning_session). user_id는
        # 원시 FK 컬럼(관계 아님)이라 한 flush에 섞으면 INSERT 순서를 못 정한다.
        asyncio.run(_add_all(_user(uid_a), _user(uid_b)))
        asyncio.run(_add_all(_session_row(sid_a, uid_a), _session_row(sid_b, uid_b)))
        token_a = create_access_token(uid_a, settings=_settings())
        auth = {"Authorization": f"Bearer {token_a}"}
        with _client() as client:
            resp = client.get("/v1/me/sessions", headers=auth)
            assert resp.status_code == 200, resp.text
            ids = {s["session_id"] for s in resp.json()}
            assert str(sid_a) in ids  # 본인 것 보임
            assert str(sid_b) not in ids  # 타인 것 차단 — 핵심 보안

            # 데이터 없는 본인 도메인은 [](스코핑·결선 확인)
            assert client.get("/v1/me/assessments", headers=auth).json() == []
            assert client.get("/v1/me/dialogues", headers=auth).json() == []

            assert client.get("/v1/me/sessions").status_code == 401  # 무토큰
    finally:
        asyncio.run(_cleanup([uid_a, uid_b]))


def test_me_deletions_resource_type_filter_on_live_pg() -> None:
    """slice 65: ?resource_type 필터가 실 PG에서 해당 도메인만 반환·생략 시 전체.

    A의 삭제 감사를 도메인별로 적재(learning_session×2·dialogue×1) → ?resource_type=
    learning_session은 2건·dialogue는 1건·필터 생략은 3건 모두. 본인 스코핑도 함께 확인.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    uid_a = uuid.uuid4()
    try:
        asyncio.run(_add_all(_user(uid_a)))
        asyncio.run(
            _add_all(
                _deletion_row(uid_a, AuditResourceType.learning_session),
                _deletion_row(uid_a, AuditResourceType.learning_session),
                _deletion_row(uid_a, AuditResourceType.dialogue),
            )
        )
        token_a = create_access_token(uid_a, settings=_settings())
        auth = {"Authorization": f"Bearer {token_a}"}
        with _client() as client:
            # 필터 생략 → 3건 전체
            resp = client.get("/v1/me/deletions", headers=auth)
            assert resp.status_code == 200, resp.text
            assert len(resp.json()) == 3

            # learning_session 필터 → 2건, 모두 해당 도메인
            resp = client.get(
                "/v1/me/deletions",
                headers=auth,
                params={"resource_type": "learning_session"},
            )
            assert resp.status_code == 200, resp.text
            rows = resp.json()
            assert len(rows) == 2
            assert {r["resource_type"] for r in rows} == {"learning_session"}

            # dialogue 필터 → 1건
            resp = client.get(
                "/v1/me/deletions", headers=auth, params={"resource_type": "dialogue"}
            )
            assert resp.status_code == 200, resp.text
            assert len(resp.json()) == 1

            # 삭제 이력 없는 도메인 → []
            resp = client.get(
                "/v1/me/deletions", headers=auth, params={"resource_type": "assessment"}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json() == []

            # slice 68: 다중 OR(IN) — learning_session + dialogue → 3건(2+1)
            resp = client.get(
                "/v1/me/deletions",
                headers=auth,
                params=[
                    ("resource_type", "learning_session"),
                    ("resource_type", "dialogue"),
                ],
            )
            assert resp.status_code == 200, resp.text
            rows = resp.json()
            assert len(rows) == 3
            assert {r["resource_type"] for r in rows} == {
                "learning_session",
                "dialogue",
            }

            # slice 71: include_total → X-Total-Count = 필터 적용 총 건수(limit/offset 무시)
            resp = client.get("/v1/me/deletions", headers=auth, params={"include_total": "true"})
            assert resp.headers["X-Total-Count"] == "3", resp.headers
            # 필터 + 페이지 축소에도 total은 *전체 필터 건수* — learning_session 2건
            resp = client.get(
                "/v1/me/deletions",
                headers=auth,
                params={
                    "resource_type": "learning_session",
                    "limit": "1",
                    "include_total": "true",
                },
            )
            assert len(resp.json()) == 1  # 페이지는 1건
            assert resp.headers["X-Total-Count"] == "2", resp.headers  # 총 2건
            # include_total 생략 → 헤더 없음
            resp = client.get("/v1/me/deletions", headers=auth)
            assert "X-Total-Count" not in resp.headers
    finally:
        asyncio.run(_cleanup([uid_a]))


def test_me_deletions_time_window_filter_on_live_pg() -> None:
    """slice 66: ?since/until이 실 PG에서 deleted_at 시간창으로 필터(inclusive).

    A의 삭제 감사를 1월·6월·12월로 적재 → since=6월은 6·12월 2건·until=6월은 1·6월 2건·
    since=6월&until=6월은 6월 1건(inclusive 경계 확인)·필터 생략은 3건 전체.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    jan = datetime(2024, 1, 15, tzinfo=UTC)
    jun = datetime(2024, 6, 15, tzinfo=UTC)
    dec = datetime(2024, 12, 15, tzinfo=UTC)
    uid_a = uuid.uuid4()
    try:
        asyncio.run(_add_all(_user(uid_a)))
        asyncio.run(
            _add_all(
                _deletion_row(uid_a, AuditResourceType.dialogue, jan),
                _deletion_row(uid_a, AuditResourceType.dialogue, jun),
                _deletion_row(uid_a, AuditResourceType.dialogue, dec),
            )
        )
        token_a = create_access_token(uid_a, settings=_settings())
        auth = {"Authorization": f"Bearer {token_a}"}
        with _client() as client:
            # 필터 생략 → 3건
            assert len(client.get("/v1/me/deletions", headers=auth).json()) == 3

            # since=6월 → 6·12월(inclusive)
            resp = client.get("/v1/me/deletions", headers=auth, params={"since": jun.isoformat()})
            assert len(resp.json()) == 2, resp.text

            # until=6월 → 1·6월(inclusive)
            resp = client.get("/v1/me/deletions", headers=auth, params={"until": jun.isoformat()})
            assert len(resp.json()) == 2, resp.text

            # since=6월 & until=6월 → 6월 1건(양끝 inclusive 경계)
            resp = client.get(
                "/v1/me/deletions",
                headers=auth,
                params={"since": jun.isoformat(), "until": jun.isoformat()},
            )
            assert len(resp.json()) == 1, resp.text
    finally:
        asyncio.run(_cleanup([uid_a]))


def test_me_sessions_time_window_filter_on_live_pg() -> None:
    """slice 67: /me/sessions의 ?since/until이 실 PG에서 started_at 시간창으로 필터.

    1·6·12월 세션 적재 → since=6월 2건·until=6월 2건·양끝=6월 1건·생략 3건. deletions와
    동일한 시간창 의미(apply_time_window 공용)를 다른 도메인에서도 검증.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    jan = datetime(2024, 1, 15, tzinfo=UTC)
    jun = datetime(2024, 6, 15, tzinfo=UTC)
    dec = datetime(2024, 12, 15, tzinfo=UTC)
    uid_a = uuid.uuid4()
    try:
        asyncio.run(_add_all(_user(uid_a)))
        asyncio.run(
            _add_all(
                _session_row(uuid.uuid4(), uid_a, jan),
                _session_row(uuid.uuid4(), uid_a, jun),
                _session_row(uuid.uuid4(), uid_a, dec),
            )
        )
        token_a = create_access_token(uid_a, settings=_settings())
        auth = {"Authorization": f"Bearer {token_a}"}
        with _client() as client:
            assert len(client.get("/v1/me/sessions", headers=auth).json()) == 3

            resp = client.get("/v1/me/sessions", headers=auth, params={"since": jun.isoformat()})
            assert len(resp.json()) == 2, resp.text

            resp = client.get("/v1/me/sessions", headers=auth, params={"until": jun.isoformat()})
            assert len(resp.json()) == 2, resp.text

            resp = client.get(
                "/v1/me/sessions",
                headers=auth,
                params={"since": jun.isoformat(), "until": jun.isoformat()},
            )
            assert len(resp.json()) == 1, resp.text
    finally:
        asyncio.run(_cleanup([uid_a]))


def test_me_sessions_order_param_on_live_pg() -> None:
    """slice 70: ?order=asc/desc가 실 PG에서 started_at 정렬 방향을 뒤집는다.

    1·6·12월 세션(고정 id) 적재 → desc(기본)=[12,6,1]월·asc=[1,6,12]월 순서. PK 2차키는
    안정 정렬용(고유 시각이라 무영향).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    jan = datetime(2024, 1, 15, tzinfo=UTC)
    jun = datetime(2024, 6, 15, tzinfo=UTC)
    dec = datetime(2024, 12, 15, tzinfo=UTC)
    uid_a = uuid.uuid4()
    s_jan, s_jun, s_dec = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        asyncio.run(_add_all(_user(uid_a)))
        asyncio.run(
            _add_all(
                _session_row(s_jan, uid_a, jan),
                _session_row(s_jun, uid_a, jun),
                _session_row(s_dec, uid_a, dec),
            )
        )
        token_a = create_access_token(uid_a, settings=_settings())
        auth = {"Authorization": f"Bearer {token_a}"}
        with _client() as client:
            # 기본(생략) = desc = 최신순 [12,6,1]월
            ids = [s["session_id"] for s in client.get("/v1/me/sessions", headers=auth).json()]
            assert ids == [str(s_dec), str(s_jun), str(s_jan)], ids

            # order=asc = 오래된순 [1,6,12]월
            resp = client.get("/v1/me/sessions", headers=auth, params={"order": "asc"})
            ids = [s["session_id"] for s in resp.json()]
            assert ids == [str(s_jan), str(s_jun), str(s_dec)], ids
    finally:
        asyncio.run(_cleanup([uid_a]))


def test_me_sessions_ended_at_window_filter_on_live_pg() -> None:
    """slice 69: /me/sessions의 ?ended_since/until이 ended_at 시간창으로 필터.

    종료 시각 1·6월 세션 2개 + 미종료(ended_at NULL) 세션 1개 적재 → ended_since=6월은
    6월 1건(NULL·1월 제외)·ended_until=3월은 1월 1건·필터 생략은 3건. 미종료는 종료 시간창에서
    항상 제외(SQL NULL 비교).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    jan = datetime(2024, 1, 15, tzinfo=UTC)
    mar = datetime(2024, 3, 15, tzinfo=UTC)
    jun = datetime(2024, 6, 15, tzinfo=UTC)
    uid_a = uuid.uuid4()
    try:
        asyncio.run(_add_all(_user(uid_a)))
        asyncio.run(
            _add_all(
                _session_row(uuid.uuid4(), uid_a, jan, jan),  # 1월 종료
                _session_row(uuid.uuid4(), uid_a, jan, jun),  # 6월 종료
                _session_row(uuid.uuid4(), uid_a, jan, None),  # 미종료(NULL)
            )
        )
        token_a = create_access_token(uid_a, settings=_settings())
        auth = {"Authorization": f"Bearer {token_a}"}
        with _client() as client:
            # 필터 생략 → 3건(미종료 포함)
            assert len(client.get("/v1/me/sessions", headers=auth).json()) == 3

            # ended_since=6월 → 6월 종료 1건(1월 종료·미종료 제외)
            resp = client.get(
                "/v1/me/sessions", headers=auth, params={"ended_since": jun.isoformat()}
            )
            assert len(resp.json()) == 1, resp.text

            # ended_until=3월 → 1월 종료 1건(6월 종료·미종료 제외)
            resp = client.get(
                "/v1/me/sessions", headers=auth, params={"ended_until": mar.isoformat()}
            )
            assert len(resp.json()) == 1, resp.text
    finally:
        asyncio.run(_cleanup([uid_a]))


def test_submit_attempt_records_and_propagates_mastery_on_live_pg() -> None:
    """POST /v1/me/attempts — ProblemAttempt 적재 + 평가 개념 숙달 갱신(end-to-end)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    uid = uuid.uuid4()
    pid = uuid.uuid4()
    cid = uuid.uuid4()
    suffix = pid.hex[:8]

    async def _setup() -> None:
        # user(FK) + problem(FK) + concept + problem_concept(PRIMARY)
        await _add_all(_user(uid))
        await _add_all(
            Problem.from_schema(
                ProblemSchema(
                    problem_id=pid,
                    source_type=SourceType.자체생성,
                    curriculum_version=Curriculum.REVISION_2022,
                    valid_from_year=2022,
                    subject=Subject.공통,
                    unit_codes=[f"U-{suffix}"],
                )
            ),
            Concept.from_schema(
                ConceptSchema(
                    concept_id=cid,
                    code=f"C-{suffix}",
                    name_ko="채점테스트개념",
                    level=ConceptLevel.세부개념,
                )
            ),
        )
        await _add_all(
            ProblemConcept.from_schema(
                ProblemConceptSchema(problem_id=pid, concept_id=cid, role=ConceptRole.PRIMARY)
            )
        )

    async def _counts() -> tuple[int, int]:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.connect() as conn:
                pa = (
                    await conn.execute(
                        text("SELECT count(*) FROM problem_attempt WHERE user_id=:u"),
                        {"u": str(uid)},
                    )
                ).scalar()
                cm = (
                    await conn.execute(
                        text("SELECT count(*) FROM concept_mastery_history WHERE user_id=:u"),
                        {"u": str(uid)},
                    )
                ).scalar()
            return int(pa or 0), int(cm or 0)
        finally:
            await engine.dispose()

    async def _full_cleanup() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                for sql, params in (
                    ("DELETE FROM problem_attempt WHERE user_id=:u", {"u": str(uid)}),
                    (
                        "DELETE FROM concept_mastery_history WHERE user_id=:u",
                        {"u": str(uid)},
                    ),
                    (
                        "DELETE FROM problem_concept WHERE problem_id=:p",
                        {"p": str(pid)},
                    ),
                    ("DELETE FROM problem WHERE problem_id=:p", {"p": str(pid)}),
                    ("DELETE FROM concept WHERE concept_id=:c", {"c": str(cid)}),
                    # EOS-115: 이 테스트는 `POST /v1/me/attempts`를 실제로 호출하므로
                    # 학습 상태 전이가 적재된다 — user_profile보다 **먼저** 지워야 한다.
                    # 빠지면 FK로 실패하고, 이 블록이 트랜잭션이라 위 삭제까지 통째로
                    # 롤백돼 잔여 문항이 다른 테스트의 추천 후보로 끼어든다(2026-09-19 실측).
                    (
                        "DELETE FROM learning_state_transition WHERE user_id=:u",
                        {"u": str(uid)},
                    ),
                    ("DELETE FROM user_profile WHERE user_id=:u", {"u": str(uid)}),
                ):
                    await conn.execute(text(sql), params)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        with _client() as client:
            resp = client.post(
                "/v1/me/attempts",
                headers={"Authorization": f"Bearer {token}"},
                json={"problem_id": str(pid), "is_correct": True},
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert len(body["mastery_updates"]) == 1
            assert body["mastery_updates"][0]["concept_id"] == str(cid)
            assert body["mastery_updates"][0]["mastery"] == 0.69
            # 무토큰 401
            assert (
                client.post(
                    "/v1/me/attempts", json={"problem_id": str(pid), "is_correct": True}
                ).status_code
                == 401
            )
        pa_count, cm_count = asyncio.run(_counts())
        assert pa_count == 1  # ProblemAttempt 1건
        assert cm_count == 1  # ConceptMasteryHistory 1건
    finally:
        asyncio.run(_full_cleanup())


async def _cleanup_mastery(user_ids: list[uuid.UUID]) -> None:
    engine = create_async_engine(_settings().database_url)
    ids = [str(u) for u in user_ids]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM concept_mastery_history WHERE user_id = ANY(:ids)"),
                {"ids": ids},
            )
    finally:
        await engine.dispose()


async def _cleanup_concepts(concept_ids: list[uuid.UUID]) -> None:
    engine = create_async_engine(_settings().database_url)
    ids = [str(c) for c in concept_ids]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM concept WHERE concept_id = ANY(:ids)"), {"ids": ids}
            )
    finally:
        await engine.dispose()


def _mastery_row(
    uid: uuid.UUID, cid: uuid.UUID, measured_at: datetime, mastery: float
) -> ConceptMasteryHistory:
    return ConceptMasteryHistory.from_schema(
        ConceptMasteryHistorySchema(
            user_id=uid,
            concept_id=cid,
            measured_at=measured_at,
            mastery=mastery,
            sample_size=1,
        )
    )


def test_me_mastery_curve_scoped_and_concept_filter_on_live_pg() -> None:
    """GET /v1/me/mastery — A 토큰은 A의 측정만(B 차단)·?concept_id로 한 개념 곡선."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid_a, uid_b = uuid.uuid4(), uuid.uuid4()
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 2, 1, tzinfo=UTC)
    try:
        # 사용자 먼저(auth가 user_profile 존재를 요구 — 없으면 401). FK 순서·clean DB 정합.
        asyncio.run(_add_all(_user(uid_a), _user(uid_b)))
        # A: c1 2측정(t1,t2)·c2 1측정 / B: c1 1측정(스코핑 차단 확인)
        asyncio.run(
            _add_all(
                _mastery_row(uid_a, c1, t1, 0.5),
                _mastery_row(uid_a, c1, t2, 0.69),
                _mastery_row(uid_a, c2, t1, 0.3),
                _mastery_row(uid_b, c1, t1, 0.9),
            )
        )
        token_a = create_access_token(uid_a, settings=_settings())
        auth = {"Authorization": f"Bearer {token_a}"}
        with _client() as client:
            # 전체: A의 3측정만(B 제외)
            resp = client.get("/v1/me/mastery", headers=auth)
            assert resp.status_code == 200, resp.text
            assert len(resp.json()) == 3
            # ?concept_id=c1 → c1의 2측정만
            resp = client.get("/v1/me/mastery", headers=auth, params={"concept_id": str(c1)})
            rows = resp.json()
            assert len(rows) == 2
            assert {str(c1)} == {r["concept_id"] for r in rows}
            # order=asc → 오래된 측정 먼저(t1의 0.5)
            resp = client.get(
                "/v1/me/mastery",
                headers=auth,
                params={"concept_id": str(c1), "order": "asc"},
            )
            asc_rows = resp.json()
            assert float(asc_rows[0]["mastery"]) == 0.5
            # 무토큰 401
            assert client.get("/v1/me/mastery").status_code == 401
    finally:
        asyncio.run(_cleanup_mastery([uid_a, uid_b]))
        asyncio.run(_cleanup([uid_a, uid_b]))  # user_profile 정리


def test_me_mastery_current_latest_per_concept_on_live_pg() -> None:
    """GET /v1/me/mastery/current — 개념마다 최신 측정 1건만(DISTINCT ON)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    suffix = uid.hex[:8]
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 2, 1, tzinfo=UTC)
    try:
        # 사용자 먼저(auth가 user_profile 존재 요구 — clean DB서 없으면 401).
        asyncio.run(_add_all(_user(uid)))
        # 개념 메타(c1만 concept 행 존재·c2는 orphan → name null로 LEFT JOIN 검증)
        asyncio.run(
            _add_all(
                Concept.from_schema(
                    ConceptSchema(
                        concept_id=c1,
                        code=f"CAL-{suffix}",
                        name_ko="정적분",
                        level=ConceptLevel.세부개념,
                    )
                )
            )
        )
        # c1: 2측정(t1 0.5 → t2 0.69 최신)·c2: 1측정(0.3)
        asyncio.run(
            _add_all(
                _mastery_row(uid, c1, t1, 0.5),
                _mastery_row(uid, c1, t2, 0.69),
                _mastery_row(uid, c2, t1, 0.3),
            )
        )
        token = create_access_token(uid, settings=_settings())
        with _client() as client:
            resp = client.get(
                "/v1/me/mastery/current", headers={"Authorization": f"Bearer {token}"}
            )
            assert resp.status_code == 200, resp.text
            rows = resp.json()
            # 3측정이지만 개념별 최신 → 2행
            assert len(rows) == 2
            by_concept = {r["concept_id"]: r for r in rows}
            assert float(by_concept[str(c1)]["mastery"]) == 0.69  # t2(최신)
            assert by_concept[str(c1)]["concept_name"] == "정적분"  # 조인된 개념명
            assert by_concept[str(c1)]["concept_code"] == f"CAL-{suffix}"
            assert float(by_concept[str(c2)]["mastery"]) == 0.3
            assert by_concept[str(c2)]["concept_name"] is None  # orphan(LEFT JOIN)
            assert client.get("/v1/me/mastery/current").status_code == 401  # 무토큰
    finally:
        asyncio.run(_cleanup_mastery([uid]))
        asyncio.run(_cleanup_concepts([c1]))
        asyncio.run(_cleanup([uid]))  # user_profile 정리


def test_me_ability_estimates_theta_from_attempts_on_live_pg() -> None:
    """GET /v1/me/ability — 채점 풀이(난이도 join)에서 IRT θ 추정(end-to-end)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid = uuid.uuid4()
    suffix = pid.hex[:8]

    async def _setup() -> None:
        await _add_all(_user(uid))
        await _add_all(
            Problem.from_schema(
                ProblemSchema(
                    problem_id=pid,
                    source_type=SourceType.자체생성,
                    curriculum_version=Curriculum.REVISION_2022,
                    valid_from_year=2022,
                    subject=Subject.공통,
                    unit_codes=[f"U-{suffix}"],
                    difficulty_overall=5.0,  # 어려운 문항
                )
            )
        )
        await _add_all(
            ProblemAttempt(attempt_id=uuid.uuid4(), user_id=uid, problem_id=pid, is_correct=True)
        )

    async def _cleanup_all() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                for sql in (
                    "DELETE FROM problem_attempt WHERE user_id=:u",
                    "DELETE FROM problem WHERE problem_id=:p",
                    "DELETE FROM user_profile WHERE user_id=:u",
                ):
                    await conn.execute(text(sql), {"u": str(uid), "p": str(pid)})
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        with _client() as client:
            resp = client.get("/v1/me/ability", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["response_count"] == 1
            assert body["theta"] == 4.0  # 채점 1건 전부 정답 → 능력 상한
            # slice 14: 측정 정밀도 — 응답 있으니 SE·CI 노출(유한)
            assert body["standard_error"] is not None
            assert body["standard_error"] > 0.0
            lo, hi = body["confidence_interval"]
            assert lo < body["theta"] < hi
            assert client.get("/v1/me/ability").status_code == 401  # 무토큰
            # slice 28: θ 성장 곡선 — 채점 1건 → 시점 1개(response_count 1·θ 상한)
            hist = client.get(
                "/v1/me/ability/history", headers={"Authorization": f"Bearer {token}"}
            )
            assert hist.status_code == 200, hist.text
            hpoints = hist.json()
            assert len(hpoints) == 1
            assert hpoints[0]["response_count"] == 1
            assert hpoints[0]["theta"] == 4.0
            assert hpoints[0]["as_of"]  # created_at 노출
            assert client.get("/v1/me/ability/history").status_code == 401
    finally:
        asyncio.run(_cleanup_all())


def test_me_next_problem_repeats_and_exclusion_toggles_on_live_pg() -> None:
    """REC-06 — ① 연속 호출 시 같은 문항 고정 ② attempt 제외 변별력(양방향) ③ 동률 정렬 결정론.

    **왜 실 PG여야 하는가**: hermetic FakeSession은 `WHERE`·`ORDER BY`를 평가하지 않아
    "`NOT IN`이 실제로 후보를 지우는가"와 "동률 구간이 `problem_id`로 고정되는가"를 볼 수 없다.
    이 테스트만이 그 두 축을 실제 SQL 실행으로 확인한다.

    **DB에 다른 문항이 있어도 흔들리지 않게** 설계했다 — 세 후보에 `irt_difficulty_b=0.0`(θ=0
    에서 거리 0 = 최소)과 **가장 작은 UUID**(`uuid.UUID(int=1..3)`)를 준다. 2차 정렬 키가
    `problem_id` 오름차순이므로 거리 0 동률 구간의 맨 앞을 이 셋이 차지한다.

    **θ를 고정한 채 제외 축만 흔든다**: ②에서 attempt를 *정답 1 + 오답 1*(둘 다 b=0)로 넣어
    MLE θ가 정확히 0.0으로 유지되게 했다. 반환 문항이 바뀌는 원인이 "θ가 움직여서"가 아니라
    "제외가 걸려서"임을 응답의 `theta` 값으로 함께 확인한다(교란 요인 차단).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    # 가장 작은 UUID 3개 — 거리 0 동률 구간에서 2차 키(problem_id asc)가 이 순서를 고정한다.
    pid_1, pid_2, pid_3 = (uuid.UUID(int=n) for n in (1, 2, 3))
    suffix = uid.hex[:8]

    def _tie_problem(pid: uuid.UUID) -> Problem:
        return Problem.from_schema(
            ProblemSchema(
                problem_id=pid,
                source_type=SourceType.자체생성,
                review_status=ReviewStatus.approved,
                curriculum_version=Curriculum.REVISION_2022,
                valid_from_year=2022,
                subject=Subject.공통,
                unit_codes=[f"U-{suffix}"],
                difficulty_overall=3.0,
                irt_difficulty_b=0.0,  # θ=0에서 거리 0(최소) — 셋 다 정보량 동률
            )
        )

    async def _purge_problems() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                for pid in (pid_1, pid_2, pid_3):
                    await conn.execute(
                        text("DELETE FROM problem_attempt WHERE problem_id=:p"), {"p": str(pid)}
                    )
                    await conn.execute(
                        text("DELETE FROM problem WHERE problem_id=:p"), {"p": str(pid)}
                    )
        finally:
            await engine.dispose()

    async def _set_attempts(rows: list[ProblemAttempt]) -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM problem_attempt WHERE user_id=:u"), {"u": str(uid)}
                )
        finally:
            await engine.dispose()
        if rows:
            await _add_all(*rows)

    def _attempt(pid: uuid.UUID, *, correct: bool) -> ProblemAttempt:
        return ProblemAttempt(
            attempt_id=uuid.uuid4(), user_id=uid, problem_id=pid, is_correct=correct
        )

    try:
        asyncio.run(_purge_problems())  # 이전 실행 잔여 제거(고정 UUID라 선제 정리)
        asyncio.run(_add_all(_user(uid)))
        asyncio.run(_add_all(_tie_problem(pid_1), _tie_problem(pid_2), _tie_problem(pid_3)))
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}

        with _client() as client:
            # ① 진도 폭 — 같은 조건 5회 연속 호출이 전부 같은 문항(REC-06이 관측한 그 상태).
            bodies = [client.get("/v1/me/next-problem", headers=auth).json() for _ in range(5)]
            returned = {b["problem_id"] for b in bodies}
            assert len(returned) == 1, f"연속 호출이 서로 다른 문항을 냈다: {returned}"
            baseline = bodies[0]["problem_id"]
            assert bodies[0]["theta"] == 0.0
            # ③ 동률 정렬 결정론 — 거리 0 동률 구간에서 problem_id 최소가 뽑힌다(2차 키 효과).
            assert baseline == str(pid_1)

            # ② 변별력(정) — attempt 정답1·오답1 주입(θ는 0.0 유지) → pid_1이 후보에서 빠진다.
            asyncio.run(
                _set_attempts([_attempt(pid_1, correct=True), _attempt(pid_2, correct=False)])
            )
            after = client.get("/v1/me/next-problem", headers=auth).json()
            assert after["theta"] == 0.0, "θ가 움직였다면 변화 원인을 제외 축으로 귀속할 수 없다"
            assert after["problem_id"] != baseline
            assert after["problem_id"] == str(pid_3)  # 1·2 제외 → 남은 동률 최소 id

            # ② 변별력(역) — attempt를 되돌리면 원래 문항으로 복귀(성공/실패가 같은 값이 아님).
            asyncio.run(_set_attempts([]))
            restored = client.get("/v1/me/next-problem", headers=auth).json()
            assert restored["problem_id"] == baseline
    finally:
        asyncio.run(_purge_problems())
        asyncio.run(_cleanup([uid]))


def test_me_next_problem_recommends_unattempted_on_live_pg() -> None:
    """GET /v1/me/next-problem — θ 근방·미응답 문항을 NOT IN 제외 후 정보량 최대로 추천."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid_done = uuid.uuid4()  # 이미 푼(정답·난이도 5) → θ 상한 + NOT IN 제외 대상
    pid_mid = uuid.uuid4()  # 미응답 난이도 3
    pid_hard = uuid.uuid4()  # 미응답 난이도 5 → θ=4에서 정보량 최대
    suffix = pid_done.hex[:8]

    def _problem(pid: uuid.UUID, difficulty: float) -> Problem:
        return Problem.from_schema(
            ProblemSchema(
                problem_id=pid,
                source_type=SourceType.자체생성,
                # PB-03 — 기본 CAT SQL도 review_status=approved만 후보(축②)라 필요.
                review_status=ReviewStatus.approved,
                curriculum_version=Curriculum.REVISION_2022,
                valid_from_year=2022,
                subject=Subject.공통,
                unit_codes=[f"U-{suffix}"],
                difficulty_overall=difficulty,
            )
        )

    async def _setup() -> None:
        await _add_all(_user(uid))
        await _add_all(_problem(pid_done, 5.0))
        await _add_all(_problem(pid_mid, 3.0))
        await _add_all(_problem(pid_hard, 5.0))
        await _add_all(
            ProblemAttempt(
                attempt_id=uuid.uuid4(),
                user_id=uid,
                problem_id=pid_done,
                is_correct=True,
            )
        )

    async def _cleanup_all() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM problem_attempt WHERE user_id=:u"),
                    {"u": str(uid)},
                )
                for pid in (pid_done, pid_mid, pid_hard):
                    await conn.execute(
                        text("DELETE FROM problem WHERE problem_id=:p"),
                        {"p": str(pid)},
                    )
                await conn.execute(
                    text("DELETE FROM user_profile WHERE user_id=:u"), {"u": str(uid)}
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        with _client() as client:
            resp = client.get("/v1/me/next-problem", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["theta"] == 4.0  # 정답 1건 → 능력 상한
            # 이미 푼 난이도-5 문항(pid_done)은 NOT IN 제외 → 미응답 난이도-5(pid_hard) 추천
            assert body["problem_id"] == str(pid_hard)
            assert body["problem_id"] != str(pid_done)
            assert body["difficulty"] == 5.0
            # slice 15: 응답 1건뿐 → SE 노출(유한)·측정 불충분
            assert body["standard_error"] is not None
            assert body["measurement_sufficient"] is False
            assert client.get("/v1/me/next-problem").status_code == 401  # 무토큰
    finally:
        asyncio.run(_cleanup_all())


def test_me_next_problem_suneung_persona_fit_only_candidate_on_live_pg() -> None:
    """S3-17: 기출유형·시그니처가 없어도 persona_fit만으로 θ 근방 SQL 풀에 잡히는지 실 PG로 증명.

    SQL 사전필터는 hermetic 테스트(FakeSession)로는 검증되지 않는다(WHERE 절이 실행되지 않고
    통째로 무시되므로) — 실 PG에서 실제로 WHERE가 평가돼야 이 조건의 존재 여부가 드러난다.
    S3-10 이전엔 persona_fit이 전부 {}라 이 문항은 사전필터에서 원천 배제됐다(무손실이었던
    이유 — 어차피 아무것도 적격이 아니었으므로). 지금은 persona_fit[A]=0.6(>=0.5 임계)만으로
    사전필터를 통과해야 하고, 통과한 뒤 `is_suneung_eligible`(진실 게이트)도 persona_fit 경로로
    적격 판정해 실제로 추천돼야 한다.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid = uuid.uuid4()
    suffix = pid.hex[:8]

    def _persona_fit_only_problem() -> Problem:
        return Problem.from_schema(
            ProblemSchema(
                problem_id=pid,
                source_type=SourceType.자체생성,
                review_status=ReviewStatus.approved,
                curriculum_version=Curriculum.REVISION_2022,
                valid_from_year=2022,
                subject=Subject.공통,
                unit_codes=[f"U-{suffix}"],
                difficulty_overall=3.0,
                # 기출유형·시그니처 둘 다 없음 — persona_fit 경로만으로 적격이어야 한다.
                exam_type=None,
                signature_patterns=[],
                persona_fit={Persona.A_일반고고3: 0.6},
            )
        )

    async def _setup() -> None:
        await _add_all(_user(uid))
        await _add_all(_persona_fit_only_problem())

    async def _cleanup() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM problem WHERE problem_id=:p"), {"p": str(pid)})
                await conn.execute(
                    text("DELETE FROM user_profile WHERE user_id=:u"), {"u": str(uid)}
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        with _client() as client:
            resp = client.get(
                "/v1/me/next-problem?mode=suneung",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            # 사전필터가 여전히 좁으면 SQL이 이 행 자체를 안 뽑아 problem_id=null이 된다.
            assert body["problem_id"] == str(pid), (
                "persona_fit-only 문항이 θ 근방 SQL 풀에서 빠졌다 — "
                "SUNEUNG_DEFAULT_MIN_FIT 조건이 사전필터에서 누락됐을 수 있다."
            )
    finally:
        asyncio.run(_cleanup())


def test_me_next_problem_suneung_persona_fit_below_threshold_excluded_on_live_pg() -> None:
    """**변별력** — persona_fit이 임계 미달(0.3<0.5)이면 여전히 사전필터에서 빠져야 한다.

    위 테스트가 "무조건 통과"라는 고장이 아님을 증명한다 — 임계값 비교가 실제로 SQL에서
    작동해야 한다(그냥 컬럼 존재만 보고 항상 True가 되는 결함을 잡는다).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid = uuid.uuid4()
    suffix = pid.hex[:8]

    def _low_fit_problem() -> Problem:
        return Problem.from_schema(
            ProblemSchema(
                problem_id=pid,
                source_type=SourceType.자체생성,
                review_status=ReviewStatus.approved,
                curriculum_version=Curriculum.REVISION_2022,
                valid_from_year=2022,
                subject=Subject.공통,
                unit_codes=[f"U-{suffix}"],
                difficulty_overall=3.0,
                exam_type=None,
                signature_patterns=[],
                persona_fit={Persona.A_일반고고3: 0.3},
            )
        )

    async def _setup() -> None:
        await _add_all(_user(uid))
        await _add_all(_low_fit_problem())

    async def _cleanup() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM problem WHERE problem_id=:p"), {"p": str(pid)})
                await conn.execute(
                    text("DELETE FROM user_profile WHERE user_id=:u"), {"u": str(uid)}
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        with _client() as client:
            resp = client.get(
                "/v1/me/next-problem?mode=suneung",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["problem_id"] is None
    finally:
        asyncio.run(_cleanup())


def test_me_next_problem_weak_concept_priority_on_live_pg() -> None:
    """GET /v1/me/next-problem?prioritize_weak_concepts=true — 동일 난이도 두 문항 중
    약점 개념(저숙달) 문항을 BKT 숙달 스냅샷 조인으로 우선 추천(BKT+IRT 융합·end-to-end)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid_strong = uuid.uuid4()  # 강점 개념 문항(난이도3)
    pid_weak = uuid.uuid4()  # 약점 개념 문항(난이도3·저숙달)
    c_strong, c_weak = uuid.uuid4(), uuid.uuid4()
    suffix = uid.hex[:8]
    t1 = datetime(2026, 1, 1, tzinfo=UTC)

    def _problem(pid: uuid.UUID) -> Problem:
        return Problem.from_schema(
            ProblemSchema(
                problem_id=pid,
                source_type=SourceType.자체생성,
                # PB-03 — 기본 CAT SQL도 review_status=approved만 후보(축②)라 필요.
                review_status=ReviewStatus.approved,
                curriculum_version=Curriculum.REVISION_2022,
                valid_from_year=2022,
                subject=Subject.공통,
                unit_codes=[f"U-{suffix}"],
                difficulty_overall=3.0,
            )
        )

    def _concept(cid: uuid.UUID, code: str) -> Concept:
        return Concept.from_schema(
            ConceptSchema(concept_id=cid, code=code, name_ko=code, level=ConceptLevel.세부개념)
        )

    async def _setup() -> None:
        await _add_all(_user(uid))
        await _add_all(_concept(c_strong, f"S-{suffix}"), _concept(c_weak, f"W-{suffix}"))
        await _add_all(_problem(pid_strong), _problem(pid_weak))
        await _add_all(
            ProblemConcept.from_schema(
                ProblemConceptSchema(
                    problem_id=pid_strong, concept_id=c_strong, role=ConceptRole.PRIMARY
                )
            ),
            ProblemConcept.from_schema(
                ProblemConceptSchema(
                    problem_id=pid_weak, concept_id=c_weak, role=ConceptRole.PRIMARY
                )
            ),
        )
        # 숙달: 강점 1.0 · 약점 0.0
        await _add_all(
            _mastery_row(uid, c_strong, t1, 1.0),
            _mastery_row(uid, c_weak, t1, 0.0),
        )

    async def _cleanup_all() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                for sql, params in (
                    (
                        "DELETE FROM concept_mastery_history WHERE user_id=:u",
                        {"u": str(uid)},
                    ),
                    (
                        "DELETE FROM problem_concept WHERE problem_id = ANY(:p)",
                        {"p": [str(pid_strong), str(pid_weak)]},
                    ),
                    (
                        "DELETE FROM problem WHERE problem_id = ANY(:p)",
                        {"p": [str(pid_strong), str(pid_weak)]},
                    ),
                    (
                        "DELETE FROM concept WHERE concept_id = ANY(:c)",
                        {"c": [str(c_strong), str(c_weak)]},
                    ),
                    ("DELETE FROM user_profile WHERE user_id=:u", {"u": str(uid)}),
                ):
                    await conn.execute(text(sql), params)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        with _client() as client:
            auth = {"Authorization": f"Bearer {token}"}
            # 약점 우선 → 저숙달 개념(pid_weak) 추천(동일 난이도·가중으로 역전)
            resp = client.get("/v1/me/next-problem?prioritize_weak_concepts=true", headers=auth)
            assert resp.status_code == 200, resp.text
            assert resp.json()["problem_id"] == str(pid_weak)
    finally:
        asyncio.run(_cleanup_all())


def test_me_next_problem_sibling_exclude_on_live_pg() -> None:
    """GET /v1/me/next-problem?sibling_filter=exclude — problem_relation(변형·유사) 첫 소비처.

    직전 오답 문항의 형제(problem_relation 양방향)가 유일한 미응답 후보면, 배제 시 후보 풀이
    비어 problem_id=null(미필터 baseline은 그 형제를 추천 — 배선이 살아있음을 대조 확인).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid_wrong = uuid.uuid4()  # 직전 오답 문항
    pid_sibling = uuid.uuid4()  # pid_wrong의 "변형" 형제 — 유일한 미응답 후보
    suffix = uid.hex[:8]

    def _problem(pid: uuid.UUID) -> Problem:
        return Problem.from_schema(
            ProblemSchema(
                problem_id=pid,
                source_type=SourceType.자체생성,
                # PB-03 — 기본 CAT SQL도 review_status=approved만 후보(축②)라 필요.
                review_status=ReviewStatus.approved,
                curriculum_version=Curriculum.REVISION_2022,
                valid_from_year=2022,
                subject=Subject.공통,
                unit_codes=[f"U-{suffix}"],
                difficulty_overall=3.0,
            )
        )

    async def _setup() -> None:
        await _add_all(_user(uid))
        await _add_all(_problem(pid_wrong), _problem(pid_sibling))
        await _add_all(
            ProblemAttempt(
                attempt_id=uuid.uuid4(),
                user_id=uid,
                problem_id=pid_wrong,
                is_correct=False,
            )
        )
        await _add_all(
            ProblemRelation.from_schema(
                ProblemRelationSchema(
                    parent_problem_id=pid_wrong,
                    related_problem_id=pid_sibling,
                    relation_type=RelationType.변형,
                    similarity_score=0.95,
                )
            )
        )

    async def _cleanup_all() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "DELETE FROM problem_relation WHERE parent_problem_id=:p "
                        "OR related_problem_id=:p"
                    ),
                    {"p": str(pid_wrong)},
                )
                await conn.execute(
                    text("DELETE FROM problem_attempt WHERE user_id=:u"), {"u": str(uid)}
                )
                for pid in (pid_wrong, pid_sibling):
                    await conn.execute(
                        text("DELETE FROM problem WHERE problem_id=:p"), {"p": str(pid)}
                    )
                await conn.execute(
                    text("DELETE FROM user_profile WHERE user_id=:u"), {"u": str(uid)}
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            # 미필터 baseline — 유일한 미응답 후보(형제)가 추천됨(배선 자체는 정상 확인).
            resp = client.get("/v1/me/next-problem", headers=auth)
            assert resp.status_code == 200, resp.text
            assert resp.json()["problem_id"] == str(pid_sibling)

            # exclude — 그 형제가 후보에서 빠져 풀이 비어 null.
            resp = client.get("/v1/me/next-problem?sibling_filter=exclude", headers=auth)
            assert resp.status_code == 200, resp.text
            assert resp.json()["problem_id"] is None
    finally:
        asyncio.run(_cleanup_all())


def test_me_next_problem_sibling_include_on_live_pg() -> None:
    """GET /v1/me/next-problem?sibling_filter=include — 형제 후보를 정보량 가중으로 우대.

    직전 오답 문항의 형제(pid_sibling)와 무관 후보(pid_other)가 난이도(=정보량) 동일이면
    가중 없이는 동률이나, include는 형제에 1+BOOST(2.0)배를 곱해 결정론으로 형제를 선택한다.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid_wrong = uuid.uuid4()
    pid_sibling = uuid.uuid4()  # pid_wrong의 "유사" 형제
    pid_other = uuid.uuid4()  # 무관 후보(동일 난이도)
    suffix = uid.hex[:8]

    def _problem(pid: uuid.UUID) -> Problem:
        return Problem.from_schema(
            ProblemSchema(
                problem_id=pid,
                source_type=SourceType.자체생성,
                review_status=ReviewStatus.approved,
                curriculum_version=Curriculum.REVISION_2022,
                valid_from_year=2022,
                subject=Subject.공통,
                unit_codes=[f"U-{suffix}"],
                difficulty_overall=3.0,
            )
        )

    async def _setup() -> None:
        await _add_all(_user(uid))
        await _add_all(_problem(pid_wrong), _problem(pid_sibling), _problem(pid_other))
        await _add_all(
            ProblemAttempt(
                attempt_id=uuid.uuid4(),
                user_id=uid,
                problem_id=pid_wrong,
                is_correct=False,
            )
        )
        await _add_all(
            ProblemRelation.from_schema(
                ProblemRelationSchema(
                    parent_problem_id=pid_wrong,
                    related_problem_id=pid_sibling,
                    relation_type=RelationType.유사,
                    similarity_score=0.6,
                )
            )
        )

    async def _cleanup_all() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "DELETE FROM problem_relation WHERE parent_problem_id=:p "
                        "OR related_problem_id=:p"
                    ),
                    {"p": str(pid_wrong)},
                )
                await conn.execute(
                    text("DELETE FROM problem_attempt WHERE user_id=:u"), {"u": str(uid)}
                )
                for pid in (pid_wrong, pid_sibling, pid_other):
                    await conn.execute(
                        text("DELETE FROM problem WHERE problem_id=:p"), {"p": str(pid)}
                    )
                await conn.execute(
                    text("DELETE FROM user_profile WHERE user_id=:u"), {"u": str(uid)}
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            resp = client.get("/v1/me/next-problem?sibling_filter=include", headers=auth)
            assert resp.status_code == 200, resp.text
            assert resp.json()["problem_id"] == str(pid_sibling)
    finally:
        asyncio.run(_cleanup_all())


def test_me_ability_by_concept_on_live_pg() -> None:
    """GET /v1/me/ability/by-concept
    — 채점 풀이를 개념별로 묶어 θ 분리 추정·약점 먼저(end-to-end)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    p_strong, p_weak = uuid.uuid4(), uuid.uuid4()
    c_strong, c_weak = uuid.uuid4(), uuid.uuid4()
    suffix = uid.hex[:8]

    def _problem(pid: uuid.UUID) -> Problem:
        return Problem.from_schema(
            ProblemSchema(
                problem_id=pid,
                source_type=SourceType.자체생성,
                review_status=ReviewStatus.approved,
                curriculum_version=Curriculum.REVISION_2022,
                valid_from_year=2022,
                subject=Subject.공통,
                unit_codes=[f"U-{suffix}"],
                difficulty_overall=3.0,
            )
        )

    def _concept(cid: uuid.UUID, code: str, name: str) -> Concept:
        return Concept.from_schema(
            ConceptSchema(concept_id=cid, code=code, name_ko=name, level=ConceptLevel.세부개념)
        )

    async def _setup() -> None:
        await _add_all(_user(uid))
        await _add_all(
            _concept(c_strong, f"S-{suffix}", "강점개념"),
            _concept(c_weak, f"W-{suffix}", "약점개념"),
        )
        await _add_all(_problem(p_strong), _problem(p_weak))
        await _add_all(
            ProblemConcept.from_schema(
                ProblemConceptSchema(
                    problem_id=p_strong, concept_id=c_strong, role=ConceptRole.PRIMARY
                )
            ),
            ProblemConcept.from_schema(
                ProblemConceptSchema(problem_id=p_weak, concept_id=c_weak, role=ConceptRole.PRIMARY)
            ),
        )
        # 강점 문항 정답(θ↑)·약점 문항 오답(θ↓)
        await _add_all(
            ProblemAttempt(
                attempt_id=uuid.uuid4(),
                user_id=uid,
                problem_id=p_strong,
                is_correct=True,
            ),
            ProblemAttempt(
                attempt_id=uuid.uuid4(),
                user_id=uid,
                problem_id=p_weak,
                is_correct=False,
            ),
        )

    async def _cleanup_all() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                for sql, params in (
                    ("DELETE FROM problem_attempt WHERE user_id=:u", {"u": str(uid)}),
                    (
                        "DELETE FROM problem_concept WHERE problem_id = ANY(:p)",
                        {"p": [str(p_strong), str(p_weak)]},
                    ),
                    (
                        "DELETE FROM problem WHERE problem_id = ANY(:p)",
                        {"p": [str(p_strong), str(p_weak)]},
                    ),
                    (
                        "DELETE FROM concept WHERE concept_id = ANY(:c)",
                        {"c": [str(c_strong), str(c_weak)]},
                    ),
                    ("DELETE FROM user_profile WHERE user_id=:u", {"u": str(uid)}),
                ):
                    await conn.execute(text(sql), params)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        with _client() as client:
            resp = client.get(
                "/v1/me/ability/by-concept",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, resp.text
            rows = resp.json()
            assert len(rows) == 2
            # 약점(오답·θ=-4) 개념 먼저, 강점(정답·θ=4) 나중
            assert rows[0]["concept_id"] == str(c_weak)
            assert rows[0]["theta"] == -4.0
            assert rows[0]["concept_name"] == "약점개념"
            assert rows[1]["concept_id"] == str(c_strong)
            assert rows[1]["theta"] == 4.0
            assert client.get("/v1/me/ability/by-concept").status_code == 401
    finally:
        asyncio.run(_cleanup_all())


def test_me_concept_diagnosis_cross_check_on_live_pg() -> None:
    """GET /v1/me/diagnosis/concepts
    — BKT 숙달↔IRT θ 불일치(irt_higher·bkt_higher) 교차검증(end-to-end)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    # c1: BKT 낮음(0.1)인데 정답(θ↑) → irt_higher / c2: BKT 높음(0.9)인데 오답(θ↓) → bkt_higher
    p1, p2 = uuid.uuid4(), uuid.uuid4()
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    suffix = uid.hex[:8]
    t1 = datetime(2026, 1, 1, tzinfo=UTC)

    def _problem(pid: uuid.UUID) -> Problem:
        return Problem.from_schema(
            ProblemSchema(
                problem_id=pid,
                source_type=SourceType.자체생성,
                review_status=ReviewStatus.approved,
                curriculum_version=Curriculum.REVISION_2022,
                valid_from_year=2022,
                subject=Subject.공통,
                unit_codes=[f"U-{suffix}"],
                difficulty_overall=3.0,
            )
        )

    def _concept(cid: uuid.UUID, code: str, name: str) -> Concept:
        return Concept.from_schema(
            ConceptSchema(concept_id=cid, code=code, name_ko=name, level=ConceptLevel.세부개념)
        )

    async def _setup() -> None:
        await _add_all(_user(uid))
        await _add_all(_concept(c1, f"A-{suffix}", "개념1"), _concept(c2, f"B-{suffix}", "개념2"))
        await _add_all(_problem(p1), _problem(p2))
        await _add_all(
            ProblemConcept.from_schema(
                ProblemConceptSchema(problem_id=p1, concept_id=c1, role=ConceptRole.PRIMARY)
            ),
            ProblemConcept.from_schema(
                ProblemConceptSchema(problem_id=p2, concept_id=c2, role=ConceptRole.PRIMARY)
            ),
        )
        await _add_all(
            ProblemAttempt(attempt_id=uuid.uuid4(), user_id=uid, problem_id=p1, is_correct=True),
            ProblemAttempt(attempt_id=uuid.uuid4(), user_id=uid, problem_id=p2, is_correct=False),
        )
        # BKT: c1 낮음·c2 높음(IRT와 반대 → 불일치 신호)
        await _add_all(_mastery_row(uid, c1, t1, 0.1), _mastery_row(uid, c2, t1, 0.9))

    async def _cleanup_all() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                for sql, params in (
                    ("DELETE FROM problem_attempt WHERE user_id=:u", {"u": str(uid)}),
                    (
                        "DELETE FROM concept_mastery_history WHERE user_id=:u",
                        {"u": str(uid)},
                    ),
                    (
                        "DELETE FROM problem_concept WHERE problem_id = ANY(:p)",
                        {"p": [str(p1), str(p2)]},
                    ),
                    (
                        "DELETE FROM problem WHERE problem_id = ANY(:p)",
                        {"p": [str(p1), str(p2)]},
                    ),
                    (
                        "DELETE FROM concept WHERE concept_id = ANY(:c)",
                        {"c": [str(c1), str(c2)]},
                    ),
                    ("DELETE FROM user_profile WHERE user_id=:u", {"u": str(uid)}),
                ):
                    await conn.execute(text(sql), params)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        with _client() as client:
            resp = client.get(
                "/v1/me/diagnosis/concepts",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, resp.text
            by_concept = {r["concept_id"]: r for r in resp.json()}
            assert by_concept[str(c1)]["agreement"] == "irt_higher"  # 정답인데 BKT 낮음
            assert by_concept[str(c2)]["agreement"] == "bkt_higher"  # 오답인데 BKT 높음
            assert by_concept[str(c1)]["bkt_mastery"] == 0.1
            assert by_concept[str(c2)]["irt_theta"] == -4.0
            # slice 21: L4 코칭 처방 결선(L2→L4→L5 풀 스택)
            assert by_concept[str(c1)]["coaching"]["focus"] == "consolidate"
            assert by_concept[str(c2)]["coaching"]["focus"] == "retrieval"
            assert client.get("/v1/me/diagnosis/concepts").status_code == 401
    finally:
        asyncio.run(_cleanup_all())


def test_me_ability_snapshot_capture_and_list_on_live_pg() -> None:
    """POST /v1/me/ability/snapshots → 적재 → GET 시계열 조회(end-to-end·실 PG)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid = uuid.uuid4()
    suffix = pid.hex[:8]

    async def _setup() -> None:
        await _add_all(_user(uid))
        await _add_all(
            Problem.from_schema(
                ProblemSchema(
                    problem_id=pid,
                    source_type=SourceType.자체생성,
                    curriculum_version=Curriculum.REVISION_2022,
                    valid_from_year=2022,
                    subject=Subject.공통,
                    unit_codes=[f"U-{suffix}"],
                    difficulty_overall=5.0,
                )
            )
        )
        await _add_all(
            ProblemAttempt(attempt_id=uuid.uuid4(), user_id=uid, problem_id=pid, is_correct=True)
        )

    async def _cleanup_all() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                for sql in (
                    "DELETE FROM ability_snapshot WHERE user_id=:u",
                    "DELETE FROM problem_attempt WHERE user_id=:u",
                    "DELETE FROM problem WHERE problem_id=:p",
                    "DELETE FROM user_profile WHERE user_id=:u",
                ):
                    await conn.execute(text(sql), {"u": str(uid), "p": str(pid)})
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            # 캡처 — 정답 1건 → θ 상한 4.0 적재
            cap = client.post("/v1/me/ability/snapshots", headers=auth)
            assert cap.status_code == 201, cap.text
            assert cap.json()["theta"] == 4.0
            assert cap.json()["response_count"] == 1
            # 조회 — 적재된 1행
            lst = client.get("/v1/me/ability/snapshots", headers=auth)
            assert lst.status_code == 200, lst.text
            snaps = lst.json()
            assert len(snaps) == 1
            assert snaps[0]["theta"] == 4.0
            assert snaps[0]["measured_at"]
            assert client.post("/v1/me/ability/snapshots").status_code == 401
            assert client.get("/v1/me/ability/snapshots").status_code == 401
    finally:
        asyncio.run(_cleanup_all())


def test_me_ability_snapshot_per_concept_on_live_pg() -> None:
    """POST ?include_concepts=true → 전과목+개념별 적재 → GET ?concept_id 분리 조회(실 PG)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid = uuid.uuid4()
    cid = uuid.uuid4()
    suffix = pid.hex[:8]

    async def _setup() -> None:
        await _add_all(_user(uid))
        await _add_all(
            Concept.from_schema(
                ConceptSchema(
                    concept_id=cid,
                    code=f"S-{suffix}",
                    name_ko="스냅개념",
                    level=ConceptLevel.세부개념,
                )
            )
        )
        await _add_all(
            Problem.from_schema(
                ProblemSchema(
                    problem_id=pid,
                    source_type=SourceType.자체생성,
                    curriculum_version=Curriculum.REVISION_2022,
                    valid_from_year=2022,
                    subject=Subject.공통,
                    unit_codes=[f"U-{suffix}"],
                    difficulty_overall=5.0,
                )
            )
        )
        await _add_all(
            ProblemConcept.from_schema(
                ProblemConceptSchema(problem_id=pid, concept_id=cid, role=ConceptRole.PRIMARY)
            )
        )
        await _add_all(
            ProblemAttempt(attempt_id=uuid.uuid4(), user_id=uid, problem_id=pid, is_correct=True)
        )

    async def _cleanup_all() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                for sql, params in (
                    ("DELETE FROM ability_snapshot WHERE user_id=:u", {"u": str(uid)}),
                    ("DELETE FROM problem_attempt WHERE user_id=:u", {"u": str(uid)}),
                    (
                        "DELETE FROM problem_concept WHERE problem_id=:p",
                        {"p": str(pid)},
                    ),
                    ("DELETE FROM problem WHERE problem_id=:p", {"p": str(pid)}),
                    ("DELETE FROM concept WHERE concept_id=:c", {"c": str(cid)}),
                    ("DELETE FROM user_profile WHERE user_id=:u", {"u": str(uid)}),
                ):
                    await conn.execute(text(sql), params)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            cap = client.post("/v1/me/ability/snapshots?include_concepts=true", headers=auth)
            assert cap.status_code == 201, cap.text
            assert cap.json()["concept_id"] is None  # 응답=전과목
            # 기본(concept_id 생략) → 전과목 곡선만(1행·concept_id null)
            glob = client.get("/v1/me/ability/snapshots", headers=auth).json()
            assert len(glob) == 1
            assert glob[0]["concept_id"] is None
            assert glob[0]["theta"] == 4.0
            # ?concept_id=cid → 그 개념 곡선(1행·concept_id=cid·θ4)
            byc = client.get(f"/v1/me/ability/snapshots?concept_id={cid}", headers=auth).json()
            assert len(byc) == 1
            assert byc[0]["concept_id"] == str(cid)
            assert byc[0]["theta"] == 4.0
    finally:
        asyncio.run(_cleanup_all())


def test_me_session_end_auto_captures_snapshot_on_live_pg() -> None:
    """slice 34: PATCH /sessions/{id}/end → θ 스냅샷 자동 적재·멱등 재호출은 미중복(실 PG)."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid = uuid.uuid4()
    sid = uuid.uuid4()
    suffix = pid.hex[:8]

    async def _setup() -> None:
        await _add_all(_user(uid))
        await _add_all(
            Problem.from_schema(
                ProblemSchema(
                    problem_id=pid,
                    source_type=SourceType.자체생성,
                    curriculum_version=Curriculum.REVISION_2022,
                    valid_from_year=2022,
                    subject=Subject.공통,
                    unit_codes=[f"U-{suffix}"],
                    difficulty_overall=5.0,
                )
            )
        )
        await _add_all(
            ProblemAttempt(attempt_id=uuid.uuid4(), user_id=uid, problem_id=pid, is_correct=True)
        )
        await _add_all(_session_row(sid, uid))  # 미종료 세션

    async def _cleanup_all() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                for sql in (
                    "DELETE FROM ability_snapshot WHERE user_id=:u",
                    "DELETE FROM problem_attempt WHERE user_id=:u",
                    "DELETE FROM learning_session WHERE user_id=:u",
                    "DELETE FROM problem WHERE problem_id=:p",
                    "DELETE FROM user_profile WHERE user_id=:u",
                ):
                    await conn.execute(text(sql), {"u": str(uid), "p": str(pid)})
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            # 처음 종료 → θ 스냅샷 자동 적재
            r1 = client.patch(f"/v1/me/sessions/{sid}/end", headers=auth)
            assert r1.status_code == 200, r1.text
            snaps = client.get("/v1/me/ability/snapshots", headers=auth).json()
            assert len(snaps) == 1
            assert snaps[0]["theta"] == 4.0
            assert snaps[0]["concept_id"] is None
            # 멱등 재호출 → 이미 종료 → 스냅샷 미중복
            r2 = client.patch(f"/v1/me/sessions/{sid}/end", headers=auth)
            assert r2.status_code == 200
            snaps2 = client.get("/v1/me/ability/snapshots", headers=auth).json()
            assert len(snaps2) == 1  # 여전히 1개
    finally:
        asyncio.run(_cleanup_all())


def test_me_session_end_auto_captures_concept_snapshots_on_live_pg() -> None:
    """slice 75: PATCH /sessions/{id}/end → 전과목 θ + *개념별* θ 자동 적재(실 PG).

    개념 매핑(PRIMARY)이 있는 문항을 풀고 세션을 종료하면 전과목 1행 + 개념 1행이 함께
    적재된다. slice 74 루프 닫기: get_current_theta(session, uid, cid)가 그 개념 θ를 읽어
    coach _server_theta_for의 정밀 경로(폴백 없이 같은 개념끼리)가 실제로 먹힘을 검증.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    pid = uuid.uuid4()
    cid = uuid.uuid4()
    sid = uuid.uuid4()
    suffix = pid.hex[:8]

    async def _setup() -> None:
        await _add_all(_user(uid))
        await _add_all(
            Concept.from_schema(
                ConceptSchema(
                    concept_id=cid,
                    code=f"S-{suffix}",
                    name_ko="세션종료개념",
                    level=ConceptLevel.세부개념,
                )
            )
        )
        await _add_all(
            Problem.from_schema(
                ProblemSchema(
                    problem_id=pid,
                    source_type=SourceType.자체생성,
                    curriculum_version=Curriculum.REVISION_2022,
                    valid_from_year=2022,
                    subject=Subject.공통,
                    unit_codes=[f"U-{suffix}"],
                    difficulty_overall=5.0,
                )
            )
        )
        await _add_all(
            ProblemConcept.from_schema(
                ProblemConceptSchema(problem_id=pid, concept_id=cid, role=ConceptRole.PRIMARY)
            )
        )
        await _add_all(
            ProblemAttempt(attempt_id=uuid.uuid4(), user_id=uid, problem_id=pid, is_correct=True)
        )
        await _add_all(_session_row(sid, uid))  # 미종료 세션

    async def _read_thetas() -> tuple[float | None, float | None]:
        # slice 74 리더(coach _server_theta_for가 쓰는 바로 그 함수)로 개념·전과목 θ 확인.
        engine = create_async_engine(_settings().database_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return (
                    await get_current_theta(session, uid, cid),
                    await get_current_theta(session, uid),
                )
        finally:
            await engine.dispose()

    async def _cleanup_all() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                for sql, params in (
                    ("DELETE FROM ability_snapshot WHERE user_id=:u", {"u": str(uid)}),
                    ("DELETE FROM problem_attempt WHERE user_id=:u", {"u": str(uid)}),
                    ("DELETE FROM learning_session WHERE user_id=:u", {"u": str(uid)}),
                    (
                        "DELETE FROM problem_concept WHERE problem_id=:p",
                        {"p": str(pid)},
                    ),
                    ("DELETE FROM problem WHERE problem_id=:p", {"p": str(pid)}),
                    ("DELETE FROM concept WHERE concept_id=:c", {"c": str(cid)}),
                    ("DELETE FROM user_profile WHERE user_id=:u", {"u": str(uid)}),
                ):
                    await conn.execute(text(sql), params)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            r = client.patch(f"/v1/me/sessions/{sid}/end", headers=auth)
            assert r.status_code == 200, r.text
            # 전과목 곡선(필터 없음) → 1행·concept_id null
            glob = client.get("/v1/me/ability/snapshots", headers=auth).json()
            assert len(glob) == 1
            assert glob[0]["concept_id"] is None
            assert glob[0]["theta"] == 4.0
            # 개념 곡선(?concept_id=cid) → 1행·concept_id=cid (세션종료로 자동 적재됨)
            byc = client.get(f"/v1/me/ability/snapshots?concept_id={cid}", headers=auth).json()
            assert len(byc) == 1
            assert byc[0]["concept_id"] == str(cid)
            assert byc[0]["theta"] == 4.0
        # slice 74 루프: 리더가 개념 θ(non-None)·전과목 θ 모두 반환
        concept_theta, global_theta = asyncio.run(_read_thetas())
        assert concept_theta == pytest.approx(4.0)
        assert global_theta == pytest.approx(4.0)
    finally:
        asyncio.run(_cleanup_all())


# ── 개념그래프 소비 슬2: GET /v1/me/weak-concepts (약개념 추천 — 진단 약점 + UC 메타 enrich) ──
async def _cleanup_concept_nodes(uc_ids: list[str]) -> None:
    # S0-4d: enrich 소스가 concept_node → atom_node로 전환됐으므로 시드·정리 좌석도 atom_node.
    # atom_node PK는 code(=concept.code=UC 브리지 키)라 code 컬럼으로 정리한다.
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM atom_node WHERE code = ANY(:ids)"),
                {"ids": uc_ids},
            )
    finally:
        await engine.dispose()


def _concept_with_code(cid: uuid.UUID, code: str, name: str) -> Concept:
    """backend `concept` 행(code=UC 브리지 키) — 진단이 mastery→concept join에 쓴다."""
    return Concept.from_schema(
        ConceptSchema(concept_id=cid, code=code, name_ko=name, level=ConceptLevel.세부개념)
    )


def _node_meta(uc: str, name_ko: str, domain: str, review_status: str) -> AtomNode:
    """atom_node(code PK) 안전 메타 행 — S0-4d로 enrich가 fetch_atom_node_meta로 전환됐다.

    enrich는 code(=concept.code=UC 브리지 키)로 atom_node를 조회해 name_ko·subject_area·
    review_status를 붙인다. 응답 DTO 필드 `domain`의 값 소스는 원자 `subject_area`이므로(S0-4d·
    필드명 유지·값 소스 교체) 인자 `domain`을 subject_area 컬럼에 시드한다. `level`은 NOT NULL이라
    시드 필수지만 enrich 대상이 아니라 표시 상수 '세부개념'을 박는다(값 무관).
    """
    return AtomNode(
        code=uc,
        name_ko=name_ko,
        level="세부개념",
        subject_area=domain,
        review_status=review_status,
    )


def test_me_weak_concepts_enrich_and_gating_on_live_pg() -> None:
    """GET /v1/me/weak-concepts — 약점(BKT) 식별 → code(UC) → atom_node 메타 enrich.

    end-to-end: mastery 약점 → backend `concept`(code=UC) join → `atom_node`(code) 안전 메타
    enrich(name_ko·domain(←subject_area)·review_status)·검수 게이팅·limit·redaction(본문 0)·401.
    강개념(고숙달)은 제외, 메타 미적재 code는 enrich None(graceful), reviewed_only=true면 reviewed.
    S0-4d로 enrich 소스가 concept_node → atom_node 전환(값 소스만 교체·필드명 유지).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    # 약개념 후보 3 + 강개념 1. UC는 uid 접미사로 유니크(실 403 데이터셋과 충돌 회피).
    sfx = uid.hex[:8]
    uc_a, uc_b, uc_c = f"UC.test.{sfx}.a", f"UC.test.{sfx}.b", f"UC.test.{sfx}.c"
    uc_d = f"UC.test.{sfx}.d"
    c_a, c_b, c_c, c_d = (uuid.uuid4() for _ in range(4))
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        asyncio.run(_add_all(_user(uid)))
        # backend concept(code=UC) — a/b/c/d 4개념
        asyncio.run(
            _add_all(
                _concept_with_code(c_a, uc_a, "일차함수"),
                _concept_with_code(c_b, uc_b, "이차함수"),
                _concept_with_code(c_c, uc_c, "삼각비"),
                _concept_with_code(c_d, uc_d, "집합"),
            )
        )
        # atom_node 메타 — a(reviewed)·b(pending)·c는 미적재(enrich None)·d(reviewed·강개념)
        asyncio.run(
            _add_all(
                _node_meta(uc_a, "일차함수", "[중]함수", "reviewed"),
                _node_meta(uc_b, "이차함수", "[중]함수", "pending"),
                _node_meta(uc_d, "집합", "[고]집합과명제", "reviewed"),
            )
        )
        # mastery — a/b/c 약점(<0.7)·d 강개념(0.9). 약점 정렬: a(0.2)<b(0.3)<c(0.4)
        asyncio.run(
            _add_all(
                _mastery_row(uid, c_a, t1, 0.2),
                _mastery_row(uid, c_b, t1, 0.3),
                _mastery_row(uid, c_c, t1, 0.4),
                _mastery_row(uid, c_d, t1, 0.9),
            )
        )
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            # ① 기본(recall) — 약점 3개만(강개념 d 제외)·약점 정렬·enrich
            resp = client.get("/v1/me/weak-concepts", headers=auth)
            assert resp.status_code == 200, resp.text
            rows = resp.json()
            assert [r["concept_code"] for r in rows] == [uc_a, uc_b, uc_c]  # 약점 정렬
            assert rows[0]["name_ko"] == "일차함수"  # atom_node enrich
            assert rows[0]["domain"] == "[중]함수"  # 값 소스=atom_node.subject_area
            assert rows[0]["review_status"] == "reviewed"
            assert rows[0]["weakness"] == 0.2
            assert rows[1]["review_status"] == "pending"  # b
            # c는 atom_node 미적재 → enrich None graceful(추천은 유지)
            assert rows[2]["concept_code"] == uc_c
            assert rows[2]["name_ko"] is None
            assert rows[2]["domain"] is None
            assert rows[2]["review_status"] is None
            # redaction — 본문 필드 부재
            assert "description" not in rows[0]
            assert "formal_definition" not in rows[0]

            # ② reviewed_only=true — reviewed만(a)·pending(b)·미적재(c) 제외
            resp = client.get(
                "/v1/me/weak-concepts", headers=auth, params={"reviewed_only": "true"}
            )
            assert [r["concept_code"] for r in resp.json()] == [uc_a]

            # ③ limit=1 — 약점 정렬 보존 상위 1(a)
            resp = client.get("/v1/me/weak-concepts", headers=auth, params={"limit": "1"})
            assert [r["concept_code"] for r in resp.json()] == [uc_a]

            # ④ threshold=0.35 — 0.35 미만만(a 0.2·b 0.3·c 0.4 제외)
            resp = client.get("/v1/me/weak-concepts", headers=auth, params={"threshold": "0.35"})
            assert [r["concept_code"] for r in resp.json()] == [uc_a, uc_b]

            # ⑤ 무토큰 401
            assert client.get("/v1/me/weak-concepts").status_code == 401
    finally:
        asyncio.run(_cleanup_mastery([uid]))
        asyncio.run(_cleanup_concepts([c_a, c_b, c_c, c_d]))
        asyncio.run(_cleanup_concept_nodes([uc_a, uc_b, uc_c, uc_d]))
        asyncio.run(_cleanup([uid]))  # user_profile 정리


# ── 소비 선수 슬1: GET /v1/me/weak-concepts/{concept_id}/prerequisites (막힌 선수개념 추천) ──
async def _cleanup_concept_edges(from_ids: list[uuid.UUID]) -> None:
    """concept_edge 정리 — concept FK 삭제 전에 엣지부터(FK 순서)."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM concept_edge WHERE from_concept_id = ANY(:ids)"),
                {"ids": from_ids},
            )
    finally:
        await engine.dispose()


def _prereq_edge(from_id: uuid.UUID, to_id: uuid.UUID, strength: float) -> ConceptEdge:
    """선수 엣지 — from(선수)이 to(후행)의 선수. edge_id·created_at은 server_default."""
    return ConceptEdge(
        from_concept_id=from_id,
        to_concept_id=to_id,
        edge_type=EdgeType.PREREQUISITE.value,
        edge_strength=strength,
    )


def test_me_prerequisite_gaps_traversal_and_gating_on_live_pg() -> None:
    """GET /v1/me/weak-concepts/{concept_id}/prerequisites — 약개념의 막힌 선수 추천.

    end-to-end: 약개념 C + 선수 2(하나 weak·하나 strong) + concept_edge(to=C·from=선수)·
    atom_node 메타·mastery 적재 → 방향(to==C→from)·weak_only(약한 선수만)·enrich·게이팅·
    정렬(weakness asc)·redaction·401 왕복.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    sfx = uid.hex[:8]
    # 후행(약개념) C + 선수 P_weak·P_strong. UC는 uid 접미사로 유니크(실 403 충돌 회피).
    uc_c = f"UC.test.{sfx}.post"
    uc_pw = f"UC.test.{sfx}.preweak"
    uc_ps = f"UC.test.{sfx}.prestrong"
    c_post, c_pw, c_ps = (uuid.uuid4() for _ in range(3))
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        asyncio.run(_add_all(_user(uid)))
        asyncio.run(
            _add_all(
                _concept_with_code(c_post, uc_c, "이차함수"),  # 후행(약개념)
                _concept_with_code(c_pw, uc_pw, "일차함수"),  # 선수(약함)
                _concept_with_code(c_ps, uc_ps, "사칙연산"),  # 선수(강함)
            )
        )
        # atom_node 메타 — 선수 둘 다 reviewed(게이팅 통과·enrich).
        asyncio.run(
            _add_all(
                _node_meta(uc_pw, "일차함수", "[중]함수", "reviewed"),
                _node_meta(uc_ps, "사칙연산", "[초]수와연산", "reviewed"),
            )
        )
        # concept_edge — 둘 다 C의 선수(to==c_post·from==선수). 강도 pw 0.9·ps 0.5.
        asyncio.run(
            _add_all(
                _prereq_edge(c_pw, c_post, 0.9),
                _prereq_edge(c_ps, c_post, 0.5),
            )
        )
        # mastery — pw 약점(0.2)·ps 강함(0.9). 후행 C 자신도 약점(추천 대상이지만 traversal은 선수).
        asyncio.run(
            _add_all(
                _mastery_row(uid, c_pw, t1, 0.2),
                _mastery_row(uid, c_ps, t1, 0.9),
                _mastery_row(uid, c_post, t1, 0.3),
            )
        )
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            base = f"/v1/me/weak-concepts/{c_post}/prerequisites"
            # ① 기본(weak_only=true) — 막힌 선수 pw만(ps는 강함 0.9 제외)·enrich
            resp = client.get(base, headers=auth)
            assert resp.status_code == 200, resp.text
            rows = resp.json()
            assert [r["concept_code"] for r in rows] == [uc_pw]  # 약한 선수만
            assert rows[0]["name_ko"] == "일차함수"  # atom_node enrich
            assert rows[0]["domain"] == "[중]함수"  # 값 소스=atom_node.subject_area
            assert rows[0]["review_status"] == "reviewed"
            assert rows[0]["weakness"] == 0.2
            assert rows[0]["edge_strength"] == 0.9
            # redaction — 본문 필드 부재
            assert "description" not in rows[0]
            assert "formal_definition" not in rows[0]

            # ② weak_only=false — 두 선수 모두(강한 ps 포함)·정렬 weakness asc(pw 0.2 먼저)
            resp = client.get(base, headers=auth, params={"weak_only": "false"})
            codes = [r["concept_code"] for r in resp.json()]
            assert codes == [uc_pw, uc_ps]  # 약한 선수(root blocker) 먼저

            # ③ threshold=0.25 — 0.25 미만만(pw 0.2 유지·ps 0.9 제외)
            resp = client.get(base, headers=auth, params={"threshold": "0.25"})
            assert [r["concept_code"] for r in resp.json()] == [uc_pw]

            # ④ 선수 없는 개념(c_pw를 후행으로) — 빈 목록
            resp = client.get(f"/v1/me/weak-concepts/{c_pw}/prerequisites", headers=auth)
            assert resp.json() == []

            # ⑤ 무토큰 401
            assert client.get(base).status_code == 401
    finally:
        asyncio.run(_cleanup_concept_edges([c_pw, c_ps]))
        asyncio.run(_cleanup_mastery([uid]))
        asyncio.run(_cleanup_concepts([c_post, c_pw, c_ps]))
        asyncio.run(_cleanup_concept_nodes([uc_c, uc_pw, uc_ps]))


def test_me_prerequisite_gaps_atom_axis_fence_on_live_pg() -> None:
    """GET /v1/me/weak-concepts/{C}/prerequisites — **원자 축 밖 선수는 노출되지 않는다**(ARCH-13).

    `concept`/`concept_edge`에는 원자 백본과 구 437 개념이 code로 병존한다. 축 밖 선수(=`atom_node`
    행이 없는 code)는 runtime truth가 아니므로 `reviewed_only=false`(기본·recall 보존 경로)에서도
    제외된다 — 예전에는 enrich만 None인 채 노출되거나 `reviewed_only`에서 조용히 사라졌다.

    울타리가 *실제 쿼리*에 있음을 증명하는 end-to-end 근거다(컴파일 SQL 거버넌스 테스트는 형태만
    본다). 두 선수는 mastery·강도가 같고 **atom_node 행 유무만 다르다** — 그래서 결과 차이의 원인이
    축 하나로 좁혀진다(변별력).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    sfx = uid.hex[:8]
    uc_c = f"UC.test.{sfx}.fence.post"
    uc_on = f"UC.test.{sfx}.fence.onaxis"  # atom_node 행 있음 = 원자 축
    uc_off = f"UC.test.{sfx}.fence.offaxis"  # atom_node 행 없음 = 축 밖(구 437 상황)
    c_post, c_on, c_off = (uuid.uuid4() for _ in range(3))
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        asyncio.run(_add_all(_user(uid)))
        asyncio.run(
            _add_all(
                _concept_with_code(c_post, uc_c, "후행개념"),
                _concept_with_code(c_on, uc_on, "축안선수"),
                _concept_with_code(c_off, uc_off, "축밖선수"),
            )
        )
        # atom_node는 축 *안* 선수에만 적재 — 이 한 가지가 두 선수의 유일한 차이다.
        asyncio.run(_add_all(_node_meta(uc_on, "축안선수", "[중]함수", "reviewed")))
        asyncio.run(
            _add_all(
                _prereq_edge(c_on, c_post, 0.9),
                _prereq_edge(c_off, c_post, 0.9),
            )
        )
        # 둘 다 동일하게 약점(0.2) — weak_only·정렬로는 구분되지 않는다.
        asyncio.run(
            _add_all(
                _mastery_row(uid, c_on, t1, 0.2),
                _mastery_row(uid, c_off, t1, 0.2),
            )
        )
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            base = f"/v1/me/weak-concepts/{c_post}/prerequisites"
            # ① 기본(reviewed_only=false) — 축 안만 노출(축 밖은 울타리가 제외).
            rows = client.get(base, headers=auth).json()
            assert [r["concept_code"] for r in rows] == [uc_on]
            assert rows[0]["name_ko"] == "축안선수"  # 같은 쿼리 OUTER JOIN enrich

            # ② weak_only=false에서도 축 밖은 여전히 제외(약점 필터와 무관한 축 판정).
            rows = client.get(base, headers=auth, params={"weak_only": "false"}).json()
            assert [r["concept_code"] for r in rows] == [uc_on]
    finally:
        asyncio.run(_cleanup_concept_edges([c_on, c_off]))
        asyncio.run(_cleanup_mastery([uid]))
        asyncio.run(_cleanup_concepts([c_post, c_on, c_off]))
        asyncio.run(_cleanup_concept_nodes([uc_c, uc_on, uc_off]))
        asyncio.run(_cleanup([uid]))  # user_profile 정리


def test_me_prerequisite_gaps_multi_hop_traversal_on_live_pg() -> None:
    """GET /v1/me/weak-concepts/{C}/prerequisites?max_depth=N — 다단계(재귀 CTE) 선수 traversal.

    체인 C ← P1(depth1) ← P2(depth2) ← P3(depth3)을 concept_edge로 적재(from=선수·to=후행)하고,
    셋 다 약점(weak_only 통과)으로 둔 뒤 max_depth별 노출과 응답의 depth 필드를 검증한다:
      - max_depth=1(기본): P1만(기존 1-hop 계약).
      - max_depth=2: P1·P2(depth 1·2)·P3 제외.
      - max_depth=3: P1·P2·P3 전부(depth 1·2·3).
    정렬은 weakness 동률이라 depth asc(가까운 선수 먼저) → P1·P2·P3 순. depth는 응답에 노출.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    sfx = uid.hex[:8]
    uc_c = f"UC.test.{sfx}.mh.post"
    uc_p1 = f"UC.test.{sfx}.mh.p1"
    uc_p2 = f"UC.test.{sfx}.mh.p2"
    uc_p3 = f"UC.test.{sfx}.mh.p3"
    c_post, c_p1, c_p2, c_p3 = (uuid.uuid4() for _ in range(4))
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        asyncio.run(_add_all(_user(uid)))
        asyncio.run(
            _add_all(
                _concept_with_code(c_post, uc_c, "후행개념"),
                _concept_with_code(c_p1, uc_p1, "선수1"),
                _concept_with_code(c_p2, uc_p2, "선수2"),
                _concept_with_code(c_p3, uc_p3, "선수3"),
            )
        )
        asyncio.run(
            _add_all(
                _node_meta(uc_p1, "선수1", "[중]함수", "reviewed"),
                _node_meta(uc_p2, "선수2", "[중]함수", "reviewed"),
                _node_meta(uc_p3, "선수3", "[초]수와연산", "reviewed"),
            )
        )
        # 선수 체인 — P1은 C의 선수·P2는 P1의 선수·P3는 P2의 선수(from=선수·to=후행).
        asyncio.run(
            _add_all(
                _prereq_edge(c_p1, c_post, 0.9),
                _prereq_edge(c_p2, c_p1, 0.8),
                _prereq_edge(c_p3, c_p2, 0.7),
            )
        )
        # 셋 다 약점(0.2)으로 둬 weak_only 통과. weakness 동률이라 depth asc 정렬 검증 가능.
        asyncio.run(
            _add_all(
                _mastery_row(uid, c_p1, t1, 0.2),
                _mastery_row(uid, c_p2, t1, 0.2),
                _mastery_row(uid, c_p3, t1, 0.2),
            )
        )
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            base = f"/v1/me/weak-concepts/{c_post}/prerequisites"
            # ① 기본(max_depth 미지정=1) — 직접 선수 P1만(1-hop 계약).
            resp = client.get(base, headers=auth)
            assert resp.status_code == 200, resp.text
            rows = resp.json()
            assert [r["concept_code"] for r in rows] == [uc_p1]
            assert rows[0]["depth"] == 1

            # ② max_depth=2 — P1(depth1)·P2(depth2)·P3 제외.
            resp = client.get(base, headers=auth, params={"max_depth": "2"})
            rows = resp.json()
            assert [r["concept_code"] for r in rows] == [uc_p1, uc_p2]
            assert [r["depth"] for r in rows] == [1, 2]  # 동률 weakness → depth asc

            # ③ max_depth=3 — P1·P2·P3 전부·depth 정확.
            resp = client.get(base, headers=auth, params={"max_depth": "3"})
            rows = resp.json()
            assert [r["concept_code"] for r in rows] == [uc_p1, uc_p2, uc_p3]
            assert [r["depth"] for r in rows] == [1, 2, 3]

            # ④ max_depth 경계 — 0은 422(ge=1)·6은 422(le=5).
            assert client.get(base, headers=auth, params={"max_depth": "0"}).status_code == 422
            assert client.get(base, headers=auth, params={"max_depth": "6"}).status_code == 422
    finally:
        asyncio.run(_cleanup_concept_edges([c_p1, c_p2, c_p3]))
        asyncio.run(_cleanup_mastery([uid]))
        asyncio.run(_cleanup_concepts([c_post, c_p1, c_p2, c_p3]))
        asyncio.run(_cleanup_concept_nodes([uc_c, uc_p1, uc_p2, uc_p3]))
        asyncio.run(_cleanup([uid]))  # user_profile 정리


# ── 소비 학습경로 슬: GET /v1/me/weak-concepts/{concept_id}/learning-path (선수 위상정렬) ──
def test_me_learning_path_topological_ordering_and_gating_on_live_pg() -> None:
    """GET /v1/me/weak-concepts/{C}/learning-path — 막힌 선수의 위상정렬 학습 순서(근본 먼저).

    prerequisites 슬1의 미러(같은 query·게이팅)이되 응답이 *순서화된 경로*다. 핵심: 두 직접
    선수 P_a·P_b가 둘 다 depth1·동률 weakness지만 내부엣지 P_a→P_b(P_a가 P_b의 선수)가 있어
    위상정렬은 P_a(근본)를 먼저 둔다 — 같은 입력의 prerequisites는 edge_strength desc tie-break
    로 P_b를 먼저 주므로 두 엔드포인트의 순서가 *뒤집힘*을 대비 검증한다(위상정렬의 가치).
    추가로 weak_only=false(강한 선수 포함)·threshold(약점 게이트)·빈 경로·redaction·401 왕복.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    sfx = uid.hex[:8]
    # 후행(약개념) C + 직접 선수 P_a·P_b(둘 다 약점·동률)·P_s(강함). 내부엣지 P_a→P_b.
    uc_c = f"UC.test.{sfx}.lp.post"
    uc_pa = f"UC.test.{sfx}.lp.prea"
    uc_pb = f"UC.test.{sfx}.lp.preb"
    uc_ps = f"UC.test.{sfx}.lp.pres"
    c_post, c_pa, c_pb, c_ps = (uuid.uuid4() for _ in range(4))
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        asyncio.run(_add_all(_user(uid)))
        asyncio.run(
            _add_all(
                _concept_with_code(c_post, uc_c, "이차함수"),  # 후행(약개념)
                _concept_with_code(c_pa, uc_pa, "선수A"),  # 근본 선수(약함)
                _concept_with_code(c_pb, uc_pb, "선수B"),  # 말단 선수(약함·A의 후행)
                _concept_with_code(c_ps, uc_ps, "선수S"),  # 강한 선수
            )
        )
        asyncio.run(
            _add_all(
                _node_meta(uc_pa, "선수A", "[중]함수", "reviewed"),
                _node_meta(uc_pb, "선수B", "[중]함수", "reviewed"),
                _node_meta(uc_ps, "선수S", "[초]수와연산", "reviewed"),
            )
        )
        # concept_edge — P_a·P_b·P_s 모두 C의 직접 선수(to==c_post). 내부엣지 P_a→P_b(to==c_pb).
        # P_a→C 강도 0.5·P_b→C 강도 0.9(동률 weakness에서 prerequisites는 강도 desc로 P_b 먼저).
        asyncio.run(
            _add_all(
                _prereq_edge(c_pa, c_post, 0.5),
                _prereq_edge(c_pb, c_post, 0.9),
                _prereq_edge(c_ps, c_post, 0.5),
                _prereq_edge(c_pa, c_pb, 0.8),  # 내부엣지 — P_a가 P_b의 선수(위상정렬 근본).
            )
        )
        # mastery — P_a·P_b 약점 동률(0.2)·P_s 강함(0.9).
        asyncio.run(
            _add_all(
                _mastery_row(uid, c_pa, t1, 0.2),
                _mastery_row(uid, c_pb, t1, 0.2),
                _mastery_row(uid, c_ps, t1, 0.9),
            )
        )
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            base = f"/v1/me/weak-concepts/{c_post}/learning-path"
            # ① 기본(weak_only=true) — 막힌 선수 P_a·P_b를 위상정렬(근본 P_a 먼저).
            resp = client.get(base, headers=auth)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["has_cycle"] is False
            steps = data["steps"]
            assert [s["concept_code"] for s in steps] == [uc_pa, uc_pb]  # 근본 먼저
            assert [s["position"] for s in steps] == [0, 1]
            assert steps[0]["concept_name"] == "선수A"  # backend concept.name_ko 전사
            # redaction — 본문 슬롯 부재(LearningStep은 안전·구조 메타만).
            assert "description" not in steps[0]
            assert "formal_definition" not in steps[0]

            # ① 대비 — 같은 입력의 prerequisites는 edge_strength desc로 P_b를 먼저 준다.
            # 위상정렬이 그 순서를 *뒤집어* 근본(P_a)을 앞세움을 명시(엔드포인트의 가치).
            prereq = client.get(f"/v1/me/weak-concepts/{c_post}/prerequisites", headers=auth).json()
            assert [r["concept_code"] for r in prereq] == [uc_pb, uc_pa]  # 추천 순서
            assert [s["concept_code"] for s in steps] != [r["concept_code"] for r in prereq]

            # ② weak_only=false — 강한 P_s 포함·여전히 위상정렬(P_a→P_b·P_s는 말단 무관).
            resp = client.get(base, headers=auth, params={"weak_only": "false"})
            codes = [s["concept_code"] for s in resp.json()["steps"]]
            assert codes == [uc_pa, uc_pb, uc_ps]

            # ③ threshold=0.15 — 0.15 미만만(P_a·P_b 0.2는 제외) → 빈 경로(게이트 통과 검증).
            resp = client.get(base, headers=auth, params={"threshold": "0.15"})
            data = resp.json()
            assert data["steps"] == []
            assert data["has_cycle"] is False

            # ④ 선수 없는 개념(P_s를 후행으로) — 빈 경로.
            resp = client.get(f"/v1/me/weak-concepts/{c_ps}/learning-path", headers=auth)
            assert resp.json()["steps"] == []

            # ⑤ 무토큰 401.
            assert client.get(base).status_code == 401
    finally:
        asyncio.run(_cleanup_concept_edges([c_pa, c_pb, c_ps]))
        asyncio.run(_cleanup_mastery([uid]))
        asyncio.run(_cleanup_concepts([c_post, c_pa, c_pb, c_ps]))
        asyncio.run(_cleanup_concept_nodes([uc_c, uc_pa, uc_pb, uc_ps]))
        asyncio.run(_cleanup([uid]))  # user_profile 정리


def test_me_learning_path_multi_hop_on_live_pg() -> None:
    """GET /v1/me/weak-concepts/{C}/learning-path?max_depth=N — 다단계 선수의 위상정렬 경로.

    체인 C ← P1 ← P2 ← P3(엣지 from=선수·to=후행)·셋 다 약점. max_depth=3이면 gaps={P1,P2,P3}·
    집합 내부엣지(P2→P1·P3→P2) 위상정렬 → 근본 P3부터 [P3,P2,P1](position 0·1·2). 이는
    prerequisites의 추천 순서(depth asc=[P1,P2,P3])와 *정반대*다 — 추천은 가까운 선수를 먼저
    보이지만 학습 순서는 근본(깊은) 선수를 먼저 다져야 하기 때문(LTHC). max_depth=1 경계도 확인.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    sfx = uid.hex[:8]
    uc_c = f"UC.test.{sfx}.lpmh.post"
    uc_p1 = f"UC.test.{sfx}.lpmh.p1"
    uc_p2 = f"UC.test.{sfx}.lpmh.p2"
    uc_p3 = f"UC.test.{sfx}.lpmh.p3"
    c_post, c_p1, c_p2, c_p3 = (uuid.uuid4() for _ in range(4))
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        asyncio.run(_add_all(_user(uid)))
        asyncio.run(
            _add_all(
                _concept_with_code(c_post, uc_c, "후행개념"),
                _concept_with_code(c_p1, uc_p1, "선수1"),
                _concept_with_code(c_p2, uc_p2, "선수2"),
                _concept_with_code(c_p3, uc_p3, "선수3"),
            )
        )
        asyncio.run(
            _add_all(
                _node_meta(uc_p1, "선수1", "[중]함수", "reviewed"),
                _node_meta(uc_p2, "선수2", "[중]함수", "reviewed"),
                _node_meta(uc_p3, "선수3", "[초]수와연산", "reviewed"),
            )
        )
        # 선수 체인 — P1은 C의 선수·P2는 P1의 선수·P3는 P2의 선수(from=선수·to=후행).
        asyncio.run(
            _add_all(
                _prereq_edge(c_p1, c_post, 0.9),
                _prereq_edge(c_p2, c_p1, 0.8),
                _prereq_edge(c_p3, c_p2, 0.7),
            )
        )
        # 셋 다 약점(0.2)으로 둬 weak_only 통과(위상정렬은 내부엣지가 강제·tie-break 무관).
        asyncio.run(
            _add_all(
                _mastery_row(uid, c_p1, t1, 0.2),
                _mastery_row(uid, c_p2, t1, 0.2),
                _mastery_row(uid, c_p3, t1, 0.2),
            )
        )
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            base = f"/v1/me/weak-concepts/{c_post}/learning-path"
            # ① max_depth=1(기본) — 직접 선수 P1만(내부엣지 없음·근본 1개).
            resp = client.get(base, headers=auth)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert [s["concept_code"] for s in data["steps"]] == [uc_p1]
            assert data["has_cycle"] is False

            # ② max_depth=3 — gaps={P1,P2,P3}·내부엣지(P2→P1·P3→P2) 위상정렬 → 근본 P3 먼저.
            resp = client.get(base, headers=auth, params={"max_depth": "3"})
            steps = resp.json()["steps"]
            assert [s["concept_code"] for s in steps] == [uc_p3, uc_p2, uc_p1]  # 근본→말단
            assert [s["position"] for s in steps] == [0, 1, 2]

            # ② 대비 — prerequisites는 depth asc(가까운 선수 먼저)=[P1,P2,P3]로 *정반대* 순서.
            prereq = client.get(
                f"/v1/me/weak-concepts/{c_post}/prerequisites",
                headers=auth,
                params={"max_depth": "3"},
            ).json()
            assert [r["concept_code"] for r in prereq] == [uc_p1, uc_p2, uc_p3]
            assert [s["concept_code"] for s in steps] == list(
                reversed([r["concept_code"] for r in prereq])
            )

            # ③ max_depth 경계 — 0은 422(ge=1)·6은 422(le=5).
            assert client.get(base, headers=auth, params={"max_depth": "0"}).status_code == 422
            assert client.get(base, headers=auth, params={"max_depth": "6"}).status_code == 422
    finally:
        asyncio.run(_cleanup_concept_edges([c_p1, c_p2, c_p3]))
        asyncio.run(_cleanup_mastery([uid]))
        asyncio.run(_cleanup_concepts([c_post, c_p1, c_p2, c_p3]))
        asyncio.run(_cleanup_concept_nodes([uc_c, uc_p1, uc_p2, uc_p3]))
        asyncio.run(_cleanup([uid]))  # user_profile 정리


# ── L4 코칭 결선: GET /v1/me/weak-concepts/{concept_id}/coaching (선수 차단 우선 코칭) ──
def test_me_concept_coaching_prereq_block_and_fallback_on_live_pg() -> None:
    """GET /v1/me/weak-concepts/{C}/coaching — 막힌 선수 있으면 선수 복습 우선·없으면 메타인지.

    end-to-end:
      ① 약개념 C + 막힌 선수 P(약함)를 concept_edge(to=C·from=P)·메타·mastery로 적재 →
         `/coaching`이 focus=='prerequisite_review'·rationale/prompt에 선수 이름(일차함수) 포함.
      ② 선수 없는(또는 막힌 선수 없는) 개념 → 메타인지 focus(verify/foundation/advance 등) fallback.
      ③ 무토큰 401.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    sfx = uid.hex[:8]
    uc_c = f"UC.test.{sfx}.co.post"  # 후행(약개념)
    uc_pw = f"UC.test.{sfx}.co.preweak"  # 막힌 선수
    c_post, c_pw = uuid.uuid4(), uuid.uuid4()
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        asyncio.run(_add_all(_user(uid)))
        asyncio.run(
            _add_all(
                _concept_with_code(c_post, uc_c, "이차함수"),  # 후행
                _concept_with_code(c_pw, uc_pw, "일차함수"),  # 막힌 선수
            )
        )
        asyncio.run(_add_all(_node_meta(uc_pw, "일차함수", "[중]함수", "reviewed")))
        # concept_edge — P는 C의 선수(to==c_post·from==c_pw).
        asyncio.run(_add_all(_prereq_edge(c_pw, c_post, 0.9)))
        # mastery — 선수 P 약점(0.2)·후행 C도 약점(0.3·fallback 경로 검증용).
        asyncio.run(
            _add_all(
                _mastery_row(uid, c_pw, t1, 0.2),
                _mastery_row(uid, c_post, t1, 0.3),
            )
        )
        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            # ① 막힌 선수 있음 → 선수 복습 우선 코칭.
            resp = client.get(f"/v1/me/weak-concepts/{c_post}/coaching", headers=auth)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["focus"] == "prerequisite_review"
            assert "일차함수" in body["prompt"]  # 선수 이름 노출(자체 코칭 문구)
            assert "일차함수" in body["rationale"]
            assert body["socratic_category"] == "clarification"
            # 톤 가드 — 학생 prompt에 금기 표현 부재.
            for forbidden in ("빨리", "정답", "틀렸"):
                assert forbidden not in body["prompt"]
            # redaction — 본문 필드 부재(자체 작성 코칭 문구).
            assert "description" not in body
            assert "formal_definition" not in body

            # ② 막힌 선수 없는 개념(선수 P를 후행으로 — P엔 선수 엣지 없음) → 메타인지 fallback.
            resp = client.get(f"/v1/me/weak-concepts/{c_pw}/coaching", headers=auth)
            assert resp.status_code == 200, resp.text
            fb = resp.json()
            assert fb["focus"] != "prerequisite_review"  # 선수 차단 아님
            # P 자신은 BKT만 있고 IRT 없음 → diagnose 또는 mastery 기반 메타인지 focus.
            assert fb["focus"] in {
                "verify",
                "consolidate",
                "retrieval",
                "foundation",
                "advance",
                "diagnose",
            }

            # ③ 무토큰 401.
            assert client.get(f"/v1/me/weak-concepts/{c_post}/coaching").status_code == 401
    finally:
        asyncio.run(_cleanup_concept_edges([c_pw]))
        asyncio.run(_cleanup_mastery([uid]))
        asyncio.run(_cleanup_concepts([c_post, c_pw]))
        asyncio.run(_cleanup_concept_nodes([uc_c, uc_pw]))
        asyncio.run(_cleanup([uid]))  # user_profile 정리
