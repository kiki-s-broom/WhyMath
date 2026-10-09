"""그래프 분석 CLI + 실 코퍼스 스모크 — ARCH-17 (hermetic·커밋된 코퍼스만·DB 불요).

CLI는 typer CliRunner로 exit code·JSON 산출 계약을, 실 코퍼스 스모크는 커밋된 4파일 위에서
집계가 완주하고 실측 수치(원자 2,683·blocking 344)와 일치하는지 못 박는다(코퍼스 회귀 감지).
"""

from __future__ import annotations

import json
from pathlib import Path

from data_pipeline.graph_analytics.__main__ import app
from data_pipeline.graph_analytics.analytics import build_report
from typer.testing import CliRunner

runner = CliRunner()

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _REPO_ROOT / "data" / "corpus"


def _corpus_args() -> list[str]:
    return [
        "report",
        "--atom-graph",
        str(_CORPUS / "atom_graph_v1" / "graph.json"),
        "--concept-graph",
        str(_CORPUS / "concept_graph_v1" / "graph.json"),
        "--misconceptions",
        str(_CORPUS / "misconceptions_v1" / "misconceptions.json"),
        "--crosswalk",
        str(_CORPUS / "concept_atom_crosswalk_v1" / "crosswalk.jsonl"),
    ]


class TestCli:
    def test_missing_file_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["report", "--atom-graph", str(tmp_path / "없음.json")])
        assert result.exit_code == 2

    def test_report_on_real_corpus_with_json(self, tmp_path: Path) -> None:
        """실 코퍼스 완주 — exit 0·경계 문구·JSON 계약(허브·전파·skip 전량)."""
        out = tmp_path / "report.json"
        result = runner.invoke(app, [*_corpus_args(), "--top-n", "5", "--json", str(out)])
        assert result.exit_code == 0, result.output
        assert "preload 투입 금지" in result.output
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["cycle"] is None
        assert payload["atom_count"] == len(payload["hubs"])
        assert payload["misconception_impacts"], "blocking 전파 결과가 비어 있으면 조인 회귀"
        top = payload["misconception_impacts"][0]
        assert top["blocked_downstream_count"] >= 1


class TestRealCorpusSmoke:
    def test_measured_invariants(self) -> None:
        """실측 고정치 — 원자 1,823(세부개념만·전체 노드 2,683)·blocking 344·해석 skip 0·DAG 유지.

        이 수치는 2026-07-27 실측(갭 설계 세션)의 동결이다 — 코퍼스가 바뀌면 의도된 변경인지
        확인하고 함께 갱신한다(스냅샷 회귀 감지·`test_node_granularity_governance` 선례).
        """
        report = build_report(
            atom_graph=_CORPUS / "atom_graph_v1" / "graph.json",
            concept_graph=_CORPUS / "concept_graph_v1" / "graph.json",
            misconceptions=_CORPUS / "misconceptions_v1" / "misconceptions.json",
            crosswalk=_CORPUS / "concept_atom_crosswalk_v1" / "crosswalk.jsonl",
        )
        assert report.atom_count == 1823  # 세부개념만(단원·소단원 제외 — 엣지 우주)
        assert report.edge_count == 2234  # 2210 + S4-60 고→대 경계 24(신규 엣지는 blocking 무관)
        assert report.blocking_total == 344
        assert report.success and report.cycle is None
        # concept_src_id 843/843 해석 가능 실측의 blocking 부분집합 — 조인 실패 0.
        assert report.skipped == []
        assert len(report.impacts) == 344
        # 랭킹 결정론: blocked desc → mis_id asc.
        counts = [i.blocked_downstream_count for i in report.impacts]
        assert counts == sorted(counts, reverse=True)
