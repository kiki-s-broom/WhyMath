"""고등 미적분Ⅰ 적분 — 부정적분·정적분·넓이·속도와 거리 스켈레톤 생성기 — W2 Phase4 #1
(결정론·LLM 0).

적분 영역([12미적Ⅰ-03-01]~[12미적Ⅰ-03-06])이 세션 전체 0/6이었다 — 이 생성기가 4개
성취기준의 첫 코퍼스를 확보한다(나머지 2개는 정의역 서술형 — 모듈 docstring 후단 참조).

`kind`가 성취기준 코드를 결정한다(gcd_lcm·conic_section_focus·measurement_unit_conversion
생성기의 "kind→코드" 패턴 재사용):
- `antiderivative`([12미적Ⅰ-03-02]) — 다항함수 f(x)의 부정적분 중 F(0)=k인 F(x)에 대해
  F(m)의 값. F(m) = k + ∫[0,m] f(x)dx(부정적분 그 자체를 직접 다루지 않고 **정적분으로
  환원**해 검증 — 부정적분은 적분상수가 임의라 단독으로는 수치 검증 대상이 아니다).
- `definite`([12미적Ⅰ-03-04]) — 다항함수의 정적분 ∫[a,b] f(x)dx의 값.
- `area`([12미적Ⅰ-03-05]) — 곡선과 x축·두 수직선으로 둘러싸인 도형의 넓이.
- `distance`([12미적Ⅰ-03-06]) — 속도함수 v(t)로부터 구간 이동 거리.

**검증 설계(핵심 신규 발견 — 2026-08-07)**: Tier1(`l3/verify_answer`)이 SymPy
`Integral(expr, (x, a, b))`을 조건식에 그대로 공급하면 수치 정적분을 정확히 재계산해
pass/fail을 가른다(스파이크 실측 확인 — 다항식·삼각함수·지수함수 전부). 부정적분(`antiderivative`)
은 위 `F(m)=k+∫[0,m]f` 항등식으로 환원해 같은 정적분 검증 경로를 재사용한다(신규 검증기
0 — 형제 생성기들의 "범용 sympify 검산기로 충분" 관례 계승, 이번엔 `Integral` 함수 지원
확장이 핵심).

`area`·`distance` kind는 **v1 단순화**로 이차항 계수 a≥1·상수항 c≥1·일차항 b=0을 강제한다
— f(x)=a·x²+c(a,c>0)는 구간 전체에서 항상 양수이므로 부호분석(절댓값 적분) 없이 "넓이=
정적분값"·"거리=정적분값"이 그대로 성립한다(형제 생성기들의 "범위(v1)" 제약 관례 계승 —
부호가 바뀌는 속도함수·아래로 볼록하지 않은 곡선은 후속).

Tier2(`solution_steps`)는 이 생성기에서 쓰지 않는다(`None`) — `Integral` 표현식 체인을
`verify_step`의 심볼릭 동치 판정에 넣는 것은 미검증 경로라 형제 생성기들의 선례(확률
법칙·표본평균 생성기 등)를 따라 Tier1 단독으로 충분히 검증한다.

concept_src_id(legacy 437 개념그래프 `source_id` 필드 실측 확인 — 2026-08-07):
  H:12미적Ⅰ03-02=[12미적Ⅰ-03-02] · H:12미적Ⅰ03-04=[12미적Ⅰ-03-04] ·
  H:12미적Ⅰ03-05=[12미적Ⅰ-03-05] · H:12미적Ⅰ03-06=[12미적Ⅰ-03-06].

범위 밖(이 생성기가 다루지 않는 나머지 2개 성취기준): [12미적Ⅰ-03-01](부정적분의 뜻 —
"설명할 수 있다" 정의역 서술형, 수치화 왜곡 위험) · [12미적Ⅰ-03-03](정적분의 개념 —
"탐구하고 이해한다" 개념 서술형). 둘 다 C급(수치 검산으로 환원 불가) — 이 세션 파이프라인
범위 밖.

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지·L1(ConceptTag)만 import(L4
참조 0). 난이도는 지역 함수(공유 difficulty.py 불침범·도메인 분담 관례 계승).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
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
    "ANTIDERIVATIVE_STANDARD_CODE",
    "AREA_STANDARD_CODE",
    "Calculus1IntegralKind",
    "Calculus1IntegralSkeletonGenerator",
    "DEFINITE_STANDARD_CODE",
    "DISTANCE_STANDARD_CODE",
]

_POOL_SEED = 20260807

ANTIDERIVATIVE_STANDARD_CODE = "[12미적Ⅰ-03-02]"
DEFINITE_STANDARD_CODE = "[12미적Ⅰ-03-04]"
AREA_STANDARD_CODE = "[12미적Ⅰ-03-05]"
DISTANCE_STANDARD_CODE = "[12미적Ⅰ-03-06]"

Calculus1IntegralKind = Literal["antiderivative", "definite", "area", "distance"]

_KIND_INFO: dict[Calculus1IntegralKind, tuple[str, str]] = {
    # kind → (성취기준 코드, concept_src_id).
    "antiderivative": (ANTIDERIVATIVE_STANDARD_CODE, "H:12미적Ⅰ03-02"),
    "definite": (DEFINITE_STANDARD_CODE, "H:12미적Ⅰ03-04"),
    "area": (AREA_STANDARD_CODE, "H:12미적Ⅰ03-05"),
    "distance": (DISTANCE_STANDARD_CODE, "H:12미적Ⅰ03-06"),
}

_A_RANGE = tuple(v for v in range(-4, 5) if v != 0)
_BC_RANGE = tuple(range(-5, 6))
_BOUND_RANGE = tuple(range(-4, 5))
_K_RANGE = tuple(range(-10, 11))
# area/distance kind 전용(v1 단순화 — a,c>0·b=0으로 구간 전체 양수 강제).
_POSITIVE_A_RANGE = tuple(range(1, 5))
_POSITIVE_C_RANGE = tuple(range(1, 6))
_POSITIVE_BOUND_RANGE = tuple(range(0, 6))


def _term(coefficient: int, symbol: str, *, lead: bool = False) -> str:
    """계수 하나를 사람이 읽는 항으로 — 부호·계수 1 생략 규칙(형제 생성기 독립 재구현·
    private 모듈 경계 비침범, 신규 규칙 발명 0)."""
    sign = "-" if coefficient < 0 else ("" if lead else "+")
    magnitude = abs(coefficient)
    body = symbol if magnitude == 1 and symbol else f"{magnitude}{symbol}"
    joint = " " if sign and not lead else ""
    return f"{sign}{joint}{body}" if lead else f"{sign} {body}"


def _quad_display(a: int, b: int, c: int, *, var: str = "x") -> str:
    """이차식 표기('3x^2 - 7x + 4') — 0항 생략·계수 1 생략."""
    parts = [_term(a, f"{var}^2", lead=True)]
    if b:
        parts.append(_term(b, var))
    if c:
        parts.append(_term(c, ""))
    return " ".join(parts) if parts else "0"


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """정적분 뼈대 — f(x)=a·x²+b·x+c·구간[lower,upper]·(antiderivative 전용) 초기값 k.
    단일 진실 원천. area/distance는 b=0으로 생성돼 f(x)>0이 구간 전체에서 보장된다.
    """

    kind: Calculus1IntegralKind
    a: int
    b: int
    c: int
    lower: int
    upper: int
    k: int = 0  # antiderivative 전용(F(0)=k). 그 외 kind는 미사용(0 고정).

    @property
    def poly_str(self) -> str:
        """SymPy 파싱용 다항식 문자열 — `_quad_display`와 별개(캐럿 지수·공백 없는 형태)."""
        return f"{self.a}*x**2 + {self.b}*x + {self.c}"

    @property
    def answer(self) -> Fraction:
        """독립 재계산(정적분 닫힌형 반도함수 F(x)=a/3·x³+b/2·x²+c·x 대입) — 생성기 자체
        검산. antiderivative는 k를 더한다. 계수·구간에 따라 기약분수가 될 수 있다(예:
        b가 홀수면 b/2·x² 항이 정수로 안 떨어짐)."""

        def antideriv(x: int) -> Fraction:
            return Fraction(self.a, 3) * x**3 + Fraction(self.b, 2) * x**2 + Fraction(self.c) * x

        base = antideriv(self.upper) - antideriv(self.lower)
        return base + (self.k if self.kind == "antiderivative" else 0)

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'Integral(f, (x, lower, upper)) [+ k] = y'."""
        integral = f"Integral({self.poly_str}, (x, {self.lower}, {self.upper}))"
        if self.kind == "antiderivative":
            return f"{integral} + {self.k} = y"
        return f"{integral} = y"

    @property
    def difficulty(self) -> float:
        difficulty = {"antiderivative": 3.3, "definite": 3.0, "area": 3.1, "distance": 3.2}[
            self.kind
        ]
        if abs(self.a) >= 3:
            difficulty += 0.1
        if self.upper - self.lower >= 4:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_pool(kind: Calculus1IntegralKind | None = None) -> tuple[_Skeleton, ...]:
    """결정론 뼈대 풀 — kind별 계수·구간 열거(시드 샘플링, 조합공간 큼)·구조 키 자연 유일."""
    kinds: tuple[Calculus1IntegralKind, ...] = (
        ("antiderivative", "definite", "area", "distance") if kind is None else (kind,)
    )
    pool: list[_Skeleton] = []
    seen: set[tuple[object, ...]] = set()
    target_per_kind = 300
    rng = random.Random(_POOL_SEED)
    for kd in kinds:
        attempts = 0
        added = 0
        while added < target_per_kind and attempts < target_per_kind * 40:
            attempts += 1
            if kd in ("area", "distance"):
                a = rng.choice(_POSITIVE_A_RANGE)
                b = 0
                c = rng.choice(_POSITIVE_C_RANGE)
                lower = rng.choice(_POSITIVE_BOUND_RANGE)
                upper = rng.choice(_POSITIVE_BOUND_RANGE)
            else:
                a = rng.choice(_A_RANGE)
                b = rng.choice(_BC_RANGE)
                c = rng.choice(_BC_RANGE)
                lower = rng.choice(_BOUND_RANGE)
                upper = rng.choice(_BOUND_RANGE)
            if kd == "antiderivative":
                # 발문이 "F(0) = k인 F(x)의 F(upper)"를 묻는다 → 적분 하한은 **0이어야 한다**.
                # 임의 lower를 쓰면 k + ∫(lower, upper)를 계산해 정답이 틀린다(PR #969 Codex P1).
                # 실측: 이 corpus 100문 중 84문이 lower≠0이었고 첫 레코드는 F(-2)를 묻고 -4부터
                # 적분해 260/3을 답으로 냈다 — SymPy 검산 결과 올바른 답은 -32/3이다.
                # 해설문("F(0)에 x=0부터 x=m까지의 정적분을 더한 값")은 처음부터 옳았다.
                lower = 0
            if lower >= upper:
                continue
            k = rng.choice(_K_RANGE) if kd == "antiderivative" else 0
            key = (kd, a, b, c, lower, upper, k)
            if key in seen:
                continue
            seen.add(key)
            pool.append(_Skeleton(kind=kd, a=a, b=b, c=c, lower=lower, upper=upper, k=k))
            added += 1
    rng.shuffle(pool)
    return tuple(pool)


