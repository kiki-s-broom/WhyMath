"""검수 세션 CLI — 사람 검수 1건마다 HIT 타이머 이벤트를 **실제로** 낸다 (EOS-78).

## 이 모듈이 메우는 공백

`EOS-54`가 HIT 계측기의 *양끝*을 만들었다 — writer(`harness/review_timer`)와 판독기
(`ops/hit_cu_metrics`). 그런데 **가운데가 비어 있었다**: 2026-09-01 실측 기준
`start_review`·`finish_review`·`abort_review`·`append_event_jsonl`의 `src/` 생산 호출자는
**전부 0건**이었고(테스트 4파일만 호출), 실제 검수 판정을 기입하는 CLI들의 `review_timer`
참조도 0이었다. 즉 writer는 *자기 테스트만 부르는 계약*이었다.

`review_timer` 모듈 docstring은 이 공백을 "검수 UI(`ADMIN-07`) 결선은 후속 태스크"로 자인해
뒀다. 그러나 `ADMIN-07`은 `ADMIN-04 → ADMIN-05/06(+WEB-01) → ADMIN-07` 4단 체인이라 9월 안에
서지 않는다. 반면 **오늘의 검수 매체는 이미 JSONL/CLI다**(검수 큐 `needs_review_worklist`·
표본 패키지 `reviewer_sample_package`·감사 라벨 `corpus_audit_eval`). 그래서 이 모듈은
웹 UI 없이 *현행 매체에서* 타이머를 강제한다 — **신규 서빙 라우트 0·웹 화면 0**.

## 어느 검수 경로인가 (acceptance ① — 실측으로 특정)

**CU는 문제 단위다** — 설계서 §3이 "CU = 문제 지문 + 정답 + 단계별 풀이 + 3단계 힌트 +
concept/skill 매핑 + 난이도 + 예상 오답 3개 + 성취기준 코드"로 동결했다. 따라서 HIT를 재야
하는 검수는 **문제 코퍼스 검수**이고, `concept_content_review_apply`/`_batch`(개념 콘텐츠
라벨 반영)는 대상이 **아니다** — 축이 다르다.

문제 코퍼스 쪽 실측 3종과 판정:

  - `needs_review_worklist` — 비수용 후보의 내구 검수 큐(`ReviewQueueEntry`·slug 축).
    **→ 이 CLI의 입력.** 사람이 판단해야 할 CU가 실제로 쌓이는 곳이다.
  - `reviewer_sample_package` — 표본 문항을 마크다운으로 렌더(사람이 빈 체크박스를 채운다).
    검수 *제시*는 하지만 판정을 되받는 경로가 없어 시간이 소급 불가다.
  - `problem_corpus_review_status_backfill` — **사람 입력 경로 0**(자기 docstring 명시).
    `corpus_audit_eval`의 기계 판정만 각인하므로 인간 개입 시간이 원리적으로 존재하지 않는다.

즉 start/finish의 자연스러운 좌석은 **검수 큐를 소비하며 판정을 되받는 지점**인데 그 지점이
저장소에 없었다. 이 모듈이 그 자리다.

## 왜 대화형인가 (설계 근거 — 대안 기각 기록)

HIT는 "CU 1건 생산의 인간 개입 시간"이다. 사람이 오프라인에서 검수한 뒤 판정만 JSONL로
제출하는 현행 흐름에서는 **시간을 소급 복원할 방법이 없다** — 라벨 파일에 `elapsed` 필드를
추가해 사람이 손으로 적게 하는 안은 (a) 자기신고라 계측이 아니고 (b) 빈칸이면 0으로 위장될
위험이 있어 기각했다(0 날조 금지). 시간을 재는 유일한 정직한 방법은 **판정을 받는 그 도구가
직접 재는 것**이므로, 항목을 하나씩 제시하고 판정을 받는 대화형 루프가 된다. 이는 `ADMIN-07`이
UI로 하려던 강제("타이머·반려코드 없이 판정 제출 자체를 불가")를 CLI 층에서 같은 형태로 세운
것이다.

## 입력·출력 (신규 형식 0 — 전부 기존 계약)

입력(둘 다 `slug` 키를 쓰므로 한 로더가 받는다):
  - 내구 검수 큐 JSONL — `needs_review_worklist.ReviewQueueEntry` 직렬화(`status`·`reasons` 동반)
  - 코퍼스 JSONL — `problems.jsonl` 레코드(`slug` 키)

출력:
  - `--events` 타이머 이벤트 JSONL — `review_timer.append_event_jsonl` 산출 형식 그대로
    (`ops/hit_cu_metrics --events`가 이미 먹는다)
  - `--verdicts` 판정 JSONL — `{"slug", "review_status"}` 형식
    (`hit_cu_metrics._parse_verdict_rows`가 이미 먹는 코퍼스 양식 · 실측 확인)

`--events`와 `--verdicts`를 둘 다 내는 이유: 리포트의 **적재율**(판정 중 타이머 동반 비율)은
두 파일의 대조로 계산된다. 한쪽만 내면 그 지표가 "미산출"로 남는다.

## 반려는 실패코드 없이 제출 불가 (설계서 §4의 CLI 층 집행)

`finish_review(verdict="rejected")`는 `failure_code` 없이 **생성 자체가 불가**하다(schema
validator). 이 CLI는 그 계약이 사람 입력 경로까지 이어지게 한다 — 반려를 고르면 F1~F8 선택을
받을 때까지 진행하지 않으며, 자유 텍스트 메모는 코드를 *대체*하지 않고 보조할 뿐이다.

## 측정 도구 실패 경로 설계 (2026-08-22 규칙)

  - **항목마다 즉시 flush** — 이벤트도 판정도 항목 단위로 append→flush→close 한다. 검수
    도중 프로세스가 죽어도 그때까지의 증거가 남는다(마지막 일괄 저장 금지).
  - **실패 원인 보존** — 입력 파싱 실패는 삼키지 않고 **예외 타입명 + 줄 번호**로 모아
    보고한다(필드 *값*·원문 줄은 넣지 않는다 — 시크릿/값 제외 규칙).
  - **중단도 사실이다** — 보류·종료·EOF(파이프 닫힘)는 조용히 끝내지 않고 `aborted` 이벤트로
    남긴다. 그때까지 쓴 시간도 그 CU에 쓴 인간 시간이다.
  - **재개 시 이중 계측 방지** — `--resume`이면 이벤트 파일에 이미 `finished`가 있는 CU를
    건너뛴다. 건너뛴 수를 요약에 별도 표기한다(조용한 축소 금지).
  - **외부 프로세스 0** — 파일 I/O와 표준입출력만 쓴다(서브프로세스·네트워크 없음).

## 경과 시간의 정직성

경과는 `time.monotonic_ns()`로 잰다 — 벽시계 조정(NTP·수동 변경)에 면역이라 음수·점프가
구조적으로 불가능하다. 발생 시각(`occurred_at`)만 벽시계(UTC)를 쓴다. 즉시 판정한 항목의
경과가 0에 가까운 것은 *실측*이지 날조가 아니다 — 날조는 재지 않은 것을 0으로 적는 것이고,
이 경로에는 그런 자리가 없다(재지 못하면 이벤트 자체가 안 나온다).

사용:
    python -m whymath_backend.harness.review_session \
        --queue data/review/queue.jsonl \
        --events data/review/timer_events.jsonl \
        --verdicts data/review/verdicts.jsonl \
        --reviewer-id kiki [--resume] [--limit 30]

exit code: 0 정상 종료(중도 종료 포함 — 중단도 기록된 사실이다) / 1 입력 실패(파일 부재·
검수 대상 0건).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from whymath_backend.harness.review_timer import (
    abort_review,
    append_event_jsonl,
    finish_review,
    load_events_jsonl,
    start_review,
)
from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.review_timer import (
    VERDICT_APPROVED_WITH_EDIT,
    ReviewTimerEventType,
    review_status_for_verdict,
)

__all__ = [
    "ReviewItem",
    "SessionOutcome",
    "append_verdict_jsonl",
    "completed_slugs",
    "load_review_items",
    "main",
    "run_review_session",
]

# 판정 입력 키 — 폐쇄 집합. `q`는 세션 종료(현재 항목은 중단으로 기록된다).
# 판정 키 — `EOS-62`가 종결 판정을 3종으로 넓혔으므로 입력 경로도 3종을 제공한다. `e`를
# 빼면 손질 승인이 무손질 승인으로 기록되어 **승인율이 AI-first 실패를 가리는** 바로 그
# 사각(EOS-62가 없앤 것)이 이 CLI에서 되살아난다.
_VERDICT_KEYS: dict[str, str] = {
    "a": "approved",
    "e": VERDICT_APPROVED_WITH_EDIT,
    "r": "rejected",
    "s": "skip",
    "q": "quit",
}

_PROMPT_VERDICT = "  판정 [a]승인 [e]수정승인 [r]반려 [s]보류 [q]종료 > "
_PROMPT_FAILURE = "  반려 사유 F1~F8 (필수·번호만) > "
_PROMPT_FAILURE_OPTIONAL = "  손질한 축 F1~F8 (선택·Enter로 생략) > "
_PROMPT_NOTE = "  메모(선택·Enter로 생략) > "


class _Skipped:
    """선택 입력을 사람이 건너뛴 사실 — EOF(`None`)와 구분하기 위한 센티널."""


_SKIPPED = _Skipped()


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """검수 대상 CU 1건 — 표시용 근거만 담고 **판정은 담지 않는다**.

    큐 항목(`ReviewQueueEntry`)과 코퍼스 레코드 둘 다 `slug`를 쓰므로 한 타입으로 받는다.
    `status`·`reasons`는 큐에만 있는 근거이며(코퍼스 레코드는 None·빈 튜플), 검수자에게
    "기계가 왜 이걸 올렸는가"를 보여주는 용도다 — `reviewer_sample_package`의 정본 패턴
    ("근거를 모으기만 하고 판정하지 않는다")을 따른다.

    `payload`는 **문항 본문**(지문·정답·해설·검산 조건)이다. 큐 행의 `candidate_payload`
    (`needs_review_worklist.ReviewQueueEntry`)이거나, 코퍼스 모드에서는 행 자신이다.
    본문 없이 slug만 보고 F1~F8(정답 불일치·논리 비약·힌트 정답 누설)을 고르는 것은 판정이
    아니라 추측이므로, 본문은 화면에 반드시 오른다. 본문이 정말 없는 행(생성 실패 후보 등)은
    `payload_absent_reason`에 사유를 담아 **그 사실을 화면에 적는다** - 빈 화면으로 넘기면
    검수자는 "볼 것이 없다"와 "도구가 안 보여준다"를 구분할 수 없다.
    """

    slug: str
    status: str | None = None
    reasons: tuple[str, ...] = ()
    payload: Mapping[str, Any] | None = None
    payload_absent_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    """세션 요약 — 무엇이 몇 건 일어났는지. 리포트가 아니라 실행 결과 회계다."""

    approved: int
    approved_with_edit: int
    rejected: int
    aborted: int
    skipped_completed: int
    events_written: int
    stopped_early: bool


def _resolve_payload(row: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, str | None]:
    """행 1건에서 **문항 본문**을 꺼낸다 - (본문, 부재 사유) 중 정확히 한쪽만 채워진다.

    입력 2종을 같은 규칙으로 받는다(모듈 docstring "입력·출력"):
      - 검수 큐 행 - 본문은 `candidate_payload`에 코퍼스 레코드와 **동일 직렬화**로 들어 있다
        (`needs_review_worklist.ReviewQueueEntry` 계약 · `canary_slice`도 같은 자리에 싣는다).
      - 코퍼스 행 - 행 자신이 본문이다(`candidate_payload` 키가 아예 없다).

    `candidate_payload` 키가 **있는데 dict가 아닌** 경우(생성 실패 후보의 `None` 등)를 코퍼스
    모드로 접지 않는다 - 그러면 큐 메타(`status`·`run_id`·`reasons`)가 문항 본문인 척 화면에
    오른다. 부재는 부재로 말한다.
    """
    if "candidate_payload" in row:
        payload = row["candidate_payload"]
        if isinstance(payload, dict):
            return payload, None
        return None, f"candidate_payload가 비어 있음(type={type(payload).__name__})"
    return row, None


def load_review_items(path: Path) -> tuple[list[ReviewItem], list[str]]:
    """검수 큐/코퍼스 JSONL → (항목, 실패 사유). 파일 부재는 그대로 전파한다.

    실패 사유는 **예외 타입명 + 줄 번호**만 담는다(값·원문 제외 — `load_events_jsonl` 동형).
    `slug`가 없는 행(생성 실패 후보 등 — 검수할 CU 자체가 없다)은 실패가 아니라 대상 제외이며
    그 사실을 사유로 남긴다(조용한 누락 금지).
    """
    items: list[ReviewItem] = []
    errors: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                row: Any = json.loads(stripped)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_no}: {type(exc).__name__}")
                continue
            if not isinstance(row, dict):
                errors.append(f"line {line_no}: TypeError(not a JSON object)")
                continue
            slug = row.get("slug") or row.get("cu_slug")
            if not isinstance(slug, str) or not slug:
                errors.append(f"line {line_no}: MissingIdentityKey(slug/cu_slug)")
                continue
            if slug in seen:
                # 같은 CU가 큐에 두 번 오면 한 번만 검수한다 — 중복 계측은 HIT를 부풀린다.
                errors.append(f"line {line_no}: DuplicateSlug(skipped)")
                continue
            seen.add(slug)
            status = row.get("status")
            reasons_raw = row.get("reasons")
            reasons: tuple[str, ...] = (
                tuple(str(r) for r in reasons_raw) if isinstance(reasons_raw, list) else ()
            )
            payload, absent_reason = _resolve_payload(row)
            items.append(
                ReviewItem(
                    slug=slug,
                    status=status if isinstance(status, str) else None,
                    reasons=reasons,
                    payload=payload,
                    payload_absent_reason=absent_reason,
                )
            )
    return items, errors


def completed_slugs(events_path: Path) -> set[str]:
    """이벤트 파일에서 이미 **종결**된 CU slug 집합 — 재개 시 이중 계측 방지.

    파일이 없으면 빈 집합(첫 세션). 파싱 실패 줄은 여기서 판정하지 않는다 — 재개 판단은
    보수적이어야 하므로 *읽어낸 finished만* 완료로 본다(못 읽은 줄 때문에 건너뛰면 검수가
    조용히 누락된다).
    """
    try:
        events, _ = load_events_jsonl(events_path)
    except FileNotFoundError:
        return set()
    return {
        event.cu_slug for event in events if event.event_type == ReviewTimerEventType.FINISHED.value
    }


def append_verdict_jsonl(
    path: Path,
    *,
    slug: str,
    verdict: str,
    reviewer_id: str,
    review_session_id: uuid.UUID,
    failure_code: GenerationFailureCode | None,
    failure_note: str | None,
) -> dict[str, Any]:
    """판정 1건을 JSONL에 **즉시** append한다(호출마다 open→기록→flush→close).

    형식은 `ops/hit_cu_metrics`가 이미 먹는 코퍼스 양식(`slug` + `review_status`)이다 —
    신규 형식을 만들지 않는다. 나머지 키(`verdict`·`reviewer_id`·`review_session_id`·
    실패코드)는 추적용 부가 정보이며 판독기는 무시한다(관용 파서 실측 확인).

    **`verdict`를 `review_status`에 그대로 복사하지 않는다** — 둘은 다른 어휘다(EOS-62).
    `approved_with_edit`을 복사하면 `hit_cu_metrics._parse_verdict_rows`가 approved/rejected
    만 판정으로 세므로 그 행이 **비판정으로 빠져 적재율 분모가 조용히 줄어든다**. 변환은
    `schema/review_timer.review_status_for_verdict`가 단일 정본이며, 그 docstring이 예고한
    "각 호출부가 verdict를 그대로 복사할 것"이 바로 이 자리다. 손질 여부는 별도 `verdict`
    키로 보존한다(노출 상태를 깎지 않고 계측 축에 남긴다).
    """
    status = review_status_for_verdict(verdict)
    row: dict[str, Any] = {
        "slug": slug,
        "review_status": status.value if status is not None else None,
        "verdict": verdict,
        "reviewer_id": reviewer_id,
        "review_session_id": str(review_session_id),
        "failure_code": failure_code.value if failure_code is not None else None,
        "failure_note": failure_note,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
    return row


def _read_line(stream: TextIO, out: TextIO, prompt: str) -> str | None:
    """프롬프트 출력 후 한 줄 입력 — EOF면 None(파이프 닫힘·Ctrl+D)."""
    out.write(prompt)
    out.flush()
    line = stream.readline()
    if line == "":  # EOF — readline은 EOF에서만 빈 문자열을 낸다("\n"은 개행 입력)
        return None
    return line.strip()


#: 본문 렌더 순서 - (payload 키, 화면 라벨). 판정에 쓰이는 축을 **한 화면에** 모은다.
#: F2(정답 불일치)는 지문·정답·해설의 대조, F8(힌트 정답 누설)은 정답과 부가 설명의 대조로만
#: 성립하므로 이 셋이 떨어져 있으면 사람이 구조적으로 판정할 수 없다.
_BODY_FIELDS: tuple[tuple[str, str], ...] = (
    ("question_text", "문항"),
    ("question_text_md", "문항(md)"),
    ("choices", "선택지"),
    ("answer", "정답"),
    ("answer_explanation", "해설"),
    ("conditions_parsed", "조건"),
    ("verify", "검산"),
    ("achievement_standard_codes", "성취기준"),
    ("unit_codes", "단원"),
    ("difficulty_overall", "난이도"),
)


def _format_value(value: Any) -> str:
    """본문 1필드를 한 줄 문자열로 - **자르지 않는다**.

    길다고 줄이면 잘린 뒤쪽에 있는 정답 누설·논리 비약이 화면에서 사라진다(F3·F8은 바로 그
    뒤쪽에서 난다). 구조체는 `ensure_ascii=False` JSON으로 낸다 - 한글이 이스케이프로 깨져
    나오면 읽을 수 없고, 읽을 수 없는 본문은 없는 본문과 같다.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _render_body(out: TextIO, item: ReviewItem) -> None:
    """문항 본문 표시 - 판정에 필요한 축 전부. 없으면 **없다고 적는다**.

    끝에 `기타 필드`로 렌더하지 않은 키를 열거하는 이유: 이 회차 코퍼스에는 힌트 필드가 없지만
    (실측 2026-09-22 - `problem_bank_*/problems.jsonl` 전 파일에 `hint` 키 0건) 설계서 §3의 CU
    정의는 3단계 힌트를 포함한다. 나중에 힌트가 실리기 시작하면 이 줄에 키 이름이 나타나므로,
    검수자는 **자기가 못 본 것이 있다는 사실**을 알 수 있다. 화이트리스트 렌더의 구조적 사각을
    화이트리스트 자신이 고지하게 하는 것이다.
    """
    if item.payload is None:
        reason = item.payload_absent_reason or "사유 미상"
        out.write(f"  ! 문항 본문 없음: {reason}\n")
        out.write("    본문 없이 F1~F8을 고르지 마십시오 - 보류(s)가 정직한 판정입니다.\n")
        return
    shown: set[str] = set()
    for key, label in _BODY_FIELDS:
        if key not in item.payload:
            continue
        value = item.payload[key]
        shown.add(key)
        if value is None or value == [] or value == {}:
            continue
        out.write(f"  {label}: {_format_value(value)}\n")
    rest = sorted(
        k
        for k, v in item.payload.items()
        if k not in shown and v is not None and v != "" and v != [] and v != {}
    )
    if rest:
        out.write(f"  기타 필드(값 있음·미표시): {', '.join(rest)}\n")


