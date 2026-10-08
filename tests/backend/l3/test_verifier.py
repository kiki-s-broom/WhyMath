"""S4-54 — 통합 Verifier v2 contract 단위 테스트.

검증 축:
  ① answer_kind 미등록 시 `unverifiable`로 회피.
  ② `_CONCEPTUAL_VERIFIERS`에 등록된 기존 도메인도 `VerificationVerdict`로 래핑.
  ③ 기계 검증 `pass` 후 잔여 축이 있으면 cross_verifier 없이는 `unverifiable`.
  ④ cross_verifier 주입 시 `ResidueSubject`로 연결되고 집계 결과가 state를 결정.
  ⑤ finite_probability/count는 `machine_model_ko` 등 교차검증 재료를 채운다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l3 import verifier as verifier_module
from whymath_backend.l3.cross_verify import (
    PROBABILITY_PERSPECTIVES,
    STATISTICAL_PERSPECTIVES,
    CrossVerificationResult,
    Perspective,
    ResidueSubject,
    ResidueVerdictLabel,
)
from whymath_backend.l3.verification_tier import VerificationTier
from whymath_backend.l3.verifier import ProblemVerifyInput, Verifier


class _FakeCrossVerifier:
    """cross_verifier 대역 — ResidueSubject를 기록하고 미리 정한 aggregate를 반환."""

    def __init__(self, aggregate: ResidueVerdictLabel) -> None:
        self.aggregate = aggregate
        self.subjects: list[ResidueSubject] = []
        self.perspectives: list[tuple[Perspective, ...] | None] = []

    def verify(
        self,
        subject: ResidueSubject,
        perspectives: tuple[Perspective, ...] | None = None,
    ) -> CrossVerificationResult:
        self.subjects.append(subject)
        self.perspectives.append(perspectives)
        return CrossVerificationResult(
            problem_id=subject.problem_id,
            verdicts=(),
            aggregate=self.aggregate,
            defect_class="",
            reason="fake cross-verification",
        )


def _problem(answer_kind: str, answer: str, conditions: str) -> ProblemVerifyInput:
    return ProblemVerifyInput(
        slug=f"test-{answer_kind}",
        question_text="테스트 발문",
        answer=answer,
        answer_kind=answer_kind,
        conditions=conditions,
        answer_explanation="테스트 해설",
        authored_by="corpus:TEST",
    )


@pytest.mark.asyncio
async def test_unknown_answer_kind_returns_unverifiable() -> None:
    verifier = Verifier()
    problem = _problem("not_registered_kind", "1", "x=1")
    verdict = await verifier.verify(problem)
    assert verdict.state == "unverifiable"
    assert "not_registered_kind" in (verdict.reason or "")
    assert verdict.tier == VerificationTier.MACHINE_SAMPLED


@pytest.mark.asyncio
async def test_finite_probability_pass_without_cross_verifier_is_unverifiable() -> None:
    """잔여 축이 있는데 cross_verifier가 없으면 보수적 회피."""
    verifier = Verifier()
    problem = _problem(
        "finite_probability",
        "1/6",
        "space=dice(n=2,faces=6); event=sum==7",
    )
    verdict = await verifier.verify(problem)
    assert verdict.state == "unverifiable"
    assert verdict.tier == VerificationTier.MACHINE_EXHAUSTIVE
    assert "유한 표본공간 전수 열거" in verdict.machine_axes
    assert "문발↔형식모델 정합" in verdict.residual_axes
    assert "cross_verifier" in (verdict.reason or "")


@pytest.mark.asyncio
async def test_finite_probability_fail_returns_fail() -> None:
    verifier = Verifier()
    problem = _problem(
        "finite_probability",
        "1/3",  # 오답
        "space=dice(n=2,faces=6); event=sum==7",
    )
    verdict = await verifier.verify(problem)
    assert verdict.state == "fail"
    assert verdict.tier == VerificationTier.MACHINE_SAMPLED
    assert "전수 열거 결과" in (verdict.reason or "")


@pytest.mark.asyncio
async def test_finite_count_pass_without_cross_verifier_is_unverifiable() -> None:
    verifier = Verifier()
    problem = _problem(
        "finite_count",
        "6",
        "space=dice(n=2,faces=6); event=sum==7",
    )
    verdict = await verifier.verify(problem)
    assert verdict.state == "unverifiable"
    assert "유한 경우의 수 전수 열거" in verdict.machine_axes


@pytest.mark.asyncio
async def test_conceptual_verifier_pass_has_residual_axes() -> None:
    """기존 _CONCEPTUAL_VERIFIERS 함수(real_root_count)도 등록되고 잔여 축을 남긴다."""
    verifier = Verifier()
    problem = _problem(
        "real_root_count",
        "2",
        "x**2 - 1 = 0",
    )
    verdict = await verifier.verify(problem)
    assert verdict.state == "unverifiable"
    assert "SymPy 기호/수치 검산" in verdict.machine_axes
    assert "발문↔SymPy 조건 정합" in verdict.residual_axes


@pytest.mark.asyncio
async def test_cross_verifier_ok_makes_pass() -> None:
    fake = _FakeCrossVerifier("ok")
    verifier = Verifier(cross_verifier=fake)  # type: ignore[arg-type]
    problem = _problem(
        "finite_probability",
        "1/6",
        "space=dice(n=2,faces=6); event=sum==7",
    )
    verdict = await verifier.verify(problem)
    assert verdict.state == "pass"
    assert len(fake.subjects) == 1
    assert fake.subjects[0].problem_id == problem.slug
    assert "cross_verify:ok" in verdict.audit_labels


@pytest.mark.asyncio
async def test_cross_verifier_defect_makes_fail() -> None:
    fake = _FakeCrossVerifier("defect")
    verifier = Verifier(cross_verifier=fake)  # type: ignore[arg-type]
    problem = _problem(
        "finite_probability",
        "1/6",
        "space=dice(n=2,faces=6); event=sum==7",
    )
    verdict = await verifier.verify(problem)
    assert verdict.state == "fail"
    assert "결함" in (verdict.reason or "")


@pytest.mark.asyncio
async def test_cross_verifier_unclear_makes_unverifiable() -> None:
    fake = _FakeCrossVerifier("unclear")
    verifier = Verifier(cross_verifier=fake)  # type: ignore[arg-type]
    problem = _problem(
        "finite_probability",
        "1/6",
        "space=dice(n=2,faces=6); event=sum==7",
    )
    verdict = await verifier.verify(problem)
    assert verdict.state == "unverifiable"
    assert "미결정" in (verdict.reason or "")


@pytest.mark.asyncio
async def test_cross_verifier_receives_machine_model_ko() -> None:
    fake = _FakeCrossVerifier("ok")
    verifier = Verifier(cross_verifier=fake)  # type: ignore[arg-type]
    problem = _problem(
        "finite_probability",
        "1/6",
        "space=dice(n=2,faces=6); event=sum==7",
    )
    await verifier.verify(problem)
    subject = fake.subjects[0]
    assert subject.machine_total == 36
    assert subject.machine_favorable == 6
    assert "주사위" in subject.machine_model_ko
    assert problem.answer in subject.answer


@pytest.mark.asyncio
async def test_statistical_claim_pass_without_cross_verifier_is_unverifiable() -> None:
    """통계 자료형도 기계 검증 후 잔여 축이 있으면 cross_verifier 없이는 unverifiable."""
    verifier = Verifier()
    problem = _problem(
        "statistical_claim",
        "3",
        "data=[1,2,3,4,5]; stat=mean",
    )
    verdict = await verifier.verify(problem)
    assert verdict.state == "unverifiable"
    assert verdict.tier == VerificationTier.MACHINE_EXHAUSTIVE
    assert "통계량 전수 결정론 검산" in verdict.machine_axes
    assert "자료↔발문 정합" in verdict.residual_axes


@pytest.mark.asyncio
async def test_statistical_claim_fail_returns_fail() -> None:
    verifier = Verifier()
    problem = _problem(
        "statistical_claim",
        "99",
        "data=[1,2,3,4,5]; stat=mean",
    )
    verdict = await verifier.verify(problem)
    assert verdict.state == "fail"
    assert verdict.tier == VerificationTier.MACHINE_SAMPLED
    assert "불일치" in (verdict.reason or "")


@pytest.mark.asyncio
async def test_statistical_claim_cross_verifier_receives_data_and_machine_value() -> None:
    fake = _FakeCrossVerifier("ok")
    verifier = Verifier(cross_verifier=fake)  # type: ignore[arg-type]
    problem = _problem(
        "statistical_claim",
        "3",
        "data=[1,2,3,4,5]; stat=mean",
    )
    await verifier.verify(problem)
    subject = fake.subjects[0]
    assert subject.data == problem.conditions
    assert subject.machine_value == pytest.approx(3.0)
    assert "평균" in subject.machine_model_ko


@pytest.mark.asyncio
async def test_kind_without_perspective_set_is_unverifiable_even_with_cross_verifier() -> None:
    """관점 세트가 없는 kind(SymPy 개념형)는 확률형 관점으로 대신 채점하지 않는다.

    교차검증기가 `ok`를 돌려줄 대역이어도 호출 자체가 일어나지 않아야 거짓 pass가 없다.
    """
    fake = _FakeCrossVerifier("ok")
    verifier = Verifier(cross_verifier=fake)  # type: ignore[arg-type]
    verdict = await verifier.verify(_problem("real_root_count", "2", "x**2 - 1 = 0"))
    assert verdict.state == "unverifiable"
    assert "관점 세트" in (verdict.reason or "")
    assert "SymPy 기호/수치 검산" in verdict.machine_axes
    assert "발문↔SymPy 조건 정합" in verdict.residual_axes
    assert fake.subjects == []  # 교차검증기를 부르지 않았다.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer_kind", "answer", "conditions", "expected"),
    [
        (
            "finite_probability",
            "1/6",
            "space=dice(n=2,faces=6); event=sum==7",
            PROBABILITY_PERSPECTIVES,
        ),
        ("finite_count", "6", "space=dice(n=2,faces=6); event=sum==7", PROBABILITY_PERSPECTIVES),
        ("statistical_claim", "3", "data=[1,2,3,4,5]; stat=mean", STATISTICAL_PERSPECTIVES),
    ],
)
async def test_cross_verifier_receives_domain_perspective_set(
    answer_kind: str,
    answer: str,
    conditions: str,
    expected: tuple[Perspective, ...],
) -> None:
    """도메인마다 정의된 관점 세트가 교차검증기에 그대로 전달된다."""
    fake = _FakeCrossVerifier("ok")
    verifier = Verifier(cross_verifier=fake)  # type: ignore[arg-type]
    await verifier.verify(_problem(answer_kind, answer, conditions))
    assert fake.perspectives == [expected]


def test_duplicate_answer_kind_is_rejected_at_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """신규 도메인 kind가 기존 `_CONCEPTUAL_VERIFIERS`와 겹치면 구성 시점에 거부(설계서 §3.3)."""
    conceptual = verifier_module._CONCEPTUAL_VERIFIERS
    monkeypatch.setitem(conceptual, "statistical_claim", conceptual["real_root_count"])
    with pytest.raises(ValueError, match="중복"):
        verifier_module._build_verifiers_v2()


def test_perspective_table_has_no_unregistered_kind() -> None:
    """관점 세트 표에 등록되지 않은 kind가 없다 — 도달 불가능한 죽은 항목을 막는다."""
    assert set(verifier_module._CROSS_VERIFY_PERSPECTIVES) <= set(verifier_module._VERIFIERS_V2)
