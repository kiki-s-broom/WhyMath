"""고등 이항분포 평균·분산 결정론 스켈레톤 생성기 — W2 Phase1 #8(결정론·LLM 0).

`discrete_expected_value_skeleton_generator`(이산확률변수 기댓값)의 형제 — 같은 통계
영역의 다음 착점이다. `[12확통03-03]`(이항분포의 뜻과 성질 — 평균과 표준편차)이 0건이었다
— 이 생성기가 첫 코퍼스를 확보한다. 개념그래프 매핑: `H:12확통03-03`(legacy 437 공간에
실존 — 형제 기댓값 생성기와 동일하게 정상 태깅 가능, 대학 축의 태깅 공백과 대비).

`kind`(mean/variance) 필터로 밴드 분리. 확률변수 X~B(n,p)(p=k/m 기약분수)일 때:
- mean: E(X) = np
- variance: V(X) = np(1−p)

**검증 설계**: 형제 기댓값 생성기와 동일 — 조건은 순수 유리수 산술식(`"n*k/m = y"`·
`"n*(k/m)*((m-k)/m) = y"`)이라 Tier1이 분수 답(기약분수 문자열)을 그대로 검증한다(신규
검증 경로 0 — sympify 기반 범용 검산기가 이항분포 공식에도 그대로 성립).

⚠️ `kind` 필터 필수(direction/operation 필터 관례 계승) — 미지정이면 두 밴드가 고정 시드
풀을 처음부터 재생해 같은 뼈대를 중복 방출한다.

범위(v1): p=k/m(m≤6, 기약분수)·n(3~20)만. 표준편차(분산의 제곱근, 일반적으로 무리수)·
초기하분포·정규분포 근사는 후속.

**노출 게이팅**: 산출물은 v0(사람 검수 전). AI 검수(Wilson 게이트)는 실 LLM 필요라 이 환경
밖(Kiki 머신)에서만 가능 — 그 전까지 `is_published=False`로 유지.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import gcd
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

__all__ = ["BinomialDistributionSkeletonGenerator", "BinomialStatKind"]

_POOL_SEED = 20260807

_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12확통03-03", role="PRIMARY", relevance=0.95),
)

_N_RANGE = range(3, 21)
_M_RANGE = range(2, 7)  # 확률 분모(p=k/m).

_MEAN_TEMPLATES: tuple[str, ...] = (
    "확률변수 X가 이항분포 B({n}, {p})를 따를 때, X의 평균 E(X)의 값을 구하시오.",
    "확률변수 X~B({n}, {p})일 때, X의 평균을 구하시오.",
)
_VARIANCE_TEMPLATES: tuple[str, ...] = (
    "확률변수 X가 이항분포 B({n}, {p})를 따를 때, X의 분산 V(X)의 값을 구하시오.",
    "확률변수 X~B({n}, {p})일 때, X의 분산을 구하시오.",
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


BinomialStatKind = Literal["mean", "variance"]


@dataclass(frozen=True, slots=True)
class _BinomialSkeleton:
    """이항분포 뼈대 — 시행 횟수 n·성공확률 p=k/m(기약분수)·통계량 종류. 단일 진실 원천."""

    kind: BinomialStatKind
    n: int
    k: int  # 확률 분자(0 < k < m)
    m: int  # 확률 분모

    @property
    def p_display(self) -> str:
        """확률 p의 발문 표기('1/3') — ASCII 슬래시(기존 관례 확인 후 사용, 신규 글리프 0)."""
        return f"{self.k}/{self.m}"

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 순수 유리수 산술식(형제 기댓값 생성기와 동형 설계)."""
        if self.kind == "mean":
            return f"{self.n}*{self.k}/{self.m} = y"
        return f"{self.n}*({self.k}/{self.m})*(({self.m} - {self.k})/{self.m}) = y"

    @property
    def result(self) -> Fraction:
        """독립 재계산(이항분포 공식 E(X)=np·V(X)=np(1−p)) — 생성기 자체 검산(형제 관례)."""
        p = Fraction(self.k, self.m)
        if self.kind == "mean":
            return self.n * p
        return self.n * p * (1 - p)


def _build_pool(kind: BinomialStatKind | None = None) -> tuple[_BinomialSkeleton, ...]:
    """결정론 이항분포 뼈대 풀 — kind×n×(k,m 기약분수) 열거·구조 키 자연 유일·고정 셔플."""
    kinds: tuple[BinomialStatKind, ...] = ("mean", "variance") if kind is None else (kind,)
    pool: list[_BinomialSkeleton] = []
    for kd in kinds:
        for n in _N_RANGE:
            for m in _M_RANGE:
                for k in range(1, m):
                    if gcd(k, m) != 1:
                        continue  # 기약분수만(예 2/4는 제외 — 이미 1/2로 표현됨).
                    pool.append(_BinomialSkeleton(kind=kd, n=n, k=k, m=m))
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _explanation(skeleton: _BinomialSkeleton) -> str:
    """이항분포 해설 — 평균/분산 공식 사용을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    answer_text = _fraction_text(skeleton.result)
    if skeleton.kind == "mean":
        return (
            "이항분포 B(n, p)의 평균은 np이므로 시행 횟수와 확률을 곱하면 구하는 평균은 "
            f"{answer_text} 이다."
        )
    return (
        "이항분포 B(n, p)의 분산은 np(1-p)이므로 시행 횟수와 확률·그 여사건의 확률을 곱하면 "
        f"구하는 분산은 {answer_text} 이다."
    )


def _answer_format(value: Fraction) -> AnswerFormat:
    """정답 형태 — 정수로 딱 떨어지면 자연수/실수, 아니면 분수(형제 생성기 관례 미러)."""
    if value.denominator == 1:
        return AnswerFormat.자연수 if value.numerator > 0 else AnswerFormat.실수
    return AnswerFormat.분수


@deterministic_generator
class BinomialDistributionSkeletonGenerator:
    """이항분포 평균·분산 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `kind`(mean/variance) 필터로 밴드를 분리한다(direction/operation 필터 관례 계승 —
    필터 없이 밴드별 인스턴스를 만들면 고정 시드 풀이 처음부터 재생돼 같은 뼈대를 중복
    방출한다).
    """

    def __init__(
        self,
        *,
        kind: BinomialStatKind | None = None,
        slug_prefix: str = "wm-binom",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("BINOMIAL-DISTRIBUTION",),
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
        """다음 이항분포 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _BinomialSkeleton) -> CandidateProblem:
        answer_text = _fraction_text(skeleton.result)
        templates = _MEAN_TEMPLATES if skeleton.kind == "mean" else _VARIANCE_TEMPLATES
        question_text = templates[self._index % len(templates)].format(
            n=skeleton.n, p=skeleton.p_display
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
            difficulty_overall=3.0 if skeleton.kind == "mean" else 3.3,
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
                    "결정론 이항분포 스켈레톤 조립(n·p→평균/분산 계산)",
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
