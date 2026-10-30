"""힌트 정답 누설 사람 판정 — Windows 팝업 창 + **판정 뒤** AI 권고 공개 (EOS-219).

EOS-210 터미널 도구(`harness/hint_verdict_session review`)와 **같은 작업 목록·같은 기록 계약**
(`hint_verdicts.jsonl` append 전용·내용 지문)으로 판정을 받되, 키보드 한 줄 입력 대신 창의
버튼으로 받는다. tkinter(표준 라이브러리)만 쓰므로 새 의존성은 0이다.

맹검 — 헌법 R19-01 ("사람이 판정을 입력하기 전에 AI 참고 판정을 보여주지 않는다")
-----------------------------------------------------------------------------
Kiki 선택(2026-10-30 · EOS-219 acceptance 정정): AI 권고는 **그 힌트의 사람 판정이 판정 파일에
append된 직후에만** 보여 준다. 판정 전 화면에 내는 것은 터미널 도구와 같은 다섯 칸(`review_view` —
문항·선택지·정답·힌트 단계·힌트 본문)과 고정 기준표(`RUBRIC_TEXT` — "무엇이 누설인가")뿐이다.
기계 판정·`gate_report`·목적(`purpose`)·기존 판정은 터미널 도구와 똑같이 내지 않는다.

집행 지점은 `GuiReviewController.reveal_recommendation`이다 — 이번 세션에서 **기록에 성공한**
hint_id가 아니면 `RecommendationLockedError`를 올린다(판정 전·건너뛰기·기록 실패 모두 거부).
창은 이 함수로만 권고를 얻으므로, 창 코드가 실수로 판정 전에 부르면 예외로 드러난다.

판정 행은 맹검 판정 그대로다(권고 공개 *전*에 기록된다). 공개 뒤 같은 창에서 판정을 바꾸는 경로는
없다 — 재판정은 맹검이 아니므로 터미널 도구의 `--rejudge`와 그 표기 규칙을 따른다. 그래서 이 창은
`--rejudge`를 받지 않는다.

**남는 한계(명시)**: 앞 힌트의 AI 이유를 본 판정자는 뒤 힌트에서 AI의 기준에 끌려갈 수 있다(교정
학습 효과). 이것은 "판정 전 권고 비노출"을 지키되 세션 전체의 독립성까지 보장하지는 못한다. 그
영향은 불일치 보고(`hint_ai_disagreements.json`)와 EOS-218(판정자 신뢰도·일치도)이 다룬다.

권고 파일 계약 — `<round>-review/hint_ai_recommendations.jsonl`
----------------------------------------------------------------
`HintAiRecommendation` 모델 JSON 1행(`schema_version="hint-ai-recommendation/v1"`): `hint_id` ·
`recommendation`(`leaked`/`not_leaked`) · `rationale`(1~2000자) · `author`(짧은 ID) · `created_at`
(시간대 포함) · `content_fingerprint`(작성 당시의 `hint_review_fingerprint`). 권고는 판정 행에 쓰지
않고 이 파일에만 둔다.

  - 형식 오류·hint_id 중복·판정 대상 밖 hint_id → **시작 거부**(exit 1 · `INPUT_ERROR=`)
  - 지문이 지금 내용과 다른 행 → **낡음(stale)**: 보여 주지 않고 "권고 없음(내용이 바뀜)"으로 표시,
    따로 센다(`AI_RECS_STALE`)
  - 파일 없음 → 권고 없이 판정만 한다("권고 없음" · 요약 `AI_RECS_FILE=MISSING`)

불일치 보고 — `<round>-review/hint_ai_disagreements.json`
-------------------------------------------------------
세션이 끝나면(완료·종료·창 닫기 모두) 판정 파일에서 **이 판정자·이 표본·지금 내용 지문**의 최신
판정(append 순서)을 권고와 비교해 불일치 목록 `[{hint_id, human, ai, ai_rationale}]`을 쓴다.
판정하지 않은 힌트의 권고는 이 파일에도 싣지 않는다(맹검 유지). stdout 요약 줄은 터미널 도구의
`SESSION_*` 줄에 `AI_RECS_FILE`·`AI_RECS_LOADED`·`AI_RECS_STALE`·`AI_AGREE`·`AI_DISAGREE`·
`AI_NO_REC`·`DISAGREEMENTS_PATH`를 더한다.

창 로직과 위젯 분리
------------------
`GuiReviewController`·권고 로더·불일치 보고는 tkinter를 모른다 — CI(디스플레이 없음)에서 그대로
테스트된다. tkinter는 `_import_tk()`(창을 만들 때)에서만 **지연 import**한다. tkinter가 없거나
디스플레이가 없으면 `GUI_UNAVAILABLE=<예외타입>`을 내고 exit 2.

실수 방지(터미널 도구와 같은 규칙)
---------------------------------
  - 쓰기 전 검증 — 판정은 `build_verdict`(터미널과 같은 함수)로 모델을 만든 뒤에만 쓴다
  - 쓰기 가능 사전 점검 — 창을 띄우기 전에 판정 파일을 append로 열어 본다(실패면 exit 2)
  - 입력 잠금 — 항목을 띄운 뒤 `INPUT_LOCK_SECONDS`(2초) 안의 기록은 거부한다
  - 확인 — 기록 버튼 뒤 "기록: … · 근거: … — 맞습니까?"를 한 번 더 묻는다
  - 시계 역행 — 판정 시각이 파일의 마지막 판정보다 이르면 쓰지 않고 세션을 멈춘다
  - 기록 실패 — append 실패(`OSError`)면 오류 창(예외 타입명) 후 창을 닫고 exit 2

exit code: 0 정상 종료(중간 종료·창 닫기 포함) / 1 입력 실패 / 2 기록 실패·창을 띄울 수 없음.

사용(Windows PowerShell — 런북 `docs/ops/eos219_*`):
    python -m whymath_backend.harness.hint_verdict_gui --round R \\
        --hints-jsonl data/runs/R-local/cu.hints.jsonl --reviewer kiki
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator

from whymath_backend.harness.hint_verdict_session import (
    DEFAULT_MANIFEST_NAME,
    DEFAULT_VERDICTS_NAME,
    EXIT_INPUT,
    EXIT_OK,
    EXIT_RECORD,
    INPUT_LOCK_SECONDS,
    REVIEWER_FORMAT_ERROR,
    SessionOutcome,
    WorkItem,
    already_done,
    build_verdict,
    load_review_inputs,
    preflight_writable,
    render_summary,
    review_dir,
)
from whymath_backend.ops.hint_human_verdicts import (
    RATIONALE_MAX_LENGTH,
    REVIEWER_ID_PATTERN,
    HintHumanVerdict,
    HintVerdict,
    SampleManifest,
    append_verdict,
    hint_review_fingerprint,
    load_verdicts,
    review_view,
)
from whymath_backend.ops.provenance_audit import default_runs_root

if TYPE_CHECKING:  # 런타임에는 창을 띄울 때만 import한다(CI 헤드리스)
    import tkinter as tk

__all__ = [
    "DEFAULT_DISAGREEMENTS_NAME",
    "DEFAULT_RECOMMENDATIONS_NAME",
    "RECOMMENDATION_SCHEMA",
    "RUBRIC_TEXT",
    "DisagreementReport",
    "GuiReviewController",
    "HintAiRecommendation",
    "ItemView",
    "RecommendationLockedError",
    "RecommendationReveal",
    "RecordResult",
    "build_disagreement_report",
    "load_recommendations",
    "main",
]

logger = logging.getLogger(__name__)

RECOMMENDATION_SCHEMA = "hint-ai-recommendation/v1"
DEFAULT_RECOMMENDATIONS_NAME = "hint_ai_recommendations.jsonl"
DEFAULT_DISAGREEMENTS_NAME = "hint_ai_disagreements.json"
_FINGERPRINT_PATTERN = r"^sha256:[0-9a-f]{64}$"

#: 판정 전에 보여 주는 유일한 보조 정보 — 고정 기준표(힌트마다 바뀌지 않으므로 AI 판정이 아니다).
RUBRIC_TEXT = (
    "무엇이 누설인가\n"
    "누설로 판정 —\n"
    "  ① 정답 값·정답 선택지를 직접 적음\n"
    "  ② 계산만 하면 바로 정답이 나오는 최종 식을 완성해 줌"
    "(학생이 할 핵심 판단·계산이 남지 않음)\n"
    "  ③ 정답을 가르는 결정적 판단(어느 선택지·어느 경우)을 대신 내림\n"
    "  ④ 정답과 같은 값을 다른 형태(분수↔소수 등)로 제시\n"
    "누설 아님 —\n"
    "  · 방향·개념·전략만 주고 학생이 핵심 계산·판단을 직접 해야 함\n"
    "  · 문제에 이미 있는 수·조건을 다시 언급\n"
    "  · 정답과 무관한 중간 정보"
)

_VERDICT_LABEL: dict[HintVerdict, str] = {
    HintVerdict.LEAKED: "누설",
    HintVerdict.NOT_LEAKED: "누설 아님",
}


# ──────────────────────────────────────────────────────────────────────────
# 권고 파일 계약
# ──────────────────────────────────────────────────────────────────────────
class HintAiRecommendation(BaseModel):
    """힌트 1건의 AI 권고(모듈 docstring '권고 파일 계약'). 필드는 전부 필수다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["hint-ai-recommendation/v1"]
    hint_id: str = Field(min_length=1)
    recommendation: HintVerdict
    rationale: str = Field(min_length=1, max_length=RATIONALE_MAX_LENGTH)
    author: str = Field(pattern=REVIEWER_ID_PATTERN)
    created_at: AwareDatetime
    content_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)

    @field_validator("rationale")
    @classmethod
    def _rationale_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("권고 이유(rationale)가 비었다")
        return value


