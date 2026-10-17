"""파라메트릭 *스켈레톤* 동등문제 생성기 — S2-o(결정론 코어·LLM 0).

`EquivalentProblemGenerator` 좌석의 **결정론 구현**이다. LLM-first 생성기
(`llm_generator.LLMEquivalentProblemGenerator`)와 정반대로 문제의 수학적 실체를 **코드가 먼저
확정**한다: 근 (r₁, r₂)를 풀에서 고르고 → 방정식을 역산(전개)하고 → conditions·answer_map·
answer_selection·정답·해설을 전부 결정론으로 조립한다. 발문은 한국어 템플릿(회전 변주)이다.

왜(Phaiakes9 배치 실측·2026-07-06): LLM-first는 모델(qwen2.5:7b)의 좁은 레퍼토리 탓에 코퍼스
11건에서 포화 — 배치 60회 중 ~82%가 판박이 재생성으로 dedup에 버려지고 수율이 5~20%→0%로
붕괴했다. 스켈레톤은 근 조합을 코드가 순회하므로 **중복이 생성 자체가 안 되고**, 근을 코드가
고르므로 **틀린 근·복소근·반올림 소수도 원천 불가능**하다(외부 리뷰 P0-2 "root-orderable
generator를 결정론으로, LLM은 wording만" 채택 — 결정 로그 2026-07-05).

정직성·이중 방어: 생성물은 여전히 S2-a 게이트(Tier1 대입·근 선택·위생·동등성)를 통과해야
저장된다 — 생성기 자신을 신뢰하지 않는 파이프라인 원칙은 스켈레톤에도 동일하게 적용된다
(derive-and-verify가 이 생성기의 answer_map을 재유도·재확인하는 교차 검증이 공짜로 붙는다).

범위(v1·S2-p): 단일변수 이차방정식·근 선택(largest/smallest/unique) 문제. variant 4종(근유형 ×
발문형식 2×2) — `short_answer`(유리근 단답형: 정수근·기약 유리근·중근)·`sqrt`(무리근 단답형:
(x−p)²=q 완전제곱꼴·answer는 SymPy 정확값 'p ± sqrt(q)')·`multiple_choice`(유리근 4지선다)·
`sqrt_multiple_choice`(무리근 4지선다). 두 객관식 variant는 오답값(반대 근·부호 반전 근)을
코드가 정확히 알고, 오개념/op-code id는 생성자 `distractor_codes`로 *주입*받는다: L4 카탈로그
하드코딩 0·조성 루트 소관. 같은 (방정식,선택)
뼈대는 결정론 해시 파티션으로 **정확히 한 형식**에만 배정된다(canonical signature가 형식을
구분하지 않으므로 단답형·객관식 중복 시 dedup 충돌 — 원천 차단). 개념 태깅(기본 HK06
PRIMARY)·rule-based 난이도(difficulty 모듈)·결정론 problem_id(slug 기반 uuid5)는 결정론 저작.
novel 구조의 오개념 겨냥은 LLM-first 생성기와의 하이브리드 분담(두 생성기가 같은 좌석·같은
게이트를 공유). **LLM 발문 다양화**(스켈레톤이 확정한 수치를 못 바꾸는 rephrase 시임)는 후속
슬라이스다 — 템플릿 변주만으로도 구조 다양성(수백 조합)이 표면 단조로움을 상회한다.

7계층: L3 지역(생성=LLM 라우터 도메인이나 이 구현은 LLM 0 — 좌석 계약만 공유). schema(최하위)·
동일 패키지(canonicalize)만 import한다.
"""

from __future__ import annotations

import hashlib
import random
import re
import uuid
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from fractions import Fraction
from math import gcd
from typing import Literal

import sympy

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.canonicalize import canonical_signature
from whymath_backend.l3.equivalent.difficulty import RootKind, estimate_difficulty
from whymath_backend.l3.equivalent.generator import CandidateProblem, deterministic_generator
from whymath_backend.lang.josa import eul_reul, wa_gwa
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

__all__ = ["SkeletonEquivalentProblemGenerator"]

# 풀 셔플 고정 시드 — 같은 구성은 같은 출제 순서(재현·디버그). 비결정 난수 금지(verify 규약 미러).
_POOL_SEED = 20260706

# 기본 개념 태깅(S2-p) — 현 풀은 전부 단일변수 이차방정식의 근이라 개념이 결정론으로 정해진다.
# HK06 = 개념그래프 원천 src_id "이차방정식의 근(실근·허근)"([10공수1-02-02] 정착 —
# data/corpus/concept_graph_v1/concepts.jsonl). 다른 단원 스켈레톤은 생성자 주입으로 교체
# (unit_codes 기본값과 같은 선례 — L1 데이터 키라 L4 오개념 id 주입 원칙의 대상이 아니다).
_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="HK06", role="PRIMARY", relevance=0.95),
)

# 근 풀 범위 — 한국 중·고 수준의 "손으로 인수분해 가능한" 작은 유리근만(커리큘럼 상식 범위).
_INT_ROOT_MIN, _INT_ROOT_MAX = -9, 9
_RATIONAL_LEADS: tuple[int, ...] = (2, 3)
_RATIONAL_NUMERATORS: tuple[int, ...] = (-7, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 7)
_RATIONAL_PARTNER_MIN, _RATIONAL_PARTNER_MAX = -6, 6

