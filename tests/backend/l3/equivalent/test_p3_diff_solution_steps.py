"""P3-03 미분 은행 풀이 단계(`verify.solution_steps`) — 도출 모듈·커밋 은행의 소비처 계약·변별력.

검증 축
-------
① 모듈 단위 — 도함수 전개·대입 변환, 전략 A/B/C 선택, 정답 미도달·도출 불가의 fail-loud.
② **커밋된 은행**(hermetic·생성 0) — 504건 전부 단계 보유, 단계마다 검증기 파서로 파싱, 소비처 계약:
   · 수용 게이트(`acceptance._evaluate_verification`): 단계 동봉 상태로 verified(Tier2 전이 전건 correct).
     게이트가 단계를 보지 않는 개념형(`answer_kind`) 문항은 `verify_solution` 전건 correct를 따로 본다.
   · 적재기(`populate`)가 단계를 그대로 싣는다 · 계측기(`phase3_coverage`)가 '단계 있음'으로 센다 ·
     WH-S replay(`corpus_replay`)가 문자열 조건 문항을 전부 replay 대상으로 잡는다.
   · 마지막 단계 — 정답에 도달하거나(값·근 목록), 근 목록이면 선택(조건·answer_selection)이 정답
     하나를 고른다. 끝맺음 분포는 스냅숏으로 동결한다.
③ **변별력** — 마지막 단계를 틀린 값으로·중간 단계를 비동치로·빈 목록·정답 근 삭제를 주입하면 계약
   검사기가 위반을 낸다(주입이 실제로 적용됐는지 `mutated != original`로 먼저 단언).
④ 생성기(`corpus_authoring`) — 검산 조건에 도함수가 없는 문항만 출발식을 달고, 그 출발식에는 도함수가
   있으며, 도출 불가·정답 미도달 문항은 빌드(`items()`)가 멈춘다.
"""

from __future__ import annotations

import collections
import copy
import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

import pytest
import sympy
from sympy.parsing.sympy_parser import parse_expr, standard_transformations

from whymath_backend.harness import corpus_reverify
from whymath_backend.harness.p3_calculus1_diff_batch import CORPUS_DIR_NAME, GENERATORS
from whymath_backend.l1.problem_bank.populate import load_problem_bank_records
from whymath_backend.l1.standards import phase3_coverage as pc
from whymath_backend.l3.equivalent.acceptance import _evaluate_verification
from whymath_backend.l3.equivalent.p3_diff_power_derivative_skeleton_generator import (
    P3DiffPowerDerivativeGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    SLOT_IDS,
    DiffItem,
    P3DiffSlotGenerator,
    steps_of,
)
from whymath_backend.l3.equivalent.p3_diff_solution_steps import (
    apply_subs,
    derive_setup,
    expand_derivatives,
    final_solution_values,
    solution_steps,
)
from whymath_backend.l3.symbolic_equivalence import _parse, to_sympy_source
from whymath_backend.l3.verify_solution import verify_solution
from whymath_backend.whs.corpus_replay import load_replay_items

_BANK = Path(__file__).resolve().parents[4] / "data" / "corpus" / CORPUS_DIR_NAME / "problems.jsonl"
_DERIVATIVE = "Derivative"
#: 평균값 정리의 결론(f'(c) = 평균변화율)만 묻는 진단 틀 둘 — 출발식에 도함수가 없는 틀은 이 둘뿐이다
#: (`p3_diff_solution_steps` docstring '한계'). ① 함수식 없음(미분할 함수가 없다) ② 함수식이 있는 짝
#: (5회차 감사 교정 · 구판 '두 실근은 …이다' 근 나열 틀의 대체 — c를 구하지 않고 f'(c)를 정하는 것이
#: 진단 대상이라 평균변화율 산술이 곧 풀이다).
_NO_FUNCTION_STEM = "f'(c) = k인 c가"
_CONCLUSION_STEMS = (_NO_FUNCTION_STEM, "평균값 정리를 만족시키는 c가 있다. f'(c)의 값을 구하시오.")
_OPS = (("<=", "le"), (">=", "ge"), ("!=", "ne"), ("<", "lt"), (">", "gt"))

