"""기호 항등성 primitive 단위테스트 — `identity_status` 4상태(동치 권위 단일·감사 §7).

`verify_step`이 위임하는 SymPy 관용구를 *직접* 검증한다 — identity(항등 확정)·not_identity(거짓
증명)·undecidable(정의역 의존·초월·미결정)·parse_error(빈/파싱 불가). 카탈로그
`canonical_wrong_form` 무결성과 verify_step 3상태가 *같은 권위*를 거치게 됐음을 못 박는다.
MATH-03: `identity_status_detail`(undecidable 변수 불일치 라벨·status 위임 정합) 추가.
"""

from __future__ import annotations

import pytest
import sympy

from whymath_backend.l3.safe_parse import UnsafeExpressionError
from whymath_backend.l3.symbolic_equivalence import (
    IdentityVerdict,
    identity_status,
    identity_status_detail,
    parse_unevaluated,
    to_sympy_source,
)


class TestIdentity:
    @pytest.mark.parametrize(
        ("lhs", "rhs"),
        [
            ("2*(x+1)", "2*x + 2"),  # 다항 항등식(자유변수 OK)
            ("(a+b)**2", "a**2 + 2*a*b + b**2"),  # 완전제곱(올바른 전개)
            ("sin(x)**2 + cos(x)**2", "1"),  # 삼각 항등식(비다항·simplify 보강)
            ("x^2", "x*x"),  # convert_xor=True → ^=거듭제곱
        ],
    )
    def test_identity(self, lhs: str, rhs: str) -> None:
        assert identity_status(lhs, rhs) is IdentityVerdict.identity


class TestNotIdentity:
    @pytest.mark.parametrize(
        ("lhs", "rhs"),
        [
            ("(a+b)**2", "a**2 + b**2"),  # freshman's dream(diff=2ab·다항 비항등)
            ("a**0", "0"),  # a**0=1 ≠ 0(상수 차)
            ("2 + 3", "6"),  # 수치 오답(상수 차 확정)
            ("x + 1", "x + 2"),  # 같은 변수 다항 비항등
        ],
    )
    def test_not_identity(self, lhs: str, rhs: str) -> None:
        assert identity_status(lhs, rhs) is IdentityVerdict.not_identity


class TestUndecidable:
    @pytest.mark.parametrize(
        ("lhs", "rhs"),
        [
            ("sqrt(x**2)", "x"),  # 정의역 의존(|x| vs x) — 가정 없이 미결정
            ("log(a+b)", "log(a) + log(b)"),  # 초월·미결정
        ],
    )
    def test_undecidable(self, lhs: str, rhs: str) -> None:
        assert identity_status(lhs, rhs) is IdentityVerdict.undecidable


class TestParseError:
    @pytest.mark.parametrize(
        ("lhs", "rhs"),
        [
            ("", "x"),  # 빈 입력
            ("x", "   "),  # 공백
            ("2 +* 3", "5"),  # 파싱 불가(SympifyError)
        ],
    )
    def test_parse_error(self, lhs: str, rhs: str) -> None:
        assert identity_status(lhs, rhs) is IdentityVerdict.parse_error


class TestIdentityStatusDetail:
    """MATH-03 — `identity_status_detail`: 같은 판정 + undecidable 변수 불일치 라벨.

    라벨은 판정이 *이미 계산하던* `is_poly`·`same_symbols` 불리언의 노출이다(신규 판정 0).
    `identity_status`는 이 함수에 위임하므로 두 반환의 verdict가 갈리면 판정 이원화다.
    """

    def test_substitution_labelled_variable_mismatch(self) -> None:
        # 치환 맥락(a vs b+1) — 다항 + 자유변수 집합 불일치 → undecidable + 라벨 True.
        detail = identity_status_detail("a", "b+1")
        assert detail.verdict is IdentityVerdict.undecidable
        assert detail.variable_mismatch is True

    def test_nonpoly_undecidable_not_labelled(self) -> None:
        # 비다항 미결정(sqrt(x²) vs x·같은 변수) — 변수와 무관한 미결정이므로 라벨 False.
        detail = identity_status_detail("sqrt(x**2)", "x")
        assert detail.verdict is IdentityVerdict.undecidable
        assert detail.variable_mismatch is False

    def test_nonpoly_same_symbols_transcendental_not_labelled(self) -> None:
        # 초월 미결정(log) — 양변 변수 집합이 같아 라벨 False(일반 undecidable).
        detail = identity_status_detail("log(a+b)", "log(a) + log(b)")
        assert detail.verdict is IdentityVerdict.undecidable
        assert detail.variable_mismatch is False

    @pytest.mark.parametrize(
        ("lhs", "rhs"),
        [
            ("2*(x+1)", "2*x + 2"),  # identity
            ("(a+b)**2", "a**2 + b**2"),  # not_identity
            ("2 +* 3", "5"),  # parse_error
        ],
    )
    def test_decisive_and_parse_error_not_labelled(self, lhs: str, rhs: str) -> None:
        # 라벨은 undecidable 전용 — 확정 판정·파싱 실패는 항상 False.
        assert identity_status_detail(lhs, rhs).variable_mismatch is False

    @pytest.mark.parametrize(
        ("lhs", "rhs"),
        [
            ("2*(x+1)", "2*x + 2"),
            ("(a+b)**2", "a**2 + b**2"),
            ("sqrt(x**2)", "x"),
            ("a", "b+1"),
            ("", "x"),
            ("2 +* 3", "5"),
        ],
    )
    def test_status_delegates_to_detail(self, lhs: str, rhs: str) -> None:
        # 위임 동결 — 4상태 계약 불변(status ≡ detail.verdict).
        assert identity_status(lhs, rhs) is identity_status_detail(lhs, rhs).verdict


class TestSuperscriptNormalization:
    """유니코드 위첨자 정규화 — `identity_status`가 `to_sympy_source`를 내부 적용(감사 §7 해소).

    과거엔 위첨자 치환이 L4에만 있어 `identity_status`가 `x²`를 parse_error로 떨궜다 — 이제 동치
    권위가 위첨자를 직접 정규화하므로 학생 손글씨·MathLive 위첨자 입력이 올바로 판정된다.
    """

    def test_superscript_identity(self) -> None:
        # `x²` 위첨자가 `x**2`와 항등(과거엔 parse_error였음 — strict 개선).
        assert identity_status("x²", "x**2") is IdentityVerdict.identity

    def test_superscript_expansion_identity(self) -> None:
        assert identity_status("(a+b)²", "a²+2*a*b+b²") is IdentityVerdict.identity

    def test_superscript_freshman_dream_not_identity(self) -> None:
        # (a+b)² ≠ a²+b² — 위첨자 입력도 거짓이 *증명*된다(같은 변수 0-아닌 다항).
        assert identity_status("(a+b)²", "a²+b²") is IdentityVerdict.not_identity

    def test_to_sympy_source_maps_all_digits_and_strips(self) -> None:
        assert to_sympy_source("  x²  ") == "x**2"
        assert to_sympy_source("a⁵+b⁰") == "a**5+b**0"

    def test_to_sympy_source_idempotent_on_ascii(self) -> None:
        # 이미 ASCII면 무변화(멱등) — caret(^)은 건드리지 않는다(convert_xor 담당).
        assert to_sympy_source("x**2 + 3") == "x**2 + 3"
        assert to_sympy_source("x^2") == "x^2"


class TestUnicodeOperatorNormalization:
    """비ASCII 수학 연산자(−·×·÷) 정규화 — S3-06 실측 동결(이미 `_OPERATOR_MAP`이 처리).

    2026-07-19 자연 사용 재측정에서 학생 제출이 U+2212 마이너스를 담았다 — `to_sympy_source`가
    이를 ASCII로 접음을 실측 확인했고(추가 구현 불요), 회귀 방지를 위해 여기 동결한다.
    """

    def test_unicode_minus_folded(self) -> None:
        # U+2212 MINUS SIGN → ASCII 하이픈(실측: Kiki 제출 원문 표기).
        assert to_sympy_source("x−2") == "x-2"

    def test_unicode_multiplication_division_folded(self) -> None:
        # U+00D7(×) → * · U+00F7(÷) → /.
        assert to_sympy_source("2×x") == "2*x"
        assert to_sympy_source("6÷2") == "6/2"

    def test_unicode_minus_identity_judged(self) -> None:
        # 정규화 경유로 동치 판정까지 도달 — x−2 ≡ x-2.
        assert identity_status("x−2", "x-2") is IdentityVerdict.identity


class TestParseUnevaluated:
    """`parse_unevaluated` — 동치 권위가 소유한 *구조 보존* 파서 (MISC-33).

    구조 정합(오개념 거짓형 Wild 매칭)은 계산 없는 파싱이 필요한데, 그 자리가 변환 규칙이 다른
    `safe_sympify(convert_xor=True)`를 직접 불러 `identity_status`가 읽는 `2x`를 거부했다. 이
    클래스는 (1) 구조가 보존되고 (2) 암묵 곱셈을 읽으며 (3) 동치 권위와 같은 규칙이고 (4) 안전
    진입점을 거침을 동결한다.
    """

    def test_keeps_structure_instead_of_evaluating(self) -> None:
        # (3+4)**2 가 49로 접히면 수치 인스턴스의 구조 정합이 불가능해진다.
        expr = parse_unevaluated("(3+4)**2")
        assert isinstance(expr, sympy.Pow)
        assert isinstance(expr.base, sympy.Add)
        assert expr != 49

    @pytest.mark.parametrize(
        ("implicit", "explicit"),
        [
            ("2x", "2*x"),  # 계수 병치
            ("3(x+1)", "3*(x+1)"),  # 계수 + 괄호
            ("(x+1)(x-1)", "(x+1)*(x-1)"),  # 괄호 병치
            ("4x**2", "4*x**2"),  # 위첨자 뒤 병치
            ("(2x+3)**2", "(2*x+3)**2"),  # MISC-33 핵심 사례
            ("x y", "x*y"),  # 공백 병치
        ],
    )
    def test_implicit_multiplication_reads_as_its_explicit_twin(
        self, implicit: str, explicit: str
    ) -> None:
        """같은 수학의 두 표기는 **구조까지 같은** 식으로 읽힌다(srepr 동일)."""
        assert sympy.srepr(parse_unevaluated(implicit)) == sympy.srepr(parse_unevaluated(explicit))

    @pytest.mark.parametrize(
        "raw", ["(2x+3)²", "2(x+1)", "(x+1)(x-1)", "x²y", "3x+4y", "(3+4)^2"]
    )
    def test_same_rules_as_the_equivalence_parser(self, raw: str) -> None:
        """구조 보존 파서의 결과를 동치 권위에 되먹이면 원문과 항등이다 — 변환 규칙이 같다는 증거.

        두 파서가 규칙이 갈리면(과거의 `safe_sympify` 직접 호출) 한쪽이 거부하거나 다른 식으로
        읽어 이 단언이 깨진다. `f(x)` 계열은 MISC-62가 소유하므로 여기서 제외한다.
        """
        src = to_sympy_source(raw)
        assert identity_status(str(parse_unevaluated(src)), raw) is IdentityVerdict.identity

    @pytest.mark.parametrize("hostile", ["9**9**9", "x**(10**10)", "__import__('os')", "exec('1')"])
    def test_still_goes_through_the_safe_entrypoint(self, hostile: str) -> None:
        """학생 원문이 닿는 자리라 안전 진입점(CONST-09)을 거친다 — 위험 입력은 거부된다."""
        with pytest.raises(UnsafeExpressionError):
            parse_unevaluated(hostile)


class TestToSympySourceDoesNotInsertMultiplication:
    """`to_sympy_source`는 표기 정규화이지 파서가 아니다 — 곱셈 기호를 넣지 않는다 (MISC-33).

    MISC-33 착수 시 가설은 "`to_sympy_source`가 `2x`를 `2*x`로 전개해야 한다"였으나, 실측은 정반대를
    보였다 — `identity_status`는 이미 파싱 단계(`_PARSE_TRANSFORMS`)에서 암묵 곱셈을 읽고, 깨지던
    곳은 *다른 변환 규칙으로 파싱하던 호출처* 하나였다. 이 동결은 소비처 전건(`verify_step`·
    `verify_final_answer`·`solution_set`·`slot_generator` 등)이 받는 문자열이 이 변경으로 바뀌지
    않았음을 기계로 남긴다 — 문자열 층에서 `*`를 끼우면 `f(x)`·`2pi` 같은 입력에서 소비처 전체의
    판정이 한꺼번에 움직인다.
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("(2x+3)²", "(2x+3)**2"),
            ("2x", "2x"),
            ("3(x+1)", "3(x+1)"),
            ("４ｘ", "4x"),  # 전각 → ASCII 는 하되 곱셈은 넣지 않는다
        ],
    )
    def test_no_star_is_inserted(self, raw: str, expected: str) -> None:
        assert to_sympy_source(raw) == expected

    def test_idempotent(self) -> None:
        once = to_sympy_source("(2x+3)²")
        assert to_sympy_source(once) == once


def test_function_application_is_read_as_multiplication_known_limitation() -> None:
    """**알려진 한계(숨기지 않는다)**: 동치 권위가 미지 함수 적용 `f(x)`를 곱 `f*x`와 같다고 본다.

    MISC-33 실측(2026-10-08). `_PARSE_TRANSFORMS`의 `auto_symbol`이 만든 `Function('f')`를
    `implicit_multiplication`이 "함수 뒤 괄호"로 보고 `*`를 끼우는 상호작용으로 보인다. 연산자
    우선순위까지 어긋나 `f(x)**2`는 `(f*x)**2`가 아니라 `f*x**2`로 읽힌다. 내장 함수(`sin`)는
    영향이 없다 — 이름이 함수로 등록돼 있기 때문이다.

    이 테스트가 존재하는 이유는 *지금 구별하지 못한다*를 계약으로 박아 두기 위해서다(EOS-104가
    암묵 곱셈 한계를 동결한 것과 같은 방식). 고치면 이 테스트가 RED가 되고 승계 지점이 기계로
    남는다. 승계 태스크: `MISC-62-function-application-read-as-multiplication` — 고칠 때는 이
    단언을 *구별한다*로 뒤집고, `tests/backend/l4/test_wrong_form_match.py`의
    `test_unknown_function_application_known_limitation`도 함께 뒤집는다.
    """
    assert identity_status("f(x)", "f*x") is IdentityVerdict.identity
    assert identity_status("f(x)**2", "f*x**2") is IdentityVerdict.identity
    # 대조군: 내장 함수는 곱으로 읽히지 않는다 — 한계가 *미지 이름*에 한정됨을 보인다.
    assert identity_status("sin(x)", "sin*x") is IdentityVerdict.parse_error

