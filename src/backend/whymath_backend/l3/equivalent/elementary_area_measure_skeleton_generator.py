"""초등 도형과 측정 — 넓이 단위 환산·직육면체 겉넓이 스켈레톤 생성기 — W2 Phase1 #4(결정론·LLM 0).

W2 계획 문서(§6 Phase1 항목4)의 원 타깃은 "초등 둘레·넓이(직사각형·삼각형)"였으나, 착수 전
재확인 결과 [6수03-11](평면도형의 둘레)·[6수03-13](직사각형·정사각형의 넓이)·[6수03-14]
(평행사변형·삼각형·사다리꼴·마름모의 넓이)는 `misconception_eval_mc_generator`가 이미 커버
하고 있었다(계획 문서 작성 시점 대비 커버리지 이동) — 중복 착수 대신 같은 도메인(초등 도형과
측정)의 **진짜 0커버** 성취기준으로 스코프를 조정한다: [6수03-12](넓이 단위 ㎠·㎡·㎢)·
[6수03-17](직육면체의 겉넓이).

두 클래스:
- `AreaUnitConversionSkeletonGenerator` — 큰 단위→작은 단위 환산(m²→cm²·km²→m²). 환산은
  항상 곱셈이라 결과가 정수로 딱 떨어진다(나눗셈 방향은 나머지 처리가 필요해 v1 범위 밖).
- `RectangularPrismSurfaceAreaSkeletonGenerator` — 직육면체 겉넓이 2(lw+lh+wh).

핵심 통찰(재구현 0): 두 문제군 모두 "x에 대한 방정식의 유일해"로 환원된다. 조건식을 그대로
`x − (환산식/겉넓이 공식) = 0`으로 공급하면 기존 근 검증 스택이 무변경 재사용된다.

⚠️ 표기 주의(**중요·이 생성기 고유 발견**): **㎠·㎡·㎢ 등 CJK 제곱단위 합성 글리프를 쓰지
않는다** — cm^2·m^2·km^2 ASCII 캐럿 표기를 쓴다(기존 `quadratic_inequality_boundary_
skeleton_generator`의 "2x^2" 관례 계승·notation_coverage_eval 게이트 사전 확인 결과 이
CJK 글리프들은 코퍼스 어디에도·베이스라인에도 없어 신규 글리프로 즉시 거부된다).

⚠️ 조사 주의(**실측 발견**): `josa.has_batchim_text`는 알파벳 단위 꼬리("3m^2" 등)를 읽지
못하고 항상 받침-有 기본값으로 폴백한다(m/cm/km이 실제로는 모두 "터"로 끝나 받침 無 — 을/는이
맞는데 엔진은 을/은을 반환). 이 생성기는 **의도적으로 상수 조사(를/는)를 하드코딩**한다 —
버그가 아니라, 조사가 달라지는 이유가 "변하는 숫자"가 아니라 "고정된 단위어 꼬리"이기 때문에
하드코딩이 오히려 정답이다(형제 생성기들의 "숫자에 따라 달라지는 조사 하드코딩 금지"와 대비
되는 반례 — 원인이 다르면 처방도 다르다).

범위(v1): 정수 값·인접 단위쌍(m↔cm, km↔m)만·대→소 방향만. 소→대 방향(나눗셈)·비인접 단위
(cm↔km)·원기둥/각기둥 겉넓이는 후속.

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지(canonicalize)·L1(ConceptTag)만
import(L4 참조 0). 난이도는 지역 함수(공유 difficulty.py 불침범·도메인 분담 관례 계승).
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
    "AreaUnitConversionSkeletonGenerator",
    "AreaUnitPair",
    "RectangularPrismSurfaceAreaSkeletonGenerator",
]

_POOL_SEED = 20260807

_UNIT_CONVERSION_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="ME2", role="PRIMARY", relevance=0.95),
)
_SURFACE_AREA_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="ME7", role="PRIMARY", relevance=0.95),
)


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _natural_answer_format(answer: int) -> AnswerFormat:
    """정답 형태 — v1은 전건 양의 정수(단위 환산·겉넓이 모두 항상 양수)."""
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


# ── 넓이 단위 환산: 큰 단위 → 작은 단위(항상 정수배) ─────────────────────────
AreaUnitPair = Literal["m_to_cm", "km_to_m"]

_UNIT_PAIR_INFO: dict[AreaUnitPair, tuple[str, str, int, range]] = {
    # (큰 단위, 작은 단위, 환산 배율, 큰 단위 값 범위)
    "m_to_cm": ("m", "cm", 10_000, range(1, 51)),
    "km_to_m": ("km", "m", 1_000_000, range(1, 21)),
}
_CONVERSION_TEMPLATES: tuple[str, ...] = (
    "{big_value}{big_unit}^2는 몇 {small_unit}^2인지 구하시오.",
    "{big_value}{big_unit}^2를 {small_unit}^2로 나타내면 얼마인지 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _ConversionSkeleton:
    """넓이 단위 환산 뼈대 — 단위쌍·큰 단위 값. 답 = 큰 단위 값 × 환산 배율. 단일 진실 원천."""

    pair: AreaUnitPair
    big_value: int

    @property
    def big_unit(self) -> str:
        return _UNIT_PAIR_INFO[self.pair][0]

    @property
    def small_unit(self) -> str:
        return _UNIT_PAIR_INFO[self.pair][1]

    @property
    def factor(self) -> int:
        return _UNIT_PAIR_INFO[self.pair][2]

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
        # 초등 5-6학년군 기준 — 단위 환산은 곱셈 1스텝이라 낮게(awareness~procedural 경계).
        difficulty = 1.6
        if self.factor >= 1_000_000:
            difficulty += 0.2
        if self.big_value >= 20:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_conversion_pool(pair: AreaUnitPair | None = None) -> tuple[_ConversionSkeleton, ...]:
    """결정론 단위 환산 뼈대 풀 — 단위쌍×값 열거·구조 키 자연 유일·고정 시드 셔플.

    `pair`가 값별로 서로 다른 range를 순회하므로 (pair, big_value) 튜플은 항상 자연히 유일
    (dedup 불필요) — 답은 단위쌍이 다르면 배율이 달라 우연 충돌이 드물지만, 이 도메인도
    좌표기하 생성기와 같은 이유(같은 값이 다른 조합에서 재출현해도 정상)로 답 기준 dedup은
    쓰지 않는다.
    """
    pairs: tuple[AreaUnitPair, ...] = ("m_to_cm", "km_to_m") if pair is None else (pair,)
    pool: list[_ConversionSkeleton] = []
    for p in pairs:
        _, _, _, value_range = _UNIT_PAIR_INFO[p]
        for big_value in value_range:
            pool.append(_ConversionSkeleton(pair=p, big_value=big_value))
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _conversion_steps(skeleton: _ConversionSkeleton) -> list[str]:
    """단위 환산 풀이의 검증 단계 체인(S2-02) — 곱셈식 → 값(표현식 동치·Tier2 correct)."""
    return [f"{skeleton.big_value} * {skeleton.factor}", str(skeleton.answer)]


def _conversion_explanation(skeleton: _ConversionSkeleton) -> str:
    """단위 환산 해설 — 배율 곱셈을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    return (
        f"{skeleton.big_unit}^2를 {skeleton.small_unit}^2로 바꿀 때는 정해진 배율을 곱하므로, "
        f"구하는 값은 {skeleton.answer} 이다."
    )


