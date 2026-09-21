"""주간 지표 자동 집계 — EOS-51 §6 "기술 KPI 6종"을 `metrics/weekly.json`에 append (OPS-56).

무엇을 재나 (정본: `docs/standards/eos_verification_design_v1.md` §6)
--------------------------------------------------------------------
EOS-51이 동결한 **기술 KPI 6종**만 낸다 — HIT·자동검증 1차 통과율·재작업률·처리량·단위비용·
실패유형분포. "내용 KPI 6종"(수학 오류율 등)은 앵커 표본 인간 검수가 필요해 주간 로그
집계로 낼 수 없으므로 이 모듈의 범위 밖이다(§6 자신이 그렇게 구분한다).

**"7지표" 표기 정정(실측, 2026-09-11)**: `OPS-56` 태스크 notes·`docs/reviews/
eos_plan52_crosswalk_2026-09.md`·`docs/strategy/eos_transition_declaration_2026-08-30.md`가
전부 "주간 7지표"라고 적었지만, `eos_verification_design_v1.md` §6 어디에도 7번째 지표명이
없다(표 자신이 "기술 KPI **6종**"이라 못박는다). `MEMORY.md`에 별개 태스크(WH-1 대리지표
①~⑦)의 "7"이 있어 그것이 잘못 전파된 것으로 보인다(근거 = MEMORY.md 2026-09-11 OPS-56
결정 로그). acceptance①의 "자체 정의 금지"를 지키기 위해 **문서가 실제로 동결한 6종만**
집계하고 7번째를 지어내지 않는다.

미측정 ≠ 0 (acceptance ② — 이 모듈의 핵심 설계 원칙)
--------------------------------------------------
6종 중 **2종은 이 저장소에 집계 대상 로그 자체가 없다**(실측, 2026-09-11):
  - **자동검증 1차 통과율** — Deterministic Gate pass/fail을 누적 기록하는 테이블이 없다.
  - **재작업률** — Run 재생성 카운트 로그가 없다(EOS-55는 재현성 컬럼만 추가했고 재생성
    카운트 자체는 좌석 미착지 — `validation_scorecard.adapt_hit_cu_metrics` 독스트링 동일 판정).
이 둘은 DB 연결 성공 여부와 무관하게 **항상** `measured=False`로 낸다 — "0%"이 아니라
"측정 불가"다.

나머지 4종(HIT·처리량·단위비용·실패유형분포)은 `review_timer_event`·`generation_log`
테이블에서 실시간 계산한다(집계 수식은 재발명하지 않고 `ops.hit_cu_metrics.aggregate`를
그대로 재사용). 이 두 테이블이 지금 이 환경(어느 DB에 연결됐는가)에서 실제로 몇 행을
갖고 있는지에 따라 진짜 0(이번 주 활동 없음)과 미측정(DB 연결 자체 실패)이 갈린다 —
후자만 `measured=False`로 낸다.

**환경의 정직한 공백(중요)**: `review_timer_event`는 마이그레이션은 있지만 **쓰기 경로가
아직 없다**(`ReviewTimerEvent.from_schema()` 호출처 0건 — 검수 UI(ADMIN-07)가 아직 이
테이블에 쓰지 않는다). 그리고 이 저장소의 CI(GitHub Actions 호스팅 러너)가 붙는 Postgres는
`ci.yml`의 다른 실PG 잡들과 마찬가지로 **매 실행 새로 뜨는 빈 컨테이너**이지 Phaiakes9의
실제 콘텐츠 제작 DB가 아니다 — 원격에서 그 DB로의 네트워크 경로 자체가 없다(비밀값
`DEPLOY_SSH_*`는 배포 대상 서버용이지 Phaiakes9용이 아니다). 즉 **이 크론이 GitHub
Actions에서 도는 한, 4종 KPI는 당분간 정직하게 "0"(빈 스키마에 이번 주 행 0건)을 낼
것이다** — 이것은 이 모듈의 결함이 아니라 실제 환경 상태이며, 실제 운영 데이터에 닿게
하는 것은 러너 배선(OPS-19) 몫이다(acceptance③ 경계).

집행 별항(OPS-19와의 경계)
--------------------------
이 모듈은 "무엇을 어떻게 계산하는가"까지만 담당한다. "어느 DB에 연결해 언제 도는가"는
`WHYMATH_DATABASE_URL` 환경변수 + 이 파일이 신설하는 GitHub Actions 스케줄(월 07:00
KST)이 최소한으로 담당하되, **그 스케줄이 실제 프로덕션 데이터에 닿게 만드는 것**(러너가
Phaiakes9에 도달하는 경로)은 `OPS-19`의 몫이다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.config import get_settings
from whymath_backend.db.models.provenance import GenerationLog
from whymath_backend.db.models.review_timer_event import (
    ReviewTimerEvent as OrmReviewTimerEvent,
)
from whymath_backend.ops.hit_cu_metrics import HitCuReport, aggregate

__all__ = [
    "HARNESS_METRIC_NAMES",
    "KPI_NAMES",
    "STRUCTURALLY_UNMEASURED",
    "build_harness_metrics",
    "load_incidents_summary",
    "KpiValue",
    "WeeklyRecord",
    "build_record_from_report",
    "collect",
    "load_ledger",
    "append_record",
    "main",
]

_logger = logging.getLogger("whymath.ops.weekly_metrics_report")

_DEFAULT_METRICS_PATH = Path("metrics/weekly.json")

# EOS-51 §6이 실제로 동결한 "기술 KPI 6종" — 모듈 docstring "7지표 표기 정정" 참조.
KPI_NAMES: tuple[str, ...] = (
    "hit_seconds",
    "auto_gate_pass_rate",
    "rework_rate",
    "throughput_cu_per_hour",
    "unit_cost_krw",
    "failure_type_distribution",
)

# DB 연결 성공 여부와 무관하게 항상 미측정인 2종 — 이 저장소에 집계 대상 로그가 아직 없다
# (모듈 docstring 참조). 값이 바뀌면(로그가 신설되면) 여기서 빼고 실제 계산으로 옮긴다.
STRUCTURALLY_UNMEASURED: dict[str, str] = {
    "auto_gate_pass_rate": (
        "Deterministic Gate pass/fail 누적 로그 없음 — 집계 대상 테이블 미존재(2026-09-11 실측)"
    ),
    "rework_rate": (
        "Run 재생성 카운트 로그 없음 — EOS-55는 재현성 컬럼만 추가·재생성 카운트 로그는 "
        "좌석 미착지(2026-09-11 실측)"
    ),
}


@dataclass(frozen=True, slots=True)
class KpiValue:
    """KPI 1건의 판정 — `measured=False`면 `value`는 항상 `None`(0으로 위장 금지)."""

    measured: bool
    value: float | dict[str, int] | None
    unit: str
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "measured": self.measured,
            "value": self.value,
            "unit": self.unit,
            "reason": self.reason,
        }


# 하네스 지표 3종 (HARN-118 ③) — EOS-51 §6의 "기술 KPI 6종"과 **별개 블록**이다.
#
# 왜 `KPI_NAMES`에 합치지 않는가: 이 모듈의 docstring이 "문서가 실제로 동결한 6종만
# 집계하고 7번째를 지어내지 않는다"를 명시적 계약으로 걸고 있고(2026-09-11 "7지표"
# 표기 정정), 그 계약을 지키면서 사고 지표를 같은 원장에 실으려면 블록을 나누는 것이
# 유일한 길이다. 6종은 EOS 검증 설계가 정의한 *콘텐츠 제작* KPI이고, 이 3종은 *공정
# 자신*의 건강 지표다 — 섞으면 어느 쪽 분모로 읽어야 하는지 알 수 없게 된다.
HARNESS_METRIC_NAMES: tuple[str, ...] = (
    "incident_count",  # 대장에 등재된 사고 총건수
    "max_series_nth",  # 계열 최대 회차 — 같은 유형이 몇 번 뚫렸는가
    "rule_only_fix_ratio",  # 대책이 산문(rule)뿐인 사고의 비율
)


@dataclass(frozen=True, slots=True)
class WeeklyRecord:
    """주간 리포트 1행 — `metrics/weekly.json`(JSON 배열)의 원소 1개."""

    week_start: str  # ISO8601 — 집계 창 시작(포함)
    week_end: str  # ISO8601 — 집계 창 끝(미포함)
    generated_at: str  # ISO8601 — 이 행을 만든 시각
    kpis: dict[str, KpiValue]
    # 하네스 지표 3종 — 기본 빈 dict가 아니라 *항상 3키*다(아래 build_harness_metrics가
    # 미측정도 키를 채운다). 빈 dict로 두면 "안 쟀다"와 "못 쟀다"가 같은 모양이 된다.
    harness: dict[str, KpiValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "week_start": self.week_start,
            "week_end": self.week_end,
            "generated_at": self.generated_at,
            "kpis": {name: kpi.to_json() for name, kpi in self.kpis.items()},
            "harness": {name: kpi.to_json() for name, kpi in self.harness.items()},
        }


def load_incidents_summary(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    """`backlog.py incident report --json` 산출물 읽기 → (요약, 실패 사유).

    백엔드는 `scripts/harness`를 **임포트하지 않는다** — 하네스는 의존성 0 단독 실행
    설계이고 백엔드는 import-linter 계약 아래 있다. 그래서 집계 로직을 재구현하지 않고
    (이중 진실 원천 금지) 하네스가 낸 JSON을 파일로 건네받는다. 그 전달을 실제로 수행하는
    자리는 `weekly-metrics.yml`의 선행 스텝이며, 그 배선은 `tests/infra`가 동결한다
    (정본화 ≠ 집행).

    실패는 **사유를 돌려준다** — 예외 타입명을 포함한다(침묵 실패 금지). 사유가 있으면
    호출측이 `measured=False`로 낸다. 0으로 위장하지 않는다.
    """
    if path is None:
        return None, "사고 요약 미지정(--incidents-summary) — 하네스 지표는 이번 실행에서 미수집"
    if not path.exists():
        return None, f"사고 요약 파일 없음: {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"사고 요약 읽기 실패 — {type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, f"사고 요약이 객체가 아님 (받은 타입 {type(data).__name__})"
    return data, None


def build_harness_metrics(
    summary: dict[str, Any] | None, *, failure_reason: str | None = None
) -> dict[str, KpiValue]:
    """사고 요약 → 하네스 지표 3종. 순수 함수 — I/O 0.

    요약이 없거나 필요한 키가 비면 **그 지표만** 미측정이다. 하나가 빠졌다고 셋 다
    버리지 않고, 하나가 있다고 나머지를 0으로 채우지도 않는다.
    """
    units = {
        "incident_count": "count",
        "max_series_nth": "count",
        "rule_only_fix_ratio": "ratio",
    }
    if summary is None:
        reason = failure_reason or "사고 요약 미수집"
        return {
            name: KpiValue(measured=False, value=None, unit=units[name], reason=reason)
            for name in HARNESS_METRIC_NAMES
        }

    source_keys = {
        "incident_count": "total",
        "max_series_nth": "max_series_nth",
        "rule_only_fix_ratio": "rule_only_ratio",
    }
    metrics: dict[str, KpiValue] = {}
    for name in HARNESS_METRIC_NAMES:
        raw = summary.get(source_keys[name])
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            metrics[name] = KpiValue(
                measured=False,
                value=None,
                unit=units[name],
                reason=(
                    f"사고 요약에 '{source_keys[name]}' 키가 없거나 수치가 아님 "
                    f"(받은 값 {raw!r})"
                ),
            )
        else:
            metrics[name] = KpiValue(measured=True, value=float(raw), unit=units[name])
    return metrics


def build_record_from_report(
    report: HitCuReport | None,
    *,
    week_start: datetime,
    week_end: datetime,
    generated_at: datetime,
    krw_per_usd: float | None,
    db_failure_reason: str | None = None,
    harness: dict[str, KpiValue] | None = None,
) -> WeeklyRecord:
    """`HitCuReport`(또는 DB 실패 시 `None`) → `WeeklyRecord`. 순수 함수 — I/O 0.

    `report is None`이면(DB 연결 실패) 4종(HIT·처리량·단위비용·실패분포) 전부
    `db_failure_reason`으로 미측정 처리한다 — 나머지 2종은 원래도 항상 미측정이다.
    """
    kpis: dict[str, KpiValue] = {}

    if report is None:
        reason = db_failure_reason or "알 수 없는 DB 오류"
        kpis["hit_seconds"] = KpiValue(measured=False, value=None, unit="seconds", reason=reason)
        kpis["throughput_cu_per_hour"] = KpiValue(
            measured=False, value=None, unit="cu_per_hour", reason=reason
        )
        kpis["unit_cost_krw"] = KpiValue(
            measured=False, value=None, unit="krw_per_cu", reason=reason
        )
        kpis["failure_type_distribution"] = KpiValue(
            measured=False, value=None, unit="count_by_code", reason=reason
        )
    else:
        # HIT — 중앙값(초). CU 표본이 없으면 median=None(0초 산입 금지, hit_cu_metrics 규약).
        if report.cu_measured > 0 and report.hit_median_seconds is not None:
            kpis["hit_seconds"] = KpiValue(
                measured=True, value=report.hit_median_seconds, unit="seconds_median"
            )
        else:
            kpis["hit_seconds"] = KpiValue(
                measured=False,
                value=None,
                unit="seconds_median",
                reason=f"이번 주 계측 완료 CU 0건(cu_total={report.cu_total})",
            )

        # 처리량 — CU/h = measured CU 수 ÷ (HIT 합 시간). 분모 0이면 미산출.
        if report.cu_measured > 0 and report.hit_total_seconds > 0:
            kpis["throughput_cu_per_hour"] = KpiValue(
                measured=True,
                value=report.cu_measured / (report.hit_total_seconds / 3600),
                unit="cu_per_hour",
            )
        else:
            kpis["throughput_cu_per_hour"] = KpiValue(
                measured=False,
                value=None,
                unit="cu_per_hour",
                reason=f"이번 주 계측 완료 CU 0건(cu_total={report.cu_total})",
            )

        # 단위 비용 — KRW/CU. 환율 미지정이거나 비용 계측 CU가 0이면 미산출(하드코딩 금지).
        if krw_per_usd is None:
            kpis["unit_cost_krw"] = KpiValue(
                measured=False,
                value=None,
                unit="krw_per_cu",
                reason="환율 미지정(--krw-per-usd) — 하드코딩된 기본 환율은 두지 않는다",
            )
        elif report.cu_with_cost > 0 and report.cost_usd_total is not None:
            kpis["unit_cost_krw"] = KpiValue(
                measured=True,
                value=(report.cost_usd_total * krw_per_usd) / report.cu_with_cost,
                unit="krw_per_cu",
            )
        else:
            kpis["unit_cost_krw"] = KpiValue(
                measured=False,
                value=None,
                unit="krw_per_cu",
                reason="이번 주 비용 계측 완료 CU 0건",
            )

        # 실패 유형 분포 — F1~F8 전건 표기(0 포함, hit_cu_metrics가 이미 그렇게 낸다).
        if report.rejected_count > 0:
            kpis["failure_type_distribution"] = KpiValue(
                measured=True,
                value=dict(report.failure_code_counts),
                unit="count_by_code",
            )
        else:
            kpis["failure_type_distribution"] = KpiValue(
                measured=False,
                value=None,
                unit="count_by_code",
                reason="이번 주 반려(rejected) 판정 0건",
            )

    # 구조적으로 항상 미측정인 2종 — DB 성패와 무관.
    for name, reason in STRUCTURALLY_UNMEASURED.items():
        kpis[name] = KpiValue(measured=False, value=None, unit="rate", reason=reason)

    assert set(kpis) == set(KPI_NAMES), f"KPI 누락/초과: {set(kpis) ^ set(KPI_NAMES)}"

    return WeeklyRecord(
        week_start=week_start.isoformat(),
        week_end=week_end.isoformat(),
        generated_at=generated_at.isoformat(),
        kpis=kpis,
        # `harness`가 None이어도 빈 dict가 아니라 **미측정 3키**를 채운다 —
        # 키가 없으면 "안 쟀다"와 "못 쟀다"가 같은 모양이 되고, 그러면 원장을 읽는 쪽이
        # 미수집을 0으로 읽는다(CLAUDE.md: 측정 실패가 "0건 통과"로 위장되면 안 된다).
        harness=harness if harness is not None else build_harness_metrics(None),
    )


async def _fetch_report(
    session: AsyncSession, *, week_start: datetime, week_end: datetime
) -> HitCuReport:
    """창 `[week_start, week_end)` 안의 이벤트·생성로그를 읽어 `HitCuReport`로 집계."""
    event_rows = (
        (
            await session.execute(
                sa.select(OrmReviewTimerEvent).where(
                    OrmReviewTimerEvent.recorded_at >= week_start,
                    OrmReviewTimerEvent.recorded_at < week_end,
                )
            )
        )
        .scalars()
        .all()
    )
    events = [row.to_schema() for row in event_rows]

    genlog_orm_rows = (
        (
            await session.execute(
                sa.select(GenerationLog).where(
                    GenerationLog.generated_at >= week_start,
                    GenerationLog.generated_at < week_end,
                )
            )
        )
        .scalars()
        .all()
    )
    genlog_rows: list[dict[str, Any]] = [
        {
            "problem_id": str(row.problem_id) if row.problem_id is not None else None,
            "cost_usd": float(row.cost_usd) if row.cost_usd is not None else None,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
        }
        for row in genlog_orm_rows
    ]

    return aggregate(events, genlog_rows=genlog_rows)


async def collect(
    *,
    week_start: datetime,
    week_end: datetime,
    generated_at: datetime,
    krw_per_usd: float | None,
    database_url: str | None = None,
    harness: dict[str, KpiValue] | None = None,
) -> WeeklyRecord:
    """DB에 연결해 한 주간 리포트를 만든다. 연결·쿼리 실패는 예외를 삼키지 않고 타입명과
    함께 전체 4종을 미측정 처리한다(침묵 실패 금지 — CLAUDE.md)."""
    url = database_url or get_settings().database_url
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            report = await _fetch_report(session, week_start=week_start, week_end=week_end)
        return build_record_from_report(
            report,
            week_start=week_start,
            week_end=week_end,
            generated_at=generated_at,
            krw_per_usd=krw_per_usd,
            harness=harness,
        )
    except Exception as exc:  # noqa: BLE001 — 침묵 실패 금지(CLAUDE.md): 타입명을 반드시 로그.
        _logger.error(
            "weekly_metrics_report: DB 조회 실패 — %s (창 %s~%s)",
            type(exc).__name__,
            week_start.isoformat(),
            week_end.isoformat(),
        )
        return build_record_from_report(
            None,
            week_start=week_start,
            week_end=week_end,
            generated_at=generated_at,
            krw_per_usd=krw_per_usd,
            db_failure_reason=f"DB 연결/조회 실패 — {type(exc).__name__}",
            harness=harness,
        )
    finally:
        await engine.dispose()


def load_ledger(path: Path) -> list[dict[str, Any]]:
    """`metrics/weekly.json` 읽기 — 파일 없음은 빈 배열(첫 실행), 파싱 실패는 예외 전파
    (조용히 덮어쓰지 않는다 — 기존 이력 손실 방지)."""
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"{path}는 JSON 배열이어야 한다 (받은 타입: {type(data).__name__})")
    return data


def append_record(path: Path, record: WeeklyRecord) -> list[dict[str, Any]]:
    """기존 원장 + 신규 행 → 파일에 pretty-printed JSON 배열로 다시 쓴다. 반환 = 갱신된 배열."""
    ledger = load_ledger(path)
    ledger.append(record.to_json())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ledger


def _resolve_window(*, now: datetime) -> tuple[datetime, datetime]:
    """`[now - 7일, now)` — 직전 실행분과 이번 실행 사이의 달력 무관 슬라이딩 7일 창."""
    return now - timedelta(days=7), now


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.weekly_metrics_report",
        description=(
            "EOS-51 §6 기술 KPI 6종을 지난 7일 창으로 집계해 metrics/weekly.json에 "
            "append한다(OPS-56). 자동검증 1차 통과율·재작업률은 이 저장소에 집계 대상 "
            "로그가 아직 없어 구조적으로 항상 미측정이다."
        ),
    )
    parser.add_argument(
        "--metrics-path",
        type=Path,
        default=_DEFAULT_METRICS_PATH,
        help=f"원장 파일 경로 (기본 {_DEFAULT_METRICS_PATH})",
    )
    parser.add_argument(
        "--krw-per-usd",
        type=float,
        default=None,
        help="USD→KRW 환율(단위비용 KPI 산출에 필요) — 미지정 시 그 KPI만 미측정",
    )
    parser.add_argument(
        "--incidents-summary",
        type=Path,
        default=None,
        help=(
            "`backlog.py incident report --json` 산출물 경로 — 하네스 지표 3종의 입력 "
            "(미지정 시 그 3종만 미측정. 0으로 채우지 않는다)"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="집계만 하고 파일에 쓰지 않음(stdout에 출력)"
    )
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    week_start, week_end = _resolve_window(now=now)

    summary, summary_failure = load_incidents_summary(args.incidents_summary)
    if summary_failure is not None:
        _logger.warning("weekly_metrics_report: 하네스 지표 미수집 — %s", summary_failure)
    harness = build_harness_metrics(summary, failure_reason=summary_failure)

    record = asyncio.run(
        collect(
            week_start=week_start,
            week_end=week_end,
            generated_at=now,
            krw_per_usd=args.krw_per_usd,
            harness=harness,
        )
    )

    if args.dry_run:
        json.dump(record.to_json(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    append_record(args.metrics_path, record)
    json.dump(record.to_json(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
