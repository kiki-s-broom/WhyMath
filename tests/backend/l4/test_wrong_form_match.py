"""오개념 거짓 항등식 SymPy 탐지 단위테스트 — Wild 정합·등식 추출·shadow(감사 §7).

`matches_wrong_form`(기호 인스턴스 정합·정답/수치/degenerate 비정합)·`extract_equations`(prose
무관 추출)·`detect_wrong_forms`·`observe_wrong_form_shadow`(off no-op·shadow 로그·never-break·
프라이버시)를 라이브 의존 없이 검증한다. SymPy는 수치(`(3+4)²`)를 평가해 못 잡고 *기호*(`(x+y)²`)를
잡는다는 스코프를 못 박는다.
"""

from __future__ import annotations

import logging

import pytest

from whymath_backend.config import get_settings
from whymath_backend.l4.misconception import wrong_form_match
from whymath_backend.l4.misconception.wrong_form_match import (
    WrongFormShadowObservation,
    detect_wrong_forms,
    extract_equations,
    matches_wrong_form,
    observe_wrong_form_shadow,
)

# distribution-over-power의 canonical_wrong_form(카탈로그 정본과 동일).
_DISTRIBUTION = ("(a+b)**2", "a**2 + b**2")
_RECORD_LOGGER = "whymath.l4.misconception.wrong_form_shadow.record"
_ENV = "WHYMATH_MISCONCEPTION_WRONG_FORM_MODE"


class TestExtractEquations:
    def test_extracts_around_korean_prose(self) -> None:
        eqs = extract_equations("학생 풀이: (x+y)² = x²+y² 이므로 답은...")
        assert ("(x+y)²", "x²+y²") in eqs

    def test_no_equation(self) -> None:
        assert extract_equations("등식이 전혀 없는 한글 문장") == []

    def test_multiple(self) -> None:
        eqs = extract_equations("a = b 그리고 c = d")
        assert ("a", "b") in eqs and ("c", "d") in eqs


class TestMatchesWrongForm:
    def test_symbolic_instance_different_vars(self) -> None:
        # substring이 놓치는 변수명 변이 — SymPy가 잡는 순기여.
        assert matches_wrong_form("(x+y)**2", "x**2+y**2", _DISTRIBUTION) is True
        assert matches_wrong_form("(p+q)**2", "p**2+q**2", _DISTRIBUTION) is True

    def test_unicode_superscript_instance(self) -> None:
        assert matches_wrong_form("(x+y)²", "x²+y²", _DISTRIBUTION) is True

    def test_correct_form_not_matched(self) -> None:
        # 올바른 완전제곱 → 거짓 규칙 아님(기대 거짓 rhs와 동치 아님).
        assert matches_wrong_form("(x+y)**2", "x**2+2*x*y+y**2", _DISTRIBUTION) is False

    def test_numeric_instance_matched(self) -> None:
        # evaluate=False 구조 보존 → 수치 인스턴스도 잡는다(regex_signals 일반화).
        assert matches_wrong_form("(3+4)**2", "3**2+4**2", _DISTRIBUTION) is True

    def test_numeric_correct_answer_not_matched(self) -> None:
        # (3+4)²=49는 올바른 값 → 기대 거짓 rhs(25)와 불일치 → 미정합.
        assert matches_wrong_form("(3+4)**2", "49", _DISTRIBUTION) is False

    def test_numeric_coincidental_true_not_matched(self) -> None:
        # (3+0)²=3²+0²=9는 *우연히 참* → 거짓 등식 가드가 제외(거짓 낙인 차단·RS2).
        assert matches_wrong_form("(3+0)**2", "3**2+0**2", _DISTRIBUTION) is False

    def test_garbage_not_matched(self) -> None:
        assert matches_wrong_form("선생님", "안녕", _DISTRIBUTION) is False

    def test_degenerate_constant_template_not_matched(self) -> None:
        # a**0 → 1(상수 평가·구조 소실) → 구조 정합 불가(거짓 주장 금지).
        assert matches_wrong_form("x**0", "0", ("a**0", "0")) is False