def _render_item(out: TextIO, index: int, total: int, item: ReviewItem) -> None:
    """검수 대상 1건의 근거 표시 — 판정은 하지 않는다(AI 자기승인 금지)."""
    out.write(f"\n[{index}/{total}] {item.slug}\n")
    if item.status is not None:
        out.write(f"  큐 상태: {item.status}\n")
    for reason in item.reasons:
        out.write(f"  근거: {reason}\n")
    _render_body(out, item)


def _prompt_verdict(stream: TextIO, out: TextIO) -> str | None:
    """판정 키를 받을 때까지 되묻는다 — EOF면 None(호출자가 중단으로 처리).

    무효 입력을 곧바로 중단으로 접지 않는 이유: 오타 한 번이 `aborted` 이벤트가 되면
    **중단 건수가 거짓말을 한다**(사람은 멈추지 않았는데 멈춘 것으로 기록된다). 중단은
    사람이 실제로 보류·종료를 고른 경우와 EOF에만 성립해야 한다.
    """
    while True:
        raw = _read_line(stream, out, _PROMPT_VERDICT)
        if raw is None:
            return None
        action = _VERDICT_KEYS.get(raw.lower())
        if action is not None:
            return action
        out.write("  ! a/e/r/s/q 중 하나여야 합니다.\n")


