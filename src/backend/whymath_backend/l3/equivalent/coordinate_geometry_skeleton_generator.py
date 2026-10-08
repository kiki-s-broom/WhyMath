"""좌표평면 — 두 점 사이의 거리·직선의 방정식 스켈레톤 생성기 — W2 Phase1 #3(결정론·LLM 0).

`quadratic_inequality_boundary_skeleton_generator`(고1 방정식과 부등식) 다음으로 처음
착점하는 신규 도메인(고1 도형의 방정식)이지만, 수학 실체는 순수 좌표 대수(피타고라스 정리·
기울기 공식)라 기존 근 검증 스택을 그대로 재사용한다. 배경(도메인 분담): [10공수2-01-01]
(두 점 사이의 거리)·[10공수2-01-02](직선의 방정식)이 0건이었다 — 이 생성기가 두 성취기준의
첫 코퍼스를 확보한다.

두 클래스:
- `PointDistanceSkeletonGenerator` — 피타고라스 삼조(3,4,5 등) 기반으로 dx·dy를 골라 거리가
  항상 정수가 되게 구성. 두 점을 그대로 발문에 노출(좌표 자체는 계산 재료일 뿐 답이 아니므로
  자명화 우려 없음 — quad_ineq의 근 노출 금지와는 다른 성격).
- `LineEquationSkeletonGenerator` — 기울기 a·절편 b를 먼저 정수로 고정한 뒤 두 번째 점을
  역산으로 구성(항상 정수 기울기 보장). 답은 a+b(직선의 방정식 y=ax+b 전체를 노출하지 않고
  단답형 수치로 환원 — quad_ineq의 "근의 합" 트릭과 동일 정신).

핵심 통찰(재구현 0): 두 문제군 모두 "x에 대한 방정식의 유일해"로 환원된다. **원시 좌표에서
공식을 다시 유도**하는 SymPy 계산식을 조건으로 공급한다(생성기가 미리 계산해 둔 dx·dy·a·b가
아니라 x1·y1·x2·y2 그 자체로부터) — 그래야 SymPy가 생성기의 파이썬 계산과 **독립적으로**
거리·기울기·절편을 재유도해 교차 검증한다(생성≠검증, 형제 생성기 전원의 관례).

⚠️ 구조 dedup 주의(quad_ineq 관례 계승, 형제 수열 생성기와 다름): 서로 다른 좌표쌍이 **같은
거리**·**같은 a+b**를 내는 것은 정상이다(예: (0,0)-(3,4)와 (1,1)-(4,5)는 둘 다 거리 5). 답
기준으로 dedup하면 이런 정당한 재출현을 오병합으로 취급하게 되므로, 여기서는 **원시 파라미터
튜플**(구조적 키)로만 dedup한다. 오케스트레이터의 구조 dedup도 조건식을 답으로 접으므로,
배치에서 반드시 `signature_index=None`으로 호출한다(quad_ineq_batch 관례 그대로).

⚠️ 표기 주의: 좌표 `(x, y)` 표기의 콤마·괄호는 ASCII라 신규 글리프가 아니다(notation_coverage
_eval 게이트 사전 확인 — S4-27 α·β 사고 이후 이 세션의 모든 신규 생성기가 발문 표기를 먼저
검증한다). 조사(을/를)는 괄호 뒤에서도 `josa.has_batchim_text`가 수식 꼬리(S3-12 확장 규칙)로
마지막 숫자를 읽어 올바르게 판별한다(실측 확인) — 하드코딩 금지.

범위(v1): 정수 좌표·정수 답(거리·a+b)만. 원의 방정식·점과 직선 사이의 거리·평행/수직 판정·
대칭이동은 후속(별도 스켈레톤 설계 필요).

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지(canonicalize)·L1(ConceptTag)만
import(L4 참조 0). 난이도는 지역 함수(공유 difficulty.py 불침범·도메인 분담 관례 계승).
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
from whymath_backend.lang.josa import eul_reul, wa_gwa
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
    "LineEquationSkeletonGenerator",
    "PointDistanceSkeletonGenerator",
]

_POOL_SEED = 20260807

_DISTANCE_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="HK17", role="PRIMARY", relevance=0.95),
)
_LINE_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="HK19", role="PRIMARY", relevance=0.95),
)


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _int_answer_format(answer: int) -> AnswerFormat:
    """정답 형태 — 양의 정수=자연수·그 외(0·음수)=실수(형제 생성기 자연수/실수 분기 미러).

    스키마에 정수 전용 항목이 없어(자연수/분수/실수/식) 형제 생성기와 동일하게 실수로 묶는다.
    """
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


# ── 두 점 사이의 거리: 피타고라스 삼조(dx, dy, 거리) ──────────────────────────
_TRIPLES: tuple[tuple[int, int, int], ...] = (
    (3, 4, 5),
    (6, 8, 10),
    (9, 12, 15),
    (5, 12, 13),
    (8, 15, 17),
    (7, 24, 25),
    (20, 21, 29),
    (12, 16, 20),
    (10, 24, 26),
    (15, 20, 25),
)
_DISTANCE_COORD_RANGE = range(-6, 7, 3)  # -6, -3, 0, 3, 6
_DISTANCE_POOL_TARGET = 260

_DISTANCE_TEMPLATES: tuple[str, ...] = (
    "두 점 A({x1}, {y1}), B({x2}, {y2}) 사이의 거리를 구하시오.",
    "좌표평면 위의 두 점 ({x1}, {y1}){wa_gwa} ({x2}, {y2}) 사이의 거리를 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _DistanceSkeleton:
    """두 점 거리 뼈대 — 좌표 x1·y1·x2·y2. 거리 = √((x2−x1)²+(y2−y1)²). 단일 진실 원천."""

    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def answer(self) -> int:
        """정답 — 피타고라스 삼조로 구성해 항상 정수(제곱근이 정확히 떨어짐)."""
        dx = self.x2 - self.x1
        dy = self.y2 - self.y1
        return math.isqrt(dx * dx + dy * dy)

    @property
    def formula(self) -> str:
        """거리 공식의 SymPy 계산식 — 원시 좌표에서 재유도(독립 재계산의 근거)."""
        return f"sqrt(({self.x2} - {self.x1})**2 + ({self.y2} - {self.y1})**2)"

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − √((x2−x1)²+(y2−y1)²) = 0'."""
        return f"x - ({self.formula}) = 0"

    @property
    def difficulty(self) -> float:
        # QUAD-EQ(base 2.0) 대비: 좌표 차·제곱·합·루트까지 4단계라 등차합(1.9)보단 무겁지만
        # 공식 1개 직대입이라 거듭제곱 합(2.1~2.3)보단 가볍다.
        difficulty = 2.0
        if abs(self.x1) >= 6 or abs(self.y1) >= 6:
            difficulty += 0.1
        if self.answer >= 20:
            difficulty += 0.2
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_distance_pool() -> tuple[_DistanceSkeleton, ...]:
    """결정론 두 점 거리 뼈대 풀 — 피타고라스 삼조×부호×시작점 열거·**구조 키 dedup**·고정 셔플.

    답(거리) 기준이 아니라 원시 파라미터(x1,y1,x2,y2) 튜플로 dedup한다 — 서로 다른 좌표쌍이
    같은 거리를 내는 것은 정상이라 답 기준 dedup은 부적절(quad_ineq 관례).
    """
    seen: set[tuple[int, int, int, int]] = set()
    pool: list[_DistanceSkeleton] = []
    for leg_a, leg_b, _dist in _TRIPLES:
        for dx_base, dy_base in ((leg_a, leg_b), (leg_b, leg_a)):
            for sign_x in (1, -1):
                for sign_y in (1, -1):
                    dx = sign_x * dx_base
                    dy = sign_y * dy_base
                    for x1 in _DISTANCE_COORD_RANGE:
                        for y1 in _DISTANCE_COORD_RANGE:
                            x2, y2 = x1 + dx, y1 + dy
                            key = (x1, y1, x2, y2)
                            if key in seen:
                                continue
                            seen.add(key)
                            pool.append(_DistanceSkeleton(x1=x1, y1=y1, x2=x2, y2=y2))
                            if len(pool) >= _DISTANCE_POOL_TARGET:
                                random.Random(_POOL_SEED).shuffle(pool)
                                return tuple(pool)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _distance_steps(formula: str, answer: int) -> list[str]:
    """거리 풀이의 검증 단계 체인(S2-02) — 공식 대입식 → 값(표현식 동치·Tier2 correct)."""
    return [formula, str(answer)]


