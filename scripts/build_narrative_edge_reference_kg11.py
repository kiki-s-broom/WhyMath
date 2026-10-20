#!/usr/bin/env python3
"""KG-11 — 서술형 선수엣지 973건의 **낱말 매칭** 재해소 참고 원장(비-traversal) + 순환 충돌 분류.

산출: `data/corpus/atom_graph_v1/narrative_edge_reference_ledger_v1.json`.
정본 `graph.json`은 읽기만 한다.

KG-10의 "소단원 싱크" 규칙은 교수학 검수(AI 2인 블라인드 2026-10-20)에서 FAIL했다 — 소단원의 *완결*
원자를 선수로 두는 완료 의미론이었고, 원 서술의 낱말(`from_원자명`)이 소단원 안 원자 이름과 일치하는
신호를 버렸다. 이 빌더는 그 권고를 따른다:

규칙 `word_match_v1`
  1. `to(후행)`가 dedup 폐기 코드면 정본 코드로 재배선(KG-10과 동일).
  2. 후보 집합 = from 소단원의 원자(단원코드면 단원 산하 원자 — `unit_level`로 표시, 폐기 분류).
  3. 낱말 매칭 — 원 서술 낱말 w(공백·구두점 제거)와 원자 이름 n을 비교해 **정확 일치 > 부분 일치**
     (w가 n에 포함)로 후보를 고르고, 같은 등급 안에서는 **개념 > 절차 > 표상**(`cognitive_type`)
     순으로 가장 앞선 인지축만 남긴다. 둘 이상 남으면 전부 제안하되 `ambiguous`로 표시한다.
  4. 매칭 0건이면 `no_name_match`(싱크 폴백 없음 — 검수가 싱크 규칙을 기각했다).
  5. 제외: 자기 자신(`self_reference`), 정본에 이미 있는 쌍(`already_present`), 넣으면 순환
     (`cycle_conflict` — 정본만으로 역경로가 있으면 (가)/(다), 제안끼리 닫는 순환이면 (나)).

적용 범위(scope) — 검수 권고 교집합:
  uni_staging   대학→대학 · 소단원 출처 · 순환 없음 · 후보 단일 → 스테이징 후보
                (AI 2인 블라인드 검수 → 승격)
  uni_ambiguous_hold  대학→대학인데 같은 등급 후보가 둘 이상(낱말이 여러 원자 이름에 걸침) → 보류
  k12_hold      초·중·고→대학 → 보류(검수 전 승격 금지)
  unit_discard  단원코드 출처 → 폐기
  elem_discard  초등→대학 → 폐기(KG-10 표본 approve 0)

순환 충돌 분류(`cycle_conflicts`):
  가  정본 안에 to→…→후보의 역경로가 **같은 과정 안**에 있다 → 대학 내부 체인(과정 순서) 역전 의심
      — 그 경로의 엣지를 `repair_path`로 적어 체인 수리 제안의 입력으로 낸다(정본 수정은 검수 뒤)
  나  정본만으로는 순환이 없고 이 원장의 다른 제안과 결합해야 순환 → 제안 쪽을 뺀다
  다  역경로가 과정 경계를 넘는다 → 과목간 엣지(S4-61)와의 상호작용 · 별도 검토

이 원장은 **traversal에 쓰지 않는다**: `relation_subtype=서술형참고(낱말매칭)`·`strength=0.5`·
`evidence=KG-11 서술형 낱말매칭 v1`. 정본 승격은 검수 통과분만 별도 병합 모듈이 수행한다.

결정론: 입력(graph.json·dedup 원장)이 같으면 바이트가 같다. 날짜·환경을 쓰지 않는다.
사용: python3 scripts/build_narrative_edge_reference_kg11.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Final

_REPO: Final[Path] = Path(__file__).resolve().parents[1]
GRAPH_PATH: Final[Path] = _REPO / "data" / "corpus" / "atom_graph_v1" / "graph.json"
DEDUP_PATH: Final[Path] = _REPO / "data" / "corpus" / "atom_graph_v1" / "dedup_merges_v1.json"
OUTPUT_PATH: Final[Path] = (
    _REPO / "data" / "corpus" / "atom_graph_v1" / "narrative_edge_reference_ledger_v1.json"
)

TASK_ID: Final[str] = "KG-11-narrative-edge-name-matching-and-chain-repair"
RULE_ID: Final[str] = "word_match_v1"
EVIDENCE: Final[str] = "KG-11 서술형 낱말매칭 v1"
RELATION: Final[str] = "prerequisite"
RELATION_SUBTYPE: Final[str] = "서술형참고(낱말매칭)"
STRENGTH: Final[float] = 0.5
STATUS: Final[str] = (
    "reference — 비-traversal 참고 원장 · 정본 미병합 · 승격은 uni_staging 가운데 AI 2인 블라인드 "
    "검수 통과분만(docs/data/narrative_edge_reference_v1.md)"
)

ATOM_LEVEL: Final[str] = "세부개념"
SUBUNIT_LEVEL: Final[str] = "소단원"
UNIT_LEVEL: Final[str] = "단원"
COGNITIVE_RANK: Final[dict[str, int]] = {"개념": 0, "절차": 1, "표상": 2}
_NORM_RE: Final[re.Pattern[str]] = re.compile(r"[\s·,\.\(\)（）]")


def normalize(text: str | None) -> str:
    return _NORM_RE.sub("", text or "")


def graph_file_sha256(path: Path = GRAPH_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dedup_map(path: Path = DEDUP_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    ledger = json.loads(path.read_text(encoding="utf-8"))
    return {str(x["retired"]): str(x["canonical"]) for x in ledger.get("applied", [])}


def _path(start: str, goal: str, succ: dict[str, set[str]]) -> list[str] | None:
    """start→…→goal 최단 경로(BFS). 없으면 None."""
    prev: dict[str, str | None] = {start: None}
    queue: deque[str] = deque([start])
    while queue:
        node = queue.popleft()
        if node == goal:
            out: list[str] = []
            cur: str | None = node
            while cur is not None:
                out.append(cur)
                cur = prev[cur]
            return out[::-1]
        for nxt in sorted(succ.get(node, ())):
            if nxt not in prev:
                prev[nxt] = node
                queue.append(nxt)
    return None


def _course(code: str) -> str:
    return code.split("-", 1)[0]


def _scope(
    from_node: dict[str, Any], to_node: dict[str, Any], unit_level: bool, ambiguous: bool
) -> str:
    if unit_level:
        return "unit_discard"
    f, t = from_node["school_level"], to_node["school_level"]
    if f == "대학" and t == "대학":
        return "uni_ambiguous_hold" if ambiguous else "uni_staging"
    if f == "초등":
        return "elem_discard"
    return "k12_hold"


def build_payload(
    graph: dict[str, Any], source_sha256: str, dedup_map: dict[str, str] | None = None
) -> dict[str, Any]:
    dedup = load_dedup_map() if dedup_map is None else dedup_map
    nodes: dict[str, dict[str, Any]] = {c["code"]: c for c in graph["concepts"]}
    by_sub: dict[str, list[str]] = defaultdict(list)
    by_unit: dict[str, list[str]] = defaultdict(list)
    for c in graph["concepts"]:
        if c["level"] != ATOM_LEVEL:
            continue
        by_sub[c["subunit_code"]].append(c["code"])
        sub = nodes.get(c["subunit_code"])
        if sub is not None and sub.get("parent_code"):
            by_unit[str(sub["parent_code"])].append(c["code"])

    succ: dict[str, set[str]] = defaultdict(set)
    existing: set[tuple[str, str]] = set()
    edge_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for e in graph["edges"]:
        succ[e["from_code"]].add(e["to_code"])
        existing.add((e["from_code"], e["to_code"]))
        edge_by_pair[(e["from_code"], e["to_code"])] = e

    records: list[dict[str, Any]] = []
    proposed: dict[tuple[str, str], dict[str, Any]] = {}
    cycle_conflicts: list[dict[str, Any]] = []
    combined_succ: dict[str, set[str]] = {k: set(v) for k, v in succ.items()}
    counts: dict[str, int] = defaultdict(int)
    match_counts: dict[str, int] = defaultdict(int)

    for idx, raw in enumerate(graph.get("narrative_edges_raw", [])):
        from_code = str(raw.get("from(선수)"))
        to_raw = str(raw.get("to(후행)"))
        to_code = dedup.get(to_raw, to_raw)
        word = str(raw.get("from_원자명") or "")
        rec: dict[str, Any] = {
            "narrative_index": idx,
            "from_code": from_code,
            "from_level": nodes.get(from_code, {}).get("level"),
            "from_name": nodes.get(from_code, {}).get("name"),
            "word": word,
            "to_code": to_code,
            "to_name": nodes.get(to_code, {}).get("name") or raw.get("to_원자명"),
            "status": "",
            "match_kind": None,
            "candidates": [],
            "resolved_from": [],
            "note": "",
        }
        if to_code != to_raw:
            rec["to_code_raw"] = to_raw
            rec["note"] = f"dedup 재배선: {to_raw}→{to_code}"
        to_node = nodes.get(to_code)
        level = rec["from_level"]
        unit_level = level == UNIT_LEVEL
        group = by_sub.get(from_code, []) if level == SUBUNIT_LEVEL else by_unit.get(from_code, [])
        if to_node is None or to_node["level"] != ATOM_LEVEL:
            rec["status"] = "to_missing"
        elif not group:
            rec["status"] = "no_atoms"
        else:
            w = normalize(word)
            exact = [a for a in group if w and normalize(nodes[a]["name"]) == w]
            partial = [a for a in group if w and w in normalize(nodes[a]["name"])]
            if exact:
                kind, cands = "exact", exact
            elif partial:
                kind, cands = "substr", partial
            else:
                kind, cands = None, []
            if not cands:
                rec["status"] = "no_name_match"
            else:
                best = min(
                    COGNITIVE_RANK.get(str(nodes[a].get("cognitive_type")), 9) for a in cands
                )
                cands = [
                    a
                    for a in cands
                    if COGNITIVE_RANK.get(str(nodes[a].get("cognitive_type")), 9) == best
                ]
                rec["match_kind"] = kind
                rec["candidates"] = cands
                rec["ambiguous"] = len(cands) > 1
                match_counts[kind] += 1
                fresh = [a for a in cands if a != to_code and (a, to_code) not in existing]
                if all(a == to_code for a in cands):
                    rec["status"] = "self_reference"
                elif not fresh:
                    rec["status"] = "already_present"
                    rec["resolved_from"] = [a for a in cands if a != to_code]
                else:
                    accepted: list[str] = []
                    conflicts: list[dict[str, Any]] = []
                    for a in fresh:
                        base_path = _path(to_code, a, succ)
                        comb_path = base_path or _path(to_code, a, combined_succ)
                        if comb_path is None:
                            accepted.append(a)
                            continue
                        if base_path is None:
                            kind_c = "나"
                        elif all(_course(x) == _course(to_code) for x in base_path):
                            kind_c = "가"
                        else:
                            kind_c = "다"
                        pairs = list(zip(comb_path, comb_path[1:], strict=False))
                        conflicts.append(
                            {
                                "narrative_index": idx,
                                "from_code": from_code,
                                "word": word,
                                "candidate": a,
                                "candidate_name": nodes[a]["name"],
                                "to_code": to_code,
                                "to_name": to_node["name"],
                                "kind": kind_c,
                                "repair_path": comb_path,
                                "repair_path_edges": [
                                    {
                                        "from_code": x,
                                        "to_code": y,
                                        "relation_subtype": edge_by_pair.get((x, y), {}).get(
                                            "relation_subtype", "(제안)"
                                        ),
                                    }
                                    for x, y in pairs
                                ],
                            }
                        )
                    if accepted:
                        scope = _scope(nodes[from_code], to_node, unit_level, len(cands) > 1)
                        rec["status"] = "resolved"
                        rec["resolved_from"] = accepted
                        rec["scope"] = scope
                        for a in accepted:
                            key = (a, to_code)
                            entry = proposed.get(key)
                            if entry is None:
                                entry = {
                                    "from_code": a,
                                    "from_name": nodes[a]["name"],
                                    "to_code": to_code,
                                    "to_name": to_node["name"],
                                    "relation": RELATION,
                                    "relation_subtype": RELATION_SUBTYPE,
                                    "school_link": nodes[a]["school_level"]
                                    != to_node["school_level"],
                                    "strength": STRENGTH,
                                    "evidence": EVIDENCE,
                                    "scope": scope,
                                    "level_pair": (
                                        f"{nodes[a]['school_level']}→{to_node['school_level']}"
                                    ),
                                    "match_kind": kind,
                                    "cognitive_type": nodes[a].get("cognitive_type"),
                                    "ambiguous": len(cands) > 1,
                                    "narrative_indices": [],
                                }
                                proposed[key] = entry
                                combined_succ.setdefault(a, set()).add(to_code)
                            entry["narrative_indices"].append(idx)
                    else:
                        rec["status"] = "cycle_conflict"
                        rec["resolved_from"] = [c["candidate"] for c in conflicts]
                    if conflicts:
                        rec["cycle_kinds"] = sorted({c["kind"] for c in conflicts})
                        cycle_conflicts.extend(conflicts)
        counts[rec["status"]] += 1
        records.append(rec)

    edges = [proposed[k] for k in sorted(proposed)]
    scope_counts: dict[str, int] = defaultdict(int)
    for e in edges:
        scope_counts[str(e["scope"])] += 1
    kind_counts: dict[str, int] = defaultdict(int)
    for c in cycle_conflicts:
        kind_counts[str(c["kind"])] += 1
    meta = {
        "task": TASK_ID,
        "rule": RULE_ID,
        "status": STATUS,
        "source_graph_sha256": source_sha256,
        "narrative_total": len(records),
        "status_counts": dict(sorted(counts.items())),
        "match_kind_counts": dict(sorted(match_counts.items())),
        "proposed_edge_count": len(edges),
        "scope_counts": dict(sorted(scope_counts.items())),
        "ambiguous_edge_count": sum(1 for e in edges if e["ambiguous"]),
        "cycle_conflict_count": len(cycle_conflicts),
        "cycle_kind_counts": dict(sorted(kind_counts.items())),
        "note": (
            "비-traversal 참고 원장. proposed_edges의 scope·level_pair·match_kind·cognitive_type·"
            "ambiguous·narrative_indices는 원장 전용 필드라 정본 엣지(AtomEdge)로 옮길 때 "
            "제외한다. "
            "승격은 uni_staging 가운데 검수 통과분만."
        ),
    }
    return {
        "_meta": meta,
        "records": records,
        "proposed_edges": edges,
        "cycle_conflicts": cycle_conflicts,
    }


def serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="기록하지 않고 차이만 판정")
    args = parser.parse_args(argv)
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    text = serialize(build_payload(graph, graph_file_sha256(GRAPH_PATH)))
    meta = json.loads(text)["_meta"]
    summary = (
        f"서술형 {meta['narrative_total']}건 → 참고 엣지 {meta['proposed_edge_count']}건 "
        f"(상태 {meta['status_counts']} · 범위 {meta['scope_counts']} · "
        f"순환 {meta['cycle_kind_counts']})"
    )
    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current == text:
            print(f"일치: {OUTPUT_PATH} · {summary}")
            return 0
        print(f"차이 있음: {OUTPUT_PATH}")
        return 1
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(f"기록: {OUTPUT_PATH} · {summary}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    raise SystemExit(main())
