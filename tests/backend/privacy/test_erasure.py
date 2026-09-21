"""개인정보 삭제권 오케스트레이션(`privacy/erasure.py`) — 단위(hermetic) + 실 PG 통합.

단위(FakeSession): 삭제 *순서*(자식→부모·user_profile 마지막)·감사 적재(user_profile 삭제 전)·
보고서 집계를 DB 없이 검증한다. ★실제 삭제(NO ACTION FK가 막던 테이블 제거·CASCADE 자식·느슨참조
고아 제거·user_profile 삭제·DeletionAudit 잔존)는 *실 PG 통합테스트*가 왕복 검증한다.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from _external_store_evidence import (
    KNOWN_UNDEPLOYED_STORES,
    assert_manifest_stores_are_deployed,
    evidence_for,
)
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.db.models.audit import DeletionAudit
from whymath_backend.db.models.dialogue import Dialogue, DialogueTurn
from whymath_backend.db.models.user import UserProfile
from whymath_backend.l4.misconception.evidence_store import get_evidence_for_student, log_evidence
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.misconception.hypothesis_store import (
    get_active_hypotheses,
    persist_hypotheses,
)
from whymath_backend.privacy.erasure import (
    _ERASURE_PLAN,
    ErasureReport,
    ExternalErasureTarget,
    erase_user,
    external_erasure_targets,
)
from whymath_backend.schema.dialogue import Dialogue as DialogueSchema
from whymath_backend.schema.dialogue import DialogueTurn as DialogueTurnSchema
from whymath_backend.schema.enums import ContentType, Persona, TurnRole
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_MID = "distribution-over-power"  # 실 카탈로그 id(log_evidence 게이트 통과용)


# ===========================================================================
# 단위 (hermetic·FakeSession) — 삭제 순서·감사·보고서
# ===========================================================================


class _FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeSession:
    """delete 실행 순서·add(감사)·flush를 캡처(이벤트 로그). execute는 fake rowcount 반환."""

    def __init__(self, default_rowcount: int = 1) -> None:
        self.events: list[tuple[str, Any]] = []
        self.default_rowcount = default_rowcount
        self.flushed = 0

    async def execute(self, stmt: Any) -> _FakeResult:
        self.events.append(("delete", stmt.table.name))
        return _FakeResult(self.default_rowcount)

    def add(self, obj: Any) -> None:
        self.events.append(("add", obj))

    async def flush(self) -> None:
        self.flushed += 1


def _delete_order(session: _FakeSession) -> list[str]:
    return [v for kind, v in session.events if kind == "delete"]


class TestEraseOrchestration:
    def test_user_profile_deleted_last(self) -> None:
        """user_profile은 모든 자식 삭제 후 *마지막*에 삭제(FK 위반 방지)."""
        session = _FakeSession()
        asyncio.run(erase_user(cast(AsyncSession, session), user_id=uuid.uuid4()))
        order = _delete_order(session)
        assert order[-1] == "user_profile"

    def test_fk_dependency_order(self) -> None:
        """dialogue→problem_attempt→learning_session 순서(FK 의존 안전)."""
        session = _FakeSession()
        asyncio.run(erase_user(cast(AsyncSession, session), user_id=uuid.uuid4()))
        order = _delete_order(session)
        assert order.index("dialogue") < order.index("problem_attempt")
        assert order.index("problem_attempt") < order.index("learning_session")

    def test_covers_all_planned_tables(self) -> None:
        """계획된 17개 테이블 전부 + user_profile 삭제(누락 0)."""
        session = _FakeSession()
        asyncio.run(erase_user(cast(AsyncSession, session), user_id=uuid.uuid4()))
        order = set(_delete_order(session))
        planned = {m.__tablename__ for m, _ in _ERASURE_PLAN}
        assert planned <= order  # 모든 계획 테이블 포함
        assert "user_profile" in order
        # 민감 데이터 핵심 — 증거·가설·BKT·θ·행동 로그·대화 포함.
        for tn in (
            "evidence_links",
            "misconception_hypothesis",
            "concept_mastery_history",
            "ability_snapshot",
            "attempt_event",
            "dialogue",
        ):
            assert tn in order

    def test_audit_recorded_before_user_profile_delete(self) -> None:
        """DeletionAudit는 user_profile 삭제 *전* 적재(user_id 살아있을 때·잔존 증빙)."""
        session = _FakeSession()
        uid = uuid.uuid4()
        asyncio.run(erase_user(cast(AsyncSession, session), user_id=uid))
        add_pos = next(i for i, (k, _) in enumerate(session.events) if k == "add")
        up_pos = next(
            i for i, (k, v) in enumerate(session.events) if k == "delete" and v == "user_profile"
        )
        assert add_pos < up_pos
        audit = session.events[add_pos][1]
        assert isinstance(audit, DeletionAudit)
        assert audit.user_id == uid
        assert audit.resource_type == "user_profile"
        assert audit.resource_id == uid

    def test_report_aggregates_counts(self) -> None:
        """보고서 — 테이블별 행수·user_profile 행수·총합·flush 1회."""
        session = _FakeSession(default_rowcount=2)
        uid = uuid.uuid4()
        report = asyncio.run(erase_user(cast(AsyncSession, session), user_id=uid))
        assert isinstance(report, ErasureReport)
        assert report.user_id == uid
        assert set(report.deleted_counts) == {m.__tablename__ for m, _ in _ERASURE_PLAN}
        assert all(c == 2 for c in report.deleted_counts.values())
        assert report.user_profile_deleted == 2
        assert report.total_rows_deleted == 2 * len(_ERASURE_PLAN) + 2
        assert session.flushed == 1

    def test_idempotent_when_nothing_to_delete(self) -> None:
        """이미 없는 사용자 → 전부 0행·user_profile_deleted=0(무해)·감사는 여전히 적재."""
        session = _FakeSession(default_rowcount=0)
        report = asyncio.run(erase_user(cast(AsyncSession, session), user_id=uuid.uuid4()))
        assert report.total_rows_deleted == 0
        assert report.user_profile_deleted == 0


class TestExternalErasureManifest:
    """외부 store(RDB 밖) 삭제 누락을 구조화·정직히 명시(GDPR 범위·날조 0).

    SEC-32 이전 이 클래스는 `{"clickhouse", "s3", "redis"}`라는 **하드코딩 집합**과의 일치만
    봤다 — 그 집합이 사실인지는 묻지 않아, 도입된 적 없는 store 2종을 3년치 회귀 테스트가
    *동결*하고 있었다. 이제는 **계약**으로 본다: 선언된 store는 배포 근거(설정 키 또는 compose
    서비스)로 실재가 확인돼야 한다. 근거 조회는 `_external_store_evidence`가 산출물
    (`Settings.model_fields`·파싱된 compose)에서 직접 수행한다(소스 grep 아님 — 표기 변형·
    주석·슬라이스 라벨에 속지 않는다).
    """

    def test_declared_stores_are_actually_deployed(self) -> None:
        """선언된 store 전부에 배포 근거가 있다 — 허위 선언 차단(계약 본체)."""
        targets = external_erasure_targets(uuid.uuid4())
        assert_manifest_stores_are_deployed(
            (t.store for t in targets), source="external_erasure_targets"
        )
        assert all(isinstance(t, ExternalErasureTarget) for t in targets)
        assert all(t.data and t.reason for t in targets)  # 설명·이유 비지 않음

    def test_undeployed_stores_are_not_declared(self) -> None:
        """미도입 store(ClickHouse·S3)는 매니페스트에 없다 — 없는 곳을 적으면 집행 불가 항목이 된다."""
        declared = {t.store for t in external_erasure_targets(uuid.uuid4())}
        for store in KNOWN_UNDEPLOYED_STORES:
            assert store not in declared, (
                f"'{store}'는 이 저장소에 도입된 적이 없다(설정 키 0·compose 서비스 0). "
                "실제로 도입했다면 이 테스트가 아니라 매니페스트·근거 상수를 갱신하라."
            )

    def test_langfuse_is_declared(self) -> None:
        """실 반출처 Langfuse가 등재돼 있다 — *누락*이 허위 선언보다 중대하다(SEC-32).

        Langfuse는 학생 요청마다 라우팅 트레이스를 외부 SaaS로 보낸다. 매니페스트에 없으면
        "우리 DB 밖으로 나가는 학생 유래 데이터가 없다"고 주장하는 것과 같다.
        """
        declared = {t.store for t in external_erasure_targets(uuid.uuid4())}
        assert "langfuse" in declared
        assert evidence_for("langfuse"), "Langfuse 배선 근거(설정 키·compose env)가 사라졌다"

    def test_locators_reference_user_id(self) -> None:
        """locator는 *그 user* 대상을 가리킨다(per-user actionable·체크리스트)."""
        uid = uuid.uuid4()
        targets = external_erasure_targets(uid)
        assert all(str(uid) in t.locator for t in targets)

    def test_targets_are_frozen(self) -> None:
        """대상은 불변(매니페스트 변조 방지)."""
        target = external_erasure_targets(uuid.uuid4())[0]
        with pytest.raises(ValidationError):
            target.store = "tampered"  # type: ignore[misc]

    def test_erase_user_report_carries_pending_external(self) -> None:
        """`erase_user` 결과가 외부 store 매니페스트를 담는다(조용한 누락 0)."""
        session = _FakeSession()
        uid = uuid.uuid4()
        report = asyncio.run(erase_user(cast(AsyncSession, session), user_id=uid))
        assert report.pending_external == external_erasure_targets(uid)
        # 개수를 상수로 박지 않는다 — store가 늘고 주는 것은 정상이고, *실재하는가*만이 계약이다.
        assert report.pending_external
        assert any(k == "add" for k, _ in session.events)  # 삭제 *시도* 증빙


# ===========================================================================
# 통합 (실 PG·기본 SKIP) — load→seed→erase→reload 왕복
# ===========================================================================

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


def _build_user(user_id: uuid.UUID) -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(
            user_id=user_id,
            persona_primary=Persona.A_일반고고3,
            nickname="삭제학생",
            email_hash=f"HASH-{user_id.hex[:8]}",
            is_minor=True,
        )
    )


async def _cleanup(user_id: uuid.UUID, dialogue_id: uuid.UUID) -> None:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.begin() as conn:
            for tbl, col in (
                ("dialogue_turn", "dialogue_id"),
                ("evidence_links", "student_id"),
                ("misconception_hypothesis", "user_id"),
                ("dialogue", "user_id"),
                ("deletion_audit", "user_id"),
                ("user_profile", "user_id"),
            ):
                key = str(dialogue_id) if col == "dialogue_id" else str(user_id)
                await conn.execute(text(f"DELETE FROM {tbl} WHERE {col} = :k"), {"k": key})
    finally:
        await engine.dispose()


@pytest.mark.integration
def test_erase_user_removes_all_linked_data_on_live_pg() -> None:
    """삭제권 — NO ACTION FK(가설)·CASCADE(증거)·자식 cascade(대화 턴) 전부 제거·감사 잔존."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()
    sid = uuid.uuid4()
    did = uuid.uuid4()

    async def _seed(sm: async_sessionmaker[AsyncSession]) -> None:
        async with sm() as session:
            session.add(_build_user(uid))
            await session.commit()
        async with sm() as session:
            # CASCADE FK — 증거 그래프 2건.
            await log_evidence(
                session,
                session_id=sid,
                student_id=uid,
                misconception_id=_MID,
                polarity=1,
                weight=1.0,
            )
            await log_evidence(
                session,
                session_id=sid,
                student_id=uid,
                misconception_id=_MID,
                polarity=-1,
            )
            # NO ACTION FK(이게 user_profile 삭제를 막던 테이블) — 활성 가설 1건.
            await persist_hypotheses(
                session,
                uid,
                [
                    MisconceptionHypothesis(
                        misconception_id="mc-erase-x",
                        confidence=0.7,
                        turns_since_evidence=0,
                        evidence_count=1,
                    )
                ],
            )
            # 대화 + 자식 턴(턴은 dialogue CASCADE로 사라져야 함).
            session.add(
                Dialogue.from_schema(
                    DialogueSchema(
                        dialogue_id=did,
                        user_id=uid,
                        total_turns=1,
                        student_turns=1,
                        assistant_turns=0,
                    )
                )
            )
            await session.flush()
            session.add(
                DialogueTurn.from_schema(
                    DialogueTurnSchema(
                        dialogue_id=did,
                        turn_order=1,
                        role=TurnRole.student,
                        content="안녕하세요",
                        content_type=ContentType.텍스트,
                        spoken_at=datetime.now(UTC),
                    )
                )
            )
            await session.commit()

    async def _run() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            sm = async_sessionmaker(engine, expire_on_commit=False)
            await _seed(sm)

            async with sm() as session:
                report = await erase_user(session, user_id=uid)
                await session.commit()  # commit은 호출자
                assert report.user_profile_deleted == 1
                assert report.deleted_counts["evidence_links"] == 2
                assert report.deleted_counts["misconception_hypothesis"] == 1
                assert report.deleted_counts["dialogue"] == 1

            # 재로드 — 전부 사라지고 user도 없음. 감사만 잔존.
            async with sm() as session:
                assert await session.get(UserProfile, uid) is None
                assert await get_active_hypotheses(session, uid) == []
                assert await get_evidence_for_student(session, uid) == []
                assert await session.get(Dialogue, did) is None
                turns = (
                    (
                        await session.execute(
                            select(DialogueTurn).where(DialogueTurn.dialogue_id == did)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert list(turns) == []  # dialogue CASCADE로 제거
                # ★삭제권 증빙 — DeletionAudit는 사용자 삭제 후에도 잔존.
                audits = (
                    (
                        await session.execute(
                            select(DeletionAudit).where(DeletionAudit.user_id == uid)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(audits) == 1
                assert audits[0].resource_type == "user_profile"
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup(uid, did))
