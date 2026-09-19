"""WH-1 학생 대면 LLM 호출의 **단일 경유 좌석** — 라우터·캐시·관측 결선(OPS-36).

`l4/misconception/judge_seam.L3JudgeSeam`의 형제다. judge가 그랬듯 WH-1 하네스도 지금까지
`Router().route()`로 결정만 받고 `provider.generate(...)`를 **직접** 불렀다 — 라우터는 경유했으나
`l3.pipeline`을 우회했으므로 Langfuse `l3_routing` 이벤트도 캐시도 실적재되지 않았다. 그 결과
2026-07-20 GA 이후 *학생 대면 LLM 트래픽 전량*이 비용 게이트② 표본에서 구조적으로 빠져 있었다
(관측이 죽어도 화면은 정상이라 무증상 — langfuse v2 8일 전멸과 동형).

이 모듈은 WH-1의 L3 의존을 **한 자리에** 가둔다. 정책(`wh1_llm_policy`)·프로즈(`wh1_prose`)는
이 좌석만 부르고 `l3.pipeline`·`Router`를 직접 알지 않는다.

**교체 가능성을 주석이 아니라 타입으로 둔다** — 소비자가 의존하는 것은 `Wh1LlmSeam` 구현체가
아니라 `Wh1Generation` Protocol이다. 내부를 다른 라우팅·다른 파이프라인으로 갈아끼워도
호출 계약(`generate(req, prompt, system, ...) -> str`)은 그대로다.

**경계(CLAUDE.md)**: 이 좌석이 돌려주는 텍스트는 *검증 전 원시 출력*이다. 학생에게 닿기 전에
반드시 하네스 불변식·게이트·톤필터를 통과해야 한다 — 이 모듈은 *운반*만 하고 어떤 노출 판정도
하지 않는다. 그리고 **프롬프트에 학생 원문이 실리지 않는 것은 호출부의 계약**(S1-a)이므로,
원문이 없는 프롬프트만 오는 한 트레이스·캐시 키에도 원문이 실릴 수 없다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from whymath_backend.l3.interfaces import (
    CacheBackend,
    InMemoryCache,
    LLMProvider,
    RecordingTraceSink,
    TraceSink,
)
from whymath_backend.l3.models import ModelFamily, RoutingRequest
from whymath_backend.l3.pipeline import generate as l3_generate


@runtime_checkable
class Wh1Generation(Protocol):
    """WH-1이 LLM에 기대하는 전부 — 라우팅 신호 + 프롬프트 → 검증 전 원시 텍스트.

    소비자(정책·프로즈)는 이 Protocol에만 의존한다. 그래서 백엔드를 로컬 Ollama에서 클라우드로,
    파이프라인을 다른 구현으로 갈아끼워도 소비자 코드는 한 글자도 바뀌지 않는다.
    """

    async def generate(
        self,
        req: RoutingRequest,
        prompt: str,
        system: str,
        *,
        prefer_local_family: ModelFamily | None = None,
        temperature: float | None = None,
    ) -> str:
        """라우팅 → 캐시 → 생성 → 관측을 거친 원시 텍스트를 돌려준다."""
        ...


class Wh1LlmSeam:
    """`l3.pipeline` 백킹 WH-1 좌석 — `Wh1Generation` 충족.

    provider/cache/trace는 주입한다. 프로덕션은 L5(엔드포인트)가 `app.state`의 공유 인스턴스
    (`CompositeProvider`·`RedisCache`·`LangfuseSink`)를 흘려보내 관측이 실제 Langfuse로 가고
    캐시도 앱 전역과 공유된다. 미주입(테스트·app.state 없는 경로)이면 `InMemoryCache`·
    `RecordingTraceSink`로 폴백해 하위호환을 지킨다 — `L3JudgeSeam`과 같은 규약이다.

    **폴백 정책을 중복 두지 않는다**: 파이프라인 예외는 *그대로 전파*하고, 안전 강등(정책의
    `_safe_fallback`·프로즈의 원 템플릿 유지)은 호출부가 이미 소유한 자리에서 한다.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        cache: CacheBackend | None = None,
        trace: TraceSink | None = None,
    ) -> None:
        if provider is None:
            # 표준 구성(app.py·pregenerate 동형) — 지연 연결이라 구성만으로 네트워크 미발생.
            # 이 import가 좌석 안에 있는 이유: 소비자(정책·프로즈)가 `l3.providers`를 손에 쥐면
            # 프로바이더 좌석 계약 스캐너(ARCH-46)의 검사 대상이 되고, 그 파일에 라우터 경유
            # 증거를 따로 심어야 한다. L3 의존을 여기 하나로 가두면 그 의무도 여기 하나뿐이다.
            from whymath_backend.l3.providers.anthropic import AnthropicProvider
            from whymath_backend.l3.providers.composite import CompositeProvider
            from whymath_backend.l3.providers.ollama import OllamaProvider

            provider = CompositeProvider(local=OllamaProvider(), cloud=AnthropicProvider())
        self._provider: LLMProvider = provider
        self._cache: CacheBackend = cache if cache is not None else InMemoryCache()
        self._trace: TraceSink = trace if trace is not None else RecordingTraceSink()

    async def generate(
        self,
        req: RoutingRequest,
        prompt: str,
        system: str,
        *,
        prefer_local_family: ModelFamily | None = None,
        temperature: float | None = None,
    ) -> str:
        """`l3.pipeline.generate` 경유 — 라우터 결정·캐시 조회/적재·트레이스 기록이 전부 여기서."""
        result = await l3_generate(
            req,
            prompt,
            system,
            provider=self._provider,
            cache=self._cache,
            trace=self._trace,
            prefer_local_family=prefer_local_family,
            temperature=temperature,
        )
        return result.text


__all__ = ["Wh1Generation", "Wh1LlmSeam"]
