"""KG-11 승격 원장(`narrative_edge_promotion_v1.json`) 계약 — 재현성·합의 규칙·Wilson 게이트·변별력.

승격 원장은 검수 합의(JSON)에서 결정론으로 만들어지며, 게이트가 FAIL이면 edges가 비어 있어야 한다.
변별력: 합의를 전건 approve로 바꾸면 게이트가 PASS로 바뀌고 edges가 채워진다(게이트가 실제로 값을 가른다).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[3]
GRAPH_PATH = _ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"
REFERENCE_PATH = (
    _ROOT / "data" / "corpus" / "atom_graph_v1" / "narrative_edge_reference_ledger_v1.json"
)
PROMOTION_PATH = _ROOT / "data" / "corpus" / "atom_graph_v1" / "narrative_edge_promotion_v1.json"
CONSENSUS_PATH = _ROOT / "docs" / "data" / "ai_review_narrative_edge_reference_v1.json"
BUILDER_PATH = _ROOT / "scripts" / "build_narrative_edge_promotion_kg11.py"


def _load_builder() -> Any:
    spec = importlib.util.spec_from_file_location("kg11_promotion_builder", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        json.loads(GRAPH_PATH.read_text(encoding="utf-8")),
        json.loads(REFERENCE_PATH.read_text(encoding="utf-8")),
        json.loads(CONSENSUS_PATH.read_text(encoding="utf-8")),
    )


@pytest.fixture(scope="module")
def promotion() -> dict[str, Any]:
    return json.loads(PROMOTION_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_regeneration_is_byte_identical(
    inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    b = _load_builder()
    graph, ref, cons = inputs
    sha = hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest()
    assert (
        b.serialize(b.build_payload(graph, ref, cons, sha)).encode("utf-8")
        == PROMOTION_PATH.read_bytes()
    )


def test_consensus_covers_every_staging_row(
    inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any]], promotion: dict[str, Any]
) -> None:
    _graph, ref, cons = inputs
    staging = [e for e in ref["proposed_edges"] if e["scope"] == "uni_staging"]
    assert (
        len(staging) == promotion["_meta"]["staging_total"] == len(promotion["rows"]) == len(cons)
    )
    assert sum(promotion["_meta"]["consensus_counts"].values()) == len(staging)


def test_gate_verdict_is_consistent(promotion: dict[str, Any]) -> None:
    m = promotion["_meta"]
    approved = m["consensus_counts"]["승인"] + m["consensus_counts"]["교체"]
    assert m["gate_pass"] == (m["wilson_lower_bound_95"] >= m["wilson_floor"])
    if not m["gate_pass"]:
        assert promotion["edges"] == [] and m["promoted_edge_count"] == 0
    else:
        assert len(promotion["edges"]) == m["promoted_edge_count"] <= approved
    # 2026-10-20 실측 동결: 합의 승인 90/183 · 하한 0.43 → FAIL (값이 바뀌면 검수가 바뀐 것이다)
    assert (approved, m["gate_pass"]) == (90, False)


def test_wilson_matches_backend_helper() -> None:
    b = _load_builder()
    import sys

    sys.path.insert(0, str(_ROOT / "src" / "backend"))
    from whymath_backend.harness.wilson import wilson_lower_bound

    for s, n in ((90, 183), (150, 183), (183, 183), (0, 5)):
        assert abs(b.wilson_lower_bound(s, n) - wilson_lower_bound(s, n)) < 1e-9


class TestDiscrimination:
    def test_all_approve_passes_gate_and_fills_edges(
        self, inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
    ) -> None:
        b = _load_builder()
        graph, ref, cons = inputs
        forced = {k: {**v, "A": "approve", "B": "approve"} for k, v in cons.items()}
        out = b.build_payload(graph, ref, forced, "x" * 64)
        assert out["_meta"]["gate_pass"] is True
        assert out["_meta"]["promoted_edge_count"] == len(out["edges"]) > 0
        for e in out["edges"]:
            assert e["evidence"] == b.EVIDENCE and e["strength"] == 0.8

    def test_disagreement_is_hold_and_same_code_replace_promotes(self) -> None:
        b = _load_builder()
        assert b.consensus_of("approve", "", "reject", "") == ("보류", None)
        assert b.consensus_of("replace", "X-1", "replace", "X-2") == ("보류", None)
        assert b.consensus_of("replace", "X-1", "replace", "X-1") == ("교체", "X-1")
        assert b.consensus_of("reject", "", "reject", "") == ("반려", None)

    def test_missing_row_is_rejected(
        self, inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
    ) -> None:
        b = _load_builder()
        graph, ref, cons = inputs
        partial = dict(cons)
        partial.pop("E001")
        with pytest.raises(ValueError, match="E001"):
            b.build_payload(graph, ref, partial, "x" * 64)
