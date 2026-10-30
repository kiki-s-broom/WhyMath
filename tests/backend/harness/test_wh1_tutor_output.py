"""P3-09 — 튜터 구조화 출력 스키마·검증기·러너 집행 (hermetic·LLM 0·DB 0).

세 단계를 각각 주입으로 본다(정본 `harness/wh1_tutor_output.py`).

1. LLM 원시 출력 판정(`classify_action_payload`)과 정책 집행(`LLMTutorPolicy._parse_action`) —
   위반 유형마다 거부 사유 코드·WARNING·안전 강등이 나고, 대조군(정상 JSON)은 통과한다.
2. 학생 대면 출력 스키마(`TutorTurnOutput`·`build_tutor_output`)와 러너 집행 — 스키마 위반 발화는
   러너가 `None`(결정론 폴백)을 돌려주고 관측 `fallback_output_schema`가 남는다.
3. 승격 직전 재검증(`check_deliverable`) — 우회 생성(`model_construct`)한 `mastery_update_allowed=True`
   구조체도 거부한다.

절마다 **그 절이 없으면 통과하는 입력**을 픽스처로 둔다(대조군 포함) — 뮤테이션이 그 절을 밟게.
"""

from __future__ import annotations

import asyncio
import logging
import typing
from collections.abc import Sequence
from typing import Any

import pytest
from pydantic import ValidationError

from whymath_backend.harness.wh1_llm_policy import LLMTutorPolicy
from whymath_backend.harness.wh1_loop import (
    CONCEPT_ID_REJECT_DETAIL,
    ENCOURAGE_FALLBACK_UTTERANCE,
    NEUTRAL_GUIDE_UTTERANCE,
    EndTurnAction,
    LogEvidenceAction,
    QueryCurriculumAction,
    ReadStateAction,
    ScriptedTutorPolicy,
    TurnState,
    VerifyStepAction,
    run_tutoring_turn,
)
from whymath_backend.harness.wh1_primary import run_wh1_primary_turn
from whymath_backend.harness.wh1_shadow import Wh1HarnessShadowObservation
from whymath_backend.harness.wh1_tutor_context import ConceptBrief, TutorContentSummary
from whymath_backend.harness.wh1_tutor_output import (
    MAX_EXPLANATION_CHARS,
    REASON_EXPLANATION_MISMATCH,
    REASON_FIELD_RANGE,
    REASON_FIELD_TYPE,
    REASON_MISSING_FIELD,
    REASON_MISSING_OUTPUT,
    REASON_NOT_JSON_OBJECT,
    REASON_STATE_AUTHORITY_CLAIM,
    REASON_UNKNOWN_CONCEPT_ID,
    REASON_UNKNOWN_KIND,
    REASON_UNKNOWN_MISCONCEPTION_ID,
    REASON_UNMAPPED_STRATEGY,
    TutorDiagnosis,
    TutorOutputReceipt,
    TutorTurnOutput,
    build_tutor_output,
    check_deliverable,
    classify_action_payload,
    validate_tutor_output,
)
from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis

_CONCEPT = "math.algebra.linear-equation"
_KNOWN = frozenset({_CONCEPT})
_MID = "distribution-over-power"
_MID_B = "sign-flip-in-inequality"
_MARKER = "ZZTUTORMARKERZZ 네가 세운 식에서 무엇을 먼저 봤는지 말해줄래?"
_POLICY_LOGGER = "whymath.harness.wh1_llm_policy"
_PRIMARY_LOGGER = "whymath.harness.wh1_primary"
_RECORD_LOGGER = "whymath.harness.wh1_shadow.record"


def _hyp(mid: str, conf: float) -> MisconceptionHypothesis:
    return MisconceptionHypothesis(
        misconception_id=mid, confidence=conf, turns_since_evidence=0, evidence_count=1
    )


def _valid_payload(**over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "diagnosis": {"concept_id": _CONCEPT, "misconception_id": _MID, "confidence": 0.8},
        "response_strategy": "guided_hint",
        "hint_level": 2,
        "explanation": "어느 단계에서 등식의 성질을 썼는지 말해줄래?",
        "explanation_source": "llm",
        "next_action": "continue_dialogue",
    }
    payload.update(over)
    return payload


# ──────────────────────────────────────────────────────────────────────
# 2단계 스키마 — 필드 집합·mastery 강제 false
# ──────────────────────────────────────────────────────────────────────
def test_output_field_set_is_frozen() -> None:
    """원 문서 제안 필드 + 판 표기. 필드 신설·삭제는 RED(스키마 판 갱신과 함께만)."""
    assert set(TutorTurnOutput.model_fields) == {
        "schema_version",
        "diagnosis",
        "response_strategy",
        "hint_level",
        "explanation",
        "explanation_source",
        "next_action",
        "mastery_update_allowed",
    }
    assert set(TutorDiagnosis.model_fields) == {"concept_id", "misconception_id", "confidence"}


def test_mastery_update_allowed_is_typed_false_only() -> None:
    """타입이 `Literal[False]`이고 기본값이 False다 — true를 담을 자리가 없다."""
    field = TutorTurnOutput.model_fields["mastery_update_allowed"]
    assert field.annotation == typing.Literal[False]
    assert field.default is False


@pytest.mark.parametrize("claimed", [True, "false", 0, None, 1])
def test_mastery_update_allowed_anything_but_false_is_rejected(claimed: object) -> None:
    """false가 아닌 모든 값(문자열 'false'·0·None 포함)은 상태 권위 주장으로 거부된다."""
    verdict = validate_tutor_output(
        _valid_payload(mastery_update_allowed=claimed), known_concept_ids=_KNOWN
    )
    assert verdict == REASON_STATE_AUTHORITY_CLAIM


