"""초등 도형과 측정 — 직육면체 부피·부피 단위·원주율 스켈레톤 생성기 — W2 Phase3 #1(결정론·LLM 0).

`elementary_area_measure_skeleton_generator`(S4-30, [6수03-12]·[6수03-17])의 형제다 — 같은
도메인("둘레·넓이·부피")의 잔여 0커버 3개 성취기준을 마저 커버한다: [6수03-19](직육면체·정육면체의
부피)·[6수03-18](부피 단위 ㎤·㎥의 관계)·[6수03-15](원주율의 근삿값 3.14 활용).

세 클래스:
- `RectangularPrismVolumeSkeletonGenerator` — 부피 = l×w×h(전건 정수).
- `VolumeUnitConversionSkeletonGenerator` — m³→cm³ 환산(배율 100³=1,000,000, 면적 환산 생성기의
  "대→소·정수배" 관례 그대로 계승 — v1은 인접 단위 1쌍·이 방향만).
- `CircleCircumferenceSkeletonGenerator` — 원주 = 지름×3.14(교육과정 지정 근삿값 — `formula_refs`
  날조 아님, standards.json statement 원문 "원주율의 근삿값으로 3.14를 사용"). 3.14=157/50이라
  지름이 정수면 원주는 항상 소수점 둘째 자리에서 정확히 끝난다(부동소수점 오차 없이 정수
  `diameter*314`(센트 단위)로 계산 — Fraction 불요).

핵심 통찰(재구현 0): 부피·단위환산은 면적 생성기와 동형(방정식 유일해 환원). 원주만 신규 패턴
(십진 소수 답)이라 `AnswerFormat.실수`를 쓴다(binomial_distribution의 분수 답과 대비 — 이 값은
교육과정이 지정한 근삿값 소수이지 기약분수가 자연스러운 문맥이 아니다).

concept_src_id(legacy 437 개념그래프 `source_id` 필드 실측 확인 — 2026-08-07):
  ME9(부피의 원리·부피 구하기)=[6수03-19] · ME8(부피 단위)=[6수03-18] · ME5(원주율)=[6수03-15].

범위(v1): 부피는 직육면체·정육면체만(원기둥 등 곡면 입체는 후속). 단위환산은 m³→cm³ 1쌍·대→소
방향만(면적 생성기 선례 그대로). 원주는 지름 제시형만(반지름 제시·원의 넓이는 후속 — 넓이는
π 자체가 필요해 다른 스켈레톤).

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지·L1(ConceptTag)만 import(L4 참조 0).
"""

from __future__ import annotations

import hashlib
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
    "CircleCircumferenceSkeletonGenerator",
    "RectangularPrismVolumeSkeletonGenerator",
    "VolumeUnitConversionSkeletonGenerator",
]

_POOL_SEED = 20260807

_VOLUME_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="ME9", role="PRIMARY", relevance=0.95),
)
_VOLUME_UNIT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="ME8", role="PRIMARY", relevance=0.95),
)
_CIRCUMFERENCE_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="ME5", role="PRIMARY", relevance=0.95),
)


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _natural_answer_format(answer: int) -> AnswerFormat:
    """정답 형태 — 전건 양의 정수(부피·단위환산 모두 항상 양수)."""
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


# ── 직육면체·정육면체 부피: l×w×h ──────────────────────────────────────────
_DIM_RANGE = range(2, 16)
_VOLUME_TEMPLATES: tuple[str, ...] = (
    "가로 {length}cm, 세로 {width}cm, 높이 {height}cm인 직육면체의 부피를 구하시오.",
    "가로가 {length}cm, 세로가 {width}cm, 높이가 {height}cm인 직육면체 모양 상자의 부피를 "
    "구하시오.",
)


@dataclass(frozen=True, slots=True)
class _VolumeSkeleton:
    """직육면체 부피 뼈대 — 가로·세로·높이. 부피 = l×w×h. 단일 진실 원천."""

    length: int
    width: int
    height: int

    @property
    def answer(self) -> int:
        """정답 — l×w×h."""
        return self.length * self.width * self.height

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − (l×w×h) = 0'."""
        return f"x - ({self.length}*{self.width}*{self.height}) = 0"

    @property
    def difficulty(self) -> float:
        # 초등 5-6학년군 — 세 곱셈이라 겉넓이(세 곱셈+합+2배)보다 가볍다.
        difficulty = 2.0
        if max(self.length, self.width, self.height) >= 10:
            difficulty += 0.2
        if self.answer >= 1000:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_volume_pool() -> tuple[_VolumeSkeleton, ...]:
    """결정론 직육면체 부피 뼈대 풀 — l≤w≤h 열거(순서 대칭 회피)·목표 크기 도달 시 조기 종료."""
    target_size = 260
    pool: list[_VolumeSkeleton] = []
    for length in _DIM_RANGE:
        for width in _DIM_RANGE:
            if width < length:
                continue
            for height in _DIM_RANGE:
                if height < width:
                    continue
                pool.append(_VolumeSkeleton(length=length, width=width, height=height))
                if len(pool) >= target_size:
                    random.Random(_POOL_SEED).shuffle(pool)
                    return tuple(pool)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _volume_steps(skeleton: _VolumeSkeleton) -> list[str]:
    """부피 풀이의 검증 단계 체인(S2-02) — 곱셈식 → 값(표현식 동치·Tier2 correct)."""
    return [f"{skeleton.length}*{skeleton.width}*{skeleton.height}", str(skeleton.answer)]


