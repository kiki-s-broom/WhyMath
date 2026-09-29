"""SolutionPath 조회 store(`l3/solution_path_store.py`) 테스트 — S4-09 (hermetic).

FakeSession(execute 표면만)으로 결선 검증: 결정적 정렬 조회(`get_solution_paths`)·첫 경로 id
단건(`find_solution_path_id` — StepPanelElement 결선의 하부). 실 SQL·인덱스 사용은 실 PG
통합 몫(`test_solution_bank.py` 이원화 선례).
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.problem import ProblemStep
from whymath_backend.db.models.solution_path import SolutionPath
from whymath_backend.l3.solution_path_store import (
    find_solution_path_id,
    get_solution_path,
    get_solution_path_steps,
    get_solution_paths,
    list_step_materialized_path_ids,
)


class _FakeScalars:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return self._items

    def first(self) -> Any | None:
        return self._items[0] if self._items else None


class _FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._items)


class _FakeSession:
    def __init__(self, items: list[Any]) -> None:
        self._items = items
        self.executed = 0

    async def execute(self, _stmt: Any) -> _FakeResult:
        self.executed += 1
        return _FakeResult(self._items)


def _orm_path(path_id: str) -> SolutionPath:
    return SolutionPath(
        solution_path_id=path_id,
        problem_id=uuid.uuid4(),
        approach_type="algebraic",
        concept_sequence=[],
        verified_by_human=False,
    )


def _step_row(step_order: int) -> ProblemStep:
    """가짜 단계 행 — ORM 인스턴스(속성 접근만 쓰이므로 세션 부착 불필요)."""
    return ProblemStep(step_order=step_order, expected_answer=f"{step_order}단계 내용")


class TestGetSolutionPaths:
    @pytest.mark.asyncio
    async def test_returns_rows_as_list(self) -> None:
        """조회 행을 리스트로 반환(읽기 전용·commit 없음)."""
        rows = [_orm_path("sp-1"), _orm_path("sp-2")]
        session = _FakeSession(rows)
        out = await get_solution_paths(cast(AsyncSession, session), uuid.uuid4())
        assert out == rows
        assert session.executed == 1

    @pytest.mark.asyncio
    async def test_empty_when_no_paths(self) -> None:
        out = await get_solution_paths(cast(AsyncSession, _FakeSession([])), uuid.uuid4())
        assert out == []


class TestFindSolutionPathId:
    @pytest.mark.asyncio
    async def test_returns_first_id(self) -> None:
        """첫 경로 id 반환 — StepPanelElement.solution_path_id 결선 재료."""
        session = _FakeSession(["sp-first", "sp-second"])
        assert await find_solution_path_id(cast(AsyncSession, session), uuid.uuid4()) == "sp-first"

    @pytest.mark.asyncio
    async def test_none_when_no_promoted_path(self) -> None:
        """승격 경로 없으면 None — 댕글링 참조를 만들 근거 없음(날조 금지)."""
        session = cast(AsyncSession, _FakeSession([]))
        assert await find_solution_path_id(session, uuid.uuid4()) is None


class TestGetSolutionPath:
    """경로 id 단건 조회 — 점층 공개 엔드포인트(SOL-02)의 404 판별 재료."""

    @pytest.mark.asyncio
    async def test_returns_header_when_found(self) -> None:
        row = _orm_path("sp-1")
        session = _FakeSession([row])
        out = await get_solution_path(cast(AsyncSession, session), "sp-1")
        assert out is row
        assert session.executed == 1

    @pytest.mark.asyncio
    async def test_none_when_missing(self) -> None:
        """없는 id → None(엔드포인트가 404로 매핑 — 빈 200 금지)."""
        out = await get_solution_path(cast(AsyncSession, _FakeSession([])), "sp-ghost")
        assert out is None


class TestGetSolutionPathSteps:
    """경로 단계 조회(problem_step additive 좌석) — step_order 순·읽기 전용."""

    @pytest.mark.asyncio
    async def test_returns_step_rows_as_list(self) -> None:
        rows = [_step_row(1), _step_row(2)]
        session = _FakeSession(rows)
        out = await get_solution_path_steps(cast(AsyncSession, session), "sp-1")
        assert out == rows
        assert session.executed == 1

    @pytest.mark.asyncio
    async def test_empty_when_no_steps(self) -> None:
        out = await get_solution_path_steps(cast(AsyncSession, _FakeSession([])), "sp-1")
        assert out == []


class _CapturingSession(_FakeSession):
    """실행 문장을 컴파일해 남기는 가짜 — 조회 조건이 실재하는지 확인용."""

    def __init__(self, items: list[Any]) -> None:
        super().__init__(items)
        self.sql: list[str] = []

    async def execute(self, stmt: Any) -> _FakeResult:
        self.sql.append(str(stmt.compile()))
        return await super().execute(stmt)


class TestListStepMaterializedPathIds:
    """S4-11 — 힌트 생성 원천 열거(단계가 실체화된 경로만·NULL 방어·결정적 정렬)."""

    @pytest.mark.asyncio
    async def test_returns_distinct_ordered_ids_and_drops_null(self) -> None:
        session = _CapturingSession(["sp-a", None, "sp-b"])
        out = await list_step_materialized_path_ids(cast(AsyncSession, session))
        assert out == ["sp-a", "sp-b"]
        sql = session.sql[0]
        assert "DISTINCT" in sql
        assert "problem_step.solution_path_id IS NOT NULL" in sql
        # 내용 NULL 행만 가진 경로는 뺀다(get_solution_path_steps와 같은 서빙 가능 기준).
        assert "problem_step.expected_answer IS NOT NULL" in sql
        assert "ORDER BY problem_step.solution_path_id" in sql
