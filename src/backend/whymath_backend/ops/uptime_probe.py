"""외부 업타임 프로브 — 서버 프로세스 *밖*에서 `/health/ready`를 폴링해 가용성을 남긴다 (OPS-30 ②).

왜 필요한가
-----------
런북(`docs/standards/incident_response_slo.md` §6)이 자인한 공백이다: 지금의 모든 지표는 **서버가
살아 있을 때만** 나온다. 죽은 서버는 자기 죽음을 보고하지 못한다 — 그래서 SLO S4(학습창 가용성
99%)가 "측정 수단 없음"으로 남아 있었다. 이 모듈은 별도 프로세스(스케줄러가 1분마다 1회 실행)로
돌아 서버 생사와 무관하게 한 줄을 남긴다.

사용법 (한 번 실행 = 한 번 폴링)
--------------------------------
    python -m whymath_backend.ops.uptime_probe probe --url http://127.0.0.1:8000/health/ready \\
        --log <경로>/uptime.jsonl
    python -m whymath_backend.ops.uptime_probe report --log <경로>/uptime.jsonl --days 30
    python -m whymath_backend.ops.uptime_probe test-notify   # 장애 없이 알림 채널만 시험 발송

프로브 종료 코드: 0=정상(up) · 1=다운(down) · 2=인자 오류. 리포트: 0=S4 목표 충족 ·
1=미달 **또는 표본 부족**(측정하지 못한 것을 통과로 읽지 않는다) · 2=인자 오류.

판정 규약
---------
- **up = HTTP 200 이고 body의 `ready`가 `true`**. 그 외는 전부 down이다 — 연결 거부·타임아웃·
  503(DB 미도달)·200이지만 JSON이 아니거나 `ready`가 아닌 경우. 사유(`error`)엔 예외 타입명 또는
  `HTTP<코드>`·`BadBody`만 남긴다(URL·본문은 싣지 않는다 — 웹훅 URL이 토큰이고, 본문엔 환경 값이
  섞일 수 있다).
- pid 파일·프로세스 존재·`/health/live` 같은 **간접 신호는 쓰지 않는다**(2026-07-17 좀비 uvicorn
  사고: 죽은 pid 파일 + 다른 프로세스가 `/health`에 응답). 보는 것은 `/health/ready`의 실제 응답뿐.
- **알림은 상태 전이 때만** 나간다(up→down 시 "다운", down→up 시 "복구"). 정상 상태에서는 조용하다.
  발송이 실패(또는 채널 미설정)하면 그 사실을 기록에 남기고(`unsent`) 다음 폴링에서 재시도한다 —
  알림 1건 유실이 곧 "아무도 모른다"가 되는 것을 막는다.

S4 계산 (`report`)
-----------------
- 창: 매일 15:00–24:00 KST. 창 밖 표본은 버린다(런북 §1-2 S4: 창 밖은 best-effort).
- `availability_observed` = 창 안 up 표본 / 창 안 전체 표본. `availability_lower_bound` = up 표본 /
  **기대 표본 수**(스케줄러가 죽어 비어 버린 구간을 down으로 센 하한). 둘의 차이가 곧 "프로브 자신의
  공백"이다.
- `coverage` = 창 안 표본 / 기대 표본. `MIN_COVERAGE`(0.9) 미만이면 **판정하지 않는다**
  (`insufficient`). 표본이 모자란 가용성 숫자는 희망이지 측정이 아니다(런북 §0-1).

한계 (정직한 공백)
------------------
- 프로브가 도는 머신이 죽으면(예: Phaiakes9 = 서버와 같은 PC) 프로브도 같이 죽는다 — 이 경우 기록은
  비고 `coverage`가 낮게 나와 `insufficient`로 드러난다(통과로 위장되지 않는다). 별도 호스트에서의
  프로브는 이 태스크 범위 밖이다(런북 §6에 잔존 공백으로 남긴다).
- 단일 URL·단일 위치의 관측이라 네트워크 구간 장애와 서버 장애를 구분하지 못한다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

import httpx

from whymath_backend.ops.alert_delivery import CONFIG_CONFIGURED, classify_webhook_url, send_webhook

__all__ = [
    "MIN_COVERAGE",
    "S4_AVAILABILITY_TARGET",
    "S4_WINDOW_END_KST_HOUR",
    "S4_WINDOW_START_KST_HOUR",
    "S4Report",
    "compute_s4",
    "main",
    "poll_once",
    "run_probe",
]

# 런북 §1-2 S4 — 숫자의 단일 진실 원천은 이 모듈이고, 문서 §1-5 계약 블록이 테스트로 대조한다.
S4_AVAILABILITY_TARGET: Final = 0.99
S4_WINDOW_START_KST_HOUR: Final = 15
S4_WINDOW_END_KST_HOUR: Final = 24
MIN_COVERAGE: Final = 0.9

_KST: Final = timezone(timedelta(hours=9))
_DEFAULT_URL: Final = "http://127.0.0.1:8000/health/ready"
_WEBHOOK_ENV: Final = "WHYMATH_OPS_ALERT_WEBHOOK_URL"
_DEFAULT_TIMEOUT_S: Final = 5.0
# 직전 기록·다운 시작 시각을 찾기 위해 파일 끝에서 읽는 최대 바이트(대용량 로그 전체를 읽지 않는다).
_TAIL_BYTES: Final = 512 * 1024

NOTICE_DOWN: Final = "down"
NOTICE_UP: Final = "up"

Record = dict[str, Any]


# ──────────────────────────────────────────────────────────────────────────
# 1회 폴링 — up/down 판정 (간접 신호 없이 실제 응답만)
# ──────────────────────────────────────────────────────────────────────────
def poll_once(url: str, *, timeout_s: float, now: datetime) -> Record:
    """`url`을 1회 GET해 기록 1건을 만든다. 예외를 던지지 않는다(다운도 정상적인 관측 결과)."""
    started = time.perf_counter()
    status: int | None = None
    error: str | None = None
    ready: bool | None = None
    alerts: int | None = None
    try:
        response = httpx.get(url, timeout=timeout_s)
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and isinstance(body.get("components"), dict):
            ready = body.get("ready") is True
            raw_alerts = body.get("alerts")
            alerts = len(raw_alerts) if isinstance(raw_alerts, list) else None
        if status != 200:
            error = f"HTTP{status}"
        elif ready is not True:
            # 200인데 우리 body 모양이 아니거나 ready가 아님 — 다른 프로세스가 대신 답했을 수 있다.
            error = "BadBody"
    except Exception as exc:  # noqa: BLE001 — 다운도 관측 결과·타입명만 기록
        error = type(exc).__name__
    latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
    return {
        "v": 1,
        "ts": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": error is None,
        "status": status,
        "latency_ms": latency_ms,
        "ready": ready,
        "alerts": alerts,
        "error": error,
        "channel": None,
        "notice": None,
        "unsent": None,
    }


# ──────────────────────────────────────────────────────────────────────────
# 기록(JSONL append) 읽기·쓰기
# ──────────────────────────────────────────────────────────────────────────
def read_tail(path: Path) -> list[Record]:
    """로그 끝부분의 기록을 시간순으로 읽는다. 없는 파일=빈 목록, 깨진 줄은 건너뛴다."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return []
    with path.open("rb") as handle:
        handle.seek(max(0, size - _TAIL_BYTES))
        raw = handle.read()
    lines = raw.decode("utf-8", errors="replace").splitlines()
    if size > _TAIL_BYTES:
        lines = lines[1:]  # 잘린 첫 줄 버림
    records: list[Record] = []
    for line in lines:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and "ts" in value and "ok" in value:
            records.append(value)
    return records


def append_record(path: Path, record: Record) -> None:
    """기록 1줄을 append하고 디스크까지 내린다(프로브 직후 머신이 꺼져도 증거가 남게)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


# ──────────────────────────────────────────────────────────────────────────
# 알림 — 상태 전이 때만
# ──────────────────────────────────────────────────────────────────────────
def decide_notice(prev: Mapping[str, Any] | None, *, ok_now: bool) -> str | None:
    """이번 폴링에서 보낼 알림 종류 — 정상 지속 시 None(조용하다).

    - down 이고: 첫 기록이거나 직전이 up 이거나 직전 다운 알림이 못 나갔으면 → "down"
    - up 이고: 직전이 down 이거나 직전 복구 알림이 못 나갔으면 → "up"
    """
    if not ok_now:
        if prev is None or prev.get("ok") is True or prev.get("unsent") == NOTICE_DOWN:
            return NOTICE_DOWN
        return None
    if prev is not None and (prev.get("ok") is False or prev.get("unsent") == NOTICE_UP):
        return NOTICE_UP
    return None


def _down_since(history: Sequence[Mapping[str, Any]]) -> str | None:
    """직전까지 이어진 다운 구간의 시작 시각(없으면 None). 읽은 꼬리 안에서만 찾는다."""
    since: str | None = None
    for rec in reversed(history):
        if rec.get("ok") is False:
            since = str(rec.get("ts"))
        else:
            break
    return since


def build_notice_text(
    kind: str, record: Mapping[str, Any], history: Sequence[Mapping[str, Any]]
) -> str:
    """알림 본문 — 시각·사유 코드만(URL·시크릿·응답 본문 없음)."""
    if kind == NOTICE_DOWN:
        return (
            f"[WhyMath] 서버 다운 감지 — {record['ts']} "
            f"/health/ready 사유={record.get('error')}"
        )
    since = _down_since(history)
    suffix = f" (다운 시작 {since})" if since else ""
    return f"[WhyMath] 서버 복구 — {record['ts']} /health/ready 정상{suffix}"


def run_probe(
    *,
    url: str,
    log_path: Path,
    timeout_s: float,
    webhook_url: str,
    webhook_timeout_s: float = _DEFAULT_TIMEOUT_S,
    now: datetime | None = None,
    sender: Any = None,
) -> Record:
    """폴링 1회 → 전이면 알림 → 기록 append. 기록(증거)을 알림보다 **먼저 확정하지 않는다**:
    알림 결과(`notice`/`unsent`)를 같은 줄에 남기기 위해 알림을 먼저 시도하되, 알림이 예외를 던져도
    기록은 반드시 남는다(`send_webhook`은 비크래시 계약).
    """
    moment = now if now is not None else datetime.now(UTC)
    history = read_tail(log_path)
    prev = history[-1] if history else None
    record = poll_once(url, timeout_s=timeout_s, now=moment)

    # 채널 상태는 전이 여부와 무관하게 매 폴링 기록한다 — 스케줄러 환경에서 웹훅 env가 실제로
    # 보이는지 평상시에 확인할 수 있다(상속 실패는 정상일 땐 아무 일도 안 일어나 드러나지 않는다).
    state = classify_webhook_url(webhook_url)
    record["channel"] = state
    kind = decide_notice(prev, ok_now=bool(record["ok"]))
    if kind is not None:
        if state != CONFIG_CONFIGURED:
            outcome = "unset" if state == "unset" else "invalid"
        else:
            send = sender if sender is not None else send_webhook
            text = build_notice_text(kind, record, history)
            error = send(webhook_url, text, timeout_s=webhook_timeout_s)
            outcome = "sent" if error is None else f"failed:{error}"
        record["notice"] = f"{kind}:{outcome}"
        record["unsent"] = None if outcome == "sent" else kind
    append_record(log_path, record)
    return record


# ──────────────────────────────────────────────────────────────────────────
# S4 계산
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class S4Report:
    """S4(학습창 가용성) 계산 결과."""

    since_utc: str
    until_utc: str
    interval_seconds: float
    samples: int
    ok_samples: int
    expected_samples: int
    coverage: float | None
    availability_observed: float | None
    availability_lower_bound: float | None
    verdict: str  # "pass" | "fail" | "insufficient"
    target: float = S4_AVAILABILITY_TARGET


def _window_overlap_seconds(start: datetime, end: datetime) -> float:
    """[start, end) 와 매일 15:00–24:00 KST 창의 겹침 길이(초)."""
    total = 0.0
    day: date = start.astimezone(_KST).date()
    last: date = end.astimezone(_KST).date()
    while day <= last:
        w_start = datetime(day.year, day.month, day.day, S4_WINDOW_START_KST_HOUR, tzinfo=_KST)
        w_end = datetime(day.year, day.month, day.day, tzinfo=_KST) + timedelta(
            hours=S4_WINDOW_END_KST_HOUR
        )
        lo = max(start, w_start)
        hi = min(end, w_end)
        if hi > lo:
            total += (hi - lo).total_seconds()
        day += timedelta(days=1)
    return total


def _in_window(moment: datetime) -> bool:
    hour = moment.astimezone(_KST).hour
    return S4_WINDOW_START_KST_HOUR <= hour < S4_WINDOW_END_KST_HOUR


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def compute_s4(
    records: Sequence[Mapping[str, Any]],
    *,
    since: datetime,
    until: datetime,
    interval_seconds: float,
) -> S4Report:
    """기록 → S4. 순수 함수(I/O 0). 표본이 부족하면 판정하지 않는다(`insufficient`)."""
    samples = 0
    ok_samples = 0
    for rec in records:
        moment = _parse_ts(rec.get("ts"))
        if moment is None or not (since <= moment < until) or not _in_window(moment):
            continue
        samples += 1
        if rec.get("ok") is True:
            ok_samples += 1

    expected = int(_window_overlap_seconds(since, until) // interval_seconds)
    coverage = (samples / expected) if expected > 0 else None
    observed = (ok_samples / samples) if samples > 0 else None
    lower = (ok_samples / expected) if expected > 0 else None

    if coverage is None or coverage < MIN_COVERAGE or observed is None:
        verdict = "insufficient"  # 스캔 0건·표본 부족은 통과가 아니다
    elif observed >= S4_AVAILABILITY_TARGET:
        verdict = "pass"
    else:
        verdict = "fail"
    return S4Report(
        since_utc=since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        until_utc=until.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        interval_seconds=interval_seconds,
        samples=samples,
        ok_samples=ok_samples,
        expected_samples=expected,
        coverage=coverage,
        availability_observed=observed,
        availability_lower_bound=lower,
        verdict=verdict,
    )


def _fmt(value: float | None) -> str:
    return "미측정" if value is None else f"{value:.4%}"


def format_s4(report: S4Report) -> str:
    """사람이 읽는 리포트 — 미측정(None)은 0이 아니라 '미측정'으로 쓴다."""
    label = {
        "pass": "PASS — 목표 충족",
        "fail": "FAIL — 목표 미달",
        "insufficient": "INSUFFICIENT — 표본 부족(판정 보류·통과 아님)",
    }[report.verdict]
    return "\n".join(
        [
            f"S4 학습창 가용성 (매일 {S4_WINDOW_START_KST_HOUR:02d}:00–"
            f"{S4_WINDOW_END_KST_HOUR:02d}:00 KST)",
            f"  기간(UTC)         : {report.since_utc} ~ {report.until_utc}",
            f"  폴링 간격 가정    : {report.interval_seconds:g}초",
            f"  표본 / 기대       : {report.samples} / {report.expected_samples}",
            f"  coverage          : {_fmt(report.coverage)} (최소 {MIN_COVERAGE:.0%})",
            f"  가용성(관측)      : {_fmt(report.availability_observed)} "
            f"(목표 {report.target:.0%})",
            f"  가용성(하한)      : {_fmt(report.availability_lower_bound)} "
            "(빈 구간을 down으로 센 값)",
            f"  판정              : {label}",
        ]
    )


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uptime_probe", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="/health/ready를 1회 폴링해 기록을 append")
    probe.add_argument("--url", default=_DEFAULT_URL)
    probe.add_argument("--log", required=True, type=Path)
    probe.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT_S)

    sub.add_parser(
        "test-notify",
        help="장애 없이 알림 채널(마지막 1홉)만 시험 발송 — 도달하면 exit 0",
    ).add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT_S)

    report = sub.add_parser("report", help="기록으로 S4(학습창 가용성)를 계산")
    report.add_argument("--log", required=True, type=Path)
    report.add_argument("--days", type=int, default=30)
    report.add_argument("--interval-seconds", type=float, default=60.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "probe":
        if args.timeout <= 0:
            print("--timeout은 0보다 커야 한다", file=sys.stderr)
            return 2
        record = run_probe(
            url=args.url,
            log_path=args.log,
            timeout_s=args.timeout,
            webhook_url=os.environ.get(_WEBHOOK_ENV, ""),
        )
        print(json.dumps(record, ensure_ascii=False))
        return 0 if record["ok"] else 1

    if args.command == "test-notify":
        return run_test_notify(os.environ.get(_WEBHOOK_ENV, ""), timeout_s=args.timeout)

    if args.days <= 0 or args.interval_seconds <= 0:
        print("--days·--interval-seconds는 0보다 커야 한다", file=sys.stderr)
        return 2
    until = datetime.now(UTC)
    s4 = compute_s4(
        read_all(args.log),
        since=until - timedelta(days=args.days),
        until=until,
        interval_seconds=args.interval_seconds,
    )
    print(format_s4(s4))
    return 0 if s4.verdict == "pass" else 1


def run_test_notify(webhook_url: str, *, timeout_s: float, sender: Any = None) -> int:
    """시험 메시지 1건을 보낸다 — 0=채널 도달(2xx 확인) · 1=미설정/형식 오류/발송 실패.

    '도달했다'의 근거는 수신 서버의 2xx 응답뿐이다(사람이 채널에서 메시지를 눈으로 확인하는 것이
    최종 증거 — 이 명령은 그 직전까지를 기계로 가른다). URL은 출력하지 않는다.
    """
    state = classify_webhook_url(webhook_url)
    if state != CONFIG_CONFIGURED:
        print(f"채널 상태={state} — 시험 발송 안 함(WHYMATH_OPS_ALERT_WEBHOOK_URL 확인)")
        return 1
    send = sender if sender is not None else send_webhook
    error = send(
        webhook_url,
        "[WhyMath] 알림 채널 시험 — 이 메시지가 보이면 마지막 1홉이 연결된 것입니다",
        timeout_s=timeout_s,
    )
    if error is not None:
        print(f"시험 발송 실패 — 사유={error}")
        return 1
    print("시험 발송 성공 — 수신 서버가 2xx로 응답(채널에서 메시지가 보이는지 눈으로 확인하세요)")
    return 0


def read_all(path: Path) -> list[Record]:
    """리포트용 전체 읽기 — 없는 파일은 빈 목록(→ 표본 0 → insufficient, 통과 아님)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    records: list[Record] = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and "ts" in value and "ok" in value:
            records.append(value)
    return records


if __name__ == "__main__":
    raise SystemExit(main())
