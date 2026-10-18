"""슬롯 배정 규칙 — 로더 검증과 판정기 계약 (P3-05 3단계).

각 테스트는 "그 절이 없으면 통과해 버리는 입력"을 하나씩 갖는다(픽스처가 절을 실제로 밟는다).
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from whymath_backend.l1.standards.phase3_coverage import PROBLEM_ELIGIBLE_STATUS, ProblemRef
from whymath_backend.l1.standards.phase3_slot_rules import (
    SlotRulesError,
    decide_slot,
    default_rules_path,
    load_slot_rules,
    parse_slot_rules,
)
from whymath_backend.schema.problem_metadata import ProblemSlot

_C1 = "H:test-A"
_C2 = "H:test-B"


def _doc() -> dict[str, Any]:
    return {
        "version": 1,
        "banks": ["bank_x"],
        "scope_concepts": [_C1, _C2],
        "rules": [
            {
                "id": "hold-count",
                "when": {"concept": _C1, "folded_stem_contains": "개수"},
                "slot": None,
                "reason": "다른 개념의 행동",
            },
            {
                "id": "trigger",
                "when": {"has_own_misconception": True},
                "slot": "misconception_trigger",
            },
            {
                "id": "applied-a",
                "when": {"concept": _C1, "has_own_misconception": False},
                "slot": "applied",
            },
        ],
    }


def _problem(
    *,
    pid: str = "p1",
    concept: str = _C1,
    status: str | None = PROBLEM_ELIGIBLE_STATUS,
    stem: str | None = "f(x) = x^3 의 값을 구하시오",
    tags: tuple[str, ...] = (),
) -> ProblemRef:
    return ProblemRef(
        problem_id=pid,
        primary_src_ids=frozenset({concept}),
        review_status=status,
        has_explanation=True,
        has_steps=True,
        problem_type_codes=("ptype.evaluate-expression",),
        distractor_ids=(),
        tags=tags,
        question_text=stem,
    )


def _never(_: ProblemRef) -> bool:
    return False


def _always(_: ProblemRef) -> bool:
    return True


def _decide(problem: ProblemRef, reaches: Callable[[ProblemRef], bool] = _never) -> Any:
    rules = parse_slot_rules(_doc())
    return decide_slot(rules, problem, reaches, eligible_status=PROBLEM_ELIGIBLE_STATUS)


class TestParse:
    def test_valid_document_loads_in_order(self) -> None:
        rules = parse_slot_rules(_doc())
        assert [r.rule_id for r in rules.rules] == ["hold-count", "trigger", "applied-a"]
        assert rules.banks == ("bank_x",)
        assert rules.scope_concepts == frozenset({_C1, _C2})
        assert (
            rules.rules[0].slot is None and rules.rules[1].slot is ProblemSlot.MISCONCEPTION_TRIGGER
        )

    def _mutate(self, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        doc = deepcopy(_doc())
        change(doc)
        return doc

    @pytest.mark.parametrize(
        ("label", "change"),
        [
            ("최상위 알 수 없는 키", lambda d: d.update({"typo": 1})),
            ("version 불일치", lambda d: d.update({"version": 2})),
            ("banks 비어 있음", lambda d: d.update({"banks": []})),
            ("banks 중복", lambda d: d.update({"banks": ["a", "a"]})),
            ("scope_concepts 비어 있음", lambda d: d.update({"scope_concepts": []})),
            ("scope_concepts 중복", lambda d: d.update({"scope_concepts": [_C1, _C1]})),
            ("rules 비어 있음", lambda d: d.update({"rules": []})),
            ("규칙 id 중복", lambda d: d["rules"].append(deepcopy(d["rules"][1]))),
            ("규칙에 알 수 없는 키", lambda d: d["rules"][1].update({"typo": 1})),
            ("when 에 알 수 없는 조건 키", lambda d: d["rules"][1]["when"].update({"conept": _C1})),
            ("when 이 비어 있음", lambda d: d["rules"][1].update({"when": {}})),
            ("concept 가 범위 밖", lambda d: d["rules"][2]["when"].update({"concept": "H:other"})),
            ("알 수 없는 슬롯 id", lambda d: d["rules"][1].update({"slot": "aplied"})),
            ("slot 키 없음", lambda d: d["rules"][1].pop("slot")),
            ("보류인데 reason 없음", lambda d: d["rules"][0].pop("reason")),
            ("보류인데 reason 이 공백", lambda d: d["rules"][0].update({"reason": "  "})),
            (
                "has_own_misconception 이 문자열",
                lambda d: d["rules"][1]["when"].update({"has_own_misconception": "true"}),
            ),
            (
                "folded_stem_contains 가 빈 문자열",
                lambda d: d["rules"][0]["when"].update({"folded_stem_contains": ""}),
            ),
        ],
    )
    def test_structural_violations_fail_loudly(
        self, label: str, change: Callable[[dict[str, Any]], None]
    ) -> None:
        with pytest.raises(SlotRulesError):
            parse_slot_rules(self._mutate(change))

    def test_non_mapping_document_fails(self) -> None:
        with pytest.raises(SlotRulesError):
            parse_slot_rules(["not", "a", "mapping"])

    def test_missing_file_fails_with_the_exception_type_name(self, tmp_path: Path) -> None:
        with pytest.raises(SlotRulesError, match="FileNotFoundError"):
            load_slot_rules(tmp_path / "nope.yaml")

    def test_unparsable_yaml_fails_with_the_exception_type_name(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("a: [unclosed", encoding="utf-8")
        with pytest.raises(SlotRulesError, match="YAMLError|ParserError"):
            load_slot_rules(bad)

    def test_the_real_rules_file_loads_and_scopes_only_the_three_empty_concepts(self) -> None:
        rules = load_slot_rules(default_rules_path())
        assert rules.scope_concepts == frozenset(
            {"H:12미적Ⅰ02-01", "H:12미적Ⅰ02-02", "H:12미적Ⅰ02-07"}
        )
        assert rules.banks == (
            "problem_bank_conceptual_v0",
            "problem_bank_generated_v0",
            "problem_bank_misconception_mc_v0",
            "problem_bank_rephrased_v0",
        )
        # 새 은행이 규칙에 슬쩍 들어오면 슬롯 없는 새 문항이 거친 규칙으로 조용히 배정된다.
        assert not any("p3_calculus1_diff" in b for b in rules.banks)

    def test_yaml_round_trip_of_the_real_file_keeps_hold_reason(self) -> None:
        doc = yaml.safe_load(default_rules_path().read_text(encoding="utf-8"))
        holds = [r for r in doc["rules"] if r["slot"] is None]
        # 보류 규칙이 하나도 없을 수 있다(P3-49 가 유일한 보류 규칙을 폐기했다) — 있으면 사유는 필수다.
        # 보류 메커니즘 자체는 합성 규칙 테스트(hold-count)가 계속 지킨다.
        assert all(r.get("reason") for r in holds)


class TestDecide:
    def test_first_matching_rule_wins_even_if_a_later_rule_also_matches(self) -> None:
        """'개수' 문면은 보류 규칙과 오개념 유발 규칙에 둘 다 맞는다 — 위에 있는 보류가 이긴다."""
        problem = _problem(stem="삼차함수 f(x) = x^3 의 극값의 개수를 구하시오")
        decision = _decide(problem, _always)
        assert decision.rule_id == "hold-count" and decision.slot is None and decision.held

    def test_trigger_rule_uses_the_injected_misconception_judgement(self) -> None:
        assert _decide(_problem(), _always).slot is ProblemSlot.MISCONCEPTION_TRIGGER
        assert _decide(_problem(), _never).slot is ProblemSlot.APPLIED

    def test_unmatched_in_scope_problem_gets_no_slot_and_no_rule(self) -> None:
        """범위 안·승인인데 어떤 규칙에도 안 맞으면 억지로 채우지 않는다(C2는 응용 규칙 대상이 아니다)."""
        decision = _decide(_problem(concept=_C2), _never)
        assert decision.slot is None and decision.rule_id is None and decision.skipped is None

    def test_numbers_do_not_change_the_fold_match(self) -> None:
        a = _decide(_problem(stem="f(x) = x^3 - 3x 의 극값의 개수를 구하시오"), _never)
        b = _decide(_problem(stem="f(x) = x^5 - 7x 의 극값의 개수를 구하시오"), _never)
        assert a.rule_id == b.rule_id == "hold-count"

    def test_stem_condition_is_matched_against_the_folded_stem_not_the_raw_text(self) -> None:
        """조건 문자열에 `#`(접힌 숫자)가 들어 있으면 원문에는 그 문자열이 없다 — 접지 않고 비교하면 맞지 않는다.

        위의 `개수` 조건은 숫자가 없어 접든 안 접든 같은 결과라 이 절을 밟지 못한다(뮤테이션이 잡은 구멍).
        """
        doc = _doc()
        doc["rules"].insert(
            0,
            {
                "id": "folded-shape",
                "when": {"folded_stem_contains": "x^# - #x"},
                "slot": "diagnostic",
            },
        )
        rules = parse_slot_rules(doc)
        hit = decide_slot(
            rules,
            _problem(stem="f(x) = x^3 - 3x 의 값을 구하시오"),
            _never,
            eligible_status=PROBLEM_ELIGIBLE_STATUS,
        )
        assert hit.rule_id == "folded-shape" and hit.slot is ProblemSlot.DIAGNOSTIC
        # 대조군 — 접어도 모양이 다르면 맞지 않는다(과하게 맞추는 수정이 통과하지 못하게 한다).
        miss = decide_slot(
            rules,
            _problem(stem="f(x) = x^3 + 3x 의 값을 구하시오"),
            _never,
            eligible_status=PROBLEM_ELIGIBLE_STATUS,
        )
        assert miss.rule_id == "applied-a"

    def test_unknown_stem_does_not_match_a_stem_condition(self) -> None:
        """문면을 못 읽었으면 '개수'를 포함하는지 모른다 — 모르면 맞지 않는다(보류로 위장하지 않는다)."""
        decision = _decide(_problem(stem=None), _never)
        assert decision.rule_id == "applied-a"  # 보류 규칙을 건너뛰고 다음 규칙으로 간다
        assert not decision.held

    @pytest.mark.parametrize(
        ("kwargs", "reason"),
        [
            ({"status": None}, "not-approved"),
            ({"status": "draft"}, "not-approved"),
            ({"concept": "H:elsewhere"}, "out-of-scope"),
            ({"tags": ("p3-slot:basic",)}, "already-slotted"),
        ],
    )
    def test_problems_the_rules_must_not_touch_are_skipped_with_a_reason(
        self, kwargs: dict[str, Any], reason: str
    ) -> None:
        decision = _decide(_problem(**kwargs), _always)
        assert decision.slot is None and decision.skipped == reason

    def test_existing_slot_is_never_overwritten_even_when_a_rule_would_differ(self) -> None:
        decision = _decide(_problem(tags=("p3-slot:diagnostic",)), _always)
        assert decision.slot is None and decision.skipped == "already-slotted"

    def test_unrelated_tags_do_not_count_as_already_slotted(self) -> None:
        assert _decide(_problem(tags=("calc", "p3-bank")), _never).slot is ProblemSlot.APPLIED

    def test_misspelled_slot_tag_is_not_silently_treated_as_slotted(self) -> None:
        """오타 난 슬롯 태그는 슬롯이 아니다 — 계측기가 따로 실패로 보고하므로 여기서 덮지 않는다."""
        decision = _decide(_problem(tags=("p3-slot:aplied",)), _never)
        assert decision.skipped is None and decision.slot is ProblemSlot.APPLIED
