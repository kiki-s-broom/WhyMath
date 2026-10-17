"""CachePrewarmer 관측 결선(OPS-109) — 사전적재 호출이 trace에 남고, 원가 좌석이 맞다.

배경: 사전적재기는 provider를 직접 부르므로 파이프라인이 해 주는 `l3_routing` trace 기록을 받지
못했다. 그 부재는 설계가 아니라 공백이었고(같은 저작 계열 `llm_generator`는 이미 보정했다), 같은
호출의 생성 로그 원가는 좌석을 생략해 `SERVING_CLOUD_SEAT`(anthropic) 단가로 적혀 openrouter 호출을
22.5배(CLOUD_MID 실측)로, 단가 미등재 좌석(CLOUD_HIGH)은 '미측정'이어야 할 값을 지어낸 금액으로
기록했다.

검증 설계(실패 주입으로 변별력을 확인한 케이스만 둔다):
  - **오라클은 구현이 아닌 순수 함수**: 기대 원가는 `actual_cost_krw/usd`를 좌석 명시로 직접 불러 얻는다
    (구현이 부르는 경로와 독립 — 좌석을 틀리게 읽으면 값이 갈라진다). 좌석 간 값이 실제로 다른지
    (`!=`)도 전제로 단언한다 — 같으면 좌석 오류가 있어도 통과한다.
  - **기록하지 않아야 할 경로**(인제스트·스킵·provider 예외·async)를 명시해 과기록을 막는다.
  - **전제 동결**: 저작 표지는 "이 클래스를 만드는 프로덕션 호출부가 배치 CLI 하나뿐"이라는 사실에 기댄다
    — 그 사실을 소스 스캔으로 고정한다.
"""

from __future__ import annotations

import ast
import asyncio
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

import whymath_backend
from whymath_backend.l3.interfaces import InMemoryCache, SurfaceTaggingTraceSink
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    RoutingDecision,
    RoutingRequest,
    Usage,
)
from whymath_backend.l3.pregenerate import __main__ as pregen_cli
from whymath_backend.l3.pregenerate.models import PregenItem, ValidationSignal
from whymath_backend.l3.pregenerate.prewarmer import CachePrewarmer
from whymath_backend.l3.router import (
    USD_TO_KRW,
    Router,
    actual_cost_krw,
    actual_cost_usd,
    cache_key_for,
)
from whymath_backend.l3.trace.langfuse_sink import LangfuseSink
from whymath_backend.schema.provenance import GenerationLog

_USAGE = Usage(input_tokens=1_000_000, output_tokens=1_000_000, latency_ms=42.0)
_SECRET_PROMPT = "비밀프롬프트원문-XYZ"


# ──────────────────────────────────────────────────────────────────────
# 대역 — 네트워크 0
# ──────────────────────────────────────────────────────────────────────
class _Provider:
    """스크립트 provider — `seat`를 주면 `cloud_seat` 표면을 노출하고 안 주면 표면 자체가 없다."""

    _NO_SURFACE: Any = object()

    def __init__(
        self,
        *,
        seat: Any = _NO_SURFACE,
        raises: Exception | None = None,
        usage: Usage | None = _USAGE,
    ) -> None:
        if seat is not _Provider._NO_SURFACE:
            self.cloud_seat = seat  # served_cloud_seat 가 읽는 표면(None=미상)
        self._raises = raises
        self._usage = usage
        self.calls = 0

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
        if self._raises is not None:
            raise self._raises
        return GenerationResult("생성응답", usage=self._usage)


class _Pass:
    def validate(self, item: PregenItem, response: str) -> None:
        return None


class _Fail:
    def validate(self, item: PregenItem, response: str) -> ValidationSignal:
        return ValidationSignal(kind="other", reason="테스트 실패 사유")


class _FixedRouter:
    """항상 같은 결정을 돌려주는 라우터 대역 — 클라우드 결정을 만들기 위해 쓴다."""

    def __init__(self, decision: RoutingDecision) -> None:
        self._decision = decision

    def route(self, req: RoutingRequest) -> RoutingDecision:
        return self._decision


class _SpyTrace:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.flushed = 0

    def record(self, fields: dict[str, object]) -> None:
        self.events.append(dict(fields))

    def flush(self) -> None:
        self.flushed += 1


class _RaisingTrace:
    def record(self, fields: dict[str, object]) -> None:
        raise RuntimeError(f"sink down {_SECRET_PROMPT}")

    def flush(self) -> None:
        raise ValueError("flush down")