def load_recommendations(
    path: Path, work_hint_ids: Iterable[str]
) -> tuple[dict[str, HintAiRecommendation], list[str]]:
    """권고 JSONL → ({hint_id: 권고}, 오류). 오류는 줄 번호·예외 타입명·필드 이름만 싣는다.

    오류: 읽기 실패 · JSON/객체 아님 · 계약 위반 · hint_id 중복 · 판정 대상 밖 hint_id.
    지문이 낡은 행은 오류가 아니다 — 그대로 돌려주고 낡음 판정은 제어기가 한다.
    """
    recommendations: dict[str, HintAiRecommendation] = {}
    errors: list[str] = []
    allowed = set(work_hint_ids)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return recommendations, [f"{path.name} 읽기 실패 — {type(exc).__name__}"]
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{line_no} JSON 파싱 실패 — {type(exc).__name__}")
            continue
        if not isinstance(parsed, dict):
            errors.append(f"{path.name}:{line_no} 객체가 아님({type(parsed).__name__})")
            continue
        try:
            rec = HintAiRecommendation.model_validate(parsed)
        except ValidationError as exc:
            fields = sorted(
                {".".join(str(p) for p in err["loc"]) or "<root>" for err in exc.errors()}
            )
            errors.append(
                f"{path.name}:{line_no} 권고 계약 위반 — {type(exc).__name__}({', '.join(fields)})"
            )
            continue
        if rec.hint_id in recommendations:
            errors.append(f"{path.name}:{line_no} hint_id {rec.hint_id} 권고가 두 번 나온다")
            continue
        if rec.hint_id not in allowed:
            errors.append(f"{path.name}:{line_no} hint_id {rec.hint_id}가 판정 대상 목록에 없다")
            continue
        recommendations[rec.hint_id] = rec
    return recommendations, errors


