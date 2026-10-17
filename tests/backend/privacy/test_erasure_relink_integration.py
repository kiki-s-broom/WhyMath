"""SEC-40 — 삭제권 이행 뒤 `evidence_event`로 **재연결되지 않는다**(실 PG · 기본 SKIP).

배경: `evidence_event`(교수법 처치·추천 기록)는 user 컬럼도 user FK도 없이 `session_id`(느슨참조)로만
학생에 묶인다. 삭제권을 이행하고도 이 행이 남으면 다음 두 경로로 삭제한 학생의 처치 기록을 다시
찾을 수 있다 — 이 파일이 두 경로를 각각 닫는다.

  ⓐ 개별 세션 삭제(`DELETE /v1/me/sessions/{id}`) — 삭제 증빙(`deletion_audit`)이 (user_id=소유자,
     resource_id=세션 ID)를 남기고, 그 세션 ID의 `evidence_event` 행이 남으면 둘을 맞대어 곧바로
     그 학생의 처치 기록을 찾는다.
  ⓑ 계정 삭제(`DELETE /v1/me`) — 삭제 증빙이 user_id를 남기고, `evidence_event.meta.user_binding`은
     HMAC(jwt 비밀키, 도메인:session_id:user_id)라 잔존 user_id로 전 행의 바인딩을 재계산하면 그
     학생의 세션을 다시 찾는다(비밀키를 가진 운영 주체 한정).

검사 항목(두 경로 각각):
  · **재연결 불가** — 삭제 뒤 증빙 로그의 키로 다시 찾아지는 행이 0건이다(`_relinkable_rows`는 운영
    주체가 하는 재연결과 같은 계산을 한다 — 세션 ID 조인 + 같은 HMAC 재계산).
  · **대조군(과삭제 방지)** — 지우지 않은 다른 학생·다른 세션의 행은 그대로이고, *같은 재연결 계산이
    그 행은 실제로 찾는다*(검사기가 항상 빈 결과를 내는 위장이 아님을 같은 화면에서 보인다).
  · **원자성** — 삭제가 도중에 실패하면 세션·증빙·계정이 전부 그대로다(부분 삭제 0).

재연결 계산이 학습 세션 ID가 아닌 행까지 닿아야 한다는 점이 이 파일의 핵심 픽스처다: 교수법 처치
(`/study`)는 `learning_session`이 아닌 **임의 UUID**를 세션 ID로 쓴다. 학습 세션 조인만으로 지우면
이 행들이 남고, 정확히 ⓑ 경로(HMAC 재계산)로만 학생에 이어진다.

주입 확인(2026-10-03 · 보고에 결과 표): erase_user의 evidence 삭제 제거 · 세션 ID 수집을 학습
세션 삭제 *뒤*로 이동 · 개별 세션 삭제 경로의 증빙 삭제 제거 · 삭제 필터 완화(전 행 삭제)에서 각각
이 파일의 어느 테스트가 RED가 되는지 확인했다.

hermetic 아님(`@pytest.mark.integration`) — CI의 `backend-migrations` 잡(실 PG)이 집행 지점이다.
PG 미도달이면 graceful skip(기존 `test_erasure_learner_state_integration.py`와 동형).

TimescaleDB 한계(정직 표기): 이 파일은 확장 없는 일반 PG에서 돈다 — `evidence_event`가 하이퍼테이블인
운영 환경(압축 청크 포함)에서의 DELETE는 여기서 검증되지 않는다(보고서 §5).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from whymath_backend.api.me import (
    AccountErasureRequest,
    delete_my_session,
    erase_my_account,
)
from whymath_backend.config import Settings
from whymath_backend.db.models.activity import AttemptEvent, LearningSession
from whymath_backend.db.models.audit import DeletionAudit
from whymath_backend.db.models.evidence_event import EvidenceEvent
from whymath_backend.db.models.user import UserProfile
from whymath_backend.l2.pedagogy_evidence import (
    META_KEY_USER_BINDING,
    record_pedagogy_outcome,
    record_pedagogy_treatment,
    session_user_binding,
)
from whymath_backend.l2.recommendation_evidence import record_recommendation_treatment
from whymath_backend.privacy import erasure
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

pytestmark = pytest.mark.integration

_SECRET = "integration-jwt-secret-0123456789abcdef"
_CONFIRM = "DELETE_MY_ACCOUNT"
_OBJECTIVE = "obj-sec40-relink"


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_SECRET))


async def _pg_reachable() -> bool:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — 도달성 프로브(미도달이면 skip·원인 무관)
        return False
    finally:
        await engine.dispose()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    if not await _pg_reachable():
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    eng = create_async_engine(_settings().database_url)
    yield eng
    await eng.dispose()


class _World:
    """한 테스트가 만든 사용자·세션 ID 기록 — 종료 시 정리 대상(실 DB 오염 방지)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.users: list[uuid.UUID] = []
        self.sessions: list[uuid.UUID] = []

    async def new_user(self) -> uuid.UUID:
        uid = uuid.uuid4()
        self.users.append(uid)
        async with async_sessionmaker(self.engine)() as db:
            db.add(
                UserProfile.from_schema(
                    UserProfileSchema(
                        user_id=uid,
                        persona_primary=Persona.A_일반고고3,
                        birth_year=2000,
                        is_minor=False,
                    )
                )
            )
            await db.commit()
        return uid

    async def new_learning_session_with_recommendation(self, uid: uuid.UUID) -> uuid.UUID:
        """학습 세션 1개 + 그 세션을 가리키는 추천 처치 행 1건(`recommendation_render`)."""
        sid = uuid.uuid4()
        self.sessions.append(sid)
        now = datetime.now(UTC)
        async with async_sessionmaker(self.engine)() as db:
            db.add(
                LearningSession(
                    session_id=sid,
                    user_id=uid,
                    started_at=now,
                    last_activity_at=now,
                    ended_at=now,  # 닫힌 세션 — 사용자당 열린 세션 부분 유니크와 무관
                )
            )
            await db.flush()
            await record_recommendation_treatment(
                db,
                problem_id=uuid.uuid4(),
                theta=0.0,
                pool_size=3,
                applied_weights=False,
                learning_session_id=sid,
            )
            await db.commit()
        return sid

    async def new_pedagogy_pair(
        self, uid: uuid.UUID, *, session_id: uuid.UUID | None = None
    ) -> uuid.UUID:
        """교수법 처치 + 결과 1쌍 — 기본은 학습 세션이 **아닌** 임의 UUID(실 `/study` 형태)."""
        sid = session_id if session_id is not None else uuid.uuid4()
        self.sessions.append(sid)
        settings = _settings()
        async with async_sessionmaker(self.engine)() as db:
            await record_pedagogy_treatment(
                db,
                objective_id=_OBJECTIVE,
                k_type="CONCEPT",
                session_id=sid,
                user_id=uid,
                settings=settings,
                strategy="worked_example",
                content_source="dsl",
            )
            await db.flush()  # 결과 기입이 처치 행을 읽는다(같은 트랜잭션 가시)
            await record_pedagogy_outcome(
                db,
                objective_id=_OBJECTIVE,
                k_type="CONCEPT",
                session_id=sid,
                user_id=uid,
                settings=settings,
                correct=True,
            )
            await db.commit()
        return sid

    async def cleanup(self) -> None:
        async with self.engine.begin() as conn:
            for sid in self.sessions:
                await conn.execute(
                    text("DELETE FROM evidence_event WHERE session_id = :s"), {"s": sid}
                )
            for uid in self.users:
                await conn.execute(text("DELETE FROM attempt_event WHERE user_id = :u"), {"u": uid})
                await conn.execute(
                    text("DELETE FROM learning_session WHERE user_id = :u"), {"u": uid}
                )
                await conn.execute(
                    text("DELETE FROM deletion_audit WHERE user_id = :u"), {"u": uid}
                )
                await conn.execute(text("DELETE FROM user_profile WHERE user_id = :u"), {"u": uid})


