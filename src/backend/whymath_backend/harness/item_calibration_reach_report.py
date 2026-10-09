"""문항 난이도 보정 루프 도달 관측 리포트 — PB-10 acceptance①.

설계 정본: `docs/architecture/problem_bank_gap_review_r3.md` §3 G4·§2 기능19.
`l2/calibrate_items.py`(IRT 보정 배치 CLI)는 완비돼 있지만 PB-10 착수 시점에
**저장소 안에 그것을 부르는 곳이 0건**이었다(`.github/workflows`·`docker-compose*.yml`·
`infra/` 전수 grep 무일치). 응답이 쌓여도 `irt_difficulty_b`는 자동으로 채워지지 않는다 —
데이터 잠금(S3-01 파일럿)이 아니라 *배선 부재*다. 이 모듈은 그 "휴면 중"을 숫자로 보이게
하는 좌석이다.

**게이트가 아니다**(`assessment_seat_reach_report`와 동일 원칙) — 어떤 숫자여도 exit 1을
내지 않는다. 목표는 활성화가 아니라 가시화다.

산출 4축 (전부 DB 읽기 전용 · 쓰기 0):
  1. **채움률** — `Problem` 전체 대비 `irt_difficulty_b`·`irt_a`가 NULL이 아닌 문항 수.
  2. **응답 규모** — 보정 입력과 *같은 필터*(`is_correct`·`user_id`·`problem_id` 모두
     NOT NULL)의 채점 응답 수·응답 학생 수·응답이 있는 문항 수.
  3. **보정 제외 사유** — 응답 `_MIN_RESPONSES_FOR_CALIBRATION`(5)회 미만 문항은 b 추정이
     불안정해 보정에서 빠지고 휴리스틱 b를 유지한다(`l2/item_calibration.py`). 제외 문항
     수와 자격 문항 수.
  4. **루프 판정** — 자격 문항(응답 ≥ 5) 중 `irt_difficulty_b`가 NULL인 문항 수로 보정
     배치가 *실제로 돌았는가*를 날짜 없이 판정한다(아래 5상태).

**판정 5상태** (상호 배타 · 위에서부터 첫 일치):
  - `NO_RESPONSES` — 채점 응답 0행. 보정 배치가 돌아도 no-op이 정상이다(휴면이 아니라
    입력 부재).
  - `NO_ELIGIBLE_ITEMS` — 응답은 있으나 5회 이상 쌓인 문항이 0건. 이것도 no-op이 정상이다.
  - `LOOP_DORMANT` — 자격 문항이 있는데 **그 전부**가 b NULL. 배치가 한 번도 돌지 않았다는
    증거다(PB-10이 만들려던 신호 — 배선 부재/미가동이 여기서 숫자로 드러난다).
  - `LOOP_STALE` — 자격 문항 일부만 채워짐. 배치가 과거에 돌았고 이후 새로 자격을 얻은
    문항이 있다(다음 실행을 기다리는 정상 상태일 수도, 배치가 멈춘 상태일 수도 있어
    단독으로 단정하지 않는다).
  - `LOOP_CAUGHT_UP` — 자격 문항 전부 채워짐.

**마지막 보정 시각은 이 리포트가 알 수 없다** — `Problem`에 `calibrated_at` 컬럼이 없고
`updated_at`은 `onupdate`가 없어 보정 UPDATE로 갱신되지 않는다(2026-10-08 실측 ·
`db/models/problem.py`). 그래서 "모른다"를 `last_calibration_at=unrecorded`로 명시한다
(0·null로 접지 않는다 — 모른다 ≠ 아니다). 시각은 보정 CLI가 실행마다 남기는 구조화 로그
한 줄(`calibration_run ... finished_at=...`)에 있고, 영속 좌석이 필요하면 마이그레이션이
따르므로 별도 태스크 몫이다. 위 5상태 판정은 시각 없이 성립한다.

사용:
    python -m whymath_backend.harness.item_calibration_reach_report
    python -m whymath_backend.harness.item_calibration_reach_report --json out/reach.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.session import dispose_engine, get_sessionmaker

# 보정 자격 임계 — `l2/item_calibration.py`의 b 채택 최소 응답 수와 **같은 값이어야** 한다.
# 값을 복제하지 않고 원천을 import한다(복제하면 임계가 바뀔 때 두 곳이 조용히 어긋난다).
from whymath_backend.l2.item_calibration import (
    _MIN_RESPONSES_FOR_CALIBRATION as MIN_RESPONSES_FOR_CALIBRATION,
)

__all__ = [
    "MIN_RESPONSES_FOR_CALIBRATION",
    "VERDICTS",
    "CalibrationReachCounts",
    "CalibrationReachReport",
    "build_report",
    "classify",
    "collect_counts",
    "dump_json",
    "main",
    "render_report",
    "report_to_json",
]

_EXIT_OK = 0
_EXIT_INPUT_ERROR = 2

VERDICT_NO_RESPONSES = "NO_RESPONSES"
VERDICT_NO_ELIGIBLE_ITEMS = "NO_ELIGIBLE_ITEMS"
VERDICT_LOOP_DORMANT = "LOOP_DORMANT"
VERDICT_LOOP_STALE = "LOOP_STALE"
VERDICT_LOOP_CAUGHT_UP = "LOOP_CAUGHT_UP"
#: 판정 순서가 곧 이 튜플의 순서다(앞 상태가 걸리면 뒤는 보지 않는다).
VERDICTS: tuple[str, ...] = (
    VERDICT_NO_RESPONSES,
    VERDICT_NO_ELIGIBLE_ITEMS,
    VERDICT_LOOP_DORMANT,
    VERDICT_LOOP_STALE,
    VERDICT_LOOP_CAUGHT_UP,
)

# 상태별 해설 — 같은 "b 채움 0건"이라도 입력 부재와 배치 미가동은 다른 사실이다(혼동 금지).
_VERDICT_MEANING: dict[str, str] = {
    VERDICT_NO_RESPONSES: (
        "채점 응답이 0행이다 — 보정 배치가 돌아도 no-op이 정상이며, "
        "이것은 휴면이 아니라 입력 부재다."
    ),
    VERDICT_NO_ELIGIBLE_ITEMS: (
        f"응답은 있으나 {MIN_RESPONSES_FOR_CALIBRATION}회 이상 쌓인 문항이 0건이다 — "
        "보정 배치가 돌아도 no-op이 정상이다(b 추정 불안정 구간)."
    ),
    VERDICT_LOOP_DORMANT: (
        "보정 자격 문항이 있는데 그 전부가 irt_difficulty_b NULL이다 — "
        "보정 배치가 한 번도 돌지 않았다는 증거다(스케줄 배선 부재 또는 미가동)."
    ),
    VERDICT_LOOP_STALE: (
        "보정 자격 문항 중 일부만 채워졌다 — 배치가 과거에 돌았고 이후 새로 자격을 얻은 "
        "문항이 있다. 다음 실행 대기일 수도 배치 정지일 수도 있어 이 값만으로 단정하지 않는다."
    ),
    VERDICT_LOOP_CAUGHT_UP: (
        "보정 자격 문항이 전부 채워졌다 — 마지막 실행 이후 새로 자격을 얻은 문항이 없다."
    ),
}

LAST_CALIBRATION_UNRECORDED = "unrecorded"


@dataclass(slots=True, frozen=True)
class CalibrationReachCounts:
    """`collect_counts`의 DB 원시 조회 결과 — `build_report`의 유일한 입력."""

    problem_total: int
    irt_b_filled: int
    irt_a_filled: int
    graded_attempts: int
    distinct_students: int
    items_with_responses: int
    eligible_items: int
    eligible_unfilled: int


@dataclass(slots=True, frozen=True)
class CalibrationReachReport:
    """도달 관측 결과 전량(불변 · 렌더/직렬화의 단일 입력)."""

    counts: CalibrationReachCounts
    items_below_floor: int
    eligible_filled: int
    verdict: str
    verdict_meaning: str
    last_calibration_at: str

    @property
    def irt_b_fill_ratio(self) -> float | None:
        """b 채움률 = 채움 / 전체 문항. **분모 0이면 None**(0.0으로 접지 않는다)."""
        if self.counts.problem_total == 0:
            return None
        return self.counts.irt_b_filled / self.counts.problem_total

    @property
    def irt_a_fill_ratio(self) -> float | None:
        if self.counts.problem_total == 0:
            return None
        return self.counts.irt_a_filled / self.counts.problem_total


async def collect_counts(session: AsyncSession) -> CalibrationReachCounts:
    """채움률·응답 규모·자격 문항·자격 미채움 문항을 조회(유일한 DB 접근 지점 · 읽기 전용).

    응답 필터는 보정 입력(`calibrate_item_difficulties`)과 **글자 그대로 같다** — 필터가 다르면 이
    리포트의 "자격 문항"이 실제 배치가 보는 문항과 어긋난다. ORM 쿼리빌더만 쓴다(원시 SQL 금지).
    """
    graded = (
        ProblemAttempt.is_correct.isnot(None),
        ProblemAttempt.user_id.isnot(None),
        ProblemAttempt.problem_id.isnot(None),
    )

    problem_total = (await session.execute(select(func.count()).select_from(Problem))).scalar_one()
    irt_b_filled = (
        await session.execute(
            select(func.count()).select_from(Problem).where(Problem.irt_difficulty_b.isnot(None))
        )
    ).scalar_one()
    irt_a_filled = (
        await session.execute(
            select(func.count()).select_from(Problem).where(Problem.irt_a.isnot(None))
        )
    ).scalar_one()

    graded_attempts, distinct_students = (
        await session.execute(
            select(func.count(), func.count(func.distinct(ProblemAttempt.user_id))).where(*graded)
        )
    ).one()

    # 문항별 채점 응답 수 서브쿼리 — items_with_responses·eligible·eligible_unfilled가
    # 같은 집합을 본다.
    per_item = (
        select(ProblemAttempt.problem_id.label("problem_id"), func.count().label("n"))
        .where(*graded)
        .group_by(ProblemAttempt.problem_id)
        .subquery()
    )
    items_with_responses = (
        await session.execute(select(func.count()).select_from(per_item))
    ).scalar_one()
    eligible_items = (
        await session.execute(
            select(func.count())
            .select_from(per_item)
            .where(per_item.c.n >= MIN_RESPONSES_FOR_CALIBRATION)
        )
    ).scalar_one()
    eligible_unfilled = (
        await session.execute(
            select(func.count())
            .select_from(per_item)
            .join(Problem, Problem.problem_id == per_item.c.problem_id)
            .where(
                per_item.c.n >= MIN_RESPONSES_FOR_CALIBRATION,
                Problem.irt_difficulty_b.is_(None),
            )
        )
    ).scalar_one()

    return CalibrationReachCounts(
        problem_total=problem_total,
        irt_b_filled=irt_b_filled,
        irt_a_filled=irt_a_filled,
        graded_attempts=graded_attempts,
        distinct_students=distinct_students,
        items_with_responses=items_with_responses,
        eligible_items=eligible_items,
        eligible_unfilled=eligible_unfilled,
    )


def classify(counts: CalibrationReachCounts) -> str:
    """원시 카운트 → 5상태 판정(순수 · 위에서부터 첫 일치)."""
    if counts.graded_attempts == 0:
        return VERDICT_NO_RESPONSES
    if counts.eligible_items == 0:
        return VERDICT_NO_ELIGIBLE_ITEMS
    if counts.eligible_unfilled == counts.eligible_items:
        return VERDICT_LOOP_DORMANT
    if counts.eligible_unfilled > 0:
        return VERDICT_LOOP_STALE
    return VERDICT_LOOP_CAUGHT_UP


def build_report(counts: CalibrationReachCounts) -> CalibrationReachReport:
    """DB 조회 결과 → 리포트(순수 · 부작용 0 · DB 세션 불요)."""
    verdict = classify(counts)
    return CalibrationReachReport(
        counts=counts,
        items_below_floor=counts.items_with_responses - counts.eligible_items,
        eligible_filled=counts.eligible_items - counts.eligible_unfilled,
        verdict=verdict,
        verdict_meaning=_VERDICT_MEANING[verdict],
        last_calibration_at=LAST_CALIBRATION_UNRECORDED,
    )


def _ratio_text(ratio: float | None) -> str:
    """분모 0이면 `none` — 0.0000으로 쓰면 "측정 대상 없음"이 "전부 비었다"처럼 읽힌다."""
    return "none" if ratio is None else f"{ratio:.4f}"


def render_report(report: CalibrationReachReport) -> str:
    """도달 관측 결과를 마크다운으로 렌더(순수 · 입력 외 계산 없음)."""
    c = report.counts
    lines = [
        "# 문항 난이도 보정 루프 도달 관측 리포트 (PB-10 ①)",
        "",
        "> 관측 리포트다 — **exit 게이트가 아니다**(어떤 숫자여도 실패시키지 않는다).",
        "> 활성화가 아니라 가시화가 목표다 — 스케줄 좌석은 `docker-compose.prod.yml`의"
        " `item-calibration`.",
        "",
        f"## 판정: `{report.verdict}`",
        "",
        f"- {report.verdict_meaning}",
        "",
        "## 1. 채움률",
        "",
        "| 컬럼 | 채움 | 전체 문항 | 비율 |",
        "|---|---:|---:|---:|",
        f"| `irt_difficulty_b` | {c.irt_b_filled} | {c.problem_total} | "
        f"{_ratio_text(report.irt_b_fill_ratio)} |",
        f"| `irt_a` | {c.irt_a_filled} | {c.problem_total} | "
        f"{_ratio_text(report.irt_a_fill_ratio)} |",
        "",
        "## 2. 응답 규모 (보정 입력과 같은 필터)",
        "",
        f"- 채점 응답: **{c.graded_attempts}**",
        f"- 응답 학생: **{c.distinct_students}**",
        f"- 응답이 있는 문항: **{c.items_with_responses}**",
        "",
        f"## 3. 보정 제외 사유 (응답 {MIN_RESPONSES_FOR_CALIBRATION}회 미만)",
        "",
        f"- 제외(응답 1~{MIN_RESPONSES_FOR_CALIBRATION - 1}회): **{report.items_below_floor}** "
        "— b 추정 불안정이라 휴리스틱 b 유지",
        f"- 자격(응답 ≥ {MIN_RESPONSES_FOR_CALIBRATION}회): **{c.eligible_items}**"
        f" (채움 {report.eligible_filled} · **미채움 {c.eligible_unfilled}**)",
        "",
        "## 4. 마지막 보정 시각",
        "",
        f"- `last_calibration_at={report.last_calibration_at}` — 이 DB에는 저장 좌석이 없다"
        "(`Problem.calibrated_at` 부재 · `updated_at`은 보정 UPDATE로 갱신되지 않음). "
        "시각은 보정 CLI가 실행마다 남기는 로그 한 줄 "
        "`calibration_run ... finished_at=...`에 있다. 위 판정은 시각 없이 성립한다.",
        "",
    ]
    return "\n".join(lines)


def report_to_json(report: CalibrationReachReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict."""
    c = report.counts
    return {
        "verdict": report.verdict,
        "verdict_meaning": report.verdict_meaning,
        "problem_total": c.problem_total,
        "irt_b_filled": c.irt_b_filled,
        "irt_a_filled": c.irt_a_filled,
        "irt_b_fill_ratio": report.irt_b_fill_ratio,
        "irt_a_fill_ratio": report.irt_a_fill_ratio,
        "graded_attempts": c.graded_attempts,
        "distinct_students": c.distinct_students,
        "items_with_responses": c.items_with_responses,
        "items_below_floor": report.items_below_floor,
        "min_responses_for_calibration": MIN_RESPONSES_FOR_CALIBRATION,
        "eligible_items": c.eligible_items,
        "eligible_filled": report.eligible_filled,
        "eligible_unfilled": c.eligible_unfilled,
        "last_calibration_at": report.last_calibration_at,
    }


