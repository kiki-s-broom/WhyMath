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

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from tokenize import TokenError
from typing import TYPE_CHECKING, Any, Final, Literal

import sympy
from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.l3.symbolic_equivalence import latex_to_plain
from whymath_backend.l3.verify_answer import (
    certified_polynomial,
    certified_root_sets,
    condition_relation,
    match_root,
    verify_substituted_value,
)
from whymath_backend.l3.verify_final_answer import verify_final_answer
from whymath_backend.l3.verify_step import (
    VerifyStepReasonCode,
    VerifyStepResult,
    VerifyStepState,
    verify_step,
)
from whymath_backend.schema.enums import StepType
from whymath_backend.schema.verification_capabilities import ValueExposure

__all__ = [
    "INTERPRETIVE_SELECTION",
    "INTERPRETIVE_SUBSTITUTION",
    "ROOT_PROVEN",
    "ROOT_UNKNOWN",
    "ROOT_WRONG",
    "InterpretedSolutionResult",
    "SolutionVerificationResult",
    "ValueExposureResult",
    "ValueSame",
    "aggregate_transitions",
    "answer_map_vars_matching",
    "arithmetic_fragments",
    "condition_items",
    "condition_relations",
    "distinct_values",
    "final_assignments",
    "float_value",
    "interpretive_step",
    "judge_root_value",
    "normalize_value",
    "numeric_assignments",
    "plan_transitions",
    "same_value",
    "scan_value_exposure",
    "split_top_level",
    "verify_solution",
    "verify_solution_interpreted",
]

logger = logging.getLogger(__name__)


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


# ══════════════════════════════════════════════════════════════════════════
# 해석 단계(근 선택·대입) — 동치가 아닌 전이를 **문항 조건으로** 판정한다
# (P3-71 이 solution_qa C4 에 넣은 판정을 P3-76 이 여기로 올렸다 — 공용 구현 하나)
# ══════════════════════════════════════════════════════════════════════════
# 풀이가 `x = -3, x = 4` 다음에 `x = 4`(근 선택)나 `x = 4` 다음에 `y = -202`(대입)를 쓰면 이웃
# 동치(`verify_step`)는 판정 불가나 incorrect 를 낸다 — 동치가 아니기 때문이다. 이 구역은 그런
# 전이를 조건만으로 다시 본다. 쓰는 곳은 셋이다: Solution QA C4(`harness/solution_qa`), 수용 게이트
# Tier2(`l3/equivalent/acceptance`), 야간 상시 재검증(`harness/corpus_reverify`). 세 곳이 같은
# 함수(`verify_solution_interpreted`)를 불러 같은 의미로 판정한다(복제 금지 — P3-76 ①).
#
# 판정 근거는 조건뿐이다 — 정답(`answer`·`answer_map`)에서 선택을 역산하지 않는다(P3-24 B3
# 단서: 역산하면 순환 통과다). 근거 셋: ①그 변수 하나만 담은 조건 등식 ②그 변수의 도메인
# 부등식 ③구조에 적힌 `answer_selection`(largest/smallest). 근의 집합은 풀이의 후보 나열이 아니라
# 조건 등식에서 **정확히** 계산한다 — 허용 목록 다항식(`certified_root_sets`)일 때만이다. 초월
# 함수·변수 분모·`.doit()` 래퍼 속 약분 같은 꼴로는 아무것도 증명하지 않는다(P3-71 4차 검토).
#
# 단조 규칙(P3-71 검토 중4 · P3-76 ②): 이웃 동치가 incorrect 를 낸 전이는 해석 판정이 **성립을
# 증명할 때만** 바꾼다. 증명 불가면 incorrect 그대로다 — 판정을 넓힐 뿐 기준을 낮추지 않는다.
# 이웃 동치가 correct 를 낸 전이는 건드리지 않는다.

# 유니코드 근호 — 정본 채점기가 못 읽는다(`8√3` → unverifiable, 2026-10-18 실측). 비교용으로만
# `N√M` → `N*sqrt(M)` 로 접는다(원문은 건드리지 않는다).
_RADICAL: Final = re.compile(r"(\d*)\s*√\s*(\d+|\([^()]*\))")
_ASSIGN: Final = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(\S.*?)\s*$")

INTERPRETIVE_SELECTION: Final = "근 선택"
INTERPRETIVE_SUBSTITUTION: Final = "대입"

RootJudgement = Literal["proven", "wrong", "unknown"]
ROOT_PROVEN: Final = "proven"  # 조건이 요구하는 바로 그 근이다(조건만으로 확정)
ROOT_WRONG: Final = "wrong"  # 도메인 위반·조건의 선택 규칙과 다른 근(확정)
ROOT_UNKNOWN: Final = "unknown"  # 조건에 근거가 없거나 판정 불가

ConditionInput = str | Sequence[str] | None


def normalize_value(text: str) -> str:
    """값 문자열을 비교용으로 정리한다(유니코드 근호 접기·앞뒤 공백)."""
    return _RADICAL.sub(
        lambda m: (f"{m.group(1)}*" if m.group(1) else "") + f"sqrt({m.group(2)})", text.strip()
    )


@dataclass(slots=True)
class _AnswerView:
    """`verify_final_answer` 가 읽는 최소 문항 필드. 선택지 모드를 끄고 값 대 값으로 비교한다."""

    answer: str | None
    choices: list[str] | None = None
    question_format: Any = None
    answer_format: Any = None
    multiple_answers: dict[str, Any] | None = None


class ValueSame(str, Enum):
    """두 값이 같은가 — 3상태(모르면 모른다)."""

    SAME = "same"
    DIFFERENT = "different"
    UNKNOWN = "unknown"


def same_value(left: str, right: str) -> ValueSame:
    """두 값 문자열이 수학적으로 같은가 — 정본 채점기(`verify_final_answer`)에 위임한다.

    판정 불가·예외는 UNKNOWN(같음/다름 위장 금지).
    """
    try:
        verdict = verify_final_answer(
            normalize_value(left), _AnswerView(answer=normalize_value(right))
        )
    except Exception as exc:  # noqa: BLE001 — 한 쌍의 실패는 UNKNOWN 으로 드러난다
        logger.debug("verify_solution 값 비교 회피: %s", type(exc).__name__)
        return ValueSame.UNKNOWN
    if verdict.state.value == "correct":
        return ValueSame.SAME
    if verdict.state.value == "incorrect":
        return ValueSame.DIFFERENT
    return ValueSame.UNKNOWN


def answer_map_vars_matching(answer_map: Mapping[str, str], answer: str) -> frozenset[str] | None:
    """`answer`(학생에게 보이는 정답 표기)와 같은 값을 가진 answer_map 변수 집합(OPS-150 공용 판정).

    값 동치는 `same_value`(정본 채점기 `verify_final_answer`)로만 본다 — `1/2`·`0.5`·`\\frac{1}{2}`·
    공백 차이는 같은 값이다. 반환:
      · 비어 있지 않은 집합 — 그 변수(들)의 값이 `answer` 와 같다(대조 성립)
      · 빈 집합 — 모든 변수가 **확정적으로** 다르다(불일치 — 학생 표기와 검산 재료가 갈라졌다)
      · None — 같은 값을 하나도 못 찾았고 판정 불가가 섞였다, 또는 answer_map 이 비어 있다
        (대조 불가 — 통과로 접지 않는다)

    변수가 하나면 `answer` 가 그 값이어야 한다(엄격). 변수가 여러 개인 문항은 `answer` 가 어느
    변수의 값인지 구조에 적혀 있지 않아 **소속**으로만 대조한다(약한 검사 — 형제 변수 값으로 바꾼
    변조는 못 잡는다. 호출부가 다변수 건수를 따로 드러낸다).

    호출부: 수용 품질 `harness.solution_qa` C1 · 야간 S6 `harness.corpus_reverify` — 두 게이트가
    같은 판정을 쓰도록 여기 한 벌만 둔다(사본 금지 — 거버넌스 테스트가 동결).

    LaTeX 표기(`\\frac{1}{2}`·`\\sqrt{3}`)는 정본 채점기가 직접 읽지 못하므로, `answer` 에
    백슬래시가 있을 때만 LaTeX 정규화 단일 권위(`l3.symbolic_equivalence.latex_to_plain`)로
    평문화한 뒤 비교한다.
    백슬래시가 없으면 손대지 않는다 — 그 함수는 중괄호를 괄호로 바꾸므로 집합 `{1, 2}` 를 튜플로
    만든다. 정규화기가 못 읽는 표기(`\\dfrac`·중첩 분수 등)는 판정 불가 → None 으로 드러난다.
    """
    if not answer_map:
        # 비교할 재료가 없다 — '모든 변수가 다르다'(빈 집합)로 단정하지 않는다(모른다 ≠ 아니다).
        return None
    candidate = latex_to_plain(answer) if "\\" in answer else answer
    matches: set[str] = set()
    unknown = False
    for var, value in answer_map.items():
        relation = same_value(value, candidate)
        if relation is ValueSame.SAME:
            matches.add(var)
        elif relation is ValueSame.UNKNOWN:
            unknown = True
    if not matches and unknown:
        return None
    return frozenset(matches)


def split_top_level(text: str) -> list[str]:
    """최상위 쉼표로만 자른다 — `f(1, 2)` 안의 쉼표는 자르지 않는다."""
    parts: list[str] = []
    depth = 0
    start = 0
    for index, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


# ──────────────────────────────────────────────────────────────────────────
# 값 노출 훑기 (P3-77) — "본문에 계산하면 정답이 되는 식이 있는가"
# ──────────────────────────────────────────────────────────────────────────
# 판정 대상 = 문자 없는 산술 조각. P3-10 판정기(`harness.ai_quality_judges._judge_leak` ③)가 쓰던
# 추출 규칙을 이곳으로 옮겨 **한 벌만** 둔다 — 힌트 게이트(S4-11 B·④ — 능력 계약 경유)와 판정기가
# 같은 판정을 쓴다(사본 금지). 값 비교는 새로 만들지 않고 `same_value`(정본 채점기)에 위임한다.
_VALUE_OP_NORMALIZE: Final = str.maketrans({"×": "*", "÷": "/", "−": "-", "·": "*"})
# 식 덩어리 — 문자·수·연산자·괄호·쉼표·등호가 이어진 구간(한글·콜론·줄바꿈에서 끊긴다).
_EXPR_RUN: Final = re.compile(r"[0-9A-Za-z_.()+\-*/^,= \t]+")
_NUMBER_TOKEN: Final = re.compile(r"\d+(?:\.\d+)?")
_OPERATOR_BETWEEN: Final = re.compile(r"[0-9)]\s*[-+*/^]\s*[-(0-9]")
_HAS_LETTER: Final = re.compile(r"[A-Za-z]")

#: 산술 조각 해석 실패로 *예상되는* 예외 — 이것만 "식이 아니다"로 접는다. 호출 계약이 깨진
#: 프로그래밍 오류(TypeError·AttributeError 등)는 삼키지 않는다 — 삼키면 무관용 축(정답 누설)이
#: 조용히 통과로 바뀐다(P3-10 리뷰 2026-10-21 실측 — 같은 규칙을 그대로 옮긴다).
_FRAGMENT_PARSE_FAILURES: Final[tuple[type[BaseException], ...]] = (
    sympy.SympifyError,
    TokenError,
    SyntaxError,
    ValueError,
    ZeroDivisionError,
    OverflowError,
    RecursionError,
)


@dataclass(frozen=True)
class ValueExposureResult:
    """`scan_value_exposure` 결과 — `ValueExposureScan`(능력 계약)을 구조적으로 만족한다."""

    outcome: ValueExposure
    fragment: str | None = None
    candidates: int = 0
    undecided: int = 0


def _top_level_sides(run: str) -> list[str]:
    """식 덩어리 하나를 최상위 `=`·`,`에서 자른 변들(괄호 안의 쉼표는 자르지 않는다)."""
    sides: list[str] = []
    for part in split_top_level(run):
        sides.extend(part.split("="))
    return sides


def arithmetic_fragments(text: str) -> list[str]:
    """본문 → 값을 가진 **독립** 산술식(문자 없음 · 수 2개 이상 · 수 사이 연산자 · 닫힌 수치).

    독립이란 그 식이 문자를 포함한 더 큰 식의 *일부*가 아니라는 뜻이다. 그래서 먼저 문자까지
    포함한 식 덩어리(`_EXPR_RUN`)를 잡고, 그 덩어리를 최상위 `=`·`,`로 자른 **변 하나 전체**가
    문자 없이 수치로 읽힐 때만 대상으로 삼는다. `Derivative(x - 1 + 1, x)` 속의 `- 1 + 1`은
    변 전체가 아니므로 대상이 아니다 — 잘라 내면 정답 0과 "같은 값"이 되지만 학생에게 값을
    알려 주는 식이 아니다(2026-10-22 코퍼스 실측: 이 규칙 없이는 승인·미승인 3,735문항의 검수 L3
    5,377건 중 2,155건이 이런 오탐으로 거부됐다).

    수치로 해석되지 않는 변(괄호 짝이 안 맞는 잘림 등)은 식이 아니므로 대상에서 뺀다 — 판정
    불가가 아니다. 순서를 보존하고 중복은 한 번만 낸다.
    """
    out: list[str] = []
    seen: set[str] = set()
    for run in _EXPR_RUN.findall(text.translate(_VALUE_OP_NORMALIZE)):
        for raw in _top_level_sides(run):
            frag = raw.strip()
            if not frag or frag in seen or _HAS_LETTER.search(frag):
                continue
            if len(_NUMBER_TOKEN.findall(frag)) < 2 or not _OPERATOR_BETWEEN.search(frag):
                continue
            try:
                value = safe_sympify(frag.replace("^", "**"))
            except _FRAGMENT_PARSE_FAILURES as exc:  # 잘린 변 — 식이 아니다(대상 아님)
                logger.debug("산술 조각 해석 불가(%s) — 대상에서 제외", type(exc).__name__)
                continue
            if not getattr(value, "is_number", False):
                continue
            seen.add(frag)
            out.append(frag)
    return out


def _value_targets(target: str) -> list[str]:
    """목표 문자열 → 비교할 값 표기 목록. LaTeX는 단일 권위로 평문화하고, 최상위 쉼표로 나뉜 여러
    값(`x = 2, x = 3`)은 각각을 목표로 삼는다 — 그중 하나만 드러내도 정답의 일부가 샌다."""
    plain = latex_to_plain(target) if "\\" in target else target
    parts = [p.strip() for p in split_top_level(plain) if p.strip()]
    return parts if len(parts) > 1 else [plain.strip()]


def scan_value_exposure(text: str, target: str) -> ValueExposureResult:
    """`text`의 산술 조각 중 값이 `target`과 같은 것이 있는가 — 3상태(P3-77).

    - **exposed**: 조각 하나가 목표(또는 목표의 한 성분)와 `same_value` SAME.
    - **undecidable**: 같은 것은 없는데 판정하지 못한 쌍(UNKNOWN)이 있다 — 목표를 읽지 못한
      경우(`{1, 6}`·`3개` 등)가 여기에 든다. **clean으로 접지 않는다**(모른다 ≠ 아니다).
    - **clean**: 조각이 없거나, 모든 조각이 모든 목표 성분과 DIFFERENT.

    조각이 없으면 목표를 읽을 필요가 없다 — 볼 것이 없었다는 뜻이며 `candidates=0`이 그 사실을
    남긴다("작동한 비율"). 목표가 비었으면 판정 불가다(호출부가 정답 원천 부재를 먼저 거른다).
    """
    fragments = arithmetic_fragments(text)
    if not fragments:
        return ValueExposureResult(ValueExposure.clean)
    targets = _value_targets(target) if target.strip() else []
    if not targets:
        return ValueExposureResult(
            ValueExposure.undecidable, candidates=len(fragments), undecided=len(fragments)
        )
    undecided = 0
    for frag in fragments:
        relations = [same_value(frag, t) for t in targets]
        if ValueSame.SAME in relations:
            return ValueExposureResult(
                ValueExposure.exposed, fragment=frag, candidates=len(fragments), undecided=undecided
            )
        if ValueSame.UNKNOWN in relations:
            undecided += 1
    return ValueExposureResult(
        ValueExposure.undecidable if undecided else ValueExposure.clean,
        candidates=len(fragments),
        undecided=undecided,
    )


def final_assignments(step: str) -> tuple[str, list[str]] | None:
    """단계가 `v = a` 또는 `v = a, v = b` 형태면 (변수, 값 목록). 아니면 None."""
    var: str | None = None
    values: list[str] = []
    for part in split_top_level(step):
        if "==" in part or "<" in part or ">" in part:
            return None
        match = _ASSIGN.match(part)
        if match is None:
            return None
        name, value = match.group(1), match.group(2)
        if "=" in value or (var is not None and name != var):
            return None
        var = name
        values.append(value)
    return (var, values) if var is not None else None


def float_value(value: str) -> float | None:
    """값 문자열의 실수값. 수치화 불가면 None."""
    try:
        return float(safe_sympify(normalize_value(value)))
    except Exception as exc:  # noqa: BLE001 — 수치화 불가는 None(판정 불가로 드러난다)
        logger.debug("verify_solution 수치화 회피: %s", type(exc).__name__)
        return None


def distinct_values(values: Sequence[str]) -> list[str] | None:
    """값 목록의 서로 다른 원소. 같은지 판정이 안 되는 쌍이 있으면 None."""
    kept: list[str] = []
    for value in values:
        relations = [same_value(value, other) for other in kept]
        if ValueSame.UNKNOWN in relations:
            return None
        if ValueSame.SAME not in relations:
            kept.append(value)
    return kept


def numeric_assignments(step: str) -> tuple[str, list[str]] | None:
    """`v = a[, v = b …]` 이고 값이 전부 수치(자유변수 없음)면 (변수, 서로 다른 값). 아니면 None."""
    parsed = final_assignments(step)
    if parsed is None:
        return None
    var, values = parsed
    distinct = distinct_values(values)
    if distinct is None or any(float_value(value) is None for value in distinct):
        return None
    return var, distinct


def condition_items(conditions: ConditionInput) -> list[str] | None:
    """조건 입력(문자열 하나 또는 목록)을 목록으로. 형식이 맞지 않으면 None."""
    if isinstance(conditions, str):
        return [conditions]
    if conditions is None:
        return None
    items = list(conditions)
    if not items or not all(isinstance(item, str) for item in items):
        return None
    return items


def condition_relations(
    conditions: ConditionInput,
) -> list[tuple[str, str, frozenset[str]]] | None:
    """조건마다 (원문, 관계 연산자, 자유변수 이름). 파싱 못 한 조건이 하나라도 있으면 None.

    파싱하지 못한 조건이 무엇을 제약하는지 모르므로, 그 상태로 "제약 없음"을 말하지 않는다.
    """
    items = condition_items(conditions)
    if items is None:
        return None
    out: list[tuple[str, str, frozenset[str]]] = []
    for condition in items:
        relation = condition_relation(condition)
        if relation is None:
            return None
        out.append((condition, relation[0], relation[1]))
    return out


def _defines_other_variable(condition: str, var: str) -> bool:
    """`w = f(var)` 꼴(한쪽이 다른 변수 하나뿐, 반대쪽은 `var` 의 허용 목록 다항식)인가.

    그 조건은 w 를 정할 뿐 `var` 를 제약하지 않는다. `x + z > 100`·`x**2 + y**2 = 1` 처럼
    `var` 를 함께 묶는 조건은 아니다. f 가 `log(x)`·`sqrt(x)`·`1/(x - a)` 처럼 암묵 정의역을
    가지면 w 가 존재하려면 x 가 그 정의역 안이어야 하므로 x 를 제약한다 — 정의로 면제하지
    않는다(PR #1703 3차 검토 하2).
    """
    if "<" in condition or ">" in condition or "!" in condition:
        return False
    sides = condition.split("=")
    if len(sides) != 2:
        return False
    for lone, other in ((sides[0], sides[1]), (sides[1], sides[0])):
        name = lone.strip()
        if name.isidentifier() and name != var:
            relation = condition_relation(other)
            if (
                relation is not None
                and relation[1] == frozenset({var})
                and certified_polynomial(other, var) is not None
            ):
                return True
    return False


