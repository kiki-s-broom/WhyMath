"""G3 미측정 3항목 측정기 — `ops/g3_content_measures` (EOS-207). hermetic(DB 0·LLM 0·네트워크 0).

검증 축(판정 분기마다 반례 + 대조군):
  (a) 자동검증 1차 통과율 — 게이트 통과 = 저장 + 중복 거부 · 생성 실패는 분모 밖 · 재진술 검산식
      통과는 우회로 뺀다(대조군: 재계산 검산식) · 우회 판정 불가는 값을 내지 않는다 · 회계 불일치·
      알 수 없는 상태·필수 파일 부재는 측정 실패 · 창 밖 시도 제외
  (b) 힌트 정답 누설 — 입력 없음/힌트 0건 = 측정 대상 부재 · 글자 축 누설 · 값 축 누설 · 짧은 정답
      사람 폴백(None) · L3 누설은 무관용 밖 · 힌트 없는 CU·L1·L2 중 한 단이 빠진 CU는 UNDECIDED · 계약 위반 행은 오류
  (c) 메타 누락 — 필수 필드마다 누락 반례 + 전부 채운 대조군 · seed는 좌석이 받을 때만
  ③ 라벨 대조 — F8인데 힌트 0건 · 기계 누설인데 F8 없음 · 무수정 승인인데 우회 · 판정 파일 없음
  종료 코드 0/1/2 · 실데이터(EOS-197) 첫 측정값 동결
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l4.hint_content.models import Hint, HintReveals, SolutionStepRef
from whymath_backend.ops import g3_content_measures as g3
from whymath_backend.ops import weekly_metrics_report as wmr

_REPO = Path(__file__).resolve().parents[3]
_T0 = "2026-10-27T23:00:00Z"
_SEEDED_MODEL = "qwen3:30b-a3b"  # seed 지원 좌석(실데이터 local 좌석과 같은 모델)
_CLOUD_MODEL = "deepseek/deepseek-v4.1-flash"


# ──────────────────────────────────────────────────────────────────────
# 픽스처 빌더
# ──────────────────────────────────────────────────────────────────────
def _cu(slug: str, conditions: object, answer: str, **over: Any) -> dict[str, Any]:
    var = over.pop("var", "answer")
    row: dict[str, Any] = {
        "problem_id": str(uuid.uuid5(uuid.NAMESPACE_URL, slug)),
        "slug": slug,
        "answer": answer,
        "achievement_standard_codes": ["[12미적Ⅰ-02-05]"],
        "license": "WHYMATH_GENERATED",
        "source_type": "자체생성",
        "generation_type": "FULLY_GENERATED",
        "authored_by": f"llm:{_SEEDED_MODEL}",
        "verify": {"conditions": conditions, "answer_map": {var: answer}},
    }
    row.update(over)
    return row


def _log(slug: str | None, *, success: bool = True, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "log_id": str(uuid.uuid4()),
        "cu_slug": slug,
        "success": success,
        "model_name": _SEEDED_MODEL,
        "prompt_version": "l3.equivalent@sha256:abc",
        "input_sha256": "f" * 64,
        "seed": 7,
        "generated_at": _T0,
    }
    row.update(over)
    return row


_NOT_GENERATED = "provider.generate failed: ReadTimeout: timed out"
_PARSE = "응답 JSON 파싱 실패"
_ASSEMBLY = "후보 조립 실패: ValueError"


def _review(
    slug: str | None,
    status: str,
    *,
    payload: dict[str, Any] | None = None,
    detail: str = _NOT_GENERATED,
) -> dict[str, Any]:
    """검토 행. `generation_failed`의 원인(`detail`)은 `_seat`가 생성 로그 실패 행으로 옮긴다."""
    row: dict[str, Any] = {
        "status": status,
        "slug": slug,
        "candidate_payload": payload,
        "recorded_at": _T0,
    }
    if status == "generation_failed":
        row["_detail"] = detail
    return row


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


def _seat(
    root: Path,
    name: str,
    *,
    cus: list[dict[str, Any]],
    reviews: list[dict[str, Any]] | None = None,
    logs: list[dict[str, Any]] | None = None,
) -> Path:
    """좌석 폴더 1개. 생성 로그를 안 주면 CU마다 성공 1행 + 검토 행마다 1행(회계 일치)을 만든다."""
    seat = root / name
    reviews = reviews or []
    details = [r.pop("_detail", None) for r in reviews]
    if logs is None:
        logs = [_log(c["slug"]) for c in cus]
        for review, detail in zip(reviews, details, strict=True):
            failed = review["status"] == "generation_failed"
            logs.append(
                _log(None if failed else review["slug"], success=not failed, error_detail=detail)
            )
    _write(seat / "cu.jsonl", cus)
    _write(seat / "cu.review.jsonl", reviews)
    _write(seat / "cu.genlog.jsonl", logs)
    return seat


def _baseline_round(root: Path) -> None:
    """재계산 통과 2 · 재진술 통과 1 · 중복(재계산) 1 · needs_review 1 · rejected_gate 1 · 생성 실패 2."""
    cus = [
        _cu("s-recompute-1", "answer == 4*3 + 7", "19"),
        _cu("s-recompute-2", "answer == 7*(0 - 2)", "-14"),
        _cu("s-restate", "n = 3", "3", var="n"),
    ]
    reviews = [
        _review("s-dup", "rejected_duplicate", payload=_cu("s-dup", "answer == 2*5", "10")),
        _review("s-nr", "needs_review"),
        _review("s-rg", "rejected_gate"),
        _review(None, "generation_failed", detail=_NOT_GENERATED),
        _review(None, "generation_failed", detail=_ASSEMBLY),
    ]
    _seat(root, "r1-seatA", cus=cus, reviews=reviews)


def _hint(problem_id: str, content: str, *, level: int = 1) -> Hint:
    return Hint(
        hint_id=f"h-{uuid.uuid4().hex[:8]}",
        solution_step_ref=SolutionStepRef(
            solution_path_id="p1", step_order=1, problem_id=uuid.UUID(problem_id)
        ),
        level=level,  # type: ignore[arg-type]
        reveals=HintReveals.from_flags(
            concept_names=level == 1, step_flow=level >= 2, partial_computation=level == 3
        ),
        content=content,
    )


def _report(root: Path, hints: list[Hint] | None = None, **kw: Any) -> dict[str, Any]:
    round_input = g3.discover_round(root, "r1", review_dir=kw.pop("review_dir", None))
    return g3.build_report(
        round_input,
        hints or [],
        hint_inputs=kw.pop("hint_inputs", 1 if hints else 0),
        hint_errors=kw.pop("hint_errors", []),
    )


# ──────────────────────────────────────────────────────────────────────
# (a) 자동검증 1차 통과율
# ──────────────────────────────────────────────────────────────────────
class TestAutoGate:
    def test_counts_follow_the_section6_definition(self, tmp_path: Path) -> None:
        _baseline_round(tmp_path)
        gate = _report(tmp_path)["auto_gate"]
        assert gate["attempts"] == 8
        assert gate["generation_failed"] == 2
        assert gate["failure_kinds"] == {"assembly_rejected": 1, "not_generated": 1}
        assert gate["evaluated"] == 6
        assert gate["responded"] == 7  # 조립 거부는 분모 안 · 미생성은 분모 밖
        assert gate["passed_raw"] == 4  # 저장 3 + 중복 거부 1(게이트는 통과했다)
        assert gate["bypassed"] == 1  # n = 3
        assert gate["recomputed"] == 3
        assert gate["rate"] == pytest.approx(3 / 7)
        assert gate["rate_raw"] == pytest.approx(4 / 7)
        assert gate["rate_gate_reached"] == pytest.approx(3 / 6)
        assert gate["rate_raw_gate_reached"] == pytest.approx(4 / 6)
        assert gate["attempt_rate"] == pytest.approx(3 / 8)
        assert gate["measured"] is True
        assert 0 < gate["wilson_lower_95"] < 0.5

    def test_duplicate_rejection_counts_as_gate_pass(self, tmp_path: Path) -> None:
        """대조: 중복 거부를 불통과로 세면 분자가 1 줄어든다 — 오케스트레이터 순서(게이트→dedup)."""
        _seat(
            tmp_path,
            "r1-a",
            cus=[],
            reviews=[_review("d", "rejected_duplicate", payload=_cu("d", "answer == 2*5", "10"))],
        )
        gate = _report(tmp_path)["auto_gate"]
        assert (gate["passed_raw"], gate["recomputed"], gate["evaluated"]) == (1, 1, 1)

    def test_restatement_pass_is_excluded_but_recompute_control_is_kept(
        self, tmp_path: Path
    ) -> None:
        _seat(tmp_path, "r1-a", cus=[_cu("x", "n - 24 = 0", "24", var="n")])
        _seat(tmp_path, "r1-b", cus=[_cu("y", "n = 4*6", "24", var="n")])
        gate = _report(tmp_path)["auto_gate"]
        assert gate["bypass_kinds"] == {"recompute": 1, "restatement": 1}
        assert gate["rate"] == pytest.approx(0.5)
        assert gate["rate_raw"] == pytest.approx(1.0)

    @pytest.mark.parametrize(
        ("detail", "kind"),
        [
            (_NOT_GENERATED, "not_generated"),
            (_PARSE, "parse_rejected"),
            (_ASSEMBLY, "assembly_rejected"),
            ("후보 조립 실패: ValidationError", "assembly_rejected"),
            ("알 수 없는 실패", "unknown"),
            (None, "unknown"),
        ],
    )
    def test_failure_classification(self, detail: object, kind: str) -> None:
        assert g3.classify_failure(detail) == kind

    @pytest.mark.parametrize(
        ("detail", "responded"), [(_PARSE, 2), (_ASSEMBLY, 2), (_NOT_GENERATED, 1)]
    )
    def test_deterministic_rejection_is_in_denominator_but_transport_failure_is_not(
        self, tmp_path: Path, detail: str, responded: int
    ) -> None:
        _seat(
            tmp_path,
            "r1-a",
            cus=[_cu("r", "answer == 2+3", "5")],
            reviews=[_review(None, "generation_failed", detail=detail)],
        )
        gate = _report(tmp_path)["auto_gate"]
        assert gate["responded"] == responded
        assert gate["rate"] == pytest.approx(1 / responded)

    def test_all_responses_rejected_before_gate_does_not_crash_weekly(self, tmp_path: Path) -> None:
        """확인 리뷰 P2 반례 — 응답이 전부 파싱·조립 거부면 게이트 도달 0건(분모 0). 주간 원장의
        사유 문자열이 None을 `:.4f`로 찍다 TypeError로 죽으면 안 된다(값은 0, 도달 기준은 산출 불가)."""
        seat = _seat(
            tmp_path,
            "r1-a",
            cus=[],
            reviews=[
                _review(None, "generation_failed", detail=_PARSE),
                _review(None, "generation_failed", detail=_ASSEMBLY),
            ],
        )
        gate = _report(tmp_path)["auto_gate"]
        assert (gate["measured"], gate["evaluated"], gate["responded"]) == (True, 0, 2)
        assert gate["rate_gate_reached"] is None
        kpi = wmr.auto_gate_kpi_from_run_dirs(
            [seat],
            week_start=datetime(2026, 10, 27, tzinfo=UTC),
            week_end=datetime(2026, 10, 28, tzinfo=UTC),
        )
        assert (kpi.measured, kpi.value) == (True, 0.0)
        assert kpi.reason is not None and "게이트 도달 기준 산출 불가(분모 0)" in kpi.reason

    def test_unclassified_failure_withholds_the_value(self, tmp_path: Path) -> None:
        _seat(
            tmp_path,
            "r1-a",
            cus=[_cu("r", "answer == 2+3", "5")],
            reviews=[_review(None, "generation_failed", detail="갑자기 다른 오류")],
        )
        gate = _report(tmp_path)["auto_gate"]
        assert gate["measured"] is False and gate["rate"] is None and gate["rate_raw"] is None
        assert "원인 분류 불가" in gate["reason"]

    def test_slug_level_accounting_catches_swapped_rows(self, tmp_path: Path) -> None:
        """행 수는 맞는데 slug가 다르다 — 행 수 대조만으로는 통과하는 반례."""
        _seat(
            tmp_path,
            "r1-a",
            cus=[_cu("a", "answer == 2+3", "5")],
            logs=[_log("other")],
        )
        gate = _report(tmp_path)["auto_gate"]
        assert any("slug 단위" in e for e in gate["errors"])
        assert gate["measured"] is False

    def test_failure_count_accounting(self, tmp_path: Path) -> None:
        _seat(
            tmp_path,
            "r1-a",
            cus=[_cu("a", "answer == 2+3", "5")],
            reviews=[_review(None, "generation_failed")],
            logs=[_log("a")],  # 실패 호출 0건 ↔ generation_failed 1행
        )
        gate = _report(tmp_path)["auto_gate"]
        assert any("실패 호출 0건" in e for e in gate["errors"])

    def test_undecidable_bypass_withholds_the_value(self, tmp_path: Path) -> None:
        _seat(tmp_path, "r1-a", cus=[_cu("u", "answer > 0", "5"), _cu("r", "answer == 2+3", "5")])
        gate = _report(tmp_path)["auto_gate"]
        assert gate["bypass_undecided"] == 1
        assert gate["measured"] is False
        assert gate["rate"] is None
        assert "[0.5000, 1.0000]" in gate["reason"]

    def test_accounting_mismatch_is_measurement_failure(self, tmp_path: Path) -> None:
        _seat(
            tmp_path,
            "r1-a",
            cus=[_cu("a", "answer == 2+3", "5")],
            logs=[_log("a"), _log(None, success=False, error_detail=_NOT_GENERATED)],
        )
        report = _report(tmp_path)
        assert report["auto_gate"]["measured"] is False
        assert any("회계 불일치" in e for e in report["auto_gate"]["errors"])
        assert report["exit_code"] == g3.EXIT_UNMEASURED

    def test_unknown_status_is_measurement_failure(self, tmp_path: Path) -> None:
        _seat(tmp_path, "r1-a", cus=[], reviews=[_review("z", "accepted_maybe")], logs=[_log("z")])
        gate = _report(tmp_path)["auto_gate"]
        assert any("알 수 없는 상태" in e for e in gate["errors"])
        assert gate["measured"] is False

    def test_missing_genlog_file_is_input_error(self, tmp_path: Path) -> None:
        seat = _seat(tmp_path, "r1-a", cus=[_cu("a", "answer == 2+3", "5")])
        (seat / "cu.genlog.jsonl").unlink()
        report = _report(tmp_path)
        assert any("cu.genlog.jsonl 없음" in e for e in report["input_errors"])
        assert report["exit_code"] == g3.EXIT_UNMEASURED

    def test_broken_json_line_is_input_error(self, tmp_path: Path) -> None:
        seat = _seat(tmp_path, "r1-a", cus=[_cu("a", "answer == 2+3", "5")])
        with (seat / "cu.review.jsonl").open("a", encoding="utf-8") as fh:
            fh.write("{not json\n")
        report = _report(tmp_path)
        assert any("JSONDecodeError" in e for e in report["input_errors"])

    def test_zero_evaluated_is_not_a_zero_rate(self, tmp_path: Path) -> None:
        _seat(tmp_path, "r1-a", cus=[], reviews=[_review(None, "generation_failed")])
        gate = _report(tmp_path)["auto_gate"]
        assert gate["evaluated"] == 0
        assert gate["rate"] is None
        assert "분모 0" in gate["reason"]

    def test_no_seat_dir_is_measurement_failure(self, tmp_path: Path) -> None:
        (tmp_path / "r1-review").mkdir()
        report = _report(tmp_path)
        assert any("좌석 폴더가 0개" in e for e in report["input_errors"])
        assert report["exit_code"] == g3.EXIT_UNMEASURED

    def test_window_excludes_attempts_outside(self, tmp_path: Path) -> None:
        from datetime import UTC, datetime

        _baseline_round(tmp_path)
        run = g3.load_run_dir(tmp_path / "r1-seatA")
        inside = g3.measure_auto_gate(
            [run], window=(datetime(2026, 10, 27, tzinfo=UTC), datetime(2026, 10, 28, tzinfo=UTC))
        )
        outside = g3.measure_auto_gate(
            [run], window=(datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC))
        )
        assert (inside.attempts, inside.outside_window) == (8, 0)
        assert (outside.attempts, outside.outside_window) == (0, 8)
        assert outside.rate is None


# ──────────────────────────────────────────────────────────────────────
# (b) 힌트 정답 누설
# ──────────────────────────────────────────────────────────────────────
class TestHintLeak:
    def _round(self, root: Path) -> dict[str, str]:
        # 두 자리 정답만 쓴다 — 한 자리 정답(`3`)은 글자 축이 유보해 대조군이 사람 폴백이 된다.
        cus = [_cu("h-14", "answer == 7*(0 - 2)", "-14"), _cu("h-13", "answer == 10 + 3", "13")]
        _seat(root, "r1-a", cus=cus)
        return {c["slug"]: c["problem_id"] for c in cus}

    def test_no_hint_input_is_not_measurable_not_zero(self, tmp_path: Path) -> None:
        self._round(tmp_path)
        hint = _report(tmp_path)["hint_leak"]
        assert hint["status"] == "NOT_MEASURABLE"
        assert hint["hints_total"] == 0
        assert "누설 0이 아니다" in hint["reason"]
        assert hint["semantic_axis"] == "NOT_MEASURED"

    def test_text_axis_leak_fails(self, tmp_path: Path) -> None:
        pids = self._round(tmp_path)
        hints = [
            _hint(pids["h-14"], "y절편은 -14가 돼요"),
            _hint(pids["h-13"], "기울기부터 구해 보면 어때요?"),
        ]
        hint = _report(tmp_path, hints)["hint_leak"]
        assert hint["leaked_l12"] == 1
        assert hint["status"] == "FAIL"

    def test_value_axis_leak_fails(self, tmp_path: Path) -> None:
        pids = self._round(tmp_path)
        hints = [
            _hint(pids["h-14"], "식 7*(0 - 2)를 계산해 보세요", level=2),
            _hint(pids["h-13"], "기울기부터 구해 보면 어때요?"),
        ]
        hint = _report(tmp_path, hints)["hint_leak"]
        judged = hint["per_cu"]["h-14"]["judged"][0]
        assert judged["value_verdict"] == "exposed"
        assert hint["status"] == "FAIL"

    def test_short_answer_goes_to_human_fallback(self, tmp_path: Path) -> None:
        cus = [_cu("h-14", "answer == 7*(0 - 2)", "-14"), _cu("h-3", "answer == 1 + 2", "3")]
        _seat(tmp_path, "r1-a", cus=cus)
        hints = [
            _hint(cus[0]["problem_id"], "접선의 기울기부터 구해 볼까요?"),
            _hint(cus[1]["problem_id"], "3단계로 나눠 생각해 봐요"),  # 정답 3 — 글자 축 유보
        ]
        hint = _report(tmp_path, hints)["hint_leak"]
        assert (hint["clean_l12"], hint["undecided_l12"]) == (1, 1)
        assert hint["status"] == "UNDECIDED"

    def test_clean_control_passes_machine_axes_only(self, tmp_path: Path) -> None:
        pids = self._round(tmp_path)
        hints = [
            _hint(pids["h-14"], "접선의 기울기부터 구해 볼까요?"),
            _hint(pids["h-14"], "접점을 먼저 정해 봐요", level=2),
            _hint(pids["h-13"], "도함수를 먼저 떠올려 봐요"),
            _hint(pids["h-13"], "두 수를 차례로 더해 봐요", level=2),
        ]
        hint = _report(tmp_path, hints)["hint_leak"]
        assert (hint["cu_without_l12"], hint["status"]) == (0, "PASS")  # 대조군 — L1·L2 각각 있음
        assert hint["semantic_axis"] == "NOT_MEASURED"  # 기계 clean ≠ 의미 누설 0

    def test_l3_leak_is_counted_outside_zero_tolerance(self, tmp_path: Path) -> None:
        pids = self._round(tmp_path)
        hints = [
            _hint(pids["h-14"], "접선의 기울기부터 구해 볼까요?"),
            _hint(pids["h-14"], "접점을 먼저 정해 봐요", level=2),
            _hint(pids["h-14"], "y절편은 -14가 돼요", level=3),
            _hint(pids["h-13"], "도함수를 먼저 떠올려 봐요"),
            _hint(pids["h-13"], "두 수를 차례로 더해 봐요", level=2),
        ]
        hint = _report(tmp_path, hints)["hint_leak"]
        assert (hint["leaked_l12"], hint["leaked_l3"]) == (0, 1)
        assert hint["status"] == "PASS"

    def test_cu_without_hints_keeps_axis_undecided(self, tmp_path: Path) -> None:
        pids = self._round(tmp_path)
        hint = _report(tmp_path, [_hint(pids["h-14"], "기울기부터 구해 볼까요?")])["hint_leak"]
        assert hint["cu_without_hints"] == 1
        assert hint["status"] == "UNDECIDED"

    def test_l3_only_round_is_not_measurable(self, tmp_path: Path) -> None:
        """리뷰 P1 반례 — L1·L2를 하나도 판정하지 않았는데 PASS가 나면 안 된다."""
        cu = _cu("only", "answer == 10 + 3", "13")
        _seat(tmp_path, "r1-a", cus=[cu])
        hint = _report(tmp_path, [_hint(cu["problem_id"], "도함수를 먼저 떠올려 봐요", level=3)])[
            "hint_leak"
        ]
        assert (hint["judged_l12"], hint["status"]) == (0, "NOT_MEASURABLE")

    def test_cu_with_only_l3_hint_keeps_axis_undecided(self, tmp_path: Path) -> None:
        pids = self._round(tmp_path)
        hints = [
            _hint(pids["h-14"], "접선의 기울기부터 구해 볼까요?"),
            _hint(pids["h-14"], "접점을 먼저 정해 봐요", level=2),
            _hint(pids["h-13"], "도함수를 먼저 떠올려 봐요", level=3),
        ]
        hint = _report(tmp_path, hints)["hint_leak"]
        assert (hint["cu_without_l12"], hint["status"]) == (1, "UNDECIDED")

    @pytest.mark.parametrize("present_level", [1, 2])
    def test_cu_with_only_one_of_l1_l2_keeps_axis_undecided(
        self, tmp_path: Path, present_level: int
    ) -> None:
        """확인 리뷰 P2 반례 — L1만(또는 L2만) 있는 CU는 나머지 단의 누설을 모른다(EOS-211 ④)."""
        pids = self._round(tmp_path)
        hints = [
            _hint(pids["h-14"], "접선의 기울기부터 구해 볼까요?"),
            _hint(pids["h-14"], "접점을 먼저 정해 봐요", level=2),
            _hint(pids["h-13"], "도함수를 먼저 떠올려 봐요", level=present_level),
        ]
        hint = _report(tmp_path, hints)["hint_leak"]
        assert (hint["leaked_l12"], hint["cu_without_l12"]) == (0, 1)
        assert hint["status"] == "UNDECIDED"
        assert "L1·L2를 모두 갖추지 못한 CU 1건" in hint["reason"]

    def test_unmatched_hint_keeps_axis_undecided_and_is_printed(self, tmp_path: Path) -> None:
        """리뷰 P1 반례 — 다른 문항의 problem_id에 붙은 누설 힌트가 조용히 사라지면 안 된다."""
        pids = self._round(tmp_path)
        stray = str(uuid.uuid5(uuid.NAMESPACE_URL, "not-in-round"))
        hints = [
            _hint(pids["h-14"], "접선의 기울기부터 구해 볼까요?"),
            _hint(pids["h-13"], "도함수를 먼저 떠올려 봐요"),
            _hint(stray, "y절편은 -14가 돼요"),
        ]
        report = _report(tmp_path, hints)
        assert (report["hint_leak"]["unmatched_hints"], report["hint_leak"]["status"]) == (
            1,
            "UNDECIDED",
        )
        assert "HINT_UNMATCHED=1" in g3.render_lines(report)

    def test_invalid_hint_row_is_input_error(self, tmp_path: Path) -> None:
        self._round(tmp_path)
        bad = tmp_path / "hints.jsonl"
        bad.write_text(json.dumps({"hint_id": "x", "level": 4}) + "\n", encoding="utf-8")
        hints, errors = g3.load_hints([bad])
        assert hints == [] and any("ValidationError" in e for e in errors)
        report = _report(tmp_path, [], hint_inputs=1, hint_errors=errors)
        assert report["hint_leak"]["status"] == "NOT_MEASURABLE"

    def test_hints_jsonl_round_trip_via_cli(self, tmp_path: Path) -> None:
        pids = self._round(tmp_path)
        path = tmp_path / "hints.jsonl"
        rows = [
            _hint(pids["h-14"], "y절편은 -14가 돼요").model_dump(mode="json"),
            _hint(pids["h-13"], "도함수를 먼저 떠올려 봐요").model_dump(mode="json"),
        ]
        _write(path, rows)
        code = g3.main(["--round", "r1", "--runs-root", str(tmp_path), "--hints-jsonl", str(path)])
        assert code == g3.EXIT_VIOLATION


# ──────────────────────────────────────────────────────────────────────
# (c) 메타 누락
# ──────────────────────────────────────────────────────────────────────
class TestMeta:
    def test_complete_control_passes(self, tmp_path: Path) -> None:
        _seat(tmp_path, "r1-a", cus=[_cu("m", "answer == 2+3", "5")])
        meta = _report(tmp_path)["meta"]
        assert (meta["status"], meta["cu_missing"], meta["seed_checked"]) == ("PASS", 0, 1)

    @pytest.mark.parametrize(
        ("field_name", "blank"),
        [
            ("achievement_standard_codes", []),
            ("achievement_standard_codes", [" "]),
            ("license", None),
            ("source_type", ""),
            ("generation_type", None),
            ("authored_by", "  "),
        ],
    )
    def test_each_record_field_missing_fails(
        self, tmp_path: Path, field_name: str, blank: object
    ) -> None:
        _seat(tmp_path, "r1-a", cus=[_cu("m", "answer == 2+3", "5", **{field_name: blank})])
        meta = _report(tmp_path)["meta"]
        assert meta["status"] == "FAIL"
        assert meta["missing_by_field"] == {field_name: 1}

    @pytest.mark.parametrize("field_name", ["model_name", "prompt_version", "input_sha256"])
    def test_each_genlog_field_missing_fails(self, tmp_path: Path, field_name: str) -> None:
        _seat(
            tmp_path,
            "r1-a",
            cus=[_cu("m", "answer == 2+3", "5")],
            logs=[_log("m", **{field_name: None})],
        )
        meta = _report(tmp_path)["meta"]
        assert meta["missing_by_field"] == {f"genlog.{field_name}": 1}

    def test_unlinked_cu_fails(self, tmp_path: Path) -> None:
        _seat(tmp_path, "r1-a", cus=[_cu("m", "answer == 2+3", "5")], logs=[_log("other")])
        meta = _report(tmp_path)["meta"]
        assert meta["missing_by_field"] == {"genlog.linked_success_call": 1}

    def test_failed_call_does_not_link(self, tmp_path: Path) -> None:
        """성공 호출만 CU를 만든다 — 실패 호출의 cu_slug로는 링크되지 않는다."""
        _seat(
            tmp_path, "r1-a", cus=[_cu("m", "answer == 2+3", "5")], logs=[_log("m", success=False)]
        )
        assert _report(tmp_path)["meta"]["missing_by_field"] == {"genlog.linked_success_call": 1}

    def test_seed_required_only_on_seeded_seats(self, tmp_path: Path) -> None:
        _seat(
            tmp_path,
            "r1-a",
            cus=[_cu("s1", "answer == 2+3", "5"), _cu("s2", "answer == 2+4", "6")],
            logs=[_log("s1", seed=None), _log("s2", seed=None, model_name=_CLOUD_MODEL)],
        )
        meta = _report(tmp_path)["meta"]
        assert meta["missing_by_field"] == {"genlog.seed": 1}  # s1만(seed 지원 좌석)
        assert meta["seed_not_applicable_by_model"] == {f"{_CLOUD_MODEL}(미상)": 1}


# ──────────────────────────────────────────────────────────────────────
# ③ 라벨 대조 · 종료 코드
# ──────────────────────────────────────────────────────────────────────
def _verdicts(root: Path, rows: list[dict[str, Any]]) -> None:
    _write(root / "r1-review" / "canary_review_verdicts.jsonl", rows)


class TestLabelCrosscheck:
    def test_f8_on_cu_without_hints_is_a_preserved_mismatch(self, tmp_path: Path) -> None:
        _seat(tmp_path, "r1-a", cus=[_cu("dup", "answer == 2+3", "5")])
        _verdicts(
            tmp_path,
            [
                {
                    "slug": "dup",
                    "verdict": "rejected",
                    "failure_code": "F8",
                    "failure_note": "중복입니다",
                }
            ],
        )
        cross = _report(tmp_path)["label_crosscheck"]
        assert cross["mismatches"][0]["kind"] == "F8_label_without_machine_hint_leak"
        row = cross["rows"][0]
        assert (row["label_failure_code"], row["machine_hints"]) == ("F8", 0)  # 둘 다 보존
        assert row["label_note_first_line"] == "중복입니다"

    def test_machine_leak_without_f8_is_a_mismatch(self, tmp_path: Path) -> None:
        cu = _cu("lk", "answer == 7*(0-2)", "-14")
        _seat(tmp_path, "r1-a", cus=[cu])
        _verdicts(tmp_path, [{"slug": "lk", "verdict": "approved", "failure_code": None}])
        cross = _report(tmp_path, [_hint(cu["problem_id"], "y절편은 -14가 돼요")])[
            "label_crosscheck"
        ]
        assert [m["kind"] for m in cross["mismatches"]] == ["machine_hint_leak_without_F8"]

    @pytest.mark.parametrize(("levels", "expected"), [((1,), None), ((2,), None), ((1, 2), False)])
    def test_machine_flag_is_unknown_when_cu_lacks_l1_or_l2(
        self, tmp_path: Path, levels: tuple[int, ...], expected: bool | None
    ) -> None:
        """재리뷰 P3 반례 — 한 단만 clean인 CU를 "기계: 누설 없음(False)"으로 적으면 모르는 것을
        아니라고 적는 것이다. 대조군 = L1·L2 둘 다 clean이면 False."""
        cu = _cu("one", "answer == 20+5", "25")
        _seat(tmp_path, "r1-a", cus=[cu])
        _verdicts(tmp_path, [{"slug": "one", "verdict": "rejected", "failure_code": "F8"}])
        hints = [_hint(cu["problem_id"], "두 수를 차례로 더해 봐요", level=lv) for lv in levels]
        cross = _report(tmp_path, hints)["label_crosscheck"]
        assert cross["rows"][0]["machine_hint_leak_l12"] is expected
        assert cross["mismatches"][0]["detail"].endswith(f"L1·L2 기계 판정 {expected}")

    def test_approved_with_bypassed_verification_is_a_mismatch(self, tmp_path: Path) -> None:
        _seat(tmp_path, "r1-a", cus=[_cu("ok", "n = 5", "5", var="n")])
        _verdicts(tmp_path, [{"slug": "ok", "verdict": "approved", "failure_code": None}])
        cross = _report(tmp_path)["label_crosscheck"]
        assert [m["kind"] for m in cross["mismatches"]] == ["approved_with_bypassed_verification"]
        assert cross["crosstab_verdict_x_bypass"] == {"approved×restatement": 1}

    def test_recompute_approved_control_has_no_mismatch(self, tmp_path: Path) -> None:
        _seat(tmp_path, "r1-a", cus=[_cu("ok", "n = 2+3", "5", var="n")])
        _verdicts(tmp_path, [{"slug": "ok", "verdict": "approved", "failure_code": None}])
        assert _report(tmp_path)["label_crosscheck"]["mismatches"] == []

    def test_absent_verdict_file_is_reported_not_performed(self, tmp_path: Path) -> None:
        _seat(tmp_path, "r1-a", cus=[_cu("ok", "n = 2+3", "5", var="n")])
        cross = _report(tmp_path)["label_crosscheck"]
        assert cross["performed"] is False

    def test_explicit_review_dir_without_file_is_input_error(self, tmp_path: Path) -> None:
        _seat(tmp_path, "r1-a", cus=[_cu("ok", "n = 2+3", "5", var="n")])
        report = _report(tmp_path, review_dir=tmp_path / "nowhere")
        assert any("--review-dir" in e for e in report["input_errors"])


class TestExitCodes:
    def _complete(self, root: Path) -> list[Hint]:
        cu = _cu("ok", "answer == 20+5", "25")
        _seat(root, "r1-a", cus=[cu])
        return [
            _hint(cu["problem_id"], "도함수를 먼저 떠올려 봐요"),
            _hint(cu["problem_id"], "두 수를 차례로 더해 봐요", level=2),
        ]

    def test_pass_when_all_three_measured_clean(self, tmp_path: Path) -> None:
        assert _report(tmp_path, self._complete(tmp_path))["exit_code"] == g3.EXIT_PASS

    def test_meta_violation_is_exit_1(self, tmp_path: Path) -> None:
        cu = _cu("ok", "answer == 20+5", "25", license=None)
        _seat(tmp_path, "r1-a", cus=[cu])
        hints = [_hint(cu["problem_id"], "도함수를 먼저 떠올려 봐요")]
        assert _report(tmp_path, hints)["exit_code"] == g3.EXIT_VIOLATION

    def test_missing_hints_is_exit_2(self, tmp_path: Path) -> None:
        self._complete(tmp_path)
        assert _report(tmp_path)["exit_code"] == g3.EXIT_UNMEASURED

    def test_cli_writes_json_and_key_value_lines(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        hints = self._complete(tmp_path)
        hints_path = tmp_path / "h.jsonl"
        _write(hints_path, [h.model_dump(mode="json") for h in hints])
        out_json = tmp_path / "out" / "report.json"
        code = g3.main(
            [
                "--round",
                "r1",
                "--runs-root",
                str(tmp_path),
                "--hints-jsonl",
                str(hints_path),
                "--json",
                str(out_json),
            ]
        )
        lines = capsys.readouterr().out.splitlines()
        assert code == g3.EXIT_PASS
        assert "MACHINE_VERDICT=PASS" in lines and "EXIT=0" in lines
        assert "HINT_SEMANTIC_AXIS=NOT_MEASURED" in lines
        assert json.loads(out_json.read_text(encoding="utf-8"))["exit_code"] == 0


# ──────────────────────────────────────────────────────────────────────
# 실데이터 — EOS-197 첫 측정값 동결(판정 근거 문서와 같은 숫자)
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def eos197_report() -> dict[str, Any]:
    round_input = g3.discover_round(_REPO / "data" / "runs", "eos197-a6")
    return g3.build_report(round_input, [], hint_inputs=0, hint_errors=[])


class TestEos197FirstMeasurement:
    @pytest.fixture
    def report(self, eos197_report: dict[str, Any]) -> dict[str, Any]:
        return eos197_report

    def test_auto_gate_first_pass_rate(self, report: dict[str, Any]) -> None:
        gate = report["auto_gate"]
        assert report["input_errors"] == []
        assert gate["status_counts"] == {
            "accepted_stored": 30,
            "generation_failed": 47,
            "needs_review": 44,
            "rejected_duplicate": 5,
            "rejected_gate": 10,
        }
        assert (gate["attempts"], gate["evaluated"], gate["passed_raw"]) == (136, 89, 35)
        assert gate["failure_kinds"] == {
            "assembly_rejected": 11,
            "not_generated": 25,
            "parse_rejected": 11,
        }
        assert gate["responded"] == 111
        assert (gate["bypassed"], gate["recomputed"], gate["bypass_undecided"]) == (22, 13, 0)
        assert gate["rate"] == pytest.approx(13 / 111)
        assert gate["rate_raw"] == pytest.approx(35 / 111)
        assert gate["rate_gate_reached"] == pytest.approx(13 / 89)
        assert gate["rate_raw_gate_reached"] == pytest.approx(35 / 89)

    def test_hint_axis_has_nothing_to_measure(self, report: dict[str, Any]) -> None:
        hint = report["hint_leak"]
        assert (hint["status"], hint["cu_total"], hint["hints_total"]) == ("NOT_MEASURABLE", 30, 0)

    def test_meta_axis(self, report: dict[str, Any]) -> None:
        meta = report["meta"]
        assert (meta["status"], meta["cu_total"], meta["cu_missing"], meta["seed_checked"]) == (
            "PASS",
            30,
            0,
            3,
        )

    def test_f8_labels_disagree_with_machine(self, report: dict[str, Any]) -> None:
        mismatches = report["label_crosscheck"]["mismatches"]
        assert sorted(m["slug"] for m in mismatches) == [
            "wm-gen-calc1-9e4ec39eaadd",
            "wm-gen-calc1-c42808b25a8f",
        ]
        assert {m["kind"] for m in mismatches} == {"F8_label_without_machine_hint_leak"}

    def test_exit_is_unmeasured(self, report: dict[str, Any]) -> None:
        assert report["exit_code"] == g3.EXIT_UNMEASURED
