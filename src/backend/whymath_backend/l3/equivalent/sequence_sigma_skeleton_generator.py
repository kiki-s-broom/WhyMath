"""수열의 합 — Σ의 성질·여러 가지 수열의 합 스켈레톤 생성기 — W2 Phase1 #2(결정론·LLM 0).

`ArithmeticSequenceSkeletonGenerator`/`ArithmeticSumSkeletonGenerator` 형제군의 확장이다.
등차·등비 일반항·합은 이미 채웠으나(S2), [12대수03-04](Σ의 뜻과 성질)·[12대수03-05](여러
가지 수열의 합)이 0건이었다 — 이 생성기가 두 성취기준의 첫 코퍼스를 확보한다.

두 클래스:
- `SigmaLinearitySkeletonGenerator` — Σ 선형성(Σ(a·k+b) = a·Σk + b·n, Σc=c·n)을 계산
  문제로 exercising. 1부터 n까지 각 자연수에 a를 곱하고 b를 더한 값들의 합.
- `PowerSumSkeletonGenerator` — 거듭제곱 합(Σk²=n(n+1)(2n+1)/6·Σk³=(n(n+1)/2)²).
  `kind`(square/cube) 필터로 밴드 분리 — `direction`/`operation` 필터 관례 계승
  (S4-22 밴드 중복 사고 재발 방지 — 필터 없이 밴드별 인스턴스를 만들면 고정 시드 풀이
  처음부터 재생돼 같은 뼈대를 중복 방출한다).

핵심 통찰(재구현 0): 두 문제군 모두 "x에 대한 방정식의 유일해"로 환원된다. 닫힌 합
공식을 그대로 조건식 `x − (공식) = 0`으로 공급하면 기존 근 검증 스택(`verify_answer`=
대입 잔차·`derive_selected_root`=solve)이 **무변경 재사용**된다. SymPy가 독립 재계산해
생성기의 파이썬 계산과 교차 검증한다(생성≠검증).

⚠️ 구조 dedup 주의: 조건은 `x − 상수`로 접혀(canonical_signature 非None) 같은 값이면 같은
signature가 된다 — 형제 수열 생성기와 동일 전략으로 **풀을 답 기준 dedup**해 답이 유일한
뼈대만 남긴다(`PowerSumSkeletonGenerator`는 square·cube 두 kind가 섞인 풀 전체에서 답
기준 dedup 후 kind 필터를 적용 — 필터가 실제로 밴드를 분리하는지는 `sequence_sigma_batch`
배치 테스트가 problem_id 유일성으로 회귀 봉인한다).

⚠️ 표기 주의: **Σ·거듭제곱 위첨자(²·³) 등 신규 Unicode 글리프를 발문에 쓰지 않는다** —
순수 한국어 서술로 지칭한다(2026-08-07 실측 교훈: `QuadraticInequalityBoundarySkeleton
Generator`가 α·β를 처음 시도했다가 `notation_coverage_eval` 게이트가 렌더 검증 안 된
신규 글리프 유입을 차단해 순수 서술형으로 교정한 전례를 이 생성기는 처음부터 따른다).

범위(v1): 양의 정수 결과·단답형만. Σ 표기 자체를 발문에 노출(글리프)·부분분수 소거형
합(계차수열)·귀납적 정의와의 결합은 후속.

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지(canonicalize)·L1(ConceptTag)만
import(L4 참조 0). 난이도는 지역 함수(공유 difficulty.py 불침범·도메인 분담 관례 계승).
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
    "PowerSumKind",
    "PowerSumSkeletonGenerator",
    "SigmaLinearitySkeletonGenerator",
]

_POOL_SEED = 20260807

_SIGMA_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12대수03-04", role="PRIMARY", relevance=0.95),
)
_POWER_SUM_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12대수03-05", role="PRIMARY", relevance=0.95),
)


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _positive_answer_format(answer: int) -> AnswerFormat:
    """정답 형태 — 양의 정수=자연수·그 외=실수(형제 생성기 미러). v1은 전건 양의 정수."""
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


# ── Σ 선형성: 1부터 n까지 (a·k+b)의 합 = a·n(n+1)/2 + b·n ────────────────────
_SIGMA_MAX = 2000
_SIGMA_TEMPLATES: tuple[str, ...] = (
    "1부터 {n}까지의 자연수 각각에 {a}{a_josa} 곱한 후 {b}{b_josa} 더한 값들을 모두 "
    "합{josa} 구하시오.",
    "1부터 {n}까지의 자연수를 k라 할 때, {ak_term}+{b}의 값을 k=1부터 {n}까지 모두 "
    "더한 합을 구하시오.",
    "1부터 {n}까지의 자연수 각각을 {a}배 하고 {b}씩 더한 다음, 그 값들의 총합을 구하시오.",
)


def _ak_term(scale: int) -> str:
    """계수 항 표기 — 배율 1이면 계수를 생략(예 '1k' 아닌 'k'). 형제 생성기의 계수-1 생략 관례."""
    return "k" if scale == 1 else f"{scale}k"


@dataclass(frozen=True, slots=True)
class _SigmaSkeleton:
    """Σ 선형성 뼈대 — 배율 a·상수항 b·항수 n. 합 = a·n(n+1)/2 + b·n. 단일 진실 원천."""

    scale: int
    constant: int
    count: int  # 항수 n(1부터 n까지)

    @property
    def answer(self) -> int:
        """정답 — Σ(a·k+b), k=1..n = a·n(n+1)/2 + b·n."""
        return self.scale * self.count * (self.count + 1) // 2 + self.constant * self.count

    @property
    def formula(self) -> str:
        """합 공식의 SymPy 계산식 — 'a·n(n+1)/2 + b·n'. condition·steps의 단일 진실 원천."""
        return f"{self.scale}*{self.count}*({self.count} + 1)/2 + {self.constant}*{self.count}"

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − (a·n(n+1)/2 + b·n) = 0'. Σ 선형성 공식 그대로(독립 재계산)."""
        return f"x - ({self.formula}) = 0"

    @property
    def difficulty(self) -> float:
        # QUAD-EQ(base 2.0) 대비: 두 공식(Σk·Σ상수)을 합성하는 2스텝이라 순수 등차합(1.9)보단
        # 살짝 무겁지만 거듭제곱은 없어 제곱합(square, base 2.1)보단 가볍다. base 2.0에서 항수·
        # 배율·값 크기로 가산.
        difficulty = 2.0
        if self.count >= 10:
            difficulty += 0.2
        if self.scale >= 4:
            difficulty += 0.1
        if self.answer > 500:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_sigma_pool() -> tuple[_SigmaSkeleton, ...]:
    """결정론 Σ 선형성 뼈대 풀 — (a, b, n) 열거·합 상한·**답 유일 dedup**·고정 시드 셔플."""
    seen: set[int] = set()
    pool: list[_SigmaSkeleton] = []
    for scale in range(1, 6):
        for constant in range(1, 10):
            for count in range(3, 16):
                skeleton = _SigmaSkeleton(scale=scale, constant=constant, count=count)
                answer = skeleton.answer
                if answer > _SIGMA_MAX or answer in seen:
                    continue
                seen.add(answer)
                pool.append(skeleton)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _sigma_steps(formula: str, answer: int) -> list[str]:
    """Σ 선형성 풀이의 검증 단계 체인(S2-02) — 공식 대입식 → 값(표현식 동치·Tier2 correct)."""
    return [formula, str(answer)]


def _sigma_explanation(skeleton: _SigmaSkeleton) -> str:
    """Σ 선형성 해설 — 합의 성질(상수배·상수항 분리)을 자연어로 서술(결정론·위생 청정)."""
    return (
        "합의 기호가 가진 성질에 따라 배율은 앞으로 빼내고 더해진 상수는 항수만큼 곱해 "
        f"각각 더하면 되므로, 1부터 {skeleton.count}까지의 합은 {skeleton.answer} 이다."
    )


@deterministic_generator
class SigmaLinearitySkeletonGenerator:
    """Σ 선형성 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    풀(답 유일)을 순서대로 소비하며 후보를 낸다(소진 시 None). 형제(등차·등비 수열)와 같은
    좌석·게이트를 공유한다(도메인 분담). 답이 유일해 signature도 유일 — skip 집합과 정합.
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-sigmalin",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("SIGMA-LINEARITY",),
        concept_tags: Sequence[ConceptTag] = _SIGMA_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_sigma_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 Σ 선형성 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
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
        self, spec: EquivalenceSpec, skeleton: _SigmaSkeleton, condition: str
    ) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        template = _SIGMA_TEMPLATES[self._index % len(_SIGMA_TEMPLATES)]
        question_text = template.format(
            a=skeleton.scale,
            b=skeleton.constant,
            n=skeleton.count,
            ak_term=_ak_term(skeleton.scale),
            a_josa=eul_reul(str(skeleton.scale)),
            b_josa=eul_reul(str(skeleton.constant)),
            josa=eul_reul("합"),
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
            answer_format=_positive_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_sigma_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 Σ 선형성 스켈레톤 조립(a·b·n→합 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # x - (a*n*(n+1)/2 + b*n) = 0(검산용·독립 재계산)
            answer_map={"x": answer_text},
            answer_selection="unique",  # 합은 유일값
            solution_steps=_sigma_steps(skeleton.formula, skeleton.answer),
            concept_tags=list(self._concept_tags),
        )


# ── 거듭제곱 합: Σk²=n(n+1)(2n+1)/6 · Σk³=(n(n+1)/2)² ────────────────────────
PowerSumKind = Literal["square", "cube"]

_SQUARE_TEMPLATES: tuple[str, ...] = (
    "1부터 {n}까지의 자연수를 각각 제곱하여 모두 더한 값을 구하시오.",
    "1부터 {n}까지의 자연수의 제곱의 합을 구하시오.",
)
_CUBE_TEMPLATES: tuple[str, ...] = (
    "1부터 {n}까지의 자연수를 각각 세제곱하여 모두 더한 값을 구하시오.",
    "1부터 {n}까지의 자연수의 세제곱의 합을 구하시오.",
)
_POWER_SQUARE_MAX = 3000
_POWER_CUBE_MAX = 20000
# 상한을 벗어나는 kind는 열거에서 자연히 절삭 — n 상한은 넉넉히 잡아 상한 필터가 실질 경계.
_SQUARE_N_RANGE = range(3, 25)
_CUBE_N_RANGE = range(3, 20)


@dataclass(frozen=True, slots=True)
class _PowerSumSkeleton:
    """거듭제곱 합 뼈대 — kind(square/cube)·항수 n. 닫힌 합 공식의 단일 진실 원천."""

    kind: PowerSumKind
    count: int  # 항수 n(1부터 n까지)

    @property
    def answer(self) -> int:
        """정답 — square: n(n+1)(2n+1)/6, cube: (n(n+1)/2)²."""
        if self.kind == "square":
            return self.count * (self.count + 1) * (2 * self.count + 1) // 6
        return (self.count * (self.count + 1) // 2) ** 2

    @property
    def formula(self) -> str:
        """합 공식의 SymPy 계산식. condition·solution_steps의 단일 진실 원천."""
        if self.kind == "square":
            return f"{self.count}*({self.count} + 1)*(2*{self.count} + 1)/6"
        return f"({self.count}*({self.count} + 1)/2)**2"

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − (닫힌 합 공식) = 0'. 공식 그대로 공급(독립 재계산)."""
        return f"x - ({self.formula}) = 0"

    @property
    def difficulty(self) -> float:
        # QUAD-EQ(base 2.0) 대비: square는 3항 곱(1스텝 무거움)이라 base 2.1, cube는 제곱까지
        # 얹혀 base 2.3 — 등차·등비합(1.9~2.0)보다 형식이 무겁다는 계통 관찰과 정합.
        difficulty = 2.1 if self.kind == "square" else 2.3
        threshold = 15 if self.kind == "square" else 10
        if self.count >= threshold:
            difficulty += 0.2
        cap = 800 if self.kind == "square" else 3000
        if self.answer > cap:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_power_sum_pool() -> tuple[_PowerSumSkeleton, ...]:
    """결정론 거듭제곱 합 뼈대 풀 — kind×n 열거·상한·**답 유일 dedup**(kind 전체 공유)·고정 셔플.

    square·cube가 우연히 같은 답을 낼 수 있어(예: 작은 n) 답 기준 dedup을 kind 구분 없이
    전체 풀에 적용한다(형제 수열 생성기 관례 미러) — 이래야 condition의 canonical_signature
    (=답값)가 풀 전체에서 유일해 오케스트레이터 구조 dedup과 정합한다.
    """
    seen: set[int] = set()
    pool: list[_PowerSumSkeleton] = []
    bands: tuple[tuple[PowerSumKind, range, int], ...] = (
        ("square", _SQUARE_N_RANGE, _POWER_SQUARE_MAX),
        ("cube", _CUBE_N_RANGE, _POWER_CUBE_MAX),
    )
    for kind, n_range, cap in bands:
        for count in n_range:
            skeleton = _PowerSumSkeleton(kind=kind, count=count)
            answer = skeleton.answer
            if answer > cap or answer in seen:
                continue
            seen.add(answer)
            pool.append(skeleton)
    random.Random(_POOL_SEED + 1).shuffle(pool)
    return tuple(pool)