def _prompt_failure_code(
    stream: TextIO, out: TextIO, *, required: bool
) -> GenerationFailureCode | None | _Skipped:
    """실패코드 F1~F8을 받는다 — 반려는 필수, 수정승인은 선택(계약 §4·EOS-62 ②).

    반환 3종을 구분한다: 코드 / `None`(EOF — 호출자가 중단으로 처리) / `_SKIPPED`(선택
    모드에서 사람이 빈 줄로 건너뜀). EOF와 "안 적음"을 같은 값으로 접으면 **파이프가 끊긴
    사고가 정상 입력으로 위장된다**.

    자유 텍스트 단독 금지(설계서 §4)의 입력 경로 집행이다. 잘못된 입력은 거부하고 다시 묻되,
    무엇이 유효한지 매번 보여준다(사람을 막다른 골목에 두지 않는다).
    """
    valid = {code.value for code in GenerationFailureCode}
    prompt = _PROMPT_FAILURE if required else _PROMPT_FAILURE_OPTIONAL
    while True:
        raw = _read_line(stream, out, prompt)
        if raw is None:
            return None
        if raw == "" and not required:
            return _SKIPPED
        token = raw.upper()
        if token in valid:
            return GenerationFailureCode(token)
        out.write(f"  ! F1~F8 중 하나여야 합니다(입력: 무효). 유효값: {sorted(valid)}\n")


