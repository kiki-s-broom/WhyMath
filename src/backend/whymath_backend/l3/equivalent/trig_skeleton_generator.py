"""삼각함수 특수각 값 파라메트릭 스켈레톤 동등문제 생성기 — S2 대수 확장(결정론·LLM 0).

지수·로그·수열 형제와 같은 `EquivalentProblemGenerator` 좌석을 구현하되 수학 실체가 다르다:
특수각(30°·45°·60°와 그 일반각)의 삼각함수 값 sin/cos/tan을 낸다. 배경(도메인 분담): 생성 코퍼스가
삼각함수 0건이었다 — 이 생성기가 삼각 코퍼스를 처음 확보한다(고2 대수·삼각함수의 뜻).

핵심 통찰(재구현 0): **삼각함수 값도 "x = f(θ)의 유일해"로 환원**된다. 조건식 `x − sin(θ) = 0`을
공급하면 SymPy가 특수각을 정확값(1/2·√3/2·√3/3 등)으로 평가하고, 기존 근 검증 스택
(`verify_answer`=evalf라 삼각 내장함수 수용·`derive_selected_root`=solve)이 **무변경 재사용**된다.
정답 문자열은 생성 시 `sympy.sstr`로 만들어 `derive_selected_root` 반환과 **글자까지 일치**시킨다
(교차 검증 정합). 조건식의 각은 도(°)를 라디안(θ·π/180)으로 넣어 SymPy 평가를 정확히 한다.

⚠️ 구조 dedup 주의: 조건은 `x − 상수`로 접혀 **같은 값이면 같은 signature**가 된다(sin30°·cos60°·
sin150°는 모두 1/2 → 충돌). 서로 다른 각이 오병합되지 않게 **풀을 값 기준으로 dedup**해 값이
유일한 (함수·각)만 남긴다(각 값 첫 출현·결정론 순서). v1은 특수각의 12개 서로 다른 값을 덮는다.
같은 값·다른 각(일반각 전체 보존)은 오케스트레이터 구조 dedup opt-out 설계가 필요해 후속으로 남긴다.

범위(v1): sin/cos/tan 특수각 값(서로 다른 값 유일)·단답형만. 삼각*방정식*(sin x = 1/2의 해·다근
선택), 삼각함수 그래프·주기, 사인·코사인 법칙, 객관식·오개념 distractor, LLM 발문 다양화는 후속.

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지·L1(ConceptTag)·SymPy(최하위)만
import(L4 참조 0). 난이도는 지역 함수(공유 difficulty.py 불침범·도메인 분담).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

import sympy

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.canonicalize import canonical_signature
from whymath_backend.l3.equivalent.generator import CandidateProblem, deterministic_generator
from whymath_backend.lang.josa import i_ga
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

__all__ = ["TrigonometricValueSkeletonGenerator"]

_POOL_SEED = 20260706

# 개념 태깅 — 개념그래프 원천 src_id(삼각함수의 뜻과 그래프). L1 데이터 키(L4 주입 원칙 밖).
_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12대수02-02", role="PRIMARY", relevance=0.95),
)

# 열거 대상 — 삼각함수 3종 × 특수각(30·45·60의 배수). tan의 미정의 각(90·270)은 값이 유한하지
# 않아 풀 조립에서 자동 제외된다(is_finite 검사). 값 기준 dedup 후 서로 다른 값 12종이 남는다.
_FUNCS: tuple[str, ...] = ("sin", "cos", "tan")
_DEGREES: tuple[int, ...] = (30, 45, 60, 90, 120, 135, 150, 180, 210, 225, 240, 300, 315, 330)
_SYMPY_FUNCS = {"sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan}


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _value_answer_format(answer_text: str) -> AnswerFormat:
    """정답 형태 — 양의 정수 문자열이면 자연수, 그 외(분수·무리수·음수)는 실수(무리근 형제 미러)."""
    try:
        return AnswerFormat.자연수 if int(answer_text) > 0 else AnswerFormat.실수
    except ValueError:
        return AnswerFormat.실수


@dataclass(frozen=True, slots=True)
class _TrigSkeleton:
    """삼각 특수각 뼈대 — 함수명 func·각도(°) deg. 값 = func(deg°). 모든 수치의 단일 진실 원천.

    `answer`는 SymPy 정확값의 `sstr`이라 `derive_selected_root` 반환과 글자까지 일치한다(정합).
    """

    func: str
    degree: int

    @property
    def _radians(self) -> sympy.Expr:
        return sympy.Rational(self.degree, 180) * sympy.pi

    @property
    def value(self) -> sympy.Expr:
        """SymPy 정확값 — 특수각이라 1/2·√3/2·√3/3 등으로 평가된다."""
        return sympy.sympify(_SYMPY_FUNCS[self.func](self._radians))

    @property
    def answer(self) -> str:
        """정답 문자열 — SymPy sstr(derive_selected_root 반환과 정확 일치)."""
        return str(sympy.sstr(self.value))

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − func(deg*pi/180) = 0'(닫힌 DSL·삼각 내장함수 수용)."""
        return f"x - {self.func}({self.degree}*pi/180) = 0"

    @property
    def difficulty(self) -> float:
        # 재보정(S2-08·계통 관찰 2·표본 30): 특수각 삼각함수 값(예 cos180°)은 단위원·특수각
        # 암기 기반 **1스텝**이라 QUAD-EQ 인수분해(base 2.0)보다 확연히 쉽다. 이전 base 2.8은
        # 명백한 인플레였다 — 1.3으로 내려(cos180°=1.5·sin30°=1.3) 저난도 대역에 둔다. 일반각
        # 부호 추론·tan·무리수 값 가산은 유지한다(전부 2.0 미만 유지).
        difficulty = 1.3
        if self.degree > 90:  # 일반각 — 사분면 부호 추론 부담.
            difficulty += 0.2
        if self.func == "tan":  # 탄젠트가 sin/cos보다 까다로움.
            difficulty += 0.2
        if "sqrt" in self.answer:  # 무리수 값.
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_trig_pool() -> tuple[_TrigSkeleton, ...]:
    """결정론 삼각 뼈대 풀 — (함수, 각) 열거·미정의(무한) 값 제외·**값 유일 dedup**·고정 시드 셔플.

    tan의 미정의 각(90°·270°)은 SymPy가 zoo(복소 무한)로 평가 — `is_finite`가 True가 아니라 제외
    된다. 값이 유일한 뼈대만 남겨 signature 유일성을 보장한다(같은 값 다른 각의 dedup 충돌 방지).
    """
    seen: set[str] = set()
    pool: list[_TrigSkeleton] = []
    for func in _FUNCS:
        for degree in _DEGREES:
            skeleton = _TrigSkeleton(func=func, degree=degree)
            value = skeleton.value
            if value.is_finite is not True:  # tan 90°·270° 등 미정의(zoo) 제외.
                continue
            answer = skeleton.answer
            if answer in seen:
                continue
            seen.add(answer)
            pool.append(skeleton)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


