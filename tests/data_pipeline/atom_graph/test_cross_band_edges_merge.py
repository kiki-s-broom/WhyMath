"""고→대 경계 엣지 정본 병합(S4-60) 테스트 — 재현성·멱등·거부 경로·스키마 호환·CLI.

핵심 주장 5개를 각각 *그 주장이 깨지면 RED인 입력*으로 확인한다(정상 입력만 초록인 것은 증거가
아니다 — CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지"):

1. **재현성** — 병합 전 정본에 병합을 다시 돌리면 커밋된 graph.json과 *바이트 동일*하다.
2. **멱등** — 이미 병합된 정본에는 쓰지 않는다.
3. **거부** — 정본이 바뀌었거나(sha)·일부만 병합됐거나·검증 error가 있으면 병합하지 않는다.
4. **스키마 호환(결정 ⒞)** — 정본 엣지는 `AtomEdge`(extra=forbid)를 통과하고 `rationale`이 없다.
   근거는 원장에만 있고, 정본 태그 엣지 ↔ 원장 행이 1:1이다.
5. **CLI** — `--check`는 쓰지 않고 판정하며, 기본 실행은 graph.json·provenance를 갱신한다.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from data_pipeline.atom_graph.cross_band_edges import (
    MERGED_EDGE_FIELDS,
    PROPOSAL_EVIDENCE,
    proposal_edges,
)
from data_pipeline.atom_graph.cross_band_edges_merge import (
    PROVENANCE_MIGRATION_ID,
    append_provenance,
    graph_sha256,
    main,
    merge_cross_band_edges,
    pre_merge_view,
    serialize_graph,
    to_canonical_edge,
)
from data_pipeline.atom_graph.models import AtomEdge

_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _ROOT / "data" / "corpus" / "atom_graph_v1"
GRAPH_PATH = _CORPUS / "graph.json"
LEDGER_PATH = _CORPUS / "cross_band_edges_university_v1.json"
PROVENANCE_PATH = _CORPUS / "_provenance.json"

_N = 24
_PRE_MERGE_SHA = "1821d31c2614dc1b882b3f9b734736f1f4183e1097105675102c3541363b979f"


@pytest.fixture(scope="module")
def live_graph() -> dict[str, Any]:
    """커밋된 정본(병합 후). 모듈 내 읽기 전용 — 변경하는 테스트는 deepcopy를 쓴다."""
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def ledger() -> dict[str, Any]:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture()
def pre_graph(live_graph: dict[str, Any]) -> dict[str, Any]:
    """병합 전 정본 복원본(테스트마다 새 객체)."""
    return copy.deepcopy(pre_merge_view(live_graph))


class TestReproducibility:
    def test_pre_merge_view_restores_original_snapshot(
        self, live_graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        """태그 엣지를 빼면 병합 직전 정본(sha256 1821d31c…)이 바이트 단위로 복원된다."""
        assert graph_sha256(pre_merge_view(live_graph)) == _PRE_MERGE_SHA
        assert ledger["_meta"]["source_graph_sha256"] == _PRE_MERGE_SHA

    def test_serialization_matches_committed_file(self, live_graph: dict[str, Any]) -> None:
        """직렬화 규약이 파일과 바이트 동일 — 이게 깨지면 병합 diff가 정본 전체로 번진다."""
        assert serialize_graph(live_graph).encode("utf-8") == GRAPH_PATH.read_bytes()

    def test_remerge_reproduces_committed_graph_exactly(
        self, pre_graph: dict[str, Any], ledger: dict[str, Any], live_graph: dict[str, Any]
    ) -> None:
        result = merge_cross_band_edges(pre_graph, ledger)
        assert (result.added, result.edges_before, result.edges_after) == (_N, 2210, 2234)
        assert pre_graph == live_graph
        assert serialize_graph(pre_graph).encode("utf-8") == GRAPH_PATH.read_bytes()

    def test_existing_edges_are_untouched_and_new_ones_are_appended_last(
        self, pre_graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        before = copy.deepcopy(pre_graph["edges"])
        merge_cross_band_edges(pre_graph, ledger)
        assert pre_graph["edges"][: len(before)] == before  # 기존 2,210건 순서·내용 불변
        assert all(e["evidence"] == PROPOSAL_EVIDENCE for e in pre_graph["edges"][len(before) :])
        assert len(pre_graph["concepts"]) == 2683  # 노드 무변경


class TestIdempotence:
    def test_merging_an_already_merged_graph_adds_nothing(
        self, live_graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        graph = copy.deepcopy(live_graph)
        result = merge_cross_band_edges(graph, ledger)
        assert (result.added, result.already_merged) == (0, _N)
        assert graph == live_graph
        assert result.pre_merge_sha256 == _PRE_MERGE_SHA


class TestRefusals:
    """거부 경로 — 각 안전 장치가 *없으면* 병합이 진행될 입력으로 RED를 확인한다."""

    def test_refuses_when_canonical_graph_changed_since_proposal(
        self, pre_graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        pre_graph["concepts"][0]["name"] = pre_graph["concepts"][0]["name"] + "(변조)"
        n_edges = len(pre_graph["edges"])
        with pytest.raises(ValueError, match="정본이 제안 이후 바뀜"):
            merge_cross_band_edges(pre_graph, ledger)
        assert len(pre_graph["edges"]) == n_edges  # 거부 시 정본 객체도 변하지 않는다

    def test_refuses_partially_merged_graph(
        self, pre_graph: dict[str, Any], ledger: dict[str, Any], live_graph: dict[str, Any]
    ) -> None:
        one = next(e for e in live_graph["edges"] if e.get("evidence") == PROPOSAL_EVIDENCE)
        pre_graph["edges"].append(dict(one))
        with pytest.raises(ValueError, match="일부만 병합"):
            merge_cross_band_edges(pre_graph, ledger)

    def test_refuses_when_validator_reports_error(
        self, pre_graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        bad = copy.deepcopy(ledger)
        bad["edges"][0]["to_code"] = "NO-SUCH-CODE"
        assert bad != ledger
        with pytest.raises(ValueError, match="검증기 error"):
            merge_cross_band_edges(pre_graph, bad)

    def test_refuses_when_mutated_ledger_breaks_acyclicity(
        self, pre_graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        """대학→고등 역방향 엣지는 방향 검사에서 막힌다(병합 경로가 검증기를 실제로 거친다)."""
        bad = copy.deepcopy(ledger)
        rec = bad["edges"][0]
        rec["from_code"], rec["to_code"] = rec["to_code"], rec["from_code"]
        with pytest.raises(ValueError, match="검증기 error"):
            merge_cross_band_edges(pre_graph, bad)


class TestSchemaCompatibility:
    def test_canonical_edge_drops_rationale_and_passes_atom_edge_model(
        self, ledger: dict[str, Any]
    ) -> None:
        record = proposal_edges(ledger)[0]
        assert "rationale" in record
        edge = to_canonical_edge(record)
        assert "rationale" not in edge
        assert set(edge) == set(MERGED_EDGE_FIELDS)
        AtomEdge.model_validate(edge)

    def test_extra_field_would_be_rejected_by_model(self, ledger: dict[str, Any]) -> None:
        """대조군: 원장 레코드를 그대로 넣으면 모델이 거부한다 — ⒞ 결정의 전제를 실측으로 고정."""
        with pytest.raises(Exception, match="rationale"):
            AtomEdge.model_validate(dict(proposal_edges(ledger)[0]))

    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [("strength", 1.5), ("from_name", ""), ("relation", "similar_to")],
    )
    def test_model_rejects_values_the_validator_does_not_check(
        self, ledger: dict[str, Any], field: str, bad_value: object
    ) -> None:
        """스키마 증명 줄의 반례 — 필드 *이름*은 맞지만 *값*이 모델 계약을 어기는 레코드.

        검증기(cross_band_edges)는 strength 범위·빈 이름을 보지 않으므로, 이 줄(`AtomEdge.model_validate`)
        이 없으면 이런 레코드가 정본에 들어간다. 정상 원장만으로는 이 줄을 밟지 못한다.
        """
        record = dict(proposal_edges(ledger)[0])
        record[field] = bad_value
        with pytest.raises(Exception, match=field):
            to_canonical_edge(record)

    def test_missing_field_fails_loudly(self, ledger: dict[str, Any]) -> None:
        record = dict(proposal_edges(ledger)[0])
        del record["strength"]
        with pytest.raises(ValueError, match="필드 누락"):
            to_canonical_edge(record)

    def test_all_graph_edges_validate_against_model(self, live_graph: dict[str, Any]) -> None:
        for e in live_graph["edges"]:
            AtomEdge.model_validate(e)

    def test_tagged_edges_and_ledger_are_one_to_one_with_rationale_in_ledger(
        self, live_graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        tagged = {
            (e["from_code"], e["to_code"]): e
            for e in live_graph["edges"]
            if e["evidence"] == PROPOSAL_EVIDENCE
        }
        rows = {(r["from_code"], r["to_code"]): r for r in proposal_edges(ledger)}
        assert set(tagged) == set(rows) and len(tagged) == _N
        for key, row in rows.items():
            assert row["rationale"].strip()  # 근거는 원장에만 있다
            assert "rationale" not in tagged[key]
            assert {k: row[k] for k in MERGED_EDGE_FIELDS} == tagged[key]


class TestPostMergeMeasurements:
    """④ 병합 후 실측 동결 — 기대값을 사후에 맞춘 것이 아니라 문서의 사전 기대(44/2,234)다."""

    def test_density_and_reachability(self, live_graph: dict[str, Any]) -> None:
        from collections import defaultdict, deque

        level = {c["code"]: c["school_level"] for c in live_graph["concepts"]}
        edges = live_graph["edges"]
        crossing = [e for e in edges if level[e["from_code"]] != level[e["to_code"]]]
        assert (len(crossing), len(edges)) == (44, 2234)
        assert round(len(crossing) / len(edges) * 100, 2) == 1.97
        high_to_uni = [
            e
            for e in crossing
            if (level[e["from_code"]], level[e["to_code"]]) == ("고등", "대학")
        ]
        assert len(high_to_uni) == _N

        adj: dict[str, list[str]] = defaultdict(list)
        for e in edges:
            adj[e["from_code"]].append(e["to_code"])
        seen = {c for c, lv in level.items() if lv != "대학"}
        queue = deque(seen)
        while queue:
            for nxt in adj[queue.popleft()]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        uni_atoms = {
            c["code"]
            for c in live_graph["concepts"]
            if c["school_level"] == "대학" and c["level"] == "세부개념"
        }
        assert (len(uni_atoms), len(uni_atoms & seen)) == (512, 198)


class TestProvenance:
    def test_committed_provenance_records_the_migration(self) -> None:
        prov = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
        ids = [m["id"] for m in prov["post_transform_migrations"]]
        assert ids.count(PROVENANCE_MIGRATION_ID) == 1
        assert prov["edge_counts"]["atom_id_edges"] == 2234
        assert _PRE_MERGE_SHA in next(
            m["summary"]
            for m in prov["post_transform_migrations"]
            if m["id"] == PROVENANCE_MIGRATION_ID
        )

    def test_append_provenance_is_idempotent(
        self, pre_graph: dict[str, Any], ledger: dict[str, Any]
    ) -> None:
        result = merge_cross_band_edges(pre_graph, ledger)
        prov: dict[str, Any] = {"edge_counts": {"atom_id_edges": 2210}}
        assert append_provenance(prov, result, merged_on="2026-10-09") is True
        snapshot = copy.deepcopy(prov)
        assert append_provenance(prov, result, merged_on="2026-10-09") is False
        assert prov == snapshot
        assert prov["edge_counts"]["atom_id_edges"] == 2234


class TestCli:
    @staticmethod
    def _copy_corpus(tmp_path: Path, live_graph: dict[str, Any]) -> tuple[Path, Path, Path]:
        """병합 *전* 정본·원장·provenance 사본을 tmp에 만든다(실파일은 건드리지 않는다)."""
        graph = tmp_path / "graph.json"
        graph.write_text(serialize_graph(pre_merge_view(live_graph)), encoding="utf-8")
        ledger = tmp_path / "ledger.json"
        ledger.write_bytes(LEDGER_PATH.read_bytes())
        prov = tmp_path / "_provenance.json"
        prov.write_text(
            json.dumps(
                {"edge_counts": {"atom_id_edges": 2210}, "post_transform_migrations": []},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return graph, ledger, prov

    def test_check_mode_does_not_write_and_flags_unmerged(
        self, tmp_path: Path, live_graph: dict[str, Any]
    ) -> None:
        graph, ledger, prov = self._copy_corpus(tmp_path, live_graph)
        before = graph.read_bytes()
        argv = ["--graph", str(graph), "--proposal", str(ledger), "--provenance", str(prov)]
        assert main([*argv, "--check"]) == 1  # 미병합 → 비정상
        assert graph.read_bytes() == before  # --check는 쓰지 않는다

    def test_default_run_merges_then_is_idempotent(
        self, tmp_path: Path, live_graph: dict[str, Any]
    ) -> None:
        graph, ledger, prov = self._copy_corpus(tmp_path, live_graph)
        argv = ["--graph", str(graph), "--proposal", str(ledger), "--provenance", str(prov)]
        assert main(argv) == 0
        assert graph.read_bytes() == GRAPH_PATH.read_bytes()  # 실파일과 바이트 동일
        merged_prov = json.loads(prov.read_text(encoding="utf-8"))
        assert merged_prov["edge_counts"]["atom_id_edges"] == 2234
        assert [m["id"] for m in merged_prov["post_transform_migrations"]] == [
            PROVENANCE_MIGRATION_ID
        ]
        # 두 번째 실행은 쓰기 없음 + --check 정상.
        after_graph, after_prov = graph.read_bytes(), prov.read_bytes()
        assert main(argv) == 0
        assert (graph.read_bytes(), prov.read_bytes()) == (after_graph, after_prov)
        assert main([*argv, "--check"]) == 0

    def test_refusal_exits_one_and_writes_nothing(
        self, tmp_path: Path, live_graph: dict[str, Any]
    ) -> None:
        graph, ledger, prov = self._copy_corpus(tmp_path, live_graph)
        data = json.loads(graph.read_text(encoding="utf-8"))
        data["concepts"][0]["name"] += "(변조)"
        graph.write_text(serialize_graph(data), encoding="utf-8")
        before = graph.read_bytes()
        argv = ["--graph", str(graph), "--proposal", str(ledger), "--provenance", str(prov)]
        assert main(argv) == 1
        assert graph.read_bytes() == before

    def test_missing_file_is_not_silently_passed(self, tmp_path: Path) -> None:
        assert main(["--graph", str(tmp_path / "없음.json")]) == 1
