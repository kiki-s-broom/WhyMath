"""KG-10 ① — 서술형 선수엣지 해소 제안 원장(`narrative_edge_resolution_proposal_v1.json`) 계약.

핵심 주장을 각각 *깨지면 RED인 입력*으로 확인한다(정상 입력만 초록인 것은 증거가 아니다):

1. **재현성** — 빌더를 다시 돌리면 커밋된 원장과 바이트 동일(결정론·날짜 없음).
2. **전수성** — 서술형 973건이 한 건도 빠짐없이 status를 갖고, status 합 = 서술형 수.
3. **구조** — 제안 엣지의 양끝은 정본 원자(세부개념)이고, 자기 루프·정본 중복·제안 내부 중복이 없으며,
   정본 + 제안을 합쳐도 prerequisite 그래프가 비순환이다.
4. **스키마 호환** — 원장 전용 필드(level_pair·unit_level_source·narrative_indices)를 떼면
   `AtomEdge`(extra=forbid)를 통과한다 — 병합 시 정본 엣지가 될 수 있다는 증명.
5. **정본 무수정** — 원장의 source_graph_sha256이 현재 정본 파일 지문과 같다(정본이 바뀌면 원장 재생성).
6. **변별력(뮤테이션)** — 정본에 역방향 엣지를 주입하면 그 제안은 cycle_conflict로 빠진다; 제안 1건을
   정본에 미리 넣으면 already_present로 바뀐다.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from data_pipeline.atom_graph.models import AtomEdge
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[3]
GRAPH_PATH = _ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"
LEDGER_PATH = (
    _ROOT / "data" / "corpus" / "atom_graph_v1" / "narrative_edge_resolution_proposal_v1.json"
)
BUILDER_PATH = _ROOT / "scripts" / "build_narrative_edge_resolution_kg10.py"

LEDGER_ONLY_FIELDS = ("level_pair", "unit_level_source", "narrative_indices")
STATUSES = {
    "resolved",
    "self_subunit_chain",
    "self_subunit_source",
    "already_present",
    "no_atoms",
    "to_missing",
    "cycle_conflict",
}


def _load_builder() -> Any:
    spec = importlib.util.spec_from_file_location("kg10_builder", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def graph() -> dict[str, Any]:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def ledger_bytes() -> bytes:
    return LEDGER_PATH.read_bytes()


@pytest.fixture(scope="module")
def ledger(ledger_bytes: bytes) -> dict[str, Any]:
    return json.loads(ledger_bytes.decode("utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def builder() -> Any:
    return _load_builder()


def _has_cycle(pairs: list[tuple[str, str]]) -> bool:
    succ: dict[str, list[str]] = {}
    for a, b in pairs:
        succ.setdefault(a, []).append(b)
    state: dict[str, int] = {}
    for start in list(succ):
        if state.get(start):
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        state[start] = 1
        while stack:
            node, i = stack[-1]
            children = succ.get(node, [])
            if i < len(children):
                stack[-1] = (node, i + 1)
                child = children[i]
                if state.get(child) == 1:
                    return True
                if not state.get(child):
                    state[child] = 1
                    stack.append((child, 0))
            else:
                state[node] = 2
                stack.pop()
    return False


class TestReproducibility:
    def test_regeneration_is_byte_identical(
        self, builder: Any, graph: dict[str, Any], ledger_bytes: bytes
    ) -> None:
        sha = hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest()
        regenerated = builder.serialize(builder.build_payload(graph, sha))
        assert regenerated.encode("utf-8") == ledger_bytes

    def test_source_sha_matches_canonical_file(self, ledger: dict[str, Any]) -> None:
        assert (
            ledger["_meta"]["source_graph_sha256"]
            == hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest()
        )

    def test_builder_does_not_touch_canonical_graph(
        self, builder: Any, graph: dict[str, Any]
    ) -> None:
        before = json.dumps(graph, ensure_ascii=False, sort_keys=True)
        builder.build_payload(graph, "x" * 64)
        assert json.dumps(graph, ensure_ascii=False, sort_keys=True) == before


class TestCoverage:
    def test_every_narrative_edge_has_a_status(
        self, ledger: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        records = ledger["records"]
        assert (
            len(records) == len(graph["narrative_edges_raw"]) == ledger["_meta"]["narrative_total"]
        )
        assert [r["narrative_index"] for r in records] == list(range(len(records)))
        assert {r["status"] for r in records} <= STATUSES
        counts = ledger["_meta"]["status_counts"]
        assert sum(counts.values()) == len(records)
        assert counts["resolved"] > 0 and counts["cycle_conflict"] > 0

    def test_resolved_records_point_at_proposed_edges(self, ledger: dict[str, Any]) -> None:
        pairs = {(e["from_code"], e["to_code"]) for e in ledger["proposed_edges"]}
        for r in ledger["records"]:
            if r["status"] == "resolved":
                assert r["resolved_from"], r
                for a in r["resolved_from"]:
                    assert (a, r["to_code"]) in pairs
        covered = {i for e in ledger["proposed_edges"] for i in e["narrative_indices"]}
        assert covered == {
            r["narrative_index"] for r in ledger["records"] if r["status"] == "resolved"
        }


class TestStructure:
    def test_endpoints_are_atoms_no_self_loop_no_duplicates(
        self, ledger: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        level = {c["code"]: c["level"] for c in graph["concepts"]}
        existing = {(e["from_code"], e["to_code"]) for e in graph["edges"]}
        seen: set[tuple[str, str]] = set()
        for e in ledger["proposed_edges"]:
            pair = (e["from_code"], e["to_code"])
            assert level.get(pair[0]) == "세부개념" and level.get(pair[1]) == "세부개념", pair
            assert pair[0] != pair[1]
            assert pair not in existing, f"정본 중복 {pair}"
            assert pair not in seen, f"제안 내부 중복 {pair}"
            seen.add(pair)
        assert len(seen) == ledger["_meta"]["proposed_edge_count"]

    def test_merged_graph_is_acyclic(self, ledger: dict[str, Any], graph: dict[str, Any]) -> None:
        pairs = [(e["from_code"], e["to_code"]) for e in graph["edges"]]
        assert not _has_cycle(pairs), "정본 자체가 순환"
        pairs += [(e["from_code"], e["to_code"]) for e in ledger["proposed_edges"]]
        assert not _has_cycle(pairs), "정본 + 제안이 순환"

    def test_level_pair_and_school_link_consistent(
        self, ledger: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        lvl = {c["code"]: c["school_level"] for c in graph["concepts"]}
        for e in ledger["proposed_edges"]:
            assert e["level_pair"] == f"{lvl[e['from_code']]}→{lvl[e['to_code']]}"
            assert e["school_link"] == (lvl[e["from_code"]] != lvl[e["to_code"]])
        assert ledger["_meta"]["proposed_level_pairs"] == {
            k: sum(1 for e in ledger["proposed_edges"] if e["level_pair"] == k)
            for k in ledger["_meta"]["proposed_level_pairs"]
        }


class TestSchemaCompat:
    def test_proposed_edges_become_atom_edges_without_ledger_fields(
        self, ledger: dict[str, Any]
    ) -> None:
        for e in ledger["proposed_edges"][:200]:
            canonical = {k: v for k, v in e.items() if k not in LEDGER_ONLY_FIELDS}
            AtomEdge.model_validate(canonical)
            with pytest.raises(ValidationError):
                AtomEdge.model_validate(e)  # 원장 전용 필드가 남으면 extra=forbid가 막는다


class TestMutations:
    """변별력 — 정본을 일부러 바꾸면 빌더 판정이 실제로 달라진다."""

    def _first_resolved_pair(self, ledger: dict[str, Any]) -> tuple[int, str, str]:
        """싱크가 정확히 하나인 첫 resolved 레코드 — 뮤테이션 1건이 판정을 통째로 바꾸는 자리."""
        r = next(
            r
            for r in ledger["records"]
            if r["status"] == "resolved" and len(r["resolved_from"]) == 1
        )
        return r["narrative_index"], r["resolved_from"][0], r["to_code"]

    def test_m1_pre_existing_edge_turns_resolved_into_already_present(
        self, builder: Any, graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        idx, a, t = self._first_resolved_pair(ledger)
        mutated = copy.deepcopy(graph)
        mutated["edges"].append({**graph["edges"][0], "from_code": a, "to_code": t})
        out = builder.build_payload(mutated, "m" * 64)
        assert out["records"][idx]["status"] == "already_present"

    def test_m2_reverse_edge_turns_resolved_into_cycle_conflict(
        self, builder: Any, graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        idx, a, t = self._first_resolved_pair(ledger)
        mutated = copy.deepcopy(graph)
        mutated["edges"].append({**graph["edges"][0], "from_code": t, "to_code": a})
        out = builder.build_payload(mutated, "m" * 64)
        assert out["records"][idx]["status"] == "cycle_conflict"

    def test_m3_missing_to_node_is_reported_not_dropped(
        self, builder: Any, graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        idx, _a, t = self._first_resolved_pair(ledger)
        mutated = copy.deepcopy(graph)
        mutated["concepts"] = [c for c in graph["concepts"] if c["code"] != t]
        mutated["edges"] = [e for e in graph["edges"] if t not in (e["from_code"], e["to_code"])]
        out = builder.build_payload(mutated, "m" * 64)
        assert out["records"][idx]["status"] == "to_missing"
        assert len(out["records"]) == len(ledger["records"])


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
        finally:
            builder.OUTPUT_PATH = original
