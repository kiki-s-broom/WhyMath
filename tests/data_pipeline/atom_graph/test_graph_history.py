"""`graph_history` 계약 — 역사 원장이 묶인 과거 정본을 현재 정본에서 바이트 단위로 되감는다.

합성 그래프로 단계(승격 벗기기 → 체인 수리 되돌리기)·위치 복원·실패 경로를 보고, 실 코퍼스로
KG-11 정본(`721fe6ff…`)이 실제로 복원되는지 확인한다. 뮤테이션: 원 위치를 하나 틀리면 sha가 다르다.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from data_pipeline.atom_graph.graph_history import (
    CHAIN_REPAIR_LEDGER,
    PROMOTION_V2_LEDGER,
    graph_at_sha,
    graph_sha256,
    serialize_graph,
    strip_evidence,
    undo_chain_repair,
)

_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _ROOT / "data" / "corpus" / "atom_graph_v1"
GRAPH_PATH = _CORPUS / "graph.json"
REFERENCE_V1_PATH = _CORPUS / "narrative_edge_reference_ledger_v1.json"


def _edge(a: str, b: str, evidence: str = "원자 백본 v1") -> dict[str, Any]:
    return {"from_code": a, "to_code": b, "relation": "prerequisite", "evidence": evidence}


@pytest.fixture()
def original() -> dict[str, Any]:
    """수리 전 정본(합성): A→B, B→C, C→D, X→Y."""
    return {
        "concepts": [{"code": c} for c in "ABCDXY"],
        "edges": [_edge("A", "B"), _edge("B", "C"), _edge("C", "D"), _edge("X", "Y")],
    }


@pytest.fixture()
def fix_edges(original: dict[str, Any]) -> list[dict[str, Any]]:
    """B→C 제거(원 위치 1) · X→Y 반전(원 위치 3)."""
    return [
        {
            "action": "제거",
            "from_code": "B",
            "to_code": "C",
            "original_index": 1,
            "original_record": original["edges"][1],
        },
        {
            "action": "반전",
            "from_code": "X",
            "to_code": "Y",
            "original_index": 3,
            "original_record": original["edges"][3],
        },
    ]


def _repaired(original: dict[str, Any]) -> dict[str, Any]:
    g = copy.deepcopy(original)
    g["edges"] = [_edge("A", "B"), _edge("C", "D"), _edge("Y", "X")]  # 제거·반전 적용
    return g


class TestUndo:
    def test_undo_restores_bytes_and_positions(
        self, original: dict[str, Any], fix_edges: list[dict[str, Any]]
    ) -> None:
        back = undo_chain_repair(_repaired(original), fix_edges)
        assert serialize_graph(back) == serialize_graph(original)

    def test_undo_refuses_graph_without_reversed_edge(
        self, original: dict[str, Any], fix_edges: list[dict[str, Any]]
    ) -> None:
        with pytest.raises(ValueError, match="반전 엣지"):
            undo_chain_repair(original, fix_edges)  # 수리 전 정본엔 Y→X 가 없다

    def test_mutation_wrong_index_changes_sha(
        self, original: dict[str, Any], fix_edges: list[dict[str, Any]]
    ) -> None:
        mutated = copy.deepcopy(fix_edges)
        mutated[0]["original_index"] = 0
        assert mutated != fix_edges
        back = undo_chain_repair(_repaired(original), mutated)
        assert {(e["from_code"], e["to_code"]) for e in back["edges"]} == {
            (e["from_code"], e["to_code"]) for e in original["edges"]
        }  # 집합은 같지만
        assert graph_sha256(back) != graph_sha256(original)  # 위치가 달라 바이트는 다르다

    def test_strip_evidence_only_removes_tagged(self, original: dict[str, Any]) -> None:
        g = copy.deepcopy(original)
        g["edges"].append(_edge("D", "X", "KG-12 서술형 낱말매칭 승격 v2"))
        assert serialize_graph(strip_evidence(g, "KG-12 서술형 낱말매칭 승격 v2")) == (
            serialize_graph(original)
        )


class TestGraphAtSha:
    def test_walks_promotion_then_repair(
        self, tmp_path: Path, original: dict[str, Any], fix_edges: list[dict[str, Any]]
    ) -> None:
        current = _repaired(original)
        current["edges"].append(_edge("D", "X", "EV2"))
        (tmp_path / "graph.json").write_text(serialize_graph(current), encoding="utf-8")
        (tmp_path / PROMOTION_V2_LEDGER).write_text(
            json.dumps({"_meta": {"evidence": "EV2"}}), encoding="utf-8"
        )
        (tmp_path / CHAIN_REPAIR_LEDGER).write_text(
            json.dumps({"fix_edges": fix_edges}, ensure_ascii=False), encoding="utf-8"
        )
        want_now = graph_sha256(current)
        want_mid = graph_sha256(_repaired(original))
        want_old = graph_sha256(original)
        assert graph_sha256(graph_at_sha(tmp_path / "graph.json", want_now)) == want_now
        assert graph_sha256(graph_at_sha(tmp_path / "graph.json", want_mid)) == want_mid
        assert graph_sha256(graph_at_sha(tmp_path / "graph.json", want_old)) == want_old

    def test_unreachable_sha_raises_with_stages(
        self, tmp_path: Path, original: dict[str, Any], fix_edges: list[dict[str, Any]]
    ) -> None:
        (tmp_path / "graph.json").write_text(serialize_graph(_repaired(original)), encoding="utf-8")
        (tmp_path / CHAIN_REPAIR_LEDGER).write_text(
            json.dumps({"fix_edges": fix_edges}, ensure_ascii=False), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="닿지 못했다"):
            graph_at_sha(tmp_path / "graph.json", "f" * 64)


class TestRealCorpus:
    def test_kg11_snapshot_is_reconstructable(self) -> None:
        """KG-11 참고 원장이 묶인 정본(엣지 2,231)이 현재 정본에서 되감긴다."""
        want = json.loads(REFERENCE_V1_PATH.read_text(encoding="utf-8"))["_meta"][
            "source_graph_sha256"
        ]
        assert want != hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest()  # 정본은 그 뒤 바뀌었다
        old = graph_at_sha(GRAPH_PATH, want)
        assert graph_sha256(old) == want
        assert len(old["edges"]) == 2231
        assert len(json.loads(GRAPH_PATH.read_text(encoding="utf-8"))["edges"]) == 2278
