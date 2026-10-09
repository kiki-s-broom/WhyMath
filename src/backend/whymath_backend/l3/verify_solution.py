"""풀이 *여러 단계* 연쇄 검증 집계 — WH-1 1단계 결선 `verify_solution`(§3.1).

직전 슬라이스(`l3/verify_step.py`)는 *한 단계* 전이(expr_before → expr_after)를 3상태
(correct/incorrect/unverifiable)로 판정하는 도구 primitive를 만들었다. 실제 학생 풀이는
*여러 단계*이므로, 본 모듈은 **이미 분해된 단계 시퀀스**에 `verify_step`을 *연쇄 적용*해
집계한다 — 설계 §3.1의 **`unverified_ratio` 누적**(검증 불가 비율)을 구현한다.

핵심 설계 계약:
  - **연쇄 전이**: 단계 표현식 리스트 `steps`(길이 n)에 대해 전이 i=0..n-2를
    `verify_step(steps[i], steps[i+1])`로 검증한다 — 전이 개수는 `max(0, n-1)`.
  - **집계만**: 본 모듈은 *판정 로직을 재구현하지 않는다*. `verify_step`을 그대로 호출하고
    그 결과를 *순서 보존*해 카운트·비율·첫 incorrect 위치만 집계한다. `verify_step`의
    보수성(판정 불가 → unverifiable·치환 → unverifiable·*거짓 incorrect 회피*)을 그대로
    상속한다(정확성 #1 — CLAUDE.md "확실하지 않으면 모른다").
  - **정직 엣지**: steps 길이 < 2(또는 빈 리스트) → 전이 0개 → 빈 결과(카운트 0·
    `unverified_ratio=0.0`·`first_incorrect_index=None`·`has_incorrect=False`). *에러가 아니라*
    "검증할 전이가 없다"는 정직한 빈 집계다.

정직 스코프(범위 밖 — 후속 슬라이스):
  - **자유 텍스트 → 단계 분해**(NLP 파싱)는 본 모듈 범위 *밖*이다. 방정식 풀이
    (`2x+1=7`·LHS≠RHS가 정상)와 변형 체인을 혼동해 *거짓 incorrect*를 낼 위험이 크기
    때문이다. **분해는 L5(OCR·공간정보)가 책임**지고, 백엔드는 *호출자가 제공한 이미 분해된
    단계 시퀀스*만 검증한다. `verify_solution`은 `Sequence[str]`(표현식 리스트)를 받는다.
  - **coach 파이프라인 결선**(`api/coach.py`)도 후속이다 — coach는 현재 분해된 단계를 받지
    않는다. 기존 `validate_response`(`l4/solution_coaching.py`·solution-level numeric)는
    *별개*이며 본 모듈은 그것을 건드리지 않는다(`verify_solution`은 신규 좌석).
  - **PRM 가중치**·**단원별 verify 커버리지 ≥70% 게이팅**도 후속이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l3.verify_step import (
    VerifyStepReasonCode,
    VerifyStepResult,
    VerifyStepState,
    verify_step,
)
from whymath_backend.schema.enums import StepType

__all__ = [
    "SolutionVerificationResult",
    "aggregate_transitions",
    "plan_transitions",
    "verify_solution",
]


class SolutionVerificationResult(BaseModel):
    """`verify_solution`의 결과 — 연쇄 전이별 판정 + 상태 카운트·비율·첫 incorrect 위치.

    `steps`는 각 연쇄 전이(steps[i] → steps[i+1])의 `verify_step` 결과를 *순서 보존*해 담는다
    (길이 = n_transitions). 카운트(`n_correct`·`n_incorrect`·`n_unverifiable`)의 합은
    항상 `n_transitions`와 같다. `unverified_ratio`는 검증 불가 비율(§3.1)이고,
    `first_incorrect_index`는 첫 incorrect 전이의 인덱스(없으면 None)다.

    `unverifiable_by_reason`(MATH-03)은 unverifiable 전이의 *사유 코드별* 카운트다 — 관측된
    코드만 담는 희소 dict이고 값 합은 항상 `n_unverifiable`과 같다(모든 unverifiable에 코드가
    구조적으로 붙으므로 — `verify_step._unverifiable` 필수 인자). 클라이언트는 `steps` 전체를
    파싱하지 않고 이 카운트만으로 학생 문구 3분기를 가른다(steps 전체 소비 강제 금지 — 노출
    계약 유지).

    **노출 계약**: 검증 결과(상태·카운트·비율·폐쇄 사유 코드)뿐 — 정답/본문은 누출하지 않는다
    (`verify_step`이 정답을 알지도 못함·`reason`은 검증 사유일 뿐·코드는 폐쇄 enum 값).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    steps: list[VerifyStepResult] = Field(
        default_factory=list,
        description="각 연쇄 전이(steps[i]→steps[i+1])의 verify_step 결과(순서 보존·길이=전이수).",
    )
    n_correct: int = Field(
        description="correct 전이 개수.",
    )
    n_incorrect: int = Field(
        description="incorrect 전이 개수.",
    )
    n_unverifiable: int = Field(
        description="unverifiable 전이 개수(검증 불가).",
    )
    unverifiable_by_reason: dict[VerifyStepReasonCode, int] = Field(
        default_factory=dict,
        description=(
            "unverifiable 전이의 사유 코드별 카운트(MATH-03·희소 — 관측된 코드만·값 합="
            "n_unverifiable). 키는 폐쇄 7종 VerifyStepReasonCode(JSON 직렬화 시 문자열 값)."
        ),
    )
    n_transitions: int = Field(
        description="총 전이 개수 = max(0, len(steps)-1). 세 카운트의 합과 같다.",
    )
    unverified_ratio: float = Field(
        description="검증 불가 비율 = n_unverifiable/n_transitions(§3.1). 전이 0이면 0.0.",
    )
    first_incorrect_index: int | None = Field(
        default=None,
        description="첫 incorrect 전이 인덱스 i(steps[i]→steps[i+1]). 없으면 None.",
    )
    has_incorrect: bool = Field(
        description="incorrect 전이가 하나라도 있으면 True(= first_incorrect_index is not None).",
    )


