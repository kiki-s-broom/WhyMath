"""대학 미적분학 I 몫의 미분법·연쇄법칙 결정론 스켈레톤 생성기 — W2 Phase1 #6(결정론·LLM 0).

`calculus_product_rule_skeleton_generator`(곱의 미분법)의 형제 — 좌석·게이트·검증 설계를
그대로 재사용한다. 대상 성취기준: `[CALC1-02-03]`(몫의 미분법 — (f/g)'=(f'g−fg')/g²)·
`[CALC1-02-04]`(연쇄법칙 — [f(g(x))]'=f'(g(x))·g'(x)).

**검증 설계**: 형제 생성기와 동일 — Tier1(`l3/verify_answer`)에 `Derivative(...).doit()`로
명시 평가한 조건을 공급한다(미평가 `Derivative`는 sympify가 수치 대입을 못 해 unverifiable).

**몫의 미분법 정수 답 보장(이 생성기 고유 설계)**: f(x)=(ax²+bx+c)/(dx+e)의 도함수
f'(k) = [(2ak+b)(dk+e) − (ak²+bk+c)d] / (dk+e)²는 일반적으로 분수다. 분모가 항상 1이
되도록 **g(k)=dk+e=±1이 되게 e를 역산**한다(e = ±1 − dk) — 그러면 g(k)²=1이라 나눗셈이
항상 정확히 떨어진다(임의 a·b·c에도 정수 답 보장, 나머지 처리·분수 답 회피).

**연쇄법칙 설계**: f(x)=(ax+b)ⁿ(선형 안쪽 함수의 거듭제곱 — 곱·몫 규칙만으로는 풀 수 없어
연쇄법칙이 실제로 필요한 최소 사례). f'(k) = n·a·(ak+b)ⁿ⁻¹, 전 항이 정수라 자동으로 정수 답.

**개념 태깅 공백**: `calculus_product_rule_skeleton_generator` 모듈 docstring과 동일 이유
(대학 원자는 구 437 legacy 개념그래프 밖·크로스워크 경로 없음) — `concept_tags=()`로
정직하게 비워 둔다(가짜 orphan-skip 태그 금지).

**노출 게이팅**: 산출물은 v0(사람 검수 전). AI 검수(Wilson 게이트)는 실 LLM 필요라 이 환경
밖(Kiki 머신)에서만 가능 — 그 전까지 `is_published=False`로 유지.

**고교 축과의 공간 분리(QUAL-07·2026-09-12)**: 몫의 미분법 밴드는 고교 미적분Ⅱ 축
(`highschool_quotient_rule_skeleton_generator`)과 계수 공간이 겹쳐 같은 문항을 만들어 냈다.
지금은 `_quotient_band_admits`(계수 중 최소 하나가 절댓값 4 이상)로 서로소다 — 연쇄법칙
밴드는 구조가 달라((ax+b)ⁿ) 애초에 겹치지 않으므로 손대지 않았다.
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

__all__ = [
    "CalculusChainRuleSkeletonGenerator",
    "CalculusQuotientRuleSkeletonGenerator",
]

_UNIVERSITY_CURRICULUM = Curriculum.REVISION_2022

_TEMPLATES: tuple[str, ...] = (
    "f(x) = {f}일 때, f'({k})의 값을 구하시오.",
    "함수 f(x) = {f}의 도함수 f'(x)에 대하여 f'({k}){eul_k} 구하시오.",
)


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


# ── 몫의 미분법: f(x) = (ax²+bx+c)/(dx+e), g(k)=±1 되도록 e 역산 ─────────────
_QUOT_A_RANGE = tuple(v for v in range(-4, 5) if v != 0)
_QUOT_BC_RANGE = range(-5, 6)
_QUOT_D_RANGE = tuple(v for v in range(-4, 5) if v != 0)
_QUOT_K_RANGE = range(-3, 4)
_QUOT_POOL_TARGET = 260

# 고교 미적분Ⅱ 축(`highschool_quotient_rule_skeleton_generator`)과의 **서로소 분리**
# (QUAL-07·2026-09-12). 두 생성기는 계수 범위가 글자 그대로 같았고 시드까지 같아서
# (`random.Random(20260807)`) 이 풀 260개가 고교 풀 300개의 **부분집합**이었다 — 두 코퍼스가
# 수학 실체 138건·발문 동일 71건을 공유한 근본 원인이다(실측). 문항만 은퇴시키면 재생성 때
# 재발하므로 공간 자체를 갈랐다: 고교 축은 계수 4종 전부 절댓값 3 이하만 쓰고, 대학 축은
# **최소 하나가 절댓값 4 이상**인 조합만 쓴다. 두 술어는 서로의 부정이라 교집합이 정의상
# 공집합이며, 이 분할은 난이도 표기(대학 3.9 > 고교 3.7)에 구조적 실체도 준다 — 이전에는
# 같은 문항에 다른 숫자를 붙인 것뿐이었다.
# 전수 열거 동결: `tests/backend/l3/equivalent/test_quotient_rule_space_disjointness.py`.
_QUOT_MIN_LARGE_ABS = 4


def _quotient_band_admits(a: int, b: int, c: int, d: int) -> bool:
    """대학 축 몫의 미분법이 받는 계수 조합인가 — 계수 4종 중 최소 하나가 절댓값 4 이상.

    `e`는 검사하지 않는다: `e = g(k) − d·k`로 *역산되는 종속값*이라 자유 파라미터가 아니고,
    (a,b,c,d,k,g) 키가 (a,b,c,d,e,k)를 유일하게 결정한다(그래서 키가 서로소면 발문·조건식도
    서로소다).
    """
    return max(abs(a), abs(b), abs(c), abs(d)) >= _QUOT_MIN_LARGE_ABS


@dataclass(frozen=True, slots=True)
class _QuotientSkeleton:
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


def _build_quotient_pool() -> tuple[_QuotientSkeleton, ...]:
    """시드 샘플 풀 — 조합공간이 크므로(product_rule 관례 계승) 전수열거 대신 시드 샘플링."""
    rng = random.Random(20260807)
    pool: list[_QuotientSkeleton] = []
    seen: set[tuple[int, ...]] = set()
    attempts = 0
    while len(pool) < _QUOT_POOL_TARGET and attempts < _QUOT_POOL_TARGET * 30:
        attempts += 1
        a = rng.choice(_QUOT_A_RANGE)
        b = rng.choice(_QUOT_BC_RANGE)
        c = rng.choice(_QUOT_BC_RANGE)
        d = rng.choice(_QUOT_D_RANGE)
        k = rng.choice(_QUOT_K_RANGE)
        g_sign = rng.choice((1, -1))
        if not _quotient_band_admits(a, b, c, d):
            continue  # 고교 축 공간(전 계수 |·|≤3)과의 서로소 유지 — QUAL-07.
        key = (a, b, c, d, k, g_sign)
        if key in seen:
            continue
        seen.add(key)
        pool.append(_QuotientSkeleton(a=a, b=b, c=c, d=d, k=k, g_sign=g_sign))
    random.Random(20260807 + 1).shuffle(pool)
    return tuple(pool)


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _answer_format(value: int) -> AnswerFormat:
    return AnswerFormat.자연수 if value > 0 else AnswerFormat.실수


class CalculusQuotientRuleSkeletonGenerator:
    """결정론 스켈레톤 생성기 — 대학 미적분학 I 몫의 미분법(`EquivalentProblemGenerator` 좌석).

    `CalculusProductRuleSkeletonGenerator`와 동일 관례: `run_equivalent_generation`을
    `signature_index=None`으로 호출해야 한다(구조 dedup이 해값 기반이라 서로 다른 조합이
    같은 f'(k) 값을 내면 오탐). 밴드 분리 불필요(문제 유형 1종)라 필터 인자 없음.
    """

    def __init__(
        self,
        *,
        skip_conditions: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-calc1-quotient-rule",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = _UNIVERSITY_CURRICULUM,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("CALC1-QUOTIENT-RULE",),
        concept_tags: Sequence[ConceptTag] = (),
    ) -> None:
        self._pool = _build_quotient_pool()
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

    def _assemble(self, spec: EquivalenceSpec, skeleton: _QuotientSkeleton) -> CandidateProblem:
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
            difficulty_overall=3.9,  # 몫 규칙+분모 처리 — product_rule(3.8)보단 약간 무겁다.
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
                    "AI 검수 게이트 대기(Kiki 머신·실 LLM 필요 — 미통과 시 is_published=False)",
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


# ── 연쇄법칙: f(x) = (ax+b)ⁿ ──────────────────────────────────────────────────
_CHAIN_A_RANGE = tuple(v for v in range(-4, 5) if v != 0)
_CHAIN_B_RANGE = range(-5, 6)
_CHAIN_N_RANGE = (2, 3, 4, 5)
_CHAIN_K_RANGE = range(-3, 4)
_CHAIN_POOL_TARGET = 260


@dataclass(frozen=True, slots=True)
class _ChainSkeleton:
    """연쇄법칙 뼈대 — f(x)=(ax+b)ⁿ. 곱·몫 규칙만으로는 못 풀어 연쇄법칙이 실제로 필요하다."""

    a: int
    b: int
    n: int
    k: int

    @property
    def condition(self) -> str:
        lin = f"{self.a}*x + {self.b}"
        return f"Derivative(({lin})**{self.n}, x).doit().subs(x, {self.k}) = y"

    @property
    def result(self) -> int:
        """독립 재계산(연쇄법칙 전개식) — f'(k) = n·a·(ak+b)ⁿ⁻¹, 전 항 정수라 자동 정수 답."""
        inner_at_k = self.a * self.k + self.b
        return self.n * self.a * int(inner_at_k ** (self.n - 1))

    @property
    def display_f(self) -> str:
        """f(x)의 사람이 읽는 표기('(2x - 3)^4') — 계수 1 생략."""
        return f"({_linear_display(self.a, self.b)})^{self.n}"


def _build_chain_pool() -> tuple[_ChainSkeleton, ...]:
    """시드 샘플 풀 — 조합공간이 크므로(product_rule 관례 계승) 전수열거 대신 시드 샘플링."""
    rng = random.Random(20260807 + 2)
    pool: list[_ChainSkeleton] = []
    seen: set[tuple[int, ...]] = set()
    attempts = 0
    while len(pool) < _CHAIN_POOL_TARGET and attempts < _CHAIN_POOL_TARGET * 30:
        attempts += 1
        a = rng.choice(_CHAIN_A_RANGE)
        b = rng.choice(_CHAIN_B_RANGE)
        n = rng.choice(_CHAIN_N_RANGE)
        k = rng.choice(_CHAIN_K_RANGE)
        key = (a, b, n, k)
        if key in seen:
            continue
        seen.add(key)
        pool.append(_ChainSkeleton(a=a, b=b, n=n, k=k))
    random.Random(20260807 + 3).shuffle(pool)
    return tuple(pool)


class CalculusChainRuleSkeletonGenerator:
    """결정론 스켈레톤 생성기 — 대학 미적분학 I 연쇄법칙(`EquivalentProblemGenerator` 좌석).

    형제 생성기와 동일 관례(`signature_index=None` 배치 호출·밴드 분리 불필요).
    """

    def __init__(
        self,
        *,
        skip_conditions: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-calc1-chain-rule",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = _UNIVERSITY_CURRICULUM,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("CALC1-CHAIN-RULE",),
        concept_tags: Sequence[ConceptTag] = (),
    ) -> None:
        self._pool = _build_chain_pool()
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

    def _assemble(self, spec: EquivalenceSpec, skeleton: _ChainSkeleton) -> CandidateProblem:
        template = _TEMPLATES[self._index % len(_TEMPLATES)]
        question_text = template.format(
            f=skeleton.display_f, k=skeleton.k, eul_k=eul_reul(str(skeleton.k))
        )
        answer_text = str(skeleton.result)
        explanation = (
            f"연쇄법칙에 따라 바깥 함수를 미분한 값에 안쪽 함수의 도함수를 곱해 "
            f"x = {skeleton.k}에서 계산하면 f'({skeleton.k})의 값은 {answer_text}이다."
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
            difficulty_overall=3.8,  # 대학 도입 개념(합성 규칙 적용) — product_rule과 동급.
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
                    "결정론 스켈레톤 조립(선형 안쪽 함수·거듭제곱 n→연쇄법칙 계산)",
                    "S2-a 수용 게이트(Tier1 SymPy 미분 평가 검산)",
                    "AI 검수 게이트 대기(Kiki 머신·실 LLM 필요 — 미통과 시 is_published=False)",
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
