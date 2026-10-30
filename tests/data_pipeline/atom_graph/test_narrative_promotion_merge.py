"""KG-11 승격 병합 모듈 계약 — 합성 그래프로 재현성·멱등·거부 경로·스키마 호환·CLI를 확인한다.

각 주장을 *깨지면 RED인 입력*으로 확인한다: 정본 sha 불일치·일부 병합·끝점 부재·자기루프·순환·
evidence 불일치는 전부 예외(ValueError)이고, 정상 입력은 끝에 덧붙인 뒤 provenance를 한 번만 갱신한다.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from data_pipeline.atom_graph.narrative_promotion_merge import (
    PROVENANCE_MIGRATION_ID,
    append_provenance,
    graph_sha256,
    main,
    merge_promotion,
    pre_merge_view,
    serialize_graph,
    to_canonical_edge,
    validate_promotion,
)

EV = "KG-11 서술형 승격 테스트"


def _atom(code: str, name: str) -> dict[str, Any]:
    return {"code": code, "name": name, "level": "세부개념", "school_level": "대학"}


def _edge(a: str, b: str, evidence: str = "원자 백본 v1") -> dict[str, Any]:
    return {
        "from_code": a,
        "from_name": a,
        "to_code": b,
        "to_name": b,
        "relation": "prerequisite",
        "relation_subtype": "소단원간",
        "school_link": False,
        "strength": 0.8,
        "evidence": evidence,
    }


@pytest.fixture
def graph() -> dict[str, Any]:
    return {
        "source_citation": "test",
        "concepts": [_atom("A", "a"), _atom("B", "b"), _atom("C", "c"), _atom("D", "d")],
        "edges": [_edge("A", "B"), _edge("B", "C")],
        "narrative_edges_raw": [],
    }


def _ledger(graph: dict[str, Any], *pairs: tuple[str, str]) -> dict[str, Any]:
    return {
        "_meta": {"evidence": EV, "source_graph_sha256": graph_sha256(graph)},
        "edges": [
            {**_edge(a, b, EV), "scope": "uni_staging", "review": "approve"} for a, b in pairs
        ],
    }


class TestMerge:
    def test_appends_and_is_idempotent(self, graph: dict[str, Any]) -> None:
        ledger = _ledger(graph, ("A", "D"), ("D", "C"))
        before = copy.deepcopy(graph)
        r = merge_promotion(graph, ledger)
        assert (r.added, r.edges_before, r.edges_after) == (2, 2, 4)
        assert serialize_graph(pre_merge_view(graph, EV)) == serialize_graph(before)
        r2 = merge_promotion(graph, ledger)
        assert (r2.added, r2.already_merged) == (0, 2)
        assert [e["evidence"] for e in graph["edges"][-2:]] == [EV, EV]
        for e in graph["edges"][-2:]:
            assert "scope" not in e and "review" not in e

    def test_rejects_when_canonical_changed(self, graph: dict[str, Any]) -> None:
        ledger = _ledger(graph, ("A", "D"))
        graph["edges"].append(_edge("C", "D"))
        with pytest.raises(ValueError, match="정본이 원장 이후 바뀜"):
            merge_promotion(graph, ledger)

    def test_rejects_partial_merge(self, graph: dict[str, Any]) -> None:
        ledger = _ledger(graph, ("A", "D"), ("D", "C"))
        graph["edges"].append(_edge("A", "D", EV))
        with pytest.raises(ValueError, match="일부만 병합"):
            merge_promotion(graph, ledger)

    @pytest.mark.parametrize(
        ("pairs", "needle"),
        [
            ((("A", "Z"),), "끝점"),
            ((("A", "A"),), "자기 루프"),
            ((("C", "A"),), "순환"),
            ((("A", "B"),), "이미 있는 쌍"),
            ((("A", "D"), ("A", "D")), "내부 중복"),
        ],
    )
    def test_rejects_structural_violations(
        self, graph: dict[str, Any], pairs: tuple[tuple[str, str], ...], needle: str
    ) -> None:
        ledger = _ledger(graph, *pairs)
        with pytest.raises(ValueError, match=needle):
            merge_promotion(graph, ledger)

    def test_rejects_other_ledger_with_same_evidence_after_merge(
        self, graph: dict[str, Any]
    ) -> None:
        """멱등 경로의 1:1 대조 — 태그 엣지 수만 같은 다른 원장은 '이미 병합됨'이 아니다."""
        merge_promotion(graph, _ledger(graph, ("A", "D")))
        other = {
            "_meta": {"evidence": EV, "source_graph_sha256": "0" * 64},
            "edges": [_edge("B", "D", EV)],
        }
        with pytest.raises(ValueError, match="정합하지 않음"):
            merge_promotion(graph, other)
        tampered = copy.deepcopy(graph)
        tampered["edges"][-1]["strength"] = 0.1
        with pytest.raises(ValueError, match="원장 레코드와 다름"):
            merge_promotion(tampered, _ledger(graph, ("A", "D")))

    def test_rejects_evidence_mismatch(self, graph: dict[str, Any]) -> None:
        ledger = _ledger(graph, ("A", "D"))
        ledger["edges"][0]["evidence"] = "다른 출처"
        with pytest.raises(ValueError, match="evidence 불일치"):
            merge_promotion(graph, ledger)

    def test_control_validate_is_green_on_clean_input(self, graph: dict[str, Any]) -> None:
        assert validate_promotion(_ledger(graph, ("A", "D"))["edges"], graph) == []

    def test_canonical_edge_drops_ledger_fields(self) -> None:
        rec = {**_edge("A", "D", EV), "scope": "uni_staging", "review": "approve"}
        assert set(to_canonical_edge(rec)) == {
            "from_code",
            "from_name",
            "to_code",
            "to_name",
            "relation",
            "relation_subtype",
            "school_link",
            "strength",
            "evidence",
        }


class TestProvenance:
    def test_append_once_and_update_counts(self, graph: dict[str, Any]) -> None:
        r = merge_promotion(graph, _ledger(graph, ("A", "D")))
        prov: dict[str, Any] = {"edge_counts": {"atom_id_edges": 2}}
        assert append_provenance(prov, r, merged_on="2026-10-20") is True
        assert append_provenance(prov, r, merged_on="2026-10-20") is False
        ids = [m["id"] for m in prov["post_transform_migrations"]]
        assert ids == [PROVENANCE_MIGRATION_ID]
        assert prov["edge_counts"]["atom_id_edges"] == 3
        assert r.pre_merge_sha256 in prov["post_transform_migrations"][0]["summary"]


class TestCli:
    def test_cli_merge_check_and_reject(self, graph: dict[str, Any], tmp_path: Path) -> None:
        g = tmp_path / "graph.json"
        g.write_text(serialize_graph(graph), encoding="utf-8")
        led = tmp_path / "ledger.json"
        led.write_text(json.dumps(_ledger(graph, ("A", "D")), ensure_ascii=False), encoding="utf-8")
        prov = tmp_path / "_provenance.json"
        prov.write_text('{"edge_counts": {"atom_id_edges": 2}}', encoding="utf-8")
        base = ["--graph", str(g), "--ledger", str(led), "--provenance", str(prov)]
        assert main([*base, "--check"]) == 1  # 미병합
        assert main(base) == 0
        assert main([*base, "--check"]) == 0
        assert json.loads(prov.read_text(encoding="utf-8"))["edge_counts"]["atom_id_edges"] == 3
        assert main(base) == 0  # 멱등 — 쓰기 없음
        bad = tmp_path / "bad.json"
        stale = _ledger(graph, ("A", "D"))
        stale["_meta"]["source_graph_sha256"] = "0" * 64
        stale["edges"] = [{**_edge("B", "D", EV)}]
        bad.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
        assert main(["--graph", str(g), "--ledger", str(bad), "--provenance", str(prov)]) == 1
        assert main(["--graph", str(tmp_path / "none.json"), "--ledger", str(led)]) == 1
