"""WH-1 학생 대면 LLM의 **파이프라인 결선** 동결 — 관측·캐시가 실적재되는가 (OPS-36).

왜 이 파일이 따로 있는가
------------------------
`test_wh1_primary.py`·`test_wh1_prose.py`는 *발화가 나오는가*를 본다. 그런데 2026-07-20 GA
이후 학생 대면 LLM 트래픽은 발화를 멀쩡히 내면서도 Langfuse `l3_routing` 이벤트를 **한 건도**
내지 않았다 — 정책·프로즈가 `Router().route()`로 결정만 받고 `provider.generate(...)`를 직접
불러 `l3.pipeline`을 우회했기 때문이다. 발화가 정상이면 화면은 정상이므로 이 결손은 무증상이고,
그래서 비용 게이트②의 표본에서 학생 대면 트래픽 전량이 구조적으로 빠져 있었다(langfuse v2가
8일간 무증상 전멸한 2026-07-16과 같은 형태).

그러므로 이 파일은 **결선 자체**를 계약으로 동결한다. 아래 검사들은 결선을 끊으면(좌석을
직접 호출로 되돌리면·`cache`/`trace` thread를 끊으면) RED가 된다 — CLAUDE.md "검증 장치를
만들고 배선 확인 없이 완료 선언 금지"의 양방향 변별 요구다. 뮤테이션 실측은 PR 본문에 있다.

**대조군을 함께 둔다**(성공/실패 양쪽에서 같은 값을 내는 검사는 위장이다): 기록이 *나온다*만
보지 않고, 기록의 내용이 라우팅 결정을 담고 있는지·캐시 키가 실제로 적재됐는지·그리고
학생 원문이 **어디에도 없는지**(S1-a·OPS-36 ③)까지 같은 자리에서 잰다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

from whymath_backend.harness.wh1_loop import NEUTRAL_GUIDE_UTTERANCE
from whymath_backend.harness.wh1_primary import run_wh1_primary_turn
from whymath_backend.harness.wh1_prose import rephrase_coach_utterance
from whymath_backend.l3.interfaces import InMemoryCache, RecordingTraceSink
from whymath_backend.l3.models import GenerationResult, RoutingDecision

# 학생 원문·풀이 sentinel — 트레이스·캐시 키 유입 봉인용(test_wh1_prose 관례 미러).
_STUDENT_SENTINEL = "ZZPIIZZ 학생 개인 풀이"
_STEPS = ["2x+3=7", "2x=4", "x=2"]

# 라우팅 결정이 실려야 할 키 — `router.langfuse_fields`가 만드는 태그 표(03a §F.2).
_ROUTING_KEYS = ("cost_tier", "local_family", "local_model", "mode", "cache_hit", "reason")


class _CapturingProvider:
    """스크립트 응답 방출 + 받은 `decision`까지 캡처 — 좌석이 결정을 싣는지 확인용."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.decisions: list[RoutingDecision] = []
        self.temperatures: list[float | None] = []

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        self.decisions.append(decision)
        self.temperatures.append(temperature)
        out = self._responses[self._index] if self._index < len(self._responses) else ""
        self._index += 1
        return GenerationResult(out)


def _run_primary(provider: object, cache: object, trace: object) -> str | None:
    """관측·캐시를 주입한 primary 1턴 — 프로덕션(coach)이 넘기는 것과 같은 형태."""
    return asyncio.run(
        run_wh1_primary_turn(  # type: ignore[arg-type]
            student_solution=_STUDENT_SENTINEL,
            solution_steps=list(_STEPS),
            active_hypotheses=[],
            provider=provider,
            cache=cache,
            trace=trace,
        )
    )


class TestPolicyCallIsTraced:
    """정책(튜터 두뇌)의 LLM 호출이 관측 원장에 남는가 — 결선의 본체."""

    def test_primary_turn_records_routing_trace(self) -> None:
        trace = RecordingTraceSink()
        provider = _CapturingProvider(['{"kind": "end_turn", "action_type": "격려"}'])

        _run_primary(provider, InMemoryCache(), trace)

        assert (
            trace.records
        ), "학생 대면 LLM 호출이 관측 기록을 한 건도 내지 않았다 — 파이프라인 우회 상태다"
        for key in _ROUTING_KEYS:
            assert key in trace.records[0], f"관측 레코드에 라우팅 필드 {key!r}가 없다"

    def test_trace_carries_the_routers_decision_not_a_hand_built_one(self) -> None:
        """기록된 결정이 provider가 받은 결정과 같아야 한다 — 손조립 우회면 갈라진다."""
        trace = RecordingTraceSink()
        provider = _CapturingProvider(['{"kind": "end_turn", "action_type": "격려"}'])

        _run_primary(provider, InMemoryCache(), trace)

        assert provider.decisions, "provider가 호출되지 않았다 — 스캔이 깨졌다"
        recorded = trace.records[0]
        sent = provider.decisions[0]
        assert recorded["cost_tier"] == sent.cost_tier
        assert recorded["local_model"] == sent.local_model
        assert recorded["local_family"] == sent.local_family

    def test_generation_is_stored_in_the_injected_cache(self) -> None:
        """캐시 결선 — 미스 생성물이 주입 캐시에 적재된다(다음 동일 요청이 적중)."""
        cache = InMemoryCache()
        provider = _CapturingProvider(['{"kind": "end_turn", "action_type": "격려"}'])

        _run_primary(provider, cache, RecordingTraceSink())

        assert cache._store, "생성물이 주입 캐시에 적재되지 않았다 — 캐시 미결선 상태다"


class TestProseCallIsTraced:
    """프로즈(발화 문맥화)의 LLM 호출도 같은 좌석을 거치는가."""

    def test_rephrase_records_routing_trace_and_keeps_temperature(self) -> None:
        trace = RecordingTraceSink()
        cache = InMemoryCache()
        provider = _CapturingProvider(["방금 그 부분, 왜 그렇게 했는지 들려줄래?"])

        asyncio.run(
            rephrase_coach_utterance(  # type: ignore[arg-type]
                NEUTRAL_GUIDE_UTTERANCE,
                action_type="힌트",
                verdict="incorrect",
                turn_index=1,
                hypothesis_label=None,
                forbidden_fragments=[_STUDENT_SENTINEL, *_STEPS],
                provider=provider,
                timeout_seconds=2.0,
                cache=cache,
                trace=trace,
            )
        )

        assert trace.records, "프로즈 호출이 관측 기록을 내지 않았다 — 파이프라인 우회 상태다"
        # 온도는 좌석을 거쳐도 provider까지 살아 있어야 한다(실측 최적 0.7 배선 보존).
        assert provider.temperatures == [0.7]

    def test_general_family_preference_survives_the_pipeline(self) -> None:
        """패밀리 선호가 라우터 *뒤*에서 적용돼 결정·기록 양쪽에 반영된다.

        종전에는 `_decide_routing`이 `RoutingDecision`을 손으로 재조립해 이 선호를 넣었고
        그 재조립이 곧 우회였다. 이제 `pipeline.generate(prefer_local_family=...)`가 같은 일을
        하되 라우터 경유를 유지한다 — 선호가 사라지면(인자를 떼면) 이 검사가 RED다.
        """
        trace = RecordingTraceSink()
        provider = _CapturingProvider(["방금 그 부분, 왜 그렇게 했는지 들려줄래?"])

        asyncio.run(
            rephrase_coach_utterance(  # type: ignore[arg-type]
                NEUTRAL_GUIDE_UTTERANCE,
                action_type="힌트",
                verdict="incorrect",
                turn_index=1,
                hypothesis_label=None,
                forbidden_fragments=[_STUDENT_SENTINEL, *_STEPS],
                provider=provider,
                timeout_seconds=2.0,
                cache=InMemoryCache(),
                trace=trace,
            )
        )

        assert provider.decisions, "provider가 호출되지 않았다 — 스캔이 깨졌다"
        assert provider.decisions[0].local_family == "general"
        assert trace.records[0]["local_family"] == "general"


class TestNoStudentTextLeaksIntoObservability:
    """OPS-36 ③ — 결선했다고 학생 원문이 관측·캐시로 새면 안 된다(S1-a 불변)."""

    def test_student_text_absent_from_trace_records_and_cache_keys(self) -> None:
        trace = RecordingTraceSink()
        cache = InMemoryCache()
        provider = _CapturingProvider(['{"kind": "end_turn", "action_type": "격려"}'])

        _run_primary(provider, cache, trace)

        assert trace.records, "기록이 0건이면 이 검사는 공허하게 통과한다 — 스캔이 깨졌다"
        blob = repr(trace.records) + repr(list(cache._store))
        assert _STUDENT_SENTINEL not in blob
        for step in _STEPS:
            assert step not in blob
