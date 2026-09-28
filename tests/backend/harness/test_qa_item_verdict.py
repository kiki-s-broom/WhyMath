"""QA 엔진 문항 단위 좌석 + predictions 어댑터 테스트 (EOS-137 ①④).

동결하는 계약:
  - **문항 좌석 판정 규칙** — fail 우선 · 판정 불가 분리 · 필수 성분(정답 재검산) pass일 때만 pass.
    성분마다 "그 성분이 없으면 무엇이 통과하는가"의 반례를 하나씩 둔다(픽스처가 절을 밟는가).
  - **집계 축 ↔ 문항 좌석 전수 대응** — 집계 9축은 문항 좌석 성분의 출처이거나 투영 불가 사유를
    가진다. 축이 새로 생기면 어느 쪽에도 안 적힌 채 조용히 빠질 수 없다.
  - **축 2와 문항 좌석의 단일 경로** — 집계 축이 문항 함수를 실제로 부른다(사본 금지).
  - **어댑터** — 검수 큐(`candidate_payload`)·코퍼스 행 둘 다 읽고, 첫 등장 판정·본문 불일치 표기·
    판정 불가 분리(predictions에 넣지 않음)·골든 필터·입력 손상 시 무산출(exit 2)·0건 exit 1.
  - **끝에서 끝** — 어댑터 산출물이 `qa_confusion_matrix`에 그대로 들어가 원장 행에 판정기와
    지표가 남는다(평가 원장 첫 행의 형식).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import qa_item_verdict as qiv
from whymath_backend.harness import qa_pipeline as qp
from whymath_backend.harness.banned_words_pii_eval import BANNED_WORDS_KO
from whymath_backend.harness.golden_benchmark import (
    AsFoundBasis,
    GoldenItem,
    GoldenLabel,
    freeze_golden_set,
    load_evaluation_ledger,
    write_golden_set,
)
from whymath_backend.ops import qa_confusion_matrix as qcm
from whymath_backend.schema.enums import GenerationFailureCode

_T0 = datetime(2026, 9, 26, 2, 38, tzinfo=UTC)


def _record(slug: str = "t1", **overrides: Any) -> dict[str, Any]:
    """코퍼스 레코드 직렬화 1행 — 실 코퍼스(`problem_bank_generated_v0` 1행)와 같은 모양."""
    record: dict[str, Any] = {
        "slug": slug,
        "license": "WHYMATH_GENERATED",
        "source_type": "자체생성",
        "question_text": "이차방정식 x^2 - 5x = 0 의 두 근 중 더 큰 근의 값을 구하시오.",
        "answer": "5",
        "answer_explanation": "좌변을 인수분해하면 x(x - 5) = 0 이고, 큰 근은 5이다.",
        "verify": {
            "conditions": "x**2 - 5*x = 0",
            "answer_map": {"x": "5"},
            "solution_steps": ["x**2 - 5*x", "(x)*(x - 5)"],
            "answer_selection": "largest",
        },
    }
    record.update(overrides)
    return record


def _wrong_answer(slug: str = "bad") -> dict[str, Any]:
    """정답이 틀린 문항 — 조건 x²−5x=0에 x=4를 정답으로 적었다(Tier1 fail)."""
    rec = _record(slug)
    rec["verify"] = {**rec["verify"], "answer_map": {"x": "4"}}
    rec["answer"] = "4"
    return rec


def _state(verdict: qp.ItemVerdict, name: str) -> str:
    return next(c.state for c in verdict.checks if c.name == name)


# ──────────────────────────────────────────────────────────────────────────
# 문항 좌석 — 성분별 반례
# ──────────────────────────────────────────────────────────────────────────
class TestJudgeItem:
    def test_clean_record_passes_with_every_component_measured(self) -> None:
        verdict = qp.judge_item(_record(), cu_slug="t1")

        assert verdict.verdict == "pass" and verdict.reason is None
        assert [c.name for c in verdict.checks] == list(qp.ITEM_SEAT_COMPONENTS)
        assert all(c.state == "pass" for c in verdict.checks)

    def test_wrong_answer_fails_on_reverify(self) -> None:
        """answer_reverify가 없으면 이 문항은 pass다 — 수학 오류가 FN이 된다."""
        verdict = qp.judge_item(_wrong_answer(), cu_slug="bad")

        assert verdict.verdict == "fail"
        assert _state(verdict, "answer_reverify") == "fail"
        assert verdict.reason is not None and verdict.reason.startswith("answer_reverify:")

    def test_condition_dsl_violation_fails(self) -> None:
        rec = _record()
        rec["verify"] = {**rec["verify"], "conditions": "largest_root(0, 5) == 5"}
        verdict = qp.judge_item(rec, cu_slug="t1")

        assert _state(verdict, "condition_dsl") == "fail"
        assert verdict.verdict == "fail"

    def test_non_equation_answer_kind_is_not_applicable_not_pass(self) -> None:
        check = qp._item_condition_dsl(
            {"verify": {"answer_kind": "finite_count", "conditions": "x"}}
        )

        assert check.state == "not_applicable"

    def test_missing_provenance_field_fails(self) -> None:
        verdict = qp.judge_item(_record(license=""), cu_slug="t1")

        assert _state(verdict, "record_provenance_fields") == "fail"
        assert verdict.verdict == "fail"

    def test_banned_word_in_explanation_fails(self) -> None:
        word = sorted(BANNED_WORDS_KO)[0]
        verdict = qp.judge_item(_record(answer_explanation=f"설명 {word} 끝"), cu_slug="t1")

        check = next(c for c in verdict.checks if c.name == "banned_words_pii")
        assert check.state == "fail" and check.reason == "answer_explanation:금칙어"
        assert word not in (check.reason or "")  # 원문·매치 값 미출력

    def test_third_party_pii_fails(self) -> None:
        verdict = qp.judge_item(
            _record(question_text="연락처 someone@example.com 으로 답을 보내시오."), cu_slug="t1"
        )

        assert _state(verdict, "banned_words_pii") == "fail"

    def test_no_prose_fields_is_not_applicable(self) -> None:
        rec = _record()
        del rec["question_text"], rec["answer_explanation"]

        assert _state(qp.judge_item(rec, cu_slug="t1"), "banned_words_pii") == "not_applicable"

    def test_missing_verify_material_is_undetermined_not_pass(self) -> None:
        """재검산 재료가 없으면 다른 성분이 전부 pass여도 pass가 아니다(미측정 ≠ 통과)."""
        rec = _record()
        del rec["verify"]
        verdict = qp.judge_item(rec, cu_slug="t1")

        assert verdict.verdict == "undetermined"
        assert _state(verdict, "answer_reverify") == "undetermined"
        assert verdict.reason is not None and "answer_reverify" in verdict.reason

    def test_fail_takes_precedence_over_undetermined(self) -> None:
        rec = _record(license="")
        del rec["verify"]

        assert qp.judge_item(rec, cu_slug="t1").verdict == "fail"

    def test_non_string_prose_field_is_undetermined(self) -> None:
        verdict = qp.judge_item(_record(question_text=123), cu_slug="t1")

        assert _state(verdict, "banned_words_pii") == "undetermined"
        assert verdict.verdict == "undetermined"

    def test_component_exception_is_undetermined_with_type_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_a: object, **_k: object) -> qp.ItemCheck:
            raise RuntimeError("합성 실패")

        monkeypatch.setattr(qp, "_item_record_provenance", _boom)
        verdict = qp.judge_item(_record(), cu_slug="t1")

        check = next(c for c in verdict.checks if c.name == "record_provenance_fields")
        assert check.state == "undetermined" and check.reason == "성분 실행 예외: RuntimeError"
        assert verdict.verdict == "undetermined"

    def test_required_component_not_passed_blocks_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """필수 성분이 not_applicable로 빠져도 pass가 아니다 — 아무것도 못 걸렀다는 통과가 아니다."""
        monkeypatch.setattr(
            qp,
            "_item_answer_reverify",
            lambda _r, *, use_fuzz: qp.ItemCheck("answer_reverify", "not_applicable", "합성"),
        )
        verdict = qp.judge_item(_record(), cu_slug="t1")

        assert verdict.verdict == "undetermined"
        assert verdict.reason == "answer_reverify: 필수 성분 미통과(not_applicable)"

    def test_predictor_id_carries_fuzz_option(self) -> None:
        assert qp.item_seat_predictor(use_fuzz=False) == qp.ITEM_SEAT_PREDICTOR
        assert qp.item_seat_predictor(use_fuzz=True) == qp.ITEM_SEAT_PREDICTOR + "+fuzz"


# ──────────────────────────────────────────────────────────────────────────
# 집계 축 ↔ 문항 좌석 — 전수 대응과 단일 경로
# ──────────────────────────────────────────────────────────────────────────
def _aggregate_axis_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """`build_report`가 실제로 조립하는 축 이름 — 축 함수는 실행하지 않는다."""
    monkeypatch.setattr(
        qp,
        "_run_axis_safely",
        lambda _func, *, axis_name: qp.AxisResult(measured=True, status="ok", detail={}),
    )
    return set(qp.build_report(tmp_path, repo_root=tmp_path)["axes"])


class TestAxisCorrespondence:
    def test_every_aggregate_axis_is_projected_or_explained(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        axes = _aggregate_axis_names(tmp_path, monkeypatch)
        projected = {src for src in qp.ITEM_SEAT_COMPONENTS.values() if src in axes}

        assert projected | set(qp.ITEM_NON_PROJECTABLE_AXES) == axes
        assert not projected & set(qp.ITEM_NON_PROJECTABLE_AXES)  # 양쪽에 동시에 적히지 않는다
        assert all(reason.strip() for reason in qp.ITEM_NON_PROJECTABLE_AXES.values())

    def test_required_component_is_a_seat_component(self) -> None:
        assert qp.ITEM_REQUIRED_COMPONENT in qp.ITEM_SEAT_COMPONENTS

    def test_axis_two_counts_through_the_item_function(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """축 2가 문항 함수를 부르지 않으면(사본으로 돌면) 여기서 0이 나온다."""
        bank = tmp_path / "problem_bank_x_v0"
        bank.mkdir()
        rows = [_record("a"), _record("b"), _record("c")]
        (bank / "problems.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
        seen: list[str] = []
        original = qp._item_condition_dsl

        def _spy(problem: dict[str, Any]) -> qp.ItemCheck:
            seen.append(str(problem["slug"]))
            return original(problem)

        monkeypatch.setattr(qp, "_item_condition_dsl", _spy)
        result = qp._axis_equivalence_canonicalize(tmp_path)

        assert seen == ["a", "b", "c"]
        assert result.detail == {"total_conditions_checked": 3, "violations": 0}


# ──────────────────────────────────────────────────────────────────────────
# 어댑터 — 입력 해석·중복·판정 불가 분리
# ──────────────────────────────────────────────────────────────────────────
def _queue_row(slug: str | None, payload: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
    return {"slug": slug, "status": "rejected_duplicate", "candidate_payload": payload, **extra}


class TestBuildPredictions:
    def test_reads_queue_payload_and_corpus_rows(self) -> None:
        rows = [_queue_row("q1", _record("q1")), _record("c1")]
        result = qiv.build_predictions(rows)

        assert [v.cu_slug for v in result.verdicts] == ["q1", "c1"]
        assert all(v.verdict == "pass" for v in result.verdicts)
        assert result.predictor == qp.ITEM_SEAT_PREDICTOR

    def test_queue_meta_is_not_judged_as_the_problem(self) -> None:
        """본문 없는 큐 행을 코퍼스 행으로 접으면 큐 메타가 문항인 척 판정된다."""
        result = qiv.build_predictions([_queue_row("q1", None)])

        assert result.verdicts == []
        assert [(u.cu_slug, u.category) for u in result.undetermined] == [("q1", "payload_absent")]

    def test_first_occurrence_wins_and_divergent_body_is_reported(self) -> None:
        rows = [
            _queue_row("s", _record("s")),
            _queue_row("s", _wrong_answer("s")),  # 뒤 등장 본문은 판정하지 않는다
            _queue_row("same", _record("same")),
            _queue_row("same", _record("same")),
        ]
        result = qiv.build_predictions(rows)

        assert {v.cu_slug: v.verdict for v in result.verdicts} == {"s": "pass", "same": "pass"}
        assert result.duplicate_rows == 2
        assert result.duplicate_divergent == ["s"]

    def test_missing_slug_rows_are_counted_not_judged(self) -> None:
        result = qiv.build_predictions(
            [_queue_row(None, None, reasons=["생성 실패"]), _record("a")]
        )

        assert result.missing_slug_rows == 1 and result.rows_total == 2
        assert [v.cu_slug for v in result.verdicts] == ["a"]

    def test_undetermined_items_are_kept_out_of_predictions(self) -> None:
        rec = _record("u")
        del rec["verify"]
        result = qiv.build_predictions([rec, _wrong_answer("bad")])

        rows = qiv.prediction_rows(result)
        assert [(r["cu_slug"], r["qa_verdict"]) for r in rows] == [("bad", "fail")]
        (u,) = qiv.undetermined_rows(result)
        assert u["cu_slug"] == "u" and u["category"] == "answer_reverify"
        assert result.summary()["by_verdict"] == {"pass": 0, "fail": 1, "undetermined": 1}

    def test_golden_filter_and_not_in_inputs(self) -> None:
        rows = [_record("g1"), _record("x")]
        result = qiv.build_predictions(rows, golden_slugs=["g1", "g2"])

        assert [v.cu_slug for v in result.verdicts] == ["g1"]
        assert result.outside_golden == 1
        assert [(u.cu_slug, u.category) for u in result.undetermined] == [("g2", "not_in_inputs")]

    def test_prediction_rows_parse_cleanly_in_confusion_matrix(self) -> None:
        result = qiv.build_predictions([_record("a"), _wrong_answer("b")])
        parsed, errors = qcm.parse_predictions(qiv.prediction_rows(result))

        assert errors == []
        assert {(p.cu_slug, p.passed, p.predictor) for p in parsed} == {
            ("a", True, qp.ITEM_SEAT_PREDICTOR),
            ("b", False, qp.ITEM_SEAT_PREDICTOR),
        }


# ──────────────────────────────────────────────────────────────────────────
# CLI — exit 규칙과 무산출
# ──────────────────────────────────────────────────────────────────────────
def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


class TestCli:
    def test_happy_path_writes_both_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        src = tmp_path / "in.jsonl"
        _write_jsonl(src, [_record("a"), _wrong_answer("b")])
        out, und = tmp_path / "p.jsonl", tmp_path / "u.jsonl"

        code = qiv.main(["--input", str(src), "--out", str(out), "--undetermined", str(und)])

        assert code == 0
        summary = json.loads(capsys.readouterr().out)
        assert summary["verdict"] == "ok" and summary["predictions"] == 2
        assert len(out.read_text(encoding="utf-8").splitlines()) == 2
        assert und.exists() and und.read_text(encoding="utf-8") == ""

    def test_parse_failure_writes_nothing(self, tmp_path: Path) -> None:
        src = tmp_path / "in.jsonl"
        src.write_text(json.dumps(_record("a")) + "\n{깨진 줄\n", encoding="utf-8")
        out, und = tmp_path / "p.jsonl", tmp_path / "u.jsonl"

        code = qiv.main(["--input", str(src), "--out", str(out), "--undetermined", str(und)])

        assert code == 2
        assert not out.exists() and not und.exists()

    def test_missing_input_file_is_input_error(self, tmp_path: Path) -> None:
        out = tmp_path / "p.jsonl"
        code = qiv.main(
            ["--input", str(tmp_path / "없음.jsonl"), "--out", str(out), "--undetermined", str(out)]
        )

        assert code == 2 and not out.exists()

    def test_all_undetermined_is_measurement_failure(self, tmp_path: Path) -> None:
        rec = _record("u")
        del rec["verify"]
        src = tmp_path / "in.jsonl"
        _write_jsonl(src, [rec])
        out, und = tmp_path / "p.jsonl", tmp_path / "u.jsonl"

        code = qiv.main(["--input", str(src), "--out", str(out), "--undetermined", str(und)])

        assert code == 1
        assert out.read_text(encoding="utf-8") == ""
        assert json.loads(und.read_text(encoding="utf-8"))["cu_slug"] == "u"

    def test_corrupt_golden_is_input_error(self, tmp_path: Path) -> None:
        src = tmp_path / "in.jsonl"
        _write_jsonl(src, [_record("a")])
        golden = tmp_path / "golden.json"
        golden.write_text("{}", encoding="utf-8")
        out = tmp_path / "p.jsonl"

        code = qiv.main(
            [
                "--input",
                str(src),
                "--golden",
                str(golden),
                "--out",
                str(out),
                "--undetermined",
                str(tmp_path / "u.jsonl"),
            ]
        )

        assert code == 2 and not out.exists()


# ──────────────────────────────────────────────────────────────────────────
# 끝에서 끝 — 어댑터 → 혼동행렬 → 평가 원장 첫 행
# ──────────────────────────────────────────────────────────────────────────
def _golden_item(slug: str, label: GoldenLabel) -> GoldenItem:
    defective = label == GoldenLabel.DEFECTIVE
    return GoldenItem(
        cu_slug=slug,
        anchor_id="A4",
        label=label,
        failure_code=GenerationFailureCode.F2 if defective else None,
        as_found_basis=(
            AsFoundBasis.REJECTED_FAILURE_CODE if defective else AsFoundBasis.EDIT_AWARE_VERDICT
        ),
    )


def test_adapter_output_feeds_confusion_matrix_and_ledger(tmp_path: Path) -> None:
    """골든 v1 모양(검수 큐 · 수용분 + 중복분 · 결함 1 · 정상 2 · 입력에 없는 1) 그대로 관통."""
    golden_path = tmp_path / "golden.json"
    write_golden_set(
        golden_path,
        freeze_golden_set(
            [
                _golden_item("d1", GoldenLabel.DEFECTIVE),
                _golden_item("c1", GoldenLabel.CLEAN),
                _golden_item("c2", GoldenLabel.CLEAN),
                _golden_item("gone", GoldenLabel.CLEAN),
            ],
            golden_version="v1",
            rotation=0,
            frozen_at=_T0,
        ),
    )
    queue = tmp_path / "canary_review_queue.jsonl"
    _write_jsonl(
        queue,
        [
            {"slug": "c1", "status": "corpus_resolved", "candidate_payload": _record("c1")},
            _queue_row("d1", _wrong_answer("d1")),
            _queue_row("c2", _record("c2")),
            _queue_row("c2", _record("c2")),
            _queue_row("x", _record("x")),  # 골든 밖
        ],
    )
    preds, und = tmp_path / "qa_verdicts.jsonl", tmp_path / "qa_undetermined.jsonl"
    assert (
        qiv.main(
            [
                "--input",
                str(queue),
                "--golden",
                str(golden_path),
                "--out",
                str(preds),
                "--undetermined",
                str(und),
            ]
        )
        == 0
    )

    ledger, report_json = tmp_path / "eval_ledger.jsonl", tmp_path / "qa_confusion.json"
    code = qcm.main(
        [
            "--golden",
            str(golden_path),
            "--predictions",
            str(preds),
            "--engine-revision",
            "abc1234",
            "--ledger",
            str(ledger),
            "--json",
            str(report_json),
        ]
    )

    assert code == 0
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert payload["matrix"] == {"tp": 1, "fn": 0, "fp": 0, "tn": 2}
    assert payload["coverage"]["unevaluated"] == 1  # 입력에 없던 골든 1건 — pass로 세지 않았다
    assert payload["predictor"]["id"] == qp.ITEM_SEAT_PREDICTOR
    assert payload["predictor"]["kind"] == "qa_engine"

    records, errors = load_evaluation_ledger(ledger)
    assert errors == [] and len(records) == 1
    (row,) = records
    assert row.predictor == qp.ITEM_SEAT_PREDICTOR and row.engine_revision == "abc1234"
    assert row.metrics is not None
    assert (row.metrics["tp"], row.metrics["fn"], row.metrics["evaluated"]) == (1, 0, 3)
    assert row.metrics["golden_total"] == 4
