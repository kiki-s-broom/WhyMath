"""고등 경우의 수 — 합의 법칙·곱의 법칙·순열 스켈레톤 생성기 — W2 Phase1 #7(결정론·LLM 0).

[10공수1-03-01](합의 법칙·곱의 법칙)·[10공수1-03-02](순열)이 0건이었다 — 이 생성기가 두
성취기준의 첫 코퍼스를 확보한다. `finite_probability_skeleton_generator`(확률 도메인)와
인접하지만 검증 방식은 다르다 — 확률 생성기는 전용 유한 표본공간 열거기(`l3/finite_
probability.py`)를 쓰지만, 경우의 수(합·곱의 법칙·순열)는 닫힌 정수 공식(덧셈·곱셈·nPr)
이라 **다른 모든 결정론 생성기와 동일한 SymPy sympify 범용 검산기**로 충분하다(도메인
전용 검증기 신설 0 — quad_ineq·sequence_sigma 계열과 동형 설계).

두 클래스:
- `SumProductPrincipleSkeletonGenerator` — `kind`(sum/product) 필터로 밴드 분리. sum:
  동시에 일어날 수 없는 두 사건(각 m·n가지)중 하나를 택하는 경우의 수 = m+n. product:
  연이어 일어나는 두 사건(각 m·n가지)의 경우의 수 = m×n.
- `PermutationSkeletonGenerator` — 서로 다른 n개에서 r개를 택해 나열하는 순열의 수
  nPr = n!/(n−r)!. SymPy `factorial()`이 조건식에 그대로 들어가 검증기가 재계산한다
  (사전 스파이크로 `factorial(n)/factorial(n-r)` 조건이 Tier1에서 정확히 pass/fail
  갈리는 것을 확인 — 신규 함수 지원 실측).

⚠️ `kind` 필터 필수(direction/operation 필터 관례 계승) — 미지정이면 두 밴드가 고정 시드
풀을 처음부터 재생해 같은 뼈대를 중복 방출한다(2026-08-05 elementary_addsub 사고).

범위(v1): 정수 값·소규모 n(≤9, 인수 폭발 방지)만. 원순열·중복순열·조합·이항정리는 후속.

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지·L1(ConceptTag)만 import(L4
참조 0). 난이도는 지역 함수(공유 difficulty.py 불침범·도메인 분담 관례 계승).
"""

from __future__ import annotations

import hashlib
import math
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.generator import CandidateProblem, deterministic_generator
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
    "PermutationSkeletonGenerator",
    "SumProductKind",
    "SumProductPrincipleSkeletonGenerator",
]

_POOL_SEED = 20260807

_SUM_PRODUCT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="HK39", role="PRIMARY", relevance=0.95),
)
_PERMUTATION_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="HK40", role="PRIMARY", relevance=0.95),
)


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _natural_answer_format(answer: int) -> AnswerFormat:
    """정답 형태 — 경우의 수는 항상 양의 정수(v1 전건)."""
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


# ── 합의 법칙·곱의 법칙 ────────────────────────────────────────────────────────
SumProductKind = Literal["sum", "product"]

_M_RANGE = range(2, 10)
_N_RANGE = range(2, 10)

_SUM_TEMPLATES: tuple[str, ...] = (
    "두 가지 방법 A, B가 있는데 A를 택하는 경우의 수는 {m}가지, B를 택하는 경우의 수는 "
    "{n}가지이다. A, B가 동시에 일어날 수 없을 때, A 또는 B를 택하는 경우의 수를 구하시오.",
)
_PRODUCT_TEMPLATES: tuple[str, ...] = (
    "사건 A가 일어나는 경우의 수는 {m}가지이고, 그와 상관없이 사건 B가 일어나는 경우의 수는 "
    "{n}가지이다. A, B가 연이어 일어나는 경우의 수를 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _SumProductSkeleton:
    """합·곱의 법칙 뼈대 — kind·m·n. sum: m+n / product: m×n. 단일 진실 원천."""

    kind: SumProductKind
    m: int
    n: int

    @property
    def answer(self) -> int:
        return self.m + self.n if self.kind == "sum" else self.m * self.n

    @property
    def condition(self) -> str:
        op = "+" if self.kind == "sum" else "*"
        return f"x - ({self.m} {op} {self.n}) = 0"

    @property
    def difficulty(self) -> float:
        # 초입 개념(단순 덧셈/곱셈 1스텝) — 경우의 수 도메인 첫 착점이라 낮게 잡는다.
        difficulty = 1.7 if self.kind == "sum" else 1.9
        if max(self.m, self.n) >= 7:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_sum_product_pool(kind: SumProductKind | None = None) -> tuple[_SumProductSkeleton, ...]:
    """결정론 합·곱의 법칙 뼈대 풀 — kind×m×n 열거·구조 키 자연 유일·고정 셔플."""
    kinds: tuple[SumProductKind, ...] = ("sum", "product") if kind is None else (kind,)
    pool: list[_SumProductSkeleton] = []
    for k in kinds:
        for m in _M_RANGE:
            for n in _N_RANGE:
                pool.append(_SumProductSkeleton(kind=k, m=m, n=n))
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _sum_product_explanation(skeleton: _SumProductSkeleton) -> str:
    """합·곱의 법칙 해설 — 규칙 적용을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    if skeleton.kind == "sum":
        return (
            "두 사건이 동시에 일어나지 않으므로 합의 법칙에 따라 각 경우의 수를 더하면 "
            f"{skeleton.answer} 이다."
        )
    return (
        "두 사건이 연이어 일어나므로 곱의 법칙에 따라 각 경우의 수를 곱하면 "
        f"{skeleton.answer} 이다."
    )


@deterministic_generator
class SumProductPrincipleSkeletonGenerator:
    """합·곱의 법칙 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    `kind`(sum/product) 필터로 밴드를 분리한다(direction/operation 필터 관례 계승 — 필터
    없이 밴드별 인스턴스를 만들면 고정 시드 풀이 처음부터 재생돼 같은 뼈대를 중복 방출한다).
    """

    def __init__(
        self,
        *,
        kind: SumProductKind | None = None,
        slug_prefix: str = "wm-sumprod",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("SUM-PRODUCT-PRINCIPLE",),
        concept_tags: Sequence[ConceptTag] = _SUM_PRODUCT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_sum_product_pool(kind)
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 합·곱의 법칙 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _SumProductSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        templates = _SUM_TEMPLATES if skeleton.kind == "sum" else _PRODUCT_TEMPLATES
        question_text = templates[self._index % len(templates)].format(m=skeleton.m, n=skeleton.n)
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
            difficulty_overall=skeleton.difficulty,
            question_format=QuestionFormat.단답형,
            answer_format=_natural_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_sum_product_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 합·곱의 법칙 스켈레톤 조립(m·n→덧셈/곱셈)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=skeleton.condition,
            answer_map={"x": answer_text},
            answer_selection="unique",
            solution_steps=[
                f"{skeleton.m} {'+' if skeleton.kind == 'sum' else '*'} {skeleton.n}",
                answer_text,
            ],
            concept_tags=list(self._concept_tags),
        )


# ── 순열: nPr = n!/(n−r)! ─────────────────────────────────────────────────────
_PERM_TEMPLATES: tuple[str, ...] = (
    "서로 다른 {n}개에서 {r}개를 택하여 일렬로 나열하는 경우의 수를 구하시오.",
    "서로 다른 {n}명 중에서 {r}명을 뽑아 순서를 정해 세우는 방법의 수를 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _PermutationSkeleton:
    """순열 뼈대 — 전체 개수 n·택하는 개수 r(1≤r≤n). nPr = n!/(n−r)!. 단일 진실 원천."""

    n: int
    r: int

    @property
    def answer(self) -> int:
        return math.factorial(self.n) // math.factorial(self.n - self.r)

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − n!/(n−r)! = 0'(factorial 그대로 공급·독립 재계산)."""
        return f"x - (factorial({self.n})/factorial({self.n} - {self.r})) = 0"

    @property
    def difficulty(self) -> float:
        # QUAD-EQ(base 2.0) 대비: 공식 1개 직대입이나 계승 개념이 처음이라 비슷한 수준.
        difficulty = 2.0
        if self.n >= 7:
            difficulty += 0.2
        if self.r >= 4:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_permutation_pool() -> tuple[_PermutationSkeleton, ...]:
    """결정론 순열 뼈대 풀 — n×r(1≤r≤n) 열거·구조 키 자연 유일·고정 셔플.

    n≤9로 제한(계승 폭발 방지 — 9!=362880이 이미 v1 상한). 답 기준이 아니라 (n,r) 튜플로
    자연히 유일(다른 (n,r)이 같은 nPr 값을 내는 경우가 드물지만, 있어도 정상 — 형제 좌표
    기하 생성기 관례 계승).
    """
    pool = [_PermutationSkeleton(n=n, r=r) for n in range(3, 10) for r in range(1, n + 1)]
    random.Random(_POOL_SEED + 1).shuffle(pool)
    return tuple(pool)


def _permutation_explanation(skeleton: _PermutationSkeleton) -> str:
    """순열 해설 — nPr 공식 사용을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    return (
        "서로 다른 것을 순서를 구별해 뽑아 나열하는 경우의 수는 순열 공식으로 구하므로, "
        f"구하는 경우의 수는 {skeleton.answer} 이다."
    )


@deterministic_generator
class PermutationSkeletonGenerator:
    """순열 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    풀(구조 키 유일)을 순서대로 소비(소진 시 None).
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-perm",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("PERMUTATION",),
        concept_tags: Sequence[ConceptTag] = _PERMUTATION_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_permutation_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 순열 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _PermutationSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        template = _PERM_TEMPLATES[self._index % len(_PERM_TEMPLATES)]
        question_text = template.format(n=skeleton.n, r=skeleton.r)
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
            difficulty_overall=skeleton.difficulty,
            question_format=QuestionFormat.단답형,
            answer_format=_natural_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_permutation_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 순열 스켈레톤 조립(n·r→nPr=n!/(n-r)! 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=skeleton.condition,
            answer_map={"x": answer_text},
            answer_selection="unique",
            solution_steps=[
                f"factorial({skeleton.n})/factorial({skeleton.n - skeleton.r})",
                answer_text,
            ],
            concept_tags=list(self._concept_tags),
        )
