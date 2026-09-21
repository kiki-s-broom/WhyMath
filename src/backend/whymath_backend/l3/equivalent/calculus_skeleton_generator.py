"""미적분(극값) 파라메트릭 스켈레톤 동등문제 생성기 — S2 미적분 확장(결정론·LLM 0).

`SkeletonEquivalentProblemGenerator`(S2-o, 이차방정식)의 **미적분 형제**다. 같은
`EquivalentProblemGenerator` 좌석을 구현하되 수학 실체가 다르다: 삼차함수의 극대·극소를 갖는
x좌표를 낸다. 배경(S2 실측): 생성 코퍼스 165건이 전부 고1 이차방정식이라 S2의 명시 목표이자
wedge(고3 킬러)인 **미적분 영역이 0건**이었다 — 이 생성기가 미적분Ⅰ 극값 코퍼스를 처음 확보한다.

핵심 통찰(재구현 0): **극값 문제는 "도함수 방정식 f'(x)=0의 근"으로 환원**된다. 임계점 (m,n)을
풀에서 골라 f'(x)=3(x−m)(x−n)을 역산·적분해 f(x)를 확정하고, conditions로 도함수 방정식을
호출자에게 공급한다. 정답은 임계점(=f'=0의 근), answer_selection은 극대→smallest·극소→largest
(선두계수 양수라 작은 임계점이 극대·큰 임계점이 극소). 따라서 기존 근 선택 검증 스택
(`verify_answer`·`verify_root_selection`·`derive_selected_root`, `sympy.solve` 기반·차수 불문)이
**무변경으로 재사용**된다 — 오케스트레이터·수용 게이트·저장 sink도 전부 그대로다.

정직성·이중 방어: 생성물은 여전히 S2-a 게이트(Tier1 대입·근 선택·위생·동등성)를 통과해야
저장된다(생성기 자기 신뢰 금지 원칙). derive-and-verify가 answer_map을 재유도해 교차 검증한다.

범위: **삼차함수 극대/극소의 x좌표**(=도함수 방정식의 근·근 선택으로 검증 가능한 것)만.
정수 임계점(같은 홀짝·f 정수계수)은 `CalculusExtremumSkeletonGenerator`, **무리 임계점 p±√q**(도함수
계수는 여전히 정수·답만 무리수)는 `CalculusIrrationalExtremumSkeletonGenerator`가 낸다 — 후자는 정수
극값의 근 선택 스택 + sqrt quad 패밀리의 SymPy 정확값 표기를 교집합 재사용(재구현 0). 극값의 *값*
f(x*)·근의 합/곱 등 근-비환원 문항, 킬러 난이도, 5지선다, LLM 발문 다양화는 후속.

7계층: L3 지역(생성=LLM 라우터 도메인이나 이 구현은 LLM 0 — 좌석 계약만 공유). schema(최하위)·
동일 패키지(canonicalize·difficulty)·L1 problem_bank(ConceptTag)만 import(L4 참조 0).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Literal

import sympy

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.canonicalize import canonical_signature
from whymath_backend.l3.equivalent.difficulty import (
    estimate_difficulty_extremum,
    estimate_difficulty_extremum_irrational,
)
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
from whymath_backend.schema.problem import DistractorEntry, Problem
from whymath_backend.schema.provenance import ContentProvenance

__all__ = [
    "CalculusExtremumMCSkeletonGenerator",
    "CalculusExtremumSkeletonGenerator",
    "CalculusExtremumValueSkeletonGenerator",
    "CalculusIrrationalExtremumSkeletonGenerator",
    "CalculusTangentSlopeSkeletonGenerator",
]

# 풀 셔플 고정 시드 — 같은 구성은 같은 출제 순서(재현·디버그). 비결정 난수 금지(verify 규약 미러).
_POOL_SEED = 20260706

# 기본 개념 태깅 — 극값 개념그래프 원천 src_id "함수의 증가·감소와 극대·극소"([12미적Ⅰ-02-07]
# 정착 — data/corpus/concept_graph_v1/concepts.jsonl). L1 데이터 키라 L4 오개념 주입 원칙 밖.
_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12미적Ⅰ02-07", role="PRIMARY", relevance=0.95),
)

# 임계점 풀 범위 — 손계산 가능한 작은 정수(미적분Ⅰ 극값 기본형·한국 고3 상식 범위).
_CRIT_MIN, _CRIT_MAX = -9, 9

ExtremumKind = Literal["극대", "극소"]

# 발문 템플릿(극값 종류별·인덱스 회전) — 표면 변주. {fx}에 사람이 읽는 삼차함수가 들어간다.
_TEMPLATES: dict[ExtremumKind, tuple[str, ...]] = {
    "극대": (
        "삼차함수 f(x) = {fx} 가 극대가 되는 x의 값을 구하시오.",
        "삼차함수 f(x) = {fx} 가 극댓값을 가질 때, 그 x의 값을 구하시오.",
        "함수 f(x) = {fx} 가 극대가 되는 x의 값을 구하시오.",
    ),
    "극소": (
        "삼차함수 f(x) = {fx} 가 극소가 되는 x의 값을 구하시오.",
        "삼차함수 f(x) = {fx} 가 극솟값을 가질 때, 그 x의 값을 구하시오.",
        "함수 f(x) = {fx} 가 극소가 되는 x의 값을 구하시오.",
    ),
}


def _term(coefficient: int, symbol: str, *, lead: bool = False) -> str:
    """계수 하나를 사람이 읽는 항으로 — 부호·1 생략 규칙(lead=선두 항은 + 없이). quad 미러."""
    sign = "-" if coefficient < 0 else ("" if lead else "+")
    magnitude = abs(coefficient)
    body = symbol if magnitude == 1 and symbol else f"{magnitude}{symbol}"
    joint = " " if sign and not lead else ""
    return f"{sign}{joint}{body}" if lead else f"{sign} {body}"


def _display_cubic(a: int, b: int, c: int, d: int) -> str:
    """전개 계수 → 사람이 읽는 삼차함수('x^3 - 6x^2 + 9x') — 0 항 생략·1 계수 생략."""
    parts = [_term(a, "x^3", lead=True)]
    if b:
        parts.append(_term(b, "x^2"))
    if c:
        parts.append(_term(c, "x"))
    if d:
        parts.append(_term(d, ""))
    return " ".join(parts)


def _derivative_condition(deriv_b: int, deriv_c: int) -> str:
    """monic 도함수 계수 → 검산용 SymPy 등식('x**2 - 4*x + 3 = 0') — 닫힌 DSL(맨 등식).

    f'(x)=3(x−m)(x−n)의 근은 3으로 나눈 monic x²+deriv_b·x+deriv_c=0과 동일하다(근 불변).
    conditions는 검산용이라 monic 정규형으로 공급한다 — canonicalize가 어차피 정규화한다.
    """
    parts = ["x**2"]
    if deriv_b:
        parts.append(f"{'-' if deriv_b < 0 else '+'} {abs(deriv_b)}*x")
    if deriv_c:
        parts.append(f"{'-' if deriv_c < 0 else '+'} {abs(deriv_c)}")
    return " ".join(parts) + " = 0"


def _linear_factor(root: int) -> str:
    """(x − root)의 사람이 읽는 표기 — 'x - 2'·'x + 3'·'x'(root 부호 반영·SymPy 파싱도 동일)."""
    if root == 0:
        return "x"
    return f"x - {root}" if root > 0 else f"x + {-root}"


def _sympy_quadratic_text(a2: int, a1: int, a0: int) -> str:
    """전개 이차식의 검산용 SymPy 표기('3*x**2 + 30*x + 27') — 0 항 생략·명시 `*`(닫힌 DSL)."""
    parts = [f"{a2}*x**2"]
    if a1:
        parts.append(f"{'-' if a1 < 0 else '+'} {abs(a1)}*x")
    if a0:
        parts.append(f"{'-' if a0 < 0 else '+'} {abs(a0)}")
    return " ".join(parts)


def _extremum_steps(m: int, n: int) -> list[str]:
    """극값류 풀이의 검증 단계 체인(S2-02) — 도함수 전개형 → 3(x−m)(x−n) 인수분해형.

    quad `_factoring_steps` 미러. 미분 전이(f→f')는 `verify_step`에서 unverifiable(실측)이라
    체인에 넣지 않는다 — 체인은 *도함수 다항식*에서 시작하는 단일 동치 스레드다(수용 게이트는
    unverifiable 0을 요구·acceptance §verified). 극값-값·MC 문항도 이 체인만 낸다: 극값 대입
    (f(m)=v)은 비동치 전이라 체인에 못 섞고, 값 자체는 Tier1 conditions가 검증한다."""
    expanded = _sympy_quadratic_text(3, -3 * (m + n), 3 * m * n)
    factored = f"3*({_linear_factor(m)})*({_linear_factor(n)})"
    return [expanded, factored]


@dataclass(frozen=True, slots=True)
class _ExtremumSkeleton:
    """극값 뼈대 — 두 임계점 (m<n)·같은 홀짝 + 극값 종류. 모든 수치의 단일 진실 원천.

    f'(x) = 3(x−m)(x−n) = 3x² − 3(m+n)x + 3mn 을 적분해 f(x) = x³ − (3(m+n)/2)x² + 3mn·x.
    m+n이 짝수라 x² 계수 −3(m+n)/2가 정수 → f 전개 계수 전부 정수(canonicalize·표기 안전).
    """

    m: int  # 작은 임계점
    n: int  # 큰 임계점 (m < n, m+n 짝수)
    kind: ExtremumKind

    @property
    def cubic_coeffs(self) -> tuple[int, int, int, int]:
        """f(x) 전개 계수 (a, b, c, d) — a x³ + b x² + c x + d. 상수항 d=0(극값 x좌표 무관)."""
        s = self.m + self.n  # 짝수(같은 홀짝 불변식)
        return 1, -(3 * s) // 2, 3 * self.m * self.n, 0

    @property
    def derivative_monic(self) -> tuple[int, int]:
        """monic 도함수 계수 (b', c') — x² + b'x + c' (= f'/3). 근 = 임계점 (m, n)."""
        return -(self.m + self.n), self.m * self.n

    @property
    def answer(self) -> int:
        """정답 임계점 — 선두계수 양수라 극대=작은 임계점 m·극소=큰 임계점 n."""
        return self.m if self.kind == "극대" else self.n

    @property
    def selection(self) -> str:
        """근 선택 — 극대→smallest(작은 임계점)·극소→largest(큰 임계점). root_selection 검증."""
        return "smallest" if self.kind == "극대" else "largest"

    @property
    def difficulty(self) -> float:
        """rule-based 종합 난이도 — 임계점 간격·전개 계수 크기에서 결정론 추정(difficulty 모듈)."""
        _, b, c, _ = self.cubic_coeffs
        return estimate_difficulty_extremum(
            root_spread=self.n - self.m,
            max_abs_coefficient=max(abs(b), abs(c)),
        )


def _build_pool() -> tuple[_ExtremumSkeleton, ...]:
    """결정론 극값 뼈대 풀 — 같은 홀짝 임계점 쌍 (m<n) × {극대, 극소} 열거·고정 시드 셔플.

    같은 (m,n)이라도 극대/극소는 다른 문제다(정답·선택이 다름 — signature의 selection payload가
    가른다). (도함수, 선택) 중복은 빌드 시점에 제거한다(풀 내 판박이 0). m+n 짝수만 수록
    (f 정수계수 불변식).
    """
    pool: list[_ExtremumSkeleton] = []
    seen: set[tuple[int, int, str]] = set()
    for m in range(_CRIT_MIN, _CRIT_MAX + 1):
        for n in range(m + 1, _CRIT_MAX + 1):
            if (m + n) % 2 != 0:
                continue  # 홀짝 다르면 f x² 계수가 비정수 → 제외.
            for kind in ("극대", "극소"):
                skeleton = _ExtremumSkeleton(m=m, n=n, kind=kind)
                key = (*skeleton.derivative_monic, skeleton.selection)
                if key not in seen:
                    seen.add(key)
                    pool.append(skeleton)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


class CalculusExtremumSkeletonGenerator:
    """미적분 극값 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(LLM 0).

    풀을 순서대로 소비하며 후보를 낸다(소진 시 None — 오케스트레이터가 generation_failed로 정직
    기록). `skip_signatures`에 이미 코퍼스에 있는 구조 signature 집합을 주면 해당 뼈대를 건너뛴다
    (배치 재실행이 dedup 거부로 회차를 낭비하지 않게 함 — 오케스트레이터 `signature_index` 공유).
    quad 형제 생성기와 동일한 좌석·게이트를 공유한다(하이브리드 분담).
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-calc-ext",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("CALC-EXTREMUM",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    # ── EquivalentProblemGenerator 좌석 ────────────────────────────────────
    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 극값 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            condition = _derivative_condition(*skeleton.derivative_monic)
            if self._skip is not None:
                signature = canonical_signature(condition, skeleton.selection)
                if signature is not None and signature in self._skip:
                    continue  # 이미 코퍼스에 있는 구조 — 회차 낭비 없이 다음 뼈대로.
            return self._assemble(spec, skeleton, condition)
        return None

    # ── 조립(전부 결정론·수치의 단일 진실 원천은 뼈대) ─────────────────────
    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _ExtremumSkeleton, condition: str
    ) -> CandidateProblem:
        a, b, c, d = skeleton.cubic_coeffs
        fx = _display_cubic(a, b, c, d)
        answer_text = str(skeleton.answer)
        templates = _TEMPLATES[skeleton.kind]
        question_text = templates[self._index % len(templates)].format(fx=fx)
        standard_codes = sorted(spec.achievement_standard_codes)
        slug = self._stable_slug(question_text, answer_text, standard_codes)

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
            answer_explanation=_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 극값 스켈레톤 조립(임계점→도함수 역산·적분)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # 도함수 방정식(검산용·호출자 제공·L5 파싱 밖)
            answer_map={"x": answer_text},
            answer_selection=skeleton.selection,
            # S2-02: 도함수 인수분해 체인 방출 — 게이트 Tier2·상시 재검증·WH-S replay가 소비.
            solution_steps=_extremum_steps(skeleton.m, skeleton.n),
            concept_tags=list(self._concept_tags),
        )

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        """결정론 안정 slug — 내용 해시(멱등 upsert 키·skeleton_generator 규약 미러)."""
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"


def _answer_format(answer: int) -> AnswerFormat:
    """정답 임계점의 형태 — 양의 정수=자연수·그 외(0·음의 정수)=실수(정수 전용 형식 부재)."""
    return AnswerFormat.자연수 if answer > 0 else AnswerFormat.실수


def _explanation(skeleton: _ExtremumSkeleton) -> str:
    """도함수 기반 해설 — 뼈대 수치에서 결정론 생성(부호 판정으로 극대·극소 확정·위생 청정)."""
    m, n = skeleton.m, skeleton.n
    f1, f2 = _linear_factor(m), _linear_factor(n)
    which_val = "극댓값" if skeleton.kind == "극대" else "극솟값"
    return (
        f"f'(x) = 3({f1})({f2}) 이므로 f'(x)=0의 해는 x = {m}, x = {n} 이다. "
        f"삼차항의 계수가 양수라 x = {m}에서 극대, x = {n}에서 극소이다. "
        f"따라서 {which_val}을 갖는 x는 {skeleton.answer}이다."
    )


# ── 미적분(무리 임계점 극값) 형제 생성기 — f'(x)=0의 근이 p±√q(답만 무리수) ──
# 정수 극값(임계점 정수)의 무리근 짝: 임계점이 p±√q여도 f'(x)=3(x−(p−√q))(x−(p+√q))
# = 3x²−6p·x+3(p²−q)라 도함수·삼차함수 계수는 *전부 정수*다. 즉 검산은 정수 극값과 동일한 근
# 선택 스택을 쓰고(도함수 monic x²−2p·x+(p²−q)=0의 근 대소 선택), *답만* 무리수 표기라 sqrt quad
# 패밀리의 SymPy 정확값 경로(sstr·AnswerFormat.실수)를 그대로 미러한다(두 선례의 교집합·재구현 0).

# 무리 임계점 풀 범위 — q는 *비제곱* 양수만(제곱수면 임계점이 유리수→정수 극값 풀과 구조 중복).
# p·q는 미적분Ⅰ "간단한 무리근" 손계산 범위(sqrt quad 패밀리 `_SQRT_QS` 규약 미러).
_IRR_P_MIN, _IRR_P_MAX = -4, 4
_IRR_QS: tuple[int, ...] = (2, 3, 5, 6, 7, 8, 10, 11, 12, 13)


def _display_monic_quadratic(b: int, c: int) -> str:
    """monic 이차식 → 사람이 읽는 표기('x^2 - 2x - 1') — 0 항·1 계수 생략(_display_cubic 미러)."""
    parts = [_term(1, "x^2", lead=True)]
    if b:
        parts.append(_term(b, "x"))
    if c:
        parts.append(_term(c, ""))
    return " ".join(parts)


@dataclass(frozen=True, slots=True)
class _IrrationalExtremumSkeleton:
    """무리 임계점 극값 뼈대 — 임계점 p±√q(q 비제곱 양수)·극값 종류. 모든 수치의 단일 진실 원천.

    f'(x) = 3(x−(p−√q))(x−(p+√q)) = 3x² − 6p·x + 3(p²−q) 을 적분해 f(x) = x³ − 3p·x² + 3(p²−q)·x.
    전개 계수(1, −3p, 3(p²−q), 0)는 전부 정수라 canonicalize·표기가 그대로 동작한다 — 답(임계점)만
    무리수다. 정수 극값 `_ExtremumSkeleton`과 별도 타입(무리수 답 계약을 정수 프로퍼티에 안 섞음).
    """

    p: int  # 임계점 정수부
    q: int  # 근호 안(비제곱 양수) — 임계점 p±√q
    kind: ExtremumKind

    @property
    def cubic_coeffs(self) -> tuple[int, int, int, int]:
        """f(x) 전개 계수 (a, b, c, d) — a x³ + b x² + c x + d. 상수항 d=0(극값 x좌표 무관)."""
        return 1, -3 * self.p, 3 * (self.p * self.p - self.q), 0

    @property
    def derivative_monic(self) -> tuple[int, int]:
        """monic 도함수 계수 (b', c') — x² + b'x + c'(= f'/3). 근 = 임계점 p±√q(정수계수)."""
        return -2 * self.p, self.p * self.p - self.q

    @property
    def smaller_root(self) -> sympy.Expr:
        """작은 임계점 p−√q의 SymPy 정확값."""
        return sympy.Integer(self.p) - sympy.sqrt(self.q)

    @property
    def larger_root(self) -> sympy.Expr:
        """큰 임계점 p+√q의 SymPy 정확값."""
        return sympy.Integer(self.p) + sympy.sqrt(self.q)

    @property
    def answer_expr(self) -> sympy.Expr:
        """정답 임계점 — 선두계수 양수라 극대=작은 근 p−√q·극소=큰 근 p+√q."""
        return self.smaller_root if self.kind == "극대" else self.larger_root

    @property
    def answer_text(self) -> str:
        """정답 임계점 SymPy 정확값 표기 — sqrt quad 패밀리 규약 미러(예 '3 - sqrt(2)')."""
        return str(sympy.sstr(self.answer_expr))

    @property
    def selection(self) -> str:
        """근 선택 — 극대→smallest(작은 임계점)·극소→largest(큰 임계점). root_selection 검증."""
        return "smallest" if self.kind == "극대" else "largest"

    @property
    def difficulty(self) -> float:
        """rule-based 종합 난이도 — 극값 base + 무리근 가산(difficulty 모듈·정수 spread 미사용)."""
        _, b, c, _ = self.cubic_coeffs
        return estimate_difficulty_extremum_irrational(max_abs_coefficient=max(abs(b), abs(c)))


def _build_irrational_pool() -> tuple[_IrrationalExtremumSkeleton, ...]:
    """결정론 무리 임계점 극값 뼈대 풀 — p × q(비제곱) × {극대,극소} 열거·고정 시드 셔플.

    (도함수 monic, 선택) 중복은 빌드 시점에 제거한다(같은 (p,q)라도 극대/극소는 정답·선택이
    다른 별개 문제). 무리근 monic은 판별식 4q가 비제곱이라 정수 극값 풀의 정수근 monic과 근의
    체가 달라 signature가 애초에 서로소다(cross-군 오dedup 0·별도 밴드 index로 이중 방어).
    """
    pool: list[_IrrationalExtremumSkeleton] = []
    seen: set[tuple[int, int, str]] = set()
    for p in range(_IRR_P_MIN, _IRR_P_MAX + 1):
        for q in _IRR_QS:
            for kind in ("극대", "극소"):
                skeleton = _IrrationalExtremumSkeleton(p=p, q=q, kind=kind)
                key = (*skeleton.derivative_monic, skeleton.selection)
                if key not in seen:
                    seen.add(key)
                    pool.append(skeleton)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _irrational_extremum_steps(skeleton: _IrrationalExtremumSkeleton) -> list[str]:
    """무리 임계점 풀이의 검증 단계 체인(S2-02) — 도함수 전개형 → 3(x−p)²−3q 완전제곱형.

    q가 비제곱이라 유리계수 인수분해가 불가 — sqrt quad `_sqrt_steps`의 완전제곱꼴 규약을
    미러한다(전이는 다항 동치라 항상 correct — `verify_step` 실측 확인). p=0이면 두 표기가
    동일 문자열로 접히나(전이 trivially correct) 균일성을 위해 체인 형태를 유지한다."""
    p, q = skeleton.p, skeleton.q
    expanded = _sympy_quadratic_text(3, -6 * p, 3 * (p * p - q))
    completed = f"3*x**2 - {3 * q}" if p == 0 else f"3*({_linear_factor(p)})**2 - {3 * q}"
    return [expanded, completed]


def _irrational_explanation(skeleton: _IrrationalExtremumSkeleton) -> str:
    """무리 임계점 극값 해설 — 도함수 방정식을 풀어 x=p±√q 도출·부호 판정으로 극대/극소 확정."""
    small_text = sympy.sstr(skeleton.smaller_root)
    large_text = sympy.sstr(skeleton.larger_root)
    quad = _display_monic_quadratic(*skeleton.derivative_monic)
    which_val = "극댓값" if skeleton.kind == "극대" else "극솟값"
    return (
        f"f'(x)=0의 양변을 3으로 나누면 {quad} = 0 이므로 그 해는 x = {small_text}, "
        f"x = {large_text} 이다. 삼차항의 계수가 양수라 작은 근 x = {small_text}에서 극대, "
        f"큰 근 x = {large_text}에서 극소이다. "
        f"따라서 {which_val}을 갖는 x는 {skeleton.answer_text}이다."
    )


class CalculusIrrationalExtremumSkeletonGenerator:
    """미적분 무리 임계점 극값 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    임계점이 p±√q인 극값 x좌표를 낸다 — 도함수 계수는 정수라 정수 극값 생성기와 동일 좌석·게이트·
    근 선택 검증 스택을 공유하고, 답만 무리수라 sqrt quad 패밀리의 SymPy 정확값 표기를 미러한다.
    풀을 순서대로 소비(소진 시 None), `skip_signatures`로 기존 구조를 건너뛴다(회차 낭비 방지).
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-calc-extirr",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("CALC-EXTREMUM-IRR",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_irrational_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 무리 극값 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            condition = _derivative_condition(*skeleton.derivative_monic)
            if self._skip is not None:
                signature = canonical_signature(condition, skeleton.selection)
                if signature is not None and signature in self._skip:
                    continue
            return self._assemble(spec, skeleton, condition)
        return None

    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _IrrationalExtremumSkeleton, condition: str
    ) -> CandidateProblem:
        a, b, c, d = skeleton.cubic_coeffs
        fx = _display_cubic(a, b, c, d)
        answer_text = skeleton.answer_text
        templates = _TEMPLATES[skeleton.kind]
        question_text = templates[self._index % len(templates)].format(fx=fx)
        standard_codes = sorted(spec.achievement_standard_codes)
        slug = self._stable_slug(question_text, answer_text, standard_codes)

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
            answer_format=AnswerFormat.실수,  # 무리수 전용 형식 부재 — 실수 매핑(sqrt 패밀리 미러)
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=_irrational_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 무리 극값 스켈레톤 조립(임계점 p±√q→도함수 역산·적분)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # 도함수 방정식(정수계수·검산용·호출자 제공)
            answer_map={"x": answer_text},
            answer_selection=skeleton.selection,
            # S2-02: 완전제곱형 체인 방출(무리근은 인수분해 불가 — sqrt quad 규약 미러).
            solution_steps=_irrational_extremum_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        """결정론 안정 slug — 내용 해시(멱등 upsert 키·극값 생성기 규약 미러)."""
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"


# ── 미적분(접선 기울기) 형제 생성기 — f'(x)=m의 근(접점 x좌표) ──────────────
# 극값(f'=0)의 짝: "접선의 기울기가 m인 점"은 f'(x)=m의 근이다. 삼차함수의 f'는 이차식이라
# f'(x)=m은 이차방정식 → 두 접점 → 근 선택(큰/작은 x)으로 극값과 동일 검증 스택을 무변경
# 재사용한다. 개념은 미분계수(H:12미적Ⅰ02-01·미분계수=접선 기울기). m≠0(짝수)만 써서 극값
# (f'=0)과 구조적으로 구분한다(m=0이면 수평 접선=극값과 동치·조건 충돌).

TangentPick = Literal["큰", "작은"]

# 접선 기울기 값 — 0이 아닌 짝수만(f 정수계수 유지·극값과 구분). p+q가 짝수라 m 짝수면 c 정수.
_TANGENT_SLOPES: tuple[int, ...] = (-6, -4, -2, 2, 4, 6)

# 발문 템플릿(x좌표 큰/작은별·인덱스 회전). {fx}=삼차함수·{m}=접선 기울기.
_TANGENT_TEMPLATES: dict[TangentPick, tuple[str, ...]] = {
    "큰": (
        "곡선 y = f(x) = {fx} 위의 점 중 접선의 기울기가 {m}인 점의 x좌표가 큰 것을 구하시오.",
        "함수 f(x) = {fx} 의 그래프 위에서 접선의 기울기가 {m}인 두 점 중 x좌표가 큰 점의 "
        "x좌표를 구하시오.",
    ),
    "작은": (
        "곡선 y = f(x) = {fx} 위의 점 중 접선의 기울기가 {m}인 점의 x좌표가 작은 것을 구하시오.",
        "함수 f(x) = {fx} 의 그래프 위에서 접선의 기울기가 {m}인 두 점 중 x좌표가 작은 점의 "
        "x좌표를 구하시오.",
    ),
}


@dataclass(frozen=True, slots=True)
class _TangentSkeleton:
    """접선 기울기 뼈대 — 두 접점 (p<q)·같은 홀짝 + 기울기 m + 큰/작은. 수치의 단일 진실 원천.

    f'(x) = 3(x−p)(x−q) + m 이라 두 접점 x=p, x=q에서 접선 기울기가 m이다. 적분하면
    f(x) = x³ − (3(p+q)/2)x² + (3pq+m)x. p+q 짝수·m 짝수라 전개 계수 전부 정수. 검산 조건은
    f'(x)=m ⟺ 3(x−p)(x−q)=0의 monic x²−(p+q)x+pq=0(근 p,q·m 무관)이다.
    """

    p: int  # 작은 접점 x좌표
    q: int  # 큰 접점 x좌표 (p < q, p+q 짝수)
    m: int  # 접선 기울기 (0이 아닌 짝수)
    pick: TangentPick

    @property
    def cubic_coeffs(self) -> tuple[int, int, int, int]:
        """f(x) 전개 계수 (a, b, c, d) — a x³ + b x² + c x + d. c=3pq+m·d=0(접점 x좌표 무관)."""
        s = self.p + self.q  # 짝수(같은 홀짝 불변식)
        return 1, -(3 * s) // 2, 3 * self.p * self.q + self.m, 0

    @property
    def derivative_monic(self) -> tuple[int, int]:
        """monic 조건 계수 (b', c') — x² + b'x + c' (= (f'−m)/3). 근 = 접점 (p, q)."""
        return -(self.p + self.q), self.p * self.q

    @property
    def answer(self) -> int:
        """정답 접점 x좌표 — 큰=q·작은=p."""
        return self.q if self.pick == "큰" else self.p

    @property
    def selection(self) -> str:
        """근 선택 — 큰→largest·작은→smallest. verify_root_selection 검증."""
        return "largest" if self.pick == "큰" else "smallest"

    @property
    def difficulty(self) -> float:
        """rule-based 난이도 — 접점 간격·전개 계수 크기에서 추정(극값과 동일 동인·함수 재사용)."""
        _, b, c, _ = self.cubic_coeffs
        return estimate_difficulty_extremum(
            root_spread=self.q - self.p,
            max_abs_coefficient=max(abs(b), abs(c)),
        )


def _build_tangent_pool() -> tuple[_TangentSkeleton, ...]:
    """결정론 접선 뼈대 풀 — 같은 홀짝 접점 쌍 (p<q) × {큰, 작은} 열거·고정 시드 셔플.

    기울기 m은 (p,q)에서 결정론으로 고른다(0이 아닌 짝수·표시 변주만·조건 무관). 같은 (p,q)라도
    큰/작은은 다른 문제다(정답·선택 상이 — signature의 selection payload가 가른다). (조건, 선택)
    중복은 빌드 시점에 제거(m은 조건에 안 들어가 (p,q,선택)이 유효 키다).
    """
    pool: list[_TangentSkeleton] = []
    seen: set[tuple[int, int, str]] = set()
    for p in range(_CRIT_MIN, _CRIT_MAX + 1):
        for q in range(p + 1, _CRIT_MAX + 1):
            if (p + q) % 2 != 0:
                continue  # 홀짝 다르면 f x² 계수가 비정수 → 제외.
            m = _TANGENT_SLOPES[(abs(p * 7 + q * 13)) % len(_TANGENT_SLOPES)]  # 결정론·(p,q) 고정
            for pick in ("큰", "작은"):
                skeleton = _TangentSkeleton(p=p, q=q, m=m, pick=pick)
                key = (*skeleton.derivative_monic, skeleton.selection)
                if key not in seen:
                    seen.add(key)
                    pool.append(skeleton)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _tangent_steps(skeleton: _TangentSkeleton) -> list[str]:
    """접선 기울기 풀이의 검증 단계 체인(S2-02) — f' 전개형 → 3(x−p)(x−q)+m 정리형.

    두 표기는 다항 동치라 전이가 항상 correct(`verify_step` 실측 확인). 미분 전이는
    unverifiable(실측)이라 체인은 도함수 다항식에서 시작한다 — `_extremum_steps` 규약 동일."""
    p, q, m = skeleton.p, skeleton.q, skeleton.m
    expanded = _sympy_quadratic_text(3, -3 * (p + q), 3 * p * q + m)
    sign, mag = ("-", -m) if m < 0 else ("+", m)  # m ≠ 0 불변식(0 아닌 짝수 풀)
    factored = f"3*({_linear_factor(p)})*({_linear_factor(q)}) {sign} {mag}"
    return [expanded, factored]


def _tangent_explanation(skeleton: _TangentSkeleton) -> str:
    """접선 기울기 기반 해설 — 뼈대 수치에서 결정론 생성(f'=m 정리·근 선택·위생 청정)."""
    f1, f2 = _linear_factor(skeleton.p), _linear_factor(skeleton.q)
    which = "큰" if skeleton.pick == "큰" else "작은"
    return (
        f"f(x)를 미분해 접선의 기울기 조건 f'(x) = {skeleton.m}"
        f"{eul_reul(str(skeleton.m))} 정리하면 "
        f"3({f1})({f2}) = 0 이므로 접점의 x좌표는 x = {skeleton.p}, x = {skeleton.q} 이다. "
        f"이 중 x좌표가 {which} 것은 {skeleton.answer}이다."
    )


class CalculusTangentSlopeSkeletonGenerator:
    """미적분 접선 기울기 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    "접선의 기울기가 m인 점의 x좌표"를 낸다 — f'(x)=m의 근(접점)이라 극값 생성기와 동일 좌석·
    게이트·근 선택 검증 스택을 공유한다(하이브리드 분담). 풀을 순서대로 소비(소진 시 None),
    `skip_signatures`로 코퍼스 기존 구조를 건너뛴다(배치 재실행 회차 낭비 방지).
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-calc-tan",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("CALC-TANGENT",),
        concept_tags: Sequence[ConceptTag] = (
            ConceptTag(concept_src_id="H:12미적Ⅰ02-01", role="PRIMARY", relevance=0.95),
        ),
    ) -> None:
        self._pool = _build_tangent_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 접선 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            condition = _derivative_condition(*skeleton.derivative_monic)
            if self._skip is not None:
                signature = canonical_signature(condition, skeleton.selection)
                if signature is not None and signature in self._skip:
                    continue
            return self._assemble(spec, skeleton, condition)
        return None

    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _TangentSkeleton, condition: str
    ) -> CandidateProblem:
        a, b, c, d = skeleton.cubic_coeffs
        fx = _display_cubic(a, b, c, d)
        answer_text = str(skeleton.answer)
        templates = _TANGENT_TEMPLATES[skeleton.pick]
        question_text = templates[self._index % len(templates)].format(fx=fx, m=skeleton.m)
        standard_codes = sorted(spec.achievement_standard_codes)
        slug = self._stable_slug(question_text, answer_text, standard_codes)

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
            answer_explanation=_tangent_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 접선 스켈레톤 조립(접점→도함수 역산·적분)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # f'(x)=m의 근 방정식(검산용·호출자 제공)
            answer_map={"x": answer_text},
            answer_selection=skeleton.selection,
            # S2-02: f' 정리형 체인 방출 — 게이트 Tier2·상시 재검증·WH-S replay가 소비.
            solution_steps=_tangent_steps(skeleton),
            concept_tags=list(self._concept_tags),
        )

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        """결정론 안정 slug — 내용 해시(멱등 upsert 키·극값 생성기 규약 미러)."""
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"


# ── 미적분(극값의 값) 객관식 형제 생성기 — 극댓값/극솟값 4지선다 + 오개념 distractor ──
# 극값-값 단답형의 객관식 짝. 정답은 여전히 극값의 *값*(극댓값 v1·극솟값 v2)이라 값 환원(dummy x
# 이차방정식 근 선택)을 그대로 재사용해 검증한다 — MC가 더하는 것은 오답 선지 3종 + 오개념 태깅뿐.
# 4지선다 = 정렬된 {v1(극댓값), v2(극솟값), m(극대 x좌표), n(극소 x좌표)}(4값 상이할 때만 적격).
# 오답 귀속(quad MC의 반대근×1+부호반전×2 구조 미러·무모호): 정답 아닌 극값 → 극대·극소 혼동
# (extremum-max-min-confused), m·n(x좌표) → 극값의 값↔극점 x좌표 혼동(extremum-value-vs-point-
# confused). v1,v2는 값이라 x좌표 m,n과 섞이지 않는 게 곧 오개념 축(값 vs 좌표). op-code id는
# 하드코딩 0 — 조성 루트가 L4 정본에서 주입(생성자 distractor_codes·quad MC 규약 미러·계층 규칙).

# MC distractor 주입 키(생성자 distractor_codes의 필수 키·harness 조성 루트가 L4 id로 채운다).
_MC_KEY_MAX_MIN = "max_min"  # 정답 아닌 극값 선지 → 극대·극소 혼동
_MC_KEY_VALUE_VS_POINT = "value_vs_point"  # 극점 x좌표 선지 → 값↔좌표 혼동

# 발문 템플릿(극댓값/극솟값별·인덱스 회전). {fx}=삼차함수.
#
# **단답형 템플릿과 한 건도 공유하지 않는다** (QUAL-08·2026-09-13). 초판은 첫 템플릿이
# `_VALUE_TEMPLATES`의 첫 템플릿("삼차함수 f(x) = {fx} 의 극댓값을 구하시오.")과 글자 그대로
# 같았고, 두 생성기의 뼈대 풀이 (m,n,kind) 140쌍을 공유하므로 **같은 발문이 단답형·객관식
# 양쪽에서 생성됐다**(공간 전수 실측 22건 · 코퍼스 실재 4건 — `wm-calc-extv-bd21cd8484d2`와
# `wm-calc-extmc-bd21cd8484d2`는 해시 접미까지 같다). 선지가 있는 문항을 "구하시오"로 묻는
# 것 자체가 형식 불일치이기도 해, 객관식 템플릿은 전부 *선택 지시*로 통일한다.
# 동결: `tests/backend/l3/equivalent/test_calculus_extremum_format_disjointness.py`.
_MC_VALUE_TEMPLATES: dict[ExtremumKind, tuple[str, ...]] = {
    "극대": (
        "삼차함수 f(x) = {fx} 의 극댓값으로 옳은 것을 고르시오.",
        "함수 f(x) = {fx} 의 극댓값으로 옳은 것을 고르시오.",
        "삼차함수 f(x) = {fx} 가 극대일 때, 그 극댓값으로 옳은 것을 고르시오.",
    ),
    "극소": (
        "삼차함수 f(x) = {fx} 의 극솟값으로 옳은 것을 고르시오.",
        "함수 f(x) = {fx} 의 극솟값으로 옳은 것을 고르시오.",
        "삼차함수 f(x) = {fx} 가 극소일 때, 그 극솟값으로 옳은 것을 고르시오.",
    ),
}


def _build_mc_pool() -> tuple[_ExtremumValueSkeleton, ...]:
    """결정론 극값 MC 뼈대 풀 — 값 뼈대 중 4지선다 {v1,v2,m,n} 4값 상이만 수록·고정 시드 셔플.

    검산 조건(dummy x 이차방정식)은 값 뼈대와 동일하므로 dedup 키·orchestrator signature는 값
    생성기와 같은 (value_monic, 선택)이다 — 같은 극값 쌍을 내는 서로 다른 (m,n)은 조건이 같아
    orchestrator가 어차피 하나만 수용한다. 그래서 키당 *첫 4-상이 뼈대*만 수록(4지선다 자격 확보).
    """
    pool: list[_ExtremumValueSkeleton] = []
    seen: set[tuple[int, int, str]] = set()
    for m in range(_CRIT_MIN, _CRIT_MAX + 1):
        for n in range(m + 1, _CRIT_MAX + 1):
            if (m + n) % 2 != 0:
                continue  # 홀짝 다르면 f x² 계수가 비정수 → 제외.
            for kind in ("극대", "극소"):
                skeleton = _ExtremumValueSkeleton(m=m, n=n, kind=kind)
                v1, v2 = skeleton.extremum_values
                if len({v1, v2, m, n}) != 4:
                    continue  # 4지선다 부적격(값·x좌표 충돌) — 단답형 풀에 남는다.
                key = (*skeleton.value_monic, skeleton.selection)
                if key in seen:
                    continue  # 같은 조건 signature — orchestrator가 어차피 하나만 수용.
                seen.add(key)
                pool.append(skeleton)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


class CalculusExtremumMCSkeletonGenerator:
    """미적분 극값 객관식 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    "삼차함수의 극댓값/극솟값" 4지선다를 낸다 — 정답은 극값의 값이라 값 생성기와 동일 좌석·게이트·
    근 선택 검증을 공유하고, 오답 3종(반대 극값·극점 x좌표 2종)에 오개념을 태깅한다. 오개념·op-code
    id는 생성자 `distractor_codes`로 주입받는다(quad MC 규약 미러·L4 하드코딩 0·계층 규칙).
    """

    def __init__(
        self,
        distractor_codes: Mapping[str, tuple[str, str]],
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-calc-extmc",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("CALC-EXTREMUM-MC",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        missing = {_MC_KEY_MAX_MIN, _MC_KEY_VALUE_VS_POINT} - set(distractor_codes)
        if missing:
            raise ValueError(
                f"극값 MC distractor_codes 주입 키 누락: {sorted(missing)} "
                f"(필수 {_MC_KEY_MAX_MIN}·{_MC_KEY_VALUE_VS_POINT})"
            )
        self._distractor_codes = dict(distractor_codes)
        self._pool = _build_mc_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 극값 MC 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            condition = _derivative_condition(*skeleton.value_monic)
            if self._skip is not None:
                signature = canonical_signature(condition, skeleton.selection)
                if signature is not None and signature in self._skip:
                    continue
            return self._assemble(spec, skeleton, condition)
        return None

    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _ExtremumValueSkeleton, condition: str
    ) -> CandidateProblem:
        a, b, c, d = skeleton.cubic_coeffs
        fx = _display_cubic(a, b, c, d)
        v1, v2 = skeleton.extremum_values
        answer_value = skeleton.answer  # 극대→v1·극소→v2
        other_value = v2 if skeleton.kind == "극대" else v1  # 정답 아닌 극값(반대 극값)

        # 선지 값→오개념 op-key: 반대 극값=극대극소 혼동·m·n(x좌표)=값↔좌표 혼동.
        op_by_value: dict[int, str] = {
            other_value: _MC_KEY_MAX_MIN,
            skeleton.m: _MC_KEY_VALUE_VS_POINT,
            skeleton.n: _MC_KEY_VALUE_VS_POINT,
        }
        ordered = sorted({v1, v2, skeleton.m, skeleton.n})  # 4값(빌드 필터가 4-상이 보장)
        choices = [str(value) for value in ordered]
        answer_text = str(answer_value)

        distractor_map: list[DistractorEntry] = []
        for index, value in enumerate(ordered):
            if value == answer_value:
                continue  # 정답 선지는 distractor_map에서 제외(스키마 계약).
            misconception_id, op_code = self._distractor_codes[op_by_value[value]]
            distractor_map.append(
                DistractorEntry(
                    choice_index=index, misconception_id=misconception_id, op_code=op_code
                )
            )

        templates = _MC_VALUE_TEMPLATES[skeleton.kind]
        question_text = templates[self._index % len(templates)].format(fx=fx)
        standard_codes = sorted(spec.achievement_standard_codes)
        slug = self._stable_slug(question_text, answer_text, standard_codes)

        problem = Problem(
            problem_id=uuid.uuid5(uuid.NAMESPACE_URL, f"whymath:problem:{slug}"),
            slug=slug,
            source_type=SourceType.자체생성,
            curriculum_version=self._curriculum_version,
            valid_from_year=self._valid_from_year,
            subject=self._subject,
            unit_codes=list(self._unit_codes),
            difficulty_overall=skeleton.difficulty,
            question_format=QuestionFormat.객관식,
            answer_format=_answer_format(answer_value),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=choices,
            answer=answer_text,
            answer_explanation=_value_explanation(skeleton),
            distractor_map=distractor_map,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 극값 MC 스켈레톤 조립(극값 쌍·극점 x좌표 4지선다·오개념 태깅)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(오개념 귀속 교수학 검수)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # 극값 쌍의 이차방정식(dummy x·정답 검증용)
            answer_map={"x": answer_text},
            answer_selection=skeleton.selection,
            # S2-02: 도함수 인수분해 체인만(극값 대입은 비동치 전이 — 값 검증은 Tier1 몫).
            solution_steps=_extremum_steps(skeleton.m, skeleton.n),
            concept_tags=list(self._concept_tags),
        )

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        """결정론 안정 slug — 내용 해시(멱등 upsert 키·극값 생성기 규약 미러)."""
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"


# ── 미적분(극값의 값) 형제 생성기 — f(x*)=극댓값·극솟값(값 자체) ──────────────
# 극값 x좌표(f'=0의 근)의 짝: "극댓값/극솟값" 그 값이다(수능·내신 최빈출 형태 — x좌표보다 잦다).
# 핵심 통찰(재구현 0): 두 극값 v1=f(m)(극대·작은 임계점)·v2=f(n)(극소·큰 임계점)은 "f(x)=k가
# 중근을 갖는 k" — 즉 변수 k의 이차방정식 k²−(v1+v2)k+v1v2=0의 두 근이다. 선두계수 양수라
# v1>v2(극댓값>극솟값)가 항상 성립해(근 선택 well-defined) 극댓값=largest·극솟값=smallest로
# 극값 x좌표와 *동일한* 근 선택 검증 스택(verify_answer·verify_root_selection·derive_selected_root)
# 을 무변경 재사용한다 — conditions의 변수는 검산용 dummy(x). 개념은 극값과 같은 함수의 증가·감소
# 와 극대·극소(H:12미적Ⅰ02-07·[12미적Ⅰ-02-07]). m,n 정수·m+n 짝수라 f 정수계수 → v1,v2 정수.

# 발문 템플릿(극댓값/극솟값별·인덱스 회전). {fx}=삼차함수.
_VALUE_TEMPLATES: dict[ExtremumKind, tuple[str, ...]] = {
    "극대": (
        "삼차함수 f(x) = {fx} 의 극댓값을 구하시오.",
        "함수 f(x) = {fx} 의 극댓값을 구하시오.",
        "삼차함수 f(x) = {fx} 가 극대일 때, 그 극댓값을 구하시오.",
    ),
    "극소": (
        "삼차함수 f(x) = {fx} 의 극솟값을 구하시오.",
        "함수 f(x) = {fx} 의 극솟값을 구하시오.",
        "삼차함수 f(x) = {fx} 가 극소일 때, 그 극솟값을 구하시오.",
    ),
}


@dataclass(frozen=True, slots=True)
class _ExtremumValueSkeleton:
    """극값의 값 뼈대 — 두 임계점 (m<n)·같은 홀짝 + 극값 종류. 수치의 단일 진실 원천.

    f(x) = x³ − (3(m+n)/2)x² + 3mn·x 는 극값 x좌표 뼈대와 동일하다(같은 f). 다른 것은 *정답*:
    x좌표가 아니라 극값의 *값* v1=f(m)(극댓값)·v2=f(n)(극솟값)이다. 두 값은 변수 dummy x의 이차
    방정식 x²−(v1+v2)x+v1v2=0의 두 근이라 근 선택으로 검증된다(극댓값=largest·극솟값=smallest).
    """

    m: int  # 작은 임계점 (극대·선두계수 양수)
    n: int  # 큰 임계점 (극소), m < n, m+n 짝수
    kind: ExtremumKind

    @property
    def cubic_coeffs(self) -> tuple[int, int, int, int]:
        """f(x) 전개 계수 (a, b, c, d) — 극값 x좌표 뼈대와 동일한 f(상수항 d=0)."""
        s = self.m + self.n  # 짝수(같은 홀짝 불변식)
        return 1, -(3 * s) // 2, 3 * self.m * self.n, 0

    @property
    def extremum_values(self) -> tuple[int, int]:
        """(극댓값 v1=f(m), 극솟값 v2=f(n)) — f 정수계수·정수 임계점이라 정수. v1>v2 불변."""
        a, b, c, d = self.cubic_coeffs
        return (
            a * self.m**3 + b * self.m**2 + c * self.m + d,
            a * self.n**3 + b * self.n**2 + c * self.n + d,
        )

    @property
    def value_monic(self) -> tuple[int, int]:
        """검산 이차방정식(dummy x)의 monic 계수 (b', c') — x²+b'x+c'. 근 = {극댓값, 극솟값}."""
        v1, v2 = self.extremum_values
        return -(v1 + v2), v1 * v2

    @property
    def answer(self) -> int:
        """정답 극값 — 극대→극댓값 v1(작은 임계점의 f값)·극소→극솟값 v2(큰 임계점의 f값)."""
        v1, v2 = self.extremum_values
        return v1 if self.kind == "극대" else v2

    @property
    def selection(self) -> str:
        """근 선택 — 극대(극댓값)→largest·극소(극솟값)→smallest. v1>v2라 항상 정합."""
        return "largest" if self.kind == "극대" else "smallest"

    @property
    def difficulty(self) -> float:
        """rule-based 난이도 — 극값 x좌표와 동일 동인(임계점 간격·삼차 계수 크기·함수 재사용).

        값 계산(f 대입) 한 단계가 더 붙으나 산술 부담은 삼차 전개 계수 크기에 종속되므로 극값
        x좌표와 같은 입력으로 추정한다(추정 근거 일원화·난이도 대역 3.0~4.0 유지).
        """
        _, b, c, _ = self.cubic_coeffs
        return estimate_difficulty_extremum(
            root_spread=self.n - self.m,
            max_abs_coefficient=max(abs(b), abs(c)),
        )


def _build_value_pool() -> tuple[_ExtremumValueSkeleton, ...]:
    """결정론 극값-값 뼈대 풀 — 같은 홀짝 임계점 쌍 (m<n) × {극대, 극소} 열거·고정 시드 셔플.

    서로 다른 (m,n)이 같은 극값 쌍 {v1,v2}를 낼 수 있어(예 (2,6)·(−4,0) 모두 {32,0}) 검산 조건이
    동일하다 — 그럴 땐 오케스트레이터가 signature로 dedup하므로 실효 문제 수는 (조건, 선택) 쌍
    수다. 이를 빌드 시점에 (value_monic, 선택)으로 미리 접는다(orchestrator dedup과 정합).
    m+n 짝수만 수록(f 정수계수·v1,v2 정수 불변식).
    """
    pool: list[_ExtremumValueSkeleton] = []
    seen: set[tuple[int, int, str]] = set()
    for m in range(_CRIT_MIN, _CRIT_MAX + 1):
        for n in range(m + 1, _CRIT_MAX + 1):
            if (m + n) % 2 != 0:
                continue  # 홀짝 다르면 f x² 계수가 비정수 → 제외.
            for kind in ("극대", "극소"):
                skeleton = _ExtremumValueSkeleton(m=m, n=n, kind=kind)
                key = (*skeleton.value_monic, skeleton.selection)
                if key not in seen:
                    seen.add(key)
                    pool.append(skeleton)
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _value_explanation(skeleton: _ExtremumValueSkeleton) -> str:
    """극값의 값 해설 — 뼈대 수치에서 결정론 생성(f'=0 근·극대/극소 판정·대입 값·위생 청정)."""
    m, n = skeleton.m, skeleton.n
    f1, f2 = _linear_factor(m), _linear_factor(n)
    v1, v2 = skeleton.extremum_values
    if skeleton.kind == "극대":
        crit, val, which = m, v1, "극댓값"
    else:
        crit, val, which = n, v2, "극솟값"
    return (
        f"f'(x) = 3({f1})({f2}) 이므로 f'(x)=0의 해는 x = {m}, x = {n} 이다. "
        f"삼차항의 계수가 양수라 x = {m}에서 극대, x = {n}에서 극소이다. "
        f"따라서 {which}은 f({crit}) = {val} 이다."
    )


class CalculusExtremumValueSkeletonGenerator:
    """미적분 극값의 값 결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석(LLM 0).

    "삼차함수의 극댓값/극솟값"(값 자체)을 낸다 — 두 극값이 dummy x 이차방정식의 두 근이라 극값
    x좌표 생성기와 동일 좌석·게이트·근 선택 검증 스택을 공유한다(하이브리드 분담). 풀을 순서대로
    소비(소진 시 None), `skip_signatures`로 코퍼스 기존 구조를 건너뛴다(배치 재실행 회차 낭비 방지).
    """

    def __init__(
        self,
        *,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-calc-extv",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("CALC-EXTREMUM-VALUE",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_value_pool()
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 극값-값 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            condition = _derivative_condition(*skeleton.value_monic)
            if self._skip is not None:
                signature = canonical_signature(condition, skeleton.selection)
                if signature is not None and signature in self._skip:
                    continue
            return self._assemble(spec, skeleton, condition)
        return None

    def _assemble(
        self, spec: EquivalenceSpec, skeleton: _ExtremumValueSkeleton, condition: str
    ) -> CandidateProblem:
        a, b, c, d = skeleton.cubic_coeffs
        fx = _display_cubic(a, b, c, d)
        answer_text = str(skeleton.answer)
        templates = _VALUE_TEMPLATES[skeleton.kind]
        question_text = templates[self._index % len(templates)].format(fx=fx)
        standard_codes = sorted(spec.achievement_standard_codes)
        slug = self._stable_slug(question_text, answer_text, standard_codes)

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
            answer_explanation=_value_explanation(skeleton),
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 극값-값 스켈레톤 조립(임계점→도함수 역산·적분·극값 대입)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,  # 극값 쌍의 이차방정식(dummy x·검산용·호출자 제공)
            answer_map={"x": answer_text},
            answer_selection=skeleton.selection,
            # S2-02: 도함수 인수분해 체인만(극값 대입은 비동치 전이 — 값 검증은 Tier1 몫).
            solution_steps=_extremum_steps(skeleton.m, skeleton.n),
            concept_tags=list(self._concept_tags),
        )

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        """결정론 안정 slug — 내용 해시(멱등 upsert 키·극값 생성기 규약 미러)."""
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"
