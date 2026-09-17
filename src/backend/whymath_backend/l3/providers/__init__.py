"""L3 LLM 백엔드 구현 — interfaces.LLMProvider Protocol의 실제 구현체.

범위 메모 (M1.2-live): S1이 로컬(Ollama) 구현을, S5가 클라우드(Anthropic Claude)
구현 + 로컬↔클라우드 디스패처(CompositeProvider)를 추가했다(03a §H 후속 4 클라우드 연동).
OpenAI 등 추가 클라우드 제공자는 후속에서 같은 패턴으로 붙인다.

ARCH-49가 DeepSeek 경로 2종을 같은 패턴으로 추가했다 — `deepseek.py`(공식 API·CN 관할
고정)와 `openrouter.py`(서방 공급사 경유·관할은 허용목록에서 유도). 둘 다 OpenAI 호환
`/chat/completions`라 공용 부품 `_openai_compat.py`를 공유한다. 어느 관할로 무엇을 보낼
수 있는지는 `l3/provider_jurisdiction.py`가 정하고, 집행은 `CompositeProvider`가 위임
직전에 한다.
"""

from whymath_backend.l3.providers.anthropic import (
    AnthropicProvider,
    AnthropicStatus,
)
from whymath_backend.l3.providers.composite import CompositeProvider
from whymath_backend.l3.providers.deepseek import DeepSeekProvider, DeepSeekStatus
from whymath_backend.l3.providers.ollama import (
    ModelAvailability,
    OllamaProvider,
    OllamaStatus,
)
from whymath_backend.l3.providers.openrouter import (
    OpenRouterProvider,
    OpenRouterStatus,
)

__all__ = [
    "AnthropicProvider",
    "AnthropicStatus",
    "CompositeProvider",
    "DeepSeekProvider",
    "DeepSeekStatus",
    "ModelAvailability",
    "OllamaProvider",
    "OllamaStatus",
    "OpenRouterProvider",
    "OpenRouterStatus",
]
