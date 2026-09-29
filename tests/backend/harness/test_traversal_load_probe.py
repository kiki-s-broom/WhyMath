"""traversal 성능 예산 실부하 판정 CLI 테스트 — 구조 계산·측정 루프·판정의 변별력 (hermetic).

대상: `whymath_backend.harness.traversal_load_probe`(S4-01 슬라이스 2). 실 DB·네트워크 0 —
실 SQL 경로는 CI `backend-migrations` 잡이 적재 후 CLI를 실제로 돌려 검증한다(배선 동결 =
`tests/infra/test_traversal_load_probe_wiring.py`).

**변별력**(CLAUDE.md "보호 장치를 실패 주입 없이 보호 있음으로 선언 금지"):
  - 판정기는 결함마다 주입 입력을 따로 둔다 — 시간 예산 초과·시간 초과·예외·결과 불일치·샘플
    누락·앵커 0건·코퍼스 드리프트·엣지 드리프트. 각각 RED여야 하고, 결함 없는 대조군은 GREEN.
  - 구조 계산은 diamond에서 **원시 행(경로 수)과 중복 제거 집합이 갈라지는** 입력을 쓴다 —
    둘이 같은 값을 내는 입력으로는 `UNION ALL` 의미를 검증할 수 없다.
  - 정책 형태가 서빙 코드의 실제 함수(`_budgeted_prerequisites`·`_apply_node_budget`)를 부르는지
    스파이로 실측한다(복제 구현이었다면 스파이가 안 불린다).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import traversal_load_probe as tlp
from whymath_backend.l2.prerequisite_recommendation import MAX_PREREQUISITE_DEPTH
from whymath_backend.l2.recommendation_policy import ConceptGraphBudget

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REAL_GRAPH = _REPO_ROOT / "data/corpus/atom_graph_v1/graph.json"


def _diamond() -> tlp.GraphIndex:
    """A→B, A→C, B→D, C→D (+ D→E). D의 깊이 2: 원시 행 4(B,C,A,A) · 중복 제거 {A,B,C}."""
    return tlp.build_index(
        ["A", "B", "C", "D", "E"],
        [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"), ("D", "E")],
    )


def _write_graph(path: Path, concepts: list[str], edges: list[tuple[str, str]]) -> Path:
    payload = {
        "concepts": [{"code": c, "name": c, "level": "세부개념"} for c in concepts],
        "edges": [
            {"from_code": f, "to_code": t, "relation": "prerequisite", "strength": 0.8}
            for f, t in edges
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ──────────────────────────────────────────────────────────────────────────
# 1. 색인 — 적재기와 같은 필터
# ──────────────────────────────────────────────────────────────────────────
def test_build_index_drops_self_edges_dedups_pairs_and_counts_orphans() -> None:
    index = tlp.build_index(
        ["A", "B"], [("A", "B"), ("A", "B"), ("A", "A"), ("A", "Z"), ("Y", "B")]
    )
    assert index.edge_count == 1  # 중복 쌍 1건(DB UNIQUE와 동형)
    assert index.orphan_edges == 2  # 양끝 중 하나가 노드 밖
    assert index.preds == {"B": ("A",)}
    assert index.succs == {"A": ("B",)}


# ──────────────────────────────────────────────────────────────────────────
# 2. 구조 계산 — 재귀 CTE(UNION ALL) 의미
# ──────────────────────────────────────────────────────────────────────────
def test_trace_counts_paths_as_raw_rows_but_dedups_ancestors() -> None:
    index = _diamond()
    d1 = tlp.trace_prerequisites(index, "D", 1)
    d2 = tlp.trace_prerequisites(index, "D", 2)
    assert (d1.raw_rows, d1.ancestors) == (2, frozenset({"B", "C"}))
    # 원시 행과 중복 제거 집합이 **갈라지는** 입력 — 둘을 혼동하는 구현은 여기서 깨진다.
    assert (d2.raw_rows, d2.ancestors) == (4, frozenset({"A", "B", "C"}))


def test_trace_is_bounded_by_depth() -> None:
    index = _diamond()
    assert tlp.trace_prerequisites(index, "E", 1).ancestors == frozenset({"D"})
    assert tlp.trace_prerequisites(index, "E", 2).ancestors == frozenset({"B", "C", "D"})
    assert tlp.trace_prerequisites(index, "E", 3).ancestors == frozenset({"A", "B", "C", "D"})
    assert tlp.trace_prerequisites(index, "A", 5).ancestors == frozenset()


def test_trace_raises_on_path_explosion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tlp, "RAW_ROW_GUARD", 3)
    with pytest.raises(tlp.StructuralExplosionError):
        tlp.trace_prerequisites(_diamond(), "E", 3)


def test_census_counts_budget_binding_anchors() -> None:
    census = tlp.structural_census(_diamond(), depths=(1, 3), policy_nodes=2, route_cap=3)
    by_depth = {d.depth: d for d in census.depths}
    assert by_depth[1].zero_prerequisite_anchors == 1  # A만
    assert by_depth[1].over_policy_nodes == 0
    # 깊이 3: D {A,B,C}=3 · E {A,B,C,D}=4 → 노드 예산 2 초과 2건 · 라우트 상한 3 초과 1건(E)
    assert by_depth[3].over_policy_nodes == 2
    assert by_depth[3].over_route_cap == 1
    assert (by_depth[3].ancestors_max, by_depth[3].ancestors_max_anchor) == (4, "E")
    assert (census.successors_max, census.successors_max_anchor) == (2, "A")


def test_load_index_overlays_extra_edge_files(tmp_path: Path) -> None:
    graph = _write_graph(tmp_path / "g.json", ["A", "B", "C"], [("A", "B")])
    extra = _write_graph(tmp_path / "x.json", [], [("B", "C")])
    assert tlp.load_index(graph).edge_count == 1
    merged = tlp.load_index(graph, [extra])
    assert merged.edge_count == 2
    assert tlp.trace_prerequisites(merged, "C", 2).ancestors == frozenset({"A", "B"})


def test_real_corpus_census_is_internally_consistent() -> None:
    """실 코퍼스 — 수치를 못 박지 않고(콘텐츠 증가를 막지 않게) 구조 불변식만 확인한다."""
    index = tlp.load_index(_REAL_GRAPH)
    payload = json.loads(_REAL_GRAPH.read_text(encoding="utf-8"))
    census = tlp.structural_census(index)
    assert census.nodes == len(payload["concepts"]) > 0
    assert census.orphan_edges == 0
    maxima = [d.ancestors_max for d in census.depths]
    assert maxima == sorted(maxima)  # 깊이가 늘면 선수 집합은 줄지 않는다
    assert [d.depth for d in census.depths] == [1, 2, MAX_PREREQUISITE_DEPTH]


# ──────────────────────────────────────────────────────────────────────────
# 3. 기대 결과 판정기
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("got", "ok"),
    [
        (["A", "B"], True),  # 대조군 — 집합 동일
        (["A"], False),  # 개수 부족
        (["A", "B", "Z"], False),  # 기대 밖 원소 + 개수 초과
        # 개수는 맞고 원소만 틀린 반례 — 위 줄은 개수 판정에도 걸려 "기대 밖" 절을 단독으로
        # 밟지 않는다(뮤테이션 M6 생존으로 실측). 이 줄이 그 절의 반례다.
        (["A", "Z"], False),
        (["A", "A"], False),  # 중복 결과
        ([], False),  # 빈 결과("빨리 돌려준 빈 결과" 회귀)
    ],
)
def test_subset_check_uncapped(got: list[str], ok: bool) -> None:
    check = tlp._subset_check(lambda _code: frozenset({"A", "B"}), cap=20)
    assert (check("X", got) is None) is ok


def test_subset_check_capped_accepts_any_cap_sized_subset() -> None:
    check = tlp._subset_check(lambda _code: frozenset({"A", "B", "C"}), cap=2)
    assert check("X", ["C", "A"]) is None
    assert check("X", ["A"]) is not None
    assert check("X", ["A", "B", "C"]) is not None


# ──────────────────────────────────────────────────────────────────────────
# 4. 측정 루프 — 가짜 세션·가짜 형태로 결함 주입
# ──────────────────────────────────────────────────────────────────────────
class _FakeSession:
    def __init__(self) -> None:
        self.rollbacks = 0

    async def rollback(self) -> None:
        self.rollbacks += 1


def _factory() -> Any:
    @asynccontextmanager
    async def make() -> Any:
        yield _FakeSession()

    return make


_ANCHORS = [(uuid.uuid4(), f"C{i}") for i in range(12)]
_EXPECT = {code: frozenset({f"{code}-p"}) for _, code in _ANCHORS}


def _shape(call: Any, *, budgeted: bool = True) -> tlp.TraversalShape:
    return tlp.TraversalShape(
        name="fake",
        call=call,
        check=tlp._subset_check(lambda code: _EXPECT[code], cap=20),
        budgeted=budgeted,
    )


def _code_of(cid: uuid.UUID) -> str:
    return next(code for i, code in _ANCHORS if i == cid)


async def _correct(_session: Any, cid: uuid.UUID) -> list[str]:
    return sorted(_EXPECT[_code_of(cid)])


async def _measure(call: Any, **kw: Any) -> tlp.ShapeMeasurement:
    return await tlp.measure_shape(
        _factory(),
        _shape(call),
        _ANCHORS,
        concurrency=kw.pop("concurrency", 3),
        budget_seconds=kw.pop("budget_seconds", 1.0),
        **kw,
    )


async def test_measure_control_is_clean_and_covers_every_anchor_once() -> None:
    seen: list[uuid.UUID] = []

    async def call(session: Any, cid: uuid.UUID) -> list[str]:
        seen.append(cid)
        return await _correct(session, cid)

    m = await _measure(call, concurrency=4)
    assert m.samples == len(_ANCHORS)
    assert sorted(seen) == sorted(cid for cid, _ in _ANCHORS)  # 동시성에서도 앵커당 정확히 1회
    assert (m.over_budget, m.timeouts, m.errors, m.mismatches) == (0, 0, {}, 0)
    assert tlp.fail_reasons([m], expected_samples=len(_ANCHORS)) == []


async def test_measure_counts_latency_over_budget() -> None:
    async def slow(session: Any, cid: uuid.UUID) -> list[str]:
        await asyncio.sleep(0.02)
        return await _correct(session, cid)

    m = await _measure(slow, budget_seconds=0.005)
    assert m.over_budget == len(_ANCHORS)
    assert tlp.fail_reasons([m], expected_samples=len(_ANCHORS))


async def test_measure_counts_hard_ceiling_timeouts() -> None:
    async def hang(_session: Any, _cid: uuid.UUID) -> list[str]:
        await asyncio.sleep(10)
        return []

    m = await _measure(hang, hard_ceiling_seconds=0.01, concurrency=len(_ANCHORS))
    assert m.timeouts == len(_ANCHORS)
    assert m.samples == len(_ANCHORS)
    assert tlp.fail_reasons([m], expected_samples=len(_ANCHORS))


async def test_measure_counts_errors_by_type_name_and_rolls_back() -> None:
    async def boom(_session: Any, _cid: uuid.UUID) -> list[str]:
        raise LookupError("값은 남기지 않는다")

    m = await _measure(boom)
    assert m.errors == {"LookupError": len(_ANCHORS)}
    assert m.samples == 0
    reasons = tlp.fail_reasons([m], expected_samples=len(_ANCHORS))
    assert any("예외" in r for r in reasons)
    assert any("샘플" in r for r in reasons)  # 예외로 빠진 앵커가 조용히 사라지지 않는다


async def test_measure_counts_result_mismatches() -> None:
    async def empty(_session: Any, _cid: uuid.UUID) -> list[str]:
        return []

    m = await _measure(empty)
    assert m.mismatches == len(_ANCHORS)
    assert len(m.mismatch_examples) == tlp._MISMATCH_EXAMPLES
    assert tlp.fail_reasons([m], expected_samples=len(_ANCHORS))


# ──────────────────────────────────────────────────────────────────────────
# 5. 판정기 — 측정 불성립(exit 2) 사유
# ──────────────────────────────────────────────────────────────────────────
def _coverage(**over: int) -> tlp.Coverage:
    base = dict(
        db_concepts=5, db_edges=4, corpus_concepts=5, corpus_edges=4, missing_in_db=0, extra_in_db=0
    )
    base.update(over)
    return tlp.Coverage(**base)


@pytest.mark.parametrize(
    ("over", "valid"),
    [
        ({}, True),  # 대조군
        ({"db_concepts": 0, "db_edges": 0, "missing_in_db": 5}, False),  # 적재 전 측정
        # 코퍼스도 비면 드리프트 0이다 — "개념 0건" 절만이 막는다(그 절의 반례).
        ({"db_concepts": 0, "db_edges": 0, "corpus_concepts": 0, "corpus_edges": 0}, False),
        ({"missing_in_db": 1}, False),  # DB 누락
        ({"extra_in_db": 1}, False),  # DB 초과
        ({"db_edges": 3}, False),  # 엣지 드리프트(개념은 같음)
    ],
)
def test_invalid_reasons(over: dict[str, int], valid: bool) -> None:
    assert (tlp.invalid_reasons(_coverage(**over)) == []) is valid


def test_fail_reasons_rejects_empty_measurement_list() -> None:
    assert tlp.fail_reasons([], expected_samples=0)


# ──────────────────────────────────────────────────────────────────────────
# 6. 정책 형태가 서빙 코드의 실제 함수를 부른다
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class _Row:
    concept_id: uuid.UUID
    concept_code: str | None


async def test_policy_shape_calls_real_budgeted_path_and_applies_node_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[ConceptGraphBudget] = []
    rows = [_Row(uuid.uuid4(), f"P{i}") for i in range(25)]

    async def spy(_session: Any, _cid: uuid.UUID, budget: ConceptGraphBudget) -> list[_Row]:
        calls.append(budget)
        return rows

    monkeypatch.setattr(tlp, "_budgeted_prerequisites", spy)
    budget = ConceptGraphBudget()
    index = tlp.build_index(["X", *(r.concept_code for r in rows)], [])
    shape = next(s for s in tlp.build_shapes(index, budget) if s.name == "policy_prerequisites")
    got = await shape.call(_FakeSession(), uuid.uuid4())  # type: ignore[arg-type]
    assert calls == [budget]
    assert len(got) == budget.max_nodes  # `_apply_node_budget`가 실제로 잘랐다


def test_build_shapes_marks_route_shape_unbudgeted() -> None:
    shapes = tlp.build_shapes(_diamond(), ConceptGraphBudget())
    by_name = {s.name: s.budgeted for s in shapes}
    assert by_name == {
        "policy_prerequisites": True,
        "policy_successors": True,
        f"route_prerequisites_depth{MAX_PREREQUISITE_DEPTH}": False,
    }


# ──────────────────────────────────────────────────────────────────────────
# 7. CLI — 입력 오류는 exit 2 · 구조 전용은 DB 없이 exit 0
# ──────────────────────────────────────────────────────────────────────────
def test_cli_rejects_extra_edges_without_structural_only(tmp_path: Path) -> None:
    graph = _write_graph(tmp_path / "g.json", ["A", "B"], [("A", "B")])
    assert tlp.main(["--graph", str(graph), "--extra-edges", str(graph)]) == tlp.EXIT_INVALID


@pytest.mark.parametrize("bad", ["0", "", "a,1", "-1"])
def test_cli_rejects_bad_concurrency(tmp_path: Path, bad: str) -> None:
    graph = _write_graph(tmp_path / "g.json", ["A", "B"], [("A", "B")])
    assert tlp.main(["--graph", str(graph), "--concurrency", bad]) == tlp.EXIT_INVALID


def test_cli_missing_graph_is_invalid(tmp_path: Path) -> None:
    assert tlp.main(["--graph", str(tmp_path / "none.json"), "--structural-only"]) == 2


def test_cli_structural_only_writes_report_with_overlay(tmp_path: Path) -> None:
    graph = _write_graph(tmp_path / "g.json", ["A", "B", "C"], [("A", "B")])
    extra = _write_graph(tmp_path / "x.json", [], [("B", "C")])
    out = tmp_path / "out" / "r.json"
    code = tlp.main(
        ["--graph", str(graph), "--structural-only", "--extra-edges", str(extra), "--out", str(out)]
    )
    assert code == tlp.EXIT_PASS
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["structural"]["edges"] == 1
    assert report["structural_with_extra_edges"]["edges"] == 2
