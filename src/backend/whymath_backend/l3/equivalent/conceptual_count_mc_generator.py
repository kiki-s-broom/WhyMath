"""개념형(개수/판정) 수치평가 객관식 스켈레톤 생성기 — 개수/판정 검증 축(결정론·LLM 0).

수치평가 MC(`misconception_eval_mc_generator`)의 개념형 형제다. 답이 *값*이 아니라 *개수/판정*(실근
개수·극값 개수·일대일 여부·등비급수 수렴 여부)인 문항을 낸다 — 이 답은 게이트가 SymPy로 *독립
계산*해 검증(`verify_real_root_count`·`verify_extremum_count`·`verify_is_one_to_one`·
`verify_geometric_convergence`)하므로 오개념의 틀린 답은 fail한다(진짜 개념 검증). 겨누는 오개념:
  - `real_root_count`: 판별식을 무시해 "이차방정식은 늘 두 실근"으로 오인(discriminant-negative-
    no-real-root) — 실근 0/1개인데 2로 답한다.
  - `extremum_count`: 임계점(f'=0)을 곧 극값으로 오인(critical-point-implies-extremum) — f(x)=(x-a)³
    은 임계점 1개(x=a)이나 극값 0개인데 1로 답한다.
  - `is_one_to_one`: "일대일 아니어도 역함수가 있다"고 오인(invertibility-without-1-1) — 포물선은
    일대일이 아니라 0인데 1로 답한다.
  - `geometric_convergence`: "등비급수는 늘 수렴한다"고 오인(geometric-series-always-converges) —
    |r|>1은 발산(0)인데 1로 답한다.

`CandidateProblem`에 `answer_kind`를 담고 `answer_map={}`(개수/판정은 근 대입 아님)로 오케스트레이터
·수용 게이트·저장 sink를 재사용한다. 오답 선지 오개념 id는 생성자 `distractor_codes`로 주입받는다
(L4 하드코딩 0·계층 규칙). 산출물은 v0(사람 검수 전) — 게이트 통과 ≠ 학생 노출.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from math import gcd
from typing import Literal

import sympy

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.canonicalize import canonical_signature
from whymath_backend.l3.equivalent.generator import CandidateProblem, deterministic_generator
from whymath_backend.lang.josa import eun_neun, euro_ro, i_ga, wa_gwa
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
    "ConceptualCountMCSkeletonGenerator",
    "CountTemplateKind",
]

CountTemplateKind = Literal[
    "real_root_count",
    "extremum_count",
    "is_one_to_one",
    "geometric_convergence",
    "limit_equals_value",
    "is_differentiable",
    "series_converges",
    "excluded_point_count",
    "mean_equals_median",
    "events_independent",
    "conditional_equal",
    "congruent_by_ratio",
    "dot_product_scalar",
    "inequality_direction",
    "root_loss_count",
]

# 개수/판정 선지 — 4지선다는 항상 {0,1,2,3}. 판정형(일대일·수렴·극한=함숫값·미분가능)은 0/1을 쓴다.
_COUNT_CHOICES: tuple[str, str, str, str] = ("0", "1", "2", "3")

# 템플릿별 L1 메타(개념 원천 src_id·단원 코드). 성취기준 코드는 spec이 공급.
_TEMPLATE_META: dict[CountTemplateKind, tuple[str, str]] = {
    "real_root_count": ("HK07", "DISC-COUNT"),
    "extremum_count": ("H:12미적Ⅰ02-01", "EXTREMUM-COUNT"),
    "is_one_to_one": ("10기수2-03-03", "FUNC-INVERSE"),
    "geometric_convergence": ("H:12미적Ⅱ01-05", "GEO-SERIES-CONV"),
    "limit_equals_value": ("H:12미적Ⅰ01-01", "LIMIT-VALUE"),
    "is_differentiable": ("H:12미적Ⅰ02-02", "DIFFERENTIABILITY"),
    "series_converges": ("H:12미적Ⅱ01-04", "SERIES-CONV"),
    "excluded_point_count": ("J0103", "DOMAIN-EXCLUDE"),
    "mean_equals_median": ("J0401", "STAT-MEAN-MEDIAN"),
    "events_independent": ("H:12확통02-05", "PROB-INDEPENDENCE"),
    "conditional_equal": ("H:12확통02-04", "PROB-CONDITIONAL"),
    "congruent_by_ratio": ("J0301", "GEOM-SIMILAR-CONGRUENT"),
    "dot_product_scalar": ("H:12기하03-03", "VEC-DOT-PRODUCT"),
    "inequality_direction": ("J0211", "INEQ-SIGN-FLIP"),
    "root_loss_count": ("J0220", "ROOT-LOSS-DIVIDE"),
}


@dataclass(frozen=True, slots=True)
class _CountItem:
    """개수형 MC 뼈대 — conditions·answer_kind·정답 개수·오개념 개수(수치의 단일 진실 원천)."""

    conditions: str
    answer_kind: CountTemplateKind
    answer_str: str  # 정답 개수(문자열)
    misc_str: str  # 오개념 개수(문자열)
    question_text: str
    answer_explanation: str
    difficulty: float


def _difficulty(seed: int) -> float:
    """종합 난이도를 [2.5, 3.5] 밴드에 결정론 분산 — spec 난이도 3.0·tol 0.5 안이라 동등성 만점."""
    return round(2.5 + (seed % 11) * 0.1, 1)


def _build_real_root_count_pool() -> tuple[_CountItem, ...]:
    """이차방정식 x²+bx+c=0 의 서로 다른 실근 개수 뼈대 풀 — 판별식 ≤ 0(실근 0/1)만.

    오개념(판별식 무시·늘 2근)이 *틀린 답*을 주는 경우만 낸다: 판별식<0(실근 0)·판별식=0(중근·실근
    1). 정답 0 또는 1·오개념 오답은 항상 2. b²-4c≤0 되도록 (b,c) 순회. conditions dedup(같은 이차식
    구조 signature 공유 방지는 오케스트레이터가 kind payload로 처리).
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for b in range(0, 8):
        for c in range(1, 18):
            disc = b * b - 4 * c
            if disc > 0:
                continue  # 실근 2개 → 오개념이 우연히 정답(무의미) → 제외.
            correct = 1 if disc == 0 else 0  # 판별식=0 중근(1개)·<0 실근 없음(0개).
            conditions = f"x**2 + {b}*x + {c} = 0" if b else f"x**2 + {c} = 0"
            if conditions in seen:
                continue
            seen.add(conditions)
            b_disp = f" + {b}x" if b else ""
            pool.append(
                _CountItem(
                    conditions=conditions,
                    answer_kind="real_root_count",
                    answer_str=str(correct),
                    misc_str="2",
                    question_text=(
                        f"이차방정식 x^2{b_disp} + {c} = 0 의 서로 다른 실근의 개수를 구하시오."
                    ),
                    answer_explanation=(
                        f"판별식 D = {b}^2 - 4·{c} = {disc} 이므로 "
                        + ("중근을 가져 서로 다른 실근은 1개" if disc == 0 else "실근이 없다(0개)")
                        + ". 판별식을 무시하고 늘 2근이라 답하면 틀린다."
                    ),
                    difficulty=_difficulty(b + c),
                )
            )
    return tuple(pool)


