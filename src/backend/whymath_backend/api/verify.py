"""풀이 검증 도구 HTTP 표면 — `verify-step`·`verify-solution`·`verify-answer`(stateless).

WH-1/WH-S 검증기 스택(§3.1·§4)의 *엔드포인트 좌석*. 3-tier 도구 primitive를 stateless HTTP로 노출:
- `/v1/verify-step`: 학생 풀이의 *한 단계*(expr_before → expr_after)가 올바른 변형인지
  **3상태**(correct/incorrect/unverifiable)로 판정한다(Tier2 기호 단계 동치).
- `/v1/verify-solution`: *이미 분해된* 단계 시퀀스(표현식 리스트)에 verify_step을 *연쇄 적용*해
  집계한다(상태별 카운트·`unverified_ratio`·첫 incorrect 위치·§3.1 연쇄 검증). 텍스트→단계
  분해는 L5(OCR·공간정보) 책임이라 여기 밖이다 — 호출자가 *이미 분해된* steps를 보낸다.
- `/v1/verify-answer`: *구한 답*(치환맵)을 원 조건(들)에 대입해 만족 여부를 **3상태**
  (pass/fail/unverifiable)로 검산한다(Tier1 수치 샘플링·§4). Tier2(단계 동치)와 *다른 질문* —
  "답이 원 조건을 만족하는가"다. Tier1 단독 pass는 증명이 아니므로(신뢰도 최저) 최종 통과엔
  Tier2와 결합해야 한다(`whs/verdict.final_verdict`). 자체 동등문제 답 검산·다중 풀이 동치 도구.

**경계**:
- *stateless* — DB 무접근·LLM 호출 0·세션 없음(순수 SymPy 결정론 검증).
- 인증 = `ConsentedUser`(미성년 동의 게이트만) — 학생 풀이 단계는 PII 가능(CLAUDE.md). 인증
  게이트만 걸고 *본인 데이터 스코핑/적재는 없다*(stateless).
- **노출 계약**: 응답은 *판정 결과*(state·reason·evidence_weight·step_type·카운트·비율)뿐이다.
  학생 풀이 단계가 *입력*으로 들어오나, 정답/본문은 *전혀 누출하지 않는다*(verify_step은 판정만
  반환·정답을 알지도 못함). `reason`은 "동치 아님 — SymPy: ..." 같은 *검증 사유*일 뿐 정답이 아니다.

**정직 스코프**(후속): PRM 점수·텍스트→단계 분해(L5 책임)·coach 파이프라인 결선·단원별 verify
커버리지 ≥70% 게이팅은 *후속 슬라이스*다. 본 슬라이스는 verify_step·verify_solution *도구
primitive* + 엔드포인트까지다(기존 validator/match_gate/coach/harness·`validate_response` 불변·
verify_solution은 신규 좌석).
"""

from __future__ import annotations

import logging
import time
from functools import partial

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from whymath_backend.api._auth import ConsentedUser
from whymath_backend.api._isolated_call import isolated
from whymath_backend.config import get_settings
from whymath_backend.l3.verify_answer import (
    AnswerVerdict,
    budget_exceeded_verdict,
    verify_answer,
)
from whymath_backend.l3.verify_solution import (
    SolutionVerificationResult,
    aggregate_transitions,
    plan_transitions,
)
from whymath_backend.l3.verify_step import (
    VerifyStepResult,
    budget_exceeded_result,
    verify_step,
)
from whymath_backend.schema.enums import StepType

# 남용 방어 상한(verify-step max_length=4000·verify-solution 200 미러) — 조건식/치환식 길이·
# 연립 조건 수·치환 변수 수 상한. 초과는 422(입력 검증 실패).
_MAX_EXPR_LEN = 4000
_MAX_CONDITIONS = 50
_MAX_ANSWER_VARS = 50

# OPS-96: verify-solution 체인 전체의 총 시간 예산 = 호출 1건 상한 × 이 배수. 전이마다 상한을 따로
# 주면 병리적 전이 199개가 한 요청으로 워커를 199×상한 동안 붙잡을 수 있다.
_CHAIN_BUDGET_FACTOR = 4

logger = logging.getLogger("whymath.api.verify")

router = APIRouter(prefix="/v1", tags=["verify"])


class VerifyStepRequest(BaseModel):
    """`POST /v1/verify-step` 요청 — 풀이 한 단계(변형 전·후 식 + 선택 step_type)."""

    model_config = ConfigDict(extra="forbid")

    expr_before: str = Field(
        max_length=4000,
        description="변형 *전* 식(학생 풀이 한 단계의 좌측). 길이 상한은 남용 방어.",
    )
    expr_after: str = Field(
        max_length=4000,
        description="변형 *후* 식(같은 단계의 우측). before와 동치면 correct.",
    )
    step_type: StepType | None = Field(
        default=None,
        description=(
            "단계 유형(선택). 비대수(조건해석·케이스분류·그래프스케치)면 SymPy 시도 없이 "
            "unverifiable. 계산·검산·미지정이면 심볼릭 동치 검증."
        ),
    )


@router.post(
    "/verify-step",
    response_model=VerifyStepResult,
    summary="풀이 한 단계 3상태 검증(correct/incorrect/unverifiable·stateless)",
)
async def post_verify_step(
    body: VerifyStepRequest,
    user: ConsentedUser,
) -> VerifyStepResult:
    """풀이 한 단계(expr_before → expr_after)가 올바른 변형인지 *3상태*로 판정 — DB 무접근.

    대수 변형은 SymPy 심볼릭 동치로 correct/incorrect를, 비대수 단계(서술형·경우나누기·기하)나
    판정/파싱 불가는 *정직하게* unverifiable로 반환한다(CLAUDE.md "확실하지 않으면 모른다" —
    correct로 위장하지 않음·unverifiable이면 evidence_weight 0.5 할인).

    **OPS-96**: SymPy는 이벤트 루프 밖 워커 프로세스에서 시간 상한과 함께 돈다. 상한을 넘기면
    계산을 끊고 `unverifiable`(`reason_code=undecidable`)로 응답한다 — 통과·오답이 아니다.

    `user`는 인증 게이트만(stateless라 user 데이터 미사용). 응답은 판정만 — 정답/본문 누출 0.
    """
    _ = user.user_id  # 인증 게이트 통과 확인용(stateless라 user 데이터 미사용).
    return await isolated(
        verify_step,
        body.expr_before,
        body.expr_after,
        body.step_type,
        on_budget_exceeded=lambda: budget_exceeded_result(body.step_type),
    )


class VerifySolutionRequest(BaseModel):
    """`POST /v1/verify-solution` 요청 — *이미 분해된* 단계 시퀀스(+ 전이별 선택 step_types).

    `steps`는 호출자가 *이미 분해한* 표현식 리스트다 — 자유 텍스트→단계 분해는 L5(OCR·공간정보)
    책임이라 여기 밖이다(방정식 풀이와 변형 체인을 혼동한 *거짓 incorrect* 위험·정확성 #1).
    인접 전이 steps[i]→steps[i+1]마다 verify_step이 걸리며, `step_types`를 주면 길이가 전이
    개수(`len(steps)-1`)와 같아야 한다(전이당 하나·불일치 시 422).
    """

    model_config = ConfigDict(extra="forbid")

    steps: list[str] = Field(
        max_length=200,
        description="이미 분해된 풀이 단계 표현식 리스트(순서대로). 인접 전이를 연쇄 검증한다.",
    )
    step_types: list[StepType | None] | None = Field(
        default=None,
        description=(
            "전이별 단계 유형(선택). 주면 길이 = 전이 개수(len(steps)-1)여야 한다(전이당 하나). "
            "비대수(조건해석·케이스분류·그래프스케치)면 그 전이는 SymPy 시도 없이 unverifiable."
        ),
    )


@router.post(
    "/verify-solution",
    response_model=SolutionVerificationResult,
    summary="풀이 단계 시퀀스 연쇄 검증 집계(카운트·unverified_ratio·첫 오류·stateless)",
)
async def post_verify_solution(
    body: VerifySolutionRequest,
    user: ConsentedUser,
) -> SolutionVerificationResult:
    """이미 분해된 단계 시퀀스에 verify_step을 *연쇄 적용*해 집계 — DB 무접근(§3.1).

    인접 전이(steps[i]→steps[i+1])마다 verify_step을 걸어 상태별 카운트·`unverified_ratio`
    (검증 불가 비율)·첫 incorrect 전이 인덱스를 모은다. 판정은 전적으로 verify_step 소관이라
    (재구현 아님) 그 보수성(거짓 incorrect 회피·판정 불가→unverifiable)을 그대로 상속한다.

    엣지: steps 길이 <2면 전이 0개 → 빈 결과(에러 아님). step_types 길이가 전이 개수와 다르면
    verify_solution이 ValueError를 던지므로 *422*로 변환해 호출자에게 명확히 알린다(조용한 패딩
    금지·정확성 #1 — FastAPI는 본문 ValueError를 자동 422로 바꾸지 않으니 명시 처리).

    **OPS-96**: 전이를 **하나씩** 이벤트 루프 밖에서 시간 상한과 함께 검증한다. 느린 전이는 그
    전이만 `unverifiable`로 접히고 나머지 전이의 정상 판정은 보존된다. 체인 전체에는 총 시간
    예산(`상한 × 4`)이 있어, 병리적 전이가 여럿이어도 한 요청이 워커를 오래 붙잡지 못한다 —
    예산이 다 쓰이면 남은 전이는 계산 없이 `unverifiable`이다.

    `user`는 인증 게이트만(stateless라 user 데이터 미사용). 응답은 검증 집계만 — 정답/본문 누출 0.
    """
    _ = user.user_id  # 인증 게이트 통과 확인용(stateless라 user 데이터 미사용).
    try:
        plan = plan_transitions(body.steps, body.step_types)
    except ValueError as exc:
        # step_types 길이 규약 위반 — 입력 오류이므로 422(스택트레이스·500 노출 금지).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    cap_s = get_settings().sympy_isolation_timeout_s
    deadline = time.monotonic() + cap_s * _CHAIN_BUDGET_FACTOR
    results: list[VerifyStepResult] = []
    exhausted_logged = False
    for before, after, step_type in plan:
        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0:
            # 총 예산 소진 — 계산 없이 판정 불가(통과·오답 아님). 요청당 한 번만 로그.
            if not exhausted_logged:
                logger.warning("sympy_isolation_chain_budget_exhausted → 남은 전이 판정 불가")
                exhausted_logged = True
            results.append(budget_exceeded_result(step_type))
            continue
        results.append(
            await isolated(
                verify_step,
                before,
                after,
                step_type,
                on_budget_exceeded=partial(budget_exceeded_result, step_type),
                # 남은 총 예산이 호출 상한보다 작으면 그만큼만 준다 — 체인 시간이 예산을 넘지 않게.
                timeout_s=min(cap_s, remaining_s),
            )
        )
    return aggregate_transitions(results)


class VerifyAnswerRequest(BaseModel):
    """`POST /v1/verify-answer` 요청 — *구한 답*(치환맵)을 원 조건(들)에 대입한 Tier1 수치 검산.

    `conditions`는 단일 조건 str 또는 연립 list[str](AND). `answer`는 변수→식 치환맵
    (예 `{"x": "3"}`·`{"x": "b/(2*a)"}`·`{"x": "2", "y": "1"}`). 값은 SymPy 식 문자열이다.
    Tier1(수치 샘플링)이라 pass는 "샘플 점에서 조건 만족"이지 *증명이 아니다*(단독 최종 통과
    금지·§4). 남용 방어로 조건식/치환식 길이·연립 개수·치환 변수 수에 상한을 둔다(초과 422).
    """

    model_config = ConfigDict(extra="forbid")

    conditions: str | list[str] = Field(
        description="단일 조건 식(str) 또는 연립(list[str]·AND). 등식·부등식·≠ 관계.",
    )
    answer: dict[str, str] = Field(
        description='변수→식 치환맵(예 {"x": "3"}). 값은 SymPy 식 문자열.',
    )
    n_samples: int = Field(
        default=8,
        ge=1,
        le=64,
        description="자유변수(파라미터) 조건의 수치 샘플 수. 상한은 남용(DoS) 방어.",
    )
    tol: float = Field(
        default=1e-9,
        gt=0.0,
        le=1.0,
        description="수치 잔차 허용오차(|residual|<tol → 만족). 상한은 남용 방어.",
    )

    @field_validator("conditions")
    @classmethod
    def _cap_conditions(cls, v: str | list[str]) -> str | list[str]:
        """조건 문자열 길이·연립 개수 상한(남용 방어) — 초과 시 422."""
        if isinstance(v, list):
            if len(v) > _MAX_CONDITIONS:
                raise ValueError(f"conditions 연립은 최대 {_MAX_CONDITIONS}개입니다.")
            items = v
        else:
            items = [v]
        for cond in items:
            if len(cond) > _MAX_EXPR_LEN:
                raise ValueError(f"각 조건 식은 최대 {_MAX_EXPR_LEN}자입니다.")
        return v

    @field_validator("answer")
    @classmethod
    def _cap_answer(cls, v: dict[str, str]) -> dict[str, str]:
        """치환 변수 수·치환식 길이 상한(남용 방어) — 초과 시 422."""
        if len(v) > _MAX_ANSWER_VARS:
            raise ValueError(f"answer 치환맵은 최대 {_MAX_ANSWER_VARS}개 변수입니다.")
        for val in v.values():
            if len(val) > _MAX_EXPR_LEN:
                raise ValueError(f"각 치환식은 최대 {_MAX_EXPR_LEN}자입니다.")
        return v


@router.post(
    "/verify-answer",
    response_model=AnswerVerdict,
    summary="구한 답을 원 조건에 대입한 Tier1 수치 검산(pass/fail/unverifiable·stateless)",
)
async def post_verify_answer(
    body: VerifyAnswerRequest,
    user: ConsentedUser,
) -> AnswerVerdict:
    """답(치환맵)을 원 조건(들)에 대입해 만족 여부를 Tier1 *3상태*로 판정 — DB 무접근(§4).

    등식·부등식·≠·연립(AND)을 지원하며, 파라미터(자유변수) 조건은 *고정 시드* 수치 샘플링으로
    검산한다. `verify_answer`(l3) 소관이라(재구현 아님) 그 정직성을 상속한다 — 파싱 불가·미지원
    관계·유효 샘플 0은 *pass로 위장하지 않고* unverifiable로 보수 처리한다(CLAUDE.md "확실하지
    않으면 모른다"). **Tier1 단독 pass는 증명이 아니다**(신뢰도 최저·§4) — 최종 통과엔 Tier2
    (verify-step/solution)와 결합해야 한다.

    노출 계약(verify-step 동형): 조건·답은 *입력*(호출자 제공)이고 응답은 *판정 결과*
    (state·reason·samples_checked)뿐이다 — 서버 정답을 조회하지도, 누출하지도 않는다.
    **OPS-96**: SymPy는 이벤트 루프 밖 워커 프로세스에서 시간 상한과 함께 돈다. 상한 초과는
    `unverifiable`이다(pass·fail 아님).

    `user`는 인증 게이트만(stateless라 user 데이터 미사용).
    """
    _ = user.user_id  # 인증 게이트 통과 확인용(stateless라 user 데이터 미사용).
    return await isolated(
        verify_answer,
        body.conditions,
        body.answer,
        n_samples=body.n_samples,
        tol=body.tol,
        on_budget_exceeded=budget_exceeded_verdict,
    )
