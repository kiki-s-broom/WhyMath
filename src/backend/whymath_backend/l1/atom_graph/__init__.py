"""원자 백본 → backend 런타임 `concept`/`concept_edge` 적재(원자 마이그레이션 Phase 1).

`l1/concept_graph/backend_concept.py`·`backend_edge.py`(구 개념그래프 적재기)의 *원자 백본* 짝이다.
산출 코퍼스 `data/corpus/atom_graph_v1/graph.json`(세부개념 원자 + 단원 + 소단원 노드와 원자ID
선수엣지 — 규모는 `docs/data/corpus_facts.md`의 `atom_graph.atoms`·`atom_graph.units`·
`atom_graph.subunits`·`atom_graph.nodes`·`atom_graph.edges`)을 backend `concept`(3계층·parent
위계)·`concept_edge`(PREREQUISITE + relation_subtype)에 멱등 적재한다. 구 개념그래프(437 개념 —
`concept_graph.concepts`)와 *병존*(code 공간 무충돌 — 원자 code =
원자ID/소단원코드/단원코드, 구 개념 code = UC `{TRACK}-{AREA}-{NNN}`).

**최소 적재 철학**(backend_concept.py 동일): backend `concept`는 *런타임 최소 식별*(code·name_ko·
level·parent·난이도·subject)만 담고, 풍부 원자 메타(인지축·노드유형·전이·원자성·학교급·연결성취기준·
4요소)는 코퍼스에 보존돼 Phase 2 `concept_node` 투영이 가져간다(억지 enum 매핑·이중 보관 회피).

redaction(우선순위 #2): 적재 레코드에 본문 슬롯이 없다 — `description`·`formal_definition`·
`core_proposition`(대학 핵심명제)을 읽지도 채우지도 않는다(구조적 차단·코퍼스/검수 보존).
"""

from __future__ import annotations

from whymath_backend.l1.atom_graph.atom_backend_concept import (
    AtomBackendConceptRecord,
    AtomBackendConceptStore,
    clamp_difficulty,
    load_atom_concepts_from_graph_json,
    populate_atom_concepts,
)
from whymath_backend.l1.atom_graph.atom_backend_edge import (
    AtomBackendEdgeRecord,
    AtomBackendEdgeStore,
    load_atom_edges_from_graph_json,
    populate_atom_edges,
)
from whymath_backend.l1.atom_graph.atom_node_projection import (
    AtomNodeMeta,
    AtomNodeRecord,
    AtomNodeStore,
    fetch_atom_node_meta,
    load_atom_nodes_from_graph_json,
    populate_atom_nodes,
)
from whymath_backend.l1.atom_graph.axis import (
    ATOM_AXIS_META_COLUMNS,
    atom_axis_outerjoin,
    atom_meta_from_row,
    fetch_atom_axis_meta,
)
from whymath_backend.l1.atom_graph.embedding import (
    AtomEmbeddingIndex,
    AtomText,
    atom_embedding_text,
    load_atoms_from_graph_json,
    populate_atom_embeddings,
)
from whymath_backend.l1.atom_graph.populate import populate_atom_backbone
from whymath_backend.l1.atom_graph.retrieval import AtomSearchHit, search_atoms

__all__ = [
    "ATOM_AXIS_META_COLUMNS",
    "AtomBackendConceptRecord",
    "AtomBackendConceptStore",
    "AtomBackendEdgeRecord",
    "AtomBackendEdgeStore",
    "AtomEmbeddingIndex",
    "AtomNodeMeta",
    "AtomNodeRecord",
    "AtomNodeStore",
    "AtomSearchHit",
    "AtomText",
    "atom_axis_outerjoin",
    "atom_embedding_text",
    "atom_meta_from_row",
    "clamp_difficulty",
    "fetch_atom_axis_meta",
    "fetch_atom_node_meta",
    "load_atom_concepts_from_graph_json",
    "load_atom_edges_from_graph_json",
    "load_atom_nodes_from_graph_json",
    "load_atoms_from_graph_json",
    "populate_atom_backbone",
    "populate_atom_concepts",
    "populate_atom_edges",
    "populate_atom_embeddings",
    "populate_atom_nodes",
    "search_atoms",
]
