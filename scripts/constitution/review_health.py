#!/usr/bin/env python3
"""scripts/constitution/review_health.py — 규칙 R2-04 (코딩 헌법 제9조 · 판례 P0001).

규칙: "사람 검토 세션의 검토 소요 시간 중앙값이 10초 미만이거나 반려율이 0%이면 경고한다
(도장 찍기 조기 경보)". 판례 P0001: 소요 시간 중앙값 3초·반려 0건인 검토가 독립 검토가 아니었다.

입력: 검수 타이머 이벤트 JSONL(`harness/review_timer.append_event_jsonl` 산출 — EOS-54 계약).
  `event_type == "finished"` 행만 센다. 세션 = `review_session_id`.
  · 소요 시간 = `elapsed_ms`(null=미측정 — 0초로 날조하지 않고 분리 카운트, 중앙값 계산에서 제외)
  · 반려 = `verdict == "rejected"` (approved·approved_with_edit 는 비반려)

판정(세션별) — 표본이 MIN_SAMPLE(5)건 미만이면 '표본 부족'이다(경고도 통과도 아니다):
  · 소요 시간이 측정된 종결이 MIN_SAMPLE건 미만이면 시간 경보는 판정 보류
  · 종결이 MIN_SAMPLE건 미만이면 반려율 경보는 판정 보류 (1건 중 0건 반려는 증거가 아니다)

종료 코드: 0 경고 없음(또는 경고만 — L4 규칙은 경고) / 1 `--strict` 인데 경고 있음 /
          2 측정 불가(입력 미지정·파일 없음·읽기 실패·파싱 전멸·세션 0건 — '0건 통과' 위장 금지)

입력 지정: --events PATH, 없으면 환경변수 REVIEW_EVENTS_JSONL. 둘 다 없으면 exit 2.
※ 이 저장소의 CI 에는 실제 검토 이벤트가 없다(검토는 Kiki 머신에서 일어난다) — 그래서 CI 는
  판정 *논리*(tests/infra/test_review_health.py)만 동결하고, 실데이터 판정은 머신에서 이 CLI 를
  돌려서 한다.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

MEDIAN_FLOOR_SEC = 10.0  # 중앙값이 이보다 작으면 경고(규칙: 10초 미만)
MIN_SAMPLE = 5  # 이보다 적은 표본으로는 경보도 통과도 선언하지 않는다


class MeasureError(Exception):
    """측정 불가 — 호출자가 종료 코드 2 로 바꾼다."""


@dataclass
class Session:
    finished: int = 0
    rejected: int = 0
    elapsed_sec: list[float] = field(default_factory=list)
    unmeasured: int = 0


def load(path: Path) -> dict[str, Session]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MeasureError(f"이벤트 파일을 읽지 못함({type(exc).__name__}): {path}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MeasureError(f"UTF-8 이 아님({type(exc).__name__}): {path}") from exc
    sessions: dict[str, Session] = defaultdict(Session)
    bad_lines: list[str] = []
    rows = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        rows += 1
        try:
            ev = json.loads(line)
            if not isinstance(ev, dict):
                raise TypeError("행이 객체가 아님")
            if ev.get("event_type") != "finished":
                continue
            sid = str(ev["review_session_id"])
        except (ValueError, TypeError, KeyError) as exc:
            bad_lines.append(f"{lineno}행({type(exc).__name__})")
            continue
        s = sessions[sid]
        s.finished += 1
        if ev.get("verdict") == "rejected":
            s.rejected += 1
        ms = ev.get("elapsed_ms")
        if isinstance(ms, int | float) and not isinstance(ms, bool) and ms >= 0:
            s.elapsed_sec.append(ms / 1000.0)
        else:
            s.unmeasured += 1
    if bad_lines:
        print(
            f"⚠ 해석 실패 {len(bad_lines)}행 제외: {', '.join(bad_lines[:10])}",
            file=sys.stderr,
        )
    if rows and not sessions and len(bad_lines) == rows:
        raise MeasureError("파싱 전멸 — 모든 행이 해석되지 않았다")
    if not sessions:
        raise MeasureError("종결(finished) 이벤트가 있는 세션이 0건 — 판정할 대상이 없다")
    return dict(sessions)


def judge(sid: str, s: Session) -> tuple[list[str], list[str]]:
    """세션 하나의 (경고들, 판정 보류 사유들)."""
    warnings: list[str] = []
    deferred: list[str] = []
    if len(s.elapsed_sec) >= MIN_SAMPLE:
        median = statistics.median(s.elapsed_sec)
        if median < MEDIAN_FLOOR_SEC:
            warnings.append(
                f"소요 시간 중앙값 {median:.1f}초 < {MEDIAN_FLOOR_SEC:.0f}초 "
                f"(측정 {len(s.elapsed_sec)}건) — 도장 찍기 의심"
            )
    else:
        deferred.append(f"시간 측정 종결 {len(s.elapsed_sec)}건 < {MIN_SAMPLE}건 — 시간 경보 보류")
    if s.finished >= MIN_SAMPLE:
        if s.rejected == 0:
            warnings.append(f"반려율 0% (종결 {s.finished}건 중 반려 0건) — 도장 찍기 의심")
    else:
        deferred.append(f"종결 {s.finished}건 < {MIN_SAMPLE}건 — 반려율 경보 보류")
    return warnings, deferred


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="검토 도장 찍기 조기 경보 (R2-04 · 제9조)")
    ap.add_argument("--events", default=os.environ.get("REVIEW_EVENTS_JSONL"))
    ap.add_argument("--strict", action="store_true", help="경고가 있으면 exit 1")
    args = ap.parse_args(argv)
    try:
        if not args.events:
            raise MeasureError("--events(또는 REVIEW_EVENTS_JSONL)가 지정되지 않음")
        sessions = load(Path(args.events))
    except MeasureError as exc:
        print(f"⛔ 측정 불가 — {exc}", file=sys.stderr)
        return 2
    total_warn = 0
    for sid, s in sorted(sessions.items()):
        warns, deferred = judge(sid, s)
        total_warn += len(warns)
        for w in warns:
            print(f"⚠ 세션 {sid}: {w}", file=sys.stderr)
        for d in deferred:
            print(f"… 세션 {sid}: 판정 보류 — {d}")
        if not warns and not deferred:
            print(f"✅ 세션 {sid}: 경고 없음 (종결 {s.finished}건·반려 {s.rejected}건)")
    print(f"세션 {len(sessions)}건 · 경고 {total_warn}건")
    return 1 if (args.strict and total_warn) else 0


if __name__ == "__main__":
    sys.exit(main())
