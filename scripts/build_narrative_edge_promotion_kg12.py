#!/usr/bin/env python3
"""KG-12 ③ — 합의 승인 90건 ∩ 가드 통과 부분집합의 3인째 블라인드 검수를 승격 원장 v2로 만든다.

입력:
  * 참고 원장 v2 `narrative_edge_reference_ledger_v2.json`(`scope == uni_staging` 행 183 — 행 번호
    E001~E183은 KG-11 검수 기록의 정본)
  * KG-11 합의 `docs/data/ai_review_narrative_edge_reference_v1.json`(A·B)
  * 3인째 검수 `docs/data/ai_review_narrative_edge_reference_v2_third.json`(C) — 부분집합 행만
    `{"E001": {"verdict": "approve|replace|reject|hold", "code": "...", "reason": "..."}}`
산출: `narrative_edge_promotion_v2.json` — 규칙(사전 고정 · 설계 문서 §3 · 2026-10-20T23:34Z):
  * 부분집합 = KG-11 합의 결과 ∈ {승인, 교체} ∧ `guards == []`
  * C 승인 = 승인 행에 C `approve`, 또는 교체 행에 C가 **같은 코드**로 `replace`. 그 밖은 불승인
  * Wilson 95% 단측 하한(C 승인 수 / 부분집합 수) < 0.80 이면 승격 0건(원장은 비운 채 기록)
  * 통과하면 C 승인분만 승격 — 불승인분은 보류(원장 기록)
  * 승인분 가운데 S4-01 과목간 저작 원장(미병합 제안)과 같은 쌍은 그 원장의 몫으로 유보(판정은
    승인으로 세고 엣지만 뺀다 — 사후 추가 규칙 · 설계 문서 §3.1에 기록)
승격 엣지는 KG-11 v1과 같은 꼴(`strength 0.8` · `relation_subtype 참고(서술형)→정규화`)이며
evidence만 `KG-12 서술형 낱말매칭 승격 v2`다. 병합은 `narrative_promotion_merge`가 한다.
사용: python3 scripts/build_narrative_edge_promotion_kg12.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Final

_REPO: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src" / "data-pipeline"))

from data_pipeline.atom_graph.graph_history import graph_at_sha  # noqa: E402

GRAPH_PATH: Final[Path] = _REPO / "data" / "corpus" / "atom_graph_v1" / "graph.json"
REFERENCE_V2_PATH: Final[Path] = (
    _REPO / "data" / "corpus" / "atom_graph_v1" / "narrative_edge_reference_ledger_v2.json"
)
CONSENSUS_PATH: Final[Path] = _REPO / "docs" / "data" / "ai_review_narrative_edge_reference_v1.json"
THIRD_PATH: Final[Path] = (
    _REPO / "docs" / "data" / "ai_review_narrative_edge_reference_v2_third.json"
)
OUTPUT_PATH: Final[Path] = (
    _REPO / "data" / "corpus" / "atom_graph_v1" / "narrative_edge_promotion_v2.json"
)
# 미병합 제안 원장(S4-01 대학 과목간 저작 129건)과 같은 쌍은 그 원장의 몫으로 남긴다 — 쌍 하나에
# 출처 하나(중복 방지). 승인 판정은 그대로 세고(게이트 분자 불변) 승격 엣지에서만 뺀다(note 기록).
INTER_COURSE_PATH: Final[Path] = (
    _REPO / "data" / "corpus" / "atom_graph_v1" / "inter_course_edges_university_v1.json"
)
TASK_ID: Final[str] = "KG-12-university-chain-repair-and-word-match-guards"
EVIDENCE: Final[str] = "KG-12 서술형 낱말매칭 승격 v2"
RELATION_SUBTYPE: Final[str] = "참고(서술형)→정규화"
STRENGTH: Final[float] = 0.8
WILSON_FLOOR: Final[float] = 0.80
REVIEW_MARKER: Final[str] = "검수:AI 3인째 블라인드 2026-10-20"
PROVENANCE_MIGRATION_ID: Final[str] = "narrative_edge_promotion_v2"


def _kg11() -> Any:
    """KG-11 승격 빌더의 합의 규칙·Wilson을 그대로 재사용(규칙 복제 금지)."""
    path = _REPO / "scripts" / "build_narrative_edge_promotion_kg11.py"
    spec = importlib.util.spec_from_file_location("kg11_promotion_builder", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def graph_file_sha256(path: Path = GRAPH_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bound_source_sha256() -> str:
    """원장이 묶인 정본 지문 — 커밋된 원장이 있으면 그 `_meta.source_graph_sha256`(병합 *전*
    정본 · 승격 엣지가 덧붙기 전), 없으면 현재 정본 파일 지문."""
    if OUTPUT_PATH.exists():
        committed = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        bound = committed.get("_meta", {}).get("source_graph_sha256") if committed else None
        if bound:
            return str(bound)
    return graph_file_sha256(GRAPH_PATH)


def load_bound_graph() -> tuple[dict[str, Any], str]:
    """묶인(병합 전) 정본을 현재 파일에서 복원한다 — 병합 뒤에는 승격 엣지를 벗겨 되감는다."""
    sha = bound_source_sha256()
    return graph_at_sha(GRAPH_PATH, sha), sha


def third_approves(result: str, code: str | None, verdict: str, c_code: str) -> bool:
    """C 승인 규칙(사전 고정): 승인 행은 approve만, 교체 행은 같은 코드의 replace만."""
    verdict, c_code = verdict.strip().lower(), (c_code or "").strip()
    if result == "승인":
        return verdict == "approve"
    if result == "교체":
        return verdict == "replace" and bool(code) and c_code == code
    return False


def build_payload(
    graph: dict[str, Any],
    reference_v2: dict[str, Any],
    consensus: dict[str, Any],
    third: dict[str, Any],
    graph_sha: str,
    pending_pairs: frozenset[tuple[str, str]] = frozenset(),
) -> dict[str, Any]:
    kg11 = _kg11()
    nodes = {c["code"]: c for c in graph["concepts"]}
    existing = {(e["from_code"], e["to_code"]) for e in graph["edges"]}
    deferred = 0
    staging = [e for e in reference_v2["proposed_edges"] if e["scope"] == "uni_staging"]
    rows: list[dict[str, Any]] = []
    promoted: list[dict[str, Any]] = []
    subset = 0
    c_approved = 0
    c_counts: dict[str, int] = {"approve": 0, "replace": 0, "reject": 0, "hold": 0}
    for i, e in enumerate(staging, start=1):
        key = f"E{i:03d}"
        v = consensus.get(key)
        if v is None:
            raise ValueError(f"KG-11 합의에 {key} 없음")
        result, code = kg11.consensus_of(
            v.get("A", ""), v.get("A_code", ""), v.get("B", ""), v.get("B_code", "")
        )
        if result not in ("승인", "교체") or e["guards"]:
            continue  # 부분집합 밖 — 가드 보류 또는 합의 미승인
        subset += 1
        c = third.get(key)
        if c is None:
            raise ValueError(f"3인째 검수에 {key} 없음 — 부분집합 전건 판정이 아니다")
        verdict = str(c.get("verdict", "")).strip().lower()
        if verdict not in c_counts:
            raise ValueError(f"{key} C 판정 값 이상: {verdict!r}")
        c_counts[verdict] += 1
        ok = third_approves(result, code, verdict, str(c.get("code", "")))
        from_code = code or e["from_code"]
        row = {
            "row": key,
            "from_code": e["from_code"],
            "to_code": e["to_code"],
            "ab_result": result,
            "ab_code": code,
            "C": verdict,
            "C_code": (c.get("code") or "").strip() or None,
            "C_approves": ok,
            "promoted_from_code": from_code if ok else None,
        }
        if ok:
            if from_code not in nodes or nodes[from_code]["level"] != "세부개념":
                raise ValueError(f"{key} 교체 코드가 정본 원자가 아님: {from_code}")
            if from_code == e["to_code"] or (from_code, e["to_code"]) in existing:
                row["C_approves"] = False
                row["promoted_from_code"] = None
                row["note"] = "교체 결과가 자기 자신 또는 정본 기존 쌍 — 승격 제외"
                rows.append(row)
                continue
            c_approved += 1
            if (from_code, e["to_code"]) in pending_pairs:
                deferred += 1
                row["promoted_from_code"] = None
                row["note"] = (
                    "S4-01 대학 과목간 저작 원장(미병합 제안)에 같은 쌍이 있다 — 그 원장의 몫으로 "
                    "남기고 여기서는 승격하지 않는다(판정은 승인으로 센다)"
                )
                rows.append(row)
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
        rows.append(row)
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for p in sorted(promoted, key=lambda x: (x["from_code"], x["to_code"])):
        pair = (p["from_code"], p["to_code"])
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(p)
    lb = kg11.wilson_lower_bound(c_approved, subset) if subset else 0.0
    gate_pass = lb >= WILSON_FLOOR
    edges = unique if gate_pass else []
    meta = {
        "task": TASK_ID,
        "evidence": EVIDENCE,
        "provenance_migration_id": PROVENANCE_MIGRATION_ID,
        "provenance_ledger_names": (
            "narrative_edge_promotion_v2.json·narrative_edge_reference_ledger_v2.json"
        ),
        "provenance_review_label": (
            "검수:AI 2인 블라인드 합의 승인 ∩ 가드 통과 → 3인째 블라인드 C 승인분만"
        ),
        "review_marker": REVIEW_MARKER,
        "source_graph_sha256": graph_sha,
        "source_reference_v2_sha256": (
            hashlib.sha256(REFERENCE_V2_PATH.read_bytes()).hexdigest()
            if REFERENCE_V2_PATH.exists()
            else ""
        ),
        "staging_total": len(staging),
        "subset_total": subset,
        "third_counts": c_counts,
        "third_approved": c_approved,
        "deferred_to_inter_course_ledger": deferred,
        "approval_rate": round(c_approved / subset, 4) if subset else 0.0,
        "wilson_lower_bound_95": round(lb, 4),
        "wilson_floor": WILSON_FLOOR,
        "gate_pass": gate_pass,
        "promoted_edge_count": len(edges),
        "note": (
            "승격 원장 v2 — 부분집합 = KG-11 합의 승인·교체 ∩ 가드 통과. gate_pass가 false면 "
            "edges는 비어 있다. review_row·review_result·narrative_indices는 원장 전용 필드."
        ),
    }
    return {"_meta": meta, "rows": rows, "edges": edges}


def serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--graph-sha", default=None, help="원장에 적을 병합 전 정본 sha")
    args = parser.parse_args(argv)
    graph, bound_sha = load_bound_graph()
    reference = json.loads(REFERENCE_V2_PATH.read_text(encoding="utf-8"))
    consensus = json.loads(CONSENSUS_PATH.read_text(encoding="utf-8"))
    third = json.loads(THIRD_PATH.read_text(encoding="utf-8"))
    sha = args.graph_sha or bound_sha
    pending = frozenset(
        (str(e["from_code"]), str(e["to_code"]))
        for e in json.loads(INTER_COURSE_PATH.read_text(encoding="utf-8")).get("edges", [])
    )
    text = serialize(build_payload(graph, reference, consensus, third, sha, pending))
    meta = json.loads(text)["_meta"]
    summary = (
        f"부분집합 {meta['subset_total']}/{meta['staging_total']} · C {meta['third_counts']} · "
        f"C 승인 {meta['third_approved']}"
        f"(과목간 원장 유보 {meta['deferred_to_inter_course_ledger']}) · "
        f"Wilson 하한 {meta['wilson_lower_bound_95']} "
        f"(floor {WILSON_FLOOR}) · gate_pass={meta['gate_pass']} · "
        f"승격 {meta['promoted_edge_count']}건"
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


if __name__ == "__main__":
    raise SystemExit(main())
