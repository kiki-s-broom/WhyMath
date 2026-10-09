"""고등 이차곡선(포물선·타원·쌍곡선) 초점 결정론 스켈레톤 생성기 — W2 Phase2 #4(결정론·LLM 0).

`elementary_gcd_lcm_skeleton_generator`와 같은 설계 패턴(kind가 밴드뿐 아니라 성취기준
코드 자체를 가름) — `[12기하01-01]`(포물선의 방정식)·`[12기하01-02]`(타원의 방정식)·
`[12기하01-03]`(쌍곡선의 방정식)이 0건이었다 — 이 생성기가 세 성취기준의 첫 코퍼스를
확보한다. 개념그래프 매핑: `H:12기하01-01`/`H:12기하01-02`/`H:12기하01-03` — legacy 437
공간에 실존.

세 곡선 모두 "초점의 x좌표(양수)를 구하시오"로 환원해 단답형 수치 문제로 만든다:
- 포물선 y²=4px → 초점 (p, 0). p는 계수(4p)를 4로 나눈 값.
- 타원 x²/a²+y²/b²=1(a>b>0) → 초점 (±c, 0), c=√(a²−b²).
- 쌍곡선 x²/a²−y²/b²=1(a,b>0) → 초점 (±c, 0), c=√(a²+b²).

**타원·쌍곡선의 정수 초점 보장**: `coordinate_geometry_skeleton_generator`의 두 점 거리
생성기와 동일 트릭 — 피타고라스 삼조(3,4,5 등)를 그대로 재사용한다. 타원은 대각선(a)이
빗변이 되도록(a²=b²+c², 두 변 b·c가 삼조의 나머지 두 변), 쌍곡선은 c(초점 거리)가 빗변이
되도록(c²=a²+b², a·b가 삼조의 두 변) 배정하면 제곱근이 항상 정수로 떨어진다.

**검증 설계**: 조건은 주어진 계수(a²·b² 또는 4p)만으로 SymPy `sqrt()`가 초점 좌표를 독립
재유도한다(형제 생성기들의 "생성≠검증" 관례 계승).

범위(v1): 초점이 x축 위에 있는 표준형만(y축 위 초점·평행이동된 중심은 후속). 포물선은
계수(4p)를 그대로 노출(자명화 우려 없음 — 두 점 거리 생성기가 좌표를 그대로 노출하는 것과
동일 성격).

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
    "CONIC_STANDARD_CODES",
    "ConicKind",
    "ConicSectionFocusSkeletonGenerator",
]

_POOL_SEED = 20260807

ConicKind = Literal["parabola", "ellipse", "hyperbola"]

CONIC_STANDARD_CODES: dict[ConicKind, str] = {
    "parabola": "[12기하01-01]",
    "ellipse": "[12기하01-02]",
    "hyperbola": "[12기하01-03]",
}
_CONCEPT_SRC_IDS: dict[ConicKind, str] = {
    "parabola": "H:12기하01-01",
    "ellipse": "H:12기하01-02",
    "hyperbola": "H:12기하01-03",
}

# 피타고라스 삼조(leg1, leg2, hyp) — coordinate_geometry_skeleton_generator의 두 점 거리
# 생성기와 동일 리스트 재사용(신규 삼조 발명 0·private 모듈 경계 비침범 위해 독립 정의).
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
_P_RANGE = range(1, 26)

_PARABOLA_TEMPLATES: tuple[str, ...] = ("포물선 y^2={coef}x의 초점의 x좌표를 구하시오.",)
_ELLIPSE_TEMPLATES: tuple[str, ...] = ("타원 x^2/{a2}+y^2/{b2}=1의 초점의 x좌표(양수)를 구하시오.",)
_HYPERBOLA_TEMPLATES: tuple[str, ...] = (
    "쌍곡선 x^2/{a2}-y^2/{b2}=1의 초점의 x좌표(양수)를 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _ParabolaSkeleton:
    """포물선 뼈대 — y²=4px. p가 곧 초점의 x좌표. 단일 진실 원천."""

    p: int

    @property
    def coef(self) -> int:
        return 4 * self.p

    @property
    def answer(self) -> int:
        return self.p

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − coef/4 = 0'(계수만으로 p를 독립 재유도)."""
        return f"x - ({self.coef}/4) = 0"


@dataclass(frozen=True, slots=True)
class _EllipseSkeleton:
    """타원 뼈대 — x²/a²+y²/b²=1(a>b). a²=b²+c² 피타고라스 삼조로 구성. 단일 진실 원천."""

    a: int
    b: int
    c: int  # 삼조의 빗변=a, 두 변=b·c → a²=b²+c²(초점 거리).

    @property
    def a2(self) -> int:
        return self.a * self.a

    @property
    def b2(self) -> int:
        return self.b * self.b

    @property
    def answer(self) -> int:
        return self.c

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — a²·b²(주어진 정보)만으로 sqrt()가 c를 독립 재유도."""
        return f"x - sqrt({self.a2} - {self.b2}) = 0"


@dataclass(frozen=True, slots=True)
class _HyperbolaSkeleton:
    """쌍곡선 뼈대 — x²/a²−y²/b²=1. c²=a²+b² 피타고라스 삼조로 구성(c=빗변). 단일 진실 원천."""

    a: int
    b: int
    c: int  # 삼조의 빗변=c(초점 거리), 두 변=a·b.

    @property
    def a2(self) -> int:
        return self.a * self.a

    @property
    def b2(self) -> int:
        return self.b * self.b

    @property
    def answer(self) -> int:
        return self.c

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — a²·b²(주어진 정보)만으로 sqrt()가 c를 독립 재유도."""
        return f"x - sqrt({self.a2} + {self.b2}) = 0"


