"""초등 나눗셈(두 자리 수) 몫과 나머지 결정론 스켈레톤 생성기 — W2 Phase2 #1(결정론·LLM 0).

`elementary_addsub_skeleton_generator`(초등 덧셈·뺄셈)의 형제 — 초등 "수와 연산" 영역의
다음 착점이다. `[4수01-07]`(나눗셈(두 자리 수))이 0건이었다 — 이 생성기가 첫 코퍼스를
확보한다. 개념그래프 매핑: `D3`(나눗셈(÷두 자리)) — legacy 437 공간에 실존.

`kind`(quotient/remainder) 필터로 밴드 분리. dividend÷divisor의 몫과 나머지를 구성상
정확히 통제한다 — divisor(10~49)·quotient(2~49)를 먼저 고르고 remainder(0~divisor-1)를
더해 dividend = divisor×quotient + remainder로 역산한다(항상 정확한 몫·나머지 보장, 나머지
< 나누는 수 불변식도 구성 자체로 성립).

**검증 설계**: 조건은 **주어진 정보(dividend·divisor)만으로** SymPy `floor()`를 이용해 몫·
나머지를 독립 재유도한다 — 생성기가 미리 계산해 둔 quotient/remainder를 그대로 되묻는 게
아니라 원시 나눗셈 데이터에서 다시 계산하게 해 진짜 교차검증이 되게 한다(형제 생성기들의
"생성≠검증" 관례 계승). `floor(dividend/divisor)`가 몫, `dividend − divisor×floor(...)`가
나머지 — Tier1이 두 식 모두 정확히 검산함을 스파이크로 확인.

범위(v1): 두 자리 나누는 수·자연수 몫·나머지만. 세 자리 나눗셈·소수 나눗셈은 후속.

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
from whymath_backend.lang.josa import eul_reul, euro_ro
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

__all__ = ["DivisionRemainderKind", "TwoDigitDivisionSkeletonGenerator"]

_POOL_SEED = 20260807

_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="D3", role="PRIMARY", relevance=0.95),
)

_DIVISOR_RANGE = range(10, 50)
_QUOTIENT_RANGE = range(2, 50)

DivisionRemainderKind = Literal["quotient", "remainder"]

_QUOTIENT_TEMPLATES: tuple[str, ...] = (
    "{dividend}÷{divisor}의 몫을 구하시오.",
    "{dividend}{eul_reul} {divisor}{euro_ro} 나누었을 때의 몫을 구하시오.",
)
_REMAINDER_TEMPLATES: tuple[str, ...] = (
    "{dividend}÷{divisor}의 나머지를 구하시오.",
    "{dividend}{eul_reul} {divisor}{euro_ro} 나누었을 때의 나머지를 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _DivisionSkeleton:
    """나눗셈 뼈대 — 나누는 수·몫·나머지(역산으로 구성). dividend는 파생값. 단일 진실 원천."""

    kind: DivisionRemainderKind
    divisor: int
    quotient: int
    remainder: int  # 0 <= remainder < divisor(구성상 항상 성립).

    @property
    def dividend(self) -> int:
        return self.divisor * self.quotient + self.remainder

    @property
    def answer(self) -> int:
        return self.quotient if self.kind == "quotient" else self.remainder

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — dividend·divisor(주어진 정보)만으로 floor()가 독립 재유도."""
        if self.kind == "quotient":
            return f"x - floor({self.dividend}/{self.divisor}) = 0"
        return f"x - ({self.dividend} - {self.divisor}*floor({self.dividend}/{self.divisor})) = 0"

    @property
    def difficulty(self) -> float:
        # 초등 3-4학년군 기준 — 두 자리 나눗셈은 procedural 하단(1.5~2.0 대역).
        difficulty = 1.6
        if self.divisor >= 30:
            difficulty += 0.1
        if self.quotient >= 30:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_pool(kind: DivisionRemainderKind | None = None) -> tuple[_DivisionSkeleton, ...]:
    """결정론 나눗셈 뼈대 풀 — kind×divisor×quotient 열거·remainder는 divisor마다 순환 샘플
    (전건 조합을 다 열거하면 과대 — 나머지 하나를 결정론적으로 골라 조합 폭발을 억제)·고정 셔플.
    """
    kinds: tuple[DivisionRemainderKind, ...]
    kinds = ("quotient", "remainder") if kind is None else (kind,)
    pool: list[_DivisionSkeleton] = []
    for kd in kinds:
        for divisor in _DIVISOR_RANGE:
            for quotient in _QUOTIENT_RANGE:
                remainder = (divisor + quotient) % divisor  # 결정론 순환 나머지(0~divisor-1).
                skeleton = _DivisionSkeleton(
                    kind=kd, divisor=divisor, quotient=quotient, remainder=remainder
                )
                pool.append(skeleton)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _explanation(skeleton: _DivisionSkeleton) -> str:
    """나눗셈 해설 — 몫과 나머지 관계를 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    if skeleton.kind == "quotient":
        return (
            "나누는 수가 나뉠 수에 몇 번 들어가는지 세면 몫을 구할 수 있으므로, "
            f"구하는 몫은 {skeleton.answer} 이다."
        )
    return "몫을 구하고 남은 만큼이 나머지이므로, 구하는 나머지는 " f"{skeleton.answer} 이다."


def _answer_format(value: int) -> AnswerFormat:
    return AnswerFormat.자연수 if value > 0 else AnswerFormat.실수


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


@deterministic_generator
class TwoDigitDivisionSkeletonGenerator:
    """두 자리 나눗셈 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `kind`(quotient/remainder) 필터로 밴드를 분리한다(direction/operation 필터 관례 계승 —
    필터 없이 밴드별 인스턴스를 만들면 고정 시드 풀이 처음부터 재생돼 같은 뼈대를 중복
    방출한다).
    """

    def __init__(
        self,
        *,
        kind: DivisionRemainderKind | None = None,
        slug_prefix: str = "wm-div2digit",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("TWO-DIGIT-DIVISION",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_pool(kind)
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 나눗셈 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _DivisionSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        templates = _QUOTIENT_TEMPLATES if skeleton.kind == "quotient" else _REMAINDER_TEMPLATES
        question_text = templates[self._index % len(templates)].format(
            dividend=skeleton.dividend,
            divisor=skeleton.divisor,
            eul_reul=eul_reul(str(skeleton.dividend)),
            euro_ro=euro_ro(str(skeleton.divisor)),
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
            answer_format=_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 나눗셈 스켈레톤 조립(divisor·quotient·remainder→dividend 역산)",
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
