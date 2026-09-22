"""L3 파이프라인 단위테스트 — 라우팅→캐시→생성→관측 결선 (라이브 서비스 없음).

가짜 provider + 인메모리 스텁(InMemoryCache·RecordingTraceSink) + 가짜 큐로 캐시
적중/미스·QUALITY 비동기 큐잉·관측 기록을 검증한다.

설계 정본: docs/architecture/03a_l3_router_design.md §F.1·§F.2·§D.3.
"""

from __future__ import annotations

import pytest

from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.interfaces import InMemoryCache, RecordingTraceSink

# provider 반환형은 pipeline.GenerationResult(오케스트레이션 결과)와 이름이 겹쳐 별칭으로 구분.
from whymath_backend.l3.models import GenerationResult as ProviderResult
from whymath_backend.l3.models import RoutingDecision, RoutingRequest, Usage
from whymath_backend.l3.pipeline import (
    GenerationResult,
    QualityQueueUnavailableError,
    generate,
)
from whymath_backend.l3.pregenerate.validator import default_seed_validator
from whymath_backend.l3.router import cache_key_for


class RecordingProvider:
    """가짜 LLMProvider — 호출 기록 + 정해진 텍스트 반환."""

    def __init__(self, text: str = "원시 생성물") -> None:
        self._text = text
        self.calls: list[tuple[str, str, RoutingDecision]] = []

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
    ) -> ProviderResult:
        self.calls.append((prompt, system, decision))
        return ProviderResult(self._text)


class RecordingQueue:
    """가짜 AsyncJobQueue — enqueue payload 기록 + 정해진 job_id 반환.

    interfaces.AsyncJobQueue를 구조적으로 충족한다. `raises`를 주면 enqueue가 그 예외를
    던져 broker 다운(디스패치 실패)을 모사한다 — 파이프라인이 QualityQueueUnavailableError
    로 변환하는지 검증할 수 있게 한다.
    """

    def __init__(self, *, job_id: str = "job-123", raises: Exception | None = None) -> None:
        self._job_id = job_id
        self._raises = raises
        self.payloads: list[dict[str, object]] = []

    async def enqueue(self, payload: dict[str, object]) -> str:
        self.payloads.append(payload)
        if self._raises is not None:
            raise self._raises
        return self._job_id


def _sync_local_request() -> RoutingRequest:
    """LOCAL·동기로 라우팅되는 평이한 요청 (FAST/MID 동기)."""
    return RoutingRequest(
        task_type="explain",
        difficulty="easy",
        requires_reasoning=False,
        student_subscription="free",  # 무료 → LOCAL 강제
        sync=True,
    )


def _quality_request() -> RoutingRequest:
    """QUALITY(비동기)로 라우팅되는 요청 — ⑤ 자기검증."""
    return RoutingRequest(
        task_type="self_verify",
        difficulty="hard",
        requires_reasoning=True,
        student_subscription="free",
        sync=False,
        call_site="self_verify",
    )


class TestCacheMissPath:
    async def test_miss_calls_provider_and_caches(self) -> None:
        """미스 → provider 호출 → 캐시 저장 → cache_hit=False 기록."""
        provider = RecordingProvider(text="결과A")
        cache = InMemoryCache()
        trace = RecordingTraceSink()

        result = await generate(
            _sync_local_request(),
            "프롬프트",
            "시스템",
            provider=provider,
            cache=cache,
            trace=trace,
            cache_ttl_s=60,
        )

        assert isinstance(result, GenerationResult)
        assert result.text == "결과A"
        assert result.cache_hit is False
        assert len(provider.calls) == 1
        # 캐시에 결정 기반 키로 저장됐는지
        key = cache_key_for("프롬프트", "시스템", result.decision)
        assert await cache.get(key) == "결과A"
        # 관측 기록 1건, cache_hit False
        assert len(trace.records) == 1
        assert trace.records[0]["cache_hit"] is False
        # 공급 경로(03c §4) — 미스는 실제 생성이므로 generate.
        assert trace.records[0]["content_source"] == "generate"


class TestCacheHitPath:
    async def test_hit_skips_provider(self) -> None:
        """히트 → provider 미호출 → 캐시 값 반환 → cache_hit=True 기록."""
        provider = RecordingProvider(text="새값")
        cache = InMemoryCache()
        trace = RecordingTraceSink()
        req = _sync_local_request()

        # 사전 적재: 라우팅 결정 키로 캐시에 미리 넣는다.
        from whymath_backend.l3.router import Router

        decision = Router().route(req)
        key = cache_key_for("프롬프트", "시스템", decision)
        await cache.set(key, "캐시된값", 60)

        result = await generate(
            req,
            "프롬프트",
            "시스템",
            provider=provider,
            cache=cache,
            trace=trace,
        )

        assert result.text == "캐시된값"
        assert result.cache_hit is True
        assert provider.calls == []  # provider 미호출
        assert len(trace.records) == 1
        assert trace.records[0]["cache_hit"] is True
        # 공급 경로(03c §4) — 프롬프트-해시 적중은 2층 캐시의 (2).
        assert trace.records[0]["content_source"] == "prompt_cache"

    async def test_second_call_hits_after_first_miss(self) -> None:
        """같은 입력 2회 호출 → 1회는 미스, 2회는 히트(provider 1회만)."""
        provider = RecordingProvider(text="동일결과")
        cache = InMemoryCache()
        trace = RecordingTraceSink()
        req = _sync_local_request()

        r1 = await generate(req, "p", "s", provider=provider, cache=cache, trace=trace)
        r2 = await generate(req, "p", "s", provider=provider, cache=cache, trace=trace)

        assert r1.cache_hit is False
        assert r2.cache_hit is True
        assert r2.text == "동일결과"
        assert len(provider.calls) == 1  # 두 번째는 캐시


