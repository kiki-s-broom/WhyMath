"""concept→skill 크로스워크 거버넌스 — 리치 Part 2 Phase 2b-1.

정본 개념 코퍼스(`concept_graph_v1/graph.json`)의 `behavior_skills` 참조가 정본 스킬 코퍼스
(`skill_graph_v1/skills.jsonl`)의 skill_id에 **전부 존재**(dangling 0)함을 동결한다. 두 코퍼스가
독립 저작이라 한쪽만 바뀌면 dangling이 생길 수 있으므로, 이 크로스워크 동결이 그 드리프트를
코드리뷰로 끌어낸다(프로젝션·mastery 해소가 dangling ref를 만나면 조용히 빠짐).

hermetic: 커밋된 코퍼스 파일만 읽는다(DB·네트워크 불요).
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONCEPT_GRAPH = _REPO_ROOT / "data" / "corpus" / "concept_graph_v1" / "graph.json"
_SKILL_GRAPH = _REPO_ROOT / "data" / "corpus" / "skill_graph_v1" / "skills.jsonl"


def _skill_ids() -> set[str]:
    lines = _SKILL_GRAPH.read_text(encoding="utf-8").splitlines()
    return {json.loads(line)["skill_id"] for line in lines if line.strip()}


def _concepts() -> list[dict]:
    return json.loads(_CONCEPT_GRAPH.read_text(encoding="utf-8"))["concepts"]


def test_behavior_skills_have_no_dangling_refs() -> None:
    """모든 concept.behavior_skills 참조가 skill_graph_v1 skill_id에 존재(dangling 0)."""
    valid = _skill_ids()
    refs: set[str] = set()
    for c in _concepts():
        refs.update(c.get("behavior_skills", []))
    dangling = refs - valid
    assert dangling == set(), f"behavior_skills dangling 참조 — {sorted(dangling)}"


def test_behavior_skills_coverage_threshold() -> None:
    """v1 매핑 커버리지 회귀 방지 — 최소 350/437 개념이 ≥1 스킬 매핑(현 404).

    초등 산술·문화·탐구 등 적합 스킬이 없는 개념은 []가 정직하다(전량 매핑 강요 아님). 이 하한은
    대량 매핑 유실(파이프라인 회귀)을 잡는 안전판이다.
    """
    concepts = _concepts()
    covered = sum(1 for c in concepts if c.get("behavior_skills"))
    assert covered >= 350, f"behavior_skills 커버리지 급감 — {covered}/{len(concepts)}"


def test_all_skills_are_reachable_vocabulary() -> None:
    """매핑이 참조하는 스킬 집합이 스킬 vocabulary의 부분집합이며 다수를 실제 사용한다.

    (일부 스킬은 아직 미참조일 수 있으나) vocabulary 밖 토큰은 없어야 한다(오타·유령 skill 방지).
    """
    valid = _skill_ids()
    used: set[str] = set()
    for c in _concepts():
        used.update(c.get("behavior_skills", []))
    assert used <= valid
    # v1 매핑이 스킬 vocabulary의 상당수를 실제로 사용(사문화 vocabulary 아님).
    assert len(used) >= 20
