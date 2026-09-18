"""오답 서명 검출기 — 알려진 오답 패턴 N종 + **변별력 주입** (EOS-104).

이 파일이 지키려는 것은 둘이다.

1. **잡아야 할 것을 잡는가** — P-07 기준 예시(`(x+2)² → x²+4`)를 포함한 오답 패턴들이
   `cross_term_omission` 계열(`distribution-over-power`) 후보로 `{id, confidence}` 형태로 나온다.
2. **안 잡아야 할 것을 안 잡는가(변별력)** — 정답·무관한 오답·우연히 참인 등식에서 초록이어야
   한다. 그리고 그 초록이 *위장*이 아님을 보이려고, 각 패턴의 **핵심 조각을 실제로 제거해**
   탐지가 사라지는지 확인한다(CLAUDE.md 2026-09-01 "보호 장치를 실패 주입 없이 선언 금지").
   정상 입력에서 초록인 것은 보호의 증거가 아니다 — *모든* 입력에서 초록인 검출기도 같은
   화면을 낸다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l4.misconception.answer_signature import (
    AttemptMisconceptionScanResult,
    detect_signature_matches,
    extract_error_signature,
    scan_attempt_answer,
)
from whymath_backend.schema.assessment_evidence import MisconceptionScan

_CROSS_TERM = "distribution-over-power"
"""`(a+b)² = a²+b²` — 교차항(2ab) 누락. P-07이 말하는 cross_term_omission 계열의 정본 kebab id."""


def _scan(question: str, answer: str | None) -> AttemptMisconceptionScanResult:
    return scan_attempt_answer(question_text=question, student_answer=answer)


def _ids(result: AttemptMisconceptionScanResult) -> list[str]:
    return [c.misconception_id for c in result.candidates]


# ── ① 잡아야 할 것 — 알려진 오답 패턴 N종 ────────────────────────────────────────
#: (발문, 오답, 기대 오개념 id). 표기 변이(ASCII `^` / 유니코드 `²`)·변수명 변이·수치
#: 인스턴스를 섞는다 — 이 채널의 주장이 "문자열 일치"가 아니라 **구조 정합**이기 때문이다.
_CAUGHT: list[tuple[str, str, str]] = [
    # P-07 기준 예시 그대로.
    ("(x+2)²을 전개하시오.", "x²+4", _CROSS_TERM),
    # 같은 오류의 ASCII 표기 — 표기가 달라도 같은 구조다.
    ("(x+2)^2을 전개하시오.", "x^2+4", _CROSS_TERM),
    # 변수명이 다른 기호 인스턴스 — substring 신호였다면 놓쳤을 자리.
    ("다음 식 (p+q)²을 전개하시오.", "p²+q²", _CROSS_TERM),
    # 수치 인스턴스 — 학생이 구체 수로 거짓 규칙을 적용한 흔적.
    ("(3+4)²의 값을 구하시오.", "3²+4²", _CROSS_TERM),
    # 계수가 붙어도 구조는 같다(명시 곱셈 표기 — 암묵 곱셈은 아래 한계 테스트 참조).
    ("(2*x+3)²을 전개하시오.", "4*x²+9", _CROSS_TERM),
]


@pytest.mark.parametrize(("question", "answer", "expected"), _CAUGHT)
def test_known_wrong_answer_patterns_yield_gated_candidate(
    question: str, answer: str, expected: str
) -> None:
    """알려진 오답 패턴 → 게이트 통과 후보 `{misconception_id, confidence}`."""
    result = _scan(question, answer)
    assert result.scan is MisconceptionScan.RAN_WITH_CANDIDATES
    assert expected in _ids(result)
    top = result.candidates[0]
    # P-07 산출 형태: id + confidence. 게이트를 통과했음을 후보가 자기 기술한다.
    assert top.gate_passed is True
    assert 0.0 < top.confidence <= 1.0


def test_candidate_id_comes_from_catalog_not_a_new_scheme() -> None:
    """후보 id는 **카탈로그 kebab id**다 — crosswalk(M-id)를 여기서 만들지 않는다.

    새 ID 체계를 만들면 kebab↔M-id 사람 승인 게이트(crosswalk_gate_contract.md)를 우회하게
    된다. 이 단언이 그 우회를 막는 자리다.
    """
    from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID

    result = _scan("(x+2)²을 전개하시오.", "x²+4")
    for candidate in result.candidates:
        assert candidate.misconception_id in CATALOG_BY_ID


def test_known_limitation_implicit_multiplication_is_not_parsed() -> None:
    """**알려진 한계(숨기지 않는다)**: 암묵 곱셈(`2x`)은 파싱되지 않아 탐지되지 않는다.

    `(2x+3)² = 4x²+9`는 구조적으로 `(2*x+3)² = 4*x²+9`와 같은 오류인데, 앞의 표기만 잡히지
    않는다. 원인은 이 모듈이 아니라 **공용 파싱 소스**(`l3.symbolic_equivalence.to_sympy_source`)
    가 `2x`에 곱셈 기호를 넣지 않아 `SympifyError`가 나는 것이다 — 동치 판정 권위가 소유한
    축이라 여기서 고치면 같은 질문에 두 개의 답이 생긴다.

    이 테스트가 존재하는 이유는 *지금 안 잡힌다*를 계약으로 박아 두기 위해서다. 한계를 테스트로
    남기지 않으면 나중에 누군가 이 채널의 0건을 "그런 오개념이 없었다"로 읽는다.
    승계 태스크: `MISC-33-implicit-multiplication-parse-gap`.
    """
    assert _CROSS_TERM not in _ids(_scan("(2x+3)²을 전개하시오.", "4x²+9"))
    # 같은 오류의 명시 곱셈 표기는 잡힌다 — 한계가 *표기*에 있음을 대조로 보인다.
    assert _CROSS_TERM in _ids(_scan("(2*x+3)²을 전개하시오.", "4*x²+9"))


# ── ② 안 잡아야 할 것 — 변별력의 대조군 ──────────────────────────────────────────
_NOT_CAUGHT: list[tuple[str, str, str]] = [
    ("(x+2)²을 전개하시오.", "x²+4x+4", "정답"),
    ("(x+2)²을 전개하시오.", "x²+5", "무관한 오답"),
    ("(x+0)²을 전개하시오.", "x²+0²", "우연히 참인 등식 — 낙인 금지"),
    ("(x+2)²을 전개하시오.", "모르겠어요", "수식이 아닌 답"),
]


@pytest.mark.parametrize(("question", "answer", "label"), _NOT_CAUGHT)
def test_no_candidate_when_pattern_absent(question: str, answer: str, label: str) -> None:
    """정답·무관 오답·우연히 참인 등식에는 후보가 붙지 않는다 — 훑었으나 0건."""
    result = _scan(question, answer)
    assert result.scan is MisconceptionScan.RAN_NO_CANDIDATE, label
    assert result.candidates == ()


# ── ③ 3상태 — 0건의 뜻이 둘이라는 것 ─────────────────────────────────────────────
def test_missing_answer_is_not_run_not_empty_result() -> None:
    """답안이 없으면 **훑지 않은 것**이다 — 빈 후보와 구별된다."""
    result = _scan("(x+2)²을 전개하시오.", None)
    assert result.scan is MisconceptionScan.NOT_RUN
    assert result.signature is None


def test_question_without_extractable_expression_is_not_run() -> None:
    """발문에서 식을 못 뽑으면 재료 부족 — 0건을 '오개념 없음'으로 읽히게 하지 않는다."""
    result = _scan("x를 구하라.", "3")
    assert result.scan is MisconceptionScan.NOT_RUN


def test_scanned_forms_discloses_channel_reach() -> None:
    """이 채널의 **사정거리**가 결과에 함께 실린다(작동한 비율 원칙).

    0건을 "카탈로그 67종 전체에 없었다"로 읽으면 거짓이다 — 이 채널은
    `canonical_wrong_form`을 가진 오개념만 본다.
    """
    from whymath_backend.l4.misconception.catalog import CATALOG

    expected = len([m for m in CATALOG if m.canonical_wrong_form is not None])
    result = _scan("(x+2)²을 전개하시오.", "x²+4x+4")
    assert result.scanned_forms == expected
    assert 0 < expected < len(CATALOG)


# ── ④ 변별력 주입 — 패턴 조각을 실제로 제거하면 탐지가 사라지는가 ──────────────────
#: (원본 오답, 무엇을 망가뜨렸나, 망가뜨린 오답). 각 줄은 "이 조각이 없으면 안 잡힌다"를
#: 주장하고, 테스트가 그 주장을 실행한다. `mutated != original`을 함께 단언해 **주입 자체가
#: 실제로 적용됐는지** 확인한다(2026-09-06 "주입 자체의 실재" — 미적용 주입은 통과로 위장된다).
_MUTATIONS: list[tuple[str, str, str]] = [
    ("x²+4", "제곱 하나를 지움(구조 정합 깨짐)", "x+4"),
    ("x²+4", "상수항을 정답의 교차항 포함형으로 되돌림", "x²+4x+4"),
    ("x²+4", "상수항 값을 바꿈(거짓 rhs 동치 깨짐)", "x²+7"),
    ("x²+4", "제곱을 세제곱으로(템플릿 지수 불일치)", "x³+4"),
]


@pytest.mark.parametrize(("original", "what_broke", "mutated"), _MUTATIONS)
def test_mutation_removes_detection(original: str, what_broke: str, mutated: str) -> None:
    """오답에서 패턴의 핵심 조각을 빼면 더 이상 잡히지 않는다 — 검출기의 변별력."""
    question = "(x+2)²을 전개하시오."
    assert mutated != original, "주입이 적용되지 않았다 — 이 테스트는 무효다"
    assert _CROSS_TERM in _ids(_scan(question, original)), "대조군(원본)이 애초에 안 잡힌다"
    assert _CROSS_TERM not in _ids(_scan(question, mutated)), what_broke


def test_mutating_the_question_expression_removes_detection() -> None:
    """*발문 쪽* 조각을 빼도 사라진다 — 탐지가 답안만 보고 있지 않다는 증거.

    같은 답안 `x²+4`가 발문이 `(x+2)²`일 때만 잡혀야 한다. 발문이 바뀌었는데도 잡힌다면
    검출기는 구조를 보는 것이 아니라 답안 문자열을 외운 것이다.
    """
    answer = "x²+4"
    assert _CROSS_TERM in _ids(_scan("(x+2)²을 전개하시오.", answer))
    assert _CROSS_TERM not in _ids(_scan("(x+3)²을 전개하시오.", answer))
    assert _CROSS_TERM not in _ids(_scan("x²+4를 인수분해하시오.", answer))


def test_gate_floor_actually_gates() -> None:
    """품질 게이트가 실제로 경유된다 — floor 미만 후보는 실릴 수 없다.

    검출 신뢰도를 floor 아래로 낮추면 `RAN_WITH_CANDIDATES`가 `RAN_NO_CANDIDATE`로 바뀌어야
    한다. 안 바뀌면 이 경로가 게이트를 **우회**하고 있다는 뜻이다(EOS-104 acceptance ⑤).
    """
    import whymath_backend.l4.misconception.answer_signature as mod

    question, answer = "(x+2)²을 전개하시오.", "x²+4"
    assert _scan(question, answer).scan is MisconceptionScan.RAN_WITH_CANDIDATES

    original = mod._STRUCTURAL_MATCH_CONFIDENCE
    mod._STRUCTURAL_MATCH_CONFIDENCE = 0.1  # 게이트 floor(0.65) 미만으로 주입
    try:
        assert mod._STRUCTURAL_MATCH_CONFIDENCE != original, "주입 미적용 — 테스트 무효"
        mutated = _scan(question, answer)
        assert mutated.scan is MisconceptionScan.RAN_NO_CANDIDATE
        assert mutated.candidates == ()
    finally:
        mod._STRUCTURAL_MATCH_CONFIDENCE = original
    assert mod._STRUCTURAL_MATCH_CONFIDENCE == original, "원복 실패 — 후속 테스트가 오염된다"


# ── ⑤ 서명 추출 — 결정론과 최장 우선 ─────────────────────────────────────────────
def test_signature_extraction_prefers_longest_expression() -> None:
    """부분식이 아니라 전체식을 고른다 — 학생이 다룬 대상일 가능성이 높은 쪽."""
    signature = extract_error_signature("(x+2)²을 전개하시오.", "x²+4")
    assert signature is not None
    assert signature.claimed_lhs == "(x+2)²"
    # 답안은 재해석하지 않고 제출 문자열 그대로.
    assert signature.claimed_rhs == "x²+4"


def test_detection_is_deterministic() -> None:
    """같은 입력에 같은 결과 — 판정이 흔들리면 증거가 재현 불가가 된다."""
    signature = extract_error_signature("(x+2)²을 전개하시오.", "x²+4")
    assert signature is not None
    first = [m.misconception.id for m in detect_signature_matches(signature)]
    second = [m.misconception.id for m in detect_signature_matches(signature)]
    assert first == second


def test_matched_signals_carry_no_student_text() -> None:
    """산출물에 학생 원문이 없다 — 미성년 PII는 추상 id·템플릿으로만 남긴다."""
    answer = "x²+4"
    signature = extract_error_signature("(x+2)²을 전개하시오.", answer)
    assert signature is not None
    for match in detect_signature_matches(signature):
        for signal in match.matched_signals:
            assert answer not in signal


# ── ⑥ reactive retrieval — 오개념 *내용*이 이 채널을 타고 나가지 않는다 ────────────
def test_candidate_carries_no_misconception_content() -> None:
    """후보에는 **식별자와 신뢰도만** 실린다 — 정의·반례·개입 전략은 실리지 않는다.

    CLAUDE.md "오개념을 초기 context에 preload 금지 — reactive retrieval만". 이 채널이
    카탈로그 *내용*을 실어 보내면, 그 내용이 하류 프롬프트로 흘러 오개념을 학생에게 먼저
    제시하는 경로(misconception contamination)가 열린다. 내용이 필요하면 하류가 id로 그때
    조회한다.

    필드 집합 자체를 단언하는 이유: "지금은 안 실린다"가 아니라 **실을 자리가 없다**를 계약으로
    박아야 나중에 필드가 늘어도 CI가 말해 준다.
    """
    from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
    from whymath_backend.schema.assessment_evidence import MisconceptionCandidate

    assert set(MisconceptionCandidate.model_fields) == {
        "misconception_id",
        "confidence",
        "gate_passed",
        "low_quality",
        "attribution_unclear",
    }
    result = _scan("(x+2)²을 전개하시오.", "x²+4")
    catalog_entry = CATALOG_BY_ID[_CROSS_TERM]
    serialized = str([c.model_dump() for c in result.candidates])
    for content in (catalog_entry.canonical_statement, catalog_entry.counterexample):
        assert content not in serialized, "오개념 내용이 후보에 실려 나간다 — preload 금기 위반"


def test_detector_does_not_read_learner_history() -> None:
    """이 검출기는 학습자 이력을 보지 않는다 — 판정은 *이 시도*만으로 결정된다.

    학습자 단위 활성 가설을 읽어 후보를 만들면 그것은 "이 답안의 오개념"이 아니라 "이 학생의
    오개념"이라 귀속이 무너진다(EOS-104 acceptance ③이 금지한 자리). 확증편향 축도 같다 —
    이미 의심하던 오개념을 근거 없이 재확인하게 된다.

    시그니처에 학습자 식별자가 없다는 것이 그 구조적 보장이다.
    """
    import inspect

    params = set(inspect.signature(scan_attempt_answer).parameters)
    assert params == {"question_text", "student_answer"}
