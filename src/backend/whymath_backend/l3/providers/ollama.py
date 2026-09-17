"""Ollama 로컬 LLM 제공자 — interfaces.LLMProvider 구현 (M1.2-live S1).

라우터 결정(RoutingDecision)을 받아 Phaiakes9 로컬 Ollama 데몬으로 실제 생성을
수행한다. 로컬(CostTier.LOCAL) 결정만 처리하며, 클라우드는 범위 밖(S5)이다.

설계 정본: `docs/architecture/03a_l3_router_design.md` §A.0(모델 매트릭스)·§D.3(QUALITY
비동기 전용)·§A.1(벤치 지연). 테스트 주입 패턴은 infra/phaiakes9/benchmark/
bench_latency.py(`_OllamaClientProtocol` 경유 가짜 클라이언트 주입)를 미러링한다.

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
from whymath_backend.l3.router import (
    LOCAL_MODEL_MATRIX,
    QUALITY_MODEL_ID,
    _as_cost_tier,
    resolve_model,
)


# ──────────────────────────────────────────────────────────────────────────
# Ollama 클라이언트 추상화 (테스트 주입용) — bench_latency.py 패턴 미러링.
# 실제 `ollama.AsyncClient`와 동형이지만 테스트는 가짜 객체로 대체한다.
# ──────────────────────────────────────────────────────────────────────────
@runtime_checkable
class _OllamaClient(Protocol):
    """ollama 비동기 클라이언트의 최소 인터페이스 (구조적 타이핑).

    `ollama.AsyncClient`의 부분집합. `generate`는 단일 프롬프트 생성, `list`는
    설치된 모델 목록 조회. 반환 타입은 라이브러리 버전별로 dict 또는 pydantic
    객체일 수 있어 `Any`로 두고, 제공자 쪽에서 방어적으로 정규화한다.
    """

    async def generate(
        self,
        *,
        model: str,
        prompt: str,
        system: str,
        images: Sequence[str] | None = None,
        options: dict[str, Any] | None = None,
        format: Any = None,  # noqa: A002 — ollama API 인자명 그대로(JSON schema 제약 디코딩)
        stream: bool = False,
    ) -> Any:
        """단일 프롬프트 생성 (ollama generate API). `images`=멀티모달(VL) base64 목록.

        `format`은 structured output 제약(S2-j) — JSON 스키마 dict를 주면 Ollama가 출력을
        그 스키마에 맞는 JSON으로 문법 수준에서 제약한다(ollama 0.5+ 제약 디코딩).
        """
        ...

    async def list(self) -> Any:
        """설치된 모델 목록 조회 (ollama list API)."""
        ...


# ──────────────────────────────────────────────────────────────────────────
# /status 보고용 값 객체
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class ModelAvailability:
    """라우팅에 필요한 단일 로컬 모델의 설치 여부."""

    model_id: str
    present: bool


@dataclass(slots=True, frozen=True)
class OllamaStatus:
    """Ollama 준비 상태 보고 (/status 엔드포인트용).

    `reachable=False`면 데몬에 닿지 못한 것이며, 이는 *처리된 비크래시 상태*다
    (호출자는 503/ready=false로 보고하되 500을 던지지 않는다).
    """

    reachable: bool
    models: tuple[ModelAvailability, ...]
    error: str | None = None

    @property
    def all_present(self) -> bool:
        """라우팅 매트릭스의 모든 모델이 설치돼 있는가."""
        return self.reachable and all(m.present for m in self.models)

    @property
    def missing(self) -> tuple[str, ...]:
        """미설치 모델 ID 목록."""
        return tuple(m.model_id for m in self.models if not m.present)


# 라우팅이 실제로 요구하는 로컬 모델 ID 전체 = 매트릭스(FAST/MID) + QUALITY(MoE).
# 03a §A.0. /status가 이 집합의 설치 여부를 점검한다.
_REQUIRED_MODEL_IDS: tuple[str, ...] = (
    *sorted(set(LOCAL_MODEL_MATRIX.values())),
    QUALITY_MODEL_ID,
)


def _extract_model_names(list_response: Any) -> set[str]:
    """ollama list 응답에서 모델 이름 집합을 방어적으로 추출.

    ollama 버전에 따라 응답이 (a) pydantic `ListResponse`(`.models[*].model`),
    (b) dict(`{"models": [{"model"|"name": ...}]}`) 등으로 달라질 수 있어 양쪽을
    모두 흡수한다. 정규화 실패 시 빈 집합(닿았으나 비어 있음과 동일하게 취급).
    """
    raw_models: Any
    if hasattr(list_response, "models"):
        raw_models = list_response.models
    elif isinstance(list_response, dict):
        raw_models = list_response.get("models", [])
    else:
        return set()

    names: set[str] = set()
    for item in raw_models or []:
        name: Any = None
        if hasattr(item, "model"):
            name = item.model
        elif isinstance(item, dict):
            name = item.get("model") or item.get("name")
        if isinstance(name, str) and name:
            names.add(name)
    return names


def _extract_text(generate_response: Any) -> str:
    """ollama generate 응답에서 생성 텍스트를 방어적으로 추출.

    pydantic `GenerateResponse`(`.response`) 또는 dict(`{"response": ...}`)
    양쪽을 흡수한다. Qwen3 계열은 json_schema format 사용 시 출력을 `thinking` 필드에
    담고 `response`는 비어 있을 수 있어 `thinking`도 fallback으로 본다.
    """

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
    """usage 필드값을 int|None으로 방어적 정규화 — 비정상 타입·음수는 None(지어내지 않음)."""
    # bool은 int의 서브클래스지만 토큰 수가 아니다 — 배제.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _read_field(response: Any, name: str) -> Any:
    """generate 응답(pydantic 객체 또는 dict)에서 필드값을 방어적으로 읽는다."""
    if hasattr(response, name):
        return getattr(response, name)
    if isinstance(response, dict):
        return response.get(name)
    return None


def _extract_usage(generate_response: Any, latency_ms: float) -> Usage:
    """ollama generate 응답에서 실측 usage를 방어적으로 추출 (S1 게이트 ②).

    ollama 응답의 `prompt_eval_count`(입력 토큰)/`eval_count`(출력 토큰)를 포착한다.
    pydantic `GenerateResponse`·dict 양쪽을 흡수하고, 형태가 예상과 다르면 토큰은 None —
    *값을 지어내지 않는다*(_extract_text와 동일한 보수적 정규화). 지연(latency_ms)은
    호출부가 monotonic으로 잰 실측값을 그대로 싣는다. 로컬은 0원이라 비용 산정에는
    쓰이지 않지만, 토큰·지연 분포는 SLA·튜닝 근거가 된다(03a §F.2).
    """
    return Usage(
        input_tokens=_coerce_token_count(_read_field(generate_response, "prompt_eval_count")),
        output_tokens=_coerce_token_count(_read_field(generate_response, "eval_count")),
        latency_ms=latency_ms,
    )


def _build_default_client(settings: Settings) -> _OllamaClient:
    """기본 ollama AsyncClient 생성 (지연 import).

    `ollama` 라이브러리/데몬이 없는 환경(CI 단위테스트)에서도 모듈 import가 깨지지
    않도록 *호출 시점에만* import한다 (bench_latency.py 패턴). 라이브러리 미설치는
    명확한 RuntimeError로 보고한다.
    """
    try:
        from ollama import AsyncClient
    except ImportError as exc:  # pragma: no cover — 환경 의존(라이브러리 미설치)
        raise RuntimeError(
            "ollama Python 클라이언트가 설치되지 않았습니다. "
            "`pip install ollama` 후 다시 시도하세요."
        ) from exc
    # ollama AsyncClient는 timeout을 httpx로 전달한다(초 단위).
    #
    # cast 사유: ollama가 제공하는 정밀 overload 스텁(stream=Literal[False/True]별
    # 반환 타입)은 우리의 좁은 구조적 시임 `_OllamaClient`와 형태가 어긋난다. 우리가
    # 실제로 쓰는 호출 규약(generate(model=,prompt=,system=,stream=False)·list())은
    # AsyncClient가 런타임에 충족하므로, 스텁 정밀도 차이만 cast로 좁힌다(타입 무시 X).
    client = AsyncClient(
        host=settings.ollama_host,
        timeout=settings.ollama_request_timeout_s,
    )
    return cast(_OllamaClient, client)


class OllamaProvider:
    """로컬 Ollama 생성 제공자 — interfaces.LLMProvider 충족.

    라우터 결정의 (패밀리 축3 × 크기 축2)를 resolve_model()로 실제 모델 ID로 바꾼 뒤
    Ollama로 호출한다. 클라우드(CLOUD_*) 결정은 명시적으로 거부한다(S5 범위).

    클라이언트는 지연 생성(lazy)·주입 가능(injectable)하다 — 테스트는 가짜 클라이언트를
    `client=` 로 넣고, 프로덕션은 기본 AsyncClient를 첫 호출 때 생성한다.
    """

    def __init__(
        self,
        *,
        client: _OllamaClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        # 주입된 클라이언트가 있으면 그것을 쓰고, 없으면 첫 사용 시 기본 생성(지연).
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
        """항상 `DOMESTIC` — Phaiakes9 온프레미스라 국외 이전 자체가 없다 (ARCH-49 관할 축).

        디스패처의 관할 게이트는 클라우드 위임에만 선다(로컬은 반출이 아니다). 그래도
        선언하는 이유는 거버넌스 테스트가 `l3/providers/`의 모든 실제 제공자에 관할
        선언을 요구하기 때문이다 — "이 제공자는 어디 관할인가"에 답이 없는 좌석을 남기지
        않는다.
        """
        return Jurisdiction.DOMESTIC

    def _get_client(self) -> _OllamaClient:
        """클라이언트 지연 해석 — 주입 우선, 없으면 기본 AsyncClient 생성."""
        if self._client is None:
            self._client = _build_default_client(self._resolved_settings)
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
        """라우터 결정에 따라 로컬 Ollama로 생성 (LLMProvider 구현).

        - CostTier.LOCAL이 아니면 즉시 거부(클라우드는 S5 범위 밖).
        - LOCAL FAST/MID/QUALITY는 resolve_model()로 실제 모델 ID를 얻어 호출한다
          (QUALITY→qwen3:30b-a3b, 패밀리 무관; FAST/MID→매트릭스 lookup, 03a §A.0;
          VISION/FAST→qwen3-vl 멀티모달).
        - `images`(base64 목록)가 주어지면 ollama generate의 `images=`로 전달한다 —
          VL 모델(qwen3-vl)이 이미지를 받는다. None이면 기존 텍스트 호출과 동일.
        - `temperature`(S2-g 생성 다양성)가 주어지면 ollama generate의 `options=`에
          `{"temperature": ...}`로 실어 샘플링 온도를 올린다(동등문제 저작 mode collapse 방어).
          None(기본)이면 options에 온도를 넣지 않아 Ollama 기본 온도를 쓴다 — *기존 동작 무변경*.
        - `json_schema`(S2-j structured output)가 주어지면 ollama generate의 `format=`에
          스키마 dict를 그대로 실어 출력을 *문법 수준에서 제약*한다(제약 디코딩 — 자유 텍스트·
          코드펜스·필드 누락을 원천 차단). None(기본)이면 format을 싣지 않아 자유 텍스트 생성
          — *기존 동작 무변경*. 문법 제약은 형식만 보장하며 수학적 진실 검증은 하류 게이트 소관.
        - `seed`(EOS-73 생성 재현)가 주어지면 ollama generate의 `options=`에 시드를 실어
          llama.cpp 샘플러 시드를 고정한다 — **Ollama가 seed를 물리적으로 받는 유일한 경로**다
          (Anthropic Messages API에는 seed 파라미터가 없다·`l3/generation_seed` 경로별 표).
          None(기본)이면 시드를 싣지 않아 Ollama가 매 호출 임의 시드를 쓴다 — *기존 동작 무변경*.
          온도와 같은 options dict를 공유하므로 둘 다 주면 함께 실린다.
          경고: 시드 고정이 곧 출력 동일을 **보증하지는 않는다** — 배치 크기·컨텍스트 길이·양자화
          커널·서버 재시작에 따라 부동소수 누적 순서가 달라질 수 있다. "같은 seed → 같은 출력"이
          이 배포에서 실제로 성립하는지는 라이브 측정 대상이며(`harness/generation_seed_replay_
          probe`), 측정 전에는 *미측정*이지 성립이 아니다(EOS-73 acceptance ③ 자인).

        주의: QUALITY(MoE)의 *동기 디스패치 차단*은 파이프라인(pipeline.generate)의
        책임이다(03a §D.3). 제공자 자체는 모델 ID 해석·호출만 담당한다 —
        비동기 워커가 같은 제공자로 QUALITY를 호출할 수 있어야 하기 때문.

        반환은 `GenerationResult(text, usage)` — text는 *검증 전 원시 출력*(모듈 docstring
        경계 메모), usage는 prompt_eval_count/eval_count + monotonic 실측 지연(S1 게이트 ②).
        """
        cost = _as_cost_tier(decision.cost_tier)
        if cost is not CostTier.LOCAL:
            raise ValueError(
                f"OllamaProvider는 로컬 결정만 처리한다(받은 cost_tier={cost.value}). "
                "클라우드 티어는 S5 범위 밖이다(03a §H 후속 4)."
            )

        # (패밀리 × 크기) → 실제 Ollama 모델 ID. local_model이 None이면 resolve_model이
        # 명확히 오류를 던진다(불변식 1 위반은 RoutingDecision 검증에서 이미 차단됨).
        # VISION/FAST는 매트릭스에서 qwen3-vl로 해석된다(텍스트 패밀리와 동일 경로).
        model_id = resolve_model(decision.local_family, decision.local_model)

        # 선택 인자(images·temperature)는 *있을 때만* 호출 kwargs에 싣는다 — 텍스트 전용·온도
        # 미지정 하위 클라이언트(기존 가짜 시임)는 해당 인자 없이도 동작(하위호환). 멀티모달일
        # 때만 images=, 온도 지정 시에만 options={"temperature": ...}가 붙는다.
        call_kwargs: dict[str, Any] = {
            "model": model_id,
            "prompt": prompt,
            "system": system,
            "stream": False,
        }
        if images is not None:
            call_kwargs["images"] = images
        # options는 온도(S2-g)·시드(EOS-73)가 공유하는 단일 dict — 지정된 것만 담고, 아무것도
        # 지정되지 않으면 키 자체를 싣지 않는다(하위호환·기존 동작 무변경).
        options: dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = temperature
        if seed is not None:
            options["seed"] = seed
        if options:
            call_kwargs["options"] = options
        if json_schema is not None:
            # S2-j structured output — 스키마 dict를 format=으로 실어 제약 디코딩(ollama 0.5+).
            call_kwargs["format"] = dict(json_schema)
        client = self._get_client()
        # 지연 실측 — 호출을 monotonic으로 감싼다(추정 est_latency_ms와 구분되는 actual).
        start = time.monotonic()
        response = await client.generate(**call_kwargs)
        latency_ms = (time.monotonic() - start) * 1000.0
        return GenerationResult(
            text=_extract_text(response),
            usage=_extract_usage(response, latency_ms),
        )

    async def check_status(self) -> OllamaStatus:
        """Ollama 도달성 + 라우팅 모델 매트릭스 설치 여부 점검 (/status용).

        데몬에 닿지 못하면 예외를 *흡수*하고 `reachable=False`로 보고한다 —
        /status는 Ollama가 죽어 있어도 500을 던지지 않고 상태를 *보고*해야 한다.
        """
        try:
            list_response = await self._get_client().list()
        except Exception as exc:  # noqa: BLE001 — 도달 불가를 비크래시 상태로 흡수
            return OllamaStatus(
                reachable=False,
                models=tuple(
                    ModelAvailability(model_id=mid, present=False) for mid in _REQUIRED_MODEL_IDS
                ),
                error=f"{type(exc).__name__}: {exc}",
            )

        installed = _extract_model_names(list_response)
        return OllamaStatus(
            reachable=True,
            models=tuple(
                ModelAvailability(model_id=mid, present=mid in installed)
                for mid in _REQUIRED_MODEL_IDS
            ),
            error=None,
        )


class FixedModelOllamaProvider(OllamaProvider):
    """강등전·측정 전용 — 라우터가 고른 모델 대신 고정 모델 ID로 호출하는 Ollama provider.

    `OllamaProvider`를 상속해 `_get_client()`·`_extract_*` 로직을 재사용하고,
    `generate()`에서만 `resolve_model()`을 건너뛰어 `--model-id` 인자로 들어온 ID를
    직접 Ollama에 넘긴다. 이를 통해 운영 라우터 매트릭스와 무관하게 특정 모델의
    정확도·지연을 측정한다(CLAUDE.md "측정·수집 도구를 성공 경로만 보고 설계 금지" —
    실패·오류 경로도 동일한 provider 인터페이스로 처리).

    `timeout`·`num_ctx`·`num_predict`는 강등전에 필요한 긴 타임아웃·컨텍스트 제한·
    출력 길이 제한을 주입하기 위한 것이다. 모두 선택 인자 — 미지정 시 Ollama 기본값.
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
        super().__init__(client=client, settings=settings)
        self._model_id = model_id
        self._num_ctx = num_ctx
        self._num_predict = num_predict

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
        """고정 모델 ID로 생성한다 — `resolve_model`을 생략한다(그 외는 부모와 동일)."""
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
        if images is not None:
            call_kwargs["images"] = images
        options: dict[str, Any] = {}
        if self._num_ctx is not None:
            options["num_ctx"] = self._num_ctx
        if self._num_predict is not None:
            options["num_predict"] = self._num_predict
        if temperature is not None:
            options["temperature"] = temperature
        if seed is not None:
            # EOS-73 — 강등전에서도 시드 고정 재현이 가능해야 한다(부모와 같은 options 좌석).
            options["seed"] = seed
        if options:
            call_kwargs["options"] = options
        if json_schema is not None:
            call_kwargs["format"] = dict(json_schema)
        client = self._get_client()
        start = time.monotonic()
        response = await client.generate(**call_kwargs)
        latency_ms = (time.monotonic() - start) * 1000.0
        return GenerationResult(
            text=_extract_text(response),
            usage=_extract_usage(response, latency_ms),
        )
