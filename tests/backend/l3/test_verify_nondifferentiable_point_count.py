"""`verify_nondifferentiable_point_count` — 미분가능하지 않은 점의 개수 개념형 검증(P3-65).

정답 개수 pass · 지름길 셈법(후보 수 · 절댓값 항 수 · 절댓값 안 차수)의 틀린 답 fail · 범위 밖
unverifiable 을 동결한다. 픽스처는 절마다 그 절이 없으면 통과해 버리는 입력을 하나씩 둔다
(매끄러운 절댓값 꼴 · 중근 · 상쇄 · 분수식 · 다항식 아닌 절댓값 인자).
"""

from __future__ import annotations

import pytest

from whymath_backend.l3.verify_answer import (
    verify_is_differentiable,
    verify_nondifferentiable_point_count,
)


def _state(expr: str, claimed: str) -> str:
    return verify_nondifferentiable_point_count(expr, claimed).state


class TestCountsOnlyCornersWhereOneSidedDerivativesDiffer:
    def test_two_simple_kinks(self) -> None:
        assert _state("Abs(x - 1) + Abs(x + 2)", "2") == "pass"
        assert _state("Abs(x - 1) + Abs(x + 2)", "1") == "fail"

    @pytest.mark.parametrize(
        "expr",
        ["(x - 1)*Abs(x - 1)", "Abs(x - 1)**3", "2*(x + 3)*Abs(x + 3) - Abs(x + 3)**3"],
    )
    def test_smooth_absolute_value_forms_are_not_counted(self, expr: str) -> None:
        """절댓값 안이 0이 되는 점이라도 좌·우미분계수가 같으면 세지 않는다(후보 수로 센 1은 fail)."""
        assert _state(expr, "0") == "pass"
        assert _state(expr, "1") == "fail"

    def test_double_root_inside_is_smooth(self) -> None:
        """|(x - 1)^2(x + 2)| — 중근 x = 1 은 매끄럽고 x = -2 만 꺾인다(후보 2 · 차수 3 은 fail)."""
        expr = "Abs((x - 1)**2*(x + 2))"
        assert _state(expr, "1") == "pass"
        assert _state(expr, "2") == "fail"
        assert _state(expr, "3") == "fail"

    def test_cancellation_between_terms(self) -> None:
        """|x^2 - 4| - (x + 2)|x - 2| — x = 2 의 꺾임이 상쇄되고 x = -2 만 남는다(절댓값 항 2개 ≠ 답)."""
        assert _state("Abs(x**2 - 4) - (x + 2)*Abs(x - 2)", "1") == "pass"
        assert _state("Abs(x**2 - 4) - (x + 2)*Abs(x - 2)", "2") == "fail"

    def test_full_cancellation_is_a_disguised_polynomial(self) -> None:
        expr = "Abs(x**2 - x - 2) + (x - 2)*Abs(x + 1) - (x + 1)*Abs(x - 2)"
        assert _state(expr, "0") == "pass"

    def test_polynomial_has_none(self) -> None:
        assert _state("x**3 - 2*x", "0") == "pass"
        assert _state("x**3 - 2*x", "1") == "fail"


class TestAgreesWithTheZeroOneVerifier:
    """개수가 0 ⟺ 실수 전체에서 미분가능(1) — 두 검증기가 같은 함수에서 같은 사실을 말한다."""

    @pytest.mark.parametrize(
        "expr",
        [
            "Abs(x - 2) + 3",
            "(x - 2)*Abs(x - 2) + x**2",
            "Abs(x - 1)**3 - 2*Abs(x - 1)",
            "Abs(x - 3)*(x**2 - 9)",
            "Abs(x + 1)*(x - 2)**2",
            "Abs(x**2 - 5*x + 6) - 3*(x - 2)*Abs(x - 3)",
        ],
    )
    def test_zero_count_iff_differentiable(self, expr: str) -> None:
        count_zero = _state(expr, "0") == "pass"
        differentiable = verify_is_differentiable(expr, "1").state == "pass"
        assert count_zero == differentiable, expr


class TestOutOfScopeIsUnverifiableNotAVerdict:
    """모른다 ≠ 아니다 — 후보 전제가 깨지는 식은 pass/fail 이 아니라 unverifiable 이다."""

    @pytest.mark.parametrize(
        ("expr", "claimed"),
        [
            ("Abs(x - 1)/(x - 2)", "1"),  # 분수식 — ℝ 전체 정의 꼴 아님
            ("Abs(sin(x))", "0"),  # 절댓값 인자가 다항식이 아님 — 후보가 무한하다
            ("Abs(x - y)", "1"),  # 변수 둘
            ("Abs(x) = 1", "1"),  # 등식
            ("Abs(x - 1)", "1.5"),  # 개수가 아님
            ("Abs(x - 1)", "-1"),  # 음수 개수
        ],
    )
    def test_unverifiable(self, expr: str, claimed: str) -> None:
        assert _state(expr, claimed) == "unverifiable", expr

    def test_two_conditions_are_not_a_single_function(self) -> None:
        verdict = verify_nondifferentiable_point_count(["Abs(x - 1)", "x > 0"], "1")
        assert verdict.state == "unverifiable"

    def test_non_polynomial_inside_is_refused_even_when_the_count_would_match(self) -> None:
        """|sin x| 는 꺾이는 점이 무한히 많다 — 어떤 주장도 판정하지 않는다(유한 후보 전제 밖)."""
        for claimed in ("0", "1", "2"):
            assert _state("Abs(sin(x))", claimed) == "unverifiable"
