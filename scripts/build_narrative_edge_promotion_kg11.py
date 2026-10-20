#!/usr/bin/env python3
"""KG-11 — 스테이징 후보의 AI 2인 블라인드 검수 합의를 승격 원장으로 만든다(결정론·정본 무수정).

입력:
  * 참고 원장 `narrative_edge_reference_ledger_v1.json`(`scope == uni_staging` 행만 승격 대상)
  * 검수 합의 `docs/data/ai_review_narrative_edge_reference_v1.json` — 행 번호(E001…)별
    `{"A": "approve|replace|reject|hold", "A_code": ..., "B": ..., "B_code": ...}`
산출: `narrative_edge_promotion_v1.json` — 합의 규칙(사전 고정 · 설계 문서 §3):
  * 승격 = 두 검수자 모두 approve, 또는 두 검수자가 같은 대체 코드로 replace(그 코드로 교체 승격)
  * 반려 = 둘 다 reject · 그 밖의 불일치 = 보류(승격하지 않는다)
  * Wilson 95% 단측 하한(합의 승인 수 / 전건) < 0.80 이면 승격 0건(메커니즘 불신 — 원장은 비운 채
    기록)
승격 엣지는 `strength 0.8`·`relation_subtype 참고(서술형)→정규화`(KG-09 정규화 엣지와 같은 범주)·
`evidence KG-11 서술형 낱말매칭 승격 v1`로 정본 엣지가 된다. 근거(원 서술·판정)는 원장에만 둔다.
사용: python3 scripts/build_narrative_edge_promotion_kg11.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Final

_REPO: Final[Path] = Path(__file__).resolve().parents[1]
GRAPH_PATH: Final[Path] = _REPO / "data" / "corpus" / "atom_graph_v1" / "graph.json"
REFERENCE_PATH: Final[Path] = (
    _REPO / "data" / "corpus" / "atom_graph_v1" / "narrative_edge_reference_ledger_v1.json"
)
CONSENSUS_PATH: Final[Path] = _REPO / "docs" / "data" / "ai_review_narrative_edge_reference_v1.json"
OUTPUT_PATH: Final[Path] = (
    _REPO / "data" / "corpus" / "atom_graph_v1" / "narrative_edge_promotion_v1.json"
)
EVIDENCE: Final[str] = "KG-11 서술형 낱말매칭 승격 v1"
RELATION_SUBTYPE: Final[str] = "참고(서술형)→정규화"
STRENGTH: Final[float] = 0.8
WILSON_FLOOR: Final[float] = 0.80
REVIEW_MARKER: Final[str] = "검수:AI 2026-10-20"
LEDGER_ONLY: Final[tuple[str, ...]] = (
    "scope",
    "level_pair",
    "match_kind",
    "cognitive_type",
    "ambiguous",
    "narrative_indices",
)


def wilson_lower_bound(successes: int, trials: int, confidence: float = 0.95) -> float:
    """Wilson 단측 신뢰하한 — backend `harness/wilson.py`와 같은 공식(의존을 피해 복제)."""
    if trials <= 0:
        return 0.0
    z = {0.95: 1.6448536269514722}.get(confidence)
    if z is None:
        raise ValueError("confidence는 0.95만 지원")
    p = successes / trials
    denom = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denom
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denom
    return max(0.0, center - margin)


def graph_file_sha256(path: Path = GRAPH_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def consensus_of(a: str, a_code: str, b: str, b_code: str) -> tuple[str, str | None]:
    """(결과, 교체 코드) — approve/replace/reject/hold 합의 규칙(사전 고정)."""
    a, b = a.strip().lower(), b.strip().lower()
    a_code, b_code = (a_code or "").strip(), (b_code or "").strip()
    if a == "approve" and b == "approve":
        return "승인", None
    if a == "replace" and b == "replace" and a_code and a_code == b_code:
        return "교체", a_code
    if a == "reject" and b == "reject":
        return "반려", None
    return "보류", None


def build_payload(
    graph: dict[str, Any],
    reference: dict[str, Any],
    consensus: dict[str, Any],
    graph_sha: str,
) -> dict[str, Any]:
    nodes = {c["code"]: c for c in graph["concepts"]}
    staging = [e for e in reference["proposed_edges"] if e["scope"] == "uni_staging"]
    rows: list[dict[str, Any]] = []
    promoted: list[dict[str, Any]] = []
    counts: dict[str, int] = {"승인": 0, "교체": 0, "반려": 0, "보류": 0}
    existing = {(e["from_code"], e["to_code"]) for e in graph["edges"]}
    for i, e in enumerate(staging, start=1):
        key = f"E{i:03d}"
        v = consensus.get(key)
        if v is None:
            raise ValueError(f"검수 합의에 {key} 없음 — 전건 판정이 아니다")
        result, code = consensus_of(
            v.get("A", ""), v.get("A_code", ""), v.get("B", ""), v.get("B_code", "")
        )
        counts[result] += 1
        from_code = code or e["from_code"]
        row = {
            "row": key,
            "from_code": e["from_code"],
            "to_code": e["to_code"],
            "A": v.get("A"),
            "A_code": v.get("A_code") or None,
            "B": v.get("B"),
            "B_code": v.get("B_code") or None,
            "result": result,
            "promoted_from_code": from_code if result in ("승인", "교체") else None,
        }
        rows.append(row)
        if result in ("승인", "교체"):
            if from_code not in nodes or nodes[from_code]["level"] != "세부개념":
                raise ValueError(f"{key} 교체 코드가 정본 원자가 아님: {from_code}")
            if from_code == e["to_code"] or (from_code, e["to_code"]) in existing:
                row["result"] = "보류"
                row["promoted_from_code"] = None
                row["note"] = "교체 결과가 자기 자신 또는 정본 기존 쌍 — 승격 제외"
                counts[result] -= 1
                counts["보류"] += 1
                continue
            promoted.append(
                {
                    "from_code": from_code,
                    "from_name": nodes[from_code]["name"],
                    "to_code": e["to_code"],
                    "to_name": e["to_name"],
                    "relation": "prerequisite",
                    "relation_subtype": RELATION_SUBTYPE,
                    "school_link": nodes[from_code]["school_level"]
                    != nodes[e["to_code"]]["school_level"],
                    "strength": STRENGTH,
                    "evidence": EVIDENCE,
                    "review_row": key,
                    "review_result": result,
                    "narrative_indices": e["narrative_indices"],
                }
            )
    # 같은 쌍으로 접히는 교체(두 행이 같은 교체 코드)는 한 번만
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for p in sorted(promoted, key=lambda x: (x["from_code"], x["to_code"])):
        pair = (p["from_code"], p["to_code"])
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(p)
    approved = counts["승인"] + counts["교체"]
    lb = wilson_lower_bound(approved, len(staging)) if staging else 0.0
    gate_pass = lb >= WILSON_FLOOR
    edges = unique if gate_pass else []
    meta = {
        "task": "KG-11-narrative-edge-name-matching-and-chain-repair",
        "evidence": EVIDENCE,
        "review_marker": REVIEW_MARKER,
        "source_graph_sha256": graph_sha,
        "staging_total": len(staging),
        "consensus_counts": counts,
        "approval_rate": round(approved / len(staging), 4) if staging else 0.0,
        "wilson_lower_bound_95": round(lb, 4),
        "wilson_floor": WILSON_FLOOR,
        "gate_pass": gate_pass,
        "promoted_edge_count": len(edges),
        "note": (
            "승격 원장 — gate_pass가 false면 edges는 비어 있다(메커니즘 불신·개별 승인분도 미승격)"
            ". "
            "review_row·review_result·narrative_indices는 원장 전용 필드."
        ),
    }
    return {"_meta": meta, "rows": rows, "edges": edges}


def serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--graph-sha", default=None, help="원장에 적을 병합 전 정본 sha(기본: 현재 파일)"
    )
    args = parser.parse_args(argv)
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    consensus = json.loads(CONSENSUS_PATH.read_text(encoding="utf-8"))
    sha = args.graph_sha or graph_file_sha256(GRAPH_PATH)
    text = serialize(build_payload(graph, reference, consensus, sha))
    meta = json.loads(text)["_meta"]
    summary = (
        f"스테이징 {meta['staging_total']} · 합의 {meta['consensus_counts']} · "
        f"Wilson 하한 {meta['wilson_lower_bound_95']} (floor {WILSON_FLOOR}) · "
        f"gate_pass={meta['gate_pass']} · 승격 {meta['promoted_edge_count']}건"
    )
    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current == text:
            print(f"일치: {OUTPUT_PATH} · {summary}")
            return 0
        print(f"차이 있음: {OUTPUT_PATH} · {summary}")
        return 1
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(f"기록: {OUTPUT_PATH} · {summary}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