def _build_extremum_count_pool() -> tuple[_CountItem, ...]:
    """삼차함수 f(x)=(x-a)³+c 의 극값 개수 뼈대 풀 — 임계점 1개이나 극값 0개(오개념 정확 표적).

    f'(x)=3(x-a)²는 x=a에서만 0이나 부호가 안 바뀌어(항상 ≥0) 극값이 없다. 정답 0·오개념 오답은
    임계점 개수 1. (a,c) 순회·conditions dedup. 오개념(임계점=극값)이 틀린 답 1을 주는 정확한 유형.
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for a in range(1, 7):
        for c in range(0, 6):
            conditions = f"(x - {a})**3 + {c}" if c else f"(x - {a})**3"
            if conditions in seen:
                continue
            seen.add(conditions)
            c_disp = f" + {c}" if c else ""
            pool.append(
                _CountItem(
                    conditions=conditions,
                    answer_kind="extremum_count",
                    answer_str="0",
                    misc_str="1",
                    question_text=(
                        f"삼차함수 f(x) = (x - {a})^3{c_disp} 의 극값의 개수를 구하시오."
                    ),
                    answer_explanation=(
                        "도함수가 완전제곱 꼴이라 한 점에서만 0이 되고 그 좌우로 부호가 바뀌지 "
                        "않으므로 극값이 없다 — 극값은 0개다. 도함수가 0인 임계점을 곧 극값으로 "
                        "여기면 1로 잘못 답한다."
                    ),
                    difficulty=_difficulty(a + c),
                )
            )
    return tuple(pool)


def _build_is_one_to_one_pool() -> tuple[_CountItem, ...]:
    """f(x)=x²+bx+c 가 ℝ에서 일대일대응인지 뼈대 풀 — 포물선은 늘 일대일 아님(오개념 정확 표적).

    이차함수 f'(x)=2x+b는 x=-b/2에서 부호가 바뀌므로(꼭짓점 좌우 단조 반전) f는 일대일이 아니다 —
    정답 0. "일대일이 아니어도 역함수가 있다"는 오개념(invertibility-without-1-1)은 1로 답해 fail.
    단항식(a=1·monic)으로 두어 정준 signature 충돌을 피하고(상수 c가 signature를 갈라줌), (b,c)
    순회. 상수항은 일대일 여부를 바꾸지 않는다(여전히 0). 답은 판정값(0/1)이라 SymPy 독립 검증.
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for b in range(0, 5):
        for c in range(0, 6):
            terms = "x**2"
            if b:
                terms += f" + {b}*x"
            if c:
                terms += f" + {c}"
            conditions = terms
            if conditions in seen:
                continue
            seen.add(conditions)
            b_disp = f" + {b}x" if b else ""
            c_disp = f" + {c}" if c else ""
            # 주격 조사는 식 꼬리 읽기 받침 판별 — 'x^2 가'(제곱=곱) 류 결함 교정(S3-12).
            formula = f"x^2{b_disp}{c_disp}"
            pool.append(
                _CountItem(
                    conditions=conditions,
                    answer_kind="is_one_to_one",
                    answer_str="0",
                    misc_str="1",
                    question_text=(
                        f"함수 f(x) = {formula} {i_ga(formula)} 실수 전체에서 일대일대응이면 1, "
                        "아니면 0을 쓰시오."
                    ),
                    answer_explanation=(
                        "이차함수는 꼭짓점을 기준으로 증가·감소가 뒤바뀌어 서로 다른 두 x가 같은 "
                        "값을 가지므로 일대일대응이 아니다 — 0이다. 일대일이 아니어도 역함수가 "
                        "있다고 오인하면 1로 잘못 답한다."
                    ),
                    difficulty=_difficulty(b + c),
                )
            )
    return tuple(pool)


