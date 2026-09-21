"""개념 평가 재료 참조 뱅크 — 주입 동작·정직한 실패·봉인 검사 범위.

이 파일이 지키는 핵심 회귀는 **"PROBLEM_BASED가 전 개념에서 렌더 불가"**의 재발이다. 그 상태는
예외도 로그도 없이 `can_render() -> False` 하나로 성립했고, 학생은 404만 받았다. 따라서 여기서는
*주입 전 False / 주입 후 True*를 같은 DSL로 나란히 확인한다 — 두 값이 같으면 이 테스트가 아무것도
검사하지 않는 것이므로, 대조 자체가 검사의 변별력이다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from whymath_backend.composition import (
    default_assessment_answer_verifier,
    default_expression_seal,
)
from whymath_backend.l3.render import assessment_bank
from whymath_backend.l3.render.adapter import RenderContext
from whymath_backend.l3.render.adapters import ProblemBasedAdapter, WorkedExampleAdapter
from whymath_backend.l3.render.assessment_bank import (
    ASSESSMENT_INDEX_PATH,
    attach_assessment,
    get_assessment_bank,
    reset_assessment_bank_cache,
    uncovered_concept_codes,
)
from whymath_backend.l3.render.dsl import ConceptAssessment, ConceptDSL


@pytest.fixture(autouse=True)
def _isolate_bank_cache():
    """뱅크 캐시는 프로세스 전역(lru_cache)이라 테스트마다 비운다(누수 차단)."""
    reset_assessment_bank_cache()
    yield
    reset_assessment_bank_cache()


def _caps() -> dict[str, object]:
    """어댑터 생성 시 주입할 과목 능력 2종(EOS-89) — 테스트가 이 사슬의 상류다."""
    return {
        "seal": default_expression_seal(),
        "assessment_verifier": default_assessment_answer_verifier(),
    }


def _dsl(**overrides: object) -> ConceptDSL:
    """평가 재료가 *없는* 최소 DSL — 주입 전 상태를 그대로 표현한다."""
    payload: dict[str, object] = {
        "code": "TEST-1",
        "name": "이차식의 인수분해",
        "subject": "중학수학",
        "definition": "곱의 꼴로 바꾸어 쓰는 일.",
    }
    payload.update(overrides)
    return ConceptDSL(**payload)  # type: ignore[arg-type]


def _write_index(tmp_path: Path, entries: list[dict[str, object]], uncovered: list[str]) -> Path:
    path = tmp_path / "index.json"
    path.write_text(
        json.dumps({"entries": entries, "uncovered_concept_codes": uncovered}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _point_bank_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(assessment_bank, "ASSESSMENT_INDEX_PATH", path)
    reset_assessment_bank_cache()


# ── 산출물 실재성(배선 동결) ────────────────────────────────────────


def test_shipped_index_exists_and_is_populated() -> None:
    """레포에 실제 산출물이 있고 비어 있지 않다 — fail-soft가 *상시* 발동하는 상태를 막는다.

    뱅크는 산출물이 없어도 빈 dict로 강등되므로(fail-open), 산출물이 사라져도 런타임은 조용히
    "PROBLEM_BASED 렌더 불가"로 되돌아간다. 그 무증상 회귀를 CI에서 잡는 것이 이 테스트다.
    """
    assert ASSESSMENT_INDEX_PATH.is_file(), ASSESSMENT_INDEX_PATH
    bank = get_assessment_bank()
    assert bank, "산출물은 있으나 항목이 0건 — 참조 주입이 무력 상태"
    sample = next(iter(bank.values()))
    assert sample.conditions and sample.answer_map


def test_shipped_uncovered_list_is_recorded_and_disjoint() -> None:
    """미커버 개념이 *숫자와 목록으로* 남아 있고 커버 목록과 겹치지 않는다(침묵 통과 금지)."""
    uncovered = uncovered_concept_codes()
    assert uncovered, "미커버 개념 목록이 비었다 — 전 개념 커버가 아니라면 기록 누락이다"
    assert not (set(uncovered) & set(get_assessment_bank())), "커버·미커버가 겹친다"


# ── 주입 동작 ────────────────────────────────────────────────────


def test_problem_based_cannot_render_before_injection_but_can_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """이 슬라이스의 주장 자체 — 같은 DSL이 주입 전 False, 주입 후 True."""
    _point_bank_at(
        monkeypatch,
        _write_index(
            tmp_path,
            [
                {
                    "concept_code": "TEST-1",
                    "conditions": ["x**2 - 5*x + 6 = 0"],
                    "answer_map": {"x": "3"},
                    "prompt": "두 근 중 큰 근을 구하시오.",
                }
            ],
            ["TEST-2"],
        ),
    )
    adapter = ProblemBasedAdapter(**_caps())
    before = _dsl()
    assert adapter.can_render(before) is False

    after = attach_assessment(before)
    assert adapter.can_render(after) is True
    unit = adapter.render(after, RenderContext())
    assert unit.ok, unit.validation_signal
    # 정답(answer_map 값)은 화면에 실리지 않는다 — 문제기반의 요점(바로 정답 제공 금지).
    assert all("3" != seg.content.strip() for seg in unit.segments)


def test_attach_is_pure_and_does_not_mutate_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """주입은 새 인스턴스를 만들고 원본을 건드리지 않는다(캐시 자산 안전)."""
    _point_bank_at(
        monkeypatch,
        _write_index(
            tmp_path,
            [{"concept_code": "TEST-1", "conditions": "x = 2", "answer_map": {"x": "2"}}],
            [],
        ),
    )
    original = _dsl()
    injected = attach_assessment(original)
    assert original.assessment is None
    assert injected is not original
    assert injected.assessment is not None
    # conditions가 str이어도 튜플로 정규화된다(코퍼스가 두 형태를 모두 쓴다).
    assert injected.assessment.conditions == ("x = 2",)


def test_attach_is_noop_for_unknown_code_and_preexisting_assessment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """뱅크에 없는 개념은 원본 그대로, 이미 재료가 있으면 덮어쓰지 않는다."""
    _point_bank_at(
        monkeypatch,
        _write_index(
            tmp_path,
            [{"concept_code": "TEST-1", "conditions": "x = 2", "answer_map": {"x": "2"}}],
            [],
        ),
    )
    unknown = _dsl(code="NOT-IN-BANK")
    assert attach_assessment(unknown) is unknown

    preset = ConceptAssessment(conditions=("y = 1",), answer_map={"y": "1"})
    already = _dsl(assessment=preset)
    assert attach_assessment(already).assessment is preset


# ── 정직한 실패(침묵 실패 금지) ──────────────────────────────────


def test_missing_index_degrades_to_empty_bank_with_typed_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """산출물 부재 → 빈 뱅크 + **예외 타입명**을 담은 경고(무타입 경고 금지)."""
    _point_bank_at(monkeypatch, tmp_path / "does-not-exist.json")
    with caplog.at_level(logging.WARNING):
        assert get_assessment_bank() == {}
    assert "FileNotFoundError" in caplog.text


def test_malformed_entry_is_skipped_with_typed_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """깨진 항목만 건너뛰고 사유를 타입명과 함께 남긴다 — 나머지 항목은 살아남는다."""
    _point_bank_at(
        monkeypatch,
        _write_index(
            tmp_path,
            [
                {"concept_code": "BROKEN"},  # conditions·answer_map 부재 → KeyError
                {"concept_code": "OK-1", "conditions": "x = 2", "answer_map": {"x": "2"}},
            ],
            [],
        ),
    )
    with caplog.at_level(logging.WARNING):
        bank = get_assessment_bank()
    assert set(bank) == {"OK-1"}
    assert "KeyError" in caplog.text


def test_empty_answer_map_entry_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """빈 `answer_map`은 검증 불가한 재료라 뱅크에 들어가지 못한다(빈 검증의 통과 위장 금지)."""
    _point_bank_at(
        monkeypatch,
        _write_index(
            tmp_path, [{"concept_code": "X", "conditions": "x = 2", "answer_map": {}}], []
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert get_assessment_bank() == {}
    assert "ValidationError" in caplog.text or "ValueError" in caplog.text


# ── 봉인 검사 범위(주입이 다른 어댑터를 깨지 않는다) ────────────────


def test_injection_does_not_break_worked_example_seal() -> None:
    """평가 재료 주입이 WORKED_EXAMPLE 봉인을 오탐으로 깨지 않는다.

    `_seal_signal`은 DSL 본문 수식이 렌더 후에도 보존됐는지 본다. 평가 재료에서 조립되는
    `solution_step`·`prompt`는 본문 수식을 실을 리가 없는데도 조건식의 `=` 때문에 캐리어로
    잡혀 EQUATION_ALTERED 오탐을 냈다 — 그 범위 제한이 살아 있는지 동결한다.
    """
    dsl = _dsl(
        definition="이차방정식 x^2 - 5x + 6 = 0 을 인수분해로 푼다.",
        assessment=ConceptAssessment(
            conditions=("t**2 - 4 = 0",), answer_map={"t": "2"}, prompt="t를 구하시오."
        ),
    )
    for adapter in (WorkedExampleAdapter(**_caps()), ProblemBasedAdapter(**_caps())):
        unit = adapter.render(dsl, RenderContext())
        assert unit.ok, f"{adapter.strategy.value}: {unit.validation_signal}"


def test_body_segments_are_still_sealed() -> None:
    """범위 제한이 봉인을 *약화*시키지 않았다 — 본문 수식이 변형되면 여전히 신호가 뜬다.

    바인딩 치환으로 본문 방정식을 훼손시켜 EQUATION_ALTERED를 유도한다(실패 상태에서 실제로
    실패하는지 확인 — 성공/실패 양쪽에서 같은 값을 내는 검사는 위장이다).
    """
    from whymath_backend.l3.render.adapters import DirectAdapter

    dsl = _dsl(definition="핵심 식은 {slot} 이다.")
    ok = DirectAdapter(**_caps()).render(dsl, RenderContext(bindings={"slot": "x + 1 = 2"}))
    assert ok.ok
    broken = DirectAdapter(**_caps()).render(
        _dsl(definition="핵심 식은 x + 1 = 2 이고 {slot} 도 성립한다."),
        RenderContext(bindings={"slot": "y = 3"}),
    )
    assert not broken.ok
    assert broken.validation_signal is not None
    assert "seal violation" in broken.validation_signal.reason
