"""발문 독립 재유도(P3-63) 테스트 — 정상 입력에서 초록인 것은 보호의 증거가 아니다.

중심은 ①문장 틀마다 **손으로 유도한 정답**(엔진 출력이 아니다)과 재유도 값이 같은 대조군 ②발문의
수식을 변조하면 재유도 값이 따라 움직여 정답과 어긋나는 주입(RED) ③세 상태(확정·값 미정·미적용)가
서로 위장하지 않는 것 ④실 코퍼스 전수에서 단원마다 변조가 실제로 검출되는 것이다.
"""

from __future__ import annotations

import re

import pytest

from whymath_backend.harness import question_rederive as qr
from whymath_backend.harness import solution_qa as qa

# (이름, 발문, 손으로 유도한 정답)
CONTROLS: list[tuple[str, str, str]] = [
    (
        "tangent_slope_pick",
        "함수 f(x) = x^3 - 18x^2 + 90x 의 그래프 위에서 접선의 기울기가 -6인 두 "
        "점 중 x좌표가 작은 점의 x좌표를 구하시오.",
        "4",  # 3x^2-36x+96=0 → x=4,8
    ),
    (
        "local_extremum_x(min)",
        "삼차함수 f(x) = x^3 - 18x^2 + 96x 가 극솟값을 가질 때, 그 x의 값을 구하시오.",
        "8",  # 3x^2-36x+96=3(x-4)(x-8), 극소는 큰 근
    ),
    (
        "local_extremum_x(max, 극댓값 표기)",
        "삼차함수 f(x) = x^3 - 3x^2 - 24x 가 극댓값을 가질 때, 그 x의 값을 구하시오.",
        "-2",  # 3(x-4)(x+2), 극대는 작은 근. '극댓'은 '극대'와 접두가 다르다(회귀 방지)
    ),
    (
        "local_extremum_value",
        "함수 f(x) = x^3 - 6x^2 - 63x 의 극댓값을 구하시오.",
        "108",  # f'=3(x-7)(x+3) → x=-3: -27-54+189
    ),
    (
        "extremum_count",
        "삼차함수 f(x) = (x - 1)^3 의 극값의 개수를 구하시오.",
        "0",  # f'=3(x-1)^2 부호 불변
    ),
    (
        "differentiable_flag",
        "함수 f(x) = |x - 1| 이 실수 전체에서 미분가능하면 1, 아니면 0을 쓰시오.",
        "0",
    ),
    (
        "derivative_at_point(chain)",
        "함수 f(x) = (4x + 3)^3 의 x = 1 에서의 미분계수 f'(1) 의 값을 구하시오.",
        "588",  # 3*4*(7)^2
    ),
    (
        "product_derivative_at_point",
        "두 함수 f(x) = x^1, g(x) = x^2 에 대하여 함수 f(x)g(x) 의 x = 6 에서의 "
        "미분계수를 구하시오.",
        "108",  # (x^3)'=3x^2
    ),
    (
        "derivative_at_point",
        "함수 f(x) = x^3에 대하여 f'(-2)의 값을 구하시오.",
        "12",
    ),
    (
        "monotone_integer(floor)",
        "함수 f(x) = 4x^3 + 12x^2 + 9x + 4가 감소하는 x의 값의 범위에 속하는 정수는 "
        "하나뿐이다. 그 정수를 구하시오.",
        "-1",  # f'=3(2x+1)(2x+3) <0 on (-3/2,-1/2) — int() 절단이면 0 이 나온다
    ),
    (
        "motion_at_time",
        "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = -t^3 + 3t^2 + 4t "
        "+ 2일 때, t = 3에서의 점 P의 속도를 구하시오.",
        "-5",  # -3t^2+6t+4 at 3 = -27+18+4
    ),
    (
        "real_root_count",
        "함수 f(x) = x^3 - 12x에 대하여 방정식 f(x) = -18의 서로 다른 실근의 개수를 구하시오.",
        "1",  # 극솟값 f(2)=-16 > -18
    ),
    (
        "extremum_parameter",
        "함수 f(x) = 2x^3 + ax^2 - 72x + 6이 x = -3에서 극값을 가질 때, f(x)의 "
        "극솟값을 구하시오. (단, a는 상수이다.)",
        "-202",  # f'(-3)=0 → a=-3, 극소 x=4: 128-48-288+6
    ),
    (
        "mean_value_c",
        "함수 f(x) = 2x^3 - x^2 - 3에 대하여 닫힌구간 [0, 4]에서 평균값 정리를 "
        "만족시키는 c의 값은?",
        "7/3",  # 평균기울기 28, 6x^2-2x=28 → x=7/3
    ),
    (
        "inequality_minimum",
        "함수 f(x) = 2x^3 - 6x + 6에 대하여 x ≥ 0에서 f(x) > 0임을 보이려 한다. "
        "x ≥ 0에서 f(x)의 최솟값을 구하시오.",
        "2",  # f'=6(x^2-1), x=1: 2-6+6
    ),
]

