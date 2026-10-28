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
    첫 항목은 **창이 실제로 화면에 보인 뒤**에 띄운다(창이 뜨기 전 시간이 HIT에 섞이지 않게).
  - 승인·수정승인·반려 → `finished` + 판정 파일 1행.
  - 보류·종료·**창 닫기** → `aborted`(판정 파일에는 쓰지 않는다 — pending은 판정이 아니다).

## 기록 오염 방지 (리뷰 P1·P2 반영)

이 창의 기록은 HIT(검수 시간) 지표가 된다. 그래서 *잘못된 기록 1건*이 *기록 실패 1건*보다 나쁘다.

  1. **기록 전 거부** — 스키마가 받지 않을 제출(사유 없는 메모·2000자 초과 메모 등)은 쓰기 *전에*
     `SubmissionRefusedError`로 거부한다. 규칙은 스키마(`ReviewTimerEvent`)에서 읽어 오고
     (메모 상한), 마지막으로 같은 값으로 `finish_review`를 **시험 생성**해 스키마 검증을
     통과하는지 본다 — 규칙이 두 곳에서 갈라져도 쓰기 전에 걸린다.
  2. **즉시 확정 금지** — 맨 글자 단축키(a/e/r/s/q)는 없다. 판정은 버튼으로만 하며, 항목이 뜬 직후
     `INPUT_LOCK_SECONDS`(1초) 동안은 버튼이 꺼지고(창) 제어기도 같은 시간 안의 제출을 거부한다
     (이중 방어 — 더블클릭·키 자동반복이 읽지 않은 다음 항목에 판정을 남기지 않게).
  3. **쓰기 실패는 보이게, 중복은 없게** — 쓰기 전에 기록 파일이 열리는지 먼저 확인해(Excel 등이
     잡고 있으면 실패) 아무것도 쓰지 않고 거부한다. 그래도 쓰는 도중 실패하면 그 항목을 닫힌 것으로
     처리하고 세션을 **정지**한다 — 같은 항목에 `finished`가 두 번 남지 않는다(2건이면
     `hit_cu_metrics`가 anomaly로 표본에서 뺀다).
  4. **예상 못한 예외도 침묵하지 않는다** — 창 아래 빨간 글씨 `기록 실패: <예외타입명>` + 로그.

## 창 로직과 위젯 분리 (acceptance ④)

`ReviewController`·`attempt_submit`은 tkinter를 모른다 — CI(디스플레이 없음)에서 그대로 테스트된다.
tkinter는 `ReviewWindow`(창)와 `main()` 안에서만 **지연 import**한다. 그래서 이 모듈을 import하는
것만으로는 tkinter가 필요 없다.

## HIT 하한 가드(OPS-90)와의 관계 (acceptance ⑤)

30초 미만 판정을 **막지 않는다** — 막으면 "기다렸다 누르기"라는 위장 시간이 생긴다. 판정은 집계
쪽(`ops/hit_cu_metrics`)이 한다. 창은 경과 시간을 1초마다 보여주고 30초 미만이면 주황색으로 칠해,
검수자가 자기 속도를 알게만 한다. 1초 입력 잠금은 연타 흡수용이며 30초 하한과 무관하다.

사용(Windows PowerShell 예 — 런북 `docs/ops/eos197_authoring_round_runbook.md` [J-G]):
    python -m whymath_backend.harness.review_session_gui \\
        --queue data/review/queue.jsonl \\
        --events data/review/timer_events.jsonl \\
        --verdicts data/review/verdicts.jsonl \\
        --reviewer-id kiki [--resume] [--limit 30]

exit code: 0 정상 종료(중도 종료·창 닫기 포함 — 중단도 기록된 사실이다) / 1 입력 실패(파일 부재·
검수 대상 0건)·tkinter 부재·**기록 실패로 세션 정지**.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

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
from whymath_backend.harness.review_timer import finish_review, load_events_jsonl
from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.review_timer import (
    VERDICT_APPROVED_WITH_EDIT,
    ReviewTimerEvent,
    ReviewTimerEventType,
)

if TYPE_CHECKING:  # 런타임에는 창을 띄울 때만 import한다(CI 헤드리스·acceptance ④)
    import tkinter as tk

__all__ = [
    "FAILURE_CODE_LABELS",
    "HIT_FLOOR_SECONDS",
    "INPUT_LOCK_SECONDS",
    "NOTE_MAX_CHARS",
    "RecordingFailedError",
    "ReviewController",
    "SubmissionRefusedError",
    "Draft",
    "HistoryEntry",
    "ReviewView",
    "SubmitFeedback",
    "attempt_submit",
    "main",
]

logger = logging.getLogger(__name__)

#: 판정 행동 — 터미널 판정 키(`a/e/r/s/q`)와 같은 폐쇄 집합이다(창에서는 버튼으로만 고른다).
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

#: 항목이 뜬 직후 판정을 받지 않는 시간(초) — 더블클릭·키 자동반복 흡수용(리뷰 P1-2).
#: 창은 이 시간 동안 버튼을 끄고, 제어기는 같은 시간 안의 제출을 거부한다(이중 방어).
INPUT_LOCK_SECONDS = 1.0
_INPUT_LOCK_NS = int(INPUT_LOCK_SECONDS * 1_000_000_000)


def _schema_note_max_length() -> int:
    """메모 상한을 **스키마에서** 읽는다 — 규칙이 이 모듈과 스키마 두 곳에서 갈라지지 않게.

    `ReviewTimerEvent.failure_note`의 `max_length` 제약(pydantic 메타데이터)을 찾는다. 못 찾으면
    import 시점에 실패한다 — 조용히 다른 값을 쓰면 그게 바로 갈라짐이다.
    """
    field = ReviewTimerEvent.model_fields["failure_note"]
    for meta in field.metadata:
        limit = getattr(meta, "max_length", None)
        if isinstance(limit, int):
            return limit
    raise RuntimeError(
        "ReviewTimerEvent.failure_note에서 max_length 제약을 찾지 못했다 — 메모 상한 재사용 경로가 "
        "깨졌다(스키마 변경 확인)"
    )


