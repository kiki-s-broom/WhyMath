"""골든 클라우드 좌석 팩토리 — 옛 `l3/providers/factory.build_cloud_provider`의 openrouter 분기만
옮겼다.

S20A 2일째(Kiki 결정 2026-11-17 선택지 B): 옛 팩토리는 `l3.providers` 패키지 안에 있어
import하는 순간 프로바이더 4종이 함께 로드된다. 골든은 OpenRouter 좌석 하나만 쓰므로 그 분기만
둔다.

좌석은 여전히 옛 설정의 셀렉터(`settings.cloud_provider` — 기본 openrouter · ARCH-64)가 정한다.
셀렉터가 다른 좌석(deepseek·anthropic)을 가리키면 **조용히 OpenRouter로 바꾸지 않고 ValueError**를
낸다(CLAUDE.md 「침묵 실패 금지」 — 옛 팩토리의 알 수 없는 좌석 처리와 같은 규칙). 튜터는 그 예외를
삼키지 않고 타입명을 로그에 남긴 뒤 대체 문장(degraded)으로 간다(`golden/tutor.py`).
"""

from __future__ import annotations

from golden.llm.openrouter import OpenRouterProvider
from whymath_backend.config import Settings, get_settings

# 골든 복사본이 만들 수 있는 좌석 — 옛 팩토리의 세 분기 중 하나
SUPPORTED_SEAT = "openrouter"


def build_cloud_provider(settings: Settings | None = None) -> OpenRouterProvider:
    """설정의 클라우드 좌석이 openrouter면 그 제공자를 만든다. 다른 좌석이면 ValueError."""
    resolved = settings if settings is not None else get_settings()
    name = resolved.cloud_provider
    if name == SUPPORTED_SEAT:
        return OpenRouterProvider(settings=resolved)
    raise ValueError(
        f"골든 LLM 경로는 cloud_provider={SUPPORTED_SEAT!r}만 지원한다(받은 값 {name!r}) — "
        "다른 좌석을 쓰려면 golden/llm/에 그 프로바이더를 복사해 분기를 더한다(HARVEST.md S20A)."
    )