# 무리근 풀 범위(S2-p) — (x−p)²=q 완전제곱꼴. q는 *비제곱* 양수만(제곱수면 유리근이 되어
# 유리근 풀과 구조 중복·무리근 취지 상실). p·q는 고1 "간단한 무리근" 손계산 범위.
_SQRT_P_MIN, _SQRT_P_MAX = -4, 4
_SQRT_QS: tuple[int, ...] = (2, 3, 5, 6, 7, 8, 10, 11, 12, 13)

# 생성 variant(S2-p) — 뼈대 풀·조립을 가른다(근유형 × 발문형식 2×2). short_answer=유리근 단답형
# (v0 기본), sqrt=무리근 단답형, multiple_choice=유리근 4지선다, sqrt_multiple_choice=무리근 4지선다
# (둘 다 distractor 오개념 태깅·distractor_codes 주입 필수).
GeneratorVariant = Literal["short_answer", "sqrt", "multiple_choice", "sqrt_multiple_choice"]

# distractor_codes 주입이 필수인 객관식 variant 집합(유리근·무리근 공통).
_MC_VARIANTS: frozenset[str] = frozenset({"multiple_choice", "sqrt_multiple_choice"})

# 객관식 distractor의 L3-지역 op키 — 오답값을 *코드가* 정확히 아는 두 오류연산. L4 카탈로그
# id(misconception_id·op_code)는 여기 하드코딩하지 않고 생성자 `distractor_codes`로 주입받는다
# (CLAUDE.md 오개념 독립 DB·preload 금지 — 조성 루트가 L4에서 읽어 주입, L3→L4 import 0).
_MC_OP_OPPOSITE = "opposite_root"  # 요구되지 않은 반대쪽 근을 선택
_MC_OP_SIGN_FLIP = "sign_flip"  # 인수 (x−a)=0에서 근 부호 반전(−근)
_MC_OP_KEYS: tuple[str, ...] = (_MC_OP_OPPOSITE, _MC_OP_SIGN_FLIP)

# 형식 파티션 해시 모듈러 — 대상 뼈대의 1/3을 객관식에 배정(나머지 단답형 풀에 잔류).
_MC_PARTITION_MOD = 3

# 객관식 발문 템플릿(선택별·인덱스 회전).
_MC_TEMPLATES: dict[str, tuple[str, ...]] = {
    "largest": (
        "이차방정식 {eq} 의 두 근 중 큰 근은?",
        "이차방정식 {eq} 의 두 근 중 더 큰 근을 고르시오.",
    ),
    "smallest": (
        "이차방정식 {eq} 의 두 근 중 작은 근은?",
        "이차방정식 {eq} 의 두 근 중 더 작은 근을 고르시오.",
    ),
}

# 발문 템플릿(선택별·인덱스 회전) — 표면 변주. {eq}에 사람이 읽는 방정식이 들어간다.
_TEMPLATES: dict[str, tuple[str, ...]] = {
    "largest": (
        "이차방정식 {eq} 의 두 근 중 큰 근을 구하시오.",
        "이차방정식 {eq} 의 두 근 중 더 큰 근의 값을 구하시오.",
        "이차방정식 {eq}{josa} 풀어 큰 근을 구하시오.",
    ),
    "smallest": (
        "이차방정식 {eq} 의 두 근 중 작은 근을 구하시오.",
        "이차방정식 {eq} 의 두 근 중 더 작은 근의 값을 구하시오.",
        "이차방정식 {eq}{josa} 풀어 작은 근을 구하시오.",
    ),
    "unique": (
        "이차방정식 {eq} 의 근을 구하시오.",
        "이차방정식 {eq} 의 중근을 구하시오.",
    ),
}


def _eq_trailing_josa(display_eq: str) -> str:
    """발문 '{eq}{josa} 풀어'의 을/를 — 방정식 표기의 마지막 정수(우변)를 수 읽기로 판별.

    display_eq는 항상 '… = 0'(이차 표준형)·'… = q'(완전제곱꼴) 꼴이라 마지막 정수가 조사를
    지배한다(예 '= 0'→0(영)→'을'·'= 13'→13(십삼)→'을'). 표기 마지막 정수를 뽑아 josa.eul_reul에
    위임한다(하드코딩 금지·값 기반 판별).
    """
    numbers = re.findall(r"-?\d+", display_eq)
    tail = numbers[-1] if numbers else "0"
    return eul_reul(tail)


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """문제 뼈대 — 인수 (a₁x−b₁)(a₂x−b₂)=0 과 근 선택. 모든 수치의 단일 진실 원천."""

    factors: tuple[tuple[int, int], tuple[int, int]]  # ((a1,b1),(a2,b2)) — aᵢ>0·기약
    selection: str  # largest / smallest / unique

    @property
    def coefficients(self) -> tuple[int, int, int]:
        """전개 계수 (a, b, c) — a x² + b x + c = 0. (a₁x−b₁)(a₂x−b₂) 전개."""
        (a1, b1), (a2, b2) = self.factors
        return a1 * a2, -(a1 * b2 + a2 * b1), b1 * b2

    @property
    def roots(self) -> tuple[Fraction, Fraction]:
        """근 (작은, 큰) 정렬 — 중근이면 같은 값 둘."""
        (a1, b1), (a2, b2) = self.factors
        pair = sorted((Fraction(b1, a1), Fraction(b2, a2)))
        return pair[0], pair[1]

    @property
    def answer_root(self) -> Fraction:
        """선택이 가리키는 정답 근 — largest=큰, smallest=작은, unique=유일(중근)."""
        small, large = self.roots
        return large if self.selection == "largest" else small

    @property
    def root_kind(self) -> RootKind:
        """난이도 추정용 근 유형 — 중근=double·분모>1 근 존재=rational·그 외=integer."""
        small, large = self.roots
        if small == large:
            return "double"
        if small.denominator > 1 or large.denominator > 1:
            return "rational"
        return "integer"

    @property
    def difficulty(self) -> float:
        """rule-based 종합 난이도(S2-p) — 뼈대 수치(근 유형·계수)에서 결정론 추정."""
        a, b, c = self.coefficients
        return estimate_difficulty(
            root_kind=self.root_kind,
            lead_coefficient=a,
            max_abs_coefficient=max(abs(a), abs(b), abs(c)),
        )


