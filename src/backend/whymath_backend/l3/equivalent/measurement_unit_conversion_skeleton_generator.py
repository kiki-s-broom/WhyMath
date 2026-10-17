"""초등 길이·들이·무게 단위 관계 스켈레톤 생성기 — W2 Phase3 #5(결정론·LLM 0).

`elementary_area_measure_skeleton_generator`(S4-30)의 `AreaUnitConversionSkeletonGenerator`
big→small 정수배 환산 패턴을 그대로 잇는다 — [4수03-16](길이 단위 mm·km의 관계)·
[4수03-18](들이 단위 L·mL의 관계)·[4수03-21](무게 단위 kg·g의 관계)이 0건이었다 — 세
성취기준의 첫 코퍼스를 확보한다.

`pair` 필터가 성취기준 코드 자체도 결정한다(gcd_lcm·conic_section_focus 생성기의
"kind→코드" 패턴 재사용) — `mm_to_cm`·`km_to_m`은 같은 코드([4수03-16], 성취기준 원문이
"1cm와 1mm, 1km와 1m의 관계"를 함께 서술)를 공유하고, `L_to_mL`·`kg_to_g`는 각각 별도
코드([4수03-18]·[4수03-21])다.

넓이 환산 생성기와 달리 이 도메인은 **CJK 합성 글리프가 아예 존재하지 않는다**(mm·cm·km·
L·mL·kg·g는 모두 순수 ASCII 단위 문자 — ㎠·㎡·㎢ 같은 결합 글리프 문제 자체가 발생하지 않음).

concept_src_id(legacy 437 개념그래프 `source_id` 필드 실측 확인 — 2026-08-07):
  L5(길이 단위 mm·km 관계)=[4수03-16] · V1(들이 단위 L·mL 관계)=[4수03-18] ·
  W1(무게 단위 kg·g 관계)=[4수03-21].

범위(v1): 정수 값·인접 단위쌍만·대→소 방향만(형제 넓이 환산 생성기와 동일 제약).

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지·L1(ConceptTag)만 import(L4
참조 0). 난이도는 지역 함수(공유 difficulty.py 불침범·도메인 분담 관례 계승).
"""

from __future__ import annotations

import hashlib
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
    "LENGTH_STANDARD_CODE",
    "MASS_STANDARD_CODE",
    "MeasurementUnitConversionSkeletonGenerator",
    "MeasurementUnitPair",
    "VOLUME_STANDARD_CODE",
]

_POOL_SEED = 20260807

LENGTH_STANDARD_CODE = "[4수03-16]"
VOLUME_STANDARD_CODE = "[4수03-18]"
MASS_STANDARD_CODE = "[4수03-21]"

MeasurementUnitPair = Literal["mm_to_cm", "km_to_m", "L_to_mL", "kg_to_g"]

# pair → (큰 단위, 작은 단위, 환산 배율, 큰 단위 값 범위, 성취기준 코드, concept_src_id).
_PAIR_INFO: dict[MeasurementUnitPair, tuple[str, str, int, range, str, str]] = {
    "mm_to_cm": ("cm", "mm", 10, range(1, 101), LENGTH_STANDARD_CODE, "L5"),
    "km_to_m": ("km", "m", 1_000, range(1, 21), LENGTH_STANDARD_CODE, "L5"),
    "L_to_mL": ("L", "mL", 1_000, range(1, 31), VOLUME_STANDARD_CODE, "V1"),
    "kg_to_g": ("kg", "g", 1_000, range(1, 31), MASS_STANDARD_CODE, "W1"),
}

_TEMPLATES: tuple[str, ...] = (
    "{big_value}{big_unit}는 몇 {small_unit}인지 구하시오.",
    "{big_value}{big_unit}를 {small_unit}로 나타내면 얼마인지 구하시오.",
)


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _natural_answer_format(answer: int) -> AnswerFormat:
    """정답 형태 — 대→소 환산은 항상 정수배라 전건 양의 정수."""
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


@dataclass(frozen=True, slots=True)
class _ConversionSkeleton:
    """단위 환산 뼈대 — 단위쌍·큰 단위 값. 답 = 큰 단위 값 × 환산 배율. 단일 진실 원천."""

    pair: MeasurementUnitPair
    big_value: int

    @property
    def big_unit(self) -> str:
        return _PAIR_INFO[self.pair][0]

    @property
    def small_unit(self) -> str:
        return _PAIR_INFO[self.pair][1]

    @property
    def factor(self) -> int:
        return _PAIR_INFO[self.pair][2]

    @property
    def standard_code(self) -> str:
        return _PAIR_INFO[self.pair][4]

    @property
    def concept_src_id(self) -> str:
        return _PAIR_INFO[self.pair][5]

    @property
    def answer(self) -> int:
        """정답 — 큰 단위 값 × 환산 배율(대→소 방향은 항상 정수 곱)."""
        return self.big_value * self.factor

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − (big_value × factor) = 0'."""
        return f"x - ({self.big_value} * {self.factor}) = 0"

    @property
    def difficulty(self) -> float:
        # 초등 3-4학년군 기준 — 단위 환산은 곱셈 1스텝이라 낮게(awareness~procedural 경계).
        difficulty = 1.7
        if self.factor >= 1_000:
            difficulty += 0.2
        if self.big_value >= 20:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_pool(pair: MeasurementUnitPair | None = None) -> tuple[_ConversionSkeleton, ...]:
    """결정론 단위 환산 뼈대 풀 — pair×값 열거·구조 키 자연 유일·고정 시드 셔플."""
    pairs: tuple[MeasurementUnitPair, ...] = (
        ("mm_to_cm", "km_to_m", "L_to_mL", "kg_to_g") if pair is None else (pair,)
    )
    pool: list[_ConversionSkeleton] = []
    for p in pairs:
        value_range = _PAIR_INFO[p][3]
        for big_value in value_range:
            pool.append(_ConversionSkeleton(pair=p, big_value=big_value))
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _steps(skeleton: _ConversionSkeleton) -> list[str]:
    """단위 환산 풀이의 검증 단계 체인(S2-02) — 곱셈식 → 값(표현식 동치·Tier2 correct)."""
    return [f"{skeleton.big_value} * {skeleton.factor}", str(skeleton.answer)]


def _explanation(skeleton: _ConversionSkeleton) -> str:
    """단위 환산 해설 — 배율 곱셈을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    return (
        f"{skeleton.big_unit}를 {skeleton.small_unit}로 바꿀 때는 정해진 배율을 곱하므로, "
        f"구하는 값은 {skeleton.answer} 이다."
    )


@deterministic_generator
class MeasurementUnitConversionSkeletonGenerator:
    """단위 환산 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `pair` 필터로 밴드를 분리한다(직육면체 부피/이차곡선 생성기의 "kind→코드" 관례 계승 —
    필터 없이 밴드별 인스턴스를 만들면 고정 시드 풀이 처음부터 재생돼 같은 뼈대를 중복
    방출한다). `pair`가 성취기준 코드도 함께 결정하므로 호출자는 배치에서 `pair`별로
    별도 `EquivalenceSpec`을 구성해야 한다(mm_to_cm/km_to_m은 같은 코드 공유).
    """

    def __init__(
        self,
        *,
        pair: MeasurementUnitPair | None = None,
        slug_prefix: str = "wm-measunit",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("MEASUREMENT-UNIT-CONVERSION",),
    ) -> None:
        self._pool = _build_pool(pair)
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 단위 환산 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(skeleton)

    def _assemble(self, skeleton: _ConversionSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        template = _TEMPLATES[self._index % len(_TEMPLATES)]
        question_text = template.format(
            big_value=skeleton.big_value,
            big_unit=skeleton.big_unit,
            small_unit=skeleton.small_unit,
        )
        standard_codes = [skeleton.standard_code]
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
            answer_explanation=_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 단위 환산 스켈레톤 조립(단위쌍·값→배율 곱셈)",
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
            solution_steps=_steps(skeleton),
            concept_tags=[
                ConceptTag(concept_src_id=skeleton.concept_src_id, role="PRIMARY", relevance=0.95)
            ],
        )
