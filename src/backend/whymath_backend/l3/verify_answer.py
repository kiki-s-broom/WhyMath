"""Tier1 수치 답 검산기 — WH-S 솔버 하네스 S0 슬라이스 1+2(설계 §4 Tier1).

설계안(`docs/architecture/03b_wh_s_solver_harness.md`) §4 검증기 스택의 **Tier1(수치 검증)**:
"구한 답을 *원 조건에 대입*, 랜덤 수치 샘플 + 경계값/특이점 검사". 커버리지가 가장 넓되
신뢰도가 가장 낮은 계층이다 — **단독 사용 금지**(과정이 틀려도 답만 맞으면 통과시킴, §4 한계).

`verify_step`(`l3/verify_step.py`)의 *단계 동치*(expr_before ≡ expr_after)와는 *다른 질문*을
묻는다: verify_step은 "한 변형이 동치인가", verify_answer는 "구한 답이 *원 조건을 만족하는가*".
전자는 Tier2(기호 단계 동치), 후자가 Tier1(수치 답 검산)이다. 최종 판정은 둘을 **결합**해야
하며(§4 판정 규칙), 그 combiner는 `whs/verdict.py`다 — 본 모듈은 Tier1 *단독*이라 그 자체로
최종 통과를 의미하지 않는다.

표기 계약·권위 경계(docs/architecture/notation_contract.md): SymPy(verify_step·verify_answer)는 수식
동치·정오 판정 단일 권위다. 웹 mathjs는 렌더·수치 평가 전용(동치 판정 미관여) — 공유 표기 계약은
`data/notation_contract.json` golden test로 양측 교차검증한다.

커버하는 조건 형태(Tier1 §4):
  - **등식**(`=`/`Eq`/항등식): `lhs - rhs`를 잔차로 만들어 |residual|<tol 검산.
    함수 동치 "f(x)=g(x) 항등식"(예 `sin(x)**2 + cos(x)**2 = 1`)도 이 등식 + 자유변수
    샘플링 경로로 자동 커버된다(치환 후 잔차가 자유변수로 남아 샘플링).
  - **부등식·≠ 관계**(`>`,`<`,`>=`,`<=`,`!=`): 잔차 `lhs - rhs`를 수치 평가한 뒤 *관계 연산자
    진리값*으로 판정(아래 _eval_relation). 등식 잔차 경로와 별개의 *진리값 평가 경로*다.
  - **연립(여러 조건 AND)**: `conditions`에 `Sequence[str]`을 주면 각 조건을 검산 후 AND 결합
    (전부 pass→pass·하나라도 fail→fail·fail 없고 일부 unverifiable→unverifiable·빈 시퀀스→
    unverifiable). 단일 `str`은 기존과 *완전 동일* 동작(하위호환).

핵심 설계 계약:
  - **대입·잔차**: `condition`을 관계로 sympify하고, 등식이면 `lhs - rhs`를 잔차(residual)로,
    부등식이면 (잔차, 연산자) 쌍으로 파싱한 뒤 `answer` 치환맵을 대입한다.
  - **자유변수 없는 잔차** → 직접 수치 평가: 등식은 |residual|<tol → pass·명백히 ≠0 → fail.
    부등식은 잔차를 연산자 진리값(tol 경계 감안)으로 평가 → True→pass·False→fail.
  - **자유변수 있는 잔차**(파라미터 문제·예: `2*a*x = b`, `x = b/(2*a)`) → **수치 샘플링**
    (Tier1의 핵심): *고정 시드* 난수 샘플 + 경계값을 자유변수에 대입해 수치 평가 — 전부
    만족이면 pass·어디서든 명백히 위반이면 fail·유효 샘플이 하나도 없으면 unverifiable.
  - **정직성(verify_step 상속·CLAUDE.md "확실하지 않으면 모른다")**: 파싱 불가·관계 아님·예외·
    유효 샘플 0은 *절대 pass로 위장하지 않고* `unverifiable`로 보수 처리한다. 0으로 나눔 등
    특이점 샘플은 *건너뛰되*(유효 샘플에서 제외), 유효 샘플이 0이면 unverifiable. 부등식·연립도
    동일 — 판정 불가·일부 미정은 pass로 위장하지 않는다(연립은 보수적으로 unverifiable).
  - **결정론**: 샘플은 *고정 시드*에서 뽑아 같은 입력에 같은 결과를 보장한다(재현·디버그).
  - **원문 정의역(P3-75)**: 평가 파싱은 `x*(x - 2)/(x - 2)` 를 `x` 로 접어 무연근 x = 2 의 잔차를
    0 으로 만든다. 그래서 pass 는 조건 원문 구문 나무를 그 점에서 허용 노드만으로 노드별로 평가해
    (`condition_definedness`) 정의될 때만 남긴다 — 정의되지 않음 확정이면 fail, 허용 구조 밖이면
    unverifiable. 근 선택·해 존재성 분류의 근 집합도 같은 판정으로 거른다(`trusted_real_roots`).

Tier1 정직성(설계 §4): `pass`는 "샘플 점들에서 조건을 만족"이지 *증명이 아니다*(신뢰도 최저).
따라서 Tier1 단독 pass를 최종 통과로 쓰지 않고, 반드시 Tier2(`verify_solution`)와 결합한다
(`whs/verdict.final_verdict`). 본 모듈은 그 *재료*만 만든다. 부등식·연립도 마찬가지로 Tier1
단독으로는 최종 통과를 의미하지 않는다.

정직 스코프(범위 밖 — 후속):
  - **베이스라인 풀이율 측정**(시드 모델 Ollama·Phaiakes9 필요)은 이 환경 밖·후속이다.
  - **솔버 루프·`solution_nodes`/저장소 스키마**(S1+·향후 alembic 마이그레이션)도 범위 밖이다.
  - **Tier3 형식 검증**(Lean4·증명 문제)·**PRM**도 후속이다(§4·§9 로드맵).
  - 본 슬라이스는 *Tier1 수치 검산기*(등식·부등식·연립) + 판정 combiner(`whs/verdict.py`)만이다.
"""

from __future__ import annotations

import ast
import decimal
import io
import logging
import math
import random
import re
import tokenize
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from typing import Final, Literal, cast

import sympy
from pydantic import BaseModel, ConfigDict, Field

# CONST-09(코딩 헌법 R22-03): 문자열 → SymPy 파싱은 전부 안전 진입점을 거친다. 이 모듈의 입력은
# 학생 답(`/v1/verify-answer`·평가 재료 답)·LLM 생성 조건·저작 코퍼스가 섞여 오므로 출처를 가려
# 신뢰하지 않는다. 거부(`UnsafeExpressionError` ⊂ ValueError)는 아래 기존 except가 받아
# unverifiable로 보수 처리한다.
from whymath_backend.l3.safe_parse import (
    ensure_within_budget,
    safe_subs,
    safe_sympify,
)

# 침묵실패 금지(CLAUDE.md) — 보수 회피(except Exception)는 예외 *타입명*을 debug로 남긴다.
# 메시지 본문은 학생 답·문항 식이 섞일 수 있어 제외(타입명만으로 계통 장애를 관측).
logger = logging.getLogger("whymath.l3.verify_answer")

__all__ = [
    "AnswerVerdict",
    "SolvabilityVerdict",
    "budget_exceeded_verdict",
    "classify_solvability",
    "certified_polynomial",
    "certified_root_sets",
    "condition_definedness",
    "condition_relation",
    "derive_selected_root",
    "function_domain_kind",
    "match_root",
    "split_equation_domain",
    "trusted_real_roots",
    "verify_answer",
    "verify_conditional_equal",
    "verify_congruent_by_ratio",
    "verify_dot_product_scalar",
    "verify_events_independent",
    "verify_extremum_count",
    "verify_geometric_convergence",
    "verify_inequality_direction",
    "verify_is_differentiable",
    "verify_is_one_to_one",
    "verify_limit_equals_value",
    "verify_mean_equals_median",
    "verify_nondifferentiable_point_count",
    "verify_real_root_count",
    "verify_root_aggregate",
    "verify_root_selection",
    "verify_series_converges",
    "verify_substituted_value",
    "warm_isolated_worker",
]


# 결정론을 위한 *고정 시드* — 같은 입력에 같은 샘플(재현·디버그). 비결정 난수 금지.
_SAMPLE_SEED = 20260613

# 자유변수 샘플링 시 항상 평가하는 경계값(특이점·부호 전환·0 근방을 의도적으로 포함).
# Tier1 §4 "경계값/특이점 검사" — 0·±1·작은 값·큰 값에서 조건이 깨지는지 본다.
_BOUNDARY_VALUES: tuple[float, ...] = (
    0.0,
    1.0,
    -1.0,
    0.5,
    -0.5,
    2.0,
    -2.0,
    10.0,
    -10.0,
)

# 난수 샘플 범위 — 0 근방 특이점은 _BOUNDARY로 따로 보고, 여기선 일반적 비특이 점을 본다.
_SAMPLE_LOW = -7.0
_SAMPLE_HIGH = 7.0


class AnswerVerdict(BaseModel):
    """`verify_answer`(Tier1 수치 답 검산)의 결과 — 3상태 + 사유·평가 샘플 수.

    `state`는 항상 3상태 중 하나다. `pass`는 "샘플 점들에서 조건을 만족"이지 *증명이 아니다*
    (Tier1 신뢰도 최저·단독 사용 금지·§4). `reason`은 fail/unverifiable의 한국어 사유
    (pass이면 None). `samples_checked`는 실제 *유효하게 평가한* 샘플 수(특이점으로 건너뛴
    샘플은 제외)다 — 디버그·신뢰도 가늠용.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["pass", "fail", "unverifiable"] = Field(
        description=(
            "Tier1 3상태 — pass(샘플 점에서 조건 만족·증명 아님)·fail(조건 위반 확정)·"
            "unverifiable(파싱 불가·관계 아님·유효 샘플 0 등 보수적 회피)."
        ),
    )
    reason: str | None = Field(
        default=None,
        description="fail/unverifiable 사유(한국어). pass이면 None(사유 불필요).",
    )
    samples_checked: int = Field(
        description="실제 유효하게 평가한 샘플 수(특이점으로 건너뛴 샘플 제외·디버그용).",
    )


def _pass(samples_checked: int) -> AnswerVerdict:
    """pass 결과 조립(샘플 점 만족·증명 아님·Tier2 결합 필수)."""
    return AnswerVerdict(state="pass", reason=None, samples_checked=samples_checked)


def _fail(reason: str, samples_checked: int) -> AnswerVerdict:
    """fail 결과 조립 — 조건 위반이 *확정*된 경우만(보수적·거짓 fail 회피)."""
    return AnswerVerdict(state="fail", reason=reason, samples_checked=samples_checked)


def _unverifiable(reason: str, samples_checked: int = 0) -> AnswerVerdict:
    """unverifiable 결과 조립 — 정직 회피의 단일 출구(절대 pass 위장 금지)."""
    return AnswerVerdict(state="unverifiable", reason=reason, samples_checked=samples_checked)


def budget_exceeded_verdict() -> AnswerVerdict:
    """계산 시간 상한 초과(OPS-96)의 *판정 불가* 결과 — pass·fail 어느 쪽도 아니다."""
    return _unverifiable("SymPy 계산 시간 상한 초과 — 검증 안전 회피")


# 부등식·≠ 관계 연산자 — 잔차(lhs-rhs) 진리값 평가 경로에서 쓰는 연산자 집합.
# 등식("==")은 잔차==0 경로(별도)라 여기 포함하지 않는다.
_RELATION_OPS: frozenset[str] = frozenset({">", "<", ">=", "<=", "!="})


class _ConditionShapeError(ValueError):
    """조건 문자열이 *단일 스칼라 식*으로 읽히지 않는다(P3-80) — 파싱 불가의 한 갈래.

    `"1,2,3,4,9"` 같은 쉼표 나열은 sympify가 파이썬 `tuple`로 돌려준다. 이것은 개념형 문항의
    자료 목록 DSL(`_parse_number_list` 소비 — 평균=중앙값·독립·조건부확률·내적)이지 방정식이
    아니다. 잔차(`sympy.Expr`) 계약을 어긴 채 돌려주면 호출부가 `.free_symbols`에서
    `AttributeError`로 터지거나(근 선택 유도·근 선택·근 집계·실근 개수 등), 상수 튜플을 0 아닌
    상수로 읽어 "해 없음"을 **확정**했다(`classify_solvability` — 판정 불가여야 할 자리의 틀린
    판정).

    `ValueError`의 하위형이라 기존 호출부(전부 파싱 실패를 판정 불가로 접는다)가 그대로 받는다.
    로그에는 이 타입명이 남아 다른 파싱 실패와 구분된다(침묵 실패 금지 — 필드값은 싣지 않는다).
    """


def _require_scalar(expr: object, where: str) -> sympy.Expr:
    """`expr`이 SymPy 스칼라 식(`sympy.Expr`)이 아니면 `_ConditionShapeError`(형태 검사·P3-80).

    튜플·리스트(쉼표 나열)·행렬·집합·진리값처럼 `잔차 == 0`으로 읽을 수 없는 꼴을 *자유 변수 수집
    전에* 막는다. 사유에는 타입명만 싣는다(조건 원문·값은 싣지 않는다).
    """
    if not isinstance(expr, sympy.Expr):
        raise _ConditionShapeError(f"조건의 {where}이 단일 식이 아님({type(expr).__name__})")
    return expr


def _parse_condition(condition: str) -> tuple[sympy.Expr, str]:
    """condition 문자열을 (잔차 식, 관계 연산자)로 파싱.

    반환 연산자:
      - `"=="` — 등식(조건 만족 ⇔ residual == 0). `=`/`Eq`/`Equality`, 또는 등호가 없는 단일
        식("== 0" 으로 해석). 잔차는 `lhs - rhs`(단일 식이면 식 자체).
      - `">"`,`"<"`,`">="`,`"<="`,`"!="` — 부등식·≠. 잔차는 `lhs - rhs`이며, 진리값은 잔차를
        수치 평가해 *연산자*로 판정한다(`_eval_relation`). 별도의 진리값 평가 경로다.

    파싱 불가는 예외를 일으켜 호출부가 unverifiable로 처리한다(보수적·pass 위장 금지). 반환
    잔차는 **항상** `sympy.Expr`이다 — 좌·우변 또는 단일 식이 스칼라 식이 아니면(쉼표 나열이
    만든 튜플 등) `_ConditionShapeError`(`ValueError` 하위형)를 낸다(P3-80).
    """
    text = condition.strip()
    if not text:
        raise ValueError("빈 condition")

    # `!=`(≠)는 파이썬 비교라 sympify가 bool로 접어버린다 — SymPy `Ne(lhs, rhs)`로 명시 변환.
    if "!=" in text:
        lhs_text, rhs_text = text.split("!=", 1)
        lhs = _require_scalar(safe_sympify(lhs_text), "좌변")
        rhs = _require_scalar(safe_sympify(rhs_text), "우변")
        return ensure_within_budget(lhs - rhs), "!="

    # `==`(파이썬식 등호)를 등식 잔차로 변환 — sympify가 `==`를 *구조 비교*로 접어 `False`(상수
    # 진리값)로 만들기 전에 문자열에서 직접 분해한다. 실 LLM이 `x**2-1 == 0`처럼 파이썬식 등호를
    # 쓰는 회귀(Phaiakes9 실측·S2-i) — 단일 `=` 경로와 동형이되 `==` 토큰을 별도로 받는다.
    if "==" in text:
        lhs_text, rhs_text = text.split("==", 1)
        lhs = _require_scalar(safe_sympify(lhs_text), "좌변")
        rhs = _require_scalar(safe_sympify(rhs_text), "우변")
        return ensure_within_budget(lhs - rhs), "=="

    # `=`(단일 등호, `==`/`<=`/`>=` 아님)를 등식 잔차로 변환. `==`는 위에서 이미 처리했다.
    if (
        "=" in text
        and "==" not in text
        and "<=" not in text
        and ">=" not in text
        and "<" not in text
        and ">" not in text
    ):
        lhs_text, rhs_text = text.split("=", 1)
        lhs = _require_scalar(safe_sympify(lhs_text), "좌변")
        rhs = _require_scalar(safe_sympify(rhs_text), "우변")
        return ensure_within_budget(lhs - rhs), "=="

    parsed = safe_sympify(text)
    if isinstance(parsed, sympy.Equality):
        return ensure_within_budget(parsed.lhs - parsed.rhs), "=="
    # 부등식(StrictGreaterThan/GreaterThan/StrictLessThan/LessThan) — 잔차 + 연산자로 환원.
    if isinstance(parsed, sympy.core.relational.Relational):
        rel_op = parsed.rel_op
        if rel_op in _RELATION_OPS:
            return ensure_within_budget(parsed.lhs - parsed.rhs), rel_op
        # 그 외 관계(예상 밖) — 보수적 거부.
        raise ValueError(f"지원하지 않는 관계 연산자: {rel_op}")
    if isinstance(parsed, sympy.logic.boolalg.Boolean):
        # sympify가 이미 진리값(BooleanTrue/False)으로 접은 경우 — 자유변수 없는 관계라 잔차
        # 모델로 환원 불가(보수적 거부). 호출부가 unverifiable 처리.
        raise ValueError("관계가 상수 진리값으로 환원 — Tier1 잔차 모델 적용 불가")
    # 등식 기호가 없는 단일 식 → 식 == 0을 묻는 잔차로 본다. 쉼표 나열(파이썬 tuple)·행렬·집합은
    # 단일 식이 아니다 — 여기서 막아야 호출부의 `.free_symbols`가 터지지 않는다(P3-80).
    return _require_scalar(parsed, "식"), "=="


def _eval_relation(magnitude: float, op: str, tol: float) -> bool | None:
    """부등식 잔차(lhs-rhs의 *실수값* `magnitude`)를 연산자 진리값으로 판정 — tol 경계 감안.

    True(조건 만족)·False(조건 위반)·None(경계 모호·판정 보류)의 3값을 돌린다. tol 밴드(|값|≤tol)
    는 *경계*로 보아: 엄격(`>`,`<`)은 경계에서 명백한 True/False가 아니므로 None(과도한 false 판정
    회피)·등호(`>=`,`<=`)는 경계를 만족(True)으로·`!=`는 경계(≈0)를 위반(False)으로 본다.
    """
    if op == ">":
        if magnitude > tol:
            return True
        if magnitude < -tol:
            return False
        return None  # 경계(≈0) — 엄격 부등식이라 모호·보류.
    if op == "<":
        if magnitude < -tol:
            return True
        if magnitude > tol:
            return False
        return None
    if op == ">=":
        if magnitude > -tol:
            return True  # 경계 포함(잔차 ≥ -tol).
        return False
    if op == "<=":
        if magnitude < tol:
            return True  # 경계 포함(잔차 ≤ tol).
        return False
    if op == "!=":
        return abs(magnitude) > tol  # 같으면(≈0) 위반(False)·다르면 만족(True).
    raise ValueError(f"알 수 없는 관계 연산자: {op}")


def _eval_numeric(expr: sympy.Expr, tol: float) -> bool | None:
    """자유변수 없는 잔차 식을 수치 평가 — |값|<tol→True·확정 ≠0→False·평가 불가→None.

    복소수·무한·NaN 등은 *평가 불가(None)* 로 보수 처리한다(pass/fail로 위장 금지).
    """
    try:
        value = complex(expr.evalf())
    except (TypeError, ValueError, AttributeError):
        return None
    # NaN·무한 — 평가 불가.
    if value != value or abs(value.real) == float("inf") or abs(value.imag) == float("inf"):
        return None
    # 허수부가 유의미하면 실수 조건 평가 불가(복소 — 보수적 None).
    if abs(value.imag) > tol:
        return None
    return abs(value.real) < tol


def verify_answer(
    conditions: str | Sequence[str],
    answer: Mapping[str, str],
    *,
    n_samples: int = 8,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """Tier1 수치 답 검산 — 답을 원 조건(들)에 대입해 만족 여부를 3상태로 판정(순수·결정론·DB 0).

    설계 §4 Tier1. 첫 인자는 *단일 조건* `str`(하위호환·기존 동작 불변) 또는 *연립* `Sequence[str]`
    (여러 조건 AND)이다. `answer`는 치환맵(예 {"x":"3"}·{"x":"b/(2*a)"}·{"x":"2","y":"1"}).

    지원 조건 형태:
      - **등식**(예 "x**2 - 5*x + 6 = 0"·"2*a*x = b"·"Eq(x**2, 9)") — `lhs - rhs` 잔차==0 검산.
        함수 동치 항등식("f(x)=g(x)"·예 "sin(x)**2 + cos(x)**2 = 1")도 등식 + 자유변수 샘플링으로
        자동 커버(치환 후 잔차가 자유변수로 남아 샘플링 경로).
      - **부등식·≠**(예 "x > 0"·"x**2 >= 4"·"a*x <= 0"·"x != 1") — 잔차 수치값을 연산자 진리값
        (tol 경계 감안)으로 판정.
      - **연립**(예 ["x+y=3","x-y=1"]) — 각 조건 검산 후 AND: 전부 pass→pass·하나라도 fail→fail·
        fail 없고 일부 unverifiable→unverifiable(보수적)·빈 시퀀스→unverifiable(검증할 조건 없음).

    단일 조건 판정 흐름(`_verify_single`):
      1. condition을 (잔차, 연산자)로 파싱(`convert_xor=True`로 `^`=거듭제곱). 파싱 불가·미지원
         관계 → **unverifiable**(보수적·pass 위장 금지).
      2. answer 치환맵을 잔차에 대입.
      3. **잔차에 자유변수 없음** → 직접 수치 평가: 등식은 |residual|<tol→pass·≠0→fail·평가 불가
         →unverifiable. 부등식은 잔차값을 연산자 진리값으로(True→pass·False→fail·경계 모호/평가
         불가→unverifiable).
      4. **잔차에 자유변수 있음**(파라미터 문제) → **수치 샘플링**(Tier1 핵심): 자유변수에
         *고정 시드* 난수 n_samples + 경계값(0·±1·작은·큰 값)을 대입해 평가 —
         · 모든 *유효* 샘플에서 만족 → **pass**
         · 어느 유효 샘플에서든 명백히 위반 → **fail**(거짓 답을 한 점으로 반증)
         · 유효 샘플이 하나도 없음(전부 특이점·복소·경계 모호) → **unverifiable**.
         0으로 나눔 등 특이점 샘플은 *건너뛴다*(유효 샘플에서 제외).

    `samples_checked`(연립): 각 조건이 유효하게 평가한 샘플 수의 *합산*(전체 검증 노력의 척도).
    `reason`(연립): fail/unverifiable이 *어느 조건*에서 났는지 인덱스·사유를 표기(디버그).

    Tier1 정직성(§4): `pass`는 "샘플 점에서 조건 만족"이지 *증명이 아니다*(신뢰도 최저).
    Tier1 단독 pass를 최종 통과로 쓰지 않고 반드시 Tier2와 결합한다(`whs/verdict.final_verdict`).
    파싱 불가·미지원 관계·평가 불가·유효 샘플 0·연립 일부 미정은 *절대 pass로 위장하지 않고*
    unverifiable로 보수 처리한다(verify_step 정직성 상속). 부등식·연립도 동일.

    범위 밖(후속): 베이스라인 풀이율 측정(시드 모델)·솔버 루프·저장소 스키마·PRM·Tier3(§9).
    """
    # 단일 str(하위호환) — 기존 단일 조건 경로와 *완전 동일*(직전 슬라이스 회귀 0).
    if isinstance(conditions, str):
        return _verify_single(conditions, answer, n_samples=n_samples, tol=tol)

    # 연립(Sequence[str]) — 각 조건 검산 후 AND 결합.
    condition_list = list(conditions)
    if not condition_list:
        # 빈 시퀀스 — 검증할 조건이 없음. pass로 위장하지 않고 보수적 unverifiable.
        return _unverifiable("연립 조건 없음(빈 시퀀스) — 검증할 것 없음·안전 회피")

    total_samples = 0
    first_unverifiable: str | None = None
    for index, condition in enumerate(condition_list):
        verdict = _verify_single(condition, answer, n_samples=n_samples, tol=tol)
        total_samples += verdict.samples_checked
        if verdict.state == "fail":
            # 어느 한 조건이라도 위반이면 연립 전체 fail(답이 조건 하나를 깸).
            return _fail(
                f"연립 조건 {index}번 위반 — {verdict.reason}",
                samples_checked=total_samples,
            )
        if verdict.state == "unverifiable" and first_unverifiable is None:
            # 첫 미정 조건만 기록(fail이 나오면 그쪽이 우선이라 보류).
            first_unverifiable = f"연립 조건 {index}번 판정 불가 — {verdict.reason}"

    if first_unverifiable is not None:
        # fail은 없으나 일부 미정 → 보수적 unverifiable(전부 pass라고 위장하지 않음).
        return _unverifiable(first_unverifiable, samples_checked=total_samples)

    # 전부 pass — 연립 전체 pass(단, 샘플 점 만족이지 증명 아님·Tier2 결합 필수).
    return _pass(samples_checked=total_samples)


def _verify_single(
    condition: str,
    answer: Mapping[str, str],
    *,
    n_samples: int,
    tol: float,
) -> AnswerVerdict:
    """단일 조건(등식 또는 부등식) Tier1 검산 — `verify_answer`의 단일-조건 코어(순수·결정론).

    등식이면 잔차==0, 부등식이면 잔차 진리값(`_eval_relation`)으로 판정한다. 자유변수가 남으면
    고정 시드 샘플링(`_sample_parametric`). 모든 정직성 계약(파싱 불가·평가 불가·유효 샘플 0 →
    unverifiable·pass 위장 금지)을 보존한다.
    """
    # ① condition → (잔차, 연산자). 파싱 불가·미지원 관계는 보수적 unverifiable.
    try:
        residual, op = _parse_condition(condition)
    except (
        Exception
    ) as exc:  # noqa: BLE001 — 파싱·미지원 관계는 보수적 unverifiable(pass 위장 금지)
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("condition 파싱 불가/미지원 관계 — 검증 안전 회피")

    # ② answer 치환맵 대입(키·값 모두 sympify). 치환 실패는 보수적 unverifiable.
    try:
        substitutions: dict[sympy.Symbol, sympy.Expr] = {
            sympy.Symbol(var): safe_sympify(val_text) for var, val_text in answer.items()
        }
        # 대입은 곧바로 계산한다 — `safe_subs`가 계산 없는 대입으로 먼저 예산을 본다
        # (조건 `y = 2^x`에 `x = 10^100` 대입이 20초 timeout이던 재현표 항목).
        substituted = safe_subs(residual, substitutions)
    except Exception as exc:  # noqa: BLE001 — 치환 실패도 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("answer 치환 불가 — 검증 안전 회피")

    free_symbols = sorted(substituted.free_symbols, key=str)

    # ③ 자유변수 없음 → 직접 수치 평가(파라미터 없는 일반 답).
    if not free_symbols:
        if op == "==":
            verdict = _eval_numeric(substituted, tol)
            if verdict is True:
                # P3-75 — 허용치 안의 잔차가 **정확히** 0 이 아니면 근이 아니다
                # (`(x - 1)**2 + 10**(-20) = 0` 의 x = 1). 근사 소수가 섞이면 허용치를 그대로 쓴다.
                if not substituted.has(sympy.Float) and substituted.is_zero is False:
                    return _fail(
                        f"조건 위반 — 잔차가 허용치 안이나 정확히 0 이 아님: {substituted}",
                        samples_checked=1,
                    )
                if substituted.has(sympy.Float) and _decimal_residual_nonzero(
                    condition, substitutions
                ):
                    return _unverifiable(
                        "조건의 소수 리터럴을 적힌 십진값으로 읽으면 잔차가 0 이 아니거나 다시"
                        " 읽지 못함(허용치 안) — 근사 소수 조건이라 확정하지 않음·안전 회피",
                        samples_checked=1,
                    )
                passed = _pass(samples_checked=1)
                return _definedness_gate(condition, residual, substitutions, passed)
            if verdict is False:
                return _fail(f"조건 위반 — 잔차 ≠ 0: {substituted}", samples_checked=1)
            return _unverifiable("수치 평가 불가(복소/NaN 등) — 검증 안전 회피")
        # 부등식 — 잔차 실수값을 연산자 진리값으로 판정.
        magnitude = _eval_relation_residual(substituted, tol)
        if magnitude is None:
            return _unverifiable("부등식 잔차 수치 평가 불가(복소/NaN 등) — 검증 안전 회피")
        truth = _eval_relation(magnitude, op, tol)
        if truth is True:
            return _definedness_gate(condition, residual, substitutions, _pass(samples_checked=1))
        if truth is False:
            return _fail(f"부등식 조건 위반({op}) — 잔차 {magnitude}", samples_checked=1)
        return _unverifiable(f"부등식 경계 모호({op}) — 검증 안전 회피")

    # ④ 자유변수 있음(파라미터 문제) → 수치 샘플링(Tier1 핵심·고정 시드 결정론).
    # P3-75 — 샘플 점에서도 원문 정의역을 본다: 원문이 정의되는 샘플이 하나도 없으면 pass 가 아니다.
    # 잔차가 접히며 사라진 이름(`x >= a - b**2` 에 x = a + 1 → 잔차 1 + b**2 의 a)도 원문 평가에는
    # 값이 필요하다 — 샘플 점의 값을 함께 준다(그 점마다 달라진다).
    hidden = {symbol for value in substitutions.values() for symbol in value.free_symbols}
    hidden |= {sympy.Symbol(name) for name in _condition_names(condition)}
    hidden -= set(substitutions) | set(free_symbols)

    def faithful(point: Mapping[sympy.Symbol, sympy.Expr]) -> bool:
        filler = next(iter(point.values()))
        full = {**{symbol: filler for symbol in hidden}, **point}
        try:
            values = {
                str(name): safe_subs(value, dict(full)) for name, value in substitutions.items()
            }
        except Exception as exc:  # noqa: BLE001 — 대입 불가는 '정의 확인 못 함'
            logger.debug("verify_answer 정의역 판정 회피: %s", type(exc).__name__)
            return False
        values.update({str(name): value for name, value in full.items()})
        return condition_definedness(condition, values) == _DEFINED

    return _sample_parametric(
        substituted, free_symbols, op, n_samples=n_samples, tol=tol, faithful=faithful
    )


class _DecimalRewriteError(Exception):
    """소수 리터럴을 정확값으로 다시 쓰지 못했다(토큰화·변환 실패). 호출부는 판정 불가로 닫는다."""


def _exact_decimal_text(condition: str) -> str | None:
    """조건 원문의 소수 리터럴(`2.0`·`1e-20`)을 **적힌 그대로의** 십진 정확값으로 바꾼 원문.

    토큰 단위로 바꾼다(식을 평가하지 않는다). 리터럴은 `(유효숫자*10**(지수))` 꼴로 쓴다 —
    `1e-100` 을 `(1/1000…0)` 처럼 101자리 정수로 펼치면 안전 파싱이 긴 리터럴로 거부한다(P3-79
    재검토 P2-1). 소수 리터럴이 없으면 None, 토큰화·변환에 실패하면 `_DecimalRewriteError`.
    정수·허수(`2j`)·16진 리터럴은 그대로 둔다.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(condition).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError) as exc:
        logger.debug("verify_answer 소수 리터럴 토큰화 회피: %s", type(exc).__name__)
        raise _DecimalRewriteError from exc
    if any(token.start[0] != 1 or token.end[0] > 1 for token in tokens if token.string):
        raise _DecimalRewriteError  # 여러 줄 조건은 다루지 않는다(오프셋 계산을 한 줄로 한정)
    pieces: list[str] = []
    cursor = 0
    changed = False
    for token in tokens:
        text = token.string
        if token.type != tokenize.NUMBER:
            continue
        lowered = text.lower()
        if lowered.endswith("j") or lowered.startswith(("0x", "0o", "0b")):
            continue
        if "." not in text and "e" not in lowered:
            continue
        try:
            sign, digits, exponent = decimal.Decimal(text.replace("_", "")).as_tuple()
        except (decimal.InvalidOperation, ValueError) as exc:
            logger.debug("verify_answer 소수 리터럴 변환 회피: %s", type(exc).__name__)
            raise _DecimalRewriteError from exc
        if not isinstance(exponent, int):
            raise _DecimalRewriteError  # inf·nan 은 리터럴로 오지 않는다(방어)
        significand = int("".join(str(d) for d in digits) or "0")
        start, end = token.start[1], token.end[1]
        pieces.append(condition[cursor:start])
        pieces.append(f"({'-' if sign else ''}{significand}*10**({exponent}))")
        cursor = end
        changed = True
    if not changed:
        return None
    pieces.append(condition[cursor:])
    return "".join(pieces)


