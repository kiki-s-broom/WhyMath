"""고등 미적분Ⅱ 적분법 — 삼각함수 정적분·넓이·속도와 거리 스켈레톤 생성기 — W2 Phase4 #2
(결정론·LLM 0).

`calculus1_integral_skeleton_generator`(S4-45)의 SymPy `Integral` Tier1 검증 경로를
삼각함수로 확장한다 — [12미적Ⅱ-03-01](여러 가지 함수의 부정적분과 정적분 — y=x^n(n실수)·
지수함수·삼각함수 중 이 생성기는 삼각함수만 담당)·[12미적Ⅱ-03-05](곡선으로 둘러싸인
도형의 넓이)·[12미적Ⅱ-03-07](속도와 거리)의 첫 코퍼스를 확보한다.

`kind`가 성취기준 코드를 결정한다(gcd_lcm·calculus1_integral 생성기의 "kind→코드" 패턴
재사용):
- `trig_definite`([12미적Ⅱ-03-01]) — f(x) = A·sin(x)의 정적분 ∫[lower,upper] f(x)dx.
  구간 부호 제약 없음(양수·음수 모두 가능).
- `trig_area`([12미적Ⅱ-03-05]) — 곡선과 x축·두 수직선으로 둘러싸인 넓이. 구간을 [0,π]
  안으로 제한해 sin(x)≥0을 구성으로 보장(v1 단순화 — 부호가 바뀌는 구간은 후속).
- `trig_distance`([12미적Ⅱ-03-07]) — 속도 v(t)=A·sin(t)로부터 이동 거리. 같은 [0,π] 제약.

**핵심 설계 — 항상 유리수(정수) 답 보장**: 구간 경계를 π/2의 배수 5점(0·π/2·π·3π/2·2π)
중에서만 선택한다. cos(kπ/2)는 k=0..4에서 순서대로 1·0·−1·0·1이므로 ∫A·sin(x)dx =
A·(cos(lower)−cos(upper))가 항상 A의 정수배로 딱 떨어진다(스파이크 실측 확인 — 무리수·
근사 답 회피, 형제 정적분 생성기들의 "닫힌형 유리수" 관례 계승).

**π 표시는 ASCII 텍스트 `pi`를 쓴다**(유니코드 `π` 자체는 코퍼스에 이미 등장하지만
grandfathered 상태의 정확한 의미가 이 세션에서 확정되지 않았다 — S4-42의 ∩·∪ 사고에서
"모호하면 안전한 쪽"을 택한 선례를 선제 적용해 위험 0인 ASCII만 쓴다). SymPy 조건식도
동일하게 `pi` 리터럴을 그대로 쓴다(sympify가 원어민 지원).

Tier2(`solution_steps`)는 형제 생성기와 동일하게 쓰지 않는다(`None`) — Tier1 단독 검증.

concept_src_id(legacy 437 개념그래프 `source_id` 필드 실측 확인 — 2026-08-07):
  H:12미적Ⅱ03-01=[12미적Ⅱ-03-01] · H:12미적Ⅱ03-05=[12미적Ⅱ-03-05] ·
  H:12미적Ⅱ03-07=[12미적Ⅱ-03-07].

범위(v1): sin(x) 계열만(cos·복합 삼각식·지수함수는 후속 — 지수함수는 정적분 결과가
일반적으로 무리수(e의 거듭제곱)라 이 생성기의 "닫힌형 유리수 답" 설계와 맞지 않아 별도
스켈레톤이 필요하다).

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
    "Calculus2TrigIntegralKind",
    "Calculus2TrigIntegralSkeletonGenerator",
    "TRIG_AREA_STANDARD_CODE",
    "TRIG_DEFINITE_STANDARD_CODE",
    "TRIG_DISTANCE_STANDARD_CODE",
]

_POOL_SEED = 20260807

TRIG_DEFINITE_STANDARD_CODE = "[12미적Ⅱ-03-01]"
TRIG_AREA_STANDARD_CODE = "[12미적Ⅱ-03-05]"
TRIG_DISTANCE_STANDARD_CODE = "[12미적Ⅱ-03-07]"

Calculus2TrigIntegralKind = Literal["trig_definite", "trig_area", "trig_distance"]

_KIND_INFO: dict[Calculus2TrigIntegralKind, tuple[str, str]] = {
    # kind → (성취기준 코드, concept_src_id).
    "trig_definite": (TRIG_DEFINITE_STANDARD_CODE, "H:12미적Ⅱ03-01"),
    "trig_area": (TRIG_AREA_STANDARD_CODE, "H:12미적Ⅱ03-05"),
    "trig_distance": (TRIG_DISTANCE_STANDARD_CODE, "H:12미적Ⅱ03-07"),
}

# 경계점 0..4 → (SymPy 파싱용 문자열, cos(k·pi/2) 값). k=0..4에서 cos는 1,0,-1,0,1 순환.
_BOUND_EXPR: dict[int, str] = {0: "0", 1: "pi/2", 2: "pi", 3: "3*pi/2", 4: "2*pi"}
_COS_AT_BOUND: dict[int, int] = {0: 1, 1: 0, 2: -1, 3: 0, 4: 1}

_A_RANGE = tuple(range(1, 6))
# trig_area/trig_distance 전용 — [0,pi] 안(경계점 0·1·2)만, sin(x)>=0 구성 보장.
_POSITIVE_BOUND_POINTS = (0, 1, 2)


def _term(coefficient: int, symbol: str) -> str:
    """계수 1은 생략('sin(x)'), 그 외는 'A*sin(x)' 형태(형제 생성기 표기 관례 미러)."""
    return symbol if coefficient == 1 else f"{coefficient}{symbol}"


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """삼각함수 정적분 뼈대 — f(x)=A·sin(x)·경계점 인덱스(0..4, π/2 배수). 단일 진실 원천."""

    kind: Calculus2TrigIntegralKind
    a: int
    lower_idx: int
    upper_idx: int

    @property
    def f_display(self) -> str:
        # trig_distance는 서술상 변수가 t(시각)이므로 표시를 t로 맞춘다 — x로 두면
        # "v(t) = 2sin(x)" 같은 변수 불일치가 생긴다(calculus1_integral 생성기 실측 발견을
        # 선제 적용해 스파이크 단계에서 재발 확인·즉시 수정).
        var = "t" if self.kind == "trig_distance" else "x"
        return _term(self.a, f"sin({var})")

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'Integral(A*sin(x), (x, lower, upper)) = y'."""
        lower = _BOUND_EXPR[self.lower_idx]
        upper = _BOUND_EXPR[self.upper_idx]
        return f"Integral({self.a}*sin(x), (x, {lower}, {upper})) = y"

    @property
    def answer(self) -> int:
        """독립 재계산(반도함수 −cos(x) 대입, cos(kπ/2) 순환표 이용) — 생성기 자체 검산."""
        return self.a * (_COS_AT_BOUND[self.lower_idx] - _COS_AT_BOUND[self.upper_idx])

    @property
    def lower_text(self) -> str:
        return _BOUND_EXPR[self.lower_idx]

    @property
    def upper_text(self) -> str:
        return _BOUND_EXPR[self.upper_idx]

    @property
    def difficulty(self) -> float:
        difficulty = {"trig_definite": 3.4, "trig_area": 3.3, "trig_distance": 3.5}[self.kind]
        if self.a >= 4:
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_pool(kind: Calculus2TrigIntegralKind | None = None) -> tuple[_Skeleton, ...]:
    """결정론 뼈대 풀 — kind별 A·경계점 쌍 열거·구조 키 자연 유일·고정 셔플.

    trig_definite는 5점 중 lower<upper 조합(PR #969 Codex P2로 역순 쌍 제거), trig_area·
    trig_distance는 [0,pi] 안(경계점 0·1·2 중 lower<upper)만 허용(sin(x)>=0 구성 보장).
    """
    kinds: tuple[Calculus2TrigIntegralKind, ...] = (
        ("trig_definite", "trig_area", "trig_distance") if kind is None else (kind,)
    )
    pool: list[_Skeleton] = []
    for kd in kinds:
        if kd == "trig_definite":
            points = range(5)
            # `lo < up`만 — 발문이 "구간 [lo, up]에서의 정적분"이라 역순 쌍은 표현이 깨진다.
            # 방향 있는 적분(∫_a^b = -∫_b^a) 자체는 정당하나, "구간"이라고 부르면서 방향 적분으로
            # 채점하면 묻는 값이 모호해진다(PR #969 Codex P2). 실측: 이 corpus의 구간 표기 100문
            # 중 50문이 [3*pi/2, 0] 같은 역순이었다. 같은 파일의 trig_area·trig_distance가
            # 이미 `lo < up` 관례를 쓰므로 그쪽으로 통일한다.
            pairs = [(lo, up) for lo in points for up in points if lo < up]
        else:
            pairs = [
                (lo, up)
                for lo in _POSITIVE_BOUND_POINTS
                for up in _POSITIVE_BOUND_POINTS
                if lo < up
            ]
        for a in _A_RANGE:
            for lower_idx, upper_idx in pairs:
                pool.append(_Skeleton(kind=kd, a=a, lower_idx=lower_idx, upper_idx=upper_idx))
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