def _volume_explanation(skeleton: _VolumeSkeleton) -> str:
    """부피 해설 — 가로×세로×높이를 자연어로 서술(결정론·위생 청정·등호 없는 서술형)."""
    return (
        "직육면체의 부피는 가로, 세로, 높이를 모두 곱하면 되므로, "
        f"구하는 부피는 {skeleton.answer} 이다."
    )


@deterministic_generator
class RectangularPrismVolumeSkeletonGenerator:
    """직육면체 부피 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    풀(l≤w≤h 열거·구조 유일)을 순서대로 소비(소진 시 None).
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-volume",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("RECT-PRISM-VOLUME",),
        concept_tags: Sequence[ConceptTag] = _VOLUME_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_volume_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 부피 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _VolumeSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        template = _VOLUME_TEMPLATES[self._index % len(_VOLUME_TEMPLATES)]
        question_text = template.format(
            length=skeleton.length, width=skeleton.width, height=skeleton.height
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
            difficulty_overall=skeleton.difficulty,
            question_format=QuestionFormat.단답형,
            answer_format=_natural_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_volume_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 직육면체 부피 스켈레톤 조립(l·w·h→l×w×h 계산)",
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
            solution_steps=_volume_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )


# ── 부피 단위 환산: m³ → cm³(항상 정수배 100³=1,000,000) ─────────────────────
_VOLUME_UNIT_FACTOR = 1_000_000
_VOLUME_UNIT_VALUE_RANGE = range(1, 51)
_VOLUME_UNIT_TEMPLATES: tuple[str, ...] = (
    "{big_value}m^3는 몇 cm^3인지 구하시오.",
    "{big_value}m^3를 cm^3로 나타내면 얼마인지 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _VolumeUnitSkeleton:
    """부피 단위 환산 뼈대 — m³ 값. 답 = m³ 값 × 1,000,000(대→소 방향은 항상 정수 곱)."""

    big_value: int

    @property
    def answer(self) -> int:
        return self.big_value * _VOLUME_UNIT_FACTOR

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − (big_value × 1,000,000) = 0'."""
        return f"x - ({self.big_value} * {_VOLUME_UNIT_FACTOR}) = 0"

    @property
    def difficulty(self) -> float:
        # 초등 5-6학년군 — 큰 배율 곱셈 1스텝(면적 환산의 km_to_m와 동급 난이도).
        difficulty = 1.8
        if self.big_value >= 20:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_volume_unit_pool() -> tuple[_VolumeUnitSkeleton, ...]:
    """결정론 부피 단위 환산 뼈대 풀 — big_value 열거(자연히 유일)·고정 시드 셔플."""
    pool = [_VolumeUnitSkeleton(big_value=v) for v in _VOLUME_UNIT_VALUE_RANGE]
    random.Random(_POOL_SEED + 1).shuffle(pool)
    return tuple(pool)


def _volume_unit_steps(skeleton: _VolumeUnitSkeleton) -> list[str]:
    """부피 단위 환산 풀이의 검증 단계 체인(S2-02) — 곱셈식 → 값(표현식 동치·Tier2 correct)."""
    return [f"{skeleton.big_value} * {_VOLUME_UNIT_FACTOR}", str(skeleton.answer)]


def _volume_unit_explanation(skeleton: _VolumeUnitSkeleton) -> str:
    """부피 단위 환산 해설 — 배율 곱셈을 자연어로 서술(결정론·위생 청정·조사 상수 하드코딩은
    의도적 — m³/cm³ 단위어 꼬리가 항상 "터"로 끝나는 고정 원인이라 하드코딩이 정답, 면적 환산
    생성기의 확립된 예외 관례 그대로 계승)."""
    return f"m^3를 cm^3로 바꿀 때는 정해진 배율을 곱하므로, 구하는 값은 {skeleton.answer} 이다."


