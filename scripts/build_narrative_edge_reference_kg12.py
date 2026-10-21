#!/usr/bin/env python3
"""KG-12 ② — 낱말 매칭 참고 원장 v1에 **체계적 오류 가드 4종**을 얹은 v2 원장(결정론·정본 무수정).

입력: `narrative_edge_reference_ledger_v1.json`(KG-11 · 검수 행 번호 E001~E183의 정본이라 바꾸지
      않는다), `graph.json`, `inter_course_edges_university_v1.json`(과정 간 선수 방향의 원장).
산출: `narrative_edge_reference_ledger_v2.json` — v1의 proposed_edges 전건에 `guards`(걸린 가드
      목록)와 `scope_v2`를 붙인다.
      스테이징 v2 = v1 `uni_staging` 가운데 가드에 하나도 걸리지 않은 것.

가드 4종 — KG-11 AI 2인 블라인드 검수의 반려 183행 실측(docs/data/narrative_edge_reference_v1.md §5·
KG-12 문서 §2)에서 반려 정밀도가 높은 특징만 골랐다(사전 고정 · 결과를 보고 재조정하지 않는다):
  homonym_cross_course   과정이 다르고 낱말이 동음이의 사전(합동·연결·증명·기저·평면·완전성·기호·
                         특이점·분리 — 검수자 지목) 안 → 실측 27건 중 반려 26
  in_course_twin         과정이 다르고 **도착 과정 안**에 같은 낱말을 이름에 가진 다른 원자가 있다
                         (더 직접적인 선수가 과정 안에 있다) → 실측 27건 중 반려 23 ·
                         `twin_candidates`에 그 원자를 적는다
  course_direction       과정이 다르고 과정 DAG(과정 간 원장 + 정본 과정 간 엣지)에서 출발 과정이
                         도착 과정의 상류가 아니다(역방향 또는 무관) → 실측 37건 중 반려 24
  short_word             과정이 다르고 낱말이 2자 이하(어느 원자 이름에나 걸리는 일반어 — '원자
                         부재로 강제 해소'의 기계적 징후) → 실측 53건 중 반려 38

사용: python3 scripts/build_narrative_edge_reference_kg12.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Final

_REPO: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src" / "data-pipeline"))

from data_pipeline.atom_graph.graph_history import graph_at_sha  # noqa: E402

_CORPUS: Final[Path] = _REPO / "data" / "corpus" / "atom_graph_v1"
GRAPH_PATH: Final[Path] = _CORPUS / "graph.json"
V1_PATH: Final[Path] = _CORPUS / "narrative_edge_reference_ledger_v1.json"
INTER_COURSE_PATH: Final[Path] = _CORPUS / "inter_course_edges_university_v1.json"
OUTPUT_PATH: Final[Path] = _CORPUS / "narrative_edge_reference_ledger_v2.json"

TASK_ID: Final[str] = "KG-12-university-chain-repair-and-word-match-guards"
RULE_ID: Final[str] = "word_match_v1 + guards_v1"
HOMONYMS: Final[frozenset[str]] = frozenset(
    {"합동", "연결", "증명", "기저", "평면", "완전성", "기호", "특이점", "분리"}
)
SHORT_WORD_MAX: Final[int] = 2
GUARD_NAMES: Final[tuple[str, ...]] = (
    "homonym_cross_course",
    "in_course_twin",
    "course_direction",
    "short_word",
)
_NORM_RE: Final[re.Pattern[str]] = re.compile(r"[\s·,\.\(\)（）]")


def normalize(text: str | None) -> str:
    return _NORM_RE.sub("", text or "")


def course_of(code: str) -> str:
    return code.split("-", 1)[0]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_course_dag(graph: dict[str, Any], inter_course: dict[str, Any]) -> dict[str, set[str]]:
    """과정 → 하류 과정 집합(과정 간 원장 + 정본의 대학 과정 간 엣지)."""
    nodes = {c["code"]: c for c in graph["concepts"]}
    succ: dict[str, set[str]] = defaultdict(set)
    for e in inter_course.get("edges", []):
        a, b = course_of(e["from_code"]), course_of(e["to_code"])
        if a != b:
            succ[a].add(b)
    for e in graph["edges"]:
        f, t = nodes.get(e["from_code"]), nodes.get(e["to_code"])
        if f is None or t is None or f["school_level"] != "대학" or t["school_level"] != "대학":
            continue
        a, b = course_of(e["from_code"]), course_of(e["to_code"])
        if a != b:
            succ[a].add(b)
    return succ


def _reach(start: str, succ: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        x = stack.pop()
        for y in succ.get(x, ()):
            if y not in seen:
                seen.add(y)
                stack.append(y)
    return seen


def build_payload(
    graph: dict[str, Any], v1: dict[str, Any], inter_course: dict[str, Any], v1_sha: str
) -> dict[str, Any]:
    nodes = {c["code"]: c for c in graph["concepts"]}
    course_succ = build_course_dag(graph, inter_course)
    atoms_by_course: dict[str, list[str]] = defaultdict(list)
    for c in graph["concepts"]:
        if c["level"] == "세부개념" and c["school_level"] == "대학":
            atoms_by_course[course_of(c["code"])].append(c["code"])
    records = v1["records"]
    edges_out: list[dict[str, Any]] = []
    guard_counts: dict[str, int] = {g: 0 for g in GUARD_NAMES}
    scope_counts: dict[str, int] = defaultdict(int)
    for e in v1["proposed_edges"]:
        f, t = e["from_code"], e["to_code"]
        cf, ct = course_of(f), course_of(t)
        words = {normalize(records[i]["word"]) for i in e["narrative_indices"]}
        guards: list[str] = []
        twin: list[str] = []
        if cf != ct and nodes[f]["school_level"] == "대학" and nodes[t]["school_level"] == "대학":
            if words & HOMONYMS:
                guards.append("homonym_cross_course")
            twin = sorted(
                a
                for a in atoms_by_course[ct]
                if a != t and any(w and w in normalize(nodes[a]["name"]) for w in words)
            )
            if twin:
                guards.append("in_course_twin")
            upstream = ct in _reach(cf, course_succ) and cf not in _reach(ct, course_succ)
            if not upstream:
                guards.append("course_direction")
            if min(len(w) for w in words) <= SHORT_WORD_MAX:
                guards.append("short_word")
        for g in guards:
            guard_counts[g] += 1
        scope_v2 = e["scope"]
        if e["scope"] == "uni_staging" and guards:
            scope_v2 = "uni_guard_hold"
        scope_counts[scope_v2] += 1
        out = dict(e)
        out["guards"] = guards
        out["twin_candidates"] = twin
        out["scope_v2"] = scope_v2
        edges_out.append(out)
    meta = {
        "task": TASK_ID,
        "rule": RULE_ID,
        "status": (
            "reference v2 — 비-traversal · 정본 미병합 · 가드 4종 적용. 승격 경로는 "
            "docs/data/narrative_edge_reference_v2.md §3(3인째 검수 + Wilson 0.80)"
        ),
        "source_graph_sha256": v1["_meta"]["source_graph_sha256"],
        "source_v1_sha256": v1_sha,
        "homonyms": sorted(HOMONYMS),
        "short_word_max": SHORT_WORD_MAX,
        "course_dag_edge_count": sum(len(v) for v in course_succ.values()),
        "proposed_edge_count": len(edges_out),
        "guard_counts": guard_counts,
        "scope_v2_counts": dict(sorted(scope_counts.items())),
        "uni_staging_v1": sum(1 for e in edges_out if e["scope"] == "uni_staging"),
        "uni_staging_v2": scope_counts.get("uni_staging", 0),
        "note": (
            "v1 원장(KG-11 검수 행 번호의 정본)은 바꾸지 않는다. 이 파일은 v1 proposed_edges "
            "전건에 "
            "guards·twin_candidates·scope_v2를 붙인 주석본이다."
        ),
    }
    return {"_meta": meta, "proposed_edges": edges_out}


def load_bound_graph(v1_source_sha256: str) -> dict[str, Any]:
    """v1 원장이 묶인 정본(KG-11 검수 시점)을 현재 파일에서 복원한다 — v2는 v1의 주석본이라 같은
    정본에 묶인다(정본이 바뀌어도 행 번호 E001~E183이 흔들리지 않는다)."""
    return graph_at_sha(GRAPH_PATH, v1_source_sha256)


def serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    v1_meta_sha = json.loads(V1_PATH.read_text(encoding="utf-8"))["_meta"]["source_graph_sha256"]
    graph = load_bound_graph(v1_meta_sha)
    v1 = json.loads(V1_PATH.read_text(encoding="utf-8"))
    ic = json.loads(INTER_COURSE_PATH.read_text(encoding="utf-8"))
    text = serialize(build_payload(graph, v1, ic, file_sha256(V1_PATH)))
    m = json.loads(text)["_meta"]
    summary = (
        f"가드 {m['guard_counts']} · scope_v2 {m['scope_v2_counts']} · "
        f"스테이징 {m['uni_staging_v1']} → {m['uni_staging_v2']}"
    )
    if args.check:
        cur = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        print(("일치: " if cur == text else "차이 있음: ") + f"{OUTPUT_PATH} · {summary}")
        return 0 if cur == text else 1
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(f"기록: {OUTPUT_PATH} · {summary}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