@pytest.fixture
async def world(engine: AsyncEngine) -> AsyncIterator[_World]:
    w = _World(engine)
    try:
        yield w
    finally:
        await w.cleanup()


# ---------------------------------------------------------------------------
# 재연결 계산 — 운영 주체가 삭제 증빙의 키로 하는 두 가지 조회를 그대로 재현한다.
# ---------------------------------------------------------------------------


async def _evidence_rows(engine: AsyncEngine, session_ids: list[uuid.UUID]) -> int:
    async with async_sessionmaker(engine)() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(EvidenceEvent)
            .where(EvidenceEvent.session_id.in_(session_ids))
        )
        return int(count or 0)


async def _relinkable_rows(
    engine: AsyncEngine,
    *,
    audit_user_id: uuid.UUID,
    audit_resource_id: uuid.UUID | None,
    hmac_scope: uuid.UUID | None = None,
) -> int:
    """삭제 증빙(`deletion_audit`)의 키로 다시 찾아지는 `evidence_event` 행 수.

    두 조회를 합친다 — ⓐ `session_id == resource_id`(세션 ID 조인) ⓑ 저장된 `user_binding`이 잔존
    user_id로 *재계산한* HMAC과 일치(행마다 자신의 session_id로 계산). 하나라도 걸리면 재연결 가능.

    `hmac_scope`: 개별 세션 삭제에서는 계정이 살아 있어 **다른 세션**의 바인딩이 같은 user_id로
    일치하는 것이 정상이다(그 행은 삭제 대상이 아니다). 그래서 ⓑ를 삭제한 세션 ID의 행으로 좁힌다.
    계정 삭제에서는 None(전 행 대상) — 계정이 사라졌으므로 어떤 행도 일치해선 안 된다.
    """
    settings = _settings()
    async with async_sessionmaker(engine)() as db:
        rows = (
            await db.execute(
                select(
                    EvidenceEvent.event_id,
                    EvidenceEvent.session_id,
                    EvidenceEvent.meta[META_KEY_USER_BINDING].astext,
                )
            )
        ).all()
    hits = 0
    for _event_id, session_id, stored in rows:
        by_join = audit_resource_id is not None and session_id == audit_resource_id
        in_scope = hmac_scope is None or session_id == hmac_scope
        by_hmac = (
            in_scope
            and stored is not None
            and stored == session_user_binding(session_id, audit_user_id, settings=settings)
        )
        if by_join or by_hmac:
            hits += 1
    return hits


