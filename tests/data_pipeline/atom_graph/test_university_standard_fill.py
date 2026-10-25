"""대학 원자 standard_codes 채움(U2) 단위테스트 + 실 코퍼스 검증.

합성 graph/맵으로 채움 규율(세부개념 대학만·K-12 무변경·1:1·멱등)을 못 박고, 실 커밋 코퍼스로
ground truth(512 채움·K-12 보존)를 확인한다(handoff 규율: 실 코퍼스 재검증).
"""

from __future__ import annotations

import json
from pathlib import Path

from data_pipeline.atom_graph.university_standard_fill import (
    build_subunit_standard_map,
    fill_university_standard_codes,
)


def _graph(*nodes: dict[str, object]) -> dict[str, object]:
    return {
        "source_citation": "x",
        "concepts": list(nodes),
        "edges": [],
        "narrative_edges_raw": [],
    }


def _atom(code: str, subunit: str, *, level: str = "세부개념", std: list[str] | None = None):
    return {
        "code": code,
        "level": level,
        "subunit_code": subunit,
        "standard_codes": std or [],
    }


class TestFill:
    def test_fills_university_atom_with_subunit_standard(self) -> None:
        g = _graph(_atom("CALC1-C01", "CALC1-U1-S1"))
        report = fill_university_standard_codes(g, {"CALC1-U1-S1": "[CALC1-01-01]"})
        assert g["concepts"][0]["standard_codes"] == ["[CALC1-01-01]"]
        assert report.university_atoms_filled == 1
        assert report.is_complete

    def test_leaves_k12_atoms_unchanged(self) -> None:
        # K-12 원자(한글 소단원·맵에 없음)는 기존 standard_codes 보존.
        g = _graph(_atom("2수01-01-1", "초수연-U1-S1", std=["[2수01-01]"]))
        report = fill_university_standard_codes(g, {"CALC1-U1-S1": "[CALC1-01-01]"})
        assert g["concepts"][0]["standard_codes"] == ["[2수01-01]"]  # 무변경
        assert report.university_atoms_filled == 0
        assert report.k12_atoms_unchanged == 1

    def test_does_not_fill_subunit_or_unit_nodes(self) -> None:
        # 단원/소단원 노드는 subunit_code가 대학형이라도 채우지 않는다(K-12 관례 — 원자만).
        g = _graph(
            {
                "code": "CALC1-U1-S1",
                "level": "소단원",
                "subunit_code": "CALC1-U1-S1",
                "standard_codes": [],
            },
            {
                "code": "CALC1-U1",
                "level": "단원",
                "subunit_code": None,
                "standard_codes": [],
            },
        )
        fill_university_standard_codes(g, {"CALC1-U1-S1": "[CALC1-01-01]"})
        assert g["concepts"][0]["standard_codes"] == []  # 소단원 노드 무변경
        assert g["concepts"][1]["standard_codes"] == []  # 단원 노드 무변경

    def test_exactly_one_code_per_atom(self) -> None:
        g = _graph(_atom("CALC1-C01", "CALC1-U1-S1"), _atom("CALC1-C02", "CALC1-U1-S1"))
        fill_university_standard_codes(g, {"CALC1-U1-S1": "[CALC1-01-01]"})
        for n in g["concepts"]:
            assert n["standard_codes"] == ["[CALC1-01-01]"]  # 같은 소단원 → 같은 코드·길이 1

    def test_idempotent(self) -> None:
        g = _graph(_atom("CALC1-C01", "CALC1-U1-S1"))
        m = {"CALC1-U1-S1": "[CALC1-01-01]"}
        fill_university_standard_codes(g, m)
        snapshot = json.dumps(g, ensure_ascii=False)
        fill_university_standard_codes(g, m)
        assert json.dumps(g, ensure_ascii=False) == snapshot  # 2회차 동일

    def test_unmapped_university_atom_reported(self) -> None:
        # 대학형 소단원인데 맵에 없으면 미매핑 보고(코드 정합 누락 차단·is_complete False).
        g = _graph(_atom("CALC1-C01", "CALC1-U9-S9"))
        report = fill_university_standard_codes(g, {"CALC1-U1-S1": "[CALC1-01-01]"})
        assert not report.is_complete
        assert report.unmapped_university_atoms == ["CALC1-C01"]


class TestBuildMap:
    def test_joins_links_and_standards(self, tmp_path: Path) -> None:
        (tmp_path / "standards.json").write_text(
            json.dumps({"standards": [{"norm_id": "대학_CALC1_01_01", "code": "[CALC1-01-01]"}]}),
            encoding="utf-8",
        )
        (tmp_path / "concept_standard_links.json").write_text(
            json.dumps(
                {"links": [{"concept_src_id": "CALC1-U1-S1", "norm_id": "대학_CALC1_01_01"}]}
            ),
            encoding="utf-8",
        )
        m = build_subunit_standard_map(tmp_path)
        assert m == {"CALC1-U1-S1": "[CALC1-01-01]"}


# ── 실 코퍼스 ground truth ──────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_GRAPH = _PROJECT_ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"
_STD_DIR = _PROJECT_ROOT / "data" / "corpus" / "standards_university_v1"

# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_FACTS = json.loads(
    (_PROJECT_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)


def test_committed_corpus_university_atoms_filled() -> None:
    import pytest

    if not _GRAPH.exists() or not (_STD_DIR / "standards.json").exists():
        pytest.skip("코퍼스 미생성")
    graph = json.loads(_GRAPH.read_text(encoding="utf-8"))
    sub_to_code = build_subunit_standard_map(_STD_DIR)
    atoms = [n for n in graph["concepts"] if n["level"] == "세부개념"]
    uni = [n for n in atoms if n.get("subunit_code") in sub_to_code]
    # 대학 원자 전부 자기 소단원 성취기준을 첫 코드로 채움. 병합 대표 원자(dedup_merges_v1
    # applied의 canonical)만 은퇴 원자 성취기준의 *병기*가 허용된다(검수:Kiki 2026-07-28 —
    # 그 외 원자의 다중 코드는 여전히 회귀).
    ledger = json.loads((_GRAPH.parent / "dedup_merges_v1.json").read_text(encoding="utf-8"))
    merge_canonicals = {m["canonical"] for m in ledger["applied"]}
    assert len(uni) == _FACTS["atom_graph.university_atoms"]
    for n in uni:
        own = sub_to_code[n["subunit_code"]]
        if n["code"] in merge_canonicals:
            assert n["standard_codes"][0] == own  # 대표 자신 코드 우선·병기 허용
        else:
            assert n["standard_codes"] == [own]
    # K-12 원자(atoms_k12 · 병합 13건 반영)는 비대학 — standard_codes 비어있지 않음(기존 채움 보존).
    k12 = [n for n in atoms if n.get("subunit_code") not in sub_to_code]
    assert len(k12) == _FACTS["atom_graph.atoms_k12"]
    assert all(n["standard_codes"] for n in k12)
