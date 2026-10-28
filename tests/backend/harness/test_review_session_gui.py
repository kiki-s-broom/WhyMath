"""검수 세션 GUI 제어기 — 터미널 세션과의 기록 동일성·이어하기 호환·거부 규칙 (EOS-199).

정본: `harness/review_session_gui.py`. 이 스위트가 동결하는 것:

  1. **기록 동일성(acceptance ②)** — 같은 큐·같은 판정 순서를 터미널 `run_review_session`
     (키 입력 문자열)과 GUI `ReviewController`(같은 시계)에 넣으면 events·verdicts 파일이
     *세션 ID·이벤트 ID·시각 외에* 같다. 시계를 같게 주입하므로 경과 시간까지 같다.
  2. **이어하기 호환(acceptance ③)** — 터미널이 남긴 파일을 GUI가 `--resume`으로 이어받고,
     그 반대도 성립한다.
  3. **거부 규칙** — 반려는 사유 없이 제출되지 않고, 거부된 제출은 아무것도 적지 않는다.
  4. **창 닫기 = 중단** — 열린 항목은 `aborted`로 남고 판정 파일에는 쓰지 않는다.
  5. **헤드리스(acceptance ④)** — 이 스위트는 tkinter 없이 돈다. 큐 0건은 창을 띄우기 전에 exit 1.
  6. **기록 전 거부(리뷰 P1-1)** — 사유 없는 메모·2000자 초과 메모는 쓰기 전에 거부, 스키마 시험
     생성이 최종 안전망. 7. **입력 잠금(P1-2)** — 표시 후 1초 안의 제출 거부(주입 시계), 단축키 0건.
  8. **쓰기 실패(P2-1)** — 잠긴 파일은 사전 점검이 거부, 도중 실패는 정지 + finished 1건 유지.
  9. **다시 보기(◀/▶)** — 판정 파일 순서 이력·경계·다시 보기 중 판정 거부·복귀 시 잠금·입력 보존.

hermetic — tmp_path와 주입된 시계만 쓴다.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from whymath_backend.harness import review_session_gui
from whymath_backend.harness.review_session import ReviewItem, run_review_session
from whymath_backend.harness.review_session_gui import (
    RecordingFailedError,
    ReviewController,
    SubmissionRefusedError,
)
from whymath_backend.schema.enums import GenerationFailureCode

#: 실행마다 달라지는 필드 — 대조에서 뺀다(UUID·벽시계). 경과 시간은 시계를 같게 주입하므로 남긴다.
_VOLATILE = frozenset({"event_id", "review_session_id", "occurred_at", "recorded_at"})
_FIXED_NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def _items(n: int) -> list[ReviewItem]:
    return [
        ReviewItem(
            slug=f"wm-gen-calc1-{i:03d}",
            status="needs_review",
            reasons=("canary",),
            payload={"question_text": f"문항 {i}", "answer": str(i)},
        )
        for i in range(1, n + 1)
    ]


def _clock(step_ns: int = 45_000_000_000):
    ticks = [0]

    def monotonic_ns() -> int:
        value = ticks[0]
        ticks[0] += step_ns
        return value

    return monotonic_ns


def _read(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _stable(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{k: v for k, v in row.items() if k not in _VOLATILE} for row in rows]


def _run_terminal(workdir: Path, items: list[ReviewItem], keystrokes: str, *, resume: bool = False):
    return run_review_session(
        items,
        events_path=workdir / "events.jsonl",
        verdicts_path=workdir / "verdicts.jsonl",
        reviewer_id="kiki",
        stream_in=io.StringIO(keystrokes),
        stream_out=io.StringIO(),
        monotonic_ns=_clock(),
        now_utc=lambda: _FIXED_NOW,
        resume=resume,
    )


def _controller(workdir: Path, items: list[ReviewItem], *, resume: bool = False):
    return ReviewController(
        items,
        events_path=workdir / "events.jsonl",
        verdicts_path=workdir / "verdicts.jsonl",
        reviewer_id="kiki",
        resume=resume,
        monotonic_ns=_clock(),
        now_utc=lambda: _FIXED_NOW,
    )


def _drive(ctl: ReviewController, steps: list[tuple[str, str | None, str | None]]) -> None:
    """GUI가 하는 그대로 — 띄우고(start_current) 판정한다."""
    for action, code, note in steps:
        ctl.start_current()
        ctl.submit(action, failure_code=code, note=note)
    ctl.start_current()  # 다음 항목을 화면에 띄운 상태(창이 그렇게 한다)


#: 승인 · 수정승인(사유 있음) · 수정승인(사유 없음) · 반려(F2) · 보류 · 종료 — 6번째에서 끝난다.
_TERMINAL_KEYS = "a\ne\nF3\n표현 손질\ne\n\n\nr\nF2\n정답 3이 아님\ns\nq\n"
_GUI_STEPS: list[tuple[str, str | None, str | None]] = [
    ("approved", None, None),
    ("approved_with_edit", "F3 — 풀이 논리 비약", "표현 손질"),
    ("approved_with_edit", None, ""),
    ("rejected", "F2 — 정답 불일치", "정답 3이 아님"),
    ("skip", None, None),
    ("quit", None, None),
]


class TestRecordEquivalence:
    """acceptance ② — 같은 판정 순서 → 같은 기록."""

    def test_events_and_verdicts_match_terminal_session(self, tmp_path: Path) -> None:
        items = _items(7)
        term_dir, gui_dir = tmp_path / "term", tmp_path / "gui"
        term_dir.mkdir()
        gui_dir.mkdir()

        term_outcome = _run_terminal(term_dir, items, _TERMINAL_KEYS)
        ctl = _controller(gui_dir, items)
        _drive(ctl, _GUI_STEPS[:-1])
        ctl.submit("quit")
        gui_outcome = ctl.summary()

        term_events = _read(term_dir / "events.jsonl")
        gui_events = _read(gui_dir / "events.jsonl")
        assert [e["event_type"] for e in gui_events] == [e["event_type"] for e in term_events]
        assert _stable(gui_events) == _stable(term_events)
        assert _stable(_read(gui_dir / "verdicts.jsonl")) == _stable(
            _read(term_dir / "verdicts.jsonl")
        )
        assert gui_outcome == term_outcome

    def test_expected_shape_of_the_shared_sequence(self, tmp_path: Path) -> None:
        """동일성만 보면 둘 다 틀려도 통과한다 — 기대 형태를 따로 못박는다."""
        ctl = _controller(tmp_path, _items(7))
        _drive(ctl, _GUI_STEPS[:-1])
        ctl.submit("quit")
        events = _read(tmp_path / "events.jsonl")
        assert [e["event_type"] for e in events] == [
            "started",
            "finished",
            "started",
            "finished",
            "started",
            "finished",
            "started",
            "finished",
            "started",
            "aborted",
            "started",
            "aborted",
        ]
        verdicts = _read(tmp_path / "verdicts.jsonl")
        assert [(v["verdict"], v["failure_code"], v["failure_note"]) for v in verdicts] == [
            ("approved", None, None),
            ("approved_with_edit", "F3", "표현 손질"),
            ("approved_with_edit", None, None),
            ("rejected", "F2", "정답 3이 아님"),
        ]
        outcome = ctl.summary()
        assert (outcome.approved, outcome.approved_with_edit, outcome.rejected) == (1, 2, 1)
        assert outcome.aborted == 2 and outcome.stopped_early is True
        assert outcome.events_written == 12
        # 7번째 항목은 화면에 띄우지 않았다 — 이벤트 0건이어야 한다.
        assert all(e["cu_slug"] != "wm-gen-calc1-007" for e in events)

    def test_elapsed_measured_from_started(self, tmp_path: Path) -> None:
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        ctl.submit("approved")
        finished = [e for e in _read(tmp_path / "events.jsonl") if e["event_type"] == "finished"]
        assert finished[0]["elapsed_ms"] == 45_000  # 시계 1틱 = started 직후 → 판정

    def test_start_current_is_idempotent(self, tmp_path: Path) -> None:
        """창이 다시 그려져도 started는 한 번 — 이중 시작은 HIT를 부풀린다."""
        ctl = _controller(tmp_path, _items(2))
        ctl.start_current()
        ctl.start_current()
        events = _read(tmp_path / "events.jsonl")
        assert [e["event_type"] for e in events] == ["started"]

    def test_completing_all_items_is_not_early_stop(self, tmp_path: Path) -> None:
        ctl = _controller(tmp_path, _items(2))
        _drive(ctl, [("approved", None, None), ("approved", None, None)])
        assert ctl.done
        ctl.close()
        outcome = ctl.summary()
        assert outcome.stopped_early is False and outcome.aborted == 0


class TestResumeCompatibility:
    """acceptance ③ — 터미널 ↔ GUI 이어하기."""

    def test_gui_resumes_terminal_session(self, tmp_path: Path) -> None:
        items = _items(4)
        _run_terminal(tmp_path, items, "a\nr\nF5\n\nq\n")
        ctl = _controller(tmp_path, items, resume=True)
        assert ctl.skipped_completed == 2
        assert ctl.start_current() == items[2]  # 종료로 중단된 3번째부터
        ctl.submit("approved")
        ctl.start_current()
        ctl.submit("approved")
        finished = [
            e["cu_slug"] for e in _read(tmp_path / "events.jsonl") if e["event_type"] == "finished"
        ]
        assert finished == [item.slug for item in items]  # 이중 계측 없음
        assert len(_read(tmp_path / "verdicts.jsonl")) == 4

    def test_terminal_resumes_gui_session(self, tmp_path: Path) -> None:
        items = _items(4)
        ctl = _controller(tmp_path, items)
        _drive(ctl, [("approved", None, None), ("rejected", "F8", None)])
        ctl.close()  # 창 닫기
        outcome = _run_terminal(tmp_path, items, "a\na\n", resume=True)
        assert outcome.skipped_completed == 2
        assert (outcome.approved, outcome.stopped_early) == (2, False)
        finished = [
            e["cu_slug"] for e in _read(tmp_path / "events.jsonl") if e["event_type"] == "finished"
        ]
        assert finished == [item.slug for item in items]

    def test_without_resume_nothing_is_skipped(self, tmp_path: Path) -> None:
        """대조군 — resume을 안 주면 건너뛰지 않는다(건너뛰기가 resume 때문임을 확인)."""
        items = _items(2)
        _run_terminal(tmp_path, items, "a\na\n")
        ctl = _controller(tmp_path, items, resume=False)
        assert ctl.skipped_completed == 0
        assert ctl.start_current() == items[0]


class TestRefusals:
    """거부 규칙 — 거부된 제출은 아무것도 기록하지 않는다."""

    def test_reject_without_code_is_refused_and_writes_nothing(self, tmp_path: Path) -> None:
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        before = _read(tmp_path / "events.jsonl")
        with pytest.raises(SubmissionRefusedError):
            ctl.submit("rejected", failure_code=None, note="사유 없이 메모만")
        with pytest.raises(SubmissionRefusedError):
            ctl.submit("rejected", failure_code="(사유 없음)")
        assert _read(tmp_path / "events.jsonl") == before
        assert _read(tmp_path / "verdicts.jsonl") == []
        # 사유를 고르면 같은 항목으로 제출된다(항목은 계속 열려 있었다).
        assert ctl.submit("rejected", failure_code=GenerationFailureCode.F4) == "rejected"
        assert _read(tmp_path / "verdicts.jsonl")[0]["failure_code"] == "F4"

    def test_invalid_code_is_refused(self, tmp_path: Path) -> None:
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        with pytest.raises(SubmissionRefusedError):
            ctl.submit("rejected", failure_code="F9")

    def test_note_on_approve_is_refused_not_dropped(self, tmp_path: Path) -> None:
        """승인은 메모를 기록하지 않는다 — 받아서 버리면 조용한 유실이므로 거부한다."""
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        with pytest.raises(SubmissionRefusedError):
            ctl.submit("approved", note="여기 손봐야 함")
        with pytest.raises(SubmissionRefusedError):
            ctl.submit("skip", failure_code="F1")
        assert _read(tmp_path / "verdicts.jsonl") == []

    def test_submit_without_started_is_refused(self, tmp_path: Path) -> None:
        """화면에 띄우지(started) 않은 항목은 판정할 수 없다 — 시간이 재어지지 않았다."""
        ctl = _controller(tmp_path, _items(1))
        with pytest.raises(SubmissionRefusedError):
            ctl.submit("approved")
        assert _read(tmp_path / "events.jsonl") == []


class TestWindowClose:
    """창 닫기 = 중단 — 열린 항목은 aborted, 판정 파일에는 안 쓴다."""

    def test_close_aborts_open_item(self, tmp_path: Path) -> None:
        items = _items(3)
        ctl = _controller(tmp_path, items)
        _drive(ctl, [("approved", None, None)])  # 2번째가 화면에 떠 있다
        ctl.close()
        events = _read(tmp_path / "events.jsonl")
        assert [(e["event_type"], e["cu_slug"]) for e in events[-2:]] == [
            ("started", items[1].slug),
            ("aborted", items[1].slug),
        ]
        assert events[-1]["elapsed_ms"] == 45_000  # 그때까지 쓴 시간도 그 CU의 인간 시간
        assert len(_read(tmp_path / "verdicts.jsonl")) == 1
        outcome = ctl.summary()
        assert outcome.aborted == 1 and outcome.stopped_early is True

    def test_close_matches_terminal_eof(self, tmp_path: Path) -> None:
        """창 닫기는 터미널의 EOF와 같은 기록을 낸다."""
        items = _items(3)
        term_dir, gui_dir = tmp_path / "term", tmp_path / "gui"
        term_dir.mkdir()
        gui_dir.mkdir()
        term_outcome = _run_terminal(term_dir, items, "a\n")  # 두 번째에서 EOF
        ctl = _controller(gui_dir, items)
        _drive(ctl, [("approved", None, None)])
        ctl.close()
        assert _stable(_read(gui_dir / "events.jsonl")) == _stable(_read(term_dir / "events.jsonl"))
        assert ctl.summary() == term_outcome

    def test_close_twice_is_safe(self, tmp_path: Path) -> None:
        ctl = _controller(tmp_path, _items(2))
        ctl.start_current()
        ctl.close()
        ctl.close()
        assert [e["event_type"] for e in _read(tmp_path / "events.jsonl")] == [
            "started",
            "aborted",
        ]


class TestMainHeadless:
    """acceptance ④ — 입력 판정은 tkinter 이전. 큐 0건 → 창 없이 exit 1."""

    def test_empty_queue_exits_1_before_tkinter(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        queue = tmp_path / "queue.jsonl"
        queue.write_text("", encoding="utf-8")
        code = review_session_gui.main(
            [
                "--queue",
                str(queue),
                "--events",
                str(tmp_path / "e.jsonl"),
                "--verdicts",
                str(tmp_path / "v.jsonl"),
                "--reviewer-id",
                "kiki",
            ]
        )
        assert code == 1
        assert "검수 대상 0건" in capsys.readouterr().err
        assert not (tmp_path / "e.jsonl").exists()

    def test_missing_queue_exits_1(self, tmp_path: Path) -> None:
        code = review_session_gui.main(
            [
                "--queue",
                str(tmp_path / "nope.jsonl"),
                "--events",
                str(tmp_path / "e.jsonl"),
                "--verdicts",
                str(tmp_path / "v.jsonl"),
                "--reviewer-id",
                "kiki",
            ]
        )
        assert code == 1

    def test_module_import_does_not_load_tkinter(self) -> None:
        """모듈 소스의 최상위에서 tkinter를 import하지 않는다(TYPE_CHECKING 블록 제외)."""
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(review_session_gui))
        for node in tree.body:
            if isinstance(node, ast.Import):
                assert all(not a.name.startswith("tkinter") for a in node.names)
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("tkinter")

    def test_summary_text_matches_terminal_format(self, tmp_path: Path) -> None:
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        ctl.submit("approved")
        text = ctl.summary_text()
        assert "=== 검수 세션 요약 ===" in text
        assert "승인 1 · 수정승인 0 · 반려 0 · 중단 0" in text

    def test_current_text_reuses_terminal_renderer(self, tmp_path: Path) -> None:
        ctl = _controller(tmp_path, _items(2))
        ctl.start_current()
        text = ctl.current_text()
        assert text.startswith("[1/2] wm-gen-calc1-001")
        assert "문항: 문항 1" in text and "정답: 1" in text


# ── 리뷰 P1·P2 반영분 — 각 가드의 반례(그 절이 없으면 실패하는 입력) ────────────────────


class _ManualClock:
    """손으로 돌리는 단조 시계 — 입력 잠금(1초) 경계를 정확히 밟기 위해 쓴다."""

    def __init__(self) -> None:
        self.now_ns = 0

    def __call__(self) -> int:
        return self.now_ns

    def advance(self, seconds: float) -> None:
        self.now_ns += int(round(seconds * 1_000_000_000))


def _manual(workdir: Path, items: list[ReviewItem], clock: _ManualClock, *, resume: bool = False):
    return ReviewController(
        items,
        events_path=workdir / "events.jsonl",
        verdicts_path=workdir / "verdicts.jsonl",
        reviewer_id="kiki",
        resume=resume,
        monotonic_ns=clock,
        now_utc=lambda: _FIXED_NOW,
    )


def _event_types(path: Path) -> list[str]:
    return [str(e["event_type"]) for e in _read(path)]


class TestSubmissionRulesBeforeWrite:
    """P1-1 — 스키마가 받지 않을 제출은 *쓰기 전에* 한국어로 거부한다(traceback·무반응 없음)."""

    def test_edit_with_memo_but_no_code_is_refused_before_writing(self, tmp_path: Path) -> None:
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        with pytest.raises(SubmissionRefusedError, match=r"사유\(F1~F8\)를 먼저 고르세요"):
            ctl.submit("approved_with_edit", failure_code=None, note="표현 손질")
        assert _event_types(tmp_path / "events.jsonl") == ["started"]
        assert _read(tmp_path / "verdicts.jsonl") == []
        # 항목은 계속 열려 있다 — 사유를 고르면 같은 항목으로 제출된다.
        assert ctl.submit("approved_with_edit", failure_code="F3", note="표현 손질") == (
            "approved_with_edit"
        )
        assert _read(tmp_path / "verdicts.jsonl")[0]["failure_note"] == "표현 손질"

    def test_edit_with_blank_memo_and_no_code_is_accepted(self, tmp_path: Path) -> None:
        """대조군 — 공백뿐인 메모는 메모가 아니다(거부 규칙이 과잉 적용되지 않음)."""
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        assert ctl.submit("approved_with_edit", failure_code=None, note="   ") == (
            "approved_with_edit"
        )

    def test_memo_over_schema_limit_is_refused(self, tmp_path: Path) -> None:
        assert review_session_gui.NOTE_MAX_CHARS == 2000
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        with pytest.raises(SubmissionRefusedError, match="2000자까지"):
            ctl.submit("rejected", failure_code="F1", note="x" * 2001)
        assert _event_types(tmp_path / "events.jsonl") == ["started"]
        # 경계 대조군 — 정확히 2000자는 받는다.
        assert ctl.submit("rejected", failure_code="F1", note="x" * 2000) == "rejected"
        assert len(str(_read(tmp_path / "verdicts.jsonl")[0]["failure_note"])) == 2000

    def test_note_limit_comes_from_schema(self) -> None:
        """상한은 스키마 메타데이터에서 읽는다 — 두 곳에 숫자를 따로 적지 않는다."""
        from whymath_backend.schema.review_timer import ReviewTimerEvent

        limits = [
            getattr(m, "max_length", None)
            for m in ReviewTimerEvent.model_fields["failure_note"].metadata
        ]
        assert review_session_gui.NOTE_MAX_CHARS in limits

    def test_schema_dry_run_catches_rule_missed_by_validator(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """입력 규칙이 하나를 놓쳐도 스키마 시험 생성이 쓰기 전에 거부한다(최종 안전망)."""
        monkeypatch.setattr(review_session_gui, "validate_submission", lambda *a, **k: None)
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        with pytest.raises(SubmissionRefusedError, match="기록 규칙에 맞지 않아"):
            ctl.submit("approved_with_edit", failure_code=None, note="사유 없는 메모")
        assert _event_types(tmp_path / "events.jsonl") == ["started"]
        assert not ctl.halted


class TestInputLock:
    """P1-2 — 항목이 뜬 직후 1초 동안은 판정을 받지 않는다(연타·자동반복 흡수)."""

    def test_lock_constant(self) -> None:
        assert review_session_gui.INPUT_LOCK_SECONDS == 1.0

    def test_submit_within_lock_is_refused_then_allowed(self, tmp_path: Path) -> None:
        clock = _ManualClock()
        ctl = _manual(tmp_path, _items(1), clock)
        ctl.start_current()
        clock.advance(0.999)
        with pytest.raises(SubmissionRefusedError, match="방금 표시된 항목"):
            ctl.submit("approved")
        assert _event_types(tmp_path / "events.jsonl") == ["started"]
        clock.advance(0.002)
        assert ctl.submit("approved") == "approved"
        finished = _read(tmp_path / "events.jsonl")[-1]
        assert finished["elapsed_ms"] == 1001  # 거부된 시도가 시계를 바꾸지 않았다

    def test_double_click_cannot_judge_unread_next_item(self, tmp_path: Path) -> None:
        """실측 재현(2연타 → 다음 항목 approved elapsed_ms=0)이 이제 거부된다."""
        clock = _ManualClock()
        ctl = _manual(tmp_path, _items(2), clock)
        ctl.start_current()
        clock.advance(40)
        ctl.submit("approved")
        ctl.start_current()  # 창은 판정 직후 다음 항목을 띄운다
        with pytest.raises(SubmissionRefusedError, match="방금 표시된 항목"):
            ctl.submit("approved")  # 같은 순간의 두 번째 클릭
        assert _event_types(tmp_path / "events.jsonl") == ["started", "finished", "started"]
        assert len(_read(tmp_path / "verdicts.jsonl")) == 1

    def test_lock_also_covers_skip_and_quit(self, tmp_path: Path) -> None:
        clock = _ManualClock()
        ctl = _manual(tmp_path, _items(1), clock)
        ctl.start_current()
        for action in ("skip", "quit"):
            with pytest.raises(SubmissionRefusedError, match="방금 표시된 항목"):
                ctl.submit(action)
        assert _event_types(tmp_path / "events.jsonl") == ["started"]


def _patch_append_open(
    monkeypatch: pytest.MonkeyPatch, target: Path, *, fail_from: int
) -> list[int]:
    """`target`을 append 모드로 여는 `fail_from`번째(1-기반) 시도부터 PermissionError를 낸다.

    Windows에서 Excel이 파일을 잡고 있을 때의 쓰기 잠금을 흉내 낸다. 반환 리스트는 시도 횟수.
    """
    original = Path.open
    calls = [0]

    def fake_open(self: Path, mode: str = "r", *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if self == target and "a" in mode:
            calls[0] += 1
            if calls[0] >= fail_from:
                raise PermissionError(13, "다른 프로세스가 사용 중", str(self))
        return original(self, mode, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "open", fake_open)
    return calls


class TestRecordingFailure:
    """P2-1 — 쓰기 실패는 화면에 보이고, 같은 CU에 finished가 두 번 남지 않는다."""

    def test_locked_verdict_file_is_refused_before_any_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        verdicts = tmp_path / "verdicts.jsonl"
        verdicts.write_text("", encoding="utf-8")  # 이미 있는 판정 파일(Excel로 열어 둔 상태)
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        _patch_append_open(monkeypatch, verdicts, fail_from=1)
        with pytest.raises(SubmissionRefusedError, match="다른 프로그램"):
            ctl.submit("approved")
        assert _event_types(tmp_path / "events.jsonl") == ["started"]  # finished 미기록
        assert not ctl.halted
        monkeypatch.undo()  # 파일을 닫았다
        assert ctl.submit("approved") == "approved"
        assert _event_types(tmp_path / "events.jsonl") == ["started", "finished"]

    def test_locked_events_file_is_refused_for_skip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        _patch_append_open(monkeypatch, tmp_path / "events.jsonl", fail_from=1)
        with pytest.raises(SubmissionRefusedError, match="이벤트 파일에 쓸 수 없어"):
            ctl.submit("skip")
        monkeypatch.undo()
        assert _event_types(tmp_path / "events.jsonl") == ["started"]

    def test_failure_midway_halts_without_duplicate_finished(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """사전 점검은 통과했는데 판정 행 쓰기에서 실패 → 정지. 재제출·창 닫기가 덧쓰지 않는다."""
        verdicts = tmp_path / "verdicts.jsonl"
        verdicts.write_text("", encoding="utf-8")
        ctl = _controller(tmp_path, _items(2))
        ctl.start_current()
        _patch_append_open(monkeypatch, verdicts, fail_from=2)  # 1회=사전 점검 통과, 2회=실패
        with pytest.raises(RecordingFailedError, match=r"판정\(finished\)이 남았지만"):
            ctl.submit("approved")
        monkeypatch.undo()
        assert ctl.halted
        with pytest.raises(SubmissionRefusedError, match="멈췄습니다"):
            ctl.submit("approved")
        ctl.close()
        assert _event_types(tmp_path / "events.jsonl") == ["started", "finished"]
        assert _read(verdicts) == []
        assert ctl.summary().stopped_early is True

    def test_failure_before_finished_reports_not_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        _patch_append_open(monkeypatch, tmp_path / "events.jsonl", fail_from=2)
        with pytest.raises(RecordingFailedError, match="기록되지 않았습니다"):
            ctl.submit("approved")
        monkeypatch.undo()
        ctl.close()  # 정지 상태 — aborted를 덧붙이지 않는다(항목은 닫힌 것으로 처리)
        assert _event_types(tmp_path / "events.jsonl") == ["started"]


class TestAttemptSubmit:
    """창의 버튼이 부르는 유일한 경로 — 어떤 실패도 화면 문구가 된다(창 없이 검증)."""

    def test_unexpected_exception_is_shown_and_logged_with_type(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()

        secret = "민감할 수 있는 메모 본문"

        def boom(*args: object, **kwargs: object) -> str:
            raise KeyError(secret)  # 예외 메시지(입력값)는 로그에 남기지 않는다 — 위치만

        monkeypatch.setattr(ctl, "submit", boom)
        with caplog.at_level("ERROR", logger=review_session_gui.__name__):
            feedback = review_session_gui.attempt_submit(ctl, "approved")
        assert feedback.accepted is False and feedback.halted is True
        assert feedback.message.startswith("기록 실패: KeyError")
        assert any("KeyError" in r.getMessage() for r in caplog.records)
        assert all("민감할 수 있는 메모 본문" not in r.getMessage() for r in caplog.records)

    def test_refusal_is_passed_through_without_halt(self, tmp_path: Path) -> None:
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        feedback = review_session_gui.attempt_submit(ctl, "rejected")
        assert (feedback.accepted, feedback.halted) == (False, False)
        assert "반려는 사유" in feedback.message

    def test_recording_failure_halts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        _patch_append_open(monkeypatch, tmp_path / "events.jsonl", fail_from=2)
        feedback = review_session_gui.attempt_submit(ctl, "approved")
        monkeypatch.undo()
        assert (feedback.accepted, feedback.halted) == (False, True)
        assert feedback.message.startswith("기록 실패(PermissionError)")

    def test_success(self, tmp_path: Path) -> None:
        ctl = _controller(tmp_path, _items(1))
        ctl.start_current()
        assert review_session_gui.attempt_submit(ctl, "approved") == (
            review_session_gui.SubmitFeedback(accepted=True, message="", halted=False)
        )


class TestNoLetterShortcuts:
    """P1-2 — 맨 글자 단축키는 없다(판정은 버튼으로만)."""

    def test_module_binds_no_key_events(self) -> None:
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(review_session_gui))
        key_literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and ("<Key" in node.value or "<KeyPress" in node.value)
        ]
        bind_all = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in ("bind_all", "bind_class")
        ]
        assert key_literals == [] and bind_all == []


class _FakeTk:
    """main의 finally 경로 검증용 가짜 Tk — mainloop이 예외로 끝나는 창을 흉내 낸다."""

    def __init__(self, raise_in_mainloop: bool) -> None:
        self._raise = raise_in_mainloop

    def mainloop(self) -> None:
        if self._raise:
            raise RuntimeError("창이 비정상 종료")


def _fake_tk_module(raise_in_mainloop: bool):  # type: ignore[no-untyped-def]
    import types

    module = types.ModuleType("tkinter")
    module.Tk = lambda: _FakeTk(raise_in_mainloop)  # type: ignore[attr-defined]
    return module


class _FakeWindow:
    """가짜 창 — 실제 창처럼 첫 항목을 띄운다(started)."""

    def __init__(self, root: object, controller: ReviewController) -> None:
        self.controller = controller
        controller.start_current()
        self.summary_calls = 0
        self.failed = False
        self.failure_message = None

    def print_summary(self) -> None:
        self.summary_calls += 1


class TestMainFinally:
    """P3 — 창이 어떤 경로로 사라져도 열린 항목은 aborted로 남는다(main의 finally)."""

    def _args(self, tmp_path: Path) -> list[str]:
        queue = tmp_path / "queue.jsonl"
        queue.write_text(
            json.dumps({"slug": "wm-gen-calc1-001", "question_text": "문항", "answer": "1"}) + "\n",
            encoding="utf-8",
        )
        return [
            "--queue",
            str(queue),
            "--events",
            str(tmp_path / "e.jsonl"),
            "--verdicts",
            str(tmp_path / "v.jsonl"),
            "--reviewer-id",
            "kiki",
        ]

    def test_mainloop_exception_still_aborts_open_item(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys

        monkeypatch.setitem(sys.modules, "tkinter", _fake_tk_module(raise_in_mainloop=True))
        monkeypatch.setattr(review_session_gui, "ReviewWindow", _FakeWindow)
        with pytest.raises(RuntimeError, match="비정상 종료"):
            review_session_gui.main(self._args(tmp_path))
        assert _event_types(tmp_path / "e.jsonl") == ["started", "aborted"]

    def test_normal_close_returns_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        monkeypatch.setitem(sys.modules, "tkinter", _fake_tk_module(raise_in_mainloop=False))
        monkeypatch.setattr(review_session_gui, "ReviewWindow", _FakeWindow)
        assert review_session_gui.main(self._args(tmp_path)) == 0
        assert _event_types(tmp_path / "e.jsonl") == ["started", "aborted"]

    def test_halted_session_returns_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import sys

        class _HaltingWindow(_FakeWindow):
            def __init__(self, root: object, controller: ReviewController) -> None:
                super().__init__(root, controller)
                controller._halted_reason = "기록 실패(PermissionError): 시험"
                self.failed = True

        monkeypatch.setitem(sys.modules, "tkinter", _fake_tk_module(raise_in_mainloop=False))
        monkeypatch.setattr(review_session_gui, "ReviewWindow", _HaltingWindow)
        assert review_session_gui.main(self._args(tmp_path)) == 1
        assert "[기록 실패]" in capsys.readouterr().err


# ── 다시 보기(◀/▶ — 읽기 전용) ─────────────────────────────────────────────


def _judge_three(tmp_path: Path, clock: _ManualClock) -> ReviewController:
    """승인 · 수정승인(F3+메모) · 반려(F2) 3건을 판정하고 4번째를 띄운 상태."""
    ctl = _manual(tmp_path, _items(5), clock)
    for action, code, note in (
        ("approved", None, None),
        ("approved_with_edit", "F3", "표현 손질"),
        ("rejected", "F2", "정답 3이 아님"),
    ):
        ctl.start_current()
        clock.advance(40)
        ctl.submit(action, failure_code=code, note=note)
    ctl.start_current()
    clock.advance(5)
    return ctl


class TestReviewHistory:
    """이전 문항 다시 보기 — 탐색 상태는 제어기에 있다(창 없이 검증)."""

    def test_no_history_disables_back(self, tmp_path: Path) -> None:
        ctl = _controller(tmp_path, _items(2))
        ctl.start_current()
        assert ctl.history == ()
        assert (ctl.can_review_back, ctl.can_review_forward) == (False, False)
        assert ctl.review_back() is False and ctl.reviewing is False
        assert ctl.review_forward() is False

    def test_walk_back_and_forward_then_return_to_current(self, tmp_path: Path) -> None:
        ctl = _judge_three(tmp_path, _ManualClock())
        positions = []
        while ctl.review_back():
            view = ctl.review_view()
            assert view is not None
            positions.append((view.position, view.total))
        assert positions == [(3, 3), (2, 3), (1, 3)]
        assert ctl.can_review_back is False  # 맨 앞 경계
        assert ctl.review_back() is False and ctl.review_view().position == 1  # type: ignore[union-attr]
        assert ctl.review_forward() and ctl.review_view().position == 2  # type: ignore[union-attr]
        assert ctl.review_forward() and ctl.review_view().position == 3  # type: ignore[union-attr]
        assert ctl.review_forward() is True  # 마지막 다음 = 지금 판정할 문항
        assert ctl.reviewing is False and ctl.review_view() is None
        assert ctl.can_review_forward is False and ctl.review_forward() is False

    def test_view_shows_verdict_code_and_memo_with_body(self, tmp_path: Path) -> None:
        ctl = _judge_three(tmp_path, _ManualClock())
        ctl.review_back()
        ctl.review_back()  # 2번째 = 수정승인 F3 + 메모
        view = ctl.review_view()
        assert view is not None
        assert "이 문항의 판정: 수정승인" in view.verdict_block
        assert "사유: F3 — 풀이 논리 비약" in view.verdict_block
        assert "메모: 표현 손질" in view.verdict_block
        assert view.body.startswith("[2/3] wm-gen-calc1-002") and "문항: 문항 2" in view.body

    def test_history_reads_previous_sessions_in_file_order(self, tmp_path: Path) -> None:
        """이어하기 — 터미널 세션이 남긴 판정도 판정 파일 순서대로 다시 볼 수 있다."""
        items = _items(4)
        _run_terminal(tmp_path, items, "r\nF5\n\na\ns\n")  # 반려 · 승인 · 보류(판정 아님)
        ctl = _controller(tmp_path, items, resume=True)
        assert [(h.slug, h.verdict) for h in ctl.history] == [
            ("wm-gen-calc1-001", "rejected"),
            ("wm-gen-calc1-002", "approved"),
        ]
        assert ctl.history_problem is None

    def test_history_skips_non_verdict_and_broken_rows(self, tmp_path: Path) -> None:
        verdicts = tmp_path / "verdicts.jsonl"
        verdicts.write_text(
            json.dumps({"slug": "wm-gen-calc1-001", "verdict": "approved"})
            + "\n"
            + json.dumps({"slug": "wm-gen-calc1-002", "verdict": "pending"})
            + "\n{깨진 줄\n"
            + json.dumps({"slug": "다른-큐-slug", "verdict": "rejected", "failure_code": "F9"})
            + "\n",
            encoding="utf-8",
        )
        ctl = _controller(tmp_path, _items(2))
        assert [(h.slug, h.verdict) for h in ctl.history] == [
            ("wm-gen-calc1-001", "approved"),
            ("다른-큐-slug", "rejected"),
        ]
        assert ctl.history_problem is not None and "1건" in ctl.history_problem
        ctl.start_current()
        ctl.review_back()
        view = ctl.review_view()
        assert view is not None and "본문은 이번 검수 큐에 없어" in view.body
        assert "사유: F9" in view.verdict_block  # 모르는 코드는 라벨 없이 원문

    def test_submit_during_review_is_refused_and_writes_nothing(self, tmp_path: Path) -> None:
        clock = _ManualClock()
        ctl = _judge_three(tmp_path, clock)
        before = _read(tmp_path / "events.jsonl")
        ctl.review_back()
        clock.advance(10)
        for action in ("approved", "skip", "quit"):
            with pytest.raises(SubmissionRefusedError, match="다시 보기 중에는 판정할 수 없습니다"):
                ctl.submit(action)
        assert _read(tmp_path / "events.jsonl") == before
        assert len(_read(tmp_path / "verdicts.jsonl")) == 3

    def test_navigation_writes_no_events_and_clock_keeps_running(self, tmp_path: Path) -> None:
        clock = _ManualClock()
        ctl = _judge_three(tmp_path, clock)
        before = _read(tmp_path / "events.jsonl")
        ctl.review_back()
        ctl.review_back()
        clock.advance(20)
        assert ctl.elapsed_seconds() == 25  # 다시 보기 중에도 지금 문항의 시계는 흐른다
        ctl.review_forward()
        ctl.review_forward()
        assert _read(tmp_path / "events.jsonl") == before

    def test_returning_reapplies_input_lock(self, tmp_path: Path) -> None:
        clock = _ManualClock()
        ctl = _judge_three(tmp_path, clock)  # 4번째가 뜬 지 5초
        ctl.review_back()
        clock.advance(10)
        assert ctl.review_forward() and not ctl.reviewing  # 15초 시점 복귀
        clock.advance(0.5)
        with pytest.raises(SubmissionRefusedError, match="방금 표시된 항목"):
            ctl.submit("approved")
        clock.advance(0.6)
        assert ctl.submit("approved") == "approved"
        assert _read(tmp_path / "events.jsonl")[-1]["elapsed_ms"] == 16_100  # started부터 계속

    def test_draft_is_kept_across_review_and_cleared_after_submit(self, tmp_path: Path) -> None:
        clock = _ManualClock()
        ctl = _judge_three(tmp_path, clock)
        draft = review_session_gui.Draft(failure_code="F2 — 정답 불일치", note="쓰던 메모")
        ctl.review_back(draft=draft)
        ctl.review_back(draft=review_session_gui.Draft(failure_code=None, note="덮어쓰기 아님"))
        ctl.review_forward()
        ctl.review_forward()
        assert ctl.reviewing is False and ctl.draft == draft
        clock.advance(2)
        ctl.submit("rejected", failure_code="F2", note="쓰던 메모")
        assert ctl.draft is None
        ctl.start_current()
        assert ctl.draft is None

    def test_session_judgments_join_history_but_skips_do_not(self, tmp_path: Path) -> None:
        clock = _ManualClock()
        ctl = _manual(tmp_path, _items(3), clock)
        ctl.start_current()
        clock.advance(3)
        ctl.submit("skip")
        assert ctl.history == ()
        ctl.start_current()
        clock.advance(3)
        ctl.submit("approved_with_edit", failure_code="F4", note="  성취기준 손질 ")
        assert [(h.slug, h.verdict, h.failure_code, h.failure_note) for h in ctl.history] == [
            ("wm-gen-calc1-002", "approved_with_edit", "F4", "성취기준 손질")
        ]
        assert ctl.history[0].item is not None


def _display_available() -> bool:
    """tkinter와 디스플레이가 둘 다 있을 때만 실제 창을 띄운다(CI 헤드리스는 건너뛴다)."""
    try:
        import tkinter
    except ImportError:
        return False
    try:
        root = tkinter.Tk()
    except tkinter.TclError:
        return False
    root.destroy()
    return True


def _pump(root, seconds: float = 0.0) -> None:  # type: ignore[no-untyped-def]
    import time

    end = time.monotonic() + seconds
    while True:
        root.update()
        if time.monotonic() >= end:
            break
        time.sleep(0.02)


def _real_controller(workdir: Path, items: list[ReviewItem]) -> ReviewController:
    return ReviewController(
        items,
        events_path=workdir / "events.jsonl",
        verdicts_path=workdir / "verdicts.jsonl",
        reviewer_id="kiki",
    )


_UNLOCK_WAIT = review_session_gui.INPUT_LOCK_SECONDS + 0.3


@pytest.mark.skipif(not _display_available(), reason="tkinter 또는 디스플레이 없음(헤드리스)")
class TestWindowWithDisplay:
    """실제 창 — 버튼·잠금·다시 보기·창 닫기가 제어기와 같은 기록을 낸다."""

    def test_started_only_after_window_is_visible(self, tmp_path: Path) -> None:
        import tkinter

        from whymath_backend.harness.review_session_gui import ReviewWindow

        ctl = _real_controller(tmp_path, _items(2))
        root = tkinter.Tk()
        window = ReviewWindow(root, ctl)
        assert not (tmp_path / "events.jsonl").exists()  # 창이 보이기 전 — started 없음
        _pump(root, 0.2)
        assert _event_types(tmp_path / "events.jsonl") == ["started"]
        window.on_close()

    def test_buttons_locked_then_enabled_and_double_click_absorbed(self, tmp_path: Path) -> None:
        import tkinter

        from whymath_backend.harness.review_session_gui import ReviewWindow

        ctl = _real_controller(tmp_path, _items(3))
        root = tkinter.Tk()
        window = ReviewWindow(root, ctl)
        _pump(root, 0.2)
        assert all(str(b.cget("state")) == "disabled" for b in window._buttons)
        assert "연타 방지" in window._lock_label.cget("text")
        _pump(root, _UNLOCK_WAIT)
        assert all(str(b.cget("state")) == "normal" for b in window._buttons)
        window._buttons[0].invoke()  # 승인
        window._buttons[0].invoke()  # 같은 순간의 두 번째 클릭 — 꺼진 버튼이라 무시
        _pump(root, 0.1)
        assert _event_types(tmp_path / "events.jsonl") == ["started", "finished", "started"]
        window.on_close()

    def test_refusals_show_red_text_and_close(self, tmp_path: Path) -> None:
        import tkinter

        from whymath_backend.harness.review_session_gui import ReviewWindow

        ctl = _real_controller(tmp_path, _items(4))
        root = tkinter.Tk()
        window = ReviewWindow(root, ctl)
        _pump(root, _UNLOCK_WAIT)
        window._buttons[0].invoke()  # 승인
        _pump(root, _UNLOCK_WAIT)
        window._memo.insert(0, "손질")
        window._buttons[1].invoke()  # 사유 없이 메모 + 수정승인 → 거부(빨간 글씨)
        _pump(root, 0.1)
        assert "사유(F1~F8)를 먼저" in window._status.cget("text")
        window._code.current(2)  # F2
        window._buttons[1].invoke()  # 수정승인
        _pump(root, _UNLOCK_WAIT)
        window._buttons[2].invoke()  # 사유 없는 반려 → 거부
        assert "사유" in window._status.cget("text")
        window.on_close()  # 3번째가 열린 채 닫기
        assert _event_types(tmp_path / "events.jsonl") == [
            "started",
            "finished",
            "started",
            "finished",
            "started",
            "aborted",
        ]
        verdicts = _read(tmp_path / "verdicts.jsonl")
        assert [(v["verdict"], v["failure_code"], v["failure_note"]) for v in verdicts] == [
            ("approved", None, None),
            ("approved_with_edit", "F2", "손질"),
        ]

    def test_review_navigation_in_window(self, tmp_path: Path) -> None:
        import tkinter

        from whymath_backend.harness.review_session_gui import ReviewWindow

        ctl = _real_controller(tmp_path, _items(3))
        root = tkinter.Tk()
        window = ReviewWindow(root, ctl)
        _pump(root, 0.2)
        assert str(window._back.cget("state")) == "disabled"  # 판정 0건
        assert str(window._forward.cget("state")) == "disabled"
        _pump(root, _UNLOCK_WAIT)
        window._buttons[0].invoke()  # 승인
        _pump(root, 0.1)
        window._code.current(3)
        window._memo.insert(0, "쓰던 메모")
        window._back.invoke()
        _pump(root, 0.1)
        assert "다시 보기 중 (1/1)" in window._banner.cget("text")
        assert all(str(b.cget("state")) == "disabled" for b in window._buttons)
        assert str(window._memo.cget("state")) == "disabled"
        assert str(window._forward.cget("state")) == "normal"
        assert "이 문항의 판정: 승인" in window._body.get("1.0", "end")
        before = _read(tmp_path / "events.jsonl")
        window._forward.invoke()  # 지금 판정할 문항으로 복귀
        _pump(root, 0.1)
        assert window._banner.cget("text") == ""
        assert window._memo.get() == "쓰던 메모" and window._code.get().startswith("F3")
        assert all(str(b.cget("state")) == "disabled" for b in window._buttons)  # 잠금 재적용
        _pump(root, _UNLOCK_WAIT)
        assert all(str(b.cget("state")) == "normal" for b in window._buttons)
        assert _read(tmp_path / "events.jsonl") == before  # 다시 보기는 기록하지 않는다
        window.on_close()
