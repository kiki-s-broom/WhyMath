"""QA 엔진 문항별 판정 좌석·어댑터 — predictions 생산자 계약 (EOS-137 ①).

정본: `harness/qa_pipeline.judge_item`(좌석) + `harness/qa_item_verdicts`(어댑터). 검증 축:
  - **판정 불가 ≠ 통과** — 판정 불가 축이 있으면 verdict None이고, 어댑터는 그 문항을
    predictions에 쓰지 않는다. 혼동행렬 쪽에서 "미평가"로 분리되는지까지 왕복으로 본다.
  - **재구현 0** — 좌석 3축의 판정이 같은 입력에서 코퍼스 단위 축(qa_pipeline 축 2·
    banned_words_pii_eval.run·provenance_audit)과 **같은 결론**을 내는지 대조한다. 술어가
    갈라지면 RED.
  - **9축 분할 전수성** — 좌석 3축 + 코퍼스 단위 6축 = build_report가 조립하는 축 전부.
  - **검수자가 본 입력** — 어댑터는 review_session 로더를 그대로 쓴다(큐 행은
    candidate_payload가 판정 대상 · 파일 안 중복은 첫 행). 로더 사유 토큰과의 결합도 동결.
  - **대응 불가 분리** — cu_slug 없음·본문 없음·slug 불일치·입력 간 본문 충돌은 사유별로
    전건 보고된다.
  - **측정 실패 ≠ 통과** — 입력 0건·판정 0건은 exit 1, 손상·부재는 exit 2, 둘 다 무산출.
  - **계약 형식 왕복** — 산출 파일을 qa_confusion_matrix의 실제 파서·CLI가 그대로 먹는다.

hermetic — tmp_path·픽스처만(LLM·DB·네트워크 0). 저장소 코퍼스는 읽기만 한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import banned_words_pii_eval
from whymath_backend.harness import qa_item_verdicts as adapter
from whymath_backend.harness import qa_pipeline as qp
from whymath_backend.harness.golden_benchmark import (
    AsFoundBasis,
    GoldenItem,
    GoldenLabel,
    freeze_golden_set,
    load_evaluation_ledger,
    write_golden_set,
)
from whymath_backend.harness.review_session import load_review_items
from whymath_backend.ops import provenance_audit
from whymath_backend.ops import qa_confusion_matrix as qcm
from whymath_backend.schema.enums import GenerationFailureCode

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SAMPLE_CORPUS = _REPO_ROOT / "data" / "corpus" / "problem_bank_binomial_distribution_v0"


def _clean_problem(slug: str = "wm-test-0001") -> dict[str, Any]:
    """저장소 실코퍼스 1행을 바탕으로 한 정상 문항(좌석 3축 전부 적용·전부 ok)."""
    with (_SAMPLE_CORPUS / "problems.jsonl").open(encoding="utf-8") as handle:
        row: dict[str, Any] = json.loads(handle.readline())
    row = json.loads(json.dumps(row))  # 깊은 복사
    row["slug"] = slug
    return row


def _write_jsonl(path: Path, rows: list[Any]) -> Path:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    return path


def _queue_row(payload: dict[str, Any] | None, *, slug: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"status": "needs_review", "candidate_payload": payload}
    resolved = slug if slug is not None else (payload or {}).get("slug")
    if resolved is not None:
        row["slug"] = resolved
    return row


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    code = adapter.main(argv)
    summary: dict[str, Any] = json.loads(capsys.readouterr().out)
    return code, summary


# ──────────────────────────────────────────────────────────────────────────
# 좌석 — qa_pipeline.judge_item
# ──────────────────────────────────────────────────────────────────────────
class TestJudgeItem:
    def test_clean_problem_passes_with_all_three_axes_applied(self) -> None:
        judgement = qp.judge_item(_clean_problem())

        assert judgement.verdict == "pass"
        assert {name: r.status for name, r in judgement.axes.items()} == {
            "equivalence_canonicalize": "ok",
            "banned_words_pii": "ok",
            "content_provenance": "ok",
        }

    def test_dsl_violation_fails(self) -> None:
        problem = _clean_problem()
        problem["verify"]["conditions"] = "largest_root(2, 8) == 8"

        judgement = qp.judge_item(problem)

        assert judgement.verdict == "fail"
        assert judgement.failed_axes == ("equivalence_canonicalize",)

    @pytest.mark.parametrize(
        ("field", "text"),
        [
            ("question_text", "이 병신 같은 문제를 푸시오."),
            # 번호 뒤에 공백을 둔다 — `\b` 경계라 조사가 붙으면(`5678로`) 엔진이 못 잡는다
            # (엔진 사각 실측 2026-09-28 · 이 테스트의 대상이 아니므로 픽스처를 맞춘다).
            ("answer_explanation", "문의는 010-1234-5678 번호로 하시오."),
        ],
    )
    def test_banned_word_or_third_party_pii_fails(self, field: str, text: str) -> None:
        problem = _clean_problem()
        problem[field] = text

        judgement = qp.judge_item(problem)

        assert judgement.verdict == "fail"
        assert judgement.failed_axes == ("banned_words_pii",)

    @pytest.mark.parametrize("missing", ["license", "source_type"])
    def test_missing_record_provenance_fails(self, missing: str) -> None:
        problem = _clean_problem()
        problem[missing] = None

        judgement = qp.judge_item(problem)

        assert judgement.verdict == "fail"
        assert judgement.failed_axes == ("content_provenance",)

    def test_unjudgeable_axis_is_not_a_pass(self) -> None:
        """핵심 계약 — 스캔할 수 없는 필드가 있으면 통과가 아니라 판정 불가다."""
        problem = _clean_problem()
        problem["question_text"] = 12345  # 타입 위반 — 금칙어 축이 볼 수 없다

        judgement = qp.judge_item(problem)

        assert judgement.verdict is None
        assert judgement.unjudgeable_axes == ("banned_words_pii",)
        assert judgement.axes["banned_words_pii"].reason is not None
        assert "TypeError" in judgement.axes["banned_words_pii"].reason

    def test_violation_wins_over_unjudgeable(self) -> None:
        """다른 축이 판정 불가여도 위반이 하나 있으면 결론(fail)은 선다."""
        problem = _clean_problem()
        problem["question_text"] = 12345
        problem["license"] = None

        judgement = qp.judge_item(problem)

        assert judgement.verdict == "fail"
        assert judgement.failed_axes == ("content_provenance",)
        assert judgement.unjudgeable_axes == ("banned_words_pii",)

    def test_exempt_answer_kind_is_not_applicable(self) -> None:
        """S3-28 제외 answer_kind는 축 2 대상이 아니다 — 좌석도 같은 선별을 쓴다."""
        problem = _clean_problem()
        problem["verify"] = {
            "answer_kind": "finite_probability",
            "conditions": "space=...; event=...",
        }

        judgement = qp.judge_item(problem)

        assert judgement.axes["equivalence_canonicalize"].status == "not_applicable"
        assert judgement.verdict == "pass"

    def test_judge_function_exception_is_unjudgeable_with_type_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(_condition: str) -> str | None:
            raise RuntimeError("합성 실패")

        monkeypatch.setattr(qp, "condition_dsl_violation", _boom)

        judgement = qp.judge_item(_clean_problem())

        assert judgement.verdict is None
        reason = judgement.axes["equivalence_canonicalize"].reason
        assert reason is not None and reason.startswith("RuntimeError")


class TestAxisPartition:
    """9축 = 좌석 3축 + 코퍼스 단위 6축 — 새 축이 분류 없이 끼면 RED."""

    def test_partition_is_exhaustive_and_disjoint(self) -> None:
        item_level = set(qp.ITEM_LEVEL_AXES)
        corpus_level = set(qp.CORPUS_LEVEL_ONLY_AXES)

        assert item_level.isdisjoint(corpus_level)
        assert item_level | corpus_level == set(qp.AXIS_NAMES)
        assert set(qp.ITEM_AXIS_SCOPE) == item_level  # 좌석 3축은 각자 범위를 밝힌다
        assert all(reason for reason in qp.CORPUS_LEVEL_ONLY_AXES.values())

    def test_axis_names_match_build_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _ok(*_args: object, **_kwargs: object) -> qp.AxisResult:
            return qp.AxisResult(measured=True, status="ok", detail={})

        for name in qp.AXIS_NAMES:
            monkeypatch.setattr(qp, f"_axis_{name}", _ok)

        report = qp.build_report(tmp_path, repo_root=tmp_path)

        assert tuple(report["axes"]) == qp.AXIS_NAMES


class TestSeatAgreesWithCorpusLevelAxes:
    """재구현 0의 기계 증거 — 같은 입력에서 좌석과 코퍼스 단위 축의 결론이 같다."""

    @pytest.fixture()
    def corpus(self, tmp_path: Path) -> tuple[Path, list[dict[str, Any]]]:
        rows: list[dict[str, Any]] = []
        for index in range(8):
            rows.append(_clean_problem(f"wm-agree-{index:02d}"))
        rows[1]["verify"]["conditions"] = "solve(x**2 - 1, x) == [1, -1]"
        rows[2]["verify"]["conditions"] = "largest_root(2, 8) == 8"
        rows[3]["question_text"] = "개새끼 같은 조건을 만족하는 x는?"
        rows[4]["answer_explanation"] = "연락처 someone@example.com 참고"
        rows[5]["license"] = None
        rows[6]["source_type"] = ""
        rows[7]["verify"] = {"answer_kind": "finite_count", "conditions": "not dsl"}
        corpus_dir = tmp_path / "corpus" / "problem_bank_agree_v0"
        corpus_dir.mkdir(parents=True)
        _write_jsonl(corpus_dir / "problems.jsonl", rows)
        return tmp_path / "corpus", rows

    def test_equivalence_axis(self, corpus: tuple[Path, list[dict[str, Any]]]) -> None:
        root, rows = corpus
        axis = qp._axis_equivalence_canonicalize(root)
        seats = [qp.judge_item(row).axes["equivalence_canonicalize"] for row in rows]

        applied = sum(1 for r in seats if r.status != "not_applicable")
        violations = sum(1 for r in seats if r.status == "violation")
        assert axis.detail == {"total_conditions_checked": applied, "violations": violations}
        assert violations == 2  # 픽스처가 실제로 두 위반을 밟는다(공허한 일치 방지)

    def test_banned_words_pii_axis(self, corpus: tuple[Path, list[dict[str, Any]]]) -> None:
        root, rows = corpus
        report = banned_words_pii_eval.run(root)
        seats = [qp.judge_item(row).axes["banned_words_pii"] for row in rows]

        # 픽스처는 위반 문항마다 히트 필드가 정확히 1개라 필드 수 = 문항 수로 대조된다.
        assert report.banned_word_hits + report.pii_third_party_hits == sum(
            1 for r in seats if r.status == "violation"
        )
        assert report.banned_word_hits == 1 and report.pii_third_party_hits == 1

    def test_provenance_record_axis(self, corpus: tuple[Path, list[dict[str, Any]]]) -> None:
        root, rows = corpus
        violation = provenance_audit._check_record_fields(root / "problem_bank_agree_v0")
        seats = [qp.judge_item(row).axes["content_provenance"] for row in rows]

        assert violation is not None
        match = re.match(r"(\d+)/(\d+)건", violation.detail)
        assert match is not None
        assert int(match.group(1)) == sum(1 for r in seats if r.status == "violation") == 2
        assert int(match.group(2)) == len(rows)


# ──────────────────────────────────────────────────────────────────────────
# 어댑터 — harness/qa_item_verdicts
# ──────────────────────────────────────────────────────────────────────────
class TestLoaderCoupling:
    def test_review_session_error_tokens_are_classified(self, tmp_path: Path) -> None:
        """로더 사유 토큰이 바뀌면 손상·정체성 부재·중복이 뒤섞인다 — 실물 로더로 동결."""
        path = tmp_path / "q.jsonl"
        path.write_text(
            json.dumps({"slug": "a", "candidate_payload": _clean_problem("a")})
            + "\n"
            + json.dumps({"status": "generation_failed", "candidate_payload": None})
            + "\n"
            + json.dumps({"slug": "a", "candidate_payload": _clean_problem("a")})
            + "\n"
            + "{broken json\n",
            encoding="utf-8",
        )
        _, errors = load_review_items(path)

        damage, no_identity, duplicates = adapter._classify_loader_errors(path, errors)

        assert len(damage) == 1 and "JSONDecodeError" in damage[0]
        assert len(no_identity) == 1 and duplicates == 1


class TestAdapter:
    def test_queue_payload_is_what_gets_judged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """큐 행은 candidate_payload가 판정 대상이다 — 큐 메타가 본문인 척하지 않는다."""
        queue = _write_jsonl(
            tmp_path / "q.jsonl",
            [{**_queue_row(_clean_problem("wm-q1")), "license": None}],
        )
        out = tmp_path / "pred.jsonl"

        code, summary = _run(["--input", str(queue), "--out", str(out)], capsys)

        assert code == 0 and summary["pass"] == 1

    def test_unjudgeable_is_not_written_as_pass_and_is_unevaluated_downstream(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        unjudgeable = _clean_problem("wm-u1")
        unjudgeable["question_text"] = 12345
        queue = _write_jsonl(
            tmp_path / "q.jsonl",
            [_queue_row(_clean_problem("wm-ok")), _queue_row(unjudgeable)],
        )
        out = tmp_path / "pred.jsonl"

        code, summary = _run(["--input", str(queue), "--out", str(out)], capsys)

        assert code == 0
        written = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        assert [row["cu_slug"] for row in written] == ["wm-ok"]
        assert summary["unjudgeable_counts"] == {"axis_unjudgeable": 1}
        entry = summary["unjudgeable"][0]
        assert entry["cu_slug"] == "wm-u1" and "TypeError" in entry["detail"]

        # 혼동행렬 쪽에서 판정 불가 문항은 "미평가"다 — FN도 TN도 되지 않는다.
        golden = freeze_golden_set(
            [
                GoldenItem(
                    cu_slug="wm-u1",
                    anchor_id="A4",
                    label=GoldenLabel.DEFECTIVE,
                    failure_code=GenerationFailureCode.F1,
                    as_found_basis=AsFoundBasis.REJECTED_FAILURE_CODE,
                ),
                GoldenItem(
                    cu_slug="wm-ok",
                    anchor_id="A4",
                    label=GoldenLabel.CLEAN,
                    as_found_basis=AsFoundBasis.EDIT_AWARE_VERDICT,
                ),
            ],
            golden_version="v1",
        )
        predictions, errors = qcm.parse_predictions(written)
        matrix, unevaluated, _ = qcm.evaluate(golden.items, predictions)
        assert errors == []
        assert unevaluated == ("wm-u1",)
        assert (matrix.fn, matrix.tn) == (0, 1)

    def test_identity_and_payload_gaps_are_reported_by_reason(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mismatched = _clean_problem("wm-inner")
        queue = _write_jsonl(
            tmp_path / "q.jsonl",
            [
                _queue_row(_clean_problem("wm-ok")),
                {"status": "generation_failed", "candidate_payload": None},  # 정체성 없음
                _queue_row(None, slug="wm-nopayload"),  # 본문 없음
                _queue_row(mismatched, slug="wm-outer"),  # 행 slug ≠ 본문 slug
            ],
        )
        out = tmp_path / "pred.jsonl"

        code, summary = _run(["--input", str(queue), "--out", str(out)], capsys)

        assert code == 0
        assert summary["unjudgeable_counts"] == {
            "no_cu_slug": 1,
            "no_payload": 1,
            "payload_slug_mismatch": 1,
        }
        assert summary["input_items"] == 4 and summary["judged"] == 1
        assert summary["operating_rate"] == pytest.approx(0.25)

    def test_within_file_duplicate_keeps_the_first_row_like_the_review_session(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """검수자가 본 것은 첫 행이다 — 두 번째 행의 결함이 판정을 바꾸면 안 된다."""
        second = _clean_problem("wm-dup")
        second["license"] = None
        queue = _write_jsonl(
            tmp_path / "q.jsonl", [_queue_row(_clean_problem("wm-dup")), _queue_row(second)]
        )
        out = tmp_path / "pred.jsonl"

        code, summary = _run(["--input", str(queue), "--out", str(out)], capsys)

        assert code == 0 and summary["pass"] == 1 and summary["fail"] == 0
        assert summary["duplicate_rows_within_input"] == 1 and summary["input_items"] == 1

    def test_cross_input_duplicates_merge_if_identical_and_conflict_otherwise(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus_same = _clean_problem("wm-same")
        corpus_diff = _clean_problem("wm-diff")
        queue_diff = _clean_problem("wm-diff")
        queue_diff["question_text"] = "다른 발문"
        queue = _write_jsonl(
            tmp_path / "q.jsonl", [_queue_row(_clean_problem("wm-same")), _queue_row(queue_diff)]
        )
        corpus = _write_jsonl(tmp_path / "problems.jsonl", [corpus_same, corpus_diff])
        out = tmp_path / "pred.jsonl"

        code, summary = _run(
            ["--input", str(queue), "--input", str(corpus), "--out", str(out)], capsys
        )

        assert code == 0
        assert summary["duplicate_identical_across_inputs"] == 1
        assert summary["unjudgeable_counts"] == {"conflicting_payload_across_inputs": 1}
        assert summary["unjudgeable"][0]["cu_slug"] == "wm-diff"
        assert summary["judged"] == 1

    def test_zero_input_items_is_measurement_failure_without_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        empty = tmp_path / "empty.jsonl"
        empty.write_text("\n", encoding="utf-8")
        out = tmp_path / "pred.jsonl"

        code, summary = _run(["--input", str(empty), "--out", str(out)], capsys)

        assert code == 1 and summary["error"] == "no_input_items"
        assert summary["operating_rate"] is None  # 미산출이지 0이 아니다
        assert not out.exists()

    def test_zero_judged_is_measurement_failure_without_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        unjudgeable = _clean_problem("wm-u1")
        unjudgeable["answer_explanation"] = ["목록"]
        queue = _write_jsonl(tmp_path / "q.jsonl", [_queue_row(unjudgeable)])
        out = tmp_path / "pred.jsonl"

        code, summary = _run(["--input", str(queue), "--out", str(out)], capsys)

        assert code == 1 and summary["error"] == "no_judged_items"
        assert summary["input_items"] == 1 and summary["operating_rate"] == 0.0
        assert not out.exists()

    def test_damaged_input_is_input_error_without_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """깨진 행이 하필 fail 문항이었다면 부분 판정은 FN을 조용히 늘린다 — 쓰지 않는다."""
        path = tmp_path / "q.jsonl"
        path.write_text(
            json.dumps(_queue_row(_clean_problem("wm-ok"))) + "\n{broken\n", encoding="utf-8"
        )
        out = tmp_path / "pred.jsonl"

        code, summary = _run(["--input", str(path), "--out", str(out)], capsys)

        assert code == 2 and summary["error"] == "input_damaged"
        assert summary["damage"] and not out.exists()

    def test_missing_input_is_input_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "pred.jsonl"
        code, summary = _run(["--input", str(tmp_path / "nope.jsonl"), "--out", str(out)], capsys)

        assert code == 2 and summary["error"] == "input_missing" and not out.exists()

    def test_summary_declares_engine_scope(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """pass가 "9축 전부 통과"로 읽히지 않게 — 좌석 범위를 산출물이 스스로 말한다."""
        queue = _write_jsonl(tmp_path / "q.jsonl", [_queue_row(_clean_problem("wm-ok"))])
        _, summary = _run(["--input", str(queue), "--out", str(tmp_path / "p.jsonl")], capsys)

        scope = summary["engine_scope"]
        assert scope["item_level_axes"] == list(qp.ITEM_LEVEL_AXES)
        assert set(scope["corpus_level_only_axes"]) == set(qp.CORPUS_LEVEL_ONLY_AXES)
        assert scope["total_axes"] == 9
        assert summary["verdict_source"] == "qa_engine"
        assert summary["axis_status_counts"]["content_provenance"] == {"ok": 1}


class TestRoundTripIntoConfusionMatrix:
    """산출물이 계약 형식인지 — qa_confusion_matrix의 **실제** 파서·CLI가 그대로 먹는다."""

    def test_predictions_parse_without_errors_and_declare_the_judge(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        failing = _clean_problem("wm-fail")
        failing["license"] = None
        queue = _write_jsonl(
            tmp_path / "q.jsonl", [_queue_row(_clean_problem("wm-pass")), _queue_row(failing)]
        )
        out = tmp_path / "pred.jsonl"
        assert _run(["--input", str(queue), "--out", str(out)], capsys)[0] == 0

        rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        predictions, errors = qcm.parse_predictions(rows)

        assert errors == []
        assert {(p.cu_slug, p.passed) for p in predictions} == {
            ("wm-pass", True),
            ("wm-fail", False),
        }
        assert qcm.resolve_verdict_source(predictions) == ("qa_engine", [])

    def test_end_to_end_ledger_row_names_the_qa_engine(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        failing = _clean_problem("wm-fail")
        failing["license"] = None
        queue = _write_jsonl(
            tmp_path / "q.jsonl", [_queue_row(_clean_problem("wm-pass")), _queue_row(failing)]
        )
        predictions_path = tmp_path / "pred.jsonl"
        assert _run(["--input", str(queue), "--out", str(predictions_path)], capsys)[0] == 0

        golden_path = tmp_path / "golden.json"
        ledger_path = tmp_path / "ledger.jsonl"
        json_path = tmp_path / "qa_confusion.json"
        write_golden_set(
            golden_path,
            freeze_golden_set(
                [
                    GoldenItem(
                        cu_slug="wm-fail",
                        anchor_id="A4",
                        label=GoldenLabel.DEFECTIVE,
                        failure_code=GenerationFailureCode.F2,
                        as_found_basis=AsFoundBasis.REJECTED_FAILURE_CODE,
                    ),
                    GoldenItem(
                        cu_slug="wm-pass",
                        anchor_id="A4",
                        label=GoldenLabel.CLEAN,
                        as_found_basis=AsFoundBasis.EDIT_AWARE_VERDICT,
                    ),
                ],
                golden_version="v1",
            ),
        )

        code = qcm.main(
            [
                "--golden",
                str(golden_path),
                "--predictions",
                str(predictions_path),
                "--ledger",
                str(ledger_path),
                "--engine-revision",
                "rev-test",
                "--json",
                str(json_path),
            ]
        )
        capsys.readouterr()

        assert code == 0
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["verdict_source"] == "qa_engine"
        assert payload["matrix"] == {"tp": 1, "fn": 0, "fp": 0, "tn": 1}
        records, errors = load_evaluation_ledger(ledger_path)
        assert errors == [] and len(records) == 1
        assert records[0].verdict_source == "qa_engine" and records[0].snapshot is not None
