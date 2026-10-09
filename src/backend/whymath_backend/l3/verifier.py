"""통합 수학 검증기 v2 contract — S4-54 구현.

S4-13 v1이 확률 유한 전수형을 닫았다면, v2는 검증 진입점을 단일화하고 SymPy 불가 영역을
도메인 verifier 플러그인으로 확장하는 contract다.

변경 요약(S4-54):
- 기존 `_CONCEPTUAL_VERIFIERS`(SymPy/통계/기하/벡터 판정)를 `_DomainResult`로 래핑해 등록.
- `_VERIFIERS_V2`에 신규 도메인(geometric_discrete, statistical_claim 등)을 추가할 수 있는
  플러그인 구조를 마련하고, 기존 키와의 중복은 구성 시점에 거부.
- 기계 검증 후 남은 `residual_axes`가 있고 `cross_verifier`가 주입되면 `ResidueSubject`를
  구성해 독립 다관점 LLM 교차검증을 연결. 주입되지 않으면 보수적으로 `unverifiable` 회피.

계층: L3 지역. L4만 호출한다(import-linter). DB·LLM 0 — 필요한 경우 cross_verify를
주입받아 잔여 축을 검증.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l3.cross_verify import (
    PROBABILITY_PERSPECTIVES,
    STATISTICAL_PERSPECTIVES,
    CrossVerifier,
    Perspective,
    ResidueSubject,
)
from whymath_backend.l3.equivalent.acceptance import _CONCEPTUAL_VERIFIERS
from whymath_backend.l3.finite_probability import (
    describe_model_ko,
    enumerate_model,
    parse_finite_model,
    verify_finite_count,
    verify_finite_probability,
)
from whymath_backend.l3.statistical_claim import (
    describe_statistical_model_ko,
    parse_statistical_model,
    verify_statistical_claim,
)
from whymath_backend.l3.verification_tier import VerificationTier
from whymath_backend.l3.verify_answer import AnswerVerdict

__all__ = [
    "ProblemVerifyInput",
    "VerificationVerdict",
    "Verifier",
]


class ProblemVerifyInput(BaseModel):
    """검증에 필요한 최소 입력 — `ProblemDSL` 전체가 아니라 verify 절 계약만 노출.

    L3 내부 타입이다. `schema/problem.py`의 `Problem`을 직접 받지 않아 계층 의존을
    최소화한다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    slug: str
    question_text: str
    answer: str
    answer_kind: str
    conditions: str
    answer_explanation: str = ""
    authored_by: str = "unknown"


class VerificationVerdict(BaseModel):
    """통합 verifier의 최종 판정 — state + 등급 + 증명/잔여 축 + 감사 라벨.

    `state`는 3상태. `tier`는 "증명된 축의 집합"을 표현. `machine_axes`는 기계가 닫은 축,
    `residual_axes`는 기계가 닫지 못한 축(교차검증/인간 폴백 대상).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["pass", "fail", "unverifiable"] = Field(
        description="최종 판정 — pass(기계+잔여 ok), fail(결함), unverifiable(측정 불가)."
    )
    tier: VerificationTier = Field(description="검증 등급 — '증명된 축의 집합'을 표현.")
    machine_axes: tuple[str, ...] = Field(
        default_factory=tuple,
        description="기계로 닫힌 축 목록.",
    )
    residual_axes: tuple[str, ...] = Field(
        default_factory=tuple,
        description="기계가 닫지 못한 잔여 축 목록.",
    )
    reason: str | None = Field(
        default=None,
        description="fail/unverifiable 사유(학생 비노출).",
    )
    audit_labels: list[str] = Field(
        default_factory=list,
        description="잔여 교차검증 감사 라벨 식별자(문자열).",
    )


@dataclass(frozen=True, slots=True)
class _DomainResult:
    """개별 도메인 verifier의 결과 — Verifier가 VerificationVerdict로 래핑하는 재료.

    `residual_axes`는 기계가 닫지 못한 축. `machine_axes`는 기계가 닫은 축.
    `cross_subject`는 잔여 교차검증에 필요한 재료로, 해당 도메인에서만 의미가 있다.
    """

    verdict: AnswerVerdict
    machine_axes: tuple[str, ...]
    residual_axes: tuple[str, ...]
    machine_total: int = 0
    machine_favorable: int = 0
    machine_model_ko: str = ""
    machine_value: float | None = None


DomainVerifier = Callable[[str, str], _DomainResult]

# 도메인별 교차검증 관점 — 기본값은 확률 유한 전수형 관점.
_CROSS_VERIFY_PERSPECTIVES: dict[str, tuple[Perspective, ...]] = {
    "statistical_claim": STATISTICAL_PERSPECTIVES,
}


# ──────────────────────────────────────────────────────────────────────────
# 기존 S4-13 v1 도메인 verifier 래퍼 — 유한 표본공간 전수 열거
# ──────────────────────────────────────────────────────────────────────────
def _verify_finite_probability_pair(conditions: str, answer: str) -> _DomainResult:
    """finite_probability → _DomainResult + 잔여 축 + 교차검증 재료."""
    verdict = verify_finite_probability(conditions, answer)
    residual = (
        "문발↔형식모델 정합",
        "등확률 가정",
    )
    machine_total = verdict.samples_checked
    machine_favorable = 0
    machine_model_ko = ""
    if verdict.state == "pass":
        try:
            model = parse_finite_model(conditions)
            result = enumerate_model(model)
            machine_total = result.total
            machine_favorable = result.favorable
            machine_model_ko = describe_model_ko(model, result)
        except Exception:  # noqa: BLE001 — 교차검증 재료가 없어도 기계 검증 결과는 유효
            machine_model_ko = ""
    return _DomainResult(
        verdict=verdict,
        machine_axes=("유한 표본공간 전수 열거",),
        residual_axes=residual,
        machine_total=machine_total,
        machine_favorable=machine_favorable,
        machine_model_ko=machine_model_ko,
    )


def _verify_finite_count_pair(conditions: str, answer: str) -> _DomainResult:
    """finite_count → _DomainResult + 잔여 축.

    finite_count는 경우의 수(카드)만 세므로 등확률 가정에 의존하지 않는다.
    """
    verdict = verify_finite_count(conditions, answer)
    machine_total = verdict.samples_checked
    machine_favorable = 0
    machine_model_ko = ""
    if verdict.state == "pass":
        try:
            model = parse_finite_model(conditions)
            result = enumerate_model(model)
            machine_total = result.total
            machine_favorable = result.favorable
            machine_model_ko = describe_model_ko(model, result)
        except Exception:  # noqa: BLE001
            machine_model_ko = ""
    return _DomainResult(
        verdict=verdict,
        machine_axes=("유한 경우의 수 전수 열거",),
        residual_axes=("문발↔형식모델 정합",),
        machine_total=machine_total,
        machine_favorable=machine_favorable,
        machine_model_ko=machine_model_ko,
    )


# ──────────────────────────────────────────────────────────────────────────
# 통계 자료형 verifier 래퍼 — SymPy 불가 영역 v2 실증 도메인(S4-53)
# ──────────────────────────────────────────────────────────────────────────
def _verify_statistical_claim_pair(conditions: str, answer: str) -> _DomainResult:
    """statistical_claim → _DomainResult + 잔여 축 + 교차검증 재료."""
    verdict, residual_axes, result = verify_statistical_claim(conditions, answer)
    machine_model_ko = ""
    machine_value: float | None = None
    if verdict.state == "pass":
        try:
            model = parse_statistical_model(conditions)
            machine_model_ko = describe_statistical_model_ko(model, result)
            machine_value = result.value
        except Exception:  # noqa: BLE001 — 교차검증 재료가 없어도 기계 검증 결과는 유효
            machine_model_ko = ""
    return _DomainResult(
        verdict=verdict,
        machine_axes=("통계량 전수 결정론 검산",),
        residual_axes=residual_axes,
        machine_model_ko=machine_model_ko,
        machine_value=machine_value,
    )


# ──────────────────────────────────────────────────────────────────────────
# 기존 `_CONCEPTUAL_VERIFIERS` → _DomainResult 래퍼
# ──────────────────────────────────────────────────────────────────────────
def _wrap_conceptual_verifier(
    fn: Callable[[str, str], AnswerVerdict],
    *,
    machine_axis: str,
    residual_axis: str = "발문↔SymPy 조건 정합",
) -> DomainVerifier:
    """SymPy/통계/기하/벡터 판정 함수를 _DomainResult로 래핑."""

    def _verify(conditions: str, answer: str) -> _DomainResult:
        verdict = fn(conditions, answer)
        return _DomainResult(
            verdict=verdict,
            machine_axes=(machine_axis,),
            residual_axes=(residual_axis,) if verdict.state == "pass" else (),
        )

    return _verify


# 기존 _CONCEPTUAL_VERIFIERS를 _VERIFIERS_V2 형태로 래핑.
# machine_axis는 도메인별로 다르게 표현할 수 있지만, S4-54에서는 SymPy 기반/도메인 프리미티브로
# 구분. S4-55 이후 tier 세분화와 함께 정밀화 가능.
_SYMPTY_BASED_KINDS: frozenset[str] = frozenset(
    {
        "real_root_count",
        "extremum_count",
        "is_one_to_one",
        "geometric_convergence",
        "limit_equals_value",
        "is_differentiable",
        "series_converges",
        "excluded_point_count",
        "root_loss_count",
        "verify_root_aggregate",
    }
)


def _machine_axis_for(kind: str) -> str:
    if kind in _SYMPTY_BASED_KINDS:
        return "SymPy 기호/수치 검산"
    return "도메인 프리미티브 판정"


# ──────────────────────────────────────────────────────────────────────────
# 도메인 verifier 플러그인 등록
# ──────────────────────────────────────────────────────────────────────────
def _build_verifiers_v2() -> dict[str, DomainVerifier]:
    """기존 `_CONCEPTUAL_VERIFIERS`를 `_DomainResult`로 래핑해 통합 테이블 구성.

    `finite_probability`/`finite_count`는 유한 전수형, `statistical_claim`은 통계
    자료형이라 별도 래퍼를 쓰고, 나머지는 `_wrap_conceptual_verifier`로 래핑.
    중복 키는 즉시 거부.
    """
    verifiers: dict[str, DomainVerifier] = {}
    verifiers["statistical_claim"] = _verify_statistical_claim_pair
    for kind, fn in _CONCEPTUAL_VERIFIERS.items():
        if kind == "finite_probability":
            verifiers[kind] = _verify_finite_probability_pair
        elif kind == "finite_count":
            verifiers[kind] = _verify_finite_count_pair
        elif kind in verifiers:
            raise ValueError(f"answer_kind={kind!r}가 중복 등록")
        else:
            verifiers[kind] = _wrap_conceptual_verifier(
                fn,
                machine_axis=_machine_axis_for(kind),
            )
    return verifiers


_VERIFIERS_V2: dict[str, DomainVerifier] = _build_verifiers_v2()


# ──────────────────────────────────────────────────────────────────────────
# 통합 Verifier
# ──────────────────────────────────────────────────────────────────────────
class Verifier:
    """통합 verifier v2 — 도메인 디스패치 + 잔여 축 식별 + 교차검증 연결."""

    def __init__(self, *, cross_verifier: CrossVerifier | None = None) -> None:
        self._cross_verifier = cross_verifier

    async def verify(self, problem: ProblemVerifyInput) -> VerificationVerdict:
        """통합 검증 진입점.

        1. answer_kind로 도메인 verifier 디스패치.
        2. 기계 검증 결과 + 잔여 축 획득.
        3. fail이면 즉시 fail.
        4. unverifiable이면서 잔여 축이 없으면 unverifiable.
        5. 잔여 축이 있으면 cross_verifier가 있을 때 교차검증, 없으면 unverifiable 회피.
        """
        verifier = _VERIFIERS_V2.get(problem.answer_kind)
        if verifier is None:
            return VerificationVerdict(
                state="unverifiable",
                tier=VerificationTier.MACHINE_SAMPLED,
                reason=f"answer_kind={problem.answer_kind!r}에 등록된 verifier가 없음(v2 미구현)",
            )

        domain_result = verifier(problem.conditions, problem.answer)
        verdict = domain_result.verdict

        if verdict.state == "fail":
            return VerificationVerdict(
                state="fail",
                tier=VerificationTier.MACHINE_SAMPLED,
                machine_axes=domain_result.machine_axes,
                residual_axes=domain_result.residual_axes,
                reason=verdict.reason or "기계 검증 실패",
            )

        if verdict.state == "unverifiable":
            if not domain_result.residual_axes:
                return VerificationVerdict(
                    state="unverifiable",
                    tier=VerificationTier.MACHINE_SAMPLED,
                    reason=verdict.reason or "기계 검증 불가",
                )
            return VerificationVerdict(
                state="unverifiable",
                tier=VerificationTier.MACHINE_SAMPLED,
                machine_axes=domain_result.machine_axes,
                residual_axes=domain_result.residual_axes,
                reason=verdict.reason or "기계 검증 불가, 잔여 축 남음",
            )

        # pass: 잔여 축이 없으면 완전 기계 검증, 있으면 교차검증 필요.
        if not domain_result.residual_axes:
            return VerificationVerdict(
                state="pass",
                tier=VerificationTier.MACHINE_EXHAUSTIVE,
                machine_axes=domain_result.machine_axes,
            )

        # 잔여 축이 있는데 cross_verifier가 없으면 보수적 회피.
        if self._cross_verifier is None:
            return VerificationVerdict(
                state="unverifiable",
                tier=VerificationTier.MACHINE_EXHAUSTIVE,
                machine_axes=domain_result.machine_axes,
                residual_axes=domain_result.residual_axes,
                reason="잔여 축이 있으나 cross_verifier가 주입되지 않음",
            )

        return await self._run_cross_verify(problem, domain_result)

    async def _run_cross_verify(
        self, problem: ProblemVerifyInput, domain_result: _DomainResult
    ) -> VerificationVerdict:
        """잔여 축에 대해 독립 다관점 LLM 교차검증을 실행하고 결과를 VerificationVerdict로 변환."""
        assert (
            self._cross_verifier is not None
        ), "_run_cross_verify는 cross_verifier가 있을 때만 호출"
        subject = ResidueSubject(
            problem_id=problem.slug,
            question_text=problem.question_text,
            answer=problem.answer,
            answer_explanation=problem.answer_explanation,
            machine_model_ko=domain_result.machine_model_ko,
            machine_total=domain_result.machine_total,
            machine_favorable=domain_result.machine_favorable,
            machine_value=domain_result.machine_value,
            authored_by=problem.authored_by,
            data=problem.conditions,
        )
        perspectives = _CROSS_VERIFY_PERSPECTIVES.get(problem.answer_kind, PROBABILITY_PERSPECTIVES)
        cross_result = await asyncio.to_thread(self._cross_verifier.verify, subject, perspectives)
        audit_labels = [f"cross_verify:{cross_result.aggregate}"]

        if cross_result.aggregate == "ok":
            return VerificationVerdict(
                state="pass",
                tier=VerificationTier.MACHINE_EXHAUSTIVE,
                machine_axes=domain_result.machine_axes,
                residual_axes=domain_result.residual_axes,
                audit_labels=audit_labels,
            )
        if cross_result.aggregate == "defect":
            return VerificationVerdict(
                state="fail",
                tier=VerificationTier.MACHINE_EXHAUSTIVE,
                machine_axes=domain_result.machine_axes,
                residual_axes=domain_result.residual_axes,
                reason=f"잔여 교차검증 결함: {cross_result.reason}",
                audit_labels=audit_labels,
            )
        return VerificationVerdict(
            state="unverifiable",
            tier=VerificationTier.MACHINE_EXHAUSTIVE,
            machine_axes=domain_result.machine_axes,
            residual_axes=domain_result.residual_axes,
            reason=f"잔여 교차검증 미결정: {cross_result.reason}",
            audit_labels=audit_labels,
        )
