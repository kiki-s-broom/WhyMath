"""삼각방정식 파라메트릭 스켈레톤 동등문제 생성기 — S2 대수 확장(결정론·LLM 0).

삼각 특수각 *값*(`TrigonometricValueSkeletonGenerator`)의 **방정식 형제**다. 같은
`EquivalentProblemGenerator` 좌석을 구현하되 수학 실체가 다르다: 0°≤x<360° 구간에서 sin x = v·
cos x = v의 해(작은 해·큰 해)를 낸다. 배경(도메인 분담): 삼각 값은 채웠으나 삼각*방정식*이 0건이
었다 — 이 생성기가 삼각방정식 코퍼스를 처음 확보한다(고2 대수·삼각함수 활용).

핵심 통찰(재구현 0): 조건 `sin(x·π/180) − v = 0`은 **초월함수라 canonical_signature=None**(지수·로그
형)이 되어 구조 dedup을 우회하고 slug 유일성에 위임한다. `derive_selected_root(cond, "smallest"/
"largest")`가 구간의 두 해를 정확히 반환하고(예 sin x=1/2 → 30·150), `verify_answer`(evalf)가 삼각
내장함수를 수용해 대입 검증한다 — **기존 근 검증 스택 무변경 재사용**. answer는 생성 시
`derive_selected_root`로 만들어 게이트의 derive-and-verify와 **정확 일치**시킨다(교차검증 정합).

⚠️ 자성 검증 빌드 필터: sin/cos 특수값만 구간에 깔끔한 정수 2근을 준다. tan은 principal 1근,
일부 값(√3/3 등)은 asin(...) 꼴이라 정수각이 아니다. 풀 조립이 (함수·값·선택)마다 smallest·
largest를 실제 계산해 **둘 다 [0,360) 정수이고 서로 다른 것만** 채택한다(부적합 조합 자동 배제).

범위(v1): sin/cos·특수값(±1/2·±√3/2·±√2/2)·0°≤x<360°·작은/큰 해 2택·단답형만. tan 방정식(반주기
[0,180) 도메인 설계 필요), 일반해(+360°n), 라디안 표기, 객관식·오개념 distractor, LLM 다양화는 후속.

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지(canonicalize)·L3 근 검증
(verify_answer·같은 계층)·L1(ConceptTag)만 import(L4 참조 0). 난이도는 지역 함수(도메인 분담).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.canonicalize import canonical_signature
from whymath_backend.l3.equivalent.generator import CandidateProblem, deterministic_generator
from whymath_backend.l3.verify_answer import derive_selected_root
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

__all__ = ["TrigonometricEquationSkeletonGenerator"]

_POOL_SEED = 20260706

# 개념 태깅 — 삼각 값 형제와 동일 개념(삼각함수의 뜻과 그래프·활용). L4 주입 원칙 밖.
_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12대수02-02", role="PRIMARY", relevance=0.95),
)

# 열거 대상 — sin/cos × 특수값(± 1/2·√3/2·√2/2) × 작은/큰 해. tan·비정수각 값은 빌드 필터가 배제.
#   value_label=발문 표시형·value_expr=SymPy 파싱형(조건식 임베드). 둘을 분리해 √ 표기를 발문엔
#   보기 좋게(√3/2)·조건엔 파싱 가능(sqrt(3)/2)하게 둔다.
_FUNCS: tuple[str, ...] = ("sin", "cos")
_VALUES: tuple[tuple[str, str], ...] = (
    ("1/2", "1/2"),
    ("√3/2", "sqrt(3)/2"),
    ("√2/2", "sqrt(2)/2"),
    ("-1/2", "-1/2"),
    ("-√3/2", "-sqrt(3)/2"),
    ("-√2/2", "-sqrt(2)/2"),
)
_SELECTIONS: tuple[str, ...] = ("smallest", "largest")
_DOMAIN = "0° ≤ x < 360°"

# 값 라벨별 을/를 — 분수·무리수는 한국어로 "분모분의 분자"·"루트 n"으로 읽어 *분자(마지막 음절)*가
# 받침을 지배한다(josa 헬퍼의 문자기반 판별이 닿지 않는 고정 6값이라 명시 매핑·정직). 부호 불변.
#   1/2=이분의 일(일ㄹ有→을)·√3/2=이분의 루트삼(삼ㅁ有→을)·√2/2=이분의 루트이(이無→를).
_VALUE_JOSA: dict[str, str] = {
    "1/2": "을",
    "√3/2": "을",
    "√2/2": "를",
    "-1/2": "을",
    "-√3/2": "을",
    "-√2/2": "를",
}


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _int_degree(root: str | None) -> int | None:
    """derive 결과가 [0,360) 정수각이면 int로, 아니면 None(asin(...) 꼴·범위 밖 배제)."""
    if root is None:
        return None
    try:
        value = int(root)
    except ValueError:
        return None
    return value if 0 <= value < 360 else None


@dataclass(frozen=True, slots=True)
class _TrigEqSkeleton:
    """삼각방정식 뼈대 — 함수·값·근 선택·정답각. 정답은 빌드 시 derive로 확정(게이트 정합)."""

    func: str
    value_label: str
    value_expr: str
    selection: str  # smallest | largest
    answer: int  # 정답각(도)

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'func(x*pi/180) − v = 0'(초월함수·signature None). 근=구간 해."""
        return f"{self.func}(x*pi/180) - ({self.value_expr}) = 0"

    @property
    def difficulty(self) -> float:
        # 재보정(S2-08·계통 관찰 2): 삼각방정식은 특수각 값 조회(TRIG-VAL 1.3)보다는 무겁다 —
        # 구간 내 2근을 찾아 작은/큰 해를 고르는 선택 단계가 있다. 다만 QUAD-EQ 인수분해(base 2.0)
        # 언저리를 넘지 않게 base 3.2→1.8로 내리고, 무리수 값·큰 해 가산은 유지한다.
        difficulty = 1.8
        if "sqrt" in self.value_expr:  # 무리수 값.
            difficulty += 0.2
        if self.selection == "largest":  # 2사분면 이상 큰 해.
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def _build_trig_eq_pool() -> tuple[_TrigEqSkeleton, ...]:
    """결정론 삼각방정식 뼈대 풀 — (함수·값·선택) 열거·**빌드 필터**(2근 정수 [0,360))·시드 셔플.

    각 (함수, 값)에 smallest·largest를 실제 derive로 계산해 둘 다 정수각이고 서로 다른 경우만
    두 selection 뼈대를 만든다. tan·단일근·비정수각 값은 여기서 자동 배제된다(자성 검증).
    """
    pool: list[_TrigEqSkeleton] = []
    for func in _FUNCS:
        for label, expr in _VALUES:
            cond = f"{func}(x*pi/180) - ({expr}) = 0"
            smallest = _int_degree(derive_selected_root(cond, "smallest"))
            largest = _int_degree(derive_selected_root(cond, "largest"))
            if smallest is None or largest is None or smallest == largest:
                continue  # 단일근·비정수각·범위 밖 — 배제.
            for selection in _SELECTIONS:
                answer = smallest if selection == "smallest" else largest
                pool.append(
                    _TrigEqSkeleton(
                        func=func,
                        value_label=label,
                        value_expr=expr,
                        selection=selection,
                        answer=answer,
                    )
                )
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


