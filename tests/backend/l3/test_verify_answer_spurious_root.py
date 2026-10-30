"""P3-75 — 평가 파싱의 자동 약분이 만든 무연근(분수방정식에서 원문 분모가 0 인 값)을 근으로 받지 않는다.

`safe_sympify` 는 식을 세우는 순간 `x*(x - 2)/(x - 2)` → `x` 처럼 접는다. 접힌 식은 x = 2 에서 정의된
것처럼 보여 Tier1·근 선택·해 존재성 분류가 그 값을 근으로 받았다(RF3·RF4). 금지 목록(분모 탐지)은
표기 변형에 뚫렸으므로(P3-71 4차 검토), 원문 구문 나무를 허용 노드만으로 그 점에서 노드별로 평가하는
`condition_definedness`(허용 목록)로 판정한다. 이 파일은 ①6꼴 + RF3/RF4 를 네 경로(C1 Tier1 ·
근 선택 원소 1개 · 해 존재성 분류 · solution_qa C2 단일 후보 문항) 전부에 넣고 ②대조군의 종전 판정이
유지되는지 ③판정기의 절마다 그 절이 없으면 통과하는 입력을 함께 본다.
"""

from __future__ import annotations

from typing import Any

import pytest
import sympy

from whymath_backend.harness import solution_qa as qa
from whymath_backend.l3.verify_answer import (
    classify_solvability,
    condition_definedness,
    derive_selected_root,
    trusted_real_roots,
    verify_answer,
    verify_root_selection,
)

# (이름, 조건, 무연근/비실근 답) — 전부 '원문에서 그 값이 근이 아니다'.
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

# 해 존재성 분류의 기대 — 원문에서 정의되는 실근이 없으면 no_solution. a2 는 x = -1 이 진짜 근이라
# 유일해다(아래 별도 테스트가 그 근이 1 이 아니라 -1 임을 확인한다).
SOLVABILITY: dict[str, str] = {name: "no_solution" for name in SPURIOUS}
SOLVABILITY["a2 Derivative 속 약분"] = "unique"


def _single_candidate_record(condition: str, answer: str) -> dict[str, Any]:
    """풀이 마지막 단계가 후보 1개(`x = 값`)인 문항 — solution_qa C2 단일 후보 경로."""
    return {
        "slug": "p3-75",
        "unit_codes": ["SYN"],
        "question_format": "단답형",
        "answer": answer,
        "verify": {
            "conditions": [condition],
            "answer_map": {"x": answer},
            "solution_steps": [condition, f"x = {answer}"],
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# ① 6꼴 + RF3/RF4 × 네 경로
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", sorted(SPURIOUS))
def test_tier1_rejects_spurious_root(name: str) -> None:
    condition, answer = SPURIOUS[name]
    verdict = verify_answer([condition], {"x": answer})
    assert verdict.state == "fail", verdict.reason
    assert verify_answer(condition, {"x": answer}).state == "fail"  # 단일 str 경로도 같다


@pytest.mark.parametrize("name", sorted(SPURIOUS))
@pytest.mark.parametrize("selection", ["unique", "largest", "smallest"])
def test_root_selection_single_element_never_passes(name: str, selection: str) -> None:
    condition, answer = SPURIOUS[name]
    verdict = verify_root_selection([condition], {"x": answer}, selection)  # type: ignore[arg-type]
    assert verdict.state == "unverifiable", verdict.reason


@pytest.mark.parametrize("name", sorted(SPURIOUS))
def test_classify_solvability_does_not_count_spurious_root(name: str) -> None:
    condition, _ = SPURIOUS[name]
    assert classify_solvability([condition]).state == SOLVABILITY[name]


def test_derivative_form_keeps_only_the_genuine_root() -> None:
    """a2: f(x) = x³(x−1)/(x−1) 은 x ≠ 1 에서 x³ 이라 f'(x) = 3 의 근은 −1 하나다(1 은 무연근)."""
    condition, _ = SPURIOUS["a2 Derivative 속 약분"]
    x = sympy.Symbol("x")
    roots = trusted_real_roots(condition, 3 * x**2 - 3, x)
    assert roots == [sympy.Integer(-1)]
    assert verify_root_selection([condition], {"x": "-1"}, "unique").state == "pass"


@pytest.mark.parametrize("name", sorted(SPURIOUS))
def test_solution_qa_single_candidate_item_is_not_pass(name: str) -> None:
    condition, answer = SPURIOUS[name]
    item = qa.judge_record(_single_candidate_record(condition, answer))
    assert item.verdict is qa.Verdict.FAIL, item.reason_text()
    assert item.checks["C1"].code == "C1_TIER1_FAIL"
    # C2 는 '풀이 최종 값 ↔ 정답' 의 일치만 본다(조건은 C1 소관) — 그래서 C2 자체는 통과로 남는다.
    assert item.checks["C2"].state is qa.CheckState.PASS


@pytest.mark.parametrize("name", sorted(SPURIOUS))
def test_derive_selected_root_does_not_derive_spurious_root(name: str) -> None:
    condition, answer = SPURIOUS[name]
    derived = derive_selected_root(condition, "unique")
    assert derived != answer


# ──────────────────────────────────────────────────────────────────────────
# ② 대조군 — 종전 판정 유지
# ──────────────────────────────────────────────────────────────────────────
def test_control_cancelled_form_at_defined_root() -> None:
    condition = "x*(x - 2)/(x - 2) = 3"
    assert verify_answer([condition], {"x": "3"}).state == "pass"
    assert verify_root_selection([condition], {"x": "3"}, "unique").state == "pass"
    assert classify_solvability([condition]).state == "unique"
    assert qa.judge_record(_single_candidate_record(condition, "3")).verdict is qa.Verdict.PASS
    assert derive_selected_root(condition, "unique") == "3"


def test_control_rational_equation() -> None:
    condition = "x/(x + 5) = 1/3"
    assert verify_answer([condition], {"x": "5/2"}).state == "pass"
    assert verify_root_selection([condition], {"x": "5/2"}, "unique").state == "pass"
    assert classify_solvability([condition]).state == "undecidable"  # 비다항 — 종전과 같다


@pytest.mark.parametrize(
    ("condition", "answer"),
    [
        ("Integral(2*x**2 + 1*x + 0, (x, -3, 2)) = y", "125/6"),  # 근이 미계산 적분 — is_real 미정
        ("Integral(4*sin(x), (x, 0, pi/2)) = y", "4"),
    ],
)
def test_control_integral_root_selection_and_solvability(condition: str, answer: str) -> None:
    assert verify_root_selection([condition], {"y": answer}, "unique").state == "pass"
    assert classify_solvability([condition]).state == "unique"


def test_numeric_realness_fallback() -> None:
    """근의 실수 여부를 SymPy 가정이 못 정하면 60자리 평가의 허수부로 가린다(0 이면 실수)."""
    assert classify_solvability("y**2 + Integral(cos(x**3), (x, 0, 1)) = 0").state == "no_solution"
    assert classify_solvability("y**2 - Integral(cos(x**3), (x, 0, 1)) = 0").state == "multiple"
    # 허수부가 1e-12 쯤인 근 — Tier1 허용치(1e-9)로는 실수로 보이지만 0 이 아니다(실근 아님).
    tiny = "y**2 + Integral(cos(x**3), (x, 0, 1))/10**24 = 0"
    assert classify_solvability(tiny).state == "no_solution"


def test_control_derivative_with_domain() -> None:
    conditions = ["Derivative(x**3, x).doit() = 3", "x > 0"]
    assert verify_answer(conditions, {"x": "1"}).state == "pass"
    assert verify_root_selection(conditions, {"x": "1"}, "unique").state == "pass"


@pytest.mark.parametrize(
    ("conditions", "answer"),
    [
        ("2*a*x = b", {"x": "b/(2*a)"}),  # 답이 기호 — 잔차가 기호적으로 0
        ("a*x >= a*x", {"x": "1"}),  # 잔차가 접히며 사라진 이름 a
        ("x**2 - 2 = 0", {"x": "1.4142135623730951"}),  # 근사 소수 답 — 허용치 판정 유지
        ("(x + I)*(x - I) = 2", {"x": "1"}),  # 허수 단위를 쓰는 조건 — 실수 아닌 중간값 정상
        ("x**2 = -1", {"x": "I"}),  # 복소 답
        ("Integral(3*x**2 + 2*x + 1, (x, 0, 2)) = y", {"y": "14"}),
        ("Derivative((2*x**2 + 3*x + 1) / (-1*x + 2), x).doit().subs(x, 1) = y", {"y": "13"}),
        ("x = log(2**3 + 2**3, 2)", {"x": "4"}),
        ("x - floor(17/5)*5 = 0", {"x": "15"}),
        # 코퍼스 실측 꼴(전 은행 대조에서 종전 pass 였던 것) — 허용 구조 안이어야 한다
        ("Integral(4*sin(x), (x, 0, pi/2)) = y", {"y": "4"}),  # 적분 안 전해석 함수
        ("Derivative(x**n, x).doit().subs(x, 2) = 4*2**n", {"n": "8"}),  # 지수가 매개변수
        (
            "Derivative(t**2 - 12*t - Derivative(t**2 - 12*t, t), t).doit().subs(t, s) = 0",
            {"s": "7"},
        ),  # 중첩 미분(속도·가속도 꼴)
    ],
)
def test_control_pass_is_kept(conditions: str, answer: dict[str, str]) -> None:
    assert verify_answer(conditions, answer).state == "pass"


# ──────────────────────────────────────────────────────────────────────────
# ③ 판정기의 절마다 — 그 절이 없으면 통과하는 입력
# ──────────────────────────────────────────────────────────────────────────
def test_inequality_at_undefined_point_fails() -> None:
    assert verify_answer("x*(x - 2)/(x - 2) > 1", {"x": "2"}).state == "fail"
    assert verify_answer("x*(x - 2)/(x - 2) > 1", {"x": "3"}).state == "pass"


def test_quotient_rule_derivative_at_pole_is_undefined() -> None:
    """몫의 미분을 극에서 대입하면 원문이 정의되지 않는다 — 극이 아닌 점은 정의된다."""
    at_pole = "Derivative((2*x**2 + 3*x + 1) / (-1*x + 2), x).doit().subs(x, 2) = y"
    off_pole = "Derivative((2*x**2 + 3*x + 1) / (-1*x + 2), x).doit().subs(x, 1) = y"
    assert condition_definedness(at_pole, {"y": sympy.Integer(1)}) == "undefined"
    assert condition_definedness(off_pole, {"y": sympy.Integer(1)}) == "defined"


def test_parametric_spurious_root_is_not_pass() -> None:
    """답이 기호여도 원문이 정의되는 샘플이 하나도 없으면 pass 가 아니다."""
    verdict = verify_answer("x*(x - a)/(x - a) = a", {"x": "a"})
    assert verdict.state == "unverifiable", verdict.reason
    sampled = verify_answer("x*(x - a)/(x - a) + 0*b = a", {"x": "a"})  # 잔차가 기호적으로 0
    assert sampled.state == "unverifiable", sampled.reason
    # 잔차에 자유 기호(b)가 남아 Tier1 샘플링 경로를 탄다 — 샘플마다 원문은 x = a 에서 정의되지 않는다.
    parametric = verify_answer("x*(x - a)/(x - a) >= a - b**2", {"x": "a"})
    assert parametric.state == "unverifiable", parametric.reason
    assert verify_answer("x*(x - a)/(x - a) >= a - b**2", {"x": "a + 1"}).state == "pass"
    # 원문 이름 c 는 잔차에서도 답에서도 사라진다(c/c → 1) — 원문 평가에는 그래도 값이 필요하다.
    assert verify_answer("x*c/c >= -b**2", {"x": "1"}).state == "pass"


def test_subs_target_is_a_bound_name() -> None:
    """`.subs(x, a)` 의 x 는 묶인 이름이다 — 답 a 의 정확한 점에서 판정해 fail 을 확정한다
    (x 를 샘플 기호로 잘못 세면 샘플 경로로 빠져 판정 불가로 약해진다)."""
    condition = "Derivative(x**3*(x - 1)/(x - 1), x).doit().subs(x, a) = 3"
    assert verify_answer(condition, {"a": "1"}).state == "fail"
    assert verify_answer(condition, {"a": "-1"}).state == "pass"


def test_float_answer_at_pole_is_not_pass() -> None:
    """근사 소수 답이 극 근처를 가리키면 '정의되지 않음' 을 확정하지 않는다 — 판정 불가.

    `2.0` 은 이진 소수로 정확히 2 라 분모가 정확히 0 이 된다(확정 — fail).
    """
    assert verify_answer("x*(x - 2)/(x - 2) = 2", {"x": "2.0"}).state == "fail"
    third = "0.333333333333333"
    assert verify_answer("x*(3*x - 1)/(3*x - 1) = 1/3", {"x": third}).state == "unverifiable"


def test_real_domain_violation_is_unknown() -> None:
    """실수 입력에서 실수가 아닌 중간값(√ 음수)은 실수 범위 정의역을 확인하지 못한 것이다."""
    assert verify_answer("sqrt(x - 3)**2 = x - 3", {"x": "1"}).state == "unverifiable"
    assert verify_answer("sqrt(x - 3)**2 = x - 3", {"x": "4"}).state == "pass"


def test_exact_nonzero_residual_within_tolerance_fails() -> None:
    assert verify_answer("x**2 - 2 = 1/10**15", {"x": "sqrt(2)"}).state == "fail"
    assert verify_answer("x**2 - 2 = 0", {"x": "sqrt(2)"}).state == "pass"


@pytest.mark.parametrize(
    ("condition", "values", "expected"),
    [
        ("x*(x - 2)/(x - 2) = 2", {"x": 2}, "undefined"),  # 나눗셈 — 분모 정확히 0
        ("x*(x - 2)**0 = 2", {"x": 2}, "undefined"),  # 0 의 0 제곱
        ("x*(x-2)*(x-2)**-1 = 2", {"x": 2}, "undefined"),  # 0 의 음수 제곱
        ("x*(x - 2)*exp(-log(x - 2)) = 2", {"x": 2}, "undefined"),  # 함수 특이점(log 0)
        ("log(x, 1) = 3", {"x": 8}, "undefined"),  # 밑 1 의 로그
        ("x = tan(pi/2)", {"x": 1}, "undefined"),
        ("1/(x - 2) != 0", {"x": 2}, "undefined"),  # ≠ 관계
        ("Eq(x/(x - 2), 1)", {"x": 2}, "undefined"),  # Eq 생성자
        ("x*(x - 2)/(x - 2) = 2", {"x": 3}, "defined"),
        ("x^2 = 4", {"x": 2}, "defined"),  # ^ 는 거듭제곱
        ("Derivative(x**3, x).doit().subs(x, a) = 108", {"a": 6}, "defined"),
        ("Derivative(sqrt(x), x).doit() = 1/2", {"x": 1}, "unknown"),  # 미분 안 √ — 허용 밖
        ("Integral(1/x, (x, 1, 2)) = y", {"y": 1}, "unknown"),  # 적분 안 변수 분모 — 허용 밖
        ("x = y", {"x": 1}, "unknown"),  # 값 없는 이름
        ("x.subs(x + 1, 2) = 3", {"x": 1}, "unknown"),  # 기호가 아닌 대입 대상
        ("y = 2**x", {"x": 10**6, "y": 1}, "unknown"),  # 계산 예산 초과
        ("y = 3**x", {"x": 10**15, "y": 1}, "unknown"),  # 예산 검사가 계산 전에 막는다
        ("x = (2*x - 2)/(x - 1 - x + 1 + sqrt(2)**2 - 2)", {"x": 1}, "undefined"),
        ("Integral(a*(a - 2)/(a - 2)*x, (x, 0, 1)) = y", {"a": 2, "y": 1}, "undefined"),
        ("Derivative(x**3*(x - 1)/(x - 1), x).doit().subs(x, a) = 3", {"a": 1}, "undefined"),
        ("Derivative(x**n, x).doit().subs(x, 2) = y", {"n": -1, "y": 1}, "defined"),
        ("Derivative(x**n, x).doit().subs(x, 2) = y", {"n": 1, "y": 1}, "defined"),
        ("Derivative(2**x, x).doit() = y", {"x": 1, "y": 1}, "defined"),  # 양의 상수 밑
        ("Derivative((-2)**x, x).doit() = y", {"x": 1, "y": 1}, "unknown"),  # 음의 밑
        ("Derivative(0**x, x).doit() = 0", {"x": 1}, "unknown"),  # 0 의 기호 지수 — 양수 밑 아님
        ("Derivative(x**x, x).doit() = 1", {"x": 1}, "unknown"),  # 밑·지수 모두 미분 변수
        ("Integral(x**(-1), (x, 1, 2)) = y", {"y": 1}, "unknown"),  # 적분 안 음수 지수
        ("Integral(x**2, (x, 0, 1)) = y", {"x": 5, "y": 1}, "defined"),  # 적분 변수는 묶인 이름
    ],
)
def test_condition_definedness(condition: str, values: dict[str, int], expected: str) -> None:
    point = {name: sympy.Integer(value) for name, value in values.items()}
    assert condition_definedness(condition, point) == expected


# ──────────────────────────────────────────────────────────────────────────
# ④ PR #1719 독립 검토 반영 — 검토가 찾은 우회·회귀를 RED/대조로 동결
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("condition", "values"),
    [
        # 적분 피적분식 속 변수 무관 분모(순서·꼴만 바꾼 우회 — 검토 1)
        ("Integral(t*(x - 2)/(x - 2), (t, 0, 1)) = 1/2", {"x": "2"}),
        ("Integral(exp(t)*(x - 2)**3/(x - 2)**2, (t, 0, 1)) = 0", {"x": "2"}),
        ("Integral((a - 2)*x/(a - 2), (x, 0, 1)) = y", {"a": "2", "y": "1/2"}),
        ("Integral(sin(t/(a - 2)), (t, 0, 1)) + a = y", {"a": "2", "y": "2"}),
        # 미분 안 같은 꼴
        ("Derivative(t*(x - 2)/(x - 2), t).doit().subs(t, 1) = 1", {"x": "2"}),
    ],
)
def test_constant_denominator_inside_integral_or_derivative(
    condition: str, values: dict[str, str]
) -> None:
    point = {name: sympy.sympify(value) for name, value in values.items()}
    assert condition_definedness(condition, point) == "undefined"
    # sin(t/0) 꼴은 평가 잔차부터 zoo 라 종전에도 판정 불가다 — 어느 쪽이든 pass 는 아니다.
    assert verify_answer([condition], values).state != "pass"


@pytest.mark.parametrize(
    ("condition", "values"),
    [
        ("Integral(t*(x - 2)/(x - 2), (t, 0, 1)) = 1/2", {"x": "2"}),
        ("Integral(exp(t)*(x - 2)**3/(x - 2)**2, (t, 0, 1)) = 0", {"x": "2"}),
        ("Integral((a - 2)*x/(a - 2), (x, 0, 1)) = y", {"a": "2", "y": "1/2"}),
    ],
)
def test_integral_spurious_root_fails(condition: str, values: dict[str, str]) -> None:
    """검토 재현 3꼴 — 종전 Tier1 pass 였다. 원문 정의역으로 fail 이 확정된다."""
    assert verify_answer([condition], values).state == "fail"


def test_integral_of_derivative_with_constant_denominator_is_undefined() -> None:
    condition = "Integral(Derivative(t**2*(x - 2)/(x - 2), t), (t, 0, 1)) = 1"
    assert condition_definedness(condition, {"x": sympy.Integer(2)}) == "undefined"
    assert verify_answer([condition], {"x": "2"}).state != "pass"


def test_control_integral_with_nonzero_constant_denominator() -> None:
    assert verify_answer(["Integral(t*(x - 2)/(x - 2), (t, 0, 1)) = 1/2"], {"x": "3"}).state == (
        "pass"
    )


@pytest.mark.parametrize(
    "condition",
    ["(x - 1)**2 + 1e-20 = 0", "(x - 1)**2 + 0.0000000001 = 0", "(x-1)**2 + 1.0/10**12 = 0"],
)
def test_decimal_literal_tiny_residual_is_not_pass(condition: str) -> None:
    """조건의 소수 리터럴을 적힌 십진값으로 읽으면 잔차가 0 이 아니다 — 확정은 안 하되 pass 금지."""
    assert verify_answer([condition], {"x": "1"}).state == "unverifiable"


@pytest.mark.parametrize(
    ("condition", "answer"),
    [
        ("1.5*x = 3", "2"),  # 소수 리터럴이지만 정확히 0
        ("x - 0.1 = 0", "1/10"),
        ("x**2 = 2", "1.41421356237"),  # 근사 소수 답 — 종전 허용치 판정
    ],
)
def test_control_decimal_literal_pass_is_kept(condition: str, answer: str) -> None:
    assert verify_answer([condition], {"x": answer}).state == "pass"


@pytest.mark.parametrize(
    "condition",
    ["x + 0*((x-2)/(x-2), 1)[0] = 2", "x*[(x-2)/(x-2)][0] = 2", "x*((x-2)/(x-2), 0)[0] = 2"],
)
def test_nodes_outside_allowlist_are_unknown(condition: str) -> None:
    """허용 목록 밖 노드(첨자·튜플·리스트)는 판정 불가다 — 금지 목록이 아니라 허용 목록이다(검토 4)."""
    assert condition_definedness(condition, {"x": sympy.Integer(2)}) == "unknown"
    assert verify_answer([condition], {"x": "2"}).state == "unverifiable"


def test_acot_is_not_smooth_at_zero() -> None:
    """SymPy 의 acot 은 0 에서 불연속이다 — 미분 안에서 허용하지 않는다(검토 6)."""
    assert verify_answer(["Derivative(acot(x), x).doit() = -1"], {"x": "0"}).state != "pass"


def test_integer_functions_require_textbook_domain() -> None:
    assert verify_answer(["x + 0*binomial(x - 3, 1) = 2"], {"x": "2"}).state == "unverifiable"
    assert verify_answer(["binomial(n, 2) = 10"], {"n": "5"}).state == "pass"
    assert verify_answer(["factorial(n) = 120"], {"n": "5"}).state == "pass"


@pytest.mark.parametrize(
    ("condition", "answer"),
    [
        ("x = sqrt(-4)*sqrt(-9)", "-6"),  # 상수 하위 나무의 의도된 복소 산술
        ("x = (1 + sqrt(-3))*(1 - sqrt(-3))", "4"),
    ],
)
def test_control_constant_complex_arithmetic(condition: str, answer: str) -> None:
    assert verify_answer([condition], {"x": answer}).state == "pass"


def test_control_quintic_crootof_and_irrational_cubic() -> None:
    """5차 기약 다항식(CRootOf)·무리 계수 3차식(카르다노 근호식) — 종전 판정 유지(검토 8)."""
    quintic = "x**5 - x - 1 = 0"
    assert classify_solvability(quintic).state == "unique"
    assert verify_root_selection(quintic, {"x": "1.1673039782614187"}, "largest").state == "pass"
    cubic = "x**3 - 3*sqrt(2)*x + 1 = 0"
    assert classify_solvability(cubic).state == "multiple"
    assert verify_root_selection(cubic, {"x": "1.9298902860579772"}, "largest").state == "pass"
    assert verify_root_selection(cubic, {"x": "0.23891668457149623"}, "largest").state == "fail"


def test_derive_selected_root_keeps_radical_notation() -> None:
    """유도 정답은 종전 근호식 표기다 — CRootOf 를 내면 생성기 정규화(safe_sympify)가 거부해
    derive-and-verify 가드가 조용히 꺼진다(검토 2)."""
    derived = derive_selected_root("x**3 - 12*x**2 + 48*x - 59 = 0", "largest")
    assert derived == "4 - 5**(1/3)"
    assert derive_selected_root("x**3 - 6*x**2 + 12*x - 4 = 0", "unique") == "2 - 2**(2/3)"
    assert derive_selected_root("x**2 - 2 = 0", "largest") == "sqrt(2)"
    assert derive_selected_root("x*(x - 2)/(x - 2) = 2", "unique") is None  # 무연근만 — 유도 불가
