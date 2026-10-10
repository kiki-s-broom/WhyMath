"""변형 3종(PB-09) 단위테스트 — 부모 복원·이동별 불변식·계보 좌석·게이트 변별력(hermetic·LLM 0).

핵심 두 가지를 봉인한다.
  ① 각 이동이 *의도한 수학적 사실*을 만든다(정답 근 고정·난이도 방향·유일성·역문제 해).
     기대값은 구현과 독립으로 SymPy에서 다시 계산한다(구현 신뢰 금지).
  ② 수용 게이트가 이 자식들을 *실제로 가려낼 수 있다* — 정답을 망가뜨린 자식은 거부된다.
     모든 입력에서 초록인 검사는 검증이 아니므로(CLAUDE.md 보호 장치 실패 주입 규칙) 대조군을 둔다.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sympy

from whymath_backend.l3.equivalent.acceptance import evaluate_equivalent_candidate
from whymath_backend.l3.equivalent.variants import (
    MOVE_SPECS,
    MOVES,
    ParentRejection,
    VariantDraft,
    VariantMove,
    VariantParent,
    VariantSkip,
    derive_variants,
    parse_parent,
)
from whymath_backend.schema.enums import GenerationType, RelationType

_X = sympy.Symbol("x")


def _row(
    conditions: str,
    selection: str,
    answer: str,
    *,
    slug: str = "wm-skel-parent",
    unit: str = "QUAD-EQ",
    difficulty: float = 2.5,
) -> dict[str, Any]:
    """코퍼스 JSONL 행 모형 — 부모 복원이 읽는 필드만 담는다."""
    return {
        "slug": slug,
        "problem_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"test:{slug}")),
        "unit_codes": [unit],
        "achievement_standard_codes": ["[9수02-20]"],
        "difficulty_overall": difficulty,
        "subject": "공통",
        "curriculum_version": "2022_REVISION",
        "valid_from_year": 2022,
        "concepts": [{"concept_src_id": "HK06", "role": "PRIMARY", "relevance": 0.95}],
        "verify": {
            "conditions": conditions,
            "answer_map": {"x": answer},
            "answer_selection": selection,
        },
    }


def _parent(conditions: str, selection: str, answer: str, **kwargs: Any) -> VariantParent:
    parsed = parse_parent(_row(conditions, selection, answer, **kwargs))
    assert isinstance(parsed, VariantParent), parsed
    return parsed


def _draft(parent: VariantParent, move: VariantMove) -> VariantDraft:
    item = derive_variants(parent, (move,))[0]
    assert isinstance(item, VariantDraft), item
    return item


def _skip(parent: VariantParent, move: VariantMove) -> VariantSkip:
    item = derive_variants(parent, (move,))[0]
    assert isinstance(item, VariantSkip), item
    return item


def _roots(condition: str) -> set[sympy.Expr]:
    """조건 'lhs = rhs'의 실근 집합 — 구현과 독립인 SymPy 재계산."""
    lhs, rhs = condition.split("=")
    expr = sympy.sympify(lhs) - sympy.sympify(rhs)
    return set(sympy.solve(expr, _X))


# 정수근 (x−5)(x+4) = x² − x − 20 — 큰 근 5 / 작은 근 −4
_INT_LARGEST = ("x**2 - x - 20 = 0", "largest", "5")
_INT_SMALLEST = ("x**2 - x - 20 = 0", "smallest", "-4")
# (x−5)(2x+7) = 2x² − 3x − 35 — 정답 5(정수)·다른 근 −7/2(유리)
_RAT_ANSWER_INT = ("2*x**2 - 3*x - 35 = 0", "largest", "5")
# (2x+3)(x+4) = 2x² + 11x + 12 — 큰 근 −3/2(정답이 유리수)
_RAT_ANSWER_RAT = ("2*x**2 + 11*x + 12 = 0", "largest", "-3/2")


class TestParseParent:
    def test_integer_parent_is_restored(self) -> None:
        parent = _parent(*_INT_LARGEST)
        assert parent.skeleton.coefficients == (1, -1, -20)
        assert parent.skeleton.root_kind == "integer"

    def test_rational_parent_is_restored(self) -> None:
        parent = _parent(*_RAT_ANSWER_RAT)
        assert parent.skeleton.root_kind == "rational"

    @pytest.mark.parametrize(
        ("row", "reason_part"),
        [
            (_row(*_INT_LARGEST, unit="ARITH-SEQ"), "QUAD-EQ"),
            (_row("x**2 - x - 20 = 0", "unique", "5"), "largest/smallest"),
            (_row("x**2 - 2*x - 1 = 0", "largest", "1 + sqrt(2)"), "무리근"),
            (_row("x**2 - 4*x + 4 = 0", "largest", "2"), "중근"),
            (_row("x**2 + 1 = 0", "largest", "0"), "실근"),
            (_row("2*x**2 - 6*x + 4 = 0", "largest", "2"), "비원시"),
            (_row("x**2 - x - 20 = 0", "largest", "-4"), "불일치"),
            (_row("x > 0", "largest", "1"), "등식"),
        ],
    )
    def test_ineligible_parents_are_rejected_with_reason(
        self, row: dict[str, Any], reason_part: str
    ) -> None:
        parsed = parse_parent(row)
        assert isinstance(parsed, ParentRejection)
        assert reason_part in parsed.reason

    def test_missing_meta_is_rejected_not_raised(self) -> None:
        row = _row(*_INT_LARGEST)
        del row["problem_id"]
        parsed = parse_parent(row)
        assert isinstance(parsed, ParentRejection)


class TestLadder:
    def test_harder_keeps_answer_and_raises_difficulty(self) -> None:
        parent = _parent(*_INT_LARGEST)
        draft = _draft(parent, "ladder_harder")
        cand = draft.candidate
        assert cand.answer_selection == "largest"
        assert cand.answer_map == {"x": "5"}  # 같은 뿌리 — 정답 고정
        roots = _roots(str(cand.conditions))
        assert roots == {sympy.Integer(5), sympy.Rational(-9, 2)}  # 다른 근만 정답 반대쪽 반 칸
        assert max(roots) == 5  # 큰 근 문제가 뒤집히지 않는다
        assert cand.problem.difficulty_overall is not None
        assert cand.problem.difficulty_overall > parent.skeleton.difficulty

    def test_harder_moves_other_root_away_from_answer_for_smallest(self) -> None:
        parent = _parent(*_INT_SMALLEST)
        cand = _draft(parent, "ladder_harder").candidate
        assert cand.answer_map == {"x": "-4"}
        roots = _roots(str(cand.conditions))
        assert min(roots) == -4
        assert roots == {sympy.Integer(-4), sympy.Rational(11, 2)}

    def test_easier_keeps_answer_and_lowers_difficulty(self) -> None:
        parent = _parent(*_RAT_ANSWER_INT)
        draft = _draft(parent, "ladder_easier")
        cand = draft.candidate
        assert cand.answer_map == {"x": "5"}
        assert _roots(str(cand.conditions)) == {
            sympy.Integer(5),
            sympy.Integer(-3),
        }  # −7/2에 가장 가까운 정수
        assert cand.problem.difficulty_overall is not None
        assert cand.problem.difficulty_overall < parent.skeleton.difficulty

    def test_harder_then_easier_round_trips_to_the_original_pair(self) -> None:
        # 심화로 올렸다가 쉬운 쪽으로 내리면 원래 근 쌍으로 돌아온다 — 두 이동이 서로의 역이다.
        original = _parent(*_INT_LARGEST)
        harder = _draft(original, "ladder_harder").candidate
        back = _parent(
            str(harder.conditions), "largest", harder.answer_map["x"], slug="wm-skel-harder"
        )
        easier = _draft(back, "ladder_easier").candidate
        assert _roots(str(easier.conditions)) == _roots(_INT_LARGEST[0])

    def test_relations_use_existing_enum_slots(self) -> None:
        harder = _draft(_parent(*_INT_LARGEST), "ladder_harder")
        easier = _draft(_parent(*_RAT_ANSWER_INT), "ladder_easier")
        assert harder.relation_type == RelationType.심화
        assert easier.relation_type == RelationType.선수  # "기초" = 방향을 뒤집은 선수
        assert harder.generation_type == GenerationType.VARIANT_STRUCTURE

    def test_harder_is_skipped_when_parent_is_not_integer(self) -> None:
        skip = _skip(_parent(*_RAT_ANSWER_INT), "ladder_harder")
        assert "정수근" in skip.reason

    def test_easier_is_skipped_when_answer_is_already_rational(self) -> None:
        # 정답 근이 유리수면 다른 근을 정수로 바꿔도 난이도 공식이 변하지 않는다 — 계열이 아니다.
        skip = _skip(_parent(*_RAT_ANSWER_RAT), "ladder_easier")
        assert "유리수" in skip.reason

    def test_easier_is_skipped_for_integer_parent(self) -> None:
        skip = _skip(_parent(*_INT_LARGEST), "ladder_easier")
        assert "유리근" in skip.reason


class TestConditionFlip:
    def test_flip_asks_the_other_root_of_the_same_equation(self) -> None:
        parent = _parent(*_INT_LARGEST)
        draft = _draft(parent, "condition_flip")
        assert draft.candidate.answer_selection == "smallest"
        assert draft.candidate.answer_map == {"x": "-4"}
        assert _roots(str(draft.candidate.conditions)) == _roots(_INT_LARGEST[0])
        assert draft.relation_type == RelationType.변형
        assert draft.generation_type == GenerationType.VARIANT_CONTEXT


class TestConditionSign:
    def test_sign_prefers_the_root_different_from_parent_answer(self) -> None:
        parent = _parent(*_INT_LARGEST)  # 부모 정답 5 → 음수 조건이 다른 근(−4)을 고른다
        cand = _draft(parent, "condition_sign").candidate
        assert isinstance(cand.conditions, list) and cand.conditions[1] == "x < 0"
        assert _roots(cand.conditions[0]) == _roots("x**2 - x - 20 = 0")
        assert cand.answer_map == {"x": "-4"}
        assert cand.answer_selection is None
        roots = _roots("x**2 - x - 20 = 0")
        assert [r for r in roots if r < 0] == [sympy.Integer(-4)]  # 유일성을 독립 재계산

    def test_sign_with_zero_root_uses_the_only_usable_sign(self) -> None:
        parent = _parent("x**2 - 5*x = 0", "smallest", "0")
        cand = _draft(parent, "condition_sign").candidate
        assert cand.conditions[1] == "x > 0"  # type: ignore[index]
        assert cand.answer_map == {"x": "5"}

    def test_sign_is_skipped_when_roots_share_a_sign(self) -> None:
        skip = _skip(_parent("x**2 - 5*x + 6 = 0", "largest", "3"), "condition_sign")
        assert "가르지 못함" in skip.reason

    def test_sign_inherits_parent_difficulty(self) -> None:
        parent = _parent(*_INT_LARGEST)
        cand = _draft(parent, "condition_sign").candidate
        assert cand.problem.difficulty_overall == parent.difficulty  # 가산 근거 없음


class TestInverse:
    def test_inverse_recovers_equation_from_roots(self) -> None:
        parent = _parent("x**2 - x - 6 = 0", "largest", "3")  # (x−3)(x+2)
        draft = _draft(parent, "inverse")
        cand = draft.candidate
        # 독립 재계산: 두 근을 대입한 선형 연립의 유일해
        b, c = sympy.symbols("b c")
        assert sympy.solve([9 + 3 * b + c, 4 - 2 * b + c], [b, c]) == {b: -1, c: -6}
        assert cand.answer_map == {"b": "-1", "c": "-6", "s": "-7"}
        assert cand.problem.answer == "-7"
        assert "b + c" in cand.problem.question_text
        assert draft.relation_type == RelationType.대조

    def test_inverse_is_skipped_for_non_monic_parent(self) -> None:
        skip = _skip(_parent(*_RAT_ANSWER_INT), "inverse")
        assert "모닉" in skip.reason


class TestLineageAndShape:
    @pytest.mark.parametrize("move", MOVES)
    def test_every_draft_carries_variant_provenance_not_fully_generated(
        self, move: VariantMove
    ) -> None:
        # 이동마다 그 이동을 낳는 부모를 골라, 어떤 자식도 FULLY_GENERATED로 새지 않음을 본다.
        parent_by_move: dict[VariantMove, tuple[str, str, str]] = {
            "ladder_harder": _INT_LARGEST,
            "ladder_easier": _RAT_ANSWER_INT,
            "condition_flip": _INT_LARGEST,
            "condition_sign": _INT_LARGEST,
            "inverse": _INT_LARGEST,
        }
        parent = _parent(*parent_by_move[move])
        prov = _draft(parent, move).candidate.provenance
        assert prov.generation_type == MOVE_SPECS[move].generation_type.value
        assert prov.generation_type != GenerationType.FULLY_GENERATED.value
        assert prov.original_source is None
        assert prov.parent_problem_id == parent.problem_id
        assert prov.transformation_pipeline is not None
        assert prov.transformation_pipeline["parent_slug"] == parent.slug
        assert prov.transformation_pipeline["variant_move"] == move

    @pytest.mark.parametrize(
        "args", [_INT_LARGEST, _INT_SMALLEST, _RAT_ANSWER_INT, _RAT_ANSWER_RAT]
    )
    def test_each_parent_yields_exactly_one_result_per_move(self, args: tuple[str, ...]) -> None:
        results = derive_variants(_parent(*args))
        assert len(results) == len(MOVES)  # 시도 회계의 분모가 구조적으로 고정된다
        assert [r.move for r in results] == list(MOVES)

    def test_all_relation_types_are_existing_enum_values(self) -> None:
        valid = {r for r in RelationType}
        assert {spec.relation_type for spec in MOVE_SPECS.values()} <= valid
        assert set(MOVE_SPECS) == set(MOVES)

    def test_slugs_are_deterministic_and_distinct_from_parent(self) -> None:
        parent = _parent(*_INT_LARGEST)
        first = [
            d.candidate.problem.slug for d in derive_variants(parent) if isinstance(d, VariantDraft)
        ]
        second = [
            d.candidate.problem.slug for d in derive_variants(parent) if isinstance(d, VariantDraft)
        ]
        assert first == second
        assert parent.slug not in first
        assert len(set(first)) == len(first)


class TestGateDiscrimination:
    """게이트가 이 자식들을 통과시키기만 하는 도장이 아님을 대조군으로 증명한다."""

    @staticmethod
    def _gate(draft: VariantDraft, **overrides: Any) -> Any:
        c = draft.candidate
        return evaluate_equivalent_candidate(
            draft.spec,
            c.problem,
            provenance=c.provenance,
            conditions=overrides.get("conditions", c.conditions),
            answer_map=overrides.get("answer_map", c.answer_map),
            solution_steps=c.solution_steps,
            answer_selection=overrides.get("answer_selection", c.answer_selection),
        )

    @pytest.mark.parametrize(
        ("args", "move"),
        [
            (_INT_LARGEST, "ladder_harder"),
            (_RAT_ANSWER_INT, "ladder_easier"),
            (_INT_LARGEST, "condition_flip"),
            (_INT_LARGEST, "condition_sign"),
            (_INT_LARGEST, "inverse"),
        ],
    )
    def test_genuine_children_are_accepted(self, args: tuple[str, ...], move: VariantMove) -> None:
        verdict = self._gate(_draft(_parent(*args), move))
        assert verdict.accepted, verdict.reasons

    def test_wrong_root_is_rejected_for_selection_children(self) -> None:
        # 큰 근 문제에 작은 근을 답으로 — Tier1만으론 통과하지만 근 선택 검산이 잡는다.
        draft = _draft(_parent(*_INT_LARGEST), "ladder_harder")
        verdict = self._gate(draft, answer_map={"x": "-9/2"})
        assert not verdict.accepted

    def test_sign_child_with_excluded_root_is_rejected(self) -> None:
        # 음수 조건인데 양수 근을 답으로 — 부호 조건이 Tier1에서 위반된다.
        draft = _draft(_parent(*_INT_LARGEST), "condition_sign")
        verdict = self._gate(draft, answer_map={"x": "5"})
        assert not verdict.accepted

    def test_inverse_child_with_wrong_sum_is_rejected(self) -> None:
        draft = _draft(_parent("x**2 - x - 6 = 0", "largest", "3"), "inverse")
        verdict = self._gate(draft, answer_map={"b": "-1", "c": "-6", "s": "-6"})
        assert not verdict.accepted

    def test_inverse_child_with_wrong_coefficient_is_rejected(self) -> None:
        draft = _draft(_parent("x**2 - x - 6 = 0", "largest", "3"), "inverse")
        verdict = self._gate(draft, answer_map={"b": "1", "c": "-6", "s": "-5"})
        assert not verdict.accepted