def _power_sum_steps(formula: str, answer: int) -> list[str]:
    """거듭제곱 합 풀이의 검증 단계 체인(S2-02) — 공식 대입식 → 값(표현식 동치·Tier2 correct)."""
    return [formula, str(answer)]


def _power_sum_explanation(skeleton: _PowerSumSkeleton) -> str:
    """거듭제곱 합 해설 — 닫힌 공식 사용을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    which = "제곱의 합 공식" if skeleton.kind == "square" else "세제곱의 합 공식"
    return (
        f"여러 가지 수열의 합 중 {which}을 이용하면, "
        f"1부터 {skeleton.count}까지의 합은 {skeleton.answer} 이다."
    )


@deterministic_generator
class PowerSumSkeletonGenerator:
    """거듭제곱 합 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    `kind`(square/cube) 필터로 밴드를 분리한다(direction/operation 필터 관례 계승 — 필터
    없이 밴드별 인스턴스를 만들면 고정 시드 풀이 처음부터 재생돼 같은 뼈대를 중복 방출한다,
    2026-08-05 elementary_addsub 사고 재발 방지). 풀(답 유일)을 순서대로 소비(소진 시 None).
    """

    def __init__(
        self,
        *,
        kind: PowerSumKind | None = None,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-powersum",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("POWER-SUM",),
        concept_tags: Sequence[ConceptTag] = _POWER_SUM_CONCEPT_TAGS,
    ) -> None:
        pool = _build_power_sum_pool()
        self._pool = tuple(s for s in pool if kind is None or s.kind == kind)
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 거듭제곱 합 뼈대를 후보로 조립 — skip 집합은 건너뛰고, 풀 소진 시 None."""
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
        self, spec: EquivalenceSpec, skeleton: _PowerSumSkeleton, condition: str
    ) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        templates = _SQUARE_TEMPLATES if skeleton.kind == "square" else _CUBE_TEMPLATES
        question_text = templates[self._index % len(templates)].format(n=skeleton.count)
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
            answer_format=_positive_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_power_sum_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 거듭제곱 합 스켈레톤 조립(kind·n→닫힌 공식 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # x - (닫힌 합 공식) = 0(검산용·독립 재계산)
            answer_map={"x": answer_text},
            answer_selection="unique",  # 합은 유일값
            solution_steps=_power_sum_steps(skeleton.formula, skeleton.answer),
            concept_tags=list(self._concept_tags),
        )
