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

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.ops import loop_kpi_gate as gate
from whymath_backend.privacy import erasure

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
    """KPI① — EOS-131 착지 후 실제로 측정되는가, 그리고 ⑨ 재정의가 옳은 세션을 세는가.

    원천 대장은 이제 **패치 없이** `PRODUCED`다(세션 writer·추천 실 session_id 결합). 그러므로
    이 클래스는 대장을 조작하지 않는다 — 조작해야 통과한다면 그것은 착지가 아니다.

    ⑨ 실패 주입 3종(EOS-131 acceptance ⑨): 옛 정의("추천이 하나라도 있는 세션")로 되돌리면
    (가)가 RED다 — 시도 전에 나간 첫 추천만으로 '도달'이 되기 때문이다.
    """

    async def _seed_session(
        self,
        db: AsyncSession,
        *,
        started_at: datetime,
        attempt_at: datetime | None,
        rec_at: datetime | None,
        objective: str,
        ktype: str,
    ) -> uuid.UUID:
        """세션 1개 + (선택) 시도 1건(서버 수신 시각) + (선택) 추천 1건을 심는다."""
        session_id = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO learning_session (session_id, started_at, last_activity_at)"
                " VALUES (:s, :t, :t)"
            ),
            {"s": session_id, "t": started_at},
        )
        if attempt_at is not None:
            await db.execute(
                text(
                    "INSERT INTO problem_attempt (attempt_id, session_id, ingested_at)"
                    " VALUES (gen_random_uuid(), :s, :t)"
                ),
                {"s": session_id, "t": attempt_at},
            )
        if rec_at is not None:
            await db.execute(
                text(
                    "INSERT INTO evidence_event (time, session_id, objective_id, k_type,"
                    " event_type, meta) VALUES (:t, :s, :o, CAST(:k AS knowledge_type),"
                    " 'recommendation_render', '{\"reason\": {}}'::jsonb)"
                ),
                {"t": rec_at, "s": session_id, "o": objective, "k": ktype},
            )
        return session_id

    async def _cleanup(
        self, db: AsyncSession, session_ids: list[uuid.UUID], objective: str
    ) -> None:
        # problem_attempt는 session_id CASCADE로 함께 지워진다.
        for session_id in session_ids:
            await db.execute(
                text("DELETE FROM learning_session WHERE session_id = :s"), {"s": session_id}
            )
        await db.execute(
            text("DELETE FROM evidence_event WHERE objective_id = :o"), {"o": objective}
        )
        await db.commit()

    async def _delta(
        self,
        db: AsyncSession,
        window: gate.ObservationWindow,
        *,
        attempt: bool,
        rec_offset: timedelta | None,
    ) -> tuple[int, int, int]:
        """세션 1개를 심고 (분자 증감, 분모 증감, 시도 없는 세션 증감)을 돌려준다."""
        objective = f"kpi1-{_RUN_TAG}-{uuid.uuid4().hex[:6]}"
        ktype = await _knowledge_type(db)
        t0 = datetime.now(UTC) - timedelta(minutes=10)
        ids: list[uuid.UUID] = []
        try:
            before = await gate.collect_loop_completion(db, window)
            ids.append(
                await self._seed_session(
                    db,
                    started_at=t0 - timedelta(minutes=5),
                    attempt_at=t0 if attempt else None,
                    rec_at=None if rec_offset is None else t0 + rec_offset,
                    objective=objective,
                    ktype=ktype,
                )
            )
            await db.commit()
            after = await gate.collect_loop_completion(db, window)
            assert before.detail is not None and after.detail is not None
            return (
                (after.numerator or 0) - (before.numerator or 0),
                (after.denominator or 0) - (before.denominator or 0),
                after.detail["sessions_without_attempt"]
                - before.detail["sessions_without_attempt"],
            )
        finally:
            await self._cleanup(db, ids, objective)

    async def test_precondition_is_open_without_patching_the_registry(self) -> None:
        """EOS-131 ⑦(가): 대장을 건드리지 않아도 선결이 비어 있다."""
        assert gate.blocked_preconditions(gate.LoopKpi.LOOP_COMPLETION) == ()

    async def test_a_recommendation_only_before_the_first_attempt_is_not_reached(
        self, db_session: AsyncSession, window: gate.ObservationWindow
    ) -> None:
        """(가) 시도 *전* 추천만 있는 세션 → 분모엔 들어가지만 미도달. 옛 정의면 RED."""
        num, den, _ = await self._delta(
            db_session, window, attempt=True, rec_offset=-timedelta(minutes=1)
        )
        assert (num, den) == (0, 1)

    async def test_b_recommendation_after_the_first_attempt_is_reached(
        self, db_session: AsyncSession, window: gate.ObservationWindow
    ) -> None:
        """(나) 시도 *후* 추천이 있는 세션 → 도달."""
        num, den, _ = await self._delta(
            db_session, window, attempt=True, rec_offset=timedelta(minutes=1)
        )
        assert (num, den) == (1, 1)

    async def test_c_attempt_without_a_later_recommendation_is_not_reached(
        self, db_session: AsyncSession, window: gate.ObservationWindow
    ) -> None:
        """(다) 시도는 있으나 이후 추천이 없는 세션 → 미도달."""
        num, den, _ = await self._delta(db_session, window, attempt=True, rec_offset=None)
        assert (num, den) == (0, 1)

    async def test_session_without_attempt_leaves_the_denominator_but_is_reported(
        self, db_session: AsyncSession, window: gate.ObservationWindow
    ) -> None:
        """시도 없는 세션은 분모에서 빠지되 **조용히** 빠지지 않는다(detail로 보고)."""
        num, den, without = await self._delta(
            db_session, window, attempt=False, rec_offset=timedelta(minutes=1)
        )
        assert (num, den, without) == (0, 0, 1)

    async def test_m_over_n_across_mixed_sessions(
        self, db_session: AsyncSession, window: gate.ObservationWindow
    ) -> None:
        """EOS-131 ⑦(가): 세션 N건·추천 도달 M건 관측창에서 M/N이 나온다(도달 2 / 시도 세션 4)."""
        objective = f"kpi1-mn-{_RUN_TAG}"
        ktype = await _knowledge_type(db_session)
        t0 = datetime.now(UTC) - timedelta(minutes=20)
        plan = [
            (True, timedelta(minutes=1)),  # 도달
            (True, timedelta(minutes=2)),  # 도달
            (True, -timedelta(minutes=1)),  # 시도 전 추천만 — 미도달
            (True, None),  # 추천 없음 — 미도달
            (False, timedelta(minutes=1)),  # 시도 없음 — 분모 제외
        ]
        ids: list[uuid.UUID] = []
        try:
            before = await gate.collect_loop_completion(db_session, window)
            for attempt, offset in plan:
                ids.append(
                    await self._seed_session(
                        db_session,
                        started_at=t0 - timedelta(minutes=5),
                        attempt_at=t0 if attempt else None,
                        rec_at=None if offset is None else t0 + offset,
                        objective=objective,
                        ktype=ktype,
                    )
                )
            await db_session.commit()
            after = await gate.collect_loop_completion(db_session, window)
            assert (after.numerator or 0) - (before.numerator or 0) == 2
            assert (after.denominator or 0) - (before.denominator or 0) == 4
            assert after.unmeasured_reason is None
        finally:
            await self._cleanup(db_session, ids, objective)

    async def test_empty_window_is_still_unmeasured_exit_2(self, db_session: AsyncSession) -> None:
        """EOS-131 ⑦(가): 세션 0건 관측창 → 분모 0 → '0% 미달'이 아니라 미측정(exit 2)."""
        far = datetime(2100, 1, 1, tzinfo=UTC)
        empty = gate.ObservationWindow(start=far, end=far + timedelta(hours=1))
        observation = await gate.collect_loop_completion(db_session, empty)
        assert observation.denominator == 0
        assert observation.unmeasured_reason is None  # 구조적 선결 때문이 아니다
        report = gate.evaluate({observation.kpi: observation}, window=empty, run_id="it")
        outcome = next(o for o in report.outcomes if o.kpi is gate.LoopKpi.LOOP_COMPLETION)
        assert outcome.verdict is gate.KpiVerdict.unmeasured
        assert "분모가 0" in outcome.reason
        assert not report.failed  # 0건을 '미달'로 위장하지 않는다
        assert report.exit_code == gate.EXIT_UNMEASURED == 2