def _build_geometric_convergence_pool() -> tuple[_CountItem, ...]:
    """공비 r=p/q(|r|>1)인 등비급수의 수렴 여부 뼈대 풀 — 발산만(오개념 정확 표적).

    |r|≥1이면 등비급수는 발산한다 — 정답 0. "등비급수는 늘 수렴한다"는 오개념(geometric-series-
    always-converges)은 1로 답해 fail. 기약분수 p/q(p>q≥1) 순회·conditions dedup. 답은 판정값(0/1)
    이라 answer_kind=geometric_convergence로 SymPy 독립 검증.
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for q in range(1, 5):
        for p in range(q + 1, q + 11):
            if gcd(p, q) != 1:
                continue
            conditions = f"{p}/{q}"
            if conditions in seen:
                continue
            seen.add(conditions)
            r_disp = f"{p}/{q}" if q != 1 else f"{p}"
            pool.append(
                _CountItem(
                    conditions=conditions,
                    answer_kind="geometric_convergence",
                    answer_str="0",
                    misc_str="1",
                    question_text=(
                        f"공비가 r = {r_disp} 인 등비급수가 수렴하면 1, 발산하면 0을 쓰시오."
                    ),
                    answer_explanation=(
                        # 보조사는 분수 읽기(분모분의 분자) 받침 판별 — '7/4 는' 류 교정(S3-12).
                        f"등비급수는 |r| < 1 일 때만 수렴하는데 r = {r_disp} "
                        f"{eun_neun(r_disp)} |r| > 1 이므로 발산한다 — 0이다. "
                        "등비급수가 늘 수렴한다고 오인하면 1로 잘못 답한다."
                    ),
                    difficulty=_difficulty(p + q),
                )
            )
    return tuple(pool)


def _build_limit_equals_value_pool() -> tuple[_CountItem, ...]:
    """유리식 f(x)=(x−a)(x−b)/(x−a)의 x=a에서 lim=f(a) 여부 뼈대 풀 — 제거가능 특이점(오개념 표적).

    x=a에서 분자·분모가 함께 0(0/0)이라 함수값은 미정의이나 극한은 유한(b−a 방향)이라 lim ≠ f(a) —
    정답 0. "극한값은 늘 함수값과 같다"는 오개념(limit-equals-function-value)은 1로 답해 fail. 자동
    약분을 막으려 **분자는 전개형** x²−(a+b)x+ab로 낸다(약분되면 특이점 소멸). (a,b≠a) 순회.
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for a in range(1, 7):
        for b in range(1, 7):
            if b == a:
                continue  # a=b면 중근이라 극한도 특이(0 or ∞)·표적 아님.
            s, p = a + b, a * b
            conditions = f"(x**2 - {s}*x + {p})/(x - {a})"
            if conditions in seen:
                continue
            seen.add(conditions)
            pool.append(
                _CountItem(
                    conditions=conditions,
                    answer_kind="limit_equals_value",
                    answer_str="0",
                    misc_str="1",
                    # 주격 조사는 식 꼬리 읽기 받침 판별 — 'f(1) 가' 류 결함 교정(S3-12).
                    question_text=(
                        f"함수 f(x) = (x^2 - {s}x + {p}) / (x - {a}) 에서 "
                        f"lim(x→{a}) f(x) = f({a}) {i_ga(f'f({a})')} 성립하면 1, "
                        "아니면 0을 쓰시오."
                    ),
                    answer_explanation=(
                        # S3-12 교정: 극한값은 (x−a)(x−b)/(x−a)의 x→a 극한 = a−b — 생성기가
                        # b−a로 부호를 뒤집어 적던 계통 결함(explanation_slip 13건)을 바로잡는다.
                        # 조사도 값 읽기 받침 판별(euro_ro·eun_neun)로 고른다.
                        f"x = {a} 에서 분자·분모가 함께 0이 되어 함수값 "
                        f"f({a}){eun_neun(f'f({a})')} 정의되지 않지만 "
                        f"약분하면 극한값은 {a - b}{euro_ro(str(a - b))} 유한하다 — "
                        "극한값과 함수값이 달라 0이다. "
                        "극한값이 늘 함수값과 같다고 오인하면 1로 잘못 답한다."
                    ),
                    difficulty=_difficulty(a + b),
                )
            )
    return tuple(pool)


def _build_is_differentiable_pool() -> tuple[_CountItem, ...]:
    """f(x)=|x−a|+c 가 ℝ에서 미분가능한지 뼈대 풀 — 절댓값 꺾인점(연속이나 미분불가·오개념 표적).

    x=a에서 좌·우 미분계수가 −1·+1로 달라 미분 불가(연속은 성립) — 정답 0. "연속이면 미분가능"이라는
    오개념(continuity-implies-differentiability)은 1로 답해 fail. (a,c) 순회·conditions dedup.
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for a in range(1, 7):
        for c in range(0, 5):
            conditions = f"Abs(x - {a}) + {c}" if c else f"Abs(x - {a})"
            if conditions in seen:
                continue
            seen.add(conditions)
            c_disp = f" + {c}" if c else ""
            # 주격 조사는 식 꼬리 읽기 받침 판별 — '|x-1| 가'·'3 가' 류 결함 교정(S3-12).
            formula = f"|x - {a}|{c_disp}"
            pool.append(
                _CountItem(
                    conditions=conditions,
                    answer_kind="is_differentiable",
                    answer_str="0",
                    misc_str="1",
                    question_text=(
                        f"함수 f(x) = {formula} {i_ga(formula)} 실수 전체에서 미분가능하면 1, "
                        "아니면 0을 쓰시오."
                    ),
                    answer_explanation=(
                        f"x = {a} 에서 좌미분계수 −1·우미분계수 +1로 서로 달라 미분가능하지 않다 "
                        "(연속이기는 하다) — 0이다. 연속이면 곧 미분가능하다고 오인하면 1로 잘못 "
                        "답한다."
                    ),
                    difficulty=_difficulty(a + c),
                )
            )
    return tuple(pool)


def _build_series_converges_pool() -> tuple[_CountItem, ...]:
    """일반항 a_n→0이나 급수가 발산하는 뼈대 풀 — 조화형·p<1(오개념 정확 표적).

    일반항이 0에 수렴해도 Σa_n은 발산할 수 있다(조화급수 Σ1/n·Σ1/√n) — 정답 0. "일반항이 0이면
    급수도 수렴"이라는 오개념(term-to-zero-implies-convergence)은 1로 답해 fail. 두 발산 계열
    (1/(n+c)·1/√(n+c)) 순회·conditions dedup. 모두 일반항→0이라 오개념이 정확히 틀린 유형이다.
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for c in range(0, 15):
        for form in (
            f"1/(n + {c})" if c else "1/n",
            f"1/sqrt(n + {c})" if c else "1/sqrt(n)",
        ):
            conditions = form
            if conditions in seen:
                continue
            seen.add(conditions)
            disp = form.replace("sqrt", "√").replace("*", "")
            pool.append(
                _CountItem(
                    conditions=conditions,
                    answer_kind="series_converges",
                    answer_str="0",
                    misc_str="1",
                    question_text=(
                        f"일반항이 a_n = {disp} 인 급수 Σa_n 이 수렴하면 1, 발산하면 0을 쓰시오."
                    ),
                    answer_explanation=(
                        "일반항은 0에 수렴하지만 이 급수는 발산한다(조화급수류) — 0이다. 일반항이 "
                        "0에 수렴하면 급수도 수렴한다고 오인하면 1로 잘못 답한다."
                    ),
                    difficulty=_difficulty(c),
                )
            )
    return tuple(pool)


def _build_excluded_point_count_pool() -> tuple[_CountItem, ...]:
    """f(x)=1/(분모)의 정의역에서 제외되는 실수 개수 뼈대 풀 — 분모=0 실근 개수(오개념 정확 표적).

    유리함수는 분모가 0인 점에서 정의되지 않는다 — 제외점 개수 = 분모의 서로 다른 실근 개수(1~3).
    "분모에 변수가 와도 항상 정의됨"이라는 오개념(division-by-zero)은 0으로 답해 fail. conditions는
    분모=0 방정식이라 `verify_real_root_count`(kind=excluded_point_count)가 근 개수로 검증한다.
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    roots_sets: list[tuple[int, ...]] = [(a,) for a in range(1, 8)]
    roots_sets += [(a, b) for a in range(1, 6) for b in range(a + 1, 7)]
    roots_sets += [(1, 2, 3), (1, 2, 4), (2, 3, 5), (1, 3, 5), (2, 4, 6)]
    for roots in roots_sets:
        factors = "*".join(f"(x - {r})" for r in roots)
        conditions = f"{factors} = 0"
        if conditions in seen:
            continue
        seen.add(conditions)
        count = len(roots)
        denom_disp = "".join(f"(x - {r})" for r in roots)
        pool.append(
            _CountItem(
                conditions=conditions,
                answer_kind="excluded_point_count",
                answer_str=str(count),
                misc_str="0",
                question_text=(
                    f"함수 f(x) = 1/({denom_disp}) 의 정의역에서 제외되는 실수의 개수를 구하시오."
                ),
                answer_explanation=(
                    f"분모가 0이 되는 x = {', '.join(str(r) for r in roots)} 에서 함수가 정의되지 "
                    f"않으므로 제외되는 실수는 {count}개다. 분모에 변수가 와도 항상 정의된다고 "
                    "여기면 0으로 잘못 답한다."
                ),
                difficulty=_difficulty(sum(roots)),
            )
        )
    return tuple(pool)


def _build_mean_equals_median_pool() -> tuple[_CountItem, ...]:
    """자료 {a..a+3, a+c}(c≥8·이상치)의 평균=중앙값 여부 뼈대 풀 — 왜곡 자료만(오개념 표적).

    중앙값 a+2·평균 a+(6+c)/5인데 c≥8이면 평균>중앙값이라 같지 않다 — 정답 0. "평균과 중앙값은 늘
    같다"는 오개념(mean-vs-median)은 1로 답해 fail. (a,c) 순회. 이상치 하나로 평균이 끌려가는 유형.
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for a in range(1, 7):
        for c in range(8, 13):
            data = [a, a + 1, a + 2, a + 3, a + c]
            conditions = ",".join(str(x) for x in data)
            if conditions in seen:
                continue
            seen.add(conditions)
            pool.append(
                _CountItem(
                    conditions=conditions,
                    answer_kind="mean_equals_median",
                    answer_str="0",
                    misc_str="1",
                    question_text=(
                        f"자료 {', '.join(str(x) for x in data)} 의 평균과 중앙값이 같으면 1, "
                        "다르면 0을 쓰시오."
                    ),
                    answer_explanation=(
                        f"중앙값은 {a + 2}이나 평균은 이상치 {a + c} 때문에 그보다 커서 둘이 같지 "
                        "않다 — 0이다. 평균과 중앙값이 늘 같다고 오인하면 1로 잘못 답한다."
                    ),
                    difficulty=_difficulty(a + c),
                )
            )
    return tuple(pool)


def _build_events_independent_pool() -> tuple[_CountItem, ...]:
    """배반사건 A,B(P(A),P(B)>0·P(A∩B)=0)의 독립 여부 뼈대 풀 — 배반이나 비독립(오개념 정확 표적).

    독립 ⇔ P(A∩B)=P(A)P(B)인데 배반이면 P(A∩B)=0·P(A)P(B)>0이라 독립이 아니다 — 정답 0. "배반이면
    독립"이라는 오개념(mutually-exclusive-implies-independent)은 1로 답해 fail. conditions는
    "P(A),P(B),0". (i,j) 순회·P(A)+P(B)≤1(유효 배반). 답은 판정(0/1)이라 SymPy 독립 계산으로 검증.
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for i in range(1, 8):
        for j in range(1, 8):
            if i + j > 11:  # P(A)+P(B) ≤ 11/12 < 1(유효 배반).
                continue
            conditions = f"{i}/12,{j}/12,0"
            if conditions in seen:
                continue
            seen.add(conditions)
            pa, pb = sympy.Rational(i, 12), sympy.Rational(j, 12)
            pool.append(
                _CountItem(
                    conditions=conditions,
                    answer_kind="events_independent",
                    answer_str="0",
                    misc_str="1",
                    question_text=(
                        f"두 배반사건 A, B에 대하여 P(A) = {pa}, P(B) = {pb} 일 때, "
                        "A와 B가 서로 독립이면 1, 아니면 0을 쓰시오."
                    ),
                    answer_explanation=(
                        f"배반사건이라 P(A∩B) = 0이지만 P(A)P(B) = {pa * pb} > 0이므로 "
                        "P(A∩B) ≠ P(A)P(B)라 독립이 아니다 — 0이다. 배반이면 곧 독립이라 "
                        "오인하면 1로 잘못 답한다."
                    ),
                    difficulty=_difficulty(i + j),
                )
            )
    return tuple(pool)


def _build_conditional_equal_pool() -> tuple[_CountItem, ...]:
    """P(A)≠P(B)인 조건에서 P(A|B)=P(B|A) 여부 뼈대 풀 — 비대칭만(오개념 정확 표적).

    베이즈로 P(B|A)=P(A|B)P(B)/P(A)라 P(A)≠P(B)면 P(A|B)≠P(B|A)다 — 정답 0. "P(A|B)=P(B|A)"라는
    오개념(prosecutor-fallacy)은 1로 답해 fail. conditions="P(A),P(B),P(A|B)"·(i≠j) 순회.
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for i in range(1, 9):
        for j in range(1, 9):
            if i == j:  # P(A)=P(B)면 대칭이라 오개념 표적 아님.
                continue
            m = 6  # P(A|B)=6/12=1/2(임의 유효값·대칭 판정은 P(A),P(B)로 결정).
            pa, pb, pab = (sympy.Rational(x, 12) for x in (i, j, m))
            # S3-12 확률 공리 가드 — P(A∩B) = P(A|B)·P(B) ≤ min(P(A), P(B))를 위반하는 시드는
            # **거부(skip)** 한다(기존 밴드 시드 정책 미러 — i=j 배제와 같은 continue 규약).
            # 위반 시드는 실현 불가능한 확률 설정(예 P(B|A)=P(A∩B)/P(A) > 1)을 낳는다 —
            # S3-09 감사 확정 모순 전제(condition_mismatch) 7건의 원인(재생성으로 자연 폐기).
            p_ab = pab * pb
            if p_ab > min(pa, pb):
                continue
            conditions = f"{i}/12,{j}/12,{m}/12"
            if conditions in seen:
                continue
            seen.add(conditions)
            pool.append(
                _CountItem(
                    conditions=conditions,
                    answer_kind="conditional_equal",
                    answer_str="0",
                    misc_str="1",
                    question_text=(
                        f"P(A) = {pa}, P(B) = {pb}, P(A|B) = {pab} 일 때, "
                        "P(A|B) = P(B|A) 이면 1, 아니면 0을 쓰시오."
                    ),
                    answer_explanation=(
                        # 접속 조사는 분수 읽기 받침 판별 — '1/2 와 달라' 류 결함 교정(S3-12).
                        f"베이즈 정리로 P(B|A) = P(A|B)·P(B)/P(A) = {pab * pb / pa} 인데 "
                        f"P(A|B) = {pab} {wa_gwa(str(pab))} 달라 P(A|B) ≠ P(B|A)다 — 0이다. "
                        "둘을 같다고 여기는 검사의 오류에 빠지면 1로 잘못 답한다."
                    ),
                    difficulty=_difficulty(i + j),
                )
            )
    return tuple(pool)


def _build_congruent_by_ratio_pool() -> tuple[_CountItem, ...]:
    """닮음비 k=p/q(≠1)인 두 도형의 합동 여부 뼈대 풀 — 닮음비≠1만(오개념 정확 표적).

    합동 ⇔ 닮음비 1인데 k≠1이면 닮았으나 합동이 아니다 — 정답 0. "닮으면 합동"이라는 오개념
    (similarity-vs-congruence)은 1로 답해 fail. 기약 p/q(p≠q) 순회·conditions dedup.
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for q in range(1, 5):
        for p in range(1, 10):
            if p == q or gcd(p, q) != 1:
                continue
            conditions = f"{p}/{q}"
            if conditions in seen:
                continue
            seen.add(conditions)
            k_disp = f"{p}/{q}" if q != 1 else f"{p}"
            pool.append(
                _CountItem(
                    conditions=conditions,
                    answer_kind="congruent_by_ratio",
                    answer_str="0",
                    misc_str="1",
                    question_text=(
                        f"닮음비가 {k_disp} 인 두 도형이 합동이면 1, 아니면 0을 쓰시오."
                    ),
                    answer_explanation=(
                        f"두 도형이 합동이려면 닮음비가 1이어야 하는데 닮음비가 {k_disp}(≠1)이므로 "
                        "닮았을 뿐 합동은 아니다 — 0이다. 닮으면 곧 합동이라고 오인하면 1로 잘못 "
                        "답한다."
                    ),
                    difficulty=_difficulty(p + q),
                )
            )
    return tuple(pool)


def _build_dot_product_scalar_pool() -> tuple[_CountItem, ...]:
    """두 벡터의 내적이 벡터인지 뼈대 풀 — 내적은 늘 스칼라(오개념 정확 표적).

    내적 a·b = a1b1+a2b2는 하나의 수(스칼라)라 벡터가 아니다 — 정답 0. "내적은 벡터"라는 오개념
    (dot-product-is-vector)은 1로 답해 fail. (a1,a2,b1,b2) 순회·conditions dedup.
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for a1 in range(1, 4):
        for a2 in range(1, 4):
            for b1 in range(1, 4):
                for b2 in range(1, 4):
                    conditions = f"{a1},{a2},{b1},{b2}"
                    if conditions in seen:
                        continue
                    seen.add(conditions)
                    pool.append(
                        _CountItem(
                            conditions=conditions,
                            answer_kind="dot_product_scalar",
                            answer_str="0",
                            misc_str="1",
                            question_text=(
                                f"두 벡터 a = ({a1}, {a2}), b = ({b1}, {b2}) 의 내적 a·b 가 "
                                "벡터이면 1, 스칼라(수)이면 0을 쓰시오."
                            ),
                            answer_explanation=(
                                # 보조사는 수 읽기 받침 판별 — '= 5 은' 류 결함 교정(S3-12).
                                f"내적 a·b = {a1}·{b1} + {a2}·{b2} = {a1 * b1 + a2 * b2} "
                                f"{eun_neun(str(a1 * b1 + a2 * b2))} "
                                "하나의 수(스칼라)라 벡터가 아니다 — 0이다. 내적을 벡터로 여기면 "
                                "1로 잘못 답한다."
                            ),
                            difficulty=_difficulty(a1 + a2 + b1 + b2),
                        )
                    )
    return tuple(pool)


def _build_inequality_direction_pool() -> tuple[_CountItem, ...]:
    """음수 계수 일차부등식 해의 방향 뼈대 풀 — 부호 뒤집힘(오개념 정확 표적).

    -a·x < b(a>0)는 음수 -a로 나누면 부호가 뒤집혀 x > -b/a(방향 1)이고, -a·x > b는 x < -b/a
    (방향 0)다. "음수 곱해도 부호 그대로"라는 오개념(sign-flip-in-inequality)은 방향을 반대로 답해
    fail. (a,b,연산자) 순회. 답은 방향 판정(0/1)이라 SymPy solveset으로 독립 검증.
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for op, correct in (("<", "1"), (">", "0")):
        for a in range(2, 7):
            for b in range(1, 9):
                conditions = f"-{a}*x {op} {b}"
                if conditions in seen:
                    continue
                seen.add(conditions)
                misc = "0" if correct == "1" else "1"
                pool.append(
                    _CountItem(
                        conditions=conditions,
                        answer_kind="inequality_direction",
                        answer_str=correct,
                        misc_str=misc,
                        question_text=(
                            f"부등식 -{a}x {op} {b} 의 해가 x > (어떤 수) 꼴이면 1, "
                            "x < (어떤 수) 꼴이면 0을 쓰시오."
                        ),
                        answer_explanation=(
                            # 부사격 조사는 수 읽기 받침 판별 — '-3로' 류 결함 교정(S3-12).
                            f"음수 -{a}{euro_ro(str(-a))} 양변을 나누면 부등호 방향이 뒤집힌다 — "
                            + (
                                "해는 x > (어떤 수) 꼴이라 1이다"
                                if correct == "1"
                                else "해는 x < (어떤 수) 꼴이라 0이다"
                            )
                            + ". 음수를 곱·나눗셈해도 부호가 그대로라고 여기면 방향을 반대로 "
                            "답해 틀린다."
                        ),
                        difficulty=_difficulty(a + b),
                    )
                )
    return tuple(pool)


def _build_root_loss_count_pool() -> tuple[_CountItem, ...]:
    """ax²=bx 형태 방정식의 서로 다른 실근 개수 뼈대 풀 — 양변 x 나눗셈 근 손실(오개념 정확 표적).

    ax²=bx는 이항해 x(ax-b)=0으로 인수분해하면 x=0·x=b/a 두 실근을 가진다(b≥1이라 서로 다름). 정답
    2·오개념 오답 1. "양변을 x로 나눠 x=b/a만"이라는 오개념(root-loss-by-dividing)은 x=0을 잃어 1로
    답해 fail. conditions는 ax²-bx=0 방정식이라 `verify_real_root_count`(kind=root_loss_count)가 근
    개수로 검증한다. (a,b) 기약쌍만 순회해 monic 정규형 signature 충돌을 원천 차단(b/a 유일).
    """
    pool: list[_CountItem] = []
    seen: set[str] = set()
    for a in range(1, 6):
        for b in range(1, 10):
            if gcd(a, b) != 1:
                continue  # 기약쌍만 — 정규형 x²-(b/a)x signature 유일(dedup 충돌 0).
            conditions = f"{a}*x**2 - {b}*x = 0"
            if conditions in seen:
                continue
            seen.add(conditions)
            lhs = f"{a}x^2" if a > 1 else "x^2"
            rhs = f"{b}x" if b > 1 else "x"
            pool.append(
                _CountItem(
                    conditions=conditions,
                    answer_kind="root_loss_count",
                    answer_str="2",
                    misc_str="1",
                    question_text=(f"방정식 {lhs} = {rhs} 의 서로 다른 실근의 개수를 구하시오."),
                    answer_explanation=(
                        f"{lhs} = {rhs} 를 이항하면 x({a}x - {b}) = 0 이라 x = 0 과 "
                        f"x = {b}/{a} 두 실근을 가지므로 2개다. 양변을 x로 나눠 "
                        "x = b/a 하나만 남기면 x = 0 근을 잃어 틀린다."
                    ),
                    difficulty=_difficulty(a + b),
                )
            )
    return tuple(pool)


_POOL_FACTORY = {
    "real_root_count": _build_real_root_count_pool,
    "extremum_count": _build_extremum_count_pool,
    "is_one_to_one": _build_is_one_to_one_pool,
    "geometric_convergence": _build_geometric_convergence_pool,
    "limit_equals_value": _build_limit_equals_value_pool,
    "is_differentiable": _build_is_differentiable_pool,
    "series_converges": _build_series_converges_pool,
    "excluded_point_count": _build_excluded_point_count_pool,
    "mean_equals_median": _build_mean_equals_median_pool,
    "events_independent": _build_events_independent_pool,
    "conditional_equal": _build_conditional_equal_pool,
    "congruent_by_ratio": _build_congruent_by_ratio_pool,
    "dot_product_scalar": _build_dot_product_scalar_pool,
    "inequality_direction": _build_inequality_direction_pool,
    "root_loss_count": _build_root_loss_count_pool,
}


@deterministic_generator
class ConceptualCountMCSkeletonGenerator:
    """개념형 개수/판정 객관식 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `template`(real_root_count/extremum_count/is_one_to_one/geometric_convergence)이 수학 실체를,
    `distractor_codes`가 오답 선지의 오개념 id를 정한다(L4 하드코딩 0·계층 규칙). 각 문항은 오답
    1건만 태깅(filler 미태깅). 풀을 순서대로 소비(소진 시 None). `skip_signatures`로 기존 구조
    건너뜀.
    """

    def __init__(
        self,
        template: CountTemplateKind,
        distractor_codes: Mapping[str, tuple[str, str | None]],
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-count-mc",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        concept_relevance: float = 0.95,
    ) -> None:
        if template not in _POOL_FACTORY:
            raise ValueError(
                f"미지원 template: {template!r} (real_root_count/extremum_count/"
                "is_one_to_one/geometric_convergence)"
            )
        if not distractor_codes:
            raise ValueError("distractor_codes 주입 누락 — 오개념 오답 태깅용 id가 필요하다.")
        self._misconception_id, self._op_code = next(iter(distractor_codes.values()))
        self._template: CountTemplateKind = template
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

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
        while self._index < len(self._pool):
            item = self._pool[self._index]
            self._index += 1
            if self._skip is not None:
                signature = canonical_signature(item.conditions, f"kind:{item.answer_kind}")
                if signature is not None and signature in self._skip:
                    continue
            return self._assemble(spec, item)
        return None

    def _assemble(self, spec: EquivalenceSpec, item: _CountItem) -> CandidateProblem:
        standard_codes = sorted(spec.achievement_standard_codes)
        slug = self._stable_slug(item.question_text, item.answer_str, standard_codes)
        misc_index = _COUNT_CHOICES.index(item.misc_str)

        distractor_map = [
            DistractorEntry(
                choice_index=misc_index,
                misconception_id=self._misconception_id,
                op_code=self._op_code,
            )
        ]
        problem = Problem(
            problem_id=uuid.uuid5(uuid.NAMESPACE_URL, f"whymath:problem:{slug}"),
            slug=slug,
            source_type=SourceType.자체생성,
            curriculum_version=self._curriculum_version,
            valid_from_year=self._valid_from_year,
            subject=self._subject,
            unit_codes=list(self._unit_codes),
            difficulty_overall=item.difficulty,
            question_format=QuestionFormat.객관식,
            answer_format=AnswerFormat.자연수,  # 개수는 비음 정수.
            achievement_standard_codes=standard_codes,
            question_text=item.question_text,
            choices=list(_COUNT_CHOICES),
            answer=item.answer_str,
            answer_explanation=item.answer_explanation,
            distractor_map=distractor_map,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 개념형 개수 MC 스켈레톤 조립(실근/극값 개수 4지선다·오개념 개수 태깅)",
                    "S2-a 수용 게이트(개수 SymPy 독립 검증)",
                    "사람 검수 큐(오개념 귀속 교수학 검수)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=item.conditions,
            answer_map={},  # 개수는 근 대입 아님 — 게이트가 answer_kind로 독립 계산.
            answer_selection=None,
            answer_aggregate=None,
            answer_kind=item.answer_kind,
            solution_steps=None,
            concept_tags=list(self._concept_tags),
        )

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        """결정론 안정 slug — 내용 해시(멱등 upsert 키)."""
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"
