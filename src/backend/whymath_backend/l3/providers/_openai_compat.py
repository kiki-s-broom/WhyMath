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

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from whymath_backend.l3.models import Usage

__all__ = [
    "ChatTransport",
    "HttpxChatTransport",
    "extract_text",
    "extract_usage",
]


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
    """

    async def post_chat(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_s: float,
    ) -> Any:
        """httpx로 POST. 비-2xx면 상태코드 + 응답 본문을 담은 RuntimeError."""
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover — 환경 의존(라이브러리 미설치)
            raise RuntimeError(
                "httpx가 설치되지 않아 OpenAI 호환 호출을 할 수 없습니다 " "(`pip install httpx`)."
            ) from exc
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(url, headers=dict(headers), json=dict(payload))
            if response.status_code >= 400:
                # 본문을 그대로 싣는다 — 키 값은 요청 헤더에만 있고 응답 본문에는 없다.
                raise RuntimeError(
                    f"OpenAI 호환 호출 실패 HTTP {response.status_code}: {response.text[:2000]}"
                )
            parsed: Any = response.json()
            return parsed


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
