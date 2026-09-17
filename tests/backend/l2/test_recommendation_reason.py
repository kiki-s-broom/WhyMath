"""EOS-14 추천 근거 조회기 — 조회 재사용·쓰기 0·선택 비관여 (hermetic·FakeSession).

가장 중요한 축은 **선택 비관여**(acceptance ⑥)다. 근거 배선이 추천 결과를 바꿀 수 있는
구조였다면 "계약 교체가 추천을 바꾸지 않았다"를 증명할 방법이 없다. 그래서 두 가지를 잰다:
  · 조회기가 쓰기를 하지 않는다(상태 무변경)
  · `problem_id=None`이면 조회 자체를 하지 않는다(없는 문항의 개념을 묻지 않는다)

계약 규칙(구간·경계·필수 reason)은 `test_recommendation_contract.py`가 본다.
"""

from __future__ import annotations

import inspect
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2.recommendation_contract import ReasonBasis, ReasonType
from whymath_backend.l2.recommendation_reason import collect_recommendation_reason
from whymath_backend.schema.enums import ConceptRole

_LEARNER = uuid.uuid4()
_PROBLEM = uuid.uuid4()
_CONCEPT = uuid.uuid4()


@dataclass
class _MasteryRow:
    mastery: float | None
    confidence: float | None
    measured_at: datetime = datetime(2026, 9, 17, tzinfo=UTC)


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

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _FakeSession:
    """대상 테이블로 분기 — `problem_concept`(대표 개념) / `concept_mastery_history`(최신 측정).

    파라미터 모양만 보고 분기하면 role 없는 조회에서 오판한다(EOS-12 픽스처에서 실측한 함정).
    """

    def __init__(
        self,
        *,
        primary: list[uuid.UUID] | None = None,
        tested: list[uuid.UUID] | None = None,
        mastery_row: _MasteryRow | None = None,
    ) -> None:
        self.primary = primary or []
        self.tested = tested or []
        self.mastery_row = mastery_row
        self.added: list[Any] = []
        self.commits = 0
        self.executes = 0

    async def execute(self, stmt: Any) -> _Result:
        self.executes += 1
        text = str(stmt)
        if "problem_concept" in text:
            values = [
                v
                for p in stmt.compile().params.values()
                for v in (p if isinstance(p, list) else [p])
            ]
            roles = [v for v in values if isinstance(v, ConceptRole)]
            out: list[uuid.UUID] = []
            if ConceptRole.PRIMARY in roles:
                out += self.primary
            if ConceptRole.TESTED in roles:
                out += self.tested
            return _Result(out)
        return _Result([self.mastery_row] if self.mastery_row is not None else [])

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


async def _collect(session: _FakeSession, problem_id: uuid.UUID | None = _PROBLEM) -> Any:
    return await collect_recommendation_reason(
        cast(AsyncSession, session), learner_id=_LEARNER, problem_id=problem_id
    )


class TestCollect:
    async def test_measured_mastery_produces_a_band_reason(self) -> None:
        session = _FakeSession(primary=[_CONCEPT], mastery_row=_MasteryRow(0.25, 0.5))
        reason = await _collect(session)
        assert reason.type is ReasonType.PREREQUISITE_GAP
        assert reason.basis is ReasonBasis.MEASURED_MASTERY
        assert reason.concept_id == _CONCEPT
        assert reason.mastery == pytest.approx(0.25)
        assert reason.confidence == pytest.approx(0.5)

    async def test_tested_fallback_is_used_when_primary_is_absent(self) -> None:
        """대표 개념 조회는 PRIMARY→TESTED 폴백을 이미 소유한 좌석을 그대로 쓴다(재구현 0)."""
        session = _FakeSession(tested=[_CONCEPT], mastery_row=_MasteryRow(0.9, 0.8))
        reason = await _collect(session)
        assert reason.concept_id == _CONCEPT
        assert reason.type is ReasonType.NEXT_CONCEPT

    async def test_unmapped_problem_reports_data_gap_not_student_state(self) -> None:
        session = _FakeSession()
        reason = await _collect(session)
        assert reason.type is ReasonType.UNMEASURED
        assert reason.basis is ReasonBasis.CONCEPT_UNMAPPED

    async def test_cold_start_reports_student_state_not_data_gap(self) -> None:
        session = _FakeSession(primary=[_CONCEPT], mastery_row=None)
        reason = await _collect(session)
        assert reason.type is ReasonType.UNMEASURED
        assert reason.basis is ReasonBasis.COLD_START
        assert reason.concept_id == _CONCEPT

    async def test_null_mastery_column_is_cold_start_not_zero(self) -> None:
        """측정 행은 있는데 mastery가 NULL — 0.0으로 접으면 없는 약점이 생긴다."""
        session = _FakeSession(primary=[_CONCEPT], mastery_row=_MasteryRow(None, 0.4))
        reason = await _collect(session)
        assert reason.basis is ReasonBasis.COLD_START
        assert reason.mastery is None