def _decimal_residual_nonzero(
    condition: str, substitutions: Mapping[sympy.Symbol, sympy.Expr]
) -> bool:
    """근사 소수가 **조건 리터럴에서만** 왔을 때, 그 리터럴을 적힌 십진 정확값으로 읽은 잔차가
    정확히 0 이 아님을 확인하지 못했는가 — True 면 호출부가 판정 불가로 둔다(P3-75 검토 3 —
    `(x - 1)**2 + 1e-20 = 0` 의 x = 1).

    P3-79 ⑦ — 종전에는 *평가된* 잔차의 Float 를 십진값으로 바꿨다. 그러면 `x = sqrt(2.0)` 은
    `sqrt(2.0)` 이 먼저 1.41421356237310 으로 평가된 뒤 그 반올림값이 정확값이 돼, 정답 sqrt(2) 가
    unverifiable 로 떨어졌다. 이제 **원문 리터럴**(`2.0`)을 정확값(2)으로 바꾼 원문을 다시 파싱한다.

    P3-79 재검토 P2-1 — 다시 쓰기·재파싱에 실패하면 True(판정 불가로 닫는다). 종전처럼 False 로
    두면 `(x - 1)**2 + 1e-100 = 0` 의 x = 1 이 허용치 안의 잔차로 pass 가 됐다(fail-open).

    답에 근사 소수가 있으면 False(종전 허용치 판정을 그대로 둔다 — √2 ≈ 1.4142… 같은 근사 답).
    정확 잔차의 0 여부를 SymPy 가 못 정하면(`is_zero` None) False(종전과 같다).
    """
    if any(value.has(sympy.Float) for value in substitutions.values()):
        return False
    try:
        exact_text = _exact_decimal_text(condition)
        if exact_text is None:
            # 근사 소수가 잔차에 있는데 원문에 소수 리터럴이 없다 — 어디서 왔는지 모르면 닫는다.
            return True
        exact, _ = _parse_condition(exact_text)
        value = safe_subs(exact, dict(substitutions))
    except Exception as exc:  # noqa: BLE001 — 정확값 재구성 불가는 판정 불가로 닫는다
        logger.debug("verify_answer 소수 리터럴 재판정 회피: %s", type(exc).__name__)
        return True
    return bool(not value.free_symbols and value.is_zero is False)


def _definedness_gate(
    condition: str,
    residual: sympy.Expr,
    substitutions: Mapping[sympy.Symbol, sympy.Expr],
    passed: AnswerVerdict,
) -> AnswerVerdict:
    """Tier1 pass 직전의 원문 정의역 확인(P3-75) — 자동 약분이 지운 무연근을 pass 로 두지 않는다.

    평가 파싱은 `x*(x - 2)/(x - 2)` 를 `x` 로 접어 x = 2 의 잔차를 0 으로 만든다. 그래서 pass 는
    원문 구문 나무를 그 점에서 노드별로 평가해(`condition_definedness`) 정의될 때만 남긴다.
      · undefined → fail(원문에서 그 값이 정의되지 않음 — 무연근)
      · unknown → unverifiable(허용 구조 밖 — 정의역을 확인하지 못했다)
    답이 기호를 담아 잔차가 기호적으로 0 이 된 경우(`2*a*x = b` 의 x = b/(2*a))는 그 기호를
    Tier1 샘플 점에서 평가해, 원문이 정의되는 샘플이 하나라도 있으면 pass 를 남긴다
    (우연한 특이점은 건너뜀).
    """
    params = {symbol for value in substitutions.values() for symbol in value.free_symbols}
    params |= residual.free_symbols - set(substitutions)
    # 잔차가 접히며 사라진 이름(`a*x >= a*x` 의 a)도 원문에는 남아 있다 — 원문 이름에서 다시 모은다.
    params |= {sympy.Symbol(name) for name in _condition_names(condition)} - set(substitutions)
    if params:
        return _definedness_gate_sampled(condition, substitutions, sorted(params, key=str), passed)
    state = condition_definedness(
        condition, {str(name): value for name, value in substitutions.items()}
    )
    if state == _DEFINED:
        return passed
    if state == _UNDEFINED:
        return _fail(
            "원문 조건이 답의 값에서 정의되지 않음(분모 0·0 의 0 이하 제곱 등) — 무연근",
            samples_checked=passed.samples_checked,
        )
    return _unverifiable(
        "원문 조건의 정의역을 확인하지 못함(허용 구조 밖) — 검증 안전 회피",
        samples_checked=passed.samples_checked,
    )


def _definedness_gate_sampled(
    condition: str,
    substitutions: Mapping[sympy.Symbol, sympy.Expr],
    params: Sequence[sympy.Symbol],
    passed: AnswerVerdict,
) -> AnswerVerdict:
    """기호가 남는 답의 원문 정의역 확인 — Tier1 샘플 점(경계값 + 고정 시드 난수)에서 본다."""
    rng = random.Random(_SAMPLE_SEED)
    points: list[float] = list(_BOUNDARY_VALUES)
    points.extend(rng.uniform(_SAMPLE_LOW, _SAMPLE_HIGH) for _ in range(8))
    for point in points:
        sample = {symbol: sympy.Float(point) for symbol in params}
        try:
            values = {
                str(name): safe_subs(value, dict(sample)) for name, value in substitutions.items()
            }
        except Exception as exc:  # noqa: BLE001 — 대입 불가 샘플은 건너뛴다
            logger.debug("verify_answer 정의역 판정 회피: %s", type(exc).__name__)
            continue
        values.update({str(symbol): value for symbol, value in sample.items()})
        if condition_definedness(condition, values) == _DEFINED:
            return passed
    return _unverifiable(
        "원문 조건이 정의되는 샘플 0(자동 약분된 점이거나 허용 구조 밖) — 검증 안전 회피",
        samples_checked=passed.samples_checked,
    )


def _eval_relation_residual(expr: sympy.Expr, tol: float) -> float | None:
    """자유변수 없는 부등식 잔차를 *실수값*으로 수치 평가 — 복소/NaN/무한이면 None(보수적).

    `_eval_numeric`(등식 bool 판정)과 달리 부등식은 부호가 필요해 *실수값 자체*를 돌린다.
    """
    try:
        value = complex(expr.evalf())
    except (TypeError, ValueError, AttributeError):
        return None
    if value != value or abs(value.real) == float("inf") or abs(value.imag) == float("inf"):
        return None
    if abs(value.imag) > tol:
        return None  # 복소 — 실수 부등식 평가 불가(보수적).
    return value.real


def _evaluate_point(
    expr: sympy.Expr,
    substitution: dict[sympy.Symbol, sympy.Float],
    tol: float,
) -> float | None:
    """한 대입점에서 잔차를 수치 평가 — *부호 있는 실수부* 반환·특이점/복소/NaN/무한이면 None.

    부호를 보존해 부등식 방향 판정(`_eval_relation`)이 가능하다. 등식 경로는 호출부에서
    `abs(...)`를 취해 기존 동작(|잔차|)을 그대로 보존한다.
    """
    try:
        value = complex(ensure_within_budget(expr.subs(substitution)).evalf())
    except (TypeError, ValueError, AttributeError, ZeroDivisionError):
        return None  # 특이점(0 나눔 등)·평가 불가 — 유효 샘플 아님.
    if value != value or abs(value.real) == float("inf"):
        return None  # NaN·무한 — 특이점으로 간주(보수적).
    if abs(value.imag) > tol:
        return None  # 복소 — 실수 조건 평가 불가.
    return value.real


def _classify_point(residual: float, op: str, tol: float) -> bool | None:
    """한 점의 *부호 있는 잔차*를 (조건 만족 True·위반 False·모호 None)으로 분류.

    등식(`==`)은 |잔차|<tol → 만족·아니면 위반. 부등식은 `_eval_relation`에 위임(tol 경계 감안).
    경계 모호(None)는 유효 샘플로 세지 않고 *건너뛴다*(pass/fail 위장 금지).
    """
    if op == "==":
        return abs(residual) < tol
    return _eval_relation(residual, op, tol)


def _sample_parametric(
    expr: sympy.Expr,
    free_symbols: list[sympy.Symbol],
    op: str,
    *,
    n_samples: int,
    tol: float,
    faithful: Callable[[Mapping[sympy.Symbol, sympy.Expr]], bool] | None = None,
) -> AnswerVerdict:
    """파라미터(자유변수) 잔차를 *고정 시드* 샘플 + 경계값으로 평가 — Tier1 샘플링 코어.

    각 자유변수에 (경계값 전부) + (n_samples개 난수)를 대입해 수치 평가하고, `op`에 따라 한 점의
    만족/위반/모호를 분류한다(`_classify_point`). 어느 유효 샘플에서든 *위반*이면 즉시 **fail**(한
    반례로 거짓 답 반증). 0으로 나눔 등 특이점·복소·경계 모호는 *건너뛴다*(유효 샘플 아님). 모든
    유효 샘플에서 만족이면 **pass**·유효 샘플이 하나도 없으면 **unverifiable**.

    등식(`op=="=="`)은 종전과 *동일*하게 |잔차|<tol 판정이라 기존 동작이 보존된다(하위호환).

    결정론: `random.Random(_SAMPLE_SEED)`로 시드를 고정해 같은 입력에 같은 샘플을 보장한다.
    다변수일 때는 변수별 *서로 다른* 점도 평가해, 상관 잔차를 한 점이 우연히 만족시키는 위장을
    차단한다.
    """
    rng = random.Random(_SAMPLE_SEED)
    valid_samples = 0
    # P3-75 — `faithful` 이 주어지면 만족 샘플 중 **원문이 정의되는** 샘플을 센다. 판정(fail)은
    # 바꾸지 않고, pass 가 원문이 정의되지 않는 점들(자동 약분된 점)에만 기대고 있으면 끌어내린다.
    faithful_samples = 0

    # (1) 단일 점 대입(모든 자유변수에 같은 값) — 경계값 + 난수.
    sample_points: list[float] = list(_BOUNDARY_VALUES)
    sample_points.extend(rng.uniform(_SAMPLE_LOW, _SAMPLE_HIGH) for _ in range(n_samples))
    for point in sample_points:
        substitution = {symbol: sympy.Float(point) for symbol in free_symbols}
        residual = _evaluate_point(expr, substitution, tol)
        if residual is None:
            continue  # 특이점·평가 불가 — 건너뜀.
        satisfied = _classify_point(residual, op, tol)
        if satisfied is None:
            continue  # 부등식 경계 모호 — 건너뜀(유효 샘플 아님).
        valid_samples += 1
        if not satisfied:
            return _fail(
                f"파라미터 샘플 {point} 에서 조건 위반({op})",
                samples_checked=valid_samples,
            )
        if faithful is not None and faithful(substitution):
            faithful_samples += 1

    # (2) 다변수 — 변수별 서로 다른 점도 평가(상관 잔차의 우연한 만족 위장 차단).
    if len(free_symbols) > 1:
        for _ in range(n_samples):
            substitution = {
                symbol: sympy.Float(rng.uniform(_SAMPLE_LOW, _SAMPLE_HIGH))
                for symbol in free_symbols
            }
            residual = _evaluate_point(expr, substitution, tol)
            if residual is None:
                continue
            satisfied = _classify_point(residual, op, tol)
            if satisfied is None:
                continue
            valid_samples += 1
            if not satisfied:
                return _fail(
                    f"다변수 파라미터 샘플에서 조건 위반({op})",
                    samples_checked=valid_samples,
                )
            if faithful is not None and faithful(substitution):
                faithful_samples += 1

    # 유효 샘플이 하나도 없으면 판정 불가(전부 특이점·복소·경계 모호) — pass 위장 금지.
    if valid_samples == 0:
        return _unverifiable("유효 샘플 0(전부 특이점/복소/경계 모호) — 검증 안전 회피")
    if faithful is not None and faithful_samples == 0:
        return _unverifiable(
            "원문 조건이 정의되는 샘플 0(자동 약분된 점이거나 허용 구조 밖) — 검증 안전 회피",
            samples_checked=valid_samples,
        )

    # 모든 유효 샘플에서 조건 만족 → pass(단, 샘플 점 만족이지 증명 아님·Tier2 결합 필수).
    return _pass(samples_checked=valid_samples)


# ──────────────────────────────────────────────────────────────────────────
# 근 선택 검증(S2-i) — "큰 근/작은 근/유일" 문제의 *어느 근인가*를 판정.
# ──────────────────────────────────────────────────────────────────────────
RootSelection = Literal["largest", "smallest", "unique"]


def _real_value(expr: sympy.Expr, tol: float) -> float | None:
    """식을 실수값으로 수치 평가 — 복소/NaN/무한이면 None(보수적)."""
    try:
        value = complex(expr.evalf())
    except (TypeError, ValueError, AttributeError):
        return None
    if value != value or abs(value.real) == float("inf") or abs(value.imag) > tol:
        return None
    return value.real


