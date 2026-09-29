"""hint_content 테스트 공용 가짜 — `hints` 표 메모리 세션(실제 문장의 WHERE 조건으로만 거른다).

가짜가 조건을 *스스로 보태지 않는다*는 점이 핵심이다 — reader에서 `verified IS true`가 빠지면 가짜도
미검수 행을 돌려주므로, 그 경우의 이중 가드(행 재확인)를 볼 수 있다. 실 PG 왕복은
`tests/backend/db/test_hints_migration_integration.py`(integration 마커) 소관이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from whymath_backend.db.models.hint import Hint as HintORM


class _Scalars:
    def __init__(self, rows: Sequence[Any]) -> None:
        self._rows = list(rows)

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows: Sequence[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _HintTableSession:
    """`hints` 표를 메모리에 두고 writer·reader의 실제 문장 조건으로만 거르는 가짜 세션."""

    def __init__(self, rows: Sequence[HintORM] = ()) -> None:
        self.rows: dict[str, HintORM] = {row.hint_id: row for row in rows}
        self._pending: list[HintORM] = []
        self.executed: list[str] = []
        self.commits = 0

    def add(self, obj: HintORM) -> None:
        self._pending.append(obj)

    async def flush(self) -> None:
        for obj in self._pending:
            self.rows[obj.hint_id] = obj
        self._pending.clear()

    async def commit(self) -> None:
        await self.flush()
        self.commits += 1

    async def execute(self, stmt: Any) -> _Result:
        compiled = stmt.compile()
        sql = str(compiled)
        params = compiled.params
        self.executed.append(sql)
        rows = list(self.rows.values())
        if "hints.hint_id IN" in sql:
            wanted = set(params["hint_id_1"])
            return _Result([r for r in rows if r.hint_id in wanted])
        if "hints.solution_path_id IN" in sql:
            paths = set(params["solution_path_id_1"])
            picked = [r for r in rows if r.solution_path_id in paths]
            if "hints.verified IS true" in sql:
                picked = [r for r in picked if r.verified is True]
            return _Result(picked)
        if "hints.problem_id = " in sql:
            picked = [
                r
                for r in rows
                if r.problem_id == params["problem_id_1"] and r.level == params["level_1"]
            ]
            if "hints.verified IS true" in sql:
                picked = [r for r in picked if r.verified is True]
            if "step_order_1" in params:
                picked = [r for r in picked if r.step_order >= params["step_order_1"]]
            picked.sort(key=lambda r: (r.step_order, r.solution_path_id))
            return _Result(picked[: params.get("param_1", len(picked))])
        raise AssertionError(f"예상 밖 문장: {sql}")