@dataclass(frozen=True, slots=True)
class _SqrtSkeleton:
    """무리근 뼈대(S2-p) — (x−p)² = q(q 비제곱 양수)·근 p±√q. 모든 수치의 단일 진실 원천.

    유리근 `_Skeleton`(인수 기반·Fraction 근)과 별도 타입 — Fraction 프로퍼티 계약을 건드리지
    않는다. 전개계수(1, −2p, p²−q)는 정수라 canonicalize(Poly)·skip signature가 그대로 동작한다.
    """

    p: int
    q: int
    selection: str  # largest / smallest — 두 근 p±√q는 항상 상이(q>0)라 unique 없음

    @property
    def coefficients(self) -> tuple[int, int, int]:
        """전개 계수 (1, −2p, p²−q) — x² − 2px + (p²−q) = 0."""
        return 1, -2 * self.p, self.p * self.p - self.q

    @property
    def answer_expr(self) -> sympy.Expr:
        """선택이 가리키는 정답 근의 SymPy 정확값 — largest=p+√q, smallest=p−√q."""
        offset = sympy.sqrt(self.q)
        base = sympy.Integer(self.p)
        expr: sympy.Expr = base + offset if self.selection == "largest" else base - offset
        return expr

    @property
    def difficulty(self) -> float:
        """rule-based 종합 난이도 — 근 유형 고정 irrational·선두계수 1."""
        a, b, c = self.coefficients
        return estimate_difficulty(
            root_kind="irrational",
            lead_coefficient=a,
            max_abs_coefficient=max(abs(a), abs(b), abs(c)),
        )


def _mc_choice_values(
    skeleton: _Skeleton,
) -> tuple[Fraction, Fraction, Fraction, Fraction] | None:
    """객관식 4지선다 값 (정답근, 반대근, −정답근, −반대근) — 4값 전부 상이할 때만(아니면 None).

    오답 3종은 전부 *코드가 정확히 아는* 오류연산의 결과다: 반대근(요구되지 않은 근 선택)·
    부호 반전 근 2종(인수 (x−a)=0을 x=−a로 읽음). 값 충돌(예: 근 {2,−2}·근 0 포함)이면 그
    뼈대는 객관식 부적격 — 값을 조작해 채우지 않고 단답형 풀에 남긴다(결정론 단순성).
    """
    if skeleton.selection not in ("largest", "smallest"):
        return None
    small, large = skeleton.roots
    answer = skeleton.answer_root
    opposite = small if answer == large else large
    values = (answer, opposite, -answer, -opposite)
    if len(set(values)) != 4:
        return None
    return values


def _assigned_format(skeleton: _Skeleton) -> Literal["short_answer", "multiple_choice"]:
    """뼈대당 형식 1개 결정론 배정 — 부적격은 단답형, 적격 중 해시 1/3만 객관식.

    canonical signature는 (방정식, 근 선택)만 보고 발문 형식을 모른다 — 같은 뼈대를 단답형·
    객관식 둘 다 내면 코퍼스 dedup이 뒤엣것을 버린다(회차 낭비·형식 커버리지 왜곡). 그래서
    형식을 뼈대 내용의 해시로 *한 번만* 결정한다(전 실행 결정론·두 variant 풀이 서로소).
    """
    if _mc_choice_values(skeleton) is None:
        return "short_answer"
    a, b, c = skeleton.coefficients
    digest = hashlib.sha256(f"{a},{b},{c},{skeleton.selection}".encode("utf-8")).hexdigest()
    return "multiple_choice" if int(digest, 16) % _MC_PARTITION_MOD == 0 else "short_answer"


