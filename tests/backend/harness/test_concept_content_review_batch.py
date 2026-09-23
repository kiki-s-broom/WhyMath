"""concept_content_review_batch 단위테스트 — LLM 없이 결정론·표본·rubric 변별력 검증."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.db.models.concept_content import (
    CONTENT_REVIEW_STATUS_AI_ESTIMATED,
    CONTENT_SCOPE_K12,
)
from whymath_backend.harness import concept_content_review_batch as ccrb
from whymath_backend.harness.concept_content_review_batch import (
    Assessment,
    BatchReport,
    _assess_one,
    _control_records,
    _injected_defects,
    main,
    min_n_for_zero_defects,
    stratified_sample,
)
from whymath_backend.l1.concept_content.projection import ConceptContentRecord


class TestMinN:
    def test_min_n_is_positive(self) -> None:
        n = min_n_for_zero_defects(0.05)
        assert n > 0

    def test_min_n_decreases_with_looser_threshold(self) -> None:
        strict = min_n_for_zero_defects(0.02)
        loose = min_n_for_zero_defects(0.05)
        assert strict > loose

    def test_min_n_higher_confidence_needs_more(self) -> None:
        n95 = min_n_for_zero_defects(0.05, confidence=0.95)
        n99 = min_n_for_zero_defects(0.05, confidence=0.99)
        assert n99 > n95

    def test_min_n_invalid_threshold_raises(self) -> None:
        with pytest.raises(ValueError):
            min_n_for_zero_defects(0.0)
        with pytest.raises(ValueError):
            min_n_for_zero_defects(1.0)


class TestStratifiedSample:
    def test_deterministic_by_seed(self) -> None:
        records = [
            ConceptContentRecord(
                code=f"N{i}",
                scope=CONTENT_SCOPE_K12,
                name="x",
                subject="s",
                unit=None,
                metaphor=None,
                misconception=None,
                formal_definition_internal=None,
                accepted_expressions=None,
                explanation=None,
                standard_codes=(),
                flashcards=(),
                review_status=CONTENT_REVIEW_STATUS_AI_ESTIMATED,
            )
            for i in range(100)
        ]
        s1 = stratified_sample(records, 10, seed=7)
        s2 = stratified_sample(records, 10, seed=7)
        assert [r.code for r in s1] == [r.code for r in s2]

    def test_respects_sample_size(self) -> None:
        records = [
            ConceptContentRecord(
                code=f"N{i}",
                scope=CONTENT_SCOPE_K12,
                name="x",
                subject="s",
                unit=None,
                metaphor=None,
                misconception=None,
                formal_definition_internal=None,
                accepted_expressions=None,
                explanation=None,
                standard_codes=(),
                flashcards=(),
                review_status=CONTENT_REVIEW_STATUS_AI_ESTIMATED,
            )
            for i in range(50)
        ]
        assert len(stratified_sample(records, 20, seed=1)) == 20

    def test_capped_at_total(self) -> None:
        records = [
            ConceptContentRecord(
                code="N1",
                scope=CONTENT_SCOPE_K12,
                name="x",
                subject="s",
                unit=None,
                metaphor=None,
                misconception=None,
                formal_definition_internal=None,
                accepted_expressions=None,
                explanation=None,
                standard_codes=(),
                flashcards=(),
                review_status=CONTENT_REVIEW_STATUS_AI_ESTIMATED,
            )
        ]
        assert len(stratified_sample(records, 100, seed=1)) == 1


class TestBatchReviewFakeLLM:
    def test_fake_llm_produces_jsonl_and_passes_gate(self, tmp_path: Path) -> None:
        out = tmp_path / "audit.jsonl"
        rc = main(
            [
                "--fake-llm",
                "--out",
                str(out),
                "--seed",
                "123",
                "--threshold",
                "0.10",
            ]
        )
        assert rc == 0
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) > 0
        # fake provider는 주입 결함을 항상 잡는다.
        assert any(json.loads(line).get("injected") for line in lines)
        assert any(json.loads(line).get("passed") for line in lines)

    def test_fake_llm_gate_fails_when_threshold_too_low(self, tmp_path: Path) -> None:
        out = tmp_path / "audit.jsonl"
        # threshold 0.0001 → 모든 결함을 초과로 판정, exit 1
        rc = main(
            [
                "--fake-llm",
                "--out",
                str(out),
                "--seed",
                "123",
                "--threshold",
                "0.0001",
            ]
        )
        assert rc == 1

    def test_dry_run_does_not_call_llm(self, tmp_path: Path) -> None:
        out = tmp_path / "audit.jsonl"
        rc = main(["--dry-run", "--out", str(out), "--seed", "123"])
        assert rc == 0
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert all(json.loads(line)["reason"] == "dry-run: 평가 생략" for line in lines)

    def test_injected_defects_count(self) -> None:
        assert len(_injected_defects()) >= 2


class TestBatchReviewWithTinyCorpus:
    def test_small_corpus_caps_sample_at_total(self, tmp_path: Path) -> None:
        k12 = tmp_path / "k12.json"
        k12.write_text(
            json.dumps(
                {
                    "scope": CONTENT_SCOPE_K12,
                    "content": [
                        {
                            "code": "N1",
                            "name": "자연수",
                            "subject": "초등수학",
                            "metaphor": "개수",
                            "misconception": "0 포함",
                            "formal_definition_internal": "1,2,3...",
                            "accepted_expressions": "자연수",
                            "explanation": "기초",
                            "standard_codes": ["[2수01-01]"],
                            "flashcards": [],
                            "review_status": "ai_estimated",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        out = tmp_path / "audit.jsonl"
        rc = main(
            [
                "--k12",
                str(k12),
                "--university",
                str(k12),
                "--fake-llm",
                "--out",
                str(out),
                "--threshold",
                "0.60",
            ]
        )
        assert rc == 0


def _mk(
    code: str,
    *,
    passed: bool,
    injected: bool = False,
    control: bool = False,
    sampled: bool = True,
) -> Assessment:
    """집계 계약 검증용 최소 Assessment."""
    return Assessment(
        code=code,
        scope=CONTENT_SCOPE_K12,
        subject="초등수학",
        passed=passed,
        defects=() if passed else ("x",),
        reason="",
        sampled=sampled,
        injected=injected,
        control=control,
        expected_pass=(False if injected else True if control else None),
        model="test",
        latency_ms=0.0,
        timestamp="2026-09-23T00:00:00+00:00",
    )


def _report(assessed: list[Assessment], **kw: object) -> BatchReport:
    params: dict = {
        "total_records": 100,
        "sample_size": sum(1 for a in assessed if a.sampled and not a.injected and not a.control),
        "injected_count": sum(1 for a in assessed if a.injected),
        "assessed": assessed,
        "threshold": 0.05,
        "confidence": 0.95,
        "control_count": sum(1 for a in assessed if a.control),
    }
    params.update(kw)
    return BatchReport(**params)  # type: ignore[arg-type]


class TestControlRecordsExist:
    """깨끗한 대조군이 실재하고 주입 결함과 짝을 이룬다."""

    def test_controls_are_present(self) -> None:
        assert len(_control_records()) >= 2

    def test_controls_pair_scopes_with_injected(self) -> None:
        # 오검출을 재려면 대조군이 주입 결함과 같은 scope를 덮어야 한다.
        assert {r.scope for r in _control_records()} == {r.scope for r in _injected_defects()}

    def test_control_codes_are_distinguishable(self) -> None:
        assert all(r.code.startswith("__CONTROL") for r in _control_records())
        assert all(r.code.startswith("__INJECT") for r in _injected_defects())

    def test_controls_have_no_missing_required_fields(self) -> None:
        # rubric 기준 5(필수 필드 결측)에 걸리면 대조군이 '정당하게' 실패해 무의미해진다.
        for r in _control_records():
            for field in (
                "metaphor",
                "misconception",
                "formal_definition_internal",
                "accepted_expressions",
                "explanation",
            ):
                assert getattr(r, field), f"{r.code}: {field} 비어 있음"

    def test_controls_have_no_crawl_residue(self) -> None:
        # rubric 기준 4(잔류 표기)에 걸리지 않아야 한다.
        for r in _control_records():
            assert "2022 개정" not in (r.explanation or "")


class TestFalseNegativeIsActuallyMeasured:
    """주입 결함을 놓친 것이 **숫자로 드러나야** 한다 (오버라이드 회귀 방지)."""

    def test_missed_injected_counts_llm_pass_on_injected(self) -> None:
        # LLM이 주입 결함을 통과시킨 상황
        rep = _report([_mk("__INJECT_A__", passed=True, injected=True, sampled=False)])
        assert rep.missed_injected == 1, "주입을 놓쳤는데 0으로 보고되면 변별력 검사가 위장이다"

    def test_missed_injected_zero_when_caught(self) -> None:
        rep = _report([_mk("__INJECT_A__", passed=False, injected=True, sampled=False)])
        assert rep.missed_injected == 0


class TestFalsePositiveIsMeasured:
    """깨끗한 대조군을 결함으로 찍은 것이 별도 축으로 집계된다."""

    def test_false_positive_counts_llm_fail_on_control(self) -> None:
        rep = _report([_mk("__CONTROL_A__", passed=False, control=True, sampled=False)])
        assert rep.false_positive_controls == 1

    def test_false_positive_zero_when_control_passes(self) -> None:
        rep = _report([_mk("__CONTROL_A__", passed=True, control=True, sampled=False)])
        assert rep.false_positive_controls == 0

    def test_controls_excluded_from_sample_defect_rate(self) -> None:
        # 대조군이 표본에 섞이면 결함율이 오염된다.
        rep = _report(
            [
                _mk("S1", passed=True),
                _mk("__CONTROL_A__", passed=False, control=True, sampled=False),
            ]
        )
        assert rep.defective_sampled == 0
        assert len(rep.sampled_assessments()) == 1

    def test_two_directions_are_separate_numbers(self) -> None:
        rep = _report(
            [
                _mk("__INJECT_A__", passed=True, injected=True, sampled=False),
                _mk("__CONTROL_A__", passed=False, control=True, sampled=False),
            ]
        )
        assert (rep.missed_injected, rep.false_positive_controls) == (1, 1)


class TestGateFailsOnFalsePositive:
    """오검출도 exit 1이어야 하고, 실패 이유가 구분돼야 한다."""

    def test_fake_llm_run_reports_both_axes(self, tmp_path: Path) -> None:
        out = tmp_path / "audit.jsonl"
        rc = main(["--fake-llm", "--out", str(out), "--seed", "123", "--threshold", "0.10"])
        assert rc == 0
        rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        assert any(r.get("control") for r in rows), "대조군이 감사 리포트에 없다"
        # fake provider는 __CONTROL을 통과시키므로 오검출 0이어야 한다(성공 방향 대조군).
        controls = [r for r in rows if r.get("control")]
        assert all(r["passed"] for r in controls)
        assert all(r["expected_pass"] is True for r in controls)
        injected = [r for r in rows if r.get("injected")]
        assert all(not r["passed"] for r in injected)
        assert all(r["expected_pass"] is False for r in injected)

    def test_dry_run_marks_discrimination_unmeasured(self, tmp_path: Path) -> None:
        out = tmp_path / "audit.jsonl"
        rc = main(["--dry-run", "--out", str(out), "--seed", "123"])
        assert rc == 0
        rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        assert any(r.get("control") for r in rows)


class TestRenderSeparatesDirections:
    def test_render_names_both_axes(self) -> None:
        rep = _report(
            [
                _mk("__INJECT_A__", passed=True, injected=True, sampled=False),
                _mk("__CONTROL_A__", passed=False, control=True, sampled=False),
            ]
        )
        text = rep.render()
        assert "false negative" in text
        assert "false positive" in text
        assert "rubric 과민" in text

    def test_render_warns_when_no_controls(self) -> None:
        rep = _report([_mk("S1", passed=True)], control_count=0)
        assert "대조군 0건" in rep.render()

    def test_dry_run_report_says_not_measured(self) -> None:
        rep = _report([_mk("S1", passed=True)], discrimination_measured=False)
        assert "측정값이 아니다" in rep.render()

    def test_to_json_exposes_false_positive(self) -> None:
        rep = _report([_mk("__CONTROL_A__", passed=False, control=True, sampled=False)])
        assert rep.to_json()["false_positive_controls"] == 1
        assert rep.to_json()["control_count"] == 1


# ──────────────────────────────────────────────────────────────────────────
# 뮤테이션 생존분 대응 — 아래 네 테스트는 각각 특정 절을 **직접 밟는다**.
# (2026-09-23 1차 뮤테이션에서 M1·M3·M5·M7이 생존했고, 원인은 코드가 아니라
#  픽스처가 그 절에 닿지 않은 것이었다 — CLAUDE.md 「픽스처가 그 절을 실제로 밟는가」)
# ──────────────────────────────────────────────────────────────────────────


class _VerdictProvider:
    """지정한 판정을 그대로 돌려주는 스텁 — rubric 자체가 아니라 *기록 경로*를 시험한다."""

    def __init__(self, *, passed_for_inject: bool, passed_for_control: bool) -> None:
        self._inject = passed_for_inject
        self._control = passed_for_control

    async def generate(self, prompt: str, system: str, decision: object, **kw: object) -> object:
        from whymath_backend.l3.models import GenerationResult, Usage

        code = ""
        for line in prompt.splitlines():
            if line.startswith("code:"):
                code = line.split(":", 1)[1].strip()
                break
        if code.startswith("__INJECT"):
            passed = self._inject
        elif code.startswith("__CONTROL"):
            passed = self._control
        else:
            passed = True
        body = (
            '{"passed": true, "defects": [], "reason": "ok"}'
            if passed
            else '{"passed": false, "defects": ["d"], "reason": "ng"}'
        )
        return GenerationResult(text=body, usage=Usage(input_tokens=1, output_tokens=1))


class TestAssessOneRecordsLlmVerdict:
    """M1 대응 — 주입 레코드의 `passed`를 강제로 덮으면 누락을 영영 못 센다."""

    async def test_injected_passed_is_not_overridden(self) -> None:
        provider = _VerdictProvider(passed_for_inject=True, passed_for_control=True)
        a = await _assess_one(
            provider, _injected_defects()[0], model_tier="quality", injected=True, sampled=False
        )
        # LLM이 "통과"라고 했으면 그대로 True여야 한다. False로 덮으면
        # missed_injected가 구조적으로 0이 되어 변별력 검사가 위장이 된다.
        assert a.passed is True
        assert a.expected_pass is False
        assert (
            BatchReport(
                total_records=1,
                sample_size=0,
                injected_count=1,
                assessed=[a],
                threshold=0.05,
                confidence=0.95,
                control_count=0,
            ).missed_injected
            == 1
        )

    async def test_control_verdict_is_recorded(self) -> None:
        provider = _VerdictProvider(passed_for_inject=False, passed_for_control=False)
        a = await _assess_one(
            provider, _control_records()[0], model_tier="quality", control=True, sampled=False
        )
        assert a.passed is False
        assert a.expected_pass is True


class TestGateFiresEndToEnd:
    """M3·M7 대응 — 게이트 조건을 `main()` 전 경로로 실제 발화시킨다."""

    def test_gate_fails_when_injected_defect_is_missed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            ccrb,
            "_FakeProvider",
            lambda: _VerdictProvider(passed_for_inject=True, passed_for_control=True),
        )
        rc = main(["--fake-llm", "--out", str(tmp_path / "a.jsonl"), "--seed", "7"])
        assert rc == 1, "주입 결함을 전부 놓쳤는데 게이트가 통과시켰다"

    def test_gate_fails_when_control_is_marked_defective(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            ccrb,
            "_FakeProvider",
            lambda: _VerdictProvider(passed_for_inject=False, passed_for_control=False),
        )
        rc = main(["--fake-llm", "--out", str(tmp_path / "b.jsonl"), "--seed", "7"])
        assert rc == 1, "깨끗한 대조군을 결함으로 찍었는데 게이트가 통과시켰다"

    def test_gate_passes_when_both_directions_correct(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 성공 방향 대조군 — 없으면 "전부 실패로 계상"이라는 과잉 수정이 통과한다.
        monkeypatch.setattr(
            ccrb,
            "_FakeProvider",
            lambda: _VerdictProvider(passed_for_inject=False, passed_for_control=True),
        )
        rc = main(["--fake-llm", "--out", str(tmp_path / "c.jsonl"), "--seed", "7"])
        assert rc == 0


class TestControlIsolationIsUnconditional:
    """M5 대응 — `sampled` 플래그와 무관하게 대조군은 표본 결함율에서 빠진다."""

    def test_control_excluded_even_when_flagged_sampled(self) -> None:
        rep = _report(
            [
                _mk("S1", passed=True),
                # sampled=True인 대조군: 격리 절이 없으면 결함율에 섞인다.
                _mk("__CONTROL_A__", passed=False, control=True, sampled=True),
            ]
        )
        assert rep.defective_sampled == 0, "대조군이 표본 결함율을 오염시켰다"
        assert [a.code for a in rep.sampled_assessments()] == ["S1"]
