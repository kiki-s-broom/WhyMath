"""순수 `verify_step` 3상태 검증 단위테스트 — WH-1 1단계 슬라이스 2(§3.1·hermetic).

correct(심볼릭 동치)·incorrect(거짓 증명)·unverifiable(비대수 step_type·파싱 불가·빈 입력·
판정 불가)·evidence_weight·step_type 전파·결정론·`VerifyStepResult` 필드셋·convert_xor 확인.
MATH-03: unverifiable 사유 코드(`reason_code` 폐쇄 7종) 분기 1:1·변별력·3상태 불변 동결 추가.

PRM 점수·step 파싱·coach 결선은 *후속*이라 여기 없다(본 슬라이스는 도구 primitive만).
"""

from __future__ import annotations

import pytest

from whymath_backend.l3.verify_step import (
    VerifyStepForm,
    VerifyStepReasonCode,
    VerifyStepResult,
    VerifyStepState,
    verify_step,
)
from whymath_backend.schema.enums import StepType


class TestCorrect:
    """대수 동치 → correct(evidence_weight 1.0·reason None)."""

    def test_distributive_law_is_correct(self) -> None:
        # 2(x+1) ≡ 2x+2 — 자유변수 OK(심볼릭 동치). 기존 numeric-only 검증과 차별점.
        result = verify_step("2*(x+1)", "2*x+2")
        assert result.state == VerifyStepState.correct
        assert result.evidence_weight == 1.0
        assert result.reason is None

    def test_numeric_identity_is_correct(self) -> None:
        result = verify_step("2+3", "5")
        assert result.state == VerifyStepState.correct
        assert result.evidence_weight == 1.0

    def test_convert_xor_caret_is_power(self) -> None:
        # convert_xor=True이므로 `^`는 거듭제곱(XOR 아님): x^2 ≡ x*x.
        result = verify_step("x^2", "x*x")
        assert result.state == VerifyStepState.correct

    def test_implicit_symbolic_equivalence(self) -> None:
        # (x+1)^2 ≡ x^2+2x+1 — 전개 동치.
        result = verify_step("(x+1)^2", "x^2+2*x+1")
        assert result.state == VerifyStepState.correct


class TestIncorrect:
    """대수 거짓 증명 → incorrect(evidence_weight 1.0·reason 채워짐).

    incorrect 조건: ⓐ 차이가 *0이 아님 확정*(is_zero is False·상수 차 등) 또는 ⓑ *같은 자유변수*의
    0-아닌 다항식(예: freshman's dream (a+b)²≠a²+b²).
    변수 집합이 다른 치환은 unverifiable(오판 회피).
    """

    def test_symbolic_constant_diff_is_incorrect(self) -> None:
        # 2x+1 vs 2x+3 — 차이가 상수 -2(0이 아님 확정) → 거짓 변형.
        result = verify_step("2*x+1", "2*x+3")
        assert result.state == VerifyStepState.incorrect
        assert result.evidence_weight == 1.0
        assert result.reason is not None
        assert "동치 아님" in result.reason

    def test_linear_constant_diff_is_incorrect(self) -> None:
        result = verify_step("x+1", "x+2")
        assert result.state == VerifyStepState.incorrect

    def test_numeric_false_is_incorrect(self) -> None:
        result = verify_step("2+3", "6")
        assert result.state == VerifyStepState.incorrect
        assert result.evidence_weight == 1.0

    def test_freshman_dream_is_incorrect(self) -> None:
        # (a+b)² vs a²+b² — 차이 2ab는 *같은 자유변수 {a,b}*의 0-아닌 다항식이라 항등식 아님이
        # 증명된다(a=b=1에서 4≠2).
        # 가장 흔한 대수 오류 → incorrect(unverifiable로 약하게 넘기지 않음).
        result = verify_step("(a+b)^2", "a^2+b^2")
        assert result.state == VerifyStepState.incorrect
        assert result.evidence_weight == 1.0
        assert result.reason is not None

    def test_substitution_different_symbols_is_unverifiable(self) -> None:
        # a vs b+1 — before{a}·after{b}로 변수 집합이 달라(치환·a가 b+1로 정의됐을 수 있음) 맥락을
        # 모른다 → 거짓 incorrect를 *회피*하고 보수적 unverifiable
        # (정확성 #1 — 올바른 단계 오판 금지).
        result = verify_step("a", "b+1")
        assert result.state == VerifyStepState.unverifiable
        assert result.evidence_weight == 0.5


