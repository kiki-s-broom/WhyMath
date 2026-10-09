"""고등 이차부등식 해의 경계값 합 결정론 스켈레톤 생성기 — W2 Phase 1 #1(결정론·LLM 0).

`w2_content_factory_completion_plan_v1.md` §6 Phase 1 우선순위 1위. 대상 성취기준:
`[10공수1-02-11]`(이차부등식과 이차함수를 연결하여 그 관계를 설명하고, 이차부등식과 연립이차
부등식을 풀 수 있다). 개념그래프 매핑: `math.equation.ichabudeungsik-yeonripichabudeungsik`
(source_id="HK16").

**문제 설계**: 정수근 r1<r2를 코드가 먼저 고르고(`SkeletonEquivalentProblemGenerator` 선례와
동형 — 근이 뼈대의 단일 진실 원천) 전개해 a·x²+Bx+C 꼴 부등식을 만든다. **발문에는 r1·r2
숫자를 노출하지 않고** "해의 경계가 되는 두 값의 합을 구하시오"로 지칭한다 — 학생이 실제로
이차부등식을 풀어 경계값을 구해야 답을 낼 수 있다(숫자를 그대로 노출하면 문제가 자명해져
성취기준 취지가 무너진다). **그리스 문자(α·β) 등 기호 표기는 쓰지 않는다** — 순수 한국어
서술로 경계를 지칭한다(2026-08-05 실측: `notation_coverage_eval` 게이트가 코퍼스에 렌더
검증 안 된 신규 글리프가 유입되는 걸 차단한다 — α/β를 처음 시도했다가 "신규 누락 글리프"로
게이트 거부돼 순수 서술형으로 교정. 다른 모든 생성기가 이미 이 관례를 따른다 — 이 슬라이스가
처음으로 벗어나려다 게이트에 걸려 재확인한 셈).

두 변형(`operation` 필터·`ElementaryAddSubSkeletonGenerator` 2026-08-05 실측 사고 이후
다변형 생성기의 표준 관례):
  - `outer`: a·x²+Bx+C > 0(a>0)의 해는 x<r1 또는 x>r2(해집합이 두 구간·근 "바깥쪽").
  - `inner`: a·x²+Bx+C < 0(a>0)의 해는 r1<x<r2(해집합이 한 구간·근 "안쪽").
둘 다 경계값 합은 항상 r1+r2(부등호 방향과 무관 — Vieta 합) — 부등식 방향이 해석에 미치는
영향(안쪽/바깥쪽)은 발문에 정확히 반영하되, 검증은 근의 합이라는 공통 스칼라로 안전하게
좁힌다(계산 결과인 이 스칼라가 이 슬라이스의 정확성 판정 대상).

**검증 설계**: `verify_answer`(Tier1)에 조건 `"r1 + r2 = y"`를 직접 준다 — 이 생성기는
뼈대(r1, r2)를 먼저 확정하고 전개해 발문 계수를 역산하므로(`skeleton_generator.py`의
근→방정식 역산 관례와 동형), 답 검증은 "생성기가 고른 두 근의 합"이라는 이미 확정된 산술
사실을 확인하는 것으로 충분하다(elementary_addsub와 동일 원칙 — Tier1은 최종 산술 단계만
검산하고, 뼈대 구성 전체의 정확성은 단위테스트의 독립 재계산이 담당).

**노출 게이팅**: 선행 생성기와 동일 원칙 — 산출물은 v0(사람 검수 전), AI 검수(Wilson
게이트)는 실 LLM 필요라 이 환경 밖(Kiki 머신)에서만 가능하다. 그 전까지
`is_published=False`로 유지.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
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

__all__ = ["InequalityDirection", "QuadraticInequalityBoundarySkeletonGenerator"]

_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="HK16", role="PRIMARY", relevance=0.95),
)

InequalityDirection = Literal["outer", "inner"]

_ROOT_MIN, _ROOT_MAX = -9, 9
_LEAD_COEFFICIENTS: tuple[int, ...] = (1, 2, 3)
_POOL_TARGET_SIZE = 300  # (r1,r2,a) 조합공간이 크므로 전수열거 대신 시드 샘플.

_OUTER_TEMPLATES: tuple[str, ...] = (
    "이차부등식 {ineq} > 0의 해의 경계가 되는 두 값의 합을 구하시오.",
    "이차부등식 {ineq} > 0을 만족하는 x의 범위의 두 경계값의 합을 구하시오.",
)
_INNER_TEMPLATES: tuple[str, ...] = (
    "이차부등식 {ineq} < 0의 해의 경계가 되는 두 값의 합을 구하시오.",
    "이차부등식 {ineq} < 0을 만족하는 x의 범위의 두 경계값의 합을 구하시오.",
)
_TEMPLATES_BY_DIRECTION: dict[InequalityDirection, tuple[str, ...]] = {
    "outer": _OUTER_TEMPLATES,
    "inner": _INNER_TEMPLATES,
}


def _term(coefficient: int, symbol: str, *, lead: bool = False) -> str:
    """계수 하나를 사람이 읽는 항으로 — 부호·계수 1 생략 규칙(선행 생성기들과 동형 독립
    구현 — private 모듈 경계를 넘지 않기 위해 재구현, 신규 규칙 발명 0)."""
    sign = "-" if coefficient < 0 else ("" if lead else "+")
    magnitude = abs(coefficient)
    body = symbol if magnitude == 1 and symbol else f"{magnitude}{symbol}"
    joint = " " if sign and not lead else ""
    return f"{sign}{joint}{body}" if lead else f"{sign} {body}"


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """문제 뼈대 — 정수근 r1<r2·선두계수 a(양수)·부등호 방향. 근이 수치의 단일 원천."""

    r1: int
    r2: int
    a: int
    direction: InequalityDirection

    @property
    def coefficients(self) -> tuple[int, int, int]:
        """전개 계수 (a, B, C) — a(x-r1)(x-r2) = a·x² - a(r1+r2)x + a·r1·r2."""
        return self.a, -self.a * (self.r1 + self.r2), self.a * self.r1 * self.r2

    @property
    def display_inequality(self) -> str:
        a, b, c = self.coefficients
        parts = [_term(a, "x^2", lead=True)]
        if b:
            parts.append(_term(b, "x"))
        if c:
            parts.append(_term(c, ""))
        return " ".join(parts)

    @property
    def result(self) -> int:
        """독립 재계산 — 근의 합은 뼈대 확정 시점에 이미 정해진 값(Vieta 공식과 무관하게
        코드가 직접 고른 r1+r2 그 자체)."""
        return self.r1 + self.r2


def _build_pool() -> tuple[_Skeleton, ...]:
    """시드 샘플 풀 — (r1,r2,a) 조합 × 방향 2종, 고정 시드 셔플(재현·디버그)."""
    rng = random.Random(20260807)
    pool: list[_Skeleton] = []
    seen: set[tuple[int, int, int, str]] = set()
    attempts = 0
    while len(pool) < _POOL_TARGET_SIZE and attempts < _POOL_TARGET_SIZE * 20:
        attempts += 1
        r1, r2 = sorted(rng.sample(range(_ROOT_MIN, _ROOT_MAX + 1), 2))
        a = rng.choice(_LEAD_COEFFICIENTS)
        direction: InequalityDirection = rng.choice(("outer", "inner"))
        key = (r1, r2, a, direction)
        if key in seen:
            continue
        seen.add(key)
        pool.append(_Skeleton(r1=r1, r2=r2, a=a, direction=direction))
    random.Random(20260807 + 1).shuffle(pool)
    return tuple(pool)


@deterministic_generator
class QuadraticInequalityBoundarySkeletonGenerator:
    """결정론 스켈레톤 생성기 — 이차부등식 해의 경계값 합(`EquivalentProblemGenerator` 좌석).

    `direction` 필터(`operation` 필터의 이 도메인 명칭) — 미지정이면 outer/inner 혼합 풀
    전체를 순서대로 낸다. 배치가 방향별 밴드를 나누려면 *반드시* 이 필터로 인스턴스를
    분리해야 한다(`_build_pool()`은 고정 시드라 필터 없이 여러 인스턴스를 만들면 매번 같은
    셔플 순서를 재생한다 — `elementary_addsub_skeleton_generator` 2026-08-05 실측 사고와
    동일 함정, `harness/quad_ineq_batch.py`가 이 필터를 사용).
    """

    def __init__(
        self,
        *,
        direction: InequalityDirection | None = None,
        skip_conditions: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-quad-ineq",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("QUAD-INEQ-BOUNDARY",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        full_pool = _build_pool()
        self._pool = (
            full_pool
            if direction is None
            else tuple(s for s in full_pool if s.direction == direction)
        )
        self._index = 0
        self._skip = skip_conditions
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            condition = f"{skeleton.r1} + {skeleton.r2} = y"
            if self._skip is not None and condition in self._skip:
                continue
            return self._assemble(spec, skeleton)
        return None

    def _assemble(self, spec: EquivalenceSpec, skeleton: _Skeleton) -> CandidateProblem:
        templates = _TEMPLATES_BY_DIRECTION[skeleton.direction]
        question_text = templates[self._index % len(templates)].format(
            ineq=skeleton.display_inequality
        )
        answer_text = str(skeleton.result)
        # 위생 게이트 오탐 회피(calculus_product_rule_skeleton_generator 2026-08-05 실측
        # 처방 계승) — 등호를 아예 쓰지 않는 서술형 결론. 그리스 문자 미사용(모듈 docstring
        # "문제 설계" 참조 — notation_coverage_eval 게이트 실측 회귀).
        which = (
            "바깥쪽 구간(근보다 작거나 큰 값)"
            if skeleton.direction == "outer"
            else "안쪽 구간(두 근 사이)"
        )
        explanation = (
            f"이차부등식의 해가 근의 {which}이므로 경계값은 이 이차식의 두 근이다. "
            f"두 근의 합의 값은 {answer_text}이다."
        )
        condition = f"{skeleton.r1} + {skeleton.r2} = y"
        standard_codes = sorted(spec.achievement_standard_codes)
        slug = self._stable_slug(question_text, answer_text, standard_codes)

        problem = Problem(
            problem_id=uuid.uuid5(uuid.NAMESPACE_URL, f"whymath:problem:{slug}"),
            slug=slug,
            source_type=SourceType.자체생성,
            curriculum_version=self._curriculum_version,
            valid_from_year=self._valid_from_year,
            subject=self._subject,
            unit_codes=list(self._unit_codes),
            difficulty_overall=2.6,  # 부등식↔함수 관계 적용 — procedural~conceptual 경계.
            question_format=QuestionFormat.단답형,
            answer_format=self._answer_format(skeleton.result),
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
                    "결정론 스켈레톤 조립(근→부등식 역산·W2 Phase1)",
                    "S2-a 수용 게이트(Tier1 산술 검산)",
                    "AI 검수 게이트 대기(Kiki 머신·실 LLM 필요 — 미통과 시 is_published=False)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,
            answer_map={"y": answer_text},
            # 근의 합은 뼈대가 이미 확정한 산술 사실이라 다단계 과정이 없다(Tier1 단독
            # verified가 정직 — 선행 생성기와 동일 원칙).
            solution_steps=None,
            concept_tags=list(self._concept_tags),
        )

    @staticmethod
    def _answer_format(value: int) -> AnswerFormat:
        return AnswerFormat.자연수 if value > 0 else AnswerFormat.실수

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"
