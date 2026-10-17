"""OPS-134 ② ③ — WH-1 primary 폴백 회계: 모든 종료 경로가 결말을 남기고, 수확기가 채택률을 말한다.

배경(2026-10-12 Phaiakes9 실측): 15요청 중 14턴이 시간 초과로 결정론 폴백했는데 primary 기록 파일은
1줄이었다. 타임아웃·예외 경로가 `emit` 전에 `return None`이라 **폴백은 기록이 0줄**이었고, "primary가
작동한 비율"을 어디서도 읽을 수 없었다. 더 숨은 경로도 있었다 — provider 실패를 정책이 안전 강등으로
흡수해 정상 `ended` 턴으로 돌려주므로 LLM이 죽어도 채택으로 세어질 수 있었다.

핵심 단언:
- **모든 종료 경로가 레코드를 남긴다** — 타임아웃·예외·예산 소진·발화 없음·프로즈 게이트·금지모드
  가드·LLM 강등·채택, 각각 서로 다른 결말 라벨(닫힌 어휘).
- **0 위장 금지** — 중단 턴의 도구 호출 수는 0이 아니라 None, 시도 0건의 채택률은 0%가 아니라 None.
- **기존 분포 불변** — 중단 턴을 섞어도 verdict·전이·형태·status 분포는 변경 전과 같은 값이다.
- **구판 레코드 하위호환** — 새 필드가 없는 레코드도 파싱되고, 결말 미기록 primary는 분모에서 빠진다.
- **프라이버시** — 예외 메시지(학생 발화를 담을 수 있음)는 레코드에 들어오지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import pytest

from whymath_backend.config import get_settings
from whymath_backend.harness import wh1_primary
from whymath_backend.harness.wh1_loop import TurnOutcome
from whymath_backend.harness.wh1_primary import run_wh1_primary_turn
from whymath_backend.harness.wh1_shadow import Wh1HarnessShadowObservation, record_logger
from whymath_backend.harness.wh1_shadow_harvest import (
    PRIMARY_OUTCOME_LABELS,
    harvest_files,
    parse_log_text,
    render_report,
    summarize,
)
from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l4.pedagogy.pack_registry import get_pack, reset_pack_cache
from whymath_backend.schema.enums import KnowledgeType

_RECORD_LOGGER = record_logger.name
_PRIMARY_LOGGER = "whymath.harness.wh1_primary"
# 예외 메시지에 실려 레코드로 새면 안 되는 sentinel(미성년 PII — 예외 메시지는 학생 발화를 담을 수 있다).
_PII = "ZZPIIZZ"
_END_TURN_QUESTION = '{"kind": "end_turn", "action_type": "질문", "utterance": "방금 왜 그렇게 전개했는지 말해줄래?"}'


class _FakeProvider:
    """스크립트된 JSON만 돌려주는 L3 provider 대역 — 소진 시 end_turn(격려)로 종료."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self._index = 0

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        if self._index < len(self._responses):
            out = self._responses[self._index]
            self._index += 1
            return GenerationResult(out)
        return GenerationResult('{"kind": "end_turn", "action_type": "격려"}')


class _SlowProvider:
    """타임아웃 대역 — 호출이 끝나기 전에 턴 예산이 먼저 소진된다."""

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        await asyncio.sleep(1.0)
        return GenerationResult(_END_TURN_QUESTION)


class _BoomProvider:
    """provider 장애 대역 — 정책이 흡수해 정상 `ended` 턴으로 돌려주는 경로(LLM 강등)."""

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        raise ConnectionError("LLM 도달 불가(테스트)")


class _FailThenScriptProvider:
    """첫 호출만 실패하고 이후는 스크립트를 따른다 — 강등 표지가 '마지막 행동' 기준임을 보인다."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._inner = _FakeProvider(responses)
        self._failed = False

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        if not self._failed:
            self._failed = True
            raise ConnectionError("첫 호출만 실패(테스트)")
        return await self._inner.generate(prompt, system, decision, images=images)


def _records(caplog: pytest.LogCaptureFixture) -> list[Wh1HarnessShadowObservation]:
    return [
        Wh1HarnessShadowObservation.model_validate_json(r.getMessage())
        for r in caplog.records
        if r.name == _RECORD_LOGGER
    ]


def _run(**kwargs: object) -> str | None:
    kwargs.setdefault("student_solution", f"내 풀이 {_PII}")
    kwargs.setdefault("solution_steps", [])
    kwargs.setdefault("active_hypotheses", [])
    kwargs.setdefault("timeout_seconds", 5.0)
    kwargs.setdefault("dialogue_id", "d-acct")
    kwargs.setdefault("problem_id", "p-acct")
    return asyncio.run(run_wh1_primary_turn(**kwargs))  # type: ignore[arg-type]


def _one_record(caplog: pytest.LogCaptureFixture) -> Wh1HarnessShadowObservation:
    records = _records(caplog)
    assert len(records) == 1, f"턴당 레코드는 정확히 1건이어야 한다: {len(records)}건"
    assert records[0].primary is True
    return records[0]


# ──────────────────────────────────────────────────────────────────────────
# ② 모든 종료 경로가 결말을 남긴다
# ──────────────────────────────────────────────────────────────────────────
class TestEveryExitPathLeavesARecord:
    def test_timeout_leaves_aborted_record(self, caplog: pytest.LogCaptureFixture) -> None:
        # 이 경로가 라이브 실측에서 기록 0줄이던 바로 그 경로다.
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            served = _run(provider=_SlowProvider(), timeout_seconds=0.05)
        assert served is None
        obs = _one_record(caplog)
        assert obs.status == "aborted"
        assert obs.primary_outcome == "fallback_timeout"
        # 0 위장 금지 — 하네스 결과가 없는 턴의 도구 호출 수는 "0회"가 아니라 "모름"이다.
        assert obs.tool_calls is None
        assert obs.action_type is None
        assert obs.verify_verdict is None
        # 호출은 시작됐으나 취소로 끝나지 못했다 — 비행 중 1건이 회계에 보인다.
        assert obs.llm_calls == 1
        assert obs.llm_calls_finished == 0
        assert obs.llm_ms_total == 0
        assert obs.elapsed_ms is not None
        assert obs.elapsed_ms >= 40  # 예산 50ms — 타이머 오차만 허용
        assert obs.dialogue_id == "d-acct"
        assert obs.problem_id == "p-acct"

    def test_exception_leaves_record_without_exception_message(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def _boom(**_kwargs: object) -> None:
            raise RuntimeError(f"학생 원문이 섞인 메시지 {_PII}")

        monkeypatch.setattr(wh1_primary, "run_tutoring_turn", _boom)
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            served = _run(provider=_FakeProvider([]))
        assert served is None
        obs = _one_record(caplog)
        assert obs.primary_outcome == "fallback_exception"  # TimeoutError와 다른 라벨이다
        assert obs.status == "aborted"
        # 정책은 만들어졌지만 루프가 한 번도 돌지 않았다 — LLM 호출 0건을 0으로 정직하게 센다.
        assert obs.llm_calls == 0
        assert obs.llm_calls_finished == 0
        # 프라이버시: 예외 메시지(학생 발화를 담을 수 있음)는 레코드 어디에도 없다.
        raw = next(r.getMessage() for r in caplog.records if r.name == _RECORD_LOGGER)
        assert _PII not in raw
        assert "RuntimeError" not in raw  # 타입명은 평문 WARNING 로그가 이미 남긴다

    def test_budget_exhausted_is_labeled_and_counts_calls(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = _FakeProvider(['{"kind": "read_student_state"}'] * 10)
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            served = _run(provider=provider, max_tool_calls=3)
        assert served is None
        obs = _one_record(caplog)
        assert obs.primary_outcome == "fallback_budget_exhausted"
        assert obs.status == "budget_exhausted"
        assert obs.llm_calls == 3
        assert obs.llm_calls_finished == 3

    def test_ended_without_utterance_is_labeled(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def _empty(**_kwargs: object) -> TurnOutcome:
            return TurnOutcome(
                status="ended",
                action_type="격려",
                utterance=None,
                hypotheses=[],
                evidence=[],
                tool_calls=0,
                trace=[],
            )

        monkeypatch.setattr(wh1_primary, "run_tutoring_turn", _empty)
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            served = _run(provider=_FakeProvider([]))
        assert served is None
        assert _one_record(caplog).primary_outcome == "fallback_no_utterance"

    def test_adopted_turn_is_labeled_and_timed(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            served = _run(provider=_FakeProvider([_END_TURN_QUESTION]))
        assert served == "방금 왜 그렇게 전개했는지 말해줄래?"
        obs = _one_record(caplog)
        assert obs.primary_outcome == "adopted"
        assert obs.status == "ended"
        assert obs.llm_calls == 1
        assert obs.llm_calls_finished == 1
        assert obs.elapsed_ms is not None and obs.elapsed_ms >= 0
        assert obs.llm_ms_total is not None and obs.llm_ms_total >= 0
        assert obs.tool_calls is not None  # 완주한 턴은 도구 호출 수가 실측값이다


class TestLlmDegradeIsNotAdoption:
    """정책이 provider 실패를 흡수해 정상 `ended`로 돌려줘도 그것은 채택이 아니다."""

    def test_provider_failure_is_degraded_not_adopted(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            served = _run(provider=_BoomProvider())
        # 학생에게는 결정론 안전 발화가 서빙된다(앱은 죽지 않는다) — 그러나 LLM 발화가 아니다.
        assert served is not None
        obs = _one_record(caplog)
        assert obs.status == "ended"  # 하네스는 정상 종료했다 — 그래서 위장이 가능했다
        assert obs.primary_outcome == "fallback_llm_degraded"
        assert obs.llm_calls == 1
        assert obs.llm_calls_finished == 1  # 예외로 끝난 호출도 '끝난' 호출이다

    def test_unparseable_output_is_degraded(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            _run(provider=_FakeProvider(["JSON이 아닌 산문 응답"]))
        assert _one_record(caplog).primary_outcome == "fallback_llm_degraded"

    def test_first_call_failure_recovered_by_second_call_is_adopted(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 풀이 단계가 있어 강등 행동이 verify_step이 되고 루프가 이어진다. 둘째 호출은 정상 LLM 선택이다.
        provider = _FailThenScriptProvider([_END_TURN_QUESTION])
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            _run(provider=provider, solution_steps=["x + 1 = 3", "x = 2"])
        obs = _one_record(caplog)
        assert obs.llm_calls == 2  # 첫 호출 실패 + 둘째 정상 — 강등 이력이 있어도
        assert obs.primary_outcome == "adopted"  # 턴을 끝낸 행동이 LLM 선택이면 채택이다


class TestGateFallbacksAreLabeled:
    def test_prose_gate_rejection_is_labeled(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("WHYMATH_WH1_PROSE_REPHRASE_ENABLED", "true")
        get_settings.cache_clear()
        provider = _FakeProvider(
            ['{"kind": "end_turn", "action_type": "질문", "utterance": "그러니까 x=9가 되는 거야"}']
        )
        try:
            with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
                served = _run(provider=provider)
        finally:
            get_settings.cache_clear()
        assert served is None  # 외래 등식(날조 정답) — 결정론 폴백 신호
        assert _one_record(caplog).primary_outcome == "fallback_prose_gate"

    def test_mode_guard_replacement_is_labeled(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("WHYMATH_MODE_GUARD_RUNTIME_ENABLED", "true")
        get_settings.cache_clear()
        reset_pack_cache()
        pack = get_pack(KnowledgeType.CONCEPT.value)
        assert pack is not None and "WORKED_EXAMPLE_FIRST" in pack.forbidden_modes
        violating = "이 개념의 정의는 주변보다 큰 값이라는 것이다. 그대로 외우면 된다."  # 가드 테스트와 동일
        provider = _FakeProvider(
            ['{"kind": "end_turn", "action_type": "질문", "utterance": "' + violating + '"}']
        )
        try:
            with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
                served = _run(provider=provider, pack=pack)
        finally:
            get_settings.cache_clear()
        assert served != violating  # 위반 발화는 서빙되지 않았다 — 학생이 받은 것은 결정론 재질문
        assert _one_record(caplog).primary_outcome == "fallback_mode_guard"


class TestEmitFailureNeverBreaksServing:
    def test_aborted_emit_failure_still_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def _explode(**_kwargs: object) -> None:
            raise ValueError("기록 계층 장애(테스트)")

        monkeypatch.setattr(wh1_primary, "emit_wh1_aborted_observation", _explode)
        with caplog.at_level(logging.WARNING, logger=_PRIMARY_LOGGER):
            served = _run(provider=_SlowProvider(), timeout_seconds=0.05)
        assert served is None  # 관측 실패가 결정론 폴백을 막지 않는다
        messages = " ".join(r.getMessage() for r in caplog.records if r.name == _PRIMARY_LOGGER)
        assert "ValueError" in messages  # 침묵 실패 금지 — 타입명 로그


# ──────────────────────────────────────────────────────────────────────────
# 수확기 — 채택률은 작동한 비율을 말하고, 기존 분포는 변하지 않는다
# ──────────────────────────────────────────────────────────────────────────
def _obs(
    outcome: str | None,
    *,
    primary: bool = True,
    status: str = "ended",
    verdict: str | None = "correct",
    counts: tuple[int, int, int] | None = (1, 0, 0),
    llm_calls: int | None = None,
    llm_finished: int | None = None,
    llm_ms: int | None = None,
    elapsed: int | None = None,
    turn: int = 1,
    when: str = "2026-10-14T09:00:00+00:00",
) -> Wh1HarnessShadowObservation:
    """관측 픽스처 — 방출 측 실물 모델로 구성한다(스키마 드리프트 시 여기서 즉시 깨진다)."""
    aborted = status == "aborted"
    return Wh1HarnessShadowObservation(
        status=status,
        action_type=None if aborted else "질문",
        verify_verdict=None if aborted else verdict,
        n_correct=None if aborted or counts is None else counts[0],
        n_incorrect=None if aborted or counts is None else counts[1],
        n_unverifiable=None if aborted or counts is None else counts[2],
        tool_calls=None if aborted else 3,
        hypothesis_count=0,
        dialogue_id="d-1",
        turn_index=turn,
        primary=primary,
        primary_outcome=outcome,  # type: ignore[arg-type]
        llm_calls=llm_calls,
        llm_calls_finished=llm_finished,
        llm_ms_total=llm_ms,
        elapsed_ms=elapsed,
        observed_at=datetime.fromisoformat(when),
    )


def _timeout(**kw: object) -> Wh1HarnessShadowObservation:
    return _obs("fallback_timeout", status="aborted", **kw)  # type: ignore[arg-type]


class TestAdoptionRate:
    def test_rate_counts_every_label_against_all_attempts(self) -> None:
        observations = [
            _obs("adopted"),
            _obs("adopted"),
            _obs("adopted"),
            _timeout(),
            _obs("fallback_llm_degraded"),
        ]
        s = summarize(observations)
        assert s.primary_attempts == 5
        assert s.primary_adopted == 3
        assert s.primary_adoption_rate == pytest.approx(0.6)
        # 전 라벨이 0건이어도 축에 있다 — "한 번도 안 났다"와 "집계가 없다"가 구분된다.
        assert set(s.primary_outcome_counts) == set(PRIMARY_OUTCOME_LABELS)
        assert s.primary_outcome_counts["fallback_timeout"] == 1
        assert s.primary_outcome_counts["fallback_llm_degraded"] == 1
        assert s.primary_outcome_counts["fallback_prose_gate"] == 0

    def test_rate_discriminates_both_directions(self) -> None:
        # 성공/실패 양쪽에서 같은 값을 내는 검사는 위장이다 — 양 끝에서 서로 다른 값을 낸다.
        all_ok = summarize([_obs("adopted")] * 4)
        all_timeout = summarize([_timeout()] * 4)
        assert all_ok.primary_adoption_rate == 1.0
        assert all_timeout.primary_adoption_rate == 0.0  # 0%는 "분모 있고 전부 폴백"이다
        assert all_timeout.primary_adoption_rate is not None

    def test_zero_attempts_is_none_not_zero_percent(self) -> None:
        s = summarize([_obs(None, primary=False)])  # shadow 레코드뿐 — 서빙된 턴이 없다
        assert s.primary_attempts == 0
        assert s.primary_adoption_rate is None
        assert s.primary_outcome_counts == {}
        assert s.primary_legacy_records == 0  # shadow는 구판 primary가 아니다

    def test_legacy_primary_excluded_from_denominator_and_counted(self) -> None:
        legacy = _obs(None, primary=True)  # 결말 계측 이전 primary — 폴백 기록이 0줄이던 시절
        s = summarize([legacy, legacy, _obs("adopted"), _timeout()])
        assert s.primary_legacy_records == 2
        assert s.primary_attempts == 2  # 구판 2건은 분모에 없다
        assert s.primary_adoption_rate == pytest.approx(0.5)  # 구판을 채택으로 세면 0.75

    def test_shadow_records_never_enter_adoption_axis(self) -> None:
        s = summarize([_obs("adopted", primary=False), _obs("adopted")])
        assert s.primary_attempts == 1

    def test_aborted_turns_do_not_touch_existing_distributions(self) -> None:
        completed = [
            _obs("adopted", verdict="correct", turn=1),
            _obs("adopted", verdict="incorrect", counts=(0, 1, 0), turn=2),
            _obs("adopted", verdict=None, counts=(0, 0, 0), turn=2),
        ]
        before = summarize(completed)
        after = summarize(
            [*completed, _timeout(), _timeout(), _obs("fallback_exception", status="aborted")]
        )
        # 기존 분포는 정상 완료 턴의 것이다 — 중단 턴 3건을 섞어도 한 칸도 변하지 않는다.
        for name in (
            "total",
            "verdict_counts",
            "verdict_ratios",
            "status_counts",
            "turn_verdicts",
            "transition_counts",
            "transition_records",
            "legacy_records",
            "form_records",
            "form_legacy_records",
            "verify_target_total",
            "verify_target_ratios",
        ):
            assert getattr(after, name) == getattr(before, name), name
        assert after.aborted_total == 3
        assert before.aborted_total == 0
        assert after.primary_attempts == 6

    def test_aborted_turns_still_extend_window_and_dialogues(self) -> None:
        late = _timeout(when="2026-10-14T23:00:00+00:00")
        s = summarize([_obs("adopted", when="2026-10-14T09:00:00+00:00"), late])
        assert s.observed_at_max == late.observed_at  # 중단 턴도 관측 창에 든다


class TestDiscardedCallAccounting:
    def test_fallback_turns_share_of_llm_calls(self) -> None:
        s = summarize(
            [
                _obs("adopted", llm_calls=2, llm_finished=2),
                _obs("adopted", llm_calls=2, llm_finished=2),
                _timeout(llm_calls=3, llm_finished=2),
                _obs("fallback_llm_degraded", llm_calls=3, llm_finished=3),
            ]
        )
        assert s.llm_calls_in_adopted == 4
        assert s.llm_calls_in_fallback == 6
        assert s.fallback_llm_call_share == pytest.approx(0.6)
        assert s.llm_calls_accounted == 4

    def test_unrecorded_calls_are_not_counted_as_zero(self) -> None:
        s = summarize([_obs("adopted"), _timeout(llm_calls=3, llm_finished=3)])
        assert s.llm_calls_accounted == 1  # 호출 수 미기록 시도는 표본에서 빠진다
        assert s.llm_calls_in_adopted == 0
        assert s.llm_calls_in_fallback == 3

    def test_no_calls_recorded_gives_none_share(self) -> None:
        s = summarize([_obs("adopted"), _timeout()])
        assert s.fallback_llm_call_share is None  # 분모 0 — 0%로 위장하지 않는다

    def test_timeout_budget_split(self) -> None:
        s = summarize(
            [
                _timeout(elapsed=15000, llm_ms=4000, llm_calls=3, llm_finished=2),
                _timeout(elapsed=15000, llm_ms=6000, llm_calls=2, llm_finished=1),
                _timeout(),  # 소요 미기록 — 분해 합계에서 빠진다
            ]
        )
        assert s.timeout_turns == 3
        assert s.timeout_elapsed_ms_total == 30000
        assert s.timeout_llm_ms_total == 10000
        assert s.timeout_inflight_calls == 2  # 비행 중 호출 (3-2)+(2-1), 미기록 턴은 0
        assert s.elapsed_ms_fallback is not None and s.elapsed_ms_fallback.n == 2
        assert s.elapsed_ms_adopted is None  # 채택 턴 소요 기록 없음 — 0ms로 위장하지 않는다


class TestBackwardCompatibleParsing:
    def test_pre_ops134_record_parses_with_null_new_fields(self) -> None:
        old = {
            "status": "ended",
            "action_type": "질문",
            "verify_verdict": "correct",
            "tool_calls": 3,
            "hypothesis_count": 1,
            "primary": True,
            "observed_at": "2026-10-12T09:00:00+00:00",
        }
        obs = Wh1HarnessShadowObservation.model_validate_json(json.dumps(old))
        assert obs.primary_outcome is None
        assert obs.elapsed_ms is None
        assert obs.llm_calls is None

    def test_aborted_record_round_trips_through_server_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            _run(provider=_SlowProvider(), timeout_seconds=0.05)
        emitted = next(r for r in caplog.records if r.name == _RECORD_LOGGER)
        line = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s").format(emitted)
        parsed, acct = parse_log_text(line)
        assert acct.parsed == 1 and acct.broken == 0
        assert parsed[0].primary_outcome == "fallback_timeout"

    def test_unknown_outcome_label_is_rejected_loudly(self) -> None:
        # 닫힌 어휘 — 오타가 새 사유로 조용히 집계되지 않는다.
        with pytest.raises(ValueError):
            _obs("fallback_timeoutt")


class TestReportSaysTheRate:
    def test_report_states_rate_and_warns_on_legacy_and_discarded_calls(self) -> None:
        s = summarize(
            [
                _obs(None, primary=True),  # 구판 primary
                _obs("adopted", llm_calls=1, llm_finished=1, elapsed=900, llm_ms=800),
                _timeout(elapsed=15000, llm_ms=3000, llm_calls=3, llm_finished=2),
            ]
        )
        report = _wrap(s)
        text = render_report(report)
        assert "primary 채택률" in text
        assert "채택 1건 (50.0%)" in text
        assert "fallback_timeout" in text
        assert "serving 표지로" in text  # 폐기된 호출이 표본에 든다는 경고
        assert "구판 primary 레코드 1건은 분모에서 제외" in text
        assert "하네스 중단 턴 1건" in text

    def test_report_with_no_attempts_refuses_to_say_zero_percent(self) -> None:
        text = render_report(_wrap(summarize([_obs(None, primary=False)])))
        assert "채택률 산출 불가" in text
        assert "0.0%" not in text.split("[primary 채택률")[1].split("[verify")[0]

    def test_end_to_end_through_harvest_files(self, tmp_path: Path) -> None:
        # 수확기는 (dialogue_id, turn_index, observed_at)로 중복을 거른다 — 시각을 달리해 3건을 유지한다.
        records = [
            _obs("adopted", when="2026-10-14T09:00:00+00:00"),
            _timeout(when="2026-10-14T09:01:00+00:00"),
            _timeout(when="2026-10-14T09:02:00+00:00"),
        ]
        log = tmp_path / "server.log"
        log.write_text(
            "\n".join(f"{_RECORD_LOGGER} {r.model_dump_json()}" for r in records), encoding="utf-8"
        )
        report = harvest_files([log])
        assert report.summary.primary_attempts == 3
        assert report.summary.primary_adoption_rate == pytest.approx(1 / 3)
        assert report.summary.aborted_total == 2


def _wrap(summary: object) -> object:
    """리포트 래퍼 — 파일 I/O 없이 렌더만 보기 위한 최소 조립."""
    from whymath_backend.harness.wh1_shadow_harvest import ParseAccounting, Wh1ShadowHarvestReport

    return Wh1ShadowHarvestReport(
        sources=["<memory>"],
        accounting=ParseAccounting(lines_total=0, parsed=0, skipped=0, broken=0),
        input_duplicates=0,
        store_path=None,
        ledger_existing=0,
        ledger_broken=0,
        appended=0,
        filter_since=None,
        filter_until=None,
        filtered_out=0,
        summary=summary,  # type: ignore[arg-type]
    )
