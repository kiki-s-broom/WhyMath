"""성장 증거(WH-1 대리 지표) 학생 대면 노출 계약 정본 (PED-06 D1 ①).

`docs/architecture/gamification_module_gap_review.md` §3 D1의 설계를 그대로 승계한다(새 설계
아님). `compute_wh1_surrogate_metrics`(`harness/wh1_evaluation.py`)의 지표(원 설계 11종 + 병합
편입 `help_demand_supply_ratio` 1종 = 12종)를 한 덩어리로 노출하면 그 자체가 새 위험이다 —
일부는 학생에게 보이면 금기 위반이 된다:

- `help_reduction_validated`의 `GAMING_SUSPECT` — 학생 대면 노출 시 **낙인**
  (`CLAUDE.md` "부정 피드백 정서 강화 금지"). ⑧(답 미루기 도달 깊이)과 **단독 분리가 안 된다**
  — R15가 교차 방어이므로 노출 계약은 필드 단위 allowlist가 아니라 **조합 제약**이다.
- ②(진단정확도)는 시스템 지표(진단엔진 품질)이지 학생 개인 지표가 아니다 — 내부 전용.
- ④(턴당 토큰)는 비용 지표 — 학생 대면 의미 0. 내부 전용.
- ⑥(보정 점수 Brier)은 "낮을수록 좋음" 역방향 스칼라라 그대로 보이면 오독 — 서술 변환 필수
  (원값은 노출하지 않는다).

**비교·서열·순위 파생 금지**(`07_community.md` "❌ 익명·집계만" 승계) — 이 모듈은 그런 파생을
계산하는 함수를 **의도적으로 두지 않는다**(백분위·랭킹·평균 대비 같은 함수가 이 파일에
없다는 사실 자체가 계약의 일부).

**노출 계층**: 학생 노출 가능(`STUDENT_VISIBLE`)·보호자 요약(`GUARDIAN_SUMMARY`)·내부 전용
(`INTERNAL_ONLY`) 3분류로 고정한다. 이번 태스크 범위(보호자 대시보드 UI 미신설)에서는
`GUARDIAN_SUMMARY`가 `STUDENT_VISIBLE`과 동일 소속을 상속한다(보호자는 학생이 보는 것을
그대로 볼 수 있되 그 이상은 아직 정의되지 않음) — 이 상속을 임의로 벌리지 않는다(과공학 방지).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.harness.wh1_evaluation import (
    R15Verdict,
    SurrogateMetrics,
)

__all__ = [
    "ExposureTier",
    "MetricExposure",
    "classify_metric_exposure",
    "narrate_calibration_brier",
]


class ExposureTier(str, Enum):
    """노출 계층 3분류(고정) — `docs/architecture/gamification_module_gap_review.md` §3 D1 ①."""

    STUDENT_VISIBLE = "student_visible"
    """자기 대비 서술로 학생에게 보여도 안전. 비교·서열·순위 파생은 이 계층에서도 금지."""

    GUARDIAN_SUMMARY = "guardian_summary"
    """보호자 요약 노출 가능. 현재 범위에서는 `STUDENT_VISIBLE`과 동일 소속(§ 상단 참조)."""

    PROVISIONAL = "provisional"
    """근사 지표 — 계산·내부 리포트는 유지하되 학생·보호자 노출은 보류(MISC-20).

    `INTERNAL_ONLY`(시스템 품질·비용 — 애초에 학생 개인 지표가 아님)와 성격이 다르다. 이 계층은
    "학생 지표가 맞지만 값이 아직 정직하게 말할 수 있는 상태가 아니다"를 뜻하며, 재승격 조건이
    충족되면 `STUDENT_VISIBLE`로 되돌아간다(만료 없는 유예 금지 — 조건은 suppressed_reason에 명시).
    """

    INTERNAL_ONLY = "internal_only"
    """운영·내부 전용 — 학생·보호자 어느 쪽에도 노출 금지(시스템 품질·비용 지표 등)."""


# 13지표 attr → 정적 노출 계층(안전 축). `diagnosis_agreement_rate`(②)·`tokens_per_turn`(④)만
# INTERNAL_ONLY — 나머지는 전부 STUDENT_VISIBLE(⑥·⑧은 아래 조합 규칙으로 *표현*이 추가 제약됨,
# 계층 자체는 STUDENT_VISIBLE 유지 — "안 보임"이 아니라 "다르게 보임").
# `help_demand_supply_ratio`(⑮·S3-16, 병합 시 편입)는 ⑤·⑧과 같은 축(학생 자신의 도움 요청·수신
# 행태)이라 STUDENT_VISIBLE — ②·④(시스템 품질·비용)와는 성격이 다르다. 노출 문구 설계(서술 변환·
# 조합 제약 필요 여부)는 이 모듈 최초 판정 당시 범위 밖이었던 지표라 **미확정**(발화조건: 보호자
# 대시보드 UI 착수 시 재검토).
_STATIC_TIER: dict[str, ExposureTier] = {
    "verify_pass_rate": ExposureTier.STUDENT_VISIBLE,
    "diagnosis_agreement_rate": ExposureTier.INTERNAL_ONLY,
    "session_completion_rate": ExposureTier.STUDENT_VISIBLE,
    "tokens_per_turn": ExposureTier.INTERNAL_ONLY,
    "help_reduction_slope": ExposureTier.STUDENT_VISIBLE,
    "help_demand_supply_ratio": ExposureTier.STUDENT_VISIBLE,
    "calibration_brier": ExposureTier.STUDENT_VISIBLE,
    "transfer_score": ExposureTier.STUDENT_VISIBLE,
    "hint_depth_reached": ExposureTier.STUDENT_VISIBLE,
    "mastery_gain_rate": ExposureTier.STUDENT_VISIBLE,
    # ⑯ 결손 복구 리드타임(PED-13) — 자기 대비 축이라 학생 노출 가능. 또래·평균 대비 파생은
    # 두지 않는다(부재가 계약 · 5원칙 #2 · ARCH-27 게이트가 기계로 막는다).
    "gap_recovery_leadtime_days": ExposureTier.STUDENT_VISIBLE,
    # MISC-20 (a) 강등 — 값이 `is_active=false` 비율이라 "학생이 실제로 극복"과 "감쇠·반박·캡
    # 절단으로 조용히 비활성화"를 구분하지 못하는데(코드가 자백: wh1_evaluation:1208), 근사임을
    # 알리는 `Metric.note`는 `GrowthEvidenceMetricView`에서 구조적으로 탈락한다 — 학생은 근사값을
    # "내가 오개념을 극복한 비율"로 읽는다(우선순위 #1 학생 안전 · "확실하지 않을 때 자신 있게
    # 말함 금지"). note를 학생에게 흘리는 우회는 택하지 않는다(검수 안 된 내부 문구).
    "misconception_resolution_rate": ExposureTier.PROVISIONAL,
    "self_solve_rate": ExposureTier.STUDENT_VISIBLE,
}

# SurrogateMetrics 필드 순서(정본 순서 — surrogate_baseline_report._METRIC_ROWS와 동일 순서).
METRIC_FIELD_ORDER: tuple[str, ...] = tuple(_STATIC_TIER)

# MISC-20 — PROVISIONAL 억제 사유(내부 문구). **재승격 조건을 문면에 담는다** — 만료 없는
# 유예를 만들지 않기 위해서다(CLAUDE.md 금기 · PB-02 그랜드파더 만료 계약 동형). 이 문장은
# *운영자 리포트용*이며 학생 응답에는 서빙 층이 소유한 별도 문장이 나간다(api/me.py).
_PROVISIONAL_SUPPRESSED_REASON = (
    "근사 지표라 학생 노출을 보류합니다 — 값이 is_active=false 비율이라 실제 해소와 감쇠·반박·"
    "캡절단을 구분하지 못합니다. 재승격 조건: misconception_hypothesis.deactivated_reason이 "
    "착지하고(MISC-20 b) 실데이터에서 '해소' 표본이 최소 규모에 도달한 시점의 명시적 판정."
)

_BRIER_GOOD_THRESHOLD = 0.15  # 낮을수록 좋음 — 경험적 구간(과신·과소신 진단 아님, 3구간 요약).
_BRIER_FAIR_THRESHOLD = 0.30


def narrate_calibration_brier(value: float | None) -> str:
    """⑥ 보정 점수(Brier) 원 스칼라를 학생 노출용 서술로 변환(원값은 반환하지 않는다).

    Brier는 "낮을수록 좋음" 역방향이라 원 스칼라를 그대로 보이면 오독한다(gap review 판단).
    값이 없으면(NO_DATA·확신도 입력 UI 부재) 그 자체를 서술한다.
    """
    if value is None:
        return "아직 예측 확신도 데이터가 없어요."
    if value <= _BRIER_GOOD_THRESHOLD:
        return "네 예측이 실제 정답과 꽤 잘 맞고 있어요."
    if value <= _BRIER_FAIR_THRESHOLD:
        return "네 예측과 실제 정답이 조금씩 어긋나고 있어요."
    return "네 예측과 실제 정답의 차이가 큰 편이에요."


class MetricExposure(BaseModel):
    """지표 1종의 최종 노출 판정 — 계층 + 노출 가능 여부(조합 제약 반영 후) + 노출용 서술."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="SurrogateMetrics 필드명.")
    tier: ExposureTier = Field(description="정적 노출 계층(안전 축).")
    exposable_now: bool = Field(
        description=(
            "이번 판정에서 실제로 노출 가능한지 — INTERNAL_ONLY는 항상 False, "
            "⑧은 R15 verdict가 GAMING_SUSPECT면 False(조합 제약)."
        )
    )
    suppressed_reason: str | None = Field(
        default=None,
        description="exposable_now=False인 이유(내부 전용·조합 제약). 노출 가능이면 None.",
    )


