"""P3-78 라이브 품질 수집의 **조립 좌석** — provider·관측 싱크·선언 모델 핀을 만든다(호출 0).

왜 이 파일이 `ai_quality_live_collect`와 따로 있는가
-------------------------------------------------
수집 도구는 provider를 *감싸* 사례마다 예외(타입명·HTTP 본문·타임아웃)를 붙잡는다 — 그 래퍼는
안쪽 provider의 `generate(prompt, system, decision)`를 그대로 **전달**한다(결정은 `l3.pipeline`
안의 `Router().route()`가 이미 낸 것이다 — 래퍼는 호출을 만들지 않고 넘길 뿐이다). 프로바이더 좌석
계약 스캐너(`scripts/ops/check_provider_seat_contract.py`·ARCH-46)는 `l3.providers`를 임포트한
파일이 `.generate(`를 부르면 그 파일에 라우터 경유 증거를 요구한다. 조립과 전달을 한 파일에 두면
전달 래퍼가 "직접 호출"로 보이고, 그 파일에 쓰지도 않는 `l3.pipeline` 임포트를 심어야 통과한다
— 그것은 증거 위장이다. 그래서 `wh1_llm_seam`이 L3 의존을 한 자리에 가둔 것과 같은 방식으로,
**조립은 여기(FACTORY — `.generate` 호출 0)**, 전달은 수집 모듈(`l3.providers` 임포트 0)에 둔다.

무엇을 만드는가 — 학생 대면 서빙(`app.create_app`)과 같은 것 / 다른 것
------------------------------------------------------------------
- provider: `CompositeProvider(local=OllamaProvider(), cloud=build_cloud_provider(settings))` —
  서빙과 **같은 팩토리**(클라우드 좌석은 `settings.cloud_provider` 셀렉터 하나가 정한다).
  **다른 점**: `runtime_local_degrade`를 켜지 않는다. 서빙은 1차 클라우드 좌석이 429·5xx·타임아웃
  으로 실패하면 LOCAL이 대신 답하지만, 측정에서 그렇게 하면 실패가 다른 모델의 응답으로 위장된다
  (app.py 주석 "저작·측정 경로에는 없다 — 명확한 실패가 옳다"·`test_cloud_runtime_local_degrade.py`
  AST 동결). 실패는 수집 도구가 실패로 기록하고 `--resume`으로 다시 돈다.
- 관측: `LangfuseSink(traffic_surface=PROBE)` — 서빙과 같은 싱크 클래스, **다른 표면 표지**. 이
  호출은 학생 대면 트래픽이 아니라 측정을 위해 일부러 낸 호출이므로 게이트② 학생 대면 비용 표본에
  섞이면 안 된다(`TrafficSurface.PROBE` 정의). 키가 비면 영구 no-op이다(네트워크 0).
- 선언 모델 핀: 셀렉터가 고른 클라우드 좌석 이름·(CLOUD_MID, CLOUD_HIGH) 핀·로컬 매트릭스·
  QUALITY 핀 — 실행 식별(`<out>.run.json`)의 *선언* 칸이다. 실제로 답한 모델은 수집 도구가
  트레이스에서 따로 센다(선언 ≠ 관측).

구성만으로는 네트워크를 타지 않는다(각 provider·싱크가 첫 호출까지 연결을 미룬다).
"""

from __future__ import annotations

from whymath_backend.config import Settings, get_settings
from whymath_backend.l3.interfaces import LLMProvider, TraceSink, TrafficSurface

__all__ = ["build_live_provider", "build_live_trace", "declared_model_pins", "trace_configured"]


def build_live_provider(settings: Settings | None = None) -> LLMProvider:
    """서빙과 같은 팩토리로 조립한 provider — 런타임 LOCAL 강등은 끈다(측정은 명확한 실패)."""
    from whymath_backend.l3.providers.composite import CompositeProvider
    from whymath_backend.l3.providers.factory import build_cloud_provider
    from whymath_backend.l3.providers.ollama import OllamaProvider

    resolved = settings if settings is not None else get_settings()
    return CompositeProvider(local=OllamaProvider(), cloud=build_cloud_provider(resolved))


def build_live_trace() -> TraceSink:
    """Langfuse 싱크(측정 표면 표지) — 키 미설정이면 영구 no-op."""
    from whymath_backend.l3.trace import LangfuseSink

    return LangfuseSink(traffic_surface=TrafficSurface.PROBE)


def trace_configured(trace: TraceSink) -> bool | None:
    """싱크가 실제로 전송할 수 있게 구성됐는가 — 그 표면이 없는 싱크(테스트 대역)는 None(모름)."""
    value = getattr(trace, "configured", None)
    return value if isinstance(value, bool) else None


def declared_model_pins(settings: Settings | None = None) -> dict[str, object]:
    """선언 모델 핀 — 셀렉터가 고른 클라우드 좌석·핀과 로컬 매트릭스(관측이 아니라 설정값).

    좌석→핀 매핑은 `cloud_model_pins`가 단일 근거다(ARCH-58 — 매핑을 두 곳에 두면 갈라진다).
    """
    from whymath_backend.l3.providers.factory import cloud_model_pins, cloud_provider_name
    from whymath_backend.l3.router import LOCAL_MODEL_MATRIX, QUALITY_MODEL_ID

    resolved = settings if settings is not None else get_settings()
    mid, high = cloud_model_pins(resolved)
    return {
        "cloud_seat": cloud_provider_name(resolved),
        "cloud_mid": mid,
        "cloud_high": high,
        "local_matrix": {
            f"{family.value}/{size.value}": model
            for (family, size), model in sorted(
                LOCAL_MODEL_MATRIX.items(), key=lambda item: (item[0][0].value, item[0][1].value)
            )
        },
        "local_quality": QUALITY_MODEL_ID,
        "ollama_host": resolved.ollama_host,
    }
