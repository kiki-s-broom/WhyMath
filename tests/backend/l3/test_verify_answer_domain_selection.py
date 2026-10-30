"""P3-71 — `verify_root_selection` 의 '단일 등식 + 도메인 부등식' 리스트와 대입 단계 판정.

넓힌 입력(도메인 리스트)마다 주입(제약 위반 근·요구 밖 근·틀린 대입값)이 fail 인지, 모양 밖 입력이
종전처럼 unverifiable 인지(하위호환), 경계 근이 모호로 접히지 않는지를 본다.
"""

from __future__ import annotations

import ast

import pytest

from whymath_backend.l3 import verify_answer as verify_answer_module
from whymath_backend.l3.verify_answer import (
    certified_polynomial,
    certified_root_sets,
    condition_relation,
    match_root,
    split_equation_domain,
    verify_root_selection,
    verify_substituted_value,
)

POSITIVE_A = ["Derivative(x**3, x).doit().subs(x, a) = 108", "a > 0"]  # 근 ±6, 허용 6
MVT_C = [  # 근 -3, 5/3 — 구간 [0, 3] 안·끝점 제외
    "Derivative(2*x**3 + 4*x**2 + 6*x + 4, x).doit().subs(x, c) = ((112) - (4))/((3) - (0))",
    "c >= 0",
    "c <= 3",
    "c != 0",
    "c != 3",
]


class TestSplitEquationDomain:
    def test_single_equation_with_domain(self) -> None:
        assert split_equation_domain(POSITIVE_A) == (POSITIVE_A[0], ("a > 0",), "a")

    def test_single_equation_string_has_empty_domain(self) -> None:
        assert split_equation_domain("x**2 - 4 = 0") == ("x**2 - 4 = 0", (), "x")

    @pytest.mark.parametrize(
        "conditions",
        [
            ["x + y = 3", "x - y = 1"],  # 연립
            ["x**2 = 4", "x**2 = 9"],  # 등식 둘
            ["x**2 = 4", "y > 0"],  # 다른 변수의 제약
            ["x > 0", "x < 3"],  # 등식 없음
            ["x**2 = 4", "((("],  # 파싱 불가
            [],
        ],
    )
    def test_other_shapes_are_rejected(self, conditions: list[str]) -> None:
        assert split_equation_domain(conditions) is None

    def test_condition_relation(self) -> None:
        assert condition_relation("y = 2*x + 1") == ("==", frozenset({"x", "y"}))
        assert condition_relation("c != 3") == ("!=", frozenset({"c"}))
        assert condition_relation("(((") is None


class TestCertifiedDomainTruth:
    """도메인 판정 3상태 — 허용 목록 다항 등식의 정확 근에서 부등식을 대수적으로 가른다."""

    @pytest.mark.parametrize(
        ("domain", "expected"),
        [
            (["s > 3"], [5]),  # 엄격 경계 — 3 은 위반 확정(모호 아님)
            (["s >= 3"], [3, 5]),  # 등호 경계 — 만족 확정
            (["s != 3"], [5]),
            (["s > 3", "s < 4"], []),  # 하나라도 위반이면 제외
            ([], [3, 5]),
        ],
    )
    def test_boundaries_are_exact(self, domain: list[str], expected: list[int]) -> None:
        sets = certified_root_sets("12*s**2 - 96*s + 180 = 0", domain, "s")
        assert sets is not None
        assert sets[0] == [3, 5]
        assert sets[1] == expected

    @pytest.mark.parametrize("domain", [["s > t"], ["((("], ["s = 3"], ["sin(s) > 0"]])
    def test_uncertified_domain_is_undecidable(self, domain: list[str]) -> None:
        # 다른 기호·파싱 불가·등식·초월 함수 — 이 변수의 다항 제약이 아니면 근 집합을 내지 않는다.
        assert certified_root_sets("12*s**2 - 96*s + 180 = 0", domain, "s") is None


class TestRootSelectionWithDomain:
    def test_admissible_root_passes(self) -> None:
        assert verify_root_selection(POSITIVE_A, {"a": "6"}, "unique").state == "pass"
        assert verify_root_selection(MVT_C, {"c": "5/3"}, "unique").state == "pass"

    def test_injection_constraint_violating_root_fails(self) -> None:
        """종전엔 리스트라 unverifiable 이던 자리 — 제약을 어기는 근은 이제 fail 로 잡힌다."""
        verdict = verify_root_selection(POSITIVE_A, {"a": "-6"}, "unique")
        assert verdict.state == "fail"
        assert "도메인" in (verdict.reason or "")
        assert verify_root_selection(MVT_C, {"c": "-3"}, "unique").state == "fail"

    def test_selection_is_made_among_admissible_roots(self) -> None:
        # 근 -6·6 중 허용 근은 6 하나 — smallest 를 요구해도 허용 근 안에서 고른다.
        assert verify_root_selection(POSITIVE_A, {"a": "6"}, "smallest").state == "pass"
        assert verify_root_selection(POSITIVE_A, {"a": "-6"}, "smallest").state == "fail"

    def test_unique_fails_when_the_domain_leaves_two_roots(self) -> None:
        conditions = ["x**2 - 5*x + 6 = 0", "x > 0"]  # 근 2·3 둘 다 허용
        assert verify_root_selection(conditions, {"x": "3"}, "unique").state == "fail"
        assert verify_root_selection(conditions, {"x": "3"}, "largest").state == "pass"
        assert verify_root_selection(conditions, {"x": "2"}, "largest").state == "fail"

    def test_strict_boundary_root_is_excluded(self) -> None:
        conditions = ["12*s**2 - 96*s + 180 = 0", "s > 3"]  # 근 3·5 — 3 은 경계라 제외
        assert verify_root_selection(conditions, {"s": "5"}, "unique").state == "pass"
        assert verify_root_selection(conditions, {"s": "3"}, "unique").state == "fail"

    @pytest.mark.parametrize(
        "conditions",
        [
            ["x + y = 3", "x - y = 1"],
            ["x**2 = 4", "y > 0"],
            ["y = x**2", "x**2 - 4 = 0", "x > 0"],  # 다른 변수의 정의 등식이 섞임
        ],
    )
    def test_other_list_shapes_stay_unverifiable(self, conditions: list[str]) -> None:
        verdict = verify_root_selection(conditions, {"x": "2", "y": "1"}, "largest")
        assert verdict.state == "unverifiable"

    @pytest.mark.parametrize(
        ("conditions", "answer", "selection"),
        [
            (["sin(x) = 0", "x > 0", "x < 10"], "pi", "unique"),  # 실제 허용 근 π·2π·3π
            (["sin(x*pi/180) = 1/2", "x >= 0", "x < 720"], "150", "largest"),  # 실제 최대 510
            (["sin(x*pi/180) = 1/2", "x >= 0", "x < 720"], "30", "unique"),
        ],
    )
    def test_periodic_equation_is_not_judged_on_a_partial_root_set(
        self, conditions: list[str], answer: str, selection: str
    ) -> None:
        """PR #1703 상3: `sympy.solve` 의 부분 해를 근 전체로 읽으면 거짓 pass 가 난다."""
        verdict = verify_root_selection(conditions, {"x": answer}, selection)  # type: ignore[arg-type]
        assert verdict.state == "unverifiable"

    def test_undecidable_domain_on_some_root_is_unverifiable_not_admissible(self) -> None:
        """근 -1 에서 `log(x) >= 0` 은 복소라 판정 불가 — 그 근을 허용으로 세면 unique 가 fail 로 간다."""
        verdict = verify_root_selection(["x**2 - 1 = 0", "log(x) >= 0"], {"x": "1"}, "unique")
        assert verdict.state == "unverifiable"

    def test_cancelled_rational_equation_with_a_spurious_root_is_unverifiable(self) -> None:
        """약분하면 `x = 2` 지만 원문 분모가 x = 2 에서 0 — 무연근을 허용 근으로 세지 않는다."""
        verdict = verify_root_selection(["x*(x - 2)/(x - 2) = 2", "x > 0"], {"x": "2"}, "unique")
        assert verdict.state == "unverifiable"

    def test_undecidable_denominator_at_a_root_is_unverifiable(self) -> None:
        """`x/((x-2)/(x-2)) = 2` 는 약분하면 x = 2, 원문 분모는 x = 2 에서 0/0 — 판정 불가로 둔다."""
        verdict = verify_root_selection(["x/((x-2)/(x-2)) = 2", "x > 0"], {"x": "2"}, "unique")
        assert verdict.state == "unverifiable"

    def test_denominator_with_an_undecidable_value_at_a_root_is_unverifiable(self) -> None:
        """`x*sqrt(x - 3)/sqrt(x - 3) = 2` 는 약분하면 x = 2, 원문 분모는 x = 2 에서 허수 — 판정 불가."""
        verdict = verify_root_selection(
            ["x*sqrt(x - 3)/sqrt(x - 3) = 2", "x > 0"], {"x": "2"}, "unique"
        )
        assert verdict.state == "unverifiable"

    def test_rational_equation_is_not_certified_even_without_a_spurious_root(self) -> None:
        """허용 목록은 변수 분모를 받지 않는다 — 무연근이 없는 `x*(x - 2)/(x - 2) = 3` 도 판정하지
        않는다(보수 — 정당한 경우까지 막는 대가로 표기 우회 전부를 구조적으로 막는다)."""
        verdict = verify_root_selection(["x*(x - 2)/(x - 2) = 3", "x > 0"], {"x": "3"}, "unique")
        assert verdict.state == "unverifiable"

    def test_derivative_of_a_polynomial_is_certified(self) -> None:
        """대조: 코퍼스 조건 형식 `Derivative(…).doit().subs(x, a)` 는 허용 목록 안이다."""
        assert verify_root_selection(POSITIVE_A, {"a": "6"}, "unique").state == "pass"

    def test_no_real_root_hidden_by_a_tiny_imaginary_part(self) -> None:
        """`(x - 1)**2 + 1/10**20 = 0` 은 실근이 없다 — 정확 계산으로 센다(허수부 허용치로 접지 않는다)."""
        assert certified_root_sets("(x - 1)**2 + 1/10**20 = 0", [], "x") == ([], [])
        verdict = verify_root_selection(
            ["(x - 1)**2 + 1/10**20 = 0", "x > 0"], {"x": "1"}, "unique"
        )
        assert verdict.state == "unverifiable"

    def test_single_element_list_is_unchanged(self) -> None:
        assert verify_root_selection(["x**2 - 10*x + 24 = 0"], {"x": "6"}, "largest").state == (
            "pass"
        )
        assert verify_root_selection(["x > 0"], {"x": "3"}, "largest").state == "unverifiable"


class TestSubstitutedValue:
    def test_defining_equation_gives_the_claimed_value(self) -> None:
        definition = "y = 2*x**3 - 6*x**2 - 18*x + 58"
        assert verify_substituted_value(definition, {"x": "3"}, "y", "4").state == "pass"

    def test_injection_wrong_value_fails(self) -> None:
        definition = "y = 2*x**3 - 6*x**2 - 18*x + 58"
        verdict = verify_substituted_value(definition, {"x": "3"}, "y", "5")
        assert verdict.state == "fail"

    @pytest.mark.parametrize(
        ("definition", "given", "claimed"),
        [
            ("y**2 = x", {"x": "4"}, "2"),  # y = ±2 — 하나로 정해지지 않는다
            ("y = a*x", {"x": "2"}, "4"),  # 매개변수 a 가 남는다
            ("y > x", {"x": "2"}, "3"),  # 등식이 아니다
            ("tan(y) = x", {"x": "1"}, "pi/4"),  # 비다항 — solve 는 pi/4 하나만 주지만 해는 무한
            ("y = x", {"x": "2"}, "I"),  # 주장값이 실수가 아니다
        ],
    )
    def test_undetermined_cases_are_unverifiable(
        self, definition: str, given: dict[str, str], claimed: str
    ) -> None:
        assert verify_substituted_value(definition, given, "y", claimed).state == "unverifiable"

    def test_leftover_parameter_is_reported_as_such(self) -> None:
        """매개변수가 남은 대입은 '자유변수가 하나가 아님'으로 드러난다(다른 사유로 뭉개지 않는다)."""
        verdict = verify_substituted_value("y = a*x", {"x": "2"}, "y", "4")
        assert verdict.state == "unverifiable"
        assert "자유변수" in (verdict.reason or "")


class TestCertifiedPolynomialAllowlist:
    """허용 목록 판정 — 거부 노드마다 하나씩, 그리고 허용 꼴의 대조군."""

    @pytest.mark.parametrize(
        "text",
        [
            "exp(x) - 1",  # 함수
            "log(x)",
            "sin(x)",
            "sqrt(x)",
            "Abs(x)",
            "Piecewise((x, x > 0), (-x, True))",
            "x**-1",  # 음수 지수
            "x**(-2)",
            "(x - 2)**0",  # 0 지수
            "x**(1/2)",  # 분수 지수
            "x**n",  # 기호 지수
            "x**2.0",  # 실수 지수
            "2.5*x",  # 실수 리터럴
            "x/(x - 2)",  # 변수 분모
            "1/x",
            "Rational(1, 2)*x",  # 허용 목록 밖 호출
            "pi*x",  # SymPy 이름 기호
            "(x**2).expand()",  # 다른 메서드
            "(x*(x - 2)/(x - 2)).doit()",  # 래퍼 속 변수 분모
            "(x**2).subs(x**2, 3)",  # 대입 대상이 기호가 아님
            "x/0",  # 0 으로 나눔
            "x**999",  # 지수 상한 초과
            "x - 1" + "0" * 40,  # 정수 리터럴 상한 초과
            "Derivative(x**3, x, 2)",  # 미분 인자 개수
            "Derivative(x**3, x**2)",  # 미분 변수가 기호가 아님
            "x**2 - 4  # 주석",  # 공식 진입점(safe_sympify)이 거부하는 문자 — 구문 나무만으로 통과 금지
            "x" + " + 1" * 400,  # 공식 진입점의 길이 예산 초과
            "x + 0.5 - 0.5",  # 실수 리터럴 — 평가하면 지워져도 노드 단계에서 거부
        ],
    )
    def test_rejected_nodes(self, text: str) -> None:
        assert certified_polynomial(text, "x") is None

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("2*x**3 - 6*x**2 + 1", "2*x**3 - 6*x**2 + 1"),
            ("x/2 + 1/3", "x/2 + 1/3"),
            ("-(x - 1)**2", "-x**2 + 2*x - 1"),
            ("Derivative(x**3, x).doit()", "3*x**2"),
            ("Derivative(t**3, t).doit().subs(t, x)", "3*x**2"),
            ("((112) - (4))/((3) - (0)) + x", "x + 36"),
        ],
    )
    def test_accepted_forms(self, text: str, expected: str) -> None:
        poly = certified_polynomial(text, "x")
        assert poly is not None
        assert str(poly.as_expr()) == expected

    def test_other_symbols_are_not_a_polynomial_in_the_variable(self) -> None:
        assert certified_polynomial("x + a", "x") is None

    @pytest.mark.parametrize(
        "text",
        [
            "exp(x)",
            "x**-1",
            "(x - 2)**0",
            "x**(1/2)",
            "x**n",
            "x**2.0",
            "2.5*x",
            "x/(x - 2)",
            "x/0",
            "(x**2).expand()",
            "(x**2).subs(x**2, 3)",
            "Derivative(x**3, x**2)",
            "Derivative(x**3, 2)",
            "Derivative(x**3, x, 2)",
            "pi*x",
            "True*x",
            "x - 1" + "0" * 40,
        ],
    )
    def test_allowlist_builder_rejects_each_node_by_itself(self, text: str) -> None:
        """허용 목록 빌더 자체가 노드를 거부한다 — 앞단 `safe_sympify` 사전 검사나 뒷단 Poly
        도메인 검사가 우연히 같은 입력을 막아 주는 것에 기대지 않는다(두 검사는 방어 중복)."""
        tree = ast.parse(text, mode="eval")
        with pytest.raises(verify_answer_module._NotCertified):
            verify_answer_module._certified_build(tree.body)

    def test_sympy_names_are_not_variables(self) -> None:
        # `E` 는 SymPy 에서 자연상수다 — 구문 나무에서 기호로 세우면 원문의 뜻과 달라진다.
        assert certified_polynomial("E**2 - 4", "E") is None

    @pytest.mark.parametrize(
        ("condition", "domain"),
        [
            ("x > 0", []),  # 등식이 아니다
            ("x**2 - 4 = 0", ["0 < x < 3"]),  # 관계가 둘인 도메인
            # 근 √2 에서 잔차가 1e-44 수준 — 60자리 평가로도 부호를 확정하지 않는다(판정 불가)
            (
                "x**2 - 2 = 0",
                ["x > (14142135623730950488016887242*10**15 + 96980785696718)/10**43"],
            ),
        ],
    )
    def test_root_sets_refuse_undecidable_shapes(self, condition: str, domain: list[str]) -> None:
        assert certified_root_sets(condition, domain, "x") is None

    def test_match_requires_a_single_exact_root_within_tolerance(self) -> None:
        sets = certified_root_sets("(x - 1)*(x - 1 - 1/10**12) = 0", [], "x")
        assert sets is not None and len(sets[0]) == 2
        assert match_root("1", sets[0]) is None  # 허용치 안에 정확 근이 둘 — 어느 근인지 모른다

    def test_exact_root_sets_and_matching(self) -> None:
        roots, admissible = certified_root_sets("x**3 - 2*x = 0", ["x >= 0"], "x") or ([], [])
        assert len(roots) == 3 and len(admissible) == 2  # -√2, 0, √2 / 0, √2
        assert match_root("1.4142135623730951", roots) == 2
        assert match_root("2.00001", certified_root_sets("(x-2)**2*(x+1) = 0", [], "x")[0]) is None
        assert match_root("(((", roots) is None

    def test_exact_boundary_is_decided_algebraically(self) -> None:
        sets = certified_root_sets("x**2 - 2 = 0", ["x**2 > 2"], "x")
        assert sets is not None and sets[1] == []  # 경계(=)에서 엄격 부등식은 거짓 — 정확 0 판정
        sets = certified_root_sets("x**2 - 2 = 0", ["x**2 >= 2", "x > 0"], "x")
        assert sets is not None and len(sets[1]) == 1
