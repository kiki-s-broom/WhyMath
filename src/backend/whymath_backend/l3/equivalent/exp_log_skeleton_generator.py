"""지수·로그 방정식 파라메트릭 스켈레톤 동등문제 생성기 — S2 대수 확장(결정론·LLM 0).

`SkeletonEquivalentProblemGenerator`(S2-o·이차방정식)·`CalculusExtremumSkeletonGenerator`
(미적분)의 **대수 형제**다. 같은 `EquivalentProblemGenerator` 좌석을 구현하되 수학 실체가 다르다:
지수방정식 bˣ = bᵏ·로그방정식 log_b x = k의 해(x)를 낸다. 배경(도메인 분담): 생성 코퍼스가
이차방정식(고1)·미적분Ⅰ(고3)에 집중돼 **대수(고2·수학Ⅰ 후신)의 지수·로그 방정식이 0건**이었다
— 병렬 미적분 세션과 겹치지 않는 별개 도메인으로, 이 생성기가 지수·로그 코퍼스를 처음 확보한다.

핵심 통찰(재구현 0): **지수·로그 방정식도 "x에 대한 방정식의 유일근"으로 환원**된다. 지수는
밑·지수를 골라 bˣ = bᵏ(우변은 정수 bᵏ)을 역산하고, 로그는 밑·값을 골라 log_b x = k(해 x=bᵏ)를
역산한다. conditions로 SymPy 방정식(`b**x - v = 0`·`log(x, b) - k = 0`)을 공급하면, 기존 근 검증
스택(`verify_answer`=evalf라 지수·로그 내장함수 수용, `verify_root_selection`/
`derive_selected_root`=`sympy.solve`)이 **무변경 재사용**된다(실측: 게이트 accepted·동치후보).
지수·로그는 비다항이라 canonical signature=None이나, 오케스트레이터가 이를 1급 지원한다(비다항→
구조 dedup 스킵·임베딩 위임). 풀이 결정론으로 유일해 실제 중복은 생성 자체가 안 된다.

정직성·이중 방어: 생성물은 여전히 S2-a 게이트(Tier1 대입·근 선택·위생·동등성)를 통과해야
저장된다(생성기 자기 신뢰 금지 원칙). derive-and-verify가 answer_map을 재유도해 교차 검증한다.

범위(v1): 지수 bˣ=bᵏ(밑·지수 정수·양의 정수해)·로그 log_b x=k(해 x=bᵏ) 단답형만. 유일근이라
selection은 `unique`. 지수·로그 *부등식*, 밑이 미지수인 경우, 음의 지수(분수 우변), 객관식·오개념
distractor, LLM 발문 다양화는 후속(별도 검증 재료·설계 필요).

7계층: L3 지역(생성=LLM 라우터 도메인이나 이 구현은 LLM 0 — 좌석 계약만 공유). schema(최하위)·
동일 패키지(canonicalize)·L1 problem_bank(ConceptTag)만 import(L4 참조 0). 난이도는 공유
difficulty.py를 건드리지 않고 지역 함수로 둔다(병렬 세션과의 공유 파일 편집 최소화·도메인 분담).
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

__all__ = [
    "ExponentialEquationSkeletonGenerator",
    "LogarithmicEquationSkeletonGenerator",
]

# 풀 셔플 고정 시드 — 같은 구성은 같은 출제 순서(재현·디버그). 비결정 난수 금지(verify 규약 미러).
_POOL_SEED = 20260706

# 기본 개념 태깅 — 지수·로그 개념그래프 원천 src_id "지수함수·로그함수의 활용"([12대수01-08]
# 정착 — data/corpus/concept_graph_v1/concepts.jsonl). L1 데이터 키라 L4 오개념 주입 원칙 밖.
_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12대수01-08", role="PRIMARY", relevance=0.95),
)

# 밑·값 범위 — 손계산 가능한 작은 정수(대수 지수·로그 기본형·한국 고2 상식 범위). 결과값(bᵏ)은
# _MAX_VALUE 이하로 제한(과대 수치 회피). 밑=1은 지수·로그가 성립 안 해(단사 아님) 제외.
_BASES: tuple[int, ...] = (2, 3, 5, 6, 7, 10)
_MAX_VALUE = 1000
_MIN_EXPONENT = 1


def _powers(base: int) -> list[int]:
    """밑 base의 지수 목록 — bᵏ ≤ _MAX_VALUE인 k(≥_MIN_EXPONENT). 결정론 오름차순."""
    exponents: list[int] = []
    exponent = _MIN_EXPONENT
    while base**exponent <= _MAX_VALUE:
        exponents.append(exponent)
        exponent += 1
    return exponents


def _answer_format(answer: int) -> AnswerFormat:
    """정답의 형태 — 양의 정수=자연수·그 외(0·음수)=실수(정수 전용 형식 부재). 형제 생성기 미러."""
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _estimate_difficulty(*, base: int, exponent: int, magnitude: int) -> float:
    """rule-based 종합 난이도(지수·로그) — 밑·지수·결과값 크기에서 결정론 추정. 범위 1.5~2.3.

    재보정(S2-08·AI 검수 계통 관찰 2): EXP-EQ(bˣ=bᵏ)·LOG-EQ(log_b x=k)는 밑 통일·로그 정의
    그대로 읽는 **정의 1스텝** 문제라, 두 인수를 찾아 인수분해하는 QUAD-EQ(estimate_difficulty
    base 2.0)보다 **쉽다**. 이전 base 2.6은 인수분해보다 높아 명백한 인플레였다(표본 28·29).
    그래서 base를 1.5로 내려 평범한 1스텝이 2.0 미만(예 log_6 x=1 → 1.8)에 앉게 하고, 크기 가산은
    유지한다. 공유 difficulty.py는 건드리지 않고 지역 함수로 둔다(도메인 분담·병렬
    세션 공유 최소화).
    """
    difficulty = 1.5
    if base >= 5:
        difficulty += 0.3
    if exponent >= 4:
        difficulty += 0.3
    if magnitude > 100:
        difficulty += 0.2
    return round(min(5.0, max(1.0, difficulty)), 1)


# ── 지수방정식 bˣ = bᵏ ─────────────────────────────────────────────────────
_EXP_TEMPLATES: tuple[str, ...] = (
    "방정식 {b}^x = {v} 의 해를 구하시오.",
    "지수방정식 {b}^x = {v}{josa} 만족하는 x의 값을 구하시오.",
    "{b}^x = {v} 일 때, x의 값을 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _ExpSkeleton:
    """지수방정식 뼈대 — 밑 b·지수 k. bˣ = bᵏ(= 정수 v). 모든 수치의 단일 진실 원천.

    밑 b>1이라 지수함수는 단사 — bˣ = bᵏ의 실근은 x=k 하나뿐(유일근·selection=unique).
    """

    base: int
    exponent: int  # 정답 지수 k (≥1)

    @property
    def value(self) -> int:
        """우변 정수 v = bᵏ."""
        return int(self.base**self.exponent)  # 지수 ≥1이라 항상 int(mypy Any 추론 방어)

    @property
    def answer(self) -> int:
        """정답 — 지수 k(bˣ=bᵏ의 유일근)."""
        return self.exponent

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'b**x - v = 0'(닫힌 DSL·evalf 수용). 근 = k."""
        return f"{self.base}**x - {self.value} = 0"

    @property
    def difficulty(self) -> float:
        return _estimate_difficulty(base=self.base, exponent=self.exponent, magnitude=self.value)


def _build_exp_pool() -> tuple[_ExpSkeleton, ...]:
    """결정론 지수 뼈대 풀 — 밑 × (bᵏ≤_MAX_VALUE인 지수 k) 열거·고정 시드 셔플.

    (밑, 지수)가 문제를 유일 결정한다(중복 원천 불가). 밑>1만 써서 단사(유일근)를 보장한다.
    """
    pool = [
        _ExpSkeleton(base=base, exponent=exponent) for base in _BASES for exponent in _powers(base)
    ]
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _exp_steps(skeleton: _ExpSkeleton) -> list[str]:
    """지수 풀이의 검증 단계 체인(S2-02) — 닫힌형 평가 log(v, b) → k(표현식 동치·Tier2 correct).

    방정식 *변형* 체인(예 `["2**x - 32", "x - 5"]`)은 verify_step이 표현식 동치만 증명하므로
    unverifiable이다(실측) — 게이트 verified는 unverifiable 0을 요구해 수율이 붕괴한다. 대신
    해의 *닫힌형*을 체인으로 쓴다: bˣ = v의 해 x = log_b v 이고, v = bᵏ이라 log(v, b) ↔ k는
    SymPy가 정확 단순화로 증명하는 표현식 동치다(실측 correct·전 밑 공통). 근 '선택'은
    `answer_selection`(unique)이, 서술은 `answer_explanation`이 담당한다(표현≠의미·형제 미러).
    """
    return [f"log({skeleton.value}, {skeleton.base})", str(skeleton.answer)]


def _exp_explanation(skeleton: _ExpSkeleton) -> str:
    """지수 해설 — 우변을 밑의 거듭제곱으로 정리해 지수 비교(결정론·위생 청정).

    순수 수치 등식('v = bᵏ')은 피한다(위생 validator의 '^' 파싱 오탐 회피) — 우변을 거듭제곱
    *형태*로만 서술하고 등식은 x를 포함한 것(bˣ=bᵏ)만 쓴다.
    """
    return (
        f"{skeleton.base}^x = {skeleton.value} 에서 우변을 밑 {skeleton.base}의 거듭제곱으로 "
        f"나타내면 {skeleton.base}^{skeleton.exponent} 이므로, 밑이 같아 지수를 비교하면 "
        f"x = {skeleton.exponent} 이다."
    )


@deterministic_generator
class ExponentialEquationSkeletonGenerator:
    """지수방정식 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    풀을 순서대로 소비하며 후보를 낸다(소진 시 None — 오케스트레이터가 generation_failed로 정직
    기록). `skip_signatures`는 형제 생성기 계약과 동일하나, 지수 conditions는 비다항이라 canonical
    signature=None이 되어 실질 스킵이 없다(풀이 결정론 유일이라 dedup 불요). 형제(이차방정식·
    미적분) 생성기와 같은 좌석·게이트를 공유한다(도메인 분담·하이브리드).
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-exp",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("EXP-EQ",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_exp_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 지수 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            condition = skeleton.condition
            if self._skip is not None:
                signature = canonical_signature(condition, "unique")
                if signature is not None and signature in self._skip:
                    continue  # (비다항이라 실질 None — 계약 미러용)
            return self._assemble(spec, skeleton, condition)
        return None

    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _ExpSkeleton, condition: str
    ) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        templates = _EXP_TEMPLATES
        question_text = templates[self._index % len(templates)].format(
            b=skeleton.base, v=skeleton.value, josa=eul_reul(str(skeleton.value))
        )
        standard_codes = sorted(spec.achievement_standard_codes)
        slug = _stable_slug(self._slug_prefix, question_text, answer_text, standard_codes)

        problem = Problem(
            problem_id=uuid.uuid5(uuid.NAMESPACE_URL, f"whymath:problem:{slug}"),
            slug=slug,
            source_type=SourceType.자체생성,  # 저작권 구조적 강제(자작 뼈대·본문성 원본 0)
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
            answer_explanation=_exp_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 지수방정식 스켈레톤 조립(밑·지수→bˣ=bᵏ 역산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # b**x - v = 0(검산용·호출자 제공)
            answer_map={"x": answer_text},
            answer_selection="unique",  # bˣ=bᵏ의 유일근
            # S2-02: 닫힌형 평가 체인(log(v, b) → k)을 구조 단계로 방출 — 수용 게이트 Tier2·
            # 상시 재검증(corpus_reverify)·WH-S replay가 소비한다(형제 skeleton_generator 미러).
            solution_steps=_exp_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )


# ── 로그방정식 log_b x = k ──────────────────────────────────────────────────
_LOG_TEMPLATES: tuple[str, ...] = (
    "방정식 log_{b} x = {k} 의 해를 구하시오.",
    "로그방정식 log_{b} x = {k}{josa} 만족하는 x의 값을 구하시오.",
    "log_{b} x = {k} 일 때, x의 값을 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _LogSkeleton:
    """로그방정식 뼈대 — 밑 b·값 k. log_b x = k(해 x=bᵏ). 모든 수치의 단일 진실 원천.

    로그의 정의상 log_b x = k ⟺ x = bᵏ 하나뿐(유일근·selection=unique). 밑 b>1.
    """

    base: int
    exponent: int  # 우변 값 k (≥1) — 해는 x=bᵏ

    @property
    def answer(self) -> int:
        """정답 해 x = bᵏ."""
        return int(self.base**self.exponent)  # 지수 ≥1이라 항상 int(mypy Any 추론 방어)

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'log(x, b) - k = 0'(닫힌 DSL·log 내장함수 수용). 근 = bᵏ."""
        return f"log(x, {self.base}) - {self.exponent} = 0"

    @property
    def difficulty(self) -> float:
        return _estimate_difficulty(base=self.base, exponent=self.exponent, magnitude=self.answer)


