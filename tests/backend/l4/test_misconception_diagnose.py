"""오개념 진단 매처 단위테스트 — top-K · confidence · 동률 안정 정렬."""

from __future__ import annotations

import re

from whymath_backend.harness import explicit_correction_gap_eval as gap_eval
from whymath_backend.l4.misconception import (
    MisconceptionMatch,
    correct_form_present,
    diagnose,
)
from whymath_backend.l4.misconception.catalog import (
    CATALOG,
    CATALOG_BY_ID,
    ZERO_ROOT_MENTION,
)
from whymath_backend.l4.misconception.diagnose import (
    _normalize,
    _signal_hit,
    classify_correction_attribution,
)
from whymath_backend.l4.misconception.match_gate import apply_match_quality_gate
from whymath_backend.l4.misconception.models import Misconception


class TestSingleMatch:
    def test_full_signal_co_occurrence_confidence_1(self) -> None:
        # distribution-over-power: signals=("(a+b)", "a² + b²")
        text = "내 풀이는 (a+b)² = a² + b²로 전개했어"
        matches = diagnose(text)
        assert len(matches) >= 1
        top = matches[0]
        assert top.misconception.id == "distribution-over-power"
        assert top.confidence == 1.0
        assert set(top.matched_signals) == {"(a+b)", "a² + b²"}

    def test_partial_match_lower_confidence(self) -> None:
        # 두 signal 중 하나만 — 0.5
        text = "(a+b)² 까지만 적었어"
        matches = diagnose(text)
        ids = {m.misconception.id for m in matches}
        assert "distribution-over-power" in ids
        m = next(x for x in matches if x.misconception.id == "distribution-over-power")
        assert m.confidence == 0.5

    def test_no_match_returns_empty(self) -> None:
        assert diagnose("그냥 자연스러운 풀이") == []
        assert diagnose("") == []

    def test_suneung_trig_period_entry_matches(self) -> None:
        # 신규 수능 항목(삼각함수)이 매처를 통과하는지 — period-of-scaled-sine
        text = "y=sin(2x)의 주기는 2π 라고 적었어"
        matches = diagnose(text)
        top = matches[0]
        assert top.misconception.id == "period-of-scaled-sine"
        assert top.confidence == 1.0
        assert top.misconception.domain == "삼각함수"

    def test_suneung_sine_distribution_full_match(self) -> None:
        # sin(a+b) = sin a + sin b — 신규 삼각함수 오개념 풀 매칭
        matches = diagnose("sin(a+b) = sin a + sin b 로 풀었어")
        top = matches[0]
        assert top.misconception.id == "sine-distributes-over-sum"
        assert top.confidence == 1.0


class TestCorrectFormPresent:
    """`correct_form_present` — 검증 풀이에 오개념의 *정정 형태*가 나타나는지(정밀 반박 신호).

    `signals`와 동일한 `_normalize`(NFKC+공백제거)로 흡수하므로 공백·위첨자 표기 변이에 불변.
    `correct_form`이 None인 오개념·정정 부재 텍스트는 False(기존 약한 반박 동작 보존).
    """

    _DISTRIBUTION = CATALOG_BY_ID[
        "distribution-over-power"
    ]  # correct_form="(a+b)² = a² + 2ab + b²"

    def test_detected_when_present(self) -> None:
        assert correct_form_present(self._DISTRIBUTION, "전개하면 (a+b)² = a² + 2ab + b²")

    def test_notation_invariant_spacing_and_superscript(self) -> None:
        # 공백 변이·위첨자 `²`↔평문 `2`(NFKC)에 불변 — 같은 정규형으로 흡수.
        assert correct_form_present(self._DISTRIBUTION, "  (a+b)2  =  a2 + 2 a b + b2  ")

    def test_absent_when_only_wrong_form(self) -> None:
        # 틀린 형태만 있는 풀이엔 정정 형태가 없음 → False(약한 경로로 빠짐).
        assert not correct_form_present(self._DISTRIBUTION, "(a+b)² = a² + b²")

    def test_none_correct_form_disabled(self) -> None:
        # correct_form 미부여 오개념(예: sign-flip-in-inequality)은 항상 False.
        none_cf = CATALOG_BY_ID["sign-flip-in-inequality"]
        assert none_cf.correct_form is None
        assert not correct_form_present(none_cf, none_cf.canonical_statement)

    def test_empty_normalized_form_not_whole_match(self) -> None:
        # 정규형이 빈 문자열인 correct_form(공백만)은 전체 매칭을 일으키지 않는다(가드).
        blank = Misconception(
            id="x",
            name_kr="x",
            domain="대수",
            canonical_statement="x",
            counterexample="x",
            signals=("x",),
            correct_form="   ",
        )
        assert not correct_form_present(blank, "아무 텍스트")


class TestSliceCatalogExpansionMatches:
    """슬 §5.4 신규 8종의 *진단 매칭* — 학생의 틀린 주장 텍스트 → 해당 id 매칭(confidence 1.0).

    각 텍스트는 *positive 오류 단편*(학생이 틀린 명제를 직접 적은 형태)으로, 두 signal
    토큰이 모두 공출현해 풀매칭(1.0)이 떠야 한다.
    """

    def _find(self, text: str, mid: str) -> MisconceptionMatch | None:
        return next((m for m in diagnose(text, top_k=8) if m.misconception.id == mid), None)

    def test_discriminant_negative_no_real_root(self) -> None:
        m = self._find("판별식이 음수라서 해가 없다고 했어", "discriminant-negative-no-real-root")
        assert m is not None
        assert m.confidence == 1.0
        assert m.misconception.domain == "대수"

    def test_root_loss_by_dividing(self) -> None:
        m = self._find("x²=2x에서 양변을 x로 나누면 x=2", "root-loss-by-dividing")
        assert m is not None
        assert m.confidence == 1.0

    def test_circle_radius_squared(self) -> None:
        m = self._find("x²+y²=9의 반지름은 r²=9 라고 적었어", "circle-radius-squared")
        assert m is not None
        assert m.confidence == 1.0
        assert m.misconception.domain == "기하"

    def test_mutually_exclusive_implies_independent(self) -> None:
        m = self._find("두 사건이 배반이니까 독립이야", "mutually-exclusive-implies-independent")
        assert m is not None
        assert m.confidence == 1.0
        assert m.misconception.domain == "확률통계"

    def test_composite_function_commutes(self) -> None:
        m = self._find("f∘g = g∘f 라서 합성 순서는 상관없어", "composite-function-commutes")
        assert m is not None
        assert m.confidence == 1.0
        assert m.misconception.domain == "함수"

    def test_translation_sign_flip(self) -> None:
        m = self._find("y=f(x-a)는 왼쪽으로 평행이동한 거야", "translation-sign-flip")
        assert m is not None
        assert m.confidence == 1.0
        assert m.misconception.domain == "함수"

    def test_continuity_implies_differentiability(self) -> None:
        # doc 함수 슬롯 #15이나 domain=미적분([H:12미적Ⅰ02-02])
        m = self._find("이 함수는 연속이니까 미분가능해", "continuity-implies-differentiability")
        assert m is not None
        assert m.confidence == 1.0
        assert m.misconception.domain == "미적분"

    def test_critical_point_implies_extremum(self) -> None:
        m = self._find("f′=0이면 극값을 가져", "critical-point-implies-extremum")
        assert m is not None
        assert m.confidence == 1.0
        assert m.misconception.domain == "미적분"

    def test_unrelated_solution_matches_no_new_entry(self) -> None:
        # 무관한 풀이는 신규 8종 어디에도 풀매칭(1.0)되지 않는다(두 토큰 AND·과잉 단일토큰 회피).
        new_ids = {
            "discriminant-negative-no-real-root",
            "root-loss-by-dividing",
            "circle-radius-squared",
            "mutually-exclusive-implies-independent",
            "composite-function-commutes",
            "translation-sign-flip",
            "continuity-implies-differentiability",
            "critical-point-implies-extremum",
        }
        text = "일차함수 y=2x+3의 그래프를 그리고 기울기를 구했어"
        for m in diagnose(text, top_k=10):
            if m.misconception.id in new_ids:
                assert m.confidence < 1.0


class TestRankingAndTopK:
    def test_higher_confidence_first(self) -> None:
        # 두 오개념 동시 등장(부분/전체 매칭)
        text = "(a+b)² = a² + b²로 전개했어. 그리고 log(a+b)는 그냥 log a + log b 정도일 거 같아"
        matches = diagnose(text)
        # 둘 다 매칭(둘 다 1.0 신뢰도)
        ids = [m.misconception.id for m in matches]
        assert "distribution-over-power" in ids
        assert "log-distribution" in ids
        # 모두 1.0이라 동률 — catalog 순서가 안정 유지(대수 distribution-over-power 먼저)
        assert matches[0].confidence == 1.0
        assert matches[1].confidence == 1.0

    def test_top_k_default_three(self) -> None:
        # 카탈로그 14개 중 부분 매칭 다수 발생할 만한 단순 토큰
        # "0"이 sign-flip-in-inequality·division-by-zero·exponent-zero에 모두 등장 가능
        text = "분모 0, a⁰, 음수, 곱, 0, 0"
        matches = diagnose(text)
        assert len(matches) <= 3

    def test_top_k_param_overrides(self) -> None:
        text = "분모 0, a⁰, 음수, 곱, 0, 0"
        few = diagnose(text, top_k=1)
        assert len(few) <= 1


class TestStableOrderingOnTie:
    """동률 confidence 시 catalog 순서(=doc 명시 순서) 유지."""

    def test_algebra_before_geometry_on_tie(self) -> None:
        # 대수(distribution-over-power)와 기하(닮음·합동) 두 케이스가 모두 풀 매칭
        text = "(a+b)² = a² + b² 그리고 닮음은 합동이야"
        matches = diagnose(text, top_k=5)
        # 둘 다 1.0이면 catalog 순서(algebra 먼저)
        assert matches[0].misconception.id == "distribution-over-power"
        assert any(m.misconception.id == "similarity-vs-congruence" for m in matches)


class TestNotationNormalization:
    """v1.1 표기 정규화 — 공백·유니코드 변이에 의한 거짓음성 제거(슬 101)."""

    def test_whitespace_insensitive_full_match(self) -> None:
        # 학생이 공백 없이 쓴 표기: signal "a² + b²"(공백)도 "a²+b²"에 매칭돼야 함
        matches = diagnose("(a+b)²=a²+b²")
        top = matches[0]
        assert top.misconception.id == "distribution-over-power"
        assert top.confidence == 1.0  # v1(공백 민감)이라면 0.5에 그쳤을 케이스

    def test_superscript_normalized_to_digit(self) -> None:
        # NFKC: 위첨자 "²" → "2". signal "a² + b²"가 평문 "a2 + b2"에도 매칭
        matches = diagnose("(a+b)2 = a2 + b2 로 전개")
        ids = {m.misconception.id for m in matches}
        assert "distribution-over-power" in ids

    def test_matched_signals_keep_original_form(self) -> None:
        # 정규화는 비교에만 — 표시되는 matched_signals는 원본 신호 문자열 유지
        top = diagnose("(a+b)²=a²+b²")[0]
        assert set(top.matched_signals) == {"(a+b)", "a² + b²"}


