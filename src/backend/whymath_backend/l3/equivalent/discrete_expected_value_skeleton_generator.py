"""고등 이산확률변수 기댓값 결정론 스켈레톤 생성기 — W2 통계 영역 착점(결정론·LLM 0).

학년축 최단경로 계획(`docs/strategy/grade_axis_mvp_shortest_path_v1.md`) §3 W2. 실측
(2026-08-05): 고등 축 "통계" 영역(`[12확통03-01]`~`[12확통03-07]`) 7코드가 전량 0.0%다.
`[12확통03-02]`(이산확률변수의 기댓값과 표준편차)를 최초 착점으로 삼는다 — 이 중 기댓값만
다룬다(표준편차는 후속). `ElementaryAddSubSkeletonGenerator`(초등)·`MatrixOpsSkeletonGenerator`
(고등 행렬)·`CalculusProductRuleSkeletonGenerator`(대학 미분)·`LinearFunctionValueSkeleton
Generator`(중등 함숫값)에 이은 다섯 번째 도메인 — 좌석·게이트 무변경 재사용.

**범위 밖 의도적 배제**: 같은 고등 0% 3대 영역 중 "집합과 명제"는 명제 논리(참/거짓 판정)가
비수치라 Tier1(수치 검산)과 근본적으로 안 맞는다 — 이 슬라이스에서 다루지 않는다(후속은
Tier3 형식 검증 스코프 — `l3/verify_answer.py` 모듈 docstring "정직 스코프" 참조).

대상 성취기준: `[12확통03-02]`. 개념그래프 매핑:
`math.probability.isanhwakryulbyeonsuui-gidaetgapsgwa-pyojunpyeoncha`
(source_id="H:12확통03-02") — legacy 437 공간에 실존해 정상 태깅 가능(대학 축과 대비).

**검증 설계**: 이산확률변수 X가 값 x₁,x₂,x₃(확률 p₁,p₂,p₃=n₁/10,n₂/10,n₃/10, Σnᵢ=10)를
가질 때 E(X)=Σxᵢpᵢ. 조건은 `"(x1*n1 + x2*n2 + x3*n3)/10 = y"`(순수 유리수 산술) — Tier1이
분수 답(기약분수 문자열)도 그대로 검증함을 실측 확인(정수 산술·미분 평가·함수 대입에 이은
5번째 확인 패턴 — 방정식 sympify 기반 범용 검산기라는 결론이 유리수에도 그대로 성립).

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
from fractions import Fraction

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

__all__ = ["DiscreteExpectedValueSkeletonGenerator"]

_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12확통03-02", role="PRIMARY", relevance=0.95),
)

_DENOMINATOR = 10  # 확률 분모 고정(교과서 관례 — 정수 확률표).
_X_MIN, _X_MAX = -6, 9  # 확률변수 값 범위.
_POOL_TARGET_SIZE = 300  # (x1,x2,x3,n1,n2,n3) 조합공간이 크므로 전수열거 대신 시드 샘플.

_TEMPLATES: tuple[str, ...] = (
    "확률변수 X의 확률분포가 다음과 같을 때, E(X)의 값을 구하시오. "
    "P(X={x1})={n1}/10, P(X={x2})={n2}/10, P(X={x3})={n3}/10",
    "이산확률변수 X가 다음 표와 같은 확률분포를 가질 때, E(X)를 구하시오. "
    "P(X={x1})={n1}/10, P(X={x2})={n2}/10, P(X={x3})={n3}/10",
)


def _fraction_text(value: Fraction) -> str:
    """기약분수 문자열('7/2'·정수면 '4') — SymPy sympify와 왕복 정합."""
    return (
        str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    )


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """문제 뼈대 — 확률변수 값 3개·확률 분자 3개(분모 10 고정). 수치의 단일 원천."""

    x1: int
    x2: int
    x3: int
    n1: int  # P(X=x1) = n1/10
    n2: int
    n3: int

    @property
    def condition(self) -> str:
        return (
            f"({self.x1}*{self.n1} + {self.x2}*{self.n2} + {self.x3}*{self.n3})"
            f"/{_DENOMINATOR} = y"
        )

    @property
    def result(self) -> Fraction:
        """독립 재계산(가중합 정의) — 생성기 스스로도 SymPy에 의존하지 않는 이중 확인."""
        weighted_sum = self.x1 * self.n1 + self.x2 * self.n2 + self.x3 * self.n3
        return Fraction(weighted_sum, _DENOMINATOR)


def _compositions_of(total: int, parts: int, *, min_value: int = 1) -> list[tuple[int, ...]]:
    """total을 parts개의 min_value 이상 정수 합으로 나누는 모든 순서 있는 분할(작은 계산 전용)."""
    if parts == 1:
        return [(total,)] if total >= min_value else []
    out: list[tuple[int, ...]] = []
    for first in range(min_value, total - min_value * (parts - 1) + 1):
        for rest in _compositions_of(total - first, parts - 1, min_value=min_value):
            out.append((first, *rest))
    return out


def _build_pool() -> tuple[_Skeleton, ...]:
    """시드 샘플 풀 — 확률 분자 조합(10을 3부분 정수합으로 분할·36가지) × 값 3개 시드 샘플."""
    prob_compositions = _compositions_of(_DENOMINATOR, 3)  # Σnᵢ=10, nᵢ≥1 — 항상 36가지.
    rng = random.Random(20260805)
    pool: list[_Skeleton] = []
    seen: set[tuple[int, ...]] = set()
    attempts = 0
    while len(pool) < _POOL_TARGET_SIZE and attempts < _POOL_TARGET_SIZE * 20:
        attempts += 1
        values = rng.sample(range(_X_MIN, _X_MAX + 1), 3)
        x1, x2, x3 = sorted(values)  # 표기 관례 — 확률변수 값 오름차순 제시.
        n1, n2, n3 = rng.choice(prob_compositions)
        key = (x1, x2, x3, n1, n2, n3)
        if key in seen:
            continue
        seen.add(key)
        pool.append(_Skeleton(x1=x1, x2=x2, x3=x3, n1=n1, n2=n2, n3=n3))
    random.Random(20260805 + 1).shuffle(pool)
    return tuple(pool)


@deterministic_generator
class DiscreteExpectedValueSkeletonGenerator:
    """결정론 스켈레톤 생성기 — 이산확률변수 기댓값(`EquivalentProblemGenerator` 좌석).

    단일 변형이라(§ 모듈 docstring) `operation` 필터가 불필요하다. `harness/discrete_ev_
    batch.py`도 `run_batch`가 아니라 `run_equivalent_generation`을 `signature_index=None`
    으로 직접 호출한다(앞선 4개 생성기와 동일 이유 — 구조 dedup이 조건식을 해값으로 정규화해
    서로 다른 확률분포가 같은 E(X)를 내면 오탐).
    """

    def __init__(
        self,
        *,
        skip_conditions: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-discrete-ev",
        subject: Subject = Subject.확통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("DISCRETE-EXPECTED-VALUE",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_pool()
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
            condition = skeleton.condition
            if self._skip is not None and condition in self._skip:
                continue
            return self._assemble(spec, skeleton)
        return None

    def _assemble(self, spec: EquivalenceSpec, skeleton: _Skeleton) -> CandidateProblem:
        template = _TEMPLATES[self._index % len(_TEMPLATES)]
        question_text = template.format(
            x1=skeleton.x1,
            x2=skeleton.x2,
            x3=skeleton.x3,
            n1=skeleton.n1,
            n2=skeleton.n2,
            n3=skeleton.n3,
        )
        answer_text = _fraction_text(skeleton.result)
        # 위생 게이트 오탐 회피(calculus_product_rule_skeleton_generator 2026-08-05 실측
        # 처방 계승) — 등호를 아예 쓰지 않는 서술형 결론.
        explanation = f"E(X)는 각 값과 확률의 곱의 합이다. 계산하면 그 값은 {answer_text}이다."
        condition = skeleton.condition
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
            difficulty_overall=2.8,  # 이산확률분포 개념 적용 — procedural~conceptual 경계.
            question_format=QuestionFormat.단답형,
            answer_format=AnswerFormat.분수,
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
                    "결정론 스켈레톤 조립(확률분포→기댓값 가중합 역산·W2)",
                    "S2-a 수용 게이트(Tier1 유리수 산술 검산)",
                    "AI 검수 게이트 대기(Kiki 머신·실 LLM 필요 — 미통과 시 is_published=False)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,
            answer_map={"y": answer_text},
            # 가중합 1회 계산은 다단계 과정이 없다(Tier1 단독 verified가 정직 — 앞선 네
            # 생성기와 동일 원칙).
            solution_steps=None,
            concept_tags=list(self._concept_tags),
        )

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"
