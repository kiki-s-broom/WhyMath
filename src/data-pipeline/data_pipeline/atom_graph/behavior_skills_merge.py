"""원자 백본 `behavior_skills` 병합 — 커밋된 graph.json 후처리 (SKB-02).

배경(SKB-01 게이트 점검 중 발견): 원자 백본 corpus(`data/corpus/atom_graph_v1/graph.json`·
2,683 concepts — `concept` 테이블 런타임 정본)에는 `behavior_skills` 필드가 전무했다. 반면
구 437 코퍼스(`data/corpus/concept_graph_v1/concepts.jsonl`)에는 #419가 저작한 concept→skill
매핑이 404/437건 실려 있다. 원자 백본 원본 xlsx(`원자_통합마스터`)는 휘발돼 transform-v1
재실행이 불가하므로(`university_standard_fill.py`의 U2와 동형 제약), 이 모듈은 **커밋된**
`graph.json`을 후처리해 behavior_skills를 병합한다(handoff §6 허용 경로 — U2 미러).

────────────────────────────────────────────────────────────────────────────
전파 규칙 — S0-2(`whymath_backend.l1.concept_atom_crosswalk.transfer`)와 동일 의미론
────────────────────────────────────────────────────────────────────────────
각 크로스워크 행의 **atom_codes 전체**(primary만 아님)에 해당 concept의 behavior_skills를
전파한다. 한 원자에 복수 concept이 닿으면 **union + dedup + 사전순 정렬**. 스킬(인지 행동)은
개념의 *구성 원자 전체*에 적용되는 속성이지 배타 귀속이 아니다(S0-2 근거 미러).
`unmapped`(atom_codes 빈) 크로스워크 행은 강제 귀속 없이 skip한다(조용히 넘기지 않음 — skip
건수는 `BehaviorSkillsMergeResult.unmapped_crosswalk_rows`로 보고).

────────────────────────────────────────────────────────────────────────────
레이어 경계(CLAUDE.md L_n은 L_{n+1}을 알지 못한다 — data-pipeline은 backend 미import)
────────────────────────────────────────────────────────────────────────────
`whymath_backend.l1.concept_atom_crosswalk.transfer`의 4개 순수 함수(로딩·유도 로직)를 이
모듈이 **재구현**한다(직접 import 금지 — data-pipeline은 빌드타임 자산, backend는 런타임
자산이라 방향이 반대). 이 모듈은 DB에 쓰지 않는다 — corpus 산출물(graph.json)만 재생성한다.

────────────────────────────────────────────────────────────────────────────
조인 축 (transfer.py 미러)
────────────────────────────────────────────────────────────────────────────
크로스워크 키는 canonical `concept_id`인데, behavior_skills 저작 좌석(concepts.jsonl)의 키는
원천 `src_id` 축이다. `concept_graph_v1/graph.json`의 `concept_id`↔`source_id`(=`src_id`)로
다리를 놓는다. 조인 실패는 즉시 오류(조용히 빠뜨리지 않음).

정본: `docs/data/atom_graph_v1.md` §2.4 · 백로그 `SKB-02-atom-graph-behavior-skills-merge`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_GRAPH = Path("data/corpus/atom_graph_v1/graph.json")
_DEFAULT_CROSSWALK = Path("data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl")
_DEFAULT_LEGACY_GRAPH = Path("data/corpus/concept_graph_v1/graph.json")
_DEFAULT_LEGACY_CONCEPTS = Path("data/corpus/concept_graph_v1/concepts.jsonl")


@dataclass(frozen=True, slots=True)
class CrosswalkRecord:
    """크로스워크 1행 — 병합에 필요한 최소 필드만(`transfer.CrosswalkRecord` 미러)."""

    concept_id: str
    atom_codes: tuple[str, ...]


def load_crosswalk_records(path: Path) -> list[CrosswalkRecord]:
    """크로스워크 코퍼스 crosswalk.jsonl → 레코드 목록(concept_id 유일성 검증).

    Raises:
        FileNotFoundError: crosswalk.jsonl 부재.
        ValueError: concept_id 누락/중복(코퍼스 계약 위반 — 조용히 넘기지 않음).
    """
    records: list[CrosswalkRecord] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        concept_id = str(row.get("concept_id") or "").strip()
        if not concept_id:
            raise ValueError(f"crosswalk 행에 concept_id 없음: {row!r}")
        if concept_id in seen:
            raise ValueError(f"crosswalk concept_id 중복: {concept_id!r}")
        seen.add(concept_id)
        raw_codes = row.get("atom_codes")
        codes = tuple(str(c) for c in raw_codes) if isinstance(raw_codes, (list, tuple)) else ()
        records.append(CrosswalkRecord(concept_id=concept_id, atom_codes=codes))
    return records


def load_concept_src_bridge(graph_path: Path) -> dict[str, str]:
    """구 437 코퍼스 graph.json → `concept_id`(canonical) → `source_id`(src_id) 다리.

    Raises:
        FileNotFoundError: graph.json 부재.
        ValueError: concept_id/source_id 누락 또는 concept_id 중복(조인 실패 — 즉시 오류).
    """
    payload = json.loads(graph_path.read_text(encoding="utf-8"))
    bridge: dict[str, str] = {}
    for node in payload.get("concepts", []):
        concept_id = str(node.get("concept_id") or "").strip()
        src_id = str(node.get("source_id") or "").strip()
        if not concept_id or not src_id:
            raise ValueError(f"graph.json 개념 노드에 concept_id/source_id 없음: {node!r}")
        if concept_id in bridge:
            raise ValueError(f"graph.json concept_id 중복: {concept_id!r}")
        bridge[concept_id] = src_id
    return bridge


def load_behavior_skills_by_src(concepts_jsonl_path: Path) -> dict[str, tuple[str, ...]]:
    """#419 저작 좌석 concepts.jsonl → `src_id` → behavior_skills(dedup·사전순).

    Raises:
        FileNotFoundError: concepts.jsonl 부재.
        ValueError: src_id 누락/중복(코퍼스 계약 위반).
    """
    skills_by_src: dict[str, tuple[str, ...]] = {}
    for line in concepts_jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        src_id = str(row.get("src_id") or "").strip()
        if not src_id:
            raise ValueError(f"concepts.jsonl 행에 src_id 없음: {row!r}")
        if src_id in skills_by_src:
            raise ValueError(f"concepts.jsonl src_id 중복: {src_id!r}")
        raw_skills = row.get("behavior_skills")
        skills = (
            tuple(sorted({str(s) for s in raw_skills}))
            if isinstance(raw_skills, (list, tuple))
            else ()
        )
        skills_by_src[src_id] = skills
    return skills_by_src


def derive_atom_behavior_skills(
    crosswalk: list[CrosswalkRecord],
    concept_src_bridge: Mapping[str, str],
    skills_by_src: Mapping[str, tuple[str, ...]],
) -> tuple[dict[str, tuple[str, ...]], int]:
    """전파 규칙 본체 — 원자 code → behavior_skills(union+dedup·사전순) 유도.

    각 크로스워크 행의 **atom_codes 전체**에 concept의 behavior_skills를 전파한다(모듈
    docstring 참조). 한 원자에 복수 concept이 닿으면 union+dedup, 결과는 사전순 정렬(결정론).
    `unmapped`(atom_codes 빈) 행은 skip한다(강제 귀속 금지). 반환 = (원자→skills 매핑, skip 건수).

    Raises:
        ValueError: 크로스워크 concept_id가 다리/저작 좌석에 없음(코퍼스 조인 실패).
    """
    acc: dict[str, set[str]] = {}
    skipped = 0
    for record in crosswalk:
        if not record.atom_codes:  # unmapped — 강제 귀속 금지
            skipped += 1
            continue
        src_id = concept_src_bridge.get(record.concept_id)
        if src_id is None:
            raise ValueError(f"크로스워크 concept_id가 graph.json에 없음: {record.concept_id!r}")
        if src_id not in skills_by_src:
            raise ValueError(f"concepts.jsonl에 src_id {src_id!r} 없음 — 코퍼스 조인 실패")
        skills = skills_by_src[src_id]
        for atom_code in record.atom_codes:
            acc.setdefault(atom_code, set()).update(skills)
    return {atom: tuple(sorted(skills)) for atom, skills in acc.items()}, skipped


@dataclass(frozen=True, slots=True)
class BehaviorSkillsMergeReport:
    """graph.json 병합 결과 — 운영 가시성(CLAUDE.md "작동한 비율" 원칙)."""

    total_concepts: int
    atoms_mapped: int
    """매핑에 존재하는 원자 수(크로스워크가 atom_codes로 닿은 원자 — 스킬이 빈 것도 포함)."""
    atoms_nonempty: int
    """behavior_skills가 비어있지 않게 채워진 원자 수(stdout 보고 대상)."""


def merge_behavior_skills_into_graph(
    graph: MutableMapping[str, Any], mapping: Mapping[str, tuple[str, ...]]
) -> BehaviorSkillsMergeReport:
    """graph['concepts'] 전체에 `behavior_skills` 키를 명시적으로 채운다(in-place·멱등).

    매핑에 code가 있는 노드(크로스워크가 닿은 원자)는 병합값(이미 사전순 — 재정렬하지 않음),
    그 외(단원·소단원·비크로스워크 원자)는 빈 리스트로 명시 — 일관성을 위해 키를 항상 채운다.
    재실행해도 같은 매핑이면 byte 동일(determinism·`university_standard_fill` 패턴 미러).
    """
    total = 0
    mapped = 0
    nonempty = 0
    for node in graph.get("concepts", []):
        total += 1
        code = str(node.get("code") or "")
        skills = mapping.get(code)
        if skills is not None:
            mapped += 1
            if skills:
                nonempty += 1
            node["behavior_skills"] = list(skills)
        else:
            node["behavior_skills"] = []
    return BehaviorSkillsMergeReport(
        total_concepts=total, atoms_mapped=mapped, atoms_nonempty=nonempty
    )


@dataclass(frozen=True, slots=True)
class BehaviorSkillsMergeResult:
    """CLI/오케스트레이션 최상위 결과 — graph 병합 리포트 + 크로스워크 소비 통계."""

    graph_report: BehaviorSkillsMergeReport
    crosswalk_rows: int
    unmapped_crosswalk_rows: int


def run_behavior_skills_merge(
    graph: MutableMapping[str, Any],
    *,
    crosswalk_path: Path = _DEFAULT_CROSSWALK,
    legacy_graph_path: Path = _DEFAULT_LEGACY_GRAPH,
    legacy_concepts_path: Path = _DEFAULT_LEGACY_CONCEPTS,
) -> BehaviorSkillsMergeResult:
    """크로스워크·구 코퍼스를 읽어 유도한 매핑을 `graph`(in-place)에 병합(오케스트레이션).

    로딩 3종(`load_crosswalk_records`·`load_concept_src_bridge`·`load_behavior_skills_by_src`)
    → 유도(`derive_atom_behavior_skills`) → 병합(`merge_behavior_skills_into_graph`) 순서.
    파일 부재는 `FileNotFoundError`, 코퍼스 조인 실패는 `ValueError`로 그대로 전파한다
    (조용히 넘기지 않음 — 호출자가 exit code로 반영).
    """
    crosswalk = load_crosswalk_records(crosswalk_path)
    bridge = load_concept_src_bridge(legacy_graph_path)
    skills_by_src = load_behavior_skills_by_src(legacy_concepts_path)
    mapping, skipped = derive_atom_behavior_skills(crosswalk, bridge, skills_by_src)
    graph_report = merge_behavior_skills_into_graph(graph, mapping)
    return BehaviorSkillsMergeResult(
        graph_report=graph_report,
        crosswalk_rows=len(crosswalk),
        unmapped_crosswalk_rows=skipped,
    )


def append_provenance(
    provenance_path: Path,
    result: BehaviorSkillsMergeResult,
    *,
    crosswalk_path: Path,
    now: datetime | None = None,
) -> None:
    """`_provenance.json`에 `behavior_skills_merge` 블록을 갱신(있으면 덮어씀 — 멱등).

    기존 `post_extraction`/`post_transform_migrations` 리스트 컨벤션(U2·dedup 병합 선례)에
    맞춰 한 줄 노트도 함께 append한다(중복 노트는 재추가하지 않음). provenance 파일 부재는
    조용히 넘긴다(코퍼스가 아직 없는 테스트 환경 — `university_standard_fill._append_provenance`
    미러).
    """
    if not provenance_path.exists():
        return
    prov: dict[str, Any] = json.loads(provenance_path.read_text(encoding="utf-8"))
    executed_at = (now or datetime.now(tz=timezone.utc)).isoformat()
    prov["behavior_skills_merge"] = {
        "executed_at": executed_at,
        "crosswalk_path": str(crosswalk_path),
        "crosswalk_rows": result.crosswalk_rows,
        "unmapped_crosswalk_rows": result.unmapped_crosswalk_rows,
        "atoms_mapped": result.graph_report.atoms_mapped,
        "atoms_nonempty": result.graph_report.atoms_nonempty,
        "source": "SKB-02 — crosswalk_v1 경유 concept_graph_v1(구 437) behavior_skills 병합",
    }
    note = (
        f"[SKB-02 {executed_at[:10]}] behavior_skills 병합 — 크로스워크 {result.crosswalk_rows}행"
        f"(skip {result.unmapped_crosswalk_rows}) 경유 원자 {result.graph_report.atoms_mapped}건에 "
        f"전파(비어있지 않음 {result.graph_report.atoms_nonempty}건). 구 437 코퍼스 "
        "concepts.jsonl이 저작 정본."
    )
    post = prov.setdefault("post_transform_migrations", [])
    if isinstance(post, list) and not any(
        isinstance(item, dict) and item.get("id") == "behavior_skills_merge_v1" for item in post
    ):
        post.append({"id": "behavior_skills_merge_v1", "summary": note})
    text = json.dumps(prov, ensure_ascii=False, indent=2) + "\n"
    provenance_path.write_text(text, encoding="utf-8")


__all__ = [
    "BehaviorSkillsMergeReport",
    "BehaviorSkillsMergeResult",
    "CrosswalkRecord",
    "append_provenance",
    "derive_atom_behavior_skills",
    "load_behavior_skills_by_src",
    "load_concept_src_bridge",
    "load_crosswalk_records",
    "merge_behavior_skills_into_graph",
    "run_behavior_skills_merge",
]
