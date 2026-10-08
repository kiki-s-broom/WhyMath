"""수열(등차·등비) 파라메트릭 스켈레톤 동등문제 생성기 — S2 대수 확장(결정론·LLM 0).

`ExponentialEquationSkeletonGenerator`(지수·로그)·`SkeletonEquivalentProblemGenerator`(이차방정식)의
**수열 형제**다. 같은 `EquivalentProblemGenerator` 좌석을 구현하되 수학 실체가 다르다: 등차수열
(첫째항 a·공차 d의 제n항 aₙ = a + (n−1)d)·등비수열(첫째항 a·공비 r의 제n항 aₙ = a·rⁿ⁻¹)의
일반항 값을 낸다. 배경(도메인 분담): 생성 코퍼스가 이차(고1)·미적분(고3)·지수로그(고2)에 집중돼
**수열(고2·대수)이 0건**이었다 — 이 생성기가 수열 코퍼스를 처음 확보한다.

핵심 통찰(재구현 0): **수열의 일반항도 "x에 대한 방정식의 유일해"로 환원**된다. 일반항 공식을
그대로 조건식 `x − (a + (n−1)·d) = 0`(등차)·`x − (a·rⁿ⁻¹) = 0`(등비)으로 공급하면, 기존 근 검증
스택(`verify_answer`=대입 잔차, `derive_selected_root`=`sympy.solve`)이 **무변경 재사용**된다.
조건식에 *계산식*(닫힌 산술)을 넣으므로 derive-and-verify가 SymPy로 **독립 재계산**해 생성기의
파이썬 계산과 교차 검증한다(생성≠검증 — 계산 버그를 게이트가 잡는다).

⚠️ 구조 dedup 주의: 조건식은 SymPy가 `x − 상수`로 접어(canonical_signature 비다항 아님·非None)
**같은 답이면 같은 signature**가 된다(a=3·d=2·n=10 와 a=1·d=4·n=6은 둘 다 21 → 충돌). 서로 다른
문제가 오병합되지 않게, **풀을 답 기준으로 dedup**해 답이 유일한 뼈대만 남긴다(각 답 첫 출현·
결정론 순서). 답이 유일하면 signature도 유일 — 오케스트레이터 구조 dedup과 정합(오병합 0).

범위(v1): 등차·등비 *일반항*(제n항)·양의 정수 항·단답형만. 수열의 *합*(Sₙ), 음의 공차/공비,
귀납적 정의, 객관식·오개념 distractor, LLM 발문 다양화는 후속(별도 검증 재료·설계 필요).

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지(canonicalize)·L1(ConceptTag)만
import(L4 참조 0). 난이도는 공유 difficulty.py를 건드리지 않고 지역 함수로 둔다(도메인 분담).
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
    "ArithmeticSequenceSkeletonGenerator",
    "GeometricSequenceSkeletonGenerator",
]

# 풀 셔플 고정 시드 — 같은 구성은 같은 출제 순서(재현·디버그). 형제 생성기 규약 미러.
_POOL_SEED = 20260706

# 개념 태깅 — 개념그래프 원천 src_id(등차=등차수열의 일반항과 합·등비=등비수열의 일반항과 합).
# L1 데이터 키라 L4 오개념 주입 원칙 밖(형제 생성기 미러).
_ARITH_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12대수03-02", role="PRIMARY", relevance=0.95),
)
_GEO_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12대수03-03", role="PRIMARY", relevance=0.95),
)

# 값 상한 — 손계산 가능한 범위(과대 수치 회피). 등차는 200·등비는 1000(거듭제곱 성장 감안).
_ARITH_MAX = 200
_GEO_MAX = 1000


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _seq_answer_format(answer: int) -> AnswerFormat:
    """정답의 형태 — 양의 정수=자연수·그 외=실수(형제 생성기 미러). 수열 v1은 전건 양의 정수."""
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


# ── 등차수열 aₙ = a + (n−1)d ─────────────────────────────────────────────────
_ARITH_TEMPLATES: tuple[str, ...] = (
    "첫째항이 {a}, 공차가 {d}인 등차수열의 제{n}항을 구하시오.",
    "등차수열 {{aₙ}}의 첫째항이 {a}이고 공차가 {d}일 때, 제{n}항을 구하시오.",
    "첫째항 {a}, 공차 {d}인 등차수열에서 {n}번째 항의 값을 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _ArithSkeleton:
    """등차수열 뼈대 — 첫째항 a·공차 d·항수 n. 제n항 = a + (n−1)d. 모든 수치의 단일 진실 원천."""

    first: int
    diff: int
    term: int  # 항수 n (≥2)

    @property
    def answer(self) -> int:
        """정답 — 제n항 aₙ = a + (n−1)d."""
        return self.first + (self.term - 1) * self.diff

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − (a + (n−1)·d) = 0'. 일반항 공식을 그대로 공급(독립 재계산)."""
        return f"x - ({self.first} + ({self.term} - 1)*{self.diff}) = 0"

    @property
    def difficulty(self) -> float:
        # 재보정(S2-08·계통 관찰 2): 일반항 공식 aₙ=a+(n−1)d 직대입은 **1스텝**이라 QUAD-EQ
        # 인수분해(base 2.0)보다 쉽다. 이전 base 2.7(표본 13~16 인플레)을 1.6으로 내려 평범한
        # 대입이 2.0 미만에 앉게 하고, 항수·공차·값 크기 가산은 유지한다.
        difficulty = 1.6
        if self.term >= 10:
            difficulty += 0.2
        if self.diff >= 4:
            difficulty += 0.2
        if self.answer > 100:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_arith_pool() -> tuple[_ArithSkeleton, ...]:
    """결정론 등차 뼈대 풀 — (a, d, n) 열거·답 상한·**답 유일 dedup**·고정 시드 셔플.

    답이 유일해야 signature도 유일하다(구조 dedup 오병합 방지) — 열거를 결정론 순서로 돌며 각 답의
    첫 출현 뼈대만 남긴다. 양의 정수 답만(a·d>0).
    """
    seen: set[int] = set()
    pool: list[_ArithSkeleton] = []
    for first in range(1, 10):
        for diff in range(1, 7):
            for term in range(4, 16):
                skeleton = _ArithSkeleton(first=first, diff=diff, term=term)
                answer = skeleton.answer
                if answer > _ARITH_MAX or answer in seen:
                    continue
                seen.add(answer)
                pool.append(skeleton)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _arith_steps(skeleton: _ArithSkeleton) -> list[str]:
    """등차 일반항 풀이의 검증 단계 체인(S2-02) — 공식 대입식 → 값(표현식 동치·Tier2 correct).

    QUAD-EQ `_factoring_steps` 패턴 미러: 풀이의 *검증 가능한 대수 골자*(공식 대입 산술)만
    구조화한다 — 서술은 `answer_explanation`이 담당한다(표현≠의미). 수용 게이트는 unverifiable
    단계 0을 요구하므로(acceptance §verified) 전이가 SymPy로 증명 가능해야 한다 — 대입식
    `a + (n−1)*d`와 그 값은 닫힌 산술 동치라 항상 correct(verify_step 실측 확인).
    """
    return [
        f"{skeleton.first} + ({skeleton.term} - 1)*{skeleton.diff}",
        str(skeleton.answer),
    ]


def _arith_explanation(skeleton: _ArithSkeleton) -> str:
    """등차 해설 — 일반항 공식을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    return (
        f"등차수열의 제n항은 첫째항에 공차를 (n−1)번 더한 값이므로, 제{skeleton.term}항은 "
        f"{skeleton.answer} 이다."
    )


@deterministic_generator
class ArithmeticSequenceSkeletonGenerator:
    """등차수열 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    풀(답 유일)을 순서대로 소비하며 후보를 낸다(소진 시 None). 형제(지수·로그·이차·미적분)와 같은
    좌석·게이트를 공유한다(도메인 분담·하이브리드). 답이 유일해 signature도 유일 — skip 집합과 정합.
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-arseq",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("ARITH-SEQ",),
        concept_tags: Sequence[ConceptTag] = _ARITH_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_arith_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 등차 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
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
        self, spec: EquivalenceSpec, skeleton: _ArithSkeleton, condition: str
    ) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        question_text = _ARITH_TEMPLATES[self._index % len(_ARITH_TEMPLATES)].format(
            a=skeleton.first, d=skeleton.diff, n=skeleton.term
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
            answer_format=_seq_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_arith_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 등차수열 스켈레톤 조립(a·d·n→제n항 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # x - (a + (n-1)*d) = 0(검산용·독립 재계산)
            answer_map={"x": answer_text},
            answer_selection="unique",  # 일반항은 유일값
            # S2-02: 공식 대입 산술 체인(대입식→값)을 구조 단계로 방출 — 수용 게이트 Tier2·
            # 상시 재검증(corpus_reverify)·WH-S replay가 소비한다(QUAD-EQ steps= 배선 미러).
            solution_steps=_arith_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )


# ── 등비수열 aₙ = a·rⁿ⁻¹ ─────────────────────────────────────────────────────
_GEO_TEMPLATES: tuple[str, ...] = (
    "첫째항이 {a}, 공비가 {r}인 등비수열의 제{n}항을 구하시오.",
    "등비수열 {{aₙ}}의 첫째항이 {a}이고 공비가 {r}일 때, 제{n}항을 구하시오.",
    "첫째항 {a}, 공비 {r}인 등비수열에서 {n}번째 항의 값을 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _GeoSkeleton:
    """등비수열 뼈대 — 첫째항 a·공비 r·항수 n. 제n항 = a·rⁿ⁻¹. 모든 수치의 단일 진실 원천."""

    first: int
    ratio: int
    term: int  # 항수 n (≥2)

    @property
    def answer(self) -> int:
        """정답 — 제n항 aₙ = a·rⁿ⁻¹."""
        return int(self.first * self.ratio ** (self.term - 1))

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − (a·rⁿ⁻¹) = 0'. 일반항 공식을 그대로 공급(독립 재계산)."""
        return f"x - ({self.first} * {self.ratio}**({self.term} - 1)) = 0"

    @property
    def difficulty(self) -> float:
        # 재보정(S2-08·계통 관찰 2): 일반항 aₙ=a·rⁿ⁻¹ 직대입 1스텝이라 QUAD-EQ(base 2.0)보다
        # 쉽다. 이전 base 3.0(표본 27 인플레)을 1.7로 내리고 공비·항수·값 크기 가산은 유지한다.
        difficulty = 1.7
        if self.ratio >= 5:
            difficulty += 0.2
        if self.term >= 6:
            difficulty += 0.2
        if self.answer > 200:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_geo_pool() -> tuple[_GeoSkeleton, ...]:
    """결정론 등비 뼈대 풀 — (a, r, n) 열거·답 상한·**답 유일 dedup**·고정 시드 셔플.

    공비 r>1·첫째항 a>0라 답은 양의 정수. 답이 유일한 뼈대만 남겨 signature 유일성을 보장한다.
    """
    seen: set[int] = set()
    pool: list[_GeoSkeleton] = []
    for first in range(1, 6):
        for ratio in (2, 3, 5):
            for term in range(3, 9):
                skeleton = _GeoSkeleton(first=first, ratio=ratio, term=term)
                answer = skeleton.answer
                if answer > _GEO_MAX or answer in seen:
                    continue
                seen.add(answer)
                pool.append(skeleton)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _geo_steps(skeleton: _GeoSkeleton) -> list[str]:
    """등비 일반항 풀이의 검증 단계 체인(S2-02) — 공식 대입식 → 값(표현식 동치·Tier2 correct).

    등차 `_arith_steps`의 등비 형제. 대입식 `a·r**(n−1)`과 그 값은 닫힌 산술 동치라 전이가
    항상 correct(verify_step 프로브 실측: '2*3**(5 - 1)' → '162' correct·풀 최대 지수 포함).
    """
    return [
        f"{skeleton.first} * {skeleton.ratio}**({skeleton.term} - 1)",
        str(skeleton.answer),
    ]


def _geo_explanation(skeleton: _GeoSkeleton) -> str:
    """등비 해설 — 일반항 공식을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    return (
        f"등비수열의 제n항은 첫째항에 공비를 (n−1)번 곱한 값이므로, 제{skeleton.term}항은 "
        f"{skeleton.answer} 이다."
    )


@deterministic_generator
class GeometricSequenceSkeletonGenerator:
    """등비수열 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    풀(답 유일)을 순서대로 소비(소진 시 None). 등차 형제와 동일 좌석·게이트·근 검증 스택을 공유
    한다(도메인 분담). 답이 유일해 signature도 유일 — 구조 dedup과 정합.
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-geseq",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("GEO-SEQ",),
        concept_tags: Sequence[ConceptTag] = _GEO_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_geo_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 등비 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
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
        self, spec: EquivalenceSpec, skeleton: _GeoSkeleton, condition: str
    ) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        question_text = _GEO_TEMPLATES[self._index % len(_GEO_TEMPLATES)].format(
            a=skeleton.first, r=skeleton.ratio, n=skeleton.term
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
            answer_format=_seq_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_geo_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 등비수열 스켈레톤 조립(a·r·n→제n항 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # x - (a * r**(n-1)) = 0(검산용·독립 재계산)
            answer_map={"x": answer_text},
            answer_selection="unique",  # 일반항은 유일값
            # S2-02: 공식 대입 산술 체인(대입식→값)을 구조 단계로 방출 — 등차 형제 배선 미러.
            solution_steps=_geo_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )
