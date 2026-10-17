"""전략 메타 PG 프로젝션 적재 *단위테스트* — Phase 6a (hermetic·PG 불요).

`StrategyNodeStore`의 실 라운드트립은 통합테스트로 미루고, 여기서는 PG 없이 검증 가능한 것만
못 박는다(`test_formula_node_projection.py` 가짜 엔진 패턴 미러):

  ① graph.json 로딩 — strategy_id 키 + 안전 메타(name_ko/family/description/standard_codes)
  ② 필수 필드 누락 graceful — strategy_id/name_ko/family/description 누락이면 skip
  ③ upsert SQL 구성 — ON CONFLICT(strategy_id)·review_status 상수·안전 메타 컬럼(enum 없음)
  ④ populate — 전 레코드 upsert(횟수=레코드 수)
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType

from whymath_backend.db.models.strategy_node import STRATEGY_REVIEW_STATUS_DEFAULT
from whymath_backend.l1.strategy_graph.strategy_node_projection import (
    StrategyNodeRecord,
    StrategyNodeStore,
    load_strategies_from_graph_json,
    populate_strategy_nodes,
)


class _FakeResult:
    """적재 upsert 결과 흉내 — RETURNING이 키 1행을 돌려준 상태(=적재됨). P3-25 보호 판정이 읽는다."""

    def first(self) -> tuple[int]:
        return (1,)


class _FakeConnection:
    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def execute(self, statement: object) -> _FakeResult:
        self._engine.executed.append(statement)
        return _FakeResult()


class _FakeEngine:
    """SQLAlchemy sync Engine 최소 흉내 — begin() + 실행 statement 기록."""

    def __init__(self) -> None:
        self.executed: list[object] = []

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)


def _fake_store() -> tuple[StrategyNodeStore, _FakeEngine]:
    engine = _FakeEngine()
    store = StrategyNodeStore(engine=engine)  # type: ignore[arg-type]
    return store, engine


def _write_graph(tmp_path: Path, strategies: list[dict[str, object]]) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(json.dumps({"strategies": strategies}, ensure_ascii=False), encoding="utf-8")
    return path


def _record(strategy_id: str = "strategy.work_backward") -> StrategyNodeRecord:
    return StrategyNodeRecord(
        strategy_id=strategy_id,
        name_ko="역방향 공략",
        family="reduction",
        description="구해야 할 목표에서 출발해 필요 조건을 거슬러 올라간다.",
        standard_codes=(),
    )


def _compile(stmt: object) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": False}))  # type: ignore[attr-defined]


class TestLoadFromGraphJson:
    def test_loads_safe_meta(self, tmp_path: Path) -> None:
        path = _write_graph(
            tmp_path,
            [
                {
                    "strategy_id": "strategy.specialize",
                    "name_ko": "특수화",
                    "family": "reduction",
                    "description": "일반 문제를 특수값·소규모 사례로 좁혀 실마리를 얻는다.",
                    "standard_codes": ["9수02-15"],
                }
            ],
        )
        rec = load_strategies_from_graph_json(path)[0]
        assert rec.strategy_id == "strategy.specialize"
        assert rec.family == "reduction"
        assert rec.name_ko == "특수화"
        assert rec.standard_codes == ("9수02-15",)

    def test_missing_required_skipped(self, tmp_path: Path) -> None:
        path = _write_graph(
            tmp_path,
            [
                {
                    "strategy_id": "strategy.ok",
                    "name_ko": "x",
                    "family": "reduction",
                    "description": "설명",
                },
                {"strategy_id": "strategy.no-desc", "name_ko": "x", "family": "reduction"},
            ],
        )
        loaded = load_strategies_from_graph_json(path)
        assert [r.strategy_id for r in loaded] == ["strategy.ok"]

    def test_standard_codes_default_empty(self, tmp_path: Path) -> None:
        path = _write_graph(
            tmp_path,
            [
                {
                    "strategy_id": "strategy.x",
                    "name_ko": "x",
                    "family": "indirect",
                    "description": "설명",
                }
            ],
        )
        assert load_strategies_from_graph_json(path)[0].standard_codes == ()


class TestUpsertSql:
    def test_upsert_on_conflict_strategy_id(self) -> None:
        store, engine = _fake_store()
        store.upsert(_record())
        compiled = _compile(engine.executed[0])
        assert "INSERT INTO strategy_node" in compiled
        assert "ON CONFLICT" in compiled
        assert "(strategy_id)" in compiled or "strategy_node.strategy_id" in compiled

    def test_upsert_includes_safe_meta_columns(self) -> None:
        store, engine = _fake_store()
        store.upsert(_record())
        compiled = _compile(engine.executed[0])
        for col in ("strategy_id", "name_ko", "family", "description", "review_status"):
            assert col in compiled

    def test_review_status_is_ai_estimated_constant(self) -> None:
        assert STRATEGY_REVIEW_STATUS_DEFAULT == "ai_estimated"


class TestPopulate:
    def test_populate_upserts_all(self) -> None:
        store, engine = _fake_store()
        count = populate_strategy_nodes(
            [_record("strategy.analogy"), _record("strategy.contradiction")], store=store
        )
        assert count == 2
        assert len(engine.executed) == 2
