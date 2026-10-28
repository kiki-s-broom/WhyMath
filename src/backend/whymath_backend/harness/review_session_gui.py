"""검수 세션 GUI — 터미널 `review_session`과 **같은 기록**을 내는 Windows 검수 창 (EOS-199).

## 왜 만들었나

터미널 대화형 검수(`harness/review_session`)는 키 한 글자 + Enter로 판정을 받는다. 그런데
붙여넣기 버퍼에 남은 줄이 판정 입력으로 먹히고(2026-09-22 실측: 무효 입력 10회 + 첫 항목 HIT
타이머 오염), 키 입력 혼동 위험도 있다. 이 모듈은 같은 검수를 **창에서 버튼으로** 받는다 —
tkinter(표준 라이브러리)만 쓰므로 새 의존성은 0이다.

## 기록 동일성 (acceptance ②) — 두 경로가 *같은 함수*를 부른다

이 모듈은 기록을 직접 만들지 않는다. 항목을 여는 것(`started`)과 닫는 것(`finished`+판정 행 /
`aborted`)은 `review_session.open_review_item`·`close_review_item`이 하며, 터미널 세션도 같은 두
함수를 부른다. 그래서 두 경로가 갈라질 수 있는 자리는 **"어떤 행동을 어떤 사유로 골랐는가"를
받는 입력 층**뿐이고, 그 층의 의미(반려는 F1~F8 필수·수정승인은 선택·보류/종료/창 닫기는 중단)는
`ReviewController.submit`이 터미널 프롬프트와 같게 맞춘다. 같은 판정 순서를 두 경로에 넣어 이벤트·
판정 파일이 같음을 `tests/backend/harness/test_review_session_gui.py`가 동결한다.

항목의 생애(터미널과 동일):
  - 화면에 띄우는 순간 `started`(`start_current`) — 창이 죽어도 "보기 시작했다"가 남는다.
  - 승인·수정승인·반려 → `finished` + 판정 파일 1행.
  - 보류·종료·**창 닫기** → `aborted`(판정 파일에는 쓰지 않는다 — pending은 판정이 아니다).

## 창 로직과 위젯 분리 (acceptance ④)

`ReviewController`는 tkinter를 모른다 — CI(디스플레이 없음)에서 그대로 테스트된다. tkinter는
`ReviewWindow`(창)와 `main()` 안에서만 **지연 import**한다. 그래서 이 모듈을 import하는 것만으로는
tkinter가 필요 없다.

## HIT 하한 가드(OPS-90)와의 관계 (acceptance ⑤)

30초 미만 판정을 **막지 않는다** — 막으면 "기다렸다 누르기"라는 위장 시간이 생긴다. 판정은 집계
쪽(`ops/hit_cu_metrics`)이 한다. 창은 경과 시간을 1초마다 보여주고 30초 미만이면 주황색으로 칠해,
검수자가 자기 속도를 알게만 한다.

사용(Windows PowerShell 예 — 런북 `docs/ops/eos197_authoring_round_runbook.md` [J-G]):
    python -m whymath_backend.harness.review_session_gui \\
        --queue data/review/queue.jsonl \\
        --events data/review/timer_events.jsonl \\
        --verdicts data/review/verdicts.jsonl \\
        --reviewer-id kiki [--resume] [--limit 30]

exit code: 0 정상 종료(중도 종료·창 닫기 포함 — 중단도 기록된 사실이다) / 1 입력 실패(파일 부재·
검수 대상 0건) 또는 tkinter 부재.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from whymath_backend.harness.review_session import (
    CONCLUDING_ACTIONS,
    OpenReview,
    ReviewItem,
    SessionOutcome,
    close_review_item,
    completed_slugs,
    open_review_item,
    prepare_session_items,
    render_item,
    render_summary,
)
from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.review_timer import VERDICT_APPROVED_WITH_EDIT

if TYPE_CHECKING:  # 런타임에는 창을 띄울 때만 import한다(CI 헤드리스·acceptance ④)
    import tkinter as tk

__all__ = [
    "FAILURE_CODE_LABELS",
    "HIT_FLOOR_SECONDS",
    "ReviewController",
    "SubmissionRefusedError",
    "main",
]

#: 판정 행동 — 터미널 판정 키(`a/e/r/s/q`)와 같은 폐쇄 집합이다.
ACTIONS: tuple[str, ...] = ("approved", VERDICT_APPROVED_WITH_EDIT, "rejected", "skip", "quit")

#: 반려 사유 드롭다운 라벨 — 런북 [J] 절의 한국어 설명과 같다(설계서 §4).
FAILURE_CODE_LABELS: dict[GenerationFailureCode, str] = {
    GenerationFailureCode.F1: "수식·파싱 실패",
    GenerationFailureCode.F2: "정답 불일치",
    GenerationFailureCode.F3: "풀이 논리 비약",
    GenerationFailureCode.F4: "성취기준 이탈",
    GenerationFailureCode.F5: "난이도 미스",
    GenerationFailureCode.F6: "오개념 오연결",
    GenerationFailureCode.F7: "언어 수준 부적합",
    GenerationFailureCode.F8: "힌트 정답 누설",
}

#: OPS-90 HIT 하한(초) — 화면 표시용. 막지 않는다(판정은 `ops/hit_cu_metrics`가 한다).
HIT_FLOOR_SECONDS = 30


class SubmissionRefusedError(ValueError):
    """판정 제출 거부 — **아무것도 기록하지 않았다**. 메시지는 화면에 그대로 보여준다."""


class ReviewController:
    """판정·기록 제어기 — tkinter 없이 동작한다(acceptance ④).

    터미널 세션의 루프를 "한 번에 한 항목" 단위로 쪼갠 것이다: `start_current()`가 항목을 열고
    (`started`), `submit()`이 닫는다(`finished`+판정 / `aborted`). 열고 닫기는 터미널과 같은
    `open_review_item`·`close_review_item`이 한다.
    """

    def __init__(
        self,
        items: list[ReviewItem],
        *,
        events_path: Path,
        verdicts_path: Path,
        reviewer_id: str,
        resume: bool = False,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        now_utc: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        already = completed_slugs(events_path) if resume else set()
        self._pending = [item for item in items if item.slug not in already]
        self._skipped_completed = len(items) - len(self._pending)
        self._events_path = events_path
        self._verdicts_path = verdicts_path
        self._reviewer_id = reviewer_id
        self._monotonic_ns = monotonic_ns
        self._now_utc = now_utc
        self._index = 0
        self._open: OpenReview | None = None
        self._counts = {"approved": 0, VERDICT_APPROVED_WITH_EDIT: 0, "rejected": 0, "aborted": 0}
        self._events_written = 0
        self._stopped_early = False
        self._closed = False

    # ── 조회 ────────────────────────────────────────────────────────────
    @property
    def total(self) -> int:
        """이번 세션에서 볼 항목 수(재개로 건너뛴 것 제외)."""
        return len(self._pending)

    @property
    def skipped_completed(self) -> int:
        """`--resume`으로 건너뛴 이미 종결된 항목 수."""
        return self._skipped_completed

    @property
    def position(self) -> int:
        """현재 항목의 1-기반 순번(끝났으면 total)."""
        return min(self._index + 1, self.total)

    @property
    def done(self) -> bool:
        """더 볼 항목이 없거나 세션을 끝냈다."""
        return self._closed or self._index >= self.total

    @property
    def current(self) -> ReviewItem | None:
        """지금 볼 항목 — 끝났으면 None."""
        if self.done:
            return None
        return self._pending[self._index]

    def current_text(self) -> str:
        """현재 항목의 본문 — 터미널과 같은 렌더러(`render_item`)를 StringIO로 재사용한다."""
        item = self.current
        if item is None:
            return ""
        buf = io.StringIO()
        render_item(buf, self.position, self.total, item)
        return buf.getvalue().lstrip("\n")

    def elapsed_seconds(self) -> int | None:
        """현재 연 항목의 경과(초, 표시용) — 열린 항목이 없으면 None."""
        if self._open is None:
            return None
        return (self._monotonic_ns() - self._open.t0_ns) // 1_000_000_000

    # ── 생애 ────────────────────────────────────────────────────────────
    def start_current(self) -> ReviewItem | None:
        """현재 항목을 화면에 띄운다 = `started`를 적는다. 이미 열려 있으면 아무것도 안 한다.

        멱등이어야 하는 이유: 창이 다시 그려질 때마다 started가 적히면 한 CU에 시작이 둘이 되고
        HIT가 부풀거나 unfinished로 오분류된다.
        """
        item = self.current
        if item is None or self._open is not None:
            return item
        self._open = open_review_item(
            item,
            events_path=self._events_path,
            reviewer_id=self._reviewer_id,
            monotonic_ns=self._monotonic_ns,
            now_utc=self._now_utc,
        )
        self._events_written += 1
        return item

    def submit(
        self,
        action: str,
        failure_code: GenerationFailureCode | str | None = None,
        note: str | None = None,
    ) -> str:
        """판정 1건 제출 — 종결 종류(`approved`·…·`aborted`)를 돌려준다.

        입력 규칙은 터미널 프롬프트와 같다: 반려는 F1~F8 필수 · 수정승인은 사유 선택 · 승인·보류·
        종료는 사유를 받지 않는다. 규칙 위반은 `SubmissionRefusedError`로 거부하며 **아무것도 적지
        않는다**(항목은 계속 열려 있고 시계도 계속 간다).
        """
        if action not in ACTIONS:
            raise SubmissionRefusedError(f"알 수 없는 판정입니다: {action}")
        if self._open is None:
            raise SubmissionRefusedError("화면에 띄운 항목이 없습니다(start_current 먼저).")
        code = _parse_failure_code(failure_code)
        memo = (note or "").strip() or None
        if action == "rejected" and code is None:
            raise SubmissionRefusedError("반려는 사유(F1~F8)를 골라야 제출됩니다.")
        if action not in ("rejected", VERDICT_APPROVED_WITH_EDIT) and (code or memo):
            # 터미널은 승인·보류·종료에서 사유·메모를 묻지 않는다 — 받아서 버리면 조용한 유실이다.
            raise SubmissionRefusedError(
                "승인·보류·종료에는 사유·메모가 기록되지 않습니다. 남기려면 수정승인(e)이나 "
                "반려(r)를 쓰고, 아니면 사유·메모 칸을 비우십시오."
            )
        concluded = close_review_item(
            self._open,
            action=action if action in CONCLUDING_ACTIONS else None,
            failure_code=code,
            note=memo,
            events_path=self._events_path,
            verdicts_path=self._verdicts_path,
            reviewer_id=self._reviewer_id,
            monotonic_ns=self._monotonic_ns,
            now_utc=self._now_utc,
        )
        self._open = None
        self._events_written += 1
        self._counts[concluded] += 1
        self._index += 1
        if action == "quit":
            self._stopped_early = True
            self._closed = True
        return concluded

    def close(self) -> None:
        """창 닫기 — 열린 항목은 `aborted`로 남긴다(터미널의 EOF와 같다). 두 번 불러도 안전."""
        if self._closed:
            return
        if self._open is not None:
            close_review_item(
                self._open,
                action=None,
                failure_code=None,
                note=None,
                events_path=self._events_path,
                verdicts_path=self._verdicts_path,
                reviewer_id=self._reviewer_id,
                monotonic_ns=self._monotonic_ns,
                now_utc=self._now_utc,
            )
            self._open = None
            self._events_written += 1
            self._counts["aborted"] += 1
        if self._index < self.total:
            self._stopped_early = True
        self._closed = True

    def summary(self) -> SessionOutcome:
        """세션 회계 — 터미널판과 같은 `SessionOutcome`."""
        return SessionOutcome(
            approved=self._counts["approved"],
            approved_with_edit=self._counts[VERDICT_APPROVED_WITH_EDIT],
            rejected=self._counts["rejected"],
            aborted=self._counts["aborted"],
            skipped_completed=self._skipped_completed,
            events_written=self._events_written,
            stopped_early=self._stopped_early,
        )

    def summary_text(self) -> str:
        """요약 문자열 — 터미널판 `render_summary`와 같은 형식."""
        buf = io.StringIO()
        render_summary(
            buf, self.summary(), events_path=self._events_path, verdicts_path=self._verdicts_path
        )
        return buf.getvalue()


def _parse_failure_code(value: GenerationFailureCode | str | None) -> GenerationFailureCode | None:
    """드롭다운 값(`"F2 — 정답 불일치"`·`"F2"`·enum·빈 값) → 코드. 무효면 거부한다."""
    if value is None or isinstance(value, GenerationFailureCode):
        return value
    token = value.strip().split(" ", 1)[0].upper()
    if not token:
        return None
    try:
        return GenerationFailureCode(token)
    except ValueError:
        raise SubmissionRefusedError(f"사유는 F1~F8 중 하나여야 합니다(입력: {token}).") from None


# ── 창 (tkinter — 여기서만 지연 import) ─────────────────────────────────────

_NO_CODE_LABEL = "(사유 없음)"
_FONT_CANDIDATES = ("맑은 고딕", "Malgun Gothic")
_COLOR_FAST = "#d97706"  # 30초 미만 — 주황(막지 않는다)
_COLOR_NORMAL = "#1f2937"
_COLOR_ERROR = "#b91c1c"


class ReviewWindow:
    """검수 창 — 위젯 배치와 이벤트 연결만 한다. 판정·기록은 전부 `ReviewController`."""

    def __init__(self, root: tk.Tk, controller: ReviewController) -> None:
        import tkinter as tk
        from tkinter import font as tkfont
        from tkinter import scrolledtext, ttk

        self._root = root
        self._ctl = controller
        self._summary_printed = False

        families = set(tkfont.families(root))
        family = next((f for f in _FONT_CANDIDATES if f in families), "TkDefaultFont")
        ui_font = (family, 12)
        body_font = (family, 13)
        bold_font = (family, 13, "bold")

        root.title("WhyMath 검수 — EOS 카나리")
        root.geometry("1100x800")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        top = tk.Frame(root, padx=12, pady=8)
        top.pack(fill="x")
        self._progress = tk.Label(top, font=bold_font, anchor="w")
        self._progress.pack(side="left")
        self._elapsed = tk.Label(top, font=bold_font, anchor="e")
        self._elapsed.pack(side="right")

        self._body = scrolledtext.ScrolledText(
            root, wrap="word", font=body_font, padx=10, pady=10, height=20
        )
        self._body.pack(fill="both", expand=True, padx=12)

        form = tk.Frame(root, padx=12, pady=6)
        form.pack(fill="x")
        tk.Label(form, text="사유(반려 필수·수정승인 선택)", font=ui_font).grid(
            row=0, column=0, sticky="w"
        )
        values = [_NO_CODE_LABEL] + [
            f"{code.value} — {label}" for code, label in FAILURE_CODE_LABELS.items()
        ]
        self._code = ttk.Combobox(form, values=values, state="readonly", width=28, font=ui_font)
        self._code.current(0)
        self._code.grid(row=0, column=1, sticky="w", padx=6)
        tk.Label(form, text="메모(선택)", font=ui_font).grid(row=0, column=2, sticky="w", padx=6)
        self._memo = tk.Entry(form, font=ui_font, width=50)
        self._memo.grid(row=0, column=3, sticky="we")
        form.columnconfigure(3, weight=1)

        buttons = tk.Frame(root, padx=12, pady=6)
        buttons.pack(fill="x")
        self._buttons: list[tk.Button] = []
        for label, action in (
            ("승인 (a)", "approved"),
            ("수정승인 (e)", VERDICT_APPROVED_WITH_EDIT),
            ("반려 (r)", "rejected"),
            ("보류 (s)", "skip"),
            ("종료 (q)", "quit"),
        ):
            btn = tk.Button(
                buttons,
                text=label,
                font=ui_font,
                width=12,
                command=self._button_command(action),
            )
            btn.pack(side="left", padx=4)
            self._buttons.append(btn)

        self._status = tk.Label(root, font=ui_font, anchor="w", fg=_COLOR_ERROR, padx=12)
        self._status.pack(fill="x", pady=(0, 8))

        for key, action in (
            ("a", "approved"),
            ("e", VERDICT_APPROVED_WITH_EDIT),
            ("r", "rejected"),
            ("s", "skip"),
            ("q", "quit"),
        ):
            root.bind(f"<KeyPress-{key}>", self._key_handler(action))

        self._show_current()
        self._tick()

    def _button_command(self, action: str) -> Callable[[], None]:
        def command() -> None:
            self._submit(action)

        return command

    def _key_handler(self, action: str) -> Callable[[tk.Event[tk.Misc]], None]:
        def handler(event: tk.Event[tk.Misc]) -> None:
            self._on_key(event, action)

        return handler

    def _on_key(self, event: tk.Event[tk.Misc], action: str) -> None:
        # 메모 칸에 글자를 치는 중이면 단축키가 아니라 글자다 — 판정으로 먹지 않는다.
        if event.widget is self._memo:
            return
        self._submit(action)

    def _show_current(self) -> None:
        item = self._ctl.start_current()  # 화면에 띄우는 순간 started(acceptance ②)
        self._body.configure(state="normal")
        self._body.delete("1.0", "end")
        if item is None:
            self._finish()
            return
        self._body.insert("1.0", self._ctl.current_text())
        self._body.configure(state="disabled")
        self._body.yview_moveto(0)
        self._progress.configure(text=f"{self._ctl.position}/{self._ctl.total}  {item.slug}")
        self._code.current(0)
        self._memo.delete(0, "end")
        self._root.focus_set()
        self._refresh_elapsed()  # 새 항목은 0초부터 — 앞 항목 시간이 남아 보이지 않게

    def _submit(self, action: str) -> None:
        if self._ctl.done:
            return
        code_value = self._code.get()
        code = None if code_value == _NO_CODE_LABEL else code_value
        try:
            self._ctl.submit(action, failure_code=code, note=self._memo.get())
        except SubmissionRefusedError as exc:
            self._status.configure(text=str(exc))
            return
        self._status.configure(text="")
        self._show_current()

    def _refresh_elapsed(self) -> None:
        """경과 표시 — 30초 미만은 주황(막지 않는다 · OPS-90 판정은 집계가 한다)."""
        seconds = self._ctl.elapsed_seconds()
        if seconds is None:
            self._elapsed.configure(text="")
        else:
            color = _COLOR_FAST if seconds < HIT_FLOOR_SECONDS else _COLOR_NORMAL
            self._elapsed.configure(text=f"경과 {seconds}초", fg=color)

    def _tick(self) -> None:
        self._refresh_elapsed()
        if not self._ctl.done:
            self._root.after(1000, self._tick)

    def _finish(self) -> None:
        """세션 종료 화면 — 요약을 창과 stdout에 낸다(한 번만)."""
        self._ctl.close()
        text = self._ctl.summary_text()
        self._body.configure(state="normal")
        self._body.delete("1.0", "end")
        self._body.insert("1.0", text.lstrip("\n") + "\n창을 닫으면 끝납니다.\n")
        self._body.configure(state="disabled")
        self._progress.configure(text=f"끝 — {self._ctl.total}건 중 판정 완료")
        self._elapsed.configure(text="")
        for btn in self._buttons:
            btn.configure(state="disabled")
        self.print_summary()

    def print_summary(self) -> None:
        if not self._summary_printed:
            sys.stdout.write(self._ctl.summary_text())
            sys.stdout.flush()
            self._summary_printed = True

    def on_close(self) -> None:
        """창 닫기(X) — 열린 항목은 aborted로 남기고 요약을 낸 뒤 닫는다."""
        self._ctl.close()
        self.print_summary()
        self._root.destroy()


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점 — exit 0 정상(중도 종료·창 닫기 포함) / 1 입력 실패·tkinter 부재."""
    parser = argparse.ArgumentParser(
        prog="review_session_gui",
        description="검수 세션 GUI — 터미널 review_session과 같은 기록을 창에서 낸다(EOS-199).",
    )
    parser.add_argument(
        "--queue", required=True, help="검수 큐 또는 코퍼스 JSONL(slug 키를 갖는 행)"
    )
    parser.add_argument("--events", required=True, help="타이머 이벤트 JSONL 출력 경로(append)")
    parser.add_argument("--verdicts", required=True, help="판정 JSONL 출력 경로(append)")
    parser.add_argument("--reviewer-id", required=True, help="검수자 핸들(학생 축 아님)")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="이벤트 파일에 이미 종결된 CU를 건너뛴다(이중 계측 방지)",
    )
    parser.add_argument("--limit", type=int, default=0, help="이번 세션에서 볼 최대 건수(0=전부)")
    args = parser.parse_args(argv)

    # 입력 판정은 tkinter보다 먼저 — 큐 0건은 창을 띄우기 전에 exit 1(터미널판과 같은 판정).
    items = prepare_session_items(Path(args.queue), args.limit)
    if items is None:
        return 1

    try:
        import tkinter as tk
    except ImportError as exc:
        print(
            f"[실행 실패] {type(exc).__name__}: tkinter를 불러오지 못했다 — "
            "python.org 설치본(Tcl/Tk 포함)을 쓰거나 터미널판 review_session을 쓰십시오.",
            file=sys.stderr,
        )
        return 1

    controller = ReviewController(
        items,
        events_path=Path(args.events),
        verdicts_path=Path(args.verdicts),
        reviewer_id=args.reviewer_id,
        resume=args.resume,
    )
    if controller.skipped_completed:
        print(
            f"재개: 이미 종결된 {controller.skipped_completed}건을 건너뜁니다(이중 계측 방지).",
            flush=True,
        )
    root = tk.Tk()
    window = ReviewWindow(root, controller)
    try:
        root.mainloop()
    finally:
        # 창이 어떤 경로로 사라지든(예외·강제 종료) 열린 항목은 aborted로 남긴다.
        controller.close()
        window.print_summary()
    return 0


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    raise SystemExit(main())
