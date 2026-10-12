"""변형 3종 발화(PB-09) — 난이도 계열변형·조건변형·역문제 (결정론·LLM 0).

문제은행 R3 §3 G5·§5-④가 "발화 조건(D4 재고 부족 실측 + D8 계보 기록 좌석)이 충족됐는데 아무도
발화시키지 않았다"고 판정한 3종을, **기존 이차방정식 스켈레톤의 근-먼저 구조 위에서** 낳는다.
신규 생성기·신규 추상·신규 필드를 만들지 않는다(1차 §2-⑥ Problem Template DSL 미채택과 정합) —
부모 코퍼스 행에서 근·선택을 복원해 `_Skeleton`을 다시 짓고, 같은 조립 경로로 자식 후보를 낸다.

## 계보 규약 (3종 전부 필수 — 계보 없는 변형 확대는 금지)

방향은 항상 **부모(코퍼스에 이미 있는 문항) → 자식(새 문항)** 이다(`ProblemRelationTag` 규약).
신규 enum 값은 0 — 기존 `RelationType`·`GenerationType` 좌석을 실사용으로 전환한다.

| 모드 | move | 자식이 부모와 갖는 관계 | relation_type | generation_type |
|---|---|---|---|---|
| 난이도 계열 | `ladder_harder` | 자식이 부모의 더 어려운 계열 | `심화` | `VARIANT_STRUCTURE` |
| 난이도 계열 | `ladder_easier` | 자식이 부모의 선행(쉬운) 계열 | `선수` | `VARIANT_STRUCTURE` |
| 조건변형 | `condition_flip` | 같은 방정식·반대쪽 근 선택 | `변형` | `VARIANT_CONTEXT` |
| 조건변형 | `condition_sign` | 같은 방정식·부호 조건("양수인 근") | `변형` | `VARIANT_CONTEXT` |
| 역문제 | `inverse` | 같은 두 근에서 방정식 복원(정문제의 반대) | `대조` | `VARIANT_STRUCTURE` |

"기초" 관계는 `RelationType`에 없다 — 방향을 뒤집은 `선수`(자식이 부모의 선수)로 같은 사실을
표현한다. 새 enum을 만들지 않은 이유는 anti-explosion(관계 타입 5~8개 제한)이다.

## 난이도 계열의 축 — "같은 뿌리"

계열은 **정답 근을 고정**하고 *다른 쪽 근의 형태*만 바꾼다. 같은 답을 다른 길로 보게 하는
것이 변형의 목적이다(플레이북 Part 0 — 문제은행이 아니라 사고 추적기). 난이도 값은 새로
추정하지 않고 `difficulty.estimate_difficulty`(근 유형·선두계수·계수 크기)를 그대로 쓴다.
공식이 값을 바꾸지 못하는 이동(예: 정답 근이 이미 유리수)은 **만들지 않고 skip 사유로 센다** —
난이도가 달라졌다고 주장할 근거가 없는 계열은 계열이 아니다.

## 검산 계약 (④ — 기계 증명 범위 안에서만)

모든 자식은 부모와 같은 수용 게이트(`evaluate_equivalent_candidate`)를 통과해야 저장된다. 이 모듈은
자식을 *낼 뿐* 합격을 선언하지 않는다. 다만 게이트가 못 보는 *유일성*(부호 조건이 정확히 한
근만 고르는가, 역문제의 해가 유일한가)은 낼 때 SymPy 정확값으로 직접 확인하고, 성립하지 않으면
자식을 만들지 않는다. 난이도 추정 공식은 조건변형·역문제 축을 모른다 — 그 둘은 **부모 난이도를
계승**하고 가산하지 않는다(추정 근거 없는 축을 날조하지 않는다 · 실응답 보정은 PB-10 소관).

## 범위 밖 (정직)

- 무리근(완전제곱꼴 p±√q) 부모 — 이동 규칙이 근의 유리성에 기대므로 v1은 부모 자격 미달 처리.
- 중근 부모 — 선택·부호 조건이 의미를 잃고 역문제는 두 근이 같아 연립이 풀리지 않는다.
- 선두계수 ≠ 1 부모의 역문제 — 두 근 제시만으로는 이차식이 유일하지 않다(상수배 자유도).
- 학생 노출 정책(형제를 언제 보일지 — L6/CAT 축)·역문제 채점 루브릭·다중 풀이.

7계층: L3 지역. schema·L1 problem_bank(ConceptTag 타입)·동일 패키지만 import한다.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from math import ceil, floor
from typing import Any, Literal

import sympy

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.skeleton_generator import (
    SkeletonEquivalentProblemGenerator,
    _display_equation,
    _factoring_steps,
    _fraction_text,
    _Skeleton,
    _sympy_equation,
)
from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.schema.enums import (
    AnswerFormat,
    Curriculum,
    GenerationType,
    LicenseType,
    RelationType,
    Subject,
)
from whymath_backend.schema.provenance import ContentProvenance

__all__ = [
    "MOVE_SPECS",
    "MOVES",
    "ParentRejection",
    "VariantDraft",
    "VariantMode",
    "VariantMove",
    "VariantParent",
    "VariantSkip",
    "derive_variants",
    "parse_parent",
]

VariantMode = Literal["ladder", "condition", "inverse"]
"""변형 모드 3종 — 난이도 계열(ladder)·조건변형(condition)·역문제(inverse)."""

VariantMove = Literal[
    "ladder_harder",
    "ladder_easier",
    "condition_flip",
    "condition_sign",
    "inverse",
]
"""모드 안의 구체 이동 5종 — 부모 1건당 이동마다 정확히 1번 시도한다(시도 회계의 분모)."""

MOVES: tuple[VariantMove, ...] = (
    "ladder_harder",
    "ladder_easier",
    "condition_flip",
    "condition_sign",
    "inverse",
)


@dataclass(frozen=True, slots=True)
class _MoveSpec:
    """이동 1종이 낳는 계보 좌석 — 모드·관계 유형·생성 유형·slug 접두."""

    mode: VariantMode
    relation_type: RelationType
    generation_type: GenerationType
    slug_prefix: str


MOVE_SPECS: Mapping[VariantMove, _MoveSpec] = {
    "ladder_harder": _MoveSpec(
        "ladder", RelationType.심화, GenerationType.VARIANT_STRUCTURE, "wm-var-lad"
    ),
    "ladder_easier": _MoveSpec(
        "ladder", RelationType.선수, GenerationType.VARIANT_STRUCTURE, "wm-var-lad"
    ),
    "condition_flip": _MoveSpec(
        "condition", RelationType.변형, GenerationType.VARIANT_CONTEXT, "wm-var-cnd"
    ),
    "condition_sign": _MoveSpec(
        "condition", RelationType.변형, GenerationType.VARIANT_CONTEXT, "wm-var-cnd"
    ),
    "inverse": _MoveSpec(
        "inverse", RelationType.대조, GenerationType.VARIANT_STRUCTURE, "wm-var-inv"
    ),
}

_QUAD_UNIT = "QUAD-EQ"
_ROOT_VAR = sympy.Symbol("x")


@dataclass(frozen=True, slots=True)
class VariantParent:
    """변형의 부모 — 코퍼스 행에서 복원한 이차방정식 뼈대 + 자식이 계승할 메타."""

    slug: str
    problem_id: uuid.UUID
    skeleton: _Skeleton
    unit_codes: tuple[str, ...]
    standard_codes: frozenset[str]
    difficulty: float
    subject: Subject
    curriculum_version: Curriculum
    valid_from_year: int
    concept_tags: tuple[ConceptTag, ...]


@dataclass(frozen=True, slots=True)
class ParentRejection:
    """부모 자격 미달 — 이 행에서는 어떤 변형도 시도하지 않는다(사유는 리포트에 센다)."""

    slug: str
    reason: str


@dataclass(frozen=True, slots=True)
class VariantSkip:
    """(부모, 이동) 시도가 자식을 낳지 못함 — 조용한 누락 금지라 사유를 남긴다."""

    parent_slug: str
    move: VariantMove
    reason: str


@dataclass(frozen=True, slots=True)
class VariantDraft:
    """자식 후보 + 그 계보 — 하네스가 게이트·dedup·저장에 태우고 relation을 부여한다.

    `spec`은 *부모 기준* 명세다(성취기준·난이도) — 자식이 부모와 같은 단원·인접 난이도 대역에
    있는지를 게이트의 동등성 성분이 본다. `dedup_key`는 구조 signature가 없는(연립 조건) 자식을
    위한 자체 중복 키다 — signature가 있는 자식은 오케스트레이터가 따로 거른다.
    """

    parent: VariantParent
    move: VariantMove
    candidate: CandidateProblem
    spec: EquivalenceSpec
    dedup_key: str

    @property
    def mode(self) -> VariantMode:
        return MOVE_SPECS[self.move].mode

    @property
    def relation_type(self) -> RelationType:
        return MOVE_SPECS[self.move].relation_type

    @property
    def generation_type(self) -> GenerationType:
        return MOVE_SPECS[self.move].generation_type


# ── 부모 복원 ───────────────────────────────────────────────────────────────


def _reject(slug: str, reason: str) -> ParentRejection:
    return ParentRejection(slug=slug, reason=reason)


def _skeleton_from_conditions(
    conditions: str, selection: str
) -> tuple[_Skeleton | None, str | None]:
    """`verify.conditions`('x**2 - 5*x = 0')에서 뼈대를 복원 — 못 하면 (None, 사유).

    복원이 코퍼스와 어긋나면(비원시 다항식 등) 거부한다: 자식은 부모와 *같은 생성 경로*의
    산물이어야 계보가 거짓이 되지 않는다.
    """
    if "=" not in conditions:
        return None, "조건이 등식이 아님"
    left_text, right_text = conditions.split("=", 1)
    try:
        residual = safe_sympify(left_text) - safe_sympify(right_text)
        poly = sympy.Poly(residual, _ROOT_VAR)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 부모 자격 미달로 센다
        return None, f"조건 파싱 불가({type(exc).__name__})"
    if poly.degree() != 2:
        return None, "이차방정식이 아님"
    try:
        a, b, c = (int(coeff) for coeff in poly.all_coeffs())
    except (TypeError, ValueError):
        return None, "정수 계수가 아님"
    if a < 0:
        a, b, c = -a, -b, -c
    disc = b * b - 4 * a * c
    if disc < 0:
        return None, "실근 없음"
    root_disc = sympy.sqrt(disc)
    if not root_disc.is_Integer:
        return None, "무리근 부모(v1 범위 밖)"
    sqrt_disc = int(root_disc)
    roots = (Fraction(-b - sqrt_disc, 2 * a), Fraction(-b + sqrt_disc, 2 * a))
    if roots[0] == roots[1]:
        return None, "중근 부모(v1 범위 밖)"
    factors = tuple((r.denominator, r.numerator) for r in roots)
    skeleton = _Skeleton(factors=(factors[0], factors[1]), selection=selection)
    if skeleton.coefficients != (a, b, c):
        return None, "비원시 다항식(스켈레톤 생성 경로 밖)"
    return skeleton, None


def parse_parent(row: Mapping[str, Any]) -> VariantParent | ParentRejection:
    """코퍼스 JSONL 행 → 부모. 변형 가능한 이차방정식 단답·객관식 행만 통과한다."""
    slug = str(row.get("slug", ""))
    if not slug:
        return _reject("", "slug 없음")
    if list(row.get("unit_codes", [])) != [_QUAD_UNIT]:
        return _reject(slug, f"단원이 {_QUAD_UNIT}이 아님")
    verify = row.get("verify") or {}
    conditions = verify.get("conditions")
    selection = verify.get("answer_selection")
    if not isinstance(conditions, str):
        return _reject(slug, "단일 등식 조건이 아님")
    if selection not in ("largest", "smallest"):
        return _reject(slug, f"근 선택이 largest/smallest가 아님({selection!r})")
    skeleton, why = _skeleton_from_conditions(conditions, selection)
    if skeleton is None:
        return _reject(slug, why or "뼈대 복원 실패")
    # 복원한 정답이 코퍼스의 정답과 다르면 계보의 전제(같은 뿌리)가 깨진다 — fail-closed.
    stored_answer = (verify.get("answer_map") or {}).get("x")
    if stored_answer != _fraction_text(skeleton.answer_root):
        return _reject(slug, "복원 정답이 코퍼스 정답과 불일치")
    try:
        return VariantParent(
            slug=slug,
            problem_id=uuid.UUID(str(row["problem_id"])),
            skeleton=skeleton,
            unit_codes=tuple(row["unit_codes"]),
            standard_codes=frozenset(row["achievement_standard_codes"]),
            difficulty=float(row["difficulty_overall"]),
            subject=Subject(row["subject"]),
            curriculum_version=Curriculum(row["curriculum_version"]),
            valid_from_year=int(row["valid_from_year"]),
            concept_tags=tuple(
                ConceptTag(
                    concept_src_id=tag["concept_src_id"],
                    role=tag["role"],
                    relevance=float(tag["relevance"]),
                )
                for tag in row.get("concepts", [])
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _reject(slug, f"부모 메타 누락·형식 오류({type(exc).__name__})")


# ── 자식 조립 ───────────────────────────────────────────────────────────────


def _generator_for(parent: VariantParent, move: VariantMove) -> SkeletonEquivalentProblemGenerator:
    """부모 메타를 계승한 조립기 — 기존 스켈레톤 조립 경로를 그대로 쓴다(신규 조립기 0)."""
    return SkeletonEquivalentProblemGenerator(
        variant="short_answer",
        slug_prefix=MOVE_SPECS[move].slug_prefix,
        subject=parent.subject,
        curriculum_version=parent.curriculum_version,
        valid_from_year=parent.valid_from_year,
        unit_codes=parent.unit_codes,
        concept_tags=parent.concept_tags,
    )


def _spec_for(parent: VariantParent) -> EquivalenceSpec:
    return EquivalenceSpec(
        achievement_standard_codes=parent.standard_codes,
        target_misconception_ids=frozenset(),
        difficulty_overall=parent.difficulty,
        answer_format=None,
    )


def _with_lineage(
    candidate: CandidateProblem,
    parent: VariantParent,
    move: VariantMove,
    *,
    conditions: str | list[str] | None = None,
    answer_map: dict[str, str] | None = None,
    answer_selection: str | None | Literal["keep"] = "keep",
    steps: list[str] | None = None,
) -> CandidateProblem:
    """조립된 후보에 변형 출처(provenance)를 박는다 — FULLY_GENERATED로 남기지 않는다.

    `parent_problem_id`·`transformation_pipeline`에 부모와 이동을 적어 후보 자신이 계보를
    들고 다니게 한다(problem_relation 행이 유실돼도 provenance만으로 출처가 복원된다).
    """
    move_spec = MOVE_SPECS[move]
    provenance = ContentProvenance(
        generation_type=move_spec.generation_type,
        license=LicenseType.WHYMATH_GENERATED,
        original_source=None,
        parent_problem_id=parent.problem_id,
        transformation_pipeline={
            "steps": [
                f"부모 코퍼스 행에서 근·선택 복원({parent.slug})",
                f"변형 이동 {move}",
                "S2-a 수용 게이트",
                "구조 signature dedup",
            ],
            "variant_mode": move_spec.mode,
            "variant_move": move,
            "parent_slug": parent.slug,
        },
    )
    return CandidateProblem(
        problem=candidate.problem,
        provenance=provenance,
        conditions=candidate.conditions if conditions is None else conditions,
        answer_map=candidate.answer_map if answer_map is None else answer_map,
        answer_selection=(
            candidate.answer_selection if answer_selection == "keep" else answer_selection
        ),
        answer_aggregate=candidate.answer_aggregate,
        answer_kind=candidate.answer_kind,
        solution_steps=candidate.solution_steps if steps is None else steps,
        concept_tags=list(candidate.concept_tags),
    )


def _draft_from_skeleton(
    parent: VariantParent, move: VariantMove, skeleton: _Skeleton
) -> VariantDraft:
    """뼈대 → 표준 스켈레톤 조립 → 변형 출처 부여(난이도 계열·선택 뒤집기 공용)."""
    spec = _spec_for(parent)
    generator = _generator_for(parent, move)
    candidate = _with_lineage(generator._assemble(spec, skeleton), parent, move)  # noqa: SLF001
    a, b, c = skeleton.coefficients
    return VariantDraft(
        parent=parent,
        move=move,
        candidate=candidate,
        spec=spec,
        dedup_key=f"{move}|{a}|{b}|{c}|{skeleton.selection}",
    )


def _ladder_harder(parent: VariantParent) -> VariantDraft | VariantSkip:
    """정답 근을 고정하고 *다른 쪽 근*을 정수 → 반정수로 — 근 유형 integer→rational(+선두계수)."""
    sk = parent.skeleton
    if sk.root_kind != "integer":
        return VariantSkip(
            parent.slug, "ladder_harder", "부모가 정수근이 아니라 더 올릴 근 유형 축이 없다"
        )
    small, large = sk.roots
    answer = sk.answer_root
    other = small if sk.selection == "largest" else large
    # 정답에서 멀어지는 쪽으로 반 칸 — 선택(큰/작은 근)이 뒤집히지 않음이 구성으로 보장된다.
    step = -1 if sk.selection == "largest" else 1
    numerator = int(2 * other) + step  # other는 정수: 반정수 numerator/2
    new_other = Fraction(numerator, 2)
    child = _Skeleton(
        factors=((1, int(answer)), (2, numerator)),
        selection=sk.selection,
    )
    return _checked_ladder(parent, "ladder_harder", child, answer, new_other)


def _ladder_easier(parent: VariantParent) -> VariantDraft | VariantSkip:
    """정답 근을 고정하고 *다른 쪽 유리근*을 가장 가까운 정수로 — 근 유형 rational→integer."""
    sk = parent.skeleton
    if sk.root_kind != "rational":
        return VariantSkip(
            parent.slug, "ladder_easier", "부모가 유리근이 아니라 낮출 근 유형 축이 없다"
        )
    small, large = sk.roots
    answer = sk.answer_root
    other = small if sk.selection == "largest" else large
    if answer.denominator != 1:
        return VariantSkip(
            parent.slug,
            "ladder_easier",
            "정답 근이 이미 유리수라 다른 근을 정수로 바꿔도 근 유형 난이도가 변하지 않는다",
        )
    if other.denominator == 1:
        return VariantSkip(parent.slug, "ladder_easier", "다른 근이 이미 정수")
    # other에서 가장 가까운(정답 쪽) 정수 — 심화 이동(정답 반대쪽으로 반 칸)의 역이 되게 한다.
    # 정답 근과 겹치면 반대쪽 정수로 물러난다(선택이 뒤집히지 않는 쪽).
    if sk.selection == "largest":
        new_other = Fraction(ceil(other))
        if new_other >= answer:
            new_other = Fraction(floor(other))
    else:
        new_other = Fraction(floor(other))
        if new_other <= answer:
            new_other = Fraction(ceil(other))
    child = _Skeleton(
        factors=((1, int(answer)), (1, int(new_other))),
        selection=sk.selection,
    )
    return _checked_ladder(parent, "ladder_easier", child, answer, new_other)


def _checked_ladder(
    parent: VariantParent,
    move: VariantMove,
    child: _Skeleton,
    answer: Fraction,
    new_other: Fraction,
) -> VariantDraft | VariantSkip:
    """계열 이동의 불변식 3종을 조립 전에 확인 — 하나라도 깨지면 자식을 만들지 않는다."""
    if child.answer_root != answer:
        return VariantSkip(parent.slug, move, "이동 후 정답 근이 바뀜(같은 뿌리 위반)")
    if new_other == answer:
        return VariantSkip(parent.slug, move, "이동 후 두 근이 겹침")
    harder = move == "ladder_harder"
    if harder and not child.difficulty > parent.skeleton.difficulty:
        return VariantSkip(parent.slug, move, "난이도 공식이 상승을 주장하지 않음")
    if not harder and not child.difficulty < parent.skeleton.difficulty:
        return VariantSkip(parent.slug, move, "난이도 공식이 하강을 주장하지 않음")
    return _draft_from_skeleton(parent, move, child)


def _condition_flip(parent: VariantParent) -> VariantDraft | VariantSkip:
    """같은 방정식에서 반대쪽 근을 묻는다 — 정답이 달라지는 조건변형."""
    sk = parent.skeleton
    flipped = "smallest" if sk.selection == "largest" else "largest"
    return _draft_from_skeleton(parent, "condition_flip", _Skeleton(sk.factors, flipped))


def _condition_sign(parent: VariantParent) -> VariantDraft | VariantSkip:
    """부호 조건("양수인/음수인 근")으로 근을 고른다 — 정확히 한 근만 고를 때만 만든다."""
    sk = parent.skeleton
    roots = sk.roots
    picks = {
        "양수": [r for r in roots if r > 0],
        "음수": [r for r in roots if r < 0],
    }
    usable = {label: found[0] for label, found in picks.items() if len(found) == 1}
    if not usable:
        return VariantSkip(parent.slug, "condition_sign", "부호 조건이 두 근을 가르지 못함")
    # 부모와 다른 근을 고르는 부호를 우선 — 같은 답을 베끼는 변형을 피한다(이동의 목적).
    label = next(
        (name for name, root in usable.items() if root != sk.answer_root),
        next(iter(usable)),
    )
    answer = usable[label]
    # 유일성(SymPy 정확값) — 게이트 Tier1은 "답이 조건을 만족하는가"만 보고 유일성은 보지 않는다.
    a, b, c = sk.coefficients
    solved = sympy.solve(sympy.Eq(safe_sympify(f"{a}*x**2+({b})*x+({c})"), 0), _ROOT_VAR)
    matching = [r for r in solved if (r > 0 if label == "양수" else r < 0)]
    if len(matching) != 1 or sympy.Rational(answer.numerator, answer.denominator) != matching[0]:
        return VariantSkip(parent.slug, "condition_sign", "SymPy 유일성 확인 실패")

    spec = _spec_for(parent)
    generator = _generator_for(parent, "condition_sign")
    display = _display_equation(a, b, c)
    sign_condition = "x > 0" if label == "양수" else "x < 0"
    answer_text = _fraction_text(answer)
    base = generator._build_candidate(  # noqa: SLF001
        spec,
        question_text=f"이차방정식 {display} 의 근 중 {label}인 근을 구하시오.",
        answer_text=answer_text,
        explanation=_sign_explanation(sk, label, answer),
        answer_format=generator._answer_format(answer),  # noqa: SLF001
        difficulty=parent.difficulty,  # 조건변형 축은 난이도 공식 밖 — 부모 계승(가산 금지)
        condition=_sympy_equation(a, b, c),
        selection="",
        steps=_factoring_steps(sk),
    )
    candidate = _with_lineage(
        base,
        parent,
        "condition_sign",
        conditions=[_sympy_equation(a, b, c), sign_condition],
        answer_map={"x": answer_text},
        answer_selection=None,
    )
    return VariantDraft(
        parent=parent,
        move="condition_sign",
        candidate=candidate,
        spec=spec,
        dedup_key=f"condition_sign|{a}|{b}|{c}|{label}",
    )


def _sign_explanation(sk: _Skeleton, label: str, answer: Fraction) -> str:
    small, large = sk.roots
    return (
        f"방정식의 두 근은 {_fraction_text(small)}, {_fraction_text(large)}이다. "
        f"이 중 {label}인 근은 {_fraction_text(answer)} 하나뿐이다."
    )


def _inverse(parent: VariantParent) -> VariantDraft | VariantSkip:
    """두 근에서 방정식을 복원하는 역문제 — 모닉(선두계수 1)·서로 다른 정수근 부모만."""
    sk = parent.skeleton
    if sk.root_kind != "integer":
        return VariantSkip(
            parent.slug,
            "inverse",
            "정수근 모닉 부모가 아님(상수배 자유도 때문에 두 근만으로 이차식이 유일하지 않다)",
        )
    r1, r2 = (int(r) for r in sk.roots)
    b_val, c_val = -(r1 + r2), r1 * r2
    asked = b_val + c_val
    # 유일성(SymPy 정확값) — 두 근을 대입한 선형 연립이 (b, c)를 단 하나로 정하는가.
    b_sym, c_sym = sympy.symbols("b c")
    solution = sympy.solve(
        [r1**2 + b_sym * r1 + c_sym, r2**2 + b_sym * r2 + c_sym], [b_sym, c_sym], dict=True
    )
    if solution != [{b_sym: b_val, c_sym: c_val}]:
        return VariantSkip(parent.slug, "inverse", "SymPy 유일성 확인 실패")

    spec = _spec_for(parent)
    generator = _generator_for(parent, "inverse")
    answer_text = str(asked)
    conditions = [
        f"({r1})**2 + b*({r1}) + c = 0",
        f"({r2})**2 + b*({r2}) + c = 0",
        "s = b + c",
    ]
    base = generator._build_candidate(  # noqa: SLF001
        spec,
        question_text=(
            f"x에 대한 이차방정식 x^2 + bx + c = 0 의 두 근이 {r1}, {r2} 일 때, "
            "b + c 의 값을 구하시오."
        ),
        answer_text=answer_text,
        explanation=(
            f"근과 계수의 관계에서 두 근의 합은 -b, 곱은 c 이다. 두 근의 합이 {r1 + r2} 이므로 "
            f"b = {b_val} 이고, 두 근의 곱이 {c_val} 이므로 c = {c_val} 이다. "
            f"따라서 b + c = {asked} 이다."
        ),
        answer_format=AnswerFormat.자연수 if asked > 0 else AnswerFormat.실수,
        difficulty=parent.difficulty,  # 역문제 축은 난이도 공식 밖 — 부모 계승(가산 금지)
        condition=conditions[0],
        selection="",
        steps=[
            f"(x - ({r1}))*(x - ({r2}))",
            sympy.sstr(sympy.expand((_ROOT_VAR - r1) * (_ROOT_VAR - r2))),
        ],
    )
    candidate = _with_lineage(
        base,
        parent,
        "inverse",
        conditions=conditions,
        answer_map={"b": str(b_val), "c": str(c_val), "s": answer_text},
        answer_selection=None,
    )
    return VariantDraft(
        parent=parent,
        move="inverse",
        candidate=candidate,
        spec=spec,
        dedup_key=f"inverse|{r1}|{r2}",
    )


_DERIVERS = {
    "ladder_harder": _ladder_harder,
    "ladder_easier": _ladder_easier,
    "condition_flip": _condition_flip,
    "condition_sign": _condition_sign,
    "inverse": _inverse,
}


def derive_variants(
    parent: VariantParent, moves: tuple[VariantMove, ...] = MOVES
) -> list[VariantDraft | VariantSkip]:
    """부모 1건에 대해 이동마다 정확히 1번 시도 — 결과는 항상 `len(moves)`개(자식 또는 skip).

    시도 수가 부모×이동으로 고정되므로 "작동한 비율"의 분모가 구조적으로 정의된다. 자식을 못
    낳은 시도는 `VariantSkip`으로 사유와 함께 남는다(조용한 누락 금지).
    """
    return [_DERIVERS[move](parent) for move in moves]