def _approx_equal(a: float, b: float, tol: float) -> bool:
    """상대·절대 허용치를 겸한 근사 동치(큰 값에서도 안전)."""
    return abs(a - b) <= max(tol, tol * abs(b))


def _distinct_values(values: Sequence[float], tol: float) -> list[float]:
    """근사 중복을 접은 서로 다른 값 목록(중근을 1개로)."""
    out: list[float] = []
    for v in values:
        if not any(_approx_equal(v, u, tol) for u in out):
            out.append(v)
    return out


# ──────────────────────────────────────────────────────────────────────────
# 도메인 제약(P3-71) — "단일 등식 + 같은 변수의 도메인 부등식" 조건 리스트를 읽는 공용 조각.
# 근 선택(`verify_root_selection`)과 Solution QA 의 해석 단계 판정(`harness/solution_qa`)이 같은
# 파서·같은 경계 규칙을 쓰게 여기 둔다(SymPy 판정 권위는 이 모듈 하나).
# ──────────────────────────────────────────────────────────────────────────
def condition_relation(condition: str) -> tuple[str, frozenset[str]] | None:
    """조건 1개의 (관계 연산자, 자유변수 이름 집합). 파싱 불가·미지원 관계면 None.

    연산자는 `_parse_condition` 과 같다 — 등식은 `"=="`, 부등식·≠ 는 `>`·`<`·`>=`·`<=`·`!=`.
    """
    try:
        residual, op = _parse_condition(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 None(호출부가 판정 불가로 드러낸다)
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return None
    return op, frozenset(str(symbol) for symbol in residual.free_symbols)


def split_equation_domain(
    conditions: str | Sequence[str],
) -> tuple[str, tuple[str, ...], str] | None:
    """조건을 (단일 등식, 도메인 부등식들, 변수)로 가른다 — 그 모양이 아니면 None.

    "그 모양" = 조건 전부가 **같은 단일 변수** 하나만 자유변수로 갖고, 그중 등식이 **정확히 하나**,
    나머지는 부등식·≠ 인 것(예 `["3*a**2 = 108", "a > 0"]`). 도메인 부등식이 없는 단일 등식도
    `(등식, (), 변수)` 로 돌린다. 등식이 둘 이상(연립)·변수가 둘 이상·파싱 불가는 None — 근 선택의
    뜻이 불명확하므로 호출부가 판정 불가로 처리한다.
    """
    items = [conditions] if isinstance(conditions, str) else list(conditions)
    equation: str | None = None
    domain: list[str] = []
    var: str | None = None
    for condition in items:
        relation = condition_relation(condition)
        if relation is None or len(relation[1]) != 1:
            return None
        op, names = relation
        name = next(iter(names))
        if var is not None and name != var:
            return None
        var = name
        if op == "==":
            if equation is not None:
                return None  # 등식 둘 이상 — 연립이다.
            equation = condition
        else:
            domain.append(condition)
    if equation is None or var is None:
        return None
    return equation, tuple(domain), var


# ──────────────────────────────────────────────────────────────────────────
# 허용 목록(allowlist) 다항 등식 — 해석 단계 '증명'이 믿는 유일한 등식 꼴
# (P3-71 · PR #1703 4차 검토)
# ──────────────────────────────────────────────────────────────────────────
# 금지 목록(분모·초월 함수…)은 표기 변형 하나로 뚫렸다(`(…).doit()` 래퍼가 파싱 중
# 약분을 실행했고, `exp(-log(x - 2))`·`(x - 2)**0` 은 분모 없이 같은 효과를 냈다).
# 그래서 거꾸로, 조건 원문의 **파이썬 구문 나무**(`ast` — 아무것도 실행하지 않는다)를
# 아래 허용 노드만으로 직접 SymPy 식으로 세운다.
#   · 정수 리터럴(크기 상한) · 기호(평범한 식별자이고 SymPy 이름이 아닌 것)
#   · `+`·`-`·`*`·단항 `±` · `/` 는 분모가 0 아닌 **상수**일 때만
#   · `**` 는 지수가 양의 정수 리터럴일 때만
#   · `Derivative(식, 기호)`·`.doit()`·`.subs(기호, 허용 식)` — 다항식에 대한 미분·대입은 다항식이다
# 그 밖의 노드(함수 전부·실수 리터럴·음수/0/분수/기호 지수·변수 분모·다른 메서드)가 하나라도 있으면
# 인증하지 않는다. 세운 식은 정의상 유리 계수 다항식이라 약분·정의역 문제가 생길 수 없다. 원문은
# 그 전에 공식 안전 진입점(`safe_sympify`)의 문자·예산 검사를 통과해야 한다(R22-03).
_CERT_MAX_INT = 10**30
_CERT_MAX_EXPONENT = 64
_CERT_MAX_DEGREE = 24
_CERT_RELATION: re.Pattern[str] = re.compile(r"(==|!=|<=|>=|<|>|=)")
_CERT_ZERO = 1e-40  # 정확 근(대수적 수)을 60자리로 평가해 0 판정할 때의 문턱 — 근 분리와 무관한 값
_CERT_PRECISION = 60


class _NotCertified(Exception):  # noqa: N818 — 오류가 아니라 '인증 안 됨' 신호
    """허용 목록 밖의 노드 — 인증하지 않는다(판정 불가)."""


def _certified_build(node: ast.AST) -> sympy.Expr:
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool) or not isinstance(value, int) or abs(value) > _CERT_MAX_INT:
            raise _NotCertified("정수 리터럴만")
        return sympy.Integer(value)
    if isinstance(node, ast.Name):
        if not node.id.isidentifier() or len(node.id) > 30 or hasattr(sympy, node.id):
            raise _NotCertified("평범한 기호만")
        return sympy.Symbol(node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _certified_build(node.operand)
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BinOp):
        left = _certified_build(node.left)
        if isinstance(node.op, ast.Pow):
            exponent = node.right
            if not (
                isinstance(exponent, ast.Constant)
                and type(exponent.value) is int
                and 1 <= exponent.value <= _CERT_MAX_EXPONENT
            ):
                raise _NotCertified("지수는 양의 정수 리터럴만")
            return sympy.Pow(left, exponent.value)
        right = _certified_build(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right.free_symbols or right == 0:
                raise _NotCertified("나눗셈은 0 아닌 상수로만")
            return left / right
        raise _NotCertified("허용되지 않는 이항 연산")
    if isinstance(node, ast.Call) and not node.keywords:
        func = node.func
        if isinstance(func, ast.Name) and func.id == "Derivative" and len(node.args) == 2:
            inner = _certified_build(node.args[0])
            variable = _certified_build(node.args[1])
            if not isinstance(variable, sympy.Symbol):
                raise _NotCertified("미분 변수는 기호만")
            return sympy.diff(inner, variable)
        if isinstance(func, ast.Attribute):
            if func.attr == "doit" and not node.args:
                return _certified_build(func.value)
            if func.attr == "subs" and len(node.args) == 2:
                base = _certified_build(func.value)
                target = _certified_build(node.args[0])
                replacement = _certified_build(node.args[1])
                if not isinstance(target, sympy.Symbol):
                    raise _NotCertified("대입 대상은 기호만")
                return base.subs(target, replacement)
    raise _NotCertified(f"허용되지 않는 노드 {type(node).__name__}")


def _certified_expression(text: str) -> sympy.Expr | None:
    """식 원문 → 허용 목록으로만 세운 유리 계수 다항식. 인증 불가면 None."""
    if not text.strip():
        return None
    try:
        safe_sympify(text)  # 공식 진입점의 허용 문자·예산 검사를 먼저 통과해야 한다(R22-03).
        tree = ast.parse(text.strip(), mode="eval")
        return _certified_build(tree.body)
    except Exception as exc:  # noqa: BLE001 — 인증 불가는 None(판정 불가로 드러난다)
        logger.debug("verify_answer 인증 거부: %s", type(exc).__name__)
        return None


def certified_polynomial(text: str, var: str) -> sympy.Poly | None:
    """식 원문이 허용 목록 구조의 `var` 다항식(유리 계수·다른 기호 없음)이면 Poly, 아니면 None."""
    expr = _certified_expression(text)
    symbol = sympy.Symbol(var)
    if expr is None or not expr.free_symbols <= {symbol}:
        return None
    poly = sympy.Poly(sympy.expand(expr), symbol)
    if poly.domain not in (sympy.ZZ, sympy.QQ) or poly.degree() > _CERT_MAX_DEGREE:
        return None
    return poly


def _certified_relation(condition: str, var: str) -> tuple[sympy.Poly, str] | None:
    """관계 원문 → (lhs − rhs 의 인증 다항식, 연산자). 관계가 정확히 하나가 아니면 None."""
    parts = _CERT_RELATION.split(condition)
    if len(parts) != 3:
        return None
    left, token, right = parts
    lhs = certified_polynomial(left, var)
    rhs = certified_polynomial(right, var)
    if lhs is None or rhs is None:
        return None
    return lhs - rhs, ("==" if token in ("=", "==") else token)


def _certified_truth(
    residual: sympy.Poly, base: sympy.Poly, root: sympy.Expr, op: str
) -> bool | None:
    """정확 근 `root`(인증 다항식 `base` 의 근)에서 `residual op 0` 의 진리값 — 정확 판정.

    0 판정은 수치가 아니라 대수로 한다: residual(root) = 0 ⇔ root 가 gcd(base, residual) 의 근.
    0 이 아님이 확정되면 부호는 고정밀(60자리) 평가로 정한다 — 그 값이 문턱 아래면 판정 불가.
    """
    common = sympy.gcd(base, residual)
    zero = False
    if common.degree() >= 1:
        target = sympy.N(root, _CERT_PRECISION)
        zero = any(
            abs(sympy.N(r, _CERT_PRECISION) - target) < _CERT_ZERO for r in sympy.real_roots(common)
        )
    if zero:
        sign = 0
    else:
        value = sympy.N(residual.as_expr().subs(residual.gen, root), _CERT_PRECISION)
        if not value.is_real or abs(value) < _CERT_ZERO:
            return None
        sign = 1 if value > 0 else -1
    return {
        "==": sign == 0,
        "!=": sign != 0,
        ">": sign > 0,
        "<": sign < 0,
        ">=": sign >= 0,
        "<=": sign <= 0,
    }.get(op)


def certified_root_sets(
    condition: str, domain: Sequence[str], var: str
) -> tuple[list[sympy.Expr], list[sympy.Expr]] | None:
    """허용 목록 다항 등식의 (서로 다른 실근 전부, 그중 도메인을 만족하는 근) — 정확값·오름차순.

    등식·도메인 부등식 어느 하나라도 인증 불가거나, 어느 근에서든 도메인 판정이 불가하면 None.
    실근은 수치 허용치가 아니라 정확 계산(`real_roots` · 제곱 인수 제거)으로 센다 —
    허수부가 아주 작은 근(`(x - 1)**2 + 1/10**20`)을 실근으로 세지 않는다.
    """
    relation = _certified_relation(condition, var)
    if relation is None or relation[1] != "==" or relation[0].degree() < 1:
        return None
    base = relation[0].sqf_part()
    roots = list(sympy.real_roots(base))
    constraints: list[tuple[sympy.Poly, str]] = []
    for text in domain:
        parsed = _certified_relation(text, var)
        if parsed is None or parsed[1] == "==":
            return None
        constraints.append(parsed)
    admissible: list[sympy.Expr] = []
    for root in roots:
        truths = [_certified_truth(residual, base, root, op) for residual, op in constraints]
        if any(truth is None for truth in truths):
            return None
        if all(truths):
            admissible.append(root)
    return roots, admissible


def match_root(value: str, roots: Sequence[sympy.Expr], *, tol: float = 1e-9) -> int | None:
    """값이 가리키는 정확 근의 위치 — 허용치 안에 근이 **정확히 하나**일 때만, 아니면 None.

    개수는 정확하게 세고 대조만 수치로 한다(근사 소수 근 `1.4142135623730951` 도 √2 로 대조된다).
    """
    try:
        number = _real_value(safe_sympify(value), tol)
    except Exception as exc:  # noqa: BLE001 — 값 파싱 불가는 None
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return None
    if number is None:
        return None
    hits = [
        index
        for index, root in enumerate(roots)
        if (approx := _real_value(root, tol)) is not None and _approx_equal(number, approx, tol)
    ]
    return hits[0] if len(hits) == 1 else None


# ──────────────────────────────────────────────────────────────────────────
# 원문 정의역 판정(P3-75) — 평가 파싱의 자동 약분이 지운 '정의되지 않는 점'을 되살린다
# ──────────────────────────────────────────────────────────────────────────
# `safe_sympify`(evaluate=True)는 식을 세우는 순간 `x*(x - 2)/(x - 2)` → `x`,
# `(x - 2)**3/(x - 2)**2` → `x - 2`, `(x - 2)**0` → `1` 로 접는다. 접힌 식은 원문이 정의된 곳에서는
# 원문과 같지만, 원문이 **정의되지 않는 점**(분모 0·0의 0제곱·log 0 …)까지 정의된 것처럼 보이게
# 한다. 그래서 그 점(무연근)이 잔차 0 으로 Tier1 을 통과했다(RF3·RF4).
#
# 금지 목록(분모 탐지)은 표기 변형(`.doit()` 래퍼·`exp(-log(x - 2))`·0 지수)에 뚫렸다(P3-71 4차
# 검토). 그래서 P3-71 의 허용 목록(`_certified_build`)과 같은 원리로 간다 — 조건 원문의 **파이썬
# 구문 나무**(`ast` · 아무것도 실행하지 않는다)를 아래 허용 노드만으로 **그 점에서 한 노드씩**
# 평가한다. 노드 하나하나가 숫자로 계산되므로 기호 약분이 끼어들 틈이 없다.
#   · 정수·실수 리터럴 · 상수 `pi`·`E`·`I` · 값이 주어진 이름(답·샘플 점)
#   · `+`·`-`·`*`·`/`·`**`(`^`)·단항 `±`
#   · 허용 함수(`_DEFINED_FUNCTIONS` — 중·고교 표준 함수 · safe_parse 허용 목록의 부분집합)
#   · `Derivative(f, v…)`(f 가 열린 정의역에서 해석적인 꼴일 때만) · `.doit()` · `.subs(기호, 식)`
#   · `Integral(f, (v, a, b))`(f 가 전해석 함수 꼴일 때만)
# 판정은 3상태다.
#   · DEFINED — 모든 노드가 유한한 값으로 정의된다.
#   · UNDEFINED — 어느 노드가 그 점에서 **정확히** 정의되지 않는다(분모가 정확히 0·0 의
#     0 이하 제곱·SymPy 가 무한/NaN 을 낸 함수값). 원문에서 그 값이 정의되지 않음이 확정된다.
#   · UNKNOWN — 허용 노드 밖·영 여부를 정확히 못 가림·실수 입력에서 실수 아닌 중간값(실수 범위
#     정의역을 판정하지 않는다)·계산 예산 초과. 판정 불가다(pass 로 위장하지 않는다).
_DEFINED: Final = "defined"
_UNDEFINED: Final = "undefined"
_UNKNOWN: Final = "unknown"
DefinednessState = Literal["defined", "undefined", "unknown"]

# 허용 함수 → SymPy 함수. 값은 그 점의 인자값에 바로 적용한다(인자는 이미 숫자다).
_DEFINED_FUNCTIONS: dict[str, Callable[..., sympy.Expr]] = {
    "sin": sympy.sin,
    "cos": sympy.cos,
    "tan": sympy.tan,
    "cot": sympy.cot,
    "sec": sympy.sec,
    "csc": sympy.csc,
    "asin": sympy.asin,
    "acos": sympy.acos,
    "atan": sympy.atan,
    "acot": sympy.acot,
    "sinh": sympy.sinh,
    "cosh": sympy.cosh,
    "tanh": sympy.tanh,
    "exp": sympy.exp,
    "log": sympy.log,
    "ln": sympy.log,
    "sqrt": sympy.sqrt,
    "cbrt": sympy.cbrt,
    "root": sympy.root,
    "Abs": sympy.Abs,
    "abs": sympy.Abs,
    "sign": sympy.sign,
    "floor": sympy.floor,
    "ceiling": sympy.ceiling,
    "gcd": sympy.gcd,
    "lcm": sympy.lcm,
    "factorial": sympy.factorial,
    "binomial": sympy.binomial,
    "Max": sympy.Max,
    "Min": sympy.Min,
    "max": sympy.Max,
    "min": sympy.Min,
}
# 인자 개수 — 그 밖의 개수는 판정 불가(SymPy 가 다른 뜻으로 받을 수 있다).
_FUNCTION_ARITY: dict[str, tuple[int, ...]] = {
    "log": (1, 2),
    "ln": (1,),
    "root": (2,),
    "gcd": (2,),
    "lcm": (2,),
    "binomial": (2,),
    "Max": (2, 3, 4),
    "Min": (2, 3, 4),
    "max": (2, 3, 4),
    "min": (2, 3, 4),
}
# 미분 안쪽에 허용하는 함수 — 정의역이 열린 집합이고 그 위에서 해석적이다. `acot` 은 SymPy
# 정의상 0 에서 불연속(−π/2 → π/2 도약)이라 뺀다(P3-75 검토 6). 그래서 '그 점에서
# 정의됨' 이 곧 '그 점 근방에서 정의·미분 가능' 이다(√·|·|·floor 처럼 정의되는데 미분 불가인 점이
# 있는 함수는 뺀다).
_SMOOTH_FUNCTIONS: frozenset[str] = frozenset(
    {"sin", "cos", "tan", "cot", "sec", "csc", "atan", "sinh", "cosh", "tanh", "exp"}
    | {"log", "ln"}
)
# 적분 안쪽에 허용하는 함수 — 실수 전체에서 정의·연속(전해석)이다.
_ENTIRE_FUNCTIONS: frozenset[str] = frozenset({"sin", "cos", "exp", "sinh", "cosh"})
_CONSTANTS: dict[str, sympy.Expr] = {"pi": sympy.pi, "E": sympy.E, "I": sympy.I}
# 정수 인자 함수 — factorial·binomial 은 음이 아닌 정수, gcd·lcm 은 정수에서만 교과 정의다.
_INTEGER_FUNCTIONS: frozenset[str] = frozenset({"factorial", "binomial", "gcd", "lcm"})
_DEF_ZERO = sympy.Float("1e-40")  # 정확 값(대수적 수 등)의 60자리 평가에서 '0 일 수 있음' 문턱
_DEF_FLOAT_ZERO = 1e-9  # 근사 소수가 섞인 값의 '0 일 수 있음' 문턱(Tier1 허용치와 같다)
_DEF_MAX_POW_BITS = 100_000  # 정확 거듭제곱 결과 크기 상한(비트) — 넘으면 판정 불가
# 120자리 평가의 허수부가 이보다 작으면 반올림 잔여로 본다(`_root_is_real`).
_DEF_ROUNDOFF = sympy.Float("1e-100")


class _DefUndefined(Exception):  # noqa: N818 — 오류가 아니라 '정의되지 않음' 신호
    """그 점에서 원문이 정의되지 않음이 확정됐다."""


class _DefUnknown(Exception):  # noqa: N818 — 오류가 아니라 '판정 불가' 신호
    """허용 노드 밖이거나 정확히 판정하지 못했다. `code` 는 원인 위치(디버그 로그로 남긴다)."""

    def __init__(self, code: str = "unspecified") -> None:
        super().__init__(code)
        self.code = code


def _relation_sides(condition: str) -> list[str]:
    """조건 원문 → 평가할 식 원문 목록. `_parse_condition` 과 같은 순서로 관계를 가른다."""
    text = condition.strip()
    if "!=" in text:
        return list(text.split("!=", 1))
    if "==" in text:
        return list(text.split("==", 1))
    if "=" in text and not any(token in text for token in ("<", ">")):
        return list(text.split("=", 1))
    return [text]


def _zero_state(value: sympy.Expr) -> bool | None:
    """값이 0 인가 — True(정확히 0)·False(0 아님)·None(못 가림). 근사 소수는 허용치로 본다."""
    if value.has(sympy.Float):
        # 근사 소수가 섞인 값은 0 을 정확히 확정하지 않는다(반올림 0 일 수 있다) — 작으면 못 가림.
        try:
            magnitude = abs(complex(value.evalf()))
        except (TypeError, ValueError) as exc:
            logger.debug("verify_answer 정의역 판정 회피: %s", type(exc).__name__)
            return None
        return None if magnitude < _DEF_FLOAT_ZERO else False
    if value == 0:
        return True
    exact = value.is_zero
    if exact is not None:
        return bool(exact)
    try:
        approx = sympy.N(value, _CERT_PRECISION)
    except Exception as exc:  # noqa: BLE001 — 평가 불가는 '못 가림'
        logger.debug("verify_answer 정의역 판정 회피: %s", type(exc).__name__)
        return None
    if not approx.is_number or approx.has(sympy.nan, sympy.zoo):
        return None
    return None if abs(approx) < _DEF_ZERO else False


def _checked(value: sympy.Expr, real_inputs: bool) -> sympy.Expr:
    """노드 값 검사 — 무한·NaN 은 정의되지 않음, 실수 입력에서 실수 아닌 값은 판정 불가."""
    if value.has(sympy.zoo, sympy.nan, sympy.oo, -sympy.oo) or value.is_finite is False:
        raise _DefUndefined
    if real_inputs and value.is_real is False:
        raise _DefUnknown("non_real_intermediate")
    try:
        ensure_within_budget(value)
    except Exception as exc:  # noqa: BLE001 — 예산 초과는 판정 불가
        logger.debug("verify_answer 정의역 판정 회피: %s", type(exc).__name__)
        raise _DefUnknown("budget") from exc
    return value


def _free_names(node: ast.AST, bound: frozenset[str] = frozenset()) -> set[str]:
    """식 나무의 값 이름(함수 이름·상수 제외).

    `.subs(t, …)` 의 t·`Integral` 의 적분 변수는 그 안에서 묶인 이름이라 뺀다(`Derivative` 의
    미분 변수는 그 점의 값이 필요해 묶지 않는다).
    """
    if isinstance(node, ast.Name):
        hidden = bound | frozenset(_CONSTANTS) | {"oo", "True", "False", "None"}
        return set() if node.id in hidden else {node.id}
    if isinstance(node, ast.Call):
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "subs"
            and len(node.args) == 2
            and isinstance(node.args[0], ast.Name)
        ):
            inner = _free_names(func.value, bound | {node.args[0].id})
            return inner | _free_names(node.args[1], bound)
        if (
            isinstance(func, ast.Name)
            and func.id == "Integral"
            and len(node.args) == 2
            and isinstance(node.args[1], ast.Tuple)
            and node.args[1].elts
            and isinstance(node.args[1].elts[0], ast.Name)
        ):
            variable = node.args[1].elts[0].id
            names: set[str] = _free_names(node.args[0], bound | {variable})
            for limit in node.args[1].elts[1:]:
                names |= _free_names(limit, bound)
            return names
        names = set() if isinstance(func, ast.Name) else _free_names(func, bound)
        for arg in node.args:
            names |= _free_names(arg, bound)
        return names
    collected: set[str] = set()
    for child in ast.iter_child_nodes(node):
        collected |= _free_names(child, bound)
    return collected


