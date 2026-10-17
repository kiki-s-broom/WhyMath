"""중등 일차함수 함숫값 결정론 스켈레톤 생성기 — W2 중등 축 착점(결정론·LLM 0).

학년축 최단경로 계획(`docs/strategy/grade_axis_mvp_shortest_path_v1.md`) §3 W2. 실측
(2026-08-05): 중등 축 0커버 37개 중 `[9수02-14]`(함수의 개념·함숫값)를 최초 착점으로 삼는다.
`ElementaryAddSubSkeletonGenerator`(초등)·`MatrixOpsSkeletonGenerator`(고등 행렬)·
`CalculusProductRuleSkeletonGenerator`(대학 미분)에 이은 네 번째 도메인 — 좌석·게이트 무변경
재사용(신규 게이트 발명 0), 앞선 세 생성기가 실측으로 확립한 함정 회피 패턴을 그대로 적용한다.

대상 성취기준: `[9수02-14]`(함수의 개념을 이해하고, 함숫값을 구할 수 있다). 개념그래프 매핑:
`math.function.hamsuui-gaenyeom-hamsutgaps`(source_id="J0214") — **대학 축(CALC1-P06)과
달리 이 개념은 구 437 legacy 개념그래프 공간에 실존**해 `ConceptTag.concept_src_id` 크로스워크
경로가 정상 동작한다(개념 태깅 공백이 대학 원자 전반의 문제이지 이 파이프라인 자체의 결함이
아님을 대비 확인 — `calculus_product_rule_skeleton_generator` 모듈 docstring 참조).

**검증 설계**: Tier1(`l3/verify_answer`)에 단순 대입 `"(ax+b).subs(x, k) = y"`를 주면
`.doit()` 없이도 바로 `pass`/`fail`이 갈린다(미분과 달리 대입은 이미 평가된 값이라 unevaluated
연산자가 안 남는다 — 실측 확인). 방정식 sympify 기반 범용 검산기라는 결론(초등·행렬·대학
미분에 이어 4번째 확인)이 함수 대입에도 그대로 성립한다.

문제: f(x) = a·x + b(a≠0)에서 f(k)를 구한다. 해설은 **등호 바로 앞에 괄호숫자를 두지 않는
서술형**을 쓴다(`calculus_product_rule_skeleton_generator`의 2026-08-05 위생 게이트 오탐
실측 처방을 그대로 계승 — 재발명 0).

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

__all__ = ["LinearFunctionValueSkeletonGenerator"]

_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="J0214", role="PRIMARY", relevance=0.95),
)

_A_MIN, _A_MAX = -6, 6  # 기울기(0 제외 — 진짜 일차함수라야 함)
_B_MIN, _B_MAX = -8, 8
_K_MIN, _K_MAX = -6, 6  # 평가점

_POOL_TARGET_SIZE = 300  # 조합공간(13×17×13≈2870)이 크므로 전수열거 대신 시드 샘플.

_TEMPLATES: tuple[str, ...] = (
    "f(x) = {f}일 때, f({k})의 값을 구하시오.",
    "일차함수 f(x) = {f}에 대하여 f({k}){eul_k} 구하시오.",
)


def _term(coefficient: int, symbol: str, *, lead: bool = False) -> str:
    """계수 하나를 사람이 읽는 항으로 — 부호·계수 1 생략 규칙(선행 3개 생성기와 동형 독립
    구현 — private 모듈 경계를 넘지 않기 위해 재구현, 신규 규칙 발명 0)."""
    sign = "-" if coefficient < 0 else ("" if lead else "+")
    magnitude = abs(coefficient)
    body = symbol if magnitude == 1 and symbol else f"{magnitude}{symbol}"
    joint = " " if sign and not lead else ""
    return f"{sign}{joint}{body}" if lead else f"{sign} {body}"


def _linear_display(a: int, b: int) -> str:
    """일차식 표기('3x - 5') — 계수 1 생략."""
    parts = [_term(a, "x", lead=True)]
    if b:
        parts.append(_term(b, ""))
    return " ".join(parts)


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """문제 뼈대 — f(x)=ax+b의 계수·평가점 k. 수치의 단일 원천."""

    a: int
    b: int
    k: int

    @property
    def condition(self) -> str:
        return f"({self.a}*x + {self.b}).subs(x, {self.k}) = y"

    @property
    def result(self) -> int:
        """독립 재계산(단순 대입) — 생성기 스스로도 SymPy에 의존하지 않는 이중 확인."""
        return self.a * self.k + self.b

    @property
    def display_f(self) -> str:
        return _linear_display(self.a, self.b)


def _build_pool() -> tuple[_Skeleton, ...]:
    """시드 샘플 풀 — 조합공간이 3자리 정수라 전수열거 대신 결정론 샘플링(중복 제거)."""
    rng = random.Random(20260805)
    pool: list[_Skeleton] = []
    seen: set[tuple[int, int, int]] = set()
    attempts = 0
    while len(pool) < _POOL_TARGET_SIZE and attempts < _POOL_TARGET_SIZE * 20:
        attempts += 1
        a = rng.choice([v for v in range(_A_MIN, _A_MAX + 1) if v != 0])
        b = rng.randint(_B_MIN, _B_MAX)
        k = rng.randint(_K_MIN, _K_MAX)
        key = (a, b, k)
        if key in seen:
            continue
        seen.add(key)
        pool.append(_Skeleton(a=a, b=b, k=k))
    random.Random(20260805 + 1).shuffle(pool)
    return tuple(pool)


@deterministic_generator
class LinearFunctionValueSkeletonGenerator:
    """결정론 스켈레톤 생성기 — 중등 일차함수 함숫값(`EquivalentProblemGenerator` 좌석).

    단일 변형이라(§ 모듈 docstring) `operation` 필터가 불필요하다(elementary_addsub·
    matrix_ops가 겪은 "밴드별 인스턴스가 고정 시드 풀을 재생하는" 함정은 밴드가 1개뿐이라
    발생하지 않는다). `harness/middle_function_batch.py`도 동일하게 `run_batch`가 아니라
    `run_equivalent_generation`을 `signature_index=None`으로 호출한다(산술 조건의 구조
    dedup이 해값 기반이라 서로 다른 (a,b,k) 조합이 같은 f(k) 값을 내면 오탐).
    """

    def __init__(
        self,
        *,
        skip_conditions: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-linear-func-value",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("LINEAR-FUNC-VALUE",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        self._pool = _build_pool()
        self._index = 0
        self._skip = skip_conditions
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
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
        # 위생 게이트 오탐 회피(calculus_product_rule_skeleton_generator 2026-08-05 실측
        # 처방 계승) — 등호를 아예 쓰지 않는 서술형 결론. 조사는 하드코딩 금지(elementary_
        # addsub 2026-08-05 실측 사고 재발 — eul_reul로 정확히 선택).
        explanation = (
            f"f(x) = {skeleton.display_f}에 x = {skeleton.k}{eul_reul(str(skeleton.k))} "
            f"대입하면 f({skeleton.k})의 값은 {answer_text}이다."
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
            difficulty_overall=1.8,  # 중등 도입 개념(대입) — awareness~procedural 경계.
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
                    "결정론 스켈레톤 조립(계수→함숫값 대입 역산·W2)",
                    "S2-a 수용 게이트(Tier1 대입 평가 검산)",
                    "AI 검수 게이트 대기(Kiki 머신·실 LLM 필요 — 미통과 시 is_published=False)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,
            answer_map={"y": answer_text},
            # 단순 대입 1회는 다단계 과정이 없다(Tier1 단독 verified가 정직 — 앞선 세 생성기와
            # 동일 원칙).
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