# ──────────────────────────────────────────────────────────────────────────
# 제어기 — tkinter 없이 동작한다
# ──────────────────────────────────────────────────────────────────────────
class RecommendationLockedError(RuntimeError):
    """기록에 성공하지 않은 힌트의 권고를 요청했다 — R19-01 집행 지점."""


@dataclass(frozen=True, slots=True)
class ItemView:
    """판정 화면 1건 — `review_view`의 다섯 칸 + 진행 표시뿐이다(권고·기계 판정 필드 없음)."""

    index: int
    total: int
    hint_id: str
    question_text: str | None
    choices: tuple[str, ...] | None
    answer: str | None
    hint_level: int
    hint_content: str


@dataclass(frozen=True, slots=True)
class RecordResult:
    """기록 시도 결과 — `recorded`(기록됨) · `rejected`(쓰지 않음·다시 입력) ·
    `record_failed`(정지)."""

    status: Literal["recorded", "rejected", "record_failed"]
    message: str
    hint_id: str | None = None


@dataclass(frozen=True, slots=True)
class RecommendationReveal:
    """기록 직후 공개하는 권고 — `state`: `shown` · `none`(권고 없음) · `stale`(내용이 바뀜)."""

    hint_id: str
    human: HintVerdict
    state: Literal["shown", "none", "stale"]
    ai: HintVerdict | None
    ai_rationale: str | None

    @property
    def agrees(self) -> bool | None:
        """사람 판정과 권고가 같은가 — 권고가 없으면 None(모른다 ≠ 일치)."""
        return None if self.ai is None else self.ai is self.human

    def text(self) -> str:
        """공개 패널 문구."""
        if self.state == "stale":
            return "AI 권고: 권고 없음(내용이 바뀜)"
        if self.state == "none" or self.ai is None:
            return "AI 권고: 권고 없음"
        return f"AI 권고: {_VERDICT_LABEL[self.ai]} — 이유: {self.ai_rationale}"


@dataclass(slots=True)
class DisagreementReport:
    """세션 끝 사람-AI 비교 — 이 판정자·이 표본·지금 내용 지문의 최신 판정만 센다."""

    agree: int = 0
    disagree: int = 0
    no_rec: int = 0
    disagreements: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def build_disagreement_report(
    verdicts_path: Path,
    items: Sequence[WorkItem],
    recommendations: Mapping[str, HintAiRecommendation],
    *,
    reviewer: str,
    sample_id: str,
) -> DisagreementReport:
    """판정 파일을 다시 읽어 사람-AI 일치·불일치를 센다(판정하지 않은 힌트는 싣지 않는다)."""
    report = DisagreementReport()
    if not verdicts_path.exists():
        verdicts: list[HintHumanVerdict] = []
    else:
        verdicts, load_errors = load_verdicts(verdicts_path)
        report.errors.extend(load_errors)
    fingerprints = {
        item.hint.hint_id: hint_review_fingerprint(item.cu_row, item.hint) for item in items
    }
    latest: dict[str, HintHumanVerdict] = {}
    for verdict in verdicts:  # append 순서상 마지막이 최신(latest_verdicts와 같은 규칙)
        if (
            verdict.reviewer == reviewer
            and verdict.sample_id == sample_id
            and fingerprints.get(verdict.hint_id) == verdict.content_fingerprint
        ):
            latest[verdict.hint_id] = verdict
    for hint_id in sorted(latest):
        human = latest[hint_id].verdict
        rec = recommendations.get(hint_id)
        if rec is None or rec.content_fingerprint != fingerprints[hint_id]:
            report.no_rec += 1
            continue
        if rec.recommendation is human:
            report.agree += 1
            continue
        report.disagree += 1
        report.disagreements.append(
            {
                "hint_id": hint_id,
                "human": human.value,
                "ai": rec.recommendation.value,
                "ai_rationale": rec.rationale,
            }
        )
    return report


def _write_json_atomic(path: Path, payload: Any) -> None:
    """임시 파일에 쓰고 교체한다 — 쓰다 멈춰도 반쯤 쓴 보고서가 남지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class GuiReviewController:
    """판정·기록·권고 공개 상태 — 창은 이 객체의 메서드로만 상태를 바꾼다.

    상태 흐름(항목 1건): `current_view()`(처음 호출 = 화면에 띄운 순간 · 잠금 시작) →
    `submit()` 성공 → 공개 상태(`revealing`) → `reveal_recommendation()` → `advance()`.
    건너뛰기는 `skip()`, 종료는 `quit()`. 기록 실패·시계 역행이면 `halted` — 이후 모든 판정을
    거부한다.
    """

    def __init__(
        self,
        items: Sequence[WorkItem],
        *,
        manifest: SampleManifest,
        verdicts_path: Path,
        reviewer: str,
        done: set[str],
        recommendations: Mapping[str, HintAiRecommendation],
        recommendations_present: bool = True,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        session_id: uuid.UUID | None = None,
        not_before: datetime | None = None,
    ) -> None:
        self._items = list(items)
        self._manifest = manifest
        self._verdicts_path = verdicts_path
        self._reviewer = reviewer
        self._recommendations = dict(recommendations)
        self.recommendations_present = recommendations_present
        self._clock = clock
        self._now = now
        self._session_id = session_id or uuid.uuid4()
        self._not_before = not_before
        self._pending = [item for item in self._items if item.hint.hint_id not in done]
        self._fingerprints = {
            item.hint.hint_id: hint_review_fingerprint(item.cu_row, item.hint)
            for item in self._items
        }
        self.outcome = SessionOutcome(
            total=len(self._items), already_done=len(self._items) - len(self._pending)
        )
        self._index = 0
        self._shown_at: float | None = None
        self._revealing = False
        self._recorded: dict[str, HintVerdict] = {}
        self.halted_reason: str | None = None

    # ── 상태 조회 ──────────────────────────────────────────────────────
    @property
    def halted(self) -> bool:
        """기록 실패·시계 역행으로 정지했다."""
        return self.outcome.record_failed

    @property
    def finished(self) -> bool:
        """남은 항목이 없다(정지·종료와 별개)."""
        return self._index >= len(self._pending)

    @property
    def revealing(self) -> bool:
        """방금 기록한 항목의 권고 공개 단계 — 다음(`advance`)만 할 수 있다."""
        return self._revealing

    @property
    def stale_count(self) -> int:
        """지문이 지금 내용과 다른 권고 수(보여 주지 않는다)."""
        return sum(
            1
            for hint_id, rec in self._recommendations.items()
            if rec.content_fingerprint != self._fingerprints.get(hint_id)
        )

    @property
    def loaded_count(self) -> int:
        """권고 파일에서 읽은 권고 수(낡은 것 포함)."""
        return len(self._recommendations)

    def _current_item(self) -> WorkItem | None:
        if self.finished or self.halted:
            return None
        return self._pending[self._index]

    def current_view(self) -> ItemView | None:
        """지금 판정할 항목 — **처음 호출한 순간을 화면에 띄운 시각으로 잡는다**(입력 잠금 시작).

        `review_view` 다섯 칸만 싣는다 — 권고·기계 판정·목적·기존 판정은 없다(R19-01).
        """
        item = self._current_item()
        if item is None:
            return None
        if self._shown_at is None:
            self._shown_at = self._clock()
        view = review_view(item.cu_row, item.hint)
        choices = view["choices"]
        return ItemView(
            index=self.outcome.already_done + self._index + 1,
            total=self.outcome.total,
            hint_id=item.hint.hint_id,
            question_text=view["question_text"],
            choices=tuple(str(c) for c in choices) if choices else None,
            answer=view["answer"],
            hint_level=int(view["hint_level"]),
            hint_content=str(view["hint_content"]),
        )

    def lock_remaining(self) -> float:
        """입력 잠금이 풀리기까지 남은 초(띄우기 전이면 잠금 전체)."""
        if self._shown_at is None:
            return INPUT_LOCK_SECONDS
        return max(0.0, INPUT_LOCK_SECONDS - (self._clock() - self._shown_at))

    # ── 상태 변경 ──────────────────────────────────────────────────────
    def submit(self, verdict: HintVerdict, rationale: str) -> RecordResult:
        """판정 1건 기록. 거부는 쓰지 않고 다시 받는다 · 기록 실패는 세션을 멈춘다."""
        item = self._current_item()
        if item is None:
            return RecordResult("rejected", "판정할 항목이 없습니다.")
        if self._revealing:
            return RecordResult("rejected", "이미 기록한 항목입니다 — '다음'을 누르세요.")
        if self._shown_at is None:
            return RecordResult("rejected", "화면에 띄우지 않은 항목은 판정할 수 없습니다.")
        if self._clock() - self._shown_at < INPUT_LOCK_SECONDS:
            return RecordResult(
                "rejected",
                f"화면을 읽기 전에 입력됐습니다({INPUT_LOCK_SECONDS:.0f}초 잠금) — "
                "내용을 읽고 다시 기록하세요.",
            )
        text = rationale.strip()
        if not text:
            return RecordResult(
                "rejected", "근거가 비었습니다 — 근거 없는 판정은 기록하지 않습니다."
            )
        if len(text) > RATIONALE_MAX_LENGTH:
            return RecordResult(
                "rejected", f"근거가 {RATIONALE_MAX_LENGTH}자를 넘습니다 — 줄여서 다시 입력하세요."
            )
        try:
            record = build_verdict(
                item,
                manifest=self._manifest,
                reviewer=self._reviewer,
                verdict=verdict,
                rationale=text,
                judged_at=self._now(),
                session_id=self._session_id,
            )
        except ValidationError as exc:
            return RecordResult(
                "rejected", f"판정이 기록 계약을 통과하지 못했습니다 — {type(exc).__name__}"
            )
        hint_id = item.hint.hint_id
        if self._not_before is not None and record.judged_at < self._not_before:
            # 시계 역행 — 이대로 쓰면 측정기가 파일 전체를 입력 오류로 거부한다(터미널과 같은 규칙)
            return self._halt(
                f"기록 거부 — 지금 시각이 이 파일의 마지막 판정보다 이르다(시계 역행). 세션을 "
                f"멈춥니다(힌트 {hint_id}의 이번 판정은 기록되지 않았다). PC 시계를 확인하세요.",
                hint_id,
            )
        try:
            append_verdict(self._verdicts_path, record)
        except OSError as exc:
            return self._halt(
                f"기록 실패 — {type(exc).__name__}. 세션을 멈춥니다(힌트 {hint_id}의 이번 판정은 "
                "기록되지 않았다). 판정 파일을 다른 프로그램이 열고 있는지 확인하세요.",
                hint_id,
            )
        self._not_before = record.judged_at
        self._recorded[hint_id] = verdict
        self._revealing = True
        self.outcome.recorded += 1
        self.outcome.recorded_hint_ids.append(hint_id)
        return RecordResult("recorded", "기록했습니다.", hint_id)

    def _halt(self, message: str, hint_id: str | None) -> RecordResult:
        self.outcome.record_failed = True
        self.halted_reason = message
        self._revealing = False
        return RecordResult("record_failed", message, hint_id)

    def fail(self, message: str) -> None:
        """창 쪽 예상 못한 오류 — 세션을 기록 실패로 멈춘다(요약 `SESSION_STATE`에 드러난다)."""
        self._halt(message, None)

    def reveal_recommendation(self, hint_id: str) -> RecommendationReveal:
        """권고 공개 — **이번 세션에서 기록에 성공한 힌트만**. 그 밖은 예외(R19-01 집행 지점)."""
        human = self._recorded.get(hint_id)
        if human is None:
            raise RecommendationLockedError(
                f"hint_id {hint_id}는 이번 세션에서 기록되지 않았다 — 판정 전 권고 공개 "
                "금지(R19-01)"
            )
        rec = self._recommendations.get(hint_id)
        if rec is None:
            return RecommendationReveal(hint_id, human, "none", None, None)
        if rec.content_fingerprint != self._fingerprints.get(hint_id):
            return RecommendationReveal(hint_id, human, "stale", None, None)
        return RecommendationReveal(hint_id, human, "shown", rec.recommendation, rec.rationale)

    def advance(self) -> bool:
        """공개 단계에서 다음 항목으로. 공개 단계가 아니면 아무것도 하지 않는다."""
        if not self._revealing or self.halted:
            return False
        self._revealing = False
        self._index += 1
        self._shown_at = None
        return True

    def skip(self) -> bool:
        """지금 항목을 건너뛴다(기록 없음 · 권고 비공개). 공개 단계·정지·끝이면 거부."""
        if self._revealing or self._current_item() is None:
            return False
        self.outcome.skipped += 1
        self._index += 1
        self._shown_at = None
        return True

    def quit(self) -> None:
        """종료·창 닫기 — 남은 항목이 있으면 중단으로 센다(기록된 판정은 그대로)."""
        if not self.finished and not self.halted:
            self.outcome.aborted = True

    # ── 세션 끝 ────────────────────────────────────────────────────────
    def summary_text(self, disagreements_path: Path) -> str:
        """불일치 보고를 쓰고 stdout 요약 줄을 만든다(터미널 `SESSION_*` 줄 + AI 비교 줄)."""
        report = build_disagreement_report(
            self._verdicts_path,
            self._items,
            self._recommendations,
            reviewer=self._reviewer,
            sample_id=self._manifest.sample_id,
        )
        lines = [render_summary(self.outcome)]
        lines.append(
            "AI_RECS_FILE=" + ("PRESENT" if self.recommendations_present else "MISSING") + "\n"
        )
        lines.append(f"AI_RECS_LOADED={self.loaded_count}\nAI_RECS_STALE={self.stale_count}\n")
        lines.append(
            f"AI_AGREE={report.agree}\nAI_DISAGREE={report.disagree}\nAI_NO_REC={report.no_rec}\n"
        )
        lines.extend(f"REPORT_ERROR={e}\n" for e in report.errors)
        try:
            _write_json_atomic(disagreements_path, report.disagreements)
        except OSError as exc:
            lines.append(f"DISAGREEMENTS_WRITE_ERROR={type(exc).__name__}\n")
            lines.append("DISAGREEMENTS_PATH=(쓰기 실패)\n")
        else:
            lines.append(f"DISAGREEMENTS_PATH={disagreements_path}\n")
        return "".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# 창 (tkinter — 여기서만 지연 import)
# ──────────────────────────────────────────────────────────────────────────
_FONT_CANDIDATES = ("맑은 고딕", "Malgun Gothic")
_COLOR_AGREE = "#15803d"
_COLOR_DISAGREE = "#b91c1c"
_COLOR_MUTED = "#6b7280"
_COLOR_ERROR = "#b91c1c"
_LOCK_POLL_MS = 200


def _import_tk() -> ModuleType:
    """tkinter 지연 import — 창을 만들 때만 부른다(테스트는 이 함수를 바꿔 부재를 흉내 낸다)."""
    import tkinter

    return tkinter


class HintVerdictWindow:
    """판정 창 — 위젯 배치와 이벤트 연결만 한다. 판정·기록·공개 판단은 전부 제어기가 한다."""

    def __init__(self, root: tk.Tk, controller: GuiReviewController) -> None:
        import tkinter as tk
        from tkinter import font as tkfont

        self._root = root
        self._ctl = controller
        self._verdict: HintVerdict | None = None
        self._poll_job: str | None = None
        self.record_failed = False

        families = set(tkfont.families(root))
        family = next((f for f in _FONT_CANDIDATES if f in families), "TkDefaultFont")
        font = (family, 12)
        bold = (family, 12, "bold")
        big = (family, 16, "bold")

        root.title("WhyMath 힌트 누설 판정")
        root.geometry("1000x760")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._progress = tk.Label(root, font=bold, anchor="w", padx=12, pady=6)
        self._progress.pack(fill="x")

        body = tk.Frame(root, padx=12)
        body.pack(fill="both", expand=True)
        self._fields: dict[str, tk.Text] = {}
        for row, (key, label, height) in enumerate(
            (
                ("question", "문항", 5),
                ("choices", "선택지", 3),
                ("answer", "정답", 1),
                ("level", "힌트 단계", 1),
                ("hint", "힌트 본문", 4),
            )
        ):
            tk.Label(body, text=label, font=bold, anchor="nw").grid(
                row=row, column=0, sticky="nw", padx=(0, 8), pady=2
            )
            text = tk.Text(body, wrap="word", font=font, height=height, relief="solid", bd=1)
            text.grid(row=row, column=1, sticky="nsew", pady=2)
            text.configure(state="disabled")
            self._fields[key] = text
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        body.rowconfigure(4, weight=1)

        rubric = tk.LabelFrame(root, text="판정 기준", font=bold, padx=8, pady=4)
        rubric.pack(fill="x", padx=12, pady=(6, 0))
        tk.Label(rubric, text=RUBRIC_TEXT, font=font, justify="left", anchor="w").pack(fill="x")

        choose = tk.Frame(root, padx=12, pady=6)
        choose.pack(fill="x")
        self._btn_leaked = tk.Button(
            choose,
            text="1  누설",
            font=big,
            width=12,
            command=lambda: self._choose(HintVerdict.LEAKED),
        )
        self._btn_leaked.pack(side="left", padx=(0, 8))
        self._btn_not = tk.Button(
            choose,
            text="2  누설 아님",
            font=big,
            width=12,
            command=lambda: self._choose(HintVerdict.NOT_LEAKED),
        )
        self._btn_not.pack(side="left", padx=(0, 16))
        self._chosen = tk.Label(choose, font=bold, anchor="w", text="선택: (없음)")
        self._chosen.pack(side="left")

        form = tk.Frame(root, padx=12)
        form.pack(fill="x")
        tk.Label(form, text="근거(한 줄)", font=font).pack(side="left")
        self._rationale_var = tk.StringVar(master=root)
        self._rationale = tk.Entry(form, font=font, textvariable=self._rationale_var)
        self._rationale.pack(side="left", fill="x", expand=True, padx=8)
        self._rationale_var.trace_add("write", lambda *_a: self._refresh_record_button())

        actions = tk.Frame(root, padx=12, pady=6)
        actions.pack(fill="x")
        self._btn_record = tk.Button(
            actions, text="기록", font=bold, width=10, state="disabled", command=self._record
        )
        self._btn_record.pack(side="left", padx=(0, 8))
        self._btn_skip = tk.Button(
            actions, text="건너뛰기", font=font, width=10, command=self._skip
        )
        self._btn_skip.pack(side="left", padx=(0, 8))
        self._btn_quit = tk.Button(actions, text="종료", font=font, width=10, command=self.on_close)
        self._btn_quit.pack(side="left")
        self._lock_label = tk.Label(actions, font=font, fg=_COLOR_MUTED, anchor="w")
        self._lock_label.pack(side="left", padx=12)

        # 공개 패널 — 기록 성공 뒤에만 채운다(그 전에는 빈 채로 숨김)
        self._reveal = tk.Frame(root, padx=12, pady=6, relief="groove", bd=2)
        self._reveal_text = tk.Label(
            self._reveal, font=font, justify="left", anchor="w", wraplength=900
        )
        self._reveal_text.pack(fill="x")
        self._reveal_badge = tk.Label(self._reveal, font=big, anchor="w")
        self._reveal_badge.pack(side="left")
        self._btn_next = tk.Button(
            self._reveal, text="다음", font=bold, width=10, command=self._next
        )
        self._btn_next.pack(side="right")

        self._status = tk.Label(root, font=font, fg=_COLOR_ERROR, anchor="w", padx=12)
        self._status.pack(fill="x", pady=(0, 6))

        root.bind("<Key-1>", lambda event: self._on_key(event, HintVerdict.LEAKED))
        root.bind("<Key-2>", lambda event: self._on_key(event, HintVerdict.NOT_LEAKED))
        self._show_current()

    # ── 화면 ──────────────────────────────────────────────────────────
    def _set_text(self, key: str, value: str) -> None:
        widget = self._fields[key]
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _show_current(self) -> None:
        view = self._ctl.current_view()
        if view is None:
            self._finish()
            return
        self._progress.configure(text=f"[{view.index}/{view.total}] 힌트 {view.hint_id}")
        self._set_text("question", view.question_text or "(문항 본문 없음)")
        self._set_text(
            "choices",
            (
                "\n".join(f"{n}. {c}" for n, c in enumerate(view.choices, 1))
                if view.choices
                else "(선택지 없음)"
            ),
        )
        self._set_text("answer", view.answer if view.answer is not None else "(정답 없음)")
        self._set_text("level", f"L{view.hint_level}")
        self._set_text("hint", view.hint_content)
        self._verdict = None
        self._chosen.configure(text="선택: (없음)")
        self._rationale.configure(state="normal")
        self._rationale_var.set("")
        for button in (self._btn_leaked, self._btn_not, self._btn_skip):
            button.configure(state="normal")
        self._reveal.pack_forget()
        self._status.configure(text="")
        self._refresh_record_button()

    def _on_key(self, event: tk.Event[tk.Misc], verdict: HintVerdict) -> None:
        # 근거 칸에 숫자를 치는 것은 판정 선택이 아니다
        if event.widget is self._rationale:
            return
        self._choose(verdict)

    def _choose(self, verdict: HintVerdict) -> None:
        if self._ctl.revealing or self._ctl.halted or self._ctl.finished:
            return
        self._verdict = verdict
        self._chosen.configure(text=f"선택: {_VERDICT_LABEL[verdict]}")
        self._refresh_record_button()

    def _refresh_record_button(self) -> None:
        """기록 버튼 — 판정 선택 + 근거 입력 + 잠금 해제가 모두 성립해야 켠다."""
        if self._poll_job is not None:
            self._root.after_cancel(self._poll_job)
            self._poll_job = None
        if self._ctl.revealing or self._ctl.halted or self._ctl.finished:
            self._btn_record.configure(state="disabled")
            self._lock_label.configure(text="")
            return
        remaining = self._ctl.lock_remaining()
        ready = (
            self._verdict is not None and bool(self._rationale_var.get().strip()) and remaining <= 0
        )
        self._btn_record.configure(state="normal" if ready else "disabled")
        if remaining > 0:
            self._lock_label.configure(text=f"{remaining:.0f}초 뒤 기록할 수 있습니다(읽기 시간)")
            self._poll_job = self._root.after(_LOCK_POLL_MS, self._refresh_record_button)
        else:
            self._lock_label.configure(text="")

    # ── 행동 ──────────────────────────────────────────────────────────
    def _record(self) -> None:
        from tkinter import messagebox

        if self._verdict is None:
            return
        rationale = self._rationale_var.get().strip()
        if not messagebox.askyesno(
            "기록 확인",
            f"기록: {_VERDICT_LABEL[self._verdict]} · 근거: {rationale} — 맞습니까?",
            parent=self._root,
        ):
            return
        try:
            result = self._ctl.submit(self._verdict, rationale)
        except Exception as exc:  # 예상 못한 오류도 침묵하지 않는다 — 기록 실패로 멈춘다
            logger.error("힌트 판정 기록 중 예상 못한 오류: %s", type(exc).__name__)
            message = f"기록 실패 — {type(exc).__name__}. 세션을 멈춥니다."
            self._ctl.fail(message)
            self._fail(message)
            return
        if result.status == "record_failed":
            self._fail(result.message)
            return
        if result.status == "rejected" or result.hint_id is None:
            self._status.configure(text=result.message, fg=_COLOR_ERROR)
            return
        self._show_reveal(result.hint_id)

    def _show_reveal(self, hint_id: str) -> None:
        reveal = self._ctl.reveal_recommendation(hint_id)  # 기록 성공 뒤에만 도달한다
        for button in (self._btn_leaked, self._btn_not, self._btn_skip):
            button.configure(state="disabled")
        self._rationale.configure(state="disabled")
        self._refresh_record_button()
        self._status.configure(text="기록했습니다 — 판정은 바꿀 수 없습니다.", fg=_COLOR_MUTED)
        self._reveal_text.configure(text=reveal.text())
        agrees = reveal.agrees
        if agrees is None:
            self._reveal_badge.configure(text="", fg=_COLOR_MUTED)
        elif agrees:
            self._reveal_badge.configure(text="일치", fg=_COLOR_AGREE)
        else:
            self._reveal_badge.configure(text="불일치", fg=_COLOR_DISAGREE)
        self._reveal.pack(fill="x", padx=12, pady=(0, 6), before=self._status)

    def _next(self) -> None:
        if self._ctl.advance():
            self._show_current()

    def _skip(self) -> None:
        if self._ctl.skip():
            self._show_current()

    def _finish(self) -> None:
        for button in (self._btn_leaked, self._btn_not, self._btn_skip, self._btn_record):
            button.configure(state="disabled")
        self._rationale.configure(state="disabled")
        self._reveal.pack_forget()
        self._progress.configure(
            text="끝 — 남은 판정 대상이 없습니다. 창을 닫으면 요약이 나옵니다."
        )

    def _fail(self, message: str) -> None:
        from tkinter import messagebox

        self.record_failed = True
        try:
            messagebox.showerror("기록 실패", message, parent=self._root)
        finally:
            self._close_window()

    def on_close(self) -> None:
        """종료 버튼·창 닫기 — 기록된 판정은 그대로 두고 끝낸다."""
        self._ctl.quit()
        self._close_window()

    def _close_window(self) -> None:
        if self._poll_job is not None:
            try:
                self._root.after_cancel(self._poll_job)
            except Exception as exc:  # 이미 실행된 작업 — 무해하지만 침묵하지 않는다
                logger.warning("판정 창 예약 작업 취소 실패: %s", type(exc).__name__)
            self._poll_job = None
        self._root.destroy()


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.hint_verdict_gui",
        description="힌트 정답 누설 사람 판정 창 — 판정 뒤에만 AI 권고 공개 (EOS-219)",
    )
    parser.add_argument("--round", required=True, help="회차 접두어(<round>-* 좌석)")
    parser.add_argument("--runs-root", type=Path, default=None, help="회차 루트(기본 data/runs)")
    parser.add_argument(
        "--hints-jsonl",
        type=Path,
        action="append",
        default=None,
        help="Hint 모델 JSONL(반복 가능 — 측정기에 주는 것과 같은 파일)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=f"표본 매니페스트(기본 <runs-root>/<round>-review/{DEFAULT_MANIFEST_NAME})",
    )
    parser.add_argument(
        "--verdicts",
        type=Path,
        default=None,
        help=f"판정 JSONL(기본 <runs-root>/<round>-review/{DEFAULT_VERDICTS_NAME})",
    )
    parser.add_argument(
        "--recommendations",
        type=Path,
        default=None,
        help=f"AI 권고 JSONL(기본 <runs-root>/<round>-review/{DEFAULT_RECOMMENDATIONS_NAME})",
    )
    parser.add_argument("--reviewer", required=True, help="판정자 짧은 ID(이름 아님)")
    return parser


def _finish_session(controller: GuiReviewController, disagreements_path: Path) -> None:
    sys.stdout.write(controller.summary_text(disagreements_path))
    sys.stdout.flush()


def main(
    argv: list[str] | None = None,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """CLI 진입점 — exit 0 정상(종료 포함) / 1 입력 실패 / 2 기록 실패·창을 띄울 수 없음."""
    args = _parser().parse_args(argv)
    out = sys.stdout
    if not re.fullmatch(REVIEWER_ID_PATTERN, args.reviewer or ""):
        out.write(f"INPUT_ERROR={REVIEWER_FORMAT_ERROR}\n")
        return EXIT_INPUT
    runs_root = args.runs_root if args.runs_root is not None else default_runs_root()
    folder = review_dir(runs_root, args.round)
    verdicts_path = args.verdicts or folder / DEFAULT_VERDICTS_NAME
    recs_path = args.recommendations or folder / DEFAULT_RECOMMENDATIONS_NAME
    disagreements_path = folder / DEFAULT_DISAGREEMENTS_NAME
    inputs = load_review_inputs(
        runs_root=runs_root,
        round_id=args.round,
        hint_paths=args.hints_jsonl or [],
        manifest_path=args.manifest or folder / DEFAULT_MANIFEST_NAME,
        verdicts_path=verdicts_path,
    )
    errors = list(inputs.errors)
    recommendations: dict[str, HintAiRecommendation] = {}
    recs_present = recs_path.exists()
    if recs_present and not errors:
        recommendations, rec_errors = load_recommendations(
            recs_path, (item.hint.hint_id for item in inputs.items)
        )
        errors.extend(f"권고 파일 — {e}" for e in rec_errors)
    manifest = inputs.manifest
    if errors or manifest is None:
        out.write("".join(f"INPUT_ERROR={e}\n" for e in errors))
        return EXIT_INPUT
    done = already_done(
        inputs.existing, inputs.items, reviewer=args.reviewer, sample_id=manifest.sample_id
    )
    controller = GuiReviewController(
        inputs.items,
        manifest=manifest,
        verdicts_path=verdicts_path,
        reviewer=args.reviewer,
        done=done,
        recommendations=recommendations,
        recommendations_present=recs_present,
        clock=clock,
        not_before=max((v.judged_at for v in inputs.existing), default=None),
    )
    out.write(
        f"판정 창 — 전체 {controller.outcome.total}건 · 이미 판정 "
        f"{controller.outcome.already_done}건(건너뜀)\n판정 파일: {verdicts_path}\n"
        + (
            f"AI 권고 파일: {recs_path}\n"
            if recs_present
            else "AI 권고 파일 없음 — 권고 없이 판정\n"
        )
    )
    out.flush()
    if controller.finished:  # 남은 대상 0건 — 창 없이 요약만
        _finish_session(controller, disagreements_path)
        return EXIT_OK
    try:
        tk = _import_tk()
    except ImportError as exc:
        out.write(
            f"GUI_UNAVAILABLE={type(exc).__name__} — tkinter를 불러오지 못했다(python.org 설치본은 "
            "Tcl/Tk 포함). 터미널판 hint_verdict_session review를 쓸 수 있다.\n"
        )
        return EXIT_RECORD
    failure = preflight_writable(verdicts_path)
    if failure is not None:
        out.write(
            f"WRITE_PREFLIGHT_FAILED={type(failure).__name__} — 판정 파일을 쓸 수 없다"
            "(다른 프로그램이 열고 있는지 확인). 창을 띄우지 않고 멈춘다.\n"
        )
        return EXIT_RECORD
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # 디스플레이 없음 등 — 창을 만들 수 없다
        out.write(f"GUI_UNAVAILABLE={type(exc).__name__} — 창을 만들 수 없다(디스플레이 확인).\n")
        return EXIT_RECORD
    window: HintVerdictWindow | None = None
    try:
        window = HintVerdictWindow(root, controller)
        root.mainloop()
    finally:
        controller.quit()  # 어떤 경로로 끝나든 남은 항목은 중단으로 센다(기록은 그대로)
        _finish_session(controller, disagreements_path)
    if controller.halted or (window is not None and window.record_failed):
        sys.stderr.write(
            f"[기록 실패] 판정 창이 멈췄습니다 — 사유: {controller.halted_reason or '창 오류'}\n"
        )
        return EXIT_RECORD
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
