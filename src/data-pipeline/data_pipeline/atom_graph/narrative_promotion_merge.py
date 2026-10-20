"""서술형 참고 엣지 **승격** 병합 — 검수 통과분을 정본 `graph.json` 끝에 덧붙인다 (KG-11).

입력 원장(`narrative_edge_promotion_v1.json`)은 `scripts/build_narrative_edge_promotion_kg11.py`가
참고 원장(`narrative_edge_reference_ledger_v1.json`)과 AI 2인 블라인드 검수 합의에서 만든다.
이 모듈은 S4-60의 `cross_band_edges_merge`와 같은 계약을 지킨다:

  * **정본 변동 거부** — 원장 `_meta.source_graph_sha256`(병합 전 정본 sha)이 현재 정본과 다르면
    쓰지 않는다.
  * **멱등** — 정본에 태그(evidence) 엣지가 이미 원장 건수만큼 있으면 쓰지 않는다. 일부만 있으면
    거부.
  * **구조 검증** — 양끝 원자 실재·자기루프 0·정본 중복 0·병합 후 prerequisite DAG 비순환.
    위반은 예외.
  * **스키마 호환** — 원장 전용 필드(scope·match_kind·review 등)를 떼고 `AtomEdge`(extra=forbid)로
    검증.
  * **provenance** — `post_transform_migrations`에 id `narrative_edge_promotion_v1`을 한 번만 남기고
    `edge_counts.atom_id_edges`를 병합 후 값으로 갱신한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from data_pipeline.atom_graph.models import AtomEdge

DEFAULT_GRAPH_PATH: Final[Path] = Path("data/corpus/atom_graph_v1/graph.json")
DEFAULT_LEDGER_PATH: Final[Path] = Path(
    "data/corpus/atom_graph_v1/narrative_edge_promotion_v1.json"
)
DEFAULT_PROVENANCE_PATH: Final[Path] = Path("data/corpus/atom_graph_v1/_provenance.json")
PROVENANCE_MIGRATION_ID: Final[str] = "narrative_edge_promotion_v1"
#: 정본 엣지로 옮기는 필드 — `AtomEdge` 스키마와 1:1.
MERGED_EDGE_FIELDS: Final[tuple[str, ...]] = (
    "from_code",
    "from_name",
    "to_code",
    "to_name",
    "relation",
    "relation_subtype",
    "school_link",
    "strength",
    "evidence",
)


@dataclass(frozen=True, slots=True)
class PromotionMergeResult:
    """병합 결과 — "작동한 비율" 원칙: 실제로 덧붙인 건수를 말한다."""

    evidence: str
    proposed: int
    added: int
    already_merged: int
    edges_before: int
    edges_after: int
    pre_merge_sha256: str
    post_merge_sha256: str


def serialize_graph(graph: Mapping[str, Any]) -> str:
    return json.dumps(graph, ensure_ascii=False, indent=2) + "\n"


def graph_sha256(graph: Mapping[str, Any]) -> str:
    return hashlib.sha256(serialize_graph(graph).encode("utf-8")).hexdigest()


def pre_merge_view(graph: Mapping[str, Any], evidence: str) -> dict[str, Any]:
    """해당 evidence 태그 엣지를 뺀 병합 전 정본(병합은 끝에 덧붙이기라 바이트 단위로 복원된다)."""
    view = dict(graph)
    view["edges"] = [e for e in graph.get("edges", []) if e.get("evidence") != evidence]
    return view


def ledger_edges(ledger: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    edges = ledger.get("edges")
    if not isinstance(edges, list):
        raise ValueError("원장에 edges 배열이 없다")
    return [e for e in edges if isinstance(e, Mapping)]


def ledger_evidence(ledger: Mapping[str, Any]) -> str:
    ev = ledger.get("_meta", {}).get("evidence")
    if not isinstance(ev, str) or not ev:
        raise ValueError("원장 _meta.evidence 누락")
    return ev


def to_canonical_edge(record: Mapping[str, Any]) -> dict[str, Any]:
    missing = [k for k in MERGED_EDGE_FIELDS if k not in record]
    if missing:
        raise ValueError(f"원장 레코드에 정본 필드 누락: {missing!r}")
    edge = {k: record[k] for k in MERGED_EDGE_FIELDS}
    AtomEdge.model_validate(edge)
    return edge


def _has_cycle(pairs: Sequence[tuple[str, str]]) -> bool:
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


def validate_promotion(records: Sequence[Mapping[str, Any]], graph: Mapping[str, Any]) -> list[str]:
    """구조 검증 — 오류 메시지 목록(비어 있으면 통과)."""
    errors: list[str] = []
    atoms = {c["code"] for c in graph.get("concepts", []) if c.get("level") == "세부개념"}
    existing = {(e["from_code"], e["to_code"]) for e in graph.get("edges", [])}
    seen: set[tuple[str, str]] = set()
    for r in records:
        pair = (str(r.get("from_code")), str(r.get("to_code")))
        if pair[0] not in atoms or pair[1] not in atoms:
            errors.append(f"끝점이 정본 원자가 아님: {pair}")
        if pair[0] == pair[1]:
            errors.append(f"자기 루프: {pair}")
        if pair in existing and r.get("evidence") not in {
            e.get("evidence")
            for e in graph.get("edges", [])
            if (e["from_code"], e["to_code"]) == pair
        }:
            errors.append(f"정본에 이미 있는 쌍(다른 evidence): {pair}")
        if pair in seen:
            errors.append(f"원장 내부 중복: {pair}")
        seen.add(pair)
        if r.get("relation") != "prerequisite":
            errors.append(f"relation이 prerequisite가 아님: {pair} {r.get('relation')!r}")
    pairs = [(e["from_code"], e["to_code"]) for e in graph.get("edges", [])] + list(seen)
    if _has_cycle(pairs):
        errors.append("병합 후 prerequisite 그래프에 순환")
    return errors


def merge_promotion(
    graph: MutableMapping[str, Any], ledger: Mapping[str, Any]
) -> PromotionMergeResult:
    """검수 통과 원장을 정본(in-place) 끝에 덧붙인다. 위반은 예외로 올린다(조용히 넘기지 않음)."""
    evidence = ledger_evidence(ledger)
    records = ledger_edges(ledger)
    edges: list[dict[str, Any]] = graph["edges"]
    before = len(edges)
    merged_count = sum(1 for e in edges if e.get("evidence") == evidence)
    if merged_count not in (0, len(records)):
        raise ValueError(
            f"일부만 병합된 상태: 정본의 태그 엣지 {merged_count}건 ≠ 원장 {len(records)}건 — "
            "수동 점검"
        )
    for r in records:
        if r.get("evidence") != evidence:
            raise ValueError(f"원장 레코드 evidence 불일치: {r.get('evidence')!r} ≠ {evidence!r}")
    if merged_count == len(records):
        view = pre_merge_view(graph, evidence)
        errors = validate_promotion(records, view)
        # 1:1 대조 — 같은 evidence의 *다른* 원장이 "이미 병합됨"으로 통과하면 안 된다.
        merged_by_pair = {
            (e["from_code"], e["to_code"]): e for e in edges if e.get("evidence") == evidence
        }
        for r in records:
            pair = (str(r.get("from_code")), str(r.get("to_code")))
            merged = merged_by_pair.get(pair)
            if merged is None:
                errors.append(f"원장 엣지가 정본 태그 엣지에 없음: {pair}")
            elif merged != to_canonical_edge(r):
                errors.append(f"정본 태그 엣지가 원장 레코드와 다름: {pair}")
        if errors:
            raise ValueError("병합된 정본이 원장과 정합하지 않음: " + "; ".join(errors[:5]))
        return PromotionMergeResult(
            evidence=evidence,
            proposed=len(records),
            added=0,
            already_merged=merged_count,
            edges_before=before,
            edges_after=before,
            pre_merge_sha256=graph_sha256(view),
            post_merge_sha256=graph_sha256(graph),
        )
    errors = validate_promotion(records, graph)
    if errors:
        raise ValueError(f"검증 error {len(errors)}건 — 병합 거부: " + "; ".join(errors[:5]))
    meta_sha = str(ledger.get("_meta", {}).get("source_graph_sha256", ""))
    pre_sha = graph_sha256(graph)
    if meta_sha != pre_sha:
        raise ValueError(
            f"정본이 원장 이후 바뀜 — 병합 거부. 원장 {meta_sha[:12]}… ≠ 현재 정본 {pre_sha[:12]}…"
        )
    edges.extend(to_canonical_edge(r) for r in records)
    return PromotionMergeResult(
        evidence=evidence,
        proposed=len(records),
        added=len(records),
        already_merged=0,
        edges_before=before,
        edges_after=len(edges),
        pre_merge_sha256=pre_sha,
        post_merge_sha256=graph_sha256(graph),
    )


def append_provenance(
    provenance: MutableMapping[str, Any], result: PromotionMergeResult, *, merged_on: str
) -> bool:
    migrations = provenance.setdefault("post_transform_migrations", [])
    if any(isinstance(m, dict) and m.get("id") == PROVENANCE_MIGRATION_ID for m in migrations):
        return False
    migrations.append(
        {
            "id": PROVENANCE_MIGRATION_ID,
            "summary": (
                f"[KG-11 {merged_on}] 서술형 낱말매칭 참고 엣지 승격 {result.added}건 병합"
                f"(검수:AI 2인 블라인드 · 합의 승인분만 · evidence '{result.evidence}') — 엣지 "
                f"{result.edges_before}→{result.edges_after}. 노드·기존 엣지 무변경, 끝에 덧붙임. "
                "근거(원 서술·검수 판정)는 원장 narrative_edge_promotion_v1.json·"
                "narrative_edge_reference_ledger_v1.json에 둔다. 병합 전 정본 sha256 "
                f"{result.pre_merge_sha256}."
            ),
        }
    )
    provenance.setdefault("edge_counts", {})["atom_id_edges"] = result.edges_after
    return True


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="서술형 참고 엣지 승격 병합(KG-11).")
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE_PATH)
    parser.add_argument("--merged-on", default="2026-10-20")
    parser.add_argument("--check", action="store_true", help="쓰지 않고 병합 정합만 판정")
    args = parser.parse_args(argv)
    for label, path in (("정본", args.graph), ("원장", args.ledger)):
        if not path.exists():
            print(f"[!] {label} 파일 없음: {path}")
            return 1
    graph = _load(args.graph)
    ledger = _load(args.ledger)
    try:
        result = merge_promotion(graph, ledger)
    except ValueError as exc:
        print(f"[!] 병합 거부: {exc}")
        return 1
    if args.check:
        if result.added:
            print(f"[--check] 미병합: 덧붙일 엣지 {result.added}건 남음")
            return 1
        print(f"[--check] 병합 정합: 태그 엣지 {result.already_merged}건 = 원장")
        return 0
    if result.added == 0:
        print(f"이미 병합됨({result.already_merged}건) — 쓰기 없음")
        return 0
    args.graph.write_text(serialize_graph(graph), encoding="utf-8")
    if args.provenance.exists():
        prov = _load(args.provenance)
        if append_provenance(prov, result, merged_on=args.merged_on):
            args.provenance.write_text(
                json.dumps(prov, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    print(
        f"병합: +{result.added}건 · 엣지 {result.edges_before}→{result.edges_after} · "
        f"병합 전 sha256 {result.pre_merge_sha256}"
    )
    return 0


__all__ = [
    "MERGED_EDGE_FIELDS",
    "PROVENANCE_MIGRATION_ID",
    "PromotionMergeResult",
    "append_provenance",
    "graph_sha256",
    "ledger_edges",
    "ledger_evidence",
    "merge_promotion",
    "pre_merge_view",
    "serialize_graph",
    "to_canonical_edge",
    "validate_promotion",
]


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    raise SystemExit(main())
