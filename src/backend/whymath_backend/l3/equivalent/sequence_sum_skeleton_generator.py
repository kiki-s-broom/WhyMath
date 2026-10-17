"""수열의 합(Sₙ) 파라메트릭 스켈레톤 동등문제 생성기 — S2 대수 확장(결정론·LLM 0).

수열 일반항 생성기(`ArithmeticSequenceSkeletonGenerator`·`GeometricSequenceSkeletonGenerator`)의
**합 형제**다. 같은 `EquivalentProblemGenerator` 좌석을 구현하되 수학 실체가 다르다: 등차수열의 합
Sₙ = n(2a+(n−1)d)/2·등비수열의 합 Sₙ = a(rⁿ−1)/(r−1)의 값을 낸다. 배경(도메인 분담): 일반항 밴드는
채웠으나 수열의 *합*이 0건이었다 — 이 생성기가 합 코퍼스를 처음 확보한다(고2 대수·수열의 합).

핵심 통찰(재구현 0): **수열의 합도 "x에 대한 방정식의 유일해"로 환원**된다. 합 공식을 그대로
조건식 `x − (Sₙ 공식) = 0`으로 공급하면 기존 근 검증 스택(`verify_answer`=대입 잔차·
`derive_selected_root`=solve)이 **무변경 재사용**된다. 조건식에 *합의 닫힌 계산식*을 넣으므로
derive-and-verify가 SymPy로 **독립 재계산**해 생성기의 파이썬 계산과 교차 검증한다(생성≠검증).

⚠️ 구조 dedup 주의: 조건은 `x − 상수`로 접혀(canonical_signature 非None) **같은 합이면 같은
signature**가 된다 — 서로 다른 문제가 오병합되지 않게 **풀을 답 기준 dedup**해 답이 유일한 뼈대만
남긴다(일반항 형제와 동일 전략). 답 유일이면 signature도 유일 — 오케스트레이터 구조 dedup과 정합.

범위(v1): 등차·등비 *합*(제n항까지)·양의 정수 합·단답형만. 부분합의 차·음의 공차/공비, 시그마
표기, 객관식·오개념 distractor, LLM 발문 다양화는 후속.

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지(canonicalize)·L1(ConceptTag)만
import(L4 참조 0). 난이도는 지역 함수(공유 difficulty.py 불침범·도메인 분담).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.canonicalize import canonical_signature
from whymath_backend.l3.equivalent.generator import CandidateProblem, deterministic_generator
from whymath_backend.lang.josa import eul_reul
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
    "ArithmeticSumSkeletonGenerator",
    "GeometricSumSkeletonGenerator",
]

_POOL_SEED = 20260706

# 개념 태깅 — 일반항 형제와 동일 개념(등차/등비 "일반항과 합"이 합을 포함). L4 주입 원칙 밖.
_ARITH_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12대수03-02", role="PRIMARY", relevance=0.95),
)
_GEO_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12대수03-03", role="PRIMARY", relevance=0.95),
)

# 합 상한 — 손계산 가능 범위. 등차합 500·등비합 2000(합은 항보다 커서 상한을 키운다).
_ARITH_SUM_MAX = 500
_GEO_SUM_MAX = 2000


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _sum_answer_format(answer: int) -> AnswerFormat:
    """정답 형태 — 양의 정수=자연수·그 외=실수(형제 미러). 합 v1은 전건 양의 정수."""
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


def _sum_steps(formula: str, answer: int) -> list[str]:
    """합 풀이의 검증 단계 체인(S2-02) — 합 공식 대입식 → 값(표현식 동치·Tier2 correct).

    `_factoring_steps`(skeleton_generator) 패턴 미러. `verify_step`은 표현식 동치만 증명하므로
    체인은 *합 공식 대입 평가*로 구성한다: 대입식(예: '10*(2*3 + (10 - 1)*4)/2')과 그 값('210')은
    수치 항등식이라 전이가 항상 correct — 수용 게이트(acceptance §verified)의 unverifiable 0·
    전 전이 correct 요구를 충족한다(실측 프로브 확인). 공식 '유도'·서술은 answer_explanation 담당
    (표현≠의미) — 여기엔 SymPy로 증명 가능한 대수 골자만 싣는다.
    """
    return [formula, str(answer)]


# ── 등차수열의 합 Sₙ = n(2a+(n−1)d)/2 ────────────────────────────────────────
_ARITH_SUM_TEMPLATES: tuple[str, ...] = (
    "첫째항이 {a}, 공차가 {d}인 등차수열의 첫째항부터 제{n}항까지의 합을 구하시오.",
    "등차수열 {{aₙ}}의 첫째항이 {a}이고 공차가 {d}일 때, 제{n}항까지의 합 S_{n}{josa} 구하시오.",
    "첫째항 {a}, 공차 {d}인 등차수열에서 처음 {n}개 항의 합을 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _ArithSumSkeleton:
    """등차합 뼈대 — 첫째항 a·공차 d·항수 n. Sₙ = n(2a+(n−1)d)/2. 모든 수치의 단일 진실 원천."""

    first: int
    diff: int
    term: int  # 항수 n (≥2)

    @property
    def answer(self) -> int:
        """정답 — Sₙ = n(2a+(n−1)d)/2. (2a+(n−1)d와 n 중 하나가 짝수라 항상 정수.)"""
        total = self.term * (2 * self.first + (self.term - 1) * self.diff)
        return total // 2

    @property
    def formula(self) -> str:
        """합 공식의 SymPy 계산식 — 'n(2a+(n−1)d)/2'. condition·solution_steps의 단일 진실 원천."""
        return f"{self.term}*(2*{self.first} + ({self.term} - 1)*{self.diff})/2"

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − n(2a+(n−1)d)/2 = 0'. 합 공식 그대로(독립 재계산)."""
        return f"x - ({self.formula}) = 0"

    @property
    def difficulty(self) -> float:
        # 재보정(S2-08·계통 관찰 2): 합 Sₙ은 공식 대입에 산술 1단(끝항·곱셈)이 더 붙어 순수
        # 일반항 조회보단 약간 무겁지만 QUAD-EQ(base 2.0) 언저리를 넘지 않는다. base 3.0→1.9로
        # 내려 QUAD-EQ 이하/근처에 두고 항수·공차·값 크기 가산은 유지한다.
        difficulty = 1.9
        if self.term >= 10:
            difficulty += 0.2
        if self.diff >= 4:
            difficulty += 0.1
        if self.answer > 200:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_arith_sum_pool() -> tuple[_ArithSumSkeleton, ...]:
    """결정론 등차합 뼈대 풀 — (a, d, n) 열거·합 상한·**답 유일 dedup**·고정 시드 셔플."""
    seen: set[int] = set()
    pool: list[_ArithSumSkeleton] = []
    for first in range(1, 10):
        for diff in range(1, 7):
            for term in range(4, 16):
                skeleton = _ArithSumSkeleton(first=first, diff=diff, term=term)
                answer = skeleton.answer
                if answer > _ARITH_SUM_MAX or answer in seen:
                    continue
                seen.add(answer)
                pool.append(skeleton)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _arith_sum_explanation(skeleton: _ArithSumSkeleton) -> str:
    """등차합 해설 — 합 공식을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    return (
        f"등차수열의 합은 (첫째항+끝항)×항수÷2와 같으므로, 제{skeleton.term}항까지의 합은 "
        f"{skeleton.answer} 이다."
    )


@deterministic_generator
class ArithmeticSumSkeletonGenerator:
    """등차수열의 합 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    풀(답 유일)을 순서대로 소비(소진 시 None). 일반항 형제와 동일 좌석·게이트·근 검증 스택을 공유
    한다(도메인 분담). 답이 유일해 signature도 유일 — 구조 dedup과 정합.
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-arsum",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("ARITH-SUM",),
        concept_tags: Sequence[ConceptTag] = _ARITH_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_arith_sum_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 등차합 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            condition = skeleton.condition
            if self._skip is not None:
                signature = canonical_signature(condition, "unique")
                if signature is not None and signature in self._skip:
                    continue
            return self._assemble(spec, skeleton, condition)
        return None

    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _ArithSumSkeleton, condition: str
    ) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        question_text = _ARITH_SUM_TEMPLATES[self._index % len(_ARITH_SUM_TEMPLATES)].format(
            a=skeleton.first, d=skeleton.diff, n=skeleton.term, josa=eul_reul(str(skeleton.term))
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
            answer_format=_sum_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_arith_sum_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 등차수열의 합 스켈레톤 조립(a·d·n→Sₙ 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # x - n(2a+(n-1)d)/2 = 0(검산용·독립 재계산)
            answer_map={"x": answer_text},
            answer_selection="unique",  # 합은 유일값
            # S2-02: 합 공식 대입식→값 체인 방출 — Tier2·상시 재검증·WH-S replay가 소비.
            solution_steps=_sum_steps(skeleton.formula, skeleton.answer),
            concept_tags=list(self._concept_tags),
        )


# ── 등비수열의 합 Sₙ = a(rⁿ−1)/(r−1) ─────────────────────────────────────────
_GEO_SUM_TEMPLATES: tuple[str, ...] = (
    "첫째항이 {a}, 공비가 {r}인 등비수열의 첫째항부터 제{n}항까지의 합을 구하시오.",
    "등비수열 {{aₙ}}의 첫째항이 {a}이고 공비가 {r}일 때, 제{n}항까지의 합 S_{n}{josa} 구하시오.",
    "첫째항 {a}, 공비 {r}인 등비수열에서 처음 {n}개 항의 합을 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _GeoSumSkeleton:
    """등비합 뼈대 — 첫째항 a·공비 r·항수 n. Sₙ = a(rⁿ−1)/(r−1). 모든 수치의 단일 진실 원천."""

    first: int
    ratio: int
    term: int  # 항수 n (≥2)

    @property
    def answer(self) -> int:
        """정답 — Sₙ = a(rⁿ−1)/(r−1). r∈{2,3,5}·a에서 정수(풀 빌드가 정수만 채택)."""
        return int(self.first * (self.ratio**self.term - 1) // (self.ratio - 1))

    @property
    def _is_integer(self) -> bool:
        """합이 정수인지 — a(rⁿ−1)이 (r−1)로 나누어떨어지는가(풀 필터용)."""
        return bool(self.first * (self.ratio**self.term - 1) % (self.ratio - 1) == 0)

    @property
    def formula(self) -> str:
        """합 공식의 SymPy 계산식 — 'a(rⁿ−1)/(r−1)'. condition·solution_steps의 단일 진실 원천."""
        return f"{self.first}*({self.ratio}**{self.term} - 1)/({self.ratio} - 1)"

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − a(rⁿ−1)/(r−1) = 0'. 합 공식 그대로(독립 재계산)."""
        return f"x - ({self.formula}) = 0"

    @property
    def difficulty(self) -> float:
        # 재보정(S2-08·계통 관찰 2): 등비합 Sₙ=a(rⁿ−1)/(r−1)은 거듭제곱·나눗셈이 얹혀 등차합보다
        # 살짝 무겁지만 QUAD-EQ(base 2.0) 언저리다. base 3.2→2.0으로 내리고 크기 가산은 유지한다.
        difficulty = 2.0
        if self.ratio >= 5:
            difficulty += 0.2
        if self.term >= 6:
            difficulty += 0.1
        if self.answer > 500:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_geo_sum_pool() -> tuple[_GeoSumSkeleton, ...]:
    """결정론 등비합 뼈대 풀 — (a, r, n) 열거·정수 합·합 상한·**답 유일 dedup**·고정 시드 셔플."""
    seen: set[int] = set()
    pool: list[_GeoSumSkeleton] = []
    for first in range(1, 6):
        for ratio in (2, 3, 5):
            for term in range(3, 9):
                skeleton = _GeoSumSkeleton(first=first, ratio=ratio, term=term)
                if not skeleton._is_integer:
                    continue
                answer = skeleton.answer
                if answer > _GEO_SUM_MAX or answer in seen:
                    continue
                seen.add(answer)
                pool.append(skeleton)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _geo_sum_explanation(skeleton: _GeoSumSkeleton) -> str:
    """등비합 해설 — 합 공식을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    return (
        f"등비수열의 합은 첫째항×(공비의 항수 거듭제곱−1)÷(공비−1)과 같으므로, "
        f"제{skeleton.term}항까지의 합은 {skeleton.answer} 이다."
    )


@deterministic_generator
class GeometricSumSkeletonGenerator:
    """등비수열의 합 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    풀(정수 합·답 유일)을 순서대로 소비(소진 시 None). 등차합 형제와 동일 좌석·게이트·근 검증
    스택을 공유한다(도메인 분담). 답이 유일해 signature도 유일 — 구조 dedup과 정합.
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-gesum",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("GEO-SUM",),
        concept_tags: Sequence[ConceptTag] = _GEO_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_geo_sum_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 등비합 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            condition = skeleton.condition
            if self._skip is not None:
                signature = canonical_signature(condition, "unique")
                if signature is not None and signature in self._skip:
                    continue
            return self._assemble(spec, skeleton, condition)
        return None

    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _GeoSumSkeleton, condition: str
    ) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        question_text = _GEO_SUM_TEMPLATES[self._index % len(_GEO_SUM_TEMPLATES)].format(
            a=skeleton.first, r=skeleton.ratio, n=skeleton.term, josa=eul_reul(str(skeleton.term))
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
            answer_format=_sum_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_geo_sum_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 등비수열의 합 스켈레톤 조립(a·r·n→Sₙ 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # x - a(rⁿ-1)/(r-1) = 0(검산용·독립 재계산)
            answer_map={"x": answer_text},
            answer_selection="unique",  # 합은 유일값
            # S2-02: 합 공식 대입식→값 체인 방출 — Tier2·상시 재검증·WH-S replay가 소비.
            solution_steps=_sum_steps(skeleton.formula, skeleton.answer),
            concept_tags=list(self._concept_tags),
        )