#: 메모 최대 글자 수 — 스키마 `failure_note` 상한과 같은 값(재사용).
NOTE_MAX_CHARS: int = _schema_note_max_length()


class SubmissionRefusedError(ValueError):
    """판정 제출 거부 — **아무것도 기록하지 않았다**. 메시지는 화면에 그대로 보여준다."""


class RecordingFailedError(RuntimeError):
    """기록 도중 실패 — 세션을 **정지**했다. 메시지(한국어 안내)는 화면에 그대로 보여준다.

    이 예외가 나면 그 항목은 닫힌 것으로 처리돼 다시 제출되지 않는다(`finished` 중복 방지).
    """


def validate_submission(action: str, code: GenerationFailureCode | None, memo: str | None) -> None:
    """입력 규칙 — 터미널 프롬프트의 의미 + 스키마 제약을 **쓰기 전에** 한국어로 거부한다.

    순서가 곧 안내 우선순위다(먼저 걸리는 이유 하나만 보여준다).
    """
    if action == "rejected" and code is None:
        raise SubmissionRefusedError("반려는 사유(F1~F8)를 골라야 제출됩니다.")
    if action not in ("rejected", VERDICT_APPROVED_WITH_EDIT) and (code or memo):
        # 터미널은 승인·보류·종료에서 사유·메모를 묻지 않는다 — 받아서 버리면 조용한 유실이다.
        raise SubmissionRefusedError(
            "승인·보류·종료에는 사유·메모가 기록되지 않습니다. 남기려면 수정승인이나 반려를 쓰고, "
            "아니면 사유·메모 칸을 비우십시오."
        )
    if memo is not None and code is None:
        # 스키마: failure_note는 failure_code 부기로만 허용(자유 텍스트 단독 금지 — §4).
        raise SubmissionRefusedError(
            "메모를 남기려면 사유(F1~F8)를 먼저 고르세요 — 메모는 사유에 붙는 설명으로만 "
            "기록됩니다. 사유 없이 수정승인하려면 메모 칸을 비우세요."
        )
    if memo is not None and len(memo) > NOTE_MAX_CHARS:
        raise SubmissionRefusedError(
            f"메모는 {NOTE_MAX_CHARS}자까지입니다(지금 {len(memo)}자). 줄여서 다시 누르세요."
        )


def _schema_check(
    opened: OpenReview,
    *,
    action: str,
    code: GenerationFailureCode | None,
    memo: str | None,
    reviewer_id: str,
) -> None:
    """같은 값으로 `finished` 이벤트를 **시험 생성**한다(쓰지 않는다) — 최종 안전망.

    `validate_submission`이 스키마 규칙 하나를 놓쳐도 여기서 걸린다 — 기록 *전에*. 로그와 화면에는
    실패 필드 위치만 남긴다(ValidationError 문자열은 입력값=메모를 포함하므로 쓰지 않는다).
    """
    verdict: Any = action
    try:
        finish_review(
            review_session_id=opened.review_session_id,
            cu_slug=opened.item.slug,
            reviewer_id=reviewer_id,
            verdict=verdict,
            elapsed_ms=None,
            failure_code=code,
            failure_note=memo,
            content_fingerprint=opened.fingerprint,
        )
    except ValidationError as exc:
        fields = sorted(
            {".".join(str(p) for p in err["loc"]) or "(모델 규칙)" for err in exc.errors()}
        )
        logger.warning(
            "검수 창 제출 거부(스키마 시험 생성 실패): %s slug=%s fields=%s",
            type(exc).__name__,
            opened.item.slug,
            fields,
        )
        raise SubmissionRefusedError(
            f"기록 규칙에 맞지 않아 제출하지 않았습니다(검사 항목: {', '.join(fields)}). "
            "사유·메모를 확인하세요. 아무것도 기록하지 않았습니다."
        ) from None


#: 판정값 → 화면 라벨(다시 보기 표시용).
VERDICT_LABELS: dict[str, str] = {
    "approved": "승인",
    VERDICT_APPROVED_WITH_EDIT: "수정승인",
    "rejected": "반려",
}


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """판정 파일의 판정 1행 — 다시 보기(◀/▶) 목록의 한 칸. 보류·종료·중단은 판정이 아니라 없다.

    item은 이번 큐에서 slug로 찾은 본문이다(큐에 없는 slug면 None — 본문 없이 판정만 보여준다).
    """

    slug: str
    verdict: str
    failure_code: str | None
    failure_note: str | None
    item: ReviewItem | None


@dataclass(frozen=True, slots=True)
class Draft:
    """현재 문항에 입력하던 사유·메모 — 다시 보기 왕복 동안 제어기가 맡아 둔다."""

    failure_code: str | None
    note: str


@dataclass(frozen=True, slots=True)
class ReviewView:
    """다시 보기 화면 1장 — 판정 요약(눈에 띄게 표시)과 본문(터미널과 같은 렌더)."""

    position: int  # 1-기반(k)
    total: int  # N
    verdict_block: str
    body: str