class TestQualityAsyncQueue:
    """QUALITY(async) 비동기 큐 경로 — enqueue→job_id, provider 미호출 (03a §D.3)."""

    async def test_queue_present_enqueues_and_returns_job_id(self) -> None:
        """큐 주입 → enqueue 1회 → status=queued·job_id 반환, provider/캐시 미사용."""
        provider = RecordingProvider(text="이건 안 쓰임")
        cache = InMemoryCache()
        trace = RecordingTraceSink()
        queue = RecordingQueue(job_id="job-xyz")

        result = await generate(
            _quality_request(),
            "검증할 풀이",
            "시스템",
            provider=provider,
            cache=cache,
            trace=trace,
            queue=queue,
        )

        assert isinstance(result, GenerationResult)
        assert result.is_queued is True
        assert result.status == "queued"
        assert result.job_id == "job-xyz"
        assert result.text == ""  # 비동기 — 텍스트는 즉시 없음(폴링)
        assert result.cache_hit is False
        # QUALITY는 동기 호출 절대 금지 — provider 미호출.
        assert provider.calls == []
        # enqueue 정확히 1회, payload는 1건.
        assert len(queue.payloads) == 1
        # 결정은 QUALITY(async)여야 한다.
        assert result.decision.mode == "async"
        assert result.decision.local_model == "quality"

    async def test_enqueued_payload_is_json_safe_and_complete(self) -> None:
        """enqueue payload는 prompt·system·decision(dict) — JSON 직렬화 가능해야 한다."""
        import json

        queue = RecordingQueue()
        result = await generate(
            _quality_request(),
            "프롬프트본문",
            "시스템본문",
            provider=RecordingProvider(),
            cache=InMemoryCache(),
            trace=RecordingTraceSink(),
            queue=queue,
        )
        payload = queue.payloads[0]
        assert payload["prompt"] == "프롬프트본문"
        assert payload["system"] == "시스템본문"
        # decision은 model_dump() dict — enum이 문자열로 직렬화(use_enum_values=True).
        decision_data = payload["decision"]
        assert isinstance(decision_data, dict)
        assert decision_data["cost_tier"] == "local"
        assert decision_data["local_model"] == "quality"
        assert decision_data["mode"] == "async"
        # payload 전체가 JSON 직렬화 가능(Celery JSON 직렬화 계약).
        assert json.loads(json.dumps(payload)) == payload
        # 재구성한 결정이 반환 결정과 동치(왕복 안전).
        assert RoutingDecision.model_validate(decision_data) == result.decision

    async def test_enqueue_records_trace_with_async_mode(self) -> None:
        """enqueue도 관측 기록한다 — mode=async, cache_hit=False (03a §F.2)."""
        trace = RecordingTraceSink()
        await generate(
            _quality_request(),
            "p",
            "s",
            provider=RecordingProvider(),
            cache=InMemoryCache(),
            trace=trace,
            queue=RecordingQueue(),
        )
        assert len(trace.records) == 1
        assert trace.records[0]["mode"] == "async"
        assert trace.records[0]["cache_hit"] is False

    async def test_queue_none_raises_named_error(self) -> None:
        """큐 미주입(미구성) → QualityQueueUnavailableError, provider 미호출(동기 폴백 금지)."""
        provider = RecordingProvider()
        with pytest.raises(QualityQueueUnavailableError):
            await generate(
                _quality_request(),
                "p",
                "s",
                provider=provider,
                cache=InMemoryCache(),
                trace=RecordingTraceSink(),
                # queue 미주입 → 기본 None
            )
        assert provider.calls == []  # 동기 호출 금지

    async def test_enqueue_failure_raises_named_error(self) -> None:
        """enqueue 자체 실패(broker 다운) → QualityQueueUnavailableError로 변환(API 503)."""
        provider = RecordingProvider()
        queue = RecordingQueue(raises=ConnectionError("broker refused"))
        with pytest.raises(QualityQueueUnavailableError) as exc_info:
            await generate(
                _quality_request(),
                "p",
                "s",
                provider=provider,
                cache=InMemoryCache(),
                trace=RecordingTraceSink(),
                queue=queue,
            )
        # 원인이 보존돼야 한다(디버깅) — broker 도달 실패의 흔적.
        assert exc_info.value.__cause__ is not None
        assert provider.calls == []  # 동기 호출 금지
        assert len(queue.payloads) == 1  # 시도는 했음

    async def test_queue_satisfies_async_job_queue_protocol(self) -> None:
        """가짜 큐가 AsyncJobQueue Protocol을 구조적으로 충족하는지 확인(테스트 위생)."""
        from whymath_backend.l3.interfaces import AsyncJobQueue

        assert isinstance(RecordingQueue(), AsyncJobQueue)


class TestShadowValidation:
    """런타임 shadow 검증(비차단·opt-in) — 미스 생성물의 환각 신호를 trace에 기록.

    반환 텍스트·캐시는 *불변*(원시 출력은 검증 전이며 학생 노출 차단은 L4/L5 책임).
    """

    async def test_clean_output_records_none_signal(self) -> None:
        """검증 통과 출력 → validation_signal=None, 텍스트 불변."""
        provider = RecordingProvider(text="정답은 2 + 2 = 4 입니다")
        trace = RecordingTraceSink()
        result = await generate(
            _sync_local_request(),
            "p",
            "s",
            provider=provider,
            cache=InMemoryCache(),
            trace=trace,
            validator=default_seed_validator(),
        )
        assert result.text == "정답은 2 + 2 = 4 입니다"
        assert trace.records[0]["validation_signal"] is None
        # 호출자도 신호를 프로그램적으로 읽을 수 있다(trace와 같은 값).
        assert result.validation_signal is None

    async def test_false_output_records_signal_but_nonblocking(self) -> None:
        """거짓 산술 출력 → validation_signal에 사유 기록, 그러나 텍스트·캐시는 *그대로*."""
        provider = RecordingProvider(text="2 + 2 = 5")
        cache = InMemoryCache()
        trace = RecordingTraceSink()
        result = await generate(
            _sync_local_request(),
            "프롬프트",
            "시스템",
            provider=provider,
            cache=cache,
            trace=trace,
            validator=default_seed_validator(),
        )
        # 비차단: 반환 텍스트는 원시 출력 그대로(차단·치환 없음).
        assert result.text == "2 + 2 = 5"
        assert result.cache_hit is False
        # 캐시에도 그대로 적재(shadow는 관측 전용 — 캐시 동작 불변).
        key = cache_key_for("프롬프트", "시스템", result.decision)
        assert await cache.get(key) == "2 + 2 = 5"
        # 그러나 환각 신호는 *조용히 넘어가지 않고* 관측에 남는다(CLAUDE.md).
        signal = trace.records[0]["validation_signal"]
        assert isinstance(signal, str) and "arithmetic error" in signal
        # 그리고 호출자도 같은 신호를 GenerationResult로 직접 받는다(관측 싱크에만 의존 X).
        assert result.validation_signal == signal

    async def test_no_validator_signal_is_none(self) -> None:
        """validator 미주입(기본) → 검증 미실행 → validation_signal=None(오버헤드 0)."""
        provider = RecordingProvider(text="5 < 3 라는 거짓 부등식")
        trace = RecordingTraceSink()
        result = await generate(
            _sync_local_request(),
            "p",
            "s",
            provider=provider,
            cache=InMemoryCache(),
            trace=trace,
            # validator 미주입
        )
        assert trace.records[0]["validation_signal"] is None
        assert result.validation_signal is None

    async def test_cache_hit_not_shadow_validated(self) -> None:
        """캐시 히트 경로는 shadow 검증 대상이 아니다(미스 생성물만) — provider 미호출."""
        provider = RecordingProvider(text="안 쓰임")
        cache = InMemoryCache()
        trace = RecordingTraceSink()
        req = _sync_local_request()
        from whymath_backend.l3.router import Router

        decision = Router().route(req)
        key = cache_key_for("p", "s", decision)
        await cache.set(key, "8 != 8", 60)  # 거짓이지만 히트는 검증 안 함

        result = await generate(
            req,
            "p",
            "s",
            provider=provider,
            cache=cache,
            trace=trace,
            validator=default_seed_validator(),
        )
        assert result.cache_hit is True
        assert provider.calls == []
        assert trace.records[0]["validation_signal"] is None
        assert result.validation_signal is None

    async def test_skip_cache_on_signal_omits_flagged_output(self) -> None:
        """skip_cache_on_signal=True + 거짓 출력 → 캐시 미적재, 그러나 텍스트·신호는 반환."""
        provider = RecordingProvider(text="2 + 2 = 5")
        cache = InMemoryCache()
        result = await generate(
            _sync_local_request(),
            "프롬프트",
            "시스템",
            provider=provider,
            cache=cache,
            trace=RecordingTraceSink(),
            validator=default_seed_validator(),
            skip_cache_on_signal=True,
        )
        # 캐시에는 *남지 않는다*(증명된 거짓 콘텐츠 캐시 위생).
        key = cache_key_for("프롬프트", "시스템", result.decision)
        assert await cache.get(key) is None
        # 그러나 호출자에겐 원시 출력+신호가 그대로 간다(비차단·캐시만 건너뜀).
        assert result.text == "2 + 2 = 5"
        assert isinstance(result.validation_signal, str)
        assert "arithmetic error" in result.validation_signal

    async def test_skip_cache_on_signal_keeps_clean_output(self) -> None:
        """skip_cache_on_signal=True여도 신호 없으면(통과) 정상 적재."""
        provider = RecordingProvider(text="2 + 2 = 4")
        cache = InMemoryCache()
        result = await generate(
            _sync_local_request(),
            "프롬프트",
            "시스템",
            provider=provider,
            cache=cache,
            trace=RecordingTraceSink(),
            validator=default_seed_validator(),
            skip_cache_on_signal=True,
        )
        key = cache_key_for("프롬프트", "시스템", result.decision)
        assert await cache.get(key) == "2 + 2 = 4"  # 통과 → 적재됨
        assert result.validation_signal is None

    async def test_skip_disabled_caches_even_when_flagged(self) -> None:
        """기본(skip=False) → 신호 나도 캐시 적재(기존 동작 불변·비차단)."""
        provider = RecordingProvider(text="5 < 3")
        cache = InMemoryCache()
        result = await generate(
            _sync_local_request(),
            "프롬프트",
            "시스템",
            provider=provider,
            cache=cache,
            trace=RecordingTraceSink(),
            validator=default_seed_validator(),
            # skip_cache_on_signal 미지정 → 기본 False
        )
        key = cache_key_for("프롬프트", "시스템", result.decision)
        assert await cache.get(key) == "5 < 3"  # 적재됨(기존 동작)
        assert isinstance(result.validation_signal, str)

    async def test_skip_without_validator_no_effect(self) -> None:
        """validator 미주입 → 신호 없음 → skip=True여도 정상 적재(무효과)."""
        provider = RecordingProvider(text="8 != 8")
        cache = InMemoryCache()
        result = await generate(
            _sync_local_request(),
            "프롬프트",
            "시스템",
            provider=provider,
            cache=cache,
            trace=RecordingTraceSink(),
            skip_cache_on_signal=True,
            # validator 미주입 → 신호 None → skip 무효과
        )
        key = cache_key_for("프롬프트", "시스템", result.decision)
        assert await cache.get(key) == "8 != 8"
        assert result.validation_signal is None

    async def test_queued_result_signal_is_none(self) -> None:
        """비동기(QUALITY) 큐잉 결과는 텍스트가 없으므로 validation_signal=None."""
        result = await generate(
            _quality_request(),
            "p",
            "s",
            provider=RecordingProvider(),
            cache=InMemoryCache(),
            trace=RecordingTraceSink(),
            queue=RecordingQueue(),
            validator=default_seed_validator(),
        )
        assert result.is_queued is True
        assert result.validation_signal is None


