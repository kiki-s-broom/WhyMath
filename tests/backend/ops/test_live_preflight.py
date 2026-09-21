"""live_preflight 프리플라이트 hermetic 테스트 — 라이브 호출 0.

가짜 Settings(키 유/무)로 ①② 판정 분기를, 가짜 provider(generate가 GenerationResult를
반환)로 ③ 실측 비용·None-vs-0·graceful skip·JSON 형식을 단언한다. 실 네트워크·실 키 없음.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from whymath_backend.l3 import pipeline
from whymath_backend.l3.data_export_policy import EXPORT_ALLOWED, EXPORT_PROHIBITED
from whymath_backend.l3.interfaces import InMemoryCache
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
    RoutingRequest,
    Usage,
)
from whymath_backend.l3.providers.anthropic import AnthropicStatus
from whymath_backend.l3.providers.ollama import ModelAvailability, OllamaStatus
from whymath_backend.l3.router import actual_cost_krw
from whymath_backend.ops import live_preflight as lp


# ──────────────────────────────────────────────────────────────────────────
# 가짜 Settings·provider — 라이브 없이 코어를 태운다.
# ──────────────────────────────────────────────────────────────────────────
class _FakeSettings:
    """Settings의 최소 표면만 흉내 — 두 판정 프로퍼티만 필요하다."""

    def __init__(self, *, anthropic: bool, langfuse: bool) -> None:
        self.anthropic_configured = anthropic
        self.langfuse_configured = langfuse


class _FakeCloud:
    """가짜 클라우드 provider — configured/check_status/generate 표면만."""

    def __init__(
        self,
        *,
        configured: bool,
        reachable: bool,
        result: GenerationResult | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._configured = configured
        self._reachable = reachable
        self._result = result
        self._raise = raise_exc
        self.generate_calls: list[RoutingDecision] = []

    @property
    def configured(self) -> bool:
        return self._configured

    async def check_status(self) -> AnthropicStatus:
        return AnthropicStatus(
            configured=self._configured,
            reachable=self._reachable,
            error=None if self._reachable else "AuthError: bad key",
        )

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision
    ) -> GenerationResult:
        self.generate_calls.append(decision)
        if self._raise is not None:
            raise self._raise
        assert self._result is not None
        return self._result


class _FakeOllama:
    """가짜 로컬 provider — check_status만."""

    def __init__(self, *, reachable: bool) -> None:
        self._reachable = reachable

    async def check_status(self) -> OllamaStatus:
        return OllamaStatus(
            reachable=self._reachable,
            models=(ModelAvailability(model_id="qwen2-math:7b", present=self._reachable),),
            error=None if self._reachable else "ConnectionError: down",
        )


def _cloud_factory(fake: _FakeCloud) -> lp.CloudProviderFactory:
    return lambda _settings: fake  # type: ignore[arg-type,return-value]


def _local_factory(fake: _FakeOllama) -> lp.LocalProviderFactory:
    return lambda _settings: fake  # type: ignore[arg-type,return-value]


def _settings(*, anthropic: bool, langfuse: bool) -> lp.Settings:
    # _FakeSettings는 Settings의 두 프로퍼티만 노출 — run_preflight는 그 둘만 읽는다.
    return _FakeSettings(anthropic=anthropic, langfuse=langfuse)  # type: ignore[return-value]


# ──────────────────────────────────────────────────────────────────────────
# ①② 판정 분기
# ──────────────────────────────────────────────────────────────────────────
async def test_configured_flags_reflect_settings() -> None:
    """①② 판정은 Settings의 두 프로퍼티를 그대로 반영한다."""
    cloud = _FakeCloud(configured=True, reachable=True, result=GenerationResult(text="2"))
    report = await lp.run_preflight(
        _settings(anthropic=True, langfuse=False),
        smoke=False,
        cloud_provider_factory=_cloud_factory(cloud),
        local_provider_factory=_local_factory(_FakeOllama(reachable=True)),
    )
    assert report.cloud_configured is True
    assert report.langfuse_configured is False


# ──────────────────────────────────────────────────────────────────────────
# ③ 스모크 — 실측 비용 산정
# ──────────────────────────────────────────────────────────────────────────
async def test_smoke_computes_actual_cost_krw() -> None:
    """토큰이 있으면 actual_cost_krw로 실측 비용을 산정하고 CLOUD_MID로 호출한다."""
    usage = Usage(input_tokens=100, output_tokens=50, latency_ms=1234.5)
    cloud = _FakeCloud(
        configured=True, reachable=True, result=GenerationResult(text="2", usage=usage)
    )
    report = await lp.run_preflight(
        _settings(anthropic=True, langfuse=True),
        smoke=True,
        cloud_provider_factory=_cloud_factory(cloud),
        local_provider_factory=_local_factory(_FakeOllama(reachable=True)),
    )
    # CLOUD_MID(Sonnet) 강제 — Opus(HIGH) 아님.
    assert cloud.generate_calls[0].cost_tier == CostTier.CLOUD_MID.value
    smoke = report.smoke
    assert smoke.ran is True
    expected = actual_cost_krw(lp._cloud_mid_decision(), usage)
    assert smoke.cost_krw == expected
    assert smoke.cost_krw is not None and smoke.cost_krw > 0.0
    assert smoke.input_tokens == 100
    assert smoke.output_tokens == 50
    assert smoke.latency_ms == 1234.5
    assert smoke.text_chars == 1
    assert report.exit_code == 0


# ──────────────────────────────────────────────────────────────────────────
# EOS-77: 스모크 결정은 라우터가 낸다 — 손 조립 클라우드 결정(법적 게이트 우회) 금지
# ──────────────────────────────────────────────────────────────────────────
def test_cloud_mid_decision_is_routed_and_carries_export_judgment() -> None:
    """현행 라우터 규칙에서 스모크 요청은 CLOUD_MID·sync로 라우팅되고 등급 판정이 실린다.

    2026-09-05 이전의 손 조립 결정은 `data_export_reason=None`(판정 안 함)이었다. 이 테스트가
    실패하면 ①비즈니스 규칙(구독·예산 임계)이 바뀌어 스모크가 클라우드에 못 가거나 ②등급
    게이트가 SYNTHETIC_PROBE를 막게 됐다는 뜻이다 — 프리플라이트가 재려던 것을 못 재는 상태를
    Kiki 실행 시점이 아니라 PR 시점에 드러낸다.
    """
    decision = lp._cloud_mid_decision()
    assert decision.cost_tier == CostTier.CLOUD_MID.value
    assert decision.mode == "sync"
    assert decision.data_export_reason == EXPORT_ALLOWED
    assert decision.data_export_blocked is False
    # CLOUD_* 불변식(03a §G) — 축3·축2 없음.
    assert decision.local_family is None and decision.local_model is None


class _LocalOnlyRouter:
    """라우터 스텁 — 비즈니스 규칙이 바뀌어(또는 등급 게이트가 막아) LOCAL을 내는 상황."""

    def route(self, req: RoutingRequest) -> RoutingDecision:
        return RoutingDecision(
            cost_tier=CostTier.LOCAL,
            local_family=ModelFamily.MATH,
            local_model=LocalModelTier.FAST,
            mode="sync",
            reason="local/math/fast (data-export gate: EXPORT_PROHIBITED)",
            est_latency_ms=1010,
            est_cost_krw=0.0,
            data_export_blocked=True,
            data_export_reason=EXPORT_PROHIBITED,
        )


async def test_smoke_refuses_to_run_when_router_does_not_yield_cloud_mid(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    """라우터가 CLOUD_MID를 주지 않으면 스모크를 *실행하지 않고* exit 2 — 로컬 1콜로 조용히
    대체하지 않는다(재려던 것을 못 잰 사실을 크게 알린다). 사유에 라우터 판정을 싣는다."""
    monkeypatch.setattr(lp, "Router", _LocalOnlyRouter)
    usage = Usage(input_tokens=100, output_tokens=50, latency_ms=10.0)
    cloud = _FakeCloud(
        configured=True, reachable=True, result=GenerationResult(text="2", usage=usage)
    )
    report = await lp.run_preflight(
        _settings(anthropic=True, langfuse=True),
        smoke=True,
        cloud_provider_factory=_cloud_factory(cloud),
        local_provider_factory=_local_factory(_FakeOllama(reachable=True)),
    )
    assert cloud.generate_calls == [], "라우터가 LOCAL을 냈는데 클라우드 1콜이 나갔다"
    smoke = report.smoke
    assert smoke.ran is False
    assert smoke.error is not None
    assert "CLOUD_MID" in smoke.error
    assert "cost_tier=local" in smoke.error
    assert EXPORT_PROHIBITED in smoke.error  # 게이트가 막은 사유가 그대로 보인다
    assert report.exit_code == 2
    # 렌더: skip이 아니라 실패로 보인다(측정 실패의 위장 방지).
    text = lp._render_stdout(report)
    assert "실패:" in text and "라우터가 CLOUD_MID" in text
    assert "skip:" not in text


# ──────────────────────────────────────────────────────────────────────────
# None-vs-0: 토큰 미상 → cost None (0원 아님)
# ──────────────────────────────────────────────────────────────────────────
async def test_smoke_none_tokens_yields_none_cost() -> None:
    """클라우드인데 토큰이 미상(None)이면 비용은 None — '0원 확정'과 구분."""
    usage = Usage(input_tokens=None, output_tokens=None, latency_ms=900.0)
    cloud = _FakeCloud(
        configured=True, reachable=True, result=GenerationResult(text="2", usage=usage)
    )
    report = await lp.run_preflight(
        _settings(anthropic=True, langfuse=True),
        smoke=True,
        cloud_provider_factory=_cloud_factory(cloud),
        local_provider_factory=_local_factory(_FakeOllama(reachable=True)),
    )
    assert report.smoke.ran is True
    assert report.smoke.cost_krw is None  # 미상 ≠ 0원


async def test_smoke_no_usage_yields_none_cost() -> None:
    """usage 자체가 없으면(미계측 provider) 비용은 None."""
    cloud = _FakeCloud(
        configured=True, reachable=True, result=GenerationResult(text="2", usage=None)
    )
    report = await lp.run_preflight(
        _settings(anthropic=True, langfuse=True),
        smoke=True,
        cloud_provider_factory=_cloud_factory(cloud),
        local_provider_factory=_local_factory(_FakeOllama(reachable=True)),
    )
    assert report.smoke.cost_krw is None
    assert report.smoke.input_tokens is None


# ──────────────────────────────────────────────────────────────────────────
# graceful skip — 키 없음
# ──────────────────────────────────────────────────────────────────────────
async def test_smoke_skipped_when_anthropic_unconfigured() -> None:
    """anthropic 미설정이면 스모크는 graceful skip 하고 사유에 '키 없음'을 명시한다."""
    cloud = _FakeCloud(configured=False, reachable=False)
    report = await lp.run_preflight(
        _settings(anthropic=False, langfuse=False),
        smoke=True,
        cloud_provider_factory=_cloud_factory(cloud),
        local_provider_factory=_local_factory(_FakeOllama(reachable=False)),
    )
    assert report.smoke.ran is False
    assert report.smoke.skipped_reason is not None
    assert "키 없음" in report.smoke.skipped_reason
    # 미설정은 정보 — Ollama도 down이지만 종료 코드는 0.
    assert report.exit_code == 0
    assert cloud.generate_calls == []  # 실 호출 없음


async def test_smoke_skipped_when_no_smoke_flag() -> None:
    """--no-smoke(smoke=False)면 설정돼 있어도 실 호출을 하지 않는다."""
    cloud = _FakeCloud(configured=True, reachable=True, result=GenerationResult(text="2"))
    report = await lp.run_preflight(
        _settings(anthropic=True, langfuse=True),
        smoke=False,
        cloud_provider_factory=_cloud_factory(cloud),
        local_provider_factory=_local_factory(_FakeOllama(reachable=True)),
    )
    assert report.smoke.ran is False
    assert cloud.generate_calls == []


# ──────────────────────────────────────────────────────────────────────────
# 종료 코드 — 설정됐는데 도달 불가 / 스모크 실패
# ──────────────────────────────────────────────────────────────────────────
async def test_exit_error_when_configured_but_unreachable() -> None:
    """클라우드가 설정됐는데 도달 불가면 종료 코드 2."""
    cloud = _FakeCloud(configured=True, reachable=False)
    report = await lp.run_preflight(
        _settings(anthropic=True, langfuse=True),
        smoke=False,
        cloud_provider_factory=_cloud_factory(cloud),
        local_provider_factory=_local_factory(_FakeOllama(reachable=True)),
    )
    assert report.cloud_reachable is False
    assert report.cloud_error is not None
    assert report.exit_code == 2


async def test_exit_error_when_smoke_raises() -> None:
    """스모크 1콜이 예외로 실패하면 종료 코드 2, 오류는 리포트에 흡수된다."""
    cloud = _FakeCloud(configured=True, reachable=True, raise_exc=RuntimeError("boom"))
    report = await lp.run_preflight(
        _settings(anthropic=True, langfuse=True),
        smoke=True,
        cloud_provider_factory=_cloud_factory(cloud),
        local_provider_factory=_local_factory(_FakeOllama(reachable=True)),
    )
    assert report.smoke.error is not None
    assert "boom" in report.smoke.error
    assert report.exit_code == 2


async def test_ollama_down_does_not_fail_exit() -> None:
    """Ollama 도달 불가는 정보용 — 종료 코드를 좌우하지 않는다."""
    cloud = _FakeCloud(configured=False, reachable=False)
    report = await lp.run_preflight(
        _settings(anthropic=False, langfuse=False),
        smoke=True,
        cloud_provider_factory=_cloud_factory(cloud),
        local_provider_factory=_local_factory(_FakeOllama(reachable=False)),
    )
    assert report.ollama_reachable is False
    assert report.ollama_error is not None
    assert report.exit_code == 0


# ──────────────────────────────────────────────────────────────────────────
# 미설정 시 클라우드 도달성은 미점검(None)
# ──────────────────────────────────────────────────────────────────────────
async def test_cloud_reachable_none_when_unconfigured() -> None:
    """anthropic 미설정이면 도달성은 점검 대상이 아니므로 None."""
    cloud = _FakeCloud(configured=False, reachable=False)
    report = await lp.run_preflight(
        _settings(anthropic=False, langfuse=True),
        smoke=False,
        cloud_provider_factory=_cloud_factory(cloud),
        local_provider_factory=_local_factory(_FakeOllama(reachable=True)),
    )
    assert report.cloud_reachable is None
    assert report.cloud_error is None


# ──────────────────────────────────────────────────────────────────────────
# 리포트 렌더·JSON 형식 + 시크릿 미출력
# ──────────────────────────────────────────────────────────────────────────
def _sample_report() -> lp.Report:
    return lp.Report(
        cloud_configured=True,
        langfuse_configured=True,
        cloud_reachable=True,
        cloud_error=None,
        ollama_reachable=False,
        ollama_error="ConnectionError: down",
        smoke=lp.SmokeResult(
            ran=True,
            cost_krw=1.155,
            input_tokens=100,
            output_tokens=50,
            latency_ms=1234.5,
            text_chars=1,
        ),
        exit_code=0,
    )


def test_stdout_render_has_sections_and_no_secrets() -> None:
    """사람용 stdout은 판정·도달성·스모크 섹션을 담고 bool·비용·토큰만 노출한다."""
    text = lp._render_stdout(_sample_report())
    assert "cloud_configured" in text
    assert "langfuse_configured" in text
    assert "CLOUD_MID" in text
    assert "1.1550원" in text  # 비용 표기
    # 시크릿 값(sk-ant-/pk-lf-)은 어디에도 없어야 한다.
    assert "sk-ant" not in text
    assert "pk-lf" not in text


def test_none_cost_renders_as_unknown() -> None:
    """비용 None은 '미상'으로 렌더(0원과 구분)."""
    assert "미상" in lp._fmt_cost(None)
    assert lp._fmt_cost(None) != "0원"


def test_json_report_roundtrip(tmp_path: Path) -> None:
    """JSON 리포트는 dataclass 구조를 그대로 담고 다시 로드된다."""
    report = _sample_report()
    out = tmp_path / "preflight.json"
    lp._write_json(report, out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["cloud_configured"] is True
    assert loaded["smoke"]["cost_krw"] == 1.155
    assert loaded["smoke"]["input_tokens"] == 100
    assert loaded["exit_code"] == 0


# ──────────────────────────────────────────────────────────────────────────
# --via-pipeline — 스모크를 pipeline.generate로 태워 Langfuse 기록·flush (hermetic)
# ──────────────────────────────────────────────────────────────────────────
class _FakePipelineProvider:
    """가짜 LLMProvider — pipeline.generate가 호출하는 generate 표면만 흉내.

    라우팅 결정과 무관하게 고정 결과(text+usage)를 돌려준다(라이브 0). images/temperature/
    json_schema 키워드는 pipeline이 텍스트 호출 시 넘기지 않으므로 선택적으로만 받는다.
    """

    def __init__(self, result: GenerationResult, *, raise_exc: Exception | None = None) -> None:
        self._result = result
        self._raise = raise_exc
        self.calls: list[RoutingDecision] = []

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,  # EOS-73 — LLMProvider 계약 정합(대역은 시드를 쓰지 않는다)
    ) -> GenerationResult:
        self.calls.append(decision)
        if self._raise is not None:
            raise self._raise
        return self._result


class _SpyInnerSink:
    """record/flush 호출 횟수를 세는 스파이 — _CapturingTraceSink의 내부 싱크로 주입.

    LangfuseSink 자리에 들어가 실전송 없이 'pipeline이 record를 불렀는가·CLI가 flush를
    불렀는가'만 관측한다(_FlushTraceSink 표면 충족).
    """

    def __init__(self) -> None:
        self.record_count = 0
        self.flush_count = 0

    def record(self, fields: dict[str, object]) -> None:
        self.record_count += 1

    def flush(self) -> None:
        self.flush_count += 1


def _pipeline_deps(
    provider: _FakePipelineProvider, spy: _SpyInnerSink
) -> tuple[lp.PipelineDeps, InMemoryCache]:
    """가짜 provider·스파이 trace로 PipelineDeps 조립 — pipeline.generate는 실물(순수)."""
    cache = InMemoryCache()
    deps = lp.PipelineDeps(
        provider=provider,  # type: ignore[arg-type]
        cache=cache,
        trace=lp._CapturingTraceSink(spy),  # type: ignore[arg-type]
        generate=pipeline.generate,
    )
    return deps, cache


async def test_via_pipeline_cloud_mid_records_and_flushes() -> None:
    """anthropic 설정 시 CLOUD_MID(sync)로 라우팅되고 record·flush가 불린다."""
    usage = Usage(input_tokens=100, output_tokens=50, latency_ms=1234.5)
    provider = _FakePipelineProvider(GenerationResult(text="2", usage=usage))
    spy = _SpyInnerSink()
    deps, cache = _pipeline_deps(provider, spy)

    report = await lp.run_preflight(
        _settings(anthropic=True, langfuse=True),
        smoke=True,
        via_pipeline=True,
        cloud_provider_factory=_cloud_factory(
            _FakeCloud(configured=True, reachable=True, result=GenerationResult(text="x"))
        ),
        local_provider_factory=_local_factory(_FakeOllama(reachable=True)),
        pipeline_deps_factory=lambda _s: deps,
    )
    smoke = report.smoke
    assert smoke.via_pipeline is True
    assert smoke.ran is True
    # 라우터가 실제로 CLOUD_MID로 결정했는가(목표대로).
    assert smoke.routed_cost_tier == CostTier.CLOUD_MID.value
    assert provider.calls[0].cost_tier == CostTier.CLOUD_MID.value
    # Langfuse record(파이프라인 경유)·flush(CLI 후처리)가 각각 불렸다.
    assert spy.record_count == 1
    assert spy.flush_count == 1
    assert smoke.langfuse_recorded is True
    # 클라우드 실측 비용 — 토큰 있으면 actual_cost_krw로 산정(>0).
    assert smoke.cost_krw is not None and smoke.cost_krw > 0.0
    assert smoke.input_tokens == 100
    assert smoke.output_tokens == 50
    # InMemoryCache에 미스 생성물이 적재됐다(캐시 경유 확인).
    assert len(cache._store) == 1
    assert report.exit_code == 0


async def test_via_pipeline_local_fallback_when_anthropic_unset() -> None:
    """anthropic 미설정이면 LOCAL(easy/free) 폴백 — cost_tier=LOCAL·0원이라도 기록 성립."""
    usage = Usage(input_tokens=20, output_tokens=10, latency_ms=900.0)
    provider = _FakePipelineProvider(GenerationResult(text="2", usage=usage))
    spy = _SpyInnerSink()
    deps, _cache = _pipeline_deps(provider, spy)

    report = await lp.run_preflight(
        _settings(anthropic=False, langfuse=True),
        smoke=True,
        via_pipeline=True,
        cloud_provider_factory=_cloud_factory(_FakeCloud(configured=False, reachable=False)),
        local_provider_factory=_local_factory(_FakeOllama(reachable=True)),
        pipeline_deps_factory=lambda _s: deps,
    )
    smoke = report.smoke
    assert smoke.routed_cost_tier == CostTier.LOCAL.value
    assert provider.calls[0].cost_tier == CostTier.LOCAL.value
    assert smoke.cost_krw == 0.0  # 로컬은 0원 확정(None 아님)
    assert spy.record_count == 1
    assert spy.flush_count == 1
    assert smoke.langfuse_recorded is True
    assert smoke.pipeline_note is not None and "폴백" in smoke.pipeline_note
    assert report.exit_code == 0


async def test_via_pipeline_skips_when_langfuse_unconfigured() -> None:
    """Langfuse 미설정이면 pipeline 호출 없이 graceful skip(exit 0) — provider 미호출."""
    provider = _FakePipelineProvider(GenerationResult(text="2"))
    spy = _SpyInnerSink()
    deps, _cache = _pipeline_deps(provider, spy)

    report = await lp.run_preflight(
        _settings(anthropic=True, langfuse=False),
        smoke=True,
        via_pipeline=True,
        cloud_provider_factory=_cloud_factory(
            _FakeCloud(configured=True, reachable=True, result=GenerationResult(text="x"))
        ),
        local_provider_factory=_local_factory(_FakeOllama(reachable=True)),
        pipeline_deps_factory=lambda _s: deps,
    )
    smoke = report.smoke
    assert smoke.ran is False
    assert smoke.via_pipeline is True
    assert smoke.skipped_reason is not None and "Langfuse 미설정" in smoke.skipped_reason
    assert provider.calls == []  # pipeline 호출 자체가 없다
    assert spy.record_count == 0 and spy.flush_count == 0
    assert report.exit_code == 0


async def test_via_pipeline_error_yields_exit_2() -> None:
    """pipeline 경유 스모크가 예외로 실패하면 종료 코드 2, 오류는 리포트에 흡수된다."""
    provider = _FakePipelineProvider(GenerationResult(text=""), raise_exc=RuntimeError("boom"))
    spy = _SpyInnerSink()
    deps, _cache = _pipeline_deps(provider, spy)

    report = await lp.run_preflight(
        _settings(anthropic=True, langfuse=True),
        smoke=True,
        via_pipeline=True,
        cloud_provider_factory=_cloud_factory(
            _FakeCloud(configured=True, reachable=True, result=GenerationResult(text="x"))
        ),
        local_provider_factory=_local_factory(_FakeOllama(reachable=True)),
        pipeline_deps_factory=lambda _s: deps,
    )
    assert report.smoke.error is not None and "boom" in report.smoke.error
    assert report.smoke.via_pipeline is True
    assert report.exit_code == 2


def test_capturing_trace_sink_forwards_and_captures() -> None:
    """_CapturingTraceSink는 record를 갈무리하며 내부로 전달하고 flush를 위임한다."""
    spy = _SpyInnerSink()
    sink = lp._CapturingTraceSink(spy)
    sink.record({"cost_krw": 1.5})
    sink.flush()
    assert sink.records == [{"cost_krw": 1.5}]
    assert spy.record_count == 1
    assert spy.flush_count == 1


def test_via_pipeline_stdout_render_shows_langfuse_and_tier() -> None:
    """via_pipeline 스모크 렌더는 라우팅 결과·Langfuse 기록 문구를 담는다."""
    report = lp.Report(
        cloud_configured=True,
        langfuse_configured=True,
        cloud_reachable=True,
        cloud_error=None,
        ollama_reachable=True,
        ollama_error=None,
        smoke=lp.SmokeResult(
            ran=True,
            via_pipeline=True,
            routed_cost_tier="cloud_mid",
            langfuse_recorded=True,
            pipeline_note="CLOUD_MID(sync) 목표 — 실 클라우드 1콜",
            cost_krw=1.617,
            input_tokens=100,
            output_tokens=50,
            latency_ms=1234.5,
            text_chars=1,
        ),
        exit_code=0,
    )
    text = lp._render_stdout(report)
    assert "pipeline.generate 경유" in text
    assert "cost_tier=cloud_mid" in text
    assert "l3_routing 이벤트 기록·flush 완료" in text


def test_main_dry_run_unconfigured_returns_zero(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """main: 키 없는 환경에서 스모크 skip·exit 0(드라이런 계약)."""

    def _fake_run(
        settings: object,
        *,
        smoke: bool,
        via_pipeline: bool = False,
        cloud_provider_factory: object = None,
        local_provider_factory: object = None,
        pipeline_deps_factory: object = None,
    ) -> lp.Report:
        # run_preflight을 가짜로 대체 — main의 파싱·출력·종료 코드 경로만 검증.
        return lp.Report(
            cloud_configured=False,
            langfuse_configured=False,
            cloud_reachable=None,
            cloud_error=None,
            ollama_reachable=False,
            ollama_error="down",
            smoke=lp.SmokeResult(
                ran=False, skipped_reason="anthropic 미설정(키 없음) — 스모크 skip"
            ),
            exit_code=0,
        )

    async def _fake_coro(*args: object, **kwargs: object) -> lp.Report:
        return _fake_run(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(lp, "run_preflight", _fake_coro)
    monkeypatch.setattr(lp, "Settings", lambda: object())
    code = lp.main([])
    captured = capsys.readouterr()
    assert code == 0
    assert "스모크 skip" in captured.out
