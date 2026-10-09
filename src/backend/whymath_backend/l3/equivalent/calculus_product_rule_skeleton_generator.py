"""대학 미적분학 I 곱의 미분법 결정론 스켈레톤 생성기 — W2 대학 축 최초 착점(결정론·LLM 0).

학년축 최단경로 계획(`docs/strategy/grade_axis_mvp_shortest_path_v1.md`) §3 W2. 실측
(2026-08-05): 문제은행 코퍼스에 대학 태깅 문항이 0건이었다(W1 리포트 §1.5) — 4축 중
마지막 미착수축이다. `ElementaryAddSubSkeletonGenerator`(초등)·`MatrixOpsSkeletonGenerator`
(고등 행렬) 선례를 그대로 따라 새 도메인에 새 생성기 1종을 짓는다 — 좌석·게이트 무변경 재사용.

대상 성취기준: `[CALC1-02-02]`(곱의 미분법 — (fg)'=f'g+fg'). 원자 백본: `CALC1-P06`
("곱의 미분은 미분의 곱이 아니다").

**검증 설계(중요·2026-08-05 실측 스파이크)**: Tier1(`l3/verify_answer`)에 `Derivative(...)`를
그대로 주면(`.doit()` 없이) `unverifiable`이 난다 — sympify가 미분 연산자를 *평가되지 않은
채* 남겨서 수치 대입이 실패한다. `.doit()`로 명시 평가해야 `pass`/`fail`이 정확히 갈린다
(오답 주입 스파이크로 변별력 확인). 조건은 `"Derivative(f(x), x).doit().subs(x, k) = y"`
형태 — Tier1이 방정식 sympify 기반 범용 검산기라는 실측(초등·행렬과 동일 결론)이 미분에도
그대로 확장된다(도메인 전용 검증기 신설 0).

문제: f(x) = (a·x² + b·x + c)(d·x + e) — 이차식과 일차식의 곱. f'(k)를 구한다. 단순
전개-후-미분과 곱의 미분법이 같은 값을 내므로(수학적으로 항등) 어느 경로로 풀든 채점은
같다 — 이는 검증 설계의 한계가 아니라 미분 자체의 성질이다(다른 모든 미분 생성기도 동형).

**개념 태깅 공백(중요·실측 발견)**: 이 문항의 개념(`CALC1-P06`)은 원자 백본에만 있고 구
437 legacy 개념그래프 코퍼스(HK06·A2·HK43 등 기존 생성기가 쓰는 공간)에는 없다.
`ConceptTag.concept_src_id`의 유일 해석 경로가 그 legacy 코퍼스→크로스워크→원자 UUID이므로
(`l1/problem_bank/populate.py` "원자 백본 재연결" 참조), 이 경로로는 대학 원자를 가리킬
방법이 없다 — 가짜 src_id를 넣으면 조용히 orphan skip(정직 회계 위반)이라 이 생성기는
`concept_tags=()`로 정직하게 비워 둔다. 원자 네이티브 태깅 경로 신설은 이 슬라이스 범위
밖(후속 U-계열 태스크 — `problem_concept` 적재가 원자 코드를 직접 받는 별도 seam 필요).

**노출 게이팅**: 선행 생성기와 동일 원칙 — 산출물은 v0(사람 검수 전), AI 검수(Wilson
게이트)는 실 LLM 필요라 이 환경 밖(Kiki 머신)에서만 가능하다. 그 전까지
`is_published=False`로 유지.
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

__all__ = ["CalculusProductRuleSkeletonGenerator"]

# 대학 커리큘럼(Curriculum enum에 값 없음 — W0에서 커리큘럼 오버레이만 확장했지 Problem.
# curriculum_version 열거값은 K-12 개정 축이라 대학 문항은 이 필드 의미가 없다. 기존
# REVISION_2022를 그대로 쓰지 않고 *가장 가까운* 값을 억지로 고르지 않기 위해, 대학 세부
# 코드(valid_from_year=2022·표기 그대로)로 자기서술만 남긴다 — 필드 자체의 재정의는 범위 밖.
_UNIVERSITY_CURRICULUM = Curriculum.REVISION_2022

_A_MIN, _A_MAX = -4, 4  # 이차항 계수(0 제외 — 진짜 이차식이어야 함)
_BC_MIN, _BC_MAX = -5, 5
_D_MIN, _D_MAX = -4, 4  # 일차항 계수(0 제외 — 진짜 일차식이어야 함)
_E_MIN, _E_MAX = -5, 5
_K_MIN, _K_MAX = -3, 3  # 평가점

_POOL_TARGET_SIZE = 300  # 조합공간이 매우 크므로(6자리 정수) 전수열거 대신 시드 샘플.

_TEMPLATES: tuple[str, ...] = (
    "f(x) = {f}일 때, f'({k})의 값을 구하시오.",
    "함수 f(x) = {f}의 도함수 f'(x)에 대하여 f'({k}){eul_k} 구하시오.",
)


def _term(coefficient: int, symbol: str, *, lead: bool = False) -> str:
    """계수 하나를 사람이 읽는 항으로 — 부호·계수 1 생략 규칙(`skeleton_generator._term`과
    동형 로직의 독립 구현·private 모듈 경계를 넘지 않기 위해 재구현, 신규 규칙 발명 0)."""
    sign = "-" if coefficient < 0 else ("" if lead else "+")
    magnitude = abs(coefficient)
    body = symbol if magnitude == 1 and symbol else f"{magnitude}{symbol}"
    joint = " " if sign and not lead else ""
    return f"{sign}{joint}{body}" if lead else f"{sign} {body}"


def _quad_display(a: int, b: int, c: int) -> str:
    """이차식 표기('3x^2 - 7x + 4') — 0항 생략·계수 1 생략(괄호 없이, 인수 표기는 호출자가 묶음)."""
    parts = [_term(a, "x^2", lead=True)]
    if b:
        parts.append(_term(b, "x"))
    if c:
        parts.append(_term(c, ""))
    return " ".join(parts)


def _linear_display(d: int, e: int) -> str:
    """일차식 표기('2x - 3') — 계수 1 생략(괄호 없이)."""
    parts = [_term(d, "x", lead=True)]
    if e:
        parts.append(_term(e, ""))
    return " ".join(parts)


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """문제 뼈대 — f(x)=(ax²+bx+c)(dx+e)의 계수·평가점 k. 수치의 단일 원천."""

    a: int
    b: int
    c: int
    d: int
    e: int
    k: int

    @property
    def condition(self) -> str:
        quad = f"{self.a}*x**2 + {self.b}*x + {self.c}"
        lin = f"{self.d}*x + {self.e}"
        return f"Derivative(({quad}) * ({lin}), x).doit().subs(x, {self.k}) = y"

    @property
    def result(self) -> int:
        """독립 재계산(곱의 미분법 전개식) — 생성기 스스로도 SymPy에 의존하지 않는 이중 확인.

        f'(x) = (2ax+b)(dx+e) + (ax²+bx+c)·d 를 그대로 정수 산술로 평가한다(생성기와 검증
        경로가 *다른* 코드를 타야 저작 결함이 실제로 드러난다 — Tier1도 독립적으로 SymPy
        미분을 재계산하므로 이중 교차검증이 된다).
        """
        a, b, c, d, e, k = self.a, self.b, self.c, self.d, self.e, self.k
        f1_prime_at_k = 2 * a * k + b
        f2_at_k = d * k + e
        f1_at_k = a * k * k + b * k + c
        f2_prime = d
        return f1_prime_at_k * f2_at_k + f1_at_k * f2_prime

    @property
    def display_f(self) -> str:
        """f(x)의 사람이 읽는 표기('(3x^2 - 7x + 4)(2x - 1)') — 0항·계수 1 생략."""
        return f"({_quad_display(self.a, self.b, self.c)})({_linear_display(self.d, self.e)})"


def _build_pool() -> tuple[_Skeleton, ...]:
    """시드 샘플 풀 — 조합공간이 6자리 정수라 전수열거 대신 결정론 샘플링(중복 제거)."""
    rng = random.Random(20260805)
    pool: list[_Skeleton] = []
    seen: set[tuple[int, ...]] = set()
    attempts = 0
    while len(pool) < _POOL_TARGET_SIZE and attempts < _POOL_TARGET_SIZE * 30:
        attempts += 1
        a = rng.choice([v for v in range(_A_MIN, _A_MAX + 1) if v != 0])
        b = rng.randint(_BC_MIN, _BC_MAX)
        c = rng.randint(_BC_MIN, _BC_MAX)
        d = rng.choice([v for v in range(_D_MIN, _D_MAX + 1) if v != 0])
        e = rng.randint(_E_MIN, _E_MAX)
        k = rng.randint(_K_MIN, _K_MAX)
        key = (a, b, c, d, e, k)
        if key in seen:
            continue
        seen.add(key)
        pool.append(_Skeleton(a=a, b=b, c=c, d=d, e=e, k=k))
    random.Random(20260805 + 1).shuffle(pool)
    return tuple(pool)


@deterministic_generator
class CalculusProductRuleSkeletonGenerator:
    """결정론 스켈레톤 생성기 — 대학 미적분학 I 곱의 미분법(`EquivalentProblemGenerator` 좌석).

    `MatrixOpsSkeletonGenerator`(2026-08-05 elementary_addsub 실측 사고 처방 계승)와 동일
    관례: `run_batch`가 아니라 `run_equivalent_generation`을 `signature_index=None`으로
    호출해야 한다(산술/미분 조건의 구조 dedup이 해값 기반이라 서로 다른 다항식 조합이 같은
    f'(k) 값을 내면 오탐 — `harness/university_calc1_batch.py` 참조). 이 생성기는 밴드
    분리가 필요 없는 단일 변형이라(§ 모듈 docstring — 문제 유형 1종) `operation` 필터가
    불필요하다(elementary_addsub/matrix_ops와 달리 배치가 밴드를 나누지 않음).
    """

    def __init__(
        self,
        *,
        skip_conditions: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-calc1-product-rule",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = _UNIVERSITY_CURRICULUM,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("CALC1-PRODUCT-RULE",),
        concept_tags: Sequence[ConceptTag] = (),
    ) -> None:
        self._pool = _build_pool()
        self._index = 0
        self._skip = skip_conditions
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        # 모듈 docstring "개념 태깅 공백" 참조 — 기본값 빈 튜플(가짜 orphan-skip 태그 금지).
        self._concept_tags = list(concept_tags)

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            condition = skeleton.condition
            if self._skip is not None and condition in self._skip:
                continue
            return self._assemble(spec, skeleton)
        return None

    def _assemble(self, spec: EquivalenceSpec, skeleton: _Skeleton) -> CandidateProblem:
        template = _TEMPLATES[self._index % len(_TEMPLATES)]
        question_text = template.format(
            f=skeleton.display_f, k=skeleton.k, eul_k=eul_reul(str(skeleton.k))
        )
        answer_text = str(skeleton.result)
        # 위생 게이트(SymPy 산술/방정식 시드 검증기 2종)가 발문 밖 임의 등식 텍스트를 검증
        # 가능한 주장으로 오탐할 수 있다(2026-08-05 실측 2회): ① "(숫자) ... = 숫자" 꼴을
        # 독립 산술 등식으로 오탐(f'(k)g(k)+f(k)g'(k) = 답) ② "f'(x)=2ax+b" 같은 식 뒤에
        # "x=k"가 나오면 "그 방정식의 해가 x=k"라는 주장으로 오탐(실제로는 무관한 두 서술).
        # 등호를 아예 쓰지 않는 순수 서술형 결론으로 우회한다(quadratic 생성기의 "이 중
        # {which} 근은 {answer}이다." 결론형 관례와 동형 — 검증 재료는 conditions/answer_map
        # 이 이미 담당하므로 해설 산문에 재검증 가능한 등식을 중복 기술할 필요가 없다).
        explanation = (
            f"곱의 미분법에 따라 두 인수를 각각 미분한 뒤 조합해 x = {skeleton.k}에서 계산하면 "
            f"f'({skeleton.k})의 값은 {answer_text}이다."
        )
        condition = skeleton.condition
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
            difficulty_overall=3.8,  # 대학 도입 개념(합성 규칙 적용) — conceptual~mastery 경계.
            question_format=QuestionFormat.단답형,
            answer_format=self._answer_format(skeleton.result),
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=explanation,
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 스켈레톤 조립(다항식 계수→곱의 미분법 역산·W2)",
                    "S2-a 수용 게이트(Tier1 SymPy 미분 평가 검산)",
                    "AI 검수 게이트 대기(Kiki 머신·실 LLM 필요 — 미통과 시 is_published=False)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,
            answer_map={"y": answer_text},
            # SymPy Derivative(...).doit()가 곱의 미분법을 전개해 단일 수치로 접는다 — 조건
            # 자체가 이미 "닫힌 계산"이라 별도 단계 체인이 없다(Tier1 단독 verified가 정직).
            solution_steps=None,
            concept_tags=list(self._concept_tags),
        )

    @staticmethod
    def _answer_format(value: int) -> AnswerFormat:
        return AnswerFormat.자연수 if value > 0 else AnswerFormat.실수

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"