# (암묵 곱셈 lhs, rhs, 같은 수학의 명시 곱셈 lhs, rhs, 기대 판정, 라벨) — MISC-33.
# 쌍둥이는 **같은 판정**을 받아야 한다. 기대 판정이 True인 행은 거짓 규칙의 인스턴스이고, False인
# 행은 낙인이 없어야 하는 대조군이다(정답·무관 오답·항등).
_TWINS: list[tuple[str, str, str, str, bool, str]] = [
    ("(2x+3)²", "4x²+9", "(2*x+3)²", "4*x²+9", True, "핵심 사례: 계수 병치"),
    ("(3y+1)²", "9y²+1", "(3*y+1)²", "9*y²+1", True, "다른 변수·계수"),
    ("(x+2y)²", "x²+4y²", "(x+2*y)²", "x²+4*y²", True, "두 번째 항의 계수"),
    ("(2x+3y)²", "4x²+9y²", "(2*x+3*y)²", "4*x²+9*y²", True, "두 항 모두 계수"),
    ("(sin(x)+2x)²", "sin(x)²+4x²", "(sin(x)+2*x)²", "sin(x)²+4*x²", True, "내장 함수 + 계수"),
    ("(2x+3)²", "4x²+12x+9", "(2*x+3)²", "4*x²+12*x+9", False, "올바른 전개 — 낙인 금지"),
    ("(2x+3)²", "4x²+10", "(2*x+3)²", "4*x²+10", False, "무관한 오답"),
    ("(2x+3)²", "(2x+3)(2x+3)", "(2*x+3)²", "(2*x+3)*(2*x+3)", False, "항등 — 가드 ⓪"),
]


class TestImplicitMultiplication:
    """암묵 곱셈(`2x`)과 명시 곱셈(`2*x`)은 같은 수학이므로 같은 판정을 받는다 (MISC-33).

    과거엔 같은 함수 안에서 ⓪ 가드(`identity_status` — `2x`를 읽음)와 ① 구조 정합(`safe_sympify
    (convert_xor=True)` — 암묵 곱셈 변환 없음)이 서로 다른 변환 규칙으로 파싱해, 계수가 붙은
    거짓 규칙 인스턴스가 통째로 미검출이었다. 파서 정의를 동치 권위(`parse_unevaluated`)로
    일원화해 닫았고, 단언의 형태가 쌍둥이 동등이라는 점이 요점이다.
    """

    @pytest.mark.parametrize(
        ("lhs_i", "rhs_i", "lhs_e", "rhs_e", "expected", "label"),
        _TWINS,
        ids=[t[-1] for t in _TWINS],
    )
    def test_twin_notations_get_the_same_verdict(
        self, lhs_i: str, rhs_i: str, lhs_e: str, rhs_e: str, expected: bool, label: str
    ) -> None:
        assert matches_wrong_form(lhs_e, rhs_e, _DISTRIBUTION) is expected, f"명시: {label}"
        assert matches_wrong_form(lhs_i, rhs_i, _DISTRIBUTION) is expected, f"암묵: {label}"

    def test_detect_wrong_forms_reads_implicit_multiplication(self) -> None:
        # 등식 추출 → 정합까지 전 경로로 — 발문이 아니라 학생 풀이 텍스트에서도 잡힌다.
        assert detect_wrong_forms("(2x+3)² = 4x²+9") == ["distribution-over-power"]
        assert detect_wrong_forms("(2x+3)² = 4x²+12x+9") == []

    def test_unknown_function_application_known_limitation(self) -> None:
        """**알려진 한계(숨기지 않는다)**: 미지 함수 `f(x)`를 이항식에 품은 거짓형은 더는 안 잡힌다.

        MISC-33 이전에는 `(f(x)+y)² = f(x)²+y²`가 잡혔다 — 구조 파싱이 `f(x)`를 함수로 읽고,
        오른쪽 비교는 동치 권위가 같은 문자열을 같은 방식(`f*x**2`)으로 읽어 **우연히** 일치했기
        때문이다. 구조 파싱을 동치 권위와 같은 규칙으로 맞추자 구조 쪽이 `(f*x + y)**2`로 읽혀
        기대 우변이 `f**2*x**2 + y**2`로 재직렬화되고, 학생 우변(`f*x**2 + y**2`)과 어긋난다.
        뿌리는 동치 권위가 `f(x)`를 곱으로 읽는 것(`MISC-62`)이며, 여기서 구조 파싱만 `f(x)`를
        함수로 읽게 하면 같은 함수 안에서 두 읽기가 다시 갈린다(MISC-33이 닫으려던 바로 그 갈림).

        누락 방향이라 거짓 낙인은 없다 — 아래 올바른 전개 대조군이 이를 보인다. 내장 함수(`sin`)는
        영향이 없다. 이 단언은 *현재 동작*의 동결이며 `MISC-62`가 고치면 `True`로 뒤집힌다.
        """
        assert matches_wrong_form("(f(x)+y)²", "f(x)²+y²", _DISTRIBUTION) is False
        # 대조군 ①: 내장 함수는 그대로 잡힌다 — 한계가 *미지 이름*에 한정됨.
        assert matches_wrong_form("(sin(x)+cos(x))²", "sin(x)²+cos(x)²", _DISTRIBUTION) is True
        # 대조군 ②: 올바른 전개는 어느 쪽이든 낙인이 없다.
        assert matches_wrong_form("(f(x)+y)²", "f(x)²+2f(x)y+y²", _DISTRIBUTION) is False


class TestDetectWrongForms:
    def test_detects_distribution_symbolic(self) -> None:
        assert detect_wrong_forms("(x+y)² = x²+y²") == ["distribution-over-power"]

    def test_correct_solution_no_detection(self) -> None:
        assert detect_wrong_forms("(x+y)² = x²+2xy+y²") == []

    def test_no_equation_no_detection(self) -> None:
        assert detect_wrong_forms("등식 없는 서술") == []


class TestObserveWrongFormShadow:
    def test_off_is_noop(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv(_ENV, "off")
        get_settings.cache_clear()
        try:
            with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
                observe_wrong_form_shadow("(x+y)² = x²+y²")
            assert [r for r in caplog.records if r.name == _RECORD_LOGGER] == []
        finally:
            get_settings.cache_clear()

    def test_shadow_logs_sympy_only(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv(_ENV, "shadow")
        get_settings.cache_clear()
        try:
            with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
                observe_wrong_form_shadow("(x+y)² = x²+y²")
            records = [r.getMessage() for r in caplog.records if r.name == _RECORD_LOGGER]
            assert len(records) == 1
            obs = WrongFormShadowObservation.model_validate_json(records[0])
            # substring은 변수명 변이를 놓치고 SymPy만 잡는다(순기여).
            assert "distribution-over-power" in obs.sympy_detected_ids
            assert "distribution-over-power" in obs.sympy_only_ids
        finally:
            get_settings.cache_clear()

    def test_shadow_never_breaks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_ENV, "shadow")
        get_settings.cache_clear()

        def _boom(_text: str) -> list[str]:
            raise RuntimeError("탐지 실패")

        monkeypatch.setattr(wrong_form_match, "detect_wrong_forms", _boom)
        try:
            # 예외 전파 0(반환 None) — 본류(코칭) 보호.
            observe_wrong_form_shadow("(x+y)² = x²+y²")
        finally:
            get_settings.cache_clear()

    def test_record_has_no_student_text(self) -> None:
        # extra='forbid'·모델 필드 한정 — 학생 풀이 원문이 구조적으로 못 들어간다(미성년 PII).
        obs = WrongFormShadowObservation(
            sympy_detected_ids=["distribution-over-power"],
            substring_detected_ids=[],
            sympy_only_ids=["distribution-over-power"],
        )
        keys = set(obs.model_dump().keys())
        assert keys == {
            "sympy_detected_ids",
            "substring_detected_ids",
            "sympy_only_ids",
            "observed_at",
        }
