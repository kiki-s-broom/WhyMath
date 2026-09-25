"""provider 기본 클라이언트의 이벤트 루프 결속 회귀 테스트 (S4-99).

사고: 2026-09-24 S4-16 2차 강등전 라이브 회차에서 v4 관점 세트 3종 각각의 **첫 관점**이
거의 전 문항 `RuntimeError`로 unclear 처리됐다. `CrossVerifier.verify`는 호출마다
`asyncio.run()`으로 새 루프를 여는데, provider가 캐시한 httpx 기반 클라이언트의 커넥션
풀은 생성 루프(이미 닫힘)에 묶여 있어 새 루프의 첫 요청이 `Event loop is closed`로 죽는다.

이 파일이 동결하는 계약:
- 기본 생성 클라이언트는 루프가 바뀌면 새로 만든다(두 번의 `asyncio.run` → 빌더 2회).
- 같은 루프 안에서는 재사용한다(빌더 1회) — 매 호출 재생성은 커넥션 재사용을 잃는다.
- 주입된 클라이언트는 루프와 무관하게 그대로 쓴다(수명은 주입한 쪽 책임).
- 실물 `ollama` AsyncClient + 루프백 가짜 서버로 사고 증상 자체가 사라졌음을 확인한다.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from pydantic import SecretStr

from whymath_backend.config import Settings
from whymath_backend.l3.models import CostTier, LocalModelTier, RoutingDecision
from whymath_backend.l3.providers.anthropic import AnthropicProvider
from whymath_backend.l3.providers.ollama import OllamaProvider


class _Marker:
    """빌더가 돌려주는 가짜 클라이언트 — 동일성 비교 전용."""


def _counting_builder(built: list[Any]) -> Any:
    def _build(settings: Settings) -> Any:
        client = _Marker()
        built.append(client)
        return client

    return _build


async def _get_twice(provider: Any) -> tuple[Any, Any]:
    return provider._get_client(), provider._get_client()


def _anthropic_settings() -> Settings:
    # ARCH-66: 사용 중단 방침 스위치(기본 False)를 켜야 클라이언트 생성 경로에 도달한다
    return Settings(anthropic_api_key=SecretStr("sk-ant-test"), anthropic_api_enabled=True)


# ── OllamaProvider ────────────────────────────────────────────────────────
class TestOllamaClientLoopBinding:
    def test_new_loop_gets_new_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """두 번의 asyncio.run → 기본 클라이언트 2개(닫힌 루프의 풀을 재사용하지 않는다)."""
        built: list[Any] = []
        monkeypatch.setattr(
            "whymath_backend.l3.providers.ollama._build_default_client", _counting_builder(built)
        )
        provider = OllamaProvider(settings=Settings())
        first, _ = asyncio.run(_get_twice(provider))
        second, _ = asyncio.run(_get_twice(provider))
        assert first is not second
        assert len(built) == 2

    def test_same_loop_reuses_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """한 루프 안에서는 1회 생성·재사용."""
        built: list[Any] = []
        monkeypatch.setattr(
            "whymath_backend.l3.providers.ollama._build_default_client", _counting_builder(built)
        )
        provider = OllamaProvider(settings=Settings())
        a, b = asyncio.run(_get_twice(provider))
        assert a is b
        assert len(built) == 1

    def test_sync_context_reuses_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """루프 밖(동기 문맥) 반복 호출도 재사용 — 종전 지연 생성 동작 보존."""
        built: list[Any] = []
        monkeypatch.setattr(
            "whymath_backend.l3.providers.ollama._build_default_client", _counting_builder(built)
        )
        provider = OllamaProvider(settings=Settings())
        assert provider._get_client() is provider._get_client()
        assert len(built) == 1

    def test_injected_client_survives_loop_change(self) -> None:
        """주입 클라이언트는 루프가 바뀌어도 교체하지 않는다."""
        injected = _Marker()
        provider = OllamaProvider(client=injected)  # type: ignore[arg-type]
        first, _ = asyncio.run(_get_twice(provider))
        second, _ = asyncio.run(_get_twice(provider))
        assert first is injected
        assert second is injected


# ── AnthropicProvider ─────────────────────────────────────────────────────
class TestAnthropicClientLoopBinding:
    def test_new_loop_gets_new_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        built: list[Any] = []
        monkeypatch.setattr(
            "whymath_backend.l3.providers.anthropic._build_default_client",
            _counting_builder(built),
        )
        provider = AnthropicProvider(settings=_anthropic_settings())
        first, _ = asyncio.run(_get_twice(provider))
        second, _ = asyncio.run(_get_twice(provider))
        assert first is not second
        assert len(built) == 2

    def test_same_loop_reuses_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        built: list[Any] = []
        monkeypatch.setattr(
            "whymath_backend.l3.providers.anthropic._build_default_client",
            _counting_builder(built),
        )
        provider = AnthropicProvider(settings=_anthropic_settings())
        a, b = asyncio.run(_get_twice(provider))
        assert a is b
        assert len(built) == 1

    def test_injected_client_survives_loop_change(self) -> None:
        injected = _Marker()
        provider = AnthropicProvider(client=injected)  # type: ignore[arg-type]
        first, _ = asyncio.run(_get_twice(provider))
        second, _ = asyncio.run(_get_twice(provider))
        assert first is injected
        assert second is injected

    def test_unconfigured_still_raises_after_fix(self) -> None:
        """루프 결속이 키 미설정 거부를 우회하지 않는다."""
        provider = AnthropicProvider(settings=Settings(anthropic_api_key=SecretStr("")))
        with pytest.raises(RuntimeError, match="API 키"):
            provider._get_client()


# ── 실물 ollama AsyncClient — 사고 증상 자체의 소멸 ─────────────────────────
class _FakeOllamaHandler(BaseHTTPRequestHandler):
    """`/api/generate`에 고정 응답을 주는 루프백 가짜 Ollama(keep-alive 유지)."""

    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = json.dumps({"model": "qwen3:30b-a3b", "response": "ok", "done": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — 부모 시그니처
        return


@pytest.fixture
def fake_ollama_host() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllamaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _quality_decision() -> RoutingDecision:
    return RoutingDecision(
        cost_tier=CostTier.LOCAL,
        local_family=None,
        local_model=LocalModelTier.QUALITY,
        mode="async",
        reason="test",
        est_latency_ms=2300,
        est_cost_krw=0.0,
    )


def test_real_ollama_client_survives_repeated_asyncio_run(fake_ollama_host: str) -> None:
    """실물 AsyncClient로 asyncio.run을 3회 — 매 루프 첫 요청이 죽던 사고가 재현되지 않는다.

    수정 전에는 루프 2·3의 첫 요청이 `RuntimeError: Event loop is closed`였다(2026-09-24
    컨테이너 재현: 루프마다 첫 요청만 실패·나머지 성공 — 라이브 로그와 같은 패턴).
    """
    pytest.importorskip("ollama")
    provider = OllamaProvider(settings=Settings(ollama_host=fake_ollama_host))
    decision = _quality_decision()

    async def _batch() -> list[str]:
        texts: list[str] = []
        for _ in range(3):
            result = await provider.generate("p", "s", decision)
            texts.append(result.text)
        return texts

    for _ in range(3):
        assert asyncio.run(_batch()) == ["ok", "ok", "ok"]