# 발문 수식 변조 — (바꿀 문자열, 새 문자열). 정답이 **실제로 바뀌는** 자리만 골랐다.
TAMPERS: dict[str, tuple[str, str]] = {
    "tangent_slope_pick": ("90x", "96x"),
    "local_extremum_x(min)": ("96x", "90x"),
    "local_extremum_x(max, 극댓값 표기)": ("24x", "9x"),
    "local_extremum_value": ("63x", "36x"),
    "extremum_count": ("(x - 1)^3", "x^3 - x"),
    "differentiable_flag": ("|x - 1|", "(x - 1)^2"),
    "derivative_at_point(chain)": ("(4x + 3)", "(5x + 3)"),
    "product_derivative_at_point": ("x = 6", "x = 7"),
    "derivative_at_point": ("f'(-2)", "f'(-3)"),
    # f'=3(2x+3)(2x+5) → 감소 구간 (-2.5, -1.5) 의 정수는 -2 라 정답 -1 과 어긋난다
    "monotone_integer(floor)": ("12x^2 + 9x", "24x^2 + 45x"),
    "motion_at_time": ("t = 3", "t = 4"),
    "real_root_count": ("= -18", "= -10"),
    "extremum_parameter": ("- 72x", "- 96x"),
    "mean_value_c": ("[0, 4]", "[0, 3]"),
    "inequality_minimum": ("6x + 6", "x + 6"),
}


@pytest.fixture(params=CONTROLS, ids=[c[0] for c in CONTROLS])
def control(request: pytest.FixtureRequest) -> tuple[str, str, str]:
    return request.param


def test_controls_rederive_the_hand_derived_answer(control: tuple[str, str, str]) -> None:
    name, question, answer = control
    result = qr.rederive_question(question)
    assert result.state is qr.RederiveState.DERIVED, (name, result)
    assert qa._same(result.value or "", answer) is qa._Same.SAME, (name, result.value, answer)


def test_every_control_has_a_tamper_and_every_tamper_changes_the_question() -> None:
    assert set(TAMPERS) == {c[0] for c in CONTROLS}
    for name, question, _ in CONTROLS:
        old, new = TAMPERS[name]
        assert question.count(old) == 1, f"{name}: 변조 대상 문자열이 발문에 정확히 한 번 없다"
        assert question.replace(old, new) != question


def test_injection_tampered_question_turns_c5_red(control: tuple[str, str, str]) -> None:
    """발문의 수식만 바꾸고 정답은 그대로 — 재유도 값이 따라 움직여 C5 가 FAIL 이어야 한다."""
    name, question, answer = control
    old, new = TAMPERS[name]
    tampered = question.replace(old, new)
    assert tampered != question
    item = qa.judge_record({"slug": name, "question_text": tampered, "answer": answer})
    assert item.checks["C5"].state is qa.CheckState.FAIL, (name, item.checks["C5"])
    assert item.checks["C5"].code == "C5_QUESTION_REDERIVED_MISMATCH"
    assert item.verdict is qa.Verdict.FAIL


def test_untampered_controls_are_green_in_the_judge(control: tuple[str, str, str]) -> None:
    name, question, answer = control
    item = qa.judge_record({"slug": name, "question_text": question, "answer": answer})
    assert item.checks["C5"].state is qa.CheckState.PASS
    assert item.checks["C5"].detail == qr.rederive_question(question).family


def test_c5_does_not_read_the_verify_block() -> None:
    """독립성의 핵심 — `verify` 가 있든 없든 망가졌든 C5 결과는 같다."""
    _, question, answer = CONTROLS[3]
    base = {"slug": "x", "question_text": question, "answer": answer}
    without = qa._check_c5(base)
    garbage = qa._check_c5(
        {**base, "verify": {"conditions": "x**2 + 284*x - 42336 = 0", "answer_map": {"x": "-1"}}}
    )
    assert without == garbage
    assert without.state is qa.CheckState.PASS


def test_c5_rederivation_does_not_use_the_answer_back_derived_conditions() -> None:
    """역산 conditions(정답 108 에서 만든 식)가 있어도 틀린 정답은 C5 가 잡는다 "
    "— C1 은 못 잡는 구멍."""
    wrong = 109  # 참값은 108 — 정답을 109 로 틀리게 적고, conditions 는 그 정답에서 역산한다
    record = {
        "slug": "back-derived",
        "unit_codes": ["CALC-EXTREMUM-VALUE"],
        "question_text": "함수 f(x) = x^3 - 6x^2 - 63x 의 극댓값을 구하시오.",
        "answer": str(wrong),
        "verify": {
            # x = wrong 이 근이 되도록 만든 식 — 정답이 틀려도 자기 자신이 만든 식을 만족한다
            "conditions": f"x**2 + 282*x - {wrong**2 + 282 * wrong} = 0",
            "answer_map": {"x": str(wrong)},
            "answer_selection": "largest",
        },
    }
    item = qa.judge_record(record)
    assert item.checks["C1"].state is qa.CheckState.PASS  # C1 은 속는다(P3-07 정직 스코프)
    assert item.checks["C5"].state is qa.CheckState.FAIL
    assert item.verdict is qa.Verdict.FAIL


