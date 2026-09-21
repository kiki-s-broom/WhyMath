"""L3→L4 오케스트레이터 — 학생 풀이 계산오류(L3 결정론 검증) → L4 검산 코칭 처방.

slice 51이 `recommend_coaching`에 `arithmetic_error` 신호를 받을 자리를 만들었으나
*미결선*이었고(L4 함수는 bool 받을 준비만), 본 모듈이 그 **결선**이다 — L3의 결정론 관계
검증기(=·<·>·≤·≥·≠, slice 36~46)를 *학생 풀이 텍스트*에 적용해 "2+3=6" 같은 계산 슬립을
검출하고, 그 bool을 L4 `recommend_coaching`에 전달한다.

레이어 경계(CLAUDE.md "L_n은 L_{n-1}을 *호출*할 수 있지만 *구현*하지 않는다"): L4(교수학
결정)가 L3 도구(`validate_response`)를 *호출*해 신호를 얻고, *순수* L4 결정 함수
(`recommend_coaching`)에 bool로 넘긴다. SymPy 검증을 재구현하지 않으며(L3 책임),
`recommend_coaching` 자체는 L3를 모르는 순수 함수로 남는다(slice 51 "L4는 원시 신호만 받음").
*본 오케스트레이터만* 양쪽 계층을 안다(이미 `l4.models`가 `l3.models`를 import하는 기존
L4→L3 결합과 동형).

비차단·보수적: 검증기는 *거짓이 증명된* 수치 관계만 신호로 내고(심볼릭·파싱 불가·빈 풀이는
통과), 신호가 없으면 기존 BKT↔IRT 기반 코칭으로 자연 폴백한다(slice 51 backward-compat).
답을 *직접* 주지 않는 검산 유도가 목적이다(CLAUDE.md 답 미루기 원칙).

WH-1 1단계 결선: `solution_steps`(L5가 분해한 단계 시퀀스)가 제공되면 `verify_solution`을
호출해 *단계별(전이별)* 검증을 추가한다. 단계 레벨 신호는 기존 텍스트 레벨 신호와 **추가적
(OR)** 으로 결합돼 검산 코칭을 정밀화하되 기존 신호를 *약화하지 않는다*. 단계 미제공 시
모든 기존 동작이 *완전 불변*이다(하위호환). 텍스트→단계 *분해*(NLP)는 L5 OCR·공간정보
책임으로 본 모듈 범위 밖 — 백엔드는 제공된 단계만 검증한다.

WH-1 1단계 OCR 신뢰 게이팅: `ocr_confidence`(L5 OCR 인식 신뢰도)가 낮으면 분해 단계 텍스트
자체가 *오인식*일 수 있어, `verify_solution`이 낸 step-incorrect가 *학생 오류가 아니라 OCR
오류*일 수 있다. 이때 학생의 옳은 풀이를 거짓 지적하는 정확성 위반을 막으려고, 저신뢰 OCR일
때 step 신호를 코칭 *결정*에서 누그러뜨린다(`step_incorrect_trusted`·위치 비지목). 게이팅은
*오케스트레이터*만 수행하고 `verify_solution`은 순수(판정 불변)로 유지한다. 보류 사실은
`verification_ocr_gated`로 정직히 노출하고 원 verdict(`solution_verification`)는 투명성 위해
그대로 노출한다. 텍스트 레벨 신호(`validate_response`)는 OCR 분해와 무관해 게이팅하지 않는다.
임계는 match_gate 게이트 ②(0.8)와 단일 출처를 공유한다(일관성).

EOS-86 MIXED 분해 — 단계 연쇄 검증은 `l3.verify_solution` 직접 import 대신 `StepChainVerifier`
(schema/verification_capabilities.py) 선택층 계약을 통해 주입받는다. `recommend_coaching_
for_solution(..., verifier=...)`을 주입하지 않으면 합성 루트(`composition.
default_step_chain_verifier`)의 기본 구현(수학)으로 지연 폴백한다. **[COMP-01] 프로덕션
경로(`api/coach.py` 3핸들러)는 app.state 등록분을 명시 주입하므로 그 폴백을 타지 않는다** —
남은 폴백은 이 함수를 직접 부르는 단위테스트용이며, 그래서 이 모듈은 여전히 `composition`을
import한다(`CORE_PULL_BASELINE` 미축소의 사유 — 함수 본문 주석 참조). `observe_wrong_form_shadow`
호출도 같은 이유로 합성 루트(`composition.default_wrong_form_shadow_observer`)를 경유한다 —
이 파일이 더 이상 `l3.verify_solution`·`l4.misconception.wrong_form_match`(둘 다 ADAPTER)를
직접 알지 못하게 하면서, CORE에서 그 두 모듈로 직접 닿던 경로였던 잔여 누수 2건(`api.coach`·
`api.ocr_handoff` 경유)을 없앤다(합성 루트는 설계된 유일 교체점 —
`docs/architecture/eos_core_adapter_boundary.md` §4).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l3.pregenerate.models import ValidationSignalKind
from whymath_backend.l3.pregenerate.validator import (
    SeedValidator,
    arithmetic_validator,
    validate_response,
)
from whymath_backend.l4.hint_deferral import HintLevel
from whymath_backend.l4.metacognitive_trigger import CoachingTrigger, recommend_coaching
from whymath_backend.l4.misconception.match_gate import _DEFAULT_OCR_THRESHOLD
from whymath_backend.l4.step_shadow import observe_step_breaks
from whymath_backend.schema.enums import StepType
from whymath_backend.schema.verification_capabilities import (
    ChainVerificationCounts,
    StepChainVerifier,
)

# OCR 신뢰도 하한 — match_gate 게이트 ②(§3.3)와 *단일 출처* 공유(임계 일관성). 이 미만이면
# 분해 단계 텍스트 자체가 OCR 오인식일 수 있어, verify_solution이 낸 step-incorrect 신호를
# 코칭 *결정*에서 누그러뜨린다(거짓 지적 방지·정확성 #1). 새 임계를 도입하지 않는다.
_OCR_THRESHOLD = _DEFAULT_OCR_THRESHOLD

SlipKind = ValidationSignalKind
"""검출된 슬립 종류 — L3 `ValidationSignalKind`와 동일 도메인(별칭). L5 UI 분기·L7 분석용.

L4 public 계약 보존용 별칭이다(`l4/__init__`·`api/coach`가 재노출). 종류는 검증기가
*직접* 선언한다(slice 59 — `_classify_slip` 산문 접두사 파싱 제거).

- `arithmetic`: 거짓 수치 등식("2+3=6") · `inequality`: 거짓 부등식("5<3")
- `not_equal`: 거짓 부등("12/4≠3") · `solution`: 틀린 방정식 해("2x+1=7 → x=5")
- `other`: 위 종류 외(예: 위생 신호 — BasicSeedValidator·주입 검증기).
"""


class SolutionCoaching(BaseModel):
    """학생 풀이 기반 코칭 결정 — 코칭 트리거 + 계산오류 신호. 불변(frozen).

    `trigger`는 항상 채워진다(`recommend_coaching`은 항상 결정 반환). `arithmetic_error`가
    True면 `trigger.focus == "verify"`(검산)이고 `validation_signal`에 *구체적 거짓 관계*가
    담긴다(예: "arithmetic error: '2 + 3 = 6' (sympy: 5 != 6)") — L5가 학생에게 검산 코칭과
    함께 *어디가 어긋났는지* 단서로 쓸 수 있다(단, 정답을 직접 주지 않음, CLAUDE.md).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trigger: CoachingTrigger = Field(description="L4 메타인지 코칭 결정(focus·근거·발화).")
    arithmetic_error: bool = Field(
        description="학생 풀이에서 거짓 수치 관계(=·<·>·≤·≥·≠)가 결정론으로 검출됐는가."
    )
    validation_signal: str | None = Field(
        default=None,
        description=(
            "검출된 거짓 관계 사유(L3 검증기 출력). None=계산오류 없음(통과·심볼릭·빈 풀이). "
            "trace의 validation_signal과 같은 형식(slice 40·50)."
        ),
    )
    error_kind: SlipKind | None = Field(
        default=None,
        description=(
            "검출된 슬립 종류(arithmetic·inequality·not_equal·solution·other) — None=오류 "
            "없음. L3 검증기가 `ValidationSignal.kind`로 *직접* 선언한 값(slice 59 — 산문 신호 "
            "파싱 제거)으로, L5가 종류별 코칭 UI를, L7이 오류 유형 분석을 할 수 있게 한다."
        ),
    )
    error_span: tuple[int, int] | None = Field(
        default=None,
        description=(
            "틀린 관계/해주장의 학생 풀이 원문 내 위치 `[start, end)`(0-based·half-open·JSON "
            "배열). None=위치 미상(오류 없음·위생 신호·유니코드 부등호 정규화로 오프셋 시프트). "
            "L5가 학생 풀이에서 *어디가 틀렸는지* 하이라이트하는 데 쓴다(slice 60 — "
            "`ValidationSignal.span` 노출)."
        ),
    )
    solution_verification: Any = Field(
        default=None,
        description=(
            "L5가 *분해한 단계 시퀀스*(`solution_steps`)를 주입된 `StepChainVerifier`(기본: 수학 "
            "구현·`verify_solution` 위임)로 연쇄 검증한 결과(상태 카운트·`unverified_ratio`·"
            "`first_incorrect_index`·`has_incorrect`) — 런타임 형태는 `ChainVerificationCounts` "
            "(schema/verification_capabilities.py)를 만족한다. "
            "단계 미제공 시 None(텍스트 레벨 폴백 — 기존 동작 완전 불변). **노출 안전**: 입력은 "
            "*학생 자신의 단계*이고 `verify_step`의 `reason`('동치 아님 — SymPy: before ≠ "
            "after')은 검증 사유일 뿐 정답/본문이 아니다(verify_step은 정답을 알지도 못함). "
            "단계 레벨 incorrect는 텍스트 신호와 *추가적(OR)*으로 결합돼 검산 코칭을 정밀화한다. "
            "**투명성**: 이 필드는 *원 verdict*를 그대로 노출한다 — 저신뢰 OCR로 코칭 결정에서 "
            "보류돼도(`verification_ocr_gated`) `has_incorrect`/`first_incorrect_index`는 "
            "verify_solution이 낸 값 그대로다(조용히 숨기지 않음). "
            "**타입이 `Any`인 이유(EOS-86 실측)**: 정적 타입은 `ChainVerificationCounts`(Protocol)"
            "여야 계약에 정직하지만, Pydantic이 그 타입으로 `model_json_schema()`를 시도하면 "
            "`PydanticInvalidForJsonSchema`(IsInstanceSchema)로 **하드 크래시**한다(OpenAPI "
            "생성이 앱 기동을 막는다 — 실측 확인). 런타임 직렬화(`model_dump(mode='json')`)는 "
            "구체 타입(`SolutionVerificationResult`)이 이미 pydantic 모델이라 정상 동작하므로, "
            "OpenAPI 크래시를 피하려고 `Any`로 낮췄다 — 대가는 **OpenAPI 스키마가 이 필드를 "
            "불투명 객체로 광고**한다는 것이다(중첩 필드 구조가 스펙에서 사라짐 — Flutter "
            "codegen이 강타입 모델 대신 `dynamic`/`Map`으로 받는다). 필드가 실려 나가는 값 자체는 "
            "이전과 바이트 동일하다 — 바뀐 것은 *스펙에 적힌 모양*뿐이다."
        ),
    )
    verification_ocr_gated: bool = Field(
        default=False,
        description=(
            "WH-1 1단계 — `verify_solution`이 step-incorrect를 냈으나 OCR 신뢰도가 낮아"
            "(<0.8·match_gate 게이트 ② 임계 공유) 코칭 *결정*에서 그 신호를 *보류*했는지 여부. "
            "True면 분해 단계 텍스트 자체가 OCR 오인식일 수 있어(예: '(a+b)³'를 '(a+b)²'로 오독) "
            "verify의 incorrect가 *학생 오류가 아니라 OCR 오류*일 가능성이 있다 — 학생의 옳은 "
            "풀이를 거짓 지적하지 않으려고(정확성 #1·'틀렸다 정서 강화 금지') step 신호를 verify "
            "코칭에서 누그러뜨리고 위치도 지목하지 않는다. L5는 이 플래그를 보고 *OCR 재확인 후* "
            "다시 판단하라(재확인 UX). `solution_verification`(원 verdict)은 투명성 위해 그대로 "
            "노출되고, 텍스트 레벨 신호(`validation_signal`)는 OCR 분해와 무관해 게이팅되지 "
            "않는다. OCR 미제공(None)·고신뢰(≥0.8)·step-incorrect 없음이면 항상 False(동작 불변)."
        ),
    )