_TRIG_DEFINITE_TEMPLATES: tuple[str, ...] = (
    "함수 f(x) = {f}에 대하여 정적분 (구간 [{lower}, {upper}]에서의) 값을 구하시오.",
)
_TRIG_AREA_TEMPLATES: tuple[str, ...] = (
    "곡선 y = {f}와 x축 및 두 직선 x = {lower}, x = {upper}로 둘러싸인 도형의 넓이를 " "구하시오.",
)
_TRIG_DISTANCE_TEMPLATES: tuple[str, ...] = (
    "수직선 위를 움직이는 점 P의 시각 t에서의 속도가 v(t) = {f}일 때, 시각 t = {lower}에서 "
    "t = {upper}까지 점 P가 움직인 거리를 구하시오.",
)


def _explanation(skeleton: _Skeleton) -> str:
    """해설 — 삼각함수 정적분 계산 적용을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    answer_text = str(skeleton.answer)
    if skeleton.kind == "trig_definite":
        return (
            f"sin(x)의 정적분은 반도함수 -cos(x)의 양 끝값 차이므로, 구하는 값은 "
            f"{answer_text} 이다."
        )
    if skeleton.kind == "trig_area":
        return (
            "구간에서 곡선이 항상 x축 위에 있으므로 넓이는 정적분값과 같아, 구하는 넓이는 "
            f"{answer_text} 이다."
        )
    return (
        "구간에서 속도가 항상 양수이므로 이동 거리는 위치의 변화량(정적분값)과 같아, 구하는 "
        f"거리는 {answer_text} 이다."
    )


def _natural_answer_format(answer: int) -> AnswerFormat:
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


@deterministic_generator
class Calculus2TrigIntegralSkeletonGenerator:
    """미적분Ⅱ 삼각함수 적분 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    `kind`(trig_definite/trig_area/trig_distance) 필터로 밴드를 분리하고 성취기준 코드도
    함께 결정한다(형제 생성기들의 "kind→코드" 관례 계승 — 필터 없이 밴드별 인스턴스를
    만들면 고정 시드 풀이 처음부터 재생돼 같은 뼈대를 중복 방출한다).
    """

    def __init__(
        self,
        *,
        kind: Calculus2TrigIntegralKind | None = None,
        slug_prefix: str = "wm-calc2trig",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("CALC2-TRIG-INTEGRAL",),
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
        if skeleton.kind == "trig_definite":
            template = _TRIG_DEFINITE_TEMPLATES[self._index % len(_TRIG_DEFINITE_TEMPLATES)]
        elif skeleton.kind == "trig_area":
            template = _TRIG_AREA_TEMPLATES[self._index % len(_TRIG_AREA_TEMPLATES)]
        else:
            template = _TRIG_DISTANCE_TEMPLATES[self._index % len(_TRIG_DISTANCE_TEMPLATES)]
        question_text = template.format(
            f=skeleton.f_display, lower=skeleton.lower_text, upper=skeleton.upper_text
        )

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
                    "결정론 삼각함수 정적분 스켈레톤 조립(A·경계점→cos 순환표 계산)",
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