class TestLatexNotationNormalization:
    """MISC-17 — OCR·MathLive 산출물은 계약상 LaTeX(`OcrResult.plain_latex`→`student_solution`).

    NFKC는 `²`→`2`만 펴고 `^`·`{}`·`\\left`/`\\right`는 남겨, 인식기의 정상 출력 `(a+b)^2=a^2+b^2`가
    신호 2개 중 1개(0.5)만 맞아 게이트 ①(0.65)에서 탈락하던 실측 결함(PR #1034 Codex P1).
    카탈로그 `signals`·`correct_form`에는 이 문자가 0건이라 양변 정규화의 일관성이 유지된다.
    """

    def test_caret_exponent_full_match(self) -> None:
        # 인식기 기본형 `^2` — 유니코드 `²`와 같은 정규형 `a2+b2`로 접혀야 풀매칭.
        top = diagnose("(a+b)^2 = a^2+b^2")[0]
        assert top.misconception.id == "distribution-over-power"
        assert top.confidence == 1.0

    def test_braced_exponent_full_match(self) -> None:
        top = diagnose("(a+b)^{2} = a^{2}+b^{2}")[0]
        assert top.misconception.id == "distribution-over-power"
        assert top.confidence == 1.0

    def test_left_right_delimiters_full_match(self) -> None:
        # `\left(`·`\right)`는 크기 조정 표식일 뿐 — 괄호 자체만 남긴다.
        top = diagnose(r"\left(a+b\right)^2 = a^2+b^2")[0]
        assert top.misconception.id == "distribution-over-power"
        assert top.confidence == 1.0

    def test_correct_latex_expansion_stays_partial(self) -> None:
        # 올바른 전개의 LaTeX형은 유니코드형(`test_symbolic_distribution_unchanged_partial`)과
        # 동일하게 부분(0.5)에 머문다 — 정규화가 거짓양성을 만들지 않는다.
        matches = [
            m
            for m in diagnose("(a+b)^2 = a^2+2ab+b^2")
            if m.misconception.id == "distribution-over-power"
        ]
        assert matches and matches[0].confidence == 0.5

    def test_correct_form_detected_in_latex(self) -> None:
        # 정정 형태 탐지(강한 반박)도 같은 `_normalize`를 쓰므로 LaTeX형에서 성립해야 한다.
        entry = CATALOG_BY_ID["distribution-over-power"]
        assert entry.correct_form is not None  # 카탈로그 전제 — 없으면 이 검사는 공허하다.
        assert correct_form_present(entry, "(a+b)^2 = a^2+2ab+b^2")


class TestSignalPrecision:
    """v1.1 신호 정밀화 — 공통어 거짓양성 축소(슬 101·invertibility)."""

    def test_invertibility_full_match_on_real_misconception(self) -> None:
        top = diagnose("모든 함수는 역함수를 갖는다고 생각했어")[0]
        assert top.misconception.id == "invertibility-without-1-1"
        assert top.confidence == 1.0

    def test_invertibility_not_confident_on_benign_modeun(self) -> None:
        # "모든 구간"처럼 무관한 '모든'은 더 이상 풀매칭을 만들지 않음
        # (v1 신호 "모든"이었다면 역함수+모든 → 1.0 거짓양성)
        benign = "이 함수의 역함수를 모든 구간에서 구했어"
        m = next(
            (x for x in diagnose(benign) if x.misconception.id == "invertibility-without-1-1"),
            None,
        )
        assert m is None or m.confidence < 1.0


class TestNumericSubstitutionDetection:
    """v1.2 정규식 보조 탐지 — *거짓 항등식의 수치 대입*(슬 102 헤드라인).

    학생이 기호 substring 없이 *구체 수치로* 거짓 항등식을 계산한 흔적을 잡는다.
    """

    def _find(self, text: str, mid: str) -> MisconceptionMatch | None:
        return next((m for m in diagnose(text, top_k=5) if m.misconception.id == mid), None)

    def test_distribution_numeric_substitution_detected(self) -> None:
        # 기호 signals "(a+b)"·"a² + b²" 부재(학생은 *수*를 적음) → v1.1이면 미탐지.
        # v1.2 정규식이 (3+4)²=3²+4² 흔적을 잡아 *추가* 탐지.
        m = self._find("(3+4)² = 3² + 4² = 25", "distribution-over-power")
        assert m is not None
        # MISC-22(v1.5): 정규식 매치 1건 = 신호 전체와 동등한 완결 증거 → conf 1.0.
        # (v1.2 원식이면 0/2 + 1/2 = 0.5로 서빙 게이트 0.65에 못 미쳤다 — 그 결함이 MISC-22)
        assert m.confidence == 1.0
        assert m.matched_signals == ()  # 기호 substring 0
        assert len(m.matched_regex_signals) == 1

    def test_square_root_numeric_substitution_detected(self) -> None:
        # √((-3)²)=-3 — 음수 대입으로 거짓 항등식이 드러난 흔적
        m = self._find("√((-3)²) = -3", "square-root-positivity")
        assert m is not None
        # MISC-22(v1.5): 정규식 매치 1건 = 신호 전체와 동등한 완결 증거 → conf 1.0.
        assert m.confidence == 1.0
        assert len(m.matched_regex_signals) == 1

    def test_fraction_numeric_substitution_detected(self) -> None:
        # (2+4)/2=4 — 분자 합에서 분모와 같은 항을 통째로 약분한 수치 흔적
        m = self._find("(2+4)/2 = 4", "fraction-cancellation")
        assert m is not None
        # MISC-22(v1.5): 정규식 매치 1건 = 신호 전체와 동등한 완결 증거 → conf 1.0.
        assert m.confidence == 1.0
        assert m.matched_signals == ()
        assert len(m.matched_regex_signals) == 1

    def test_correct_computation_not_flagged_by_regex(self) -> None:
        # 거짓양성 가드: *올바른* 계산은 정규식이 잡지 않는다(역참조 불일치).
        for text, mid in (
            ("(3+4)² = 49 로 계산", "distribution-over-power"),
            ("√((-3)²) = 3", "square-root-positivity"),
            ("(2+4)/2 = 3", "fraction-cancellation"),
        ):
            m = self._find(text, mid)
            # 후보가 떠도(다른 weak substring 때문) 정규식은 미발화여야 함
            assert m is None or m.matched_regex_signals == ()

    def test_log_distribution_numeric_substitution_detected(self) -> None:
        # 슬 102 후속(보수적 확장): 로그를 합에 분배해 *수치로* 거짓 항등식을 계산한 흔적
        # `log(2+3)=log2+log3`을 잡는다. 기호 signals "log(a+b)"·"log a + log b" 부재(학생은
        # *수*만 적음) → v1.1이면 미탐지. v1.2 정규식이 *추가* 탐지.
        m = self._find("log(2+3) = log2 + log3", "log-distribution")
        assert m is not None
        # MISC-22(v1.5): 정규식 매치 1건 = 신호 전체와 동등한 완결 증거 → conf 1.0.
        assert m.confidence == 1.0
        assert m.matched_signals == ()  # 기호 substring 0
        assert len(m.matched_regex_signals) == 1

    def test_log_correct_product_law_not_flagged_by_regex(self) -> None:
        # FP 0 증명: 올바른 곱 법칙 `log(2·3)=log2+log3`은 괄호 안이 *곱*(·)이라 정규식
        # `\d+\+\d+`(합)에 미매치 — 정상 풀이를 오개념으로 거짓 매칭하지 않는다(낙인 방지).
        # 동시에 올바른 값 `log(2+3)=log5`(우변 단항)·기호식 `log(a+b)=log a+log b`(문자)도 미발화.
        for text in (
            "log(2·3) = log2 + log3",  # 올바른 곱 법칙(분배 대상은 곱)
            "log(2+3) = log5",  # 올바른 값 계산
            "log(a+b) = log a + log b",  # 기호식(substring 경로 담당·regex 미발화)
            "log(2+3) = log2 + log4",  # 역참조 불일치(진수 b: 3≠4)
        ):
            m = self._find(text, "log-distribution")
            assert m is None or m.matched_regex_signals == ()


class TestFactorSignFlipServingReach:
    """MISC-22 — factor-sign-flip 채널이 confidence 공식 정정 후 서빙 게이트(0.65)에 도달한다.

    이 채널은 signals가 기호형(`("(x-a)", "x=-a")`)이라 수치 입력에 substring이 구조적으로
    0건 매치된다 — v1.2 원식이면 정규식만 매치돼 conf 0.5에 갇혀 한 번도 서빙에 닿지 못했다
    (`anchor_detection_channel_eval` 실측). MISC-22가 confidence 공식을 정정한다.
    """

    def _find(self, text: str, mid: str) -> MisconceptionMatch | None:
        return next((m for m in diagnose(text, top_k=5) if m.misconception.id == mid), None)

    def test_numeric_sign_flip_reaches_full_confidence(self) -> None:
        m = self._find("(x-2)=0 이므로 x=-2", "factor-sign-flip")
        assert m is not None
        assert m.confidence == 1.0  # 정규식 매치 1건 = 신호 전체(MISC-22)
        assert m.matched_signals == ()  # 기호 substring 0(수치 입력이라 구조적으로 미매칭)
        assert len(m.matched_regex_signals) == 1

    def test_numeric_sign_flip_survives_serving_gate(self) -> None:
        # 서빙 게이트(top-1 floor 0.65)까지 살아남는지 — MISC-22 해소의 실제 판정 기준.
        gated = apply_match_quality_gate(diagnose("(x-2)=0 이므로 x=-2", top_k=5))
        assert any(m.misconception.id == "factor-sign-flip" for m in gated.matches)

    def test_correct_root_not_flagged(self) -> None:
        # 부호가 뒤집히지 않은 올바른 풀이는 여전히 미탐지(역참조 불일치·거짓양성 0).
        m = self._find("(x-2)=0 이므로 x=2", "factor-sign-flip")
        assert m is None or m.matched_regex_signals == ()

    def test_originally_positive_root_not_flagged(self) -> None:
        # (x+2)=0의 근은 -2가 정답이다 — 부호가 원래 +인 정답까지 오탐하면 안 된다.
        m = self._find("(x+2)=0 이므로 x=-2", "factor-sign-flip")
        assert m is None or m.matched_regex_signals == ()


class TestExplicitCorrectionMentionSuppressesRegex:
    """MISC-22 v1.5 후속(Codex P1, PR #1071 리뷰) — 거짓 항등식을 *인용해 반박*한 진술은

    정규식이 발화해도(부분 문자열만 보므로) confidence를 얻으면 안 된다. v1.5 전에는 이 인용-반박
    진술도 conf 0.5(게이트 미만)에 머물러 무해했으나, "정규식 매치=신호 전체" 정정 이후에는 그대로
    두면 확신 개입(정답에 오진단)이 나갈 뻔했다 — 5개 채널(factor-sign-flip·distribution-over-
    power·square-root-positivity·fraction-cancellation·log-distribution) 전부 실측 확인.
    `EXPLICIT_CORRECTION_MENTION`(catalog.py)이 정정 언급 앞에서 해당 regex_signals의 미발화를
    보장한다.
    """

    def _find(self, text: str, mid: str) -> MisconceptionMatch | None:
        return next((m for m in diagnose(text, top_k=10) if m.misconception.id == mid), None)

    def test_factor_sign_flip_refuted_quote_not_confident(self) -> None:
        m = self._find("(x-2)=0이므로 x=-2라는 풀이는 틀리고 x=2다", "factor-sign-flip")
        assert m is None or m.matched_regex_signals == ()

    def test_distribution_refuted_quote_not_confident(self) -> None:
        m = self._find("(3+4)²=3²+4²는 틀렸고 정답은 49다", "distribution-over-power")
        assert m is None or m.matched_regex_signals == ()

    def test_square_root_refuted_quote_not_confident(self) -> None:
        m = self._find("√((-3)²)=-3은 틀리고 3이 맞다", "square-root-positivity")
        assert m is None or m.matched_regex_signals == ()

    def test_fraction_cancellation_refuted_quote_not_confident(self) -> None:
        # "틀린"(관형형)은 어간 "틀리"를 substring으로 포함하지 않는다 — 활용형 나열 검증.
        m = self._find("(2+4)/2=4는 틀린 계산이고 실제로는 3이다", "fraction-cancellation")
        assert m is None or m.matched_regex_signals == ()

    def test_log_distribution_refuted_quote_not_confident(self) -> None:
        m = self._find("log(2+3)=log2+log3은 틀렸고 log5가 맞다", "log-distribution")
        assert m is None or m.matched_regex_signals == ()

    def test_genuine_misconceptions_still_reach_full_confidence(self) -> None:
        # 회귀 가드 — 반박 언급이 *없는* 진짜 오개념까지 죽이면 안 된다.
        cases = (
            ("(x-2)=0 이므로 x=-2", "factor-sign-flip"),
            ("(3+4)² = 3² + 4² = 25", "distribution-over-power"),
            ("√((-3)²) = -3", "square-root-positivity"),
            ("(2+4)/2 = 4", "fraction-cancellation"),
            ("log(2+3) = log2 + log3", "log-distribution"),
        )
        for text, mid in cases:
            m = self._find(text, mid)
            assert m is not None, mid
            assert m.confidence == 1.0, mid
            assert len(m.matched_regex_signals) == 1, mid


class TestExtremumAmbiguousCoincidenceNotOverconfident:
    """MISC-24 — `extremum-value-vs-point-confused`가 f(x₀)=x₀ 우연의 일치 정답에 확신 오진단을
    내지 않는다.

    배경(acceptance ①의 실측 재현)
    -------------------------------
    이 채널의 정규식은 리터럴 "극댓값"을 포함해 매치될 때마다 substring 신호 "극댓값"도 항상
    함께 발화한다. MISC-22 정정 *이전*(v1.2 원식)에도 `1(substring)+1(regex 1개 credit)=2=
    len(signals)`로 이미 confidence 1.0이었다 — 즉 이 위험은 MISC-22와 무관하게 이전부터
    있었다(MISC-22 조사 중 발견 → MISC-24로 분리 등재). f(x₀)=x₀인 *우연의 일치* 정답(극대점
    x=2에서 극댓값도 2)은 오개념을 저지른 풀이와 텍스트가 글자 그대로 동일해 `refuting_regex`
    (MISC-23)로도 반박할 대상이 없다 — 그래서 `ambiguous_regex_signals`(models.py)로 이 항목의
    정규식 가산 자체를 0으로 만드는 방식으로 해소한다.
    """

    def _find(
        self, text: str, mid: str = "extremum-value-vs-point-confused"
    ) -> MisconceptionMatch | None:
        return next((m for m in diagnose(text, top_k=5) if m.misconception.id == mid), None)

    def test_ambiguous_coincidence_no_longer_reaches_full_confidence(self) -> None:
        """우연의_일치_정답은_더는_confidence_1.0에_도달하지_않는다 — acceptance ①·② 직접 재현"""
        text = "극대는 x=2 에서 나오고 극댓값은 2 이다 (f(2)=2 인 함수)"
        m = self._find(text)
        assert m is not None  # 정규식은 여전히 발화(텔레메트리 유지)
        assert m.confidence == 0.5  # 1.0이 아니라 substring "극댓값" 단독 수준에 캡됨
        assert m.matched_signals == ("극댓값",)
        assert len(m.matched_regex_signals) == 1  # 발화는 기록되나 가산은 0

    def test_ambiguous_coincidence_does_not_survive_serving_gate(self) -> None:
        """우연의_일치_정답은_서빙_품질_게이트를_통과하지_못한다 — 실제 해악 지점의 대조"""
        text = "극대는 x=2 에서 나오고 극댓값은 2 이다 (f(2)=2 인 함수)"
        gated = apply_match_quality_gate(diagnose(text))
        surfaced = [m.misconception.id for m in gated.matches]
        assert "extremum-value-vs-point-confused" not in surfaced

    def test_numeric_trace_misconception_also_capped(self) -> None:
        """x좌표라는_말을_안_쓴_수치_흔적_오개념도_함께_0.5에_갇힌다 — 회귀가 아니라 설계 의도

        원래 이 정규식이 잡으려던 자리(학생이 "x좌표"라는 말 없이 극댓값을 좌표 숫자로 답한
        경우)도 우연의 일치 정답과 텍스트가 완전히 같은 형태라 함께 캡된다 — 그 자체가 이
        채널이 텍스트만으로는 둘을 가를 수 없다는 실측 증거다.
        """
        m = self._find("극대는 x=-1 에서 나오고 극댓값은 -1")
        assert m is not None
        assert m.confidence == 0.5
        assert len(m.matched_regex_signals) == 1  # 정규식은 여전히 발화(검출은 유지)

    def test_explicit_x_coordinate_confusion_unaffected(self) -> None:
        """x좌표라는_말을_명시한_경우는_MISC-24와_무관하게_여전히_confidence_1.0

        정규식과 무관한 substring AND("극댓값"+"x좌표") 경로 — 원래도 모호하지 않았다.
        """
        m = self._find("극댓값을 극점의 x좌표라고 답함")
        assert m is not None
        assert m.confidence == 1.0
        assert set(m.matched_signals) == {"극댓값", "x좌표"}
        gated = apply_match_quality_gate(diagnose("극댓값을 극점의 x좌표라고 답함"))
        assert any(x.misconception.id == "extremum-value-vs-point-confused" for x in gated.matches)

    def test_distinct_coordinate_and_value_not_flagged(self) -> None:
        """좌표와_값이_다른_정답은_여전히_미탐지 — 회귀 없음(FP 0 대조)"""
        m = self._find("극대는 x=-1 에서 나오고 극댓값은 101")
        assert m is None or m.matched_regex_signals == ()


class TestAmbiguousRegexSignalsGovernance:
    """`ambiguous_regex_signals` 부여 항목의 동결 — 조용히 늘거나 줄지 않게(MISC-24).

    `TestRefutingRegexGovernance`와 같은 정신 — 이 플래그도 탐지를 **끄는** 방향(정규식이
    발화해도 confidence에 기여하지 않게)이라 잘못 붙으면 다른 채널의 MISC-22 해소를 조용히
    되돌린다.
    """

    _AMBIGUOUS_IDS = {"extremum-value-vs-point-confused"}

    def test_only_listed_entries_have_the_flag(self) -> None:
        """목록_밖_항목은_플래그가_없다 — 다른 5개 정규식 채널(MISC-22)의 회귀 방지"""
        for m in CATALOG:
            if m.id not in self._AMBIGUOUS_IDS:
                assert m.ambiguous_regex_signals is False, m.id

    def test_listed_entries_actually_have_it(self) -> None:
        """목록에_적힌_항목은_실제로_플래그가_켜져있다 — 선언과 사실의 대조"""
        for mid in self._AMBIGUOUS_IDS:
            assert CATALOG_BY_ID[mid].ambiguous_regex_signals is True, mid

    def test_flagged_entries_actually_have_regex_signals(self) -> None:
        """플래그를_가진_항목은_실제로_regex_signals가_있다 — 무의미한 플래그 방지"""
        for mid in self._AMBIGUOUS_IDS:
            assert CATALOG_BY_ID[mid].regex_signals, mid


class TestRegexBackwardCompatibility:
    """v1.2 정규식 도입이 v1.1 기호식 매칭(confidence·matched_signals)을 *불변*으로 유지."""

    def test_symbolic_distribution_unchanged_full(self) -> None:
        # 기호 풀매칭은 여전히 1.0·동일 matched_signals, 정규식은 미발화
        m = next(
            x
            for x in diagnose("(a+b)² = a² + b²로 전개")
            if x.misconception.id == "distribution-over-power"
        )
        assert m.confidence == 1.0
        assert set(m.matched_signals) == {"(a+b)", "a² + b²"}
        assert m.matched_regex_signals == ()

    def test_symbolic_distribution_unchanged_partial(self) -> None:
        m = next(
            x for x in diagnose("(a+b)² 까지만") if x.misconception.id == "distribution-over-power"
        )
        assert m.confidence == 0.5
        assert m.matched_regex_signals == ()

    def test_symbolic_fraction_unchanged_full(self) -> None:
        # 슬: 신호 정밀화로 둘째 signal `b`→`= b`(틀린 RHS) — 틀린 형태는 여전히 풀매칭 1.0.
        m = next(
            x
            for x in diagnose("(a+b)/a = b 로 약분")
            if x.misconception.id == "fraction-cancellation"
        )
        assert m.confidence == 1.0
        assert set(m.matched_signals) == {"(a+b)/a", "= b"}
        assert m.matched_regex_signals == ()


# ──────────────────────────────────────────────────────────────────────────
# v1.3 (슬109) — 짧은 영숫자 signal 경계 매칭: 실증 라이브 FP의 영구 회귀 잠금
# ──────────────────────────────────────────────────────────────────────────
class TestSignalBoundaryV13:
    """전문가 리뷰가 실증한 라이브 결함의 회귀 가드.

    결함: `'0' ∈ '10'` 같은 *토큰 내부* 부분문자열 매칭으로, 완전히 올바른 진술
    ("분모가 10인 분수를 약분했어요")이 division-by-zero **풀매칭(1.0) → COUNTEREXAMPLE
    개입 발화**. v1.3은 숫자-only·단일 ASCII 문자 signal을 영숫자 경계로 매칭해 차단한다.
    """

    def _by_id(self, text: str, mid: str) -> MisconceptionMatch | None:
        return next((m for m in diagnose(text, top_k=30) if m.misconception.id == mid), None)

    def test_demonstrated_live_fp_no_longer_full_matches(self) -> None:
        # 실증 케이스 그대로: '10'의 '0'이 더는 매칭되지 않아 풀매칭(1.0)이 사라진다.
        m = self._by_id("분모가 10인 분수를 약분했어요", "division-by-zero")
        assert m is not None  # '분모'는 여전히 부분매칭(알려진 트레이드오프)
        assert m.matched_signals == ("분모",)  # '0'은 미매칭
        assert m.confidence == 0.5  # 1.0 풀매칭 소멸

    def test_demonstrated_live_fp_counterexample_no_longer_fires(self) -> None:
        # 피해 지점 회귀: conf 1.0 → COUNTEREXAMPLE(단정적 개입)이 더는 발화하지 않는다.
        # 부분매칭 0.5 → REVERSE_REASONING은 substring 설계의 문서화된 잔여 트레이드오프
        # (정밀 해법은 semantic/judge 계층 — 슬104~108·측정 대기)라
        # 여기선 "단정 개입 소멸"만 잠근다.
        from whymath_backend.l4.misconception import select_intervention
        from whymath_backend.l4.misconception.models import InterventionPattern

        matches = diagnose("분모가 10인 분수를 약분했어요")
        assert matches, "부분매칭은 존재(트레이드오프)"
        iv = select_intervention(matches[0])
        assert iv is None or iv.pattern is not InterventionPattern.COUNTEREXAMPLE

    def test_zero_inside_decimal_not_matched(self) -> None:
        # '0.5'·'1.0' 내부의 0은 소수점 경계로 차단.
        m = self._by_id("계산하면 0.5가 나와요", "exponent-zero")
        assert m is None or "0" not in m.matched_signals

    def test_zero_after_nfkc_subscript_not_matched(self) -> None:
        # 'a₀'는 NFKC로 'a0'이 된다 — 식별자 내부 0은 차단(수열 첨자 오매칭 방지).
        m = self._by_id("수열 a₀의 값을 구했다", "division-by-zero")
        assert m is None  # '분모'도 '0'도 없음

    def test_legitimate_zero_still_matches(self) -> None:
        # 정당한 사용처(한글 조사 이웃)는 계속 풀매칭 — 거짓음성 추가 없음 회귀.
        m = self._by_id("분모가 0이 되어도 항상 정의된다고 생각했어", "division-by-zero")
        assert m is not None
        assert set(m.matched_signals) == {"분모", "0"}
        assert m.confidence == 1.0

    def test_single_latin_b_inside_identifier_not_matched(self) -> None:
        # 슬: fraction-cancellation 신호가 `("(a+b)/a","= b")`로 정밀화돼 단일 `b`는 사라졌다.
        # `ab를 전개…`는 LHS식·`= b` 둘 다 없어 미매칭 — 임의 텍스트 오매칭 차단(정밀화 후 유지).
        m = self._by_id("ab를 전개해서 정리했어요", "fraction-cancellation")
        assert m is None

    def test_180_inside_larger_number_not_matched(self) -> None:
        # '1800' 내부의 '180'은 차단·정당한 '180'(비숫자 이웃)은 유지.
        wrong = self._by_id("내각의 합이 1800이라고 적었다", "angle-sum-non-triangle")
        assert wrong is not None and "180" not in wrong.matched_signals
        right = self._by_id("내각의 합은 180이라고 했다", "angle-sum-non-triangle")
        assert right is not None and "180" in right.matched_signals

    def test_catalog_short_signal_ratchet(self) -> None:
        # 래칫 가드: 경계 매칭 대상(숫자-only·단일 문자) signal의 전수 스냅숏.
        # 새 항목이 짧은/숫자 signal을 추가하면 이 테스트가 깨져 의식적 리뷰를 강제한다
        # (v1.1 "signals 작성 원칙"의 코드 강제 — 종전엔 권고뿐이라 라이브 FP가 들어왔다).
        from whymath_backend.l4.misconception.catalog import CATALOG

        short_or_digit = {
            (m.id, s) for m in CATALOG for s in m.signals if len(s) <= 1 or s.isdigit()
        }
        # 슬: 신호 정밀화로 square-root(`√`)·fraction(`b`)의 짧은 signal이 LHS식+틀린 RHS로 대체돼
        # 래칫에서 빠졌다(정답 거짓 COUNTEREXAMPLE 제거 부수효과 — 짧은 signal 오매칭면 축소).
        assert short_or_digit == {
            ("sign-flip-in-inequality", "곱"),  # 한글 형태소 — substring 유지(내용성)
            ("division-by-zero", "0"),  # 경계 매칭
            ("exponent-zero", "0"),  # 경계 매칭
            ("angle-sum-non-triangle", "180"),  # 경계 매칭(숫자-only)
        }


class TestUnsafeSignalTightening:
    """LHS-only 느슨 신호 정밀화 — 정답 작업의 거짓 COUNTEREXAMPLE 개입 제거(우선순위 #1·#109 동류).

    세 오개념(square-root-positivity·fraction-cancellation·chain-rule)의 `signals`가 *틀린 RHS*를
    포함하지 않아 정답 형태(`√(x²)=|x|`·`(a+b)/a=1+b/a`·`d/dx[sin(2x)]=2cos(2x)`)를 1.0 풀매칭 →
    judge 기본 off라 COUNTEREXAMPLE 낙인 발화가 학생에 도달했다. LHS식+틀린 RHS로 좁혀 정답은 0.5
    (게이트 0.65 미만)·틀린 형태만 1.0이 되게 한다. 각 ① 정답 미발화 ② 틀림 1.0 ③ 정답에 단정
    개입 소멸(#109 미러)을 잠근다.
    """

    # (id, 정답 형태, 틀린 형태)
    _CASES = (
        ("square-root-positivity", "√(x²) = |x|", "√(x²) = x"),
        ("fraction-cancellation", "(a+b)/a = 1 + b/a", "(a+b)/a = b"),
        (
            "chain-rule-inner-derivative-omitted",
            "d/dx[sin(2x)] = 2cos(2x)",
            "d/dx[sin(2x)] = cos(2x)",
        ),
    )

    def _find(self, text: str, mid: str) -> MisconceptionMatch | None:
        return next((m for m in diagnose(text, top_k=30) if m.misconception.id == mid), None)

    def test_correct_form_below_gate(self) -> None:
        # 정답 형태는 자기 오개념을 신뢰 게이트(0.65) 이상으로 내지 않는다(거짓양성 소멸).
        for mid, correct, _wrong in self._CASES:
            m = self._find(correct, mid)
            assert m is None or m.confidence < 0.65, (mid, correct)

    def test_wrong_form_full_match(self) -> None:
        # 틀린 형태는 여전히 1.0 풀매칭(정밀화가 탐지력을 죽이지 않음).
        for mid, _correct, wrong in self._CASES:
            m = self._find(wrong, mid)
            assert m is not None and m.confidence == 1.0, (mid, wrong)

    def test_correct_form_no_counterexample_intervention(self) -> None:
        # #109 미러 — 정답 형태에 단정적 COUNTEREXAMPLE 개입이 발화하지 않는다(낙인 방지).
        from whymath_backend.l4.misconception import select_intervention
        from whymath_backend.l4.misconception.models import InterventionPattern

        for mid, correct, _wrong in self._CASES:
            m = self._find(correct, mid)
            if m is None:
                continue
            iv = select_intervention(m)
            assert iv is None or iv.pattern is not InterventionPattern.COUNTEREXAMPLE, (
                mid,
                correct,
            )


class TestRefutingRegex:
    """반박 조건(MISC-23) — 오개념을 *저지른* 풀이와 그것을 *설명한 정답*을 가른다.

    왜 필요했나
    -----------
    `signals` 공출현(AND)은 양성 단편만 센다. `root-loss-by-dividing`의
    `("양변", "x로 나누")`는 근 손실을 저지른 풀이에도, 그 함정을 정확히 설명한 정답에도
    똑같이 발화한다 — 둘 다 "양변을 x로 나누"를 쓰기 때문이다. 그래서 정답이 confidence
    1.0을 받아 품질 게이트(0.65)를 넘어 학생에게 확신 오진단으로 나갔다(실측).

    설계 판정: 감점이 아니라 **거부**다. 오개념 귀속이 *반박된* 것이지 *덜 확실한* 것이
    아니며, 낮은 confidence로 남기면 하류가 그것을 약한 증거로 취급한다.
    """

    #: 전부 **정답**이다 — 0을 근으로 남겼거나, 그 함정을 경고하는 서술이다.
    CORRECT_ANSWERS = (
        "x²=2x에서 양변을 x로 나누면 x=2만 나와서 안 되고 해는 0과 2다",
        "x²=3x 에서 양변을 x로 나누면 안 된다 — x=0 근을 잃는다",
        "x²=5x 이므로 x(x-5)=0, 따라서 x=0 또는 x=5",
        "양변을 x로 나누는 순간 x=0 이라는 근이 사라진다",
        "x²=7x, 양변을 x로 나누면 x=7 만 남아 x=0 을 잃는다",
        "x²=10x 의 두 근은 0이나 10 이다 — 양변을 x로 나누면 안 된다",
    )

    #: 전부 **오개념**이다 — 0을 어디에도 근으로 적지 않았다.
    ACTUAL_MISCONCEPTIONS = (
        "x²=2x 양변을 x로 나누면 x=2",
        "x² = 5x 이므로 양변을 x로 나눠 x=5",
        "ax²=bx 의 양변을 x로 나누면 x=b/a 라고 했다",
        "양변을 x로 나누어 x=12 를 얻었다",
    )

    def test_correct_answers_are_refuted(self) -> None:
        """정답은_반박돼_후보에서_빠진다"""
        for text in self.CORRECT_ANSWERS:
            ids = [m.misconception.id for m in diagnose(text)]
            assert "root-loss-by-dividing" not in ids, text

    #: 제로근을 **부정한** 오답들 — 리터럴 `x=0`·`0은`이 있지만 *주장이 아니라 부정*이다.
    #: 이것을 반박으로 세면 명백한 오개념을 통째로 놓친다(PR #1039 Codex P2).
    #: 부정 어미를 **하나씩 다르게** 쓴다 — 목록을 좁히는 뮤테이션이 살아남지 않게 하기 위해서다
    #: (실측: 어미를 `아니` 하나로 줄인 뮤테이션 P3가 처음엔 생존했다).
    NEGATED_ZERO_ROOT = (
        "x²=2x에서 x=0은 근이 아니므로 양변을 x로 나누면 x=2다",  # 아니
        "x=0 은 근이 될 수 없으니 양변을 x로 나눠 x=5",  # 없
        "0은 근에서 제외하고, 양변을 x로 나누면 x=7",  # 제외
        "x=0 은 무시해도 되니까 양변을 x로 나누어 x=3",  # 무시
        "x=0 은 버리고 양변을 x로 나누면 x=9",  # 버리
        "x=0 은 빼고 생각해서 양변을 x로 나누면 x=11",  # 빼
    )

    def test_negated_zero_root_is_not_a_refutation(self) -> None:
        """제로근을_부정한_오답은_반박으로_치지_않는다 — 미검출 방향 회귀 차단

        반박은 탐지를 *끄는* 방향이라 과잉 발동이 곧 미검출이고, 미검출은 오검출과 달리
        아무도 소리내지 않는다.
        """
        for text in self.NEGATED_ZERO_ROOT:
            ids = [m.misconception.id for m in diagnose(text)]
            assert "root-loss-by-dividing" in ids, text

    def test_actual_misconceptions_still_detected(self) -> None:
        """진짜_근_손실은_여전히_검출된다 — 반박을 넓히다 오개념을 죽이지 않았는지"""
        for text in self.ACTUAL_MISCONCEPTIONS:
            ids = [m.misconception.id for m in diagnose(text)]
            assert "root-loss-by-dividing" in ids, text

    def test_refuted_answers_do_not_reach_the_serving_gate(self) -> None:
        """반박된_정답은_서빙_품질_게이트에_도달하지_않는다 — 실제 해악 지점의 대조

        `diagnose`에서 빠졌다는 것과 학생에게 안 나간다는 것은 다른 사실이므로 따로 단언한다.
        수정 전에는 이 두 문장이 conf 1.0으로 게이트를 통과했다.
        """
        for text in self.CORRECT_ANSWERS:
            gated = apply_match_quality_gate(diagnose(text))
            surfaced = [m.misconception.id for m in gated.matches]
            assert "root-loss-by-dividing" not in surfaced, text

    def test_refutation_is_checked_before_signal_counting(self) -> None:
        """반박은_신호를_세기_전에_판정된다 — 감점이 아니라 거부임을 계약으로 고정

        신호가 **전부** 맞는 문장(공출현 2/2)인데도 후보가 아예 없어야 한다. 감점 방식이었다면
        낮은 confidence로 남았을 자리다.
        """
        text = "x²=2x에서 양변을 x로 나누면 x=2만 나와서 안 되고 해는 0과 2다"
        entry = CATALOG_BY_ID["root-loss-by-dividing"]
        norm = _normalize(text)
        assert all(_signal_hit(s, norm) for s in entry.signals), "전제: 두 신호가 다 맞는 문장"
        assert not [m for m in diagnose(text) if m.misconception.id == entry.id]

    #: 끝자리가 0인 수 뒤에 제로근 조사(`과`·`와`·`또는`·`이나`·`,`)가 붙는 문장들.
    #: `(?<!\d)` 경계가 없으면 `10과`의 `0과`가 제로근 언급으로 오인돼 **반박이 과잉 발동**하고,
    #: 진짜 오개념이 통째로 미검출된다. 미검출은 오검출과 달리 아무도 소리내지 않는다.
    BOUNDARY_MISCONCEPTIONS = (
        "x²=10x 양변을 x로 나누면 x=10과 같다",
        "x²=20x 이므로 양변을 x로 나누어 x=20와 같은 값을 얻었다",
        "양변을 x로 나누면 x=30 또는 그 근처다",
        "x²=40x, 양변을 x로 나누면 x=40이나 마찬가지다",
        "양변을 x로 나누어 x=50, 이것이 답이다",
    )

    def test_number_boundary_is_respected(self) -> None:
        """숫자_경계 — 끝자리 0인 수에 붙은 조사를 제로근으로 오인하지 않는다

        경계가 없으면 반박이 과잉 발동해 진짜 오개념을 놓친다(미검출 방향 회귀). 최초 판의
        이 테스트는 `x=10`·`x=20`만 봐서 **그 경계를 한 번도 밟지 않는 위장**이었다 —
        뮤테이션(경계 제거)이 살아남아 드러났다. 조사가 붙은 형태여야 그 절을 실제로 통과한다.
        """
        for text in self.BOUNDARY_MISCONCEPTIONS:
            ids = [m.misconception.id for m in diagnose(text)]
            assert "root-loss-by-dividing" in ids, text

    def test_plain_numeric_answers_still_detected(self) -> None:
        """조사_없는_끝자리0_수도_검출된다"""
        for text in ("x²=10x 양변을 x로 나누면 x=10", "양변을 x로 나누어 x=20 을 얻었다"):
            ids = [m.misconception.id for m in diagnose(text)]
            assert "root-loss-by-dividing" in ids, text


class TestAdditionMultiplicationRefutation:
    """반박 조건(PR #1068 Codex P1) — `addition-multiplication-rule-confused`.

    왜 필요했나
    -----------
    `signals=("합의 법칙", "곱의 법칙")` 공출현(AND)은 두 법칙을 *뒤섞어 쓴* 오답에도, 두
    법칙을 *정확히 구분해 설명한* 정답에도 똑같이 발화한다 — 둘 다 두 법칙 이름을 함께
    언급하기 때문이다. judge(`misconception_judge_enabled`)가 비활성인 기본 상태에서
    "합의 법칙과 곱의 법칙을 구분해서 써야 한다"가 confidence 1.0으로 품질 게이트(0.65)를
    넘어 정답에 반례 개입이 나갈 뻔했다(실측).
    """

    #: 전부 **정답**이다 — 두 법칙을 명시적으로 구분·구별하는 서술.
    CORRECT_ANSWERS = (
        "합의 법칙과 곱의 법칙을 구분해서 써야 한다",
        "합의 법칙과 곱의 법칙을 구별해야 헷갈리지 않는다",
        "동시에 일어나면 곱의 법칙, 아니면 합의 법칙으로 구분한다",
    )

    #: 전부 **오개념**이다 — 두 법칙을 혼동해 틀리게 계산했다("구분"·"구별" 미포함).
    ACTUAL_MISCONCEPTIONS = (
        "동전과 주사위를 던지는 경우의 수는 합의 법칙과 곱의 법칙이 헷갈려서 6+2=8로 계산했다",
        "합의 법칙과 곱의 법칙 중 뭘 써야 할지 몰라서 그냥 6+2로 풀었다",
    )

    def test_correct_answers_are_refuted(self) -> None:
        """정답은_반박돼_후보에서_빠진다"""
        for text in self.CORRECT_ANSWERS:
            ids = [m.misconception.id for m in diagnose(text)]
            assert "addition-multiplication-rule-confused" not in ids, text

    def test_actual_misconceptions_still_detected(self) -> None:
        """진짜_혼동은_여전히_검출된다 — 반박을 넓히다 오개념을 죽이지 않았는지"""
        for text in self.ACTUAL_MISCONCEPTIONS:
            ids = [m.misconception.id for m in diagnose(text)]
            assert "addition-multiplication-rule-confused" in ids, text

    def test_refuted_answers_do_not_reach_the_serving_gate(self) -> None:
        """반박된_정답은_서빙_품질_게이트에_도달하지_않는다 — 실제 해악 지점의 대조"""
        for text in self.CORRECT_ANSWERS:
            gated = apply_match_quality_gate(diagnose(text))
            surfaced = [m.misconception.id for m in gated.matches]
            assert "addition-multiplication-rule-confused" not in surfaced, text

    def test_refutation_is_checked_before_signal_counting(self) -> None:
        """반박은_신호를_세기_전에_판정된다 — 감점이 아니라 거부임을 계약으로 고정"""
        text = "합의 법칙과 곱의 법칙을 구분해서 써야 한다"
        entry = CATALOG_BY_ID["addition-multiplication-rule-confused"]
        norm = _normalize(text)
        assert all(_signal_hit(s, norm) for s in entry.signals), "전제: 두 신호가 다 맞는 문장"
        assert not [m for m in diagnose(text) if m.misconception.id == entry.id]


class TestRefutingRegexGovernance:
    """반박 조건을 *가진* 항목의 동결 — 조용히 늘거나 줄지 않게.

    반박은 탐지를 **끄는** 방향이라 잘못 붙으면 오개념을 통째로 놓치고, 그 미검출은 오검출과
    달리 아무도 소리내지 않는다. 그래서 부여 항목을 명시 목록으로 묶는다.
    """

    _REFUTING_IDS = {"root-loss-by-dividing", "addition-multiplication-rule-confused"}

    def test_only_listed_entries_have_refuting_regex(self) -> None:
        """목록_밖_항목은_반박_조건이_없다"""
        for m in CATALOG:
            assert isinstance(m.refuting_regex, tuple)
            if m.id not in self._REFUTING_IDS:
                assert m.refuting_regex == (), m.id

    def test_listed_entries_actually_have_one(self) -> None:
        """목록에_적힌_항목은_실제로_갖고_있다 — 선언과 사실의 대조"""
        for mid in self._REFUTING_IDS:
            assert CATALOG_BY_ID[mid].refuting_regex, mid

    def test_all_refuting_patterns_compile(self) -> None:
        """반박_정규식은_전부_컴파일된다 — 런타임 re.error 회귀 가드"""
        seen = 0
        for m in CATALOG:
            for pat in m.refuting_regex:
                re.compile(pat)
                seen += 1
        assert seen > 0, "스캔 0건 — 이 가드가 공허하게 통과했다"

    def test_shared_zero_root_definition_feeds_both_enforcement_points(self) -> None:
        """제로근_정의가_반박과_전방탐색_양쪽에_쓰인다 — 두 곳이 갈라지지 않게

        같은 개념을 두 번 적었던 것이 PR #1032 Codex P1의 자리였다(한쪽만 넓혀 정답이 샜다).
        """
        entry = CATALOG_BY_ID["root-loss-by-dividing"]
        assert entry.refuting_regex == (ZERO_ROOT_MENTION,)
        assert ZERO_ROOT_MENTION in entry.regex_signals[0]


# ──────────────────────────────────────────────────────────────────────────
# MISC-25 — 명시적 정정 언급: 절 경계 안 근접 판정
# ──────────────────────────────────────────────────────────────────────────
class TestExplicitCorrectionNearSignals:
    """학생이 오개념을 *명시적으로 부정*했는데도 확신 진단이 나가던 구조적 공백.

    발단: `MISC-22`(PR #1071) Codex P1이 5개 정규식 채널에서 이 축을 지적했고, 그보다 앞서
    있던 **substring 경로의 같은 사각**은 범위 밖으로 분리됐다(MISC-25).

    실측된 크기: 진단 카탈로그의 **측정 가능 66종 전부**가 "…라는 풀이는 틀렸다"를 붙여도
    서빙 게이트를 통과했다(100%). 항목별 결함이 아니라 구조적 공백이라 항목마다
    `refuting_regex`를 다는 방식으로는 못 메운다 —
    측정 정본은 `harness/explicit_correction_gap_eval.py`.
    """

    def test_explicit_correction_suppresses_confident_diagnosis(self) -> None:
        """[결함 재현] MISC-25 acceptance① 그 문장 — 정정 언급이 있으면 진단이 나가지 않는다.

        수정 전 실측: `root-loss-by-dividing` confidence **1.0**으로 게이트 통과 →
        `select_intervention`이 COUNTEREXAMPLE을 내 *정답을 쓴 학생에게* 반례가 나갔다.
        """
        text = "x²=2x 양변을 x로 나누면 x=2라는 풀이는 틀렸다"
        assert "root-loss-by-dividing" not in [m.misconception.id for m in diagnose(text)]

    def test_prefix_correction_label_is_recognized_but_held_not_suppressed(self) -> None:
        """전치 라벨("틀린 풀이: …") — 인지하되 **억제가 아니라 보류**다 (MISC-28 ⓒ).

        창이 **양방향**이어야 하는 이유는 그대로다: 후치 전용 창이면 이 형태를 하나도 못 잡는다
        (교수학 판정 실측: 전치 라벨 66종 중 0종). 이 픽스처가 없으면 `_CORRECTION_LOOKBEHIND`를
        0으로 줄여도 전건 초록이다.

        **MISC-28에서 바뀐 것**: 전치 정정을 *억제*로 읽으면 같은 위치의 무관한 정정
        ("부호를 잘못 옮겨 적었지만 <오개념>")까지 삼켜 오억제 66/66이 된다. 위치로는 둘을
        구별할 수 없으므로(실측) 매칭은 살리고 `attribution_unclear`로 판정을 보류한다 —
        확신 진단은 게이트 ③(`apply_match_quality_gate`)과 영속 계층이 함께 막는다.
        """
        hits = [m for m in diagnose("틀린 풀이: 양변을 x로 나누면 x=2")]
        target = [m for m in hits if m.misconception.id == "root-loss-by-dividing"]
        assert target, "전치 라벨을 인지하지 못했다 — 매칭 자체가 사라지면 안 된다(보류≠억제)"
        assert target[0].attribution_unclear is True, (
            "전치 정정은 귀속 불명으로 **표시**돼야 한다 — 플래그가 없으면 확신 진단이 그대로 "
            "나간다(선행정정 사각 66/66 상태로 회귀)"
        )

    def test_quoted_criticism_of_someone_elses_error_is_suppressed(self) -> None:
        """남의 오답을 인용해 비판하는 문장 — 그 학생이 그 오개념을 가진 것이 아니다."""
        text = "친구는 (a+b)² 를 a² + b² 라고 했는데 틀렸어"
        assert "distribution-over-power" not in [m.misconception.id for m in diagnose(text)]

    # ── 아래 4건이 이 설계의 본체다: **억제되면 안 되는** 경우 ──

    def test_self_correction_in_an_earlier_clause_does_not_silence_a_later_error(self) -> None:
        """[대조군·핵심] 앞 단계에서 스스로 정정하고 뒤 단계에서 오개념을 저지른 풀이.

        텍스트 전체 스코프를 택했다면 "잘못" 한 단어 때문에 이 진단이 사라진다. 그러면
        **자기 오류를 언어화한 학생일수록 진단을 덜 받는** 역선택이 되고, 그건 이 프로젝트가
        기르려는 바로 그 메타인지 행동에 침묵으로 보상하는 것이다. 게다가 미검출은 아무도
        소리내지 않는다 — 이 픽스처가 그 침묵을 소리내게 하는 자리다.
        """
        text = (
            "1) 처음에 -3을 +3으로 잘못 옮겨 적어서 고쳤다.\n2) x²=2x 이므로 양변을 x로 나누면 x=2."
        )
        assert "root-loss-by-dividing" in [m.misconception.id for m in diagnose(text)]

    def test_numbered_steps_without_punctuation_still_split_into_clauses(self) -> None:
        """[대조군] 구두점 없는 손글씨 전사 — 번호 매김이 절 경계여야 한다.

        문장부호에만 기대면 이런 텍스트는 전체가 한 문장이 되어 **문장 스코프가 텍스트 전체
        스코프로 조용히 붕괴**한다(교수학 판정 실측: 64/64 오억제). OCR·손글씨 경로에서
        구두점 없는 전사는 예외가 아니라 기본에 가깝다.

        **픽스처 주의**: 정정 어휘가 신호에서 근접 창 **안**에 있어야 이 절을 밟는다. 초안은
        "부호를 잘못 봐서 고침"이었는데 `잘못`이 `양변`에서 정규형 11자 떨어져 lookbehind
        12자 창을 **한 글자 차이로 벗어났다** — 번호 경계를 지워도 통과해서 뮤테이션 M1이
        살아남았다. 즉 이름은 '번호 경계'인데 코드는 그 절을 지나가지 않았다.
        """
        text = "1) 부호가 잘못 2) x²=2x 양변을 x로 나누면 x=2"
        assert "root-loss-by-dividing" in [m.misconception.id for m in diagnose(text)]

    def test_correction_in_a_previous_sentence_does_not_reach_across_the_period(self) -> None:
        """[대조군] 정정이 신호와 **가깝지만 다른 절**이면 억제하지 않는다.

        위 번호 경계 테스트와 짝이면서 다른 절을 밟는다 — 이쪽은 마침표 경계다. 정정 어휘가
        창 거리 안(정규형 3자)에 있으므로, 절 경계가 없으면 반드시 억제된다.
        경계를 통째로 없애는 뮤테이션(=텍스트 전체 스코프로의 붕괴)이 여기서 잡힌다.
        """
        text = "부호를 잘못 봤다. 양변을 x로 나누면 x=2"
        assert "root-loss-by-dividing" in [m.misconception.id for m in diagnose(text)]

    def test_distant_correction_in_the_same_clause_does_not_suppress(self) -> None:
        """[대조군] 같은 절이어도 창 밖이면 억제하지 않는다 — 창 계산이 신호 위치 기준인지.

        `_signal_span`이 `_signal_hit`과 다른 규칙을 쓰면(예: 항상 0에서 시작) 창이 절 머리에
        열려 먼 정정까지 삼킨다. 이 픽스처는 정정을 절 머리에, 신호를 창 밖(정규형 15자)에
        두어 그 차이를 드러낸다 — 없으면 `_signal_span` 뮤테이션이 살아남는다.
        """
        text = "잘못 적었던 부분을 고치고 다시 계산하면 양변을 x로 나누면 x=2"
        assert "root-loss-by-dividing" in [m.misconception.id for m in diagnose(text)]

    def test_contrastive_ani_connective_is_not_a_correction_marker(self) -> None:
        """[대조군·언어] 연결형 `아니`는 정정 표지가 아니라 **대조 표지**다.

        "A가 아니라 B다"는 오개념을 *부정*하는 말이 아니라 *주장*하는 가장 흔한 형식이다.
        `catalog.EXPLICIT_CORRECTION_MENTION`을 그대로 쓰면 이 문장이 억제돼
        `TestRefutingRegex::test_negated_zero_root_is_not_a_refutation`이 지키던 것을 잃는다
        (실제로 1차 구현에서 그 테스트가 red를 냈다 — 이 저장소가 PR #1039에서 이미 한 번
        싸운 결함의 재발이었다). 그래서 이 축은 종결형만 정정으로 본다.
        """
        text = "x²=2x에서 x=0은 근이 아니므로 양변을 x로 나누면 x=2다"
        assert "root-loss-by-dividing" in [m.misconception.id for m in diagnose(text)]

    def test_numeric_signal_window_opens_at_the_signal_not_the_clause_head(self) -> None:
        """[대조군] **숫자 signal**(`"0"`)도 창이 신호 위치에서 열린다.

        `_signal_span`은 `_signal_hit`처럼 두 갈래다 — 숫자·단일 영문자는 경계 정규식,
        나머지는 substring. 위 픽스처들은 전부 `양변`·`x로 나누` 같은 substring 갈래라
        **경계 정규식 갈래를 한 번도 밟지 않았다**(뮤테이션 M9 생존으로 발각). 여기서
        `division-by-zero`의 `"0"`으로 그 갈래를 밟는다: 정정이 절 머리에, 숫자 신호가
        창 밖(정규형 18자)에 있으므로 창이 신호 기준으로 열려야만 진단이 살아남는다.
        """
        text = "잘못 적었던 부분을 고치고 다시 계산하니 분모가 0"
        assert "division-by-zero" in [m.misconception.id for m in diagnose(text)]

    def test_suppression_still_works_in_a_later_clause_of_a_long_solution(self) -> None:
        """[억제] 앞 절이 긴 다중 절 풀이에서도 뒤 절의 정정이 인지된다.

        창은 **그 절 안의** 신호 위치를 기준으로 열려야 한다. 전체 텍스트 기준 위치를 쓰면
        앞 절 길이만큼 밀려 창이 절 끝 밖으로 나가고, 정정이 있는데도 못 잡는다
        (뮤테이션 M3). 앞 절이 짧으면 밀림이 작아 우연히 통과하므로 **길게** 잡았다 —
        초안(28자)으로는 밀림이 창 안에 흡수돼 M3가 살아남았고, 함수 수준에서 원본과
        출력이 실제로 갈리는 길이를 찾아 교체했다.
        """
        text = (
            "앞에서 계수를 정리하고 공통인수를 묶고 다시 한 번 검토한 뒤에 아래를 적었다. "
            "양변을 x로 나누면 x=2라는 풀이는 틀렸다"
        )
        assert "root-loss-by-dividing" not in [m.misconception.id for m in diagnose(text)]

    def test_self_correction_joined_by_the_connective_go_does_not_silence(self) -> None:
        """[대조군] 연결어미 `-고`로 이어진 자기정정은 뒤 절의 오개념을 죽이지 않는다.

        **MISC-25 착지분의 실측된 결함**이다(MISC-26에서 발견·수정). 그때 대조군 픽스처가
        전부 마침표·번호를 써서 이 형태를 한 번도 밟지 않았고, 한국어 풀이가 구두점 없이
        절을 잇는 가장 흔한 방식이 바로 `-고`다.
        """
        for text in (
            "부호를 잘못 봤고 양변을 x로 나누면 x=2다",
            "앞에서 틀린 부분을 고치고 양변을 x로 나누면 x=2다",
        ):
            assert "root-loss-by-dividing" in [m.misconception.id for m in diagnose(text)], text

    def test_quotative_rago_is_not_a_clause_boundary(self) -> None:
        """인용격 `라고`는 절 경계가 아니다 — 빼지 않으면 인용 비판의 억제가 풀린다.

        `-고`를 경계로 넣을 때 `라고`·`다고`를 제외하지 않으면
        "친구는 (a+b)²를 a²+b²**라고** 했는데 틀렸어"가 인용 앞뒤로 갈려, 남의 오답을
        비판하는 문장에 확신 오진단이 나간다. 위 `-고` 테스트와 반대 방향의 짝이다 —
        한쪽만 두면 "`-고`를 통째로 경계에서 뺐다"도 같은 초록을 낸다.
        """
        text = "친구는 (a+b)² 를 a² + b² 라고 했는데 틀렸어"
        assert "distribution-over-power" not in [m.misconception.id for m in diagnose(text)]

    def test_weak_signals_do_not_anchor_a_correction_window(self) -> None:
        """[대조군] 숫자 signal(`"0"`)은 창을 열지 않는다 — 정의역 조건문에 딸려 나오기 때문.

        "분모가 0이면 나눌 수 있다고 봤고 x=0은 근이 아니다"에서 뒤 절의 `아니다`는
        *제로근*을 부정하는 말이지 나눗셈 오개념을 부정하는 말이 아니다. 그런데 뒤 절의
        `0`이 신호로 잡혀 창을 열면 그 `아니다`가 `division-by-zero`를 삼킨다(실측).
        비용은 0이다 — 신호가 전부 약한 카탈로그 항목은 없다(실측 확인).
        """
        text = "분모가 0이면 나눌 수 있다고 봤고 x=0은 근이 아니다"
        assert "division-by-zero" in [m.misconception.id for m in diagnose(text, top_k=70)]

    def test_genuine_refutation_after_a_connective_is_still_suppressed(self) -> None:
        """`-지만` **뒤**의 진짜 반박은 억제된다 — 연결어미를 경계로 넣지 않은 이유.

        "…라고 봤지만 틀렸다"의 `틀렸다`는 실제로 앞 주장을 반박하므로 갈라 놓으면 반박을
        잃는다. 그래서 `-지만`·`-는데`는 경계가 아니다.

        ⚠️ **알려진 한계(이 테스트가 지키는 것의 이면)**: 같은 연결어미가 반대 뜻으로도
        쓰인다 — "부호가 잘못됐**지만** 양변을 x로 나누면 x=2다"는 *다른 것*을 정정하고
        이 오개념을 저지른 문장인데 현재 억제된다(미검출). 두 문장은 연결어미만으로는
        구별 불가이고, 이것이 `MISC-28`(귀속 판정)의 근거다. 어휘를 넓히면 이 미검출
        경로가 **함께 넓어지므로**, MISC-26은 어휘 확장을 채택하지 않았다.
        """
        text = "양변을 x로 나누면 x=2라고 봤지만 틀렸다"
        assert "root-loss-by-dividing" not in [m.misconception.id for m in diagnose(text)]

    def test_distant_correction_referring_to_an_earlier_step_does_not_suppress(self) -> None:
        """[대조군] 같은 절 안이어도 **창 밖**(정규형 16자)의 정정은 이 오개념을 안 가린다.

        "양변을 x로 나누면 x=2인데 앞의 계산이 틀렸다" — `틀렸다`가 가리키는 것은 *앞의
        계산*이고 근 손실은 그대로 저질러졌다. 창을 옛 24로 되돌리면 여기까지 닿아 억제된다.

        이 픽스처가 필요한 이유: MISC-26에서 절 경계에 연결어미 `-고`가 추가되면서, 창 크기를
        고정하던 원래 사례("…있다고 봤고 x=0은 근이 아니다")가 **절 분리로 먼저 보호**받게
        됐다. 그 결과 창 크기 뮤테이션(12→24)이 살아남았다 — 방어가 다른 절로 옮겨 갔을 뿐인데
        "창 크기가 검사됐다"고 읽힐 자리다. 그래서 창만이 막는 사례를 따로 둔다.
        """
        text = "양변을 x로 나누면 x=2인데 앞의 계산이 틀렸다"
        assert "root-loss-by-dividing" in [m.misconception.id for m in diagnose(text)]

    def test_plain_misconception_without_any_correction_is_unaffected(self) -> None:
        """[대조군] 정정 어휘가 없는 순수 오개념은 그대로 진단된다(과잉 억제 아님)."""
        assert "root-loss-by-dividing" in [
            m.misconception.id for m in diagnose("x²=2x 양변을 x로 나누면 x=2")
        ]

    def test_sentence_final_anida_is_a_correction_marker(self) -> None:
        """종결형 `아니다`는 정정으로 본다 — 연결형과의 구별이 실제로 작동하는지 확인.

        위 `test_contrastive_ani_connective_...`와 짝이다. 한쪽만 두면 "아니 계열을 전부 뺐다"와
        "종결형만 남겼다"가 같은 초록을 낸다.
        """
        assert "root-loss-by-dividing" not in [
            m.misconception.id for m in diagnose("양변을 x로 나누면 x=2인 것은 아니다")
        ]


class TestOverSuppressionIsMeasured:
    """MISC-28 — 반대 방향(오억제)이 측정되고 보고서에 **함께** 나온다.

    왜 필요한가: 사각 축만 보면 **과잉 억제가 개선으로 보인다**. 무엇이든 억제하면 사각은
    0%가 되기 때문이다. 실제로 그 상태였다 — `explicit_correction_gap_eval`이 "사각 0%"를
    내는 동안 오억제는 **100%**였고, 그 사실이 어느 화면에도 없었다.

    측정 설계의 핵심은 **변수 통제**다. 1차 측정은 연결어미마다 정정 어휘를 다르게 써서
    `-는데`만 오억제 0%가 나왔고, 그것을 "연결어미 차이"로 읽을 뻔했다 — 실제 원인은 그
    접두에만 정정 어휘가 없었던 것이다. 그래서 어휘를 `잘못` 하나로 고정하고 연결어미만
    바꾼다. 대조군(정정 어휘 없음)이 그 통제가 실제로 걸렸는지 보여 준다.
    """

    def test_every_connective_prefix_holds_the_correction_word_constant(self) -> None:
        """세_연결어미_접두가_같은_정정_어휘를_쓴다 — 변수 통제가 코드에 고정돼 있다

        이 단언이 없으면 누군가 접두 하나를 "자연스럽게" 고치다가 어휘를 바꿔 버리고,
        그러면 측정이 다시 두 변수를 섞는다(1차 측정에서 실제로 일어난 일이다).
        """
        connective = [
            prefix
            for label, prefix in gap_eval.FOREIGN_CORRECTION_PREFIXES
            if not label.startswith("[대조군]")
        ]
        assert len(connective) == 3, "연결어미 3종(-지만·-어서·-는데)을 전부 밟아야 한다"
        assert all("잘못" in p for p in connective), "정정 어휘가 접두마다 다르면 변수가 섞인다"

    def test_control_prefix_carries_no_correction_word(self) -> None:
        """대조군_접두에는_정정_어휘가_없다 — 이것이 없으면 '무엇이든 억제'와 구별되지 않는다"""
        control = [
            prefix
            for label, prefix in gap_eval.FOREIGN_CORRECTION_PREFIXES
            if label.startswith("[대조군]")
        ]
        assert len(control) == 1
        assert not any(w in control[0] for w in ("잘못", "틀리", "틀렸", "오답", "아니"))

    def test_control_prefix_is_not_suppressed(self) -> None:
        """[대조군] 정정_어휘가_없으면_억제되지_않는다

        억제가 *정정 어휘* 때문임을 보인다. 대조군까지 억제되면 그것은 귀속 문제가 아니라
        접두 문장 자체가 진단을 죽이는 것이고, 그러면 이 측정 전체가 무의미하다.
        """
        control = [
            r for r in gap_eval.measure_over_suppression() if r.prefix_label.startswith("[대조군]")
        ]
        assert control, "대조군 측정이 0건 — 스캔 0건은 실패다"
        assert not any(r.suppressed for r in control)

    def test_report_shows_both_directions(self) -> None:
        """보고서가_사각과_오억제를_한_화면에_낸다 — 한쪽만 보고 '해결됐다'고 적지 못하게"""
        rendered = gap_eval.format_report(gap_eval.evaluate())
        assert "사각" in rendered
        assert "오억제" in rendered, "반대 방향이 빠지면 과잉 억제가 개선으로 보인다"
        assert "억제되면 안 된다" in rendered, "대조군 행의 기대 방향이 화면에 없다"


# ──────────────────────────────────────────────────────────────────────────
# MISC-28 ⓒ — 3-state 강등(귀속 불명 = 억제도 진단도 아닌 **보류**)
# ──────────────────────────────────────────────────────────────────────────
class TestCorrectionAttributionIsThreeState:
    """Kiki 판정(2026-09-12 · 게이트 `G-misc28-attribution-seat`)의 계약 동결.

    판정 원문 취지: "목표가 정답률 최대화가 아니라 학생에게 **잘못된 확신**을 주는 오류를
    최소화하는 것이다. 귀속이 불명확한데 바로 '네가 틀렸다'고 판정하는 것보다, 판정을
    보류하고 한 번 확인하는 상태를 두는 편이 교육적으로 안전하다."

    그 판정이 필요한 이유는 이 교환표다(MISC-28 전수 실측 · 카탈로그 66종):

        현행(양방향 억제)  : 오억제 66/66(100%) · 선행정정 사각  0/66(  0%)
        뒤돌아보기 끔       : 오억제  2/66(  3%) · 선행정정 사각 66/66(100%)

    2상태로는 어느 쪽을 골라도 *틀린 확신*이 나간다. 그래서 세 번째 상태를 둔다.
    """

    # ── 세 상태가 각각 실제로 발생하는가 (성공 방향 대조군 포함) ──

    def test_correction_after_signal_is_refuted_and_suppressed(self) -> None:
        """신호_뒤의_정정은_확정_반박이다 — 어순으로 귀속이 확정되므로 종전대로 억제(None)

        이 단언이 없으면 "전부 보류로 강등"이라는 과잉 수정이 통과한다 — 그러면 MISC-25가
        막은 사각(정답을 쓴 학생에게 반례가 나가는 것)이 *보류 플래그를 단 채* 되살아난다.
        """
        m = CATALOG_BY_ID["root-loss-by-dividing"]
        assert (
            classify_correction_attribution(m, "x²=2x 양변을 x로 나누면 x=2라는 풀이는 틀렸다")
            == "refuted"
        )
        assert "root-loss-by-dividing" not in [
            x.misconception.id for x in diagnose("x²=2x 양변을 x로 나누면 x=2라는 풀이는 틀렸다")
        ]

    def test_correction_before_signal_is_unclear_not_suppressed(self) -> None:
        """신호_앞의_정정은_귀속_불명이다 — 매칭은 살고 플래그가 선다

        이것이 오억제 100%를 끊는 자리다: "부호를 잘못 옮겨 적었지만 <오개념>"이라고 쓴
        학생이 **어떤 오개념도 진단받지 못하던** 상태의 해소.

        **픽스처 주의**(같은 파일 `test_numbered_steps_…`의 교훈 재적용): 정정 어휘가 신호에서
        lookbehind 창(12자) **안**에 있어야 이 절을 밟는다. 초안은 "…적었지만 x²=2x 양변을…"
        이었는데 사이에 낀 수식 때문에 `잘못`이 창을 **한 글자 차이로** 벗어나 `none`이 나왔다
        — 이름은 '선행 정정'인데 코드는 그 분기를 지나가지 않았다. 측정 하네스
        (`explicit_correction_gap_eval`)의 프로브와 같은 밀착 형태로 고정한다.
        """
        text = "부호를 잘못 옮겨 적었지만 양변을 x로 나누면 x=2"
        m = CATALOG_BY_ID["root-loss-by-dividing"]
        assert classify_correction_attribution(m, text) == "unclear"
        hit = [x for x in diagnose(text) if x.misconception.id == "root-loss-by-dividing"]
        assert hit, "오억제가 되살아났다 — 무관한 정정이 진단을 통째로 죽이면 안 된다"
        assert hit[0].attribution_unclear is True

    def test_no_correction_word_leaves_the_flag_down(self) -> None:
        """[대조군] 정정_어휘가_없으면_플래그도_없다 — 항상 True면 게이트 ③이 상시 발동한다"""
        text = "x²=2x 양변을 x로 나누면 x=2"
        m = CATALOG_BY_ID["root-loss-by-dividing"]
        assert classify_correction_attribution(m, text) == "none"
        hit = [x for x in diagnose(text) if x.misconception.id == "root-loss-by-dividing"]
        assert hit and hit[0].attribution_unclear is False

    def test_correction_outside_the_clause_is_not_attributed_at_all(self) -> None:
        """[대조군] 다른_절의_정정은_세_상태_중_none이다 — MISC-25의 절 경계가 여전히 산다

        자기 오류를 언어화한 학생일수록 진단을 덜 받는 역선택을 막는 자리다. 여기서 `unclear`가
        나오면 그 학생은 *보류*로 강등돼 확신 진단을 못 받는다 — 억제보다는 낫지만 여전히
        MISC-25가 지킨 것을 잃는다.
        """
        text = (
            "1) 처음에 -3을 +3으로 잘못 옮겨 적어서 고쳤다.\n2) x²=2x 이므로 양변을 x로 나누면 x=2."
        )
        m = CATALOG_BY_ID["root-loss-by-dividing"]
        assert classify_correction_attribution(m, text) == "none"
        hit = [x for x in diagnose(text) if x.misconception.id == "root-loss-by-dividing"]
        assert hit and hit[0].attribution_unclear is False

    def test_clause_boundary_still_scopes_the_three_state_verdict(self) -> None:
        """[절 경계] 앞_절의_정정은_창_안이어도_다른_절이면_none이다 — MISC-25 스코프 보존

        **픽스처 주의**(2026-09-07 규칙 "픽스처가 그 절을 실제로 밟는가"): 절 경계를 지우는
        뮤테이션(M7)이 이 절에 닿으려면 정정 어휘가 *경계 너머*에 있으면서 동시에 *창 안*에
        있어야 한다. 위 `test_correction_outside_the_clause_…`의 번호 매김 픽스처는 거리가
        멀어 경계를 지워도 `none`이라 M7이 **살아남았다**. 여기서는 마침표 하나만 사이에 둔다:

            부호를 잘못 봤다. 양변을 x로 나누면 x=2
                     └── 경계를 지우면 `양변` 앞 8자 안에 들어온다

        경계가 살아 있으면 `none`, 죽으면 `unclear`다.
        """
        m = CATALOG_BY_ID["root-loss-by-dividing"]
        assert (
            classify_correction_attribution(m, "부호를 잘못 봤다. 양변을 x로 나누면 x=2") == "none"
        )

    def test_refuted_wins_over_unclear_when_both_directions_carry_a_correction(self) -> None:
        """양쪽에_다_정정이_있으면_뒤쪽이_이긴다 — 확정이 불명을 이긴다(순서 의존 금지)

        `verdict`를 덮어쓰는 순서만 바꿔도 통과하는 단언이면 무의미하므로, 앞쪽 정정을
        **먼저** 만나는 배치로 고정한다. `unclear`가 뒤늦게 나온 `refuted`를 덮으면 RED다.
        """
        m = CATALOG_BY_ID["root-loss-by-dividing"]
        text = "부호를 잘못 봤는데 양변을 x로 나누면 x=2라는 풀이는 틀렸다"
        assert classify_correction_attribution(m, text) == "refuted"

    # ── 게이트 ③ — 보류가 실제로 확신을 막는가 ──

    def test_gate_flags_when_top1_is_unclear(self) -> None:
        """게이트_③이_top1의_보류를_승격한다 — L4 판정이 API까지 닿는 경로"""
        text = "부호를 잘못 옮겨 적었지만 양변을 x로 나누면 x=2"
        gated = apply_match_quality_gate(diagnose(text))
        assert gated.matches, "매칭이 유지돼야 한다(보류≠억제)"
        assert gated.attribution_unclear is True

    def test_gate_does_not_flag_when_top1_is_clear(self) -> None:
        """[대조군] top1이_깨끗하면_플래그가_서지_않는다 — 학생에게 발화되는 것이 top-1이다"""
        gated = apply_match_quality_gate(diagnose("x²=2x 양변을 x로 나누면 x=2"))
        assert gated.matches
        assert gated.attribution_unclear is False

    def test_gate_does_not_flag_when_confidence_floor_emptied_the_list(self) -> None:
        """[대조군] 게이트_①이_비우면_보류할_판정_자체가_없다 — 빈 리스트에 인덱싱하지 않는다"""
        text = "부호를 잘못 옮겨 적었지만 양변을 x로 나누면 x=2"
        gated = apply_match_quality_gate(diagnose(text), confidence_floor=1.1)
        assert gated.matches == []
        assert gated.no_confident_match is True
        assert gated.attribution_unclear is False

    def test_confidence_scale_is_untouched_by_the_hold(self) -> None:
        """보류가_confidence를_깎지_않는다 — `refuting_regex` docstring의 '왜 감점이 아닌가'

        귀속 불명은 *신뢰도가 낮은 것*이 아니라 **다른 축**이다. 감점으로 구현하면 "얼마나
        깎을 것인가"라는 답 없는 눈금 문제가 돌아오고, 깎인 후보가 하류에 약한 증거로 남는다.
        """
        clear = "x²=2x 양변을 x로 나누면 x=2"
        held = "부호를 잘못 옮겨 적었지만 양변을 x로 나누면 x=2"

        def _conf(text: str) -> float:
            hit = [x for x in diagnose(text) if x.misconception.id == "root-loss-by-dividing"]
            assert hit
            return hit[0].confidence

        assert _conf(held) == _conf(clear)


class TestHeldVerdictAxisIsMeasured:
    """MISC-28 ⓒ — 세 번째 축(보류)이 측정되고 보고서에 **함께** 나온다.

    왜 필요한가: ⓒ는 전치 정정을 억제에서 *보류*로 바꿨다. 그러면 사각 축(`gap`)이 이
    형태를 더는 0%로 보증하지 않는다 — 도달하기 때문이다. 보증해야 하는 것이 "도달하지
    않는다"에서 "도달하되 확신을 보류한다"로 바뀌었으므로 측정도 같이 바뀌어야 한다.
    이 축이 없으면 위 두 표가 "오억제 100%→3%"라는 좋은 숫자만 남기고 **그 대가를 감춘다**.
    """

    def test_no_confident_verdict_leaks_on_prefix_labels(self) -> None:
        """전치_라벨에서_확신_진단이_새지_않는다 — 이 축의 유일한 실패 모드

        `reaches and not held`가 곧 "남의 오답을 인용해 비판한 학생에게 '네가 틀렸다'가
        나가는" 상태다. Kiki 판정이 최소화하라고 지목한 바로 그 오류다.
        """
        rows = gap_eval.measure_held_verdicts()
        assert rows, "보류 축 측정이 0건 — 스캔 0건은 실패다"
        leaked = [r for r in rows if r.confident_and_wrong]
        assert not leaked, "전치 정정 라벨에서 확신 진단이 샜다: " + ", ".join(
            f"{r.kebab_id}({r.label!r})" for r in leaked[:5]
        )

    def test_prefix_labels_still_reach_rather_than_being_suppressed(self) -> None:
        """[대조군] 전치_라벨이_도달은_한다 — 전부 억제되면 ⓒ가 아니라 종전 동작이다

        이 단언이 없으면 "전부 억제"라는 ⓒ 이전 상태가 `confident_and_wrong` 0건으로
        **초록을 낸다** — 도달이 0이면 누출도 0이기 때문이다(공허한 통과).
        """
        rows = [r for r in gap_eval.measure_held_verdicts() if not r.is_control]
        assert rows
        assert all(r.reaches for r in rows), "전치 라벨이 억제됐다 — 보류가 아니라 종전 동작"
        assert all(r.held for r in rows), "도달했는데 보류 플래그가 없다"

    def test_control_prefix_reaches_without_being_held(self) -> None:
        """[대조군] 정정_어휘가_없는_접두는_도달하되_보류되지_않는다

        이 축의 변별력이 전부 여기 걸려 있다. 대조군이 없으면 `held`가 `reaches`와 구별되지
        않아 "도달하면 보류로 친다"는 측정 결함이 **살아남는다**(뮤테이션 M13 실측 — 대조군을
        넣기 전에는 그 뮤테이션이 전건 초록이었다). 즉 보류 플래그가 *정정 어휘*를 따라가는지,
        그냥 *도달*을 따라가는지를 가르는 유일한 행이다.
        """
        control = [r for r in gap_eval.measure_held_verdicts() if r.is_control]
        assert control, "대조군 측정이 0건 — 스캔 0건은 실패다"
        assert all(r.reaches for r in control), "대조군이 도달조차 못 하면 비교가 성립하지 않는다"
        assert not any(
            r.held for r in control
        ), "정정 어휘가 없는 접두가 보류됐다 — 플래그가 어휘가 아니라 도달을 따라가고 있다"

    def test_report_shows_the_held_axis(self) -> None:
        """보고서가_세_축을_한_화면에_낸다 — 한쪽만 보고 '해결됐다'고 적지 못하게"""
        rendered = gap_eval.format_report(gap_eval.evaluate())
        assert "사각" in rendered
        assert "오억제" in rendered
        assert "보류 축" in rendered, "ⓒ의 대가가 화면에서 빠지면 좋은 숫자만 남는다"
        assert "확신 누출" in rendered
        assert "0이어야 한다" in rendered, "기대 방향이 화면에 없으면 숫자를 읽을 기준이 없다"