class TestTraceabilityOnTheLiveSchema:
    """KPI⑤ — EOS-132 착지 후 실 스키마에서 체인을 끝까지 따라가 끊김을 **홉별로** 세는가.

    다른 통합테스트와 행이 섞이지 않게 **과거 시각대의 전용 관측창**에 심는다. 근거 기록 개시는
    전역 최솟값이므로, 창 시작을 기존 근거 행보다 이르게 잡아 이 테스트의 근거 행이 개시가 되게
    한다(그래야 개시 이전 기록의 제외를 이 창 안에서 확인할 수 있다).

    심는 추천(창 안 7건): ⓐ 개시 이전 근거 없음 → 제외 ⓑ 전 홉 이어짐 ⓒ 사전값(숙달 이력 없음)
    ⓓ 개시 이후 근거 없음 ⓔ 세션 없음 ⓕ 근거 숙달 행이 1µs 어긋남 ⓖ 숙달 행에 attempt_id 없음.
    """

    async def _enum_label(self, db: AsyncSession, typname: str) -> str:
        return str(
            (
                await db.execute(
                    text(
                        "SELECT min(e.enumlabel) FROM pg_enum e JOIN pg_type t"
                        " ON t.oid = e.enumtypid WHERE t.typname = :t"
                    ),
                    {"t": typname},
                )
            ).scalar_one()
        )

    async def test_each_broken_hop_is_counted_once_and_prior_is_not_a_break(
        self, db_session: AsyncSession
    ) -> None:
        db = db_session
        earliest = (
            await db.execute(
                text(
                    "SELECT min(time) FROM evidence_event WHERE event_type = 'recommendation_render'"
                    " AND meta ? 'learner_state_basis'"
                )
            )
        ).scalar_one()
        floor = datetime(2001, 1, 1, tzinfo=UTC)
        t0 = min(floor, earliest) - timedelta(days=1) if earliest is not None else floor
        t0 = t0.replace(microsecond=0)
        window = gate.ObservationWindow(start=t0, end=t0 + timedelta(minutes=30))

        uid, sid, pid, aid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        concept, legacy_concept = uuid.uuid4(), uuid.uuid4()
        snapshot, hypothesis = uuid.uuid4(), uuid.uuid4()
        measured = t0 + timedelta(minutes=1, microseconds=123456)
        legacy_measured = t0 + timedelta(minutes=1, seconds=30)
        objective = f"kpi5-{_RUN_TAG}"
        ktype = await _knowledge_type(db)

        def basis(**override: Any) -> str:
            value: dict[str, Any] = {
                "schema": 1,
                "assembled_at": (t0 + timedelta(minutes=2)).isoformat(),
                "mastery": {"concept_id": str(concept), "measured_at": measured.isoformat()},
                "ability_snapshot": {"snapshot_id": str(snapshot)},
                "misconception_hypothesis_ids": [str(hypothesis)],
            }
            value.update(override)
            return json.dumps({"learner_state_basis": value, "reason": {}})

        plan: list[tuple[int, uuid.UUID, str]] = [
            (0, sid, '{"reason": {}}'),  # ⓐ 개시 이전 · 근거 없음 → 제외
            (2, sid, basis()),  # ⓑ 전 홉 이어짐
            (
                3,
                sid,
                basis(
                    mastery={"absent": "no_mastery_history"},
                    ability_snapshot={"absent": "no_ability_snapshot"},
                    misconception_hypothesis_ids=[],
                ),
            ),  # ⓒ 사전값 — 끊김 아님
            (4, sid, '{"reason": {}}'),  # ⓓ 개시 이후 근거 없음 → basis_missing
            (5, uuid.uuid4(), basis()),  # ⓔ 세션 행 없음 → learner_unjoined
            (
                6,
                sid,
                basis(
                    mastery={
                        "concept_id": str(concept),
                        "measured_at": (measured + timedelta(microseconds=1)).isoformat(),
                    }
                ),
            ),  # ⓕ 근거 숙달 행 없음 → assessment_missing
            (
                7,
                sid,
                basis(
                    mastery={
                        "concept_id": str(legacy_concept),
                        "measured_at": legacy_measured.isoformat(),
                    }
                ),
            ),  # ⓖ attempt_id 없는 숙달 행 → attempt_missing
        ]
        try:
            await db.execute(
                text(
                    "INSERT INTO user_profile (user_id, persona_primary) VALUES (:u, 'A_일반고고3')"
                ),
                {"u": uid},
            )
            await db.execute(
                text(
                    "INSERT INTO problem (problem_id, source_type, curriculum_version,"
                    " valid_from_year, subject, unit_codes) VALUES (:p,"
                    " CAST(:st AS source_type_enum), CAST(:cv AS curriculum_enum), 2015,"
                    " CAST(:sj AS subject_enum), '{}')"
                ),
                {
                    "p": pid,
                    "st": await self._enum_label(db, "source_type_enum"),
                    "cv": await self._enum_label(db, "curriculum_enum"),
                    "sj": await self._enum_label(db, "subject_enum"),
                },
            )
            await db.execute(
                text(
                    "INSERT INTO learning_session (session_id, user_id, started_at,"
                    " last_activity_at) VALUES (:s, :u, :t, :t)"
                ),
                {"s": sid, "u": uid, "t": t0},
            )
            await db.execute(
                text(
                    "INSERT INTO problem_attempt (attempt_id, user_id, session_id, problem_id,"
                    " is_correct, ingested_at) VALUES (:a, :u, :s, :p, false, :t)"
                ),
                {"a": aid, "u": uid, "s": sid, "p": pid, "t": measured},
            )
            await db.execute(
                text(
                    "INSERT INTO concept_mastery_history (user_id, concept_id, measured_at,"
                    " mastery, attempt_id) VALUES (:u, :c, :m, 0.30, :a),"
                    " (:u, :lc, :lm, 0.50, NULL)"
                ),
                {
                    "u": uid,
                    "c": concept,
                    "m": measured,
                    "a": aid,
                    "lc": legacy_concept,
                    "lm": legacy_measured,
                },
            )
            await db.execute(
                text(
                    "INSERT INTO ability_snapshot (snapshot_id, user_id, theta, response_count,"
                    " measured_at) VALUES (:sn, :u, 0.1, 1, :m)"
                ),
                {"sn": snapshot, "u": uid, "m": measured},
            )
            await db.execute(
                text(
                    "INSERT INTO misconception_hypothesis (id, user_id, misconception_id,"
                    " confidence) VALUES (:h, :u, :mid, 0.40)"
                ),
                {"h": hypothesis, "u": uid, "mid": f"M-{_RUN_TAG}"},
            )
            for minute, session_id, meta in plan:
                await db.execute(
                    text(
                        "INSERT INTO evidence_event (time, session_id, objective_id, k_type,"
                        " event_type, meta) VALUES (:t, :s, :o, CAST(:k AS knowledge_type),"
                        " 'recommendation_render', CAST(:m AS jsonb))"
                    ),
                    {
                        "t": t0 + timedelta(minutes=minute),
                        "s": session_id,
                        "o": objective,
                        "k": ktype,
                        "m": meta,
                    },
                )
            await db.commit()

            observation = await gate.collect_traceability(db, window)
            assert observation.unmeasured_reason is None  # 선결이 풀렸다 — 대장을 패치하지 않고
            detail = dict(observation.detail or {})
            assert detail["recommendations_in_window"] == 7
            assert detail["excluded_pre_basis"] == 1
            assert detail["traced_full"] == 1
            assert detail["traced_prior_only"] == 1
            assert detail["break_basis_missing"] == 1
            assert detail["break_learner_unjoined"] == 1
            assert detail["break_assessment_missing"] == 1
            assert detail["break_attempt_missing"] == 1
            assert (observation.numerator, observation.denominator) == (4, 6)

            report = gate.evaluate({observation.kpi: observation}, window=window, run_id="it")
            outcome = next(o for o in report.outcomes if o.kpi is gate.LoopKpi.TRACEABILITY)
            assert outcome.verdict is gate.KpiVerdict.failed  # 무관용 — 1건이면 미달
        finally:
            await db.rollback()
            await db.execute(
                text("DELETE FROM evidence_event WHERE objective_id = :o"), {"o": objective}
            )
            for table in (
                "concept_mastery_history",
                "ability_snapshot",
                "misconception_hypothesis",
            ):
                await db.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
            await db.execute(text("DELETE FROM learning_session WHERE user_id = :u"), {"u": uid})
            await db.execute(text("DELETE FROM problem_attempt WHERE user_id = :u"), {"u": uid})
            await db.execute(text("DELETE FROM problem WHERE problem_id = :p"), {"p": pid})
            await db.execute(text("DELETE FROM user_profile WHERE user_id = :u"), {"u": uid})
            await db.commit()

        # 정리 후 — 이 창에 남은 것이 없다(잔존 0).
        after = await gate.collect_traceability(db, window)
        assert dict(after.detail or {})["recommendations_in_window"] == 0


class TestTraceabilityAcrossErasure:
    """KPI⑤ × 삭제권 — 학습자 1명의 삭제가 무관용 축을 FAIL시키지 않는가(EOS-37·처분 (나)).

    EOS-141 판정(main `a82f9449`)에서 판정 하네스가 `DELETE /v1/me`로 지운 학습자의 추천 40건이
    전건 `break_learner_unjoined`로 계상돼 ⑤가 40/40 FAIL이었다. 처분 (나)(Kiki 2026-09-30)에 따라
    삭제는 그 세션의 추천 기록을 함께 지운다(SEC-40). 이 파일은 그 **결과를 수집기 쪽에서** 고정한다.

    심는 것(과거 시각대 전용 관측창): 남긴 학습자 K의 추천(전 홉 이어짐) · 지울 학습자 E의 추천(전
    홉 이어짐) · 세션 기록 실패 placeholder(세션 행 없음). 실제 삭제 경로 `erasure.erase_user`로 E를
    지운 뒤 같은 창을 다시 잰다. 실행 전·후를 한 테스트에서 재는 이유: 사전에 E의 추천이 **실제로
    잡히고 끊김 없이 이어진다**는 사실이 없으면 "삭제 뒤 안 보인다"가 위장일 수 있다.
    """

    async def test_erasure_removes_the_learner_from_the_axis_without_hiding_real_breaks(
        self, db_session: AsyncSession
    ) -> None:
        db = db_session
        earliest = (
            await db.execute(
                text(
                    "SELECT min(time) FROM evidence_event WHERE event_type = 'recommendation_render'"
                    " AND meta ? 'learner_state_basis'"
                )
            )
        ).scalar_one()
        floor = datetime(2002, 1, 1, tzinfo=UTC)
        t0 = (min(floor, earliest) - timedelta(days=1) if earliest is not None else floor).replace(
            microsecond=0
        )
        window = gate.ObservationWindow(start=t0, end=t0 + timedelta(minutes=30))
        # 지울 학습자의 추천만 담는 좁은 창 — 삭제로 관측창이 비면 미측정이어야 한다.
        only_erased = gate.ObservationWindow(
            start=t0 + timedelta(minutes=2, seconds=30), end=t0 + timedelta(minutes=3, seconds=30)
        )

        keep_uid, gone_uid = uuid.uuid4(), uuid.uuid4()
        keep_sid, gone_sid, placeholder_sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        pid = uuid.uuid4()
        objective = f"kpi5-erase-{_RUN_TAG}"
        ktype = await _knowledge_type(db)
        measured = t0 + timedelta(minutes=1, microseconds=654321)

        learners: dict[uuid.UUID, dict[str, uuid.UUID]] = {
            keep_uid: {"sid": keep_sid, "aid": uuid.uuid4(), "c": uuid.uuid4()},
            gone_uid: {"sid": gone_sid, "aid": uuid.uuid4(), "c": uuid.uuid4()},
        }
        for ids in learners.values():
            ids["snap"], ids["hyp"] = uuid.uuid4(), uuid.uuid4()

        def basis(ids: dict[str, uuid.UUID]) -> str:
            return json.dumps(
                {
                    "learner_state_basis": {
                        "schema": 1,
                        "assembled_at": (t0 + timedelta(minutes=2)).isoformat(),
                        "mastery": {
                            "concept_id": str(ids["c"]),
                            "measured_at": measured.isoformat(),
                        },
                        "ability_snapshot": {"snapshot_id": str(ids["snap"])},
                        "misconception_hypothesis_ids": [str(ids["hyp"])],
                    },
                    "reason": {},
                }
            )

        # (분, 세션 ID, meta) — K=2분 · E=3분(좁은 창 안) · placeholder=4분.
        plan = [
            (2, keep_sid, basis(learners[keep_uid])),
            (3, gone_sid, basis(learners[gone_uid])),
            (4, placeholder_sid, basis(learners[keep_uid])),
        ]
        settings = Settings(jwt_secret_key=SecretStr("integration-jwt-secret-0123456789abcdef"))
        try:
            await db.execute(
                text(
                    "INSERT INTO problem (problem_id, source_type, curriculum_version,"
                    " valid_from_year, subject, unit_codes) VALUES (:p,"
                    " CAST(:st AS source_type_enum), CAST(:cv AS curriculum_enum), 2015,"
                    " CAST(:sj AS subject_enum), '{}')"
                ),
                {
                    "p": pid,
                    "st": await self._enum_label(db, "source_type_enum"),
                    "cv": await self._enum_label(db, "curriculum_enum"),
                    "sj": await self._enum_label(db, "subject_enum"),
                },
            )
            for uid, ids in learners.items():
                await db.execute(
                    text(
                        "INSERT INTO user_profile (user_id, persona_primary)"
                        " VALUES (:u, 'A_일반고고3')"
                    ),
                    {"u": uid},
                )
                await db.execute(
                    text(
                        "INSERT INTO learning_session (session_id, user_id, started_at,"
                        " last_activity_at) VALUES (:s, :u, :t, :t)"
                    ),
                    {"s": ids["sid"], "u": uid, "t": t0},
                )
                await db.execute(
                    text(
                        "INSERT INTO problem_attempt (attempt_id, user_id, session_id, problem_id,"
                        " is_correct, ingested_at) VALUES (:a, :u, :s, :p, false, :t)"
                    ),
                    {"a": ids["aid"], "u": uid, "s": ids["sid"], "p": pid, "t": measured},
                )
                await db.execute(
                    text(
                        "INSERT INTO concept_mastery_history (user_id, concept_id, measured_at,"
                        " mastery, attempt_id) VALUES (:u, :c, :m, 0.30, :a)"
                    ),
                    {"u": uid, "c": ids["c"], "m": measured, "a": ids["aid"]},
                )
                await db.execute(
                    text(
                        "INSERT INTO ability_snapshot (snapshot_id, user_id, theta,"
                        " response_count, measured_at) VALUES (:sn, :u, 0.1, 1, :m)"
                    ),
                    {"sn": ids["snap"], "u": uid, "m": measured},
                )
                await db.execute(
                    text(
                        "INSERT INTO misconception_hypothesis (id, user_id, misconception_id,"
                        " confidence) VALUES (:h, :u, :mid, 0.40)"
                    ),
                    {"h": ids["hyp"], "u": uid, "mid": f"M-{_RUN_TAG}"},
                )
            for minute, session_id, meta in plan:
                await db.execute(
                    text(
                        "INSERT INTO evidence_event (time, session_id, objective_id, k_type,"
                        " event_type, meta) VALUES (:t, :s, :o, CAST(:k AS knowledge_type),"
                        " 'recommendation_render', CAST(:m AS jsonb))"
                    ),
                    {
                        "t": t0 + timedelta(minutes=minute),
                        "s": session_id,
                        "o": objective,
                        "k": ktype,
                        "m": meta,
                    },
                )
            await db.commit()

            # ── 사전: 세 추천이 모두 잡히고, E의 추천은 전 홉이 이어진다(위장 아님의 전제).
            before = await gate.collect_traceability(db, window)
            detail_before = dict(before.detail or {})
            assert detail_before["recommendations_in_window"] == 3
            assert detail_before["traced_full"] == 2  # K · E
            assert detail_before["break_learner_unjoined"] == 1  # placeholder
            assert (before.numerator, before.denominator) == (1, 3)
            solo_before = await gate.collect_traceability(db, only_erased)
            assert (solo_before.numerator, solo_before.denominator) == (0, 1)

            # ── 실제 삭제 경로로 E를 지운다(운영 `DELETE /v1/me`의 본체).
            await erasure.erase_user(db, user_id=gone_uid, settings=settings)
            await db.commit()
            gone_rows = (
                await db.execute(
                    text("SELECT count(*) FROM evidence_event WHERE session_id = :s"),
                    {"s": gone_sid},
                )
            ).scalar_one()
            assert gone_rows == 0, "전제 — SEC-40이 삭제된 학습자의 추천 기록을 함께 지운다"

            # ── 사후: E는 분자에도 분모에도 없다(끊김으로 계상되지 않는다) …
            after = await gate.collect_traceability(db, window)
            detail_after = dict(after.detail or {})
            assert detail_after["recommendations_in_window"] == 2
            assert detail_after["break_learner_unjoined"] == 1  # … 세션 기록 실패는 그대로 끊김
            assert detail_after["traced_full"] == 1  # … 남긴 학습자 K는 그대로 전 홉 이어짐
            assert (after.numerator, after.denominator) == (1, 2)

            # ── 삭제로 관측창이 비면 통과가 아니라 미측정이다(표본 경로는 EOS-38 소유).
            solo_after = await gate.collect_traceability(db, only_erased)
            assert solo_after.denominator == 0
            report = gate.evaluate(
                {solo_after.kpi: solo_after}, window=only_erased, run_id="it-erased"
            )
            outcome = next(o for o in report.outcomes if o.kpi is gate.LoopKpi.TRACEABILITY)
            assert outcome.verdict is gate.KpiVerdict.unmeasured
            assert report.exit_code == 2  # 통과(0)로 읽히지 않는다
        finally:
            await db.rollback()
            await db.execute(
                text("DELETE FROM evidence_event WHERE objective_id = :o"), {"o": objective}
            )
            for uid in learners:
                for table in (
                    "concept_mastery_history",
                    "ability_snapshot",
                    "misconception_hypothesis",
                    "problem_attempt",
                    "learning_session",
                    "deletion_audit",
                ):
                    await db.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
                await db.execute(text("DELETE FROM user_profile WHERE user_id = :u"), {"u": uid})
            await db.execute(text("DELETE FROM problem WHERE problem_id = :p"), {"p": pid})
            await db.commit()

        residue = await gate.collect_traceability(db, window)
        assert dict(residue.detail or {})["recommendations_in_window"] == 0

    async def _enum_label(self, db: AsyncSession, typname: str) -> str:
        return str(
            (
                await db.execute(
                    text(
                        "SELECT min(e.enumlabel) FROM pg_enum e JOIN pg_type t"
                        " ON t.oid = e.enumtypid WHERE t.typname = :t"
                    ),
                    {"t": typname},
                )
            ).scalar_one()
        )


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
