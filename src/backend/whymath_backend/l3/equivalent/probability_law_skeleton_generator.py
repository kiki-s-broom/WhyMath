"""고등 확률 — 덧셈정리·여사건·곱셈정리 스켈레톤 생성기 — W2 Phase3 #3(결정론·LLM 0).

`binomial_distribution_skeleton_generator`(S4-34)의 Fraction 관례를 그대로 잇는다 — 확률
값을 기약분수로 다루고 조건식은 순수 유리수 산술식이라 **동일한 SymPy sympify 범용
검산기**로 충분하다(도메인 전용 검증기 신설 0). [12확통02-02](확률의 덧셈정리)·
[12확통02-03](여사건의 확률)·[12확통02-06](확률의 곱셈정리)이 0건이었다 — 세 성취기준의
첫 코퍼스를 확보한다.

세 클래스(전부 `kind`가 성취기준 코드 자체를 결정 — gcd_lcm·conic_section_focus 생성기의
"kind→코드" 패턴 재사용):
- `AdditionLawSkeletonGenerator` — P(A∪B) = P(A)+P(B)−P(A∩B). ([12확통02-02])
- `ComplementLawSkeletonGenerator` — P(A^c) = 1−P(A). 발문은 기호 없이 "여사건"으로만
  서술(A^c 등 위첨자 기호 미사용 — 신규 글리프 회피). ([12확통02-03])
- `MultiplicationLawSkeletonGenerator` — P(A∩B) = P(A)×P(B|A)(조건부확률). ([12확통02-06])

표시 확률은 모두 기약분수로 구성(gcd 필터) — "4/8" 같은 비기약 표기가 발문에 나오지
않도록 형제 이항분포 생성기의 관례를 그대로 계승한다. 덧셈정리는 P(A∪B)≤1을 만족하도록
교집합 개수 범위를 역산 제약한다(날조 없는 유효 확률공간 보장).

concept_src_id(legacy 437 개념그래프 `source_id` 필드 실측 확인 — 2026-08-07):
  H:12확통02-02(덧셈정리)=[12확통02-02] · H:12확통02-03(여사건)=[12확통02-03] ·
  H:12확통02-06(곱셈정리)=[12확통02-06].

범위(v1): 표본공간 크기(분모) 소규모(≤20)·정수 사건 개수만. 조건부확률 자체를 구하는
문항(나눗셈 역산)은 후속.

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지·L1(ConceptTag)만 import(L4
참조 0). 난이도는 지역 함수(공유 difficulty.py 불침범·도메인 분담 관례 계승).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import gcd

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
    "AdditionLawSkeletonGenerator",
    "ComplementLawSkeletonGenerator",
    "MultiplicationLawSkeletonGenerator",
]

_POOL_SEED = 20260807

_ADDITION_STANDARD_CODE = "[12확통02-02]"
_COMPLEMENT_STANDARD_CODE = "[12확통02-03]"
_MULTIPLICATION_STANDARD_CODE = "[12확통02-06]"

_ADDITION_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12확통02-02", role="PRIMARY", relevance=0.95),
)
_COMPLEMENT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12확통02-03", role="PRIMARY", relevance=0.95),
)
_MULTIPLICATION_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12확통02-06", role="PRIMARY", relevance=0.95),
)


def _fraction_text(value: Fraction) -> str:
    """기약분수 문자열('7/2'·정수면 '4') — SymPy sympify와 왕복 정합(형제 생성기 관례 미러)."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _answer_format(value: Fraction) -> AnswerFormat:
    """정답 형태 — 정수로 딱 떨어지면 자연수/실수, 아니면 분수(형제 생성기 관례 미러)."""
    if value.denominator == 1:
        return AnswerFormat.자연수 if value.numerator > 0 else AnswerFormat.실수
    return AnswerFormat.분수


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


