"""P3-76 — 수용 게이트 Tier2 · 야간 상시 재검증이 해석 단계(근 선택·대입)를 같은 의미로 판정한다.

두 게이트는 종전에 이웃 동치(`verify_solution`)만 봐서, P3-62 규칙 (가)(풀이 끝에 근 선택 +
대입 두 줄)를 넣은 문항을 Tier2 incorrect 로 떨어뜨렸다(수용 failed · 재검증 fail). P3-76 은 두
게이트를 Solution QA C4 와 같은 공용 판정(`verify_solution_interpreted`)으로 옮겼다.

여기서는 ①실 레코드 변형이 verified·pass 가 되는지 ②근거 없는 대입·틀린 근 선택·틀린 대입값이
failed·fail 로 남는지(RED) ③P3-71 반례(분수 약분·`.doit()` 래퍼·`exp(-log)`·0 지수·허수부가
아주 작은 근·초월 등식·섞인 제약·암묵 정의역)가 두 게이트에서도 통과하지 않는지 ④허용 목록 다항
증명(A10·DR2·다항식 미분)만 통과로 바뀌는지를 본다. 실 레코드를 찾지 못하면 실패한다(공허 통과 금지).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import corpus_reverify as cr
from whymath_backend.l3.equivalent.acceptance import _evaluate_verification

_ROOT = Path(__file__).resolve().parents[4]
_BANK = _ROOT / "data" / "corpus" / "problem_bank_p3_calculus1_diff_v0" / "problems.jsonl"
_SLUG = "wm-p3-diff-graphshape-e6551214a538"

Record = dict[str, Any]

# 규칙 (가) 꼴의 조건 — a 결정 등식 · a 대입 도함수 등식 · 선택 근거(f'' > 0) · 정의 등식.
_GA_CONDITIONS = [
    "Derivative(2*x**3 + a*x**2 - 72*x + 6, x).doit().subs(x, 4) = 0",
    "Derivative(2*x**3 - 3*x**2 - 72*x + 6, x).doit() = 0",
    "12*x - 6 > 0",
    "y = 2*x**3 - 3*x**2 - 72*x + 6",
]


def _real_record() -> Record:
    for line in _BANK.read_text(encoding="utf-8").splitlines():
        if _SLUG in line:
            record: Record = json.loads(line)
            return record
    pytest.fail(f"실 레코드 {_SLUG} 를 찾지 못함 — 이 테스트는 아무것도 검증하지 못한다")


def _variant(extra: list[str], conditions: list[str] | None = None) -> Record:
    record = copy.deepcopy(_real_record())
    verify = record["verify"]
    verify["conditions"] = list(conditions if conditions is not None else _GA_CONDITIONS)
    verify["solution_steps"] = [*verify["solution_steps"], *extra]
    assert record != _real_record(), "변형이 레코드를 바꾸지 못했다"
    return record


def _gates(record: Record) -> tuple[str, str]:
    verify = record["verify"]
    steps = verify.get("solution_steps")
    state, _ = _evaluate_verification(
        verify["conditions"],
        {str(k): str(v) for k, v in verify["answer_map"].items()},
        [str(s) for s in steps] if steps else None,
        None,
        verify.get("answer_selection"),
        verify.get("answer_aggregate"),
        record.get("answer"),
        verify.get("answer_kind"),
    )
    reverify, _ = cr._reverify_one(record, use_fuzz=False)
    return state, reverify


def _rec(conditions: list[str], answer: str, amap: dict[str, str], steps: list[str]) -> Record:
    return {
        "slug": "adv",
        "answer": answer,
        "verify": {"conditions": conditions, "answer_map": amap, "solution_steps": steps},
    }


class TestRealRecordRuleGa:
    def test_current_record_is_unchanged(self) -> None:
        assert _gates(_real_record()) == ("verified", "pass")

    def test_selection_and_substitution_lines_are_accepted(self) -> None:
        assert _gates(_variant(["x = 4", "y = -202"])) == ("verified", "pass")

    def test_selection_line_alone_is_accepted(self) -> None:
        assert _gates(_variant(["x = 4"])) == ("verified", "pass")

    def test_structured_selection_rule_is_the_basis(self) -> None:
        """도메인 부등식 대신 구조의 `answer_selection`(largest)이 근거인 꼴 — 게이트가 그 규칙을
        해석 판정에 넘긴다. 규칙을 어기면 failed·fail 이다.

        수용 게이트가 verified 가 아니라 unverified 인 것은 Tier2 때문이 아니라 그 뒤의 근 선택 검사
        (`verify_root_selection(조건 전체, …)`) 때문이다 — 다변수 조건 목록이라 선택을 확인하지 못해
        종전 규칙대로 강등한다(이 태스크가 바꾸지 않은 축). Tier2 가 incorrect 를 냈다면 failed 였다."""
        conditions = [c for c in _GA_CONDITIONS if c != "12*x - 6 > 0"]
        record = _variant(["x = 4", "y = -202"], conditions)
        record["verify"]["answer_selection"] = "largest"
        assert _gates(record) == ("unverified", "pass")
        record["verify"]["answer_selection"] = "smallest"  # 4 는 smallest 가 아니다
        assert _gates(record) == ("failed", "fail")

    @pytest.mark.parametrize(
        ("extra", "conditions"),
        [
            (["x = -3", "y = 141"], None),  # 틀린 근 선택(도메인 위반 근)
            (["x = 4", "y = -200"], None),  # 틀린 대입값
            (["x = 4", "y = -202"], [c for c in _GA_CONDITIONS if c != "12*x - 6 > 0"]),
            (["x = 4", "y = -202"], [c for c in _GA_CONDITIONS if not c.startswith("y =")]),
        ],
        ids=["wrong-root", "wrong-value", "no-selection-basis", "no-definition"],
    )
    def test_injections_stay_failed(self, extra: list[str], conditions: list[str] | None) -> None:
        assert _gates(_variant(extra, conditions)) == ("failed", "fail")


# P3-71 검토 반례 — main 에서 FAIL 이었고 허용 목록 밖이라 두 게이트에서도 FAIL 로 남아야 한다.
_STAY_FAILED: dict[str, Record] = {
    "A3d 도메인 위반 값 대입": _rec(
        ["a**2 - 4 = 0", "a > 0", "y = a**2 + 1"], "5", {"a": "2", "y": "5"}, ["a = -2", "y = 5"]
    ),
    "A3c 근 아닌 값 대입": _rec(
        ["x**3 = 27", "y = x**2"], "9", {"x": "3", "y": "9"}, ["x = -3", "y = 9"]
    ),
    "A4 정의 등식 없는 변수 전환": _rec(
        ["x**2 = 9", "x > 0"], "5", {"x": "3", "y": "5"}, ["x = 3", "y = 5"]
    ),
    "MV2 섞인 제약": {
        "slug": "adv",
        "answer": "3",
        "verify": {
            "conditions": ["x**2 - 4 = 0", "x > -5", "x + z > 100", "y = x + 1"],
            "answer_map": {"x": "2", "y": "3", "z": "200"},
            "answer_selection": "largest",
            "solution_steps": ["x = -2, x = 2", "x = 2", "y = 3"],
        },
    },
    "RF3 분수 약분 무연근": _rec(
        ["x*(x - 2)/(x - 2) = 2", "y = x + 1"], "3", {"x": "2", "y": "3"}, ["x = 2", "y = 3"]
    ),
    "RF5 음수 지수 표기": _rec(
        ["x*(x-2)*(x-2)**-1 = 2", "y = x + 1"], "3", {"x": "2", "y": "3"}, ["x = 2", "y = 3"]
    ),
    "T1 초월 등식": _rec(
        ["sin(x) = 1", "y = 2*x"], "pi", {"x": "pi/2", "y": "pi"}, ["x = pi/2", "y = pi"]
    ),
    "B1 .doit() 래퍼": _rec(
        ["(x*(x - 2)/(x - 2)).doit() = 2", "y = x + 1"],
        "3",
        {"x": "2", "y": "3"},
        ["x = 2", "y = 3"],
    ),
    "B3 exp(-log)": _rec(
        ["x*(x - 2)*exp(-log(x - 2)) = 2", "y = x + 1"],
        "3",
        {"x": "2", "y": "3"},
        ["x = 2", "y = 3"],
    ),
    "B10 0 지수": _rec(
        ["x*(x - 2)**0 = 2", "y = x + 1"], "3", {"x": "2", "y": "3"}, ["x = 2", "y = 3"]
    ),
    "D3 미분 래퍼 속 약분": _rec(
        ["Derivative(x**3*(x - 1)/(x - 1), x).doit() = 3", "x > 0", "y = x + 5"],
        "6",
        {"x": "1", "y": "6"},
        ["x = 1", "y = 6"],
    ),
    "NR1 허수부가 아주 작은 근": _rec(
        ["(x - 1)**2 + 10**(-20) = 0", "y = x + 1"], "2", {"x": "1", "y": "2"}, ["x = 1", "y = 2"]
    ),
}


@pytest.mark.parametrize("name", sorted(_STAY_FAILED))
def test_review_counterexamples_stay_failed(name: str) -> None:
    assert _gates(_STAY_FAILED[name]) == ("failed", "fail")


def test_implicit_domain_definition_is_not_a_proof() -> None:
    """ID1 — `y = log(x)` 는 x 를 제약하므로 정의로 면제하지 않는다. 근 선택은 판정 불가로 남고,
    대입은 종전 incorrect 그대로다."""
    record = {
        "slug": "adv",
        "answer": "log(2)",
        "verify": {
            "conditions": ["x**2 - 4 = 0", "y = log(x)"],
            "answer_map": {"x": "2", "y": "log(2)"},
            "answer_selection": "smallest",
            "solution_steps": ["x = -2, x = 2", "x = 2", "y = log(2)"],
        },
    }
    assert _gates(record) == ("failed", "fail")


# 허용 목록 다항 증명 — main 에서 FAIL 이던 것 중 이 판정 확장으로 통과하는 정당 대조군.
_NOW_PROVEN: dict[str, Record] = {
    "A10 도메인으로 고른 근의 대입": _rec(
        ["a**2 - 4 = 0", "a > 0", "y = a**2 + 1"],
        "5",
        {"a": "2", "y": "5"},
        ["a**2 - 4 = 0", "a = -2, a = 2", "a = 2", "y = 5"],
    ),
    "DR2 중근 다항식": _rec(
        ["(x-2)**2*(x+1) = 0", "x > 0", "y = x**2"], "4", {"x": "2", "y": "4"}, ["x = 2", "y = 4"]
    ),
    "DOK 다항식의 미분": _rec(
        ["Derivative(x**3, x).doit() = 3", "x > 0", "y = x + 5"],
        "6",
        {"x": "1", "y": "6"},
        ["x = -1, x = 1", "x = 1", "y = 6"],
    ),
}


@pytest.mark.parametrize("name", sorted(_NOW_PROVEN))
def test_allowlisted_polynomial_proofs_are_accepted(name: str) -> None:
    assert _gates(_NOW_PROVEN[name]) == ("verified", "pass")
