"""Tier1 검산 거부 행 분류기 테스트 — EOS-23 ③(순수·결정론·LLM 0·네트워크 0).

픽스처는 **실제 직렬화 경로**로 만든다: `ScriptedGenerator` 후보를 실제 오케스트레이터
(`run_equivalent_generation`)에 흘려 게이트가 **진짜로** 내는 `rejected_gate` outcome과 사유
문자열을 얻고, 회차 축적 CLI가 쓰는 조성 함수(`problem_corpus_accumulate._queue_entry` →
`_to_record` → `_record_to_json`)로 `ReviewQueueEntry` 행을 만들어 JSONL에 append한다.
즉 Phaiakes9의 `anthropic.review.jsonl`과 같은 모양의 행이다 — 손으로 흉내 낸 dict가 아니다.

각 판정 절의 반례(CLAUDE.md "픽스처가 그 절을 실제로 밟는가"):
  - ⓑ 절(파생량 일치)      → 근의 합 5 · 곱 6 · 차 1 · 제곱합 13 · 역수합 5/6
  - ⓐ 절(아무것도 불일치)   → 7
  - 재현 절(재검산 pass)    → 근 자체 2 (대조군 — 게이트는 근 선택으로 거부했다)
  - 판정불가 절(ⓐ로 접지 않음) → 파싱 불가 조건 · 다변수 · 비다항 · 연립 · 집계 선언
  - 0건 가드               → 대상 없는 큐 · spec 필터로 전부 빠진 큐 · 파일 없음
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import problem_corpus_accumulate as accumulate
from whymath_backend.harness import tier1_rejection_classifier as clf
from whymath_backend.harness.needs_review_worklist import (
    ReviewQueueEntry,
    append_review_queue_jsonl,
    load_review_queue_jsonl,
)
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.generator import CandidateProblem, ScriptedGenerator
from whymath_backend.l3.equivalent.orchestrator import run_equivalent_generation
from whymath_backend.l3.verify_answer import AnswerVerdict
from whymath_backend.schema.enums import (
    AnswerFormat,
    Curriculum,
    GenerationType,
    LicenseType,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem
from whymath_backend.schema.provenance import ContentProvenance

_QUAD = "x**2 - 5*x + 6 = 0"  # 근 2·3 → 합 5 · 곱 6 · 차 1 · 제곱합 13 · 역수합 5/6
_STEM_SUM = "이차방정식 x^2 - 5x + 6 = 0 의 두 근의 합을 구하시오."
_SPEC = EquivalenceSpec(
    achievement_standard_codes=frozenset({"[10공수1-02-02]"}), difficulty_overall=3.5
)


def _candidate(
    claimed: str,
    *,
    conditions: str | list[str] = _QUAD,
    stem: str = _STEM_SUM,
    selection: str | None = "unique",
    answer_map: dict[str, str] | None = None,
) -> CandidateProblem:
    # LLM 저작 경로(llm_generator._assemble)와 같은 모양 — answer_selection은 스키마 필수라
    # 모델이 항상 선언하고, answer_aggregate는 그 경로가 채우지 않는다.
    return CandidateProblem(
        problem=Problem(
            slug=f"t-{abs(hash((claimed, str(conditions), stem))) % 10**8}",
            source_type=SourceType.자체생성,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.공통,
            unit_codes=["POLY-ROOT"],
            difficulty_overall=3.5,
            answer_format=AnswerFormat.실수,
            achievement_standard_codes=["[10공수1-02-02]"],
            question_text=stem,
            answer=claimed,
            answer_explanation="근과 계수의 관계로 구한다.",
        ),
        provenance=ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
        ),
        conditions=conditions,
        answer_map=answer_map if answer_map is not None else {"x": claimed},
        answer_selection=selection,
    )


def _real_entry(candidate: CandidateProblem, *, spec_id: str = "quad-sum") -> ReviewQueueEntry:
    """실제 게이트 → 실제 조성 함수로 큐 행을 만든다(수용이면 테스트 전제 위반)."""
    outcome = run_equivalent_generation(_SPEC, ScriptedGenerator([candidate]))
    assert outcome.status not in ("accepted", "accepted_stored"), outcome.reasons
    return accumulate._queue_entry(outcome, "run-eos23-test", spec_id)


def _roundtrip(tmp_path: Path, entries: list[ReviewQueueEntry]) -> Path:
    """JSONL로 append 후 되읽을 경로 반환 — Phaiakes9 파일과 같은 매체를 거친다."""
    path = tmp_path / "anthropic.review.jsonl"
    for entry in entries:
        append_review_queue_jsonl(path, entry)
    return path


def _loaded(tmp_path: Path, entry: ReviewQueueEntry) -> ReviewQueueEntry:
    path = _roundtrip(tmp_path, [entry])
    loaded, errors = load_review_queue_jsonl(path)
    assert errors == []
    return loaded[0]


def _with_verify(entry: ReviewQueueEntry, **changes: Any) -> ReviewQueueEntry:
    """실제 행의 verify 재료만 바꾼 사본 — 게이트 경유가 불가능한 판정불가 절을 밟는 용도."""
    assert entry.candidate_payload is not None
    payload = json.loads(json.dumps(entry.candidate_payload))
    payload["verify"].update(changes)
    return entry.model_copy(update={"candidate_payload": payload})


# ══════════════════════════════════════════════════════════════════════════
# 픽스처 실재 — 실제 게이트가 EOS-121과 같은 사유로 거부하는가
# ══════════════════════════════════════════════════════════════════════════
class TestFixtureFidelity:
    def test_sum_answer_is_rejected_by_tier1_like_eos121(self, tmp_path: Path) -> None:
        """합을 x에 담으면 게이트가 `Tier1 답 검산 fail: 조건 위반 — 잔차 ≠ 0`으로 거부한다."""
        entry = _loaded(tmp_path, _real_entry(_candidate("5")))
        assert entry.status == "rejected_gate"
        assert any("Tier1 답 검산 fail: 조건 위반 — 잔차 ≠ 0" in r for r in entry.reasons)
        payload = entry.candidate_payload
        assert payload is not None
        # 실제 코퍼스 직렬화 형태(`_record_to_json`) — verify 하위에 검산 재료가 있다.
        assert payload["verify"]["conditions"] == _QUAD
        assert payload["verify"]["answer_map"] == {"x": "5"}
        assert "answer_aggregate" not in payload["verify"]
        assert payload["question_text"] == _STEM_SUM


# ══════════════════════════════════════════════════════════════════════════
# ⓑ 표현 불일치
# ══════════════════════════════════════════════════════════════════════════
class TestRepresentationMismatch:
    def test_sum_in_root_slot_is_representation_mismatch(self, tmp_path: Path) -> None:
        row = clf.classify_entry(_loaded(tmp_path, _real_entry(_candidate("5"))))
        assert row.verdict == "representation_mismatch"
        assert row.reason_code == "classified"
        assert row.matched_derived == ["sum"]
        assert row.matches_root is False
        assert sorted(row.roots) == ["2", "3"]
        assert row.recorded_tier1_fail is True
        assert row.reproduced_state == "fail"
        assert row.reproduced_direct_branch is True
        # 게이트 검증기가 answer_aggregate="sum"이었다면 통과시켰을 것 — 처방 축의 증거.
        assert row.aggregate_gate_recheck == {"sum": "pass", "product": "fail"}
        assert row.stem_signals == ["sum"]
        assert row.stem_consistent is True

    @pytest.mark.parametrize(
        ("claimed", "expected"),
        [
            ("6", "product"),
            ("1", "abs_difference"),
            ("13", "sum_of_squares"),
            ("5/6", "sum_of_reciprocals"),
        ],
    )
    def test_each_derived_quantity_is_recognised(
        self, tmp_path: Path, claimed: str, expected: str
    ) -> None:
        """파생량마다 반례 — 그 비교를 지우면 이 케이스가 ⓐ로 떨어진다."""
        row = clf.classify_entry(_loaded(tmp_path, _real_entry(_candidate(claimed))))
        assert row.verdict == "representation_mismatch"
        assert row.matched_derived == [expected]

    def test_stem_disagreement_is_recorded_not_used_for_verdict(self, tmp_path: Path) -> None:
        """발문은 합을 묻는데 답은 곱 — 판정은 여전히 ⓑ(수식 일관성), 발문 불일치는 기록만."""
        row = clf.classify_entry(_loaded(tmp_path, _real_entry(_candidate("6"))))
        assert row.verdict == "representation_mismatch"
        assert row.stem_consistent is False


# ══════════════════════════════════════════════════════════════════════════
# ⓐ 산술 오류
# ══════════════════════════════════════════════════════════════════════════
class TestArithmeticError:
    def test_unrelated_value_is_arithmetic_error(self, tmp_path: Path) -> None:
        row = clf.classify_entry(_loaded(tmp_path, _real_entry(_candidate("7"))))
        assert row.verdict == "arithmetic_error"
        assert row.matched_derived == []
        assert row.matches_root is False
        # 모든 비교가 확정(False)이어야 ⓐ다 — None이 하나라도 있으면 판정불가여야 한다.
        assert row.derived_comparison
        assert all(hit is False for hit in row.derived_comparison.values())


# ══════════════════════════════════════════════════════════════════════════
# 재현 — 대조군(근 자체)
# ══════════════════════════════════════════════════════════════════════════
class TestReproduction:
    def test_root_itself_is_not_reproduced_real_gate(self, tmp_path: Path) -> None:
        """근 2를 답으로 내면 Tier1은 통과한다(게이트는 근 선택 unique 위반으로 거부) → 재현 안 됨."""
        entry = _loaded(tmp_path, _real_entry(_candidate("2")))
        assert entry.status == "rejected_gate"
        row = clf.classify_entry(entry)
        assert row.verdict == "undecidable"
        assert row.reason_code == "not_reproduced"
        assert row.reproduced_state == "pass"
        assert row.recorded_tier1_fail is False

    def test_root_itself_with_tier1_reason_is_still_not_reproduced(self, tmp_path: Path) -> None:
        """기록 사유가 Tier1 fail이라도 재검산이 pass면 증거로 쓰지 않는다(기록보다 재현 우선)."""
        base = _loaded(tmp_path, _real_entry(_candidate("5")))
        doctored = _with_verify(base, answer_map={"x": "2"})
        row = clf.classify_entry(doctored)
        assert row.recorded_tier1_fail is True
        assert row.reason_code == "not_reproduced"
        assert row.verdict == "undecidable"

    def test_other_gate_rejection_is_not_tier1_population(self, tmp_path: Path) -> None:
        """재검산은 fail이나 게이트는 '해 없음'으로 먼저 거부 → Tier1 모집단 밖."""
        candidate = _candidate("-1", conditions="x**2 + x + 1 = 0")
        entry = _loaded(tmp_path, _real_entry(candidate))
        assert not any("Tier1" in r for r in entry.reasons)
        row = clf.classify_entry(entry)
        assert row.reproduced_state == "fail"
        assert row.reason_code == "not_tier1_rejection"
        assert row.verdict == "undecidable"


# ══════════════════════════════════════════════════════════════════════════
# 판정불가 — 모른다 ≠ 아니다(ⓐ로 접지 않는다)
# ══════════════════════════════════════════════════════════════════════════
class TestUndecidable:
    def test_unparseable_condition(self, tmp_path: Path) -> None:
        base = _loaded(tmp_path, _real_entry(_candidate("5")))
        row = clf.classify_entry(_with_verify(base, conditions="x**2 - 5*x + + = 0"))
        assert row.verdict == "undecidable"
        assert row.reason_code == "not_reproduced"
        assert row.reproduced_state == "unverifiable"

    def test_multivariate_condition(self, tmp_path: Path) -> None:
        base = _loaded(tmp_path, _real_entry(_candidate("5")))
        row = clf.classify_entry(
            _with_verify(base, conditions="x**2 - y = 0", answer_map={"x": "2", "y": "5"})
        )
        assert row.reproduced_state == "fail"
        assert row.verdict == "undecidable"
        assert row.reason_code == "multivariate"

    def test_non_polynomial_condition(self, tmp_path: Path) -> None:
        base = _loaded(tmp_path, _real_entry(_candidate("5")))
        row = clf.classify_entry(
            _with_verify(base, conditions="sin(x) = 2*x + 1", answer_map={"x": "1"})
        )
        assert row.reproduced_state == "fail"
        assert row.verdict == "undecidable"
        assert row.reason_code == "not_polynomial"
        assert row.message  # 사유가 비어 있지 않다(예외 타입명 포함)

    def test_multi_condition(self, tmp_path: Path) -> None:
        base = _loaded(tmp_path, _real_entry(_candidate("5")))
        row = clf.classify_entry(_with_verify(base, conditions=[_QUAD, "x > 0"]))
        assert row.reproduced_state == "fail"
        assert row.reason_code == "multi_condition"
        assert row.verdict == "undecidable"

    def test_declared_aggregate_is_not_tier1_path(self, tmp_path: Path) -> None:
        base = _loaded(tmp_path, _real_entry(_candidate("5")))
        row = clf.classify_entry(_with_verify(base, answer_aggregate="sum"))
        assert row.reason_code == "not_tier1_path"
        assert row.verdict == "undecidable"

    def test_undetermined_root_comparison_is_not_arithmetic_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """비교 확정 불가(None) + 일치 0 → 판정불가. ⓐ는 모든 비교가 False로 확정될 때만이다."""
        entry = _loaded(tmp_path, _real_entry(_candidate("7")))
        monkeypatch.setattr(clf, "_equal", lambda actual, claimed: None)
        row = clf.classify_entry(entry)
        assert row.matches_root is None
        assert row.verdict == "undecidable"
        assert row.reason_code == "compare_undetermined"

    def test_unverifiable_aggregate_recheck_is_not_arithmetic_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """게이트 집계 검증기가 unverifiable이면 합·곱 불일치를 단정하지 않는다."""
        entry = _loaded(tmp_path, _real_entry(_candidate("7")))
        monkeypatch.setattr(
            clf,
            "verify_root_aggregate",
            lambda *args, **kwargs: AnswerVerdict(
                state="unverifiable", reason="주입", samples_checked=0
            ),
        )
        row = clf.classify_entry(entry)
        assert row.derived_comparison["sum"] is None
        assert row.verdict == "undecidable"
        assert row.reason_code == "compare_undetermined"

    def test_missing_verify(self, tmp_path: Path) -> None:
        base = _loaded(tmp_path, _real_entry(_candidate("5")))
        assert base.candidate_payload is not None
        payload = {k: v for k, v in base.candidate_payload.items() if k != "verify"}
        row = clf.classify_entry(base.model_copy(update={"candidate_payload": payload}))
        assert row.reason_code == "verify_missing"
        assert row.verdict == "undecidable"


# ══════════════════════════════════════════════════════════════════════════
# 발문 보조 신호
# ══════════════════════════════════════════════════════════════════════════
class TestStemSignals:
    @pytest.mark.parametrize(
        ("stem", "expected"),
        [
            (_STEM_SUM, ["sum"]),
            ("이차방정식 x^2+3x-4=0의 두 근의 곱을 구하시오.", ["product"]),
            ("이차방정식 x^2-3x+1=0의 두 근의 제곱의 합을 구하시오.", ["sum_of_squares"]),
            ("두 근의 역수의 합을 구하시오.", ["sum_of_reciprocals"]),
            ("이차방정식 x^2-3x+1=0의 큰 근을 구하시오.", ["root"]),
            ("이차방정식을 푸시오.", []),
            ("두 근 α, β에 대하여 α+β의 값을 구하시오.", ["sum"]),
        ],
    )
    def test_signals(self, stem: str, expected: list[str]) -> None:
        """'제곱의 합'은 합으로 이중 계상하지 않고, '이차'의 '차'는 차 신호가 아니다."""
        assert clf.stem_signals(stem) == expected


# ══════════════════════════════════════════════════════════════════════════
# CLI — 집계·0건 가드·로드 실패·산출 파일
# ══════════════════════════════════════════════════════════════════════════
class TestCli:
    def _mixed_queue(self, tmp_path: Path) -> Path:
        return _roundtrip(
            tmp_path,
            [
                _real_entry(_candidate("5")),  # ⓑ
                _real_entry(_candidate("7")),  # ⓐ
                _real_entry(_candidate("2")),  # 대조군 — 재현 안 됨
                _real_entry(_candidate("3", selection=None)),  # needs_review — 비대상
                _real_entry(_candidate("5"), spec_id="quad-largest"),  # spec 필터로 비대상
            ],
        )

    def test_summary_counts(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = self._mixed_queue(tmp_path)
        out = tmp_path / "result.json"
        code = clf.main([str(path), "--spec", "quad-sum", "--json", "--out", str(out)])
        stdout = capsys.readouterr().out
        assert code == clf.EXIT_OK
        assert stdout.isascii()  # PowerShell cp949 콘솔을 거쳐도 깨지지 않게
        # 행은 한 줄에 하나 — 채팅 붙여넣기 단위.
        assert sum(1 for line in stdout.splitlines() if line.startswith('  {"line":')) == 3
        summary = json.loads(stdout)
        assert summary["measured"] is True
        assert summary["rows_total"] == 5
        assert summary["target_rows"] == 3
        assert summary["verdict_counts"] == {
            "arithmetic_error": 1,
            "representation_mismatch": 1,
            "undecidable": 1,
        }
        assert summary["by_spec"] == {
            "quad-sum": {"arithmetic_error": 1, "representation_mismatch": 1, "undecidable": 1}
        }
        assert summary["undecidable_reason_codes"] == {"not_reproduced": 1}
        assert summary["matched_derived_counts"] == {"sum": 1}
        assert summary["aggregate_gate_would_pass"] == {"sum": 1}
        assert summary["skipped"]["by_status"] == {"needs_review": 1}
        assert summary["skipped"]["by_spec_filter"] == {"quad-largest": 1}
        assert summary["run_ids"] == {"run-eos23-test": 3}
        assert [r["verdict"] for r in summary["rows"]] == [
            "representation_mismatch",
            "arithmetic_error",
            "undecidable",
        ]
        full = json.loads(out.read_text(encoding="utf-8"))
        assert len(full["rows_full"]) == 3
        assert full["rows_full"][0]["stem_excerpt"] == _STEM_SUM

    def test_no_spec_filter_includes_all_specs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = self._mixed_queue(tmp_path)
        assert clf.main([str(path), "--json"]) == clf.EXIT_OK
        summary = json.loads(capsys.readouterr().out)
        assert summary["target_rows"] == 4
        assert set(summary["by_spec"]) == {"quad-sum", "quad-largest"}

    def test_zero_targets_exits_2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """대상 0건은 실패다 — 공허한 통과 금지."""
        path = _roundtrip(tmp_path, [_real_entry(_candidate("3", selection=None))])
        assert clf.main([str(path), "--json"]) == clf.EXIT_EMPTY
        summary = json.loads(capsys.readouterr().out)
        assert summary["measured"] is False
        assert summary["target_rows"] == 0

    def test_spec_filter_excluding_everything_exits_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _roundtrip(tmp_path, [_real_entry(_candidate("5"))])
        assert clf.main([str(path), "--spec", "quad-typo", "--json"]) == clf.EXIT_EMPTY
        summary = json.loads(capsys.readouterr().out)
        assert summary["skipped"]["by_spec_filter"] == {"quad-sum": 1}

    def test_missing_file_exits_2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code = clf.main([str(tmp_path / "nope.jsonl"), "--json"])
        assert code == clf.EXIT_EMPTY
        summary = json.loads(capsys.readouterr().out)
        assert summary["measured"] is False
        assert "FileNotFoundError" in summary["error"]

    def test_broken_line_is_counted_and_exit_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _roundtrip(tmp_path, [_real_entry(_candidate("5"))])
        with path.open("a", encoding="utf-8") as fh:
            fh.write("{not json\n")
        assert clf.main([str(path), "--json"]) == clf.EXIT_PARTIAL
        summary = json.loads(capsys.readouterr().out)
        assert summary["rows_total"] == 2
        assert summary["rows_valid"] == 1
        assert len(summary["load_errors"]) == 1
        assert "JSONDecodeError" in summary["load_errors"][0]
        assert summary["target_rows"] == 1

    def test_text_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = _roundtrip(tmp_path, [_real_entry(_candidate("5"))])
        assert clf.main([str(path)]) == clf.EXIT_OK
        text = capsys.readouterr().out
        assert "표현 불일치(ⓑ) 1" in text
