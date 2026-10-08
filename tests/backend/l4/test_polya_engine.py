"""L4 PolyaCoach 단위테스트 — decide() 결정 + coach() LLM 좌석.

LLM은 FakeLLM(Protocol 만족 — `async def generate`)으로 주입해 hermetic 검증.
"""

from __future__ import annotations

import pytest

from whymath_backend.l3.models import CostTier
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.models import PolyaStage, PolyaState, next_polya_stage
from whymath_backend.l4.polya.engine import PolyaCoach
from whymath_backend.l4.polya.prompts import STAGE_PROMPTS


class FakeLLM:
    """LLMSeam Protocol 만족 — 캡처된 입력·구성된 응답으로 검증 가능."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def generate(self, prompt: str, system: str) -> str:
        self.calls.append((prompt, system))
        return self.response


def _state(stage: PolyaStage) -> PolyaState:
    return PolyaState(current_stage=stage)


class TestDecideStays:
    def test_understand_short_input_stays_with_stage1_prompt(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("음", _state(PolyaStage.UNDERSTAND))
        assert d.polya_stage_to_advance == "stay"
        assert d.prompt == STAGE_PROMPTS[PolyaStage.UNDERSTAND].prompt
        assert d.system == STAGE_PROMPTS[PolyaStage.UNDERSTAND].system
        assert d.recommended_cost_tier is CostTier.LOCAL
        assert d.hint_level == 1
        assert "조건 나열" in d.suggested_actions
        # 슬라이스 2: socratic_category 채워짐 — 단계 기본(CLARIFICATION)
        assert d.socratic_category == "clarification"


class TestMasteryTransitionWiring:
    """slice 71 — decide()가 mastery_level을 should_advance에 전달(전이 가속/지연)."""

    def test_mastery_accelerates_understand_advance(self) -> None:
        coach = PolyaCoach()
        s = _state(PolyaStage.UNDERSTAND)
        text = "f의 최댓값을 구해, x>0."  # 16자 — 기본 stay·숙달 next(임계 15)
        assert coach.decide(text, s).polya_stage_to_advance == "stay"
        assert coach.decide(text, s, mastery_level="숙달").polya_stage_to_advance == "next"

    """슬라이스 3 — decide()가 PolyaState.prev_hint_level·turn_count를 읽어
    hint_level/reveals 채움."""

    def test_default_hint_level_1_with_reveals(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("음", _state(PolyaStage.UNDERSTAND))
        assert d.hint_level == 1
        assert d.reveals == "next_concept_to_focus"

    def test_frustration_signal_raises_hint_level(self) -> None:
        coach = PolyaCoach()
        s = PolyaState(current_stage=PolyaStage.PLAN, prev_hint_level=2)
        d = coach.decide("너무 어려워서 모르겠어", s)
        assert d.hint_level == 3
        assert d.reveals == "partial_steps_demo"

    def test_demand_answer_raises_hint_level(self) -> None:
        coach = PolyaCoach()
        s = PolyaState(current_stage=PolyaStage.PLAN, prev_hint_level=1)
        d = coach.decide("그냥 답이 뭐야", s)
        assert d.hint_level == 2
        assert d.reveals == "step_flow"

    def test_stuck_threshold_jumps_to_3(self) -> None:
        coach = PolyaCoach()
        s = PolyaState(current_stage=PolyaStage.EXECUTE, turn_count=5, prev_hint_level=1)
        d = coach.decide("음...", s)
        assert d.hint_level == 3
        assert d.reveals == "partial_steps_demo"


class TestSocraticCategory:
    """슬라이스 2 — `decide()`가 socratic_category를 단계·전이·발화 신호로 채운다."""

    def test_understand_default_is_clarification(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("음", _state(PolyaStage.UNDERSTAND))
        assert d.socratic_category == "clarification"

    def test_plan_default_is_perspective(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("음", _state(PolyaStage.PLAN))
        assert d.socratic_category == "perspective"

    def test_review_default_is_meta(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("음", _state(PolyaStage.REVIEW))
        assert d.socratic_category == "meta"

    def test_evidence_signal_overrides_on_stay(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("왜 그런지 모르겠어", _state(PolyaStage.PLAN))
        assert d.polya_stage_to_advance == "stay"
        assert d.socratic_category == "evidence"

    def test_assumption_signal_overrides_on_stay(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("양수라고 가정했어", _state(PolyaStage.PLAN))
        assert d.polya_stage_to_advance == "stay"
        assert d.socratic_category == "assumption"

    def test_next_uses_target_stage_default(self) -> None:
        # UNDERSTAND→PLAN 진입 시 PERSPECTIVE("관점 선택" 마디)
        coach = PolyaCoach()
        text = "함수 f의 최댓값을 구하는 문제고, 조건은 x≥0이야."
        d = coach.decide(text, _state(PolyaStage.UNDERSTAND))
        assert d.polya_stage_to_advance == "next"
        assert d.socratic_category == "perspective"


class TestMisconceptionHypothesisWiring:
    """decide()가 misconception_hypotheses를 select_category에 전달(가정 표면화)."""

    def test_high_conf_recent_hypothesis_yields_assumption_category(self) -> None:
        coach = PolyaCoach()
        h = [
            MisconceptionHypothesis(
                misconception_id="MC-1",
                confidence=0.8,
                turns_since_evidence=0,
                evidence_count=1,
            )
        ]
        d = coach.decide("음", _state(PolyaStage.PLAN), misconception_hypotheses=h)
        assert d.polya_stage_to_advance == "stay"
        # 단계 기본(perspective) 대신 가정 표면화(assumption)로 정밀화
        assert d.socratic_category == "assumption"

    def test_default_none_keeps_stage_default(self) -> None:
        # 가설 미전달 → 현 동작 불변(하위호환)
        coach = PolyaCoach()
        d = coach.decide("음", _state(PolyaStage.PLAN))
        assert d.socratic_category == "perspective"


class TestDecideAdvances:
    def test_understand_restatement_advances_to_plan_prompt(self) -> None:
        coach = PolyaCoach()
        text = "함수 f의 최댓값을 구하는 문제고, 조건은 x≥0이야."
        d = coach.decide(text, _state(PolyaStage.UNDERSTAND))
        assert d.polya_stage_to_advance == "next"
        # 다음 단계(PLAN) 프롬프트가 들어가야 함
        assert d.prompt == STAGE_PROMPTS[PolyaStage.PLAN].prompt
        assert "전략 후보 나열" in d.suggested_actions

    def test_plan_strategy_keyword_advances_to_execute_prompt(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("미분 공식 써볼게", _state(PolyaStage.PLAN))
        assert d.polya_stage_to_advance == "next"
        assert d.prompt == STAGE_PROMPTS[PolyaStage.EXECUTE].prompt

    def test_execute_full_solution_advances_to_review_prompt(self) -> None:
        coach = PolyaCoach()
        text = "f'(x) = 2x - 4\n2x - 4 = 0\n따라서 x = 2"
        d = coach.decide(text, _state(PolyaStage.EXECUTE))
        assert d.polya_stage_to_advance == "next"
        assert d.prompt == STAGE_PROMPTS[PolyaStage.REVIEW].prompt

    def test_review_is_terminal_stays_with_stage4_prompt(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("검산하니 맞고 다른 방법도 있어", _state(PolyaStage.REVIEW))
        assert d.polya_stage_to_advance == "stay"
        assert d.prompt == STAGE_PROMPTS[PolyaStage.REVIEW].prompt


class TestNextStage:
    """REVIEW가 종착임을 `next_polya_stage` 직접 호출로도 보장(미래 회귀 가드)."""

    def test_review_next_stage_is_review(self) -> None:
        assert next_polya_stage(PolyaStage.REVIEW) is PolyaStage.REVIEW

    def test_non_terminal_advances(self) -> None:
        assert next_polya_stage(PolyaStage.UNDERSTAND) is PolyaStage.PLAN
        assert next_polya_stage(PolyaStage.PLAN) is PolyaStage.EXECUTE
        assert next_polya_stage(PolyaStage.EXECUTE) is PolyaStage.REVIEW


class TestSystemPromptShape:
    def test_system_mentions_polya_and_safety(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("음", _state(PolyaStage.UNDERSTAND))
        # 5가지 원칙·금기 표현이 시스템 프롬프트에 명시되어 있어야(LLM에 주입)
        assert "Polya" in d.system
        assert "소크라테스" in d.system
        assert "틀렸" in d.system  # 금기 목록에 포함되어야 — 모델 자기검열 유도


class TestGradeRegisterWiring:
    """W0 — S-2: decide(grade=...)가 base_system 정체성 문구의 register를 바꾼다(학년축 최단경로
    계획 §2.3·§3). grade=None(기본·미전달)은 기존 문구와 바이트 동일 — 회귀 0."""

    def test_grade_none_matches_default_stage_prompt_byte_identical(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("음", _state(PolyaStage.UNDERSTAND))  # grade 미전달
        assert d.system == STAGE_PROMPTS[PolyaStage.UNDERSTAND].system

    def test_elementary_grade_uses_elementary_register(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("음", _state(PolyaStage.UNDERSTAND), grade=3)
        assert "초등학생" in d.system
        assert "중·고등학생" not in d.system

    def test_high_school_grade_uses_high_school_register(self) -> None:
        # 현재 UserProfile.grade 실호출 범위(10~14) 안 — "고등학생" register(구 결합 표현
        # "중·고등학생"보다 더 정확한 문구로 바뀜 — grade=None 폴백만 구 문구 보존).
        coach = PolyaCoach()
        d = coach.decide("음", _state(PolyaStage.UNDERSTAND), grade=11)
        assert "고등학생" in d.system
        assert d.system != STAGE_PROMPTS[PolyaStage.UNDERSTAND].system

    def test_university_grade_uses_university_register(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("음", _state(PolyaStage.UNDERSTAND), grade=14)
        assert "대학생" in d.system

    def test_out_of_range_grade_falls_back_to_default_register(self) -> None:
        coach = PolyaCoach()
        d = coach.decide("음", _state(PolyaStage.UNDERSTAND), grade=99)
        assert d.system == STAGE_PROMPTS[PolyaStage.UNDERSTAND].system

    def test_principles_and_stage_prompt_unaffected_by_register(self) -> None:
        """register만 바뀌고 5원칙 본문·톤·단계 발문은 학년 무관(4축 공용 — 구조 분기 아님)."""
        coach = PolyaCoach()
        d = coach.decide("음", _state(PolyaStage.UNDERSTAND), grade=3)
        assert "Polya" in d.system
        assert "소크라테스" in d.system
        assert "틀렸" in d.system
        assert d.prompt == STAGE_PROMPTS[PolyaStage.UNDERSTAND].prompt


class TestCoachWiring:
    @pytest.mark.asyncio
    async def test_coach_calls_llm_and_returns_clean_response(self) -> None:
        coach = PolyaCoach()
        llm = FakeLLM("좋은 시도네! 다음 단계로 가볼까?")
        decision, response, report = await coach.coach("음", _state(PolyaStage.UNDERSTAND), llm=llm)
        assert len(llm.calls) == 1
        called_prompt, called_system = llm.calls[0]
        assert called_prompt == decision.prompt
        assert called_system == decision.system
        assert response == "좋은 시도네! 다음 단계로 가볼까?"
        assert report.violations == []
        assert report.rewritten is False

    @pytest.mark.asyncio
    async def test_coach_scrubs_banned_tokens_in_llm_output(self) -> None:
        coach = PolyaCoach()
        # LLM이 금지 패턴을 뱉어도 마지막 방어선이 차단
        llm = FakeLLM("그건 틀렸어. 그런 실수는 흔해.")
        _, response, report = await coach.coach("음", _state(PolyaStage.UNDERSTAND), llm=llm)
        assert "틀렸" not in response
        assert "실수" not in response
        assert report.rewritten is True
        assert "틀렸" in report.violations
        assert "실수" in report.violations