def test_mastery_update_allowed_true_cannot_be_constructed() -> None:
    """검증기 우회 없이 생성하면 타입이 막는다(사유 코드 축과 독립된 두 번째 축)."""
    with pytest.raises(ValidationError):
        TutorTurnOutput.model_validate(_valid_payload(mastery_update_allowed=True))


def test_valid_payload_passes_and_mastery_is_false() -> None:
    out = validate_tutor_output(_valid_payload(), known_concept_ids=_KNOWN)
    assert isinstance(out, TutorTurnOutput)
    assert out.mastery_update_allowed is False
    assert out.schema_version == "tutor-output-v1"
    # 명시 false echo는 허용(계약과 같은 값).
    echoed = validate_tutor_output(
        _valid_payload(mastery_update_allowed=False), known_concept_ids=_KNOWN
    )
    assert isinstance(echoed, TutorTurnOutput)


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"hint_level": 5}, "SCHEMA_LITERAL_ERROR"),  # 범위 밖 hint_level
        ({"hint_level": 0}, "SCHEMA_LITERAL_ERROR"),
        ({"hint_level": "2"}, "SCHEMA_VALUE_ERROR"),  # 문자열 형변환 금지
        ({"hint_level": True}, "SCHEMA_VALUE_ERROR"),  # 검토 하1 — Literal 값 동등(True == 1) 차단
        ({"hint_level": 2.0}, "SCHEMA_VALUE_ERROR"),  # 검토 하1 — 2.0 == 2 차단
        ({"explanation": "\u200b"}, "SCHEMA_VALUE_ERROR"),  # 검토 하2 — ZWSP만
        ({"explanation": "\u3164\u3164"}, "SCHEMA_VALUE_ERROR"),  # 한글 채움 문자만
        ({"explanation": "\ufeff \u2060\u00a0"}, "SCHEMA_VALUE_ERROR"),  # BOM·WJ·NBSP
        ({"explanation_source": "teacher"}, "SCHEMA_LITERAL_ERROR"),
        ({"diagnosis": {"misconception_id": _MID, "confidence": True}}, "SCHEMA_VALUE_ERROR"),
        # 검토 중2 — 전략·다음 행동 일관성
        (
            {"response_strategy": "encouragement", "next_action": "revise_solution"},
            "SCHEMA_VALUE_ERROR",
        ),
        ({"response_strategy": "diagnostic_probe"}, "SCHEMA_VALUE_ERROR"),
        ({"next_action": "solve_probe"}, "SCHEMA_VALUE_ERROR"),
        ({"explanation": ""}, "SCHEMA_STRING_TOO_SHORT"),
        ({"explanation": "   "}, "SCHEMA_VALUE_ERROR"),  # 공백뿐
        ({"explanation": "가" * (MAX_EXPLANATION_CHARS + 1)}, "SCHEMA_STRING_TOO_LONG"),
        ({"explanation": 3}, "SCHEMA_STRING_TYPE"),
        ({"response_strategy": "give_answer"}, "SCHEMA_LITERAL_ERROR"),
        ({"next_action": "show_solution"}, "SCHEMA_LITERAL_ERROR"),
        ({"extra_field": 1}, "SCHEMA_EXTRA_FORBIDDEN"),
        ({"schema_version": "tutor-output-v0"}, "SCHEMA_LITERAL_ERROR"),
        ({"diagnosis": {"misconception_id": "no-such-misconception"}}, "SCHEMA_VALUE_ERROR"),
        ({"diagnosis": {"concept_id": "math.fake.hallucinated"}}, REASON_UNKNOWN_CONCEPT_ID),
        ({"diagnosis": {"confidence": 0.5}}, "SCHEMA_VALUE_ERROR"),  # 오개념 없는 신뢰도
        (
            {"diagnosis": {"misconception_id": _MID, "confidence": 1.5}},
            "SCHEMA_LESS_THAN_EQUAL",
        ),
        ({"diagnosis": {"concept_id": _CONCEPT, "theta": 0.4}}, "SCHEMA_EXTRA_FORBIDDEN"),
    ],
)
def test_schema_violations_are_rejected_with_reason(over: dict[str, Any], code: str) -> None:
    payload = _valid_payload(**over)
    assert validate_tutor_output(payload, known_concept_ids=_KNOWN) == code


def test_missing_required_field_is_rejected() -> None:
    payload = _valid_payload()
    del payload["explanation"]
    assert validate_tutor_output(payload, known_concept_ids=_KNOWN) == "SCHEMA_MISSING"


def test_concept_id_requires_known_set_and_empty_set_fails_closed() -> None:
    """개념 id는 알려진 집합(이번 턴 DB 조회) 안에서만 — 집합이 비면 개념 id 진단은 거부된다.

    모델 자체는 조회 결과를 모른다(응답 직렬화·재검증 자리에서 깨지지 않게) — 실재 확인은 게이트
    함수(`validate_tutor_output`)를 경유한 경로에서만 일어난다.
    """
    assert (
        validate_tutor_output(_valid_payload(), known_concept_ids=frozenset())
        == REASON_UNKNOWN_CONCEPT_ID
    )
    assert isinstance(TutorTurnOutput.model_validate(_valid_payload()), TutorTurnOutput)
    no_concept = _valid_payload(diagnosis={"misconception_id": _MID, "confidence": 0.8})
    assert isinstance(
        validate_tutor_output(no_concept, known_concept_ids=frozenset()), TutorTurnOutput
    )


# ──────────────────────────────────────────────────────────────────────
# 2단계 빌더 — 값의 출처는 서버, 매핑은 닫힌 어휘
# ──────────────────────────────────────────────────────────────────────
def _build(**over: Any) -> TutorTurnOutput | str:
    kwargs: dict[str, Any] = {
        "explanation": "네가 먼저 본 것은 무엇이었어?",
        "explanation_source": "llm",
        "action_type": "질문",
        "mode_guard_replaced": False,
        "verify_verdict": "correct",
        "hypotheses": [_hyp(_MID_B, 0.6), _hyp(_MID, 0.8)],
        "concept_id": _CONCEPT,
        "known_concept_ids": _KNOWN,
        "hint_level": 1,
    }
    kwargs.update(over)
    return build_tutor_output(**kwargs)