def _empty_result() -> SolutionVerificationResult:
    """전이 0개(steps 길이 < 2·빈 리스트)의 정직한 빈 집계 — 에러가 아니다."""
    return SolutionVerificationResult(
        steps=[],
        n_correct=0,
        n_incorrect=0,
        n_unverifiable=0,
        unverifiable_by_reason={},
        n_transitions=0,
        unverified_ratio=0.0,
        first_incorrect_index=None,
        has_incorrect=False,
    )


def verify_solution(
    steps: Sequence[str],
    step_types: Sequence[StepType | None] | None = None,
) -> SolutionVerificationResult:
    """이미 분해된 단계 시퀀스에 `verify_step`을 연쇄 적용해 집계 — 순수·결정론·DB 0.

    설계 §3.1 연쇄 검증 + `unverified_ratio` 누적. 입력 `steps`는 *호출자가 제공한 이미 분해된*
    표현식 리스트다(자유 텍스트 → 단계 분해는 L5 책임·범위 밖 — 거짓 incorrect 위험).

    연쇄 전이:
      - i=0..len(steps)-2에 대해 `verify_step(steps[i], steps[i+1], step_type=...)`를 호출한다.
      - 전이 i의 step_type = `step_types[i]`(있을 때). 즉 step_types는 *전이당 하나*이므로
        의미상 길이가 전이 개수(`len(steps)-1`)와 맞으면 가장 깔끔하다.

    step_types 길이 규약(정직·안전):
      - `step_types is None` → 모든 전이를 step_type 미지정(None)으로 검증.
      - `len(step_types) != len(steps) - 1` → **ValueError**. 길이 불일치를 *조용히 패딩하면*
        전이와 타입이 어긋나 비대수 단계를 대수로(또는 그 반대로) 오판할 위험이 있다 — 정확성
        #1 원칙상 *명시적으로 거부*한다(거짓 판정 회피). (전이 0개일 때는 빈 step_types만 허용.)

    집계:
      - 상태별 카운트(`n_correct`·`n_incorrect`·`n_unverifiable`)·`n_transitions`.
      - `unverifiable_by_reason` = unverifiable 전이의 사유 코드별 카운트(MATH-03·희소·값 합
        == n_unverifiable — verify_step의 reason_code를 세기만 한다·재판정 0).
      - `unverified_ratio` = n_unverifiable / n_transitions(전이 0이면 0.0).
      - `first_incorrect_index` = 첫 incorrect 전이 인덱스(없으면 None)·`has_incorrect`.

    엣지: steps 길이 < 2(또는 빈 리스트) → 전이 0개 → 빈 결과(카운트 0·ratio 0.0·
    first_incorrect_index None·has_incorrect False). 에러가 아니라 "검증할 전이 없음"의 정직한
    빈 집계다.

    **재구현 아님**: 판정은 전적으로 `verify_step`이 하고, 본 함수는 그 결과를 *집계만* 한다.
    따라서 `verify_step`의 보수성(판정 불가·치환 → unverifiable·*거짓 incorrect 회피*)을 그대로
    상속한다.

    범위 밖(후속): 텍스트 → 단계 분해(L5)·coach 파이프라인 결선·PRM 가중치·단원별 verify
    커버리지 ≥70% 게이팅.
    """
    plan = plan_transitions(steps, step_types)
    results = [verify_step(before, after, step_type=step_type) for before, after, step_type in plan]
    return aggregate_transitions(results)