class TestEquationSolutionSet:
    """등호 방정식 단계 — 해집합 보존 동치 판정(S3-02·방향 B).

    before·after가 *둘 다* 단일 등식이면 표현식 동치가 아니라 *해집합 보존*으로 판정한다 —
    보존이면 correct·변화면 incorrect·풀이 불가면 unverifiable(정직). 과거엔 등식이 파싱 실패해
    전부 unverifiable로 떨어졌다(shadow 89% unverifiable 근본원인).
    """

    def test_equation_transform_is_correct(self) -> None:
        # 2x+3=7 → 2x=4 : 둘 다 해집합 {2} → 올바른 변형.
        result = verify_step("2x+3=7", "2x=4")
        assert result.state == VerifyStepState.correct
        assert result.evidence_weight == 1.0
        assert result.reason is None

    def test_equation_final_step_is_correct(self) -> None:
        # 2x=4 → x=2 : 둘 다 {2} → correct.
        result = verify_step("2x=4", "x=2")
        assert result.state == VerifyStepState.correct

    def test_equation_changed_solution_is_incorrect(self) -> None:
        # 2x=6 → 2x=8 : {3} vs {4}(해가 바뀜) → incorrect.
        result = verify_step("2x=6", "2x=8")
        assert result.state == VerifyStepState.incorrect
        assert result.evidence_weight == 1.0
        assert result.reason is not None
        assert "해집합 비보존" in result.reason

    def test_equation_root_added_is_incorrect(self) -> None:
        # x=2 → x^2=2x : {2} vs {0,2}(양변에 x 곱해 근 추가) → incorrect.
        result = verify_step("x=2", "x^2=2*x")
        assert result.state == VerifyStepState.incorrect

    def test_equation_multivariable_is_unverifiable(self) -> None:
        # 다변수(x+y=2 → y=2-x)는 해집합 보존이어도 정직하게 unverifiable(거짓 판정 회피).
        result = verify_step("x+y=2", "y=2-x")
        assert result.state == VerifyStepState.unverifiable
        assert result.evidence_weight == 0.5

    def test_equation_complex_root_is_unverifiable(self) -> None:
        # x^2=-1 → x=1 : 좌변이 실근 없음(복소) → 판정 불가·unverifiable(거짓 incorrect 아님).
        result = verify_step("x^2=-1", "x=1")
        assert result.state == VerifyStepState.unverifiable

    def test_mixed_equation_and_expression_is_unverifiable(self) -> None:
        # 한쪽만 등식(방정식↔표현식 혼합) → 비교 대상 불일치 → 보수적 unverifiable.
        result = verify_step("2x+3=7", "x")
        assert result.state == VerifyStepState.unverifiable
        assert result.evidence_weight == 0.5

    def test_equation_identity_all_reals_is_correct(self) -> None:
        # (x+1)^2=x^2+2x+1 → x^2+2x+1=(x+1)^2 : 둘 다 항등(모든 실수) → correct.
        # 항등 방정식의 ∅/ℝ 모호성이 *거짓 incorrect*로 새지 않음을 확인(계약 핵심).
        result = verify_step("(x+1)^2=x^2+2*x+1", "x^2+2*x+1=(x+1)^2")
        assert result.state == VerifyStepState.correct

    def test_equation_with_unicode_superscript_correct(self) -> None:
        # 위첨자 등식도 정규화되어 판정 — x²=4 → x^2=4 : 둘 다 {-2,2} → correct.
        result = verify_step("x²=4", "x^2=4")
        assert result.state == VerifyStepState.correct

    def test_equation_step_type_propagated(self) -> None:
        # 등호 방정식 단계도 step_type을 그대로 전파한다.
        result = verify_step("2x+3=7", "2x=4", StepType.계산)
        assert result.state == VerifyStepState.correct
        assert result.step_type == StepType.계산


class TestExpressionRegressionWithEquationPath:
    """등호 방정식 경로 추가 후에도 *표현식* 동치 동작이 회귀하지 않음(등호 없는 식은 기존 경로)."""

    def test_expression_expand_still_correct(self) -> None:
        # (x+1)(x+2) → x^2+3x+2 : 등호 없는 표현식 → 기존 심볼릭 동치 → correct.
        result = verify_step("(x+1)*(x+2)", "x^2+3*x+2")
        assert result.state == VerifyStepState.correct

    def test_expression_wrong_expansion_still_incorrect(self) -> None:
        # (x+1)(x+2) → x^2+2 (오전개) : 등호 없는 표현식 비동치 → incorrect(유지).
        result = verify_step("(x+1)*(x+2)", "x^2+2")
        assert result.state == VerifyStepState.incorrect


class TestUnverifiableNonAlgebraic:
    """비대수 step_type → SymPy 시도 없이 unverifiable(0.5)."""

    def test_condition_interpretation_unverifiable(self) -> None:
        result = verify_step("어쩌고", "저쩌고", StepType.조건해석)
        assert result.state == VerifyStepState.unverifiable
        assert result.evidence_weight == 0.5
        assert result.reason is not None
        assert "비대수" in result.reason

    def test_case_analysis_unverifiable(self) -> None:
        result = verify_step("x>0", "x<0", StepType.케이스분류)
        assert result.state == VerifyStepState.unverifiable
        assert result.evidence_weight == 0.5

    def test_graph_sketch_unverifiable(self) -> None:
        result = verify_step("포물선", "위로 볼록", StepType.그래프스케치)
        assert result.state == VerifyStepState.unverifiable

    def test_non_algebraic_skips_sympy_even_if_equivalent(self) -> None:
        # 비대수 step_type이면 *동치여도* SymPy를 시도하지 않고 unverifiable(검증 불가 단원 정직).
        result = verify_step("2+3", "5", StepType.조건해석)
        assert result.state == VerifyStepState.unverifiable


class TestUnverifiableParsing:
    """파싱 불가·빈 입력·판정 불가 → unverifiable(correct 위장 금지·0.5)."""

    def test_sympify_exception_unverifiable(self) -> None:
        # "2 +* 3"는 SymPy가 파싱 못 해 SympifyError를 던진다 → except 경로로 unverifiable
        # (보수적·correct 위장 금지). reason은 "판정 불가/파싱 불가" 표기.
        result = verify_step("2 +* 3", "5")
        assert result.state == VerifyStepState.unverifiable
        assert result.evidence_weight == 0.5
        assert result.reason is not None
        assert "파싱 불가" in result.reason

    def test_prose_treated_as_symbol_is_unverifiable(self) -> None:
        # 한글 산문은 sympify가 *자유 심볼*로 받아(예외 아님) 차이의 is_zero가 None → unverifiable.
        result = verify_step("어쩌고저쩌고", "음음음")
        assert result.state == VerifyStepState.unverifiable
        assert result.evidence_weight == 0.5

    def test_empty_before_unverifiable(self) -> None:
        result = verify_step("", "5")
        assert result.state == VerifyStepState.unverifiable
        assert result.evidence_weight == 0.5
        assert result.reason is not None
        assert "빈 입력" in result.reason

    def test_empty_after_unverifiable(self) -> None:
        result = verify_step("5", "   ")
        assert result.state == VerifyStepState.unverifiable

    def test_both_empty_unverifiable(self) -> None:
        result = verify_step("", "")
        assert result.state == VerifyStepState.unverifiable

    def test_indeterminate_is_zero_none_unverifiable(self) -> None:
        # 판정 불가(is_zero None) 경로 — 미지 함수 차이는 simplify가 None을 낸다(거짓도 참도 아님).
        # f(x) - g(x)는 0인지 SymPy가 단정 못 함 → correct 위장 금지·unverifiable.
        result = verify_step("f(x)", "g(x)")
        assert result.state == VerifyStepState.unverifiable
        assert result.evidence_weight == 0.5
        assert result.reason is not None
        assert "판정 불가" in result.reason


