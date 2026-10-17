"""R4-03 (헌법 제7조) — 문서에 적힌 핵심 숫자는 원본에서 센 실제 값과 같아야 한다.

원본(진실)은 코퍼스 파일이고, 문서는 그 숫자를 인용한다. 문서가 낡으면 이 테스트가 실패해
'문서가 거짓말하는 상태'가 CI 에서 드러난다.

대조 대상(원본 → 문서):
  · 원자 백본 노드·엣지 수 — data/corpus/atom_graph_v1/graph.json → CLAUDE.md · 00_overview.md
  · 오개념(M-id) 수 — data/corpus/misconceptions_v1/misconceptions.json → 04_pedagogy_engine.md
    · 04c_misconception_seven_stage_separation.md

미포함(정직한 한계): 헌법 R4-03 은 '시그니처 패턴 수'도 말하지만, 저장소에 그 수를 셀 수 있는
원본이 없다(문서의 '55+108'은 ROADMAP 설계 수치이고 코퍼스·코드에 대응 목록이 없다). 센 값이
없는 숫자를 대조하는 척하지 않는다 — 원본이 생기면 이 테스트에 항목을 더한다.

'스캔 0건은 실패': 문서에서 숫자를 하나도 못 찾으면 통과가 아니라 실패다(정규식이 낡아 아무것도
검사하지 않는 위장 통과 방지).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ATOM_GRAPH = ROOT / "data/corpus/atom_graph_v1/graph.json"
MISCONCEPTIONS = ROOT / "data/corpus/misconceptions_v1/misconceptions.json"

# (문서 경로, 정규식 — 첫 번째 그룹이 숫자, 비교 대상 키)
NODE_EDGE = re.compile(r"(\d[\d,]*)노드·(\d[\d,]*)엣지")
MID_COUNT = re.compile(r"M-id \*\*(\d[\d,]*)건\*\*")


def _num(text: str) -> int:
    return int(text.replace(",", ""))


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _truth() -> dict[str, int]:
    graph = json.loads(ATOM_GRAPH.read_text(encoding="utf-8"))
    miscon = json.loads(MISCONCEPTIONS.read_text(encoding="utf-8"))
    return {
        "nodes": len(graph["concepts"]),
        "edges": len(graph["edges"]),
        "mid": len(miscon["misconceptions"]),
    }


def test_truth_sources_are_internally_consistent() -> None:
    """원본 자체가 자기 선언(count)과 맞는다 — 원본이 틀렸으면 문서 대조가 무의미하다."""
    miscon = json.loads(MISCONCEPTIONS.read_text(encoding="utf-8"))
    assert miscon["count"] == len(miscon["misconceptions"])


@pytest.mark.parametrize("rel", ["CLAUDE.md", "docs/architecture/00_overview.md"])
def test_atom_backbone_numbers_match_source(rel: str) -> None:
    truth = _truth()
    found = NODE_EDGE.findall(_read(rel))
    assert found, f"{rel}: '<N>노드·<M>엣지' 표기를 못 찾음 — 대조 대상이 0건(정규식·문서 확인)"
    for nodes, edges in found:
        assert _num(nodes) == truth["nodes"], f"{rel}: 노드 {nodes} ≠ 원본 {truth['nodes']}"
        assert _num(edges) == truth["edges"], f"{rel}: 엣지 {edges} ≠ 원본 {truth['edges']}"


@pytest.mark.parametrize(
    "rel",
    [
        "docs/architecture/04_pedagogy_engine.md",
        "docs/architecture/04c_misconception_seven_stage_separation.md",
    ],
)
def test_misconception_count_matches_source(rel: str) -> None:
    truth = _truth()
    found = MID_COUNT.findall(_read(rel))
    assert found, f"{rel}: 'M-id **<N>건**' 표기를 못 찾음 — 대조 대상이 0건(정규식·문서 확인)"
    for n in found:
        assert _num(n) == truth["mid"], f"{rel}: M-id {n} ≠ 원본 {truth['mid']}"
