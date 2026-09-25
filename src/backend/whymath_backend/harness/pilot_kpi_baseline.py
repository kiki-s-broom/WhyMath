"""파일럿 KPI 베이스라인 리포트 — 5개 핵심 KPI를 *하나의 구조화 산출물*로 조립(CLI).

배경 (왜 이 도구가 필요한가)
----------------------------
S3 파일럿(5~10명) 노출 직전, "무엇을 *지금* 잴 수 있고 무엇이 *아직* 못 재는지"를 한 장으로
내는 **KPI 베이스라인**이 필요하다(S3-04). 기존 `surrogate_baseline_report`가 WH-1 대리 지표
11종의 커버리지 맵을 낸다면, 본 모듈은 *파일럿 사업 판정*에 직접 쓰는 5개 KPI만 골라 조립한다:

  1. **학습성과(숙달 델타)** — `wh1_evaluation` ⑨ `mastery_gain_rate` **재사용**(신규 계산 0).
  2. **재사용/리텐션** — `LearningSession`(user·started_at) 기반 파일럿 리텐션 지표 **신설**.
     **무엇을 재는가(EOS-131 계약 1줄)**: 세션은 서버 30분 유휴 규칙이 만드는 *학습 활동 묶음*이라
     (앱을 열기만 하면 세션이 생기지 않는다) 이 재방문율은 **학습 재방문율** — "다른 날 다시 와서
     학습 활동(추천 조회·시도·코치 턴)을 했는가"이지 앱 실행 재방문율이 아니다.
  3. **정서안전(톤 위반)** — 현재 아키텍처상 **NO_DATA 정직 표기**. `l4.tone_filter.filter_tone`
     은 존재하나 라이브 경로 미배선(결정론 coach·LLM 생성 0)이라 위반할 발화 자체가 없다.
  4. **세션비용(P&L)** — 코호트 LLM 비용은 `ops.cost_report` **재사용**(부분). per-session
     비용·P&L 구간 판정은 **NO_DATA 정직 표기**(결정론 coach가 Dialogue 비용 컬럼 미적재).
  5. **입력 verify 커버리지** — `wh1_shadow_harvest.summarize`의 3-state verdict 분포 **재사용**.
     결정 구간 = (correct+incorrect)/total.

정직성 원칙 (CLAUDE.md "모르면 모른다"·"측정 없는 판정 금지"·surrogate_baseline_report 미러)
-------------------------------------------------------------------------------------------
**없는 것을 날조하지 않는다.** 각 KPI는 *값(MEASURED)* 또는 *NO_DATA(사유 문자열)*를 반드시
가진다 — 빈 값·가짜 0으로 위장하지 않는다(빈 통과/미달 위장 금지). KPI 4는 코호트 비용만 재고
per-session·P&L은 NO_DATA인 *부분(PARTIAL)* 상태를 정직하게 낸다. 미측정 KPI에는 "무엇을
만들면 잴 수 있는지"(후속)를 note에 밝힌다.

설계 경계 (계산/렌더 분리·hermetic 테스트)
------------------------------------------
- **순수 조립 코어**(`compute_retention`·`compute_verify_coverage`·`assemble_pilot_baseline`·
  `render_pilot_baseline`)는 I/O 없는 순수 함수다 — 이미 계산된 입력(Metric·CostReport·분포
  요약·세션 행)만 받아 조립·렌더한다. 실 DB/Langfuse 없이 픽스처로 전수 검증 가능.
- **얇은 glue**(`_run`·`main`)만 DB 세션·Langfuse 조회·shadow 원장 로드를 수행한다(pragma
  no cover — 라이브 통합 검증 소관).

--mode 스코프 (정직 표기)
-------------------------
`--mode`는 `compute_wh1_surrogate_metrics(mode=)`로 패스스루된다 — 그 안의 *attempt_event
기반 지표*(① verify·⑤ 도움 감소·⑧ 도달 깊이)만 mode-scoped다. **본 리포트의 5 파일럿 KPI는
모두 세션 mode 컬럼 부재로 mode 무관 집계**다(⑨ 숙달·리텐션·톤·비용·shadow 커버리지 어느
것도 ①⑤⑧에 속하지 않음). 완전한 mode별 분해(세션 mode 컬럼 마이그레이션)는 범위 밖(후속).

계층 메모 (CLAUDE.md 7계층): 본 모듈은 계약 밖(harness/ops 무제약)이다. L1(활동
`LearningSession`)·harness(`wh1_evaluation`·`wh1_shadow_harvest`)·ops(`cost_report`)를
*조회·조립만* 하는 리포팅 진입점이며, 새 계산·새 지표를 만들지 않는다(⑨·비용·커버리지는
기존 자산 재사용, 리텐션만 신설). L4(`tone_filter`)는 import하지 않고 note에서 경로만 참조한다.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import LearningSession
from whymath_backend.db.session import get_sessionmaker
from whymath_backend.harness.wh1_evaluation import (
    Metric,
    MetricStatus,
    compute_wh1_surrogate_metrics,
)
from whymath_backend.harness.wh1_shadow_harvest import (
    Wh1ShadowDistributionSummary,
    load_ledger,
    summarize,
)
from whymath_backend.ops.cost_report import CostReport, aggregate_l3_events, fetch_l3_events

__all__ = [
    "CohortCostSummary",
    "KpiStatus",
    "PilotKpiBaseline",
    "RetentionReport",
    "VerifyCoverageReport",
    "assemble_pilot_baseline",
    "compute_retention",
    "compute_verify_coverage",
    "load_retention_sessions",
    "main",
    "render_pilot_baseline",
]


# 리텐션율이 *기술통계*(추론 아님)임을 캐비엇으로 다는 최소 사용자 수. 파일럿은 5~10명이라
# 이보다 적으면 값은 실측이되 표본이 작아 추론 근거로 쓰지 말라는 note를 단다(가짜 0/NO_DATA
# 위장과 구분 — 값은 진짜다). 사용자 0명일 때만 NO_DATA다(genuine 부재).
_MIN_RETENTION_USERS_STABLE = 3


class KpiStatus(str, Enum):
    """파일럿 KPI 1종의 *롤업* 상태 — 리프 Metric 상태(MetricStatus)와 구분되는 KPI 레벨 판정.

    KPI 하나가 여러 리프 지표로 구성될 수 있어(예: KPI4=코호트비용+per-session+P&L) 리프
    상태만으로는 KPI 전체 상태를 못 낸다. 이 enum이 그 롤업이다.
    """

    MEASURED = "measured"
    """🟢 실측 — 이 KPI의 핵심 값이 계측됐다."""

    PARTIAL = "partial"
    """🟠 부분 — 일부 하위 지표만 계측되고 나머지는 NO_DATA(예: 코호트 비용은 있으나 P&L 없음)."""

    NO_DATA = "no_data"
    """🟡 데이터 없음 — 핵심 값이 아직 계측 불가(사유는 note). 가짜 0으로 위장하지 않는다."""


# ──────────────────────────────────────────────────────────────────────────
# KPI 2: 재사용/리텐션 (신설·순수 계산)
# ──────────────────────────────────────────────────────────────────────────


class RetentionReport(BaseModel):
    """KPI2 재사용/리텐션 — 파일럿 세션 기반 리텐션 지표 묶음(각 리프는 Metric·날조 0)."""

    model_config = ConfigDict(extra="forbid")

    returning_user_rate: Metric = Field(
        description=(
            "복귀 사용자 비율 — 서로 다른 *날*에 2회 이상 세션을 연 사용자 / 전체 사용자. "
            "핵심 리텐션(다른 날 다시 옴). 사용자 0명이면 NO_DATA. 세션=서버 유휴 규칙의 학습 "
            "활동 묶음이므로 *학습* 재방문율이다(앱만 열고 학습 활동이 없으면 세지 않는다)."
        )
    )
    sessions_per_user: Metric = Field(
        description=(
            "사용자당 세션 수 — 전체 유효 세션 / 전체 사용자(재사용 강도). 사용자 0명이면 NO_DATA."
        )
    )
    active_days_per_user: Metric = Field(
        description="사용자당 활동일 수(평균) — distinct 활동 날짜 평균. 사용자 0명이면 NO_DATA."
    )
    return_gap_days_median: Metric = Field(
        description=(
            "복귀 간격 중앙값(일) — 복귀 사용자들의 연속 활동일 간격 중앙값. 복귀 사용자 0명이면 "
            "NO_DATA(간격 산출 불가·genuine 부재)."
        )
    )

    distinct_users: int = Field(
        default=0, description="유효 세션을 연 고유 사용자 수(user·started_at 둘 다 존재)."
    )
    returning_users: int = Field(
        default=0, description="서로 다른 날 2회 이상 세션을 연 사용자 수."
    )
    total_valid_sessions: int = Field(
        default=0, description="집계 대상 유효 세션 수(user·started_at NOT NULL)."
    )
    excluded_rows: int = Field(
        default=0,
        description="user_id·started_at 결손으로 리텐션 귀속 불가라 제외된 세션 행 수(정직 회계).",
    )


def _median(values: list[float]) -> float:
    """정렬 후 중앙값(순수) — 호출부가 비어 있지 않음을 보장한다(빈 리스트 미호출)."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def compute_retention(
    sessions: Sequence[tuple[uuid.UUID | None, datetime | None]],
) -> RetentionReport:
    """(user_id, started_at) 세션 목록 → 파일럿 리텐션 지표(순수·결정론·날조 0).

    입력은 집계 스코프(user·시간창 필터 후) 안의 `LearningSession` 행 (user_id, started_at)
    시퀀스다(호출부가 조회). user_id 또는 started_at이 결손인 행은 리텐션을 *귀속할 수 없어*
    제외하고 `excluded_rows`로 정직하게 센다(조용한 누락 금지).

    지표(각 Metric·값 또는 NO_DATA):
      - `returning_user_rate` = 서로 다른 *날*에 2회 이상 세션을 연 사용자 / 전체 사용자.
        핵심 리텐션(다른 날 다시 옴). 사용자 0명이면 NO_DATA.
      - `sessions_per_user` = 유효 세션 / 전체 사용자(재사용 강도).
      - `active_days_per_user` = 사용자당 distinct 활동 날짜 평균.
      - `return_gap_days_median` = 복귀 사용자들의 연속 활동일 간격 중앙값. 복귀 사용자 0명이면
        NO_DATA(간격 산출 불가·genuine 부재).

    표본 정직성(중요): 사용자 0명일 때만 NO_DATA다(genuine 부재). 사용자 1명 이상이면 값은
    *실측*이되, `_MIN_RETENTION_USERS_STABLE` 미만이면 "기술통계(추론 아님)" 캐비엇을 note에
    단다 — 파일럿은 5~10명이라 값을 숨기지 않되(가짜 0/NO_DATA 위장 아님) 작은 표본임을 밝힌다.

    시간대 메모: 활동일은 `started_at.date()`로 구한다(TIMESTAMPTZ의 저장 tz 기준). 파일럿
    베이스라인엔 충분하나 tz 경계 세밀 분해는 후속(세션별·현지시각 분해).
    """
    valid: list[tuple[uuid.UUID, datetime]] = [
        (user, started) for user, started in sessions if user is not None and started is not None
    ]
    excluded = len(sessions) - len(valid)
    total_valid = len(valid)

    # user별 distinct 활동 날짜 집합(복귀·활동일 판정의 단일 원천).
    active_days: dict[uuid.UUID, set[date]] = {}
    for user, started in valid:
        active_days.setdefault(user, set()).add(started.date())
    distinct_users = len(active_days)

    if distinct_users == 0:
        no_users = Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                "유효 세션(user·started_at NOT NULL) 0건 — 파일럿 사용자가 세션을 열면 리텐션 "
                "계측(가짜 0 아님)."
            ),
        )
        return RetentionReport(
            returning_user_rate=no_users,
            sessions_per_user=no_users,
            active_days_per_user=no_users,
            return_gap_days_median=no_users,
            distinct_users=0,
            returning_users=0,
            total_valid_sessions=total_valid,
            excluded_rows=excluded,
        )

    returning_users = sum(1 for days in active_days.values() if len(days) >= 2)
    returning_rate = returning_users / distinct_users
    sessions_per_user = total_valid / distinct_users
    active_days_per_user = sum(len(days) for days in active_days.values()) / distinct_users

    # 복귀 사용자들의 연속 활동일 간격(일)을 전부 모아 중앙값(복귀가 없으면 빈 리스트).
    gaps: list[float] = []
    for days in active_days.values():
        ordered_days = sorted(days)
        gaps.extend(
            float((ordered_days[i + 1] - ordered_days[i]).days)
            for i in range(len(ordered_days) - 1)
        )

    # 작은 표본 캐비엇(값은 실측·추론 아님) — genuine 부재(0명)와 구분된다.
    small = (
        f" 파일럿 표본 {distinct_users}명(<{_MIN_RETENTION_USERS_STABLE}) — 기술통계(추론 아님)."
        if distinct_users < _MIN_RETENTION_USERS_STABLE
        else ""
    )

    returning_metric = Metric(
        value=returning_rate,
        status=MetricStatus.MEASURED,
        note=(
            f"복귀(다른 날 2회+) 사용자 {returning_users}/{distinct_users}명={returning_rate:.4f}."
            f"{small}"
        ),
    )
    sessions_metric = Metric(
        value=sessions_per_user,
        status=MetricStatus.MEASURED,
        note=(
            f"유효 세션 {total_valid}건 / 사용자 {distinct_users}명="
            f"{sessions_per_user:.4f}(재사용 강도).{small}"
        ),
    )
    active_days_metric = Metric(
        value=active_days_per_user,
        status=MetricStatus.MEASURED,
        note=(
            f"사용자당 distinct 활동일 평균 {active_days_per_user:.4f}"
            f"(started_at.date 기준).{small}"
        ),
    )
    if gaps:
        gap_median = _median(gaps)
        gap_metric = Metric(
            value=gap_median,
            status=MetricStatus.MEASURED,
            note=(
                f"복귀 사용자 {returning_users}명의 연속 활동일 간격 중앙값 {gap_median:.4f}일"
                f"(간격 표본 {len(gaps)}개).{small}"
            ),
        )
    else:
        gap_metric = Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                "복귀 사용자 0명 — 연속 활동일 간격 산출 불가(genuine 부재·가짜 0 아님). 다른 날 "
                "재방문이 쌓이면 복귀 간격 계측."
            ),
        )

    return RetentionReport(
        returning_user_rate=returning_metric,
        sessions_per_user=sessions_metric,
        active_days_per_user=active_days_metric,
        return_gap_days_median=gap_metric,
        distinct_users=distinct_users,
        returning_users=returning_users,
        total_valid_sessions=total_valid,
        excluded_rows=excluded,
    )


# ──────────────────────────────────────────────────────────────────────────
# KPI 4: 세션비용(P&L) — 코호트 비용 재사용(부분) + per-session·P&L NO_DATA
# ──────────────────────────────────────────────────────────────────────────


class CohortCostSummary(BaseModel):
    """KPI4 세션비용의 *코호트* 부분 — `ops.cost_report` 집계 재사용(부분 정직)."""

    model_config = ConfigDict(extra="forbid")

    total_cost_krw: Metric = Field(
        description=(
            "코호트 LLM 총비용(원) — l3_routing 실측 cost_krw 합. 이벤트/실측 0이면 NO_DATA."
        )
    )
    local_ratio: Metric = Field(
        description="로컬 LLM 비중 — local/(local+cloud)(목표 0.80). 분류 표본 0이면 NO_DATA."
    )
    event_count: int = Field(default=0, description="집계에 들어온 l3_routing 이벤트 총수.")
    cost_sample: int = Field(default=0, description="실측 cost_krw가 있던 이벤트 수(None 제외).")


def _cohort_cost_summary(cost_report: CostReport | None) -> CohortCostSummary:
    """`CostReport`(또는 None) → 코호트 비용 요약(순수·날조 0).

    `cost_report`가 None(Langfuse 미설정·미조회)이거나 이벤트 0건이면 total_cost·local_ratio를
    NO_DATA로 둔다(가짜 0 회피). 실측 cost_krw 표본이 0이면(캐시·비동기·미계측만) total_cost도
    NO_DATA다 — `aggregate_l3_events`가 이미 None으로 분리해 둔 것을 그대로 옮긴다(재계산 0).
    """
    if cost_report is None or cost_report.event_count == 0:
        reason = (
            "Langfuse 미설정 또는 l3_routing 이벤트 0건 — 코호트 LLM 비용 산출 불가(가짜 0 아님). "
            "라이브 트래픽이 쌓이면 cost_report로 집계."
        )
        no_data = Metric(value=None, status=MetricStatus.NO_DATA, note=reason)
        return CohortCostSummary(
            total_cost_krw=no_data,
            local_ratio=no_data,
            event_count=0 if cost_report is None else cost_report.event_count,
            cost_sample=0,
        )

    cost_dist = cost_report.cost_krw
    if cost_dist.total is None or cost_dist.count == 0:
        total_metric = Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                f"l3_routing 이벤트 {cost_report.event_count}건이나 실측 cost_krw 표본 0 — "
                "캐시·비동기·미계측만 있었을 수 있음(가짜 0 아님·대표 트래픽 필요)."
            ),
        )
    else:
        total_metric = Metric(
            value=float(cost_dist.total),
            status=MetricStatus.MEASURED,
            note=(
                f"코호트 LLM 총비용 {cost_dist.total:.4f}원(실측 cost_krw {cost_dist.count}건 합·"
                f"p50 {cost_dist.p50}). ops.cost_report 재사용(l3_routing 집계)."
            ),
        )

    if cost_report.local_ratio is None:
        local_metric = Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note="cost_tier 분류 이벤트 0건 — 로컬:클라우드 비율 산출 불가(가짜 0 아님).",
        )
    else:
        local_metric = Metric(
            value=cost_report.local_ratio,
            status=MetricStatus.MEASURED,
            note=(
                f"로컬 비중 {cost_report.local_ratio:.4f}(로컬 {cost_report.local_count}/클라우드 "
                f"{cost_report.cloud_count}·목표 0.80)."
            ),
        )

    return CohortCostSummary(
        total_cost_krw=total_metric,
        local_ratio=local_metric,
        event_count=cost_report.event_count,
        cost_sample=cost_dist.count,
    )


