"""근의 합/곱(Vieta) 킬러 스켈레톤 생성기 — S2 wedge 킬러 확장(결정론·LLM 0).

`SkeletonEquivalentProblemGenerator`(이차방정식 근)의 킬러 형제다. 같은
`EquivalentProblemGenerator` 좌석을 구현하되, 답이 f(x)=0의 *근*이 아니라 **근들의
합/곱**(Vieta)이다 — "삼차방정식 …의 세 근의 합/곱을 구하시오"류 고3 킬러 문항.
calculus_skeleton_generator 헤더가 후속으로 지목한 "근의 합/곱" 항목을 처음 확보한다.

핵심(재구현 0): 근을 코드가 골라 다항식을 역산하므로 근의 합/곱을 *코드가 정확히 안다*
(무리·복소여도 Vieta 정확값). 검증은 신규 정본 `verify_root_aggregate`(l3/verify_answer)로,
수용 게이트(`acceptance._evaluate_verification`의 answer_aggregate 분기)가 answer(주장
집계값)를 재계산해 교차 검증한다 — 생성기 자기 신뢰 금지 원칙 유지.

킬러 난이도: 계수가 정수이되 **근이 비환원(무리수 포함)**이라 학생이 근을 일일이 구하면
막힌다 — Vieta(합=−b/a·곱=(−1)ⁿc/a)를 *간파해야* 풀린다. 이차(두 근의 합/곱)·삼차(세
근의 합/곱)를 낸다. answer는 정수(Vieta는 정수계수·선두계수 1이면 항상 정수).

7계층: L3 지역. schema·동일 패키지(canonicalize·difficulty)·L1 problem_bank만 import.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Literal

import sympy

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.canonicalize import canonical_signature
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

__all__ = ["RootAggregateSkeletonGenerator"]

_POOL_SEED = 20260709
_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="HK06", role="PRIMARY", relevance=0.90),
)

# 킬러 aggregate 종류.
AggregateKind = Literal["sum", "product"]

# 발문 템플릿(차수·종류별·인덱스 회전).
_TEMPLATES: dict[tuple[int, str], tuple[str, ...]] = {
    (2, "sum"): (
        "이차방정식 {eq} 의 두 근의 합을 구하시오.",
        "이차방정식 {eq} 의 서로 다른 두 근의 합의 값을 구하시오.",
    ),
    (2, "product"): (
        "이차방정식 {eq} 의 두 근의 곱을 구하시오.",
        "이차방정식 {eq} 의 두 근의 곱의 값을 구하시오.",
    ),
    (3, "sum"): (
        "삼차방정식 {eq} 의 세 근의 합을 구하시오.",
        "삼차방정식 {eq} 의 모든 근의 합을 구하시오.",
    ),
    (3, "product"): (
        "삼차방정식 {eq} 의 세 근의 곱을 구하시오.",
        "삼차방정식 {eq} 의 모든 근의 곱을 구하시오.",
    ),
}


@dataclass(frozen=True, slots=True)
class _AggSkeleton:
    """근 집계 뼈대 — 근 튜플(정수·무리 섞임)·차수·종류. 수치의 단일 진실 원천."""

    roots: tuple[sympy.Expr, ...]  # 근(무리수 포함 가능)
    kind: str  # sum / product

    @property
    def degree(self) -> int:
        return len(self.roots)

    @property
    def coefficients(self) -> tuple[int, ...]:
        """전개 정수 계수(선두계수 1) — ∏(x−rᵢ) 전개. 무리근은 켤레쌍이라 계수는 정수."""
        x = sympy.Symbol("x")
        poly = sympy.Integer(1)
        for r in self.roots:
            poly = poly * (x - r)
        expanded = sympy.expand(poly)
        p = sympy.Poly(expanded, x)
        coeffs = [int(c) for c in p.all_coeffs()]
        return tuple(coeffs)

    @property
    def answer(self) -> int:
        """근의 합/곱(Vieta 정확값) — 선두계수 1·정수계수라 정수."""
        result = sympy.Integer(0) if self.kind == "sum" else sympy.Integer(1)
        for r in self.roots:
            result = result + r if self.kind == "sum" else result * r
        return int(sympy.simplify(result))


def _sympy_equation(coeffs: Sequence[int]) -> str:
    """정수 계수 → 검산용 SymPy 등식('x**3 - 6*x**2 + 11*x - 6 = 0')."""
    deg = len(coeffs) - 1
    terms: list[str] = []
    for i, c in enumerate(coeffs):
        power = deg - i
        if c == 0:
            continue
        sign = "-" if c < 0 else "+"
        mag = abs(c)
        if power == 0:
            body = f"{mag}"
        elif power == 1:
            body = "x" if mag == 1 else f"{mag}*x"
        else:
            body = f"x**{power}" if mag == 1 else f"{mag}*x**{power}"
        if not terms:
            terms.append(f"-{body}" if c < 0 else body)
        else:
            terms.append(f"{sign} {body}")
    return " ".join(terms) + " = 0"


def _display_equation(coeffs: Sequence[int]) -> str:
    """정수 계수 → 사람이 읽는 방정식('x^3 - 6x^2 + 11x - 6 = 0')."""
    deg = len(coeffs) - 1
    terms: list[str] = []
    for i, c in enumerate(coeffs):
        power = deg - i
        if c == 0:
            continue
        sign = "-" if c < 0 else "+"
        mag = abs(c)
        if power == 0:
            body = f"{mag}"
        elif power == 1:
            body = "x" if mag == 1 else f"{mag}x"
        else:
            body = f"x^{power}" if mag == 1 else f"{mag}x^{power}"
        if not terms:
            terms.append(f"-{body}" if c < 0 else body)
        else:
            terms.append(f"{sign} {body}")
    return " ".join(terms) + " = 0"


def _build_pool() -> tuple[_AggSkeleton, ...]:
    """결정론 근 집계 뼈대 풀 — 무리근 쌍(p±√q) + 정수근 조합으로 이차·삼차 킬러 생성.

    무리근을 반드시 하나 포함해 "근을 일일이 못 구하고 Vieta로 풀어야" 하는 킬러성을 준다.
    켤레쌍이라 전개계수는 정수(선두계수 1). (계수, 종류) 중복은 빌드 시 제거.
    """
    pool: list[_AggSkeleton] = []
    seen: set[tuple[tuple[int, ...], str]] = set()

    def _add(roots: tuple[sympy.Expr, ...], kind: str) -> None:
        sk = _AggSkeleton(roots=roots, kind=kind)
        key = (sk.coefficients, kind)
        if key not in seen:
            seen.add(key)
            pool.append(sk)

    qs = (2, 3, 5, 6, 7)  # 비제곱 → 무리근
    ps = (-3, -2, -1, 0, 1, 2, 3)
    # 이차: p±√q (무리 켤레쌍) → 두 근의 합=2p·곱=p²−q.
    for p in ps:
        for q in qs:
            base = sympy.Integer(p)
            roots2 = (base + sympy.sqrt(q), base - sympy.sqrt(q))
            for kind in ("sum", "product"):
                _add(roots2, kind)
    # 삼차: 정수근 r + 무리 켤레쌍 p±√q → 세 근의 합=r+2p·곱=r(p²−q).
    for r in (-2, -1, 1, 2, 3):
        for p in (-1, 0, 1, 2):
            for q in qs:
                base = sympy.Integer(p)
                roots3 = (sympy.Integer(r), base + sympy.sqrt(q), base - sympy.sqrt(q))
                for kind in ("sum", "product"):
                    _add(roots3, kind)

    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


@deterministic_generator
class RootAggregateSkeletonGenerator:
    """근의 합/곱 킬러 생성기 — `EquivalentProblemGenerator` 좌석 구현(S2·LLM 0)."""

    def __init__(
        self,
        *,
        kind: AggregateKind = "sum",
        degree: Literal[2, 3] = 3,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-vieta",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("POLY-ROOT",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
        difficulty_overall: float = 4.0,
    ) -> None:
        self._pool = tuple(s for s in _build_pool() if s.kind == kind and s.degree == degree)
        self._kind: AggregateKind = kind
        self._degree = degree
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)
        self._difficulty = difficulty_overall

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 뼈대를 근 집계 킬러 후보로 조립 — skip 구조는 건너뛰고, 소진 시 None."""
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            coeffs = skeleton.coefficients
            condition = _sympy_equation(coeffs)
            if self._skip is not None:
                signature = canonical_signature(condition, f"agg:{self._kind}")
                if signature is not None and signature in self._skip:
                    continue
            return self._assemble(spec, skeleton, coeffs, condition)
        return None

    def _assemble(
        self,
        spec: EquivalenceSpec,
        skeleton: _AggSkeleton,
        coeffs: tuple[int, ...],
        condition: str,
    ) -> CandidateProblem:
        display_eq = _display_equation(coeffs)
        answer = str(skeleton.answer)
        templates = _TEMPLATES[(skeleton.degree, skeleton.kind)]
        question = templates[self._index % len(templates)].format(eq=display_eq)
        which = "합" if skeleton.kind == "sum" else "곱"
        vieta = "-b/a" if skeleton.kind == "sum" else "((-1)^n)·(상수항/최고차항계수)"
        explanation = (
            f"모든 근을 직접 구하지 않아도 근과 계수의 관계(비에트)로 근의 {which}은 "
            f"{vieta}에서 {answer}이다."
        )
        standard_codes = sorted(spec.achievement_standard_codes)
        slug = self._stable_slug(question, answer, standard_codes)
        problem = Problem(
            problem_id=uuid.uuid5(uuid.NAMESPACE_URL, f"whymath:problem:{slug}"),
            slug=slug,
            source_type=SourceType.자체생성,
            curriculum_version=self._curriculum_version,
            valid_from_year=self._valid_from_year,
            subject=self._subject,
            unit_codes=list(self._unit_codes),
            difficulty_overall=self._difficulty,
            question_format=QuestionFormat.단답형,
            answer_format=AnswerFormat.실수,
            achievement_standard_codes=standard_codes,
            question_text=question,
            answer=answer,
            answer_explanation=explanation,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 근 집계 스켈레톤 조립(근→다항식 역산·Vieta)",
                    "S2-a 수용 게이트(verify_root_aggregate)",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,
            answer_map={},  # 답이 근이 아니라 집계값이라 근 치환맵 비움
            answer_selection=None,
            answer_aggregate=skeleton.kind,  # 게이트가 verify_root_aggregate로 분기
            solution_steps=None,
            concept_tags=list(self._concept_tags),
        )

    def _stable_slug(self, question: str, answer: str, codes: Sequence[str]) -> str:
        payload = "|".join([question, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"
