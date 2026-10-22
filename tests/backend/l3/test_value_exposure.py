"""값 노출 훑기 `scan_value_exposure` — 힌트 게이트(S4-11 B·④)·P3-10 판정기의 공용 판정 (P3-77).

이 함수 하나가 "본문에 계산하면 목표 값이 되는 식이 있는가"를 정한다. 그래서 세 방향을 모두 잰다:
① 노출 주입 → exposed(RED 신호) ② 값이 다른 대조군 → clean ③ 판정 불가 → undecidable(clean으로
접지 않는다). 그리고 코퍼스 실측에서 드러난 오탐(문자 섞인 식의 *일부*를 잘라 정답과 같다고 보는
것)을 픽스처로 둔다. 2026-10-22 실측(승인·미승인 3,735문항의 검수 L3 5,377건): 옛 판정기 규칙은
2,155건을 거부했고 그중 22건이 그런 오탐(문자 섞인 식의 일부)이었다 — 나머지 2,133건은 진짜 누설.

PR #1721 리뷰(P2-1·P2-2) 회귀도 여기서 동결한다: 함수로 감싼 닫힌 식(`Abs`·`log`·삼각 — 승인
76문항 102건)과 값 진술(`1 = y` — 승인 9문항)이 글자 규칙을 빠져나갔다.
"""

from __future__ import annotations

from typing import Any

import pytest

from whymath_backend.l3 import verify_solution
from whymath_backend.l3.verify_solution import arithmetic_fragments, scan_value_exposure
from whymath_backend.schema.verification_capabilities import ValueExposure, ValueExposureScan

# P3-10 실측 `aq-h-06-04-l3`의 L3 본문 한 줄(정답 4).
_MVT_LINE = (
    "이것을 한 번 바꾸면 2번째 단계의 식이 돼: (-3) + (4)*((2) - (0)) + (-3) + (1)*((2) - (0)) = y"
)


def test_measured_leak_is_exposed() -> None:
    scan = scan_value_exposure(_MVT_LINE, "4")
    assert scan.outcome is ValueExposure.exposed
    assert scan.fragment == "(-3) + (4)*((2) - (0)) + (-3) + (1)*((2) - (0))"
    assert scan.candidates == 1 and scan.undecided == 0


def test_result_satisfies_the_core_contract() -> None:
    """어댑터 결과가 Core가 읽는 구조적 계약(`ValueExposureScan`)을 만족한다(변환 객체 없음)."""
    assert isinstance(scan_value_exposure(_MVT_LINE, "4"), ValueExposureScan)


def test_different_value_is_clean() -> None:
    """대조군 — 같은 식이라도 목표가 다르면(4 ≠ 5) clean. 과잉 거부가 아니다."""
    scan = scan_value_exposure(_MVT_LINE, "5")
    assert scan.outcome is ValueExposure.clean and scan.candidates == 1


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("참고: 2 + 5", "7"),  # 1자 정답 — 글자 대조가 유보하는 구간
        ("참고: 1/2 + 0", "0.5"),  # 표기가 달라도 값이 같다(정본 채점기 위임)
        ("참고: 2^3", "8"),  # 거듭제곱 표기
        ("참고: 3 × 4", "12"),  # 곱셈 기호 정규화
        ("참고: 1 + 1", "x = 2, x = 3"),  # 여러 값 중 하나만 드러내도 노출
        ("참고: 2 + 2", "y = 4"),  # 목표가 관계식(최종 단계)이어도 값으로 비교
        ("참고: 1 + 1", "\\frac{4}{2}"),  # LaTeX 목표는 단일 권위로 평문화
    ],
)
def test_value_equal_expressions_are_exposed(text: str, target: str) -> None:
    assert scan_value_exposure(text, target).outcome is ValueExposure.exposed


def test_expression_inside_a_symbolic_expression_is_not_a_candidate() -> None:
    """`Derivative(x - 1 + 1, x)` 속 `- 1 + 1`(= 0)은 독립 식이 아니다 — 변 *전체*만 대상이다."""
    text = "첫 단계에서 적는 식은 다음과 같아: (Derivative(x - 1 + 1, x) - 3).doit()"
    assert arithmetic_fragments(text) == []
    assert scan_value_exposure(text, "0").outcome is ValueExposure.clean


def test_relation_side_and_value_statement_are_candidates() -> None:
    """`3*(2) + 1 = y`의 좌변은 계산만 남은 식, `x = 7`의 7은 값 진술(변수 하나 = 닫힌 값)이다."""
    assert arithmetic_fragments("y = 3*(2) + 1, x = 7") == ["3*(2) + 1", "7"]


def test_bare_number_in_prose_is_not_a_candidate() -> None:
    """변수 옆 `=`이 없는 수 하나(본문의 '4단계')는 값 진술이 아니다 — 과잉 거부 방지."""
    assert arithmetic_fragments("풀이는 모두 4단계로 이어져. 지금은 2번째 단계야.") == []


@pytest.mark.parametrize(
    ("text", "target"),
    [
        # P2-2 — 정답 그 자체를 좌우 바꿔 보여 준다(문항 1fe0ab77 3단계 L3)
        ("이것을 한 번 바꾸면 3번째 단계의 식이 돼: 1 = y", "1"),
        ("식: y = 0", "0"),
        ("식: (-12) = a", "-12"),
        # P2-1 — 함수로 감싼 닫힌 식(문항 c019e458 3단계 L3 · log · 삼각)
        ("이것을 한 번 바꾸면 3번째 단계의 식이 돼: Abs((6*(5)**2 - 8*(5) - 4)) = y", "106"),
        ("첫 단계에서 적는 식은 다음과 같아: log(64, 2)", "6"),
        ("첫 단계에서 적는 식은 다음과 같아: sin(210*pi/180)", "-1/2"),
        ("첫 단계에서 적는 식은 다음과 같아: tan(30*pi/180)", "sqrt(3)/3"),
        ("첫 단계에서 적는 식은 다음과 같아: sqrt((9 - 6)**2 + (4 - 0)**2)", "5"),
        ("첫 단계에서 적는 식은 다음과 같아: factorial(6)/factorial(5)", "6"),
    ],
)
def test_review_1721_bypasses_are_exposed(text: str, target: str) -> None:
    assert scan_value_exposure(text, target).outcome is ValueExposure.exposed


@pytest.mark.parametrize(
    "text",
    [
        # 남은 일이 미분(그 단원의 인지 행동)인 설정 식 — 안전 파서는 `.doit()`을 실행해 수를
        # 만들지만, 쓰인 그대로는 변수 x를 쓴다 → 닫힌 값이 아니다(앞 단계 대체 후보가 이것이다).
        "첫 단계에서 적는 식은 다음과 같아: Derivative(x**3, x).doit().subs(x, -2) = y",
        "첫 단계에서 적는 식은 다음과 같아: "
        "((-3) + Derivative(4*x - 3, x)*((2) - (0)) + (-3) + Derivative(x - 3, x)*((2) - (0)))"
        ".doit() = y",
        # 대입이 남은 식도 같다 — 학생이 대입을 해야 값이 나온다
        "이것을 한 번 바꾸면 2번째 단계의 식이 돼: (3*x**2).subs(x, -2) = y",
        # 변수가 둘 이상 남은 등식은 값 진술이 아니다
        "식: 3*b**2 - 12*b = 0",
    ],
)
def test_expressions_that_still_name_a_variable_are_not_closed(text: str) -> None:
    assert scan_value_exposure(text, "12").outcome is ValueExposure.clean
    assert scan_value_exposure(text, "0").outcome is ValueExposure.clean


def test_truncated_run_is_not_a_candidate_and_not_undecidable() -> None:
    """괄호 짝이 안 맞는 잘린 조각은 식이 아니다 — 판정 불가로도 세지 않는다(대상 0)."""
    scan = scan_value_exposure("앞에서 ((2) + (3) 까지 봤어", "5")
    assert scan.outcome is ValueExposure.clean and scan.candidates == 0


@pytest.mark.parametrize("target", ["{1, 6}", "3개", "(1, 4)"])
def test_unreadable_target_is_undecidable_not_clean(target: str) -> None:
    """목표 값을 읽지 못하면 판정 불가 — clean으로 접지 않는다(모른다 ≠ 아니다)."""
    scan = scan_value_exposure("참고: 2 + 2", target)
    assert scan.outcome is ValueExposure.undecidable and scan.undecided == 1


def test_empty_target_with_candidates_is_undecidable() -> None:
    scan = scan_value_exposure("참고: 2 + 2", "  ")
    assert scan.outcome is ValueExposure.undecidable


def test_no_candidates_is_clean_without_reading_the_target() -> None:
    """볼 식이 없으면 목표를 읽을 필요가 없다 — 읽을 수 없는 목표여도 clean(candidates=0)."""
    scan = scan_value_exposure("풀이는 모두 4단계로 이어져. 지금은 2번째 단계야.", "{1, 6}")
    assert scan.outcome is ValueExposure.clean and scan.candidates == 0


def test_programming_errors_are_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """식 해석기 호출 계약이 깨지면(TypeError) 삼키지 않는다 — 삼키면 무관용 축이 통과로 바뀐다."""

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise TypeError("unexpected keyword argument")

    monkeypatch.setattr(verify_solution, "safe_sympify", broken)
    with pytest.raises(TypeError):
        scan_value_exposure("참고: 2 + 2", "4")


# ── PR #1721 재리뷰 P3 — 이름 종류·읽지 못한 이름·상수 이름 진술 ─────────────────
@pytest.mark.parametrize(
    "text",
    [
        "식: Rational(8, 2)",  # 허용 목록 밖 이름 — 종전엔 '변수'로 오판해 clean
        "식: Integer(2)+Integer(2)",
        "식: S(8)/2",
        "식: N(8/2)",
        "식: (8/2).evalf()",  # 허용 목록 밖 속성
    ],
)
def test_unreadable_closed_expression_is_undecidable_not_clean(text: str) -> None:
    """안전 파서가 읽기를 거절한 닫힌 식은 판정 불가 — 게이트가 거부한다(clean으로 접지 않는다)."""
    assert scan_value_exposure(text, "4").outcome is ValueExposure.undecidable


def test_number_only_doit_is_a_closed_value() -> None:
    """`.doit()`은 속성이지 변수가 아니다 — 수만 있는 `(2+2).doit()`은 계산만 남은 식이다."""
    assert scan_value_exposure("식: (2+2).doit()", "4").outcome is ValueExposure.exposed


@pytest.mark.parametrize(
    ("text", "target", "expected"),
    [
        # 한 글자 이름은 SymPy 상수(E·I)여도 학교 수학에서는 사용자 변수다 — 값 진술로 본다
        ("식: E = 4", "4", ValueExposure.exposed),
        ("식: I = 4", "4", ValueExposure.exposed),
        # 여러 글자 상수(pi)는 변수가 아니다 — `pi = 4`는 값 진술이 아니다(N5 반례)
        ("식: pi = 4", "4", ValueExposure.clean),
        # 읽지 못한 이름(gamma)은 변수 쪽으로 본다 — 값 진술이다(N8 반례)
        ("식: gamma = 4", "4", ValueExposure.exposed),
        # 수 없는 닫힌 값도 값을 진술한다(N7 — 수 토큰 가드를 없앤 이유)
        ("식: x = pi", "pi", ValueExposure.exposed),
        ("식: x = pi", "4", ValueExposure.clean),
    ],
)
def test_value_statement_name_rules(text: str, target: str, expected: ValueExposure) -> None:
    assert scan_value_exposure(text, target).outcome is expected


@pytest.mark.parametrize(
    "text",
    [
        # 묶인 변수가 있는 적분·합은 남은 일이 적분·합 계산(그 단원의 인지 행동)이다 — 닫힌 식이
        # 아니다(Derivative와 같은 판정 · 판정문 §2.0). Sum은 안전 파서 허용 목록 밖이기도 하다.
        "식: Integral(2, (x, 0, 2))",
        "식: Sum(k, (k, 1, 4))",
    ],
)
def test_bound_variable_operators_are_not_closed(text: str) -> None:
    assert scan_value_exposure(text, "4").outcome is ValueExposure.clean
