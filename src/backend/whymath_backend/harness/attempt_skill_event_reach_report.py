"""`문제시도` 스킬 배열 기록률 리포트 — EOS-57 acceptance ②("작동한 비율" 상시 보고).

**존재 이유**: `attempt_event.skill_ids` 좌석과 writer를 만든 것만으로는 그것이 *작동한다*는
증거가 되지 않는다(CLAUDE.md 「작동 신호 없는 알고리즘 부착 금지」 — 정상 응답 201은 스킬이
해소·기록됐다는 증거가 아니다). 이 리포트가 그 비율을 말한다.

**3분류를 뭉개지 않는다** — 채점 1건은 다음 셋 중 하나이고, 셋의 대책이 서로 다르다:
  1. **미도달**(attempt은 있는데 `문제시도` 이벤트가 없다) — writer 배선이 끊겼거나, 이 배선
     이전(EOS-57 착지 전)의 과거 시도다. 배선 회귀는 여기서만 보인다.
  2. **기록·해소 0건**(`skill_ids == []`) — writer는 돌았고 concept→skill 매핑이 0건이었다.
     대책은 배선이 아니라 *데이터*(문항↔개념↔스킬 브리지 보강)다.
  3. **기록·해소 ≥1**(`skill_ids != []`) — 의도한 상태.
1과 2를 한 숫자로 뭉개면 "코드가 죽었다"와 "데이터가 비었다"가 같은 글자가 된다.

**경로별 분모**: `event_data.source`(attempt_submit·coach_completion·
coach_wrong_submission)로 나눠 본다. 한쪽 채점 경로에만 writer가 남으면 전체 평균에서는
절반의 감소로 희석돼 보이지만 경로별로는 0%로 즉시 드러난다.

**게이트가 아니다**(`assessment_seat_reach_report` 동일 원칙) — 비율이 0%여도 exit 1을 내지
않는다. 목표는 차단이 아니라 가시화이며, 판정 임계는 실측이 쌓인 뒤에 정한다(측정 없는 게이트
금지). exit는 **0=성공(0%여도) / 2=DB 오류**뿐이고, 조회 실패는 예외 타입명과 함께 stderr로
보고한다(침묵 실패 금지 — 측정 실패가 "0% 미달"로 위장되면 안 된다).

**"상시 보고"의 집행 지점(정본화≠집행)**: 이 리포트의 *판정 로직*(3분류 변별력·분모 0 처리·죽은
경로 보강·CLI exit 0/2)은 `tests/backend/harness/test_attempt_skill_event_reach_report.py`가 CI에서
상시 검증한다. *수치* 자체는 실 PG의 실제 채점 이력이 분모라 CI(매 잡 빈 DB)에서 돌리면 전 지표가
"측정 불가(분모 0)"만 난다 — 그래서 `ops/declared_unwired_audit`에 `_NEEDS_LIVE_SAMPLE`로 의도를
선언했다(무선언 미도달은 그 감사가 exit 1로 막는다). 주기 실행(cron) 배선은 주간 지표 크론
태스크 **OPS-56**이 소유한다 — 이 모듈은 그때 호출될 CLI를 제공할 뿐 새 스케줄러를 만들지 않는다.

**`--since`가 필요한 이유**: 이 배선 이전의 과거 attempt는 구조적으로 이벤트가 없다. 그것을
분모에 섞으면 기록률이 영원히 낮게 보이고, 실제 회귀가 그 잡음에 묻힌다. 배선 착지일 이후로
창을 좁혀 보는 것이 상시 감시의 기본 사용법이다.

사용:
    python -m whymath_backend.harness.attempt_skill_event_reach_report
    python -m whymath_backend.harness.attempt_skill_event_reach_report --since 2026-09-01
    python -m whymath_backend.harness.attempt_skill_event_reach_report --json out/eos57.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import AttemptEvent, ProblemAttempt
from whymath_backend.db.session import get_sessionmaker
from whymath_backend.l2.attempt_skill_event import AttemptSource
from whymath_backend.schema.enums import EventType

__all__ = [
    "RecordingCounts",
    "SkillEventReachReport",
    "SourceBreakdown",
    "build_report",
    "collect_counts",
    "dump_json",
    "main",
    "render_report",
    "report_to_json",
]

_EXIT_OK = 0
_EXIT_INPUT_ERROR = 2


@dataclass(slots=True, frozen=True)
class RecordingCounts:
    """DB 원시 조회 결과 투영 — `build_report`의 유일한 입력(순수 집계와 DB를 가르는 seam).

    `attempts_total`은 창 안의 `problem_attempt` 행 수(= 채점 확정 건수)이고, 나머지는 그중
    `문제시도` 이벤트가 남은 건수의 세부다. `events_null_skill_ids`는 **이벤트는 있는데
    skill_ids가 NULL**인 병리 상태다 — 현행 writer는 항상 배열을 넣으므로 정상 배선에서는 0이며,
    0이 아니면 이 컬럼을 NULL로 쓰는 다른 경로가 생겼다는 신호다(조용히 넘기지 않는다).
    """

    attempts_total: int
    events_total: int
    events_null_skill_ids: int
    events_empty_skill_ids: int
    events_nonempty_skill_ids: int
    events_by_source: dict[str, int]
    nonempty_by_source: dict[str, int]


@dataclass(slots=True, frozen=True)
class SourceBreakdown:
    """채점 경로 1개의 기록 현황(이벤트 수·해소 ≥1 건수·해소율)."""

    source: str
    events: int
    nonempty: int

    @property
    def nonempty_rate(self) -> float | None:
        """해소 ≥1 비율. 이벤트 0건이면 **None**(분모 0을 0%로 위장하지 않는다)."""
        return None if self.events == 0 else self.nonempty / self.events


@dataclass(slots=True, frozen=True)
class SkillEventReachReport:
    """기록률 관측 결과 전량(불변·렌더/직렬화의 단일 입력)."""

    counts: RecordingCounts
    sources: tuple[SourceBreakdown, ...]
    since: datetime | None

    @property
    def writer_reach_rate(self) -> float | None:
        """attempt 중 `문제시도` 이벤트가 남은 비율(=writer 도달률). attempt 0건이면 None."""
        total = self.counts.attempts_total
        return None if total == 0 else self.counts.events_total / total

    @property
    def resolution_rate(self) -> float | None:
        """**이벤트 중** 해소 ≥1 비율(=데이터 축). 이벤트 0건이면 None."""
        total = self.counts.events_total
        return None if total == 0 else self.counts.events_nonempty_skill_ids / total

    @property
    def end_to_end_rate(self) -> float | None:
        """attempt 중 스킬이 실제로 기록된 비율(acceptance ② 본문 지표). attempt 0건이면 None."""
        total = self.counts.attempts_total
        return None if total == 0 else self.counts.events_nonempty_skill_ids / total


async def collect_counts(
    session: AsyncSession, *, since: datetime | None = None
) -> RecordingCounts:
    """창 안의 attempt 수 + `문제시도` 이벤트 세부를 조회(유일한 DB 접근 지점·쓰기 0).

    전부 ORM 쿼리빌더로 조립한다(원시 SQL 금지 — CLAUDE.md 원칙). `func.cardinality`는
    SQLAlchemy `func` 네임스페이스 경유 표준 함수 호출이라 원시 SQL 문자열이 아니다.

    시간 축은 서로 다른 컬럼을 쓴다 — attempt는 `created_at`(서버 적재), 이벤트는
    `event_at`(서버 수신). 둘 다 서버 시각이라 같은 창에서 비교 가능하다(클라 신고 시각을
    분모에 쓰면 오프라인 sync에서 창이 어긋난다).
    """
    attempt_stmt = select(func.count()).select_from(ProblemAttempt)
    event_base = AttemptEvent.event_type == EventType.문제시도
    event_stmt = select(func.count()).select_from(AttemptEvent).where(event_base)
    if since is not None:
        attempt_stmt = attempt_stmt.where(ProblemAttempt.created_at >= since)
        event_stmt = event_stmt.where(AttemptEvent.event_at >= since)

    attempts_total = (await session.execute(attempt_stmt)).scalar_one()
    events_total = (await session.execute(event_stmt)).scalar_one()

    def _event_count(*extra: Any) -> Any:
        stmt = select(func.count()).select_from(AttemptEvent).where(event_base, *extra)
        if since is not None:
            stmt = stmt.where(AttemptEvent.event_at >= since)
        return stmt

    null_count = (
        await session.execute(_event_count(AttemptEvent.skill_ids.is_(None)))
    ).scalar_one()
    empty_count = (
        await session.execute(
            _event_count(
                AttemptEvent.skill_ids.is_not(None),
                func.cardinality(AttemptEvent.skill_ids) == 0,
            )
        )
    ).scalar_one()
    nonempty_count = (
        await session.execute(
            _event_count(
                AttemptEvent.skill_ids.is_not(None),
                func.cardinality(AttemptEvent.skill_ids) > 0,
            )
        )
    ).scalar_one()

    # 경로별 — event_data->>'source'(계약 필드). 계약이 source를 required로 고정하므로 NULL 키는
    # 구판/비계약 기록을 뜻한다(그 경우 '(미기재)'로 렌더 — 조용한 생략 금지).
    source_expr = AttemptEvent.event_data["source"].astext
    by_source_stmt = select(source_expr, func.count()).where(event_base).group_by(source_expr)
    nonempty_by_source_stmt = (
        select(source_expr, func.count())
        .where(
            event_base,
            AttemptEvent.skill_ids.is_not(None),
            func.cardinality(AttemptEvent.skill_ids) > 0,
        )
        .group_by(source_expr)
    )
    if since is not None:
        by_source_stmt = by_source_stmt.where(AttemptEvent.event_at >= since)
        nonempty_by_source_stmt = nonempty_by_source_stmt.where(AttemptEvent.event_at >= since)

    events_by_source = {
        (row[0] or ""): row[1] for row in (await session.execute(by_source_stmt)).all()
    }
    nonempty_by_source = {
        (row[0] or ""): row[1] for row in (await session.execute(nonempty_by_source_stmt)).all()
    }

    return RecordingCounts(
        attempts_total=attempts_total,
        events_total=events_total,
        events_null_skill_ids=null_count,
        events_empty_skill_ids=empty_count,
        events_nonempty_skill_ids=nonempty_count,
        events_by_source=events_by_source,
        nonempty_by_source=nonempty_by_source,
    )


def build_report(
    counts: RecordingCounts, *, since: datetime | None = None
) -> SkillEventReachReport:
    """조회 결과 → 리포트(순수·부작용 0·DB 세션 불요).

    `AttemptSource` 폐쇄 3종을 **전부** 보강한다 — DB에 행이 없는 경로도 0으로 명시한다(조용한
    생략 금지: 한 경로의 writer가 통째로 죽으면 그 경로는 group by 결과에서 *사라지므로*, 보강이
    없으면 전멸이 화면에서 안 보인다). DB에만 있는 미지 라벨(구판·오배선)도 버리지 않고 뒤에
    덧붙인다.
    """
    known = [s.value for s in AttemptSource]
    extra = [k for k in sorted(counts.events_by_source) if k not in known]
    sources = tuple(
        SourceBreakdown(
            source=key,
            events=counts.events_by_source.get(key, 0),
            nonempty=counts.nonempty_by_source.get(key, 0),
        )
        for key in [*known, *extra]
    )
    return SkillEventReachReport(counts=counts, sources=sources, since=since)


def _pct(value: float | None) -> str:
    """비율 렌더 — 분모 0(None)은 `측정 불가(분모 0)`로 말한다(0%로 위장 금지)."""
    return "측정 불가(분모 0)" if value is None else f"{value * 100:.1f}%"


def render_report(report: SkillEventReachReport) -> str:
    """기록률 관측 결과를 마크다운으로 렌더(순수·입력 외 계산 없음)."""
    counts = report.counts
    window = report.since.isoformat() if report.since is not None else "전체(창 제한 없음)"
    lines: list[str] = [
        "# `문제시도` 스킬 배열 기록률 리포트 (EOS-57 ②)",
        "",
        "> 관측 리포트다 — **exit 게이트가 아니다**(비율이 0%여도 실패시키지 않는다).",
        "> 측정 실패는 exit 2 + 예외 타입명으로 구분된다(0% 미달로 위장되지 않는다).",
        "",
        f"- 관측 창: **{window}**",
        f"- 채점 확정(`problem_attempt`) 건수: **{counts.attempts_total}**",
        f"- `문제시도` 이벤트 건수: **{counts.events_total}**",
        "",
        "## 1. 3분류 (미도달 / 해소 0건 / 해소 ≥1)",
        "",
        "| 상태 | 건수 | 뜻 | 대책 축 |",
        "|---|---:|---|---|",
        f"| writer 미도달 | {max(counts.attempts_total - counts.events_total, 0)} | "
        "attempt은 있으나 이벤트 없음(배선 이전 과거분 포함) | 배선(코드) |",
        f"| 기록·해소 0건 | {counts.events_empty_skill_ids} | writer는 돌았고 concept→skill "
        "매핑이 0건 | 데이터(브리지 보강) |",
        f"| 기록·해소 ≥1 | {counts.events_nonempty_skill_ids} | 의도한 상태 | — |",
        f"| 이벤트 있으나 skill_ids NULL | {counts.events_null_skill_ids} | **병리** — 현행 "
        "writer는 항상 배열을 넣는다(0이 아니면 다른 경로 발생) | 조사 |",
        "",
    ]
    if counts.events_total > counts.attempts_total:
        # 클램프한 음수를 조용히 0으로 보여주지 않는다 — 창 경계에서 attempt(created_at)는
        # 창 밖이고 그 이벤트(event_at)만 창 안인 경우 자연히 생긴다. 창을 넓히지 않은 채
        # "미도달 0"만 보면 분모가 어긋난 사실이 숨는다.
        lines.append(
            f"> ⚠ 이벤트({counts.events_total})가 attempt({counts.attempts_total})보다 많다 — "
            "창 경계 왜곡(attempt는 창 밖·이벤트는 창 안)일 수 있다. `--since`를 넓혀 재확인한다. "
            "'미도달'은 0으로 클램프된 값이다."
        )
        lines.append("")
    lines += [
        "## 2. 비율 (분모를 명시한다 — 분모 없는 0 금지)",
        "",
        f"- **writer 도달률**(이벤트/attempt): {_pct(report.writer_reach_rate)} "
        f"({counts.events_total}/{counts.attempts_total})",
        f"- **해소율**(해소≥1/이벤트): {_pct(report.resolution_rate)} "
        f"({counts.events_nonempty_skill_ids}/{counts.events_total})",
        f"- **종단 기록률**(해소≥1/attempt): {_pct(report.end_to_end_rate)} "
        f"({counts.events_nonempty_skill_ids}/{counts.attempts_total})",
        "",
        "## 3. 채점 경로별 (폐쇄 3종 전부 — 행 없는 경로도 0으로 명시)",
        "",
        "| source | 이벤트 | 해소 ≥1 | 해소율 |",
        "|---|---:|---:|---|",
    ]
    for breakdown in report.sources:
        label = breakdown.source or "(미기재)"
        lines.append(
            f"| `{label}` | {breakdown.events} | {breakdown.nonempty} | "
            f"{_pct(breakdown.nonempty_rate)} |"
        )
    lines += [
        "",
        "- 한 경로의 writer가 죽으면 전체 평균에서는 절반의 감소로 희석되지만 그 경로 행은 0%로"
        " 즉시 드러난다 — 이 표가 존재하는 이유다.",
        "- `(미기재)`는 `event_data.source`가 없는 기록이다(계약상 required라 구판·오배선 신호).",
        "",
    ]
    return "\n".join(lines)


def report_to_json(report: SkillEventReachReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict(키 정렬은 dump 시 `sort_keys=True`)."""
    counts = report.counts
    return {
        "since": report.since.isoformat() if report.since is not None else None,
        "attempts_total": counts.attempts_total,
        "events_total": counts.events_total,
        "events_null_skill_ids": counts.events_null_skill_ids,
        "events_empty_skill_ids": counts.events_empty_skill_ids,
        "events_nonempty_skill_ids": counts.events_nonempty_skill_ids,
        "writer_reach_rate": report.writer_reach_rate,
        "resolution_rate": report.resolution_rate,
        "end_to_end_rate": report.end_to_end_rate,
        "sources": [
            {
                "source": b.source,
                "events": b.events,
                "nonempty": b.nonempty,
                "nonempty_rate": b.nonempty_rate,
            }
            for b in report.sources
        ],
    }