#: 마지막 단계의 끝맺음 분포 — 스냅숏(값만 갱신 가능 · 이유를 주석으로 남긴다 · 약화 금지).
#: 2026-10-07 최초 동결(P3-03 풀이 단계 도입 · 504건).
#: 2026-10-08 갱신(5회차 감사 교정 · 틀 재설계): 정답 1개 272 → 251, 근 목록·선택 101 → 122(합 불변).
#: 이차 함수의 평균값 정리·롤·속도 0 틀(도함수가 일차라 근이 하나)을 삼차로 바꿔 f'(c) = 평균변화율·
#: v(t) = 0이 이차방정식이 되었다 — 근 두 개 중 구간·부호 조건이 정답을 고른다(이차 지름길 제거의
#: 직접 결과). 정답 대입 검산(B) 19건은 건수가 같지만 구성이 바뀌었다 — 이차 끝점 틀 6건이 삼차 끝점
#: 틀 6건으로 대체(끝점이 미지수인 방정식은 근 목록 연쇄로 표현되지 않는다).
#: 2026-10-08 갱신(7회차 · 은행 감사 3회차 교정): 정답 1개 251 → 252, 근 목록·선택 122 → 128, 정답 대입
#: 검산(B) 19 → 12(합 불변). ① 02-05 이차곡선 접점 틀(기울기·평행·수직·y = x^2 오개념 유발)을 삼차로
#: 바꿔 f'(a) = m이 이차방정식이 됐다 — 근 둘 중 '양수 a'가 정답을 고른다(정답 1개 -6 · 근 목록 +6).
#: ② 02-03 'cx^m 꼴의 m만'(`= c·2**m`)·'f'(x) = 8x^7일 때 n'(`x**n`)은 미지수가 지수에 있어 근 목록으로
#: 끝나지 않던(B) 문항 7건이다 — c + m · c와 m의 곱 · 계수 k(일차 미지수)를 묻게 바꿔 정답 1개가 됐다.
_ENDING_SNAPSHOT: dict[str, int] = {
    "정답 1개(u = 정답)": 252,
    # 단일 미지수 근 목록 — 보호 조건(a > 0 등) 또는 answer_selection이 정답 하나만 남긴다.
    "근 목록 · 선택 조건이 정답 하나를 고름": 128,
    # 정답 사전에 다른 미지수(y·a·b·k)가 함께 있는 연립 — 근 선택은 그 미지수의 조건(극값의 값 등)이
    # 맡는다. 여기서는 정답이 보호 조건을 통과하는지만 본다.
    "근 목록 · 연립(다른 미지수 조건이 고름)": 48,
    "정답 대입 검산 연쇄(B)": 12,
    "도함수 식 연쇄(C · 허근 인수 임계점)": 8,
    "경계점(정답은 증감 구간 안 정수)": 6,
    "근 목록 · 정답 변수 아님(개수·위치)": 50,
}


# ──────────────────────────────────────────────────────────────────────────
# 공용 도구
# ──────────────────────────────────────────────────────────────────────────
def _rows() -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in _BANK.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


@pytest.fixture(scope="module")
def rows() -> list[dict[str, Any]]:
    return _rows()


def _p(text: str) -> sympy.Expr:
    return sympy.sympify(parse_expr(text, transformations=standard_transformations))


def _conditions(row: dict[str, Any]) -> list[str]:
    raw = row["verify"]["conditions"]
    return [raw] if isinstance(raw, str) else list(raw)


def _constraint(text: str) -> sympy.Basic | None:
    for op, name in _OPS:
        if op in text:
            lhs, rhs = text.split(op)
            return sympy.Rel(_p(lhs), _p(rhs), name)
    return None


def _top_level_parts(text: str, sep: str) -> list[str]:
    """괄호 밖의 구분자로만 나눈다(`.subs(x, 2)`·`Derivative(f, x)` 안의 쉼표는 그대로 둔다)."""
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == sep and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def _parse_every_side(step: str) -> None:
    """단계를 검증기와 같은 파서(`symbolic_equivalence._parse`)로 읽는다 — 실패하면 예외.

    근 목록(`a = -6, a = 6`)은 최상위 쉼표로, 등식은 최상위 `=`로 나눠 변마다 읽는다.
    """
    for part in _top_level_parts(step, ","):
        for side in _top_level_parts(part, "="):
            _parse(to_sympy_source(side))


def _is_boundary(row: dict[str, Any]) -> bool:
    """도함수 부호 조건만 있는 문항 — 연쇄의 근은 증감 구간의 끝점(정답은 그 안의 정수)."""
    conds = _conditions(row)
    has_equation = any(c.count("=") == 1 and _constraint(c) is None for c in conds)
    return not has_equation and any(_DERIVATIVE in c for c in conds)