class TestCloudRejectedThroughProvider:
    async def test_cloud_decision_rejected_by_provider(self) -> None:
        """클라우드로 라우팅된 동기 결정은 (OllamaProvider 류) provider가 거부.

        파이프라인은 QUALITY만 차단하고 클라우드는 provider 경계로 흘려보낸다.
        여기서는 클라우드를 거부하는 가짜 provider로 그 계약을 검증한다.
        """

        class CloudRejectingProvider:
            async def generate(
                self, prompt: str, system: str, decision: RoutingDecision
            ) -> ProviderResult:
                from whymath_backend.l3.models import CostTier
                from whymath_backend.l3.router import _as_cost_tier

                if _as_cost_tier(decision.cost_tier) is not CostTier.LOCAL:
                    raise ValueError("로컬 결정만 처리")
                return ProviderResult("ok")

        # killer 난이도 + premium → CLOUD_HIGH로 라우팅 (예산 충분).
        cloud_req = RoutingRequest(
            task_type="prove",
            difficulty="killer",
            requires_reasoning=True,
            student_subscription="gifted",
            budget_krw=10000.0,
            sync=True,
            # 반출 가능 등급 명시 — 이 테스트가 재는 것은 provider 거부 경로이지 데이터 등급
            # 게이트(EOS-59)가 아니다. 미지정이면 fail-closed로 LOCAL이 되어 축이 바뀐다.
            data_licenses=SELF_AUTHORED_CORPUS,
        )
        with pytest.raises(ValueError, match="로컬 결정만"):
            await generate(
                cloud_req,
                "p",
                "s",
                provider=CloudRejectingProvider(),
                cache=InMemoryCache(),
                trace=RecordingTraceSink(),
            )


