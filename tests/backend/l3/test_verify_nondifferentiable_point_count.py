"""`verify_nondifferentiable_point_count` — 미분가능하지 않은 점의 개수 개념형 검증(P3-65).

정답 개수 pass · 지름길 셈법(후보 수 · 절댓값 항 수 · 절댓값 안 차수)의 틀린 답 fail · 범위 밖
unverifiable 을 동결한다. 픽스처는 절마다 그 절이 없으면 통과해 버리는 입력을 하나씩 둔다
(매끄러운 절댓값 꼴 · 중근 · 상쇄 · 분수식 · 다항식 아닌 절댓값 인자).
"""

from __future__ import annotations

import pytest
import sympy

from whymath_backend.l3 import verify_answer as va
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


# ──────────────────────────────────────────────────────────────────────────
# P3-65 독립 리뷰 P1-1 — 무리수 실근(세 실근 기약 삼차식)의 후보를 놓치던 결함의 회귀 동결
# ──────────────────────────────────────────────────────────────────────────
#: `sympy.solve` 가 허수 섞인 근호식(`is_real` None)으로 돌려주는 세 실근 — 종전 `if r.is_real` 필터가
#: 셋 다 버려 후보 0개 → '0'(미분불가 점 없음)·'1'(미분가능)이 pass 했다.
_THREE_IRRATIONAL_KINKS = ("Abs(x**3 - 3*x + 1)", "Abs(x**3 - 4*x + 1)", "x*Abs(x**3 - 3*x + 1)")


class TestIrrationalRealRootsAreCandidates:
    @pytest.mark.parametrize("expr", _THREE_IRRATIONAL_KINKS)
    def test_three_kinks_are_counted(self, expr: str) -> None:
        assert _state(expr, "0") == "fail"
        assert _state(expr, "3") == "pass"

    @pytest.mark.parametrize("expr", _THREE_IRRATIONAL_KINKS)
    def test_zero_one_verifier_never_passes_differentiable(self, expr: str) -> None:
        """`verify_is_differentiable` 도 같은 결함이 있었다 — '1'(미분가능)이 pass 하면 안 된다.

        그 검증기는 후보에서 차분몫 극한을 쓰는데 `CRootOf` 에서 극한이 계산되지 않으므로 판정 불가로
        접는다(거짓 pass 가 아니면 된다 — 판정 범위 확장은 이 태스크 밖).
        """
        assert verify_is_differentiable(expr, "1").state != "pass"

    @pytest.mark.parametrize(
        ("expr", "count"),
        [
            ("Abs(x**5 - x - 1)", 1),  # 실근 하나(CRootOf) — 극한으로는 계산 불가였던 실제 사례
            ("Abs(x**5 - 5*x + 1)", 3),  # 실근 셋(CRootOf)
            ("Abs(x**3 - 2*x - 1)", 3),  # 유리근 + 근호식 근
            ("Abs(x**2 - 2)*(x**2 - 2)", 0),  # 무리근이지만 매끄러운 꼴
            ("Abs(x**3 - 3*x + 1)**3", 0),  # 무리근 · 세제곱 — 매끄럽다
        ],
    )
    def test_exact_algebra_decides_irrational_corners(self, expr: str, count: int) -> None:
        assert _state(expr, str(count)) == "pass"
        assert _state(expr, str(count + 1)) == "fail"


