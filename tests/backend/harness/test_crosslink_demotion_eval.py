"""crosswalk 강등전 하니스 테스트 — tier별 집계·Wilson·커버리지 회계·CLI(순수·hermetic).

합성 trial로 게이트 판정·집계를 동결하고, 커밋 코퍼스 e2e로 cross 거부율 하한·정답 오거부 0·
커버리지 경계·exit 0를 봉인한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from whymath_backend.harness import crosslink_demotion_eval as ev
from whymath_backend.l4.misconception.crosslink_demotion_seeder import CrosslinkTrial

_KEBAB_STANDARDS = {
    "opposite-root-selected": frozenset({"[10공수1-02-02]"}),
    "extremum-max-min-confused": frozenset({"[12미적Ⅰ-02-07]"}),
}
_MID_STANDARDS: dict[str, str | None] = {
    "M0862": "[10공수1-02-02]",
    "M0864": "[12미적Ⅰ-02-07]",
    "M0500": "[10공수1-01-01]",  # cross for both
}


class TestSummarize:
    def test_tier_counts_and_false_reject(self) -> None:
        trials = [
            CrosslinkTrial("opposite-root-selected", "M0862", "correct", "positive"),
            CrosslinkTrial("opposite-root-selected", "M0500", "wrong", "cross_standard_neg"),
            CrosslinkTrial("opposite-root-selected", "M0864", "wrong", "same_standard_neg"),
        ]
        # M0864 standard [12미적Ⅰ-02-07] not in opposite-root([10공수1-02-02]) → 실제로 cross지만
        # 여기선 tier를 명시 지정해 집계 경로만 검증. gate는 성취기준으로 판정한다.
        report = ev.summarize(trials, _KEBAB_STANDARDS, _MID_STANDARDS)
        assert report.positive_total == 1 and report.positive_false_reject == 0
        assert report.cross_total == 1 and report.cross_detected == 1  # M0500 cross → reject
        # M0864는 opposite-root 성취기준과 다르므로 게이트가 reject → same_detected=1
        assert report.same_total == 1

    def test_coverage_accounting_uses_real_catalog(self) -> None:
        report = ev.summarize([], _KEBAB_STANDARDS, _MID_STANDARDS)
        assert report.kebabs_total == 67  # 실 카탈로그 67종(843 트랜치1~5 + MISC-21 3 포함)
        assert report.kebabs_decidable == 2  # 신호 부여한 2 kebab


class TestHumanRejectRate:
    def test_parses_wrong_labels(self, tmp_path: Path) -> None:
        p = tmp_path / "human.jsonl"
        p.write_text(
            json.dumps({"is_wrong": True, "label": "reject"})
            + "\n"
            + json.dumps({"is_wrong": True, "label": "approve"})
            + "\n"
            + json.dumps({"is_wrong": False, "label": "approve"})
            + "\n",
            encoding="utf-8",
        )
        assert ev._human_reject_rate(p) == 0.5  # 오매핑 2건 중 1건 거부


class TestCliEndToEnd:
    def test_committed_corpora_measure_and_exit_zero(self) -> None:
        # 커밋 코퍼스 e2e — cross 거부율 하한 통과·정답 오거부 0 → exit 0.
        code = ev.main([])
        assert code == 0

    def test_report_shows_honest_boundary(self) -> None:
        report, _ = ev.run(
            problem_corpora=ev._default_problem_corpora(),
            misconceptions=ev._default_misconceptions(),
            cross_per_positive=60,
            same_per_positive=60,
        )
        # cross-standard 전건 거부(구조 신호 정확)·정답 오거부 0.
        assert report.cross_detected == report.cross_total and report.cross_total > 0
        assert report.positive_false_reject == 0
        # same-standard는 못 잡음(false accept·인간 존치)·커버 64/67
        # (843 트랜치1~4 24종 신규 탐지 kebab 포함·전수 machine-decidable). MISC-21 3종
        # (bigger-denominator-bigger-fraction·ratio-order-swapped·
        # addition-multiplication-rule-confused)은 아직 문항 코퍼스에 등장하지 않아
        # kebab_standards가 비어 human-only 3건으로 정직 집계된다(좌석만 생겼을 뿐 문항
        # 연계는 이번 태스크 범위 밖 — MISC-21 acceptance ④).
        assert report.same_detected == 0
        assert report.kebabs_decidable == 64 and report.kebabs_total == 67
        text = ev.format_report(report, confidence=0.95, human_reject_rate=None)
        assert "인간 존치" in text and "machine-decidable" in text
