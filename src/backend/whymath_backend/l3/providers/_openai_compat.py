"""OpenAI 호환 `/chat/completions` 공용 부품 — DeepSeek·OpenRouter 공통 (ARCH-49).

왜 `openai` SDK를 쓰지 않는가
----------------------------
둘 다 OpenAI 호환이라 `openai.AsyncOpenAI(base_url=...)`로 부를 수 있다. 그런데도 얇은
httpx 경유를 택한 이유는 **검사 가능성**이다: OpenRouter 채택 계약(ARCH-49 acceptance ⑨)은
요청 본문에 `provider.only`·`provider.allow_fallbacks`·`provider.data_collection` **세
파라미터가 항상 실릴 것**을 요구하는데, SDK를 끼우면 그 셋이 `extra_body`로 삼켜져
"무엇이 실제로 전송됐는가"를 테스트가 바이트 수준에서 볼 수 없다. 여기서는 전송 직전의
payload dict가 시임(`_ChatTransport`)에 그대로 넘어오므로, 뮤테이션 테스트가 세 파라미터
중 하나만 빠져도 RED를 낼 수 있다. 계약을 **문자열 열거가 아니라 구성된 결과로** 검사한다
(CLAUDE.md 「금지 패턴 열거 대신 산출물 검사」).

경계 메모 (CLAUDE.md 절대 금기): 이 부품이 돌려주는 텍스트는 *검증 전 원시 모델 출력*이다.
03 문서 환각 방어 파이프라인을 통과하기 전에는 *학생에게 직접 노출 금지*.

7계층: L3 내부 부품. `config`·`l3.models`만 의존한다.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from typing import Any, Protocol, runtime_checkable

from whymath_backend.l3.models import Usage

__all__ = [
    "RETRYABLE_STATUS",
    "ChatTransport",
    "HttpxChatTransport",
    "extract_text",
    "extract_usage",
    "reset_retry_count",
    "retries_in_current_call",
]

RETRYABLE_STATUS: frozenset[int] = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
"""다시 걸면 성립할 수 있는 상태코드.