def _subtree_expr(node: ast.AST) -> sympy.Expr:
    """하위 나무 → SymPy 식(평가 파싱). 호출부가 이미 꼴(해석적·전해석)을 확인했다."""
    return safe_sympify(ast.unparse(node))


class _DefinednessEvaluator:
    """허용 노드만으로 원문 식을 한 점에서 노드별로 평가한다(`_DefUndefined`·`_DefUnknown` 신호)."""

    def __init__(self, real_inputs: bool) -> None:
        self.real_inputs = real_inputs

    def smooth(
        self,
        node: ast.AST,
        variables: frozenset[str],
        env: Mapping[str, sympy.Expr],
        *,
        entire: bool,
    ) -> bool:
        """`variables`(미분·적분 변수)의 함수로서 '열린 정의역에서 해석적'(entire=False) /
        '전해석'(entire=True) 꼴인가. 변수를 담지 않은 하위 나무는 그 점의 상수라 값으로 본다."""
        if not (_free_names(node) & variables):
            # 변수와 무관한 하위 나무는 그 점의 상수다 — 그 값이 정의되는지만 본다(정의되지 않으면
            # 신호가 그대로 올라간다 — 적분 안의 상수 `a*(a - 2)/(a - 2)` 도 자동 약분 전에 잡힌다).
            self.value(node, env)
            return True
        if isinstance(node, ast.Name):
            return True
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return self.smooth(node.operand, variables, env, entire=entire)
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
                return self.smooth(node.left, variables, env, entire=entire) and self.smooth(
                    node.right, variables, env, entire=entire
                )
            if isinstance(node.op, ast.Div):
                if _free_names(node.right) & variables:
                    # 전해석 꼴은 변수 분모를 받지 않는다 — 적분 구간 위에서 0 이 될 수 있다.
                    if entire:
                        return False
                else:
                    # 변수 무관 분모는 그 점의 상수다 — 0 이면 원문이 정의되지 않는다
                    # (`Integral(t*(x - 2)/(x - 2), …)` 의 x = 2 · P3-75 검토 1).
                    zero = _zero_state(self.value(node.right, env))
                    if zero is True:
                        raise _DefUndefined
                    if zero is None:
                        raise _DefUnknown("smooth_denominator_zero_unknown")
                return self.smooth(node.left, variables, env, entire=entire) and self.smooth(
                    node.right, variables, env, entire=entire
                )
            if isinstance(node.op, (ast.Pow, ast.BitXor)):
                return self._smooth_power(node, variables, env, entire=entire)
            return False
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            if node.func.id == "Derivative":
                # 해석 함수의 도함수는 같은 열린 정의역에서 해석적이다(중첩 미분 — 속도·가속도 꼴).
                if len(node.args) < 2 or not all(isinstance(a, ast.Name) for a in node.args[1:]):
                    return False
                inner_vars = variables | {cast(ast.Name, a).id for a in node.args[1:]}
                return self.smooth(node.args[0], inner_vars, env, entire=entire)
            allowed = _ENTIRE_FUNCTIONS if entire else _SMOOTH_FUNCTIONS
            return (
                node.func.id in allowed
                and len(node.args) == 1
                and self.smooth(node.args[0], variables, env, entire=entire)
            )
        return False

    def _smooth_power(
        self,
        node: ast.BinOp,
        variables: frozenset[str],
        env: Mapping[str, sympy.Expr],
        *,
        entire: bool,
    ) -> bool:
        """거듭제곱 꼴 — 지수가 변수와 무관하면 그 값이 정수(전해석이면 0 이상)여야 하고, 지수가
        변수를 담으면 밑이 변수와 무관한 양수여야 한다(b**x = exp(x·log b))."""
        if not (_free_names(node.right) & variables):
            exponent = self.value(node.right, env)
            if not exponent.is_Integer or (entire and exponent.is_negative):
                return False
            return self.smooth(node.left, variables, env, entire=entire)
        if _free_names(node.left) & variables:
            return False
        return bool(self.value(node.left, env).is_positive) and self.smooth(
            node.right, variables, env, entire=entire
        )

    def value(self, node: ast.AST, env: Mapping[str, sympy.Expr]) -> sympy.Expr:
        if self.real_inputs and not isinstance(node, ast.Name) and not _free_names(node):
            # 이름이 하나도 없는 상수 하위 나무 — 실수 아닌 중간값은 답과 무관한 의도된 복소
            # 산술이다(`sqrt(-4)*sqrt(-9)`). 실수 범위 규칙은 답에 의존하는 노드에만 건다.
            return _DefinednessEvaluator(False).value(node, env)
        return self._value(node, env)

    def _value(self, node: ast.AST, env: Mapping[str, sympy.Expr]) -> sympy.Expr:
        if isinstance(node, ast.Constant):
            raw = node.value
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise _DefUnknown("literal_not_allowed")
            return sympy.Integer(raw) if isinstance(raw, int) else sympy.Float(repr(raw))
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            if node.id in _CONSTANTS:
                return _CONSTANTS[node.id]
            # 값이 없는 이름(자유 기호)·oo 등 — 그 점이 정해지지 않았다.
            raise _DefUnknown("unbound_name")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = self.value(node.operand, env)
            return -operand if isinstance(node.op, ast.USub) else operand
        if isinstance(node, ast.BinOp):
            return self._binop(node, env)
        if isinstance(node, ast.Call) and not node.keywords:
            return self._call(node, env)
        raise _DefUnknown("node_not_allowed")

    def _binop(self, node: ast.BinOp, env: Mapping[str, sympy.Expr]) -> sympy.Expr:
        left = self.value(node.left, env)
        right = self.value(node.right, env)
        if isinstance(node.op, ast.Add):
            return _checked(left + right, self.real_inputs)
        if isinstance(node.op, ast.Sub):
            return _checked(left - right, self.real_inputs)
        if isinstance(node.op, ast.Mult):
            return _checked(left * right, self.real_inputs)
        if isinstance(node.op, ast.Div):
            zero = _zero_state(right)
            if zero is True:
                raise _DefUndefined
            if zero is None:
                raise _DefUnknown("binop")
            return _checked(left / right, self.real_inputs)
        if isinstance(node.op, (ast.Pow, ast.BitXor)):
            return self._power(left, right)
        raise _DefUnknown("binop")

    def _power(self, base: sympy.Expr, exponent: sympy.Expr) -> sympy.Expr:
        zero = _zero_state(base)
        if zero is None:
            raise _DefUnknown("power")
        if zero:
            # 0 의 거듭제곱 — 지수가 양수일 때만 정의된다(0**0·0**음수는 정의되지 않음).
            positive = exponent.is_positive
            if positive is None:
                raise _DefUnknown("power")
            if not positive:
                raise _DefUndefined
            return sympy.Integer(0)
        if exponent.is_Integer and base.is_number:
            try:
                magnitude = abs(complex(base.evalf()))
            except (TypeError, ValueError) as exc:
                logger.debug("verify_answer 정의역 판정 회피: %s", type(exc).__name__)
                raise _DefUnknown("power_magnitude") from exc
            bits = abs(int(exponent)) * max(1.0, math.log2(magnitude + 2.0))
            if bits > _DEF_MAX_POW_BITS:
                raise _DefUnknown("power")
        return _checked(sympy.Pow(base, exponent), self.real_inputs)

    def _call(self, node: ast.Call, env: Mapping[str, sympy.Expr]) -> sympy.Expr:
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr == "doit" and not node.args:
                return self.value(func.value, env)
            if func.attr == "subs" and len(node.args) == 2 and isinstance(node.args[0], ast.Name):
                replacement = self.value(node.args[1], env)
                return self.value(func.value, {**env, node.args[0].id: replacement})
            raise _DefUnknown("call")
        if not isinstance(func, ast.Name):
            raise _DefUnknown("call")
        if func.id == "Derivative":
            return self._derivative(node, env)
        if func.id == "Integral":
            return self._integral(node, env)
        apply = _DEFINED_FUNCTIONS.get(func.id)
        if apply is None or len(node.args) not in _FUNCTION_ARITY.get(func.id, (1,)):
            raise _DefUnknown("call")
        args = [self.value(arg, env) for arg in node.args]
        if func.id in _INTEGER_FUNCTIONS and not all(
            arg.is_Integer and (func.id in ("gcd", "lcm") or arg.is_nonnegative) for arg in args
        ):
            # 교과 정의는 (음이 아닌) 정수에서만이다 — 일반화 값(binomial(-1, 1) = -1)을 정의됨으로
            # 읽지 않는다.
            raise _DefUnknown("integer_function_domain")
        # 함수의 특이점(log 0·tan(pi/2)·밑 1 의 log·factorial(-1) …)은 SymPy 가 무한/NaN 으로 낸다.
        return _checked(apply(*args), self.real_inputs)

    def _derivative(self, node: ast.Call, env: Mapping[str, sympy.Expr]) -> sympy.Expr:
        """`Derivative(f, v…)` 의 그 점 값 — f 가 열린 정의역에서 해석적인 꼴이고 그 점에서
        정의될 때만(그러면 그 점 근방에서 정의·미분 가능하다). 미분 변수의 값은 env 에 있어야
        한다."""
        if len(node.args) < 2 or not all(isinstance(a, ast.Name) for a in node.args[1:]):
            raise _DefUnknown("derivative")
        inner = node.args[0]
        names = [cast(ast.Name, a).id for a in node.args[1:]]
        if not all(n in env for n in names):
            raise _DefUnknown("derivative")
        if not self.smooth(inner, frozenset(names), env, entire=False):
            raise _DefUnknown("derivative")
        self.value(inner, env)  # 그 점에서 원문 f 가 정의되는가(정의되지 않으면 신호가 올라간다)
        try:
            expr = _subtree_expr(inner)
            # 중첩 Derivative 는 평가 파싱에서 미계산으로 남는다 — 미분 뒤 doit 으로 끝까지
            # 계산한다.
            derived = sympy.diff(expr, *[sympy.Symbol(n) for n in names]).doit()
            point = {sympy.Symbol(k): v for k, v in env.items()}
            value = safe_subs(derived, point)
        except Exception as exc:  # noqa: BLE001 — 미분·대입 불가는 판정 불가
            logger.debug("verify_answer 정의역 판정 회피: %s", type(exc).__name__)
            raise _DefUnknown("derivative") from exc
        if value.free_symbols:
            raise _DefUnknown("derivative")
        return _checked(value, self.real_inputs)

    def _integral(self, node: ast.Call, env: Mapping[str, sympy.Expr]) -> sympy.Expr:
        """`Integral(f, (v, a, b))` — f 가 전해석 꼴이고 끝점이 유한할 때만(정적분이 정의된다)."""
        if len(node.args) != 2 or not isinstance(node.args[1], ast.Tuple):
            raise _DefUnknown("integral")
        limits = node.args[1].elts
        if len(limits) != 3 or not isinstance(limits[0], ast.Name):
            raise _DefUnknown("integral")
        inner = node.args[0]
        bound = limits[0].id
        lower = self.value(limits[1], env)
        upper = self.value(limits[2], env)
        outer = {k: v for k, v in env.items() if k != bound}
        if not _free_names(inner, frozenset({bound})) <= set(outer):
            raise _DefUnknown("integral")
        if not self.smooth(inner, frozenset({bound}), outer, entire=True):
            raise _DefUnknown("integral")
        try:
            expr = _subtree_expr(inner)
            point = {sympy.Symbol(k): v for k, v in outer.items()}
            integrand = safe_subs(expr, point)
            if integrand.has(sympy.zoo, sympy.nan, sympy.oo, -sympy.oo):
                raise _DefUndefined
            value = sympy.Integral(integrand, (sympy.Symbol(bound), lower, upper))
        except _DefUndefined:
            raise
        except Exception as exc:  # noqa: BLE001 — 구성 불가는 판정 불가
            logger.debug("verify_answer 정의역 판정 회피: %s", type(exc).__name__)
            raise _DefUnknown("integral") from exc
        if value.free_symbols:
            raise _DefUnknown("integral")
        return value


def condition_definedness(condition: str, values: Mapping[str, sympy.Expr]) -> DefinednessState:
    """조건 원문이 `values`(이름 → 값) 의 점에서 정의되는가 — defined·undefined·unknown.

    평가 파싱의 자동 약분 전에, 원문 구문 나무를 허용 노드만으로 그 점에서 노드별로 평가한다
    (위 절 설명). undefined 는 '원문에서 그 값이 정의되지 않음' 이 정확히 확정된 경우뿐이다.
    """
    sides = _relation_sides(condition)
    if any(not side.strip() for side in sides):
        return _UNKNOWN
    real_inputs = all(value.is_real is True for value in values.values())
    try:
        trees = []
        for side in sides:
            safe_sympify(side)
            tree = ast.parse(side.strip().replace("^", "**"), mode="eval").body
            trees.append(tree)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가·거부는 판정 불가
        logger.debug("verify_answer 정의역 판정 회피: %s", type(exc).__name__)
        return _UNKNOWN
    uses_imaginary = any(
        isinstance(child, ast.Name) and child.id == "I"
        for tree in trees
        for child in ast.walk(tree)
    )
    if uses_imaginary:
        real_inputs = False  # 허수 단위를 쓰는 조건 — 실수 아닌 중간값이 정상이다
    evaluator = _DefinednessEvaluator(real_inputs)
    try:
        for tree in trees:
            for part in _comparison_parts(tree):
                evaluator.value(part, values)
    except _DefUndefined:
        return _UNDEFINED
    except _DefUnknown as unknown:
        logger.debug("verify_answer 정의역 판정 불가: %s", unknown.code)
        return _UNKNOWN
    except Exception as exc:  # noqa: BLE001 — 예상 밖 예외도 판정 불가(pass 위장 금지)
        logger.debug("verify_answer 정의역 판정 회피: %s", type(exc).__name__)
        return _UNKNOWN
    return _DEFINED


def _condition_names(condition: str) -> frozenset[str]:
    """조건 원문의 값 이름(함수·상수·묶인 이름 제외) — 구문 나무로 모은다(실행하지 않는다).

    못 읽는 쪽은 건너뛴다(그 이름은 정의역 판정에서 '값 없는 이름' 으로 판정 불가가 된다).
    """
    names: set[str] = set()
    for side in _relation_sides(condition):
        try:
            tree = ast.parse(side.strip().replace("^", "**"), mode="eval")
        except SyntaxError:
            continue
        names |= _free_names(tree)
    return frozenset(names)


def _comparison_parts(tree: ast.AST) -> list[ast.AST]:
    """관계 나무를 비교 대상 식들로 편다(`a < b`·`Eq(a, b)`). 관계가 아니면 그 자신."""
    if isinstance(tree, ast.Compare) and len(tree.ops) == 1:
        return [tree.left, *tree.comparators]
    if (
        isinstance(tree, ast.Call)
        and isinstance(tree.func, ast.Name)
        and tree.func.id in ("Eq", "Ne", "Lt", "Le", "Gt", "Ge")
        and len(tree.args) == 2
        and not tree.keywords
    ):
        return list(tree.args)
    return [tree]


RootReality = Literal["real", "vanishing", "nonreal"]


def _root_is_real(root: sympy.Expr) -> bool | None:
    """근이 실수인가 — True·False·None(못 가림). 근거의 종류는 `_root_reality` 가 낸다."""
    reality = _root_reality(root)
    return None if reality is None else reality != "nonreal"


def _root_reality(root: sympy.Expr) -> RootReality | None:
    """근의 실수 여부와 그 근거 — SymPy 가정(`is_real`)이 정하면 그대로(real·nonreal), 못 정하면
    120자리 평가의 허수부가 정확히 0 이면 real·문턱보다 크고 정밀도에 따라 변하지 않으면 nonreal·
    허수부가 정밀도와 함께 계속 사라지면 vanishing(실근 *후보* — 호출부가 SymPy 실근 개수로 맞춘다)·
    그 밖은 못 가림(None). Tier1 허용치(1e-9)로 실수라 부르지 않는다 — 허수부 1e-10 인 근이 실근으로
    세어지던 결함(P3-75 ⑤(d)). 반올림 문턱(1e-100) 아래의 0 아닌 허수부도 그대로 실근이라 부르지
    않는다(P3-79 ⑦)."""
    real = root.is_real
    if real is not None:
        return "real" if real else "nonreal"
    try:
        low = sympy.N(root, _CERT_PRECISION).as_real_imag()[1]
        high = sympy.N(root, 2 * _CERT_PRECISION).as_real_imag()[1]
    except Exception as exc:  # noqa: BLE001 — 평가 불가는 못 가림
        logger.debug("verify_answer 실근 판정 회피: %s", type(exc).__name__)
        return None
    if not (low.is_number and high.is_number):
        return None
    if high == 0:
        return "real"
    if abs(high) < _DEF_ROUNDOFF:
        # P3-79 ⑦ — 문턱 아래의 허수부를 그대로 실근이라 부르지 않는다. 종전에는 여기서 곧바로
        # 실근이라 불러, 허수부 ~4.8e-101 인 비실근(`(x - sqrt(2))**2*(x + 3) + 10**(-200)`)을
        # 실근으로 셌다. 정밀도를 다시 두 배로 올려, 허수부가 그 정밀도와 함께 계속 사라질 때만
        # (evalf 가 0 을 유효숫자 없는 상한 `0.e-128` 로 낸다 — 카르다노 근호식의 실근
        # `x**3 - 3*sqrt(2)*x + 1`) 반올림 잔여로 본다. 값이 그대로 남으면 진짜 허수부라 판정 불가.
        # 사라지는 상한도 증명은 아니다 — 호출부가 SymPy 실근 개수(`count_roots`)로 맞춘다.
        try:
            higher = sympy.N(root, 4 * _CERT_PRECISION).as_real_imag()[1]
        except Exception as exc:  # noqa: BLE001 — 평가 불가는 못 가림
            logger.debug("verify_answer 실근 판정 회피: %s", type(exc).__name__)
            return None
        if higher.is_number and (higher == 0 or abs(higher) <= abs(high) * _DEF_ZERO):
            return "vanishing"
        return None
    if abs(high) > _DEF_ZERO and abs(high - low) <= abs(high) * _DEF_ZERO:
        return "nonreal"
    return None


# 빠른 실근 판정(P3-79 재검토 P2-2)의 30자리 평가 문턱 — 근의 크기에 대한 상대값이다.
_SPLIT_PRECISION = 30
_SPLIT_REAL = sympy.Float("1e-25")  # 이 아래면 실근 후보(평가 오차 ≤ 1e-30 이라 실근은 반드시 여기)
_SPLIT_NONREAL = sympy.Float("1e-20")  # 이 위면 확실한 비실근(오차를 빼도 허수부 > 0)


def _complete_poly_roots(poly: sympy.Poly | None) -> list[sympy.Expr] | None:
    """다항식의 서로 다른 근 전부(근호식) — 중복도까지 다 못 구하면 None(호출부가 solve 로)."""
    if poly is None or poly.degree() < 1:
        return None
    try:
        root_mult = sympy.roots(poly)
    except Exception as exc:  # noqa: BLE001 — 근 계산 불가는 None(solve 로 넘긴다)
        logger.debug("verify_answer 근 계산 회피: %s", type(exc).__name__)
        return None
    if sum(root_mult.values()) != poly.degree():
        return None
    return list(root_mult)


def _poly_real_split(poly: sympy.Poly | None, roots: Sequence[sympy.Expr]) -> list[bool] | None:
    """다항식의 서로 다른 근 `roots` 전부에 대해 실근 여부를 빠르게 확정 — 못 하면 None.

    SymPy 의 정확한 실근 개수(`count_roots`, 확장 체 위)를 기준으로, 30자리 평가에서 허수부가
    |근|·1e-25 이하인 근(실근은 반드시 여기 든다)의 수가 그 개수와 같고 나머지가 전부 |근|·1e-20
    보다 크면(확실한 비실근) 그 분할이 곧 정확한 실근 집합이다. 하나라도 사이에 끼거나 개수가
    어긋나면 None — 호출부는 근별 판정(`_root_reality`)으로 간다. 근별 판정의 `is_real` 가정 추론·
    120/240자리 평가가 대수적 계수 근호식에서 수 초씩 들던 비용을 피한다(정확성은 같은 기준).
    """
    if poly is None or poly.degree() < 1 or not roots:
        return None
    try:
        count = int(sympy.Poly(poly.as_expr(), *poly.gens, extension=True).sqf_part().count_roots())
        flags: list[bool] = []
        for root in roots:
            value = sympy.N(root, _SPLIT_PRECISION)
            real_part, imag_part = value.as_real_imag()
            if not (real_part.is_number and imag_part.is_number):
                return None
            scale = max(abs(value), sympy.Integer(1))
            if abs(imag_part) <= scale * _SPLIT_REAL:
                flags.append(True)
            elif abs(imag_part) > scale * _SPLIT_NONREAL:
                flags.append(False)
            else:
                return None
    except Exception as exc:  # noqa: BLE001 — 셀 수 없는 계수 체·평가 불가는 느린 경로로
        logger.debug("verify_answer 빠른 실근 판정 회피: %s", type(exc).__name__)
        return None
    if len(set(roots)) != len(roots) or sum(flags) != count:
        return None
    return flags


def _condition_total(condition: str, var: str) -> bool:
    """조건 원문의 모든 변이 `var` 하나의 어디서나 정의되는 꼴(`function_domain_kind` TOTAL)인가."""
    sides = _relation_sides(condition)
    return bool(sides) and all(function_domain_kind(side, var) == "total" for side in sides)


def _real_count_agrees(poly: sympy.Poly | None, real_roots: Sequence[sympy.Expr]) -> bool:
    """실근 후보(사라지는 허수부 상한 포함)의 수가 SymPy 의 정확한 실근 개수와 같은가(P3-79 ⑦).

    잔차가 다항식이 아니거나(`poly` None) 계수 체 위에서 실근을 세지 못하면 False(확인 못 함 —
    호출부가 판정 불가로 둔다). 대수적 수 계수(`sqrt(2)`)는 확장 체 위의 다항식으로 다시 세운다.
    """
    if poly is None or poly.degree() < 1:
        return False
    try:
        algebraic = sympy.Poly(poly.as_expr(), *poly.gens, extension=True).sqf_part()
        count = algebraic.count_roots()
    except Exception as exc:  # noqa: BLE001 — 셀 수 없는 계수 체는 '확인 못 함'
        logger.debug("verify_answer 실근 개수 확인 회피: %s", type(exc).__name__)
        return False
    return int(count) == len(real_roots)


def trusted_real_roots(
    condition: str,
    residual: sympy.Expr,
    var: sympy.Symbol,
    *,
    given: Mapping[str, sympy.Expr] | None = None,
    known_roots: Sequence[sympy.Expr] | None = None,
) -> list[sympy.Expr] | None:
    """조건 등식의 **원문에서 정의되는** 서로 다른 실근(정확값) — 판정 불가면 None(P3-75).

    `residual` 은 평가 파싱이 자동 약분한 잔차라 그 근에는 원문이 정의되지 않는 점(무연근)이
    섞일 수 있다. 그래서 두 가지를 정확하게 가린다.
      · 실근 여부 — 유리 계수 다항식이면 `real_roots`(정확), 아니면 `solve` 의 근마다 SymPy
        `is_real`(정확) · 못 가리면 None. 허수부가 아주 작은 근(`(x - 1)**2 + 10**(-20)`)을 허용치로
        실근이라 부르지 않는다.
      · 원문 정의역 — 근마다 `condition_definedness`. 정의되지 않음은 버리고, 판정 불가가
        하나라도 있으면 None.
    `solve` 경로의 근 집합이 완전하다는 보장은 여기서 하지 않는다(종전과 같다 — 호출부가
    다항일 때만 존재성을 단정한다). 다만 실근 후보가 사라지는 허수부 상한(`vanishing`)에서
    왔으면 실근으로 분류한 개수를 SymPy 실근 개수(`count_roots`)와 맞춰 보고, 어긋나거나 셀 수
    없으면 None 이다(P3-79 ⑦ — 수치 평가가 허수부를 0 상한으로 낸 비실근을 실근으로 세지 않는다).

    `given`(P3-79) — 조건에 `var` 밖의 이름이 있을 때 그 값(대입 단계 `y = f(x)` 의 x). 원문 정의역
    판정에 함께 넣는다. `known_roots` — 호출부가 이미 구한 잔차의 서로 다른 근 전부(중복도까지 다
    구한 `sympy.roots` 의 키). 주면 근을 다시 구하지 않는다(비유리 계수 경로만 — 유리 계수는
    `real_roots` 가 정확해 그대로 쓴다).
    """
    try:
        poly: sympy.Poly | None = sympy.Poly(residual, var)
    except (sympy.PolynomialError, sympy.GeneratorsError, ValueError):
        poly = None
    candidates: list[sympy.Expr]
    if poly is not None and poly.domain in (sympy.ZZ, sympy.QQ) and poly.degree() >= 1:
        candidates = list(sympy.real_roots(poly.sqf_part()))
    else:
        candidates = []
        roots = list(known_roots) if known_roots is not None else _complete_poly_roots(poly)
        if roots is None:
            roots = list(sympy.solve(sympy.Eq(residual, 0), var))
        split = _poly_real_split(poly, roots)
        if split is not None:
            candidates = [root for root, real in zip(roots, split, strict=True) if real]
        else:
            vanishing = False  # 사라지는 허수부 상한으로 실근 후보가 된 근이 있는가
            for root in roots:
                reality = _root_reality(root)
                if reality is None:
                    return None
                if reality != "nonreal":
                    candidates.append(root)
                    vanishing = vanishing or reality == "vanishing"
            if vanishing and not _real_count_agrees(poly, candidates):
                return None
    if not given and _condition_total(condition, str(var)):
        # P3-79 재검토 P2-2 — 원문이 어디서나 정의되는 꼴(나눗셈·음수 지수·제한 함수 없음)이면
        # 근마다 원문을 평가할 까닭이 없다(대수적 계수 근호식 근의 평가가 수십 초였다).
        return candidates
    base = {} if given is None else dict(given)
    kept: list[sympy.Expr] = []
    for root in candidates:
        # 5차 이상 기약 다항식의 근(CRootOf)은 원문 평가에 60자리 수치로 넣는다 — 근사 소수라
        # 0 확정은 하지 않는다(분모가 그 근에서 0 에 가까우면 판정 불가로 남는다).
        state = _root_definedness(condition, str(var), root, base)
        if state == _UNKNOWN:
            return None
        if state == _DEFINED:
            kept.append(root)
    return kept


def _definedness_point(root: sympy.Expr) -> sympy.Expr:
    """원문 정의역 평가에 넣을 근의 값 — CRootOf 는 60자리 수치(`trusted_real_roots` 와 같다)."""
    return sympy.N(root, _CERT_PRECISION) if root.has(sympy.CRootOf) else root


# 정확한 근 표현의 크기 예산(P3-83) — 근호가 겹겹이 쌓인 근(기약 4차 방정식의 페라리 꼴·
# 대수적 수 계수 3차의 카르다노 꼴)을 원문에 넣으면 SymPy 의 영 판정(`is_zero`)·실수 판정
# (`is_real`)이 최소다항식 연산으로 가서 한 근에 수십 초~수 분이 걸린다(같은 크기에서도 어떤
# 근은 0.2초, 어떤 근은 20초 넘게 — 예측할 수 없다). 시간 상한은 비결정이고 이 모듈은 알람을
# 쓰지 않으므로(작업자 스레드 — safe_parse 머리말) 크기로 닫는다: 이 값(`count_ops`)을 넘는
# 근은 원문 정의역을 확정하지 못한 것으로 둔다(판정 불가 — fail-closed).
# 실측(P3-83): 예산 밖의 근은 기약 4차 꼴(69 이상 — 정수 계수 72~87 · 근호 계수 500 이상)이고
# 20초를 넘는 근이 섞인다. 예산 안에서는 정수 계수 3차의 카르다노 꼴(≤45)이 대체로 0.2초 안이다.
# 한계(예산이 닫지 못하는 잔여 클래스 — 후속): 크기가 작아도 느린 꼬리가 있다.
#   · `(x**4 - 4*x**3 - 6*x**2 - 3*x - 2)*(x-1)/(x-1) = 0` 의
#     `verify_root_aggregate(…, "0", "sum")` 은 근의 `count_ops` 가 1·19·33·35 라 모두 예산 밑인데
#     PYTHONHASHSEED 0~3 에서 PR 은 100.1·5.3·102.6·197.8초, 종전 main 은 4.4·4.6·202.5·195.4초였다
#     (4.5초~200초). 어느 한쪽이 일관되게 느리지 않다 — PR 이 느린 시드(0)도 main 이 느린 시드(2)도
#     있고, 예산 검사의 `count_ops` 호출 하나를 빼기만 해도 시드 2 가 102.6 → 4.5초로 바뀐다.
#   · 대수적 수 계수 3차도 60 이하에서 드물게(142근 중 5근) 1초를 넘고 2근은 20초를 넘겼다.
#   크기만으로는 예측할 수 없고, 오프라인 배치 `root_aggregate_batch`·`corpus_reverify` 에는
#   시간 상한이 없다.
_DEF_ROOT_MAX_OPS = 60


def _root_definedness(
    condition: str, var: str, root: sympy.Expr, base: Mapping[str, sympy.Expr]
) -> DefinednessState:
    """근 하나에서 조건 원문이 정의되는가 — 근 표현이 예산을 넘으면 평가하지 않고 판정 불가(P3-83).

    CRootOf 는 60자리 수치로 평가하므로 예산을 보지 않는다. `base` 는 var 밖 이름의 값."""
    if not root.has(sympy.CRootOf) and sympy.count_ops(root) > _DEF_ROOT_MAX_OPS:
        logger.debug("verify_answer 정의역 판정 불가: root_expression_too_large")
        return _UNKNOWN
    return condition_definedness(condition, {**base, var: _definedness_point(root)})


def _defined_root_multiplicities(
    condition: str, var: sympy.Symbol, root_mult: Mapping[sympy.Expr, int]
) -> dict[sympy.Expr, int] | None:
    """`{근: 중복도}` 중 원문이 그 근에서 정의되는 것만(P3-79). 판정 불가가 하나라도 있으면 None.

    원문이 어디서나 정의되는 꼴(`_condition_total`)이면 근별 평가 없이 그대로 돌려준다 — 그 꼴은
    복소수 점에서도 정의된다(허용 연산이 다항·상수 나눗셈·전해석 함수뿐이다)."""
    if _condition_total(condition, str(var)):
        return dict(root_mult)
    kept: dict[sympy.Expr, int] = {}
    for root, mult in root_mult.items():
        state = _root_definedness(condition, str(var), root, {})
        if state == _UNKNOWN:
            return None
        if state == _DEFINED:
            kept[root] = mult
    return kept