def _sqrt_mc_choice_exprs(
    skeleton: _SqrtSkeleton,
) -> tuple[sympy.Expr, sympy.Expr, sympy.Expr, sympy.Expr] | None:
    """무리근 객관식 4지선다 식 (정답근, 반대근, 부호반전 정답, 부호반전 반대) — p≠0일 때만.

    (x−p)²=q의 두 근은 p±√q. 오답 3종은 코드가 아는 오류연산의 결과다: 반대근(요구되지 않은
    근·opposite-root-selected)·정수부 p의 부호 반전 2종((x−p)의 이동을 반대 부호로 읽음 —
    factor-sign-flip의 완전제곱꼴 대응). p=0이면 −p=p라 부호반전이 원본과 겹쳐 4값이 안 되므로
    객관식 부적격(None) — 단답형 풀에 남긴다.
    """
    if skeleton.p == 0:
        return None
    root = sympy.sqrt(skeleton.q)
    sign = 1 if skeleton.selection == "largest" else -1
    p = sympy.Integer(skeleton.p)
    answer: sympy.Expr = p + sign * root
    opposite: sympy.Expr = p - sign * root
    flip_answer: sympy.Expr = -p + sign * root
    flip_opposite: sympy.Expr = -p - sign * root
    exprs = (answer, opposite, flip_answer, flip_opposite)
    if len({sympy.sstr(e) for e in exprs}) != 4:  # pragma: no cover — p≠0이면 항상 4값(방어)
        return None
    return exprs


def _assigned_sqrt_format(skeleton: _SqrtSkeleton) -> Literal["sqrt", "sqrt_multiple_choice"]:
    """무리근 뼈대당 형식 1개 결정론 배정 — 유리근 `_assigned_format`의 무리근 대응.

    p=0(부호반전 불성립)은 단답형(sqrt), 적격(p≠0) 중 해시 1/3만 객관식. 유리근·무리근 풀은
    근의 체가 달라 signature가 애초에 서로소이므로, 이 파티션은 *무리근 풀 내부*에서 단답형·
    객관식이 같은 방정식을 중복 내지 않게 한다(dedup 충돌 차단).
    """
    if _sqrt_mc_choice_exprs(skeleton) is None:
        return "sqrt"
    digest = hashlib.sha256(
        f"sqrt:{skeleton.p},{skeleton.q},{skeleton.selection}".encode("utf-8")
    ).hexdigest()
    return "sqrt_multiple_choice" if int(digest, 16) % _MC_PARTITION_MOD == 0 else "sqrt"


def _sqrt_inner_text(p: int) -> str:
    """(x−p)의 사람이 읽는 안쪽 표기 — p 부호 반영('x - 1'·'x + 3'). p=0은 호출부에서 분기."""
    return f"x - {p}" if p > 0 else f"x + {-p}"


def _sqrt_display_equation(p: int, q: int) -> str:
    """완전제곱꼴의 사람이 읽는 방정식 — '(x - 1)^2 = 2'·'x^2 = 5'."""
    if p == 0:
        return f"x^2 = {q}"
    return f"({_sqrt_inner_text(p)})^2 = {q}"


def _sqrt_condition(p: int, q: int) -> str:
    """완전제곱꼴의 검산용 SymPy 등식 — 발문 표기를 그대로 전사(닫힌 DSL·맨 등식).

    전개형이 아니라 완전제곱꼴 원형을 담는 이유: conditions는 문제 진술의 구조 전사다
    (표현≠의미). canonicalize가 전개·정규화하므로 dedup·검증엔 차이가 없다(실측 확인).
    """
    if p == 0:
        return f"x**2 = {q}"
    return f"({_sqrt_inner_text(p)})**2 = {q}"


def _sqrt_answer_display(p: int, q: int, selection: str) -> str:
    """정답 근의 사람이 읽는 표기('1 + √2'·'-√5') — 해설 전용(answer 필드는 SymPy 표기)."""
    sign = "+" if selection == "largest" else "-"
    if p == 0:
        return f"√{q}" if selection == "largest" else f"-√{q}"
    return f"{p} {sign} √{q}"


def _fraction_text(value: Fraction) -> str:
    """Fraction → SymPy/표시 겸용 정확값 문자열('4/3'·'-6') — 반올림 소수 금지."""
    return (
        str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    )


def _term(coefficient: int, symbol: str, *, lead: bool = False) -> str:
    """계수 하나를 사람이 읽는 항으로 — 부호·1 생략 규칙(lead=선두 항은 + 없이)."""
    sign = "-" if coefficient < 0 else ("" if lead else "+")
    magnitude = abs(coefficient)
    body = symbol if magnitude == 1 and symbol else f"{magnitude}{symbol}"
    joint = " " if sign and not lead else ""
    return f"{sign}{joint}{body}" if lead else f"{sign} {body}"


def _display_equation(a: int, b: int, c: int) -> str:
    """전개 계수 → 사람이 읽는 방정식('3x^2 - 7x + 4 = 0') — 0 항 생략·1 계수 생략."""
    parts = [_term(a, "x^2", lead=True)]
    if b:
        parts.append(_term(b, "x"))
    if c:
        parts.append(_term(c, ""))
    return " ".join(parts) + " = 0"


def _sympy_equation(a: int, b: int, c: int) -> str:
    """전개 계수 → 검산용 SymPy 등식('3*x**2 - 7*x + 4 = 0') — 닫힌 DSL(맨 등식)."""
    parts = ["x**2" if a == 1 else f"{a}*x**2"]
    if b:
        parts.append(f"{'-' if b < 0 else '+'} {abs(b)}*x")
    if c:
        parts.append(f"{'-' if c < 0 else '+'} {abs(c)}")
    return " ".join(parts) + " = 0"


def _factor_text(a: int, b: int) -> str:
    """(a x − b) 인수의 사람이 읽는 표기 — 'x - 2'·'3x + 4'(b 부호 반영)."""
    head = "x" if a == 1 else f"{a}x"
    if b == 0:
        return head
    return f"{head} - {b}" if b > 0 else f"{head} + {abs(b)}"


def _sympy_factor_text(a: int, b: int) -> str:
    """(a x − b) 인수의 검산용 SymPy 표기 — 'x - 2'·'3*x + 4'(닫힌 DSL·`_factor_text`의 짝)."""
    head = "x" if a == 1 else f"{a}*x"
    if b == 0:
        return head
    return f"{head} - {b}" if b > 0 else f"{head} + {abs(b)}"


def _factoring_steps(skeleton: _Skeleton) -> list[str]:
    """유리근 풀이의 검증 단계 체인(S2-02) — 전개형 → 인수분해형(표현식 동치·Tier2 correct).

    풀이의 *검증 가능한 대수 골자*(인수분해)만 구조화한다 — 근 '선택'은 `answer_selection`이
    별도 검증(verify_root_selection)하고, 서술은 `answer_explanation`이 담당한다(표현≠의미).
    수용 게이트는 unverifiable 단계 0을 요구하므로(acceptance §verified) 체인 전 전이가
    SymPy로 증명 가능해야 한다 — 전개↔인수분해는 다항 동치라 항상 correct.
    """
    a, b, c = skeleton.coefficients
    (a1, b1), (a2, b2) = skeleton.factors
    expanded = _sympy_equation(a, b, c).removesuffix(" = 0")
    factored = f"({_sympy_factor_text(a1, b1)})*({_sympy_factor_text(a2, b2)})"
    return [expanded, factored]


def _sqrt_steps(skeleton: _SqrtSkeleton) -> list[str]:
    """무리근 풀이의 검증 단계 체인(S2-02) — 전개형 → 완전제곱꼴(표현식 동치·Tier2 correct).

    (x−p)²−q 는 x²−2px+(p²−q)와 다항 동치라 전이가 항상 correct다. p=0이면 두 표기가
    동일 문자열로 접히나(전이 trivially correct) 균일성을 위해 체인 형태를 유지한다.
    """
    p, q = skeleton.p, skeleton.q
    a, b, c = skeleton.coefficients
    expanded = _sympy_equation(a, b, c).removesuffix(" = 0")
    completed = f"x**2 - {q}" if p == 0 else f"({_sqrt_inner_text(p)})**2 - {q}"
    return [expanded, completed]


def _build_pool() -> tuple[_Skeleton, ...]:
    """결정론 스켈레톤 풀 — 정수근 쌍·기약 유리근·중근을 열거하고 고정 시드로 셔플.

    같은 방정식이라도 선택(largest/smallest)이 다르면 다른 문제다(정수근 쌍은 두 선택 모두 수록).
    (a, b, c, selection) 중복은 빌드 시점에 제거한다(풀 내 판박이 0 보장 — dedup은 코퍼스 대비
    방어로만 남는다).
    """
    pool: list[_Skeleton] = []
    seen: set[tuple[int, int, int, str]] = set()

    def _add(factors: tuple[tuple[int, int], tuple[int, int]], selection: str) -> None:
        skeleton = _Skeleton(factors=factors, selection=selection)
        key = (*skeleton.coefficients, selection)
        if key not in seen:
            seen.add(key)
            pool.append(skeleton)

    # ① 정수근 쌍 (r1 < r2)·a=1 — 큰 근/작은 근 문제 둘 다 수록.
    for r1 in range(_INT_ROOT_MIN, _INT_ROOT_MAX + 1):
        for r2 in range(r1 + 1, _INT_ROOT_MAX + 1):
            for selection in ("largest", "smallest"):
                _add(((1, r1), (1, r2)), selection)

    # ② 기약 유리근 (a₁x−b₁)(x−r) — 선두계수 2·3, b₁/a₁ 기약, 정수근 r과 상이. 선택은
    #    결정론 교대(합 홀짝) — 풀 크기 절제.
    for lead in _RATIONAL_LEADS:
        for numerator in _RATIONAL_NUMERATORS:
            if gcd(abs(numerator), lead) != 1:
                continue
            for partner in range(_RATIONAL_PARTNER_MIN, _RATIONAL_PARTNER_MAX + 1):
                if Fraction(numerator, lead) == partner:
                    continue  # pragma: no cover — 기약 분수는 정수와 못 겹침(방어)
                selection = "largest" if (numerator + partner) % 2 else "smallest"
                _add(((lead, numerator), (1, partner)), selection)

    # ③ 중근 (x−r)²·(2x−b)²(b 홀수) — 유일근 문제(unique).
    for r in range(_INT_ROOT_MIN, _INT_ROOT_MAX + 1):
        if r != 0:
            _add(((1, r), (1, r)), "unique")
    for b in (-7, -5, -3, -1, 1, 3, 5, 7):
        _add(((2, b), (2, b)), "unique")

    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


