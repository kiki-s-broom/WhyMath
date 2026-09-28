"""코치 완료 경로의 힌트 사용 귀속 — 창·셈 규칙·적재 순서 (EOS-133 · DB 무접근 단위).

`api/coach._complete_problem`이 이 풀이에 쓰인 힌트를 attempt에 귀속한다(`used_hint` 3상태 +
`hint_usage` 행). 이 파일은 세 부품을 각각 잡는다:

  - `_hint_attribution_window` — 창 `[대화 시작, 정답을 처음 낸 학생 턴의 발화 시각)`. 상한은 완료
    시각이 아니다(정답 제출 턴·돌아보기 턴의 공급은 답이 나온 *뒤*라 이 풀이에 쓰였을 수 없다).
  - `_attribute_hints` — 단계 2 이상만 센다 · 판독 불가 행이 섞이면 "안 썼다"로 확정하지 않는다.
  - `_complete_problem` — attempt의 `used_hint` + `hint_usage` 행을 **같은 commit**으로, 부모 행을
    먼저 내보낸 뒤 적재한다.

실 PG 위의 전 경로(HTTP 3턴 → 행 적재)는 `test_eos133_hint_attribution_integration.py`와
시나리오 스위트 SCENARIO-005가 본다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

import whymath_backend.api.coach as coach_module
from whymath_backend.db.models.activity import ProblemAttempt as ProblemAttemptORM
from whymath_backend.db.models.hint_usage import HintUsage as HintUsageORM
from whymath_backend.l4.completion import REFLECTION_TURNS, review_turns_on_entry
from whymath_backend.l4.hint_deferral import HINT_USAGE_MIN_LEVEL, counts_as_hint_usage

_T0 = datetime(2026, 9, 28, 9, 0, 0, tzinfo=timezone.utc)
_UID = uuid.UUID("00000000-0000-0000-0000-00000000e133")
_PID = uuid.UUID("00000000-0000-0000-0000-0000000a0133")
_DID = uuid.UUID("00000000-0000-0000-0000-0000000d0133")


# ── 가짜 세션 — 실행한 문장을 기록하고, 준비된 결과를 차례로 돌려준다 ──────────────────


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _Result:
        return self


class _ScriptedSession:
    """`execute` 결과를 준비된 순서대로 내고, 소진되면 0행을 낸다(증거 조립 등 후속 조회용)."""

    def __init__(self, scripted: list[list[Any]] | None = None) -> None:
        self._scripted = list(scripted or [])
        self.statements: list[Any] = []
        self.ops: list[tuple[str, Any]] = []

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self._scripted.pop(0) if self._scripted else [])

    def add(self, obj: Any) -> None:
        self.ops.append(("add", obj))

    def add_all(self, objs: list[Any]) -> None:
        self.ops.append(("add_all", list(objs)))

    async def flush(self) -> None:
        self.ops.append(("flush", None))

    async def commit(self) -> None:
        self.ops.append(("commit", None))


def _sql(stmt: Any) -> str:
    """리터럴을 박아 컴파일한 SQL — 연산자·정렬·OFFSET을 문자열로 확인한다."""
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ── 정본 상수 ─────────────────────────────────────────────────────────────────────


class TestUsageThreshold:
    """'힌트 사용'의 경계는 L4 정본 한 곳 — 1(방향)은 세지 않고 2(단계 흐름)부터 센다."""

    def test_threshold_is_step_flow(self) -> None:
        assert HINT_USAGE_MIN_LEVEL == 2

    @pytest.mark.parametrize(("level", "counted"), [(1, False), (2, True), (3, True), (4, True)])
    def test_counts_as_hint_usage(self, level: int, counted: bool) -> None:
        assert counts_as_hint_usage(level) is counted

    def test_review_turns_on_entry_is_the_state_machine_value(self) -> None:
        """창 계산과 상태 머신이 같은 값을 쓴다 — 최소 1 클램프까지 한 함수가 소유한다."""
        assert review_turns_on_entry() == max(1, REFLECTION_TURNS)
        assert review_turns_on_entry(0) == 1
        assert review_turns_on_entry(3) == 3


# ── 페이로드 판독 ─────────────────────────────────────────────────────────────────


class TestSuppliedHintLevel:
    @pytest.mark.parametrize("level", [1, 2, 3, 4])
    def test_reads_closed_range(self, level: int) -> None:
        assert coach_module._supplied_hint_level({"hint_level": level}) == level

    @pytest.mark.parametrize(
        "payload",
        [
            {"hint_level": 0},
            {"hint_level": 5},
            {"hint_level": "2"},
            {"hint_level": 2.0},
            {"hint_level": None},
            {},
            None,
            "hint_level=2",
            [2],
        ],
    )
    def test_unreadable_is_none(self, payload: object) -> None:
        assert coach_module._supplied_hint_level(payload) is None

    def test_bool_is_not_level_one(self) -> None:
        """`bool`은 `int`의 하위형이다 — `True`가 단계 1로 새어 들어오면 안 된다."""
        assert coach_module._supplied_hint_level({"hint_level": True}) is None


# ── 창 ───────────────────────────────────────────────────────────────────────────


class TestAttributionWindow:
    def test_no_dialogue_means_unknown_without_query(self) -> None:
        session = _ScriptedSession()
        window = _run(
            coach_module._hint_attribution_window(
                session, dialogue_id=None, started_at=_T0  # type: ignore[arg-type]
            )
        )
        assert window is None
        assert session.statements == []

    def test_no_start_means_unknown_without_query(self) -> None:
        session = _ScriptedSession()
        window = _run(
            coach_module._hint_attribution_window(
                session, dialogue_id=_DID, started_at=None  # type: ignore[arg-type]
            )
        )
        assert window is None
        assert session.statements == []

    def test_naive_start_is_unknown(self) -> None:
        session = _ScriptedSession([[_T0]])
        window = _run(
            coach_module._hint_attribution_window(
                session,  # type: ignore[arg-type]
                dialogue_id=_DID,
                started_at=_T0.replace(tzinfo=None),
            )
        )
        assert window is None

    def test_upper_bound_is_the_correct_submission_turn(self) -> None:
        boundary = _T0 + timedelta(minutes=3)
        session = _ScriptedSession([[boundary]])
        window = _run(
            coach_module._hint_attribution_window(
                session, dialogue_id=_DID, started_at=_T0  # type: ignore[arg-type]
            )
        )
        assert window == (_T0, boundary)

    def test_first_message_solution_gives_empty_window(self) -> None:
        """첫 메시지에서 바로 정답 — 상한이 시작 시각과 같아 창이 빈다(도움 없이 풀었다)."""
        session = _ScriptedSession([[_T0]])
        window = _run(
            coach_module._hint_attribution_window(
                session, dialogue_id=_DID, started_at=_T0  # type: ignore[arg-type]
            )
        )
        assert window == (_T0, _T0)

    @pytest.mark.parametrize(
        "row",
        [
            [],  # 학생 턴 행이 없다
            [None],  # 발화 시각 NULL
            [_T0 - timedelta(seconds=1)],  # 시작보다 앞선다(정합 깨짐)
            [(_T0 + timedelta(minutes=1)).replace(tzinfo=None)],  # naive
            ["2026-09-28T09:01:00+00:00"],  # 시각 타입이 아니다
        ],
    )
    def test_broken_boundary_is_unknown(self, row: list[Any]) -> None:
        session = _ScriptedSession([row])
        window = _run(
            coach_module._hint_attribution_window(
                session, dialogue_id=_DID, started_at=_T0  # type: ignore[arg-type]
            )
        )
        assert window is None

    def test_query_walks_back_over_reflection_turns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """정답 제출 턴 = 적재된 학생 턴 중 마지막 (돌아보기 턴 수 − 1)개 앞 — 턴 수는 정본에서."""
        session = _ScriptedSession([[_T0]])
        _run(
            coach_module._hint_attribution_window(
                session, dialogue_id=_DID, started_at=_T0  # type: ignore[arg-type]
            )
        )
        sql = _sql(session.statements[0])
        assert "FROM dialogue_turn" in sql
        assert "dialogue_turn.role = 'student'" in sql
        assert "ORDER BY dialogue_turn.turn_order DESC" in sql
        assert f"OFFSET {review_turns_on_entry() - 1}" in sql

        # 돌아보기가 2턴으로 늘면 한 턴 더 거슬러 올라간다 — 상수를 따로 적지 않았다는 증거.
        monkeypatch.setattr(coach_module, "review_turns_on_entry", lambda: 2)
        session2 = _ScriptedSession([[_T0]])
        _run(
            coach_module._hint_attribution_window(
                session2, dialogue_id=_DID, started_at=_T0  # type: ignore[arg-type]
            )
        )
        assert "OFFSET 1" in _sql(session2.statements[0])


# ── 셈 ───────────────────────────────────────────────────────────────────────────


def _hint_rows(*levels: object) -> list[tuple[datetime, object]]:
    return [
        (_T0 + timedelta(seconds=10 * (i + 1)), {"hint_level": lv} if lv != "raw" else "raw")
        for i, lv in enumerate(levels)
    ]


class TestAttributeHints:
    _WINDOW = (_T0, _T0 + timedelta(minutes=5))

    def _attribute(self, rows: list[Any]) -> tuple[Any, _ScriptedSession]:
        session = _ScriptedSession([rows])
        result = _run(
            coach_module._attribute_hints(
                session,  # type: ignore[arg-type]
                user_id=_UID,
                problem_id=_PID,
                window=self._WINDOW,
            )
        )
        return result, session

    def test_unknown_window_is_unknown_without_query(self) -> None:
        session = _ScriptedSession()
        result = _run(
            coach_module._attribute_hints(
                session,  # type: ignore[arg-type]
                user_id=_UID,
                problem_id=_PID,
                window=None,
            )
        )
        assert result.used_hint is None and result.hints == ()
        assert session.statements == []

    def test_no_supply_is_false(self) -> None:
        result, _ = self._attribute([])
        assert result.used_hint is False and result.hints == ()

    def test_direction_only_is_false(self) -> None:
        """단계 1만 받았다 — 코치의 기본 공급이지 힌트 사용이 아니다."""
        result, _ = self._attribute(_hint_rows(1, 1, 1))
        assert result.used_hint is False and result.hints == ()

    def test_counts_step_flow_and_above_in_time_order(self) -> None:
        rows = _hint_rows(2, 1, 4)
        result, _ = self._attribute(rows)
        assert result.used_hint is True
        assert result.hints == ((rows[0][0], 2), (rows[2][0], 4))

    def test_unreadable_without_countable_is_unknown(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """판독 불가 행이 2 이상이었을 수 있다 — "안 썼다"로 확정하지 않고 경고를 남긴다."""
        with caplog.at_level(logging.WARNING, logger=coach_module.logger.name):
            result, _ = self._attribute(_hint_rows(1, "x"))
        assert result.used_hint is None and result.hints == ()
        assert "1건" in caplog.text and "미상" in caplog.text

    def test_unreadable_beside_countable_stays_true_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=coach_module.logger.name):
            result, _ = self._attribute(_hint_rows(3, "raw"))
        assert result.used_hint is True and [lv for _, lv in result.hints] == [3]
        assert "1건" in caplog.text and "used_hint=True" in caplog.text

    def test_query_scope_is_this_learner_problem_supply_and_half_open(self) -> None:
        _, session = self._attribute([])
        sql = _sql(session.statements[0])
        assert "FROM attempt_event" in sql
        assert str(_UID) in sql and str(_PID) in sql
        assert "attempt_event.event_type = '힌트제공'" in sql
        assert "attempt_event.event_at >= " in sql
        # 상한은 엄격 비교다 — 같은 턴의 공급 행이 저해상도 시계에서 발화 시각과 같아져도 뺀다.
        assert "attempt_event.event_at < " in sql
        assert "attempt_event.event_at <= " not in sql
        assert "ORDER BY attempt_event.event_at" in sql


# ── 적재 ─────────────────────────────────────────────────────────────────────────


async def _noop_list(*_args: Any, **_kwargs: Any) -> list[Any]:
    return []


async def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _no_session(*_args: Any, **_kwargs: Any) -> None:
    return None


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """숙달·스킬·학습 세션 부수효과는 no-op — 이 파일의 관심은 힌트 귀속 적재뿐이다."""
    monkeypatch.setattr(coach_module, "record_problem_attempt_mastery", _noop_list)
    monkeypatch.setattr(coach_module, "record_problem_attempt_skill_mastery", _noop_list)
    monkeypatch.setattr(coach_module, "record_attempt_skill_event", _noop)
    monkeypatch.setattr(coach_module, "record_learning_activity", _no_session)
    yield


def _complete(session: _ScriptedSession, *, dialogue_id: uuid.UUID | None) -> uuid.UUID | None:
    attempt_id, _evidence = _run(
        coach_module._complete_problem(
            session,  # type: ignore[arg-type]
            user_id=_UID,
            problem_id=_PID,
            final_answer=None,
            started_at=_T0,
            dialogue_id=dialogue_id,
        )
    )
    return attempt_id


def _attempt_of(session: _ScriptedSession) -> ProblemAttemptORM:
    attempts = [
        obj for op, obj in session.ops if op == "add" and isinstance(obj, ProblemAttemptORM)
    ]
    assert len(attempts) == 1, session.ops
    return attempts[0]


class TestCompleteProblemWritesAttribution:
    def test_without_dialogue_used_hint_stays_null(self) -> None:
        """dialogue를 모르는 호출(생성 턴·기존 직접 호출) — 판정 없이 NULL, 이전과 같은 값."""
        session = _ScriptedSession()
        _complete(session, dialogue_id=None)
        assert _attempt_of(session).used_hint is None
        assert [op for op, _ in session.ops] == ["add", "commit"]

    def test_countable_hints_become_rows_in_the_same_commit(self) -> None:
        boundary = _T0 + timedelta(minutes=4)
        supply = _hint_rows(2, 1, 3)
        session = _ScriptedSession([[boundary], supply])
        attempt_id = _complete(session, dialogue_id=_DID)

        attempt = _attempt_of(session)
        assert attempt.attempt_id == attempt_id
        assert attempt.used_hint is True
        # 부모 행을 먼저 내보낸 뒤 자식 행 — 둘은 한 commit으로 durable해진다.
        kinds = [op for op, _ in session.ops]
        assert kinds == ["add", "flush", "add_all", "commit"], kinds
        rows = session.ops[2][1]
        assert all(isinstance(r, HintUsageORM) for r in rows)
        assert [(r.hint_level, r.requested_at) for r in rows] == [
            (2, supply[0][0]),
            (3, supply[2][0]),
        ]
        for r in rows:
            assert r.attempt_id == attempt_id and r.user_id == _UID
            # 동적 생성 힌트라 식별자가 없고, 코치 경로에는 열람 종료 신호가 없다 — 날조 금지.
            assert r.hint_id is None and r.view_duration_ms is None

    def test_direction_only_writes_false_and_no_rows(self) -> None:
        session = _ScriptedSession([[_T0 + timedelta(minutes=2)], _hint_rows(1, 1)])
        _complete(session, dialogue_id=_DID)
        assert _attempt_of(session).used_hint is False
        assert [op for op, _ in session.ops] == ["add", "commit"]

    def test_unknown_window_writes_null_and_no_rows(self) -> None:
        session = _ScriptedSession([[]])  # 정답 제출 턴 행을 못 찾았다
        _complete(session, dialogue_id=_DID)
        assert _attempt_of(session).used_hint is None
        assert [op for op, _ in session.ops] == ["add", "commit"]