def _request() -> RoutingRequest:
    return RoutingRequest(
        task_type="explain",
        difficulty="easy",
        requires_reasoning=False,
        student_subscription="free",
        sync=True,
    )


def _item(**overrides: object) -> PregenItem:
    base: dict[str, object] = {"prompt": _SECRET_PROMPT, "system": "시스템", "request": _request()}
    base.update(overrides)
    return PregenItem(**base)  # type: ignore[arg-type]


def _cloud(tier: CostTier) -> RoutingDecision:
    return RoutingDecision(cost_tier=tier, mode="sync", reason="t", est_latency_ms=3000)


def _run(
    items: list[PregenItem],
    *,
    provider: _Provider | None = None,
    trace: object | None = None,
    validator: object | None = None,
    router: object | None = None,
    cache: InMemoryCache | None = None,
    genlogs: list[GenerationLog] | None = None,
) -> tuple[CachePrewarmer, Any]:
    prewarmer = CachePrewarmer(
        provider=provider if provider is not None else _Provider(),  # type: ignore[arg-type]
        cache=cache if cache is not None else InMemoryCache(),
        validator=validator if validator is not None else _Pass(),  # type: ignore[arg-type]
        router=router,  # type: ignore[arg-type]
        generation_log_sink=genlogs.append if genlogs is not None else None,
        trace=trace,  # type: ignore[arg-type]
    )
    return prewarmer, asyncio.run(prewarmer.prewarm(items))