class TestDecimalCoefficientsAreUnverifiable:
    """P3-65 재리뷰 P1 — 소수 계수는 정확 대수의 전제(나머지가 정확히 0)를 깨 거짓 pass를 만들었다.

    `|x - 0.1|^3`은 매끄러운데(참값 0) 반올림 잔차로 '1'이 pass했고, `|x^2 - 2.0000000000000001|`은
    꺾인 점이 2개인데 '0'이 pass했다. 어느 주장도 pass하지 않아야 하며, 판정 불가가 정직한 답이다.
    """

    @pytest.mark.parametrize(
        "expr",
        [
            "Abs(x - 0.1)**3",
            "Abs(x - 0.2)**3",
            "Abs(x - 3.7)**3",
            "Abs(x**2 - 2.0000000000000001)",
            "(x - 0.1)*Abs(x - 0.1)",
        ],
    )
    @pytest.mark.parametrize("claimed", ["0", "1", "2"])
    def test_decimal_coefficients_never_pass(self, expr: str, claimed: str) -> None:
        assert _state(expr, claimed) == "unverifiable", (expr, claimed)

    def test_rational_twin_is_still_decided(self) -> None:
        # 대조군 — 같은 함수를 유리수 계수로 쓰면 정확 판정이 그대로 돈다(가드가 과잉 거부가 아님).
        assert _state("Abs(x - 1/10)**3", "0") == "pass"
        assert _state("Abs(x - 1/10)**3", "1") == "fail"
        assert _state("Abs(x**2 - 2)", "2") == "pass"


class TestIrrationalCoefficientsAreUnverifiable:
    """P3-65 3차 리뷰 P1 — 무리수 계수는 Q 위 기약이라는 전제를 깨 켤레 근의 꺾임을 옮겨 셌다.

    `|x²−2|(x−√2)`는 √2에서 매끄럽고 −√2에서만 꺾이는데(참값 1) '2'가 pass했고,
    `|x³−2|(x−∛2)`는 매끄러운데(참값 0) '1'이 pass했다. 어느 주장도 pass하지 않아야 한다.
    """

    @pytest.mark.parametrize(
        "expr",
        [
            "Abs(x**2 - 2)*(x - sqrt(2))",
            "Abs(x**2 - 2)*(x + sqrt(2))",
            "Abs(x**2 - 3)*(x - sqrt(3)) + x**2",
            "(x - sqrt(2))*Abs(x**2 - 2) + Abs(x)",
            "Abs(x**3 - 2)*(x - 2**(1/3))",
            "Abs(x - sqrt(2))",
        ],
    )
    @pytest.mark.parametrize("claimed", ["0", "1", "2", "3"])
    def test_irrational_coefficients_never_pass(self, expr: str, claimed: str) -> None:
        assert _state(expr, claimed) == "unverifiable", (expr, claimed)

    @pytest.mark.parametrize(
        "expr",
        ["Abs(sin(x)) - sin(x)", "Abs(sin(x)) - sin(x) + x**2", "Abs(x**2 + sin(x)) - sin(x)"],
    )
    @pytest.mark.parametrize("claimed", ["0", "1", "2"])
    def test_non_polynomial_inner_cancelling_outside_is_unverifiable_not_an_exception(
        self, expr: str, claimed: str
    ) -> None:
        # 4차 리뷰 P2 — 벗긴 식은 상쇄로 다항식이지만 절댓값 인자는 아니다. 예외가 새면 안 된다.
        assert _state(expr, claimed) == "unverifiable", (expr, claimed)

    def test_rational_coefficients_with_irrational_corners_are_still_decided(self) -> None:
        # 대조군 — 계수는 유리수이고 꺾인 점만 무리수인 식은 정확 판정 그대로다(과잉 거부가 아님).
        assert _state("Abs(x**2 - 2)", "2") == "pass"
        assert _state("Abs(x**3 - 3*x + 1)", "3") == "pass"
        assert _state("Abs(x**3 - 3*x + 1)", "0") == "fail"