# ── 덧셈정리: P(A∪B) = P(A)+P(B)-P(A∩B) ──────────────────────────────────────
_ADDITION_N_RANGE = range(6, 16)
_ADDITION_TEMPLATES: tuple[str, ...] = (
    "두 사건 A, B에 대하여 P(A) = {a}/{n}, P(B) = {b}/{n}이고 A와 B가 동시에 일어날 확률이 "
    "{both}/{n}일 때, A 또는 B가 일어날 확률을 구하시오.",
    "두 사건 A, B에 대하여 P(A) = {a}/{n}, P(B) = {b}/{n}이고 두 사건이 동시에 일어날 "
    "확률이 {both}/{n}일 때, 확률의 덧셈정리를 이용하여 A 또는 B가 일어날 확률을 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _AdditionSkeleton:
    """덧셈정리 뼈대 — 분모 n·P(A) 분자 a·P(B) 분자 b·P(A∩B) 분자 both. 단일 진실 원천."""

    n: int
    a: int
    b: int
    both: int

    @property
    def answer(self) -> Fraction:
        return Fraction(self.a + self.b - self.both, self.n)

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'y − (a+b-both)/n = 0'."""
        return f"({self.a} + {self.b} - {self.both})/{self.n} = y"


def _build_addition_pool() -> tuple[_AdditionSkeleton, ...]:
    """결정론 덧셈정리 뼈대 풀 — n×a×b×both 열거(P(A)·P(B) 기약분수·유효 확률공간만)·고정 셔플.

    both는 max(0, a+b-n)..min(a,b) 범위만 허용(P(A∪B)≤1 보장 — 날조 없는 유효 확률).
    """
    pool: list[_AdditionSkeleton] = []
    for n in _ADDITION_N_RANGE:
        for a in range(1, n):
            if gcd(a, n) != 1:
                continue
            for b in range(1, n):
                if gcd(b, n) != 1:
                    continue
                low = max(0, a + b - n)
                high = min(a, b)
                for both in range(low, high + 1):
                    pool.append(_AdditionSkeleton(n=n, a=a, b=b, both=both))
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _addition_explanation(skeleton: _AdditionSkeleton) -> str:
    """덧셈정리 해설 — 공식 적용을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    answer_text = _fraction_text(skeleton.answer)
    return (
        "확률의 덧셈정리에 따라 P(A)와 P(B)를 더하고 두 사건이 동시에 일어날 확률을 빼면 "
        "구하는 확률은 "
        f"{answer_text} 이다."
    )


@deterministic_generator
class AdditionLawSkeletonGenerator:
    """확률의 덧셈정리 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    풀(구조 키 유일)을 순서대로 소비(소진 시 None).
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-addlaw",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("PROBABILITY-ADDITION-LAW",),
        concept_tags: Sequence[ConceptTag] = _ADDITION_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_addition_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 덧셈정리 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _AdditionSkeleton) -> CandidateProblem:
        answer_text = _fraction_text(skeleton.answer)
        template = _ADDITION_TEMPLATES[self._index % len(_ADDITION_TEMPLATES)]
        question_text = template.format(
            a=skeleton.a, b=skeleton.b, both=skeleton.both, n=skeleton.n
        )
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
            difficulty_overall=2.8,
            question_format=QuestionFormat.단답형,
            answer_format=_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_addition_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 확률 덧셈정리 스켈레톤 조립(a·b·both→P(A∪B)=P(A)+P(B)-P(A∩B) 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=skeleton.condition,
            answer_map={"y": answer_text},
            answer_selection="unique",
            solution_steps=None,
            concept_tags=list(self._concept_tags),
        )


# ── 여사건: P(A^c) = 1-P(A) ───────────────────────────────────────────────────
_COMPLEMENT_N_RANGE = range(4, 21)
_COMPLEMENT_TEMPLATES: tuple[str, ...] = (
    "사건 A에 대하여 P(A) = {a}/{n}일 때, 사건 A의 여사건이 일어날 확률을 구하시오.",
    "사건 A가 일어날 확률이 {a}/{n}일 때, A가 일어나지 않을 확률을 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _ComplementSkeleton:
    """여사건 뼈대 — 분모 n·P(A) 분자 a(기약분수). 단일 진실 원천."""

    n: int
    a: int

    @property
    def answer(self) -> Fraction:
        return 1 - Fraction(self.a, self.n)

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'y − (1 − a/n) = 0'."""
        return f"1 - {self.a}/{self.n} = y"


def _build_complement_pool() -> tuple[_ComplementSkeleton, ...]:
    """결정론 여사건 뼈대 풀 — n×a(기약분수) 열거·고정 셔플."""
    pool = [
        _ComplementSkeleton(n=n, a=a)
        for n in _COMPLEMENT_N_RANGE
        for a in range(1, n)
        if gcd(a, n) == 1
    ]
    random.Random(_POOL_SEED + 1).shuffle(pool)
    return tuple(pool)


def _complement_explanation(skeleton: _ComplementSkeleton) -> str:
    """여사건 해설 — 공식 적용을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    answer_text = _fraction_text(skeleton.answer)
    return f"여사건의 확률은 1에서 P(A)를 빼면 되므로, 구하는 확률은 {answer_text} 이다."


@deterministic_generator
class ComplementLawSkeletonGenerator:
    """여사건의 확률 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    풀(구조 키 유일)을 순서대로 소비(소진 시 None).
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-complaw",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("PROBABILITY-COMPLEMENT-LAW",),
        concept_tags: Sequence[ConceptTag] = _COMPLEMENT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_complement_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 여사건 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _ComplementSkeleton) -> CandidateProblem:
        answer_text = _fraction_text(skeleton.answer)
        template = _COMPLEMENT_TEMPLATES[self._index % len(_COMPLEMENT_TEMPLATES)]
        question_text = template.format(a=skeleton.a, n=skeleton.n)
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
            difficulty_overall=2.0,
            question_format=QuestionFormat.단답형,
            answer_format=_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_complement_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 여사건 스켈레톤 조립(a·n→P(A^c)=1-P(A) 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=skeleton.condition,
            answer_map={"y": answer_text},
            answer_selection="unique",
            solution_steps=None,
            concept_tags=list(self._concept_tags),
        )


# ── 곱셈정리: P(A∩B) = P(A)×P(B|A) ────────────────────────────────────────────
_MULTIPLICATION_N_RANGE = range(4, 11)
_MULTIPLICATION_M_RANGE = range(4, 11)
_MULTIPLICATION_TEMPLATES: tuple[str, ...] = (
    "두 사건 A, B에 대하여 P(A) = {a}/{n}이고, 조건부확률 P(B|A) = {c}/{m}일 때, 확률의 "
    "곱셈정리를 이용하여 A와 B가 동시에 일어날 확률을 구하시오.",
    "사건 A가 일어날 확률이 {a}/{n}이고 A가 일어났을 때 B가 일어날 조건부확률이 {c}/{m}"
    "일 때, A와 B가 동시에 일어날 확률을 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _MultiplicationSkeleton:
    """곱셈정리 뼈대 — P(A) 분모 n·분자 a·P(B|A) 분모 m·분자 c(모두 기약분수). 단일 진실 원천."""

    n: int
    a: int
    m: int
    c: int

    @property
    def answer(self) -> Fraction:
        return Fraction(self.a, self.n) * Fraction(self.c, self.m)

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'y − (a/n)×(c/m) = 0'."""
        return f"({self.a}/{self.n})*({self.c}/{self.m}) = y"


def _build_multiplication_pool() -> tuple[_MultiplicationSkeleton, ...]:
    """결정론 곱셈정리 뼈대 풀 — n×a×m×c(P(A)·P(B|A) 각각 기약분수) 열거·고정 셔플."""
    pool: list[_MultiplicationSkeleton] = []
    for n in _MULTIPLICATION_N_RANGE:
        for a in range(1, n):
            if gcd(a, n) != 1:
                continue
            for m in _MULTIPLICATION_M_RANGE:
                for c in range(1, m):
                    if gcd(c, m) != 1:
                        continue
                    pool.append(_MultiplicationSkeleton(n=n, a=a, m=m, c=c))
    random.Random(_POOL_SEED + 2).shuffle(pool)
    return tuple(pool)


def _multiplication_explanation(skeleton: _MultiplicationSkeleton) -> str:
    """곱셈정리 해설 — 공식 적용을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    answer_text = _fraction_text(skeleton.answer)
    return (
        "확률의 곱셈정리에 따라 P(A)와 조건부확률 P(B|A)를 곱하면 구하는 확률은 "
        f"{answer_text} 이다."
    )


@deterministic_generator
class MultiplicationLawSkeletonGenerator:
    """확률의 곱셈정리 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    풀(구조 키 유일)을 순서대로 소비(소진 시 None).
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-mullaw",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("PROBABILITY-MULTIPLICATION-LAW",),
        concept_tags: Sequence[ConceptTag] = _MULTIPLICATION_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_multiplication_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 곱셈정리 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _MultiplicationSkeleton
    ) -> CandidateProblem:
        answer_text = _fraction_text(skeleton.answer)
        template = _MULTIPLICATION_TEMPLATES[self._index % len(_MULTIPLICATION_TEMPLATES)]
        question_text = template.format(a=skeleton.a, n=skeleton.n, c=skeleton.c, m=skeleton.m)
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
            difficulty_overall=3.0,
            question_format=QuestionFormat.단답형,
            answer_format=_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_multiplication_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 확률 곱셈정리 스켈레톤 조립(a·n·c·m→P(A∩B)=P(A)×P(B|A) 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=skeleton.condition,
            answer_map={"y": answer_text},
            answer_selection="unique",
            solution_steps=None,
            concept_tags=list(self._concept_tags),
        )