# ══════════════════════════════════════════════════════════════════════
# 실측 usage·비용 계측 (S1 게이트 ② — hermetic, 라이브 키 불요)
# ══════════════════════════════════════════════════════════════════════
class UsageProvider:
    """가짜 provider — 정해진 텍스트 + 실측 usage(토큰·지연)를 반환.

    실제 Anthropic/Ollama provider가 usage를 포착해 돌려주는 계약을 모사한다 —
    파이프라인이 usage를 trace(cost_krw·토큰·지연)로 흘리는 배선을 검증한다.
    """

    def __init__(self, *, text: str = "결과", usage: Usage | None = None) -> None:
        self._text = text
        self._usage = usage
        self.calls: list[tuple[str, str, RoutingDecision]] = []

    async def generate(self, prompt: str, system: str, decision: RoutingDecision) -> ProviderResult:
        self.calls.append((prompt, system, decision))
        return ProviderResult(self._text, usage=self._usage)


def _cloud_request() -> RoutingRequest:
    """CLOUD_HIGH로 라우팅되는 요청 — killer·gifted·예산 충분."""
    return RoutingRequest(
        task_type="prove",
        difficulty="killer",
        requires_reasoning=True,
        student_subscription="gifted",
        budget_krw=10000.0,
        sync=True,
        # 반출 가능 등급 명시 — 이 헬퍼는 *클라우드 실측 계측*을 재는 좌석이라 데이터 등급
        # 게이트(EOS-59)를 중립화해야 원래 축을 잰다(등급 축은 test_data_export_policy).
        data_licenses=SELF_AUTHORED_CORPUS,
    )