class TestCollectorDoesNotTouchSelection:
    """acceptance ⑥ — 근거 배선이 추천 결과를 바꿀 수 있는 구조가 아님을 잰다."""

    @pytest.mark.parametrize("problem_id", [_PROBLEM, None])
    async def test_no_writes(self, problem_id: uuid.UUID | None) -> None:
        session = _FakeSession(primary=[_CONCEPT], mastery_row=_MasteryRow(0.5, 0.5))
        await _collect(session, problem_id)
        assert session.added == []
        assert session.commits == 0

    async def test_absent_recommendation_costs_zero_queries(self) -> None:
        """없는 문항의 개념을 묻지 않는다 — 근거를 댈 대상이 없다."""
        session = _FakeSession()
        reason = await _collect(session, None)
        assert session.executes == 0
        assert reason.type is ReasonType.NO_CANDIDATE

    async def test_present_recommendation_costs_exactly_two_queries(self) -> None:
        """비용을 숫자로 못 박는다 — 조용히 늘면 이 테스트가 깨진다(정직 표기의 기계 축)."""
        session = _FakeSession(primary=[_CONCEPT], mastery_row=_MasteryRow(0.5, 0.5))
        await _collect(session)
        assert session.executes == 2

    async def test_tested_fallback_costs_one_more_query_than_primary_hit(self) -> None:
        """PRIMARY가 비면 TESTED를 한 번 더 묻는다 — 비용은 2가 아니라 3이다.

        모듈 docstring의 "2건 또는 3건" 표기가 *어느 경우에* 3인지까지 못 박는다. 2만
        재면 폴백 경로의 비용이 표기에서 조용히 빠진다(정직 표기가 반쪽이 된다).
        """
        session = _FakeSession(tested=[_CONCEPT], mastery_row=_MasteryRow(0.5, 0.5))
        reason = await _collect(session)
        assert session.executes == 3
        assert reason.concept_id == _CONCEPT  # 폴백으로 잡힌 개념이 근거에 실린다

    async def test_unmapped_problem_stops_before_the_mastery_query(self) -> None:
        """PRIMARY·TESTED 둘 다 비면 숙달을 묻지 않는다 — 물을 대상이 없다(조회 2건에서 정지)."""
        session = _FakeSession(mastery_row=_MasteryRow(0.5, 0.5))
        reason = await _collect(session)
        assert session.executes == 2
        assert reason.basis is ReasonBasis.CONCEPT_UNMAPPED
        assert reason.mastery is None  # 큐에 숙달 행이 있어도 읽지 않는다(경로 자체가 다르다)

    def test_module_source_has_no_write_calls(self) -> None:
        from whymath_backend.l2 import recommendation_reason

        body = "\n".join(
            line
            for line in inspect.getsource(recommendation_reason).splitlines()
            if not line.strip().startswith("#")
        )
        assert "session.add(" not in body
        assert "session.commit(" not in body

    def test_module_does_not_import_a_selector(self) -> None:
        """선택기를 import하면 언젠가 부르게 된다 — 구조적으로 닫아 둔다."""
        from whymath_backend.l2 import recommendation_reason

        source = inspect.getsource(recommendation_reason)
        for selector in ("select_weighted_item", "recommend_suneung_index", "item_information"):
            assert selector not in source