async def _audit_keys(engine: AsyncEngine, uid: uuid.UUID) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """실제 `deletion_audit` 행에서 (user_id, resource_id)를 읽는다 — 키를 테스트가 지어내지 않는다."""
    async with async_sessionmaker(engine)() as db:
        audits = (
            (await db.execute(select(DeletionAudit).where(DeletionAudit.user_id == uid)))
            .scalars()
            .all()
        )
        return [(a.user_id, a.resource_id) for a in audits]


async def _load_user(engine: AsyncEngine, uid: uuid.UUID) -> UserProfile:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        user = await db.get(UserProfile, uid)
        assert user is not None
        return user


# ===========================================================================
# 경로 ⓑ — 계정 삭제(`DELETE /v1/me`)
# ===========================================================================


class TestAccountErasureRelink:
    async def test_no_evidence_event_is_relinkable_after_account_erasure(
        self, engine: AsyncEngine, world: _World
    ) -> None:
        victim = await world.new_user()
        control = await world.new_user()
        v_learning = await world.new_learning_session_with_recommendation(victim)
        v_pedagogy = await world.new_pedagogy_pair(victim)  # 학습 세션이 아닌 임의 UUID
        c_learning = await world.new_learning_session_with_recommendation(control)
        c_pedagogy = await world.new_pedagogy_pair(control)

        # 사전 — 검사기가 실제로 찾는다(대조군·피해자 모두): 항상 0을 내는 위장 검사가 아님.
        assert await _evidence_rows(engine, [v_learning, v_pedagogy]) == 3  # 추천1 + 처치·결과
        assert await _relinkable_rows(engine, audit_user_id=victim, audit_resource_id=victim) == 1
        assert await _relinkable_rows(engine, audit_user_id=control, audit_resource_id=control) == 1

        user = await _load_user(engine, victim)
        async with async_sessionmaker(engine)() as db:
            await erase_my_account(
                AccountErasureRequest(confirmation=_CONFIRM), user, db, _settings()
            )

        # 삭제 증빙의 실제 키로 재연결 시도 — 0건이어야 한다.
        keys = await _audit_keys(engine, victim)
        assert keys, "삭제 증빙이 남아 있어야 한다(전제 — 이 키가 재연결 시도의 출발점)."
        for audit_user, resource in keys:
            assert (
                await _relinkable_rows(engine, audit_user_id=audit_user, audit_resource_id=resource)
                == 0
            ), "삭제 증빙의 (user_id, resource_id)로 evidence_event가 다시 찾아진다(재연결 가능)."
        # 직접 확인 — 피해자 세션 ID로 남은 행이 0.
        assert await _evidence_rows(engine, [v_learning, v_pedagogy]) == 0

        # 대조군 — 다른 학생의 행은 그대로이고, 같은 재연결 계산이 그 행은 여전히 찾는다.
        assert await _evidence_rows(engine, [c_learning, c_pedagogy]) == 3
        assert await _relinkable_rows(engine, audit_user_id=control, audit_resource_id=control) == 1

    async def test_account_erasure_is_atomic_when_a_later_step_fails(
        self, engine: AsyncEngine, world: _World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """증빙 삭제 *뒤*에 실패해도(= 같은 트랜잭션) 롤백되어 아무것도 지워지지 않는다."""
        victim = await world.new_user()
        v_learning = await world.new_learning_session_with_recommendation(victim)
        v_pedagogy = await world.new_pedagogy_pair(victim)

        def _boom(_uid: uuid.UUID) -> Any:
            raise RuntimeError("의도된 실패 — 삭제 이후 단계")

        monkeypatch.setattr(erasure, "external_erasure_targets", _boom)
        user = await _load_user(engine, victim)
        async with async_sessionmaker(engine)() as db:
            with pytest.raises(RuntimeError):
                await erase_my_account(
                    AccountErasureRequest(confirmation=_CONFIRM), user, db, _settings()
                )
            await db.rollback()

        # 부분 삭제 0 — 증빙·세션·계정 전부 그대로.
        assert await _evidence_rows(engine, [v_learning, v_pedagogy]) == 3
        async with async_sessionmaker(engine)() as db:
            assert await db.get(UserProfile, victim) is not None
            owned = await db.scalar(
                select(func.count())
                .select_from(LearningSession)
                .where(LearningSession.user_id == victim)
            )
            assert owned == 1
        assert await _audit_keys(engine, victim) == []  # 감사 행도 같은 트랜잭션이라 롤백


# ===========================================================================
# 경로 ⓐ — 개별 세션 삭제(`DELETE /v1/me/sessions/{id}`)
# ===========================================================================


class TestSessionDeletionRelink:
    async def test_no_evidence_event_is_relinkable_after_session_deletion(
        self, engine: AsyncEngine, world: _World
    ) -> None:
        owner = await world.new_user()
        other = await world.new_user()
        s_gone = await world.new_learning_session_with_recommendation(owner)
        # 같은 세션 ID로 교수법 처치·결과도 있는 경우 — 저장된 HMAC(s_gone, owner)가 존재해야
        # 바인딩 재계산 검사가 공허하지 않다(실 `/study`는 임의 UUID라 이 겹침은 인위적이다).
        await world.new_pedagogy_pair(owner, session_id=s_gone)
        s_kept = await world.new_learning_session_with_recommendation(owner)  # 같은 학생·다른 세션
        p_kept = await world.new_pedagogy_pair(
            owner
        )  # 같은 학생의 임의 UUID 처치(세션 삭제 대상 아님)
        o_session = await world.new_learning_session_with_recommendation(other)  # 다른 학생

        # 사전 — 재연결 계산이 실제로 찾는다.
        assert await _evidence_rows(engine, [s_gone]) == 3  # 추천1 + 처치·결과
        assert (
            await _relinkable_rows(
                engine, audit_user_id=owner, audit_resource_id=s_gone, hmac_scope=s_gone
            )
            == 3
        )

        user = await _load_user(engine, owner)
        async with async_sessionmaker(engine)() as db:
            await delete_my_session(s_gone, user, db)

        keys = await _audit_keys(engine, owner)
        assert (owner, s_gone) in keys, "삭제 증빙이 (소유자, 세션 ID)를 남겨야 한다(전제)."
        for audit_user, resource in keys:
            if resource != s_gone:
                continue
            assert (
                await _relinkable_rows(
                    engine,
                    audit_user_id=audit_user,
                    audit_resource_id=resource,
                    hmac_scope=resource,
                )
                == 0
            ), "삭제 증빙의 (user_id, resource_id)로 evidence_event가 다시 찾아진다(재연결 가능)."
        assert await _evidence_rows(engine, [s_gone]) == 0

        # 대조군 — 같은 학생의 다른 세션·임의 UUID 처치·다른 학생의 세션은 그대로다.
        assert await _evidence_rows(engine, [s_kept]) == 1
        assert await _evidence_rows(engine, [p_kept]) == 2
        assert await _evidence_rows(engine, [o_session]) == 1
        assert (
            await _relinkable_rows(
                engine, audit_user_id=owner, audit_resource_id=s_kept, hmac_scope=p_kept
            )
            == 2
        ), "대조군을 재연결 계산이 못 찾는다 — 검사기가 위장이다(s_kept 조인 1 + p_kept 바인딩 1)."

    async def test_foreign_session_id_deletes_nothing(
        self, engine: AsyncEngine, world: _World
    ) -> None:
        """타인의 세션 ID로 요청하면 404이고 그 세션의 증빙 행은 하나도 지워지지 않는다."""
        owner = await world.new_user()
        intruder = await world.new_user()
        sid = await world.new_learning_session_with_recommendation(owner)

        user = await _load_user(engine, intruder)
        async with async_sessionmaker(engine)() as db:
            with pytest.raises(HTTPException) as excinfo:
                await delete_my_session(sid, user, db)
        assert excinfo.value.status_code == 404
        assert await _evidence_rows(engine, [sid]) == 1

    async def test_session_deletion_is_atomic_when_commit_fails(
        self, engine: AsyncEngine, world: _World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """커밋이 실패하면 세션·증빙이 함께 남는다 — 증빙만 지워진 부분 삭제 상태가 없다."""
        owner = await world.new_user()
        sid = await world.new_learning_session_with_recommendation(owner)

        user = await _load_user(engine, owner)
        async with async_sessionmaker(engine)() as db:

            async def _failing_commit() -> None:
                raise RuntimeError("의도된 실패 — 커밋 단계")

            monkeypatch.setattr(db, "commit", _failing_commit)
            with pytest.raises(RuntimeError):
                await delete_my_session(sid, user, db)
            await db.rollback()

        assert await _evidence_rows(engine, [sid]) == 1
        async with async_sessionmaker(engine)() as db:
            assert await db.get(LearningSession, sid) is not None
        assert await _audit_keys(engine, owner) == []


# ===========================================================================
# attempt_event 처분 판정의 전제 핀 (SEC-40 acceptance ②) — 실 DB로 '유지' 판정의 전제를 동결
# ===========================================================================


async def test_attempt_event_remains_after_session_deletion_and_has_no_session_axis(
    engine: AsyncEngine, world: _World
) -> None:
    """판정 '유지'의 전제를 실 DB로 동결한다 — 삭제된 세션 ID로는 attempt_event를 찾을 수 없다.

    `attempt_event`에는 세션 컬럼이 없고(`attempt_id`·`user_id`·`problem_id`뿐), 시도↔세션 연결은
    `problem_attempt` 행에만 있으며 그 행은 세션 삭제의 CASCADE로 사라진다. 그래서 `evidence_event`와
    달리 삭제 증빙의 (user_id, resource_id=세션 ID)로 재연결할 키가 구조적으로 없다 — 이 전제가
    깨지면(세션 컬럼이 생기면) 처분을 다시 판정해야 한다(보고서 §4).
    """
    columns = {c.key for c in AttemptEvent.__table__.columns}  # type: ignore[attr-defined]
    assert not any(
        name == "session_id" or name.endswith("_session_id") for name in columns
    ), "attempt_event에 세션 컬럼이 생겼다 — 세션 삭제 처분(SEC-40 §4)을 다시 판정하라."

    owner = await world.new_user()
    sid = await world.new_learning_session_with_recommendation(owner)
    async with async_sessionmaker(engine)() as db:
        db.add(
            AttemptEvent(
                event_at=datetime.now(UTC), user_id=owner, attempt_id=uuid.uuid4(), event_type=None
            )
        )
        await db.commit()

    user = await _load_user(engine, owner)
    async with async_sessionmaker(engine)() as db:
        await delete_my_session(sid, user, db)

    async with async_sessionmaker(engine)() as db:
        remaining = await db.scalar(
            select(func.count()).select_from(AttemptEvent).where(AttemptEvent.user_id == owner)
        )
    assert remaining == 1, "판정 '유지'가 바뀌었다 — 보고서 §4와 이 단언을 함께 갱신하라."