**429가 여기 있는 이유**: 2026-09-17 OpenRouter 실측에서 20회 중 6회(30%)가
`429 engine_overloaded · limit_source=upstream_provider_shared_pool`로 죽었다. 재시도가
없으면 그 회차를 그냥 버리고, 그러면 "가용성 70%"라는 숫자가 **공급사의 성질이 아니라
우리 전송기의 성질**을 재게 된다. 400·401·403·404는 다시 걸어도 같으므로 뺀다 —
모델 ID 오타·키 오류·공급사 필터 거부가 전부 그쪽이고, 그것들은 즉시 실패해야 한다.
"""

_RETRY_COUNT: ContextVar[int] = ContextVar("openai_compat_retry_count", default=0)


def reset_retry_count() -> None:
    """이번 호출의 재시도 카운터를 0으로 — 회차 시작 시 호출한다."""
    _RETRY_COUNT.set(0)


def retries_in_current_call() -> int:
    """이번 호출에서 실제로 일어난 재시도 횟수.

    재시도는 **측정을 가린다** — 30% 실패를 재시도로 덮으면 리포트가 100% 성공으로 보이고,
    운영에서 같은 부하를 만났을 때 지연과 쿼터 소모가 설명되지 않는다. 그래서 횟수를
    노출해 리포트가 "몇 번 다시 걸어서 얻은 성공인지"를 말할 수 있게 한다.
    `ContextVar`라 asyncio 태스크마다 독립이다(동시 실행 회차끼리 섞이지 않는다).
    """
    return _RETRY_COUNT.get()


@runtime_checkable
class ChatTransport(Protocol):
    """`/chat/completions` 1회 왕복의 경계 — 테스트는 가짜를 주입해 payload를 그대로 본다."""

    async def post_chat(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_s: float,
    ) -> Any:
        """요청 본문을 그대로 POST하고 파싱된 JSON을 돌려준다(비스트리밍)."""
        ...


class HttpxChatTransport:
    """기본 전송 구현 — httpx 비동기 POST (지연 import).

    `httpx`를 *호출 시점에만* import한다(ollama.py·anthropic.py `_build_default_client`
    패턴) — 라이브러리 부재 환경에서도 모듈 import가 깨지지 않게.

    비-2xx는 **삼키지 않는다**. `raise_for_status()`가 던지는 `httpx.HTTPStatusError`에는
    응답 본문이 없어 "왜 거절당했는지"가 사라지므로(공급사 필터 거부·모델 ID 오타·쿼터는
    전부 4xx다), 본문을 붙인 `RuntimeError`로 바꿔 던진다 — CLAUDE.md 「측정·수집 도구를
    성공 경로만 보고 설계 금지」 ②(실패 *원인*이 남는가).

    재시도 (2026-09-17 실측 대응)
    ---------------------------
    `RETRYABLE_STATUS`에 한해 지수 백오프로 다시 건다. 공급사가 `Retry-After`를 주면
    **그 값을 우선**하고(공급사가 우리보다 자기 부하를 잘 안다), 없으면
    `base_delay * 2**n`에 지터를 얹는다 — 동시 실행 회차가 같은 순간에 몰려 재시도하면
    상류를 다시 밀어 버리기 때문이다.

    재시도는 조용하지 않다: 횟수가 `retries_in_current_call()`로 노출되고, 최종 실패
    메시지에 **몇 번 시도했는지**가 들어간다. 재시도가 보이지 않으면 "성공률 100%"가
    상류를 몇 번 두드려 얻은 것인지 리포트가 말할 수 없다.
    """

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        base_delay_s: float = 1.0,
        max_delay_s: float = 20.0,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        """`max_attempts`는 **총 시도 횟수**다(1이면 재시도 없음).

        `sleep`·`jitter`는 테스트 주입점이다 — 실제로 기다리면 회귀 테스트가 느려지고,
        지터가 난수면 대기 시간을 단언할 수 없다.
        """
        if max_attempts < 1:
            raise ValueError("max_attempts는 1 이상이어야 합니다(1 = 재시도 없음).")
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._sleep = sleep or asyncio.sleep
        self._jitter = jitter or random.random

    def _backoff_s(self, attempt: int, retry_after: float | None) -> float:
        """이번 재시도 전에 기다릴 초. 공급사의 `Retry-After`가 있으면 그것을 쓴다."""
        if retry_after is not None:
            return min(retry_after, self._max_delay_s)
        exponential: float = self._base_delay_s * float(2**attempt)
        return min(exponential, self._max_delay_s) + self._jitter() * self._base_delay_s

    async def post_chat(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_s: float,
    ) -> Any:
        """httpx로 POST. 재시도 가능 상태면 백오프 후 재시도, 최종 실패는 본문 포함 오류."""
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover — 환경 의존(라이브러리 미설치)
            raise RuntimeError(
                "httpx가 설치되지 않아 OpenAI 호환 호출을 할 수 없습니다 " "(`pip install httpx`)."
            ) from exc
        last_error = ""
        for attempt in range(self._max_attempts):
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(url, headers=dict(headers), json=dict(payload))
                if response.status_code < 400:
                    parsed: Any = response.json()
                    return parsed
                # 본문을 그대로 싣는다 — 키 값은 요청 헤더에만 있고 응답 본문에는 없다.
                last_error = (
                    f"OpenAI 호환 호출 실패 HTTP {response.status_code}: {response.text[:2000]}"
                )
                retryable = response.status_code in RETRYABLE_STATUS
                retry_after = _parse_retry_after(response.headers.get("retry-after"))
            if not retryable or attempt == self._max_attempts - 1:
                break
            _RETRY_COUNT.set(_RETRY_COUNT.get() + 1)
            await self._sleep(self._backoff_s(attempt, retry_after))
        raise RuntimeError(f"{last_error} (시도 {self._max_attempts}회)")


def _parse_retry_after(raw: str | None) -> float | None:
    """`Retry-After` 헤더를 초로. 숫자가 아니면(HTTP-date 형식 등) None.

    날짜 형식을 파싱하지 않는 것은 의도다 — 시계 오차가 붙으면 음수 대기나 과대 대기가
    나오고, 그때는 우리 백오프가 더 안전하다. **모르면 모른다고 하고 기본 경로로 간다.**
    음수·비정상 값도 None으로 떨어뜨린다(지어내지 않는다).
    """
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except (AttributeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def _first_choice_message(payload: Any) -> Any:
    """응답에서 첫 choice의 message를 방어적으로 꺼낸다(형태가 다르면 None)."""
    choices: Any
    if isinstance(payload, Mapping):
        choices = payload.get("choices")
    elif hasattr(payload, "choices"):
        choices = payload.choices
    else:
        return None
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if isinstance(first, Mapping):
        return first.get("message")
    return getattr(first, "message", None)


def extract_text(payload: Any) -> str:
    """OpenAI 호환 응답에서 생성 텍스트를 방어적으로 추출.

    `choices[0].message.content`만 읽는다 — `reasoning_content`(DeepSeek 추론 블록)는
    **의도적으로 제외**한다. 그것은 최종 답이 아니라 사고 과정이고, 하류 검증 파이프라인이
    답으로 오독하면 검산 대상이 엉뚱해진다. 형태가 예상과 다르면 빈 문자열
    (anthropic `_extract_text`·ollama와 동일한 보수적 정규화 — 값을 지어내지 않는다).
    """
    message = _first_choice_message(payload)
    if message is None:
        return ""
    content: Any
    if isinstance(message, Mapping):
        content = message.get("content")
    else:
        content = getattr(message, "content", None)
    return content if isinstance(content, str) else ""


def _coerce_token_count(value: Any) -> int | None:
    """토큰 값을 int|None으로 정규화 — 비정상 타입·음수는 None(지어내지 않음).

    bool은 int의 서브클래스지만 토큰 수가 아니다 — 배제(anthropic 제공자와 동일).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _read_usage_token(raw_usage: Any, field: str) -> int | None:
    """usage 객체/dict에서 토큰 필드 1개를 읽는다 — 부재(None)와 값 0을 **구분한다**."""
    if raw_usage is None:
        return None
    if isinstance(raw_usage, Mapping):
        return _coerce_token_count(raw_usage.get(field))
    if hasattr(raw_usage, field):
        return _coerce_token_count(getattr(raw_usage, field))
    return None


