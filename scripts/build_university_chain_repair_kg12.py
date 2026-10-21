#!/usr/bin/env python3
"""KG-12 ① — 대학 내부 체인 역전 (가) 40건의 AI 2인 블라인드 검수 합의 → 수리 원장.

입력:
  * 참고 원장 v1 `narrative_edge_reference_ledger_v1.json`의 `cycle_conflicts`
    (kind 가 · 40건 · 행 R01~R40은 원장 순서)
  * 검수 합의 `docs/data/ai_review_university_chain_repair_v1.json` — 행별
    `{"A": "A|B|hold", "A_edges": [...], "B": ..., "B_edges": [...]}`
    (A = 서술 옳음·정본 체인이 읽기 순서를 선수로 적은 역전 → 정본 수정,
     B = 정본 옳음·서술 반려)
  * 정본 `graph.json` — **수리 전** 정본(sha256이 참고 원장 v1의
    source_graph_sha256과 같아야 한다). 수리가 이미 적용된 정본이면 이 원장
    자신으로 수리 전 정본을 복원해 쓴다(`graph_history`).
산출: `university_chain_repair_v1.json` — 합의 규칙(사전 고정 · 설계 문서 §4):
  * A합의 = 둘 다 A **이고** 수정 엣지 집합이 같다 → 그 엣지를 정본에 적용(제거·반전)
  * B합의 = 둘 다 B → 서술 반려(정본 무변경) · 그 밖 = 보류(정본 무변경 · 기록)
  * `fix_edges`에는 수정 대상 엣지의 **원 레코드와 정본 edges 목록 안 위치**를
    적는다 — 수리 전 정본을 바이트 단위로 복원하는 데 쓴다(역사 원장들이 그
    정본에 묶여 있다)
사용: python3 scripts/build_university_chain_repair_kg12.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Final

_REPO: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src" / "data-pipeline"))

from data_pipeline.atom_graph.graph_history import graph_at_sha  # noqa: E402

GRAPH_PATH: Final[Path] = _REPO / "data" / "corpus" / "atom_graph_v1" / "graph.json"
REFERENCE_V1_PATH: Final[Path] = (
    _REPO / "data" / "corpus" / "atom_graph_v1" / "narrative_edge_reference_ledger_v1.json"
)
CONSENSUS_PATH: Final[Path] = _REPO / "docs" / "data" / "ai_review_university_chain_repair_v1.json"
OUTPUT_PATH: Final[Path] = (
    _REPO / "data" / "corpus" / "atom_graph_v1" / "university_chain_repair_v1.json"
)
TASK_ID: Final[str] = "KG-12-university-chain-repair-and-word-match-guards"
REVIEW_MARKER: Final[str] = "검수:AI 2인 블라인드 2026-10-20"
ACTIONS: Final[frozenset[str]] = frozenset({"제거", "반전"})


def parse_fix(text: str) -> tuple[str, str, str]:
    """`제거 X→Y` / `반전 X→Y` → (action, from, to)."""
    action, _, pair = text.strip().partition(" ")
    if action not in ACTIONS or "→" not in pair:
        raise ValueError(f"수정 엣지 표기 이상: {text!r}")
    f, t = (p.strip() for p in pair.split("→", 1))
    return action, f, t


def consensus_of(v: dict[str, Any]) -> tuple[str, list[tuple[str, str, str]]]:
    a, b = str(v.get("A", "")).strip(), str(v.get("B", "")).strip()
    a_edges = sorted({parse_fix(x) for x in v.get("A_edges", [])})
    b_edges = sorted({parse_fix(x) for x in v.get("B_edges", [])})
    if a == b == "A" and a_edges == b_edges and a_edges:
        return "A합의", a_edges
    if a == b == "B":
        return "B합의", []
    return "보류", []


def build_payload(
    graph: dict[str, Any], reference_v1: dict[str, Any], consensus: dict[str, Any], graph_sha: str
) -> dict[str, Any]:
    nodes = {c["code"]: c for c in graph["concepts"]}
    index_of = {(e["from_code"], e["to_code"]): i for i, e in enumerate(graph["edges"])}
    conflicts = [c for c in reference_v1["cycle_conflicts"] if c["kind"] == "가"]
    rows: list[dict[str, Any]] = []
    counts = {"A합의": 0, "B합의": 0, "보류": 0}
    fixes: dict[tuple[str, str], dict[str, Any]] = {}
    for i, c in enumerate(conflicts, start=1):
        key = f"R{i:02d}"
        v = consensus.get(key)
        if v is None:
            raise ValueError(f"검수 합의에 {key} 없음 — 전건 판정이 아니다")
        result, edges = consensus_of(v)
        counts[result] += 1
        path = {(x["from_code"], x["to_code"]) for x in c["repair_path_edges"]}
        rows.append(
            {
                "row": key,
                "narrative_index": c["narrative_index"],
                "candidate": c["candidate"],
                "to_code": c["to_code"],
                "word": c["word"],
                "A": v.get("A"),
                "B": v.get("B"),
                "result": result,
                "fix_edges": [f"{a} {f}→{t}" for a, f, t in edges],
                "narrative_edge_addable_after_repair": result == "A합의",
            }
        )
        for action, f, t in edges:
            if (f, t) not in path:
                raise ValueError(f"{key} 수정 엣지 {f}→{t}가 정본 역경로 위에 없다")
            if (f, t) not in index_of:
                raise ValueError(f"{key} 수정 엣지 {f}→{t}가 정본에 없다(수리 전 정본인가?)")
            prev = fixes.get((f, t))
            if prev is not None and prev["action"] != action:
                raise ValueError(f"{f}→{t} 처분 충돌: {prev['action']} vs {action}")
            fixes.setdefault(
                (f, t),
                {
                    "action": action,
                    "from_code": f,
                    "to_code": t,
                    "from_name": nodes[f]["name"],
                    "to_name": nodes[t]["name"],
                    "original_index": index_of[(f, t)],
                    "original_record": graph["edges"][index_of[(f, t)]],
                    "rows": [],
                },
            )["rows"].append(key)
    fix_edges = [fixes[k] for k in sorted(fixes, key=lambda k: fixes[k]["original_index"])]
    for fx in fix_edges:
        f, t = fx["from_code"], fx["to_code"]
        if fx["action"] == "반전" and (t, f) in index_of:
            raise ValueError(f"반전 결과 {t}→{f}가 이미 정본에 있다")
        if f.split("-", 1)[0] != t.split("-", 1)[0]:
            raise ValueError(f"과정 밖 엣지는 이 원장의 대상이 아니다: {f}→{t}")
    meta = {
        "task": TASK_ID,
        "review_marker": REVIEW_MARKER,
        "source_graph_sha256": graph_sha,
        "source_reference_v1_sha256": (
            hashlib.sha256(REFERENCE_V1_PATH.read_bytes()).hexdigest()
            if REFERENCE_V1_PATH.exists()
            else ""
        ),
        "conflict_total": len(conflicts),
        "consensus_counts": counts,
        "fix_edge_count": len(fix_edges),
        "fix_action_counts": {
            a: sum(1 for x in fix_edges if x["action"] == a) for a in sorted(ACTIONS)
        },
        "note": (
            "수리 원장 — A합의 행의 수정 엣지만 정본에 적용한다(원본 xlsx 선수엣지_통합 "
            "수정 → regenerate_atom_backbone_v3.sh 재생성). original_index·original_record는 "
            "수리 전 정본을 바이트 단위로 복원하기 위한 것(graph_history). 서술 엣지"
            "(candidate→to) 자체는 여기서 추가하지 않는다 — "
            "narrative_edge_addable_after_repair 행은 후속 낱말 매칭 재해소의 입력."
        ),
    }
    return {"_meta": meta, "rows": rows, "fix_edges": fix_edges}


def serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    reference = json.loads(REFERENCE_V1_PATH.read_text(encoding="utf-8"))
    consensus = json.loads(CONSENSUS_PATH.read_text(encoding="utf-8"))
    want = reference["_meta"]["source_graph_sha256"]
    graph = graph_at_sha(GRAPH_PATH, want)
    text = serialize(build_payload(graph, reference, consensus, want))
    meta = json.loads(text)["_meta"]
    summary = (
        f"(가) {meta['conflict_total']} · 합의 {meta['consensus_counts']} · "
        f"수정 엣지 {meta['fix_edge_count']} {meta['fix_action_counts']}"
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
