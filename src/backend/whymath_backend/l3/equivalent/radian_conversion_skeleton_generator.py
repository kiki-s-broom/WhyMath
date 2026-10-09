"""고등 일반각과 호도법(도↔라디안 변환) 스켈레톤 생성기 — W2 Phase4 #5(결정론·LLM 0).

`[12대수02-01]`("일반각과 호도법의 뜻을 알고, 그 관계를 설명할 수 있다." — NCIC 실측,
2026-08-09)의 첫 코퍼스. `kind`가 방향을 가르되 성취기준 코드는 **하나를 공유**한다
(measurement_unit_conversion 생성기의 "여러 kind가 한 코드 공유" 패턴 재사용 — 이 코드
자체가 "도↔라디안 관계"를 양방향으로 서술해 방향별 분리 코드가 없다):
- `deg_to_rad` → 도 단위 일반각을 호도법(라디안, π 분수)으로.
- `rad_to_deg` → 호도법(라디안, π 분수)을 도 단위로.

**설계**: d=15k(k는 0이 아닌 정수, |k|≤36 — 최대 ±540°까지 다루어 "일반각"의 핵심(0~360°를
넘거나 음의 각도 허용)을 실제로 겨눈다)만 다룬다. 180=15×12라서 d=15k의 기약분수 표현은
항상 분모가 12의 약수(1/2/3/4/6/12)로 떨어져(gcd(k,12)로 소거) 전형적 "특수각" 라디안
분수 계열(π/6·π/4·π/3·π/2·π 등과 그 정수배)만 노출된다 — 임의 정수도를 그대로 쓰면
분모가 지저분해져 교과서 관례를 벗어난다.

**검증 설계**: 조건식은 답을 *원 변환 공식*(라디안=도×π/180, 도=분자×180/분모)으로 독립
재계산해 검산한다 — 기약분수 계산(gcd 소거) 로직 자체의 버그도 잡아낸다(단순 자기복제
등식이 아님). `AnswerFormat.식`을 이 세션에서 처음 사용(라디안 답은 자연수/분수/실수가
아니라 π 포함 식) — SymPy `sympify`가 `pi`를 상수 심볼로 즉시 접어 `verify_answer`의
자유변수 없는 직접 수치 평가 경로를 그대로 탄다(신규 분기 불요, 스파이크 테스트로 실측
확인 — 2026-08-09).

표기: 유니코드 π 대신 ASCII `pi`를 계속 쓴다(calculus2_trig_integral 생성기의 방어적
선례 계승 — 신규 글리프 위험 회피). 도(°) 기호는 trig_skeleton_generator 등 기존
생성기가 이미 안전하게 쓰는 기호라 그대로 재사용한다.

concept_src_id(legacy 437 개념그래프 `source_id` 필드 실측 확인 — 2026-08-09):
  H:12대수02-01=[12대수02-01](양쪽 kind 공유).

범위(v1 단순화): 특수각 계열(분모 12의 약수)만 — 임의 정수도(분모가 지저분해지는 경우)·
호도법 단위의 삼각비 계산은 범위 밖.

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
    "RADIAN_STANDARD_CODE",
    "RadianConversionKind",
    "RadianConversionSkeletonGenerator",
]

_POOL_SEED = 20260809

RADIAN_STANDARD_CODE = "[12대수02-01]"
_CONCEPT_SRC_ID = "H:12대수02-01"

RadianConversionKind = Literal["deg_to_rad", "rad_to_deg"]

# d=15k, k≠0, |k|≤36 → |d|≤540(±1.5바퀴 — 일반각 핵심을 실제로 겨눔). 180=15×12라서 기약분수
# 분모가 항상 12의 약수로 떨어진다(본문 설계 절 참조).
_K_RANGE = tuple(k for k in range(-36, 37) if k != 0)


def _reduced_radian(degree: int) -> tuple[int, int]:
    """도 정수를 π 기약분수(분자,분모)로 — gcd 소거(분모는 항상 12의 약수, d=15k 불변식)."""
    g = math.gcd(abs(degree), 180)
    return degree // g, 180 // g


def _radian_display(numerator: int, denominator: int) -> str:
    """π 기약분수 표기('5*pi/6'·'-pi/2'·'3*pi') — 분자 1·분모 1 생략 규칙."""
    sign = "-" if numerator < 0 else ""
    magnitude = abs(numerator)
    coeff = "" if magnitude == 1 else f"{magnitude}*"
    return f"{sign}{coeff}pi" if denominator == 1 else f"{sign}{coeff}pi/{denominator}"


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """도↔라디안 뼈대 — degree=15k(단일 진실 원천), 라디안 기약분수는 그로부터 파생."""

    kind: RadianConversionKind
    degree: int

    @property
    def radian_fraction(self) -> tuple[int, int]:
        return _reduced_radian(self.degree)

    @property
    def answer_text(self) -> str:
        if self.kind == "deg_to_rad":
            numerator, denominator = self.radian_fraction
            return _radian_display(numerator, denominator)
        return str(self.degree)

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 원 변환 공식으로 독립 재계산(기약분수 gcd 소거 버그도 포착)."""
        if self.kind == "deg_to_rad":
            return f"y = ({self.degree}) * pi / 180"
        numerator, denominator = self.radian_fraction
        return f"y = ({numerator}) * 180 / ({denominator})"

    @property
    def difficulty(self) -> float:
        difficulty = 2.0
        if abs(self.degree) > 360:
            difficulty += 0.3  # 한 바퀴(360°)를 넘는 일반각 — 난도 상승.
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_pool(kind: RadianConversionKind | None = None) -> tuple[_Skeleton, ...]:
    """결정론 뼈대 풀 — kind별 degree=15k 전수(고정 시드 셔플, 조합공간이 작아 전수 열거)."""
    kinds: tuple[RadianConversionKind, ...] = (
        ("deg_to_rad", "rad_to_deg") if kind is None else (kind,)
    )
    pool: list[_Skeleton] = []
    rng = random.Random(_POOL_SEED)
    for kd in kinds:
        for k in _K_RANGE:
            pool.append(_Skeleton(kind=kd, degree=15 * k))
    rng.shuffle(pool)
    return tuple(pool)


def _natural_answer_format(answer: int) -> AnswerFormat:
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


@deterministic_generator
class RadianConversionSkeletonGenerator:
    """도↔라디안 변환 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `kind` 필터로 밴드(변환 방향)를 분리한다. 두 방향 모두 같은 성취기준 코드를 공유하므로
    (measurement_unit_conversion 관례) `kind` 필터 없이 밴드별 인스턴스를 만들면 같은
    degree 전수 풀이 두 방향에 그대로 재사용돼 방향이 섞이지 않는다 — 단, 명시적 `kind`
    지정이 여전히 권장(배치 스크립트의 밴드 분리 관례 일관성).
    """

    def __init__(
        self,
        *,
        kind: RadianConversionKind | None = None,
        slug_prefix: str = "wm-radconv",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("RADIAN-CONVERSION",),
    ) -> None:
        self._pool = _build_pool(kind)
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(skeleton)

    def _assemble(self, skeleton: _Skeleton) -> CandidateProblem:
        answer_text = skeleton.answer_text
        if skeleton.kind == "deg_to_rad":
            question_text = f"일반각 {skeleton.degree}°를 호도법으로 나타내면 얼마인가?"
            answer_format = AnswerFormat.식
            explanation = (
                f"호도법 값은 도 × pi/180으로 구한다. {skeleton.degree}°는 기약분수로 "
                f"약분하면 {answer_text} 이다."
            )
        else:
            numerator, denominator = skeleton.radian_fraction
            radian_display = _radian_display(numerator, denominator)
            question_text = (
                f"일반각의 호도법 표시 {radian_display}를 도(°) 단위로 나타내면 얼마인가?"
            )
            answer_format = _natural_answer_format(skeleton.degree)
            explanation = (
                f"도 값은 라디안 분수 × 180/pi으로 구한다. {radian_display}는 도 단위로 "
                f"환산하면 {answer_text} 이다."
            )

        standard_codes = [RADIAN_STANDARD_CODE]
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
            answer_format=answer_format,
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
                    "결정론 도↔라디안 스켈레톤 조립(degree=15k→기약분수 gcd 소거)",
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
            concept_tags=[
                ConceptTag(concept_src_id=_CONCEPT_SRC_ID, role="PRIMARY", relevance=0.95)
            ],
        )
