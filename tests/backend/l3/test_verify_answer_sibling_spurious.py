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

import pytest
import sympy

from whymath_backend.l3.equivalent.counterexample_fuzz import fuzz_answer
from whymath_backend.l3.verify_answer import (
    _exact_decimal_text,
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
    """허용 구조 밖(`asinh`) — 원문 정의역을 못 가리면 pass 로 단정하지 않는다(종전 pass).
    반례는 정의역과 무관하게 반례다 — 틀린 답은 그대로 fail."""
    assert fuzz_answer("asinh(x) = 0", {"x": "0"}).state == "unverifiable"
    assert fuzz_answer("asinh(x) = 0", {"x": "1"}).state == "fail"


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
        ("x = sqrt(2.0)", "x = sqrt((2/1))"),
        ("x = 2.0**0.5", "x = (2/1)**(1/2)"),
        ("(x - 1)**2 + 1e-20 = 0", "(x - 1)**2 + (1/100000000000000000000) = 0"),
        ("x = 1.5", "x = (3/2)"),
        ("x**2 = 4", None),  # 소수 리터럴 없음
        ("x = 2j", None),  # 허수 리터럴은 바꾸지 않는다
    ],
)
def test_exact_decimal_text_rewrites_literals_only(condition: str, expected: str | None) -> None:
    assert _exact_decimal_text(condition) == expected
