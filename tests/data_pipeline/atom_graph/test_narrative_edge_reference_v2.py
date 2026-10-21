"""KG-12 ② — 가드 4종을 얹은 참고 원장 v2 계약: 재현성·v1 불변·가드 정밀도 실측 동결·뮤테이션.

가드 정밀도는 KG-11 검수 합의(`docs/data/ai_review_narrative_edge_reference_v1.json`)로 잰다 — 가드가
반려를 실제로 가리키는지(반려율)는 라벨 대조로만 알 수 있다. 뮤테이션: 동음이의 낱말을 끼우면 가드가
켜지고, 과정 DAG 엣지를 지우면 course_direction이 켜진다.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _ROOT / "data" / "corpus" / "atom_graph_v1"
GRAPH_PATH = _CORPUS / "graph.json"
V1_PATH = _CORPUS / "narrative_edge_reference_ledger_v1.json"
V2_PATH = _CORPUS / "narrative_edge_reference_ledger_v2.json"
IC_PATH = _CORPUS / "inter_course_edges_university_v1.json"
CONSENSUS_PATH = _ROOT / "docs" / "data" / "ai_review_narrative_edge_reference_v1.json"
BUILDER_PATH = _ROOT / "scripts" / "build_narrative_edge_reference_kg12.py"


def _builder() -> Any:
    spec = importlib.util.spec_from_file_location("kg12_builder", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    v1 = json.loads(V1_PATH.read_text(encoding="utf-8"))
    return (
        _builder().load_bound_graph(v1["_meta"]["source_graph_sha256"]),
        v1,
        json.loads(IC_PATH.read_text(encoding="utf-8")),
    )


@pytest.fixture(scope="module")
def v2() -> dict[str, Any]:
    return json.loads(V2_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_regeneration_is_byte_identical(
    inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    b = _builder()
    graph, v1, ic = inputs
    sha = hashlib.sha256(V1_PATH.read_bytes()).hexdigest()
    assert b.serialize(b.build_payload(graph, v1, ic, sha)).encode("utf-8") == V2_PATH.read_bytes()
    meta = json.loads(V2_PATH.read_text(encoding="utf-8"))["_meta"]
    assert meta["source_v1_sha256"] == sha
    assert meta["source_graph_sha256"] == v1["_meta"]["source_graph_sha256"]


def test_v2_is_annotation_of_v1(
    inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any]], v2: dict[str, Any]
) -> None:
    _g, v1, _ic = inputs
    assert len(v2["proposed_edges"]) == len(v1["proposed_edges"])
    for a, b in zip(v1["proposed_edges"], v2["proposed_edges"], strict=True):
        assert {k: b[k] for k in a} == a  # v1 필드 불변
        assert set(b["guards"]) <= set(_builder().GUARD_NAMES)
        assert (b["scope_v2"] == "uni_guard_hold") == (
            a["scope"] == "uni_staging" and bool(b["guards"])
        )
    m = v2["_meta"]
    assert m["uni_staging_v1"] == 183 and m["uni_staging_v2"] == m["scope_v2_counts"]["uni_staging"]
    assert m["uni_staging_v1"] - m["uni_staging_v2"] == m["scope_v2_counts"]["uni_guard_hold"]


def test_twin_candidates_are_real_in_course_twins(
    inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any]], v2: dict[str, Any]
) -> None:
    """in_course_twin이 켜진 행은 도착 과정 안의 실제 쌍둥이(같은 낱말·다른 원자)를 적어야 한다.

    뮤테이션 M9(목록을 비워 내보내기)가 살아남았던 자리 — 가드 비트만 보고 근거를 안 보면 통과한다.
    """
    b = _builder()
    graph, v1, _ic = inputs
    nodes = {c["code"]: c for c in graph["concepts"]}
    records = v1["records"]
    seen = 0
    for e in v2["proposed_edges"]:
        twins = e["twin_candidates"]
        assert ("in_course_twin" in e["guards"]) == bool(twins)
        if not twins:
            continue
        seen += 1
        words = {b.normalize(records[i]["word"]) for i in e["narrative_indices"]}
        for a in twins:
            assert a != e["to_code"]
            assert b.course_of(a) == b.course_of(e["to_code"])
            assert nodes[a]["school_level"] == "대학" and nodes[a]["level"] == "세부개념"
            assert any(w and w in b.normalize(nodes[a]["name"]) for w in words)
    assert seen == v2["_meta"]["guard_counts"]["in_course_twin"] > 0


def test_guard_precision_against_kg11_labels(v2: dict[str, Any]) -> None:
    """실측 동결(2026-10-20): 가드별 반려율 — 라벨이 바뀌면 검수가 바뀐 것이다."""
    cons = json.loads(CONSENSUS_PATH.read_text(encoding="utf-8"))
    staging = [e for e in v2["proposed_edges"] if e["scope"] == "uni_staging"]
    assert len(staging) == len(cons) == 183

    def label(v: dict[str, Any]) -> str:
        if v["A"] == "reject" and v["B"] == "reject":
            return "반려"
        if (v["A"] == "approve" and v["B"] == "approve") or (
            v["A"] == "replace" and v["B"] == "replace" and v["A_code"] == v["B_code"]
        ):
            return "승인"
        return "보류"

    hits: dict[str, list[str]] = {g: [] for g in _builder().GUARD_NAMES}
    for i, e in enumerate(staging, start=1):
        lab = label(cons[f"E{i:03d}"])
        for g in e["guards"]:
            hits[g].append(lab)
    reject_rate = {g: (v.count("반려") / len(v) if v else 0.0) for g, v in hits.items()}
    assert len(hits["homonym_cross_course"]) == 27 and reject_rate["homonym_cross_course"] > 0.9
    assert len(hits["in_course_twin"]) == 27 and reject_rate["in_course_twin"] > 0.8
    assert len(hits["course_direction"]) == 37 and reject_rate["course_direction"] > 0.6
    assert len(hits["short_word"]) == 53 and reject_rate["short_word"] > 0.7
    # 가드 통과 잔여의 승인율이 가드 전보다 높다(가드가 반려를 걸러낸다는 증거)
    labs_all = [label(cons[f"E{i:03d}"]) for i in range(1, 184)]
    labs_pass = [
        label(cons[f"E{i:03d}"]) for i, e in enumerate(staging, start=1) if not e["guards"]
    ]
    assert labs_pass.count("승인") / len(labs_pass) > labs_all.count("승인") / len(labs_all)


class TestMutations:
    def test_homonym_word_triggers_guard(
        self, inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
    ) -> None:
        b = _builder()
        graph, v1, ic = inputs
        v1m = copy.deepcopy(v1)
        target = next(
            e
            for e in v1m["proposed_edges"]
            if e["scope"] == "uni_staging"
            and e["level_pair"] == "대학→대학"
            and b.course_of(e["from_code"]) != b.course_of(e["to_code"])
        )
        for i in target["narrative_indices"]:
            v1m["records"][i]["word"] = "합동"
        out = b.build_payload(graph, v1m, ic, "m" * 64)
        got = next(
            e
            for e in out["proposed_edges"]
            if (e["from_code"], e["to_code"]) == (target["from_code"], target["to_code"])
        )
        assert "homonym_cross_course" in got["guards"] and got["scope_v2"] == "uni_guard_hold"

    def test_removing_course_dag_edges_triggers_direction_guard(
        self, inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any]], v2: dict[str, Any]
    ) -> None:
        b = _builder()
        graph, v1, _ic = inputs
        ok = next(
            e
            for e in v2["proposed_edges"]
            if e["scope"] == "uni_staging"
            and not e["guards"]
            and b.course_of(e["from_code"]) != b.course_of(e["to_code"])
        )
        # 과정 간 원장을 비우고 정본의 과정 간 엣지도 지우면 어느 과정도 상류가 아니다
        gm = copy.deepcopy(graph)
        nodes = {c["code"]: c for c in gm["concepts"]}
        gm["edges"] = [
            e
            for e in gm["edges"]
            if not (
                nodes[e["from_code"]]["school_level"] == "대학"
                and nodes[e["to_code"]]["school_level"] == "대학"
                and b.course_of(e["from_code"]) != b.course_of(e["to_code"])
            )
        ]
        out = b.build_payload(gm, v1, {"edges": []}, "m" * 64)
        got = next(
            e
            for e in out["proposed_edges"]
            if (e["from_code"], e["to_code"]) == (ok["from_code"], ok["to_code"])
        )
        assert "course_direction" in got["guards"]

    def test_check_cli(self) -> None:
        assert _builder().main(["--check"]) == 0