def extract_usage(payload: Any, latency_ms: float) -> Usage:
    """OpenAI 호환 응답의 usage를 `l3.models.Usage`로 정규화.

    `prompt_tokens`/`completion_tokens`가 OpenAI 호환 이름이다(Anthropic의
    `input_tokens`/`output_tokens`와 이름이 다르다 — 그래서 anthropic.py의 추출기를
    재사용하지 않는다). 캐시 축은 DeepSeek의
    `prompt_cache_hit_tokens`/`prompt_cache_miss_tokens`를 읽는다.

    ⚠️ 의미 차이를 그대로 적어 둔다(합산 금지 축): Anthropic은 캐시로 읽힌 프리픽스를
    `input_tokens`에서 **빼고** 따로 세지만, DeepSeek의 hit/miss는 `prompt_tokens`를
    **쪼갠 것**이라 `hit + miss == prompt_tokens`다. 그래서 `cache_read_input_tokens`에
    hit을 싣되 `input_tokens`에는 `prompt_tokens`를 그대로 싣는다 — 이 좌석에서 두 회계를
    맞추려 들면 어느 한쪽이 거짓이 된다. 적중률 집계는 provider별 의미를 아는 상류
    (`harness/anchor_round_ledger`)가 한다. `cache_creation_input_tokens`는 이 API에
    대응 개념이 **없으므로 항상 None**이다(0이 아니다 — 미측정 ≠ 0).
    """
    raw_usage: Any = None
    if isinstance(payload, Mapping):
        raw_usage = payload.get("usage")
    elif hasattr(payload, "usage"):
        raw_usage = payload.usage
    return Usage(
        input_tokens=_read_usage_token(raw_usage, "prompt_tokens"),
        output_tokens=_read_usage_token(raw_usage, "completion_tokens"),
        latency_ms=latency_ms,
        cache_read_input_tokens=_read_usage_token(raw_usage, "prompt_cache_hit_tokens"),
        cache_creation_input_tokens=None,
    )
