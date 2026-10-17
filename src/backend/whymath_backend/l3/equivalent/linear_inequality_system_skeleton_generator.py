"""고등 연립일차부등식(미지수 1개) 스켈레톤 생성기 — W2 Phase4 #7(결정론·LLM 0).

`PolynomialFactoringSkeletonGenerator`(S4-48)의 형제 설계 — S4-47/S4-48/S4-49/S4-50
다항식·호도법·복소수 웨이브의 연속. 두 성취기준 모두 "미지수가 1개인 연립일차부등식을
풀 수 있다."는 동일 문장(NCIC 실측, 2026-08-10):
  - `[10공수1-02-09]`(공통수학1)
  - `[10기수1-02-07]`(기본수학1)

`kind`가 성취기준 코드를 결정한다(1 kind = 1 코드 — calculus1/calculus2 적분·
polynomial_factoring 생성기의 1:1 패턴과 동형):
- `gongsu_sysineq` → [10공수1-02-09].
- `kisu_sysineq` → [10기수1-02-07].

**설계**: 해 구간의 두 경계값 p<q를 먼저 고른 뒤 두 일차부등식을 *역합성*한다 — 하한
부등식 `a1*x + b1 > 0`(a1>0이라 x>p로 정확히 풀림, b1=-a1*p)과 상한 부등식
`a2*x + b2 < 0`(a2>0이라 x<q로 정확히 풀림, b2=-a2*q)을 연립하면 해가 정확히 p<x<q가
된다 — 구성 자체가 연립부등식의 해 구간 정합성을 보장한다(polynomial_factoring의
"인수 먼저 선택→다항식 역합성" 설계와 동형 논리). 학생에게 묻는 값(두 경계값 중 큰 값/
작은 값)은 계수만 봐서는 바로 읽을 수 없어(각 부등식을 실제로 풀어야 함) 진짜 연립부등식
풀이 능력을 겨눈다. Tier1 조건식은 "그 경계값이 실제로 대응 부등식의 등식 경계를 만족하는가"
(`a*y + b = 0`)로 공급해 역합성 로직 자체의 버그도 잡아낸다.

**v1 단순화**: 계수 a1·a2는 항상 양수로 고정(음수 계수로 나눌 때의 부등호 방향 반전은
후속 — 이 세션의 반복되는 "부호 반전은 후속" 관례와 동형, 예: polynomial_arithmetic의
나눗셈 제외). 전부 강한 부등식(>·<)만 다룬다(경계 포함 여부 혼재는 후속).

concept_src_id(legacy 437 개념그래프 `source_id` 필드 실측 확인 — 2026-08-10):
  HK14=[10공수1-02-09] · 10기수1-02-07=[10기수1-02-07].

범위(v1): quad_ineq_v0([10공수1-02-11] 이차부등식)와 다른 코드 — 겹치지 않음.

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
    "GONGSU_SYSINEQ_STANDARD_CODE",
    "KISU_SYSINEQ_STANDARD_CODE",
    "LinearInequalitySystemKind",
    "LinearInequalitySystemSkeletonGenerator",
]

_POOL_SEED = 20260810

GONGSU_SYSINEQ_STANDARD_CODE = "[10공수1-02-09]"
KISU_SYSINEQ_STANDARD_CODE = "[10기수1-02-07]"

LinearInequalitySystemKind = Literal["gongsu_sysineq", "kisu_sysineq"]

_KIND_INFO: dict[LinearInequalitySystemKind, tuple[str, str]] = {
    # kind → (성취기준 코드, concept_src_id).
    "gongsu_sysineq": (GONGSU_SYSINEQ_STANDARD_CODE, "HK14"),
    "kisu_sysineq": (KISU_SYSINEQ_STANDARD_CODE, "10기수1-02-07"),
}

# 경계값 범위(0 포함 — 해 구간이 0을 지나는 경우도 정상) · 계수 범위(0 제외, 항상 양수).
_BOUNDARY_RANGE = tuple(range(-10, 11))
_COEFFICIENT_RANGE = tuple(range(1, 7))
_TARGETS: tuple[str, ...] = ("larger", "smaller")


def _term(coefficient: int, symbol: str, *, lead: bool = False) -> str:
    """계수 하나를 사람이 읽는 항으로 — 부호·계수 1 생략 규칙(형제 생성기 독립 재구현·
    private 모듈 경계 비침범, 신규 규칙 발명 0)."""
    sign = "-" if coefficient < 0 else ("" if lead else "+")
    magnitude = abs(coefficient)
    body = symbol if magnitude == 1 and symbol else f"{magnitude}{symbol}"
    joint = " " if sign and not lead else ""
    return f"{sign}{joint}{body}" if lead else f"{sign} {body}"


def _inequality_display(a: int, b: int, op: str) -> str:
    """부등식 표기('3x - 7 > 0') — 계수 1 생략·이중부호 회피(_term 재사용)."""
    parts = [_term(a, "x", lead=True)]
    if b:
        parts.append(_term(b, ""))
    return " ".join(parts) + f" {op} 0"


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """연립일차부등식 뼈대 — 경계값 larger>smaller(해 구간의 두 끝)에서 역합성한 두
    부등식(a1x+b1>0 → x>smaller · a2x+b2<0 → x<larger). 단일 진실 원천 — b1,b2는 항상
    -a*경계값으로 *정의*되므로 해 구간 정합성이 구성만으로 보장된다."""

    kind: LinearInequalitySystemKind
    larger: int
    smaller: int
    a1: int  # x > smaller 부등식의 계수(양수).
    a2: int  # x < larger 부등식의 계수(양수).
    target: str  # "larger" | "smaller".

    @property
    def b1(self) -> int:
        return -self.a1 * self.smaller

    @property
    def b2(self) -> int:
        return -self.a2 * self.larger

    @property
    def answer(self) -> int:
        return self.larger if self.target == "larger" else self.smaller

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 경계 부등식의 등식 경계(a*y+b=0)로 답을 재확인(역합성
        로직 자체의 버그 포착 — 단순 자기복제 등식이 아님)."""
        if self.target == "larger":
            return f"({self.a2})*y + ({self.b2}) = 0"
        return f"({self.a1})*y + ({self.b1}) = 0"

    @property
    def target_label(self) -> str:
        return "두 경계값 중 더 큰 값" if self.target == "larger" else "두 경계값 중 더 작은 값"

    @property
    def difficulty(self) -> float:
        difficulty = 2.3
        if max(abs(self.larger), abs(self.smaller)) >= 7:
            difficulty += 0.2
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_pool(
    kind: LinearInequalitySystemKind | None = None,
) -> tuple[_Skeleton, ...]:
    """결정론 뼈대 풀 — kind별 (larger,smaller,a1,a2,target) 시드 샘플링(조합공간 큼)·
    구조 키 자연 유일."""
    kinds: tuple[LinearInequalitySystemKind, ...] = (
        ("gongsu_sysineq", "kisu_sysineq") if kind is None else (kind,)
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
            p = rng.choice(_BOUNDARY_RANGE)
            q = rng.choice(_BOUNDARY_RANGE)
            if p == q:
                continue
            larger, smaller = (p, q) if p > q else (q, p)
            a1 = rng.choice(_COEFFICIENT_RANGE)
            a2 = rng.choice(_COEFFICIENT_RANGE)
            target = rng.choice(_TARGETS)
            key = (kd, larger, smaller, a1, a2, target)
            if key in seen:
                continue
            seen.add(key)
            pool.append(
                _Skeleton(kind=kd, larger=larger, smaller=smaller, a1=a1, a2=a2, target=target)
            )
            added += 1
    rng.shuffle(pool)
    return tuple(pool)


_TEMPLATES: tuple[str, ...] = (
    "다음 연립부등식을 만족하는 x의 값의 범위에서 {target}을 구하시오: " "{ineq1}, {ineq2}",
)


def _explanation(skeleton: _Skeleton) -> str:
    """해설 — 두 부등식을 각각 풀어 연립한 과정을 자연어로 서술(결정론·위생 청정)."""
    return (
        f"첫째 부등식을 풀면 x > {skeleton.smaller}, 둘째 부등식을 풀면 x < "
        f"{skeleton.larger}이므로 두 조건을 모두 만족하는 범위는 {skeleton.smaller} < x < "
        f"{skeleton.larger}이고, 구하는 값은 {skeleton.answer} 이다."
    )


def _natural_answer_format(answer: int) -> AnswerFormat:
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


@deterministic_generator
class LinearInequalitySystemSkeletonGenerator:
    """연립일차부등식(미지수 1개) 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator`
    좌석(LLM 0).

    `kind` 필터로 밴드를 분리하고 성취기준 코드도 함께 결정한다(형제 생성기들의
    "kind→코드" 관례 계승 — 필터 없이 밴드별 인스턴스를 만들면 고정 시드 풀이 처음부터
    재생돼 같은 뼈대를 중복 방출한다).
    """

    def __init__(
        self,
        *,
        kind: LinearInequalitySystemKind | None = None,
        slug_prefix: str = "wm-sysineq",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("LINEAR-INEQUALITY-SYSTEM",),
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
        ineq1 = _inequality_display(skeleton.a1, skeleton.b1, ">")
        ineq2 = _inequality_display(skeleton.a2, skeleton.b2, "<")
        template = _TEMPLATES[self._index % len(_TEMPLATES)]
        question_text = template.format(ineq1=ineq1, ineq2=ineq2, target=skeleton.target_label)

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
                    "결정론 연립일차부등식 스켈레톤 조립(경계값 선택→부등식 역합성)",
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
