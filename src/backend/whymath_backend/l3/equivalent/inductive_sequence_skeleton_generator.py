"""귀납 정의 수열 파라메트릭 스켈레톤 동등문제 생성기 — S2-06 수능 신호 점화(결정론·LLM 0).

수열 일반항 생성기(`ArithmeticSequenceSkeletonGenerator`·`GeometricSequenceSkeletonGenerator`)의
**귀납적 정의 형제**다. 같은 `EquivalentProblemGenerator` 좌석을 구현하되, 발문이 수능 시그니처
구조를 *실제로* 가진다: (가)(나) 조건 나열 + 점화식(등차 `aₙ₊₁ = aₙ + d`·등비 `aₙ₊₁ = r·aₙ`)으로
수열을 귀납 정의하고 특정 항을 묻는다. 배경(비날조 원칙): 기존 코퍼스 1,073문은 어떤 시그니처에도
해당하지 않았다 — 시그니처를 *날조*하는 대신, 시그니처 구조를 실제로 가진 문항 밴드를 신설한다.

핵심 통찰(재구현 0): **귀납 정의 수열의 특정 항도 "x에 대한 방정식의 유일해"로 환원**된다. 점화식의
폐형(등차 aₖ = a+(k−1)d·등비 aₖ = a·rᵏ⁻¹)을 조건식 `x − (폐형) = 0`으로 공급하면 기존 근 검증
스택(`verify_answer`·`derive_selected_root`)이 **무변경 재사용**된다(생성≠검증 — SymPy 독립 재계산).

발문 표기(고정·태거 계약): `l1/problem_bank/signature_tagger.py`의 T2 정규식
(`aₙ₊₁ = (?:aₙ \\+ \\d+|\\d+·aₙ)`)과 정확히 일치하는 유니코드 아래첨자 표기를 방출한다. ASCII
`a_1 = 3` 표기는 위생 게이트의 수치 등식 검사("1 = 3" 오검출)와 충돌해 쓰지 않는다(실측 확인).
`signature_patterns`는 생성기가 채우지 않는다(빈 배열) — 태거가 단일 권위(조성 루트가 sink 기록
직전 적용). 대신 조건 나열 메타(`has_condition_list=True`·`condition_count=2`·`conditions_parsed`)
는 문항 구조의 사실이므로 여기서 채운다.

⚠️ 구조 dedup 주의: 조건식은 `x − 상수`로 접혀(canonical_signature 非None) **같은 답이면 같은
signature**다 — 등차·등비를 가로질러 **답 기준 단일 dedup**해 답이 유일한 뼈대만 남긴다(밴드 내
signature 전건 유일·오병합 0·일반항 형제와 동일 전략).

범위(v1): 1단계 점화(등차·등비)·양의 정수 항·단답형만. 2단계 점화(aₙ₊₂), 조건부 점화(홀짝 분기),
객관식·오개념 distractor는 후속(별도 검증 재료 필요).

7계층: L3 지역(LLM 0·좌석 계약만 공유). schema·동일 패키지(canonicalize)·L1(ConceptTag)만
import(L4 참조 0). 난이도는 지역 함수(공유 difficulty.py 불침범·도메인 분담).
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
from whymath_backend.schema.problem import Condition, Problem
from whymath_backend.schema.provenance import ContentProvenance

__all__ = ["InductiveSequenceSkeletonGenerator", "skeleton_to_sequence_dsl"]

# 풀 셔플 고정 시드 — 같은 구성은 같은 출제 순서(재현·디버그). 형제 생성기 규약 미러.
_POOL_SEED = 20260706

# 개념 태깅 — 개념그래프 원천 src_id(수열의 귀납적 정의·`data/corpus/concept_graph_v1` 실재 노드).
# 성취기준 [12대수03-06]("수열의 귀납적 정의를 설명할 수 있다")과 1:1 — 형제 생성기 규약 미러.
_INDSEQ_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12대수03-06", role="PRIMARY", relevance=0.95),
)

# 값 상한 — 손계산 가능 범위(일반항 형제 미러): 등차 점화 200·등비 점화 1000(거듭제곱 성장 감안).
_ARITH_MAX = 200
_GEO_MAX = 1000

# 등차:등비 인터리브 비율 — 등차 4문마다 등비 1문을 섞는다. 셔플 운에 맡기면 기본 밴드(30문)에
# 등비 점화 변형이 0건일 수 있어, 결정론 인터리브로 두 변형의 동시 수록을 구조적으로 보장한다.
_INTERLEAVE_ARITH_PER_GEO = 4

# 아래첨자 숫자 변환 — 발문 항 번호 표기(a₇)·위생 게이트와 충돌 없는 유니코드 표기.
_SUBSCRIPT_DIGITS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def _subscript(n: int) -> str:
    """양의 정수를 유니코드 아래첨자 문자열로(예: 12 → '₁₂')."""
    return str(n).translate(_SUBSCRIPT_DIGITS)


def _stable_slug(prefix: str, question_text: str, answer: str, codes: Sequence[str]) -> str:
    """결정론 안정 slug — 내용 해시(멱등 upsert 키·형제 스켈레톤 생성기 규약 미러)."""
    payload = "|".join([question_text, answer, ",".join(sorted(codes))])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _indseq_answer_format(answer: int) -> AnswerFormat:
    """정답 형태 — 양의 정수=자연수·그 외=실수(형제 미러). 귀납 v1은 전건 양의 정수."""
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


@dataclass(frozen=True, slots=True)
class _InductiveSkeleton:
    """귀납 정의 뼈대 — 점화 종류(kind)·첫째항 a·증분(공차/공비)·구하는 항 k. 수치의 단일 진실 원천.

    kind="arith"(등차 점화 aₙ₊₁ = aₙ + step)·"geo"(등비 점화 aₙ₊₁ = step·aₙ). 폐형은 각각
    aₖ = a + (k−1)·step·aₖ = a·stepᵏ⁻¹ — 조건식·정답이 이 폐형에서 나온다(파이썬 계산과 SymPy
    재계산의 교차 검증).
    """

    kind: str  # "arith" | "geo"
    first: int
    step: int  # 등차=공차 d·등비=공비 r
    term: int  # 구하는 항 번호 k (≥2)

    @property
    def answer(self) -> int:
        """정답 — 등차 폐형 a+(k−1)d·등비 폐형 a·rᵏ⁻¹."""
        if self.kind == "arith":
            return self.first + (self.term - 1) * self.step
        return int(self.first * self.step ** (self.term - 1))

    @property
    def condition(self) -> str:
        """검산용 SymPy 등식 — 'x − (폐형) = 0'. 점화식의 폐형을 그대로 공급(독립 재계산)."""
        if self.kind == "arith":
            return f"x - ({self.first} + ({self.term} - 1)*{self.step}) = 0"
        return f"x - ({self.first} * {self.step}**({self.term} - 1)) = 0"

    @property
    def recurrence_text(self) -> str:
        """(나) 점화식 발문 표기 — 태거 T2 정규식과 정확 일치하는 고정 표기(상호 계약)."""
        if self.kind == "arith":
            return f"aₙ₊₁ = aₙ + {self.step} (n ≥ 1)"
        return f"aₙ₊₁ = {self.step}·aₙ (n ≥ 1)"

    @property
    def difficulty(self) -> float:
        """rule-based 난이도 — 기저 1.7·항 번호 크면 +0.1·등비 점화 +0.1(범위 1.7~1.9).

        재보정(S2-08·계통 관찰 2): 점화식을 폐형으로 펴 특정 항을 구하는 정의 1스텝이라 QUAD-EQ
        인수분해(base 2.0)보다 쉽다. 이전 base 3.3은 명백한 인플레였다 — 1.7로 내려 QUAD-EQ 아래에
        앉힌다(항수·등비 가산 유지).
        """
        difficulty = 1.7
        if self.term >= 8:
            difficulty += 0.1
        if self.kind == "geo":
            difficulty += 0.1
        return round(min(5.0, max(1.0, difficulty)), 1)


def skeleton_to_sequence_dsl(skeleton: _InductiveSkeleton) -> str:
    """뼈대를 `sequence_induction` DSL로 직렬화한다 — 발문의 점화식을 **실제로 실행**할 재료(S4-66).

    `verify.conditions`의 폐형식(`x - (폐형) = 0`)은 생성기가 계산한 값이라 점화식과 어긋나게
    생성돼도 Tier1에서는 드러나지 않는다. 이 DSL은 발문과 같은 점화식(등차 `aₙ₊₁ = aₙ + d`·등비
    `aₙ₊₁ = r·aₙ`)과 초기항을 그대로 옮기므로, 실행값과 폐형 값의 대조가 그 정합을 닫는다.
    """
    if skeleton.kind == "arith":
        recurrence = f"a(n) + {skeleton.step}"
    else:
        recurrence = f"{skeleton.step}*a(n)"
    return f"init=a(1)={skeleton.first}; " f"rec=a(n+1)={recurrence}; " f"query=a({skeleton.term})"


def _build_inductive_pool() -> tuple[_InductiveSkeleton, ...]:
    """결정론 귀납 뼈대 풀 — 등차·등비 열거·답 상한·**답 유일 dedup(종류 가로질러)**·인터리브.

    답이 유일해야 signature도 유일하다(`x − 상수` 접힘·구조 dedup 오병합 방지) — 등차·등비가 같은
    답을 내면 같은 signature이므로 **단일 seen 집합**으로 가로질러 dedup한다(등비 먼저 열거해 작은
    답 등비 뼈대를 보존 — 등차가 4~200 대역을 조밀하게 채우므로 순서를 바꾸면 등비가 소수만 남는다).
    최종 순서는 각 종류를 고정 시드로 셔플한 뒤 등차 4 : 등비 1로 인터리브 — 기본 밴드(30문)에 두
    점화 변형이 반드시 함께 실리게 한다(운 배제·결정론).
    """
    seen: set[int] = set()
    geo_pool: list[_InductiveSkeleton] = []
    for first in range(1, 6):
        for step in (2, 3, 5):
            for term in range(3, 9):
                skeleton = _InductiveSkeleton(kind="geo", first=first, step=step, term=term)
                answer = skeleton.answer
                if answer > _GEO_MAX or answer in seen:
                    continue
                seen.add(answer)
                geo_pool.append(skeleton)
    arith_pool: list[_InductiveSkeleton] = []
    for first in range(1, 10):
        for step in range(1, 7):
            for term in range(4, 13):
                skeleton = _InductiveSkeleton(kind="arith", first=first, step=step, term=term)
                answer = skeleton.answer
                if answer > _ARITH_MAX or answer in seen:
                    continue
                seen.add(answer)
                arith_pool.append(skeleton)
    random.Random(_POOL_SEED).shuffle(arith_pool)
    random.Random(_POOL_SEED).shuffle(geo_pool)

    # 결정론 인터리브(등차 4 : 등비 1) — 한쪽 소진 시 나머지를 그대로 잇는다.
    pool: list[_InductiveSkeleton] = []
    arith_iter = iter(arith_pool)
    geo_iter = iter(geo_pool)
    arith_run = 0
    while True:
        source = arith_iter if arith_run < _INTERLEAVE_ARITH_PER_GEO else geo_iter
        item = next(source, None)
        if item is None:
            remaining = geo_iter if source is arith_iter else arith_iter
            pool.extend(remaining)
            break
        pool.append(item)
        arith_run = arith_run + 1 if source is arith_iter else 0
    return tuple(pool)


def _inductive_steps(skeleton: _InductiveSkeleton) -> list[str]:
    """귀납 전개 풀이의 검증 단계 체인(S2-02) — 반복 전개 → 폐형 → 값(단일 동치 스레드).

    `verify_step`은 *연속 쌍의 표현식 동치*만 증명하므로, 점화식 전개를 상수 표현식의 평가
    체인으로 편다(실측 프로브 확인 — 전 전이 correct·수용 게이트 unverifiable 0 충족):
      등차: "2 + 3 + 3 + 3" → "2 + (4 - 1)*3" → "11"  (첫째항에 공차를 k−1번 더함)
      등비: "2*3*3*3" → "2*3**(4 - 1)" → "54"        (첫째항에 공비를 k−1번 곱함)
    근 '선택'은 `answer_selection`(unique)이 별도 검증하고, 서술은 `answer_explanation`이
    담당한다(표현≠의미 — QUAD-EQ `_factoring_steps` 규약 미러).
    """
    repeats = skeleton.term - 1  # 점화 적용 횟수 k−1 (풀 전건 term ≥ 3이라 항상 ≥ 2)
    if skeleton.kind == "arith":
        expanded = f"{skeleton.first} + " + " + ".join([str(skeleton.step)] * repeats)
        closed = f"{skeleton.first} + ({skeleton.term} - 1)*{skeleton.step}"
    else:
        expanded = f"{skeleton.first}*" + "*".join([str(skeleton.step)] * repeats)
        closed = f"{skeleton.first}*{skeleton.step}**({skeleton.term} - 1)"
    return [expanded, closed, str(skeleton.answer)]


def _indseq_explanation(skeleton: _InductiveSkeleton) -> str:
    """귀납 해설 — 점화식을 폐형으로 푸는 과정을 자연어로 서술(결정론·위생 청정·수치 등식 회피)."""
    if skeleton.kind == "arith":
        return (
            f"점화식에 따라 첫째항 {skeleton.first}에 "
            f"{skeleton.step}{eul_reul(str(skeleton.step))} {skeleton.term - 1}번 "
            f"더한 값이므로, a{_subscript(skeleton.term)}의 값은 {skeleton.answer} 이다."
        )
    return (
        f"점화식에 따라 첫째항 {skeleton.first}에 "
        f"{skeleton.step}{eul_reul(str(skeleton.step))} {skeleton.term - 1}번 "
        f"곱한 값이므로, a{_subscript(skeleton.term)}의 값은 {skeleton.answer} 이다."
    )


@deterministic_generator
class InductiveSequenceSkeletonGenerator:
    """귀납 정의 수열 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    풀(답 유일·등차/등비 인터리브)을 순서대로 소비(소진 시 None). 일반항 형제와 동일 좌석·게이트·
    근 검증 스택을 공유한다(도메인 분담). 답이 유일해 signature도 유일 — 구조 dedup과 정합.
    발문은 (가)(나) 조건 나열 + 점화식 고정 표기 — 시그니처 태거(T1·T2)의 실제 양성 코퍼스가 된다.
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-indseq",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("IND-SEQ",),
        concept_tags: Sequence[ConceptTag] = _INDSEQ_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_inductive_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 귀납 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
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
        self, spec: EquivalenceSpec, skeleton: _InductiveSkeleton, condition: str
    ) -> CandidateProblem:
        answer_text = str(skeleton.answer)
        first_condition_text = f"a₁ = {skeleton.first}"
        # 발문 형식(고정) — (가)(나) 조건 나열 + 점화식(태거 T1·T2 정규식과 정확 일치).
        question_text = (
            "수열 {aₙ}이 다음 조건을 만족시킨다.\n"
            f"(가) {first_condition_text}\n"
            f"(나) {skeleton.recurrence_text}\n"
            f"a{_subscript(skeleton.term)}의 값을 구하시오."
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
            answer_format=_indseq_answer_format(skeleton.answer),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_indseq_explanation(skeleton),
            distractor_map=None,
            # 조건 나열 메타 — 발문 구조의 사실(가/나 2건). signature_patterns는 채우지 않는다
            # (태거가 단일 권위 — 조성 루트가 sink 기록 직전 apply_signatures 적용).
            has_condition_list=True,
            condition_count=2,
            conditions_parsed=[
                Condition(label="가", text=first_condition_text),
                Condition(label="나", text=skeleton.recurrence_text),
            ],
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 귀납 정의 수열 스켈레톤 조립(점화식→폐형→항 계산)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # x - (폐형) = 0(검산용·독립 재계산)
            answer_map={"x": answer_text},
            answer_selection="unique",  # 특정 항은 유일값
            # S2-02: 생성기가 아는 풀이 경로(반복 전개→폐형→값)를 구조 단계로 방출 —
            # 수용 게이트 Tier2·상시 재검증(corpus_reverify)·WH-S replay가 소비한다.
            solution_steps=_inductive_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )
