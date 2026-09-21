"""QA 엔진 혼동행렬 CLI — FN 무관용 축·적재율·게이트 변별력 (EOS-60 acceptance ②④⑤).

정본: `ops/qa_confusion_matrix.py`. 검증 축:
  - **혼동행렬 4칸** — positive=defective. 골든 라벨 × QA 판정 조합 4종 전건 실측.
  - **FN 위장 차단** — 예측이 없는 골든 항목을 pass로 간주하지 않는다(미평가 분리 카운트).
    이 계약이 깨지면 FN율이 구조적으로 과소평가된다(골든의 존재 이유 훼손).
  - **Wilson 경계 방향** — recall·precision은 하한, FN율·오검출률은 **상한**(점추정 금지).
  - **미산출 ≠ 0** — clean 0건이면 Precision·오검출률은 미산출이고, 그 지표에 게이트가
    걸리면 통과가 아니라 **측정 실패**(exit 1).
  - **게이트 변별력 양방향** — 통과/미달 양쪽을 실측(변별력 없는 검증 스텝 금지).
  - **재채점 금지 집행** — 같은 골든·다른 리비전은 exit 1, 같은 리비전 재실행은 통과.
  - **내용 KPI 결선표(⑤)** — 착지 표기는 import 가능해야 하고, 미착지분은 좌석 태스크가
    백로그에 실재해야 한다(선언과 실체의 드리프트 동결).

hermetic — tmp_path·픽스처만(파일 I/O 외 부작용 0·LLM/DB/네트워크 0).
"""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from whymath_backend.harness.golden_benchmark import (
    AsFoundBasis,
    EvaluationRecord,
    GoldenItem,
    GoldenLabel,
    append_evaluation_ledger,
    freeze_golden_set,
    load_evaluation_ledger,
    write_golden_set,
)
from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.ops.qa_confusion_matrix import (
    CONTENT_KPI_CONSUMERS,
    Prediction,
    _report_payload,
    build_report,
    evaluate,
    main,
    parse_predictions,
    render_report,
)
from whymath_backend.schema.enums import GenerationFailureCode

_T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _item(
    slug: str,
    label: GoldenLabel,
    *,
    anchor: str = "A4",
    code: GenerationFailureCode | None = None,
) -> GoldenItem:
    return GoldenItem(
        cu_slug=slug,
        anchor_id=anchor,
        label=label,
        failure_code=code if label == GoldenLabel.DEFECTIVE else None,
        as_found_basis=(
            AsFoundBasis.REJECTED_FAILURE_CODE
            if label == GoldenLabel.DEFECTIVE
            else AsFoundBasis.PRE_REVIEW_SNAPSHOT
        ),
    )


def _golden(items: list[GoldenItem], *, version: str = "v1", rotation: int = 0):
    return freeze_golden_set(items, golden_version=version, rotation=rotation, frozen_at=_T0)