def _distance_explanation(skeleton: _DistanceSkeleton) -> str:
    """거리 해설 — 피타고라스 정리를 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    return (
        "두 점 사이의 거리는 가로 좌표 차와 세로 좌표 차를 두 변으로 하는 직각삼각형의 빗변과 "
        f"같으므로, 구하는 거리는 {skeleton.answer} 이다."
    )


@deterministic_generator
class PointDistanceSkeletonGenerator:
    """두 점 사이의 거리 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    풀(구조 키 유일)을 순서대로 소비(소진 시 None). 답(거리) 중복은 정상이라 skip은 없다
    (형제 생성기의 `skip_signatures`/`skip_conditions`는 답 유일 도메인 전용 패턴).
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-ptdist",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("POINT-DISTANCE",),
        concept_tags: Sequence[ConceptTag] = _DISTANCE_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_distance_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 두 점 거리 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _DistanceSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        template = _DISTANCE_TEMPLATES[self._index % len(_DISTANCE_TEMPLATES)]
        question_text = template.format(
            x1=skeleton.x1,
            y1=skeleton.y1,
            x2=skeleton.x2,
            y2=skeleton.y2,
            wa_gwa=wa_gwa(f"({skeleton.x1}, {skeleton.y1})"),
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
            answer_format=_int_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_distance_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 두 점 거리 스켈레톤 조립(피타고라스 삼조→좌표→거리 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=skeleton.condition,  # x - sqrt(...) = 0(검산용·독립 재계산)
            answer_map={"x": answer_text},
            answer_selection="unique",
            solution_steps=_distance_steps(skeleton.formula, skeleton.answer),
            concept_tags=list(self._concept_tags),
        )


# ── 직선의 방정식: 기울기 a·y절편 b(직선 y=ax+b, 답은 a+b) ────────────────────
_SLOPE_RANGE = range(-5, 6)  # 0 포함 — 수평선도 유효한 직선.
_X1_RANGE = range(-6, 7)
_DX_RANGE = tuple(d for d in range(-6, 7) if d != 0)  # x1≠x2(수직선 배제).
_LINE_POOL_TARGET = 260

_LINE_TEMPLATES: tuple[str, ...] = (
    "두 점 ({x1}, {y1}), ({x2}, {y2}){a_josa} 지나는 직선의 방정식이 y=ax+b 꼴일 때, "
    "a+b의 값을 구하시오.",
    "좌표평면 위의 두 점 ({x1}, {y1}), ({x2}, {y2})를 지나는 직선을 y=ax+b로 나타낼 때, "
    "a와 b의 합을 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _LineSkeleton:
    """직선 뼈대 — 좌표 x1·y1·x2·y2(기울기 a·y1로부터 역산 구성). 단일 진실 원천."""

    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def answer(self) -> int:
        """정답 — a+b. a=(y2−y1)/(x2−x1)·b=y1−a·x1(구성상 항상 정수로 나누어떨어짐)."""
        slope = (self.y2 - self.y1) // (self.x2 - self.x1)
        intercept = self.y1 - slope * self.x1
        return slope + intercept

    @property
    def formula(self) -> str:
        """a+b의 SymPy 계산식 — 원시 좌표에서 기울기·절편을 재유도(독립 재계산의 근거)."""
        dy = f"({self.y2} - {self.y1})"
        dx = f"({self.x2} - {self.x1})"
        slope = f"({dy}/{dx})"
        intercept = f"({self.y1} - {slope}*{self.x1})"
        return f"{slope} + {intercept}"

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − (a+b) = 0'."""
        return f"x - ({self.formula}) = 0"

    @property
    def difficulty(self) -> float:
        # QUAD-EQ(base 2.0) 대비: 기울기·절편 2단계 유도 후 합산이라 순수 대입보단 무겁다.
        difficulty = 2.2
        if abs(self.x1) >= 5 or abs(self.y1) >= 5:
            difficulty += 0.1
        if abs(self.answer) >= 15:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_line_pool() -> tuple[_LineSkeleton, ...]:
    """결정론 직선 뼈대 풀 — 기울기 a·시작점(x1,y1)·dx 열거(정수 기울기 보장)·**구조 키 dedup**.

    기울기 a를 먼저 정수로 고정하고 y2=y1+a·dx로 역산하므로 나눗셈 나머지가 항상 0이다
    (필터링 불필요 — 구성 자체가 정수 보장). 답(a+b) 기준이 아니라 원시 파라미터(x1,y1,x2,y2)
    로 dedup한다(두 점 거리 생성기와 동일 전략 — 답 재출현은 정상).
    """
    seen: set[tuple[int, int, int, int]] = set()
    pool: list[_LineSkeleton] = []
    for slope in _SLOPE_RANGE:
        for x1 in _X1_RANGE:
            for y1 in _X1_RANGE:
                for dx in _DX_RANGE:
                    x2 = x1 + dx
                    y2 = y1 + slope * dx
                    key = (x1, y1, x2, y2)
                    if key in seen:
                        continue
                    seen.add(key)
                    pool.append(_LineSkeleton(x1=x1, y1=y1, x2=x2, y2=y2))
                    if len(pool) >= _LINE_POOL_TARGET:
                        random.Random(_POOL_SEED + 1).shuffle(pool)
                        return tuple(pool)
    random.Random(_POOL_SEED + 1).shuffle(pool)
    return tuple(pool)


def _line_steps(formula: str, answer: int) -> list[str]:
    """직선 풀이의 검증 단계 체인(S2-02) — 공식 대입식 → 값(표현식 동치·Tier2 correct)."""
    return [formula, str(answer)]


def _line_explanation(skeleton: _LineSkeleton) -> str:
    """직선 해설 — 기울기·절편 유도를 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    return (
        "두 점을 지나는 직선의 기울기는 좌표 차의 비로 구하고, 절편은 한 점을 대입해 구할 수 "
        f"있으므로, 기울기와 절편을 더한 값은 {skeleton.answer} 이다."
    )


@deterministic_generator
class LineEquationSkeletonGenerator:
    """직선의 방정식 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    풀(구조 키 유일)을 순서대로 소비(소진 시 None). 두 점 거리 형제와 동일 좌석·게이트·근
    검증 스택을 공유한다.
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-lineeq",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("LINE-EQUATION",),
        concept_tags: Sequence[ConceptTag] = _LINE_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_line_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 직선 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _LineSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        template = _LINE_TEMPLATES[self._index % len(_LINE_TEMPLATES)]
        question_text = template.format(
            x1=skeleton.x1,
            y1=skeleton.y1,
            x2=skeleton.x2,
            y2=skeleton.y2,
            a_josa=eul_reul(f"({skeleton.x2}, {skeleton.y2})"),
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
            answer_format=_int_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_line_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 직선 스켈레톤 조립(기울기·시작점·dx→좌표→a+b 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=skeleton.condition,  # x - (a+b) = 0(검산용·독립 재계산)
            answer_map={"x": answer_text},
            answer_selection="unique",
            solution_steps=_line_steps(skeleton.formula, skeleton.answer),
            concept_tags=list(self._concept_tags),
        )
