"""KG-11 — 서술형 낱말 매칭 참고 원장(`narrative_edge_reference_ledger_v1.json`) 계약.

1. 재현성 — 빌더 재실행이 커밋된 원장과 바이트 동일, source_graph_sha256 = 정본 파일 지문.
2. 전수성 — 서술형 973건 전부 status, 합 = 총수.
3. 구조 — 제안 끝점은 원자·자기루프 0·정본 중복 0·내부 중복 0, 정본 + uni_staging 제안은 비순환.
4. 규칙 — 제안 출발 원자 이름이 원 서술 낱말을 포함(낱말 매칭) · 같은 등급 안 개념 우선 · 모호 매칭은
   uni_ambiguous_hold · 단원 출처는 unit_discard · 초등→대학은 elem_discard.
5. 순환 분류 — 모든 충돌에 kind(가/나/다)·repair_path가 있고 경로 양끝이 to·후보다.
6. 스키마 — 원장 전용 필드를 떼면 AtomEdge(extra=forbid) 통과.
7. 뮤테이션 — 낱말을 바꾸면 no_name_match, 역방향 엣지 주입이면 cycle_conflict(가), 선주입이면
   already_present.
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
    _ROOT / "data" / "corpus" / "atom_graph_v1" / "narrative_edge_reference_ledger_v1.json"
)
BUILDER_PATH = _ROOT / "scripts" / "build_narrative_edge_reference_kg11.py"
LEDGER_ONLY = (
    "scope",
    "level_pair",
    "match_kind",
    "cognitive_type",
    "ambiguous",
    "narrative_indices",
)
STATUSES = {
    "resolved",
    "already_present",
    "cycle_conflict",
    "no_name_match",
    "self_reference",
    "to_missing",
    "no_atoms",
}
SCOPES = {"uni_staging", "uni_ambiguous_hold", "k12_hold", "unit_discard", "elem_discard"}


def _load_builder() -> Any:
    spec = importlib.util.spec_from_file_location("kg11_builder", BUILDER_PATH)
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
        assert builder.serialize(builder.build_payload(graph, sha)).encode("utf-8") == ledger_bytes

    def test_source_sha_matches_canonical_file(self, ledger: dict[str, Any]) -> None:
        assert (
            ledger["_meta"]["source_graph_sha256"]
            == hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest()
        )


class TestCoverage:
    def test_every_narrative_edge_has_a_status(
        self, ledger: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        records = ledger["records"]
        assert len(records) == len(graph["narrative_edges_raw"])
        assert {r["status"] for r in records} <= STATUSES
        assert sum(ledger["_meta"]["status_counts"].values()) == len(records)
        assert ledger["_meta"]["status_counts"]["resolved"] > 0

    def test_resolved_records_point_at_proposed_edges(self, ledger: dict[str, Any]) -> None:
        pairs = {(e["from_code"], e["to_code"]) for e in ledger["proposed_edges"]}
        for r in ledger["records"]:
            if r["status"] == "resolved":
                assert r["resolved_from"] and all(
                    (a, r["to_code"]) in pairs for a in r["resolved_from"]
                )
        covered = {i for e in ledger["proposed_edges"] for i in e["narrative_indices"]}
        assert covered == {
            r["narrative_index"] for r in ledger["records"] if r["status"] == "resolved"
        }


class TestStructureAndRule:
    def test_endpoints_atoms_no_self_loop_no_duplicates(
        self, ledger: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        level = {c["code"]: c["level"] for c in graph["concepts"]}
        existing = {(e["from_code"], e["to_code"]) for e in graph["edges"]}
        seen: set[tuple[str, str]] = set()
        for e in ledger["proposed_edges"]:
            pair = (e["from_code"], e["to_code"])
            assert level[pair[0]] == "세부개념" and level[pair[1]] == "세부개념"
            assert pair[0] != pair[1] and pair not in existing and pair not in seen
            seen.add(pair)
            assert e["scope"] in SCOPES
            assert e["strength"] <= 0.5 and e["relation_subtype"] == "서술형참고(낱말매칭)"

    def test_word_matching_rule_holds(
        self, builder: Any, ledger: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        name = {c["code"]: c["name"] for c in graph["concepts"]}
        for e in ledger["proposed_edges"]:
            words = {ledger["records"][i]["word"] for i in e["narrative_indices"]}
            assert any(
                builder.normalize(w) in builder.normalize(name[e["from_code"]]) for w in words
            )

    def test_scope_classification(self, ledger: dict[str, Any], graph: dict[str, Any]) -> None:
        lvl = {c["code"]: c["school_level"] for c in graph["concepts"]}
        level = {c["code"]: c["level"] for c in graph["concepts"]}
        for e in ledger["proposed_edges"]:
            srcs = {ledger["records"][i]["from_code"] for i in e["narrative_indices"]}
            unit_src = any(level[s] == "단원" for s in srcs)
            f, t = lvl[e["from_code"]], lvl[e["to_code"]]
            if e["scope"] == "unit_discard":
                assert unit_src
            elif e["scope"] in ("uni_staging", "uni_ambiguous_hold"):
                assert (f, t) == ("대학", "대학") and not unit_src
                assert e["ambiguous"] == (e["scope"] == "uni_ambiguous_hold")
            elif e["scope"] == "elem_discard":
                assert f == "초등"
            else:
                assert f in ("중학", "고등") and t == "대학"
        assert ledger["_meta"]["scope_counts"]["uni_staging"] > 0

    def test_graph_plus_staging_is_acyclic(
        self, ledger: dict[str, Any], graph: dict[str, Any]
    ) -> None:
        pairs = [(e["from_code"], e["to_code"]) for e in graph["edges"]]
        pairs += [
            (e["from_code"], e["to_code"])
            for e in ledger["proposed_edges"]
            if e["scope"] == "uni_staging"
        ]
        assert not _has_cycle(pairs)

    def test_cycle_conflicts_are_classified_with_paths(self, ledger: dict[str, Any]) -> None:
        assert ledger["cycle_conflicts"], "순환 충돌 0건은 빌더 결함 의심"
        for c in ledger["cycle_conflicts"]:
            assert c["kind"] in ("가", "나", "다")
            assert c["repair_path"][0] == c["to_code"] and c["repair_path"][-1] == c["candidate"]
            assert len(c["repair_path_edges"]) == len(c["repair_path"]) - 1
        assert sum(ledger["_meta"]["cycle_kind_counts"].values()) == len(ledger["cycle_conflicts"])


class TestSchemaCompat:
    def test_proposed_edges_become_atom_edges(self, ledger: dict[str, Any]) -> None:
        for e in ledger["proposed_edges"][:200]:
            AtomEdge.model_validate({k: v for k, v in e.items() if k not in LEDGER_ONLY})
            with pytest.raises(ValidationError):
                AtomEdge.model_validate(e)


class TestMutations:
    def _single(self, ledger: dict[str, Any]) -> dict[str, Any]:
        return next(
            r
            for r in ledger["records"]
            if r["status"] == "resolved" and len(r["resolved_from"]) == 1
        )

    def test_m1_changed_word_becomes_no_name_match(
        self, builder: Any, graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        r = self._single(ledger)
        mutated = copy.deepcopy(graph)
        mutated["narrative_edges_raw"][r["narrative_index"]]["from_원자명"] = "ZZZ존재하지않는낱말"
        out = builder.build_payload(mutated, "m" * 64)
        assert out["records"][r["narrative_index"]]["status"] == "no_name_match"

    def test_m2_reverse_edge_becomes_cycle_conflict_kind_ga(
        self, builder: Any, graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        r = next(
            x
            for x in ledger["records"]
            if x["status"] == "resolved"
            and len(x["resolved_from"]) == 1
            and x["resolved_from"][0].split("-")[0] == x["to_code"].split("-")[0]
        )
        a, t = r["resolved_from"][0], r["to_code"]
        mutated = copy.deepcopy(graph)
        mutated["edges"].append({**graph["edges"][0], "from_code": t, "to_code": a})
        out = builder.build_payload(mutated, "m" * 64)
        rec = out["records"][r["narrative_index"]]
        assert rec["status"] == "cycle_conflict" and rec["cycle_kinds"] == ["가"]

    def test_m3_pre_existing_edge_becomes_already_present(
        self, builder: Any, graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        r = self._single(ledger)
        a, t = r["resolved_from"][0], r["to_code"]
        mutated = copy.deepcopy(graph)
        mutated["edges"].append({**graph["edges"][0], "from_code": a, "to_code": t})
        out = builder.build_payload(mutated, "m" * 64)
        assert out["records"][r["narrative_index"]]["status"] == "already_present"


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