@deterministic_generator
class VolumeUnitConversionSkeletonGenerator:
    """부피 단위 환산 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    풀(big_value 열거·구조 유일)을 순서대로 소비(소진 시 None).
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-volunit",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("VOLUME-UNIT-CONVERSION",),
        concept_tags: Sequence[ConceptTag] = _VOLUME_UNIT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_volume_unit_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 부피 단위 환산 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _VolumeUnitSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        template = _VOLUME_UNIT_TEMPLATES[self._index % len(_VOLUME_UNIT_TEMPLATES)]
        question_text = template.format(big_value=skeleton.big_value)
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
            answer_explanation=_volume_unit_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 부피 단위 환산 스켈레톤 조립(m^3 값→배율 곱셈)",
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
            solution_steps=_volume_unit_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )


# ── 원주: 지름 × 3.14(교육과정 지정 근삿값) ──────────────────────────────────
_DIAMETER_RANGE = range(1, 51)
_CIRCUMFERENCE_TEMPLATES: tuple[str, ...] = (
    "지름이 {diameter}cm인 원의 원주를 구하시오. (원주율은 3.14로 계산한다.)",
    "지름이 {diameter}cm인 원이 있다. 원주율을 3.14로 할 때, 이 원의 원주를 구하시오.",
)


def _cents_to_decimal_str(cents: int) -> str:
    """정수 '센트'(값×100) → 최소 자릿수 십진 문자열. 3.14 배율은 항상 소수 둘째 자리에서
    정확히 끝나므로(부동소수점 오차 없이 diameter*314로 계산) 문자열 변환도 정수 연산만 쓴다.
    """
    whole, remainder = divmod(cents, 100)
    if remainder == 0:
        return str(whole)
    if remainder % 10 == 0:
        return f"{whole}.{remainder // 10}"
    return f"{whole}.{remainder:02d}"


@dataclass(frozen=True, slots=True)
class _CircumferenceSkeleton:
    """원주 뼈대 — 지름. 원주 = 지름×3.14(교육과정 지정 근삿값). 단일 진실 원천.

    `answer_cents`(값×100)를 정수로 직접 계산해(diameter*314) 부동소수점을 전혀 거치지 않는다
    — 3.14=157/50이라 diameter가 정수면 결과는 항상 소수 둘째 자리에서 정확히 끝난다.
    """

    diameter: int

    @property
    def answer_cents(self) -> int:
        """정답×100 — diameter*314(정수 연산만·부동소수점 오차 0)."""
        return self.diameter * 314

    @property
    def answer(self) -> str:
        """정답 문자열 — 최소 자릿수 십진 표기(예 '31.4'·'3.14')."""
        return _cents_to_decimal_str(self.answer_cents)

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − (지름×314)/100 = 0'(3.14를 정수비로 표현해 정밀 유지)."""
        return f"x - ({self.diameter}*314)/100 = 0"

    @property
    def difficulty(self) -> float:
        # 초등 5-6학년군 — 소수 곱셈 1스텝이라 정수 곱셈류보다 약간 무겁다.
        difficulty = 2.1
        if self.diameter >= 20:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_circumference_pool() -> tuple[_CircumferenceSkeleton, ...]:
    """결정론 원주 뼈대 풀 — diameter 열거(자연히 유일)·고정 시드 셔플."""
    pool = [_CircumferenceSkeleton(diameter=d) for d in _DIAMETER_RANGE]
    random.Random(_POOL_SEED + 2).shuffle(pool)
    return tuple(pool)


def _circumference_steps(skeleton: _CircumferenceSkeleton) -> list[str]:
    """원주 풀이의 검증 단계 체인(S2-02) — 곱셈식 → 값(표현식 동치·Tier2 correct).

    식은 `diameter * 3.14`(부동소수점 리터럴)가 아니라 `(diameter*314)/100`(정수비)로 쓴다 —
    스파이크 테스트 실측(2026-08-07): `verify_step`의 `simplify(diff).is_zero` 동치 판정은
    Float 리터럴("3.14") 간 비교에서 정밀도 표현 차이로 거짓 incorrect를 낸다("5 * 3.14" vs
    "15.7" → incorrect). 정수비로 쓰면 정확히 correct로 판정된다 — 조건식(`condition`)과
    동일한 정수비 표현을 재사용(단일 진실 원천 일관성).
    """
    return [f"({skeleton.diameter}*314)/100", skeleton.answer]


def _circumference_explanation(skeleton: _CircumferenceSkeleton) -> str:
    """원주 해설 — 지름×3.14를 자연어로 서술(결정론·위생 청정·등호 없는 서술형)."""
    return (
        "원의 원주는 지름에 원주율(3.14)을 곱하면 되므로, "
        f"구하는 원주는 {skeleton.answer}cm 이다."
    )


@deterministic_generator
class CircleCircumferenceSkeletonGenerator:
    """원주 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    풀(diameter 열거·구조 유일)을 순서대로 소비(소진 시 None). 답이 소수라
    `AnswerFormat.실수`를 쓴다(교육과정이 3.14 근삿값을 지정하므로 기약분수 표기가 아님).
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-circumference",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("CIRCLE-CIRCUMFERENCE",),
        concept_tags: Sequence[ConceptTag] = _CIRCUMFERENCE_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_circumference_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 원주 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _CircumferenceSkeleton
    ) -> CandidateProblem:
        answer_text = skeleton.answer
        template = _CIRCUMFERENCE_TEMPLATES[self._index % len(_CIRCUMFERENCE_TEMPLATES)]
        question_text = template.format(diameter=skeleton.diameter)
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
            answer_format=AnswerFormat.실수,
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_circumference_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 원주 스켈레톤 조립(지름×3.14 계산)",
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
            solution_steps=_circumference_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )
