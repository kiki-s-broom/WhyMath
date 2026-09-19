"""provider 응답에서 *관측값*을 읽는 공용 리더 (EOS-112).

**왜 별도 좌석인가**: 응답 최상위의 모델 식별자를 읽는 일은 OpenAI 호환·Anthropic·Ollama
셋이 **같은 형태**로 한다(Mapping이면 키, 객체면 속성). 같은 매핑을 provider마다 각자
들고 있으면 반드시 갈라지고, **ARCH-58이 정확히 그 형태의 사고였다** — 좌석→핀 매핑이 두
곳에 있다가 한쪽만 고쳐져 genlog가 8일간 거짓 모델명을 적었다. 그래서 구현을 하나로 둔다.

이 모듈은 파싱만 한다 — 설정을 읽지 않고, 선언값과 대조하지 않는다(대조는 상류
`harness/anchor_round_ledger.seat_operating_rates`의 일이다).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["read_response_model_id"]


def read_response_model_id(payload: Any) -> str | None:
    """응답 최상위의 모델 식별자 — 없거나 문자열이 아니면 None.

    출처: OpenAI 호환 `/chat/completions` payload의 `model`, Anthropic Messages 응답의
    `message.model`, Ollama generate 응답의 `model`. 셋 다 "응답이 실제로 어느 모델에서
    왔는가"를 말하는 같은 자리다.

    **설정값으로 접지 않는다.** 접는 순간 이 값이 선언값(`GenerationLog.model_name`)의
    복사본이 되어 대조 축이 통째로 무의미해진다 — 둘이 항상 같으면 어긋남은 영영 0건이다.

    빈 문자열·공백도 None이다. ""를 그대로 실으면 "이름이 빈 문자열인 모델이 답했다"는
    거짓 관측이 되고, 그것은 미관측(None)과 구분되지 않은 채 '관측됨'으로 계상된다.
    """
    raw: Any = None
    if isinstance(payload, Mapping):
        raw = payload.get("model")
    elif hasattr(payload, "model"):
        raw = payload.model
    if not isinstance(raw, str):
        return None
    return raw.strip() or None
