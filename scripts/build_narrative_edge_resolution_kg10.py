#!/usr/bin/env python3
"""KG-10 ① — 서술형 선수엣지 973건의 대표 원자 해소 *제안 원장* 생성(결정론·멱등·정본 무수정).

무엇을 만드나: `data/corpus/atom_graph_v1/narrative_edge_resolution_proposal_v1.json`.
정본 `graph.json`은 **읽기만** 한다 — 이 스크립트는 정본을 수정하지 않는다. 정본 반영은 교수학 검토
게이트(설계 문서 `docs/data/narrative_edge_resolution_v1.md` §6) 통과 뒤 별도 병합 모듈의 몫이다.

해소 규칙 (설계 문서 §3 — "소단원 싱크" 규칙):
  서술형 엣지는 `from(선수)`가 소단원코드(886건) 또는 단원코드(87건)이고 `to(후행)`가 원자다.
  "소단원 S가 원자 t의 선수"라는 서술을 "S 안의 **싱크 원자**(S 내부 선수 체인에서 후행이 없는
  원자)가 t의 선수"로 읽는다. 싱크는 그 소단원의 완결 개념이라, 싱크를 선수로 두면 내부 체인을
  통해 소단원 전체가 t의 조상이 된다(전체 원자를 다 잇는 '전체' 규칙은 같은 도달성을 엣지 N배로
  사고 — 관계 폭발).
  단원코드 from은 단원 산하 원자 전체의 싱크로 같은 규칙을 적용하되 `단원수준` 표시를 남긴다.

상태(status) 분류 — 해소되지 않은 것도 전부 기록한다(침묵 없음):
  resolved            싱크→t 엣지 제안(1건 이상)
  self_subunit_chain  from이 t 자신의 소단원이고 t에 소단원 내부 선수가 이미 있음 → 내부 체인이 표현
  self_subunit_source from이 t 자신의 소단원인데 t가 소단원의 첫 원자(내부 선수 없음) → 기계 해소
                      불가
  already_present     싱크→t 엣지가 전부 정본에 이미 있음(중복)
  no_atoms            from 소단원/단원에 원자가 없음
  to_missing          to 원자가 정본에 없음(dedup 폐기 코드는 정본 코드로 재배선한 뒤 판정)
  cycle_conflict      싱크→t를 넣으면 순환 — t가 이미 그 싱크의 조상(서술이 역방향이거나 싱크가
                      t보다 뒤)

결정론: 입력(graph.json)이 같으면 바이트가 같다(테스트 `test_regeneration_is_byte_identical`). 날짜·
실행 환경을 쓰지 않는다.

사용:
    python3 scripts/build_narrative_edge_resolution_kg10.py            # 생성·기록
    python3 scripts/build_narrative_edge_resolution_kg10.py --check    # 드라이런(차이만 판정)
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Final

_REPO: Final[Path] = Path(__file__).resolve().parents[1]
GRAPH_PATH: Final[Path] = _REPO / "data" / "corpus" / "atom_graph_v1" / "graph.json"
#: dedup 원장(2026-07-28) — 정본 엣지는 폐기→정본 코드로 재배선됐지만 서술형 raw는 원문 그대로라
#: `to(후행)`가 폐기 코드일 수 있다(실측: NUMER-C05→CALC1-C16 2건). 같은 규칙으로 재배선한다.
DEDUP_PATH: Final[Path] = _REPO / "data" / "corpus" / "atom_graph_v1" / "dedup_merges_v1.json"
OUTPUT_PATH: Final[Path] = (
    _REPO / "data" / "corpus" / "atom_graph_v1" / "narrative_edge_resolution_proposal_v1.json"
)

TASK_ID: Final[str] = "KG-10-narrative-edge-resolution-and-boundary-review"
RULE_ID: Final[str] = "subunit_sink_v1"
EVIDENCE: Final[str] = "KG-10 서술형 해소 v1"
RELATION: Final[str] = "prerequisite"
RELATION_SUBTYPE: Final[str] = "서술형해소(싱크)"
#: 기계 해소라 원본 저작 엣지(0.8)보다 낮은 신뢰를 준다 — 설계 문서 §3.4.
STRENGTH: Final[float] = 0.6
STATUS_PROPOSAL: Final[str] = "proposal — 교수학 검토 전 · 정본 미병합"

ATOM_LEVEL: Final[str] = "세부개념"
SUBUNIT_LEVEL: Final[str] = "소단원"
UNIT_LEVEL: Final[str] = "단원"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def graph_file_sha256(path: Path = GRAPH_PATH) -> str:
    """정본 파일 바이트 sha256 — 원장 `_meta.source_graph_sha256`(파일 지문)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _join(existing: str, text: str) -> str:
    return f"{existing} · {text}" if existing else text