class TestConfusionMatrix:
    """혼동행렬 4칸 — positive = defective(걸러져야 하는 쪽)."""

    def test_four_cells_are_assigned_correctly(self) -> None:
        items = [
            _item("tp", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2),
            _item("fn", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F3),
            _item("fp", GoldenLabel.CLEAN),
            _item("tn", GoldenLabel.CLEAN),
        ]
        predictions = [
            Prediction("tp", passed=False),  # 결함을 걸렀다
            Prediction("fn", passed=True),  # 결함을 통과시켰다 ← 무관용
            Prediction("fp", passed=False),  # 무결한데 걸렀다
            Prediction("tn", passed=True),
        ]

        matrix, unevaluated, extraneous = evaluate(items, predictions)

        assert (matrix.tp, matrix.fn, matrix.fp, matrix.tn) == (1, 1, 1, 1)
        assert unevaluated == () and extraneous == ()

    def test_missing_prediction_is_not_counted_as_pass(self) -> None:
        """골든의 존재 이유를 지키는 계약 — 미평가를 pass로 세면 FN율이 구조적으로 낮아진다."""
        items = [_item("a", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F1)]

        matrix, unevaluated, _ = evaluate(items, [])

        assert matrix.fn == 0 and matrix.evaluated == 0
        assert unevaluated == ("a",)

    def test_extraneous_predictions_do_not_pollute_denominator(self) -> None:
        items = [_item("a", GoldenLabel.CLEAN)]
        matrix, _, extraneous = evaluate(
            items, [Prediction("a", passed=True), Prediction("other", passed=False)]
        )

        assert matrix.evaluated == 1
        assert extraneous == ("other",)

    def test_wilson_bound_directions(self) -> None:
        """ "높을수록 좋은" 지표는 하한, "낮을수록 좋은" 지표는 상한 — 방향이 뒤집히면 과신이다."""
        items = [
            _item(f"d{i}", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2) for i in range(4)
        ] + [_item(f"c{i}", GoldenLabel.CLEAN) for i in range(4)]
        predictions = [Prediction(f"d{i}", passed=i == 3) for i in range(4)] + [
            Prediction(f"c{i}", passed=i != 3) for i in range(4)
        ]
        matrix, _, _ = evaluate(items, predictions)

        assert matrix.recall_lower() == pytest.approx(wilson_lower_bound(3, 4))
        assert matrix.fn_rate_upper() == pytest.approx(wilson_upper_bound(1, 4))
        assert matrix.false_alarm_upper() == pytest.approx(wilson_upper_bound(1, 4))
        assert matrix.precision_lower() == pytest.approx(wilson_lower_bound(3, 4))
        # 하한 < 점추정 < 상한 — 작은 표본에서 크게 깎인다(5/5=1.0 과신 차단의 근거).
        assert matrix.recall_lower() < 0.75 < matrix.fn_rate_upper() + 0.75

    def test_undecidable_metrics_are_none_not_zero(self) -> None:
        """clean 라벨 0건(승격 경로 ⓐ·ⓑ 부재 시 정상 상태) → Precision·오검출률 미산출."""
        items = [_item("a", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F1)]
        matrix, _, _ = evaluate(items, [Prediction("a", passed=False)])

        assert matrix.false_alarm_upper() is None
        assert matrix.recall_lower() is not None


class TestReport:
    def test_coverage_reports_wilson_lower_bound(self) -> None:
        items = [
            _item(f"d{i}", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2) for i in range(4)
        ]
        report = build_report(_golden(items), [Prediction("d0", passed=False)])

        assert report.coverage_rate == pytest.approx(0.25)
        assert report.coverage_lower == pytest.approx(wilson_lower_bound(1, 4))
        assert len(report.unevaluated) == 3

    def test_fn_breakdown_by_failure_code(self) -> None:
        """놓친 결함의 코드 분포 — 어떤 결함류를 못 보는지가 다음 교정 대상이다."""
        items = [
            _item("a", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F3),
            _item("b", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F3),
            _item("c", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2),
        ]
        predictions = [
            Prediction("a", passed=True),
            Prediction("b", passed=True),
            Prediction("c", passed=False),
        ]
        report = build_report(_golden(items), predictions)

        assert report.fn_by_failure_code == {"F3": 2}
        assert report.golden_by_failure_code == {"F3": 2, "F2": 1}

    def test_anchor_breakdown_prevents_average_hiding(self) -> None:
        """F-Ⅳ가 앵커 단위 판정이라 평균 은폐를 막는 분해가 필수다."""
        items = [
            _item("a4", GoldenLabel.DEFECTIVE, anchor="A4", code=GenerationFailureCode.F2),
            _item("a5", GoldenLabel.DEFECTIVE, anchor="A5", code=GenerationFailureCode.F2),
        ]
        predictions = [Prediction("a4", passed=False), Prediction("a5", passed=True)]
        report = build_report(_golden(items), predictions)

        by_anchor = {row.anchor_id: row for row in report.by_anchor}
        assert by_anchor["A4"].matrix.tp == 1 and by_anchor["A4"].matrix.fn == 0
        assert by_anchor["A5"].matrix.fn == 1

    def test_render_states_fn_section_and_unenforced_ledger(self) -> None:
        items = [_item("a", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2)]
        rendered = render_report(build_report(_golden(items), [Prediction("a", passed=True)]))

        assert "False Negative" in rendered
        assert "미집행" in rendered  # 원장 미제공 시 재채점 금지 미집행을 상시 자인
        assert "내용 KPI 정답지 확보 현황" in rendered

    def test_render_flags_undecidable_precision(self) -> None:
        items = [_item("a", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2)]
        rendered = render_report(build_report(_golden(items), [Prediction("a", passed=False)]))

        assert "미산출" in rendered
        assert "clean 라벨 0건" in rendered


