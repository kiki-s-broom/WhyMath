"""초등 어림(올림·버림·반올림) 결정론 스켈레톤 생성기 — W2 Phase2 #2(결정론·LLM 0).

`elementary_division_remainder_skeleton_generator`(초등 나눗셈)의 형제 — 초등 "수와 연산"
영역의 다음 착점이다. `[6수01-03]`(올림, 버림, 반올림)이 0건이었다 — 이 생성기가 첫
코퍼스를 확보한다. 개념그래프 매핑: `R2`(어림(올림·버림·반올림)) — legacy 437 공간에
실존, 세 연산을 한 개념으로 묶어 다룬다(생성기의 `kind` 3분기 설계와 정합).

**발문 해석(QUAL-11)**: 한국 초등 교과서의 정식 표현은 "올림하여 십의 자리까지 나타내기"다 —
"X의 자리까지"는 X 자리를 *마지막으로 남기는* 해석(배율 N=X의 자리값)이고, "X의 자리에서
올림"은 *X 자리 숫자를 보고 그 윗자리까지* 나타내는 다른 해석(배율 10N)이다. 정답 계산은
전자(배율=자리값)이므로 발문도 "X의 자리까지"로 맞춘다(과거 "X의 자리에서"로 쓴 600문은
537문이 관례와 어긋났다). 어림 자리 아래가 전부 0이라 답이 입력값과 같은 입력은 어림의
의미가 없어 풀에서 거른다.

`kind`(ceil/floor/round) 필터로 밴드 분리. 자릿수 위치(십·백·천의 자리)는 밴드 내 자유
파라미터 — 별도 필터 불필요(place가 달라져도 같은 kind 풀 안에서 서로 다른 뼈대이므로
중복 위험이 없다).

**검증 설계**: 조건은 값·자릿수 배율(N=10/100/1000)만으로 SymPy `ceiling()`/`floor()`가
결과를 독립 재유도한다.
- 올림: `ceiling(value/N)*N`
- 버림: `floor(value/N)*N`
- 반올림: `floor(value/N + 1/2)*N` — **주의**: Python 내장 `round()`(은행가 반올림·5를 짝수로
  반올림)와 다르다. 한국 초등 교과서 관례는 "5는 항상 올림"(round-half-up)이므로
  `floor(x+0.5)`로 직접 구현한다(스파이크로 정확히 5인 경계값에서 올림 방향 확인).

범위(v1): 자연수·십/백/천의 자리 어림만. 소수 어림·만 단위 이상은 후속.

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
from whymath_backend.l3.equivalent.generator import CandidateProblem
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

__all__ = ["RoundingKind", "RoundingSkeletonGenerator"]

_POOL_SEED = 20260807

_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="R2", role="PRIMARY", relevance=0.95),
)

RoundingKind = Literal["ceil", "floor", "round"]

# (자리 이름, 배율 N — "N의 자리까지 나타내기"는 N의 한 자리 아래 숫자를 보고 N의 배수로 어림).
_PLACES: tuple[tuple[str, int], ...] = (("십", 10), ("백", 100), ("천", 1000))
# 어림 대상(바로 아랫자리) 이름 — 해설에서 "어느 자리 숫자를 보는가"를 밝힌다.
_LOWER_PLACE: dict[int, str] = {10: "일", 100: "십", 1000: "백"}
_VALUE_RANGE = range(1000, 100000)
_POOL_TARGET = 300

# 교과서 정식 표현("~하여 X의 자리까지 나타내면") — 정답 계산(배율=자리값)과 같은 해석.
_CEIL_TEMPLATES: tuple[str, ...] = (
    "{value}{josa} 올림하여 {place}의 자리까지 나타내면 얼마인지 구하시오.",
)
_FLOOR_TEMPLATES: tuple[str, ...] = (
    "{value}{josa} 버림하여 {place}의 자리까지 나타내면 얼마인지 구하시오.",
)
_ROUND_TEMPLATES: tuple[str, ...] = (
    "{value}{josa} 반올림하여 {place}의 자리까지 나타내면 얼마인지 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _RoundingSkeleton:
    """어림 뼈대 — 원래 값·자리 이름·배율 N·연산 종류. 단일 진실 원천."""

    kind: RoundingKind
    value: int
    place_name: str
    factor: int  # N

    @property
    def answer(self) -> int:
        """정답 — 올림/버림/반올림 공식을 그대로 정수 산술로 평가(생성기 자체 검산)."""
        q, r = divmod(self.value, self.factor)
        if self.kind == "floor":
            return q * self.factor
        if self.kind == "ceil":
            return q * self.factor if r == 0 else (q + 1) * self.factor
        # round-half-up: 나머지가 배율의 절반 이상이면 올림.
        return (q + 1) * self.factor if r * 2 >= self.factor else q * self.factor

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — value·factor(주어진 정보)만으로 독립 재유도."""
        if self.kind == "floor":
            return f"x - floor({self.value}/{self.factor})*{self.factor} = 0"
        if self.kind == "ceil":
            return f"x - ceiling({self.value}/{self.factor})*{self.factor} = 0"
        return f"x - floor({self.value}/{self.factor} + 1/2)*{self.factor} = 0"

    @property
    def difficulty(self) -> float:
        # 초등 5-6학년군 기준 — 어림은 나눗셈류보단 가볍다(procedural 하단).
        difficulty = 1.5
        if self.factor >= 1000:
            difficulty += 0.1
        if self.kind == "round":
            difficulty += 0.1  # 반올림이 올림·버림보다 판단 단계가 하나 더 있음.
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_pool(kind: RoundingKind | None = None) -> tuple[_RoundingSkeleton, ...]:
    """결정론 어림 뼈대 풀 — kind×value×place 거부 표본추출(조합공간이 크므로)·고정 셔플."""
    kinds: tuple[RoundingKind, ...] = ("ceil", "floor", "round") if kind is None else (kind,)
    rng = random.Random(_POOL_SEED)
    pool: list[_RoundingSkeleton] = []
    for kd in kinds:
        seen: set[tuple[int, int]] = set()
        target = _POOL_TARGET
        attempts = 0
        while len(seen) < target and attempts < target * 20:
            attempts += 1
            value = rng.choice(_VALUE_RANGE)
            place_name, factor = rng.choice(_PLACES)
            if value % factor == 0:
                continue  # 어림 자리 아래가 전부 0 — 답=입력값이라 어림의 의미가 없다(QUAL-11).
            key = (value, factor)
            if key in seen:
                continue
            seen.add(key)
            pool.append(
                _RoundingSkeleton(kind=kd, value=value, place_name=place_name, factor=factor)
            )
    rng.shuffle(pool)
    return tuple(pool)


def _explanation(skeleton: _RoundingSkeleton) -> str:
    """어림 해설 — 연산별 판단 기준을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    lower = _LOWER_PLACE[skeleton.factor]
    if skeleton.kind == "ceil":
        rule = f"{lower}의 자리 이하를 무조건 올려서"
    elif skeleton.kind == "floor":
        rule = f"{lower}의 자리 이하를 무조건 버려서"
    else:
        rule = f"{lower}의 자리 숫자가 5 이상이면 올리고 5 미만이면 버려서"
    return (
        f"{skeleton.place_name}의 자리까지 나타낼 때는 {rule} 나타내므로, "
        f"구하는 값은 {skeleton.answer} 이다."
    )


def _answer_format(value: int) -> AnswerFormat:
    return AnswerFormat.자연수 if value > 0 else AnswerFormat.실수


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


class RoundingSkeletonGenerator:
    """어림 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    `kind`(ceil/floor/round) 필터로 밴드를 분리한다(direction/operation 필터 관례 계승 —
    필터 없이 밴드별 인스턴스를 만들면 고정 시드 풀이 처음부터 재생돼 같은 뼈대를 중복
    방출한다).
    """

    def __init__(
        self,
        *,
        kind: RoundingKind | None = None,
        slug_prefix: str = "wm-round",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("ELEMENTARY-ROUNDING",),
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
        """다음 어림 뼈대를 후보로 조립 — 풀 소진 시 None."""
        if self._index >= len(self._pool):
            return None
        skeleton = self._pool[self._index]
        self._index += 1
        return self._assemble(spec, skeleton)

    def _assemble(self, spec: EquivalenceSpec, skeleton: _RoundingSkeleton) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        if skeleton.kind == "ceil":
            templates = _CEIL_TEMPLATES
        elif skeleton.kind == "floor":
            templates = _FLOOR_TEMPLATES
        else:
            templates = _ROUND_TEMPLATES
        question_text = templates[self._index % len(templates)].format(
            value=skeleton.value,
            place=skeleton.place_name,
            josa=eul_reul(str(skeleton.value)),
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
                    "결정론 어림 스켈레톤 조립(값·자리·연산종류→올림/버림/반올림 계산)",
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