@pytest.mark.parametrize(
    ("action_type", "guard", "strategy"),
    [
        ("질문", False, "guided_question"),
        ("힌트", False, "guided_hint"),
        ("출제", False, "diagnostic_probe"),
        ("격려", False, "encouragement"),
        ("질문", True, "socratic_requestion"),
        ("출제", True, "socratic_requestion"),
    ],
)
def test_strategy_mapping(action_type: str, guard: bool, strategy: str) -> None:
    out = _build(action_type=action_type, mode_guard_replaced=guard)
    assert isinstance(out, TutorTurnOutput)
    assert out.response_strategy == strategy


def test_unmapped_strategy_is_rejected() -> None:
    assert _build(action_type=None) == REASON_UNMAPPED_STRATEGY


@pytest.mark.parametrize(
    ("action_type", "guard", "verdict", "expected"),
    [
        ("출제", False, "incorrect", "solve_probe"),  # 출제가 판정보다 우선
        ("출제", True, "incorrect", "revise_solution"),  # 가드가 출제를 대체했으면 출제 아님
        ("질문", False, "incorrect", "revise_solution"),
        ("힌트", False, "unverifiable", "revise_solution"),
        ("질문", False, "correct", "continue_dialogue"),
        ("질문", False, None, "continue_dialogue"),
    ],
)
def test_next_action_mapping(
    action_type: str, guard: bool, verdict: str | None, expected: str
) -> None:
    out = _build(action_type=action_type, mode_guard_replaced=guard, verify_verdict=verdict)
    assert isinstance(out, TutorTurnOutput)
    assert out.next_action == expected


def test_diagnosis_uses_top_hypothesis_and_db_concept() -> None:
    out = _build()
    assert isinstance(out, TutorTurnOutput)
    assert out.diagnosis.concept_id == _CONCEPT
    assert out.diagnosis.misconception_id == _MID  # 0.8 > 0.6 — 입력 순서 무관
    assert out.diagnosis.confidence == pytest.approx(0.8)
    assert out.hint_level == 1
    assert out.mastery_update_allowed is False


def test_diagnosis_tie_breaks_by_id() -> None:
    out = _build(hypotheses=[_hyp(_MID_B, 0.7), _hyp(_MID, 0.7)])
    assert isinstance(out, TutorTurnOutput)
    assert out.diagnosis.misconception_id == min(_MID, _MID_B)


def test_no_hypothesis_and_no_concept_yields_empty_diagnosis() -> None:
    out = _build(hypotheses=[], concept_id=None, known_concept_ids=frozenset())
    assert isinstance(out, TutorTurnOutput)
    assert out.diagnosis == TutorDiagnosis()


def test_builder_rejects_concept_outside_known_set() -> None:
    """진단 개념의 출처가 바뀌면(조회 개념 밖) 거부 — 출처 고정 장치."""
    assert _build(concept_id="math.fake.node") == REASON_UNKNOWN_CONCEPT_ID


def test_builder_rejects_overlong_explanation() -> None:
    assert _build(explanation="가" * (MAX_EXPLANATION_CHARS + 1)) == "SCHEMA_STRING_TOO_LONG"


def test_builder_rejects_out_of_range_hint_level() -> None:
    assert _build(hint_level=7) == "SCHEMA_LITERAL_ERROR"


# ──────────────────────────────────────────────────────────────────────
# 3단계 — 승격 직전 재검증
# ──────────────────────────────────────────────────────────────────────
def _ok_output() -> TutorTurnOutput:
    out = _build(explanation=_MARKER)
    assert isinstance(out, TutorTurnOutput)
    return out


def _forged(**over: Any) -> TutorTurnOutput:
    """검증기를 우회해 만든 구조체(`model_construct`) — 프로듀서 결함·변조 주입."""
    fields: dict[str, Any] = dict(_ok_output())
    fields.update(over)
    return TutorTurnOutput.model_construct(**fields)


def test_deliverable_control_passes() -> None:
    assert check_deliverable(_ok_output(), utterance=_MARKER, known_concept_ids=_KNOWN) is None


def test_deliverable_rejects_missing_output() -> None:
    assert check_deliverable(None, utterance=_MARKER, known_concept_ids=_KNOWN) == (
        REASON_MISSING_OUTPUT
    )


def test_deliverable_rejects_forged_mastery_true() -> None:
    forged = _forged(mastery_update_allowed=True)
    assert forged.mastery_update_allowed is True  # 주입 실재 단언
    assert (
        check_deliverable(forged, utterance=_MARKER, known_concept_ids=_KNOWN)
        == REASON_STATE_AUTHORITY_CLAIM
    )


def test_deliverable_rejects_explanation_mismatch() -> None:
    assert (
        check_deliverable(_ok_output(), utterance="다른 문장", known_concept_ids=_KNOWN)
        == REASON_EXPLANATION_MISMATCH
    )


def test_deliverable_rejects_concept_not_confirmed_by_caller() -> None:
    """러너가 낸 개념 id라도 호출자(코치)의 DB 조회 집합 밖이면 거부한다."""
    assert (
        check_deliverable(_ok_output(), utterance=_MARKER, known_concept_ids=frozenset())
        == REASON_UNKNOWN_CONCEPT_ID
    )


def test_deliverable_rejects_forged_hint_level() -> None:
    forged = _forged(hint_level=9)
    assert (
        check_deliverable(forged, utterance=_MARKER, known_concept_ids=_KNOWN)
        == "SCHEMA_LITERAL_ERROR"
    )


