"""SolutionPath 조회 store — 승격된 풀이 경로의 *읽기* 표면 (S4-09·D1 reader ②의 하부).

`solution_paths`(헤더·`db/models/solution_path.py`)에서 문제 단위·경로 단위로 경로를 조회한다.
쓰기는 승격 어댑터(`whs/path_promotion.py`)만 한다 — 본 모듈은 읽기 전용(commit 없음·저장소 패턴).

소비처(계층 방향):
  - L4 `scene_generation.find_step_panel_solution_path_id`가 본 모듈을 *다운콜*해
    `StepPanelElement.solution_path_id` 댕글링을 해소한다(L4→L3 — import-linter 계약 방향).
    SolutionPath는 L3 소유 엔티티(yaml `layer: L3`)라 조회 좌석도 L3에 둔다.
  - L5 `api/solution_paths`(SOL-02 점층 공개 엔드포인트)가 `get_solution_path`·
    `get_solution_path_steps`로 경로 헤더·단계를 읽는다. 단계 영속 좌석은 S4-09 결정대로
    `problem_step` additive 컬럼(`solution_path_id` FK)이라 단계 읽기도 본 store가 담당한다
    (경로 읽기 단일 표면 — 재구현 금지).
  - L4 `hint_content/store`(S4-11 힌트 오프라인 생성 원천)가 `list_step_materialized_path_ids`
    로 단계가 실체화된 경로를 열거하고, 위 두 함수로 헤더·단계를 읽는다(재구현 금지 — 같은 표면).

저장소 패턴(`whs/solution_bank.py` 선례): AsyncSession 주입·순수 ORM/쿼리빌더·결정적 정렬.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.problem import ProblemStep
from whymath_backend.db.models.solution_path import SolutionPath

__all__ = [
    "find_solution_path_id",
    "get_solution_path",
    "get_solution_path_steps",
    "get_solution_paths",
    "list_step_materialized_path_ids",
]


async def get_solution_paths(session: AsyncSession, problem_id: uuid.UUID) -> list[SolutionPath]:
    """문제의 승격된 풀이 경로 *전부*를 결정적 순서로 조회한다(검사·열람용).

    `(created_at, solution_path_id)` 정렬로 재실행에도 순서가 안정적이다.
    `idx_solution_paths_problem` 인덱스를 탄다.
    """
    stmt = (
        select(SolutionPath)
        .where(SolutionPath.problem_id == problem_id)
        .order_by(SolutionPath.created_at, SolutionPath.solution_path_id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def find_solution_path_id(session: AsyncSession, problem_id: uuid.UUID) -> str | None:
    """문제에 승격된 SolutionPath가 있으면 *첫* 경로의 id, 없으면 None.

    `StepPanelElement.solution_path_id` 결선용 최소 조회 — "첫 경로"는 결정적 순서
    (`created_at, solution_path_id`)의 첫 행이다. 다중 경로 간 *선택 정책*(선호 유형·검수
    우선 등)은 L2 `preferred_solution_style` 추적이 서는 후속 몫이라 여기서 만들지 않는다
    (`solution_module_gap_review.md` §4-⑤).
    """
    stmt = (
        select(SolutionPath.solution_path_id)
        .where(SolutionPath.problem_id == problem_id)
        .order_by(SolutionPath.created_at, SolutionPath.solution_path_id)
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalars().first()
    return row


async def get_solution_path(session: AsyncSession, solution_path_id: str) -> SolutionPath | None:
    """경로 id로 헤더 단건 조회 — 없으면 None(서빙 경로의 404 판별용)."""
    stmt = select(SolutionPath).where(SolutionPath.solution_path_id == solution_path_id)
    result = await session.execute(stmt)
    return result.scalars().first()


async def get_solution_path_steps(
    session: AsyncSession, solution_path_id: str
) -> list[ProblemStep]:
    """경로의 실체화 단계(`problem_step` additive 좌석)를 step_order 순으로 조회한다.

    `UNIQUE(problem_id, step_order)` 제약상 한 문제에 한 경로의 단계만 실체화되므로
    (`db/models/problem.py` ProblemStep docstring) step_order 단일 정렬이 결정적이다.
    승격 어댑터는 단계 내용을 `expected_answer`에 싣는다(`whs/path_promotion.py` —
    `SolutionStep.content`의 영속 좌석). 쓰기 시점에 내용 비어있음은 차단되지만
    (`skipped_empty_steps`), 깨진 행 하나가 응답 전체를 깨지 않게 NULL 내용 행은 방어적으로
    제외한다 — 총수 집계도 이 필터 기준(서빙 가능분)으로 자기정합이다.
    """
    stmt = (
        select(ProblemStep)
        .where(
            ProblemStep.solution_path_id == solution_path_id,
            ProblemStep.expected_answer.isnot(None),
        )
        .order_by(ProblemStep.step_order)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_step_materialized_path_ids(session: AsyncSession) -> list[str]:
    """단계가 `problem_step`에 실체화된 경로 id 전부 — 결정적 정렬(S4-11 힌트 생성 원천 열거).

    문제당 대표 1경로만 단계가 실체화되므로(`whs/path_promotion.py` S4-10 재론) 이 목록은 곧
    "단계 단위 산출물(힌트 등)을 만들 수 있는 경로"다. 헤더만 있는 추가 경로는 단계가 없어
    포함되지 않는다. 내용 NULL 행만 가진 경로는 `get_solution_path_steps`와 같은 기준으로 뺀다.
    """
    stmt = (
        select(ProblemStep.solution_path_id)
        .where(
            ProblemStep.solution_path_id.isnot(None),
            ProblemStep.expected_answer.isnot(None),
        )
        .distinct()
        .order_by(ProblemStep.solution_path_id)
    )
    result = await session.execute(stmt)
    return [path_id for path_id in result.scalars().all() if path_id is not None]
