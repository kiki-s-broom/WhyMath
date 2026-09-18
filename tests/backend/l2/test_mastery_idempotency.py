"""같은 Attempt의 숙달 **이중 반영 방지** — EOS-108 acceptance ④·⑦-가 (hermetic).

왜 이것이 중요한가
------------------
KPI 2(State Integrity < 1%)는 "학습자 상태가 실제 학습 사실과 어긋난 비율"이다. 같은 시도가
두 번 반영되면 그 학생의 숙달·표본 수가 즉시 틀어지고, 그것은 표본 하나의 오차가 아니라
**학습 곡선의 형태**를 바꾼다(BKT는 누적이라 한 번 어긋난 prior가 이후 전부를 끌고 간다).

2026-09-18 이전 상태(실측): 숙달 적재 경로에 시도 식별자가 **아예 없었다**. 즉 중복을 막을
방법이 없었던 것이 아니라, 중복인지 판정할 재료가 없었다.

두 겹의 보호 — 여기서 보는 것과 보지 않는 것
--------------------------------------------
  ① **읽기측 사전 조회**(이 파일) — 정상 재시도가 예외를 거치지 않고 조용히 끝난다.
  ② **DB 부분 유니크 인덱스**(`tests/backend/l2/test_mastery_tracking_integration.py`) —
     동시 갱신 경합의 *권위*. 사전 조회는 check-then-act라 경합을 못 막으므로, 그 축은
     실 PG 통합테스트가 본다. 여기서는 그 경합이 났을 때의 **복구 경로**(IntegrityError →
     rollback → 승자 행 반환)만 시뮬로 확인한다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.assessment import ConceptMasteryHistory
from whymath_backend.l2.mastery_tracking import (
    record_attempt_mastery,
    record_problem_attempt_mastery,
)

_UID = uuid.uuid4()
_CID = uuid.uuid4()
_PID = uuid.uuid4()
_ATTEMPT = uuid.uuid4()
_NOW = datetime(2026, 9, 18, tzinfo=UTC)


def _row(attempt_id: uuid.UUID | None, mastery: float = 0.62) -> ConceptMasteryHistory:
    return ConceptMasteryHistory(
        user_id=_UID,
        concept_id=_CID,
        measured_at=_NOW,
        mastery=mastery,
        confidence=0.5,
        sample_size=5,
        attempt_id=attempt_id,
    )


class _Result:
    """`session.execute` 반환 시뮬 — `scalars().first()/.all()` 둘 다 받는다."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)


class _Session:
    """질의를 **컴파일된 SQL 텍스트로 분기**하는 시뮬 세션.

    호출 순서에 기대는 스크립트 큐 대신 이 방식을 쓴 이유: 순서 큐는 구현이 질의를 하나
    더하거나 빼는 순간 *엉뚱한 응답*을 돌려주면서도 통과해 버린다(위장). SQL 텍스트 분기는
    무엇을 묻는 질의인지로 답하므로 그런 오정렬이 생기지 않는다.
    """

    def __init__(
        self,
        *,
        assessed: list[uuid.UUID] | None = None,
        already_applied: list[ConceptMasteryHistory] | None = None,
        prior: ConceptMasteryHistory | None = None,
        commit_raises_once: bool = False,
        applied_after_conflict: list[ConceptMasteryHistory] | None = None,
    ) -> None:
        self._assessed = assessed if assessed is not None else [_CID]
        self._already = already_applied or []
        self._prior = prior
        self._commit_raises_once = commit_raises_once
        self._applied_after_conflict = applied_after_conflict or []
        self._conflicted = False
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.idempotency_queries = 0

    async def execute(self, stmt: Any) -> _Result:
        sql = str(stmt)
        if "problem_concept" in sql:
            return _Result(list(self._assessed))
        if "attempt_id" in sql and "ORDER BY" not in sql:
            # `_applied_for_attempt` — 이 시도가 이미 반영됐는가.
            self.idempotency_queries += 1
            rows = self._applied_after_conflict if self._conflicted else self._already
            return _Result(list(rows))
        # `_latest_mastery` — 직전 측정 1건.
        return _Result([self._prior] if self._prior is not None else [])

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        if self._commit_raises_once and not self._conflicted:
            self._conflicted = True
            raise IntegrityError("INSERT ...", {}, Exception("duplicate key"))
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1
        self.added.clear()


def _as_session(session: _Session) -> AsyncSession:
    return cast(AsyncSession, session)


class TestReplayIsNotApplied:
    """정상 재시도 — 같은 시도를 다시 처리해도 새 측정이 찍히지 않는다."""

    async def test_replayed_attempt_writes_nothing(self) -> None:
        applied = _row(_ATTEMPT)
        session = _Session(already_applied=[applied])
        records = await record_problem_attempt_mastery(
            _as_session(session), _UID, _PID, True, attempt_id=_ATTEMPT
        )
        assert session.added == [], "재시도가 새 측정 행을 만들었다 — 학습 곡선이 왜곡된다"
        assert session.commits == 0, "쓸 것이 없는데 커밋했다"
        assert records == [applied], "이미 반영된 측정을 그대로 돌려줘야 한다"

    async def test_single_concept_replay_writes_nothing(self) -> None:
        """단일 개념 공개 래퍼도 같은 보호를 받는다(두 진입점이 갈라지지 않게)."""
        applied = _row(_ATTEMPT)
        session = _Session(already_applied=[applied])
        row = await record_attempt_mastery(
            _as_session(session), _UID, _CID, True, attempt_id=_ATTEMPT
        )
        assert session.added == []
        assert session.commits == 0
        assert row is applied

    async def test_first_application_does_write(self) -> None:
        """**대조군** — 처음 반영은 정상적으로 쓴다.

        이것이 없으면 "항상 건너뛴다"는 과잉 수정이 위 테스트들을 전부 통과한다.
        """
        session = _Session()
        records = await record_problem_attempt_mastery(
            _as_session(session), _UID, _PID, True, attempt_id=_ATTEMPT
        )
        assert len(session.added) == 1
        assert session.commits == 1
        assert records[0].attempt_id == _ATTEMPT, "멱등 키가 행에 적재되지 않으면 다음이 못 본다"

    async def test_partial_replay_writes_only_the_missing_concept(self) -> None:
        """다개념 중 **일부만** 이미 반영된 경우 — 나머지만 쓴다(전부 건너뛰지 않는다).

        부분 반영은 실제로 일어난다(개념 A는 commit됐고 B에서 프로세스가 죽는 경우는 없지만,
        개념 집합이 매핑 변경으로 늘어난 뒤의 재처리가 정확히 이 모양이다).
        """
        other = uuid.uuid4()
        session = _Session(assessed=[_CID, other], already_applied=[_row(_ATTEMPT)])
        records = await record_problem_attempt_mastery(
            _as_session(session), _UID, _PID, True, attempt_id=_ATTEMPT
        )
        assert len(session.added) == 1
        assert session.added[0].concept_id == other
        assert len(records) == 2, "이미 반영된 것도 결과에는 포함돼야 한다(호출자가 보는 상태)"


class TestNoAttemptIdMeansNoProtection:
    """신원 없는 관측은 **조용히 합쳐지지 않는다** — 없는 보호를 있는 척하지 않는다."""

    async def test_without_attempt_id_no_idempotency_query_runs(self) -> None:
        session = _Session()
        await record_problem_attempt_mastery(_as_session(session), _UID, _PID, True)
        assert session.idempotency_queries == 0
        assert len(session.added) == 1
        assert session.added[0].attempt_id is None

    async def test_without_attempt_id_two_calls_write_twice(self) -> None:
        """멱등 키 없는 두 호출은 두 번 쓴다 — 그것이 사실이고, 숨기면 관측이 사라진다."""
        session = _Session()
        await record_problem_attempt_mastery(_as_session(session), _UID, _PID, True)
        await record_problem_attempt_mastery(_as_session(session), _UID, _PID, True)
        assert len(session.added) == 2


class TestConcurrentConflictRecovery:
    """동시 갱신 — DB 인덱스가 진 쪽에서 무엇이 일어나는가."""

    async def test_integrity_error_resolves_to_the_winner_row(self) -> None:
        """사전 조회 이후 경합이 나면 롤백 후 **승자의 행**을 돌려준다(예외 전파 없음)."""
        winner = _row(_ATTEMPT, mastery=0.71)
        session = _Session(commit_raises_once=True, applied_after_conflict=[winner])
        records = await record_problem_attempt_mastery(
            _as_session(session), _UID, _PID, True, attempt_id=_ATTEMPT
        )
        assert session.rollbacks == 1
        assert records == [winner]

    async def test_integrity_error_without_attempt_id_propagates(self) -> None:
        """멱등 키가 없으면 그 `IntegrityError`는 **멱등 위반이 아니다** — 삼키면 원인을 잃는다."""
        session = _Session(commit_raises_once=True)
        with pytest.raises(IntegrityError):
            await record_problem_attempt_mastery(_as_session(session), _UID, _PID, True)

    async def test_unrelated_integrity_error_propagates(self) -> None:
        """멱등 키가 있어도 **승자가 없으면** 다른 무결성 오류다 — 그대로 올린다."""
        session = _Session(commit_raises_once=True, applied_after_conflict=[])
        with pytest.raises(IntegrityError):
            await record_problem_attempt_mastery(
                _as_session(session), _UID, _PID, True, attempt_id=_ATTEMPT
            )
