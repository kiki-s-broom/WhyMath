"""합성 루트(composition root) — 과목 능력 계약의 **기본 구현 배선 지점** (EOS-69).

────────────────────────────────────────────────────────────────────────────
왜 이 모듈이 필요한가
────────────────────────────────────────────────────────────────────────────
`schema/verification_capabilities.py`가 Core가 아는 **좁은 능력 계약**(Protocol)을 정의하고,
`l4/subject_adapter_math.py`가 그 계약의 수학 구현을 제공한다. 남은 문제는 *누가 둘을 잇는가*다.

Core 모듈이 스스로 기본 구현을 import하면(예: `slot_generator`가 `math_expression_equivalence`를
직접 부르면) 계약을 도입한 의미가 사라진다 — 함수 안에서 import해도 경계 스캔·import-linter는
그 간선을 그대로 본다. 계약은 있는데 Core가 여전히 수학 어댑터를 *이름으로* 안다.

그래서 배선을 한 곳으로 모은다. 이 모듈은 **횡단 인프라(INFRA)**다:
  - Core는 이 모듈을 부를 수 있다(CORE → INFRA는 경계 위반이 아니다).
  - 이 모듈은 어댑터를 알아도 된다(INFRA는 경계 계약의 대상이 아니다).

────────────────────────────────────────────────────────────────────────────
이 모듈이 지켜야 하는 3규칙 (어기면 "라벨만 INFRA인 Core"가 된다)
────────────────────────────────────────────────────────────────────────────
1. **판정 로직 금지** — 여기에는 조립(어느 구현을 쓸지)만 둔다. 수학·교수학 판단이 한 줄이라도
   들어오면 그 순간 이 파일은 어댑터이며 INFRA 배정이 거짓말이 된다.
2. **지연 import** — 어댑터 import는 함수 안에서 한다. 모듈 상단에서 하면 `whymath_backend`를
   import하는 모든 경로가 SymPy를 끌고 들어온다(기동 비용·과목 미설치 시 ImportError).
3. **팩토리만 노출** — 구현 클래스를 re-export하지 않는다. 소비자가 `composition`을 통해
   구현 타입을 이름으로 알게 되면 1번 규칙이 우회된다.

────────────────────────────────────────────────────────────────────────────
정직한 한계
────────────────────────────────────────────────────────────────────────────
Physics·국어를 붙일 때 **이 파일은 고쳐야 한다** — 그것이 합성 루트의 정의다(과목 선택이
사는 유일한 곳). "고치지 않아도 되는 모듈"이라는 CORE 기준을 이 파일은 만족하지 않으며,
그래서 CORE가 아니라 INFRA다. 경계의 목적은 *변경 지점을 없애는 것*이 아니라 **한 곳으로
모으는 것**이다. 현재는 수학 단일 과목이라 분기가 없다 — 과목 셀렉터는 두 번째 과목이
실재할 때 도입한다(소비처 0 추상 금기).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from whymath_backend.schema.verification_capabilities import (
        AnswerFormVerifier,
        AssessmentAnswerVerifier,
        AttemptMisconceptionDetector,
        ExpressionEquivalence,
        ExpressionSeal,
        FinalAnswerVerifier,
        StepChainVerifier,
    )

__all__ = [
    "default_answer_form_verifier",
    "default_attempt_misconception_detector",
    "default_assessment_answer_verifier",
    "default_expression_equivalence",
    "default_expression_seal",
    "default_final_answer_verifier",
    "default_step_chain_verifier",
    "default_wrong_form_shadow_observer",
]


def default_expression_equivalence() -> ExpressionEquivalence:
    """`ExpressionEquivalence`(식 항등 판정)의 기본 구현을 준다.

    호출자가 자기 구현을 주입하면(테스트 더블·타 과목) 이 함수는 아예 실행되지 않는다.
    지연 import인 이유는 모듈 docstring 규칙 2번 참조.
    """
    from whymath_backend.l4.subject_adapter_math import math_expression_equivalence

    return math_expression_equivalence()


def default_final_answer_verifier() -> FinalAnswerVerifier:
    """`FinalAnswerVerifier`(학생 최종답 3상태 판정)의 기본 구현을 준다."""
    from whymath_backend.l4.subject_adapter_math import math_final_answer_verifier

    return math_final_answer_verifier()


def default_assessment_answer_verifier() -> AssessmentAnswerVerifier:
    """`AssessmentAnswerVerifier`(평가 재료 답↔조건 대조)의 기본 구현을 준다."""
    from whymath_backend.l4.subject_adapter_math import math_assessment_answer_verifier

    return math_assessment_answer_verifier()


def default_expression_seal() -> ExpressionSeal:
    """`ExpressionSeal`(본문 수식 봉인 검사)의 기본 구현을 준다."""
    from whymath_backend.l4.subject_adapter_math import math_expression_seal

    return math_expression_seal()


def default_answer_form_verifier() -> AnswerFormVerifier:
    """`AnswerFormVerifier`(제출답의 표기 지시 준수 판정)의 기본 구현을 준다."""
    from whymath_backend.l4.subject_adapter_math import math_answer_form_verifier

    return math_answer_form_verifier()


def default_step_chain_verifier() -> StepChainVerifier:
    """`StepChainVerifier`(풀이 단계 연쇄 검증)의 기본 구현을 준다."""
    from whymath_backend.l4.subject_adapter_math import math_step_chain_verifier

    return math_step_chain_verifier()


def default_wrong_form_shadow_observer() -> Callable[[str], None]:
    """오개념 거짓 항등식 SymPy shadow 관측(fire-and-forget)의 기본 구현을 준다.

    `verification_capabilities.py`의 Protocol 계약이 아니라 콜러블 하나다 — 관측기는 값을
    돌려주지 않고 로그로만 sink하므로(비노출·비차단) 능력 계약으로 분리할 상태가 없다. 그래도
    구현(`l4.misconception.wrong_form_match`)은 ADAPTER이므로 이 파일을 통해서만 조회한다
    (그래야 solution_coaching이 이 모듈 하나만 알면 된다 — 규칙 1·3 그대로 적용).
    """
    from whymath_backend.l4.misconception.wrong_form_match import observe_wrong_form_shadow

    return observe_wrong_form_shadow


def default_attempt_misconception_detector() -> AttemptMisconceptionDetector:
    """`AttemptMisconceptionDetector`(오답 1건 → 오개념 후보)의 기본 구현을 준다.

    Core(채점 핸들러)가 `l4.misconception.answer_signature`를 *이름으로* 알면 경계 위반이다 —
    함수 안 import여도 경계 스캔은 그 간선을 본다. 그래서 이 팩토리 하나만 알게 한다.

    과목이 이 능력을 제공하지 않으면 호출자는 훑지 않은 것으로 처리한다
    (`MisconceptionScan.NOT_RUN`) — 능력 부재를 "오개념 없음"으로 접지 않는다.
    """
    from whymath_backend.l4.subject_adapter_math import math_attempt_misconception_detector

    return math_attempt_misconception_detector()
