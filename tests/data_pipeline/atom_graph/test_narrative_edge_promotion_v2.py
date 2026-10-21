"""KG-12 ③ 승격 원장 v2 계약 — 재현성(병합 전 정본 복원)·부분집합 전건·C 승인 규칙·Wilson 게이트·
과목간 원장 유보·정본 병합 1:1·뮤테이션(전건 reject → 게이트 FAIL·edges 비움)."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from data_pipeline.atom_graph.narrative_promotion_merge import (
    ledger_edges,
    ledger_identity,
    merge_promotion,
)

_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _ROOT / "data" / "corpus" / "atom_graph_v1"
GRAPH_PATH = _CORPUS / "graph.json"
PROMOTION_PATH = _CORPUS / "narrative_edge_promotion_v2.json"
REFERENCE_V2_PATH = _CORPUS / "narrative_edge_reference_ledger_v2.json"
INTER_COURSE_PATH = _CORPUS / "inter_course_edges_university_v1.json"
CONSENSUS_PATH = _ROOT / "docs" / "data" / "ai_review_narrative_edge_reference_v1.json"
THIRD_PATH = _ROOT / "docs" / "data" / "ai_review_narrative_edge_reference_v2_third.json"
BUILDER_PATH = _ROOT / "scripts" / "build_narrative_edge_promotion_kg12.py"


@pytest.fixture(scope="module")
def builder() -> Any:
    spec = importlib.util.spec_from_file_location("kg12_promotion_builder", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def inputs(builder: Any) -> dict[str, Any]:
    graph, sha = builder.load_bound_graph()
    return {
        "graph": graph,
        "sha": sha,
        "ref": json.loads(REFERENCE_V2_PATH.read_text(encoding="utf-8")),
        "cons": json.loads(CONSENSUS_PATH.read_text(encoding="utf-8")),
        "third": json.loads(THIRD_PATH.read_text(encoding="utf-8")),
        "pending": frozenset(
            (e["from_code"], e["to_code"])
            for e in json.loads(INTER_COURSE_PATH.read_text(encoding="utf-8"))["edges"]
        ),
    }


@pytest.fixture(scope="module")
def promotion() -> dict[str, Any]:
    return json.loads(PROMOTION_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _build(builder: Any, i: dict[str, Any], **over: Any) -> dict[str, Any]:
    args = {k: i[k] for k in ("graph", "ref", "cons", "third", "sha", "pending")}
    args.update(over)
    return builder.build_payload(  # type: ignore[no-any-return]
        args["graph"], args["ref"], args["cons"], args["third"], args["sha"], args["pending"]
    )


def test_regeneration_is_byte_identical(builder: Any, inputs: dict[str, Any]) -> None:
    assert builder.serialize(_build(builder, inputs)).encode("utf-8") == PROMOTION_PATH.read_bytes()
    assert (
        inputs["sha"]
        == json.loads(PROMOTION_PATH.read_text(encoding="utf-8"))["_meta"]["source_graph_sha256"]
    )


def test_subset_and_gate_frozen(promotion: dict[str, Any], inputs: dict[str, Any]) -> None:
    m = promotion["_meta"]
    assert (m["staging_total"], m["subset_total"]) == (183, 66)
    assert m["third_counts"] == {"approve": 60, "replace": 2, "reject": 3, "hold": 1}
    assert m["third_approved"] == 62 and m["deferred_to_inter_course_ledger"] == 3
    assert m["gate_pass"] is True and m["promoted_edge_count"] == 59
    assert m["wilson_lower_bound_95"] >= m["wilson_floor"] == 0.80
    assert set(inputs["third"]) == {r["row"] for r in promotion["rows"]}  # 부분집합 전건·초과 없음


def test_third_approval_rule(builder: Any) -> None:
    assert builder.third_approves("승인", None, "approve", "") is True
    assert builder.third_approves("승인", None, "replace", "X-C1") is False
    assert builder.third_approves("교체", "X-C1", "replace", "X-C1") is True
    assert builder.third_approves("교체", "X-C1", "replace", "X-C2") is False
    assert builder.third_approves("교체", "X-C1", "approve", "") is False
    assert builder.third_approves("승인", None, "hold", "") is False


def test_deferred_rows_belong_to_pending_ledger(
    promotion: dict[str, Any], inputs: dict[str, Any]
) -> None:
    deferred = [r for r in promotion["rows"] if r["C_approves"] and r["promoted_from_code"] is None]
    assert len(deferred) == 3
    promoted_pairs = {(e["from_code"], e["to_code"]) for e in promotion["edges"]}
    for r in deferred:
        pair = (r.get("ab_code") or r["from_code"], r["to_code"])
        assert pair in inputs["pending"] and pair not in promoted_pairs


def test_promoted_edges_are_merged_one_to_one(promotion: dict[str, Any]) -> None:
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    ev = promotion["_meta"]["evidence"]
    tagged = {(e["from_code"], e["to_code"]) for e in graph["edges"] if e.get("evidence") == ev}
    assert tagged == {(e["from_code"], e["to_code"]) for e in promotion["edges"]}
    assert len(tagged) == 59
    result = merge_promotion(copy.deepcopy(graph), promotion)  # 멱등 경로 — 1:1 대조 통과
    assert (result.added, result.already_merged) == (0, 59)
    assert result.migration_id == "narrative_edge_promotion_v2" and result.task_label == "KG-12"


def test_ledger_identity_defaults_for_v1() -> None:
    assert ledger_identity({"_meta": {}})["migration_id"] == "narrative_edge_promotion_v1"
    assert ledger_identity({"_meta": {"task": "KG-11-x"}})["task_label"] == "KG-11"


def test_promoted_edge_records_drop_ledger_only_fields(promotion: dict[str, Any]) -> None:
    for r in ledger_edges(promotion):
        assert r["strength"] == 0.8 and r["relation"] == "prerequisite"


class TestMutations:
    def test_all_reject_fails_gate_and_empties_edges(
        self, builder: Any, inputs: dict[str, Any]
    ) -> None:
        third = {k: {**v, "verdict": "reject", "code": ""} for k, v in inputs["third"].items()}
        out = _build(builder, inputs, third=third)
        assert out["_meta"]["gate_pass"] is False and out["edges"] == []
        assert out["_meta"]["third_approved"] == 0

    def test_missing_subset_row_is_refused(self, builder: Any, inputs: dict[str, Any]) -> None:
        third = dict(inputs["third"])
        third.pop(next(iter(third)))
        with pytest.raises(ValueError, match="3인째 검수에"):
            _build(builder, inputs, third=third)

    def test_threshold_is_discriminative(self, builder: Any, inputs: dict[str, Any]) -> None:
        """58/66 은 하한 0.797 로 FAIL, 59/66 은 0.815 로 PASS — 게이트가 경계에서 갈린다."""
        kg11 = builder._kg11()
        assert kg11.wilson_lower_bound(58, 66) < 0.80 <= kg11.wilson_lower_bound(59, 66)


class TestCli:
    def test_check_exit_zero_on_committed_ledger(self, builder: Any) -> None:
        assert builder.main(["--check"]) == 0
