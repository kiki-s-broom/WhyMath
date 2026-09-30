"""WH-1 프로덕션 LLM 정책(`harness/wh1_llm_policy.py`) — 단위·통합(hermetic·순수).

FakeProvider(스크립트된 JSON 반환)로 두뇌의 계약을 검증한다 — 실 네트워크·직접 LLM 호출 0.
검증 축: ①정상 매핑 ②verify 의무 이중 방어 ③unverifiable 정답 억제 ④안전 폴백(깨진 JSON·미지
kind) ⑤학생 원문·정답의 프롬프트 미노출(요구사항 ⑥) ⑥run_tutoring_turn 통합 완주.

정직 스코프: L3 provider는 FakeProvider로 대체(라우터 결정은 실제 `Router().route()`가 내리되
로컬·순수라 네트워크 없음). 하네스 불변식의 *최종* 강제는 `test_wh1_loop.py`가 검증하며, 여기서는
정책의 *선제* 방어와 매핑만 본다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence

import pytest

from whymath_backend.harness.wh1_llm_policy import (
    _MAX_CONTEXT_NODES,
    _MAX_HISTORY,
    _MAX_PROMPT_TOKENS,
    LLMTutorPolicy,
)
from whymath_backend.harness.wh1_loop import (
    Action,
    EndTurnAction,
    MatchMisconceptionAction,
    ToolResult,
    TurnState,
    VerifyStepAction,
    run_tutoring_turn,
)
from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.models import PolyaStage
from whymath_backend.l4.session_recall import SessionRecall
from whymath_backend.schema.enums import SocraticStrategy

# diagnose가 confidence 1.0으로 잡는 실 신호(wh1_loop 테스트와 동일).
_MATCH_TEXT = "(a+b) a² + b²"
# 프롬프트에 절대 새면 안 되는 민감 표지(요구사항 ⑥ 검증용).
_SECRET_STUDENT_TEXT = "비밀학생풀이-SENTINEL-x=42"
_SECRET_ANSWER_STEP = "정답원문-SENTINEL-x=3"


class FakeProvider:
    """스크립트된 JSON 응답만 돌려주는 L3 provider 대역 — LLMProvider 충족(실 네트워크 0).

    `responses`를 순서대로 방출하고 소진되면 항상 end_turn(격려)을 반환해 루프를 종료시킨다.
    호출마다 (prompt, system)을 `calls`에 기록해 원문 미노출 검증에 쓴다.
    """

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.calls: list[tuple[str, str]] = []

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        self.calls.append((prompt, system))
        if self._index < len(self._responses):
            out = self._responses[self._index]
            self._index += 1
            return GenerationResult(out)
        return GenerationResult('{"kind": "end_turn", "action_type": "격려"}')


class RaisingProvider:
    """generate가 항상 예외를 던지는 provider 대역 — provider 장애 안전 강등 검증용."""

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        raise RuntimeError("provider 다운(테스트)")


def _state(
    *,
    has_solution_steps: bool = False,
    verify_called: bool = False,
    last_verdict: str | None = None,
) -> TurnState:
    return TurnState(
        turn_index=1,
        has_solution_steps=has_solution_steps,
        hypotheses=[],
        verify_called=verify_called,
        last_verdict=last_verdict,  # type: ignore[arg-type]
    )


def _next(policy: LLMTutorPolicy, state: TurnState) -> Action:
    return asyncio.run(policy.next_action(state))  # type: ignore[return-value]


class TestNormalMapping:
    def test_match_misconception_maps_and_injects_private_text(self) -> None:
        """LLM이 match_misconception을 고르면 정책이 *보유한* 학생 원문으로 인자를 채운다."""
        provider = FakeProvider(['{"kind": "match_misconception"}'])
        policy = LLMTutorPolicy(provider, student_text=_MATCH_TEXT)
        action = _next(policy, _state())
        assert isinstance(action, MatchMisconceptionAction)
        # 원문은 LLM 출력이 아니라 정책 보유값에서 온다.
        assert action.student_text == _MATCH_TEXT

    def test_curate_parses_scalar_field(self) -> None:
        """비민감 스칼라(turns_elapsed)는 LLM 출력에서 파싱된다."""
        provider = FakeProvider(['{"kind": "curate_hypothesis", "turns_elapsed": 3}'])
        policy = LLMTutorPolicy(provider)
        action = _next(policy, _state())
        from whymath_backend.harness.wh1_loop import CurateHypothesisAction

        assert isinstance(action, CurateHypothesisAction)
        assert action.turns_elapsed == 3

    def test_json_inside_prose_and_codefence(self) -> None:
        """코드펜스·주변 산문에 감싸인 JSON도 관대하게 추출한다."""
        provider = FakeProvider(
            ['설명...\n```json\n{"kind": "end_turn", "action_type": "격려"}\n```']
        )
        policy = LLMTutorPolicy(provider)
        action = _next(policy, _state())
        assert isinstance(action, EndTurnAction)
        assert action.action_type == "격려"


class TestVerifyObligationDefense:
    def test_end_turn_redirected_to_verify_when_obligation_pending(self) -> None:
        """풀이 제출·미검증인데 LLM이 end_turn을 내면 정책이 verify_step으로 재지정(이중 방어)."""
        provider = FakeProvider(['{"kind": "end_turn", "action_type": "격려"}'])
        policy = LLMTutorPolicy(provider, solution_steps=[_SECRET_ANSWER_STEP])
        action = _next(policy, _state(has_solution_steps=True, verify_called=False))
        assert isinstance(action, VerifyStepAction)
        # 단계는 정책 보유값으로 채워진다(LLM 미경유).
        assert action.steps == [_SECRET_ANSWER_STEP]

    def test_verify_step_selected_directly(self) -> None:
        """LLM이 직접 verify_step을 골라도 보유 단계로 채운다."""
        provider = FakeProvider(['{"kind": "verify_step"}'])
        policy = LLMTutorPolicy(provider, solution_steps=["x+1", "x=2"])
        action = _next(policy, _state(has_solution_steps=True, verify_called=False))
        assert isinstance(action, VerifyStepAction)
        assert action.steps == ["x+1", "x=2"]


class TestAnswerSuppression:
    """correct 아닌(incorrect·unverifiable) verdict의 정답 억제 — 정책 선제 방어."""

    def test_incorrect_strips_answer_and_downgrades_to_socratic(self) -> None:
        """오답도 명시 발화 제거 + 출제형 → 질문 강등(unverifiable와 동형)."""
        provider = FakeProvider(
            ['{"kind": "end_turn", "action_type": "출제", "utterance": "정답은 x=3이야."}']
        )
        policy = LLMTutorPolicy(provider)
        action = _next(
            policy,
            _state(has_solution_steps=True, verify_called=True, last_verdict="incorrect"),
        )
        assert isinstance(action, EndTurnAction)
        assert action.action_type == "질문"  # 정답 제시형(출제) → 소크라테스 질문으로 강등
        assert action.utterance is None  # LLM 정답 발화 제거

    def test_unverifiable_strips_answer_and_downgrades_to_socratic(self) -> None:
        """unverifiable 상태의 end_turn은 명시 발화 제거 + 정답 제시형(출제) → 질문 강등."""
        provider = FakeProvider(
            ['{"kind": "end_turn", "action_type": "출제", "utterance": "정답은 x=3이야."}']
        )
        policy = LLMTutorPolicy(provider)
        # 검증은 이미 호출됨(verify_called=True) → verify 의무 분기 아님, unverifiable 분기만.
        action = _next(
            policy,
            _state(has_solution_steps=True, verify_called=True, last_verdict="unverifiable"),
        )
        assert isinstance(action, EndTurnAction)
        assert action.action_type == "질문"  # 정답 제시형(출제) → 소크라테스 질문으로 강등
        assert action.utterance is None  # LLM 정답 발화 제거 → 하네스 개입 발화가 대신 말함

    def test_unverifiable_keeps_safe_socratic_type(self) -> None:
        """unverifiable라도 이미 안전한 힌트/질문/격려는 유형 보존(발화만 제거)."""
        provider = FakeProvider(
            ['{"kind": "end_turn", "action_type": "힌트", "utterance": "여기 정답 x=3"}']
        )
        policy = LLMTutorPolicy(provider)
        action = _next(
            policy,
            _state(has_solution_steps=True, verify_called=True, last_verdict="unverifiable"),
        )
        assert isinstance(action, EndTurnAction)
        assert action.action_type == "힌트"
        assert action.utterance is None


class TestSafeFallback:
    def test_broken_json_falls_back_to_encouragement(self) -> None:
        """깨진 JSON → 안전 폴백(격려 종료·크래시 없음)."""
        provider = FakeProvider(["이건 JSON이 아니라 그냥 문장입니다."])
        policy = LLMTutorPolicy(provider)
        action = _next(policy, _state())
        assert isinstance(action, EndTurnAction)
        assert action.action_type == "격려"

    def test_unknown_kind_falls_back(self) -> None:
        """미지 kind → 안전 폴백."""
        provider = FakeProvider(['{"kind": "teleport_student", "foo": 1}'])
        policy = LLMTutorPolicy(provider)
        action = _next(policy, _state())
        assert isinstance(action, EndTurnAction)

    def test_invalid_action_type_falls_back(self) -> None:
        """스키마 위반(잘못된 action_type Literal) → Pydantic 검증 실패 → 폴백."""
        provider = FakeProvider(['{"kind": "end_turn", "action_type": "설명"}'])
        policy = LLMTutorPolicy(provider)
        action = _next(policy, _state())
        assert isinstance(action, EndTurnAction)
        assert action.action_type == "격려"  # 폴백 기본

    def test_fallback_prefers_verify_when_obligation_pending(self) -> None:
        """폴백도 verify 의무를 존중 — 미검증 풀이 제출 턴이면 verify_step으로 강등."""
        provider = FakeProvider(["깨진 응답"])
        policy = LLMTutorPolicy(provider, solution_steps=["step1"])
        action = _next(policy, _state(has_solution_steps=True, verify_called=False))
        assert isinstance(action, VerifyStepAction)

    def test_provider_error_falls_back(self, caplog: pytest.LogCaptureFixture) -> None:
        """provider 예외(장애) → 안전 강등(학생 앞 크래시 금지) + 강등 사실이 타입명과 함께 로그에 남는다."""
        policy = LLMTutorPolicy(RaisingProvider())
        with caplog.at_level(logging.WARNING, logger="whymath.harness.wh1_llm_policy"):
            action = _next(policy, _state())
        assert isinstance(action, EndTurnAction)
        assert action.action_type == "격려"
        # 침묵 실패 금지(CLAUDE.md) — 타입명은 남기고 예외 메시지·트레이스백은 남기지 않는다
        # (예외 메시지는 학생 발화·답안을 담을 수 있다 — 미성년자 PII).
        warnings = [
            r
            for r in caplog.records
            if r.name == "whymath.harness.wh1_llm_policy" and r.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        assert "RuntimeError" in warnings[0].getMessage()
        assert "provider 다운" not in warnings[0].getMessage()
        assert warnings[0].exc_info is None


class TestNoRawLeak:
    """요구사항 ⑥ — 학생 원문·정답이 프롬프트/시스템에 절대 실리지 않는다(요약만)."""

    def test_student_text_and_answer_absent_from_prompt(self) -> None:
        provider = FakeProvider(['{"kind": "match_misconception"}'])
        policy = LLMTutorPolicy(
            provider,
            student_text=_SECRET_STUDENT_TEXT,
            solution_steps=[_SECRET_ANSWER_STEP],
        )
        _next(policy, _state(has_solution_steps=True, verify_called=True))
        assert provider.calls, "provider가 호출되어야 한다"
        prompt, system = provider.calls[0]
        combined = prompt + system
        assert _SECRET_STUDENT_TEXT not in combined
        assert _SECRET_ANSWER_STEP not in combined


class TestIntegration:
    """LLMTutorPolicy + FakeProvider로 run_tutoring_turn 한 턴 완주(ScriptedPolicy 테스트 미러)."""

    def test_full_turn_completes_ended(self) -> None:
        """match → curate → end_turn(격려) 스크립트로 한 턴 완주(ended)."""
        provider = FakeProvider(
            [
                '{"kind": "match_misconception"}',
                '{"kind": "curate_hypothesis", "turns_elapsed": 1}',
                '{"kind": "end_turn", "action_type": "격려", "utterance": "좋아, 잘했어."}',
            ]
        )
        policy = LLMTutorPolicy(provider, student_text=_MATCH_TEXT)
        outcome = asyncio.run(run_tutoring_turn(policy=policy, has_solution_steps=False))
        assert outcome.status == "ended"
        assert outcome.action_type == "격려"
        assert outcome.utterance == "좋아, 잘했어."

    def test_full_turn_respects_verify_obligation(self) -> None:
        """풀이 제출 턴: LLM이 곧장 end_turn을 내도 정책이 verify_step으로 유도 → 검증 후 종료."""
        provider = FakeProvider(
            [
                '{"kind": "end_turn", "action_type": "격려"}',  # 정책이 verify_step으로 재지정
                '{"kind": "end_turn", "action_type": "질문"}',  # 검증 후엔 종료 허용
            ]
        )
        policy = LLMTutorPolicy(provider, solution_steps=["x = 2", "x + 1 = 3"])
        outcome = asyncio.run(run_tutoring_turn(policy=policy, has_solution_steps=True))
        assert outcome.status == "ended"
        # verify_step이 트레이스에 존재(정책 선제 방어 → 하네스 실행).
        assert any(t.kind == "verify_step" and t.ok for t in outcome.trace)

    def test_budget_exhausts_without_crash(self) -> None:
        """정책이 계속 내부 도구만 내도(예: read) 예산 소진으로 안전 종료(크래시 없음)."""
        provider = FakeProvider(['{"kind": "read_student_state"}'] * 5)
        policy = LLMTutorPolicy(provider)
        outcome = asyncio.run(run_tutoring_turn(policy=policy, max_tool_calls=3))
        assert outcome.status == "budget_exhausted"
        assert outcome.tool_calls == 3


def _hyp(mid: str, confidence: float) -> MisconceptionHypothesis:
    """테스트용 가설 — 카탈로그 밖 id면 라벨은 id로 폴백(임의 id 허용)."""
    return MisconceptionHypothesis(
        misconception_id=mid,
        confidence=confidence,
        turns_since_evidence=0,
        evidence_count=1,
    )


def _prompt_summary(provider: FakeProvider) -> dict[str, object]:
    """provider가 받은 첫 프롬프트에서 JSON 요약 블록을 추출·파싱(예산 검증용)."""
    assert provider.calls, "provider가 호출되어야 한다"
    prompt = provider.calls[0][0]
    start = prompt.find("{")
    end = prompt.rfind("}")
    assert start != -1 and end > start
    obj = json.loads(prompt[start : end + 1])
    assert isinstance(obj, dict)
    return obj


class TestMinimalReasoningSubgraphBudget:
    """플레이북 Part 8 예산(depth≤2·max_nodes≤12~20·max_tokens≤3000)의 프롬프트 배선 검증.

    감사 Q2: "예산 상한 코드 부재 → S1-a 빌드 시 반드시 동반". `_build_prompt`가 유일 소비처.
    """

    def test_context_nodes_capped_keeps_top_confidence(self) -> None:
        """가설 수가 `_MAX_CONTEXT_NODES` 초과 시 상위 confidence만 남고 나머지 절단·정직 신호."""
        n = _MAX_CONTEXT_NODES + 5
        # confidence를 인덱스로 결정론적으로 부여(0.10, 0.11, ...): 상위 20개만 생존해야 함.
        hyps = [_hyp(f"mc-{i:02d}", 0.10 + i * 0.01) for i in range(n)]
        provider = FakeProvider(['{"kind": "end_turn", "action_type": "격려"}'])
        policy = LLMTutorPolicy(provider)
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=hyps)
        _next(policy, state)
        summary = _prompt_summary(provider)
        kept = summary["active_hypotheses"]
        assert isinstance(kept, list)
        assert len(kept) == _MAX_CONTEXT_NODES  # 20개만 실림
        # 생존자는 confidence 상위 20 — 잘린 5개는 최저 confidence(mc-00..mc-04).
        kept_ids = {h["id"] for h in kept}
        assert "mc-00" not in kept_ids and "mc-04" not in kept_ids
        assert "mc-24" in kept_ids  # 최고 confidence는 반드시 생존
        assert summary["context_truncated"] is True
        assert summary["omitted_count"] == 5

    def test_history_capped_to_recent(self) -> None:
        """history가 `_MAX_HISTORY` 초과 시 최근 것만 남는다(오래된 것 절단)."""
        history = [
            ToolResult(kind=f"tool-{i}", ok=True, detail="x") for i in range(_MAX_HISTORY + 12)
        ]
        provider = FakeProvider(['{"kind": "end_turn", "action_type": "격려"}'])
        # 인스턴스 max_history를 크게 줘도 Part 8 천장(_MAX_HISTORY)으로 클램프됨을 검증.
        policy = LLMTutorPolicy(provider, max_history=100)
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=[], history=history)
        _next(policy, state)
        summary = _prompt_summary(provider)
        recent = summary["recent_tools"]
        assert isinstance(recent, list)
        assert len(recent) == _MAX_HISTORY  # 8개로 절단
        # 최근 것만: 마지막 도구가 포함되고 오래된 tool-0는 빠짐.
        assert recent[-1]["kind"] == f"tool-{_MAX_HISTORY + 11}"
        assert all(r["kind"] != "tool-0" for r in recent)
        assert summary["context_truncated"] is True

    def test_token_budget_forces_additional_truncation(self) -> None:
        """토큰 근사가 `_MAX_PROMPT_TOKENS` 초과면 추가 절단 → 프롬프트가 근사 상한 이하로 축소."""
        # 카탈로그 밖의 초장문 id → name이 id로 폴백해 프롬프트가 토큰 예산을 크게 초과.
        huge = "x" * 6000
        hyps = [_hyp(f"{huge}-{i}", 0.10 + i * 0.01) for i in range(3)]
        provider = FakeProvider(['{"kind": "end_turn", "action_type": "격려"}'])
        policy = LLMTutorPolicy(provider)
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=hyps)
        _next(policy, state)
        prompt = provider.calls[0][0]
        # 토큰 근사(문자수/4)가 상한 이하로 줄었다.
        assert len(prompt) // 4 <= _MAX_PROMPT_TOKENS
        summary = _prompt_summary(provider)
        # 입력 3개보다 적게 남고, 절단 신호가 켜져야 한다(노드 cap은 미발동·토큰 cap만).
        assert len(summary["active_hypotheses"]) < 3
        assert summary["context_truncated"] is True

    def test_truncation_is_deterministic(self) -> None:
        """같은 입력 2회 → 동일 프롬프트(random·시각 미사용)."""
        hyps = [_hyp(f"mc-{i:02d}", 0.10 + i * 0.01) for i in range(_MAX_CONTEXT_NODES + 5)]
        prompts: list[str] = []
        for _ in range(2):
            provider = FakeProvider(['{"kind": "end_turn", "action_type": "격려"}'])
            policy = LLMTutorPolicy(provider)
            state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=list(hyps))
            _next(policy, state)
            prompts.append(provider.calls[0][0])
        assert prompts[0] == prompts[1]

    def test_within_budget_has_no_truncation_signal(self) -> None:
        """예산 내(소수 가설·짧은 history)면 절단 신호가 없다(정상 케이스)."""
        hyps = [_hyp("mc-01", 0.5), _hyp("mc-02", 0.4)]
        history = [ToolResult(kind="read_student_state", ok=True, detail="x")]
        provider = FakeProvider(['{"kind": "end_turn", "action_type": "격려"}'])
        policy = LLMTutorPolicy(provider)
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=hyps, history=history)
        _next(policy, state)
        summary = _prompt_summary(provider)
        assert "context_truncated" not in summary
        assert "omitted_count" not in summary
        assert len(summary["active_hypotheses"]) == 2


class TestSessionRecallInjection:
    """PED-04 D1 reader ② — 세션 간 회상을 정책이 프롬프트에 어떻게 주입하는지.

    구조적 전제: `SessionRecall`의 필드가 전부 enum/정수라 학생 원문을 실을 자리가 없다
    (`test_session_recall.py`가 그 전제를 동결). 여기서는 *주입 지점*(정책·예산 가드)만 본다.
    """

    def test_recall_none_prompt_is_byte_identical_to_baseline(self) -> None:
        """recall 미주입(기존 호출)이면 프롬프트가 recall 인자를 아예 모르는 것과 동일해야 한다
        (회귀 0 — 이 테스트는 recall 키가 요약에 없음을 확인한다)."""
        provider = FakeProvider(['{"kind": "end_turn", "action_type": "격려"}'])
        policy = LLMTutorPolicy(provider)  # session_recall 미지정 → None 기본값.
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=[])
        _next(policy, state)
        summary = _prompt_summary(provider)
        assert "session_recall" not in summary

    def test_recall_present_injects_three_axes_only(self) -> None:
        """recall 주입 시 요약에 session_recall 키가 생기고 **3축만** 실린다 —
        unresolved_hypothesis_ids는 모델에 있어도 프롬프트에는 나가지 않는다(오개념 preload
        금지)."""
        recall = SessionRecall(
            last_polya_stage=PolyaStage.PLAN,
            last_socratic_strategies=(SocraticStrategy.조건확인, SocraticStrategy.단계분해),
            unresolved_hypothesis_ids=("M001", "M002"),
            turns_since=5,
        )
        provider = FakeProvider(['{"kind": "end_turn", "action_type": "격려"}'])
        policy = LLMTutorPolicy(provider, session_recall=recall)
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=[])
        _next(policy, state)
        summary = _prompt_summary(provider)
        assert "session_recall" in summary
        sr = summary["session_recall"]
        assert isinstance(sr, dict)
        assert set(sr) == {"last_polya_stage", "last_strategies", "turns_since"}
        assert sr["last_polya_stage"] == "plan"
        assert sr["last_strategies"] == ["조건확인", "단계분해"]
        assert sr["turns_since"] == 5
        # 활성 가설 id는 프롬프트 어디에도 리터럴로 없어야 한다(warmstart 전용 필드).
        prompt, _system = provider.calls[0]
        assert "M001" not in prompt
        assert "M002" not in prompt

    def test_recall_is_truncated_before_history_or_hypotheses(self) -> None:
        """예산 초과 시 recall이 **1순위**로 잘린다 — history·가설이 아직 여유 있는 상태에서도
        recall부터 사라져야 한다(세션 간 맥락이 이번 턴 결정에 가장 덜 급하다는 설계 우선순위)."""
        # recall 자체는 고정 3키라 팽창 없음 — 다른 축(초장문 가설)으로 예산을 초과시켜 recall이
        # 가장 먼저 절단되는지 본다.
        huge = "y" * 6000
        hyps = [_hyp(f"{huge}-{i}", 0.9 - i * 0.01) for i in range(2)]
        recall = SessionRecall(
            last_polya_stage=PolyaStage.REVIEW,
            last_socratic_strategies=(SocraticStrategy.유사문제,),
            unresolved_hypothesis_ids=(),
            turns_since=1,
        )
        provider = FakeProvider(['{"kind": "end_turn", "action_type": "격려"}'])
        policy = LLMTutorPolicy(provider, session_recall=recall)
        state = TurnState(turn_index=1, has_solution_steps=False, hypotheses=hyps)
        _next(policy, state)
        prompt = provider.calls[0][0]
        assert len(prompt) // 4 <= _MAX_PROMPT_TOKENS
        summary = _prompt_summary(provider)
        assert "session_recall" not in summary  # 예산 압박에 recall이 먼저 사라짐.
        assert summary["context_truncated"] is True

    def test_recall_absent_from_prompt_does_not_break_no_raw_leak(self) -> None:
        """recall 필드 자체가 enum/정수뿐이라, 회상이 실려도 학생 원문 비노출 계약은 유지된다."""
        recall = SessionRecall(
            last_polya_stage=PolyaStage.UNDERSTAND,
            last_socratic_strategies=(),
            unresolved_hypothesis_ids=(),
            turns_since=0,
        )
        provider = FakeProvider(['{"kind": "match_misconception"}'])
        policy = LLMTutorPolicy(
            provider,
            student_text=_SECRET_STUDENT_TEXT,
            solution_steps=[_SECRET_ANSWER_STEP],
            session_recall=recall,
        )
        _next(policy, _state(has_solution_steps=True, verify_called=True))
        prompt, system = provider.calls[0]
        combined = prompt + system
        assert _SECRET_STUDENT_TEXT not in combined
        assert _SECRET_ANSWER_STEP not in combined
