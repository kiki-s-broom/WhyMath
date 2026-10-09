"""실 코퍼스(data/corpus/atom_graph_v1/) 통계·redaction 단언.

코퍼스가 생성돼 있어야 한다(transform-v1 --output-dir). 미생성 시 fixture가 skip한다.
실데이터 카운트·redaction 누수 0을 *생성된 산출물*로 검증한다(데이터카드 §5 통계 대응).
"""

from __future__ import annotations

import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_STANDARDS = _PROJECT_ROOT / "data" / "corpus" / "standards_v1" / "standards.json"


class TestCorpusCounts:
    def test_node_counts(self, corpus_provenance: dict[str, object]) -> None:
        nc = corpus_provenance["node_counts"]  # type: ignore[index]
        assert nc["atoms"] == 1823
        assert nc["units"] == 217
        assert nc["subunits"] == 643
        assert nc["total"] == 2683

    def test_edge_counts(self, corpus_provenance: dict[str, object]) -> None:
        ec = corpus_provenance["edge_counts"]  # type: ignore[index]
        # 2210(백본 v1) + 24(S4-60 고→대 경계 병합 · cross_band_edges_university_merge_v1)
        assert ec["atom_id_edges"] == 2234
        assert ec["narrative_edges_raw"] == 1007

    def test_university_atoms(self, corpus_provenance: dict[str, object]) -> None:
        assert corpus_provenance["school_level_university_atoms"] == 512

    def test_normalization_counts(self, corpus_provenance: dict[str, object]) -> None:
        nc = corpus_provenance["normalization_counts"]  # type: ignore[index]
        assert nc["자리값"] == 13  # 11(concept/기타 필드) + 2(엣지 from/to_name·4수03-14-2)
        assert nc["경계값"] == 4
        assert nc["미적하이픈_distinct"] == 43  # 미적Ⅰ/Ⅱ 무하이픈 고유 코드 43개
        assert nc["redacted_핵심명제"] == 1324  # K-12 원자 전수 redact

    def test_validation_pass(self, corpus_provenance: dict[str, object]) -> None:
        v = corpus_provenance["validation"]  # type: ignore[index]
        assert v["success"] is True
        assert v["errors"] == 0

    def test_source_sha256(self, corpus_provenance: dict[str, object]) -> None:
        # 정본 소스 = 통합 코퍼스 마스터(54c14913-260622, 2026-06-22 채택). 직전 소스
        # (58b1d193, sha 759f163a…)는 미적 원자ID raw였고, 이 마스터가 원자ID 하이픈을
        # 통일(공수·기수와 정합) → 129 미적 원자ID만 변경, 그 외 카운트 동일.
        assert (
            corpus_provenance["source_sha256"]
            == "83a0d2883fe8552868916181f04ebe687f24dd9cabb91ec4b3096d59a767d0e0"
        )


class TestCorpusRedaction:
    def test_no_body_keys(self, corpus_graph: dict[str, object]) -> None:
        """graph.json에 description/formal_definition 키 0건."""
        text = json.dumps(corpus_graph, ensure_ascii=False)
        assert '"description"' not in text
        assert '"formal_definition"' not in text

    def test_no_ncic_statement_leak(self, corpus_graph: dict[str, object]) -> None:
        """K-12 핵심명제(=NCIC statement) 본문이 graph.json에 0건 나타남."""
        text = json.dumps(corpus_graph, ensure_ascii=False)
        std = json.loads(_STANDARDS.read_text(encoding="utf-8"))
        # 가장 긴 200개 statement 표본(부분 문자열 누수 탐지 — 전수보다 빠르고 충분히 보수적).
        stmts = sorted({s["statement"] for s in std["standards"]}, key=len, reverse=True)
        leaks = [s for s in stmts[:200] if s in text]
        assert leaks == []

    def test_k12_atoms_redacted_marker(self, corpus_graph: dict[str, object]) -> None:
        atoms = [c for c in corpus_graph["concepts"] if c["level"] == "세부개념"]  # type: ignore[index]
        k12 = [c for c in atoms if c["school_level"] != "대학"]
        assert k12, "K-12 원자가 있어야 함"
        assert all("핵심명제/성취기준내용" in c["redacted_fields"] for c in k12)
        assert all(c["core_proposition"] is None for c in k12)

    def test_university_atoms_preserve_core_proposition(
        self, corpus_graph: dict[str, object]
    ) -> None:
        atoms = [c for c in corpus_graph["concepts"] if c["level"] == "세부개념"]  # type: ignore[index]
        univ = [c for c in atoms if c["school_level"] == "대학"]
        assert len(univ) == 512
        assert all(c["core_proposition"] for c in univ)
        assert all(c["redacted_fields"] == [] for c in univ)


class TestCorpusNotation:
    def test_no_nonstandard_saisiot(self, corpus_graph: dict[str, object]) -> None:
        """코퍼스 전체(concepts+edges+narrative)에 비표준 사이시옷 0건.

        회색지대(고유값·진리값·실고유값 등)는 `자리값`/`경계값`/`초기값` 토큰을 포함하지 않아
        무영향. 엣지 from_name/to_name 등 *모든 carried 문자열*을 포괄한다(엣지 이름 정규화
        누락 회귀 방지).
        """
        text = json.dumps(corpus_graph, ensure_ascii=False)
        for token in ("초기값", "자리값", "경계값"):
            assert text.count(token) == 0, f"비표준 사이시옷 잔존: {token}"


class TestCorpusStandardJoin:
    def test_all_standard_codes_resolve(
        self, corpus_graph: dict[str, object], standards_codes: set[str]
    ) -> None:
        """원자 standard_codes(정규화 후)가 전부 standards.json에 존재(미적 정규화 후 미매칭 0)."""
        atoms = [c for c in corpus_graph["concepts"] if c["level"] == "세부개념"]  # type: ignore[index]
        unmatched = {
            code for c in atoms for code in c["standard_codes"] if code not in standards_codes
        }
        assert unmatched == set()
