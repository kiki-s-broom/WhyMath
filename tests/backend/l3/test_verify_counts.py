"""개념형 검증 프리미티브 테스트 — 개수·판정·극한·미분·통계·확률(순수·SymPy·라이브 0).

정답 개수/판정 pass·오개념(판별식·임계점=극값·역함수·늘 수렴·극한=함숫값·연속→미분가능·일반항→0⇒
수렴·평균=중앙값·배반→독립·검사오류·유사=합동·내적=벡터·부등호 방향)의 틀린 답 fail·범위 밖
unverifiable을 동결한다.
"""

from __future__ import annotations

from whymath_backend.l3.verify_answer import (
    verify_conditional_equal,
    verify_congruent_by_ratio,
    verify_dot_product_scalar,
    verify_events_independent,
    verify_extremum_count,
    verify_geometric_convergence,
    verify_inequality_direction,
    verify_is_differentiable,
    verify_is_one_to_one,
    verify_limit_equals_value,
    verify_mean_equals_median,
    verify_real_root_count,
    verify_series_converges,
)


class TestRealRootCount:
    def test_no_real_root_pass(self) -> None:
        # 판별식<0 → 실근 0개.
        assert verify_real_root_count("x**2 + x + 1 = 0", "0").state == "pass"

    def test_misconception_two_fails(self) -> None:
        # 판별식 무시("늘 2근") 오개념 — 실근 0인데 2로 답 → fail.
        assert verify_real_root_count("x**2 + x + 1 = 0", "2").state == "fail"

    def test_double_root_is_one(self) -> None:
        # 중근 → 서로 다른 실근 1개.
        assert verify_real_root_count("x**2 - 4*x + 4 = 0", "1").state == "pass"
        assert verify_real_root_count("x**2 - 4*x + 4 = 0", "2").state == "fail"

    def test_two_distinct_roots(self) -> None:
        assert verify_real_root_count("x**2 - 5*x + 6 = 0", "2").state == "pass"

    def test_non_polynomial_unverifiable(self) -> None:
        assert verify_real_root_count("2**x = 8", "1").state == "unverifiable"

    def test_non_count_claim_unverifiable(self) -> None:
        # 개수가 아닌 주장(음수·분수)은 보수적 회피.
        assert verify_real_root_count("x**2 + 1 = 0", "sqrt(2)").state == "unverifiable"


class TestExtremumCount:
    def test_cubic_perfect_cube_zero_extrema(self) -> None:
        # f(x)=x³ → f'=3x²(중근)·부호 불변 → 극값 0개.
        assert verify_extremum_count("x**3", "0").state == "pass"

    def test_misconception_critical_as_extremum_fails(self) -> None:
        # 임계점=극값 오개념 — 극값 0인데 1(임계점 수)로 답 → fail.
        assert verify_extremum_count("x**3", "1").state == "fail"
        assert verify_extremum_count("(x - 2)**3 + 5", "1").state == "fail"

    def test_cubic_two_extrema(self) -> None:
        # f(x)=x³-3x → f'=3x²-3(서로 다른 두 근·부호 변화) → 극값 2개.
        assert verify_extremum_count("x**3 - 3*x", "2").state == "pass"
        assert verify_extremum_count("x**3 - 3*x", "1").state == "fail"

    def test_shifted_perfect_cube_pass(self) -> None:
        assert verify_extremum_count("(x - 3)**3 + 1", "0").state == "pass"

    def test_equation_form_unverifiable(self) -> None:
        # 함수 식이어야 함(등식/부등식은 회피).
        assert verify_extremum_count("x**3 = 0", "0").state == "unverifiable"


class TestIsOneToOne:
    def test_parabola_not_one_to_one_pass(self) -> None:
        # 이차함수 f'=2x+b 부호 변화 → 일대일 아님(0).
        assert verify_is_one_to_one("x**2", "0").state == "pass"
        assert verify_is_one_to_one("x**2 + 3*x + 2", "0").state == "pass"

    def test_misconception_invertible_fails(self) -> None:
        # "일대일 아니어도 역함수 있다" 오개념 — 0인데 1로 답 → fail.
        assert verify_is_one_to_one("x**2", "1").state == "fail"
        assert verify_is_one_to_one("x**2 + 3*x + 2", "1").state == "fail"

    def test_monotone_cubic_is_one_to_one(self) -> None:
        # f(x)=x³ → f'=3x²(부호 불변·단조) → 일대일(1).
        assert verify_is_one_to_one("x**3", "1").state == "pass"
        assert verify_is_one_to_one("x**3", "0").state == "fail"

    def test_linear_is_one_to_one(self) -> None:
        assert verify_is_one_to_one("2*x + 1", "1").state == "pass"

    def test_non_count_claim_unverifiable(self) -> None:
        # 판정값(0/1)이 아닌 주장은 보수적 회피.
        assert verify_is_one_to_one("x**2", "2").state == "unverifiable"

    def test_multivariate_unverifiable(self) -> None:
        assert verify_is_one_to_one("x**2 + y", "0").state == "unverifiable"


class TestGeometricConvergence:
    def test_ratio_gt_one_diverges_pass(self) -> None:
        # |r|>1 → 발산(0).
        assert verify_geometric_convergence("3/2", "0").state == "pass"
        assert verify_geometric_convergence("5", "0").state == "pass"

    def test_misconception_always_converges_fails(self) -> None:
        # "등비급수는 늘 수렴" 오개념 — 발산(0)인데 1로 답 → fail.
        assert verify_geometric_convergence("3/2", "1").state == "fail"

    def test_ratio_lt_one_converges(self) -> None:
        # |r|<1 → 수렴(1).
        assert verify_geometric_convergence("1/2", "1").state == "pass"
        assert verify_geometric_convergence("1/2", "0").state == "fail"

    def test_boundary_ratio_one_diverges(self) -> None:
        # 경계 |r|=1은 발산(0).
        assert verify_geometric_convergence("1", "0").state == "pass"

    def test_non_count_claim_unverifiable(self) -> None:
        assert verify_geometric_convergence("1/2", "3").state == "unverifiable"


class TestLimitEqualsValue:
    def test_removable_singularity_mismatch_pass(self) -> None:
        # 제거가능 특이점 x=1 — 함수값 미정의·극한 유한 → lim ≠ f(a)(0).
        assert verify_limit_equals_value("(x**2 - 3*x + 2)/(x - 1)", "0").state == "pass"

    def test_misconception_always_equal_fails(self) -> None:
        # "극한값=함수값 항상" 오개념 — 0인데 1로 답 → fail.
        assert verify_limit_equals_value("(x**2 - 3*x + 2)/(x - 1)", "1").state == "fail"

    def test_no_singularity_unverifiable(self) -> None:
        # 특이점 없는 함수는 오개념 표적 아님 → 보수적 회피.
        assert verify_limit_equals_value("x + 1", "1").state == "unverifiable"

    def test_non_count_claim_unverifiable(self) -> None:
        assert verify_limit_equals_value("(x**2 - 1)/(x - 1)", "2").state == "unverifiable"


class TestIsDifferentiable:
    def test_abs_corner_not_differentiable_pass(self) -> None:
        # |x-2|+3 → x=2 좌우 미분계수 상이 → 미분 불가(0).
        assert verify_is_differentiable("Abs(x - 2) + 3", "0").state == "pass"

    def test_misconception_continuity_implies_diff_fails(self) -> None:
        # "연속이면 미분가능" 오개념 — 0인데 1로 답 → fail.
        assert verify_is_differentiable("Abs(x - 2) + 3", "1").state == "fail"

    def test_polynomial_is_differentiable(self) -> None:
        # 다항식은 ℝ 전체에서 미분가능(1).
        assert verify_is_differentiable("x**2", "1").state == "pass"
        assert verify_is_differentiable("x**2", "0").state == "fail"

    def test_rational_unverifiable(self) -> None:
        # 유리식은 도메인 복잡 → 보수적 회피.
        assert verify_is_differentiable("1/x", "1").state == "unverifiable"

    def test_non_count_claim_unverifiable(self) -> None:
        assert verify_is_differentiable("Abs(x - 2)", "2").state == "unverifiable"


class TestSeriesConverges:
    def test_harmonic_diverges_pass(self) -> None:
        # 조화급수 Σ1/n — 항→0이나 발산(0).
        assert verify_series_converges("1/n", "0").state == "pass"
        assert verify_series_converges("1/sqrt(n)", "0").state == "pass"

    def test_misconception_term_zero_implies_conv_fails(self) -> None:
        # "일반항→0이면 수렴" 오개념 — 발산(0)인데 1로 답 → fail.
        assert verify_series_converges("1/n", "1").state == "fail"

    def test_p_series_converges(self) -> None:
        # Σ1/n² 수렴(1).
        assert verify_series_converges("1/n**2", "1").state == "pass"
        assert verify_series_converges("1/n**2", "0").state == "fail"

    def test_multivariate_unverifiable(self) -> None:
        assert verify_series_converges("1/(n*m)", "1").state == "unverifiable"

    def test_non_count_claim_unverifiable(self) -> None:
        assert verify_series_converges("1/n", "2").state == "unverifiable"