def classify_metric_exposure(metrics: SurrogateMetrics) -> dict[str, MetricExposure]:
    """13지표 전체의 노출 판정 — 정적 계층 + ⑧×R15 조합 제약을 적용한 최종 표.

    조합 제약(gap review 명시): ⑧(답 미루기 도달 깊이)은 `help_reduction_validated.verdict`가
    `GAMING_SUSPECT`이면 노출하지 않는다(R15가 교정기 함정으로 판정한 도움 감소를 "답 미루기
    깊이"로만 떼어 보이면 게이밍을 은연중 정당화하는 신호가 된다). `GAMING_SUSPECT` 라벨
    자체는 항상 `INTERNAL_ONLY`이며 이 함수의 반환값에 별도 필드로 노출하지 않는다(호출자가
    `metrics.help_reduction_validated`를 직접 읽지 않도록 이 함수가 유일한 노출 판정 경로가
    되게 한다).
    """
    verdict = metrics.help_reduction_validated.verdict
    result: dict[str, MetricExposure] = {}
    for field, tier in _STATIC_TIER.items():
        if tier is ExposureTier.PROVISIONAL:
            result[field] = MetricExposure(
                field=field,
                tier=tier,
                exposable_now=False,
                suppressed_reason=_PROVISIONAL_SUPPRESSED_REASON,
            )
            continue
        if tier is ExposureTier.INTERNAL_ONLY:
            result[field] = MetricExposure(
                field=field,
                tier=tier,
                exposable_now=False,
                suppressed_reason="내부 전용 지표(시스템 품질/비용) — 학생·보호자 비노출.",
            )
            continue
        if field == "hint_depth_reached" and verdict is R15Verdict.GAMING_SUSPECT:
            result[field] = MetricExposure(
                field=field,
                tier=tier,
                exposable_now=False,
                suppressed_reason=(
                    "R15 결합 판정이 교정기 함정(GAMING_SUSPECT)으로 나와 이 지표 단독 노출을 "
                    "보류합니다(조합 제약 — 답 미루기 깊이만 보이면 힌트 회피를 개선으로 오독)."
                ),
            )
            continue
        result[field] = MetricExposure(
            field=field, tier=tier, exposable_now=True, suppressed_reason=None
        )
    return result
