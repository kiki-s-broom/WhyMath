"""DeepSeek 공식 API 제공자 — CN 관할 직행 경로 (ARCH-49 ③⑦⑧).

이 경로의 성질
-------------
`api.deepseek.com`은 **중국 본토 서버 전용**이고 데이터 레지던시 선택지가 없다(2026-09 실측).
따라서 이 제공자의 관할은 `Jurisdiction.CN`으로 **고정**이다 — 설정으로 바꿀 수 없다
(`jurisdiction`이 상수 프로퍼티인 이유). 같은 모델의 서방 공급사 경유는 별도 좌석
(`providers/openrouter.py`)이며 그쪽 관할은 허용목록에서 *유도*된다.

관할이 CN이라는 사실이 뜻하는 것은 `l3.provider_jurisdiction`이 정한다: 기본 허용 등급은
`WHYMATH_GENERATED`(합성 프로브)뿐이고, 자체 저작 코퍼스(`INTERNAL_OWNED`)를 태우려면
`settings.deepseek_allow_internal_corpus` opt-in이 필요하다. 학생 저작
(`USER_GENERATED`)은 **어떤 설정으로도 열리지 않는다** — `export=False`라 허용 집합에
들어올 방법이 없고, 애초에 라우터의 1차 게이트가 그런 요청을 `LOCAL`로 강등한다.

모델 ID는 실측값만 쓴다
----------------------
2026-09-16 Kiki 머신에서 유효 키로 `GET https://api.deepseek.com/models`를 조회한 결과
반환된 id는 정확히 두 개다 — **`deepseek-flash`** · **`deepseek-v4-pro`**. 웹 자료 3곳이
일치해 적고 있는 `deepseek-v4-flash`는 **API가 받지 않는 이름**이다(제품 표기 ≠ API id).
기본 핀은 `config.deepseek_model_mid/high`에 있고 env로 오버라이드한다. 새 ID를 핀할
때도 같은 방식으로 실 API 조회를 먼저 한다 — CLAUDE.md 「환경 사실의 추론 등재 금지」.

비용 축의 시간대 구분 (측정 리포트가 알아야 할 사실)
---------------------------------------------------
DeepSeek 공식 API는 피크(UTC 01:00-04:00·06:00-10:00, 월~금)와 오프피크의 단가가 정확히
2배 차이다(2026-08-16 개정). **시간축 라우팅은 만들지 않는다** — 한국시간 환산 시 피크가
10:00-13:00·15:00-19:00 KST라 학생 사용 피크(평일 저녁·주말)가 오프피크와 겹치기 때문이다.
대신 `pricing_window`가 호출 시각의 요금 구간을 돌려주어, 측정 리포트가 두 구간을 **분리
집계**할 수 있게 한다(같은 통에 넣으면 단가 2배 차이가 평균에 녹아 비교가 무의미해진다).

경계 메모 (CLAUDE.md 절대 금기): 반환 텍스트는 *검증 전 원시 모델 출력*이다 —
03 문서 환각 방어 파이프라인 통과 전 *학생에게 직접 노출 금지*.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from whymath_backend.config import Settings, get_settings
from whymath_backend.l3.models import CostTier, GenerationResult, RoutingDecision
from whymath_backend.l3.provider_jurisdiction import Jurisdiction
from whymath_backend.l3.providers._openai_compat import (
    ChatTransport,
    HttpxChatTransport,
    extract_text,
    extract_usage,
    retries_in_current_call,
    retries_since,
)
from whymath_backend.l3.router import _as_cost_tier

__all__ = [
    "PEAK_WINDOWS_UTC",
    "PRICING_OFF_PEAK",
    "PRICING_PEAK",
    "DeepSeekProvider",
    "DeepSeekStatus",
    "pricing_window",
]

PRICING_PEAK: Final[str] = "peak"
"""요금 구간 — 피크(오프피크의 2배 단가)."""

PRICING_OFF_PEAK: Final[str] = "off_peak"
"""요금 구간 — 오프피크."""

# 피크 구간(UTC, 월~금). 각 원소는 [시작시, 종료시) 반개구간이다 — 경계에서 두 구간에
# 동시에 속하지 않게 반개구간으로 둔다. 2026-08-16 공식 개정 기준.
PEAK_WINDOWS_UTC: Final[tuple[tuple[int, int], ...]] = ((1, 4), (6, 10))


def pricing_window(moment: datetime) -> str:
    """호출 시각 → 요금 구간(`peak`/`off_peak`) — 측정 리포트의 분리 집계 키.

    주말(토·일)은 전부 오프피크다. 시각은 **UTC로 환산해** 판정한다 — naive datetime이
    오면 로컬 시간대로 추측하지 않고 `ValueError`를 던진다. 시간대 추측은 요금 구간을
    통째로 뒤집을 수 있고(KST는 UTC+9라 구간이 다른 날로 넘어간다), 잘못된 구간 라벨은
    측정 회차를 조용히 오염시킨다(CLAUDE.md 「환경 사실의 추론 등재 금지」의 시각 축).
    """
    if moment.tzinfo is None:
        raise ValueError(
            "pricing_window는 시간대를 아는(aware) datetime만 받는다 — naive 값의 "
            "시간대를 추측하면 요금 구간 라벨이 통째로 뒤집힐 수 있다(UTC 명시 필요)."
        )
    utc = moment.astimezone(UTC)
    if utc.weekday() >= 5:  # 토(5)·일(6)
        return PRICING_OFF_PEAK
    for start, end in PEAK_WINDOWS_UTC:
        if start <= utc.hour < end:
            return PRICING_PEAK
    return PRICING_OFF_PEAK


@dataclass(slots=True, frozen=True)
class DeepSeekStatus:
    """DeepSeek 공식 API 준비 상태 보고 — 네트워크를 타지 않는 *구성* 점검.

    `jurisdiction`·`allow_internal_corpus`를 함께 보고한다: 이 경로는 키가 있다고 해서
    무엇이든 보낼 수 있는 것이 아니라 **등급 정책이 함께 걸려 있고**, /status가 그 사실을
    침묵하면 운영자가 "키 넣었는데 왜 막히지"를 코드에서 찾게 된다.
    """

    configured: bool
    jurisdiction: Jurisdiction
    allow_internal_corpus: bool
    error: str | None = None


class DeepSeekProvider:
    """DeepSeek 공식 API 생성 제공자 — interfaces.LLMProvider 충족.

    클라우드 결정(CLOUD_MID/CLOUD_HIGH)만 처리한다. 등급 판정은 이 제공자가 아니라
    `CompositeProvider`가 디스패치 직전에 한다(openrouter.py와 같은 이유 — provider가
    자기를 검열하면 직접 호출 우회 경로가 생긴다). 이 제공자는 자기 관할만 선언한다.
    """

    def __init__(
        self,
        *,
        transport: ChatTransport | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._transport = transport
        self._settings = settings

    @property
    def _resolved_settings(self) -> Settings:
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    @property
    def configured(self) -> bool:
        """전송 가능 여부 — 전송이 주입됐거나 API 키가 있는가."""
        if self._transport is not None:
            return True
        return self._resolved_settings.deepseek_configured

    @property
    def jurisdiction(self) -> Jurisdiction:
        """항상 `CN` — 본토 서버 전용이고 레지던시 선택지가 없다(설정으로 못 바꾼다)."""
        return Jurisdiction.CN

    @property
    def allow_internal_corpus(self) -> bool:
        """자체 저작 코퍼스(`INTERNAL_OWNED`)를 이 관할로 보내는 opt-in — 기본 False."""
        return self._resolved_settings.deepseek_allow_internal_corpus

    def _resolve_model(self, cost: CostTier, settings: Settings) -> str:
        """클라우드 티어 → DeepSeek 모델 ID. LOCAL은 거부(OllamaProvider 담당)."""
        if cost is CostTier.CLOUD_MID:
            return settings.deepseek_model_mid
        if cost is CostTier.CLOUD_HIGH:
            return settings.deepseek_model_high
        raise ValueError(
            f"DeepSeekProvider는 클라우드 결정만 처리한다(받은 cost_tier={cost.value}). "
            "로컬 티어는 OllamaProvider 담당이다(03a §A.0)."
        )

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        """라우터 결정에 따라 DeepSeek 공식 API로 생성 (LLMProvider 구현).

        선택 인자 처리(조용한 무시 없음): `images`·`json_schema`는 거부하고
        (비전은 로컬 경유·문법 제약 미실측), `temperature`·`top_p`·`seed`는 OpenAI 호환
        파라미터로 그대로 전달한다. seed는 "전달했다"는 사실이며 결정론을 보장하지 않는다.
        `top_p`는 미지정(기본)이면 키 자체를 싣지 않아 공급사 기본값이 쓰인다 — 기존 동작
        무변경이며, 지정 시에만 실린다(EOS-121 선결조건 A·temperature와 같은 규약).
        """
        if images:
            raise RuntimeError(
                "DeepSeekProvider는 멀티모달(images) 입력을 지원하지 않습니다 — 비전 인식은 "
                "로컬 Qwen3-VL(VISION 패밀리) 경유입니다(클라우드 비전 미배선)."
            )
        if json_schema is not None:
            raise RuntimeError(
                "DeepSeekProvider는 json_schema(문법 제약 디코딩)를 지원하지 않습니다 — "
                "문법 강제 여부를 실측하지 않았습니다. 프롬프트+관대 파서로 동작하세요 "
                "(조용한 무시 금지)."
            )
        cost = _as_cost_tier(decision.cost_tier)
        settings = self._resolved_settings
        model_id = self._resolve_model(cost, settings)
        if not self.configured:
            raise RuntimeError(
                "DeepSeek API 키가 미설정이라 생성을 할 수 없습니다 "
                "(WHYMATH_DEEPSEEK_API_KEY 또는 DEEPSEEK_API_KEY)."
            )

        payload: dict[str, Any] = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": settings.deepseek_max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        # EOS-121 선결조건 A — temperature와 같은 규약(지정 시에만 키를 싣는다·None 전송 금지).
        if top_p is not None:
            payload["top_p"] = top_p
        if seed is not None:
            payload["seed"] = seed

        transport = self._transport if self._transport is not None else HttpxChatTransport()
        headers = {
            # 시크릿은 *여기서, 헤더로 나갈 때만* 평문을 꺼낸다(anthropic.py와 동일 규율).
            "Authorization": f"Bearer {settings.deepseek_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        # 재시도 카운터는 ContextVar라 **회차 내내 누적**된다 — 호출 전후 차분을 잡아야
        # 이 호출 1건의 값이 된다(EOS-112). `reset_retry_count()`를 여기서 부르지 않는
        # 이유는 그것이 *공유 상태를 지우는* 행위라, 바깥에서 회차 단위로 세고 있는
        # 소비자(`harness/provider_accuracy_battle`)의 회계를 말없이 뒤엎기 때문이다.
        retries_before = retries_in_current_call()
        start = time.monotonic()
        response = await transport.post_chat(
            f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            payload=payload,
            timeout_s=settings.deepseek_request_timeout_s,
        )
        latency_ms = (time.monotonic() - start) * 1000.0
        return GenerationResult(
            text=extract_text(response),
            usage=extract_usage(
                response,
                latency_ms,
                retries=retries_since(retries_before),
            ),
        )

    async def check_status(self) -> DeepSeekStatus:
        """구성 점검(네트워크 없음) — 키·관할·opt-in 상태를 보고한다.

        도달성을 재지 않는 이유는 openrouter.py와 같다: 조회 엔드포인트가 살아 있다는 것이
        *등급 게이트를 통과한 경로가 산다*는 뜻은 아니라, 그 보고가 오독을 부른다.
        """
        error: str | None = None
        if not self.configured:
            error = "DeepSeek API 키 미설정"
        return DeepSeekStatus(
            configured=self.configured,
            jurisdiction=self.jurisdiction,
            allow_internal_corpus=self.allow_internal_corpus,
            error=error,
        )
