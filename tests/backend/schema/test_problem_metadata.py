"""Problem 메타데이터 7필드·6슬롯 계약 단위 테스트 — P3-04 (DB 0 · 파일 I/O는 범위 명세 읽기뿐).

원칙(CLAUDE.md "보호 장치를 실패 주입 없이 보호 있음으로 선언 금지"): 정상 입력의 초록은 증거가
아니다. 그래서 7필드 **각각**을 하나씩 비우는 주입을 파라미터로 돌리고, 주입이 **그 필드만** 바꿨는지
(다른 필드가 같이 흔들리면 주입이 아니라 오염이다)와 대조군(전부 채운 입력)이 통과하는지를 함께 잰다.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from whymath_backend.l1.standards.phase3_scope import load_scope_spec
from whymath_backend.schema import problem_metadata as pm
from whymath_backend.schema.problem_metadata import (
    FIELD_EVIDENCE,
    FieldState,
    ProblemMetadataEvidence,
    ProblemMetadataField,
    ProblemSlot,
    evaluate_metadata,
    parse_slot_tags,
    slot_tag,
)

_F = ProblemMetadataField
_S = ProblemSlot
_PRESENT = FieldState.PRESENT
_MISSING = FieldState.MISSING
_UNKNOWN = FieldState.UNKNOWN

#: 증거 속성마다 "측정했고 비어 있다"(→ MISSING)에 해당하는 값.
_EMPTY: dict[str, object] = {
    "difficulty": float("nan"),
    "answer": "   ",
    "solution_text": "",
    "concept_ids": (),
    "skill_ids": (),
    "own_misconception_ids": (),
    "concept_misconception_ids": (),
    "verified_hint_count": 0,
}


def _complete(**overrides: object) -> ProblemMetadataEvidence:
    """7필드가 전부 채워진 대조군. 슬롯은 트리거가 아닌 것(상속 인정)으로 둔다."""
    base: dict[str, object] = {
        "difficulty": 2.0,
        "answer": "7",
        "solution_text": "지수를 앞으로 내리고 1을 줄인다.",
        "concept_ids": ("H:12미적Ⅰ02-03",),
        "skill_ids": ("skill.power-rule",),
        "own_misconception_ids": ("power-rule-step-omitted",),
        "concept_misconception_ids": ("M0671",),
        "verified_hint_count": 2,
        "slots": frozenset({_S.REPRESENTATIVE}),
    }
    base.update(overrides)
    return ProblemMetadataEvidence(**base)  # type: ignore[arg-type]


def _blank(evidence: ProblemMetadataEvidence, field: ProblemMetadataField, *, value: object | None):
    """한 필드의 증거 속성들만 비운다 — `value`가 None이면 '측정 못함', 아니면 `_EMPTY` 값."""
    changes = {attr: (None if value is None else _EMPTY[attr]) for attr in FIELD_EVIDENCE[field]}
    return dataclasses.replace(evidence, **changes)


# ── 범위 명세와의 동치 (단일 정의 — 두 사본이 갈라지지 않게) ─────────────────────────
def test_fields_equal_scope_spec_required_fields_in_order() -> None:
    spec = load_scope_spec()
    assert [f.value for f in ProblemMetadataField] == list(spec.problem_required_fields)


def test_slots_equal_scope_spec_slots() -> None:
    spec = load_scope_spec()
    assert [s.value for s in ProblemSlot] == [s.id for s in spec.slots]


def test_every_evidence_attribute_belongs_to_a_field_or_is_the_slot_helper() -> None:
    """증거에 속성을 하나 더하고 어느 필드에도 안 달면 그 사실은 아무 판정에도 안 쓰인다."""
    attrs = {f.name for f in dataclasses.fields(ProblemMetadataEvidence)}
    mapped = [a for names in FIELD_EVIDENCE.values() for a in names]
    assert len(mapped) == len(set(mapped)), "한 증거 속성이 두 필드에 중복 귀속됐다"
    assert attrs - {"slots"} == set(mapped)
    assert set(_EMPTY) == set(mapped), "테스트의 비움 값 표가 증거 속성과 어긋났다"


def test_judges_and_evidence_table_cover_every_field() -> None:
    assert set(pm._JUDGES) == set(ProblemMetadataField)
    assert set(FIELD_EVIDENCE) == set(ProblemMetadataField)


# ── 대조군 ───────────────────────────────────────────────────────────────────
def test_control_complete_evidence_passes_all_seven() -> None:
    verdict = evaluate_metadata(_complete())
    assert verdict.complete
    assert len(verdict.states) == 7
    assert set(verdict.states.values()) == {_PRESENT}
    assert verdict.missing == () and verdict.unknown == () and verdict.failures() == []


def test_default_evidence_is_entirely_unknown_not_complete() -> None:
    """아무것도 못 쟀으면 7필드 전부 UNKNOWN이다 — 비어 있다고도, 통과라고도 하지 않는다."""
    verdict = evaluate_metadata(ProblemMetadataEvidence())
    assert not verdict.complete
    assert set(verdict.states.values()) == {_UNKNOWN}
    assert verdict.unknown == tuple(ProblemMetadataField)


# ── 누락 주입: 7필드 각각 → RED, 그리고 그 필드만 ────────────────────────────────
@pytest.mark.parametrize("field", list(ProblemMetadataField), ids=lambda f: f.value)
def test_blanking_one_field_makes_exactly_that_field_missing(field: ProblemMetadataField) -> None:
    broken = _blank(_complete(), field, value="empty")
    verdict = evaluate_metadata(broken)
    assert broken != _complete(), "주입이 적용되지 않았다 — 같은 입력을 검사한 것이다"
    assert not verdict.complete
    assert verdict.missing == (field,)
    assert verdict.unknown == ()
    assert verdict.failures() == [f"{field.value}: 비어 있다"]


@pytest.mark.parametrize("field", list(ProblemMetadataField), ids=lambda f: f.value)
def test_unmeasured_one_field_is_unknown_and_not_a_pass(field: ProblemMetadataField) -> None:
    broken = _blank(_complete(), field, value=None)
    verdict = evaluate_metadata(broken)
    assert broken != _complete()
    assert not verdict.complete
    assert verdict.unknown == (field,)
    assert verdict.missing == ()
    assert verdict.failures() == [f"{field.value}: 측정하지 못했다"]


def test_blanking_all_fields_reports_all_seven_in_field_order() -> None:
    broken = _complete()
    for field in ProblemMetadataField:
        broken = _blank(broken, field, value="empty")
    verdict = evaluate_metadata(broken)
    assert verdict.missing == tuple(ProblemMetadataField)
    assert [line.split(":")[0] for line in verdict.failures()] == [
        f.value for f in ProblemMetadataField
    ]


# ── 필드별 경계 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", [float("nan"), math.inf, -math.inf, True, False])
def test_difficulty_rejects_non_finite_and_bool(bad: object) -> None:
    verdict = evaluate_metadata(_complete(difficulty=bad))
    assert verdict.states[_F.DIFFICULTY] is _MISSING


def test_difficulty_zero_is_present_scale_is_not_assumed() -> None:
    assert evaluate_metadata(_complete(difficulty=0.0)).states[_F.DIFFICULTY] is _PRESENT


@pytest.mark.parametrize("blank", ["", " ", "\n\t"])
def test_text_fields_reject_blank_strings(blank: str) -> None:
    verdict = evaluate_metadata(_complete(answer=blank, solution_text=blank))
    assert verdict.states[_F.ANSWER] is _MISSING
    assert verdict.states[_F.SOLUTION] is _MISSING


def test_link_fields_reject_blank_ids() -> None:
    verdict = evaluate_metadata(_complete(concept_ids=("",), skill_ids=("  ",)))
    assert verdict.states[_F.CONCEPT] is _MISSING
    assert verdict.states[_F.SKILL] is _MISSING


@pytest.mark.parametrize(("count", "state"), [(0, _MISSING), (-1, _MISSING), (1, _PRESENT)])
def test_hint_needs_at_least_one_verified_hint(count: int, state: FieldState) -> None:
    assert evaluate_metadata(_complete(verified_hint_count=count)).states[_F.HINT_STRATEGY] is state


# ── 오개념 서명: 슬롯별 규칙 진리표 (Kiki 결정 2026-10-14) ─────────────────────────
_TRIG = frozenset({_S.MISCONCEPTION_TRIGGER})
_REP = frozenset({_S.REPRESENTATIVE})
_M = ("M0671",)


@pytest.mark.parametrize(
    ("slots", "own", "inherited", "expected", "source"),
    [
        # 트리거 슬롯 — 문항 자체 연결만 인정
        pytest.param(_TRIG, _M, (), _PRESENT, "own", id="trigger+own"),
        pytest.param(_TRIG, _M, None, _PRESENT, "own", id="trigger+own+inherited-unmeasured"),
        pytest.param(_TRIG, (), _M, _MISSING, None, id="trigger+inherited-only=NOT-enough"),
        pytest.param(_TRIG, (), (), _MISSING, None, id="trigger+nothing"),
        pytest.param(_TRIG, None, _M, _UNKNOWN, None, id="trigger+own-unmeasured"),
        pytest.param(_TRIG | _REP, (), _M, _MISSING, None, id="trigger+other-slot-inherited"),
        # 그 밖의 슬롯 — 상속 인정
        pytest.param(_REP, (), _M, _PRESENT, "concept", id="other+inherited"),
        pytest.param(_REP, (), (), _MISSING, None, id="other+nothing"),
        pytest.param(_REP, _M, (), _PRESENT, "own", id="other+own"),
        pytest.param(_REP, None, _M, _PRESENT, "concept", id="other+inherited+own-unmeasured"),
        pytest.param(_REP, None, None, _UNKNOWN, None, id="other+nothing-measured"),
        pytest.param(_REP, (), None, _UNKNOWN, None, id="other+inherited-unmeasured"),
        # 슬롯 미지정(태그 없음) — 트리거가 아니므로 상속 인정
        pytest.param(frozenset(), (), _M, _PRESENT, "concept", id="no-slot+inherited"),
        # 슬롯을 모른다 — 완화 규칙을 쓰지 않는다
        pytest.param(None, (), _M, _UNKNOWN, None, id="slot-unknown+inherited=NOT-enough"),
        pytest.param(None, _M, (), _PRESENT, "own", id="slot-unknown+own"),
        pytest.param(None, (), (), _MISSING, None, id="slot-unknown+nothing"),
        pytest.param(None, None, None, _UNKNOWN, None, id="all-unknown"),
    ],
)
def test_misconception_signature_rule_by_slot(
    slots: frozenset[ProblemSlot] | None,
    own: tuple[str, ...] | None,
    inherited: tuple[str, ...] | None,
    expected: FieldState,
    source: str | None,
) -> None:
    ev = _complete(slots=slots, own_misconception_ids=own, concept_misconception_ids=inherited)
    verdict = evaluate_metadata(ev)
    assert verdict.states[_F.MISCONCEPTION_SIGNATURE] is expected
    assert verdict.misconception_source == source


def test_trigger_slot_with_only_inherited_signature_is_not_complete() -> None:
    """핵심 대조: 같은 증거가 트리거 슬롯이면 거부되고 다른 슬롯이면 통과한다."""
    inherited_only = {"own_misconception_ids": (), "concept_misconception_ids": _M}
    assert evaluate_metadata(_complete(slots=_REP, **inherited_only)).complete
    refused = evaluate_metadata(_complete(slots=_TRIG, **inherited_only))
    assert not refused.complete and refused.missing == (_F.MISCONCEPTION_SIGNATURE,)


# ── 슬롯 태그 ────────────────────────────────────────────────────────────────
def test_slot_tag_round_trips_for_every_slot() -> None:
    for slot in ProblemSlot:
        assert parse_slot_tags([slot_tag(slot)]).slots == frozenset({slot})


def test_parse_slot_tags_ignores_unrelated_tags_and_keeps_typos_visible() -> None:
    parsed = parse_slot_tags(
        ["p3-slot:basic", "misc", "p3-slot:aplied", "p3-slot:basic", "x:basic"]
    )
    assert parsed.slots == frozenset({_S.BASIC})
    assert parsed.unknown == ("p3-slot:aplied",)


def test_parse_slot_tags_accepts_none_and_non_strings() -> None:
    assert parse_slot_tags(None) == parse_slot_tags([])
    assert parse_slot_tags([3, None]).slots == frozenset()  # type: ignore[list-item]


def test_rejected_inherited_evidence_reports_no_source() -> None:
    """트리거 슬롯에서 거부된 상속 증거가 "concept"로 집계되면 상속 비율이 부풀려진다."""
    verdict = evaluate_metadata(
        _complete(slots=_TRIG, own_misconception_ids=(), concept_misconception_ids=_M)
    )
    assert verdict.states[_F.MISCONCEPTION_SIGNATURE] is _MISSING
    assert verdict.misconception_source is None
