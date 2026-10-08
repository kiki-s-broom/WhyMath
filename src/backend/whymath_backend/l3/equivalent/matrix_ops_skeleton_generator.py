"""고등 2×2 행렬 연산(덧셈·뺄셈·스칼라배·곱셈) 결정론 스켈레톤 생성기 — W2(결정론·LLM 0).

학년축 최단경로 계획(`docs/strategy/grade_axis_mvp_shortest_path_v1.md`) §3 W2. 실측
(2026-08-05): 고등 축 0커버 211개 중 "행렬" 영역은 4코드 전량(`[10공수1-04-01/02]`·
`[10기수1-04-01/02]`) 0.0%다. `ElementaryAddSubSkeletonGenerator`(초등 축) 선례를 그대로
따라 새 도메인에 새 생성기 1종을 짓는다 — 좌석·게이트는 무변경 재사용.

대상 성취기준: `[10공수1-04-02]`(행렬의 연산). 개념그래프 매핑:
`math.matrix.haengryeolui-yeonsan-2`(source_id="HK43").

**검증 설계(중요·2026-08-05 실측 스파이크)**: Tier1(`l3/verify_answer`)에 행렬값 조건을
직접 주면(`"Matrix(...) + Matrix(...) = Matrix(...)"`) `unverifiable`이 난다 — 수치 평가기가
행렬 잔차를 스칼라로 환원하지 못한다(설계상 스칼라 등식·부등식 대상). 따라서 이 생성기는
행렬 연산 결과의 **특정 성분 1개**를 스칼라 조건으로 검증한다("행렬 A, B에 대해 A+B의 (i,j)
성분을 구하시오" → 조건은 `"a_ij + b_ij = x"`, 순수 스칼라). 학생이 보는 발문에는 행렬 전체가
그대로 노출되므로 교수학적으로는 정식 행렬 문제이고, 검증 재료만 스칼라로 좁힌다(안전한
검증 경로 재사용 — 도메인 전용 검증기 신설 0).

곱셈(AB)의 (i,j) 성분은 행벡터·열벡터 내적(Σₖ A[i][k]B[k][j])이라 덧셈/뺄셈/스칼라배보다
인지 부하가 크다 — 난이도를 별도로 높게 잡는다(§ `_Skeleton.difficulty`).

**노출 게이팅**: `elementary_addsub_skeleton_generator`와 동일 원칙 — 산출물은 v0(사람
검수 전), AI 검수(Wilson 게이트)는 실 LLM 필요라 이 환경 밖(Kiki 머신)에서만 가능하다.
그 전까지 `is_published=False`로 유지.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
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

__all__ = ["MatrixOpsSkeletonGenerator", "MatrixOperation"]

_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="HK43", role="PRIMARY", relevance=0.95),
)

Matrix2x2 = tuple[tuple[int, int], tuple[int, int]]
MatrixOperation = Literal["add", "subtract", "scalar_mul", "multiply"]

_ENTRY_MIN, _ENTRY_MAX = -6, 6
_SCALAR_MIN, _SCALAR_MAX = -4, 4
_POOL_SIZE_PER_OP = 120  # 뼈대 조합공간이 매우 크므로(4자리×2×2) 전수 열거 대신 시드 샘플.

_ADD_TEMPLATES: tuple[str, ...] = (
    "행렬 A = {a}, B = {b}에 대하여 A + B의 ({row}행 {col}열) 성분을 구하시오.",
    "두 행렬 A = {a}, B = {b}의 합 A + B에서 ({row}행 {col}열) 성분의 값은?",
)
_SUB_TEMPLATES: tuple[str, ...] = (
    "행렬 A = {a}, B = {b}에 대하여 A - B의 ({row}행 {col}열) 성분을 구하시오.",
    "두 행렬 A = {a}, B = {b}의 차 A - B에서 ({row}행 {col}열) 성분의 값은?",
)
_SCALAR_TEMPLATES: tuple[str, ...] = (
    "행렬 A = {a}에 대하여 {k}A의 ({row}행 {col}열) 성분을 구하시오.",
    "행렬 A = {a}의 각 성분에 {k}를 곱한 행렬 {k}A에서 ({row}행 {col}열) 성분의 값은?",
)
_MUL_TEMPLATES: tuple[str, ...] = (
    "행렬 A = {a}, B = {b}에 대하여 AB의 ({row}행 {col}열) 성분을 구하시오.",
    "두 행렬 A = {a}, B = {b}의 곱 AB에서 ({row}행 {col}열) 성분의 값은?",
)
_TEMPLATES_BY_OP: dict[MatrixOperation, tuple[str, ...]] = {
    "add": _ADD_TEMPLATES,
    "subtract": _SUB_TEMPLATES,
    "scalar_mul": _SCALAR_TEMPLATES,
    "multiply": _MUL_TEMPLATES,
}


def _matrix_text(m: Matrix2x2) -> str:
    """행렬 표기 — 대괄호 표기(기존 생성기 관례 미러: 방정식도 렌더러-중립 평문)."""
    (a11, a12), (a21, a22) = m
    return f"[[{a11}, {a12}], [{a21}, {a22}]]"


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """문제 뼈대 — 행렬 A(·B·스칼라 k)·연산·조회 성분(row,col은 0-index). 수치의 단일 원천."""

    a: Matrix2x2
    b: Matrix2x2 | None  # scalar_mul에서만 None
    k: int | None  # scalar_mul에서만 값을 가짐
    operation: MatrixOperation
    row: int  # 0 또는 1
    col: int  # 0 또는 1

    @property
    def result_entry(self) -> int:
        i, j = self.row, self.col
        if self.operation == "add":
            assert self.b is not None
            return self.a[i][j] + self.b[i][j]
        if self.operation == "subtract":
            assert self.b is not None
            return self.a[i][j] - self.b[i][j]
        if self.operation == "scalar_mul":
            assert self.k is not None
            return self.k * self.a[i][j]
        # multiply: (AB)[i][j] = Σₖ A[i][k]·B[k][j] (2×2 내적).
        assert self.b is not None
        return self.a[i][0] * self.b[0][j] + self.a[i][1] * self.b[1][j]

    @property
    def difficulty(self) -> float:
        """rule-based 난이도 — 사칙 성분연산은 procedural 초입, 곱셈은 내적 이해가 필요해 상향.

        L6 밴드 앵커(procedural=2.5) 이내로 클램프 — 고1 도입 단원이 대학 밴드로 새지 않게.
        """
        base = 2.8 if self.operation == "multiply" else 2.0
        return min(base, 2.8)

    @property
    def condition(self) -> str:
        i, j = self.row, self.col
        if self.operation == "add":
            assert self.b is not None
            return f"{self.a[i][j]} + {self.b[i][j]} = x"
        if self.operation == "subtract":
            assert self.b is not None
            return f"{self.a[i][j]} - {self.b[i][j]} = x"
        if self.operation == "scalar_mul":
            assert self.k is not None
            return f"{self.k} * {self.a[i][j]} = x"
        assert self.b is not None
        return f"{self.a[i][0]} * {self.b[0][j]} + {self.a[i][1]} * {self.b[1][j]} = x"


def _random_entries(rng: random.Random) -> Matrix2x2:
    vals = [rng.randint(_ENTRY_MIN, _ENTRY_MAX) for _ in range(4)]
    return ((vals[0], vals[1]), (vals[2], vals[3]))


def _build_pool() -> tuple[_Skeleton, ...]:
    """4연산 × 시드 샘플 풀 — 조합공간이 4자리 정수×2×2라 전수열거 대신 결정론 샘플링."""
    rng = random.Random(20260805)
    pool: list[_Skeleton] = []
    seen: set[tuple[object, ...]] = set()
    for operation in ("add", "subtract", "scalar_mul", "multiply"):
        made = 0
        attempts = 0
        while made < _POOL_SIZE_PER_OP and attempts < _POOL_SIZE_PER_OP * 20:
            attempts += 1
            a = _random_entries(rng)
            b = None if operation == "scalar_mul" else _random_entries(rng)
            k = rng.randint(_SCALAR_MIN, _SCALAR_MAX) if operation == "scalar_mul" else None
            if operation == "scalar_mul" and k == 0:
                continue  # 0배는 자명해 학습 가치가 낮다(모든 성분이 0으로 뻔함).
            row, col = rng.randint(0, 1), rng.randint(0, 1)
            key = (a, b, k, operation, row, col)
            if key in seen:
                continue
            seen.add(key)
            pool.append(_Skeleton(a=a, b=b, k=k, operation=operation, row=row, col=col))
            made += 1
    random.Random(20260805 + 1).shuffle(pool)
    return tuple(pool)


@deterministic_generator
class MatrixOpsSkeletonGenerator:
    """결정론 스켈레톤 생성기 — 2×2 행렬 연산(`EquivalentProblemGenerator` 좌석).

    `ElementaryAddSubSkeletonGenerator`와 동일 관례: `run_batch`가 아니라
    `run_equivalent_generation`을 `signature_index=None`으로 호출해야 한다(산술 조건의
    구조 dedup이 해값 기반이라 서로 다른 행렬 조합이 같은 성분값을 내면 오탐 — 초등 배치와
    동일 처방, `harness/matrix_ops_batch.py` 참조).
    """

    def __init__(
        self,
        *,
        operation: MatrixOperation | None = None,
        skip_conditions: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-matrix-ops",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("MATRIX-OPS",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        # `operation` 필터 필수(elementary_addsub_skeleton_generator 2026-08-05 실측 사고
        # 참조·동일 함정): `_build_pool()`은 고정 시드라 필터 없이 여러 인스턴스를 만들면
        # 매번 *같은* 셔플 순서를 재생한다 — 배치가 연산별 밴드를 나누려면 이 필터로 인스턴스를
        # 분리해야 한다(안 그러면 밴드가 같은 뼈대를 중복 방출).
        full_pool = _build_pool()
        self._pool = (
            full_pool
            if operation is None
            else tuple(s for s in full_pool if s.operation == operation)
        )
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
        templates = _TEMPLATES_BY_OP[skeleton.operation]
        question_text = templates[self._index % len(templates)].format(
            a=_matrix_text(skeleton.a),
            b=_matrix_text(skeleton.b) if skeleton.b is not None else "",
            k=skeleton.k if skeleton.k is not None else "",
            row=skeleton.row + 1,
            col=skeleton.col + 1,
        )
        answer_text = str(skeleton.result_entry)
        explanation = self._explanation(skeleton)
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
            difficulty_overall=skeleton.difficulty,
            question_format=QuestionFormat.단답형,
            answer_format=self._answer_format(skeleton.result_entry),
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
                    "결정론 스켈레톤 조립(행렬 성분→성분식 역산·W2)",
                    "S2-a 수용 게이트(Tier1 성분 스칼라 검산)",
                    "AI 검수 게이트 대기(Kiki 머신·실 LLM 필요 — 미통과 시 is_published=False)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,
            answer_map={"x": answer_text},
            # 성분 1개짜리 스칼라 조건이라 다단계 과정이 없다(모듈 docstring — 검증 설계 참조).
            # Tier1 단독 verified가 정직한 최종 등급(elementary_addsub와 동일 원칙).
            solution_steps=None,
            concept_tags=list(self._concept_tags),
        )

    @staticmethod
    def _answer_format(value: int) -> AnswerFormat:
        return AnswerFormat.자연수 if value > 0 else AnswerFormat.실수

    @staticmethod
    def _explanation(skeleton: _Skeleton) -> str:
        i, j = skeleton.row + 1, skeleton.col + 1
        answer = skeleton.result_entry
        if skeleton.operation == "add":
            assert skeleton.b is not None
            return (
                f"({i}행 {j}열) 성분은 A의 ({i}행 {j}열) 성분과 B의 ({i}행 {j}열) 성분의 합이다: "
                f"{skeleton.a[i - 1][j - 1]} + {skeleton.b[i - 1][j - 1]} = {answer}."
            )
        if skeleton.operation == "subtract":
            assert skeleton.b is not None
            return (
                f"({i}행 {j}열) 성분은 A의 ({i}행 {j}열) 성분에서 B의 ({i}행 {j}열) 성분을 "
                f"뺀 값이다: {skeleton.a[i - 1][j - 1]} - {skeleton.b[i - 1][j - 1]} = {answer}."
            )
        if skeleton.operation == "scalar_mul":
            assert skeleton.k is not None
            return (
                f"스칼라배는 각 성분에 {skeleton.k}를 곱한다: "
                f"{skeleton.k} × {skeleton.a[i - 1][j - 1]} = {answer}."
            )
        assert skeleton.b is not None
        a_row = skeleton.a[i - 1]
        b_col = (skeleton.b[0][j - 1], skeleton.b[1][j - 1])
        return (
            f"AB의 ({i}행 {j}열) 성분은 A의 {i}행과 B의 {j}열의 내적이다: "
            f"{a_row[0]} × {b_col[0]} + {a_row[1]} × {b_col[1]} = {answer}."
        )

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"
