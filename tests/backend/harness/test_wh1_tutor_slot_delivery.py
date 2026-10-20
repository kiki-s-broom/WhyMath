"""P3-72 — 튜터 슬롯 값 전달(개념·스킬·문제 구조·팩 요약)과 전달 경로 분리 (hermetic·LLM 0).

Kiki 결정 (가) 2026-10-20: 튜터 LLM 프롬프트에 싣는 것은 개념·스킬·문제 내용(구조)·교수 정책(pack)
요약뿐이고, 학생 개인 학습 데이터(θ·숙달도·그 파생 라벨)는 프롬프트에 싣지 않는다(서버 사적 보유는
허용). 이 파일이 동결하는 것:

① 내용 요약 타입·선택 규칙 — 상한(개념 1·스킬 이름 5·금지 모드 8·문자열 길이)과 결정론 선택.
② 매니페스트 경로 — `delivery_paths`(prompt·private_tool·output_guard)에서 `delivered_to_tutor`가
   파생되고, 학생 상태·숙달 슬롯은 prompt 경로를 가질 수 없다(검증자 거부).
③ 정책 프롬프트 — 요약이 실리고, *실제로 좌석에 넘긴* 프롬프트에서 prompt 경로가 계산된다.
   θ·숙달 값·파생 라벨·학년은 프롬프트·시스템 프롬프트 어디에도 없다(⑥ 동결).
④ 예산 — 최악의 요약 + 최대 가설·history에서도 노드 ≤ 20·토큰 ≤ 3000, 요약은 잘리지 않는다.
⑤ 러너 — 경로는 턴 *뒤* 실측(넘긴 프롬프트·보유값·가드가 실제로 돈 턴)으로 확정된다.

HTTP 서빙 경로는 `tests/backend/api/test_coach_tutor_context.py`가 본다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from pydantic import ValidationError

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
from whymath_backend.harness.wh1_tutor_context import (
    MAX_SKILL_NAMES,
    PROMPT_FORBIDDEN_SLOTS,
    PROMPT_KEY_SLOTS,
    ConceptBrief,
    PackBrief,
    ProblemBrief,
    SkillBrief,
    TutorContentSummary,
    TutorContextManifest,
    TutorContextSlot,
    TutorContextSlotStatus,
    TutorDeliveryPath,
    TutorDeliveryReceipt,
    build_tutor_content_summary,
    build_tutor_context_manifest,
)
from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.pedagogy.pack_registry import get_pack
from whymath_backend.l4.session_recall import SessionRecall

S = TutorContextSlot
P = TutorDeliveryPath
_PACK = get_pack("CONCEPT")
_THETA = 0.4137
_MASTERY = 0.5813
_ANSWER = "x+1=3 이니까 x=2"
_HYP = MisconceptionHypothesis(
    misconception_id="distribution-over-power",
    confidence=0.8,
    turns_since_evidence=0,
    evidence_count=1,
)
_PRIMARY_LOGGER = "whymath.harness.wh1_primary"
_FORBIDDEN_KEYS = {
    "theta",
    "ability",
    "mastery",
    "mastery_level",
    "bkt_mastery",
    "grade",
    "learner",
}
_MASTERY_LABELS = ("초보", "발전 중", "숙달")


@pytest.fixture(autouse=True)
def _settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _content(**over: Any) -> TutorContentSummary:
    assert _PACK is not None
    params: dict[str, Any] = {
        "concept_code": "math.algebra.linear-equation",
        "concept_name": "일차방정식",
        "skills": [("SK-ALG-02", "괄호 풀기"), ("SK-ALG-01", "등식의 성질로 이항하기")],
        "skill_total": 2,
        "problem": ProblemBrief(
            question_format="단답형", bloom_level="APPLY", has_visual=False, condition_count=2
        ),
        "pack": _PACK,
    }
    params.update(over)
    return build_tutor_content_summary(**params)


def _manifest(**over: Any) -> TutorContextManifest:
    kwargs: dict[str, Any] = {
        "problem_present": True,
        "concept_present": True,
        "concept_lookup_failed": False,
        "skill_ids": ["SK-ALG-01", "SK-ALG-02"],
        "skill_lookup_failed": False,
        "theta": _THETA,
        "theta_enabled": True,
        "grade": 11,
        "student_answer": _ANSWER,
        "solution_steps": ["x+1=3", "x=2"],
        "hypotheses": [_HYP],
        "server_mastery": _MASTERY,
        "client_mastery_supplied": False,
        "mastery_enabled": True,
        "pack": _PACK,
        "pack_enabled": True,
    }
    kwargs.update(over)
    return build_tutor_context_manifest(**kwargs)


class _CapturingProvider:
    """스크립트 JSON 반환 + 프롬프트·시스템 캡처(실 네트워크 0)."""

    def __init__(self, responses: Sequence[str] = (), default: str | None = None) -> None:
        self._responses = list(responses)
        self._default = default or '{"kind": "end_turn", "action_type": "격려"}'
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
        return GenerationResult(self._default)


def _summary(prompt: str) -> dict[str, Any]:
    start, end = prompt.index("{"), prompt.rindex("}")
    parsed: dict[str, Any] = json.loads(prompt[start : end + 1])
    return parsed


def _all_keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        keys = {str(k) for k in node}
        for v in node.values():
            keys |= _all_keys(v)
        return keys
    if isinstance(node, list):
        out: set[str] = set()
        for v in node:
            out |= _all_keys(v)
        return out
    return set()


def _numeric_forms(value: float) -> list[str]:
    return [str(value), f"{value:.2f}", f"{value:.3f}", str(round(value * 100))]


def _assert_no_student_learning_data(prompt: str, system: str) -> None:
    """⑥ 동결 판정 — 프롬프트 요약의 키와 두 문자열 전체에 θ·숙달 값·파생 라벨·학년이 없다."""
    keys = _all_keys(_summary(prompt))
    assert not keys & _FORBIDDEN_KEYS, keys & _FORBIDDEN_KEYS
    for text in (prompt, system):
        for sentinel in (*_numeric_forms(_THETA), *_numeric_forms(_MASTERY)):
            assert sentinel not in text, sentinel
        for label in _MASTERY_LABELS:
            assert label not in text, label
        assert "학년" not in text


# ──────────────────────────────────────────────────────────────────────────
# ① 내용 요약 타입·선택 규칙
# ──────────────────────────────────────────────────────────────────────────
class TestContentSummary:
    def test_skill_selection_is_sorted_by_id_and_capped(self) -> None:
        skills = [(f"SK-{i:02d}", f"스킬{i}") for i in (7, 3, 9, 1, 5, 2, 8)]
        brief = _content(skills=skills, skill_total=7).skills
        assert brief is not None
        assert brief.count == 7
        assert brief.names == ["스킬1", "스킬2", "스킬3", "스킬5", "스킬7"]  # id 오름차순 앞 5
        assert len(brief.names) == MAX_SKILL_NAMES

    def test_long_strings_are_clipped_and_overlong_code_is_dropped(self) -> None:
        summary = _content(
            concept_code="math." + "x" * 200,
            concept_name="가" * 100,
            skills=[("SK-1", "나" * 100)],
            skill_total=1,
        )
        assert summary.concept is not None and summary.skills is not None
        assert summary.concept.code is None  # 잘린 id는 다른 id다 — 싣지 않는다
        assert len(summary.concept.name) == 60 and summary.concept.name.endswith("…")
        assert len(summary.skills.names[0]) == 60

    def test_pack_summary_has_type_and_capped_forbidden_modes(self) -> None:
        assert _PACK is not None
        many = _PACK.model_copy(update={"forbidden_modes": [f"m{i}" for i in range(12)]})
        brief = _content(pack=many).pedagogy_policy
        assert brief is not None
        assert brief.k_type == _PACK.k_type
        assert brief.forbidden_modes == [f"m{i}" for i in range(8)]
        # 발문 템플릿 본문은 싣지 않는다(팩 요약에 자리가 없다).
        assert "socratic_prompt" not in brief.model_dump()

    def test_empty_inputs_give_empty_sections(self) -> None:
        summary = build_tutor_content_summary(
            concept_code=None, concept_name=None, skills=[], skill_total=0, problem=None, pack=None
        )
        assert summary.prompt_fields() == {}
        assert summary.node_count() == 0

    def test_node_count_is_concept_plus_listed_skills(self) -> None:
        assert _content().node_count() == 3

    @pytest.mark.parametrize(
        ("model", "field"),
        [
            (TutorContentSummary, "theta"),
            (TutorContentSummary, "mastery"),
            (TutorContentSummary, "grade"),
            (ProblemBrief, "answer"),
            (ProblemBrief, "answer_explanation"),
            (ProblemBrief, "question_text"),
            (ProblemBrief, "choices"),
            (PackBrief, "socratic_prompt"),
            (ConceptBrief, "mastery"),
            (SkillBrief, "mastery"),
        ],
    )
    def test_types_have_no_seat_for_student_data_or_answers(self, model: Any, field: str) -> None:
        # 결정 (가)·정답 억제 — 학생 학습 데이터·학년·정답·지문은 이 타입들을 거쳐 실릴 자리가 없다.
        base: dict[str, Any] = {
            TutorContentSummary: {},
            ProblemBrief: {},
            PackBrief: {"k_type": "CONCEPT"},
            ConceptBrief: {"name": "n"},
            SkillBrief: {"count": 1},
        }[model]
        with pytest.raises(ValidationError):
            model(**{**base, field: 1})

    def test_prompt_key_table_covers_exactly_the_content_slots(self) -> None:
        assert set(PROMPT_KEY_SLOTS.values()) == {S.CONCEPT, S.SKILL, S.PROBLEM, S.PEDAGOGY_POLICY}
        assert set(PROMPT_KEY_SLOTS) == set(TutorContentSummary.model_fields)
        assert not set(PROMPT_KEY_SLOTS.values()) & PROMPT_FORBIDDEN_SLOTS


# ──────────────────────────────────────────────────────────────────────────
# ② 매니페스트 경로 불변식
# ──────────────────────────────────────────────────────────────────────────
class TestDeliveryPathInvariants:
    def test_delivered_bit_is_derived_from_paths(self) -> None:
        with pytest.raises(ValueError):
            TutorContextSlotStatus(slot=S.CONCEPT, resolved=True, delivered_to_tutor=True, size=1)
        with pytest.raises(ValueError):
            TutorContextSlotStatus(
                slot=S.CONCEPT,
                resolved=True,
                delivered_to_tutor=False,
                size=1,
                delivery_paths=[P.PROMPT],
            )

    @pytest.mark.parametrize("slot", sorted(PROMPT_FORBIDDEN_SLOTS, key=lambda s: s.value))
    def test_learner_data_cannot_take_the_prompt_path(self, slot: TutorContextSlot) -> None:
        with pytest.raises(ValueError):
            TutorContextSlotStatus(
                slot=slot,
                resolved=True,
                delivered_to_tutor=True,
                size=1,
                delivery_paths=[P.PROMPT],
            )
        # with_delivery(=model_copy 경로)도 재검증으로 같은 거부를 낸다.
        with pytest.raises(ValueError):
            _manifest().with_delivery(tutor_invoked=True, paths={slot: {P.PROMPT}})

    def test_forbidden_set_is_exactly_learner_state_and_mastery(self) -> None:
        assert PROMPT_FORBIDDEN_SLOTS == {S.LEARNER_STATE, S.MASTERY}

    def test_paths_are_normalized_and_name_helpers_split_by_path(self) -> None:
        m = _manifest().with_delivery(
            tutor_invoked=True,
            paths={
                S.MISCONCEPTION: {P.PRIVATE_TOOL, P.PROMPT},
                S.CONCEPT: {P.PROMPT},
                S.STUDENT_ANSWER: {P.PRIVATE_TOOL},
                S.PEDAGOGY_POLICY: {P.OUTPUT_GUARD},
            },
        )
        assert m.status_of(S.MISCONCEPTION).delivery_paths == [P.PROMPT, P.PRIVATE_TOOL]
        assert m.prompt_names() == ["concept", "misconception"]
        assert m.held_privately_names() == ["student_answer", "pedagogy_policy"]
        assert m.status_of(S.MASTERY).delivery_paths == []
        assert m.status_of(S.MASTERY).delivered_to_tutor is False

    def test_duplicate_or_unordered_paths_are_rejected(self) -> None:
        with pytest.raises(ValueError):
            TutorContextSlotStatus(
                slot=S.MISCONCEPTION,
                resolved=True,
                delivered_to_tutor=True,
                size=1,
                delivery_paths=[P.PRIVATE_TOOL, P.PROMPT],
            )


# ──────────────────────────────────────────────────────────────────────────
# ③ 정책 프롬프트 — 실림·실측 회계·⑥ 동결
# ──────────────────────────────────────────────────────────────────────────
def _state(**over: Any) -> TurnState:
    params: dict[str, Any] = {"turn_index": 1, "has_solution_steps": False, "hypotheses": [_HYP]}
    params.update(over)
    return TurnState(**params)


class TestPolicyContentPrompt:
    def test_content_sections_reach_the_prompt(self) -> None:
        provider = _CapturingProvider()
        policy = LLMTutorPolicy(provider, content=_content())
        asyncio.run(policy.next_action(_state()))
        summary = _summary(provider.prompts[0])
        assert summary["concept"] == {"code": "math.algebra.linear-equation", "name": "일차방정식"}
        assert summary["skills"] == {"count": 2, "names": ["등식의 성질로 이항하기", "괄호 풀기"]}
        assert summary["problem"]["question_format"] == "단답형"
        assert summary["pedagogy_policy"]["k_type"] == "CONCEPT"

    def test_prompt_path_is_what_was_actually_sent(self) -> None:
        provider = _CapturingProvider()
        policy = LLMTutorPolicy(provider, content=_content(problem=None))
        assert policy.prompt_slots_sent == frozenset()  # 아직 아무것도 넘기지 않았다
        assert policy.planned_prompt_slots() == {S.CONCEPT, S.SKILL, S.PEDAGOGY_POLICY}
        asyncio.run(policy.next_action(_state()))
        sent_keys = set(_summary(provider.prompts[0]))
        expected = {PROMPT_KEY_SLOTS[k] for k in sent_keys if k in PROMPT_KEY_SLOTS}
        assert policy.prompt_slots_sent == expected | {S.MISCONCEPTION}
        assert S.PROBLEM not in policy.prompt_slots_sent

    def test_no_content_keeps_prompt_free_of_content_keys(self) -> None:
        provider = _CapturingProvider()
        policy = LLMTutorPolicy(provider)
        asyncio.run(policy.next_action(_state(hypotheses=[])))
        assert not set(_summary(provider.prompts[0])) & set(PROMPT_KEY_SLOTS)
        assert policy.prompt_slots_sent == frozenset()

    def test_theta_and_mastery_never_reach_prompt_or_system(self) -> None:
        # ⑥ 동결 — θ는 사적 보유(select_probe 전용). 프롬프트·시스템 프롬프트에는 값도 라벨도 없다.
        provider = _CapturingProvider(['{"kind": "select_probe"}'])
        policy = LLMTutorPolicy(
            provider, theta=_THETA, content=_content(), student_text=_ANSWER, solution_steps=["x=2"]
        )
        policy.disclose_context(
            missing=[], not_delivered=["mastery"], held_privately=["learner_state"]
        )
        action = asyncio.run(policy.next_action(_state()))
        assert getattr(action, "theta", None) == _THETA  # 사적 보유는 그대로 동작
        _assert_no_student_learning_data(provider.prompts[0], provider.systems[0])
        assert S.LEARNER_STATE in policy.private_context_slots()
        assert not policy.prompt_slots_sent & PROMPT_FORBIDDEN_SLOTS

    def test_system_prompt_says_private_holdings_are_invisible(self) -> None:
        assert "context_held_privately" in _SYSTEM_PROMPT
        assert "내용은 당신에게 보이지 않습니다" in _SYSTEM_PROMPT
        assert "정답·풀이·지문은 들어 있지 않습니다" in _SYSTEM_PROMPT
        for label in _MASTERY_LABELS:
            assert label not in _SYSTEM_PROMPT
        assert "학년" not in _SYSTEM_PROMPT

    def test_held_privately_disclosure_reaches_prompt(self) -> None:
        provider = _CapturingProvider()
        policy = LLMTutorPolicy(provider)
        policy.disclose_context(
            missing=[], not_delivered=[], held_privately=["learner_state", "student_answer"]
        )
        asyncio.run(policy.next_action(_state()))
        assert _summary(provider.prompts[0])["context_held_privately"] == [
            "learner_state",
            "student_answer",
        ]

    def test_answer_suppression_still_holds_with_content(self) -> None:
        # 정답 억제 계약 유지 — 오답 판정 뒤 LLM이 발화를 실어도 정책이 걷어 낸다(요약이 있어도).
        provider = _CapturingProvider(
            ['{"kind": "end_turn", "action_type": "힌트", "utterance": "정답은 x=2야"}']
        )
        policy = LLMTutorPolicy(provider, content=_content())
        action = asyncio.run(policy.next_action(_state(last_verdict="incorrect")))
        assert getattr(action, "utterance", "x") is None


# ──────────────────────────────────────────────────────────────────────────
# ④ 예산 — 요약이 실려도 노드 ≤ 20·토큰 ≤ 3000, 요약은 잘리지 않는다
# ──────────────────────────────────────────────────────────────────────────
def _worst_content() -> TutorContentSummary:
    assert _PACK is not None
    return build_tutor_content_summary(
        concept_code="math." + "c" * 110,
        concept_name="개" * 200,
        skills=[(f"SK-{i:02d}", "스" * 200) for i in range(30)],
        skill_total=30,
        problem=ProblemBrief(
            question_format="서술형", bloom_level="EVALUATE", has_visual=True, condition_count=20
        ),
        pack=_PACK.model_copy(update={"forbidden_modes": ["m" * 40 for _ in range(30)]}),
    )


class TestBudget:
    def test_worst_case_content_is_bounded(self) -> None:
        fields = _worst_content().prompt_fields()
        rendered = json.dumps(fields, ensure_ascii=False, indent=2)
        # 상한이 타입에 박혀 있어 압력은 상수다 — 문자 1,600(≈ 토큰 400) 이하.
        assert len(rendered) <= 1600, len(rendered)
        assert _worst_content().node_count() == 1 + MAX_SKILL_NAMES

    def test_full_pressure_keeps_node_and_token_budget_and_keeps_content(self) -> None:
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
        content = _worst_content()
        policy = LLMTutorPolicy(
            provider,
            max_history=100,
            content=content,
            session_recall=SessionRecall(
                last_polya_stage=None, last_socratic_strategies=(), turns_since=3
            ),
        )
        names = [s.value for s in S]
        policy.disclose_context(missing=names, not_delivered=names, held_privately=names)
        asyncio.run(policy.next_action(_state(hypotheses=hyps, history=history)))
        prompt = provider.prompts[0]
        summary = _summary(prompt)
        assert len(prompt) // 4 <= _MAX_PROMPT_TOKENS
        nodes = len(summary["active_hypotheses"]) + len(summary["last_match_ids"])
        assert nodes + content.node_count() <= _MAX_CONTEXT_NODES  # 노드 *총합* ≤ 20
        assert summary["context_truncated"] is True
        for key in PROMPT_KEY_SLOTS:
            assert key in summary  # 요약은 예산 루프가 자르지 않는다
        assert summary["context_held_privately"] == names

    def test_content_nodes_take_budget_from_hypotheses(self) -> None:
        hyps = [
            MisconceptionHypothesis(
                misconception_id=f"mc-{i}",
                confidence=0.5,
                turns_since_evidence=0,
                evidence_count=1,
            )
            for i in range(_MAX_CONTEXT_NODES)
        ]
        provider = _CapturingProvider()
        policy = LLMTutorPolicy(provider, content=_content())  # 노드 3(개념 1 + 스킬 2)
        asyncio.run(policy.next_action(_state(hypotheses=hyps)))
        summary = _summary(provider.prompts[0])
        assert len(summary["active_hypotheses"]) == _MAX_CONTEXT_NODES - 3
        assert summary["omitted_count"] == 3


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 러너 — 경로는 턴 뒤 실측으로 확정
# ──────────────────────────────────────────────────────────────────────────
def _run(receipt: TutorDeliveryReceipt, **kwargs: Any) -> Any:
    params: dict[str, Any] = {
        "student_solution": _ANSWER,
        "solution_steps": ["x+1=3", "x=2"],
        "active_hypotheses": [_HYP],
        "provider": _CapturingProvider(),
        "theta": _THETA,
        "pack": _PACK,
        "tutor_context": _manifest(),
        "delivery": receipt,
        "tutor_content": _content(),
    }
    params.update(kwargs)
    return asyncio.run(run_wh1_primary_turn(**params))


def _paths(receipt: TutorDeliveryReceipt) -> dict[str, list[str]]:
    assert receipt.manifest is not None
    return {s.slot.value: [p.value for p in s.delivery_paths] for s in receipt.manifest.slots}


_EXPECTED_GUARD_OFF = {
    "learner_state": ["private_tool"],
    "concept": ["prompt"],
    "skill": ["prompt"],
    "problem": ["prompt"],
    "student_answer": ["private_tool"],
    "solution_record": ["private_tool"],
    "misconception": ["prompt", "private_tool"],
    "mastery": [],
    "pedagogy_policy": ["prompt"],
}


class TestRunnerPaths:
    def test_paths_match_what_the_runner_actually_sent_and_held(self) -> None:
        provider = _CapturingProvider()
        receipt = TutorDeliveryReceipt()
        assert _run(receipt, provider=provider) is not None
        assert _paths(receipt) == _EXPECTED_GUARD_OFF
        # 독립 대조 — 캡처한 프롬프트 키에서 계산한 prompt 경로와 같다(정책 메서드를 쓰지 않는다).
        sent = set()
        for prompt in provider.prompts:
            summary = _summary(prompt)
            sent |= {k for k in summary if k in PROMPT_KEY_SLOTS}
            if summary["active_hypotheses"]:
                sent.add("misconception")
            _assert_no_student_learning_data(prompt, provider.systems[0])
        sent_slots = {PROMPT_KEY_SLOTS[k].value if k in PROMPT_KEY_SLOTS else k for k in sent}
        assert receipt.manifest is not None
        assert set(receipt.manifest.prompt_names()) == sent_slots
        assert receipt.manifest.not_delivered_names() == ["mastery"]
        first = _summary(provider.prompts[0])
        assert first["context_not_delivered"] == ["mastery"]
        assert first["context_held_privately"] == [
            "learner_state",
            "student_answer",
            "solution_record",
        ]

    def test_output_guard_counts_only_when_the_guard_ran(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WHYMATH_MODE_GUARD_RUNTIME_ENABLED", "true")
        get_settings.cache_clear()
        ran = TutorDeliveryReceipt()
        assert _run(ran) is not None
        assert _paths(ran)["pedagogy_policy"] == ["prompt", "output_guard"]
        # 발화가 없어(예산 소진) 가드가 돌지 않은 턴 — 가드가 켜져 있어도 output_guard는 없다.
        exhausted = TutorDeliveryReceipt()
        out = _run(
            exhausted,
            solution_steps=[],
            provider=_CapturingProvider(default='{"kind": "curate_hypothesis"}'),
            max_tool_calls=1,
        )
        assert out is None
        assert _paths(exhausted)["pedagogy_policy"] == ["prompt"]

    def test_guard_exception_is_not_counted_as_guard_delivery(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WHYMATH_MODE_GUARD_RUNTIME_ENABLED", "true")
        get_settings.cache_clear()

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("guard down (test)")

        monkeypatch.setattr(wh1_primary, "check_forbidden_modes", _boom)
        receipt = TutorDeliveryReceipt()
        assert _run(receipt) is not None
        assert _paths(receipt)["pedagogy_policy"] == ["prompt"]

    def test_planned_but_never_sent_prompt_is_not_counted(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 정책이 프롬프트를 한 번도 넘기기 전에 턴이 끝나면 prompt 경로는 0이다(계획값으로 채우지 않음).
        async def _dies(**kwargs: Any) -> Any:
            raise RuntimeError("harness down before first prompt (test)")

        monkeypatch.setattr(wh1_primary, "run_tutoring_turn", _dies)
        receipt = TutorDeliveryReceipt()
        with caplog.at_level(logging.WARNING, logger=_PRIMARY_LOGGER):
            assert _run(receipt) is None
        paths = _paths(receipt)
        for slot in ("concept", "skill", "problem", "pedagogy_policy"):
            assert paths[slot] == [], slot
        assert paths["misconception"] == ["private_tool"]
        assert any("계획≠실측" in r.getMessage() for r in caplog.records)

    def test_timeout_after_first_prompt_keeps_what_was_sent(self) -> None:
        class _Slow(_CapturingProvider):
            async def generate(self, *args: Any, **kwargs: Any) -> GenerationResult:
                self.prompts.append(str(args[0]))
                await asyncio.sleep(1.0)
                return GenerationResult('{"kind": "end_turn", "action_type": "격려"}')

        receipt = TutorDeliveryReceipt()
        assert _run(receipt, provider=_Slow(), timeout_seconds=0.05) is None
        assert _paths(receipt)["concept"] == ["prompt"]  # 넘긴 뒤 끊겼다 — 실렸다

    def test_turn_started_misconception_from_tools_is_not_a_context_slot(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 초기 가설 0 — 턴 도중 match→curate 도구가 만든 가설은 *도구 출력*이지 context 슬롯이 아니다.
        # 그 가설이 이후 프롬프트에 렌더돼도 판정 불일치(WARNING)·거짓 전달 표기를 내지 않는다.
        spy: list[LLMTutorPolicy] = []
        original = wh1_primary.LLMTutorPolicy

        def _policy(*args: Any, **kwargs: Any) -> LLMTutorPolicy:
            inst = original(*args, **kwargs)
            spy.append(inst)
            return inst

        monkeypatch.setattr(wh1_primary, "LLMTutorPolicy", _policy)
        receipt = TutorDeliveryReceipt()
        with caplog.at_level(logging.WARNING):
            _run(
                receipt,
                student_solution="(a+b)^2 = a^2 + b^2",
                solution_steps=[],
                active_hypotheses=[],
                tutor_context=_manifest(hypotheses=[], solution_steps=[]),
                provider=_CapturingProvider(
                    ['{"kind": "match_misconception"}', '{"kind": "curate_hypothesis"}']
                ),
            )
        (policy,) = spy
        assert S.MISCONCEPTION in policy.prompt_slots_sent  # 픽스처가 그 절을 실제로 밟았다
        assert _paths(receipt)["misconception"] == []
        assert not any("판정 불일치" in r.getMessage() for r in caplog.records)
        assert not any("계획≠실측" in r.getMessage() for r in caplog.records)
