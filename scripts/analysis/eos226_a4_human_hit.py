"""EOS-226 — 사람 단독 첫 검수 HIT 표본 집계 (A4 2회차 · G5 실패정의 F-Ⅰ의 A4 쪽 입력).

판정하지 않는다(G5 몫). 표본을 고르고 세기만 한다.

무엇을 하나
-----------
검수 타이머 이벤트를 CU 단위로 묶어 CU마다 "유효 표본인가, 빠진다면 왜인가"를 정하고,
CU별 기록(JSONL)과 요약(JSON)을 낸다. CU의 HIT 정의(그 CU 전 세션 경과의 합)는
`whymath_backend.ops.hit_cu_metrics`를 그대로 쓴다 — 여기서 다시 짜지 않는다.

유효 표본 규칙 (EOS-226 acceptance 대조)
-----------------------------------------
① 검수 조건 = 사람 단독(AI 보조 없음). 이벤트에 조건 칸이 없으므로 `--condition`으로 받아
   CU별 기록에 남긴다(acceptance ③ "레코드와 문서 양쪽"). 한 번 실행에 조건 하나만 받는다 —
   조건이 섞인 회차는 조건별로 이벤트를 나눠 따로 실행한다(섞어서 한 중앙값을 내지 않는다).
② 첫 검수만(acceptance ⑥). 아래 중 하나면 재검수로 보고 그 CU를 뺀다.
   ⓐ 다른 회차 이벤트(`--prior-events`)에 같은 slug 또는 같은 내용 지문의 판정(finished)이 있다.
   ⓑ 이 파일 안에서, 그 CU의 첫 판정 *뒤에* 시작한 세션이 있다(판정 뒤 다시 본 시간이 HIT에
      더해지므로). 판정이 2회 이상인 경우도 여기에 걸린다.
③ 다시 보기(◀▶) 사용 문항은 뺀다(acceptance ⑥ · EOS-201 ⑦). 다시 보기는 이벤트를 남기지 않아
   (`harness/review_session_gui.ReviewController.review_back` — 그동안 현재 문항 시계는 계속 흐른다)
   기록으로는 식별할 수 없다. 그래서 검수자 확인값을 `--review-back`으로 받는다:
   `none`(안 썼다) · `unknown`(모른다 — 빼지 않고 요약에 미확인으로 남긴다) ·
   slug 목록(그 CU를 뺀다).
④ 계측 성립(measured)만 — 미계측·미종결 CU는 뺀다(0초 산입 금지 · hit_cu_metrics 3분류).
⑤ OPS-90 하한 — CU HIT가 하한(기본 30초) *미만*이면 뺀다(acceptance ③ "가드를 통과한 것만").
   하한과 정확히 같으면 통과다(hit_cu_metrics와 같은 경계).

분리 집계: **보류 후 재개**(판정 없이 끝난 세션 뒤 같은 CU의 판정 세션) — 유효 표본에 넣되
따로 센다. HIT가 두 세션의 합이라 첫 세션 시간이 빠지지 않으므로 재개가 HIT를 줄이지는 않는다.
그래도 같은 문항을 두 번 마주한 조건이라 섞지 않고 볼 수 있게 한다(acceptance ③).

공식 대조 (같은 정의를 쓰는지 기계 확인)
------------------------------------------
전체 계측 CU의 중앙값·P90·하한 미만 건수를 `hit_cu_metrics.aggregate`가 낸 값과 대조한다.
다르면 exit 1 — 이 스크립트의 CU 묶음이 공식 계측기와 갈라졌다는 뜻이다.

종료 코드: 0 성공 · 2 인자 오류 ·
  1 측정 실패(입력 파싱 실패·이벤트 0건·대조 불일치·대조 회차 이벤트 0건).

실행(저장소 루트에서):
  PYTHONPATH=src/backend python3 scripts/analysis/eos226_a4_human_hit.py \\
    --events data/runs/eos-a4-review/canary_review_events.jsonl \\
    --prior-events data/runs/eos197-a6-review/canary_review_events.jsonl \\
    --condition human_only --condition-source "<근거>" \\
    --review-back none --review-back-source "<근거>" \\
    --out data/runs/eos-a4-review/cu.review_human_hit.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from whymath_backend.harness.review_timer import load_events_jsonl
from whymath_backend.ops.hit_cu_metrics import (
    DEFAULT_MIN_PLAUSIBLE_SECONDS,
    _percentile,
    aggregate,
    classify_cus,
    classify_sessions,
    dedupe_events,
    effective_moment,
)
from whymath_backend.schema.review_timer import ReviewTimerEvent

#: 조건 값 — 지금은 사람 단독만 받는다.
#: AI 보조 회차를 넣으려면 값을 늘리고 `ai_assist`도 함께 정한다.
CONDITIONS: dict[str, bool] = {"human_only": False}

#: 제외 사유 이름(요약·기록 공통). 순서는 기록의 `exclusion_reasons` 정렬 순서다.
REASON_RE_REVIEW_PRIOR = "re_review_prior_round"
REASON_RE_REVIEW_POST_VERDICT = "re_review_post_verdict_session"
REASON_REVIEW_BACK = "review_back_used"
REASON_NOT_MEASURED = "not_measured"
REASON_BELOW_FLOOR = "below_ops90_floor"
REASON_ORDER = (
    REASON_RE_REVIEW_PRIOR,
    REASON_RE_REVIEW_POST_VERDICT,
    REASON_REVIEW_BACK,
    REASON_NOT_MEASURED,
    REASON_BELOW_FLOOR,
)


class MeasurementError(Exception):
    """측정 실패 — 통과로 위장하지 않고 exit 1로 올린다."""


@dataclass(frozen=True, slots=True)
class ReviewBack:
    """다시 보기 사용 확인값. mode = none | unknown | listed."""

    mode: str
    slugs: frozenset[str] = frozenset()

    @classmethod
    def parse(cls, raw: str) -> ReviewBack:
        text = raw.strip()
        if text in ("none", "unknown"):
            return cls(mode=text)
        slugs = frozenset(s.strip() for s in text.split(",") if s.strip())
        if not slugs:
            raise ValueError("--review-back 은 none · unknown · slug 목록(쉼표 구분) 중 하나")
        return cls(mode="listed", slugs=slugs)


def _stats(values: Sequence[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "median_seconds": _percentile(ordered, 0.50),
        "p90_seconds": _percentile(ordered, 0.90),
    }


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def classify(
    events: Sequence[ReviewTimerEvent],
    *,
    prior_events: Sequence[ReviewTimerEvent],
    condition: str,
    condition_source: str,
    review_back: ReviewBack,
    review_back_source: str,
    min_plausible_seconds: float = DEFAULT_MIN_PLAUSIBLE_SECONDS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """순수 집계 — (CU별 기록, 요약). I/O 없음."""
    if condition not in CONDITIONS:
        raise ValueError(f"알 수 없는 조건 {condition!r} — 허용: {sorted(CONDITIONS)}")
    deduped, duplicate_count = dedupe_events(events)
    if not deduped:
        raise MeasurementError("이벤트 0건 — 측정 실패(성공 0이 아니다)")

    sessions, anomaly_count = classify_sessions(deduped)
    cus = {c.cu_slug: c for c in classify_cus(sessions)}

    # 세션별 시작 시각·종결 종류 — 이벤트에서 직접 읽는다(SessionSummary에는 시각이 없다).
    session_events: dict[Any, list[ReviewTimerEvent]] = {}
    for e in deduped:
        session_events.setdefault(e.review_session_id, []).append(e)

    def _start(sid: Any) -> datetime | None:
        moments = [m for m in (effective_moment(e) for e in session_events[sid]) if m is not None]
        return min(moments) if moments else None

    # 다른 회차의 판정(finished) — slug·지문 양쪽으로 대조한다.
    # slug가 바뀌어도 같은 내용이면 지문으로 잡는다.
    prior_finished = [e for e in prior_events if e.event_type == "finished"]
    prior_slugs = {e.cu_slug for e in prior_finished}
    prior_fps = {e.content_fingerprint for e in prior_finished if e.content_fingerprint}

    by_cu_sessions: dict[str, list[Any]] = {}
    for s in sessions:
        by_cu_sessions.setdefault(s.cu_slug, []).append(s)

    def _finish_moment(sid: Any) -> datetime | None:
        moments = [
            m
            for m in (
                effective_moment(e) for e in session_events[sid] if e.event_type == "finished"
            )
            if m is not None
        ]
        return min(moments) if moments else None

    records: list[dict[str, Any]] = []
    for slug, cu_sessions in by_cu_sessions.items():
        cu = cus[slug]
        known = sorted(
            (s for s in cu_sessions if _start(s.review_session_id) is not None),
            key=lambda s: _start(s.review_session_id),  # type: ignore[arg-type, return-value]
        )
        unknown_start = [s for s in cu_sessions if _start(s.review_session_id) is None]
        ordered = known + unknown_start  # 시작 시각을 모르는 세션은 뒤에 둔다
        finished_sessions = [s for s in ordered if s.has_finish]
        first_finished = finished_sessions[0] if finished_sessions else None
        first_finish_at = (
            _finish_moment(first_finished.review_session_id) if first_finished else None
        )
        # 판정 뒤에 시작한 세션 = 재검수.
        # 시작 시각을 모르면 판정 전인지 알 수 없으므로 재검수로 본다
        # (모르는 것을 첫 검수로 세면 표본이 유리한 쪽으로 오염될 수 있다).
        post_verdict = []
        if first_finished is not None:
            for s in ordered:
                if s is first_finished:
                    continue
                start = _start(s.review_session_id)
                if start is None or first_finish_at is None or start >= first_finish_at:
                    post_verdict.append(s)
        # 보류 후 재개 = 첫 판정 세션 *앞에* 판정 없이 끝난(중단) 세션이 있다.
        held_resumed = first_finished is not None and any(
            s.has_terminal and not s.has_finish for s in ordered[: ordered.index(first_finished)]
        )
        fps = {
            e.content_fingerprint
            for s in ordered
            for e in session_events[s.review_session_id]
            if e.content_fingerprint
        }

        reasons: list[str] = []
        if slug in prior_slugs or (fps & prior_fps):
            reasons.append(REASON_RE_REVIEW_PRIOR)
        if post_verdict:
            reasons.append(REASON_RE_REVIEW_POST_VERDICT)
        if review_back.mode == "listed" and slug in review_back.slugs:
            reasons.append(REASON_REVIEW_BACK)
        if cu.kind != "measured":
            reasons.append(REASON_NOT_MEASURED)
        below_floor: bool | None = None
        if cu.hit_seconds is not None and min_plausible_seconds > 0:
            below_floor = cu.hit_seconds < min_plausible_seconds
            if below_floor:
                reasons.append(REASON_BELOW_FLOOR)

        verdicts = [v for s in finished_sessions for v in s.verdicts]
        session_rows = []
        for s in ordered:
            terminal = "finished" if s.has_finish else ("aborted" if s.has_terminal else None)
            session_rows.append(
                {
                    "terminal": terminal,
                    "started_at": _iso(_start(s.review_session_id)),
                    "elapsed_seconds": s.elapsed_ms_total / 1000.0 if s.measured else None,
                }
            )
        records.append(
            {
                "cu_slug": slug,
                "first_started_at": session_rows[0]["started_at"] if session_rows else None,
                "verdict": verdicts[0] if verdicts else None,
                "review_condition": condition,
                "ai_assist": CONDITIONS[condition],
                "condition_source": condition_source,
                "review_back": (
                    "used"
                    if review_back.mode == "listed" and slug in review_back.slugs
                    else ("unknown" if review_back.mode == "unknown" else "not_used")
                ),
                "review_back_source": review_back_source,
                "kind": cu.kind,
                "session_count": cu.session_count,
                "sessions": session_rows,
                "hit_seconds": cu.hit_seconds,
                "held_resumed": held_resumed,
                "first_review": not (
                    REASON_RE_REVIEW_PRIOR in reasons or REASON_RE_REVIEW_POST_VERDICT in reasons
                ),
                "below_floor": below_floor,
                "valid": not reasons,
                "exclusion_reasons": [r for r in REASON_ORDER if r in reasons],
            }
        )

    records.sort(key=lambda r: (r["first_started_at"] is None, r["first_started_at"] or ""))
    for order, rec in enumerate(records, start=1):
        rec["review_order"] = order

    measured_hits = [r["hit_seconds"] for r in records if r["kind"] == "measured"]
    valid = [r for r in records if r["valid"]]
    valid_hits = [r["hit_seconds"] for r in valid]
    official = aggregate(deduped, min_plausible_seconds=min_plausible_seconds)
    summary: dict[str, Any] = {
        "task": "EOS-226",
        "review_condition": condition,
        "ai_assist": CONDITIONS[condition],
        "condition_source": condition_source,
        "review_back": review_back.mode,
        "review_back_listed": sorted(review_back.slugs),
        "review_back_source": review_back_source,
        "min_plausible_seconds": min_plausible_seconds,
        "events": len(deduped),
        "duplicate_events_removed": duplicate_count,
        "sessions": len(sessions),
        "session_anomalies": anomaly_count,
        "prior_finished_scanned": len(prior_finished),
        "cu_total": len(records),
        "all_measured": _stats(measured_hits),
        "valid": _stats(valid_hits),
        "valid_excluding_held_resumed": _stats(
            [r["hit_seconds"] for r in valid if not r["held_resumed"]]
        ),
        "held_resumed_in_valid": _stats([r["hit_seconds"] for r in valid if r["held_resumed"]]),
        "excluded_total": len(records) - len(valid),
        "excluded_by_reason": {
            reason: sum(1 for r in records if reason in r["exclusion_reasons"])
            for reason in REASON_ORDER
        },
        "official": {
            "hit_median_seconds": official.hit_median_seconds,
            "hit_p90_seconds": official.hit_p90_seconds,
            "cu_measured": official.cu_measured,
            "cu_implausible_short_count": official.cu_implausible_short_count,
            "hit_implausible_majority": official.hit_implausible_majority,
        },
    }
    _cross_check(summary)
    return records, summary


def _cross_check(summary: dict[str, Any]) -> None:
    """전체 계측 값이 공식 계측기 값과 같은지 — 다르면 측정 실패."""
    mine, official = summary["all_measured"], summary["official"]
    below = summary["excluded_by_reason"][REASON_BELOW_FLOOR]
    problems = []
    if mine["n"] != official["cu_measured"]:
        problems.append(f"계측 CU 수 {mine['n']} ≠ 공식 {official['cu_measured']}")
    if mine["median_seconds"] != official["hit_median_seconds"]:
        problems.append(f"중앙값 {mine['median_seconds']} ≠ 공식 {official['hit_median_seconds']}")
    if mine["p90_seconds"] != official["hit_p90_seconds"]:
        problems.append(f"P90 {mine['p90_seconds']} ≠ 공식 {official['hit_p90_seconds']}")
    official_below = official["cu_implausible_short_count"]
    if official_below is not None and below != official_below:
        problems.append(f"하한 미만 {below} ≠ 공식 {official_below}")
    if problems:
        raise MeasurementError("공식 계측기와 불일치 — " + " · ".join(problems))


def _load(path: Path) -> list[ReviewTimerEvent]:
    events, errors = load_events_jsonl(path)
    print(f"[이벤트] {path} — 유효 {len(events)}건 · 파싱 실패 {len(errors)}건", flush=True)
    if errors:
        raise MeasurementError(f"{path} 파싱 실패 {len(errors)}건 — 첫 사유: {errors[0]}")
    return events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eos226_a4_human_hit",
        description="사람 단독 첫 검수 HIT 표본 집계 (EOS-226 — 판정하지 않는다)",
    )
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--prior-events", action="append", default=[], type=Path)
    parser.add_argument("--condition", required=True, choices=sorted(CONDITIONS))
    parser.add_argument("--condition-source", required=True)
    parser.add_argument("--review-back", required=True)
    parser.add_argument("--review-back-source", required=True)
    parser.add_argument(
        "--min-plausible-seconds", type=float, default=DEFAULT_MIN_PLAUSIBLE_SECONDS
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        review_back = ReviewBack.parse(args.review_back)
    except ValueError as exc:
        print(f"인자 오류: {exc}", file=sys.stderr)
        return 2
    try:
        events = _load(args.events)
        prior: list[ReviewTimerEvent] = []
        for path in args.prior_events:
            loaded = _load(path)
            if not loaded:
                # 대조 회차를 줬는데 0건이면 "재검수 0건"이 공허한 통과가 된다.
                raise MeasurementError(
                    f"대조 회차 {path} 이벤트 0건 — 재검수 대조가 성립하지 않는다"
                )
            prior.extend(loaded)
        records, summary = classify(
            events,
            prior_events=prior,
            condition=args.condition,
            condition_source=args.condition_source,
            review_back=review_back,
            review_back_source=args.review_back_source,
            min_plausible_seconds=args.min_plausible_seconds,
        )
    except MeasurementError as exc:
        print(f"[측정 실패] {exc}", file=sys.stderr)
        return 1
    summary["prior_events"] = [str(p) for p in args.prior_events]
    summary["events_path"] = str(args.events)
    if args.out is not None:
        with args.out.open("w", encoding="utf-8", newline="\n") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"[기록] {args.out} — {len(records)}행", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