# ──────────────────────────────────────────────────────────────────────
# 1단계 — LLM 원시 출력 판정
# ──────────────────────────────────────────────────────────────────────
_VALID_ACTIONS: list[dict[str, Any]] = [
    {"kind": "verify_step"},
    {"kind": "match_misconception"},
    {"kind": "select_probe"},
    {"kind": "read_student_state"},
    {"kind": "read_student_state", "node_ids": [_CONCEPT]},
    {"kind": "read_student_state", "node_ids": None},
    {"kind": "curate_hypothesis"},
    {"kind": "curate_hypothesis", "turns_elapsed": 2},
    {"kind": "query_curriculum", "node_id": _CONCEPT, "relation": "선수"},
    {"kind": "log_evidence", "misconception_id": _MID, "polarity": 1},
    {"kind": "log_evidence", "misconception_id": _MID, "polarity": -1, "weight": 0.5},
    {"kind": "end_turn", "action_type": "질문"},
    {"kind": "end_turn", "action_type": "질문", "utterance": "왜 그렇게 생각했어?"},
    {"kind": "end_turn", "action_type": "질문", "utterance": None},
    {"kind": "end_turn", "action_type": "질문", "mastery_update_allowed": False},
    {"kind": "end_turn", "action_type": "질문", "reason": "여분 키는 버려진다"},
]


@pytest.mark.parametrize("payload", _VALID_ACTIONS)
def test_valid_action_payloads_pass(payload: dict[str, Any]) -> None:
    """대조군 — 정상 JSON이 거부되면 검증기가 과잉이다(폴백률 위장 상승)."""
    assert classify_action_payload(payload) is None


_INVALID_ACTIONS: list[tuple[dict[str, Any], str]] = [
    # 상태 권위 주장
    ({"kind": "end_turn", "action_type": "질문", "mastery_update_allowed": True}, "STATE"),
    ({"kind": "end_turn", "action_type": "질문", "mastery_update_allowed": "false"}, "STATE"),
    ({"kind": "end_turn", "action_type": "질문", "mastery_update_allowed": 0}, "STATE"),
    ({"kind": "end_turn", "action_type": "질문", "Mastery_Level": "숙달"}, "STATE"),
    ({"kind": "verify_step", "student_ability": 0.9}, "STATE"),
    ({"kind": "log_evidence", "misconception_id": _MID, "polarity": 1, "proficiency": 1}, "STATE"),
    # 미지 도구
    ({"kind": "give_answer"}, REASON_UNKNOWN_KIND),
    ({"action_type": "질문"}, REASON_UNKNOWN_KIND),
    # 필수 필드 누락
    ({"kind": "end_turn"}, REASON_MISSING_FIELD),
    ({"kind": "end_turn", "action_type": None}, REASON_MISSING_FIELD),
    ({"kind": "query_curriculum"}, REASON_MISSING_FIELD),
    ({"kind": "log_evidence", "polarity": 1}, REASON_MISSING_FIELD),
    ({"kind": "log_evidence", "misconception_id": _MID}, REASON_MISSING_FIELD),
    # 타입 오류(관대한 형변환 금지)
    ({"kind": "end_turn", "action_type": 1}, REASON_FIELD_TYPE),
    ({"kind": "end_turn", "action_type": "질문", "utterance": ["정답은 3"]}, REASON_FIELD_TYPE),
    ({"kind": "read_student_state", "node_ids": _CONCEPT}, REASON_FIELD_TYPE),
    ({"kind": "read_student_state", "node_ids": [1]}, REASON_FIELD_TYPE),
    ({"kind": "read_student_state", "node_ids": [" "]}, REASON_FIELD_TYPE),
    ({"kind": "curate_hypothesis", "turns_elapsed": True}, REASON_FIELD_TYPE),
    ({"kind": "curate_hypothesis", "turns_elapsed": "1"}, REASON_FIELD_TYPE),
    ({"kind": "query_curriculum", "node_id": 3}, REASON_FIELD_TYPE),
    ({"kind": "query_curriculum", "node_id": _CONCEPT, "relation": 2}, REASON_FIELD_TYPE),
    ({"kind": "log_evidence", "misconception_id": _MID, "polarity": True}, REASON_FIELD_TYPE),
    ({"kind": "log_evidence", "misconception_id": _MID, "polarity": "1"}, REASON_FIELD_TYPE),
    ({"kind": "log_evidence", "misconception_id": 7, "polarity": 1}, REASON_FIELD_TYPE),
    (
        {"kind": "log_evidence", "misconception_id": _MID, "polarity": 1, "weight": "0.5"},
        REASON_FIELD_TYPE,
    ),
    (
        {"kind": "log_evidence", "misconception_id": _MID, "polarity": 1, "weight": False},
        REASON_FIELD_TYPE,
    ),
    # 범위 밖 값(검토 중1 — 가중치 관례 [0, 1]·NaN·inf 거부)
    *[
        (
            {"kind": "log_evidence", "misconception_id": _MID, "polarity": -1, "weight": w},
            REASON_FIELD_RANGE,
        )
        for w in (1e9, 1.0000001, -0.1, float("nan"), float("inf"), float("-inf"))
    ],
    ({"kind": "curate_hypothesis", "turns_elapsed": -1}, REASON_FIELD_RANGE),
    # 상태 권위 주장 변형(검토 하3) — 중첩·전각·camelCase·복수형·한글
    ({"kind": "end_turn", "action_type": "질문", "meta": {"mastery": 0.9}}, "STATE"),
    ({"kind": "end_turn", "action_type": "질문", "meta": [{"proficiency": 1}]}, "STATE"),
    ({"kind": "end_turn", "action_type": "질문", "ｍａｓｔｅｒｙ": 1}, "STATE"),
    ({"kind": "end_turn", "action_type": "질문", "studentMastery": 1}, "STATE"),
    ({"kind": "end_turn", "action_type": "질문", "abilities": [1]}, "STATE"),
    ({"kind": "end_turn", "action_type": "질문", "skillLevel": 2}, "STATE"),
    ({"kind": "end_turn", "action_type": "질문", "skill_level": 2}, "STATE"),
    ({"kind": "end_turn", "action_type": "질문", "숙달도": "높음"}, "STATE"),
    ({"kind": "end_turn", "action_type": "질문", "masteryUpdateAllowed": False}, "STATE"),
    # 환각 id(오개념 — 카탈로그 정본)
    (
        {"kind": "log_evidence", "misconception_id": "no-such-mid", "polarity": 1},
        REASON_UNKNOWN_MISCONCEPTION_ID,
    ),
]


