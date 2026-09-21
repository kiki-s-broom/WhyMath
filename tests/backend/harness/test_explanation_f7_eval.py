"""explanation_f7_eval(EOS-98 ④ 강등전 CLI) hermetic 상시 회귀 — 라이브 LLM 0.

analogy_fidelity_eval 테스트 선례 미러. 검증 축:
  ① 시험지 결정론(밴드별 그리드 — 고등/대학은 violating 셀 구조적으로 0)
  ② summarize 순수 집계·Wilson 상한 방향
  ③ 본판정: 규칙 검출기에서 미검출·오검출 0 → exit 0
  ④ 변별력: `--control`(널 검출기)이면 violating 전량 미검출이 실측돼 exit 1
  ⑤ `measure_generated_f7_rate` — 실제 생성 배치(ExplanationOutcome)의 F7 발생률 dense 집계
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness.explanation_f7_eval import (
    CaseOutcome,
    CaseSpec,
    _null_checker,
    _real_checker,
    build_exam,
    main,
    measure_generated_f7_rate,
    run_machine,
    summarize,
)
from whymath_backend.l3.pedagogy.explanation_generator import ExplanationOutcome
from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.speech import SpeechGradeBand


class TestExamGrid:
    def test_grid_deterministic(self) -> None:
        exam1 = build_exam(2)
        exam2 = build_exam(2)
        assert exam1 == exam2

    def test_violating_only_for_elementary_and_middle(self) -> None:
        """고등/대학은 `PROFILES`상 전 구조 도입 — violating 셀이 구조적으로 없다(정직 회계)."""
        violating_bands = {c.band for c in build_exam(1) if c.category == "violating"}
        assert violating_bands == {SpeechGradeBand.초등, SpeechGradeBand.중등}

    def test_violating_count_matches_missing_construct_count(self) -> None:
        cases = build_exam(1)
        elementary_violating = [
            c for c in cases if c.band == SpeechGradeBand.초등 and c.category == "violating"
        ]
        middle_violating = [
            c for c in cases if c.band == SpeechGradeBand.중등 and c.category == "violating"
        ]
        assert len(elementary_violating) == 8  # 초등에 미도입된 8개 구조(vocabulary 매핑 기준)
        assert len(middle_violating) == 6  # 중등에 미도입된 6개 구조

    def test_clean_cases_carry_no_forbidden_vocabulary_for_their_band(self) -> None:
        """중등 clean 셀은 root/trig 어휘(제곱근·사인)를 포함하되 미도입 어휘는 없다(경계 스트레스)."""
        forbidden_for_middle = ("로그", "적분", "시그마", "급수", "극한", "미분", "도함수", "조합")
        for spec in build_exam(1):
            if spec.band == SpeechGradeBand.중등 and spec.category == "clean":
                assert not any(term in spec.text for term in forbidden_for_middle)

    def test_rejects_invalid_n(self) -> None:
        with pytest.raises(ValueError):
            build_exam(0)


class TestSummarize:
    def test_pure_accounting_and_bounds_direction(self) -> None:
        spec_v = CaseSpec(
            band=SpeechGradeBand.초등,
            axis="derivative",
            category="violating",
            text="t",
            expected=GenerationFailureCode.F7,
        )
        spec_c = CaseSpec(
            band=SpeechGradeBand.초등, axis="-", category="clean", text="t", expected=None
        )
        outcomes = [
            CaseOutcome(spec=spec_v, detected=None, missed=True, false_alarm=False),
            CaseOutcome(
                spec=spec_v, detected=GenerationFailureCode.F7, missed=False, false_alarm=False
            ),
            CaseOutcome(spec=spec_c, detected=None, missed=False, false_alarm=False),
        ]
        report = summarize(outcomes)
        assert report.violating_total == 2
        assert report.missed == 1
        assert report.clean_total == 1
        assert report.false_alarm == 0
        assert report.miss_upper_bound() > 0.5
        assert report.false_alarm_upper_bound() > 0.0


class TestMachineJudge:
    def test_null_checker_misses_everything(self) -> None:
        cases = [c for c in build_exam(1) if c.category == "violating"]
        outcomes = run_machine(cases, _null_checker)
        assert all(o.missed for o in outcomes)

    def test_real_checker_detects_all_violating(self) -> None:
        cases = [c for c in build_exam(1) if c.category == "violating"]
        outcomes = run_machine(cases, _real_checker)
        assert all(not o.missed for o in outcomes)

    def test_real_checker_no_false_alarm_on_clean(self) -> None:
        cases = [c for c in build_exam(1) if c.category == "clean"]
        outcomes = run_machine(cases, _real_checker)
        assert all(not o.false_alarm for o in outcomes)


class TestMainGate:
    def test_real_checker_passes_exit_zero(self, tmp_path: Path) -> None:
        """③ 본판정 — 기본 그리드(n=12·CI와 동일)로 완주. 시험지가 analogy_fidelity_eval보다

        작아(violating 14축, 6템플릿 아님) n=2 같은 소표본은 Wilson 상한이 기본 임계(0.05)를
        넘는다(표본↓→상한↑ 방향은 정상 — `TestSummarize`가 별도로 그 방향을 봉인한다). 그래서
        본 게이트는 CI가 실제로 쓰는 n=12로 완주해 판정한다.
        """
        out = tmp_path / "report.json"
        assert main(["--json", str(out)]) == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["missed"] == 0
        assert payload["false_alarm"] == 0
        assert payload["control"] is False

    def test_control_null_checker_fails_exit_one(self) -> None:
        assert main(["--n-per-cell", "1", "--control"]) == 1


class TestMeasureGeneratedF7Rate:
    """실제 생성 배치 측정 — "작동한 비율" 원칙(정상 응답 ≠ 알고리즘이 일함) 준수."""

    def _outcome(self, reject_reason: str | None, status: str = "REJECTED") -> ExplanationOutcome:
        return ExplanationOutcome(
            row={}, status=status, prescreen_score=3, reject_reason=reject_reason
        )

    def test_dense_dict_carries_all_eight_codes(self) -> None:
        report = measure_generated_f7_rate([self._outcome(None, status="APPROVED")])
        assert set(report.failure_counts.keys()) == {f"F{i}" for i in range(1, 9)}

    def test_f7_hits_counted_and_non_fcode_reasons_ignored(self) -> None:
        outcomes = [
            self._outcome("F7"),
            self._outcome("F7"),
            self._outcome("empty_body"),  # F-코드가 아닌 구조 결함 — 집계 제외
            self._outcome(None, status="APPROVED"),
        ]
        report = measure_generated_f7_rate(outcomes)
        assert report.trials == 4
        assert report.failure_counts["F7"] == 2
        assert report.failure_counts["F1"] == 0

    def test_rate_upper_bound_is_conservative(self) -> None:
        outcomes = [self._outcome("F7"), self._outcome(None, status="APPROVED")]
        report = measure_generated_f7_rate(outcomes)
        assert report.f7_rate_upper_bound() > 0.5  # 1/2 관측 — 상한은 점추정보다 크다.

    def test_zero_trials_rejected_not_silently_zero(self) -> None:
        """빈 배치를 0%로 조용히 보고하지 않는다("관측 0 ≠ 확정 0")."""
        report = measure_generated_f7_rate([])
        with pytest.raises(ValueError):
            report.f7_rate_upper_bound()
