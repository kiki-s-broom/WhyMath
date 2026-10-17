"""고등 벡터 — 벡터의 연산·위치벡터 성분 스켈레톤 생성기 — W2 Phase1 #5(결정론·LLM 0).

`matrix_ops_skeleton_generator`(성분별 선형 연산)와 구조가 유사한 신규 도메인 착점이다.
[12기하03-01](벡터의 뜻과 연산)·[12기하03-02](위치벡터와 벡터의 성분)이 0건이었다 — 이
생성기가 두 성취기준의 첫 코퍼스를 확보한다. [12기하03-03](내적)은 이미 다른 코퍼스가
커버 중이라 이 생성기는 다루지 않는다(중복 착수 회피).

두 클래스:
- `VectorLinearCombinationSkeletonGenerator` — 벡터 a=(ax,ay)·b=(bx,by)의 선형결합
  p·a+q·b(덧셈·뺄셈·실수배)를 계산, 답은 결과 벡터의 x성분+y성분 합(quad_ineq의 "근의 합"
  트릭과 동일 정신 — 벡터 전체 대신 단답형 수치로 환원).
- `PositionVectorComponentSkeletonGenerator` — 점 A(ax,ay)에서 점 B(bx,by)로 향하는
  위치벡터 AB(=OB−OA)의 성분을 구성, 답은 x성분+y성분 합. 좌표기하 두 점 거리 생성기와
  기계적으로는 유사하지만(좌표 차 계산), 검증 대상 개념이 다르다(거리=피타고라스 vs
  성분=좌표 대응 자체) — "위치벡터" 표준이 요구하는 정확히 그 대응 관계를 exercising한다.

핵심 통찰(재구현 0): 두 문제군 모두 "x에 대한 방정식의 유일해"로 환원된다. 조건식을 원시
파라미터에서 그대로 재구성해 SymPy가 독립적으로 재계산한다(생성≠검증).

⚠️ 부호 결합 표기 주의: 계수 p·q가 음수일 수 있어 "pa+qb" 형태를 그대로 문자열 결합하면
"2a+-3b" 같은 겹부호가 난다. `_signed_term`으로 부호를 정규화해 "2a-3b" 형태로만 표기한다
(형제 생성기들의 "+ -"/"- -" 위생 관례 계승).

⚠️ 구조 dedup 주의(quad_ineq·coordinate_geometry 관례 계승): 서로 다른 벡터·좌표 조합이
같은 성분 합을 내는 것은 정상이다 — 답 기준이 아니라 원시 파라미터 튜플로 dedup한다.

범위(v1): 정수 성분·정수 계수만. 벡터의 크기(노름)·평행/수직 판정·공간벡터(3차원)는 후속.

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지(canonicalize)·L1(ConceptTag)만
import(L4 참조 0). 난이도는 지역 함수(공유 difficulty.py 불침범·도메인 분담 관례 계승).
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
from whymath_backend.lang.josa import euro_ro
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
    "PositionVectorComponentSkeletonGenerator",
    "VectorLinearCombinationSkeletonGenerator",
]

_POOL_SEED = 20260807

_LINEAR_COMBO_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12기하03-01", role="PRIMARY", relevance=0.95),
)
_POSITION_VECTOR_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12기하03-02", role="PRIMARY", relevance=0.95),
)


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _int_answer_format(answer: int) -> AnswerFormat:
    """정답 형태 — 양의 정수=자연수·그 외(0·음수)=실수(형제 생성기 자연수/실수 분기 미러)."""
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


def _signed_term(coeff: int, symbol: str, *, leading: bool) -> str:
    """계수-부호 정규화 항 표기 — 겹부호(+ -, - -) 방지. 계수 1은 숫자를 생략(예 '1a' 아닌 'a')."""
    magnitude = "" if abs(coeff) == 1 else str(abs(coeff))
    body = f"{magnitude}{symbol}"
    if leading:
        return f"-{body}" if coeff < 0 else body
    return f" - {body}" if coeff < 0 else f" + {body}"


# ── 벡터 선형결합: p·a + q·b (덧셈·뺄셈·실수배) ────────────────────────────────
_COEFF_RANGE = tuple(c for c in range(-4, 5) if c != 0)  # 0 제외(실수배 의미 있게).
_COMPONENT_RANGE = range(-6, 7)
_LINEAR_COMBO_POOL_TARGET = 260
_LINEAR_COMBO_TEMPLATES: tuple[str, ...] = (
    "벡터 a=({ax}, {ay}), b=({bx}, {by})에 대해 {combo}의 x성분과 y성분의 합을 구하시오.",
    "두 벡터 a=({ax}, {ay})와 b=({bx}, {by})가 있을 때, {combo}의 성분의 합을 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _LinearComboSkeleton:
    """벡터 선형결합 뼈대 — 벡터 a·b 성분·계수 p·q. 답 = (p·a+q·b)의 x성분+y성분 합."""

    ax: int
    ay: int
    bx: int
    by: int
    p: int
    q: int

    @property
    def result_x(self) -> int:
        return self.p * self.ax + self.q * self.bx

    @property
    def result_y(self) -> int:
        return self.p * self.ay + self.q * self.by

    @property
    def answer(self) -> int:
        """정답 — (p·a+q·b)의 x성분+y성분 합."""
        return self.result_x + self.result_y

    @property
    def formula(self) -> str:
        """답의 SymPy 계산식 — 원시 성분·계수에서 재유도(독립 재계산의 근거)."""
        return (
            f"({self.p}*{self.ax} + {self.q}*{self.bx}) "
            f"+ ({self.p}*{self.ay} + {self.q}*{self.by})"
        )

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − ((p·ax+q·bx)+(p·ay+q·by)) = 0'."""
        return f"x - ({self.formula}) = 0"

    @property
    def combo_display(self) -> str:
        """'pa+qb' 겹부호 없는 표기 — 예 '2a - 3b'."""
        return _signed_term(self.p, "a", leading=True) + _signed_term(self.q, "b", leading=False)

    @property
    def difficulty(self) -> float:
        # QUAD-EQ(base 2.0) 대비: 스칼라배 2회+덧셈 2회+최종 합산이라 대수 부담이 비슷하거나
        # 약간 무겁다.
        difficulty = 2.1
        if abs(self.p) >= 3 or abs(self.q) >= 3:
            difficulty += 0.2
        if abs(self.answer) >= 30:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_linear_combo_pool() -> tuple[_LinearComboSkeleton, ...]:
    """결정론 벡터 선형결합 뼈대 풀 — 거부 표본추출로 목표 크기까지 채움(구조 키 자연 유일).

    전체 성분×계수 조합(약 180만)은 전건 열거하기엔 과대라, 고정 시드 난수로 직접 표본추출
    한다(elementary_area_measure의 조기 종료 관례와 동형 — 목표 도달 시 정지). 답 기준이
    아니라 원시 파라미터(ax,ay,bx,by,p,q) 튜플로 dedup한다(다른 조합이 같은 답을 내는 것은
    정상 — coordinate_geometry 관례 계승).
    """
    rng = random.Random(_POOL_SEED)
    seen: set[tuple[int, int, int, int, int, int]] = set()
    pool: list[_LinearComboSkeleton] = []
    while len(pool) < _LINEAR_COMBO_POOL_TARGET:
        key = (
            rng.choice(_COMPONENT_RANGE),
            rng.choice(_COMPONENT_RANGE),
            rng.choice(_COMPONENT_RANGE),
            rng.choice(_COMPONENT_RANGE),
            rng.choice(_COEFF_RANGE),
            rng.choice(_COEFF_RANGE),
        )
        if key in seen:
            continue
        seen.add(key)
        ax, ay, bx, by, p, q = key
        pool.append(_LinearComboSkeleton(ax=ax, ay=ay, bx=bx, by=by, p=p, q=q))
    return tuple(pool)