_TRIG_TEMPLATES: tuple[str, ...] = (
    "{func} {deg}°의 값을 구하시오.",
    "삼각함수 {func} {deg}°의 값을 구하시오.",
    "{func} {deg}° 를 계산하시오.",
)


# 함수별 단위원 좌표 정의 서술 — sin=y좌표·cos=x좌표·tan=y좌표를 x좌표로 나눈 값.
_UNIT_CIRCLE_COORD: dict[str, str] = {
    "sin": "y좌표",
    "cos": "x좌표",
    "tan": "y좌표를 x좌표로 나눈 값",
}


def _trig_explanation(skeleton: _TrigSkeleton) -> str:
    """삼각 해설 — 단위원 정의로 값의 근거를 서술(결정론·위생 청정·수치 등식 회피).

    교수학 교정(S2-08·표본 30): 이전 문구 "특수각의 삼각비로 구할 수 있으며"는 부정확했다 —
    '삼각비'는 직각삼각형(예각)에서 정의되는 개념이라 180°·210° 등 일반각에는 적용되지 않는다.
    좌표평면 **단위원 정의**(sin=대응점 y좌표·cos=x좌표·tan=y/x)로 서술해 근거 있는 논리를
    남긴다. 수치 등식('cos 180° = −1')은 위생 validator 오탐 여지가 있어 넣지 않고, 자기정합적인
    최종 값(그 값은 answer)만 자연어로 남긴다(형제 해설 규약 미러).
    """
    coord = _UNIT_CIRCLE_COORD[skeleton.func]
    # 주격 조사는 받침에 따라 이/가로 갈린다 — sin/cos 정의는 "…좌표"(받침 無 '가')지만
    # tan 정의는 "…나눈 값"(받침 有 '이')이라 하드코딩 '가'는 "값가" 오류를 낳는다(S2-08 josa
    # 계통 결함 잔여·표본 검수 2건). josa 헬퍼로 받침 판별해 교정(형제 생성기 josa 규약 미러).
    return (
        f"단위원 위에서 {skeleton.degree}°에 대응하는 점의 {coord}{i_ga(coord)} "
        f"{skeleton.func} {skeleton.degree}°의 값이므로, 그 값은 {skeleton.answer} 이다."
    )


def _trig_value_steps(skeleton: _TrigSkeleton) -> list[str]:
    """특수각 평가의 검증 단계 체인(S2-02) — 도(°)식 → 라디안식 → 정확값(전이 전부 correct).

    풀이의 *검증 가능한 골자*(도→라디안 환산·특수각 정확값 평가)만 구조화한다 — 서술은
    `answer_explanation` 몫(표현≠의미·QUAD-EQ `_factoring_steps` 규약 미러). 수용 게이트는
    unverifiable 0을 요구하므로(acceptance §verified) 체인 전 전이가 SymPy로 증명 가능해야
    한다 — 세 표기 모두 SymPy가 특수각 정확값으로 평가해 동치가 증명된다(풀 13종 전수 프로브:
    음수 값 −1/2·−√2/2, tan 무리수 값 √3/3·−√3 포함 전이 전부 correct 실측).
    """
    radian_expr = f"{skeleton.func}({sympy.sstr(skeleton._radians)})"  # 예 sin(pi/6)
    return [f"{skeleton.func}({skeleton.degree}*pi/180)", radian_expr, skeleton.answer]


@deterministic_generator
class TrigonometricValueSkeletonGenerator:
    """삼각함수 특수각 값 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    풀(값 유일)을 순서대로 소비(소진 시 None). 형제(수열·지수·로그·이차·미적분)와 같은 좌석·게이트·
    근 검증 스택을 공유한다(도메인 분담). 값이 유일해 signature도 유일 — 구조 dedup과 정합.
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-trig",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("TRIG-VAL",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_trig_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 삼각 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
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
        self, spec: EquivalenceSpec, skeleton: _TrigSkeleton, condition: str
    ) -> CandidateProblem:
        answer_text = skeleton.answer
        question_text = _TRIG_TEMPLATES[self._index % len(_TRIG_TEMPLATES)].format(
            func=skeleton.func, deg=skeleton.degree
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
            answer_format=_value_answer_format(answer_text),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_trig_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 삼각 특수각 값 스켈레톤 조립(함수·각→SymPy 정확값)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # x - func(deg*pi/180) = 0(검산용·독립 재계산)
            answer_map={"x": answer_text},
            answer_selection="unique",
            # S2-02: 생성기가 아는 평가 경로(도→라디안→정확값)를 구조 단계로 방출 —
            # 수용 게이트 Tier2·상시 재검증(corpus_reverify)·WH-S replay가 소비한다.
            solution_steps=_trig_value_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )
