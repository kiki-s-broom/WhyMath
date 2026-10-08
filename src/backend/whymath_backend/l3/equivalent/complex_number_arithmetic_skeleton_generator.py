"""고등 복소수 사칙연산(덧셈·뺄셈·곱셈) 스켈레톤 생성기 — W2 Phase4 #6(결정론·LLM 0).

`[10공수1-02-01]`("복소수의 뜻과 성질을 설명하고, 사칙연산을 수행할 수 있다." — NCIC
실측, 2026-08-08)의 첫 코퍼스. S4-47(다항식 사칙연산)·S4-48(인수분해)·S4-49(호도법)
웨이브의 연속. **기수 대응코드 없음**(NCIC 실측 — `10기수1-02` 서브도메인 목록에 "복소수"
항목 자체가 없다. 기본수학1 교육과정은 복소수를 다루지 않는다) — 이 생성기는 단일
성취기준만 다루므로 `kind`가 성취기준 코드를 나누지 않고 밴드(연산 종류)만 가른다.

`kind`가 연산을 가르되 코드는 하나를 공유한다(measurement_unit_conversion·
radian_conversion 생성기의 "여러 kind가 한 코드 공유" 패턴 재사용):
- `add`·`sub`·`mul` → 모두 [10공수1-02-01].

**설계**: 두 가우스 정수 z1=a1+b1i·z2=a2+b2i(a1,b1,a2,b2 전부 0 아님 — "0+5i" 같은 실수부
생략형 표시를 피해 항상 "a + bi" 완전형으로 표시)에서 합/차/곱의 실수부 또는 허수부를
묻는다. 계수는 항상 입력 정수의 닫힌형 합성이라(덧셈: a1±a2·곱셈: (a1a2-b1b2)+(a1b2+a2b1)i
전개항) polynomial_arithmetic 생성기와 동일하게 SymPy `I` 자체는 불필요 — 조건식은 실수부·
허수부 각각의 순수 정수 산술식으로 공급한다(범용 sympify 검산기로 충분).

concept_src_id(legacy 437 개념그래프 `source_id` 필드 실측 확인 — 2026-08-08):
  HK05=[10공수1-02-01].

범위(v1 단순화): 나눗셈은 후속 — (a1+b1i)/(a2+b2i)는 일반적으로 가우스 유리수(분수 실수부·
허수부)가 되어 Fraction 처리가 필요하고, 검증 설계가 한 차원 더 복잡해진다(calculus1_
integral 생성기의 Fraction 선례를 재사용할 수 있으나 별도 스켈레톤으로 분리하는 편이
검증 추적이 쉽다).

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
    "COMPLEX_ARITHMETIC_STANDARD_CODE",
    "ComplexNumberArithmeticKind",
    "ComplexNumberArithmeticSkeletonGenerator",
]

_POOL_SEED = 20260810

COMPLEX_ARITHMETIC_STANDARD_CODE = "[10공수1-02-01]"
_CONCEPT_SRC_ID = "HK05"

ComplexNumberArithmeticKind = Literal["add", "sub", "mul"]

# 실수부·허수부 계수 범위 — 0 제외("0+5i" 같은 생략형 회피, 항상 "a + bi" 완전형 표시).
_COEFFICIENT_RANGE = tuple(v for v in range(-9, 10) if v != 0)
_TARGETS: tuple[str, ...] = ("real", "imag")


def _term(coefficient: int, symbol: str, *, lead: bool = False) -> str:
    """계수 하나를 사람이 읽는 항으로 — 부호·계수 1 생략 규칙(형제 생성기 독립 재구현·
    private 모듈 경계 비침범, 신규 규칙 발명 0)."""
    sign = "-" if coefficient < 0 else ("" if lead else "+")
    magnitude = abs(coefficient)
    body = symbol if magnitude == 1 and symbol else f"{magnitude}{symbol}"
    joint = " " if sign and not lead else ""
    return f"{sign}{joint}{body}" if lead else f"{sign} {body}"


def _complex_display(a: int, b: int) -> str:
    """복소수 표기('3 + 2i'·'-4 - i') — 이중부호 회피(polynomial_factoring 교훈 적용:
    _term의 부호 폴딩을 실수부·허수부 양쪽에 그대로 적용)."""
    real_part = _term(a, "", lead=True)
    imag_part = _term(b, "i")
    return f"{real_part} {imag_part}"


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """복소수 사칙연산 뼈대 — z1=a1+b1i·z2=a2+b2i·연산·묻는 부(실수부/허수부). 단일
    진실 원천."""

    kind: ComplexNumberArithmeticKind
    a1: int
    b1: int
    a2: int
    b2: int
    target: str  # "real" | "imag"

    @property
    def answer(self) -> int:
        """독립 재계산 — 덧셈/뺄셈은 대응 성분 합·차, 곱셈은 (a1+b1i)(a2+b2i) 전개
        (a1a2-b1b2) + (a1b2+a2b1)i의 실수부·허수부."""
        if self.kind == "add":
            return self.a1 + self.a2 if self.target == "real" else self.b1 + self.b2
        if self.kind == "sub":
            return self.a1 - self.a2 if self.target == "real" else self.b1 - self.b2
        # mul
        if self.target == "real":
            return self.a1 * self.a2 - self.b1 * self.b2
        return self.a1 * self.b2 + self.a2 * self.b1

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 실수부·허수부 공식을 순수 정수 산술식으로 그대로 공급
        (I 불요 — 복소수 연산의 실수부/허수부는 이미 실수 산술로 환원된 형태)."""
        if self.kind == "add":
            if self.target == "real":
                return f"({self.a1}) + ({self.a2}) = y"
            return f"({self.b1}) + ({self.b2}) = y"
        if self.kind == "sub":
            if self.target == "real":
                return f"({self.a1}) - ({self.a2}) = y"
            return f"({self.b1}) - ({self.b2}) = y"
        # mul
        if self.target == "real":
            return f"({self.a1})*({self.a2}) - ({self.b1})*({self.b2}) = y"
        return f"({self.a1})*({self.b2}) + ({self.a2})*({self.b1}) = y"

    @property
    def op_symbol(self) -> str:
        return {"add": "+", "sub": "-", "mul": "*"}[self.kind]

    @property
    def target_label(self) -> str:
        return "실수부" if self.target == "real" else "허수부"

    @property
    def difficulty(self) -> float:
        difficulty = 2.1 if self.kind != "mul" else 2.6
        if max(abs(self.a1), abs(self.b1), abs(self.a2), abs(self.b2)) >= 6:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_pool(kind: ComplexNumberArithmeticKind | None = None) -> tuple[_Skeleton, ...]:
    """결정론 뼈대 풀 — kind별 계수·목표부 시드 샘플링(조합공간 큼)·구조 키 자연 유일."""
    kinds: tuple[ComplexNumberArithmeticKind, ...] = (
        ("add", "sub", "mul") if kind is None else (kind,)
    )
    pool: list[_Skeleton] = []
    seen: set[tuple[object, ...]] = set()
    target_size = 300
    rng = random.Random(_POOL_SEED)
    for kd in kinds:
        attempts = 0
        added = 0
        while added < target_size and attempts < target_size * 30:
            attempts += 1
            a1 = rng.choice(_COEFFICIENT_RANGE)
            b1 = rng.choice(_COEFFICIENT_RANGE)
            a2 = rng.choice(_COEFFICIENT_RANGE)
            b2 = rng.choice(_COEFFICIENT_RANGE)
            target = rng.choice(_TARGETS)
            key = (kd, a1, b1, a2, b2, target)
            if key in seen:
                continue
            seen.add(key)
            pool.append(_Skeleton(kind=kd, a1=a1, b1=b1, a2=a2, b2=b2, target=target))
            added += 1
    rng.shuffle(pool)
    return tuple(pool)


