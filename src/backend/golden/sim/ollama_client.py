"""학생 시뮬레이터 전용 로컬 Ollama 제공자 — 옛 `l3/providers/ollama.py`에서 필요한 부분만 복사했다.

[골든 복사본 · S18 · HARVEST.md "복사: 의존 과다"]
옛 `whymath_backend.l3.providers.ollama.FixedModelOllamaProvider`(고정 모델 ID로 부르는 Ollama
제공자)를 import하면 `l3/providers/__init__.py`가 프로바이더 4종(Anthropic·DeepSeek·OpenRouter·
Composite)을 함께 부른다. S20A가 끊은 패키지라 다시 붙으면 `tests/golden/test_import_budget.py`
(전이 28/30 · 끊은 패키지 재유입 금지)가 RED가 된다. 그래서 학생 모델이 쓰는 경로만 옮겼다.

옮긴 것(동작 그대로 — `tests/golden/characterization/test_s18_ollama_client.py`가 옛 클래스와 나란히
입력 10개를 돌려 같은 호출 인자·같은 결과를 내는지 고정한다):
- `_OllamaClient`(주입용 구조 타입) · `_extract_text` · `_coerce_token_count` · `_read_field` ·
  `_extract_usage` · `_build_default_client`
- `FixedModelOllamaProvider.generate`의 호출 인자 조립(고정 모델 ID · num_ctx·num_predict·온도·
  top_p·시드 · LOCAL 결정만 처리)과 클라이언트 지연 생성·이벤트 루프 결속(S4-99)

버린 것: `OllamaProvider.generate`의 `resolve_model` 경로(라우터 매트릭스로 모델을 고르는 것 — 학생
모델은 `GOLDEN_SIM_STUDENT_MODEL`로 고정한다) · `check_status`·`OllamaStatus`·`ModelAvailability`
(/status 엔드포인트용) · 이미지 입력·JSON 스키마 제약(학생 발화에 쓰지 않는다) ·
`_running_loop_or_none`(루프 밖 호출 분기 — 여기서는 비동기 generate 안에서만 클라이언트를 만든다).

바꾼 것: import 출처 하나(`_response_fields`는 S20A가 이미 복사한 `golden.llm._response_fields`).
`golden/llm/sync.py`의 자동 동기화 검사 대상은 아니다(파일 일부만 옮겼기 때문 —
특성화 테스트가 대신한다).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from typing import Any, Protocol, cast, runtime_checkable

from golden.llm._response_fields import read_response_model_id
from whymath_backend.config import Settings, get_settings
from whymath_backend.l3.models import CostTier, GenerationResult, RoutingDecision, Usage
from whymath_backend.l3.provider_jurisdiction import Jurisdiction
from whymath_backend.l3.router import _as_cost_tier


@runtime_checkable
class _OllamaClient(Protocol):
    """ollama 비동기 클라이언트의 최소 인터페이스(옛 것과 같다 — 테스트는 가짜 객체로 바꾼다)."""

    async def generate(
        self,
        *,
        model: str,
        prompt: str,
        system: str,
        images: Sequence[str] | None = None,
        options: dict[str, Any] | None = None,
        format: Any = None,  # noqa: A002 — ollama API 인자명 그대로
        stream: bool = False,
    ) -> Any:
        """단일 프롬프트 생성(ollama generate API)."""
        ...

    async def list(self) -> Any:
        """설치된 모델 목록 조회(ollama list API)."""
        ...


def _extract_text(generate_response: Any) -> str:
    """generate 응답의 생성 텍스트 — `response`가 비면 `thinking`을 본다(옛 것과 같다)."""

    def _attr(name: str) -> str | None:
        if hasattr(generate_response, name):
            v = getattr(generate_response, name)
            return v if isinstance(v, str) else None
        if isinstance(generate_response, dict):
            v = generate_response.get(name)
            return v if isinstance(v, str) else None
        return None

    for field in ("response", "thinking"):
        text = _attr(field)
        if text:
            return text
    return ""


def _coerce_token_count(value: Any) -> int | None:
    """토큰 수를 int|None으로 — bool·음수·다른 타입은 None(값을 지어내지 않는다)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _read_field(response: Any, name: str) -> Any:
    """응답(pydantic 객체 또는 dict)에서 필드값을 읽는다."""
    if hasattr(response, name):
        return getattr(response, name)
    if isinstance(response, dict):
        return response.get(name)
    return None


def _extract_usage(generate_response: Any, latency_ms: float) -> Usage:
    """입력·출력 토큰과 실측 지연, 실제로 로드된 모델 태그를 담는다(옛 것과 같다)."""
    return Usage(
        input_tokens=_coerce_token_count(_read_field(generate_response, "prompt_eval_count")),
        output_tokens=_coerce_token_count(_read_field(generate_response, "eval_count")),
        latency_ms=latency_ms,
        served_model=read_response_model_id(generate_response),
    )


def _build_default_client(settings: Settings) -> _OllamaClient:
    """기본 ollama AsyncClient — 호출 시점에만 import한다(라이브러리 없는 CI에서도 안 깨지게)."""
    try:
        from ollama import AsyncClient
    except ImportError as exc:  # pragma: no cover — 환경 의존(라이브러리 미설치)
        raise RuntimeError(
            "ollama Python 클라이언트가 설치되지 않았습니다. "
            "`python -m pip install ollama` 후 다시 시도하세요."
        ) from exc
    client = AsyncClient(
        host=settings.ollama_host,
        timeout=settings.ollama_request_timeout_s,
    )
    return cast(_OllamaClient, client)


class FixedModelOllamaProvider:
    """고정 모델 ID로 로컬 Ollama를 부르는 제공자(옛 `FixedModelOllamaProvider`의 생성 경로).

    클라우드(CLOUD_*) 결정은 거부한다 — 학생 시뮬레이터는 로컬만 부른다(공통 규칙 7·9).
    """

    def __init__(
        self,
        model_id: str,
        *,
        client: _OllamaClient | None = None,
        settings: Settings | None = None,
        timeout: float | None = None,
        num_ctx: int | None = None,
        num_predict: int | None = None,
    ) -> None:
        if settings is not None and timeout is not None:
            settings = settings.model_copy(update={"ollama_request_timeout_s": timeout})
        elif timeout is not None:
            settings = get_settings().model_copy(update={"ollama_request_timeout_s": timeout})
        self._client = client
        self._settings = settings
        # 기본 생성 클라이언트는 만든 이벤트 루프 안에서만 재사용한다(옛 S4-99와 같다)
        self._owns_client = client is None
        self._client_loop: asyncio.AbstractEventLoop | None = None
        self._model_id = model_id
        self._num_ctx = num_ctx
        self._num_predict = num_predict

    @property
    def model_id(self) -> str:
        """이 제공자가 부르는 Ollama 모델 태그."""
        return self._model_id

    @property
    def jurisdiction(self) -> Jurisdiction:
        """항상 DOMESTIC — Kiki 머신(온프레미스) 로컬 데몬이라 국외 이전이 없다."""
        return Jurisdiction.DOMESTIC

    @property
    def _resolved_settings(self) -> Settings:
        """설정 지연 해석 — 주입 우선, 없으면 전역 Settings."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_client(self) -> _OllamaClient:
        """클라이언트 지연 해석 — 주입 우선, 루프가 바뀌면 새로 만든다."""
        if not self._owns_client:
            assert self._client is not None  # 주입 경로 — 생성자가 보장
            return self._client
        # generate(비동기) 안에서만 불리므로 실행 중 루프가 늘 있다(옛 루프 없음 분기는 버림)
        loop = asyncio.get_running_loop()
        if self._client is None or self._client_loop is not loop:
            self._client = _build_default_client(self._resolved_settings)
            self._client_loop = loop
        return self._client

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        """고정 모델 ID로 생성한다. LOCAL 결정이 아니면 호출하지 않고 ValueError."""
        cost = _as_cost_tier(decision.cost_tier)
        if cost is not CostTier.LOCAL:
            raise ValueError(
                f"FixedModelOllamaProvider는 로컬 결정만 처리한다"
                f"(받은 cost_tier={decision.cost_tier})."
            )
        call_kwargs: dict[str, Any] = {
            "model": self._model_id,
            "prompt": prompt,
            "system": system,
            "stream": False,
        }
        options: dict[str, Any] = {}
        if self._num_ctx is not None:
            options["num_ctx"] = self._num_ctx
        if self._num_predict is not None:
            options["num_predict"] = self._num_predict
        if temperature is not None:
            options["temperature"] = temperature
        if top_p is not None:
            options["top_p"] = top_p
        if seed is not None:
            options["seed"] = seed
        if options:
            call_kwargs["options"] = options
        client = self._get_client()
        start = time.monotonic()
        response = await client.generate(**call_kwargs)
        latency_ms = (time.monotonic() - start) * 1000.0
        return GenerationResult(
            text=_extract_text(response),
            usage=_extract_usage(response, latency_ms),
        )