def _ending(row: dict[str, Any]) -> str:
    """마지막 단계의 끝맺음 분류(스냅숏 키) — 정답 도달 위반이면 'VIOLATION: …'."""
    verify = row["verify"]
    steps = verify["solution_steps"]
    final = final_solution_values(steps[-1])
    answer_map: dict[str, str] = verify["answer_map"]
    if final is None:
        return (
            "정답 대입 검산 연쇄(B)"
            if ".subs(" in steps[0]
            else "도함수 식 연쇄(C · 허근 인수 임계점)"
        )
    variable, values = final
    if variable not in answer_map:
        return "근 목록 · 정답 변수 아님(개수·위치)"
    answer = _p(answer_map[variable])
    if not any(sympy.simplify(v - answer) == 0 for v in values):
        if _is_boundary(row):
            return "경계점(정답은 증감 구간 안 정수)"
        return f"VIOLATION: 마지막 근 목록에 정답 {variable} = {answer}이 없다"
    if len(values) == 1:
        return "정답 1개(u = 정답)"
    symbol = sympy.Symbol(variable)
    relations = [
        rel
        for c in _conditions(row)
        if (rel := _constraint(c)) is not None and symbol in rel.free_symbols
    ]
    kept = [v for v in values if all(bool(rel.subs(symbol, v)) for rel in relations)]
    if not any(sympy.simplify(v - answer) == 0 for v in kept):
        return "VIOLATION: 보호 조건이 정답을 뺀다"
    if set(answer_map) != {variable}:
        return "근 목록 · 연립(다른 미지수 조건이 고름)"
    selection = verify.get("answer_selection")
    if selection in ("largest", "smallest"):
        kept = [max(values, key=float) if selection == "largest" else min(values, key=float)]
    if len(kept) == 1 and sympy.simplify(kept[0] - answer) == 0:
        return "근 목록 · 선택 조건이 정답 하나를 고름"
    return "VIOLATION: 단일 미지수인데 선택 조건이 정답 하나를 고르지 못한다"


def _contract_violations(row: dict[str, Any]) -> list[str]:
    """한 레코드의 단계 계약 위반 — 빈 리스트면 통과(뮤테이션 테스트와 은행 전수가 같은 함수를 쓴다)."""
    steps = row["verify"].get("solution_steps")
    if not isinstance(steps, list) or len(steps) < 2:
        return ["단계가 없거나 2개 미만"]
    if not all(isinstance(s, str) and s.strip() for s in steps):
        return ["빈 단계·문자열 아님"]
    out: list[str] = []
    for step in steps:
        try:
            _parse_every_side(step)
        except Exception as exc:  # noqa: BLE001 — 파싱 실패 종류와 무관하게 위반으로 센다
            out.append(f"파싱 불가({type(exc).__name__}): {step}")
    result = verify_solution(steps)
    if result.n_transitions < 1 or result.n_correct != result.n_transitions:
        out.append(
            f"전이 판정: correct {result.n_correct}/{result.n_transitions} "
            f"(incorrect {result.n_incorrect}·unverifiable {result.n_unverifiable})"
        )
    ending = _ending(row)
    if ending.startswith("VIOLATION"):
        out.append(ending)
    return out


# ──────────────────────────────────────────────────────────────────────────
# ① 모듈 단위
# ──────────────────────────────────────────────────────────────────────────
def test_expand_derivatives_and_apply_subs_follow_the_student_steps() -> None:
    setup_side = "Derivative(x**3 - 2*x, x).doit().subs(x, -2)"
    expanded = expand_derivatives(setup_side)
    assert expanded == "(3*x**2 - 2).subs(x, -2)"
    assert apply_subs(expanded) == "(3*(-2)**2 - 2)"
    # 도함수가 산술과 섞인 출발식(식 전체에 .doit().subs) — 접선 y = f'(a)(x - a) + f(a)의 x = 1 값.
    mixed = "(x**2 + Derivative(x**2, x)*((1) - x)).doit().subs(x, 3)"
    assert expand_derivatives(mixed) == "(x**2 + (2*x)*((1) - x)).subs(x, 3)"
    assert apply_subs(expand_derivatives(mixed)) == "((3)**2 + (2*(3))*((1) - (3)))"


def test_strategy_a_reaches_the_answer_from_the_derivative_setup() -> None:
    chain = solution_steps(
        conditions=("Derivative(x**3, x).doit().subs(x, a) = 108", "a > 0"),
        answer_map={"a": "6"},
    )
    assert chain.strategy == "A"
    assert chain.steps == (
        "Derivative(x**3, x).doit().subs(x, a) = 108",
        "(3*x**2).subs(x, a) = 108",
        "3*(a)**2 = 108",
        "3*a**2 - 108 = 0",
        "3*(a - 6)*(a + 6) = 0",
        "a = -6, a = 6",
    )


def test_strategy_b_checks_the_answer_when_the_equation_is_undecidable() -> None:
    # 미지수가 지수에 있으면 해집합 판정 불가 — 정답을 넣어 양변이 같은 값임을 보인다.
    chain = solution_steps(
        conditions="Derivative(x**3, x).doit().subs(x, 2) = 3*2**m",
        answer_map={"m": "2"},
    )
    assert chain.strategy == "B"
    assert chain.steps == (
        "Derivative(x**3, x).doit().subs(x, 2)",
        "(3*x**2).subs(x, 2)",
        "3*(2)**2",
        "12",
        "3*2**2",
    )


def test_strategy_c_comes_first_for_a_critical_point_with_a_complex_factor() -> None:
    chain = solution_steps(
        conditions=("Derivative(2*x**4 + 8*x + 11, x).doit() = 0", "y = 2*x**4 + 8*x + 11"),
        answer_map={"x": "-1", "y": "5"},
    )
    assert chain.strategy == "C"
    assert chain.steps == (
        "Derivative(2*x**4 + 8*x + 11, x).doit()",
        "8*x**3 + 8",
        "8*(x + 1)*(x**2 - x + 1)",
    )


def test_derive_setup_turns_sign_conditions_and_root_counts_into_critical_point_equations() -> None:
    assert (
        derive_setup(("Derivative(x**3 - 3*x, x).doit() < 0",), None)
        == "Derivative(x**3 - 3*x, x).doit() = 0"
    )
    assert (
        derive_setup("x**3 - 12*x = 2", "real_root_count")
        == "Derivative(x**3 - 12*x, x).doit() = 0"
    )
    assert (
        derive_setup("3*x**4 - 8*x**3 = 6*x**2 - 24*x - 11", "real_root_count")
        == "Derivative(3*x**4 - 8*x**3 - (6*x**2 - 24*x - 11), x).doit() = 0"
    )


def test_unreached_answer_is_a_hard_error_not_a_fallback() -> None:
    """정답이 근 목록에 없으면 B·C로 넘어가지 않고 멈춘다 — C(도함수 식)가 오류를 가리지 못하게."""
    with pytest.raises(ValueError, match="정답"):
        solution_steps(
            conditions="Derivative(x**3, x).doit().subs(x, a) = 108", answer_map={"a": "5"}
        )


def test_underivable_setup_raises_instead_of_emitting_unverified_steps() -> None:
    with pytest.raises(ValueError, match="풀이 단계를 만들 수 없다"):
        solution_steps(conditions="x**5 - x - 1 = 0", answer_map={})


def test_final_solution_values_reads_only_assignments() -> None:
    variable, values = final_solution_values("a = -6, a = 6") or ("", ())
    assert variable == "a" and values == (sympy.Integer(-6), sympy.Integer(6))
    assert final_solution_values("12") is None
    assert final_solution_values("3*a**2 - 108 = 0") is None


# ──────────────────────────────────────────────────────────────────────────
# ② 커밋된 은행 — 소비처 계약(hermetic)
# ──────────────────────────────────────────────────────────────────────────
def test_every_record_carries_solution_steps(rows: list[dict[str, Any]]) -> None:
    assert len(rows) == 504
    for row in rows:
        steps = row["verify"].get("solution_steps")
        assert isinstance(steps, list) and len(steps) >= 2, row["slug"]
        assert all(isinstance(s, str) and s.strip() for s in steps), row["slug"]
        assert "review_status" not in row


def test_every_step_parses_with_the_verifier_parser(rows: list[dict[str, Any]]) -> None:
    failures: list[str] = []
    for row in rows:
        for step in row["verify"]["solution_steps"]:
            try:
                _parse_every_side(step)
            except Exception as exc:  # noqa: BLE001 — 실패 종류와 무관하게 슬러그와 함께 모은다
                failures.append(f"{row['slug']}: {type(exc).__name__}: {step}")
    assert failures == []


def test_acceptance_gate_verifies_every_record_with_its_steps(rows: list[dict[str, Any]]) -> None:
    """수용 게이트의 실제 계약 — 단계를 실은 채 verified(Tier2 전이 전건 correct + Tier1 + 근 선택).

    게이트는 개념형(`answer_kind`) 문항의 단계를 보지 않으므로(Tier2 앞에서 반환) 그 문항은
    `verify_solution` 전건 correct를 따로 단언한다(빈 단계 묶음이 '검증됨'으로 위장되지 않게).
    """
    unverified: list[str] = []
    for row in rows:
        verify = row["verify"]
        steps = verify["solution_steps"]
        if verify.get("answer_kind") is not None:
            result = verify_solution(steps)
            if not (result.n_transitions >= 1 and result.n_correct == result.n_transitions):
                unverified.append(
                    f"{row['slug']}: kind 문항 Tier2 {result.n_correct}/{result.n_transitions}"
                )
            continue
        state, reasons = _evaluate_verification(
            verify["conditions"],
            verify["answer_map"],
            steps,
            None,
            verify.get("answer_selection"),
            verify.get("answer_aggregate"),
            row.get("answer"),
            verify.get("answer_kind"),
        )
        if state != "verified":
            unverified.append(f"{row['slug']}: {state} {reasons}")
    assert unverified == []


def test_contract_and_ending_snapshot(rows: list[dict[str, Any]]) -> None:
    """정답 도달·선택 일관성 — 끝맺음 분포 동결(위반 0건)."""
    endings = collections.Counter(_ending(row) for row in rows)
    violations = {k: n for k, n in endings.items() if k.startswith("VIOLATION")}
    assert violations == {}
    assert dict(endings) == _ENDING_SNAPSHOT


def test_first_step_differentiates_except_the_function_free_mvt_diagnostic(
    rows: list[dict[str, Any]],
) -> None:
    without = [r for r in rows if _DERIVATIVE not in r["verify"]["solution_steps"][0]]
    # 3 → 6(5회차 감사 교정): 함수식이 있는 결론 진단 틀 3문항이 더해졌다 — 틀마다 3문항씩.
    assert len(without) == 6
    assert all(any(stem in str(r["question_text"]) for stem in _CONCLUSION_STEMS) for r in without)
    for stem in _CONCLUSION_STEMS:
        assert sum(stem in str(r["question_text"]) for r in without) == 3, stem


def test_loader_meter_and_replay_consume_the_steps(rows: list[dict[str, Any]]) -> None:
    """적재기·계측기·WH-S replay가 단계를 실제로 읽는다(형식 계약)."""
    records = load_problem_bank_records(_BANK)
    assert len(records) == len(rows)
    by_slug = {r["slug"]: r for r in rows}
    for record in records:
        assert (
            record.verify.solution_steps == by_slug[record.problem.slug]["verify"]["solution_steps"]
        )
    refs = [pc._problem_from_row(row) for row in rows]
    assert all(ref is not None and ref.has_steps and ref.has_explanation for ref in refs)
    replay = load_replay_items(_BANK.read_text(encoding="utf-8"))
    string_conditions = [r for r in rows if isinstance(r["verify"]["conditions"], str)]
    assert len(replay) == len(string_conditions)


# ──────────────────────────────────────────────────────────────────────────
# ③ 변별력 — 주입하면 계약 검사기가 위반을 낸다
# ──────────────────────────────────────────────────────────────────────────
def _pick(rows: Sequence[dict[str, Any]], ending: str) -> dict[str, Any]:
    return copy.deepcopy(next(r for r in rows if _ending(r) == ending))


def _mutated(row: dict[str, Any], steps: list[str]) -> dict[str, Any]:
    out = copy.deepcopy(row)
    out["verify"]["solution_steps"] = steps
    assert out != row  # 주입이 실제로 적용됐다
    return out


def test_control_rows_have_no_violations(rows: list[dict[str, Any]]) -> None:
    for ending in _ENDING_SNAPSHOT:
        assert _contract_violations(_pick(rows, ending)) == [], ending


def test_wrong_last_step_is_caught(rows: list[dict[str, Any]]) -> None:
    row = _pick(rows, "정답 1개(u = 정답)")
    steps = list(row["verify"]["solution_steps"])
    variable, values = final_solution_values(steps[-1]) or ("", ())
    steps[-1] = f"{variable} = {values[0] + 1}"
    bad = _mutated(row, steps)
    violations = _contract_violations(bad)
    assert any("전이 판정" in v for v in violations)
    assert any("VIOLATION" in v for v in violations)
    state, _ = corpus_reverify._reverify_one(bad, use_fuzz=False)
    assert state == "fail"


def test_non_equivalent_middle_step_is_caught(rows: list[dict[str, Any]]) -> None:
    row = _pick(rows, "정답 1개(u = 정답)")
    steps = list(row["verify"]["solution_steps"])
    middle = next(i for i, s in enumerate(steps) if s.startswith("(") and ".subs(" in s)
    expr = steps[middle]
    close = expr.index(").subs(")
    steps[middle] = f"{expr[:close]} + 1{expr[close:]}"  # 도함수 전개형에 상수 1을 더한다
    bad = _mutated(row, steps)
    assert any("전이 판정" in v for v in _contract_violations(bad))
    state, _ = corpus_reverify._reverify_one(bad, use_fuzz=False)
    assert state == "fail"


def test_empty_steps_are_caught_and_drop_the_meter_link(rows: list[dict[str, Any]]) -> None:
    row = _pick(rows, "정답 1개(u = 정답)")
    bad = _mutated(row, [])
    assert _contract_violations(bad) == ["단계가 없거나 2개 미만"]
    ref = pc._problem_from_row(bad)
    assert ref is not None and not ref.has_steps


def test_dropping_the_answer_root_is_caught(rows: list[dict[str, Any]]) -> None:
    row = _pick(rows, "근 목록 · 선택 조건이 정답 하나를 고름")
    steps = list(row["verify"]["solution_steps"])
    variable, values = final_solution_values(steps[-1]) or ("", ())
    answer = _p(row["verify"]["answer_map"][variable])
    kept = [v for v in values if sympy.simplify(v - answer) != 0]
    steps[-1] = ", ".join(f"{variable} = {sympy.sstr(v)}" for v in kept)
    violations = _contract_violations(_mutated(row, steps))
    assert any("전이 판정" in v for v in violations)  # 진부분집합 전이는 판정 불가
    assert any("VIOLATION" in v for v in violations)


# ──────────────────────────────────────────────────────────────────────────
# ④ 생성기 — 출발식 재정의의 범위와 빌드 fail-loud (corpus_authoring)
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.corpus_authoring
@pytest.mark.parametrize("generator_cls", GENERATORS, ids=lambda g: g.__name__)
def test_setup_overrides_exist_exactly_where_conditions_lack_a_derivative(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    for slot in SLOT_IDS:
        for item in generator_cls.items(slot):
            conditions = (item.conditions,) if isinstance(item.conditions, str) else item.conditions
            in_conditions = any(_DERIVATIVE in c for c in conditions)
            chain = steps_of(item)
            if item.solution_setup is not None:
                assert _DERIVATIVE in item.solution_setup, item.frame_id
                assert chain.steps[0] == item.solution_setup, item.frame_id
            elif not in_conditions and getattr(item, "answer_kind", None) is None:
                # 도함수 없는 조건에 출발식도 없으면 — 평균값 정리의 결론만 묻는 진단 틀 둘뿐이다.
                assert any(stem in item.question_text for stem in _CONCLUSION_STEMS), item.frame_id
            assert len(chain.steps) >= 2


class _Unreachable(P3DiffPowerDerivativeGenerator):
    """대표 슬롯 첫 문항의 출발식을 도출 불가한 식으로 바꾼 생성기 — 빌드가 멈춰야 한다."""

    slug_prefix: ClassVar[str] = "wm-test-unreachable"

    @classmethod
    def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
        items = super()._slot_items(slot, claimed)
        if slot == "representative":
            items[0] = dataclasses.replace(items[0], solution_setup="x**5 - x - 1 = 0")
        return items


class _WrongAnswer(P3DiffPowerDerivativeGenerator):
    """정답과 어긋난 출발식(근 목록에 정답이 없다) — 빌드가 멈춰야 한다."""

    slug_prefix: ClassVar[str] = "wm-test-wrong-answer"

    @classmethod
    def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
        items = super()._slot_items(slot, claimed)
        if slot == "applied":
            target = next(i for i, it in enumerate(items) if dict(it.answer_map).get("a"))
            items[target] = dataclasses.replace(
                items[target], solution_setup="Derivative(x**2, x).doit().subs(x, a) = 2"
            )
        return items


@pytest.mark.corpus_authoring
@pytest.mark.parametrize(
    ("broken", "message"),
    [(_Unreachable, "풀이 단계를 만들 수 없다"), (_WrongAnswer, "정답")],
)
def test_build_stops_on_underivable_or_answer_missing_steps(
    broken: type[P3DiffSlotGenerator], message: str
) -> None:
    with pytest.raises(ValueError, match="풀이 단계 도출 실패") as info:
        broken.items("representative")
    assert message in str(info.value)
