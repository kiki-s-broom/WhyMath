"""고등 다항식의 인수분해(이차식 트리노미얼) 스켈레톤 생성기 — W2 Phase4 #4(결정론·LLM 0).

`polynomial_arithmetic_skeleton_generator`(S4-47)의 형제·후속 — 그 모듈 docstring이 이미
"범위(v1) ... 인수분해([10공수1-01-03]·[10기수1-01-03])는 후속"이라 명시해 둔 항목을
착수한다. 두 성취기준 모두 "다항식" 대단원의 "인수분해" 소단원이다(NCIC 실측, 2026-08-08):
  - `[10공수1-01-03]` "다항식의 인수분해를 할 수 있다."
  - `[10기수1-01-03]` "인수분해 공식을 이용하여 다항식의 인수분해를 할 수 있다."

`kind`가 성취기준 코드를 결정한다(형제 생성기들의 "kind→코드" 관례 계승 — 이번엔 1 kind =
1 코드로 measurement_unit_conversion류의 "여러 kind가 한 코드 공유" 패턴은 해당 없음,
calculus1/calculus2 적분 생성기의 1:1 패턴과 동형):
- `gongsu_factor` → [10공수1-01-03].
- `kisu_factor` → [10기수1-01-03].

**설계**: 서로 다른 두 정수 인수 p>q(둘 다 0이 아님)를 먼저 고른 뒤 이차식 x^2+bx+c
(b=p+q, c=pq)를 *역으로 합성*한다 — 다항식→인수분해가 아니라 인수→다항식 합성이라
"이 b,c가 실제로 (x+p)(x+q)로 인수분해되는가"를 SymPy로 재확인할 필요가 없다(구성 자체가
그 사실을 보장 — polynomial_arithmetic의 "P(x),Q(x)를 독립 구성 후 연산" 설계와 동형 논리).
학생에게 묻는 값(두 인수의 상수항 중 큰 값/작은 값)은 b·c만으로는 바로 읽을 수 없어(실제
인수분해가 필요) 진짜 인수분해 능력을 겨눈다. Tier1 조건식은 "다른 한 인수 + y = b" 형태로
공급해 답이 두 인수 합 항등식을 만족하는지 재검산한다(SymPy 전개 불요 — 순수 정수 산술).

concept_src_id(legacy 437 개념그래프 `source_id` 필드 실측 확인 — 2026-08-08):
  HK04=[10공수1-01-03] · 10기수1-01-03=[10기수1-01-03].

범위(v1 단순화): 모닉(monic, 이차항 계수 1) 트리노미얼 x^2+bx+c만 — 이차항 계수가 1이 아닌
경우(`ax^2+bx+c`, a≠1)는 인수 분배가 한 차원 더 필요해 후속. 공통인수 추출형(c=0, 예
`x^2+3x=x(x+3)`)·완전제곱식(p=q)도 다른 서술이 필요해 범위 밖 — 두 인수가 서로 다른
정수인 일반형만 다룬다.

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
    "GONGSU_FACTOR_STANDARD_CODE",
    "KISU_FACTOR_STANDARD_CODE",
    "PolynomialFactoringKind",
    "PolynomialFactoringSkeletonGenerator",
]

_POOL_SEED = 20260809

GONGSU_FACTOR_STANDARD_CODE = "[10공수1-01-03]"
KISU_FACTOR_STANDARD_CODE = "[10기수1-01-03]"

PolynomialFactoringKind = Literal["gongsu_factor", "kisu_factor"]

_KIND_INFO: dict[PolynomialFactoringKind, tuple[str, str]] = {
    # kind → (성취기준 코드, concept_src_id).
    "gongsu_factor": (GONGSU_FACTOR_STANDARD_CODE, "HK04"),
    "kisu_factor": (KISU_FACTOR_STANDARD_CODE, "10기수1-01-03"),
}

# 인수 범위(0 제외 — 공통인수 추출형은 범위 밖). |p|,|q| ≤ 10, p≠q로 서로 다른 두 인수 보장.
_FACTOR_RANGE = tuple(v for v in range(-10, 11) if v != 0)
_TARGETS: tuple[str, ...] = ("larger", "smaller")


def _term(coefficient: int, symbol: str, *, lead: bool = False) -> str:
    """계수 하나를 사람이 읽는 항으로 — 부호·계수 1 생략 규칙(형제 생성기 독립 재구현·
    private 모듈 경계 비침범, 신규 규칙 발명 0)."""
    sign = "-" if coefficient < 0 else ("" if lead else "+")
    magnitude = abs(coefficient)
    body = symbol if magnitude == 1 and symbol else f"{magnitude}{symbol}"
    joint = " " if sign and not lead else ""
    return f"{sign}{joint}{body}" if lead else f"{sign} {body}"


def _trinomial_display(b: int, c: int) -> str:
    """모닉 이차식 표기('x^2 + 5x - 6') — b=0이면 x항 생략(차수 유지 표기는 x^2로 충분)."""
    parts = ["x^2"]
    if b:
        parts.append(_term(b, "x"))
    parts.append(_term(c, ""))
    return " ".join(parts)


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """인수분해 뼈대 — 두 인수 larger>smaller(둘 다 0 아님)에서 역합성한 x^2+bx+c. 단일
    진실 원천 — b,c는 항상 larger+smaller·larger*smaller로 *정의*되므로 인수분해 정합성이
    구성만으로 보장된다(별도 SymPy 재확인 불요)."""

    kind: PolynomialFactoringKind
    larger: int
    smaller: int
    target: str  # "larger" | "smaller" — 묻는 인수의 상수항.

    @property
    def b(self) -> int:
        return self.larger + self.smaller

    @property
    def c(self) -> int:
        return self.larger * self.smaller

    @property
    def answer(self) -> int:
        return self.larger if self.target == "larger" else self.smaller

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — '다른 한 인수 + y = b' 항등식(순수 정수 산술, 전개 불요)."""
        other = self.smaller if self.target == "larger" else self.larger
        return f"y + ({other}) = ({self.b})"

    @property
    def target_label(self) -> str:
        if self.target == "larger":
            return "두 인수의 상수항 중 더 큰 값"
        return "두 인수의 상수항 중 더 작은 값"

    @property
    def difficulty(self) -> float:
        difficulty = 2.2
        if max(abs(self.larger), abs(self.smaller)) >= 7:
            difficulty += 0.2
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_pool(kind: PolynomialFactoringKind | None = None) -> tuple[_Skeleton, ...]:
    """결정론 뼈대 풀 — kind별 (larger,smaller,target) 시드 샘플링(조합공간 큼)·구조 키
    자연 유일."""
    kinds: tuple[PolynomialFactoringKind, ...] = (
        ("gongsu_factor", "kisu_factor") if kind is None else (kind,)
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
            p = rng.choice(_FACTOR_RANGE)
            q = rng.choice(_FACTOR_RANGE)
            if p == q:
                continue
            larger, smaller = (p, q) if p > q else (q, p)
            target = rng.choice(_TARGETS)
            key = (kd, larger, smaller, target)
            if key in seen:
                continue
            seen.add(key)
            pool.append(_Skeleton(kind=kd, larger=larger, smaller=smaller, target=target))
            added += 1
    rng.shuffle(pool)
    return tuple(pool)


_FACTOR_TEMPLATES: tuple[str, ...] = (
    "이차식 {trinomial}를 인수분해하면 (x + p)(x + q)(p > q) 꼴이다. {target}을 구하시오.",
)


def _factor_group(value: int) -> str:
    """인수 하나를 '(x + 5)'/'(x - 5)' 괄호식으로 — 이중부호('x + -5') 회피."""
    return f"(x - {abs(value)})" if value < 0 else f"(x + {value})"


def _explanation(skeleton: _Skeleton) -> str:
    """해설 — 인수분해 결과를 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    return (
        f"두 정수 {skeleton.larger}, {skeleton.smaller}는 합이 x의 계수, 곱이 상수항과 "
        f"같으므로 {_factor_group(skeleton.larger)}{_factor_group(skeleton.smaller)}로 "
        f"인수분해되고, 구하는 값은 {skeleton.answer} 이다."
    )


def _natural_answer_format(answer: int) -> AnswerFormat:
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


@deterministic_generator
class PolynomialFactoringSkeletonGenerator:
    """모닉 이차식 인수분해 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `kind` 필터로 밴드를 분리하고 성취기준 코드도 함께 결정한다(형제 생성기들의
    "kind→코드" 관례 계승 — 필터 없이 밴드별 인스턴스를 만들면 고정 시드 풀이 처음부터
    재생돼 같은 뼈대를 중복 방출한다).
    """

    def __init__(
        self,
        *,
        kind: PolynomialFactoringKind | None = None,
        slug_prefix: str = "wm-polyfactor",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("POLYNOMIAL-FACTORING",),
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
        trinomial = _trinomial_display(skeleton.b, skeleton.c)
        template = _FACTOR_TEMPLATES[self._index % len(_FACTOR_TEMPLATES)]
        question_text = template.format(trinomial=trinomial, target=skeleton.target_label)

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
                    "결정론 인수분해 스켈레톤 조립(인수 선택→이차식 역합성)",
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
