"""EOS-132 서빙 경로 — 실 PG에서 **실제 추천 경로를 불러** 근거가 기록되고 KPI⑤가 그것을 되짚는가.

원천 대장·meta 형태를 읽어 판정하지 않는다. 공개 HTTP 표면(`/v1/me/next-problem`·`/v1/me/attempts`
·`/v1/me/learning-trace`)만 불러 DB에 남은 것을 본다(기본 SKIP — `WHYMATH_RUN_INTEGRATION=1`):

  ① 첫 추천(이력 없음) — 근거가 **사유와 함께** 비어 있다(숙달 이력 없음 · θ 스냅샷 없음).
  ② 오답 제출 뒤 둘째 추천 — 근거 숙달 행이 **DB의 최신 숙달 행과 같고**, 그 행의 attempt_id가
     방금 낸 시도다. 활성 가설 id도 DB와 같다.
  ③ KPI⑤ 수집기가 이 두 추천을 사전값 1 · 전 홉 이어짐 1 · 끊김 0으로 센다.
  ④ 학습 이벤트 시간선에 상태 생성 사건이 추천 수만큼 실린다.

픽스처 조립은 페르소나 하네스를 재사용한다(EOS-131 서빙 경로 테스트와 같은 방식).
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import uuid
from datetime import datetime, timedelta
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.l2.learner_state import LearnerStateBasis
from whymath_backend.ops import loop_kpi_gate as gate

pytestmark = pytest.mark.integration

_PERSONA_PATH = pathlib.Path(__file__).with_name("test_e2e_persona_journeys.py")
_HELPERS = (
    "_WRONG_ANSWER",
    "_attempt",
    "_begin",
    "_client",
    "_erase_learner",
    "_get",
    "_login",
    "_next_problem",
    "_seed_concept",
    "_seed_problems",
    "_settings",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_eos132_persona_harness", _PERSONA_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"페르소나 하네스 스펙 생성 실패: {_PERSONA_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"페르소나 하네스 헬퍼가 사라졌다: {missing}")
    return module


_P = _load()


def _rows(sql: str, params: dict[str, Any]) -> list[tuple[Any, ...]]:
    async def _run() -> list[tuple[Any, ...]]:
        engine = create_async_engine(_P._settings().database_url)
        try:
            async with engine.connect() as conn:
                return [tuple(r) for r in (await conn.execute(text(sql), params)).all()]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _traceability(start: datetime, end: datetime) -> gate.Observation:
    async def _run() -> gate.Observation:
        engine = create_async_engine(_P._settings().database_url)
        try:
            async with async_sessionmaker(engine)() as session:
                return await gate.collect_traceability(
                    session, gate.ObservationWindow(start=start, end=end)
                )
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _delete_recommendations(session_ids: list[str]) -> None:
    async def _run() -> None:
        engine = create_async_engine(_P._settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM evidence_event WHERE session_id = ANY(CAST(:ids AS uuid[]))"),
                    {"ids": session_ids},
                )
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_recommendations_record_the_state_they_saw_and_kpi5_traces_them() -> None:
    content, _journal = _P._begin("EOS-132")
    session_ids: list[str] = []
    try:
        cid, _code = _P._seed_concept(content, "e132", "일차방정식의 활용")
        _P._seed_problems(content, cid, "e132", [3.0, 3.4, 3.8])
        with _P._client() as client:
            _P._erase_learner(client)  # 지난 회차 잔여 제거(멱등)
            auth = _P._login(client)
            uid = uuid.UUID(_P._get(client, auth, "/v1/me/export")["user_id"])

            first = _P._next_problem(client, auth)
            assert first["problem_id"] is not None, first
            _P._attempt(
                client, auth, uuid.UUID(first["problem_id"]), correct=False, answer=_P._WRONG_ANSWER
            )
            second = _P._next_problem(client, auth)
            assert second["problem_id"] is not None, second

            recs = _rows(
                "SELECT e.time, e.meta, e.session_id FROM evidence_event e"
                " JOIN learning_session s ON s.session_id = e.session_id"
                " WHERE s.user_id = :u AND e.event_type = 'recommendation_render'"
                " ORDER BY e.time",
                {"u": uid},
            )
            assert len(recs) == 2, recs
            session_ids.extend(sorted({str(r[2]) for r in recs}))
            bases = [LearnerStateBasis.from_meta(r[1].get("learner_state_basis")) for r in recs]
            assert all(b is not None for b in bases), [r[1] for r in recs]
            before, after = bases[0], bases[1]
            assert before is not None and after is not None

            # ① 이력 없는 첫 추천 — 근거가 사유와 함께 비어 있다(지어내지 않는다).
            assert before.mastery is None and before.ability_snapshot_id is None
            assert recs[0][1]["learner_state_basis"]["mastery"] == {"absent": "no_mastery_history"}

            # ② 둘째 추천의 근거 = DB의 최신 숙달 행, 그 행의 시도 = 방금 제출한 시도.
            (latest,) = _rows(
                "SELECT concept_id, measured_at, attempt_id FROM concept_mastery_history"
                " WHERE user_id = :u ORDER BY measured_at DESC, concept_id LIMIT 1",
                {"u": uid},
            )
            assert after.mastery is not None
            assert (after.mastery.concept_id, after.mastery.measured_at) == (latest[0], latest[1])
            attempts = _rows(
                "SELECT attempt_id, problem_id FROM problem_attempt WHERE user_id = :u", {"u": uid}
            )
            assert [(a[0], str(a[1])) for a in attempts] == [(latest[2], first["problem_id"])]
            active = _rows(
                "SELECT id FROM misconception_hypothesis WHERE user_id = :u AND is_active",
                {"u": uid},
            )
            assert set(after.misconception_hypothesis_ids) == {r[0] for r in active}

            # ③ KPI⑤ — 이 두 추천만 담는 창에서 사전값 1 · 이어짐 1 · 끊김 0.
            observation = _traceability(
                recs[0][0] - timedelta(milliseconds=1), recs[-1][0] + timedelta(milliseconds=1)
            )
            detail = dict(observation.detail or {})
            assert detail["recommendations_in_window"] == 2, detail
            assert detail["traced_prior_only"] == 1, detail
            assert detail["traced_full"] == 1, detail
            assert (observation.numerator, observation.denominator) == (0, 2), detail

            # ④ 시간선 — 상태 생성 사건이 추천 수만큼(대장 문자열이 아니라 조회 결과).
            trace = _P._get(client, auth, "/v1/me/learning-trace")
            counts = {c["event_type"]: c["count"] for c in trace["coverage"]}
            assert counts["learner_state_created"] == 2, counts
            assert counts["recommendation_generated"] == 2, counts
            _P._erase_learner(client)
    finally:
        try:
            content.teardown()
        finally:
            if session_ids:
                _delete_recommendations(session_ids)