def run_review_session(
    items: list[ReviewItem],
    *,
    events_path: Path,
    verdicts_path: Path,
    reviewer_id: str,
    stream_in: TextIO,
    stream_out: TextIO,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    now_utc: Callable[[], datetime] = lambda: datetime.now(UTC),
    resume: bool = False,
) -> SessionOutcome:
    """항목을 하나씩 제시하고 판정을 받으며 타이머 이벤트를 생산한다.

    한 항목의 생애: `started` append → 사람 입력 대기 → (`finished` | `aborted`) append.
    **started를 먼저 적는 이유**: 검수 도중 프로세스가 죽어도 "이 CU를 보기 시작했다"는 사실이
    남아야 `hit_cu_metrics`가 unfinished로 분류할 수 있다. 나중에 한꺼번에 적으면 죽은 세션은
    흔적조차 없다(실패해도 증거가 남는가 — 2026-08-22 규칙 ①).
    """
    already = completed_slugs(events_path) if resume else set()
    pending = [item for item in items if item.slug not in already]
    skipped = len(items) - len(pending)
    if skipped:
        stream_out.write(f"재개: 이미 종결된 {skipped}건을 건너뜁니다(이중 계측 방지).\n")

    approved = approved_with_edit = rejected = aborted = events_written = 0
    stopped_early = False
    total = len(pending)

    for index, item in enumerate(pending, start=1):
        started = append_event_jsonl(
            events_path,
            start_review(
                cu_slug=item.slug,
                reviewer_id=reviewer_id,
                occurred_at=now_utc(),
            ),
        )
        events_written += 1
        t0 = monotonic_ns()
        _render_item(stream_out, index, total, item)

        action = _prompt_verdict(stream_in, stream_out)

        failure_code: GenerationFailureCode | None = None
        note: str | None = None
        if action in ("rejected", VERDICT_APPROVED_WITH_EDIT):
            # 반려는 코드 필수, 수정승인은 선택(권장) — 계약이 그렇게 갈라 둔다.
            picked = _prompt_failure_code(stream_in, stream_out, required=(action == "rejected"))
            if picked is None:
                action = None  # EOF — 판정을 완성하지 못했다. 중단으로 남긴다(억지 판정 금지)
            else:
                failure_code = None if isinstance(picked, _Skipped) else picked
                note_raw = _read_line(stream_in, stream_out, _PROMPT_NOTE)
                note = note_raw or None

        elapsed_ms = (monotonic_ns() - t0) // 1_000_000

        if action in ("approved", VERDICT_APPROVED_WITH_EDIT, "rejected"):
            verdict: Any = action
            append_event_jsonl(
                events_path,
                finish_review(
                    review_session_id=started.review_session_id,
                    cu_slug=item.slug,
                    reviewer_id=reviewer_id,
                    verdict=verdict,
                    elapsed_ms=elapsed_ms,
                    failure_code=failure_code,
                    failure_note=note,
                    occurred_at=now_utc(),
                ),
            )
            events_written += 1
            append_verdict_jsonl(
                verdicts_path,
                slug=item.slug,
                verdict=action,
                reviewer_id=reviewer_id,
                review_session_id=started.review_session_id,
                failure_code=failure_code,
                failure_note=note,
            )
            if action == "approved":
                approved += 1
            elif action == VERDICT_APPROVED_WITH_EDIT:
                approved_with_edit += 1
            else:
                rejected += 1
            continue

        # 보류·종료·EOF·무효입력 — 전부 중단으로 남긴다. 판정이 없으므로 verdicts에는 안 쓴다
        # (pending은 판정이 아니다 — 분모 오염 방지).
        append_event_jsonl(
            events_path,
            abort_review(
                review_session_id=started.review_session_id,
                cu_slug=item.slug,
                reviewer_id=reviewer_id,
                elapsed_ms=elapsed_ms,
                occurred_at=now_utc(),
            ),
        )
        events_written += 1
        aborted += 1
        if action in ("quit", None):
            # quit=명시 종료 · None=EOF(파이프 닫힘·Ctrl+D). 둘 다 세션을 끝낸다.
            stopped_early = True
            break

    return SessionOutcome(
        approved=approved,
        approved_with_edit=approved_with_edit,
        rejected=rejected,
        aborted=aborted,
        skipped_completed=skipped,
        events_written=events_written,
        stopped_early=stopped_early,
    )


