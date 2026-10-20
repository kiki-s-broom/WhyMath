"""P3-71 — `verify_root_selection` 의 '단일 등식 + 도메인 부등식' 리스트와 대입 단계 판정.

넓힌 입력(도메인 리스트)마다 주입(제약 위반 근·요구 밖 근·틀린 대입값)이 fail 인지, 모양 밖 입력이
종전처럼 unverifiable 인지(하위호환), 경계 근이 모호로 접히지 않는지를 본다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l3.verify_answer import (
    condition_relation,
    satisfies_domain,
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


class TestSatisfiesDomain:
    @pytest.mark.parametrize(
        ("domain", "value", "expected"),
        [
            (["s > 3"], "3", False),  # 엄격 경계 — 위반 확정(모호 아님)
            (["s >= 3"], "3", True),  # 등호 경계 — 만족 확정
            (["s != 3"], "3", False),
            (["s > 3"], "5", True),
            (["s > 3", "s < 4"], "5", False),  # 하나라도 위반이면 False
            (["s > 3"], "(((", None),  # 값 파싱 불가 — 판정 불가
            (["s > t"], "5", None),  # 대입 뒤 자유변수 — 이 변수의 제약이 아니다
            ([], "5", True),
        ],
    )
    def test_three_states(self, domain: list[str], value: str, expected: bool | None) -> None:
        assert satisfies_domain(domain, "s", value) is expected


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