@deterministic_generator
class AreaUnitConversionSkeletonGenerator:
    """넓이 단위 환산 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `pair`(m_to_cm/km_to_m) 필터로 밴드를 분리한다(direction/kind 필터 관례 계승 — 필터
    없이 밴드별 인스턴스를 만들면 고정 시드 풀이 처음부터 재생돼 같은 뼈대를 중복 방출한다).
    """

    def __init__(
        self,
        *,
        pair: AreaUnitPair | None = None,
        slug_prefix: str = "wm-areaunit",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("AREA-UNIT-CONVERSION",),
        concept_tags: Sequence[ConceptTag] = _UNIT_CONVERSION_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_conversion_pool(pair)
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 단위 환산 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _ConversionSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        template = _CONVERSION_TEMPLATES[self._index % len(_CONVERSION_TEMPLATES)]
        question_text = template.format(
            big_value=skeleton.big_value,
            big_unit=skeleton.big_unit,
            small_unit=skeleton.small_unit,
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
            answer_explanation=_conversion_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 넓이 단위 환산 스켈레톤 조립(단위쌍·값→배율 곱셈)",
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
            solution_steps=_conversion_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )


# ── 직육면체 겉넓이: 2(lw+lh+wh) ──────────────────────────────────────────────
_DIM_RANGE = range(2, 16)
_SURFACE_AREA_TEMPLATES: tuple[str, ...] = (
    "가로 {length}cm, 세로 {width}cm, 높이 {height}cm인 직육면체의 겉넓이를 구하시오.",
    "가로가 {length}cm, 세로가 {width}cm, 높이가 {height}cm인 직육면체 모양 상자의 겉넓이를 "
    "구하시오.",
)


@dataclass(frozen=True, slots=True)
class _SurfaceAreaSkeleton:
    """직육면체 겉넓이 뼈대 — 가로·세로·높이. 겉넓이 = 2(lw+lh+wh). 단일 진실 원천."""

    length: int
    width: int
    height: int

    @property
    def answer(self) -> int:
        """정답 — 2(lw+lh+wh)."""
        return 2 * (self.length * self.width + self.length * self.height + self.width * self.height)

    @property
    def formula(self) -> str:
        """겉넓이 공식의 SymPy 계산식. condition·steps의 단일 진실 원천."""
        return (
            f"2*({self.length}*{self.width} + {self.length}*{self.height} "
            f"+ {self.width}*{self.height})"
        )

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − 2(lw+lh+wh) = 0'."""
        return f"x - ({self.formula}) = 0"

    @property
    def difficulty(self) -> float:
        # 초등 5-6학년군 기준 — 세 곱셈+합+2배라 단위 환산(1.6~1.8)보단 무겁다(procedural 상단).
        difficulty = 2.2
        if max(self.length, self.width, self.height) >= 10:
            difficulty += 0.2
        if self.answer >= 600:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_surface_area_pool() -> tuple[_SurfaceAreaSkeleton, ...]:
    """결정론 직육면체 겉넓이 뼈대 풀 — l≤w≤h 열거(순서 대칭 회피)·목표 크기 도달 시 조기 종료."""
    target_size = 260
    pool: list[_SurfaceAreaSkeleton] = []
    for length in _DIM_RANGE:
        for width in _DIM_RANGE:
            if width < length:
                continue
            for height in _DIM_RANGE:
                if height < width:
                    continue
                pool.append(_SurfaceAreaSkeleton(length=length, width=width, height=height))
                if len(pool) >= target_size:
                    random.Random(_POOL_SEED + 1).shuffle(pool)
                    return tuple(pool)
    random.Random(_POOL_SEED + 1).shuffle(pool)
    return tuple(pool)


def _surface_area_steps(skeleton: _SurfaceAreaSkeleton) -> list[str]:
    """겉넓이 풀이의 검증 단계 체인(S2-02) — 공식 대입식 → 값(표현식 동치·Tier2 correct)."""
    return [skeleton.formula, str(skeleton.answer)]


def _surface_area_explanation(skeleton: _SurfaceAreaSkeleton) -> str:
    """겉넓이 해설 — 세 쌍의 마주 보는 면의 넓이 합을 자연어로 서술(결정론·위생 청정)."""
    return (
        "직육면체의 겉넓이는 서로 다른 세 면의 넓이를 더한 뒤 2배 하면 되므로, "
        f"구하는 겉넓이는 {skeleton.answer} 이다."
    )


@deterministic_generator
class RectangularPrismSurfaceAreaSkeletonGenerator:
    """직육면체 겉넓이 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    풀(l≤w≤h 열거·구조 유일)을 순서대로 소비(소진 시 None).
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-surfarea",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("RECT-PRISM-SURFACE-AREA",),
        concept_tags: Sequence[ConceptTag] = _SURFACE_AREA_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_surface_area_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 겉넓이 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _SurfaceAreaSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        template = _SURFACE_AREA_TEMPLATES[self._index % len(_SURFACE_AREA_TEMPLATES)]
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
            answer_explanation=_surface_area_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 직육면체 겉넓이 스켈레톤 조립(l·w·h→2(lw+lh+wh) 계산)",
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
            solution_steps=_surface_area_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )
