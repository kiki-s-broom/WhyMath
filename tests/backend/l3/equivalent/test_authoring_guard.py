"""EOS-205 생성 단계 거부 규칙(`l3/equivalent/authoring_guard.py`) — 순수 판정 단위 테스트.

검산식 근거 판정은 EOS-197 A6 회차 실측(30 CU)을 회귀 픽스처로 고정한다: 재진술 17 · 근거 없음 9 ·
통과 4. 양성 대조군은 Kiki 검수 메모의 교체안(`answer == (2**3 - 5*2 + 2) - 2*(3*2**2 - 5)` 등)이다
— 대조군 없이 거부 쪽만 고정하면 "전부 거부"라는 과잉 수정이 통과한다.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from whymath_backend.l3.equivalent.authoring_guard import (
    ANSWER_KEY,
    GroundingState,
    curriculum_method_violation,
    extract_question_relations,
    grounding_verdict,
    normalize_answer_key,
    standard_unit_codes,
)

_REPO = Path(__file__).resolve().parents[4]
_EOS197_RUNS = ("eos197-a6-openrouter", "eos197-a6-local")

_TANGENT_Q = "삼차함수 f(x) = x^3 - 5x + 2 의 그래프 위의 점 (2, 0) 에서의 접선의 y절편을 구하시오."
_EXTREMUM_Q = "삼차함수 y = x^3 - 3x^2 - 9x + 10 의 극댓값을 구하시오."
_VELOCITY_Q = (
    "점의 위치가 시간 t에 따라 s(t) = 2t^2 + 7t + 4로 주어질 때, t=3일 때의 속도를 구하시오."
)
_COUNT_Q = (
    "삼차함수 f(x) = x^3 - 3x^2 + 1 에 대하여 방정식 f(x) = k 가 서로 다른 세 실근을 갖도록 하는 "
    "정수 k의 개수를 구하시오."
)
_QUAD_Q = "이차방정식 x^2 - 6x + 8 = 0 의 두 근 중 큰 근을 구하시오."


def _eos197_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for run in _EOS197_RUNS:
        path = _REPO / "data" / "runs" / run / "cu.jsonl"
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return rows


class TestEos197Regression:
    def test_recorded_round_splits_17_restatement_9_ungrounded_4_grounded(self) -> None:
        """회차 실측 고정 — acceptance ①의 '30 CU 중 17건이 동어반복'이 재진술 판정과 같다."""
        rows = _eos197_rows()
        assert len(rows) == 30  # 스캔 0건·일부 누락은 공허한 통과다 — 표본 크기부터 고정
        counts: Counter[str] = Counter()
        for row in rows:
            verify = row["verify"]
            assert isinstance(verify, dict)
            verdict = grounding_verdict(
                str(row["question_text"]), verify["conditions"], verify["answer_map"]
            )
            counts[verdict.state.value] += 1
        assert counts == Counter({"restatement": 17, "ungrounded": 9, "grounded": 4})


class TestGrounding:
    @pytest.mark.parametrize(
        ("question", "condition", "answer_map"),
        [
            # Kiki 검수 메모 교체안 — 함수에 점을 대입한 식(양성 대조군)
            (_TANGENT_Q, "answer == (2**3 - 5*2 + 2) - 2*(3*2**2 - 5)", {"answer": "-14"}),
            (_EXTREMUM_Q, "answer == (-1)**3 - 3*(-1)**2 - 9*(-1) + 10", {"answer": "15"}),
            (_VELOCITY_Q, "answer == 4*3 + 7", {"answer": "19"}),
            (_COUNT_Q, "answer == (0**3 - 3*0**2 + 1) - (2**3 - 3*2**2 + 1) - 1", {"answer": "3"}),
            # `.subs` 꼴 — 함수식 자체를 SymPy가 대입
            (
                _TANGENT_Q,
                "answer == (x**3 - 5*x + 2 - x*(3*x**2 - 5)).subs(x, 2)",
                {"answer": "-14"},
            ),
            # 근 문항 — 발문의 방정식 그대로(정규형 비교라 인수분해 표기도 같다)
            (_QUAD_Q, "x**2 - 6*x + 8 = 0", {"x": "4"}),
            (_QUAD_Q, "(x - 2)*(x - 4) = 0", {"x": "4"}),
        ],
    )
    def test_recomputation_from_question_function_is_grounded(
        self, question: str, condition: str, answer_map: dict[str, str]
    ) -> None:
        verdict = grounding_verdict(question, condition, answer_map)
        assert verdict.state is GroundingState.GROUNDED
        assert verdict.rejected is False

    @pytest.mark.parametrize(
        ("condition", "answer_map"),
        [("n = 3", {"n": "3"}), ("b + 14 = 0", {"b": "-14"}), ("answer == -14", {"answer": "-14"})],
    )
    def test_restatement_is_rejected(self, condition: str, answer_map: dict[str, str]) -> None:
        verdict = grounding_verdict(_TANGENT_Q, condition, answer_map)
        assert verdict.state is GroundingState.RESTATEMENT
        assert verdict.rejected is True

    @pytest.mark.parametrize(
        ("question", "condition", "answer_map"),
        [
            # 기울기 7을 f′에서 계산하지 않고 박았다(Kiki: "기울기 하드코딩 제거")
            (_TANGENT_Q, "b = 7*(0 - 2)", {"b": "-14"}),
            # 정답이 근이 되게 거꾸로 만든 이차식 — 발문 함수와 무관
            (_EXTREMUM_Q, "M**2 + 2*M - 255 = 0", {"M": "15"}),
            # 다른 방정식으로 검산 — 발문의 방정식과 정규형이 다르다
            (_QUAD_Q, "x**2 - 7*x + 12 = 0", {"x": "4"}),
        ],
    )
    def test_hardcoded_or_unrelated_condition_is_ungrounded(
        self, question: str, condition: str, answer_map: dict[str, str]
    ) -> None:
        verdict = grounding_verdict(question, condition, answer_map)
        assert verdict.state is GroundingState.UNGROUNDED
        assert verdict.rejected is True

    def test_value_coincidence_alone_is_not_grounding(self) -> None:
        """값 일치만으로는 통과하지 않는다 — 구조 일치 절의 반례 픽스처.

        f(x) = x^3 - 4x^2 + 3x + 5에서 f′(1) = -2다. `-2*1`은 값이 f′(1)과 같지만 미리 구한
        기울기 -2를 박은 식이다. 1을 x로 되돌리면 `-2*x`라 f′(x) = 3x^2 - 8x + 3이 아니다.
        """
        question = "삼차함수 f(x) = x^3 - 4x^2 + 3x + 5 의 그래프 위의 점 (1, 5)에서의 접선의 y절편"
        verdict = grounding_verdict(question, "-2*1 + b = 5", {"b": "7"})
        assert verdict.state is GroundingState.UNGROUNDED

    def test_question_without_math_is_unknown_not_rejected(self) -> None:
        """발문 수식을 못 읽으면 판정 불가 — 거부하지 않는다(모른다 ≠ 아니다)."""
        verdict = grounding_verdict(
            "한 변의 길이가 7인 정사각형의 둘레를 구하시오.", "a = 4*7", {"a": "28"}
        )
        assert verdict.state is GroundingState.UNKNOWN
        assert verdict.rejected is False

    def test_unit_annotation_does_not_pollute_function(self) -> None:
        """`… + 1 (m)`의 단위 `(m)`가 암묵 곱셈으로 함수식에 섞이지 않는다."""
        question = (
            "위치가 x(t) = 2t^3 - 9t^2 + 12t + 1 (m)이다. 시각 t = 4에서 점 P의 속도를 구하시오."
        )
        relations = extract_question_relations(question)
        assert [str(expr) for _, expr in relations.functions] == ["2*t**3 - 9*t**2 + 12*t + 1"]

    def test_latex_parenthesis_wrapper_is_read(self) -> None:
        relations = extract_question_relations("이차방정식 \\( x^2 - 5x + 6 = 0 \\)의 해는?")
        # 짝 없는 여는 괄호를 벗겨 방정식을 읽는다 — 비어 있지 않은 것만이 아니라 내용까지 본다.
        assert relations.equations == ("x**2 - 5*x + 6 = 0",)
        function_only = extract_question_relations("함수 \\( f(x) = x^3 - 3x \\)의 극댓값")
        assert function_only.equations == ()  # `f*x = …` 방정식으로 오독하지 않는다
        assert [str(expr) for _, expr in function_only.functions] == ["x**3 - 3*x"]


class TestAnswerKey:
    def test_model_named_key_becomes_answer(self) -> None:
        conditions, answer_map = normalize_answer_key(
            _TANGENT_Q, "b == (2**3 - 5*2 + 2) - 2*(3*2**2 - 5)", {"b": "-14"}
        )
        assert answer_map == {ANSWER_KEY: "-14"}
        assert conditions == "answer == (2**3 - 5*2 + 2) - 2*(3*2**2 - 5)"

    def test_list_conditions_are_renamed_together(self) -> None:
        conditions, answer_map = normalize_answer_key(
            _VELOCITY_Q, ["v == 4*3 + 7", "v > 0"], {"v": "19"}
        )
        assert conditions == ["answer == 4*3 + 7", "answer > 0"]
        assert answer_map == {ANSWER_KEY: "19"}

    def test_question_variable_is_kept_for_root_problems(self) -> None:
        """근 문항의 x는 발문 방정식의 변수라 바꾸면 검산식이 발문과 갈라진다 — 유지."""
        conditions, answer_map = normalize_answer_key(_QUAD_Q, "x**2 - 6*x + 8 = 0", {"x": "4"})
        assert answer_map == {"x": "4"}
        assert conditions == "x**2 - 6*x + 8 = 0"

    def test_unreadable_question_leaves_key_alone(self) -> None:
        conditions, answer_map = normalize_answer_key("둘레를 구하시오.", "a = 4*7", {"a": "28"})
        assert answer_map == {"a": "28"}
        assert conditions == "a = 4*7"

    def test_rename_does_not_touch_substrings(self) -> None:
        """`b` → `answer` 치환이 다른 이름(`abs`)의 일부를 건드리지 않는다."""
        conditions, _ = normalize_answer_key(
            _TANGENT_Q, "b == abs(2**3 - 5*2 + 2) - 14", {"b": "-14"}
        )
        assert conditions == "answer == abs(2**3 - 5*2 + 2) - 14"


class TestUnitCodes:
    def test_brackets_are_stripped_and_deduplicated(self) -> None:
        assert standard_unit_codes(["[12미적Ⅰ-02-05]", "[12미적Ⅰ-02-05]", "[10공수1-02-02]"]) == [
            "12미적Ⅰ-02-05",
            "10공수1-02-02",
        ]

    def test_empty_input_gives_empty(self) -> None:
        assert standard_unit_codes([" ", "[]"]) == []


class TestCurriculumScope:
    @pytest.mark.parametrize(
        "explanation",
        [
            "이계도함수 f''(x) = 6x - 6 이므로 x = -1에서 f''(-1) < 0, 극대이다.",
            "f″(-1) = -12 < 0 이므로 극대.",
            "이차 도함수의 부호로 판정한다.",
            "By the second derivative test, x = -1 is a local maximum.",
        ],
    )
    def test_second_derivative_in_calculus1_is_rejected(self, explanation: str) -> None:
        assert curriculum_method_violation(["[12미적Ⅰ-02-07]"], [explanation]) is not None

    @pytest.mark.parametrize(
        "explanation",
        [
            "f'(x) = 3x^2 - 6x - 9 = 3(x+1)(x-3), x = -1 좌우에서 f'의 부호가 + → − 이므로 극대.",
            "f(2) = 0, f'(2) = 7 이므로 접선은 y = 7x - 14.",
        ],
    )
    def test_first_derivative_sign_change_is_allowed(self, explanation: str) -> None:
        assert curriculum_method_violation(["[12미적Ⅰ-02-07]"], [explanation]) is None

    def test_other_standards_are_not_checked(self) -> None:
        """범위 표가 없는 성취기준은 검사하지 않는다(미적분Ⅱ에서는 이계도함수가 범위 안)."""
        assert curriculum_method_violation(["[12미적Ⅱ-02-03]"], ["이계도함수 f''(x)"]) is None


# ──────────────────────────────────────────────────────────────────────
# 독립 검토 지적 회귀(PR 전 검토 1~9번) — 과잉 거부·미탐 반례를 픽스처로 고정
# ──────────────────────────────────────────────────────────────────────
_TANGENT2_Q = (
    "삼차함수 f(x) = x^3 - 6x^2 + 9x + 4 의 그래프 위의 점 (2, f(2))에서의 접선의 y절편을 구하시오."
)


class TestReviewRegressions:
    @pytest.mark.parametrize(
        ("question", "condition", "answer_map"),
        [
            # 1 — `^` 표기(오프셋이 밀려 부분식이 잘리던 결함)
            (_TANGENT_Q, "answer == (2^3 - 5*2 + 2) - 2*(3*2^2 - 5)", {"answer": "-14"}),
            # 3 — 점이 1이면 재진술 판정기가 0·1을 버려 정당한 식을 재진술로 읽던 결함
            ("함수 f(x) = 2x^2 + 3 에서 f'(1)의 값", "answer == 4*1", {"answer": "4"}),
            ("함수 f(x) = x^2 + 1 에서 f(1)의 값", "answer == 1**2 + 1", {"answer": "2"}),
            ("이차방정식 x^2 - 2x - 3 = 0 의 큰 근", "(x - 3)*(x + 1) = 0", {"x": "3"}),
            # 4 — LaTeX 구분자·중괄호·매개변수 함수
            (
                "함수 \\( f(x) = x^3 - 3x \\)의 극댓값",
                "answer == (-1)**3 - 3*(-1)",
                {"answer": "2"},
            ),
            ("함수 $f(x) = x^{3} - 3x$의 극댓값", "answer == (-1)**3 - 3*(-1)", {"answer": "2"}),
            (
                "f(x) = x^2 + ax + b 에 대하여 f(1) = 0, f(2) = 3 일 때",
                ["1 + a + b = 0", "4 + 2*a + b = 3"],
                {"a": "2", "b": "-3"},
            ),
            # 5 — 함수 적용 `f(a) = 10`(검산식 변수가 함수 변수와 다름)
            ("f(x) = x^2 + 3x 에서 f(a) = 10인 양수 a", "a**2 + 3*a - 10 = 0", {"a": "2"}),
            # 2의 대조군 — 기울기도 f′에 점을 대입해 쓰면 통과
            (
                _TANGENT2_Q,
                "b == (2**3 - 6*2**2 + 9*2 + 4) - 2*(3*2**2 - 12*2 + 9)",
                {"b": "12"},
            ),
        ],
    )
    def test_legitimate_recomputation_is_grounded(
        self, question: str, condition: str | list[str], answer_map: dict[str, str]
    ) -> None:
        assert grounding_verdict(question, condition, answer_map).state is GroundingState.GROUNDED

    @pytest.mark.parametrize(
        ("question", "condition", "answer_map"),
        [
            # 2 — 근거 부분식 하나에 기대 중간값·정답을 박은 식
            (_TANGENT2_Q, "b == (2**3 - 6*2**2 + 9*2 + 4) - (-3)*2", {"b": "12"}),
            (_TANGENT2_Q, "b == (2**3 - 6*2**2 + 9*2 + 4) - 99 + 105", {"b": "12"}),
            (_TANGENT2_Q, "b == 0*(2**3 - 6*2**2 + 9*2 + 4) + 12", {"b": "12"}),
            # 6 — 발문의 `t = 3`(점 지정)을 방정식으로 끼워 넣어 재진술을 통과시키던 결함
            (_VELOCITY_Q, ["t = 3", "v == 19"], {"v": "19"}),
        ],
    )
    def test_padding_with_hardcoded_numbers_is_rejected(
        self, question: str, condition: str | list[str], answer_map: dict[str, str]
    ) -> None:
        assert grounding_verdict(question, condition, answer_map).rejected is True

    def test_function_variable_answer_is_renamed(self) -> None:
        """7 — 극값을 함수 변수 `x`로 적은 답은 근이 아니므로 `answer`로 바꾼다."""
        conditions, answer_map = normalize_answer_key(
            "삼차함수 f(x) = x^3 - 3x의 극댓값을 구하시오.", "x == (-1)**3 - 3*(-1)", {"x": "2"}
        )
        assert answer_map == {ANSWER_KEY: "2"}
        assert conditions == "answer == (-1)**3 - 3*(-1)"

    @pytest.mark.parametrize(
        "text",
        ['f"(x) < 0', "h''(x) < 0", "d^2y/dx^2 < 0", "두 번 미분하면", "f^{\\prime\\prime}(x)"],
    )
    def test_second_derivative_notation_variants(self, text: str) -> None:
        """9 — 표기 변형으로 교육과정 범위 검사를 우회하지 못한다."""
        assert curriculum_method_violation(["[12미적Ⅰ-02-07]"], [text]) is not None

    def test_ascii_roman_numeral_standard_is_checked(self) -> None:
        assert curriculum_method_violation(["[12미적I-02-07]"], ["이계도함수"]) is not None


def test_every_equation_must_be_grounded() -> None:
    """등식 전부가 근거를 가져야 한다 — 근거 등식 하나에 재진술 등식을 덧붙인 반례(M14)."""
    verdict = grounding_verdict(
        _VELOCITY_Q, ["answer == 4*3 + 7", "answer == 19"], {"answer": "19"}
    )
    assert verdict.rejected is True


def test_point_assignment_is_not_a_root_variable() -> None:
    """발문의 `t=3`은 점 지정이지 방정식이 아니다 — 속도 답을 `t`로 적으면 `answer`로 바꾼다(M15)."""
    conditions, answer_map = normalize_answer_key(_VELOCITY_Q, "t == 4*3 + 7", {"t": "19"})
    assert answer_map == {ANSWER_KEY: "19"}
    assert conditions == "answer == 4*3 + 7"
