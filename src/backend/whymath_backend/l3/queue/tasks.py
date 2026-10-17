"""Celery 태스크 — QUALITY(27b) 비동기 생성 (M1.2-live S4).

QUALITY로 라우팅된 요청(03a §D.3)을 워커가 처리하는 실제 작업이다. 흐름:
  1. 파이프라인이 JSON payload(prompt·system·decision-as-dict)를 enqueue한다.
  2. 워커(동시성 1, GPU 단일 점유)가 이 태스크를 집어 payload에서 RoutingDecision을
     재구성하고, OllamaProvider.generate(QUALITY→qwen3.5:27b)를 실행한다.
  3. 생성 텍스트를 result backend에 저장 → 호출자가 job_id로 폴링한다.

asyncio 경계: Celery 태스크는 *동기* 함수다. OllamaProvider.generate는 async이므로
`asyncio.run(...)`으로 새 이벤트 루프에서 실행한다. 워커 프로세스는 동시성 1이라
태스크당 루프 1개만 돈다(루프 충돌 없음, 03a §D.3).

테스트 경계: 핵심 로직은 *플레인 함수* `run_quality_generation_payload`에 두고, Celery
태스크는 그 위의 얇은 래퍼다. 단위테스트는 broker 없이 플레인 함수를 직접 호출하며
가짜 provider를 주입한다(가짜 celery app 시임과 함께 CI hermetic 유지).

경계 메모 (CLAUDE.md 절대 금기): 이 태스크가 돌려주는 텍스트는 *검증 전 원시 모델
출력*이다 — QUALITY(27b)라 해도 03 문서 환각 방어 파이프라인(스키마→SymPy/Lean→PRM→
자기검증→사람검수)을 통과하기 전에는 학생에게 직접 노출 금지("LLM 응답을 검증 없이
학생에게 제공 금지"). 비동기 결과를 폴링한 상위 계층이 (게이트) 검증 책임을 진다.

shadow 관측 (slice 43): 워커는 결정론 검증기로 생성물을 검사해 *거짓 수치 관계* 등
환각 신호를 **로그로만** 남긴다(WARNING·비차단). 동기 파이프라인의 shadow 검증
(`pipeline.generate`, slice 40)을 비동기 워커로 확장한 것. 반환 텍스트는 *불변*
(게이트가 아니라 관측, CLAUDE.md "환각 발견 시 로그").

usage 계측 (S1 게이트 ②): 워커 태스크는 TraceSink(LangfuseSink — 미설정 시 자기 no-op)
를 주입받아 QUALITY 생성 완료의 실측 usage(토큰·지연)·cost_krw(=0.0 로컬)를 기록한다 —
종전엔 워커에 sink가 없어 로컬 QUALITY(27b) 경로가 관측 공백이었다. 비차단·never-break.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from whymath_backend.config import get_settings
from whymath_backend.l3.interfaces import LLMProvider, TraceSink
from whymath_backend.l3.models import RoutingDecision
from whymath_backend.l3.pregenerate.validator import (
    SeedValidator,
    default_seed_validator,
    validate_response,
)
from whymath_backend.l3.queue.celery_app import build_celery_app
from whymath_backend.l3.router import actual_cost_krw, langfuse_fields

if TYPE_CHECKING:  # pragma: no cover — 타입 체크 전용(런타임 import 회피)
    from celery import Celery

logger = logging.getLogger("whymath.l3.quality")

# 태스크 이름 — send_task로 디스패치할 때 쓰는 안정적 식별자(네임스페이스 고정).
# CeleryJobQueue가 이 이름으로 send_task를 호출하므로 *문자열 계약*으로 공유한다.
QUALITY_TASK_NAME = "whymath.l3.quality.generate"

# 워커 기본 shadow 검증기 — 결정론 관계 검증(=·<·>·≤·≥·≠). 모듈 import 시 1회 생성
# (I/O 없음·재사용). 등록된 태스크가 이 검증기로 비동기 생성물을 *로그 관측*한다.
_WORKER_SHADOW_VALIDATOR = default_seed_validator()

# payload 키 — 파이프라인(enqueue)과 태스크(소비)가 공유하는 JSON 스키마.
PAYLOAD_PROMPT = "prompt"
PAYLOAD_SYSTEM = "system"
PAYLOAD_DECISION = "decision"
PAYLOAD_TRAINING_ALLOWED = "training_allowed"


def _resolve_provider(provider: LLMProvider | None) -> LLMProvider:
    """생성 provider 해석 — 주입 우선, 없으면 기본 OllamaProvider 지연 생성.

    OllamaProvider는 *호출 시점에만* import한다(ollama 라이브러리 부재 환경에서도 이
    모듈 import가 깨지지 않도록 — 다른 시임들의 지연 import 패턴과 동일). 단위테스트는
    가짜 provider를 주입해 ollama·GPU 없이 태스크 로직을 검증한다.
    """
    if provider is not None:
        return provider
    from whymath_backend.l3.providers.ollama import OllamaProvider

    return OllamaProvider()


def run_quality_generation_payload(
    payload: dict[str, Any],
    *,
    provider: LLMProvider | None = None,
    validator: SeedValidator | None = None,
    trace: TraceSink | None = None,
) -> str:
    """QUALITY 생성 핵심 로직 (플레인 함수 — broker 없이 직접 테스트 가능).

    payload(JSON-safe dict)에서 prompt·system·decision을 꺼내 RoutingDecision을
    재구성하고, provider.generate로 QUALITY(qwen3.5:27b)를 실행한다. Celery 태스크는
    이 함수를 asyncio.run으로 감싼 래퍼다.

    Args:
        payload: `{prompt, system, decision}` — decision은 RoutingDecision.model_dump().
        provider: 생성 백엔드(테스트는 가짜 주입). None이면 OllamaProvider 지연 생성.
        validator: 런타임 shadow 검증기(L3 결정론 도구). 주입 시 생성물의 거짓 수치 관계
            등 환각 신호를 *로그로만* 남긴다(WARNING). **비차단** — 반환 텍스트는 원시
            출력 *그대로*(바이트 동일·계약 불변). 동기 파이프라인의 shadow 검증(slice 40)
            을 비동기 워커로 확장한 것(CLAUDE.md "환각 발견 시 로그"). None이면 검증
            미실행(오버헤드 0).
        trace: 관측성 싱크(S1 게이트 ② 워커 계측). 주입 시 생성 완료 후 실측 usage
            (토큰·지연)·cost_krw(로컬 QUALITY=0.0)를 record한다 — 동기 파이프라인의
            trace.record와 같은 langfuse_fields 스키마. **비차단** — sink 오류는 sink가
            삼킨다(LangfuseSink never-break). None이면 관측 미기록(종전 동작).

    Returns:
        생성된 *검증 전 원시 텍스트*(모듈 docstring 경계 메모 참조). validator가 신호를
        내도 텍스트는 차단·치환되지 않는다(게이트는 폴링 상위 계층·L4/L5 책임).

    Raises:
        KeyError/ValidationError: payload 스키마가 깨졌을 때(워커가 실패로 기록).
    """
    prompt = payload[PAYLOAD_PROMPT]
    system = payload[PAYLOAD_SYSTEM]
    decision_data = payload[PAYLOAD_DECISION]

    # decision dict → RoutingDecision 재구성. RoutingDecision은 use_enum_values=True라
    # model_dump()가 문자열 값을 내놓고, 재구성 시 검증기(불변식)를 다시 통과한다.
    decision = RoutingDecision.model_validate(decision_data)

    resolved = _resolve_provider(provider)
    # Celery 태스크는 동기 → async generate를 새 이벤트 루프에서 실행(동시성 1, 루프 1개).
    # provider 반환은 models.GenerationResult(text, usage) — 반환 계약(str)은 유지하고
    # usage(실측 토큰·지연)는 trace로 흘린다(S1 게이트 ② — 로컬 QUALITY 27b 관측 공백 보완).
    generated = asyncio.run(resolved.generate(prompt, system, decision))
    output = generated.text

    # 워커 계측(비차단) — enqueue 기록(pipeline)과 분리된 *생성 완료* 실측 기록.
    # QUALITY는 불변식상 LOCAL(27b)이라 cost_krw=0.0 확정 — usage가 없어도(미노출
    # provider) 비용은 확정 기록하고, 토큰·지연은 None으로 남긴다(지어내지 않음).
    if trace is not None:
        # OPS-116 — 좌석은 `seat=None`(미상)을 명시한다: LOCAL이면 좌석과 무관하게 0.0이고, 불변식이
        # 깨져 클라우드 결정이 들어와도 anthropic 단가로 접지 않고 '미측정'(None)으로 남는다.
        cost = (
            actual_cost_krw(decision, generated.usage, seat=None)
            if generated.usage is not None
            else 0.0
        )
        trace.record(
            langfuse_fields(
                decision,
                cache_hit=False,
                usage=generated.usage,
                cost_krw=cost,
                training_allowed=payload.get(PAYLOAD_TRAINING_ALLOWED),
            )
        )

    # 런타임 shadow 검증(비차단·로그 관측) — 비동기 생성물의 환각 신호를 조용히 넘기지 않는다.
    if validator is not None:
        signal = validate_response(validator, output)
        if signal is not None:
            logger.warning(
                "QUALITY 비동기 생성물 환각 신호 — %s (비차단·로그 관측, reason=%s)",
                signal.reason,
                decision.reason,
            )

    return output


def register_quality_task(app: Celery) -> Any:
    """Celery 앱에 QUALITY 태스크를 등록하고 태스크 객체를 반환한다.

    `@app.task` 데코레이터를 함수 호출형으로 적용한다 — 모듈 최상단에서 app을 만들지
    않기 위함(앱은 지연 생성이라 import 시 broker를 타지 않는다, 03a §D.3). 워커는
    celery_app의 include=[...tasks]로 이 모듈을 import하고, 아래 모듈 레벨 등록이
    실행돼 태스크가 등록된다.

    태스크 본체는 플레인 함수 `run_quality_generation_payload`에 위임한다(provider
    주입 없이 → 워커는 실제 OllamaProvider를 쓴다). 워커는 기본 shadow 검증기
    (`_WORKER_SHADOW_VALIDATOR`)를 함께 넘겨 비동기 생성물의 환각 신호를 *로그로* 남긴다
    (비차단·log-only이라 default-on이 안전). 활성 여부는 `Settings.
    l3_shadow_validation_enabled`로 게이트 — 비활성이면 validator=None(검증 미실행)·
    엔드포인트(`/v1/generate`)와 *같은 플래그*로 통제(태스크 실행 시점에 settings 조회).

    관측(S1 게이트 ②): 태스크는 `LangfuseSink`를 trace로 넘겨 QUALITY(27b) 생성 완료의
    실측 usage·cost_krw(=0.0 로컬)를 기록한다 — 종전엔 워커에 sink가 없어 로컬 QUALITY
    경로가 관측 공백이었다. 키 미설정이면 sink가 스스로 영구 no-op(자기비활성)이라
    default-on이 안전하다(never-break·hermetic).
    """

    # 무시 사유: celery는 py.typed를 제공하지 않아 `@app.task`가 mypy에 *untyped
    # 데코레이터*로 보여 데코레이트된 함수까지 untyped로 만든다(untyped-decorator).
    # 데코레이터 적용에는 cast가 끼어들 자리가 없어, 이 한 줄의 해당 코드만 좁게 무시한다
    # (다른 시임들이 cast로 좁힌 것과 동일한 방침 — celery 스텁 부재만 국소 처리). 본체
    # 로직은 검증된 플레인 함수에 위임하므로 타입 안전성 손실은 사실상 없다.
    @app.task(name=QUALITY_TASK_NAME, bind=False)  # type: ignore[untyped-decorator]
    def run_quality_generation(payload: dict[str, Any]) -> str:
        """워커 태스크 — payload로 QUALITY 생성(검증 전 원시 출력·shadow 신호 로그)."""
        # Settings 게이트: 비활성이면 검증기 미주입(검증 미실행). 태스크당 1회 조회(캐시).
        validator = (
            _WORKER_SHADOW_VALIDATOR if get_settings().l3_shadow_validation_enabled else None
        )
        # 관측 sink — 지연 import(langfuse 미설치 환경에서도 이 모듈 import는 hermetic).
        # 미설정이면 LangfuseSink가 스스로 no-op(자기비활성·오류 삼킴 — never-break).
        from whymath_backend.l3.trace.langfuse_sink import LangfuseSink

        return run_quality_generation_payload(payload, validator=validator, trace=LangfuseSink())

    return run_quality_generation


# 모듈 import 시 기본 앱에 태스크를 등록한다(워커가 include로 이 모듈을 로드할 때 실행).
# 앱 생성은 지연 import이며 broker에 연결하지 않으므로(첫 디스패치 때 연결) import는
# hermetic하다. celery 미설치 환경에서는 build_celery_app가 RuntimeError를 내지만,
# 그 경로는 워커 기동(celery 설치 전제)에서만 닿는다 — 단위테스트는 이 모듈을 import
# 하지 않고 플레인 함수만 직접 호출한다.
quality_celery_app = build_celery_app()
run_quality_generation = register_quality_task(quality_celery_app)
