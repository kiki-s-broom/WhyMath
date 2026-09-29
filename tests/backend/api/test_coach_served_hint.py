"""S4-11 coach 서빙 reader 결선 — `served_hint` 응답 좌석 + 힌트제공 reveal_score 적재.

연기 해제 전제 ③ serving의 **집행 지점**(`api/coach._served_hint_for`)을 두 세션 경로에서 확인한다
(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지" — reader가 있다는 것이 아니라 서빙 코드가
실제로 부른다는 것을 잰다). store 조회 자체(verified 필터·Level 4 미조회)는
`tests/backend/l4/hint_content/test_store.py`가 동결하므로, 여기서는 store 호출을 가짜로 바꿔
①호출 인자(문항·레벨·단계 하한) ②응답·이벤트로의 운반 ③부르지 *않아야* 하는 경우를 본다.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api import coach
from whymath_backend.api._auth import get_consented_user
from whymath_backend.api._rate_limit import reset_store
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.activity import AttemptEvent as AttemptEventORM
from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
from whymath_backend.db.models.problem import Problem as ProblemORM
from whymath_backend.db.session import get_session
from whymath_backend.l4.hint_content.models import ServedHint
from whymath_backend.l4.socratic.categories import SocraticCategory
from whymath_backend.schema.dialogue import Dialogue as DialogueSchema
from whymath_backend.schema.enums import EventType, Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()
_SECRET = "test-secret-0123456789abcdef"
_SERVED = ServedHint(
    hint_id="hint-sp-9-s2-l1",
    level=1,
    step_order=2,
    content="이번 단계에서는 「인수분해」를 떠올려 볼까?",
    socratic_category=SocraticCategory.PERSPECTIVE,
    reveal_score=1 / 3,
)


@pytest.fixture(autouse=True)
def _reset_rate_limit_store() -> None:
    import asyncio

    asyncio.run(reset_store())


def _settings() -> Settings:
    return Settings(
        jwt_secret_key=SecretStr(_SECRET),
        coach_rate_limit_read_per_minute=0,
        coach_rate_limit_write_per_minute=0,
    )


def _user() -> UserProfileSchema:
    return UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one(self) -> Any:
        return 0.0

    def scalar_one_or_none(self) -> Any:
        return None

    def all(self) -> list[Any]:
        return list(self._rows)


class _CapturingSession:
    def __init__(self, preload: dict[Any, Any] | None = None) -> None:
        self.added: list[Any] = []
        self._preload = preload or {}

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def add_all(self, objs: list[Any]) -> None:
        self.added.extend(objs)

    async def commit(self) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass

    async def get(self, model: Any, pk: Any) -> Any | None:
        return self._preload.get((model, pk))

    async def execute(self, stmt: Any) -> _Result:
        return _Result([])


def _client(preload: dict[Any, Any] | None = None) -> tuple[TestClient, _CapturingSession]:
    app = create_app()
    app.dependency_overrides[get_consented_user] = _user
    app.dependency_overrides[get_settings] = _settings
    captured = _CapturingSession(preload)

    async def _sess() -> AsyncIterator[_CapturingSession]:
        yield captured

    app.dependency_overrides[get_session] = _sess
    return TestClient(app), captured


def _problem(answer: str = "3") -> SimpleNamespace:
    return SimpleNamespace(
        answer=answer,
        answer_constraint=None,
        choices=None,
        question_format=None,
        answer_format=None,
        multiple_answers=None,
        domain=None,
        subunit=None,
    )


def _hint_events(captured: _CapturingSession) -> list[AttemptEventORM]:
    return [
        obj
        for obj in captured.added
        if isinstance(obj, AttemptEventORM) and obj.event_type is EventType.힌트제공
    ]


class _Recorder:
    """`find_served_hint` 대역 — 호출 인자를 기록하고 정해진 값을 돌려준다."""

    def __init__(self, result: ServedHint | None = _SERVED, error: Exception | None = None):
        self.calls: list[dict[str, object]] = []
        self._result = result
        self._error = error

    async def __call__(self, _session: object, **kwargs: object) -> ServedHint | None:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._result


class TestCreateSessionServing:
    def test_served_hint_reaches_response_and_hint_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder()
        monkeypatch.setattr(coach, "find_served_hint", recorder)
        pid = uuid.uuid4()
        client, captured = _client({(ProblemORM, pid): _problem()})
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "어디서부터 해야 할지 모르겠어요",
                "problem_id": str(pid),
                # 판정 불가(기호 1개) 단계 — 완료 상태머신(정답/재고)이 턴을 가로채지 않게 한다.
                "solution_steps": ["a"],
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # ① 호출 인자 — 문항·결정된 레벨·단계 하한(제출 1단계 → 2번째 단계부터).
        assert len(recorder.calls) == 1
        call = recorder.calls[0]
        assert call["problem_id"] == pid
        assert call["hint_level"] == body["decision"]["hint_level"]
        assert call["from_step_order"] == 2
        # ② 응답 운반 — 검수 힌트가 served_hint로 실린다(발화 decision.prompt는 불변 좌석).
        assert body["served_hint"]["hint_id"] == _SERVED.hint_id
        assert body["served_hint"]["level"] == 1
        assert body["served_hint"]["reveal_score"] == pytest.approx(1 / 3)
        assert body["decision"]["prompt"] != _SERVED.content
        # ③ KPI 적재 — 같은 힌트제공 행에 reveal_score·hint_id가 실린다.
        events = _hint_events(captured)
        assert len(events) == 1
        assert events[0].event_data["reveal_score"] == pytest.approx(1 / 3)
        assert events[0].event_data["hint_id"] == _SERVED.hint_id

    def test_no_catalog_hint_logs_none_not_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """카탈로그에 힌트가 없으면 served_hint=null·reveal_score=None(0으로 날조하지 않는다)."""
        monkeypatch.setattr(coach, "find_served_hint", _Recorder(result=None))
        pid = uuid.uuid4()
        client, captured = _client({(ProblemORM, pid): _problem()})
        resp = client.post(
            "/v1/coach/sessions", json={"student_input": "모르겠어요", "problem_id": str(pid)}
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["served_hint"] is None
        event = _hint_events(captured)[0]
        assert event.event_data["reveal_score"] is None and event.event_data["hint_id"] is None

    def test_without_problem_context_reader_is_not_called(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder()
        monkeypatch.setattr(coach, "find_served_hint", recorder)
        client, _captured = _client()
        resp = client.post("/v1/coach/sessions", json={"student_input": "모르겠어요"})
        assert resp.status_code == 201, resp.text
        assert recorder.calls == [] and resp.json()["served_hint"] is None

    def test_kill_switch_off_skips_reader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _Recorder()
        monkeypatch.setattr(coach, "find_served_hint", recorder)
        monkeypatch.setenv("WHYMATH_L4_HINT_CONTENT_SERVING_ENABLED", "false")
        get_settings.cache_clear()
        try:
            pid = uuid.uuid4()
            client, captured = _client({(ProblemORM, pid): _problem()})
            resp = client.post(
                "/v1/coach/sessions", json={"student_input": "모르겠어요", "problem_id": str(pid)}
            )
            assert resp.status_code == 201, resp.text
            assert recorder.calls == [] and resp.json()["served_hint"] is None
            assert _hint_events(captured)[0].event_data["reveal_score"] is None
        finally:
            monkeypatch.delenv("WHYMATH_L4_HINT_CONTENT_SERVING_ENABLED", raising=False)
            get_settings.cache_clear()

    def test_completion_turn_serves_no_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """정답에 도착해 돌아보기로 넘어간 턴에는 힌트를 조회하지 않는다."""
        recorder = _Recorder()
        monkeypatch.setattr(coach, "find_served_hint", recorder)
        pid = uuid.uuid4()
        client, _captured = _client({(ProblemORM, pid): _problem(answer="3")})
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "이게 답인 것 같아요",
                "problem_id": str(pid),
                "solution_steps": ["2x=6", "x=3"],
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["awaiting_reflection"] is True
        assert recorder.calls == [] and resp.json()["served_hint"] is None

    def test_reader_failure_never_breaks_the_turn(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """조회 실패는 힌트 없이 진행하고 예외 **타입명**을 남긴다(침묵 실패 금지)."""
        monkeypatch.setattr(coach, "find_served_hint", _Recorder(error=RuntimeError("boom")))
        pid = uuid.uuid4()
        client, _captured = _client({(ProblemORM, pid): _problem()})
        with caplog.at_level(logging.WARNING):
            resp = client.post(
                "/v1/coach/sessions", json={"student_input": "모르겠어요", "problem_id": str(pid)}
            )
        assert resp.status_code == 201, resp.text
        assert resp.json()["served_hint"] is None
        assert "exc_type=RuntimeError" in caplog.text


class TestAppendTurnServing:
    def test_turn_uses_dialogue_problem_and_carries_served_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder()
        monkeypatch.setattr(coach, "find_served_hint", recorder)
        did, pid = uuid.uuid4(), uuid.uuid4()
        dialogue = DialogueORM.from_schema(
            DialogueSchema(
                dialogue_id=did,
                user_id=_UID,
                problem_id=pid,
                total_turns=2,
                student_turns=1,
                assistant_turns=1,
                review_turns_remaining=0,
            )
        )
        client, captured = _client({(DialogueORM, did): dialogue, (ProblemORM, pid): _problem()})
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "여기서 막혔어요", "solution_steps": ["a", "b"]},
        )
        assert resp.status_code == 201, resp.text
        assert recorder.calls and recorder.calls[0]["problem_id"] == pid
        assert recorder.calls[0]["from_step_order"] == 3
        assert resp.json()["served_hint"]["hint_id"] == _SERVED.hint_id
        assert _hint_events(captured)[0].event_data["hint_id"] == _SERVED.hint_id


def test_stateless_coach_response_has_no_served_hint_seat() -> None:
    """stateless `/v1/coach`는 DB가 없다 — 항상 null인 가짜 계기판을 만들지 않는다."""
    assert "served_hint" not in coach.CoachResponse.model_fields
    assert "served_hint" in coach.SessionCreateResponse.model_fields
    assert "served_hint" in coach.TurnAppendResponse.model_fields


async def test_helper_skips_query_when_completion_handled() -> None:
    """헬퍼 단위 — 완료 상태머신이 발화를 가로챈 턴은 세션을 건드리지 않는다."""

    class _NoTouch:
        async def execute(self, _stmt: Any) -> Any:
            raise AssertionError("완료 턴에서 힌트 조회가 일어났다")

    served = await coach._served_hint_for(
        cast(AsyncSession, _NoTouch()),
        problem_id=uuid.uuid4(),
        hint_level=2,
        solution_steps=None,
        completion_handled=True,
    )
    assert served is None
