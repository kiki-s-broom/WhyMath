"""원자 백본 커밋 코퍼스 무결성 거버넌스 — 초인간 검증 S6(hermetic·DB 0).

정본: `docs/standards/superhuman_verification_standard.md` S6(상시성). 커밋된
`data/corpus/atom_graph_v1/graph.json`(규모는 `docs/data/corpus_facts.md`의 `atom_graph.atoms`·
`atom_graph.edges`)의 **구조 무결성을 DB 없이 상시(빠른 CI) 재검증**한다. 기존 방어는 ⓐ 생성 시점
provenance(손수 편집 후엔 구식·미생성 시 skip) ⓑ Neo4j 적재(load.py·통합 잡) 두 경로뿐이라,
"graph.json이 손수 편집되고 재생성·DB 적재가 없는" 경로가 상시 게이트에서 비었다(load.py:52
docstring이 바로 그 손수 편집 위험을 명시). 이 테스트가 그 갭을 매 PR 닫는다.

*순환 탐지는 정본 함수 재사용*(`validate._find_prerequisite_cycle`) — 재구현 0. 사람은
수천 개 엣지에서 순환·dangling을 눈으로 못 찾지만 기계는 즉시 잡는다(§S6 취지).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from data_pipeline.atom_graph.validate import AtomRelation, _find_prerequisite_cycle

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GRAPH_JSON = _REPO_ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"


def _load_graph() -> dict[str, object]:
    return json.loads(_GRAPH_JSON.read_text(encoding="utf-8"))


def test_committed_atom_graph_is_acyclic() -> None:
    """커밋된 원자 선수그래프에 순환이 없다(DAG 불변식·정본 탐지기 재사용).

    순환이 있으면 학습 경로 위상정렬(l2/learning_path)이 깨진다 — 붕괴 연쇄 #3.
    """
    graph = _load_graph()
    edges = [
        SimpleNamespace(relation=e["relation"], from_code=e["from_code"], to_code=e["to_code"])
        for e in graph["edges"]  # type: ignore[union-attr]
    ]
    cycle = _find_prerequisite_cycle(edges)  # type: ignore[arg-type]
    assert cycle is None, f"커밋된 원자 그래프에 순환: {' → '.join(cycle or [])}"


def test_committed_atom_graph_referential_integrity() -> None:
    """모든 선수엣지의 양 끝(from/to)이 실재 노드다(dangling 0)."""
    graph = _load_graph()
    codes = {c["code"] for c in graph["concepts"]}  # type: ignore[union-attr]
    dangling: list[str] = []
    prereq = 0
    for e in graph["edges"]:  # type: ignore[union-attr]
        if e["relation"] != AtomRelation.PREREQUISITE.value:
            continue
        prereq += 1
        if e["from_code"] not in codes:
            dangling.append(f"{e['from_code']}(from)")
        if e["to_code"] not in codes:
            dangling.append(f"{e['to_code']}(to)")
    assert prereq > 0, "선수엣지가 0 — 코퍼스 로드 이상"
    assert dangling == [], f"dangling 엔드포인트 {len(dangling)}건: {dangling[:10]}"
