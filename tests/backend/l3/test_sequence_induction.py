"""S4-66 — 수열 귀납 검증기(`l3/sequence_induction.py`) 단위 테스트.

검증 축:
  ① 설계서 §5.4 예시 5종이 실측값과 일치한다(손계산이 아니라 실행 결과).
  ② **정확 일치**: a(30)=1073741823에 정답+1을 주면 fail — 같은 쌍을 `isclose`로 보면 통과함을
     테스트 안에서 함께 보여 비교 방식이 바뀌었다는 변별력 증거를 남긴다.
  ③ 자원 상한 초과는 fail이 아니라 unverifiable(사유 "범위 초과").
  ④ 파서 거부(절 중복·미지 키·초기항 부족·질의 항 번호<시작 항·금지 식 요소).
  ⑤ `eval`·`sympify`·`isclose`를 소스가 쓰지 않는다(AST 검사).
  ⑥ 결함 주입(초기항·계수·시작 번호·홀짝 분기)이 각각 pass→fail로 뒤집힌다 — 주입이 실제
     적용됐는지(`mutated != original`)와 원복이 바이트 동일한지를 함께 단언한다.
"""

from __future__ import annotations

import ast
import math
from fractions import Fraction
from pathlib import Path

import pytest

from whymath_backend.l3 import sequence_induction as module
from whymath_backend.l3.sequence_induction import (
    MAX_AST_NODES,
    MAX_BITS,
    MAX_POW_EXPONENT,
    MAX_STEPS,
    SequenceInductionError,
    SequenceRangeError,
    describe_sequence_model_ko,
    execute_sequence_model,
    format_exact_value,
    parse_exact_value,
    parse_sequence_model,
    verify_sequence_induction,
)
from whymath_backend.l3.verification_tier import VerificationTier

ARITH = "init=a(1)=7; rec=a(n+1)=a(n)+6; query=a(12)"
FIB = "init=a(1)=1,a(2)=1; rec=a(n+2)=a(n+1)+a(n); query=a(10)"
CLOSED = "init=a(1)=3; rec=a(n+1)=5*a(n); query=closed(a(n)=3*5^(n-1), upto=12)"
BRANCH_SUM = "init=a(1)=1; rec=a(n+1)=if(n%2==1, a(n)+2, 2*a(n)); query=S(6)"
BRANCH_TERMS = "init=a(1)=1; rec=a(n+1)=if(n%2==1, a(n)+2, 2*a(n)); query=terms(6)"
DOUBLE_PLUS_ONE = "init=a(1)=1; rec=a(n+1)=2*a(n)+1; query=a(30)"


def _state(conditions: str, answer: str) -> str:
    return verify_sequence_induction(conditions, answer).state


# ──────────────────────────────────────────────────────────────────────────
# ① 설계서 예시 — 값은 실행 결과
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("conditions", "answer"),
    [
        (ARITH, "73"),  # 7 + 11*6
        (FIB, "55"),
        (CLOSED, "1"),
        (BRANCH_SUM, "52"),  # 1, 3, 6, 8, 16, 18
        (BRANCH_TERMS, "[1, 3, 6, 8, 16, 18]"),
        (DOUBLE_PLUS_ONE, "1073741823"),
    ],
)
def test_design_doc_examples_pass(conditions: str, answer: str) -> None:
    verdict = verify_sequence_induction(conditions, answer)
    assert verdict.state == "pass", verdict.reason
    assert verdict.residual_axes  # 잔여 축은 항상 남는다(발문↔점화식 정합)


def test_difference_form_and_second_order_constant() -> None:
    """계차형 a(n+1)=a(n)+2n+1 → a(n)=n², 2단계 상수항 포함 점화."""
    assert _state("init=a(1)=1; rec=a(n+1)=a(n)+2*n+1; query=a(10)", "100") == "pass"
    assert (
        _state("init=a(1)=1; rec=a(n+1)=a(n)+2*n+1; query=closed(a(n)=n^2, upto=40)", "1") == "pass"
    )
    assert _state("init=a(1)=1,a(2)=2; rec=a(n+2)=2*a(n+1)-a(n)+1; query=a(4)", "7") == "pass"


def test_rational_and_negative_terms_are_exact() -> None:
    assert _state("init=a(1)=1/2; rec=a(n+1)=a(n)/2; query=a(4)", "1/16") == "pass"
    assert _state("init=a(1)=-3; rec=a(n+1)=-2*a(n); query=a(3)", "-12") == "pass"
    # 같은 값의 다른 표기(약분 전)도 정확히 같은 유리수다.
    assert _state("init=a(1)=1/2; rec=a(n+1)=a(n)/2; query=a(4)", "2/32") == "pass"


def test_start_zero_index_semantics() -> None:
    """start=0: a(N)은 항 번호 N, S(N)·terms(N)은 첫 N항(= a(0)..a(N-1))."""
    base = "start=0; init=a(0)=2; rec=a(n+1)=a(n)+3; "
    assert _state(base + "query=a(4)", "14") == "pass"
    assert _state(base + "query=terms(3)", "[2, 5, 8]") == "pass"
    assert _state(base + "query=S(3)", "15") == "pass"
    assert _state(base + "query=a(0)", "2") == "pass"  # 초기항 자체도 질의 가능


def test_branch_condition_uses_recurrence_index_n() -> None:
    """분기의 n은 a(n)의 항 번호다 — start가 달라지면 같은 식도 다른 수열이 된다."""
    rec = "rec=a(n+1)=if(n%2==0, a(n)+1, a(n)*2); "
    assert _state("start=0; init=a(0)=1; " + rec + "query=a(4)", "10") == "pass"
    assert _state("init=a(1)=1; " + rec + "query=a(4)", "6") == "pass"


# ──────────────────────────────────────────────────────────────────────────
# ② 정확 일치 — isclose 회귀
# ──────────────────────────────────────────────────────────────────────────
def test_off_by_one_integer_answer_fails_where_isclose_would_pass() -> None:
    """a(30)=1073741823에 정답+1(1073741824)을 주면 fail이다.

    이 쌍은 `math.isclose(rel_tol=1e-9)`로는 **같은 값**이다(설계서 §6.1 실측) — 그래서 이
    단언이 비교 방식이 `==`로 바뀌었다는 변별력 증거가 된다. 아래 첫 단언이 깨지면 이 테스트의
    전제(isclose가 통과시킨다)가 사라진 것이므로 케이스를 다시 골라야 한다.
    """
    assert math.isclose(1073741823, 1073741824, rel_tol=1e-9)
    assert _state(DOUBLE_PLUS_ONE, "1073741823") == "pass"
    off_by_one = verify_sequence_induction(DOUBLE_PLUS_ONE, "1073741824")
    assert off_by_one.state == "fail"
    assert "불일치" in (off_by_one.reason or "")


def test_no_tolerance_on_any_answer_form() -> None:
    assert _state(ARITH, "74") == "fail"
    assert _state("init=a(1)=1/2; rec=a(n+1)=a(n)/2; query=a(4)", "1/17") == "fail"
    assert _state(BRANCH_TERMS, "[1, 3, 6, 8, 16, 19]") == "fail"  # 마지막 항만 다름
    assert _state(CLOSED, "0") == "fail"  # 폐형이 맞으므로 0은 틀린 답


def test_closed_mismatch_is_detected_and_answer_zero_passes() -> None:
    """폐형이 점화식과 어긋나면 closed는 0 — 어긋남을 정확히 짚는다."""
    wrong = "init=a(1)=3; rec=a(n+1)=5*a(n); query=closed(a(n)=3*5^n, upto=12)"
    assert _state(wrong, "0") == "pass"
    assert _state(wrong, "1") == "fail"


def test_closed_agreement_stops_at_upto_and_is_not_a_general_claim() -> None:
    """n ≤ upto에서만 일치하는 폐형은 upto 안에서는 1이고, 넘으면 0 — '모든 n'이 아니다."""
    # 점화 a(n+1)=a(n)+2n+1은 n²을 만들지만, n=5에서만 +1이 더해져 a(6)=37≠36이다.
    # 즉 n²은 a(1)..a(5)까지만 점화식과 일치한다.
    rec = "init=a(1)=1; rec=a(n+1)=a(n)+2*n+1+if(n%6==5, 1, 0); "
    assert _state(rec + "query=closed(a(n)=n^2, upto=5)", "1") == "pass"
    assert _state(rec + "query=closed(a(n)=n^2, upto=6)", "0") == "pass"


def test_closed_always_keeps_general_claim_residual() -> None:
    """Verifier는 잔여 축이 비면 완전 기계 pass로 처리한다 — closed에서는 절대 비우지 않는다."""
    for answer in ("1", "0"):
        verdict = verify_sequence_induction(CLOSED, answer)
        assert "모든 n에 대한 일반 주장" in verdict.residual_axes


# ──────────────────────────────────────────────────────────────────────────
# ③ 자원 상한 — 초과는 fail이 아니라 unverifiable
# ──────────────────────────────────────────────────────────────────────────
SQUARE = "init=a(1)=2; rec=a(n+1)=a(n)^2; query=a({n})"


def test_square_recurrence_exceeds_bit_limit_at_n17() -> None:
    """a(n+1)=a(n)²·a(1)=2는 a(16)=2^32768까지는 한도 안, a(17)=2^65536에서 한도를 넘는다."""
    over = verify_sequence_induction(SQUARE.format(n=17), "1")
    assert over.state == "unverifiable"
    assert "범위 초과" in (over.reason or "")
    assert over.tier is None
    assert over.residual_axes == ()  # 기계가 닫은 축이 없다
    # 한도 안(n=16)이면 실행은 된다 — 값이 4,300자리를 넘어 답 문자열로 읽지 못해 판정은 unverifiable
    # 이지만 사유가 '범위 초과'가 아니라 '읽을 수 없음'임을 구분한다.
    within = verify_sequence_induction(SQUARE.format(n=16), "1")
    assert within.state == "fail"  # 실행값(2^32768)은 1이 아니다 — 비트 한도 안이라 실행·대조 성립
    assert "범위 초과" not in (within.reason or "")


def test_bit_limit_fires_on_multiplication_without_pow() -> None:
    """곱셈으로 비트가 폭주하는 경로(`a(n)*a(n)`)도 `_check_bits`가 잡는다.

    제곱 점화를 `^2`로 쓰면 지수 사전검사가 먼저 걸려 `_check_bits`에 닿지 않는다 — 이 케이스가
    비트 길이 검사 자체의 변별력을 따로 증명한다(없으면 그 검사를 지워도 모든 테스트가 통과한다).
    """
    template = "init=a(1)=2; rec=a(n+1)=a(n)*a(n); query=a({n})"
    assert _state(template.format(n=2), "4") == "pass"
    over = verify_sequence_induction(template.format(n=17), "1")
    assert over.state == "unverifiable"
    assert "범위 초과" in (over.reason or "")


def test_query_smaller_than_initial_term_count_returns_only_requested_terms() -> None:
    """2단계 점화는 초기항이 2개지만 질의가 1항이면 첫 1항만 돌려준다(초과 반환 금지)."""
    fib = "init=a(1)=1,a(2)=1; rec=a(n+2)=a(n+1)+a(n); "
    assert _state(fib + "query=terms(1)", "[1]") == "pass"
    assert _state(fib + "query=terms(1)", "[1, 1]") == "fail"
    assert _state(fib + "query=S(1)", "1") == "pass"
    assert _state(fib + "query=terms(2)", "[1, 1]") == "pass"
    assert _state(fib + "query=terms(3)", "[1, 1, 2]") == "pass"
    assert _state(fib + "query=S(3)", "4") == "pass"
    assert _state(fib + "query=closed(a(n)=1, upto=1)", "1") == "pass"
    # start=0: a(0)만 묻는 closed — 초기항 범위 안에서 끝난다.
    assert _state("start=0; init=a(0)=5,a(1)=5; rec=a(n+2)=a(n); query=terms(1)", "[5]") == "pass"


def test_step_limit() -> None:
    over = "init=a(1)=0; rec=a(n+1)=a(n)+1; query=a({n})"
    assert MAX_STEPS == 1000
    assert _state(over.format(n=1000), "999") == "pass"
    verdict = verify_sequence_induction(over.format(n=1001), "1000")
    assert verdict.state == "unverifiable"
    assert "범위 초과" in (verdict.reason or "")


def test_pow_exponent_limit_literal_and_runtime() -> None:
    assert MAX_POW_EXPONENT == 64
    literal = verify_sequence_induction(
        f"init=a(1)=1; rec=a(n+1)=a(n)^{MAX_POW_EXPONENT + 1}; query=a(3)", "1"
    )
    assert literal.state == "unverifiable"
    assert "범위 초과" in (literal.reason or "")
    # n-의존 지수는 평가 시점에 같은 범위를 검사한다 — 2^n은 n=65에서 한도를 넘는다. 폐형이 n=64까지
    # 점화식과 일치해야(a(n)=2^n) 평가가 n=65에 도달한다(불일치는 첫 항에서 결론이 나 조기 종료한다).
    runtime = verify_sequence_induction(
        "init=a(1)=2; rec=a(n+1)=2*a(n); query=closed(a(n)=2^n, upto=100)", "1"
    )
    assert runtime.state == "unverifiable"
    assert "범위 초과" in (runtime.reason or "")
    # 음수 지수도 범위 밖이다.
    negative = verify_sequence_induction(
        "init=a(1)=1; rec=a(n+1)=a(n)+1; query=closed(a(n)=2^(n-2), upto=3)", "1"
    )
    assert negative.state == "unverifiable"


def test_ast_node_limit() -> None:
    long_expr = "+".join(["1"] * 40) + "+a(n)"
    verdict = verify_sequence_induction(f"init=a(1)=1; rec=a(n+1)={long_expr}; query=a(2)", "42")
    assert MAX_AST_NODES == 64
    assert verdict.state == "unverifiable"
    assert "범위 초과" in (verdict.reason or "")


def test_bit_limit_constant_is_the_documented_value() -> None:
    assert MAX_BITS == 65_536


def test_division_by_zero_is_unverifiable_not_fail() -> None:
    verdict = verify_sequence_induction("init=a(1)=1; rec=a(n+1)=1/(a(n)-a(n)); query=a(2)", "1")
    assert verdict.state == "unverifiable"
    assert "0으로 나눔" in (verdict.reason or "")


def test_untaken_branch_is_not_evaluated() -> None:
    """선택되지 않은 가지의 0 나눗셈은 평가하지 않는다(분기 의미 보존)."""
    cond = "init=a(1)=4; rec=a(n+1)=if(n%2==1, a(n)/2, 1/(n-n)); query=a(2)"
    assert _state(cond, "2") == "pass"


# ──────────────────────────────────────────────────────────────────────────
# ④ 파서 거부
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("conditions", "needle"),
    [
        ("init=a(1)=1; init=a(1)=2; rec=a(n+1)=a(n); query=a(2)", "절 중복"),
        ("init=a(1)=1; rec=a(n+1)=a(n); query=a(2); foo=1", "미지 절 키"),
        ("init=a(1)=1; rec=a(n+1)=a(n)", "필수 절 누락"),
        ("rec=a(n+1)=a(n); query=a(2)", "필수 절 누락"),
        ("start=2; init=a(2)=1; rec=a(n+1)=a(n); query=a(3)", "start는 0 또는 1"),
        # 종전 부록 예시(폐기) — 키 `sequence`는 미지 키다.
        ("sequence=a(n+1)=2*a(n)+1, a(1)=1; query=a(10)", "미지 절 키"),
        # 2단계 점화인데 초기항 1개 / 3개 / 시작 항이 아닌 번호.
        ("init=a(1)=1; rec=a(n+2)=a(n+1)+a(n); query=a(5)", "초기항"),
        ("init=a(1)=1,a(2)=1,a(3)=2; rec=a(n+2)=a(n+1)+a(n); query=a(5)", "초기항"),
        ("init=a(2)=1; rec=a(n+1)=a(n); query=a(3)", "초기항"),
        ("init=a(1)=1,a(1)=2; rec=a(n+2)=a(n+1); query=a(3)", "중복"),
        # 질의 항 번호가 시작 항 번호보다 작음.
        ("init=a(1)=1; rec=a(n+1)=a(n); query=a(0)", "시작 항 번호"),
        ("start=0; init=a(0)=1; rec=a(n+1)=a(n); query=closed(a(n)=1, upto=0)", ""),
        ("init=a(1)=1; rec=a(n+1)=a(n); query=S(0)", "1 이상"),
        # 점화식 형식.
        ("init=a(1)=1; rec=a(n+3)=a(n); query=a(2)", "rec 형식"),
        ("init=a(1)=1; rec=a(n)=a(n); query=a(2)", "rec 형식"),
        # 질의 형식 — 수렴·극한은 이 도메인이 받지 않는다.
        ("init=a(1)=1; rec=a(n+1)=a(n); query=limit(a(n))", "질의 형식"),
        ("init=a(1)=1/0; rec=a(n+1)=a(n); query=a(2)", "분모 0"),
    ],
)
def test_parser_rejections(conditions: str, needle: str) -> None:
    if needle == "":
        # start=0, upto=0 은 합법 — 이 줄은 '경계 하나는 통과해야 한다'는 대조군이다.
        parse_sequence_model(conditions)
        return
    with pytest.raises(SequenceInductionError, match=needle):
        parse_sequence_model(conditions)
    verdict = verify_sequence_induction(conditions, "1")
    assert verdict.state == "unverifiable"
    assert verdict.tier is None


@pytest.mark.parametrize(
    "rec",
    [
        "a(n)+0.5",  # 소수점 — 분수로 써야 한다
        "__import__('os')",  # 허용 문자 밖
        "nn+1",  # 미지 이름
        "a(n)//2",  # 내림 나눗셈 — 허용 연산자 밖
        "a(n)==1",  # 비교는 if 조건에서만
        "a(n+1)",  # 1단계 점화에서 a(n+1) 참조
        "a(n-1)",  # 허용 인자 아님
        "a(2)",  # 상수 인덱스 참조 금지
        "2^a(n)",  # 지수에는 항 참조 금지
        "if(n>1, 1, 2)",  # 분기 조건은 n%정수==정수만
        "if(n%0==1, 1, 2)",  # 법 0
        "a(n)+(",  # 구문 오류
        "",  # 빈 식
        "f(n)",  # 미지 함수
    ],
)
def test_forbidden_expression_elements_are_rejected(rec: str) -> None:
    conditions = f"init=a(1)=1; rec=a(n+1)={rec}; query=a(2)"
    with pytest.raises(SequenceInductionError):
        parse_sequence_model(conditions)
    assert _state(conditions, "1") == "unverifiable"


def test_closed_form_cannot_reference_terms() -> None:
    """폐형은 n만의 식이다 — 점화식 항 a(...)를 참조하면 순환 정의라 거부한다."""
    bad_closed = "init=a(1)=1; rec=a(n+1)=a(n); query=closed(a(n)=a(n), upto=3)"
    with pytest.raises(SequenceInductionError):
        parse_sequence_model(bad_closed)


def test_conditions_and_expression_length_caps() -> None:
    huge = "init=a(1)=1; rec=a(n+1)=a(n)+" + "1+" * 2000 + "1; query=a(2)"
    with pytest.raises(SequenceRangeError):
        parse_sequence_model(huge)
    long_expr = "init=a(1)=1; rec=a(n+1)=a(n)+" + "1" * 400 + "; query=a(2)"
    with pytest.raises(SequenceRangeError):
        parse_sequence_model(long_expr)


# ──────────────────────────────────────────────────────────────────────────
# 답 형태 — 정수·p/q·목록만, 허용오차 없음
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("answer", ["0.5", "73.0", "약 73", "", "a12", "1/0", "7 3"])
def test_unreadable_answers_are_unverifiable_not_fail(answer: str) -> None:
    verdict = verify_sequence_induction(ARITH, answer)
    assert verdict.state == "unverifiable"
    assert verdict.model is not None  # 모델은 구성됐다 — 답만 읽지 못했다


def test_answer_shape_must_match_query_shape() -> None:
    assert _state(BRANCH_TERMS, "52") == "unverifiable"  # 목록 질의에 스칼라
    assert _state(ARITH, "[73]") == "unverifiable"  # 스칼라 질의에 목록
    assert _state(CLOSED, "5") == "unverifiable"  # closed는 0/1만


def test_tier_follows_query_kind() -> None:
    assert verify_sequence_induction(ARITH, "73").tier is VerificationTier.DETERMINISTIC_DATA
    assert verify_sequence_induction(BRANCH_SUM, "52").tier is VerificationTier.DETERMINISTIC_DATA
    assert verify_sequence_induction(CLOSED, "1").tier is VerificationTier.FINITE_EXHAUSTIVE


def test_residual_axes_by_feature() -> None:
    base = verify_sequence_induction(ARITH, "73").residual_axes
    assert base == ("발문↔점화식 정합", "인덱스 시작점·초기항 완비성")
    assert "분기 조건 해석" in verify_sequence_induction(BRANCH_SUM, "52").residual_axes
    assert "분기 조건 해석" not in base


# ──────────────────────────────────────────────────────────────────────────
# 정확값 직렬화/역직렬화
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("73", Fraction(73)),
        ("  73  ", Fraction(73)),
        ("-5", Fraction(-5)),
        ("3/6", Fraction(1, 2)),
        ("3 / 6", Fraction(1, 2)),
        ("[1, 3, 6]", (Fraction(1), Fraction(3), Fraction(6))),
        ("1, 3, 6", (Fraction(1), Fraction(3), Fraction(6))),
        (["1", "2/3"], (Fraction(1), Fraction(2, 3))),
        (7, Fraction(7)),
    ],
)
def test_parse_exact_value_accepts(raw: object, expected: object) -> None:
    assert parse_exact_value(raw) == expected


@pytest.mark.parametrize(
    "raw", ["0.5", "73.0", 73.0, True, "", "1/0", "[]", [], "1,2,x", None, "7 3"]
)
def test_parse_exact_value_rejects_inexact_or_unreadable(raw: object) -> None:
    assert parse_exact_value(raw) is None


def test_format_exact_value_roundtrip_and_oversize_guard() -> None:
    assert format_exact_value(Fraction(73)) == "73"
    assert format_exact_value(Fraction(3, 2)) == "3/2"
    assert format_exact_value((Fraction(1), Fraction(3, 2))) == "[1, 3/2]"
    assert parse_exact_value(format_exact_value((Fraction(1), Fraction(3, 2)))) == (
        Fraction(1),
        Fraction(3, 2),
    )
    # 4,300자리 직렬화 한도를 넘는 정수는 빈 문자열 — 말없이 잘라 쓰지 않는다.
    assert format_exact_value(Fraction(2**20_000)) == ""


def test_describe_model_names_definition_but_not_the_result() -> None:
    model = parse_sequence_model(ARITH)
    text = describe_sequence_model_ko(model)
    for fragment in ("첫 항 번호는 1", "a(1)=7", "a(n+1) = a(n)+6", "a(12)"):
        assert fragment in text
    assert "73" not in text  # 계산 결과 값은 싣지 않는다(관점 ③은 번역 대조 전용)
    closed = describe_sequence_model_ko(parse_sequence_model(CLOSED))
    assert "3*5^(n-1)" in closed and "1, 아니면 0" in closed


def test_execute_returns_terms_count() -> None:
    result = execute_sequence_model(parse_sequence_model(BRANCH_TERMS))
    assert result.value == tuple(Fraction(x) for x in (1, 3, 6, 8, 16, 18))
    assert result.terms_computed == 6


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 소스 위생 — eval·sympify·isclose·float 연산 금지
# ──────────────────────────────────────────────────────────────────────────
def test_module_source_uses_no_eval_sympify_isclose() -> None:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    # 이름 호출(`eval(...)`)과 속성 호출(`math.isclose(...)`)을 구분한다 — `re.compile(...)`은
    # 정규식 컴파일이라 허용 대상인데 이름만 보면 내장 `compile`로 오탐한다.
    forbidden_names = {"eval", "exec", "compile", "sympify", "parse_expr", "isclose", "float"}
    forbidden_attrs = {"sympify", "parse_expr", "isclose"}
    called_names: set[str] = set()
    called_attrs: set[str] = set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called_names.add(func.id)
            elif isinstance(func, ast.Attribute):
                called_attrs.add(func.attr)
        elif isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not called_names & forbidden_names, called_names & forbidden_names
    assert not called_attrs & forbidden_attrs, called_attrs & forbidden_attrs
    assert not imported & {"sympy", "math", "numpy"}, imported & {"sympy", "math", "numpy"}


# ──────────────────────────────────────────────────────────────────────────
# ⑥ 결함 주입 — 각 축이 실제로 RED로 뒤집힌다
# ──────────────────────────────────────────────────────────────────────────
def _inject(original: str, old: str, new: str) -> tuple[str, str]:
    """`old`를 정확히 1건 `new`로 치환한 (주입본, 원복본)을 돌려준다 — 주입·원복 모두 단언.

    주입이 조용히 실패하면(치환 대상 0건) 정상 입력에 대해 테스트가 돌아 'N passed'가 검출처럼
    보인다. 그래서 치환 대상 실재(count==1)·주입 적용(mutated != original)·원복 바이트 동일을
    하네스 안에서 단언한다.
    """
    assert original.count(old) == 1, f"주입 대상 {old!r}이 {original.count(old)}건"
    mutated = original.replace(old, new)
    assert mutated != original, "주입이 적용되지 않았다"
    restored = mutated.replace(new, old)
    assert restored.encode("utf-8") == original.encode("utf-8"), "원복이 바이트 동일하지 않다"
    return mutated, restored


@pytest.mark.parametrize(
    ("label", "conditions", "answer", "old", "new"),
    [
        ("초기항 오류", ARITH, "73", "a(1)=7", "a(1)=8"),
        ("점화식 계수 오류", ARITH, "73", "a(n)+6", "a(n)+7"),
        ("점화식 곱 계수 오류", CLOSED, "1", "5*a(n)", "6*a(n)"),
        ("인덱스 시작점 오류", ARITH, "73", "init=a(1)=7;", "start=0; init=a(0)=7;"),
        ("홀짝 분기 반전", BRANCH_SUM, "52", "n%2==1", "n%2==0"),
        ("홀짝 분기 같음/다름 반전", BRANCH_SUM, "52", "n%2==1", "n%2!=1"),
        ("2단계 초기항 오류", FIB, "55", "a(2)=1", "a(2)=2"),
    ],
)
def test_injected_defect_flips_pass_to_fail(
    label: str, conditions: str, answer: str, old: str, new: str
) -> None:
    assert _state(conditions, answer) == "pass", f"{label}: 주입 전 기준선이 pass가 아님"
    mutated, restored = _inject(conditions, old, new)
    assert _state(mutated, answer) == "fail", f"{label}: 결함 주입이 RED로 뒤집히지 않았다"
    assert _state(restored, answer) == "pass", f"{label}: 원복 후 기준선이 복구되지 않았다"