_ANTIDERIVATIVE_TEMPLATES: tuple[str, ...] = (
    "다항함수 f(x) = {f}의 부정적분 중 F(0) = {k}인 함수를 F(x)라 할 때, F({m})의 값을 "
    "구하시오.",
)
_DEFINITE_TEMPLATES: tuple[str, ...] = (
    "다항함수 f(x) = {f}에 대하여 정적분 (구간 [{lower}, {upper}]에서의) 값을 구하시오.",
    "정적분 [{lower}, {upper}] 구간에서 f(x) = {f}의 정적분 값을 구하시오.",
)
_AREA_TEMPLATES: tuple[str, ...] = (
    "곡선 y = {f}와 x축 및 두 직선 x = {lower}, x = {upper}로 둘러싸인 도형의 넓이를 " "구하시오.",
)
_DISTANCE_TEMPLATES: tuple[str, ...] = (
    "수직선 위를 움직이는 점 P의 시각 t에서의 속도가 v(t) = {f}일 때, 시각 t = {lower}에서 "
    "t = {upper}까지 점 P가 움직인 거리를 구하시오.",
)


def _fraction_text(value: Fraction) -> str:
    """기약분수 문자열('7/2'·정수면 '4') — SymPy sympify와 왕복 정합(형제 생성기 관례 미러)."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _explanation(skeleton: _Skeleton) -> str:
    """해설 — 정적분 계산 적용을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    answer_text = _fraction_text(skeleton.answer)
    if skeleton.kind == "antiderivative":
        return (
            "F(m)의 값은 F(0)에 x=0부터 x=m까지의 정적분을 더한 값과 같으므로, 구하는 값은 "
            f"{answer_text} 이다."
        )
    if skeleton.kind == "definite":
        return f"정적분은 반도함수의 양 끝값의 차이므로, 구하는 값은 {answer_text} 이다."
    if skeleton.kind == "area":
        return (
            "구간에서 곡선이 항상 x축 위에 있으므로 넓이는 정적분값과 같아, 구하는 넓이는 "
            f"{answer_text} 이다."
        )
    return (
        "구간에서 속도가 항상 양수이므로 이동 거리는 위치의 변화량(정적분값)과 같아, 구하는 "
        f"거리는 {answer_text} 이다."
    )


def _answer_format(value: Fraction) -> AnswerFormat:
    """정답 형태 — 정수로 딱 떨어지면 자연수/실수, 아니면 분수(형제 생성기 관례 미러)."""
    if value.denominator == 1:
        return AnswerFormat.자연수 if value.numerator > 0 else AnswerFormat.실수
    return AnswerFormat.분수


@deterministic_generator
class Calculus1IntegralSkeletonGenerator:
    """미적분Ⅰ 적분 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `kind`(antiderivative/definite/area/distance) 필터로 밴드를 분리하고 성취기준 코드도
    함께 결정한다(gcd_lcm·conic_section_focus·measurement_unit_conversion 생성기의
    "kind→코드" 관례 계승 — 필터 없이 밴드별 인스턴스를 만들면 고정 시드 풀이 처음부터
    재생돼 같은 뼈대를 중복 방출한다).
    """

    def __init__(
        self,
        *,
        kind: Calculus1IntegralKind | None = None,
        slug_prefix: str = "wm-calc1integral",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("CALC1-INTEGRAL",),
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
        answer_text = _fraction_text(skeleton.answer)
        # distance kind는 서술상 변수가 t(시각)이므로 표시 변수를 t로 맞춘다 — x로 두면
        # "v(t) = x^2 + 1" 같은 변수 불일치가 생긴다(실측 발견·수정).
        display_var = "t" if skeleton.kind == "distance" else "x"
        f_display = _quad_display(skeleton.a, skeleton.b, skeleton.c, var=display_var)
        if skeleton.kind == "antiderivative":
            template = _ANTIDERIVATIVE_TEMPLATES[self._index % len(_ANTIDERIVATIVE_TEMPLATES)]
            question_text = template.format(f=f_display, k=skeleton.k, m=skeleton.upper)
        elif skeleton.kind == "definite":
            template = _DEFINITE_TEMPLATES[self._index % len(_DEFINITE_TEMPLATES)]
            question_text = template.format(f=f_display, lower=skeleton.lower, upper=skeleton.upper)
        elif skeleton.kind == "area":
            template = _AREA_TEMPLATES[self._index % len(_AREA_TEMPLATES)]
            question_text = template.format(f=f_display, lower=skeleton.lower, upper=skeleton.upper)
        else:
            template = _DISTANCE_TEMPLATES[self._index % len(_DISTANCE_TEMPLATES)]
            question_text = template.format(f=f_display, lower=skeleton.lower, upper=skeleton.upper)

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
                    "결정론 정적분 스켈레톤 조립(다항식 계수·구간→정적분 닫힌형 계산)",
                    "S2-a 수용 게이트(Tier1 SymPy Integral 평가 검산)",
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