def _load_verdict_history(
    verdicts_path: Path, items_by_slug: dict[str, ReviewItem]
) -> tuple[list[HistoryEntry], str | None]:
    """판정 파일을 **파일 순서대로** 읽어 판정 3종 행만 이력으로 만든다 — (이력, 읽기 문제 요약).

    파일이 없으면 빈 이력(첫 세션). 읽을 수 없거나 깨진 줄이 있으면 읽은 만큼만 쓰고 문제를
    돌려준다(침묵 금지 — 로그에 예외 타입명, 화면에 요약). 다시 보기는 읽기 전용이라 이 실패가
    판정을 막지는 않는다.
    """
    entries: list[HistoryEntry] = []
    try:
        if not verdicts_path.exists():
            return entries, None
        lines = verdicts_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(
            "검수 창 이전 판정 기록 읽기 실패: %s file=%s", type(exc).__name__, verdicts_path
        )
        return entries, f"이전 판정 기록을 읽지 못했습니다({type(exc).__name__})"
    bad = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if not isinstance(row, dict):
            bad += 1
            continue
        slug, verdict = row.get("slug"), row.get("verdict")
        if not isinstance(slug, str) or verdict not in CONCLUDING_ACTIONS:
            continue  # 판정이 아닌 행(또는 다른 형식) — 다시 보기 대상 아님
        code, note = row.get("failure_code"), row.get("failure_note")
        entries.append(
            HistoryEntry(
                slug=slug,
                verdict=str(verdict),
                failure_code=code if isinstance(code, str) else None,
                failure_note=note if isinstance(note, str) else None,
                item=items_by_slug.get(slug),
            )
        )
    if bad:
        logger.warning(
            "검수 창 이전 판정 기록에 읽을 수 없는 줄 %d건: JSONDecodeError file=%s",
            bad,
            verdicts_path,
        )
        return entries, f"이전 판정 기록에 읽을 수 없는 줄이 {bad}건 있어 건너뛰었습니다"
    return entries, None


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
        self._halted_reason: str | None = None
        # 다시 보기(◀/▶ — 읽기 전용). 이력은 판정 파일 순서 그대로: 시작 시 파일에서 읽고(이전
        # 세션 포함), 이번 세션의 판정은 파일에 쓴 순서대로 덧붙인다.
        self._items_by_slug = {item.slug: item for item in items}
        self._history, self._history_problem = _load_verdict_history(
            verdicts_path, self._items_by_slug
        )
        self._review_pos: int | None = None  # None = 지금 판정할 문항 화면
        self._draft: Draft | None = None  # 다시 보기 왕복 동안 맡아 둔 입력
        self._lock_since_ns: int | None = None  # 입력 잠금 기준 시각(표시·복귀 시점)

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
    def halted(self) -> bool:
        """기록 실패로 세션을 정지했다 — 더는 판정을 받지 않는다."""
        return self._halted_reason is not None

    @property
    def halted_reason(self) -> str | None:
        """정지 사유(화면 안내문) — 정지하지 않았으면 None."""
        return self._halted_reason

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
        HIT가 부풀거나 unfinished로 오분류된다. 정지한 세션은 새 항목을 열지 않는다.
        """
        item = self.current
        if item is None or self._open is not None or self.halted:
            return item
        self._open = open_review_item(
            item,
            events_path=self._events_path,
            reviewer_id=self._reviewer_id,
            monotonic_ns=self._monotonic_ns,
            now_utc=self._now_utc,
        )
        self._events_written += 1
        self._lock_since_ns = self._open.t0_ns  # 표시 순간부터 입력 잠금
        self._draft = None  # 새 문항 — 앞 문항 입력은 남기지 않는다
        return item

    # ── 다시 보기(◀/▶ · 읽기 전용 — 이벤트를 쓰지 않는다) ────────────────────
    @property
    def history(self) -> tuple[HistoryEntry, ...]:
        """판정 이력(판정 파일 순서) — 승인·수정승인·반려만. 보류·종료·중단은 판정이 아니다."""
        return tuple(self._history)

    @property
    def history_problem(self) -> str | None:
        """이전 판정 기록을 읽다 생긴 문제(화면 안내용) — 없으면 None."""
        return self._history_problem

    @property
    def reviewing(self) -> bool:
        """다시 보기 중이다 — 판정을 받지 않는다."""
        return self._review_pos is not None

    @property
    def can_review_back(self) -> bool:
        """◀ 가능 — 판정 이력이 있고, 다시 보기 중이면 맨 앞이 아니다."""
        if not self._history:
            return False
        return self._review_pos is None or self._review_pos > 0

    @property
    def can_review_forward(self) -> bool:
        """▶ 가능 — 다시 보기 중일 때만(맨 끝 다음은 지금 판정할 문항으로 돌아간다)."""
        return self._review_pos is not None

    @property
    def draft(self) -> Draft | None:
        """다시 보기에 들어가며 맡긴 입력 — 현재 문항으로 돌아오면 창이 이것을 되살린다."""
        return self._draft

    def review_back(self, draft: Draft | None = None) -> bool:
        """◀ 한 칸 — 움직였으면 True. 현재 문항 화면에서 들어갈 때 `draft`(입력 중이던 사유·메모)를
        맡긴다. 이벤트는 쓰지 않으며 현재 문항의 시계는 계속 흐른다(started는 그대로 열려 있다).
        """
        if not self.can_review_back:
            return False
        if self._review_pos is None:
            self._draft = draft
            self._review_pos = len(self._history) - 1
        else:
            self._review_pos -= 1
        return True

    def review_forward(self) -> bool:
        """▶ 한 칸 — 움직였으면 True. 마지막 다음은 지금 판정할 문항으로 돌아가며, 그때 입력 잠금을
        다시 건다(돌아오자마자 연타가 판정이 되지 않게).
        """
        if self._review_pos is None:
            return False
        if self._review_pos < len(self._history) - 1:
            self._review_pos += 1
            return True
        self._review_pos = None
        self._lock_since_ns = self._monotonic_ns()
        return True

    def review_view(self) -> ReviewView | None:
        """다시 보기 화면 — 다시 보기 중이 아니면 None."""
        if self._review_pos is None:
            return None
        entry = self._history[self._review_pos]
        position, total = self._review_pos + 1, len(self._history)
        lines = [f"이 문항의 판정: {VERDICT_LABELS.get(entry.verdict, entry.verdict)}"]
        if entry.failure_code is not None:
            known = _code_or_none(entry.failure_code)
            label = FAILURE_CODE_LABELS[known] if known is not None else ""
            lines.append(f"사유: {entry.failure_code}" + (f" — {label}" if label else ""))
        else:
            lines.append("사유: (없음)")
        lines.append(f"메모: {entry.failure_note}" if entry.failure_note else "메모: (없음)")
        if entry.item is not None:
            buf = io.StringIO()
            render_item(buf, position, total, entry.item)
            body = buf.getvalue().lstrip("\n")
        else:
            body = (
                f"[{position}/{total}] {entry.slug}\n  (이 문항의 본문은 이번 검수 큐에 없어 "
                "보여줄 수 없습니다 — 판정만 표시합니다)\n"
            )
        return ReviewView(
            position=position, total=total, verdict_block="\n".join(lines) + "\n", body=body
        )

    def submit(
        self,
        action: str,
        failure_code: GenerationFailureCode | str | None = None,
        note: str | None = None,
    ) -> str:
        """판정 1건 제출 — 종결 종류(`approved`·…·`aborted`)를 돌려준다.

        검사 순서(앞에서 걸리면 **아무것도 적지 않는다** — 항목은 열린 채, 시계도 계속 간다):
          ① 정지 여부 ② 행동·열린 항목 ③ 입력 규칙(`validate_submission`) ④ 스키마 시험 생성
          ⑤ 입력 잠금(표시 후 `INPUT_LOCK_SECONDS`) ⑥ 기록 파일 쓰기 가능 사전 점검.
        여기까지는 `SubmissionRefusedError`. 그 뒤 실제 기록 도중 실패하면 항목을 닫힌 것으로
        처리하고 세션을 정지한 뒤 `RecordingFailedError`를 던진다(재제출로 `finished`가 두 번
        남지 않게).

        시계는 ⑤에서 **한 번만** 읽고 그 값을 기록에도 쓴다 — 터미널 종결과 같은 호출 횟수라
        같은 시계를 주입하면 경과 시간까지 같다(기록 동일성 ②).
        """
        if self._halted_reason is not None:
            raise SubmissionRefusedError(
                "세션이 기록 실패로 멈췄습니다 — 더는 판정을 받지 않습니다. 창을 닫으세요. "
                f"(정지 사유: {self._halted_reason})"
            )
        if self._review_pos is not None:
            raise SubmissionRefusedError(
                "다시 보기 중에는 판정할 수 없습니다 — ▶로 지금 판정할 문항에 돌아가세요. "
                "아무것도 기록하지 않았습니다."
            )
        if action not in ACTIONS:
            raise SubmissionRefusedError(f"알 수 없는 판정입니다: {action}")
        opened = self._open
        if opened is None:
            raise SubmissionRefusedError("화면에 띄운 항목이 없습니다(start_current 먼저).")
        code = _parse_failure_code(failure_code)
        memo = (note or "").strip() or None
        validate_submission(action, code, memo)
        concluding = action in CONCLUDING_ACTIONS
        if concluding:
            _schema_check(
                opened, action=action, code=code, memo=memo, reviewer_id=self._reviewer_id
            )
        now_ns = self._monotonic_ns()
        lock_base = self._lock_since_ns if self._lock_since_ns is not None else opened.t0_ns
        if now_ns - lock_base < _INPUT_LOCK_NS:
            raise SubmissionRefusedError(
                f"방금 표시된 항목입니다 — {INPUT_LOCK_SECONDS:g}초 뒤에 다시 누르세요"
                "(연타·자동반복 방지). 아무것도 기록하지 않았습니다."
            )
        self._preflight_writable(concluding)
        try:
            concluded = close_review_item(
                opened,
                action=action if concluding else None,
                failure_code=code,
                note=memo,
                events_path=self._events_path,
                verdicts_path=self._verdicts_path,
                reviewer_id=self._reviewer_id,
                monotonic_ns=lambda: now_ns,
                now_utc=self._now_utc,
            )
        except Exception as exc:  # 기록 도중 실패 — 삼키지 않고 정지·안내·로그
            raise RecordingFailedError(self._halt(opened, action, exc)) from exc
        self._open = None
        self._events_written += 1
        self._counts[concluded] += 1
        self._index += 1
        self._draft = None
        if concluding:  # 판정 파일에 쓴 그대로 다시 보기 이력에 덧붙인다(파일 순서 = 이력 순서)
            self._history.append(
                HistoryEntry(
                    slug=opened.item.slug,
                    verdict=concluded,
                    failure_code=code.value if code is not None else None,
                    failure_note=memo,
                    item=opened.item,
                )
            )
        if action == "quit":
            self._stopped_early = True
            self._closed = True
        return concluded

    def _preflight_writable(self, concluding: bool) -> None:
        """기록할 파일이 지금 쓰기로 열리는지 먼저 본다 — 실패면 아무것도 쓰지 않고 거부한다.

        Windows에서 판정 파일을 Excel로 열어 두면 쓰기 잠금이 걸린다. 이벤트를 쓴 뒤 판정 행에서
        실패하면 반쪽 기록이 남으므로, 둘 다 먼저 열어 본다(append 모드로 열고 바로 닫는다 — 내용은
        바뀌지 않는다). 아직 없는 파일은 건너뛴다(만드는 순간의 실패는 기록 단계의 정지가 받는다).
        """
        targets = [("이벤트", self._events_path)]
        if concluding:
            targets.append(("판정", self._verdicts_path))
        for label, path in targets:
            try:
                if path.exists():
                    with path.open("a", encoding="utf-8"):
                        pass
            except OSError as exc:
                logger.warning(
                    "검수 창 제출 거부(%s 파일 쓰기 불가): %s errno=%s file=%s",
                    label,
                    type(exc).__name__,
                    exc.errno,
                    path,
                )
                raise SubmissionRefusedError(
                    f"{label} 파일에 쓸 수 없어 제출하지 않았습니다({type(exc).__name__}). "
                    "Excel·메모장 등 다른 프로그램에 그 파일이 열려 있으면 닫고 같은 버튼을 다시 "
                    f"누르세요. 아무것도 기록하지 않았고 이 항목은 계속 열려 있습니다. 파일: {path}"
                ) from None

    def _halt(self, opened: OpenReview, action: str, exc: Exception) -> str:
        """기록 도중 실패 → 항목을 닫힌 것으로 처리하고 세션을 정지한다. 화면 안내문을 돌려준다.

        `_open`을 비우는 것이 핵심이다 — 비우지 않으면 재제출이 `finished`를 한 번 더 쓰고, 창
        닫기가 `aborted`를 덧붙인다. 무엇이 남았는지는 이벤트 파일을 다시 읽어 판정한다(3상태:
        남음/안 남음/모름 — 모름을 "안 남음"으로 접지 않는다).
        """
        self._open = None
        slug = opened.item.slug
        finished = self._finished_recorded(opened)
        if finished is True:
            self._events_written += 1  # 요약의 이벤트 수가 파일과 맞게(판정 수는 판정 파일 기준)
            state = (
                f"이벤트 파일에는 이 항목({slug})의 판정(finished)이 남았지만 판정 파일에는 쓰지 "
                "못했습니다. 이 항목은 다시 판정하지 않습니다 — 이 문구를 세션에 알려 주세요"
            )
        elif finished is False:
            state = (
                f"이 항목({slug})의 판정은 기록되지 않았습니다(시작만 남음) — 파일을 닫은 뒤 창을 "
                "다시 띄우면(--resume) 이 항목부터 다시 봅니다"
            )
        else:
            state = (
                f"이 항목({slug})의 판정이 이벤트 파일에 남았는지 확인하지 못했습니다 — 이 문구를 "
                "세션에 알려 주세요"
            )
        reason = (
            f"기록 실패({type(exc).__name__}): {state}. 판정·이벤트 파일이 Excel 등 다른 "
            "프로그램에 열려 있는지 확인하세요. 같은 항목이 두 번 기록되지 않도록 세션을 "
            "멈췄습니다 — 창을 닫으세요."
        )
        self._halted_reason = reason
        logger.error(
            "검수 창 기록 실패 — 세션 정지: %s slug=%s action=%s finished_recorded=%s errno=%s",
            type(exc).__name__,
            slug,
            action,
            finished,
            getattr(exc, "errno", None),
        )
        return reason

    def _finished_recorded(self, opened: OpenReview) -> bool | None:
        """이 열림(review_session_id)의 `finished`가 이벤트 파일에 있는가 — 못 읽으면 None."""
        try:
            events, _ = load_events_jsonl(self._events_path)
        except (OSError, ValueError) as exc:
            logger.error(
                "검수 창 정지 판정 중 이벤트 파일 재독 실패: %s file=%s",
                type(exc).__name__,
                self._events_path,
            )
            return None
        return any(
            event.review_session_id == opened.review_session_id
            and event.event_type == ReviewTimerEventType.FINISHED.value
            for event in events
        )

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


def _code_or_none(value: str) -> GenerationFailureCode | None:
    """이력의 사유 문자열 → 코드(라벨 조회용). 모르는 값이면 None — 라벨 없이 원문만 보여준다."""
    try:
        return GenerationFailureCode(value)
    except ValueError:
        return None


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


@dataclass(frozen=True, slots=True)
class SubmitFeedback:
    """창이 보여줄 제출 결과 — `attempt_submit`이 만든다(창 없이 테스트된다).

    accepted: 기록됐다(다음 항목으로). message: 상태줄 문구(성공이면 빈 문자열).
    halted: 더는 판정을 받으면 안 된다(창은 판정 버튼을 끈다).
    """

    accepted: bool
    message: str
    halted: bool


def attempt_submit(
    controller: ReviewController,
    action: str,
    *,
    failure_code: GenerationFailureCode | str | None = None,
    note: str | None = None,
) -> SubmitFeedback:
    """제출 1건을 시도하고 **어떤 실패도 화면 문구로** 바꾼다 — 창의 버튼이 부르는 유일한 경로.

    예상 못한 예외도 삼키지 않는다: 문구에 예외 타입명을 넣고, 로그에 타입명과 발생 위치(스택)를
    남긴다(메시지 본문은 입력값=메모를 담을 수 있어 로그에 넣지 않는다). 그 경우 안전을 위해 판정
    입력을 멈춘다(halted=True) — 원인 모를 상태에서 다음 판정을 받지 않는다.
    """
    try:
        controller.submit(action, failure_code=failure_code, note=note)
    except SubmissionRefusedError as exc:
        return SubmitFeedback(accepted=False, message=str(exc), halted=controller.halted)
    except RecordingFailedError as exc:
        return SubmitFeedback(accepted=False, message=str(exc), halted=True)
    except Exception as exc:  # 예상 못한 예외 — 침묵 금지(화면 + 로그)
        logger.error(
            "검수 창 제출 중 예상 못한 예외: %s action=%s\n%s",
            type(exc).__name__,
            action,
            "".join(traceback.format_tb(exc.__traceback__)),
        )
        return SubmitFeedback(
            accepted=False,
            message=(
                f"기록 실패: {type(exc).__name__} — 예상 못한 오류로 판정을 멈췄습니다. 창을 닫고 "
                "PowerShell 창의 오류 줄을 세션에 알려 주세요."
            ),
            halted=True,
        )
    return SubmitFeedback(accepted=True, message="", halted=False)


# ── 창 (tkinter — 여기서만 지연 import) ─────────────────────────────────────

_NO_CODE_LABEL = "(사유 없음)"
_FONT_CANDIDATES = ("맑은 고딕", "Malgun Gothic")
_COLOR_FAST = "#d97706"  # 30초 미만 — 주황(막지 않는다)
_COLOR_NORMAL = "#1f2937"
_COLOR_ERROR = "#b91c1c"
_COLOR_MUTED = "#6b7280"
_COLOR_REVIEW_BG = "#fef3c7"  # 다시 보기 — 연노랑 배경(판정 화면과 구별)
_COLOR_REVIEW_FG = "#92400e"
#: 창 쪽 잠금 해제는 제어기 잠금보다 살짝 늦게 — 버튼이 켜진 순간의 클릭이 제어기에서 거부되지 않게.
_UI_UNLOCK_MS = int(INPUT_LOCK_SECONDS * 1000) + 50


class ReviewWindow:
    """검수 창 — 위젯 배치와 이벤트 연결만 한다. 판정·기록·다시 보기 상태는 전부 `ReviewController`.

    키보드 단축키는 없다(리뷰 P1-2): 판정은 버튼으로만 한다. 맨 글자 단축키는 메모 칸 클릭 전
    타이핑·드롭다운 포커스·Caps Lock·한/영 상태에서 읽지 않은 항목에 판정을 남겼다.
    """

    def __init__(self, root: tk.Tk, controller: ReviewController) -> None:
        import tkinter as tk
        from tkinter import font as tkfont
        from tkinter import scrolledtext, ttk

        self._root = root
        self._ctl = controller
        self._summary_printed = False
        self._failure: str | None = None
        self._shown = False
        self._lock_token = 0
        # 예약된 after 작업 — 창을 닫을 때 취소한다(닫힌 뒤 실행돼 Tcl 오류가 찍히지 않게).
        self._tick_job: str | None = None
        self._unlock_job: str | None = None

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

        # 다시 보기 배너 — 다시 보기 중에만 글자가 찬다(판정할 수 없다는 사실을 위에 크게).
        self._banner = tk.Label(root, font=bold_font, anchor="w", padx=12, pady=4)
        self._banner_bg = self._banner.cget("bg")
        self._banner.pack(fill="x", padx=12)

        self._body = scrolledtext.ScrolledText(
            root, wrap="word", font=body_font, padx=10, pady=10, height=20
        )
        self._body.tag_configure(
            "verdict", font=bold_font, background=_COLOR_REVIEW_BG, foreground=_COLOR_REVIEW_FG
        )
        self._body.pack(fill="both", expand=True, padx=12)

        form = tk.Frame(root, padx=12, pady=6)
        form.pack(fill="x")
        tk.Label(form, text="사유 — 반려: 필수 · 수정승인: 선택", font=ui_font).grid(
            row=0, column=0, sticky="w"
        )
        values = [_NO_CODE_LABEL] + [
            f"{code.value} — {label}" for code, label in FAILURE_CODE_LABELS.items()
        ]
        self._code = ttk.Combobox(form, values=values, state="readonly", width=28, font=ui_font)
        self._code.current(0)
        self._code.grid(row=0, column=1, sticky="w", padx=6)
        tk.Label(
            form, text=f"메모 — 사유를 고른 경우만 · {NOTE_MAX_CHARS}자까지", font=ui_font
        ).grid(row=0, column=2, sticky="w", padx=6)
        self._memo = tk.Entry(form, font=ui_font, width=40)
        self._memo.grid(row=0, column=3, sticky="we")
        form.columnconfigure(3, weight=1)
        tk.Label(
            form,
            text="승인·보류·종료는 사유·메모를 비워 두세요(채워져 있으면 거부됩니다).",
            font=ui_font,
            fg=_COLOR_MUTED,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        buttons = tk.Frame(root, padx=12, pady=6)
        buttons.pack(fill="x")
        # 다시 보기 버튼(◀ ▶ 문자 + 글자 병기 — 이미지 파일 없이. 맑은 고딕은 ◀▶를 갖고 있고,
        # 없는 글꼴이어도 '이전'·'다음' 글자가 뜻을 전한다).
        self._back = tk.Button(
            buttons,
            text="◀ 이전",
            font=ui_font,
            width=8,
            takefocus=False,
            state="disabled",
            command=self._go_back,
        )
        self._back.pack(side="left", padx=(0, 4))
        self._forward = tk.Button(
            buttons,
            text="다음 ▶",
            font=ui_font,
            width=8,
            takefocus=False,
            state="disabled",
            command=self._go_forward,
        )
        self._forward.pack(side="left", padx=(0, 16))
        self._buttons: list[tk.Button] = []
        for label, action in (
            ("승인", "approved"),
            ("수정승인", VERDICT_APPROVED_WITH_EDIT),
            ("반려", "rejected"),
            ("보류", "skip"),
            ("종료", "quit"),
        ):
            btn = tk.Button(
                buttons,
                text=label,
                font=ui_font,
                width=10,
                takefocus=False,  # 키보드(스페이스)로 버튼이 눌리지 않게 — 판정은 마우스 클릭만
                state="disabled",  # 첫 항목이 뜨고 잠금이 풀릴 때 켠다
                command=self._button_command(action),
            )
            btn.pack(side="left", padx=4)
            self._buttons.append(btn)
        self._lock_label = tk.Label(buttons, font=ui_font, anchor="w", fg=_COLOR_MUTED)
        self._lock_label.pack(side="left", padx=12)

        self._status = tk.Label(root, font=ui_font, anchor="w", fg=_COLOR_ERROR, padx=12)
        self._status.pack(fill="x", pady=(0, 8))
        if controller.history_problem:
            self._status.configure(
                text=(
                    f"{controller.history_problem} — 다시 보기(◀)에서 빠진 판정이 "
                    "있을 수 있습니다."
                ),
                fg=_COLOR_MUTED,
            )

        # 첫 항목은 창이 실제로 보인 뒤에 띄운다 — started가 창 표시 전에 찍히면 그 사이 시간이
        # 첫 항목의 HIT에 섞인다. 이미 보이는 창이면 바로(유휴 시점에) 띄운다.
        root.update_idletasks()
        if root.winfo_viewable():
            root.after_idle(self._first_show)
        else:
            root.bind("<Map>", self._on_map, add="+")

    @property
    def failed(self) -> bool:
        """창 쪽에서 기록 실패·예상 못한 오류를 만났다(종료 코드 1의 근거)."""
        return self._failure is not None or self._ctl.halted

    @property
    def failure_message(self) -> str | None:
        """정지 사유(화면 안내문) — 정지하지 않았으면 None."""
        return self._ctl.halted_reason or self._failure

    def _on_map(self, event: tk.Event[tk.Misc]) -> None:
        # <Map>은 자식 위젯에도 전달된다 — 최상위 창 자신이 보였을 때만, 한 번만.
        if event.widget is not self._root or self._shown:
            return
        self._root.after_idle(self._first_show)

    def _first_show(self) -> None:
        if self._shown:
            return
        self._shown = True
        try:
            self._root.lift()
            self._root.focus_force()
        except Exception as exc:  # 앞으로 올리기는 편의 기능 — 실패해도 검수는 계속(로그만)
            logger.warning("검수 창 앞으로 올리기 실패: %s", type(exc).__name__)
        self._show_current()
        self._tick()

    def _button_command(self, action: str) -> Callable[[], None]:
        def command() -> None:
            self._submit(action)

        return command

    def _set_buttons(self, state: Literal["normal", "disabled"]) -> None:
        for btn in self._buttons:
            btn.configure(state=state)

    def _set_inputs(self, state: Literal["normal", "disabled"]) -> None:
        """사유·메모 입력 칸 — 다시 보기 중에는 끈다."""
        self._code.configure(state="readonly" if state == "normal" else "disabled")
        self._memo.configure(state=state)

    def _refresh_nav(self) -> None:
        """◀/▶ 상태 — 판정 중·정지·끝이면 둘 다 끈다. 상태 판정은 제어기가 한다."""
        live = not self.failed and not self._ctl.done
        self._back.configure(state="normal" if live and self._ctl.can_review_back else "disabled")
        self._forward.configure(
            state="normal" if live and self._ctl.can_review_forward else "disabled"
        )

    def _set_body(self, text: str, verdict_block: str | None = None) -> None:
        self._body.configure(state="normal")
        self._body.delete("1.0", "end")
        if verdict_block is not None:
            self._body.insert("1.0", verdict_block, ("verdict",))
            self._body.insert("end", "\n" + text)
        else:
            self._body.insert("1.0", text)
        self._body.configure(state="disabled")
        self._body.yview_moveto(0)

    def _show_current(self) -> None:
        try:
            item = self._ctl.start_current()  # 화면에 띄우는 순간 started(acceptance ②)
        except Exception as exc:  # started를 못 썼다 — 판정을 받지 않고 멈춘다(침묵 금지)
            logger.error("검수 창 항목 열기(started) 실패: %s", type(exc).__name__)
            self._enter_failure(
                f"기록 실패: {type(exc).__name__} — 다음 항목을 여는 기록(started)을 쓰지 "
                "못했습니다. 이벤트 파일이 다른 프로그램(Excel 등)에 열려 있는지 확인하고, "
                "창을 닫은 뒤 다시 띄우세요(--resume)."
            )
            return
        if item is None:
            self._finish()
            return
        self._code.current(0)
        self._memo.delete(0, "end")
        self._render_current()
        self._root.focus_set()
        self._lock_inputs()

    def _render_current(self) -> None:
        """지금 판정할 문항 화면(다시 보기에서 돌아올 때도 쓴다 — started는 다시 쓰지 않는다)."""
        item = self._ctl.current
        if item is None:
            return
        self._set_body(self._ctl.current_text())
        self._progress.configure(text=f"{self._ctl.position}/{self._ctl.total}  {item.slug}")
        self._banner.configure(text="", bg=self._banner_bg)
        self._set_inputs("normal")
        self._refresh_elapsed()  # 새 항목은 0초부터 — 앞 항목 시간이 남아 보이지 않게
        self._refresh_nav()

    def _go_back(self) -> None:
        """◀ — 판정을 마친 문항을 거슬러 본다(읽기 전용 · 이벤트를 쓰지 않는다)."""
        if self.failed or self._ctl.done:
            return
        draft = None
        if not self._ctl.reviewing:  # 지금 문항을 떠난다 — 입력 중이던 사유·메모를 맡긴다
            code_value = self._code.get()
            draft = Draft(
                failure_code=None if code_value == _NO_CODE_LABEL else code_value,
                note=self._memo.get(),
            )
        if self._ctl.review_back(draft=draft):
            self._render_review()

    def _go_forward(self) -> None:
        """▶ — 한 칸 앞으로. 마지막 다음은 지금 판정할 문항(입력 복원 + 1초 잠금 재적용)."""
        if self.failed or self._ctl.done or not self._ctl.review_forward():
            return
        if self._ctl.reviewing:
            self._render_review()
            return
        self._render_current()
        draft = self._ctl.draft
        self._code.current(0)
        self._memo.delete(0, "end")
        if draft is not None:
            if draft.failure_code is not None and draft.failure_code in self._code.cget("values"):
                self._code.set(draft.failure_code)
            self._memo.insert(0, draft.note)
        self._lock_inputs()

    def _render_review(self) -> None:
        view = self._ctl.review_view()
        if view is None:
            return
        # 다시 보기 중: 판정 버튼·사유·메모를 모두 끈다(제어기도 submit을 거부한다 — 이중 방어).
        self._lock_token += 1  # 대기 중인 잠금 해제가 판정 버튼을 켜지 않게
        self._set_buttons("disabled")
        self._lock_label.configure(text="")
        self._code.set(_NO_CODE_LABEL)
        self._memo.delete(0, "end")
        self._set_inputs("disabled")
        self._set_body(view.body, verdict_block=view.verdict_block)
        self._banner.configure(
            text=(
                f"다시 보기 중 ({view.position}/{view.total}) — 판정할 수 없습니다. ▶로 돌아가세요"
            ),
            bg=_COLOR_REVIEW_BG,
        )
        self._refresh_nav()

    def _lock_inputs(self) -> None:
        """새 항목이 뜬 직후(또는 다시 보기에서 돌아온 직후) 판정 버튼을 잠근다 — 연타 방지."""
        self._lock_token += 1
        token = self._lock_token
        self._set_buttons("disabled")
        self._lock_label.configure(text=f"버튼은 {INPUT_LOCK_SECONDS:g}초 뒤에 켜집니다(연타 방지)")
        self._cancel_job(self._unlock_job)
        self._unlock_job = self._root.after(_UI_UNLOCK_MS, lambda: self._unlock_inputs(token))

    def _unlock_inputs(self, token: int) -> None:
        self._unlock_job = None  # 실행됐다 — 닫을 때 취소할 대상이 아니다
        # 그 사이 다음 항목·다시 보기로 넘어갔거나(다른 토큰) 멈췄으면 켜지 않는다.
        if token != self._lock_token or self.failed or self._ctl.done or self._ctl.reviewing:
            return
        self._set_buttons("normal")
        self._lock_label.configure(text="")

    def _submit(self, action: str) -> None:
        if self._ctl.done or self.failed:
            return
        code_value = self._code.get()
        code = None if code_value == _NO_CODE_LABEL else code_value
        feedback = attempt_submit(self._ctl, action, failure_code=code, note=self._memo.get())
        if feedback.halted:
            self._enter_failure(feedback.message)
            return
        if not feedback.accepted:
            self._status.configure(text=feedback.message, fg=_COLOR_ERROR)
            return
        self._status.configure(text="")
        self._show_current()

    def _enter_failure(self, message: str) -> None:
        """정지 상태 — 판정·다시 보기 버튼을 끄고 빨간 글씨로 사유를 남긴다. 창 닫기(X)는 된다."""
        self._failure = message
        self._lock_token += 1  # 대기 중인 잠금 해제가 버튼을 다시 켜지 않게
        self._set_buttons("disabled")
        self._refresh_nav()
        self._lock_label.configure(text="판정 정지 — 창을 닫으세요")
        self._status.configure(text=message, fg=_COLOR_ERROR)

    def _refresh_elapsed(self) -> None:
        """경과 표시 — 30초 미만은 주황(막지 않는다 · OPS-90 판정은 집계가 한다).

        다시 보기 중에도 지금 판정할 문항의 시계는 흐른다(started가 열려 있다) — 표시도 계속한다.
        """
        seconds = self._ctl.elapsed_seconds()
        if seconds is None:
            self._elapsed.configure(text="")
        else:
            color = _COLOR_FAST if seconds < HIT_FLOOR_SECONDS else _COLOR_NORMAL
            self._elapsed.configure(text=f"경과 {seconds}초", fg=color)

    def _tick(self) -> None:
        self._refresh_elapsed()
        self._tick_job = None
        if not self._ctl.done and not self.failed:
            self._tick_job = self._root.after(1000, self._tick)

    def _cancel_job(self, job: str | None) -> None:
        if job is None:
            return
        try:
            self._root.after_cancel(job)
        except Exception as exc:  # 이미 실행·취소된 작업 — 무해하지만 침묵하지 않는다
            logger.warning("검수 창 예약 작업 취소 실패: %s", type(exc).__name__)

    def _finish(self) -> None:
        """세션 종료 화면 — 요약을 창과 stdout에 낸다(한 번만)."""
        self._ctl.close()
        text = self._ctl.summary_text()
        self._set_body(text.lstrip("\n") + "\n창을 닫으면 끝납니다.\n")
        self._progress.configure(text=f"끝 — {self._ctl.total}건 중 판정 완료")
        self._elapsed.configure(text="")
        self._banner.configure(text="", bg=self._banner_bg)
        self._lock_token += 1
        self._set_buttons("disabled")
        self._refresh_nav()
        self._lock_label.configure(text="")
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
        self._cancel_job(self._tick_job)
        self._cancel_job(self._unlock_job)
        self._tick_job = self._unlock_job = None
        self._root.destroy()


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점 — exit 0 정상(중도 종료·창 닫기 포함) / 1 입력 실패·tkinter 부재·기록 실패."""
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
    window: ReviewWindow | None = None
    try:
        root = tk.Tk()
        window = ReviewWindow(root, controller)
        root.mainloop()
    finally:
        # 창이 어떤 경로로 사라지든(예외·강제 종료) 열린 항목은 aborted로 남긴다.
        controller.close()
        if window is not None:
            window.print_summary()
        else:
            sys.stdout.write(controller.summary_text())
            sys.stdout.flush()
    if (window is not None and window.failed) or controller.halted:
        reason = window.failure_message if window is not None else controller.halted_reason
        print(
            "[기록 실패] 검수 창이 기록 실패로 판정을 멈췄습니다 — 위 요약과 창의 빨간 안내문을 "
            f"세션에 알려 주세요. 사유: {reason}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    raise SystemExit(main())
