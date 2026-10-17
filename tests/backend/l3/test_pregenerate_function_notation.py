"""위생 검증기 함수 표기 오탐 동결 — QUAL-13 (P3-03 2회차 감사 교정 중 부수 발견).

실측 사고(2026-10-07): 미분 문항 은행 재생성에서 73건이 거부됐다. 원인은 두 갈래다.

- **산술·부등식·부등 검증기** — `f'(2) = 5`에서 `'`가 "더 큰 식의 일부" 신호로 인정되지 않아
  함수 적용 `f'(2)`의 괄호 `(2)`만 떼어 `(2) = 5`라는 거짓 등식으로 판정했다.
- **해 주장 검증기** — `f(1) = -7`·`f(2) = 5`의 `f(2)`를 `2·f`(곱셈)로 읽어 "f의 해는 5/2인데
  3이라 주장했다"고 판정했다. 함수 적용과 곱셈은 글자만으로 갈리지 않으므로 *판별 규칙*이 필요하다.

이 파일은 ① 함수 표기가 거부되지 않음(RED였던 것) ② 진짜 거짓 산술·곱셈 해석은 *계속* 거부됨
(대조군 — 과잉 수정이 통과하지 않도록)을 함께 동결한다. 대조군 없는 "통과" 테스트는 모든 입력에
초록인 가드와 화면이 같다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l3.pregenerate import (
    SymPyArithmeticValidator,
    SymPyInequalityValidator,
    SymPyNotEqualValidator,
    SymPySolutionValidator,
    default_seed_validator,
    detect_step_breaks,
)

# ──────────────────────────────────────────────────────────────────────────
# ① 함수 적용 표기 — 거부되면 안 된다 (수정 전 RED)
# ──────────────────────────────────────────────────────────────────────────
# 산술 검증기가 오탐하던 형태: 함수 기호 뒤 꼬리 문자(' ′ ’ ` })가 `(`에 붙어 있다.
_PRIME_APPLICATIONS = [
    "f'(2) = 5",  # 과제 원문 사례 — "'(2) = 5"로 읽혀 거부됐다
    "f'(2) = 5이므로 접선의 기울기는 5이다.",
    "f''(1) = 0이다.",  # 이계도함수
    "y'(0) = 2",
    "f′(2) = 5",  # U+2032 PRIME
    "f’(2) = 5",  # U+2019 오른쪽 작은따옴표 (LLM·워드프로세서가 자주 쓴다)
    "f^{-1}(2) = 3",  # 역함수 — `}` 꼬리
    "f_{n}(2) = 4",  # 아래첨자 함수
    "f(1) = -7이고 f'(1) = 0이다.",  # 두 표기가 한 문장에
    "f'(2) + f'(3) = 8",  # 연산자로 이어진 함수 값의 합
]


@pytest.mark.parametrize("text", _PRIME_APPLICATIONS)
def test_arithmetic_validator_ignores_function_application(text: str) -> None:
    assert SymPyArithmeticValidator().validate(None, text) is None


@pytest.mark.parametrize(
    "text",
    [
        "f'(2) < 1",  # "(2) < 1"로 읽혀 거짓 부등식 판정되던 형태
        "f''(0) >= 3",
        "g'(5) ≤ 4",
        "f′(1) > 9",
    ],
)
def test_inequality_validator_ignores_function_application(text: str) -> None:
    assert SymPyInequalityValidator().validate(None, text) is None


@pytest.mark.parametrize(
    "text",
    [
        "f'(3) != 3",  # "(3) != 3" — 같은 값이라 거짓 부등으로 판정되던 형태
        "f'(3) ≠ 3",
        "g''(2) ≠ 2",
    ],
)
def test_not_equal_validator_ignores_function_application(text: str) -> None:
    assert SymPyNotEqualValidator().validate(None, text) is None


# 해 주장 검증기가 오탐하던 형태: 한 글자 함수 기호 + 곧바로 `(` (인수에 그 글자가 없다).
_SOLUTION_APPLICATIONS = [
    "f(1) = 3, f(2) = 5",  # f(2)를 2·f로 읽어 f=5/2 vs 주장 f=3
    "f(1) = -7이고 f(2) = 5이다.",
    "x(1) = 4, x(2) = 7",  # 위치 함수 x(t) — 변수 이름이 아니라 함수다
    "g(0) = 1이고 g(3) = 10이다.",
    "F(1) = 2이고 F(2) = 6이다.",  # 대문자 함수 기호
    "f'(x) = 2x이고 x = 3일 때 f'(3) = 6이다.",  # (x) = 2x 가 x=0으로 풀려 주장 x=3과 충돌
    "g''(t) = 6t이고 t = 2일 때 g''(2) = 12이다.",
    "3 = f(1)이고 5 = f(2)이다.",  # 함수 적용이 *우변*에만 있다 — 좌변만 보면 5 = 2f로 읽혀 f=3과 충돌
]


@pytest.mark.parametrize("text", _SOLUTION_APPLICATIONS)
def test_solution_validator_ignores_function_application(text: str) -> None:
    assert SymPySolutionValidator().validate(None, text) is None


def test_step_breaks_ignore_function_application() -> None:
    """단계 진단(shadow)도 같은 관계 추출기를 쓴다 — 함수 값 나열을 '해집합 이탈'로 보지 않는다."""
    assert detect_step_breaks("f(1) = 3 따라서 f(2) = 5") == []


def test_default_chain_accepts_original_notation_of_avoided_phrasing() -> None:
    """P3-03 생성기가 오탐을 피하려 바꿨던 문면을 *원래 표기*로 되돌려도 체인이 통과시킨다.

    회피 문면: "f'(2)의 값은 5" · "x = 1에서 극솟값 -7". 원래 표기: "f'(2) = 5" · "f(1) = -7".
    """
    chain = default_seed_validator()
    originals = [
        "f(x) = x^2 + 1이므로 f'(x) = 2x이다. 따라서 f'(2) = 4이다.",
        "f'(x) = 0에서 x = 1이고 f(1) = -7이므로 극솟값은 -7이다.",
        "f(2) = 5이고 f'(2) = 5이므로 접선의 방정식은 y = 5x - 5이다.",
        "f(1) = -7, f(2) = 5, f'(1) = 0, f'(2) = 5이다.",
    ]
    for text in originals:
        assert chain.validate(None, text) is None, text


# ──────────────────────────────────────────────────────────────────────────
# ② 대조군 — 진짜 거짓 산술·곱셈 해석은 수정 뒤에도 거부된다
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text",
    [
        "2 + 3 = 6",  # 순수 거짓 산술
        "(2) = 5",  # 단독 괄호 거짓 등식 — 꼬리 문자가 없으면 함수 적용이 아니다
        "계산하면 (2) = 5이다.",  # 한글 산문에 인접한 단독 괄호
        "3 × (2) = 7",  # 곱셈 산술
        "식 '(2) = 5'는 거짓이다.",  # 공백 뒤 여는 따옴표 — 프라임이 아니라 인용부호(앞 글자가 영숫자 아님)
        "‘함수’(2) = 5",  # 한글 뒤 닫는 curly quote — 산문 경계지 함수 기호가 아니다
        "함수 f'(2) = 5이고 2 + 3 = 6이다.",  # 함수 표기가 뒤따르는 *진짜* 오류를 가리면 안 된다
        "2 + 3 = 6이고 f'(2) = 5이다.",  # 순서를 바꿔도 마찬가지
    ],
)
def test_arithmetic_validator_still_rejects_false_arithmetic(text: str) -> None:
    signal = SymPyArithmeticValidator().validate(None, text)
    assert signal is not None
    assert signal.kind == "arithmetic"


def test_inequality_validator_still_rejects_false_inequality() -> None:
    assert SymPyInequalityValidator().validate(None, "5 < 3") is not None
    assert SymPyInequalityValidator().validate(None, "(2) < 1") is not None  # 꼬리 없는 단독 괄호
    assert SymPyInequalityValidator().validate(None, "f'(2) < 5이고 7 < 4이다.") is not None


def test_not_equal_validator_still_rejects_false_not_equal() -> None:
    assert SymPyNotEqualValidator().validate(None, "8 != 8") is not None
    assert SymPyNotEqualValidator().validate(None, "(3) != 3") is not None  # 꼬리 없는 단독 괄호
    assert SymPyNotEqualValidator().validate(None, "f'(3) != 3이고 12/4 ≠ 3이다.") is not None


@pytest.mark.parametrize(
    "text",
    [
        "2x + 1 = 7 이므로 x = 5",  # 기본 대수 슬립
        "x(x + 1) = 6 이므로 x = 5",  # 인수에 같은 글자 → 곱셈 해석 유지 (근 2, -3)
        "2(x + 1) = 6 이므로 x = 5",  # 숫자 계수 + 괄호 → 곱셈 (정해 2)
        "2x(1 + 1) = 8 이므로 x = 5",  # 계수 뒤 한 글자+괄호 — 인수에 x가 없어도 함수가 아니라 곱 (정해 2)
        "x((2 + 1)x) = 9 이므로 x = 5",  # 인수가 중첩 괄호 — 첫 ')'에서 끊으면 x를 놓쳐 함수로 오인한다
        "f(1) = 3이고 2x + 1 = 7 이므로 x = 5",  # 함수 표기가 곁에 있어도 진짜 슬립은 잡는다
        "2x + 1 = 7 이므로 x = 5이고 f'(x) = 2x이다.",  # 순서를 바꿔도 마찬가지
    ],
)
def test_solution_validator_still_rejects_wrong_solution(text: str) -> None:
    signal = SymPySolutionValidator().validate(None, text)
    assert signal is not None
    assert signal.kind == "solution"


def test_default_chain_still_rejects_when_function_notation_is_present() -> None:
    chain = default_seed_validator()
    assert chain.validate(None, "f'(2) = 5이고 f(1) = -7이다. 그런데 3 × 4 = 11이다.") is not None