def _reachable(start: str, succ: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        for nxt in succ.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def load_dedup_map(path: Path = DEDUP_PATH) -> dict[str, str]:
    """폐기 코드 → 정본 코드(dedup_merges_v1.json `applied`). 파일이 없으면 빈 맵(재배선 없음)."""
    if not path.exists():
        return {}
    ledger = json.loads(path.read_text(encoding="utf-8"))
    return {str(x["retired"]): str(x["canonical"]) for x in ledger.get("applied", [])}


def build_payload(
    graph: dict[str, Any], source_sha256: str, dedup_map: dict[str, str] | None = None
) -> dict[str, Any]:
    """정본 dict → 제안 원장 dict(순수 함수 · 정본 무수정)."""
    dedup = load_dedup_map() if dedup_map is None else dedup_map
    nodes: dict[str, dict[str, Any]] = {c["code"]: c for c in graph["concepts"]}
    atoms_by_subunit: dict[str, list[str]] = defaultdict(list)
    atoms_by_unit: dict[str, list[str]] = defaultdict(list)
    for c in graph["concepts"]:
        if c["level"] != ATOM_LEVEL:
            continue
        atoms_by_subunit[c["subunit_code"]].append(c["code"])
        sub = nodes.get(c["subunit_code"])
        if sub is not None and sub.get("parent_code"):
            atoms_by_unit[str(sub["parent_code"])].append(c["code"])

    succ: dict[str, set[str]] = defaultdict(set)
    pred: dict[str, set[str]] = defaultdict(set)
    existing: set[tuple[str, str]] = set()
    for e in graph["edges"]:
        succ[e["from_code"]].add(e["to_code"])
        pred[e["to_code"]].add(e["from_code"])
        existing.add((e["from_code"], e["to_code"]))

    def sinks(group: list[str]) -> list[str]:
        members = set(group)
        return [a for a in group if not (succ.get(a, set()) & members)]

    records: list[dict[str, Any]] = []
    proposed: dict[tuple[str, str], dict[str, Any]] = {}
    # 결합 그래프(정본 + 지금까지 채택한 제안)로 순환을 판정한다 — 제안끼리 만드는 순환도 막는다.
    combined_succ: dict[str, set[str]] = {k: set(v) for k, v in succ.items()}
    counts: dict[str, int] = defaultdict(int)

    for idx, raw in enumerate(graph.get("narrative_edges_raw", [])):
        from_code = str(raw.get("from(선수)"))
        to_raw = str(raw.get("to(후행)"))
        to_code = dedup.get(to_raw, to_raw)
        rec: dict[str, Any] = {
            "narrative_index": idx,
            "from_code": from_code,
            "from_level": nodes.get(from_code, {}).get("level"),
            "from_name": nodes.get(from_code, {}).get("name") or raw.get("from_원자명"),
            "to_code": to_code,
            "to_name": nodes.get(to_code, {}).get("name") or raw.get("to_원자명"),
            "status": "",
            "resolved_from": [],
            "note": "",
        }
        if to_code != to_raw:
            rec["to_code_raw"] = to_raw
            rec["note"] = f"dedup 재배선: {to_raw}→{to_code}"
        to_node = nodes.get(to_code)
        if to_node is None or to_node["level"] != ATOM_LEVEL:
            rec["status"] = "to_missing"
            rec["note"] = _join(rec["note"], "to 원자가 정본에 없음 — 저작 정정 필요")
        else:
            level = rec["from_level"]
            if level == SUBUNIT_LEVEL:
                group = atoms_by_subunit.get(from_code, [])
            elif level == UNIT_LEVEL:
                group = atoms_by_unit.get(from_code, [])
            else:
                group = []
            if not group:
                rec["status"] = "no_atoms"
                rec["note"] = _join(
                    rec["note"], "from 소단원/단원에 원자가 없음 — 원자 저작 뒤 재시도"
                )
            elif level == SUBUNIT_LEVEL and to_node["subunit_code"] == from_code:
                if pred.get(to_code, set()) & set(group):
                    rec["status"] = "self_subunit_chain"
                    rec["note"] = _join(
                        rec["note"], "자기 소단원 — 내부 선수 체인이 이미 표현(추가 엣지 불필요)"
                    )
                else:
                    rec["status"] = "self_subunit_source"
                    rec["note"] = _join(
                        rec["note"],
                        "자기 소단원의 첫 원자 — 소단원 안에서는 선수를 만들 수 없음(저작 판단)",
                    )
            else:
                cands = [a for a in sinks(group) if a != to_code]
                dup = [a for a in cands if (a, to_code) in existing]
                fresh = [a for a in cands if (a, to_code) not in existing]
                if not fresh:
                    rec["status"] = "already_present"
                    rec["resolved_from"] = dup
                    rec["note"] = _join(rec["note"], "싱크→to 엣지가 정본에 이미 있음")
                else:
                    accepted: list[str] = []
                    conflicts: list[str] = []
                    for a in fresh:
                        if a in _reachable(to_code, combined_succ):
                            conflicts.append(a)
                        else:
                            accepted.append(a)
                    if accepted:
                        rec["status"] = "resolved"
                        rec["resolved_from"] = accepted
                        if level == UNIT_LEVEL:
                            rec["note"] = _join(
                                rec["note"], "단원수준 — 단원 산하 원자 전체의 싱크(저신뢰)"
                            )
                        if dup:
                            rec["note"] = (rec["note"] + " · " if rec["note"] else "") + (
                                f"싱크 {len(dup)}건은 이미 정본에 있음"
                            )
                        if conflicts:
                            rec["note"] = (rec["note"] + " · " if rec["note"] else "") + (
                                f"싱크 {len(conflicts)}건은 순환이라 제외"
                            )
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
                                    "level_pair": (
                                        f"{nodes[a]['school_level']}→{to_node['school_level']}"
                                    ),
                                    "unit_level_source": level == UNIT_LEVEL,
                                    "narrative_indices": [],
                                }
                                proposed[key] = entry
                                combined_succ.setdefault(a, set()).add(to_code)
                            entry["narrative_indices"].append(idx)
                    else:
                        rec["status"] = "cycle_conflict"
                        rec["resolved_from"] = conflicts
                        rec["note"] = _join(
                            rec["note"],
                            "싱크→to를 넣으면 순환 — to가 이미 그 싱크의 조상(서술이 역방향이거나 "
                            "싱크가 to보다 뒤) · 저작 판단",
                        )
        counts[rec["status"]] += 1
        records.append(rec)

    edges = [proposed[k] for k in sorted(proposed)]
    pair_counts: dict[str, int] = defaultdict(int)
    for e in edges:
        pair_counts[str(e["level_pair"])] += 1
    meta = {
        "task": TASK_ID,
        "rule": RULE_ID,
        "status": STATUS_PROPOSAL,
        "source_graph_sha256": source_sha256,
        "narrative_total": len(records),
        "status_counts": dict(sorted(counts.items())),
        "proposed_edge_count": len(edges),
        "proposed_level_pairs": dict(sorted(pair_counts.items())),
        "proposed_unit_level_count": sum(1 for e in edges if e["unit_level_source"]),
        "note": (
            "정본 미반영 제안. 해소 규칙·수치·검토 결과는 "
            "docs/data/narrative_edge_resolution_v1.md. "
            "proposed_edges의 level_pair·unit_level_source·narrative_indices는 원장 전용 필드라 "
            "정본 엣지(AtomEdge)로 옮길 때 제외한다."
        ),
    }
    return {"_meta": meta, "records": records, "proposed_edges": edges}


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
        f"서술형 {meta['narrative_total']}건 → 제안 엣지 {meta['proposed_edge_count']}건 "
        f"(상태 {meta['status_counts']} · 학교급 쌍 {meta['proposed_level_pairs']})"
    )
    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current == text:
            print(f"일치: {OUTPUT_PATH} · {summary}")
            return 0
        print(
            f"차이 있음: {OUTPUT_PATH} (현재 sha {_sha256_text(current)[:12]} ≠ "
            f"재생성 {_sha256_text(text)[:12]})"
        )
        return 1
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(f"기록: {OUTPUT_PATH} · {summary}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    raise SystemExit(main())