@pytest.mark.parametrize(("payload", "code"), _INVALID_ACTIONS)
def test_invalid_action_payloads_are_rejected(payload: dict[str, Any], code: str) -> None:
    expected = REASON_STATE_AUTHORITY_CLAIM if code == "STATE" else code
    assert classify_action_payload(payload) == expected


def test_concept_ids_are_not_judged_by_the_payload_classifier() -> None:
    """개념 id 실재는 판정기가 보지 않는다 — 하네스가 그 도구만 실패시킨다(턴 종료 아님·검토 중2)."""
    for payload in (
        {"kind": "query_curriculum", "node_id": "일차방정식"},
        {"kind": "read_student_state", "node_ids": ["math.fake.node"]},
    ):
        assert classify_action_payload(payload) is None


# ──────────────────────────────────────────────────────────────────────
# 1단계 집행 — 정책이 실제로 거부·기록·강등한다
# ──────────────────────────────────────────────────────────────────────
class _Seam:
    """좌석 대역 — 스크립트된 원시 출력을 차례로 돌려준다(소진 시 마지막 반복)."""

    def __init__(self, outputs: Sequence[str]) -> None:
        self._outputs = list(outputs)
        self.calls = 0

    async def generate(self, request: Any, prompt: str, system: str, **_: Any) -> str:
        out = self._outputs[min(self.calls, len(self._outputs) - 1)]
        self.calls += 1
        return out


def _policy(outputs: Sequence[str], *, content: bool = True) -> LLMTutorPolicy:
    summary = (
        TutorContentSummary(concept=ConceptBrief(code=_CONCEPT, name="일차방정식"))
        if content
        else None
    )
    return LLMTutorPolicy(seam=_Seam(outputs), content=summary, solution_steps=["x+1=3", "x=2"])


def _state(*, steps: bool = False) -> TurnState:
    return TurnState(turn_index=1, has_solution_steps=steps, hypotheses=[])


_BROKEN = [
    ('{"kind": "end_turn", "action_type": "질문", "utterance": "x"', REASON_NOT_JSON_OBJECT),
    ("[1, 2, 3]", REASON_NOT_JSON_OBJECT),
    ("정답은 3이야", REASON_NOT_JSON_OBJECT),
    ('{"kind": "end_turn", "action_type": "질문", "mastery_update_allowed": true}', "STATE"),
    (
        '{"kind": "log_evidence", "misconception_id": "'
        + _MID
        + '", "polarity": -1, "weight": 1e9}',
        REASON_FIELD_RANGE,
    ),
    (
        '{"kind": "log_evidence", "misconception_id": "'
        + _MID
        + '", "polarity": -1, "weight": NaN}',
        REASON_FIELD_RANGE,
    ),
    ('{"kind": "end_turn", "utterance": "x"}', REASON_MISSING_FIELD),
    ('{"kind": "end_turn", "action_type": "질문", "utterance": 3}', REASON_FIELD_TYPE),
    ('{"kind": "end_turn", "action_type": "칭찬"}', "ValidationError"),  # Literal 밖
    (
        '{"kind": "query_curriculum", "node_id": "' + _CONCEPT + '", "relation": "조상"}',
        "ValidationError",
    ),
]


@pytest.mark.parametrize(("raw", "code"), _BROKEN)
def test_policy_rejects_logs_counts_and_degrades(
    raw: str, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    expected = REASON_STATE_AUTHORITY_CLAIM if code == "STATE" else code
    policy = _policy([raw])
    with caplog.at_level(logging.WARNING, logger=_POLICY_LOGGER):
        action = asyncio.run(policy.next_action(_state()))
    assert action == EndTurnAction(action_type="격려", utterance=None)  # 결정론 강등(LLM 문자열 0)
    assert policy.last_action_degraded is True
    assert policy.output_rejections == {expected: 1}
    lines = [r.getMessage() for r in caplog.records if r.name == _POLICY_LOGGER]
    assert any(f"출력 스키마 위반({expected})" in line for line in lines), lines
    assert all("x+1=3" not in line for line in lines)  # 원문·풀이 미출력


def test_policy_rejection_respects_verify_obligation() -> None:
    """풀이 제출 턴의 강등은 검증 의무를 지킨다 — 거부가 verify를 건너뛰게 하지 않는다."""
    policy = _policy(
        ['{"kind": "end_turn", "action_type": "질문", "mastery_update_allowed": true}']
    )
    action = asyncio.run(policy.next_action(_state(steps=True)))
    assert isinstance(action, VerifyStepAction)


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ('{"kind": "end_turn", "action_type": "질문", "utterance": "왜?"}', EndTurnAction),
        ('{"kind": "query_curriculum", "node_id": "' + _CONCEPT + '"}', QueryCurriculumAction),
        ('{"kind": "read_student_state", "node_ids": ["' + _CONCEPT + '"]}', ReadStateAction),
        (
            '{"kind": "log_evidence", "misconception_id": "' + _MID + '", "polarity": 1}',
            LogEvidenceAction,
        ),
        (
            '{"kind": "end_turn", "action_type": "질문", "mastery_update_allowed": false}',
            EndTurnAction,
        ),
    ],
)
def test_policy_accepts_valid_outputs(raw: str, kind: type) -> None:
    """대조군 — 정상 출력은 거부 0·강등 0."""
    policy = _policy([raw])
    action = asyncio.run(policy.next_action(_state()))
    assert isinstance(action, kind)
    assert policy.output_rejections == {}
    assert policy.last_action_degraded is False


def test_policy_passes_hallucinated_concept_id_to_the_harness() -> None:
    """정책은 개념 id를 거부·강등하지 않는다 — 액션을 그대로 넘기고 허용 집합만 공개한다."""
    policy = _policy(['{"kind": "query_curriculum", "node_id": "일차방정식"}'])
    action = asyncio.run(policy.next_action(_state()))
    assert isinstance(action, QueryCurriculumAction)
    assert policy.output_rejections == {}
    assert policy.last_action_degraded is False
    assert policy.known_concept_ids == _KNOWN
    assert _policy(["{}"], content=False).known_concept_ids == frozenset()


# ──────────────────────────────────────────────────────────────────────
# 러너 집행 — 스키마 미통과 발화는 학생에게 가지 않는다
# ──────────────────────────────────────────────────────────────────────
class _Provider:
    """L3 provider 대역 — 같은 원시 출력을 매 호출 돌려준다(네트워크 0)."""

    def __init__(self, raw: str) -> None:
        self._raw = raw

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        return GenerationResult(self._raw)


def _end_turn(utterance: str, **extra: Any) -> str:
    import json

    return json.dumps({"kind": "end_turn", "action_type": "질문", "utterance": utterance, **extra})


def _run(raw: str, receipt: TutorOutputReceipt, **over: Any) -> str | None:
    kwargs: dict[str, Any] = {
        "student_solution": "x+1=3 이니까 x=2",
        "solution_steps": ["x+1=3", "x=2"],  # 정답 풀이 — 정책 명시 발화가 존중되는 턴
        "active_hypotheses": [_hyp(_MID, 0.8)],
        "provider": _Provider(raw),
        "tutor_content": TutorContentSummary(
            concept=ConceptBrief(code=_CONCEPT, name="일차방정식")
        ),
        "hint_level": 2,
        "output_receipt": receipt,
    }
    kwargs.update(over)
    return asyncio.run(run_wh1_primary_turn(**kwargs))


def _record(caplog: pytest.LogCaptureFixture) -> Wh1HarnessShadowObservation:
    (rec,) = [
        Wh1HarnessShadowObservation.model_validate_json(r.getMessage())
        for r in caplog.records
        if r.name == _RECORD_LOGGER
    ]
    return rec


def test_runner_control_delivers_validated_structure(caplog: pytest.LogCaptureFixture) -> None:
    receipt = TutorOutputReceipt()
    with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
        utterance = _run(_end_turn(_MARKER), receipt)
    assert utterance == _MARKER
    out = receipt.output
    assert out is not None and out.explanation == _MARKER
    assert out.mastery_update_allowed is False
    assert out.diagnosis.concept_id == _CONCEPT and out.diagnosis.misconception_id == _MID
    assert out.hint_level == 2 and out.response_strategy == "guided_question"
    assert out.next_action == "continue_dialogue"
    rec = _record(caplog)
    assert rec.primary_outcome == "adopted"
    assert rec.llm_output_rejections == 0
    assert rec.tutor_output_reason_code is None


@pytest.mark.parametrize(
    "raw",
    [
        _end_turn(_MARKER, mastery_update_allowed=True),
        _end_turn(_MARKER, mastery_level="숙달"),
        _end_turn(_MARKER, student_ability=0.9),
    ],
)
def test_runner_state_claim_never_reaches_student(
    raw: str, caplog: pytest.LogCaptureFixture
) -> None:
    receipt = TutorOutputReceipt()
    with caplog.at_level(logging.INFO):
        utterance = _run(raw, receipt)
    assert utterance == ENCOURAGE_FALLBACK_UTTERANCE  # 결정론 강등 발화
    assert utterance is not None and "ZZTUTORMARKERZZ" not in utterance
    assert receipt.output is not None and receipt.output.mastery_update_allowed is False
    rec = _record(caplog)
    assert rec.primary_outcome == "fallback_llm_degraded"
    assert rec.llm_output_rejections is not None and rec.llm_output_rejections >= 1


def test_runner_overlong_utterance_falls_back_with_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """2단계 집행 — 정책·하네스·톤필터를 다 통과한 발화도 스키마(길이)에 걸리면 None."""
    long_utterance = _MARKER + " " + "가" * MAX_EXPLANATION_CHARS
    receipt = TutorOutputReceipt()
    receipt.output = _ok_output()  # 이전 턴 값이 남아 있어도 지워져야 한다
    with caplog.at_level(logging.INFO):
        utterance = _run(_end_turn(long_utterance), receipt)
    assert utterance is None
    assert receipt.output is None
    rec = _record(caplog)
    assert rec.primary_outcome == "fallback_output_schema"
    assert rec.tutor_output_reason_code == "SCHEMA_STRING_TOO_LONG"
    lines = [r.getMessage() for r in caplog.records if r.name == _PRIMARY_LOGGER]
    assert any("튜터 출력 스키마 거부(SCHEMA_STRING_TOO_LONG)" in line for line in lines), lines
    assert all("ZZTUTORMARKERZZ" not in line for line in lines)


def test_runner_without_content_emits_no_concept_in_diagnosis() -> None:
    receipt = TutorOutputReceipt()
    utterance = _run(_end_turn(_MARKER), receipt, tutor_content=None)
    assert utterance == _MARKER
    assert receipt.output is not None and receipt.output.diagnosis.concept_id is None


def test_runner_broken_json_never_reaches_student(caplog: pytest.LogCaptureFixture) -> None:
    receipt = TutorOutputReceipt()
    with caplog.at_level(logging.INFO):
        utterance = _run('{"kind": "end_turn", "utterance": "' + _MARKER, receipt)
    assert utterance == ENCOURAGE_FALLBACK_UTTERANCE
    rec = _record(caplog)
    assert rec.llm_output_rejections is not None and rec.llm_output_rejections >= 1


# ──────────────────────────────────────────────────────────────────────
# PR #1713 독립 검토 반영(중2·중1·하1~하5) — 회귀 픽스처
# ──────────────────────────────────────────────────────────────────────
def test_visible_text_control_passes() -> None:
    """대조군 — 보이지 않는 문자가 섞였어도 보이는 글자가 있으면 통과한다."""
    out = validate_tutor_output(
        _valid_payload(explanation="​왜 그렇게 했어?"), known_concept_ids=_KNOWN
    )
    assert isinstance(out, TutorTurnOutput)


def test_mastery_zero_is_rejected_even_without_the_gate() -> None:
    """`0 == False`라 Literal만으로는 통과한다 — 모델 직접 생성에서도 `is False` 검사가 막는다."""
    with pytest.raises(ValidationError):
        TutorTurnOutput.model_validate(_valid_payload(mastery_update_allowed=0))
    assert TutorTurnOutput.model_validate(_valid_payload()).mastery_update_allowed is False


@pytest.mark.parametrize(
    "key", ["probability", "capability", "probabilities", "masterpiece", "reason"]
)
def test_state_key_words_do_not_false_positive(key: str) -> None:
    """검토 하3 — 부분 문자열 일치가 `probability`·`capability`를 거부하던 거짓 양성 해소."""
    payload = {"kind": "end_turn", "action_type": "질문", key: 1}
    assert classify_action_payload(payload) is None


def test_nested_contract_echo_is_allowed() -> None:
    payload = {"kind": "end_turn", "action_type": "질문", "meta": {"mastery_update_allowed": False}}
    assert classify_action_payload(payload) is None


@pytest.mark.parametrize("weight", [0, 0.0, 0.5, 1, 1.0])
def test_weight_in_range_passes(weight: float) -> None:
    payload = {"kind": "log_evidence", "misconception_id": _MID, "polarity": 1, "weight": weight}
    assert classify_action_payload(payload) is None


def test_builder_rejects_encouragement_on_a_turn_to_revise() -> None:
    """검토 중2 — 틀린 풀이 턴에 격려(정책이 고른 격려 포함)는 구조체가 되지 못한다."""
    assert _build(action_type="격려", verify_verdict="incorrect") == "SCHEMA_VALUE_ERROR"
    assert isinstance(_build(action_type="격려", verify_verdict="correct"), TutorTurnOutput)


def test_builder_skips_out_of_catalog_hypotheses(caplog: pytest.LogCaptureFixture) -> None:
    """검토 하5 — DB에 남은 구판 id가 최상위여도 출력 전체가 거부되지 않는다(건너뛰고 WARNING)."""
    stale = _hyp("removed-legacy-misconception", 0.95)
    with caplog.at_level(logging.WARNING, logger="whymath.harness.wh1_tutor_output"):
        out = _build(hypotheses=[stale, _hyp(_MID, 0.5)])
    assert isinstance(out, TutorTurnOutput)
    assert out.diagnosis.misconception_id == _MID
    assert any("카탈로그 밖 가설 1건" in r.getMessage() for r in caplog.records)
    assert all("removed-legacy" not in r.getMessage() for r in caplog.records)
    only_stale = _build(hypotheses=[stale])
    assert isinstance(only_stale, TutorTurnOutput) and only_stale.diagnosis.misconception_id is None


# ── 러너 회귀(검토 중2) — 오답 턴의 환각 개념 id는 그 도구만 실패, 학생 발화는 격려가 아니다 ──
class _SeqProvider:
    """차례로 다른 원시 출력을 돌려준다(마지막은 반복)."""

    def __init__(self, raws: Sequence[str]) -> None:
        self._raws = list(raws)

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        return GenerationResult(self._raws.pop(0) if len(self._raws) > 1 else self._raws[0])


_WRONG = {"student_solution": "x+1=3 이니까 x=3", "solution_steps": ["x+1=3", "x=3"]}
_END_Q = '{"kind": "end_turn", "action_type": "질문", "utterance": "어느 단계가 이상해 보여?"}'


@pytest.mark.parametrize(
    ("tool", "content"),
    [
        ('{"kind": "query_curriculum", "node_id": "일차방정식", "relation": "선수"}', True),
        ('{"kind": "read_student_state", "node_ids": ["math.fake.node"]}', True),
        # 미매핑 턴 — 프롬프트에 개념이 없으니 실재 code라도 LLM이 받은 id가 아니다.
        ('{"kind": "query_curriculum", "node_id": "' + _CONCEPT + '"}', False),
    ],
)
def test_wrong_answer_turn_with_bad_concept_id_is_not_encouraged(
    tool: str, content: bool, caplog: pytest.LogCaptureFixture
) -> None:
    receipt = TutorOutputReceipt()
    with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
        utterance = _run(
            "",
            receipt,
            **_WRONG,
            active_hypotheses=[],
            provider=_SeqProvider(['{"kind": "verify_step"}', tool, _END_Q]),
            tutor_content=(
                TutorContentSummary(concept=ConceptBrief(code=_CONCEPT, name="일차방정식"))
                if content
                else None
            ),
        )
    # main e609c543과 같은 학생 발화 — 오답 턴의 하네스 중립 유도 질문(정답 억제 백스톱).
    assert utterance == NEUTRAL_GUIDE_UTTERANCE
    assert utterance != ENCOURAGE_FALLBACK_UTTERANCE
    out = receipt.output
    assert out is not None
    assert (out.response_strategy, out.next_action) == ("guided_question", "revise_solution")
    assert out.explanation_source == "harness_template"
    rec = _record(caplog)
    assert rec.concept_id_tool_rejections == 1  # 그 도구만 실패
    assert rec.llm_output_rejections == 0  # 턴 종료·강등 없음
    assert rec.primary_outcome == "adopted"


def test_wrong_answer_turn_with_valid_concept_id_control() -> None:
    """대조군 — 허용 id면 도구 성공·같은 발화."""
    receipt = TutorOutputReceipt()
    utterance = _run(
        "",
        receipt,
        **_WRONG,
        active_hypotheses=[],
        provider=_SeqProvider(
            [
                '{"kind": "verify_step"}',
                '{"kind": "query_curriculum", "node_id": "' + _CONCEPT + '"}',
                _END_Q,
            ]
        ),
    )
    assert utterance == NEUTRAL_GUIDE_UTTERANCE


def test_degraded_wrong_answer_turn_asks_instead_of_encouraging() -> None:
    """검토 중2 (b) — 검증 뒤 LLM 출력이 거부돼 강등돼도, 오답 턴이면 격려가 아니라 질문."""
    receipt = TutorOutputReceipt()
    utterance = _run(
        "",
        receipt,
        **_WRONG,
        active_hypotheses=[],
        provider=_SeqProvider(['{"kind": "verify_step"}', '{"kind": "end_turn"']),
    )
    assert utterance == NEUTRAL_GUIDE_UTTERANCE
    assert receipt.output is not None
    assert receipt.output.response_strategy == "guided_question"


def test_degraded_correct_turn_still_encourages() -> None:
    """대조군 — 정답 턴의 강등은 격려 그대로."""
    utterance = _run(
        "",
        TutorOutputReceipt(),
        provider=_SeqProvider(['{"kind": "verify_step"}', '{"kind": "end_turn"']),
    )
    assert utterance == ENCOURAGE_FALLBACK_UTTERANCE


def test_llm_chosen_encouragement_on_wrong_answer_becomes_a_question(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LLM이 오답 턴에 격려를 고르면 정책 불변식이 질문으로 강등한다(main은 격려 템플릿을 그대로
    냈다) — 하네스 소크라테스 유도가 대신 말하고 구조체도 일관된다."""
    receipt = TutorOutputReceipt()
    with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
        utterance = _run(
            "",
            receipt,
            **_WRONG,
            active_hypotheses=[],
            provider=_SeqProvider(
                ['{"kind": "verify_step"}', '{"kind": "end_turn", "action_type": "격려"}']
            ),
        )
    assert utterance == NEUTRAL_GUIDE_UTTERANCE
    assert receipt.output is not None
    assert receipt.output.response_strategy == "guided_question"
    assert _record(caplog).primary_outcome == "adopted"


def test_diagnosis_ignores_in_turn_llm_evidence() -> None:
    """검토 중1 — 턴 안 LLM 증거(가중치 상한 1.0)로 가설 세트가 바뀌어도 진단은 코치 큐레이션 세트."""
    receipt = TutorOutputReceipt()
    _run(
        "",
        receipt,
        student_solution="(a+b)^2=a^2+b^2",
        solution_steps=[],
        active_hypotheses=[_hyp(_MID, 0.9), _hyp(_MID_B, 0.6)],
        provider=_SeqProvider(
            [
                '{"kind": "log_evidence", "misconception_id": "'
                + _MID
                + '", "polarity": -1, "weight": 1.0}',
                '{"kind": "curate_hypothesis"}',
                _END_Q,
            ]
        ),
    )
    assert receipt.output is not None
    assert receipt.output.diagnosis.misconception_id == _MID
    assert receipt.output.diagnosis.confidence == pytest.approx(0.9)


def test_runner_explanation_source_marks_llm_authorship() -> None:
    receipt = TutorOutputReceipt()
    _run(_end_turn(_MARKER), receipt)
    assert receipt.output is not None and receipt.output.explanation_source == "llm"


@pytest.mark.parametrize(
    ("known", "ok"),
    [(None, True), (frozenset({"math.fake.node"}), True), (frozenset(), False), (_KNOWN, False)],
)
def test_harness_fails_only_the_tool_for_unknown_concept_ids(
    known: frozenset[str] | None, ok: bool
) -> None:
    """하네스 단위 — 허용 집합 밖이면 그 도구만 ok=False, 루프는 다음 액션으로 계속(end_turn 도달).
    None(기본)은 검사하지 않는다(shadow·Scripted 기존 동작)."""
    policy = ScriptedTutorPolicy(
        [
            QueryCurriculumAction(node_id="math.fake.node"),
            ReadStateAction(node_ids=["math.fake.node"]),
            EndTurnAction(action_type="질문", utterance=None),
        ]
    )
    outcome = asyncio.run(run_tutoring_turn(policy=policy, known_concept_ids=known))
    assert outcome.status == "ended"
    assert [r.ok for r in outcome.trace[:2]] == [ok, ok]
    if not ok:
        assert all(r.detail == CONCEPT_ID_REJECT_DETAIL for r in outcome.trace[:2])


class _VerifyThenBoomProvider:
    """첫 호출은 verify_step, 이후 provider 장애 — 정책이 불변식 *없이* 바로 강등하는 경로."""

    def __init__(self) -> None:
        self._calls = 0

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        self._calls += 1
        if self._calls == 1:
            return GenerationResult('{"kind": "verify_step"}')
        raise ConnectionError("LLM 도달 불가(테스트)")


def test_provider_failure_on_wrong_answer_asks_instead_of_encouraging() -> None:
    """검토 중2 (b) — provider 장애 강등은 `_enforce_invariants`를 거치지 않으므로 `_safe_fallback`
    자신이 오답 턴의 격려를 막아야 한다(이 픽스처가 그 절을 밟는다)."""
    receipt = TutorOutputReceipt()
    utterance = _run(
        "", receipt, **_WRONG, active_hypotheses=[], provider=_VerifyThenBoomProvider()
    )
    assert utterance == NEUTRAL_GUIDE_UTTERANCE
    assert receipt.output is not None and receipt.output.response_strategy == "guided_question"
