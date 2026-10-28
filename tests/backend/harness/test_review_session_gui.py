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
from whymath_backend.harness.review_session_gui import ReviewController, SubmissionRefusedError
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


@pytest.mark.skipif(not _display_available(), reason="tkinter 또는 디스플레이 없음(헤드리스)")
class TestWindowWithDisplay:
    """실제 창 — 버튼·단축키·메모 입력 중 단축키 무시·창 닫기가 제어기와 같은 기록을 낸다."""

    def test_buttons_keys_and_close(self, tmp_path: Path) -> None:
        import tkinter

        from whymath_backend.harness.review_session_gui import ReviewWindow

        ctl = _controller(tmp_path, _items(4))
        root = tkinter.Tk()
        window = ReviewWindow(root, ctl)
        root.update()
        window._buttons[0].invoke()  # 승인
        window._code.current(2)  # F2
        window._memo.insert(0, "손질")
        root.focus_set()
        root.event_generate("<KeyPress-e>")  # 수정승인 단축키
        root.update()
        window._buttons[2].invoke()  # 사유 없는 반려 → 거부
        assert "사유" in window._status.cget("text")
        window._memo.focus_set()
        root.update()
        window._memo.event_generate("<KeyPress-r>")  # 메모 칸의 글자는 판정이 아니다
        root.update()
        assert ctl.position == 3
        window.on_close()  # 3번째가 열린 채 닫기
        events = _read(tmp_path / "events.jsonl")
        assert [e["event_type"] for e in events] == [
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