def _per_session_cost_no_data(sample_dialogues_with_tokens: int) -> Metric:
    """KPI4 per-session 비용 — 결정론 coach가 Dialogue 비용 컬럼 미적재라 NO_DATA(증거 기반).

    `sample_dialogues_with_tokens`(④ 턴당 토큰이 센 total_tokens NOT NULL Dialogue 수)를 증거로
    싣는다 — 0이면 "비용 컬럼 전무"가 실측으로 확인된다(추론 아님). per-session 적재(Dialogue
    total_tokens/estimated_cost_usd) 로직 신설은 범위 밖(후속).
    """
    return Metric(
        value=None,
        status=MetricStatus.NO_DATA,
        note=(
            f"per-session 비용 미계측 — total_tokens 적재된 Dialogue "
            f"{sample_dialogues_with_tokens}건(결정론 coach가 Dialogue.total_tokens/"
            "estimated_cost_usd 미적재). per-session 비용 "
            "적재 로직 신설은 범위 밖(후속). 코호트 비용은 위 total_cost_krw 참조."
        ),
    )


def _pnl_no_data() -> Metric:
    """KPI4 P&L 구간 판정 — per-session 비용·수익(구독) 모델 부재로 NO_DATA(고정)."""
    return Metric(
        value=None,
        status=MetricStatus.NO_DATA,
        note=(
            "P&L 구간 판정 미계측 — per-session 비용(NO_DATA)·수익(구독) 모델이 있어야 손익 구간을 "
            "낸다. P&L 구간 로직 신설은 범위 밖(후속)."
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# KPI 5: 입력 verify 커버리지 (wh1_shadow_harvest 3-state 분포 재사용)
# ──────────────────────────────────────────────────────────────────────────


class VerifyCoverageReport(BaseModel):
    """KPI5 입력 verify 커버리지 — shadow verdict 3-state 분포의 *결정 구간* 비율(재사용)."""

    model_config = ConfigDict(extra="forbid")

    coverage: Metric = Field(
        description=(
            "결정 구간 비율 = (correct+incorrect)/total — verify가 correct/incorrect로 *판정*한 "
            "관측 비율(unverifiable·none 제외). 관측 0건·원장 미지정이면 NO_DATA."
        )
    )
    total_observations: int = Field(
        default=0, description="집계 대상 shadow 관측 총건수(중복 제거 후)."
    )
    verdict_counts: dict[str, int] = Field(
        default_factory=dict,
        description="verdict 분포 — correct/incorrect/unverifiable/none(verify 미호출) 각 건수.",
    )


def compute_verify_coverage(
    summary: Wh1ShadowDistributionSummary | None,
    *,
    ledger_provided: bool,
) -> VerifyCoverageReport:
    """shadow verdict 분포 요약(또는 None) → 입력 verify 커버리지(순수·날조 0).

    `wh1_shadow_harvest.summarize`가 낸 3-state verdict 분포를 재사용한다. 결정 구간 =
    (correct+incorrect)/total — verify가 실제로 correct/incorrect로 *판정*한 관측 비율이다
    (unverifiable·none[verify 미호출]은 결정 구간이 아니다). ① surrogate binary 검산은 커버리지가
    아니므로 쓰지 않는다(3-state 원장만).

    - `summary is None` + `ledger_provided=False` → 원장 미지정 NO_DATA.
    - `summary is None` + `ledger_provided=True` → 원장 로드 결과 없음 NO_DATA(부재/부식).
    - `total == 0` → 관측 0건 NO_DATA(가짜 0 아님).
    - 그 외 → MEASURED(결정 구간 비율).

    S3-02 스코프 메모: S3-02가 등호 방정식을 결정 구간(correct/incorrect)으로 끌어온 건 *신규
    shadow 관측*에만 반영된다(과거 원장은 불변) — 원장에 신규 관측이 쌓일수록 커버리지가
    올라가는 폐루프다(두 주제 연결·note 표기).
    """
    if summary is None:
        note = (
            "shadow 원장 미지정(--shadow-ledger 없음) — 입력 verify 커버리지 산출 불가"
            "(가짜 0 아님). wh1_shadow_harvest 원장을 지정하면 결정 구간 비율 계측."
            if not ledger_provided
            else "shadow 원장에 관측 0건(부재/부식) — 관측이 쌓이면 결정 구간 계측(가짜 0 아님)."
        )
        return VerifyCoverageReport(
            coverage=Metric(value=None, status=MetricStatus.NO_DATA, note=note),
            total_observations=0,
            verdict_counts={},
        )

    total = summary.total
    counts = dict(summary.verdict_counts)
    if total == 0:
        return VerifyCoverageReport(
            coverage=Metric(
                value=None,
                status=MetricStatus.NO_DATA,
                note="shadow 관측 0건 — coach 턴(shadow ON)이 쌓이면 결정 구간 계측(가짜 0 아님).",
            ),
            total_observations=0,
            verdict_counts=counts,
        )

    decided = counts.get("correct", 0) + counts.get("incorrect", 0)
    coverage = decided / total
    return VerifyCoverageReport(
        coverage=Metric(
            value=coverage,
            status=MetricStatus.MEASURED,
            note=(
                f"결정 구간 (correct+incorrect)/total = {decided}/{total}={coverage:.4f}"
                f"(unverifiable {counts.get('unverifiable', 0)}·none[verify 미호출] "
                f"{counts.get('none', 0)} 제외). S3-02 등호 방정식 결정 구간 편입은 *신규 shadow "
                "관측*에만 반영(과거 원장 불변)·원장 축적 폐루프."
            ),
        ),
        total_observations=total,
        verdict_counts=counts,
    )


# ──────────────────────────────────────────────────────────────────────────
# KPI 3: 정서안전(톤 위반) — 라이브 경로 미배선이라 NO_DATA(고정·측정 조건 명시)
# ──────────────────────────────────────────────────────────────────────────


def _tone_safety_no_data() -> Metric:
    """KPI3 정서안전(톤 위반율) — 현재 아키텍처상 NO_DATA(고정·측정 가능 조건 명시).

    `l4.tone_filter.filter_tone`(금지 6패턴 치환)은 존재하나 *라이브 경로 미배선*이다: coach는
    결정론 `decide()`로 응답하고 LLM 생성이 0이라 톤 필터를 타지 않으며, 위반 이벤트도 적재되지
    않는다. 즉 현재는 *위반할 LLM 발화 자체가 없다*. 목표(위반 0)와 함께 NO_DATA로 정직 표기하되,
    측정 가능 조건을 note에 명시한다(톤필터 배선·EventType 신설은 별도 슬라이스·범위 밖).
    """
    return Metric(
        value=None,
        status=MetricStatus.NO_DATA,
        note=(
            "정서안전 톤 위반 미계측(목표: 위반 0) — l4.tone_filter.filter_tone은 존재하나 라이브 "
            "경로 미배선(결정론 coach·LLM 발화 0·위반 이벤트 미적재)이라 위반할 발화 자체가 없음. "
            "측정 가능 조건 = S1-11 flip(LLM 발화 라이브) + 톤필터 배선 + 위반 이벤트 적재(별도 "
            "슬라이스·범위 밖)."
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# 조립·렌더 (순수)
# ──────────────────────────────────────────────────────────────────────────


class PilotKpiBaseline(BaseModel):
    """파일럿 5 KPI 베이스라인 — 하나의 구조화 산출물(각 KPI는 값 또는 NO_DATA·날조 0)."""

    model_config = ConfigDict(extra="forbid")

    # KPI1 학습성과(숙달 델타) — wh1_evaluation ⑨ 재사용.
    mastery_gain: Metric = Field(
        description="KPI1 학습성과 — ⑨ BKT 숙달 증가율(첫→마지막 mastery 차 평균·재사용)."
    )
    sample_mastery_groups: int = Field(
        default=0, description="⑨ 집계 대상 자격 (user,concept) 그룹 수."
    )

    # KPI2 재사용/리텐션 — 신설.
    retention: RetentionReport = Field(description="KPI2 재사용/리텐션 — 파일럿 세션 기반(신설).")

    # KPI3 정서안전(톤 위반) — NO_DATA.
    tone_safety: Metric = Field(
        description="KPI3 정서안전(톤 위반) — 라이브 미배선이라 NO_DATA(목표 위반 0)."
    )

    # KPI4 세션비용(P&L) — 코호트 재사용(부분).
    cohort_cost: CohortCostSummary = Field(
        description="KPI4 세션비용 — 코호트 LLM 비용(ops.cost_report 재사용)."
    )
    per_session_cost: Metric = Field(
        description="KPI4 per-session 비용 — Dialogue 비용 컬럼 미적재라 NO_DATA."
    )
    pnl: Metric = Field(
        description="KPI4 P&L 구간 판정 — per-session 비용·수익 모델 부재로 NO_DATA."
    )

    # KPI5 입력 verify 커버리지 — shadow 분포 재사용.
    verify_coverage: VerifyCoverageReport = Field(
        description="KPI5 입력 verify 커버리지 — shadow 3-state 결정 구간 비율(재사용)."
    )

    # ── 범위·메타 ──
    user_scoped: bool = Field(
        default=False, description="True면 특정 user 본인 집계, False면 코호트 전체."
    )
    window_start: datetime | None = Field(
        default=None, description="집계 시간창 시작(생략 시 None=무한 과거)."
    )
    window_end: datetime | None = Field(
        default=None, description="집계 시간창 끝(생략 시 None=무한 미래)."
    )
    mode_filter: str | None = Field(
        default=None,
        description=(
            "--mode 패스스루 값 — compute_wh1_surrogate_metrics의 ①⑤⑧에만 반영된다. **본 5 KPI는 "
            "모두 세션 mode 컬럼 부재로 mode 무관 집계**(정직 표기)."
        ),
    )

    def kpi_coverage(self) -> dict[str, KpiStatus]:
        """5 KPI의 *롤업* 상태(순수·결정론) — 리프 Metric 상태에서 KPI 레벨 판정을 낸다.

        - KPI1 학습성과 = ⑨ mastery 리프 상태 그대로(MEASURED/NO_DATA).
        - KPI2 리텐션 = 복귀율(핵심)이 MEASURED면 MEASURED, 아니면 NO_DATA.
        - KPI3 톤안전 = 항상 NO_DATA(라이브 미배선).
        - KPI4 세션비용 = 코호트 비용 MEASURED면 PARTIAL(per-session·P&L은 NO_DATA), 아니면 NO_DATA.
        - KPI5 verify 커버리지 = coverage 리프 상태 그대로.
        """

        def leaf(metric: Metric) -> KpiStatus:
            return (
                KpiStatus.MEASURED if metric.status is MetricStatus.MEASURED else KpiStatus.NO_DATA
            )

        if self.cohort_cost.total_cost_krw.status is MetricStatus.MEASURED:
            cost_status = KpiStatus.PARTIAL  # 코호트만 실측·per-session·P&L은 NO_DATA
        else:
            cost_status = KpiStatus.NO_DATA
        return {
            "KPI1 학습성과(숙달 델타)": leaf(self.mastery_gain),
            "KPI2 재사용/리텐션": leaf(self.retention.returning_user_rate),
            "KPI3 정서안전(톤 위반)": leaf(self.tone_safety),
            "KPI4 세션비용(P&L)": cost_status,
            "KPI5 입력 verify 커버리지": leaf(self.verify_coverage.coverage),
        }


def assemble_pilot_baseline(
    *,
    mastery_gain: Metric,
    sample_mastery_groups: int,
    retention: RetentionReport,
    cost_report: CostReport | None,
    sample_dialogues_with_tokens: int,
    verify_summary: Wh1ShadowDistributionSummary | None,
    verify_ledger_provided: bool,
    user_scoped: bool,
    window_start: datetime | None,
    window_end: datetime | None,
    mode_filter: str | None,
) -> PilotKpiBaseline:
    """이미 계산된 5 KPI 입력을 하나의 베이스라인으로 조립(순수·I/O 없음·날조 0).

    호출부(glue)가 ⑨ mastery(SurrogateMetrics에서 추출)·리텐션(compute_retention)·코호트
    비용(CostReport)·shadow 분포(summarize)를 미리 계산해 넘기면, 여기서 톤(고정 NO_DATA)·
    코호트 비용 요약·per-session/P&L(고정 NO_DATA)·verify 커버리지를 조립한다.
    """
    return PilotKpiBaseline(
        mastery_gain=mastery_gain,
        sample_mastery_groups=sample_mastery_groups,
        retention=retention,
        tone_safety=_tone_safety_no_data(),
        cohort_cost=_cohort_cost_summary(cost_report),
        per_session_cost=_per_session_cost_no_data(sample_dialogues_with_tokens),
        pnl=_pnl_no_data(),
        verify_coverage=compute_verify_coverage(
            verify_summary, ledger_provided=verify_ledger_provided
        ),
        user_scoped=user_scoped,
        window_start=window_start,
        window_end=window_end,
        mode_filter=mode_filter,
    )


# 리프 Metric 상태 → 아이콘(surrogate_baseline_report 미러).
_METRIC_ICON: dict[MetricStatus, str] = {
    MetricStatus.MEASURED: "🟢",
    MetricStatus.NO_DATA: "🟡",
    MetricStatus.NOT_INSTRUMENTED: "🔴",
    MetricStatus.REQUIRES_DATA: "🔴",
    MetricStatus.REQUIRES_TOOL: "🔴",
}

# KPI 롤업 상태 → 아이콘.
_KPI_ICON: dict[KpiStatus, str] = {
    KpiStatus.MEASURED: "🟢",
    KpiStatus.PARTIAL: "🟠",
    KpiStatus.NO_DATA: "🟡",
}


def _fmt_value(value: float | None) -> str:
    """지표 value 렌더 — None(NO_DATA·표본 부족)은 값 대신 '—'(가짜 0 금지)."""
    return "—" if value is None else f"{value:.4f}"


def _metric_line(label: str, metric: Metric) -> list[str]:
    """리프 Metric 1종을 2줄로(아이콘·상태·값 + 사유) — 렌더 공통."""
    icon = _METRIC_ICON.get(metric.status, "🔴")
    return [
        f"- {icon} {label}: 상태 {metric.status.value} · 값 {_fmt_value(metric.value)}",
        f"  - {metric.note}",
    ]


def render_pilot_baseline(baseline: PilotKpiBaseline) -> str:
    """파일럿 5 KPI 베이스라인을 사람이 읽을 마크다운으로 렌더(순수·DB 무관).

    헤더에 집계 범위·mode 스코프·KPI 커버리지 롤업(MEASURED/PARTIAL/NO_DATA)을, 이어 KPI별로
    리프 지표(값 또는 '—' + 사유)를, 끝에 후속(범위 밖) note를 낸다. "가짜 0 금지" — NO_DATA는
    값 대신 사유를 옮긴다. 입력 `PilotKpiBaseline` 외 어떤 계산도 하지 않는다(렌더 전용).
    """
    scope = "본인(user)" if baseline.user_scoped else "코호트 전체(파일럿)"
    win_start = baseline.window_start.isoformat() if baseline.window_start else "무한 과거"
    win_end = baseline.window_end.isoformat() if baseline.window_end else "무한 미래"
    coverage = baseline.kpi_coverage()
    measured = sum(1 for s in coverage.values() if s is KpiStatus.MEASURED)
    partial = sum(1 for s in coverage.values() if s is KpiStatus.PARTIAL)
    no_data = sum(1 for s in coverage.values() if s is KpiStatus.NO_DATA)
    total = len(coverage)

    lines: list[str] = [
        "# 파일럿 KPI 베이스라인 (5 KPI 커버리지 맵)",
        "",
        f"- 집계 범위: {scope} · 시간창 {win_start} ~ {win_end}",
        (
            f"- mode 스코프: {baseline.mode_filter or '전체(mode 무관)'} — 본 5 KPI는 모두 "
            "세션 mode 컬럼 부재로 mode 무관 집계(①⑤⑧만 mode-scoped·5 KPI 미포함)"
        ),
        f"- KPI 커버리지: MEASURED {measured} · PARTIAL {partial} · NO_DATA {no_data} / {total}",
        "  (가짜 0 금지 — 미측정은 값 대신 사유를 표기)",
        "",
        "## KPI 커버리지 롤업",
    ]
    for name, status in coverage.items():
        lines.append(f"- {_KPI_ICON[status]} {name}: {status.value}")
    lines.append("")

    # KPI1 학습성과
    lines.append("## KPI1 학습성과 — 숙달 델타(⑨ 재사용)")
    lines.extend(_metric_line("BKT 숙달 증가율", baseline.mastery_gain))
    lines.append(f"  - 표본: 자격 (user,concept) 그룹 {baseline.sample_mastery_groups}개")
    lines.append("")

    # KPI2 리텐션
    r = baseline.retention
    lines.append("## KPI2 재사용/리텐션 (신설)")
    lines.extend(_metric_line("복귀 사용자 비율", r.returning_user_rate))
    lines.extend(_metric_line("사용자당 세션 수", r.sessions_per_user))
    lines.extend(_metric_line("사용자당 활동일 수", r.active_days_per_user))
    lines.extend(_metric_line("복귀 간격 중앙값(일)", r.return_gap_days_median))
    lines.append(
        f"  - 표본: 사용자 {r.distinct_users}명 · 복귀 {r.returning_users}명 · 유효 세션 "
        f"{r.total_valid_sessions}건 · 제외(귀속 불가) {r.excluded_rows}건"
    )
    lines.append("")

    # KPI3 톤안전
    lines.append("## KPI3 정서안전 — 톤 위반(NO_DATA·목표 위반 0)")
    lines.extend(_metric_line("톤 위반율", baseline.tone_safety))
    lines.append("")

    # KPI4 세션비용
    c = baseline.cohort_cost
    lines.append("## KPI4 세션비용 — P&L (부분: 코호트 재사용·per-session/P&L NO_DATA)")
    lines.extend(_metric_line("코호트 LLM 총비용(원)", c.total_cost_krw))
    lines.extend(_metric_line("로컬 LLM 비중", c.local_ratio))
    lines.append(f"  - 표본: l3_routing 이벤트 {c.event_count}건 · 실측 cost_krw {c.cost_sample}건")
    lines.extend(_metric_line("per-session 비용", baseline.per_session_cost))
    lines.extend(_metric_line("P&L 구간 판정", baseline.pnl))
    lines.append("")

    # KPI5 verify 커버리지
    v = baseline.verify_coverage
    lines.append("## KPI5 입력 verify 커버리지 — shadow 3-state 결정 구간(재사용)")
    lines.extend(_metric_line("결정 구간 비율", v.coverage))
    verdict_str = " ".join(f"{k}={val}" for k, val in sorted(v.verdict_counts.items())) or "(없음)"
    lines.append(f"  - 표본: shadow 관측 {v.total_observations}건 · verdict 분포 {verdict_str}")
    lines.append("")

    # 후속(범위 밖) note
    lines.append("## 후속 (범위 밖 — 별도 슬라이스)")
    lines.append("- 세션 mode 컬럼 마이그레이션·전 지표 mode 분해 (현재 5 KPI는 mode 무관)")
    lines.append("- 톤필터 라이브 배선·톤 위반 EventType 신설 (KPI3 측정 조건)")
    lines.append(
        "- per-session 비용 적재(Dialogue total_tokens/estimated_cost_usd)·P&L 구간 로직 (KPI4)"
    )
    lines.append("- 숙달 rate 시간 정규화(measured_at 간격) (KPI1)")
    lines.append("- 전체 11지표 커버리지 맵은 surrogate_baseline_report 참조")
    lines.append("")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# CLI glue — DB 세션·Langfuse 조회·shadow 원장 로드(pragma no cover·라이브 통합 소관).
# ──────────────────────────────────────────────────────────────────────────


def _resolve_params(
    user_id: str | None,
    since: str | None,
    until: str | None,
) -> tuple[uuid.UUID | None, datetime | None, datetime | None]:
    """CLI 문자열 인자를 타입으로 해석(순수·검증). user_id는 UUID, since/until은 ISO8601.

    잘못된 형식은 ValueError로 즉시 실패(조용한 폴백 없음·surrogate_baseline_report 미러).
    """
    resolved_user = uuid.UUID(user_id) if user_id is not None else None
    resolved_since = datetime.fromisoformat(since) if since is not None else None
    resolved_until = datetime.fromisoformat(until) if until is not None else None
    return resolved_user, resolved_since, resolved_until


async def load_retention_sessions(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    since: datetime | None,
    until: datetime | None,
) -> list[tuple[uuid.UUID | None, datetime | None]]:
    """KPI2 입력 — `LearningSession`의 (user_id, started_at) 행(compute_wh1 세션 필터 패턴 동형).

    EOS-131 이후 이 행은 서버 30분 유휴 규칙 writer(`l2/learning_session_writer`)가 만든다 —
    `compute_retention`에 그대로 넘기면 KPI2 재방문율이 된다(조회 전용·쓰기 0).
    """
    session_conds = []
    if user_id is not None:
        session_conds.append(LearningSession.user_id == user_id)
    if since is not None:
        session_conds.append(LearningSession.started_at >= since)
    if until is not None:
        session_conds.append(LearningSession.started_at <= until)
    rows = (
        await session.execute(
            select(LearningSession.user_id, LearningSession.started_at).where(*session_conds)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def _run(  # pragma: no cover — 라이브 PG/Langfuse/원장 glue(단위테스트 아닌 실 통합)
    *,
    user_id: uuid.UUID | None,
    since: datetime | None,
    until: datetime | None,
    mode: str | None,
    shadow_ledger: Path | None,
    cost_days: int,
) -> str:
    """세션을 열어 5 KPI 입력을 계산·조립하고 리포트를 렌더한다(조회 전용·쓰기 0)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        # KPI1 ⑨ mastery + KPI4 per-session 증거(sample_dialogues) — SurrogateMetrics 재사용.
        metrics = await compute_wh1_surrogate_metrics(
            session, user_id=user_id, since=since, until=until, mode=mode
        )
        # KPI2 리텐션 — LearningSession (user, started_at) 조회 → 순수 계산.
        retention = compute_retention(
            await load_retention_sessions(session, user_id=user_id, since=since, until=until)
        )

    # KPI4 코호트 비용 — Langfuse l3_routing 집계(미설정이면 빈 리스트·NO_DATA).
    cost_report = aggregate_l3_events(fetch_l3_events(days=cost_days))

    # KPI5 입력 verify 커버리지 — shadow 원장(있으면) 로드 후 3-state 분포 요약.
    verify_summary: Wh1ShadowDistributionSummary | None = None
    if shadow_ledger is not None:
        observations, _broken = load_ledger(shadow_ledger)
        verify_summary = summarize(observations) if observations else None

    baseline = assemble_pilot_baseline(
        mastery_gain=metrics.mastery_gain_rate,
        sample_mastery_groups=metrics.sample_mastery_groups,
        retention=retention,
        cost_report=cost_report,
        sample_dialogues_with_tokens=metrics.sample_dialogues,
        verify_summary=verify_summary,
        verify_ledger_provided=shadow_ledger is not None,
        user_scoped=user_id is not None,
        window_start=since,
        window_end=until,
        mode_filter=mode,
    )
    return render_pilot_baseline(baseline)


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 파일럿 5 KPI 베이스라인 리포트를 stdout에 출력. 0=성공."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.pilot_kpi_baseline",
        description=(
            "파일럿 KPI 5종(학습성과·리텐션·정서안전·세션비용·verify 커버리지) 베이스라인 "
            "리포트를 낸다(기본 코호트 전체·가짜 0 금지 — 미측정은 NO_DATA 사유 표기). "
            "DB/Langfuse 조회 전용."
        ),
    )
    parser.add_argument("--since", type=str, default=None, help="집계 시작 ISO8601(선택).")
    parser.add_argument("--until", type=str, default=None, help="집계 끝 ISO8601(선택).")
    parser.add_argument(
        "--user-id", type=str, default=None, help="특정 user UUID(선택·기본은 코호트 전체 집계)."
    )
    parser.add_argument(
        "--mode",
        type=str,
        default=None,
        help="응용 모드 스코프(예: suneung) — ①⑤⑧에만 반영·본 5 KPI는 mode 무관(정직 표기).",
    )
    parser.add_argument(
        "--shadow-ledger",
        type=Path,
        default=None,
        help=(
            "wh1_shadow_harvest 원장(ndjson) 경로 — KPI5 입력 verify 커버리지 산출용"
            "(없으면 NO_DATA)."
        ),
    )
    parser.add_argument(
        "--cost-days", type=int, default=7, help="KPI4 코호트 비용 집계 기간(일). 기본 7."
    )
    args = parser.parse_args(argv)
    user_id, since, until = _resolve_params(args.user_id, args.since, args.until)
    report = asyncio.run(  # pragma: no cover — 라이브 통합 glue
        _run(
            user_id=user_id,
            since=since,
            until=until,
            mode=args.mode,
            shadow_ledger=args.shadow_ledger,
            cost_days=args.cost_days,
        )
    )
    print(report)  # pragma: no cover
    return 0  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
