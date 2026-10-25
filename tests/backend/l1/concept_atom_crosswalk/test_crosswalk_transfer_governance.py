"""437-키 자산 원자 축 이전 *거버넌스* — 실 코퍼스 대조 dangling 0 동결 (S0-2·hermetic·PG 불요).

커밋된 실 코퍼스(크로스워크·구 437·원자 그래프·스킬 그래프·K-12/대학 콘텐츠)로 이전 유도를
실행해 참조 무결성을 동결한다(모든 소스가 repo 커밋 코퍼스라 hermetic — DB·네트워크 불요):

  ① 전파된 behavior_skills ⊆ 스킬 정본 27종(`skill_graph_v1/skills.jsonl`) — dangling 0
  ② 전파 대상 원자 code ⊆ 원자 그래프 세부개념(`atom_graph_v1/graph.json`) — dangling 0
  ③ K-12 콘텐츠 원자 연결 — 437행 전량 커버(키 집합 일치)·atom code dangling 0
  ④ 대학 콘텐츠 code(409)와 유도 키 무교차 — 대학 행 무변경 축 분리
  ⑤ 커버리지 하한 동결 — 스킬 보유 원자 ≥ 1,000(실측 1,211·#419 커버 404/437 반영)

코퍼스가 재유도·재저작되어 수치가 내려가면 여기서 잡는다(드리프트 감지 — 데이터카드 §7 선례).
"""

from __future__ import annotations

import json
from pathlib import Path

from whymath_backend.l1.concept_atom_crosswalk.transfer import (
    derive_atom_behavior_skills,
    derive_k12_content_atom_codes,
    load_behavior_skills_by_src,
    load_concept_src_bridge,
    load_crosswalk_records,
)

# 레포 루트 앵커(tests/backend/l1/concept_atom_crosswalk/ → parents[4]) — CWD 상대 경로는
# CI(cwd=src/backend)에서 깨진다(형제 통합테스트 앵커 선례).
_ROOT = Path(__file__).resolve().parents[4]
_CROSSWALK = _ROOT / "data" / "corpus" / "concept_atom_crosswalk_v1" / "crosswalk.jsonl"
_CONCEPT_GRAPH = _ROOT / "data" / "corpus" / "concept_graph_v1" / "graph.json"
_CONCEPTS_JSONL = _ROOT / "data" / "corpus" / "concept_graph_v1" / "concepts.jsonl"
_ATOM_GRAPH = _ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"
_SKILLS_JSONL = _ROOT / "data" / "corpus" / "skill_graph_v1" / "skills.jsonl"
_K12_CONTENT = _ROOT / "data" / "corpus" / "concept_content_v1" / "content.json"
_UNIV_CONTENT = _ROOT / "data" / "corpus" / "concept_content_university_v1" / "content.json"

# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_FACTS = json.loads((_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8"))


def _derived_atom_skills() -> dict[str, tuple[str, ...]]:
    crosswalk = load_crosswalk_records(_CROSSWALK)
    bridge = load_concept_src_bridge(_CONCEPT_GRAPH)
    skills = load_behavior_skills_by_src(_CONCEPTS_JSONL)
    return derive_atom_behavior_skills(crosswalk, bridge, skills)


def _derived_content_atoms() -> dict[str, tuple[str, ...]]:
    crosswalk = load_crosswalk_records(_CROSSWALK)
    bridge = load_concept_src_bridge(_CONCEPT_GRAPH)
    return derive_k12_content_atom_codes(crosswalk, bridge)


def _skill_universe() -> set[str]:
    rows = [
        json.loads(line)
        for line in _SKILLS_JSONL.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {str(r["skill_id"]) for r in rows}


def _atom_universe() -> set[str]:
    payload = json.loads(_ATOM_GRAPH.read_text(encoding="utf-8"))
    return {str(c["code"]) for c in payload["concepts"] if c.get("level") == "세부개념"}


def test_corpora_exist() -> None:
    """소스 코퍼스 전부 커밋 존재 — 부재 시 조용한 skip 대신 명시 실패(거버넌스는 loud)."""
    for path in (
        _CROSSWALK,
        _CONCEPT_GRAPH,
        _CONCEPTS_JSONL,
        _ATOM_GRAPH,
        _SKILLS_JSONL,
        _K12_CONTENT,
        _UNIV_CONTENT,
    ):
        assert path.exists(), f"코퍼스 부재: {path}"


# ── ① 전파 스킬 ⊆ 27 스킬 정본 (dangling 0) ────────────────────────────────
def test_propagated_skills_subset_of_skill_graph() -> None:
    universe = _skill_universe()
    assert len(universe) == _FACTS["skill_graph.skills"]  # 스킬 정본(#419·skill_graph_v1)
    derived = _derived_atom_skills()
    dangling = {s for skills in derived.values() for s in skills} - universe
    assert dangling == set(), f"스킬 정본에 없는 skill_id 전파(dangling): {sorted(dangling)}"


# ── ② 전파 대상 원자 ⊆ 세부개념 (dangling 0) ────────────────────────────────
def test_propagated_atoms_subset_of_atom_graph_leaf() -> None:
    atoms = _atom_universe()
    derived = _derived_atom_skills()
    dangling = set(derived) - atoms
    assert dangling == set(), f"원자 그래프 세부개념에 없는 code(dangling): {sorted(dangling)}"


# ── ③ K-12 콘텐츠 원자 연결 — 전량 커버·dangling 0 ─────────────────────────
def test_k12_content_fully_covered_and_atoms_valid() -> None:
    payload = json.loads(_K12_CONTENT.read_text(encoding="utf-8"))
    k12_codes = {str(c["code"]) for c in payload["content"]}
    derived = _derived_content_atoms()
    # 키 집합 일치 — K-12 콘텐츠 행 전량이 원자 연결을 받는다(누락 0·잉여 0).
    assert set(derived) == k12_codes
    assert len(derived) == _FACTS["concept_content.k12"]
    atoms = _atom_universe()
    dangling = {a for codes in derived.values() for a in codes} - atoms
    assert dangling == set(), f"세부개념에 없는 atom_codes(dangling): {sorted(dangling)}"
    # 연결은 전부 비어있지 않다(unmapped 0 — 크로스워크 S0-1 실측 동결과 정합).
    assert all(codes for codes in derived.values())


# ── ④ 대학 행 축 분리 — 유도 키와 무교차 ────────────────────────────────────
def test_university_codes_disjoint_from_transfer_keys() -> None:
    payload = json.loads(_UNIV_CONTENT.read_text(encoding="utf-8"))
    univ_codes = {str(c["code"]) for c in payload["content"]}
    assert len(univ_codes) == _FACTS["concept_content.university"]
    derived = _derived_content_atoms()
    # 대학 code(소단원코드)는 유도 키(구 437 개념코드)와 키 공간이 겹치지 않는다 —
    # scope='K-12' SQL 필터에 더해 데이터 축 자체가 분리돼 있음을 동결(이중 방어).
    assert set(derived) & univ_codes == set()


# ── ⑤ 커버리지 하한 동결 ────────────────────────────────────────────────────
def test_skill_coverage_lower_bound() -> None:
    derived = _derived_atom_skills()
    nonempty = sum(1 for skills in derived.values() if skills)
    # 실측(2026-07-03): 전파 대상 원자 1,324 · 스킬 보유 1,211 · 유니크 스킬 27.
    assert len(derived) >= 1_300
    assert nonempty >= 1_000
    unique_skills = {s for skills in derived.values() for s in skills}
    assert len(unique_skills) == _FACTS["skill_graph.skills"]  # 스킬 정본 전부가 최소 한 원자에 닿는다