def _build_log_pool() -> tuple[_LogSkeleton, ...]:
    """결정론 로그 뼈대 풀 — 밑 × (bᵏ≤_MAX_VALUE인 값 k) 열거·고정 시드 셔플.

    (밑, 값)이 문제를 유일 결정한다(중복 원천 불가). 밑>1만 써서 로그가 성립(유일근)한다.
    """
    pool = [
        _LogSkeleton(base=base, exponent=exponent) for base in _BASES for exponent in _powers(base)
    ]
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _log_steps(skeleton: _LogSkeleton) -> list[str]:
    """로그 풀이의 검증 단계 체인(S2-02) — 닫힌형 평가 bᵏ → 값(표현식 동치·Tier2 correct).

    지수 형제와 같은 이유로 방정식 변형 체인은 금지(unverifiable 실측·게이트 수율 붕괴) —
    로그의 정의 log_b x = k ⟺ x = bᵏ의 닫힌형만 체인화한다: b**k ↔ answer(정수 평가)는 SymPy가
    항상 증명하는 표현식 동치다(실측 correct). 스켈레톤 수치에서만 유도(결정론·slug 불변).
    """
    return [f"{skeleton.base}**{skeleton.exponent}", str(skeleton.answer)]


def _log_explanation(skeleton: _LogSkeleton) -> str:
    """로그 해설 — 로그의 정의로 지수 형태 환원(결정론·위생 청정).

    방정식 재진술('log_b x = k')은 넣지 않는다 — 위생 validator가 'log_b x'를 선형식 'b·x'로
    오독해 해설의 최종 해(x=answer)와 대조·거짓 해로 오탐하기 때문(실측). 정의를 자연어로만
    서술하고 등식은 자기정합적인 최종 해(x=answer)만 남긴다. 순수 수치 등식('bᵏ=answer')도 피한다.
    """
    return (
        f"로그의 정의에 따라 이 방정식의 해는 밑 {skeleton.base}{eul_reul(str(skeleton.base))} "
        f"{skeleton.exponent}번 거듭제곱한 값이므로, x = {skeleton.answer} 이다."
    )


@deterministic_generator
class LogarithmicEquationSkeletonGenerator:
    """로그방정식 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    "log_b x = k의 해"를 낸다 — 해 x=bᵏ이 유일근이라 지수 형제와 동일 좌석·게이트·근 검증 스택을
    공유한다(도메인 분담). 풀을 순서대로 소비(소진 시 None). 로그 conditions도 비다항이라 canonical
    signature=None(오케스트레이터 1급 지원·풀 결정론 유일이라 dedup 불요).
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-log",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("LOG-EQ",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_log_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 로그 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
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
        self, spec: EquivalenceSpec, skeleton: _LogSkeleton, condition: str
    ) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        templates = _LOG_TEMPLATES
        question_text = templates[self._index % len(templates)].format(
            b=skeleton.base, k=skeleton.exponent, josa=eul_reul(str(skeleton.exponent))
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
            answer_explanation=_log_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 로그방정식 스켈레톤 조립(밑·값→log_b x=k 역산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # log(x, b) - k = 0(검산용·호출자 제공)
            answer_map={"x": answer_text},
            answer_selection="unique",  # log_b x=k의 유일근
            # S2-02: 닫힌형 평가 체인(bᵏ → 값)을 구조 단계로 방출 — 지수 형제와 동일 규약.
            solution_steps=_log_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )
