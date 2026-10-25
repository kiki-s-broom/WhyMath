"""P3-79 — 형제 검증기의 자동 약분 무연근(P3-75 승계) + 실근 판정 문턱(⑦) + 소수 리터럴(⑦).

P3-75 는 Tier1·근 선택(원소 1개)·해 존재성 분류·근 유도만 원문 정의역 판정
(`condition_definedness`·`trusted_real_roots`)으로 막았다. 같은 자동 약분
(`x*(x - 2)/(x - 2)` → `x`)을 거치는 형제 경로가 남아 있었다.

  ① 실근 개수 `verify_real_root_count` ② 극값 개수 `verify_extremum_count`
  ③ 대입값 `verify_substituted_value` ④ 근 집계 `verify_root_aggregate`
  ⑤ 미분가능 `verify_is_differentiable` · 일대일 `verify_is_one_to_one` · 수치 반례
     `counterexample_fuzz.fuzz_answer`

이 파일은 각 경로에 P3-75 의 6꼴 + RF3/RF4(+ 허수부가 아주 작은 근 d1/d2)를 넣어 **종전 셈이
나오면 RED** 로 고정하고(셈을 맞힌 답도, 무연근을 세서 *맞는 답을 떨어뜨리던* 거짓 fail 방향도),
대조군(정의되는 꼴)의 종전 판정이 그대로인지 함께 본다. 각 표의 "종전" 열은 P3-75 머지 시점
main(`5d1ef801`)에서 실측한 값이다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator, Mapping

import pytest
import sympy

from whymath_backend.l3 import verify_answer as verify_answer_module
from whymath_backend.l3.equivalent import counterexample_fuzz as fuzz_module
from whymath_backend.l3.equivalent.counterexample_fuzz import fuzz_answer
from whymath_backend.l3.verify_answer import (
    AnswerVerdict,
    _exact_decimal_text,
    _real_count_agrees,
    _root_is_real,
    classify_solvability,
    derive_selected_root,
    function_domain_kind,
    verify_answer,
    verify_extremum_count,
    verify_is_differentiable,
    verify_is_one_to_one,
    verify_real_root_count,
    verify_root_aggregate,
    verify_root_selection,
    verify_substituted_value,
)

# (이름, 조건, 무연근/비실근 답) — P3-75 테스트(`test_verify_answer_spurious_root.py`)의 표와 같다.
SPURIOUS: dict[str, tuple[str, str]] = {
    "RF3 약분": ("x*(x - 2)/(x - 2) = 2", "2"),
    "RF4 거듭제곱 약분": ("(x - 2)**3/(x - 2)**2 = 0", "2"),
    "V1 음수 지수 표기": ("x*(x-2)*(x-2)**-1 = 2", "2"),
    "V2 분모 속 분수 표기": ("x/((x-2)/(x-2)) = 2", "2"),
    "a1 .doit() 래퍼": ("(x*(x - 2)/(x - 2)).doit() = 2", "2"),
    "a2 Derivative 속 약분": ("Derivative(x**3*(x - 1)/(x - 1), x).doit() = 3", "1"),
    "b exp(-log) 분모 대용": ("x*(x - 2)*exp(-log(x - 2)) = 2", "2"),
    "c 0 지수": ("x*(x - 2)**0 = 2", "2"),
    "d1 허수부 1e-10 근": ("(x - 1)**2 + 10**(-20) = 0", "1"),
    "d2 허수부 1e-6 근": ("(x - 1)**2 + 1/10**12 = 0", "1"),
}

# ──────────────────────────────────────────────────────────────────────────
# ① 실근 개수 — (종전 셈, 참 셈). 종전은 무연근·허수부 1e-10 근까지 셌다.
# ──────────────────────────────────────────────────────────────────────────
ROOT_COUNTS: dict[str, tuple[int, int]] = {
    name: (1, 0) for name in SPURIOUS if not name.startswith(("a2", "d2"))
}
ROOT_COUNTS["a2 Derivative 속 약분"] = (2, 1)  # 근 ±1 중 1 이 무연근
ROOT_COUNTS["d2 허수부 1e-6 근"] = (0, 0)  # 종전에도 허용치 밖이라 맞게 셌다(대조)


@pytest.mark.parametrize("name", sorted(SPURIOUS))
def test_real_root_count_does_not_count_spurious_roots(name: str) -> None:
    condition, _ = SPURIOUS[name]
    old, true = ROOT_COUNTS[name]
    if old != true:
        assert verify_real_root_count(condition, str(old)).state == "fail"
    assert verify_real_root_count(condition, str(true)).state == "pass"


@pytest.mark.parametrize(
    ("condition", "claimed"),
    [
        ("x*(x - 2)/(x - 2) = 3", "1"),  # 약분 꼴이어도 근 3 은 정의된다
        ("x**2 - 1 = 0", "2"),
        ("x**2 + 1 = 0", "0"),
        ("x**3 - 3*x + 1 = 0", "3"),  # 기약 3차(실근 3 · casus irreducibilis)
        ("(x - 1)*(x - 2) = 0", "2"),  # 제외점 개수(excluded_point_count) 꼴
        ("2*x**2 - 3*x = 0", "2"),  # 근 손실(root_loss_count) 꼴
        ("x**3 - 3*sqrt(2)*x + 1 = 0", "3"),  # 무리 계수 — solve + 실근 개수 확인 경로
    ],
)
def test_real_root_count_controls_keep_verdict(condition: str, claimed: str) -> None:
    assert verify_real_root_count(condition, claimed).state == "pass"
    wrong = str(int(claimed) + 1)
    assert verify_real_root_count(condition, wrong).state == "fail"


def test_real_root_count_with_range_controls() -> None:
    conditions = ["6*x**2 - 4*x - 32 = 0", "x > -4", "x < 4"]  # 근 8/3·−2 모두 범위 안
    assert verify_real_root_count(conditions, "2").state == "pass"
    assert verify_real_root_count(conditions, "1").state == "fail"
    narrow = ["6*x**2 - 4*x - 32 = 0", "x > 0", "x < 4"]  # 8/3 만
    assert verify_real_root_count(narrow, "1").state == "pass"


# ──────────────────────────────────────────────────────────────────────────
# ② 극값 개수 — 함수 식으로 옮긴 꼴(임계점이 원문의 구멍에 오게 만든다).
#   (식, 종전 셈, 기대 판정 {주장: 상태})
# ──────────────────────────────────────────────────────────────────────────
EXTREMA: dict[str, tuple[str, int, dict[str, str]]] = {
    "RF3 약분": ("(x - 2)**3/(x - 2)", 1, {"0": "pass", "1": "fail"}),
    "RF4 거듭제곱 약분": ("(x - 2)**4/(x - 2)**2", 1, {"0": "pass", "1": "fail"}),
    "V1 음수 지수 표기": ("(x-2)**3*(x-2)**-1", 1, {"0": "pass", "1": "fail"}),
    "V2 분모 속 분수 표기": ("(x-2)**2/((x-2)/(x-2))", 1, {"0": "pass", "1": "fail"}),
    "a1 .doit() 래퍼": ("((x - 2)**3/(x - 2)).doit()", 1, {"1": "unverifiable"}),
    "a2 Derivative 속 약분": (
        "Derivative((x - 2)**3*(x - 2)/(x - 2), x).doit()",
        1,
        {"1": "unverifiable"},
    ),
    "b exp(-log) 분모 대용": ("(x - 2)**3*exp(-log(x - 2))", 1, {"1": "unverifiable"}),
    "c 0 지수": ("(x - 2)**2*(x - 2)**0", 1, {"0": "pass", "1": "fail"}),
    "d1 허수부 1e-10 근": ("x**3/3 - x**2 + x*(1 + 10**(-20))", 2, {"0": "pass", "2": "fail"}),
    "d2 허수부 1e-6 근": ("x**3/3 - x**2 + x*(1 + 1/10**12)", 0, {"0": "pass", "2": "fail"}),
}


@pytest.mark.parametrize("name", sorted(EXTREMA))
def test_extremum_count_does_not_count_undefined_critical_point(name: str) -> None:
    expression, old, expected = EXTREMA[name]
    for claimed, state in expected.items():
        assert verify_extremum_count(expression, claimed).state == state, claimed
    if old not in (int(c) for c, s in expected.items() if s == "pass"):
        assert verify_extremum_count(expression, str(old)).state != "pass"


@pytest.mark.parametrize(
    ("expression", "claimed"),
    [
        ("x**3 - 3*x", "2"),
        ("(x - 1)**3 + 1", "0"),  # 코퍼스 extremum_count 꼴
        ("x**2*(x - 1)/(x - 1)", "1"),  # 구멍(x = 1)이 임계점(0)과 다르면 극값은 남는다
        ("x**4/2", "1"),
        ("x**3 - 3*sqrt(2)*x**2", "2"),
    ],
)
def test_extremum_count_controls_keep_verdict(expression: str, claimed: str) -> None:
    assert verify_extremum_count(expression, claimed).state == "pass"
    assert verify_extremum_count(expression, str(int(claimed) + 1)).state == "fail"


# ──────────────────────────────────────────────────────────────────────────
# ③ 대입값 — 정의 등식에 원문이 정의되지 않는 값을 대입한 단계 "x = 2 → y = 2".
# ──────────────────────────────────────────────────────────────────────────
SUBSTITUTIONS: dict[str, tuple[str, str, str]] = {
    "RF3 약분": ("y = x*(x - 2)/(x - 2)", "2", "2"),
    "RF4 거듭제곱 약분": ("y = (x - 2)**3/(x - 2)**2", "2", "0"),
    "V1 음수 지수 표기": ("y = x*(x-2)*(x-2)**-1", "2", "2"),
    "V2 분모 속 분수 표기": ("y = x/((x-2)/(x-2))", "2", "2"),
    "a1 .doit() 래퍼": ("y = (x*(x - 2)/(x - 2)).doit()", "2", "2"),
    "a2 Derivative 속 약분": ("y = Derivative(x**3*(x - 1)/(x - 1), x).doit()", "1", "3"),
    "b exp(-log) 분모 대용": ("y = x*(x - 2)*exp(-log(x - 2))", "2", "2"),
    "c 0 지수": ("y = x*(x - 2)**0", "2", "2"),
    "d1 허수부 1e-10 근": ("(y - x)**2 + 10**(-20) = 0", "1", "1"),
    "d2 허수부 1e-6 근": ("(y - x)**2 + 1/10**12 = 0", "1", "1"),
}


@pytest.mark.parametrize("name", sorted(SUBSTITUTIONS))
def test_substituted_value_rejects_undefined_point(name: str) -> None:
    """종전에는 d2 를 뺀 전부가 pass 였다(무연근·허수부 1e-10 해)."""
    condition, given_x, claimed = SUBSTITUTIONS[name]
    verdict = verify_substituted_value(condition, {"x": given_x}, "y", claimed)
    assert verdict.state == "unverifiable", verdict.reason


def test_substituted_value_controls_keep_verdict() -> None:
    assert verify_substituted_value("y = x*(x - 2)/(x - 2)", {"x": "3"}, "y", "3").state == "pass"
    assert verify_substituted_value("y = x*(x - 2)/(x - 2)", {"x": "3"}, "y", "4").state == "fail"
    assert verify_substituted_value("y = x**2 + 1", {"x": "2"}, "y", "5").state == "pass"
    assert verify_substituted_value("y = x**2 + 1", {"x": "2"}, "y", "4").state == "fail"
    assert verify_substituted_value(
        "y = 2*x/(x + 1)", {"x": "sqrt(2)"}, "y", "4 - 2*sqrt(2)"
    ).state == ("pass")


# ──────────────────────────────────────────────────────────────────────────
# ④ 근 집계 — 종전 집계값(무연근 포함)을 주장하면 pass 였다.
#   집계는 복소근 포함 Vieta 값이 계약이라 d1/d2(복소근)는 무연근이 아니다 — 대조군으로 둔다.
# ──────────────────────────────────────────────────────────────────────────
AGGREGATE_OLD: dict[str, tuple[str, str]] = {
    name: ("2", "2") for name in SPURIOUS if not name.startswith(("a2", "d"))
}
AGGREGATE_OLD["a2 Derivative 속 약분"] = ("0", "-1")  # 근 ±1 → 합 0·곱 −1 (1 은 무연근)


@pytest.mark.parametrize("name", sorted(AGGREGATE_OLD))
def test_root_aggregate_does_not_aggregate_spurious_roots(name: str) -> None:
    condition, _ = SPURIOUS[name]
    old_sum, old_product = AGGREGATE_OLD[name]
    assert verify_root_aggregate(condition, old_sum, "sum").state != "pass"
    if name.startswith("a2"):
        # 남는 근은 −1 하나 — 합·곱 모두 −1.
        assert verify_root_aggregate(condition, "-1", "sum").state == "pass"
        assert verify_root_aggregate(condition, "-1", "product").state == "pass"
    else:
        assert verify_root_aggregate(condition, old_product, "product").state != "pass"


@pytest.mark.parametrize(
    ("condition", "kind", "claimed"),
    [
        ("x**2 + 2*x - 2 = 0", "sum", "-2"),
        ("x**2 + 2*x - 2 = 0", "product", "-2"),
        ("x**3 - 6*x**2 + 11*x - 6 = 0", "sum", "6"),
        ("x**2 + 1 = 0", "product", "1"),  # 복소근 포함 Vieta
        ("(x - 1)**2 + 10**(-20) = 0", "sum", "2"),  # d1 — 복소근은 정의된다(집계 계약)
        ("(x - 1)**2 + 1/10**12 = 0", "product", "1 + 1/10**12"),
        ("x*(x - 2)/(x - 2) = 3", "sum", "3"),
    ],
)
def test_root_aggregate_controls_keep_verdict(condition: str, kind: str, claimed: str) -> None:
    assert verify_root_aggregate(condition, claimed, kind).state == "pass"  # type: ignore[arg-type]
    assert verify_root_aggregate(condition, f"{claimed} + 1", kind).state == "fail"  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────
# ⑥ 거짓 fail 방향 — 종전 셈이 무연근을 세서 *맞는 답*이 fail 이던 경우.
# ──────────────────────────────────────────────────────────────────────────
def test_root_aggregate_is_unverifiable_when_a_root_definedness_is_unknown() -> None:
    """`sqrt(x)**2*x - 4` 는 x² − 4 로 접힌다. x = −2 에서 원문은 실수 범위 밖 중간값(√−2)이라
    정의역을 판정하지 못한다 — 판정 불가 근이 하나라도 있으면 집계를 단정하지 않는다(종전 pass)."""
    condition = "sqrt(x)**2*x - 4 = 0"
    assert verify_root_aggregate(condition, "0", "sum").state == "unverifiable"
    assert verify_root_aggregate(condition, "-4", "product").state == "unverifiable"


def test_false_fail_direction_real_root_count() -> None:
    assert verify_real_root_count("x*(x - 2)/(x - 2) = 2", "0").state == "pass"  # 종전 fail


def test_false_fail_direction_root_aggregate() -> None:
    condition = "(x - 3)*(x - 2)**2/(x - 2) = 0"  # 근은 3 하나(2 는 무연근)
    assert verify_root_aggregate(condition, "3", "sum").state == "pass"  # 종전 fail
    assert verify_root_aggregate(condition, "3", "product").state == "pass"  # 종전 fail
    assert verify_root_aggregate(condition, "5", "sum").state == "fail"  # 종전 pass
    assert verify_real_root_count(condition, "1").state == "pass"  # 종전 fail


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 미분가능·일대일 — 'ℝ 전체' 성질이라 원문이 ℝ 전체에서 정의되는 꼴일 때만 판정한다.
# ──────────────────────────────────────────────────────────────────────────
HOLED_FUNCTIONS: dict[str, str] = {
    "RF3 약분": "x*(x - 2)/(x - 2)",
    "RF4 거듭제곱 약분": "(x - 2)**3/(x - 2)**2",
    "V1 음수 지수 표기": "x*(x-2)*(x-2)**-1",
    "V2 분모 속 분수 표기": "x/((x-2)/(x-2))",
    "a1 .doit() 래퍼": "(x*(x - 2)/(x - 2)).doit()",
    "a2 Derivative 속 약분": "Derivative(x**3*(x - 1)/(x - 1), x).doit()",
    "b exp(-log) 분모 대용": "x*(x - 2)*exp(-log(x - 2))",
    "c 0 지수": "x*(x - 2)**0",
    "⑤(a) 원문": "x**2*(x-1)/(x-1)",
}


@pytest.mark.parametrize("name", sorted(HOLED_FUNCTIONS))
def test_differentiable_is_not_judged_on_cancelled_form(name: str) -> None:
    """종전에는 전부 '미분가능 1' 이 pass 였다(원문은 구멍에서 정의되지 않는다)."""
    expression = HOLED_FUNCTIONS[name]
    assert verify_is_differentiable(expression, "1").state == "unverifiable"
    assert verify_is_differentiable(expression, "0").state == "unverifiable"


@pytest.mark.parametrize("name", sorted(HOLED_FUNCTIONS))
def test_one_to_one_is_not_judged_on_cancelled_form(name: str) -> None:
    expression = HOLED_FUNCTIONS[name]
    for claimed in ("0", "1"):
        assert verify_is_one_to_one(expression, claimed).state == "unverifiable"


def test_one_to_one_counts_only_exact_real_critical_points() -> None:
    """d1 — f' = (x − 1)² + 10⁻²⁰ 은 실근이 없어 단조(일대일 1). 종전에는 허수부 1e-10 근을
    부호 변화로 세어 0 을 pass 로 냈다."""
    expression = "x**3/3 - x**2 + x*(1 + 10**(-20))"
    assert verify_is_one_to_one(expression, "1").state == "pass"
    assert verify_is_one_to_one(expression, "0").state == "fail"


@pytest.mark.parametrize(
    ("expression", "claimed"),
    [("Abs(x - 1)", "0"), ("Abs(x - 1) + 3", "0"), ("x**2", "1"), ("x**3 - 3*x/2", "1")],
)
def test_differentiable_controls_keep_verdict(expression: str, claimed: str) -> None:
    assert verify_is_differentiable(expression, claimed).state == "pass"
    assert verify_is_differentiable(expression, str(1 - int(claimed))).state == "fail"


@pytest.mark.parametrize(
    ("expression", "claimed"),
    [("x**3", "1"), ("x**2 + 1", "0"), ("x**2 + 2*x + 1", "0"), ("x**3/2 + x", "1")],
)
def test_one_to_one_controls_keep_verdict(expression: str, claimed: str) -> None:
    assert verify_is_one_to_one(expression, claimed).state == "pass"
    assert verify_is_one_to_one(expression, str(1 - int(claimed))).state == "fail"


@pytest.mark.parametrize(
    ("expression", "kind"),
    [
        ("x**2 + 3*x - 1", "total"),
        ("x**2/2", "total"),  # 상수 분모
        ("Abs(x - 1) + 2", "total"),
        ("sin(x)*exp(x)", "total"),
        ("2**x", "total"),
        ("x*(x - 2)/(x - 2)", "open"),
        ("x*(x-2)*(x-2)**-1", "open"),
        ("x*(x - 2)**0", "open"),  # 변수 밑의 0 지수 — 밑이 0 인 점에서 정의되지 않는다
        ("(x*(x - 2)/(x - 2)).doit()", None),
        ("sqrt(x)**2", None),
        ("x*exp(-log(x - 2))", None),
        ("x/0", None),  # 상수 분모 0
        ("x + a", None),  # 다른 이름
        ("x**(1/2)", None),  # 정수 아닌 지수
    ],
)
def test_function_domain_kind(expression: str, kind: str | None) -> None:
    assert function_domain_kind(expression, "x") == kind


# ──────────────────────────────────────────────────────────────────────────
# ⑤(c) 수치 반례 fuzz — 주장 정답을 정확값으로 원문 정의역에 넣는다.
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", sorted(SPURIOUS))
@pytest.mark.parametrize("selection", [None, "unique", "largest"])
def test_fuzz_rejects_spurious_root(name: str, selection: str | None) -> None:
    """종전에는 a2 의 unique 를 뺀 전부가 pass 였다."""
    condition, answer = SPURIOUS[name]
    verdict = fuzz_answer(condition, {"x": answer}, selection)
    assert verdict.state == "fail", verdict.reason


def test_fuzz_does_not_pass_when_claim_definedness_is_unknown() -> None:
    """허용 구조 밖(미분 안의 √ — 해석 함수 허용 목록 밖) — 원문 정의역을 못 가리면 pass 로
    단정하지 않는다(종전 pass). 반례는 정의역과 무관하게 반례다 — 틀린 답은 그대로 fail."""
    condition = "Derivative(sqrt(x), x).doit() = 1/4"
    assert fuzz_answer(condition, {"x": "4"}).state == "unverifiable"
    assert fuzz_answer(condition, {"x": "5"}).state == "fail"


def test_fuzz_selection_ignores_spurious_neighbour_root() -> None:
    """근 3 하나뿐인 조건 — 무연근 2 가 '둘째 근'·'더 작은 근' 반례를 만들지 않는다(종전 fail)."""
    condition = "(x - 3)*(x - 2)**2/(x - 2) = 0"
    assert fuzz_answer(condition, {"x": "3"}, "unique").state == "pass"
    assert fuzz_answer(condition, {"x": "3"}, "smallest").state == "pass"


@pytest.mark.parametrize(
    ("condition", "answer", "selection", "state"),
    [
        ("x*(x - 2)/(x - 2) = 3", "3", "unique", "pass"),
        ("x**2 - 1 = 0", "1", "largest", "pass"),
        ("x**2 - 1 = 0", "-1", "largest", "fail"),
        ("x**2 - 1 = 0", "-1", "unique", "fail"),
        ("x**2 - 2 = 0", "sqrt(2)", "largest", "pass"),
        ("x**2 - 2 = 0", "1.41421356237310", None, "pass"),  # 근사 소수 답 — 수치 허용치
        ("2*x + 1 = 4", "2", None, "fail"),
        # 중근 0(뉴턴 다듬기가 1e-21 근처에 멈춘다)은 정확값 0 으로 맞춰 원문 정의역을 본다 —
        # 코퍼스 `Derivative(…).doit() = 0` 꼴(p3_calculus1_diff·p3_fill)의 선택 판정 회귀 고정.
        ("x**3*(x - 2) = 0", "2", "largest", "pass"),
        ("Derivative(3*x**4 - 4*x**3 - 6, x).doit() = 0", "1", "largest", "pass"),
        ("Derivative(3*x**4 - 4*x**3 - 6, x).doit() = 0", "1", "unique", "fail"),
        ("Derivative(-3*x**4 - 12*x**3 + 5, x).doit() = 0", "-3", "smallest", "pass"),
    ],
)
def test_fuzz_controls_keep_verdict(
    condition: str, answer: str, selection: str | None, state: str
) -> None:
    assert fuzz_answer(condition, {"x": answer}, selection).state == state


# ──────────────────────────────────────────────────────────────────────────
# ⑦-1 실근 판정 문턱 — 0 아닌 허수부는 문턱(1e-100) 아래여도 실근이 아니다.
# ──────────────────────────────────────────────────────────────────────────
_X = sympy.Symbol("x")
_NEAR_DOUBLE = sympy.expand((_X - sympy.sqrt(2)) ** 2 * (_X + 3))


def _tiny_imaginary_roots(exponent: int) -> list[sympy.Expr]:
    """(x − √2)²(x + 3) + 10⁻ᵏ 의 √2 근방 두 근 — 허수부 ≈ 10^(−k/2)·0.48 인 비실근."""
    roots = sympy.solve(_NEAR_DOUBLE + sympy.Rational(1, 10**exponent), _X)
    near = [r for r in roots if abs(complex(sympy.N(r, 30)) - complex(sympy.sqrt(2))) < 0.1]
    assert len(near) == 2
    return near


@pytest.mark.parametrize("exponent", [100, 200])
def test_root_is_real_does_not_call_tiny_imaginary_root_real(exponent: int) -> None:
    """허수부 ~5e-51(문턱 1e-40 아래)·~4.8e-101(반올림 문턱 1e-100 아래)인 비실근.

    종전(main)은 1e-100 아래를 실근으로 불렀다. 문턱을 1e-40 으로 완화하면 두 경우 모두 다시
    실근이 된다 — 이 테스트가 그 완화를 RED 로 잡는다.
    """
    for root in _tiny_imaginary_roots(exponent):
        assert _root_is_real(root) is not True


@pytest.mark.parametrize("exponent", [100, 200, 400])
def test_tiny_imaginary_roots_do_not_make_multiple_roots(exponent: int) -> None:
    """참 실근은 x ≈ −3 하나(unique). 판정 불가는 허용, multiple·거짓 fail·비실근 유도는 RED.

    10⁻⁴⁰⁰ 은 허수부(~10⁻²⁰⁰)가 120자리 평가에서 0 상한으로 사라지는 꼴 — 실근 개수
    (`count_roots`) 확인이 막는다.
    """
    condition = f"{sympy.sstr(_NEAR_DOUBLE)} + 10**(-{exponent}) = 0"
    assert classify_solvability(condition).state in ("unique", "undecidable")
    assert verify_root_selection(condition, {"x": "-3"}, "unique").state != "fail"
    derived = derive_selected_root(condition, "largest")
    if derived is not None:
        value = complex(sympy.N(sympy.sympify(derived), 30))
        assert abs(value.real + 3) < 0.01  # √2 근방의 비실근을 '가장 큰 근'으로 내지 않는다


def test_cardano_real_roots_stay_real() -> None:
    """대조군 — 카르다노 근호식의 실근(허수부가 정밀도와 함께 사라진다)은 실근이다."""
    condition = "x**3 - 3*sqrt(2)*x + 1 = 0"
    roots = sympy.solve(sympy.sympify("x**3 - 3*sqrt(2)*x + 1"), _X)
    assert [_root_is_real(r) for r in roots] == [True, True, True]
    assert classify_solvability(condition).state == "multiple"
    assert verify_real_root_count(condition, "3").state == "pass"


# ──────────────────────────────────────────────────────────────────────────
# ⑦-2 소수 리터럴 재판정 — 평가된 Float 가 아니라 원문 리터럴을 십진 정확값으로 읽는다.
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("condition", "answer", "state"),
    [
        ("x = sqrt(2.0)", "sqrt(2)", "pass"),  # 종전 unverifiable
        ("x = 2.0**0.5", "sqrt(2)", "pass"),  # 종전 unverifiable
        ("x/3.0 = 1", "3", "pass"),
        ("0.1*x = 0.3", "3", "pass"),
        ("x = 0.1 + 0.2", "3/10", "pass"),
        ("(x - 1)**2 + 1e-20 = 0", "1", "unverifiable"),  # P3-75 — 적힌 십진값이면 잔차 ≠ 0
        ("x = 1.41421356237310", "sqrt(2)", "unverifiable"),  # 반올림 리터럴은 √2 가 아니다
        ("x**2 = 2", "1.4142135623731", "pass"),  # 근사 답 — 종전 허용치 판정
    ],
)
def test_decimal_literals_read_as_written(condition: str, answer: str, state: str) -> None:
    assert verify_answer(condition, {"x": answer}).state == state


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("x = sqrt(2.0)", "x = sqrt((20*10**(-1)))"),
        ("x = 2.0**0.5", "x = (20*10**(-1))**(5*10**(-1))"),
        ("(x - 1)**2 + 1e-20 = 0", "(x - 1)**2 + (1*10**(-20)) = 0"),
        ("x = 1.5", "x = (15*10**(-1))"),
        ("x = 1e-300", "x = (1*10**(-300))"),  # 301자리 정수로 펼치지 않는다(재검토 P2-1)
        ("x**2 = 4", None),  # 소수 리터럴 없음
        ("x = 2j", None),  # 허수 리터럴은 바꾸지 않는다
    ],
)
def test_exact_decimal_text_rewrites_literals_only(condition: str, expected: str | None) -> None:
    assert _exact_decimal_text(condition) == expected


# ──────────────────────────────────────────────────────────────────────────
# PR #1722 재검토 — P2-1 소수 리터럴 재판정 fail-closed · P2-2 성능 · P3-1 fuzz 군집 · P3-2 픽스처
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("exponent", [20, 100, 200, 300])
def test_decimal_literal_residual_is_not_passed_at_any_exponent(exponent: int) -> None:
    """P2-1 — `1e-100` 을 101자리 정수로 펼치던 재작성이 안전 파싱에 거부되면 종전 코드는
    False(통과)를 돌려 허용치 안의 0 아닌 잔차가 pass 였다(지수 100·200·300)."""
    assert verify_answer([f"(x - 1)**2 + 1e-{exponent} = 0"], {"x": "1"}).state == "unverifiable"
    assert verify_answer([f"x = 1e-{exponent}"], {"x": "0"}).state == "unverifiable"
    assert verify_answer([f"x**2 + 1.5e-{exponent} = 0"], {"x": "0"}).state == "unverifiable"


@pytest.mark.parametrize("exponent", [100, 300])
def test_decimal_literal_exact_answer_still_passes_at_large_exponent(exponent: int) -> None:
    """대조군 — 리터럴이 정확히 같은 값이면 큰 지수에서도 pass(재작성이 짧은 꼴이라 재파싱된다)."""
    assert verify_answer([f"x = 1e-{exponent}"], {"x": f"10**(-{exponent})"}).state == "pass"


@pytest.mark.parametrize("rewritten", ["(x - 1)**2 + ((( = 0", None])
def test_decimal_literal_rewrite_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch, rewritten: str | None
) -> None:
    """정확값 재작성을 다시 읽지 못하거나(안전 파싱 거부 — 재검토 P2-1 의 실패 경로) 원문에서 소수
    리터럴을 찾지 못하면 판정 불가로 닫는다(fail-closed). 지금 파서 한도(소수 지수 ≤ 308·리터럴
    길이)에서는 짧은 재작성 꼴이 늘 읽히므로, 그 어긋남을 직접 주입해 계약을 고정한다."""
    monkeypatch.setattr(verify_answer_module, "_exact_decimal_text", lambda _c: rewritten)
    assert verify_answer(["(x - 1)**2 + 1e-20 = 0"], {"x": "1"}).state == "unverifiable"


def test_decimal_literal_with_long_significand_is_read_exactly() -> None:
    """유효숫자가 긴 리터럴(100자리 — 안전 파싱 길이 한도 안)도 짧은 꼴로 다시 써져 정확 판정된다."""
    long_one = "1." + "0" * 97 + "1"
    assert verify_answer([f"(x - 1)**2 + {long_one} - 1 = 0"], {"x": "1"}).state == "unverifiable"
    assert verify_answer([f"x = {long_one}"], {"x": "1 + 10**(-98)"}).state == "pass"


def test_total_condition_skips_per_root_definedness(monkeypatch: pytest.MonkeyPatch) -> None:
    """P2-2 — 어디서나 정의되는 꼴의 조건은 근마다 원문을 평가하지 않는다(대수적 계수 근호식 근의
    평가가 근 집계 하나에 25초였다). 구멍이 있는 꼴은 그대로 평가한다(대조)."""
    calls: list[str] = []
    original = verify_answer_module.condition_definedness

    def counting(condition: str, values: object) -> str:
        calls.append(condition)
        return original(condition, values)  # type: ignore[arg-type]

    monkeypatch.setattr(verify_answer_module, "condition_definedness", counting)
    assert verify_root_aggregate("x**2 + 2*x - 2 = 0", "-2", "sum").state == "pass"
    assert verify_real_root_count("x**3 - 3*sqrt(2)*x + 1 = 0", "3").state == "pass"
    assert calls == []
    assert verify_root_aggregate("x*(x - 2)/(x - 2) = 2", "2", "sum").state == "unverifiable"
    assert calls  # 구멍이 있는 꼴은 근별로 본다


def test_algebraic_coefficient_aggregate_is_fast() -> None:
    """P2-2 재현식 — 종전 25.6초. 시간 상한은 넉넉히(CI 부하) 두되 종전 회귀는 잡는 값이다."""
    import time

    started = time.perf_counter()
    condition = "x**4 + 3*x**3 - 7*sqrt(5)*x**2 + 11*x - 13 = 0"
    assert verify_root_aggregate(condition, "-3", "sum").state == "pass"
    assert time.perf_counter() - started < 8.0


@pytest.mark.parametrize(
    ("condition", "answer"),
    [
        ("x*(x-2)**2*(x - 2 - 3*10**(-8))/(x-2) = 0", "0"),
        ("(x+1)*(3*x-1)**2*(x - 1/3 - 4*10**(-6))/(3*x-1) = 0", "-1"),
        ("x*(3*x-1)**2*(x - 1/3 - 10**(-9))/(3*x-1) = 0", "0"),
    ],
)
def test_fuzz_does_not_drop_true_root_hidden_next_to_spurious_root(
    condition: str, answer: str
) -> None:
    """P3-1 — 진짜 근이 무연근에서 1e-5 안에 있으면 수치 근이 무연근 정확값으로 맞춰져 통째로
    버려졌다(거짓 pass). 참 '가장 큰 근' 은 무연근 바로 옆의 진짜 근이라 주장은 틀렸다 — pass 금지."""
    assert fuzz_answer(condition, {"x": answer}, "largest").state != "pass"


def test_fuzz_isolated_spurious_root_is_still_dropped() -> None:
    """대조군 — 홀로 떨어진 무연근은 그대로 버린다(가장 큰 근 1 이 맞다)."""
    condition = "(x-1)*(x+5)*(x-2)**3/(x-2)**2 = 0"
    assert fuzz_answer(condition, {"x": "1"}, "largest").state == "pass"
    assert fuzz_answer(condition, {"x": "-5"}, "largest").state == "fail"


@pytest.mark.parametrize(
    ("expression", "kind"),
    [
        ("x/(1.0 - 0.99999999999)", None),  # R1 — 0 여부를 못 가리는 상수 분모(허용치 안)
        ("tan(x)", None),  # R2 — 실수 전체에서 정의되지 않는 함수
        ("(-2)**x", None),  # R3 — 밑이 양수가 아닌 b**x
        ("2**x", "total"),  # R3 대조군
    ],
)
def test_function_domain_kind_review_clauses(expression: str, kind: str | None) -> None:
    assert function_domain_kind(expression, "x") == kind


def test_differentiable_rejects_function_outside_total_functions() -> None:
    """R2 — `0*tan(x)` 는 평가 파싱이 지워 x³ 이 되지만 원문은 x = π/2 에서 정의되지 않는다."""
    assert verify_is_differentiable("x**3 + 0*tan(x)", "1").state == "unverifiable"
    assert verify_is_differentiable("x**3 + 0*sin(x)", "1").state == "pass"  # 대조군


def test_real_count_agreement_is_exact_equality() -> None:
    """R4 — 실근 후보 수는 SymPy 실근 개수와 **같아야** 한다(더 적으면 놓친 실근이 있다)."""
    x = sympy.Symbol("x")
    poly = sympy.Poly(x**3 - x, x)  # 실근 3개
    assert _real_count_agrees(poly, [sympy.Integer(0)]) is False
    assert _real_count_agrees(poly, [sympy.Integer(-1), sympy.Integer(0), sympy.Integer(1)]) is True


def test_fuzz_selection_with_undecidable_neighbour_root_is_unverifiable() -> None:
    """R5 — 다른 수치 근(x = −2: 원문 √−2 가 실수 범위 밖)의 정의역을 못 가리면 그 근을 조용히
    버리지 않는다(버리면 '유일근' 판정이 근거 없이 pass 가 된다)."""
    assert fuzz_answer("sqrt(x)**2*x - 4 = 0", {"x": "2"}, "unique").state == "unverifiable"


def test_root_aggregate_with_only_spurious_roots_is_unverifiable() -> None:
    """R7 — 원문에서 정의되는 근이 하나도 없으면 빈 합(0)·빈 곱(1)으로 판정하지 않는다."""
    condition = "x*(x - 2)/(x - 2) = 2"
    assert verify_root_aggregate(condition, "0", "sum").state == "unverifiable"
    assert verify_root_aggregate(condition, "1", "product").state == "unverifiable"


def test_fuzz_does_not_fail_true_root_whose_exact_residual_is_undecided() -> None:
    """R9 대조군 — 2cos(2π/9) 는 x³ − 3x + 1 = 0 의 참 근이지만 SymPy 가 정확 잔차의 0 여부를
    정하지 못한다(`is_zero` None). '모름' 을 '0 아님' 으로 접어 거짓 fail 을 내지 않는다."""
    condition = "x**3 - 3*x + 1 = 0"
    assert fuzz_answer(condition, {"x": "2*cos(2*pi/9)"}).state == "pass"
    assert fuzz_answer(condition, {"x": "2*cos(4*pi/9)"}).state == "pass"


def test_derivative_roots_in_ambiguous_band_fall_back_to_exact_reality() -> None:
    """빠른 실근 판정(30자리)이 가르지 못하는 도함수 근(허수부 ~1e-50 — 실근 수가 SymPy 개수와
    어긋난다)은 근별 판정으로 넘어가 SymPy 가 비실근으로 확정한다. 허용치로 실근이라 부르면
    극값 2개·일대일 0 이 거짓으로 나온다."""
    expression = "x**3/3 - x**2 + x*(1 + 10**(-100))"
    assert verify_extremum_count(expression, "0").state == "pass"
    assert verify_extremum_count(expression, "2").state == "fail"
    assert verify_is_one_to_one(expression, "1").state == "pass"
    assert verify_is_one_to_one(expression, "0").state == "fail"


# ──────────────────────────────────────────────────────────────────────────
# P3-83 — P3-79 재검토 잔여 P3 3건: ① fuzz 군집 창 ② 4차 대수 계수 성능 ③ fail-closed 분기 동결
# ──────────────────────────────────────────────────────────────────────────
_X = sympy.Symbol("x")
# 창 계산에 쓰는 임의의 유한 창(분기 단위 시험용) — 실제 호출부는 격자 간격에서 정한다.
_WINDOW = sympy.Rational(1, 50)
# 정확히 0 이지만 SymPy 가 0 임을 증명하지 못하는 상수(`is_zero` None) — '도함수 0 여부 미정'의 재료.
_HIDDEN_ZERO = sympy.sin(1) ** 2 + sympy.cos(1) ** 2 - 1


def _hole_grid() -> list[tuple[str, str, str, bool]]:
    """① 거짓 pass 격자 520건 — (조건, 답, 선택, 주장이 참인가).

    조건은 `x*(x-2)**m*(x - 2 ± d)/(x-2)**k = 0` — 참 근은 0 과 2 ∓ d, x = 2 는 분모 0 이라 무연근.
    홀 중복도 5종(m, k) × 부호 2 × 간격 d 13종(1e-9 ~ 1e-3) × 주장 4종(거짓 2·참 2) = 520.
    """
    gaps = [
        "1*10**(-9)",
        "1*10**(-8)",
        "3*10**(-8)",
        "1*10**(-7)",
        "1*10**(-6)",
        "5*10**(-6)",
        "9*10**(-6)",
        "10**(-5)",
        "11*10**(-6)",
        "2*10**(-5)",
        "5*10**(-5)",
        "10**(-4)",
        "10**(-3)",
    ]
    cases: list[tuple[str, str, str, bool]] = []
    for m, k in ((1, 1), (2, 1), (2, 2), (3, 1), (3, 2)):
        for sign in ("+", "-"):
            true_root_sign = "-" if sign == "+" else "+"
            for gap in gaps:
                condition = f"x*(x-2)**{m}*(x - 2 {sign} {gap})/(x-2)**{k} = 0"
                cases.append((condition, "0", "largest", False))  # 참 최대 근은 2 근방
                cases.append((condition, "0", "unique", False))  # 서로 다른 정의 근이 둘
                cases.append((condition, f"2 {true_root_sign} {gap}", "largest", True))
                cases.append((condition, "0", "smallest", True))
    return cases


# 종전부터 있던 한계 — 수치 탐색이 한 칸 안에서 합친 참 근을 못 봐 '맞는 답'을 '근이 아님'으로
# 부르는 거짓 fail(P3-83 착수 시점 main 실측 27건, 창 확대 뒤에도 같다). 늘어나면 RED.
_GRID_KNOWN_FALSE_FAIL = 27


def test_fuzz_hole_grid_has_no_false_pass() -> None:
    """P3-83 ① — 무연근 곁(2e-5~3e-3)의 참 근이 무연근 군집으로 버려져 거짓 pass 가 나던 격자 520건.

    착수 시점 main 은 거짓 pass 20건(거짓 주장 `0` 이 '가장 큰 근'·'유일근'으로 pass)이었다. 거짓 주장은
    pass 가 아니어야 하고, 참 주장의 거짓 fail 은 종전 한계(27건)를 넘지 않아야 한다."""
    cases = _hole_grid()
    assert len(cases) == 520
    false_pass: list[tuple[str, str, str]] = []
    false_fail = 0
    for condition, answer, selection, claim_is_true in cases:
        state = fuzz_answer(condition, {"x": answer}, selection).state
        if not claim_is_true and state == "pass":
            false_pass.append((condition, answer, selection))
        if claim_is_true and state == "fail":
            false_fail += 1
    assert false_pass == []
    assert false_fail <= _GRID_KNOWN_FALSE_FAIL


@pytest.mark.parametrize(
    "condition",
    [
        "x*(x-2)**2*(x - 2 + 5*10**(-5))/(x-2) = 0",
        "x*(x-2)**3*(x-2-3*10**(-3))/(x-2)**2 = 0",
    ],
)
def test_fuzz_true_root_near_hole_is_not_passed(condition: str) -> None:
    """P3-83 ① 재현식 — 참 근은 0 과 무연근 곁의 한 점이라 '가장 큰 근 = 0' 은 거짓이다."""
    assert fuzz_answer(condition, {"x": "0"}, "largest").state != "pass"
    assert fuzz_answer(condition, {"x": "0"}, "unique").state != "pass"


@pytest.mark.parametrize("gap", ["5*10**(-2)", "10**(-1)", "1/2"])
def test_fuzz_hole_far_from_true_root_is_still_dropped(gap: str) -> None:
    """① 대조군 — 참 근이 창의 2배(격자 간격 4배 ≈ 0.04, 비율 검사 문턱 1/2) 밖이면 무연근은 그대로
    버려져 정답이 pass 다.
    창을 넓힌 대가로 정상 답이 판정 불가로 밀리지 않는지 본다."""
    condition = f"x*(x-2)**2*(x - 2 - {gap})/(x-2) = 0"
    assert fuzz_answer(condition, {"x": f"2 + {gap}"}, "largest").state == "pass"
    assert fuzz_answer(condition, {"x": "0"}, "smallest").state == "pass"
    assert fuzz_answer(condition, {"x": "0"}, "largest").state == "fail"


def test_isolation_window_follows_the_search_grid() -> None:
    """① 창 하한 = 격자 간격의 `_ISOLATION_GRID_STEPS` 배(작은 격자에서도 절대 하한 1e-5 아래로 안
    내려간다). 격자 간격을 모르면(0·음수·NaN·무한) 창을 정하지 않는다(None — 고립을 확인하지 못함)."""
    step = (2.0 * 50.0) / (10_000 - 1)
    window = fuzz_module._isolation_min_window(step)
    assert window is not None
    assert float(window) == pytest.approx(step * fuzz_module._ISOLATION_GRID_STEPS)
    assert fuzz_module._isolation_min_window(1e-9) == fuzz_module._ISOLATION_MIN_WINDOW
    for unknown in (0.0, -0.01, float("nan"), float("inf")):
        assert fuzz_module._isolation_min_window(unknown) is None


def test_fuzz_isolation_window_covers_numeric_merge_radius() -> None:
    """① 창 하한의 근거 재측정 — 수치 탐색이 무연근 곁의 참 근을 따로 찾지 못하는 최대 간격이 창 하한
    안에 든다. 순중복도 1·2 · 격자 위 무연근 위치 20곳 · 간격 1.0~1.8 격자(0.1 간격)를 훑는다 —
    최대 1.6 격자(순중복도 2)가 합쳐지므로 창 하한이 1.5 격자 이하면 RED. 측정이 합쳐짐을 실제로
    보는지(스캔 0건 = 공허한 통과)도 함께 단언한다."""
    step = (2.0 * 50.0) / (10_000 - 1)
    window = float(fuzz_module._isolation_min_window(step) or 0)
    hidden_max = 0.0
    for net in (1, 2):  # 무연근의 순중복도
        for offset in range(20):  # 격자 위 무연근 위치 20곳
            hole = 2.0 + step * offset / 20
            for tenth in range(10, 19):  # 간격 1.0 ~ 1.8 격자
                for sign in (1.0, -1.0):
                    gap = sign * (tenth / 10) * step
                    func = sympy.lambdify(_X, _X * (_X - hole) ** net * (_X - hole - gap), "math")
                    roots, _ = fuzz_module._find_roots(func, 50.0, 10_000, 1e-7)
                    near = [
                        r
                        for r in roots
                        if min(hole, hole + gap) - 0.05 <= r <= max(hole, hole + gap) + 0.05
                    ]
                    if len(near) < 2:  # 두 근이 하나로 합쳐졌다
                        hidden_max = max(hidden_max, abs(gap))
    assert hidden_max >= 1.5 * step  # 측정이 합쳐짐을 실제로 본다(실측 최대 1.6 격자)
    assert hidden_max < window  # 합쳐지는 간격은 모두 창 안이다


# ── ③ `_isolated_exact_root` 의 fail-closed 분기 동결 ──────────────────────────
# 반환값을 True 로 뒤집으면 무연근 군집을 '고립됨'으로 오판해 참 근을 통째로 버린다(거짓 pass).
# 분기마다 실세계 원인을 열거하고, 원인별로 (해로운 입력 · 고립된 구멍 · 성공 방향 대조군)을 둔다.
#
#  분기 E(예외 → False) 원인: ⓐ `sympy.diff` 가 식을 못 미분(NotImplementedError 등) ⓑ 값이 수가 아닌 채
#      남아 `complex()` 가 TypeError ⓒ 아주 큰 식의 RecursionError(같은 분기 — 따로 재현하지 못했다).
#  분기 F(비유한 값 → False, P3-83 신설) 원인: 창 끝이 잔차의 극점이라 값이 zoo/NaN.
#  분기 Z(`is_zero` None → False) 원인: ⓐ 도함수 값이 정확히 0 이지만 SymPy 가 증명하지 못하는 상수
#      (삼각 항등식 등)를 담음 ⓑ 도함수 값이 깊은 근호 중첩이라 0 여부를 못 가림.
#  분기 L(`lead` None → False) 원인: ⓐ 무연근의 순중복도가 8 을 넘음 ⓑ 잔차가 항등적으로 0.
#  (분기 W: 창을 정할 수 없음 · 분기 P: 점이 근사 소수/자유 기호를 담음 — 같은 방식으로 고정한다.)
def _near_root_condition(power: int, denominator: int, gap: str = "3*10**(-8)") -> str:
    return f"x*(x-2)**{power}*(x-2-{gap})/(x-2)**{denominator} = 0"


def _isolated_hole_condition(power: int, denominator: int) -> str:
    return f"x*(x-5)*(x-2)**{power}/(x-2)**{denominator} = 0"


def _raising_diff(*_args: object, **_kwargs: object) -> object:
    raise NotImplementedError("지원하지 않는 식")


def _hidden_zero_diff(real_diff: object) -> object:
    """미분 결과에 '정확히 0 이나 증명 불가'한 상수를 더한다 — 도함수 값의 0 여부를 미정으로 만든다."""

    def patched(expr: sympy.Expr, *args: object, **kwargs: object) -> sympy.Expr:
        return real_diff(expr, *args, **kwargs) + _HIDDEN_ZERO  # type: ignore[operator, no-any-return]

    return patched


def test_hidden_zero_constant_is_really_undecidable() -> None:
    """픽스처 전제 — 이 상수가 0 이라고 SymPy 가 답했다면 분기 Z 의 픽스처가 그 분기를 밟지 않는다."""
    assert _HIDDEN_ZERO.is_zero is None
    assert abs(float(_HIDDEN_ZERO.evalf(30))) < 1e-25  # 실제로 0


def test_isolation_exception_branch_fails_closed_end_to_end(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """분기 E ⓐ — 미분이 예외를 올리면 '고립됨'이 아니라 판정 불가다(예외 타입명은 로그에 남는다)."""
    harmful = _near_root_condition(3, 2)
    isolated = _isolated_hole_condition(3, 2)
    assert fuzz_answer(isolated, {"x": "5"}, "largest").state == "pass"  # 대조군 — 고립된 구멍
    monkeypatch.setattr(fuzz_module.sympy, "diff", _raising_diff)
    with caplog.at_level(logging.DEBUG, logger="whymath.l3.equivalent.counterexample_fuzz"):
        assert fuzz_answer(harmful, {"x": "0"}, "largest").state == "unverifiable"
        assert fuzz_answer(isolated, {"x": "5"}, "largest").state == "unverifiable"
    assert any(
        "무연근 군집 확인 회피" in rec.getMessage() and "NotImplementedError" in rec.getMessage()
        for rec in caplog.records
    )


def test_isolation_exception_branch_pole_at_window_edge(caplog: pytest.LogCaptureFixture) -> None:
    """분기 E ⓑ — 창 끝(2 − 1/50)이 잔차의 극점이면 값이 zoo 라 판정 불가. 다른 쪽 끝 값이 `g(2)` 와
    가까워 NaN 비교가 '벗어나지 않음'으로 접히면 거짓 '고립됨'이 되는 모양이다(대조군: 극점이 멀면 고립).
    극점은 `complex()` 가 예외 없이 NaN 으로 바꾸므로 예외 분기가 아니라 비유한 값 분기를 탄다."""
    nearly_flat = (_X - 2) ** 2 * (1 + sympy.Rational(1, 5000) / (_X - 2 + _WINDOW))
    with caplog.at_level(logging.DEBUG, logger="whymath.l3.equivalent.counterexample_fuzz"):
        assert (
            fuzz_module._isolated_exact_root(nearly_flat, _X, sympy.Integer(2), 2.0, _WINDOW)
            is False
        )
    assert not any("무연근 군집 확인 회피" in rec.getMessage() for rec in caplog.records)
    far_pole = (_X - 2) ** 2 * (1 + sympy.Rational(1, 5000) / (_X - 7))
    assert fuzz_module._isolated_exact_root(far_pole, _X, sympy.Integer(2), 2.0, _WINDOW) is True


def test_isolation_exception_branch_non_numeric_value(caplog: pytest.LogCaptureFixture) -> None:
    """분기 E ⓑ — 값이 수가 아닌 채 남는 식(복소수로 못 바꾸는 값)은 예외 분기로 판정 불가."""
    unevaluated = _X * (_X - 2) ** 2 + sympy.Symbol("a")  # 자유 기호가 남아 N() 이 수가 아니다
    with caplog.at_level(logging.DEBUG, logger="whymath.l3.equivalent.counterexample_fuzz"):
        assert (
            fuzz_module._isolated_exact_root(unevaluated, _X, sympy.Integer(2), 2.0, _WINDOW)
            is False
        )
    assert any(
        "무연근 군집 확인 회피" in rec.getMessage() and "TypeError" in rec.getMessage()
        for rec in caplog.records
    )
    assert (
        fuzz_module._isolated_exact_root(_X * (_X - 2) ** 2, _X, sympy.Integer(2), 2.0, _WINDOW)
        is True
    )  # 대조군 — 같은 식에서 자유 기호만 없으면 고립


def test_isolation_zero_unknown_branch_fails_closed_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """분기 Z ⓐ — 도함수 값의 0 여부를 못 가리면 '모른다'다(고립됨으로 접지 않는다)."""
    harmful = _near_root_condition(
        3, 1
    )  # 무연근의 순중복도 2 — 1계 도함수 값이 0 이어야 다음 차수로
    isolated = _isolated_hole_condition(3, 1)
    assert fuzz_answer(isolated, {"x": "5"}, "largest").state == "pass"  # 대조군
    monkeypatch.setattr(fuzz_module.sympy, "diff", _hidden_zero_diff(sympy.diff))
    assert fuzz_answer(harmful, {"x": "0"}, "largest").state == "unverifiable"
    assert fuzz_answer(isolated, {"x": "5"}, "largest").state == "unverifiable"


def test_isolation_zero_unknown_branch_direct() -> None:
    """분기 Z ⓐ 직접 — 1계 도함수 값이 증명 불가한 0(`(x-1)·c`, c = sin²1 + cos²1 − 1)이면 False,
    대조군(같은 모양에서 c 대신 결정되는 수)은 True."""
    undecided = (_X - 1) * _HIDDEN_ZERO
    assert fuzz_module._isolated_exact_root(undecided, _X, sympy.Integer(1), 1.0, _WINDOW) is False
    decided = (_X - 1) * (_X - 5)
    assert fuzz_module._isolated_exact_root(decided, _X, sympy.Integer(1), 1.0, _WINDOW) is True


def test_isolation_lead_missing_branch_fails_closed_end_to_end() -> None:
    """분기 L ⓐ — 무연근의 순중복도 9(> 8)는 도함수로 중복도를 못 구해 판정 불가. 경계(8)는 고립 확인."""
    assert fuzz_answer(_near_root_condition(10, 1), {"x": "0"}, "largest").state == "unverifiable"
    assert (
        fuzz_answer(_isolated_hole_condition(10, 1), {"x": "5"}, "largest").state == "unverifiable"
    )
    assert fuzz_answer(_near_root_condition(9, 1), {"x": "0"}, "largest").state == "unverifiable"
    assert (
        fuzz_answer(_isolated_hole_condition(9, 1), {"x": "5"}, "largest").state == "pass"
    )  # 경계 대조군


def test_isolation_lead_missing_branch_direct() -> None:
    """분기 L 직접 — ⓐ 순중복도 9 ⓑ 항등적으로 0 인 잔차는 False, 순중복도 8 은 True(대조군)."""
    point = sympy.Integer(2)
    assert fuzz_module._isolated_exact_root(_X * (_X - 2) ** 9, _X, point, 2.0, _WINDOW) is False
    assert fuzz_module._isolated_exact_root(sympy.Integer(0), _X, point, 2.0, _WINDOW) is False
    assert (
        fuzz_module._isolated_exact_root((_X - 3) * (_X - 2) ** 8, _X, point, 2.0, _WINDOW) is True
    )


def test_isolation_ratio_threshold_is_half_of_the_value_at_the_point() -> None:
    """창 양 끝에서 g 가 g(점)의 절반 넘게 벗어나면 고립이 아니다 — 문턱 양쪽. 선형 g 에서 다른 근이
    점에서 r 떨어져 있으면 벗어남 비율은 창/r 이라, r 이 창의 2배보다 약간 가까우면(1.9배) 닫히고
    약간 멀면(2.1배) 고립이다. 문턱이 비율 1(느슨)이면 1.9배도 고립으로 읽는다."""
    point = sympy.Integer(2)
    near = (_X - 2) * (_X - 2 - _WINDOW * sympy.Rational(19, 10))
    far = (_X - 2) * (_X - 2 - _WINDOW * sympy.Rational(21, 10))
    assert fuzz_module._isolated_exact_root(near, _X, point, 2.0, _WINDOW) is False
    assert fuzz_module._isolated_exact_root(far, _X, point, 2.0, _WINDOW) is True


def test_fuzz_true_root_just_inside_twice_the_window_is_not_dropped() -> None:
    """끝에서 끝까지 — 창은 격자 간격의 2배(0.0200)라 무연근에서 0.0400 안의 참 근은 판정 불가로 닫히고
    (수치 탐색은 이 근을 따로 찾지만 창 끝 비율 검사가 닫는다 — 안전이 아니라 확인 가능성의 비용)
    0.0400 밖은 무연근만 버려져 판정된다. 양쪽 경계가 문턱 1/2 에 묶여 있다."""
    for side in ("+", "-"):
        for gap, state in (("38/1000", "unverifiable"), ("42/1000", "pass")):
            condition = f"x*(x-2)**2*(x-2{side}{gap})/(x-2) = 0"
            true_root = f"2 {'+' if side == '-' else '-'} {gap}"
            assert fuzz_answer(condition, {"x": true_root}, "largest").state == state


def test_isolation_unknown_window_or_inexact_point_is_not_isolated() -> None:
    """분기 W·P — 창을 정할 수 없거나(None) 점이 근사 소수·자유 기호를 담으면 고립을 확인한 것이 아니다."""
    residual = (_X - 3) * (_X - 2)
    assert fuzz_module._isolated_exact_root(residual, _X, sympy.Integer(2), 2.0, _WINDOW) is True
    assert fuzz_module._isolated_exact_root(residual, _X, sympy.Integer(2), 2.0, None) is False
    assert fuzz_module._isolated_exact_root(residual, _X, sympy.Float(2), 2.0, _WINDOW) is False
    assert fuzz_module._isolated_exact_root(residual, _X, sympy.Symbol("a"), 2.0, _WINDOW) is False


# ── ② 4차 이상 근호 근의 원문 정의역 평가 예산 ───────────────────────────────
_QUARTIC_ALGEBRAIC_HOLE = "(x**4 + 3*x**3 - 7*sqrt(5)*x**2 + 11*x - 13)*(x-1)/(x-1) = 0"
_QUARTIC_INTEGER_HOLE = "(x**4 + 3*x**3 - 7*x**2 + 11*x - 13)*(x-1)/(x-1) = 0"
_SECONDS_LIMIT = 10.0  # 종전 15분 이상 · 15초 안팎이 정상인 CI 부하를 넉넉히 덮는 상한


def _timed(call: Callable[[], AnswerVerdict]) -> tuple[AnswerVerdict, float]:
    started = time.perf_counter()
    verdict = call()
    return verdict, time.perf_counter() - started


# 기약 4차 근(페라리 꼴)의 최소 크기 — 예산(60)을 끈 코드가 원문에 넣어 보게 되는 근이다. 예산 값이
# 아니라 이 고정 문턱을 쓰므로 예산을 10**9 로 끄거나 우회해도 놓치지 않는다.
_OVERSIZED_ROOT_OPS = 69


class _OversizedRootEvaluated(BaseException):  # noqa: N818 — `except Exception` 이 삼키지 못하게
    """예산을 넘는 근이 원문 정의역 평가에 들어왔다."""


@pytest.fixture
def no_oversized_root_evaluation(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """원문 정의역 평가(`condition_definedness`)에 `count_ops` > 69 인 값이 들어오면 즉시 중단한다.

    예산이 꺼지거나 우회돼도 CI 가 job 시간초과로만 알리지 않고 수 초 안에 단언 실패로 알린다.
    검증기들이 `except Exception` 으로 예외를 삼키므로 BaseException 으로 올리고, 본 값은 목록에도
    남겨 시험 끝에서 한 번 더 확인한다."""
    seen: list[int] = []
    original = verify_answer_module.condition_definedness

    def spy(condition: str, values: Mapping[str, sympy.Expr]) -> str:
        for value in values.values():
            ops = int(sympy.count_ops(value))
            if ops > _OVERSIZED_ROOT_OPS:
                seen.append(ops)
                raise _OversizedRootEvaluated(f"count_ops={ops}")
        return original(condition, values)

    monkeypatch.setattr(verify_answer_module, "condition_definedness", spy)
    yield seen
    assert seen == []


@pytest.mark.usefixtures("no_oversized_root_evaluation")
@pytest.mark.parametrize("kind", ["sum", "product"])
@pytest.mark.parametrize("condition", [_QUARTIC_ALGEBRAIC_HOLE, _QUARTIC_INTEGER_HOLE])
def test_quartic_aggregate_with_removable_singularity_is_closed_within_the_time_limit(
    condition: str, kind: str
) -> None:
    """P3-83 ② — 제거 가능한 특이점이 붙은 기약 4차식의 근 집계는 근의 페라리 꼴을 원문에 넣어 보는 데
    수 분이 걸렸다(근호 계수 15분 이상 · 정수 계수 근 하나당 25초). 크기 예산으로 판정 불가로 닫는다 —
    틀린 pass 가 아니라 판정 불가여야 하고, 맞는 주장도 거짓 fail 이 되지 않는다."""
    right = "-3" if kind == "sum" else "-13"  # 근의 합 −3 · 곱 −13 (참)
    wrong = "5" if kind == "sum" else "7"
    for claimed in (right, wrong):
        verdict, elapsed = _timed(
            lambda claimed=claimed: verify_root_aggregate(condition, claimed, kind)  # type: ignore[arg-type]
        )
        assert verdict.state == "unverifiable"
        assert elapsed < _SECONDS_LIMIT


@pytest.mark.usefixtures("no_oversized_root_evaluation")
def test_quartic_real_root_count_with_algebraic_coefficient_is_closed_within_the_time_limit() -> (
    None
):
    """② 실근 개수 — 대수 계수 4차는 근 표현이 예산을 넘어 판정 불가(정수 계수는 `real_roots` 의 수치
    근이라 종전에도 빨랐고 그대로 판정된다). 주장값은 판정 불가에 영향이 없어 하나만 본다."""
    claimed = "2"
    verdict, elapsed = _timed(lambda: verify_real_root_count(_QUARTIC_ALGEBRAIC_HOLE, claimed))
    assert verdict.state == "unverifiable"
    assert elapsed < _SECONDS_LIMIT
    integer_verdict, integer_elapsed = _timed(
        lambda: verify_real_root_count(_QUARTIC_INTEGER_HOLE, claimed)
    )
    assert integer_verdict.state in ("pass", "fail")
    assert integer_elapsed < _SECONDS_LIMIT


@pytest.mark.parametrize(
    ("condition", "claimed_sum"),
    [
        ("(x**3 - 3*x + 1)*(x-1)/(x-1) = 0", "0"),
        ("(x**3 - 6*x + 2)*(x-1)/(x-1) = 0", "0"),
        ("(x**2 - 2*sqrt(5)*x + 3)*(x-1)/(x-1) = 0", "2*sqrt(5)"),
    ],
)
def test_cubic_or_quadratic_with_removable_singularity_is_still_decided(
    condition: str, claimed_sum: str
) -> None:
    """② 대조군 — 근 표현이 작은 3차 이하(카르다노 꼴 count_ops ≤ 45)는 예산 안이라 종전처럼 판정된다."""
    assert verify_root_aggregate(condition, claimed_sum, "sum").state == "pass"
    assert verify_root_aggregate(condition, "100", "sum").state == "fail"


def _radical_sum_with_ops(target: int) -> sympy.Expr:
    """`count_ops` 가 정확히 `target` 인 근호 합 — 서로 다른 소수의 제곱근을 더하고(항 하나에 3), 앞의
    몇 항에 계수 2 를 곱해(항마다 +1) 크기를 한 칸씩 맞춘다."""
    primes = list(sympy.primerange(2, 600))
    for count in range(1, len(primes) + 1):
        for scaled in range(count + 1):
            terms = [(2 if i < scaled else 1) * sympy.sqrt(p) for i, p in enumerate(primes[:count])]
            candidate = sympy.Add(*terms)
            if sympy.count_ops(candidate) == target:
                return candidate
    raise AssertionError("크기가 맞는 식을 만들지 못했다")


def test_roots_between_44_and_60_ops_are_still_decided() -> None:
    """② 예산이 너무 낮아지지 않는지 — 근호 계수 3차 `x³ + 2√2·x² − 5x + 1` 의 근은 `count_ops` 가
    44·58·60 이고 0.1초 안에 정의역이 평가된다. 예산을 44 로 낮추면 58·60 이 닫혀 판정 불가가 된다."""
    condition = "(x**3 + 2*sqrt(2)*x**2 - 5*x + 1)*(x-1)/(x-1) = 0"
    residual, _ = verify_answer_module._parse_condition(condition)
    roots = sympy.roots(sympy.Poly(residual, _X))
    assert sorted(sympy.count_ops(root) for root in roots) == [44, 58, 60]  # 픽스처 전제
    assert verify_real_root_count(condition, "3").state == "pass"
    assert verify_real_root_count(condition, "1").state == "fail"


def test_definedness_budget_closes_only_oversized_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    """② 예산의 경계 — 근 표현의 `count_ops` 가 상한과 같으면 평가하고(대조군), 하나만 넘어도 평가 없이
    판정 불가. CRootOf(5차 이상)는 60자리 수치로 넣으므로 식이 커도 예산과 무관하게 평가한다."""
    budget = verify_answer_module._DEF_ROOT_MAX_OPS
    calls: list[str] = []
    original = verify_answer_module.condition_definedness

    def counting(condition: str, values: object) -> str:
        calls.append(condition)
        return original(condition, values)  # type: ignore[arg-type]

    monkeypatch.setattr(verify_answer_module, "condition_definedness", counting)
    condition = "(x**2 - 2)*(x-1)/(x-1) = 0"
    at_budget = _radical_sum_with_ops(budget)
    over_budget = _radical_sum_with_ops(budget + 1)
    assert sympy.count_ops(at_budget) == budget
    assert sympy.count_ops(over_budget) == budget + 1

    assert verify_answer_module._root_definedness(condition, "x", at_budget, {}) == "defined"
    assert len(calls) == 1
    assert verify_answer_module._root_definedness(condition, "x", over_budget, {}) == "unknown"
    assert len(calls) == 1  # 예산을 넘은 근은 평가하지 않았다

    quintic_root = sympy.CRootOf(_X**5 - _X - 1, 0)
    assert verify_answer_module._root_definedness(condition, "x", quintic_root, {}) == "defined"
    assert len(calls) == 2
    # 식이 큰 CRootOf(다항식 항이 많다)도 예산 대상이 아니다 — 수치로 평가한다.
    wide = sympy.CRootOf(sum((k + 2) * _X**k for k in range(0, 45)) - 7, 0)
    assert sympy.count_ops(wide) > budget
    assert verify_answer_module._root_definedness(condition, "x", wide, {}) == "defined"
    assert len(calls) == 3