def _render_summary(
    out: TextIO, outcome: SessionOutcome, *, events_path: Path, verdicts_path: Path
) -> None:
    """세션 요약 — 다음에 무엇을 할 수 있는지까지 알려준다(간접 신호 금지·자가검증 동봉).

    판독 명령은 **경로를 채워서** 낸다 — 자리표시자를 남기면 그대로 복사·실행돼 실패한다
    (2026-08-31 규칙: 앞 단계가 만들어 낸 값에는 자리표시자를 쓰지 않는다).
    """
    out.write("\n=== 검수 세션 요약 ===\n")
    out.write(
        f"  승인 {outcome.approved} · 수정승인 {outcome.approved_with_edit} · "
        f"반려 {outcome.rejected} · 중단 {outcome.aborted}\n"
    )
    if outcome.skipped_completed:
        out.write(f"  재개로 건너뜀 {outcome.skipped_completed}\n")
    out.write(f"  이벤트 {outcome.events_written}건 기록 → {events_path}\n")
    if outcome.stopped_early:
        out.write("  (중도 종료 — `--resume`으로 이어서 할 수 있습니다)\n")
    out.write(
        "  HIT 판독: python -m whymath_backend.ops.hit_cu_metrics "
        f"--events {events_path} --verdicts {verdicts_path}\n"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점 — exit 0 정상(중도 종료 포함) / 1 입력 실패."""
    parser = argparse.ArgumentParser(
        prog="review_session",
        description="검수 세션 — 판정을 받으며 HIT 타이머 이벤트를 생산한다(EOS-78).",
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

    queue_path = Path(args.queue)
    try:
        items, errors = load_review_items(queue_path)
    except FileNotFoundError as exc:
        # "파일 없음"과 "0건"은 다른 실패다 — 예외 타입명을 남긴다(침묵 실패 금지).
        print(f"[입력 실패] {type(exc).__name__}: {queue_path}", file=sys.stderr)
        return 1

    print(f"[① 큐] 대상 {len(items)}건 · 제외/실패 {len(errors)}건", flush=True)
    for reason in errors:
        print(f"  - {reason}", flush=True)
    if not items:
        print("[입력 실패] 검수 대상 0건 — '0건 통과'가 아니라 측정 실패다.", file=sys.stderr)
        return 1

    if args.limit > 0:
        items = items[: args.limit]

    outcome = run_review_session(
        items,
        events_path=Path(args.events),
        verdicts_path=Path(args.verdicts),
        reviewer_id=args.reviewer_id,
        stream_in=sys.stdin,
        stream_out=sys.stdout,
        resume=args.resume,
    )
    _render_summary(
        sys.stdout,
        outcome,
        events_path=Path(args.events),
        verdicts_path=Path(args.verdicts),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    raise SystemExit(main())