class TestTraceIsRecorded:
    def test_generated_item_records_one_authoring_event(self) -> None:
        """provider 생성 1건 = 이벤트 1건 · 저작 표지 · 실측 토큰 · 로컬 0원 확정."""
        spy = _SpyTrace()

        _run(
            [_item()],
            provider=_Provider(usage=Usage(input_tokens=50, output_tokens=120)),
            trace=spy,
        )

        assert len(spy.events) == 1
        event = spy.events[0]
        assert event["traffic_surface"] == "authoring"
        assert event["input_tokens"] == 50 and event["output_tokens"] == 120
        assert event["cost_krw"] == 0.0  # LOCAL 0원 확정(미상 None 과 구분)
        assert event["cloud_seat"] is None  # LOCAL 은 좌석이 없다
        assert event["cache_hit"] is False

    @pytest.mark.parametrize(
        "case",
        ["ingest", "skipped_exists", "provider_raises", "async_decision"],
    )
    def test_no_llm_call_means_no_event(self, case: str) -> None:
        """생성 호출이 없었던 항목은 기록하지 않는다 — 과기록은 비용을 부풀린다."""
        spy = _SpyTrace()
        cache = InMemoryCache()
        provider = _Provider()
        router: object | None = None
        item = _item()
        if case == "ingest":
            item = _item(precomputed_response="외부 시드 응답")
        elif case == "skipped_exists":
            decision = Router().route(item.request)
            asyncio.run(
                cache.set(cache_key_for(item.prompt, item.system, decision), "이미 있음", 0)
            )
        elif case == "provider_raises":
            provider = _Provider(raises=RuntimeError("provider down"))
        elif case == "async_decision":
            router = _FixedRouter(
                RoutingDecision(
                    cost_tier=CostTier.LOCAL,
                    local_model="quality",  # type: ignore[arg-type]
                    mode="async",
                    reason="t",
                    est_latency_ms=3000,
                )
            )

        _, report = _run([item], provider=provider, trace=spy, cache=cache, router=router)

        assert spy.events == [], f"{case}: 호출이 없었는데 기록이 남았다"
        if case != "ingest":
            assert report.items[0].status in {"skipped_exists", "error"}, case

    def test_validation_failure_still_records_because_cost_was_incurred(self) -> None:
        """응답이 왔다 = 비용이 발생했다 — 검증 실패여도 기록한다(성공 경로만 보는 계측 금지)."""
        spy = _SpyTrace()

        _, report = _run([_item()], trace=spy, validator=_Fail())

        assert report.items[0].status == "failed_validation"
        assert len(spy.events) == 1

    def test_sink_failure_never_breaks_the_batch_and_logs_only_the_type_name(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """관측 장애는 배치를 깨지 않고, 경고에는 예외 타입명만 남는다(원문·메시지 미노출)."""
        with caplog.at_level(logging.WARNING, logger="whymath.l3.pregenerate.prewarmer"):
            _, report = _run([_item(), _item(prompt="두번째")], trace=_RaisingTrace())

        assert [i.status for i in report.items] == ["written", "written"]
        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "RuntimeError" in messages
        assert _SECRET_PROMPT not in messages and "sink down" not in messages


class TestDefaultAndFlush:
    def test_default_trace_is_langfuse_wrapped_with_the_authoring_surface(self) -> None:
        """trace 를 안 주면 LangfuseSink 가 기본이고 저작 표지로 감싸진다(끄는 옵션 없음)."""
        prewarmer = CachePrewarmer(provider=_Provider(), cache=InMemoryCache(), validator=_Pass())  # type: ignore[arg-type]

        sink = prewarmer._trace
        assert isinstance(sink, SurfaceTaggingTraceSink)
        assert sink.surface.value == "authoring"
        assert isinstance(sink._inner, LangfuseSink)

    def test_injected_trace_is_wrapped_too(self) -> None:
        spy = _SpyTrace()
        prewarmer = CachePrewarmer(
            provider=_Provider(), cache=InMemoryCache(), validator=_Pass(), trace=spy  # type: ignore[arg-type]
        )

        assert isinstance(prewarmer._trace, SurfaceTaggingTraceSink)
        assert prewarmer._trace._inner is spy

    def test_flush_trace_delegates_and_swallows_errors_with_the_type_name(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        spy = _SpyTrace()
        ok, _ = _run([], trace=spy)
        ok.flush_trace()
        assert spy.flushed == 1

        bad, _ = _run([], trace=_RaisingTrace())
        with caplog.at_level(logging.WARNING, logger="whymath.l3.pregenerate.prewarmer"):
            bad.flush_trace()  # 예외 전파 금지
        assert "ValueError" in " ".join(r.getMessage() for r in caplog.records)


class TestCostSeatIsReadFromTheProvider:
    """원가 좌석은 설정이 아니라 꽂힌 provider 에서 읽는다 — trace 와 생성 로그가 같은 값을 말한다."""

    def _record(
        self, tier: CostTier, provider: _Provider
    ) -> tuple[dict[str, object], GenerationLog, RoutingDecision]:
        spy = _SpyTrace()
        logs: list[GenerationLog] = []
        decision = _cloud(tier)
        _run([_item()], provider=provider, trace=spy, router=_FixedRouter(decision), genlogs=logs)
        return spy.events[0], logs[0], decision

    def test_openrouter_seat_prices_with_the_openrouter_table(self) -> None:
        event, log, decision = self._record(CostTier.CLOUD_MID, _Provider(seat="openrouter"))

        want_krw = actual_cost_krw(decision, _USAGE, seat="openrouter")
        want_usd = actual_cost_usd(decision, _USAGE, seat="openrouter")
        assert want_krw is not None and want_usd is not None
        # 전제 — 좌석이 값을 실제로 바꾼다(같으면 좌석 오류가 있어도 통과한다).
        assert want_usd != actual_cost_usd(decision, _USAGE, seat="anthropic")
        assert event["cost_krw"] == pytest.approx(want_krw)
        assert event["cloud_seat"] == "openrouter"
        assert log.cost_usd == pytest.approx(want_usd)

    def test_trace_and_generation_log_agree_on_the_cost(self) -> None:
        """두 채널이 서로 다른 원가를 말하지 않는다(USD×환율 = KRW)."""
        event, log, _ = self._record(CostTier.CLOUD_MID, _Provider(seat="openrouter"))

        assert log.cost_usd is not None
        assert float(event["cost_krw"]) == pytest.approx(log.cost_usd * USD_TO_KRW)  # type: ignore[arg-type]

    def test_anthropic_seat_prices_with_the_anthropic_table(self) -> None:
        event, log, decision = self._record(CostTier.CLOUD_MID, _Provider(seat="anthropic"))

        assert event["cost_krw"] == pytest.approx(
            actual_cost_krw(decision, _USAGE, seat="anthropic")
        )
        assert event["cloud_seat"] == "anthropic"
        assert log.cost_usd == pytest.approx(actual_cost_usd(decision, _USAGE, seat="anthropic"))

    def test_unlisted_price_is_unmeasured_not_invented(self) -> None:
        """단가 미등재 좌석은 None('미측정') — 다른 좌석의 금액으로 채우지 않는다."""
        decision = _cloud(CostTier.CLOUD_HIGH)
        # 전제 — 오라클이 실제로 None 이고 anthropic 에는 값이 있다(없으면 이 테스트가 공허하다).
        assert actual_cost_usd(decision, _USAGE, seat="openrouter") is None
        assert actual_cost_usd(decision, _USAGE, seat="anthropic") is not None

        event, log, _ = self._record(CostTier.CLOUD_HIGH, _Provider(seat="openrouter"))

        assert event["cost_krw"] is None
        assert log.cost_usd is None

    def test_unknown_seat_is_unmeasured(self) -> None:
        """좌석 표면은 있으나 미상(None)이면 anthropic 으로 접지 않고 '미측정'으로 남긴다."""
        event, log, _ = self._record(CostTier.CLOUD_MID, _Provider(seat=None))

        assert event["cost_krw"] is None
        assert event["cloud_seat"] is None
        assert log.cost_usd is None

    def test_provider_without_a_seat_surface_keeps_the_legacy_meaning(self) -> None:
        """좌석 표면이 없는 provider(테스트 가짜·레거시)는 종전 의미(서빙 좌석 anthropic)를 유지한다."""
        event, _, decision = self._record(CostTier.CLOUD_MID, _Provider())

        assert event["cost_krw"] == pytest.approx(
            actual_cost_krw(decision, _USAGE, seat="anthropic")
        )

    def test_unmetered_cloud_call_is_unmeasured_not_zero(self) -> None:
        """usage 가 없는 클라우드 호출은 0원이 아니라 None 이다('미상'과 '0원 확정'의 구분)."""
        event, log, _ = self._record(CostTier.CLOUD_MID, _Provider(seat="openrouter", usage=None))

        assert event["cost_krw"] is None
        assert log.cost_usd is None

    def test_cloud_call_with_unknown_tokens_is_unmeasured_not_zero(self) -> None:
        """토큰이 미상인 클라우드 호출도 0원이 아니라 None 이다 — '토큰 미상' 분기의 반례 픽스처."""
        unknown = Usage(input_tokens=None, output_tokens=None)

        event, log, _ = self._record(
            CostTier.CLOUD_MID, _Provider(seat="openrouter", usage=unknown)
        )

        assert event["cost_krw"] is None
        assert log.cost_usd is None


class TestPremiseAndCli:
    def test_only_the_batch_cli_constructs_the_prewarmer_in_production(self) -> None:
        """저작 표지의 근거 — 프로덕션에서 이 클래스를 만드는 곳은 배치 CLI 하나뿐이다.

        서빙 경로가 이 클래스를 만들기 시작하면 이 테스트가 red 가 되어, 표지(`authoring`)를 다시
        판정하게 한다(서빙 비용이 저작으로 위장되는 것을 막는다).
        """
        root = Path(whymath_backend.__file__).resolve().parent
        constructors: set[str] = set()
        scanned = 0
        for path in sorted(root.rglob("*.py")):
            scanned += 1
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "CachePrewarmer"
                ):
                    constructors.add(path.relative_to(root).as_posix())

        assert scanned > 100, "스캔 루트가 틀렸다 — 거의 못 읽었다"
        assert constructors == {"l3/pregenerate/__main__.py"}

    @pytest.mark.parametrize("prewarm_raises", [False, True])
    def test_cli_flushes_the_trace_even_when_the_batch_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        prewarm_raises: bool,
    ) -> None:
        """Langfuse 는 배치 전송이라 짧게 끝나는 CLI 는 flush 로 확정해야 한다 — 예외 종료에도."""
        flushed: list[int] = []
        monkeypatch.setattr(CachePrewarmer, "flush_trace", lambda self: flushed.append(1))
        if prewarm_raises:

            async def _boom(self: CachePrewarmer, *a: object, **k: object) -> None:
                raise RuntimeError("router down")

            monkeypatch.setattr(CachePrewarmer, "prewarm", _boom)
        specs = tmp_path / "specs.jsonl"
        specs.write_text(_item().model_dump_json() + "\n", encoding="utf-8")

        coro = pregen_cli._run(
            specs,
            overwrite=False,
            ttl_seconds=0,
            min_length=1,
            provider=_Provider(),  # type: ignore[arg-type]
            cache=InMemoryCache(),
        )
        if prewarm_raises:
            with pytest.raises(RuntimeError):
                asyncio.run(coro)
        else:
            assert asyncio.run(coro) == 0

        assert flushed == [1]
