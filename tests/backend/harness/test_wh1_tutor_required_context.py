"""P3-74 — 필수 튜터 context 누락 판정과 폴백 표기 계약(순수·DB 0·LLM 0).

지시문 [12] 3항: "필수 context가 비어 있으면 조용히 빈 값으로 LLM을 부르지 말고 명시적으로 fallback
경로로 보낸다." 이 파일은 **무엇이 필수 누락인가**(판정)와 **폴백 표기가 거짓일 수 없는가**(검증자)를
본다. 서빙 경로가 실제로 튜터를 부르지 않는가는 `tests/backend/api/test_coach_tutor_context.py`가 본다.

- 필수 슬롯 = 학생 상태·현재 개념. 둘 다 *시스템 결함*(`source_disabled`·`lookup_failed`)일 때만 센다.
- 대조군: 같은 필수 슬롯의 정상 부재(`no_history`·`no_problem_context`·`coverage_gap`)는 0건이고,
  비필수 슬롯의 결함(스킬 조회 실패·팩/숙달 플래그 OFF)도 0건이다 — 이 대조군이 없으면 "아무 누락이나
  폴백"이라는 과잉 수정이 통과한다.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from whymath_backend.harness.wh1_tutor_context import (
    REQUIRED_CONTEXT_FALLBACK,
    REQUIRED_TUTOR_SLOTS,
    SYSTEM_DEFECT_CAUSES,
    TutorContextManifest,
    TutorContextSlot,
    build_tutor_context_manifest,
    log_tutor_context,
    required_context_missing,
    tutor_context_trace_fields,
)
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.pedagogy.pack_registry import get_pack

S = TutorContextSlot
_CTX_LOGGER = "whymath.harness.wh1_tutor_context"
_HYP = MisconceptionHypothesis(
    misconception_id="distribution-over-power",
    confidence=0.8,
    turns_since_evidence=0,
    evidence_count=1,
)


def _manifest(**over: Any) -> TutorContextManifest:
    """9종을 얻은 튜터 호출 전 매니페스트 — `over`로 조회 결과를 바꾼다."""
    pack = get_pack("CONCEPT")
    assert pack is not None
    kwargs: dict[str, Any] = {
        "problem_present": True,
        "concept_present": True,
        "concept_lookup_failed": False,
        "skill_ids": ["SK-ALG-01"],
        "skill_lookup_failed": False,
        "theta": 0.3,
        "theta_enabled": True,
        "grade": 11,
        "student_answer": "x=2",
        "solution_steps": ["x+1=3", "x=2"],
        "hypotheses": [_HYP],
        "server_mastery": 0.5,
        "client_mastery_supplied": False,
        "mastery_enabled": True,
        "pack": pack,
        "pack_enabled": True,
    }
    kwargs.update(over)
    return build_tutor_context_manifest(**kwargs)


# ──────────────────────────────────────────────────────────────────────────
# 판정 — 필수 누락 = 필수 슬롯 ∧ 시스템 결함
# ──────────────────────────────────────────────────────────────────────────
def test_required_slots_are_learner_state_and_concept() -> None:
    assert REQUIRED_TUTOR_SLOTS == (S.LEARNER_STATE, S.CONCEPT)


_REQUIRED_DEFECTS: list[tuple[str, dict[str, Any], list[TutorContextSlot]]] = [
    ("θ 조회 꺼짐", {"theta": None, "theta_enabled": False}, [S.LEARNER_STATE]),
    ("개념 조회 실패", {"concept_present": False, "concept_lookup_failed": True}, [S.CONCEPT]),
    (
        "둘 다",
        {"theta": None, "theta_enabled": False, "concept_lookup_failed": True},
        [S.LEARNER_STATE, S.CONCEPT],
    ),
]


@pytest.mark.parametrize(("label", "over", "expected"), _REQUIRED_DEFECTS)
def test_required_defect_is_counted(
    label: str, over: dict[str, Any], expected: list[TutorContextSlot]
) -> None:
    assert required_context_missing(_manifest(**over)) == expected, label


_NOT_REQUIRED: list[tuple[str, dict[str, Any]]] = [
    # 같은 필수 슬롯의 학생 측 정상 부재·커버리지 공백
    ("콜드스타트(θ 이력 없음)", {"theta": None}),
    ("콜드스타트 + 학년 없음", {"theta": None, "grade": None}),
    ("개념 미매핑(coverage_gap)", {"concept_present": False}),
    ("문항 없는 대화", {"problem_present": False, "concept_present": False}),
    # 비필수 슬롯의 결함
    ("스킬 조회 실패", {"skill_lookup_failed": True}),
    ("팩 플래그 OFF", {"pack": None, "pack_enabled": False}),
    ("숙달 플래그 OFF", {"server_mastery": None, "mastery_enabled": False}),
    # 비필수 슬롯의 정상 부재(첫 진입 텍스트 턴)
    ("답안·풀이 없음", {"student_answer": None, "solution_steps": None}),
    ("오개념 의심 없음", {"hypotheses": []}),
    ("완비", {}),
]


@pytest.mark.parametrize(("label", "over"), _NOT_REQUIRED)
def test_normal_absence_and_non_required_defect_are_not_counted(
    label: str, over: dict[str, Any]
) -> None:
    assert required_context_missing(_manifest(**over)) == [], label


def test_judgement_reads_only_manifest_status() -> None:
    """두 번째 판정 원천 금지 — 같은 매니페스트면 결과가 같고, 결과는 `status_of`의 원인에서만 나온다."""
    m = _manifest(theta=None, theta_enabled=False)
    status = m.status_of(S.LEARNER_STATE)
    assert not status.resolved and status.cause in SYSTEM_DEFECT_CAUSES
    assert required_context_missing(m) == [S.LEARNER_STATE]


# ──────────────────────────────────────────────────────────────────────────
# 폴백 표기 — 거짓 표기를 검증자가 거부한다
# ──────────────────────────────────────────────────────────────────────────
def test_with_required_fallback_marks_reason_slots_and_not_invoked() -> None:
    m = _manifest(theta=None, theta_enabled=False).with_required_fallback()
    assert m.fallback_reason == REQUIRED_CONTEXT_FALLBACK == "required_context_missing"
    assert m.required_missing == [S.LEARNER_STATE]
    assert m.tutor_invoked is False
    assert not any(s.delivered_to_tutor for s in m.slots)
    # 응답 JSON 왕복(코치 응답 `tutor_context`)이 그대로 검증을 통과한다.
    assert TutorContextManifest.model_validate(m.model_dump(mode="json")) == m


def test_fallback_cannot_be_faked_without_required_missing() -> None:
    with pytest.raises(ValueError):
        _manifest(theta=None).with_required_fallback()  # 콜드스타트는 필수 누락이 아니다


@pytest.mark.parametrize(
    "patch",
    [
        {"required_missing": ["learner_state"]},  # 사유 없이 슬롯만
        {"fallback_reason": "required_context_missing", "required_missing": []},  # 슬롯 없이
        {
            "fallback_reason": "required_context_missing",
            "required_missing": ["concept"],
        },  # 틀린 슬롯
        {
            "fallback_reason": "required_context_missing",
            "required_missing": ["learner_state"],
            "tutor_invoked": True,  # 부르고도 폴백
        },
    ],
)
def test_validator_rejects_inconsistent_fallback_marks(patch: dict[str, Any]) -> None:
    base = _manifest(theta=None, theta_enabled=False).model_dump(mode="json")
    with pytest.raises(ValueError):
        TutorContextManifest.model_validate({**base, **patch})


def test_fallback_mark_on_normal_absence_is_rejected() -> None:
    base = _manifest(theta=None).model_dump(mode="json")  # 콜드스타트
    with pytest.raises(ValueError):
        TutorContextManifest.model_validate(
            {**base, "fallback_reason": "required_context_missing", "required_missing": []}
        )


def test_plain_manifest_has_no_fallback_marks() -> None:
    m = _manifest(theta=None, theta_enabled=False)  # 결함이 있어도 폴백 표기는 집행 지점만 단다
    assert m.fallback_reason is None and m.required_missing == []


# ──────────────────────────────────────────────────────────────────────────
# 표기 — 로그·Langfuse 필드
# ──────────────────────────────────────────────────────────────────────────
def test_fallback_log_is_warning_with_reason(caplog: pytest.LogCaptureFixture) -> None:
    m = _manifest(concept_present=False, concept_lookup_failed=True).with_required_fallback()
    with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
        log_tutor_context(m, seat="coach.create_session")
    (line,) = [r for r in caplog.records if r.name == _CTX_LOGGER]
    assert line.levelno == logging.WARNING
    msg = line.getMessage()
    assert "tutor_invoked=False" in msg
    assert "폴백 required_context_missing(concept)" in msg


def test_not_invoked_without_fallback_stays_info(caplog: pytest.LogCaptureFixture) -> None:
    """대조군 — 같은 결함이라도 튜터를 원하지 않던 턴(primary OFF)은 폴백이 아니고 INFO다."""
    m = _manifest(theta=None, theta_enabled=False)
    with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
        log_tutor_context(m, seat="s")
    (line,) = [r for r in caplog.records if r.name == _CTX_LOGGER]
    assert line.levelno == logging.INFO and "폴백" not in line.getMessage()


def test_trace_fields_carry_fallback() -> None:
    m = _manifest(theta=None, theta_enabled=False).with_required_fallback()
    fields = tutor_context_trace_fields(m, seat="s")
    assert fields["fallback_reason"] == "required_context_missing"
    assert fields["required_missing"] == ["learner_state"]
    assert fields["tutor_invoked"] is False
    plain = tutor_context_trace_fields(_manifest(), seat="s")
    assert plain["fallback_reason"] is None and plain["required_missing"] == []
