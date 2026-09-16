"""`GET /v1/me/learning-trace`(EOS-11) — 학습 시간선 읽기 표면 (hermetic·FakeSession).

이 파일이 지키는 것은 **표면 계약**이다: 인증 스코프·직렬화 모양·가용성 대장 동반 노출·
절단 고지·limit 경계. 투영 의미(전후 값·오답 파생·PII allowlist)는
`tests/backend/l2/test_learning_event_trace.py`가 본다.

스코프 가드가 이 표면의 핵심이다 — 학습 이벤트는 미성년 학습자의 행동 기록이므로 타인 조회
경로가 **구조적으로 없어야** 한다(경로·쿼리에 user_id 슬롯 부재 + 401).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from whymath_backend.api._auth import get_consented_user
from whymath_backend.app import create_app
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import EventType, Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()
_T0 = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return _T0 + timedelta(minutes=minutes)


def _consented_user() -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)
    )


@dataclass
class _AssessmentRow:
    started_at: datetime | None
    completed_at: datetime | None = None
    assessment_type: Any = None


@dataclass
class _AttemptRow:
    attempt_id: uuid.UUID
    problem_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    is_correct: bool | None = None
    duration_seconds: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    ingested_at: datetime | None = None
    created_at: datetime | None = None


@dataclass
class _EventRow:
    event_type: EventType | None
    event_at: datetime
    event_time: datetime | None = None
    event_data: dict[str, Any] | None = None
    attempt_id: uuid.UUID | None = None
    problem_id: uuid.UUID | None = None


@dataclass
class _MasteryViewRow:
    axis_id: Any
    measured_at: datetime
    mastery: float | None
    confidence: float | None
    sample_size: int | None
    mastery_before: float | None


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class FakeSession:
    """`execute()`가 `build_trace`의 질의 순서대로 결과를 반환(7회)."""

    def __init__(self, queue: list[list[Any]]) -> None:
        self._queue = queue
        self.calls = 0

    async def execute(self, _stmt: Any) -> _Result:
        self.calls += 1
        return _Result(self._queue[self.calls - 1] if self.calls <= len(self._queue) else [])


def _scenario_queue() -> list[list[Any]]:
    """계획서 §17 한 세션 — 진단→막힘→오답→오개념→숙달 하락."""
    return [
        [_AssessmentRow(started_at=_at(0), completed_at=_at(4))],
        [
            _AttemptRow(
                attempt_id=uuid.uuid4(),
                problem_id=uuid.uuid4(),
                is_correct=False,
                started_at=_at(10),
                ingested_at=_at(10),
                duration_seconds=95,
            )
        ],
        [_EventRow(event_type=EventType.막힘, event_at=_at(8), event_data={"turn_count": 5})],
        [_MasteryViewRow(uuid.uuid4(), _at(12), 0.43, None, None, 0.54)],
        [],
        [],
        [],
    ]


def _client(queue: list[list[Any]] | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_consented_user] = _consented_user
    fake = FakeSession(queue if queue is not None else [[] for _ in range(7)])

    async def _sess() -> AsyncIterator[FakeSession]:
        yield fake

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


def _no_auth_client() -> TestClient:
    app = create_app()

    async def _sess() -> AsyncIterator[FakeSession]:
        yield FakeSession([[] for _ in range(7)])

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


class TestLearningTraceSurface:
    def test_returns_the_session_in_chronological_order(self) -> None:
        client = _client(_scenario_queue())
        resp = client.get("/v1/me/learning-trace")
        assert resp.status_code == 200
        body = resp.json()
        assert [e["event_type"] for e in body["entries"]] == [
            "diagnostic_started",
            "diagnostic_completed",
            "stuck_detected",
            "problem_attempted",
            "assessment_failed",
            "mastery_updated",
        ]

    def test_mastery_entry_serialises_before_and_after(self) -> None:
        client = _client(_scenario_queue())
        body = client.get("/v1/me/learning-trace").json()
        (mastery,) = [e for e in body["entries"] if e["event_type"] == "mastery_updated"]
        assert mastery["mastery_change"]["mastery_before"] == 0.54
        assert mastery["mastery_change"]["mastery_after"] == 0.43
        assert mastery["mastery_change"]["is_first_measurement"] is False

    def test_coverage_is_always_returned_with_entries(self) -> None:
        """대장 없이 entries만 주면 0건이 '안 했다'로 읽힌다 — 함께 나가는 것이 계약이다."""
        client = _client(_scenario_queue())
        body = client.get("/v1/me/learning-trace").json()
        by_type = {c["event_type"]: c for c in body["coverage"]}
        assert by_type["content_viewed"]["availability"] == "dormant"
        assert by_type["recommendation_generated"]["availability"] == "unjoinable"
        assert by_type["problem_attempted"]["availability"] == "produced"
        assert by_type["problem_attempted"]["count"] == 1

    def test_dormant_reason_is_human_readable(self) -> None:
        client = _client(_scenario_queue())
        body = client.get("/v1/me/learning-trace").json()
        by_type = {c["event_type"]: c for c in body["coverage"]}
        assert by_type["concept_selected"]["reason"]

    def test_empty_learner_still_reports_coverage(self) -> None:
        client = _client()
        body = client.get("/v1/me/learning-trace").json()
        assert body["entries"] == []
        assert body["coverage"]

    def test_truncation_is_disclosed(self) -> None:
        client = _client(_scenario_queue())
        body = client.get("/v1/me/learning-trace?limit=2").json()
        assert body["truncated"] is True
        assert len(body["entries"]) == 2

    def test_limit_upper_bound_is_enforced_by_the_surface(self) -> None:
        client = _client(_scenario_queue())
        resp = client.get("/v1/me/learning-trace?limit=100000")
        assert resp.status_code == 422

    def test_limit_zero_is_rejected(self) -> None:
        client = _client(_scenario_queue())
        resp = client.get("/v1/me/learning-trace?limit=0")
        assert resp.status_code == 422

    def test_time_window_parameters_are_accepted(self) -> None:
        client = _client(_scenario_queue())
        resp = client.get(
            "/v1/me/learning-trace",
            params={"since": _at(0).isoformat(), "until": _at(60).isoformat()},
        )
        assert resp.status_code == 200

    def test_requires_authentication(self) -> None:
        client = _no_auth_client()
        assert client.get("/v1/me/learning-trace").status_code == 401

    def test_learner_id_is_taken_from_the_token_not_the_request(self) -> None:
        """타인 id를 넣을 자리가 없다 — 쿼리로 준 user_id는 무시되고 본인 id가 나온다."""
        other = uuid.uuid4()
        client = _client(_scenario_queue())
        body = client.get(f"/v1/me/learning-trace?learner_id={other}&user_id={other}").json()
        assert body["learner_id"] == str(_UID)

    def test_no_student_prose_is_serialised(self) -> None:
        """응답 어디에도 답안·풀이 키가 없어야 한다(미성년 PII 경계)."""
        client = _client(_scenario_queue())
        raw = client.get("/v1/me/learning-trace").text
        for forbidden in ("student_answer", "answer_text", "solution_latex", "ocr_result"):
            assert forbidden not in raw
