"""코치 완료 경로의 학습 상태 머신 배선 — 인자·순서·거부 표면 (EOS-134 · DB 무접근 단위).

`api/coach._complete_problem`이 `/v1/me/attempts`와 같은 공용 진입점
(`l2/learning_state_machine.advance_on_graded_attempt`)을 부른다. 이 파일은 그 호출의 세 축을 본다:

  - **인자** — 서버 판정 정답(`is_correct=True`) · 확신도 미측정(`confidence=None` — 0.0으로 채우지
    않는다) · 방금 적재한 attempt의 id · 그 학생.
  - **순서** — attempt commit과 숙달·스킬 기록 **뒤**다(연속 오답 카운트가 이번 행을 `offset(1)`로
    건너뛰는 전제 · `/v1/me/attempts`와 같은 순서).
  - **거부 표면** — 평가 진입이 거부되면(예: 진단 중 학습자) 원장에 아무것도 남지 않으므로 경고로
    남긴다. 완료 자체(attempt 적재)는 그대로 성공한다.

두 경로가 같은 함수를 부른다는 구조 동결은 `test_me_learning_state.py`(AST), 같은 입력에 같은 전이가
난다는 실측은 `test_eos134_coach_state_machine_integration.py`(실 PG)가 맡는다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import whymath_backend.api.coach as coach_module
from whymath_backend.db.models.activity import ProblemAttempt as ProblemAttemptORM

_UID = uuid.UUID("00000000-0000-0000-0000-00000000e134")
_PID = uuid.UUID("00000000-0000-0000-0000-0000000a0134")
_T0 = datetime(2026, 9, 28, 11, 0, 0, tzinfo=timezone.utc)


class _EmptyResult:
    """모든 조회가 0행 — 힌트 귀속 창을 모르는 상태(이 파일의 관심은 상태 머신이다)."""

    def scalar_one_or_none(self) -> Any:
        return None

    def all(self) -> list[Any]:
        return []

    def scalars(self) -> _EmptyResult:
        return self


class _FakeSession:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.added: list[Any] = []

    async def execute(self, _stmt: Any) -> _EmptyResult:
        return _EmptyResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self._calls.append("commit")


class _Spy:
    """호출 순서와 상태 머신 인자를 기록한다."""

    def __init__(self, rejected: str | None = None) -> None:
        self.calls: list[str] = []
        self.state_kwargs: dict[str, Any] | None = None
        self._rejected = rejected

    def recorder(self, name: str) -> Any:
        async def _record(*_args: Any, **_kwargs: Any) -> list[Any]:
            self.calls.append(name)
            return []

        return _record

    async def state_machine(self, _session: Any, **kwargs: Any) -> SimpleNamespace:
        self.calls.append("state_machine")
        self.state_kwargs = kwargs
        return SimpleNamespace(rejected_transition=self._rejected)


def _patch(monkeypatch: pytest.MonkeyPatch, spy: _Spy) -> None:
    monkeypatch.setattr(coach_module, "record_learning_activity", spy.recorder("session"))
    monkeypatch.setattr(coach_module, "record_problem_attempt_mastery", spy.recorder("mastery"))
    monkeypatch.setattr(
        coach_module, "record_problem_attempt_skill_mastery", spy.recorder("skill_mastery")
    )
    monkeypatch.setattr(coach_module, "record_attempt_skill_event", spy.recorder("skill_event"))
    monkeypatch.setattr(coach_module, "advance_on_graded_attempt", spy.state_machine)


def _complete(session: _FakeSession, *, problem_id: uuid.UUID | None = _PID) -> Any:
    return asyncio.run(
        coach_module._complete_problem(
            session,  # type: ignore[arg-type]
            user_id=_UID,
            problem_id=problem_id,
            final_answer=None,
            started_at=_T0,
            dialogue_id=None,
        )
    )


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Spy]:
    s = _Spy()
    _patch(monkeypatch, s)
    yield s


class TestArguments:
    def test_server_verdict_correct_and_unmeasured_confidence(self, spy: _Spy) -> None:
        session = _FakeSession(spy.calls)
        attempt_id, _evidence = _complete(session)

        assert spy.state_kwargs is not None, "코치 완료가 상태 머신을 부르지 않았다"
        assert spy.state_kwargs["user_id"] == _UID
        assert spy.state_kwargs["is_correct"] is True
        # 코치 경로에는 자기보고 확신도 입력이 없다 — None(미측정)이지 0.0이 아니다.
        assert "confidence" in spy.state_kwargs and spy.state_kwargs["confidence"] is None
        assert spy.state_kwargs["attempt_id"] == attempt_id

    def test_attempt_id_is_the_one_just_persisted(self, spy: _Spy) -> None:
        session = _FakeSession(spy.calls)
        _complete(session)
        attempts = [o for o in session.added if isinstance(o, ProblemAttemptORM)]
        assert len(attempts) == 1
        assert spy.state_kwargs is not None
        assert spy.state_kwargs["attempt_id"] == attempts[0].attempt_id


class TestOrdering:
    def test_runs_after_commit_and_after_mastery_and_skill_records(self, spy: _Spy) -> None:
        """`/v1/me/attempts`와 같은 순서 — attempt commit → 숙달 → 스킬 → 스킬 이벤트 → 상태."""
        _complete(_FakeSession(spy.calls))
        calls = spy.calls
        assert calls.count("state_machine") == 1, calls
        at = calls.index("state_machine")
        assert at == len(calls) - 1, f"상태 머신은 마지막이어야 한다: {calls}"
        for earlier in ("commit", "mastery", "skill_mastery", "skill_event"):
            assert earlier in calls[:at], f"{earlier}가 상태 머신보다 앞서지 않았다: {calls}"

    def test_not_called_without_a_problem(self, spy: _Spy) -> None:
        """문항이 없으면 완료 적재 자체가 없다 — 상태 머신도 돌지 않는다."""
        assert _complete(_FakeSession(spy.calls), problem_id=None) == (None, None)
        assert "state_machine" not in spy.calls


class TestRejectionSurface:
    def test_rejected_transition_is_logged_and_completion_still_succeeds(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        rejection = (
            "DIAGNOSING → ASSESSING (UndefinedTransitionError; DIAGNOSING에서 가능한 상태: …)"
        )
        s = _Spy(rejected=rejection)
        _patch(monkeypatch, s)
        with caplog.at_level(logging.WARNING, logger=coach_module.logger.name):
            attempt_id, _evidence = _complete(_FakeSession(s.calls))
        assert attempt_id is not None, "거부가 완료 적재를 막았다"
        assert rejection in caplog.text
        assert "EOS-134" in caplog.text

    def test_no_warning_when_the_transition_is_recorded(
        self, spy: _Spy, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=coach_module.logger.name):
            _complete(_FakeSession(spy.calls))
        assert "학습 상태 전이 거부" not in caplog.text