def _build_sqrt_pool() -> tuple[_SqrtSkeleton, ...]:
    """무리근 뼈대 풀(S2-p) — p×q×선택 전수 열거 후 고정 시드 셔플(9×10×2=180).

    q가 전부 비제곱이라 근은 항상 무리수·두 근은 항상 상이 — 유리근 풀과 구조(근의 체)가
    달라 signature 충돌이 원천 불가능하다. 선택은 largest/smallest 둘 다 수록(같은 방정식이라도
    선택이 다르면 다른 문제 — signature의 `#sel=` payload가 가른다).
    """
    pool = [
        _SqrtSkeleton(p=p, q=q, selection=selection)
        for p in range(_SQRT_P_MIN, _SQRT_P_MAX + 1)
        for q in _SQRT_QS
        for selection in ("largest", "smallest")
    ]
    random.Random(_POOL_SEED).shuffle(pool)
    return tuple(pool)


@deterministic_generator
class SkeletonEquivalentProblemGenerator:
    """결정론 스켈레톤 생성기 — `EquivalentProblemGenerator` 좌석 구현(S2-o·LLM 0).

    풀을 순서대로 소비하며 후보를 낸다(소진 시 None — 오케스트레이터가 generation_failed로
    정직 기록). `skip_signatures`에 이미 코퍼스에 있는 구조 signature 집합을 주면 해당 뼈대를
    건너뛴다 — 배치 재실행이 dedup 거부로 회차를 낭비하지 않게 한다(오케스트레이터의
    `signature_index`와 같은 set을 공유하면 회차 간 증분도 자동 반영).
    """

    def __init__(
        self,
        *,
        variant: GeneratorVariant = "short_answer",
        distractor_codes: Mapping[str, tuple[str, str]] | None = None,
        skip_signatures: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-skel",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("QUAD-EQ",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        if variant in _MC_VARIANTS:
            provided = distractor_codes or {}
            missing = [key for key in _MC_OP_KEYS if not provided.get(key)]
            if missing:
                # fail-fast(조용한 무매핑 금지) — 객관식은 오답→오개념 역추적이 존재 이유라
                # 매핑 없는 조립을 허용하지 않는다. id는 조성 루트가 L4 카탈로그에서 읽어
                # 주입한다(llm_generator._acceptable_misconceptions 주입 선례 미러).
                raise ValueError(
                    f"{variant} variant는 distractor_codes 주입이 필수입니다 — "
                    f"누락 op키: {missing} (op키→(misconception_id, op_code))"
                )
        self._pool: tuple[_Skeleton | _SqrtSkeleton, ...]
        if variant in ("sqrt", "sqrt_multiple_choice"):
            self._pool = tuple(s for s in _build_sqrt_pool() if _assigned_sqrt_format(s) == variant)
        else:
            wanted = "multiple_choice" if variant == "multiple_choice" else "short_answer"
            self._pool = tuple(s for s in _build_pool() if _assigned_format(s) == wanted)
        self._variant = variant
        self._distractor_codes = dict(distractor_codes or {})
        self._index = 0
        self._skip = skip_signatures
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    # ── EquivalentProblemGenerator 좌석 ────────────────────────────────
    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 뼈대를 후보로 조립 — skip 집합에 있는 구조는 건너뛰고, 풀 소진 시 None."""
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            if self._skip is not None:
                a, b, c = skeleton.coefficients
                signature = canonical_signature(_sympy_equation(a, b, c), skeleton.selection)
                if signature is not None and signature in self._skip:
                    continue  # 이미 코퍼스에 있는 구조 — 회차 낭비 없이 다음 뼈대로.
            if isinstance(skeleton, _SqrtSkeleton):
                if self._variant == "sqrt_multiple_choice":
                    return self._assemble_sqrt_mc(spec, skeleton)
                return self._assemble_sqrt(spec, skeleton)
            if self._variant == "multiple_choice":
                return self._assemble_mc(spec, skeleton)
            return self._assemble(spec, skeleton)
        return None

    # ── 조립(전부 결정론·수치의 단일 진실 원천은 뼈대) ─────────────────
    def _assemble(self, spec: EquivalenceSpec, skeleton: _Skeleton) -> CandidateProblem:
        a, b, c = skeleton.coefficients
        display_eq = _display_equation(a, b, c)
        answer_text = _fraction_text(skeleton.answer_root)
        templates = _TEMPLATES[skeleton.selection]
        return self._build_candidate(
            spec,
            question_text=templates[self._index % len(templates)].format(
                eq=display_eq, josa=_eq_trailing_josa(display_eq)
            ),
            answer_text=answer_text,
            explanation=self._explanation(skeleton),
            answer_format=self._answer_format(skeleton.answer_root),
            difficulty=skeleton.difficulty,
            condition=_sympy_equation(a, b, c),
            selection=skeleton.selection,
            steps=_factoring_steps(skeleton),
        )

    def _assemble_sqrt(self, spec: EquivalenceSpec, skeleton: _SqrtSkeleton) -> CandidateProblem:
        """무리근 조립(S2-p) — answer는 SymPy 정확값 문자열('1 + sqrt(2)').

        `sympy.sstr(answer_expr)`는 `derive_selected_root`의 반환 규약과 문자열까지 정확히
        일치한다(실측 확인) — 교차 검증(②)이 무리근에도 그대로 성립한다.
        """
        display_eq = _sqrt_display_equation(skeleton.p, skeleton.q)
        answer_text = str(sympy.sstr(skeleton.answer_expr))
        templates = _TEMPLATES[skeleton.selection]
        return self._build_candidate(
            spec,
            question_text=templates[self._index % len(templates)].format(
                eq=display_eq, josa=_eq_trailing_josa(display_eq)
            ),
            answer_text=answer_text,
            explanation=self._sqrt_explanation(skeleton),
            answer_format=AnswerFormat.실수,  # 무리수 전용 형식 부재 — 실수로 정직 매핑
            difficulty=skeleton.difficulty,
            condition=_sqrt_condition(skeleton.p, skeleton.q),
            selection=skeleton.selection,
            steps=_sqrt_steps(skeleton),
        )

    def _assemble_sqrt_mc(self, spec: EquivalenceSpec, skeleton: _SqrtSkeleton) -> CandidateProblem:
        """무리근 객관식 조립(S2-p 후속) — 4지선다(정답근·반대근·±부호반전)·전 선지 오개념 태깅.

        선지·answer는 SymPy 정확값 문자열(sstr — 단답형 무리근과 동일 표기·`derive_selected_root`
        규약 정합). 선지는 수치(evalf) 오름차순 정렬(결정론). 유리근 객관식과 동일하게 오답 3선지
        전부가 주입된 두 오개념으로 태깅되어 밴드 스펙 Jaccard 1.0 고정.
        """
        exprs = _sqrt_mc_choice_exprs(skeleton)
        if exprs is None:  # pragma: no cover — 풀 필터(_assigned_sqrt_format)가 부적격을 배제
            raise RuntimeError(f"무리근 객관식 부적격 뼈대가 풀에 유입: {skeleton}")
        answer_expr, opposite_expr, flip_answer_expr, flip_opposite_expr = exprs
        ordered = sorted(exprs, key=lambda expr: float(expr.evalf()))
        choices = [str(sympy.sstr(expr)) for expr in ordered]
        answer_text = str(sympy.sstr(answer_expr))

        op_by_expr: dict[sympy.Expr, str] = {
            opposite_expr: _MC_OP_OPPOSITE,
            flip_answer_expr: _MC_OP_SIGN_FLIP,
            flip_opposite_expr: _MC_OP_SIGN_FLIP,
        }
        distractor_map: list[DistractorEntry] = []
        for index, expr in enumerate(ordered):
            if expr == answer_expr:
                continue  # 정답 선지는 distractor_map에서 제외(스키마 계약).
            misconception_id, op_code = self._distractor_codes[op_by_expr[expr]]
            distractor_map.append(
                DistractorEntry(
                    choice_index=index, misconception_id=misconception_id, op_code=op_code
                )
            )

        display_eq = _sqrt_display_equation(skeleton.p, skeleton.q)
        templates = _MC_TEMPLATES[skeleton.selection]
        return self._build_candidate(
            spec,
            question_text=templates[self._index % len(templates)].format(
                eq=display_eq, josa=_eq_trailing_josa(display_eq)
            ),
            answer_text=answer_text,
            explanation=self._sqrt_explanation(skeleton),
            answer_format=AnswerFormat.실수,  # 무리수 전용 형식 부재 — 실수로 정직 매핑
            difficulty=skeleton.difficulty,
            condition=_sqrt_condition(skeleton.p, skeleton.q),
            selection=skeleton.selection,
            question_format=QuestionFormat.객관식,
            choices=choices,
            distractor_map=distractor_map,
            steps=_sqrt_steps(skeleton),
        )

    def _assemble_mc(self, spec: EquivalenceSpec, skeleton: _Skeleton) -> CandidateProblem:
        """객관식 조립(S2-p) — 4지선다(정답근·반대근·±부호반전근)·distractor 전 선지 오개념 태깅.

        선지는 값 오름차순 정렬(결정론), answer는 선지 *값* 문자열(시드 wm-quad-eq-root-count-mc
        패턴 미러 — 인덱스 아님). 오답 3선지 전부가 주입된 두 오개념으로 태깅되므로 후보의
        오개념 집합은 항상 주입 집합과 일치 — 밴드 스펙 Jaccard가 1.0으로 고정된다(부분 방출
        경로 없음·0.85 경계 비접촉).
        """
        values = _mc_choice_values(skeleton)
        if values is None:  # pragma: no cover — 풀 필터(_assigned_format)가 부적격을 배제
            raise RuntimeError(f"객관식 부적격 뼈대가 풀에 유입: {skeleton}")
        answer_value, opposite_value = values[0], values[1]
        ordered = sorted(values)
        choices = [_fraction_text(value) for value in ordered]
        answer_text = _fraction_text(answer_value)

        op_by_value: dict[Fraction, str] = {
            opposite_value: _MC_OP_OPPOSITE,
            -answer_value: _MC_OP_SIGN_FLIP,
            -opposite_value: _MC_OP_SIGN_FLIP,
        }
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

        a, b, c = skeleton.coefficients
        display_eq = _display_equation(a, b, c)
        templates = _MC_TEMPLATES[skeleton.selection]
        return self._build_candidate(
            spec,
            question_text=templates[self._index % len(templates)].format(
                eq=display_eq, josa=_eq_trailing_josa(display_eq)
            ),
            answer_text=answer_text,
            explanation=self._explanation(skeleton),
            answer_format=self._answer_format(skeleton.answer_root),
            difficulty=skeleton.difficulty,
            condition=_sympy_equation(a, b, c),
            selection=skeleton.selection,
            question_format=QuestionFormat.객관식,
            choices=choices,
            distractor_map=distractor_map,
            steps=_factoring_steps(skeleton),
        )

    def _build_candidate(
        self,
        spec: EquivalenceSpec,
        *,
        question_text: str,
        answer_text: str,
        explanation: str,
        answer_format: AnswerFormat,
        difficulty: float,
        condition: str,
        selection: str,
        question_format: QuestionFormat = QuestionFormat.단답형,
        choices: list[str] | None = None,
        distractor_map: list[DistractorEntry] | None = None,
        steps: list[str] | None = None,
    ) -> CandidateProblem:
        """뼈대 종류 공통 후보 조립 — Problem·Provenance·CandidateProblem(전부 결정론)."""
        standard_codes = sorted(spec.achievement_standard_codes)
        slug = self._stable_slug(question_text, answer_text, standard_codes)

        problem = Problem(
            # 결정론 problem_id — slug(내용 해시) 기반 uuid5. 재생성이 같은 내용이면 같은 id
            # (코퍼스 전면 재생성의 바이트 동일성·멱등 upsert 키와 정합). uuid4 기본값은
            # 실행마다 달라져 결정론 배치 CLI의 재실행 diff를 오염시킨다.
            problem_id=uuid.uuid5(uuid.NAMESPACE_URL, f"whymath:problem:{slug}"),
            slug=slug,
            source_type=SourceType.자체생성,  # 저작권 구조적 강제(자작 뼈대·본문성 원본 0)
            curriculum_version=self._curriculum_version,
            valid_from_year=self._valid_from_year,
            subject=self._subject,
            unit_codes=list(self._unit_codes),
            # S2-p: 스펙 미러(2.5 균일) → rule-based 결정론 추정(difficulty 모듈 공식).
            # 스펙 2.5 대비 최대 gap 1.1 < 3.5(게이트 감쇠 수학)라 동등성 성분 안전.
            difficulty_overall=difficulty,
            question_format=question_format,
            answer_format=answer_format,
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=choices,
            answer=answer_text,
            answer_explanation=explanation,
            distractor_map=distractor_map,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 스켈레톤 조립(근→방정식 역산·S2-o)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,
            answer_map={"x": answer_text},
            answer_selection=selection,
            # S2-02: 생성기가 아는 풀이 경로(전개↔인수분해/완전제곱)를 구조 단계로 방출 —
            # 수용 게이트 Tier2·상시 재검증(corpus_reverify)·WH-S replay가 소비한다.
            solution_steps=steps,
            concept_tags=list(self._concept_tags),  # S2-p: 결정론 개념 태깅(기본 HK06 PRIMARY)
        )

    @staticmethod
    def _sqrt_explanation(skeleton: _SqrtSkeleton) -> str:
        """완전제곱꼴 해설 — 뼈대 수치에서 결정론 생성(√ 표기는 사람 가독·위생 실측 청정)."""
        p, q = skeleton.p, skeleton.q
        which = "큰" if skeleton.selection == "largest" else "작은"
        answer_disp = _sqrt_answer_display(p, q, skeleton.selection)
        if p == 0:
            return f"x^2 = {q} 이므로 x = ±√{q} 이다. 이 중 {which} 근은 {answer_disp}이다."
        inner = _sqrt_inner_text(p)
        return (
            f"완전제곱꼴에서 {inner} = ±√{q} 이므로 x = {p} ± √{q} 이다. "
            f"이 중 {which} 근은 {answer_disp}이다."
        )

    @staticmethod
    def _explanation(skeleton: _Skeleton) -> str:
        """인수분해 기반 해설 — 뼈대 수치에서 결정론 생성(손저작 코퍼스 문체 미러·위생 청정)."""
        (a1, b1), (a2, b2) = skeleton.factors
        f1, f2 = _factor_text(a1, b1), _factor_text(a2, b2)
        small, large = skeleton.roots
        if skeleton.selection == "unique":
            return (
                f"좌변을 인수분해하면 ({f1})^2 = 0 이므로 근은 {_fraction_text(small)} "
                "(중근) 하나뿐이다."
            )
        which = "큰" if skeleton.selection == "largest" else "작은"
        # 와/과는 선행 근(작은 근)의 한국어 읽기 받침으로 결정 — 분수는 분모먼저 읽어 분자(읽기의
        # 마지막 음절)가 지배하므로 numerator를 토큰으로 넘긴다(정수근은 numerator=정수 자신).
        return (
            f"좌변을 인수분해하면 ({f1})({f2}) = 0 이고, 두 근은 "
            f"{_fraction_text(small)}{wa_gwa(str(small.numerator))} "
            f"{_fraction_text(large)}이다. 이 중 {which} 근은 "
            f"{_fraction_text(skeleton.answer_root)}이다."
        )

    @staticmethod
    def _answer_format(root: Fraction) -> AnswerFormat:
        """정답 근의 형태 — 양의 정수=자연수·기약 분수=분수·그 외(음의 정수 등)=실수."""
        if root.denominator == 1:
            return AnswerFormat.자연수 if root.numerator > 0 else AnswerFormat.실수
        return AnswerFormat.분수

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        """결정론 안정 slug — 내용 해시(멱등 upsert 키·llm_generator._stable_slug 규약 미러)."""
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"