def plan_transitions(
    steps: Sequence[str],
    step_types: Sequence[StepType | None] | None = None,
) -> list[tuple[str, str, StepType | None]]:
    """연쇄 전이 계획 — `(before, after, step_type)` 목록(전이 순서·길이 = `max(0, len(steps)-1)`).

    `step_types` 길이 규약(전이당 하나)을 여기서 검사하고 불일치는 `ValueError`로 거부한다 —
    조용한 패딩은 전이와 타입을 어긋나게 해 비대수 단계를 대수로(또는 그 반대로) 오판할 위험이
    있다(정확성 #1). 전이 0개면 빈 목록(에러 아님).

    `verify_solution`에서 *분리*한 이유(OPS-96): 호출부가 전이를 **하나씩** 이벤트 루프 밖에서
    시간 상한과 함께 돌릴 수 있게 하기 위해서다. 체인 전체를 한 번에 돌리면 느린 전이 1개가
    다른 전이의 정상 판정까지 판정 불가로 지운다. 판정 로직은 여전히 `verify_step` 하나뿐이다.
    """
    n_transitions = max(0, len(steps) - 1)

    # step_types 길이 규약 — 전이당 하나. 불일치는 조용한 패딩 대신 명시 거부(거짓 판정 회피).
    if step_types is not None and len(step_types) != n_transitions:
        raise ValueError(
            "step_types 길이는 전이 개수(len(steps)-1)와 같아야 한다 "
            f"— 받은 길이 {len(step_types)} ≠ 전이 {n_transitions}."
        )

    return [
        (steps[i], steps[i + 1], step_types[i] if step_types is not None else None)
        for i in range(n_transitions)
    ]


def aggregate_transitions(results: Sequence[VerifyStepResult]) -> SolutionVerificationResult:
    """전이별 `verify_step` 결과를 순서 보존해 집계 — 판정 재구현 0(카운트·비율·첫 incorrect만).

    전이 0개면 정직한 빈 집계다(에러 아님).
    """
    n_transitions = len(results)
    if n_transitions == 0:
        return _empty_result()

    n_correct = 0
    n_incorrect = 0
    n_unverifiable = 0
    unverifiable_by_reason: dict[VerifyStepReasonCode, int] = {}
    first_incorrect_index: int | None = None

    for i, result in enumerate(results):
        if result.state == VerifyStepState.correct:
            n_correct += 1
        elif result.state == VerifyStepState.incorrect:
            n_incorrect += 1
            if first_incorrect_index is None:
                first_incorrect_index = i
        else:  # unverifiable — 판정 불가(verify_step의 보수적 출구·거짓 incorrect 회피).
            n_unverifiable += 1
            # MATH-03 사유 코드 집계 — verify_step이 모든 unverifiable에 코드를 구조적으로
            # 붙이므로(`_unverifiable` 필수 인자·총부착 동결 테스트) None 분기는 도달하지 않고,
            # is None 가드는 타입 내로잉용이다(값 합==n_unverifiable 불변식 유지).
            if result.reason_code is not None:
                unverifiable_by_reason[result.reason_code] = (
                    unverifiable_by_reason.get(result.reason_code, 0) + 1
                )

    # unverified_ratio — 검증 불가 비율(§3.1). 전이가 있으므로 0 나눗셈 없음.
    unverified_ratio = n_unverifiable / n_transitions

    return SolutionVerificationResult(
        steps=list(results),
        n_correct=n_correct,
        n_incorrect=n_incorrect,
        n_unverifiable=n_unverifiable,
        unverifiable_by_reason=unverifiable_by_reason,
        n_transitions=n_transitions,
        unverified_ratio=unverified_ratio,
        first_incorrect_index=first_incorrect_index,
        has_incorrect=first_incorrect_index is not None,
    )


if TYPE_CHECKING:
    # ── EOS-69 구조적 적합성 증명 ──────────────────────────────────────────
    # `SolutionVerificationResult`가 Core의 중립 계약을 *변환 없이* 만족함을 mypy가 검사한다.
    # 이 줄이 있어야 "계약을 만들었다"가 "계약이 실제로 성립한다"가 된다 — 필드 이름을 바꾸거나
    # 카운트를 지우면 여기서 적색이 난다(설계 규칙 1: 중간 변환 객체 금지).
    from whymath_backend.schema.verification_capabilities import ChainVerificationCounts

    def _counts_conformance(result: SolutionVerificationResult) -> ChainVerificationCounts:
        return result
