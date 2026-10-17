"""검수 타이머 writer — HIT 이벤트(시작·종료·중단) 생성·JSONL 적재 (EOS-54 acceptance ①).

정본: 이벤트 계약 = `schema/review_timer.py`(교차 필드 강제) · 영속 =
`db/models/review_timer_event.py`(DB 경로는 `ReviewTimerEvent.from_schema` seam) · 집계 =
`ops/hit_cu_metrics`(HIT 중앙값·P90·적재율·실패코드 분포). 본 모듈은 검수 *경로 함수 레벨*의
writer다 — **서빙 라우트 신설 없음**(태스크 지침). 현행 검수 흐름(harness 워크리스트·라벨
JSONL — needs_review_worklist·#841 승격 인프라)이 파일 기반이므로 1차 매체는 JSONL이고, DB
적재는 같은 schema 이벤트를 `from_schema`로 넘기면 된다(별도 코드 불요).

집행 별항(정본화≠집행 — acceptance ③): 이 모듈이 집행하는 것은 함수 레벨 계약이다 —
`finish_review(verdict="rejected")`는 `failure_code` 없이 **생성 자체가 불가**(schema
validator — §4 강제 분류의 코드 착지). **사람 입력 경로까지의 배선은 `EOS-78`이 맡았다**:
`harness/review_session` CLI가 이 writer의 첫 생산 호출자다(그 전까지 `src/` 생산 호출자는
0건이었고 테스트만 이 모듈을 불렀다). 전 경로 강제(어떤 경로로도 타이머 없는 판정 제출
불가)는 여전히 검수 UI(**ADMIN-07**) 몫이다.

측정 도구 실패 경로 설계(2026-08-22 규칙):
  - **단계별 즉시 flush** — `append_event_jsonl`은 호출마다 append-open→1줄 기록→flush→close
    한다. 검수 도중 프로세스가 죽어도 그때까지의 이벤트는 파일에 남는다(마지막 일괄 저장
    금지 — 중간에 멈추면 전부 잃는 설계 금지).
  - **실패 원인 보존** — `load_events_jsonl`은 파싱 실패 줄을 삼키지 않고 **예외 타입명 +
    줄 번호**로 수집해 돌려준다(침묵 실패 금지 — 시크릿·필드값은 로그에 넣지 않는다).
  - **외부 프로세스 0** — 이 모듈은 파일 I/O만 한다(서브프로세스·네트워크 없음 — 타임아웃
    대상 없음을 명시).

시각 계약(EOS-48 발생/수신 분리): 이벤트 생성 함수는 `occurred_at`(발생)을 호출 시각
now(UTC)로 기본 스탬프한다 — 함수가 곧 그 행위 시점에 호출되므로 정직한 신고다(호출자가
명시 전달하면 그 값 우선). `recorded_at`(수신)은 매체가 찍는다: JSONL은
`append_event_jsonl`이 append 시각으로 스탬프하고, DB는 `server_default now()`가 찍는다.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.review_timer import (
    ReviewTimerEvent,
    ReviewTimerEventType,
    ReviewVerdict,
)

__all__ = [
    "abort_review",
    "append_event_jsonl",
    "finish_review",
    "load_events_jsonl",
    "start_review",
]


def _now_utc() -> datetime:
    """발생 시각 기본값 — UTC(EOS-48: 전 writer 서버 now(UTC) 관례)."""
    return datetime.now(UTC)


def start_review(
    *,
    cu_slug: str,
    reviewer_id: str,
    review_session_id: uuid.UUID | None = None,
    problem_id: uuid.UUID | None = None,
    content_fingerprint: str | None = None,
    occurred_at: datetime | None = None,
) -> ReviewTimerEvent:
    """검수 착수 이벤트 생성 — 세션 id를 발급한다(finish/abort가 재사용).

    반환 이벤트의 `review_session_id`를 들고 있다가 `finish_review`/`abort_review`에 그대로
    넘겨야 한 앉음(sitting)으로 페어링된다. 판정·경과 필드는 계약상 금지(schema가 강제).

    `content_fingerprint`(EOS-27) — 검수자에게 보일 CU 내용의 지문(`review_content_fingerprint`).
    생략(None) = "모름"이다 — 지문을 못 만든 상태를 일치로 읽는 소비자는 없다.
    """
    return ReviewTimerEvent(
        review_session_id=review_session_id or uuid4(),
        cu_slug=cu_slug,
        problem_id=problem_id,
        reviewer_id=reviewer_id,
        event_type=ReviewTimerEventType.STARTED,
        content_fingerprint=content_fingerprint,
        occurred_at=occurred_at or _now_utc(),
    )


def finish_review(
    *,
    review_session_id: uuid.UUID,
    cu_slug: str,
    reviewer_id: str,
    verdict: ReviewVerdict,
    elapsed_ms: int | None,
    failure_code: GenerationFailureCode | None = None,
    failure_note: str | None = None,
    problem_id: uuid.UUID | None = None,
    content_fingerprint: str | None = None,
    occurred_at: datetime | None = None,
) -> ReviewTimerEvent:
    """검수 종결 이벤트 생성 — 판정 필수·반려는 failure_code(F1~F8) 없이 생성 불가.

    `elapsed_ms`는 **키워드 필수 인자**다(기본값 없음) — 호출자가 "계측했는가"를 반드시
    자문하게 한다. 계측 실패면 None을 *명시*로 넘긴다(0 날조 금지 — 그 판정은 집계에서
    "미계측"으로 분리된다·acceptance ④). `verdict="rejected"`인데 failure_code가 없으면
    schema validator가 ValidationError를 던진다(§4 강제 분류 — 함수 레벨 집행).

    판정 3종(EOS-62): `approved`(무손질 통과) · `approved_with_edit`(사람이 손질해 통과) ·
    `rejected`(반려). **손질했으면 `approved`가 아니라 `approved_with_edit`을 넘긴다** — 둘을
    같은 값으로 적는 순간 승인율이 AI-first 전략의 실패를 가린다(해상도 갭). 손질 승인에는
    `failure_code`가 **선택**이지만(무엇을 고쳤는가) 권장이며, 미기재분은 집계가 분리
    카운트한다. 무손질 승인에 failure_code를 붙이면 거부된다 — 고친 것이 있다면 판정값이
    틀린 것이다.

    `content_fingerprint`(EOS-27) — **판정이 인증한 내용**의 지문. 착수 이벤트와 같은 값을 넘긴다
    (검수자가 본 것이 곧 판정한 것). 각인 도구·승격 게이트가 이 값을 코퍼스 현재 내용의 지문과
    대조해 "승인 뒤 내용이 바뀌었는가"를 가린다. None = 모름(통과가 아니다).
    """
    return ReviewTimerEvent(
        review_session_id=review_session_id,
        cu_slug=cu_slug,
        problem_id=problem_id,
        reviewer_id=reviewer_id,
        event_type=ReviewTimerEventType.FINISHED,
        verdict=verdict,
        failure_code=failure_code,
        failure_note=failure_note,
        content_fingerprint=content_fingerprint,
        elapsed_ms=elapsed_ms,
        occurred_at=occurred_at or _now_utc(),
    )


def abort_review(
    *,
    review_session_id: uuid.UUID,
    cu_slug: str,
    reviewer_id: str,
    elapsed_ms: int | None,
    problem_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
) -> ReviewTimerEvent:
    """검수 중단 이벤트 생성 — 판정 없음(판정이 있으면 finished다·schema가 강제).

    부분 경과가 계측됐으면 `elapsed_ms`로 남긴다(있는 만큼만 — 그 시간도 그 CU에 쓴 인간
    시간이다). 미계측이면 None 명시(0 날조 금지). elapsed_ms는 finish와 같은 이유로 키워드
    필수 인자다.
    """
    return ReviewTimerEvent(
        review_session_id=review_session_id,
        cu_slug=cu_slug,
        problem_id=problem_id,
        reviewer_id=reviewer_id,
        event_type=ReviewTimerEventType.ABORTED,
        elapsed_ms=elapsed_ms,
        occurred_at=occurred_at or _now_utc(),
    )


def append_event_jsonl(path: Path, event: ReviewTimerEvent) -> ReviewTimerEvent:
    """이벤트 1건을 JSONL에 **즉시** append한다(호출마다 open→기록→flush→close).

    `recorded_at`(수신 시각)이 비어 있으면 append 시각으로 스탬프한다 — JSONL 매체에서는
    append가 곧 수신이다(DB 경로의 `server_default now()`와 같은 역할·EOS-48). 스탬프된
    이벤트를 반환하므로 호출자는 기록된 그대로의 사본을 갖는다(원본 불변 — model_copy).

    실패 경로: 마지막 일괄 저장이 아니라 **이벤트마다 flush**라, 검수 도중 프로세스가 죽어도
    그때까지의 이벤트는 파일에 남는다(2026-08-22 규칙 ① "실패해도 증거가 남는가").
    """
    stamped = (
        event
        if event.recorded_at is not None
        else event.model_copy(update={"recorded_at": _now_utc()})
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(stamped.model_dump_json() + "\n")
        fh.flush()
    return stamped


def load_events_jsonl(path: Path) -> tuple[list[ReviewTimerEvent], list[str]]:
    """JSONL에서 이벤트를 읽는다 — (유효 이벤트, 실패 사유[예외 타입명+줄 번호]) 튜플.

    파싱·검증 실패 줄은 삼키지 않고 사유로 수집한다(침묵 실패 금지 — **예외 타입명** + 줄
    번호 + 실패 필드 위치만 담는다. 필드 *값*·원문 줄은 넣지 않는다: "타입명 포함·시크릿/
    필드값 제외" CLAUDE.md 규칙 — ValidationError 문자열화는 input_value를 포함하므로 loc만
    추출). 파일 부재는 호출자가 구분할 수 있게 FileNotFoundError를 그대로 전파한다 —
    "파일 없음"과 "이벤트 0건"은 다른 실패다(미측정≠0 원칙의 입력 축).
    """
    events: list[ReviewTimerEvent] = []
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                events.append(ReviewTimerEvent.model_validate(json.loads(text)))
            except ValidationError as exc:
                locs = ",".join(
                    "/".join(str(part) for part in err.get("loc", ())) or "(root)"
                    for err in exc.errors()
                )
                errors.append(f"line {line_no}: ValidationError: fields=[{locs}]")
            except Exception as exc:  # noqa: BLE001 — 사유 수집(타입명 보존)이 목적
                errors.append(f"line {line_no}: {type(exc).__name__}")
    return events, errors