class TestStepTypePropagation:
    """입력 step_type이 결과에 그대로 전파."""

    def test_step_type_propagated_on_correct(self) -> None:
        result = verify_step("2+3", "5", StepType.계산)
        assert result.state == VerifyStepState.correct
        assert result.step_type == StepType.계산

    def test_step_type_propagated_on_verify(self) -> None:
        result = verify_step("2*x+1", "2*x+3", StepType.검산)
        assert result.state == VerifyStepState.incorrect
        assert result.step_type == StepType.검산

    def test_step_type_none_default(self) -> None:
        result = verify_step("2+3", "5")
        assert result.step_type is None

    def test_step_type_propagated_on_unverifiable(self) -> None:
        result = verify_step("어쩌고", "저쩌고", StepType.조건해석)
        assert result.step_type == StepType.조건해석


class TestDeterminismAndFields:
    """결정론·필드셋·계산/검산은 대수 경로."""

    def test_deterministic_repeated_calls(self) -> None:
        first = verify_step("2*(x+1)", "2*x+2")
        second = verify_step("2*(x+1)", "2*x+2")
        assert first == second

    def test_result_field_set(self) -> None:
        result = verify_step("2+3", "5")
        assert isinstance(result, VerifyStepResult)
        # frozen·extra=forbid 모델 — 6필드 정확히(MATH-03 reason_code·S3-51 form 직교 추가).
        assert set(result.model_dump().keys()) == {
            "state",
            "step_type",
            "reason",
            "reason_code",
            "evidence_weight",
            "form",
        }

    def test_calc_step_type_uses_algebraic_path(self) -> None:
        # 계산은 비대수 집합에 없으므로 SymPy 동치 경로(correct 판정 가능).
        result = verify_step("3*4", "12", StepType.계산)
        assert result.state == VerifyStepState.correct

    def test_verify_step_type_uses_algebraic_path(self) -> None:
        # 검산도 대수 경로 — 거짓이면 incorrect.
        result = verify_step("3*4", "11", StepType.검산)
        assert result.state == VerifyStepState.incorrect


# ──────────────────────────────────────────────────────────────────────────
# MATH-03 — 검증 실패의 변별력 회복(reason_code 직교 필드·gap review §3 D3)
# ──────────────────────────────────────────────────────────────────────────

# 분기 1:1 실측 배터리 — (사유 코드, 입력 3튜플). 각 입력이 해당 unverifiable 분기를 실제로
# 발화시킴은 아래 TestReasonCodeBranchMap이 고정한다. 입력 선정 근거(2026-08-11 실측):
#   - parse_error: "2 +* 3"은 sympify 예외(TestUnverifiableParsing 기존 케이스).
#   - undecidable(표현식): sqrt(x²) vs x — 비다항·정의역 의존(identity_status docstring 예).
#     주의: "f(x)" vs "g(x)"는 implicit_multiplication이 f*x·g*x로 접어 *변수 집합 불일치*가
#     되므로(실측) 일반 undecidable 대표가 아니다.
#   - variable_mismatch: "a" vs "b+1" — 다항 + 자유변수 집합 불일치(치환 맥락). 한글 산문
#     ("어쩌고" vs "저쩌고")도 심볼 강제로 같은 분기다(identity_status docstring "산문이 심볼로
#     강제" — 문서화된 의미 그대로).
#   - heterogeneous_form: 항등식(ℝ)↔값 선언({2}) 전이(S3-06) + 등식↔표현식 혼합(같은 코드 —
#     둘 다 형태 이질·운영 세부는 reason 문장으로 구분).
#   - subset_ambiguous: x²=4 → x=2({−2,2}→{2} 진부분집합·S3-08).
#   - undecidable(등식): 다변수 등식 — 해집합 계산 불가(incomputable_side → undecidable).
_REASON_BRANCH_CASES: list[tuple[VerifyStepReasonCode, tuple[str, str, StepType | None]]] = [
    (VerifyStepReasonCode.parse_error, ("2 +* 3", "5", None)),
    (VerifyStepReasonCode.empty_input, ("", "5", None)),
    (VerifyStepReasonCode.non_algebraic_step, ("2+3", "5", StepType.조건해석)),
    (VerifyStepReasonCode.undecidable, ("sqrt(x^2)", "x", None)),
    (VerifyStepReasonCode.variable_mismatch, ("a", "b+1", None)),
    (VerifyStepReasonCode.heterogeneous_form, ("(x+1)^2=x^2+2*x+1", "x=2", None)),
    (VerifyStepReasonCode.heterogeneous_form, ("2x+3=7", "x", None)),
    (VerifyStepReasonCode.subset_ambiguous, ("x^2=4", "x=2", None)),
    (VerifyStepReasonCode.undecidable, ("x+y=2", "y=2-x", None)),
]


class TestFoldPointBackend:
    """MATH-03 ① — 백엔드 접힘 지점의 실측 고정(무변별 재현 + reason_code만이 가른다).

    접힘 ①(백엔드): IdentityVerdict 4상태·해집합 가드 3종이 VerifyStepState 3상태 하나
    (unverifiable)로 접히고, 자유문 `reason`도 분기 간 *동일 문장*이라 state·reason 두 축
    모두 원인을 구분하지 못한다 — 이 무변별은 설계상 유지되고(3상태 불변·문장 불변),
    변별은 오직 직교 `reason_code`가 회복한다. 접힘 ②(클라 폐기)는 모바일
    coach_signal_card_test.dart가 재현한다 — 한쪽만 고치면(코드만 싣고 클라가 안 읽으면,
    또는 클라만 분기하고 데이터가 없으면) 학생 화면의 변별은 회복되지 않는다(두 손실 분리).
    """

    def test_state_axis_is_indiscriminate_by_design(self) -> None:
        # 표기 문제(parse_error)·비대수 단계·수학적 미결정 — 학생 행동이 정반대인 세 원인이
        # state 축에서는 전부 같은 unverifiable(접힘 재현·3상태 불변이 의도이므로 계속 참).
        parse = verify_step("2 +* 3", "5")
        non_alg = verify_step("2+3", "5", StepType.조건해석)
        undec = verify_step("sqrt(x^2)", "x")
        assert parse.state == non_alg.state == undec.state == VerifyStepState.unverifiable

    def test_reason_text_axis_is_indiscriminate_within_equation_path(self) -> None:
        # 등식 경로의 이질 형태·진부분집합·계산 불가는 자유문 reason이 *한 글자까지 같다* —
        # 문장 축으로도 무변별(접힘 ① 재현). reason_code만이 세 분기를 가른다.
        hetero = verify_step("(x+1)^2=x^2+2*x+1", "x=2")
        subset = verify_step("x^2=4", "x=2")
        incomputable = verify_step("x+y=2", "y=2-x")
        assert hetero.reason == subset.reason == incomputable.reason  # 자유문 무변별 실측
        codes = {hetero.reason_code, subset.reason_code, incomputable.reason_code}
        assert codes == {
            VerifyStepReasonCode.heterogeneous_form,
            VerifyStepReasonCode.subset_ambiguous,
            VerifyStepReasonCode.undecidable,
        }


class TestReasonCodeBranchMap:
    """MATH-03 ② — 폐쇄 7종 코드 ↔ 실분기 1:1(라벨링만·판정 불변)."""

    @pytest.mark.parametrize(("expected_code", "args"), _REASON_BRANCH_CASES)
    def test_branch_yields_expected_code(
        self,
        expected_code: VerifyStepReasonCode,
        args: tuple[str, str, StepType | None],
    ) -> None:
        result = verify_step(args[0], args[1], args[2])
        assert result.state == VerifyStepState.unverifiable
        assert result.reason_code == expected_code
        # 라벨 부착이지 판정 변경 아님 — 가중치 할인(0.5)은 전 분기 불변(⑥c 동결).
        assert result.evidence_weight == 0.5

    def test_all_seven_codes_are_reachable(self) -> None:
        # 배터리가 폐쇄 7종을 전부 발화시킨다 — 죽은 코드(도달 불가 라벨) 없음.
        reached = {code for code, _ in _REASON_BRANCH_CASES}
        assert reached == set(VerifyStepReasonCode)

    def test_prose_symbols_labelled_variable_mismatch(self) -> None:
        # 한글 산문은 sympify가 서로 다른 심볼로 강제(실측) → 변수 집합 불일치 라벨.
        # identity_status docstring의 "산문이 심볼로 강제" 문서화 의미 그대로다.
        result = verify_step("어쩌고저쩌고", "음음음")
        assert result.state == VerifyStepState.unverifiable
        assert result.reason_code == VerifyStepReasonCode.variable_mismatch


class TestReasonCodeDiscrimination:
    """MATH-03 ⑤ — 변별력 실측: 다른 원인 입력이 같은 값을 내면 이 태스크 자체가 실패."""

    def test_parse_error_and_non_algebraic_differ(self) -> None:
        # "내 표기가 잘못됨"(고칠 수 있음)과 "원래 계산으로 확인 못 하는 단계"(고칠 게 없음)는
        # 학생 행동이 정반대다 — 두 입력이 서로 다른 코드를 내는지 실측(같으면 red).
        parse = verify_step("2 +* 3", "5")
        non_alg = verify_step("포물선", "위로 볼록", StepType.그래프스케치)
        assert parse.reason_code == VerifyStepReasonCode.parse_error
        assert non_alg.reason_code == VerifyStepReasonCode.non_algebraic_step
        assert parse.reason_code != non_alg.reason_code

    def test_every_unverifiable_carries_a_code(self) -> None:
        # 총부착 — 모든 unverifiable 분기가 코드를 갖는다(`_unverifiable` 필수 인자의 실측 확인·
        # verify_solution의 사유별 카운트 합 == n_unverifiable 불변식의 전제).
        for _, args in _REASON_BRANCH_CASES:
            result = verify_step(args[0], args[1], args[2])
            assert result.state == VerifyStepState.unverifiable
            assert result.reason_code is not None


class TestReasonCodeInvariants:
    """MATH-03 ⑥ — 불변식 동결: 3상태·폐쇄 7종·correct/incorrect 무코드·판정 무변경."""

    def test_verify_step_state_stays_three(self) -> None:
        # state는 3상태 불변 — 4·5상태 확장 금지(BKT·코치·집계·모바일 계약·acceptance ②).
        assert {s.value for s in VerifyStepState} == {"correct", "incorrect", "unverifiable"}

    def test_reason_code_is_closed_seven(self) -> None:
        # 폐쇄 enum 7종 — 코드 추가는 학생 3분기 사상·이벤트 계약 재검토를 요구하는 결정이다.
        assert {c.value for c in VerifyStepReasonCode} == {
            "parse_error",
            "undecidable",
            "non_algebraic_step",
            "empty_input",
            "heterogeneous_form",
            "subset_ambiguous",
            "variable_mismatch",
        }

    def test_correct_and_incorrect_have_no_reason_code(self) -> None:
        # reason_code의 질문은 "왜 판정 못 했는가" — 판정이 *된* 결과(correct/incorrect)는
        # None이다(검증 메타데이터·ReasoningStep 도메인 모델 아님 — D5 앞당기기 금지·⑥d).
        assert verify_step("2+3", "5").reason_code is None
        assert verify_step("2*x+1", "2*x+3").reason_code is None
        # 연쇄 등식 내부 위반 승격(incorrect)도 무코드.
        assert verify_step("x=(1+3)/2=3", "x=3").reason_code is None

    def test_labelling_did_not_change_verdicts_or_reasons(self) -> None:
        # 라벨 부착 전 관측 문장·상태·가중치의 바이트 동결(⑥c — 판정 변경 아님). 문장이 바뀌면
        # 여기서 red — reason은 학생/운영 노출 표면이라 이 슬라이스에서 불변이어야 한다.
        frozen: list[tuple[tuple[str, str, StepType | None], str]] = [
            (("2 +* 3", "5", None), "SymPy 판정 불가/파싱 불가 — 검증 안전 회피"),
            (("", "5", None), "빈 입력 — 검증 안전 회피"),
            (
                ("2+3", "5", StepType.조건해석),
                "비대수 단계(서술형/경우나누기/기하) — SymPy 검증 불가",
            ),
            (("sqrt(x^2)", "x", None), "SymPy 판정 불가 — 검증 안전 회피"),
            (("a", "b+1", None), "SymPy 판정 불가 — 검증 안전 회피"),
            (("(x+1)^2=x^2+2*x+1", "x=2", None), "해집합 판정 불가 — 검증 안전 회피"),
            (("x^2=4", "x=2", None), "해집합 판정 불가 — 검증 안전 회피"),
            (("x+y=2", "y=2-x", None), "해집합 판정 불가 — 검증 안전 회피"),
            (("2x+3=7", "x", None), "등호 방정식↔표현식 혼합 단계 — 검증 대상 불일치·안전 회피"),
        ]
        for args, expected_reason in frozen:
            result = verify_step(args[0], args[1], args[2])
            assert result.state == VerifyStepState.unverifiable
            assert result.reason == expected_reason
            assert result.evidence_weight == 0.5


# ──────────────────────────────────────────────────────────────────────────
# 판정 경로 형태 라벨 (S3-51) — 분기가 이미 정한 사실의 노출·판정 변경 0
# ──────────────────────────────────────────────────────────────────────────
class TestFormLabel:
    """`form`은 *어느 경로로* 판정했는지만 말한다 — state·reason_code와 직교(S3-51).

    이 축이 없으면 "등호 방정식을 해집합으로 판정한 correct"와 "표현식 동치 correct"가 같은
    글자라, S3-02가 실사용에서 몇 번 작동했는지(자유사용 대표측정 V3)를 셀 수 없다.
    """

    def test_equation_transition_is_equation_form(self) -> None:
        result = verify_step("2*x+3=7", "2*x=4")
        assert result.state == VerifyStepState.correct
        assert result.form == VerifyStepForm.equation

    def test_solution_set_break_is_equation_form(self) -> None:
        # 해집합 비보존(거짓 증명)도 등식 경로다 — incorrect라고 형태가 바뀌지 않는다.
        result = verify_step("2*x+3=7", "2*x=5")
        assert result.state == VerifyStepState.incorrect
        assert result.form == VerifyStepForm.equation

    def test_chain_equation_violation_is_equation_form(self) -> None:
        # 연쇄 등식 내부 위반 승격(S3-06 ①)도 등식 형태로 계상된다.
        result = verify_step("x=(1+3)/2=3", "x=2")
        assert result.state == VerifyStepState.incorrect
        assert result.form == VerifyStepForm.equation

    def test_mixed_form_is_mixed(self) -> None:
        # 한쪽만 등식 — 비교 전제 불성립(보수적 unverifiable)이며 형태는 mixed다.
        result = verify_step("2*x+3=7", "2*x")
        assert result.state == VerifyStepState.unverifiable
        assert result.reason_code == VerifyStepReasonCode.heterogeneous_form
        assert result.form == VerifyStepForm.mixed

    def test_expression_path_is_expression_form(self) -> None:
        result = verify_step("2*(x+1)", "2*x+2")
        assert result.state == VerifyStepState.correct
        assert result.form == VerifyStepForm.expression

    def test_expression_undecidable_keeps_expression_form(self) -> None:
        # 표현식 경로의 회피(미결정)도 형태는 판별된 뒤다 — expression으로 남는다.
        result = verify_step("sqrt(x**2)", "x")
        assert result.state == VerifyStepState.unverifiable
        assert result.form == VerifyStepForm.expression

    def test_non_algebraic_step_has_no_form(self) -> None:
        # 형태를 *판별하기 전에* 회피한 분기는 None — expression으로 접으면 위장이다.
        result = verify_step("경우 1과 2로 나눈다", "경우 1", StepType.케이스분류)
        assert result.state == VerifyStepState.unverifiable
        assert result.form is None

    def test_empty_input_has_no_form(self) -> None:
        result = verify_step("", "x=2")
        assert result.state == VerifyStepState.unverifiable
        assert result.form is None
