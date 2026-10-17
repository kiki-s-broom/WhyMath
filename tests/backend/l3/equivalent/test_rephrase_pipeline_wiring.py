"""저작 rephrase의 **파이프라인 결선** 동결 — 관측이 실적재되고 캐시가 다양화를 죽이지 않는가 (OPS-84).

왜 이 파일이 따로 있는가
------------------------
`test_rephrase.py`는 *봉인이 지켜지는가*를 본다. 그런데 종전 `QuestionRephraser`는 봉인이
멀쩡하면서도 Langfuse `l3_routing` 이벤트를 **한 건도** 내지 않았다 — `Router().route()` 결과를
손으로 재조립해 `provider.generate(...)`를 직접 불러 `l3.pipeline`을 우회했기 때문이다(OPS-36이
학생 대면 축에서 고친 것과 같은 형태의 저작 경로판). 발문이 정상이면 산출물도 정상이라 무증상이다.

그러므로 이 파일은 **결선 자체**와 **캐시 판정의 근거**를 계약으로 동결한다:

  ① 결선 — 호출마다 trace 1건, 그 결정이 파이프라인이 낸 것(`prefer:general`)이어야 한다.
     재조립 코드로 되돌리면(`→ rephrase:general`) 또는 trace thread를 끊으면 RED.
  ② 캐시 — 같은 발문을 반복해도 매번 provider가 불린다. 대조군(캐시를 켠 경우)이 스윕의
     반복 측정을 **실제로** 붕괴시킨다는 것까지 같은 자리에서 잰다 — 판정 근거가 추측이 아니라
     이 테스트의 실측이다(모듈 docstring 「캐시 판정」).
  ③ 관측 기본값 — 라이브 지연 구성이면 LangfuseSink, 그 싱크가 실제 클라이언트에 `l3_routing`
     이벤트를 낸다(주입 가짜 클라이언트로 SDK 직전까지).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from whymath_backend.harness.problem_corpus_batch import run_corpus_batch
from whymath_backend.harness.problem_corpus_rephrase_sweep import run_rephrase_sweep
from whymath_backend.l3.equivalent import rephrase as rephrase_module
from whymath_backend.l3.equivalent.rephrase import QuestionRephraser
from whymath_backend.l3.interfaces import InMemoryCache, RecordingTraceSink
from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l3.trace.langfuse_sink import LangfuseSink

_Q = "이차방정식 3x^2 - 7x + 4 = 0 의 두 근 중 큰 근을 구하시오."
_OUT = "이차방정식 3x^2 - 7x + 4 = 0 을 풀어 두 해 중 더 큰 값을 답하시오."

# 라우팅 결정이 실려야 할 키 — `router.langfuse_fields`가 만드는 태그 표(03a §F.2).
_ROUTING_KEYS = ("cost_tier", "local_family", "local_model", "mode", "cache_hit", "reason")


class _CountingProvider:
    """고정 응답 + 호출 수·받은 decision·온도 캡처."""

    def __init__(self, out: str = _OUT) -> None:
        self._out = out
        self.calls = 0
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
        self.calls += 1
        self.decisions.append(decision)
        self.temperatures.append(temperature)
        return GenerationResult(self._out)


class _AlternatingProvider:
    """호출 순번 짝수=다양화·홀수=원문 — 회차 간 변형률이 흔들리게(스윕 min≠max 재현).

    `test_problem_corpus_rephrase_sweep._AlternatingProvider`와 같은 모델이다(라이브 LLM의 회차
    변동을 결정론으로 모사). 여기서는 호출 수를 함께 세어 캐시가 호출을 삼키는지를 본다.
    """

    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def _base(prompt: str) -> str:
        for line in prompt.splitlines():
            if line.startswith("원 발문: "):
                return line[len("원 발문: ") :]
        return "무효"  # pragma: no cover — 프롬프트 형식 보증

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
        base = self._base(prompt)
        diversify = self.calls % 2 == 0
        self.calls += 1
        return GenerationResult(base + " (다양화)" if diversify else base)


class _FakeLangfuseClient:
    """SDK 직전 경계 — `create_event`·`flush` 호출을 캡처."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.flushed = 0

    def create_event(self, *, name: str, metadata: dict[str, object], level: str) -> None:
        self.events.append({"name": name, "metadata": metadata, "level": level})

    def flush(self) -> None:
        self.flushed += 1