def dump_json(report: SkillEventReachReport) -> str:
    return json.dumps(report_to_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def parse_since(raw: str) -> datetime:
    """`--since` 파싱 — ISO 날짜/일시. tz 미지정은 UTC로 해석(서버 시각 축과 정합).

    파싱 실패는 `ValueError`를 그대로 올린다(argparse가 exit 2로 잡는다) — 잘못된 창을
    조용히 "전체"로 폴백하면 관측 대상이 바뀌었다는 사실이 숨는다.
    """
    parsed = datetime.fromisoformat(raw)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


# ──────────────────────────────────────────────────────────────────────────
# CLI (얇은 껍데기 — DB 조회·입출력만, 집계는 위 순수 코어)
# ──────────────────────────────────────────────────────────────────────────
async def _run(since: datetime | None) -> SkillEventReachReport:  # pragma: no cover — PG glue
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        counts = await collect_counts(session, since=since)
    return build_report(counts, since=since)


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 기록률 리포트를 stdout에 출력. **0=성공(0%여도) / 2=DB·입력 오류**."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.attempt_skill_event_reach_report",
        description=(
            "`문제시도` 스킬 배열 기록률 리포트(EOS-57 ②) — writer 도달률·해소율·경로별 분해. "
            "게이트 아님(exit 0/2)."
        ),
    )
    parser.add_argument(
        "--since",
        dest="since",
        type=parse_since,
        default=None,
        help="관측 창 시작(ISO 날짜/일시·tz 미지정은 UTC). 배선 착지일 이후로 좁혀 본다.",
    )
    parser.add_argument(
        "--json", dest="json_path", type=Path, default=None, help="JSON 산출물 경로(선택)"
    )
    args = parser.parse_args(argv)

    try:
        report = asyncio.run(_run(args.since))
    except Exception as exc:  # noqa: BLE001 — DB 오류는 타입명과 함께 보고하고 exit 2
        print(
            f"DB 오류 — 기록률 집계 실패({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return _EXIT_INPUT_ERROR

    print(render_report(report))
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(dump_json(report), encoding="utf-8")
        print(f"JSON 산출물: {args.json_path}")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
