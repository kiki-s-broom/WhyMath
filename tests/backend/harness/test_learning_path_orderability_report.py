"""학습 경로 위상 제약 밀도 관측 리포트 테스트 — 결정론·정직 회계·정렬 로직 재사용 동결(hermetic).

대상: `whymath_backend.harness.learning_path_orderability_report`(PATH-01 acceptance). 실 DB·
LLM·네트워크 0 — 소형 픽스처(그래프 리터럴)로 검증한다. 실 코퍼스 대상 acceptance① 재현
테스트 1건만 실제 `data/corpus/atom_graph_v1/graph.json`을 읽는다(회귀 감시·정확 임계값 단언).

**변별력**(CLAUDE.md "변별력 없는 검증 스텝 금지"):
  - `order_learning_path`를 재구현하지 않고 그대로 재호출하는지 — 몽키패치 스파이로 실제 호출
    횟수를 실측한다(재구현이었다면 스파이가 안 불린다).
  - 코퍼스 엣지 1개를 가감하면 순서화 카운트가 양방향으로 움직이는지(추가→증가·제거→감소).
  - 직접 축과 전이 축이 서로 다른 값을 내는지(`A→X→B`, X 비-population 경유 — 직접은 못 잡고
    전이(depth=2)는 잡는다). 두 축이 같은 값만 낸다면 축이 하나뿐인 위장이다.
  - DAG 가정이 깨진 병리적 입력에서 `has_cycle` sanity가 조용히 숨겨지지 않고 표면화되는지.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness import learning_path_orderability_report as lpo
from whymath_backend.l2.prerequisite_recommendation import MAX_PREREQUISITE_DEPTH


def _payload(concepts: list[str], edges: list[tuple[str, str, str]]) -> dict[str, object]:
    """`(from_code, to_code, relation)` 튜플 목록 → graph.json 형태 payload."""
    return {
        "concepts": [{"code": c} for c in concepts],
        "edges": [{"from_code": f, "to_code": t, "relation": rel} for f, t, rel in edges],
    }


# ──────────────────────────────────────────────────────────────────────────
# 1. 로더 — 정상·정직 실패
# ──────────────────────────────────────────────────────────────────────────
def test_load_corpus_graph_filters_non_prerequisite_relations() -> None:
    payload = _payload(
        ["A", "B"],
        [("A", "B", "prerequisite"), ("A", "B", "similar_to")],
    )
    graph = lpo.load_corpus_graph(payload)
    assert graph.concept_codes == ("A", "B")
    assert graph.prerequisite_edges == (("A", "B"),)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"items": []},
        {"concepts": [{"name": "code 없음"}]},
        {"concepts": [{"code": "A"}], "edges": "not-a-list"},
        {"concepts": [{"code": "A"}], "edges": [{"to_code": "A", "relation": "prerequisite"}]},
        {"concepts": [{"code": "A"}], "edges": [{"from_code": "A", "relation": "prerequisite"}]},
    ],
)
def test_load_corpus_graph_rejects_malformed_payload(payload: object) -> None:
    with pytest.raises(ValueError):
        lpo.load_corpus_graph(payload)


# ──────────────────────────────────────────────────────────────────────────
# 2. 인접·모집단·도달성 — 순수 헬퍼
# ──────────────────────────────────────────────────────────────────────────
def test_distribution_and_population_small_fixture() -> None:
    """A:0선수·B:0선수·C:2선수(A,B)·D:1선수(A) → population은 C 하나뿐(직접 선수 2개 이상)."""
    edges = [("A", "C"), ("B", "C"), ("A", "D")]
    codes = ("A", "B", "C", "D")
    pred, _succ = lpo._build_adjacency(edges)
    dist = lpo._direct_predecessor_distribution(codes, pred)
    assert dist == {0: 2, 1: 1, 2: 1}
    assert lpo._population(codes, pred) == ("C",)


def test_reach_within_hops_bounds_correctly_and_terminates() -> None:
    edges = [("A", "X"), ("X", "B"), ("B", "Y")]
    _pred, succ = lpo._build_adjacency(edges)
    assert lpo._reach_within_hops("A", 1, succ) == frozenset({"X"})
    assert lpo._reach_within_hops("A", 2, succ) == frozenset({"X", "B"})
    assert lpo._reach_within_hops("A", 3, succ) == frozenset({"X", "B", "Y"})
    # 그래프 끝(Y는 후행 없음)에 닿은 뒤엔 hops를 더 키워도 자연 종료·집합 불변.
    assert lpo._reach_within_hops("A", 99, succ) == frozenset({"X", "B", "Y"})


def test_concept_id_for_code_is_deterministic_and_distinct() -> None:
    assert lpo._concept_id_for_code("X") == lpo._concept_id_for_code("X")
    assert lpo._concept_id_for_code("X") != lpo._concept_id_for_code("Y")


def test_depth_budgets_reuse_max_prerequisite_depth_single_source() -> None:
    """깊이 축 상수 "5"는 하드코딩이 아니라 `MAX_PREREQUISITE_DEPTH` 단일 출처 재사용이다."""
    assert lpo.DEPTH_BUDGETS == (1, 2, MAX_PREREQUISITE_DEPTH)
    assert lpo.DEPTH_BUDGETS[-1] == 5  # 현재 코드 값 실측(문서 인용이 아니라 소스 재확인).


# ──────────────────────────────────────────────────────────────────────────
# 3. 셀 판정 — 결정도 경계(완전/부분/병렬) + 직접·전이 축 변별력
# ──────────────────────────────────────────────────────────────────────────
def test_determinism_parallel_when_no_pairs_related() -> None:
    edges = [("A", "C"), ("B", "C")]  # C 내부(A,B)에 제약 엣지 0.
    pred, succ = lpo._build_adjacency(edges)
    edge_set = frozenset(edges)
    result = lpo._evaluate_cell(pred["C"], axis="direct", depth=1, edge_set=edge_set, succ=succ)
    assert result.pair_total == 1
    assert result.pair_determined == 0
    assert result.determinism == "parallel"
    assert result.orderable is False
    assert result.has_cycle is False


def test_determinism_partial_when_some_pairs_related() -> None:
    """|S|=3(쌍 3개)에서 A→B 하나만 있으면 부분 결정(1/3)이다."""
    edges = [("A", "C"), ("B", "C"), ("D", "C"), ("A", "B")]
    pred, succ = lpo._build_adjacency(edges)
    edge_set = frozenset(edges)
    result = lpo._evaluate_cell(pred["C"], axis="direct", depth=1, edge_set=edge_set, succ=succ)
    assert result.pair_total == 3  # (A,B)·(A,D)·(B,D)
    assert result.pair_determined == 1  # (A,B)만
    assert result.determinism == "partial"
    assert result.orderable is True


def test_determinism_full_when_all_pairs_related() -> None:
    edges = [
        ("A", "C"),
        ("B", "C"),
        ("D", "C"),
        ("A", "B"),
        ("B", "D"),
        ("A", "D"),
    ]
    pred, succ = lpo._build_adjacency(edges)
    edge_set = frozenset(edges)
    result = lpo._evaluate_cell(pred["C"], axis="direct", depth=1, edge_set=edge_set, succ=succ)
    assert result.pair_total == 3
    assert result.pair_determined == 3
    assert result.determinism == "full"
    assert result.orderable is True


def test_direct_and_transitive_axes_diverge_via_intermediate_node() -> None:
    """A→X→B(X 비-막힘·population 밖)에서 직접 축은 못 잡고 전이 축(depth=2)이 잡는다.

    `learning_path.py`가 스스로 "A→X→B에서 X가 막힌 선수가 아니면 A·B 사이 순서는 못 잡는다"고
    적어둔 한계(D3)를 이 리포트의 "직접 vs 전이" 두 축으로 직접 재현한다 — 두 축이 서로 다른
    값을 낸다(변별력⑤). 두 축이 항상 같은 값만 내면 축이 하나뿐인 위장이다.
    """
    edges = [("A", "C"), ("B", "C"), ("A", "X"), ("X", "B")]
    pred, succ = lpo._build_adjacency(edges)
    edge_set = frozenset(edges)
    predecessors = pred["C"]
    assert predecessors == frozenset({"A", "B"})

    direct = lpo._evaluate_cell(predecessors, axis="direct", depth=1, edge_set=edge_set, succ=succ)
    assert direct.orderable is False
    assert direct.determinism == "parallel"

    trans_depth1 = lpo._evaluate_cell(
        predecessors, axis="transitive", depth=1, edge_set=edge_set, succ=succ
    )
    assert trans_depth1.orderable is False  # depth=1 전이 == 직접(구조적으로 동일 — reach 1홉).

    trans_depth2 = lpo._evaluate_cell(
        predecessors, axis="transitive", depth=2, edge_set=edge_set, succ=succ
    )
    assert trans_depth2.orderable is True  # X 경유로 A→B가 depth=2에서 비로소 잡힌다.
    assert trans_depth2.determinism == "full"

    # 변별력⑤ 핵심 — 같은 population, 같은 깊이 예산 밖에서 두 축이 다른 값을 낸다.
    assert direct.orderable != trans_depth2.orderable


def test_cycle_sanity_surfaces_when_data_pathologically_cyclic() -> None:
    """DAG 가정이 깨진 입력에서 `has_cycle`이 조용히 숨겨지지 않고 표면화된다(하드코딩 False 아님).

    원자 백본은 DAG 보장(`prerequisite_cycle` hard error)이라 실전에선 발생하지 않지만, 이
    sanity check 자체가 실제로 작동하는지(변별력)는 병리적 입력으로만 확인 가능하다.
    """
    edges = [("A", "C"), ("B", "C"), ("A", "B"), ("B", "A")]  # A,B 2-cycle(방어적 병리 케이스).
    pred, succ = lpo._build_adjacency(edges)
    edge_set = frozenset(edges)
    result = lpo._evaluate_cell(pred["C"], axis="direct", depth=1, edge_set=edge_set, succ=succ)
    assert result.has_cycle is True


# ──────────────────────────────────────────────────────────────────────────
# 4. 집계 리포트 — 결정론·변별력(엣지 가감 양방향)·order_learning_path 실호출
# ──────────────────────────────────────────────────────────────────────────
def test_orderable_count_moves_both_directions_with_one_edge() -> None:
    """코퍼스 엣지 1개를 가감하면 순서화 카운트가 양방향으로 움직인다(변별력⑤)."""
    codes = ("C", "A", "B")
    base_edges = (("A", "C"), ("B", "C"))  # C 내부(A,B) 제약 엣지 0.

    without = lpo.build_report(lpo.CorpusGraph(concept_codes=codes, prerequisite_edges=base_edges))
    direct_without = next(c for c in without.cells if c.depth == 1 and c.axis == "direct")
    assert direct_without.orderable_count == 0

    with_edge = (*base_edges, ("A", "B"))  # 엣지 1개 추가.
    added = lpo.build_report(lpo.CorpusGraph(concept_codes=codes, prerequisite_edges=with_edge))
    direct_added = next(c for c in added.cells if c.depth == 1 and c.axis == "direct")
    assert direct_added.orderable_count == 1  # 증가(0→1).

    removed = lpo.build_report(lpo.CorpusGraph(concept_codes=codes, prerequisite_edges=base_edges))
    direct_removed = next(c for c in removed.cells if c.depth == 1 and c.axis == "direct")
    assert direct_removed.orderable_count == 0  # 감소(1→0) — 양방향 이동 확인.


def test_build_report_calls_real_order_learning_path_not_a_reimplementation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """변별력 핵심 — order_learning_path를 몽키패치하면 실제 호출 횟수가 실측된다.

    재구현이었다면(리포트가 자체 Kahn을 돌렸다면) 이 스파이는 전혀 호출되지 않는다.
    """
    calls: list[int] = []
    original = lpo.order_learning_path

    def _spy(gaps: object, internal_edges: list[object]) -> object:
        calls.append(len(internal_edges))
        return original(gaps, internal_edges)  # type: ignore[arg-type]

    monkeypatch.setattr(lpo, "order_learning_path", _spy)

    graph = lpo.CorpusGraph(
        concept_codes=("C", "A", "B"),
        prerequisite_edges=(("A", "C"), ("B", "C"), ("A", "B")),
    )
    lpo.build_report(graph)

    # population=1("C") × depth 3(1·2·5) × axis 2(직접·전이) = 6회 실제 호출.
    assert len(calls) == len(lpo.DEPTH_BUDGETS) * 2 == 6
    assert any(n > 0 for n in calls)  # 최소 한 번은 실제 제약 엣지를 담아 호출됨(내부 A→B).

    monkeypatch.undo()
    restored_calls_len_before = len(calls)
    lpo.build_report(graph)
    assert len(calls) == restored_calls_len_before  # undo 후 스파이 미호출(원본 복구 확인).


def test_build_report_is_deterministic_regardless_of_input_order() -> None:
    edges = (("A", "C"), ("B", "C"))
    reversed_edges = tuple(reversed(edges))
    graph1 = lpo.CorpusGraph(concept_codes=("C", "A", "B"), prerequisite_edges=edges)
    graph2 = lpo.CorpusGraph(concept_codes=("B", "A", "C"), prerequisite_edges=reversed_edges)
    r1 = lpo.render_report(lpo.build_report(graph1))
    r2 = lpo.render_report(lpo.build_report(graph2))
    assert r1 == r2


def test_report_grid_has_depth_times_axis_cells() -> None:
    graph = lpo.CorpusGraph(
        concept_codes=("C", "A", "B"), prerequisite_edges=(("A", "C"), ("B", "C"))
    )
    report = lpo.build_report(graph)
    assert len(report.cells) == len(lpo.DEPTH_BUDGETS) * 2
    depths_axes = {(c.depth, c.axis) for c in report.cells}
    assert depths_axes == {(d, a) for d in lpo.DEPTH_BUDGETS for a in ("direct", "transitive")}


def test_orderable_rate_is_none_when_population_is_empty() -> None:
    """population 0건(어떤 개념도 직접 선수 2개 이상이 아님)이어도 0-division 없이 None."""
    graph = lpo.CorpusGraph(concept_codes=("A", "B"), prerequisite_edges=())
    report = lpo.build_report(graph)
    assert report.population_size == 0
    for cell in report.cells:
        assert cell.orderable_rate is None
    rendered = lpo.render_report(report)
    assert "데이터없음" in rendered


# ──────────────────────────────────────────────────────────────────────────
# 5. JSON — 구조적 상한 표기(acceptance③)
# ──────────────────────────────────────────────────────────────────────────
def test_report_to_json_includes_structural_ceiling_fields() -> None:
    graph = lpo.CorpusGraph(
        concept_codes=("C", "A", "B"), prerequisite_edges=(("A", "C"), ("B", "C"))
    )
    report = lpo.build_report(graph)
    payload = lpo.report_to_json(report)

    note = payload["structural_ceiling_note"]
    assert payload["is_structural_ceiling"] is True
    assert "weak_only" in note
    assert "100%" in note or "목표" in note
    assert len(payload["cells"]) == len(lpo.DEPTH_BUDGETS) * 2

    dumped = lpo.dump_json(report)
    assert json.loads(dumped) == payload


def test_render_report_states_ceiling_and_not_a_gate() -> None:
    graph = lpo.CorpusGraph(concept_codes=("A",), prerequisite_edges=())
    rendered = lpo.render_report(lpo.build_report(graph))
    assert "게이트가 아니다" in rendered
    assert "구조적 상한" in rendered
    assert "100%는 목표가 아니다" in rendered


# ──────────────────────────────────────────────────────────────────────────
# 6. CLI — exit 코드 규율(게이트 아님·입력 오류만 2)
# ──────────────────────────────────────────────────────────────────────────
_TINY_FIXTURE = {
    "concepts": [{"code": "C"}, {"code": "A"}, {"code": "B"}],
    "edges": [
        {"from_code": "A", "to_code": "C", "relation": "prerequisite"},
        {"from_code": "B", "to_code": "C", "relation": "prerequisite"},
    ],
}


def test_main_exit_0_on_tiny_fixture(tmp_path: Path) -> None:
    corpus_path = tmp_path / "graph.json"
    corpus_path.write_text(json.dumps(_TINY_FIXTURE), encoding="utf-8")
    assert lpo.main(["--corpus", str(corpus_path)]) == 0


def test_main_exit_2_on_missing_corpus_file(tmp_path: Path) -> None:
    assert lpo.main(["--corpus", str(tmp_path / "없음.json")]) == 2


def test_main_writes_json_artifact(tmp_path: Path) -> None:
    corpus_path = tmp_path / "graph.json"
    corpus_path.write_text(json.dumps(_TINY_FIXTURE), encoding="utf-8")
    out_path = tmp_path / "out" / "report.json"

    exit_code = lpo.main(["--corpus", str(corpus_path), "--json", str(out_path)])
    assert exit_code == 0
    assert out_path.is_file()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["population_size"] == 1


# ──────────────────────────────────────────────────────────────────────────
# 7. 실 코퍼스 — acceptance① 정확 재현(임계값 단언·회귀 감시)
# ──────────────────────────────────────────────────────────────────────────
def test_real_corpus_reproduces_pinned_acceptance_one_numbers() -> None:
    """2,683노드/2,234엣지 원자 백본(S4-60 병합 후)의 순서화 수치를 정확히 재현한다.

    acceptance① — 직접선수 분포(915/1388/302/70/8)·population 380·depth1 순서화 96/380(25.3%).
    부수로 depth5 전이 수치(254/380·66.8%·206/48/126)도 함께 재확인하고, 직접 축이 깊이와
    무관하게 상수(96)임을 depth5 행에서도 재확인해 변별력⑤(두 축이 다른 값)를 실 코퍼스 수준에서
    봉인한다.

    **S4-60 병합 전 값**(D1 원 주장): 2,210엣지·915/1412/278/70/8·population 356·96/356(27.0%)·
    depth2 168·depth5 249/356(69.9%)·201/48/107. 병합이 바꾼 것은 설명 가능하다 — 신규 고→대
    24건이 서로 다른 대학 노드 24곳에 하나씩 닿아 직접 선수 1개짜리(1412→1388)가 2개짜리
    (278→302)가 됐고 모집단이 +24 됐다. 새 24곳은 직접 축에서 전부 병렬(260→284)이라 직접 축
    순서화 96은 불변이며, 병합 전후 in-degree 분포를 독립 계산한 값과 대조해 확정했다.
    """
    if not lpo.DEFAULT_CORPUS_PATH.is_file():
        pytest.skip("data/corpus/atom_graph_v1/graph.json 미존재")

    payload = json.loads(lpo.DEFAULT_CORPUS_PATH.read_text(encoding="utf-8"))
    graph = lpo.load_corpus_graph(payload)
    report = lpo.build_report(graph)

    assert report.corpus_concept_total == 2683
    assert report.corpus_edge_total == 2234
    assert report.direct_predecessor_distribution == {0: 915, 1: 1388, 2: 302, 3: 70, 4: 8}
    assert report.population_size == 380

    def _cell(depth: int, axis: str) -> lpo.DepthAxisSummary:
        return next(c for c in report.cells if c.depth == depth and c.axis == axis)

    depth1_direct = _cell(1, "direct")
    assert depth1_direct.orderable_count == 96
    assert depth1_direct.orderable_rate is not None
    assert round(depth1_direct.orderable_rate, 3) == round(96 / 380, 3)
    depth1_direct_determinism = (
        depth1_direct.full_count,
        depth1_direct.partial_count,
        depth1_direct.parallel_count,
    )
    assert depth1_direct_determinism == (64, 32, 284)

    depth1_trans = _cell(1, "transitive")
    assert depth1_trans.orderable_count == 96  # 1홉 전이 == 직접(구조적으로 동일).

    depth2_trans = _cell(2, "transitive")
    assert depth2_trans.orderable_count == 170
    assert (depth2_trans.full_count, depth2_trans.partial_count, depth2_trans.parallel_count) == (
        132,
        38,
        210,
    )

    depth5_trans = _cell(5, "transitive")
    assert depth5_trans.orderable_count == 254
    assert round(depth5_trans.orderable_rate or 0.0, 3) == round(254 / 380, 3)
    assert (depth5_trans.full_count, depth5_trans.partial_count, depth5_trans.parallel_count) == (
        206,
        48,
        126,
    )

    # 직접 축은 깊이 무관 상수 — depth5 행에서도 96 그대로(변별력⑤: 두 축이 다른 값을 낸다).
    depth5_direct = _cell(5, "direct")
    assert depth5_direct.orderable_count == 96
    assert depth5_direct.orderable_count != depth5_trans.orderable_count

    # sanity — DAG 보장 코퍼스이므로 사이클 0건(조용히 숨기지 않고 실측 확인).
    assert all(cell.cycle_detected_count == 0 for cell in report.cells)

    assert isinstance(lpo.render_report(report), str)
    assert isinstance(lpo.dump_json(report), str)