class TestPredictionParser:
    def test_accepts_string_and_boolean_verdict_forms(self) -> None:
        rows = [
            {"cu_slug": "a", "qa_verdict": "pass"},
            {"slug": "b", "verdict": "FAIL"},
            {"code": "c", "passed": True},
            {"cu_slug": "d", "qa_pass": False},
        ]
        parsed, errors = parse_predictions(rows)

        assert errors == []
        assert [(p.cu_slug, p.passed) for p in parsed] == [
            ("a", True),
            ("b", False),
            ("c", True),
            ("d", False),
        ]

    def test_unknown_verdict_is_an_error_not_a_pass(self) -> None:
        """어휘 밖 판정을 pass로 관용하면 FN이 위장된다 — 실패로 센다."""
        parsed, errors = parse_predictions([{"cu_slug": "a", "verdict": "maybe"}])

        assert parsed == []
        assert len(errors) == 1 and "ValueError" in errors[0]

    def test_missing_identity_is_an_error(self) -> None:
        parsed, errors = parse_predictions([{"verdict": "pass"}])
        assert parsed == [] and len(errors) == 1


class TestContentKpiConsumerTable:
    """집행 별항(⑤) — 결선표와 실체의 드리프트를 기계로 동결한다."""

    def test_all_four_content_kpis_are_declared(self) -> None:
        assert len(CONTENT_KPI_CONSUMERS) == 4
        codes = {code for c in CONTENT_KPI_CONSUMERS for code in c.failure_codes}
        assert GenerationFailureCode.F3 in codes  # 풀이 비약
        assert GenerationFailureCode.F4 in codes  # 성취기준 이탈
        assert GenerationFailureCode.F6 in codes  # 오개념 오연결

    def test_landed_consumers_are_importable(self) -> None:
        """'착지'라고 적힌 채점기는 실제로 import 가능해야 한다(선언≠실체 금지)."""
        for consumer in CONTENT_KPI_CONSUMERS:
            if consumer.consumer_module is not None:
                assert importlib.util.find_spec(consumer.consumer_module) is not None

    def test_seat_tasks_exist_in_backlog(self) -> None:
        """미착지분은 추적 축(좌석 태스크)이 실재해야 한다 — 만료 없는 유예 금지."""
        tasks_dir = _REPO_ROOT / "backlog" / "tasks"
        for consumer in CONTENT_KPI_CONSUMERS:
            assert (tasks_dir / f"{consumer.seat_task}.yaml").exists(), consumer.seat_task


