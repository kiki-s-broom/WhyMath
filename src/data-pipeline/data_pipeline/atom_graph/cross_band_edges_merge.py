"""고등→대학 경계 엣지 정본 병합 — 검수 통과분을 `graph.json`에 반영 (S4-60).

S4-01 슬라이스 1이 저작·검증한 24건(`cross_band_edges_university_v1.json`)은 게이트
`G-s401-uni-boundary-edge-review`의 AI 검수(2026-10-08)를 통과했다. 이 모듈은 그 승인분을
정본에 넣는 **한 동작**만 한다.

────────────────────────────────────────────────────────────────────────────
스키마 처리 결정 — ⒞ 제안 파일을 근거 원장으로 남기고 정본에는 호환 필드만 넣는다
────────────────────────────────────────────────────────────────────────────
`AtomEdge`는 `extra="forbid"`라 `rationale`을 받지 못한다. 세 안 중 ⒞를 고른 근거(실측):

  * DB 적재 경로(`l1/atom_graph/atom_backend_edge.py`)는 `evidence`를 **읽지 않는다**(슬롯 부재).
    그러므로 ⒜(근거를 evidence에 합성)는 아무도 읽지 않는 산문을 4.9MB 정본에 얹을 뿐이고,
    `evidence`가 가진 "출처 태그" 의미(기존 백본 `원자 백본 v1`과의 구분)를 흐린다.
  * ⒝(모델 필드 추가)는 `AtomEdge` + DB 컬럼(마이그레이션) + 적재기 + prod 재적재까지 번진다.
    24건의 근거를 보관하는 데 비해 파급이 크고, 소비자가 없는 필드를 먼저 만드는 셈이다.
  * ⒞는 2026-07-28 중복 원자 병합 선례(`dedup_merges_v1.json` 원장 + `_provenance.json` 기록)와
    같은 형태다. 정본의 `evidence`는 깨끗한 태그로 남고, 근거는 원장(제안 파일)에 있다.
    태그 ↔ 원장의 1:1 대응은 검증기(`merged_edge_mismatch`·`merged_edge_orphan`)가 기계로 지킨다.

────────────────────────────────────────────────────────────────────────────
안전 장치
────────────────────────────────────────────────────────────────────────────
  1. **정본 변동 선검사** — 원장 `_meta.source_graph_sha256`이 병합 직전 정본의 sha256과 다르면
     병합하지 않는다(그 사이 정본이 바뀐 것 — 검증기부터 재실행).
  2. **병합 전 검증** — 검증기 error 0이어야 한다.
  3. **스키마 호환 증명** — 덧붙이는 레코드마다 `AtomEdge.model_validate`를 통과해야 한다.
  4. **끝에 덧붙이기** — 기존 2,210건의 순서·내용은 건드리지 않는다(diff = 추가분만).
  5. **멱등** — 이미 24건이 다 병합돼 있으면 쓰지 않고 정합만 확인한다. 일부만 있으면 거부한다.
  6. **되돌릴 수 있음** — `pre_merge_view`가 태그 엣지를 뺀 병합 전 정본을 바이트 단위로 복원한다
     (복원본의 sha256이 원장 `source_graph_sha256`과 같다는 것을 테스트가 동결).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from data_pipeline.atom_graph.cross_band_edges import (
    DEFAULT_GRAPH_PATH,
    DEFAULT_PROPOSAL_PATH,
    MERGED_EDGE_FIELDS,
    PROPOSAL_EVIDENCE,
    proposal_edges,
    validate_cross_band_edges,
)
from data_pipeline.atom_graph.models import AtomEdge

DEFAULT_PROVENANCE_PATH: Final[Path] = Path("data/corpus/atom_graph_v1/_provenance.json")
PROVENANCE_MIGRATION_ID: Final[str] = "cross_band_edges_university_merge_v1"


@dataclass(frozen=True, slots=True)
class CrossBandMergeResult:
    """병합 결과 — 운영 가시성(CLAUDE.md "작동한 비율" 원칙: 실제로 덧붙인 건수를 말한다)."""

    proposed: int
    added: int
    already_merged: int
    edges_before: int
    edges_after: int
    pre_merge_sha256: str
    post_merge_sha256: str


def serialize_graph(graph: Mapping[str, Any]) -> str:
    """정본 직렬화 — `graph.json` 관례(ensure_ascii=False · indent=2 · 끝 개행)와 바이트 동일."""
    return json.dumps(graph, ensure_ascii=False, indent=2) + "\n"


def graph_sha256(graph: Mapping[str, Any]) -> str:
    """정본 dict를 정본 직렬화로 찍은 sha256(디스크 파일의 sha256과 같아야 정상)."""
    return hashlib.sha256(serialize_graph(graph).encode("utf-8")).hexdigest()


def pre_merge_view(graph: Mapping[str, Any]) -> dict[str, Any]:
    """출처 태그 엣지를 뺀 병합 전 정본 — 병합이 끝에 덧붙이기였으므로 바이트 단위로 복원된다."""
    view = dict(graph)
    view["edges"] = [e for e in graph.get("edges", []) if e.get("evidence") != PROPOSAL_EVIDENCE]
    return view


def to_canonical_edge(record: Mapping[str, Any]) -> dict[str, Any]:
    """원장 레코드 → 정본 엣지(`rationale` 제외). `AtomEdge` 스키마 호환을 여기서 증명한다."""
    missing = [k for k in MERGED_EDGE_FIELDS if k not in record]
    if missing:
        raise ValueError(f"원장 레코드에 정본 필드 누락: {missing!r}")
    edge = {k: record[k] for k in MERGED_EDGE_FIELDS}
    AtomEdge.model_validate(edge)  # extra="forbid" — 호환 필드만 남았음을 모델이 확인한다.
    return edge


def merge_cross_band_edges(
    graph: MutableMapping[str, Any], proposal: Mapping[str, Any]
) -> CrossBandMergeResult:
    """검수 통과 제안을 `graph`(in-place)의 edges 끝에 덧붙인다. 위반은 예외(조용히 넘기지 않음).

    Raises:
        ValueError: 정본 변동(sha 불일치)·검증기 error·일부만 병합된 상태.
    """
    records = proposal_edges(proposal)
    edges: list[dict[str, Any]] = graph["edges"]
    before = len(edges)
    merged_count = sum(1 for e in edges if e.get("evidence") == PROPOSAL_EVIDENCE)

    if merged_count not in (0, len(records)):
        raise ValueError(
            f"일부만 병합된 상태: 정본의 태그 엣지 {merged_count}건 ≠ 원장 {len(records)}건 — "
            "수동 점검 필요"
        )

    report = validate_cross_band_edges(records, graph)
    if not report.success:
        raise ValueError(f"검증기 error {len(report.errors)}건 — 병합 거부\n{report.report_text()}")

    if merged_count == len(records):  # 멱등 경로 — 정합(위 검증)만 확인하고 쓰지 않는다.
        sha = graph_sha256(pre_merge_view(graph))
        return CrossBandMergeResult(
            proposed=len(records),
            added=0,
            already_merged=merged_count,
            edges_before=before,
            edges_after=before,
            pre_merge_sha256=sha,
            post_merge_sha256=graph_sha256(graph),
        )

    meta_sha = str(proposal.get("_meta", {}).get("source_graph_sha256", ""))
    pre_sha = graph_sha256(graph)
    if meta_sha != pre_sha:
        raise ValueError(
            "정본이 제안 이후 바뀜 — 병합 거부. "
            f"원장 source_graph_sha256={meta_sha[:12]}… ≠ 현재 정본 {pre_sha[:12]}…"
        )

    edges.extend(to_canonical_edge(r) for r in records)
    return CrossBandMergeResult(
        proposed=len(records),
        added=len(records),
        already_merged=0,
        edges_before=before,
        edges_after=len(edges),
        pre_merge_sha256=pre_sha,
        post_merge_sha256=graph_sha256(graph),
    )


def append_provenance(
    provenance: MutableMapping[str, Any], result: CrossBandMergeResult, *, merged_on: str
) -> bool:
    """`_provenance.json` dict에 병합 기록을 남긴다(멱등). 바꿨으면 True.

    `edge_counts.atom_id_edges`는 "정본 원자 엣지 수"라 병합 후 값으로 갱신한다(2026-07-28 중복 병합
    선례: 2213→2210). 병합 기록은 `post_transform_migrations`에 id로 한 번만 남긴다.
    """
    migrations = provenance.setdefault("post_transform_migrations", [])
    if any(isinstance(m, dict) and m.get("id") == PROVENANCE_MIGRATION_ID for m in migrations):
        return False
    migrations.append(
        {
            "id": PROVENANCE_MIGRATION_ID,
            "summary": (
                f"[S4-60 {merged_on}] 고→대 경계 엣지 {result.added}건 병합(검수:AI 2026-10-08 · "
                "게이트 G-s401-uni-boundary-edge-review) — 엣지 "
                f"{result.edges_before}→{result.edges_after}. 노드·기존 엣지 무변경, 끝에 덧붙임. "
                "근거(rationale)는 정본에 넣지 않고 원장 cross_band_edges_university_v1.json에 둔다"
                "(AtomEdge extra=forbid · 결정 ⒞). 병합 전 정본 sha256 "
                f"{result.pre_merge_sha256}."
            ),
        }
    )
    provenance.setdefault("edge_counts", {})["atom_id_edges"] = result.edges_after
    return True


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI — 기본은 병합·기록, `--check`는 쓰지 않고 병합 정합만 판정(exit 0/1)."""
    parser = argparse.ArgumentParser(description="고→대 경계 엣지 정본 병합(S4-60).")
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL_PATH)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE_PATH)
    parser.add_argument("--merged-on", default="2026-10-09", help="provenance 기록 일자")
    parser.add_argument(
        "--check",
        action="store_true",
        help="쓰지 않고 '이미 병합돼 정합한가'만 판정(미병합이면 exit 1).",
    )
    args = parser.parse_args(argv)

    for label, path in (("정본", args.graph), ("원장", args.proposal)):
        if not path.exists():
            print(f"[!] {label} 파일 없음: {path}")
            return 1

    graph = _load(args.graph)
    proposal = _load(args.proposal)
    try:
        result = merge_cross_band_edges(graph, proposal)
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
    "PROVENANCE_MIGRATION_ID",
    "CrossBandMergeResult",
    "append_provenance",
    "graph_sha256",
    "merge_cross_band_edges",
    "pre_merge_view",
    "serialize_graph",
    "to_canonical_edge",
]


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    raise SystemExit(main())