def dump_json(report: CalibrationReachReport) -> str:
    return json.dumps(report_to_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


async def _run() -> CalibrationReachReport:  # pragma: no cover — 라이브 PG 연결 glue
    """세션을 열어 카운트를 조회하고 리포트를 조립한다(읽기 전용 · 만든 쪽이 엔진을 치운다)."""
    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as session:
            counts = await collect_counts(session)
    finally:
        await dispose_engine()
    return build_report(counts)


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 보정 루프 도달 관측 리포트를 stdout에 출력.

    **0=성공(어떤 판정이어도) / 2=DB 오류**.

    DB 접속·쿼리 실패는 예외 타입명을 stderr에 포함해 보고한다(침묵 실패 금지).
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.item_calibration_reach_report",
        description=(
            "문항 난이도 보정 루프 도달 관측 리포트(PB-10) — irt_difficulty_b·irt_a 채움률, "
            "응답 규모, 보정 제외 사유, 루프 5상태 판정. "
            "결정론 아님(DB 실측) · 게이트 아님(exit 0/2)."
        ),
    )
    parser.add_argument(
        "--json", dest="json_path", type=Path, default=None, help="JSON 산출물 경로(선택)"
    )
    args = parser.parse_args(argv)

    try:
        report = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — DB 오류는 타입명과 함께 보고하고 exit 2
        print(f"DB 오류 — 보정 루프 카운트 조회 실패({type(exc).__name__}): {exc}", file=sys.stderr)
        return _EXIT_INPUT_ERROR

    print(render_report(report))
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(dump_json(report), encoding="utf-8")
        print(f"JSON 산출물: {args.json_path}")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
