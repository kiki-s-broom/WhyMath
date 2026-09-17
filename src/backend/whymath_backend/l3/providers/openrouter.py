"""OpenRouter 경유 클라우드 제공자 — 서방 공급사가 서빙하는 오픈웨이트 (ARCH-49 ⑨⑩).

이 경로가 왜 따로 있는가
-----------------------
DeepSeek V4는 MIT 오픈웨이트라 **공식 API(중국 본토 서버)와 서방 공급사 서빙이 둘 다
존재한다.** 즉 "DeepSeek = CN 관할"은 모델의 성질이 아니라 *경로*의 성질이다. 같은 모델을
`deepinfra`(미국)가 서빙하면 그 호출의 관할은 US다. 이 제공자는 그 경로를 담당한다.

세 파라미터 계약 (옵션이 아니다)
-------------------------------
모든 호출 본문에 `provider` 블록이 **항상** 실리며 세 키를 모두 포함한다:

    "provider": {"only": [...], "allow_fallbacks": false, "data_collection": "deny"}

셋이 각각 막는 것이 다르고, **하나라도 빠지면 나머지 둘이 무의미해진다**:

- `only` — 우리가 국적·평판을 아는 공급사만. 2026-09-16 실측에서 이 모델의 엔드포인트는
  **16곳**이었고, 우리가 국적을 확인한 것은 그중 일부뿐이다(미확인: `open-inference`·
  `streamlake`·`gmicloud`·`novita`·`atlas-cloud`·`nextbit`·`mancer`·`phala`).
- `allow_fallbacks=false` — `only`가 있어도 fallback이 열려 있으면 그 공급사가 실패할 때
  **조용히 다른 곳으로 넘어간다.** 조용한 우회는 이 저장소가 금지하는 침묵 실패다.
- `data_collection="deny"` — 프롬프트를 학습에 쓰는 공급사를 OpenRouter가 걸러낸다.
  준수 엔드포인트가 없으면 우회하지 않고 **거부**하는 것이 실호출로 확인됐다(2026-09-16,
  `open-inference`·`deepinfra`·`venice`·`digitalocean`·`azure` 5곳 전건 통과).

`only`가 없으면 부수 효과가 하나 더 있다: **양자화가 공급사마다 다르다**(대부분 fp8,
`atlas-cloud`만 fp4, `venice`·`digitalocean`·`phala`·`azure`는 unknown). 공급사를 고정하지
않으면 매 호출마다 다른 정밀도가 응답해 **품질 비교 자체가 성립하지 않는다** — ARCH-49
acceptance ①의 강등전이 재는 것이 모델이 아니라 잡음이 된다.

`deny`를 안전의 단일 근거로 쓰지 않는다 (이중 방어)
--------------------------------------------------
위 (c) 실측은 OpenRouter의 **분류**이지 우리가 검증한 사실이 아니다. 2026-09-16에 제시된
2차 자료는 `open-inference`를 "프롬프트를 학습에 쓰는 대가로 rate limit을 푸는 공급사"로
설명해 deny 통과와 정면 충돌하는데, 1차 자료(`openrouter.ai` 문서)는 조사 세션의 egress
프록시가 차단해 확정하지 못했다. 그래서 설계는 **어느 쪽이 참이어도 성립**해야 한다:
ⓐ `data_collection="deny"`(OpenRouter 판정) ⓑ `only`=우리가 아는 공급사만(우리 판정).
ⓑ가 단독으로도 성립하므로 OpenRouter의 분류를 신뢰하지 않아도 계약이 유지된다 —
CLAUDE.md 「판정치를 외부 관측 인프라에만 의존 금지·이중 회계」의 프로바이더 축 적용이다.
그래서 `open-inference`는 최저가($0.05/$0.14)임에도 기본 허용목록에 **없다**.

Preset 기능은 쓰지 않는다 — 설정이 웹 UI에 있으면 저장소 게이트가 검사할 수 없어 이중
진실 원천이 된다(요청의 명시 파라미터가 Preset을 덮어쓰므로 코드가 항상 이긴다).

경계 메모 (CLAUDE.md 절대 금기): 반환 텍스트는 *검증 전 원시 모델 출력*이다 —
03 문서 환각 방어 파이프라인 통과 전 *학생에게 직접 노출 금지*.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from whymath_backend.config import Settings, get_settings
from whymath_backend.l3.models import CostTier, GenerationResult, RoutingDecision
from whymath_backend.l3.provider_jurisdiction import Jurisdiction
from whymath_backend.l3.providers._openai_compat import (
    ChatTransport,
    HttpxChatTransport,
    extract_text,
    extract_usage,
)
from whymath_backend.l3.router import _as_cost_tier

__all__ = [
    "PROVIDER_JURISDICTIONS",
    "DATA_COLLECTION_DENY",
    "OpenRouterProvider",
    "OpenRouterStatus",
    "build_provider_block",
    "jurisdiction_of_slugs",
    "provider_slug_from_tag",
]

DATA_COLLECTION_DENY: Final[str] = "deny"
"""`provider.data_collection`에 싣는 유일한 값 — 이 제공자는 다른 값을 만들지 않는다."""


# 공급사 slug → 관할. **우리가 국적을 아는 것만** 적는다. 여기 없는 slug는 `UNKNOWN`이고,
# UNKNOWN 관할은 허용 등급이 빈 집합이라 아무 요청도 통과하지 못한다(fail-closed).
#
# 여기 없다는 것은 "중국계다"가 아니라 **"우리가 확인하지 않았다"**는 뜻이다 — 2026-09-16
# 실측 당시 이 모델의 엔드포인트는 16곳이었고 국적 미확인이 다수다(`open-inference`·
# `streamlake`·`gmicloud`·`novita`·`atlas-cloud`·`nextbit`·`mancer`·`phala`).
#
# **두 줄의 근거 등급이 다르다는 것을 표기한다**(모르면 모른다고):
#   · US 2곳 — `data_collection="deny"` 필터 통과를 **실호출로 확인**했고 미국 법인이다.
#     기본 허용목록(`config.openrouter_allowed_providers`)은 이 둘뿐이다.
#   · CN 3곳 — **회사로 아는 것**이지 API가 말해 주는 값이 아니다(엔드포인트 응답에는 국적
#     필드가 없다). 그래도 적는 이유는 "중국계로 안다"와 "모른다"가 **다른 사실**이기
#     때문이다 — 전자는 CN 정책(합성 프로브만·코퍼스 opt-in)이 적용되고 후자는 전건
#     차단이다. 둘을 같은 칸에 접으면 나중에 근거를 되짚을 수 없다.
# 목록을 늘리려면 법인 국적의 근거를 등급과 함께 남긴다.
PROVIDER_JURISDICTIONS: Final[Mapping[str, Jurisdiction]] = {
    "deepinfra": Jurisdiction.US,
    "digitalocean": Jurisdiction.US,
    "siliconflow": Jurisdiction.CN,
    "alibaba": Jurisdiction.CN,
    "baidu": Jurisdiction.CN,
}


def provider_slug_from_tag(tag: str) -> str:
    """OpenRouter endpoints 응답의 `tag` → 공급사 slug (2026-09-16 실측 규칙).

    `tag`는 `공급사/양자화` 형태이고 slug는 `/` **앞부분**이다(`deepinfra/fp8`→`deepinfra`).
    `/`가 없으면 전체가 slug다. 앞뒤 공백은 제거한다 — 설정 문자열이 사람 손을 타므로.
    실호출로 확인했다: `only=["deepinfra"]`+`allow_fallbacks=false`로 부르면 응답의
    `PROVIDER`가 `DeepInfra`다.
    """
    return tag.strip().split("/", 1)[0]


def jurisdiction_of_slugs(slugs: Sequence[str]) -> Jurisdiction:
    """허용 공급사 목록 전체의 관할 — **가장 보수적인 하나**로 접는다.

    규칙: 빈 목록이거나 우리가 모르는 slug가 하나라도 섞이면 `UNKNOWN`이고, 전부 같은
    관할이면 그 관할이며, 서로 다른 관할이 섞이면 `UNKNOWN`이다. 마지막 규칙이 중요하다 —
    "US 한 곳 + CN 한 곳"을 허용하면 `allow_fallbacks=false`라 해도 *어느 쪽이 응답할지*는
    OpenRouter가 정하므로, 그 호출의 관할을 우리가 말할 수 없다. 말할 수 없으면 모른다고
    한다(CLAUDE.md "모르면 모른다고").

    빈 목록을 `UNKNOWN`으로 두는 것이 fail-closed의 핵심이다: `openrouter_allowed_providers`
    를 비워도 "아무나 허용"이 되지 않고 **전건 차단**된다.
    """
    if not slugs:
        return Jurisdiction.UNKNOWN
    resolved = {
        PROVIDER_JURISDICTIONS.get(provider_slug_from_tag(slug), Jurisdiction.UNKNOWN)
        for slug in slugs
    }
    if len(resolved) != 1:
        return Jurisdiction.UNKNOWN
    return resolved.pop()


def build_provider_block(allowed_providers: Sequence[str]) -> dict[str, Any]:
    """요청 본문의 `provider` 블록 — 세 파라미터를 **항상** 함께 만든다.

    이 함수가 계약의 단일 좌석이다. 호출부가 셋 중 하나를 빼고 조립할 수 있는 경로를 남기지
    않으려고 `provider` 블록 자체를 여기서만 만든다(`OpenRouterProvider`는 이 반환값을
    그대로 payload에 넣는다). 테스트는 *구성된 payload*를 보고 셋의 존재와 값을 판정하며,
    이 함수에서 어느 한 줄을 지워도 RED가 나온다.

    slug는 `tag` 형태(`deepinfra/fp8`)로 들어와도 받아 준다 — 설정에 tag를 그대로 붙여
    넣는 실수가 `only`를 조용히 무효화하지 않게 정규화한다.

    빈 목록은 **오류**다. `{"only": []}`를 보내면 OpenRouter가 이를 제약 없음으로 읽어
    16곳 전체가 후보가 되는데, 그러면 우리 쪽 방어층 ⓑ가 통째로 사라진 채 요청이 나간다 —
    조용한 무제한보다 명확한 실패가 낫다(fail-closed).
    """
    slugs = [provider_slug_from_tag(slug) for slug in allowed_providers if slug.strip()]
    if not slugs:
        raise ValueError(
            "OpenRouter 허용 공급사 목록이 비어 있습니다 — provider.only를 빈 채로 보내면 "
            "제약 없음으로 해석돼 국적 미확인 공급사로 나갈 수 있습니다. "
            "WHYMATH_OPENROUTER_ALLOWED_PROVIDERS에 국적을 확인한 slug를 지정하세요."
        )
    return {
        "only": slugs,
        "allow_fallbacks": False,
        "data_collection": DATA_COLLECTION_DENY,
    }


@dataclass(slots=True, frozen=True)
class OpenRouterStatus:
    """OpenRouter 준비 상태 보고 — 네트워크를 타지 않는 *구성* 점검.

    `reachable`을 두지 않는다(AnthropicStatus와 다른 점). 도달성 확인에는 호출이 필요한데
    OpenRouter의 조회 엔드포인트는 라우팅 계약(세 파라미터)을 거치지 않으므로, 여기서
    "닿았다"를 보고하면 *계약을 통과한 경로가 살아 있다*는 뜻으로 오독된다. 구성 점검만
    한다 — 키·허용목록·관할 세 가지가 맞는지.
    """

    configured: bool
    allowed_providers: tuple[str, ...]
    jurisdiction: Jurisdiction
    error: str | None = None


class OpenRouterProvider:
    """OpenRouter 경유 생성 제공자 — interfaces.LLMProvider 충족.

    클라우드 결정(CLOUD_MID/CLOUD_HIGH)만 처리한다. 관할 판정(어느 등급을 보내도 되는가)은
    이 제공자가 아니라 `CompositeProvider`가 디스패치 직전에 한다 — 관할은 *프로바이더의
    메타데이터*이고 등급 판정은 *라우팅 결정*에 대한 것이라, 둘을 한 곳에서 하면 provider가
    자기 자신을 검열하는 구조가 되어 우회 경로(provider 직접 호출)가 생긴다.
    이 제공자의 관할은 `jurisdiction` 프로퍼티가 노출하고 디스패처가 그것을 읽는다.
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
        """전송 가능 여부 — 키가 있고(또는 전송이 주입됐고) 허용목록이 비어 있지 않은가."""
        settings = self._resolved_settings
        if not settings.openrouter_allowed_providers:
            return False
        if self._transport is not None:
            return True
        return settings.openrouter_configured

    @property
    def jurisdiction(self) -> Jurisdiction:
        """이 제공자가 실제로 닿는 관할 — 허용목록에서 유도한다(선언이 아니라 계산).

        설정을 바꾸면 관할도 따라 바뀐다. 국적 미상 slug를 넣으면 `UNKNOWN`이 되고, 그러면
        허용 등급이 빈 집합이라 디스패처가 전건 차단한다 — 허용목록 오염이 조용한 통과가
        아니라 **명시적 차단**으로 나타난다.
        """
        return jurisdiction_of_slugs(self._resolved_settings.openrouter_allowed_providers)

    def _resolve_model(self, cost: CostTier, settings: Settings) -> str:
        """클라우드 티어 → OpenRouter 모델 slug. LOCAL은 거부(OllamaProvider 담당)."""
        if cost is CostTier.CLOUD_MID:
            return settings.openrouter_model_mid
        if cost is CostTier.CLOUD_HIGH:
            return settings.openrouter_model_high
        raise ValueError(
            f"OpenRouterProvider는 클라우드 결정만 처리한다(받은 cost_tier={cost.value}). "
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
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        """라우터 결정에 따라 OpenRouter 경유로 생성 (LLMProvider 구현).

        선택 인자 처리는 **각 축이 실제로 가능한지**로 갈린다(조용한 무시 없음):
        - `images` → 거부. 멀티모달은 로컬 Qwen3-VL 경유이며(미성년자 프라이버시·로컬 우선)
          이 경로는 미배선이다.
        - `temperature` → 그대로 전달(OpenAI 호환 `temperature`).
        - `seed` → 그대로 전달. OpenAI 호환 API에는 `seed` 파라미터가 **있다**(Anthropic과
          다른 점). 다만 결정론은 공급사·양자화에 따라 보장되지 않으므로, 기록된 seed는
          "전달했다"는 사실이며 재현 성공을 뜻하지 않는다.
        - `json_schema` → 거부. OpenRouter의 structured output 지원은 공급사마다 다르고
          `only`로 고정한 공급사가 그것을 지원하는지 실측하지 않았다 — 지원 여부를 모르는 채
          스키마를 실으면 "문법이 강제됐다"고 거짓말하는 경로가 된다(모르면 모른다고).
        """
        if images:
            raise RuntimeError(
                "OpenRouterProvider는 멀티모달(images) 입력을 지원하지 않습니다 — 비전 인식은 "
                "로컬 Qwen3-VL(VISION 패밀리) 경유입니다(클라우드 비전 미배선)."
            )
        if json_schema is not None:
            raise RuntimeError(
                "OpenRouterProvider는 json_schema(문법 제약 디코딩)를 지원하지 않습니다 — "
                "structured output 지원이 공급사마다 다르고 허용목록 공급사의 지원 여부를 "
                "실측하지 않았습니다. 프롬프트+관대 파서로 동작하세요(조용한 무시 금지)."
            )
        cost = _as_cost_tier(decision.cost_tier)
        settings = self._resolved_settings
        model_id = self._resolve_model(cost, settings)
        if not self.configured:
            raise RuntimeError(
                "OpenRouter가 미설정이라 생성을 할 수 없습니다 — 키"
                "(WHYMATH_OPENROUTER_API_KEY 또는 OPENROUTER_API_KEY)와 허용 공급사 목록"
                "(WHYMATH_OPENROUTER_ALLOWED_PROVIDERS)이 둘 다 필요합니다."
            )

        payload: dict[str, Any] = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": settings.openrouter_max_tokens,
            # 계약 — 세 파라미터를 함께 만드는 단일 좌석(build_provider_block).
            "provider": build_provider_block(settings.openrouter_allowed_providers),
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if seed is not None:
            payload["seed"] = seed

        transport = self._transport if self._transport is not None else HttpxChatTransport()
        headers = {
            # 시크릿은 *여기서, 헤더로 나갈 때만* 평문을 꺼낸다(anthropic.py와 동일 규율).
            "Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        start = time.monotonic()
        response = await transport.post_chat(
            f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            payload=payload,
            timeout_s=settings.openrouter_request_timeout_s,
        )
        latency_ms = (time.monotonic() - start) * 1000.0
        return GenerationResult(
            text=extract_text(response),
            usage=extract_usage(response, latency_ms),
        )

    async def check_status(self) -> OpenRouterStatus:
        """구성 점검(네트워크 없음) — 키·허용목록·유도된 관할을 보고한다.

        허용목록이 비었거나 관할이 `UNKNOWN`이면 그 사실을 `error`에 담는다 — /status가
        "설정은 됐는데 아무것도 못 보낸다"는 상태를 침묵하지 않게 한다.
        """
        settings = self._resolved_settings
        allowed = tuple(settings.openrouter_allowed_providers)
        jurisdiction = self.jurisdiction
        error: str | None = None
        if not allowed:
            error = "허용 공급사 목록이 비어 있음 — 전건 차단 상태"
        elif jurisdiction is Jurisdiction.UNKNOWN:
            error = (
                "허용 공급사의 관할을 확정할 수 없음(국적 미확인 slug 또는 관할 혼재) — "
                "전건 차단 상태"
            )
        return OpenRouterStatus(
            configured=self.configured,
            allowed_providers=allowed,
            jurisdiction=jurisdiction,
            error=error,
        )
