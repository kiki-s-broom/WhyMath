"""고등 다항식의 덧셈·뺄셈·곱셈 스켈레톤 생성기 — W2 Phase4 #3(결정론·LLM 0).

다항식 영역([10공수1-01-01]~[10기수1-01-03])이 세션 전체 1/6이었다(행렬 도메인과 혼재
집계된 이전 리포트 대비 재확인 — 다항식 자체는 0건). 이 생성기가 세 성취기준의 첫
코퍼스를 확보한다: [10공수1-01-01](다항식의 사칙연산)·[10기수1-01-01](다항식의 덧셈과
뺄셈)·[10기수1-01-02](다항식의 곱셈과 나눗셈).

`kind`가 성취기준 코드를 결정한다(measurement_unit_conversion 생성기의 "여러 kind가
한 코드 공유" 패턴 재사용):
- `gongsu_add`·`gongsu_sub` → [10공수1-01-01]("사칙연산의 원리" 중 덧셈·뺄셈 서브스코프 —
  **v1 단순화**: 곱셈도 사칙연산에 포함되나 이 코드는 덧셈·뺄셈만 다룬다. 원문이 "덧셈·뺄셈·
  곱셈·나눗셈"을 한 성취기준으로 뭉쳐 서술해 코드 단위 분리가 원천적으로 불가능 — 이
  코드의 첫 착점을 덧셈·뺄셈으로 잡고 곱셈·나눗셈 확장은 후속).
- `kisu_add`·`kisu_sub` → [10기수1-01-01](정확히 "덧셈과 뺄셈"만 서술 — 범위 완전 일치).
- `kisu_mul` → [10기수1-01-02]("곱셈과 나눗셈" 중 곱셈만 — **v1 단순화**: 나눗셈은 나머지
  개념이 필요해 별도 스켈레톤 설계가 필요, 후속).

**검증 설계**: 두 일차식 P(x)=a1x+b1·Q(x)=a2x+b2의 합/차/곱에서 특정 항의 계수를 묻는다.
계수는 항상 입력 정수의 닫힌형 합성이라(덧셈: a1±a2·곱셈: 배분법칙 전개항) **SymPy 전개조차
불요** — 조건식은 순수 정수 산술식이다(형제 생성기들과 동일한 "범용 sympify 검산기로
충분" 관례, 다만 이번엔 다항식 계수 공식을 생성기가 직접 계산해 공급).

concept_src_id(legacy 437 개념그래프 `source_id` 필드 실측 확인 — 2026-08-07):
  HK01=[10공수1-01-01] · 10기수1-01-01=[10기수1-01-01] · 10기수1-01-02=[10기수1-01-02].

범위(v1): 일차식×일차식(곱셈 결과는 이차식)만. 나눗셈(나머지 개념)·인수분해([10공수1-01-03]·
[10기수1-01-03])는 후속.

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
    "GONGSU_STANDARD_CODE",
    "KISU_ADDSUB_STANDARD_CODE",
    "KISU_MUL_STANDARD_CODE",
    "PolynomialArithmeticKind",
    "PolynomialArithmeticSkeletonGenerator",
]

_POOL_SEED = 20260808

GONGSU_STANDARD_CODE = "[10공수1-01-01]"
KISU_ADDSUB_STANDARD_CODE = "[10기수1-01-01]"
KISU_MUL_STANDARD_CODE = "[10기수1-01-02]"

PolynomialArithmeticKind = Literal["gongsu_add", "gongsu_sub", "kisu_add", "kisu_sub", "kisu_mul"]

_KIND_INFO: dict[PolynomialArithmeticKind, tuple[str, str]] = {
    # kind → (성취기준 코드, concept_src_id).
    "gongsu_add": (GONGSU_STANDARD_CODE, "HK01"),
    "gongsu_sub": (GONGSU_STANDARD_CODE, "HK01"),
    "kisu_add": (KISU_ADDSUB_STANDARD_CODE, "10기수1-01-01"),
    "kisu_sub": (KISU_ADDSUB_STANDARD_CODE, "10기수1-01-01"),
    "kisu_mul": (KISU_MUL_STANDARD_CODE, "10기수1-01-02"),
}
_ADD_SUB_KINDS: frozenset[PolynomialArithmeticKind] = frozenset(
    {"gongsu_add", "gongsu_sub", "kisu_add", "kisu_sub"}
)

_A_RANGE = tuple(v for v in range(-6, 7) if v != 0)  # 일차항 계수(0이면 상수식이 됨 — 제외).
_B_RANGE = tuple(range(-8, 9))
_ADD_SUB_TARGETS: tuple[str, ...] = ("x", "const")
_MUL_TARGETS: tuple[str, ...] = ("x2", "x1", "const")


def _term(coefficient: int, symbol: str, *, lead: bool = False) -> str:
    """계수 하나를 사람이 읽는 항으로 — 부호·계수 1 생략 규칙(형제 생성기 독립 재구현·
    private 모듈 경계 비침범, 신규 규칙 발명 0)."""
    sign = "-" if coefficient < 0 else ("" if lead else "+")
    magnitude = abs(coefficient)
    body = symbol if magnitude == 1 and symbol else f"{magnitude}{symbol}"
    joint = " " if sign and not lead else ""
    return f"{sign}{joint}{body}" if lead else f"{sign} {body}"


def _linear_display(a: int, b: int) -> str:
    """일차식 표기('3x - 7') — 계수 1 생략."""
    parts = [_term(a, "x", lead=True)]
    if b:
        parts.append(_term(b, ""))
    return " ".join(parts)


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """다항식 사칙연산 뼈대 — P(x)=a1x+b1·Q(x)=a2x+b2·연산·묻는 항. 단일 진실 원천."""

    kind: PolynomialArithmeticKind
    a1: int
    b1: int
    a2: int
    b2: int
    target: str  # add/sub: "x"/"const". mul: "x2"/"x1"/"const".

    @property
    def is_add_sub(self) -> bool:
        return self.kind in _ADD_SUB_KINDS

    @property
    def op_symbol(self) -> str:
        return "+" if self.kind in ("gongsu_add", "kisu_add") else "-"

    @property
    def answer(self) -> int:
        """독립 재계산 — 덧셈/뺄셈은 대응 계수 합·차, 곱셈은 배분법칙 전개 계수(생성기
        자체 검산·SymPy 전개와 별개 경로)."""
        if self.is_add_sub:
            sign = 1 if self.op_symbol == "+" else -1
            if self.target == "x":
                return self.a1 + sign * self.a2
            return self.b1 + sign * self.b2
        # kisu_mul: (a1 x + b1)(a2 x + b2) = a1a2 x^2 + (a1 b2 + a2 b1) x + b1 b2.
        if self.target == "x2":
            return self.a1 * self.a2
        if self.target == "x1":
            return self.a1 * self.b2 + self.a2 * self.b1
        return self.b1 * self.b2

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 계수 공식을 정수 산술식으로 그대로 공급."""
        if self.is_add_sub:
            sign = "+" if self.op_symbol == "+" else "-"
            if self.target == "x":
                return f"({self.a1}) {sign} ({self.a2}) = y"
            return f"({self.b1}) {sign} ({self.b2}) = y"
        if self.target == "x2":
            return f"({self.a1}) * ({self.a2}) = y"
        if self.target == "x1":
            return f"({self.a1})*({self.b2}) + ({self.a2})*({self.b1}) = y"
        return f"({self.b1}) * ({self.b2}) = y"

    @property
    def target_label(self) -> str:
        return {"x2": "x^2", "x1": "x", "x": "x", "const": "상수"}[self.target]

    @property
    def difficulty(self) -> float:
        difficulty = 1.8 if self.is_add_sub else 2.4
        if max(abs(self.a1), abs(self.a2)) >= 4:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_pool(kind: PolynomialArithmeticKind | None = None) -> tuple[_Skeleton, ...]:
    """결정론 뼈대 풀 — kind별 계수·목표항 시드 샘플링(조합공간 큼)·구조 키 자연 유일."""
    kinds: tuple[PolynomialArithmeticKind, ...] = (
        ("gongsu_add", "gongsu_sub", "kisu_add", "kisu_sub", "kisu_mul")
        if kind is None
        else (kind,)
    )
    pool: list[_Skeleton] = []
    seen: set[tuple[object, ...]] = set()
    target_size = 300
    rng = random.Random(_POOL_SEED)
    for kd in kinds:
        targets = _ADD_SUB_TARGETS if kd in _ADD_SUB_KINDS else _MUL_TARGETS
        attempts = 0
        added = 0
        while added < target_size and attempts < target_size * 30:
            attempts += 1
            a1 = rng.choice(_A_RANGE)
            b1 = rng.choice(_B_RANGE)
            a2 = rng.choice(_A_RANGE)
            b2 = rng.choice(_B_RANGE)
            target = rng.choice(targets)
            key = (kd, a1, b1, a2, b2, target)
            if key in seen:
                continue
            seen.add(key)
            pool.append(_Skeleton(kind=kd, a1=a1, b1=b1, a2=a2, b2=b2, target=target))
            added += 1
    rng.shuffle(pool)
    return tuple(pool)


_ADD_TEMPLATES: tuple[str, ...] = (
    "두 다항식 P(x) = {p}, Q(x) = {q}에 대하여 P(x) + Q(x)에서 {target}의 계수를 " "구하시오.",
)
_SUB_TEMPLATES: tuple[str, ...] = (
    "두 다항식 P(x) = {p}, Q(x) = {q}에 대하여 P(x) - Q(x)에서 {target}의 계수를 " "구하시오.",
)
_MUL_TEMPLATES: tuple[str, ...] = (
    "두 다항식 P(x) = {p}, Q(x) = {q}에 대하여 P(x) * Q(x)를 전개했을 때 {target}의 "
    "계수를 구하시오.",
)


def _explanation(skeleton: _Skeleton) -> str:
    """해설 — 계수 합성 계산을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    answer_text = str(skeleton.answer)
    if skeleton.is_add_sub:
        op_word = "더하면" if skeleton.op_symbol == "+" else "빼면"
        return f"같은 차수의 항끼리 계수를 {op_word} 구하는 값은 {answer_text} 이다."
    return "분배법칙으로 전개한 뒤 같은 차수끼리 모으면 구하는 계수는 " f"{answer_text} 이다."


def _natural_answer_format(answer: int) -> AnswerFormat:
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


@deterministic_generator
class PolynomialArithmeticSkeletonGenerator:
    """다항식 사칙연산 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `kind` 필터로 밴드를 분리하고 성취기준 코드도 함께 결정한다(형제 생성기들의
    "kind→코드" 관례 계승 — 필터 없이 밴드별 인스턴스를 만들면 고정 시드 풀이 처음부터
    재생돼 같은 뼈대를 중복 방출한다).
    """

    def __init__(
        self,
        *,
        kind: PolynomialArithmeticKind | None = None,
        slug_prefix: str = "wm-polyarith",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("POLYNOMIAL-ARITHMETIC",),
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
        p_display = _linear_display(skeleton.a1, skeleton.b1)
        q_display = _linear_display(skeleton.a2, skeleton.b2)
        if skeleton.kind in ("gongsu_add", "kisu_add"):
            template = _ADD_TEMPLATES[self._index % len(_ADD_TEMPLATES)]
        elif skeleton.kind in ("gongsu_sub", "kisu_sub"):
            template = _SUB_TEMPLATES[self._index % len(_SUB_TEMPLATES)]
        else:
            template = _MUL_TEMPLATES[self._index % len(_MUL_TEMPLATES)]
        question_text = template.format(p=p_display, q=q_display, target=skeleton.target_label)

        standard_code, concept_src_id = _KIND_INFO[skeleton.kind]
        standard_codes = [standard_code]
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
                    "결정론 다항식 사칙연산 스켈레톤 조립(계수→합/차/전개 계수 공식 계산)",
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
                ConceptTag(concept_src_id=concept_src_id, role="PRIMARY", relevance=0.95)
            ],
        )