class TestActualUsageInstrumentation:
    """provider usage → trace 실측 필드(cost_krw·토큰·지연) 배선 검증."""

    async def test_cloud_miss_records_positive_actual_cost_and_tokens(self) -> None:
        """클라우드 미스 → cost_krw>0(토큰 산정)·input/output_tokens·latency_ms 실측 기록."""
        usage = Usage(input_tokens=1000, output_tokens=1000, latency_ms=2500.0)
        trace = RecordingTraceSink()

        await generate(
            _cloud_request(),
            "증명 프롬프트",
            "시스템",
            provider=UsageProvider(text="증명", usage=usage),
            cache=InMemoryCache(),
            trace=trace,
            cache_ttl_s=60,
        )

        rec = trace.records[0]
        # CLOUD_HIGH(opus $5/$25 per 1M)·1K+1K 토큰·1540원/USD → 46.2원 (router.py 상수 유도).
        assert rec["cost_krw"] == pytest.approx(46.2)
        assert rec["input_tokens"] == 1000
        assert rec["output_tokens"] == 1000
        assert rec["latency_ms"] == 2500.0
        # 추정(est_*)은 실측과 *별개 키*로 공존한다 — 구분 유지(03a §F.2).
        # est는 단가표×가정 토큰(S1-13 실측 보정 74+358)에서 유도된다 — 이 호출의 실측은
        # 1K+1K(46.2원)라 est(14.3528)와 *다른 값*: 추정 vs 실측 분리가 값으로도 드러난다.
        from whymath_backend.l3.models import CostTier
        from whymath_backend.l3.router import CLOUD_MIN_COST_KRW

        assert rec["est_cost_krw"] == pytest.approx(
            CLOUD_MIN_COST_KRW[(CostTier.CLOUD_HIGH, "anthropic")]
        )  # 라우터 추정(CLOUD_MIN_COST_KRW·실측 보정 유도 — 상수 참조라 재보정에 강건)
        assert rec["cost_tier"] == "cloud_high"

    async def test_local_miss_records_zero_cost_with_tokens(self) -> None:
        """로컬 미스 → cost_krw=0.0 확정 + 토큰·지연 실측 기록(0원이어도 토큰은 실측)."""
        usage = Usage(input_tokens=120, output_tokens=340, latency_ms=980.5)
        trace = RecordingTraceSink()

        await generate(
            _sync_local_request(),
            "프롬프트",
            "시스템",
            provider=UsageProvider(usage=usage),
            cache=InMemoryCache(),
            trace=trace,
            cache_ttl_s=60,
        )

        rec = trace.records[0]
        assert rec["cost_krw"] == 0.0  # 로컬=0원 확정
        assert rec["input_tokens"] == 120
        assert rec["output_tokens"] == 340
        assert rec["latency_ms"] == 980.5

    async def test_cloud_unknown_tokens_records_none_cost_not_zero(self) -> None:
        """클라우드인데 토큰 미상 → cost_krw=None('미상'≠'0원' — 지어내지 않음)."""
        usage = Usage(input_tokens=None, output_tokens=None, latency_ms=1000.0)
        trace = RecordingTraceSink()

        await generate(
            _cloud_request(),
            "p",
            "s",
            provider=UsageProvider(usage=usage),
            cache=InMemoryCache(),
            trace=trace,
            cache_ttl_s=60,
        )

        rec = trace.records[0]
        assert rec["cost_krw"] is None  # 0.0이 아님!
        assert rec["latency_ms"] == 1000.0

    async def test_usage_none_provider_records_none_actuals(self) -> None:
        """usage 미노출 provider(테스트 가짜 등) → 실측 4필드 전부 None(하위호환·정직)."""
        trace = RecordingTraceSink()

        await generate(
            _sync_local_request(),
            "p",
            "s",
            provider=UsageProvider(usage=None),
            cache=InMemoryCache(),
            trace=trace,
            cache_ttl_s=60,
        )

        rec = trace.records[0]
        assert rec["cost_krw"] is None
        assert rec["input_tokens"] is None
        assert rec["output_tokens"] is None
        assert rec["latency_ms"] is None

    async def test_cache_hit_records_zero_cost_and_no_tokens(self) -> None:
        """캐시 적중 → cost_krw=0.0 확정(신규 호출 없음)·토큰/지연 None(이 요청 실측 없음)."""
        usage = Usage(input_tokens=50, output_tokens=60, latency_ms=900.0)
        provider = UsageProvider(usage=usage)
        cache = InMemoryCache()
        trace = RecordingTraceSink()

        await generate(
            _sync_local_request(),
            "p",
            "s",
            provider=provider,
            cache=cache,
            trace=trace,
            cache_ttl_s=60,
        )
        await generate(
            _sync_local_request(),
            "p",
            "s",
            provider=provider,
            cache=cache,
            trace=trace,
            cache_ttl_s=60,
        )

        hit = trace.records[1]
        assert hit["cache_hit"] is True
        assert hit["cost_krw"] == 0.0  # 적중=신규 호출 없음=0원 확정
        assert hit["input_tokens"] is None  # 이 요청에서 실측된 토큰 없음
        assert hit["latency_ms"] is None
        assert len(provider.calls) == 1  # 두 번째는 provider 미호출

    async def test_async_enqueue_records_zero_cost(self) -> None:
        """비동기(QUALITY) enqueue → cost_krw=0.0(로컬 MoE=0원·생성 실측은 워커 몫)."""
        trace = RecordingTraceSink()

        result = await generate(
            _quality_request(),
            "p",
            "s",
            provider=UsageProvider(),
            cache=InMemoryCache(),
            trace=trace,
            queue=RecordingQueue(),
        )

        assert result.is_queued
        rec = trace.records[0]
        assert rec["mode"] == "async"
        assert rec["cost_krw"] == 0.0
        assert rec["input_tokens"] is None  # enqueue 시점엔 생성이 없다