_TEMPLATES: tuple[str, ...] = (
    "두 복소수 z1 = {z1}, z2 = {z2}에 대하여 z1 {op} z2의 {target}를 구하시오.",
)


def _explanation(skeleton: _Skeleton) -> str:
    """해설 — 실수부·허수부 계산을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    if skeleton.kind == "mul":
        return (
            "분배법칙으로 전개한 뒤 i^2 = -1을 대입해 실수부와 허수부를 각각 모으면 "
            f"구하는 {skeleton.target_label}는 {skeleton.answer} 이다."
        )
    op_word = "더하면" if skeleton.kind == "add" else "빼면"
    return f"두 복소수의 같은 부(실수부·허수부)끼리 {op_word} 구하는 값은 {skeleton.answer} 이다."


def _natural_answer_format(answer: int) -> AnswerFormat:
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


@deterministic_generator
class ComplexNumberArithmeticSkeletonGenerator:
    """복소수 사칙연산 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `kind` 필터로 밴드(연산 종류)를 분리한다. 단일 성취기준만 다루므로 코드는 항상
    고정이나(measurement_unit_conversion·radian_conversion 관례 계승), 필터 없이 밴드별
    인스턴스를 만들면 고정 시드 풀이 처음부터 재생돼 같은 뼈대를 중복 방출한다.
    """

    def __init__(
        self,
        *,
        kind: ComplexNumberArithmeticKind | None = None,
        slug_prefix: str = "wm-complexarith",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("COMPLEX-NUMBER-ARITHMETIC",),
    ) -> None:
        self._pool = _build_pool(kind)
        self._index = 0
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(skeleton)

    def _assemble(self, skeleton: _Skeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        z1_display = _complex_display(skeleton.a1, skeleton.b1)
        z2_display = _complex_display(skeleton.a2, skeleton.b2)
        template = _TEMPLATES[self._index % len(_TEMPLATES)]
        question_text = template.format(
            z1=z1_display, z2=z2_display, op=skeleton.op_symbol, target=skeleton.target_label
        )

        standard_codes = [COMPLEX_ARITHMETIC_STANDARD_CODE]
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
            answer_explanation=_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 복소수 사칙연산 스켈레톤 조립(성분→합/차/전개 실수부·허수부 공식 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=skeleton.condition,
            answer_map={"y": answer_text},
            answer_selection="unique",
            solution_steps=None,
            concept_tags=[
                ConceptTag(concept_src_id=_CONCEPT_SRC_ID, role="PRIMARY", relevance=0.95)
            ],
        )
