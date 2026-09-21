"""원자 백본 `behavior_skills` 병합(SKB-02) 단위테스트 + CLI + 실 코퍼스 ground truth.

합성 크로스워크·구 437 코퍼스로 전파 규칙(union+dedup+사전순·unmapped skip·조인 실패)을
못 박고, 실 커밋 코퍼스로 ground truth를 재확인한다(`test_university_standard_fill.py` 패턴
미러 — handoff 규율: 실 코퍼스 재검증).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from data_pipeline.atom_graph.behavior_skills_merge import (
    BehaviorSkillsMergeResult,
    CrosswalkRecord,
    append_provenance,
    derive_atom_behavior_skills,
    load_behavior_skills_by_src,
    load_concept_src_bridge,
    load_crosswalk_records,
    merge_behavior_skills_into_graph,
    run_behavior_skills_merge,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")


def _graph(*nodes: dict[str, object]) -> dict[str, object]:
    return {"source_citation": "x", "concepts": list(nodes), "edges": [], "narrative_edges_raw": []}


def _atom(code: str, *, level: str = "세부개념") -> dict[str, object]:
    return {"code": code, "level": level}


class TestLoadCrosswalkRecords:
    def test_loads_atom_codes(self, tmp_path: Path) -> None:
        path = tmp_path / "crosswalk.jsonl"
        _write_jsonl(
            path,
            [{"concept_id": "math.a", "atom_codes": ["A1", "A2"], "primary_atom_code": "A1"}],
        )
        records = load_crosswalk_records(path)
        assert records == [CrosswalkRecord(concept_id="math.a", atom_codes=("A1", "A2"))]

    def test_unmapped_row_has_empty_atom_codes(self, tmp_path: Path) -> None:
        path = tmp_path / "crosswalk.jsonl"
        _write_jsonl(
            path, [{"concept_id": "math.b", "atom_codes": [], "unmapped_reason": "no match"}]
        )
        records = load_crosswalk_records(path)
        assert records[0].atom_codes == ()

    def test_rejects_missing_concept_id(self, tmp_path: Path) -> None:
        path = tmp_path / "crosswalk.jsonl"
        _write_jsonl(path, [{"atom_codes": ["A1"]}])
        with pytest.raises(ValueError, match="concept_id"):
            load_crosswalk_records(path)

    def test_rejects_duplicate_concept_id(self, tmp_path: Path) -> None:
        path = tmp_path / "crosswalk.jsonl"
        _write_jsonl(
            path,
            [
                {"concept_id": "math.a", "atom_codes": ["A1"]},
                {"concept_id": "math.a", "atom_codes": ["A2"]},
            ],
        )
        with pytest.raises(ValueError, match="중복"):
            load_crosswalk_records(path)

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "crosswalk.jsonl"
        path.write_text('\n{"concept_id": "math.a", "atom_codes": ["A1"]}\n\n', encoding="utf-8")
        assert len(load_crosswalk_records(path)) == 1


class TestLoadConceptSrcBridge:
    def test_builds_bridge(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.json"
        path.write_text(
            json.dumps({"concepts": [{"concept_id": "math.a", "source_id": "N1"}]}),
            encoding="utf-8",
        )
        assert load_concept_src_bridge(path) == {"math.a": "N1"}

    def test_rejects_missing_source_id(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.json"
        path.write_text(json.dumps({"concepts": [{"concept_id": "math.a"}]}), encoding="utf-8")
        with pytest.raises(ValueError, match="concept_id/source_id"):
            load_concept_src_bridge(path)

    def test_rejects_duplicate_concept_id(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.json"
        path.write_text(
            json.dumps(
                {
                    "concepts": [
                        {"concept_id": "math.a", "source_id": "N1"},
                        {"concept_id": "math.a", "source_id": "N2"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="중복"):
            load_concept_src_bridge(path)


class TestLoadBehaviorSkillsBySrc:
    def test_dedups_and_sorts(self, tmp_path: Path) -> None:
        path = tmp_path / "concepts.jsonl"
        _write_jsonl(path, [{"src_id": "N1", "behavior_skills": ["skill.b", "skill.a", "skill.a"]}])
        assert load_behavior_skills_by_src(path) == {"N1": ("skill.a", "skill.b")}

    def test_missing_behavior_skills_is_empty_tuple(self, tmp_path: Path) -> None:
        path = tmp_path / "concepts.jsonl"
        _write_jsonl(path, [{"src_id": "N1"}])
        assert load_behavior_skills_by_src(path) == {"N1": ()}

    def test_rejects_duplicate_src_id(self, tmp_path: Path) -> None:
        path = tmp_path / "concepts.jsonl"
        _write_jsonl(path, [{"src_id": "N1"}, {"src_id": "N1"}])
        with pytest.raises(ValueError, match="중복"):
            load_behavior_skills_by_src(path)


class TestDeriveAtomBehaviorSkills:
    def test_propagates_to_all_atom_codes_not_just_primary(self) -> None:
        crosswalk = [CrosswalkRecord(concept_id="math.a", atom_codes=("A1", "A2"))]
        bridge = {"math.a": "N1"}
        skills_by_src = {"N1": ("skill.x",)}
        mapping, skipped = derive_atom_behavior_skills(crosswalk, bridge, skills_by_src)
        assert mapping == {"A1": ("skill.x",), "A2": ("skill.x",)}
        assert skipped == 0

    def test_union_dedup_sorted_when_atom_reached_by_two_concepts(self) -> None:
        crosswalk = [
            CrosswalkRecord(concept_id="math.a", atom_codes=("A1",)),
            CrosswalkRecord(concept_id="math.b", atom_codes=("A1",)),
        ]
        bridge = {"math.a": "N1", "math.b": "N2"}
        skills_by_src = {"N1": ("skill.z",), "N2": ("skill.a",)}
        mapping, _ = derive_atom_behavior_skills(crosswalk, bridge, skills_by_src)
        assert mapping == {"A1": ("skill.a", "skill.z")}  # union·사전순(입력 순서 무관)

    def test_unmapped_rows_are_skipped_not_forced(self) -> None:
        crosswalk = [
            CrosswalkRecord(concept_id="math.a", atom_codes=()),
            CrosswalkRecord(concept_id="math.b", atom_codes=("A1",)),
        ]
        bridge = {"math.b": "N1"}
        skills_by_src = {"N1": ("skill.x",)}
        mapping, skipped = derive_atom_behavior_skills(crosswalk, bridge, skills_by_src)
        assert mapping == {"A1": ("skill.x",)}
        assert skipped == 1

    def test_raises_when_concept_id_missing_from_bridge(self) -> None:
        crosswalk = [CrosswalkRecord(concept_id="math.missing", atom_codes=("A1",))]
        with pytest.raises(ValueError, match="graph.json에 없음"):
            derive_atom_behavior_skills(crosswalk, {}, {})

    def test_raises_when_src_id_missing_from_skills(self) -> None:
        crosswalk = [CrosswalkRecord(concept_id="math.a", atom_codes=("A1",))]
        with pytest.raises(ValueError, match="코퍼스 조인 실패"):
            derive_atom_behavior_skills(crosswalk, {"math.a": "N1"}, {})

    def test_concept_with_no_authored_skills_yields_empty_tuple_key(self) -> None:
        """스킬이 빈 concept도 닿은 원자는 키로 남긴다(빈 튜플 — stale 값 청소용 멱등성)."""
        crosswalk = [CrosswalkRecord(concept_id="math.a", atom_codes=("A1",))]
        mapping, _ = derive_atom_behavior_skills(crosswalk, {"math.a": "N1"}, {"N1": ()})
        assert mapping == {"A1": ()}


class TestMergeBehaviorSkillsIntoGraph:
    def test_fills_mapped_atoms_and_empties_others(self) -> None:
        g = _graph(_atom("A1"), _atom("A2"), {"code": "U1", "level": "단원"})
        report = merge_behavior_skills_into_graph(g, {"A1": ("skill.x",)})
        by_code = {n["code"]: n["behavior_skills"] for n in g["concepts"]}
        assert by_code == {"A1": ["skill.x"], "A2": [], "U1": []}
        assert report.total_concepts == 3
        assert report.atoms_mapped == 1
        assert report.atoms_nonempty == 1

    def test_mapped_but_empty_skills_counts_as_mapped_not_nonempty(self) -> None:
        g = _graph(_atom("A1"))
        report = merge_behavior_skills_into_graph(g, {"A1": ()})
        assert g["concepts"][0]["behavior_skills"] == []
        assert report.atoms_mapped == 1
        assert report.atoms_nonempty == 0

    def test_idempotent(self) -> None:
        g = _graph(_atom("A1"))
        mapping = {"A1": ("skill.x", "skill.y")}
        merge_behavior_skills_into_graph(g, mapping)
        snapshot = json.dumps(g, ensure_ascii=False)
        merge_behavior_skills_into_graph(g, mapping)
        assert json.dumps(g, ensure_ascii=False) == snapshot


class TestRunBehaviorSkillsMerge:
    def _fixture_paths(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        crosswalk = tmp_path / "crosswalk.jsonl"
        _write_jsonl(crosswalk, [{"concept_id": "math.a", "atom_codes": ["A1", "A2"]}])
        legacy_graph = tmp_path / "legacy_graph.json"
        legacy_graph.write_text(
            json.dumps({"concepts": [{"concept_id": "math.a", "source_id": "N1"}]}),
            encoding="utf-8",
        )
        legacy_concepts = tmp_path / "legacy_concepts.jsonl"
        _write_jsonl(legacy_concepts, [{"src_id": "N1", "behavior_skills": ["skill.x"]}])
        return crosswalk, legacy_graph, legacy_concepts

    def test_orchestrates_load_derive_merge(self, tmp_path: Path) -> None:
        crosswalk, legacy_graph, legacy_concepts = self._fixture_paths(tmp_path)
        g = _graph(_atom("A1"), _atom("A2"), _atom("A3"))
        result = run_behavior_skills_merge(
            g,
            crosswalk_path=crosswalk,
            legacy_graph_path=legacy_graph,
            legacy_concepts_path=legacy_concepts,
        )
        by_code = {n["code"]: n["behavior_skills"] for n in g["concepts"]}
        assert by_code == {"A1": ["skill.x"], "A2": ["skill.x"], "A3": []}
        assert result.crosswalk_rows == 1
        assert result.unmapped_crosswalk_rows == 0
        assert result.graph_report.atoms_mapped == 2
        assert result.graph_report.atoms_nonempty == 2


class TestAppendProvenance:
    def _result(self) -> BehaviorSkillsMergeResult:
        from data_pipeline.atom_graph.behavior_skills_merge import BehaviorSkillsMergeReport

        return BehaviorSkillsMergeResult(
            graph_report=BehaviorSkillsMergeReport(
                total_concepts=3, atoms_mapped=2, atoms_nonempty=2
            ),
            crosswalk_rows=1,
            unmapped_crosswalk_rows=0,
        )

    def test_adds_block_and_migration_note(self, tmp_path: Path) -> None:
        prov = tmp_path / "_provenance.json"
        prov.write_text(json.dumps({"existing": "kept"}), encoding="utf-8")
        append_provenance(prov, self._result(), crosswalk_path=Path("crosswalk.jsonl"))
        data = json.loads(prov.read_text(encoding="utf-8"))
        assert data["existing"] == "kept"  # 기존 키 보존
        assert data["behavior_skills_merge"]["atoms_mapped"] == 2
        assert data["behavior_skills_merge"]["atoms_nonempty"] == 2
        assert data["behavior_skills_merge"]["crosswalk_rows"] == 1
        assert len(data["post_transform_migrations"]) == 1

    def test_no_duplicate_note_on_second_run(self, tmp_path: Path) -> None:
        prov = tmp_path / "_provenance.json"
        prov.write_text(json.dumps({}), encoding="utf-8")
        append_provenance(prov, self._result(), crosswalk_path=Path("crosswalk.jsonl"))
        append_provenance(prov, self._result(), crosswalk_path=Path("crosswalk.jsonl"))
        data = json.loads(prov.read_text(encoding="utf-8"))
        assert len(data["post_transform_migrations"]) == 1  # 재실행해도 노트 1건만

    def test_missing_provenance_file_is_noop(self, tmp_path: Path) -> None:
        append_provenance(tmp_path / "nope.json", self._result(), crosswalk_path=Path("x"))
        assert not (tmp_path / "nope.json").exists()


# ── 실 코퍼스 ground truth (test_university_standard_fill.py 패턴 미러) ─────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_GRAPH = _PROJECT_ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"
_CROSSWALK = _PROJECT_ROOT / "data" / "corpus" / "concept_atom_crosswalk_v1" / "crosswalk.jsonl"
_LEGACY_GRAPH = _PROJECT_ROOT / "data" / "corpus" / "concept_graph_v1" / "graph.json"
_LEGACY_CONCEPTS = _PROJECT_ROOT / "data" / "corpus" / "concept_graph_v1" / "concepts.jsonl"


def _skip_if_corpus_missing() -> None:
    for path in (_GRAPH, _CROSSWALK, _LEGACY_GRAPH, _LEGACY_CONCEPTS):
        if not path.exists():
            pytest.skip(f"코퍼스 미생성: {path}")


def test_committed_corpus_behavior_skills_merged() -> None:
    """커밋된 atom_graph_v1/graph.json이 이미 SKB-02 병합을 반영했는지(ground truth).

    기대치는 크로스워크 union 결과를 이 테스트가 스스로 재계산해 대조한다(하드코딩 숫자를
    믿지 않음 — CLAUDE.md "검증 없는 실행 안내 금지"의 테스트 축 적용).
    """
    _skip_if_corpus_missing()
    crosswalk = load_crosswalk_records(_CROSSWALK)
    bridge = load_concept_src_bridge(_LEGACY_GRAPH)
    skills_by_src = load_behavior_skills_by_src(_LEGACY_CONCEPTS)
    expected_mapping, expected_skipped = derive_atom_behavior_skills(
        crosswalk, bridge, skills_by_src
    )
    expected_nonempty = sum(1 for skills in expected_mapping.values() if skills)

    graph = json.loads(_GRAPH.read_text(encoding="utf-8"))
    by_code = {n["code"]: tuple(n.get("behavior_skills") or ()) for n in graph["concepts"]}

    # 크로스워크가 닿은 원자는 전부 graph.json에 실재(coverage 회귀 없음).
    assert set(expected_mapping) <= set(by_code)
    for code, skills in expected_mapping.items():
        assert by_code[code] == skills, f"{code}: 기대 {skills} != 실제 {by_code[code]}"

    actual_nonempty = sum(1 for skills in by_code.values() if skills)
    assert actual_nonempty == expected_nonempty > 0

    # 크로스워크가 닿지 않은 원자(대학 등)·단원/소단원은 빈 리스트.
    untouched = [code for code in by_code if code not in expected_mapping]
    assert untouched  # 대학 512건 등 비크로스워크 노드가 실재해야 이 검증에 의미가 있음
    assert all(by_code[code] == () for code in untouched)


def test_committed_provenance_records_behavior_skills_merge() -> None:
    prov_path = _GRAPH.parent / "_provenance.json"
    if not prov_path.exists():
        pytest.skip("_provenance.json 미생성")
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    assert "behavior_skills_merge" in prov
    assert prov["behavior_skills_merge"]["atoms_nonempty"] > 0