def _linear_combo_steps(skeleton: _LinearComboSkeleton) -> list[str]:
    """선형결합 풀이의 검증 단계 체인(S2-02) — 공식 대입식 → 값(표현식 동치·Tier2 correct)."""
    return [skeleton.formula, str(skeleton.answer)]


def _linear_combo_explanation(skeleton: _LinearComboSkeleton) -> str:
    """선형결합 해설 — 성분별 연산을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    return (
        "벡터의 덧셈·뺄셈·실수배는 성분별로 계산하므로, x성분과 y성분을 각각 구해 더하면 "
        f"{skeleton.answer} 이다."
    )


@deterministic_generator
class VectorLinearCombinationSkeletonGenerator:
    """벡터 선형결합 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    풀(구조 키 유일)을 순서대로 소비(소진 시 None).
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-vecops",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("VECTOR-LINEAR-COMBO",),
        concept_tags: Sequence[ConceptTag] = _LINEAR_COMBO_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_linear_combo_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 벡터 선형결합 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _LinearComboSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        template = _LINEAR_COMBO_TEMPLATES[self._index % len(_LINEAR_COMBO_TEMPLATES)]
        question_text = template.format(
            ax=skeleton.ax,
            ay=skeleton.ay,
            bx=skeleton.bx,
            by=skeleton.by,
            combo=skeleton.combo_display,
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
            answer_explanation=_linear_combo_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 벡터 선형결합 스켈레톤 조립(성분·계수→성분별 계산)",
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
            solution_steps=_linear_combo_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )


# ── 위치벡터: 점 A→점 B의 벡터 AB(=OB−OA) 성분 ────────────────────────────────
_POSITION_COORD_RANGE = range(-8, 9)
_POSITION_POOL_TARGET = 260
_POSITION_TEMPLATES: tuple[str, ...] = (
    "점 A({ax}, {ay})에서 점 B({bx}, {by}){euro_ro} 향하는 벡터 AB의 x성분과 y성분의 합을 "
    "구하시오.",
    "두 점 A({ax}, {ay}), B({bx}, {by})에 대응하는 위치벡터를 각각 OA, OB라 할 때, "
    "벡터 AB(=OB−OA)의 성분의 합을 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _PositionVectorSkeleton:
    """위치벡터 뼈대 — 점 A·B 좌표. 벡터 AB = (bx−ax, by−ay). 답 = 두 성분의 합."""

    ax: int
    ay: int
    bx: int
    by: int

    @property
    def answer(self) -> int:
        """정답 — (bx−ax)+(by−ay)."""
        return (self.bx - self.ax) + (self.by - self.ay)

    @property
    def formula(self) -> str:
        """답의 SymPy 계산식 — 원시 좌표에서 재유도(독립 재계산의 근거)."""
        return f"({self.bx} - {self.ax}) + ({self.by} - {self.ay})"

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − ((bx−ax)+(by−ay)) = 0'."""
        return f"x - ({self.formula}) = 0"

    @property
    def difficulty(self) -> float:
        # QUAD-EQ(base 2.0) 대비: 좌표 차 두 번+합산이라 등차합(1.9)보단 약간 무겁다.
        difficulty = 1.9
        if abs(self.ax) >= 6 or abs(self.ay) >= 6:
            difficulty += 0.1
        if abs(self.answer) >= 15:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_position_vector_pool() -> tuple[_PositionVectorSkeleton, ...]:
    """결정론 위치벡터 뼈대 풀 — 점 A·B 좌표 열거·**구조 키 자연 유일**(dedup 불요)·고정 셔플."""
    combos: list[tuple[int, int, int, int]] = [
        (ax, ay, bx, by)
        for ax in _POSITION_COORD_RANGE
        for ay in _POSITION_COORD_RANGE
        for bx in _POSITION_COORD_RANGE
        for by in _POSITION_COORD_RANGE
        if (ax, ay) != (bx, by)
    ]
    rng = random.Random(_POOL_SEED + 1)
    rng.shuffle(combos)
    pool = [
        _PositionVectorSkeleton(ax=ax, ay=ay, bx=bx, by=by)
        for ax, ay, bx, by in combos[:_POSITION_POOL_TARGET]
    ]
    return tuple(pool)


def _position_vector_steps(skeleton: _PositionVectorSkeleton) -> list[str]:
    """위치벡터 풀이의 검증 단계 체인(S2-02) — 공식 대입식 → 값(표현식 동치·Tier2 correct)."""
    return [skeleton.formula, str(skeleton.answer)]


def _position_vector_explanation(skeleton: _PositionVectorSkeleton) -> str:
    """위치벡터 해설 — 종점 좌표에서 시점 좌표를 뺀다는 원리를 자연어로 서술(위생 청정)."""
    return (
        "위치벡터에서 벡터 AB의 성분은 도착점 B의 좌표에서 출발점 A의 좌표를 빼면 되므로, "
        f"두 성분의 합은 {skeleton.answer} 이다."
    )


@deterministic_generator
class PositionVectorComponentSkeletonGenerator:
    """위치벡터 성분 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    풀(구조 키 유일)을 순서대로 소비(소진 시 None).
    """

    def __init__(
        self,
        *,
        slug_prefix: str = "wm-posvec",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("POSITION-VECTOR",),
        concept_tags: Sequence[ConceptTag] = _POSITION_VECTOR_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_position_vector_pool()
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 위치벡터 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _PositionVectorSkeleton
    ) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        template = _POSITION_TEMPLATES[self._index % len(_POSITION_TEMPLATES)]
        question_text = template.format(
            ax=skeleton.ax,
            ay=skeleton.ay,
            bx=skeleton.bx,
            by=skeleton.by,
            euro_ro=euro_ro(f"({skeleton.bx}, {skeleton.by})"),
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
            answer_explanation=_position_vector_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 위치벡터 스켈레톤 조립(점 A·B 좌표→성분 계산)",
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
            solution_steps=_position_vector_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )
