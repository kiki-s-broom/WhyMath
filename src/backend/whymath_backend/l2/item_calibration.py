"""L2 — 문항 IRT 모수 *보정*(채점 응답 전수 → 1PL JMLE로 b·θ → 2PL로 a → `Problem` 영속).

`ability_estimation`(학생 θ 추정)·`irt`(순수 IRT 알고리즘)와 대칭으로, 이 모듈은 *문항* 모수를
응답 데이터로 *자가 보정*한다 — 전문가 라벨(`difficulty_overall`) 휴리스틱을 데이터 보정 b로
격상. 두 단계로 나뉜다.

1. **1PL 단계(slice 79 — 동작 그대로)**: `fit_jmle`(결합 최대우도·a=1 고정)이 학생 θ·문항 b를
   동시 추정하고, *응답이 충분한*(≥ `_MIN_RESPONSES_FOR_CALIBRATION`) 문항만 보정 b를 채택한다.
   이 단계의 θ가 척도(logit 원점·단위)를 정의한다.
2. **2PL 단계(EOS-129)**: 1단계 θ를 *고정*하고 문항마다 (a, b)를 조건부 MLE로 다시 적합한다
   (`estimate_item_parameters`). 응답 수·반응 분산·수렴·경계·표준오차 게이트를 **전부** 통과한
   문항만 a를 채택하고, 나머지는 a=1.0(Rasch) 폴백이다 — 폴백 비율과 사유를 리포트가 말한다
   (CLAUDE.md "작동한 비율" 원칙: 보정을 붙였으면 그 보정이 실제로 작동한 비율을 말해야 한다).

소비측: θ 추정은 `resolve_item_difficulty_b`로 보정 b를, CAT 진단 경로
(`next_problem_selection.load_attempt_history_state`)는 `resolve_item_discrimination_a`로 보정 a를
우선 소비한다.

스케일 메모: `fit_jmle`·2PL 적합은 순수 파이썬·전수 적합(소규모 프로토타입용). 운영 트리거(주기
배치·증분 적합·엔드포인트)는 후속 — 본 모듈은 *호출형 함수*만 노출한다(L2→L5 역방향 의존 0).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.irt import (
    _THETA_LOWER,
    _THETA_UPPER,
    ItemFit,
    estimate_item_parameters,
    fit_jmle,
)

# 보정 b를 영속할 최소 응답 수 — 미만은 b 추정 불안정(전부 정답/오답 → 경계값)이라 보류하고
# 휴리스틱(`difficulty_to_logit`)을 유지한다. 데이터 축적에 맞춰 상향(현재는 프로토타입 floor).
_MIN_RESPONSES_FOR_CALIBRATION = 5

# EOS-129: 변별도 a를 추정할 최소 응답 수(경계 θ 응답 제외 후). **프로토타입 floor다** — 문헌상
# 2PL 문항 모수의 안정 추정에는 문항당 수백 응답이 권장된다. 50은 "이 아래로는 적합을 시도조차
# 하지 않는다"는 바닥일 뿐이고, 채택의 실질 판정은 아래 SE 게이트가 한다(응답 수가 충분해도
# 정보가 모자라면 SE가 커서 탈락한다).
_MIN_RESPONSES_FOR_DISCRIMINATION = 50
# EOS-129: 채택할 a의 표준오차 상한. a의 95% 구간이 대략 ±0.6 — a=1.0(폴백)과 a=1.6을 가를 수
# 있는 최소 정밀도다. 이보다 부정확한 a를 쓰면 CAT의 SE 계산 자체가 흔들린다(과대 a는 SE를
# 과소평가해 측정을 조기 종료시킨다 — 폴백보다 나쁘다).
_MAX_DISCRIMINATION_SE = 0.3
# 1PL θ가 이 경계에 닿은 학생(만점·영점 → clamp)은 θ가 추정값이 아니라 발산 표시라 a 입력에서 뺀다.
_THETA_BOUNDARY_EPS = 1e-9

#: a 폴백 사유 코드 — 판정 순서가 곧 이 튜플의 순서다(앞 사유가 걸리면 뒤는 보지 않는다).
FALLBACK_INSUFFICIENT_RESPONSES = "insufficient_responses"
FALLBACK_NO_RESPONSE_VARIANCE = "no_response_variance"
FALLBACK_NOT_CONVERGED = "not_converged"
FALLBACK_A_AT_BOUND = "a_at_bound"
FALLBACK_B_AT_BOUND = "b_at_bound"
FALLBACK_SE_ABOVE_LIMIT = "se_above_limit"
FALLBACK_REASONS: tuple[str, ...] = (
    FALLBACK_INSUFFICIENT_RESPONSES,
    FALLBACK_NO_RESPONSE_VARIANCE,
    FALLBACK_NOT_CONVERGED,
    FALLBACK_A_AT_BOUND,
    FALLBACK_B_AT_BOUND,
    FALLBACK_SE_ABOVE_LIMIT,
)

#: 문항당 응답 수 분포 버킷(응답 ≥1 문항만 센다). 경계가 두 임계(5·50)와 맞물린다.
RESPONSE_COUNT_BUCKETS: tuple[str, ...] = ("1-4", "5-49", "50-99", "100+")

#: a 채택 후보 버킷(응답 ≥ `_MIN_RESPONSES_FOR_DISCRIMINATION`) — EOS-154 사전 지표의 입력.
#: 임계(50)와 이 튜플이 어긋나면 사전 지표가 조용히 거짓이 되므로 테스트가 모든 응답 수에서
#: `_response_bucket`과의 일치를 동결한다(`test_a_candidate_buckets_match_the_threshold`).
A_CANDIDATE_BUCKETS: tuple[str, ...] = ("50-99", "100+")


def _response_bucket(count: int) -> str:
    """응답 수 → 분포 버킷 이름."""
    if count < _MIN_RESPONSES_FOR_CALIBRATION:
        return "1-4"
    if count < _MIN_RESPONSES_FOR_DISCRIMINATION:
        return "5-49"
    if count < 100:
        return "50-99"
    return "100+"


class CalibrationReport(BaseModel):
    """보정 1회의 결과 리포트 — **무엇을 보정했고 무엇이 폴백했는지**를 숫자로 말한다(불변).

    판별도 분모는 b 보정 대상(응답 ≥ `_MIN_RESPONSES_FOR_CALIBRATION`) 문항 전체다. 그보다 응답이
    적은 문항은 b조차 휴리스틱이라 a 판정의 대상이 아니다(분포에는 `1-4` 버킷으로 보인다).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dry_run: bool = Field(description="True면 UPDATE·commit 0건(읽기 전용 측정).")
    items_with_responses: int = Field(description="채점 응답이 1건 이상인 문항 수.")
    calibrated_b: int = Field(description="b 보정 대상(응답 ≥ 5) 문항 수 = a 판정 분모.")
    discrimination_calibrated: int = Field(description="a를 채택한 문항 수.")
    discrimination_fallback: int = Field(description="a=1.0 폴백 문항 수(분모 − 채택).")
    fallback_reasons: dict[str, int] = Field(description="폴백 사유 코드별 건수(0건 사유 포함).")
    response_count_distribution: dict[str, int] = Field(
        description="문항당 응답 수 분포(버킷 → 문항 수, 0건 버킷 포함)."
    )
    boundary_theta_responses_excluded: int = Field(
        description="1PL θ가 경계(만점·영점)라 a 추정 입력에서 뺀 응답 수(b 보정 대상 문항 한정)."
    )

    @property
    def discrimination_fallback_ratio(self) -> float | None:
        """a 폴백 비율 = 폴백 / b 보정 대상. **분모 0이면 None**(0.0으로 접지 않는다 —
        "측정할 문항이 없었다"와 "전부 작동했다"는 다른 사실이다)."""
        if self.calibrated_b == 0:
            return None
        return self.discrimination_fallback / self.calibrated_b

    @property
    def discrimination_candidates(self) -> int:
        """응답 ≥ 50건인 문항 수 — a 채택의 **사전 지표(상한)**(EOS-154).

        경계 θ 응답 제외·수렴·SE 게이트가 이 뒤에 더 걸리므로 채택 수는 이 값을 넘지 못한다.
        이 값이 0이면 a는 구조적으로 채택될 수 없고, 1 이상이어도 채택이 보장되지는 않는다.
        """
        return sum(self.response_count_distribution.get(b, 0) for b in A_CANDIDATE_BUCKETS)


@dataclass(frozen=True, slots=True)
class _OnePlFit:
    """1PL 단계 결과 — 보정 b(임계 통과분)·학생 θ·문항별 (학생 인덱스, 정답) 응답."""

    calibrated_b: dict[uuid.UUID, float]
    abilities: list[float]
    item_responses: dict[uuid.UUID, list[tuple[int, bool]]]


@dataclass(frozen=True, slots=True)
class _CalibrationPlan:
    """보정 계획 — 영속할 값(1PL b·채택 2PL 적합)과 리포트. 순수 산출물(DB 무관)."""

    calibrated_b: dict[uuid.UUID, float]
    adopted: dict[uuid.UUID, ItemFit]
    report: CalibrationReport


def _fit_one_pl(rows: list[tuple[uuid.UUID, uuid.UUID, bool]]) -> _OnePlFit:
    """(user_id, problem_id, 정답) 응답 → `fit_jmle`(θ·b 동시 추정) → 응답 N회 이상 문항 b 채택.

    학생·문항을 0-based로 인덱싱해 희소 삼중쌍을 만든다. 빈 입력이면 빈 결과.
    """
    if not rows:
        return _OnePlFit(calibrated_b={}, abilities=[], item_responses={})
    student_idx: dict[uuid.UUID, int] = {}
    item_idx: dict[uuid.UUID, int] = {}
    responses: list[tuple[int, int, bool]] = []
    item_responses: dict[uuid.UUID, list[tuple[int, bool]]] = {}
    for user_id, problem_id, is_correct in rows:
        s = student_idx.setdefault(user_id, len(student_idx))
        i = item_idx.setdefault(problem_id, len(item_idx))
        responses.append((s, i, bool(is_correct)))
        item_responses.setdefault(problem_id, []).append((s, bool(is_correct)))
    abilities, difficulties = fit_jmle(responses, len(student_idx), len(item_idx))
    calibrated_b = {
        problem_id: difficulties[i]
        for problem_id, i in item_idx.items()
        if len(item_responses[problem_id]) >= _MIN_RESPONSES_FOR_CALIBRATION
    }
    return _OnePlFit(calibrated_b=calibrated_b, abilities=abilities, item_responses=item_responses)


def _compute_calibrated_b(
    rows: list[tuple[uuid.UUID, uuid.UUID, bool]],
) -> dict[uuid.UUID, float]:
    """(user_id, problem_id, 정답) 응답 → 문항별 1PL 보정 b(응답수 ≥ 임계 문항만). 순수·DB 무관.

    slice 79의 1PL 단계 그대로다(2PL 단계와 무관하게 같은 값을 낸다). 빈 입력이면 빈 매핑.
    """
    return _fit_one_pl(rows).calibrated_b


def _classify_discrimination(
    fit: ItemFit | None, n_responses: int, has_variance: bool
) -> str | None:
    """a 채택 판정 — 채택이면 None, 탈락이면 `FALLBACK_REASONS` 중 **첫** 사유 코드.

    `fit`은 응답 수·분산 게이트를 통과했을 때만 계산된다(그 전 탈락이면 None이 들어온다).
    """
    if n_responses < _MIN_RESPONSES_FOR_DISCRIMINATION:
        return FALLBACK_INSUFFICIENT_RESPONSES
    if not has_variance:
        return FALLBACK_NO_RESPONSE_VARIANCE
    if fit is None or not fit.converged:
        return FALLBACK_NOT_CONVERGED
    if fit.a_clamped:
        return FALLBACK_A_AT_BOUND
    if fit.b_clamped:
        return FALLBACK_B_AT_BOUND
    if not fit.discrimination_se <= _MAX_DISCRIMINATION_SE:  # inf·nan도 탈락
        return FALLBACK_SE_ABOVE_LIMIT
    return None


def _compute_calibration(
    rows: list[tuple[uuid.UUID, uuid.UUID, bool]], *, dry_run: bool = False
) -> _CalibrationPlan:
    """1PL(b·θ) → 2PL(a) 두 단계 보정 계획을 산출한다. 순수·DB 무관·결정론.

    2PL 단계는 b 보정 대상 문항만 본다. 경계 θ(만점·영점 학생) 응답을 빼고, 판정 게이트를 전부
    통과하면 그 적합의 (a, b)를 **짝으로** 채택한다 — a는 같은 적합의 b와 함께여야 의미가 있다
    (1PL b에 2PL a를 붙이면 곡선이 실제 적합과 어긋난다).
    """
    one_pl = _fit_one_pl(rows)
    distribution = dict.fromkeys(RESPONSE_COUNT_BUCKETS, 0)
    for responses in one_pl.item_responses.values():
        distribution[_response_bucket(len(responses))] += 1

    reasons = dict.fromkeys(FALLBACK_REASONS, 0)
    adopted: dict[uuid.UUID, ItemFit] = {}
    excluded = 0
    for problem_id, b_1pl in one_pl.calibrated_b.items():
        usable: list[tuple[float, bool]] = []
        for s_idx, correct in one_pl.item_responses[problem_id]:
            theta = one_pl.abilities[s_idx]
            if (
                theta <= _THETA_LOWER + _THETA_BOUNDARY_EPS
                or theta >= _THETA_UPPER - _THETA_BOUNDARY_EPS
            ):
                excluded += 1
                continue
            usable.append((theta, correct))
        has_variance = any(c for _, c in usable) and not all(c for _, c in usable)
        fit: ItemFit | None = None
        if len(usable) >= _MIN_RESPONSES_FOR_DISCRIMINATION and has_variance:
            fit = estimate_item_parameters(usable, initial_b=b_1pl)
        reason = _classify_discrimination(fit, len(usable), has_variance)
        if reason is not None:
            reasons[reason] += 1
        elif fit is not None:  # reason None ⇒ fit 존재(판정기가 fit None을 not_converged로 탈락)
            adopted[problem_id] = fit

    report = CalibrationReport(
        dry_run=dry_run,
        items_with_responses=len(one_pl.item_responses),
        calibrated_b=len(one_pl.calibrated_b),
        discrimination_calibrated=len(adopted),
        discrimination_fallback=len(one_pl.calibrated_b) - len(adopted),
        fallback_reasons=reasons,
        response_count_distribution=distribution,
        boundary_theta_responses_excluded=excluded,
    )
    return _CalibrationPlan(calibrated_b=one_pl.calibrated_b, adopted=adopted, report=report)


async def count_adopted_discrimination(session: AsyncSession) -> int:
    """지금 DB에 변별도 a가 채택돼 있는 문항 수(`Problem.irt_a IS NOT NULL`) — 읽기 전용.

    EOS-154: "a 채택이 0에서 1 이상이 됐다"는 전이는 **이번 실행의 채택 수**와 **실행 직전의 채택
    수**를 비교해야 보인다. 직전 값을 별도 상태 파일에 두면 그 파일이 또 하나의 진실 원천이 되므로,
    보정기가 유일한 쓰기 경로인 `irt_a` 컬럼 자체를 직전 상태로 읽는다(`calibrate_item_difficulties`
    docstring 참조 — 탈락 문항은 NULL로 되돌려지므로 이 값은 "직전 실행의 채택 수"와 같다).
    **보정 UPDATE보다 먼저 호출해야 한다** — 이후에 부르면 이번 실행의 결과를 직전으로 읽는다.
    """
    count = (
        await session.execute(
            select(func.count()).select_from(Problem).where(Problem.irt_a.isnot(None))
        )
    ).scalar_one()
    return int(count)


async def calibrate_item_difficulties(
    session: AsyncSession, *, dry_run: bool = False
) -> CalibrationReport:
    """채점된 전체 응답으로 문항 b(1PL)·a(2PL)를 보정해 `Problem`에 영속하고 리포트를 반환.

    `problem_attempt`(채점됨·학생·문항 식별 가능) 전수를 (학생, 문항, 정답)으로 모아
    `_compute_calibration`으로 계획을 세운 뒤:
      - a 채택 문항: `irt_a`와 **같은 2PL 적합의** b를 `irt_difficulty_b`에 UPDATE
      - b만 보정된 문항: 1PL b를 UPDATE하고 **`irt_a`를 NULL로 되돌린다** — 이전 실행에서
        채택됐다가 이번에 탈락한 문항의 낡은 a가 남으면, 소비측은 그 a를 "현재 보정값"으로
        읽는다(탈락 사실이 조용히 사라진다). `irt_a`의 쓰기 경로는 이 보정기가 유일하므로
        (EOS-129 착수 시점 실측·적재 데이터에도 irt_a 없음) NULL 복귀가 다른 원천을 지우지 않는다.

    `dry_run=True`면 UPDATE·commit을 **하나도** 하지 않는다 — 운영 DB에서 문항당 응답 분포와
    a 채택 가능 건수를 읽기 전용으로 재는 모드(EOS-129 acceptance ⑤). commit은 내부 수행
    (`mastery_tracking` 선례).
    """
    rows = (
        await session.execute(
            select(
                ProblemAttempt.user_id,
                ProblemAttempt.problem_id,
                ProblemAttempt.is_correct,
            ).where(
                ProblemAttempt.is_correct.isnot(None),
                ProblemAttempt.user_id.isnot(None),
                ProblemAttempt.problem_id.isnot(None),
            )
        )
    ).all()
    plan = _compute_calibration(
        [(user_id, problem_id, bool(is_correct)) for user_id, problem_id, is_correct in rows],
        dry_run=dry_run,
    )
    if dry_run:
        return plan.report
    for problem_id, b in plan.calibrated_b.items():
        fit = plan.adopted.get(problem_id)
        values: dict[str, float | None]
        if fit is not None:
            values = {"irt_difficulty_b": fit.difficulty, "irt_a": fit.discrimination}
        else:
            values = {"irt_difficulty_b": b, "irt_a": None}
        await session.execute(
            update(Problem).where(Problem.problem_id == problem_id).values(**values)
        )
    await session.commit()
    return plan.report


__all__ = [
    "A_CANDIDATE_BUCKETS",
    "FALLBACK_REASONS",
    "RESPONSE_COUNT_BUCKETS",
    "CalibrationReport",
    "calibrate_item_difficulties",
    "count_adopted_discrimination",
]