class TestUnverifiableBranches:
    """판정 불가 가지마다 그 가지를 밟는 입력 — 가지를 지우면 pass/fail·예외로 바뀐다(뮤테이션 동결)."""

    def test_non_polynomial_after_stripping(self) -> None:
        assert _state("Abs(x - 1) + sin(x)", "1") == "unverifiable"

    def test_zero_one_verifier_refuses_non_polynomial_inner(self) -> None:
        """후보를 `real_roots` 로 구하므로 인자가 다항식이 아니면 후보를 셀 수 없다."""
        assert verify_is_differentiable("Abs(sin(x))", "0").state == "unverifiable"
        assert verify_is_differentiable("Abs(sin(x))", "1").state == "unverifiable"

    @pytest.mark.parametrize("claimed", ["1+", "2개", "x"])
    def test_unparseable_claims_are_not_counts(self, claimed: str) -> None:
        """안전 파서가 거부하는 주장 — 예외를 올리지 않고 판정 불가로 접는다."""
        assert _state("Abs(x - 1)", claimed) == "unverifiable"

    def test_real_root_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_a: object, **_k: object) -> list[sympy.Expr]:
            raise NotImplementedError("실근 계산 불가 주입")

        monkeypatch.setattr(sympy, "real_roots", boom)
        assert _state("Abs(x - 1)", "1") == "unverifiable"
        assert verify_is_differentiable("Abs(x - 1)", "0").state == "unverifiable"

    def test_root_reality_not_established(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sympy, "real_roots", lambda *_a, **_k: [sympy.Symbol("r")])
        assert _state("Abs(x - 1)", "1") == "unverifiable"
        assert verify_is_differentiable("Abs(x - 1)", "0").state == "unverifiable"

    def test_minimal_polynomial_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_a: object, **_k: object) -> sympy.Expr:
            raise NotImplementedError("최소다항식 불가 주입")

        monkeypatch.setattr(sympy, "minimal_polynomial", boom)
        assert _state("Abs(x - 1)", "1") == "unverifiable"

    def test_reality_check_is_its_own_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """실수 여부가 None 인 근(`solve` 의 근호식)이 와도 부호 판독이 통과해 버리는 상황을 만든다 —
        그때 막는 것은 `is_real is not True` 검사 하나다(다른 가지가 대신 막지 않게 고립)."""
        radicals = sympy.solve(sympy.Symbol("x") ** 3 - 3 * sympy.Symbol("x") + 1)
        assert all(r.is_real is None for r in radicals)  # 전제 — 픽스처가 그 절을 밟는다
        monkeypatch.setattr(sympy, "real_roots", lambda *_a, **_k: radicals)
        monkeypatch.setattr(va, "_nonzero_sign", lambda _v: 1)
        assert _state("Abs(x**3 - 3*x + 1)", "3") == "unverifiable"
        assert _state("Abs(x**3 - 3*x + 1)", "0") == "unverifiable"

    def test_sign_not_readable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(va, "_nonzero_sign", lambda _v: None)
        assert _state("Abs(x - 1)", "1") == "unverifiable"

    @pytest.mark.parametrize(("unreadable_call", "label"), [(0, "기울기"), (1, "인자")])
    def test_each_sign_gate_alone(
        self, monkeypatch: pytest.MonkeyPatch, unreadable_call: int, label: str
    ) -> None:
        """부호 판독 두 곳(최소다항식 기울기 · 인자의 나머지 몫)을 하나씩만 실패시킨다 — 한 가지가
        지워지면 다른 가지가 대신 막지 못하고 None 이 산술로 흘러간다."""
        calls: list[int] = []

        def reader(_value: sympy.Expr) -> int | None:
            calls.append(1)
            return None if len(calls) - 1 == unreadable_call else 1

        monkeypatch.setattr(va, "_nonzero_sign", reader)
        verdict = verify_nondifferentiable_point_count("Abs(x - 1)", "1")
        assert verdict.state == "unverifiable", label
        assert verdict.reason is not None and label in verdict.reason

    def test_sign_reader_refuses_zero_and_complex(self) -> None:
        assert va._nonzero_sign(sympy.Integer(0)) is None
        assert va._nonzero_sign(sympy.I) is None
        assert va._nonzero_sign(sympy.sqrt(2) - 1) == 1
        assert va._nonzero_sign(1 - sympy.sqrt(3)) == -1