def judge_root_value(
    conditions: ConditionInput, answer_selection: object, var: str, value: str
) -> RootJudgement:
    """`var = value` 가 조건이 요구하는 근인가 — proven·wrong·unknown.

    · `var` 를 다른 변수와 함께 담은 조건이 있으면 unknown — 그 조건이 `var` 를 더 제약하는지
      모른다. 예외는 다른 변수 하나를 `var` 의 허용 목록 다항식으로 정하는 정의 등식뿐이다.
    · 그 변수 하나만 담은 조건 등식이 정확히 하나이고, 그 등식과 그 변수의 도메인 부등식이 전부
      허용 목록 다항식이어야 한다(`certified_root_sets`). 아니면 unknown.
    · 실근은 정확 계산으로 센다. 값은 허용치 안의 정확 근 **하나**에 대응해야 한다.
    · 그 근이 도메인을 어기면 wrong. 선택 규칙 = `answer_selection`(largest/smallest — 허용 근의
      끝/처음이 아니면 wrong), 없으면 unique(허용 근이 하나일 때만 proven, 둘 이상이면 unknown).
    """
    relations = condition_relations(conditions)
    if relations is None:
        return ROOT_UNKNOWN
    domain = [c for c, op, names in relations if op != "==" and names == frozenset({var})]
    equations = [c for c, op, names in relations if op == "==" and names == frozenset({var})]
    mixed = [
        c
        for c, op, names in relations
        if var in names and len(names) > 1 and not _defines_other_variable(c, var)
    ]
    if mixed or len(equations) != 1:
        return ROOT_UNKNOWN
    sets = certified_root_sets(equations[0], domain, var)
    if sets is None:
        return ROOT_UNKNOWN
    roots, admissible = sets
    index = match_root(value, roots)
    if index is None:
        return ROOT_UNKNOWN  # 값이 정확 실근 하나에 대응하지 않는다(근이 아니거나 판정 불가).
    chosen = roots[index]
    if chosen not in admissible:
        return ROOT_WRONG  # 근이지만 도메인 제약을 어긴다(제약 위반 근).
    if answer_selection == "largest":
        return ROOT_PROVEN if chosen == admissible[-1] else ROOT_WRONG
    if answer_selection == "smallest":
        return ROOT_PROVEN if chosen == admissible[0] else ROOT_WRONG
    return ROOT_PROVEN if len(admissible) == 1 else ROOT_UNKNOWN


def _judge_selection(
    conditions: ConditionInput, answer_selection: object, var: str, chosen: str
) -> VerifyStepState:
    """근 선택 `v = a, v = b → v = a` — 고른 값이 조건이 요구하는 근인가."""
    verdict = judge_root_value(conditions, answer_selection, var, chosen)
    if verdict == ROOT_PROVEN:
        return VerifyStepState.correct
    return VerifyStepState.incorrect if verdict == ROOT_WRONG else VerifyStepState.unverifiable


def _judge_substitution(
    conditions: ConditionInput,
    answer_selection: object,
    var: str,
    candidates: Sequence[str],
    target: str,
    claimed: str,
) -> VerifyStepState:
    """대입 `v = a → w = b` — 조건이 요구하는 v 를 정의 등식(자유변수가 정확히 {v, w})에 대입한
    w 가 b 인가.

    대입에 쓰는 v 는 **조건만으로 확정된 근**이어야 한다(proven). 앞 단계 값이 하나여도 같다 —
    풀이 첫 줄의 값은 들어오는 전이가 없어 아무도 검산하지 않는다(PR #1703 검토 상1). 후보가
    여럿이면 확정되는 후보가 정확히 하나일 때만 그것을 쓴다 — 결과값에 맞는 후보를 거꾸로 찾지
    않는다(정답 역산). 다른 매개변수가 섞인 정의 등식은 쓰지 않는다.
    """
    verdicts = [judge_root_value(conditions, answer_selection, var, c) for c in candidates]
    proven = [c for c, verdict in zip(candidates, verdicts, strict=True) if verdict == ROOT_PROVEN]
    if not proven:  # 선택 규칙(unique·largest·smallest)이 확정하는 근은 많아야 하나다.
        return VerifyStepState.unverifiable
    relations = condition_relations(conditions) or []  # 확정됐으면 조건은 이미 전부 파싱됐다.
    definitions = [c for c, op, names in relations if op == "==" and names == {var, target}]
    if not definitions:
        return VerifyStepState.unverifiable
    states = [
        verify_substituted_value(definition, {var: proven[0]}, target, claimed).state
        for definition in definitions
    ]
    if "fail" in states:
        return VerifyStepState.incorrect
    if all(state == "pass" for state in states):
        return VerifyStepState.correct
    return VerifyStepState.unverifiable


def interpretive_step(
    conditions: ConditionInput, answer_selection: object, before: str, after: str
) -> tuple[str, VerifyStepState] | None:
    """동치가 아닌 해석 단계면 (종류, 판정). 그 모양이 아니면 None — 동치 판정을 그대로 둔다.

    모양은 좁게 잡는다(넓으면 진짜 틀린 변형이 '해석 단계'로 빠져나간다):
      · 근 선택 — 앞: 같은 변수의 서로 다른 수치 후보 ≥2, 뒤: 그중 **하나**
        (후보 밖 값은 선택이 아니다).
      · 대입 — 앞: 변수 v 의 수치 값(들), 뒤: **다른** 변수 w 의 수치 값 하나.
    """
    prev = numeric_assignments(before)
    nxt = numeric_assignments(after)
    if prev is None or nxt is None or len(nxt[1]) != 1:
        return None
    var, candidates = prev
    target, (claimed,) = nxt
    if target != var:
        judged = _judge_substitution(conditions, answer_selection, var, candidates, target, claimed)
        return INTERPRETIVE_SUBSTITUTION, judged
    if ValueSame.SAME not in [same_value(claimed, candidate) for candidate in candidates]:
        return None
    return INTERPRETIVE_SELECTION, _judge_selection(conditions, answer_selection, var, claimed)


@dataclass(frozen=True, slots=True)
class InterpretedSolutionResult:
    """`verify_solution_interpreted` 의 결과.

    `result` 는 해석 판정을 반영한 집계다(필드·불변식은 `SolutionVerificationResult` 그대로 —
    호출부는 `verify_solution` 결과처럼 쓴다). `interpretive` 는 해석 단계 모양으로 다시 본
    전이의 위치 → 종류(근 선택·대입)다. 판정이 바뀌지 않은 전이(증명 불가로 종전 판정 유지)도
    들어 있다 — 사람 검수 목록에서 "조건에 근거 없음"을 가르는 데 쓴다.
    """

    result: SolutionVerificationResult
    interpretive: Mapping[int, str]


def verify_solution_interpreted(
    steps: Sequence[str],
    step_types: Sequence[StepType | None] | None = None,
    *,
    conditions: ConditionInput,
    answer_selection: object = None,
) -> InterpretedSolutionResult:
    """`verify_solution`(이웃 동치) + 해석 단계(근 선택·대입)의 조건 판정 — 세 게이트 공용.

    1. `verify_solution(steps, step_types)` 를 그대로 먼저 돌린다(step_types 길이 규약 포함).
    2. correct 가 아닌 전이만 `interpretive_step` 으로 모양을 본다.
    3. 단조 규칙: 이웃 동치가 incorrect 였던 전이는 해석 판정이 correct(성립 증명)일 때만
       바꾼다. unverifiable 이었던 전이는 해석 판정(correct·incorrect)으로 바꾸고, 판정 불가면
       그대로 둔다. correct 였던 전이는 다시 보지 않는다.
    4. 바뀐 전이로 `aggregate_transitions` 를 다시 돈다 — 카운트·첫 incorrect 위치가 일관된다.
    """
    base = verify_solution(steps, step_types)
    results = list(base.steps)
    interpretive: dict[int, str] = {}
    for index, step in enumerate(base.steps):
        if step.state == VerifyStepState.correct:
            continue
        interpreted = interpretive_step(
            conditions, answer_selection, steps[index], steps[index + 1]
        )
        if interpreted is None:
            continue
        kind, judged = interpreted
        interpretive[index] = kind
        if judged == VerifyStepState.correct:
            results[index] = step.model_copy(
                update={
                    "state": VerifyStepState.correct,
                    "reason": None,
                    "reason_code": None,
                    "evidence_weight": 1.0,
                }
            )
        elif judged == VerifyStepState.incorrect and step.state == VerifyStepState.unverifiable:
            results[index] = step.model_copy(
                update={
                    "state": VerifyStepState.incorrect,
                    "reason": f"해석 단계({kind}) — 문항 조건이 요구하는 값과 어긋남(확정)",
                    "reason_code": None,
                    "evidence_weight": 1.0,
                }
            )
    return InterpretedSolutionResult(aggregate_transitions(results), interpretive)


if TYPE_CHECKING:
    # ── EOS-69 구조적 적합성 증명 ──────────────────────────────────────────
    # `SolutionVerificationResult`가 Core의 중립 계약을 *변환 없이* 만족함을 mypy가 검사한다.
    # 이 줄이 있어야 "계약을 만들었다"가 "계약이 실제로 성립한다"가 된다 — 필드 이름을 바꾸거나
    # 카운트를 지우면 여기서 적색이 난다(설계 규칙 1: 중간 변환 객체 금지).
    from whymath_backend.schema.verification_capabilities import ChainVerificationCounts

    def _counts_conformance(result: SolutionVerificationResult) -> ChainVerificationCounts:
        return result
