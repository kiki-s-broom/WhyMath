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

import logging
import random
from collections.abc import Mapping, Sequence
from typing import Literal

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
    "derive_selected_root",
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
    "verify_real_root_count",
    "verify_root_aggregate",
    "verify_root_selection",
    "verify_series_converges",
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


def _parse_condition(condition: str) -> tuple[sympy.Expr, str]:
    """condition 문자열을 (잔차 식, 관계 연산자)로 파싱.

    반환 연산자:
      - `"=="` — 등식(조건 만족 ⇔ residual == 0). `=`/`Eq`/`Equality`, 또는 등호가 없는 단일
        식("== 0" 으로 해석). 잔차는 `lhs - rhs`(단일 식이면 식 자체).
      - `">"`,`"<"`,`">="`,`"<="`,`"!="` — 부등식·≠. 잔차는 `lhs - rhs`이며, 진리값은 잔차를
        수치 평가해 *연산자*로 판정한다(`_eval_relation`). 별도의 진리값 평가 경로다.

    파싱 불가는 예외를 일으켜 호출부가 unverifiable로 처리한다(보수적·pass 위장 금지).
    """
    text = condition.strip()
    if not text:
        raise ValueError("빈 condition")

    # `!=`(≠)는 파이썬 비교라 sympify가 bool로 접어버린다 — SymPy `Ne(lhs, rhs)`로 명시 변환.
    if "!=" in text:
        lhs_text, rhs_text = text.split("!=", 1)
        lhs = safe_sympify(lhs_text)
        rhs = safe_sympify(rhs_text)
        return ensure_within_budget(lhs - rhs), "!="

    # `==`(파이썬식 등호)를 등식 잔차로 변환 — sympify가 `==`를 *구조 비교*로 접어 `False`(상수
    # 진리값)로 만들기 전에 문자열에서 직접 분해한다. 실 LLM이 `x**2-1 == 0`처럼 파이썬식 등호를
    # 쓰는 회귀(Phaiakes9 실측·S2-i) — 단일 `=` 경로와 동형이되 `==` 토큰을 별도로 받는다.
    if "==" in text:
        lhs_text, rhs_text = text.split("==", 1)
        lhs = safe_sympify(lhs_text)
        rhs = safe_sympify(rhs_text)
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
        lhs = safe_sympify(lhs_text)
        rhs = safe_sympify(rhs_text)
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
    # 등식 기호가 없는 단일 식 → 식 == 0을 묻는 잔차로 본다.
    return parsed, "=="


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
                return _pass(samples_checked=1)
            if verdict is False:
                return _fail(f"조건 위반 — 잔차 ≠ 0: {substituted}", samples_checked=1)
            return _unverifiable("수치 평가 불가(복소/NaN 등) — 검증 안전 회피")
        # 부등식 — 잔차 실수값을 연산자 진리값으로 판정.
        magnitude = _eval_relation_residual(substituted, tol)
        if magnitude is None:
            return _unverifiable("부등식 잔차 수치 평가 불가(복소/NaN 등) — 검증 안전 회피")
        truth = _eval_relation(magnitude, op, tol)
        if truth is True:
            return _pass(samples_checked=1)
        if truth is False:
            return _fail(f"부등식 조건 위반({op}) — 잔차 {magnitude}", samples_checked=1)
        return _unverifiable(f"부등식 경계 모호({op}) — 검증 안전 회피")

    # ④ 자유변수 있음(파라미터 문제) → 수치 샘플링(Tier1 핵심·고정 시드 결정론).
    return _sample_parametric(substituted, free_symbols, op, n_samples=n_samples, tol=tol)


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

    # 유효 샘플이 하나도 없으면 판정 불가(전부 특이점·복소·경계 모호) — pass 위장 금지.
    if valid_samples == 0:
        return _unverifiable("유효 샘플 0(전부 특이점/복소/경계 모호) — 검증 안전 회피")

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

    적용 범위: **단일 변수·단일 등식** 조건만. 연립·다변수·파라미터·부등식·비다항 등 풀 수 없거나
    실근이 없거나 답이 실근이 아니면 **unverifiable**(보수적·pass 위장 금지 — verify_answer 정직성
    상속). 이 함수는 답이 조건을 *만족*하는지는 검사하지 않는다(그건 verify_answer 소관) — 오직
    *선택*만 판정한다. 판정:
      - **pass**: 답이 요구된 근(largest=최대·smallest=최소·unique=유일)과 일치.
      - **fail**: 답이 실근이나 *요구된 근이 아님*(예 큰 근 요구에 작은 근·unique 요구에 다근).
      - **unverifiable**: 적용 밖(풀 수 없음·다변수·실근 없음 등) — Tier1에 판정을 맡긴다.
    """
    # 단일 등식만 — 연립/빈 조건은 선택 의미가 불명확(보수적 회피).
    if isinstance(conditions, str):
        condition: str | None = conditions
    else:
        condition_list = list(conditions)
        condition = condition_list[0] if len(condition_list) == 1 else None
    if condition is None:
        return _unverifiable("근 선택 — 단일 등식이 아님(연립/빈 조건)·안전 회피")

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

    try:
        ans_val = _real_value(safe_sympify(ans_text), tol)
        raw_roots = sympy.solve(sympy.Eq(residual, 0), var)
    except Exception as exc:  # noqa: BLE001 — 풀이/치환 불가는 보수적 unverifiable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return _unverifiable("근 선택 — 방정식 풀이/치환 불가·안전 회피")
    if ans_val is None:
        return _unverifiable("근 선택 — 답이 실수가 아님·안전 회피")

    real_roots = [rv for r in raw_roots if (rv := _real_value(r, tol)) is not None]
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
    except Exception as exc:  # noqa: BLE001 — 풀이 불가는 보수적 None
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return None

    # (정확근, 실수값) 쌍 — 복소근은 제외. 실수값은 선택 판정용·반환은 정확근 문자열.
    reals = [(r, rv) for r in raw_roots if (rv := _real_value(r, tol)) is not None]
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
        raw_roots = sympy.solve(sympy.Eq(residual, 0), var)
    except Exception as exc:  # noqa: BLE001 — 풀이 불가는 보수적 undecidable
        logger.debug("verify_answer 보수 회피: %s", type(exc).__name__)
        return SolvabilityVerdict(state="undecidable", reason="방정식 풀이 불가")

    real_roots = [rv for r in raw_roots if (rv := _real_value(r, tol)) is not None]
    distinct = _distinct_values(real_roots, tol)
    n = len(distinct)
    if n == 0:
        return SolvabilityVerdict(
            state="no_solution", reason="다항이나 실근이 하나도 없음(복소근만)"
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
      - pass: 실제 서로 다른 실근 수 == 주장 개수.
      - fail: 불일치(오개념).
      - unverifiable: 단일변수 다항 등식 아님·근을 다 못 구함·주장이 개수 아님(보수적 회피).
    """
    condition = _single_condition(conditions)
    if condition is None:
        return _unverifiable("실근 개수 — 단일 등식이 아님·안전 회피")
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
    real = [rv for r in root_mult if (rv := _real_value(r, tol)) is not None]
    actual = len(_distinct_values(real, tol))
    if actual == claimed_n:
        return _pass(samples_checked=actual)
    return _fail(
        f"실근 개수 — 실제 {actual}개이나 주장은 {claimed_n}개(불일치)",
        samples_checked=actual,
    )


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
    # 극값 = 실근 중 중복도 홀수(부호 변화). 짝수 중복도(예 x³의 f'=3x²)는 극값 아님.
    actual = sum(
        1
        for root, mult in root_mult.items()
        if _real_value(root, tol) is not None and mult % 2 == 1
    )
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
    free = sorted(expr.free_symbols, key=str)
    if len(free) != 1:
        return _unverifiable("일대일 — 단일 변수 함수가 아님·안전 회피")
    claimed_n = _claimed_int(claimed, tol)
    if claimed_n not in (0, 1):
        return _unverifiable("일대일 — 주장값이 0/1이 아님·안전 회피")
    var = free[0]
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
        sign_changes = sum(
            1
            for root, mult in root_mult.items()
            if _real_value(root, tol) is not None and mult % 2 == 1
        )
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
    free = sorted(expr.free_symbols, key=str)
    if len(free) != 1:
        return _unverifiable("미분가능 — 단일 변수 함수가 아님·안전 회피")
    claimed_n = _claimed_int(claimed, tol)
    if claimed_n not in (0, 1):
        return _unverifiable("미분가능 — 주장값이 0/1이 아님·안전 회피")
    var = free[0]
    abs_terms = expr.atoms(sympy.Abs)
    if not abs_terms:
        # Abs 없는 다항식은 ℝ 전체에서 매끄러워 미분가능(1). 그 외(유리식 등)는 도메인 복잡 → 회피.
        if expr.is_polynomial(var):
            actual = 1
        else:
            return _unverifiable("미분가능 — 다항식·절댓값 꼴이 아님·안전 회피")
    else:
        corners: set[sympy.Expr] = set()
        for term in abs_terms:
            try:
                roots = sympy.solve(sympy.Eq(term.args[0], 0), var)
            except (NotImplementedError, sympy.PolynomialError, ValueError):
                return _unverifiable("미분가능 — 꺾인점 계산 불가·안전 회피")
            corners.update(r for r in roots if r.is_real)
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
    """쉼표 구분 수치 목록을 SymPy 정확값 리스트로 — 하나라도 파싱 불가·비수치면 None(보수적)."""
    parts = [p.strip() for p in condition.split(",") if p.strip()]
    if not parts:
        return None
    values: list[sympy.Expr] = []
    for part in parts:
        try:
            expr = safe_sympify(part)
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
