"""오개념 커버리지 확대용 수치평가 객관식 스켈레톤 생성기 — S2 확장(결정론·LLM 0).

`CalculusExtremumMCSkeletonGenerator`(극값 MC)의 형제다. 같은 `EquivalentProblemGenerator`
좌석을 구현하되 목적이 다르다: 기존 코퍼스가 `distractor_map`으로 커버하지 못하던 오개념 여러 종을
문항에 *등장*시켜 crosswalk 기계 게이트의 machine-decidable 커버리지(8/34→13/34)를 끌어올린다.

여덟 템플릿(각각 오개념 1종을 오답 선지로 태깅):
  - `distribution`   — (a+b)² 의 값(오개념: 제곱을 각 항에 분배해 교차항 2ab 누락 → a²+b²).
  - `chain_rule`     — f(x)=(kx+c)³ 의 f'(x₀)(오개념: 연쇄법칙 내부 도함수 k 누락 → 3(kx₀+c)²).
  - `sine_sum`       — sin(A+B) 의 값(오개념: 사인을 합에 분배 → sin A + sin B).
  - `exp_zero`       — n + a^0 의 값(오개념: a^0=0 으로 오인 → n).
  - `sqrt_pos`       — √((-a)²) 의 값(오개념: √(x²)=x 로 오인 → -a).
  - `log_dist`       — log₂(2^k + 2^k) 의 값(오개념: log₂(2^k)+log₂(2^k)=k+k → 2k).
  - `func_compose`   — f(x)=x+a, g(x)=bx 의 (f∘g)(c)(오개념: 합성 순서 뒤집어 (g∘f)(c) → bc+ab).
  - `sine_period`    — y=sin(kx) 의 주기(오개념: 계수 k 무시 주기 불변 오인 → 2π).

뒤 5종(exp_zero~sine_period)은 정본 카탈로그에는 실재하나 유발 op-code가 없다(수치평가 MC는
op-code 없이 오개념만 태깅 — `DistractorEntry.op_code` 옵셔널·`distractor_codes` op_code=None 허용).

핵심 통찰(극값 MC 미러·재구현 0): 수치평가 문항은 정답이 *하나의 닫힌 값*이라, dummy 변수 x의
등식 `x = <닫힌형 식>`(conditions)과 `{"x": <정답값>}`(answer_map)로 기존 Tier1 검산 스택
(`verify_answer`·`classify_solvability`)을 **무변경 재사용**한다 — 오케스트레이터·수용 게이트·
저장 sink 전부 그대로다. 오답 선지 오개념·op-code id는 생성자 `distractor_codes`로 주입받는다
(L4 하드코딩 0·계층 규칙·극값 MC 규약 미러).

정직성·이중 방어: 생성물은 S2-a 게이트(정확성·저작권·위생·동등성)를 통과해야 저장된다. 각 문항의
4지선다는 *4값이 서로 다른* 경우만 수록하고(정답·오개념 오답·filler 2종), 오개념 오답 1건만
`distractor_map`에 태깅한다(filler는 미태깅·스키마 계약). 산출물은 v0(사람 검수 전) —
게이트 통과 ≠ 학생 노출(§03 정본).

7계층: L3 지역(생성=LLM 라우터 도메인이나 이 구현은 LLM 0 — 좌석 계약만 공유). schema(최하위)·
동일 패키지(generator·acceptance·canonicalize)·L1 problem_bank(ConceptTag)만 import(L4 참조 0).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from math import comb, factorial, gcd, isqrt, perm
from typing import Literal

import sympy

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.canonicalize import canonical_signature
from whymath_backend.l3.equivalent.generator import CandidateProblem, deterministic_generator
from whymath_backend.lang.josa import eul_reul, eun_neun, euro_ro, i_ga, wa_gwa
from whymath_backend.schema.enums import (
    AnswerFormat,
    Curriculum,
    GenerationType,
    LicenseType,
    QuestionFormat,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import DistractorEntry, Problem
from whymath_backend.schema.provenance import ContentProvenance

__all__ = [
    "MisconceptionEvalMCSkeletonGenerator",
    "TemplateKind",
]

# 풀 셔플 고정 시드 — 같은 구성은 같은 출제 순서(재현·디버그). 비결정 난수 금지(verify 규약 미러).
_POOL_SEED = 20260709

# 수치 4-상이 판정 허용치 — 두 선지 값이 이보다 가까우면 사실상 같은 값(4지선다 부적격).
_DISTINCT_TOL = 1e-9

TemplateKind = Literal[
    "distribution",
    "chain_rule",
    "sine_sum",
    "exp_zero",
    "sqrt_pos",
    "log_dist",
    "func_compose",
    "sine_period",
    "translate",
    "product_rule",
    "fraction_cancel",
    "polygon_angle_sum",
    "area_perimeter",
    "circle_radius",
    "gambler_streak",
    "fraction_addition",
    "negative_product",
    "subtract_negative",
    "absolute_value",
    "sqrt_sum",
    "difference_of_squares",
    "exponent_product",
    "power_of_power",
    "negative_square",
    "distribute_partial",
    "negative_distribute",
    "square_difference",
    "midpoint_no_half",
    "scale_area",
    "negative_even_power",
    "combine_unlike",
    "complete_square",
    "conjugate_product",
    "transpose",
    "gcd_lcm",
    "decimal_mult",
    "mixed_mult",
    "remainder_sign",
    "vieta_sum",
    "trapezoid_area",
    "scale_volume",
    "cone_volume",
    "circle_area",
    "combination",
    "same_item_permutation",
]

# 템플릿별 L1 데이터 메타(개념 원천 src_id·단원 코드) — L4 오개념 주입 원칙 밖(L1 데이터).
# concept_src_id는 개념그래프 원천 키, unit_code는 문항 단원 코드. 성취기준 코드는 spec이 공급한다.
#
# S3-12 rotation-1 자기정합성 교정(2026-07-29): `misconception_mc_batch._Band.standard_codes`
# 재태깅 시 이 dict의 concept_src_id는 갱신되지 않아 13개 항목이 achievement_standard_codes와
# 무관한 개념(concept_graph_v1)을 계속 가리키고 있었다(M0052 크로스링크 회귀와 동일 계통 —
# 표시용 태그만 고치고 그래프 순회용 앵커를 놓치는 패턴). concept_graph_v1의 standard_codes로
# 역탐색해 실제 겹치는 개념으로 전부 재고정(아래 개별 주석 = 신규 src_id 선정 근거).
_TEMPLATE_META: dict[TemplateKind, tuple[str, str]] = {
    "distribution": ("J0219", "POLY-PRODUCT"),
    "chain_rule": ("H:12미적Ⅰ02-01", "CALC-CHAIN"),
    "sine_sum": ("H:12미적Ⅱ02-02", "TRIG-ADD"),
    "exp_zero": ("J0208", "EXP-ZERO"),
    "sqrt_pos": ("J0107", "SQRT-POS"),
    "log_dist": ("H:12대수01-05", "LOG-DIST"),
    "func_compose": ("HK35", "FUNC-COMPOSE"),
    # sine_period(S3-12 rotation-1 재고정): 밴드 성취기준이 [12미적Ⅱ-02-02]→[12대수02-02]로
    # 재태깅됐으나 concept_src_id는 그대로였다 — [12대수02-02](삼각함수의 뜻과 그래프) 보유
    # H:12대수02-02로 교정.
    "sine_period": ("H:12대수02-02", "TRIG-PERIOD"),
    "translate": ("10기수2-01-06", "FUNC-TRANSLATE"),
    "product_rule": ("H:12미적Ⅰ02-01", "CALC-PRODUCT"),
    "fraction_cancel": ("J0104", "FRACTION-CANCEL"),
    "polygon_angle_sum": ("J0305", "POLYGON-ANGLE-SUM"),
    # area_perimeter(S3-12 rotation-1 재고정): 재태깅 후 [9수03-12](닮음)만 보유한 J0312는
    # 무관 — 문항이 실제로 묻는 직사각형 넓이 [6수03-13] 보유 ME3로 교정.
    "area_perimeter": ("ME3", "AREA-PERIMETER"),
    # circle_radius(S3-12 rotation-1 발견 — 재태깅과 무관한 선재 결함): 원래 값 "10공수2-01-04"는
    # concept_graph_v1에 없는 성취기준 코드 문자열이 그대로 src_id 자리에 들어간 오기(이 그래프는
    # 원칙적으로 J/H:/HK/ME/S 접두 source_id를 쓰나 드물게 코드형 source_id도 있다 — 다만 그건
    # "10기수2-01-04"(원의 방정식, 별개 개념)이지 "10공수2-01-04"가 아니다). 밴드 표준코드 3종
    # 중 [10공수2-01-04] 보유 HK22(원의 방정식-2)로 교정.
    "circle_radius": ("HK22", "CIRCLE-RADIUS"),
    "gambler_streak": ("H:12확통02-01", "PROB-INDEPENDENT-TRIAL"),
    # 843 확장 트랜치1(기초 계산형 6종) — 성취기준은 spec이 공급([9수01-*]).
    # fraction_addition(S3-12 rotation-1 재고정): [9수01-04]→[9수01-05] 재태깅에 맞춰 J0104→
    # [9수01-05] 보유 J0105로 교정.
    "fraction_addition": ("J0105", "FRACTION-ADD"),
    "negative_product": ("J0103", "NEG-PRODUCT"),
    "subtract_negative": ("J0103", "SUBTRACT-NEG"),
    "absolute_value": ("J0104", "ABS-VALUE"),
    "sqrt_sum": ("J0107", "SQRT-SUM"),
    # difference_of_squares(S3-12 rotation-1 재고정): [9수01-01]→[9수02-19] 재태깅에 맞춰
    # [9수02-19](다항식의 곱셈·인수분해) 보유 J0219로 교정.
    "difference_of_squares": ("J0219", "DIFF-SQUARES"),
    # 843 확장 트랜치2(거듭제곱·분배·부호 계산형 6종) — 성취기준은 spec이 공급([9수02-*]).
    "exponent_product": ("J0208", "EXP-PRODUCT"),
    "power_of_power": ("J0208", "POWER-OF-POWER"),
    "negative_square": ("J0208", "NEG-SQUARE"),
    # distribute_partial/negative_distribute(S3-12 rotation-1 재고정): 둘 다 [9수02-09]→
    # [9수02-10] 재태깅에 맞춰 [9수02-10](단항식과 다항식의 곱셈) 보유 J0210으로 교정 —
    # J0209(다항식의 덧셈·뺄셈)는 combine_unlike의 정당한 앵커라 그대로 둔다(오직 이 두
    # 템플릿의 배정이 오귀속이었음).
    "distribute_partial": ("J0210", "DISTRIBUTE-PARTIAL"),
    "negative_distribute": ("J0210", "NEG-DISTRIBUTE"),
    "square_difference": ("J0219", "SQUARE-DIFF"),
    # 843 확장 트랜치3(중점·비례·부호·동류항·완전제곱·켤레 계산형 6종).
    "midpoint_no_half": ("J0205", "MIDPOINT-NO-HALF"),
    "scale_area": ("J0207", "SCALE-AREA"),
    "negative_even_power": ("J0208", "NEG-EVEN-POWER"),
    "combine_unlike": ("J0209", "COMBINE-UNLIKE"),
    "complete_square": ("J0219", "COMPLETE-SQUARE"),
    "conjugate_product": ("J0107", "CONJUGATE-PRODUCT"),
    # 843 확장 트랜치4(이항·GCD/LCM·소수·대분수·나머지정리·근과계수 계산형 6종).
    # transpose(S3-12 rotation-1 재고정): [9수02-13]→[9수02-04] 재태깅에 맞춰 [9수02-04]
    # (일차방정식 풀이·활용) 보유 J0204로 교정.
    "transpose": ("J0204", "TRANSPOSE-SIGN"),
    "gcd_lcm": ("J0102", "GCD-LCM"),
    # decimal_mult(S3-12 rotation-1 재고정): [9수01-06]→[6수01-13] 재태깅에 맞춰 [6수01-13]
    # (소수의 곱셈) 보유 S5로 교정.
    "decimal_mult": ("S5", "DECIMAL-MULT"),
    # mixed_mult(S3-12 rotation-1 재고정): [9수01-04]→[9수01-05] 재태깅에 맞춰 fraction_addition과
    # 동일 근거로 J0105로 교정(공유 앵커 — [9수01-05]는 정수·유리수 사칙연산 포괄 성취기준).
    "mixed_mult": ("J0105", "MIXED-MULT"),
    # remainder_sign(S3-12 rotation-1 재고정): [10공수1-01-01]→[10공수1-01-02] 재태깅에 맞춰
    # 교정 — [10공수1-01-02] 보유 개념이 HK02(항등식·미정계수)·HK03(나머지정리·인수정리) 둘이라
    # misconception 자체가 "나머지정리"이므로 HK03을 선택(HK02는 무관 개념).
    "remainder_sign": ("HK03", "REMAINDER-THEOREM"),
    "vieta_sum": ("HK08", "VIETA-SUM"),
    # 843 확장 트랜치5(비대수 도메인·기하4·확통2) — 성취기준은 spec이 공급.
    # trapezoid_area(S3-12 rotation-1 재고정): [9수03-12]→[6수03-14] 재태깅에 맞춰 [6수03-14]
    # (평행사변형·삼각형·사다리꼴·마름모의 넓이) 보유 ME4로 교정.
    "trapezoid_area": ("ME4", "TRAPEZOID-AREA"),
    "scale_volume": ("J0312", "SCALE-VOLUME"),
    "cone_volume": ("J0308", "CONE-VOLUME"),
    # circle_area(S3-12 rotation-1 재고정): [9수03-19]→[6수03-16]/[9수03-06] 재태깅에 맞춰
    # [6수03-16](원주와 원의 넓이 — 문항이 실제로 묻는 넓이·둘레 혼동을 그대로 포괄) 보유
    # ME6으로 교정(J0306=부채꼴은 다른 도형이라 배제).
    "circle_area": ("ME6", "CIRCLE-AREA"),
    "combination": ("HK41", "COMBINATION-COUNT"),
    # same_item_permutation(S3-12 rotation-1 재고정): [12직수04-01]만→[12확통01-01] 추가
    # 재태깅에 맞춰 교정 — 종전 HK41(조합)은 combination 템플릿의 정당한 앵커라 여기 재사용은
    # 애초 오귀속이었다. [12확통01-01](중복순열·같은 것이 있는 순열)이 이름 그대로의 정확한
    # 매치라 H:12확통01-01로 교체(H:12직수04-01은 범용 직무 경우의 수라 배제).
    "same_item_permutation": ("H:12확통01-01", "SAME-ITEM-PERM"),
}


@dataclass(frozen=True, slots=True)
class _EvalItem:
    """수치평가 MC 뼈대 — 한 문항의 전 계산 결과(수치의 단일 진실 원천·결정론).

    선지(`choices`)는 4값을 *수치 오름차순*으로 정렬한 표기 문자열이고, `answer_index`·`misc_index`
    는 그 정렬 안의 정답·오개념 오답 위치다(정렬 확정으로 결정론). `conditions`/`answer_str`은 Tier1
    검산 재료(dummy x 등식·정답값). 오개념 id·op-code는 뼈대에 담지 않는다 — 생성기가 주입한다.
    """

    conditions: str
    answer_str: str
    choices: tuple[str, str, str, str]
    answer_index: int
    misc_index: int
    question_text: str
    answer_explanation: str
    difficulty: float
    answer_format: AnswerFormat


def _difficulty(seed: int) -> float:
    """종합 난이도를 [2.5, 3.5] 밴드에 결정론 분산 — spec 난이도 3.0·tol 0.5 안이라 동등성 만점."""
    return round(2.5 + (seed % 11) * 0.1, 1)


def _answer_format_for(value: sympy.Expr) -> AnswerFormat:
    """정답값 형태 — 양의 정수=자연수·유리(비정수)=분수·그 외(무리·음수·0)=실수."""
    if value.is_integer and value > 0:
        return AnswerFormat.자연수
    if value.is_rational:
        return AnswerFormat.분수
    return AnswerFormat.실수


def _display(value: sympy.Expr) -> str:
    """선지·정답 표기 문자열 — SymPy 정확값(반올림 소수 아님·파싱 가능 형태 'sqrt(3)/2')."""
    return str(sympy.sstr(value))


def _numeric(value: sympy.Expr) -> float:
    """정렬·상이 판정용 실수 근사(SymPy 정확값을 float로)."""
    return float(value)


def _four_distinct(values: Sequence[sympy.Expr]) -> bool:
    """네 선지 값이 수치적으로 서로 다른가(4지선다 자격) + 0 값 없음(위생·filler 규약)."""
    nums = [_numeric(v) for v in values]
    if any(abs(n) < _DISTINCT_TOL for n in nums):
        return False  # 0 선지 금지(filler·정답 모두 — 위생).
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            if abs(nums[i] - nums[j]) < _DISTINCT_TOL:
                return False
    return True


def _assemble_item(
    *,
    values: tuple[sympy.Expr, sympy.Expr, sympy.Expr, sympy.Expr],
    conditions: str,
    answer_str: str,
    question_text: str,
    answer_explanation: str,
    difficulty: float,
    answer_format: AnswerFormat,
) -> _EvalItem | None:
    """4값(정답·오개념·filler1·filler2)을 수치 오름차순 선지로 접어 뼈대 조립 — 4-상이 아니면 None.

    `values`는 (정답, 오개념 오답, filler1, filler2) 순서다. 표기 문자열까지 서로 다른지도 확인해
    (수치는 다르나 표기가 겹치는 병리 케이스) 4지선다 자격을 이중 보장한다.
    """
    if not _four_distinct(values):
        return None
    roles = ("correct", "misc", "f1", "f2")
    entries = sorted(zip(roles, values, strict=True), key=lambda e: _numeric(e[1]))
    choices = tuple(_display(v) for _, v in entries)
    if len(set(choices)) != 4:
        return None  # 표기 충돌(수치는 달랐으나 문자열이 같음) — 안전 배제.
    ordered_roles = [role for role, _ in entries]
    return _EvalItem(
        conditions=conditions,
        answer_str=answer_str,
        choices=(choices[0], choices[1], choices[2], choices[3]),
        answer_index=ordered_roles.index("correct"),
        misc_index=ordered_roles.index("misc"),
        question_text=question_text,
        answer_explanation=answer_explanation,
        difficulty=difficulty,
        answer_format=answer_format,
    )


def _build_distribution_pool() -> tuple[_EvalItem, ...]:
    """(a+b)² 값 뼈대 풀 — 정답 (a+b)²·오개념 a²+b²(교차항 누락)·filler 2ab·a²+b²+ab.

    정답값 (a+b)²=합²으로 dedup(같은 합은 conditions 정규형이 같아 구조 dedup 충돌). a<b·a,b≥2라
    네 값 {(a+b)², a²+b², 2ab, a²+b²+ab}은 항상 서로 다르다(대수적 증명·전건 4-상이).
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(2, 8):
        for b in range(a + 1, 24):
            correct_v = (a + b) ** 2
            if correct_v in seen:
                continue  # 같은 합 → 같은 정답값 → 구조 signature 충돌(회차 낭비 방지).
            correct = sympy.Integer(correct_v)
            misc = sympy.Integer(a * a + b * b)  # 교차항 2ab 누락.
            filler1 = sympy.Integer(2 * a * b)  # 교차항만.
            filler2 = sympy.Integer(a * a + b * b + a * b)  # 교차항을 1배만(2배를 1배로).
            item = _assemble_item(
                values=(correct, misc, filler1, filler2),
                conditions=f"x = ({a}+{b})**2",
                answer_str=str(correct_v),
                question_text=(
                    f"두 수 a, b에 대하여 a = {a}, b = {b} 일 때, (a+b)^2 의 값을 구하시오."
                ),
                answer_explanation=(
                    # 조사는 수 읽기 받침 판별(josa 헬퍼) — S3-09 감사 조사 계통 결함 교정(S3-12).
                    f"(a+b)^2 = a^2 + 2ab + b^2 이므로 a = {a}, b = {b} {eul_reul(str(b))} "
                    f"대입하면 (a+b)^2 = {correct_v} 이다. 교차항 2ab 를 빠뜨리면 "
                    f"a^2+b^2 {i_ga('a^2+b^2')} 되어 틀린다."
                ),
                difficulty=_difficulty(a + b),
                answer_format=AnswerFormat.자연수,
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_chain_rule_pool() -> tuple[_EvalItem, ...]:
    """f(x)=(kx+c)³ 의 f'(x₀) 뼈대 풀 — 정답 3k(kx₀+c)²·오개념 3(kx₀+c)²(내부 도함수 k 누락).

    filler: 3k²(kx₀+c)²(k 이중 적용)·k(kx₀+c)²(거듭제곱 계수 3 누락). k≥2·k≠3라 네 계수
    {3k, 3, 3k², k}가 서로 달라(대수적 증명) 전건 4-상이. 정답값으로 dedup(구조 signature 충돌↓).
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for k in (2, 4, 5):  # k≥2(3k≠3)·k≠3(3≠k, 즉 오개념≠filler2 계수 충돌 회피).
        for x0 in range(1, 4):
            for c in range(1, 5):
                inner = k * x0 + c  # ≥3 > 0.
                correct_v = 3 * k * inner * inner
                if correct_v in seen:
                    continue
                inner_sq = sympy.Integer(inner * inner)
                correct = sympy.Integer(correct_v)
                misc = sympy.Integer(3) * inner_sq  # 내부 도함수 k 누락.
                filler1 = sympy.Integer(3 * k * k) * inner_sq  # k 이중 적용.
                filler2 = sympy.Integer(k) * inner_sq  # 거듭제곱 계수 3 누락.
                item = _assemble_item(
                    values=(correct, misc, filler1, filler2),
                    conditions=f"x = 3*{k}*({k}*{x0}+{c})**2",
                    answer_str=str(correct_v),
                    question_text=(
                        f"함수 f(x) = ({k}x + {c})^3 의 x = {x0} 에서의 미분계수 "
                        f"f'({x0}) 의 값을 구하시오."
                    ),
                    answer_explanation=(
                        # 조사는 수 읽기 받침 판별 — 'x = 2 을' 류 계통 결함 교정(S3-12).
                        f"연쇄법칙으로 도함수를 구하면 내부 함수의 도함수 {k} "
                        f"{eul_reul(str(k))} 곱해야 한다. x = {x0} {eul_reul(str(x0))} "
                        f"대입하면 미분계수는 {correct_v} 이다. "
                        f"내부 도함수 {k} {eul_reul(str(k))} 곱하지 않으면 틀린 값이 된다."
                    ),
                    difficulty=_difficulty(k + inner),
                    answer_format=AnswerFormat.자연수,
                )
                if item is not None:
                    seen.add(correct_v)
                    pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_sine_pool() -> tuple[_EvalItem, ...]:
    """sin(A+B) 값 뼈대 풀 — 정답 k·sin(A+B)·오개념 k·(sinA+sinB)(사인을 합에 분배).

    filler: k·sinA·cosB(덧셈정리 한 항만)·k·cosA·cosB(코사인 정리와 혼동). A=aπ/12·B=bπ/12(15°
    격자)라 sin(A+B)는 덧셈정리의 정본 산출값(sin15°·sin45°·sin75° 등 표준 특수각)이다 — 이 오개념
    (sin의 합 분배)이 정확히 겨냥하는 문항 유형. 15° 격자만으론 서로 다른 sin(A+B) 값이 12종뿐이라,
    작은 정수 배수 k(1~3)를 곱해 서로 다른 정답값을 넉넉히 확보한다(k배는 오개념 충실도를 보존 —
    학생이 sin을 합에 분배하면 k(sinA+sinB)가 됨). 정답값으로 dedup(sin 특수각은 대수 상수로 접혀
    conditions가 다항 signature를 가지므로 값 dedup=구조 dedup 정합). 0 값·4-비상이는 배제.
    """
    pi = sympy.pi
    pool: list[_EvalItem] = []
    seen: set[float] = set()
    for a in range(1, 12):
        for b in range(a, 12):  # a ≤ b(대칭 중복 축소)·A,B ∈ (0, π).
            a_ang = sympy.Rational(a, 12) * pi
            b_ang = sympy.Rational(b, 12) * pi
            base = sympy.sin(a_ang + b_ang)
            base_misc = sympy.sin(a_ang) + sympy.sin(b_ang)
            base_f1 = sympy.sin(a_ang) * sympy.cos(b_ang)
            base_f2 = sympy.cos(a_ang) * sympy.cos(b_ang)
            for k in (1, 2, 3):
                correct = sympy.Integer(k) * base
                key = round(_numeric(correct), 9)
                if abs(key) < _DISTINCT_TOL or key in seen:
                    continue  # 0(위생)·정답값 중복(구조 dedup 충돌) 배제.
                coeff = "" if k == 1 else f"{k} "
                item = _assemble_item(
                    values=(
                        correct,
                        sympy.Integer(k) * base_misc,  # 사인 합 분배(오개념).
                        sympy.Integer(k) * base_f1,  # 덧셈정리 한 항만.
                        sympy.Integer(k) * base_f2,  # 코사인 정리와 혼동.
                    ),
                    conditions=f"x = {k}*sin({a}*pi/12 + {b}*pi/12)",
                    answer_str=_display(correct),
                    question_text=(
                        f"두 각 A = {a}π/12, B = {b}π/12 에 대하여 "
                        f"{coeff}sin(A + B) 의 값을 구하시오."
                    ),
                    answer_explanation=(
                        "삼각함수의 덧셈정리에 의해 sin(A + B) = sin A cos B + cos A sin B 이다. "
                        "사인을 합에 분배하여 sin A + sin B 로 계산하면 틀린 값이 된다."
                    ),
                    difficulty=_difficulty(a + b + k),
                    answer_format=_answer_format_for(correct),
                )
                if item is not None:
                    seen.add(key)
                    pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_exp_zero_pool() -> tuple[_EvalItem, ...]:
    """n + a^0 값 뼈대 풀 — 정답 n+1(a^0=1)·오개념 n(a^0=0)·filler n+a(a^0=a)·n+2.

    a≥2·n≥1. 정답값 n+1로 dedup(같은 n은 정답 signature 동일). filler1=n+a가 a=2일 때
    filler2=n+2와 충돌하므로 그런 조합은 4-상이 검사에서 배제되고, 같은 n의 다른 a(≥3)로 채운다.
    n≥1이라 네 값 {n+1, n, n+a, n+2}은 모두 양(0 값 위생 통과).
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for n in range(1, 31):
        for a in range(2, 8):
            correct_v = n + 1
            if correct_v in seen:
                continue  # 같은 n → 같은 정답값 → 구조 signature 충돌(회차 낭비 방지).
            correct = sympy.Integer(correct_v)
            misc = sympy.Integer(n)  # a^0=0 오인.
            filler1 = sympy.Integer(n + a)  # a^0=a 오인.
            filler2 = sympy.Integer(n + 2)  # 근접 오답(a^0=2 등).
            item = _assemble_item(
                values=(correct, misc, filler1, filler2),
                conditions=f"x = {n} + {a}**0",
                answer_str=str(correct_v),
                question_text=f"자연수 a = {a} 에 대하여 {n} + a^0 의 값을 구하시오.",
                answer_explanation=(
                    # 조사는 수 읽기 받침 판별 — '15 이 되어' 류 계통 결함 교정(S3-12).
                    f"a^0 = 1 이므로 {n} + a^0 = {n} + 1 = {correct_v} 이다. "
                    f"a^0 을 0 으로 잘못 계산하면 {n} {i_ga(str(n))} 되어 틀린다."
                ),
                difficulty=_difficulty(n + a),
                answer_format=AnswerFormat.자연수,
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_sqrt_pos_pool() -> tuple[_EvalItem, ...]:
    """√((-a)²) 값 뼈대 풀 — 정답 a(=|−a|)·오개념 -a(√(x²)=x 오인)·filler a²·2a.

    a≥3(a=2 스킵: 2a=a²=4 충돌). 네 값 {a, -a, a², 2a}은 a≥3에서 서로 다르다(a²≠2a·a≠2a·
    a≠a²·음수 -a는 양수들과 분리). 정답값 a로 dedup(각 a 유일). -a는 음수 선지(위생 0 값 아님).
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(3, 30):
        correct_v = a
        if correct_v in seen:
            continue
        correct = sympy.Integer(a)
        misc = sympy.Integer(-a)  # √(x²)=x 오인(절댓값 누락).
        filler1 = sympy.Integer(a * a)  # 제곱을 안 벗김.
        filler2 = sympy.Integer(2 * a)  # √를 ×2로 혼동.
        item = _assemble_item(
            values=(correct, misc, filler1, filler2),
            conditions=f"x = sqrt((-{a})**2)",
            answer_str=str(correct_v),
            question_text=f"√((-{a})^2) 의 값을 구하시오.",
            answer_explanation=(
                # 조사는 수 읽기 받침 판별 — '-28 가' 류 계통 결함 교정(S3-12·부호 무시).
                f"√(x²) = |x| 이므로 √((-{a})²) = |-{a}| = {a} 이다. "
                f"√(x²) = x 로 오인하면 -{a} {i_ga(str(-a))} 되어 틀린다."
            ),
            difficulty=_difficulty(a),
            answer_format=AnswerFormat.자연수,
        )
        if item is not None:
            seen.add(correct_v)
            pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_log_dist_pool() -> tuple[_EvalItem, ...]:
    """log₂(2^k + 2^k) 값 뼈대 풀 — 정답 k+1(2^k+2^k=2^{k+1})·오개념 2k(log 분배)·filler 2k+1·k.

    k≥2(k=1 스킵: k+1=2k=2 충돌). 네 값 {k+1, 2k, 2k+1, k}은 k≥2에서 서로 다르다(대수적 증명).
    정답값 k+1로 dedup(각 k 유일). k≥2라 모두 양(0 값 위생 통과).
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for k in range(2, 28):
        correct_v = k + 1
        if correct_v in seen:
            continue
        correct = sympy.Integer(correct_v)
        misc = sympy.Integer(2 * k)  # log₂(2^k)+log₂(2^k)=k+k 오인(로그 합 분배).
        filler1 = sympy.Integer(2 * k + 1)  # 근접 오답.
        filler2 = sympy.Integer(k)  # 지수만 취함.
        item = _assemble_item(
            values=(correct, misc, filler1, filler2),
            conditions=f"x = log(2**{k} + 2**{k}, 2)",
            answer_str=str(correct_v),
            question_text=f"log_2(2^{k} + 2^{k}) 의 값을 구하시오.",
            answer_explanation=(
                # 조사는 수 읽기 받침 판별 — '40 로' 류 계통 결함 교정(S3-12).
                f"2^{k} + 2^{k} = 2·2^{k} = 2^{k + 1} 이므로 값은 {correct_v} 이다. "
                f"로그를 합에 분배해 {k}+{k} = {2 * k} {euro_ro(str(2 * k))} 하면 틀린다."
            ),
            difficulty=_difficulty(k),
            answer_format=AnswerFormat.자연수,
        )
        if item is not None:
            seen.add(correct_v)
            pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_func_compose_pool() -> tuple[_EvalItem, ...]:
    """(f∘g)(c) 값 뼈대 풀 — f(x)=x+a, g(x)=bx. 정답 f(g(c))=bc+a·오개념 (g∘f)(c)=bc+ab.

    filler: bc(합성 +a 누락)·bc+a+b. b≥2·a≥1·c≥1. 유일 충돌 (a,b)=(2,2)에서 오개념 bc+ab가
    filler2 bc+a+b와 겹치나 4-상이 검사가 배제한다. 정답값 bc+a로 dedup. 모두 양(0 값 위생 통과).
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(1, 6):
        for b in range(2, 6):
            for c in range(1, 7):
                correct_v = b * c + a
                if correct_v in seen:
                    continue
                correct = sympy.Integer(correct_v)
                misc = sympy.Integer(b * c + a * b)  # (g∘f)(c)=g(c+a)=bc+ab(합성 순서 뒤집음).
                filler1 = sympy.Integer(b * c)  # +a 누락.
                filler2 = sympy.Integer(b * c + a + b)  # 계수 오합.
                item = _assemble_item(
                    values=(correct, misc, filler1, filler2),
                    conditions=f"x = {b}*{c} + {a}",
                    answer_str=str(correct_v),
                    question_text=(
                        f"두 함수 f(x) = x + {a}, g(x) = {b}x 에 대하여 "
                        f"(f∘g)({c}) 의 값을 구하시오."
                    ),
                    answer_explanation=(
                        # 조사는 수 읽기 받침 판별 — '26 로' 류 잠복 결함 교정(S3-12).
                        f"(f∘g)({c}) = f(g({c})) = f({b * c}) = {b * c} + {a} = {correct_v} 이다. "
                        f"순서를 뒤집어 (g∘f)({c}) = g({c}+{a}) = {b * c + a * b} "
                        f"{euro_ro(str(b * c + a * b))} 하면 틀린다."
                    ),
                    difficulty=_difficulty(a + b + c),
                    answer_format=AnswerFormat.자연수,
                )
                if item is not None:
                    seen.add(correct_v)
                    pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_sine_period_pool() -> tuple[_EvalItem, ...]:
    """y = sin(kx) 주기 뼈대 풀 — 정답 2π/k·오개념 2π(계수 무시 주기 불변)·filler π/k·2πk.

    k≥2. 네 값 {2π/k, 2π, π/k, 2πk}은 k≥2에서 서로 다르다(대수적 증명). 정답값(실수 근사)으로
    dedup(각 k 유일). 모두 양(0 값 위생 통과). 정답은 무리수(2π/k)라 answer_format=실수.
    """
    pi = sympy.pi
    pool: list[_EvalItem] = []
    seen: set[float] = set()
    for k in range(2, 28):
        correct = sympy.Integer(2) * pi / k
        key = round(_numeric(correct), 9)
        if key in seen:
            continue
        misc = sympy.Integer(2) * pi  # 계수 k 무시(주기 불변 오인).
        filler1 = pi / k  # 반주기 혼동.
        filler2 = sympy.Integer(2) * pi * k  # 계수 역적용.
        item = _assemble_item(
            values=(correct, misc, filler1, filler2),
            conditions=f"x = 2*pi/{k}",
            answer_str=_display(correct),
            question_text=f"함수 y = sin({k}x) 의 주기를 구하시오.",
            answer_explanation=(
                # 조사는 수 읽기 받침 판별 — '26 를' 류 계통 결함 교정(S3-12).
                f"y = sin(bx) 의 주기는 2π/b 이므로 y = sin({k}x) 의 주기는 2π/{k} 이다. "
                f"계수 {k} {eul_reul(str(k))} 무시하면 주기를 2π 로 잘못 구한다."
            ),
            difficulty=_difficulty(k),
            answer_format=_answer_format_for(correct),
        )
        if item is not None:
            seen.add(key)
            pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_translate_pool() -> tuple[_EvalItem, ...]:
    """g(x)=f(x-1)(우로 1 평행이동)의 g(c) 뼈대 풀 — f(x)=x²+bx. 정답 f(c-1)·오개념 f(c+1).

    평행이동 y=f(x-a)는 그래프를 *오른쪽*으로 a 이동(부호 반대). 오개념은 부호를 뒤집어
    f(x+a)로 봐 g(c)=f(c+1)로 계산한다. a=1 고정·b·d(=c-1)를 순회해 정답값 f(d)=d²+bd로 다수
    확보(정답값 dedup). filler: f(c)(이동 미적용)·d²(선형항 누락). 전부 양(0 값 위생).
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for b in range(1, 5):
        for d in range(1, 8):  # d = c - 1 ≥ 1.
            c = d + 1
            correct_v = d * d + b * d  # f(d) = f(c-1).
            if correct_v in seen:
                continue
            correct = sympy.Integer(correct_v)
            misc = sympy.Integer((d + 2) ** 2 + b * (d + 2))  # f(c+1)=f(d+2)(부호 뒤집음).
            filler1 = sympy.Integer(c * c + b * c)  # f(c)(이동 미적용).
            filler2 = sympy.Integer(d * d)  # 선형항 bx 누락.
            item = _assemble_item(
                values=(correct, misc, filler1, filler2),
                conditions=f"x = {d}**2 + {b}*{d}",
                answer_str=str(correct_v),
                question_text=(
                    f"함수 f(x) = x^2 + {b}x 에 대하여 g(x) = f(x - 1) 일 때, "
                    f"g({c}) 의 값을 구하시오."
                ),
                answer_explanation=(
                    f"y = f(x-1) 은 그래프를 오른쪽으로 1 평행이동한 것이므로 "
                    f"g({c}) = f({c}-1) = f({d}) = {correct_v} 이다. 부호를 뒤집어 f({c}+1) 로 "
                    f"계산하면 틀린다."
                ),
                difficulty=_difficulty(b + d),
                answer_format=AnswerFormat.자연수,
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_product_rule_pool() -> tuple[_EvalItem, ...]:
    """f(x)=x^m, g(x)=x^n 의 곱의 미분계수 (fg)'(c) 뼈대 풀 — 정답 (m+n)c^(m+n-1)·오개념 f'(c)g'(c).

    곱의 미분은 (fg)'=f'g+fg'인데, 오개념은 (fg)'=f'g'로 오인해 f'(c)g'(c)=mn·c^(m+n-2)로
    계산한다. fg=x^(m+n)이라 정답은 (m+n)c^(m+n-1). (m,n,c) 순회·정답값 dedup. filler:
    (m+n)c^(m+n)(지수 오차)·mn·c^(m+n-1)(계수 오차). 전부 양(0 값 위생).
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for m in range(1, 4):
        for n in range(1, 4):
            for c in range(2, 9):
                correct_v = (m + n) * c ** (m + n - 1)
                if correct_v in seen:
                    continue
                correct = sympy.Integer(correct_v)
                misc = sympy.Integer(m * n * c ** (m + n - 2))  # f'(c)g'(c)(곱미분 오인).
                filler1 = sympy.Integer((m + n) * c ** (m + n))  # 지수 미하강.
                filler2 = sympy.Integer(m * n * c ** (m + n - 1))  # 계수 오합.
                item = _assemble_item(
                    values=(correct, misc, filler1, filler2),
                    conditions=f"x = {m + n}*{c}**{m + n - 1}",
                    answer_str=str(correct_v),
                    question_text=(
                        f"두 함수 f(x) = x^{m}, g(x) = x^{n} 에 대하여 함수 f(x)g(x) 의 "
                        f"x = {c} 에서의 미분계수를 구하시오."
                    ),
                    answer_explanation=(
                        f"f(x)g(x) = x^{m + n} 이므로 미분계수는 {m + n}·{c}^{m + n - 1} "
                        f"= {correct_v} 이다. (fg)' = f'g' 로 오인하면 틀린 값이 된다."
                    ),
                    difficulty=_difficulty(m + n + c),
                    answer_format=AnswerFormat.자연수,
                )
                if item is not None:
                    seen.add(correct_v)
                    pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_fraction_cancel_pool() -> tuple[_EvalItem, ...]:
    """(a+b)/a 값 뼈대 풀 — 정답 (a+b)/a·오개념 b(분모 a만 약분해 b로 남김)·filler a·a+b.

    (a+b)/a = 1 + b/a 인데, 분자의 a와 분모의 a를 지워 b로 오인한다(잘못된 약분). 네 값
    {(a+b)/a, b, a, a+b}는 대체로 서로 다르며 4-상이 검사로 이중 보장한다. 정답값(실수 근사)으로
    dedup. 값이 정수면 자연수·아니면 분수 answer_format.
    """
    pool: list[_EvalItem] = []
    seen: set[float] = set()
    for a in range(2, 8):
        for b in range(2, 16):
            correct = sympy.Rational(a + b, a)
            key = round(_numeric(correct), 9)
            if key in seen:
                continue
            item = _assemble_item(
                values=(
                    correct,
                    sympy.Integer(b),  # 분모 a만 약분해 b로 오인(잘못된 약분).
                    sympy.Integer(a),  # 분모.
                    sympy.Integer(a + b),  # 분자.
                ),
                conditions=f"x = ({a}+{b})/{a}",
                answer_str=_display(correct),
                question_text=(
                    f"두 자연수 a = {a}, b = {b} 에 대하여 (a + b) / a 의 값을 구하시오."
                ),
                answer_explanation=(
                    # 조사는 수 읽기 받침 판별 — '13 를' 류 계통 결함 교정(S3-12).
                    f"(a + b) / a = 1 + b/a 이므로 a = {a}, b = {b} {eul_reul(str(b))} "
                    f"대입하면 {_display(correct)} 이다. 분자와 분모의 a 를 지워 b 로 "
                    "약분하면 틀린다."
                ),
                difficulty=_difficulty(a + b),
                answer_format=_answer_format_for(correct),
            )
            if item is not None:
                seen.add(key)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_polygon_angle_sum_pool() -> tuple[_EvalItem, ...]:
    """n각형 내각의 합 뼈대 풀 — 정답 (n-2)·180·오개념 180(삼각형 값 고정)·filler n·180·(n-1)·180.

    n각형 내각의 합은 (n-2)·180° 인데, 모든 다각형에서 180° 로 고정 오인한다. n≥4라 네 값
    {(n-2)·180, 180, n·180, (n-1)·180}는 서로 다르다. 정답값으로 dedup. 모두 자연수.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for n in range(4, 30):
        correct_v = (n - 2) * 180
        if correct_v in seen:
            continue
        item = _assemble_item(
            values=(
                sympy.Integer(correct_v),
                sympy.Integer(180),  # 다각형 무관 180° 고정 오인.
                sympy.Integer(n * 180),  # -2 누락.
                sympy.Integer((n - 1) * 180),  # 한 변 오차.
            ),
            conditions=f"x = ({n}-2)*180",
            answer_str=str(correct_v),
            question_text=f"{n}각형의 내각의 크기의 합을 구하시오. (단위: 도)",
            answer_explanation=(
                f"n각형의 내각의 합은 (n - 2)·180° 이므로 {n}각형은 "
                f"({n} - 2)·180 = {correct_v}° 이다. 모든 다각형의 내각의 합을 180° 로 여기면 "
                "틀린다."
            ),
            difficulty=_difficulty(n),
            answer_format=AnswerFormat.자연수,
        )
        if item is not None:
            seen.add(correct_v)
            pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_area_perimeter_pool() -> tuple[_EvalItem, ...]:
    """직사각형 넓이 뼈대 풀 — 정답 a·b·오개념 2(a+b)(넓이-둘레 혼동)·filler a+b·2ab.

    가로 a·세로 b 직사각형의 넓이는 a·b 인데, 둘레 2(a+b)와 혼동한다("둘레가 크면 넓이도 크다"류).
    네 값 {ab, 2(a+b), a+b, 2ab}는 4-상이 검사로 이중 보장한다. 정답값 ab로 dedup. 모두 자연수.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(2, 12):
        for b in range(a + 1, 16):
            correct_v = a * b
            if correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(correct_v),
                    sympy.Integer(2 * (a + b)),  # 둘레와 혼동.
                    sympy.Integer(a + b),  # 반둘레.
                    sympy.Integer(2 * a * b),  # 넓이 2배.
                ),
                conditions=f"x = {a}*{b}",
                answer_str=str(correct_v),
                question_text=(f"가로가 {a}, 세로가 {b} 인 직사각형의 넓이를 구하시오."),
                answer_explanation=(
                    # 조사는 수 읽기 받침 판별 — '30 와' 류 계통 결함 교정(S3-12).
                    f"직사각형의 넓이는 가로×세로 = {a}×{b} = {correct_v} 이다. "
                    f"둘레 2×({a}+{b}) = {2 * (a + b)} {wa_gwa(str(2 * (a + b)))} "
                    "혼동하면 틀린다."
                ),
                difficulty=_difficulty(a + b),
                answer_format=AnswerFormat.자연수,
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_circle_radius_pool() -> tuple[_EvalItem, ...]:
    """원 x²+y²=r² 반지름 뼈대 풀 — 정답 r·오개념 r²(r²을 반지름으로 오인)·filler 2r·r²+r.

    x² + y² = r² 의 반지름은 r 인데, 우변 r² 을 곧 반지름으로 오인한다(제곱을 안 벗김). r≥3라 네 값
    {r, r², 2r, r²+r}는 서로 다르다. 문항 우변은 r² 을 정수로 제시(완전제곱). 정답값 r로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for r in range(3, 30):
        r_sq = r * r
        if r in seen:
            continue
        item = _assemble_item(
            values=(
                sympy.Integer(r),
                sympy.Integer(r_sq),  # r² 을 반지름으로 오인.
                sympy.Integer(2 * r),  # 지름과 혼동.
                sympy.Integer(r_sq + r),  # 근접 오답.
            ),
            conditions=f"x = sqrt({r_sq})",
            answer_str=str(r),
            question_text=f"원 x^2 + y^2 = {r_sq} 의 반지름의 길이를 구하시오.",
            answer_explanation=(
                # 조사는 수 읽기 받침 판별 — '529 을' 류 계통 결함 교정(S3-12).
                f"x² + y² = r² 에서 반지름은 r 이므로 r² = {r_sq} 이면 반지름은 {r} 이다. "
                f"우변 {r_sq} {eul_reul(str(r_sq))} 반지름으로 여기면 틀린다."
            ),
            difficulty=_difficulty(r),
            answer_format=AnswerFormat.자연수,
        )
        if item is not None:
            seen.add(r)
            pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_gambler_streak_pool() -> tuple[_EvalItem, ...]:
    """독립시행 연속 후 다음 확률 뼈대 풀 — 정답 p(독립)·오개념 p²(연속이면 덜 나온다 오인).

    앞면 확률 p=a/b인 동전을 여러 번 던져 연속으로 앞면이 나와도, 각 시행은 독립이라 다음 앞면
    확률은 여전히 p다. "연속으로 나왔으니 이제 덜 나온다"는 도박사 오류(gambler-fallacy)는 작은 값
    (예 p²)으로 답한다. filler: 1-p(앞뒤 혼동)·p/2. a<b·기약이라 네 값이 서로 다르다(값 dedup).
    """
    pool: list[_EvalItem] = []
    seen: set[float] = set()
    for b in range(3, 12):
        for a in range(1, b):
            if gcd(a, b) != 1:
                continue
            correct = sympy.Rational(a, b)
            key = round(_numeric(correct), 9)
            if key in seen:
                continue
            item = _assemble_item(
                values=(
                    correct,
                    correct * correct,  # p²(연속이면 덜 나온다 오인·gambler).
                    sympy.Integer(1) - correct,  # 1-p(앞뒤 혼동).
                    correct / 2,  # p/2(근접 오답).
                ),
                conditions=f"x = {a}/{b}",
                answer_str=_display(correct),
                question_text=(
                    f"앞면이 나올 확률이 {correct} 인 동전을 던져 앞면이 3번 연속 나왔다. "
                    "다음 시행에서 앞면이 나올 확률을 구하시오."
                ),
                answer_explanation=(
                    f"각 시행은 독립이라 이전 결과와 무관하게 다음 앞면 확률은 {correct} 그대로다. "
                    "연속으로 나왔으니 이제 덜 나온다고 여기는 도박사 오류에 빠지면 틀린다."
                ),
                difficulty=_difficulty(a + b),
                answer_format=_answer_format_for(correct),
            )
            if item is not None:
                seen.add(key)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_fraction_addition_pool() -> tuple[_EvalItem, ...]:
    """1/p + 1/q 값 뼈대 풀 — 정답 (p+q)/(pq)·오개념 2/(p+q)(분자·분모 각각 더함·통분 누락).

    1/p + 1/q = (p+q)/(pq) 인데, 통분 없이 분자끼리(1+1)·분모끼리(p+q) 더해 2/(p+q)로 오인한다.
    filler: 1/p·1/q. (p,q) 기약쌍(p<q)만 순회해 값 유일. 정답값으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[float] = set()
    for p in range(2, 9):
        for q in range(p + 1, 12):
            if gcd(p, q) != 1:
                continue
            correct = sympy.Rational(p + q, p * q)
            key = round(_numeric(correct), 9)
            if key in seen:
                continue
            item = _assemble_item(
                values=(
                    correct,
                    sympy.Rational(2, p + q),  # (1+1)/(p+q)·통분 누락.
                    sympy.Rational(1, p),
                    sympy.Rational(1, q),
                ),
                conditions=f"x = ({p}+{q})/({p}*{q})",
                answer_str=_display(correct),
                question_text=(f"1/{p} + 1/{q} 의 값을 구하시오."),
                answer_explanation=(
                    # 조사는 분수 읽기(분모분의 분자) 받침 판별 — '1/5 는' 류 계통 결함 교정(S3-12).
                    f"1/{p} + 1/{q} {eun_neun(f'1/{q}')} 통분하면 "
                    f"({p}+{q})/({p}·{q}) = {_display(correct)} 이다. "
                    "통분 없이 분자·분모를 각각 더해 2/(p+q)로 답하면 틀린다."
                ),
                difficulty=_difficulty(p + q),
                answer_format=_answer_format_for(correct),
            )
            if item is not None:
                seen.add(key)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_negative_product_pool() -> tuple[_EvalItem, ...]:
    """(-a)(-b) 값 뼈대 풀 — 정답 ab(음×음=양)·오개념 -ab(음×음=음 오인)·filler a+b·-(a+b).

    (-a)×(-b) = ab 인데, 부호 규칙을 놓쳐 -ab로 오인한다. a<b(a,b≥2)라 네 값 {ab, -ab, a+b,
    -(a+b)}는 서로 다르다. 정답값으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(2, 9):
        for b in range(a + 1, 14):
            correct_v = a * b
            if correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(a * b),
                    sympy.Integer(-a * b),  # 음×음=음 오인.
                    sympy.Integer(a + b),
                    sympy.Integer(-(a + b)),
                ),
                conditions=f"x = ({a})*({b})",
                answer_str=str(correct_v),
                question_text=(f"(-{a}) × (-{b}) 의 값을 구하시오."),
                answer_explanation=(
                    f"음수끼리의 곱은 양수이므로 (-{a})×(-{b}) = {correct_v} 이다. "
                    "음수끼리 곱해도 음수라고 여기면 부호를 틀린다."
                ),
                difficulty=_difficulty(a + b),
                answer_format=_answer_format_for(sympy.Integer(correct_v)),
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_subtract_negative_pool() -> tuple[_EvalItem, ...]:
    """a - (-b) 값 뼈대 풀 — 정답 a+b(부호 반전)·오개념 a-b(반전 누락)·filler b-a·-(a+b).

    a - (-b) = a + b 인데, 음수를 빼는 부호 반전을 놓쳐 a - b로 오인한다. a≠b(a,b≥2)라 네 값
    {a+b, a-b, b-a, -(a+b)}는 서로 다르다(a-b≠0). 정답값으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(2, 13):
        for b in range(2, 22):
            if a == b:
                continue
            correct_v = a + b
            if correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(a + b),
                    sympy.Integer(a - b),  # 부호 반전 누락.
                    sympy.Integer(b - a),
                    sympy.Integer(-(a + b)),
                ),
                conditions=f"x = {a}+{b}",
                answer_str=str(correct_v),
                question_text=(f"{a} - (-{b}) 의 값을 구하시오."),
                answer_explanation=(
                    f"음수를 빼면 그만큼 더해지므로 {a} - (-{b}) = {a} + {b} = {correct_v} 이다. "
                    "부호 반전을 놓쳐 a - b로 계산하면 틀린다."
                ),
                difficulty=_difficulty(a + b),
                answer_format=_answer_format_for(sympy.Integer(correct_v)),
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_absolute_value_pool() -> tuple[_EvalItem, ...]:
    """|-a| + b 값 뼈대 풀 — 정답 a+b(|-a|=a)·오개념 -a+b(부호 유지 오인)·filler a-b·-(a+b).

    |-a| + b = a + b 인데, 절댓값이 음수 부호를 유지한다고 여겨 -a + b로 오인한다. a≠b(a,b≥2)라
    네 값 {a+b, -a+b, a-b, -(a+b)}는 서로 다르다. 정답값으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(2, 13):
        for b in range(2, 22):
            if a == b:
                continue
            correct_v = a + b
            if correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(a + b),
                    sympy.Integer(-a + b),  # |-a|=-a 부호 유지 오인.
                    sympy.Integer(a - b),
                    sympy.Integer(-(a + b)),
                ),
                conditions=f"x = {a}+{b}",
                answer_str=str(correct_v),
                question_text=(f"|-{a}| + {b} 의 값을 구하시오."),
                answer_explanation=(
                    f"절댓값은 음이 아니므로 |-{a}| = {a} 이고 |-{a}| + {b} = {correct_v} 이다. "
                    "절댓값이 음수 부호를 유지한다고 여기면 틀린다."
                ),
                difficulty=_difficulty(a + b),
                answer_format=_answer_format_for(sympy.Integer(correct_v)),
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_sqrt_sum_pool() -> tuple[_EvalItem, ...]:
    """√(m²+n²) 값 뼈대 풀 — 정답 k(피타고라스 m²+n²=k²)·오개념 m+n(√ 합 분배)·filler n-m·n.

    √(m²+n²) = k 인데, 제곱근이 합에 분배된다고 여겨 √(m²)+√(n²)=m+n으로 오인한다. 피타고라스
    쌍(m<n·m²+n²=k²)만 써서 정답이 정수·오개념(m+n)과 다르다. 네 값 {k, m+n, n-m, n}은 서로 다르다.
    정답값(k)으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for m in range(3, 85):
        for n in range(m + 1, 85):
            s = m * m + n * n
            k = isqrt(s)
            if k * k != s:
                continue  # 피타고라스 쌍만(정답 정수).
            if k in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(k),
                    sympy.Integer(m + n),  # √(m²)+√(n²)=m+n·합 분배 오인.
                    sympy.Integer(n - m),
                    sympy.Integer(n),
                ),
                conditions=f"x = {k}",
                answer_str=str(k),
                question_text=(f"√({m * m} + {n * n}) 의 값을 구하시오."),
                answer_explanation=(
                    # 조사는 수 읽기 받침 판별 — '10000 는'·'84 이' 류 계통 결함 교정(S3-12).
                    f"근호 안의 합 {s} {eun_neun(str(s))} {k} 의 제곱이므로 "
                    f"그 제곱근은 {k} 이다. "
                    f"제곱근을 각 항에 분배하면 {m} + {n} {i_ga(str(n))} 되어 틀린다."
                ),
                difficulty=_difficulty(m + n),
                answer_format=_answer_format_for(sympy.Integer(k)),
            )
            if item is not None:
                seen.add(k)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_difference_of_squares_pool() -> tuple[_EvalItem, ...]:
    """x²-a² 값 뼈대 풀 — 정답 x²-a²·오개념 (x-a)²(제곱의 차를 차의 제곱으로)·filler (x+a)²·x²+a².

    x² - a² = (x-a)(x+a) 인데, 차의 제곱 (x-a)²로 오인한다(합차공식 혼동). x>a≥1이라 네 값
    {x²-a², (x-a)², (x+a)², x²+a²}는 서로 다르다. 정답값으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(1, 8):
        for x in range(a + 1, a + 14):
            correct_v = x * x - a * a
            if correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(x * x - a * a),
                    sympy.Integer((x - a) ** 2),  # 차의 제곱으로 오인.
                    sympy.Integer((x + a) ** 2),
                    sympy.Integer(x * x + a * a),
                ),
                conditions=f"x = {correct_v}",
                answer_str=str(correct_v),
                question_text=(f"x = {x}, a = {a} 일 때 x² - a² 의 값을 구하시오."),
                answer_explanation=(
                    # 조사는 수·수식 꼬리 읽기 판별 — '1 를'·'(x-a)²로' 류 결함 교정(S3-12).
                    f"x² - a² = (x-a)(x+a) 이므로 x={x}, a={a} {eul_reul(str(a))} "
                    f"대입하면 {correct_v} 이다. "
                    f"제곱의 차를 차의 제곱 (x-a)²{euro_ro('(x-a)²')} 여기면 틀린다."
                ),
                difficulty=_difficulty(x + a),
                answer_format=_answer_format_for(sympy.Integer(correct_v)),
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_exponent_product_pool() -> tuple[_EvalItem, ...]:
    """a × a² 값 뼈대 풀 — 정답 a³(지수 1+2)·오개념 a²(지수를 곱함 1·2)·filler a·a⁴.

    밑이 같은 거듭제곱의 곱은 지수를 더한다: a¹ × a² = a^(1+2) = a³. 지수를 곱하면 a^(1·2) = a²로
    틀린다. 밑 a를 순회(a≥2)해 정답 a³이 유일하다. 네 값 {a³, a², a, a⁴}은 a≥2에서 서로 다르다.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(2, 26):
        correct_v = a**3
        if correct_v in seen:
            continue
        item = _assemble_item(
            values=(
                sympy.Integer(a**3),
                sympy.Integer(a**2),  # 지수를 곱함(1·2=2).
                sympy.Integer(a),
                sympy.Integer(a**4),
            ),
            conditions=f"x = {a}**3",
            answer_str=str(correct_v),
            question_text=f"{a} × {a}² 의 값을 구하시오.",
            answer_explanation=(
                # 조사는 수식 꼬리(제곱) 읽기 받침 판별 — '18² 로' 류 계통 결함 교정(S3-12).
                f"밑이 같은 거듭제곱의 곱은 지수를 더하므로 {a} × {a}² = {a}^(1+2) = {a}³ "
                f"= {correct_v} 이다. 지수를 곱해 {a}² {euro_ro(f'{a}²')} 답하면 틀린다."
            ),
            difficulty=_difficulty(a),
            answer_format=_answer_format_for(sympy.Integer(correct_v)),
        )
        if item is not None:
            seen.add(correct_v)
            pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_power_of_power_pool() -> tuple[_EvalItem, ...]:
    """(aᵐ)ⁿ 값 뼈대 풀 — 정답 a^(mn)·오개념 a^(m+n)(지수를 더함)·filler a^m·a^n.

    거듭제곱의 거듭제곱은 지수를 곱한다: (aᵐ)ⁿ = a^(mn). 지수를 더하면 a^(m+n)로 틀린다. 밑 a와
    지수쌍(m<n)을 순회·정답값 상한 안만 담아 dedup. mn>m+n(m,n≥2)이라 오개념과 다름.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(2, 11):
        for m in range(2, 4):
            for n in range(m + 1, 9):
                correct_v = a ** (m * n)
                if correct_v > 10**8 or correct_v in seen:
                    continue
                item = _assemble_item(
                    values=(
                        sympy.Integer(a ** (m * n)),
                        sympy.Integer(a ** (m + n)),  # 지수를 더함.
                        sympy.Integer(a**m),
                        sympy.Integer(a**n),
                    ),
                    conditions=f"x = {a}**{m * n}",
                    answer_str=str(correct_v),
                    question_text=f"({a}^{m})^{n} 의 값을 구하시오.",
                    answer_explanation=(
                        # 조사는 수식 꼬리(제곱) 읽기 판별 — '10^5 로' 류 결함 교정(S3-12).
                        f"거듭제곱의 거듭제곱은 지수를 곱하므로 ({a}^{m})^{n} = {a}^{m * n} "
                        f"= {correct_v} 이다. 지수를 더해 {a}^{m + n} "
                        f"{euro_ro(f'{a}^{m + n}')} 답하면 틀린다."
                    ),
                    difficulty=_difficulty(a + m + n),
                    answer_format=_answer_format_for(sympy.Integer(correct_v)),
                )
                if item is not None:
                    seen.add(correct_v)
                    pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_negative_square_pool() -> tuple[_EvalItem, ...]:
    """-a² + b 값 뼈대 풀 — 정답 b-a²·오개념 b+a²(-a²을 (-a)²로 오인)·filler -(a²+b)·a²-b.

    거듭제곱이 음의 부호보다 우선하므로 -a² = -(a²)이다. -a²을 (-a)²=a²로 계산하면 부호가 뒤집힌다.
    a²≠b·b≥1이라 네 값 {b-a², b+a², -(a²+b), a²-b}은 서로 다르다. 정답값으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(2, 10):
        for b in range(1, 14):
            if a * a == b:
                continue  # 정답 0 회피(위생).
            correct_v = b - a * a
            if correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(b - a * a),
                    sympy.Integer(b + a * a),  # -a²을 (-a)²=a²로 오인.
                    sympy.Integer(-(a * a + b)),
                    sympy.Integer(a * a - b),
                ),
                conditions=f"x = {b} - {a * a}",
                answer_str=str(correct_v),
                question_text=f"-{a}² + {b} 의 값을 구하시오.",
                answer_explanation=(
                    # 조사는 수 읽기 받침 판별 — '16로' 류 계통 결함 교정(S3-12).
                    f"거듭제곱이 부호보다 우선하므로 -{a}² = -{a * a} 이고 -{a}² + {b} = "
                    f"{correct_v} 이다. -{a}²을 (-{a})²={a * a}{euro_ro(str(a * a))} "
                    "계산하면 틀린다."
                ),
                difficulty=_difficulty(a + b),
                answer_format=_answer_format_for(sympy.Integer(correct_v)),
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_distribute_partial_pool() -> tuple[_EvalItem, ...]:
    """a(x+b)를 x=c에서 값 뼈대 풀 — 정답 a(c+b)·오개념 ac+b(뒷항 분배 누락)·filler ac·ab.

    분배법칙은 a(x+b)=ax+ab이므로 x=c에서 a(c+b)이다. 뒷항을 분배하지 않으면 ac+b로 틀린다.
    a,b,c≥2·조합이 네 값 {a(c+b), ac+b, ac, ab}을 서로 다르게 만든다. 정답값으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(2, 7):
        for b in range(2, 8):
            for c in range(2, 9):
                correct_v = a * (c + b)
                if correct_v in seen:
                    continue
                item = _assemble_item(
                    values=(
                        sympy.Integer(a * (c + b)),
                        sympy.Integer(a * c + b),  # 뒷항 분배 누락.
                        sympy.Integer(a * c),
                        sympy.Integer(a * b),
                    ),
                    conditions=f"x = {a} * ({c} + {b})",
                    answer_str=str(correct_v),
                    question_text=f"{a}(x + {b}) 에서 x = {c} 일 때의 값을 구하시오.",
                    answer_explanation=(
                        # 조사는 수 읽기 받침 판별 — 'x = 8 를' 류 계통 결함 교정(S3-12).
                        f"분배법칙으로 {a}(x + {b}) = {a}x + {a * b} 이므로 "
                        f"x = {c} {eul_reul(str(c))} 대입하면 {correct_v} 이다. "
                        f"뒷항을 분배하지 않고 {a * c} + {b}{euro_ro(str(b))} 계산하면 틀린다."
                    ),
                    difficulty=_difficulty(a + b + c),
                    answer_format=_answer_format_for(sympy.Integer(correct_v)),
                )
                if item is not None:
                    seen.add(correct_v)
                    pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_negative_distribute_pool() -> tuple[_EvalItem, ...]:
    """-(x-b)를 x=c에서 값 뼈대 풀 — 정답 b-c·오개념 -c-b(뒷항 부호 미반전)·filler c-b·c+b.

    음의 부호 분배는 -(x-b)=-x+b이므로 x=c에서 b-c이다. 뒷항 부호를 반전하지 않으면 -c-b로 틀린다.
    b≠c(b,c≥2)라 네 값 {b-c, -c-b, c-b, c+b}은 서로 다르다. 정답값으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for c in range(2, 15):
        for b in range(2, 22):
            if b == c:
                continue
            correct_v = b - c
            if correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(b - c),
                    sympy.Integer(-c - b),  # 뒷항 부호 미반전.
                    sympy.Integer(c - b),
                    sympy.Integer(c + b),
                ),
                conditions=f"x = {b} - {c}",
                answer_str=str(correct_v),
                question_text=f"-(x - {b}) 에서 x = {c} 일 때의 값을 구하시오.",
                answer_explanation=(
                    # 조사는 수 읽기 받침 판별 — '13 를' 류 계통 결함 교정(S3-12).
                    f"음의 부호 분배는 -(x - {b}) = -x + {b} 이므로 "
                    f"x = {c} {eul_reul(str(c))} 대입하면 {correct_v} 이다. "
                    f"뒷항 부호를 반전하지 않고 -{c} - {b}{euro_ro(str(b))} 계산하면 틀린다."
                ),
                difficulty=_difficulty(b + c),
                answer_format=_answer_format_for(sympy.Integer(correct_v)),
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_square_difference_pool() -> tuple[_EvalItem, ...]:
    """(a-b)² 값 뼈대 풀 — 정답 (a-b)²·오개념 a²-b²(교차항 누락)·filler (a+b)²·a²+b².

    차의 제곱은 (a-b)²=a²-2ab+b²이다. 교차항 -2ab를 누락해 a²-b²로 계산하면 틀린다. a>b≥2라 네 값
    {(a-b)², a²-b², (a+b)², a²+b²}은 서로 다르다. 정답값으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(3, 28):
        for b in range(2, a):
            correct_v = (a - b) ** 2
            if correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer((a - b) ** 2),
                    sympy.Integer(a * a - b * b),  # 교차항 -2ab 누락.
                    sympy.Integer((a + b) ** 2),
                    sympy.Integer(a * a + b * b),
                ),
                conditions=f"x = ({a} - {b})**2",
                answer_str=str(correct_v),
                question_text=f"({a} - {b})² 의 값을 구하시오.",
                answer_explanation=(
                    # 조사는 수식 꼬리(제곱) 읽기 받침 판별 — '2²로' 류 계통 결함 교정(S3-12).
                    f"차의 제곱은 ({a} - {b})² = {a}² - 2·{a}·{b} + {b}² = {correct_v} 이다. "
                    f"교차항을 누락해 {a}² - {b}²{euro_ro(f'{b}²')} 계산하면 틀린다."
                ),
                difficulty=_difficulty(a + b),
                answer_format=_answer_format_for(sympy.Integer(correct_v)),
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_midpoint_no_half_pool() -> tuple[_EvalItem, ...]:
    """두 점 a, b의 중점 값 뼈대 풀 — 정답 (a+b)/2·오개념 a+b(2로 안 나눔)·filler a·b.

    수직선 위 두 점 a, b의 중점은 (a+b)/2이다. 2로 나누기를 누락하면 a+b로 틀린다. a<b라 네 값
    {(a+b)/2, a+b, a, b}은 서로 다르다. 정답값으로 dedup. 값이 정수면 자연수·아니면 분수.
    """
    pool: list[_EvalItem] = []
    seen: set[float] = set()
    for a in range(1, 12):
        for b in range(a + 1, 20):
            correct = sympy.Rational(a + b, 2)
            key = round(_numeric(correct), 9)
            if key in seen:
                continue
            item = _assemble_item(
                values=(
                    correct,
                    sympy.Integer(a + b),  # 2로 나누기 누락.
                    sympy.Integer(a),
                    sympy.Integer(b),
                ),
                conditions=f"x = ({a}+{b})/2",
                answer_str=_display(correct),
                question_text=f"수직선 위 두 점 {a}, {b} 의 중점의 좌표를 구하시오.",
                answer_explanation=(
                    # 조사는 수 읽기 받침 판별 — '20로' 류 계통 결함 교정(S3-12).
                    f"두 점의 중점은 좌표의 평균이므로 ({a}+{b})/2 = {_display(correct)} 이다. "
                    f"2로 나누지 않고 {a + b}{euro_ro(str(a + b))} 답하면 틀린다."
                ),
                difficulty=_difficulty(a + b),
                answer_format=_answer_format_for(correct),
            )
            if item is not None:
                seen.add(key)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_scale_area_pool() -> tuple[_EvalItem, ...]:
    """닮음비 k의 넓이비 뼈대 풀 — 정답 k²·오개념 k(선형 오인)·filler 2k·k³.

    닮음비가 k이면 넓이의 비는 k²이다(길이의 제곱에 비례). 선형으로 여겨 k로 답하면 틀린다. k≥3라
    네 값 {k², k, 2k, k³}은 서로 다르다(k=2는 k²=2k 충돌로 제외). 정답값 k²으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for k in range(3, 27):
        correct_v = k * k
        if correct_v in seen:
            continue
        item = _assemble_item(
            values=(
                sympy.Integer(k * k),
                sympy.Integer(k),  # 선형 오인.
                sympy.Integer(2 * k),
                sympy.Integer(k**3),
            ),
            conditions=f"x = {k}**2",
            answer_str=str(correct_v),
            question_text=f"닮음비가 {k} 인 두 도형의 넓이의 비를 구하시오.",
            answer_explanation=(
                # 조사는 수 읽기 받침 판별 — '17 를' 류 계통 결함 교정(S3-12).
                f"넓이는 길이의 제곱에 비례하므로 닮음비 {k} 의 넓이의 비는 {k}² = {correct_v} "
                f"이다. 닮음비 {k} {eul_reul(str(k))} 그대로 넓이의 비로 답하면 틀린다."
            ),
            difficulty=_difficulty(k),
            answer_format=_answer_format_for(sympy.Integer(correct_v)),
        )
        if item is not None:
            seen.add(correct_v)
            pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_negative_even_power_pool() -> tuple[_EvalItem, ...]:
    """(-a)^짝수 값 뼈대 풀 — 정답 a^n(양수)·오개념 -a^n(음수로 오인)·filler a·-a.

    음수의 짝수 거듭제곱은 양수다: (-a)^n = a^n(n 짝수). 음수로 여겨 -a^n으로 답하면 틀린다. 밑 a와
    짝수 지수 n을 순회하며 정답값 ≤ 10^5만 담아 dedup(값 폭주 방지). 네 값 {a^n, -a^n, a, -a} 상이.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for n in (2, 4, 6):
        for a in range(2, 22):
            correct_v = a**n
            if correct_v > 10**5 or correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(a**n),
                    sympy.Integer(-(a**n)),  # 음수로 오인.
                    sympy.Integer(a),
                    sympy.Integer(-a),
                ),
                conditions=f"x = {a}**{n}",
                answer_str=str(correct_v),
                question_text=f"(-{a})^{n} 의 값을 구하시오.",
                answer_explanation=(
                    # 조사는 수 읽기 받침 판별 — '-46656로' 류 계통 결함 교정(S3-12).
                    f"음수의 짝수 거듭제곱은 양수이므로 (-{a})^{n} = {a}^{n} = {correct_v} 이다. "
                    f"음수로 여겨 -{correct_v}{euro_ro(str(-correct_v))} 답하면 틀린다."
                ),
                difficulty=_difficulty(a + n),
                answer_format=_answer_format_for(sympy.Integer(correct_v)),
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_combine_unlike_pool() -> tuple[_EvalItem, ...]:
    """ax+bx²를 x=c에서 값 뼈대 풀 — 정답 ac+bc²·오개념 (a+b)c³(차수 무시 결합)·filler ac·bc².

    차수가 다른 항은 동류항이 아니라 결합할 수 없다: ax+bx²는 x=c에서 ac+bc²이다. 차수를 무시하고
    (a+b)x³으로 결합하면 (a+b)c³로 틀린다. 조합이 네 값 {ac+bc², (a+b)c³, ac, bc²}을 상이하게 한다.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(2, 7):
        for b in range(2, 8):
            for c in range(2, 9):
                correct_v = a * c + b * c * c
                if correct_v in seen:
                    continue
                item = _assemble_item(
                    values=(
                        sympy.Integer(a * c + b * c * c),
                        sympy.Integer((a + b) * c**3),  # 차수 무시 결합.
                        sympy.Integer(a * c),
                        sympy.Integer(b * c * c),
                    ),
                    conditions=f"x = {a}*{c} + {b}*{c}**2",
                    answer_str=str(correct_v),
                    question_text=f"{a}x + {b}x² 에서 x = {c} 일 때의 값을 구하시오.",
                    answer_explanation=(
                        # 조사는 수식 꼬리(제곱) 읽기 받침 판별 — 'x² 는' 류 계통 결함 교정(S3-12).
                        f"차수가 다른 항은 따로 계산하므로 {a}x + {b}x² {eun_neun(f'{b}x²')} "
                        f"x = {c} 에서 {a * c} + {b * c * c} = {correct_v} 이다. "
                        f"차수를 무시하고 {a + b}x³으로 결합하면 틀린다."
                    ),
                    difficulty=_difficulty(a + b + c),
                    answer_format=_answer_format_for(sympy.Integer(correct_v)),
                )
                if item is not None:
                    seen.add(correct_v)
                    pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_complete_square_pool() -> tuple[_EvalItem, ...]:
    """x²+bx를 x=c에서 값 뼈대 풀 — 정답 c²+bc·오개념 (c+b)²(완전제곱 오인)·filler c²·bc.

    x²+bx는 (x+b)²이 아니다(일차항 계수를 반으로 나눠야 함). x=c에서 c²+bc이다. (x+b)²으로 오인하면
    (c+b)²로 틀린다. b,c 조합이 네 값 {c²+bc, (c+b)², c², bc}을 상이하게 한다. 정답값으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for b in range(2, 12):
        for c in range(2, 12):
            correct_v = c * c + b * c
            if correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(c * c + b * c),
                    sympy.Integer((c + b) ** 2),  # 완전제곱 오인.
                    sympy.Integer(c * c),
                    sympy.Integer(b * c),
                ),
                conditions=f"x = {c}**2 + {b}*{c}",
                answer_str=str(correct_v),
                question_text=f"x² + {b}x 에서 x = {c} 일 때의 값을 구하시오.",
                answer_explanation=(
                    # S3-12 교정: 해설의 미치환 템플릿 변수 '(c+N)²' 노출을 실수치로 치환하고
                    # ('(c+11)²' 계통 결함), 조사는 수 읽기 받침 판별로 고른다('²로' 계통 결함).
                    f"x² + {b}x 는 x = {c} 에서 {c * c} + {b * c} = {correct_v} 이다. "
                    f"이를 (x+{b})²으로 오인하면 ({c}+{b})² = {(c + b) ** 2} "
                    f"{i_ga(str((c + b) ** 2))} 되어 틀린다."
                ),
                difficulty=_difficulty(b + c),
                answer_format=_answer_format_for(sympy.Integer(correct_v)),
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_conjugate_product_pool() -> tuple[_EvalItem, ...]:
    """(√a+1)(√a-1) 값 뼈대 풀 — 정답 a-1·오개념 a+1(부호 오용)·filler a·2a.

    켤레 무리수의 곱은 합차공식으로 (√a)²-1² = a-1이다. 부호를 오용해 a+1로 답하면 틀린다.
    a≥3라 네 값 {a-1, a+1, a, 2a}은 서로 다르다. 정답값 a-1으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(3, 28):
        correct_v = a - 1
        if correct_v in seen:
            continue
        item = _assemble_item(
            values=(
                sympy.Integer(a - 1),
                sympy.Integer(a + 1),  # 부호 오용.
                sympy.Integer(a),
                sympy.Integer(2 * a),
            ),
            conditions=f"x = {a} - 1",
            answer_str=str(correct_v),
            question_text=f"(√{a} + 1)(√{a} - 1) 의 값을 구하시오.",
            answer_explanation=(
                f"켤레 무리수의 곱은 (√{a})² - 1² = {a} - 1 = {correct_v} 이다. "
                f"합차공식 부호를 오용해 {a} + 1로 답하면 틀린다."
            ),
            difficulty=_difficulty(a),
            answer_format=_answer_format_for(sympy.Integer(correct_v)),
        )
        if item is not None:
            seen.add(correct_v)
            pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_transpose_pool() -> tuple[_EvalItem, ...]:
    """x+b=c 의 해 뼈대 풀 — 정답 c-b(이항 시 부호 반전)·오개념 c+b(부호 미변경)·filler b·c.

    x+b=c에서 b를 이항하면 x=c-b이다. 이항할 때 부호를 바꾸지 않으면 c+b로 틀린다. b≠c라 네 값
    {c-b, c+b, b, c}은 서로 다르다(c-b 비영). 정답값 c-b로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for b in range(2, 14):
        for c in range(2, 22):
            if b == c:
                continue
            correct_v = c - b
            if correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(c - b),
                    sympy.Integer(c + b),  # 이항 부호 미변경.
                    sympy.Integer(b),
                    sympy.Integer(c),
                ),
                conditions=f"x = {c} - {b}",
                answer_str=str(correct_v),
                question_text=f"일차방정식 x + {b} = {c} 의 해를 구하시오.",
                answer_explanation=(
                    # 조사는 수 읽기 받침 판별 — '10를'·'10로' 류 계통 결함 교정(S3-12).
                    f"{b}{eul_reul(str(b))} 이항하면 부호가 바뀌어 "
                    f"x = {c} - {b} = {correct_v} 이다. "
                    f"이항할 때 부호를 바꾸지 않으면 {c} + {b}{euro_ro(str(b))} 틀린다."
                ),
                difficulty=_difficulty(b + c),
                answer_format=_answer_format_for(sympy.Integer(correct_v)),
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_gcd_lcm_pool() -> tuple[_EvalItem, ...]:
    """두 수의 최소공배수 뼈대 풀 — 정답 lcm(a,b)·오개념 gcd(a,b)(혼동)·filler a·b.

    최소공배수와 최대공약수는 다르다. 최소공배수를 물으면 정답은 lcm(a,b), 최대공약수와 혼동하면
    gcd(a,b)로 틀린다. a<b·lcm≠a≠b라 네 값 {lcm, gcd, a, b}은 서로 다르다. 정답값 lcm으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(2, 13):
        for b in range(a + 1, 21):
            g = gcd(a, b)
            lcm = a * b // g
            if lcm in (a, b) or lcm in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(lcm),
                    sympy.Integer(g),  # 최대공약수와 혼동.
                    sympy.Integer(a),
                    sympy.Integer(b),
                ),
                conditions=f"x = {lcm}",
                answer_str=str(lcm),
                # 조사는 수 읽기 받침 판별 — '10 와' 류 계통 결함 교정(S3-12).
                question_text=f"{a} {wa_gwa(str(a))} {b} 의 최소공배수를 구하시오.",
                answer_explanation=(
                    f"{a}{wa_gwa(str(a))} {b}의 최소공배수는 {lcm} 이다(최대공약수는 {g}). "
                    "최소공배수와 최대공약수를 혼동하면 틀린다."
                ),
                difficulty=_difficulty(a + b),
                answer_format=_answer_format_for(sympy.Integer(lcm)),
            )
            if item is not None:
                seen.add(lcm)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_decimal_mult_pool() -> tuple[_EvalItem, ...]:
    """0.a × 0.b 값 뼈대 풀 — 정답 ab/100·오개념 ab/10(자릿수 무시)·filler a/10·b/10.

    0.a × 0.b = (ab)/100이다. 소수점 자릿수를 무시하면 (ab)/10로 틀린다. a<b·기약 곱이 네 값
    {ab/100, ab/10, a/10, b/10}을 서로 다르게 한다. 정답값 ab/100으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[float] = set()
    for a in range(1, 10):
        for b in range(a + 1, 10):
            correct = sympy.Rational(a * b, 100)
            key = round(_numeric(correct), 9)
            if key in seen:
                continue
            item = _assemble_item(
                values=(
                    correct,
                    sympy.Rational(a * b, 10),  # 자릿수 무시.
                    sympy.Rational(a, 10),
                    sympy.Rational(b, 10),
                ),
                conditions=f"x = {a}*{b}/100",
                answer_str=_display(correct),
                question_text=f"0.{a} × 0.{b} 의 값을 구하시오.",
                answer_explanation=(
                    # 조사는 소수·분수 읽기 받침 판별 — '0.8 는'·'40/10로' 류 계통 결함 교정(S3-12).
                    f"0.{a} × 0.{b} {eun_neun(f'0.{b}')} 소수점 아래 자릿수를 더해 "
                    f"{a * b}/100 = {_display(correct)} 이다. "
                    f"자릿수를 무시하면 {a * b}/10{euro_ro(f'{a * b}/10')} 틀린다."
                ),
                difficulty=_difficulty(a + b),
                answer_format=AnswerFormat.실수,
            )
            if item is not None:
                seen.add(key)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_mixed_mult_pool() -> tuple[_EvalItem, ...]:
    """(a + 1/2) × n 값 뼈대 풀 — 정답 n(2a+1)/2·오개념 an+1/2(정수부만 곱)·filler an·(2a+1)/2.

    대분수 (a + 1/2)에 n을 곱하면 정수부와 분수부 모두에 곱해 n(2a+1)/2이다. 정수부만 곱하면
    an + 1/2로 틀린다. a≥1·n≥2·조합이 네 값을 서로 다르게 한다. 정답값으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[float] = set()
    for a in range(1, 9):
        for n in range(2, 10):
            correct = sympy.Rational((2 * a + 1) * n, 2)
            key = round(_numeric(correct), 9)
            if key in seen:
                continue
            item = _assemble_item(
                values=(
                    correct,
                    sympy.Rational(2 * a * n + 1, 2),  # 정수부만 곱(an + 1/2).
                    sympy.Integer(a * n),
                    sympy.Rational(2 * a + 1, 2),
                ),
                conditions=f"x = ({2 * a + 1}*{n})/2",
                answer_str=_display(correct),
                # 조사는 수 읽기 받침 판별 — '5과'·'5 을' 류 계통 결함 교정(S3-12).
                question_text=(
                    f"{a}{wa_gwa(str(a))} 1/2 (대분수)에 {n} {eul_reul(str(n))} 곱한 값을 구하시오."
                ),
                answer_explanation=(
                    f"대분수 {a}½ = {2 * a + 1}/2 에 {n}{eul_reul(str(n))} 곱하면 "
                    f"{(2 * a + 1) * n}/2 = {_display(correct)} 이다. "
                    f"정수부만 곱해 {a * n}½로 답하면 틀린다."
                ),
                difficulty=_difficulty(a + n),
                answer_format=_answer_format_for(correct),
            )
            if item is not None:
                seen.add(key)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_remainder_sign_pool() -> tuple[_EvalItem, ...]:
    """x²+bx+c 를 (x-a)로 나눈 나머지 뼈대 풀 — 정답 f(a)·오개념 f(-a)(부호 반대)·filler c·a²+c.

    나머지정리로 f(x)=x²+bx+c를 (x-a)로 나눈 나머지는 f(a)=a²+ab+c이다. 부호를 반대로
    f(-a)=a²-ab+c로 대입하면 틀린다. b≠0이라 f(a)≠f(-a). 조합이 네 값을 상이하게 한다. 정답값 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for a in range(2, 8):
        for b in range(1, 8):
            for c in range(1, 8):
                correct_v = a * a + a * b + c
                if correct_v in seen:
                    continue
                item = _assemble_item(
                    values=(
                        sympy.Integer(a * a + a * b + c),
                        sympy.Integer(a * a - a * b + c),  # f(-a) 부호 반대.
                        sympy.Integer(c),
                        sympy.Integer(a * a + c),
                    ),
                    conditions=f"x = {a}**2 + {a}*{b} + {c}",
                    answer_str=str(correct_v),
                    # 조사는 수·수식 꼬리 읽기 판별 — '7 를'·'(x-6)로' 류 결함 교정(S3-12).
                    question_text=(
                        f"다항식 x² + {b}x + {c} {eul_reul(str(c))} "
                        f"(x - {a}){euro_ro(f'(x - {a})')} 나눈 나머지를 구하시오."
                    ),
                    answer_explanation=(
                        f"나머지정리로 f({a}) = {a}² + {b}·{a} + {c} = {correct_v} 이다. "
                        f"부호를 반대로 f(-{a}){euro_ro(f'f(-{a})')} 대입하면 틀린다."
                    ),
                    difficulty=_difficulty(a + b + c),
                    answer_format=_answer_format_for(sympy.Integer(correct_v)),
                )
                if item is not None:
                    seen.add(correct_v)
                    pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_vieta_sum_pool() -> tuple[_EvalItem, ...]:
    """x²+bx+c=0 의 두 근의 합 뼈대 풀 — 정답 -b·오개념 b(부호 놓침)·filler c·-c.

    근과 계수 관계로 x²+bx+c=0의 두 근의 합은 -b이다. 부호를 놓치면 b로 틀린다. b≠0·c≠0이라 네 값
    {-b, b, c, -c}은 서로 다르다(c≠±b 되도록 c 순회). 정답값 -b로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for b in range(2, 26):
        c = b + 1  # c≠±b 보장(c=b+1)·filler ±c와 ±b 분리.
        correct_v = -b
        if correct_v in seen:
            continue
        item = _assemble_item(
            values=(
                sympy.Integer(-b),
                sympy.Integer(b),  # 부호 놓침.
                sympy.Integer(c),
                sympy.Integer(-c),
            ),
            conditions=f"x = -{b}",
            answer_str=str(correct_v),
            question_text=f"x² + {b}x + {c} = 0 의 두 근의 합을 구하시오.",
            answer_explanation=(
                # 조사는 수 읽기 받침 판별 — '23로' 류 계통 결함 교정(S3-12).
                f"근과 계수 관계로 두 근의 합은 -(일차항 계수) = -{b} = {correct_v} 이다. "
                f"부호를 놓쳐 {b}{euro_ro(str(b))} 답하면 틀린다."
            ),
            difficulty=_difficulty(b),
            answer_format=_answer_format_for(sympy.Integer(correct_v)),
        )
        if item is not None:
            seen.add(correct_v)
            pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_trapezoid_area_pool() -> tuple[_EvalItem, ...]:
    """사다리꼴 넓이 뼈대 풀 — 정답 (a+b)h/2·오개념 (a+b)h(÷2 누락)·filler a·h·b·h.

    사다리꼴 넓이 = (윗변+아랫변)×높이÷2 인데, ÷2 를 빠뜨려 (a+b)h 로 오인(M0161). a<b라
    네 값 {(a+b)h/2, (a+b)h, ah, bh}는 서로 다르다(a≠b·양수·÷2). 정답값으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[float] = set()
    for a in range(2, 9):
        for b in range(a + 1, 15):
            for h in range(2, 11):
                correct = sympy.Rational((a + b) * h, 2)
                key = round(_numeric(correct), 9)
                if key in seen:
                    continue
                item = _assemble_item(
                    values=(
                        correct,
                        sympy.Integer((a + b) * h),  # ÷2 누락.
                        sympy.Integer(a * h),  # 한 변만.
                        sympy.Integer(b * h),  # 다른 한 변만.
                    ),
                    conditions=f"x = ({a}+{b})*{h}/2",
                    answer_str=_display(correct),
                    question_text=(
                        f"윗변이 {a}, 아랫변이 {b}, 높이가 {h} 인 사다리꼴의 넓이를 구하시오."
                    ),
                    answer_explanation=(
                        # 조사는 수 읽기 받침 판별 — '81 가' 류 계통 결함 교정(S3-12).
                        f"사다리꼴의 넓이 = (윗변+아랫변)×높이÷2 = ({a}+{b})×{h}÷2 = "
                        f"{_display(correct)} 이다. ÷2 를 빠뜨리면 {(a + b) * h} "
                        f"{i_ga(str((a + b) * h))} 되어 틀린다."
                    ),
                    difficulty=_difficulty(a + b + h),
                    answer_format=_answer_format_for(correct),
                )
                if item is not None:
                    seen.add(key)
                    pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_scale_volume_pool() -> tuple[_EvalItem, ...]:
    """닮음비→부피비 뼈대 풀 — 정답 k³·오개념 k(부피비=닮음비 오인)·filler k²·3k.

    닮음비가 1:k 이면 부피비는 1:k³ 인데, 부피비를 닮음비 k 와 같게 오인한다(M0056·차원혼동).
    filler 는 넓이비 k²·선형 3배 3k. k≥2·k≠3(k²=3k 충돌 회피)라 네 값이 서로 다르다. 값 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for k in range(2, 31):
        correct_v = k**3
        if correct_v in seen:
            continue
        item = _assemble_item(
            values=(
                sympy.Integer(correct_v),
                sympy.Integer(k),  # 부피비=닮음비 오인.
                sympy.Integer(k * k),  # 넓이비와 혼동.
                sympy.Integer(3 * k),  # 선형 3배 오인.
            ),
            conditions=f"x = {k}**3",
            answer_str=str(correct_v),
            question_text=(
                f"닮음비가 1:{k} 인 두 입체도형의 부피비는 1:? 이다. ? 의 값을 구하시오."
            ),
            answer_explanation=(
                # 조사는 수 읽기 받침 판별 — '20 로' 류 계통 결함 교정(S3-12).
                f"닮음비가 1:{k} 이면 부피비는 1:{k}³ = 1:{correct_v} 이다. "
                f"부피비를 닮음비와 같은 {k} {euro_ro(str(k))} 두면 틀린다."
            ),
            difficulty=_difficulty(k),
            answer_format=AnswerFormat.자연수,
        )
        if item is not None:
            seen.add(correct_v)
            pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_cone_volume_pool() -> tuple[_EvalItem, ...]:
    """원뿔 부피 π계수 뼈대 풀 — 정답 r²h/3·오개념 r²h(⅓ 누락=원기둥)·filler r²h/2·2r²h/3.

    원뿔 부피 = ⅓·π·r²·h 이므로 부피÷π = r²h/3 인데, ⅓ 을 빠뜨려 원기둥 부피 πr²h 로 오인
    (M0063). filler 는 ½ 오인·⅔ 오인. r²h 를 6의 배수로 골라 네 값이 모두 자연수·서로 다르다
    (비율 1/3·1·1/2·2/3 상이). 정답값 r²h/3 으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for r in range(1, 8):
        for h in range(1, 31):
            v = r * r * h
            if v % 6 != 0:
                continue  # r²h 를 6의 배수로 한정 → V/2·V/3·2V/3 전부 자연수.
            correct_v = v // 3
            if correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(correct_v),
                    sympy.Integer(v),  # ⅓ 누락(원기둥 부피).
                    sympy.Integer(v // 2),  # ⅓ 을 ½ 로 오인.
                    sympy.Integer(2 * v // 3),  # ⅔ 로 오인.
                ),
                conditions=f"x = {r}**2*{h}/3",
                answer_str=str(correct_v),
                question_text=(
                    f"밑면의 반지름이 {r}, 높이가 {h} 인 원뿔의 부피를 원주율 π로 나눈 "
                    "값을 구하시오."
                ),
                answer_explanation=(
                    # 조사는 수 읽기 받침 판별 — '126 가' 류 계통 결함 교정(S3-12).
                    f"원뿔의 부피는 ⅓×π×(반지름)²×높이 이므로 π로 나눈 값은 "
                    f"{r}²×{h}÷3 곧 {correct_v} 이다. "
                    f"⅓ 을 빠뜨려 원기둥 부피로 계산하면 {v} {i_ga(str(v))} 되어 틀린다."
                ),
                difficulty=_difficulty(r + h),
                answer_format=AnswerFormat.자연수,
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_circle_area_pool() -> tuple[_EvalItem, ...]:
    """원 넓이 π계수 뼈대 풀 — 정답 r²·오개념 2r(넓이를 둘레 2πr 로 오인)·filler r·2r².

    원의 넓이 = π·r² 이므로 넓이÷π = r² 인데, 둘레 공식 2πr 와 혼동해 2r 로 오인한다
    (M0053). filler 는 반지름만 r·계수 2배 2r². r≥3(r²=2r 충돌 회피)라 네 값이 서로 다르다.
    정답값 r² 으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for r in range(3, 31):
        correct_v = r * r
        if correct_v in seen:
            continue
        item = _assemble_item(
            values=(
                sympy.Integer(correct_v),
                sympy.Integer(2 * r),  # 둘레 공식 2πr 와 혼동.
                sympy.Integer(r),  # 반지름만.
                sympy.Integer(2 * correct_v),  # 계수 2배.
            ),
            conditions=f"x = {r}**2",
            answer_str=str(correct_v),
            question_text=(f"반지름이 {r} 인 원의 넓이를 원주율 π로 나눈 값을 구하시오."),
            answer_explanation=(
                # 조사는 수·문자 읽기 받침 판별 — '6 로'·'2πr 와'(알=ㄹ 받침) 계통 결함 교정(S3-12).
                f"원의 넓이는 π×(반지름)² 이므로 π로 나눈 값은 {r}² 곧 {correct_v} 이다. "
                f"원의 둘레 공식 2πr {wa_gwa('2πr')} 혼동하면 2×{r} 곧 {2 * r} "
                f"{euro_ro(str(2 * r))} 잘못 답한다."
            ),
            difficulty=_difficulty(r),
            answer_format=AnswerFormat.자연수,
        )
        if item is not None:
            seen.add(correct_v)
            pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_combination_pool() -> tuple[_EvalItem, ...]:
    """조합 nCr 뼈대 풀 — 정답 C(n,r)·오개념 P(n,r)(분모 r! 누락=순열)·filler n·r·n+r.

    nCr = n!/(r!(n-r)!) 인데, 분모의 r! 을 빠뜨리면 순열의 수 nPr = n!/(n-r)! 이 된다(M0087).
    filler 는 곱셈 오인 n·r·덧셈 오인 n+r. 4-상이 검사로 충돌(예 r=2·특정 n)은 배제. 값 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for r in range(2, 5):
        for n in range(r + 2, 24):
            correct_v = comb(n, r)
            if correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(correct_v),
                    sympy.Integer(perm(n, r)),  # 분모 r! 누락(순열).
                    sympy.Integer(n * r),  # 곱셈 오인.
                    sympy.Integer(n + r),  # 덧셈 오인.
                ),
                conditions=f"x = {correct_v}",
                answer_str=str(correct_v),
                # 조사는 수식 꼬리(끝 수) 읽기 받침 판별 — '17C3 를'·'3024 이' 류 결함 교정(S3-12).
                question_text=(
                    f"서로 다른 {n} 개에서 {r} 개를 뽑는 조합의 수 "
                    f"{n}C{r} {eul_reul(f'{n}C{r}')} 구하시오."
                ),
                answer_explanation=(
                    f"{n}C{r} = {n}!/({r}!×{n - r}!) = {correct_v} 이다. "
                    f"분모의 {r}! 을 빠뜨리면 순열의 수 {n}P{r} = {perm(n, r)} "
                    f"{i_ga(str(perm(n, r)))} 되어 틀린다."
                ),
                difficulty=_difficulty(n + r),
                answer_format=AnswerFormat.자연수,
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_same_item_permutation_pool() -> tuple[_EvalItem, ...]:
    """같은 것이 있는 순열 뼈대 풀 — 정답 n!/(p!q!)·오개념 n!(중복 나눗셈 누락)·filler n!/p!·n!/q!.

    p 개의 A·q 개의 B(n=p+q)를 일렬 배열하는 경우의 수는 n!/(p!q!) 인데, 같은 것의 중복을 나누지
    않고 n! 로 오인한다(M0190·분배누락). filler 는 한쪽만 나눔 n!/p!·n!/q!. p<q라 네 값이 서로
    다르다(정답<n!/p!<n!/q!<n!). 정답값으로 dedup.
    """
    pool: list[_EvalItem] = []
    seen: set[int] = set()
    for p in range(2, 11):
        for q in range(p + 1, 11):
            n = p + q
            correct_v = factorial(n) // (factorial(p) * factorial(q))
            if correct_v in seen:
                continue
            item = _assemble_item(
                values=(
                    sympy.Integer(correct_v),
                    sympy.Integer(factorial(n)),  # 중복 나눗셈 누락.
                    sympy.Integer(factorial(n) // factorial(p)),  # 한쪽만 나눔.
                    sympy.Integer(factorial(n) // factorial(q)),  # 다른 한쪽만.
                ),
                conditions=f"x = {correct_v}",
                answer_str=str(correct_v),
                question_text=(
                    f"{p} 개의 A 와 {q} 개의 B, 모두 {n} 개의 문자를 일렬로 "
                    "배열하는 경우의 수를 구하시오."
                ),
                answer_explanation=(
                    f"같은 것이 있는 순열이므로 {n}! 을 각 문자 개수의 계승 {p}!·{q}! 로 나눈다: "
                    f"{n}!/({p}!×{q}!) = {correct_v} 이다. 중복을 나누지 않고 {n}! 로 두면 틀린다."
                ),
                difficulty=_difficulty(p + q),
                answer_format=AnswerFormat.자연수,
            )
            if item is not None:
                seen.add(correct_v)
                pool.append(item)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


_POOL_FACTORY = {
    "distribution": _build_distribution_pool,
    "chain_rule": _build_chain_rule_pool,
    "sine_sum": _build_sine_pool,
    "exp_zero": _build_exp_zero_pool,
    "sqrt_pos": _build_sqrt_pos_pool,
    "log_dist": _build_log_dist_pool,
    "func_compose": _build_func_compose_pool,
    "sine_period": _build_sine_period_pool,
    "translate": _build_translate_pool,
    "product_rule": _build_product_rule_pool,
    "fraction_cancel": _build_fraction_cancel_pool,
    "polygon_angle_sum": _build_polygon_angle_sum_pool,
    "area_perimeter": _build_area_perimeter_pool,
    "circle_radius": _build_circle_radius_pool,
    "gambler_streak": _build_gambler_streak_pool,
    "fraction_addition": _build_fraction_addition_pool,
    "negative_product": _build_negative_product_pool,
    "subtract_negative": _build_subtract_negative_pool,
    "absolute_value": _build_absolute_value_pool,
    "sqrt_sum": _build_sqrt_sum_pool,
    "difference_of_squares": _build_difference_of_squares_pool,
    "exponent_product": _build_exponent_product_pool,
    "power_of_power": _build_power_of_power_pool,
    "negative_square": _build_negative_square_pool,
    "distribute_partial": _build_distribute_partial_pool,
    "negative_distribute": _build_negative_distribute_pool,
    "square_difference": _build_square_difference_pool,
    "midpoint_no_half": _build_midpoint_no_half_pool,
    "scale_area": _build_scale_area_pool,
    "negative_even_power": _build_negative_even_power_pool,
    "combine_unlike": _build_combine_unlike_pool,
    "complete_square": _build_complete_square_pool,
    "conjugate_product": _build_conjugate_product_pool,
    "transpose": _build_transpose_pool,
    "gcd_lcm": _build_gcd_lcm_pool,
    "decimal_mult": _build_decimal_mult_pool,
    "mixed_mult": _build_mixed_mult_pool,
    "remainder_sign": _build_remainder_sign_pool,
    "vieta_sum": _build_vieta_sum_pool,
    "trapezoid_area": _build_trapezoid_area_pool,
    "scale_volume": _build_scale_volume_pool,
    "cone_volume": _build_cone_volume_pool,
    "circle_area": _build_circle_area_pool,
    "combination": _build_combination_pool,
    "same_item_permutation": _build_same_item_permutation_pool,
}


@deterministic_generator
class MisconceptionEvalMCSkeletonGenerator:
    """오개념 수치평가 객관식 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `template`(distribution/chain_rule/sine_sum/exp_zero/sqrt_pos/log_dist/func_compose/
    sine_period)이 수학 실체를, 생성자 `distractor_codes`가 오답 선지의 오개념·op-code id를 정한다
    (극값 MC 규약 미러·L4 하드코딩 0). `distractor_codes`는 단일 엔트리
    `{kebab: (misconception_id, op_code)}`를 기대한다(op_code는 None 허용 — op-code 없는 오개념은
    오개념만 태깅) — 각 문항이 오개념 오답 *1건*만
    태깅하기 때문(filler는 미태깅). 풀을 순서대로 소비하며 후보를 낸다(소진 시 None —
    generation_failed로 정직 기록). `skip_signatures`에 이미 코퍼스에 있는 구조 signature를 주면
    해당 뼈대를 건너뛴다(배치 재실행 dedup 낭비 방지·오케스트레이터 signature_index 공유).
    """

    def __init__(
        self,
        template: TemplateKind,
        distractor_codes: Mapping[str, tuple[str, str | None]],
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-misc-eval-mc",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        concept_relevance: float = 0.95,
    ) -> None:
        if template not in _POOL_FACTORY:
            raise ValueError(
                f"미지원 template: {template!r} (distribution/chain_rule/sine_sum/exp_zero/"
                "sqrt_pos/log_dist/func_compose/sine_period/translate/product_rule/"
                "fraction_cancel/polygon_angle_sum/area_perimeter/circle_radius/gambler_streak/"
                "fraction_addition/negative_product/subtract_negative/absolute_value/sqrt_sum/"
                "difference_of_squares/exponent_product/power_of_power/negative_square/"
                "distribute_partial/negative_distribute/square_difference/midpoint_no_half/"
                "scale_area/negative_even_power/combine_unlike/complete_square/conjugate_product/"
                "transpose/gcd_lcm/decimal_mult/mixed_mult/remainder_sign/vieta_sum/"
                "trapezoid_area/scale_volume/cone_volume/circle_area/combination/"
                "same_item_permutation)"
            )
        if not distractor_codes:
            raise ValueError(
                "distractor_codes 주입 누락 — 오개념 오답 태깅용 (misconception_id, op_code)가 "
                "최소 1건 필요하다(L4 정본에서 조성 루트가 주입)."
            )
        # 각 문항이 오개념 오답 1건만 태깅하므로 단일 (misconception_id, op_code)만 쓴다.
        self._misconception_id, self._op_code = next(iter(distractor_codes.values()))
        self._template: TemplateKind = template
        self._pool = _POOL_FACTORY[template]()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        concept_src_id, unit_code = _TEMPLATE_META[template]
        self._unit_codes = [unit_code]
        self._concept_tags = [
            ConceptTag(
                concept_src_id=concept_src_id,
                role="PRIMARY",
                relevance=concept_relevance,
            )
        ]

    # ── EquivalentProblemGenerator 좌석 ────────────────────────────────────
    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
        while self._index < len(self._pool):
            item = self._pool[self._index]
            self._index += 1
            if self._skip is not None:
                signature = canonical_signature(item.conditions, None)
                if signature is not None and signature in self._skip:
                    continue  # 이미 코퍼스에 있는 구조 — 회차 낭비 없이 다음 뼈대로.
            return self._assemble(spec, item)
        return None

    # ── 조립(전부 결정론·수치의 단일 진실 원천은 뼈대) ─────────────────────
    def _assemble(self, spec: EquivalenceSpec, item: _EvalItem) -> CandidateProblem:
        standard_codes = sorted(spec.achievement_standard_codes)
        answer_text = item.choices[item.answer_index]
        slug = self._stable_slug(item.question_text, answer_text, standard_codes)

        # 오개념 오답 1건만 태깅(filler는 미태깅·스키마 계약: 정답 선지 제외).
        distractor_map = [
            DistractorEntry(
                choice_index=item.misc_index,
                misconception_id=self._misconception_id,
                op_code=self._op_code,
            )
        ]

        problem = Problem(
            problem_id=uuid.uuid5(uuid.NAMESPACE_URL, f"whymath:problem:{slug}"),
            slug=slug,
            source_type=SourceType.자체생성,  # 저작권 구조적 강제(자작 뼈대·본문성 원본 0)
            curriculum_version=self._curriculum_version,
            valid_from_year=self._valid_from_year,
            subject=self._subject,
            unit_codes=list(self._unit_codes),
            difficulty_overall=item.difficulty,
            question_format=QuestionFormat.객관식,
            answer_format=item.answer_format,
            achievement_standard_codes=standard_codes,
            question_text=item.question_text,
            choices=list(item.choices),
            answer=answer_text,
            answer_explanation=item.answer_explanation,
            distractor_map=distractor_map,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 수치평가 MC 스켈레톤 조립(닫힌 값 4지선다·오개념 오답 태깅)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(오개념 귀속 교수학 검수)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=item.conditions,  # dummy x 등식(정답 검산용·호출자 제공)
            answer_map={"x": item.answer_str},
            answer_selection=None,  # 유일해(닫힌 값)라 근 선택 불요.
            answer_aggregate=None,
            solution_steps=None,
            concept_tags=list(self._concept_tags),
        )

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        """결정론 안정 slug — 내용 해시(멱등 upsert 키·극값 MC 규약 미러)."""
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"
