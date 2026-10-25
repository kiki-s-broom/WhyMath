"""concept_atom_crosswalk 실코퍼스 거버넌스 — 커밋된 crosswalk.jsonl 동결.

정본 크로스워크(`concept_atom_crosswalk_v1/crosswalk.jsonl`)가 양측 정본 코퍼스
(구 437 `concept_graph_v1/graph.json` · 신 원자 `atom_graph_v1/graph.json`)와 정합함을 동결한다.
세 코퍼스 중 하나만 바뀌어도 dangling·누락이 생길 수 있으므로, 이 동결이 그 드리프트를
코드리뷰로 끌어낸다(test_concept_skill_crosswalk.py 선례 미러).

hermetic: 커밋된 코퍼스 파일만 읽는다(DB·네트워크·openpyxl/neo4j 불요).
"""

from __future__ import annotations

import json
from pathlib import Path

from data_pipeline.concept_atom_crosswalk.models import CrosswalkEntry
from data_pipeline.concept_atom_crosswalk.validate import validate_crosswalk

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CROSSWALK = _REPO_ROOT / "data" / "corpus" / "concept_atom_crosswalk_v1" / "crosswalk.jsonl"
_PROVENANCE = _REPO_ROOT / "data" / "corpus" / "concept_atom_crosswalk_v1" / "_provenance.json"
_CONCEPT_GRAPH = _REPO_ROOT / "data" / "corpus" / "concept_graph_v1" / "graph.json"
_ATOM_GRAPH = _REPO_ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"

# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)

# 커버리지 하한 — #419 behavior_skills 선례(350/437) 수준. 실측 437/437(2026-07-03 유도)이나,
# 소스 코퍼스 변경 시 재유도로 다소 줄 수 있어 하한은 350으로 동결(대량 유실 회귀 안전판).
_MIN_MAPPED = 350


def _entries() -> list[CrosswalkEntry]:
    lines = _CROSSWALK.read_text(encoding="utf-8").splitlines()
    return [CrosswalkEntry.model_validate(json.loads(line)) for line in lines if line.strip()]


def _concept_ids() -> set[str]:
    payload = json.loads(_CONCEPT_GRAPH.read_text(encoding="utf-8"))
    return {str(node["concept_id"]) for node in payload["concepts"]}


def _atom_codes() -> set[str]:
    payload = json.loads(_ATOM_GRAPH.read_text(encoding="utf-8"))
    return {str(node["code"]) for node in payload["concepts"] if node.get("level") == "세부개념"}


def test_full_rows_and_sorted() -> None:
    """전량(구 그래프 개념 수와 동일) + concept_id 사전순·중복 0.

    기대 행 수는 사실 파일에서 읽는다 — 값이 바뀌면 그 파일의 diff가 의식적 리뷰 지점이다.
    """
    entries = _entries()
    concept_ids = _concept_ids()
    assert len(entries) == len(concept_ids) == _FACTS["concept_atom_crosswalk.entries"]
    ids = [e.concept_id for e in entries]
    assert ids == sorted(ids), "crosswalk.jsonl은 concept_id 사전순이어야 함"
    assert len(set(ids)) == len(ids), "concept_id 중복"


def test_validate_green_against_both_corpora() -> None:
    """양측 코퍼스에 대한 전체 검증 green — dangling 0·전량 존재·primary 유일."""
    report = validate_crosswalk(_entries(), concept_ids=_concept_ids(), atom_codes=_atom_codes())
    assert report.success, report.report_text()


def test_mapped_coverage_threshold() -> None:
    """커버리지 하한 — 매핑 ≥ 350/437(실측 437·대량 유실 회귀 안전판)."""
    entries = _entries()
    mapped = sum(1 for e in entries if e.match_method != "unmapped")
    assert mapped >= _MIN_MAPPED, f"매핑 커버리지 급감 — {mapped}/{len(entries)}"


def test_all_rows_ai_estimated() -> None:
    """전량 review_status='ai_estimated'(프로그램적 유도·사람 검수 전 정직 표기)."""
    assert all(e.review_status == "ai_estimated" for e in _entries())


def test_provenance_records_sources_and_counts() -> None:
    """_provenance.json — 소스 두 코퍼스 경로·sha256과 커버리지 카운트 기록."""
    payload = json.loads(_PROVENANCE.read_text(encoding="utf-8"))
    sources = payload["sources"]
    assert "concept_graph" in sources and "atom_graph" in sources
    for meta in sources.values():
        assert len(meta["sha256"]) == 64
    counts = payload["counts"]
    assert (
        counts["entries"]
        == counts["mapped"] + counts["unmapped"]
        == _FACTS["concept_atom_crosswalk.entries"]
    )