class TestMeanEqualsMedian:
    def test_skewed_not_equal_pass(self) -> None:
        # 이상치로 평균≠중앙값 → 0.
        assert verify_mean_equals_median("1,2,3,4,100", "0").state == "pass"

    def test_misconception_always_equal_fails(self) -> None:
        # "평균=중앙값 항상" 오개념 — 0인데 1로 답 → fail.
        assert verify_mean_equals_median("1,2,3,4,100", "1").state == "fail"

    def test_symmetric_equal(self) -> None:
        # 대칭 자료 평균=중앙값 → 1.
        assert verify_mean_equals_median("1,2,3", "1").state == "pass"
        assert verify_mean_equals_median("1,2,3", "0").state == "fail"

    def test_even_count_median(self) -> None:
        assert verify_mean_equals_median("1,2,3,10", "0").state == "pass"

    def test_non_numeric_unverifiable(self) -> None:
        assert verify_mean_equals_median("a,b,c", "1").state == "unverifiable"

    def test_non_count_claim_unverifiable(self) -> None:
        assert verify_mean_equals_median("1,2,3,4,100", "2").state == "unverifiable"


class TestEventsIndependent:
    def test_exclusive_not_independent_pass(self) -> None:
        # 배반(P>0)이라 P(A∩B)=0≠P(A)P(B) → 비독립(0).
        assert verify_events_independent("1/3,1/4,0", "0").state == "pass"

    def test_misconception_exclusive_implies_independent_fails(self) -> None:
        # "배반이면 독립" 오개념 — 0인데 1로 답 → fail.
        assert verify_events_independent("1/3,1/4,0", "1").state == "fail"

    def test_actually_independent(self) -> None:
        # P(A∩B)=P(A)P(B) → 독립(1).
        assert verify_events_independent("1/2,1/2,1/4", "1").state == "pass"
        assert verify_events_independent("1/2,1/2,1/4", "0").state == "fail"

    def test_out_of_range_unverifiable(self) -> None:
        assert verify_events_independent("2,1/4,0", "0").state == "unverifiable"

    def test_wrong_arity_unverifiable(self) -> None:
        assert verify_events_independent("1/3,1/4", "0").state == "unverifiable"

    def test_non_count_claim_unverifiable(self) -> None:
        assert verify_events_independent("1/3,1/4,0", "3").state == "unverifiable"


class TestConditionalEqual:
    def test_asymmetric_not_equal_pass(self) -> None:
        # P(A)≠P(B) → P(A|B)≠P(B|A)(0).
        assert verify_conditional_equal("1/2,1/10,9/10", "0").state == "pass"

    def test_misconception_prosecutor_fails(self) -> None:
        # "P(A|B)=P(B|A)" 오개념 — 0인데 1로 답 → fail.
        assert verify_conditional_equal("1/2,1/10,9/10", "1").state == "fail"

    def test_symmetric_when_equal_marginals(self) -> None:
        # P(A)=P(B) → 대칭(1).
        assert verify_conditional_equal("1/2,1/2,1/3", "1").state == "pass"

    def test_zero_marginal_unverifiable(self) -> None:
        assert verify_conditional_equal("0,1/2,1/3", "0").state == "unverifiable"

    def test_non_count_claim_unverifiable(self) -> None:
        assert verify_conditional_equal("1/2,1/10,9/10", "2").state == "unverifiable"


class TestCongruentByRatio:
    def test_ratio_not_one_not_congruent_pass(self) -> None:
        # 닮음비≠1 → 비합동(0).
        assert verify_congruent_by_ratio("3/2", "0").state == "pass"

    def test_misconception_similar_implies_congruent_fails(self) -> None:
        # "닮으면 합동" 오개념 — 0인데 1로 답 → fail.
        assert verify_congruent_by_ratio("3/2", "1").state == "fail"

    def test_ratio_one_congruent(self) -> None:
        assert verify_congruent_by_ratio("1", "1").state == "pass"
        assert verify_congruent_by_ratio("1", "0").state == "fail"

    def test_non_positive_unverifiable(self) -> None:
        assert verify_congruent_by_ratio("-2", "0").state == "unverifiable"

    def test_non_count_claim_unverifiable(self) -> None:
        assert verify_congruent_by_ratio("3/2", "2").state == "unverifiable"


class TestDotProductScalar:
    def test_dot_is_scalar_pass(self) -> None:
        # 내적은 스칼라 → 벡터 아님(0).
        assert verify_dot_product_scalar("1,2,3,4", "0").state == "pass"

    def test_misconception_dot_is_vector_fails(self) -> None:
        # "내적은 벡터" 오개념 — 0인데 1로 답 → fail.
        assert verify_dot_product_scalar("1,2,3,4", "1").state == "fail"

    def test_wrong_arity_unverifiable(self) -> None:
        assert verify_dot_product_scalar("1,2,3", "0").state == "unverifiable"

    def test_non_count_claim_unverifiable(self) -> None:
        assert verify_dot_product_scalar("1,2,3,4", "2").state == "unverifiable"


class TestInequalityDirection:
    def test_negative_coeff_flips_to_greater_pass(self) -> None:
        # 음수 계수로 나누면 방향 뒤집힘 → 해 x>c 꼴(1).
        assert verify_inequality_direction("-2*x < 6", "1").state == "pass"

    def test_misconception_no_flip_fails(self) -> None:
        # "부호 안 뒤집힌다" 오개념 — 해는 x>c(1)인데 0으로 답 → fail.
        assert verify_inequality_direction("-2*x < 6", "0").state == "fail"

    def test_positive_coeff_stays_less_pass(self) -> None:
        # 양수 계수 → 방향 그대로 x<c 꼴(0).
        assert verify_inequality_direction("2*x < 6", "0").state == "pass"

    def test_negative_coeff_geq_flips_to_less_pass(self) -> None:
        # -3x >= 9 → x <= -3 꼴(0).
        assert verify_inequality_direction("-3*x >= 9", "0").state == "pass"

    def test_equality_unverifiable(self) -> None:
        assert verify_inequality_direction("2*x = 6", "0").state == "unverifiable"

    def test_multivar_unverifiable(self) -> None:
        assert verify_inequality_direction("x + y < 3", "1").state == "unverifiable"

    def test_non_binary_claim_unverifiable(self) -> None:
        assert verify_inequality_direction("-2*x < 6", "2").state == "unverifiable"


class TestRealRootCountInInterval:
    """실근 개수 + 범위(P3-03 6회차 은행 감사 — '구간 [a, b]에서 평균값 정리를 만족시키는 c의 개수')."""

    _EQ = "3*x**2 - 2*x - 16 = 0"  # 근 -2, 8/3

    def test_bounds_restrict_the_count(self) -> None:
        assert verify_real_root_count([self._EQ, "x > 1", "x < 4"], "1").state == "pass"
        assert verify_real_root_count([self._EQ, "x > 1", "x < 4"], "2").state == "fail"
        assert verify_real_root_count([self._EQ, "x > -3", "x < 4"], "2").state == "pass"
        assert verify_real_root_count([self._EQ, "x >= 3"], "0").state == "pass"

    def test_single_condition_still_counts_every_real_root(self) -> None:
        # 종전 계약 그대로 — 범위가 없으면 실수 전체의 근(-2·8/3)을 센다.
        assert verify_real_root_count(self._EQ, "2").state == "pass"
        assert verify_real_root_count([self._EQ], "2").state == "pass"

    def test_root_on_a_strict_boundary_is_unverifiable(self) -> None:
        # 근 -2가 엄격 경계에 걸리면 안이냐 밖이냐 판정이 모호하다 — 통과·실패로 위장하지 않는다.
        assert verify_real_root_count([self._EQ, "x > -2"], "1").state == "unverifiable"
        # 경계를 포함하는 범위는 근을 센다.
        assert verify_real_root_count([self._EQ, "x >= -2", "x < 0"], "1").state == "pass"

    def test_malformed_bounds_are_unverifiable(self) -> None:
        # 둘째 등식·다른 변수·비선형 범위는 범위 계약 밖이다(보수적 회피).
        assert verify_real_root_count([self._EQ, "x = 1"], "1").state == "unverifiable"
        assert verify_real_root_count([self._EQ, "y > 1"], "1").state == "unverifiable"
        assert verify_real_root_count([self._EQ, "x**2 > 1"], "1").state == "unverifiable"
        assert verify_real_root_count([], "1").state == "unverifiable"