_TEMPLATES: tuple[str, ...] = (
    "{domain}일 때, {func} x = {v}{josa} 만족하는 {sel} 해를 구하시오.",
    "{domain} 범위에서 방정식 {func} x = {v} 의 {sel} 해를 구하시오.",
)
_SEL_KO = {"smallest": "가장 작은", "largest": "가장 큰"}


def _explanation(skeleton: _TrigEqSkeleton) -> str:
    """삼각방정식 해설 — 구간 해 중 선택을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    sel = _SEL_KO[skeleton.selection]
    return (
        f"주어진 구간에서 {skeleton.func} 값이 조건을 만족하는 각을 찾아 {sel} 해를 고르면, "
        f"그 값은 {skeleton.answer}° 이다."
    )


def _substitution_check_steps(skeleton: _TrigEqSkeleton) -> list[str]:
    """정답각 대입 *검산 체인*(S2-02) — 좌변 함숫값(도→라디안) → 우변 특수값(표현식 동치).

    `_factoring_steps`(skeleton_generator·S2-02) 패턴의 삼각방정식판. 단 방정식 *변형* 체인
    ("sin(x·π/180)−v=0" → "x=30")은 `verify_step`이 표현식 동치만 증명해 unverifiable로
    떨어진다(실측) — 게이트 verified는 unverifiable 0을 요구하므로 금지. 대신 해를 대입한
    좌변 `func(answer*pi/180)`과 우변 `value_expr`의 동치를 체인으로 낸다. 풀의 모든 뼈대는
    특수각이라 SymPy simplify가 항상 correct로 증명한다(전 18건 프로브 실측). 근 '선택'은
    `answer_selection`(verify_root_selection)이 별도 검증한다(표현≠의미·역할 분담).
    """
    return [f"{skeleton.func}({skeleton.answer}*pi/180)", skeleton.value_expr]


@deterministic_generator
class TrigonometricEquationSkeletonGenerator:
    """삼각방정식 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    풀(빌드 필터로 2근 정수만)을 순서대로 소비(소진 시 None). 삼각 값 형제와 동일 좌석·게이트·근
    검증 스택을 공유한다(도메인 분담). 조건이 초월함수라 signature=None → slug 유일성에 위임.
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-trigeq",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("TRIG-EQ",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_trig_eq_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 삼각방정식 뼈대를 후보로 조립 — skip 집합 구조는 건너뛰고, 풀 소진 시 None."""
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            condition = skeleton.condition
            if self._skip is not None:
                signature = canonical_signature(condition, skeleton.selection)
                if signature is not None and signature in self._skip:
                    continue  # (초월함수라 실질 None — 계약 미러용)
            return self._assemble(spec, skeleton, condition)
        return None

    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _TrigEqSkeleton, condition: str
    ) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        question_text = _TEMPLATES[self._index % len(_TEMPLATES)].format(
            domain=_DOMAIN,
            func=skeleton.func,
            v=skeleton.value_label,
            josa=_VALUE_JOSA[skeleton.value_label],
            sel=_SEL_KO[skeleton.selection],
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
            answer_format=AnswerFormat.자연수,  # 정답각은 양의 정수(도)
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
                    "결정론 삼각방정식 스켈레톤 조립(함수·값·구간→근 선택)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # func(x*pi/180) - v = 0(검산용·derive 재계산)
            answer_map={"x": answer_text},
            answer_selection=skeleton.selection,  # smallest | largest(다근 중 선택)
            # S2-02: 대입 검산 체인 방출 — 수용 게이트 Tier2·상시 재검증·WH-S replay가 소비.
            solution_steps=_substitution_check_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )
