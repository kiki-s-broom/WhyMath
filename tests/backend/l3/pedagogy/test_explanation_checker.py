"""explanation_checker(F7 언어 수준 결함 검출기) 단위 테스트 — 순수 규칙·hermetic.

검증 축: ①미도입 구조 어휘 검출(F7) ②이미 도입된 구조는 통과(오탐 없음) ③밴드별 경계
(고등/대학처럼 전 구조 도입된 밴드는 검출 대상이 구조적으로 없음).
"""

from __future__ import annotations

from whymath_backend.l3.pedagogy.explanation_checker import (
    CONSTRUCT_VOCABULARY,
    check_explanation_language_level_defect,
)
from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.speech import SpeechGradeBand

_ARITHMETIC_ONLY: frozenset[str] = frozenset({"fraction", "power", "abs", "factorial"})
_WITH_ROOT_TRIG: frozenset[str] = _ARITHMETIC_ONLY | {"root", "subscript", "trig"}
_FULL: frozenset[str] = _WITH_ROOT_TRIG | {
    "log",
    "integral",
    "sum",
    "product",
    "limit",
    "derivative",
    "binom",
}


class TestUnintroducedConstructDetection:
    def test_derivative_vocabulary_flags_f7_for_elementary(self) -> None:
        text = "미분은 순간의 변화율을 구하는 방법이다."
        result = check_explanation_language_level_defect(
            SpeechGradeBand.초등, text, introduced_constructs=_ARITHMETIC_ONLY
        )
        assert result is GenerationFailureCode.F7

    def test_each_vocabulary_term_maps_to_a_missing_construct_flags_f7(self) -> None:
        """어휘 사전 전량이 실제로 검출 신호가 됨을 봉인(사전에 죽은 항목이 없게)."""
        for term, construct in CONSTRUCT_VOCABULARY.items():
            introduced_without = _FULL - {construct}
            result = check_explanation_language_level_defect(
                SpeechGradeBand.대학,
                f"이 개념은 {term}과 관련이 있다.",
                introduced_constructs=introduced_without,
            )
            assert result is GenerationFailureCode.F7, f"{term!r}({construct!r}) 미검출"

    def test_introduced_construct_vocabulary_passes(self) -> None:
        """중등에 이미 도입된 root/trig 어휘는 걸리지 않는다(오탐 없음 — 경계 스트레스)."""
        text = "제곱근을 구하고 사인 값을 이용해 비율을 계산한다."
        result = check_explanation_language_level_defect(
            SpeechGradeBand.중등, text, introduced_constructs=_WITH_ROOT_TRIG
        )
        assert result is None

    def test_clean_arithmetic_only_text_passes_for_elementary(self) -> None:
        text = "분수는 전체를 똑같이 나눈 것 중 몇 조각인지를 나타낸다."
        result = check_explanation_language_level_defect(
            SpeechGradeBand.초등, text, introduced_constructs=_ARITHMETIC_ONLY
        )
        assert result is None

    def test_full_introduced_set_never_flags(self) -> None:
        """전 구조 도입 상태(고등/대학)라면 사전의 모든 어휘가 등장해도 결함이 아니다."""
        text = " ".join(CONSTRUCT_VOCABULARY.keys())
        result = check_explanation_language_level_defect(
            SpeechGradeBand.고등, text, introduced_constructs=_FULL
        )
        assert result is None

    def test_empty_introduced_constructs_flags_any_vocabulary_term(self) -> None:
        result = check_explanation_language_level_defect(
            SpeechGradeBand.초등, "로그를 계산한다.", introduced_constructs=frozenset()
        )
        assert result is GenerationFailureCode.F7

    def test_no_vocabulary_terms_present_passes_trivially(self) -> None:
        result = check_explanation_language_level_defect(
            SpeechGradeBand.초등, "오늘은 날씨가 좋다.", introduced_constructs=frozenset()
        )
        assert result is None
