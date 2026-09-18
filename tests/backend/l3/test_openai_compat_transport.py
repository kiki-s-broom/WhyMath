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
    RETRYABLE_STATUS,
    HttpxChatTransport,
    extract_text,
    extract_usage,
    reset_retry_count,
    retries_in_current_call,
)


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        payload: Any = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        # 실제 httpx.Response는 항상 headers를 가진다 — 전송기가 `Retry-After`를 읽으므로
        # 시임도 그 표면을 갖춰야 한다(없으면 시임만 통과하는 거짓 계약이 된다).
        self.headers: dict[str, str] = headers or {}

    def json(self) -> Any:
        return self._payload


class _FakeAsyncClient:
    """httpx.AsyncClient의 최소 시임 — 실제 네트워크 없이 상태코드·본문을 통제한다."""

    last_init: dict[str, Any] = {}
    last_post: dict[str, Any] = {}

    post_count: int = 0

    def __init__(self, response: _FakeResponse, **kwargs: Any) -> None:
        self._response = response
        type(self).last_init = kwargs

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, url: str, *, headers: Any, json: Any) -> _FakeResponse:
        type(self).last_post = {"url": url, "headers": headers, "json": json}
        type(self).post_count += 1
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


class _SequenceClient:
    """응답을 순서대로 내는 시임 — 재시도 경로는 *여러 번* 응답해야 밟을 수 있다.

    단일 응답만 내는 `_FakeAsyncClient`로는 "첫 번째는 429, 두 번째는 200" 상태를 만들 수
    없고, 그러면 '재시도해서 성공한다'는 절을 한 번도 지나가지 않는다
    (CLAUDE.md 「픽스처가 그 절을 실제로 밟는가」).
    """

    posts: int = 0
    _queue: list[_FakeResponse] = []

    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs

    async def __aenter__(self) -> _SequenceClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, url: str, *, headers: Any, json: Any) -> _FakeResponse:
        type(self).posts += 1
        index = min(type(self).posts - 1, len(type(self)._queue) - 1)
        return type(self)._queue[index]


@pytest.fixture
def sequenced_httpx(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """응답 시퀀스를 주는 httpx 시임."""

    def _install(responses: list[_FakeResponse]) -> type[_SequenceClient]:
        _SequenceClient.posts = 0
        _SequenceClient._queue = responses
        module = types.ModuleType("httpx")
        module.AsyncClient = _SequenceClient  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "httpx", module)
        return _SequenceClient

    return _install


async def _no_sleep(_seconds: float) -> None:
    """테스트는 실제로 기다리지 않는다 — 대기 시간은 `_backoff_s`로 따로 단언한다."""
    return None


class TestRetryOnTransientFailure:
    """429·5xx 재시도 (2026-09-17 OpenRouter 실측 대응).

    실측: 20회 중 6회(30%)가 `429 engine_overloaded`로 죽었고 우리 전송기에 재시도가
    없었다. 재시도가 없으면 "가용성 70%"가 공급사의 성질이 아니라 **우리 전송기의 성질**을
    재는 숫자가 된다.
    """

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 408])
    async def test_retries_then_succeeds(self, sequenced_httpx: Any, status: int) -> None:
        client = sequenced_httpx(
            [
                _FakeResponse(status, text="upstream busy"),
                _FakeResponse(200, payload={"ok": True}),
            ]
        )
        reset_retry_count()
        result = await HttpxChatTransport(sleep=_no_sleep, jitter=lambda: 0.0).post_chat(
            "https://example.test/v1/chat/completions",
            headers={},
            payload={"model": "m"},
            timeout_s=1.0,
        )
        assert result == {"ok": True}
        assert client.posts == 2
        assert retries_in_current_call() == 1

    @pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422])
    async def test_permanent_errors_are_not_retried(
        self, sequenced_httpx: Any, status: int
    ) -> None:
        """모델 ID 오타·키 오류·공급사 필터 거부는 다시 걸어도 같다 — 즉시 실패해야 한다."""
        client = sequenced_httpx([_FakeResponse(status, text="nope")])
        reset_retry_count()
        with pytest.raises(RuntimeError, match=str(status)):
            await HttpxChatTransport(sleep=_no_sleep, jitter=lambda: 0.0).post_chat(
                "https://example.test/v1/chat/completions",
                headers={},
                payload={"model": "m"},
                timeout_s=1.0,
            )
        assert client.posts == 1
        assert retries_in_current_call() == 0

    async def test_gives_up_after_max_attempts_and_says_how_many(
        self, sequenced_httpx: Any
    ) -> None:
        """포기할 때 **몇 번 시도했는지**가 메시지에 남는다 — 없으면 1회 실패와 구분 안 된다."""
        client = sequenced_httpx([_FakeResponse(429, text="still busy")])
        reset_retry_count()
        with pytest.raises(RuntimeError, match="시도 3회"):
            await HttpxChatTransport(max_attempts=3, sleep=_no_sleep, jitter=lambda: 0.0).post_chat(
                "https://example.test/v1/chat/completions",
                headers={},
                payload={"model": "m"},
                timeout_s=1.0,
            )
        assert client.posts == 3
        assert retries_in_current_call() == 2

    async def test_max_attempts_one_means_no_retry(self, sequenced_httpx: Any) -> None:
        client = sequenced_httpx([_FakeResponse(429, text="busy")])
        reset_retry_count()
        with pytest.raises(RuntimeError):
            await HttpxChatTransport(max_attempts=1, sleep=_no_sleep, jitter=lambda: 0.0).post_chat(
                "https://example.test/v1/chat/completions",
                headers={},
                payload={"model": "m"},
                timeout_s=1.0,
            )
        assert client.posts == 1

    def test_zero_attempts_is_refused(self) -> None:
        with pytest.raises(ValueError, match="1 이상"):
            HttpxChatTransport(max_attempts=0)

    async def test_the_retried_request_is_byte_identical(self, sequenced_httpx: Any) -> None:
        """재시도가 payload를 바꾸면 공급사 3파라미터 계약이 두 번째 요청에서 깨질 수 있다."""
        seen: list[Any] = []

        class _Recording(_SequenceClient):
            async def post(self, url: str, *, headers: Any, json: Any) -> _FakeResponse:
                seen.append(json)
                return await super().post(url, headers=headers, json=json)

        _SequenceClient.posts = 0
        _SequenceClient._queue = [_FakeResponse(429), _FakeResponse(200, payload={"ok": 1})]
        module = types.ModuleType("httpx")
        module.AsyncClient = _Recording  # type: ignore[attr-defined]
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "httpx", module)
            await HttpxChatTransport(sleep=_no_sleep, jitter=lambda: 0.0).post_chat(
                "https://example.test/v1/chat/completions",
                headers={},
                payload={"model": "m", "provider": {"only": ["deepinfra"]}},
                timeout_s=1.0,
            )
        assert len(seen) == 2
        assert seen[0] == seen[1]


class TestBackoffSchedule:
    """대기 시간 — 공급사의 `Retry-After`가 있으면 그것을 쓴다."""

    def test_exponential_with_jitter(self) -> None:
        transport = HttpxChatTransport(base_delay_s=2.0, max_delay_s=100.0, jitter=lambda: 0.5)
        assert transport._backoff_s(0, None) == pytest.approx(2.0 + 1.0)
        assert transport._backoff_s(1, None) == pytest.approx(4.0 + 1.0)
        assert transport._backoff_s(2, None) == pytest.approx(8.0 + 1.0)

    def test_capped_by_max_delay(self) -> None:
        transport = HttpxChatTransport(base_delay_s=1.0, max_delay_s=5.0, jitter=lambda: 0.0)
        assert transport._backoff_s(10, None) == pytest.approx(5.0)

    def test_retry_after_header_wins(self) -> None:
        transport = HttpxChatTransport(base_delay_s=1.0, max_delay_s=60.0, jitter=lambda: 0.0)
        assert transport._backoff_s(0, 7.5) == pytest.approx(7.5)

    def test_retry_after_is_still_capped(self) -> None:
        """공급사가 1시간을 요구해도 우리 상한을 넘기지 않는다."""
        transport = HttpxChatTransport(base_delay_s=1.0, max_delay_s=20.0, jitter=lambda: 0.0)
        assert transport._backoff_s(0, 3600.0) == pytest.approx(20.0)

    async def test_retry_after_header_is_read_from_the_response(self, sequenced_httpx: Any) -> None:
        """헤더를 실제로 읽는가 — 읽지 않으면 위 단위 테스트는 전부 통과하면서 무의미하다."""
        slept: list[float] = []

        async def _record(seconds: float) -> None:
            slept.append(seconds)

        sequenced_httpx(
            [
                _FakeResponse(429, text="busy", headers={"retry-after": "9"}),
                _FakeResponse(200, payload={"ok": 1}),
            ]
        )
        await HttpxChatTransport(sleep=_record, jitter=lambda: 0.0, max_delay_s=60.0).post_chat(
            "https://example.test/v1/chat/completions",
            headers={},
            payload={"model": "m"},
            timeout_s=1.0,
        )
        assert slept == [pytest.approx(9.0)]

    @pytest.mark.parametrize("raw", ["Wed, 21 Oct 2026 07:28:00 GMT", "", "-3", "abc", None])
    async def test_unparsable_retry_after_falls_back_to_backoff(
        self, sequenced_httpx: Any, raw: str | None
    ) -> None:
        """HTTP-date·음수·쓰레기 값은 **모른다**로 떨어뜨리고 우리 백오프로 간다."""
        slept: list[float] = []

        async def _record(seconds: float) -> None:
            slept.append(seconds)

        headers = {} if raw is None else {"retry-after": raw}
        sequenced_httpx(
            [
                _FakeResponse(429, text="busy", headers=headers),
                _FakeResponse(200, payload={"ok": 1}),
            ]
        )
        await HttpxChatTransport(
            sleep=_record, jitter=lambda: 0.0, base_delay_s=1.0, max_delay_s=60.0
        ).post_chat(
            "https://example.test/v1/chat/completions",
            headers={},
            payload={"model": "m"},
            timeout_s=1.0,
        )
        assert slept == [pytest.approx(1.0)]


class TestRetryableStatusSet:
    def test_permanent_client_errors_are_absent(self) -> None:
        for status in (400, 401, 402, 403, 404, 422):
            assert status not in RETRYABLE_STATUS

    def test_the_status_we_actually_hit_is_present(self) -> None:
        """2026-09-17 OpenRouter 실측에서 실제로 맞은 코드."""
        assert 429 in RETRYABLE_STATUS
