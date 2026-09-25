"""일별 학습 지표 롤업 CLI (COLLAB-03) — `l2.learning_metrics_rollup`의 운영 진입점.

집계 로직은 `whymath_backend.l2.learning_metrics_rollup`에 있고 이 모듈은 **CLI 껍데기**다
(인자 파싱·엔진 수명·트랜잭션 커밋·JSON 리포트). `problem_corpus_*_backfill` 계열의 argparse·
`--dry-run`·stdout JSON 규약을 그대로 따른다 — **새 스케줄러·새 인프라는 도입하지 않는다**
(acceptance ②). 운영에서는 이 CLI를 하루 1회 크론/수동 실행한다.

실행 예(레포 루트·backend venv):
    python -m whymath_backend.harness.learning_metrics_rollup_cli --days 2
    python -m whymath_backend.harness.learning_metrics_rollup_cli --since 2026-08-01 \
        --until 2026-08-09 --dry-run

멱등: `--days 2`(기본)는 어제·오늘을 매번 재집계한다. 복합 PK 충돌 시 `DO UPDATE`라 재실행이
곧 정합 회복이며, 지연 도착(자정을 넘겨 종료된 세션·늦은 채점)이 다음 실행에서 흡수된다.

DB 자격은 env(`WHYMATH_DATABASE_URL` → `Settings.database_url`)에서만 온다(하드코딩 0). 커밋은
이 CLI가 하며(집계 전체가 한 트랜잭션 — 부분 적재 0), 예외 발생 시 롤백 후 **예외 타입명을 로그에
남기고** exit 1로 실패를 드러낸다(CLAUDE.md 「침묵 실패 금지」 — 조용한 exit 0 금지).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.config import get_settings
from whymath_backend.l2.learning_metrics_rollup import (
    KST,
    MIN_SOLVE_TIME_SAMPLE,
    RollupReport,
    run_daily_rollup,
)
from whymath_backend.l2.learning_session_writer import close_idle_sessions

__all__ = ["main", "resolve_window", "run"]

_logger = logging.getLogger("whymath.harness.learning_metrics_rollup_cli")


def resolve_window(
    *,
    since: date | None,
    until: date | None,
    days: int,
    today: date,
) -> tuple[date, date]:
    """CLI 인자 → 집계 창 `[start, end]`(양끝 포함·tz 달력일). 순수 함수(hermetic 검증 가능).

    규칙:
      - `--since`/`--until` 둘 다 주면 그대로. 하나만 주면 나머지는 `today`로 채운다.
      - 둘 다 없으면 `[today − (days−1), today]` — 기본 `days=2`면 어제·오늘.
      - `since > until`이면 ValueError(조용한 빈 집계 금지).
    """
    if days < 1:
        raise ValueError(f"--days는 1 이상이어야 한다(받은 값 {days})")
    if since is None and until is None:
        end = today
        start = today - timedelta(days=days - 1)
    else:
        start = since if since is not None else today
        end = until if until is not None else today
    if start > end:
        raise ValueError(f"--since({start})가 --until({end})보다 늦다")
    return start, end


async def run(
    *,
    start_date: date,
    end_date: date,
    tz: ZoneInfo,
    min_solve_time_sample: int,
    dry_run: bool,
) -> RollupReport:
    """엔진 생성 → 롤업 → 커밋(또는 dry-run 롤백) → 엔진 정리. 예외는 호출자에게 전파."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            # EOS-131: 롤업 전에 유휴 초과 서버 세션을 마지막 활동 시각으로 닫는다(배치 시점 확정 —
            # 다시 오지 않는 학생의 세션이 영원히 열려 있지 않게). 롤업이 ended_at−started_at 폴백을
            # 쓰므로 순서가 중요하다. 배치 경로라 never-break가 아니다(실패는 호출자에게 전파).
            closed = await close_idle_sessions(session)
            _logger.info("유휴 초과 학습 세션 종료 확정 %d건(dry_run=%s).", closed, dry_run)
            report = await run_daily_rollup(
                session,
                start_date=start_date,
                end_date=end_date,
                tz=tz,
                min_solve_time_sample=min_solve_time_sample,
                dry_run=dry_run,
            )
            if dry_run:
                # 읽기만 했더라도 명시 롤백 — "쓰지 않았음"을 코드로 보이게 한다.
                await session.rollback()
            else:
                await session.commit()
            return report
    finally:
        await engine.dispose()


def _parse_date(raw: str) -> date:
    """`YYYY-MM-DD` 파싱 — 형식 오류는 argparse가 사용자에게 그대로 보인다."""
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"날짜는 YYYY-MM-DD 형식이어야 한다: {raw!r}") from exc


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 롤업 리포트를 JSON으로 stdout에 내고 exit 0. 실패는 타입명 로그 + exit 1."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.learning_metrics_rollup_cli",
        description=(
            "일별 학습 지표 롤업(COLLAB-03) — learning_session·problem_attempt·attempt_event에서 "
            "daily_learning_metrics·user_behavior_metrics·problem_solve_time_distribution로 "
            "멱등 upsert. 기본 창은 어제·오늘 2일."
        ),
    )
    parser.add_argument("--since", type=_parse_date, default=None, help="집계 시작일(YYYY-MM-DD).")
    parser.add_argument("--until", type=_parse_date, default=None, help="집계 종료일(YYYY-MM-DD).")
    parser.add_argument(
        "--days",
        type=int,
        default=2,
        help="--since/--until 미지정 시 오늘 포함 최근 N일 재집계(기본 2 — 어제·오늘).",
    )
    parser.add_argument(
        "--timezone",
        dest="timezone",
        type=str,
        default=str(KST),
        help="달력일 경계 타임존(기본 Asia/Seoul — 학습자 생활 시간대).",
    )
    parser.add_argument(
        "--min-solve-time-sample",
        type=int,
        default=MIN_SOLVE_TIME_SAMPLE,
        help=(
            f"풀이 시간 분포의 k-익명 하한(기본 {MIN_SOLVE_TIME_SAMPLE}). 이 표본 미만 "
            "(문항, 페르소나) 조합은 적재하지 않는다."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="DB 미기록 — 집계 결과만 출력.")
    args = parser.parse_args(argv)

    try:
        tz = ZoneInfo(args.timezone)
    except Exception as exc:  # 알 수 없는 타임존 — 타입명과 함께 즉시 실패(침묵 금지).
        parser.error(f"알 수 없는 타임존 {args.timezone!r}: {type(exc).__name__}")

    try:
        start_date, end_date = resolve_window(
            since=args.since,
            until=args.until,
            days=args.days,
            today=datetime.now(tz).date(),
        )
    except ValueError as exc:
        parser.error(str(exc))

    try:
        report = asyncio.run(
            run(
                start_date=start_date,
                end_date=end_date,
                tz=tz,
                min_solve_time_sample=args.min_solve_time_sample,
                dry_run=args.dry_run,
            )
        )
    except Exception as exc:
        # 침묵 실패 금지 — 예외 *타입명*을 반드시 남긴다(값·PII는 싣지 않는다).
        _logger.error(
            "learning_metrics_rollup 실패: %s (창 %s~%s)",
            type(exc).__name__,
            start_date,
            end_date,
        )
        raise

    json.dump(report.to_json(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