_ConicSkeleton = _ParabolaSkeleton | _EllipseSkeleton | _HyperbolaSkeleton


def _build_pool(kind: ConicKind) -> tuple[_ConicSkeleton, ...]:
    """결정론 이차곡선 뼈대 풀 — kind별 구조(포물선=p 열거, 타원/쌍곡선=삼조×부호)·고정 셔플."""
    if kind == "parabola":
        pool: list[_ConicSkeleton] = [_ParabolaSkeleton(p=p) for p in _P_RANGE]
        random.Random(_POOL_SEED).shuffle(pool)
        return tuple(pool)
    if kind == "ellipse":
        ellipse_pool: list[_ConicSkeleton] = []
        for leg1, leg2, hyp in _TRIPLES:
            for b_leg, c_leg in ((leg1, leg2), (leg2, leg1)):
                ellipse_pool.append(_EllipseSkeleton(a=hyp, b=b_leg, c=c_leg))
        random.Random(_POOL_SEED + 1).shuffle(ellipse_pool)
        return tuple(ellipse_pool)
    hyperbola_pool: list[_ConicSkeleton] = []
    for leg1, leg2, hyp in _TRIPLES:
        for a_leg, b_leg in ((leg1, leg2), (leg2, leg1)):
            hyperbola_pool.append(_HyperbolaSkeleton(a=a_leg, b=b_leg, c=hyp))
    random.Random(_POOL_SEED + 2).shuffle(hyperbola_pool)
    return tuple(hyperbola_pool)


def _explanation(kind: ConicKind, answer: int) -> str:
    """이차곡선 해설 — 초점 공식을 자연어로 서술(결정론·위생 청정·수치 등식 회피).

    ⚠️ ASCII만 사용(²·√ 등 유니코드 금지) — √는 코퍼스 베이스라인에 이미 있어 안전하지만
    ²는 신규 글리프라 게이트 즉시 거부 대상이다(2026-08-07 실측 발견 — question_text만
    확인하고 explanation을 놓쳐 처음엔 새어나갔다. S4-27 α·β 사고와 같은 유형).
    """
    if kind == "parabola":
        rule = "포물선 y^2=4px의 초점은 (p, 0)이므로 계수를 4로 나누면"
    elif kind == "ellipse":
        rule = "타원의 초점 거리는 a^2에서 b^2을 뺀 값의 제곱근이므로"
    else:
        rule = "쌍곡선의 초점 거리는 a^2과 b^2을 더한 값의 제곱근이므로"
    return f"{rule} 구하는 초점의 x좌표는 {answer} 이다."


def _answer_format(value: int) -> AnswerFormat:
    return AnswerFormat.자연수 if value > 0 else AnswerFormat.실수


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


@deterministic_generator
class ConicSectionFocusSkeletonGenerator:
    """이차곡선 초점 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `kind`(parabola/ellipse/hyperbola) 필터로 밴드를 분리한다. `kind`가 성취기준 코드·개념
    태그도 함께 결정한다(모듈 docstring 참조 — gcd/lcm 생성기와 동일 설계, 스펙의
    achievement_standard_codes를 그대로 따르지 않는다).
    """

    def __init__(
        self,
        *,
        kind: ConicKind,
        slug_prefix: str = "wm-conic",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("CONIC-SECTION-FOCUS",),
    ) -> None:
        self._kind = kind
        self._pool = _build_pool(kind)
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._standard_code = CONIC_STANDARD_CODES[kind]
        self._concept_tags = [
            ConceptTag(concept_src_id=_CONCEPT_SRC_IDS[kind], role="PRIMARY", relevance=0.95)
        ]

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 이차곡선 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(skeleton)

    def _assemble(self, skeleton: _ConicSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        if isinstance(skeleton, _ParabolaSkeleton):
            template = _PARABOLA_TEMPLATES[self._index % len(_PARABOLA_TEMPLATES)]
            question_text = template.format(coef=skeleton.coef)
        elif isinstance(skeleton, _EllipseSkeleton):
            template = _ELLIPSE_TEMPLATES[self._index % len(_ELLIPSE_TEMPLATES)]
            question_text = template.format(a2=skeleton.a2, b2=skeleton.b2)
        else:
            template = _HYPERBOLA_TEMPLATES[self._index % len(_HYPERBOLA_TEMPLATES)]
            question_text = template.format(a2=skeleton.a2, b2=skeleton.b2)

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
            difficulty_overall=3.2,  # 고등 기하 선택과목 도입 개념(conceptual 대역).
            question_format=QuestionFormat.단답형,
            answer_format=_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_explanation(self._kind, skeleton.answer),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 이차곡선 스켈레톤 조립(계수/피타고라스 삼조→초점 계산)",
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
