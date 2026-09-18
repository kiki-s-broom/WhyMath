"""과목 능력 7종을 app.state에 **등록(push)**하고 라우터가 조회하는 자리 — EOS-89·COMP-01.

────────────────────────────────────────────────────────────────────────────
왜 이 모듈이 필요한가 (계획서 100 §3.8)
────────────────────────────────────────────────────────────────────────────
§3.8이 "덜 정확하다"고 한 형태는 **Core가 합성 루트에서 기본 구현을 끌어오는 것**(pull)이다.
`api/coach.py`가 `composition.default_final_answer_verifier()`를 직접 부르면, Core는 구현체를
모르더라도 *합성 루트를 이름으로 안다*. 방향은 여전히 Core → 배선이다.

권장 형태는 그 반대다: **Application이 부팅 시 능력을 Core에 등록하고, Core는 인터페이스 타입만
안다**(`EOS Core → Subject Interface ← Math Adapter`). 이 모듈은 그 등록의 *주소*(app.state 키)와
*조회*(Depends)를 한곳에 모은다 — `api/_l3_state.py`(provider·cache·trace·queue)와 같은 house
style이며, 이유도 같다: 라우터가 `app.py`를 import하면 순환이다(app.py가 라우터를 include한다).

────────────────────────────────────────────────────────────────────────────
경계
────────────────────────────────────────────────────────────────────────────
- 이 모듈은 **인터페이스 타입만** 안다(`schema/verification_capabilities.py`). 어느 과목 구현이
  올라오는지는 `app.py`(Application·합성 루트 소비자)만 안다.
- 조회는 `getattr(request.app.state, KEY)`다 — 키가 없으면 `AttributeError`로 **터진다**.
  기본값 폴백을 두지 않는 이유: 폴백이 있으면 등록이 빠져도 조용히 돌아가고, 그 순간
  "등록 형태"라는 주장이 거짓이 된다(침묵 실패 금지).
"""

from __future__ import annotations

from fastapi import Request

from whymath_backend.schema.verification_capabilities import (
    AnswerFormVerifier,
    AssessmentAnswerVerifier,
    AttemptMisconceptionDetector,
    ExpressionEquivalence,
    ExpressionSeal,
    FinalAnswerVerifier,
    StepChainVerifier,
)

# app.state 속성 키 — create_app(app.py)이 저장하고 아래 getter가 조회(문자열 단일 출처).
# 접두사 `subject_`는 "과목 교체 시 함께 바뀌는 값"이라는 표시다(provider·cache 등 과목 무관
# 인프라 키와 구분).
EXPRESSION_EQUIVALENCE_KEY = "subject_expression_equivalence"
FINAL_ANSWER_VERIFIER_KEY = "subject_final_answer_verifier"
ASSESSMENT_ANSWER_VERIFIER_KEY = "subject_assessment_answer_verifier"
EXPRESSION_SEAL_KEY = "subject_expression_seal"
ANSWER_FORM_VERIFIER_KEY = "subject_answer_form_verifier"
STEP_CHAIN_VERIFIER_KEY = "subject_step_chain_verifier"
ATTEMPT_MISCONCEPTION_DETECTOR_KEY = "subject_attempt_misconception_detector"

# 등록되어야 하는 과목 능력 키 전체 — 테스트가 "등록 7종 존재"를 이 집합으로 대조한다.
# EOS-89가 남긴 요청("EOS-86의 `StepChainVerifier` 팩토리가 착지하면 여기에 키를 더하고 app.py
# 등록을 늘린다")을 COMP-01이 이행했다 — `STEP_CHAIN_VERIFIER_KEY`가 그 6번째다. 이 집합에
# 키를 더하는 것이 강제 장치인 이유: `tests/infra/test_eos_dependency_direction.py`가 이 집합을
# 읽어 app.py 등록 줄과 대조하므로, 키만 더하고 등록을 빼면 RED가 난다(조용한 누락 차단).
SUBJECT_CAPABILITY_KEYS: frozenset[str] = frozenset(
    {
        EXPRESSION_EQUIVALENCE_KEY,
        FINAL_ANSWER_VERIFIER_KEY,
        ASSESSMENT_ANSWER_VERIFIER_KEY,
        EXPRESSION_SEAL_KEY,
        ANSWER_FORM_VERIFIER_KEY,
        STEP_CHAIN_VERIFIER_KEY,
        # EOS-104: 오답 1건 → 오개념 후보. 7번째이며 같은 강제 장치를 그대로 받는다.
        ATTEMPT_MISCONCEPTION_DETECTOR_KEY,
    }
)


def get_expression_equivalence(request: Request) -> ExpressionEquivalence:
    """요청의 app.state에서 식 항등 판정 능력을 꺼낸다(create_app 등록)."""
    capability: ExpressionEquivalence = getattr(request.app.state, EXPRESSION_EQUIVALENCE_KEY)
    return capability


def get_final_answer_verifier(request: Request) -> FinalAnswerVerifier:
    """요청의 app.state에서 최종답 3상태 판정 능력을 꺼낸다."""
    capability: FinalAnswerVerifier = getattr(request.app.state, FINAL_ANSWER_VERIFIER_KEY)
    return capability


def get_assessment_answer_verifier(request: Request) -> AssessmentAnswerVerifier:
    """요청의 app.state에서 평가 재료 답↔조건 대조 능력을 꺼낸다."""
    capability: AssessmentAnswerVerifier = getattr(
        request.app.state, ASSESSMENT_ANSWER_VERIFIER_KEY
    )
    return capability


def get_expression_seal(request: Request) -> ExpressionSeal:
    """요청의 app.state에서 수식 봉인(추출·불변 판정) 능력을 꺼낸다."""
    capability: ExpressionSeal = getattr(request.app.state, EXPRESSION_SEAL_KEY)
    return capability


def get_answer_form_verifier(request: Request) -> AnswerFormVerifier:
    """요청의 app.state에서 답 형태 지시 준수 판정 능력을 꺼낸다."""
    capability: AnswerFormVerifier = getattr(request.app.state, ANSWER_FORM_VERIFIER_KEY)
    return capability


def get_step_chain_verifier(request: Request) -> StepChainVerifier:
    """요청의 app.state에서 풀이 단계 연쇄 검증 능력을 꺼낸다(COMP-01).

    다른 5종과 **같은 규약**이다(폴백 없는 `getattr` — 등록 누락은 `AttributeError`로 터진다).
    이 능력은 계약상 *선택적*이라(`StepChainVerifier` docstring — 제공하지 않는 과목이 정상)
    Core에는 미주입 경로가 남아 있지만, 그 선택권은 **과목 배선의 것**이지 등록 누락의 알리바이가
    아니다. 수학이 구현을 갖고 있는 한 서빙 경로는 항상 등록분을 쓴다.
    """
    capability: StepChainVerifier = getattr(request.app.state, STEP_CHAIN_VERIFIER_KEY)
    return capability


def get_attempt_misconception_detector(request: Request) -> AttemptMisconceptionDetector:
    """요청의 app.state에서 오답 서명 → 오개념 후보 검출 능력을 꺼낸다(EOS-104).

    다른 6종과 **같은 규약**이다(폴백 없는 `getattr` — 등록 누락은 `AttributeError`로 터진다).
    이 능력도 계약상 *선택적*이지만, 선택권은 **과목 배선의 것**이지 등록 누락의 알리바이가
    아니다. 과목이 이 능력을 제공하지 않기로 했다면 그 사실이 `app.py`에 보여야 하고, 그때
    채점 경로는 `MisconceptionScan.NOT_RUN`으로 "훑지 않았다"를 고지한다.
    """
    capability: AttemptMisconceptionDetector = getattr(
        request.app.state, ATTEMPT_MISCONCEPTION_DETECTOR_KEY
    )
    return capability
