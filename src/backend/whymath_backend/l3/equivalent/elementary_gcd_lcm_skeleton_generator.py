"""초등 최대공약수·최소공배수 결정론 스켈레톤 생성기 — W2 Phase2 #3(결정론·LLM 0).

`elementary_rounding_skeleton_generator`(초등 어림)의 형제 — 초등 "수와 연산" 영역의
다음 착점이다. `[6수01-04]`(최대공약수)·`[6수01-05]`(최소공배수)가 0건이었다 — 이 생성기가
두 성취기준의 첫 코퍼스를 확보한다. 개념그래프 매핑: `B1`(약수·공약수·최대공약수 →
[6수01-04])·`B2`(배수·공배수·최소공배수 → [6수01-05]) — legacy 437 공간에 실존.

**형제 생성기들과의 차이(중요)**: 이 도메인은 `kind`가 밴드만이 아니라 **성취기준 코드
자체**를 가른다(gcd→[6수01-04]·lcm→[6수01-05], 서로 다른 표준). 형제 생성기들(direction/
operation 필터)은 밴드가 달라도 같은 표준코드를 공유했는데 여긴 다르다 — 그래서
`achievement_standard_codes`를 스펙에서 그대로 따르지 않고 `kind`로 자체 결정한다(배치가
kind별로 다른 EquivalenceSpec을 넘겨야 함).

**검증 설계**: 조건은 SymPy `gcd()`/`lcm()`을 그대로 사용한다(신규 검증 경로 0 — 형제
생성기들의 sympify 범용 검산기 재사용, 스파이크로 두 함수 모두 정확히 pass/fail 갈림 확인).

범위(v1): 두 수의 최대공약수·최소공배수만(3개 이상 수·공약수/공배수 나열은 후속).

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
from whymath_backend.lang.josa import wa_gwa
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

__all__ = ["GCD_STANDARD_CODE", "GcdLcmKind", "GcdLcmSkeletonGenerator", "LCM_STANDARD_CODE"]

_POOL_SEED = 20260807

GCD_STANDARD_CODE = "[6수01-04]"
LCM_STANDARD_CODE = "[6수01-05]"

_GCD_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="B1", role="PRIMARY", relevance=0.95),
)
_LCM_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="B2", role="PRIMARY", relevance=0.95),
)

_VALUE_RANGE = range(4, 61)

GcdLcmKind = Literal["gcd", "lcm"]

_GCD_TEMPLATES: tuple[str, ...] = (
    "두 수 {a}{wa_gwa} {b}의 최대공약수를 구하시오.",
    "{a}{wa_gwa} {b}의 최대공약수를 구하시오.",
)
_LCM_TEMPLATES: tuple[str, ...] = (
    "두 수 {a}{wa_gwa} {b}의 최소공배수를 구하시오.",
    "{a}{wa_gwa} {b}의 최소공배수를 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _GcdLcmSkeleton:
    """최대공약수·최소공배수 뼈대 — 두 수 a·b(a<b)·연산 종류. 단일 진실 원천."""

    kind: GcdLcmKind
    a: int
    b: int

    @property
    def answer(self) -> int:
        gcd_value = math.gcd(self.a, self.b)
        if self.kind == "gcd":
            return gcd_value
        return self.a * self.b // gcd_value

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — a·b(주어진 정보)만으로 gcd()/lcm()이 독립 재유도."""
        func = "gcd" if self.kind == "gcd" else "lcm"
        return f"x - {func}({self.a}, {self.b}) = 0"

    @property
    def difficulty(self) -> float:
        # 초등 5-6학년군 기준 — 최소공배수가 최대공약수보다 약간 무겁다(배수 나열이 더 긺).
        difficulty = 1.6 if self.kind == "gcd" else 1.8
        if max(self.a, self.b) >= 40:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_pool(kind: GcdLcmKind | None = None) -> tuple[_GcdLcmSkeleton, ...]:
    """결정론 최대공약수·최소공배수 뼈대 풀 — kind×(a<b) 전수열거·구조 키 자연 유일·고정 셔플."""
    kinds: tuple[GcdLcmKind, ...] = ("gcd", "lcm") if kind is None else (kind,)
    pool: list[_GcdLcmSkeleton] = []
    for kd in kinds:
        for a in _VALUE_RANGE:
            for b in _VALUE_RANGE:
                if a < b:
                    pool.append(_GcdLcmSkeleton(kind=kd, a=a, b=b))
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _explanation(skeleton: _GcdLcmSkeleton) -> str:
    """해설 — 최대공약수/최소공배수 정의를 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    if skeleton.kind == "gcd":
        return (
            "두 수를 동시에 나누어떨어지게 하는 수 중 가장 큰 수가 최대공약수이므로, "
            f"구하는 최대공약수는 {skeleton.answer} 이다."
        )
    return (
        "두 수의 공통인 배수 중 가장 작은 수가 최소공배수이므로, "
        f"구하는 최소공배수는 {skeleton.answer} 이다."
    )


def _answer_format(value: int) -> AnswerFormat:
    return AnswerFormat.자연수 if value > 0 else AnswerFormat.실수


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


@deterministic_generator
class GcdLcmSkeletonGenerator:
    """최대공약수·최소공배수 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `kind`(gcd/lcm) 필터로 밴드를 분리한다(direction/operation 필터 관례 계승 — 필터 없이
    밴드별 인스턴스를 만들면 고정 시드 풀이 처음부터 재생돼 같은 뼈대를 중복 방출한다).
    `kind`가 성취기준 코드·개념 태그도 함께 결정한다(모듈 docstring 참조 — 이 도메인 고유
    설계, 스펙의 achievement_standard_codes를 그대로 따르지 않는다).
    """

    def __init__(
        self,
        *,
        kind: GcdLcmKind,
        slug_prefix: str = "wm-gcdlcm",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("GCD-LCM",),
    ) -> None:
        self._kind = kind
        self._pool = _build_pool(kind)
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(_GCD_CONCEPT_TAGS if kind == "gcd" else _LCM_CONCEPT_TAGS)
        self._standard_code = GCD_STANDARD_CODE if kind == "gcd" else LCM_STANDARD_CODE

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 최대공약수·최소공배수 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(skeleton)

    def _assemble(self, skeleton: _GcdLcmSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        templates = _GCD_TEMPLATES if skeleton.kind == "gcd" else _LCM_TEMPLATES
        question_text = templates[self._index % len(templates)].format(
            a=skeleton.a, b=skeleton.b, wa_gwa=wa_gwa(str(skeleton.a))
        )
        standard_codes = [self._standard_code]
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
            answer_format=_answer_format(skeleton.answer),
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
                    "결정론 최대공약수·최소공배수 스켈레톤 조립(a·b→gcd/lcm 계산)",
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
            solution_steps=None,
            concept_tags=list(self._concept_tags),
        )
