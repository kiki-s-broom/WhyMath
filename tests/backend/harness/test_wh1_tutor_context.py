"""P3-08 — 튜터 context 9종 매니페스트: 판정·전달 회계·로그·튜터 프롬프트·관측 레코드 (hermetic·LLM 0).

막는 것은 두 가지다. ① 슬롯을 못 얻었는데 **조용히 진행**하는 것 ② 얻은 값이 튜터에 **실리지
않았는데 실린 것처럼** 표기하는 것. 그래서 슬롯마다 `resolved`와 `delivered_to_tutor`를 분리하고,
`delivered_to_tutor`가 정책 객체의 **실제 보유값**과 일치하는지를 스파이로 대조한다(전달 경로를
뮤테이션하면 RED). 대조군(9종 완비)이 초록인 것만으로는 증거가 아니므로 주입 9건이 전부 '누락
표기'로 반응해야 통과한다.

HTTP 서빙 경로(코치 핸들러가 이 판정기·영수증을 실제로 쓰는가)는 `tests/backend/api/
test_coach_tutor_context.py`가 본다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

import pytest

from whymath_backend.config import get_settings
from whymath_backend.harness import wh1_primary
from whymath_backend.harness.wh1_llm_policy import (
    _MAX_CONTEXT_NODES,
    _MAX_PROMPT_TOKENS,
    _SYSTEM_PROMPT,
    LLMTutorPolicy,
)
from whymath_backend.harness.wh1_loop import ToolResult, TurnState
from whymath_backend.harness.wh1_primary import run_wh1_primary_turn
from whymath_backend.harness.wh1_shadow import Wh1HarnessShadowObservation
from whymath_backend.harness.wh1_tutor_context import (
    SYSTEM_DEFECT_CAUSES,
    AbsenceCause,
    TutorContextManifest,
    TutorContextSlot,
    TutorContextSlotStatus,
    TutorDeliveryReceipt,
    build_tutor_context_manifest,
    log_tutor_context,
)
from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.pedagogy.pack_registry import get_pack
from whymath_backend.ops.log_scrubber import scrub_text

_CTX_LOGGER = "whymath.harness.wh1_tutor_context"
_RECORD_LOGGER = "whymath.harness.wh1_shadow.record"
_HYP = MisconceptionHypothesis(
    misconception_id="distribution-over-power",
    confidence=0.8,
    turns_since_evidence=0,
    evidence_count=1,
)
_PACK = get_pack("CONCEPT")
# 값 누출 감시 표지 — θ·숙달 수치·답안이 로그·매니페스트에 실리면 안 된다(slice 69/70 비노출 불변).
_THETA_SENTINEL = 1.2345
_MASTERY_SENTINEL = 0.6789
_ANSWER = "x+1=3 이니까 x=2"
S = TutorContextSlot
# 현재 튜터 러너가 받는 슬롯(가드 OFF 기본) — 나머지 5종은 얻어도 '미전달'이다.
_DELIVERABLE = {S.LEARNER_STATE, S.STUDENT_ANSWER, S.SOLUTION_RECORD, S.MISCONCEPTION}
_NOT_DELIVERABLE = [S.CONCEPT, S.SKILL, S.PROBLEM, S.MASTERY, S.PEDAGOGY_POLICY]


@pytest.fixture(autouse=True)
def _settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _full_kwargs() -> dict[str, Any]:
    """9종이 전부 얻어지는 정상 입력(대조군)."""
    assert _PACK is not None  # 코퍼스에 CONCEPT 팩이 실재해야 대조군이 성립한다
    return {
        "problem_present": True,
        "concept_present": True,
        "concept_lookup_failed": False,
        "skill_ids": ["SK-ALG-01", "SK-ALG-02"],
        "skill_lookup_failed": False,
        "theta": _THETA_SENTINEL,
        "theta_enabled": True,
        "grade": 11,
        "student_answer": _ANSWER,
        "solution_steps": ["x+1=3", "x=2"],
        "hypotheses": [_HYP],
        "server_mastery": _MASTERY_SENTINEL,
        "client_mastery_supplied": False,
        "mastery_enabled": True,
        "pack": _PACK,
        "pack_enabled": True,
    }


# 슬롯 하나를 비우는 주입 9건 — (비울 슬롯, kwargs 덮어쓰기, 기대 원인).
_INJECTIONS: list[tuple[TutorContextSlot, dict[str, Any], AbsenceCause]] = [
    (S.LEARNER_STATE, {"theta": None}, AbsenceCause.NO_HISTORY),
    (S.CONCEPT, {"concept_present": False, "skill_ids": []}, AbsenceCause.COVERAGE_GAP),
    (S.SKILL, {"skill_ids": []}, AbsenceCause.COVERAGE_GAP),
    (
        S.PROBLEM,
        {
            "problem_present": False,
            "concept_present": False,
            "skill_ids": [],
            "server_mastery": None,
            "pack": None,
        },
        AbsenceCause.NOT_SUPPLIED,
    ),
    (S.STUDENT_ANSWER, {"student_answer": "   "}, AbsenceCause.NOT_SUPPLIED),
    (S.SOLUTION_RECORD, {"solution_steps": None}, AbsenceCause.NOT_SUPPLIED),
    (S.MISCONCEPTION, {"hypotheses": []}, AbsenceCause.NONE_DETECTED),
    (S.MASTERY, {"server_mastery": None}, AbsenceCause.NO_HISTORY),
    (S.PEDAGOGY_POLICY, {"pack": None}, AbsenceCause.COVERAGE_GAP),
]
_IDS = [s.value for s, _, _ in _INJECTIONS]
# 연쇄 — 개념이 비면 스킬도(1홉)·숙달도(개념 없이는 숙달 조회 불가), 문제가 비면 문항 기반 전부.
_CASCADE: dict[TutorContextSlot, set[TutorContextSlot]] = {
    S.CONCEPT: {S.CONCEPT, S.SKILL},
    S.PROBLEM: {S.PROBLEM, S.CONCEPT, S.SKILL, S.MASTERY, S.PEDAGOGY_POLICY},
}


def _inject(override: dict[str, Any]) -> dict[str, Any]:
    kwargs = {**_full_kwargs(), **override}
    assert kwargs != _full_kwargs()  # 주입이 실제로 적용됐다(mutated != original)
    return kwargs


def _invoked(m: TutorContextManifest, delivered: Iterable[TutorContextSlot] = ()) -> Any:
    """튜터 호출 반영 — 실제 러너처럼 *얻은* 슬롯만 전달로 넘긴다(못 얻은 값은 전달될 수 없다)."""
    real = [s for s in delivered if m.status_of(s).resolved]
    return m.with_delivery(tutor_invoked=True, delivered=real)


# ──────────────────────────────────────────────────────────────────────────
# ① 판정기 — 대조군·주입 9건·원인 분류
# ──────────────────────────────────────────────────────────────────────────
class TestManifestDiscrimination:
    def test_control_all_nine_resolved_none_delivered_before_call(self) -> None:
        m = build_tutor_context_manifest(**_full_kwargs())
        assert m.complete is True and m.missing == []
        assert m.tutor_invoked is False
        assert [s.slot for s in m.slots] == list(S)
        assert all(s.resolved and not s.delivered_to_tutor for s in m.slots)
        # 호출 전에는 9종 전부 '미전달'이다 — 완비 턴에도 미전달 표기는 비지 않는다.
        assert m.not_delivered == list(S)
        assert m.status_of(S.SKILL).size == 2
        assert m.status_of(S.LEARNER_STATE).size == 2
        assert m.status_of(S.STUDENT_ANSWER).size is None  # 답안 길이는 노출하지 않는다

    @pytest.mark.parametrize(("slot", "override", "cause"), _INJECTIONS, ids=_IDS)
    def test_each_single_slot_injection_is_not_silent(
        self, slot: TutorContextSlot, override: dict[str, Any], cause: AbsenceCause
    ) -> None:
        m = build_tutor_context_manifest(**_inject(override))
        expected = _CASCADE.get(slot, {slot})
        assert m.complete is False
        assert set(m.missing) == expected
        status = m.status_of(slot)
        assert (status.resolved, status.cause) == (False, cause)
        for other in S:
            if other not in expected:
                assert m.status_of(other).resolved, other  # '전부 누락'으로 뭉개지지 않는다

    def test_learner_state_grade_only_is_still_missing(self) -> None:
        s = build_tutor_context_manifest(**_inject({"theta": None})).status_of(S.LEARNER_STATE)
        assert (s.resolved, s.size) == (False, 1)  # 학년만 — θ=0.0 콜드스타트를 '있음'으로 위장 X

    def test_disabled_sources_are_reported_as_disabled(self) -> None:
        m = build_tutor_context_manifest(
            **_inject(
                {
                    "theta": None,
                    "theta_enabled": False,
                    "server_mastery": None,
                    "mastery_enabled": False,
                    "pack": None,
                    "pack_enabled": False,
                }
            )
        )
        for slot in (S.LEARNER_STATE, S.MASTERY, S.PEDAGOGY_POLICY):
            assert m.status_of(slot).cause is AbsenceCause.SOURCE_DISABLED

    def test_lookup_failures_are_not_folded_into_coverage_gap(self) -> None:
        m = build_tutor_context_manifest(
            **_inject({"concept_present": False, "concept_lookup_failed": True, "skill_ids": []})
        )
        for slot in (S.CONCEPT, S.SKILL):
            assert m.status_of(slot).cause is AbsenceCause.LOOKUP_FAILED
        skill_fail = build_tutor_context_manifest(
            **_inject({"skill_ids": [], "skill_lookup_failed": True})
        )
        assert skill_fail.status_of(S.SKILL).cause is AbsenceCause.LOOKUP_FAILED
        assert skill_fail.status_of(S.CONCEPT).resolved is True

    def test_mastery_without_concept_inherits_concept_cause(self) -> None:
        m = build_tutor_context_manifest(
            **_inject({"concept_present": False, "skill_ids": [], "server_mastery": None})
        )
        assert m.status_of(S.MASTERY).cause is AbsenceCause.COVERAGE_GAP

    def test_client_mastery_signal_resolves_mastery(self) -> None:
        m = build_tutor_context_manifest(
            **_inject({"server_mastery": None, "client_mastery_supplied": True})
        )
        assert m.status_of(S.MASTERY).resolved is True

    def test_blank_solution_steps_do_not_count_as_record(self) -> None:
        m = build_tutor_context_manifest(**_inject({"solution_steps": ["", "  "]}))
        assert m.status_of(S.SOLUTION_RECORD).resolved is False

    def test_manifest_carries_no_values(self) -> None:
        raw = build_tutor_context_manifest(**_full_kwargs()).model_dump_json()
        for leak in (str(_THETA_SENTINEL), str(_MASTERY_SENTINEL), "SK-ALG-01", "x+1=3"):
            assert leak not in raw
        assert "distribution-over-power" not in raw
        assert "cause_detail" not in raw  # 예외 타입명 좌석 자체가 응답 모델에 없다
        assert str(len(_ANSWER)) not in json.dumps(
            json.loads(raw)["slots"][list(S).index(S.STUDENT_ANSWER)]
        )


class TestManifestInvariants:
    """매니페스트가 스스로 '무증상 누락'·'거짓 전달'을 표현할 수 없게 막는 검증자."""

    def test_unresolved_without_cause_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            TutorContextSlotStatus(slot=S.SKILL, resolved=False, delivered_to_tutor=False, size=0)

    def test_resolved_with_cause_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            TutorContextSlotStatus(
                slot=S.SKILL,
                resolved=True,
                delivered_to_tutor=False,
                size=1,
                cause=AbsenceCause.COVERAGE_GAP,
            )

    def test_delivered_but_unresolved_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            TutorContextSlotStatus(
                slot=S.SKILL,
                resolved=False,
                delivered_to_tutor=True,
                size=0,
                cause=AbsenceCause.COVERAGE_GAP,
            )

    def test_student_answer_size_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            TutorContextSlotStatus(
                slot=S.STUDENT_ANSWER, resolved=True, delivered_to_tutor=False, size=12
            )

    def test_manifest_missing_a_slot_is_rejected(self) -> None:
        good = build_tutor_context_manifest(**_full_kwargs())
        with pytest.raises(ValueError):
            TutorContextManifest(
                tutor_invoked=False,
                slots=good.slots[:-1],
                missing=[],
                not_delivered=[s.slot for s in good.slots[:-1]],
                complete=True,
            )

    def test_manifest_hiding_a_gap_is_rejected(self) -> None:
        gap = build_tutor_context_manifest(**_inject({"pack": None}))
        with pytest.raises(ValueError):
            TutorContextManifest(
                tutor_invoked=False,
                slots=gap.slots,
                missing=[],
                not_delivered=gap.not_delivered,
                complete=True,
            )

    def test_manifest_hiding_non_delivery_is_rejected(self) -> None:
        m = build_tutor_context_manifest(**_full_kwargs())
        with pytest.raises(ValueError):
            TutorContextManifest(
                tutor_invoked=False, slots=m.slots, missing=[], not_delivered=[], complete=True
            )

    def test_delivery_without_invocation_is_rejected(self) -> None:
        m = _invoked(build_tutor_context_manifest(**_full_kwargs()), [S.STUDENT_ANSWER])
        with pytest.raises(ValueError):
            TutorContextManifest(
                tutor_invoked=False,
                slots=m.slots,
                missing=m.missing,
                not_delivered=m.not_delivered,
                complete=m.complete,
            )

    def test_with_delivery_ignores_and_warns_on_unresolved_delivery(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        m = build_tutor_context_manifest(**_inject({"theta": None}))
        with caplog.at_level(logging.WARNING, logger=_CTX_LOGGER):
            out = m.with_delivery(tutor_invoked=True, delivered=[S.LEARNER_STATE, S.STUDENT_ANSWER])
        assert out.status_of(S.LEARNER_STATE).delivered_to_tutor is False
        assert out.status_of(S.STUDENT_ANSWER).delivered_to_tutor is True
        assert any("판정 불일치" in r.getMessage() for r in caplog.records)

    def test_not_invoked_delivers_nothing_even_if_asked(self) -> None:
        m = build_tutor_context_manifest(**_full_kwargs())
        out = m.with_delivery(tutor_invoked=False, delivered=list(S))
        assert out.tutor_invoked is False
        assert not any(s.delivered_to_tutor for s in out.slots)


# ──────────────────────────────────────────────────────────────────────────
# ② 로그 — 누락·미전달 슬롯명이 남고 값은 남지 않는다 · WARNING은 시스템 결함 ∧ 튜터 호출만
# ──────────────────────────────────────────────────────────────────────────
def _ctx_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _CTX_LOGGER]


class TestLogging:
    def test_fully_delivered_complete_manifest_logs_nothing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        m = _invoked(build_tutor_context_manifest(**_full_kwargs()), list(S))
        with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
            log_tutor_context(m, seat="t")
        assert _ctx_lines(caplog) == []

    def test_complete_but_undelivered_turn_is_still_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        m = _invoked(build_tutor_context_manifest(**_full_kwargs()), _DELIVERABLE)
        with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
            log_tutor_context(m, seat="t")
        (line,) = _ctx_lines(caplog)
        assert line.levelno == logging.INFO
        assert "튜터 미전달 5: concept skill problem mastery pedagogy_policy" in line.getMessage()

    @pytest.mark.parametrize(("slot", "override", "cause"), _INJECTIONS, ids=_IDS)
    def test_each_injection_leaves_a_line_naming_the_slot(
        self,
        caplog: pytest.LogCaptureFixture,
        slot: TutorContextSlot,
        override: dict[str, Any],
        cause: AbsenceCause,
    ) -> None:
        m = _invoked(build_tutor_context_manifest(**_inject(override)), _DELIVERABLE)
        with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
            log_tutor_context(m, seat="coach.test")
        (line,) = _ctx_lines(caplog)
        msg = line.getMessage()
        assert f"{slot.value}({cause.value})" in msg
        assert "seat=coach.test" in msg
        # 주입 9건의 원인은 전부 학생 측 부재·커버리지 공백 — 운영 상시 상태라 WARNING이 아니다.
        assert line.levelno == logging.INFO
        assert str(_THETA_SENTINEL) not in msg and str(_MASTERY_SENTINEL) not in msg

    @pytest.mark.parametrize("cause", sorted(SYSTEM_DEFECT_CAUSES, key=lambda c: c.value))
    def test_system_defect_warns_only_when_tutor_invoked(
        self, caplog: pytest.LogCaptureFixture, cause: AbsenceCause
    ) -> None:
        override = (
            {"theta": None, "theta_enabled": False}
            if cause is AbsenceCause.SOURCE_DISABLED
            else {"skill_ids": [], "skill_lookup_failed": True}
        )
        m = build_tutor_context_manifest(**_inject(override))
        with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
            log_tutor_context(_invoked(m, _DELIVERABLE), seat="invoked")
            log_tutor_context(m, seat="not-invoked")
        invoked, not_invoked = _ctx_lines(caplog)
        assert invoked.levelno == logging.WARNING
        assert not_invoked.levelno == logging.INFO  # 튜터 미호출 턴은 표기만

    def test_defect_set_is_exactly_disabled_and_failed(self) -> None:
        assert SYSTEM_DEFECT_CAUSES == {AbsenceCause.SOURCE_DISABLED, AbsenceCause.LOOKUP_FAILED}

    def test_log_line_survives_root_pii_scrubber(self, caplog: pytest.LogCaptureFixture) -> None:
        # 루트 PII 스크러버가 `student_answer=…` 꼴을 마스킹한다 — 그 형식이면 표기가 지워진다.
        m = build_tutor_context_manifest(
            **_inject(
                {
                    "problem_present": False,
                    "concept_present": False,
                    "skill_ids": [],
                    "server_mastery": None,
                    "pack": None,
                    "theta": None,
                    "student_answer": "",
                    "solution_steps": [],
                    "hypotheses": [],
                }
            )
        )
        assert set(m.missing) == set(S)  # 9종 전부 비운 최악 경우
        with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
            log_tutor_context(m, seat="t")
        (line,) = _ctx_lines(caplog)
        scrubbed = scrub_text(line.getMessage())
        assert "***MASKED***" not in scrubbed
        for status in m.slots:
            assert status.cause is not None
            assert f"{status.slot.value}({status.cause.value})" in scrubbed


# ──────────────────────────────────────────────────────────────────────────
# ③ 튜터 정책 — 실제 보유값 기준 전달 회계 + 프롬프트 정직 신호 + 예산·preload
# ──────────────────────────────────────────────────────────────────────────
class _CapturingProvider:
    """스크립트 JSON 반환 + 프롬프트·시스템 캡처(실 네트워크 0)."""

    def __init__(self, responses: Sequence[str] = ()) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []
        self.systems: list[str] = []

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        self.prompts.append(prompt)
        self.systems.append(system)
        if self._responses:
            return GenerationResult(self._responses.pop(0))
        return GenerationResult('{"kind": "end_turn", "action_type": "격려"}')


def _summary(prompt: str) -> dict[str, Any]:
    start, end = prompt.index("{"), prompt.rindex("}")
    parsed: dict[str, Any] = json.loads(prompt[start : end + 1])
    return parsed


def _first_prompt(policy: LLMTutorPolicy, provider: _CapturingProvider, state: TurnState) -> str:
    asyncio.run(policy.next_action(state))
    return provider.prompts[0]


class TestPolicyDelivery:
    def test_delivered_slots_follow_what_the_policy_holds(self) -> None:
        held = LLMTutorPolicy(
            _CapturingProvider(), student_text=_ANSWER, solution_steps=["x=2"], theta=0.3
        )
        assert held.delivered_context_slots() == {
            S.STUDENT_ANSWER,
            S.SOLUTION_RECORD,
            S.LEARNER_STATE,
        }
        empty = LLMTutorPolicy(
            _CapturingProvider(), student_text="  ", solution_steps=["", " "], theta=None
        )
        assert empty.delivered_context_slots() == frozenset()

    def test_cold_start_theta_still_feeds_probe_but_is_not_counted_delivered(self) -> None:
        provider = _CapturingProvider(['{"kind": "select_probe"}'])
        policy = LLMTutorPolicy(provider, theta=None)
        action = asyncio.run(
            policy.next_action(TurnState(turn_index=1, has_solution_steps=False, hypotheses=[]))
        )
        assert getattr(action, "theta", None) == 0.0  # 동작 불변 — 콜드스타트 0.0
        assert S.LEARNER_STATE not in policy.delivered_context_slots()


class TestPolicyPrompt:
    def test_no_disclosure_keys_by_default(self) -> None:
        provider = _CapturingProvider()
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=[_HYP])
        summary = _summary(_first_prompt(LLMTutorPolicy(provider), provider, state))
        assert "context_missing" not in summary and "context_not_delivered" not in summary

    def test_disclosure_reaches_the_prompt(self) -> None:
        provider = _CapturingProvider()
        policy = LLMTutorPolicy(provider)
        policy.disclose_context(missing=["skill"], not_delivered=["concept", "mastery"])
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=[])
        summary = _summary(_first_prompt(policy, provider, state))
        assert summary["context_missing"] == ["skill"]
        assert summary["context_not_delivered"] == ["concept", "mastery"]

    def test_system_prompt_explains_the_disclosure_keys(self) -> None:
        assert "context_missing" in _SYSTEM_PROMPT
        assert "context_not_delivered" in _SYSTEM_PROMPT

    def test_budget_guards_still_hold_with_disclosure(self) -> None:
        # 노드 상한(≤20)·토큰 상한(≤3000)은 표기가 실려도 그대로 — 표기는 절단으로 지워지지 않는다.
        hyps = [
            MisconceptionHypothesis(
                misconception_id=f"mc-{'x' * 400}-{i}",
                confidence=0.1 + i * 0.01,
                turns_since_evidence=0,
                evidence_count=1,
            )
            for i in range(_MAX_CONTEXT_NODES + 10)
        ]
        history = [ToolResult(kind=f"tool-{i}", ok=True, detail="x") for i in range(30)]
        provider = _CapturingProvider()
        policy = LLMTutorPolicy(provider, max_history=100)
        names = [s.value for s in S]
        policy.disclose_context(missing=names, not_delivered=names)
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=hyps, history=history)
        prompt = _first_prompt(policy, provider, state)
        summary = _summary(prompt)
        assert len(prompt) // 4 <= _MAX_PROMPT_TOKENS
        assert len(summary["active_hypotheses"]) <= _MAX_CONTEXT_NODES
        assert summary["context_truncated"] is True
        assert summary["context_missing"] == names and summary["context_not_delivered"] == names

    def test_warmstart_outside_mids_are_not_preloaded_into_prompt(self) -> None:
        # 오개념 preload 금지 — 웜스타트 탐색 표적은 정책 사적 보유(select_probe) 전용이다.
        provider = _CapturingProvider()
        policy = LLMTutorPolicy(provider, outside_mids=["sign-flip-in-inequality"])
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=[])
        prompt = _first_prompt(policy, provider, state)
        assert "sign-flip-in-inequality" not in prompt
        assert _summary(prompt)["active_hypotheses"] == []


# ──────────────────────────────────────────────────────────────────────────
# ④ 러너 — 영수증의 전달 판정이 '실제로 넘긴 것'과 일치하는가 (스파이 대조)
# ──────────────────────────────────────────────────────────────────────────
def _records(caplog: pytest.LogCaptureFixture) -> list[Wh1HarnessShadowObservation]:
    return [
        Wh1HarnessShadowObservation.model_validate_json(r.getMessage())
        for r in caplog.records
        if r.name == _RECORD_LOGGER
    ]


class _Spy:
    def __init__(self) -> None:
        self.policies: list[LLMTutorPolicy] = []
        self.initial_hypotheses: list[list[MisconceptionHypothesis]] = []


def _spy_runner(monkeypatch: pytest.MonkeyPatch) -> _Spy:
    """정책 인스턴스와 `run_tutoring_turn`에 실제로 넘어간 초기 가설을 붙잡는다."""
    spy = _Spy()
    original_policy = wh1_primary.LLMTutorPolicy
    original_turn = wh1_primary.run_tutoring_turn

    def _policy(*args: Any, **kwargs: Any) -> LLMTutorPolicy:
        inst = original_policy(*args, **kwargs)
        spy.policies.append(inst)
        return inst

    async def _turn(**kwargs: Any) -> Any:
        spy.initial_hypotheses.append(list(kwargs["initial_hypotheses"]))
        return await original_turn(**kwargs)

    monkeypatch.setattr(wh1_primary, "LLMTutorPolicy", _policy)
    monkeypatch.setattr(wh1_primary, "run_tutoring_turn", _turn)
    return spy


def _actually_delivered(spy: _Spy) -> set[TutorContextSlot]:
    """스파이가 본 실제 입력에서 독립적으로 계산한 전달 집합(정책 메서드를 쓰지 않는다)."""
    (policy,) = spy.policies
    actual: set[TutorContextSlot] = set()
    if policy._student_text.strip():
        actual.add(S.STUDENT_ANSWER)
    if any(step.strip() for step in policy._solution_steps):
        actual.add(S.SOLUTION_RECORD)
    if policy._theta_known:
        actual.add(S.LEARNER_STATE)
    if spy.initial_hypotheses and spy.initial_hypotheses[0]:
        actual.add(S.MISCONCEPTION)
    return actual


def _run(
    manifest: TutorContextManifest | None,
    receipt: TutorDeliveryReceipt | None,
    **kwargs: Any,
) -> Any:
    params: dict[str, Any] = {
        "student_solution": _ANSWER,
        "solution_steps": ["x+1=3", "x=2"],
        "active_hypotheses": [_HYP],
        "provider": _CapturingProvider(),
        "theta": _THETA_SENTINEL,
        "pack": _PACK,
        "tutor_context": manifest,
        "delivery": receipt,
    }
    params.update(kwargs)
    return asyncio.run(run_wh1_primary_turn(**params))


class TestPrimaryRunnerDelivery:
    def test_receipt_matches_what_was_actually_passed(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        spy = _spy_runner(monkeypatch)
        provider = _CapturingProvider()
        receipt = TutorDeliveryReceipt()
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            out = _run(build_tutor_context_manifest(**_full_kwargs()), receipt, provider=provider)
        assert out is not None
        final = receipt.manifest
        assert final is not None and final.tutor_invoked is True
        reported = {s.slot for s in final.slots if s.delivered_to_tutor}
        assert reported == _actually_delivered(spy) == _DELIVERABLE
        assert final.not_delivered == _NOT_DELIVERABLE
        summary = _summary(provider.prompts[0])
        assert summary["context_not_delivered"] == [s.value for s in _NOT_DELIVERABLE]
        assert "context_missing" not in summary  # 9종 다 얻은 턴
        (record,) = _records(caplog)
        assert record.context_missing == []
        assert record.context_not_delivered == [s.value for s in _NOT_DELIVERABLE]
        assert record.context_coverage_gap == []

    def test_empty_inputs_are_reported_undelivered_and_match_spy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = _spy_runner(monkeypatch)
        receipt = TutorDeliveryReceipt()
        manifest = build_tutor_context_manifest(
            **_inject({"theta": None, "student_answer": "", "solution_steps": [], "hypotheses": []})
        )
        _run(
            manifest,
            receipt,
            student_solution="",
            solution_steps=[],
            active_hypotheses=[],
            theta=None,
        )
        assert receipt.manifest is not None
        reported = {s.slot for s in receipt.manifest.slots if s.delivered_to_tutor}
        assert reported == _actually_delivered(spy) == set()

    def test_pack_counts_as_delivered_only_when_mode_guard_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        receipt = TutorDeliveryReceipt()
        _run(build_tutor_context_manifest(**_full_kwargs()), receipt)
        assert receipt.manifest is not None
        assert receipt.manifest.status_of(S.PEDAGOGY_POLICY).delivered_to_tutor is False
        monkeypatch.setenv("WHYMATH_MODE_GUARD_RUNTIME_ENABLED", "true")
        get_settings.cache_clear()
        guarded = TutorDeliveryReceipt()
        _run(build_tutor_context_manifest(**_full_kwargs()), guarded)
        assert guarded.manifest is not None
        assert guarded.manifest.status_of(S.PEDAGOGY_POLICY).delivered_to_tutor is True

    def test_failure_before_policy_construction_delivers_nothing(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def _boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("probe pool down (test)")

        monkeypatch.setattr(wh1_primary, "assemble_probe_candidate_pool", _boom)
        receipt = TutorDeliveryReceipt()
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            out = _run(build_tutor_context_manifest(**_full_kwargs()), receipt)
        assert out is None
        assert receipt.manifest is not None and receipt.manifest.tutor_invoked is True
        assert not any(s.delivered_to_tutor for s in receipt.manifest.slots)
        (record,) = _records(caplog)
        assert record.status == "aborted"
        assert record.context_not_delivered == [s.value for s in S]

    def test_aborted_turn_records_missing_and_coverage_gap(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        class _Slow(_CapturingProvider):
            async def generate(self, *args: Any, **kwargs: Any) -> GenerationResult:
                await asyncio.sleep(1.0)
                return GenerationResult('{"kind": "end_turn", "action_type": "격려"}')

        manifest = build_tutor_context_manifest(**_inject({"pack": None}))
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            out = _run(manifest, TutorDeliveryReceipt(), provider=_Slow(), timeout_seconds=0.05)
        assert out is None
        (record,) = _records(caplog)
        assert record.status == "aborted"
        assert record.context_missing == ["pedagogy_policy"]
        assert record.context_coverage_gap == ["pedagogy_policy"]

    def test_legacy_caller_without_manifest_records_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            _run(None, None)
        (record,) = _records(caplog)
        assert record.context_missing is None
        assert record.context_not_delivered is None
        assert record.context_coverage_gap is None
