"""고등 경우의 수 — 중복조합·이항정리 계수 스켈레톤 생성기 — W2 Phase3 #2(결정론·LLM 0).

`permutation_combination_skeleton_generator`(S4-33, [10공수1-03-01]·[10공수1-03-02])가 명시
후속으로 남긴 범위("원순열·중복순열·조합·이항정리는 후속") 중 [12확통01-02](중복조합)·
[12확통01-03](이항정리)를 착수한다 — 두 성취기준의 첫 코퍼스다.

두 클래스 모두 닫힌 정수 공식(조합 계열)이라 순열 생성기와 **동일한 SymPy `factorial()`
범용 검산기**로 충분하다(도메인 전용 검증기 신설 0 — 형제 관례 계승).

- `RepeatedCombinationSkeletonGenerator` — 서로 다른 n종에서 중복을 허락해 r개를 택하는
  중복조합의 수 H(n,r) = C(n+r-1,r) = (n+r-1)!/(r!(n-1)!).
- `BinomialCoefficientSkeletonGenerator` — (x+y)^n 전개식에서 x^(n-r)y^r 항의 계수(이항정리)
  = C(n,r) = n!/(r!(n-r)!). r을 1..n-1로 제한(양 끝 r=0/r=n은 계수가 항상 1인 자명 항이라
  제외 — 교육적으로 의미 있는 항만 출제).

concept_src_id(legacy 437 개념그래프 `source_id` 필드 실측 확인 — 2026-08-07):
  H:12확통01-02(중복조합)=[12확통01-02] · H:12확통01-03(이항정리)=[12확통01-03].

범위(v1): 정수 값·소규모 n(중복조합 n≤8·이항정리 n≤12, 인수 폭발 방지)만.

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
    "BinomialCoefficientSkeletonGenerator",
    "RepeatedCombinationSkeletonGenerator",
]

_POOL_SEED = 20260807

_REPEATED_COMBINATION_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12확통01-02", role="PRIMARY", relevance=0.95),
)
_BINOMIAL_COEFFICIENT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12확통01-03", role="PRIMARY", relevance=0.95),
)


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _natural_answer_format(answer: int) -> AnswerFormat:
    """정답 형태 — 경우의 수·이항계수는 항상 양의 정수(v1 전건)."""
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


def _power_display(symbol: str, exponent: int) -> str:
    """거듭제곱 표기 — 지수 1은 생략(예 'x^3'·'y')."""
    return symbol if exponent == 1 else f"{symbol}^{exponent}"


# ── 중복조합: H(n,r) = C(n+r-1,r) = (n+r-1)!/(r!(n-1)!) ─────────────────────────
_REPEATED_COMBINATION_N_RANGE = range(2, 9)
_REPEATED_COMBINATION_R_RANGE = range(1, 9)
_REPEATED_COMBINATION_TEMPLATES: tuple[str, ...] = (
    "서로 다른 종류의 사탕 {n}가지 중에서 중복을 허락하여 {r}개를 택하는 경우의 수를 " "구하시오.",
    "{n}가지 종류의 음료 중에서 중복을 허락하여 {r}병을 고르는 경우의 수를 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _RepeatedCombinationSkeleton:
    """중복조합 뼈대 — 종류 수 n·택하는 개수 r. H(n,r) = (n+r-1)!/(r!(n-1)!). 단일 진실 원천."""

    n: int
    r: int

    @property
    def answer(self) -> int:
        return math.factorial(self.n + self.r - 1) // (
            math.factorial(self.r) * math.factorial(self.n - 1)
        )

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − (n+r-1)!/(r!(n-1)!) = 0'(factorial 그대로 공급·독립
        재계산 — 순열 생성기의 factorial() Tier1 지원 확인 선례 재사용)."""
        return (
            f"x - (factorial({self.n} + {self.r} - 1)"
            f"/(factorial({self.r}) * factorial({self.n} - 1))) = 0"
        )

    @property
    def difficulty(self) -> float:
        # PERMUTATION(base 2.0) 대비: 중복조합은 조합 공식 위에 개념 한 겹이 더 있어 약간 무겁다.
        difficulty = 2.3
        if self.n >= 6:
            difficulty += 0.1
        if self.r >= 6:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_repeated_combination_pool() -> tuple[_RepeatedCombinationSkeleton, ...]:
    """결정론 중복조합 뼈대 풀 — n×r 열거·구조 키 자연 유일·고정 셔플.

    n≤8·r≤8로 제한(n+r-1 최대 15 — factorial(15) 안전권, 순열 생성기의 n≤9 관례와 동급 보수성).
    """
    pool = [
        _RepeatedCombinationSkeleton(n=n, r=r)
        for n in _REPEATED_COMBINATION_N_RANGE
        for r in _REPEATED_COMBINATION_R_RANGE
    ]
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _repeated_combination_explanation(skeleton: _RepeatedCombinationSkeleton) -> str:
    """중복조합 해설 — 중복조합 공식 사용을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    return (
        "중복을 허락해 여러 개를 택하는 경우의 수는 중복조합 공식으로 구하므로, "
        f"구하는 경우의 수는 {skeleton.answer} 이다."
    )


@deterministic_generator
class RepeatedCombinationSkeletonGenerator:
    """중복조합 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    풀(구조 키 유일)을 순서대로 소비(소진 시 None).
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-repcomb",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("REPEATED-COMBINATION",),
        concept_tags: Sequence[ConceptTag] = _REPEATED_COMBINATION_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_repeated_combination_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 중복조합 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _RepeatedCombinationSkeleton
    ) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        template = _REPEATED_COMBINATION_TEMPLATES[
            self._index % len(_REPEATED_COMBINATION_TEMPLATES)
        ]
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
            answer_explanation=_repeated_combination_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 중복조합 스켈레톤 조립(n·r→H(n,r)=(n+r-1)!/(r!(n-1)!) 계산)",
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
                f"factorial({skeleton.n} + {skeleton.r} - 1)"
                f"/(factorial({skeleton.r}) * factorial({skeleton.n} - 1))",
                answer_text,
            ],
            concept_tags=list(self._concept_tags),
        )


# ── 이항정리 계수: (x+y)^n에서 x^(n-r)y^r 항의 계수 = C(n,r) ─────────────────────
_BINOMIAL_N_RANGE = range(3, 13)
_BINOMIAL_TEMPLATES: tuple[str, ...] = (
    "(x+y)^{n}의 전개식에서 {term}의 계수를 구하시오.",
    "이항정리를 이용하여 (x+y)^{n}의 전개식에서 {term}의 계수를 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _BinomialCoefficientSkeleton:
    """이항정리 계수 뼈대 — 지수 n·항 인덱스 r(1≤r≤n-1). 계수 = C(n,r). 단일 진실 원천."""

    n: int
    r: int

    @property
    def answer(self) -> int:
        return math.factorial(self.n) // (math.factorial(self.r) * math.factorial(self.n - self.r))

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − n!/(r!(n-r)!) = 0'(factorial 그대로 공급·독립 재계산)."""
        return (
            f"x - (factorial({self.n})/(factorial({self.r}) * factorial("
            f"{self.n} - {self.r}))) = 0"
        )

    @property
    def term_display(self) -> str:
        """항 표기 — 'x^(n-r)y^r'(지수 1 생략)."""
        return _power_display("x", self.n - self.r) + _power_display("y", self.r)

    @property
    def difficulty(self) -> float:
        # PERMUTATION(base 2.0) 대비: 이항정리 적용은 조합 공식 재인식이 필요해 약간 무겁다.
        difficulty = 2.4
        if self.n >= 9:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_binomial_pool() -> tuple[_BinomialCoefficientSkeleton, ...]:
    """결정론 이항정리 계수 뼈대 풀 — n×r(1≤r≤n-1, 자명 끝항 제외) 열거·고정 셔플."""
    pool = [_BinomialCoefficientSkeleton(n=n, r=r) for n in _BINOMIAL_N_RANGE for r in range(1, n)]
    random.Random(_POOL_SEED + 1).shuffle(pool)
    return tuple(pool)


def _binomial_explanation(skeleton: _BinomialCoefficientSkeleton) -> str:
    """이항정리 계수 해설 — 이항정리 공식 사용을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    return (
        "이항정리에 따라 전개식의 각 항의 계수는 이항계수로 구해지므로, "
        f"구하는 계수는 {skeleton.answer} 이다."
    )


@deterministic_generator
class BinomialCoefficientSkeletonGenerator:
    """이항정리 계수 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    풀(구조 키 유일)을 순서대로 소비(소진 시 None).
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-binom",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("BINOMIAL-COEFFICIENT",),
        concept_tags: Sequence[ConceptTag] = _BINOMIAL_COEFFICIENT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_binomial_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 이항정리 계수 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _BinomialCoefficientSkeleton
    ) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        template = _BINOMIAL_TEMPLATES[self._index % len(_BINOMIAL_TEMPLATES)]
        question_text = template.format(n=skeleton.n, term=skeleton.term_display)
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
            answer_explanation=_binomial_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 이항정리 계수 스켈레톤 조립(n·r→C(n,r)=n!/(r!(n-r)!) 계산)",
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
                f"factorial({skeleton.n})/(factorial({skeleton.r}) * factorial("
                f"{skeleton.n} - {skeleton.r}))",
                answer_text,
            ],
            concept_tags=list(self._concept_tags),
        )
