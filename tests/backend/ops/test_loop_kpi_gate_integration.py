"""학습 루프 KPI 게이트(`ops/loop_kpi_gate.py`, EOS-15) — 실 PostgreSQL 주입 변별력 통합테스트.

`WHYMATH_RUN_INTEGRATION=1` + 살아있는 PG(마이그레이션 head 적용)에서만 실행한다(conftest
게이트가 CI 기본 skip · `test_integrity_violations_gate_integration.py` 패턴 미러).

hermetic 스위트(`test_loop_kpi_gate.py`)는 *판정기*가 관측치에 반응하는지를 본다. 이 파일은
그 앞단, **수집기가 실 스키마에서 옳은 숫자를 세는지**를 본다 — 둘은 다른 실패 모드다:
판정기가 완벽해도 수집 쿼리가 엉뚱한 행을 세면 게이트는 조용히 틀린다.

각 KPI를 3단 왕복으로 증명한다: ①주입 전 — 위반 0(오탐 아님) ②주입 후 — 위반 검출
③정리 후 — 다시 0(잔존 없음). 같은 DB를 다른 통합테스트가 공유하므로 전역 판정이 아니라
**이 테스트가 심은 행의 증감(delta)**으로 단언한다(격리·재현성).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.l2 import learning_event_trace as trace
from whymath_backend.ops import loop_kpi_gate as gate

pytestmark = pytest.mark.integration

_RUN_TAG = uuid.uuid4().hex[:8]


async def _pg_reachable() -> bool:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not await _pg_reachable():
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    engine = create_async_engine(Settings().database_url)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def window() -> gate.ObservationWindow:
    now = datetime.now(UTC)
    # 끝점을 조금 미래로 둔다 — `now()`로 심은 행이 경계 밖으로 떨어지지 않게.
    return gate.ObservationWindow(start=now - timedelta(hours=1), end=now + timedelta(minutes=5))


async def _knowledge_type(session: AsyncSession) -> str:
    """`knowledge_type` enum의 아무 라벨 — 이 테스트의 관심사가 아니라 NOT NULL 충족용이다.

    SQL 안에 서브쿼리로 끼워 넣지 않고 파이썬으로 먼저 해소한다 — 중첩 캐스팅은 괄호 하나만
    어긋나도 조용히 다른 문장이 되고, 그 오류는 트랜잭션을 중단시켜 *정리 구문까지* 삼킨다
    (2026-09-19 실측: cleanup의 DELETE가 InFailedSQLTransactionError로 죽어 픽스처가 남았다).
    """
    return str(
        (
            await session.execute(
                text(
                    "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid"
                    " WHERE t.typname = 'knowledge_type' LIMIT 1"
                )
            )
        ).scalar_one()
    )


class TestExplainabilityDiscrimination:
    """KPI③ — reason 없는 추천이 실제로 분자로 잡히는가."""

    async def test_reason_present_is_not_counted_and_missing_is(
        self, db_session: AsyncSession, window: gate.ObservationWindow
    ) -> None:
        objective = f"kpi3-{_RUN_TAG}"
        ktype = await _knowledge_type(db_session)
        insert = text(
            "INSERT INTO evidence_event (time, session_id, objective_id, k_type, event_type,"
            " meta) VALUES (now(), gen_random_uuid(), :o, CAST(:k AS knowledge_type),"
            " 'recommendation_render', CAST(:m AS jsonb))"
        )
        try:
            # ① 정상 — reason이 실린 추천 3건은 분자에 들어가지 않는다(성공 방향 대조군).
            before = await gate.collect_explainability(db_session, window)
            for _ in range(3):
                await db_session.execute(
                    insert,
                    {"o": objective, "k": ktype, "m": '{"reason": {"kind": "weak_concept"}}'},
                )
            await db_session.commit()
            clean = await gate.collect_explainability(db_session, window)
            assert clean.denominator == (before.denominator or 0) + 3
            assert clean.numerator == before.numerator

            # ② 주입 — reason 없는 추천 1건이 분자를 정확히 1 올린다.
            await db_session.execute(
                insert, {"o": objective, "k": ktype, "m": '{"problem_id": "p1"}'}
            )
            await db_session.commit()
            dirty = await gate.collect_explainability(db_session, window)
            assert dirty.numerator == (clean.numerator or 0) + 1

            # 무관용 축이므로 1건이면 판정이 뒤집힌다.
            report = gate.evaluate({dirty.kpi: dirty}, window=window, run_id="it")
            verdict = next(o for o in report.outcomes if o.kpi is dirty.kpi)
            assert verdict.verdict is gate.KpiVerdict.failed
        finally:
            await db_session.execute(
                text("DELETE FROM evidence_event WHERE objective_id = :o"), {"o": objective}
            )
            await db_session.commit()

        # ③ 정리 후 — 잔존 없음.
        restored = await gate.collect_explainability(db_session, window)
        assert restored.numerator == before.numerator
        assert restored.denominator == before.denominator

    async def test_null_meta_counts_as_missing_reason(
        self, db_session: AsyncSession, window: gate.ObservationWindow
    ) -> None:
        """meta 자체가 NULL인 추천도 '이유 없음'이다 — 키 부재만 보면 이 행이 샌다."""
        objective = f"kpi3-null-{_RUN_TAG}"
        ktype = await _knowledge_type(db_session)
        try:
            before = await gate.collect_explainability(db_session, window)
            await db_session.execute(
                text(
                    "INSERT INTO evidence_event (time, session_id, objective_id, k_type,"
                    " event_type, meta) VALUES (now(), gen_random_uuid(), :o,"
                    " CAST(:k AS knowledge_type), 'recommendation_render', NULL)"
                ),
                {"o": objective, "k": ktype},
            )
            await db_session.commit()
            after = await gate.collect_explainability(db_session, window)
            assert after.numerator == (before.numerator or 0) + 1
        finally:
            await db_session.execute(
                text("DELETE FROM evidence_event WHERE objective_id = :o"), {"o": objective}
            )
            await db_session.commit()

    async def test_json_null_reason_counts_as_missing(
        self, db_session: AsyncSession, window: gate.ObservationWindow
    ) -> None:
        """`{"reason": null}`은 "이유 있음"이 아니다 — `->`로 보면 이 행이 조용히 샌다.

        JSONB에서 `meta -> 'reason'`은 JSON null을 *값이 있는 것*으로 돌려주므로 `IS NULL`이
        거짓이 된다. `->>`(astext)만이 키 부재와 JSON null을 함께 접는다. 우리 writer는 지금
        이 모양을 만들지 않지만, 게이트가 **막아야 하는 상태**를 writer의 현재 습관에 기대어
        정의하면 그 습관이 바뀌는 날 조용히 뚫린다.
        """
        objective = f"kpi3-jsonnull-{_RUN_TAG}"
        ktype = await _knowledge_type(db_session)
        try:
            before = await gate.collect_explainability(db_session, window)
            await db_session.execute(
                text(
                    "INSERT INTO evidence_event (time, session_id, objective_id, k_type,"
                    " event_type, meta) VALUES (now(), gen_random_uuid(), :o,"
                    " CAST(:k AS knowledge_type), 'recommendation_render',"
                    " '{\"reason\": null}'::jsonb)"
                ),
                {"o": objective, "k": ktype},
            )
            await db_session.commit()
            after = await gate.collect_explainability(db_session, window)
            assert after.numerator == (before.numerator or 0) + 1
        finally:
            await db_session.execute(
                text("DELETE FROM evidence_event WHERE objective_id = :o"), {"o": objective}
            )
            await db_session.commit()


class TestManualInterventionDiscrimination:
    """KPI④ — 운영자 감사만 세고 학생 본인 행위는 세지 않는가."""

    async def test_operator_audit_counts_but_student_own_action_does_not(
        self, db_session: AsyncSession, window: gate.ObservationWindow
    ) -> None:
        actor = uuid.uuid4()
        try:
            before = await gate.collect_manual_intervention(db_session, window)

            # ① 학생 본인 행위(반출)는 개입이 아니다 — 세면 정상 시나리오가 위반이 된다.
            await db_session.execute(
                text("INSERT INTO privacy_audit (user_id, event_kind) VALUES (:u, 'export_data')"),
                {"u": actor},
            )
            await db_session.commit()
            clean = await gate.collect_manual_intervention(db_session, window)
            assert clean.numerator == before.numerator

            # ② 운영자 역할변경은 개입이다.
            await db_session.execute(
                text("INSERT INTO privacy_audit (user_id, event_kind) VALUES (:u, 'role_change')"),
                {"u": actor},
            )
            await db_session.commit()
            dirty = await gate.collect_manual_intervention(db_session, window)
            assert dirty.numerator == (clean.numerator or 0) + 1
        finally:
            await db_session.execute(
                text("DELETE FROM privacy_audit WHERE user_id = :u"), {"u": actor}
            )
            await db_session.commit()

        restored = await gate.collect_manual_intervention(db_session, window)
        assert restored.numerator == before.numerator

    async def test_attempts_form_the_denominator(
        self, db_session: AsyncSession, window: gate.ObservationWindow
    ) -> None:
        """분모가 없으면 '개입 0'이 통과인지 무활동인지 구분되지 않는다."""
        try:
            before = await gate.collect_manual_intervention(db_session, window)
            await db_session.execute(
                text(
                    "INSERT INTO problem_attempt (attempt_id, ingested_at, is_correct)"
                    " VALUES (:a, now(), true)"
                ),
                {"a": uuid.uuid5(uuid.NAMESPACE_URL, f"kpi4-{_RUN_TAG}")},
            )
            await db_session.commit()
            after = await gate.collect_manual_intervention(db_session, window)
            assert after.denominator == (before.denominator or 0) + 1
        finally:
            await db_session.execute(
                text("DELETE FROM problem_attempt WHERE attempt_id = :a"),
                {"a": uuid.uuid5(uuid.NAMESPACE_URL, f"kpi4-{_RUN_TAG}")},
            )
            await db_session.commit()


class TestStateIntegrityDelegation:
    """KPI② — 기존 무결성 게이트의 산출을 그대로 읽는가(재구현하지 않았다는 증거)."""

    async def test_observation_matches_the_integrity_gate_report(
        self, db_session: AsyncSession, window: gate.ObservationWindow
    ) -> None:
        from whymath_backend.ops import integrity_violations_gate

        report = await integrity_violations_gate.scan_integrity(db_session)
        observation = await gate.collect_state_integrity(db_session, window)
        assert observation.numerator == len(report.violations)
        assert observation.denominator == sum(report.scanned.values())


class TestLoopCompletionOnceTheSessionAxisIsWired:
    """KPI① — 원천 대장이 PRODUCED가 되면 조인이 실제로 도는가(설계 주장의 실 DB 검증)."""

    async def test_join_counts_only_sessions_that_reached_a_recommendation(
        self,
        db_session: AsyncSession,
        window: gate.ObservationWindow,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            gate,
            "source_registry",
            lambda: tuple(
                c.model_copy(update={"availability": trace.SourceAvailability.PRODUCED})
                for c in trace.source_registry()
            ),
        )
        assert gate.blocked_preconditions(gate.LoopKpi.LOOP_COMPLETION) == ()

        reached = [uuid.uuid4() for _ in range(3)]
        missed = [uuid.uuid4() for _ in range(2)]
        objective = f"kpi1-{_RUN_TAG}"
        ktype = await _knowledge_type(db_session)
        try:
            before = await gate.collect_loop_completion(db_session, window)
            for session_id in reached + missed:
                await db_session.execute(
                    text(
                        "INSERT INTO learning_session (session_id, started_at)"
                        " VALUES (:s, now())"
                    ),
                    {"s": session_id},
                )
            for session_id in reached:
                await db_session.execute(
                    text(
                        "INSERT INTO evidence_event (time, session_id, objective_id, k_type,"
                        " event_type, meta) VALUES (now(), :s, :o,"
                        " CAST(:k AS knowledge_type), 'recommendation_render',"
                        " '{\"reason\": {}}'::jsonb)"
                    ),
                    {"s": session_id, "o": objective, "k": ktype},
                )
            await db_session.commit()

            after = await gate.collect_loop_completion(db_session, window)
            assert after.denominator == (before.denominator or 0) + 5
            assert after.numerator == (before.numerator or 0) + 3
        finally:
            for session_id in reached + missed:
                await db_session.execute(
                    text("DELETE FROM learning_session WHERE session_id = :s"), {"s": session_id}
                )
            await db_session.execute(
                text("DELETE FROM evidence_event WHERE objective_id = :o"), {"o": objective}
            )
            await db_session.commit()


class TestSchemaSmoke:
    """스키마 스모크 — 5종 수집기가 실 스키마를 상대로 예외 없이 완주하는가(CI 배선 축)."""

    async def test_every_collector_completes_against_the_live_schema(
        self, db_session: AsyncSession, window: gate.ObservationWindow
    ) -> None:
        observations = await gate.collect_all(
            db_session,
            window,
            evidence=gate.EvidenceWriter(None, run_id="it", window=window),
        )
        assert gate.schema_smoke_failures(observations) == ()
        assert len(observations) == 5
