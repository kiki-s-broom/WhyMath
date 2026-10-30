"""정본 그래프의 과거 스냅샷 복원 — 역사 원장이 묶인 정본(sha256)을 현재 정본에서 되감는다.

왜 필요한가: KG-10·KG-11의 검수 원장(`narrative_edge_resolution_proposal_v1`·
`narrative_edge_reference_ledger_v1/v2`·`narrative_edge_promotion_v1`)은 행 번호
(E001…·R01…)가 검수 기록의 정본이라 정본이 바뀌어도 **재생성하지 않는다**. 대신
그 원장들의 `source_graph_sha256`이 가리키는 정본을 이 모듈이 복원하고, 재현성
테스트는 복원된 정본으로 빌더를 다시 돌려 바이트 동일을 확인한다. 복원이 그
sha256에 정확히 닿지 못하면 예외다 — "대충 비슷한 정본"으로 통과하는 길은 없다.

되감기 단계(최신 → 과거 · KG-12 이후 정본 변경 2종):
  1. 서술형 승격 v2 엣지 제거 — `narrative_edge_promotion_v2.json`의 evidence 태그
     엣지(끝에 덧붙여졌다)
  2. 대학 내부 체인 수리 되돌리기 — `university_chain_repair_v1.json`의 `fix_edges`
     (반전 엣지를 지우고 원 레코드를 원 위치에 되끼운다 · 제거 엣지도 원 위치에)
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

PROMOTION_V2_LEDGER: Final[str] = "narrative_edge_promotion_v2.json"
CHAIN_REPAIR_LEDGER: Final[str] = "university_chain_repair_v1.json"
# 경계(S4-60) 병합 *뒤에* 끝에 덧붙여진 evidence 태그들 — cross_band_edges_merge.pre_merge_view가
# "병합 전 정본"을 복원할 때 함께 벗긴다(덧붙이기 순서: 재생성 → 경계 24 → 서술형 승격 v2 62).
APPENDED_AFTER_CROSS_BAND: Final[tuple[str, ...]] = ("KG-12 서술형 낱말매칭 승격 v2",)


def serialize_graph(graph: Mapping[str, Any]) -> str:
    return json.dumps(graph, ensure_ascii=False, indent=2) + "\n"


def graph_sha256(graph: Mapping[str, Any]) -> str:
    return hashlib.sha256(serialize_graph(graph).encode("utf-8")).hexdigest()


def strip_evidence(graph: Mapping[str, Any], evidence: str) -> dict[str, Any]:
    """evidence 태그 엣지를 뺀 사본(병합이 끝에 덧붙이기였으므로 바이트 단위로 복원된다)."""
    view = dict(graph)
    view["edges"] = [e for e in graph.get("edges", []) if e.get("evidence") != evidence]
    return view


def undo_chain_repair(
    graph: Mapping[str, Any], fix_edges: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """체인 수리(제거·반전)를 되돌린 사본 — 반전 엣지는 지우고, 원 레코드를 원 위치에 되끼운다."""
    reversed_pairs = {
        (fx["to_code"], fx["from_code"]) for fx in fix_edges if fx["action"] == "반전"
    }
    edges = [
        e for e in graph.get("edges", []) if (e["from_code"], e["to_code"]) not in reversed_pairs
    ]
    if len(edges) != len(graph.get("edges", [])) - len(reversed_pairs):
        raise ValueError("반전 엣지가 현재 정본에 기대한 수만큼 없다 — 수리가 적용된 정본이 아니다")
    for fx in sorted(fix_edges, key=lambda x: int(x["original_index"])):
        edges.insert(int(fx["original_index"]), dict(fx["original_record"]))
    view = dict(graph)
    view["edges"] = edges
    return view


def graph_at_sha(
    graph_path: Path,
    want_sha256: str,
    *,
    corpus_dir: Path | None = None,
) -> dict[str, Any]:
    """현재 정본 파일에서 `want_sha256` 정본을 복원한다. 닿지 못하면 ValueError."""
    raw = graph_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() == want_sha256:
        return json.loads(raw)  # type: ignore[no-any-return]
    corpus = corpus_dir or graph_path.parent
    graph: dict[str, Any] = json.loads(raw)
    tried = [hashlib.sha256(raw).hexdigest()]
    promo = corpus / PROMOTION_V2_LEDGER
    if promo.exists():
        ev = json.loads(promo.read_text(encoding="utf-8"))["_meta"]["evidence"]
        graph = strip_evidence(graph, ev)
        tried.append(graph_sha256(graph))
        if tried[-1] == want_sha256:
            return graph
    repair = corpus / CHAIN_REPAIR_LEDGER
    if repair.exists():
        fixes = json.loads(repair.read_text(encoding="utf-8"))["fix_edges"]
        graph = undo_chain_repair(graph, fixes)
        tried.append(graph_sha256(graph))
        if tried[-1] == want_sha256:
            return graph
    raise ValueError(
        f"정본 {want_sha256[:12]}…에 닿지 못했다 — 되감기 단계별 sha256: "
        + " → ".join(t[:12] for t in tried)
    )


__all__ = [
    "APPENDED_AFTER_CROSS_BAND",
    "CHAIN_REPAIR_LEDGER",
    "PROMOTION_V2_LEDGER",
    "graph_at_sha",
    "graph_sha256",
    "serialize_graph",
    "strip_evidence",
    "undo_chain_repair",
]