def verify_substituted_value(
    condition: str,
    given: Mapping[str, str],
    target: str,
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """대입 단계 판정(P3-71) — 등식 `condition` 에 `given` 을 대입하면 `target` 이 실수 하나로
    정해지고, 그 값이 `claimed` 인가.

    풀이의 해석 단계 "x = 3 → y = 4"(변수 값 → 식의 값)를 동치가 아니라 **정의 등식에 대입한 결과**
    로 판정한다. 정의 등식은 호출부가 문항 조건에서 고른다(정답에서 만들지 않는다).
      - **pass**: 대입 뒤 `target` 에 대한 다항 등식이 서로 다른 실수해 1개를 갖고 그것이 `claimed`.
      - **fail**: 그 유일 실수해가 `claimed` 와 다르다(틀린 대입값).
      - **unverifiable**: 등식 아님·대입 뒤 `target` 외 자유변수가 남음·`target` 에 대한 다항식이
        아님·실수해가 0개 또는 여러 개·값이 실수가 아님(보수적·pass 위장 금지).
    """
    try:
        residual, op = _parse_condition(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("대입 — 조건 파싱 불가·안전 회피")
    if op != "==":
        return _unverifiable("대입 — 등식이 아님(부등식/≠)·안전 회피")
    symbol = sympy.Symbol(target)
    try:
        given_values = {k: safe_sympify(v) for k, v in given.items()}
        reduced = safe_subs(residual, {sympy.Symbol(k): v for k, v in given_values.items()})
        claimed_value = _real_value(safe_sympify(claimed), tol)
    except Exception as exc:  # noqa: BLE001 — 대입·치환 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("대입 — 값 대입/치환 불가·안전 회피")
    if {str(s) for s in reduced.free_symbols} != {target}:
        return _unverifiable(f"대입 — 대입 뒤 자유변수가 {target} 하나가 아님·안전 회피")
    if claimed_value is None:
        return _unverifiable("대입 — 주장값이 실수가 아님·안전 회피")
    try:
        sympy.Poly(reduced, symbol)  # 다항일 때만 근 집합을 신뢰한다(빈 결과 오판 회피).
        # P3-79 — 대입 뒤 잔차는 자동 약분된 식이라(`y = x*(x - 2)/(x - 2)` 에 x = 2 → y - 2)
        # 그 해에서 원문 정의 등식이 정의되지 않을 수 있다. 해마다 원문 정의역(대입값 포함)으로
        # 거르고, 실근 여부도 허용치가 아니라 정확하게 가린다(`trusted_real_roots`).
        trusted = trusted_real_roots(condition, reduced, symbol, given=given_values)
    except Exception as exc:  # noqa: BLE001 — 비다항·풀이 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable(f"대입 — {target} 에 대한 다항 등식이 아님/풀이 불가·안전 회피")
    if trusted is None:
        return _unverifiable("대입 — 원문 정의역·실근 여부를 확정하지 못함·안전 회피")
    values = _distinct_values([rv for r in trusted if (rv := _real_value(r, tol)) is not None], tol)
    if len(values) != 1:
        return _unverifiable(f"대입 — {target} 이 실수 하나로 정해지지 않음({len(values)}개)")
    if _approx_equal(claimed_value, values[0], tol):
        return _pass(samples_checked=1)
    return _fail(
        f"대입 — {dict(given)} 를 대입하면 {target} = {values[0]} 이나 주장값은 {claimed}",
        samples_checked=1,
    )


def _certified_root_selection(
    condition: str,
    domain: Sequence[str],
    var: str,
    ans_text: str,
    selection: RootSelection,
    tol: float,
) -> AnswerVerdict:
    """도메인 경로(P3-71) — 허용 목록 다항 등식의 정확 근 집합 안에서만 선택을 판정한다.

    등식·도메인이 허용 목록(`certified_root_sets`) 밖이면 unverifiable — `sympy.solve` 의 부분 해
    (주기함수)·평가 파싱의 자동 약분(무연근)·허수부가 아주 작은 근을 근 집합으로 믿지
    않는다(PR #1703 검토 상3 · 3차·4차 상1). 정확 근은 오름차순이라 largest/smallest 는
    허용 근의 끝·처음이다.
    """
    sets = certified_root_sets(condition, domain, var)
    if sets is None:
        return _unverifiable("근 선택 — 도메인 경로는 허용 목록 다항 등식·부등식만·안전 회피")
    roots, admissible = sets
    index = match_root(ans_text, roots, tol=tol)
    if index is None:
        return _unverifiable("근 선택 — 답이 정확 실근 하나에 대응하지 않음(Tier1 소관)·안전 회피")
    chosen = roots[index]
    if chosen not in admissible:
        return _fail(
            f"근 선택({selection}) — 답이 도메인 제약 {list(domain)}을 어김"
            f"(허용 근 {[sympy.sstr(r) for r in admissible]}).",
            samples_checked=len(roots),
        )
    if selection == "unique":
        if len(admissible) == 1:
            return _pass(samples_checked=len(roots))
        return _fail(
            f"근 선택(unique) — 허용 근이 {len(admissible)}개라 답이 유일하게 정해지지 않음",
            samples_checked=len(roots),
        )
    target = admissible[-1] if selection == "largest" else admissible[0]
    if chosen == target:
        return _pass(samples_checked=len(roots))
    return _fail(
        f"근 선택({selection}) — 답이 요구된 근 {sympy.sstr(target)}가 아님",
        samples_checked=len(roots),
    )


def verify_root_selection(
    conditions: str | Sequence[str],
    answer: Mapping[str, str],
    selection: RootSelection,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """답이 조건의 실근 집합에서 *요구된 선택*(largest/smallest/unique)에 해당하는지 검증(S2-i).

    `verify_answer`(Tier1)이 "답이 조건을 만족하는가"만 보는 반면, 이 함수는 "여러 실근 중
    발문이 요구한 그 근(가장 큰/작은/유일)인가"를 본다. `큰 근을 구하시오`류 문제는 *방정식만으론
    답이 유일하게 정해지지 않아*(두 근 다 방정식을 만족) Tier1이 **틀린 근도 통과**시키기 때문이다
    (Phaiakes9 실측: `3x²+11x-4=0`의 큰 근에 작은 근 -4를 줘도 Tier1 pass).

    적용 범위: **단일 변수·단일 등식** 조건, 또는 **단일 등식 + 같은 변수의 도메인 부등식** 리스트
    (P3-71 — 예 `["3*a**2 = 108", "a > 0"]`·`["… = 36", "c >= 0", "c <= 3"]`). 도메인 부등식이
    있으면 실근을 그 제약으로 먼저 거르고(허용 근), 선택은 허용 근 안에서 한다. 도메인 판정은
    조건에서만 한다 — 답에서 선택을 역산하지 않는다(P3-24 B3 단서). 연립(등식 둘 이상)·다변수·
    파라미터·비다항 등 풀 수 없거나 실근이 없거나 답이 실근이 아니면 **unverifiable**
    (보수적·pass 위장 금지 — verify_answer 정직성 상속). 이 함수는 답이 등식을 *만족*하는지는
    검사하지 않는다(그건 verify_answer 소관) — 오직 *선택*만 판정한다. 판정:
      - **pass**: 답이 요구된 근(largest=최대·smallest=최소·unique=유일)과 일치.
      - **fail**: 답이 실근이나 *요구된 근이 아님*(예 큰 근 요구에 작은 근·unique 요구에 다근·
        도메인 제약을 어기는 근).
      - **unverifiable**: 적용 밖(풀 수 없음·다변수·실근 없음·도메인 판정 불가 등) — Tier1에 맡긴다.
    """
    # 단일 등식(종전) 또는 단일 등식 + 같은 변수의 도메인 부등식(P3-71). 연립/빈 조건은 선택 의미가
    # 불명확(보수적 회피). 원소 1개 리스트는 종전과 같은 경로다(하위호환).
    domain: tuple[str, ...] = ()
    condition: str | None
    if isinstance(conditions, str):
        condition = conditions
    else:
        condition_list = list(conditions)
        if len(condition_list) == 1:
            condition = condition_list[0]
        else:
            split = split_equation_domain(condition_list)
            condition, domain = (split[0], split[1]) if split is not None else (None, ())
    if condition is None:
        return _unverifiable(
            "근 선택 — 단일 등식(+같은 변수의 도메인 부등식)이 아님(연립/빈 조건)·안전 회피"
        )

    try:
        residual, op = _parse_condition(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("근 선택 — 조건 파싱 불가·안전 회피")
    if op != "==":
        return _unverifiable("근 선택 — 등식이 아님(부등식/≠)·안전 회피")

    free = sorted(residual.free_symbols, key=str)
    if len(free) != 1:
        return _unverifiable("근 선택 — 단일 변수 방정식이 아님·안전 회피")
    var = free[0]

    ans_text = answer.get(str(var))
    if ans_text is None:
        return _unverifiable(f"근 선택 — answer_map에 변수 {var} 없음·안전 회피")

    if domain:
        return _certified_root_selection(condition, domain, str(var), ans_text, selection, tol)

    try:
        ans_val = _real_value(safe_sympify(ans_text), tol)
        # P3-75 — 자동 약분된 잔차의 근에서 원문이 정의되지 않는 근(무연근)을 빼고, 실근 여부를
        # 허용치가 아니라 정확하게 가린다(`trusted_real_roots`).
        exact_roots = trusted_real_roots(condition, residual, var)
    except Exception as exc:  # noqa: BLE001 — 풀이/치환 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("근 선택 — 방정식 풀이/치환 불가·안전 회피")
    if ans_val is None:
        return _unverifiable("근 선택 — 답이 실수가 아님·안전 회피")
    if exact_roots is None:
        return _unverifiable("근 선택 — 원문 정의역·실근 여부를 확정하지 못함·안전 회피")

    real_roots = [rv for r in exact_roots if (rv := _real_value(r, tol)) is not None]
    if not real_roots:
        return _unverifiable("근 선택 — 실근 없음(복소근/풀이 불가)·안전 회피")

    # 답이 실근 중 하나인지(Tier1이 이미 보장하나 방어적 확인 — 아니면 Tier1에 판정을 맡긴다).
    if not any(_approx_equal(ans_val, r, tol) for r in real_roots):
        return _unverifiable("근 선택 — 답이 실근 집합에 없음(Tier1 소관)·안전 회피")

    distinct = _distinct_values(real_roots, tol)
    if selection == "unique":
        if len(distinct) == 1:
            return _pass(samples_checked=len(real_roots))
        return _fail(
            f"근 선택(unique) — 실근이 {len(distinct)}개라 답이 유일하게 정해지지 않음",
            samples_checked=len(real_roots),
        )

    target = max(distinct) if selection == "largest" else min(distinct)
    if _approx_equal(ans_val, target, tol):
        return _pass(samples_checked=len(real_roots))
    return _fail(
        f"근 선택({selection}) — 답 {ans_val}가 요구된 근 {target}가 아님"
        f"(실근 {sorted(distinct)}).",
        samples_checked=len(real_roots),
    )


def derive_selected_root(
    conditions: str | Sequence[str],
    selection: str,
    *,
    tol: float = 1e-9,
) -> str | None:
    """(단일변수 등식 + 근 선택)에서 정답 근을 *유도* — 정확값 문자열(SymPy 표기), 불가 시 None.

    `verify_root_selection`이 "답이 요구된 근인가"를 *판정*한다면, 이 함수는 요구된 근 자체를
    **유도**한다(derive-and-verify·S2-n). LLM의 답을 신뢰하는 대신 우리가 (방정식+선택)에서
    정답을 계산해 대조·정규화할 수 있게 한다 — canonical 정답의 소유권이 코드로 온다.

    반환은 SymPy 정확값 문자열이다(예 `'4/3'`·`'3/2'`·`'sqrt(2)'` — 반올림 소수 아님). 적용 밖
    (연립·다변수·부등식·실근 없음·unique인데 다근·미지 selection)은 None(보수적 — 호출자는
    유도 없이 기존 경로를 탄다). 판정 규약은 verify_root_selection과 동일 계약을 공유한다.

    단일 식이 아닌 조건(쉼표 나열 `"1,2,3,4,9"` 같은 개념형 자료 목록 — 파싱 결과가 튜플)도
    판정 불가 None이다. 예외를 내지 않는다(P3-80 — 종전에는 `AttributeError`). 형태 검사는
    `_parse_condition`이 자유 변수 수집 전에 한다.
    """
    if selection not in ("largest", "smallest", "unique"):
        return None
    # 단일 등식만 — verify_root_selection과 동일 규약.
    if isinstance(conditions, str):
        condition: str | None = conditions
    else:
        condition_list = list(conditions)
        condition = condition_list[0] if len(condition_list) == 1 else None
    if condition is None:
        return None

    try:
        residual, op = _parse_condition(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 None
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return None
    if op != "==":
        return None
    free = sorted(residual.free_symbols, key=str)
    if len(free) != 1:
        return None
    try:
        raw_roots = sympy.solve(sympy.Eq(residual, 0), free[0])
        # P3-75 — 반환 표기는 종전 `solve` 근(근호식)을 그대로 쓰고, 어느 근을 믿을지만 정확 판정
        # (`trusted_real_roots` — 무연근·허수부가 아주 작은 근 제외)으로 거른다. `real_roots` 의
        # CRootOf 표기를 그대로 내면 생성기 정규화(`safe_sympify`)가 거부해 가드가 꺼진다(검토 2).
        trusted = trusted_real_roots(condition, residual, free[0])
    except Exception as exc:  # noqa: BLE001 — 풀이 불가는 보수적 None
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return None
    if trusted is None:
        return None
    trusted_values = [tv for t in trusted if (tv := _real_value(t, tol)) is not None]

    # (정확근, 실수값) 쌍 — 복소근·신뢰 근 집합 밖의 근은 제외. 반환은 정확근 문자열.
    reals = [
        (r, rv)
        for r in raw_roots
        if (rv := _real_value(r, tol)) is not None
        and any(_approx_equal(rv, tv, tol) for tv in trusted_values)
    ]
    if not reals:
        return None
    distinct = _distinct_values([rv for _, rv in reals], tol)
    if selection == "unique":
        if len(distinct) != 1:
            return None  # 다근인데 unique 요구 — 유도 불가(문제 자체가 잘못).
        target = distinct[0]
    else:
        target = max(distinct) if selection == "largest" else min(distinct)
    for root, value in reals:
        if _approx_equal(value, target, tol):
            return str(sympy.sstr(root))
    return None  # pragma: no cover — target은 reals에서 왔으므로 도달 불가(방어)


# ──────────────────────────────────────────────────────────────────────────
# 근의 합/곱(Vieta) 검증 — S2 킬러 확장(f'=0 근이 아니라 *근들의 집계값*이 답).
# ──────────────────────────────────────────────────────────────────────────
RootAggregate = Literal["sum", "product"]


def verify_root_aggregate(
    conditions: str | Sequence[str],
    claimed: str,
    kind: RootAggregate,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """답이 조건 방정식의 *모든 근의 합/곱*(Vieta)과 일치하는지 검증(S2 킬러 확장).

    "삼차방정식 …의 세 근의 합/곱을 구하시오"류 킬러 문항의 답은 f(x)=0의 *근이 아니라*
    근들의 집계값이라 `verify_answer`(답이 근인가)·`verify_root_selection`(어느 근인가)로는
    검증할 수 없다. 이 함수가 그 빈 검증면을 채운다 — 다항식의 근을 중복도까지 정확히 구해
    (`sympy.roots`) 합/곱을 **기호적 정확값**으로 계산하고, 주장값과 `simplify` 차 0을 본다
    (복소근 포함 Vieta 정확값이라 근이 무리·복소여도 정확). 판정:
      - **pass**: 근들의 합/곱이 주장값과 정확히 일치(simplify 차 0).
      - **fail**: 불일치(주장값이 틀림).
      - **unverifiable**: 적용 밖 — 단일 변수 다항 등식이 아님·근을 중복도까지 다 못 구함·
        파싱/치환 불가(보수적·pass 위장 금지, verify_answer 정직성 상속).
    """
    # 단일 등식만(연립/빈 조건은 집계 의미 불명확 — 보수적 회피).
    if isinstance(conditions, str):
        condition: str | None = conditions
    else:
        condition_list = list(conditions)
        condition = condition_list[0] if len(condition_list) == 1 else None
    if condition is None:
        return _unverifiable("근 집계 — 단일 등식이 아님(연립/빈 조건)·안전 회피")

    try:
        residual, op = _parse_condition(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("근 집계 — 조건 파싱 불가·안전 회피")
    if op != "==":
        return _unverifiable("근 집계 — 등식이 아님(부등식/≠)·안전 회피")

    free = sorted(residual.free_symbols, key=str)
    if len(free) != 1:
        return _unverifiable("근 집계 — 단일 변수 방정식이 아님·안전 회피")
    var = free[0]

    try:
        poly = sympy.Poly(residual, var)
    except (sympy.PolynomialError, sympy.GeneratorsError, ValueError):
        return _unverifiable("근 집계 — 다항식이 아님·안전 회피")

    try:
        root_mult = sympy.roots(poly)  # {근: 중복도} — 복소근 포함 정확값.
        claimed_expr = safe_sympify(claimed)
    except Exception as exc:  # noqa: BLE001 — 풀이/치환 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("근 집계 — 근 계산/주장값 치환 불가·안전 회피")

    total_mult = sum(root_mult.values())
    if total_mult != poly.degree():
        # 근을 중복도까지 전부 구하지 못함(라디칼 표현 불가 등) → 집계 정확값 보장 못 함.
        return _unverifiable("근 집계 — 근을 중복도까지 전부 구하지 못함·안전 회피")

    # P3-79 — 잔차는 자동 약분된 식이라(`(x - 3)*(x - 2)**2/(x - 2)` → (x - 3)*(x - 2)) 원문에서
    # 정의되지 않는 근(x = 2)이 섞인다. 근마다(복소근 포함 — 집계는 Vieta 정확값이 계약) 원문
    # 정의역을 보고, 정의되지 않음은 빼고 판정 불가가 하나라도 있으면 unverifiable.
    defined = _defined_root_multiplicities(condition, var, root_mult)
    if defined is None:
        return _unverifiable("근 집계 — 원문 정의역을 확정하지 못함·안전 회피")
    if not defined:
        return _unverifiable("근 집계 — 원문에서 정의되는 근이 없음(무연근만)·안전 회피")
    root_mult = defined
    total_mult = sum(root_mult.values())

    if kind == "sum":
        actual: sympy.Expr = sum(
            (root * mult for root, mult in root_mult.items()), sympy.Integer(0)
        )
    else:
        actual = sympy.Integer(1)
        for root, mult in root_mult.items():
            actual = actual * root**mult

    try:
        diff = sympy.simplify(actual - claimed_expr)
    except Exception as exc:  # noqa: BLE001 — 단순화 실패는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("근 집계 — 차 단순화 불가·안전 회피")

    if diff == 0:
        return _pass(samples_checked=total_mult)
    return _fail(
        f"근 {kind} — 근들의 {kind}는 {sympy.sstr(sympy.simplify(actual))}이나 "
        f"주장값은 {claimed}(불일치)",
        samples_checked=total_mult,
    )


# ──────────────────────────────────────────────────────────────────────────
# 해 존재성·유일성 분류(문항 품질 15축 ②③) — *답과 무관하게* 방정식 자체가 성립 문제인가.
# ──────────────────────────────────────────────────────────────────────────
# 정본: `docs/standards/superhuman_verification_standard.md`(측정된 게이트) + 문항 품질 15축 진단
# ②(답이 존재하지 않음)·③(답이 여러 개). verify_answer가 "주어진 답이 조건을 만족하는가"만 보는
# 반면, 이 분류기는 "방정식 자체가 *풀 수 있는 문제*인가"를 답 이전에 판정한다:
#   - 항등식(무한해·예 `2*(x+1)=2*x+2`)은 residual이 항등적 0이라 *어떤 답도* Tier1 pass →
#     단일 정답 문항으로 malformed(현 게이트의 구멍: unique 프로브가 실근 0으로 unverifiable을
#     돌려 강등 안 됨 → verified로 통과). 이 축이 그 구멍을 닫는다.
#   - 해 없음(예 `x+1=x+2`의 상수 잔차·실근 없는 다항)은 malformed이며, 기존엔 Tier1 fail로만
#     *우연히* 걸려 사유가 모호했다 — 여기서 명시 사유로 승격.
SolvabilityClass = Literal["no_solution", "identity", "unique", "multiple", "undecidable"]


class SolvabilityVerdict(BaseModel):
    """`classify_solvability`의 결과 — 방정식의 해 존재/유일 5분류 + 사유·서로 다른 실근 수.

    `state`는 방정식 *자체*의 성질이다(주장 답과 무관): no_solution(해 없음)·identity(무한해·
    항등식)·unique(서로 다른 실근 1개)·multiple(≥2)·undecidable(단일변수 다항 등식 밖·판정 회피).
    정직성(verify_answer 상속): 비다항·다변수·파싱 불가는 `undecidable`로 보수 처리한다 —
    sympy.solve의 빈 결과를 "해 없음"으로 *오판하지 않는다*(다항에서만 존재성을 단정).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: SolvabilityClass = Field(description="해 존재/유일 5분류(방정식 자체 성질·답 무관).")
    reason: str | None = Field(
        default=None, description="분류 사유(한국어·undecidable/특이 케이스)."
    )
    n_distinct_real_roots: int = Field(
        default=0, description="서로 다른 실근 수(unique=1·multiple≥2·그 외 0)."
    )


def classify_solvability(
    conditions: str | Sequence[str],
    *,
    tol: float = 1e-9,
) -> SolvabilityVerdict:
    """단일변수 (실계수) 방정식의 해 존재/유일을 5분류 — 답 이전에 방정식이 성립 문제인지 판정.

    실수해 스코프(K-12·수능 실답 전제): 실근을 기준으로 unique/multiple/no_solution을 가른다.
    보수성(핵심): **다항식일 때만** sympy 근을 신뢰해 존재성을 단정하고, 비다항·다변수·파싱 불가는
    `undecidable`로 회피한다 — sympy.solve가 "못 푼" 빈 결과를 "해 없음"으로 오판해 정상 문항을
    거짓 거부하지 않기 위함. 판정:
      - **identity**(무한해): lhs-rhs가 항등적 0(예 `2*(x+1)=2*x+2`) — 모든 값이 해.
      - **no_solution**: lhs-rhs가 0 아닌 상수(예 `x+1=x+2`) 또는 다항인데 실근이 하나도 없음.
      - **unique**: 서로 다른 실근 1개(중근은 1개로 접음).
      - **multiple**: 서로 다른 실근 ≥2개.
      - **undecidable**: 단일변수 다항 등식이 아님(연립·부등식·다변수·비다항·파싱 불가)·안전 회피.
    """
    # 단일 등식만 — 연립/빈 조건은 존재성 의미가 불명확(보수적 회피).
    if isinstance(conditions, str):
        condition: str | None = conditions
    else:
        condition_list = list(conditions)
        condition = condition_list[0] if len(condition_list) == 1 else None
    if condition is None:
        return SolvabilityVerdict(state="undecidable", reason="단일 등식이 아님(연립/빈 조건)")

    try:
        residual, op = _parse_condition(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 undecidable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return SolvabilityVerdict(state="undecidable", reason="조건 파싱 불가")
    if op != "==":
        return SolvabilityVerdict(state="undecidable", reason="등식이 아님(부등식/≠)")

    # 항등식·상수 잔차 판정 — simplify가 자유변수를 다 지우면 상수(답 무관 결론).
    try:
        simplified = sympy.simplify(residual)
    except Exception as exc:  # noqa: BLE001 — 단순화 실패는 보수적 undecidable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return SolvabilityVerdict(state="undecidable", reason="잔차 단순화 불가")
    if not simplified.free_symbols:
        if simplified == 0:
            return SolvabilityVerdict(
                state="identity", reason="lhs-rhs가 항등적 0 — 모든 값이 해(무한해)"
            )
        return SolvabilityVerdict(
            state="no_solution", reason=f"lhs-rhs가 0 아닌 상수 {simplified} — 해 없음"
        )

    free = sorted(residual.free_symbols, key=str)
    if len(free) != 1:
        return SolvabilityVerdict(
            state="undecidable", reason="단일 변수 방정식이 아님(다변수/파라미터)"
        )
    var = free[0]

    # 다항일 때만 근 존재성을 신뢰(sympy 완전). 비다항은 solve 빈결과 오판 회피 → undecidable.
    try:
        sympy.Poly(residual, var)
    except (sympy.PolynomialError, sympy.GeneratorsError, ValueError):
        return SolvabilityVerdict(state="undecidable", reason="다항식이 아님 — 존재성 단정 회피")

    try:
        # P3-75 — 자동 약분된 잔차의 근 중 원문에서 정의되는 정확 실근만 센다(무연근·허수부가
        # 아주 작은 근을 해로 세지 않는다).
        exact_roots = trusted_real_roots(condition, residual, var)
    except Exception as exc:  # noqa: BLE001 — 풀이 불가는 보수적 undecidable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return SolvabilityVerdict(state="undecidable", reason="방정식 풀이 불가")
    if exact_roots is None:
        return SolvabilityVerdict(
            state="undecidable", reason="원문 정의역·실근 여부를 확정하지 못함 — 존재성 단정 회피"
        )

    real_roots = [rv for r in exact_roots if (rv := _real_value(r, tol)) is not None]
    distinct = _distinct_values(real_roots, tol)
    n = len(distinct)
    if n == 0:
        return SolvabilityVerdict(
            state="no_solution",
            reason="다항이나 원문에서 정의되는 실근이 하나도 없음(복소근·무연근만)",
        )
    if n == 1:
        return SolvabilityVerdict(state="unique", reason=None, n_distinct_real_roots=1)
    return SolvabilityVerdict(
        state="multiple",
        reason=f"서로 다른 실근 {n}개 — 답이 유일하게 확정되려면 근 선택 필요",
        n_distinct_real_roots=n,
    )


# ──────────────────────────────────────────────────────────────────────────
# 개념형(개수/존재) 검증 — 답이 값이 아니라 *개수*(실근 개수·극값 개수)인 문항.
# ──────────────────────────────────────────────────────────────────────────
# 정본: 문항 품질 15축 개념형 확장. 수치평가(x=<닫힌형>)의 약한 잔차와 달리, 개수는 SymPy로
# *독립 계산*해 주장값과 대조하므로 오개념의 틀린 개수는 fail한다(진짜 개념 검증). 판별식을 무시해
# "이차방정식은 늘 두 실근"으로 오인(discriminant-negative-no-real-root)·임계점(f'=0)을 곧 극값으로
# 오인(critical-point-implies-extremum)하는 오개념을 정확히 겨눈다.


def _single_condition(conditions: str | Sequence[str]) -> str | None:
    """단일 등식/식만 허용 — 연립·빈 조건은 None(개념형 개수 검증의 공통 전제)."""
    if isinstance(conditions, str):
        return conditions
    condition_list = list(conditions)
    return condition_list[0] if len(condition_list) == 1 else None


def _claimed_int(claimed: str, tol: float) -> int | None:
    """주장 개수를 정수로 — 실수로 평가해 정수 근방이면 그 정수, 아니면 None(개수 아님)."""
    value = _real_value(safe_sympify(claimed), tol) if claimed else None
    if value is None:
        return None
    rounded = round(value)
    return rounded if abs(value - rounded) < 1e-6 and rounded >= 0 else None


def _count_bounds(
    conditions: str | Sequence[str],
) -> tuple[str, list[tuple[sympy.Expr, str]]] | None:
    """실근 개수 조건 = 등식 1개 + (선택) 같은 변수의 범위 부등식들 → (등식, [(잔차, 연산자)]).

    "열린구간 (-4, 4)에서 … 실수 c의 개수"처럼 *범위 안의* 근만 세는 문항의 검산 재료다
    (`["6*x**2 - 4*x - 32 = 0", "x > -4", "x < 4"]`). 범위 조건은 변수 하나에 대한 부등식·`!=`
    (잔차가 그 변수의 일차식)만 받는다 — 그 밖의 형태(둘째 등식·다른 변수·비선형 범위)는 None
    (보수적 unverifiable). 단일 조건이면 범위 없이 그대로(종전 계약).
    """
    if isinstance(conditions, str):
        return conditions, []
    items = list(conditions)
    if not items:
        return None
    equation, rest = items[0], items[1:]
    bounds: list[tuple[sympy.Expr, str]] = []
    for text in rest:
        try:
            residual, op = _parse_condition(text)
        except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 None
            logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
            return None
        if op == "==" or len(residual.free_symbols) != 1:
            return None
        (symbol,) = residual.free_symbols
        try:
            if sympy.degree(residual, symbol) != 1:
                return None
        except sympy.PolynomialError:
            return None
        bounds.append((residual, op))
    return equation, bounds


def verify_real_root_count(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """답이 단일변수 다항식 방정식의 *서로 다른 실근 개수*와 일치하는지 검증(개념형).

    "이차방정식 …의 서로 다른 실근의 개수"류 문항의 답은 근이 아니라 *개수*라 verify_answer로는
    검증 못 한다. 이 함수가 다항식의 실근을 중복도까지 구해(`sympy.roots`) 서로 다른 실근 수를
    세고 주장 개수와 대조한다. 판별식 무시("늘 2근") 오개념은 실근 0/1을 2로 답해 fail한다.

    조건이 목록이면 첫 항목이 방정식, 나머지는 **같은 변수의 범위**(`x > -4`·`t >= 0` 등)다 —
    범위를 모두 만족하는 실근만 센다(P3-03 6회차 감사: "구간 [-4, 4]에서 평균값 정리를 만족시키는
    c의 개수"의 검산이 실수 전체의 근을 세던 결함). 범위 경계에 근이 걸려 판정이 모호하면
    unverifiable이다.
      - pass: 실제 서로 다른 실근 수(범위 안) == 주장 개수.
      - fail: 불일치(오개념).
      - unverifiable: 단일변수 다항 등식 아님·근을 다 못 구함·주장이 개수 아님·범위 형식 밖·경계
        모호(보수적 회피).
    """
    parsed = _count_bounds(conditions)
    if parsed is None:
        return _unverifiable("실근 개수 — 등식 1개 + 같은 변수의 범위 부등식 형태가 아님·안전 회피")
    condition, bounds = parsed
    try:
        residual, op = _parse_condition(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("실근 개수 — 조건 파싱 불가·안전 회피")
    if op != "==":
        return _unverifiable("실근 개수 — 등식이 아님·안전 회피")
    free = sorted(residual.free_symbols, key=str)
    if len(free) != 1:
        return _unverifiable("실근 개수 — 단일 변수 방정식이 아님·안전 회피")
    var = free[0]
    if any(b.free_symbols != {var} for b, _ in bounds):
        return _unverifiable("실근 개수 — 범위 조건의 변수가 방정식의 변수와 다름·안전 회피")
    try:
        poly = sympy.Poly(residual, var)
        root_mult = sympy.roots(poly)
    except (sympy.PolynomialError, sympy.GeneratorsError, ValueError):
        return _unverifiable("실근 개수 — 다항식이 아님·안전 회피")
    except Exception as exc:  # noqa: BLE001 — 근 계산 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("실근 개수 — 근 계산 불가·안전 회피")
    if sum(root_mult.values()) != poly.degree():
        return _unverifiable("실근 개수 — 근을 중복도까지 다 못 구함·안전 회피")

    claimed_n = _claimed_int(claimed, tol)
    if claimed_n is None:
        return _unverifiable("실근 개수 — 주장값이 개수(비음 정수)가 아님·안전 회피")
    # P3-79 — 잔차는 자동 약분된 식이라(`x*(x - 2)/(x - 2) = 2` → x - 2) 원문에서 정의되지 않는
    # 근(무연근)이 섞이고, 허용치(1e-9)로 실수를 부르면 허수부가 아주 작은 근도 섞인다. 셈에
    # 넣는 근은 원문에서 정의되는 정확 실근만이다(`trusted_real_roots` — 판정 불가면 None).
    try:
        trusted = trusted_real_roots(condition, residual, var, known_roots=list(root_mult))
    except Exception as exc:  # noqa: BLE001 — 근 계산 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("실근 개수 — 근 계산 불가·안전 회피")
    if trusted is None:
        return _unverifiable("실근 개수 — 원문 정의역·실근 여부를 확정하지 못함·안전 회피")
    real = [rv for r in trusted if (rv := _real_value(r, tol)) is not None]
    inside: list[float] = []
    for value in real:
        verdicts = [
            _eval_relation(float(bound.subs(var, value)), bound_op, tol)
            for bound, bound_op in bounds
        ]
        if any(v is None for v in verdicts):
            return _unverifiable("실근 개수 — 근이 범위 경계에 걸려 판정 모호·안전 회피")
        if all(verdicts):
            inside.append(value)
    actual = len(_distinct_values(inside, tol))
    if actual == claimed_n:
        return _pass(samples_checked=actual)
    return _fail(
        f"실근 개수 — 실제 {actual}개이나 주장은 {claimed_n}개(불일치)",
        samples_checked=actual,
    )


# ──────────────────────────────────────────────────────────────────────────
# 함수 식 원문의 정의역 꼴(P3-79 ⑤) — 극값·일대일·미분가능은 *한 점*이 아니라 *근방·ℝ 전체*의
# 성질이라, 점별 정의역 판정(`condition_definedness`)만으로는 부족하다. 원문 구문 나무를 허용 노드만
# 으로 훑어(실행하지 않는다) 정의역이 어떤 꼴인지 가린다.
#   · TOTAL — 모든 실수에서 정의·유한(다항·상수 분모·Abs·전해석 함수). 평가 파싱이 접은 식과 ℝ
#     전체에서 값이 같다.
#   · OPEN  — 변수 분모·변수 밑의 0 이하 정수 지수가 있어 정의되지 않는 점이 있을 수 있으나, 남은
#     정의역은 열린 집합이고 그 위에서 접은 식과 값이 같다(연속 연산·나눗셈만으로 지어졌다).
#   · None  — 허용 노드 밖(√·log·`.doit()`·Derivative 등). 정의역 꼴을 모른다.
# ──────────────────────────────────────────────────────────────────────────
FunctionDomain = Literal["total", "open"]
# 실수 전체에서 정의·유한·연속인 함수(인자가 TOTAL 이면 결과도 TOTAL).
_TOTAL_FUNCTIONS: frozenset[str] = frozenset(
    {"Abs", "abs", "sin", "cos", "exp", "sinh", "cosh", "atan"}
)


def _constant_value(node: ast.AST) -> sympy.Expr | None:
    """이름 없는 상수 하위 나무의 값 — 허용 노드 평가(`_DefinednessEvaluator`)로만 구한다."""
    try:
        return _DefinednessEvaluator(True).value(node, {})
    except (_DefUndefined, _DefUnknown):
        return None
    except Exception as exc:  # noqa: BLE001 — 예상 밖 예외도 '모름'
        logger.debug("verify_answer 함수 정의역 판정 회피: %s", type(exc).__name__)
        return None


def _domain_kind(node: ast.AST, var: str) -> FunctionDomain | None:
    """하위 나무의 정의역 꼴(위 절 설명). 변수 `var` 하나의 함수로 본다."""
    names = _free_names(node)
    if names - {var}:
        return None  # 다른 이름(자유 기호)이 섞이면 단일 변수 함수가 아니다
    if not names:
        # 변수 없는 상수 — 그 값이 유한한 실수로 정의되면 어디서나 같은 값(TOTAL).
        value = _constant_value(node)
        return "total" if value is not None and value.is_real else None
    if isinstance(node, ast.Name):
        return "total"
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _domain_kind(node.operand, var)
    if isinstance(node, ast.BinOp):
        return _binop_domain_kind(node, var)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _TOTAL_FUNCTIONS
        and len(node.args) == 1
        and not node.keywords
    ):
        return _domain_kind(node.args[0], var)
    return None


def _binop_domain_kind(node: ast.BinOp, var: str) -> FunctionDomain | None:
    left_has = var in _free_names(node.left)
    right_has = var in _free_names(node.right)
    if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
        kinds = (_domain_kind(node.left, var), _domain_kind(node.right, var))
        if None in kinds:
            return None
        return "total" if kinds == ("total", "total") else "open"
    if isinstance(node.op, ast.Div):
        top = _domain_kind(node.left, var)
        if top is None:
            return None
        if not right_has:
            value = _constant_value(node.right)
            if value is None or _zero_state(value) is not False:
                return None  # 상수 분모가 0 이거나 0 여부를 못 가림
            return top
        bottom = _domain_kind(node.right, var)
        return None if bottom is None else "open"
    if isinstance(node.op, (ast.Pow, ast.BitXor)):
        if right_has:
            # b**x — 밑이 변수와 무관한 양수일 때만(exp(x·log b)).
            base = _constant_value(node.left) if not left_has else None
            if base is None or base.is_positive is not True:
                return None
            return _domain_kind(node.right, var)
        exponent = _constant_value(node.right)
        if exponent is None or not exponent.is_Integer:
            return None
        base_kind = _domain_kind(node.left, var)
        if base_kind is None:
            return None
        if exponent.is_positive:
            return base_kind
        # 변수 밑의 0 이하 정수 지수 — 밑이 0 인 점에서 정의되지 않는다(0**0·0**음수).
        return "open" if left_has else base_kind
    return None


def function_domain_kind(expression: str, var: str) -> FunctionDomain | None:
    """함수 식 원문의 정의역 꼴 — `total`·`open`·None(허용 구조 밖). 실행하지 않는다(P3-79)."""
    try:
        safe_sympify(expression)  # 안전 진입점의 거부(위험 토큰·예산)를 먼저 통과해야 한다
        tree = ast.parse(expression.strip().replace("^", "**"), mode="eval").body
    except Exception as exc:  # noqa: BLE001 — 파싱 불가·거부는 '모름'
        logger.debug("verify_answer 함수 정의역 판정 회피: %s", type(exc).__name__)
        return None
    return _domain_kind(tree, var)


def _real_root_items(
    poly: sympy.Poly, root_mult: Mapping[sympy.Expr, int]
) -> list[tuple[sympy.Expr, int]] | None:
    """`{근: 중복도}` 의 실근만 — 실근 여부는 허용치가 아니라 정확하게(`_root_is_real`). 못 가리면
    None(P3-79 — 허수부 1e-10 인 도함수 근을 임계점으로 세던 결함). 실근 후보가 사라지는
    허수부 상한(`vanishing`)에서 왔으면 SymPy 실근 개수와 맞춰 본다(`trusted_real_roots` 규칙)."""
    pairs = list(root_mult.items())
    split = _poly_real_split(poly, [root for root, _ in pairs])
    if split is not None:
        return [pair for pair, real in zip(pairs, split, strict=True) if real]
    items: list[tuple[sympy.Expr, int]] = []
    vanishing = False
    for root, mult in root_mult.items():
        reality = _root_reality(root)
        if reality is None:
            return None
        if reality != "nonreal":
            items.append((root, mult))
            vanishing = vanishing or reality == "vanishing"
    if vanishing and not _real_count_agrees(poly, [root for root, _ in items]):
        return None
    return items


def verify_extremum_count(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """답이 다항함수 f(x)의 *극값 개수*와 일치하는지 검증(개념형).

    극값 개수 = f'의 실근 중 *부호가 바뀌는*(중복도 홀수) 근 수다. f'=0이나 부호 불변(예 x³의
    f'=3x²)이면 임계점은 있으나 극값은 없다 — "임계점=극값" 오개념은 임계점 수를 극값 수로 답해
    fail한다. `conditions`는 f(x) *식*(등식 아님·예 "x**3 - 3*x").
      - pass: 실제 극값 수 == 주장 개수.
      - fail: 불일치(오개념).
      - unverifiable: 단일변수 다항식 아님·f' 근을 다 못 구함·주장이 개수 아님(보수적 회피).
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("극값 개수 — 단일 식이 아님·안전 회피")
    try:
        expr = safe_sympify(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("극값 개수 — 식 파싱 불가·안전 회피")
    if isinstance(expr, sympy.core.relational.Relational):
        return _unverifiable("극값 개수 — 함수 식이어야 함(등식/부등식 아님)·안전 회피")
    if not isinstance(expr, sympy.Expr):  # P3-80 — 쉼표 나열(튜플) 등은 자유 변수 수집 전에 회피
        return _unverifiable("극값 개수 — 단일 식이 아님(쉼표 나열 등)·안전 회피")
    free = sorted(expr.free_symbols, key=str)
    if len(free) != 1:
        return _unverifiable("극값 개수 — 단일 변수 함수가 아님·안전 회피")
    var = free[0]
    try:
        fprime = sympy.diff(expr, var)
        poly = sympy.Poly(fprime, var)
        root_mult = sympy.roots(poly)
    except (sympy.PolynomialError, sympy.GeneratorsError, ValueError):
        return _unverifiable("극값 개수 — 도함수가 다항식이 아님·안전 회피")
    except Exception as exc:  # noqa: BLE001 — 근 계산 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("극값 개수 — 도함수 근 계산 불가·안전 회피")
    if sum(root_mult.values()) != poly.degree():
        return _unverifiable("극값 개수 — 도함수 근을 중복도까지 다 못 구함·안전 회피")

    claimed_n = _claimed_int(claimed, tol)
    if claimed_n is None:
        return _unverifiable("극값 개수 — 주장값이 개수(비음 정수)가 아님·안전 회피")
    # P3-79 — f 는 평가 파싱이 접은 식이다(`(x - 2)**3/(x - 2)` → (x - 2)**2). 원문 정의역 꼴이
    # TOTAL 이면 접은 식과 ℝ 전체에서 같고, OPEN 이면 남은 정의역(열린 집합) 위에서만 같아 정의되지
    # 않는 임계점(x = 2)은 극값이 아니다 — 점마다 `condition_definedness` 로 거른다. 허용 구조 밖은
    # 정의역을 몰라 판정 불가.
    domain = function_domain_kind(condition, str(var))
    if domain is None:
        return _unverifiable("극값 개수 — 원문 함수의 정의역을 확인 못 함(허용 구조 밖)·안전 회피")
    critical = _real_root_items(poly, root_mult)
    if critical is None:
        return _unverifiable("극값 개수 — 도함수 근의 실수 여부를 확정하지 못함·안전 회피")
    if domain == "open":
        filtered = _defined_root_multiplicities(condition, var, dict(critical))
        if filtered is None:
            return _unverifiable("극값 개수 — 임계점에서 원문 정의역을 확정하지 못함·안전 회피")
        critical = list(filtered.items())
    # 극값 = 실근 중 중복도 홀수(부호 변화). 짝수 중복도(예 x³의 f'=3x²)는 극값 아님.
    actual = sum(1 for _, mult in critical if mult % 2 == 1)
    if actual == claimed_n:
        return _pass(samples_checked=actual)
    return _fail(
        f"극값 개수 — 실제 {actual}개이나 주장은 {claimed_n}개(불일치)",
        samples_checked=actual,
    )


def verify_is_one_to_one(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """다항함수 f(x)가 ℝ에서 *일대일대응*(역함수 존재 가능)인지 0/1로 검증(개념형).

    다항함수는 f'이 부호를 바꾸지 않을 때만(단조) 일대일이다 — f'의 부호 변화(도함수 실근 중
    중복도 홀수) 개수가 0이면 1(일대일)·아니면 0. "일대일 아니어도 역함수가 있다"는 오개념
    (invertibility-without-1-1)은 x²류(부호 변화 有)를 1로 답해 fail한다. `conditions`는 f(x) 식.
      - pass: 실제 일대일 여부(1/0) == 주장.
      - fail: 불일치(오개념).
      - unverifiable: 단일변수 다항식 아님·주장이 0/1 아님(보수적 회피).
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("일대일 — 단일 식이 아님·안전 회피")
    try:
        expr = safe_sympify(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("일대일 — 식 파싱 불가·안전 회피")
    if isinstance(expr, sympy.core.relational.Relational):
        return _unverifiable("일대일 — 함수 식이어야 함(등식/부등식 아님)·안전 회피")
    if not isinstance(expr, sympy.Expr):  # P3-80 — 쉼표 나열(튜플) 등은 자유 변수 수집 전에 회피
        return _unverifiable("일대일 — 단일 식이 아님(쉼표 나열 등)·안전 회피")
    free = sorted(expr.free_symbols, key=str)
    if len(free) != 1:
        return _unverifiable("일대일 — 단일 변수 함수가 아님·안전 회피")
    claimed_n = _claimed_int(claimed, tol)
    if claimed_n not in (0, 1):
        return _unverifiable("일대일 — 주장값이 0/1이 아님·안전 회피")
    var = free[0]
    # P3-79 — 'ℝ 에서 일대일대응' 은 ℝ 전체에서 정의돼야 묻는다. 평가 파싱이 접은 식
    # (`x**3*(x - 1)/(x - 1)` → x**3)이 아니라 원문이 ℝ 전체에서 정의되는 꼴(TOTAL)일 때만 판정한다.
    if function_domain_kind(condition, str(var)) != "total":
        return _unverifiable(
            "일대일 — 원문 함수가 ℝ 전체에서 정의되는 꼴임을 확인 못 함(분모·허용 구조 밖)"
            "·안전 회피"
        )
    fprime = sympy.diff(expr, var)
    if fprime == 0:
        actual = 0  # 상수함수 → 일대일 아님.
    else:
        try:
            poly = sympy.Poly(fprime, var)
            root_mult = sympy.roots(poly)
        except (sympy.PolynomialError, sympy.GeneratorsError, ValueError):
            return _unverifiable("일대일 — 도함수가 다항식이 아님·안전 회피")
        if sum(root_mult.values()) != poly.degree():
            return _unverifiable("일대일 — 도함수 근을 중복도까지 다 못 구함·안전 회피")
        critical = _real_root_items(poly, root_mult)
        if critical is None:
            return _unverifiable("일대일 — 도함수 근의 실수 여부를 확정하지 못함·안전 회피")
        sign_changes = sum(1 for _, mult in critical if mult % 2 == 1)
        actual = 1 if sign_changes == 0 else 0  # 부호 변화 없음(단조) → 일대일.
    if actual == claimed_n:
        return _pass(samples_checked=1)
    return _fail(f"일대일 — 실제 {actual}이나 주장은 {claimed_n}(불일치)", samples_checked=1)


def verify_geometric_convergence(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """공비 r인 등비급수의 *수렴 여부*를 0/1로 검증(개념형). `conditions`는 공비 r(값/식).

    등비급수는 |r|<1일 때만 수렴한다(1)·그 외 발산(0). "등비급수는 늘 수렴한다"는 오개념
    (geometric-series-always-converges)은 |r|≥1인데 1로 답해 fail한다.
      - pass: 실제 수렴 여부(1/0) == 주장.
      - fail: 불일치(오개념).
      - unverifiable: r이 실수가 아님·주장이 0/1 아님(보수적 회피).
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("등비급수 수렴 — 단일 값이 아님·안전 회피")
    try:
        ratio = _real_value(safe_sympify(condition), tol)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("등비급수 수렴 — 공비 파싱 불가·안전 회피")
    if ratio is None:
        return _unverifiable("등비급수 수렴 — 공비가 실수가 아님·안전 회피")
    claimed_n = _claimed_int(claimed, tol)
    if claimed_n not in (0, 1):
        return _unverifiable("등비급수 수렴 — 주장값이 0/1이 아님·안전 회피")
    actual = 1 if abs(ratio) < 1 - tol else 0  # |r|<1 수렴(경계 |r|=1은 발산).
    if actual == claimed_n:
        return _pass(samples_checked=1)
    verdict = "수렴" if actual else "발산"
    return _fail(
        f"등비급수 수렴 — 공비 {ratio}는 {verdict}이나 주장 {claimed_n}(불일치)",
        samples_checked=1,
    )


def verify_limit_equals_value(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """유리식 f(x)가 특이점에서 lim = f(a)를 만족하는지 0/1로 검증(개념형). `conditions`는 f(x).

    분모가 0이 되는 실수 특이점 a에서 극한값(유한)과 함수값을 비교한다 — 제거가능 특이점(0/0 꼴)은
    극한은 존재하나 함수값이 미정의라 lim ≠ f(a)(0). "극한값은 늘 함수값과 같다"는 오개념
    (limit-equals-function-value)은 1로 답해 fail한다. 자동 약분을 막으려 분자는 전개형으로 받는다.
      - pass: 실제 일치 여부(1/0) == 주장.
      - fail: 불일치(오개념).
      - unverifiable: 단일변수 유리식 아님·특이점 없음·주장 0/1 아님·극한 계산 불가(보수적 회피).
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("극한=함숫값 — 단일 식이 아님·안전 회피")
    try:
        expr = safe_sympify(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("극한=함숫값 — 식 파싱 불가·안전 회피")
    if isinstance(expr, sympy.core.relational.Relational):
        return _unverifiable("극한=함숫값 — 함수 식이어야 함(등식/부등식 아님)·안전 회피")
    if not isinstance(expr, sympy.Expr):  # P3-80 — 쉼표 나열(튜플) 등은 자유 변수 수집 전에 회피
        return _unverifiable("극한=함숫값 — 단일 식이 아님(쉼표 나열 등)·안전 회피")
    free = sorted(expr.free_symbols, key=str)
    if len(free) != 1:
        return _unverifiable("극한=함숫값 — 단일 변수 함수가 아님·안전 회피")
    claimed_n = _claimed_int(claimed, tol)
    if claimed_n not in (0, 1):
        return _unverifiable("극한=함숫값 — 주장값이 0/1이 아님·안전 회피")
    var = free[0]
    _, den = expr.as_numer_denom()
    try:
        singular = sympy.solve(sympy.Eq(den, 0), var)
    except (NotImplementedError, sympy.PolynomialError, ValueError):
        return _unverifiable("극한=함숫값 — 특이점 계산 불가·안전 회피")
    real_singular = [s for s in singular if s.is_real]
    if not real_singular:
        return _unverifiable("극한=함숫값 — 실수 특이점 없음(오개념 표적 아님)·안전 회피")
    actual = 1
    for point in real_singular:
        try:
            lim = sympy.limit(expr, var, point)
        except Exception as exc:  # noqa: BLE001 — 극한 계산 불가는 보수적 회피
            logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
            return _unverifiable("극한=함숫값 — 극한 계산 불가·안전 회피")
        if lim in (sympy.zoo, sympy.oo, -sympy.oo, sympy.nan) or lim.is_finite is not True:
            return _unverifiable("극한=함숫값 — 극한이 유한하지 않음·안전 회피")
        value = expr.subs(var, point)
        # 함수값 미정의(0/0 → nan 등) 또는 극한과 불일치 → lim ≠ f(a).
        if value.is_finite is not True or sympy.simplify(lim - value) != 0:
            actual = 0
            break
    if actual == claimed_n:
        return _pass(samples_checked=len(real_singular))
    verdict = "일치" if actual else "불일치(함숫값 미정의)"
    return _fail(
        f"극한=함숫값 — 특이점에서 {verdict}이나 주장 {claimed_n}(불일치)",
        samples_checked=len(real_singular),
    )


def verify_is_differentiable(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """함수 f(x)가 ℝ 전체에서 *미분가능*한지 0/1로 검증(개념형). `conditions`는 f(x) 식.

    절댓값 꺾인점(좌·우 미분계수 상이)에서 미분가능하지 않다 — |x-a| 꼴은 연속이나 x=a에서 미분
    불가(0). "연속이면 미분가능"이라는 오개념(continuity-implies-differentiability)은 1로 답해
    fail한다. 꺾인점 후보는 식 안 Abs 인자의 실근이며, 각 점에서 좌·우 차분몫 극한을 비교한다.
      - pass: 실제 미분가능 여부(1/0) == 주장.
      - fail: 불일치(오개념).
      - unverifiable: 단일변수 아님·주장 0/1 아님·유리식 등 도메인 복잡·극한 불가(보수적 회피).
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("미분가능 — 단일 식이 아님·안전 회피")
    try:
        expr = safe_sympify(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("미분가능 — 식 파싱 불가·안전 회피")
    if isinstance(expr, sympy.core.relational.Relational):
        return _unverifiable("미분가능 — 함수 식이어야 함(등식/부등식 아님)·안전 회피")
    if not isinstance(expr, sympy.Expr):  # P3-80 — 쉼표 나열(튜플) 등은 자유 변수 수집 전에 회피
        return _unverifiable("미분가능 — 단일 식이 아님(쉼표 나열 등)·안전 회피")
    free = sorted(expr.free_symbols, key=str)
    if len(free) != 1:
        return _unverifiable("미분가능 — 단일 변수 함수가 아님·안전 회피")
    claimed_n = _claimed_int(claimed, tol)
    if claimed_n not in (0, 1):
        return _unverifiable("미분가능 — 주장값이 0/1이 아님·안전 회피")
    var = free[0]
    # P3-79 ⑤(a) — 'ℝ 전체에서 미분가능' 은 원문이 ℝ 전체에서 정의돼야 성립한다. 평가 파싱이 접은
    # 식(`x**2*(x - 1)/(x - 1)` → x**2)으로 판정하면 원문이 정의되지 않는 x = 1 을 놓친다 — 원문이
    # ℝ 전체에서 정의되는 꼴(TOTAL)일 때만 판정하고, 그 밖은 판정 불가.
    if function_domain_kind(condition, str(var)) != "total":
        return _unverifiable(
            "미분가능 — 원문 함수가 ℝ 전체에서 정의되는 꼴임을 확인 못 함(분모·허용 구조 밖)"
            "·안전 회피"
        )
    abs_terms = expr.atoms(sympy.Abs)
    if not abs_terms:
        # Abs 없는 다항식은 ℝ 전체에서 매끄러워 미분가능(1). 그 외(유리식 등)는 도메인 복잡 → 회피.
        if expr.is_polynomial(var):
            actual = 1
        else:
            return _unverifiable("미분가능 — 다항식·절댓값 꼴이 아님·안전 회피")
    else:
        corners = _abs_real_corners(abs_terms, var)
        if isinstance(corners, str):
            return _unverifiable(f"미분가능 — {corners}·안전 회피")
        actual = 1
        for corner in corners:
            f_corner = expr.subs(var, corner)
            if f_corner.is_finite is not True:
                return _unverifiable("미분가능 — 꺾인점에서 함수값 미정의·안전 회피")
            quotient = (expr - f_corner) / (var - corner)
            try:
                left = sympy.limit(quotient, var, corner, "-")
                right = sympy.limit(quotient, var, corner, "+")
            except Exception as exc:  # noqa: BLE001 — 극한 불가는 보수적 회피
                logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
                return _unverifiable("미분가능 — 좌우 미분계수 계산 불가·안전 회피")
            if left.is_finite is not True or right.is_finite is not True or left != right:
                actual = 0  # 좌·우 미분계수 상이(또는 발산) → 그 점에서 미분 불가.
                break
    if actual == claimed_n:
        return _pass(samples_checked=1)
    verdict = "미분가능" if actual else "미분 불가(꺾인점)"
    return _fail(
        f"미분가능 — 실제 {verdict}이나 주장 {claimed_n}(불일치)",
        samples_checked=1,
    )


def _abs_real_corners(
    abs_terms: AbstractSet[sympy.Expr], var: sympy.Symbol
) -> list[sympy.Expr] | str:
    """절댓값 인자의 실근 전부(정확값 — 유리수·근호식·`CRootOf`) · 셀 수 없으면 사유 문자열.

    P3-65 리뷰 P1-1.

    `sympy.solve` 는 세 실근을 가진 기약 삼차식(`x**3 - 3*x + 1`)의 근을 허수가 섞인 근호식으로
    돌려주고 그 `is_real` 은 None 이다 — `if r.is_real` 로 거르면 **실근 셋이 조용히 사라져** 후보가
    0개가 되고, 꺾이는 함수가 '미분가능'으로 통과했다(2026-10-26 독립 리뷰 실측). 그래서 실근은
    `real_roots`(실근만·정확·`CRootOf`)로 구하고, 인자가 다항식이 아니거나 실근 판정이 확정되지
    않으면(`is_real` 이 True 가 아님) 후보 집합을 모른다 — 셀 수 없음으로 접는다(모른다 ≠ 없다).
    """
    corners: list[sympy.Expr] = []
    for term in sorted(abs_terms, key=sympy.default_sort_key):
        inner = term.args[0]
        try:
            # 인자가 다항식이 아니면(|sin x| 등 — 후보가 유한하지 않다) `Poly` 가
            # PolynomialError 다.
            roots = sympy.real_roots(sympy.Poly(inner, var))
        except (NotImplementedError, sympy.PolynomialError, ValueError) as exc:
            logger.debug("verify_answer 실근 계산 회피: %s", type(exc).__name__)
            return "꺾인점 후보 계산 불가(인자가 다항식이 아니거나 실근 계산 실패)"
        for root in roots:
            if root.is_real is not True:
                return "꺾인점 후보의 실수 여부 미확정"
            if root not in corners:
                corners.append(root)
    return corners


#: 0 이 아님을 정확히 판정한 대수적 수의 부호를 수치로 읽을 때의 자릿수·하한(아래 참조).
_SIGN_DIGITS: Final = 50
_SIGN_FLOOR: Final = sympy.Rational(1, 10**40)


def _minimal_poly(root: sympy.Expr, var: sympy.Symbol) -> sympy.Poly | None:
    """후보 근의 (Q 위) 최소다항식 — `real_roots` 는 유리수·근호식·`CRootOf` 를 섞어 돌려준다.

    셋 모두 `minimal_polynomial` 로 다룬다. 계산할 수 없으면 None(호출측이 판정 불가로 접는다).
    """
    try:
        return sympy.Poly(sympy.minimal_polynomial(root, var), var)
    except (NotImplementedError, sympy.PolynomialError, ValueError) as exc:
        logger.debug("verify_answer 최소다항식 회피: %s", type(exc).__name__)
        return None


def _nonzero_sign(value: sympy.Expr) -> int | None:
    """0 이 아님이 이미 정확히 판정된 실수의 부호 — 수치(50자리)가 하한보다 작거나 복소면 None."""
    numeric = sympy.N(value, _SIGN_DIGITS)
    if not numeric.is_real or abs(numeric) < _SIGN_FLOOR:
        return None
    return 1 if numeric > 0 else -1


def _corner_differentiability(
    expr: sympy.Expr, abs_terms: AbstractSet[sympy.Expr], var: sympy.Symbol
) -> list[bool] | str:
    """후보마다 미분가능한가(좌·우미분계수가 같은가) — **극한 없이 정확 대수**로 판정(P3-65 P1-1).

    전제: f 는 다항식과 `Abs(u)`(u 다항식)로만 된 식이다. 후보 c 에서 각 `Abs(u)` 는 c 의 양옆에서
    ±u 로 벗겨진다 — u 를 c 의 기약 다항식 g 로 나눠 u = g^k·h (h(c) ≠ 0) 라 하면 우측 부호는
    sgn h(c)·sgn g'(c)^k, 좌측 부호는 sgn h(c)·(-sgn g'(c))^k 다(g 는 기약이라 c 는 단순근). 벗긴
    두 분기 R·L 의 도함수 차 D = (R - L)' 가 c 에서 0 인지는 **D 를 g 로 나눈 나머지가 0 인가**로
    정확히 판정한다 — `CRootOf` 에서의 극한(`sympy.limit` 은 NotImplementedError)이 필요 없다.
    부호는 '0 이 아님'을 나머지로 정확히 확인한 뒤에만 50자리 수치로 읽는다(하한 미만이면 판정
    불가).
    셀 수 없으면 사유 문자열(호출측이 unverifiable 로 접는다).
    """
    stripped = expr.xreplace({term: term.args[0] for term in abs_terms})
    if not stripped.is_polynomial(var):
        return "절댓값을 벗긴 식이 다항식이 아님"
    inner_polys = {term: sympy.Poly(term.args[0], var) for term in abs_terms}
    # 아래 '나머지가 0인가'는 g(최소다항식)가 **Q 위에서** 기약이라는 데 기댄다. 계수가 Q(√2)처럼
    # 확장체에 있으면 나눗셈이 그 체에서 일어나 g가 쪼개지고(x²−2 = (x−√2)(x+√2)), 'c에서 0'이
    # 아니라 '켤레 근 전부에서 0'을 묻게 돼 매끄러운 점을 꺾인 점으로 센다(P3-65 3차 리뷰 P1 —
    # |x²−2|(x−√2)에 '2' pass). 소수(RR)·π(ZZ[π])도 같은 전제 밖이므로 정수·유리수 계수만 판정한다.
    for poly in (sympy.Poly(stripped, var), *inner_polys.values()):
        if not (poly.domain.is_ZZ or poly.domain.is_QQ):
            return "계수가 정수·유리수가 아님(정확 판정 범위 밖)"
    corners = _abs_real_corners(abs_terms, var)
    if isinstance(corners, str):
        return corners
    verdicts: list[bool] = []
    for corner in corners:
        g = _minimal_poly(corner, var)
        if g is None:
            return "후보 근의 최소다항식 계산 불가"
        g_slope = _nonzero_sign(g.diff(var).as_expr().subs(var, corner))
        if g_slope is None:
            return "후보 근의 기울기 부호 판정 불가"
        right: dict[sympy.Expr, sympy.Expr] = {}
        left: dict[sympy.Expr, sympy.Expr] = {}
        for term, u in inner_polys.items():
            k, h = 0, u
            while not h.is_zero and h.rem(g).is_zero:
                h, k = h.quo(g), k + 1
            # h = 0 이면(인자가 0 인 식 — 실근 계산이 먼저 거부해 도달하지 않는다) 부호가 None 이다.
            h_sign = _nonzero_sign(h.as_expr().subs(var, corner))
            if h_sign is None:
                return "절댓값 인자의 부호 판정 불가"
            r_sign = h_sign * g_slope**k
            l_sign = h_sign * (-g_slope) ** k
            right[term] = r_sign * term.args[0]
            left[term] = l_sign * term.args[0]
        jump = sympy.Poly(
            sympy.expand(sympy.diff(expr.xreplace(right) - expr.xreplace(left), var)), var
        )
        verdicts.append(jump.is_zero or jump.rem(g).is_zero)
    return verdicts


def verify_nondifferentiable_point_count(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """함수 f(x)가 ℝ에서 *미분가능하지 않은 점의 개수*를 검증(개념형 · P3-65).

    `conditions`는 f(x) 식이다.

    `verify_is_differentiable`(0/1)의 개수형이다. f는 다항식과 절댓값 항으로 된 식이고, 절댓값
    안의 식이 0이 아닌 점에서는 f가 한 다항식과 같아 미분가능하다. 그래서 후보는 각 `Abs` 인자의
    실근(`real_roots` — 정확값)뿐이고, 후보마다 좌·우 분기의 미분계수가 같은지를 **정확 대수**로
    판정해(`_corner_differentiability` — 극한을 쓰지 않아 무리수 근 `CRootOf` 도 판정한다) 다른 점을
    센다.
    '절댓값 안이 0이 되는 점의 개수'(`(x - p)|x - p|`·`|x - p|^3`처럼 매끄러운 꼴도 세는 오개념)나
    '절댓값 항의 개수'로 센 답은 fail한다.

    개수는 후보 **전부**를 판정해야 하므로, 한 후보라도 판정할 수 없으면 개수 전체를 판정 불가로
    둔다(모른다 ≠ 아니다 — 일부만 센 값으로 pass/fail 하지 않는다). 주장 문자열이 안전 파서에서
    거부되는 꼴('1+'·'2개')도 개수가 아니므로 판정 불가다.
      - pass: 실제 개수 == 주장.
      - fail: 불일치.
      - unverifiable: 단일변수 아님·주장이 0 이상 정수 아님·ℝ 전체 정의 꼴 확인 불가·다항식·절댓값
        꼴 아님(중첩 절댓값 포함)·후보(실근) 계산 불가·실수 여부 미확정·최소다항식 계산 불가·부호
        판정 불가(보수적 회피).
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("미분불가 점 개수 — 단일 식이 아님·안전 회피")
    try:
        expr = safe_sympify(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("미분불가 점 개수 — 식 파싱 불가·안전 회피")
    if isinstance(expr, sympy.core.relational.Relational):
        return _unverifiable("미분불가 점 개수 — 함수 식이어야 함(등식/부등식 아님)·안전 회피")
    if expr.has(sympy.Float):
        # 아래 판정은 '정확 대수'(나머지가 정확히 0인가)에 기댄다. 소수 계수는 근
        # (`real_roots`가 유리수로 돌려줌)과 식(소수 그대로) 사이에 반올림 잔차를 남겨,
        # 매끄러운 `|x - 0.1|^3`을 꺾인 점으로 세거나 `|x^2 - 2.0000000000000001|`의
        # 부호를 잘못 확정한다(P3-65 재리뷰 P1 실측). 유리화(nsimplify)는 함수를 바꿀 수
        # 있으므로 하지 않고 판정 불가로 접는다(모른다 ≠ 아니다).
        return _unverifiable("미분불가 점 개수 — 소수 계수 식은 정확 판정 불가·안전 회피")
    free = sorted(expr.free_symbols, key=str)
    if len(free) != 1:
        return _unverifiable("미분불가 점 개수 — 단일 변수 함수가 아님·안전 회피")
    try:
        claimed_n = _claimed_int(claimed, tol)
    except Exception as exc:  # noqa: BLE001 — '1+'·'2개' 등 파싱 거부는 '개수가 아님'으로 접는다
        logger.debug("verify_answer 주장 파싱 회피: %s", type(exc).__name__)
        claimed_n = None
    if claimed_n is None:
        return _unverifiable("미분불가 점 개수 — 주장값이 0 이상 정수가 아님·안전 회피")
    var = free[0]
    if function_domain_kind(condition, str(var)) != "total":
        return _unverifiable(
            "미분불가 점 개수 — 원문 함수가 ℝ 전체에서 정의되는 꼴임을 확인 못 함·안전 회피"
        )
    abs_terms = expr.atoms(sympy.Abs)
    if not abs_terms:
        if expr.is_polynomial(var):
            actual = 0
        else:
            return _unverifiable("미분불가 점 개수 — 다항식·절댓값 꼴이 아님·안전 회피")
    else:
        judged = _corner_differentiability(expr, abs_terms, var)
        if isinstance(judged, str):
            return _unverifiable(f"미분불가 점 개수 — {judged}·안전 회피")
        actual = sum(1 for differentiable in judged if not differentiable)
    if actual == claimed_n:
        return _pass(samples_checked=1)
    return _fail(
        f"미분불가 점 개수 — 실제 {actual}개이나 주장 {claimed_n}(불일치)",
        samples_checked=1,
    )


def verify_series_converges(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """일반항 a_n의 급수 Σa_n 수렴 여부를 0/1로 검증(개념형). `conditions`는 일반항 a_n(n 식).

    일반항이 0에 수렴해도 급수는 발산할 수 있다 — 조화급수 Σ1/n은 항→0이나 발산(0). "일반항이
    0이면 급수도 수렴"이라는 오개념(term-to-zero-implies-convergence)은 1로 답해 fail한다. SymPy
    `Sum.is_convergent`로 독립 판정한다.
      - pass: 실제 수렴 여부(1/0) == 주장.
      - fail: 불일치(오개념).
      - unverifiable: 단일변수 아님·주장 0/1 아님·수렴성 판정 불가(보수적 회피).
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("급수 수렴 — 단일 식이 아님·안전 회피")
    try:
        term = safe_sympify(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("급수 수렴 — 식 파싱 불가·안전 회피")
    if isinstance(term, sympy.core.relational.Relational):
        return _unverifiable("급수 수렴 — 일반항 식이어야 함(등식/부등식 아님)·안전 회피")
    if not isinstance(term, sympy.Expr):  # P3-80 — 쉼표 나열(튜플) 등은 자유 변수 수집 전에 회피
        return _unverifiable("급수 수렴 — 단일 식이 아님(쉼표 나열 등)·안전 회피")
    free = sorted(term.free_symbols, key=str)
    if len(free) != 1:
        return _unverifiable("급수 수렴 — 단일 변수 일반항이 아님·안전 회피")
    claimed_n = _claimed_int(claimed, tol)
    if claimed_n not in (0, 1):
        return _unverifiable("급수 수렴 — 주장값이 0/1이 아님·안전 회피")
    var = free[0]
    try:
        converges = sympy.Sum(term, (var, 1, sympy.oo)).is_convergent()
    except Exception as exc:  # noqa: BLE001 — 수렴성 판정 불가는 보수적 회피
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("급수 수렴 — 수렴성 판정 불가·안전 회피")
    # is_convergent는 SymPy Boolean(true/false)을 돌려준다(파이썬 bool 아님·is 비교 금지).
    if converges not in (sympy.true, sympy.false):
        return _unverifiable("급수 수렴 — 수렴성 미결정·안전 회피")
    actual = 1 if bool(converges) else 0
    if actual == claimed_n:
        return _pass(samples_checked=1)
    verdict = "수렴" if actual else "발산"
    return _fail(
        f"급수 수렴 — Σa_n은 {verdict}이나 주장 {claimed_n}(불일치)",
        samples_checked=1,
    )


def _parse_number_list(condition: str) -> list[sympy.Expr] | None:
    """쉼표 구분 수치 목록을 SymPy 정확값 리스트로 — 하나라도 파싱 불가·비수치면 None(보수적).

    항목 하나가 *SymPy 식이 아닌 값*으로 읽히면(P3-84) 그것도 파싱 불가로 친다. `safe_sympify`는
    `True`→`bool`·`None`→`NoneType`·`[1]`→`list`·`()`→`tuple`·`2 == 3`→`bool`(파이썬 구조 비교)처럼
    `.is_number`가 없는 값을 돌려줄 수 있고, 종전에는 그 속성 조회가 `try` 밖이라 `AttributeError`가
    네 검증기(평균=중앙값·독립·조건부확률·내적) 밖으로 새어 나갔다. 형태 검사(`_require_scalar`)를
    `try` 안에서 부르므로 그 실패는 다른 파싱 실패와 같은 출구(None → 호출부 unverifiable)로 닫히고,
    로그에는 `_ConditionShapeError` 타입명만 남는다(항목 값은 싣지 않는다).
    """
    parts = [p.strip() for p in condition.split(",") if p.strip()]
    if not parts:
        return None
    values: list[sympy.Expr] = []
    for part in parts:
        try:
            expr = _require_scalar(safe_sympify(part), "나열 항목")
        except Exception as exc:  # noqa: BLE001 — 파싱 불가는 목록 전체 무효
            logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
            return None
        if not expr.is_number or expr.is_real is not True:
            return None
        values.append(expr)
    return values


def verify_mean_equals_median(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """자료의 평균과 중앙값이 같은지 0/1로 검증(개념형·통계). `conditions`는 쉼표 구분 자료값 목록.

    평균=Σx/n, 중앙값=정렬 후 가운데(짝수개는 두 값 평균). SymPy 정확 산술로 대조 — 왜곡(비대칭)
    자료는 평균≠중앙값(0)이다. "평균과 중앙값은 늘 같다"는 오개념(mean-vs-median)은 1로 답해 fail.
      - pass: 실제 일치 여부(1/0) == 주장.
      - fail: 불일치(오개념).
      - unverifiable: 자료 파싱 불가·비수치·주장 0/1 아님(보수적 회피).
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("평균=중앙값 — 단일 자료 목록이 아님·안전 회피")
    values = _parse_number_list(condition)
    if values is None or len(values) < 1:
        return _unverifiable("평균=중앙값 — 자료 파싱 불가·비수치·안전 회피")
    claimed_n = _claimed_int(claimed, tol)
    if claimed_n not in (0, 1):
        return _unverifiable("평균=중앙값 — 주장값이 0/1이 아님·안전 회피")
    n = len(values)
    mean = sympy.Add(*values) / n
    ordered = sorted(values, key=lambda v: float(v))
    if n % 2 == 1:
        median = ordered[n // 2]
    else:
        median = (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    actual = 1 if sympy.simplify(mean - median) == 0 else 0
    if actual == claimed_n:
        return _pass(samples_checked=n)
    verdict = "일치" if actual else "불일치"
    return _fail(
        f"평균=중앙값 — 평균 {mean}·중앙값 {median}로 {verdict}이나 주장 {claimed_n}",
        samples_checked=n,
    )


def verify_events_independent(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """두 사건의 독립 여부를 0/1로 검증(개념형·확률). `conditions`는 "P(A),P(B),P(A∩B)".

    독립 ⇔ P(A∩B)=P(A)P(B). 배반사건(P(A∩B)=0)이라도 P(A),P(B)>0이면 0≠P(A)P(B)라 독립이 아니다.
    "배반이면 독립"이라는 오개념(mutually-exclusive-implies-independent)은 1로 답해 fail.
      - pass: 실제 독립 여부(1/0) == 주장.
      - fail: 불일치(오개념).
      - unverifiable: 세 확률 파싱 불가·범위 밖([0,1])·주장 0/1 아님(보수적 회피).
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("사건 독립 — 단일 확률 목록이 아님·안전 회피")
    values = _parse_number_list(condition)
    if values is None or len(values) != 3:
        return _unverifiable("사건 독립 — P(A),P(B),P(A∩B) 3값이 아님·안전 회피")
    p_a, p_b, p_ab = values
    if any(v < 0 or v > 1 for v in (p_a, p_b, p_ab)):
        return _unverifiable("사건 독립 — 확률이 [0,1] 밖·안전 회피")
    claimed_n = _claimed_int(claimed, tol)
    if claimed_n not in (0, 1):
        return _unverifiable("사건 독립 — 주장값이 0/1이 아님·안전 회피")
    actual = 1 if sympy.simplify(p_ab - p_a * p_b) == 0 else 0
    if actual == claimed_n:
        return _pass(samples_checked=1)
    verdict = "독립" if actual else "비독립"
    return _fail(
        f"사건 독립 — P(A∩B)={p_ab}·P(A)P(B)={p_a * p_b}로 {verdict}이나 주장 {claimed_n}",
        samples_checked=1,
    )


def verify_conditional_equal(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """P(A|B)=P(B|A) 여부를 0/1로 검증(개념형·확률). `conditions`는 "P(A),P(B),P(A|B)".

    베이즈로 P(B|A)=P(A|B)·P(B)/P(A)를 구해 P(A|B)와 대조 — P(A)≠P(B)면 둘은 다르다. "P(A|B)=P(B|A)"
    라는 오개념(prosecutor-fallacy·검사의 오류)은 1로 답해 fail한다.
      - pass: 실제 일치 여부(1/0) == 주장.
      - fail: 불일치(오개념).
      - unverifiable: 세 확률 파싱 불가·범위 밖·P(A)=0·주장 0/1 아님(보수적 회피).
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("조건부확률 대칭 — 단일 확률 목록이 아님·안전 회피")
    values = _parse_number_list(condition)
    if values is None or len(values) != 3:
        return _unverifiable("조건부확률 대칭 — P(A),P(B),P(A|B) 3값이 아님·안전 회피")
    p_a, p_b, p_ab = values
    if any(v < 0 or v > 1 for v in (p_a, p_b, p_ab)) or p_a == 0:
        return _unverifiable("조건부확률 대칭 — 확률 범위 밖 또는 P(A)=0·안전 회피")
    claimed_n = _claimed_int(claimed, tol)
    if claimed_n not in (0, 1):
        return _unverifiable("조건부확률 대칭 — 주장값이 0/1이 아님·안전 회피")
    p_ba = p_ab * p_b / p_a  # 베이즈.
    actual = 1 if sympy.simplify(p_ab - p_ba) == 0 else 0
    if actual == claimed_n:
        return _pass(samples_checked=1)
    verdict = "일치" if actual else "불일치"
    return _fail(
        f"조건부확률 대칭 — P(A|B)={p_ab}·P(B|A)={p_ba}로 {verdict}이나 주장 {claimed_n}",
        samples_checked=1,
    )


def verify_congruent_by_ratio(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """닮음비 k인 두 도형의 합동 여부를 0/1로 검증(개념형·기하). `conditions`는 닮음비 k(값/식).

    두 도형이 합동 ⇔ 닮음비 k=1. k≠1이면 닮았으나 합동이 아니다. "닮으면 합동"이라는 오개념
    (similarity-vs-congruence)은 k≠1인데 1로 답해 fail한다.
      - pass: 실제 합동 여부(1/0) == 주장.
      - fail: 불일치(오개념).
      - unverifiable: k가 실수(양수)가 아님·주장 0/1 아님(보수적 회피).
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("합동(닮음비) — 단일 값이 아님·안전 회피")
    try:
        ratio = _real_value(safe_sympify(condition), tol)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("합동(닮음비) — 닮음비 파싱 불가·안전 회피")
    if ratio is None or ratio <= 0:
        return _unverifiable("합동(닮음비) — 닮음비가 양의 실수가 아님·안전 회피")
    claimed_n = _claimed_int(claimed, tol)
    if claimed_n not in (0, 1):
        return _unverifiable("합동(닮음비) — 주장값이 0/1이 아님·안전 회피")
    actual = 1 if abs(ratio - 1) < tol else 0  # 합동 ⇔ 닮음비 1.
    if actual == claimed_n:
        return _pass(samples_checked=1)
    verdict = "합동" if actual else "합동 아님(닮음만)"
    return _fail(
        f"합동(닮음비) — 닮음비 {ratio}는 {verdict}이나 주장 {claimed_n}",
        samples_checked=1,
    )


def verify_dot_product_scalar(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """두 벡터의 내적이 *벡터*인지 0/1로 검증(개념형·벡터). `conditions`는 "a1,a2,b1,b2"(2차원).

    내적 a·b = a1·b1 + a2·b2는 하나의 수(스칼라)라 벡터가 아니다. "내적은 벡터"라는 오개념
    (dot-product-is-vector)은 1로 답해 fail한다. SymPy로 내적을 계산해 스칼라(수)임을 확인한다.
      - pass: 내적이 벡터인지(1/0) == 주장 — 유효 입력이면 항상 스칼라라 0.
      - fail: 불일치(오개념·내적을 벡터로 봄).
      - unverifiable: 네 성분 파싱 불가·주장 0/1 아님(보수적 회피).
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("내적 스칼라 — 단일 성분 목록이 아님·안전 회피")
    values = _parse_number_list(condition)
    if values is None or len(values) != 4:
        return _unverifiable("내적 스칼라 — 2차원 두 벡터 4성분이 아님·안전 회피")
    claimed_n = _claimed_int(claimed, tol)
    if claimed_n not in (0, 1):
        return _unverifiable("내적 스칼라 — 주장값이 0/1이 아님·안전 회피")
    a1, a2, b1, b2 = values
    dot = sympy.simplify(a1 * b1 + a2 * b2)
    actual = 0 if dot.is_number else 1  # 내적은 수(스칼라) → 벡터 아님(0).
    if actual == claimed_n:
        return _pass(samples_checked=1)
    verdict = "벡터" if actual else "스칼라(수)"
    return _fail(
        f"내적 스칼라 — 내적 {dot}은 {verdict}이나 주장 {claimed_n}(내적은 스칼라)",
        samples_checked=1,
    )


def verify_inequality_direction(
    conditions: str | Sequence[str],
    claimed: str,
    *,
    tol: float = 1e-9,
) -> AnswerVerdict:
    """일차부등식 해의 방향(x>c 꼴이면 1·x<c 꼴이면 0)을 검증(개념형·부등식). `conditions`는 부등식.

    SymPy `solveset`으로 해집합을 구해 방향을 판정한다 — 음수 계수로 나누면 부호가 뒤집혀 x>c가
    된다(예 -2x<6 → x>-3). "음수를 곱해도 부호 그대로"라는 오개념(sign-flip-in-inequality)은 x<c로
    오인해 틀린 판정을 준다.
      - pass: 실제 해 방향(1=x>c·0=x<c) == 주장.
      - fail: 불일치(오개념·부호 안 뒤집음).
      - unverifiable: 부등식 아님·단일변수 아님·해가 반직선(x>c/x<c) 꼴이 아님·주장 0/1 아님.
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("부등식 방향 — 단일 부등식이 아님·안전 회피")
    try:
        expr = safe_sympify(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("부등식 방향 — 부등식 파싱 불가·안전 회피")
    if not isinstance(expr, sympy.core.relational.Relational) or isinstance(expr, sympy.Equality):
        return _unverifiable("부등식 방향 — 부등식이어야 함(등식/식 아님)·안전 회피")
    free = sorted(expr.free_symbols, key=str)
    if len(free) != 1:
        return _unverifiable("부등식 방향 — 단일 변수 부등식이 아님·안전 회피")
    claimed_n = _claimed_int(claimed, tol)
    if claimed_n not in (0, 1):
        return _unverifiable("부등식 방향 — 주장값이 0/1이 아님·안전 회피")
    try:
        solution = sympy.solveset(expr, free[0], domain=sympy.S.Reals)
    except Exception as exc:  # noqa: BLE001 — 해집합 계산 불가는 보수적 회피
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("부등식 방향 — 해집합 계산 불가·안전 회피")
    if not isinstance(solution, sympy.Interval):
        return _unverifiable("부등식 방향 — 해가 반직선 꼴이 아님·안전 회피")
    inf_infinite = solution.inf in (-sympy.oo, sympy.oo)
    sup_infinite = solution.sup in (-sympy.oo, sympy.oo)
    if solution.sup == sympy.oo and not inf_infinite:
        actual = 1  # x > c(하한 유한·상한 ∞).
    elif solution.inf == -sympy.oo and not sup_infinite:
        actual = 0  # x < c(하한 -∞·상한 유한).
    else:
        return _unverifiable("부등식 방향 — 유계/전체/공집합 해·안전 회피")
    if actual == claimed_n:
        return _pass(samples_checked=1)
    verdict = "x>c(부호 뒤집힘)" if actual else "x<c"
    return _fail(
        f"부등식 방향 — 해는 {verdict}이나 주장 {claimed_n}(음수 나눗셈 시 부호 뒤집힘)",
        samples_checked=1,
    )


def warm_isolated_worker() -> None:
    """격리 워커가 `ready` 전에 부르는 웜업 — 답 검산 경로의 첫 사용 비용을 미리 치른다(OPS-142).

    `verify_step` 뒤에서는 새 모듈이 없지만(실측) 워커의 *첫* 호출이 이 경로일 수 있어, 단일 등식·
    연립·항등식 세 형태를 한 번씩 밟는다. 반환값은 쓰지 않는다.
    """
    verify_answer("x**2 - 5*x + 6 = 0", {"x": "3"})
    verify_answer(["x+y=3", "x-y=1"], {"x": "2", "y": "1"})
    verify_answer("sin(x)**2 + cos(x)**2 = 1", {"x": "1"})
