"""KG-12 ① 체인 수리 원장 계약 — 재현성(수리 전 정본 복원)·합의 규칙·수정 엣지 실재·적용 상태·CLI·뮤테이션."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _ROOT / "data" / "corpus" / "atom_graph_v1"
GRAPH_PATH = _CORPUS / "graph.json"
LEDGER_PATH = _CORPUS / "university_chain_repair_v1.json"
REFERENCE_V1_PATH = _CORPUS / "narrative_edge_reference_ledger_v1.json"
CONSENSUS_PATH = _ROOT / "docs" / "data" / "ai_review_university_chain_repair_v1.json"
BUILDER_PATH = _ROOT / "scripts" / "build_university_chain_repair_kg12.py"


@pytest.fixture(scope="module")
def builder() -> Any:
    spec = importlib.util.spec_from_file_location("kg12_repair_builder", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def inputs(builder: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    ref = json.loads(REFERENCE_V1_PATH.read_text(encoding="utf-8"))
    want = ref["_meta"]["source_graph_sha256"]
    return (
        builder.graph_at_sha(GRAPH_PATH, want),
        ref,
        json.loads(CONSENSUS_PATH.read_text(encoding="utf-8")),
        want,
    )


@pytest.fixture(scope="module")
def ledger() -> dict[str, Any]:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_regeneration_is_byte_identical(
    builder: Any, inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]
) -> None:
    graph, ref, cons, sha = inputs
    assert builder.serialize(builder.build_payload(graph, ref, cons, sha)).encode("utf-8") == (
        LEDGER_PATH.read_bytes()
    )


def test_counts_frozen(ledger: dict[str, Any]) -> None:
    m = ledger["_meta"]
    assert m["conflict_total"] == 40 and len(ledger["rows"]) == 40
    assert m["consensus_counts"] == {"A합의": 21, "B합의": 16, "보류": 3}
    assert m["fix_edge_count"] == 16 and m["fix_action_counts"] == {"반전": 4, "제거": 12}
    assert sum(1 for r in ledger["rows"] if r["narrative_edge_addable_after_repair"]) == 21


def test_fix_edges_existed_before_and_are_applied_now(
    ledger: dict[str, Any], inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]
) -> None:
    """수정 엣지는 수리 전 정본에 원 위치 그대로 있었고, 현재 정본에서는 제거·반전돼 있다."""
    old = inputs[0]
    now = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    now_pairs = {(e["from_code"], e["to_code"]) for e in now["edges"]}
    for fx in ledger["fix_edges"]:
        pair = (fx["from_code"], fx["to_code"])
        assert old["edges"][fx["original_index"]] == fx["original_record"]
        assert fx["original_record"]["from_code"] == pair[0]
        assert pair not in now_pairs
        assert ((pair[1], pair[0]) in now_pairs) == (fx["action"] == "반전")
        assert pair[0].split("-", 1)[0] == pair[1].split("-", 1)[0]  # 과정 내부만


def test_fix_edges_lie_on_recorded_repair_paths(
    ledger: dict[str, Any], inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]
) -> None:
    conflicts = [c for c in inputs[1]["cycle_conflicts"] if c["kind"] == "가"]
    by_row = {f"R{i:02d}": c for i, c in enumerate(conflicts, start=1)}
    for fx in ledger["fix_edges"]:
        for row in fx["rows"]:
            path = {(x["from_code"], x["to_code"]) for x in by_row[row]["repair_path_edges"]}
            assert (fx["from_code"], fx["to_code"]) in path


class TestConsensusRule:
    def test_a_with_same_edges(self, builder: Any) -> None:
        v = {"A": "A", "A_edges": ["제거 X-C1→X-C2"], "B": "A", "B_edges": ["제거 X-C1→X-C2"]}
        assert builder.consensus_of(v) == ("A합의", [("제거", "X-C1", "X-C2")])

    def test_a_with_different_edges_is_hold(self, builder: Any) -> None:
        v = {"A": "A", "A_edges": ["제거 X-C1→X-C2"], "B": "A", "B_edges": ["반전 X-C1→X-C2"]}
        assert builder.consensus_of(v) == ("보류", [])

    def test_b_b_and_mixed(self, builder: Any) -> None:
        assert builder.consensus_of({"A": "B", "B": "B"}) == ("B합의", [])
        assert builder.consensus_of({"A": "A", "A_edges": ["제거 X-C1→X-C2"], "B": "B"}) == (
            "보류",
            [],
        )

    def test_bad_fix_text_is_rejected(self, builder: Any) -> None:
        with pytest.raises(ValueError):
            builder.parse_fix("삭제 X-C1→X-C2")


class TestMutations:
    def test_flipping_one_verdict_changes_ledger(
        self, builder: Any, inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]
    ) -> None:
        graph, ref, cons, sha = inputs
        mutated = copy.deepcopy(cons)
        row = next(k for k, v in mutated.items() if v["result"] == "A합의")
        mutated[row]["B"] = "B"
        assert mutated != cons
        out = builder.build_payload(graph, ref, mutated, sha)
        assert out["_meta"]["consensus_counts"]["A합의"] == 20
        assert out["_meta"]["fix_edge_count"] <= 16

    def test_fix_edge_off_path_is_refused(
        self, builder: Any, inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]
    ) -> None:
        graph, ref, cons, sha = inputs
        mutated = copy.deepcopy(cons)
        row = next(k for k, v in mutated.items() if v["result"] == "A합의")
        mutated[row]["A_edges"] = mutated[row]["B_edges"] = ["제거 CALC1-C01→CALC1-C02"]
        with pytest.raises(ValueError, match="역경로 위에 없다"):
            builder.build_payload(graph, ref, mutated, sha)


class TestCli:
    def test_check_exit_zero_on_committed_ledger(self, builder: Any) -> None:
        assert builder.main(["--check"]) == 0

    def test_check_exit_one_when_ledger_differs(self, builder: Any, tmp_path: Path) -> None:
        stale = tmp_path / "stale.json"
        stale.write_text("{}\n", encoding="utf-8")
        original = builder.OUTPUT_PATH
        builder.OUTPUT_PATH = stale
        try:
            assert builder.main(["--check"]) == 1
            assert stale.read_text(encoding="utf-8") == "{}\n"
        finally:
            builder.OUTPUT_PATH = original