def _write_predictions(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


class TestCli:
    @pytest.fixture()
    def workspace(self, tmp_path: Path) -> tuple[Path, Path]:
        golden_path = tmp_path / "golden.json"
        predictions_path = tmp_path / "predictions.jsonl"
        write_golden_set(
            golden_path,
            _golden(
                [
                    _item("d1", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2),
                    _item("d2", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F3),
                    _item("c1", GoldenLabel.CLEAN),
                    _item("c2", GoldenLabel.CLEAN),
                ]
            ),
        )
        _write_predictions(
            predictions_path,
            [
                {"cu_slug": "d1", "qa_verdict": "fail"},
                {"cu_slug": "d2", "qa_verdict": "pass"},
                {"cu_slug": "c1", "qa_verdict": "pass"},
                {"cu_slug": "c2", "qa_verdict": "pass"},
            ],
        )
        return golden_path, predictions_path

    def test_reports_and_exits_zero_without_gates(self, workspace: tuple[Path, Path]) -> None:
        golden_path, predictions_path = workspace
        assert main(["--golden", str(golden_path), "--predictions", str(predictions_path)]) == 0

    def test_gate_discriminates_both_directions(self, workspace: tuple[Path, Path]) -> None:
        """변별력 양방향 — 같은 입력에서 임계만 바꿔 통과/미달이 갈린다."""
        golden_path, predictions_path = workspace
        base = ["--golden", str(golden_path), "--predictions", str(predictions_path)]

        # FN 1/2 → Wilson 상한은 0.9 근처. 느슨한 임계는 통과, 엄격한 임계는 미달.
        assert main([*base, "--max-fn-upper", "0.99"]) == 0
        assert main([*base, "--max-fn-upper", "0.10"]) == 1

    def test_coverage_gate_uses_wilson_lower_bound(self, tmp_path: Path) -> None:
        golden_path = tmp_path / "golden.json"
        predictions_path = tmp_path / "predictions.jsonl"
        write_golden_set(
            golden_path,
            _golden(
                [
                    _item(f"d{i}", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2)
                    for i in range(4)
                ]
            ),
        )
        _write_predictions(predictions_path, [{"cu_slug": "d0", "qa_verdict": "fail"}])

        code = main(
            [
                "--golden",
                str(golden_path),
                "--predictions",
                str(predictions_path),
                "--min-coverage",
                "0.9",
            ]
        )
        assert code == 1  # 적재율 1/4 — 미평가를 pass로 세지 않으므로 게이트가 잡는다

    def test_gate_on_undecidable_metric_is_measurement_failure(self, tmp_path: Path) -> None:
        """clean 0건인데 오검출률 게이트를 걸면 '통과'가 아니라 측정 실패다."""
        golden_path = tmp_path / "golden.json"
        predictions_path = tmp_path / "predictions.jsonl"
        write_golden_set(
            golden_path,
            _golden([_item("d1", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2)]),
        )
        _write_predictions(predictions_path, [{"cu_slug": "d1", "qa_verdict": "fail"}])

        code = main(
            [
                "--golden",
                str(golden_path),
                "--predictions",
                str(predictions_path),
                "--max-false-alarm-upper",
                "0.05",
            ]
        )
        assert code == 1

    def test_missing_inputs_are_measurement_failures(self, tmp_path: Path) -> None:
        golden_path = tmp_path / "golden.json"
        write_golden_set(
            golden_path,
            _golden([_item("d1", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2)]),
        )

        assert main(["--golden", str(tmp_path / "no.json"), "--predictions", str(golden_path)]) == 1
        assert (
            main(["--golden", str(golden_path), "--predictions", str(tmp_path / "no.jsonl")]) == 1
        )

    def test_no_overlap_is_measurement_failure(self, tmp_path: Path) -> None:
        golden_path = tmp_path / "golden.json"
        predictions_path = tmp_path / "predictions.jsonl"
        write_golden_set(
            golden_path,
            _golden([_item("d1", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2)]),
        )
        _write_predictions(predictions_path, [{"cu_slug": "other", "qa_verdict": "fail"}])

        assert main(["--golden", str(golden_path), "--predictions", str(predictions_path)]) == 1

    def test_parse_failure_blocks_verdict(self, workspace: tuple[Path, Path]) -> None:
        golden_path, predictions_path = workspace
        with predictions_path.open("a", encoding="utf-8") as fp:
            fp.write("{깨진 줄\n")

        assert main(["--golden", str(golden_path), "--predictions", str(predictions_path)]) == 1

    def test_tampered_golden_fails_to_load(self, workspace: tuple[Path, Path]) -> None:
        """라벨 손편집은 무증상으로 통과하지 않는다 — digest 불일치로 로드가 터진다."""
        golden_path, predictions_path = workspace
        payload = json.loads(golden_path.read_text(encoding="utf-8"))
        defective = next(row for row in payload["items"] if row["label"] == "defective")
        defective["label"] = "clean"  # FN 1건을 TN으로 위장하는 방향의 변조
        defective["failure_code"] = None
        golden_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        assert main(["--golden", str(golden_path), "--predictions", str(predictions_path)]) == 1


class TestRescoreLedgerEnforcement:
    """acceptance ③의 집행 지점 — 같은 골든을 다른 엔진 리비전으로 재채점하면 막는다."""

    @pytest.fixture()
    def workspace(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        golden_path = tmp_path / "golden.json"
        predictions_path = tmp_path / "predictions.jsonl"
        ledger_path = tmp_path / "ledger.jsonl"
        write_golden_set(
            golden_path,
            _golden([_item("d1", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2)]),
        )
        _write_predictions(predictions_path, [{"cu_slug": "d1", "qa_verdict": "fail"}])
        return golden_path, predictions_path, ledger_path

    def test_first_evaluation_records_ledger_entry(
        self, workspace: tuple[Path, Path, Path]
    ) -> None:
        golden_path, predictions_path, ledger_path = workspace
        code = main(
            [
                "--golden",
                str(golden_path),
                "--predictions",
                str(predictions_path),
                "--ledger",
                str(ledger_path),
                "--engine-revision",
                "rev-a",
            ]
        )

        assert code == 0
        records, errors = load_evaluation_ledger(ledger_path)
        assert errors == []
        assert len(records) == 1 and records[0].engine_revision == "rev-a"

    def test_same_revision_rerun_is_allowed(self, workspace: tuple[Path, Path, Path]) -> None:
        """재현성(S4) 확인은 재채점이 아니다 — 같은 리비전 재실행은 통과."""
        golden_path, predictions_path, ledger_path = workspace
        argv = [
            "--golden",
            str(golden_path),
            "--predictions",
            str(predictions_path),
            "--ledger",
            str(ledger_path),
            "--engine-revision",
            "rev-a",
        ]
        assert main(argv) == 0
        assert main(argv) == 0

    def test_different_revision_on_same_golden_is_blocked(
        self, workspace: tuple[Path, Path, Path]
    ) -> None:
        golden_path, predictions_path, ledger_path = workspace
        append_evaluation_ledger(
            ledger_path,
            EvaluationRecord(
                digest=json.loads(golden_path.read_text(encoding="utf-8"))["digest"],
                engine_revision="rev-a",
                evaluated_at=_T0,
            ),
        )

        code = main(
            [
                "--golden",
                str(golden_path),
                "--predictions",
                str(predictions_path),
                "--ledger",
                str(ledger_path),
                "--engine-revision",
                "rev-b",
            ]
        )
        assert code == 1

    def test_rotated_golden_is_a_new_set_and_passes(
        self, workspace: tuple[Path, Path, Path]
    ) -> None:
        """교정 후 재판정의 정본 경로 — rotation을 올린 *신규 표본*은 막히지 않는다."""
        golden_path, predictions_path, ledger_path = workspace
        append_evaluation_ledger(
            ledger_path,
            EvaluationRecord(
                digest=json.loads(golden_path.read_text(encoding="utf-8"))["digest"],
                engine_revision="rev-a",
                evaluated_at=_T0,
            ),
        )
        rotated_path = golden_path.parent / "golden_rot1.json"
        write_golden_set(
            rotated_path,
            _golden(
                [_item("d2", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2)], rotation=1
            ),
        )
        _write_predictions(predictions_path, [{"cu_slug": "d2", "qa_verdict": "fail"}])

        code = main(
            [
                "--golden",
                str(rotated_path),
                "--predictions",
                str(predictions_path),
                "--ledger",
                str(ledger_path),
                "--engine-revision",
                "rev-b",
            ]
        )
        assert code == 0

    def test_corrupt_ledger_is_measurement_failure_not_a_free_pass(
        self, workspace: tuple[Path, Path, Path]
    ) -> None:
        """#928 리뷰 P1 — 원장이 깨진 순간이 곧 재채점 금지가 무력해지는 순간이다.

        손상된 줄이 하필 이전 평가 기록(rev-a)이면 `find_rescore_violation`은 빈 이력을 보고
        rev-b를 통과시킨다 — 금지 규율이 그 *증거가 손상된 바로 그 순간에* 사라진다.
        손상 = 판정 불가지 통과가 아니다.
        """
        golden_path, predictions_path, ledger_path = workspace
        digest = json.loads(golden_path.read_text(encoding="utf-8"))["digest"]
        # engine_revision 키가 빠진 손상 줄 — 원래 rev-a 평가 기록이었다고 가정
        ledger_path.write_text(json.dumps({"digest": digest}) + "\n", encoding="utf-8")

        code = main(
            [
                "--golden",
                str(golden_path),
                "--predictions",
                str(predictions_path),
                "--ledger",
                str(ledger_path),
                "--engine-revision",
                "rev-b",
            ]
        )
        assert code == 1

    def test_intact_ledger_with_same_content_passes(
        self, workspace: tuple[Path, Path, Path]
    ) -> None:
        """변별력 대조군 — 같은 시나리오에서 원장이 온전하면 통과한다(위 케이스가 위장이 아님)."""
        golden_path, predictions_path, ledger_path = workspace
        digest = json.loads(golden_path.read_text(encoding="utf-8"))["digest"]
        ledger_path.write_text(
            json.dumps(
                {
                    "digest": digest,
                    "engine_revision": "rev-b",
                    "evaluated_at": _T0.isoformat(),
                }
            )
            + "\n",
            encoding="utf-8",
        )

        code = main(
            [
                "--golden",
                str(golden_path),
                "--predictions",
                str(predictions_path),
                "--ledger",
                str(ledger_path),
                "--engine-revision",
                "rev-b",
            ]
        )
        assert code == 0

    def test_ledger_without_engine_revision_is_measurement_failure(
        self, workspace: tuple[Path, Path, Path]
    ) -> None:
        golden_path, predictions_path, ledger_path = workspace
        code = main(
            [
                "--golden",
                str(golden_path),
                "--predictions",
                str(predictions_path),
                "--ledger",
                str(ledger_path),
            ]
        )
        assert code == 1

    def test_measurement_failure_is_not_recorded_as_a_rescore(self, tmp_path: Path) -> None:
        """측정 실패 회차가 원장에 남으면 다음 정상 회차가 재채점으로 오판된다."""
        golden_path = tmp_path / "golden.json"
        predictions_path = tmp_path / "predictions.jsonl"
        ledger_path = tmp_path / "ledger.jsonl"
        write_golden_set(
            golden_path,
            _golden([_item("d1", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2)]),
        )
        _write_predictions(predictions_path, [{"cu_slug": "other", "qa_verdict": "fail"}])

        assert (
            main(
                [
                    "--golden",
                    str(golden_path),
                    "--predictions",
                    str(predictions_path),
                    "--ledger",
                    str(ledger_path),
                    "--engine-revision",
                    "rev-a",
                ]
            )
            == 1
        )
        records, _ = load_evaluation_ledger(ledger_path)
        assert records == []


class TestJsonOutput:
    def test_json_payload_carries_verdict_inputs(self, tmp_path: Path) -> None:
        """EOS-61 스코어카드의 입력 — 판정치가 기계가 읽는 형태로 나온다."""
        golden_path = tmp_path / "golden.json"
        predictions_path = tmp_path / "predictions.jsonl"
        json_path = tmp_path / "report.json"
        write_golden_set(
            golden_path,
            _golden(
                [
                    _item("d1", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2),
                    _item("c1", GoldenLabel.CLEAN),
                ]
            ),
        )
        _write_predictions(
            predictions_path,
            [{"cu_slug": "d1", "qa_verdict": "pass"}, {"cu_slug": "c1", "qa_verdict": "pass"}],
        )

        assert (
            main(
                [
                    "--golden",
                    str(golden_path),
                    "--predictions",
                    str(predictions_path),
                    "--json",
                    str(json_path),
                ]
            )
            == 0
        )
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["matrix"] == {"tp": 0, "fn": 1, "fp": 0, "tn": 1}
        assert payload["metrics"]["fn_rate_upper"] is not None
        assert payload["golden"]["rotation"] == 0
        assert payload["fn_by_failure_code"] == {"F2": 1}


class TestFailureCodeKeyContract:
    """실패코드 JSON 키 계약(EOS-75) — 키는 코드 **값**(`F1`)이지 파이썬 repr이 아니다.

    검증을 거친 `GoldenItem`은 `use_enum_values=True`라 *우연히* `F1`을 냈다(그래서 기존
    테스트는 `str(enum)` 구현에서도 초록이었다 — 변별력 0). 그 우연을 계약으로 바꾼다:
    검증을 우회해 enum 인스턴스를 든 항목에서도 같은 키가 나와야 하고, 뮤테이션(`str()`로
    되돌리기)에서 이 클래스가 RED여야 한다.
    """

    @staticmethod
    def _constructed(slug: str, code: GenerationFailureCode) -> GoldenItem:
        # model_construct = 검증 우회 → use_enum_values가 적용되지 않아 enum 인스턴스가 남는다
        return GoldenItem.model_construct(
            cu_slug=slug,
            subject_id="math",
            anchor_id="A4",
            label=GoldenLabel.DEFECTIVE,
            failure_code=code,
            as_found_basis=AsFoundBasis.REJECTED_FAILURE_CODE,
        )

    def test_keys_are_code_values_even_when_items_bypass_validation(self) -> None:
        item = self._constructed("a", GenerationFailureCode.F1)
        assert isinstance(item.failure_code, GenerationFailureCode)  # 전제: enum 인스턴스다

        report = build_report(_golden([item]), [Prediction("a", passed=True)])

        assert report.fn_by_failure_code == {"F1": 1}
        assert report.golden_by_failure_code == {"F1": 1}

    def test_json_payload_keys_match_the_contract(self) -> None:
        """JSON 키 전수 = `F1`~`F8` 또는 `(코드 없음)` — 검증 경유·우회 항목을 섞어도."""
        items = [
            _item("a", GoldenLabel.DEFECTIVE, code=GenerationFailureCode.F2),
            self._constructed("b", GenerationFailureCode.F3),
            _item("c", GoldenLabel.DEFECTIVE),  # defective인데 코드 미기재 → "(코드 없음)"
            _item("d", GoldenLabel.CLEAN),
        ]
        predictions = [Prediction(slug, passed=True) for slug in ("a", "b", "c", "d")]

        payload = _report_payload(build_report(_golden(items), predictions))

        for section in ("fn_by_failure_code", "golden_by_failure_code"):
            keys = set(payload[section])
            assert keys == {"F2", "F3", "(코드 없음)"}, section
            for key in keys:
                assert key == "(코드 없음)" or re.fullmatch(
                    r"F[1-8]", key
                ), f"{section} 키가 계약 밖(파이썬 repr 누출?): {key!r}"

    def test_content_kpi_table_counts_enum_backed_golden(self) -> None:
        """결선표(⑤)는 `.value`로 조회한다 — 생산·조회 표기가 갈라지면 정답지가 있어도 0건."""
        item = self._constructed("a", GenerationFailureCode.F1)
        rendered = render_report(build_report(_golden([item]), [Prediction("a", passed=False)]))

        row = next(line for line in rendered.splitlines() if "수학적 오류율" in line)
        assert "| 1건 |" in row, row
