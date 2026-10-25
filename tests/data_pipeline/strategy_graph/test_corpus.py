"""strategy_graph 실 코퍼스 검증 — 커밋된 `strategies.jsonl`·`graph.json` 무결성.

hermetic: 커밋된 코퍼스 파일만 읽는다(DB·네트워크 불요). CI가 코퍼스 회귀를 잡는다.
"""

from __future__ import annotations

import json
from pathlib import Path

from data_pipeline.strategy_graph.models import StrategyNode
from data_pipeline.strategy_graph.transform import transform_strategies
from data_pipeline.strategy_graph.validate import validate_strategies

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _REPO_ROOT / "data" / "corpus" / "strategy_graph_v1"

# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
# 고정 지점이 사실 파일 한 곳이다 — 값이 바뀌면 그 파일의 diff가 의식적 리뷰 지점이다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_strategies_jsonl_transforms_clean() -> None:
    """실 strategies.jsonl → 정형화 skip 0(전 행 유효·정확히 8)."""
    records = _read_jsonl(_CORPUS / "strategies.jsonl")
    result = transform_strategies(records)
    assert result.skipped == []
    assert len(result.strategies) == _FACTS["strategy_graph.strategies"]
    assert len(result.strategies) == len(records)


def test_corpus_validates_pass() -> None:
    """실 코퍼스 그래프 검증 PASS(정확히 8·slug 집합 일치·error 0)."""
    result = transform_strategies(_read_jsonl(_CORPUS / "strategies.jsonl"))
    report = validate_strategies(result.strategies)
    assert report.success, report.report_text()
    assert report.errors == []


def test_graph_json_matches_source() -> None:
    """커밋된 graph.json이 strategies.jsonl 재정형화 산출과 일치(결정성·정합)."""
    result = transform_strategies(_read_jsonl(_CORPUS / "strategies.jsonl"))
    graph = json.loads((_CORPUS / "graph.json").read_text(encoding="utf-8"))
    committed = [StrategyNode(**r) for r in graph["strategies"]]
    assert [s.model_dump() for s in committed] == [s.model_dump() for s in result.strategies]


def test_graph_json_has_no_edge_keys() -> None:
    """graph.json에 엣지 배열·노드 내 관계 키 없음(closed canonical·연결은 참조 키·Phase 6b)."""
    graph = json.loads((_CORPUS / "graph.json").read_text(encoding="utf-8"))
    assert "edges" not in graph  # 연결은 참조 키·별도 엣지 배열 없음
    assert len(graph["strategies"]) == _FACTS["strategy_graph.strategies"]
    for node in graph["strategies"]:
        assert node["description"]  # 필수 설명 존재
        for forbidden in ("edges", "prerequisites", "related", "prompt"):
            assert forbidden not in node