def recommend_coaching_for_solution(
    student_solution: str,
    bkt_mastery: float | None,
    irt_theta: float | None,
    *,
    problem_id: uuid.UUID | None = None,
    expected_answer: str | None = None,
    validator: SeedValidator | None = None,
    solution_steps: Sequence[str] | None = None,
    solution_step_types: Sequence[StepType | None] | None = None,
    ocr_confidence: float | None = None,
    hint_level: HintLevel | None = None,
    discrepancy_tol: float = 0.2,
    mastery_threshold: float = 0.6,
    verifier: StepChainVerifier | None = None,
) -> SolutionCoaching:
    """학생 풀이 + L2 두 신호 → 코칭 처방. L3 결정론 검증을 거쳐 검산 코칭을 우선한다.

    ① L3 도구(`validate_response`)로 풀이의 *거짓 수치 관계*를 검출한다(기본 검증기는
    `arithmetic_validator` — 위생 검사 없이 SymPy 관계 검증기만). ② 신호 유무를
    `arithmetic_error` bool로 환산. ③ L4 *순수* 결정 `recommend_coaching`에 전달 —
    계산오류면 `verify`(검산)를 최우선으로, 아니면 BKT↔IRT 기반 코칭(slice 51 우선순위).

    `validator`를 주입하면 다른 결정론 검증기(예: 향후 방정식 풀이 검증)를 끼울 수 있다.
    순수·결정론(같은 입력 → 같은 결정). `student_solution`이 비었거나 심볼릭이면 신호가
    없어 자연히 BKT↔IRT 경로로 폴백한다(false positive 0·보수적). `discrepancy_tol`·
    `mastery_threshold`는 `recommend_coaching`에 그대로 위임한다.

    **단계 결선(WH-1 1단계 · EOS-86 재배선)**: `solution_steps`가 제공되고 전이가 1개 이상(즉
    len≥2)이면 `verifier.verify_chain(solution_steps, solution_step_types)`로 *L5가 분해한 단계
    시퀀스*를 연쇄 검증한다(텍스트→단계 *분해*는 L5 OCR·공간정보 책임으로 본 함수 범위 밖 —
    백엔드는 제공된 단계만 검증). `verifier`가 주어지면 **그것을 쓰고**, 주어지지 않을 때만 합성
    루트(`composition.default_step_chain_verifier`)의 기본 구현(수학 — `l3.verify_solution`
    위임)으로 지연 폴백한다(COMP-01: 서빙 3경로는 전부 명시 주입이라 폴백을 타지 않는다 — 본문
    주석에 확인 방법 2가지). 이 파일은 `l3.verify_solution`을 더 이상 알지 못한다(CORE→ADAPTER
    직접 의존 제거·EOS-84/86). 신호 결합은 **추가적(OR)**으로, 기존 텍스트 레벨 신호를 *약화하지
    않는다*: `arithmetic_error = (텍스트 신호 있음) or verification.has_incorrect`·`verify_steps
    = (텍스트 신호가 kind="solution") or verification.has_incorrect`(단계 레벨 incorrect는
    *단계 자가검산* 프레이밍과 자연 정합). 이 bool들을 *그대로* 기존 `recommend_coaching`에
    넘긴다(결정 함수 시그니처·로직 불변). `solution_steps` 미제공·전이 0개면 `verification=None`·
    신호는 기존 텍스트 레벨 그대로 — **모든 기존 동작 완전 불변**(하위호환).

    **OCR 신뢰 게이팅(WH-1 1단계)**: `ocr_confidence`(0~1·L5 OCR 인식 신뢰도)가 제공되고
    `_OCR_THRESHOLD`(0.8·match_gate 게이트 ② 임계 공유) 미만이면(`ocr_low`), 분해 단계 텍스트
    자체가 OCR 오인식일 수 있어(예: "(a+b)³"를 "(a+b)²"로 오독) `verify_solution`이 낸
    step-incorrect 신호를 코칭 *결정*에서 누그러뜨린다 — 학생의 옳은 풀이를 거짓 지적하지
    않으려는 정확성 #1 가드(CLAUDE.md "틀렸다 정서 강화 금지"). 신뢰 게이팅:
    `step_incorrect_trusted = step_incorrect and not ocr_low`. 이 *신뢰분만* verify 신호 결합에
    반영하고(arithmetic_error·verify_steps·incorrect_step_index), 저신뢰 OCR이면 *위치도 지목하지
    않는다*(거짓 지적 방지). 보류 사실은 `verification_ocr_gated`(=`step_incorrect and ocr_low`)로
    노출한다 — L5가 *OCR 재확인 후* 다시 판단하라는 신호다(조용히 버리지 않음·정직). **텍스트
    레벨 신호는 게이팅하지 않는다**: `validate_response`(student_solution 텍스트 거짓 등식)는 OCR
    분해와 무관하므로 `signal` 경로는 *불변*이다(OCR 저신뢰여도 텍스트 거짓 등식은 유효). 게이팅은
    *step(verify_solution) 신호만*이다. `ocr_confidence` 미제공(None)이면 `ocr_low=False`라
    `step_incorrect_trusted == step_incorrect` — **모든 기존 동작 완전 불변**(하위호환).

    **redaction**: `verify_solution` 결과(`solution_verification`)의 `reason`('동치 아님 —
    SymPy: before ≠ after')은 *학생 자신의 단계*(solution_steps 입력)에 대한 검증 사유라
    노출이 안전하다 — 정답/본문이 아니다(`verify_step`은 정답을 알지도 못함). `SolutionCoaching`
    에 채워 L5가 단계별 검산 UI(has_incorrect·first_incorrect_index)를 그릴 수 있게 한다. 원
    verdict(`solution_verification`)는 저신뢰 OCR로 보류돼도 *투명성* 위해 그대로 노출한다 —
    코칭 *결정*엔 신뢰분(`step_incorrect_trusted`)만 반영하고 보류 사실은 플래그로 정직히 알린다.

    **hint 점층 결선(WH-1 1단계 잔여)**: `hint_level`(답 미루기 1~4·None이면 미적용)을 그대로
    `recommend_coaching`에 위임한다 — 오케스트레이터(api)가 *이미 계산한* Polya 결정의
    `decision.hint_level`(`decide_hint_level`·턴/좌절/숙달 기반)을 넘기면, *단계 자가검산*
    (verify_steps) 발화가 3·4단계에서 과정 재구성 비계로 점층된다(정답/"틀렸다" 미포함·답 미루기).
    재계산하지 않고 그대로 전달만 한다(L4 경계·이 함수는 hint 산정 책임 없음). 미제공(None)·
    verify_steps 아님이면 발화 불변(하위호환).

    `problem_id`·`expected_answer`(slice 64)는 *step shadow 진단 맥락*으로만 쓰여 반환
    `SolutionCoaching`을 *바꾸지 않는다*(비노출 불변). `expected_answer`는 호출자(api 계층)가
    서버 DB에서 조회해 넘기며 요청/응답엔 결코 싣지 않는다 — student-facing이면 정답 누출.
    """
    signal = validate_response(
        validator if validator is not None else arithmetic_validator(),
        student_solution,
    )
    # 단계 결선 — L5가 분해한 단계 시퀀스가 있고 전이가 1개 이상(len≥2)일 때만 검증 호출(분해는
    # L5 책임·범위 밖). 미제공·전이 0개면 None(기존 텍스트 레벨 동작 완전 불변).
    #
    # [COMP-01] **주어지면 그것을 쓰고, 주어지지 않을 때만 폴백한다.** 프로덕션 경로는 push
    # 주입이다 — `create_app`이 app.state에 올린 능력을 `api/coach.py`의 세 핸들러가
    # `_build_response_payload(step_chain_verifier=...)`로 명시 주입하므로, 서빙 중에는 아래
    # `if verifier is None` 분기가 **돌지 않는다**. 남은 폴백은 이 함수를 직접 호출하는 300+
    # 단위테스트 편의용이며, 지우면 그 전량이 verifier를 만들어 넘겨야 해 이 태스크 범위를 넘는다
    # (회귀 위험 > 이득 — COMP-01 acceptance ③ "유지 시 사유 문서화").
    #
    # 서빙 경로가 정말 주입을 쓰는지 확인하는 법(추론 금지·주입으로 확인):
    #   ① `tests/backend/api/test_coach.py::TestStepChainVerifierInjection` — 가짜 verifier를
    #      app.state에 올리고 `/v1/coach` 응답이 그 가짜의 판정을 담는지 본다. 명시 주입을
    #      빼면 이 테스트가 RED다(폴백이 진짜 수학 구현을 부르므로 가짜가 호출되지 않는다).
    #   ② 이 분기에 breakpoint/로그를 걸고 `/v1/coach`에 단계 2개 이상을 제출 — 걸리면 어딘가
    #      주입이 빠진 것이다.
    # 폴백이 남아 있으므로 이 모듈은 여전히 `composition`을 import하며(아래 관측기도 같다),
    # `CORE_PULL_BASELINE`에서 `l4.solution_coaching`은 **축소되지 않는다**.
    # verifier가 오든 폴백이든 이 모듈 자체는 l3.verify_solution을 모른다(EOS-86: CORE→ADAPTER
    # 직접 의존 제거. composition은 설계된 유일 교체점).
    verification: ChainVerificationCounts | None = None
    if solution_steps is not None and len(solution_steps) >= 2:
        if verifier is None:
            from whymath_backend.composition import default_step_chain_verifier

            verifier = default_step_chain_verifier()
        verification = verifier.verify_chain(solution_steps, solution_step_types)

    # WH-1 1단계 — OCR 신뢰 게이팅. ocr_confidence가 제공되고 임계(0.8·match_gate 공유) 미만이면
    # 분해 단계 텍스트가 OCR 오인식일 수 있어 step 신호를 코칭 결정에서 누그러뜨린다(정확성 #1).
    # 미제공(None)이면 ocr_low=False → step_incorrect_trusted == step_incorrect(기존 동작 불변).
    ocr_low = ocr_confidence is not None and ocr_confidence < _OCR_THRESHOLD
    # `has_incorrect`는 ChainVerificationCounts 계약(schema/verification_capabilities.py)에
    # 없는 구체 타입(SolutionVerificationResult)의 편의 필드다 — 계약에 있는
    # first_incorrect_index로 동치 계산한다(`has_incorrect == (first_incorrect_index is not
    # None)`이 그 필드의 정의).
    step_incorrect = verification is not None and verification.first_incorrect_index is not None
    # 신뢰분 — 저신뢰 OCR이면 step-incorrect를 코칭 결정에 반영하지 않는다(거짓 지적 방지).
    step_incorrect_trusted = step_incorrect and not ocr_low
    # 신호 결합은 *추가적(OR)* — 텍스트 레벨 신호를 약화하지 않고 *신뢰* 단계 incorrect만 더한다.
    # 텍스트 레벨 신호(signal)는 OCR 분해와 무관하므로 *게이팅하지 않는다*(저신뢰여도 유효).
    arithmetic_error = (signal is not None) or step_incorrect_trusted
    # 다단계 대수 슬립(kind="solution")이면 verify 발화를 *단계 자가검산*으로 변형한다(slice 61).
    # 단계 레벨 incorrect도 *단계 자가검산* 프레이밍과 자연 정합 → 같은 변형으로 OR 결합한다.
    # L3 kind→순수 bool 환산은 *오케스트레이터만* 수행(L4 recommend_coaching은 kind를 모름).
    verify_steps = (signal is not None and signal.kind == "solution") or step_incorrect_trusted
    # *신뢰* 단계 incorrect가 있으면 첫 incorrect 전이 인덱스를 *위치 신호*로 전달한다(slice 후속).
    # verify 발화를 *위치 인지* 점층(앞단계 통과 확인 + 그 지점 자가검산)으로 좁히되 정답/수정은
    # 주지 않는다(답 미루기·LTHC). 저신뢰 OCR이거나 텍스트 레벨만 있으면 None(위치 비지목·하위호환).
    incorrect_step_index = (
        verification.first_incorrect_index
        if (verification is not None and step_incorrect_trusted)
        else None
    )
    # verify가 incorrect를 냈으나 OCR 저신뢰로 코칭에서 *보류*했음을 노출(조용히 버리지 않음·정직).
    verification_ocr_gated = step_incorrect and ocr_low
    trigger = recommend_coaching(
        bkt_mastery,
        irt_theta,
        arithmetic_error=arithmetic_error,
        verify_steps=verify_steps,
        incorrect_step_index=incorrect_step_index,
        discrepancy_tol=discrepancy_tol,
        mastery_threshold=mastery_threshold,
        hint_level=hint_level,
    )
    result = SolutionCoaching(
        trigger=trigger,
        arithmetic_error=arithmetic_error,
        validation_signal=signal.reason if signal is not None else None,
        error_kind=signal.kind if signal is not None else None,
        error_span=signal.span if signal is not None else None,
        solution_verification=verification,
        verification_ocr_gated=verification_ocr_gated,
    )
    # 중간 step 등가성 shadow 관측(slice 63) — fire-and-forget·반환 무반영(비노출·비차단).
    # `result`를 *바꾸지 않는다* — observe_step_breaks는 None을 반환하고 로그로만 sink한다.
    # slice 64: 문항 맥락(problem_id·expected_answer)을 *shadow 로그에만* 주입(진단 라벨 정확도
    # 측정용). `result`엔 싣지 않는다 — 특히 expected_answer는 student-facing이면 정답 누출.
    observe_step_breaks(student_solution, problem_id=problem_id, expected_answer=expected_answer)
    # 오개념 거짓 항등식 SymPy 탐지 shadow(감사 §7) — 비노출·비차단·로그만(verdict 불변·off
    # 기본). [EOS-86] `wrong_form_match`(ADAPTER)를 더 이상 직접 import하지 않는다 — 합성
    # 루트(`composition.default_wrong_form_shadow_observer`)에서 지연 조회한다(verifier와
    # 동일한 pull 지점 재사용 — 새 간선 0).
    from whymath_backend.composition import default_wrong_form_shadow_observer

    default_wrong_form_shadow_observer()(student_solution)
    return result


__all__ = [
    "SlipKind",
    "SolutionCoaching",
    "recommend_coaching_for_solution",
]
