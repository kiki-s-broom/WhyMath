"""S4-65 ④ — `MathSubjectAdapter.validate_problem`의 저작 서명 주입점.

배경: Core 봉투 `ProblemStatement`는 필드가 동결돼 서명 좌석이 없고, 어댑터는 `authored_by`를 넘기지
않아 `ProblemVerifyInput`의 기본값(`UNRECORDED_AUTHOR`)이 그대로 쓰였다. 교차검증기가 주입된
`Verifier`는 그 값을 생성자≠검증자 가드로 거부한다(PB-15). 그래서 서명은 호출측이 어댑터 생성자에
`author_resolver`로 넣어 주는 자리로만 들어온다.

검증 축:
  ① resolver가 있으면 그 서명이 `ProblemVerifyInput.authored_by`로 닫힌다.
  ② resolver가 없으면 서명을 지어내지 않는다 — 기본값 `UNRECORDED_AUTHOR` 그대로.
  ③ 실제 가드(`assert_author_independent`)를 통과시키는 종단: 서명 없는 호출은 거부, 있는 호출은 통과.
  ④ 봉투 `ProblemStatement`의 필드는 늘지 않는다(동결 불변 — 이 슬라이스가 건드리지 않았다).

변별력: resolver 연결을 지우면 ①이, 서명 기본값을 어댑터가 채우면 ②가, 가드를 우회하면 ③이 RED다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l3.cross_verify import (
    UNRECORDED_AUTHOR,
    CrossVerificationResult,
    IndependenceError,
    Perspective,
    ResidueSubject,
    assert_author_independent,
    deterministic_author,
    llm_author,
)
from whymath_backend.l3.verifier import ProblemVerifyInput, VerificationVerdict, Verifier
from whymath_backend.l4.subject_adapter_math import MathSubjectAdapter
from whymath_backend.schema.subject_adapter import ProblemStatement

_DICE = "space=dice(n=2,faces=6); event=sum==7"


def _statement(ref: str = "p-1") -> ProblemStatement:
    return ProblemStatement(
        problem_ref=ref,
        question_text="주사위 두 개의 합이 7일 확률은?",
        answer="1/6",
        answer_kind="finite_probability",
        conditions=_DICE,
    )


class _CapturingVerifier(Verifier):
    """`verify`에 들어온 입력을 기록하는 `Verifier` — 판정 자체는 부모에 위임한다."""

    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[ProblemVerifyInput] = []

    async def verify(self, problem: ProblemVerifyInput) -> VerificationVerdict:
        self.inputs.append(problem)
        return await super().verify(problem)


class _GuardedCrossVerifier:
    """실제 교차검증기와 같은 첫 줄(생성자≠검증자 가드)을 거치는 대역.

    진짜 `CrossVerifier.verify`는 첫 줄에서 `assert_author_independent(subject.authored_by,
    self.signature)`를 부른다. `signature`는 라우터·설정이 필요해 단위 테스트에서 못 만들므로
    검증자 서명만 고정하고 **가드 함수는 진짜를 그대로 쓴다**.
    """

    signature = llm_author("verifier-model")

    def __init__(self) -> None:
        self.calls = 0

    def verify(
        self,
        subject: ResidueSubject,
        perspectives: tuple[Perspective, ...] | None = None,
    ) -> CrossVerificationResult:
        del perspectives
        assert_author_independent(subject.authored_by, self.signature)
        self.calls += 1
        return CrossVerificationResult(
            problem_id=subject.problem_id,
            verdicts=(),
            aggregate="ok",
            defect_class="",
            reason="guarded-fake",
        )


# ── ① resolver가 있으면 서명이 닫힌다 ─────────────────────────────────────
@pytest.mark.asyncio
async def test_resolver_signature_reaches_the_verifier_input() -> None:
    capturing = _CapturingVerifier()
    seen: list[str] = []

    def resolver(problem: ProblemStatement) -> str:
        seen.append(problem.problem_ref)
        return deterministic_author("dice-generator")

    adapter = MathSubjectAdapter(verifier=capturing, author_resolver=resolver)
    await adapter.validate_problem(_statement("p-42"))

    assert seen == ["p-42"]  # 문항을 받아 서명을 정한다(문항마다 다를 수 있다)
    assert [i.authored_by for i in capturing.inputs] == ["deterministic:dice-generator"]


# ── ② resolver가 없으면 서명을 지어내지 않는다 ────────────────────────────
@pytest.mark.asyncio
async def test_without_resolver_the_default_unrecorded_signature_is_kept() -> None:
    capturing = _CapturingVerifier()
    await MathSubjectAdapter(verifier=capturing).validate_problem(_statement())
    assert [i.authored_by for i in capturing.inputs] == [UNRECORDED_AUTHOR]


# ── ③ 실제 가드와의 종단 ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_unsigned_call_is_rejected_by_the_independence_guard() -> None:
    """서명 없는 호출은 교차검증기 주입 시 가드가 거부한다 — 어댑터가 조용히 통과시키지 않는다."""
    adapter = MathSubjectAdapter(
        verifier=Verifier(cross_verifier=_GuardedCrossVerifier())  # type: ignore[arg-type]
    )
    with pytest.raises(IndependenceError):
        await adapter.validate_problem(_statement())


@pytest.mark.asyncio
async def test_signed_call_passes_the_guard_and_reaches_cross_verification() -> None:
    guarded = _GuardedCrossVerifier()
    adapter = MathSubjectAdapter(
        verifier=Verifier(cross_verifier=guarded),  # type: ignore[arg-type]
        author_resolver=lambda _p: deterministic_author("dice-generator"),
    )
    result = await adapter.validate_problem(_statement())
    assert guarded.calls == 1
    assert result.state == "pass"
    assert result.residual_axes  # 잔여 축은 응답에 그대로 남는다


@pytest.mark.asyncio
async def test_same_model_author_is_still_rejected_as_self_approval() -> None:
    """resolver가 검증자와 같은 LLM 서명을 주면 가드가 자기승인으로 거부한다(주입점이 가드를 약화하지 않는다)."""
    adapter = MathSubjectAdapter(
        verifier=Verifier(cross_verifier=_GuardedCrossVerifier()),  # type: ignore[arg-type]
        author_resolver=lambda _p: llm_author("verifier-model"),
    )
    with pytest.raises(IndependenceError):
        await adapter.validate_problem(_statement())


# ── ④ Core 봉투는 늘지 않았다 ────────────────────────────────────────────
def test_core_envelope_fields_are_unchanged() -> None:
    assert set(ProblemStatement.model_fields) == {
        "problem_ref",
        "question_text",
        "answer",
        "answer_kind",
        "conditions",
    }
