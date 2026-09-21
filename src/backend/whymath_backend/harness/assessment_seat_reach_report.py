"""평가 결과 영속 좌석(`assessment` 4테이블) 도달 관측 리포트 — ASM-01 acceptance②.

설계 정본: `docs/architecture/assessment_module_gap_review.md` §3 D1. `assessment`·
`concept_mastery_history`·`skill_mastery_history`·`ability_snapshot` 4테이블의 행 수·분포·결손을
관측한다. ASM-01 동결 시점(2026-08)에는 `assessment` 본체가 조회·완료·삭제·프라이버시 5개 표면
완비 상태에서 `Assessment(...)` 생성 코드 0건이었고(이 시리즈 "완비된 소비 경로+미도달 공급원"
8회차) 이 모듈이 그 사실을 눈에 보이게 하는 좌석이었다. **2026-08-10(ASM-05 세션) 실측 정정**:
ASM-03(capture)·ASM-04(assemble)·mastery 트래킹 착지로 4테이블 전부 라이브 writer가 실재한다 —
지금 이 리포트가 감시하는 것은 "writer 부재"가 아니라 "writer 실재 상태의 실호출 여부"다.

**게이트가 아니다**(`visualization_reach_report`·`problem_bank_coverage`와 동일 원칙) — 카운트가
0이어도 exit 1을 내지 않는다. 목표는 활성화가 아니라 가시화다.

**"0건"과 "writer 부재"를 혼동하지 않는다** — `_KNOWN_WRITER_CITATION`이 테이블별 writer 유무를
정적으로 기록해 두 상태("생성 경로 자체가 없음" vs "생성 경로는 있으나 아직 호출된 적 없음")를
구분해 렌더한다. 카운트 0인 테이블에 writer가 실재하는데 "생성 경로 부재"라고 말하면 거짓 주장이
된다(ASM-01 당시 `ability_snapshot`이 그 반례였고, 지금은 4테이블 전부가 그렇다). 향후 writer
없는 테이블이 이 대장에 추가되면 값 None으로 "생성 경로 부재"가 다시 렌더된다 — 두 상태의
변별력은 hermetic 테스트가 합성 writerless 항목으로 동결한다.

산출 3축:
  1. **4테이블 행 수** — 테이블별 row count + writer 유무에 따른 정직한 사유 문구.
  2. **`AssessmentType` 5종 분포** — DB에 실재하는 값만이 아니라 5종 전부를 보여준다(데이터 없는
     값도 0으로 명시 — 조용한 생략 금지).
  3. **진단 산출물 JSONB 결손** — `concept_diagnosis`(오개념 목록이 여기 담길 자리)·
     `recommended_path`(추천 학습경로)·`strong_points`(강점 개념·ASM-13)가 비어있지 않은 row
     수. 하드코딩이 아니라 실제 쿼리 결과를 그대로 신뢰한다(측정 없는 도입 없음).

[ASM-13·2026-09-06] `strong_points`는 `recommend_strong_concepts`(l2/strong_concept_
recommendation.py) writer 착지 전까지 writer 0건이었다 — "작동 신호 없는 알고리즘 부착 금지"
준수를 위해 착지와 같은 PR에서 이 결손 카운트를 동반 추가한다(하드코딩 필드 추가가 아니라
실제 채운 비율을 보이게 하는 것).

사용:
    python -m whymath_backend.harness.assessment_seat_reach_report
    python -m whymath_backend.harness.assessment_seat_reach_report --json out/asm_reach.json
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

from whymath_backend.db.models.assessment import (
    AbilitySnapshot,
    Assessment,
    ConceptMasteryHistory,
    SkillMasteryHistory,
)
from whymath_backend.db.session import get_sessionmaker
from whymath_backend.schema.enums import AssessmentType

__all__ = [
    "SeatCounts",
    "SeatReachReport",
    "TableSeat",
    "build_report",
    "collect_seat_counts",
    "dump_json",
    "main",
    "render_report",
    "report_to_json",
]

_EXIT_OK = 0
_EXIT_INPUT_ERROR = 2

# 렌더링 사유 3종 — count>0/writer 없음/writer 있음의 상호 배타 3분류(§D1 "0건≠writer 부재").
_REASON_OBSERVED = "관측됨"
_REASON_NO_PRODUCER = "생성 경로 부재"
_REASON_UNCALLED_WRITER = "writer 존재하나 미호출 관측"

# 테이블별 실제 writer 인용 — None이면 저장소 전체에 생성 코드 0(전수 grep 실측). 있으면 그
# writer가 아직 호출되지 않았을 뿐임을 렌더가 구분해야 한다(혼동하면 거짓 주장이 된다).
# [ASM-05 stale 정정·2026-08-10 실측] ASM-01 동결 당시 assessment·concept_mastery_history·
# skill_mastery_history는 None(생성 경로 부재)이었으나 ASM-03(capture)·ASM-04(assemble)·
# mastery 트래킹 착지로 라이브 writer가 실재한다 — 인용을 실측 갱신했다(행 번호는 2026-08-10
# 기준·기존 ability_snapshot 인용 :965도 드리프트해 :1030으로 재실측 정정). '오류 발견 시
# 조용히 넘어가지 않기' 집행이며, 빈 테이블의 사유가 '생성 경로 부재'→'writer 존재하나 미호출
# 관측'으로 바뀌는 것은 의도된 진실 갱신이다(동결 테스트도 새 진실로 재작성).
# [EOS-57 실측 재정정·2026-09-01] 위 5개 행 번호가 08-10 이후 me.py 성장으로 전부 드리프트해
# 있었다(738→759·743→764·1030→1064·2714→2768·2927→2970 · l2 134→202·136→148). EOS-57이
# me.py 채점 경로를 건드리며 재실측해 갱신한다 — 이 인용은 사람이 코드를 찾아가는 앵커이므로
# 틀린 번호는 조용한 거짓 주장이다(모듈 docstring이 예고한 '다음 드리프트' 회차).
_KNOWN_WRITER_CITATION: dict[str, str | None] = {
    "assessment": (
        "POST /v1/me/assessments/capture — capture_measurement_assessment (api/me.py:2768)"
        " · POST /v1/me/assessments/assemble — assemble_blueprint_assessment (api/me.py:2970)"
    ),
    "concept_mastery_history": (
        "POST /v1/me/attempts — submit_attempt → record_problem_attempt_mastery"
        " (api/me.py:759 → l2/mastery_tracking.py:202)"
    ),
    "skill_mastery_history": (
        "POST /v1/me/attempts — submit_attempt → record_problem_attempt_skill_mastery"
        " (api/me.py:764 → l2/skill_mastery_tracking.py:148)"
    ),
    "ability_snapshot": (
        "POST /v1/me/ability/snapshots — capture_ability_snapshot (api/me.py:1064)"
    ),
}

# 테이블 렌더 순서(§부록 표와 동일 순서 — assessment 본체 먼저, 형제 3종 뒤).
_TABLE_ORDER: tuple[str, ...] = (
    "assessment",
    "concept_mastery_history",
    "skill_mastery_history",
    "ability_snapshot",
)


@dataclass(slots=True, frozen=True)
class SeatCounts:
    """`collect_seat_counts`의 DB 원시 조회 결과 투영 — `build_report`의 유일한 입력.

    `assessment_type_counts`는 DB에 *실재하는* 값만 담는다(5종 보강은 순수 `build_report`가
    수행 — 그래야 단위테스트가 DB 없이 보강 로직 자체를 검증할 수 있다).
    """

    table_row_counts: dict[str, int]
    assessment_type_counts: dict[str, int]
    concept_diagnosis_nonempty_count: int
    recommended_path_nonempty_count: int
    strong_points_nonempty_count: int


@dataclass(slots=True, frozen=True)
class TableSeat:
    """테이블 1건의 리포트 투영 — 행 수 + writer 유무 + 그에 따른 정직한 사유 문구."""

    name: str
    row_count: int
    writer_citation: str | None
    reason: str


@dataclass(slots=True, frozen=True)
class SeatReachReport:
    """도달 관측 결과 전량(불변·렌더/직렬화의 단일 입력)."""

    seats: tuple[TableSeat, ...]
    assessment_type_distribution: dict[str, int]  # AssessmentType 5종 전부(0 보강 완료)
    concept_diagnosis_nonempty_count: int
    recommended_path_nonempty_count: int
    strong_points_nonempty_count: int


async def collect_seat_counts(session: AsyncSession) -> SeatCounts:
    """4테이블 행 수 + `assessment_type` 분포 + JSONB 결손 카운트를 조회(유일한 DB 접근 지점).

    전부 ORM 쿼리빌더로만 조립한다(원시 SQL 금지 — CLAUDE.md 원칙). `func.jsonb_array_length`는
    SQLAlchemy `func` 네임스페이스를 통한 표준 함수 호출이라 원시 SQL 문자열이 아니다.
    """
    table_counts: dict[str, int] = {}
    for name, model in (
        ("assessment", Assessment),
        ("concept_mastery_history", ConceptMasteryHistory),
        ("skill_mastery_history", SkillMasteryHistory),
        ("ability_snapshot", AbilitySnapshot),
    ):
        result = await session.execute(select(func.count()).select_from(model))
        table_counts[name] = result.scalar_one()

    type_result = await session.execute(
        select(Assessment.assessment_type, func.count())
        .where(Assessment.assessment_type.is_not(None))
        .group_by(Assessment.assessment_type)
    )
    # enum 컬럼은 `AssessmentType` 인스턴스로 돌아온다 — 정본 표기는 `.value`(D-100예측 하이픈).
    type_counts = {row[0].value: row[1] for row in type_result.all()}

    concept_diagnosis_nonempty = await session.execute(
        select(func.count())
        .select_from(Assessment)
        .where(func.jsonb_array_length(Assessment.concept_diagnosis) > 0)
    )
    recommended_path_nonempty = await session.execute(
        select(func.count())
        .select_from(Assessment)
        .where(func.jsonb_array_length(Assessment.recommended_path) > 0)
    )
    strong_points_nonempty = await session.execute(
        select(func.count())
        .select_from(Assessment)
        .where(func.jsonb_array_length(Assessment.strong_points) > 0)
    )

    return SeatCounts(
        table_row_counts=table_counts,
        assessment_type_counts=type_counts,
        concept_diagnosis_nonempty_count=concept_diagnosis_nonempty.scalar_one(),
        recommended_path_nonempty_count=recommended_path_nonempty.scalar_one(),
        strong_points_nonempty_count=strong_points_nonempty.scalar_one(),
    )


def _reason_for(name: str, count: int) -> str:
    """행 수 + writer 유무 → 3분류 중 하나(§D1 핵심 — 0건과 writer 부재를 혼동하지 않는다)."""
    if count > 0:
        return _REASON_OBSERVED
    writer = _KNOWN_WRITER_CITATION.get(name)
    return _REASON_UNCALLED_WRITER if writer is not None else _REASON_NO_PRODUCER


def build_report(counts: SeatCounts) -> SeatReachReport:
    """DB 조회 결과(`SeatCounts`) → `SeatReachReport`(순수·부작용 0·DB 세션 불요).

    `AssessmentType` 5종 전부를 여기서 보강한다(DB에 없는 값도 0으로 명시) — 이 보강을
    `collect_seat_counts`가 아니라 여기서 하는 이유는, 단위테스트가 실 DB 없이 "5종 전부가
    빠짐없이 나타나는가"를 직접 검증할 수 있게 하기 위함이다.
    """
    seats = tuple(
        TableSeat(
            name=name,
            row_count=counts.table_row_counts.get(name, 0),
            writer_citation=_KNOWN_WRITER_CITATION.get(name),
            reason=_reason_for(name, counts.table_row_counts.get(name, 0)),
        )
        for name in _TABLE_ORDER
    )
    # 5종 전부 보강 — `.value`로 순회해 D-100예측의 하이픈 표기를 정확히 유지한다.
    distribution = {t.value: counts.assessment_type_counts.get(t.value, 0) for t in AssessmentType}
    return SeatReachReport(
        seats=seats,
        assessment_type_distribution=distribution,
        concept_diagnosis_nonempty_count=counts.concept_diagnosis_nonempty_count,
        recommended_path_nonempty_count=counts.recommended_path_nonempty_count,
        strong_points_nonempty_count=counts.strong_points_nonempty_count,
    )


def render_report(report: SeatReachReport, *, max_listed: int = 40) -> str:
    """도달 관측 결과를 마크다운으로 렌더(순수·입력 외 계산 없음).

    `max_listed`는 이 리포트에는 목록형 산출물이 없어 현재 미사용이나, 시리즈 관례
    (`visualization_reach_report.render_report`)와 시그니처를 맞춰 향후 목록 확장 시
    호출부를 바꾸지 않아도 되게 한다.
    """
    del max_listed  # 현재 렌더에는 목록이 없다 — 시그니처만 관례에 맞춘다.
    lines: list[str] = [
        "# 평가 결과 영속 좌석 도달 관측 리포트 (ASM-01 D1)",
        "",
        "> 관측 리포트다 — **exit 게이트가 아니다**(행 수가 0이어도 실패시키지 않는다).",
        "> 활성화가 아니라 가시화가 목표다 — 생성 API 신설은 이 리포트의 범위 밖이다.",
        "",
        "## 1. 좌석별 행 수",
        "",
        "| 테이블 | 행 수 | writer | 사유 |",
        "|---|---:|---|---|",
    ]
    for seat in report.seats:
        writer_cell = seat.writer_citation if seat.writer_citation is not None else "—"
        lines.append(f"| `{seat.name}` | {seat.row_count} | {writer_cell} | {seat.reason} |")

    lines += [
        "",
        f"- `{_REASON_NO_PRODUCER}`: 저장소 전체에 이 테이블에 행을 생성하는 코드가 없다"
        "(0건이 곧 구조적 부재).",
        f"- `{_REASON_UNCALLED_WRITER}`: 생성 경로(writer)는 실재하나 이번 조회 시점에 행이"
        " 없다(0건이 부재를 뜻하지 않는다 — 혼동 방지).",
        "",
        "## 2. AssessmentType 분포 (5종 전부 — 데이터 없는 값도 0으로 명시)",
        "",
        "| 유형 | 건수 |",
        "|---|---:|",
    ]
    for type_value, count in report.assessment_type_distribution.items():
        lines.append(f"| {type_value} | {count} |")

    lines += [
        "",
        "## 3. 진단 산출물 JSONB 결손 (오개념 목록·강점 개념·추천 학습경로)",
        "",
        f"- `concept_diagnosis`(오개념 목록이 담길 자리) 비어있지 않은 행: "
        f"**{report.concept_diagnosis_nonempty_count}**",
        f"- `strong_points`(강점 개념·ASM-13) 비어있지 않은 행: "
        f"**{report.strong_points_nonempty_count}**",
        f"- `recommended_path`(추천 학습경로) 비어있지 않은 행: "
        f"**{report.recommended_path_nonempty_count}**",
        "- 이 값은 하드코딩이 아니라 실제 쿼리 결과다(측정 없는 도입 없음) — `assessment`"
        " writer가 0이던 ASM-01 시점엔 구조적 0이었으나, capture/assemble writer 착지"
        "(ASM-03·ASM-04·ASM-13) 후에는 실측값이다.",
        "",
    ]
    return "\n".join(lines)


def report_to_json(report: SeatReachReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict(키 정렬은 dump 시 `sort_keys=True`로 고정)."""
    return {
        "seats": [
            {
                "name": seat.name,
                "row_count": seat.row_count,
                "writer_citation": seat.writer_citation,
                "reason": seat.reason,
            }
            for seat in report.seats
        ],
        "assessment_type_distribution": report.assessment_type_distribution,
        "concept_diagnosis_nonempty_count": report.concept_diagnosis_nonempty_count,
        "recommended_path_nonempty_count": report.recommended_path_nonempty_count,
        "strong_points_nonempty_count": report.strong_points_nonempty_count,
    }


