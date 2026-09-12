"""고등 미적분Ⅱ 몫의 미분법 결정론 스켈레톤 생성기 — W2 Phase2 #5·최종(결정론·LLM 0).

`calculus_chain_quotient_rule_skeleton_generator`(대학 CALC1 축·`[CALC1-02-03]`)의 몫의
미분법 설계를 K-12 고등학교 미적분Ⅱ 축(`[12미적Ⅱ-02-04]`)으로 재적용한다 — 규칙 자체는
동일(둘 다 (f/g)'=(f'g−fg')/g²)하고 성취기준 축이 다르다. `[12미적Ⅱ-02-04]`가 0건이었다 —
이 생성기가 첫 코퍼스를 확보한다.

**정정(QUAL-07·2026-09-12)**: 초판은 설계를 "그대로 재적용"해 파라미터 공간까지 글자 그대로
같았고(시드도 동일), 그 결과 두 코퍼스가 같은 문항을 공유했다(수학 실체 138건·발문 동일
71건 — 실측). 지금은 계수 공간이 대학 축과 **서로소**다(아래 `_MAX_ABS_COEFFICIENT` 주석).

**대학 축과의 차이(중요)**: 대학 축 형제는 대학 원자가 구 437 legacy 개념그래프 경로로
해석되지 않아 `concept_tags=()`로 비워야 했지만(정직 회계), 이 K-12 개념(`H:12미적Ⅱ02-04`
— 몫의 미분법)은 legacy 437 공간에 실존한다 — 정상적으로 태깅한다.

**검증 설계**: 형제 생성기와 동일 — Tier1(`l3/verify_answer`)에 `Derivative(...).doit()`로
명시 평가한 조건을 공급한다. f(x)=(ax²+bx+c)/(dx+e)에서 분모 g(k)=dk+e가 항상 ±1이 되도록
e를 역산 구성해(e=±1−dk) 나눗셈이 항상 정확히 떨어지는 정수 답을 보장한다(임의 a·b·c에도
분수 답 회피 — 형제 생성기 g(k)=±1 트릭 재사용).

범위(v1): 이차식/일차식의 몫만. 삼각함수·지수함수가 낀 몫의 미분법은 후속.

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지·L1(ConceptTag)만 import(L4
참조 0). 난이도는 지역 함수(공유 difficulty.py 불침범·도메인 분담 관례 계승).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.lang.josa import eul_reul
from whymath_backend.schema.enums import (
    AnswerFormat,
    Curriculum,
    GenerationType,
    LicenseType,
    QuestionFormat,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem
from whymath_backend.schema.provenance import ContentProvenance

__all__ = ["HighschoolQuotientRuleSkeletonGenerator"]

_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12미적Ⅱ02-04", role="PRIMARY", relevance=0.95),
)

_TEMPLATES: tuple[str, ...] = (
    "f(x) = {f}일 때, f'({k})의 값을 구하시오.",
    "함수 f(x) = {f}의 도함수 f'(x)에 대하여 f'({k}){eul_k} 구하시오.",
)

# ── 파라미터 공간: 대학 CALC1 몫의 미분법 축과 **서로소**(QUAL-07·2026-09-12) ──────────
# 두 생성기는 원래 계수 범위가 글자 그대로 같았고 시드까지 같아(`random.Random(20260807)`),
# 대학 몫의 미분법 풀 260개가 이 풀 300개의 **부분집합**이었다(실측). 그 결과 두 코퍼스가
# 수학 실체 138건·발문 동일 71건을 공유했다. 문항만 은퇴시키면 재생성 때 그대로 재발하므로
# 공간 자체를 갈랐다 —
#   · 고교 미적분Ⅱ(여기, 난이도 3.7): 계수 4종 전부 절댓값 3 이하(교과서 도입 수준).
#   · 대학 CALC1(`calculus_chain_quotient_rule_skeleton_generator`, 난이도 3.9):
#     계수 4종 중 **최소 하나가 절댓값 4 이상**(`_quotient_band_admits`).
# 두 술어는 서로의 부정이므로 교집합이 정의상 공집합이다(전수 열거 동결:
# `tests/backend/l3/equivalent/test_quotient_rule_space_disjointness.py`).
# 대입점 `k`는 좁히지 않는다 — 음수 대입 연습은 고교 축에서도 성취기준 요구다.
_MAX_ABS_COEFFICIENT = 3
_A_RANGE = tuple(v for v in range(-_MAX_ABS_COEFFICIENT, _MAX_ABS_COEFFICIENT + 1) if v != 0)
_BC_RANGE = range(-_MAX_ABS_COEFFICIENT, _MAX_ABS_COEFFICIENT + 1)
_D_RANGE = tuple(v for v in range(-_MAX_ABS_COEFFICIENT, _MAX_ABS_COEFFICIENT + 1) if v != 0)
_K_RANGE = range(-3, 4)
_POOL_TARGET = 300


def _term(coefficient: int, symbol: str, *, lead: bool = False) -> str:
    """계수 하나를 사람이 읽는 항으로 — 부호·계수 1 생략 규칙(형제 생성기 독립 재구현·
    private 모듈 경계 비침범, 신규 규칙 발명 0)."""
    sign = "-" if coefficient < 0 else ("" if lead else "+")
    magnitude = abs(coefficient)
    body = symbol if magnitude == 1 and symbol else f"{magnitude}{symbol}"
    joint = " " if sign and not lead else ""
    return f"{sign}{joint}{body}" if lead else f"{sign} {body}"


def _quad_display(a: int, b: int, c: int) -> str:
    """이차식 표기('3x^2 - 7x + 4') — 0항 생략·계수 1 생략."""
    parts = [_term(a, "x^2", lead=True)]
    if b:
        parts.append(_term(b, "x"))
    if c:
        parts.append(_term(c, ""))
    return " ".join(parts)


def _linear_display(d: int, e: int) -> str:
    """일차식 표기('2x - 3') — 계수 1 생략."""
    parts = [_term(d, "x", lead=True)]
    if e:
        parts.append(_term(e, ""))
    return " ".join(parts)


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """몫의 미분법 뼈대 — f(x)=(ax²+bx+c)/(dx+e), g(k)=dk+e=±1(역산 보장). 단일 진실 원천."""

    a: int
    b: int
    c: int
    d: int
    k: int
    g_sign: int  # g(k) = +1 또는 -1

    @property
    def e(self) -> int:
        """e = g(k) − d·k (g(k)=±1이 되도록 역산 — 분모 항상 정확히 나누어떨어짐 보장)."""
        return self.g_sign - self.d * self.k

    @property
    def condition(self) -> str:
        quad = f"{self.a}*x**2 + {self.b}*x + {self.c}"
        lin = f"{self.d}*x + {self.e}"
        return f"Derivative(({quad}) / ({lin}), x).doit().subs(x, {self.k}) = y"

    @property
    def result(self) -> int:
        """독립 재계산(몫의 미분법 전개식, g(k)²=1이라 나눗셈 없이 정수) — 생성기 자체 검산.

        f'(k) = [(2ak+b)·g(k) − (ak²+bk+c)·d] / g(k)² = (2ak+b)·g(k) − (ak²+bk+c)·d
        (g(k)²=1 항등 — 이중 교차검증: Tier1도 독립적으로 SymPy 미분을 재계산한다).
        """
        a, b, c, d, k, g = self.a, self.b, self.c, self.d, self.k, self.g_sign
        f1_prime_at_k = 2 * a * k + b
        f1_at_k = a * k * k + b * k + c
        return f1_prime_at_k * g - f1_at_k * d

    @property
    def display_f(self) -> str:
        """f(x)의 사람이 읽는 표기('(3x^2 - 7x + 4)/(2x - 1)') — 0항·계수 1 생략."""
        return f"({_quad_display(self.a, self.b, self.c)})/({_linear_display(self.d, self.e)})"


def _build_pool() -> tuple[_Skeleton, ...]:
    """시드 샘플 풀 — 조합공간이 크므로(형제 생성기 관례 계승) 전수열거 대신 시드 샘플링."""
    rng = random.Random(20260807)
    pool: list[_Skeleton] = []
    seen: set[tuple[int, ...]] = set()
    attempts = 0
    while len(pool) < _POOL_TARGET and attempts < _POOL_TARGET * 30:
        attempts += 1
        a = rng.choice(_A_RANGE)
        b = rng.choice(_BC_RANGE)
        c = rng.choice(_BC_RANGE)
        d = rng.choice(_D_RANGE)
        k = rng.choice(_K_RANGE)
        g_sign = rng.choice((1, -1))
        key = (a, b, c, d, k, g_sign)
        if key in seen:
            continue
        seen.add(key)
        pool.append(_Skeleton(a=a, b=b, c=c, d=d, k=k, g_sign=g_sign))
    random.Random(20260807 + 1).shuffle(pool)
    return tuple(pool)


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _answer_format(value: int) -> AnswerFormat:
    return AnswerFormat.자연수 if value > 0 else AnswerFormat.실수


class HighschoolQuotientRuleSkeletonGenerator:
    """결정론 스켈레톤 생성기 — 고등 미적분Ⅱ 몫의 미분법(`EquivalentProblemGenerator` 좌석).

    `CalculusQuotientRuleSkeletonGenerator`(대학 축)와 동일 관례: `run_equivalent_generation`
    을 `signature_index=None`으로 호출해야 한다(구조 dedup이 해값 기반이라 서로 다른 조합이
    같은 f'(k) 값을 내면 오탐). 밴드 분리 불필요(문제 유형 1종)라 필터 인자 없음.
    """

    def __init__(
        self,
        *,
        skip_conditions: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-hs-quotient-rule",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("HS-CALC2-QUOTIENT-RULE",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_pool()
        self._index = 0
        self._skip = skip_conditions
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            condition = skeleton.condition
            if self._skip is not None and condition in self._skip:
                continue
            return self._assemble(spec, skeleton)
        return None

    def _assemble(self, spec: EquivalenceSpec, skeleton: _Skeleton) -> CandidateProblem:
        template = _TEMPLATES[self._index % len(_TEMPLATES)]
        question_text = template.format(
            f=skeleton.display_f, k=skeleton.k, eul_k=eul_reul(str(skeleton.k))
        )
        answer_text = str(skeleton.result)
        # 위생 게이트 오탐 회피 — 등호 없는 순수 서술형 결론(형제 생성기 관례 그대로).
        explanation = (
            f"몫의 미분법에 따라 분자와 분모를 각각 미분해 조합한 뒤 x = {skeleton.k}에서 "
            f"계산하면 f'({skeleton.k})의 값은 {answer_text}이다."
        )
        condition = skeleton.condition
        standard_codes = sorted(spec.achievement_standard_codes)
        slug = _stable_slug(self._slug_prefix, question_text, answer_text, standard_codes)

        problem = Problem(
            problem_id=uuid.uuid5(uuid.NAMESPACE_URL, f"whymath:problem:{slug}"),
            slug=slug,
            source_type=SourceType.자체생성,
            curriculum_version=self._curriculum_version,
            valid_from_year=self._valid_from_year,
            subject=self._subject,
            unit_codes=list(self._unit_codes),
            difficulty_overall=3.7,  # 고3 미적분Ⅱ 도입 개념(몫 규칙+분모 처리).
            question_format=QuestionFormat.단답형,
            answer_format=_answer_format(skeleton.result),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=explanation,
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 스켈레톤 조립(다항식 계수·g(k)=±1 역산→몫의 미분법 계산)",
                    "S2-a 수용 게이트(Tier1 SymPy 미분 평가 검산)",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,
            answer_map={"y": answer_text},
            solution_steps=None,
            concept_tags=list(self._concept_tags),
        )
