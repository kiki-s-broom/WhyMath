"""OpenAI 호환 공용 부품 단위테스트 — 실패 경로가 *정보를 남기는가* (ARCH-49).

왜 실패 경로를 따로 재는가
--------------------------
`HttpxChatTransport`가 하는 일은 거의 없다 — POST하고 JSON을 돌려준다. 유일하게 판단이
들어가는 자리가 **비-2xx 처리**이고, 거기가 이 저장소가 반복해서 대가를 치른 자리다.
`raise_for_status()`가 던지는 `HTTPStatusError`에는 **응답 본문이 없다.** 그런데 이 경로의
4xx는 전부 서로 다른 사건이다: 공급사 필터 거부 · 모델 ID 오타 · 쿼터 소진 · 키 만료.
본문을 잃으면 그 넷이 같은 글자로 보인다(CLAUDE.md 「측정·수집 도구를 성공 경로만 보고
설계 금지」 ② 실패 *원인*이 남는가).

응답 정규화(`extract_text`·`extract_usage`)도 여기서 잰다 — 형태가 예상과 다를 때
**값을 지어내지 않는지**가 계약이다.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from whymath_backend.l3.providers._openai_compat import (
    HttpxChatTransport,
    extract_text,
    extract_usage,
)


class _FakeResponse:
    def __init__(self, status_code: int, *, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        return self._payload


class _FakeAsyncClient:
    """httpx.AsyncClient의 최소 시임 — 실제 네트워크 없이 상태코드·본문을 통제한다."""

    last_init: dict[str, Any] = {}
    last_post: dict[str, Any] = {}

    def __init__(self, response: _FakeResponse, **kwargs: Any) -> None:
        self._response = response
        type(self).last_init = kwargs

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, url: str, *, headers: Any, json: Any) -> _FakeResponse:
        type(self).last_post = {"url": url, "headers": headers, "json": json}
        return self._response


@pytest.fixture
def fake_httpx(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """`import httpx`를 시임으로 바꾼다 — 전송은 지연 import라 이 치환이 유효하다."""

    def _install(response: _FakeResponse) -> type[_FakeAsyncClient]:
        module = types.ModuleType("httpx")

        def _client(**kwargs: Any) -> _FakeAsyncClient:
            return _FakeAsyncClient(response, **kwargs)

        module.AsyncClient = _client  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "httpx", module)
        return _FakeAsyncClient

    return _install


class TestTransportFailurePath:
    """비-2xx가 *원인을 담아* 실패하는가."""

    @pytest.mark.parametrize(
        ("status", "body"),
        [
            # 각 픽스처가 서로 다른 실 사건을 밟는다 — 본문이 없으면 넷이 구별되지 않는다.
            (400, '{"error":{"message":"no allowed providers available"}}'),
            (404, '{"error":{"message":"model not found: deepseek-v4-flash"}}'),
            (402, '{"error":{"message":"insufficient credits"}}'),
            (401, '{"error":{"message":"invalid api key"}}'),
        ],
    )
    async def test_non_2xx_raises_with_the_response_body(
        self, fake_httpx: Any, status: int, body: str
    ) -> None:
        fake_httpx(_FakeResponse(status, text=body))
        with pytest.raises(RuntimeError) as excinfo:
            await HttpxChatTransport().post_chat(
                "https://example.test/chat/completions",
                headers={"Authorization": "Bearer secret-key"},
                payload={"model": "m"},
                timeout_s=1.0,
            )
        message = str(excinfo.value)
        assert str(status) in message, "상태코드가 없으면 어느 종류의 거부인지 모른다"
        # 본문의 고유 어구가 살아 있어야 네 사건이 구별된다.
        assert body[20:40] in message

    async def test_error_message_does_not_leak_the_key(self, fake_httpx: Any) -> None:
        """키는 요청 *헤더*에만 있고 응답 본문에는 없다 — 오류 문자열에 새지 않는다."""
        fake_httpx(_FakeResponse(401, text='{"error":"invalid api key"}'))
        with pytest.raises(RuntimeError) as excinfo:
            await HttpxChatTransport().post_chat(
                "https://example.test/chat/completions",
                headers={"Authorization": "Bearer super-secret-value"},
                payload={"model": "m"},
                timeout_s=1.0,
            )
        assert "super-secret-value" not in str(excinfo.value)

    async def test_2xx_returns_parsed_json(self, fake_httpx: Any) -> None:
        client = fake_httpx(_FakeResponse(200, payload={"ok": True}))
        result = await HttpxChatTransport().post_chat(
            "https://example.test/chat/completions",
            headers={"X": "1"},
            payload={"model": "m"},
            timeout_s=12.5,
        )
        assert result == {"ok": True}
        # 타임아웃이 실제로 클라이언트에 전달되는가 — 무한 대기 금지(측정 도구 설계 규칙).
        assert client.last_init["timeout"] == 12.5
        assert client.last_post["json"] == {"model": "m"}


class TestResponseNormalization:
    """형태가 예상과 다를 때 값을 지어내지 않는가."""

    def test_extracts_content_of_first_choice(self) -> None:
        payload = {"choices": [{"message": {"content": "답"}}]}
        assert extract_text(payload) == "답"

    def test_reasoning_content_is_not_returned_as_the_answer(self) -> None:
        """추론 블록은 최종 답이 아니다 — 하류 검증이 그것을 답으로 오독하면 안 된다."""
        payload = {
            "choices": [{"message": {"reasoning_content": "생각 과정", "content": "최종 답"}}]
        }
        assert extract_text(payload) == "최종 답"

    @pytest.mark.parametrize(
        "payload",
        [
            {},  # choices 키 자체가 없음
            {"choices": []},  # 빈 목록
            {"choices": [{}]},  # message 없음
            {"choices": [{"message": {}}]},  # content 없음
            {"choices": [{"message": {"content": 42}}]},  # 문자열이 아님
            "not a mapping",  # 통째로 다른 형태
        ],
    )
    def test_malformed_shapes_yield_empty_string(self, payload: Any) -> None:
        assert extract_text(payload) == ""

    def test_usage_uses_openai_field_names(self) -> None:
        usage = extract_usage(
            {"usage": {"prompt_tokens": 9, "completion_tokens": 4}}, latency_ms=12.0
        )
        assert usage.input_tokens == 9
        assert usage.output_tokens == 4
        assert usage.latency_ms == 12.0

    def test_missing_usage_is_none_not_zero(self) -> None:
        """부재와 0을 구분한다 — 0은 '읽었는데 0이었다'는 실측이다."""
        usage = extract_usage({"choices": []}, latency_ms=1.0)
        assert usage.input_tokens is None
        assert usage.output_tokens is None

    def test_zero_is_preserved_as_a_measurement(self) -> None:
        usage = extract_usage({"usage": {"prompt_tokens": 0}}, latency_ms=1.0)
        assert usage.input_tokens == 0

    @pytest.mark.parametrize("bogus", [True, "12", -3, 1.5, None])
    def test_non_token_values_become_none(self, bogus: Any) -> None:
        """bool은 int의 서브클래스지만 토큰 수가 아니다 — 음수·문자열·실수도 마찬가지."""
        usage = extract_usage({"usage": {"prompt_tokens": bogus}}, latency_ms=1.0)
        assert usage.input_tokens is None

    def test_cache_creation_is_always_none_for_this_api(self) -> None:
        """이 API에는 캐시 *쓰기* 개념이 없다 — 0이 아니라 None(미측정 ≠ 0)."""
        usage = extract_usage(
            {"usage": {"prompt_tokens": 10, "prompt_cache_hit_tokens": 6}}, latency_ms=1.0
        )
        assert usage.cache_read_input_tokens == 6
        assert usage.cache_creation_input_tokens is None