def _seed_corpus(tmp_path: Path) -> Path:
    """소형 결정론 코퍼스(quad 밴드 12건 — 방정식 추출 대상)."""
    src = tmp_path / "src.jsonl"
    report = run_corpus_batch(
        out_path=src,
        short_n=8,
        mc_n=4,
        sqrt_n=0,
        sqrt_mc_n=0,
        calc_extremum_n=0,
        calc_tangent_n=0,
        calc_value_n=0,
        calc_value_mc_n=0,
        calc_extremum_irr_n=0,
        exp_n=0,
        log_n=0,
        arith_n=0,
        geo_n=0,
        trig_n=0,
        arith_sum_n=0,
        geo_sum_n=0,
        trig_eq_n=0,
        seq_inductive_n=0,
        write=True,
    )
    assert report.fulfilled
    return src


# ===========================================================================
# ① 결선 — 호출마다 파이프라인이 trace를 남긴다
# ===========================================================================


class TestPipelineWiring:
    def test_each_rephrase_records_one_routing_trace(self) -> None:
        trace = RecordingTraceSink()
        rephraser = QuestionRephraser(_CountingProvider(), trace=trace)
        rephraser.rephrase(_Q)
        rephraser.rephrase(_Q)
        assert len(trace.records) == 2
        for record in trace.records:
            for key in _ROUTING_KEYS:
                assert key in record, key
            assert record["content_source"] == "generate"
            # 저작 표지 — cost_report가 게이트② 표본에서 분리하는 근거(OPS-84 ③).
            assert record["traffic_surface"] == "authoring"

    def test_trace_carries_the_pipelines_decision_not_a_hand_built_one(self) -> None:
        # 파이프라인의 패밀리 선호는 사유 문자열에 `prefer:general`을 남긴다. 종전 재조립 코드는
        # `rephrase:general`을 남겼다 — 재조립으로 되돌리는 회귀는 이 단언에서 RED가 된다.
        trace = RecordingTraceSink()
        provider = _CountingProvider()
        QuestionRephraser(provider, trace=trace).rephrase(_Q)
        (record,) = trace.records
        assert record["local_family"] == "general"
        assert "prefer:general" in str(record["reason"])
        assert "rephrase:general" not in str(record["reason"])
        # provider가 받은 결정과 trace의 결정이 같은 것이어야 한다(관측 ≠ 실제 호출 방지).
        assert provider.decisions[0].reason == record["reason"]

    def test_temperature_survives_the_pipeline(self) -> None:
        provider = _CountingProvider()
        QuestionRephraser(provider, temperature=0.9, trace=RecordingTraceSink()).rephrase(_Q)
        assert provider.temperatures == [0.9]

    def test_no_trace_when_equation_absent(self) -> None:
        # 대조군 — LLM을 부르지 않은 경로는 기록도 없다(호출 1건 = 기록 1건의 양방향).
        trace = RecordingTraceSink()
        provider = _CountingProvider()
        QuestionRephraser(provider, trace=trace).rephrase("발문에 방정식이 없다.")
        assert provider.calls == 0
        assert trace.records == []


# ===========================================================================
# ② 캐시 판정 — 끈다. 근거는 대조군 실측
# ===========================================================================


class TestNoStoreCacheJudgement:
    def test_repeated_prompt_reaches_provider_every_time(self) -> None:
        trace = RecordingTraceSink()
        provider = _CountingProvider()
        rephraser = QuestionRephraser(provider, trace=trace)
        for _ in range(3):
            rephraser.rephrase(_Q)
        assert provider.calls == 3
        assert [r["cache_hit"] for r in trace.records] == [False, False, False]

    def test_sweep_repeats_are_real_calls_and_keep_their_spread(self, tmp_path: Path) -> None:
        # 스윕은 같은 rephraser로 같은 앞 N건을 repeats회 반복해 회차 간 폭으로 유의성을 본다.
        src = _seed_corpus(tmp_path)
        provider = _AlternatingProvider()
        report = run_rephrase_sweep(
            in_path=src,
            temperatures=(0.7,),
            limit=5,
            repeats=5,
            rephraser_factory=lambda t: QuestionRephraser(
                provider, temperature=t, trace=RecordingTraceSink()  # type: ignore[arg-type]
            ),
        )
        (row,) = report.rows
        assert provider.calls == 5 * 5  # N×repeats — 회차마다 실제 호출
        assert row.rate_min != row.rate_max  # 회차 변동이 측정에 살아 있다

    def test_control_group_cache_on_collapses_the_sweep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 대조군 — 같은 스윕을 캐시를 켠 상태로 돌리면 2회차부터 전건 적중해 호출이 N회로 줄고
        # 폭이 0으로 붕괴한다. 이것이 「캐시를 끈다」 판정의 실측 근거다(추측 아님).
        cache = InMemoryCache()
        monkeypatch.setattr(rephrase_module, "_NoStoreCache", lambda: cache)
        src = _seed_corpus(tmp_path)
        provider = _AlternatingProvider()
        report = run_rephrase_sweep(
            in_path=src,
            temperatures=(0.7,),
            limit=5,
            repeats=5,
            rephraser_factory=lambda t: QuestionRephraser(
                provider, temperature=t, trace=RecordingTraceSink()  # type: ignore[arg-type]
            ),
        )
        (row,) = report.rows
        assert provider.calls == 5  # 1회차만 실제 호출 — 측정이 위장된다
        assert row.rate_min == row.rate_max


# ===========================================================================
# ③ 관측 기본값·전송 — 라이브 경로는 LangfuseSink, SDK 직전까지 이벤트가 간다
# ===========================================================================


class TestTraceDefaults:
    def test_injected_provider_without_trace_falls_back_to_recording(self) -> None:
        rephraser = QuestionRephraser(_CountingProvider())
        rephraser.rephrase(_Q)
        assert isinstance(rephraser._trace, RecordingTraceSink)  # noqa: SLF001
        assert len(rephraser._trace.records) == 1  # noqa: SLF001

    def test_live_lazy_assembly_uses_langfuse_sink(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 라이브 지연 구성 경로 — 네트워크 없이 조립만 확인(제공자 생성자를 가짜로 교체).
        import whymath_backend.l3.providers.factory as factory
        import whymath_backend.l3.providers.ollama as ollama

        monkeypatch.setattr(factory, "build_cloud_provider", lambda: _CountingProvider())
        monkeypatch.setattr(ollama, "OllamaProvider", lambda: _CountingProvider())
        rephraser = QuestionRephraser()
        rephraser._resolve_provider()  # noqa: SLF001
        assert isinstance(rephraser._trace, LangfuseSink)  # noqa: SLF001

    def test_langfuse_sink_receives_l3_routing_event_and_flush(self) -> None:
        client = _FakeLangfuseClient()
        rephraser = QuestionRephraser(_CountingProvider(), trace=LangfuseSink(client=client))
        rephraser.rephrase(_Q)
        rephraser.flush()
        assert [e["name"] for e in client.events] == ["l3_routing"]
        metadata = client.events[0]["metadata"]
        assert isinstance(metadata, dict)
        assert metadata["local_family"] == "general"
        assert metadata["traffic_surface"] == "authoring"
        assert client.flushed == 1

    def test_flush_is_noop_for_sinks_without_flush(self) -> None:
        rephraser = QuestionRephraser(_CountingProvider(), trace=RecordingTraceSink())
        rephraser.flush()  # 예외 없이 끝나야 한다


def test_prompt_text_absent_from_trace_records() -> None:
    # 저작 발문은 자체 저작 동등문제라 PII는 아니지만, trace는 라우팅 메타만 싣는다는 계약을 확인.
    trace = RecordingTraceSink()
    QuestionRephraser(_CountingProvider(), trace=trace).rephrase(_Q)
    digest = hashlib.sha256(_Q.encode("utf-8")).hexdigest()
    flat = repr(trace.records)
    assert _Q not in flat
    assert digest not in flat
