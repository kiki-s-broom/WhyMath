"""EOS-131 서빙 경로 배선 — 실 PG에서 **실제 writer 경로를 호출해** 세션 행이 생기는가(기본 SKIP).

acceptance ⑥ "테스트는 대장 문자열이 아니라 실제 writer 경로를 호출해 행이 생기는 것을 확인한다"의
집행 지점이다. 원천 대장(`_SOURCE_REGISTRY`)을 읽지 않고, 공개 HTTP 표면(`/v1/me/next-problem`·
`/v1/me/attempts`)만 불러 DB에 남은 것을 본다:

  ② 추천 조회·시도 제출이 **한** 학습 세션을 연다(30분 안 — 같은 세션을 잇는다).
  ③ 그 행의 점수 컬럼은 NULL이다.
  ④ 추천 기록 `evidence_event.session_id`가 placeholder가 아니라 그 세션이고, 시도의
     `problem_attempt.session_id`도 서버가 채운 그 세션이다.
  ⑤ 열람권 export에 추천 기록이 조인으로 실리고, 삭제권 이행 뒤에는 추천 행은 **남되** 학습자와
     끊긴다(조인 0) — `evidence_event.session_id`가 FK가 아니라는 성질의 실측.
  ⑥ 학습 이벤트 시간선에 `concept_selected`·`recommendation_generated`가 실제 건수로 실린다.
  ⑦(나) 파일럿 KPI2 입력(`load_retention_sessions`)이 이 세션 행을 읽어 재방문율 값을 낸다.

픽스처 조립은 페르소나 하네스를 재사용한다(재구현 0 — 시나리오 스위트와 같은 경로 적재 방식).
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import uuid
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.harness.pilot_kpi_baseline import compute_retention, load_retention_sessions
from whymath_backend.harness.wh1_evaluation import MetricStatus

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
    spec = importlib.util.spec_from_file_location("_eos131_persona_harness", _PERSONA_PATH)
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


def _retention_for(uid: uuid.UUID) -> Any:
    async def _run() -> Any:
        engine = create_async_engine(_P._settings().database_url)
        try:
            async with async_sessionmaker(engine)() as session:
                return compute_retention(
                    await load_retention_sessions(session, user_id=uid, since=None, until=None)
                )
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_serving_paths_open_one_session_and_join_recommendations() -> None:
    content, _journal = _P._begin("EOS-131")
    session_ids: list[str] = []
    try:
        cid, _code = _P._seed_concept(content, "e131", "일차방정식의 풀이")
        _P._seed_problems(content, cid, "e131", [3.0, 3.4, 3.8])
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

            # ② 한 세션 — writer 경로(HTTP)만 불렀다. ③ 점수 NULL.
            sessions = _rows(
                "SELECT session_id, ended_at, last_activity_at, focus_score, engagement_score"
                " FROM learning_session WHERE user_id = :u",
                {"u": uid},
            )
            assert len(sessions) == 1, sessions
            sid, ended_at, last_activity_at, focus, engagement = sessions[0]
            session_ids.append(str(sid))
            assert ended_at is None and last_activity_at is not None
            assert focus is None and engagement is None

            # ④ 시도·추천이 같은 실 세션에 결합된다(placeholder 아님).
            attempts = _rows(
                "SELECT session_id FROM problem_attempt WHERE user_id = :u", {"u": uid}
            )
            assert attempts == [(sid,)], attempts
            recs = _rows(
                "SELECT e.session_id FROM evidence_event e"
                " JOIN learning_session s ON s.session_id = e.session_id"
                " WHERE s.user_id = :u AND e.event_type = 'recommendation_render'",
                {"u": uid},
            )
            assert recs == [(sid,), (sid,)], recs

            # ⑥ 시간선에 실제 건수로 실린다(대장 문자열이 아니라 조회 결과).
            trace = _P._get(client, auth, "/v1/me/learning-trace")
            counts = {c["event_type"]: c["count"] for c in trace["coverage"]}
            assert counts["concept_selected"] == 1, counts
            assert counts["recommendation_generated"] == 2, counts

            # ⑤ 열람권 — 추천 기록이 세션 조인으로 export에 실린다.
            exported = _P._get(client, auth, "/v1/me/export")["data"]["recommendation_events"]
            assert [row["session_id"] for row in exported] == [str(sid), str(sid)], exported

            # ⑦(나) KPI2 — 세션 행을 읽어 값을 낸다(1명·1일 → 재방문 0/1 = 0.0, 측정됨).
            retention = _retention_for(uid)
            assert retention.returning_user_rate.status is MetricStatus.MEASURED
            assert retention.returning_user_rate.value == 0.0
            assert retention.distinct_users == 1

            # ⑤ 삭제권 — 세션 행이 지워지면 추천은 남되 학습자와 끊긴다(FK 아님).
            _P._erase_learner(client)
            assert _rows("SELECT 1 FROM learning_session WHERE session_id = :s", {"s": sid}) == []
            orphaned = _rows(
                "SELECT count(*) FROM evidence_event WHERE session_id = :s"
                " AND event_type = 'recommendation_render'",
                {"s": sid},
            )
            assert orphaned == [(2,)], "추천 기록 자체는 파기 대상이 아니다(비민감 처치 회계)"
            rejoined = _rows(
                "SELECT count(*) FROM evidence_event e"
                " JOIN learning_session s ON s.session_id = e.session_id WHERE s.user_id = :u",
                {"u": uid},
            )
            assert rejoined == [(0,)], "삭제권 이행 후에도 추천이 학습자와 결합돼 있다"
    finally:
        try:
            content.teardown()
        finally:
            if session_ids:
                _rows_delete(session_ids)


def _rows_delete(session_ids: list[str]) -> None:
    """이 회차가 남긴 추천 처치 행 정리(학습자와 이미 끊긴 비민감 회계 행)."""

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
