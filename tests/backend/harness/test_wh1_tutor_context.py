"""P3-08 — 튜터 context 9종 매니페스트: 판정·로그·튜터 프롬프트·관측 레코드 (hermetic·LLM 0).

막는 것: context 슬롯이 비었는데 **조용히 진행**하는 것. 그래서 정상 입력 대조군(9종 완비 → 누락 0)과
9종을 하나씩 비우는 주입 9건(파라미터화)을 같은 판정기에 넣어, 주입마다 ① 그 슬롯이 `missing`에
뜨고 ② 나머지 8종은 그대로 채워져 있으며 ③ 로그 1줄에 슬롯명이 남고 ④ 튜터 프롬프트의
`context_missing`과 관측 레코드에 그 이름이 실리는지를 본다. 대조군이 초록인 것만으로는 증거가
아니므로 주입 9건이 전부 '누락 표기'로 반응해야 통과한다.

HTTP 서빙 경로(코치 핸들러가 이 판정기를 실제로 부르는가)는 `tests/backend/api/
test_coach_tutor_context.py`가 본다 — 이 파일은 판정기·러너 좌석의 계약이다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from typing import Any

import pytest

from whymath_backend.harness.wh1_llm_policy import (
    _MAX_CONTEXT_NODES,
    _MAX_PROMPT_TOKENS,
    LLMTutorPolicy,
)
from whymath_backend.harness.wh1_loop import ToolResult, TurnState
from whymath_backend.harness.wh1_primary import run_wh1_primary_turn
from whymath_backend.harness.wh1_shadow import Wh1HarnessShadowObservation
from whymath_backend.harness.wh1_tutor_context import (
    SYSTEM_GAP_CAUSES,
    AbsenceCause,
    TutorContextManifest,
    TutorContextSlot,
    TutorContextSlotStatus,
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
# 값 누출 감시 표지 — θ·숙달 수치가 로그·매니페스트에 실리면 안 된다(slice 69/70 비노출 불변).
_THETA_SENTINEL = 1.2345
_MASTERY_SENTINEL = 0.6789


def _full_kwargs() -> dict[str, Any]:
    """9종이 전부 채워지는 정상 입력(대조군)."""
    assert _PACK is not None  # 코퍼스에 CONCEPT 팩이 실재해야 대조군이 성립한다
    return {
        "problem_present": True,
        "concept_present": True,
        "concept_lookup_error": None,
        "skill_ids": ["SK-ALG-01", "SK-ALG-02"],
        "skill_lookup_error": None,
        "theta": _THETA_SENTINEL,
        "theta_enabled": True,
        "grade": 11,
        "student_answer": "x+1=3 이니까 x=2",
        "solution_steps": ["x+1=3", "x=2"],
        "hypotheses": [_HYP],
        "server_mastery": _MASTERY_SENTINEL,
        "client_mastery_supplied": False,
        "mastery_enabled": True,
        "pack": _PACK,
        "pack_enabled": True,
    }


# 슬롯 하나를 비우는 주입 9건 — (비울 슬롯, kwargs 덮어쓰기, 기대 원인).
# 문제(problem) 주입은 문항 기반 슬롯 전체를 연쇄로 비우므로 기대 누락 집합을 따로 적는다.
_INJECTIONS: list[tuple[TutorContextSlot, dict[str, Any], AbsenceCause]] = [
    (TutorContextSlot.LEARNER_STATE, {"theta": None}, AbsenceCause.UNRESOLVED),
    (TutorContextSlot.CONCEPT, {"concept_present": False}, AbsenceCause.UNRESOLVED),
    (TutorContextSlot.SKILL, {"skill_ids": []}, AbsenceCause.UNRESOLVED),
    (TutorContextSlot.PROBLEM, {"problem_present": False}, AbsenceCause.NOT_SUPPLIED),
    (TutorContextSlot.STUDENT_ANSWER, {"student_answer": "   "}, AbsenceCause.NOT_SUPPLIED),
    (TutorContextSlot.SOLUTION_RECORD, {"solution_steps": None}, AbsenceCause.NOT_SUPPLIED),
    (TutorContextSlot.MISCONCEPTION, {"hypotheses": []}, AbsenceCause.NONE_DETECTED),
    (TutorContextSlot.MASTERY, {"server_mastery": None}, AbsenceCause.UNRESOLVED),
    (TutorContextSlot.PEDAGOGY_POLICY, {"pack": None}, AbsenceCause.UNRESOLVED),
]
# 연쇄 — 개념이 비면 스킬도(1홉), 문제가 비면 문항 기반 조회 슬롯 전부가 빈다.
_CASCADE: dict[TutorContextSlot, set[TutorContextSlot]] = {
    TutorContextSlot.CONCEPT: {TutorContextSlot.CONCEPT, TutorContextSlot.SKILL},
    TutorContextSlot.PROBLEM: {
        TutorContextSlot.PROBLEM,
        TutorContextSlot.CONCEPT,
        TutorContextSlot.SKILL,
        TutorContextSlot.MASTERY,
        TutorContextSlot.PEDAGOGY_POLICY,
    },
}


def _problem_cascade_kwargs() -> dict[str, Any]:
    # 문항이 없으면 핸들러는 개념·숙달·팩도 못 얻는다 — 실제 서빙 경로의 값 조합을 그대로 재현.
    return {
        "problem_present": False,
        "concept_present": False,
        "skill_ids": [],
        "server_mastery": None,
        "pack": None,
    }


def _inject(slot: TutorContextSlot, override: dict[str, Any]) -> dict[str, Any]:
    kwargs = _full_kwargs()
    kwargs.update(_problem_cascade_kwargs() if slot is TutorContextSlot.PROBLEM else override)
    if slot is TutorContextSlot.CONCEPT:
        kwargs["skill_ids"] = []  # 개념이 없으면 스킬 해소가 성립하지 않는다(핸들러와 동일)
    assert kwargs != _full_kwargs()  # 주입이 실제로 적용됐다(mutated != original)
    return kwargs


# ──────────────────────────────────────────────────────────────────────────
# ① 판정기 — 대조군·주입 9건
# ──────────────────────────────────────────────────────────────────────────
class TestManifestDiscrimination:
    def test_control_all_nine_filled(self) -> None:
        m = build_tutor_context_manifest(**_full_kwargs())
        assert m.complete is True
        assert m.missing == []
        assert [s.slot for s in m.slots] == list(TutorContextSlot)
        assert all(s.filled and s.cause is None for s in m.slots)
        # 크기는 값이 아니라 개수다 — 스킬 2·답안 문자 수·단계 2·가설 1·학생 상태 축 2.
        assert m.status_of(TutorContextSlot.SKILL).size == 2
        assert m.status_of(TutorContextSlot.SOLUTION_RECORD).size == 2
        assert m.status_of(TutorContextSlot.MISCONCEPTION).size == 1
        assert m.status_of(TutorContextSlot.LEARNER_STATE).size == 2

    @pytest.mark.parametrize(
        ("slot", "override", "cause"), _INJECTIONS, ids=[s.value for s, _, _ in _INJECTIONS]
    )
    def test_each_single_slot_injection_is_not_silent(
        self, slot: TutorContextSlot, override: dict[str, Any], cause: AbsenceCause
    ) -> None:
        m = build_tutor_context_manifest(**_inject(slot, override))
        expected_missing = _CASCADE.get(slot, {slot})
        assert m.complete is False
        assert set(m.missing) == expected_missing
        status = m.status_of(slot)
        assert status.filled is False
        assert status.cause is cause
        # 주입하지 않은 슬롯은 그대로 채워져 있다 — 판정이 '전부 누락'으로 뭉개지지 않는다.
        for other in TutorContextSlot:
            if other not in expected_missing:
                assert m.status_of(other).filled, other

    def test_learner_state_grade_only_is_still_missing(self) -> None:
        # θ 없이 학년만 있으면 튜터는 θ=0.0 콜드스타트로 돈다 — '있음'으로 위장하지 않는다.
        m = build_tutor_context_manifest(**{**_full_kwargs(), "theta": None})
        s = m.status_of(TutorContextSlot.LEARNER_STATE)
        assert s.filled is False and s.size == 1

    def test_disabled_sources_are_reported_as_disabled_not_unresolved(self) -> None:
        kwargs = {
            **_full_kwargs(),
            "theta": None,
            "theta_enabled": False,
            "server_mastery": None,
            "mastery_enabled": False,
            "pack": None,
            "pack_enabled": False,
        }
        m = build_tutor_context_manifest(**kwargs)
        for slot in (
            TutorContextSlot.LEARNER_STATE,
            TutorContextSlot.MASTERY,
            TutorContextSlot.PEDAGOGY_POLICY,
        ):
            assert m.status_of(slot).cause is AbsenceCause.SOURCE_DISABLED

    def test_lookup_failure_carries_exception_type_name(self) -> None:
        m = build_tutor_context_manifest(
            **{
                **_full_kwargs(),
                "concept_present": False,
                "concept_lookup_error": "OperationalError",
                "skill_ids": [],
            }
        )
        for slot in (TutorContextSlot.CONCEPT, TutorContextSlot.SKILL):
            s = m.status_of(slot)
            assert s.cause is AbsenceCause.LOOKUP_FAILED
            assert s.cause_detail == "OperationalError"
        skill_fail = build_tutor_context_manifest(
            **{**_full_kwargs(), "skill_ids": [], "skill_lookup_error": "TimeoutError"}
        )
        s = skill_fail.status_of(TutorContextSlot.SKILL)
        assert (s.cause, s.cause_detail) == (AbsenceCause.LOOKUP_FAILED, "TimeoutError")
        assert skill_fail.status_of(TutorContextSlot.CONCEPT).filled is True

    def test_client_mastery_signal_fills_mastery(self) -> None:
        m = build_tutor_context_manifest(
            **{**_full_kwargs(), "server_mastery": None, "client_mastery_supplied": True}
        )
        assert m.status_of(TutorContextSlot.MASTERY).filled is True

    def test_blank_solution_steps_do_not_count_as_record(self) -> None:
        m = build_tutor_context_manifest(**{**_full_kwargs(), "solution_steps": ["", "  "]})
        assert m.status_of(TutorContextSlot.SOLUTION_RECORD).filled is False

    def test_manifest_carries_no_values(self) -> None:
        raw = build_tutor_context_manifest(**_full_kwargs()).model_dump_json()
        assert str(_THETA_SENTINEL) not in raw
        assert str(_MASTERY_SENTINEL) not in raw
        assert "SK-ALG-01" not in raw
        assert "x+1=3" not in raw
        assert "distribution-over-power" not in raw


class TestManifestInvariants:
    """매니페스트가 스스로 '무증상 누락'을 표현할 수 없게 막는 검증자 — 위반 주입이 거부돼야 한다."""

    def test_empty_slot_without_cause_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            TutorContextSlotStatus(slot=TutorContextSlot.SKILL, filled=False, size=0)

    def test_filled_slot_with_cause_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            TutorContextSlotStatus(
                slot=TutorContextSlot.SKILL, filled=True, size=1, cause=AbsenceCause.UNRESOLVED
            )

    def test_manifest_missing_a_slot_is_rejected(self) -> None:
        good = build_tutor_context_manifest(**_full_kwargs())
        with pytest.raises(ValueError):
            TutorContextManifest(slots=good.slots[:-1], missing=[], complete=True)

    def test_manifest_hiding_a_gap_is_rejected(self) -> None:
        gap = build_tutor_context_manifest(**{**_full_kwargs(), "pack": None})
        with pytest.raises(ValueError):
            TutorContextManifest(slots=gap.slots, missing=[], complete=True)


# ──────────────────────────────────────────────────────────────────────────
# ② 로그 — 누락 슬롯명·원인·예외 타입명이 남고, 값은 남지 않는다
# ──────────────────────────────────────────────────────────────────────────
class TestLogging:
    def test_complete_manifest_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
            log_tutor_context(build_tutor_context_manifest(**_full_kwargs()), seat="t")
        assert [r for r in caplog.records if r.name == _CTX_LOGGER] == []

    @pytest.mark.parametrize(
        ("slot", "override", "cause"), _INJECTIONS, ids=[s.value for s, _, _ in _INJECTIONS]
    )
    def test_each_injection_leaves_a_log_line_naming_the_slot(
        self,
        caplog: pytest.LogCaptureFixture,
        slot: TutorContextSlot,
        override: dict[str, Any],
        cause: AbsenceCause,
    ) -> None:
        m = build_tutor_context_manifest(**_inject(slot, override))
        with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
            log_tutor_context(m, seat="coach.test")
        lines = [r for r in caplog.records if r.name == _CTX_LOGGER]
        assert len(lines) == 1
        msg = lines[0].getMessage()
        assert f"{slot.value}({cause.value})" in msg
        assert "seat=coach.test" in msg
        has_system_gap = any(m.status_of(s).cause in SYSTEM_GAP_CAUSES for s in m.missing)
        assert lines[0].levelno == (logging.WARNING if has_system_gap else logging.INFO)
        assert str(_THETA_SENTINEL) not in msg and str(_MASTERY_SENTINEL) not in msg

    def test_lookup_failure_logs_exception_type_name(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        m = build_tutor_context_manifest(
            **{**_full_kwargs(), "skill_ids": [], "skill_lookup_error": "OperationalError"}
        )
        with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
            log_tutor_context(m, seat="t")
        (line,) = [r for r in caplog.records if r.name == _CTX_LOGGER]
        assert line.levelno == logging.WARNING
        assert "skill(lookup_failed·OperationalError)" in line.getMessage()

    def test_log_line_survives_root_pii_scrubber(self, caplog: pytest.LogCaptureFixture) -> None:
        # 운영 루트 로거의 PII 스크러버가 `student_answer=…` 꼴을 학생 원문 필드로 마스킹한다 —
        # 누락 표기가 그 형식이면 슬롯명·원인이 지워져 '로그에 남는다'가 거짓이 된다(실측 회귀).
        names = {s.value for s in TutorContextSlot}
        kwargs = {
            **_full_kwargs(),
            **_problem_cascade_kwargs(),
            "theta": None,
            "student_answer": "",
            "solution_steps": [],
            "hypotheses": [],
        }
        m = build_tutor_context_manifest(**kwargs)
        assert set(m.missing_names()) == names  # 9종 전부 비운 최악 경우
        with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
            log_tutor_context(m, seat="t")
        (line,) = [r for r in caplog.records if r.name == _CTX_LOGGER]
        scrubbed = scrub_text(line.getMessage())
        assert "***MASKED***" not in scrubbed
        for status in m.slots:
            assert status.cause is not None
            assert f"{status.slot.value}({status.cause.value})" in scrubbed


# ──────────────────────────────────────────────────────────────────────────
# ③ 튜터 프롬프트 — context_missing 정직 신호 + subgraph 예산·preload 금지 유지
# ──────────────────────────────────────────────────────────────────────────
class _CapturingProvider:
    """스크립트 JSON 반환 + 프롬프트 캡처(실 네트워크 0)."""

    def __init__(self, responses: Sequence[str] = ()) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        self.prompts.append(prompt)
        if self._responses:
            return GenerationResult(self._responses.pop(0))
        return GenerationResult('{"kind": "end_turn", "action_type": "격려"}')


def _summary(prompt: str) -> dict[str, Any]:
    start, end = prompt.index("{"), prompt.rindex("}")
    parsed: dict[str, Any] = json.loads(prompt[start : end + 1])
    return parsed


def _first_prompt(policy_kwargs: dict[str, Any], state: TurnState) -> str:
    provider = _CapturingProvider()
    policy = LLMTutorPolicy(provider, **policy_kwargs)
    asyncio.run(policy.next_action(state))
    return provider.prompts[0]


class TestPolicyPrompt:
    def test_no_context_missing_key_by_default_and_bytes_unchanged(self) -> None:
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=[_HYP])
        base = _first_prompt({}, state)
        assert "context_missing" not in _summary(base)
        assert _first_prompt({"context_missing": ()}, state) == base

    def test_missing_slots_reach_the_prompt(self) -> None:
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=[])
        prompt = _first_prompt({"context_missing": ("skill", "pedagogy_policy")}, state)
        assert _summary(prompt)["context_missing"] == ["skill", "pedagogy_policy"]

    def test_budget_guards_still_hold_with_context_missing(self) -> None:
        # 노드 상한(≤20)·토큰 상한(≤3000)은 context_missing이 실려도 그대로 — 그리고 누락 표기는
        # 예산 절단으로 지워지지 않는다(지우면 그 자체가 무증상 누락).
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
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=hyps, history=history)
        names = tuple(s.value for s in TutorContextSlot)
        prompt = _first_prompt({"context_missing": names, "max_history": 100}, state)
        summary = _summary(prompt)
        assert len(prompt) // 4 <= _MAX_PROMPT_TOKENS
        assert len(summary["active_hypotheses"]) <= _MAX_CONTEXT_NODES
        assert summary["context_truncated"] is True
        assert summary["context_missing"] == list(names)

    def test_warmstart_outside_mids_are_not_preloaded_into_prompt(self) -> None:
        # 오개념 preload 금지 — 웜스타트 탐색 표적은 정책 사적 보유(select_probe)이고 프롬프트에는
        # 이번 턴 매칭에서 큐레이션된 가설만 실린다(reactive). 주입: 표적 id가 프롬프트에 새면 RED.
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=[])
        prompt = _first_prompt(
            {"outside_mids": ["sign-flip-in-inequality"], "context_missing": ("misconception",)},
            state,
        )
        assert "sign-flip-in-inequality" not in prompt
        assert _summary(prompt)["active_hypotheses"] == []


# ──────────────────────────────────────────────────────────────────────────
# ④ 러너(run_wh1_primary_turn) — 매니페스트가 프롬프트·관측 레코드까지 실제로 흐르는가
# ──────────────────────────────────────────────────────────────────────────
def _records(caplog: pytest.LogCaptureFixture) -> list[Wh1HarnessShadowObservation]:
    return [
        Wh1HarnessShadowObservation.model_validate_json(r.getMessage())
        for r in caplog.records
        if r.name == _RECORD_LOGGER
    ]


class TestPrimaryRunnerWiring:
    def test_manifest_flows_to_prompt_and_observation(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        manifest = build_tutor_context_manifest(**{**_full_kwargs(), "pack": None, "skill_ids": []})
        provider = _CapturingProvider()
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            out = asyncio.run(
                run_wh1_primary_turn(
                    student_solution="음",
                    solution_steps=[],
                    active_hypotheses=[],
                    provider=provider,
                    tutor_context=manifest,
                )
            )
        assert out is not None  # 누락이 있어도 진행한다(거부 아님)
        assert _summary(provider.prompts[0])["context_missing"] == ["skill", "pedagogy_policy"]
        (record,) = _records(caplog)
        assert record.context_missing == ["skill", "pedagogy_policy"]

    def test_complete_manifest_records_empty_list_not_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = _CapturingProvider()
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            asyncio.run(
                run_wh1_primary_turn(
                    student_solution="음",
                    solution_steps=[],
                    active_hypotheses=[],
                    provider=provider,
                    tutor_context=build_tutor_context_manifest(**_full_kwargs()),
                )
            )
        assert "context_missing" not in _summary(provider.prompts[0])
        (record,) = _records(caplog)
        assert record.context_missing == []  # 누락 0(=[])과 구판(None)을 구분한다

    def test_legacy_caller_without_manifest_records_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            asyncio.run(
                run_wh1_primary_turn(
                    student_solution="음",
                    solution_steps=[],
                    active_hypotheses=[],
                    provider=_CapturingProvider(),
                )
            )
        (record,) = _records(caplog)
        assert record.context_missing is None

    def test_aborted_turn_still_records_context_missing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        class _Slow(_CapturingProvider):
            async def generate(self, *args: Any, **kwargs: Any) -> GenerationResult:
                await asyncio.sleep(1.0)
                return GenerationResult('{"kind": "end_turn", "action_type": "격려"}')

        manifest = build_tutor_context_manifest(**{**_full_kwargs(), "theta": None})
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            out = asyncio.run(
                run_wh1_primary_turn(
                    student_solution="음",
                    solution_steps=[],
                    active_hypotheses=[],
                    provider=_Slow(),
                    timeout_seconds=0.05,
                    tutor_context=manifest,
                )
            )
        assert out is None  # 결정론 폴백 신호
        (record,) = _records(caplog)
        assert record.status == "aborted"
        assert record.context_missing == ["learner_state"]