# ──────────────────────────────────────────────────────────────────────────
# 세 상태가 서로를 위장하지 않는다
# ──────────────────────────────────────────────────────────────────────────
def test_unknown_template_is_not_covered_not_pass() -> None:
    result = qr.rederive_question("다음 중 옳은 설명을 고르시오.")
    assert result.state is qr.RederiveState.NOT_COVERED and result.reason == "NO_RECOGNIZER"
    check = qa._check_c5({"question_text": "다음 중 옳은 설명을 고르시오.", "answer": "1"})
    assert check.state is qa.CheckState.NOT_APPLICABLE and check.code == qa.C5_NOT_COVERED


def test_parameter_formula_without_a_solver_rule_is_not_covered() -> None:
    result = qr.rederive_question("함수 f(x) = x^3 + ax^2에 대하여 f'(1)의 값을 구하시오.")
    assert result.state is qr.RederiveState.NOT_COVERED and result.reason == "PARAMETER"


def test_two_candidates_is_undecided_not_a_guess() -> None:
    """극대가 두 개인 사차함수에 '극대가 되는 x의 값'은 하나로 안 정해진다 — 임의로 "
    "고르지 않는다."""
    q = "사차함수 f(x) = -x^4 + 8x^2 가 극대가 되는 x의 값을 구하시오."
    result = qr.rederive_question(q)
    assert result.state is qr.RederiveState.UNDECIDED
    check = qa._check_c5({"question_text": q, "answer": "2"})
    assert check.state is qa.CheckState.UNVERIFIABLE and check.code == "C5_REDERIVE_UNDECIDED"
    item = qa.judge_record({"slug": "u", "question_text": q, "answer": "2"})
    assert item.verdict is qa.Verdict.UNVERIFIABLE  # 값 미정은 통과로 세지 않는다


def test_point_not_on_the_curve_is_undecided() -> None:
    q = "곡선 y = x^3 위의 점 (2, 9)에서의 접선의 기울기를 구하시오."
    assert qr.rederive_question(q).reason == "POINT_NOT_ON_CURVE"


def test_missing_question_or_answer_is_not_applicable_with_a_code() -> None:
    assert qa._check_c5({"answer": "1"}).code == "C5_NO_QUESTION_TEXT"
    assert qa._check_c5(
        {"question_text": "함수 f(x) = x^3에 대하여 f'(2)의 값을 구하시오."}
    ).code == ("C5_NO_ANSWER")


def test_unbounded_minimum_is_undecided() -> None:
    q = "함수 f(x) = -x^3 + 3에 대하여 x ≥ 0에서 f(x) > 0임을 보이려 한다. x ≥ 0에서 f(x)의 최솟값을 구하시오."
    assert qr.rederive_question(q).state is qr.RederiveState.UNDECIDED


def test_integer_endpoint_makes_the_integer_range_ambiguous() -> None:
    # f'=3x(x-2)... 증가하는 범위의 끝점이 정수 → 열린/닫힌 구간에 따라 정수 개수가 달라진다
    q = "함수 f(x) = -x^3 + 3x^2 + 4가 증가하는 x의 값의 범위에 속하는 정수는 하나뿐이다. 그 정수를 구하시오."
    assert qr.rederive_question(q).reason == "INTEGER_ENDPOINT"


def test_ellipsis_with_a_wrong_tail_is_not_guessed() -> None:
    q = "함수 f(x) = x + x^2 + x^3 + ... + 2x^8에 대하여 f'(2)의 값을 구하시오."
    assert qr.rederive_question(q).state is qr.RederiveState.NOT_COVERED


def test_ellipsis_alternating_and_geometric_rules() -> None:
    alt = qr.rederive_question(
        "함수 f(x) = x - x^2 + x^3 - x^4 + ... + x^7에 대하여 f'(1)의 값을 구하시오."
    )
    # 1 -2 +3 -4 +5 -6 +7 = 4
    assert alt.value == "4"
    geo = qr.rederive_question(
        "함수 f(x) = x + 2x^2 + 4x^3 + ... + 64x^7에 대하여 f'(0)의 값을 구하시오."
    )
    assert geo.value == "1"


# ──────────────────────────────────────────────────────────────────────────
# 레지스트리 자체의 건전성
# ──────────────────────────────────────────────────────────────────────────
def test_every_rule_family_has_a_title_and_a_fullmatch_pattern() -> None:
    assert qr._RULES, "규칙이 하나도 등록되지 않았다 — 공허하게 통과하는 가드가 된다"
    for rule in qr._RULES:
        assert rule.family in qr.FAMILY_TITLES, rule.family
        assert isinstance(rule.pattern, re.Pattern)


def test_rederive_is_pure_and_deterministic() -> None:
    q = CONTROLS[0][1]
    assert qr.rederive_question(q) == qr.rederive_question(q)
