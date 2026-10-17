"""고등 표본평균의 평균·분산 결정론 스켈레톤 생성기 — W2 Phase3 #4(결정론·LLM 0).

`binomial_distribution_skeleton_generator`(S4-34)의 Fraction·`kind` 필터·단일코드 관례를
그대로 잇는다 — [12확통03-06](표본평균과 모평균, 표본비율과 모비율의 관계)이 0건이었다 —
이 생성기가 첫 코퍼스를 확보한다.

`kind`(mean/variance) 필터로 밴드 분리. 모평균 μ·모분산 σ²인 모집단에서 크기 n인 표본을
임의추출할 때 표본평균 X̄에 대해:
- mean: E(X̄) = μ (표본평균의 평균은 모평균과 같다 — 이 성취기준의 핵심 이해 지점 자체가
  이 항등 관계이므로 자명해 보여도 정당한 출제다)
- variance: V(X̄) = σ²/n

**검증 설계**: 형제 이항분포 생성기와 동일 — 조건은 순수 유리수 산술식(`"mu = y"`·
`"sigma_sq/n = y"`)이라 Tier1이 분수/정수 답을 그대로 검증한다(신규 검증 경로 0).

범위(v1): μ·σ²는 정수(폭 넓은 서술 회피)·n(2~30)만. 표본표준편차(제곱근, 일반적으로
무리수)·중심극한정리 근사·신뢰구간은 후속.

concept_src_id(legacy 437 개념그래프 `source_id` 필드 실측 확인 — 2026-08-07):
  H:12확통03-06(표본평균과 모평균)=[12확통03-06].

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

__all__ = ["SampleMeanDistributionSkeletonGenerator", "SampleMeanStatKind"]

_POOL_SEED = 20260807

_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12확통03-06", role="PRIMARY", relevance=0.95),
)

_MU_RANGE = range(1, 31)
_SIGMA_SQ_RANGE = range(1, 21)
_N_RANGE = range(2, 31)

_MEAN_TEMPLATES: tuple[str, ...] = (
    "모평균이 {mu}이고 모분산이 {sigma_sq}인 모집단에서 크기 {n}인 표본을 임의추출할 때, "
    "표본평균 X바의 평균 E(X바)를 구하시오.",
    "모평균이 {mu}, 모분산이 {sigma_sq}인 모집단에서 크기 {n}인 표본을 임의추출할 때, "
    "표본평균의 평균을 구하시오.",
)
_VARIANCE_TEMPLATES: tuple[str, ...] = (
    "모평균이 {mu}이고 모분산이 {sigma_sq}인 모집단에서 크기 {n}인 표본을 임의추출할 때, "
    "표본평균 X바의 분산 V(X바)를 구하시오.",
    "모평균이 {mu}, 모분산이 {sigma_sq}인 모집단에서 크기 {n}인 표본을 임의추출할 때, "
    "표본평균의 분산을 구하시오.",
)


def _fraction_text(value: Fraction) -> str:
    """기약분수 문자열('7/2'·정수면 '4') — SymPy sympify와 왕복 정합(형제 생성기 관례 미러)."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


SampleMeanStatKind = Literal["mean", "variance"]


@dataclass(frozen=True, slots=True)
class _SampleMeanSkeleton:
    """표본평균 뼈대 — 모평균 mu·모분산 sigma_sq·표본크기 n·통계량 종류. 단일 진실 원천."""

    kind: SampleMeanStatKind
    mu: int
    sigma_sq: int
    n: int

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 형제 이항분포 생성기와 동형(순수 유리수 산술식)."""
        if self.kind == "mean":
            return f"{self.mu} = y"
        return f"{self.sigma_sq}/{self.n} = y"

    @property
    def result(self) -> Fraction:
        """독립 재계산(E(X바)=mu·V(X바)=sigma_sq/n) — 생성기 자체 검산(형제 관례)."""
        if self.kind == "mean":
            return Fraction(self.mu)
        return Fraction(self.sigma_sq, self.n)


def _build_pool(kind: SampleMeanStatKind | None = None) -> tuple[_SampleMeanSkeleton, ...]:
    """결정론 표본평균 뼈대 풀 — kind×mu×sigma_sq×n 열거·구조 키 자연 유일·고정 셔플."""
    kinds: tuple[SampleMeanStatKind, ...] = ("mean", "variance") if kind is None else (kind,)
    pool: list[_SampleMeanSkeleton] = []
    for kd in kinds:
        for mu in _MU_RANGE:
            for sigma_sq in _SIGMA_SQ_RANGE:
                for n in _N_RANGE:
                    pool.append(_SampleMeanSkeleton(kind=kd, mu=mu, sigma_sq=sigma_sq, n=n))
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _explanation(skeleton: _SampleMeanSkeleton) -> str:
    """표본평균 해설 — 평균/분산 관계를 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    answer_text = _fraction_text(skeleton.result)
    if skeleton.kind == "mean":
        return "표본평균의 평균은 모평균과 같으므로, 구하는 값은 " f"{answer_text} 이다."
    return (
        "표본평균의 분산은 모분산을 표본크기로 나눈 값이므로, 구하는 값은 " f"{answer_text} 이다."
    )


def _answer_format(value: Fraction) -> AnswerFormat:
    """정답 형태 — 정수로 딱 떨어지면 자연수/실수, 아니면 분수(형제 생성기 관례 미러)."""
    if value.denominator == 1:
        return AnswerFormat.자연수 if value.numerator > 0 else AnswerFormat.실수
    return AnswerFormat.분수


@deterministic_generator
class SampleMeanDistributionSkeletonGenerator:
    """표본평균의 평균·분산 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `kind`(mean/variance) 필터로 밴드를 분리한다(direction/operation 필터 관례 계승 —
    필터 없이 밴드별 인스턴스를 만들면 고정 시드 풀이 처음부터 재생돼 같은 뼈대를 중복
    방출한다).
    """

    def __init__(
        self,
        *,
        kind: SampleMeanStatKind | None = None,
        slug_prefix: str = "wm-samplemean",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("SAMPLE-MEAN-DISTRIBUTION",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_pool(kind)
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 표본평균 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _SampleMeanSkeleton) -> CandidateProblem:
        answer_text = _fraction_text(skeleton.result)
        templates = _MEAN_TEMPLATES if skeleton.kind == "mean" else _VARIANCE_TEMPLATES
        question_text = templates[self._index % len(templates)].format(
            mu=skeleton.mu, sigma_sq=skeleton.sigma_sq, n=skeleton.n
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
            difficulty_overall=2.6 if skeleton.kind == "mean" else 3.1,
            question_format=QuestionFormat.단답형,
            answer_format=_answer_format(skeleton.result),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 표본평균 스켈레톤 조립(mu·sigma_sq·n→E(X바)/V(X바) 계산)",
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
