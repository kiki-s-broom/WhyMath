"""WH-1 0단계 대리 지표 *코호트 베이스라인 리포트* — 설계 산출물 결선(CLI).

설계 정본: `docs/architecture/04a_wh1_tutoring_harness.md` §8.4. WH-1 0단계의 산출물은
**"커버리지 맵 + 베이스라인 수치"**(무엇을 *지금* 잴 수 있고, 무엇이 *아직* 못 재는지)다.
`wh1_evaluation.compute_wh1_surrogate_metrics`가 지표 12종(7 + S3 세션 4 + S3-16 ⑫)을 계산하지만,
그 결과는 지금까지 per-user API(`GET /v1/me/harness-metrics`)로만 소비됐다 — 설계가 명시한
**코호트 전체 집계(`user_id=None`)를 ops/스크립트가 직접 호출**하는 진입점(그 산출물을 사람이
읽을 리포트로 렌더)이 비어 있었다. 본 모듈이 그 결선이다.

렌더 철학(계산 계층과 동일·CLAUDE.md "모르면 모른다"): "가짜 0 금지"를 그대로 표면화한다 —
MEASURED만 값을 보이고, NO_DATA/미계측은 값 대신 사유(note)를 그대로 옮긴다. 요약에 커버리지
카운트(MEASURED n / 전체)를 실어 *무엇이 아직 데이터 없이 비어 있는지*를 한 장으로 드러낸다.

실행: `python -m whymath_backend.harness.surrogate_baseline_report [--since ISO --until ISO
[--user-id UUID]]`. 기본은 코호트 전체(user 미지정)·전체 기간. DB 조회 전용(쓰기 0).

계층 메모(CLAUDE.md 7계층): `wh1_evaluation`(횡단 인프라)을 소비하는 *리포팅* 진입점이다 —
L1(활동)·L2(mastery)·L4(오개념)·Dialogue를 조회만 하는 계산 계층을 그대로 호출하고, 새 계산·
새 지표를 만들지 않는다(렌더 전용).

**PED-06 확장(도달 관측 + 3상태 + 노출 계약)**: `docs/architecture/gamification_module_gap_
review.md` §3 D1. `render_baseline_report`(위 원본)는 그대로 두고, `render_growth_evidence_
reach_report`가 그 위에 세 가지를 더한다 — ① 지표별 노출 계층(`growth_evidence_exposure`
계약 재사용) ② 3상태(구조적불가/무데이터/미도달) 구분 ③ `requests_total`(라이브 카운터 —
`GET /health/ready` `growth_evidence.requests_total`에서 읽은 값을 CLI 인자로 받는다. 이
CLI는 DB만 조회하는 별도 프로세스라 실행 중인 API 서버의 인프로세스 카운터를 직접 읽을 수
없다 — 값을 합성하지 않고 인자로 명시 요구한다). 새 계산·새 지표는 없다(렌더 전용 원칙 유지).

**S4-19 확장(3상태 단계 검증 회계 내부 섹션)**: `compute_step_verification_accounting`
(wh1_evaluation)의 결과를 두 리포트 끝에 내부 전용 섹션으로 덧붙인다 — 파생 지표
(step_decision_rate·step_incorrect_rate)는 `SurrogateMetrics`에 넣지 않아(학생 라우트
자동 서빙 실측·노출 집행 별항) 이 CLI가 유일한 렌더 표면이다. 학생 라우트 무변경.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import datetime
from enum import Enum

from whymath_backend.db.session import get_sessionmaker
from whymath_backend.harness.growth_evidence_exposure import (
    ExposureTier,
    classify_metric_exposure,
)
from whymath_backend.harness.wh1_evaluation import (
    MetricStatus,
    StepVerificationAccounting,
    SurrogateMetrics,
    compute_step_verification_accounting,
    compute_wh1_surrogate_metrics,
)

__all__ = [
    "GrowthEvidenceReachState",
    "classify_reach_state",
    "render_baseline_report",
    "render_growth_evidence_reach_report",
    "render_step_verification_section",
    "main",
]


# 상태 → 아이콘(커버리지 맵 가독). MEASURED 실측·NO_DATA 좌석 있으나 표본 0·나머지는 미계측.
_STATUS_ICON: dict[MetricStatus, str] = {
    MetricStatus.MEASURED: "🟢",
    MetricStatus.NO_DATA: "🟡",
    MetricStatus.NOT_INSTRUMENTED: "🔴",
    MetricStatus.REQUIRES_DATA: "🔴",
    MetricStatus.REQUIRES_TOOL: "🔴",
}

# 렌더 순서·라벨·표본 필드 — (라벨, SurrogateMetrics 지표 attr, 표본 수 attr). 12 지표 정본 순서
# (7종 + S3 세션 4종 + S3-16 ⑫). 표본 attr은 그 지표의 대표 표본 수(없으면 None).
_METRIC_ROWS: list[tuple[str, str, str | None]] = [
    ("① verify 통과율", "verify_pass_rate", "sample_verify_events"),
    ("② 진단정확도(오프라인)", "diagnosis_agreement_rate", "sample_diagnostic_probes"),
    ("③ 세션 완주율", "session_completion_rate", "sample_sessions"),
    ("④ 턴당 토큰", "tokens_per_turn", "sample_dialogues"),
    ("⑤ 도움 감소 곡선", "help_reduction_slope", "sample_hint_events"),
    ("⑥ 보정 점수(Brier)", "calibration_brier", "sample_calibration_pairs"),
    ("⑦ 전이 점수(근사)", "transfer_score", "sample_transfer_probes"),
    ("⑧ 답 미루기 도달 깊이", "hint_depth_reached", "sample_hint_events"),
    ("⑨ BKT 숙달 증가율", "mastery_gain_rate", "sample_mastery_groups"),
    ("⑩ 오개념 해소율", "misconception_resolution_rate", "sample_misconception_hypotheses"),
    ("⑪ 스스로 풀이 도달율", "self_solve_rate", "sample_resolved_dialogues"),
    ("⑯ 결손 복구 리드타임", "gap_recovery_leadtime_days", "sample_gap_recovery_groups"),
    ("⑮ 도움 요청 대 제공 비", "help_demand_supply_ratio", "sample_demand_events"),
]


def _format_value(value: float | None) -> str:
    """지표 value 렌더 — None(미측정·표본 부족)은 값 대신 '—'(가짜 0 금지)."""
    return "—" if value is None else f"{value:.4f}"


def render_baseline_report(metrics: SurrogateMetrics) -> str:
    """대리 지표 12종 커버리지 맵 + 베이스라인을 사람이 읽을 마크다운으로 렌더(순수·DB 무관).

    헤더에 집계 범위(코호트/본인·시간창)와 커버리지 카운트(MEASURED n/전체)를, 이어 지표별로
    상태 아이콘·값·표본 수·사유(note)를, 끝에 R15 결합 판정을 낸다. "가짜 0 금지" — NO_DATA/
    미계측은 값 대신 note를 옮긴다(무엇이 아직 비어 있는지 정직 표면화). 입력 `SurrogateMetrics`
    외 어떤 계산도 하지 않는다(렌더 전용).
    """
    scope = "본인(user)" if metrics.user_scoped else "코호트 전체"
    win_start = metrics.window_start.isoformat() if metrics.window_start else "무한 과거"
    win_end = metrics.window_end.isoformat() if metrics.window_end else "무한 미래"
    measured = sum(
        1 for _, attr, _ in _METRIC_ROWS if getattr(metrics, attr).status is MetricStatus.MEASURED
    )
    total = len(_METRIC_ROWS)

    lines: list[str] = [
        "# WH-1 0단계 대리 지표 베이스라인 (커버리지 맵)",
        "",
        f"- 집계 범위: {scope} · 시간창 {win_start} ~ {win_end}",
        f"- 커버리지: MEASURED {measured}/{total} · NO_DATA/미계측 {total - measured}/{total}",
        "  (가짜 0 금지 — 미측정은 값 대신 사유를 표기)",
        "",
    ]
    for label, attr, sample_attr in _METRIC_ROWS:
        metric = getattr(metrics, attr)
        icon = _STATUS_ICON.get(metric.status, "🔴")
        sample = f"표본 {getattr(metrics, sample_attr)}" if sample_attr is not None else "표본 —"
        lines.append(f"## {icon} {label}")
        lines.append(f"- 상태 {metric.status.value} · 값 {_format_value(metric.value)} · {sample}")
        lines.append(f"- {metric.note}")
        lines.append("")

    r15 = metrics.help_reduction_validated
    lines.append("## R15 결합 판정 (⑤ 도움 감소 × 정답률 × 난이도)")
    lines.append(f"- 판정 {r15.verdict.value}")
    lines.append(f"- {r15.note}")
    lines.append("")
    return "\n".join(lines)


# ── PED-06 — 도달 3상태 + 노출 계약 확장 ──────────────────────────────────────────
# `docs/architecture/gamification_module_gap_review.md` §3 D1 ③. 세션완주율(③)만 구조적
# 불가로 고정한다 — LearningSession 생성자 호출이 src/ 전체에서 0건이고(실측), writer는
# 2026-07-29 영구 미신설 결정(S3-16 소유). 다른 지표는 전부 좌석이 살아 있어 표본만 쌓이면
# MEASURED가 된다(구조적 불가가 아니다).
_STRUCTURALLY_IMPOSSIBLE_FIELDS: frozenset[str] = frozenset({"session_completion_rate"})

# calibration_brier가 NO_DATA일 때 REC-01(attempt 제출 자체 미도달)과 구분해 붙이는 부기 —
# "확신도 필드를 받을 입력 UI가 없다"는 *다른 층*의 이유임을 리포트가 명시한다(gap review ④).
_CALIBRATION_NO_UI_NOTE = (
    "(참고: attempt 제출 루프 자체는 REC-01 축과 별개로 이미 배선돼 있음 — 비어 있는 이유는 "
    "confidence_self_reported를 받을 학생 입력 UI가 src/mobile/lib/에 아직 없기 때문. "
    "REC-01의 '입력 루프 미도달'과는 다른 층의 부재.)"
)


class GrowthEvidenceReachState(str, Enum):
    """지표 1종의 도달 3상태(+ 도달) — 미도달/무데이터/구조적불가를 서로 다른 칸으로 분리.

    같은 정보를 한 칸에 뭉치면 다음 세션이 "무데이터니까 writer를 만들자"처럼 잘못된 조치를
    취할 위험이 있다(구조적 불가는 writer를 만들어도 소용없는 *결정된* 상태 — S3-16 소유).
    """

    STRUCTURALLY_IMPOSSIBLE = "structurally_impossible"
    """생산자 자체가 없음(예: ③ LearningSession writer 영구 미신설) — 표본을 기다려도 안 참."""

    NO_DATA = "no_data"
    """계측 좌석은 있는데 표본이 0(또는 부족) — MetricStatus가 MEASURED가 아님."""

    UNREACHED = "unreached"
    """계측은 되는데(MEASURED) 학생에게 보여준 적이 없음 — `requests_total`이 0."""

    REACHED = "reached"
    """계측되고(MEASURED) 실제로 요청된 적도 있음(`requests_total` > 0) — 유일한 정상 종착점."""


def classify_reach_state(
    field: str, status: MetricStatus, requests_total: int
) -> GrowthEvidenceReachState:
    """지표 1종의 도달 상태를 판정(순수 함수) — 구조적불가 > 무데이터 > 미도달 > 도달 우선순위.

    `field`가 `_STRUCTURALLY_IMPOSSIBLE_FIELDS`에 있으면 다른 조건과 무관하게
    `STRUCTURALLY_IMPOSSIBLE`(생산자가 없으니 표본·요청 여부가 의미 없음). 그다음 `status`가
    `MEASURED`가 아니면 `NO_DATA`. 둘 다 아니면 `requests_total`로 미도달/도달을 가른다.
    """
    if field in _STRUCTURALLY_IMPOSSIBLE_FIELDS:
        return GrowthEvidenceReachState.STRUCTURALLY_IMPOSSIBLE
    if status is not MetricStatus.MEASURED:
        return GrowthEvidenceReachState.NO_DATA
    if requests_total <= 0:
        return GrowthEvidenceReachState.UNREACHED
    return GrowthEvidenceReachState.REACHED


_REACH_STATE_LABEL: dict[GrowthEvidenceReachState, str] = {
    GrowthEvidenceReachState.STRUCTURALLY_IMPOSSIBLE: "구조적 불가",
    GrowthEvidenceReachState.NO_DATA: "무데이터",
    GrowthEvidenceReachState.UNREACHED: "미도달",
    GrowthEvidenceReachState.REACHED: "도달",
}

_TIER_LABEL: dict[ExposureTier, str] = {
    ExposureTier.STUDENT_VISIBLE: "학생 노출 가능",
    ExposureTier.GUARDIAN_SUMMARY: "보호자 요약",
    ExposureTier.INTERNAL_ONLY: "내부 전용",
    # MISC-20 — 근사라 학생 노출만 보류된 지표. 운영자 리포트에는 값·도달상태가 그대로 실린다
    # (강등 ≠ 삭제 — 계산·리포트는 유지되고 억제 사유에 재승격 조건이 함께 렌더된다).
    ExposureTier.PROVISIONAL: "근사(학생 노출 보류)",
}


def render_growth_evidence_reach_report(metrics: SurrogateMetrics, requests_total: int) -> str:
    """`render_baseline_report` 위에 노출 계약 + 도달 3상태를 얹은 확장 리포트(순수·DB 무관).

    `requests_total`은 `GET /health/ready`의 `growth_evidence.requests_total`(라이브
    인프로세스 카운터)에서 읽어 인자로 전달한다 — 이 함수 자체는 DB도 라이브 프로세스 상태도
    새로 조회하지 않는다(렌더 전용 원칙 유지). "표본 0"과 "요청 0"을 구분해 둘 다 "0건 통과"로
    뭉개지 않는다(VIZ-01·NLP-01 이중 회계 승계).
    """
    exposure = classify_metric_exposure(metrics)
    lines: list[str] = [
        "# 성장 증거(WH-1 대리 지표) 도달 관측 + 노출 계약",
        "",
        f"- 도달 카운터: GET /v1/me/harness-metrics 누적 요청 {requests_total}건",
        "  (0이면 '측정했더니 0'이 아니라 '이 API를 부르기로 결정한 적이 없다' — 정적 감사 "
        "결과와의 이중 회계)",
        "",
    ]
    for label, attr, _sample_attr in _METRIC_ROWS:
        metric = getattr(metrics, attr)
        reach = classify_reach_state(attr, metric.status, requests_total)
        exp = exposure[attr]
        tier_label = _TIER_LABEL[exp.tier]
        lines.append(f"## {label}")
        lines.append(
            f"- 도달상태 {_REACH_STATE_LABEL[reach]} · 계측상태 {metric.status.value} · "
            f"노출계층 {tier_label}"
        )
        if not exp.exposable_now:
            lines.append(f"- 노출 억제 사유: {exp.suppressed_reason}")
        if attr == "calibration_brier" and metric.status is not MetricStatus.MEASURED:
            lines.append(f"- {_CALIBRATION_NO_UI_NOTE}")
        lines.append("")
    return "\n".join(lines)


def render_step_verification_section(accounting: StepVerificationAccounting) -> str:
    """S4-19 — 3상태 단계 검증 회계를 내부 전용 섹션으로 렌더(순수·DB 무관·결정론).

    지표 ①(verify 통과율·binary)의 병기 파생이다 — 교체가 아니라 이중 회계. "가짜 0 금지"를
    승계한다: 전이 표본 0이면 파생 비율을 0이 아니라 'NO_DATA(—)'로 표기한다. 카운트 비보유
    이벤트는 "구판 *또는* 검증 미실행 제출"의 한 버킷으로 정직 계상한다(저장 모양이 같아 구분
    불가 — 구분한다고 주장하지 않는다). 이 섹션은 학생 라우트(`GET /v1/me/harness-metrics`)에
    나가지 않는다 — `SurrogateMetrics` 무변경(노출 집행 별항·2026-08-04 헌법).
    """
    # 두 비율은 같은 분모라 계산 계층에서 함께 None이거나 함께 값이다 — 렌더는 방어적으로 둘 다
    # 확인한다(한쪽만 None인 비정상 입력도 NO_DATA로 정직 표기·크래시 없음).
    if accounting.step_decision_rate is None or accounting.step_incorrect_rate is None:
        rate_line = (
            "- step_decision_rate — · step_incorrect_rate — "
            "(counted 전이 표본 0 — NO_DATA·가짜 0 아님)"
        )
    else:
        rate_line = (
            f"- step_decision_rate {accounting.step_decision_rate:.4f} · "
            f"step_incorrect_rate {accounting.step_incorrect_rate:.4f} "
            "(분모=counted 이벤트의 전체 전이 합·D6 정의)"
        )
    lines = [
        "## [내부 전용] 3상태 단계 검증 회계 (S4-19 — 지표 ① binary와 이중 회계)",
        f"- counted(3카운트 보유·신판 유검증) {accounting.counted_events}건 · "
        "uncounted(구판 또는 검증 미실행 제출 — 구분 불가·한 버킷) "
        f"{accounting.uncounted_events}건",
        f"- 전이 합계: correct {accounting.n_correct_total} · "
        f"incorrect {accounting.n_incorrect_total} · "
        f"unverifiable {accounting.n_unverifiable_total}",
        rate_line,
        f"- ocr_gated(저신뢰 OCR로 step-incorrect 코칭 보류) {accounting.ocr_gated_events}건",
        "- 학생 라우트 비노출(SurrogateMetrics 무변경) — 이 CLI 섹션이 유일한 렌더 표면.",
        "",
    ]
    return "\n".join(lines)


def _resolve_params(
    user_id: str | None,
    since: str | None,
    until: str | None,
) -> tuple[uuid.UUID | None, datetime | None, datetime | None]:
    """CLI 문자열 인자를 타입으로 해석(순수·검증). user_id는 UUID, since/until은 ISO8601.

    TZ-aware/naive·since>until 등 세부 검증은 계산 계층(`compute_wh1_surrogate_metrics`가 받은
    경계를 그대로 비교)·API 계층(time_window)이 담당한다 — 여기선 파싱만 한다(잘못된 형식은
    ValueError로 즉시 실패·조용한 폴백 없음).
    """
    resolved_user = uuid.UUID(user_id) if user_id is not None else None
    resolved_since = datetime.fromisoformat(since) if since is not None else None
    resolved_until = datetime.fromisoformat(until) if until is not None else None
    return resolved_user, resolved_since, resolved_until


async def _run(  # pragma: no cover — 라이브 PG 연결 glue(단위테스트 아닌 실 PG 검증)
    *,
    user_id: uuid.UUID | None,
    since: datetime | None,
    until: datetime | None,
    requests_total: int | None,
) -> str:
    """세션을 열어 대리 지표를 계산하고 리포트를 렌더한다(DB 조회 전용·쓰기 0).

    `requests_total`이 주어지면(PED-06) 도달 3상태 + 노출 계약을 얹은 확장 리포트를,
    아니면(기본) 기존 베이스라인 리포트를 낸다 — 기존 호출자(스크립트·문서)의 기본 동작은
    바뀌지 않는다. S4-19: 두 리포트 모두 끝에 3상태 단계 검증 회계 내부 섹션을 덧붙인다
    (이 CLI가 유일한 렌더 표면 — 학생 라우트 비노출).
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        metrics = await compute_wh1_surrogate_metrics(
            session, user_id=user_id, since=since, until=until
        )
        step_accounting = await compute_step_verification_accounting(
            session, user_id=user_id, since=since, until=until
        )
    if requests_total is not None:
        report = render_growth_evidence_reach_report(metrics, requests_total)
    else:
        report = render_baseline_report(metrics)
    return report + "\n" + render_step_verification_section(step_accounting)


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 대리 지표 코호트 베이스라인 리포트를 stdout에 출력. 0=성공."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.surrogate_baseline_report",
        description=(
            "WH-1 0단계 대리 지표 12종의 커버리지 맵 + 베이스라인 리포트를 낸다(기본 코호트 "
            "전체·가짜 0 금지 — 미측정은 사유 표기). DB 조회 전용."
        ),
    )
    parser.add_argument("--since", type=str, default=None, help="집계 시작 ISO8601(선택).")
    parser.add_argument("--until", type=str, default=None, help="집계 끝 ISO8601(선택).")
    parser.add_argument(
        "--user-id",
        type=str,
        default=None,
        help="특정 user UUID(선택·기본은 코호트 전체 집계).",
    )
    parser.add_argument(
        "--requests-total",
        type=int,
        default=None,
        help=(
            "PED-06 — GET /health/ready의 growth_evidence.requests_total 값을 그대로 전달하면 "
            "도달 3상태 + 노출 계약을 얹은 확장 리포트를 낸다(미지정 시 기존 베이스라인 리포트)."
        ),
    )
    args = parser.parse_args(argv)
    user_id, since, until = _resolve_params(args.user_id, args.since, args.until)
    report = asyncio.run(  # pragma: no cover — 라이브 PG 연결 glue
        _run(user_id=user_id, since=since, until=until, requests_total=args.requests_total)
    )
    print(report)  # pragma: no cover
    return 0  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