def dump_json(report: SeatReachReport) -> str:
    return json.dumps(report_to_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# CLI (얇은 껍데기 — DB 조회·입출력만, 집계는 위 순수 코어)
# ──────────────────────────────────────────────────────────────────────────
async def _run() -> SeatReachReport:  # pragma: no cover — 라이브 PG 연결 glue
    """세션을 열어 좌석 카운트를 조회하고 리포트를 조립한다(DB 조회 전용·쓰기 0)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        counts = await collect_seat_counts(session)
    return build_report(counts)


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 좌석 도달 관측 리포트를 stdout에 출력. **0=성공(카운트 0이어도) / 2=DB 오류**.

    DB 접속·쿼리 실패는 예외 타입명을 stderr에 포함해 보고한다(CLAUDE.md 침묵 실패 금지 —
    무타입 경고 금지 원칙).
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.assessment_seat_reach_report",
        description=(
            "평가 결과 영속 좌석(assessment 4테이블) 도달 관측 리포트(ASM-01 D1) — 행 수·"
            "AssessmentType 분포·진단 산출물 JSONB 결손. 결정론 아님(DB 실측)·게이트 아님"
            "(exit 0/2)."
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        type=Path,
        default=None,
        help="JSON 산출물 경로(선택)",
    )
    args = parser.parse_args(argv)

    try:
        report = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — DB 오류는 타입명과 함께 보고하고 exit 2
        print(
            f"DB 오류 — 좌석 카운트 조회 실패({type(exc).__name__}): {exc}",
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
