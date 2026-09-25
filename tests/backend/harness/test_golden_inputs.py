"""[MP-03] 골든 경로 입력 준비 CLI — 제안 목록·앵커 매핑이 판정을 만들지 않고 열거만 하는가.

이 파일이 붙드는 것
------------------
두 산출물은 **판정기의 입력**이다(`golden_promotion_gate --proposal`·`golden_benchmark
--anchor-map`). 입력 생성기가 틀리면 판정기가 아무리 정확해도 결과가 틀린다. 그래서 여기서는
"정상 입력에서 초록"이 아니라 **분기마다 그 분기가 없으면 통과할 반례**를 둔다:

  proposal   — started만 있는 slug·aborted만 있는 slug는 판정이 아니다(제외) · 재검수는 마지막
               종결이 이긴다 · 필터가 실제로 거른다 · 손상 1줄이면 쓰지 않는다(exit 2) ·
               0건은 측정 실패(exit 1) · **게이트가 보는 판정 집합과 정확히 같다**(계약 대조).
  anchor-map — 미매핑 사유 5종 각각의 반례 · 중복 slug는 한 번만 · slug 없는 행은 세고 버림 ·
               손상 1줄이면 쓰지 않는다 · 0건은 측정 실패 · **산출물을 golden_benchmark가 파싱
               실패 0으로 먹는다**(계약 대조) · 입력 바이트 불변.

레지스트리는 **저장소 정본**(`data/corpus/eos_anchor_set_v1/anchors.yaml`)을 그대로 쓴다 — 픽스처
레지스트리를 만들면 실물과 어긋난 코드 체계로 초록이 날 수 있다. 코드 선택은 레지스트리에서
동적으로 뽑아 레지스트리가 바뀌어도 반례의 성질(범위 안·밖·복수)이 유지되게 한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness.golden_benchmark import ANCHOR_IDS, parse_anchor_rows
from whymath_backend.harness.golden_inputs import (
    UNMAPPED_REASONS,
    build_anchor_map,
    main,
    select_proposal,
)
from whymath_backend.harness.golden_promotion_gate import main as gate_main
from whymath_backend.l1.standards.anchor_registry import load_anchor_registry

_REGISTRY = load_anchor_registry()


def _code_in(anchor_id: str) -> str:
    """정본 레지스트리에서 그 앵커의 첫 코드를 뽑는다(하드코딩하지 않는다)."""
    return _REGISTRY.by_id(anchor_id).codes[0]


def _golden_anchor() -> str:
    """골든 어휘 안의 앵커 하나(A4 우선 — MP-02 회차의 실제 앵커)."""
    return "A4" if "A4" in ANCHOR_IDS else sorted(ANCHOR_IDS)[0]


def _out_of_golden_anchor() -> str | None:
    """레지스트리에는 있으나 골든 어휘 밖인 앵커 — 없으면 None(그 반례는 건너뛴다)."""
    extra = sorted(a.id for a in _REGISTRY.anchors if a.id not in ANCHOR_IDS)
    return extra[0] if extra else None


_ABSENT_CODE = "[없는코드99-99]"


def _event(i: int, slug: str, event_type: str, verdict: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "review_session_id": f"00000000-0000-4000-8000-{i:012d}",
        "cu_slug": slug,
        "reviewer_id": "kiki",
        "event_type": event_type,
    }
    if verdict is not None:
        row["verdict"] = verdict
        if verdict == "rejected":
            row["failure_code"] = "F7"
    return row


def _write_jsonl(
    path: Path, rows: list[dict[str, Any]], *, extra_lines: tuple[str, ...] = ()
) -> Path:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    lines.extend(extra_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


# ─────────────────────────────── proposal ───────────────────────────────


def _standard_events(tmp_path: Path) -> Path:
    """승인 2 · 반려 1 · started만 1 · aborted만 1 · 재검수(승인→반려) 1."""
    rows = [
        _event(1, "wm-a", "started"),
        _event(2, "wm-a", "finished", "approved"),
        _event(3, "wm-b", "finished", "rejected"),
        _event(4, "wm-only-started", "started"),
        _event(5, "wm-only-aborted", "aborted"),
        _event(6, "wm-c", "finished", "approved_with_edit"),
        _event(7, "wm-re", "finished", "approved"),
        _event(8, "wm-re", "finished", "rejected"),
    ]
    return _write_jsonl(tmp_path / "events.jsonl", rows)


class TestProposal:
    def test_lists_only_finished_verdicts_in_first_appearance_order(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        events = _standard_events(tmp_path)
        out = tmp_path / "proposal.txt"
        code, summary = _run(["proposal", "--events", str(events), "--out", str(out)], capsys)
        assert code == 0
        assert out.read_text(encoding="utf-8").splitlines() == ["wm-a", "wm-b", "wm-c", "wm-re"]
        assert summary["judged_slugs"] == 4 and summary["selected"] == 4 and summary["written"]

    def test_started_or_aborted_alone_is_not_a_verdict(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """판정 없는 착수·중단을 제안에 넣으면 그것이 곧 '기계가 판정을 대신하는' 형태다."""
        events = _standard_events(tmp_path)
        out = tmp_path / "proposal.txt"
        _run(["proposal", "--events", str(events), "--out", str(out)], capsys)
        listed = set(out.read_text(encoding="utf-8").split())
        assert "wm-only-started" not in listed and "wm-only-aborted" not in listed

    def test_rereview_last_verdict_wins(self) -> None:
        """재검수(승인→반려)는 반려다 — 이전 승인이 남으면 승인 필터에 반려분이 섞인다."""
        verdicts = {"wm-a": "approved", "wm-re": "rejected"}
        assert select_proposal(verdicts, ["approved"]) == ["wm-a"]

    def test_verdict_filter_excludes_other_values(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        events = _standard_events(tmp_path)
        out = tmp_path / "proposal.txt"
        code, summary = _run(
            ["proposal", "--events", str(events), "--out", str(out), "--verdict", "approved"],
            capsys,
        )
        assert code == 0
        assert out.read_text(encoding="utf-8").splitlines() == ["wm-a"]
        assert summary["by_verdict"] == {"approved": 1, "rejected": 2, "approved_with_edit": 1}

    def test_one_damaged_line_writes_nothing_exit_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """잘린 반려 행 하나가 이전 승인을 최신 판정으로 만들 수 있다 — 손상 위에서는 쓰지 않는다."""
        rows = [_event(1, "wm-a", "finished", "approved")]
        events = _write_jsonl(
            tmp_path / "events.jsonl", rows, extra_lines=('{"cu_slug": "wm-a", "event_ty',)
        )
        out = tmp_path / "proposal.txt"
        code, summary = _run(["proposal", "--events", str(events), "--out", str(out)], capsys)
        assert code == 2
        assert not out.exists()
        assert summary["error"] == "input_damaged" and summary["load_errors"]

    def test_missing_events_file_is_input_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "proposal.txt"
        code, summary = _run(
            ["proposal", "--events", str(tmp_path / "nope.jsonl"), "--out", str(out)], capsys
        )
        assert code == 2 and summary["error"] == "input_missing" and not out.exists()

    def test_zero_selection_is_measurement_failure_not_pass(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        events = _write_jsonl(tmp_path / "events.jsonl", [_event(1, "wm-a", "started")])
        out = tmp_path / "proposal.txt"
        code, summary = _run(["proposal", "--events", str(events), "--out", str(out)], capsys)
        assert code == 1 and summary["error"] == "no_selection" and not out.exists()

    def test_proposal_is_exactly_the_gates_judged_set(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """계약 대조 — 제안을 게이트에 넣으면 `no_human_verdict`가 0건이고 분모가 제안 수와 같다.

        제안 생성기와 게이트가 판정을 다르게 읽으면(예: started를 판정으로 세면) 게이트 리포트에
        `no_human_verdict`가 나타난다 — 두 모듈이 한 파일을 같은 판정 집합으로 읽는지 실물로 잰다.
        """
        events = _standard_events(tmp_path)
        proposal = tmp_path / "proposal.txt"
        _, summary = _run(["proposal", "--events", str(events), "--out", str(proposal)], capsys)
        corpus = _write_jsonl(
            tmp_path / "acc.jsonl", [{"slug": s, "review_status": None} for s in ("wm-a", "wm-c")]
        )
        queue = _write_jsonl(tmp_path / "acc.review.jsonl", [])
        audit = _write_jsonl(tmp_path / "audit.jsonl", [])
        report = tmp_path / "gate.json"
        gate_main(
            [
                "--proposal", str(proposal),
                "--review-queue", str(queue),
                "--review-events", str(events),
                "--corpus", str(corpus),
                "--backfill-audit", str(audit),
                "--json", str(report),
            ]
        )  # fmt: skip
        capsys.readouterr()
        gate = json.loads(report.read_text(encoding="utf-8"))
        reasons = {v["slug"]: v["blocked_reason"] for v in gate["verdicts"]}
        assert gate["reviewed"] == summary["selected"] == gate["proposed"]
        assert "no_human_verdict" not in reasons.values()
        # 게이트의 탈락 사유 분포가 실물 구조를 그대로 보여 준다(MP-03 ②의 형태).
        assert reasons == {
            "wm-a": "review_status_not_backfilled",
            "wm-b": "not_in_corpus",
            "wm-c": "review_status_not_backfilled",
            "wm-re": "not_in_corpus",
        }


# ─────────────────────────────── anchor-map ───────────────────────────────


def _queue_row(
    slug: str | None, payload: Any = None, *, with_payload: bool = True
) -> dict[str, Any]:
    row: dict[str, Any] = {"status": "needs_review", "reasons": []}
    if slug is not None:
        row["slug"] = slug
    if with_payload:
        row["candidate_payload"] = payload
    return row


def _payload(*codes: str) -> dict[str, Any]:
    return {"slug": "x", "achievement_standard_codes": list(codes)}


class TestAnchorMap:
    def test_single_anchor_code_maps(self) -> None:
        anchor = _golden_anchor()
        result = build_anchor_map([_queue_row("wm-a", _payload(_code_in(anchor)))], _REGISTRY)
        assert result.rows == [
            {"cu_slug": "wm-a", "anchor_id": anchor, "standard_codes": [_code_in(anchor)]}
        ]
        assert result.unmapped == []

    @pytest.mark.parametrize(
        ("row", "reason"),
        [
            (_queue_row("wm-n", with_payload=False), "no_payload"),
            (_queue_row("wm-n", None), "no_payload"),
            (_queue_row("wm-n", {"slug": "x"}), "no_standard_codes"),
            (_queue_row("wm-n", _payload()), "no_standard_codes"),
            (_queue_row("wm-n", _payload(_ABSENT_CODE)), "code_not_in_registry"),
        ],
    )
    def test_each_unmapped_reason_has_its_counterexample(
        self, row: dict[str, Any], reason: str
    ) -> None:
        assert _REGISTRY.anchor_for_code(_ABSENT_CODE) is None  # 반례의 전제
        result = build_anchor_map([row], _REGISTRY)
        assert result.rows == []
        assert [item["reason"] for item in result.unmapped] == [reason]

    def test_codes_spanning_two_anchors_are_not_guessed(self) -> None:
        """복수 앵커면 어느 한쪽을 고르지 않는다 — 고르는 순간 앵커를 추론한 것이다."""
        first, second = sorted(ANCHOR_IDS)[:2]
        result = build_anchor_map(
            [_queue_row("wm-m", _payload(_code_in(first), _code_in(second)))], _REGISTRY
        )
        assert result.rows == []
        assert result.unmapped[0]["reason"] == "multiple_anchors"
        assert result.unmapped[0]["anchors"] == [first, second]

    def test_anchor_outside_golden_vocabulary_is_not_written(self) -> None:
        """레지스트리 A7·A8은 골든 어휘 밖 — 쓰면 golden_benchmark가 파싱 실패로 전건을 막는다."""
        extra = _out_of_golden_anchor()
        if extra is None:
            pytest.skip("레지스트리에 골든 어휘 밖 앵커가 없다")
        result = build_anchor_map([_queue_row("wm-x", _payload(_code_in(extra)))], _REGISTRY)
        assert result.rows == []
        assert result.unmapped[0]["reason"] == "anchor_out_of_golden_scope"

    def test_same_anchor_codes_twice_is_one_anchor(self) -> None:
        """같은 앵커의 코드 2개는 복수 앵커가 아니다(집합으로 센다)."""
        anchor = next(a for a in _REGISTRY.anchors if a.id in ANCHOR_IDS and len(a.codes) >= 2)
        result = build_anchor_map([_queue_row("wm-a", _payload(*anchor.codes[:2]))], _REGISTRY)
        assert [row["anchor_id"] for row in result.rows] == [anchor.id]

    def test_duplicate_and_missing_slug_rows_are_counted_not_mapped_twice(self) -> None:
        code = _code_in(_golden_anchor())
        rows = [
            _queue_row("wm-a", _payload(code)),
            _queue_row("wm-a", _payload(code)),
            _queue_row(None, _payload(code)),
        ]
        result = build_anchor_map(rows, _REGISTRY)
        assert len(result.rows) == 1
        assert (
            result.duplicate_rows == 1 and result.missing_slug_rows == 1 and result.rows_total == 3
        )

    def test_every_reason_is_declared(self) -> None:
        assert set(UNMAPPED_REASONS) == {
            "no_payload",
            "no_standard_codes",
            "code_not_in_registry",
            "multiple_anchors",
            "anchor_out_of_golden_scope",
        }


class TestAnchorMapCli:
    def _queue(self, tmp_path: Path, *, extra_lines: tuple[str, ...] = ()) -> Path:
        code = _code_in(_golden_anchor())
        rows = [
            _queue_row("wm-a", _payload(code)),
            _queue_row("wm-b", _payload(_ABSENT_CODE)),
            _queue_row("wm-a", _payload(code)),
        ]
        return _write_jsonl(tmp_path / "canary_review_queue.jsonl", rows, extra_lines=extra_lines)

    def test_output_is_consumed_by_golden_benchmark_without_errors(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """계약 대조 — 산출물을 소비자 파서에 그대로 먹인다(파싱 실패 0·행 수 일치)."""
        out = tmp_path / "anchor_map.jsonl"
        code, summary = _run(
            ["anchor-map", "--queue", str(self._queue(tmp_path)), "--out", str(out)], capsys
        )
        assert code == 0 and summary["written"]
        rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        parsed, errors = parse_anchor_rows(rows)
        assert errors == [] and [p.cu_slug for p in parsed] == ["wm-a"]
        assert summary["mapped"] == 1 and summary["distinct_slugs"] == 2
        assert summary["unmapped_counts"] == {"code_not_in_registry": 1}
        assert summary["duplicate_rows"] == 1

    def test_one_damaged_line_writes_nothing_exit_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "anchor_map.jsonl"
        queue = self._queue(tmp_path, extra_lines=('{"slug": "wm-z", "candid',))
        code, summary = _run(["anchor-map", "--queue", str(queue), "--out", str(out)], capsys)
        assert code == 2 and summary["error"] == "input_damaged" and not out.exists()

    def test_zero_mapped_is_measurement_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        queue = _write_jsonl(tmp_path / "q.jsonl", [_queue_row("wm-b", _payload(_ABSENT_CODE))])
        out = tmp_path / "anchor_map.jsonl"
        code, summary = _run(["anchor-map", "--queue", str(queue), "--out", str(out)], capsys)
        assert code == 1 and summary["error"] == "no_mapped_rows" and not out.exists()

    def test_missing_queue_and_broken_registry_are_input_errors(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "anchor_map.jsonl"
        code, summary = _run(
            ["anchor-map", "--queue", str(tmp_path / "nope.jsonl"), "--out", str(out)], capsys
        )
        assert code == 2 and summary["error"] == "input_missing"
        code, summary = _run(
            [
                "anchor-map",
                "--queue", str(self._queue(tmp_path)),
                "--out", str(out),
                "--registry", str(tmp_path / "no_registry.yaml"),
            ],
            capsys,
        )  # fmt: skip
        assert code == 2 and summary["error"] == "registry_load_failed" and not out.exists()

    def test_inputs_are_byte_identical_after_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        queue = self._queue(tmp_path)
        events = _standard_events(tmp_path)
        before = (queue.read_bytes(), events.read_bytes())
        _run(["anchor-map", "--queue", str(queue), "--out", str(tmp_path / "m.jsonl")], capsys)
        _run(["proposal", "--events", str(events), "--out", str(tmp_path / "p.txt")], capsys)
        assert (queue.read_bytes(), events.read_bytes()) == before
