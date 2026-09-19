"""MathSubjectAdapter — `SubjectAdapter` 계약의 수학 구현 (EOS-66 · Math Adapter Contract v1).

**이 모듈은 수학 로직을 한 줄도 새로 쓰지 않는다.** 전부 기존 함수 위임이다(계획서 006 §43
"전면 재작성 금지"). 하는 일은 두 가지뿐:

1. Core 중립 봉투(`schema.subject_adapter`) ↔ L3/L4 수학 타입의 **변환**
2. 수학 판정 함수로의 **디스패치**

위임 대상 3건 (2026-08-31 실측 경로):

| 계약 메서드 | 위임 대상 | 경로 |
|---|---|---|
| `evaluate_answer` | `verify_answer()` | `l3/verify_answer.py:272` |
| `detect_misconception` | `diagnose()` | `l4/misconception/diagnose.py:136` |
| `validate_problem` | `Verifier.verify()` | `l3/verifier.py:300` |

## 경계상의 위치

`docs/architecture/eos_core_adapter_boundary.md`의 배정에서 이 모듈은 **ADAPTER**다 — CORE인
`l4` 안에 살지만 배정은 파일 단위로 갈린다(선례: `l4.misconception.wrong_form_match`).
`BOUNDARY_MAP`에 그렇게 등재돼 있으므로, CORE 모듈이 이 파일을 import하면 EOS-67 계약이
위반으로 잡는다 — **그것이 의도다**. Core는 `schema.subject_adapter.SubjectAdapter`(Protocol)만
알아야 하고, 이 구현체는 조립 지점(DI)에서만 주입돼야 한다.

`l4`에 두는 이유: 계약상 `l3`(수학 검증)와 `l4.misconception`(오개념) 양쪽을 불러야 하는데,
7계층 단방향 계약에서 그 둘을 동시에 볼 수 있는 가장 낮은 자리가 `l4`다. 물리적
`subjects/math/` 이전은 전환 선언 §1.3-③이 보류한 범위라 여기서 하지 않는다.

## 집행 상태 (2026-08-31 EOS-69 실측)

이 파일은 필수 3종(`SubjectAdapter`) 외에 **선택적 능력 4종**을 함께 구현한다 — 항등 판정·
최종답 검증·평가 재료 답 검증·수식 봉인. 넷 다 `SubjectAdapter`에 넣지 않은 이유는 같다:
"이 능력이 Physics·Chemistry·History에도 **반드시** 존재하는가?"에 아니라고 답해야 하기
때문이다(인터페이스 분리 — `schema/verification_capabilities.py` 모듈 docstring).

경유 배선은 합성 루트(`whymath_backend.composition`)가 한다. Core는 이 파일의 이름을 모르고
좁은 Protocol만 알며, 기본 구현 선택이 사는 곳은 합성 루트 한 곳뿐이다. 경계 스캔 위반은
EOS-69 착수 시점 15건에서 이 배선 이후 실측치로 내려갔다(정확한 수는 태스크 acceptance 기재).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Sequence, cast

from whymath_backend.l3.equivalent.rephrase import classify_invariance_failure, extract_equation
from whymath_backend.l3.symbolic_equivalence import identity_status
from whymath_backend.l3.verifier import ProblemVerifyInput, Verifier
from whymath_backend.l3.verify_answer import AnswerVerdict, verify_answer
from whymath_backend.l3.verify_answer_form import form_verdict_for
from whymath_backend.l3.verify_final_answer import FinalAnswerResult, verify_final_answer
from whymath_backend.l3.verify_solution import verify_solution
from whymath_backend.l4.misconception.answer_signature import (
    AttemptMisconceptionScanResult,
    scan_attempt_answer,
)
from whymath_backend.l4.misconception.diagnose import diagnose
from whymath_backend.schema.answer_form import FormVerdict
from whymath_backend.schema.enums import StepType
from whymath_backend.schema.subject_adapter import (
    AnswerEvaluation,
    MisconceptionSignal,
    ProblemStatement,
    ProblemValidation,
    SubjectAdapter,
)
from whymath_backend.schema.verification_capabilities import (
    AnswerFormVerifier,
    AssessmentAnswerVerifier,
    AttemptMisconceptionDetector,
    ChainVerificationCounts,
    EquivalenceOutcome,
    ExpressionEquivalence,
    ExpressionSeal,
    FinalAnswerVerifier,
    StepChainVerifier,
)

_MACHINE_AXIS_NUMERIC = "numeric_substitution"
"""`verify_answer`가 닫는 축 이름 — 수치 대입 검산(Tier1).

Tier1은 *샘플 점에서의 만족*이지 증명이 아니다(`verify_answer` docstring 자인). 축 이름을
남기는 이유는 "무엇을 근거로 pass인가"가 판정과 함께 흘러야 하기 때문이다.
"""


class MathSubjectAdapter:
    """`SubjectAdapter` Protocol의 수학 구현 — 위임 전용.

    `Verifier`를 주입할 수 있다(교차검증기 결선 등 호출측 결정). 주입하지 않으면 기본
    `Verifier()`를 쓴다 — 그 경우 잔여 축은 교차검증 없이 `unverifiable`로 회피된다
    (보수적·거짓 pass 금지).
    """

    subject_id = "math"

    def __init__(self, *, verifier: Verifier | None = None) -> None:
        self._verifier = verifier if verifier is not None else Verifier()

    def evaluate_answer(
        self, problem: ProblemStatement, answer: Mapping[str, str]
    ) -> AnswerEvaluation:
        """`l3.verify_answer.verify_answer`에 위임하고 3상태를 그대로 옮긴다.

        상태를 재해석하지 않는다 — 특히 `unverifiable`을 `fail`로 접지 않는다(측정 실패를
        오답으로 위장 금지). `checked_axes`는 pass일 때만 채운다: fail·unverifiable에서
        "축을 닫았다"고 말하면 거짓이 된다.
        """
        verdict = verify_answer(problem.conditions, answer)
        return AnswerEvaluation(
            state=verdict.state,
            reason=verdict.reason,
            checked_axes=(_MACHINE_AXIS_NUMERIC,) if verdict.state == "pass" else (),
        )

    def detect_misconception(
        self, student_work: str, *, top_k: int = 3
    ) -> Sequence[MisconceptionSignal]:
        """`l4.misconception.diagnose.diagnose`에 위임하고 식별자·신뢰도만 추린다.

        오개념 *내용*(정의·반례·개입)은 의도적으로 버린다 — Core는 코드만 받고 필요할 때
        reactive 조회한다(구축 플레이북: 오개념 초기 context preload 금지).
        """
        return tuple(
            MisconceptionSignal(
                code=match.misconception.id,
                confidence=match.confidence,
                matched_signals=match.matched_signals + match.matched_regex_signals,
            )
            for match in diagnose(student_work, top_k=top_k)
        )

    async def validate_problem(self, problem: ProblemStatement) -> ProblemValidation:
        """`l3.verifier.Verifier.verify`(통합 수학 검증기 v2)에 위임한다.

        중립 봉투 → `ProblemVerifyInput` 변환이 이 메서드의 실질이다. `tier`·`audit_labels`는
        수학 검증 내부 개념이라 계약으로 넘기지 않는다 — 대신 닫힌 축/잔여 축만 넘긴다.
        """
        verdict = await self._verifier.verify(
            ProblemVerifyInput(
                slug=problem.problem_ref,
                question_text=problem.question_text,
                answer=problem.answer,
                answer_kind=problem.answer_kind,
                conditions=problem.conditions,
            )
        )
        return ProblemValidation(
            state=verdict.state,
            reason=verdict.reason,
            machine_axes=verdict.machine_axes,
            residual_axes=verdict.residual_axes,
        )


if TYPE_CHECKING:
    # 구조적 적합성 증명 — `mypy --strict`(CI backend 잡)가 이 대입을 검사한다.
    # 런타임 `isinstance`(runtime_checkable)는 *메서드 이름 존재*만 보고 시그니처를 보지
    # 않으므로, 인자·반환 타입까지 계약과 맞는지는 이 줄이 유일하게 잡는다.
    # 계약이 바뀌었는데 구현이 안 따라오면 여기서 CI가 적색이 된다.
    _CONFORMANCE_PROOF: SubjectAdapter = MathSubjectAdapter()


# ──────────────────────────────────────────────────────────────────────────
# 선택적 능력 — 항등 판정 (EOS-69)
# ──────────────────────────────────────────────────────────────────────────
class MathExpressionEquivalence:
    """`ExpressionEquivalence` 수학 구현 — SymPy 항등 판정으로 위임.

    `SubjectAdapter` 필수 3종에 넣지 않은 이유: 항등 판정은 역사·국어에 존재하지 않는다.
    필수로 만들면 그 과목들이 의미 없는 빈 구현을 강요당하고, 빈 구현은 곧 "판정했다"는
    거짓 신호가 된다(계약 모듈 docstring — 인터페이스 분리).

    **얇은 위임만 한다** — 판정 로직은 `symbolic_equivalence.identity_status`가 단일 권위다.
    여기서 상태를 재해석하지 않는다(4상태를 그대로 통과시킨다).
    """

    def identity_status(self, lhs: str, rhs: str) -> EquivalenceOutcome:
        """SymPy 4상태 판정 그대로 — 합치거나 승격하지 않는다."""
        return identity_status(lhs, rhs)


def math_expression_equivalence() -> MathExpressionEquivalence:
    """기본 주입용 팩토리 — Core의 배선 지점이 이 이름 하나만 알면 된다."""
    return MathExpressionEquivalence()


# ──────────────────────────────────────────────────────────────────────────
# 선택적 능력 — 최종답 검증 (EOS-69)
# ──────────────────────────────────────────────────────────────────────────
class MathFinalAnswerVerifier:
    """`FinalAnswerVerifier` 수학 구현 — `l3.verify_final_answer`로 위임.

    `problem`을 그대로 받아 넘긴다 — **기대정답을 꺼내지 않는다**. 정답이 이 클래스 안에서도
    변수에 담기지 않으므로 Core는 물론 어댑터 표면에도 노출 경로가 없다(계약 docstring).
    """

    def verify_final_answer(self, student_answer: str, problem: Any) -> FinalAnswerResult:
        """3상태 판정 그대로 반환 — 상태 재해석 없음."""
        return verify_final_answer(student_answer, problem)


def math_final_answer_verifier() -> MathFinalAnswerVerifier:
    """기본 주입용 팩토리."""
    return MathFinalAnswerVerifier()


# ──────────────────────────────────────────────────────────────────────────
# 선택적 능력 — 평가 재료 답 검증 (EOS-69)
# ──────────────────────────────────────────────────────────────────────────
class MathAssessmentAnswerVerifier:
    """`AssessmentAnswerVerifier` 수학 구현 — `l3.verify_answer`로 위임."""

    def verify_answer(
        self, conditions: Sequence[str], answer_map: Mapping[str, str]
    ) -> AnswerVerdict:
        """pass/fail/unverifiable 3상태 그대로 — 합치지 않는다."""
        return verify_answer(list(conditions), dict(answer_map))


def math_assessment_answer_verifier() -> MathAssessmentAnswerVerifier:
    """기본 주입용 팩토리."""
    return MathAssessmentAnswerVerifier()


# ──────────────────────────────────────────────────────────────────────────
# 선택적 능력 — 수식 봉인 (EOS-69)
# ──────────────────────────────────────────────────────────────────────────
class MathExpressionSeal:
    """`ExpressionSeal` 수학 구현 — 봉인 대상은 **방정식**이다(`l3.equivalent.rephrase`).

    Core(렌더 검증)는 "봉인 대상을 뽑아라 / 깨졌는지 말하라"만 알고, 그 대상이 방정식이라는
    사실은 여기서만 안다. 역사 어댑터라면 같은 두 메서드로 인용 원문을 봉인할 것이다.
    """

    def extract_sealed(self, source: str) -> str | None:
        """본문에서 방정식을 뽑는다 — 없으면 None(검사 대상 아님)."""
        return extract_equation(source)

    def classify_invariance_failure(self, rendered: str, *, sealed: str) -> str | None:
        """봉인(방정식)이 깨졌으면 사유 코드, 지켜졌으면 None."""
        return classify_invariance_failure(rendered, equation=sealed)


def math_expression_seal() -> MathExpressionSeal:
    """기본 주입용 팩토리."""
    return MathExpressionSeal()


# ──────────────────────────────────────────────────────────────────────────
# 선택적 능력 — 답 표기 형태 판정 (EOS-28)
# ──────────────────────────────────────────────────────────────────────────
class MathAnswerFormVerifier:
    """`AnswerFormVerifier` 수학 구현 — 형태 어휘(기약분수 등)가 수학 소유임을 여기서만 안다."""

    def verify_answer_form(self, student_answer: str | None, answer_constraint: Any) -> FormVerdict:
        """4상태 판정 그대로 — 값 판정에 영향을 주지 않는다."""
        return form_verdict_for(student_answer, answer_constraint)


def math_answer_form_verifier() -> MathAnswerFormVerifier:
    """기본 주입용 팩토리."""
    return MathAnswerFormVerifier()


# ──────────────────────────────────────────────────────────────────────────
# 선택적 능력 — 풀이 단계 연쇄 검증 (EOS-86)
# ──────────────────────────────────────────────────────────────────────────
class MathStepChainVerifier:
    """`StepChainVerifier` 수학 구현 — `l3.verify_solution.verify_solution`으로 위임.

    `SolutionVerificationResult`는 이미 `ChainVerificationCounts`(→`ChainVerification`)
    구조적 적합성을 갖는다(`l3/verify_solution.py`의 `_counts_conformance` 증명 — 설계
    규칙 1: 중간 변환 객체 금지). 여기서도 상태를 재해석하지 않고 그대로 반환한다.
    """

    def verify_chain(
        self, steps: Sequence[str], step_types: Sequence[Any] | None = None
    ) -> ChainVerificationCounts:
        """전이별 연쇄 검증 그대로 — 4상태(correct/incorrect/unverifiable) 재해석 없음."""
        typed = cast("Sequence[StepType | None] | None", step_types)
        return verify_solution(steps, typed)


def math_step_chain_verifier() -> MathStepChainVerifier:
    """기본 주입용 팩토리."""
    return MathStepChainVerifier()


class MathAttemptMisconceptionDetector:
    """`AttemptMisconceptionDetector` 수학 구현 — `l4.misconception.answer_signature`로 위임.

    "문항 식과 제출 답을 이어 거짓 항등식을 읽는다"는 것이 **수학 고유의 독법**임을 아는 곳이
    여기 하나다. Core는 `question_text`·`student_answer`를 불투명 문자열로 넘길 뿐이다.

    변환 없음(설계 규칙 1): `AttemptMisconceptionScanResult`가 `scan`·`candidates`를 그대로
    갖고 있어 Protocol을 **구조적으로** 만족한다 — 중간 변환 객체를 두지 않는다.
    """

    def scan_attempt_answer(
        self, *, question_text: str, student_answer: str | None
    ) -> AttemptMisconceptionScanResult:
        """오답 1건의 오개념 훑기 — 판정·게이트는 전부 위임(재구현 0)."""
        return scan_attempt_answer(question_text=question_text, student_answer=student_answer)


def math_attempt_misconception_detector() -> MathAttemptMisconceptionDetector:
    """기본 주입용 팩토리."""
    return MathAttemptMisconceptionDetector()


if TYPE_CHECKING:
    # 구조적 적합성 증명 — SubjectAdapter와 동일 패턴(mypy --strict가 검사).
    _EQUIVALENCE_CONFORMANCE: ExpressionEquivalence = MathExpressionEquivalence()
    _FINAL_ANSWER_CONFORMANCE: FinalAnswerVerifier = MathFinalAnswerVerifier()
    _ASSESSMENT_CONFORMANCE: AssessmentAnswerVerifier = MathAssessmentAnswerVerifier()
    _SEAL_CONFORMANCE: ExpressionSeal = MathExpressionSeal()
    _ANSWER_FORM_CONFORMANCE: AnswerFormVerifier = MathAnswerFormVerifier()
    _STEP_CHAIN_CONFORMANCE: StepChainVerifier = MathStepChainVerifier()
    _ATTEMPT_MISCONCEPTION_CONFORMANCE: AttemptMisconceptionDetector = (
        MathAttemptMisconceptionDetector()
    )
