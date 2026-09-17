"""Anthropic Claude 클라우드 LLM 제공자 — interfaces.LLMProvider 구현 (M1.2-live S5).

라우터 결정(RoutingDecision)을 받아 Anthropic Claude로 실제 생성을 수행한다.
클라우드(CostTier.CLOUD_MID/CLOUD_HIGH) 결정만 처리하며, 로컬은 OllamaProvider 담당이다.
디스패치(로컬↔클라우드 분기)는 CompositeProvider가 cost_tier로 수행한다(composite.py).

설계 정본: `docs/architecture/03a_l3_router_design.md` §C.1(축1 클라우드 규칙)·§A.0(모델
풀: CLOUD_MID=Sonnet 4.6·CLOUD_HIGH=Opus 4.7)·§C.4(클라우드는 mode="sync")·§H 후속 4
("클라우드 티어 실제 연동"). 테스트 주입·지연 import·시크릿 처리 패턴은
providers/ollama.py(`_OllamaClient` 시임)·trace/langfuse_sink.py(SecretStr를 클라이언트
생성 순간에만 평문 추출)를 미러링한다.

SDK 규약 메모 (Anthropic Python SDK): `AsyncAnthropic.messages.create(model=,max_tokens=,
system=,messages=[{"role":"user","content":...}])`. 응답은 content 블록 리스트이며
`type=="text"` 블록의 `.text`만 모은다(thinking/tool 블록 제외). 헬스체크는
`models.list()`(토큰 비용 0). **Opus 4.7는 temperature/top_p/top_k/budget_tokens를
거부(400)하므로** 샘플링·thinking 인자를 보내지 않는다(plain create) — 두 모델 모두 안전.
프롬프트 캐싱·thinking/effort 튜닝은 라이브 키 보유 보정 과제로 미룬다(S5 범위 밖).

경계 메모 (CLAUDE.md 절대 금기): 이 제공자가 반환하는 텍스트는 *검증 전 원시 모델
출력*이다. 03 문서 환각 방어 파이프라인(스키마→SymPy/Lean→PRM→자기검증→사람검수)을
통과하기 전에는 *학생에게 직접 노출 금지* ("LLM 응답을 검증 없이 학생에게 제공 금지").
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from whymath_backend.config import Settings, get_settings
from whymath_backend.l3.models import CostTier, GenerationResult, RoutingDecision, Usage
from whymath_backend.l3.provider_jurisdiction import Jurisdiction
from whymath_backend.l3.router import _as_cost_tier


# ──────────────────────────────────────────────────────────────────────────
# Anthropic 클라이언트 추상화 (테스트 주입용) — ollama.py·langfuse_sink.py 시임 패턴.
# 실제 `anthropic.AsyncAnthropic`와 동형이지만 우리가 *실제로 쓰는* 표면만 좁게 선언한다.
# 단위테스트는 가짜 클라이언트를 주입해 라이브러리·네트워크·API 키 없이 검증한다.
# ──────────────────────────────────────────────────────────────────────────
@runtime_checkable
class _Messages(Protocol):
    """`client.messages`의 최소 인터페이스 — 단발 메시지 생성."""

    async def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Any:
        """메시지 생성 (anthropic messages.create API의 부분집합).

        `**kwargs`는 선택적 튜닝 인자(output_config·thinking·cache_control)를 *설정된
        경우에만* 전달하기 위함이다 — None을 넘기지 않고 키 자체를 생략한다(SDK NotGiven
        규약 충돌 회피).
        """
        ...


@runtime_checkable
class _Models(Protocol):
    """`client.models`의 최소 인터페이스 — 모델 목록(헬스체크용, 토큰 비용 0)."""

    async def list(self) -> Any:
        """모델 목록 조회 (anthropic models.list API)."""
        ...


@runtime_checkable
class _AnthropicClient(Protocol):
    """anthropic.AsyncAnthropic의 최소 인터페이스 (구조적 타이핑).

    우리는 `messages.create`(생성)와 `models.list`(헬스체크)만 쓴다. 반환 타입은
    SDK 버전별로 pydantic 객체일 수 있어 `Any`로 두고 제공자 쪽에서 방어적으로 정규화한다.
    """

    messages: _Messages
    models: _Models


# ──────────────────────────────────────────────────────────────────────────
# /status 보고용 값 객체
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class AnthropicStatus:
    """Anthropic 클라우드 준비 상태 보고 (/status 엔드포인트용).

    `configured`=키 존재 여부(전송 가능). `reachable`=라이브 도달·인증 확인(models.list
    성공). 키 미설정이면 네트워크 없이 configured=False, reachable=False로 보고한다 —
    /status는 클라우드가 미구성이거나 도달 불가여도 500을 던지지 않고 *보고*한다.
    """

    configured: bool
    reachable: bool
    error: str | None = None


def resolve_cloud_model(cost_tier: object, settings: Settings) -> str:
    """축1 클라우드 티어(CostTier) → 실제 Anthropic 모델 ID 해석 (03a §A.0).

    CLOUD_MID→Sonnet 4.6(anthropic_model_mid), CLOUD_HIGH→Opus 4.7(anthropic_model_high).
    모델 ID는 Settings에서 읽어 env 오버라이드를 허용한다. LOCAL은 router.resolve_model
    담당이라 여기서는 거부한다(호출 전 cost_tier로 분기되므로 방어적 가드).
    """
    cost = _as_cost_tier(cost_tier)
    if cost is CostTier.CLOUD_MID:
        return settings.anthropic_model_mid
    if cost is CostTier.CLOUD_HIGH:
        return settings.anthropic_model_high
    raise ValueError(
        f"resolve_cloud_model은 클라우드 티어에만 적용된다(받은 {cost.value}). "
        "LOCAL은 router.resolve_model 담당이다(03a §A.0)."
    )


def _extract_text(message: Any) -> str:
    """anthropic messages.create 응답에서 생성 텍스트를 방어적으로 추출.

    응답의 `content`는 블록 리스트다(pydantic 객체 또는 dict). `type=="text"` 블록의
    `.text`만 이어붙인다 — thinking/tool_use 등 비텍스트 블록은 건너뛴다. 형태가 예상과
    다르면 빈 문자열(ollama `_extract_text`와 동일한 보수적 정규화).
    """
    content: Any
    if hasattr(message, "content"):
        content = message.content
    elif isinstance(message, dict):
        content = message.get("content")
    else:
        return ""

    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        block_type: Any = None
        if hasattr(block, "type"):
            block_type = block.type
        elif isinstance(block, dict):
            block_type = block.get("type")
        if block_type != "text":
            continue
        text: Any = None
        if hasattr(block, "text"):
            text = block.text
        elif isinstance(block, dict):
            text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _coerce_token_count(value: Any) -> int | None:
    """usage 필드값을 int|None으로 방어적 정규화 — 비정상 타입·음수는 None(지어내지 않음)."""
    # bool은 int의 서브클래스지만 토큰 수가 아니다 — 배제.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _read_usage_token(raw_usage: Any, field: str) -> int | None:
    """usage 객체/dict에서 토큰 필드 1개를 방어적으로 읽는다(pydantic·dict 양쪽 흡수).

    필드가 없으면 None이다 — 필드 부재와 값 0을 **구분한다**. 캐시 축(EOS-99)에서 이 구분이
    판정을 가른다: 부재는 "캐시 개념이 없는 provider이거나 못 읽었다"(미측정)이고, 0은
    "읽었는데 적중이 없었다"(실측)다. 둘을 같은 칸으로 접으면 '켰지만 작동 안 함'이
    '해당 없음'으로 위장된다.
    """
    if raw_usage is None:
        return None
    if hasattr(raw_usage, field):
        return _coerce_token_count(getattr(raw_usage, field))
    if isinstance(raw_usage, dict):
        # dict에 키가 아예 없으면 .get이 None을 주고, _coerce_token_count가 None을 돌려준다.
        return _coerce_token_count(raw_usage.get(field))
    return None


def _extract_usage(message: Any, latency_ms: float) -> Usage:
    """anthropic messages.create 응답에서 실측 usage를 방어적으로 추출 (S1 게이트 ②).

    응답의 `usage`(pydantic 객체 또는 dict)에서 `input_tokens`/`output_tokens`와
    **프롬프트 캐시 2종**(`cache_read_input_tokens`·`cache_creation_input_tokens` — EOS-99)을
    포착한다. 형태가 예상과 다르면 토큰은 None — *값을 지어내지 않는다*(_extract_text와
    동일한 보수적 정규화). 지연(latency_ms)은 호출부가 monotonic으로 잰 실측값을 그대로 싣는다.

    캐시 2종을 읽는 이유(CLAUDE.md "작동 신호 없는 알고리즘 부착 금지"): `settings.
    anthropic_prompt_caching`을 켜면 요청에 `cache_control`이 실리지만, **적중했는지는
    응답 usage에만 있다.** 이 두 필드를 안 읽으면 플래그를 켠 상태와 캐시가 실제로 작동하는
    상태를 구분할 수단이 없다(짧은 프리픽스는 최소 토큰 미만이라 조용히 무효가 된다).
    SDK가 이 필드를 노출하지 않는 구버전이면 부재 → None(미측정)이 정직한 값이다.
    """
    raw_usage: Any = None
    if hasattr(message, "usage"):
        raw_usage = message.usage
    elif isinstance(message, dict):
        raw_usage = message.get("usage")

    return Usage(
        input_tokens=_read_usage_token(raw_usage, "input_tokens"),
        output_tokens=_read_usage_token(raw_usage, "output_tokens"),
        latency_ms=latency_ms,
        cache_read_input_tokens=_read_usage_token(raw_usage, "cache_read_input_tokens"),
        cache_creation_input_tokens=_read_usage_token(raw_usage, "cache_creation_input_tokens"),
    )


def _build_default_client(settings: Settings) -> _AnthropicClient:
    """기본 anthropic AsyncAnthropic 클라이언트 생성 (지연 import).

    `anthropic` 라이브러리가 없는 환경(CI 단위테스트)에서도 모듈 import가 깨지지 않도록
    *호출 시점에만* import한다 (ollama.py·langfuse_sink.py `_build_default_client` 패턴).
    이 함수는 *키가 설정됐을 때만* 호출된다(AnthropicProvider._get_client가 보장).

    시크릿(SecretStr)은 *여기서, 클라이언트 생성 인자로 전달할 때만* 평문을 꺼낸다
    (`get_secret_value()`). 키를 로그/repr로 내보내지 않는다(CLAUDE.md 보안 금기). 생성자
    자체는 네트워크를 타지 않는다(실제 호출 시 연결).
    """
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:  # pragma: no cover — 환경 의존(라이브러리 미설치)
        raise RuntimeError(
            "anthropic Python 클라이언트가 설치되지 않았습니다. "
            "`pip install anthropic` 후 다시 시도하세요."
        ) from exc
    # cast 사유: anthropic이 제공하는 정밀 스텁(messages.create의 풍부한 overload·NotGiven
    # 센티넬·반환 타입 Message)은 우리의 좁은 구조적 시임 `_AnthropicClient`와 형태가 어긋난다.
    # 우리가 실제로 쓰는 호출 규약(messages.create(model=,max_tokens=,system=,messages=)·
    # models.list())은 AsyncAnthropic가 런타임에 충족하므로 스텁 정밀도 차이만 cast로
    # 좁힌다(타입 무시 X — ollama.py가 AsyncClient를, langfuse_sink.py가 Langfuse를 다룬 방식).
    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout=settings.anthropic_request_timeout_s,
    )
    return cast(_AnthropicClient, client)


class AnthropicProvider:
    """Anthropic Claude 클라우드 생성 제공자 — interfaces.LLMProvider 충족.

    라우터 결정의 축1(CLOUD_MID/CLOUD_HIGH)을 resolve_cloud_model()로 실제 모델 ID로
    바꿔 Anthropic으로 호출한다. 로컬(LOCAL) 결정은 명시적으로 거부한다(OllamaProvider 담당).

    클라이언트는 지연 생성(lazy)·주입 가능(injectable)하다 — 테스트는 가짜 클라이언트를
    `client=`로 넣고, 프로덕션은 키가 설정돼 있을 때 첫 호출에서 기본 AsyncAnthropic을
    생성한다(생성자/`create_app()`만으로는 키·네트워크가 필요 없도록). 키 미설정 시
    generate()는 *명확한 오류*를 던진다 — 라우터가 정당한 이유로 클라우드를 택했으므로
    조용한 LOCAL 강등은 하지 않는다(가용성보다 정확성이 먼저인 경로 — CLAUDE.md #3).
    """

    def __init__(
        self,
        *,
        client: _AnthropicClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        # 주입된 클라이언트가 있으면 그것을 쓰고, 없으면 키 설정 시 첫 사용에 지연 생성.
        self._client = client
        self._settings = settings

    @property
    def _resolved_settings(self) -> Settings:
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    @property
    def jurisdiction(self) -> Jurisdiction:
        """항상 `US` — Anthropic PBC는 미국 법인이다 (ARCH-49 관할 축).

        관할은 1차 법적 게이트(`l3.data_export_policy`)보다 좁히지 않는다 — 즉 이 경로에
        대해 관할 축은 아무 판정도 추가하지 않으며, 디스패치 동작은 종전과 같다. 그래도
        *선언*하는 이유는 기본값(`composite.DEFAULT_CLOUD_JURISDICTION`)에 기대지 않기
        위해서다: 기본값은 테스트 가짜를 위한 것이고, 프로덕션 좌석은 자기 관할을 말한다.
        """
        return Jurisdiction.US

    @property
    def configured(self) -> bool:
        """클라우드 생성 가능 여부 — 클라이언트가 주입됐거나 API 키가 있는가.

        주입된 클라이언트가 있으면(테스트·DI) 키 설정과 무관하게 활성으로 본다. 그 외에는
        Settings.anthropic_configured(키 존재)를 따른다. 네트워크를 타지 않고 내성만 한다.
        """
        if self._client is not None:
            return True
        return self._resolved_settings.anthropic_configured

    def _get_client(self) -> _AnthropicClient:
        """클라이언트 지연 해석 — 주입 우선, 키 설정 시 기본 생성, 미설정이면 오류.

        키 미설정은 *조용히 넘기지 않고* RuntimeError로 보고한다 — 클라우드 결정이
        내려졌는데 키가 없는 것은 설정 오류이며, 학생에게 잘못된 모델로 답하느니
        명확히 실패하는 편이 안전하다(CLAUDE.md "모르면 모른다고").
        """
        if self._client is not None:
            return self._client
        settings = self._resolved_settings
        if not settings.anthropic_configured:
            raise RuntimeError(
                "Anthropic API 키가 미설정이라 클라우드 생성을 할 수 없습니다 "
                "(라우터가 CLOUD_* 결정을 내렸으나 WHYMATH_ANTHROPIC_API_KEY 없음). "
                "키를 주입하거나, 클라우드 미사용 배포라면 "
                "CompositeProvider(cloud=None)로 구성하세요."
            )
        self._client = _build_default_client(settings)
        return self._client

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
        """라우터 결정에 따라 Anthropic Claude로 생성 (LLMProvider 구현).

        - CostTier.LOCAL이면 즉시 거부(로컬은 OllamaProvider 담당).
        - CLOUD_MID/CLOUD_HIGH는 resolve_cloud_model()로 실제 모델 ID(Sonnet/Opus)를 얻어
          plain messages.create로 호출한다(샘플링·thinking 인자 없음 — Opus 4.7 호환).
        - `images`가 주어지면 *명확한 오류*를 던진다 — 멀티모달은 로컬 Qwen3-VL 경유이며
          (미성년자 프라이버시·로컬-우선) 클라우드 비전은 미배선이다(조용한 무시 금지).
        - `temperature`(S2-g 생성 다양성)가 주어지면 messages.create의 `temperature=`로
          전달한다. None(기본)이면 온도를 싣지 않아 API 기본 온도를 쓴다 — *기존 동작 무변경*.
          ⚠️ 주의(모듈 docstring): **Opus 4.7(CLOUD_HIGH)는 temperature를 거부(400)**한다 —
          따라서 CLOUD_HIGH 경로로 가는 호출부는 temperature를 지정하지 말아야 한다. 동등문제
          저작(S2-g)은 라우팅상 LOCAL/CLOUD_MID로 흐르며 CLOUD_HIGH(killer/prove)로는 가지 않는다.
        - `json_schema`(S2-j structured output)가 주어지면 *명확한 오류*를 던진다 — plain
          messages.create에는 문법 제약 디코딩이 없어 스키마를 보장할 수 없다(조용한 무시 금지).
          호출부 계약: 클라우드 결정 경로에서는 json_schema를 지정하지 말고 프롬프트+관대 파서로
          동작해야 한다(동등문제 저작은 LOCAL 결정일 때만 스키마를 싣는다 — llm_generator._invoke).
        - `seed`(EOS-73 생성 재현)가 주어지면 *명확한 오류*를 던진다 — Anthropic Messages API에는
          **seed 파라미터 자체가 없다**(`messages.create(model, max_tokens, system, messages)` +
          temperature/thinking 등). 즉 이 경로의 seed는 정책 선택이 아니라 **구조적 불가**이며,
          조용히 무시하면 `GenerationLog.seed`에 "모델에 전달된 적 없는 숫자"가 남아 *재현
          가능하다고 거짓말하는 행*이 된다(날조 금지·EOS-55 정직 원칙 승계). 따라서 클라우드
          경로의 seed는 **NULL(미기록)로 유지**되고, 호출부는 `l3/generation_seed.seed_supported`
          가 True(=LOCAL)일 때만 seed를 싣는다(json_schema와 동일한 계약 형태).

        반환은 `GenerationResult(text, usage)` — text는 *검증 전 원시 출력*(모듈 docstring
        경계 메모), usage는 응답 usage(input/output_tokens) + monotonic 실측 지연(S1 게이트 ②).
        """
        if images:
            raise RuntimeError(
                "AnthropicProvider는 멀티모달(images) 입력을 지원하지 않습니다 — 비전 인식은 "
                "로컬 Qwen3-VL(VISION 패밀리) 경유입니다(클라우드 비전 미배선·미성년자 프라이버시)."
            )
        if seed is not None:
            raise RuntimeError(
                "AnthropicProvider는 seed(생성 재현 시드)를 지원하지 않습니다 — Anthropic Messages "
                "API에 seed 파라미터가 없어 구조적으로 전달 불가입니다. 클라우드 경로의 "
                "GenerationLog.seed는 NULL(미기록)이 정직한 값입니다(EOS-73·날조 금지). "
                "호출부는 generation_seed.seed_supported(decision)가 True일 때만 seed를 싣습니다."
            )
        if json_schema is not None:
            raise RuntimeError(
                "AnthropicProvider는 json_schema(문법 제약 디코딩)를 지원하지 않습니다 — plain "
                "messages.create에는 structured output 강제가 없어 스키마를 보장할 수 없습니다. "
                "클라우드 경로는 프롬프트+관대 파서로 동작하세요(조용한 무시 금지·S2-j)."
            )
        cost = _as_cost_tier(decision.cost_tier)
        if cost is CostTier.LOCAL:
            raise ValueError(
                f"AnthropicProvider는 클라우드 결정만 처리한다(받은 cost_tier={cost.value}). "
                "로컬 티어는 OllamaProvider 담당이다(03a §A.0)."
            )

        settings = self._resolved_settings
        model_id = resolve_cloud_model(cost, settings)
        # 선택적 튜닝 인자 — *설정된 경우에만* 키를 싣는다(기본 전부 OFF=현 동작, 03a §H#4).
        extra: dict[str, Any] = {}
        if settings.anthropic_effort:
            extra["output_config"] = {"effort": settings.anthropic_effort}
        if settings.anthropic_thinking:
            extra["thinking"] = {"type": "adaptive"}
        if settings.anthropic_prompt_caching:
            extra["cache_control"] = {"type": "ephemeral"}
        # S2-g 생성 다양성 — 온도 지정 시에만 싣는다(기본 미지정=현 동작). Opus 4.7은 temperature를
        # 거부하므로 CLOUD_HIGH 호출부는 지정하지 않는다(위 docstring ⚠️).
        if temperature is not None:
            extra["temperature"] = temperature

        # 지연 실측 — 호출을 monotonic으로 감싼다(추정 est_latency_ms와 구분되는 actual).
        start = time.monotonic()
        response = await self._get_client().messages.create(
            model=model_id,
            max_tokens=settings.anthropic_max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            **extra,
        )
        latency_ms = (time.monotonic() - start) * 1000.0
        return GenerationResult(
            text=_extract_text(response),
            usage=_extract_usage(response, latency_ms),
        )

    async def check_status(self) -> AnthropicStatus:
        """클라우드 구성 + 도달성(인증) 점검 (/status용).

        키 미설정이면 네트워크 없이 configured=False로 보고한다. 키가 있으면 models.list()
        로 도달성·인증을 확인하되, 실패(인증·네트워크)는 *흡수*하고 reachable=False로
        보고한다 — /status는 클라우드가 죽어 있어도 500을 던지지 않는다(ollama check_status
        와 동일한 비크래시 보고 패턴).
        """
        if not self.configured:
            return AnthropicStatus(configured=False, reachable=False, error=None)
        try:
            await self._get_client().models.list()
        except Exception as exc:  # noqa: BLE001 — 도달/인증 실패를 비크래시 상태로 흡수
            return AnthropicStatus(
                configured=True,
                reachable=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        return AnthropicStatus(configured=True, reachable=True, error=None)
